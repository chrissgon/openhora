"""The messaging bridge and a Google Drive link a listed sender sends (runtime/messaging_cloud.py, package V1d-3, limit L70): a link from a sender whose profile holds
`media-phone` starts the fetch and then the post list; the same link from any other sender is not taken; each refusal gives its sentence; the language. The
operations layer is the real one over a real store of recordings; the socket and the provider are fakes; the messenger is the stand-in of the attachment tests. Offline,
no model, no network; every name and id is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_messaging_cloud.py
"""
from __future__ import annotations

import io
import subprocess
import sys

import pytest

import phrase_kit as pk
import standin_tree as st
from media_fixtures import body_of, mp4_head
from media_kit import world as media_world  # noqa: F401
from test_attachments import accept
from test_messaging_video import IDENT, OTHER, STEM, SECOND, keys, phone, second_post  # noqa: F401

cloud_fetch = st.load("cloud_fetch")
messaging_cloud = st.load("messaging_cloud")
phrases = st.load("phrases")
media = st.load("media")
FID = "FAKEfileID0123456789"
LINK = f"https://drive.google.com/file/d/{FID}/view?usp=sharing"
MP4 = body_of(mp4_head(), 64)


@pytest.fixture
def fetched(monkeypatch):
    """A fake `cloud_fetch.fetch` that feeds the synthetic MP4 to `receive`; the list holds what it was asked for."""
    asked = []

    def fake(url, receive, cap, **seams):
        asked.append((url, cap))
        return receive(io.BytesIO(MP4), len(MP4))
    monkeypatch.setattr(cloud_fetch, "fetch", fake)
    return asked


def recordings(w) -> int:
    return len(media.records(w.world["data"]))


# 1. a link from a sender with the group


def test_a_drive_link_from_a_sender_with_the_group_is_fetched_then_the_post_list_is_sent(phone, fetched):
    w = phone
    before = recordings(w)
    w.say(f"Here is the recording {LINK}")
    assert keys(w) == ["VID_CLOUD_FETCHING", "VID_RECEIVED", "VID_PICK_POST"]
    pk.assert_said(w.texts()[1], "VID_RECEIVED", size="64 bytes")
    pk.assert_said(w.texts()[2], "VID_PICK_POST", list=f"1. {STEM}")
    assert w.calls[0] == "video-phone-fetch" and "video-phone-start" not in w.calls
    assert fetched == [(cloud_fetch.download_url(FID), media.MEDIA_MAX_BYTES)] and recordings(w) == before + 1
    assert IDENT in w.bridge.video.held and w.fetches() == [], "the messenger fetched nothing: the link is not an attachment"
    w.say("1")
    assert keys(w)[-1] == "VID_REVIEW_WORDS" and w.calls[-1] == "video-phone-start", "the recording goes on as one sent as a file does"


def test_two_posts_are_listed_in_order_and_a_number_starts_one(phone, fetched):
    w = phone
    second_post(w)
    w.say(LINK)
    pk.assert_said(w.texts()[2], "VID_PICK_POST", list=f"1. {SECOND}\n2. {STEM}")


def test_no_post_ready_says_so_after_the_recording_was_kept(phone, fetched):
    w = phone
    import os
    from pathlib import Path
    os.remove(Path(w.world["path"]) / "docs" / "marketing" / "content" / f"{STEM}.md")
    w.say(LINK)
    assert keys(w) == ["VID_CLOUD_FETCHING", "VID_RECEIVED", "VID_NO_POST"] and w.bridge.video.held == {}


def test_a_docs_link_is_taken_too_and_a_host_word_in_capitals_counts(phone, fetched):
    w = phone
    w.say(f"https://DRIVE.GOOGLE.COM/open?id={FID}")
    assert keys(w)[0] == "VID_CLOUD_FETCHING" and len(fetched) == 1
    w.reset()
    w.say(f"https://docs.google.com/file/d/{FID}/edit")
    assert keys(w)[0] == "VID_CLOUD_FETCHING" and len(fetched) == 2


# 2. every other line goes on as before


def test_the_same_link_from_a_sender_without_the_group_is_not_taken(phone, fetched):
    w = phone
    before = recordings(w)
    assert w.bridge.video.cloud.link(w.project, OTHER, LINK) is False
    assert w.bridge.video.line(w.project, OTHER, LINK) is False
    w.say(LINK, sender=OTHER)
    assert "video-phone-fetch" not in w.calls and fetched == [] and recordings(w) == before
    assert "VID_CLOUD_FETCHING" not in keys(w)


def test_a_line_with_no_drive_host_is_not_taken(phone, fetched):
    w = phone
    cloud = w.bridge.video.cloud
    for text in ("hello", "https://evil.example/file/d/" + FID, "drive.google.com", "see docs.google.com", "", None):
        assert cloud.link(w.project, IDENT, text) is False, text
    assert w.texts() == [] and fetched == [] and w.calls == []


def test_a_line_with_the_host_and_no_link_is_told_how_to_send_one(phone, fetched):
    w = phone
    w.say("it is on drive.google.com/ somewhere")
    assert keys(w)[0] == "VID_CLOUD_FETCHING" and fetched == []
    assert "drive.google.com/file/d/" in w.texts()[-1]


def test_the_post_waiting_line_still_works_for_a_number(phone, fetched):
    w = phone
    second_post(w)
    w.say(LINK)
    assert w.bridge.video.line(w.project, IDENT, "what is this?") is False and IDENT in w.bridge.video.held
    w.say("9")
    assert keys(w)[-1] == "VID_POST_GONE"


# 3. each refusal gives its sentence


def test_each_refusal_code_gives_its_sentence_and_no_recording_is_kept(phone, monkeypatch):
    w = phone
    before = recordings(w)
    want = {"not_shared": "VID_CLOUD_NOT_SHARED", "too_large": "VID_CLOUD_TOO_LARGE", "no_length": "VID_CLOUD_NO_LENGTH", "address": "VID_CLOUD_FAILED",
            "redirect": "VID_CLOUD_FAILED", "status": "VID_CLOUD_FAILED", "network": "VID_CLOUD_FAILED"}
    assert set(want) == set(cloud_fetch.CODES)
    for code, key in want.items():
        def fake(url, receive, cap, _code=code, **seams):
            raise cloud_fetch.CloudError(_code)
        monkeypatch.setattr(cloud_fetch, "fetch", fake)
        w.reset()
        w.say(LINK)
        assert keys(w) == ["VID_CLOUD_FETCHING", key], code
        assert w.bridge.video.held == {}
    assert recordings(w) == before and w.incoming() == []
    assert w.texts()[-1] == phrases.en("VID_CLOUD_FAILED")


def test_a_refusal_of_the_store_is_said_in_the_operations_own_sentence(phone, monkeypatch):
    w = phone
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 56
    monkeypatch.setattr(cloud_fetch, "fetch", lambda url, receive, cap, **s: receive(io.BytesIO(png), len(png)))
    w.say(LINK)
    assert keys(w)[0] == "VID_CLOUD_FETCHING" and w.texts()[-1].endswith("(type)") and "VID_RECEIVED" not in keys(w)


def test_the_sentences_never_hold_the_link_or_its_id(phone, monkeypatch):
    w = phone
    for code in cloud_fetch.CODES:
        monkeypatch.setattr(cloud_fetch, "fetch", lambda url, receive, cap, _c=code, **s: (_ for _ in ()).throw(cloud_fetch.CloudError(_c)))
        w.say(LINK)
    assert all(FID not in text and "drive.google.com" not in text for text in w.texts())


# 4. the language


def test_a_project_in_portuguese_gets_the_portuguese_sentences(phone, monkeypatch):
    w = phone
    accept(w.world["path"], language="pt-BR")
    monkeypatch.setattr(cloud_fetch, "fetch", lambda url, receive, cap, **s: (_ for _ in ()).throw(cloud_fetch.CloudError("not_shared")))
    w.say(LINK)
    assert w.texts() == [phrases.text("VID_CLOUD_FETCHING", {"language": "pt-BR"}), phrases.text("VID_CLOUD_NOT_SHARED", {"language": "pt-BR"})]
    assert w.texts()[0] != phrases.text("VID_CLOUD_FETCHING", {"language": "en"})


def test_the_phrases_are_in_both_languages_with_the_rule_of_the_part():
    for key in ("VID_CLOUD_FETCHING", "VID_CLOUD_NOT_SHARED", "VID_CLOUD_TOO_LARGE", "VID_CLOUD_NO_LENGTH", "VID_CLOUD_FAILED"):
        assert phrases.en(key) != phrases.text(key, {"language": "pt-BR"})
    assert "anyone with the link" in phrases.en("VID_CLOUD_NOT_SHARED") and "qualquer pessoa com o link" in phrases.text("VID_CLOUD_NOT_SHARED", {"language": "pt-BR"})


def test_the_module_starts_on_its_own():
    flags = ["--help"]
    done = subprocess.run([sys.executable, "-I", str(st.RUNTIME / "messaging_cloud.py"), *flags], capture_output=True, text=True, timeout=60, env={})
    assert done.returncode == 0 and "media-phone" in done.stdout
    other = ["--nope"]
    assert subprocess.run([sys.executable, "-I", str(st.RUNTIME / "messaging_cloud.py"), *other], capture_output=True, text=True, timeout=60, env={}).returncode == 2


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
