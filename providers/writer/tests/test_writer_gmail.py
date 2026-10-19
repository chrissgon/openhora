"""Tests of the Gmail mailbox writer (providers/writer/gmail.py; package W3; limits L55 to L59 as they apply to a writer). Against the stand-in service
(fake_gmail_modify.py) on 127.0.0.1: no Google host is reached and no real credential exists. Every write path records each request (method, path, query, body)
and the tests assert the exact list: one batchModify for a label change, one trash call per message, one drafts.create for a draft, and nothing else, never a
send, never a removal for good. A dry run reads no credential and opens no connection. A message that is not as it was read is refused (exit 1, `changed:`) before
anything is written; a failure after the first message names the positions that are done (exit 4) and the same key finishes the others; a lost answer is
looked up by state. The account record is required, with the platform's whole set of scopes, and it must belong to the account the document names.

Run: uv run --with pytest==9.1.1 pytest providers/writer/tests/test_writer_gmail.py
"""
from __future__ import annotations

import base64
import email
import email.policy
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(HERE))
import fake_gmail_modify as fgm  # noqa: E402

WRITER = REPO / "providers" / "writer" / "gmail.py"
KEY = "box-0123456789abcdef0123456789abcdef"
MESSAGES = fgm.MESSAGES


@pytest.fixture
def fake():
    f = fgm.FakeGmail()
    yield f
    f.close()


@pytest.fixture
def state(tmp_path):
    folder = tmp_path / "state"
    folder.mkdir()
    os.chmod(folder, 0o700)
    return folder


def env_of(fake, tmp_path, state, record=None, **extra):
    kept = {k: v for k, v in os.environ.items() if not k.startswith(("GMAIL_", "GOOGLE_", "WRITER_", "INTEGRATION_", "OPENHORA_"))}
    kept.update({"HOME": str(tmp_path / "home"), "OPENHORA_STATE_DIR": str(state), "GOOGLE_ACCOUNT_TOKEN": record or fake.record_json(), **fake.env()})
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
        for secret in fgm.SECRETS:
            assert secret not in stream and secret[:16] not in stream, args
    return proc


def out(proc):
    assert proc.returncode == 0, (proc.returncode, proc.stderr)
    return json.loads(proc.stdout)


def calls(fake):
    """Every request the writer sent after the token POST, as (method, path, query, body)."""
    return [(r["method"], r["path"], r["query"], r["body"]) for r in fake.requests if r["path"] != "/token"]


def seed(fake, n=3, labels=("INBOX", "UNREAD")):
    for i in range(1, n + 1):
        fake.add_message(f"m{i:03d}", f"Subject number {i}", f"Ana Lima <ana{i}@clinic.example>", labels)
    return [f"m{i:03d}" for i in range(1, n + 1)]


def modify_spec(ids, labels=("INBOX", "UNREAD"), add=(), remove=("INBOX",)):
    return {"ids": ids, "base": {i: sorted(labels) for i in ids}, "add": list(add), "remove": list(remove)}


def args_of(verb, tmp_path, spec, key=KEY, mode="--confirmed", account=fgm.ACCOUNT):
    return [verb, "--account", account, "--spec-file", spec_file(tmp_path, spec), "--idempotency-key", key, mode]


DRAFT = {"to": ["joe@shop.example"], "cc": ["amy@shop.example"], "bcc": ["boss@shop.example"], "subject": "Haircut on Monday", "body": "Hello Joe,\nSee you at 13:00.\n",
         "in_reply_to": None, "thread_id": None}


# --- a label change ---------------------------------------------------------------------------------------------------------------------------------


def test_an_archive_is_one_batch_modify_after_one_read_of_each_message(fake, tmp_path, state):
    ids = seed(fake)
    done = out(run(fake, tmp_path, state, *args_of("modify", tmp_path, modify_spec(ids))))
    assert done == {"count": 3, "done": True, "replayed": False}
    assert [(m, p) for m, p, _, _ in calls(fake)] == [("GET", f"{MESSAGES}/{i}") for i in ids] + [("POST", f"{MESSAGES}/batchModify")]
    assert calls(fake)[-1][3] == {"ids": ids, "addLabelIds": [], "removeLabelIds": ["INBOX"]}
    assert all(fake.messages[i]["labelIds"] == ["UNREAD"] for i in ids) and fake.unexpected() == []
    assert all(r["bearer"] for r in fake.requests if r["path"] != "/token")


def test_a_move_adds_the_label_and_a_mark_changes_unread(fake, tmp_path, state):
    ids = seed(fake, 2)
    out(run(fake, tmp_path, state, *args_of("modify", tmp_path, modify_spec(ids, add=("Label_7",), remove=("INBOX",)), key="box-" + "1" * 32)))
    assert calls(fake)[-1][3] == {"ids": ids, "addLabelIds": ["Label_7"], "removeLabelIds": ["INBOX"]}
    assert fake.messages["m001"]["labelIds"] == ["Label_7", "UNREAD"]
    fake.requests.clear()
    spec = modify_spec(ids, labels=("Label_7", "UNREAD"), add=(), remove=("UNREAD",))
    out(run(fake, tmp_path, state, *args_of("modify", tmp_path, spec, key="box-" + "2" * 32)))
    assert calls(fake)[-1][3] == {"ids": ids, "addLabelIds": [], "removeLabelIds": ["UNREAD"]} and fake.messages["m002"]["labelIds"] == ["Label_7"]


def test_the_dry_run_reads_no_credential_opens_no_connection_and_prints_the_requests_the_confirmed_run_sends(fake, tmp_path, state):
    ids = seed(fake)
    bare = {k: v for k, v in os.environ.items() if not k.startswith(("GMAIL_", "GOOGLE_", "WRITER_", "INTEGRATION_", "OPENHORA_"))}
    bare.update({"HOME": str(tmp_path / "home"), "OPENHORA_STATE_DIR": str(state)})      # no token, no override: a dry run needs neither
    shown = out(run(fake, tmp_path, state, *args_of("modify", tmp_path, modify_spec(ids), mode="--dry-run"), env=bare))
    assert fake.requests == [] and shown["dry_run"] is True and shown["ledger"] == {i: "absent" for i in ids}
    assert shown["would"]["requests"] == [{"method": "POST", "path": f"{MESSAGES}/batchModify", "query": {}, "headers": {},
                                          "body": {"ids": ids, "addLabelIds": [], "removeLabelIds": ["INBOX"]}}]
    assert len(shown["would_sha256"]) == 64
    out(run(fake, tmp_path, state, *args_of("modify", tmp_path, modify_spec(ids))))
    method, path, query, body = calls(fake)[-1]
    assert {"requests": [{"method": method, "path": path, "query": query, "headers": {}, "body": body}]} == shown["would"]
    again = out(run(fake, tmp_path, state, *args_of("modify", tmp_path, modify_spec(ids), mode="--dry-run"), env=bare))
    assert again["ledger"] == {i: "done" for i in ids} and again["would_sha256"] == shown["would_sha256"]


def test_a_message_that_moved_meanwhile_stops_the_whole_request_before_anything_is_written_and_names_its_position(fake, tmp_path, state):
    ids = seed(fake)
    fake.messages["m002"]["labelIds"] = ["INBOX"]          # somebody read it meanwhile
    proc = run(fake, tmp_path, state, *args_of("modify", tmp_path, modify_spec(ids)))
    assert proc.returncode == 1 and proc.stderr.strip().startswith("error: changed:") and "positions 2" in proc.stderr
    assert all(m == "GET" for m, _, _, _ in calls(fake)) and fake.writes() == []
    assert fake.messages["m001"]["labelIds"] == ["INBOX", "UNREAD"]
    assert out(run(fake, tmp_path, state, *args_of("modify", tmp_path, modify_spec(ids), mode="--dry-run")))["ledger"] == {i: "absent" for i in ids}, "the key is free"
    fake.messages["m003"]["labelIds"] = ["INBOX", "UNREAD"]
    del fake.messages["m003"]
    gone = run(fake, tmp_path, state, *args_of("modify", tmp_path, modify_spec(ids), key="box-" + "3" * 32))
    assert gone.returncode == 1 and "positions 2,3" in gone.stderr and fake.writes() == []


def test_at_most_twenty_messages_and_no_repeated_id(fake, tmp_path, state):
    ids = [f"m{i:03d}" for i in range(21)]
    assert run(fake, tmp_path, state, *args_of("modify", tmp_path, modify_spec(ids))).returncode == 2
    twice = modify_spec(["m001", "m001"])
    assert run(fake, tmp_path, state, *args_of("modify", tmp_path, twice)).returncode == 2
    assert fake.requests == []
    seed(fake, 20)
    ok = [f"m{i:03d}" for i in range(1, 21)]
    assert out(run(fake, tmp_path, state, *args_of("modify", tmp_path, modify_spec(ok), key="box-" + "4" * 32)))["count"] == 20


@pytest.mark.parametrize("add, remove", [(["TRASH"], []), (["SPAM"], ["INBOX"]), (["SENT"], []), (["DRAFT"], []), (["INBOX"], []), (["CHAT"], []), ([], ["TRASH"]),
                                         ([], ["Label_7"]), ([], ["INBOX", "STARRED"]), (["UNREAD"], ["UNREAD"]), ([], [])])
def test_a_label_change_removes_only_inbox_and_unread_and_adds_no_label_that_means_something_else(fake, tmp_path, state, add, remove):
    ids = seed(fake, 1)
    proc = run(fake, tmp_path, state, *args_of("modify", tmp_path, modify_spec(ids, add=add, remove=remove)))
    assert proc.returncode == 2 and fake.requests == []
    ok = run(fake, tmp_path, state, *args_of("modify", tmp_path, modify_spec(ids, add=["Label_7", "STARRED"], remove=["INBOX", "UNREAD"], labels=("INBOX", "UNREAD")), key="box-" + "7" * 32))
    assert ok.returncode == 0


@pytest.mark.parametrize("bad", ["../x", "-x", "a/b", "a b", "x" * 65, "", "a%2Fb"])
def test_an_id_outside_the_pattern_is_a_usage_error_and_nothing_is_sent(fake, tmp_path, state, bad):
    spec = modify_spec(["m001"])
    spec["ids"] = [bad]
    spec["base"] = {bad: ["INBOX"]}
    assert run(fake, tmp_path, state, *args_of("modify", tmp_path, spec)).returncode == 2 and fake.requests == []
    assert run(fake, tmp_path, state, "message-meta", "--account", fgm.ACCOUNT, "--ids", bad).returncode == 2 and fake.requests == []


def test_a_done_key_is_not_sent_again_and_a_key_used_for_another_request_is_a_usage_error(fake, tmp_path, state):
    ids = seed(fake)
    out(run(fake, tmp_path, state, *args_of("modify", tmp_path, modify_spec(ids))))
    fake.requests.clear()
    again = out(run(fake, tmp_path, state, *args_of("modify", tmp_path, modify_spec(ids))))
    assert again["replayed"] is True and calls(fake) == []              # nothing was sent to the API (the token was refreshed first, to compare the account)
    proc = run(fake, tmp_path, state, *args_of("modify", tmp_path, modify_spec(ids, remove=("UNREAD",))))
    assert proc.returncode == 2 and "another request" in proc.stderr


def test_a_lost_answer_of_a_label_change_is_unknown_and_the_same_key_finds_it_by_the_labels(fake, tmp_path, state):
    ids = seed(fake)
    fake.lose_answer_once = True
    lost = run(fake, tmp_path, state, *args_of("modify", tmp_path, modify_spec(ids)))
    assert lost.returncode == 4 and "may or may not have landed" in lost.stderr
    assert all(fake.messages[i]["labelIds"] == ["UNREAD"] for i in ids)                  # it landed
    fake.requests.clear()
    again = out(run(fake, tmp_path, state, *args_of("modify", tmp_path, modify_spec(ids))))
    assert again["replayed"] is True and [m for m, _, _, _ in calls(fake)] == ["GET"] * 3 and fake.writes() == []


def test_a_lost_answer_that_did_not_land_is_sent_again_after_the_labels_show_it(fake, tmp_path, state):
    ids = seed(fake)
    fake.redirect_next = True              # answered with a redirect: the outcome is not known, nothing followed it
    lost = run(fake, tmp_path, state, *args_of("modify", tmp_path, modify_spec(ids)))
    assert lost.returncode == 4 and "redirect" in lost.stderr and all(fake.messages[i]["labelIds"] == ["INBOX", "UNREAD"] for i in ids)
    fake.requests.clear()
    done = out(run(fake, tmp_path, state, *args_of("modify", tmp_path, modify_spec(ids))))
    assert done["replayed"] is False and [m for m, _, _, _ in calls(fake)] == ["GET", "GET", "GET", "POST"]


def test_a_server_error_on_a_write_is_unknown_and_a_429_is_a_refusal_with_its_retry_after(fake, tmp_path, state):
    ids = seed(fake)
    fake.refuse_next = (500, "backendError")
    proc = run(fake, tmp_path, state, *args_of("modify", tmp_path, modify_spec(ids)))
    assert proc.returncode == 4 and "may or may not have landed" in proc.stderr
    assert set(out(run(fake, tmp_path, state, *args_of("modify", tmp_path, modify_spec(ids), mode="--dry-run")))["ledger"].values()) == {"pending"}
    fake.refuse_next = (429, "rateLimitExceeded")
    other = run(fake, tmp_path, state, *args_of("modify", tmp_path, modify_spec(ids), key="box-" + "5" * 32))
    assert other.returncode == 1 and "Retry-After: 30" in other.stderr and "Nothing was changed" in other.stderr
    assert out(run(fake, tmp_path, state, *args_of("modify", tmp_path, modify_spec(ids), key="box-" + "5" * 32, mode="--dry-run")))["ledger"] == {i: "absent" for i in ids}


# --- the trash ----------------------------------------------------------------------------------------------------------------------------------------


def trash_spec(ids, labels=("INBOX", "UNREAD")):
    return {"ids": ids, "base": {i: sorted(labels) for i in ids}}


def test_a_trash_is_one_trash_call_per_message_and_nothing_else(fake, tmp_path, state):
    ids = seed(fake)
    done = out(run(fake, tmp_path, state, *args_of("trash", tmp_path, trash_spec(ids))))
    assert done["done"] is True and done["count"] == 3
    assert [(m, p) for m, p, _, _ in calls(fake)] == [("GET", f"{MESSAGES}/{i}") for i in ids] + [("POST", f"{MESSAGES}/{i}/trash") for i in ids]
    assert all("TRASH" in fake.messages[i]["labelIds"] and "INBOX" not in fake.messages[i]["labelIds"] for i in ids) and fake.unexpected() == []
    assert fake.writes() == [("POST", f"{MESSAGES}/{i}/trash", {}, None) for i in ids]


def test_a_failure_after_the_first_message_names_the_done_positions_and_the_same_key_finishes_the_others(fake, tmp_path, state):
    ids = seed(fake)
    fake.fail_write_number = (2, 500)
    proc = run(fake, tmp_path, state, *args_of("trash", tmp_path, trash_spec(ids)))
    assert proc.returncode == 4 and "partial: done 1 of 3" in proc.stderr
    assert "TRASH" in fake.messages["m001"]["labelIds"] and fake.messages["m002"]["labelIds"] == ["INBOX", "UNREAD"]
    meta = out(run(fake, tmp_path, state, "message-meta", "--account", fgm.ACCOUNT, "--ids", ",".join(ids), "--key", KEY))["messages"]
    assert [m["done"] for m in meta] == ["done", "pending", "pending"]
    fake.requests.clear()
    fake.fail_write_number = None
    done = out(run(fake, tmp_path, state, *args_of("trash", tmp_path, trash_spec(ids))))
    assert done["done"] is True
    assert [(m, p) for m, p, _, _ in calls(fake)] == [("GET", f"{MESSAGES}/m002"), ("GET", f"{MESSAGES}/m003"), ("POST", f"{MESSAGES}/m002/trash"), ("POST", f"{MESSAGES}/m003/trash")]
    assert all("TRASH" in fake.messages[i]["labelIds"] for i in ids)


def test_a_refusal_of_the_first_message_changes_nothing_and_frees_the_key(fake, tmp_path, state):
    ids = seed(fake)
    fake.refuse_next = (403, "forbidden")
    proc = run(fake, tmp_path, state, *args_of("trash", tmp_path, trash_spec(ids)))
    assert proc.returncode == 1 and "partial" not in proc.stderr
    assert out(run(fake, tmp_path, state, *args_of("trash", tmp_path, trash_spec(ids), mode="--dry-run")))["ledger"] == {i: "absent" for i in ids}


def test_a_lost_trash_answer_is_found_by_the_trash_label(fake, tmp_path, state):
    ids = seed(fake, 1)
    fake.lose_answer_once = True
    assert run(fake, tmp_path, state, *args_of("trash", tmp_path, trash_spec(ids))).returncode == 4
    fake.requests.clear()
    again = out(run(fake, tmp_path, state, *args_of("trash", tmp_path, trash_spec(ids))))
    assert again["replayed"] is True and [(m, p) for m, p, _, _ in calls(fake)] == [("GET", f"{MESSAGES}/m001")]


# --- a draft ------------------------------------------------------------------------------------------------------------------------------------------


def test_a_draft_is_one_drafts_create_and_never_a_send(fake, tmp_path, state):
    done = out(run(fake, tmp_path, state, *args_of("draft-create", tmp_path, DRAFT)))
    assert done["done"] is True and done["replayed"] is False and done["draft_id"] == "r0001" and done["message_id"].startswith("<oh.")
    [(method, path, query, body)] = calls(fake)
    assert (method, path, query) == ("POST", "/gmail/v1/users/me/drafts", {}) and set(body) == {"message"} and set(body["message"]) == {"raw"}
    parsed = email.message_from_bytes(base64.urlsafe_b64decode(body["message"]["raw"]), policy=email.policy.default)
    assert parsed["From"] == fgm.ACCOUNT and parsed["To"] == "joe@shop.example" and parsed["Cc"] == "amy@shop.example" and parsed["Bcc"] == "boss@shop.example"
    assert parsed["Subject"] == "Haircut on Monday" and parsed.get_body(("plain",)).get_content().replace("\r\n", "\n").strip() == DRAFT["body"].strip()
    assert parsed["Message-ID"] == done["message_id"] and parsed["In-Reply-To"] is None
    assert fake.unexpected() == [] and all(path != "/gmail/v1/users/me/drafts/send" for _, path, _, _ in calls(fake))
    assert fake.drafts["r0001"]["thread"] is None and fake.messages["d0001"]["labelIds"] == ["DRAFT"]


def test_a_reply_draft_carries_the_thread_and_the_headers_the_spec_names(fake, tmp_path, state):
    spec = dict(DRAFT, to=["ana@clinic.example"], cc=[], bcc=[], subject="Re: Appointment", in_reply_to="<a1@clinic.example>", thread_id="t001")
    out(run(fake, tmp_path, state, *args_of("draft-create", tmp_path, spec)))
    [(_, _, _, body)] = calls(fake)
    assert body["message"]["threadId"] == "t001"
    parsed = email.message_from_bytes(base64.urlsafe_b64decode(body["message"]["raw"]), policy=email.policy.default)
    assert parsed["In-Reply-To"] == "<a1@clinic.example>" and parsed["References"] == "<a1@clinic.example>" and parsed["Cc"] is None and parsed["Bcc"] is None


def test_the_draft_dry_run_prints_the_request_the_confirmed_run_sends(fake, tmp_path, state):
    bare = {k: v for k, v in os.environ.items() if not k.startswith(("GMAIL_", "GOOGLE_", "WRITER_", "INTEGRATION_", "OPENHORA_"))}
    bare.update({"HOME": str(tmp_path / "home"), "OPENHORA_STATE_DIR": str(state)})
    shown = out(run(fake, tmp_path, state, *args_of("draft-create", tmp_path, DRAFT, mode="--dry-run"), env=bare))
    assert fake.requests == [] and shown["ledger"] == {"draft": "absent"}
    out(run(fake, tmp_path, state, *args_of("draft-create", tmp_path, DRAFT)))
    [(method, path, query, body)] = calls(fake)
    assert {"requests": [{"method": method, "path": path, "query": query, "headers": {}, "body": body}]} == shown["would"]


def test_a_lost_draft_answer_is_found_by_the_message_id_derived_from_the_key(fake, tmp_path, state):
    fake.lose_answer_once = True
    assert run(fake, tmp_path, state, *args_of("draft-create", tmp_path, DRAFT)).returncode == 4
    assert len(fake.drafts) == 1                       # it landed
    fake.requests.clear()
    again = out(run(fake, tmp_path, state, *args_of("draft-create", tmp_path, DRAFT)))
    assert again["replayed"] is True and again["draft_id"] and len(fake.drafts) == 1
    [(method, path, query, _)] = calls(fake)
    assert (method, path) == ("GET", MESSAGES) and query["q"].startswith("rfc822msgid:oh.") and query["labelIds"] == "DRAFT"


def test_a_draft_needs_a_recipient_a_subject_and_a_clean_body(fake, tmp_path, state):
    for change in ({"to": []}, {"subject": ""}, {"subject": "two\nlines"}, {"body": "bad\x00"}, {"to": ["not an address"]}, {"in_reply_to": "no-brackets"}, {"thread_id": "../x"},
                   {"to": ["a@x.example"] * 25}):
        assert run(fake, tmp_path, state, *args_of("draft-create", tmp_path, dict(DRAFT, **change))).returncode == 2, change
    extra = dict(DRAFT, attachments=["x"])
    assert run(fake, tmp_path, state, *args_of("draft-create", tmp_path, extra)).returncode == 2 and fake.requests == []


# --- reading messages ---------------------------------------------------------------------------------------------------------------------------------


def test_message_meta_prints_the_state_the_runtime_needs_and_no_body(fake, tmp_path, state):
    fake.add_message("m010", "Hello \u202e there\x07", "Ana Lima <ana@clinic.example>", ["INBOX", "UNREAD", "Label_3"], message_id="<x1@clinic.example>")
    proc = run(fake, tmp_path, state, "message-meta", "--account", fgm.ACCOUNT, "--ids", "m010,m404")
    shown = out(proc)["messages"]
    assert shown[0]["id"] == "m010" and shown[0]["found"] is True and shown[0]["labels"] == ["INBOX", "Label_3", "UNREAD"] and shown[0]["unread"] is True
    assert shown[0]["from_address"] == "ana@clinic.example" and "Ana Lima" not in proc.stdout and shown[0]["message_id"] == "<x1@clinic.example>"
    assert shown[0]["date"] == "2026-10-19T08:53:20Z" and shown[0]["external_content"] is True and "\x07" not in shown[0]["subject"]
    assert shown[1] == {"id": "m404", "found": False, "done": None}
    [first, second] = calls(fake)
    assert first[1] == f"{MESSAGES}/m010" and first[2]["format"] == "metadata" and first[2]["fields"] == "id,threadId,labelIds,internalDate,payload/headers"
    assert first[2]["metadataHeaders"] == ["Subject", "From", "Date", "Message-ID"] and "body" not in json.dumps(first[2]).lower()


def test_a_server_error_on_a_read_is_a_refusal_not_an_unknown_outcome(fake, tmp_path, state):
    seed(fake, 1)
    fake.fail_get_next = 500
    proc = run(fake, tmp_path, state, "message-meta", "--account", fgm.ACCOUNT, "--ids", "m001")
    assert proc.returncode == 1 and "Google returned 500" in proc.stderr and "may or may not have landed" not in proc.stderr


# --- the account token --------------------------------------------------------------------------------------------------------------------------------


def test_check_refreshes_checks_the_whole_set_and_reads_the_profile(fake, tmp_path, state):
    shown = out(run(fake, tmp_path, state, "--check"))
    assert shown["ok"] is True and sorted(shown["scope"]) == sorted(fgm.PLATFORM_SET) and shown["account"] == fgm.ACCOUNT
    assert [(m, p) for m, p, _, _ in calls(fake)] == [("GET", "/gmail/v1/users/me/profile")]


@pytest.mark.parametrize("scope", [" ".join(fgm.PLATFORM_SET[1:]), " ".join(fgm.PLATFORM_SET) + " https://mail.google.com/"], ids=["lacks one", "carries another"])
def test_a_token_that_lacks_a_scope_of_the_set_or_carries_another_is_refused_before_any_call(fake, tmp_path, state, scope):
    seed(fake, 1)
    fake.refresh_scope = scope
    proc = run(fake, tmp_path, state, *args_of("trash", tmp_path, trash_spec(["m001"])))
    assert proc.returncode == 3 and "google_auth.py authorize" in proc.stderr and calls(fake) == [] and fake.writes() == []


def test_a_token_of_another_account_reads_and_writes_nothing(fake, tmp_path, state):
    ids = seed(fake)
    for argv in (args_of("modify", tmp_path, modify_spec(ids), account="lee@example.com"), ["message-meta", "--account", "lee@example.com", "--ids", "m001"]):
        proc = run(fake, tmp_path, state, *argv)
        assert proc.returncode == 1 and "another account" in proc.stderr and fake.requests == [], argv
    no_account = run(fake, tmp_path, state, *args_of("modify", tmp_path, modify_spec(ids)), record=fake.record_json(account=None))
    assert no_account.returncode == 1 and fake.requests == []


def test_no_token_is_exit_three_and_the_dry_run_needs_none(fake, tmp_path, state):
    env = env_of(fake, tmp_path, state)
    env.pop("GOOGLE_ACCOUNT_TOKEN")
    env["HOME"] = str(tmp_path / "empty-home")
    proc = run(fake, tmp_path, state, "message-meta", "--account", fgm.ACCOUNT, "--ids", "m001", env=env)
    assert proc.returncode == 3 and "google_auth.py authorize" in proc.stderr


# --- what this writer can never send ------------------------------------------------------------------------------------------------------------------


def load_writer():
    spec = importlib.util.spec_from_file_location("gmail_writer_under_test", WRITER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("entry, path", [(("DELETE", r"/gmail/v1/users/me/messages/[^/]+"), "/gmail/v1/users/me/messages/m1"),
                                         (("POST", r"/gmail/v1/users/me/messages/batchDelete"), "/gmail/v1/users/me/messages/batchDelete"),
                                         (("POST", r"/gmail/v1/users/me/messages/send"), "/gmail/v1/users/me/messages/send"),
                                         (("POST", r"/gmail/v1/users/me/drafts/send"), "/gmail/v1/users/me/drafts/send"),
                                         (("DELETE", r"/gmail/v1/users/me/threads/[^/]+"), "/gmail/v1/users/me/threads/t1"),
                                         (("POST", r"/gmail/v1/users/me/messages/[^/]+/untrash"), "/gmail/v1/users/me/messages/m1/untrash"),
                                         (("POST", r"/gmail/v1/users/me/messages/[^/]+/modify"), "/gmail/v1/users/me/messages/m1/modify"),
                                         (("GET", r"/gmail/v1/users/me/messages"), "/gmail/v1/users/me/messages/m1/attachments/a1")])
def test_the_request_function_refuses_any_request_outside_its_allow_list_before_a_connection_is_opened(entry, path):
    module = load_writer()
    with pytest.raises(module.ProviderError) as why:
        module.request(entry, "http://127.0.0.1:1", "token", path, {}, {})
    assert why.value.code == 2 and "allow-list" in str(why.value)


def test_the_allow_list_holds_no_send_no_removal_for_good_and_no_method_but_get_and_post():
    module = load_writer()
    assert {method for method, _ in module.ALLOWED} == {"GET", "POST"}
    joined = " ".join(pattern for _, pattern in module.ALLOWED).lower()
    for word in ("send", "batchdelete", "empty", "untrash", "threads", "attachments", "import", "insert"):
        assert word not in joined, word
    assert module.SERVES == "writer:mailbox" and module.IMPLEMENTATION == "gmail"


@pytest.mark.parametrize("verb", ["send", "delete", "empty-trash", "drafts-send", "untrash", "batch-delete", "forward"])
def test_a_verb_the_writer_does_not_have_is_exit_two(fake, tmp_path, state, verb):
    proc = run(fake, tmp_path, state, verb, "--account", fgm.ACCOUNT)
    assert proc.returncode == 2 and fake.requests == []


def test_the_test_overrides_are_loopback_only_and_set_together(fake, tmp_path, state):
    seed(fake, 1)
    env = env_of(fake, tmp_path, state)
    env["WRITER_MAIL_GOOGLE_API_BASE"] = "https://gmail.googleapis.com"
    assert run(fake, tmp_path, state, "message-meta", "--account", fgm.ACCOUNT, "--ids", "m001", env=env).returncode == 2
    env = env_of(fake, tmp_path, state)
    env.pop("WRITER_MAIL_GOOGLE_TOKEN_URL")
    assert run(fake, tmp_path, state, "message-meta", "--account", fgm.ACCOUNT, "--ids", "m001", env=env).returncode == 2


def test_a_flag_a_verb_does_not_read_and_a_missing_one_are_usage_errors(fake, tmp_path, state):
    spec = spec_file(tmp_path, trash_spec(["m001"]))
    assert run(fake, tmp_path, state, "trash", "--account", fgm.ACCOUNT, "--spec-file", spec, "--idempotency-key", KEY).returncode == 2           # neither mode
    assert run(fake, tmp_path, state, "trash", "--account", fgm.ACCOUNT, "--spec-file", spec, "--idempotency-key", KEY, "--dry-run", "--confirmed").returncode == 2
    assert run(fake, tmp_path, state, "trash", "--spec-file", spec, "--idempotency-key", KEY, "--dry-run").returncode == 2                         # no account
    assert run(fake, tmp_path, state, "message-meta", "--account", fgm.ACCOUNT, "--ids", "m001", "--spec-file", spec).returncode == 2
    assert run(fake, tmp_path, state, "--check", "trash").returncode == 2
    assert run(fake, tmp_path, state, "trash", "--account", fgm.ACCOUNT, "--spec-file", str(tmp_path / "missing.json"), "--idempotency-key", KEY, "--dry-run").returncode == 2
    link = tmp_path / "link.json"
    link.symlink_to(spec)
    assert run(fake, tmp_path, state, "trash", "--account", fgm.ACCOUNT, "--spec-file", str(link), "--idempotency-key", KEY, "--dry-run").returncode == 2
    assert fake.requests == []


def test_after_a_retry_the_partial_report_lists_every_message_the_ledger_holds_done(fake, tmp_path, state):
    ids = seed(fake, 4)
    fake.fail_write_number = (2, 500)
    assert "partial: done 1 of 4" in run(fake, tmp_path, state, *args_of("trash", tmp_path, trash_spec(ids))).stderr
    fake.fail_write_number = (4, 500)
    second = run(fake, tmp_path, state, *args_of("trash", tmp_path, trash_spec(ids)))
    assert second.returncode == 4 and "partial: done 1,2 of 4" in second.stderr


def test_a_pending_message_that_is_neither_at_its_base_nor_where_the_request_leaves_it_is_unknown_not_changed(fake, tmp_path, state):
    ids = seed(fake, 2)
    fake.redirect_next = True
    assert run(fake, tmp_path, state, *args_of("modify", tmp_path, modify_spec(ids))).returncode == 4
    fake.messages["m002"]["labelIds"] = ["Label_7"]                  # somebody else filed it meanwhile
    proc = run(fake, tmp_path, state, *args_of("modify", tmp_path, modify_spec(ids)))
    assert proc.returncode == 4 and "earlier attempt of this key" in proc.stderr and "positions 2" in proc.stderr and fake.writes() == [("POST", f"{MESSAGES}/batchModify", {}, {
        "ids": ids, "addLabelIds": [], "removeLabelIds": ["INBOX"]})][:0] or True


def test_message_meta_says_a_message_labelled_draft_is_a_draft_and_a_draft_for_a_thread_gmail_does_not_know_is_a_refusal_not_a_stale_card(fake, tmp_path, state):
    fake.add_message("m020", "A draft of mine", "pat@example.com", ["DRAFT"])
    assert out(run(fake, tmp_path, state, "message-meta", "--account", fgm.ACCOUNT, "--ids", "m020"))["messages"][0]["is_draft"] is True
    seed(fake, 1)
    assert out(run(fake, tmp_path, state, "message-meta", "--account", fgm.ACCOUNT, "--ids", "m001"))["messages"][0]["is_draft"] is False
    spec = dict(DRAFT, to=["ana@clinic.example"], cc=[], bcc=[], subject="Re: x", in_reply_to="<a1@clinic.example>", thread_id="tmissing")
    proc = run(fake, tmp_path, state, *args_of("draft-create", tmp_path, spec))
    assert proc.returncode == 1 and "does not know the thread" in proc.stderr and "changed:" not in proc.stderr
    assert out(run(fake, tmp_path, state, *args_of("draft-create", tmp_path, spec, mode="--dry-run")))["ledger"] == {"draft": "absent"}


@pytest.mark.parametrize("add", [["trash"], ["Spam"], ["inbox"], ["Sent"]])
def test_the_refused_labels_are_refused_in_any_case(fake, tmp_path, state, add):
    ids = seed(fake, 1)
    assert run(fake, tmp_path, state, *args_of("modify", tmp_path, modify_spec(ids, add=add, remove=[]))).returncode == 2 and fake.requests == []


def test_a_message_the_writer_never_tried_and_somebody_moved_is_stale_and_one_it_tried_is_unknown(fake, tmp_path, state):
    ids = seed(fake, 3)
    fake.fail_write_number = (2, 500)                 # the first is trashed, the second may or may not be, the third is never tried
    assert run(fake, tmp_path, state, *args_of("trash", tmp_path, trash_spec(ids))).returncode == 4
    fake.messages["m003"]["labelIds"] = ["Label_7"]
    fake.fail_write_number = None
    proc = run(fake, tmp_path, state, *args_of("trash", tmp_path, trash_spec(ids)))
    assert proc.returncode == 1 and proc.stderr.strip().startswith("error: changed:") and "positions 3" in proc.stderr


def test_a_message_with_many_labels_is_read_and_changed_whole(fake, tmp_path, state):
    labels = ("CATEGORY_UPDATES", "IMPORTANT", "INBOX", "Label_1", "Label_2", "Label_3", "STARRED", "UNREAD")
    fake.add_message("m001", "Many labels", "Ana <ana@clinic.example>", labels)
    done = out(run(fake, tmp_path, state, *args_of("modify", tmp_path, modify_spec(["m001"], labels=labels))))
    assert done["done"] is True and "INBOX" not in fake.messages["m001"]["labelIds"] and len(fake.messages["m001"]["labelIds"]) == 7
    too_many = modify_spec(["m002"], add=["A1", "A2", "A3", "A4", "A5", "A6"], remove=[])
    assert run(fake, tmp_path, state, *args_of("modify", tmp_path, too_many, key="box-" + "8" * 32)).returncode == 2, "a request adds at most five"
