"""The files a listed sender sends, in the project's language (package LR-1 over ATT-1b, runtime/phrases.py): the refusals before anything is fetched, the
card of a held file, the answer to a tap or a typed `/add` and `/discard`, the list of the files that wait, and what a phone is told of an error of the
operations layer. The operations layer is the real one over a real store, the converter and the messenger are the stand-ins of test_messaging_attach.py;
a project with no `language` gets the English sentences it always got. Offline, no model, no network; every name and id is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_runtime_language_files.py
"""
from __future__ import annotations

import phrase_kit as pk
import standin_tree as st
from test_attachments import IDENT, PDF, accept, case  # noqa: F401  (the project the attachment tests use)
from test_messaging_attach import card_action, make_world, world  # noqa: F401  (the stand-in world over a real store)

ops = st.load("ops")
attachments = st.load("attachments")
phrases = st.load("phrases")
PT = phrases.TABLE["pt-BR"]
PT_CFG = {"language": "pt-BR"}


def speak(world, tag):
    accept(world.case.path, language=tag)


def test_a_provider_that_takes_no_file_and_a_channel_without_the_group_are_told_in_portuguese(case, monkeypatch):  # noqa: F811
    w = make_world(case, monkeypatch, caps={"attachments": False})
    speak(w, "pt-BR")
    w.send([w.file()])
    [told] = w.texts()
    pk.assert_said(told, "ATT_NO_FILES", PT_CFG)
    assert w.fetches() == []
    w.reset()
    (w.folder / "caps.json").write_text('{"attachments": true, "max_attachment_bytes": 20971520}')
    w.messenger._caps = None
    accept(case.path, channels={"messaging": ["read", "talk"]}, policies=None, language="pt-BR")
    w.send([w.file()])
    [told] = w.texts()
    pk.assert_said(told, "ATT_OFF", PT_CFG)
    assert w.fetches() == [] and case.rows() == []


def test_the_refusals_before_a_byte_is_fetched_are_in_portuguese(world):
    speak(world, "pt-BR")
    world.send([world.file("p1", "talk.ogg", 5000, "voice")])
    [media] = world.texts()
    pk.assert_said(media, "ATT_MEDIA", PT_CFG)
    world.send([world.file("big", "Big.pdf", 30 * 1024 * 1024)])
    pk.assert_said(world.texts()[-1], "ATT_TOO_LARGE", PT_CFG, name="Big.pdf", size="30,0 MiB", cap="20,0 MiB")
    before = len(world.texts())
    world.send([world.file()], text="please read the file")
    assert pk.said(world.texts()[before].splitlines()[-1], "ATT_CAPTION_IGNORED", PT_CFG)
    assert len(world.fetches()) == 1


def test_the_card_of_a_held_file_and_its_answers_are_in_portuguese(world):
    speak(world, "pt-BR")
    world.send([world.file("r1", "Q3 plan.pdf", len(PDF))])
    [message] = [s["message"] for s in world.sent()]
    head, blank, what, add = message["text"].split("\n")
    pk.assert_said(head, "HEADER_FILE", PT_CFG, project="northwind-shop", id=1)
    assert blank == ""
    pk.assert_said(what, "ATTACH_WHAT", PT_CFG, name="Q3 plan.pdf", size=attachments.size_text(len(PDF)), kind="pdf")
    pk.assert_said(add, "ATTACH_WHAT_ADD", PT_CFG, project="northwind-shop", id="q3-plan")
    assert [a["id"].split(":")[1] for a in message["actions"]] == ["add", "discard"]
    pk.assert_said(message["actions"][0]["label"], "LABEL_ADD", PT_CFG)
    pk.assert_said(message["actions"][1]["label"], "LABEL_DISCARD", PT_CFG)
    action = card_action(world, "add")
    world.reset()
    world.say("/pending")
    nothing, waiting = world.texts()
    pk.assert_said(nothing, "NOTHING_WAITS", PT_CFG, name="northwind-shop")
    waiting_head, waiting_line = waiting.split("\n")
    pk.assert_said(waiting_head, "ATT_WAITING_HEAD", PT_CFG, project="northwind-shop")
    pk.assert_said(waiting_line, "ATT_WAITING_LINE", PT_CFG, id=1, name="Q3 plan.pdf")
    world.say(action=action)
    pk.assert_said(world.texts()[-1].splitlines()[0], "ATT_ADDED", PT_CFG, name="Q3 plan.pdf", id="q3-plan", n=1)
    world.say(action=action)
    pk.assert_said(world.texts()[-1], "ATT_NOT_HELD", PT_CFG, status="adicionado")
    world.say("/add 77")
    pk.assert_said(world.texts()[-1], "NO_CARD", PT_CFG)
    world.say("/add")
    pk.assert_said(world.texts()[-1], "USAGE_ADD", PT_CFG)


def test_a_typed_discard_is_answered_in_portuguese(world):
    speak(world, "pt-BR")
    world.put("r2", PDF + b"\n")
    world.send([world.file("r1"), world.file("r2", "Second.pdf")])
    world.say("/discard 2")
    pk.assert_said(world.texts()[-1], "ATT_DISCARDED", PT_CFG, name="Second.pdf")


def test_what_a_phone_is_told_of_an_error_of_the_operations_layer(world):
    phone = world.bridge.attach.phone
    speak(world, "pt-BR")
    assert phone(ops.OpsError("see /Users/someone/projects/x/ for it"), world.project) == PT["ATT_MACHINE"]
    pk.assert_said(phone(ops.OpsError(phrases.text("ATT_NO_SUCH", None, n=3)), world.project), "ATT_NO_SUCH", PT_CFG, n=3)
    refused = ops.OpsError(attachments.REFUSED.format(name="a.docx", reason=phrases.text("ATT_REASON_MACRO", None)))
    pk.assert_said(phone(refused, world.project), "ATT_REFUSED", PT_CFG, name="a.docx", reason=phrases.text("ATT_REASON_MACRO", PT_CFG))
    # a text the table does not know is the plain sentence in a language that is not English (S14b)
    pk.assert_said(phone(ops.OpsError("Send /add 3 or /discard 3."), world.project), "PHONE_FAILED", PT_CFG, where=phrases.text("PHONE_WHERE", PT_CFG) + ".")      # a full stop closes the sentence that ends with the place
    assert phone(ops.OpsError("The sources folder cannot be opened", 3), world.project) == PT["ATT_MACHINE"]
    speak(world, None)
    pk.assert_said(phone(ops.OpsError(phrases.text("ATT_NO_SUCH", None, n=3)), world.project), "ATT_NO_SUCH", None, n=3)
    assert phone(ops.OpsError("see /Users/someone/projects/x/ for it"), world.project) == attachments.MACHINE
    speak(world, "fr")
    pk.assert_said(phone(ops.OpsError(phrases.text("ATT_NO_SUCH", None, n=3)), world.project), "ATT_NO_SUCH", {"language": "fr"}, n=3)


def test_an_english_project_gets_the_file_sentences_it_always_got(world):
    world.send([world.file("p1", "talk.ogg", 5000, "voice")])
    assert world.texts() == [attachments.MEDIA]
    world.send([world.file("r1", "Q3 plan.pdf", len(PDF))])
    head, blank, what, _rest = world.texts()[-1].split("\n", 3)
    pk.assert_said(head, "HEADER_FILE", None, project="northwind-shop", id=1)
    assert blank == ""
    pk.assert_said(what, "ATTACH_WHAT", None, name="Q3 plan.pdf", size=attachments.size_text(len(PDF)), kind="pdf")
    world.say(action=card_action(world, "add"))
    pk.assert_said(world.texts()[-1].splitlines()[0], "ATT_ADDED", None, name="Q3 plan.pdf", id="q3-plan", n=1)
    world.say("/add 77")
    pk.assert_said(world.texts()[-1], "NO_CARD", None)
