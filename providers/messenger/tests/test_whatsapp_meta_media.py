"""Offline tests of the media half of providers/messenger/whatsapp_meta.py, the code the two official WhatsApp providers share when they
fetch a file a sender sent (ATT-3): the stream into `<out>/content`, the byte cap, the declared hash, the host check and the cleaning of
what the platform declared. Nothing here reaches a network; the bodies are fakes.

Run: uv run --with pytest pytest providers/messenger/tests/test_whatsapp_meta_media.py
"""
from __future__ import annotations

import base64
import hashlib
import http.client
import os
import stat

import pytest

import whatsapp_cloud_kit as kit
from whatsapp_cloud_kit import EndlessResponse, StreamResponse

meta = kit.wc.meta
BODY = b"%PDF-1.4 a small fake document " * 40


def out_dir(tmp_path):
    folder = tmp_path / "incoming"
    folder.mkdir(mode=0o700)
    return str(folder)


def fail(call):
    with pytest.raises(meta.ProviderError) as e:
        call()
    return e.value


# --- the stream into <out>/content ---------------------------------------------------------------------------------------------


def test_the_body_is_written_as_content_mode_0600_with_its_count_and_hash(tmp_path):
    out = out_dir(tmp_path)
    found = meta.save_stream(StreamResponse(BODY), out, 1_000_000)
    assert found == {"bytes": len(BODY), "sha256": hashlib.sha256(BODY).hexdigest()}
    path = os.path.join(out, "content")
    assert open(path, "rb").read() == BODY and stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert os.listdir(out) == ["content"], "nothing but the one fixed name is written"


def test_a_body_of_exactly_the_cap_is_taken_and_one_byte_more_is_not(tmp_path):
    assert meta.save_stream(StreamResponse(b"a" * 100), out_dir(tmp_path), 100)["bytes"] == 100
    other = tmp_path / "other"
    other.mkdir(mode=0o700)
    err = fail(lambda: meta.save_stream(StreamResponse(b"a" * 101), str(other), 100))
    assert err.kind == "usage" and err.code == meta.EXIT_USAGE and os.listdir(other) == []


def test_the_cap_is_enforced_while_streaming_and_the_partial_file_is_removed(tmp_path):
    out = out_dir(tmp_path)
    body = EndlessResponse()
    err = fail(lambda: meta.save_stream(body, out, 200_000))
    assert err.kind == "usage" and "larger" in str(err)
    assert body.total <= 200_000 + 1, "it stops reading at the first byte over the cap"
    assert os.listdir(out) == []


def test_a_declared_length_over_the_cap_is_refused_before_a_byte_is_read(tmp_path):
    out = out_dir(tmp_path)
    body = StreamResponse(BODY, headers={"Content-Length": str(10_000_000)})
    err = fail(lambda: meta.save_stream(body, out, 1_000_000))
    assert err.kind == "usage" and body.total == 0 and os.listdir(out) == []


def test_a_length_header_that_is_not_a_number_is_ignored_and_the_stream_decides(tmp_path):
    body = StreamResponse(BODY, headers={"Content-Length": "lots"})
    assert meta.save_stream(body, out_dir(tmp_path), 1_000_000)["bytes"] == len(BODY)


def test_a_body_that_lies_about_a_small_length_is_still_cut_at_the_cap(tmp_path):
    out = out_dir(tmp_path)
    body = EndlessResponse(headers={"Content-Length": "5"})
    assert fail(lambda: meta.save_stream(body, out, 1000)).kind == "usage" and body.total <= 1001 and os.listdir(out) == []


def test_the_whole_fetch_has_a_deadline_and_the_partial_file_is_removed(tmp_path):
    out = out_dir(tmp_path)
    ticks = iter(range(0, 10_000, 40))
    err = fail(lambda: meta.save_stream(EndlessResponse(), out, 10**9, clock=lambda: next(ticks)))
    assert err.kind == "failed" and "too long" in str(err) and os.listdir(out) == []


def test_a_failure_while_reading_names_the_kind_only_and_leaves_no_file(tmp_path):
    planted = "planted-secret-in-the-error-text"
    for error in (http.client.IncompleteRead(b"abc", 10), OSError(planted), ValueError(planted), http.client.RemoteDisconnected(planted)):
        out = str(tmp_path / f"o{id(error)}")
        os.mkdir(out, 0o700)
        err = fail(lambda: meta.save_stream(StreamResponse(b"partial", error=error), out, 1000))
        assert err.kind == "failed" and planted not in str(err) and "abc" not in str(err)
        assert type(error).__name__ in str(err) and os.listdir(out) == []


def test_the_declared_hash_is_checked_in_hex_and_in_base64_and_a_mismatch_removes_the_file(tmp_path):
    digest = hashlib.sha256(BODY)
    for n, declared in enumerate((digest.hexdigest(), digest.hexdigest().upper(), base64.b64encode(digest.digest()).decode())):
        out = str(tmp_path / f"ok{n}")
        os.mkdir(out, 0o700)
        assert meta.save_stream(StreamResponse(BODY), out, 10**6, declared=meta.declared_digest(declared))["sha256"] == digest.hexdigest()
    out = str(tmp_path / "bad")
    os.mkdir(out, 0o700)
    wrong = meta.declared_digest(hashlib.sha256(b"another file").hexdigest())
    err = fail(lambda: meta.save_stream(StreamResponse(BODY), out, 10**6, declared=wrong))
    assert err.kind == "failed" and "hash" in str(err) and os.listdir(out) == []


@pytest.mark.parametrize("bad", ["", "abc", "g" * 64, "A" * 43, "A" * 44, 5, ["x"], "a" * 63, "a" * 65])
def test_a_declared_hash_of_no_known_shape_is_refused_not_ignored(bad):
    assert fail(lambda: meta.declared_digest(bad)).kind == "failed"


def test_no_declared_hash_is_no_check():
    assert meta.declared_digest(None) is None


# --- where it writes ---------------------------------------------------------------------------------------------------------


def test_an_existing_content_is_never_overwritten_or_removed(tmp_path):
    out = out_dir(tmp_path)
    (tmp_path / "incoming" / "content").write_bytes(b"keep me")
    err = fail(lambda: meta.save_stream(StreamResponse(BODY), out, 10**6))
    assert err.kind == "usage" and (tmp_path / "incoming" / "content").read_bytes() == b"keep me"


def test_a_content_that_is_a_link_is_not_followed(tmp_path):
    out = out_dir(tmp_path)
    target = tmp_path / "elsewhere"
    target.write_bytes(b"untouched")
    os.symlink(target, os.path.join(out, "content"))
    assert fail(lambda: meta.save_stream(StreamResponse(BODY), out, 10**6)).kind == "usage"
    assert target.read_bytes() == b"untouched"


def test_the_folder_must_be_an_absolute_real_directory_of_this_user(tmp_path):
    real = tmp_path / "real"
    real.mkdir(mode=0o700)
    link = tmp_path / "link"
    os.symlink(real, link)
    plain = tmp_path / "plain"
    plain.write_text("x")
    for bad in ("relative/dir", "", str(tmp_path / "missing"), str(link), str(plain), "/dev/null", str(real) + "\x00"):
        err = fail(lambda: meta.save_stream(StreamResponse(BODY), bad, 1000))
        assert err.kind == "usage", bad
    assert os.listdir(real) == []


def test_a_file_name_the_platform_declared_never_reaches_the_path(tmp_path):
    out = out_dir(tmp_path)
    meta.save_stream(StreamResponse(BODY), out, 10**6)
    assert os.listdir(out) == ["content"] and not (tmp_path / "passwd").exists()


# --- the host check ----------------------------------------------------------------------------------------------------------

HOSTS = ("lookaside.fbsbx.com",)


@pytest.mark.parametrize("url", [
    "https://lookaside.fbsbx.com/whatsapp_business/attachments/?mid=1&ext=2&hash=3",
    "https://LOOKASIDE.fbsbx.com/x",
    "https://lookaside.fbsbx.com:443/x",
])
def test_an_address_on_a_listed_host_over_https_is_rebuilt_from_its_parts(url):
    found = meta.url_on_hosts(url, HOSTS)
    assert found.startswith("https://lookaside.fbsbx.com/") and "@" not in found


@pytest.mark.parametrize("url", [
    "http://lookaside.fbsbx.com/x",                        # not https
    "https://lookaside.fbsbx.com.evil.example/x",          # a longer name
    "https://evil.example/lookaside.fbsbx.com",            # the name in the path
    "https://evil.example?lookaside.fbsbx.com",
    "https://evil.example#@lookaside.fbsbx.com/",
    "https://user@lookaside.fbsbx.com/x",                  # userinfo
    "https://evil.example\\@lookaside.fbsbx.com/x",        # a backslash: parsers disagree on where the host ends
    "https://lookaside.fbsbx.com:8443/x",                  # another port
    "https://lookaside.fbsbx.com:bad/x",
    "https://xlookaside.fbsbx.com/x",
    "https://fbsbx.com/x",
    "https://lookaside.fbsbx.com /x",                      # a space
    "https://lookaside.fbsbx.com/x\n",                     # a control character
    "https://127.0.0.1/x",
    "//lookaside.fbsbx.com/x",
    "file:///etc/passwd",
    "lookaside.fbsbx.com/x",
    "",
    None,
    5,
    "https://" + "a" * 3000 + ".lookaside.fbsbx.com/",
])
def test_every_other_address_is_refused(url):
    assert meta.url_on_hosts(url, HOSTS) is None


# --- what the platform declared ---------------------------------------------------------------------------------------------


def test_a_declared_name_is_cleaned_of_control_characters_and_cut_and_is_text_only():
    assert meta.clean_name("plan\x00\x1b[31m.pdf\n") == "plan[31m.pdf"
    assert meta.clean_name("  report.docx ") == "report.docx"
    assert len(meta.clean_name("a" * 900)) == 255
    for none in (None, 5, "", "   ", "\x00\x01", ["x"]):
        assert meta.clean_name(none) is None


def test_a_declared_type_is_a_media_type_in_lower_case_or_nothing():
    assert meta.clean_mime("Application/PDF; charset=binary") == "application/pdf"
    assert meta.clean_mime("text/csv") == "text/csv"
    for none in (None, 5, "", "pdf", "a/b/c", "application/", "/pdf", "x y/z", "a" * 300 + "/b", "text/\x00"):
        assert meta.clean_mime(none) is None


def test_a_media_type_the_bridge_refuses_early_is_named_as_the_kind_it_is():
    assert meta.type_for_mime("image/jpeg") == "photo" and meta.type_for_mime("image/webp") == "photo"
    assert meta.type_for_mime("audio/ogg") == "audio" and meta.type_for_mime("video/mp4") == "video"
    assert meta.type_for_mime("application/pdf") == "application/pdf"
    assert meta.type_for_mime(None) is None and meta.type_for_mime("nonsense") is None
