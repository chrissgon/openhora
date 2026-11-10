"""The messaging bridge and a video a listed sender sends (runtime/messaging_video.py, package V1d-1): the claim by the sender's profile, the bound checked before
anything is fetched, the fetch through a stand-in messenger provider, the choice of the post, the caption words sent back, a correction and `continue` as replies
to the cards, and the language. The operations layer is the real one over a real store of recordings; the video engine is a fake; the messenger is the stand-in of
the attachment tests. Offline, no model, no network; every name and id is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_messaging_video.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import phrase_kit as pk
import standin_tree as st
from media_fixtures import body_of, mp4_head
from media_kit import POST, flag, open_items, ops_core, post_text, task_row, world as media_world  # noqa: F401
from test_attachments import accept
from test_messaging_attach import CAPS, make_world
from test_service import WAIT

attachments = st.load("attachments")
phrases = st.load("phrases")
messaging_video = st.load("messaging_video")
IDENT, OTHER = "4242424242", "5151515151"
STEM = POST.rsplit("/", 1)[1][:-3]
SECOND = "2027-11-03-northwind"
MIB = 1024 * 1024
LATER = "2026-10-17T12:00:01+00:00"


def chunked(engine):
    plain = engine._base

    def base(a):
        out = plain(a)
        if flag(a, "--out").endswith("proposal.edl.json"):
            engine._write(flag(a, "--out"), {"proposals": [], "normalisation": {}, "captions": {"chunks": [[0, 3], [4, 8]]}})
        return out
    return base


@pytest.fixture
def phone(media_world, monkeypatch):
    """The real bridge over the stand-in messenger, on the project of the media kit: IDENT's profile holds `media-phone`, OTHER's holds `add-sources` only."""
    path = media_world["path"]
    case = SimpleNamespace(tmp=media_world["tmp"], path=path, data=Path(media_world["data"]),
                           tree=lambda base: sorted(str(p.relative_to(base)) for p in Path(base).rglob("*")))
    w = make_world(case, monkeypatch)
    accept(path, policies={"studio": ["read", "answer", "media-phone"], "desk": ["read", "add-sources"]}, channels={"messaging": "desk"},
           messaging={"senders": {"telegram": [{"id": IDENT, "policy": "studio"}, {"id": OTHER, "policy": "desk"}]}})
    media_world["engine"]._base = chunked(media_world["engine"])
    w.world, w.calls = media_world, []
    real = w.bridge.run_op

    def spy(project, op, *args, **kwargs):
        w.calls.append(op)
        return real(project, op, *args, **kwargs)
    w.bridge.run_op = spy
    w.put("v1", body_of(mp4_head(), 64))
    w.video_file = lambda ref="v1", size=64, kind="video/mp4", name="take.mp4": w.file(ref, name, size, kind)

    def reply(text, to, sender=IDENT):
        w.bridge.handle({"update_id": next(w.counter), "sender": sender, "chat": sender, "private": True, "text": text, "action": None, "action_ref": None,
                         "reply_to": to})
        w.settle()

    def card_of(task):
        w.bridge.notify_project(w.project, only_chat=IDENT)
        w.settle()
        return str(100 + len(w.sent()))
    w.reply, w.card_of = reply, card_of

    def settle():
        """Every job and the jobs they start (the fetch starts the video's job from its own thread)."""
        for _ in range(100):
            alive = [t for t in list(w.bridge.threads) if t.is_alive()]
            if not alive:
                return
            for thread in alive:
                thread.join(WAIT)
    w.settle = settle
    yield w
    w.bridge.stopping.set()
    for thread in list(w.bridge.threads):
        thread.join(WAIT)


def keys(w):
    return [pk.which(text)[0] for text in w.texts()]


def second_post(w, newer=True):
    path = Path(w.world["path"]) / "docs" / "marketing" / "content" / f"{SECOND}.md"
    path.write_text(post_text(), encoding="utf-8")
    stamp = os.stat(Path(w.world["path"]) / POST).st_mtime + (100 if newer else -100)
    os.utime(path, (stamp, stamp))


def video_task(w) -> int:
    """The id of the one step task the video made."""
    ctx = ops_core.context(w.world["path"])
    [row] = ctx["conn"].execute("SELECT id FROM tasks WHERE key = 'video'").fetchall()
    return row[0]


def review_task(w):
    """A video sent with the post's name as its caption, run to the caption review: its task and the open review question."""
    w.send([w.video_file()], text=STEM)
    task = video_task(w)
    [item] = open_items(w.world, task)
    assert item["kind"] == "question", w.texts()
    return task, item


# 1. the claim, the limits and the refusals before a byte


def test_limit_69_a_recording_is_fetched_only_within_the_bound_for_a_sender_with_the_group_and_never_over_it(phone):
    w = phone
    w.send([w.video_file()], sender=OTHER)                      # a profile with no `media-phone`: the old refusal, and nothing fetched
    assert w.fetches() == [] and keys(w) == ["ATT_MEDIA"] and w.bridge.video.held == {}
    w.reset()
    w.send([w.video_file(size=30 * MIB, name="big.mp4")])        # over the app's file limit (20 MiB here): said, and nothing fetched
    assert w.fetches() == [] and keys(w) == ["VID_TOO_BIG"]
    w.reset()
    w.send([w.video_file()], text=STEM)                          # within the bound, for the sender with the group: fetched once
    assert len(w.fetches()) == 1 and w.fetches()[0]["max_bytes"] == 20 * MIB
    assert w.calls[:2] == ["video-phone-in", "video-phone-start"] and w.incoming() == []


def test_a_video_from_a_sender_without_the_group_is_refused_as_before_and_videos_says_nothing(phone):
    w = phone
    spoke = []
    real = messaging_video.Videos._say
    messaging_video.Videos._say = lambda self, *a, **k: spoke.append(a)
    try:
        w.send([w.video_file()], sender=OTHER)
        assert not w.bridge.video.claims(w.project, OTHER, {"kind": "attachment", "attachments": [w.video_file()], "text": None})
    finally:
        messaging_video.Videos._say = real
    assert spoke == [] and w.fetches() == []
    texts = w.texts()
    assert len(texts) == 1
    pk.assert_said(texts[0], "ATT_MEDIA")


def test_two_attachments_or_a_file_that_is_not_a_video_are_not_claimed(phone):
    w = phone
    intent = {"kind": "attachment", "text": None}
    assert w.bridge.video.claims(w.project, IDENT, {**intent, "attachments": [w.video_file()]})
    assert w.bridge.video.claims(w.project, IDENT, {**intent, "attachments": [w.video_file(kind="video")]})
    assert not w.bridge.video.claims(w.project, IDENT, {**intent, "attachments": [w.video_file(), w.video_file("v2")]})
    assert not w.bridge.video.claims(w.project, IDENT, {**intent, "attachments": [w.video_file(kind="application/pdf", name="a.pdf")]})
    assert not w.bridge.video.claims(w.project, IDENT, {**intent, "attachments": []})


def test_a_video_over_the_providers_limit_says_both_sizes_and_the_provider_fetches_nothing(phone):
    w = phone
    w.send([w.video_file(size=30 * MIB, name="big.mp4")])
    [text] = w.texts()
    pk.assert_said(text, "VID_TOO_BIG", size="30.0 MiB", cap="20.0 MiB")
    assert w.fetches() == [] and w.calls == [] and w.bridge.video.held == {}


def test_no_post_ready_says_so_and_fetches_nothing(phone):
    w = phone
    os.remove(Path(w.world["path"]) / POST)
    w.send([w.video_file()])
    assert keys(w) == ["VID_NO_POST"] and w.fetches() == []


# 2. the fetch and the post


def test_a_video_whose_caption_is_a_posts_name_is_fetched_started_and_its_words_are_sent(phone):
    w = phone
    w.send([w.video_file()], text=STEM)
    assert keys(w) == ["VID_FETCHING", "VID_RECEIVED", "VID_REVIEW_WORDS"]
    pk.assert_said(w.texts()[1], "VID_RECEIVED", size="64 bytes")
    assert "Welcome to Aster Lane\nwhere every small step counts" in w.texts()[2]
    assert w.calls[:2] == ["video-phone-in", "video-phone-start"]
    assert w.incoming() == [] and len(w.fetches()) == 1 and w.fetches()[0]["max_bytes"] == 20 * MIB
    assert w.world["engine"].of("transcribe"), "the video ran to the review"


def test_a_video_with_no_caption_gets_the_list_and_a_number_starts_the_post(phone):
    w = phone
    second_post(w)
    w.send([w.video_file()])
    assert keys(w) == ["VID_FETCHING", "VID_RECEIVED", "VID_PICK_POST"]
    pk.assert_said(w.texts()[2], "VID_PICK_POST", list=f"1. {SECOND}\n2. {STEM}")
    assert "video-phone-start" not in w.calls
    w.say("9")
    assert keys(w)[-1] == "VID_POST_GONE" and "video-phone-start" not in w.calls
    pk.assert_said(w.texts()[-1], "VID_POST_GONE", n=2)
    w.say("2")
    assert keys(w)[-1] == "VID_REVIEW_WORDS" and w.calls[-1] == "video-phone-start" and w.bridge.video.held == {}
    assert task_row(w.world, video_task(w))["step_args"]["post"].endswith(STEM + ".md")


def test_the_exact_name_of_a_post_chooses_it_and_any_other_line_leaves_the_recording_waiting(phone):
    w = phone
    second_post(w)
    w.send([w.video_file()])
    assert w.bridge.video.line(w.project, IDENT, "what is this?") is False and IDENT in w.bridge.video.held
    w.say(SECOND)
    assert keys(w)[-1] == "VID_REVIEW_WORDS" and task_row(w.world, video_task(w))["step_args"]["post"].endswith(SECOND + ".md")


def test_a_recording_waiting_for_its_post_expires_after_an_hour(phone):
    w = phone
    second_post(w)
    w.send([w.video_file()])
    assert IDENT in w.bridge.video.held
    w.bridge.clock = lambda: LATER
    assert w.bridge.video.line(w.project, IDENT, "2") is False and w.bridge.video.held == {}
    assert "video-phone-start" not in w.calls


def test_a_busy_fetch_lock_and_a_provider_error_are_told_and_leave_no_incoming_folder(phone):
    w = phone
    lock = attachments.fetch_lock(str(w.world["data"]))
    try:
        w.send([w.video_file()], text=STEM)
    finally:
        lock.release()
    assert keys(w)[-1] == "ATT_BUSY" and w.incoming() == [] and "video-phone-in" not in w.calls
    w.reset()
    w.flag("fail.json", ["v1"])
    w.send([w.video_file()], text=STEM)
    assert keys(w)[-1] == "ATT_FETCH_FAILED" and w.incoming() == [] and "video-phone-in" not in w.calls
    w.reset()
    w.flag("fail.json", [])
    w.flag("lie.json", ["v1"])                                  # a provider that leaves more than it said is not taken at its word
    w.send([w.video_file()], text=STEM)
    assert keys(w)[-1] == "ATT_FETCH_FAILED" and w.incoming() == [] and "video-phone-in" not in w.calls


def test_a_file_the_store_refuses_is_told_in_the_operations_own_sentence(phone):
    w = phone
    w.put("v2", b"\x89PNG\r\n\x1a\n" + b"\x00" * 56)           # declared as a video, but the bytes are a picture
    w.send([w.video_file("v2")], text=STEM)
    assert keys(w)[0] == "VID_FETCHING" and w.texts()[-1].endswith("(type)") and "VID_RECEIVED" not in keys(w)
    assert w.incoming() == [] and "video-phone-start" not in w.calls


# 3. the replies to the cards


def test_continue_as_a_reply_to_the_review_card_answers_it_and_runs_the_video(phone):
    w = phone
    task, item = review_task(w)
    card = w.card_of(task)
    w.reply("continue", card)
    assert w.calls[-3:] == ["video-phone-reply", "answer", "video-phone-run"]
    assert "VID_RENDERING" in keys(w)
    [gate] = open_items(w.world, task)
    assert gate["kind"] == "effect" and gate["id"] != item["id"], "the video went on to the delivery decision"


def test_a_correction_as_a_reply_to_the_review_card_changes_the_words_and_sends_them(phone):
    w = phone
    task, item = review_task(w)
    card = w.card_of(task)
    w.reply("Aster -> Astor", card)
    assert keys(w)[-1] == "VID_EDITED" and "Welcome to Astor Lane\nwhere every small step counts" in w.texts()[-1]
    assert [i["id"] for i in open_items(w.world, task)] == [item["id"]], "the review is still open"
    w.reply("Nothing -> x", card)
    assert keys(w)[-1] == "VID_NOT_FOUND"
    pk.assert_said(w.texts()[-1], "VID_NOT_FOUND", wrong="Nothing")
    w.reply("to -> Lane", card)
    w.reply("Lane -> x", card)
    assert keys(w)[-1] == "VID_AMBIGUOUS"
    w.reply("what is this", card)
    assert keys(w)[-1] == "VID_HOW"


def test_a_correction_as_a_reply_to_the_delivery_card_renders_again(phone):
    w = phone
    task, item = review_task(w)
    w.reply("continue", w.card_of(task))
    [gate] = open_items(w.world, task)
    card = w.card_of(task)
    assert "Deliver the video" in w.texts()[-1], "the delivery card was sent to the sender"
    w.world["engine"].salt = b"two"
    w.reply("Aster -> Astor", card)
    assert "VID_EDITED_GATE" in keys(w) and w.calls[-1] == "video-phone-run"
    [new] = open_items(w.world, task)
    assert new["id"] != gate["id"] and new["payload_sha256"] != gate["payload_sha256"]
    ctx = ops_core.context(w.world["path"])
    assert ctx["store"].pending_get(ctx["conn"], gate["id"])["resolution"] == "answered"


def test_continue_at_the_delivery_card_is_how_not_an_approval(phone):
    w = phone
    task, item = review_task(w)
    w.reply("continue", w.card_of(task))
    [gate] = open_items(w.world, task)
    card = w.card_of(task)
    w.reply("continue", card)
    assert keys(w)[-1] == "VID_HOW" and [i["id"] for i in open_items(w.world, task)] == [gate["id"]]


def test_a_reply_to_a_card_that_is_not_a_video_is_left_to_the_old_path(phone):
    w = phone
    card = {"pending_id": 99999, "kind": "question", "project": w.project["id"]}
    before = len(w.sent())
    assert w.bridge.video.replied(w.project, IDENT, card, "continue") is False
    assert len(w.sent()) == before
    assert w.bridge.video.replied(w.project, OTHER, {**card, "pending_id": 1}, "continue") is False, "a sender without the group is not read"


# 4. the language


def test_a_project_in_portuguese_gets_the_portuguese_sentences(phone):
    w = phone
    accept(w.world["path"], language="pt-BR")
    second_post(w)
    w.send([w.video_file()])
    assert w.texts()[-1] == phrases.text("VID_PICK_POST", {"language": "pt-BR"}, list=f"1. {SECOND}\n2. {STEM}")
    assert w.texts()[-1] != phrases.text("VID_PICK_POST", {"language": "en"}, list=f"1. {SECOND}\n2. {STEM}")


def test_the_module_starts_on_its_own():
    import subprocess
    flags = ["--help"]
    done = subprocess.run([sys.executable, "-I", str(st.RUNTIME / "messaging_video.py"), *flags], capture_output=True, text=True, timeout=60, env={})
    assert done.returncode == 0 and "media-phone" in done.stdout
    other = ["--nope"]
    assert subprocess.run([sys.executable, "-I", str(st.RUNTIME / "messaging_video.py"), *other], capture_output=True, text=True, timeout=60, env={}).returncode == 2


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
