"""Tests of the Outlook mailer (providers/mailer/outlook.py; package W2; limits L42, L55 to L60 as they apply to a mailer of the person's own account). Against the
stand-in service (fake_graph_send.py) on 127.0.0.1: no Microsoft host is reached and no real credential exists. Every write path records each request (method, path,
query, body) and the tests assert the exact list: the token, `GET /me`, then the draft, its update and its send. A dry run reads no credential and opens no connection,
and the requests it prints are the requests the confirmed run sends. The draft Graph made is read back and must be the approved message (the recipients exactly, the
subject, the plain text) before anything is sent; if it is not, or a step before the send fails, it is moved to Deleted Items and the key is freed. The From address
must be the address of the account token. A lost answer on the send is exit 4 and the same key finds the message in Sent Items by the Message-ID Graph gave the draft;
a key that is done is not sent again. The request function refuses any method or path outside ALLOWED, and there is no DELETE anywhere.

Run: uv run --python 3.11 --with pytest==9.1.1 --with keyring==25.7.0 pytest providers/mailer/tests/test_mailer_outlook.py
"""
from __future__ import annotations

import base64
import copy
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
import fake_graph_send as fgg  # noqa: E402

MAILER = REPO / "providers" / "mailer" / "outlook.py"
KEY = "send-0123456789abcdef0123456789abcdef"
MID = "<oh.0123456789abcdef0123456789abcdef@mail.example>"
SUBJECT = "Haircut on Monday"
BODY = "Hello Ana,\n\nSee you on Monday at one.\n\nCasey\n"
ORIGINAL = "AAMkOriginal+1="
ME = f"{fgg.GRAPH}/me"
MESSAGES = f"{fgg.GRAPH}/me/messages"
SENT_ITEMS = f"{fgg.GRAPH}/me/mailFolders/sentitems/messages"


@pytest.fixture
def fake():
    f = fgg.FakeGraphSend()
    f.add_message(ORIGINAL, "ana@client.example", "Haircut", reply_to="front-desk@client.example")
    yield f
    f.close()


@pytest.fixture
def state(tmp_path):
    folder = tmp_path / "state"
    folder.mkdir()
    os.chmod(folder, 0o700)
    return folder


def env_of(fake, tmp_path, state, record=None, **extra):
    kept = {k: v for k, v in os.environ.items() if not k.startswith(("MICROSOFT_", "OUTLOOK_", "MAILER_", "WRITER_", "INTEGRATION_", "OPENHORA_"))}
    kept.update({"HOME": str(tmp_path / "home"), "OPENHORA_STATE_DIR": str(state), "MICROSOFT_ACCOUNT_TOKEN": record or fake.record_json(), **fake.env()})
    kept.update(extra)
    return kept


def put(tmp_path, name, data):
    path = tmp_path / name
    path.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
    os.chmod(path, 0o600)
    return str(path)


def run(fake, tmp_path, state, *args, record=None, env=None):
    proc = subprocess.run([sys.executable, str(MAILER), *args], env=env or env_of(fake, tmp_path, state, record), capture_output=True, text=True, timeout=60)
    for stream in (proc.stdout, proc.stderr):    # no run ever prints a credential, not even partially (limit L59)
        for secret in fgg.SECRETS + tuple(f"fake-refresh-token-{n}-not-real" for n in range(1, 6)):
            assert secret not in stream and secret[:16] not in stream, args
    return proc


def out(proc):
    assert proc.returncode == 0, (proc.returncode, proc.stderr)
    return json.loads(proc.stdout)


def send_args(tmp_path, *, mode="--confirmed", key=KEY, sender=fgg.ADDRESS, to=("ana@client.example",), cc=(), bcc=(), extra=(), subject=SUBJECT, body=BODY, mid=MID):
    args = ["send", "--from", sender, "--to", *to]
    if cc:
        args += ["--cc", *cc]
    if bcc:
        args += ["--bcc", *bcc]
    args += ["--subject-file", put(tmp_path, "subject.txt", subject), "--body-file", put(tmp_path, "body.txt", body), "--message-id", mid,
             "--idempotency-key", key, *extra, mode]
    return args


def reply_args(tmp_path, **more):
    return send_args(tmp_path, subject="Re: Haircut", extra=["--in-reply-to", "<CA+original1@mail.client.example>", "--reply-id", ORIGINAL], **more)


def ledger_of(state):
    path = state / "mailer-outlook" / "ledger.json"
    return json.loads(path.read_text(encoding="utf-8"))["keys"] if path.exists() else {}


# --- a new message ----------------------------------------------------------------------------------------------------------------------------------


def test_a_send_is_the_token_me_a_draft_and_its_send_and_leaves_no_draft_behind(fake, tmp_path, state):
    done = out(run(fake, tmp_path, state, *send_args(tmp_path, cc=("lee@client.example",), bcc=("boss@client.example",))))
    assert done["sent"] is True and done["replayed"] is False and done["message_id"] == MID and done["recipients"] == 3 and done["service_message_id"].startswith("<AM")
    assert [(r["method"], r["path"]) for r in fake.requests[:3]] == [("POST", "/token"), ("GET", ME), ("POST", MESSAGES)]
    [token, me, create, send] = fake.requests
    assert me["query"] == {"$select": "mail,userPrincipalName"} and create["prefer"] == 'outlook.body-content-type="text"'
    assert create["body"] == {"subject": SUBJECT, "body": {"contentType": "text", "content": BODY}, "toRecipients": [fgg.recipient("ana@client.example")],
                              "ccRecipients": [fgg.recipient("lee@client.example")], "bccRecipients": [fgg.recipient("boss@client.example")]}
    draft_id = fake.sent[0]["draft_id"]
    assert (send["method"], send["path"], send["body"]) == ("POST", f"{MESSAGES}/{fake.sent[0]['draft_id']}/send", None)
    assert fake.drafts == {} and fake.deleted == [] and len(fake.sent) == 1 and fake.unexpected() == []
    assert all(r["bearer"] for r in fake.requests if r["path"] != "/token") and ledger_of(state)[KEY]["status"] == "done" and draft_id
    assert fake.sent[0]["to"] == ["ana@client.example"] and fake.sent[0]["bcc"] == ["boss@client.example"]


def test_the_dry_run_reads_no_credential_opens_no_connection_and_prints_the_requests_the_confirmed_run_sends(fake, tmp_path, state):
    bare = {k: v for k, v in os.environ.items() if not k.startswith(("MICROSOFT_", "OUTLOOK_", "MAILER_", "WRITER_", "INTEGRATION_", "OPENHORA_"))}
    bare.update({"HOME": str(tmp_path / "home"), "OPENHORA_STATE_DIR": str(state)})
    pdf = put(tmp_path, "cv.pdf", b"%PDF-1.4 a small cv")
    extra = ["--attach", f"{pdf}=CV 2026.pdf"]
    preview = out(run(fake, tmp_path, state, *send_args(tmp_path, mode="--dry-run", extra=extra), env=bare))
    assert fake.requests == [] and preview["dry_run"] is True and preview["ledger"] == "absent" and not (state / "mailer-outlook").exists()
    would = preview["would"]
    assert would["service"] == "outlook" and would["envelope"] == {"from": fgg.ADDRESS, "to": ["ana@client.example"]} and would["body"] == BODY
    [create, send, cleanup] = would["requests"]
    [attachment] = create["body"]["attachments"]
    assert attachment["contentBytes_sha256"] and "contentBytes" not in attachment and attachment["name"] == "CV 2026.pdf"
    assert send["path"] == "/me/messages/{draft}/send" and cleanup["path"] == "/me/messages/{draft}/move" and cleanup["body"] == {"destinationId": "deleteditems"}
    again = out(run(fake, tmp_path, state, *send_args(tmp_path, mode="--dry-run", extra=extra), env=bare))
    assert again["would_sha256"] == preview["would_sha256"]
    out(run(fake, tmp_path, state, *send_args(tmp_path, extra=extra)))
    real = fake.requests[2]["body"]
    [file] = real["attachments"]
    assert base64.b64decode(file["contentBytes"]) == b"%PDF-1.4 a small cv" and file["name"] == "CV 2026.pdf" and file["@odata.type"] == "#microsoft.graph.fileAttachment"
    summary = copy.deepcopy(real)
    summary["attachments"] = [{**{k: v for k, v in a.items() if k != "contentBytes"}, "contentBytes_sha256": attachment["contentBytes_sha256"], "bytes": 19} for a in real["attachments"]]
    assert summary == create["body"], "the request sent is the request previewed; the file is shown by its hash"
    assert fake.sent[0]["attachments"] and ledger_of(state)[KEY]["status"] == "done"
    assert out(run(fake, tmp_path, state, *send_args(tmp_path, mode="--dry-run", extra=extra), env=bare))["ledger"] == "done"
    assert run(fake, tmp_path, state, *send_args(tmp_path, mode="--dry-run", body=BODY + "More.\n"), env=bare).returncode == 0


def test_the_from_must_be_the_address_of_the_account_token_the_record_and_graph_both_say_it(fake, tmp_path, state):
    proc = run(fake, tmp_path, state, *send_args(tmp_path, sender="someone.else@mail.example"))
    assert proc.returncode == 3 and "not the address of the Microsoft account token" in proc.stderr and fake.requests[-1]["path"] == "/token"
    assert fake.sent == [] and fake.drafts == {} and ledger_of(state) == {}
    fake.requests.clear()
    fake.address, fake.principal = "casey.new@mail.example", "casey.new@work.example"       # the record says casey.rivera@mail.example
    proc = run(fake, tmp_path, state, *send_args(tmp_path))
    assert proc.returncode == 3 and "another address" in proc.stderr and fake.sent == [] and fake.drafts == {} and ledger_of(state) == {}
    assert [(r["method"], r["path"]) for r in fake.requests] == [("POST", "/token"), ("GET", ME)]
    fake.address, fake.principal = None, fgg.ADDRESS
    assert out(run(fake, tmp_path, state, *send_args(tmp_path)))["sent"] is True, "Graph names the address as userPrincipalName when `mail` is absent"
    fake.address = fgg.ADDRESS
    assert run(fake, tmp_path, state, *send_args(tmp_path, key="send-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"), record=fake.record_json(account=None)).returncode == 3


def test_a_token_that_lacks_a_permission_or_carries_another_is_refused_before_anything_is_made(fake, tmp_path, state):
    fake.scope_granted = " ".join(fgg.PREFIX + n for n in fgg.PLATFORM if n != "Mail.Send") + " offline_access"
    proc = run(fake, tmp_path, state, *send_args(tmp_path))
    assert proc.returncode == 3 and "Mail.Send" in proc.stderr and fake.drafts == {} and [r["path"] for r in fake.requests] == ["/token"]
    fake.scope_granted = " ".join(fgg.PREFIX + n for n in fgg.PLATFORM) + " " + fgg.PREFIX + "Mail.Read offline_access"
    assert run(fake, tmp_path, state, *send_args(tmp_path)).returncode == 3
    assert run(fake, tmp_path, state, *send_args(tmp_path), record="not json").returncode == 3


def test_the_flags_the_class_refuses_are_exit_2_before_a_credential_is_read(fake, tmp_path, state):
    for wrong in (dict(to=("Ana <ana@client.example>",)), dict(to=("ana@client.example", "ANA@client.example")), dict(subject="=?utf-8?q?x?="),
                  dict(to=tuple(f"p{i}@client.example" for i in range(21)))):
        assert run(fake, tmp_path, state, *send_args(tmp_path, **wrong)).returncode == 2, wrong
    big = put(tmp_path, "big.pdf", b"x" * (2560 * 1024 + 1))
    assert run(fake, tmp_path, state, *send_args(tmp_path, extra=["--attach", f"{big}=big.pdf"])).returncode == 2
    assert fake.requests == []


# --- a reply ---------------------------------------------------------------------------------------------------------------------------------------


def test_a_reply_is_the_draft_graph_makes_in_the_conversation_updated_to_exactly_the_approved_message_and_sent(fake, tmp_path, state):
    fake.reply_to_reply_to = True      # createReply addresses the draft to the message's Reply-To: the update puts it back to the sender
    done = out(run(fake, tmp_path, state, *reply_args(tmp_path)))
    assert done["sent"] is True
    assert [(r["method"], r["path"]) for r in fake.requests] == [("POST", "/token"), ("GET", ME), ("POST", f"{MESSAGES}/{ORIGINAL}/createReply".replace("+", "+")),
                                                                  ("PATCH", fake.requests[3]["path"]), ("POST", fake.requests[4]["path"])]
    [_, _, create, patch, send] = fake.requests
    assert create["raw_path"] == f"{MESSAGES}/AAMkOriginal%2B1%3D/createReply", "an id is percent-encoded wherever it enters a path"
    assert create["body"] == {} and patch["path"].endswith(fake.sent[0]["draft_id"]) and send["path"] == patch["path"] + "/send"
    assert patch["body"] == {"subject": "Re: Haircut", "body": {"contentType": "text", "content": BODY}, "toRecipients": [fgg.recipient("ana@client.example")],
                             "ccRecipients": [], "bccRecipients": []}
    assert fake.sent[0]["to"] == ["ana@client.example"] and "front-desk@client.example" not in sum((fake.sent[0][k] for k in ("to", "cc", "bcc")), [])
    assert fake.drafts == {} and fake.deleted == [] and fake.unexpected() == []
    preview = out(run(fake, tmp_path, state, *reply_args(tmp_path, key="send-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", mode="--dry-run")))
    assert [(r["method"], r["path"]) for r in preview["would"]["requests"]] == [("POST", f"/me/messages/AAMkOriginal%2B1%3D/createReply"),
                                                                                 ("PATCH", "/me/messages/{draft}"), ("POST", "/me/messages/{draft}/send"),
                                                                                 ("POST", "/me/messages/{draft}/move")]
    assert preview["would"]["requests"][1]["body"] == patch["body"] and preview["would"]["headers"]["In-Reply-To"] == "<CA+original1@mail.client.example>"


def test_a_reply_carries_one_recipient_no_attachment_and_its_service_id_and_never_a_thread_id(fake, tmp_path, state):
    pdf = put(tmp_path, "cv.pdf", b"%PDF-1.4")
    for wrong in (dict(cc=("lee@client.example",)), dict(bcc=("boss@client.example",)), dict(to=("ana@client.example", "lee@client.example"))):
        assert run(fake, tmp_path, state, *reply_args(tmp_path, **wrong)).returncode == 2, wrong
    assert run(fake, tmp_path, state, *send_args(tmp_path, extra=["--in-reply-to", "<c@x.example>", "--reply-id", ORIGINAL, "--attach", f"{pdf}=cv.pdf"])).returncode == 2
    assert run(fake, tmp_path, state, *send_args(tmp_path, extra=["--in-reply-to", "<c@x.example>"])).returncode == 2, "a reply needs --reply-id"
    assert run(fake, tmp_path, state, *send_args(tmp_path, extra=["--reply-id", ORIGINAL])).returncode == 2, "--reply-id goes with --in-reply-to"
    assert run(fake, tmp_path, state, *send_args(tmp_path, extra=["--in-reply-to", "<c@x.example>", "--reply-id", ORIGINAL, "--thread-id", "abc"])).returncode == 2
    assert fake.requests == []


# --- the draft is read back --------------------------------------------------------------------------------------------------------------------------


def test_a_draft_that_is_not_the_approved_message_is_moved_to_deleted_items_nothing_is_sent_and_the_key_is_free(fake, tmp_path, state):
    fake.ignore_recipients = True       # the update leaves the draft addressed to the Reply-To
    fake.reply_to_reply_to = True
    proc = run(fake, tmp_path, state, *reply_args(tmp_path))
    assert proc.returncode == 1 and "toRecipients" in proc.stderr and "Deleted Items" in proc.stderr
    assert fake.sent == [] and fake.drafts == {} and len(fake.deleted) == 1 and ledger_of(state) == {}
    assert [r["method"] for r in fake.requests if r["path"].endswith("/send")] == []
    assert fake.requests[-1]["path"].endswith("/move") and fake.requests[-1]["body"] == {"destinationId": "deleteditems"}
    fake.deleted.clear()
    fake.ignore_recipients, fake.body_as_html = False, True
    proc = run(fake, tmp_path, state, *send_args(tmp_path))
    assert proc.returncode == 1 and "plain text" in proc.stderr and fake.sent == [] and len(fake.deleted) == 1 and ledger_of(state) == {}


@pytest.mark.parametrize("kind,status,drafts_moved", [("create", 400, 0), ("createReply", 404, 0), ("patch", 500, 1), ("send", 400, 1), ("send", 429, 1)])
def test_a_step_before_the_send_that_fails_sends_nothing_moves_the_unsent_draft_and_frees_the_key(fake, tmp_path, state, kind, status, drafts_moved):
    fake.refuse_next = (kind, status)
    args = send_args(tmp_path) if kind == "create" else reply_args(tmp_path)
    proc = run(fake, tmp_path, state, *args)
    assert proc.returncode == 1 and fake.sent == [] and ledger_of(state) == {} and len(fake.deleted) == drafts_moved and fake.drafts == {}
    if status == 429:
        assert "Retry-After" in proc.stderr or "retry after 30" in proc.stderr
    assert out(run(fake, tmp_path, state, *args))["sent"] is True and len(fake.sent) == 1, "the same key may be tried again"


# --- the key: once, and a lost answer -------------------------------------------------------------------------------------------------------------------


def test_a_done_key_is_not_sent_again_and_a_key_used_for_another_message_is_a_usage_error(fake, tmp_path, state):
    out(run(fake, tmp_path, state, *send_args(tmp_path)))
    fake.requests.clear()
    again = out(run(fake, tmp_path, state, *send_args(tmp_path)))
    assert again["replayed"] is True and len(fake.sent) == 1 and [r["path"] for r in fake.requests] == ["/token", ME], "no draft, no send"
    proc = run(fake, tmp_path, state, *send_args(tmp_path, body=BODY + "Something else.\n"))
    assert proc.returncode == 2 and "another e-mail" in proc.stderr and len(fake.sent) == 1


def test_a_lost_answer_on_the_send_is_exit_4_and_the_same_key_finds_the_message_in_sent_items_by_the_message_id_graph_gave_the_draft(fake, tmp_path, state):
    fake.lose_answer_once = True
    proc = run(fake, tmp_path, state, *send_args(tmp_path))
    assert proc.returncode == 4 and len(fake.sent) == 1 and ledger_of(state)[KEY]["status"] == "pending" and ledger_of(state)[KEY]["phase"] == "sending"
    assert ledger_of(state)[KEY]["service_message_id"].startswith("<AM")
    fake.requests.clear()
    again = out(run(fake, tmp_path, state, *send_args(tmp_path)))
    assert again["replayed"] is True and len(fake.sent) == 1 and fake.drafts == {}, "found by its Message-ID: no second draft, nothing sent again"
    assert [(r["method"], r["path"]) for r in fake.requests] == [("POST", "/token"), ("GET", ME), ("GET", SENT_ITEMS)]
    assert fake.requests[2]["query"]["$filter"] == f"internetMessageId eq '{fake.sent[0]['internetMessageId']}'"
    assert ledger_of(state)[KEY]["status"] == "done"


def test_a_server_error_on_the_send_is_exit_4_the_draft_stays_and_when_the_message_is_not_in_sent_items_only_the_person_settles_the_key(fake, tmp_path, state):
    fake.refuse_next = ("send", 503)
    proc = run(fake, tmp_path, state, *send_args(tmp_path))
    assert proc.returncode == 4 and "may or may not have been sent" in proc.stderr and ledger_of(state)[KEY]["phase"] == "sending"
    assert len(fake.drafts) == 1 and fake.deleted == [], "a send that may have landed does not touch its draft"
    proc = run(fake, tmp_path, state, *send_args(tmp_path))
    assert proc.returncode == 4 and "not in Sent Items" in proc.stderr and fake.sent == [] and len(fake.drafts) == 1
    assert out(run(fake, tmp_path, state, "resolve", "--idempotency-key", KEY, "--not-sent", "--dry-run"))["dry_run"] is True
    assert ledger_of(state)[KEY]["status"] == "pending", "a dry run settles nothing"
    assert out(run(fake, tmp_path, state, "resolve", "--idempotency-key", KEY, "--not-sent", "--confirmed"))["recorded"] == "not sent"
    assert out(run(fake, tmp_path, state, *send_args(tmp_path)))["sent"] is True and len(fake.sent) == 1


def test_a_key_left_before_the_send_phase_sent_nothing_and_is_taken_again_with_a_new_draft(fake, tmp_path, state):
    out(run(fake, tmp_path, state, *send_args(tmp_path, mode="--dry-run")))
    would = out(run(fake, tmp_path, state, *send_args(tmp_path, mode="--dry-run")))["would_sha256"]
    folder = state / "mailer-outlook"
    folder.mkdir()
    os.chmod(folder, 0o700)
    for phase in ("claimed", "drafted"):
        (folder / "ledger.json").write_text(json.dumps({"keys": {KEY: {"status": "pending", "phase": phase, "message_id": MID, "payload_sha256": would,
                                                                      "recipients": 1, "created_at": "2026-10-18T09:00:00Z", "draft_id": "AAMkOld="}}}))
        os.chmod(folder / "ledger.json", 0o600)
        done = out(run(fake, tmp_path, state, *send_args(tmp_path)))
        assert done["sent"] is True and done["replayed"] is False
        assert not [r for r in fake.requests if r["path"] == SENT_ITEMS], "no lookup: nothing could have been sent in that phase"
        fake.sent.clear()
        fake.requests.clear()


def test_a_redirect_on_the_send_is_not_followed_and_is_exit_4(fake, tmp_path, state):
    fake.redirect_next = True
    proc = run(fake, tmp_path, state, *send_args(tmp_path))
    assert proc.returncode == 4 and "307" in proc.stderr and fake.sent == [] and ledger_of(state)[KEY]["status"] == "pending"
    assert not any(r["path"] == "/elsewhere" for r in fake.requests)


def test_a_lookup_that_cannot_be_made_leaves_the_key_pending_and_is_exit_4(fake, tmp_path, state):
    fake.lose_answer_once = True
    assert run(fake, tmp_path, state, *send_args(tmp_path)).returncode == 4
    original = fake.api

    def failing(entry):
        return (500, {"error": {"code": "generalException", "message": "stand-in failure"}}, {}, None) if entry["path"] == SENT_ITEMS else original(entry)
    fake.api = failing
    proc = run(fake, tmp_path, state, *send_args(tmp_path))
    assert proc.returncode == 4 and "cannot be looked up now" in proc.stderr and len(fake.sent) == 1 and ledger_of(state)[KEY]["status"] == "pending"


def test_the_lookup_verb_and_the_check_verb(fake, tmp_path, state):
    done = out(run(fake, tmp_path, state, *send_args(tmp_path)))
    assigned = done["service_message_id"]
    assert out(run(fake, tmp_path, state, "lookup", "--message-id", assigned)) == {"found": True, "count": 1, "message_id": assigned}
    assert out(run(fake, tmp_path, state, "lookup", "--message-id", "<nothing@mail.example>"))["found"] is False
    assert run(fake, tmp_path, state, "lookup", "--message-id", "not an id").returncode == 2
    fake.requests.clear()
    checked = out(run(fake, tmp_path, state, "--check"))
    assert checked["ok"] is True and checked["from"] == fgg.ADDRESS and checked["rotation"] == "not stored: the record comes from the environment or the credentials directory"
    assert [(r["method"], r["path"]) for r in fake.requests] == [("POST", "/token"), ("GET", ME)]


# --- the allow-list ----------------------------------------------------------------------------------------------------------------------------------


def load_module():
    spec = importlib.util.spec_from_file_location("mailer_outlook_under_test", MAILER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_request_function_refuses_any_method_or_path_outside_the_allow_list_before_it_opens_a_connection():
    module = load_module()
    assert [m for m, _ in module.ALLOWED] == ["GET", "POST", "POST", "PATCH", "POST", "POST", "GET"] and not [1 for m, _ in module.ALLOWED if m == "DELETE"]
    session = type("S", (), {"client": type("C", (), {"token": "t", "url_for": staticmethod(lambda path, query: "http://127.0.0.1:1" + path)})()})()
    for entry, path in ((("DELETE", r"/me/messages/[^/]+"), "/me/messages/abc"),
                        (("POST", r"/me/messages/[^/]+/send"), "/me/messages/abc/send/extra"),
                        (("POST", r"/me/messages/[^/]+/permanentDelete"), "/me/messages/abc/permanentDelete"),
                        (("POST", r"/me/sendMail"), "/me/sendMail"),
                        (("GET", r"/me"), "/me/drive")):
        with pytest.raises(module.ProviderError) as why:
            module.request(entry, session, path, {}, {})
        assert why.value.code == 2 and "allow-list" in str(why.value)


def test_the_test_overrides_are_for_loopback_and_set_together(fake, tmp_path, state):
    proc = run(fake, tmp_path, state, *send_args(tmp_path), env=env_of(fake, tmp_path, state, MAILER_OUTLOOK_API_BASE="https://graph.example.com/v1.0"))
    assert proc.returncode == 2 and "loopback" in proc.stderr
    only = {k: v for k, v in env_of(fake, tmp_path, state).items() if k != "MAILER_OUTLOOK_TOKEN_URL"}
    assert run(fake, tmp_path, state, *send_args(tmp_path), env=only).returncode == 2
    assert fake.requests == []


def test_two_processes_with_one_key_send_once_the_second_finds_the_key_in_use(fake, state, tmp_path):
    import threading
    import time
    original = fake.api

    def slow(entry):
        if entry["method"] == "POST" and entry["path"].endswith("/me/messages"):
            time.sleep(1.5)      # a slow draft creation: the first process holds the key in phase `claimed`
        return original(entry)
    fake.api = slow
    args, env, results = send_args(tmp_path), env_of(fake, tmp_path, state), []

    def one():
        proc = subprocess.run([sys.executable, str(MAILER), *args], env=env, capture_output=True, text=True, timeout=60)
        results.append((proc.returncode, proc.stderr))
    first = threading.Thread(target=one)
    first.start()
    time.sleep(0.8)      # the first one has claimed the key and is inside POST /me/messages
    second = threading.Thread(target=one)
    second.start()
    first.join()
    second.join()
    assert len(fake.sent) == 1 and fake.drafts == {} and fake.deleted == []
    assert sorted(code for code, _ in results) == [0, 1] and any("in progress" in text for _, text in results)
    assert ledger_of(state)[KEY]["status"] == "done"


def test_a_key_in_a_phase_before_the_send_is_taken_again_only_after_it_has_been_still_for_a_while(fake, state, tmp_path):
    import datetime
    would = out(run(fake, tmp_path, state, *send_args(tmp_path, mode="--dry-run")))["would_sha256"]
    folder = state / "mailer-outlook"
    folder.mkdir()
    os.chmod(folder, 0o700)
    now = datetime.datetime.now(datetime.timezone.utc)
    for age, taken in ((5, False), (60, False), (400, True)):
        made = (now - datetime.timedelta(seconds=age)).strftime("%Y-%m-%dT%H:%M:%SZ")
        (folder / "ledger.json").write_text(json.dumps({"keys": {KEY: {"status": "pending", "phase": "drafted", "message_id": MID, "payload_sha256": would,
                                                                      "recipients": 1, "created_at": made}}}))
        os.chmod(folder / "ledger.json", 0o600)
        fake.requests.clear()
        proc = run(fake, tmp_path, state, *send_args(tmp_path))
        if taken:
            assert proc.returncode == 0 and len(fake.sent) == 1
        else:
            assert proc.returncode == 1 and "in progress" in proc.stderr and fake.sent == []
            assert [r["path"] for r in fake.requests] == ["/token", ME], "a busy key makes no draft"


def test_a_draft_that_claims_an_attachment_the_plan_does_not_have_is_not_the_approved_message(fake, tmp_path, state):
    fake.claim_attachments = True
    proc = run(fake, tmp_path, state, *send_args(tmp_path))
    assert proc.returncode == 1 and "exactly the approved attachments" in proc.stderr and fake.sent == [] and len(fake.deleted) == 1 and ledger_of(state) == {}


def test_a_2xx_the_documentation_does_not_give_for_a_send_is_unknown_not_a_refusal(fake, tmp_path, state):
    fake.send_status = 201
    proc = run(fake, tmp_path, state, *send_args(tmp_path))
    assert proc.returncode == 4 and len(fake.sent) == 1 and fake.deleted == [] and ledger_of(state)[KEY]["status"] == "pending"
