"""Offline tests for the files of an e-mail (AT2) in providers/messenger/email-imap.py: which parts of an authenticated message are files, the update that
names them (`ref`, `name`, `size`, `type`), the listen request `fetch` that reads the message again on a fresh connection, admits it again and writes the one
file as `<out>/content`, and what a hostile message cannot do (more parts than the walk visits, a file inside an attached message, a ref outside the closed
pattern, a folder that is a link, a file that already exists, a message that no longer passes). The oracle is this file's literal lists and the bridge's own
checks (runtime/messaging_provider.py, loaded by path). A fake IMAP inbox on loopback; no real mail service, no credential; fictional people and `.example`
addresses.

Run: uv run --python 3.9 --with pytest==9.1.1 pytest providers/messenger/tests/test_email_attachments.py
"""
from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import os
import stat
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from test_messenger_email import GOOD, ID, OWN, OWNER, PASSWORD, Pipe, admit, mail, provider, world  # noqa: F401  (the world fixture is theirs)

REPO = Path(__file__).resolve().parents[3]
PDF = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF\n"
DOCX = b"PK\x03\x04" + bytes(range(256)) * 3
CAP = 1 << 20


def bridge():
    spec = importlib.util.spec_from_file_location("messaging_provider_for_email_attachments", REPO / "runtime" / "messaging_provider.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


mp = bridge()


def b64(data):
    return base64.encodebytes(data).decode("ascii").splitlines()


def file_part(data=PDF, name="Q3 plan.pdf", ctype="application/pdf", disposition="attachment", cid=None, params=None):
    """The lines of one MIME part that carries bytes; `params` replaces the whole disposition parameter (an RFC 2231 name, for one)."""
    if params is not None:
        disp = f"{disposition}; {params}"
    else:
        disp = f'{disposition}; filename="{name}"' if name else disposition
    head = [f"Content-Type: {ctype}", "Content-Transfer-Encoding: base64", f"Content-Disposition: {disp}"]
    if cid:
        head.append(f"Content-ID: <{cid}>")
    return [*head, "", *b64(data)]


def inner_message(*parts):
    """A message as a client attaches it (message/rfc822), holding files of its own."""
    return ["Content-Type: message/rfc822", "Content-Disposition: attachment", "",
            "From: bia@elsewhere.example", f"To: {OWN}", "Subject: older plan", "MIME-Version: 1.0", 'Content-Type: multipart/mixed; boundary="B2"', "",
            "--B2", "Content-Type: text/plain; charset=utf-8", "", "the old words", *[line for part in parts for line in ("--B2", *part)], "--B2--"]


def mime(parts=(), text="Here is the plan.", sender=OWNER, auth=GOOD, subject="Plan for Q3", text_head="Content-Type: text/plain; charset=utf-8"):
    """A multipart/mixed message as the receiving server stores it: its own Authentication-Results first, then what the sender wrote. `text` None writes
    no text part."""
    head = [] if auth is None else [f"Authentication-Results: {auth}"]
    head += ["Received: from mail.office.example by mx.office.example; Sat, 17 Oct 2026 09:00:00 +0000", f"From: {sender}", f"To: {OWN}", f"Subject: {subject}",
             "Date: Sat, 17 Oct 2026 08:59:00 +0000", "Message-ID: <inbound-7@office.example>", "MIME-Version: 1.0", 'Content-Type: multipart/mixed; boundary="B1"']
    body = [] if text is None else ["--B1", text_head, "", text]
    for part in parts:
        body += ["--B1", *part]
    body.append("--B1--")
    return ("\r\n".join([*head, "", *body]) + "\r\n").encode("utf-8")


def inspect(data, ref_base="1000:7", sent=()):
    return provider.inspect_message(data, OWN, ID, lambda chat: set(sent), mail, ref_base=ref_base)


def listed(data, ref_base="1000:7"):
    update, why = inspect(data, ref_base)
    assert why is None, why
    return update


# --- which parts are files, and the update that names them ---------------------------------------------------------------------------


def test_a_message_with_a_pdf_is_an_update_whose_attachments_name_the_file_its_exact_size_and_a_ref_of_the_message():
    update = listed(mime([file_part()]))
    assert update["attachments"] == [{"ref": "1000:7:1", "name": "Q3 plan.pdf", "size": len(PDF), "type": "application/pdf"}]
    assert update["text"] == "Here is the plan." and update["sender"] == update["chat"] == OWNER and "forwarded" not in update


def test_a_message_with_only_a_file_is_an_update_with_text_null_and_without_a_ref_base_it_stays_empty():
    update = listed(mime([file_part(DOCX, "Zurich notes.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")], text=None))
    assert update["text"] is None and update["attachments"][0]["size"] == len(DOCX) and update["attachments"][0]["name"] == "Zurich notes.docx"
    assert inspect(mime([file_part()], text=None), ref_base=None) == (None, "empty")
    plain, why = inspect(mime([file_part()]), ref_base=None)
    assert why is None and "attachments" not in plain and plain["text"] == "Here is the plan."


def test_an_inline_image_with_a_content_id_is_no_file_and_an_inline_pdf_with_a_name_is_one():
    data = mime([file_part(b"\x89PNG\r\n\x1a\n" + bytes(40), "logo.png", "image/png", disposition="inline", cid="logo@office.example"),
                 file_part(PDF, "Inline plan.pdf", disposition="inline"),
                 file_part(PDF, "Tagged plan.pdf", disposition="attachment", cid="tag@office.example"),
                 file_part(bytes(40), None, "image/png", disposition="inline")])
    update = listed(data)
    assert [(f["ref"], f["name"]) for f in update["attachments"]] == [("1000:7:1", "Inline plan.pdf"), ("1000:7:2", "Tagged plan.pdf")]


def test_the_body_part_is_never_a_file_even_when_it_carries_a_name():
    update = listed(mime([file_part()], text_head='Content-Type: text/plain; charset=utf-8; name="notes.txt"'))
    assert [f["name"] for f in update["attachments"]] == ["Q3 plan.pdf"] and update["text"] == "Here is the plan."


def test_a_file_inside_an_attached_message_is_never_listed_and_the_update_is_forwarded():
    update = listed(mime([inner_message(file_part(PDF, "Inner.pdf")), file_part(PDF, "Beside.pdf")]))
    assert update["forwarded"] is True and [(f["ref"], f["name"]) for f in update["attachments"]] == [("1000:7:1", "Beside.pdf")]
    update = listed(mime([inner_message(file_part(PDF, "Inner.pdf"))]))
    assert update["forwarded"] is True and "attachments" not in update


def test_a_forward_by_subject_lists_no_file_and_reads_no_body(monkeypatch):
    def refuse(data):
        raise AssertionError("the body of a forward by subject is not read")
    monkeypatch.setattr(provider, "text_and_forward_in_child", refuse)
    update = listed(mime([file_part()], subject="Fwd: plan"))
    assert update == {"sender": OWNER, "chat": OWNER, "private": True, "text": None, "action": None, "action_ref": None, "reply_to": None, "forwarded": True}


def test_at_most_ten_files_are_listed_in_order():
    update = listed(mime([file_part(PDF, f"File {n:02d}.pdf") for n in range(1, 13)]))
    assert [(f["ref"], f["name"]) for f in update["attachments"]] == [(f"1000:7:{n}", f"File {n:02d}.pdf") for n in range(1, 11)]


def test_no_more_than_the_first_two_hundred_parts_are_visited_so_a_file_after_them_is_never_listed():
    filler = [["Content-Type: text/plain; charset=utf-8", "Content-Disposition: inline", "", "x"] for _ in range(250)]
    assert provider.PARTS_MAX == 200 and provider.FILES_MAX == 10
    assert "attachments" not in listed(mime([*filler, file_part()]))
    assert listed(mime([*filler[:100], file_part()]))["attachments"][0]["ref"] == "1000:7:1"


def test_a_name_with_control_and_invisible_characters_is_cleaned_and_an_rfc_2231_name_is_decoded():
    update = listed(mime([file_part(params="filename*=utf-8''Zurich%20plan.pdf"),
                          file_part(params="filename*=utf-8''a%01b%C2%85c%EF%B8%8Fd.pdf"),
                          file_part(params="filename*=utf-8''%01%EF%B8%8F"),
                          file_part(params="filename*=utf-8''" + "n" * 3000)]))
    names = [f["name"] for f in update["attachments"]]
    assert names[:3] == ["Zurich plan.pdf", "abcd.pdf", None] and len(names[3]) == provider.FILE_NAME_MAX


def test_a_part_with_no_name_that_is_an_attachment_is_a_file_with_name_null():
    update = listed(mime([file_part(PDF, None)]))
    assert update["attachments"] == [{"ref": "1000:7:1", "name": None, "size": len(PDF), "type": "application/pdf"}]


def test_the_size_is_that_of_the_decoded_bytes_and_a_type_is_the_parts_own():
    update = listed(mime([file_part(DOCX, "Zurich notes.docx", "application/octet-stream")]))
    assert update["attachments"][0]["size"] == len(DOCX) and update["attachments"][0]["type"] == "application/octet-stream"


def test_a_message_that_fails_a_check_before_the_text_lists_nothing_with_or_without_a_file():
    assert inspect(mime([file_part()], auth=None)) == (None, "unauthenticated")
    assert inspect(mime([file_part()], sender="Team: owner@office.example;")) in ((None, "sender"), (None, "unparsable"))


def test_the_update_and_the_capabilities_pass_the_bridges_own_checks():
    update = listed(mime([file_part()]))
    valid = mp.valid_update(update)
    assert valid is not None and valid["attachments"] == update["attachments"] and valid["text"] == "Here is the plan."
    only = mp.valid_update(listed(mime([file_part()], text=None)))
    assert only is not None and only["text"] is None and len(only["attachments"]) == 1
    caps = provider.CAPABILITIES
    for key, kind in mp.CAPABILITY_KEYS.items():
        assert type(caps.get(key)) is kind, key
    for key, kind in mp.OPTIONAL_KEYS.items():
        assert key not in caps or type(caps[key]) is kind, key
    assert caps["attachments"] is True and caps["max_attachment_bytes"] == 1048576 == provider.MAX_SIZE      # a literal, which the generated table reads
    assert "gone" in mp.ANSWER_KINDS and len(update["attachments"]) <= mp.ATTACHMENTS_MAX


def test_add_and_discard_are_commands_alone_on_the_first_line():
    assert "/add" in provider.COMMANDS_ALONE and "/discard" in provider.COMMANDS_ALONE
    assert provider.command_only("/add 3\nSent from my phone") == "/add 3"
    assert provider.command_only("\n\n/discard 3\nThanks,\nA.") == "/discard 3"
    update, why = admit(mime([], text="/add 3\n\nSent from my phone"))
    assert why is None and update["text"] == "/add 3"


# --- the child that reads one part ---------------------------------------------------------------------------------------------------


def test_the_part_the_fetch_serves_is_the_one_the_update_numbered():
    data = mime([file_part(PDF, "One.pdf"), file_part(DOCX, "Two.docx", "application/octet-stream")])
    assert provider.part_in_child(data, 1) == PDF and provider.part_in_child(data, 2) == DOCX
    with pytest.raises(provider.ProviderError) as e:
        provider.part_in_child(data, 3)
    assert e.value.kind == "failed" and "could not be read" in str(e.value)


@pytest.mark.parametrize("n", ["0", "11", "-1", "x", "1.5", "01a", ""])
def test_the_part_verb_takes_one_whole_number_from_one_to_ten_and_nothing_else(n):
    done = subprocess.run([sys.executable, "-I", str(Path(provider.__file__)), "message-part", n], input=mime([file_part()]), capture_output=True, timeout=20)
    assert done.returncode != 0 and done.stdout == b""


def test_the_text_verb_writes_one_json_line_and_a_message_that_is_not_that_shape_is_unparsable(monkeypatch):
    done = subprocess.run([sys.executable, "-I", str(Path(provider.__file__)), "message-text"], input=mime([file_part()]), capture_output=True, timeout=20)
    shape = json.loads(done.stdout)
    assert done.returncode == 0 and set(shape) == {"text", "forwarded", "files"} and shape["files"][0]["part"] == 1
    assert provider.text_and_forward_in_child(mime([file_part()]))[0] == "Here is the plan."

    class Done:
        returncode, stdout = 0, b'{"text": "x", "forwarded": false}'
    monkeypatch.setattr(provider.subprocess, "run", lambda *a, **k: Done)
    update, why = inspect(mime([file_part()]))
    assert update is None and why == "unparsable"


# --- the fetch --------------------------------------------------------------------------------------------------------------------------


def ready(world):
    pipe = Pipe(world)
    pipe.wait(lambda x: x.get("event") == "ready")
    return pipe


def new_update(pipe, world, data):
    """Put a message in the mailbox and return (its uid, the update the provider emitted for it)."""
    before = len(pipe.events("update"))
    uid = world["imap"].add(data)
    pipe.wait(lambda x: x.get("event") == "update" and len(pipe.events("update")) > before)
    return uid, pipe.events("update")[before]["update"]


def out_folder(world, name="out"):
    folder = world["tmp"] / name
    folder.mkdir(mode=0o700)
    return folder


def fetch(pipe, rid, ref, out, max_bytes=CAP, **over):
    request = {"id": rid, "op": "fetch", "ref": ref, "out": str(out), "max_bytes": max_bytes, **over}
    pipe.request(request)
    return pipe.wait(lambda x: x.get("id") == rid)[0]


def test_a_fetch_request_writes_the_file_as_content_with_its_sha256_and_changes_nothing_in_the_mailbox(world):
    pipe = ready(world)
    uid, update = new_update(pipe, world, mime([file_part()]))
    [item] = update["attachments"]
    assert item["ref"] == f"1000:{uid}:1" and item["size"] == len(PDF)
    out = out_folder(world)
    answer = fetch(pipe, 5, item["ref"], out)
    assert answer == {"id": 5, "ok": True, "bytes": len(PDF), "sha256": hashlib.sha256(PDF).hexdigest()}
    assert sorted(os.listdir(out)) == ["content"] and (out / "content").read_bytes() == PDF
    assert stat.S_IMODE(os.stat(out / "content").st_mode) == 0o600
    assert pipe.end() == 0
    verbs = set(world["imap"].verbs())
    assert verbs <= set(provider.ALLOWED_IMAP), verbs
    assert not verbs & {"SELECT", "STORE", "COPY", "MOVE", "EXPUNGE", "CLOSE", "APPEND", "DELETE", "CREATE", "RENAME", "SUBSCRIBE", "IDLE"}
    fetches = [c for c in world["imap"].commands if c.startswith("UID FETCH")]
    assert fetches and all(c.endswith("(BODY.PEEK[])") or c.endswith("(RFC822.SIZE)") for c in fetches), fetches
    assert world["imap"].connections == 2, "the fetch used a connection of its own, besides the mailbox thread's"


def test_a_fetch_serves_the_part_it_names_and_a_second_file_is_its_own_ref(world):
    pipe = ready(world)
    uid, update = new_update(pipe, world, mime([file_part(PDF, "One.pdf"), file_part(DOCX, "Two.docx", "application/octet-stream")]))
    assert [i["ref"] for i in update["attachments"]] == [f"1000:{uid}:1", f"1000:{uid}:2"]
    out = out_folder(world)
    answer = fetch(pipe, 6, f"1000:{uid}:2", out)
    assert answer["ok"] is True and (out / "content").read_bytes() == DOCX and answer["sha256"] == hashlib.sha256(DOCX).hexdigest()
    assert pipe.end() == 0


def test_a_fetch_over_max_bytes_answers_usage_and_leaves_no_file(world):
    pipe = ready(world)
    uid, update = new_update(pipe, world, mime([file_part()]))
    out = out_folder(world)
    answer = fetch(pipe, 7, update["attachments"][0]["ref"], out, max_bytes=len(PDF) - 1)
    assert answer["ok"] is False and answer["kind"] == "usage" and f"{len(PDF)} bytes" in answer["reason"]
    assert os.listdir(out) == []
    answer = fetch(pipe, 8, update["attachments"][0]["ref"], out, max_bytes=len(PDF))
    assert answer["ok"] is True and (out / "content").read_bytes() == PDF
    assert pipe.end() == 0


def test_a_fetch_under_another_uidvalidity_or_of_a_missing_uid_answers_gone(world):
    pipe = ready(world)
    uid, update = new_update(pipe, world, mime([file_part()]))
    out = out_folder(world)
    for rid, ref in ((9, f"999:{uid}:1"), (10, f"1000:{uid + 50}:1")):
        answer = fetch(pipe, rid, ref, out)
        assert answer["ok"] is False and answer["kind"] == "gone" and "no longer has this message" in answer["reason"], answer
    assert os.listdir(out) == [] and pipe.end() == 0


@pytest.mark.parametrize("ref", ["../x", "1000:7:0", "1000:7:11", "imap://x.example/1", "1000:07:1", "1000:7", "1000:7:1:1", "1000:7:1\n", " 1000:7:1",
                                 "0:7:1", "10000000000:7:1", "1000:7:+1", "1000:7:-1", "", "1000:7:1\x00", 7, None, ["1000:7:1"]])
def test_a_ref_outside_the_closed_pattern_is_refused_before_any_connection(world, ref):
    pipe = ready(world)
    out = out_folder(world)
    before = world["imap"].connections
    answer = fetch(pipe, 11, ref, out)
    assert answer["ok"] is False and answer["kind"] == "usage" and "ref is" in answer["reason"]
    assert world["imap"].connections == before and os.listdir(out) == []
    assert pipe.end() == 0


@pytest.mark.parametrize("over,why", [({"out": ""}, "out is"), ({"out": None}, "out is"), ({"out": 3}, "out is"), ({"max_bytes": 0}, "max_bytes"),
                                      ({"max_bytes": True}, "max_bytes"), ({"max_bytes": "5"}, "max_bytes"), ({"max_bytes": -4}, "max_bytes"),
                                      ({"max_bytes": 1.5}, "max_bytes")])
def test_an_out_or_a_cap_that_is_not_what_the_protocol_says_is_refused_before_any_connection(world, over, why):
    pipe = ready(world)
    before = world["imap"].connections
    request = {"id": 12, "op": "fetch", "ref": "1000:7:1", "out": str(out_folder(world)), "max_bytes": CAP, **over}
    pipe.request(request)
    answer = pipe.wait(lambda x: x.get("id") == 12)[0]
    assert answer["ok"] is False and answer["kind"] == "usage" and why in answer["reason"] and world["imap"].connections == before
    assert pipe.end() == 0


def test_a_fetch_with_no_integer_id_is_dropped_with_one_log_line_and_the_provider_goes_on(world, capfd):
    pipe = ready(world)
    for rid in (True, "3", None):
        pipe.request({"id": rid, "op": "fetch", "ref": "1000:7:1", "out": "/x", "max_bytes": 5})
    answer = fetch(pipe, 13, "bad", "/x")
    assert answer["kind"] == "usage" and pipe.end() == 0
    assert capfd.readouterr().err.count("dropped a request with no integer id") == 3


def test_a_fetch_into_a_folder_that_is_a_link_or_already_holds_content_writes_nothing(world):
    pipe = ready(world)
    uid, update = new_update(pipe, world, mime([file_part()]))
    ref = update["attachments"][0]["ref"]
    real = out_folder(world, "real")
    link = world["tmp"] / "link"
    link.symlink_to(real, target_is_directory=True)
    answer = fetch(pipe, 14, ref, link)
    assert answer["ok"] is False and answer["kind"] == "usage" and os.listdir(real) == []
    held = out_folder(world, "held")
    (held / "content").write_bytes(b"already here")
    answer = fetch(pipe, 15, ref, held)
    assert answer["ok"] is False and answer["kind"] == "failed" and (held / "content").read_bytes() == b"already here"
    assert fetch(pipe, 16, ref, world["tmp"] / "no-such-folder")["kind"] == "usage"
    assert pipe.end() == 0


def test_a_fetch_of_a_message_that_no_longer_passes_the_checks_is_refused(world, capfd):
    pipe = ready(world)
    uid, update = new_update(pipe, world, mime([file_part()]))
    ref = update["attachments"][0]["ref"]
    world["imap"].messages[uid] = mime([file_part()], auth=None)       # the same uid, a message the server did not vouch for
    out = out_folder(world)
    answer = fetch(pipe, 17, ref, out)
    assert answer["ok"] is False and answer["kind"] == "failed" and "no longer passes the channel's checks" in answer["reason"] and os.listdir(out) == []
    world["imap"].messages[uid] = mime([file_part()], sender="intruder@elsewhere.example")
    assert fetch(pipe, 18, ref, out)["kind"] == "failed"
    world["imap"].messages[uid] = mime([file_part()])       # a message that holds one file: the second ordinal is none of its files
    assert fetch(pipe, 19, ref[:-1] + "2", out)["kind"] == "failed" and os.listdir(out) == []
    assert fetch(pipe, 20, ref, out)["ok"] is True
    assert pipe.end() == 0
    err = capfd.readouterr().err
    assert "office.example" not in err and "1000:" not in err and "Plan for Q3" not in err and "Q3 plan" not in err and PASSWORD not in err


def test_a_message_over_a_mebibyte_is_never_read_for_a_fetch(world):
    pipe = ready(world)
    uid, update = new_update(pipe, world, mime([file_part()]))
    world["imap"].sizes[uid] = provider.MAX_SIZE + 1
    out = out_folder(world)
    answer = fetch(pipe, 21, update["attachments"][0]["ref"], out)
    assert answer["ok"] is False and answer["kind"] == "failed" and "larger than the channel reads" in answer["reason"] and os.listdir(out) == []
    assert world["imap"].commands.count(f"UID FETCH {uid} (BODY.PEEK[])") == 1, "only the mailbox thread's own read of it"
    assert pipe.end() == 0


def test_an_unexpected_failure_of_a_fetch_is_a_failed_answer_with_no_detail_and_the_provider_goes_on(world, monkeypatch, capfd):
    def boom(self, *args):
        raise RuntimeError("SECRETWORDS in a traceback")
    monkeypatch.setattr(provider.Listener, "fetch_file", boom)
    pipe = ready(world)
    answer = fetch(pipe, 22, "1000:7:1", out_folder(world))
    assert answer["ok"] is False and answer["kind"] == "failed" and answer["reason"] == "the fetch failed unexpectedly" and pipe.end() == 0
    err = capfd.readouterr().err
    assert "a fetch failed unexpectedly (RuntimeError)" in err and "SECRETWORDS" not in err


def test_a_lost_connection_during_a_fetch_is_a_failed_answer_and_never_ends_the_mailbox_thread(world):
    pipe = ready(world)
    uid, update = new_update(pipe, world, mime([file_part()]))
    ref = update["attachments"][0]["ref"]
    world["imap"].login_answer = "NO [UNAVAILABLE] too many connections"
    answer = fetch(pipe, 23, ref, out_folder(world))
    assert answer["ok"] is False and answer["kind"] == "failed" and PASSWORD not in json.dumps(pipe.lines)
    world["imap"].login_answer = None
    assert fetch(pipe, 24, ref, out_folder(world, "again"))["ok"] is True
    assert pipe.end() == 0


def test_a_send_answers_while_a_fetch_waits(world, monkeypatch):
    gate = threading.Event()
    real = provider.part_in_child

    def held(data, n):
        assert gate.wait(15)
        return real(data, n)
    monkeypatch.setattr(provider, "part_in_child", held)
    pipe = ready(world)
    uid, update = new_update(pipe, world, mime([file_part()]))
    out = out_folder(world)
    pipe.request({"id": 30, "op": "fetch", "ref": update["attachments"][0]["ref"], "out": str(out), "max_bytes": CAP})
    pipe.request({"id": 31, "op": "send", "chat": OWNER, "message": {"text": "Plan received.", "actions": [], "link": None, "document": None}})
    sent = pipe.wait(lambda x: x.get("id") == 31)[0]
    assert sent["ok"] is True and not [x for x in pipe.lines if x.get("id") == 30], "the fetch is still waiting"
    gate.set()
    answer = pipe.wait(lambda x: x.get("id") == 30)[0]
    assert answer["ok"] is True and (out / "content").read_bytes() == PDF
    assert pipe.end() == 0


def test_the_other_ops_are_still_refused_and_a_fetch_is_not_a_send(world):
    pipe = ready(world)
    pipe.request({"id": 40, "op": "delete", "chat": OWNER})
    answer = pipe.wait(lambda x: x.get("id") == 40)[0]
    assert answer["ok"] is False and answer["kind"] == "usage" and "send" in answer["reason"]
    assert pipe.end() == 0
