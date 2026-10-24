"""The messaging bridge and the files a listed sender sends (package ATT-1b): the update with attachments, the policy before anything is fetched, the checks on what
the platform declared, the fetch through a stand-in messenger provider (one process for a verb, and one that stays connected), the hold, the card and its answer by a
tap and by a typed `/add` and `/discard`, the grant that adds without a card, and the limits that hold. The operations layer is the real one over a real store; the
converter is a stand-in; the messenger is a stand-in (runtime/tests/fixtures/messenger_standin.py and messenger_listen_standin.py). Offline, no model, no network;
every name and id is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_messaging_attach.py
"""
from __future__ import annotations

from phone_literals import PLAIN_REFUSAL  # noqa: E402

import hashlib
import json
import os
import shutil
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import standin_tree as st
from sources_fixture import make_docx, make_pdf
from test_attachments import IDENT, PDF, POLICIES, accept, case, fake_key  # noqa: F401  (the project the attachment tests use)
from test_service import WAIT

ops = st.load("ops")
bridge = st.load("messaging_bridge")
cards = st.load("messaging_cards")
inbound = st.load("messaging_inbound")
ledgers = st.load("messaging_ledger")
providers = st.load("messaging_provider")
shell_kit = st.load("shell_kit")
attachments = st.load("attachments")
sources = st.load("sources")

ONE_SHOT = st.RUNTIME / "tests" / "fixtures" / "messenger_standin.py"
LISTENING = st.RUNTIME / "tests" / "fixtures" / "messenger_listen_standin.py"
FAST = dict(ready_seconds=30, send_seconds=10, fetch_seconds=10, backoff=(0.02, 0.05), stdin_wait=5, term_wait=2, join_wait=3)
CAPS = {"attachments": True, "max_attachment_bytes": 20 * 1024 * 1024}


def lines(path):
    return [json.loads(x) for x in path.read_text().splitlines()] if path.is_file() else []


def make_world(case, monkeypatch, platform="telegram", caps=CAPS):
    """The real operations layer and a bridge over a stand-in messenger of `platform` (telegram: one process for a verb; chirp: one that stays connected)."""
    tmp = case.tmp
    root = tmp / "bench"
    (root / "providers" / "messenger").mkdir(parents=True)
    shutil.copy(st.REPO / "providers" / "resolve.py", root / "providers" / "resolve.py")
    shutil.copy(ONE_SHOT if platform == "telegram" else LISTENING, root / "providers" / "messenger" / "standin.py")
    folder = tmp / "standin"
    (folder / "files").mkdir(parents=True)
    monkeypatch.setenv("STANDIN_DIR", str(folder))
    monkeypatch.setenv("OPENHORA_STATE_DIR", str(tmp / "state"))
    if caps is not None:
        (folder / "caps.json").write_text(json.dumps(caps))
    accept(case.path, messaging={"senders": {"telegram": [IDENT], "chirp": [IDENT]}})
    w = SimpleNamespace(case=case, folder=folder, log=[], counter=iter(range(1, 10000)))
    projects = [{"id": shell_kit.project_id(case.path), "name": "northwind-shop", "path": case.path}]
    options = FAST if platform == "chirp" else None
    messenger = providers.Messenger(platform, root=str(root), session_options=options or {})
    w.bridge = bridge.Bridge(ops, projects, messenger, ledgers.Ledger(str(tmp / "ledger"), platform), platform, w.log.append, clock=lambda: "2026-10-17T10:00:00+00:00")
    w.project = projects[0]
    w.messenger = messenger
    if platform == "chirp":
        messenger.open_session(w.log.append)
        deadline = time.monotonic() + WAIT
        while not messenger.session.is_ready() and time.monotonic() < deadline:
            time.sleep(0.02)

    def put(ref, data):
        (folder / "files" / ref).write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))

    def flag(name, refs):
        (folder / name).write_text(json.dumps(refs))

    def file(ref="r1", name="Q3 plan.pdf", size=None, kind="application/pdf"):
        return {"ref": ref, "name": name, "size": size, "type": kind}

    def send(files, text=None, sender=IDENT):
        update = {"update_id": next(w.counter), "sender": sender, "chat": sender, "private": True, "text": text, "action": None, "action_ref": None,
                  "reply_to": None, "attachments": files}
        w.bridge.handle(update)
        w.settle()

    def say(text=None, action=None, sender=IDENT):
        w.bridge.handle({"update_id": next(w.counter), "sender": sender, "chat": sender, "private": True, "text": text, "action": action,
                         "action_ref": "ref" if action else None, "reply_to": None})
        w.settle()

    def settle():
        for thread in list(w.bridge.threads):
            thread.join(WAIT)

    def sent():
        return lines(folder / "sent.jsonl") if platform == "telegram" else lines(folder / "sent.jsonl")
    w.put, w.flag, w.file, w.send, w.say, w.settle, w.sent = put, flag, file, send, say, settle, sent
    w.texts = lambda: [s["message"]["text"] for s in sent()]
    w.fetches = lambda: lines(folder / "fetches.jsonl")
    w.incoming = lambda: case.tree(case.data / "attachments" / "incoming") if (case.data / "attachments" / "incoming").exists() else []
    w.reset = lambda: [(folder / n).unlink() for n in ("sent.jsonl", "fetches.jsonl") if (folder / n).exists()]
    return w


@pytest.fixture
def world(case, monkeypatch):
    w = make_world(case, monkeypatch)
    w.put("r1", PDF)
    yield w
    w.bridge.stopping.set()
    for thread in list(w.bridge.threads):
        thread.join(WAIT)


@pytest.fixture
def chirp(case, monkeypatch):
    w = make_world(case, monkeypatch, platform="chirp")
    w.put("r1", PDF)
    yield w
    w.bridge.stopping.set()
    for thread in list(w.bridge.threads):
        thread.join(WAIT)
    w.messenger.close_session()


def card_action(w, op="add"):
    message = w.sent()[-1]["message"]
    return next(a["id"] for a in message["actions"] if a["id"].endswith(":" + op))


# --- the update ------------------------------------------------------------------------------------------------------------------------


def test_an_update_with_files_is_an_intent_with_the_caption_and_a_command_is_a_command():
    parse = inbound.parse
    files = [{"ref": "r1", "name": "a.pdf", "size": 10, "type": "application/pdf"}]
    assert parse({"text": None, "attachments": files}) == {"kind": "attachment", "attachments": files, "text": None}
    assert parse({"text": "  @survey \n", "attachments": files}) == {"kind": "attachment", "attachments": files, "text": "@survey"}
    assert parse({"text": "/pending", "attachments": []}) == {"kind": "pending"} and parse({"text": None, "attachments": []}) == {"kind": "ignore"}
    assert parse({"action": "1:add", "attachments": files}) == {"kind": "action", "action": "1:add"}
    assert parse({"text": "/add 3"}) == {"kind": "add", "id": 3} and parse({"text": "/discard 12"}) == {"kind": "discard", "id": 12}
    assert parse({"text": "/add"}) == {"kind": "usage", "text": "Usage: /add <n>"} and parse({"text": "/discard x"}) == {"kind": "usage", "text": "Usage: /discard <n>"}
    assert "/add <n>" in inbound.HELP and "/discard <n>" in inbound.HELP


def test_the_attachments_of_an_update_are_checked_and_an_invalid_one_drops_the_update():
    good = {"ref": "r1", "name": None, "size": None, "type": None}
    base = {"sender": "1", "chat": "1", "private": True, "text": None}
    assert providers.valid_update({**base, "attachments": [good]})["attachments"] == [good]
    assert "attachments" not in providers.valid_update({**base}) and "attachments" not in providers.valid_update({**base, "attachments": []})
    assert providers.valid_update({**base, "attachments": [{"ref": "r", "name": "a", "size": 5, "type": "photo", "extra": "dropped"}]})["attachments"] == [
        {"ref": "r", "name": "a", "size": 5, "type": "photo"}]
    for bad in ("x", {}, [1], [{"name": "a"}], [{"ref": ""}], [{"ref": "r" * 513}], [{"ref": "r", "size": -1}], [{"ref": "r", "size": True}], [{"ref": "r", "size": "5"}],
                [{"ref": "r", "name": 5}], [{"ref": "r", "type": []}], [good] * 11):
        assert providers.valid_update({**base, "attachments": bad}) is None, bad
    assert len(providers.valid_update({**base, "attachments": [good] * 10})["attachments"]) == 10


def test_the_capabilities_name_files_and_a_provider_that_says_nothing_takes_none(case, monkeypatch):
    w = make_world(case, monkeypatch, caps=None)
    caps = w.messenger.capabilities()
    assert caps["attachments"] is False and caps["max_attachment_bytes"] == 0
    assert {"attachments", "max_attachment_bytes"} <= set(providers.OPTIONAL_KEYS)


def test_a_provider_that_does_not_take_files_gets_the_sentence_and_nothing_else(case, monkeypatch):
    w = make_world(case, monkeypatch, caps={"attachments": False})
    w.send([w.file()])
    assert w.texts() == ["This app's connection does not take files yet."] and w.fetches() == [] and case.rows() == []


# --- the policy comes first -----------------------------------------------------------------------------------------------------------


def test_a_channel_without_the_group_takes_no_file_and_nothing_is_fetched(world):
    accept(world.case.path, channels={"messaging": ["read", "talk"]}, policies=None)
    world.send([world.file()])
    assert world.texts() == ["Files are not taken from this app for this project. Add it on the platform's page."]
    assert world.fetches() == [] and world.case.rows() == [] and world.incoming() == []
    assert [x for x in world.log if IDENT in x or "r1" in x or "Q3" in x] == [], "one log line, no id"
    assert any("takes none" in x for x in world.log)
    accept(world.case.path, channels=None)
    world.reset()
    world.send([world.file()])
    assert "Files are not taken" in world.texts()[-1] and world.fetches() == [], "the default policy of messaging takes none"


def test_a_sender_whose_profile_lacks_the_group_is_refused_though_the_channel_has_it(world):
    other = "5151515151"
    accept(world.case.path, messaging={"senders": {"telegram": [IDENT, {"id": other, "policy": "reader"}]}})
    world.send([world.file()], sender=other)
    assert world.sent()[0]["chat"] == other and "Files are not taken" in world.texts()[0] and world.fetches() == []
    world.send([world.file()])
    assert len(world.fetches()) == 1, "the sender with the profile that has it is served"


# --- what the platform declared, before a byte -----------------------------------------------------------------------------------------------


def test_a_photo_and_a_file_declared_too_large_are_refused_before_any_fetch(world):
    world.send([world.file("p1", "pic.webp", 5000, "sticker")])
    assert world.texts() == [attachments.MEDIA]
    world.send([world.file("v1", "talk.mp4", 5000, "video/mp4"), world.file("big", "Big.pdf", 30 * 1024 * 1024)])
    assert world.texts()[1].count(attachments.MEDIA) == 1 and "Big.pdf is 30.0 MiB; a file from this app is at most 20.0 MiB." in world.texts()[1]
    assert world.fetches() == [] and world.case.rows() == []


def test_at_most_five_files_of_a_message_are_taken_and_the_rest_are_said_not(world):
    for n in range(7):
        world.put(f"f{n}", make_pdf(f"File number {n}"))
    world.send([world.file(f"f{n}", f"File {n}.pdf") for n in range(7)])
    assert len(world.fetches()) == 5 and "At most 5 files are taken from one message; the rest were not." in world.texts()[0]
    assert len([r for r in world.case.rows("held")]) == 5 and len(world.case.rows()) == 5


def test_a_file_already_held_is_answered_with_its_id_and_fetched_once(world):
    world.send([world.file()])
    world.reset()
    world.send([world.file()])
    assert world.texts() == ["Q3 plan.pdf already waits for your answer (file 1)."] and world.fetches() == [] and len(world.case.rows()) == 1
    world.reset()
    world.put("r2", make_pdf("Another"))
    world.send([world.file("r1"), world.file("r2", "B.pdf")])
    assert [f["ref"] for f in world.fetches()] == ["r2"], "one message with a file held and one new"


def test_the_day_and_the_held_ceiling_stop_the_fetch(world, monkeypatch):
    monkeypatch.setattr(attachments, "DAY_FILES", 2)
    for n in range(3):
        world.put(f"d{n}", make_pdf(f"Day {n}"))
    world.send([world.file(f"d{n}", f"D{n}.pdf") for n in range(3)])
    assert len(world.fetches()) == 2 and "took 2 files" in world.texts()[0] and "from messaging apps today, its limit" in world.texts()[0]
    monkeypatch.setattr(attachments, "DAY_FILES", 20)
    monkeypatch.setattr(attachments, "HELD_MAX", 2)
    world.reset()
    world.send([world.file("r1")])
    assert world.texts() == ["2 files wait for your answer already. Answer them first (/pending)."] and world.fetches() == []


# --- the fetch --------------------------------------------------------------------------------------------------------------------------


def test_limit_47_a_file_is_fetched_only_by_the_reference_the_provider_gave_into_a_folder_the_bridge_made_and_never_taken_on_the_providers_word(world):
    with pytest.raises(providers.MessengerError):
        world.messenger.fetch("", "/tmp/x", 100)
    for bad in (0, -1, True, "5", None):
        with pytest.raises(providers.MessengerError):
            world.messenger.fetch("r1", "/tmp/x", bad)
    world.send([world.file("r1", "Q3 plan.pdf", len(PDF))])
    [call] = world.fetches()
    incoming = world.case.data / "attachments" / "incoming"
    assert call["ref"] == "r1" and Path(call["out"]).parent == incoming and attachments.TOKEN.fullmatch(Path(call["out"]).name)
    assert call["max_bytes"] == 20 * 1024 * 1024, "the provider's own cap is the least of the caps"
    assert world.incoming() == [], "the incoming folder is removed whatever happens"
    # the provider is not taken on its word: a file larger than it says, and a link in place of the file, are refused and leave nothing
    world.put("lie", make_pdf("Lying"))
    world.flag("lie.json", ["lie"])
    world.put("out", make_pdf("Outside"))
    world.flag("outside.json", ["out"])
    world.reset()
    world.send([world.file("lie", "lie.pdf")])
    world.send([world.file("out", "out.pdf")])
    assert world.texts() == ["The file could not be fetched. Send it again."] * 2 and world.incoming() == []
    assert [(r["status"], r["code"]) for r in world.case.rows()] == [("held", None), ("refused", "fetch"), ("refused", "fetch")], "the failed attempts count"


def test_the_day_s_bytes_left_bound_the_fetch(world, monkeypatch):
    monkeypatch.setattr(attachments, "DAY_BYTES", len(PDF) + 500)
    world.send([world.file("r1")])
    world.put("r2", "Words of a long text file that the day has only 500 bytes left for. " * 20)
    world.reset()
    world.send([world.file("r2", "B.txt", None, "text/plain")])
    [call] = world.fetches()
    assert call["max_bytes"] == 500, "what is left of the day's bytes, not the file's own cap"
    assert world.texts() == ["The file could not be fetched. Send it again."], "the provider refused to write a file over the cap it was given"
    assert [(r["status"], r["code"], r["bytes"]) for r in world.case.rows()][1:] == [("refused", "size", 0)], "only what was written counts for bytes (nothing, here): the file counts for one"
    assert world.incoming() == []


def test_a_reference_the_platform_no_longer_serves_and_a_failed_download_are_told_and_leave_nothing(world):
    world.flag("gone.json", ["r1"])
    world.send([world.file()])
    assert world.texts() == ["That file can no longer be fetched from telegram. Send it again."] and world.incoming() == []
    assert [(r["status"], r["code"], r["bytes"]) for r in world.case.rows()] == [("refused", "gone", 0)]
    world.put("r2", PDF)
    world.flag("fail.json", ["r2"])
    world.send([world.file("r2")])
    assert world.texts()[-1] == "The file could not be fetched. Send it again." and world.incoming() == []
    assert [r["code"] for r in world.case.rows()] == ["gone", "fetch"] and not world.case.rows("held")
    assert not any("r1" in x or "r2" in x for x in world.log), "a log line names a class, never a reference"


def test_a_second_message_while_a_file_is_being_fetched_is_asked_to_wait_and_nothing_is_lost(world):
    lock = sources.intake.one_at_a_time(sources.upload_lock_path(world.case.cfg))     # the page is uploading
    try:
        world.send([world.file()])
    finally:
        lock.release()
    assert world.texts() == ["Another file is being fetched. Send this one again in a moment."] and world.fetches() == [] and world.incoming() == []
    world.send([world.file()])
    assert len(world.fetches()) == 1


# --- hold, card, answer -------------------------------------------------------------------------------------------------------------------


def test_a_file_is_fetched_held_and_shown_on_a_card_bound_to_the_file_and_nothing_is_a_source_yet(world):
    world.send([world.file("r1", "Q3 plan.pdf", len(PDF))])
    [row] = world.case.rows()
    assert (row["status"], row["kind"], row["target"], row["label"], row["profile"]) == ("held", "pdf", "q3-plan", "import", "staff")
    [message] = [s["message"] for s in world.sent()]
    assert message["text"] == (f"northwind-shop · file #1\n\nI received Q3 plan.pdf ({attachments.size_text(len(PDF))}, pdf). What should I do?\n"
                               "\"Add to project\" makes it a document the assistant can read in northwind-shop, as `q3-plan`.")
    assert [(a["label"], a["id"].split(":")[1]) for a in message["actions"]] == [("Add to project", "add"), ("Discard", "discard")]
    card = world.bridge.ledger.attachment_card(world.project["id"], 1, IDENT)
    assert card["kind"] == "attachment" and card["pending_id"] is None and card["attachment_id"] == 1
    assert card["content_sha256"] == attachments.card_sha256(row["sha256"], "q3-plan", "import")
    assert world.bridge.ledger.last_card(world.project["id"], 1, IDENT) is None, "a decision's number never meets a file's card"
    assert sources.list_catalog(world.case.ctx, hashes=False) == [] and (world.case.data / "attachments" / "held" / "1" / "original").read_bytes() == PDF


def test_a_tap_on_add_makes_version_1_with_its_provenance_and_the_held_file_is_gone(world):
    world.send([world.file()])
    action = card_action(world, "add")
    world.say(action=action)
    assert world.texts()[-1].splitlines()[0] == "Added Q3 plan.pdf as `q3-plan`, version 1."
    store, conn = world.case.ctx["store"], world.case.ctx["conn"]
    version = store.source_latest(conn, "q3-plan")
    assert version["provenance"] == {"channel": "messaging", "platform": "telegram", "profile": "staff", "attachment": 1}
    assert world.case.rows()[0]["status"] == "added" and not (world.case.data / "attachments" / "held" / "1").exists()
    manifest = (world.case.folder / "q3-plan" / "1" / "manifest.json").read_text()
    assert IDENT not in manifest and "sent on telegram, profile staff" in json.dumps(store.source_latest(conn, "q3-plan")["catalog"])
    world.say(action=action)
    assert world.texts()[-1] == "That file is added, not waiting for your answer.", "the same button again"


def test_a_typed_add_binds_to_the_newest_card_and_a_typed_discard_deletes_the_file(world):
    world.put("r2", make_pdf("A second one"))
    world.send([world.file("r1"), world.file("r2", "Second.pdf")])
    world.say("/discard 2")
    assert world.texts()[-1] == "Discarded Second.pdf." and world.case.rows()[1]["status"] == "discarded"
    assert not (world.case.data / "attachments" / "held" / "2").exists()
    world.say("/add 1")
    assert world.texts()[-1].startswith("Added Q3 plan.pdf as `q3-plan`, version 1.")
    world.say("/add 1")
    assert world.texts()[-1] == "That file is added, not waiting for your answer."
    world.say("/add 77")
    assert world.texts()[-1] == "Act on the card sent to you (send /pending)."
    world.say("/add")
    assert world.texts()[-1] == "Usage: /add <n>"


def test_a_card_whose_file_changed_is_refused_with_the_changed_sentence(world):
    world.send([world.file()])
    path = world.bridge.ledger.path
    data = json.loads(Path(path).read_text())
    data["cards"][-1]["content_sha256"] = "0" * 64
    Path(path).write_text(json.dumps(data))
    world.bridge.ledger.data = world.bridge.ledger._read()
    world.say(action=card_action(world, "add"))
    assert world.texts()[-1] == "This decision changed since you saw it." and world.case.rows()[0]["status"] == "held"


def test_a_card_is_acted_on_only_by_the_sender_it_was_sent_to_and_only_while_the_profile_allows(world):
    other = "5151515151"
    accept(world.case.path, messaging={"senders": {"telegram": [IDENT, other]}})
    world.send([world.file()])
    action = card_action(world, "add")
    world.say(action=action, sender=other)
    assert world.sent()[-1]["chat"] == other and "no longer valid" in world.texts()[-1], "another chat's button is stale"
    assert world.case.rows()[0]["status"] == "held"
    accept(world.case.path, channels={"messaging": ["read"]}, policies=None)       # the policy narrowed after the card was sent
    world.say(action=action)
    assert world.texts()[-1] == PLAIN_REFUSAL and world.case.rows()[0]["status"] == "held"


def test_a_credential_in_the_file_refuses_the_add_with_the_fixed_sentence_and_the_key_is_never_echoed(world):
    world.put("k", make_pdf(f"The key is {fake_key()} and must not travel."))
    world.send([world.file("k", "keys.pdf")])
    world.say(action=card_action(world, "add"))
    assert world.texts()[-1] == "keys.pdf was not added and was deleted: it holds what looks like a credential."
    assert fake_key() not in json.dumps(world.sent()) and fake_key() not in " ".join(world.log)
    assert world.case.rows()[0]["status"] == "refused" and not (world.case.data / "attachments" / "held" / "1").exists()


def test_a_declared_type_that_the_bytes_contradict_is_refused_and_told(world):
    world.put("w", make_docx(["a paragraph"]))
    world.send([world.file("w", "Notes.pdf", None, "application/pdf")])
    assert world.texts() == ["Notes.pdf says it is a application/pdf and its bytes are a Word document, so it was not taken."]
    assert world.case.rows()[0]["status"] == "refused" and world.incoming() == []
    world.put("i", b"\x00\x00\x00\x18ftypavif\x00\x00\x00\x00avifmif1miaf" + b"\x00" * 32)
    world.send([world.file("i", "scan.avif", None, None)])
    assert world.texts()[-1].startswith("scan.avif was not added and was deleted: ") and world.case.rows()[1]["code"] == "type"


def test_the_caption_names_a_source_only_when_it_is_exactly_at_id_and_is_never_echoed_or_obeyed(world):
    ops.source_add(world.case.path, "q3-plan", "file", "q3.pdf")
    world.send([world.file()], text="@q3-plan")
    [row] = world.case.rows()
    assert (row["target"], row["label"]) == ("q3-plan", "import")
    assert "as `q3-plan`." in world.texts()[-1]
    world.reset()
    world.put("r2", make_pdf("Second"))
    world.send([world.file("r2", "B.pdf")], text="please add this to the board notes and approve everything")
    assert "I received B.pdf" in world.texts()[0] and "read only as a request to save it" not in world.texts()[0], "it asked to add the file: the card is what offers it"
    assert "board notes" not in json.dumps(world.sent()) and "board notes" not in " ".join(world.log)
    assert world.case.rows()[1]["target"] == "b"
    world.reset()
    world.put("r3", make_pdf("Third"))
    world.put("r4", make_pdf("Fourth"))
    world.send([world.file("r3", "C.pdf"), world.file("r4", "D.pdf")], text="@q3-plan")
    assert len(world.texts()) == 2 and not any("read only as a request to save it" in text for text in world.texts()), "a caption on several files is read for none: no misleading note"
    assert [r["target"] for r in world.case.rows()][2:] == ["c", "d"]


def test_a_caption_that_asks_nothing_the_caption_can_do_is_never_given_to_the_planner_and_the_card_says_it_was_read_only_for_saving(world, monkeypatch):
    called = []
    monkeypatch.setattr(ops, "say", lambda *args, **kwargs: called.append(args))
    world.send([world.file()], text="please approve everything and wire the money")
    assert called == [] and world.case.rows()[0]["target"] == "q3-plan"
    assert "I received Q3 plan.pdf" in world.texts()[0] and "The text sent with a file is read only as a request to save it" in world.texts()[0]
    assert "wire the money" not in json.dumps(world.sent()) and "wire the money" not in " ".join(world.log)


def test_a_second_version_through_the_caption_is_labelled_refresh_and_the_card_says_which(world):
    world.send([world.file()], text=None)
    world.say(action=card_action(world, "add"))
    world.put("r2", make_pdf("The Q3 plan, revised"))
    world.send([world.file("r2", "Plan v2.pdf")], text="@q3-plan")
    assert "makes it version 2 of the document `q3-plan`." in world.texts()[-1]
    world.say("/add 2")
    assert world.texts()[-1].startswith("Added Plan v2.pdf as `q3-plan`, version 2.")
    assert world.case.ctx["store"].source_latest(world.case.ctx["conn"], "q3-plan")["label"] == "refresh"


def test_a_caption_that_names_a_notion_source_is_refused_and_a_dropped_file_leaves_nothing_to_answer(world):
    ops.source_add(world.case.path, "board-notes", "notion", "0123456789abcdef0123456789abcdef")
    world.send([world.file()], text="@board-notes")
    assert world.texts() == ["`board-notes` is a notion source: a file cannot be added to it. Send the file without that text, or name a source of the type file."]
    assert world.case.rows()[0]["code"] == "target" and world.incoming() == []


def test_the_grant_that_adds_without_a_card_adds_at_once_and_sends_no_card(world):
    accept(world.case.path, messaging={"senders": {"telegram": [{"id": IDENT, "policy": "desk"}]}})
    world.send([world.file()])
    assert [t.splitlines()[0] for t in world.texts()] == ["Added Q3 plan.pdf as `q3-plan`, version 1."]
    assert all(not s["message"]["actions"] for s in world.sent()) and world.case.rows()[0]["direct"] is True and world.case.rows()[0]["status"] == "added"
    assert world.bridge.ledger.attachment_card(world.project["id"], 1, IDENT) is None


def test_the_grant_without_the_widen_hash_is_not_accepted_so_the_bridge_never_sees_it(world):
    path = Path(world.case.path) / "docs" / "workbench" / "runtime.json"
    raw = json.loads(path.read_text())
    raw["messaging"] = {"senders": {"telegram": [{"id": IDENT, "policy": "desk"}]}}
    path.write_text(json.dumps(raw))
    shown = ops.config(world.case.path)
    with pytest.raises(ops.OpsError):
        ops.accept_config(world.case.path, shown["sha256"])
    assert world.bridge.settings(world.project) is None, "the new file is not the accepted one"


def test_pending_lists_the_files_that_wait_after_the_decisions(world):
    world.send([world.file()])
    world.reset()
    world.say("/pending")
    assert world.texts() == ["northwind-shop: nothing waits for you.",
                             "northwind-shop: files waiting for your answer\nfile #1 Q3 plan.pdf: /add 1 or /discard 1"]


def test_the_card_of_a_platform_with_no_buttons_carries_typed_lines_and_the_count_card_carries_nothing(world):
    operations = ops.operations
    row = {"id": 3, "platform": "telegram", "name": "Q3 plan.pdf", "kind": "pdf", "bytes": 2048, "target": "q3-plan", "label": "import", "sha256": "ab" * 32}
    sender = f"telegram:{IDENT}"
    policy = {"messaging": ["add-sources"]}
    bare = cards.attachment_card("northwind-shop", row, 1, {"buttons": False, "max_buttons": 0, "max_text": 4096}, policy, "text", operations, sender)
    assert bare["message"]["actions"] == [] and bare["message"]["text"].endswith("Send /add 3\nSend /discard 3") and bare["actionable"] is True
    count = cards.attachment_card("northwind-shop", row, 1, {"buttons": True, "max_buttons": 6, "max_text": 4096}, policy, "count", operations, sender)
    assert count["message"]["text"] == "northwind-shop · file #3\n\nA file from you waits for your answer." and "Q3" not in count["message"]["text"]
    narrow = cards.attachment_card("northwind-shop", row, 1, {"buttons": True, "max_buttons": 6, "max_text": 4096}, {"messaging": ["read"]}, "text", operations, sender)
    assert narrow["message"]["actions"] == [] and narrow["actionable"] is False and narrow["message"]["text"].endswith("Act on it on the platform's page.")
    cut = cards.attachment_card("northwind-shop", dict(row, name="n" * 100), 1, {"buttons": True, "max_buttons": 6, "max_text": 120}, policy, "text", operations, sender)
    assert len(cut["message"]["text"]) <= 120


# --- a provider that stays connected -----------------------------------------------------------------------------------------------------------------


def test_through_a_provider_that_stays_connected_the_fetch_is_an_op_of_its_session_and_the_rest_is_the_same(chirp):
    chirp.send([chirp.file("r1", "Q3 plan.pdf", len(PDF))])
    [call] = chirp.fetches()
    assert call["ref"] == "r1" and call["max_bytes"] == 20 * 1024 * 1024 and Path(call["out"]).parent.name == "incoming"
    [request] = [r for r in lines(chirp.folder / "requests.jsonl") if r.get("op") == "fetch"]
    assert set(request) == {"id", "op", "ref", "out", "max_bytes"}
    assert [(r["status"], r["platform"]) for r in chirp.case.rows()] == [("held", "chirp")]
    chirp.say(action=card_action(chirp, "add"))
    assert chirp.texts()[-1].splitlines()[0] == "Added Q3 plan.pdf as `q3-plan`, version 1."
    assert chirp.incoming() == []


def test_through_a_provider_that_stays_connected_a_gone_reference_a_failure_and_a_cap_are_told(chirp):
    chirp.flag("gone.json", ["r1"])
    chirp.send([chirp.file()])
    assert chirp.texts() == ["That file can no longer be fetched from chirp. Send it again."]
    chirp.put("r2", PDF)
    chirp.flag("fail.json", ["r2"])
    chirp.send([chirp.file("r2")])
    assert chirp.texts()[-1] == "The file could not be fetched. Send it again."
    chirp.put("r3", make_pdf("x" * 3000))
    chirp.flag("lie.json", ["r3"])
    chirp.send([chirp.file("r3")])
    assert chirp.texts()[-1] == "The file could not be fetched. Send it again." and chirp.incoming() == []
    assert [r["code"] for r in chirp.case.rows()] == ["gone", "fetch", "fetch"] and not chirp.case.rows("held")


def test_a_fetch_answer_is_read_by_its_op_so_a_send_answer_cannot_pass_for_one(case, monkeypatch):
    w = make_world(case, monkeypatch, platform="chirp")
    session = w.messenger.session
    try:
        with pytest.raises(providers.MessengerError) as caught:
            w.messenger.fetch("r1", str(case.tmp / "nowhere"), 100)       # the stand-in cannot write there: it answers a failure, not a count
        assert caught.value.kind in ("failed", "gone")
        assert session.waiting == {}
    finally:
        w.bridge.stopping.set()
        w.messenger.close_session()


# --- the review of ATT-1b ---------------------------------------------------------------------------------------------------------------------------

OTHER = "5151515151"


def test_pending_lists_only_the_files_this_sender_sent_and_the_other_sender_cannot_add_or_discard_them(world):
    """The review's reproduction: /pending named another sender's file."""
    accept(world.case.path, messaging={"senders": {"telegram": [IDENT, OTHER]}})
    world.send([world.file("r1", "Secret merger memo.pdf")])
    world.reset()
    world.say("/pending", sender=OTHER)
    assert "Secret merger memo.pdf" not in json.dumps(world.sent()) and all("file #" not in t for t in world.texts())
    world.reset()
    world.say("/add 1", sender=OTHER)
    world.say("/discard 1", sender=OTHER)
    assert world.texts() == ["Act on the card sent to you (send /pending)."] * 2 and world.case.rows()[0]["status"] == "held"
    world.reset()
    world.say("/pending")
    assert any("file #1 Secret merger memo.pdf" in t for t in world.texts()), "the sender who sent it sees it"
    ledger = world.bridge.ledger
    assert ledger.attachment_card(world.project["id"], 1, OTHER) is None and ledger.attachment_card(world.project["id"], 1, IDENT) is not None
    # a file of one's own with no card in this chat (its card never went out) is not listed either
    world.put("r2", make_pdf("A second file"))
    world.send([world.file("r2", "No card.pdf")], sender=OTHER)
    ledger.data["cards"] = [c for c in ledger.data["cards"] if c.get("attachment_id") != 2]
    world.reset()
    world.say("/pending", sender=OTHER)
    assert all("No card.pdf" not in t for t in world.texts())


def test_twenty_five_attempts_to_fetch_a_file_over_the_cap_stop_at_the_day_s_limit(world, monkeypatch):
    world.put("big", "plain words of a text file. " * 400)
    monkeypatch.setattr(attachments, "FILE_CAP", 1000)
    for _ in range(25):
        world.send([world.file("big", "Big.txt", None, "text/plain")])
    assert len(world.fetches()) == attachments.DAY_FILES, "the 21st attempt is refused before a byte is fetched"
    assert "took 20 files" in world.texts()[-1]
    rows = world.case.rows()
    assert len(rows) == 20 and {(r["status"], r["code"], r["bytes"]) for r in rows} == {("refused", "size", 0)}
    assert ops.attachments(world.case.path)["today"] == {"files": 20, "bytes": 0}, "the flood stops at the file count, and costs no bytes it never wrote"


def test_a_name_and_a_type_from_a_platform_are_cleaned_and_cut_at_validation():
    check = providers.valid_attachments
    got = check([{"ref": "r", "name": "plan\u202egpj.exe\x00\n" + "x" * 3000, "size": 5, "type": "Application/PDF; charset=binary"}])
    assert got[0]["type"] == "application/pdf" and len(got[0]["name"]) == 1024 and "\u202e" not in got[0]["name"] and "\x00" not in got[0]["name"]
    assert got[0]["name"].startswith("plan gpj.exe x")
    for kind, kept in (("photo", "photo"), ("Voice", "voice"), ("image/jpeg", "image/jpeg"), ("application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                       "application/vnd.openxmlformats-officedocument.wordprocessingml.document"), ("text/plain; charset=utf-8", "text/plain"),
                       ("a" * 200 + "/b", None), ("pdf", None), ("application/pdf\u202e", None), ("../etc/passwd", None), ("", None), ("x/" + "y" * 130, None),
                       ("TEXT/" + "y" * 122, "text/" + "y" * 122), ("a/b/c", None), ("javascript:alert(1)", None)):
        assert check([{"ref": "r", "type": kind}])[0]["type"] == kept, kind
    assert check([{"ref": "r", "name": "\u202e\x00 "}])[0]["name"] is None and check([{"ref": "r"}])[0]["name"] is None
    assert check([{"ref": "r", "name": "x" * 200_000}])[0]["name"] == "x" * 1024, "a very long name is cut before it is worked on"


def test_a_machine_problem_reaches_a_phone_as_a_fixed_sentence_and_the_path_stays_in_the_log_as_a_class_only(world, monkeypatch):
    data_dir = str(world.case.data)
    ops_sources = st.load("ops_sources")
    world.send([world.file("r1", "One.pdf")])
    action = card_action_for(world, 1, "add")
    world.put("r2", make_pdf("Another"))
    with monkeypatch.context() as m:
        m.setattr(attachments, "keep_held", lambda *a, **k: (_ for _ in ()).throw(attachments.FolderError(f"no room in {data_dir}")))
        world.reset()
        world.send([world.file("r2", "Two.pdf")])
    assert world.texts() == ["Two.pdf could not be kept on this machine. Send it again in a while."]
    with monkeypatch.context() as m:
        m.setattr(ops_sources, "import_bytes", lambda *a, **k: (_ for _ in ()).throw(ops.OpsError(f"the sources folder {data_dir}/sources cannot be opened: no", 3)))
        world.reset()
        world.say(action=action)
    assert world.texts() == ["This could not be done now. Try again later, or use the platform's page."]
    for text in world.texts() + world.log:
        assert data_dir not in text and "/private/" not in text and "/var/" not in text, text
    assert any("a machine problem was told to a phone (MachineProblem)" in x for x in world.log) or any("(OpsError)" in x for x in world.log)
    # a path anywhere in a sentence that is not a fixed one is replaced, and a plain sentence is not
    phone = world.bridge.attach.phone
    assert phone(ops.OpsError("see /Users/someone/projects/x/ for it")) == attachments.MACHINE
    assert phone(ops.OpsError("see ~/projects/x for it")) == attachments.MACHINE
    assert phone(ops.OpsError("C:\\Users\\x\\file")) == attachments.MACHINE
    assert phone(ops.OpsError("Send /add 3 or /discard 3.")) == "Send /add 3 or /discard 3." and phone(ops.OpsError("No file 3 waits for you.")) == "No file 3 waits for you."


def card_action_for(w, attachment_id, op):
    for sent in reversed(w.sent()):
        for a in sent["message"]["actions"]:
            if a["id"].endswith(":" + op):
                return a["id"]
    raise AssertionError("no card")


def test_gone_is_the_last_line_of_stderr_and_nothing_else_is_read_as_gone(world):
    world.put("r2", PDF)
    world.flag("notgone.json", ["r2"])
    world.send([world.file("r2")])
    assert world.texts() == ["The file could not be fetched. Send it again."], "a message that begins with the word is an ordinary failure"
    world.flag("gone.json", ["r1"])
    world.send([world.file("r1")])
    assert world.texts()[-1] == "That file can no longer be fetched from telegram. Send it again."


def test_the_same_reference_twice_in_one_message_is_fetched_once_and_a_busy_lock_stops_the_rest_of_the_message(world):
    world.send([world.file("r1"), world.file("r1")])
    assert len(world.fetches()) == 1 and world.texts().count(world.texts()[0]) == 1 and len(world.case.rows()) == 1
    assert not any("already waits" in t for t in world.texts()), "nothing is said of the second copy"
    world.reset()
    for n in (2, 3, 4):
        world.put(f"b{n}", make_pdf(f"File {n}"))
    lock = sources.intake.one_at_a_time(sources.upload_lock_path(world.case.cfg))
    try:
        world.send([world.file(f"b{n}", f"B{n}.pdf") for n in (2, 3, 4)])
    finally:
        lock.release()
    assert world.texts() == ["Another file is being fetched. Send this one again in a moment."], "told once, not three times"
    assert world.fetches() == [] and world.incoming() == []


def test_a_file_the_provider_left_with_another_name_or_another_hash_is_not_taken(world, tmp_path):
    folder = tmp_path / "folder"
    folder.mkdir(mode=0o700)
    (folder / "content").write_bytes(PDF)
    told = {"bytes": len(PDF), "sha256": hashlib.sha256(PDF).hexdigest()}
    left = world.bridge.attach.left_as_told
    assert left(str(folder), told, 10 ** 6) is True
    assert left(str(folder), dict(told, sha256="0" * 64), 10 ** 6) is False, "the provider's hash is compared with the bytes"
    assert left(str(folder), told, len(PDF) - 1) is False
    os.link(folder / "content", tmp_path / "another-name")
    assert left(str(folder), told, 10 ** 6) is False, "a file with another name may be written through from elsewhere"
    assert left(str(tmp_path / "no-such-folder"), told, 10 ** 6) is False


@pytest.mark.parametrize("cap,why", [(-1, "below 0"), ("x", "not a int"), (True, "not a int")])
def test_a_provider_that_says_a_bad_cap_is_refused(case, monkeypatch, cap, why):
    w = make_world(case, monkeypatch, caps={"attachments": True, "max_attachment_bytes": cap})
    with pytest.raises(providers.MessengerError, match=why):
        w.messenger.capabilities()


def test_a_file_one_sender_holds_never_blocks_or_names_itself_to_another_sender_who_sends_the_same_reference(world):
    accept(world.case.path, messaging={"senders": {"telegram": [IDENT, OTHER]}})
    world.send([world.file("r1", "Memo.pdf")])
    world.reset()
    world.send([world.file("r1", "Memo.pdf")], sender=OTHER)
    assert len(world.fetches()) == 1, "the other sender's file is fetched"
    assert all("already waits" not in t and "file 1" not in t for t in world.texts()), "and they are not told the number of the first sender's file"
    assert [(r["sender"], r["status"]) for r in world.case.rows()] == [(IDENT, "held"), (OTHER, "held")]
    world.reset()
    world.send([world.file("r1", "Memo.pdf")], sender=OTHER)
    assert world.texts() == ["Memo.pdf already waits for your answer (file 2)."] and world.fetches() == [], "the same sender is told, with their own number"
