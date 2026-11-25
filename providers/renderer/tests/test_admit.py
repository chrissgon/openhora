"""The admission of a HyperFrames component (PF-a3): the comparator of the determinism test, the plan (commit, edits, lint, name), what is written and
what is not, and the measurement itself run offline with the host's Chromium and ffmpeg against the PF-a2 kit's fictional component and a stand-in
for the runtime (the real runtime exists only in the image: the supervisor's live step). Skipped with a reason where a tool is absent."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

import renderer_kit as K
import hf_second_kit as H
import _admit
import _admit_check
import _blocks
import _hf_host
from _text import Refusal

needs_all = pytest.mark.skipif(not (K.HAVE_FFMPEG and K.BROWSER), reason=K.SKIP_MEDIA + "; " + K.SKIP_BROWSER)
HASH = [hashlib.sha256(str(i).encode()).hexdigest() for i in range(6)]


def refused(fn, *a, **kw):
    with pytest.raises(Refusal) as info:
        fn(*a, **kw)
    return info.value


# ---------------------------------------------------------------- the comparator

def test_the_comparator_passes_four_identical_lists_and_counts_the_frames():
    assert _admit_check.compare_runs([HASH[:4]] * 3, HASH[:4]) == 4


@pytest.mark.parametrize("which", [0, 1, 2, 3])
def test_the_comparator_refuses_one_differing_frame_in_any_run_and_names_the_first_one(which):
    runs = [list(HASH[:5]) for _ in range(4)]
    runs[which][3] = HASH[5]
    err = refused(_admit_check.compare_runs, runs[:3], runs[3])
    assert (err.code, err.field) == ("determinism_failed", "frame 3")


def test_the_comparator_refuses_a_reverse_list_that_was_not_put_back_in_frame_order():
    forward = HASH[:5]
    assert refused(_admit_check.compare_runs, [forward] * 3, list(reversed(forward))).field == "frame 0"


def test_the_comparator_refuses_blocked_requests_exceptions_and_policy_violations_before_anything_else():
    runs = [HASH[:3]] * 3
    assert refused(_admit_check.compare_runs, runs, HASH[:3], blocked=1).code == "blocked_request"
    assert refused(_admit_check.compare_runs, runs, HASH[:3], csp=2).code == "blocked_request"
    assert refused(_admit_check.compare_runs, runs, HASH[:3], exceptions=1).code == "block_failed"


@pytest.mark.parametrize("forward,reverse,field", [
    ([HASH[:3]] * 2, HASH[:3], "runs"),                          # two forward runs, not three
    ([HASH[:3]] * 3, "abc", "runs"),
    ([HASH[:3], HASH[:3], HASH[:2]], HASH[:3], "frames"),        # lists of different lengths
    ([[], [], []], [], "frames"),                                # no frame at all
    ([HASH[:3], HASH[:3], ["nothex"] * 3], HASH[:3], "runs"),
])
def test_the_comparator_refuses_a_malformed_set_of_runs(forward, reverse, field):
    assert (refused(_admit_check.compare_runs, forward, reverse).code, refused(_admit_check.compare_runs, forward, reverse).field) == ("determinism_failed", field)


# ---------------------------------------------------------------- the plan and what is written

COMPONENT = "registry/components/oh-test-pop"


def git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                   env={"PATH": os.environ["PATH"], "HOME": os.environ["HOME"], "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"})


def world(tmp, html=None, name=H.NAME, entry_over=None):
    """A fictional registry clone (a git folder with the component committed), a runtime folder whose manifest names that commit, a copy of the
    committed blocks, and the person's file of our fields. Returns the pieces."""
    tmp = Path(tmp)
    source = tmp / "registry-clone"
    folder = source / COMPONENT
    folder.mkdir(parents=True)
    (folder / H.FILE).write_text(html if html is not None else H.component(), encoding="utf-8")
    git("init", "-q", cwd=source)
    git("add", ".", cwd=source)
    git("commit", "-q", "-m", "c", cwd=source)
    head = subprocess.run(["git", "-C", str(source), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    runtime = tmp / "hf-runtime"
    runtime.mkdir()
    (runtime / "registry.sha256").write_text("# commit %s\n# sha256  path\n%s  LICENSE\n" % (head, "4" * 64))
    (runtime / "NOTICE.md").write_text("# Notice\n\nbase text\n")
    blocks = tmp / "blocks"
    shutil.copytree(K.BLOCKS, blocks)
    entry = {"name": name, "preset": "keyword", "use_when": "a fictional pop for one short phrase, used by the tests only",
             "params": {"text": {"type": "text", "max": 24, "required": True}, "color": {"type": "color"}},
             "samples": [{"text": "Go"}, {"text": "Name every dollar"}], "natural_duration": 2.0, "bind": {"text": "var:text", "color": "css:--brand"}, "fixed": {},
             "theme_vars": dict(H.THEME_VARS), "edits": ["E1", "E2:Inter"], "font_map": {"Inter": "oh-text"}}
    entry.update(entry_over or {})
    entry_path = tmp / "entry.json"
    entry_path.write_text(json.dumps(entry))
    return {"source": str(source), "head": head, "runtime": str(runtime), "blocks": str(blocks), "entry": str(entry_path), "tmp": tmp}


def plan(w, **kw):
    return _admit.plan(source=w["source"], component=COMPONENT, entry_path=w["entry"], stage=kw.pop("stage", False), blocks_dir=w["blocks"], runtime=w["runtime"], **kw)


def tree(*folders):
    out = {}
    for folder in folders:
        for root, _, names in os.walk(folder):
            for n in names:
                p = os.path.join(root, n)
                out[p] = hashlib.sha256(open(p, "rb").read()).hexdigest()
    return out


RECORD = {"served_sha256": None, "runtime_sha256": "e" * 64, "samples": 2, "frames": 120, "runs": 4, "blocked": 0, "seconds": 3.5}


def measured(planned, **over):
    return dict(RECORD, served_sha256=planned["entry"]["served_sha256"], **over)


def test_the_plan_reads_hashes_edits_and_lints_and_writes_nothing(tmp_path):
    w = world(tmp_path)
    before = tree(w["tmp"])
    p = plan(w)
    assert tree(w["tmp"]) == before
    e = p["entry"]
    assert e["files"] == {H.FILE: hashlib.sha256(H.component().encode()).hexdigest()} and e["commit"] == w["head"] and e["tier"] == "A" and e["may_cross_face"] is False
    assert e["served_sha256"] == H.served_of({H.FILE: H.component()}) and "determinism" not in e and p["name_taken"] is False and p["staged"] is False
    assert p["summary"]["writes"][-1] == "blocks/hf/allowlist.json" and p["summary"]["plan"] is True


def test_a_clone_that_is_not_at_the_pinned_commit_is_admitted_commit(tmp_path):
    w = world(tmp_path)
    (Path(w["runtime"]) / "registry.sha256").write_text("# commit %s\n" % ("a" * 40))
    assert refused(plan, w).code == "admitted_commit"
    shutil.rmtree(Path(w["source"]) / ".git")
    (Path(w["runtime"]) / "registry.sha256").write_text("# commit %s\n" % w["head"])
    assert refused(plan, w).code == "admitted_commit"


@pytest.mark.parametrize("edits,code", [(["E1", "E2:Inter", "E3"], "block_edit"), (["E2:Inter"], "block_lint"), (["E1", "E2:Roboto"], "block_edit")])
def test_an_edit_beyond_e1_and_e2_or_one_that_does_not_apply_is_refused(tmp_path, edits, code):
    w = world(tmp_path, entry_over={"edits": edits})
    assert refused(plan, w).code == code             # E3 is no edit; the CDN line left in is a remote reference; a family not in `font_map` is not an edit of this entry


def test_an_edit_that_finds_nothing_to_change_is_block_edit(tmp_path):
    w = world(tmp_path, entry_over={"edits": ["E1", "E2:Inter"], "font_map": {"Inter": "oh-text"}}, html=H.component().replace("Inter", "Roboto"))
    assert refused(plan, w).code == "block_edit"


def test_an_entry_the_lint_refuses_is_refused_after_the_edits(tmp_path):
    w = world(tmp_path, html=H.component("lint_storage"))
    assert refused(plan, w).code == "block_lint"


def test_an_entry_file_with_a_key_that_is_not_ours_or_a_key_missing_is_refused(tmp_path):
    w = world(tmp_path, entry_over={"may_cross_face": True})
    assert refused(plan, w).code == "admit_entry"
    w = world(tmp_path / "b")
    e = json.loads(Path(w["entry"]).read_text())
    del e["bind"]
    Path(w["entry"]).write_text(json.dumps(e))
    assert refused(plan, w).code == "admit_entry"


def test_a_name_another_block_holds_is_staged_and_the_catalogue_never_loads_the_staged_file(tmp_path):
    w = world(tmp_path, name="hf:spring-pop")
    p = plan(w)
    assert p["name_taken"] is True and p["staged"] is True and p["target"] == os.path.join(w["runtime"], "staged", "spring-pop.json")
    done = _admit.write_all(p, _admit.record_of(measured(p), p, "openhora-renderer:test", "2026-11-24"))
    staged = json.loads(Path(p["target"]).read_text())
    assert done["staged"] is True and staged["name"] == "hf:spring-pop" and staged["determinism"]["image"] == "openhora-renderer:test"
    assert _admit.read_staged(p["target"], w["head"])["name"] == "hf:spring-pop"
    allow = json.loads((Path(w["blocks"]) / "hf" / "allowlist.json").read_text())
    assert allow["blocks"] == [] and "hf-runtime" not in "".join(_blocks.read_pins(w["blocks"])[1])
    assert _blocks.load_catalogue(w["blocks"])["blocks"]["hf:spring-pop"]["tier"] == "B"        # the port still holds the name
    rows = (Path(w["runtime"]) / "registry.sha256").read_text().splitlines()
    assert rows[-1] == "%s  %s/%s" % (p["entry"]["files"][H.FILE], COMPONENT, H.FILE) and rows[2].endswith("  LICENSE")
    assert "<!-- admitted: hf:spring-pop -->" in (Path(w["runtime"]) / "NOTICE.md").read_text()


def test_a_sample_with_accents_is_written_as_escapes_so_that_the_file_is_ascii(tmp_path):
    w = world(tmp_path, entry_over={"samples": [{"text": "Go"}, {"text": "Promo\u00e7\u00e3o"}]})
    p = plan(w, stage=True)
    _admit.write_all(p, _admit.record_of(measured(p), p, "openhora-renderer:test", "2026-11-24"))
    raw = Path(p["target"]).read_bytes()
    assert raw.isascii() and json.loads(raw)["samples"][1]["text"] == "Promo\u00e7\u00e3o"


def test_stage_asks_for_the_staged_file_even_when_the_name_is_free(tmp_path):
    w = world(tmp_path)
    p = plan(w, stage=True)
    assert p["staged"] is True and p["name_taken"] is False
    _admit.write_all(p, _admit.record_of(measured(p), p, "openhora-renderer:test", "2026-11-24"))
    assert os.path.exists(os.path.join(w["runtime"], "staged", "oh-test-pop.json"))
    assert json.loads((Path(w["blocks"]) / "hf" / "allowlist.json").read_text())["blocks"] == []


def test_a_free_name_goes_into_the_allowlist_and_the_pins_and_the_catalogue_follow(tmp_path):
    w = world(tmp_path)
    p = plan(w)
    done = _admit.write_all(p, _admit.record_of(measured(p), p, "openhora-renderer:test", "2026-11-24"))
    allow = json.loads((Path(w["blocks"]) / "hf" / "allowlist.json").read_text())
    assert done["staged"] is False and allow["registry_commit"] == w["head"] and [b["name"] for b in allow["blocks"]] == [H.NAME]
    cat = _blocks.load_catalogue(w["blocks"])
    assert cat["blocks"][H.NAME]["determinism"]["runtime_sha256"] == "e" * 64 and (Path(w["blocks"]) / "catalogue.json").exists()
    again = _admit.plan(source=w["source"], component=COMPONENT, entry_path=w["entry"], stage=False, blocks_dir=w["blocks"], runtime=w["runtime"])
    assert again["name_taken"] is True and again["staged"] is True                    # a second admission of the same name stages instead of replacing


def test_a_measurement_that_does_not_match_the_plan_writes_nothing(tmp_path):
    w = world(tmp_path)
    p = plan(w)
    before = tree(w["tmp"])
    for bad in (dict(measured(p), served_sha256="1" * 64), measured(p, runs=3), measured(p, blocked=1), measured(p, samples=1), measured(p, runtime_sha256="short"),
                measured(p, frames=0)):
        assert refused(_admit.record_of, bad, p, "openhora-renderer:test").code == "admit_result"
    assert tree(w["tmp"]) == before


def test_a_manifest_row_that_exists_with_another_hash_is_refused_and_nothing_is_changed(tmp_path):
    w = world(tmp_path)
    p = plan(w)
    row = "%s/%s" % (COMPONENT, H.FILE)
    (Path(w["runtime"]) / "registry.sha256").write_text("# commit %s\n%s  %s\n" % (w["head"], "9" * 64, row))
    before = tree(w["tmp"])
    assert refused(_admit.write_all, p, _admit.record_of(measured(p), p, "openhora-renderer:test", "2026-11-24")).code == "registry_row_differs"
    assert tree(w["tmp"]) == before


def test_the_notice_entry_is_written_once(tmp_path):
    w = world(tmp_path)
    p = plan(w, stage=True)
    rec = _admit.record_of(measured(p), p, "openhora-renderer:test", "2026-11-24")
    _admit.write_all(p, rec)
    _admit.write_all(p, rec)                                                       # a replay of the same staged file is not an error
    text = (Path(w["runtime"]) / "NOTICE.md").read_text()
    assert text.count("<!-- admitted: ") == 1 and (Path(w["runtime"]) / "registry.sha256").read_text().count(H.FILE) == 1


# ---------------------------------------------------------------- the measurement, offline

def check_args(tmp, variant="clean", samples=None):
    """The arguments of `admit-check` for the fictional component's variant with the stand-in runtime; the candidate entry has no determinism record."""
    rt = H.write_runtime(tmp)
    html = H.component(variant)
    files = H.write_component(rt["registry"], html)
    served = H.served_of({H.FILE: html})
    entry = H.entry(files, served, "0" * 64)
    del entry["determinism"]
    if samples:
        entry["samples"] = samples
    entry_path = Path(tmp) / "entry.json"
    entry_path.write_text(json.dumps(entry))
    scratch = Path(tmp) / "scratch"
    scratch.mkdir()
    args = ["admit-check", "--entry", entry_path, "--component-dir", Path(rt["registry"]) / H.COMPONENT_DIR, "--vocabulary", K.VOCABULARY, "--blocks", K.BLOCKS,
            "--blocks-sha256", K.BLOCKS_SHA256, "--scratch", scratch, "--vendor", rt["vendor"], "--jobs", "2"]
    return args, {"RENDERER_TEST": "1", "RENDERER_HF_RUNTIME_DIR": rt["runtime_dir"]}, served


@needs_all
def test_the_clean_component_passes_the_whole_measurement_and_the_result_says_what_was_measured(tmp_path):
    args, env, served = check_args(tmp_path, "stable", samples=[{"text": "Go"}, {"text": "Name every dollar"}])
    rc, out, err = K.run_verb(*args, env=env)
    assert rc == 0, err
    assert out["served_sha256"] == served and out["runs"] == 4 and out["blocked"] == 0 and out["samples"] == 2 and re.fullmatch(r"[0-9a-f]{64}", out["runtime_sha256"])
    assert [s["frames"] for s in out["per_sample"]] == [out["per_sample"][0]["frames"]] * 2 and out["frames"] == 2 * out["per_sample"][0]["frames"] > 40
    assert out["seconds"] > 0 and not list(Path(tmp_path, "scratch").glob("*/frames"))


@needs_all
def test_a_page_whose_pixels_depend_on_the_frames_drawn_before_them_is_refused_by_the_reverse_run(tmp_path):
    """The fade of the plain clean control leaves Chrome's raster of the frames after it different from the same frames drawn first: forward runs agree
    with each other and the reverse run does not. It is a property of the page's layers, found only because one run seeks the last frame first."""
    args, env, _ = check_args(tmp_path, "clean", samples=[{"text": "Go"}])
    rc, out, err = K.run_verb(*args, env=env)
    assert rc == 1 and err.startswith("refused: determinism_failed sample 1 frame "), err


@needs_all
def test_a_page_that_draws_from_math_random_is_refused_by_the_comparator(tmp_path):
    args, env, _ = check_args(tmp_path, "math_random", samples=[{"text": "Go"}])
    rc, out, err = K.run_verb(*args, env=env)
    assert rc == 1 and err.startswith("refused: determinism_failed sample 1 frame "), err


@needs_all
@pytest.mark.parametrize("variant,code", [("face_dot_default", "overlay_hits_face"), ("below_default_line", "caption_below_line"), ("nothing", "block_not_drawn"),
                                          ("computed_fetch", "blocked_request"), ("system_font", "font_not_allowed"), ("fontface", "block_lint")])
def test_every_gate_of_the_second_contract_stops_an_admission_with_its_own_code(tmp_path, variant, code):
    args, env, _ = check_args(tmp_path, variant, samples=[{"text": "Go"}])
    rc, out, err = K.run_verb(*args, env=env)
    assert rc == 1 and err.startswith("refused: %s" % code), err


@needs_all
def test_the_vendor_folder_cannot_be_replaced_outside_test_mode(tmp_path):
    args, env, _ = check_args(tmp_path, samples=[{"text": "Go"}])
    rc, out, err = K.run_verb(*args, env={})
    assert rc == 2 and "--vendor is for the tests" in err, err


def test_the_math_random_variant_is_in_the_kit_and_the_lint_does_not_see_it():
    import _hf_lint
    assert "Math.random" in H.component("math_random")
    _hf_lint.check({H.FILE: _hf_host.apply_edits({H.FILE: H.component("math_random").encode()}, ["E1", "E2:Inter"], {"Inter": "oh-text"})[H.FILE]})


def test_the_spring_pop_entry_file_is_a_valid_entry_of_our_fields_and_stays_inside_the_components_own_bounds():
    path = K.RENDERER / "hf-runtime" / "entries" / "spring-pop.json"
    src = _admit.read_source(str(path))
    commit = _admit.read_manifest(str(K.RENDERER / "hf-runtime" / "registry.sha256"))[0]
    entry = _admit.build_entry(src, commit, "registry/components/spring-pop", "spring-pop.html", {"spring-pop.html": "a" * 64}, "b" * 64)
    probe = dict(entry, determinism={"served_sha256": "b" * 64, "runtime_sha256": "c" * 64, "samples": 3, "frames": 1, "runs": 4, "blocked": 0,
                                     "date": "2026-11-24", "image": "probe", "seconds": 0})
    _blocks.check_block(probe, "spring-pop", "hf", registry_commit=commit)
    assert entry["name"] == "hf:spring-pop" and entry["may_cross_face"] is False and "--bg" not in entry["theme_vars"] and entry["edits"] == ["E1", "E2:Inter"]
    assert entry["use_when"] == "a single short keyword that should pop in, no icon" and set(entry["params"]) == {"text", "color"} and entry["params"]["text"]["max"] == 24
    assert entry["bind"]["text"] == "var:text" and entry["fixed"] == {"overshoot": 1.4, "fromScale": 0.9}
    assert 1.1 <= entry["fixed"]["overshoot"] <= 2 and 0.8 <= entry["fixed"]["fromScale"] <= 0.97            # spring-pop's declared ranges
    assert sorted(entry["theme_vars"]) == ["--border", "--brand", "--fg", "--font-body", "--font-display", "--surface"]
    texts = [s["text"] for s in entry["samples"]]
    assert len(texts) == 3 and len(min(texts, key=len)) <= 3 and max(len(t) for t in texts) == 24 and any(re.search(r"[^\x00-\x7f]", t) for t in texts)
