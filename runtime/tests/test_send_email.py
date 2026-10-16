"""Tests of sending an e-mail from the project's outbox as an external effect (runtime/step_send_email.py, runtime/send_document.py,
runtime/effect_send.py, runtime/ops_step_effects.py, the provider providers/mailer/smtp.py; package EMAIL-SEND). The mail service is a fake SMTP
server and a fake IMAP server on loopback (providers/mailer/tests/fake_mail.py): no mail service is ever called, no credential is real, every
address is on `.example`. The provider runs as the process the runtime starts, with the minimum environment. The cases of the spec's "Done
when": a send without the approval of its exact content is refused by structure; one with it goes out once, to exactly the recipients of the
document, and records; a changed attachment stops it and asks again; a lost answer is `unknown`, and approving again looks in the Sent folder.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_send_email.py
"""
from __future__ import annotations

import ast
import datetime
import hashlib
import importlib.util
import json
import os
import shutil
import sys
from pathlib import Path

import pytest

import standin_tree as st

sys.path.insert(0, str(st.REPO / "providers" / "mailer" / "tests"))
import fake_mail  # noqa: E402  (providers/mailer/tests/fake_mail.py: the fake servers)

lab = st.load("lab")
ops = st.load("ops")
ops_core = st.load("ops_core")
ops_steps = st.load("ops_steps")
effects = st.load("effects")
effect_send = st.load("effect_send")
send_document = st.load("send_document")
mail_address = st.load("mail_address")
ops_step_effects = st.load("ops_step_effects")
ops_step_seams = st.load("ops_step_seams")
step_send_email = st.load("step_send_email")
project_config = st.load("project_config")
flow_files = st.load("flow_files")
steps = st.load("steps")


def _by_path(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


smtp = _by_path("smtp_under_runtime_test", st.REPO / "providers" / "mailer" / "smtp.py")
email_helpers = _by_path("email_helpers_under_runtime_test", st.REPO / "providers" / "_email.py")

PASSWORD = "app-password-x"  # security-scan: allow secret-assignment -- a made-up password for a fake server on loopback; no real account has it
FROM = "outbox@office.example"
PATH = "docs/outputs/invoice.pdf"
PDF = b"%PDF-1.4 the october invoice"
SUBJECT = "Your invoice for October"
BODY = "Hello Ana,\n\nThe invoice for October is below.\n\nBest regards,\nThe office\n"
ARGS = {"to": "ana@client.example", "subject": SUBJECT, "body": BODY}


def sha(data):
    return hashlib.sha256(data if isinstance(data, bytes) else data.encode("utf-8")).hexdigest()


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("WB_LOCAL_EVIDENCE_DIR", str(tmp_path / "evidence"))
    built = st.build(tmp_path, monkeypatch, lab)
    tree = built["tree"]
    for rel in ("providers/mailer/smtp.py", "providers/_email.py", "providers/secrets/resolver.py", "providers/secrets/password_managers.py"):
        (tree / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(st.REPO / rel, tree / rel)
    (tree / "flows").mkdir(exist_ok=True)
    shutil.copyfile(st.REPO / "flows" / "send-email.json", tree / "flows" / "send-email.json")
    state = tmp_path / "mail-state"
    state.mkdir()
    os.chmod(state, 0o700)
    monkeypatch.setenv("OPENHORA_STATE_DIR", str(state))
    monkeypatch.setenv("OPENHORA_MAIL_TEST_PLAIN", "1")
    monkeypatch.setenv("MAILER_SMTP_PASSWORD", PASSWORD)
    monkeypatch.setenv("MAILER_SMTP_TIMEOUT", "5")
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    server, imap = fake_mail.FakeSmtp(PASSWORD), fake_mail.FakeImap(PASSWORD)
    assert smtp.main(["setup", "--from", FROM, "--smtp-host", "127.0.0.1", "--smtp-port", str(server.port), "--smtp-security", "plain",
                      "--imap-host", "127.0.0.1", "--imap-port", str(imap.port), "--sent-folder", "Sent"]) == 0
    path = built["project"] / "docs" / "workbench" / "runtime.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["outbox"] = {"provider": "auto", "from": FROM}
    path.write_text(json.dumps(raw), encoding="utf-8")
    monkeypatch.setattr(ops_core, "ROOT", str(tree))
    resolver = project_config.resolver(str(tree))      # the test variables reach the provider the runtime starts
    monkeypatch.setattr(resolver, "ENV_MINIMUM", resolver.ENV_MINIMUM + ("OPENHORA_MAIL_TEST_PLAIN", "MAILER_SMTP_TIMEOUT"))
    monkeypatch.setattr(project_config, "resolver", lambda workbench: resolver)      # one resolver module for the step seam and the effect
    project = str(built["project"])
    ops.accept_config(project, ops.project_config.load(project)["sha256"])
    (built["project"] / "docs" / "outputs").mkdir(parents=True)
    (built["project"] / PATH).write_bytes(PDF)
    yield {**built, "path": project, "smtp": server, "imap": imap, "tmp": tmp_path, "state": state}
    server.stop()
    imap.stop()


def add(world, args=None, **extra):
    ctx = ops_core.context(world["path"])
    made = steps.add_task(ctx["store"], ctx["conn"], "send-email", {**(args or ARGS), **extra}, key="send", title="Send the e-mail", text="Send it.")
    return made["task"]


def run_task(world, task):
    ctx = ops_core.context(world["path"])
    if ctx["store"].task_get(ctx["conn"], task)["state"] == "failed":
        ctx["store"].task_retry(ctx["conn"], task)
    return ops_steps.run_step(world["path"], task)


def pending_of(world, task):
    ctx = ops_core.context(world["path"])
    rows = [p for p in ctx["store"].pending_list(ctx["conn"], "open", task)]
    assert len(rows) == 1, rows
    return rows[0]


def task_state(world, task):
    ctx = ops_core.context(world["path"])
    return ctx["store"].task_get(ctx["conn"], task)["state"]


def opened(world, args=None, **extra):
    task = add(world, args, **extra)
    out = run_task(world, task)
    assert out["ok"] is True and out["task_state"] == "waiting", out
    return task, pending_of(world, task)


def effect_doc(world, task):
    cfg = ops_core.context(world["path"])["cfg"]
    return json.loads((Path(ops_step_effects.effect_dir(cfg, task, 0)) / "effect.json").read_text(encoding="ascii"))


def approve(world, item, channel="terminal"):
    return ops.approve(world["path"], item["id"], sha256=item["payload_sha256"], channel=channel)


def sent(world):
    return world["smtp"].messages


# --- what the person is shown ------------------------------------------------------------------------------------------------------------


def test_the_task_opens_an_effect_with_the_hash_of_the_whole_message_and_sends_nothing(world):
    task, item = opened(world, cc="bo@client.example", bcc="dee@client.example")
    assert item["kind"] == "effect" and len(item["payload_sha256"]) == 64 and item["payload"]["step"] == {"kind": "send-email", "step": "send"}
    assert sent(world) == [] and world["smtp"].connections == 0 and world["smtp"].logins == [], "preparing sends nothing and logs in nowhere"
    body = item["body"]
    for needle in (FROM, "ana@client.example", "bo@client.example", "dee@client.example", SUBJECT, BODY.rstrip("\n"), item["payload_sha256"],
                   "approve", "--sha256", "Bcc", "Recipients in all: 3"):
        assert needle in body, needle
    order = [body.index(x) for x in ("From:", "To:", "Cc:", "Bcc", "Subject:", "the message, exactly as it will be sent")]
    assert order == sorted(order), "the recipients come first, before the text"
    assert "dee@client.example" not in json.dumps(item["payload"]) and BODY not in json.dumps(item["payload"]), "the state keeps counts and hashes"
    assert item["payload"]["effect"]["recipients"] == 3 and item["payload"]["effect"]["bcc"] == 1


def test_the_hash_is_the_hash_of_the_effect_file_which_holds_every_recipient_the_key_and_the_providers_preview(world):
    task, item = opened(world, cc="bo@client.example", bcc="dee@client.example")
    cfg = ops_core.context(world["path"])["cfg"]
    path = Path(ops_step_effects.effect_dir(cfg, task, 0)) / "effect.json"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == item["payload_sha256"] and oct(path.stat().st_mode & 0o777) == "0o600"
    for folder in (path.parent, path.parent.parent, path.parent.parent.parent):
        assert oct(folder.stat().st_mode & 0o777) == "0o700", folder
    doc = effect_doc(world, task)
    assert doc["effect"] == "send" and doc["from"] == FROM and doc["provider"] == "smtp"
    assert doc["to"] == ["ana@client.example"] and doc["cc"] == ["bo@client.example"] and doc["bcc"] == ["dee@client.example"]
    assert doc["subject"] == SUBJECT and doc["body"] == BODY and doc["body_sha256"] == sha(BODY) and doc["attachments"] == []
    assert doc["idempotency_key"].startswith("send-") and len(doc["idempotency_key"]) == 37
    assert doc["message_id"] == f"<oh.{sha(doc['idempotency_key'])[:32]}@office.example>"
    assert len(doc["dry_run_sha256"]) == 64 and doc["dry_run_sha256"] != "0" * 64


def test_a_different_recipient_is_a_different_hash_and_a_different_key_so_one_approval_covers_one_message(world):
    base = dict(task_id=1, provider="smtp", from_addr=FROM, to=["ana@client.example"], cc=[], bcc=[], subject=SUBJECT, body=BODY, in_reply_to=None,
                attachments=[], dry_run_sha256="1" * 64)
    a = send_document.document(**base)
    b = send_document.document(**{**base, "bcc": ["dee@client.example"]})
    c = send_document.document(**{**base, "to": ["ana@client.example", "bo@client.example"]})
    d = send_document.document(**{**base, "task_id": 2})
    digests = [sha(effects._text(x)) for x in (a, b, c, d)]
    assert len(set(digests)) == 4 and len({x["idempotency_key"] for x in (a, b, c, d)}) == 4
    approval = {"scope": "action", "status": "pending-execution", "payload_sha256": digests[0]}
    with pytest.raises(effects.EffectError) as refused:
        effect_send.execute(b, approval, lambda verb, args: pytest.fail("the provider was called"), b["idempotency_key"])
    assert refused.value.kind == "deviation" and "no approval of this exact content" in refused.value.reason


def test_an_effect_file_edited_after_the_preview_is_not_the_approved_one_and_nothing_is_sent(world):
    task, item = opened(world)
    cfg = ops_core.context(world["path"])["cfg"]
    path = Path(ops_step_effects.effect_dir(cfg, task, 0)) / "effect.json"
    doc = json.loads(path.read_text(encoding="ascii"))
    doc["bcc"] = ["mal@client.example"]
    path.write_text(json.dumps(doc, sort_keys=True, indent=1) + "\n", encoding="ascii")
    with pytest.raises(ops_core.OpsError) as refused:
        approve(world, item)
    assert "not the one approved" in str(refused.value) and "nothing was sent" in str(refused.value)
    assert sent(world) == [] and world["smtp"].connections == 0 and task_state(world, task) == "waiting"


# --- the approval ---------------------------------------------------------------------------------------------------------------------------


def test_limit_42_a_send_without_the_approval_of_its_exact_content_is_refused_by_structure(world):
    task, item = opened(world)
    for channel in ("messaging", "mcp", "conversation", None):
        with pytest.raises(ops_core.OpsError) as refused:
            ops.approve(world["path"], item["id"], sha256=item["payload_sha256"], channel=channel)
        assert "approved in the terminal" in str(refused.value), channel
    with pytest.raises(ops_core.OpsError):
        ops.approve(world["path"], item["id"], sha256=None, channel="terminal")
    with pytest.raises(ops_core.OpsError) as refused:
        ops.approve(world["path"], item["id"], sha256="0" * 64, channel="terminal")
    assert "nothing was approved" in str(refused.value)
    with pytest.raises(ops_core.OpsError):
        ops.answer(world["path"], item["id"], "approve")      # a word typed into a conversation is no approval either
    assert sent(world) == [] and world["smtp"].connections == 0
    doc = effect_doc(world, task)
    for approval in (None, {}, {"scope": "plan", "status": "pending-execution", "payload_sha256": item["payload_sha256"]},
                     {"scope": "action", "status": "revoked", "payload_sha256": item["payload_sha256"]},
                     {"scope": "action", "status": "pending-execution", "payload_sha256": "0" * 64}):
        with pytest.raises(effects.EffectError):
            effect_send.execute(doc, approval, lambda verb, args: pytest.fail("the provider was called"), doc["idempotency_key"])
    assert sent(world) == []


def test_a_standing_approval_never_covers_a_send_and_the_seam_for_a_messaging_grant_is_named(world, monkeypatch):
    monkeypatch.setattr(ops_core, "ROOT", str(st.REPO))      # the vocabulary of side effects is read from the checkout's scripts/validate.py
    assert effects.KINDS["send"] == "effect_send"
    kind = effects.module_for("send")
    assert kind.POLICY is False and kind.GATE is False and kind.STEP is True and kind.PROVIDER_CLASS == "sender:email"
    assert "send" not in effects.policy_kinds() and "send" not in ops._bounds_words()
    assert effects.gate_kind("send", ["sender:email"]) is None, "no skill's gate can name it"
    assert kind.APPROVAL_GROUP == "approve-effect-send" and kind.on_cards({"attachments": []}) is True
    assert kind.on_cards({"attachments": [{"name": "a.pdf"}]}) is False and kind.is_long({"attachments": [{}]}) is True
    assert "send" in ops._effect_words(), "the word is in the vocabulary of side effects"
    operations = st.load("operations")      # no group of today's policy lets a messaging app approve it; POL-1 adds kind.APPROVAL_GROUP
    assert "terminal" in operations.EFFECT_CHANNELS and "page" in operations.EFFECT_CHANNELS
    assert not {"messaging", "mcp", "chat"} & set(operations.EFFECT_CHANNELS)


@pytest.mark.parametrize("channel", ["terminal", "page"])
def test_limit_42_with_the_approval_of_its_hash_from_the_terminal_or_the_page_it_is_sent_once_to_exactly_the_recipients_and_recorded(world, channel):
    task, item = opened(world, cc="Bo@Client.Example", bcc="dee@client.example")
    done = approve(world, item, channel)
    assert done["task_state"] == "done" and done["result"]["sent"] is True and done["result"]["replayed"] is False
    assert done["result"]["recipients"] == 3 and done["result"]["bytes"] == len(BODY.encode())
    assert len(sent(world)) == 1
    [taken] = sent(world)
    assert taken["from"] == FROM and taken["to"] == ["ana@client.example", "Bo@client.example", "dee@client.example"]
    text = taken["data"].decode("utf-8", errors="replace")
    assert "Bcc" not in text and "dee@client.example" not in text, "the Bcc is in the envelope only"
    assert f"Message-ID: {effect_doc(world, task)['message_id']}" in text and "Subject: Your invoice for October" in text
    assert task_state(world, task) == "done"
    ctx = ops_core.context(world["path"])
    row = ctx["store"].approval_get(ctx["conn"], done["approval_id"])
    assert row["status"] == "executed" and row["scope"] == "action" and row["payload_sha256"] == item["payload_sha256"]
    settled = ctx["store"].pending_get(ctx["conn"], item["id"])
    assert settled["status"] == "resolved" and settled["resolution"] == "approved" and settled["payload"]["result"]["sent"] is True
    assert "ana@client.example" not in json.dumps(settled["payload"]), "the record keeps no address"
    with pytest.raises(ops_core.OpsError):
        approve(world, item, channel)
    assert len(sent(world)) == 1
    assert list((world["tmp"] / "data").glob("openhora-send-*")) == [], "the private copies are removed"


def test_the_state_file_gets_the_generated_row_of_the_executed_approval(world):
    task, item = opened(world)
    done = approve(world, item)
    text = (Path(world["path"]) / "docs" / "workbench" / "state.md").read_text(encoding="utf-8")
    assert done["state"]["written"] is True and f"sha256:{item['payload_sha256']}" in text and "send an e-mail from" in text and "executed" in text
    assert "ana@client.example" not in text, "the row names the sender and a count, not the recipients"


def test_a_rejected_send_cancels_the_task_and_sends_nothing(world):
    task, item = opened(world)
    ops.reject(world["path"], item["id"], "not now")
    assert task_state(world, task) == "cancelled" and sent(world) == [] and world["smtp"].connections == 0


def test_the_same_document_approved_again_is_replayed_not_sent_twice(world):
    task, item = opened(world)
    doc = effect_doc(world, task)
    approval = {"scope": "action", "status": "pending-execution", "payload_sha256": item["payload_sha256"]}
    cfg = ops_core.context(world["path"])["cfg"]
    call = effect_send.caller(cfg, ops_core.ROOT)
    first = effect_send.execute(doc, approval, call, doc["idempotency_key"], str(world["tmp"]), project=cfg["project"])
    second = effect_send.execute(doc, approval, call, doc["idempotency_key"], str(world["tmp"]), project=cfg["project"])
    assert first["replayed"] is False and second["replayed"] is True and len(sent(world)) == 1
    assert world["smtp"].connections == 1, "the second one did not even connect"


# --- the attachments ------------------------------------------------------------------------------------------------------------------------


def test_an_attachment_is_a_private_copy_of_the_file_the_task_read_and_travels_with_its_name(world):
    task, item = opened(world, attach=[PATH])
    doc = effect_doc(world, task)
    assert doc["attachments"] == [{"path": PATH, "name": "invoice.pdf", "media_type": "application/pdf", "bytes": len(PDF), "sha256": sha(PDF)}]
    assert f"invoice.pdf: {len(PDF)} bytes, sha256 {sha(PDF)}" in item["body"] and "not on this card" in item["body"]
    assert effect_send.on_cards(doc) is False and effect_send.is_long(doc) is True
    approve(world, item)
    import email
    import email.policy
    [attached] = list(email.message_from_bytes(sent(world)[0]["data"], policy=email.policy.default).iter_attachments())
    assert attached.get_filename() == "invoice.pdf" and attached.get_content() == PDF


def test_limit_42_an_attachment_changed_after_the_preview_stops_the_send_and_asks_again_about_the_file_as_it_is(world):
    task, item = opened(world, attach=[PATH])
    (Path(world["path"]) / PATH).write_bytes(PDF + b" and a changed line")
    with pytest.raises(ops_core.OpsError) as stopped:
        approve(world, item)
    assert "is not the file the task read" in str(stopped.value) and "starts over" in str(stopped.value)
    assert sent(world) == [] and world["smtp"].connections == 0
    ctx = ops_core.context(world["path"])
    old = ctx["store"].pending_get(ctx["conn"], item["id"])
    assert old["status"] == "resolved" and old["resolution"] == "answered" and task_state(world, task) == "ready"
    assert ctx["store"].approval_get(ctx["conn"], 1)["status"] == "revoked"
    out = run_task(world, task)
    assert out["ok"] is True and out["task_state"] == "waiting"
    new = pending_of(world, task)
    assert new["payload_sha256"] != item["payload_sha256"] and sha(PDF + b" and a changed line") in new["body"]
    assert approve(world, new)["task_state"] == "done" and len(sent(world)) == 1
    with pytest.raises(ops_core.OpsError):
        approve(world, item)


def test_an_attachment_that_became_a_link_or_vanished_is_stale_too(world):
    task, item = opened(world, attach=[PATH])
    (Path(world["path"]) / PATH).unlink()
    (Path(world["path"]) / PATH).symlink_to(Path(world["path"]) / "AGENTS.md")
    with pytest.raises(ops_core.OpsError) as stopped:
        approve(world, item)
    assert "is not the file the task read" in str(stopped.value) and sent(world) == []


def test_an_attachment_that_is_missing_a_link_or_in_the_sources_folder_opens_no_effect(world):
    root = Path(world["path"])
    task = add(world, attach=["docs/outputs/missing.pdf"])
    assert run_task(world, task)["code"] == "attachment_missing"
    (root / "docs" / "real.pdf").write_bytes(PDF)
    (root / "docs" / "outputs" / "link.pdf").symlink_to(root / "docs" / "real.pdf")
    other = add(world, attach=["docs/outputs/link.pdf"])
    assert run_task(world, other)["code"] == "path_unsafe"
    ctx = ops_core.context(world["path"])
    assert ctx["store"].pending_list(ctx["conn"], "open", task) == [] and sent(world) == []


# --- the lost answer ------------------------------------------------------------------------------------------------------------------------


def test_limit_42_a_lost_answer_is_unknown_the_effect_stays_open_and_approving_again_looks_in_the_sent_folder_first(world):
    task, item = opened(world)
    world["smtp"].drop_after_data = True
    with pytest.raises(ops_core.OpsError) as lost:
        approve(world, item)
    assert "may or may not have been sent" in str(lost.value) and "Sent folder" in str(lost.value)
    assert task_state(world, task) == "waiting" and len(sent(world)) == 1
    ctx = ops_core.context(world["path"])
    assert ctx["store"].pending_get(ctx["conn"], item["id"])["status"] == "open"
    world["smtp"].drop_after_data = False
    connections = world["smtp"].connections
    with pytest.raises(ops_core.OpsError) as still:      # not in the Sent folder: blocked, and no second connection
        approve(world, item)
    assert "Sent folder" in str(still.value) and world["smtp"].connections == connections and len(sent(world)) == 1
    world["imap"].message_ids["Sent"] = {effect_doc(world, task)["message_id"]: 4}
    done = approve(world, item)
    assert done["task_state"] == "done" and done["result"]["replayed"] is True
    assert len(sent(world)) == 1 and world["smtp"].connections == connections


def test_limit_42_a_recipient_the_server_refuses_sends_nothing_names_the_address_and_leaves_the_effect_open(world):
    task, item = opened(world, args={**ARGS, "to": "ana@client.example, bo@client.example"})
    world["smtp"].refuse.add("bo@client.example")
    with pytest.raises(ops_core.OpsError) as refused:
        approve(world, item)
    assert "bo@client.example" in str(refused.value) and "nothing was sent" in str(refused.value)
    assert sent(world) == [] and task_state(world, task) == "waiting"
    ctx = ops_core.context(world["path"])
    assert ctx["store"].pending_get(ctx["conn"], item["id"])["status"] == "open"
    world["smtp"].refuse.clear()
    assert approve(world, item)["task_state"] == "done" and len(sent(world)) == 1


def test_a_provider_that_would_render_another_message_than_the_one_previewed_sends_nothing(world, monkeypatch):
    task, item = opened(world)
    real = effect_send.caller

    def tampered(cfg, root):
        call = real(cfg, root)

        def wrapper(verb, args):
            out = call(verb, args)
            if "--dry-run" in args:
                out = {**out, "would_sha256": "f" * 64}
            return out
        return wrapper
    monkeypatch.setattr(effect_send, "caller", tampered)
    with pytest.raises(ops_core.OpsError) as refused:
        approve(world, item)
    assert "something other than the e-mail that was previewed" in str(refused.value) and sent(world) == [] and world["smtp"].connections == 0


# --- the configuration -----------------------------------------------------------------------------------------------------------------------


def test_the_project_needs_an_outbox_that_names_the_documents_sender_and_a_provider_that_resolves(world):
    task, item = opened(world)
    path = Path(world["path"]) / "docs" / "workbench" / "runtime.json"
    original = path.read_text(encoding="utf-8")

    def change(**outbox):
        raw = json.loads(original)
        if outbox is None:
            raw.pop("outbox")
        else:
            raw["outbox"] = outbox
        path.write_text(json.dumps(raw), encoding="utf-8")
        ops.accept_config(world["path"], ops.project_config.load(world["path"])["sha256"])

    change(provider="auto", **{"from": "someone.else@office.example"})
    with pytest.raises(ops_core.OpsError) as refused:
        approve(world, item)
    assert "sender is not the one the e-mail was prepared for" in str(refused.value) and refused.value.code == 1 and sent(world) == []
    raw = json.loads(original)
    raw.pop("outbox")
    path.write_text(json.dumps(raw), encoding="utf-8")
    ops.accept_config(world["path"], ops.project_config.load(world["path"])["sha256"])
    with pytest.raises(ops_core.OpsError) as refused:
        approve(world, item)
    assert "no outbox configured" in str(refused.value) and refused.value.code == 3 and sent(world) == []
    path.write_text(original, encoding="utf-8")
    ops.accept_config(world["path"], ops.project_config.load(world["path"])["sha256"])
    assert approve(world, item)["task_state"] == "done" and len(sent(world)) == 1


def test_the_outbox_key_is_closed_and_its_sender_is_a_plain_address(world, tmp_path):
    for bad in ({"from": "Ana <ana@client.example>"}, {"from": FROM, "extra": 1}, {"provider": "auto"}, {"provider": "nowhere", "from": FROM},
                {"provider": "auto", "from": ""}, "outbox@office.example", ["a"]):
        path = Path(world["path"]) / "docs" / "workbench" / "runtime.json"
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw["outbox"] = bad
        path.write_text(json.dumps(raw), encoding="utf-8")
        with pytest.raises(project_config.ConfigError):
            project_config.load(world["path"])
    path = Path(world["path"]) / "docs" / "workbench" / "runtime.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["outbox"] = {"from": "Outbox@Office.Example"}
    path.write_text(json.dumps(raw), encoding="utf-8")
    assert project_config.load(world["path"])["outbox"] == {"provider": "auto", "from": "Outbox@office.example"}
    assert "outbox" in project_config.TASK_RUNTIME_KEYS


def test_a_project_without_an_outbox_cannot_prepare_an_e_mail(world):
    path = Path(world["path"]) / "docs" / "workbench" / "runtime.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw.pop("outbox")
    path.write_text(json.dumps(raw), encoding="utf-8")
    ops.accept_config(world["path"], ops.project_config.load(world["path"])["sha256"])
    task = add(world)
    out = run_task(world, task)
    assert out["ok"] is False and out["code"] == "not_configured" and world["smtp"].connections == 0


# --- what stops it before the effect is opened ---------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("args", [
    {}, {"to": "ana@client.example"}, {"to": "ana@client.example", "subject": SUBJECT}, {"subject": SUBJECT, "body": BODY},
    {**ARGS, "to": "Ana <ana@client.example>"}, {**ARGS, "to": "ana@client.example\nBcc: mal@client.example"},
    {**ARGS, "to": "ana@client.example; bo@client.example"}, {**ARGS, "to": "none"}, {**ARGS, "to": ""},
    {**ARGS, "cc": "ana@client.example"}, {**ARGS, "bcc": "ANA@client.example"},
    {**ARGS, "subject": "Hello\nBcc: mal@client.example"}, {**ARGS, "subject": "x" * 201}, {**ARGS, "subject": ""},
    {**ARGS, "subject": "=?utf-8?b?SGkNClJlcGx5LVRvOiB0aGllZkBldmlsLmV4YW1wbGUNCg0KUGF5IHRvIDk5OQ==?="}, {**ARGS, "subject": " padded "},
    {**ARGS, "to": "=?utf-8?q?ceo?=@client.example"}, {**ARGS, "cc": "=?utf-8?q?ceo?=@client.example"}, {**ARGS, "to": "ana@stra\u00dfe.example"},
    {**ARGS, "in_reply_to": "<=?utf-8?q?x?=@client.example>"},
    {**ARGS, "body": ""}, {**ARGS, "body": "x" * (send_document.BODY_MAX + 1)}, {**ARGS, "body": "a\x00b"}, {**ARGS, "body": "a\x1bb"},
    {**ARGS, "to": ", ".join(f"p{i}@client.example" for i in range(21))},
    {**ARGS, "to": ", ".join(f"p{i}@client.example" for i in range(15)), "cc": ", ".join(f"q{i}@client.example" for i in range(6))},
    {**ARGS, "extra": 1}, {**ARGS, "in_reply_to": "not an id"}, {**ARGS, "in_reply_to": "<a b@c.example>"},
    {**ARGS, "attach": "docs/a.pdf"}, {**ARGS, "attach": ["other/a.pdf"]}, {**ARGS, "attach": ["docs/../a.pdf"]}, {**ARGS, "attach": ["docs/a.exe"]},
    {**ARGS, "attach": ["docs/a.md.comments.md"]}, {**ARGS, "attach": ["docs/a.pdf", "docs/b/a.pdf"]}, {**ARGS, "attach": ["docs/x.pdf"] * 11},
    {**ARGS, "attach": [3]}, {**ARGS, "to": 5}])
def test_the_arguments_are_checked_when_the_task_is_planned(args):
    with pytest.raises(steps.StepFailure) as refused:
        steps.plan_task("send-email", args, key="k", title="t", text="x")
    assert refused.value.code == "bad_args"


def test_the_arguments_are_normalised_so_the_plans_hash_covers_the_addresses_as_they_will_be_used():
    planned = steps.plan_task("send-email", {"to": " Ana@Client.Example ,bo@client.example", "cc": "none", "subject": SUBJECT, "body": BODY},
                              key="k", title="t", text="x")
    assert planned["args"] == {"to": "Ana@client.example, bo@client.example", "subject": SUBJECT, "body": BODY}
    assert steps.plan_task("send-email", {**ARGS, "cc": "bo@client.example", "attach": ["docs/a.pdf"]}, key="k", title="t",
                           text="x")["args"]["attach"] == ["docs/a.pdf"]


def test_a_subject_or_body_that_holds_a_credential_opens_no_effect_and_the_key_is_not_echoed(world):
    key = "sk-" + "ant-" + "api03-" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6"
    for args in ({**ARGS, "body": f"The key: {key}\n"}, {**ARGS, "subject": f"Key {key}"}):
        task = add(world, args)
        out = run_task(world, task)
        assert out["ok"] is False and out["code"] == "content_refused" and key not in json.dumps(out)
        ctx = ops_core.context(world["path"])
        assert ctx["store"].pending_list(ctx["conn"], "open", task) == []
    assert world["smtp"].connections == 0


def test_the_flow_from_a_request_to_an_e_mail_that_is_sent_once_after_two_approvals(world, monkeypatch):
    monkeypatch.setattr(st.load("plan"), "resolve_pack", lambda pack, root: sorted(p.name for p in (Path(root) / "skills").iterdir()))
    request = ops.request(world["path"], "Send Ana her October invoice")["request"]
    opened = ops.route(world["path"], request, flow="send-email",
                       params=["to=ana@client.example, bo@client.example", "subject=" + SUBJECT, "body=" + BODY, "cc=dee@client.example"])
    plan = ops.approve(world["path"], opened["pending_id"])
    [made] = plan["tasks"]
    assert made["key"] == "send" and sent(world) == []
    out = run_task(world, made["id"])
    assert out["ok"] is True and out["task_state"] == "waiting"
    item = pending_of(world, made["id"])
    assert "dee@client.example" in item["body"] and "bo@client.example" in item["body"] and BODY.rstrip("\n") in item["body"]
    assert approve(world, item)["task_state"] == "done"
    [taken] = sent(world)
    assert taken["to"] == ["ana@client.example", "bo@client.example", "dee@client.example"]
    ctx = ops_core.context(world["path"])
    assert ctx["store"].task_get(ctx["conn"], made["id"])["state"] == "done"


def test_the_flow_fills_the_step_and_a_cc_of_none_is_no_one(world):
    loaded = flow_files.load("send-email")
    now = datetime.datetime(2026, 10, 16, 9, 0, tzinfo=datetime.timezone.utc)
    bound = flow_files.bind(loaded, {"to": "ana@client.example, bo@client.example", "subject": SUBJECT, "body": BODY}, now)["flow"]
    [task] = bound["tasks"]
    assert task["step"] == "send-email" and task["args"]["cc"] == "none" and task["args"]["to"] == "ana@client.example, bo@client.example"
    planned = steps.plan_task(task["step"], task["args"], key=task["key"], title=task["title"], text=task["text"])
    assert "cc" not in planned["args"] and planned["args"]["subject"] == SUBJECT
    assert set(loaded["params"]) == {"to", "cc", "subject", "body"} and loaded["params"]["cc"]["default"] == "none"


# --- the structure ----------------------------------------------------------------------------------------------------------------------------


def test_the_shared_approval_names_no_platform_and_no_provider():
    tree = ast.parse((st.REPO / "runtime" / "ops_step_effects.py").read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert not imported & {"documents", "board", "project_config", "effect_write", "effect_send", "send_document", "write_document",
                           "output_document"}, imported
    for kind in ("write", "send"):
        module = effects.module_for(kind)
        assert module.STEP is True and callable(module.preflight) and callable(module.caller) and callable(module.idempotency_key), kind


def test_the_outbox_service_a_step_kind_is_given_has_a_dry_run_and_no_way_to_send():
    reader = ops_step_seams.OutboxReader({"outbox": {"provider": "auto", "from": FROM}}, str(st.REPO))
    assert {name for name in dir(reader) if not name.startswith("_")} == {"enabled", "sender", "provider", "dry_run"}
    source = (st.REPO / "runtime" / "ops_step_seams.py").read_text(encoding="utf-8")
    assert "--confirmed" not in source and '"--dry-run"' in source
    assert reader.enabled() is True and reader.sender() == FROM
    assert ops_step_seams.OutboxReader({}, str(st.REPO)).enabled() is False


def test_the_dry_run_a_step_gets_opens_no_connection_and_reads_no_secret(world, monkeypatch):
    monkeypatch.delenv("MAILER_SMTP_PASSWORD")
    task, item = opened(world, cc="bo@client.example")
    assert world["smtp"].connections == 0 and world["imap"].connections == 0 and world["smtp"].logins == []
    assert effect_doc(world, task)["dry_run_sha256"] != "0" * 64


ADDRESSES = ["ana@client.example", "Ana.B+tag@Client.Example", "ana@Bücher.Example", "o'neil@sub.client.example", "", " ana@client.example", "ana",
             "ana@client", "ana@@client.example", "Ana <ana@client.example>", "ana@client.example\r\nBcc: x@y.example", "\"ana\"@client.example",
             "añá@client.example", "ana..b@client.example", "-x@client.example", "x" * 65 + "@client.example", "ana@-client.example",
             "ana@" + "a" * 64 + ".example", "ana@client.example, bo@client.example", "ana@[127.0.0.1]"]


@pytest.mark.parametrize("address", ADDRESSES)
def test_the_runtimes_address_rule_is_the_providers(address):
    def runtime():
        try:
            return mail_address.normalize_address(address)
        except mail_address.AddressError:
            return None

    def provider():
        try:
            return email_helpers.normalize_address(address)
        except email_helpers.EmailError:
            return None
    assert runtime() == provider()


def test_the_limits_and_the_derived_names_of_the_runtime_are_the_providers():
    assert send_document.RECIPIENTS_MAX == smtp.MAX_RECIPIENTS and send_document.BODY_MAX == smtp.BODY_MAX
    assert send_document.ATTACH_TOTAL_MAX == smtp.ATTACH_TOTAL_MAX and send_document.MEDIA_TYPES == email_helpers.MEDIA_TYPES
    assert send_document.REFERENCE.pattern == email_helpers.REFERENCE.pattern and send_document.MESSAGE_ID.pattern == email_helpers.MESSAGE_ID.pattern
    assert send_document.ATTACHMENT_NAME.pattern == email_helpers.ATTACHMENT_NAME.pattern
    assert mail_address.LOCAL_PART.pattern == email_helpers.LOCAL_PART.pattern and mail_address.LABEL.pattern == email_helpers.LABEL.pattern
    for key in ("send-0123456789abcdef0123456789abcdef", "send-fedcba9876543210fedcba9876543210"):
        assert send_document.message_id_of(key, FROM) == email_helpers.message_id("office.example", key)
    for name in ("report.pdf", "Plan October.xlsx"):
        assert send_document.attachment_name(name) == email_helpers.attachment_name(name)
        assert send_document.media_type(name) == email_helpers.media_type(name)
    for bad in ("../a.pdf", "a.exe", "a", ".pdf", "a..pdf", "x" * 101 + ".pdf"):
        with pytest.raises(effects.EffectError):
            send_document.attachment_name(bad)
        with pytest.raises(email_helpers.EmailError):
            email_helpers.attachment_name(bad)
    assert mail_address.split_list("Ana@Client.Example, bo@client.example") == ["Ana@client.example", "bo@client.example"]
    assert mail_address.split_list("none") == [] and mail_address.split_list("  ") == []
    with pytest.raises(mail_address.AddressError):
        mail_address.split_list("ana@client.example, ")


def test_a_lone_carriage_return_in_the_text_is_written_as_a_line_feed_so_the_hash_and_the_message_agree(world):
    planned = steps.plan_task("send-email", {**ARGS, "body": "Pay to account 111\rPay to account 999\r\nBest\n"}, key="k", title="t", text="x")
    assert planned["args"]["body"] == "Pay to account 111\nPay to account 999\nBest\n"
    base = dict(task_id=1, provider="smtp", from_addr=FROM, to=["ana@client.example"], cc=[], bcc=[], subject=SUBJECT, in_reply_to=None, attachments=[],
                dry_run_sha256="1" * 64)
    with pytest.raises(effects.EffectError):
        send_document.document(**base, body="one\rtwo\n")
    task, item = opened(world, body="one\rtwo\n")
    assert effect_doc(world, task)["body"] == "one\ntwo\n"
    approve(world, item)
    assert b"one\r\ntwo" in sent(world)[0]["data"] and b"one\r\r\ntwo" not in sent(world)[0]["data"]


def test_an_encoded_word_cannot_reach_the_wire_through_the_runtime(world):
    sneaky = "=?utf-8?b?" + __import__("base64").b64encode(b"Hi\r\nReply-To: thief@evil.example\r\n\r\nPay to 999").decode() + "?="
    with pytest.raises(steps.StepFailure):
        add(world, subject=sneaky)
    with pytest.raises(steps.StepFailure):
        add(world, to="=?utf-8?q?ceo?=@client.example")
    assert world["smtp"].connections == 0 and sent(world) == []


def test_every_send_is_made_under_the_decision_lock_and_not_the_write_lock_so_a_cancel_cannot_close_it_midway(world, monkeypatch):
    import threading
    task, item = opened(world)
    cfg = ops_core.context(world["path"])["cfg"]
    assert effect_send.is_long(effect_doc(world, task)) is True and effect_send.is_long({"attachments": []}) is True
    real = effect_send.caller
    seen = {}

    def watching(cfg_, root):
        call = real(cfg_, root)

        def wrapper(verb, args):
            if "--confirmed" in args:      # the send itself is running
                for name, attempt in (("reject", lambda: ops.reject(world["path"], item["id"], "changed my mind")),
                                      ("answer", lambda: ops.answer(world["path"], item["id"], "rather not"))):
                    try:
                        attempt()
                        seen[name] = "accepted"
                    except ops_core.OpsError as e:
                        seen[name] = str(e)

                def other_writer():
                    try:
                        with ops_core._write_lock(cfg, wait=0.3):
                            seen["write_lock"] = "free"
                    except ops_core.OpsError:
                        seen["write_lock"] = "held"
                thread = threading.Thread(target=other_writer)
                thread.start()
                thread.join()
            return call(verb, args)
        return wrapper
    monkeypatch.setattr(effect_send, "caller", watching)
    done = approve(world, item)
    assert "being written" in seen["reject"] and "being written" in seen["answer"], seen
    assert seen["write_lock"] == "free", "the project's write lock is not held while the e-mail is sent"
    assert done["task_state"] == "done" and len(sent(world)) == 1
    ctx = ops_core.context(world["path"])
    settled = ctx["store"].pending_get(ctx["conn"], item["id"])
    assert settled["status"] == "resolved" and settled["resolution"] == "approved", "the record of the send was made"
    text = (Path(world["path"]) / "docs" / "workbench" / "state.md").read_text(encoding="utf-8")
    assert f"sha256:{item['payload_sha256']}" in text, "and the state row"


def test_an_ordinary_long_pt_br_subject_is_prepared_approved_and_arrives_as_written(world):
    subject = "reuni\u00e3o fatura pr\u00f3xima 100% aten\u00e7\u00e3o reuni\u00e3o Paulo reuni\u00e3o"
    task, item = opened(world, subject=subject)
    assert subject in item["body"]
    approve(world, item)
    import email
    import email.policy
    assert email.message_from_bytes(sent(world)[0]["data"], policy=email.policy.default)["Subject"] == subject


def test_a_refusal_of_the_provider_at_prepare_says_what_to_do(world, monkeypatch):
    task = add(world)
    monkeypatch.setattr(ops_step_seams.OutboxReader, "dry_run", lambda self, doc, blobs: (_ for _ in ()).throw(
        ops_step_seams.StepServiceError("refused", "the subject could not be encoded exactly")))
    out = run_task(world, task)
    assert out["ok"] is False and out["code"] == "refused" and "shorten or simplify the subject" in json.dumps(out)
