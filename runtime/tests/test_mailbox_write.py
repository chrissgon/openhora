"""A change to the person's own mailbox as an external effect (package W3): runtime/step_mailbox.py, runtime/mailbox_document.py, runtime/effect_mailbox.py,
runtime/ops_mailbox.py, runtime/ops_step_seams.py (`mailbox_read`), runtime/ops_step_effects.py, runtime/item_refs.py (the references to the messages) and the two mailbox
writers (providers/writer/gmail.py and outlook-mail.py) as the processes the runtime starts. The services are stand-ins on loopback (providers/writer/tests/
fake_gmail_modify.py, fake_graph_mail_write.py): no Google or Microsoft host is ever called, no credential is real, every address is on a `.example` or `example.com` name.
The messages the person names come from a real snapshot of a mail source (a stand-in reader behind the one caller of the readers). Held here, and the limit each belongs to
(the tests named test_limit_N_ are the ones the rows of contracts/runtime.md name):

  L55  a write is made only by `approve` with the hash of the exact document: no approval, another hash, an edited effect file or a writer that would send other requests
       writes nothing; a mail folder the project's `accounts` does not name is refused at the start and again at the approval; the request list of an archive, a move, a
       mark, a trash and a draft is exactly the one the card says, and nothing is ever sent;
  L56  a message is changed only as it was read: a card is `stale` as a whole when any message moved between the card and the approval (labels, changeKey or folder, or gone),
       nothing is sent, the decision is answered and the task starts over from the step that reads;
  L57  nothing is removed for good: a trash is Gmail's `messages.trash` and a move to Deleted Items, never a removal;
  L58  the writer is started only by the effect module and the read-only seam: the seam reads messages and folders and asks for a dry run (no credential), nothing else;
  L59  the writer's environment is the minimum plus the one token of the account asked for; no token is in the store, the card or the effect file;
  L60  a reply goes to the From address of the message as the snapshot's index recorded it and as the mailbox says now, never to its Reply-To.

The preparation reads each message from the mailbox (the card shows its subject and sender as the mailbox holds them now), sends nothing and writes no file but the effect
document. A partial failure after the first message is `unknown`, names the positions that are done, and approving again finishes the others.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_mailbox_write.py
"""
from __future__ import annotations

import base64
import copy
import datetime
import email
import email.policy
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

import pytest

import standin_tree as st
import test_sources_mail as tsm
from sources_fixture import standin_convert

sys.path.insert(0, str(st.REPO / "providers" / "writer" / "tests"))
import fake_gmail_modify as fgm  # noqa: E402  (providers/writer/tests/fake_gmail_modify.py: the stand-in for Gmail)
import fake_graph_mail_write as fgr  # noqa: E402  (providers/writer/tests/fake_graph_mail_write.py: the stand-in for Graph)

lab = st.load("lab")
ops = st.load("ops")
ops_core = st.load("ops_core")
ops_steps = st.load("ops_steps")
ops_sources = st.load("ops_sources")
ops_step_effects = st.load("ops_step_effects")
ops_step_seams = st.load("ops_step_seams")
effects = st.load("effects")
effect_mailbox = st.load("effect_mailbox")
mailbox_document = st.load("mailbox_document")
step_mailbox = st.load("step_mailbox")
ops_mailbox = st.load("ops_mailbox")
item_refs = st.load("item_refs")
sources = st.load("sources")
sources_mail = st.load("sources_mail")
steps = st.load("steps")
phrases = st.load("phrases")
operations = st.load("operations")
project_config = st.load("project_config")
cards = st.load("messaging_cards")

ACCOUNTS = {"google": {"address": fgm.ACCOUNT, "mail_folders": {"bills": "Label_7", "later": "Label_9"}},
            "microsoft": {"address": fgr.ADDRESS, "mail_folders": {"bills": fgr.NAMED}}}
MESSAGES = "/gmail/v1/users/me/messages"
GRAPH_MESSAGES = "/v1.0/me/messages"
UTC = datetime.timezone.utc
WHEN = {1: "2026-10-17T09:00:00Z", 2: "2026-10-16T14:30:00Z", 3: "2026-10-15T08:00:00Z"}      # the newest first: inbox#1 is m1
SNAPSHOT_SUBJECTS = {1: "Appointment confirmed", 2: "Your order", 3: "Hello"}
LIVE_SUBJECTS = {1: "Appointment confirmed for Monday", 2: "Your order has shipped", 3: "Hello again"}
SENDERS = {1: "ana@clinic.example", 2: "bob@shop.example", 3: "cleo@club.example"}


def ms(stamp: str) -> str:
    return str(int(datetime.datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).timestamp() * 1000))


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("WB_LOCAL_EVIDENCE_DIR", str(tmp_path / "evidence"))
    built = st.build(tmp_path, monkeypatch, lab)
    tree = built["tree"]
    for rel in ("providers/writer/gmail.py", "providers/writer/outlook-mail.py", "providers/_google.py", "providers/_msgraph.py", "providers/_writer_mailbox.py", "providers/_email.py",
                "providers/secrets/resolver.py", "providers/secrets/password_managers.py"):
        (tree / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(st.REPO / rel, tree / rel)
    state = tmp_path / "writer-state"
    state.mkdir()
    os.chmod(state, 0o700)
    google, graph = fgm.FakeGmail(), fgr.FakeGraphMail()
    monkeypatch.setenv("OPENHORA_STATE_DIR", str(state))
    monkeypatch.setenv("TZ", "America/Sao_Paulo")
    time.tzset()
    monkeypatch.setenv("GOOGLE_ACCOUNT_TOKEN", google.record_json())
    monkeypatch.setenv("MICROSOFT_ACCOUNT_TOKEN", graph.record_json())
    monkeypatch.setenv("UNRELATED_SECRET", "must-not-reach-a-writer")
    names = ("WRITER_MAIL_GOOGLE_API_BASE", "WRITER_MAIL_GOOGLE_TOKEN_URL", "WRITER_MAIL_OUTLOOK_API_BASE", "WRITER_MAIL_OUTLOOK_TOKEN_URL")
    for fake, pair in ((google, names[:2]), (graph, names[2:])):
        for name, value in zip(pair, (fake.base, fake.token_url)):
            monkeypatch.setenv(name, value)
    path = built["project"] / "docs" / "workbench" / "runtime.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["accounts"] = ACCOUNTS
    path.write_text(json.dumps(raw), encoding="utf-8")
    monkeypatch.setattr(ops_core, "ROOT", str(tree))
    resolver = project_config.resolver(str(tree))      # the test variables reach the writer the runtime starts; it runs on this interpreter (no install)
    monkeypatch.setattr(resolver, "ENV_MINIMUM", resolver.ENV_MINIMUM + names)
    monkeypatch.setattr(resolver, "interpreter_for", lambda script: [sys.executable])
    monkeypatch.setattr(project_config, "resolver", lambda workbench: resolver)      # one resolver module for the seam and the effect
    project = str(built["project"])
    shown = ops.config(project)      # the accounts are a widening: the person types the hash of what `config` lists
    ops.accept_config(project, shown["sha256"], widen=shown["widening_sha256"])
    # the mail sources: a real snapshot of a stand-in reader, so that `inbox#n` and `work#n` are references the index resolves
    readers = tsm.Providers()
    readers.mail["gmail"] = [tsm.message(n, WHEN[n], sender=f"Ana Lima <{SENDERS[n]}>" if n == 1 else f"Sender <{SENDERS[n]}>", subject=SNAPSHOT_SUBJECTS[n], thread_id=f"t{n}",
                                         reply_to="desk@clinic.example" if n == 1 else None, headers={"Message-ID": f"<a{n}@mail.example>"}) for n in (1, 2, 3)]
    readers.mail["outlook"] = [tsm.message(n, WHEN[n], sender=f"Sender <{SENDERS[n]}>", subject=SNAPSHOT_SUBJECTS[n], source="outlook", change_key=f"CK{n}",
                                           thread_id=f"c{n}", headers={"Message-ID": f"<o{n}@work.example>"}) for n in (1, 2, 3)]
    monkeypatch.setattr(sources, "provider_convert", lambda cfg, call=None: standin_convert)

    def provider_call(cfg, cls, implementation, verb, args, *, call=None, timeout=sources_mail.PROVIDER_TIMEOUT):
        return tsm.ORIGINAL_CALL(cfg, cls, implementation, verb, args, call=call or readers, timeout=timeout)
    monkeypatch.setattr(sources_mail, "provider_call", provider_call)
    ops_sources.source_mail(project, "inbox", "gmail:box=inbox;days=7;max=50")
    ops_sources.source_mail(project, "work", "outlook:box=inbox;days=7;max=50")
    for n in (1, 2, 3):
        google.add_message(f"m{n}", LIVE_SUBJECTS[n], f"Display Name <{SENDERS[n]}>", ["INBOX", "UNREAD"], internal_date=ms(WHEN[n]), thread=f"t{n}", message_id=f"<a{n}@mail.example>")
        graph.add_message(f"m{n}", LIVE_SUBJECTS[n], SENDERS[n], folder="inbox", internet_id=f"<o{n}@work.example>", conversation=f"c{n}", receivedDateTime=WHEN[n],
                          changeKey=f"CK{n}")
    graph.messages["m1"]["changeKey"] = "CK1"
    yield {**built, "path": project, "tmp": tmp_path, "google": google, "graph": graph, "state": state, "resolver": resolver, "readers": readers}
    google.close()
    graph.close()
    monkeypatch.undo()
    time.tzset()


def archive(world, refs="inbox#1,inbox#2", account="google", **kw):
    return ops.mail_archive(world["path"], account, refs, **kw)


def item_of(world, started):
    ctx = ops_core.context(world["path"])
    return ctx["store"].pending_get(ctx["conn"], started["pending"])


def approve(world, started_or_item, channel="terminal"):
    pending = started_or_item["pending"] if "pending" in started_or_item else started_or_item["id"]
    ctx = ops_core.context(world["path"])
    item = ctx["store"].pending_get(ctx["conn"], pending)
    return ops.approve(world["path"], pending, sha256=item["payload_sha256"], channel=channel, sender=("telegram:830461975213" if channel == "messaging" else None))


def effect_doc(world, started, cycle=0):
    cfg = ops_core.context(world["path"])["cfg"]
    return json.loads((Path(ops_step_effects.effect_dir(cfg, started["task"], cycle)) / "effect.json").read_text(encoding="ascii"))


def task_state(world, task):
    ctx = ops_core.context(world["path"])
    return ctx["store"].task_get(ctx["conn"], task)["state"]


def rows(world):
    ctx = ops_core.context(world["path"])
    return ctx["store"].tasks_list(ctx["conn"]), ctx["store"].pending_list(ctx["conn"], "open")


def refused(world, call, *args, **kw):
    with pytest.raises(ops.OpsError) as why:
        call(world["path"], *args, **kw)
    return why.value


def calls(fake, token_path="/token"):
    """Every request after the token POSTs: (method, path, query, body)."""
    return [(r["method"], r["path"], r["query"], r["body"]) for r in fake.requests if r["path"] != token_path]


def gmail_calls(world):
    return [(m, p) for m, p, _, _ in calls(world["google"])]


def graph_calls(world):
    return [(r["method"], r["path"]) for r in world["graph"].graph_requests()]


def reaccept(world, **more):
    """Accept the configuration as it is now, as the person does: the hash of the file, and of the widening list it shows when it widens."""
    shown = ops.config(world["path"])
    return ops.accept_config(world["path"], shown["sha256"], widen=shown.get("widening_sha256"), **more)


def edit_accounts(world, change):
    path = Path(world["path"]) / "docs" / "workbench" / "runtime.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    change(raw["accounts"])
    path.write_text(json.dumps(raw), encoding="utf-8")
    reaccept(world)


# --- an archive: the card, and nothing written ----------------------------------------------------------------------------------------------------------


def test_an_archive_prepares_a_card_of_every_message_by_the_subject_and_sender_the_mailbox_holds_now_and_writes_nothing(world):
    started = archive(world)
    assert set(started) == {"request", "task", "pending", "word", "on_cards"} and started["word"] == "mailbox" and started["on_cards"] is True
    item = item_of(world, started)
    assert item["kind"] == "effect" and item["title"] == "Mailbox: archive messages" and "Appointment" not in item["title"]
    assert item["payload"]["step"] == {"kind": "mailbox-change", "step": "mailbox"} and phrases.card_valid(item["payload"]["card"])
    assert item["body"] == phrases.card_text(item["payload"]["card"])
    lines = item["body"].splitlines()
    assert lines[0] == f"Code makes this change in your mailbox {fgm.ACCOUNT} after your approval. Nothing is sent and nothing is deleted."
    assert lines[1] == f"Account: google ({fgm.ACCOUNT})" and lines[2] == "Archive: 2 message(s)"
    assert lines[3] == "1. 2026-10-17 06:00 · from ana@clinic.example · Appointment confirmed for Monday", "the subject is the LIVE one, not the snapshot's, and the sender is the address alone"
    assert lines[4] == "2. 2026-10-16 11:30 · from bob@shop.example · Your order has shipped"
    assert lines[5].startswith("Read from your mailbox at 20") and lines[6].startswith("Chosen from a snapshot read at 20") and len(lines) == 7
    doc = effect_doc(world, started)
    assert doc["effect"] == "mailbox" and doc["action"] == "archive" and doc["implementation"] == "gmail" and doc["messages"][0]["ref"] == "inbox#1"
    assert doc["messages"][0]["labels"] == ["INBOX", "UNREAD"] and doc["messages"][0]["change_key"] is None and doc["zone"] == "America/Sao_Paulo"
    assert [m for m, _, _, _ in calls(world["google"]) if m != "GET"] == [] and gmail_calls(world) == [("GET", f"{MESSAGES}/m1"), ("GET", f"{MESSAGES}/m2")], "reads only"
    first = calls(world["google"])[0]
    assert first[2]["format"] == "metadata" and first[2]["metadataHeaders"] == ["Subject", "From", "Date", "Message-ID"], "no body is read"
    tasks, pending = rows(world)
    assert {t["id"]: t["title"] for t in tasks}[started["task"]] == "Mailbox: archive messages" and len(pending) == 1
    assert "Display Name" not in item["body"], "the sender's display name is another person's words and is dropped"


def test_the_approval_of_an_archive_is_one_batch_modify_after_a_read_of_each_message_and_nothing_is_ever_sent(world):
    started = archive(world)
    item = item_of(world, started)
    done = approve(world, started)
    assert done["task_state"] == "done" and done["result"]["done"] is True and done["result"]["replayed"] is False and done["result"]["action"] == "archive"
    assert done["result"]["count"] == 2 and done["result"]["idempotency_key"].startswith("box-")
    google = world["google"]
    assert gmail_calls(world)[2:] == [("GET", f"{MESSAGES}/m1"), ("GET", f"{MESSAGES}/m2"), ("GET", f"{MESSAGES}/m1"), ("GET", f"{MESSAGES}/m2"), ("POST", f"{MESSAGES}/batchModify")]
    assert google.writes() == [("POST", f"{MESSAGES}/batchModify", {}, {"ids": ["m1", "m2"], "addLabelIds": [], "removeLabelIds": ["INBOX"]})]
    assert google.messages["m1"]["labelIds"] == ["UNREAD"] and google.messages["m3"]["labelIds"] == ["INBOX", "UNREAD"] and google.unexpected() == [] and world["graph"].requests == []
    ctx = ops_core.context(world["path"])
    recorded = ctx["store"].approvals_list(ctx["conn"])
    assert [a["payload_sha256"] for a in recorded] == [item["payload_sha256"]] and all("Appointment" not in str(a) for a in recorded), "the record of the approval holds none of the mail"


def test_a_move_adds_the_label_the_project_names_and_leaves_the_inbox_unless_the_account_says_otherwise(world):
    started = ops.mail_move(world["path"], "google", "inbox#1", "bills")
    assert "Move to \"bills\": 1 message(s)" in item_of(world, started)["body"] and effect_doc(world, started)["folder_id"] == "Label_7"
    approve(world, started)
    assert world["google"].writes() == [("POST", f"{MESSAGES}/batchModify", {}, {"ids": ["m1"], "addLabelIds": ["Label_7"], "removeLabelIds": ["INBOX"]})]
    edit_accounts(world, lambda accounts: accounts["google"].__setitem__("move_removes_inbox", False))
    world["google"].requests.clear()
    again = ops.mail_move(world["path"], "google", "inbox#2", "later")
    assert effect_doc(world, again)["remove_inbox"] is False
    approve(world, again)
    assert world["google"].writes() == [("POST", f"{MESSAGES}/batchModify", {}, {"ids": ["m2"], "addLabelIds": ["Label_9"], "removeLabelIds": []})]


def test_a_mark_changes_the_unread_label_and_a_mark_that_changes_nothing_is_refused(world):
    started = ops.mail_mark(world["path"], "google", "inbox#1,inbox#3", "read")
    assert "Mark as read: 2 message(s)" in item_of(world, started)["body"]
    approve(world, started)
    assert world["google"].writes() == [("POST", f"{MESSAGES}/batchModify", {}, {"ids": ["m1", "m3"], "addLabelIds": [], "removeLabelIds": ["UNREAD"]})]
    again = refused(world, ops.mail_mark, "google", "inbox#1", "read")
    assert "already as asked" in str(again) and "position" in str(again) and again.code == 1
    later = ops.mail_mark(world["path"], "google", "inbox#1", "unread")
    approve(world, later)
    assert "UNREAD" in world["google"].messages["m1"]["labelIds"]
    assert rows(world)[1] == []


def test_a_trash_is_one_trash_call_per_message_and_a_message_in_the_trash_already_is_refused(world):
    started = ops.mail_trash(world["path"], "google", "inbox#1,inbox#2")
    body = item_of(world, started)["body"]
    assert "Move to the trash (Gmail empties it after 30 days): 2 message(s)" in body
    approve(world, started)
    assert world["google"].writes() == [("POST", f"{MESSAGES}/m1/trash", {}, None), ("POST", f"{MESSAGES}/m2/trash", {}, None)]
    assert all("TRASH" in world["google"].messages[m]["labelIds"] for m in ("m1", "m2")) and world["google"].unexpected() == []
    again = refused(world, ops.mail_trash, "google", "inbox#1")
    assert "already as asked" in str(again)


def test_a_message_that_is_not_in_the_inbox_cannot_be_archived_again(world):
    world["google"].messages["m2"]["labelIds"] = ["Label_7"]
    error = refused(world, ops.mail_archive, "google", "inbox#1,inbox#2")
    assert "already as asked" in str(error) and "positions 2 are" in str(error)
    assert rows(world) == ([task for task in rows(world)[0]], []) and {t["state"] for t in rows(world)[0]} <= {"cancelled"}


# --- Outlook -----------------------------------------------------------------------------------------------------------------------------------------


def test_an_outlook_archive_moves_each_message_to_the_archive_folder_after_one_read_of_the_folder_and_each_message(world):
    started = archive(world, "work#1,work#2", "microsoft")
    doc = effect_doc(world, started)
    assert doc["implementation"] == "outlook-mail" and doc["folder_id"] == "archive" and doc["messages"][0]["change_key"] == "CK1" and doc["messages"][0]["folder_id"] == fgr.FOLDERS["inbox"]
    assert "Archive: 2 message(s)" in item_of(world, started)["body"] and "1. 2026-10-17 06:00 · from ana@clinic.example · Appointment confirmed for Monday" in item_of(world, started)["body"]
    assert graph_calls(world) == [("GET", "/v1.0/me/mailFolders/archive"), ("GET", f"{GRAPH_MESSAGES}/m1"), ("GET", f"{GRAPH_MESSAGES}/m2")]
    world["graph"].requests.clear()
    done = approve(world, started)
    assert done["task_state"] == "done" and done["result"]["count"] == 2
    assert world["graph"].writes() == [("POST", f"{GRAPH_MESSAGES}/m1/move", {}, {"destinationId": "archive"}), ("POST", f"{GRAPH_MESSAGES}/m2/move", {}, {"destinationId": "archive"})]
    assert sorted(m["parentFolderId"] for m in world["graph"].messages.values() if m["id"].startswith("AAMkMoved")) == [fgr.FOLDERS["archive"]] * 2
    assert world["graph"].unexpected() == [] and world["google"].requests == []


def test_an_outlook_move_goes_to_the_folder_the_project_names_and_a_trash_to_deleted_items_and_a_mark_is_one_patch(world):
    moved = ops.mail_move(world["path"], "microsoft", "work#1", "bills")
    assert effect_doc(world, moved)["folder_id"] == fgr.NAMED
    approve(world, moved)
    assert world["graph"].writes() == [("POST", f"{GRAPH_MESSAGES}/m1/move", {}, {"destinationId": fgr.NAMED})]
    world["graph"].requests.clear()
    trashed = ops.mail_trash(world["path"], "microsoft", "work#2")
    assert "Move to Deleted Items (Outlook deletes them from there after 30 days): 1 message(s)" in item_of(world, trashed)["body"]
    approve(world, trashed)
    assert world["graph"].writes() == [("POST", f"{GRAPH_MESSAGES}/m2/move", {}, {"destinationId": "deleteditems"})]
    world["graph"].requests.clear()
    marked = ops.mail_mark(world["path"], "microsoft", "work#3", "read")
    approve(world, marked)
    assert world["graph"].writes() == [("PATCH", f"{GRAPH_MESSAGES}/m3", {}, {"isRead": True})] and world["graph"].messages["m3"]["isRead"] is True
    assert world["graph"].unexpected() == []
    again = refused(world, ops.mail_mark, "microsoft", "work#3", "read")
    assert "already as asked" in str(again)


def test_an_outlook_message_already_in_the_archive_is_refused_and_a_folder_that_is_not_there_is_refused(world):
    world["graph"].messages["m1"]["parentFolderId"] = fgr.FOLDERS["archive"]
    error = refused(world, ops.mail_archive, "microsoft", "work#1")
    assert "already as asked" in str(error)
    del world["graph"].folders["archive"]
    world["graph"].known_folder_ids.discard(fgr.FOLDERS["archive"])
    gone = refused(world, ops.mail_archive, "microsoft", "work#2")
    assert "not in the mailbox" in str(gone)
    assert world["graph"].writes() == []


# --- the mail folders the project names ---------------------------------------------------------------------------------------------------------------


def test_limit_55_a_mail_folder_the_project_does_not_name_is_refused_before_anything_is_made_and_a_label_that_means_something_else_is_too(world):
    for folder in ("other", "Bills", "../x", "", "trash"):
        error = refused(world, ops.mail_move, "google", "inbox#1", folder)
        assert error.code in (1, 2), folder
    assert rows(world)[1] == [] and world["google"].requests == []
    edit_accounts(world, lambda accounts: (accounts["google"].__setitem__("mail_folders", {"trash": "TRASH", "spam": "SPAM", "sent": "SENT", "inbox": "INBOX", "unread": "UNREAD",
                                                                                            "bills": "Label_7"}),
                                           accounts["microsoft"].__setitem__("mail_folders", {"drafts": "drafts", "outbox": "outbox", "purge": "recoverableitemspurges",
                                                                                              "bills": fgr.NAMED})))
    for name in ("trash", "spam", "sent", "inbox", "unread"):
        assert "cannot be a place for a move" in str(refused(world, ops.mail_move, "google", "inbox#1", name)), name
    for name in ("drafts", "outbox", "purge"):
        assert "cannot be a place for a move" in str(refused(world, ops.mail_move, "microsoft", "work#1", name)), name
    assert world["google"].requests == [] and world["graph"].writes() == []


def test_limit_55_a_mail_folder_the_configuration_stops_naming_between_the_card_and_the_approval_writes_nothing(world):
    started = ops.mail_move(world["path"], "google", "inbox#1", "bills")
    edit_accounts(world, lambda accounts: accounts["google"].__setitem__("mail_folders", {"later": "Label_9"}))
    world["google"].requests.clear()
    with pytest.raises(ops.OpsError) as why:
        approve(world, started)
    assert "bills" in str(why.value) and world["google"].requests == []
    edit_accounts(world, lambda accounts: accounts["google"].__setitem__("mail_folders", {"bills": "Label_8"}))      # the same name, another label
    with pytest.raises(ops.OpsError) as other:
        approve(world, started)
    assert "id of the folder is not the one" in str(other.value) and world["google"].requests == []
    edit_accounts(world, lambda accounts: accounts["google"].update(mail_folders={"bills": "Label_7"}, move_removes_inbox=False))
    with pytest.raises(ops.OpsError) as inbox:
        approve(world, started)
    assert "leaving the inbox" in str(inbox.value) and world["google"].writes() == []


# --- references, accounts and counts -------------------------------------------------------------------------------------------------------------------


def test_a_reference_that_cannot_be_resolved_is_refused_with_a_sentence_of_the_phrase_table_and_nothing_is_made(world):
    cases = {"inbox#9": "does not exist", "inbox#0": "start at 1", "nothing#1": "There is no source nothing", "inbox#x": "is not a reference to a message", "created:3": "created:3 does not name a message of your mailbox",
             "inbox": "is not a reference", "": "Name at least one message", "inbox#1,inbox#1": "is named twice"}
    for ref, sentence in cases.items():
        error = refused(world, ops.mail_archive, "google", ref)
        assert sentence in str(error), (ref, str(error))
    assert rows(world)[1] == [] and world["google"].requests == []
    other = refused(world, ops.mail_archive, "google", "work#1")      # an Outlook message asked on the Google account
    assert "another account than the google account" in str(other)
    twenty_one = ",".join(f"inbox#{i}" for i in range(1, 22))
    many = refused(world, ops.mail_archive, "google", twenty_one)
    assert "at most 20 messages; 21 were named" in str(many) and many.code == 2


def test_every_item_ref_error_code_has_its_sentence_in_both_languages_with_only_the_fields_the_reference_gives():
    source = (st.REPO / "runtime" / "item_refs.py").read_text(encoding="utf-8")
    codes = {"malformed", "zero", "not_readable", "past_end", "no_source", "not_snapshot", "wrong_kind", "no_version", "stale", "no_index", "integrity", "created_unavailable",
             "created_unknown"}
    raised = {code for code in re.findall(r'ItemRefError\("([a-z_]+)"', source)}
    assert raised == codes and set(ops_mailbox.REF_KEY) == codes, "a code item_refs raises that this map does not know would reach the person as a malformed reference"
    for code, key in ops_mailbox.REF_KEY.items():
        for tag in ("en", "pt-BR"):
            sentence = phrases.TABLE[tag][key]
            assert phrases._fields_of(sentence) <= {"ref", "source"}, (code, tag)
        assert phrases.TABLE["en"][key] != phrases.TABLE["pt-BR"][key] and key.startswith("ACCT_")
        assert phrases.localize(phrases.en(key).format(ref="inbox#2", source="inbox"), {"language": "pt-BR"}) == phrases.TABLE["pt-BR"][key].format(ref="inbox#2", source="inbox"), code


# --- a draft -----------------------------------------------------------------------------------------------------------------------------------------


NEW_DRAFT = {"to": "joe@shop.example", "cc": "amy@shop.example", "bcc": "boss@shop.example", "subject": "Haircut on Monday", "body": "Hello Joe,\nSee you at 13:00.\n"}


def test_a_new_gmail_draft_is_shown_whole_saved_by_one_post_and_never_sent(world):
    started = ops.mail_draft(world["path"], "google", **NEW_DRAFT)
    item = item_of(world, started)
    assert item["title"] == "Mailbox: save a draft" and item["body"].splitlines()[0].endswith("It is not sent: it waits in your Drafts for you to read and send yourself.")
    for needle in ("To: joe@shop.example", "Cc: amy@shop.example", "Bcc: boss@shop.example", "Subject: Haircut on Monday", "The draft's text, exactly as it will be saved (every line starts with \u2502):\n\u2502 Hello Joe,\n\u2502 See you at 13:00."):
        assert needle in item["body"], needle
    assert world["google"].requests == [], "preparing a new draft reads nothing and opens no connection"
    done = approve(world, started)
    assert done["task_state"] == "done" and done["result"]["action"] == "draft" and done["result"]["draft_id"] in world["google"].drafts
    [(method, path, _, body)] = world["google"].writes()
    assert (method, path) == ("POST", "/gmail/v1/users/me/drafts") and set(body) == {"message"}
    parsed = email.message_from_bytes(base64.urlsafe_b64decode(body["message"]["raw"]), policy=email.policy.default)
    assert parsed["From"] == fgm.ACCOUNT and parsed["To"] == "joe@shop.example" and parsed["Subject"] == "Haircut on Monday" and parsed["Bcc"] == "boss@shop.example"
    assert world["google"].unexpected() == [] and not [r for r in world["google"].requests if "send" in r["path"]]


def test_a_reply_draft_goes_to_the_sender_the_index_recorded_never_to_the_reply_to_and_follows_the_thread(world):
    started = ops.mail_draft(world["path"], "google", message="inbox#1", body="Thanks, Monday works.\n")
    doc = effect_doc(world, started)
    assert doc["draft"]["to"] == ["ana@clinic.example"] and doc["draft"]["cc"] == [] and doc["draft"]["bcc"] == [] and doc["draft"]["subject"] == "Re: Appointment confirmed for Monday"
    reply = doc["draft"]["reply"]
    assert reply["reply_to"] == "desk@clinic.example" and reply["message_id"] == "<a1@mail.example>" and reply["thread_id"] == "t1" and reply["ref"] == "inbox#1"
    body = item_of(world, started)["body"]
    assert "Reply to: ana@clinic.example, the sender of inbox#1 (2026-10-17 06:00, 'Appointment confirmed for Monday')" in body
    assert "The message asks replies to go to desk@clinic.example: this draft goes to the sender above, not there." in body and "To: ana@clinic.example" in body
    approve(world, started)
    [(_, _, _, sent)] = world["google"].writes()
    assert sent["message"]["threadId"] == "t1"
    parsed = email.message_from_bytes(base64.urlsafe_b64decode(sent["message"]["raw"]), policy=email.policy.default)
    assert parsed["To"] == "ana@clinic.example" and "desk@clinic.example" not in str(parsed) and parsed["In-Reply-To"] == "<a1@mail.example>" and parsed["Cc"] is None


def test_an_outlook_reply_draft_is_create_reply_then_one_patch_to_the_sender_and_a_new_one_is_one_post(world):
    started = ops.mail_draft(world["path"], "microsoft", message="work#2", body="Noted.\n")
    doc = effect_doc(world, started)
    assert doc["draft"]["to"] == ["bob@shop.example"] and doc["draft"]["subject"] == "Re: Your order has shipped" and doc["draft"]["reply"]["thread_id"] is None
    world["graph"].requests.clear()
    done = approve(world, started)
    draft = done["result"]["draft_id"]
    assert [(m, p) for m, p, _, _ in calls(world["graph"]) if m != "GET"] == [("POST", f"{GRAPH_MESSAGES}/m2/createReply"), ("PATCH", f"{GRAPH_MESSAGES}/{draft}")]
    assert world["graph"].messages[draft]["toRecipients"] == [{"emailAddress": {"address": "bob@shop.example"}}] and world["graph"].unexpected() == []
    new = ops.mail_draft(world["path"], "microsoft", **NEW_DRAFT)
    world["graph"].requests.clear()
    approve(world, new)
    assert [(m, p) for m, p, _, _ in calls(world["graph"])] == [("POST", "/v1.0/me/messages")]


def test_a_reply_to_a_message_whose_sender_changed_since_the_snapshot_is_refused(world):
    world["google"].messages["m1"]["headers"]["From"] = "Someone Else <other@clinic.example>"
    error = refused(world, ops.mail_draft, "google", message="inbox#1", body="Hi")
    assert "not the one the snapshot recorded" in str(error) and rows(world)[1] == []
    world["google"].messages["m2"]["headers"]["Message-ID"] = "no-brackets"
    bad = refused(world, ops.mail_draft, "google", message="inbox#2", body="Hi")
    assert "no thread or Message-ID a reply can follow" in str(bad) and rows(world)[1] == [] and world["google"].writes() == []


def test_a_draft_that_is_not_in_its_form_is_refused_and_leaves_nothing_behind(world):
    for more in ({"to": ""}, {"to": "not an address"}, {"subject": ""}, {"subject": "two\nlines"}, {"body": "bad\x00"}, {"to": ",".join(f"a{i}@x.example" for i in range(21))}, {"cc": "joe@shop.example"}):
        error = refused(world, ops.mail_draft, "google", **{**NEW_DRAFT, **more})
        assert error.code in (1, 2), more
    secret = "token " + "ghp_" + "abcdefghijklmnopqrstuvwxyz0123456789"
    assert "credential" in str(refused(world, ops.mail_draft, "google", **{**NEW_DRAFT, "body": secret}))
    mixed = refused(world, ops.mail_draft, "google", message="inbox#1", body="Hi", subject="Mine")
    assert "give only the message and the body" in str(mixed)
    two = refused(world, ops.mail_draft, "google", message="inbox#1,inbox#2", body="Hi")
    assert "one reference" in str(two)
    no_body = refused(world, ops.mail_draft, "google", to="joe@shop.example", subject="x")
    assert "needs a body" in str(no_body)
    assert rows(world)[1] == [] and {t["state"] for t in rows(world)[0]} <= {"cancelled"} and world["google"].writes() == []


# --- L55: nothing is written without the approval of the exact hash ------------------------------------------------------------------------------------


def test_limit_55_no_approval_another_hash_an_edited_file_or_a_writer_that_would_send_something_else_writes_nothing_to_the_mailbox(world):
    started = archive(world)
    doc = effect_doc(world, started)
    sent = []
    spy = lambda verb, args, implementation=None: sent.append((verb, args)) or {}          # noqa: E731  (a writer that must not be reached)
    for approval in (None, {}, {"scope": "plan", "status": "pending-execution", "payload_sha256": "0" * 64},
                     {"scope": "action", "status": "pending-execution", "payload_sha256": "0" * 64},
                     {"scope": "action", "status": "revoked", "payload_sha256": effect_mailbox.sha(effects._text(doc))}):
        with pytest.raises(effects.EffectError) as why:
            effect_mailbox.execute(doc, approval, spy, doc["idempotency_key"])
        assert why.value.kind == "deviation"
    good = {"scope": "action", "status": "pending-execution", "payload_sha256": effect_mailbox.sha(effects._text(doc))}
    with pytest.raises(effects.EffectError) as other_key:
        effect_mailbox.execute(doc, good, spy, "box-" + "0" * 32)
    assert other_key.value.kind == "deviation" and sent == []
    state = {"messages": [{"id": m["id"], "found": True, "labels": m["labels"], "done": None} for m in doc["messages"]]}
    dry_other = lambda verb, args, implementation=None: state if verb == "message-meta" else {"would_sha256": "f" * 64} if "--dry-run" in args else sent.append(verb)       # noqa: E731
    with pytest.raises(effects.EffectError) as would:
        effect_mailbox.execute(doc, good, dry_other, doc["idempotency_key"])
    assert would.value.kind == "deviation" and "previewed" in would.value.reason and sent == []
    cfg = ops_core.context(world["path"])["cfg"]
    path = Path(ops_step_effects.effect_dir(cfg, started["task"], 0)) / "effect.json"
    path.write_bytes(path.read_bytes().replace(b"inbox#1", b"inbox#2"))
    world["google"].requests.clear()
    with pytest.raises(ops.OpsError) as edited:
        approve(world, started)
    assert "hash changed" in str(edited.value) and world["google"].requests == [] and task_state(world, started["task"]) == "waiting"
    with pytest.raises(ops.OpsError) as wrong:
        ops.approve(world["path"], started["pending"], sha256="0" * 64, channel="terminal")
    assert "nothing was approved" in str(wrong.value) and world["google"].requests == []


def test_the_dry_run_hash_the_card_holds_is_what_the_confirmed_run_sends(world):
    started = ops.mail_trash(world["path"], "google", "inbox#1,inbox#2")
    doc = effect_doc(world, started)
    approve(world, started)
    sent = [{"method": m, "path": p, "query": q, "headers": {}, "body": b} for m, p, q, b in world["google"].writes()]
    assert mailbox_document.requests_match(doc, {"requests": sent}) is True
    from_writer = {"requests": sent}
    digest = effect_mailbox.sha(json.dumps(from_writer, sort_keys=True, ensure_ascii=True, separators=(",", ":")))
    assert digest == doc["dry_run_sha256"], "the writer's would_sha256 is the hash of the requests it then sent"


@pytest.mark.parametrize("account, action, tamper", [
    ("google", "trash", lambda would: would["requests"].append({"method": "POST", "path": "/gmail/v1/users/me/messages/m1/send", "query": {}, "headers": {}, "body": None})),
    ("google", "archive", lambda would: would["requests"][0]["body"].update(addLabelIds=["TRASH"])),
    ("microsoft", "archive", lambda would: would["requests"].append({"method": "POST", "path": "/me/messages/m1/send", "query": {}, "headers": {}, "body": None})),
    ("microsoft", "mark", lambda would: would["requests"][0]["body"].update(isRead=False)),
    ("microsoft", "archive", lambda would: would["requests"][0]["body"].update(destinationId="deleteditems"))])
def test_a_dry_run_that_adds_a_request_or_changes_a_body_is_not_what_the_arguments_say(world, account, action, tamper):
    refs = "inbox#1" if account == "google" else "work#1"
    started = {"trash": lambda: ops.mail_trash(world["path"], account, refs), "archive": lambda: ops.mail_archive(world["path"], account, refs),
               "mark": lambda: ops.mail_mark(world["path"], account, refs, "read")}[action]()
    doc = effect_doc(world, started)
    would = ops_step_seams.MailboxReader(ops_core.context(world["path"])).dry_run(doc)["would"]
    assert mailbox_document.requests_match(doc, would) is True
    tampered = copy.deepcopy(would)
    tamper(tampered)
    assert mailbox_document.requests_match(doc, tampered) is False
    assert mailbox_document.requests_match(doc, {"requests": []}) is False and mailbox_document.requests_match(doc, None) is False


# --- L56: a card is stale as a whole when any message moved -------------------------------------------------------------------------------------------


def test_limit_56_a_message_that_moved_between_the_card_and_the_approval_makes_the_whole_card_stale_nothing_is_sent_and_the_task_starts_over(world):
    started = archive(world, "inbox#1,inbox#2,inbox#3")
    world["google"].messages["m2"]["labelIds"] = ["INBOX"]           # somebody read it meanwhile
    world["google"].requests.clear()
    with pytest.raises(ops.OpsError) as stale:
        approve(world, started)
    assert "positions 2 of the card" in str(stale.value) and "starts over" in str(stale.value)
    assert [m for m, _, _, _ in calls(world["google"])] == ["GET", "GET", "GET"], "every message was read again, compared, and nothing was written"
    assert world["google"].messages["m1"]["labelIds"] == ["INBOX", "UNREAD"] and world["google"].writes() == []
    ctx = ops_core.context(world["path"])
    old = ctx["store"].pending_get(ctx["conn"], started["pending"])
    assert old["status"] == "resolved" and old["resolution"] == "answered" and task_state(world, started["task"]) == "ready"
    assert [a["status"] for a in ctx["store"].approvals_list(ctx["conn"])] == ["revoked"], "the approval of that attempt is revoked when the decision is answered"
    out = ops_steps.run_step(world["path"], started["task"])
    assert out["ok"] is True and out["task_state"] == "waiting"
    [new] = ctx["store"].pending_list(ctx["conn"], "open", started["task"])
    assert new["payload_sha256"] != old["payload_sha256"] and effect_doc(world, started, cycle=1)["messages"][1]["labels"] == ["INBOX"], "the new card is based on the message as it is now"
    world["google"].requests.clear()
    assert approve(world, {"pending": new["id"]})["task_state"] == "done" and world["google"].messages["m2"]["labelIds"] == []


@pytest.mark.parametrize("change, positions", [(lambda g: g.messages["m1"].__setitem__("changeKey", g.next_key()), "1"),
                                               (lambda g: g.messages["m2"].__setitem__("parentFolderId", fgr.NAMED), "2"), (lambda g: g.messages.pop("m3"), "3")],
                         ids=["a changeKey moved", "a folder moved", "a message gone"])
def test_limit_56_a_changekey_or_a_folder_moved_or_a_message_gone_on_outlook_is_stale_too(world, change, positions):
    started = archive(world, "work#1,work#2,work#3", "microsoft")
    change(world["graph"])
    with pytest.raises(ops.OpsError) as stale:
        approve(world, started)
    assert f"positions {positions} of the card" in str(stale.value) and "starts over" in str(stale.value)
    assert world["graph"].writes() == [] and task_state(world, started["task"]) == "ready"


def test_a_message_gone_before_the_card_is_refused_with_its_position(world):
    del world["google"].messages["m2"]
    error = refused(world, ops.mail_archive, "google", "inbox#1,inbox#2")
    assert "positions 2 are not in the mailbox any more" in str(error) and rows(world)[1] == []


# --- a partial failure and a lost answer ---------------------------------------------------------------------------------------------------------------


def test_a_failure_after_the_first_message_is_unknown_names_the_done_positions_and_approving_again_finishes_the_others(world):
    started = ops.mail_trash(world["path"], "google", "inbox#1,inbox#2,inbox#3")
    world["google"].fail_write_number = (2, 500)
    with pytest.raises(ops.OpsError) as partial:
        approve(world, started)
    assert "partial: done 1 of 3" in str(partial.value) and "1 of 3 messages are done (positions 1 on the card)" in str(partial.value)
    assert task_state(world, started["task"]) == "waiting" and "TRASH" in world["google"].messages["m1"]["labelIds"] and "TRASH" not in world["google"].messages["m2"]["labelIds"]
    ctx = ops_core.context(world["path"])
    assert ctx["store"].pending_get(ctx["conn"], started["pending"])["status"] == "open"
    world["google"].requests.clear()
    world["google"].fail_write_number = None
    done = approve(world, started)
    assert done["task_state"] == "done" and all("TRASH" in world["google"].messages[m]["labelIds"] for m in ("m1", "m2", "m3"))
    assert world["google"].writes() == [("POST", f"{MESSAGES}/m2/trash", {}, None), ("POST", f"{MESSAGES}/m3/trash", {}, None)], "the done message is not sent again"


def test_a_lost_answer_of_a_label_change_is_unknown_the_effect_stays_open_and_approving_again_finds_it_by_the_labels(world):
    started = archive(world)
    world["google"].lose_answer_once = True
    with pytest.raises(ops.OpsError) as lost:
        approve(world, started)
    assert "may or may not have landed" in str(lost.value) or "outcome is unknown" in str(lost.value)
    assert task_state(world, started["task"]) == "waiting" and world["google"].messages["m1"]["labelIds"] == ["UNREAD"]
    world["google"].requests.clear()
    done = approve(world, started)
    assert done["task_state"] == "done" and done["result"]["replayed"] is True and world["google"].writes() == [], "nothing was sent again"


def test_a_lost_answer_of_an_outlook_move_is_found_in_the_destination_and_a_lost_draft_by_its_property(world):
    started = archive(world, "work#1", "microsoft")
    world["graph"].lose_answer_once = True
    with pytest.raises(ops.OpsError):
        approve(world, started)
    assert "m1" not in world["graph"].messages
    world["graph"].requests.clear()
    done = approve(world, started)
    assert done["result"]["replayed"] is True and world["graph"].writes() == []
    new = ops.mail_draft(world["path"], "microsoft", **NEW_DRAFT)
    world["graph"].lose_answer_once = True
    with pytest.raises(ops.OpsError):
        approve(world, new)
    count = len([m for m in world["graph"].messages.values() if m["isDraft"]])
    again = approve(world, new)
    assert again["result"]["replayed"] is True and len([m for m in world["graph"].messages.values() if m["isDraft"]]) == count == 1


def test_a_server_error_on_a_write_is_unknown_for_the_runtime_too_and_a_429_leaves_nothing_changed(world):
    started = archive(world)
    world["google"].refuse_next = (503, "backendError")
    with pytest.raises(ops.OpsError) as why:
        approve(world, started)
    assert "outcome is unknown" in str(why.value) or "may or may not have landed" in str(why.value)
    second = archive(world, "inbox#3")
    world["google"].refuse_next = (429, "rateLimitExceeded")
    with pytest.raises(ops.OpsError) as slow:
        approve(world, second)
    assert "slow down" in str(slow.value) and "stays open" in str(slow.value) and world["google"].messages["m3"]["labelIds"] == ["INBOX", "UNREAD"]


# --- L59: the account and the token -------------------------------------------------------------------------------------------------------------------


def test_limit_59_a_token_of_another_account_than_the_one_the_configuration_names_writes_nothing(world, monkeypatch):
    started = archive(world)
    monkeypatch.setenv("GOOGLE_ACCOUNT_TOKEN", world["google"].record_json(account="lee@example.com"))
    world["google"].requests.clear()
    with pytest.raises(ops.OpsError) as why:
        approve(world, started)
    assert "another account" in str(why.value) and world["google"].requests == [] and world["google"].writes() == []
    assert task_state(world, started["task"]) == "waiting"


def test_limit_59_the_writer_gets_the_minimum_environment_plus_one_token_and_no_token_is_in_the_store_the_card_or_the_file(world):
    started = archive(world)
    approve(world, started)
    assert world["google"].requests and all(r["bearer"] for r in world["google"].requests if r["path"] != "/token")
    environment = world["resolver"].provider_environment("writer:mailbox", None, ("GOOGLE_ACCOUNT_TOKEN",))
    assert "UNRELATED_SECRET" not in environment and "MICROSOFT_ACCOUNT_TOKEN" not in environment and "GOOGLE_ACCOUNT_TOKEN" in environment
    item = item_of(world, started)
    cfg = ops_core.context(world["path"])["cfg"]
    effect_file = (Path(ops_step_effects.effect_dir(cfg, started["task"], 0)) / "effect.json").read_text(encoding="ascii")
    ctx = ops_core.context(world["path"])
    stored = json.dumps([item, ctx["store"].approvals_list(ctx["conn"]), effect_file], default=str)
    for secret in fgm.SECRETS + fgr.SECRETS:
        assert secret not in stored
    for mode in (0o700,):
        assert (Path(ops_step_effects.effect_dir(cfg, started["task"], 0)).stat().st_mode & 0o777) == mode


# --- L58: the seam reads and previews, and nothing else ------------------------------------------------------------------------------------------------


def test_limit_58_the_seam_reads_messages_and_folders_and_asks_for_a_dry_run_and_has_no_way_to_write(world):
    ctx = ops_core.context(world["path"])
    reader = ops_step_seams.services(ctx)["mailbox_read"]
    rows_ = reader.message_meta("google", ["m1", "m404"])
    assert [r["found"] for r in rows_] == [True, False] and rows_[0]["labels"] == ["INBOX", "UNREAD"]
    assert reader.folder_get("microsoft", "archive") == {"found": True, "id": fgr.FOLDERS["archive"]}
    assert ops_step_seams.MAILBOX_READ_VERBS == ("message-meta", "folder-get")
    assert not [name for name in dir(reader) if name.lstrip("_") in ("move", "modify", "trash", "mark", "draft_create", "write", "send")]
    started = archive(world)
    doc = effect_doc(world, started)
    world["google"].requests.clear()
    shown = reader.dry_run(doc)
    assert shown["would_sha256"] == doc["dry_run_sha256"] and world["google"].requests == [], "a dry run opens no connection"
    with pytest.raises(ops_step_seams.StepServiceError) as why:
        reader._read("google", "modify", [])
    assert why.value.code == "refused"


def test_a_step_task_of_the_kind_is_not_started_by_the_dispatcher_and_the_kind_is_checked_when_planned(world):
    kind = steps.kind_of("mailbox-change")
    assert kind.unattended is False and kind.footprint({}) == ()
    for bad in ({"account": "google", "action": "archive"}, {"account": "google", "action": "archive", "messages": []}, {"account": "google", "action": "archive", "messages": "inbox#1"},
                {"account": "google", "action": "mark", "messages": [], "state": "seen"}, {"account": "yahoo", "action": "archive"}, {"account": "google", "action": "erase"},
                {"account": "google", "action": "archive", "messages": [], "to": ["a@x.example"]}, {"account": "google", "action": "draft"}, {"account": "google", "action": "draft", "body": "x"}):
        with pytest.raises(steps.StepFailure):
            kind.check(bad)
    entry = {"ref": "inbox#1", "id": "m1", "snapshot_at": "2026-10-17T09:00:00Z"}
    with pytest.raises(steps.StepFailure):
        kind.check({"account": "google", "action": "archive", "messages": [dict(entry, subject="a stray key")]})
    with pytest.raises(steps.StepFailure):
        kind.check({"account": "google", "action": "archive", "messages": [dict(entry, id="../x")]})
    assert kind.check({"account": "google", "action": "archive", "messages": [entry]})["action"] == "archive"
    assert kind.check({"account": "google", "action": "move", "folder": "bills", "messages": [entry]})["folder"] == "bills"


def test_an_outlook_failure_after_the_first_move_names_the_done_positions_and_approving_again_finishes_the_others_without_calling_the_moved_one_stale(world):
    started = archive(world, "work#1,work#2,work#3", "microsoft")
    world["graph"].fail_write_number = (2, 500)
    with pytest.raises(ops.OpsError) as partial:
        approve(world, started)
    assert "partial: done 1 of 3" in str(partial.value) and "positions 1 on the card" in str(partial.value)
    assert "m1" not in world["graph"].messages and task_state(world, started["task"]) == "waiting"
    world["graph"].requests.clear()
    world["graph"].fail_write_number = None
    done = approve(world, started)
    assert done["task_state"] == "done" and done["result"]["replayed"] is False
    assert world["graph"].writes() == [("POST", f"{GRAPH_MESSAGES}/m2/move", {}, {"destinationId": "archive"}), ("POST", f"{GRAPH_MESSAGES}/m3/move", {}, {"destinationId": "archive"})]


def test_the_seam_starts_the_writer_with_the_account_token_to_read_and_with_none_for_a_dry_run(world, monkeypatch):
    seen = []
    real = effect_mailbox.provider_call

    def spy(root, implementation, verb, args, secrets=(), timeout=effect_mailbox.CALL_TIMEOUT):
        seen.append((verb, "--dry-run" in args, tuple(secrets)))
        return real(root, implementation, verb, args, secrets, timeout)
    monkeypatch.setattr(effect_mailbox, "provider_call", spy)
    started = archive(world)
    approve(world, started)
    assert seen[0] == ("message-meta", False, ("GOOGLE_ACCOUNT_TOKEN",)) and seen[1] == ("modify", True, ()), "the preparation reads with the token and previews with none"
    assert all(secrets == () for _, dry, secrets in seen if dry) and all(secrets == ("GOOGLE_ACCOUNT_TOKEN",) for _, dry, secrets in seen if not dry)
    assert not [verb for verb, _, _ in seen if verb not in ("message-meta", "folder-get", "modify")], "the preparation starts no write verb but with --dry-run"
    assert [dry for verb, dry, _ in seen if verb == "modify"] == [True, True, False], "a preview in the preparation, a preview before the write, then the write"


def test_a_new_draft_is_prepared_with_no_credential_in_the_environment_at_all(world, monkeypatch):
    for name in ("GOOGLE_ACCOUNT_TOKEN", "MICROSOFT_ACCOUNT_TOKEN"):
        monkeypatch.delenv(name)
    started = ops.mail_draft(world["path"], "google", **NEW_DRAFT)
    assert world["google"].requests == [] and item_of(world, started)["kind"] == "effect"
    with pytest.raises(ops.OpsError) as why:
        approve(world, started)
    assert "google_auth.py authorize" in str(why.value) and world["google"].writes() == []
    assert task_state(world, started["task"]) == "waiting"


def test_an_approval_cannot_be_used_twice_and_a_second_start_is_a_second_card(world):
    started = archive(world, "inbox#1")
    approve(world, started)
    with pytest.raises(ops.OpsError):
        approve(world, started)
    assert len(world["google"].writes()) == 1
    with pytest.raises(ops.OpsError) as again:
        archive(world, "inbox#1")
    assert "already as asked" in str(again.value)
    second = ops.mail_mark(world["path"], "google", "inbox#1", "read")
    assert second["pending"] != started["pending"] and effect_doc(world, second)["idempotency_key"] != effect_doc(world, started)["idempotency_key"]


# --- the review of #483 ---------------------------------------------------------------------------------------------------------------------------------


def test_limit_57_a_mailbox_trash_is_the_providers_trash_and_nothing_is_removed_for_good_on_either_account(world):
    google = ops.mail_trash(world["path"], "google", "inbox#1")
    approve(world, google)
    microsoft = ops.mail_trash(world["path"], "microsoft", "work#1")
    approve(world, microsoft)
    assert world["google"].writes() == [("POST", f"{MESSAGES}/m1/trash", {}, None)] and "TRASH" in world["google"].messages["m1"]["labelIds"]
    assert world["graph"].writes() == [("POST", f"{GRAPH_MESSAGES}/m1/move", {}, {"destinationId": "deleteditems"})]
    assert world["google"].unexpected() == [] and world["graph"].unexpected() == []
    assert not [r for fake in (world["google"], world["graph"]) for r in fake.requests if r["method"] == "DELETE"]
    import importlib.util
    for name in ("gmail.py", "outlook-mail.py"):
        spec = importlib.util.spec_from_file_location("writer_" + name.split(".")[0].replace("-", "_"), st.REPO / "providers" / "writer" / name)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        assert {method for method, _ in module.ALLOWED} <= {"GET", "POST", "PATCH"}, name
        assert not [pattern for _, pattern in module.ALLOWED if re.search(r"delete|empty|send|forward|(?<!create)reply", pattern, re.I)], name


def test_the_arguments_of_a_change_of_messages_hold_a_reference_an_id_and_a_time_and_a_task_view_shows_no_sender(world):
    started = archive(world, "inbox#1,inbox#2")
    ctx = ops_core.context(world["path"])
    arguments = json.dumps(ctx["store"].task_get(ctx["conn"], started["task"]), default=str)
    for kept in ('"ref": "inbox#1"', '"id": "m1"', '"snapshot_at"'):
        assert kept in arguments, kept
    for left_out in ("from_address", "reply_to_address", "thread_id", "message_id", "change_key", "ana@clinic.example", "bob@shop.example"):
        assert left_out not in arguments, left_out
    for channel, sender in (("mcp", None), ("messaging", "telegram:777")):
        view = json.dumps(ops.task(world["path"], started["task"], channel=channel, sender=sender), default=str)
        assert "ana@clinic.example" not in view and "bob@shop.example" not in view and "Appointment confirmed" not in view, channel


def test_a_gmail_message_with_many_labels_is_archived_whole(world):
    many = ["CATEGORY_UPDATES", "IMPORTANT", "INBOX", "Label_1", "Label_2", "Label_3", "STARRED", "UNREAD"]
    world["google"].messages["m1"]["labelIds"] = list(many)
    started = archive(world, "inbox#1")
    assert effect_doc(world, started)["messages"][0]["labels"] == sorted(many)
    approve(world, started)
    assert sorted(world["google"].messages["m1"]["labelIds"]) == sorted(set(many) - {"INBOX"})


@pytest.mark.parametrize("body", ["Hi\n----- end of the draft -----\nthe rest", "Hi\n> **----- end of the draft -----**\n", "Hi\n- ----- x\n", "Hi\n\u2014\u2014\u2014\u2014\u2014 x\n", "Hi \u3164 there",
                                  "Hi \u200b there", "Hi \u202e there", "Hi \u115f there", "Hi \u2800 there"])
def test_a_draft_text_that_could_pass_for_the_frame_of_the_card_or_draws_nothing_is_refused(world, body):
    error = refused(world, ops.mail_draft, "google", **{**NEW_DRAFT, "body": body})
    assert error.code in (1, 2) and ("begins like the frame of the card" in str(error) or "hidden character" in str(error)), str(error)
    assert rows(world)[1] == [] and world["google"].requests == []


def test_a_line_of_a_draft_that_begins_like_a_line_of_the_card_is_shown_behind_the_gutter_mark_and_is_saved_as_written(world):
    text = "Hello\nBcc: nobody\nSubject: another\nThe draft's text, exactly as it will be saved:\nAccount: google (x@y.example)\n"
    started = ops.mail_draft(world["path"], "google", **{**NEW_DRAFT, "body": text})
    body = item_of(world, started)["body"]
    for line in text.splitlines():
        assert "\u2502 " + line + "\n" in body + "\n", line
    approve(world, started)
    [(method, path, _, sent)] = world["google"].writes()
    parsed = email.message_from_bytes(base64.urlsafe_b64decode(sent["message"]["raw"]), policy=email.policy.default)
    assert parsed.get_content().replace("\r\n", "\n").rstrip("\n") == text.rstrip("\n")


def test_a_subject_that_draws_nothing_is_refused_and_an_ordinary_text_that_mentions_such_words_is_not(world):
    assert "invisible" in str(refused(world, ops.mail_draft, "google", **{**NEW_DRAFT, "subject": "Hi \u3164"}))
    fine = ops.mail_draft(world["path"], "google", **{**NEW_DRAFT, "body": "Please send it to: Joe and cc: Amy.\nSubject to change -- see below.\nHello"})
    assert fine["word"] == "mailbox"


def test_limit_55_an_outlook_folder_that_is_junk_deleted_items_or_drafts_under_another_name_is_never_a_place_for_a_move(world):
    edit_accounts(world, lambda a: a["microsoft"]["mail_folders"].update({"spamlike": "junkemail", "keep": fgr.FOLDERS["deleteditems"], "wip": fgr.FOLDERS["drafts"],
                                                                          "junk": fgr.FOLDERS["junkemail"], "trashy": "deleteditems", "ok": fgr.NAMED}))
    for name in ("spamlike", "trashy"):
        assert "cannot be a place for a move" in str(refused(world, ops.mail_move, "microsoft", "work#1", name)), name
    for name in ("keep", "wip", "junk"):
        assert "never reaches" in str(refused(world, ops.mail_move, "microsoft", "work#1", name)), name
    assert world["graph"].writes() == [] and rows(world)[1] == []
    assert ops.mail_move(world["path"], "microsoft", "work#1", "ok")["word"] == "mailbox"


def test_a_message_the_writer_never_tried_and_somebody_moved_ends_stale_and_one_it_tried_ends_unknown(world):
    started = ops.mail_trash(world["path"], "google", "inbox#1,inbox#2,inbox#3")
    world["google"].fail_write_number = (2, 500)
    with pytest.raises(ops.OpsError) as partial:
        approve(world, started)
    assert "partial: done 1 of 3" in str(partial.value)
    world["google"].messages["m3"]["labelIds"] = ["Label_7"]      # never attempted by the writer, and somebody filed it
    world["google"].fail_write_number = None
    with pytest.raises(ops.OpsError) as stale:
        approve(world, started)
    assert "positions 3 are not as they were read" in str(stale.value) and "starts over" in str(stale.value), "stale, with the decision answered: not 'unknown' for ever"
    assert task_state(world, started["task"]) == "ready"
