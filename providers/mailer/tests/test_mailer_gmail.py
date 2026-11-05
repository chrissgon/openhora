"""Tests of the Gmail mailer (providers/mailer/gmail.py; package W2; limits L42, L55 to L60 as they apply to a mailer of the person's own account). Against the
stand-in service (fake_gmail_send.py) on 127.0.0.1: no Google host is reached and no real credential exists. Every write path records each request (method, path,
query, body) and the tests assert the exact list: the token, the profile, and one POST of the message. A dry run reads no credential and opens no connection, and its
hash is the hash of what the confirmed run sends (the message without its Date header). The From address must be the address of the account token (the record and the
service's own profile). A lost answer is exit 4 and the same key finds the message among the account's sent mail by its Message-ID; a key that is done is not sent
again. The request function refuses any method or path outside ALLOWED before it opens a connection.

Run: uv run --python 3.11 --with pytest==9.1.1 pytest providers/mailer/tests/test_mailer_gmail.py
"""
from __future__ import annotations

import base64
import email
import email.policy
import hashlib
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
import fake_gmail_send as fgs  # noqa: E402

MAILER = REPO / "providers" / "mailer" / "gmail.py"
_spec = importlib.util.spec_from_file_location("email_helpers_under_gmail_test", REPO / "providers" / "_email.py")
email_helpers = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(email_helpers)
KEY = "send-0123456789abcdef0123456789abcdef"
MID = "<oh.0123456789abcdef0123456789abcdef@example.com>"
SEND_PATH = "/gmail/v1/users/me/messages/send"
SUBJECT = "Haircut on Monday"
BODY = "Hello Ana,\n\nSee you on Monday at one.\n\nPat\n"


@pytest.fixture
def fake():
    f = fgs.FakeGmail()
    yield f
    f.close()


@pytest.fixture
def state(tmp_path):
    folder = tmp_path / "state"
    folder.mkdir()
    os.chmod(folder, 0o700)
    return folder


def env_of(fake, tmp_path, state, record=None, **extra):
    kept = {k: v for k, v in os.environ.items() if not k.startswith(("GMAIL_", "GOOGLE_", "MAILER_", "WRITER_", "INTEGRATION_", "OPENHORA_"))}
    kept.update({"HOME": str(tmp_path / "home"), "OPENHORA_STATE_DIR": str(state), "GOOGLE_ACCOUNT_TOKEN": record or fake.record_json(), **fake.env()})
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
        for secret in fgs.SECRETS:
            assert secret not in stream and secret[:16] not in stream, args
    return proc


def out(proc):
    assert proc.returncode == 0, (proc.returncode, proc.stderr)
    return json.loads(proc.stdout)


def send_args(tmp_path, *, mode="--confirmed", key=KEY, sender=fgs.ACCOUNT, to=("ana@client.example",), cc=(), extra=(), subject=SUBJECT, body=BODY, mid=MID):
    args = ["send", "--from", sender, "--to", *to]
    if cc:
        args += ["--cc", *cc]
    args += ["--subject-file", put(tmp_path, "subject.txt", subject), "--body-file", put(tmp_path, "body.txt", body), "--message-id", mid,
             "--idempotency-key", key, *extra, mode]
    return args


def sent_message(fake, index=-1):
    return email.message_from_bytes(fake.sent[index]["raw"], policy=email.policy.default)


def ledger_of(state):
    path = state / "mailer-gmail" / "ledger.json"
    return json.loads(path.read_text(encoding="utf-8"))["keys"] if path.exists() else {}


# --- a send ---------------------------------------------------------------------------------------------------------------------------------------


def test_a_send_is_the_token_the_profile_and_exactly_one_post_of_the_message(fake, tmp_path, state):
    done = out(run(fake, tmp_path, state, *send_args(tmp_path, cc=("lee@client.example",))))
    assert done["sent"] is True and done["replayed"] is False and done["message_id"] == MID and done["recipients"] == 2 and done["idempotency_key"] == KEY
    assert [(r["method"], r["path"]) for r in fake.requests] == [("POST", "/token"), ("GET", f"{fgs.PREFIX}/profile"), ("POST", SEND_PATH)]
    [_, _, (method, path, query, body)] = [(r["method"], r["path"], r["query"], r["body"]) for r in fake.requests]
    assert (method, path) == ("POST", SEND_PATH) and query == {"fields": "id,threadId"} and set(body) == {"raw"}
    assert fake.unexpected() == [] and all(r["bearer"] for r in fake.requests if r["path"] != "/token")
    message = sent_message(fake)
    assert message["From"] == fgs.ACCOUNT and message["To"] == "ana@client.example" and message["Cc"] == "lee@client.example"
    assert message["Subject"] == SUBJECT and message["Message-ID"] == MID and message["Bcc"] is None and message["Date"]
    assert message.get_body(("plain",)).get_content().replace("\r\n", "\n") == BODY
    assert ledger_of(state)[KEY]["status"] == "done"


def test_the_dry_run_reads_no_credential_opens_no_connection_and_its_hash_is_that_of_the_message_the_confirmed_run_sends(fake, tmp_path, state):
    bare = {k: v for k, v in os.environ.items() if not k.startswith(("GMAIL_", "GOOGLE_", "MAILER_", "WRITER_", "INTEGRATION_", "OPENHORA_"))}
    bare.update({"HOME": str(tmp_path / "home"), "OPENHORA_STATE_DIR": str(state)})      # no token, no override: a dry run needs neither
    shown = out(run(fake, tmp_path, state, *send_args(tmp_path, mode="--dry-run"), env=bare))
    assert fake.requests == [] and shown["dry_run"] is True and shown["ledger"] == "absent" and not (state / "mailer-gmail").exists()
    would = shown["would"]
    assert would["envelope"] == {"from": fgs.ACCOUNT, "to": ["ana@client.example"]} and would["headers"]["Message-ID"] == MID and would["headers"]["In-Reply-To"] is None
    assert would["body"] == BODY and would["body_sha256"] == hashlib.sha256(BODY.encode()).hexdigest() and would["service"] == "gmail"
    [request] = would["requests"]
    assert request["method"] == "POST" and request["path"] == SEND_PATH and "threadId" not in request["body"] and request["body"]["date_header"] == "added at send"
    again = out(run(fake, tmp_path, state, *send_args(tmp_path, mode="--dry-run"), env=bare))
    assert again["would_sha256"] == shown["would_sha256"], "the same flags, the same hash"
    out(run(fake, tmp_path, state, *send_args(tmp_path)))
    assert email_helpers.inspect_message(fake.sent[0]["raw"]) == would["wire"], "the message sent reads back as the preview says; only its Date was added"
    assert sent_message(fake)["Date"] and would["headers"]["Subject"] == SUBJECT
    other = out(run(fake, tmp_path, state, *send_args(tmp_path, mode="--dry-run", body=BODY + "More.\n"), env=bare))
    assert other["would_sha256"] != shown["would_sha256"], "another text, another hash"
    assert out(run(fake, tmp_path, state, *send_args(tmp_path, mode="--dry-run"), env=bare))["ledger"] == "done"


def test_a_reply_carries_the_thread_the_in_reply_to_and_the_references_of_the_message_it_answers(fake, tmp_path, state):
    original = "<CA+original1@mail.client.example>"
    extra = ["--in-reply-to", original, "--thread-id", "18e9a1b2c3d4e5f6"]
    done = out(run(fake, tmp_path, state, *send_args(tmp_path, extra=extra, subject="Re: Haircut")))
    assert done["sent"] is True
    [(_, _, _, body)] = [c for c in fake.calls() if c[0] == "POST"]
    assert body["threadId"] == "18e9a1b2c3d4e5f6" and fake.sent[0]["threadId"] == "18e9a1b2c3d4e5f6"
    message = sent_message(fake)
    assert message["In-Reply-To"] == original and message["References"] == original and message["Subject"] == "Re: Haircut"
    chain = ["--in-reply-to", "<c@x.example>", "--references", "<a@x.example>", "<b@x.example>", "<c@x.example>"]
    out(run(fake, tmp_path, state, *send_args(tmp_path, key="send-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", extra=chain)))
    assert sent_message(fake)["References"] == "<a@x.example> <b@x.example> <c@x.example>"
    for wrong in (["--references", "<a@x.example>"], ["--thread-id", "abc"], ["--in-reply-to", "<c@x.example>", "--references", "<a@x.example>"],
                  ["--in-reply-to", "<c@x.example>", "--reply-id", "m1"]):      # the last is Outlook's flag
        assert run(fake, tmp_path, state, *send_args(tmp_path, key="send-cccccccccccccccccccccccccccccccc", extra=wrong)).returncode == 2


def test_the_from_must_be_the_address_of_the_account_token_the_record_and_the_service_both_say_it(fake, tmp_path, state):
    proc = run(fake, tmp_path, state, *send_args(tmp_path, sender="someone.else@example.com"))
    assert proc.returncode == 3 and "not the address of the Google account token" in proc.stderr
    assert [r["path"] for r in fake.requests if r["method"] == "POST" and r["path"] != "/token"] == [] and fake.sent == [] and ledger_of(state) == {}
    fake.requests.clear()
    fake.profile_address = "pat.new@example.com"       # the record says pat@example.com; the service says the token belongs to another address
    proc = run(fake, tmp_path, state, *send_args(tmp_path))
    assert proc.returncode == 3 and "another address" in proc.stderr and fake.sent == [] and ledger_of(state) == {}
    assert [(r["method"], r["path"]) for r in fake.requests] == [("POST", "/token"), ("GET", f"{fgs.PREFIX}/profile")]
    fake.profile_address = fgs.ACCOUNT
    proc = run(fake, tmp_path, state, *send_args(tmp_path), record=fake.record_json(account=None))
    assert proc.returncode == 3 and "names no address" in proc.stderr and fake.sent == []


def test_a_token_that_lacks_a_scope_or_carries_another_is_refused_before_anything_is_sent(fake, tmp_path, state):
    fake.refresh_scope = " ".join(fgs.PLATFORM_SET[:3])
    proc = run(fake, tmp_path, state, *send_args(tmp_path))
    assert proc.returncode == 3 and "lacks" in proc.stderr and fake.sent == [] and [r["method"] for r in fake.requests] == ["POST"]
    fake.refresh_scope = " ".join(fgs.PLATFORM_SET) + " https://mail.google.com/"
    proc = run(fake, tmp_path, state, *send_args(tmp_path))
    assert proc.returncode == 3 and "carries" in proc.stderr and fake.sent == []
    assert run(fake, tmp_path, state, *send_args(tmp_path), record="not json").returncode == 3


def test_a_bcc_a_second_recipient_form_and_the_other_flags_the_class_refuses_are_exit_2(fake, tmp_path, state):
    bcc = send_args(tmp_path) + ["--bcc", "hidden@client.example"]
    assert run(fake, tmp_path, state, *bcc).returncode == 2, "a Bcc is refused in this version: the API reads the recipients from the headers"
    assert "Bcc is refused" in run(fake, tmp_path, state, *bcc).stderr
    for wrong in (dict(to=("Ana <ana@client.example>",)), dict(to=("ana@client.example", "ANA@client.example")), dict(to=("ana@client.example",), subject="=?utf-8?q?x?="),
                  dict(to=tuple(f"p{i}@client.example" for i in range(21)))):
        assert run(fake, tmp_path, state, *send_args(tmp_path, **wrong)).returncode == 2, wrong
    assert fake.requests == [] and fake.sent == []


def test_an_attachment_is_sent_with_its_name_and_a_total_over_the_cap_is_refused_before_a_credential_is_read(fake, tmp_path, state):
    pdf = put(tmp_path, "cv.pdf", b"%PDF-1.4 a small cv")
    out(run(fake, tmp_path, state, *send_args(tmp_path, extra=["--attach", f"{pdf}=CV 2026.pdf"])))
    message = sent_message(fake)
    [attached] = list(message.iter_attachments())
    assert attached.get_filename() == "CV 2026.pdf" and attached.get_payload(decode=True) == b"%PDF-1.4 a small cv"
    big = put(tmp_path, "big.pdf", b"x" * (3 * 1024 * 1024 + 1))
    fake.requests.clear()
    proc = run(fake, tmp_path, state, *send_args(tmp_path, key="send-dddddddddddddddddddddddddddddddd", extra=["--attach", f"{big}=big.pdf"]))
    assert proc.returncode == 2 and "over" in proc.stderr and fake.requests == []


# --- the key: once, and a lost answer ---------------------------------------------------------------------------------------------------------------


def test_a_done_key_is_not_sent_again_and_a_key_used_for_another_message_is_a_usage_error(fake, tmp_path, state):
    out(run(fake, tmp_path, state, *send_args(tmp_path)))
    again = out(run(fake, tmp_path, state, *send_args(tmp_path)))
    assert again["replayed"] is True and again["sent"] is True and len(fake.sent) == 1
    assert [r["method"] for r in fake.requests].count("POST") == 3, "two token requests and the one send: the second run sent no message"
    proc = run(fake, tmp_path, state, *send_args(tmp_path, body=BODY + "Something else.\n"))
    assert proc.returncode == 2 and "another e-mail" in proc.stderr and len(fake.sent) == 1


def test_a_lost_answer_is_exit_4_the_key_stays_pending_and_the_same_key_finds_the_message_by_its_message_id(fake, tmp_path, state):
    fake.lose_answer_once = True
    proc = run(fake, tmp_path, state, *send_args(tmp_path))
    assert proc.returncode == 4 and len(fake.sent) == 1 and ledger_of(state)[KEY]["status"] == "pending"
    assert out(run(fake, tmp_path, state, *send_args(tmp_path, mode="--dry-run")))["ledger"] == "pending"
    fake.requests.clear()
    again = out(run(fake, tmp_path, state, *send_args(tmp_path)))
    assert again["replayed"] is True and len(fake.sent) == 1, "found by its Message-ID: nothing is sent again"
    assert [(r["method"], r["path"]) for r in fake.requests] == [("POST", "/token"), ("GET", f"{fgs.PREFIX}/profile"), ("GET", f"{fgs.PREFIX}/messages"),
                                                                 ("GET", f"{fgs.PREFIX}/messages/{fake.sent[0]['id']}")]
    search = fake.requests[2]["query"]
    assert search["q"] == "rfc822msgid:oh.0123456789abcdef0123456789abcdef@example.com in:sent"
    assert fake.requests[3]["query"]["metadataHeaders"] == "Message-ID" and ledger_of(state)[KEY]["status"] == "done"


def test_when_the_service_gave_the_message_another_message_id_the_lookup_finds_nothing_and_only_the_person_settles_the_key(fake, tmp_path, state):
    fake.rewrite_message_id = True
    fake.lose_answer_once = True
    assert run(fake, tmp_path, state, *send_args(tmp_path)).returncode == 4
    proc = run(fake, tmp_path, state, *send_args(tmp_path))
    assert proc.returncode == 4 and "not among the account's sent mail" in proc.stderr and len(fake.sent) == 1, "identity is the Message-ID, never size or time"
    assert run(fake, tmp_path, state, "resolve", "--idempotency-key", KEY, "--sent", "--dry-run").returncode == 0
    assert ledger_of(state)[KEY]["status"] == "pending", "a dry run changes nothing"
    assert out(run(fake, tmp_path, state, "resolve", "--idempotency-key", KEY, "--sent", "--confirmed"))["recorded"] == "sent"
    assert out(run(fake, tmp_path, state, *send_args(tmp_path)))["replayed"] is True and len(fake.sent) == 1


def test_a_key_settled_as_not_sent_may_be_sent_again(fake, tmp_path, state):
    fake.rewrite_message_id = True
    fake.lose_answer_once = True
    assert run(fake, tmp_path, state, *send_args(tmp_path)).returncode == 4
    assert out(run(fake, tmp_path, state, "resolve", "--idempotency-key", KEY, "--not-sent", "--confirmed"))["recorded"] == "not sent"
    assert ledger_of(state) == {}
    fake.rewrite_message_id = False
    assert out(run(fake, tmp_path, state, *send_args(tmp_path)))["replayed"] is False and len(fake.sent) == 2
    assert run(fake, tmp_path, state, "resolve", "--idempotency-key", KEY, "--sent", "--confirmed").returncode == 2, "a done key is not pending"


@pytest.mark.parametrize("status", [500, 503])
def test_a_server_error_on_the_send_is_exit_4_and_keeps_the_key(fake, tmp_path, state, status):
    fake.refuse_next = (status, "backendError")
    proc = run(fake, tmp_path, state, *send_args(tmp_path))
    assert proc.returncode == 4 and "may or may not have been sent" in proc.stderr and ledger_of(state)[KEY]["status"] == "pending"


@pytest.mark.parametrize("status,code", [(400, 1), (403, 1), (429, 1), (404, 1)])
def test_a_refusal_by_the_service_is_exit_1_nothing_was_sent_and_the_key_is_free(fake, tmp_path, state, status, code):
    fake.refuse_next = (status, "invalidArgument" if status != 429 else "rateLimitExceeded")
    proc = run(fake, tmp_path, state, *send_args(tmp_path))
    assert proc.returncode == code and fake.sent == [] and ledger_of(state) == {}
    if status == 429:
        assert "slow down" in proc.stderr and "Retry-After: 30" in proc.stderr
    assert out(run(fake, tmp_path, state, *send_args(tmp_path)))["replayed"] is False and len(fake.sent) == 1, "the same key may be tried again"


def test_a_redirect_on_the_send_is_not_followed_and_is_exit_4(fake, tmp_path, state):
    fake.redirect_next = True
    proc = run(fake, tmp_path, state, *send_args(tmp_path))
    assert proc.returncode == 4 and "redirect" in proc.stderr and fake.sent == [] and ledger_of(state)[KEY]["status"] == "pending"


def test_a_lookup_that_cannot_be_made_leaves_the_key_pending_and_is_exit_4(fake, tmp_path, state):
    fake.lose_answer_once = True
    assert run(fake, tmp_path, state, *send_args(tmp_path)).returncode == 4
    fake.fail_search_next = 500
    proc = run(fake, tmp_path, state, *send_args(tmp_path))
    assert proc.returncode == 4 and "cannot be looked up now" in proc.stderr and len(fake.sent) == 1 and ledger_of(state)[KEY]["status"] == "pending"


def test_the_lookup_verb_and_the_check_verb(fake, tmp_path, state):
    out(run(fake, tmp_path, state, *send_args(tmp_path)))
    found = out(run(fake, tmp_path, state, "lookup", "--message-id", MID))
    assert found == {"found": True, "count": 1, "message_id": MID}
    none = out(run(fake, tmp_path, state, "lookup", "--message-id", "<oh.ffffffffffffffffffffffffffffffff@example.com>"))
    assert none["found"] is False and none["count"] == 0
    assert run(fake, tmp_path, state, "lookup", "--message-id", "not an id").returncode == 2
    fake.requests.clear()
    checked = out(run(fake, tmp_path, state, "--check"))
    assert checked["ok"] is True and checked["from"] == fgs.ACCOUNT and "scope" in checked
    assert [(r["method"], r["path"]) for r in fake.requests] == [("POST", "/token"), ("GET", f"{fgs.PREFIX}/profile")]


# --- the allow-list ----------------------------------------------------------------------------------------------------------------------------------


def load_module():
    spec = importlib.util.spec_from_file_location("mailer_gmail_under_test", MAILER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_request_function_refuses_any_method_or_path_outside_the_allow_list_before_it_opens_a_connection():
    module = load_module()
    assert module.ALLOWED == (("GET", r"/gmail/v1/users/me/profile"), ("GET", r"/gmail/v1/users/me/messages"), ("GET", r"/gmail/v1/users/me/messages/[^/]+"),
                              ("POST", r"/gmail/v1/users/me/messages/send"))
    for entry, path in ((("DELETE", r"/gmail/v1/users/me/messages/[^/]+"), "/gmail/v1/users/me/messages/abc"),
                        (("POST", r"/gmail/v1/users/me/messages/send"), "/gmail/v1/users/me/messages/send/../trash"),
                        (("POST", r"/gmail/v1/users/me/drafts"), "/gmail/v1/users/me/drafts"),
                        (("GET", r"/gmail/v1/users/me/profile"), "/gmail/v1/users/me/profile/x"),
                        (("POST", r"/gmail/v1/users/me/messages/[^/]+/trash"), "/gmail/v1/users/me/messages/abc/trash")):
        with pytest.raises(module.ProviderError) as why:
            module.request(entry, "http://127.0.0.1:1", "token", path, {})
        assert why.value.code == 2 and "allow-list" in str(why.value)
    source = MAILER.read_text(encoding="utf-8")
    assert "DELETE" not in source.replace("no delete", "") and "batchDelete" not in source and "/trash" not in source.replace("no trash", "")


def test_the_test_overrides_are_for_loopback_and_set_together(fake, tmp_path, state):
    proc = run(fake, tmp_path, state, *send_args(tmp_path), env=env_of(fake, tmp_path, state, MAILER_GMAIL_API_BASE="https://gmail.example.com"))
    assert proc.returncode == 2 and "loopback" in proc.stderr
    only = {k: v for k, v in env_of(fake, tmp_path, state).items() if k != "MAILER_GMAIL_TOKEN_URL"}
    assert run(fake, tmp_path, state, *send_args(tmp_path), env=only).returncode == 2
    assert fake.requests == []


def test_the_preview_shows_the_exact_query_the_send_carries(fake, tmp_path, state):
    bare = {k: v for k, v in os.environ.items() if not k.startswith(("GMAIL_", "GOOGLE_", "MAILER_", "OPENHORA_"))}
    bare.update({"HOME": str(tmp_path / "home"), "OPENHORA_STATE_DIR": str(state)})
    [request] = out(run(fake, tmp_path, state, *send_args(tmp_path, mode="--dry-run"), env=bare))["would"]["requests"]
    out(run(fake, tmp_path, state, *send_args(tmp_path)))
    [(method, path, query, _)] = [c for c in fake.calls() if c[0] == "POST"]
    assert (request["method"], request["path"], request["query"]) == (method, path, query) == ("POST", SEND_PATH, {"fields": "id,threadId"})


def test_a_2xx_the_documentation_does_not_give_for_a_send_is_unknown_not_a_refusal(fake, tmp_path, state):
    fake.send_status = 201
    proc = run(fake, tmp_path, state, *send_args(tmp_path))
    assert proc.returncode == 4 and len(fake.sent) == 1 and ledger_of(state)[KEY]["status"] == "pending"
