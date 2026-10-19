"""Tests of the Outlook mailbox writer (providers/writer/outlook-mail.py; package W3; limits L55 to L59 as they apply to a writer). Against the stand-in service
(fake_graph_mail_write.py) on 127.0.0.1: no Microsoft host is reached and no real credential exists. Every write path records each request (method, path, query,
body) and the tests assert the exact list: one `move` per message (to the archive, a folder, or Deleted Items), one PATCH of `isRead` per message, one POST for a draft,
`createReply` then one PATCH for a reply draft, and nothing else, never a send, never a removal. A message that is not as it was read (its changeKey or its folder
moved) is refused (exit 1, `changed:`) before anything is written; a failure after the first message names the positions that are done (exit 4) and the same key
finishes the others; a lost answer is looked up by state (a moved message is found in the destination by its internetMessageId). The account record is required, with the
platform's whole set, and it must belong to the account the document names.

Run: uv run --with pytest==9.1.1 pytest providers/writer/tests/test_writer_outlook_mail.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import urllib.parse
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(HERE))
import fake_graph_mail_write as fgm  # noqa: E402

WRITER = REPO / "providers" / "writer" / "outlook-mail.py"
KEY = "box-fedcba9876543210fedcba9876543210"
ME = "/v1.0/me/messages"


@pytest.fixture
def fake():
    f = fgm.FakeGraphMail()
    yield f
    f.close()


@pytest.fixture
def state(tmp_path):
    folder = tmp_path / "state"
    folder.mkdir()
    os.chmod(folder, 0o700)
    return folder


def env_of(fake, tmp_path, state, record=None, **extra):
    kept = {k: v for k, v in os.environ.items() if not k.startswith(("MICROSOFT_", "OUTLOOK_", "WRITER_", "INTEGRATION_", "OPENHORA_"))}
    kept.update({"HOME": str(tmp_path / "home"), "OPENHORA_STATE_DIR": str(state), "MICROSOFT_ACCOUNT_TOKEN": record or fake.record_json(), **fake.env()})
    kept.update(extra)
    return kept


def spec_file(tmp_path, spec, name="spec.json"):
    path = tmp_path / name
    path.write_text(json.dumps(spec), encoding="utf-8")
    os.chmod(path, 0o600)
    return str(path)


def run(fake, tmp_path, state, *args, record=None, env=None):
    proc = subprocess.run([sys.executable, str(WRITER), *args], env=env or env_of(fake, tmp_path, state, record), capture_output=True, text=True, timeout=60)
    for stream in (proc.stdout, proc.stderr):    # no run ever prints a credential, not even partially (limit L59)
        for secret in fgm.SECRETS + ("fake-refresh-token-1-not-real",):
            assert secret not in stream, args
    return proc


def out(proc):
    assert proc.returncode == 0, (proc.returncode, proc.stderr)
    return json.loads(proc.stdout)


def calls(fake):
    """Every request the writer sent to Graph, as (method, path, query, body)."""
    return [(r["method"], r["path"], r["query"], r["body"]) for r in fake.graph_requests()]


def seed(fake, n=3, folder="inbox"):
    for i in range(1, n + 1):
        fake.add_message(f"AAMkMsg{i:04d}=", f"Subject number {i}", f"ana{i}@clinic.example", folder=folder)
    return [f"AAMkMsg{i:04d}=" for i in range(1, n + 1)]


def move_spec(fake, ids, to="archive"):
    base = {i: {"change_key": fake.messages[i]["changeKey"], "folder_id": fake.messages[i]["parentFolderId"]} for i in ids}
    return {"ids": ids, "base": base, "internet_ids": {i: fake.messages[i]["internetMessageId"] for i in ids}, "to": to}


def mark_spec(fake, ids, read=True):
    return {"ids": ids, "base": {i: {"change_key": fake.messages[i]["changeKey"], "is_read": fake.messages[i]["isRead"]} for i in ids}, "read": read}


def args_of(verb, tmp_path, spec, key=KEY, mode="--confirmed", account=fgm.ADDRESS):
    return [verb, "--account", account, "--spec-file", spec_file(tmp_path, spec), "--idempotency-key", key, mode]


def path_of(message, tail=""):
    return f"{ME}/{message}{tail}"


DRAFT = {"to": ["joe@shop.example"], "cc": ["amy@shop.example"], "bcc": ["boss@shop.example"], "subject": "Haircut on Monday", "body": "Hello Joe,\nSee you at 13:00.\n"}


# --- a move ------------------------------------------------------------------------------------------------------------------------------------------


def test_an_archive_is_one_read_then_one_move_per_message_to_the_well_known_folder(fake, tmp_path, state):
    ids = seed(fake)
    done = out(run(fake, tmp_path, state, *args_of("move", tmp_path, move_spec(fake, ids))))
    assert done == {"count": 3, "done": True, "replayed": False}
    assert [(m, p) for m, p, _, _ in calls(fake)] == [("GET", path_of(i)) for i in ids] + [("POST", path_of(i, "/move")) for i in ids]
    assert fake.writes() == [("POST", path_of(i, "/move"), {}, {"destinationId": "archive"}) for i in ids] and fake.unexpected() == []
    assert [m["parentFolderId"] for m in fake.messages.values()] == [fgm.FOLDERS["archive"]] * 3
    assert all(r["bearer"] for r in fake.graph_requests())


def test_a_move_to_a_named_folder_and_a_trash_are_the_same_verb_with_another_destination(fake, tmp_path, state):
    ids = seed(fake, 2)
    out(run(fake, tmp_path, state, *args_of("move", tmp_path, move_spec(fake, ids[:1], to=fgm.NAMED), key="box-" + "1" * 32)))
    assert fake.writes() == [("POST", path_of(ids[0], "/move"), {}, {"destinationId": fgm.NAMED})]
    fake.requests.clear()
    out(run(fake, tmp_path, state, *args_of("move", tmp_path, move_spec(fake, ids[1:], to="deleteditems"), key="box-" + "2" * 32)))
    assert fake.writes() == [("POST", path_of(ids[1], "/move"), {}, {"destinationId": "deleteditems"})]
    assert sorted(m["parentFolderId"] for m in fake.messages.values()) == sorted([fgm.NAMED, fgm.FOLDERS["deleteditems"]])


def test_the_dry_run_reads_no_credential_opens_no_connection_and_prints_the_requests_the_confirmed_run_sends(fake, tmp_path, state):
    ids = seed(fake)
    bare = {k: v for k, v in os.environ.items() if not k.startswith(("MICROSOFT_", "OUTLOOK_", "WRITER_", "INTEGRATION_", "OPENHORA_"))}
    bare.update({"HOME": str(tmp_path / "home"), "OPENHORA_STATE_DIR": str(state)})      # no token, no override: a dry run needs neither
    spec = move_spec(fake, ids)
    shown = out(run(fake, tmp_path, state, *args_of("move", tmp_path, spec, mode="--dry-run"), env=bare))
    assert fake.requests == [] and shown["dry_run"] is True and shown["ledger"] == {i: "absent" for i in ids}
    assert shown["would"]["requests"] == [{"method": "POST", "path": f"/me/messages/{urllib.parse.quote(i, safe='')}/move", "query": {}, "headers": {}, "body": {"destinationId": "archive"}}
                                          for i in ids]
    out(run(fake, tmp_path, state, *args_of("move", tmp_path, spec)))
    sent = [r for r in fake.graph_requests() if r["method"] != "GET"]
    assert [{"method": r["method"], "path": r["raw_path"].removeprefix("/v1.0"), "query": r["query"], "headers": {}, "body": r["body"]} for r in sent] == shown["would"]["requests"]
    again = out(run(fake, tmp_path, state, *args_of("move", tmp_path, spec, mode="--dry-run"), env=bare))
    assert again["ledger"] == {i: "done" for i in ids} and again["would_sha256"] == shown["would_sha256"]


def test_a_message_whose_changekey_or_folder_moved_stops_the_whole_request_before_anything_is_written(fake, tmp_path, state):
    ids = seed(fake)
    spec = move_spec(fake, ids)
    fake.messages[ids[1]]["changeKey"] = fake.next_key()                      # somebody read it meanwhile
    fake.messages[ids[2]]["parentFolderId"] = fgm.NAMED                      # somebody filed it meanwhile
    proc = run(fake, tmp_path, state, *args_of("move", tmp_path, spec))
    assert proc.returncode == 1 and proc.stderr.strip().startswith("error: changed:") and "positions 2,3" in proc.stderr
    assert all(m == "GET" for m, _, _, _ in calls(fake)) and fake.writes() == []
    assert out(run(fake, tmp_path, state, *args_of("move", tmp_path, spec, mode="--dry-run")))["ledger"] == {i: "absent" for i in ids}, "the key is free"
    del fake.messages[ids[0]]
    gone = run(fake, tmp_path, state, *args_of("move", tmp_path, spec, key="box-" + "3" * 32))
    assert gone.returncode == 1 and "positions 1,2,3" in gone.stderr and fake.writes() == []


def test_at_most_twenty_messages_and_no_repeated_id_and_no_destination_outside_the_closed_names(fake, tmp_path, state):
    ids = seed(fake, 21)
    assert run(fake, tmp_path, state, *args_of("move", tmp_path, move_spec(fake, ids))).returncode == 2
    twice = move_spec(fake, ids[:1])
    twice["ids"] = ids[:1] * 2
    assert run(fake, tmp_path, state, *args_of("move", tmp_path, twice)).returncode == 2
    for destination in ("drafts", "outbox", "recoverableitemsdeletions", "recoverableitemspurges", "msgfolderroot", "sentitems", "../x", "-x", "a/b", "", "a b"):
        assert run(fake, tmp_path, state, *args_of("move", tmp_path, move_spec(fake, ids[:1], to=destination))).returncode == 2, destination
    assert fake.requests == []
    assert out(run(fake, tmp_path, state, *args_of("move", tmp_path, move_spec(fake, ids[:20]), key="box-" + "4" * 32)))["count"] == 20


@pytest.mark.parametrize("bad", ["../x", "-x", "a/b", "a b", "x" * 601, "", "a%2Fb", "a?b"])
def test_an_id_outside_the_pattern_is_a_usage_error_and_nothing_is_sent(fake, tmp_path, state, bad):
    seed(fake, 1)
    spec = {"ids": [bad], "base": {bad: {"change_key": "CQ", "folder_id": "x"}}, "internet_ids": {bad: None}, "to": "archive"}
    assert run(fake, tmp_path, state, *args_of("move", tmp_path, spec)).returncode == 2 and fake.requests == []
    assert run(fake, tmp_path, state, "message-meta", "--account", fgm.ADDRESS, "--ids", bad).returncode == 2 and fake.requests == []


def test_an_id_with_characters_that_belong_in_a_url_is_percent_encoded_in_the_path(fake, tmp_path, state):
    tricky = "AAMk+Msg=_-1"
    fake.add_message(tricky, "Plus", "ana@clinic.example")
    out(run(fake, tmp_path, state, *args_of("move", tmp_path, move_spec(fake, [tricky]))))
    assert [r["raw_path"] for r in fake.graph_requests()] == [f"/v1.0/me/messages/{'AAMk%2BMsg%3D_-1'}"] * 1 + [f"/v1.0/me/messages/{'AAMk%2BMsg%3D_-1'}/move"]


def test_a_done_key_is_not_sent_again_and_a_key_used_for_another_request_is_a_usage_error(fake, tmp_path, state):
    ids = seed(fake)
    spec = move_spec(fake, ids)
    out(run(fake, tmp_path, state, *args_of("move", tmp_path, spec)))
    fake.requests.clear()
    again = out(run(fake, tmp_path, state, *args_of("move", tmp_path, spec)))
    assert again["replayed"] is True and calls(fake) == []
    other = run(fake, tmp_path, state, *args_of("move", tmp_path, dict(spec, to="deleteditems")))
    assert other.returncode == 2 and "another request" in other.stderr


def test_a_failure_after_the_first_message_names_the_done_positions_and_the_same_key_finishes_the_others(fake, tmp_path, state):
    ids = seed(fake)
    spec = move_spec(fake, ids)
    fake.fail_write_number = (2, 500)
    proc = run(fake, tmp_path, state, *args_of("move", tmp_path, spec))
    assert proc.returncode == 4 and "partial: done 1 of 3" in proc.stderr
    assert fake.messages[ids[1]]["parentFolderId"] == fgm.FOLDERS["inbox"] and ids[0] not in fake.messages        # the first moved: its old id is gone
    meta = out(run(fake, tmp_path, state, "message-meta", "--account", fgm.ADDRESS, "--ids", ",".join(ids), "--key", KEY))["messages"]
    assert [(m["found"], m.get("done")) for m in meta] == [(False, "done"), (True, "pending"), (True, "pending")]
    fake.requests.clear()
    fake.fail_write_number = None
    done = out(run(fake, tmp_path, state, *args_of("move", tmp_path, spec)))
    assert done["done"] is True
    assert [(m, p) for m, p, _, _ in calls(fake)] == [("GET", path_of(ids[1])), ("GET", path_of(ids[2])), ("POST", path_of(ids[1], "/move")), ("POST", path_of(ids[2], "/move"))]
    assert sorted(m["parentFolderId"] for m in fake.messages.values()) == [fgm.FOLDERS["archive"]] * 3


def test_a_refusal_of_the_first_message_changes_nothing_and_frees_the_key(fake, tmp_path, state):
    ids = seed(fake)
    spec = move_spec(fake, ids)
    fake.refuse_next = (403, "ErrorAccessDenied")
    proc = run(fake, tmp_path, state, *args_of("move", tmp_path, spec))
    assert proc.returncode == 1 and "partial" not in proc.stderr
    assert out(run(fake, tmp_path, state, *args_of("move", tmp_path, spec, mode="--dry-run")))["ledger"] == {i: "absent" for i in ids}


def test_a_lost_answer_of_a_move_is_found_in_the_destination_by_its_internet_message_id(fake, tmp_path, state):
    [one] = seed(fake, 1)
    spec = move_spec(fake, [one])
    fake.lose_answer_once = True
    assert run(fake, tmp_path, state, *args_of("move", tmp_path, spec)).returncode == 4
    assert one not in fake.messages and [m["parentFolderId"] for m in fake.messages.values()] == [fgm.FOLDERS["archive"]]       # it landed
    fake.requests.clear()
    again = out(run(fake, tmp_path, state, *args_of("move", tmp_path, spec)))
    assert again["replayed"] is True
    assert [(m, p) for m, p, _, _ in calls(fake)] == [("GET", path_of(one)), ("GET", path_of(one)), ("GET", "/v1.0/me/mailFolders/archive/messages")]
    assert calls(fake)[-1][2]["$filter"] == "internetMessageId eq '<AAMkMsg0001=@mail.example>'" and fake.writes() == []


def test_a_lost_answer_that_did_not_land_is_sent_again_after_the_message_is_seen_where_it_was(fake, tmp_path, state):
    [one] = seed(fake, 1)
    spec = move_spec(fake, [one])
    fake.redirect_next = True
    assert run(fake, tmp_path, state, *args_of("move", tmp_path, spec)).returncode == 4 and fake.messages[one]["parentFolderId"] == fgm.FOLDERS["inbox"]
    fake.requests.clear()
    done = out(run(fake, tmp_path, state, *args_of("move", tmp_path, spec)))
    assert done["replayed"] is False and [m for m, _, _, _ in calls(fake)] == ["GET", "POST"]


def test_a_lost_answer_whose_message_is_nowhere_to_be_found_is_unknown_not_a_guess_and_not_stale(fake, tmp_path, state):
    [one] = seed(fake, 1)
    spec = move_spec(fake, [one])
    fake.lose_answer_once = True
    run(fake, tmp_path, state, *args_of("move", tmp_path, spec))
    [moved] = list(fake.messages)
    fake.messages[moved]["internetMessageId"] = "<somebody-else@mail.example>"           # what is in the destination is not the message
    proc = run(fake, tmp_path, state, *args_of("move", tmp_path, spec))
    assert proc.returncode == 4 and "earlier attempt of this key" in proc.stderr and "changed:" not in proc.stderr
    assert fake.writes() == [("POST", path_of(one, "/move"), {}, {"destinationId": "archive"})], "nothing was sent again, and the outcome is called unknown, not stale"


def test_a_server_error_on_a_write_is_unknown_and_a_429_is_a_refusal_with_its_retry_after(fake, tmp_path, state):
    ids = seed(fake, 1)
    spec = move_spec(fake, ids)
    fake.refuse_next = (503, "serviceNotAvailable")
    proc = run(fake, tmp_path, state, *args_of("move", tmp_path, spec))
    assert proc.returncode == 4 and "may or may not have landed" in proc.stderr
    assert out(run(fake, tmp_path, state, *args_of("move", tmp_path, spec, mode="--dry-run")))["ledger"] == {ids[0]: "pending"}
    fake.refuse_next = (429, "TooManyRequests")
    other = run(fake, tmp_path, state, *args_of("move", tmp_path, spec, key="box-" + "5" * 32))
    assert other.returncode == 1 and "retry after 30 seconds" in other.stderr


# --- mark read and unread ----------------------------------------------------------------------------------------------------------------------------


def test_a_mark_is_one_patch_of_is_read_per_message_and_nothing_else(fake, tmp_path, state):
    ids = seed(fake, 2)
    out(run(fake, tmp_path, state, *args_of("mark", tmp_path, mark_spec(fake, ids))))
    assert fake.writes() == [("PATCH", path_of(i), {}, {"isRead": True}) for i in ids] and fake.unexpected() == []
    assert all(fake.messages[i]["isRead"] is True for i in ids)
    fake.requests.clear()
    out(run(fake, tmp_path, state, *args_of("mark", tmp_path, mark_spec(fake, ids[:1], read=False), key="box-" + "6" * 32)))
    assert fake.writes() == [("PATCH", path_of(ids[0]), {}, {"isRead": False})] and fake.messages[ids[0]]["isRead"] is False


def test_a_mark_of_a_message_that_changed_meanwhile_is_refused_before_the_patch(fake, tmp_path, state):
    ids = seed(fake, 2)
    spec = mark_spec(fake, ids)
    fake.messages[ids[0]]["changeKey"] = fake.next_key()
    proc = run(fake, tmp_path, state, *args_of("mark", tmp_path, spec))
    assert proc.returncode == 1 and "positions 1" in proc.stderr and fake.writes() == []


def test_a_lost_mark_answer_is_found_by_the_read_state(fake, tmp_path, state):
    [one] = seed(fake, 1)
    spec = mark_spec(fake, [one])
    fake.lose_answer_once = True
    assert run(fake, tmp_path, state, *args_of("mark", tmp_path, spec)).returncode == 4 and fake.messages[one]["isRead"] is True
    fake.requests.clear()
    again = out(run(fake, tmp_path, state, *args_of("mark", tmp_path, spec)))
    assert again["replayed"] is True and [(m, p) for m, p, _, _ in calls(fake)] == [("GET", path_of(one))]


# --- a draft ------------------------------------------------------------------------------------------------------------------------------------------


def test_a_draft_is_one_post_with_the_key_as_a_private_property_and_never_a_send(fake, tmp_path, state):
    done = out(run(fake, tmp_path, state, *args_of("draft-create", tmp_path, DRAFT)))
    assert done["done"] is True and done["replayed"] is False and done["draft_id"].startswith("AAMkDraft")
    [(method, path, query, body)] = calls(fake)
    assert (method, path, query) == ("POST", "/v1.0/me/messages", {})
    assert body == {"subject": "Haircut on Monday", "body": {"contentType": "text", "content": DRAFT["body"]},
                    "toRecipients": [{"emailAddress": {"address": "joe@shop.example"}}], "ccRecipients": [{"emailAddress": {"address": "amy@shop.example"}}],
                    "bccRecipients": [{"emailAddress": {"address": "boss@shop.example"}}], "singleValueExtendedProperties": [{"id": fgm.KEY_PROPERTY, "value": KEY}]}
    assert fake.unexpected() == [] and fake.messages[done["draft_id"]]["isDraft"] is True and fake.messages[done["draft_id"]]["parentFolderId"] == fgm.FOLDERS["drafts"]


def test_a_reply_draft_is_create_reply_then_one_patch_that_makes_it_exactly_the_text_approved(fake, tmp_path, state):
    [one] = seed(fake, 1)
    spec = {"to": ["ana1@clinic.example"], "cc": [], "bcc": [], "subject": "RE: Subject number 1", "body": "Thanks, Monday works.\n"}
    done = out(run(fake, tmp_path, state, "draft-reply", "--account", fgm.ADDRESS, "--message", one, "--spec-file", spec_file(tmp_path, spec), "--idempotency-key", KEY, "--confirmed"))
    draft = done["draft_id"]
    assert [(m, p) for m, p, _, _ in calls(fake)] == [("POST", path_of(one, "/createReply")), ("PATCH", path_of(draft))]
    approved = {"subject": "RE: Subject number 1", "body": {"contentType": "text", "content": spec["body"]}, "toRecipients": [{"emailAddress": {"address": "ana1@clinic.example"}}],
                "ccRecipients": [], "bccRecipients": [], "singleValueExtendedProperties": [{"id": fgm.KEY_PROPERTY, "value": KEY}]}
    assert calls(fake)[0][3] == {"message": approved}, "the approved message goes in the createReply too"
    assert calls(fake)[1][3] == approved
    assert calls(fake)[1][3]["toRecipients"] == [{"emailAddress": {"address": "ana1@clinic.example"}}] and calls(fake)[1][3]["body"] == {"contentType": "text", "content": spec["body"]}
    shown = fake.messages[draft]
    assert shown["toRecipients"] == [{"emailAddress": {"address": "ana1@clinic.example"}}], "not where Graph would have addressed it (the Reply-To)"
    assert shown["body"] == {"contentType": "text", "content": spec["body"]} and shown["conversationId"] == fake.messages[one]["conversationId"] and fake.unexpected() == []


def test_the_draft_dry_run_prints_the_requests_the_confirmed_run_sends(fake, tmp_path, state):
    bare = {k: v for k, v in os.environ.items() if not k.startswith(("MICROSOFT_", "OUTLOOK_", "WRITER_", "INTEGRATION_", "OPENHORA_"))}
    bare.update({"HOME": str(tmp_path / "home"), "OPENHORA_STATE_DIR": str(state)})
    shown = out(run(fake, tmp_path, state, *args_of("draft-create", tmp_path, DRAFT, mode="--dry-run"), env=bare))
    assert fake.requests == [] and shown["ledger"] == {"draft": "absent"}
    out(run(fake, tmp_path, state, *args_of("draft-create", tmp_path, DRAFT)))
    [(method, path, query, body)] = calls(fake)
    assert {"requests": [{"method": method, "path": path.removeprefix("/v1.0"), "query": query, "headers": {}, "body": body}]} == shown["would"]


def test_a_lost_draft_answer_is_found_by_the_private_property_in_the_drafts_folder(fake, tmp_path, state):
    fake.lose_answer_once = True
    assert run(fake, tmp_path, state, *args_of("draft-create", tmp_path, DRAFT)).returncode == 4
    assert len(fake.messages) == 1                        # it landed
    fake.requests.clear()
    again = out(run(fake, tmp_path, state, *args_of("draft-create", tmp_path, DRAFT)))
    assert again["replayed"] is True and again["draft_id"] and len(fake.messages) == 1
    [(method, path, query, _)] = calls(fake)
    assert (method, path) == ("GET", "/v1.0/me/mailFolders/drafts/messages") and fgm.KEY_PROPERTY in query["$filter"] and KEY in query["$filter"]


def test_a_draft_needs_a_recipient_a_subject_and_a_clean_body(fake, tmp_path, state):
    for change in ({"to": []}, {"subject": ""}, {"subject": "two\nlines"}, {"body": "bad\x00"}, {"to": ["not an address"]}, {"to": ["a@x.example"] * 25}, {"extra": 1}):
        assert run(fake, tmp_path, state, *args_of("draft-create", tmp_path, dict(DRAFT, **change))).returncode == 2, change
    assert fake.requests == []


# --- reading ------------------------------------------------------------------------------------------------------------------------------------------


def test_message_meta_prints_the_state_the_runtime_needs_and_no_body(fake, tmp_path, state):
    fake.add_message("AAMkMsg0010=", "Hello \u202e there\x07", "ana@clinic.example", isRead=True)
    proc = run(fake, tmp_path, state, "message-meta", "--account", fgm.ADDRESS, "--ids", "AAMkMsg0010=,AAMkNone=")
    shown = out(proc)["messages"]
    one = shown[0]
    assert one["found"] is True and one["is_read"] is True and one["folder_id"] == fgm.FOLDERS["inbox"] and one["change_key"].startswith("CQAAABYAAAB")
    assert one["from_address"] == "ana@clinic.example" and "Display Name" not in proc.stdout and one["message_id"] == "<AAMkMsg0010=@mail.example>"
    assert one["date"] == "2026-10-17T09:00:00Z" and one["external_content"] is True and "\x07" not in one["subject"] and one["thread_id"].startswith("AAQkConv")
    assert shown[1] == {"id": "AAMkNone=", "found": False, "done": None}
    first = calls(fake)[0]
    assert first[2]["$select"] == "id,changeKey,parentFolderId,isRead,isDraft,subject,from,receivedDateTime,internetMessageId,conversationId" and "body" not in first[2]["$select"].split(",")


def test_folder_get_gives_the_real_id_of_a_well_known_name_and_found_false_for_a_folder_that_is_not_there(fake, tmp_path, state):
    assert out(run(fake, tmp_path, state, "folder-get", "--account", fgm.ADDRESS, "--folder", "archive")) == {"found": True, "id": fgm.FOLDERS["archive"]}
    assert out(run(fake, tmp_path, state, "folder-get", "--account", fgm.ADDRESS, "--folder", fgm.NAMED)) == {"found": True, "id": fgm.NAMED}
    assert out(run(fake, tmp_path, state, "folder-get", "--account", fgm.ADDRESS, "--folder", "AAMkNoSuchFolder=")) == {"found": False}
    assert out(run(fake, tmp_path, state, "folder-get", "--account", fgm.ADDRESS, "--folder", "drafts")) == {"found": True, "id": fgm.FOLDERS["drafts"]}, "readable: the runtime asks its id"
    assert out(run(fake, tmp_path, state, "folder-get", "--account", fgm.ADDRESS, "--folder", "junkemail")) == {"found": True, "id": fgm.FOLDERS["junkemail"]}
    assert out(run(fake, tmp_path, state, "folder-get", "--account", fgm.ADDRESS, "--folder", "recoverableitemspurges")) == {"found": False}
    assert run(fake, tmp_path, state, "folder-get", "--account", fgm.ADDRESS, "--folder", "Clutter").returncode == 2


def test_a_server_error_on_a_read_is_a_refusal_not_an_unknown_outcome(fake, tmp_path, state):
    seed(fake, 1)
    fake.fail_get_next = 500
    proc = run(fake, tmp_path, state, "message-meta", "--account", fgm.ADDRESS, "--ids", "AAMkMsg0001=")
    assert proc.returncode == 1 and "Graph returned 500" in proc.stderr and "may or may not have landed" not in proc.stderr


# --- the account token --------------------------------------------------------------------------------------------------------------------------------


def test_check_refreshes_checks_the_whole_set_and_reads_one_folder(fake, tmp_path, state):
    shown = out(run(fake, tmp_path, state, "--check"))
    assert shown["ok"] is True and shown["record"] == "account" and shown["scope"] == " ".join(fgm.PLATFORM) and shown["tenant"] == "common"
    assert [(m, p) for m, p, _, _ in calls(fake)] == [("GET", "/v1.0/me/mailFolders")]


@pytest.mark.parametrize("scope", [" ".join(fgm.PREFIX + n for n in fgm.PLATFORM[1:]) + " offline_access", " ".join(fgm.GRANTED.split()) + " https://graph.microsoft.com/Contacts.Read"],
                         ids=["lacks one", "carries another"])
def test_a_token_that_lacks_a_permission_of_the_set_or_carries_another_is_refused_before_any_call(fake, tmp_path, state, scope):
    ids = seed(fake, 1)
    fake.scope_granted = scope
    proc = run(fake, tmp_path, state, *args_of("move", tmp_path, move_spec(fake, ids)))
    assert proc.returncode == 3 and "microsoft_auth.py authorize" in proc.stderr and calls(fake) == []


def test_a_token_of_another_account_reads_and_writes_nothing(fake, tmp_path, state):
    ids = seed(fake)
    for argv in (args_of("move", tmp_path, move_spec(fake, ids), account="lee@example.com"), ["message-meta", "--account", "lee@example.com", "--ids", ids[0]],
                 ["folder-get", "--account", "lee@example.com", "--folder", "archive"]):
        proc = run(fake, tmp_path, state, *argv)
        assert proc.returncode == 1 and "another account" in proc.stderr and fake.requests == [], argv
    assert run(fake, tmp_path, state, *args_of("move", tmp_path, move_spec(fake, ids)), record=fake.record_json(account=None)).returncode == 1 and fake.requests == []


def test_no_token_is_exit_three(fake, tmp_path, state):
    env = env_of(fake, tmp_path, state)
    env.pop("MICROSOFT_ACCOUNT_TOKEN")
    env["HOME"] = str(tmp_path / "empty-home")
    proc = run(fake, tmp_path, state, "message-meta", "--account", fgm.ADDRESS, "--ids", "AAMkMsg0001=", env=env)
    assert proc.returncode == 3 and "microsoft_auth.py authorize" in proc.stderr


# --- what this writer can never send ------------------------------------------------------------------------------------------------------------------


def load_writer():
    spec = importlib.util.spec_from_file_location("outlook_mail_writer_under_test", WRITER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class StubSession:
    class client:
        token = "t"
        url_for = staticmethod(lambda path, query: "http://127.0.0.1:1" + path)


@pytest.mark.parametrize("entry, path", [(("DELETE", r"/me/messages/[^/]+"), "/me/messages/m1"),
                                         (("POST", r"/me/messages/[^/]+/permanentDelete"), "/me/messages/m1/permanentDelete"),
                                         (("POST", r"/me/messages/[^/]+/send"), "/me/messages/m1/send"),
                                         (("POST", r"/me/messages/[^/]+/reply"), "/me/messages/m1/reply"),
                                         (("POST", r"/me/messages/[^/]+/replyAll"), "/me/messages/m1/replyAll"),
                                         (("POST", r"/me/messages/[^/]+/forward"), "/me/messages/m1/forward"),
                                         (("POST", r"/me/sendMail"), "/me/sendMail"),
                                         (("POST", r"/me/messages/[^/]+/copy"), "/me/messages/m1/copy"),
                                         (("PATCH", r"/me/mailFolders/[^/]+"), "/me/mailFolders/inbox"),
                                         (("GET", r"/me/messages"), "/me/messages/m1/attachments")])
def test_the_request_function_refuses_any_request_outside_its_allow_list_before_a_connection_is_opened(entry, path):
    module = load_writer()
    with pytest.raises(module.WriterError) as why:
        module.request(entry, StubSession, path, {}, {})
    assert why.value.code == 2 and "allow-list" in str(why.value)


def test_the_allow_list_holds_no_send_no_removal_no_copy_and_no_method_but_get_post_and_patch():
    module = load_writer()
    assert {method for method, _ in module.ALLOWED} == {"GET", "POST", "PATCH"}
    joined = " ".join(pattern for _, pattern in module.ALLOWED).lower()
    for word in ("send", "reply", "forward", "permanent", "copy", "attachments", "empty"):
        if word == "reply":
            assert "createreply" in joined and joined.replace("createreply", "").count("reply") == 0
        else:
            assert word not in joined, word
    assert module.SERVES == "writer:mailbox" and module.IMPLEMENTATION == "outlook-mail"


@pytest.mark.parametrize("verb", ["send", "delete", "reply", "forward", "copy", "empty", "permanent-delete"])
def test_a_verb_the_writer_does_not_have_is_exit_two(fake, tmp_path, state, verb):
    proc = run(fake, tmp_path, state, verb, "--account", fgm.ADDRESS)
    assert proc.returncode == 2 and fake.requests == []


def test_the_test_overrides_are_loopback_only_and_set_together(fake, tmp_path, state):
    env = env_of(fake, tmp_path, state)
    env["WRITER_MAIL_OUTLOOK_API_BASE"] = "https://graph.microsoft.com/v1.0"
    assert run(fake, tmp_path, state, "folder-get", "--account", fgm.ADDRESS, "--folder", "archive", env=env).returncode == 2
    env = env_of(fake, tmp_path, state)
    env.pop("WRITER_MAIL_OUTLOOK_TOKEN_URL")
    assert run(fake, tmp_path, state, "folder-get", "--account", fgm.ADDRESS, "--folder", "archive", env=env).returncode == 2


def test_a_flag_a_verb_does_not_read_and_a_missing_one_are_usage_errors(fake, tmp_path, state):
    ids = seed(fake, 1)
    spec = spec_file(tmp_path, move_spec(fake, ids))
    assert run(fake, tmp_path, state, "move", "--account", fgm.ADDRESS, "--spec-file", spec, "--idempotency-key", KEY).returncode == 2           # neither mode
    assert run(fake, tmp_path, state, "move", "--account", fgm.ADDRESS, "--spec-file", spec, "--idempotency-key", KEY, "--dry-run", "--confirmed").returncode == 2
    assert run(fake, tmp_path, state, "move", "--spec-file", spec, "--idempotency-key", KEY, "--dry-run").returncode == 2                         # no account
    assert run(fake, tmp_path, state, "move", "--account", fgm.ADDRESS, "--message", "m1", "--spec-file", spec, "--idempotency-key", KEY, "--dry-run").returncode == 2
    assert run(fake, tmp_path, state, "draft-reply", "--account", fgm.ADDRESS, "--spec-file", spec_file(tmp_path, {"x": 1}), "--idempotency-key", KEY, "--dry-run").returncode == 2
    assert run(fake, tmp_path, state, "--check", "move").returncode == 2
    link = tmp_path / "link.json"
    link.symlink_to(spec)
    assert run(fake, tmp_path, state, "move", "--account", fgm.ADDRESS, "--spec-file", str(link), "--idempotency-key", KEY, "--dry-run").returncode == 2
    assert fake.requests == []


REPLY_SPEC = {"to": ["ana1@clinic.example"], "cc": [], "bcc": [], "subject": "RE: Subject number 1", "body": "Thanks, Monday works.\n"}


def reply_argv(tmp_path, one, mode="--confirmed"):
    return ["draft-reply", "--account", fgm.ADDRESS, "--message", one, "--spec-file", spec_file(tmp_path, REPLY_SPEC), "--idempotency-key", KEY, mode]


def drafts_in(fake, folder):
    return [m for m in fake.messages.values() if m["isDraft"] and m["parentFolderId"] == fgm.FOLDERS[folder]]


def test_a_reply_whose_patch_was_lost_is_unknown_and_a_retry_sets_the_text_of_the_same_draft(fake, tmp_path, state):
    [one] = seed(fake, 1)
    fake.fail_write_number = (2, 500)
    lost = run(fake, tmp_path, state, *reply_argv(tmp_path, one))
    assert lost.returncode == 4 and "send it again to set it" in lost.stderr
    [made] = drafts_in(fake, "drafts")
    assert made["toRecipients"] == [{"emailAddress": {"address": "ana1@clinic.example"}}], "createReply carried the approved message: no draft addressed as Graph would"
    fake.fail_write_number = None
    fake.requests.clear()
    done = out(run(fake, tmp_path, state, *reply_argv(tmp_path, one)))
    assert done["draft_id"] == made["id"] and done["replayed"] is False
    assert [(m, p) for m, p, _, _ in calls(fake)] == [("PATCH", path_of(made["id"]))], "no second createReply: the draft whose id the ledger noted before the PATCH is the one set"
    assert len(drafts_in(fake, "drafts")) == 1


def test_a_reply_whose_patch_is_refused_while_createreply_ignored_the_message_is_moved_to_deleted_items_and_the_key_is_free(fake, tmp_path, state):
    [one] = seed(fake, 1)
    fake.ignore_reply_body = True
    fake.fail_write_number = (2, 403)
    refused = run(fake, tmp_path, state, *reply_argv(tmp_path, one))
    assert refused.returncode == 1 and "moved to Deleted Items" in refused.stderr
    assert drafts_in(fake, "drafts") == [] and len(drafts_in(fake, "deleteditems")) == 1, "no draft addressed as Graph would is left in Drafts"
    assert out(run(fake, tmp_path, state, *reply_argv(tmp_path, one, "--dry-run")))["ledger"] == {"draft": "absent"}
    fake.ignore_reply_body = False
    fake.fail_write_number = None
    done = out(run(fake, tmp_path, state, *reply_argv(tmp_path, one)))
    [kept] = drafts_in(fake, "drafts")
    assert done["draft_id"] == kept["id"] and kept["toRecipients"] == [{"emailAddress": {"address": "ana1@clinic.example"}}]


def test_a_reply_that_cannot_be_moved_either_says_so_and_keeps_the_key_pending(fake, tmp_path, state):
    [one] = seed(fake, 1)
    fake.ignore_reply_body = True
    fake.fail_from_write = (2, 403)
    refused = run(fake, tmp_path, state, *reply_argv(tmp_path, one))
    assert refused.returncode == 1 and "could not be moved" in refused.stderr and "remove it yourself" in refused.stderr
    assert out(run(fake, tmp_path, state, *reply_argv(tmp_path, one, "--dry-run")))["ledger"] == {"draft": "pending"}


@pytest.mark.parametrize("name", ["Drafts", "Outbox", "SentItems", "RecoverableItemsPurges", "MsgFolderRoot", "DrAfTs", "JUNKEMAILX", "Clutter", "junkemail", "JunkEmail"])
def test_a_well_known_name_is_refused_whatever_its_case_unless_it_is_one_of_the_four(fake, tmp_path, state, name):
    ids = seed(fake, 1)
    proc = run(fake, tmp_path, state, *args_of("move", tmp_path, move_spec(fake, ids, to=name)))
    assert proc.returncode == 2 and fake.requests == [], name


def test_after_a_retry_the_partial_report_lists_every_message_the_ledger_holds_done_and_an_unprovable_pending_one_is_unknown_not_changed(fake, tmp_path, state):
    ids = seed(fake, 4)
    spec = move_spec(fake, ids)
    fake.fail_write_number = (2, 500)
    first = run(fake, tmp_path, state, *args_of("move", tmp_path, spec))
    assert first.returncode == 4 and "partial: done 1 of 4" in first.stderr
    fake.fail_write_number = (4, 500)
    second = run(fake, tmp_path, state, *args_of("move", tmp_path, spec))
    assert second.returncode == 4 and "partial: done 1,2 of 4" in second.stderr, "the first attempt's message is counted too"
    fake.fail_write_number = None
    del fake.messages[ids[3]]                      # the message the lost answer left pending is gone, and no copy of it is in the destination
    third = run(fake, tmp_path, state, *args_of("move", tmp_path, spec))
    assert third.returncode == 1 and "changed:" in third.stderr and "positions 4" in third.stderr, "a message the writer never tried and somebody moved is stale, not unknown"
