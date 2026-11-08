"""The compatibility run of tier A, `hyperframes-image/hf_compat.py` (V3b-3), and the host's `compat` verb, against a fictional survey folder
(components named `aster-pop`, `lane-caption` and so on, written here). No docker, no browser, no network: the guard's browser is a stub, and the
verb's container is a stub that writes what the real one would."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import renderer_kit  # noqa: F401  (puts the renderer folder on the path)
import _blocks
import hyperframes as H
from _text import Refusal

FOLDER = Path(__file__).resolve().parents[1] / "hyperframes-image"
spec = importlib.util.spec_from_file_location("hf_compat_under_test", FOLDER / "hf_compat.py")
C = importlib.util.module_from_spec(spec)
spec.loader.exec_module(C)

POP = """<template>
<style>#root { font-family: "Inter", sans-serif; }</style>
<div id="root" data-composition-id="aster-pop" data-duration="3" data-composition-variables='[{"id":"text","type":"string","max":24,"required":true}]'></div>
<script>
(function () {
  var tl = gsap.timeline({ paused: true });
  window.__timelines = window.__timelines || {};
  window.__timelines["aster-pop"] = tl;
})();
</script>
</template>
"""
ITEM = {"name": "x", "type": "hyperframes:component", "tags": ["reveal"]}
PRESETS = {"keyword": {"text": {"type": "text", "required": True}, "icon": {"type": "icon"}}, "number": {"value": {"type": "number", "required": True}}}


def write_survey(folder: Path, comps: dict, commit=C.REGISTRY_COMMIT, unfetched=()):
    """comps: {name: {rel: text}}; `unfetched` is a list of (name, rel) rows with no body."""
    rows = []
    for name, files in comps.items():
        entry = {"name": name, "files": []}
        for rel, text in files.items():
            raw = text.encode("utf-8")
            (folder / name).mkdir(parents=True, exist_ok=True)
            (folder / name / rel).write_bytes(raw)
            entry["files"].append({"rel": rel, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "fetched": True})
        for n, rel in unfetched:
            if n == name:
                entry["files"].append({"rel": rel, "bytes": 5000, "sha256": None, "fetched": False})
        rows.append(entry)
    (folder / "survey.json").write_text(json.dumps({"commit": commit, "components": rows}))
    return folder


def item(name, **over):
    return json.dumps(dict(ITEM, name=name, **over))


def make(tmp_path):
    survey = tmp_path / "survey"
    survey.mkdir()
    write_survey(survey, {
        "aster-pop": {"aster-pop.html": POP, "registry-item.json": item("aster-pop"), "README.md": "docs"},
        "lane-caption": {"lane-caption.html": POP, "registry-item.json": item("lane-caption", tags=["caption"])},
        "harbor-media": {"harbor-media.html": POP, "registry-item.json": item("harbor-media")},
        "dock-fetch": {"dock-fetch.html": POP.replace("var tl", 'fetch("/x"); var tl'), "registry-item.json": item("dock-fetch")},
        "Bad_Name": {"Bad_Name.html": POP, "registry-item.json": item("x")},
        "no-item": {"no-item.html": POP},
        "odd-kind": {"odd-kind.html": POP, "registry-item.json": item("odd-kind", type="hyperframes:block")},
        "dash-var": {"dash-var.html": POP.replace('"id":"text"', '"id":"x-y"'), "registry-item.json": item("dash-var")},
        "loose-pop": {"loose-pop.html": POP.replace('"id":"text"', '"id":"headlineText"'), "registry-item.json": item("loose-pop")},
    }, unfetched=[("harbor-media", "clip.mp4")])
    return survey


def licence_root(tmp_path, monkeypatch):
    root = tmp_path / "registry"
    root.mkdir()
    (root / "LICENSE").write_text("a fictional licence text\n")
    monkeypatch.setattr(C, "LICENCE_SHA256", hashlib.sha256(b"a fictional licence text\n").hexdigest())
    return str(root)


def run(tmp_path, monkeypatch, survey=None):
    return C.run(str(survey or make(tmp_path)), str(tmp_path), PRESETS, licence_root(tmp_path, monkeypatch), guard=lambda html: False)


def by_name(report):
    return {c["name"]: c for c in report["components"]}


# ---------------------------------------------------------------- the verdicts

def test_each_component_gets_the_verdict_of_its_own_fault_and_the_report_is_closed(tmp_path, monkeypatch):
    report = run(tmp_path, monkeypatch)
    got = {c["name"]: c["verdict"] for c in report["components"]}
    assert got == {"aster-pop": "admit-candidate", "lane-caption": "refuse:caption_tier_b_only", "harbor-media": "refuse:bundled_media",
                   "dock-fetch": "refuse:network", "invalid": "refuse:name_invalid", "no-item": "refuse:no_implementation", "odd-kind": "refuse:kind_not_supported",
                   "dash-var": "refuse:param_name", "loose-pop": "admit-candidate"}
    assert C.check_report(report) is report
    assert report["schema"] == 1 and report["commit"] == C.REGISTRY_COMMIT and report["licence_sha256"] == C.LICENCE_SHA256
    assert report["planted"] == {"total": len(C.PLANTED), "refused": len(C.PLANTED)} and report["planted"]["total"] >= 16


def test_an_admit_candidate_lists_its_two_files_its_parameters_its_preset_and_its_duration(tmp_path, monkeypatch):
    pop = by_name(run(tmp_path, monkeypatch))["aster-pop"]
    assert set(pop["files"]) == {"aster-pop.html", "registry-item.json"} and all(len(v) == 64 for v in pop["files"].values())
    assert pop["params"] == {"text": {"type": "text", "max": 24, "required": True}}
    assert pop["preset"] == "keyword" and pop["natural_duration"] == 3.0 and pop["dynamic"] is None
    assert pop["bytes"] == sum(len(x.encode()) for x in (POP, item("aster-pop"), "docs"))


def test_the_parameter_names_are_snake_case_and_a_block_that_fits_no_preset_has_none(tmp_path, monkeypatch):
    loose = by_name(run(tmp_path, monkeypatch))["loose-pop"]
    assert list(loose["params"]) == ["headline_text"] and loose["preset"] is None


def test_the_preset_rule_wants_every_parameter_in_the_preset_with_its_type_and_every_required_one_present():
    assert C.preset_for({"text": {"type": "text"}}, PRESETS) == "keyword"
    assert C.preset_for({"text": {"type": "text"}, "icon": {"type": "icon"}}, PRESETS) == "keyword"
    assert C.preset_for({"text": {"type": "text"}, "other": {"type": "text"}}, PRESETS) is None
    assert C.preset_for({"text": {"type": "color"}}, PRESETS) is None
    assert C.preset_for({}, PRESETS) is None
    assert C.preset_for({"value": {"type": "number"}}, PRESETS) == "number"


def test_a_licence_file_that_is_not_the_reviewed_text_refuses_every_component(tmp_path, monkeypatch):
    root = tmp_path / "registry"
    root.mkdir()
    (root / "LICENSE").write_text("some other text")
    report = C.run(str(make(tmp_path)), str(tmp_path), PRESETS, str(root), guard=lambda html: False)
    assert {c["verdict"] for c in report["components"]} == {"refuse:licence_unknown"} and report["licence_sha256"] == ""


# ---------------------------------------------------------------- the planted escapes and the run's own failures

def test_every_planted_escape_is_refused_and_the_control_is_admitted():
    tried = C.try_planted(lambda html: False)
    assert tried == {"total": len(C.PLANTED), "refused": len(C.PLANTED), "admitted": []}


def test_a_planted_escape_the_lint_admits_fails_the_whole_run_and_no_report_is_written(tmp_path, monkeypatch):
    real = C.W.lint
    monkeypatch.setattr(C.W, "lint", lambda html: [] if "window.foo = 1" in html else real(html))
    with pytest.raises(C.RunFailed) as caught:
        run(tmp_path, monkeypatch)
    assert (caught.value.code, caught.value.field) == ("planted_escape_admitted", "window_dot")
    code = C.main(["--survey", str(tmp_path / "survey"), "--out", str(tmp_path)])
    assert code == 1 and json.loads((tmp_path / "result.json").read_text()) == {"ok": False, "code": "planted_escape_admitted", "field": "window_dot"}
    assert not (tmp_path / "compat-report.json").exists()


def test_the_guard_can_refuse_what_the_lint_admits(monkeypatch):
    real = C.W.lint
    monkeypatch.setattr(C.W, "lint", lambda html: [] if "window.foo = 1" in html else real(html))
    assert C.try_planted(lambda html: "window.foo = 1" in html)["admitted"] == []


def test_a_lint_that_refuses_the_control_fails_the_run(monkeypatch):
    monkeypatch.setattr(C.W, "lint", lambda html: ["network"])
    with pytest.raises(C.RunFailed) as caught:
        C.try_planted(lambda html: False)
    assert caught.value.code == "control_refused"


def test_the_guard_is_false_when_the_browser_cannot_run(tmp_path):
    assert C.run_guard(C.control_component(), browser=str(tmp_path / "no-browser"), scratch=str(tmp_path)) is False


def test_a_file_that_differs_from_the_surveys_hash_fails_the_run(tmp_path, monkeypatch):
    survey = make(tmp_path)
    (survey / "aster-pop" / "aster-pop.html").write_text(POP + "<!-- changed -->")
    with pytest.raises(C.RunFailed) as caught:
        run(tmp_path, monkeypatch, survey)
    assert caught.value.code == "survey_hash_mismatch"


def test_a_survey_of_another_commit_or_a_bad_shape_is_refused(tmp_path):
    survey = tmp_path / "s"
    survey.mkdir()
    write_survey(survey, {}, commit="a" * 40)
    with pytest.raises(C.RunFailed) as caught:
        C.load_survey(str(survey))
    assert caught.value.code == "survey_invalid"
    (survey / "survey.json").write_text(json.dumps({"commit": C.REGISTRY_COMMIT, "components": [{"name": "a", "files": [{"rel": "x"}]}]}))
    with pytest.raises(C.RunFailed):
        C.load_survey(str(survey))


def test_the_command_line_writes_the_report_and_a_result_row(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    assert C.main(["--survey", str(make(tmp_path)), "--out", str(out)]) == 0
    assert json.loads((out / "result.json").read_text())["ok"] is True
    C.check_report(json.loads((out / "compat-report.json").read_text()))


def test_the_report_check_refuses_an_open_form():
    good = {"schema": 1, "commit": C.REGISTRY_COMMIT, "licence_sha256": "", "planted": {"total": 16, "refused": 16}, "components": []}
    assert C.check_report(good)
    for change in ({"planted": {"total": 16, "refused": 15}}, {"planted": {"total": 3, "refused": 3}}, {"schema": 2}, {"extra": 1},
                   {"components": [{"name": "a", "files": {}, "bytes": 0, "verdict": "refuse:free text", "dynamic": None, "params": {}, "preset": None, "natural_duration": None}]}):
        with pytest.raises(ValueError):
            C.check_report(dict(copy.deepcopy(good), **change))


def test_the_scripts_start_alone_from_a_clean_environment(tmp_path):
    env = {"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", "/nonexistent")}
    for script, flag in (("hf_compat.py", "--survey"), ("fetch_registry.py", "manifest")):
        done = subprocess.run([sys.executable, "-I", str(FOLDER / script), "--help"], capture_output=True, text=True, env=env, timeout=60, cwd=str(tmp_path))
        assert done.returncode == 0 and flag in done.stdout, done.stderr[-500:]


# ---------------------------------------------------------------- the host's verb

def test_the_survey_folder_check_wants_a_real_folder_of_regular_files_within_the_caps(tmp_path):
    survey = make(tmp_path)
    assert H.check_survey(str(survey)) > 5
    for bad in (str(tmp_path / "missing"), "relative/path"):
        with pytest.raises(Refusal) as caught:
            H.check_survey(bad)
        assert caught.value.code == "bad_survey"
    (survey / "aster-pop" / "link").symlink_to(survey / "survey.json")
    with pytest.raises(Refusal) as caught:
        H.check_survey(str(survey))
    assert caught.value.code == "bad_survey"
    (survey / "aster-pop" / "link").unlink()
    (survey / "aster-pop" / "big.js").write_bytes(b"x" * (H.SURVEY_FILE_CAP + 1))
    with pytest.raises(Refusal):
        H.check_survey(str(survey))


def test_the_overlay_presets_come_from_our_own_blocks():
    presets = H.overlay_presets(_blocks.load_catalogue(_blocks.BLOCKS_DIR))
    assert {"keyword", "number", "quote", "list"} <= set(presets) and presets["keyword"]["text"] == {"type": "text", "required": True}


def fake_world(tmp_path, monkeypatch, report=None, code=0, written=None):
    work = tmp_path / "work"
    work.mkdir(mode=0o700, exist_ok=True)
    monkeypatch.setattr(H, "work_folder", lambda path: str(work))
    monkeypatch.setattr(H, "check_hf_image", lambda: {"id": "sha256:" + "ef" * 32, "tag": "t", "definition": "d", "arch": "arm64"})
    monkeypatch.setattr(H.D, "daemon_facts", lambda: {"cpus": 4})
    calls = []

    def run(command, name, timeout):
        calls.append(command)
        out = [Path(command[i + 1].rsplit(":", 2)[0]) for i, w in enumerate(command) if w == "-v" and command[i + 1].endswith("/work/out:rw")][0]
        if report is not None:
            (out / "compat-report.json").write_text(json.dumps(report))
        (out / "result.json").write_text(json.dumps(written or {"ok": code == 0, "code": "survey_invalid", "field": "survey.json"} if code else {"ok": True}))
        return type("Done", (), {"returncode": code})()
    monkeypatch.setattr(H.box, "run", run)
    return work, calls


def args(survey, out, **over):
    base = dict(survey=str(survey), out=str(out), timeout=None, memory_mb=H.COMPAT_MEMORY_MB, dry_run=False)
    base.update(over)
    return type("Args", (), base)()


def test_the_verb_mounts_the_survey_read_only_with_no_network_and_copies_the_report_back(tmp_path, monkeypatch):
    survey = make(tmp_path)
    report = C.run(str(survey), str(tmp_path), PRESETS, licence_root(tmp_path, monkeypatch), guard=lambda h: False)
    work, calls = fake_world(tmp_path, monkeypatch, report)
    out = tmp_path / "report.json"
    result = H.verb_compat(args(survey, out))
    assert result["ok"] is True and result["admit_candidates"] == 2 and json.loads(out.read_text()) == report and oct(out.stat().st_mode & 0o777) == "0o600"
    command = calls[0]
    assert command[command.index("--network") + 1] == "none" and "%s:/work/survey:ro" % survey in command
    assert command[-8:-6] == ["-I", "/opt/hf-run/hf_compat.py"] and os.listdir(work) == []


def test_the_verb_refuses_a_container_that_wrote_an_open_report_or_failed(tmp_path, monkeypatch):
    survey = make(tmp_path)
    fake_world(tmp_path, monkeypatch, {"schema": 1})
    with pytest.raises(Refusal) as caught:
        H.verb_compat(args(survey, tmp_path / "r.json"))
    assert caught.value.code == "container_result_invalid"
    fake_world(tmp_path, monkeypatch, None, code=1)
    with pytest.raises(Refusal) as failed:
        H.verb_compat(args(survey, tmp_path / "r.json"))
    assert (failed.value.code, failed.value.field) == ("survey_invalid", "survey.json") and not (tmp_path / "r.json").exists()


def test_the_verb_never_overwrites_a_file_and_a_dry_run_runs_nothing(tmp_path, monkeypatch):
    survey = make(tmp_path)
    fake_world(tmp_path, monkeypatch, None)
    (tmp_path / "there.json").write_text("{}")
    with pytest.raises(Refusal) as caught:
        H.verb_compat(args(survey, tmp_path / "there.json"))
    assert caught.value.code == "bad_out"
    monkeypatch.setattr(H.box, "run", lambda *a, **k: pytest.fail("a container was started"))
    dry = H.verb_compat(args(survey, tmp_path / "new.json", dry_run=True))
    assert dry["dry_run"] is True and dry["command"][0] == "docker" and not (tmp_path / "new.json").exists()
