"""Tests of the operations of a video that comes from a messaging app (runtime/ops_media_phone.py, package V1d-1): the channel and the group first, the posts
offered, the recording kept from an incoming folder, the start for a post, the reading of a reply to the captions and the run again. The engine is a fake, the
store of recordings and the approval path are the real ones; no messenger is involved and every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_ops_media_phone.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from media_fixtures import body_of, mp4_head, png_head
from media_kit import POST, flag, media, open_items, ops, ops_core, post_text, task_row, to_gate, world  # noqa: F401
import standin_tree as st
from test_attachments import accept

ops_media_phone = st.load("ops_media_phone")
operations = st.load("operations")
attachments = st.load("attachments")
RUNTIME = st.REPO / "runtime"
IDENT, OTHER = "4242424242", "5151515151"
SENDER, STRANGER = f"telegram:{IDENT}", f"telegram:{OTHER}"
CONTENT = Path("docs") / "marketing" / "content"


def configure(world, groups=("read", "answer", "media-phone")):
    """The sender IDENT holds the profile `studio` (with the group `media-phone`), the sender OTHER the channel's `reader`."""
    accept(world["path"], policies={"studio": list(groups), "reader": ["read"]}, channels={"messaging": "reader"},
           messaging={"senders": {"telegram": [{"id": IDENT, "policy": "studio"}, OTHER]}})
    world["engine"]._base = chunked(world["engine"])


def chunked(engine):
    """The fake engine's proposal edit list with two caption chunks, so that the review text has two lines."""
    plain = engine._base

    def base(a):
        out = plain(a)
        if flag(a, "--out").endswith("proposal.edl.json"):
            engine._write(flag(a, "--out"), {"proposals": [], "normalisation": {}, "captions": {"chunks": [[0, 3], [4, 8]]}})
        return out
    return base


def refused(call, *args, **kwargs):
    with pytest.raises(ops_core.OpsError) as caught:
        call(*args, **kwargs)
    return caught.value


def post(world, stem, text=None, age=0):
    path = Path(world["path"]) / CONTENT / f"{stem}.md"
    path.write_text(text if text is not None else post_text(), encoding="utf-8")
    stamp = 1_700_000_000 + age
    os.utime(path, (stamp, stamp))
    return path


def incoming(world, data):
    cfg = ops_core.context(world["path"])["cfg"]
    token, folder = attachments.make_incoming(cfg["data_dir"])
    Path(folder, "content").write_bytes(data)
    return token, folder


def tasks(world) -> int:
    ctx = ops_core.context(world["path"])
    return len(ctx["conn"].execute("SELECT id FROM tasks WHERE key = 'video'").fetchall())


def kit(world):
    """The project path and the calls, as the bridge makes them: the channel messaging and the sender IDENT."""
    configure(world)
    return world["path"]


STEM = POST.rsplit("/", 1)[1][:-3]


def start(world):
    path = kit(world)
    out = ops_media_phone.video_phone_start(path, world["rid"], STEM, channel="messaging", sender=SENDER)
    assert out["stopped"] == "review", out
    return out


# 1. the channel, then the group


def test_limit_69_the_operations_are_the_bridges_and_need_the_group(world):
    path = kit(world)
    assert "media-phone" not in operations.DEFAULT_POLICY["messaging"] and not any("media-phone" in g for g in operations.GRANTS["messaging"])
    calls = [
        lambda ch, who: ops_media_phone.video_phone_posts(path, channel=ch, sender=who),
        lambda ch, who: ops_media_phone.video_phone_in(path, "0" * 16, "telegram", "r1", channel=ch, sender=who),
        lambda ch, who: ops_media_phone.video_phone_start(path, "0" * 16, STEM, channel=ch, sender=who),
        lambda ch, who: ops_media_phone.video_phone_reply(path, 999, "continue", channel=ch, sender=who),
        lambda ch, who: ops_media_phone.video_phone_run(path, 999, channel=ch, sender=who),
    ]
    for call in calls:
        for channel in (None, "terminal", "page"):
            err = refused(call, channel, SENDER)
            assert err.code == 1 and "messaging bridge's call" in str(err), (channel, str(err))
        err = refused(call, "messaging", STRANGER)         # a sender whose profile lacks the group: the guard's own sentence, before anything is read
        assert err.code == 1 and "messaging bridge's call" not in str(err) and str(err)
        err = refused(call, "messaging", None)
        assert err.code == 1
    assert tasks(world) == 0
    assert ops_media_phone.video_phone_posts(path, channel="messaging", sender=SENDER)["posts"] == [STEM]


def test_a_profile_that_lists_the_group_passes_and_one_that_does_not_is_refused(world):
    path = kit(world)
    assert ops_media_phone.video_phone_posts(path, channel="messaging", sender=SENDER)["posts"] == [STEM]
    assert refused(ops_media_phone.video_phone_posts, path, channel="messaging", sender=STRANGER).code == 1


# 2. the posts


def test_the_posts_offered_are_files_with_a_script_and_a_network_newest_first(world):
    path = kit(world)
    post(world, "2027-11-03-northwind", age=500)
    os.utime(Path(path) / POST, (1_700_000_100, 1_700_000_100))
    post(world, "no-script", post_text(script=False), age=900)
    post(world, "no-network", post_text(network=None), age=901)
    post(world, "Bad_Name", age=902)
    (Path(path) / CONTENT / "linked.md").symlink_to(Path(path) / POST)
    (Path(path) / CONTENT / "notes.txt").write_text(post_text(), encoding="utf-8")
    (Path(path) / CONTENT / "binary.md").write_bytes(b"\xff\xfe\x00")
    (Path(path) / "docs" / "marketing" / "outside.md").write_text(post_text(), encoding="utf-8")
    got = ops_media_phone.video_phone_posts(path, channel="messaging", sender=SENDER)
    assert got["posts"] == ["2027-11-03-northwind", STEM], "newest first"
    assert got["max_bytes"] == media.MEDIA_MAX_BYTES and got["free_bytes"] == media.QUOTA_BYTES - media.usage(world["data"])


def test_at_most_ten_posts_are_offered(world):
    path = kit(world)
    for n in range(12):
        post(world, f"post-{n:02d}", age=n)
    got = ops_media_phone.video_phone_posts(path, channel="messaging", sender=SENDER)["posts"]
    assert len(got) == 10 and got[:2] == [STEM, "post-11"] and "post-00" not in got


def test_a_folder_that_is_a_link_out_of_the_project_offers_no_post(world):
    path = kit(world)
    outside = world["tmp"] / "elsewhere"
    outside.mkdir()
    (outside / "x.md").write_text(post_text(), encoding="utf-8")
    folder = Path(path) / CONTENT
    for item in folder.iterdir():
        item.unlink()
    folder.rmdir()
    folder.symlink_to(outside)
    assert ops_media_phone.video_phone_posts(path, channel="messaging", sender=SENDER)["posts"] == []


# 3. the recording


def test_a_recording_in_an_incoming_folder_is_kept_and_the_folder_is_left_to_the_bridge(world):
    path = kit(world)
    token, folder = incoming(world, body_of(mp4_head(), 64))
    got = ops_media_phone.video_phone_in(path, token, "telegram", "r1", channel="messaging", sender=SENDER)
    assert set(got) == {"media", "size", "type"} and got["size"] == 64 and got["type"] == "mp4" and media.ID.fullmatch(got["media"])
    assert str(world["tmp"]) not in str(got) and os.path.isdir(folder), "the bridge removes the incoming folder, not this call"
    assert media.load(world["data"], got["media"])["raw"]["size"] == 64


def test_a_png_is_refused_a_platform_that_is_not_the_senders_is_refused_and_a_removed_folder_is_gone(world):
    path = kit(world)
    token, folder = incoming(world, body_of(png_head(), 64))
    err = refused(ops_media_phone.video_phone_in, path, token, "telegram", "r1", channel="messaging", sender=SENDER)
    assert err.code == 2 and str(err).endswith("(type)")
    token, _ = incoming(world, body_of(mp4_head(), 64))
    assert refused(ops_media_phone.video_phone_in, path, token, "chirp", "r1", channel="messaging", sender=SENDER).code == 2
    assert refused(ops_media_phone.video_phone_in, path, token, "telegram", "", channel="messaging", sender=SENDER).code == 2
    gone = refused(ops_media_phone.video_phone_in, path, "0123456789abcdef", "telegram", "r1", channel="messaging", sender=SENDER)
    assert gone.code == 1 and str(gone) == attachments.GONE.format(platform="telegram")
    assert refused(ops_media_phone.video_phone_in, path, "../x", "telegram", "r1", channel="messaging", sender=SENDER).code == 1


# 4. the start


def test_a_stem_that_is_not_offered_is_refused_and_makes_no_task(world):
    path = kit(world)
    before = tasks(world)
    for bad in ("nothing", "../" + STEM, STEM + ".md", None, 3, ""):
        err = refused(ops_media_phone.video_phone_start, path, world["rid"], bad, channel="messaging", sender=SENDER)
        assert err.code == 2 and "not one of the posts offered" in str(err), bad
    assert tasks(world) == before


def test_a_listed_stem_runs_to_the_review_and_the_answer_carries_the_words(world):
    out = start(world)
    assert out["words"] == "Welcome to Aster Lane\nwhere every small step counts" and out["cut"] is False and out["revision"] == 0
    assert out["started"] is True and len(open_items(world, out["task"])) == 1


def test_a_long_caption_text_is_cut_at_a_line_end(world, monkeypatch):
    configure(world)
    monkeypatch.setattr(ops_media_phone, "WORDS_TEXT_MAX", 30)
    out = ops_media_phone.video_phone_start(world["path"], world["rid"], STEM, channel="messaging", sender=SENDER)
    assert out["words"] == "Welcome to Aster Lane" and out["cut"] is True


# 5. the reply at the review


def test_continue_at_the_review_is_read_and_leaves_the_decision_open(world):
    out = start(world)
    [item] = open_items(world, out["task"])
    got = ops_media_phone.video_phone_reply(world["path"], item["id"], "Continue.", channel="messaging", sender=SENDER)
    assert got == {"action": "continue", "task": out["task"]}
    assert [i["id"] for i in open_items(world, out["task"])] == [item["id"]]


def test_a_correction_at_the_review_changes_the_word_and_a_missing_word_changes_nothing(world):
    out = start(world)
    [item] = open_items(world, out["task"])
    got = ops_media_phone.video_phone_reply(world["path"], item["id"], "Aster -> Astor", channel="messaging", sender=SENDER)
    assert got["action"] == "edited" and got["mode"] == "review" and got["run"] is False and got["answered"] is None and got["task"] == out["task"]
    assert got["words"] == "Welcome to Astor Lane\nwhere every small step counts" and got["revision"] == 1
    assert ops.captions_read(world["path"], out["task"])["view"]["words"][2]["text"] == "Astor"
    lost = ops_media_phone.video_phone_reply(world["path"], item["id"], "Nothing -> x", channel="messaging", sender=SENDER)
    assert lost == {"action": "not_found", "wrong": "Nothing"}
    assert ops.captions_read(world["path"], out["task"])["view"]["revision"] == 1, "a refused correction changes nothing"
    clash = refused(ops_media_phone.video_phone_reply, world["path"], item["id"], "Welcome -> Hello\nWelcome -> Hi", channel="messaging", sender=SENDER)
    assert clash.code == 1 and "overlapping_edits" in str(clash)
    assert ops.captions_read(world["path"], out["task"])["view"]["revision"] == 1
    assert [i["id"] for i in open_items(world, out["task"])] == [item["id"]]


def test_a_word_that_appears_twice_is_ambiguous_and_an_unreadable_reply_is_unknown(world):
    out = start(world)
    [item] = open_items(world, out["task"])
    edited = ops_media_phone.video_phone_reply(world["path"], item["id"], "to -> Lane", channel="messaging", sender=SENDER)
    assert edited["action"] == "edited"
    ambiguous = ops_media_phone.video_phone_reply(world["path"], item["id"], "Lane -> x", channel="messaging", sender=SENDER)
    assert ambiguous == {"action": "ambiguous", "wrong": "Lane"}
    unknown = ops_media_phone.video_phone_reply(world["path"], item["id"], "what is this", channel="messaging", sender=SENDER)
    assert unknown == {"action": "unknown"}
    assert ops_media_phone.video_phone_reply(world["path"], item["id"], None, channel="messaging", sender=SENDER) == {"action": "unknown"}


def test_a_reply_to_a_decision_that_is_not_a_video_or_is_closed_is_not_a_video(world):
    out = start(world)
    [item] = open_items(world, out["task"])
    assert ops_media_phone.video_phone_reply(world["path"], 99999, "continue", channel="messaging", sender=SENDER) == {"action": "not-video"}
    ops.answer(world["path"], item["id"], "continue")
    assert ops_media_phone.video_phone_reply(world["path"], item["id"], "Aster -> Astor", channel="messaging", sender=SENDER) == {"action": "not-video"}


def test_a_question_of_another_step_is_not_a_video(world):
    out = start(world)
    [item] = open_items(world, out["task"])
    ctx = ops_core.context(world["path"])
    ctx["conn"].execute("UPDATE pending_decisions SET payload = ? WHERE id = ?", ('{"step": {"kind": "media", "step": "base"}}', item["id"]))
    ctx["conn"].commit()
    assert ops_media_phone.video_phone_reply(world["path"], item["id"], "continue", channel="messaging", sender=SENDER) == {"action": "not-video"}


# 6. the reply at the gate and the run


def test_continue_at_the_gate_is_unknown_and_a_correction_there_renders_again_and_asks_again(world):
    configure(world)
    task, gate = to_gate(world)
    unknown = ops_media_phone.video_phone_reply(world["path"], gate["id"], "continue", channel="messaging", sender=SENDER)
    assert unknown == {"action": "unknown"} and [i["id"] for i in open_items(world, task)] == [gate["id"]]
    got = ops_media_phone.video_phone_reply(world["path"], gate["id"], "Aster -> Astor", channel="messaging", sender=SENDER)
    assert got["action"] == "edited" and got["mode"] == "gate" and got["run"] is True and got["answered"] == gate["id"]
    assert got["words"].startswith("Welcome to Astor Lane")
    assert open_items(world, task) == [] and task_row(world, task)["state"] == "ready"
    world["engine"].salt = b"two"
    out = ops_media_phone.video_phone_run(world["path"], task, channel="messaging", sender=SENDER)
    assert out["ok"] is True and out["stopped"] == "deliver"
    [new] = open_items(world, task)
    assert new["id"] != gate["id"] and new["payload_sha256"] != gate["payload_sha256"]


def test_run_after_the_review_was_answered_goes_to_the_delivery_decision(world):
    out = start(world)
    [item] = open_items(world, out["task"])
    ops.answer(world["path"], item["id"], "continue")
    done = ops_media_phone.video_phone_run(world["path"], out["task"], channel="messaging", sender=SENDER)
    assert done["ok"] is True and done["stopped"] == "deliver" and "words" not in done


def test_the_modules_start_on_their_own():
    flags = ["--help"]
    done = subprocess.run([sys.executable, "-I", str(RUNTIME / "ops_media_phone.py"), *flags], capture_output=True, text=True, timeout=60, env={})
    assert done.returncode == 0 and "messaging bridge" in done.stdout
    other = ["--nope"]
    assert subprocess.run([sys.executable, "-I", str(RUNTIME / "ops_media_phone.py"), *other], capture_output=True, text=True, timeout=60, env={}).returncode == 2


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
