"""The second page contract (PF-a2), end to end on the host with the host's Chromium and ffmpeg and a stand-in for the HyperFrames runtime (hf_second_kit):
a fictional HF-shaped component is served, drawn, gated on its pixels and composed. The clean control is drawn twice and is byte-identical, and every
planted variant is refused with its code. The real runtime is the live legs' (`test_engine_contract_live.py`), because its files exist only in the image.
Skipped with a reason where ffmpeg or Chromium is absent."""
from __future__ import annotations

import copy
import json
import re
import shutil

import pytest

import renderer_kit as K
import hf_second_kit as H
import _cdp
import _hf_host

needs_all = pytest.mark.skipif(not (K.HAVE_FFMPEG and K.BROWSER), reason=K.SKIP_MEDIA + "; " + K.SKIP_BROWSER)


@pytest.fixture(scope="module")
def pipe(tmp_path_factory):
    """One recording taken through analyse, base and align: the post has one keyword beat."""
    tmp = tmp_path_factory.mktemp("second")
    files = K.pipeline(tmp, K.build_transcript(K.SHORT_SENTENCES[:2]), H.POST)
    return {"files": files, "tmp": tmp}


def setup(pipe, variant="clean", tag=None, edit=None, runtime_edit=None, entry_over=None):
    """Write a runtime stand-in, the variant's component, the entry and the blocks folder; returns (render arguments tail, env)."""
    tmp = pipe["tmp"] / (tag or variant)
    rt = H.write_runtime(tmp)
    html = H.component(variant)
    files = H.write_component(rt["registry"], html)
    served = H.served_of({H.FILE: html})
    shims = rt["runtime_dir"] + "/shims"
    rsha = _hf_host.load_runtime(rt["vendor"], shims, H.FPS, _cdp.browser_version(K.BROWSER))["runtime_sha256"]
    if runtime_edit:
        rsha = runtime_edit(rsha)
    entry = H.entry(files, served, rsha, **(entry_over or {}))
    if edit:
        edit(entry)
    blocks = H.blocks_folder(tmp, entry)
    tail = ["--blocks", blocks, "--vendor", rt["vendor"], "--hf-registry", rt["registry"]]
    env = {"RENDERER_TEST": "1", "RENDERER_HF_RUNTIME_DIR": rt["runtime_dir"]}
    return tail, env, tmp, rt


def render(pipe, tail, env, out, *more):
    return K.run_verb(*K.render_args(pipe["files"], out, "--jobs", "2", *tail, *more, slots=()), env=env)


def refusal(err: str) -> tuple:
    m = re.match(r"refused: (\S+)\s*(.*)", err)
    return (m.group(1), m.group(2).strip()) if m else (None, err[-300:])


def start_frame(pipe, tail, env, tmp):
    rc, out, err = render(pipe, tail, env, tmp / "dry", "--dry-run")
    assert rc == 0, err
    drawn = [e for e in out["beats_drawn"] if e["block"] == H.NAME]
    assert len(drawn) == 1
    return drawn[0]["start_frame"], drawn[0]["end_frame"], out


@needs_all
def test_the_clean_control_is_drawn_twice_byte_identical_and_the_summary_carries_the_two_hashes(pipe):
    tail, env, tmp, rt = setup(pipe)
    rc1, one, err1 = render(pipe, tail, env, tmp / "o1")
    assert rc1 == 0, err1
    rc2, two, err2 = render(pipe, tail, env, tmp / "o2")
    assert rc2 == 0, err2
    assert one["sha256"] == two["sha256"] and one["frames_rendered"] > 20
    proof = one["hf_proofs"][H.NAME]
    assert re.fullmatch(r"[0-9a-f]{64}", proof["served_sha256"]) and re.fullmatch(r"[0-9a-f]{64}", proof["runtime_sha256"])
    assert one["blocks"][H.NAME] == proof["served_sha256"] and one["seconds"]["gates"] >= 0
    assert [e["block"] for e in one["beats_drawn"] if e["preset"] == "keyword"] == [H.NAME]


@needs_all
def test_a_dry_run_reads_proves_and_names_the_beats_without_a_browser(pipe):
    tail, env, tmp, rt = setup(pipe, tag="dry")
    start, end, out = start_frame(pipe, tail, env, tmp)
    assert end - start > 20 and out["dry_run"] is True and out["hf_proofs"][H.NAME]["runtime_sha256"] == ""
    tail, env, tmp, rt = setup(pipe, tag="dry2", entry_over={"determinism": dict(H.entry({}, "a" * 64, "b" * 64)["determinism"])})
    rc, out, err = render(pipe, tail, env, tmp / "dry", "--dry-run")
    assert rc == 1 and refusal(err)[0] == "block_not_proven"


@needs_all
@pytest.mark.parametrize("variant,code,offset", [
    ("below_line", "drawn_below_line", 4),
    ("nothing", "block_not_drawn", 0),
    ("opaque", "drawn_below_line", 3),             # a full-frame layer (the corner cut keeps it RGBA): below the line from frame 3 of the entry
])
def test_the_exact_gates_report_a_pixel_where_it_should_not_be_as_advice_and_the_render_goes_on(pipe, variant, code, offset):
    """Video P0b: the line and the drawn floor of the exact gates are advice, never a refusal (the maintainer's principle of 2026-11-24)."""
    tail, env, tmp, rt = setup(pipe, variant)
    start, end, _ = start_frame(pipe, tail, env, tmp)
    rc, out, err = render(pipe, tail, env, tmp / "o")
    assert rc == 0, err
    row = next(r for r in out["advice"] if r["code"] == code)
    assert row["value"] >= 1 and row["default"] == 0 and list((tmp / "o").glob("render-*.mp4"))


@needs_all
def test_a_page_that_draws_on_the_speakers_face_is_drawn_twice_byte_identical_nothing_is_refused_for_the_face(pipe):
    """`face_dot` (alpha 1/255 at the face box's centre on frames 5-7) was found by the exact face gate; the maintainer removed that rule on 2026-11-24."""
    tail, env, tmp, rt = setup(pipe, "face_dot")
    rc1, one, err1 = render(pipe, tail, env, tmp / "o1")
    rc2, two, err2 = render(pipe, tail, env, tmp / "o2")
    assert rc1 == 0 and rc2 == 0, (err1, err2)
    assert one["sha256"] == two["sha256"]


@needs_all
def test_a_frame_the_browser_wrote_as_rgb_is_refused_before_anything_is_composed(pipe):
    tail, env, tmp, rt = setup(pipe, "opaque_no_clip")
    start, end, _ = start_frame(pipe, tail, env, tmp)
    rc, out, err = render(pipe, tail, env, tmp / "o")
    code, field = refusal(err)
    assert rc == 1 and code == "frame_not_rgba" and int(field.split()[1]) >= start + 3, err


@needs_all
def test_a_request_built_at_run_time_passes_the_lint_and_is_refused_by_the_page_policy(pipe):
    tail, env, tmp, rt = setup(pipe, "computed_fetch")
    rc, out, err = render(pipe, tail, env, tmp / "o")
    assert rc == 1 and refusal(err)[0] == "blocked_request", err


@needs_all
def test_a_family_the_host_did_not_declare_is_font_not_allowed(pipe):
    tail, env, tmp, rt = setup(pipe, "system_font")
    rc, out, err = render(pipe, tail, env, tmp / "o")
    assert rc == 1 and refusal(err)[0] == "font_not_allowed", err


@needs_all
@pytest.mark.parametrize("variant,rule", [("fontface", "fontface"), ("lint_storage", "storage")])
def test_the_lint_refuses_the_entrys_files_at_render_with_the_rule_and_the_line(pipe, variant, rule):
    tail, env, tmp, rt = setup(pipe, variant)
    rc, out, err = render(pipe, tail, env, tmp / "o")
    code, field = refusal(err)
    assert rc == 1 and code == "block_lint" and field.startswith(rule + ":" + H.FILE.replace(".", ".")) and re.search(r":\d+$", field), err


@needs_all
def test_a_missing_or_mismatched_determinism_record_is_block_not_proven(pipe):
    tail, env, tmp, rt = setup(pipe, tag="wrong-runtime", runtime_edit=lambda s: "0" * 64)
    rc, out, err = render(pipe, tail, env, tmp / "o")
    assert rc == 1 and refusal(err)[0] == "block_not_proven", err

    def other_served(e):
        e["determinism"]["served_sha256"] = "1" * 64
    tail, env, tmp, rt = setup(pipe, tag="wrong-served", edit=other_served)
    rc, out, err = render(pipe, tail, env, tmp / "o")
    assert rc == 1 and refusal(err)[0] == "block_not_proven", err


@needs_all
def test_a_file_that_is_not_the_pinned_one_or_an_edit_that_does_not_apply_is_refused(pipe):
    tail, env, tmp, rt = setup(pipe, tag="changed")
    path = tmp / "registry" / H.COMPONENT_DIR / H.FILE
    path.write_text(path.read_text() + "\n<!-- one more line -->\n")
    rc, out, err = render(pipe, tail, env, tmp / "o")
    assert rc == 1 and refusal(err)[0] == "block_hash", err
    tail, env, tmp, rt = setup(pipe, tag="served", entry_over={"served_sha256": "2" * 64})
    rc, out, err = render(pipe, tail, env, tmp / "o")
    assert rc == 1 and refusal(err)[0] == "block_hash", err


@needs_all
def test_the_image_folders_cannot_be_replaced_outside_test_mode(pipe):
    tail, env, tmp, rt = setup(pipe, tag="notest")
    rc, out, err = render(pipe, tail, {}, tmp / "o")
    assert rc == 2 and "--vendor and --hf-registry are for the tests" in err, err
