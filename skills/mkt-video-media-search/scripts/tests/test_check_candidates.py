"""Offline tests of check_candidates.py: each rule of the skill's self-check step, the screen_work flag, the open items,
the stop rule 1 file, the usage errors, and that the refused text never reaches the output.

Names are fictional and hosts are under .example. Nothing here opens a link.

Run: uv run --with pytest pytest skills/mkt-video-media-search/scripts/tests
"""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "check_candidates.py"
SLOTS = ["harbour:image", "market"]

GOOD = {
    "slot": "harbour",
    "kind": "image",
    "media_url": "https://photos.example/aster/harbour-1.jpg",
    "thumb_url": "https://photos.example/aster/harbour-1-small.jpg",
    "page_url": "https://photos.example/aster/harbour",
    "title": "Harbour at dusk",
    "licence_claim": "Free to use, attribution required",
    "screen_work": False,
    "resolution": "1080x1920",
    "site_terms": "free, attribution required, personal use only",
}


def candidate(**changes):
    item = copy.deepcopy(GOOD)
    item.update(changes)
    return item


def doc(*candidates, opens=()):
    return {"schema_version": 1, "candidates": list(candidates), "open": list(opens)}


def run(tmp_path, data, slots=SLOTS, raw=None):
    path = tmp_path / "web-candidates.json"
    path.write_text(raw if raw is not None else json.dumps(data), encoding="utf-8")
    argv = [sys.executable, str(SCRIPT), "--file", str(path)]
    for slot in slots:
        argv += ["--slot", slot]
    proc = subprocess.run(argv, capture_output=True, text=True)
    out = json.loads(proc.stdout) if proc.stdout.strip() else None
    return proc.returncode, out, proc


def codes(out):
    return {(e["where"], e["field"], e["code"]) for e in out["errors"]}


def test_a_good_file_is_ok(tmp_path):
    rc, out, _ = run(tmp_path, doc(GOOD, candidate(slot="market", kind="clip", media_url="https://clips.example/a.mp4")))
    assert rc == 0 and out["ok"] is True and out["errors"] == []
    assert out["counts"] == {"candidates": 2, "open": 0}


def test_stop_rule_1_file_is_ok(tmp_path):
    rc, out, _ = run(tmp_path, doc(opens=[{"code": "no_search_tool"}]))
    assert rc == 0 and out["ok"] is True


def test_minimal_candidate_without_optional_fields_is_ok(tmp_path):
    item = {k: v for k, v in GOOD.items() if k not in ("thumb_url", "resolution", "site_terms")}
    rc, out, _ = run(tmp_path, doc(item))
    assert rc == 0 and out["ok"] is True


@pytest.mark.parametrize("url,code", [
    ("http://photos.example/a.jpg", "not_https"),
    ("https://photos.example:8443/a.jpg", "bad_port"),
    ("https://user:pw@photos.example/a.jpg", "user_info"),
    ("https://203.0.113.9/a.jpg", "ip_literal"),
    ("https://[2001:db8::1]/a.jpg", "ip_literal"),
    ("https://photos.example./a.jpg", "trailing_dot"),
    ("https://localhost/a.jpg", "bad_host"),
    ("https://bad_host.example/a.jpg", "bad_host"),
    ("https://photos.example/a b.jpg", "bad_character"),
    ("https://photos.example/" + "a" * 2050, "too_long"),
    ("ftp://photos.example/a.jpg", "not_https"),
])
def test_each_url_rule_is_refused_on_every_url_field(tmp_path, url, code):
    for field in ("media_url", "page_url", "thumb_url"):
        rc, out, _ = run(tmp_path, doc(candidate(**{field: url})))
        assert rc == 1
        assert ("candidates[0]", field, code) in codes(out)


def test_port_443_is_accepted(tmp_path):
    rc, out, _ = run(tmp_path, doc(candidate(media_url="https://photos.example:443/a.jpg")))
    assert rc == 0, out


def test_url_at_the_limit_is_accepted(tmp_path):
    url = "https://photos.example/" + "a" * (2048 - len("https://photos.example/"))
    assert len(url) == 2048
    rc, out, _ = run(tmp_path, doc(candidate(media_url=url)))
    assert rc == 0, out


def test_more_than_three_per_slot_is_refused(tmp_path):
    items = [candidate(media_url=f"https://photos.example/a{i}.jpg") for i in range(4)]
    rc, out, _ = run(tmp_path, doc(*items))
    assert rc == 1 and ("file", "candidates", "too_many_for_slot") in codes(out)


def test_three_per_slot_is_accepted(tmp_path):
    items = [candidate(media_url=f"https://photos.example/a{i}.jpg") for i in range(3)]
    rc, out, _ = run(tmp_path, doc(*items))
    assert rc == 0, out


def test_more_than_eighteen_in_all_is_refused(tmp_path):
    slots = [f"s{i}" for i in range(7)]
    items = [candidate(slot=f"s{i // 3}", media_url=f"https://photos.example/a{i}.jpg") for i in range(19)]
    rc, out, _ = run(tmp_path, doc(*items), slots=slots)
    assert rc == 1 and ("file", "candidates", "too_many") in codes(out)


def test_eighteen_in_all_is_accepted(tmp_path):
    slots = [f"s{i}" for i in range(6)]
    items = [candidate(slot=f"s{i // 3}", media_url=f"https://photos.example/a{i}.jpg") for i in range(18)]
    rc, out, _ = run(tmp_path, doc(*items), slots=slots)
    assert rc == 0, out


def test_a_slot_the_task_does_not_give_is_refused(tmp_path):
    rc, out, _ = run(tmp_path, doc(candidate(slot="elsewhere")))
    assert ("candidates[0]", "slot", "not_in_task") in codes(out)


def test_a_kind_the_slot_does_not_allow_is_refused(tmp_path):
    rc, out, _ = run(tmp_path, doc(candidate(kind="clip")))
    assert rc == 1 and ("candidates[0]", "kind", "not_in_task") in codes(out)


def test_a_kind_that_is_neither_image_nor_clip_is_refused(tmp_path):
    rc, out, _ = run(tmp_path, doc(candidate(kind="gif")))
    assert ("candidates[0]", "kind", "not_image_or_clip") in codes(out)


def test_title_and_claim_bounds(tmp_path):
    rc, out, _ = run(tmp_path, doc(candidate(title="t" * 121, licence_claim="c" * 201, site_terms="s" * 201)))
    assert {("candidates[0]", "title", "too_long"), ("candidates[0]", "licence_claim", "too_long"),
            ("candidates[0]", "site_terms", "too_long")} <= codes(out)
    rc, out, _ = run(tmp_path, doc(candidate(title="t" * 120, licence_claim="c" * 200, site_terms="s" * 200)))
    assert rc == 0, out


def test_empty_text_is_refused(tmp_path):
    rc, out, _ = run(tmp_path, doc(candidate(title="  ")))
    assert ("candidates[0]", "title", "not_text") in codes(out)


@pytest.mark.parametrize("value", ["true", 1, 0, None, "yes"])
def test_screen_work_must_be_a_boolean(tmp_path, value):
    rc, out, _ = run(tmp_path, doc(candidate(screen_work=value)))
    assert rc == 1 and ("candidates[0]", "screen_work", "not_boolean") in codes(out)


@pytest.mark.parametrize("value", [True, False])
def test_screen_work_booleans_are_accepted(tmp_path, value):
    rc, out, _ = run(tmp_path, doc(candidate(screen_work=value)))
    assert rc == 0, out


def test_screen_work_is_required(tmp_path):
    item = candidate()
    del item["screen_work"]
    rc, out, _ = run(tmp_path, doc(item))
    assert ("candidates[0]", "screen_work", "missing") in codes(out)


@pytest.mark.parametrize("value", ["600x900", "1080x1920", "270x370"])
def test_resolution_forms_accepted(tmp_path, value):
    rc, out, _ = run(tmp_path, doc(candidate(resolution=value)))
    assert rc == 0, out


@pytest.mark.parametrize("value", ["1080", "1080 x 1920", "0x900", 1080, "big", "1080x1920px"])
def test_resolution_bad_forms_refused(tmp_path, value):
    rc, out, _ = run(tmp_path, doc(candidate(resolution=value)))
    assert ("candidates[0]", "resolution", "bad_form") in codes(out)


def test_missing_required_field_is_named(tmp_path):
    item = candidate()
    del item["page_url"]
    rc, out, _ = run(tmp_path, doc(item))
    assert ("candidates[0]", "page_url", "missing") in codes(out)


def test_unknown_field_is_refused(tmp_path):
    rc, out, _ = run(tmp_path, doc(candidate(tracking_url="https://t.example/x")))
    assert ("candidates[0]", "item", "unknown_field") in codes(out)


def test_duplicate_media_url_is_refused(tmp_path):
    rc, out, _ = run(tmp_path, doc(candidate(), candidate()))
    assert ("candidates[1]", "media_url", "duplicate") in codes(out)


def test_open_items(tmp_path):
    opens = [{"code": "no_result", "slot": "market"}, {"code": "scene_only", "slot": "harbour", "note": "episode 4"}]
    rc, out, _ = run(tmp_path, doc(opens=opens))
    assert rc == 0, out


def test_open_bad_code_slot_and_note(tmp_path):
    opens = [{"code": "later"}, {"code": "no_result"}, {"code": "no_result", "slot": "nope"},
             {"code": "scene_only", "slot": "market", "note": "n" * 201}]
    rc, out, _ = run(tmp_path, doc(opens=opens))
    assert {("open[0]", "code", "unknown_code"), ("open[1]", "slot", "missing"), ("open[2]", "slot", "not_in_task"),
            ("open[3]", "note", "too_long")} <= codes(out)


def test_schema_version_must_be_1(tmp_path):
    data = doc()
    data["schema_version"] = 2
    rc, out, _ = run(tmp_path, data)
    assert ("file", "schema_version", "not_1") in codes(out)
    data["schema_version"] = True
    rc, out, _ = run(tmp_path, data)
    assert ("file", "schema_version", "not_1") in codes(out)


def test_root_and_list_shapes(tmp_path):
    rc, out, _ = run(tmp_path, [])
    assert ("file", "root", "not_object") in codes(out)
    rc, out, _ = run(tmp_path, {"schema_version": 1, "candidates": {}, "open": "x"})
    assert {("file", "candidates", "not_list"), ("file", "open", "not_list")} <= codes(out)


def test_not_json_is_an_error_item_not_a_usage_error(tmp_path):
    rc, out, _ = run(tmp_path, None, raw="{not json")
    assert rc == 1 and ("file", "root", "not_json") in codes(out)


def test_the_refused_text_never_reaches_the_output(tmp_path):
    token = "SECRET-TOKEN-91731"  # security-scan: allow secret-assignment -- a planted marker the test searches for, not a secret
    bad = candidate(media_url=f"http://leak.example/{token}.jpg", page_url=f"https://user:{token}@leak.example/p",
                    title=token * 30, licence_claim=token * 40, resolution=token, kind=token, slot=token,
                    screen_work=token)
    rc, out, proc = run(tmp_path, doc(bad, opens=[{"code": token, "slot": token, "note": token * 100}]))
    assert rc == 1
    assert token not in proc.stdout and token not in proc.stderr


def test_every_error_item_has_exactly_the_three_keys(tmp_path):
    rc, out, _ = run(tmp_path, doc(candidate(media_url="http://x.example/a.jpg", screen_work="no")))
    assert out["errors"] and all(set(e) == {"where", "field", "code"} for e in out["errors"])


def test_usage_errors(tmp_path):
    path = tmp_path / "f.json"
    path.write_text("{}", encoding="utf-8")
    for argv in ([], ["--file", str(path)], ["--file", str(path), "--slot", "a:video"], ["--file", str(path), "--slot", ":image"],
                 ["--file", str(tmp_path / "missing.json"), "--slot", "a"], ["--bogus"]):
        proc = subprocess.run([sys.executable, str(SCRIPT)] + argv, capture_output=True, text=True)
        assert proc.returncode == 2, argv
        assert proc.stdout == ""
        assert proc.stderr


def test_help_exits_zero_with_usage():
    proc = subprocess.run([sys.executable, str(SCRIPT), "--help"], capture_output=True, text=True)
    assert proc.returncode == 0 and "--slot" in proc.stdout and "--file" in proc.stdout
