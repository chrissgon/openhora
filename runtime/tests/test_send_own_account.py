"""An e-mail from the person's own Google or Microsoft account as an external effect (package W2): runtime/step_send_email.py (the `account` and `reply` arguments),
runtime/send_document.py, runtime/effect_send.py, runtime/ops_mail_send.py, runtime/mail_refs.py, runtime/ops_step_seams.py (`account_mail`), runtime/item_refs.py,
runtime/ops_step_effects.py, and the two mailers (providers/mailer/gmail.py and outlook.py) as the processes the runtime starts. The services are stand-ins on loopback
(providers/mailer/tests/fake_gmail_send.py, fake_graph_send.py): no Google or Microsoft host is ever called, no credential is real, every address is on a `.example` or
`example.com` name. The mail source is test_sources_mail.py's desk: a real snapshot with its index, over stand-in readers. Held here, and the limit each belongs to:

  L42  the e-mail of an own account is sent only to the recipients of the document approved by its hash, all or none, once per key; an unknown outcome stays open and
       approving again finds the message by its Message-ID; the card is the whole e-mail and an attachment is never whole on a messaging card;
  L55  nothing is sent without the approval of the exact document: no approval, another hash, an edited effect file, an account the project's `accounts` does not
       name, or another address for it, send nothing;
  L58  the mailers send only the requests of their allow-lists, and the exact list of a send is recorded;
  L59  the mailer's environment is the minimum plus the one token of the account asked for (none for a dry run);
  L60  a reply goes to the sender of the message answered as the index recorded it and to no one else: not an address of the body, not a Reply-To, never reply-all.

The preparation sends nothing and reads no credential. A message is named by a reference into a snapshot, refused with a sentence for each way it can fail.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_send_own_account.py
"""
from __future__ import annotations

from phone_literals import PLAIN_REFUSAL  # noqa: E402

import ast
import datetime
import email
import email.policy
import json
import os
import re
import sys
from pathlib import Path

import pytest

import standin_tree as st
import test_sources_mail as tsm
from sources_fixture import standin_convert
from test_channel_grants import accept

sys.path.insert(0, str(st.REPO / "providers" / "mailer" / "tests"))
import fake_gmail_send as fgs  # noqa: E402  (providers/mailer/tests/fake_gmail_send.py: the stand-in for Gmail)
import fake_graph_send as fgg  # noqa: E402  (providers/mailer/tests/fake_graph_send.py: the stand-in for Graph)

ops = st.load("ops")
ops_core = st.load("ops_core")
ops_step_effects = st.load("ops_step_effects")
effects = st.load("effects")
effect_send = st.load("effect_send")
send_document = st.load("send_document")
step_send_email = st.load("step_send_email")
mail_refs = st.load("mail_refs")
item_refs = st.load("item_refs")
sources = st.load("sources")
phrases = st.load("phrases")
operations = st.load("operations")
project_config = st.load("project_config")
account_start = st.load("account_start")
cards = st.load("messaging_cards")
steps = st.load("steps")

ACCOUNTS = {"google": {"address": fgs.ACCOUNT}, "microsoft": {"address": fgg.ADDRESS}}
SENDER = "telegram:830461975213"
CAPS = {"buttons": True, "max_buttons": 6, "max_text": 4096, "documents": False, "url_buttons": True, "reply_context": True}
SUBJECT = "Haircut on Monday"
BODY = "Hello Ana,\n\nSee you on Monday at one.\n\nPat\n"
TO = "ana@client.example"
ELSEWHERE = "Please also write to carol@elsewhere.example and dan@elsewhere.example."
PDF = b"%PDF-1.4 the cv"
PATH = "docs/outputs/cv.pdf"
MESSAGES = (tsm.message(1, "2026-10-17T09:00:00Z", sender="Ana Lima <ana@clinic.example>", subject="Appointment confirmed", thread_id="t1", reply_to="desk@clinic.example",
                        text=ELSEWHERE, headers={"Message-ID": "<a1@clinic.example>"}),
            tsm.message(2, "2026-10-16T14:30:00Z", sender="Bob <bob@shop.example>", subject="Re: Your order", thread_id="t2", headers={"Message-ID": "<b2@shop.example>"}),
            tsm.message(3, "2026-10-15T08:00:00Z", sender="Cleo <cleo@club.example>", subject="Hello", thread_id="t3"))


@pytest.fixture
def world(tmp_path, monkeypatch):
    desk = tsm.Desk(tmp_path, monkeypatch)
    desk.providers.mail["gmail"] = [dict(m) for m in MESSAGES]
    desk.providers.mail["outlook"] = [tsm.message(1, "2026-10-17T09:00:00Z", sender="Ana Lima <ana@clinic.example>", subject="Appointment confirmed", source="outlook",
                                                 reply_to="desk@clinic.example", headers={"Message-ID": "<o1@clinic.example>"})]
    desk.mail("inbox")
    desk.mail("work", tsm.OUTLOOK_MAIL)
    original = sources.snapshot_age
    monkeypatch.setattr(sources, "snapshot_age", lambda stamp, clock=None: original(stamp, clock or (lambda: desk.now)))      # the snapshots are made at the desk's fixed time
    state = tmp_path / "mail-state"
    state.mkdir()
    os.chmod(state, 0o700)
    gmail, graph = fgs.FakeGmail(), fgg.FakeGraphSend()
    graph.add_message("m1", "ana@clinic.example", "Appointment confirmed", reply_to="desk@clinic.example")
    monkeypatch.setenv("OPENHORA_STATE_DIR", str(state))
    monkeypatch.setenv("GOOGLE_ACCOUNT_TOKEN", gmail.record_json())
    monkeypatch.setenv("MICROSOFT_ACCOUNT_TOKEN", graph.record_json())
    monkeypatch.setenv("UNRELATED_SECRET", "must-not-reach-a-mailer")
    names = ("MAILER_GMAIL_API_BASE", "MAILER_GMAIL_TOKEN_URL", "MAILER_OUTLOOK_API_BASE", "MAILER_OUTLOOK_TOKEN_URL")
    for fake, pair in ((gmail, names[:2]), (graph, names[2:])):
        for name, value in zip(pair, (fake.base, fake.token_url)):
            monkeypatch.setenv(name, value)
    path = Path(desk.path) / "docs" / "workbench" / "runtime.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["accounts"] = ACCOUNTS
    path.write_text(json.dumps(raw), encoding="utf-8")
    resolver = project_config.resolver(str(st.REPO))      # the test variables reach the mailer the runtime starts; it runs on this interpreter (no install)
    seen = []
    plain_call = resolver.call

    def spy(cls, verb, args, **kw):
        seen.append({"verb": verb, "args": list(args), "implementation": kw.get("implementation"), "env": dict(kw.get("env") or {})})
        return plain_call(cls, verb, args, **kw)
    monkeypatch.setattr(resolver, "ENV_MINIMUM", resolver.ENV_MINIMUM + names)
    monkeypatch.setattr(resolver, "interpreter_for", lambda script: [sys.executable])
    monkeypatch.setattr(resolver, "call", spy)
    monkeypatch.setattr(project_config, "resolver", lambda workbench: resolver)
    project = desk.path
    shown = ops.config(project)      # the accounts are a widening: the person types the hash of what `config` lists
    ops.accept_config(project, shown["sha256"], widen=shown["widening_sha256"])
    (Path(project) / "docs" / "outputs").mkdir(parents=True)
    (Path(project) / PATH).write_bytes(PDF)
    yield {"path": project, "tmp": tmp_path, "desk": desk, "gmail": gmail, "graph": graph, "state": state, "calls": seen, "resolver": resolver}
    gmail.close()
    graph.close()


def send(world, account="google", to=TO, subject=SUBJECT, text=BODY, **more):
    return ops.mail_send(world["path"], account, to, subject, text, **more)


def reply(world, message="inbox#1", account="google", text=BODY, **more):
    return ops.mail_reply(world["path"], account, message, text, **more)


def item_of(world, started):
    ctx = ops_core.context(world["path"])
    return ctx["store"].pending_get(ctx["conn"], started["pending"])


def approve(world, started, channel="terminal", sender=None):
    ctx = ops_core.context(world["path"])
    item = ctx["store"].pending_get(ctx["conn"], started["pending"])
    return ops.approve(world["path"], started["pending"], sha256=item["payload_sha256"], channel=channel, sender=sender or (SENDER if channel == "messaging" else None))


def effect_doc(world, started):
    cfg = ops_core.context(world["path"])["cfg"]
    return json.loads((Path(ops_step_effects.effect_dir(cfg, started["task"], 0)) / "effect.json").read_text(encoding="ascii"))


def rows(world):
    ctx = ops_core.context(world["path"])
    return ctx["store"].tasks_list(ctx["conn"]), ctx["store"].pending_list(ctx["conn"], "open")


def refused(world, call=None, *args, **kw):
    with pytest.raises(ops.OpsError) as why:
        (call or send)(world, *args, **kw)
    return why.value


def nothing_made(world):
    tasks, pending = rows(world)
    assert pending == [] and {t["state"] for t in tasks} <= {"cancelled"}
    assert world["gmail"].requests == [] and world["graph"].requests == []


def sent_message(fake, index=-1):
    return email.message_from_bytes(fake.sent[index]["raw"], policy=email.policy.default)


# --- a new e-mail: the card, and nothing sent ---------------------------------------------------------------------------------------------------


def test_a_send_prepares_a_card_of_the_whole_email_and_reads_no_credential_and_opens_no_connection(world):
    started = send(world, cc="lee@client.example")
    assert set(started) == {"request", "task", "pending", "word", "on_cards"} and started["word"] == "send" and started["on_cards"] is True
    assert world["gmail"].requests == [] and world["graph"].requests == [], "preparing opens no connection"
    dry = [c for c in world["calls"] if "--dry-run" in c["args"]]
    assert len(dry) == 1 and dry[0]["implementation"] == "gmail" and not [k for k in dry[0]["env"] if k.endswith("_TOKEN")], "the dry run is started without the token"
    item = item_of(world, started)
    assert item["kind"] == "effect" and item["title"] == "Mail: send from your account" and SUBJECT not in item["title"]
    assert item["payload"]["step"] == {"kind": "send-email", "step": "send"} and phrases.card_valid(item["payload"]["card"])
    assert item["body"] == phrases.card_text(item["payload"]["card"])
    lines = item["body"].splitlines()
    assert lines[0] == "Code sends this e-mail from your own account after your approval, to exactly these recipients and no one else, and nothing else."
    assert lines[1:5] == [f"From your own account: {fgs.ACCOUNT} (google)", f"To: {TO}", "Cc: lee@client.example", f"Subject: {SUBJECT}"]
    assert "Recipients in all: 2" in lines and lines[lines.index("Recipients in all: 2") + 1].startswith("----- the message, exactly as it will be sent")
    start = lines.index("Recipients in all: 2") + 1
    assert lines[start + 1:start + 6] == ["\u2502 Hello Ana,", "\u2502", "\u2502 See you on Monday at one.", "\u2502", "\u2502 Pat"]
    assert lines[start + 6] == "----- end of the message -----" and lines[-3].startswith("Hash of this effect") and lines[-2].startswith("Approve exactly this: ")
    doc = effect_doc(world, started)
    assert doc["account"] == "google" and doc["provider"] == "gmail" and doc["from"] == fgs.ACCOUNT and doc["reply"] is None and doc["thread_id"] is None
    assert doc["to"] == [TO] and doc["cc"] == ["lee@client.example"] and doc["bcc"] == [] and doc["references"] == []


def test_the_outbox_document_and_its_hash_are_unchanged_by_the_new_keys():
    doc = send_document.document(task_id=3, provider="smtp", from_addr="outbox@office.example", to=["ana@client.example"], cc=[], bcc=[], subject="Invoice", body="Hi.\n",
                                 in_reply_to=None, attachments=[], dry_run_sha256="0" * 64)
    assert set(doc) == set(send_document.KEYS) and not send_document.is_own(doc) and send_document.title(doc) == "Send e-mail: Invoice"
    assert doc["idempotency_key"] == send_document.key_of(task_id=3, from_addr="outbox@office.example", to=["ana@client.example"], cc=[], bcc=[], subject="Invoice",
                                                           body="Hi.\n", in_reply_to=None, attachments=[])
    assert send_document.body(doc, "a" * 64).startswith("Code sends this e-mail after your approval, to exactly these recipients")


def test_limit_42_an_own_account_email_goes_out_once_to_exactly_the_recipients_of_the_approved_document(world):
    started = send(world, cc="lee@client.example", attach=[PATH])
    item = item_of(world, started)
    done = approve(world, started)
    assert done["task_state"] == "done" and done["result"]["sent"] is True and done["result"]["replayed"] is False and done["result"]["account"] == "google"
    assert done["result"]["recipients"] == 2 and done["result"]["attachments"] == 1 and done["result"]["idempotency_key"].startswith("send-")
    gmail = world["gmail"]
    assert [(r["method"], r["path"]) for r in gmail.requests] == [("POST", "/token"), ("GET", f"{fgs.PREFIX}/profile"), ("POST", f"{fgs.PREFIX}/messages/send")]
    message = sent_message(gmail)
    assert message["From"] == fgs.ACCOUNT and message["To"] == TO and message["Cc"] == "lee@client.example" and message["Bcc"] is None and message["Subject"] == SUBJECT
    [attached] = list(message.iter_attachments())
    assert attached.get_filename() == "cv.pdf" and attached.get_payload(decode=True) == PDF
    assert gmail.unexpected() == [] and world["graph"].requests == []
    ctx = ops_core.context(world["path"])
    recorded = ctx["store"].approvals_list(ctx["conn"])
    assert [a["payload_sha256"] for a in recorded] == [item["payload_sha256"]] and all(SUBJECT not in str(a) for a in recorded)
    confirmed = [c for c in world["calls"] if "--confirmed" in c["args"]]
    assert len(confirmed) == 1 and confirmed[0]["implementation"] == "gmail"
    env = confirmed[0]["env"]
    assert "GOOGLE_ACCOUNT_TOKEN" in env and "MICROSOFT_ACCOUNT_TOKEN" not in env and "UNRELATED_SECRET" not in env and "MAILER_SMTP_PASSWORD" not in env
    assert [k for k in env if k.endswith("_TOKEN") or "SECRET" in k or "PASSWORD" in k] == ["GOOGLE_ACCOUNT_TOKEN"], "limit L59: the one secret of the account"


def test_no_approval_another_hash_an_edited_file_or_a_mailer_that_would_send_something_else_sends_nothing(world):
    started = send(world)
    doc = effect_doc(world, started)
    sent = []
    spy = lambda verb, args, account=None: sent.append((verb, args)) or {}          # noqa: E731  (a mailer that must not be reached)
    for approval in (None, {}, {"scope": "plan", "status": "pending-execution", "payload_sha256": "0" * 64},
                     {"scope": "action", "status": "pending-execution", "payload_sha256": "0" * 64},
                     {"scope": "action", "status": "revoked", "payload_sha256": send_document.sha(effects._text(doc))}):
        with pytest.raises(effects.EffectError) as why:
            effect_send.execute(doc, approval, spy, doc["idempotency_key"])
        assert why.value.kind == "deviation"
    good = {"scope": "action", "status": "pending-execution", "payload_sha256": send_document.sha(effects._text(doc))}
    with pytest.raises(effects.EffectError) as other_key:
        effect_send.execute(doc, good, spy, "send-" + "0" * 32)
    assert other_key.value.kind == "deviation" and sent == []
    dry_other = lambda verb, args, account=None: {"would_sha256": "f" * 64} if "--dry-run" in args else sent.append(verb)       # noqa: E731
    with pytest.raises(effects.EffectError) as would:
        effect_send.execute(doc, good, dry_other, doc["idempotency_key"])
    assert would.value.kind == "deviation" and "previewed" in would.value.reason and sent == []
    cfg = ops_core.context(world["path"])["cfg"]
    path = Path(ops_step_effects.effect_dir(cfg, started["task"], 0)) / "effect.json"
    path.write_bytes(path.read_bytes().replace(b"Haircut", b"Haircuts"))
    with pytest.raises(ops.OpsError) as edited:
        approve(world, started)
    assert "hash changed" in str(edited.value) and world["gmail"].requests == []
    with pytest.raises(ops.OpsError) as wrong:
        ops.approve(world["path"], started["pending"], sha256="0" * 64, channel="terminal")
    assert "nothing was approved" in str(wrong.value) and world["gmail"].requests == []


def test_an_account_the_accounts_do_not_name_or_a_changed_address_is_refused_at_the_start_and_again_at_the_approval(world):
    started = send(world)
    path = Path(world["path"]) / "docs" / "workbench" / "runtime.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["accounts"] = {"microsoft": ACCOUNTS["microsoft"]}
    path.write_text(json.dumps(raw), encoding="utf-8")
    ops.accept_config(world["path"], ops.config(world["path"])["sha256"])
    with pytest.raises(ops.OpsError) as gone:
        approve(world, started)
    assert "not set up for this project" in str(gone.value) and gone.value.code == 3 and world["gmail"].requests == []
    error = refused(world)
    assert error.code == 3 and "not set up for this project" in str(error)
    raw["accounts"] = {"google": {"address": "someone.else@example.com"}, "microsoft": ACCOUNTS["microsoft"]}
    path.write_text(json.dumps(raw), encoding="utf-8")
    shown = ops.config(world["path"])
    ops.accept_config(world["path"], shown["sha256"], widen=shown["widening_sha256"])
    with pytest.raises(ops.OpsError) as moved:
        approve(world, started)
    assert "address" in str(moved.value) and world["gmail"].requests == []


def test_a_mailer_whose_account_token_is_another_address_than_the_configured_one_sends_nothing(world):
    world["gmail"].profile_address = "pat.new@example.com"
    started = send(world)
    with pytest.raises(ops.OpsError) as why:
        approve(world, started)
    assert "another address" in str(why.value) and world["gmail"].sent == [] and ops.pending(world["path"], started["pending"])["status"] == "open"


@pytest.mark.parametrize("kind", ["lost", 503])
def test_limit_42_an_unknown_outcome_stays_open_and_approving_again_finds_the_message_by_its_message_id(world, kind):
    gmail = world["gmail"]
    started = send(world)
    if kind == "lost":
        gmail.lose_answer_once = True
    else:
        gmail.refuse_next = (503, "backendError")
    with pytest.raises(ops.OpsError) as unknown:
        approve(world, started)
    assert "unknown" in str(unknown.value) and "sent mail of your account" in str(unknown.value) and ops.pending(world["path"], started["pending"])["status"] == "open"
    gmail.requests.clear()
    if kind == "lost":
        done = approve(world, started)
        assert done["task_state"] == "done" and done["result"]["replayed"] is True and len(gmail.sent) == 1, "found among the sent mail: nothing was sent again"
        assert [r["path"] for r in gmail.requests if r["method"] == "GET"][-2:] == [f"{fgs.PREFIX}/messages", f"{fgs.PREFIX}/messages/{gmail.sent[0]['id']}"]
    else:
        with pytest.raises(ops.OpsError) as again:
            approve(world, started)
        assert "unknown" in str(again.value) and gmail.sent == [] and "resolve" in str(again.value), "not found: still unknown, and the person settles the key"


def test_a_refusal_by_the_service_sends_nothing_and_leaves_the_effect_open_to_try_again(world):
    started = send(world)
    world["gmail"].refuse_next = (400, "invalidArgument")
    with pytest.raises(ops.OpsError) as no:
        approve(world, started)
    assert "nothing was sent" in str(no.value) and world["gmail"].sent == []
    assert approve(world, started)["task_state"] == "done" and len(world["gmail"].sent) == 1


def test_a_send_is_not_made_twice_whatever_the_number_of_approvals(world):
    started = send(world)
    approve(world, started)
    with pytest.raises(ops.OpsError):
        approve(world, started)
    assert len(world["gmail"].sent) == 1
    again = send(world)
    assert effect_doc(world, again)["idempotency_key"] != effect_doc(world, started)["idempotency_key"], "a new task is a new e-mail"


def test_an_attachment_changed_after_the_card_stops_the_send_and_asks_again_about_the_file_as_it_is(world):
    started = send(world, attach=[PATH])
    (Path(world["path"]) / PATH).write_bytes(PDF + b" edited")
    with pytest.raises(ops.OpsError) as stale:
        approve(world, started)
    assert "not the file the task read" in str(stale.value) and world["gmail"].requests == [] and world["gmail"].sent == []
    ctx = ops_core.context(world["path"])
    assert ctx["store"].task_get(ctx["conn"], started["task"])["state"] in ("ready", "planned"), "the task starts over from the step that reads"
    again = send(world, attach=[PATH])
    assert approve(world, again)["task_state"] == "done" and len(world["gmail"].sent) == 1


def test_what_the_mailer_will_not_take_is_refused_at_the_start_with_its_own_sentence_to_the_caller_and_the_note_keeps_the_fixed_one(world):
    big = Path(world["path"]) / "docs" / "outputs" / "big.pdf"
    big.write_bytes(b"x" * (3 * 1024 * 1024 + 1))
    error = refused(world, attach=["docs/outputs/big.pdf"])
    assert "the attachment big.pdf is over 3145728 bytes" in str(error) and "error:" not in str(error), "the person at the terminal reads the mailer's exact words"
    tasks, pending = rows(world)
    assert pending == [] and {t["state"] for t in tasks} <= {"cancelled", "failed"}
    kept = json.dumps([[t["note"], (t["step_state"] or {}).get("failure")] for t in tasks], default=str)      # the stored note and failure (the arguments are the request itself)
    assert "big.pdf" not in kept and step_send_email.REFUSED_NEXT_OWN in kept, "the stored note and failure keep the fixed sentence"
    assert world["gmail"].requests == [] and world["graph"].requests == []
    graph_big = Path(world["path"]) / "docs" / "outputs" / "graph.pdf"
    graph_big.write_bytes(b"x" * (2560 * 1024 + 1))
    error = refused(world, send, "microsoft", attach=["docs/outputs/graph.pdf"])
    assert "graph.pdf is over" in str(error)
    accept(world["path"], {"messaging": ["read", "mail-send"]})      # a caller who may not read the person's mail gets the fixed sentence
    error = refused(world, attach=["docs/outputs/big.pdf"], channel="messaging", sender=SENDER)
    assert step_send_email.REFUSED_NEXT_OWN in str(error) and "big.pdf" not in str(error)
    assert "big.pdf" not in json.dumps([[t["note"], (t["step_state"] or {}).get("failure")] for t in rows(world)[0]], default=str)


# --- the arguments ---------------------------------------------------------------------------------------------------------------------------


def test_a_bcc_from_a_google_account_is_refused_and_from_a_microsoft_account_it_is_on_the_card_and_goes_out(world):
    error = refused(world, bcc="hidden@client.example")
    assert "Bcc is not sent from a Google account" in str(error)
    nothing_made(world)
    started = send(world, "microsoft", bcc="hidden@client.example")
    assert "Bcc (hidden from the others, listed here for you): hidden@client.example" in item_of(world, started)["body"]
    done = approve(world, started)
    assert done["task_state"] == "done" and world["graph"].sent[0]["bcc"] == ["hidden@client.example"]


@pytest.mark.parametrize("more", [{"to": "Ana <ana@client.example>"}, {"to": "ana@client.example,ANA@client.example"}, {"subject": ""}, {"subject": " padded "},
                                  {"subject": "two\nlines"}, {"subject": "hidden \u202e"}, {"text": "  "}, {"text": "a\x00b"}, {"cc": "none,x"}, {"attach": ["../x.pdf"]},
                                  {"attach": ["docs/outputs/missing.pdf"]}, {"to": ",".join(f"p{i}@client.example" for i in range(21))}], ids=lambda m: next(iter(m)))
def test_an_argument_that_is_not_in_its_form_is_refused_and_leaves_nothing_behind(world, more):
    error = refused(world, **more)
    assert error.code in (1, 2)
    nothing_made(world)


def test_a_credential_in_the_subject_or_the_text_is_refused_not_sent_anywhere(world):
    key = "AKIA" + "ABCDEFGHIJKLMNOP"
    for kw in ({"text": f"my key is {key}\n"}, {"subject": f"key {key}"}):
        error = refused(world, **kw)
        assert "credential" in str(error) or "AWS" in str(error) or "secret" in str(error) or error.code in (1, 2)
    nothing_made(world)


@pytest.mark.parametrize("line", ["-----", "----- end of the message -----", "  ----- hello", "> ----- x", "# ----- x", "**----- x**", "- ----- x", "1. ----- x",
                                  "\u2014\u2014\u2014\u2014\u2014 end", "\uff0d\uff0d\uff0d\uff0d\uff0d", "\u2500\u2500\u2500\u2500\u2500", "\u2010\u2011\u2012\u2013\u2014 x"])
def test_a_line_of_the_text_that_could_pass_for_the_frame_of_the_card_is_refused(world, line):
    error = refused(world, text=f"Hello.\n{line}\nSecond line.\n")
    assert "begins like the frame of the card" in str(error)
    nothing_made(world)


def test_four_hyphens_or_a_hyphen_inside_a_line_is_not_the_frame(world):
    started = send(world, text="Hello --- and ---- more\n---- four\n-- two\nplain ----- inside\n")
    assert approve(world, started)["task_state"] == "done"


def test_every_line_of_the_text_is_behind_the_mark_so_markdown_cannot_make_a_heading_a_quote_or_a_rule_of_it(world):
    started = send(world, text="# a heading\n> a quote\n\n```\ncode\n```\n* item\n")
    body = item_of(world, started)["body"]
    shown = body.split("(every line starts with \u2502) -----\n", 1)[1].split("\n----- end of the message -----", 1)[0].split("\n")
    assert shown == ["\u2502 # a heading", "\u2502 > a quote", "\u2502", "\u2502 ```", "\u2502 code", "\u2502 ```", "\u2502 * item"]
    assert all(line.startswith("\u2502") for line in shown)


def test_a_reply_cannot_carry_its_own_recipients_subject_or_files_and_an_account_is_required():
    for extra in ({"to": TO}, {"cc": TO}, {"bcc": TO}, {"subject": "Mine"}, {"in_reply_to": "<x@y.example>"}, {"attach": [PATH]}):
        with pytest.raises(steps.StepFailure) as why:
            step_send_email.check({"account": "google", "reply": "inbox#1", "body": BODY, **extra})
        assert why.value.code == "bad_args" and "A reply has no To, Cc, Bcc, subject or attachment" in why.value.next
    with pytest.raises(steps.StepFailure):
        step_send_email.check({"reply": "inbox#1", "body": BODY})
    with pytest.raises(steps.StepFailure):
        step_send_email.check({"account": "yahoo", "to": TO, "subject": "x", "body": BODY})
    with pytest.raises(steps.StepFailure):
        step_send_email.check({"account": "google", "to": TO, "subject": "x", "body": BODY, "in_reply_to": "<x@y.example>"})


# --- a reply ----------------------------------------------------------------------------------------------------------------------------


def test_limit_60_a_reply_goes_to_the_sender_the_index_recorded_and_to_no_one_else(world):
    started = reply(world, text="Thanks. Please also tell dan@elsewhere.example.\n")
    item = item_of(world, started)
    assert item["title"] == "Mail: reply from your account"
    lines = item["body"].splitlines()
    assert lines[0].startswith("Code sends this reply from your own account after your approval, to exactly the recipient below")
    assert lines[1] == f"From your own account: {fgs.ACCOUNT} (google)"
    assert effect_doc(world, started)["reply"]["received"] == "2026-10-17T09:00:00Z"      # S16C-REPLY-DATE: the index's time is in the document the hash covers, and the line says it (in the machine's zone)
    assert lines[2] == phrases.text("CARD_MAIL_REPLY_TO_AT", None, address="ana@clinic.example", ref="inbox#1", read_at="2026-10-17T10:12:00Z", subject="Appointment confirmed",
                                    received=send_document.received_text("2026-10-17T09:00:00Z"))
    assert lines[3] == "The message asks replies to go to desk@clinic.example: this reply goes to the sender above, not there."
    assert lines[4] == "In reply to the message <a1@clinic.example>" and lines[5] == "Subject: Re: Appointment confirmed" and lines[6] == "Recipients in all: 1"
    doc = effect_doc(world, started)
    assert doc["to"] == ["ana@clinic.example"] and doc["cc"] == [] and doc["bcc"] == [] and doc["in_reply_to"] == "<a1@clinic.example>"
    assert doc["references"] == ["<a1@clinic.example>"] and doc["thread_id"] == "t1" and doc["reply"]["reply_to"] == "desk@clinic.example"
    assert doc["reply"]["provider_id"] == "m1" and doc["reply"]["ref"] == "inbox#1" and doc["subject"] == "Re: Appointment confirmed"
    approve(world, started)
    gmail = world["gmail"]
    message = sent_message(gmail)
    assert message["To"] == "ana@clinic.example" and message["Cc"] is None and message["Bcc"] is None, "the envelope is the sender and no address of the body or the Reply-To"
    assert message["In-Reply-To"] == "<a1@clinic.example>" and message["References"] == "<a1@clinic.example>" and message["Subject"] == "Re: Appointment confirmed"
    assert gmail.sent[0]["threadId"] == "t1"
    assert "desk@clinic.example" not in gmail.sent[0]["raw"].decode("utf-8", "replace") and "carol@elsewhere.example" not in gmail.sent[0]["raw"].decode("utf-8", "replace")
    assert "dan@elsewhere.example" in gmail.sent[0]["raw"].decode("utf-8", "replace"), "the person's own words are the text, whatever they name"


def test_limit_60_the_document_of_a_reply_refuses_every_edit_of_its_recipients_and_its_conversation(world):
    doc = effect_doc(world, reply(world))
    send_document.check(doc)

    def broken(**change):
        edited = json.loads(json.dumps(doc))
        for key, value in change.items():
            if key.startswith("reply."):
                edited["reply"][key[6:]] = value
            else:
                edited[key] = value
        return edited
    for change in ({"to": ["carol@elsewhere.example"]}, {"to": ["ana@clinic.example", "carol@elsewhere.example"]}, {"cc": ["carol@elsewhere.example"]},
                   {"bcc": ["carol@elsewhere.example"]}, {"to": [doc["reply"]["reply_to"]]}, {"in_reply_to": "<other@clinic.example>"}, {"references": []},
                   {"references": ["<a1@clinic.example>", "<x@y.example>"]}, {"subject": "Something else"}, {"thread_id": None}, {"reply.address": "carol@elsewhere.example"},
                   {"attachments": [{"path": PATH, "name": "cv.pdf", "media_type": "application/pdf", "bytes": 3, "sha256": "0" * 64}]}, {"account": "microsoft"},
                   {"provider": "outlook"}):
        with pytest.raises(effects.EffectError):
            send_document.check(broken(**change))
    with pytest.raises(effects.EffectError):
        send_document.check({**doc, "extra": 1})
    assert {"all", "reply_all"}.isdisjoint({a["name"] for r in operations.OPERATIONS if r["name"] in ("mail-send", "mail-reply") for a in r["args"]}), "there is no reply to all"


def test_a_reply_from_a_microsoft_account_is_createreply_an_update_and_the_send_with_the_sender_only(world):
    started = reply(world, "work#1", "microsoft")
    doc = effect_doc(world, started)
    assert doc["provider"] == "outlook" and doc["thread_id"] is None and doc["reply"]["provider_id"] == "m1" and doc["to"] == ["ana@clinic.example"]
    world["graph"].reply_to_reply_to = True      # createReply addresses the draft to the Reply-To: the update puts it back to the sender
    done = approve(world, started)
    assert done["task_state"] == "done" and done["result"]["account"] == "microsoft" and done["result"]["reply"] is True
    graph = world["graph"]
    assert [(r["method"], r["path"].rsplit("/", 1)[-1]) for r in graph.requests] == [("POST", "token"), ("GET", "me"), ("POST", "createReply"), ("PATCH", graph.sent[0]["draft_id"]),
                                                                                  ("POST", "send")]
    assert graph.sent[0]["to"] == ["ana@clinic.example"] and graph.unexpected() == [] and graph.deleted == []


def test_each_way_a_reference_can_fail_has_its_sentence_and_nothing_is_made(world):
    desk = world["desk"]
    (Path(world["tmp"]) / "notes.txt").write_text("a\n", encoding="utf-8")
    sources.import_version(desk.ctx, sources.register(desk.ctx, "notes", "file", "notes.txt"), str(Path(world["tmp"]) / "notes.txt"), convert=standin_convert)
    sources.register(desk.ctx, "later", "mail", "gmail:box=starred;days=3;max=10")
    cases = [("inbox", "is not a reference to a message"), ("inbox#0", "start at 1"), ("inbox#9", "past the end"), ("nothing#1", "no mail source"),
             ("created:3", "not a message of a mail snapshot"), ("notes#1", "is not a mail source"), ("later#1", "has no snapshot yet")]
    for message, sentence in cases:
        error = refused(world, reply, message)
        assert sentence in str(error) and error.code == 1, (message, str(error))
        nothing_made(world)
    desk.now = desk.now + datetime.timedelta(hours=30)
    stale = refused(world, reply, "inbox#1")
    assert "more than 26 hours old" in str(stale)
    nothing_made(world)
    assert "{" not in str(stale) and str(stale).startswith("The newest snapshot of inbox#1 ")


def test_a_message_of_another_account_or_without_a_sender_or_a_message_id_cannot_be_answered(world):
    error = refused(world, reply, "work#1", "google")
    assert "another account than google" in str(error)
    error = refused(world, reply, "inbox#3")      # no Message-ID header in the snapshot
    assert "cannot be answered from here" in str(error)
    desk = world["desk"]
    desk.providers.mail["gmail"] = [tsm.message(7, "2026-10-17T09:00:00Z", sender="undisclosed", subject="List", thread_id="t7", headers={"Message-ID": "<l7@list.example>"},
                                                from_address=None)]
    desk.later(minutes=5)
    desk.refresh("inbox")
    error = refused(world, reply, "inbox#1")
    assert "no single sender address" in str(error)
    nothing_made(world)


def test_the_terminal_and_the_service_reach_the_same_operations_with_the_names_the_table_gives(world):
    cli = st.load("cli")
    started = cli.run(["mail-send", "--project", world["path"], "--account", "google", "--to", TO, "--subject", SUBJECT, "--text", BODY, "--attach", PATH])
    assert started["word"] == "send" and started["on_cards"] is False and effect_doc(world, started)["attachments"][0]["name"] == "cv.pdf"
    answered = cli.run(["mail-reply", "--project", world["path"], "--account", "google", "--message", "inbox#2", "--text", BODY])
    assert effect_doc(world, answered)["to"] == ["bob@shop.example"] and effect_doc(world, answered)["subject"] == "Re: Your order", "a subject that already starts with Re: is kept"
    service = st.load("service")
    assert {(r["pattern"], r["op"]) for r in service.ROUTES if r["op"] in ("mail-send", "mail-reply")} == {("/projects/{p}/mail/send", "mail-send"),
                                                                                                           ("/projects/{p}/mail/reply", "mail-reply")}


def test_every_code_item_refs_can_raise_has_a_sentence_in_both_columns():
    source = (st.REPO / "runtime" / "item_refs.py").read_text(encoding="utf-8")
    codes = set(re.findall(r'ItemRefError\("([a-z_]+)"', source))
    assert codes and codes == set(mail_refs.REF_PHRASES), codes ^ set(mail_refs.REF_PHRASES)
    for code, key in mail_refs.REF_PHRASES.items():
        assert key in phrases.TABLE["en"] and key in phrases.TABLE["pt-BR"], key
        sentence = mail_refs.ref_sentence(code, "inbox#4\nnext line")
        assert "\n" not in sentence and "{" not in sentence, code
        assert phrases.localize(sentence, {"language": "pt-BR"}) == phrases.text(key, {"language": "pt-BR"}, ref=mail_refs.shown("inbox#4\nnext line")), code
    assert mail_refs.ref_sentence("nonsense", "x") == mail_refs.ref_sentence("integrity", "x"), "a code this module does not know is read as an integrity problem: it fails closed"


# --- the channels -----------------------------------------------------------------------------------------------------------------------


def test_a_messaging_sender_prepares_with_the_group_and_names_a_snapshot_only_with_ask_mail_and_approves_only_with_the_grant_and_the_hash(world, monkeypatch):
    with pytest.raises(ops.OpsError) as no:
        send(world, channel="messaging", sender=SENDER)
    assert "is not enabled for this channel" in str(no.value)
    nothing_made(world)
    accept(world["path"], {"messaging": ["read", "approve-effect-send-own"]})      # the approval grant alone does not let a sender ask
    with pytest.raises(ops.OpsError):
        send(world, channel="messaging", sender=SENDER)
    accepted = accept(world["path"], {"messaging": ["read", "mail-send"]})
    assert [w["group"] for w in accepted["widened"]] == ["mail-send"]
    started = send(world, channel="messaging", sender=SENDER)
    assert started["word"] == "send" and account_start.reply_text({}, started) == f"Card #{started['pending']} waits for your approval."
    assert world["gmail"].requests == []
    error = refused(world, reply, "inbox#1", channel="messaging", sender=SENDER)
    assert "may not read it" in str(error) and "ask-mail" in str(error), "no profile can list the group ask-mail before NR-2 builds it: a messaging sender cannot name a snapshot"
    with pytest.raises(ops.OpsError) as not_granted:
        approve(world, started, "messaging")
    assert "approve-effect-send-own" in str(not_granted.value) and world["gmail"].requests == []
    monkeypatch.setattr(item_refs, "may_read", lambda ctx, channel, sender=None: True)      # stands in for a sender whose profile lists `ask-mail` (NR-2 adds the group)
    replied = reply(world, channel="messaging", sender=SENDER)
    assert replied["word"] == "send"
    full = ops.pending(world["path"], started["pending"])
    card = cards.build("office", full, CAPS, ops.config(world["path"])["channels"], "text", None, operations=operations)
    assert card["approvable"] is False, "the grant is not accepted yet"
    accept(world["path"], {"messaging": ["read", "mail-send", "approve-effect-send-own"]})
    reader_of_mail = {"messaging": [*ops.config(world["path"])["channels"]["messaging"], "ask-mail"]}      # the card is whole only for a reader of the mail
    card = cards.build("office", full, CAPS, reader_of_mail, "text", None, operations=operations, sender=SENDER)
    assert card["approvable"] is True and card["whole"] is True and "Approve this exact content" in [a["label"] for a in card["message"]["actions"]]
    for line in (f"To: {TO}", f"Subject: {SUBJECT}", "\u2502 Hello Ana,"):
        assert line in card["message"]["text"], line
    with pytest.raises(ops.OpsError):
        ops.approve(world["path"], started["pending"], "0" * 64, channel="messaging", sender=SENDER)
    assert world["gmail"].requests == []
    assert approve(world, started, "messaging")["task_state"] == "done" and len(world["gmail"].sent) == 1


def test_an_email_with_an_attachment_is_never_whole_on_a_messaging_card_whatever_the_grants(world):
    accept(world["path"], {"messaging": ["read", "mail-send", "approve-effect-send-own"]})
    started = send(world, attach=[PATH], channel="messaging", sender=SENDER)
    assert started["on_cards"] is False
    full = ops.pending(world["path"], started["pending"])
    card = cards.build("office", full, CAPS, ops.config(world["path"])["channels"], "text", None, operations=operations, sender=SENDER)
    assert card["approvable"] is False
    with pytest.raises(ops.OpsError):
        approve(world, started, "messaging")
    assert world["gmail"].requests == [] and approve(world, started, "terminal")["task_state"] == "done"


def test_the_mcp_mode_and_the_conversation_never_prepare_or_approve_an_email_from_an_own_account(world):
    for channel in ("mcp", "chat"):
        with pytest.raises(ops.OpsError):
            send(world, channel=channel)
        with pytest.raises(ops.OpsError):
            reply(world, channel=channel)
    nothing_made(world)
    started = send(world)
    for channel in ("mcp", "chat", None):
        with pytest.raises(ops.OpsError):
            approve(world, started, channel)
    for channel in ("messaging", "chat"):
        said = ops.say(world["path"], f"/approve {started['pending']} {item_of(world, started)['payload_sha256']}", channel=channel,
                       sender=(SENDER if channel == "messaging" else None))["reply"]
        assert said == PLAIN_REFUSAL if channel == "messaging" else said.startswith("error: ")
    assert world["gmail"].requests == [] and ops.pending(world["path"], started["pending"])["status"] == "open"
    assert operations.GROUPS["mail-send"] == {"operations": ("mail-send", "mail-reply"), "kind": None} and "mail-send" not in operations.DEFAULT_POLICY["messaging"]
    assert "approve-effect-send" not in operations.GRANTS["mcp"]


def test_the_page_prepares_with_its_group_and_approves(world):
    accept(world["path"], {"page": ["read", "approve-effects"]})
    with pytest.raises(ops.OpsError) as no:
        send(world, channel="page")
    assert "not enabled" in str(no.value)
    accept(world["path"], {"page": ["read", "mail-send", "approve-effects"]})
    started = send(world, channel="page")
    assert approve(world, started, "page")["task_state"] == "done" and len(world["gmail"].sent) == 1


# --- the card, in two languages ---------------------------------------------------------------------------------------------------------


def test_the_card_is_said_line_by_line_in_the_projects_language_with_the_same_hash_and_the_persons_words_unchanged(world):
    started = reply(world)
    item = item_of(world, started)
    english = cards.effect_card_text(item, {})
    assert english == item["body"]
    portuguese = cards.effect_card_text(item, {"language": "pt-BR"})
    assert portuguese.splitlines()[0].startswith("O c\u00f3digo envia esta resposta da sua pr\u00f3pria conta depois da sua aprova\u00e7\u00e3o")
    for needle in (f"Da sua pr\u00f3pria conta: {fgs.ACCOUNT} (google)", "Resposta para: ana@clinic.example, quem enviou inbox#1", "Appointment confirmed",
                   "A mensagem pede que as respostas v\u00e3o para desk@clinic.example", "Assunto: Re: Appointment confirmed", "Destinat\u00e1rios no total: 1",
                   "\u2502 Hello Ana,", "----- fim da mensagem -----"):
        assert needle in portuguese, needle
    policy = {"messaging": ["read", "approve-effect-send-own"]}
    full = ops.pending(world["path"], started["pending"])
    pt = cards.build("northwind", full, CAPS, policy, "text", None, operations=operations, cfg={"language": "pt-BR"})
    en = cards.build("northwind", full, CAPS, policy, "text", None, operations=operations, cfg={})
    assert pt["content_sha256"] == en["content_sha256"] and full["payload_sha256"] not in pt["message"]["text"] and pt["content_sha256"] == full["payload_sha256"]      # the hash binds the button; a phone does not print it (LIVE-2)
    assert phrases.heading(item["title"], {"language": "pt-BR"}) == "E-mail: responder da sua conta"


def test_every_key_of_the_family_is_in_both_columns_with_the_same_fields_and_the_card_of_every_kind_equals_its_stored_body(world):
    keys = [k for k in phrases.TABLE["en"] if k.startswith("CARD_MAIL_")]
    assert keys and all(k in phrases.TABLE["pt-BR"] and phrases.TABLE["pt-BR"][k] != phrases.TABLE["en"][k] for k in keys)
    for each in (send(world, cc="lee@client.example", attach=[PATH]), send(world, "microsoft", bcc="hidden@client.example"), reply(world)):
        item = item_of(world, each)
        card = item["payload"]["card"]
        assert phrases.card_valid(card) and phrases.card_text(card) == item["body"]
        assert phrases.card_text(card, {"language": "pt-BR"}) != item["body"]


# --- the structure --------------------------------------------------------------------------------------------------------------------------


def test_the_mailers_are_named_explicitly_and_never_chosen_by_auto_nor_listed_as_the_outbox():
    resolver = project_config.resolver(str(st.REPO))
    assert resolver.resolve("sender:email", root=str(st.REPO), env={})["implementation"] == "smtp"
    assert resolver.resolve("sender:email", root=str(st.REPO), env={})["source"] == "class-default"
    assert resolver.resolve("sender:email", root=str(st.REPO), env={}, implementation="gmail")["implementation"] == "gmail"
    assert resolver.resolve("sender:email", root=str(st.REPO), env={"MAILER_PROVIDER": "outlook"})["implementation"] == "outlook"
    assert {"gmail", "outlook"} <= set(resolver.implementations("sender:email", root=str(st.REPO)))
    with pytest.raises(project_config.ConfigError):
        project_config._outbox({"provider": "gmail", "from": "me@mail.example"}, str(st.REPO))
    assert project_config._outbox({"provider": "auto", "from": "me@mail.example"}, str(st.REPO)) == {"provider": "auto", "from": "me@mail.example"}
    assert send_document.ACCOUNTS == {"google": "gmail", "microsoft": "outlook"}


def test_a_variable_that_names_a_mailer_of_an_own_account_never_makes_it_the_projects_outbox(monkeypatch):
    seams, cfg = st.load("ops_step_seams"), {"outbox": {"provider": "auto", "from": "outbox@office.example"}}
    monkeypatch.setenv("MAILER_PROVIDER", "gmail")
    with pytest.raises(seams.StepServiceError) as why:
        seams.OutboxReader(cfg, str(st.REPO)).provider()
    assert why.value.code == "not_configured" and "SMTP account" in why.value.reason
    doc = send_document.document(task_id=3, provider="gmail", from_addr="outbox@office.example", to=["ana@client.example"], cc=[], bcc=[], subject="Invoice", body="Hi.\n",
                                 in_reply_to=None, attachments=[], dry_run_sha256="0" * 64)
    refusal = effect_send.preflight(cfg, doc, str(st.REPO))
    assert refusal is not None and refusal[0] == 3 and "SMTP account" in refusal[1]
    monkeypatch.delenv("MAILER_PROVIDER")
    assert seams.OutboxReader(cfg, str(st.REPO)).provider() == "smtp"


def test_no_step_module_or_run_reaches_the_account_mailers_and_only_the_effect_module_and_the_seam_name_them():
    named = []
    for path in sorted((st.REPO / "runtime").glob("*.py")):
        text = path.read_text(encoding="utf-8")
        if re.search(r"""["']gmail["']|["']outlook["']|\bgmail\.py\b|\boutlook\.py\b""", text) and path.name not in ("sources_mail.py", "sources.py", "phrases.py", "operations.py",
                                                                                                                     "item_refs.py", "snapshot_text.py", "cli.py", "ops_sources.py",
                                                                                                                     "messaging_provider.py", "project_config.py", "service.py",
                                                                                                                     "natural_lang_en.py", "natural_lang_pt_br.py", "ops_natural_calendar.py"):      # NR-5: the words a person types to name a service ("no gmail", "on my outlook") are language data
            named.append(path.name)
    assert set(named) <= {"send_document.py", "effect_send.py", "mail_refs.py", "ops_step_seams.py", "ops_mail_send.py", "step_send_email.py",
                          "mailbox_document.py", "ops_mailbox.py"}, named      # W3: the mailbox document and its operations name the writer of the account (an implementation of writer:mailbox), never a mailer
    for path in (st.REPO / "runtime").glob("step_*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        assert not [n for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr in ("provider_call", "execute", "caller")], path.name


def test_the_seam_a_step_is_given_can_only_ask_for_a_dry_run_never_a_send(world):
    seam = st.load("ops_step_seams").AccountMailReader(ops_core.context(world["path"]))
    assert {n for n in dir(seam) if not n.startswith("_")} == {"enabled", "address", "implementation", "reply_facts", "dry_run"}
    assert seam.enabled("google") and seam.enabled("microsoft") and not seam.enabled("yahoo") and seam.implementation("microsoft") == "outlook"
    doc = effect_doc(world, send(world))
    shown = seam.dry_run(doc, [])
    assert shown["dry_run"] is True and shown["would"]["service"] == "gmail" and shown["would_sha256"] == doc["dry_run_sha256"]
    assert world["gmail"].requests == []


# --- the review of the first version -------------------------------------------------------------------------------------------------


def test_the_grant_of_the_outboxs_e_mail_does_not_cover_an_e_mail_from_an_own_account(world, monkeypatch):
    accept(world["path"], {"messaging": ["read", "mail-send", "approve-effect-send"]})
    started = send(world, channel="messaging", sender=SENDER)
    full = ops.pending(world["path"], started["pending"])
    assert full["effect_word"] == "send-own" and started["word"] == "send", "the policy is asked about send-own; the effect is still the word send"
    card = cards.build("office", full, CAPS, ops.config(world["path"])["channels"], "text", None, operations=operations, sender=SENDER)
    assert card["approvable"] is False
    with pytest.raises(ops.OpsError) as no:
        approve(world, started, "messaging")
    assert "approve-effect-send-own" in str(no.value) and world["gmail"].requests == []
    accepted = accept(world["path"], {"messaging": ["read", "mail-send", "approve-effect-send", "approve-effect-send-own"]})
    assert [w["group"] for w in accepted["widened"]] == ["approve-effect-send-own"], "giving it needs accept-config --widen"
    with pytest.raises(ops.OpsError) as unread:
        approve(world, started, "messaging")
    assert "ask-mail" in str(unread.value) and world["gmail"].requests == [], "the grant is not enough: the card has lines only a reader of the mail is shown"
    monkeypatch.setattr(item_refs, "may_read", lambda ctx, channel, sender=None: True)      # stands in for a sender whose profile lists `ask-mail` (NR-2 adds the group)
    assert approve(world, started, "messaging")["task_state"] == "done"
    assert operations.GROUPS["approve-effect-send-own"] == {"operations": ("approve",), "kind": "effect:send-own"} and "send-own" in operations.EFFECT_APPROVAL_WORDS
    assert "approve-effect-send-own" in operations.IMPLIED["approve-effects"] and "approve-effect-send-own" in operations.GRANTS["messaging"]
    assert "approve-effect-send-own" not in operations.GRANTS["mcp"] and "your own accounts" in operations.GRANT_TEXT["messaging:approve-effect-send-own"]
    assert "own accounts" not in operations.GRANT_TEXT["messaging:approve-effect-send"]


def test_the_outboxs_send_is_still_asked_by_the_word_send(world):
    doc = send_document.document(task_id=3, provider="smtp", from_addr="outbox@office.example", to=["ana@client.example"], cc=[], bcc=[], subject="Invoice", body="Hi.\n",
                                 in_reply_to=None, attachments=[], dry_run_sha256="0" * 64)
    assert effect_send.approval_word(doc) == "send"
    assert effect_send.approval_word(effect_doc(world, send(world))) == "send-own"


def test_a_sender_address_with_capitals_is_answered_in_its_normal_form_and_a_reply_to_that_differs_only_in_case_is_the_same_address(world):
    desk = world["desk"]
    desk.providers.mail["gmail"] = [tsm.message(1, "2026-10-17T09:00:00Z", sender="Ana Lima <ana@Clinic.Example>", subject="Appointment confirmed", thread_id="t1",
                                                reply_to="ANA@clinic.example", headers={"Message-ID": "<a1@clinic.example>"}),
                                    tsm.message(2, "2026-10-16T09:00:00Z", sender="Bob <bob@shop.example>", subject="Order", thread_id="t2", reply_to="Desk@Shop.Example",
                                                headers={"Message-ID": "<b2@shop.example>"})]
    desk.later(minutes=5)
    desk.refresh("inbox")
    doc = effect_doc(world, reply(world))
    assert doc["to"] == ["ana@clinic.example"] and doc["reply"]["address"] == "ana@clinic.example" and doc["reply"]["reply_to"] is None
    other = effect_doc(world, reply(world, "inbox#2"))
    assert other["to"] == ["bob@shop.example"] and other["reply"]["reply_to"] == "Desk@shop.example"


def test_the_message_a_reply_answers_is_pinned_and_a_preparation_that_resolves_to_another_message_is_refused(world):
    started = reply(world)
    assert json.loads(json.dumps(effect_doc(world, started)))["reply"]["provider_id"] == "m1"
    ctx = ops_core.context(world["path"])
    task = ctx["store"].task_get(ctx["conn"], started["task"])
    assert task["step_args"]["reply_pin"] == {"id": "m1", "message_id": "<a1@clinic.example>"}
    desk = world["desk"]
    desk.providers.mail["gmail"] = [tsm.message(9, "2026-10-17T09:30:00Z", sender="Mallory <mallory@evil.example>", subject="Re: Appointment confirmed", thread_id="t9",
                                                headers={"Message-ID": "<z9@evil.example>"})] + desk.providers.mail["gmail"]
    desk.later(minutes=5)
    desk.refresh("inbox")      # inbox#1 is now someone else
    pin = {"id": "m1", "message_id": "<a1@clinic.example>"}
    args = {"account": "google", "reply": "inbox#1", "reply_pin": pin, "body": BODY, "channel": "terminal"}
    with pytest.raises(ops.OpsError) as moved:
        account_start.start(world["path"], "send-email", args, key_words="mail-reply", title_key="TITLE_MAIL_REPLY", account="google")
    assert "no longer names the message you asked to answer" in str(moved.value)
    assert world["gmail"].requests == []
    still = account_start.start(world["path"], "send-email", {**args, "reply": "inbox#2", "reply_pin": {"id": "m1", "message_id": "<a1@clinic.example>"}},
                                key_words="mail-reply", title_key="TITLE_MAIL_REPLY", account="google")
    assert effect_doc(world, still)["to"] == ["ana@clinic.example"], "the pin follows the message, not its number"
    for bad in ({"id": "m1"}, {"id": "m1", "message_id": "x"}, {"id": 1, "message_id": "<a@b.example>"}, "m1", {"id": "m1", "message_id": "<a@b.example>", "x": 1}):
        with pytest.raises(steps.StepFailure):
            step_send_email.check({"account": "google", "reply": "inbox#1", "reply_pin": bad, "body": BODY, "channel": "terminal"})
    with pytest.raises(steps.StepFailure):
        step_send_email.check({"account": "google", "to": TO, "subject": "x", "body": BODY, "reply_pin": pin})


@pytest.mark.parametrize("letter", ["ㅤ", "ᅟ", "⠀", "͏", "️", "ᅠ"])
def test_a_letter_that_draws_nothing_is_refused_in_the_text_and_the_subject(world, letter):
    assert "hidden character" in str(refused(world, text=f"Hello{letter}\n"))
    assert "hidden character" in str(refused(world, subject=f"Hi{letter}there"))
    nothing_made(world)


def test_the_service_message_id_graph_gave_is_in_the_effect_record_so_the_message_can_be_found(world):
    started = send(world, "microsoft")
    done = approve(world, started)
    assert done["result"]["service_message_id"] == world["graph"].sent[0]["internetMessageId"] and done["result"]["service_message_id"].startswith("<AM")
    ctx = ops_core.context(world["path"])
    assert done["result"]["service_message_id"] in json.dumps(ctx["store"].pending_get(ctx["conn"], started["pending"]), default=str)
    gmail = approve(world, send(world))
    assert "service_message_id" not in gmail["result"], "Gmail keeps the Message-ID the message carries"
    assert send_document.facts({"message_id": "<a@b.example>", "to": ["x@y.example"], "cc": [], "bcc": [], "attachments": [], "body": "x", "idempotency_key": "k"}, "sent",
                               "<ignored@b.example>").get("service_message_id") is None, "the outbox's record has none"


# --- who may read what a reply shows (the mechanism of W1: phrases.CARD_PRIVATE) and the binding of the reading right ---------------------


def card_for(world, started, groups, channel=None):
    full = ops.pending(world["path"], started["pending"])
    return cards.build("office", full, CAPS, {"messaging": groups}, "text", None, operations=operations, sender=SENDER)


def test_every_line_that_shows_who_an_email_goes_to_what_it_says_or_which_files_it_carries_is_private_and_the_count_and_the_hash_are_not(world):
    private = set(phrases.CARD_PRIVATE)
    reply_keys = ["CARD_MAIL_REPLY_TO_AT", "CARD_MAIL_REPLY_TO_DIFFERS", "CARD_MAIL_IN_REPLY", "CARD_MAIL_SUBJECT_REPLY", "CARD_MAIL_MESSAGE"]
    new_keys = ["CARD_MAIL_TO", "CARD_MAIL_CC", "CARD_MAIL_SUBJECT", "CARD_MAIL_MESSAGE", "CARD_MAIL_ATTACHMENT"]
    assert set(reply_keys + new_keys + ["CARD_MAIL_BCC"]) <= private
    answered = reply(world)
    assert [k for k, _ in item_of(world, answered)["payload"]["card"] if k in private] == reply_keys
    written = send(world, cc="lee@client.example", attach=[PATH])
    assert [k for k, _ in item_of(world, written)["payload"]["card"] if k in private] == new_keys
    microsoft = send(world, "microsoft", bcc="hidden@client.example")
    assert "CARD_MAIL_BCC" in [k for k, _ in item_of(world, microsoft)["payload"]["card"] if k in private]
    kept = [k for k, _ in item_of(world, written)["payload"]["card"] if k not in private]
    for key in ("CARD_MAIL_SEND", "CARD_MAIL_FROM_ACCOUNT", "CARD_MAIL_COUNT", "CARD_MAIL_ATTACHMENTS", "CARD_MAIL_HASH", "CARD_MAIL_APPROVE", "CARD_MAIL_ONCE"):
        assert key in kept, key


def test_a_reply_card_shows_what_the_message_says_only_to_a_messaging_reader_who_holds_ask_mail_and_is_not_approvable_without(world):
    started = reply(world)
    holder = card_for(world, started, ["read", "approve-effect-send-own", "ask-mail"])
    other = card_for(world, started, ["read", "approve-effect-send-own"])
    assert "Appointment confirmed" in holder["message"]["text"] and "ana@clinic.example" in holder["message"]["text"] and holder["approvable"] is True
    text = other["message"]["text"]
    for hidden in ("Appointment confirmed", "ana@clinic.example", "desk@clinic.example", "<a1@clinic.example>"):
        assert hidden not in text, hidden
    assert "Some of the addresses, subjects and text of the e-mail are not shown here" in text and "Recipients in all: 1" in text
    assert other["approvable"] is False and "Approve this exact content" not in [a["label"] for a in other["message"]["actions"]]
    assert other["content_sha256"] == holder["content_sha256"], "the hash is the effect's, whatever is drawn"


def test_the_mcp_mode_and_a_messaging_reader_without_ask_mail_read_a_reply_without_those_lines_and_the_terminal_reads_all(world):
    started = reply(world)
    for channel, sender in (("mcp", None), ("messaging", SENDER)):
        view = ops.pending(world["path"], started["pending"], channel=channel, sender=sender)
        assert "Appointment confirmed" not in view["body"] and "ana@clinic.example" not in view["body"] and "not shown here" in view["body"], channel
        assert all(key not in phrases.CARD_PRIVATE for key, _ in view["payload"]["card"])
    full = ops.pending(world["path"], started["pending"], channel="terminal")
    assert "Appointment confirmed" in full["body"] and "ana@clinic.example" in full["body"]
    assert "Appointment confirmed" in ops.pending(world["path"], started["pending"])["body"]


def test_the_reading_right_is_bound_into_the_step_and_a_plan_or_a_flow_cannot_carry_the_arguments_of_an_own_account_email(world):
    started = reply(world)
    ctx = ops_core.context(world["path"])
    task = ctx["store"].task_get(ctx["conn"], started["task"])
    assert task["step_args"]["channel"] == "terminal" and "sender" not in task["step_args"]
    for args in ({"account": "google", "reply": "inbox#1", "body": "Hi\n"}, {"account": "google", "to": TO, "subject": "x", "body": "Hi\n"},
                 {"to": TO, "subject": "x", "body": "Hi\n", "channel": "terminal"}):
        with pytest.raises(steps.StepFailure) as why:
            steps.plan_task("send-email", args, key="k", title="t", text="x")
        assert why.value.code == "not_plannable"
    planned = steps.plan_task("send-email", {"to": TO, "subject": "x", "body": "Hi\n"}, key="k", title="t", text="x")
    assert planned["args"]["to"] == TO, "the outbox's e-mail is still a plan's task"
    for bad in ({"account": "google", "reply": "inbox#1", "body": BODY}, {"account": "google", "reply": "inbox#1", "body": BODY, "channel": "mcp"},
                {"account": "google", "reply": "inbox#1", "body": BODY, "channel": "terminal", "sender": "telegram:1"},
                {"account": "google", "reply": "inbox#1", "body": BODY, "channel": "messaging"},
                {"account": "google", "reply": "inbox#1", "body": BODY, "channel": "messaging", "sender": "no sender"}):
        with pytest.raises(steps.StepFailure):
            step_send_email.check(bad)
    ok = step_send_email.check({"account": "google", "reply": "inbox#1", "body": BODY, "channel": "messaging", "sender": SENDER})
    assert ok["channel"] == "messaging" and ok["sender"] == SENDER


def test_a_preparation_never_resolves_a_reference_without_saying_who_asked(world, monkeypatch):
    seam = st.load("ops_step_seams").AccountMailReader(ops_core.context(world["path"]))
    for channel in (None, "mcp", "chat"):
        with pytest.raises(st.load("ops_step_seams").StepServiceError) as why:
            seam.reply_facts("inbox#1", "google", channel, None)
        assert why.value.code == "refused" and "may not read it" in why.value.reason
    assert seam.reply_facts("inbox#1", "google", "terminal", None)["address"] == "ana@clinic.example"
    with pytest.raises(st.load("ops_step_seams").StepServiceError) as no:
        seam.reply_facts("inbox#1", "google", "messaging", SENDER)
    assert "may not read it" in no.value.reason, "a messaging sender without ask-mail cannot be read for, even in a preparation"


# --- the task row, the result and the records of an e-mail from an own account, as a reader who may not read the person's mail sees them -------------------------

ops_grants = st.load("ops_grants")
OTHER = "telegram:9999"
BLIND = (("mcp", None), ("messaging", "telegram:9999"), ("messaging", None), ("messaging", SENDER))      # none of these holds ask-mail


def test_the_task_row_of_an_email_from_an_own_account_is_cut_to_nothing_for_mcp_and_messaging_readers_without_ask_mail(world):
    accept(world["path"], {"messaging": ["read", "mail-send"]})
    new = send(world, channel="messaging", sender=SENDER, cc="lee@client.example")
    answered = reply(world)
    for started in (new, answered):
        whole = ops.task(world["path"], started["task"])["task"]
        assert whole["step_args"]["account"] == "google" and whole["step_args"]["body"] == BODY, "the terminal and the page read the request itself"
        for channel in ("terminal", "page", "chat"):
            assert ops.task(world["path"], started["task"], channel=channel)["task"]["step_args"] == whole["step_args"], channel
        for channel, sender in BLIND:
            shown = ops.task(world["path"], started["task"], channel=channel, sender=sender)["task"]
            assert shown["step_args"] == {} and shown["step_kind"] == "send-email" and shown["step_state"]["steps"]["prepare"]["status"] == "done", (channel, sender)
            for word in (TO, "lee@client.example", SUBJECT, "Hello Ana", "830461975213", "terminal", "inbox#1", "Appointment confirmed", "ana@clinic.example", "google"):
                assert word not in json.dumps(shown), (channel, sender, word)
    for channel, sender in BLIND:      # the reply card draws the message answered only for a reader of the mail: nowhere in what these readers get
        shown = json.dumps(ops.task(world["path"], answered["task"], channel=channel, sender=sender))
        for word in ("ana@clinic.example", "desk@clinic.example", "Appointment confirmed", "830461975213"):
            assert word not in shown, (channel, sender, word)


def test_the_note_and_the_failure_of_an_email_from_an_own_account_are_cut_to_their_codes_and_a_reader_of_mail_gets_the_row_whole(world, monkeypatch):
    ctx = ops_core.context(world["path"])
    sentence = "the address ana@client.example is listed twice in Haircut on Monday"
    row = {"id": 1, "step_kind": "send-email", "note": f"prepare: refused account -- {sentence}",
           "step_args": {"account": "google", "to": TO, "subject": SUBJECT, "body": BODY, "reply": "inbox#1", "reply_pin": {"id": "m1", "message_id": "<a1@clinic.example>"},
                         "channel": "messaging", "sender": SENDER},
           "step_state": {"kind": "send-email", "failure": {"step": "prepare", "code": "refused", "field": "account", "provider": "mailer", "next": sentence, "at": "t"}}}
    cut = ops_grants.task_view(ctx, row, "mcp")
    assert cut["step_args"] == {} and cut["note"] == "prepare: refused account"
    assert cut["step_state"]["failure"] == {"step": "prepare", "code": "refused", "field": "account", "provider": "mailer", "at": "t"}
    assert row["step_args"]["to"] == TO and "listed twice" in row["note"], "the stored row is untouched"
    for channel, sender in BLIND:
        assert ops_grants.task_view(ctx, row, channel, sender)["step_args"] == {}, (channel, sender)
    for channel in ("terminal", "page", "chat", None):
        assert ops_grants.task_view(ctx, row, channel) is row, channel
    plain = {"id": 2, "step_kind": "send-email", "note": None, "step_args": {"to": TO, "subject": SUBJECT, "body": BODY}, "step_state": None}
    assert ops_grants.task_view(ctx, plain, "mcp") is plain, "the outbox's send has none of the arguments only an operation writes: it is not an account write"
    assert steps.is_account_step("send-email", row["step_args"]) and not steps.is_account_step("send-email", plain["step_args"]) and not steps.is_account_step("send-email")
    assert steps.public_args(row["step_args"], "send-email") == {} and steps.public_args({"operation": "create", "account": "google", "title": "x"}) == {"operation": "create", "account": "google"}
    monkeypatch.setattr(ops_grants.item_refs, "may_read", lambda *a, **k: True)
    assert ops_grants.task_view(ctx, row, "messaging", SENDER) is row, "a reader of the person's mail gets the row whole"


def test_the_mailers_own_sentence_never_reaches_the_note_of_the_task_but_the_reference_sentence_does():
    class Refusal(Exception):
        code, reason = "refused", "error: the address ana@client.example is listed twice"

    def refuse(*args):
        raise Refusal()
    with pytest.raises(steps.StepFailure) as failure:
        step_send_email._asked_own(refuse, 1)
    assert failure.value.next == step_send_email.REFUSED_NEXT_OWN and "ana@" not in failure.value.next and failure.value.provider == "mailer"
    with pytest.raises(steps.StepFailure) as sentence:
        step_send_email._asked_own(refuse, 1, words=True)
    assert "listed twice" in sentence.value.next, "the reading of a reference answers with a sentence written by code: it names the reference, never a text"


def test_the_result_the_description_and_the_approval_of_an_email_from_an_own_account_hold_no_recipient_subject_or_sender_id(world):
    accept(world["path"], {"messaging": ["read", "mail-send", "approve-effect-send-own"]})
    new = send(world, channel="messaging", sender=SENDER, cc="lee@client.example")
    answered = reply(world)
    with pytest.MonkeyPatch.context() as reader:      # the sender who approves holds the right to read (the group ask-mail comes with NR-2)
        reader.setattr(item_refs, "may_read", lambda ctx, channel, sender=None: True)
        approve(world, new, "messaging")
        approve(world, answered, "messaging")
    ctx = ops_core.context(world["path"])
    cfg = ctx["cfg"]
    for started in (new, answered):
        doc = json.loads((Path(ops_step_effects.effect_dir(cfg, started["task"], 0)) / "effect.json").read_text(encoding="utf-8"))
        approval = [a for a in ctx["store"].approvals_list(ctx["conn"]) if a["pending_id"] == started["pending"]][0]
        row = effects.approval_row(approval, doc)
        for kept in (effects.module_for("send").describe(doc), json.dumps(row), approval["what"]):      # the sender id is in the store alone (effects.approval_row)
            for word in (TO, "lee@client.example", SUBJECT, "Appointment confirmed", "ana@clinic.example", "desk@clinic.example", "830461975213"):
                assert word not in kept, (started["task"], word)
        assert "telegram" in row[1] or started is answered, "an approval on a messaging app says the platform and the profile, never the sender's id"
        whole = ops.pending(world["path"], started["pending"])
        assert whole["payload"]["result"]["sent"] is True and set(whole["payload"]["result"]) <= {
            "sent", "replayed", "message_id", "recipients", "attachments", "bytes", "idempotency_key", "account", "reply", "service_message_id"}
        for channel, sender in BLIND:
            shown = json.dumps([ops.pending(world["path"], started["pending"], channel=channel, sender=sender), ops.task(world["path"], started["task"], channel=channel, sender=sender)["pending"]])
            for word in (TO, "lee@client.example", SUBJECT, "Hello Ana", "830461975213", "ana@clinic.example", "desk@clinic.example", "Appointment confirmed"):
                assert word not in shown, (channel, sender, started["task"], word)


# --- the card of an e-mail is private: whole for a reader of the mail, for the terminal and the page; nowhere else, and approved only where it is whole -------------------


def test_the_card_of_a_new_email_is_read_whole_by_the_terminal_the_page_and_a_reader_of_the_mail_and_by_no_other_view(world, monkeypatch):
    started = send(world, cc="lee@client.example", attach=[PATH])
    words = (TO, "lee@client.example", SUBJECT, "Hello Ana", "See you on Monday", "cv.pdf")
    sha = item_of(world, started)["payload_sha256"]
    for channel in (None, "terminal", "page", "chat"):
        whole = ops.pending(world["path"], started["pending"], channel=channel)
        for word in words:
            assert word in whole["body"], (channel, word)
        assert any(word in json.dumps(ops.task(world["path"], started["task"], channel=channel)) for word in words)
    for channel, sender in BLIND:
        views = [ops.pending(world["path"], started["pending"], channel=channel, sender=sender), ops.pending(world["path"], channel=channel, sender=sender),
                 ops.task(world["path"], started["task"], channel=channel, sender=sender), ops.status(world["path"])]
        text = json.dumps(views)
        for word in words:
            assert word not in text, (channel, sender, word)
        shown = views[0]
        assert "not shown here" in shown["body"] and "Recipients in all: 2" in shown["body"] and sha in shown["body"], "the count, the hash and the way to approve stay"
        assert all(key not in phrases.CARD_PRIVATE for key, _ in shown["payload"]["card"]) and shown["payload_sha256"] == sha
    monkeypatch.setattr(item_refs, "may_read", lambda ctx, channel, sender=None: channel == "messaging" and sender == SENDER)      # a sender whose profile lists `ask-mail` (NR-2 adds the group)
    held = ops.pending(world["path"], started["pending"], channel="messaging", sender=SENDER)
    for word in words:
        assert word in held["body"], word
    assert "not shown here" not in held["body"]
    assert "cv.pdf" not in json.dumps(ops.pending(world["path"], started["pending"], channel="mcp")), "the MCP mode never reads it, whoever asks"
    assert "cv.pdf" not in json.dumps(ops.pending(world["path"], started["pending"], channel="messaging", sender=OTHER))


def test_a_card_with_private_lines_is_approved_from_messaging_only_by_a_reader_of_the_mail_at_the_operations_layer_too(world, monkeypatch):
    accept(world["path"], {"messaging": ["read", "mail-send", "approve-effect-send-own"]})
    started = send(world, channel="messaging", sender=SENDER)
    answered = reply(world)
    for card in (started, answered):
        with pytest.raises(ops.OpsError) as no:
            approve(world, card, "messaging")
        assert "ask-mail" in str(no.value) and "terminal or on the page" in str(no.value), card
        with pytest.raises(ops.OpsError):
            approve(world, card, "mcp")
    assert world["gmail"].requests == [] and item_of(world, started)["status"] == "open" and item_of(world, answered)["status"] == "open"
    ctx = ops_core.context(world["path"])
    item = item_of(world, started)
    facts = ops_grants.effect_facts(ctx, item)
    assert "ask-mail" in ops_grants.effect_refusal(ctx, item, "messaging", facts, SENDER)
    assert ops_grants.effect_refusal(ctx, item, "terminal", facts) is None and ops_grants.effect_refusal(ctx, item, "page", facts) is None
    assert ops_grants.has_private_lines(item) and not ops_grants.has_private_lines({"payload": {}}) and not ops_grants.has_private_lines({"payload": {"card": [["CARD_MAIL_ONCE", {}]]}})
    channels = ops.config(world["path"])["channels"]
    plain = cards.build("office", ops.pending(world["path"], started["pending"]), CAPS, channels, "text", None, operations=operations, sender=SENDER)
    assert plain["approvable"] is False and "Approve this exact content" not in [a["label"] for a in plain["message"]["actions"]], "the bridge says the same"
    monkeypatch.setattr(item_refs, "may_read", lambda ctx, channel, sender=None: channel == "messaging")      # a sender who holds `ask-mail`
    assert ops_grants.effect_refusal(ctx, item, "messaging", facts, SENDER) is None
    reader = {"messaging": [*channels["messaging"], "ask-mail"]}
    whole = cards.build("office", ops.pending(world["path"], started["pending"]), CAPS, reader, "text", None, operations=operations, sender=SENDER)
    assert whole["approvable"] is True and TO in whole["message"]["text"] and SUBJECT in whole["message"]["text"]
    assert approve(world, started, "messaging")["task_state"] == "done" and approve(world, answered, "terminal")["task_state"] == "done"
    assert len(world["gmail"].sent) == 2


def test_the_private_lines_of_an_email_card_show_and_approve_for_the_sender_whose_own_profile_lists_ask_mail_alone(world):
    """The real configuration (NR-2): `ask-mail` is in one listed sender's own profile, never in the channel's list; the card and the approval follow that policy."""
    from test_channel_grants_mailbox import accept as accept_holder      # the channel keeps the list without ask-mail; SENDER's profile `holder` lists it
    accept_holder(world["path"], {"messaging": ["read", "mail-send", "approve-effect-send-own", "ask-mail"]})
    started = send(world, channel="messaging", sender=SENDER)
    channels = ops.config(world["path"])["channels"]
    full = ops.pending(world["path"], started["pending"])
    holder = cards.build("office", full, CAPS, channels, "text", None, operations=operations, sender=SENDER)
    other = cards.build("office", full, CAPS, channels, "text", None, operations=operations, sender="telegram:777")
    assert TO in holder["message"]["text"] and SUBJECT in holder["message"]["text"] and holder["approvable"] is True
    assert TO not in other["message"]["text"] and other["approvable"] is False
    ctx = ops_core.context(world["path"])
    item = item_of(world, started)
    facts = ops_grants.effect_facts(ctx, item)
    assert ops_grants.effect_refusal(ctx, item, "messaging", facts, SENDER) is None
    assert "ask-mail" in ops_grants.effect_refusal(ctx, item, "messaging", facts, "telegram:777")


def test_the_private_card_a_holder_of_ask_mail_reads_is_not_kept_in_the_conversation_the_mcp_mode_reads(world):
    """A messaging read drawn under the wider view of a holder of `ask-mail` (a typed /pending, a natural line) goes to that chat; the conversation keeps a neutral word,
    so the MCP mode, which reads it, never sees the recipient or the subject (limit L51)."""
    from test_channel_grants_mailbox import accept as accept_holder      # the channel keeps the list without ask-mail; SENDER's profile `holder` lists it
    accept_holder(world["path"], {"messaging": ["read", "talk", "mail-send", "approve-effect-send-own", "ask-mail"]})
    started = send(world, channel="messaging", sender=SENDER)
    neutral = phrases.text("NAT_READ_REPLY", None)
    typed = ops.say(world["path"], f"/pending {started['pending']}", channel="messaging", sender=SENDER)
    assert TO in typed["reply"] and SUBJECT in typed["reply"], "the holder reads the whole card"
    words = ops.say(world["path"], f"task {started['task']}", channel="messaging", sender=SENDER)
    assert "Mail: send from your account" in words["reply"]
    messages = ops.conversation(world["path"], channel="mcp")["messages"]
    assert [m["text"] for m in messages if m["role"] == "assistant"] == [neutral, neutral]
    assert not any(TO in m["text"] or SUBJECT in m["text"] for m in messages)
