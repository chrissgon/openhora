"""The bridge's side of sending a file (slice S18; runtime/messaging_bridge.py `line`, `reply`, `deliver_file`, `file_to_send`, runtime/messaging_file.py), over the stand-in messenger of test_messaging.py.

The stand-in provider (runtime/tests/fixtures/messenger_standin.py, started through providers/resolve.py as the real one is) reads the file at the path it is handed WHILE it runs and records
the bytes, the mode of the file and of its folder in sent.jsonl: the test's own count, never the bridge's. The stand-in operations object answers `say` with a reply and an attachment
(bytes in memory), as the operations layer does (runtime/tests/test_file_send.py). Offline, no model, no network; every name is invented.

  a provider that declares `send_files` is told its limits in the call of `say`; one that does not is told nothing (the call is the one it always was)
  the file goes with the reply as one temporary file of a private folder, the provider reads it, and the folder is gone when the send ends (also when the provider refuses it)
  the right is asked again at the send: a profile that lost a group, a provider that cannot carry the file, or a file over the limit sends no file and the reply says so
  a file that did not arrive after the text went out, and a file the provider refused, are one plain sentence

Each oracle has a `test_vacuity_` case. Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_messaging_file.py
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

import standin_tree as st
from test_messaging import OPEN_POLICY, SENDER, wait_for, world  # noqa: F401  (the bridge world of test_messaging.py)

CAPS = {"send_files": True, "max_send_bytes": 1000, "max_photo_bytes": 500, "photo_types": ["png"], "send_types": ["text", "png"]}
LIMITS = {"max_bytes": 1000, "photo_max_bytes": 500, "photo_types": ["png"], "types": ["text", "png"]}
BYTES = b"Segunda: ensaio do coral.\n"
HELD = {"name": "Atividades.txt", "kind": "document", "data": BYTES}
SAID = "Atividades (OneDrive, pasta default):\n\nSegunda: ensaio do coral."
NOT_SENT = "The file did not arrive. Try again in a few minutes."


@pytest.fixture
def sending(world, monkeypatch, tmp_path):
    """The bridge world with a provider that declares `send_files`, a policy that holds both groups, a private temporary folder to watch, and an operations object that returns the file."""
    folder = tmp_path / "tmp"
    folder.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(folder))
    world.config["channels"] = {"messaging": OPEN_POLICY + ["read-files", "send-files"]}
    world.caps(**CAPS)
    world.leftovers = lambda: sorted(p.name for p in folder.iterdir())
    world.gone = lambda: wait_for(lambda: world.leftovers() == [], 10)      # the provider's process answers before the bridge unlinks its message file: wait, with a deadline
    world.answer = lambda attachment=HELD, reply=SAID: world.fake.answers.__setitem__("say", {"reply": reply, "request_id": None, "pending_id": None, "ran": False, "queued": False, **({"attachment": attachment} if attachment is not None else {})})
    return world


def wait_sent(world, count=1):
    assert wait_for(lambda: len(world.sent()) >= count, 10), world.sent()
    return world.sent()


def say_calls(world):
    return [c for c in world.calls("say")]


def test_the_limits_are_told_to_the_operation_and_the_file_goes_with_the_reply_from_one_temporary_file_that_is_gone_after(sending):
    sending.answer()
    sending.say("bring me the activities")
    [sent] = wait_sent(sending)
    assert say_calls(sending)[0][2]["can_send"] == LIMITS
    file = sent["message"]["file"]
    assert sent["message"]["text"] == SAID and sent["message"]["document"] is None
    assert (file["name"], file["kind"], bytes.fromhex(file["bytes_hex"]), file["mode"], file["folder_mode"]) == ("Atividades.txt", "document", BYTES, "0o600", "0o700")
    assert sending.gone() and not os.path.exists(file["path"]), "the provider read it while it ran, and nothing of it is left"      # the bridge removes the folder after the provider answers: wait for it, with a deadline
    assert sending.log == []


def test_vacuity_a_bridge_that_forgot_to_remove_the_folder_would_leave_the_file_and_be_seen(sending, monkeypatch):
    """The planted fault: the folder is not removed. The bytes stay in the temporary folder; the oracle above (nothing left) fails."""
    monkeypatch.setattr(st.load("messaging_file").shutil, "rmtree", lambda *a, **k: None)
    sending.answer()
    sending.say("bring me the activities")
    wait_sent(sending)
    assert any(name.startswith("messenger-file-") for name in sending.leftovers())


def test_a_provider_that_declares_no_send_files_is_told_nothing_and_is_never_handed_a_file(sending):
    sending.caps(**{k: v for k, v in CAPS.items() if k != "send_files"})
    sending.answer()
    sending.say("bring me the activities")
    [sent] = wait_sent(sending)
    assert "can_send" not in say_calls(sending)[0][2]
    assert "file" not in sent["message"]
    assert sent["message"]["text"] == SAID + "\n\n" + NOT_SENT, "an attachment the provider cannot carry stays home, and the reply says so"


def test_vacuity_a_provider_that_declares_send_files_is_told_its_limits(sending):
    """The oracle above rests on the declaration: the same call with it declared carries the limits."""
    sending.answer(attachment=None)
    sending.say("bring me the activities")
    wait_sent(sending)
    assert say_calls(sending)[0][2]["can_send"] == LIMITS


def test_a_profile_that_lost_the_group_since_the_search_sends_no_file_and_the_reply_says_so(sending):
    sending.answer()
    sending.config["channels"] = {"messaging": OPEN_POLICY + ["read-files"]}
    sending.say("bring me the activities")
    [sent] = wait_sent(sending)
    assert "file" not in sent["message"] and sent["message"]["text"] == SAID + "\n\n" + NOT_SENT
    assert sending.gone()


def test_vacuity_the_same_policy_with_both_groups_sends_the_file(sending):
    sending.answer()
    sending.config["channels"] = {"messaging": OPEN_POLICY + ["read-files", "send-files"]}
    sending.say("bring me the activities")
    assert "file" in wait_sent(sending)[0]["message"]


@pytest.mark.parametrize("held", [dict(HELD, data=b"x" * 1001), dict(HELD, kind="photo", data=b"x" * 501), dict(HELD, kind="video"), dict(HELD, data=b"")])
def test_a_file_beyond_the_limits_of_the_app_is_not_handed_to_the_provider(sending, held):
    sending.answer(held)
    sending.say("bring me the activities")
    [sent] = wait_sent(sending)
    assert "file" not in sent["message"] and sent["message"]["text"] == SAID + "\n\n" + NOT_SENT


def test_a_file_that_did_not_arrive_after_the_text_went_out_is_one_plain_sentence(sending):
    (sending.standin / "file_fail.json").write_text("true")
    sending.answer()
    sending.say("bring me the activities")
    first, second = wait_sent(sending, 2)
    assert first["message"]["text"] == SAID and "file" in first["message"]
    assert second["message"]["text"] == NOT_SENT and "file" not in second["message"]
    assert sending.gone()


def test_a_file_the_provider_refused_before_sending_anything_leaves_the_text_alone_and_the_sentence(sending):
    (sending.standin / "file_usage.json").write_text("true")
    sending.answer()
    sending.say("bring me the activities")
    first, second = wait_sent(sending, 2)
    assert first["message"]["text"] == SAID and "file" not in first["message"]
    assert second["message"]["text"] == NOT_SENT
    assert sending.gone(), "the folder is gone although the provider refused"


def test_a_long_reply_carries_the_file_with_its_last_piece_only(sending):
    long = ("palavra " * 700).strip()
    sending.answer(reply=long)
    sending.say("bring me the activities")
    pieces = wait_sent(sending, 2)
    assert ["file" in p["message"] for p in pieces] == [False, True]
    assert "".join(p["message"]["text"] for p in pieces).replace("\n", " ").split() == long.split()


def test_a_reply_with_no_attachment_is_the_reply_it_always_was(sending):
    sending.answer(attachment=None)
    sending.say("bring me the activities")
    [sent] = wait_sent(sending)
    assert sent["message"] == {"text": SAID, "actions": [], "link": None, "document": None}


def test_the_capability_keys_of_sending_default_to_off_and_are_checked(world):
    caps = world.bridge.messenger.capabilities()
    assert (caps["send_files"], caps["max_send_bytes"], caps["max_photo_bytes"], caps["photo_types"], caps["send_types"]) == (False, 0, 0, [], [])
    for bad in ({"send_files": True, "max_send_bytes": -1}, {"max_photo_bytes": -5}, {"photo_types": "png"}, {"send_files": "yes"}):
        world.caps(**bad)
        with pytest.raises(st.load("messaging_provider").MessengerError):
            world.bridge.messenger.capabilities()
    world.caps(**CAPS)
    assert world.bridge.messenger.capabilities()["send_types"] == ["text", "png"]
