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
SAID = "Atividades (OneDrive, pasta Documentos):\n\nSegunda: ensaio do coral."
NOT_SENT = "The file did not arrive. Try again in a few minutes."
RIGHT = "I did not send the file: what you may receive here changed after you asked."


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


def test_a_profile_that_lost_the_group_since_the_search_sends_no_file_and_the_reply_says_the_right_changed(sending):
    sending.answer()
    sending.config["channels"] = {"messaging": OPEN_POLICY + ["read-files"]}
    sending.say("bring me the activities")
    [sent] = wait_sent(sending)
    assert "file" not in sent["message"] and sent["message"]["text"] == SAID + "\n\n" + RIGHT
    assert sending.gone()


def test_a_profile_that_lost_the_right_to_read_files_since_the_search_gets_neither_the_file_nor_the_text_found(sending):
    sending.answer()
    sending.config["channels"] = {"messaging": OPEN_POLICY + ["send-files"]}
    sending.say("bring me the activities")
    [sent] = wait_sent(sending)
    assert "file" not in sent["message"] and sent["message"]["text"] == RIGHT, "the preview of a file the sender may no longer read is not sent"
    assert "ensaio" not in json.dumps(sent["message"])


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


def test_a_send_with_a_file_gets_a_longer_time_than_the_providers_own_calls_and_one_without_keeps_its_time(world, monkeypatch):
    providers = st.load("messaging_provider")
    seen = []
    monkeypatch.setattr(providers.Messenger, "_call", lambda self, verb, args, timeout=providers.SEND_SECONDS: seen.append(timeout) or {"message_id": "1"})
    messenger = world.bridge.messenger
    messenger.send("4242", {"text": "a", "actions": [], "link": None, "document": None})
    messenger.send("4242", {"text": "a", "actions": [], "link": None, "document": None, "file": {"name": "a", "kind": "document", "path": "/x"}})
    assert seen == [60, 180]
    assert 30 * 4 < seen[1], "the bridge outlasts four calls of Telegram's 30 s each"


def test_a_send_that_ran_over_its_time_after_the_text_may_have_gone_says_the_file_did_not_arrive_and_sends_the_text_no_second_time(sending, monkeypatch):
    real = sending.bridge.messenger.send

    def slow(chat, message):
        if message.get("file"):
            raise st.load("messaging_provider").MessengerError("timeout", "the provider ran over 180 s")
        return real(chat, message)
    monkeypatch.setattr(sending.bridge.messenger, "send", slow)
    sending.answer()
    sending.say("bring me the activities")
    [only] = wait_sent(sending)
    assert only["message"]["text"] == NOT_SENT and "file" not in only["message"], "the sentence only: the text is not sent again (it may be in the chat already)"
    assert sending.gone()
    assert wait_for(lambda: any("ran over the time" in line for line in sending.log), 5) and all("activities" not in line and "coral" not in line for line in sending.log)


def test_vacuity_a_send_of_the_same_reply_that_does_not_time_out_sends_the_text_once_with_the_file(sending):
    sending.answer()
    sending.say("bring me the activities")
    [sent] = wait_sent(sending)
    assert sent["message"]["text"] == SAID and "file" in sent["message"]


def test_the_sweep_removes_only_old_folders_of_its_own_prefix_owned_by_the_user_with_mode_0700(tmp_path, monkeypatch):
    sendfile = st.load("messaging_file")
    monkeypatch.setattr(sendfile.tempfile, "tempdir", str(tmp_path))
    now = 1_000_000.0

    def folder(name, age, mode=0o700):
        path = tmp_path / name
        path.mkdir()
        (path / "content").write_bytes(b"x")
        path.chmod(mode)
        os.utime(path, (now - age, now - age))
        return path
    old, young = folder("messenger-file-old", 7200), folder("messenger-file-young", 600)
    loose, other, near = folder("messenger-file-loose", 7200, 0o755), folder("messenger-other-old", 7200), folder("somebody-messenger-file-old", 7200)
    link_target = tmp_path / "target"
    link_target.mkdir()
    (link_target / "keep").write_bytes(b"k")
    os.utime(link_target, (now - 7200, now - 7200))
    (tmp_path / "messenger-file-link").symlink_to(link_target)
    plain = tmp_path / "messenger-file-plain"
    plain.write_bytes(b"not a folder")
    assert sendfile.sweep(now=now) == 1
    assert not old.exists()
    assert all(p.exists() for p in (young, loose, other, near, link_target / "keep", plain)) and (tmp_path / "messenger-file-link").is_symlink()
    young.chmod(0o700)
    assert sendfile.sweep(now=now + 3600) == 1 and not young.exists(), "an hour later the young one is old"


def test_vacuity_a_sweep_that_took_any_folder_of_the_prefix_would_remove_the_loose_one(tmp_path, monkeypatch):
    sendfile = st.load("messaging_file")
    monkeypatch.setattr(sendfile.tempfile, "tempdir", str(tmp_path))
    loose = tmp_path / "messenger-file-loose"
    loose.mkdir()
    loose.chmod(0o755)
    os.utime(loose, (1, 1))
    assert sendfile.sweep(now=10 ** 7) == 0 and loose.exists()
    loose.chmod(0o700)
    assert sendfile.sweep(now=10 ** 7) == 1 and not loose.exists()


def test_the_bridge_sweeps_when_it_starts(world, monkeypatch):
    called = []
    monkeypatch.setattr(st.load("messaging_file"), "sweep", lambda *a, **k: called.append(1) or 0)
    stop = __import__("threading").Event()
    stop.set()
    world.bridge.loop(stop, 1.0, poll=1)
    assert called == [1]
