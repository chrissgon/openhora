"""The card, the approval of the exact file and caption, and sending a video back (runtime/ops_video.py, runtime/video.py), through the
terminal and the operations layer: what the approval binds (the file's sha256, the caption's sha256, the platform, the date), what
invalidates it (a re-render, a caption edit), what it refuses (the wrong hash, a changed caption, a post that is not open, a channel that
may not approve), and that nothing in it publishes or schedules. A rendered video is a file of video_fixtures.py: no ffmpeg, no model.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_video_ops.py
"""
from __future__ import annotations

import datetime
import json
import os
import re

import pytest

import standin_tree as st
from video_fixtures import CAPTION, POST, caption_sha, mp4_bytes, world, write_post, write_render  # noqa: F401

ops = st.load("ops")
ops_video = st.load("ops_video")
cli = st.load("cli")
media = st.load("media")
video = st.load("video")
operations = st.load("operations")


@pytest.fixture
def one(world):
    return write_render(world.data, world.rid, "one")


def card(world, **kw):
    return ops.video_card(world.project, world.rid, **kw)


def approve(world, sha, caption=CAPTION, channel="page", **kw):
    return ops.video_approve(world.project, world.rid, sha, caption_sha(caption), channel=channel, **kw)


def refused(call, *args, **kwargs):
    with pytest.raises(ops.OpsError) as caught:
        call(*args, **kwargs)
    return caught.value


# --- the card ---------------------------------------------------------------------------------------------------------------------------------


def test_the_card_shows_the_render_the_cover_the_caption_and_its_hash_and_no_approval_yet(world, one):
    shown = card(world)
    assert shown["recording"] == world.rid and shown["platform"] == "instagram" and shown["platforms"] == ["instagram"] and shown["status"] == "open"
    assert shown["render"]["sha256"] == one["sha"] and shown["render"]["source"] == "result" and shown["render"]["bytes"] == len(one["bytes"])
    assert (shown["render"]["duration"], shown["render"]["width"], shown["render"]["height"], shown["render"]["fps"]) == (41.5, 1080, 1920, 30)
    assert shown["render"]["name"] == f"render-{one['sha'][:12]}.mp4" and shown["render"]["codec"] == "h264"
    assert shown["cover"]["offset_ms"] == 1200 and shown["cover"]["bytes"] == len(one["cover"])
    assert shown["caption"] == {"text": CAPTION, "sha256": caption_sha(), "chars": len(CAPTION), "post_file": POST}
    assert shown["approval"] is None and shown["sent_back"] is None and shown["can_download"] is False and shown["download_name"] is None
    assert shown["problems"] == []


def test_the_card_names_the_render_by_the_pipelines_result_and_not_by_the_folder_and_falls_back_to_the_newest_file(world, one):
    newer = write_render(world.data, world.rid, "newer", result=False, cover=False)
    os.utime(newer["path"], (os.stat(one["path"]).st_mtime + 100,) * 2)
    assert card(world)["render"]["sha256"] == one["sha"], "render.json names the current render"
    os.unlink(os.path.join(world.folder, "render.json"))
    fallback = card(world)
    assert fallback["render"]["sha256"] == newer["sha"] and fallback["render"]["source"] == "folder" and fallback["cover"] is None
    assert fallback["render"]["duration"] is None


def test_the_card_says_so_with_no_render_no_post_block_or_several_posts(world):
    empty = card(world)
    assert empty["render"] is None and "there is no render yet" in empty["problems"]
    write_render(world.data, world.rid, "one")
    with open(os.path.join(world.project, POST), "w", encoding="utf-8") as f:
        f.write("# no caption block here\n")
    assert card(world)["caption"] is None and any("```post" in p for p in card(world)["problems"])
    write_post(world.project)
    media.link_posts(world.data, world.rid, {"tiktok": POST})
    many = card(world)
    assert many["platform"] is None and many["platforms"] == ["instagram", "tiktok"] and any("name the platform" in p for p in many["problems"])
    assert card(world, platform="tiktok")["platform"] == "tiktok"
    assert refused(ops.video_card, world.project, world.rid, platform="mastodon").code == 1
    assert refused(ops.video_card, world.project, "not-an-id").code == 2


def test_a_result_file_with_a_wrong_shape_is_ignored_and_never_trusted_for_a_path(world, one):
    with open(os.path.join(world.folder, "render.json"), "w", encoding="utf-8") as f:
        json.dump({"sha256": one["sha"], "path": "/etc/passwd", "output": {"width": "<script>", "codec": "x" * 500, "bytes": -4}, "cover": "no"}, f)
    shown = card(world)
    assert shown["render"]["sha256"] == one["sha"] and shown["render"]["width"] is None and shown["render"]["codec"] is None
    assert shown["render"]["bytes"] == len(one["bytes"]) and shown["cover"]["offset_ms"] is None
    assert "/etc/passwd" not in json.dumps(shown)
    with open(os.path.join(world.folder, "render.json"), "w", encoding="utf-8") as f:
        f.write("{not json")
    assert card(world)["render"]["sha256"] == one["sha"], "an unreadable result falls back to the folder"
    with open(os.path.join(world.folder, "render.json"), "w", encoding="utf-8") as f:
        json.dump({"sha256": "ab" * 32}, f)
    named = card(world)
    assert named["render"] is None and any("cannot be served" in p for p in named["problems"])


# --- the approval -------------------------------------------------------------------------------------------------------------------------------


def test_the_approval_binds_the_files_hash_the_captions_hash_the_platform_and_the_date(world, one):
    before = datetime.datetime.now(datetime.timezone.utc)
    done = approve(world, one["sha"])
    after = datetime.datetime.now(datetime.timezone.utc)
    approval = done["approval"]
    assert approval["state"] == "approved" and approval["reasons"] == [] and approval["platform"] == "instagram"
    assert approval["video_sha256"] == one["sha"] and approval["caption_sha256"] == caption_sha() and approval["caption"] == CAPTION
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", approval["approved_at"])
    stamped = media.parse_stamp(approval["approved_at"])
    assert before - datetime.timedelta(seconds=2) <= stamped <= after + datetime.timedelta(seconds=2), "the date comes from the clock, not from the caller"
    assert approval["approved_via"] == "page" and done["can_download"] is True and done["download_name"] == f"short-video-instagram-{one['sha'][:12]}.mp4"
    record = media.load(world.data, world.rid)
    assert record["approvals"]["instagram"] == {"video_sha256": one["sha"], "video_bytes": len(one["bytes"]), "caption_sha256": caption_sha(),
                                                "caption": CAPTION, "platform": "instagram", "approved_at": approval["approved_at"], "approved_via": "page"}
    assert [e["event"] for e in record["approval_log"]] == ["approved"]
    assert record["status"] == "open", "approving schedules nothing, publishes nothing and changes the post's status in no way"
    assert "effects" not in record and not os.path.exists(os.path.join(world.data, "effects"))


def test_a_caption_edit_invalidates_the_approval_and_putting_the_text_back_restores_it(world, one):
    approve(world, one["sha"])
    write_post(world.project, CAPTION + "!")
    stale = card(world)
    assert stale["approval"]["state"] == "stale" and stale["approval"]["reasons"] == ["caption_changed"] and stale["can_download"] is False
    assert stale["caption"]["sha256"] == caption_sha(CAPTION + "!") and stale["approval"]["caption_sha256"] == caption_sha()
    write_post(world.project)
    assert card(world)["approval"]["state"] == "approved"


def test_a_re_render_invalidates_the_approval(world, one):
    approve(world, one["sha"])
    second = write_render(world.data, world.rid, "two")
    stale = card(world)
    assert stale["render"]["sha256"] == second["sha"] and stale["approval"]["state"] == "stale"
    assert stale["approval"]["reasons"] == ["render_changed"] and stale["can_download"] is False
    assert stale["approval"]["video_sha256"] == one["sha"], "the card still says which file was approved"
    # approving the new render replaces the approval
    fresh = approve(world, second["sha"])
    assert fresh["approval"]["state"] == "approved" and fresh["approval"]["video_sha256"] == second["sha"]
    assert [e["event"] for e in media.load(world.data, world.rid)["approval_log"]] == ["approved", "approved"]


def test_both_hashes_and_the_current_render_are_required_and_nothing_is_recorded_on_a_refusal(world, one):
    other = write_render(world.data, world.rid, "two")                                      # the current render is now `two`
    assert "changed since you watched" in str(refused(approve, world, one["sha"]))          # the person watched `one`
    assert "caption changed" in str(refused(approve, world, other["sha"], caption=CAPTION + " x"))
    for bad in ("", "xyz", "AB" * 32, "ab" * 31, None, 7):
        assert refused(ops.video_approve, world.project, world.rid, bad, caption_sha(), channel="page").code == 2, bad
        assert refused(ops.video_approve, world.project, world.rid, other["sha"], bad, channel="page").code == 2, bad
    assert refused(ops.video_approve, world.project, "f" * 16, other["sha"], caption_sha(), channel="page").code == 1
    assert refused(ops.video_approve, world.project, world.rid, other["sha"], caption_sha(), platform="tiktok", channel="page").code == 1
    assert not media.load(world.data, world.rid).get("approvals")


def test_the_file_is_hashed_again_at_the_approval_so_a_file_that_is_not_its_hash_is_never_approved(world, one):
    ops.video_card(world.project, world.rid)                                                # warm: the digest is remembered for the file
    os.chmod(one["path"], 0o600)
    with open(one["path"], "r+b") as f:
        f.seek(7000)
        f.write(b"changed under the page")
    error = refused(approve, world, one["sha"])
    assert "sha256" in str(error) and not media.load(world.data, world.rid).get("approvals")


def test_the_approval_never_reads_the_digest_kept_for_a_file_even_when_that_digest_is_forged(world, one):
    os.chmod(one["path"], 0o600)
    with open(one["path"], "r+b") as f:
        f.seek(9000)
        f.write(b"different bytes")
    info = os.stat(one["path"])
    key = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
    video._VERIFIED[key] = one["sha"]                         # a remembered digest that says the changed file is the right one
    served = video.open_render(world.data, world.rid, one["sha"])        # a range request would trust it ...
    served.close()
    assert "sha256" in str(refused(approve, world, one["sha"]))          # ... the approval does not
    assert not media.load(world.data, world.rid).get("approvals")


def test_there_is_nothing_to_approve_without_a_render_and_a_post_that_is_not_open_takes_no_approval(world, one):
    empty = media.create(world.data, posts={"instagram": POST})["id"]
    assert "no render" in str(refused(ops.video_approve, world.project, empty, one["sha"], caption_sha(), channel="page"))
    media.mark(world.data, world.rid, "scheduled")
    assert "scheduled" in str(refused(approve, world, one["sha"]))
    assert not media.load(world.data, world.rid).get("approvals")
    media.mark(world.data, world.rid, "open")
    assert approve(world, one["sha"])["approval"]["state"] == "approved"


def test_only_the_terminal_and_the_page_can_approve_and_the_code_says_so_whatever_the_table_says(world, one):
    for channel in ("mcp", "messaging", "chat", "", None, "page "):
        assert "terminal or the local page" in str(refused(approve, world, one["sha"], channel=channel)), channel
    assert not media.load(world.data, world.rid).get("approvals")
    for name in ("video-approve", "video-send-back", "video-card"):
        channels = operations.by_name(name)["channels"]
        assert not {"mcp", "messaging", "chat"} & set(channels), name
    assert approve(world, one["sha"], channel="terminal")["approval"]["approved_via"] == "terminal"


def test_the_approval_is_kept_per_platform(world, one):
    media.link_posts(world.data, world.rid, {"tiktok": POST})
    assert "name the platform" in str(refused(approve, world, one["sha"]))
    approve(world, one["sha"], platform="instagram")
    assert card(world, platform="instagram")["approval"]["state"] == "approved"
    assert card(world, platform="tiktok")["approval"] is None
    approve(world, one["sha"], platform="tiktok")
    assert sorted(media.load(world.data, world.rid)["approvals"]) == ["instagram", "tiktok"]


# --- send back ----------------------------------------------------------------------------------------------------------------------------------


def test_sending_back_needs_a_comment_removes_the_approval_and_returns_the_post_to_the_review_step(world, one):
    approve(world, one["sha"])
    for bad in ("", "   ", "\n\t", None, 5):
        assert refused(ops.video_send_back, world.project, world.rid, bad).code == 2, bad
    assert refused(ops.video_send_back, world.project, world.rid, "x" * (video.MAX_COMMENT + 1)).code == 2
    assert media.load(world.data, world.rid)["approvals"]["instagram"], "a refused send-back changes nothing"
    done = ops.video_send_back(world.project, world.rid, "The second beat\x00 is too\x07 fast.\r\nSlow it down.")
    assert done["sent_back"]["comment"] == "The second beat  is too  fast.\nSlow it down." and done["sent_back"]["render_sha256"] == one["sha"]
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", done["sent_back"]["at"])
    assert done["approval"] is None and done["can_download"] is False
    record = media.load(world.data, world.rid)
    assert "instagram" not in record["approvals"]
    assert record["resume"] == {"step": "review", "reason": "sent_back", "platform": "instagram", "at": done["sent_back"]["at"]}
    assert [e["event"] for e in record["approval_log"]] == ["approved", "sent_back"] and record["approval_log"][1]["approval_removed"] is True
    assert record["status"] == "open"


def test_a_send_back_holds_the_post_until_it_is_rendered_again_or_its_caption_is_edited(world, one):
    approve(world, one["sha"])
    ops.video_send_back(world.project, world.rid, "Change the hook.")
    shown = card(world)
    assert shown["sent_back"]["comment"] == "Change the hook." and shown["sent_back"]["blocks_approval"] is True
    # the same render and the same caption, from a card that was open before the send-back: refused with its own code, nothing recorded
    error = refused(approve, world, one["sha"])
    assert error.kind == "sent_back" and error.code == 1 and "sent_back" in str(error)
    record = media.load(world.data, world.rid)
    assert not record["approvals"] and record["resume"]["step"] == "review", "the refused approval undid nothing"
    # a new render lifts it
    second = write_render(world.data, world.rid, "two")
    assert card(world)["sent_back"]["blocks_approval"] is False
    again = approve(world, second["sha"])
    assert again["sent_back"] is None and again["approval"]["state"] == "approved"


def test_an_edit_of_the_caption_lifts_a_send_back_and_the_pipelines_resume_lifts_it_too(world, one):
    ops.video_send_back(world.project, world.rid, "Reword it.")
    assert refused(approve, world, one["sha"]).kind == "sent_back"
    write_post(world.project, CAPTION + " (reworded)")
    assert card(world)["sent_back"]["blocks_approval"] is False
    assert approve(world, one["sha"], caption=CAPTION + " (reworded)")["approval"]["state"] == "approved"
    write_post(world.project)
    ops.video_send_back(world.project, world.rid, "Back again.")
    assert refused(approve, world, one["sha"]).kind == "sent_back"
    media.update(world.data, world.rid, lambda r: r.pop("resume"))                       # the pipeline resumed at review and cleared its marker
    assert card(world)["sent_back"]["blocks_approval"] is False
    assert approve(world, one["sha"])["approval"]["state"] == "approved"


def test_a_stale_card_in_a_second_tab_cannot_approve_after_the_send_back_of_the_first(world, one):
    tab_two = card(world)                                                         # tab two reads the card: nothing approved, nothing held
    assert tab_two["sent_back"] is None
    ops.video_send_back(world.project, world.rid, "Too fast.")                    # tab one sends it back
    error = refused(ops.video_approve, world.project, world.rid, tab_two["render"]["sha256"], tab_two["caption"]["sha256"], channel="page")
    assert error.kind == "sent_back" and not media.load(world.data, world.rid)["approvals"]
    # the race inside the record lock: the check runs again where the approval is written
    original = ops_video._sent_back_blocks
    calls = []

    def late(record, platform, render_sha, caption_sha):
        calls.append(1)
        return False if len(calls) == 1 else original(record, platform, render_sha, caption_sha)    # the first look sees nothing, the one under the lock sees the send-back

    ops_video._sent_back_blocks = late
    try:
        assert refused(approve, world, one["sha"]).kind == "sent_back" and len(calls) == 2
    finally:
        ops_video._sent_back_blocks = original
    assert not media.load(world.data, world.rid)["approvals"]


def test_a_closed_post_cannot_be_sent_back(world, one):
    media.mark(world.data, world.rid, "published")
    assert "published" in str(refused(ops.video_send_back, world.project, world.rid, "late"))


def test_the_log_keeps_only_the_last_events(world, one):
    for _ in range(video.LOG_MAX + 8):
        approve(world, one["sha"])
    assert len(media.load(world.data, world.rid)["approval_log"]) == video.LOG_MAX


# --- the terminal --------------------------------------------------------------------------------------------------------------------------------


def test_the_terminal_reads_the_card_approves_and_sends_back_with_the_flags_of_the_table(world, one):
    base = ["--project", world.project, "--recording", world.rid]
    shown = cli.run(["video-card", *base])
    assert shown["render"]["sha256"] == one["sha"]
    done = cli.run(["video-approve", *base, "--video-sha256", one["sha"], "--caption-sha256", caption_sha(), "--post-platform", "instagram"])
    assert done["approval"]["state"] == "approved" and done["approval"]["approved_via"] == "terminal"
    back = cli.run(["video-send-back", *base, "--comment", "Trim the ending."])
    assert back["sent_back"]["comment"] == "Trim the ending." and back["approval"] is None


def test_nothing_in_the_approval_calls_a_model_a_provider_or_the_network():
    import ast
    imported = set()
    for name in ("video.py", "ops_video.py"):
        for node in ast.walk(ast.parse(open(os.path.join(st.RUNTIME, name), encoding="utf-8").read())):
            if isinstance(node, ast.Import):
                imported |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported.add((node.module or "").split(".")[0])
    assert imported <= {"__future__", "hashlib", "json", "os", "re", "stat", "sys", "threading", "media", "video", "ops_core", "ops_reads"}, imported
