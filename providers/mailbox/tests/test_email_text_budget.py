"""Tests of the time budget of the HTML-to-text step of the Gmail and Outlook readers (EM5): each HTML body is turned into text by a
short-lived child process (providers/_email_text.py, html_to_text_within) stopped after HTML_TEXT_SECONDS. A body that runs over, or a child
that fails, drops the HTML (text and links) and keeps the message, flagged "html_dropped": true. A body converted in time is unchanged.

Stand-in children (a script that never ends, one that fails, one that answers another shape) prove the cut on every interpreter; the
pathological bodies (`<a` repeated) prove the bound on real input, and hit the budget only where the standard library parser is quadratic.

Run: uv run --with pytest==9.1.1 pytest providers/mailbox/tests/test_email_text_budget.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from email.message import EmailMessage
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
PROVIDERS = HERE.parents[1]
sys.path.insert(0, str(HERE))
import fake_graph_mail  # noqa: E402


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


et = _load("email_text_for_the_budget_tests", PROVIDERS / "_email_text.py")
gmail = _load("gmail_for_the_budget_tests", PROVIDERS / "mailbox" / "gmail.py")
ol = _load("outlook_for_the_budget_tests", PROVIDERS / "mailbox" / "outlook.py")

PATHOLOGICAL_SMALL = "<a" * 50_000     # 100,000 bytes, the readers' text cap
PATHOLOGICAL = "<a" * 200_000          # 400,000 bytes: unbudgeted it takes minutes where the parser is quadratic
SLACK = 3.0                            # seconds over the budget an in-process call may take (the child's start, the kill)
PROCESS_SLACK = 15.0                   # the same for a reader started as a process (interpreter start, imports, the fake service)


def write_child(tmp_path, name, body):
    script = tmp_path / name
    script.write_text(body)
    return script


def never_ending(tmp_path):
    """A child that never ends; it writes its pid to the file named by its first argument. Returns (command, pid file)."""
    script = write_child(tmp_path, "never.py", "import os, sys, time\nopen(sys.argv[1], 'w').write(str(os.getpid()))\nsys.stdin.buffer.read()\ntime.sleep(60)\n")
    pid_file = tmp_path / "never.pid"
    return [sys.executable, "-I", str(script), str(pid_file)], pid_file


def child_printing(tmp_path, name, out="", err="", code=0):
    script = write_child(tmp_path, name, f"import sys\nsys.stdin.buffer.read()\nsys.stdout.write({out!r})\nsys.stderr.write({err!r})\nsys.exit({code})\n")
    return [sys.executable, "-I", str(script)]


def gone(pid_file):
    if not pid_file.exists():
        return True
    try:
        os.kill(int(pid_file.read_text()), 0)
    except ProcessLookupError:
        return True
    return False


def eml(html=None, plain=None, attach=True):
    msg = EmailMessage()
    msg["From"] = "Robin Example <robin@news.example>"
    msg["To"] = "sam@mail.example"
    msg["Subject"] = "Weekly digest"
    msg["Message-ID"] = "<digest-1@news.example>"
    if plain is not None:
        msg.set_content(plain)
        if html is not None:
            msg.add_alternative(html, subtype="html")
    else:
        msg.set_content(html, subtype="html")
    if attach:
        msg.add_attachment(b"%PDF-1.4 fake", maintype="application", subtype="pdf", filename="plan.pdf")
    return msg.as_bytes()


# --- the conversion in a child ---------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("html", [
    '<p>seen</p><p style="display:none">UNSEEN</p><div hidden>UNSEEN</div><p>See <a href="https://x.example/a?i=1">one</a> and '
    '<a href="javascript:alert(1)">bad</a> and <a href="https://y.example/">two</a></p>',
    "<p>Caf\u00e9 and zero\u200bwidth</p>",
    "<p>lone \ud800 surrogate</p>",
    "",
])
def test_the_child_gives_exactly_what_html_to_text_gives(html):
    assert et.html_to_text_within(html) == (*et.html_to_text(html), False)


def test_the_child_command_is_isolated_and_names_this_file():
    command = et._child_command()
    assert command[1] == "-I" and command[-2:] == [str(PROVIDERS / "_email_text.py"), "html-to-text"]
    helped = subprocess.run([sys.executable, "-I", command[-2], "--help"], capture_output=True, text=True, timeout=30)
    assert helped.returncode == 0 and "html-to-text" in helped.stdout
    bare = subprocess.run([sys.executable, "-I", command[-2]], capture_output=True, text=True, timeout=30)
    assert bare.returncode == 2


def test_a_child_over_the_budget_is_stopped_and_the_body_is_dropped(tmp_path, monkeypatch):
    command, pid_file = never_ending(tmp_path)
    monkeypatch.setattr(et, "_child_command", lambda: command)
    started = time.monotonic()
    assert et.html_to_text_within("<p>x</p>", 1.0) == ("", [], True)
    assert time.monotonic() - started < 1.0 + SLACK
    assert gone(pid_file)


@pytest.mark.parametrize("kind", ["exit", "notjson", "text_not_str", "link_not_str"])
def test_a_child_that_fails_or_answers_another_shape_drops_the_body_and_prints_nothing_of_it(tmp_path, monkeypatch, capsys, kind):
    command = {
        "exit": child_printing(tmp_path, "c1.py", err="PRIVATE BODY WORDS", code=3),
        "notjson": child_printing(tmp_path, "c2.py", out="not json"),
        "text_not_str": child_printing(tmp_path, "c3.py", out='{"text": 1, "links": []}'),
        "link_not_str": child_printing(tmp_path, "c4.py", out='{"text": "x", "links": [{"href": 1, "text": "y"}]}'),
    }[kind]
    monkeypatch.setattr(et, "_child_command", lambda: command)
    assert et.html_to_text_within("<p>x</p>") == ("", [], True)
    seen = capsys.readouterr()
    assert "PRIVATE BODY WORDS" not in seen.out + seen.err and seen.out + seen.err == ""


def test_the_budget_works_from_worker_threads_and_in_parallel(tmp_path, monkeypatch):
    command, _ = never_ending(tmp_path)
    monkeypatch.setattr(et, "_child_command", lambda: command)
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: et.html_to_text_within("<p>x</p>", 1.0), range(4)))
    assert results == [("", [], True)] * 4
    assert time.monotonic() - started < 3.5


@pytest.mark.parametrize("html", [PATHOLOGICAL_SMALL, "</" * 50_000])
def test_a_pathological_body_costs_at_most_the_budget(html):
    started = time.monotonic()
    text, links, dropped = et.html_to_text_within(html, 1.0)
    assert time.monotonic() - started < 1.0 + SLACK
    assert isinstance(text, str) and isinstance(links, list)
    if dropped:
        assert (text, links) == ("", [])


# --- the Gmail reader ------------------------------------------------------------------------------------------------------------


def stall(module, tmp_path, monkeypatch):
    command, pid_file = never_ending(tmp_path)
    monkeypatch.setattr(module._text, "_child_command", lambda: command)
    monkeypatch.setattr(module, "HTML_TEXT_SECONDS", 1.0)
    return pid_file


def test_gmail_keeps_the_message_and_flags_a_dropped_html_part(tmp_path, monkeypatch, capsys):
    stall(gmail, tmp_path, monkeypatch)
    started = time.monotonic()
    m = gmail.normalize(eml(html='<p>Hi <a href="https://x.example/">there</a></p>'), source="eml")
    assert time.monotonic() - started < 1.0 + SLACK
    assert (m["text"], m["links"], m["html_dropped"], m["truncated"]) == ("", [], True, False)
    assert m["subject"] == "Weekly digest" and m["from_address"] == "robin@news.example" and m["external_content"] is True
    assert [a["name"] for a in m["attachments"]] == ["plan.pdf"]
    err = capsys.readouterr().err
    assert "html_dropped" in err and "the message" in err and "Weekly digest" not in err


def test_gmail_keeps_the_plain_part_when_only_the_html_part_is_dropped(tmp_path, monkeypatch):
    stall(gmail, tmp_path, monkeypatch)
    m = gmail.normalize(eml(html="<p>Hi</p>", plain="Plan for Tuesday"), source="eml")
    assert (m["text"], m["links"], m["html_dropped"]) == ("Plan for Tuesday", [], True)


def test_gmail_own_words_on_a_dropped_html_part(tmp_path, monkeypatch):
    stall(gmail, tmp_path, monkeypatch)
    m = gmail.normalize(eml(html="<p>Hi</p>"), source="eml", own_words=True)
    assert (m["text"], m["own_words_cut"], m["html_dropped"]) == ("", 0, True)


def test_gmail_names_the_message_id_in_the_note(tmp_path, monkeypatch, capsys):
    stall(gmail, tmp_path, monkeypatch)
    gmail.normalize(eml(html="<p>Hi</p>"), source="gmail", message_id="18c0ffee")
    assert "message 18c0ffee" in capsys.readouterr().err


def test_a_message_converted_in_time_has_no_html_dropped_key():
    g = gmail.normalize(eml(html='<p>Hello <a href="https://x.example/a">link</a></p>'), source="eml")
    assert g["text"] == "Hello link" and g["links"] == [{"href": "https://x.example/a", "text": "link"}] and "html_dropped" not in g
    item = {"id": "m1", "receivedDateTime": "2026-10-17T07:12:03Z", "from": {"emailAddress": {"name": "Ana Lima", "address": "ana@clinic.example"}},
            "toRecipients": [], "subject": "Plan", "body": {"contentType": "html", "content": '<p>Hello <a href="https://x.example/a">link</a></p>'},
            "hasAttachments": False, "isRead": False}
    o = ol.normalize(item)
    assert o["text"] == "Hello link" and o["links"] == g["links"] and "html_dropped" not in o


# --- the Outlook reader ----------------------------------------------------------------------------------------------------------

ITEM = {"id": "m9", "receivedDateTime": "2026-10-17T07:12:03Z", "from": {"emailAddress": {"name": "Ana Lima", "address": "ana@clinic.example"}},
        "toRecipients": [], "subject": "Plan", "body": {"contentType": "html", "content": "<p>x</p>"}, "hasAttachments": False, "isRead": False}


def test_outlook_keeps_the_message_and_flags_a_dropped_html_body(tmp_path, monkeypatch, capsys):
    stall(ol, tmp_path, monkeypatch)
    started = time.monotonic()
    m = ol.normalize(ITEM)
    assert time.monotonic() - started < 1.0 + SLACK
    assert (m["text"], m["links"], m["html_dropped"], m["subject"]) == ("", [], True, "Plan")
    err = capsys.readouterr().err
    assert "message m9" in err and "html_dropped" in err and "Plan" not in err


def test_outlook_starts_no_child_for_a_text_body(monkeypatch):
    def refuse():
        raise AssertionError("no child for a text body")
    monkeypatch.setattr(ol._text, "_child_command", refuse)
    m = ol.normalize({**ITEM, "body": {"contentType": "text", "content": "Order 77 shipped."}})
    assert m["text"] == "Order 77 shipped." and "html_dropped" not in m


# --- the readers as a person runs them -------------------------------------------------------------------------------------------


def test_gmail_read_eml_of_a_pathological_body_costs_at_most_the_budget(tmp_path):
    path = tmp_path / "digest.eml"
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = "news@digest.example", "sam@mail.example", "Weekly digest"
    msg.set_content(PATHOLOGICAL, subtype="html")
    path.write_bytes(msg.as_bytes())
    started = time.monotonic()
    done = subprocess.run([sys.executable, str(PROVIDERS / "mailbox" / "gmail.py"), "read-eml", "--file", str(path)], capture_output=True, text=True,
                          timeout=120, env={"PATH": os.environ["PATH"], "HOME": str(tmp_path)})
    assert time.monotonic() - started < gmail.HTML_TEXT_SECONDS + PROCESS_SLACK
    assert done.returncode == 0, done.stderr
    m = json.loads(done.stdout)
    assert m["subject"] == "Weekly digest" and m["external_content"] is True
    if "html_dropped" in m:
        assert m["html_dropped"] is True and m["text"] == "" and m["links"] == [] and "html_dropped" in done.stderr
    print("python", sys.version.split()[0], "gmail dropped:", "html_dropped" in m)


def test_outlook_search_with_a_pathological_body_costs_at_most_the_budget():
    fake = fake_graph_mail.FakeGraphMail()
    try:
        fake.add("slow1", "2026-10-17T07:12:03Z", "Digest", "news@digest.example", "Weekly digest", html=PATHOLOGICAL)
        fake.add("ok1", "2026-10-16T18:30:00Z", "Shop", "shop@shop.example", "Your order", html="<p>Your order has shipped</p>")
        base = {k: v for k, v in os.environ.items() if not k.startswith("OUTLOOK_") and not k.startswith("MAILBOX_")}
        started = time.monotonic()
        done = subprocess.run([sys.executable, str(PROVIDERS / "mailbox" / "outlook.py"), "search", "--query", "in:inbox", "--since",
                               "2026-10-01T00:00:00Z", "--jobs", "4"], capture_output=True, text=True, timeout=120, env={**base, **fake.env()})
        elapsed = time.monotonic() - started
    finally:
        fake.close()
    assert elapsed < 3.0 + PROCESS_SLACK
    assert done.returncode == 0, done.stderr
    by_id = {m["id"]: m for m in json.loads(done.stdout)["messages"]}
    assert set(by_id) == {"slow1", "ok1"}
    assert by_id["ok1"]["text"] == "Your order has shipped" and "html_dropped" not in by_id["ok1"]
    if "html_dropped" in by_id["slow1"]:
        assert by_id["slow1"]["text"] == "" and by_id["slow1"]["links"] == []
    print("python", sys.version.split()[0], "outlook dropped:", "html_dropped" in by_id["slow1"])
