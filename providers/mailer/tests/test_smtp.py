"""Tests of providers/mailer/smtp.py (class sender:email) against a fake SMTP server and a fake IMAP server on loopback
(providers/mailer/tests/fake_mail.py): no real mail service, no credential, `.example` addresses, fictional people. They hold the
rules of the class: nothing is sent without --confirmed; the dry run opens no connection and reads no secret; the recipients are exactly the
flags; one refused recipient sends nothing and releases the key; a lost answer after DATA keeps the key pending and the next send looks in the
Sent folder first; a header is never built from a caller's text; no password before TLS.

Run: uv run --python 3.9 --with pytest==9.1.1 pytest providers/mailer/tests
"""
from __future__ import annotations

import email
import email.policy
import hashlib
import importlib.util
import json
import os
import stat
from pathlib import Path

import pytest

import fake_mail

HERE = Path(__file__).resolve()
PROVIDER = HERE.parents[1] / "smtp.py"
SPEC = importlib.util.spec_from_file_location("mailer_smtp_under_test", PROVIDER)
smtp = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(smtp)

PASSWORD = "app-password-x"  # security-scan: allow secret-assignment -- a made-up password for a fake server on loopback; no real account has it
FROM = "outbox@office.example"
MID = "<oh.0123456789abcdef0123456789abcdef@office.example>"
KEY = "send-0123456789abcdef0123456789abcdef"


@pytest.fixture
def world(tmp_path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir()
    os.chmod(state, 0o700)
    monkeypatch.setenv("OPENHORA_STATE_DIR", str(state))
    monkeypatch.setenv("OPENHORA_MAIL_TEST_PLAIN", "1")
    monkeypatch.setenv("MAILER_SMTP_PASSWORD", PASSWORD)
    monkeypatch.setenv("MAILER_SMTP_TIMEOUT", "5")
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    server, imap = fake_mail.FakeSmtp(PASSWORD), fake_mail.FakeImap(PASSWORD)
    work = tmp_path / "work"
    work.mkdir()
    yield {"smtp": server, "imap": imap, "tmp": tmp_path, "work": work, "state": state / "mailer-smtp"}
    server.stop()
    imap.stop()


def run(capsys, *argv):
    code = smtp.main(list(argv))
    out, err = capsys.readouterr()
    return code, out, err


def set_up(world, capsys, imap=True, **extra):
    argv = ["setup", "--from", FROM, "--smtp-host", "127.0.0.1", "--smtp-port", str(world["smtp"].port), "--smtp-security", "plain"]
    if imap:
        argv += ["--imap-host", "127.0.0.1", "--imap-port", str(world["imap"].port), "--sent-folder", "Sent"]
    code, out, err = run(capsys, *argv)
    assert code == 0, err
    return json.loads(out)


def write(world, name, data):
    path = world["work"] / name
    path.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
    return str(path)


def send_args(world, mode="--confirmed", to=("ana@client.example",), cc=(), bcc=(), subject="Your invoice for October", body="Hello Ana,\n\nThe invoice is attached.\n",
              attach=(), key=KEY, message_id=MID, sender=FROM, extra=()):
    argv = ["send", "--from", sender, "--to", *to]
    if cc:
        argv += ["--cc", *cc]
    if bcc:
        argv += ["--bcc", *bcc]
    argv += ["--subject-file", write(world, "subject.txt", subject), "--body-file", write(world, "body.txt", body)]
    for spec in attach:
        argv += ["--attach", spec]
    argv += ["--message-id", message_id, "--idempotency-key", key, mode, *extra]
    return argv


def ledger(world):
    path = world["state"] / "ledger.json"
    return json.loads(path.read_text(encoding="utf-8"))["keys"] if path.exists() else {}


def message_of(raw):
    return email.message_from_bytes(raw, policy=email.policy.default)


# --- the dry run ---------------------------------------------------------------------------------------------------------------------


def test_the_dry_run_prints_the_whole_preview_and_opens_no_connection_reads_no_secret_and_writes_nothing(world, capsys, monkeypatch):
    monkeypatch.setattr(smtp, "secret_resolver", lambda: pytest.fail("the dry run read a credential"))
    monkeypatch.delenv("MAILER_SMTP_PASSWORD")
    pdf = write(world, "invoice.pdf", b"%PDF-1.4 fake")
    code, out, err = run(capsys, *send_args(world, "--dry-run", to=("ana@client.example", "bo@client.example"), cc=("cy@client.example",),
                                            bcc=("dee@client.example",), attach=(f"{pdf}=Invoice October.pdf",)))
    assert code == 0, err
    shown = json.loads(out)
    would = shown["would"]
    assert shown["dry_run"] is True and shown["ledger"] == "absent"
    assert would["envelope"] == {"from": FROM, "to": ["ana@client.example", "bo@client.example", "cy@client.example", "dee@client.example"]}
    assert would["headers"]["To"] == "ana@client.example, bo@client.example" and would["headers"]["Cc"] == "cy@client.example"
    assert "Bcc" not in would["headers"] and "dee@client.example" not in json.dumps(would["headers"])
    assert would["headers"]["Subject"] == "Your invoice for October" and would["headers"]["Message-ID"] == MID
    assert would["body"] == "Hello Ana,\n\nThe invoice is attached.\n" and would["body_sha256"] == hashlib.sha256(would["body"].encode()).hexdigest()
    assert would["attachments"] == [{"name": "Invoice October.pdf", "media_type": "application/pdf", "bytes": 13,
                                     "sha256": hashlib.sha256(b"%PDF-1.4 fake").hexdigest()}]
    assert len(shown["would_sha256"]) == 64
    assert world["smtp"].connections == 0 and world["imap"].connections == 0
    assert not world["state"].exists(), "a dry run makes no folder and no ledger"
    assert PASSWORD not in out + err


def test_the_preview_hash_is_the_same_for_the_same_content_and_changes_with_any_recipient(world, capsys):
    one = json.loads(run(capsys, *send_args(world, "--dry-run"))[1])["would_sha256"]
    again = json.loads(run(capsys, *send_args(world, "--dry-run"))[1])["would_sha256"]
    other = json.loads(run(capsys, *send_args(world, "--dry-run", bcc=("dee@client.example",)))[1])["would_sha256"]
    assert one == again and one != other


# --- a send --------------------------------------------------------------------------------------------------------------------------


def test_a_confirmed_send_goes_to_exactly_the_recipients_with_no_bcc_header_and_records_the_key_done(world, capsys):
    set_up(world, capsys)
    code, out, err = run(capsys, *send_args(world, to=("ana@client.example",), cc=("Cy@Client.Example",), bcc=("dee@client.example",)))
    assert code == 0, err
    done = json.loads(out)
    assert done["sent"] is True and done["replayed"] is False and done["message_id"] == MID and done["recipients"] == 3
    [taken] = world["smtp"].messages
    assert taken["from"] == FROM and taken["to"] == ["ana@client.example", "Cy@client.example", "dee@client.example"]
    parsed = message_of(taken["data"])
    assert parsed["To"] == "ana@client.example" and parsed["Cc"] == "Cy@client.example" and parsed["Message-ID"] == MID
    assert parsed["Subject"] == "Your invoice for October" and parsed["Date"] and parsed["Bcc"] is None
    assert b"dee@client.example" not in taken["data"], "the Bcc address is in the envelope and nowhere in the message"
    assert parsed.get_body().get_content().replace("\r\n", "\n") == "Hello Ana,\n\nThe invoice is attached.\n"
    assert ledger(world)[KEY]["status"] == "done" and ledger(world)[KEY]["message_id"] == MID
    assert PASSWORD not in out + err
    commands = world["smtp"].verbs()
    assert commands.index("AUTH") < commands.index("MAIL") < commands.index("DATA")


def test_a_non_ascii_subject_and_body_and_an_attachment_travel_intact(world, capsys):
    set_up(world, capsys)
    pdf = write(world, "plan.pdf", b"%PDF-1.4 plan bytes")
    body = "Gr\u00fc\u00dfe, Zo\u00eb!\n\nThe plan for October is attached.\n"
    code, out, err = run(capsys, *send_args(world, subject="Plan f\u00fcr Oktober \u2014 review", body=body, attach=(f"{pdf}=Plan October.pdf",)))
    assert code == 0, err
    parsed = message_of(world["smtp"].messages[0]["data"])
    assert parsed["Subject"] == "Plan f\u00fcr Oktober \u2014 review"
    assert parsed.get_body(("plain",)).get_content().replace("\r\n", "\n") == body
    [attached] = list(parsed.iter_attachments())
    assert attached.get_filename() == "Plan October.pdf" and attached.get_content() == b"%PDF-1.4 plan bytes"
    assert attached.get_content_type() == "application/pdf"


def test_nothing_is_sent_without_confirmed(world, capsys):
    set_up(world, capsys)
    code, out, err = run(capsys, "send", "--from", FROM, "--to", "ana@client.example", "--subject-file", write(world, "s.txt", "x"),
                         "--body-file", write(world, "b.txt", "y"), "--message-id", MID, "--idempotency-key", KEY)
    assert code == 2 and world["smtp"].connections == 0 and ledger(world) == {}


def test_a_key_that_is_done_replays_without_connecting_and_a_key_for_another_message_is_refused(world, capsys):
    set_up(world, capsys)
    assert run(capsys, *send_args(world))[0] == 0
    connections = world["smtp"].connections
    code, out, err = run(capsys, *send_args(world))
    assert code == 0 and json.loads(out)["replayed"] is True and len(world["smtp"].messages) == 1
    assert world["smtp"].connections == connections, "the second send did not even connect"
    code, out, err = run(capsys, *send_args(world, body="Another text.\n"))
    assert code == 2 and "another e-mail" in err and len(world["smtp"].messages) == 1


# --- all or nothing ------------------------------------------------------------------------------------------------------------------


def test_one_refused_recipient_sends_nothing_names_the_address_and_releases_the_key(world, capsys):
    set_up(world, capsys)
    world["smtp"].refuse.add("bo@client.example")
    code, out, err = run(capsys, *send_args(world, to=("ana@client.example", "bo@client.example")))
    assert code == 1 and "bo@client.example" in err and "nothing was sent" in err
    verbs = world["smtp"].verbs()
    assert "RSET" in verbs and "DATA" not in verbs and world["smtp"].messages == []
    assert ledger(world) == {}, "the key is released: the same e-mail may be tried again"
    world["smtp"].refuse.clear()
    assert run(capsys, *send_args(world, to=("ana@client.example", "bo@client.example")))[0] == 0
    assert len(world["smtp"].messages) == 1


def test_a_message_the_server_refuses_at_data_or_after_it_is_nothing_sent_and_the_key_is_released(world, capsys):
    set_up(world, capsys)
    world["smtp"].refuse_data = True
    code, out, err = run(capsys, *send_args(world))
    assert code == 1 and "nothing was sent" in err and ledger(world) == {}
    world["smtp"].refuse_data, world["smtp"].reject_message = False, True
    code, out, err = run(capsys, *send_args(world))
    assert code == 1 and "nothing was sent" in err and ledger(world) == {}


# --- a lost answer ----------------------------------------------------------------------------------------------------------------


def test_a_dropped_answer_after_data_keeps_the_key_pending_and_the_next_send_looks_in_the_sent_folder_first(world, capsys):
    set_up(world, capsys)
    world["smtp"].drop_after_data = True
    code, out, err = run(capsys, *send_args(world))
    assert code == 4 and "may or may not have been sent" in err
    assert ledger(world)[KEY]["status"] == "pending"
    world["smtp"].drop_after_data = False
    connections = world["smtp"].connections
    # not in the Sent folder: blocked, and no second SMTP connection is made
    code, out, err = run(capsys, *send_args(world))
    assert code == 4 and "resolve" in err and "--not-sent" in err and "second copy" in err
    assert world["smtp"].connections == connections and len(world["smtp"].messages) == 1
    assert ledger(world)[KEY]["status"] == "pending"
    # found in the Sent folder: it was sent, replayed, and nothing is sent again
    world["imap"].message_ids["Sent"] = {MID: 7}
    code, out, err = run(capsys, *send_args(world))
    assert code == 0 and json.loads(out)["replayed"] is True
    assert world["smtp"].connections == connections and len(world["smtp"].messages) == 1
    assert ledger(world)[KEY]["status"] == "done"


def test_an_error_nobody_foresaw_keeps_the_exit_codes_true(world, capsys, monkeypatch):
    set_up(world, capsys)
    real = smtp.connect_smtp
    monkeypatch.setattr(smtp, "connect_smtp", lambda *a: (_ for _ in ()).throw(RuntimeError("boom")))
    code, out, err = run(capsys, *send_args(world))
    assert code == 1 and "nothing was sent" in err and ledger(world) == {}, "before a server was reached: nothing sent, the key is free"
    monkeypatch.setattr(smtp, "connect_smtp", real)
    monkeypatch.setattr(smtp.smtplib.SMTP, "data", lambda self, msg: (_ for _ in ()).throw(RuntimeError("boom")))
    code, out, err = run(capsys, *send_args(world))
    assert code == 4 and ledger(world)[KEY]["status"] == "pending", "after the message was handed over: not known"


def test_a_message_over_the_size_a_server_takes_is_refused_before_anything_is_recorded_or_opened(world, capsys, monkeypatch):
    set_up(world, capsys)
    monkeypatch.setattr(smtp, "MESSAGE_MAX", 300)
    for mode in ("--dry-run", "--confirmed"):
        code, out, err = run(capsys, *send_args(world, mode, body="x" * 400))
        assert code == 2 and "most servers take" in err, mode
    assert world["smtp"].connections == 0 and ledger(world) == {}


def test_resolve_settles_a_pending_key_either_way_and_only_with_confirmed(world, capsys):
    set_up(world, capsys)
    world["smtp"].drop_after_data = True
    run(capsys, *send_args(world))
    world["smtp"].drop_after_data = False
    code, out, err = run(capsys, "resolve", "--idempotency-key", KEY, "--not-sent", "--dry-run")
    assert code == 0 and json.loads(out)["would"]["record"] == "not sent" and ledger(world)[KEY]["status"] == "pending"
    assert run(capsys, "resolve", "--idempotency-key", KEY, "--not-sent")[0] == 2        # neither --dry-run nor --confirmed
    assert run(capsys, "resolve", "--idempotency-key", KEY, "--not-sent", "--confirmed")[0] == 0
    assert ledger(world) == {}
    assert run(capsys, *send_args(world))[0] == 0 and len(world["smtp"].messages) == 2     # the one dropped and the new one
    assert run(capsys, "resolve", "--idempotency-key", KEY, "--sent", "--confirmed")[0] == 2    # no longer pending
    world["smtp"].drop_after_data = True
    other = "send-ffffffffffffffffffffffffffffffff"
    run(capsys, *send_args(world, key=other, message_id="<oh.ffffffffffffffffffffffffffffffff@office.example>"))
    assert run(capsys, "resolve", "--idempotency-key", other, "--sent", "--confirmed")[0] == 0
    assert ledger(world)[other]["status"] == "done"
    world["smtp"].drop_after_data = False
    count = len(world["smtp"].messages)
    code, out, err = run(capsys, *send_args(world, key=other, message_id="<oh.ffffffffffffffffffffffffffffffff@office.example>"))
    assert code == 0 and json.loads(out)["replayed"] is True and len(world["smtp"].messages) == count


def test_lookup_is_read_only_and_says_whether_the_message_id_is_in_the_sent_folder(world, capsys):
    set_up(world, capsys)
    world["imap"].message_ids["Sent"] = {MID: 3}
    code, out, err = run(capsys, "lookup", "--message-id", MID)
    assert code == 0 and json.loads(out) == {"found": True, "count": 1, "folder": "Sent", "message_id": MID}
    other = "<oh.aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa@office.example>"
    assert json.loads(run(capsys, "lookup", "--message-id", other)[1])["found"] is False
    verbs = world["imap"].verbs()
    assert set(verbs) <= {"LOGIN", "EXAMINE", "UID", "LOGOUT", "CAPABILITY", "NOOP"}, verbs
    assert not set(verbs) & {"SELECT", "STORE", "COPY", "EXPUNGE", "APPEND", "DELETE", "MOVE", "CREATE"}
    assert all(c.startswith("UID SEARCH") for c in world["imap"].commands if c.startswith("UID"))
    assert run(capsys, "lookup", "--message-id", "not-an-id")[0] == 2


# --- what a caller's text can never do ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("address", ["Eve <eve@client.example>", "eve@client.example, mal@client.example", "eve@client.example>",
                                     "ev e@client.example", "eve@@client.example", "eve@client.example\r\nBcc: mal@client.example",
                                     "eve@client.example\nBcc: mal@client.example", "(c)eve@client.example", "\"eve\"@client.example",
                                     "eve@client", "eve@.example", "eve@client..example", "", " eve@client.example", "eve@client.example;mal@x.example",
                                     "a" * 65 + "@client.example"])
def test_an_address_with_a_display_name_comment_break_or_second_at_is_refused_and_nothing_is_sent(world, capsys, address):
    set_up(world, capsys)
    for flag in ("to", "cc", "bcc"):
        kwargs = {"to": ("ana@client.example",), "cc": (), "bcc": ()}
        kwargs[flag] = (address,) if flag != "to" else (address,)
        code, out, err = run(capsys, *send_args(world, **kwargs))
        assert code == 2, (flag, address, err)
    assert world["smtp"].connections == 0 and world["smtp"].messages == [] and ledger(world) == {}


def test_a_line_break_in_the_subject_or_a_bad_message_id_is_refused(world, capsys):
    set_up(world, capsys)
    for subject in ("Hello\nBcc: mal@client.example", "Hello\r\nBcc: mal@client.example", "Hello\x00there"):
        code, out, err = run(capsys, *send_args(world, subject=subject))
        assert code == 2, subject
    for bad in ("<id@office.example>", "oh.0123456789abcdef0123456789abcdef@office.example", MID + "\r\nBcc: x@y.example"):
        assert run(capsys, *send_args(world, message_id=bad))[0] == 2, bad
    assert run(capsys, *send_args(world, extra=("--in-reply-to", "<a b@c.example>")))[0] == 2
    assert world["smtp"].connections == 0


def test_more_than_twenty_recipients_or_a_repeated_address_is_refused(world, capsys):
    set_up(world, capsys)
    many = tuple(f"p{i}@client.example" for i in range(21))
    assert run(capsys, *send_args(world, to=many))[0] == 2
    assert run(capsys, *send_args(world, to=many[:10], cc=many[10:15], bcc=many[15:20]))[0] == 0     # exactly 20 is the cap
    assert run(capsys, *send_args(world, key="send-other", message_id="<oh.00000000000000000000000000000001@office.example>",
                                  to=("ana@client.example",), cc=("ANA@client.example",)))[0] == 2
    assert len(world["smtp"].messages) == 1 and world["smtp"].messages[0]["to"] == list(many[:20])


def test_no_address_outside_the_flags_reaches_the_envelope_even_when_the_text_names_one(world, capsys):
    set_up(world, capsys)
    body = "To: mal@client.example\nBcc: mal@client.example\n\nPlease also tell mal@client.example.\n"
    assert run(capsys, *send_args(world, body=body))[0] == 0
    assert world["smtp"].messages[0]["to"] == ["ana@client.example"]
    assert [c.upper() for c in world["smtp"].commands if c.upper().startswith("RCPT")] == ["RCPT TO:<ANA@CLIENT.EXAMPLE>"]


def test_an_attachment_must_be_a_plain_regular_file_with_an_allowed_extension(world, capsys, tmp_path):
    set_up(world, capsys)
    good = write(world, "report.pdf", b"%PDF-1.4")
    script = write(world, "run.sh", "echo hi")
    link = world["work"] / "link.pdf"
    link.symlink_to(good)
    for spec in (f"{script}=run.sh", f"{good}=report.exe", f"{good}=../report.pdf", f"{good}=report", f"{good}=re\nport.pdf", f"{link}=link.pdf",
                 f"{world['work']}=folder.pdf", f"{world['work']}/missing.pdf=missing.pdf", "no-equals-sign"):
        assert run(capsys, *send_args(world, attach=(spec,)))[0] == 2, spec
    assert run(capsys, *send_args(world, attach=(f"{good}=a.pdf", f"{good}=A.PDF")))[0] == 2, "two attachments with one name"
    assert world["smtp"].connections == 0


# --- the account, the secret, the login ------------------------------------------------------------------------------------------------


def test_another_from_address_is_not_configured_and_connects_to_nothing(world, capsys):
    set_up(world, capsys)
    code, out, err = run(capsys, *send_args(world, sender="someone.else@office.example"))
    assert code == 3 and "one outbox account" in err and world["smtp"].connections == 0 and ledger(world) == {}


def test_no_settings_or_no_password_is_not_configured_and_leaves_no_pending_key(world, capsys, monkeypatch):
    code, out, err = run(capsys, *send_args(world))
    assert code == 3 and "setup" in err
    set_up(world, capsys)
    monkeypatch.delenv("MAILER_SMTP_PASSWORD")
    monkeypatch.setenv("OPENHORA_CREDENTIALS_DIR", str(world["tmp"] / "no-credentials"))
    monkeypatch.setattr(smtp, "load_password", lambda: (_ for _ in ()).throw(smtp.ProviderError("no usable MAILER_SMTP_PASSWORD", 3)))
    code, out, err = run(capsys, *send_args(world))
    assert code == 3 and "MAILER_SMTP_PASSWORD" in err and ledger(world) == {} and world["smtp"].connections == 0


def test_a_login_the_server_refuses_is_not_configured_and_releases_the_key(world, capsys, monkeypatch):
    set_up(world, capsys)
    monkeypatch.setenv("MAILER_SMTP_PASSWORD", "a-wrong-password")
    code, out, err = run(capsys, *send_args(world))
    assert code == 3 and "refused the login" in err and ledger(world) == {} and world["smtp"].messages == []
    assert "a-wrong-password" not in out + err


def test_the_password_is_never_printed_not_even_by_the_check_or_an_error(world, capsys):
    set_up(world, capsys)
    code, out, err = run(capsys, "--check")
    assert code == 0 and json.loads(out) == {"ok": True, "from": FROM, "smtp": True, "imap": True}
    assert PASSWORD not in out + err
    world["imap"].refuse_login = True
    code, out, err = run(capsys, "--check")
    assert code == 3 and PASSWORD not in out + err


# --- TLS: no password before it, and plain only for a test on loopback ----------------------------------------------------------------------


def test_a_server_that_does_not_offer_starttls_gets_no_password(world, capsys):
    run(capsys, "setup", "--from", FROM, "--smtp-host", "127.0.0.1", "--smtp-port", str(world["smtp"].port), "--smtp-security", "starttls")
    code, out, err = run(capsys, *send_args(world))
    assert code == 3 and "STARTTLS" in err
    assert "AUTH" not in world["smtp"].verbs() and "MAIL" not in world["smtp"].verbs() and world["smtp"].logins == []
    assert ledger(world) == {}


def test_a_certificate_that_is_not_trusted_gets_no_password(world, capsys, tmp_path):
    certificate = fake_mail.make_certificate(str(tmp_path))
    if certificate is None:
        pytest.skip("the openssl command is not available")
    with fake_mail.FakeSmtp(PASSWORD, offer_starttls=True, certificate=certificate) as secure:
        run(capsys, "setup", "--from", FROM, "--smtp-host", "127.0.0.1", "--smtp-port", str(secure.port), "--smtp-security", "starttls")
        code, out, err = run(capsys, *send_args(world))
        assert code == 3 and "TLS" in err and secure.logins == [] and "AUTH" not in secure.verbs()
        assert "STARTTLS" in secure.verbs(), "the handshake was tried, and refused by the client"


def test_plain_is_for_a_test_on_loopback_only(world, capsys, monkeypatch):
    argv = ["setup", "--from", FROM, "--smtp-host", "127.0.0.1", "--smtp-port", "2525", "--smtp-security", "plain"]
    monkeypatch.delenv("OPENHORA_MAIL_TEST_PLAIN")
    assert run(capsys, *argv)[0] == 2, "no test variable, no plain"
    monkeypatch.setenv("OPENHORA_MAIL_TEST_PLAIN", "1")
    assert run(capsys, "setup", "--from", FROM, "--smtp-host", "mail.office.example", "--smtp-port", "465")[0] == 2, "the test variable reaches loopback only"
    assert run(capsys, "setup", "--from", FROM, "--smtp-host", "mail.office.example", "--smtp-security", "plain")[0] == 2
    monkeypatch.delenv("OPENHORA_MAIL_TEST_PLAIN")
    assert run(capsys, "setup", "--from", FROM, "--smtp-host", "mail.office.example", "--smtp-port", "2525")[0] == 2, "a port that says nothing about TLS"
    assert run(capsys, "setup", "--from", FROM, "--smtp-host", "mail.office.example", "--smtp-port", "587")[0] == 0
    assert run(capsys, "setup", "--from", FROM, "--smtp-host", "mail.office.example")[0] == 0     # 465 by default
    saved = json.loads((world["state"] / "settings.json").read_text(encoding="utf-8"))
    assert saved["smtp_security"] == "ssl" and saved["smtp_port"] == 465


def test_a_settings_file_edited_to_plain_is_refused_when_used_without_the_test_variable(world, capsys, monkeypatch):
    set_up(world, capsys)
    monkeypatch.delenv("OPENHORA_MAIL_TEST_PLAIN")
    code, out, err = run(capsys, *send_args(world))
    assert code == 2 and "tests only" in err and world["smtp"].connections == 0


# --- the state ---------------------------------------------------------------------------------------------------------------------------


def test_setup_writes_the_settings_privately_and_without_any_secret(world, capsys):
    shown = set_up(world, capsys)
    assert shown["settings"]["from"] == FROM and shown["settings"]["sent_folder"] == "Sent"
    path = world["state"] / "settings.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600 and stat.S_IMODE(world["state"].stat().st_mode) == 0o700
    assert PASSWORD not in path.read_text(encoding="utf-8")
    assert run(capsys, "send", "--from", FROM, "--to", "ana@client.example", "--subject-file", write(world, "s", "s"),
               "--body-file", write(world, "b", "b"), "--message-id", MID, "--idempotency-key", KEY, "--confirmed")[0] == 0
    assert stat.S_IMODE((world["state"] / "ledger.json").stat().st_mode) == 0o600
    assert PASSWORD not in (world["state"] / "ledger.json").read_text(encoding="utf-8")


def test_a_state_folder_open_to_others_is_refused(world, capsys):
    set_up(world, capsys)
    os.chmod(world["state"], 0o755)
    code, out, err = run(capsys, *send_args(world))
    assert code == 3 and "open to other users" in err and world["smtp"].connections == 0


def test_help_names_the_verbs_and_exits_zero(capsys):
    with pytest.raises(SystemExit) as stop:
        smtp.build_parser().parse_args(["--help"])
    assert stop.value.code == 0
    text = capsys.readouterr().out
    for word in ("send", "resolve", "lookup", "setup", "--check", "OPENHORA_MAIL_TEST_PLAIN"):
        assert word in text
    assert smtp.main(["--help"]) == 0


SNEAKY = "=?utf-8?b?" + __import__("base64").b64encode(b"Hi\r\nReply-To: thief@evil.example\r\n\r\nPay to account 999").decode() + "?="


@pytest.mark.parametrize("mode", ["--dry-run", "--confirmed"])
def test_an_encoded_word_in_the_subject_or_an_address_is_refused_because_the_library_would_decode_it(world, capsys, mode):
    set_up(world, capsys)
    for kwargs in ({"subject": SNEAKY}, {"subject": "Invoice =?utf-8?q?ceo?="}, {"to": ("=?utf-8?q?ceo?=@client.example",)},
                   {"bcc": ("=?utf-8?q?ceo?=@client.example",)}, {"extra": ("--in-reply-to", "<=?utf-8?q?x?=@client.example>")}):
        code, out, err = run(capsys, *send_args(world, mode, **kwargs))
        assert code == 2, (kwargs, err)
    assert world["smtp"].connections == 0 and ledger(world) == {}


def test_a_lone_cr_or_a_domain_that_is_not_ascii_is_refused_and_an_xn_domain_is_not(world, capsys):
    set_up(world, capsys)
    assert run(capsys, *send_args(world, body="Pay to account 111\rPay to account 999\n"))[0] == 2
    assert run(capsys, *send_args(world, to=("ana@stra\u00dfe.example",)))[0] == 2
    assert run(capsys, *send_args(world, to=("ana@xn--bcher-kva.example",)))[0] == 0
    assert world["smtp"].messages[0]["to"] == ["ana@xn--bcher-kva.example"]


def test_a_library_that_decodes_more_than_was_approved_is_caught_by_reading_the_built_message_back(world, capsys, monkeypatch):
    set_up(world, capsys)
    mail = smtp.helpers()
    real = mail.build_message

    def tampered(**kwargs):
        msg = real(**kwargs)
        msg["Reply-To"] = "thief@evil.example"      # what a library flaw could add to the wire
        return msg
    monkeypatch.setattr(mail, "build_message", tampered)
    for mode in ("--dry-run", "--confirmed"):
        code, out, err = run(capsys, *send_args(world, mode))
        assert code == 2 and "header that was not asked for" in err, (mode, err)
    assert world["smtp"].connections == 0 and ledger(world) == {}
    monkeypatch.setattr(mail, "build_message", lambda **kw: real(**{**kw, "body": kw["body"] + "Pay to account 999\n"}))
    code, out, err = run(capsys, *send_args(world))
    assert code == 2 and "not the message approved" in err and world["smtp"].messages == []


def test_the_dry_run_says_what_the_built_message_reads_back_as_and_the_hash_covers_it(world, capsys):
    set_up(world, capsys)
    one = json.loads(run(capsys, *send_args(world, "--dry-run"))[1])
    wire = one["would"]["wire"]
    assert wire["headers"]["Subject"] == "Your invoice for October" and wire["headers"]["To"] == "ana@client.example"
    assert wire["text_sha256"] == hashlib.sha256(b"Hello Ana,\n\nThe invoice is attached.").hexdigest()
    two = json.loads(run(capsys, *send_args(world, "--dry-run", subject="Your invoice for November"))[1])
    assert one["would_sha256"] != two["would_sha256"]
