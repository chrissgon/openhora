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
def good_guard(html):
    """The browser as it should answer: the control runs through, every planted escape is stopped."""
    return "ran" if html == C.control_component() else "escaped-refused"


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
    return C.run(str(survey or make(tmp_path)), str(tmp_path), PRESETS, licence_root(tmp_path, monkeypatch), guard=good_guard)


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
    assert report["planted"] == {"total": len(C.PLANTED), "refused": len(C.PLANTED), "guarded": sum(1 for r in C.PLANTED if r[4])} and report["planted"]["total"] >= 16


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
    report = C.run(str(make(tmp_path)), str(tmp_path), PRESETS, str(root), guard=good_guard)
    assert {c["verdict"] for c in report["components"]} == {"refuse:licence_unknown"} and report["licence_sha256"] == ""


# ---------------------------------------------------------------- the planted escapes and the run's own failures

def test_every_planted_escape_is_refused_and_the_control_is_admitted():
    tried = C.try_planted(good_guard)
    runtime = sum(1 for row in C.PLANTED if row[4])
    assert tried == {"total": len(C.PLANTED), "refused": len(C.PLANTED), "admitted": [], "guarded": runtime} and runtime >= 14


def test_a_planted_escape_the_lint_admits_fails_the_whole_run_and_no_report_is_written(tmp_path, monkeypatch):
    real = C.W.lint
    monkeypatch.setattr(C.W, "lint", lambda html: [] if "window.foo = 1" in html else real(html))
    with pytest.raises(C.RunFailed) as caught:
        run(tmp_path, monkeypatch)
    assert (caught.value.code, caught.value.field) == ("planted_escape_admitted", "window_dot")
    monkeypatch.setattr(C, "guard_verdict", good_guard)
    code = C.main(["--survey", str(tmp_path / "survey"), "--out", str(tmp_path)])
    assert code == 1 and json.loads((tmp_path / "result.json").read_text()) == {"ok": False, "code": "planted_escape_admitted", "field": "window_dot"}
    assert not (tmp_path / "compat-report.json").exists()


def test_a_planted_escape_refused_with_another_code_than_the_one_it_declares_counts_as_admitted(monkeypatch):
    real = C.W.lint
    monkeypatch.setattr(C.W, "lint", lambda html: ["media"] if "window.foo = 1" in html else real(html))
    assert C.try_planted(good_guard)["admitted"] == ["window_dot"]


def test_the_guard_is_proven_first_the_control_must_run_in_the_browser_or_the_run_fails_guard_unavailable():
    for verdict in ("unavailable", "error", "escaped-refused"):
        with pytest.raises(C.RunFailed) as caught:
            C.try_planted(lambda html, v=verdict: v)
        assert (caught.value.code, caught.value.field) == ("guard_unavailable", "control")


def test_a_runtime_escape_the_guard_does_not_stop_fails_the_run_guard_unavailable_naming_it():
    def lax(html):
        return "ran"
    with pytest.raises(C.RunFailed) as caught:
        C.try_planted(lax)
    assert caught.value.code == "guard_unavailable" and caught.value.field == next(row[0] for row in C.PLANTED if row[4])


def test_every_planted_escape_that_acts_at_run_time_is_put_in_front_of_the_guard_with_the_lint_out_of_the_way():
    seen = []
    C.try_planted(lambda html: seen.append(html) or good_guard(html))
    runtime = [C.planted_component(row)[1] for row in C.PLANTED if row[4]]
    assert seen[0] == C.control_component() and seen[1:] == runtime


def test_a_lint_that_refuses_the_control_fails_the_run(monkeypatch):
    monkeypatch.setattr(C.W, "lint", lambda html: ["network"])
    with pytest.raises(C.RunFailed) as caught:
        C.try_planted(lambda html: False)
    assert caught.value.code == "control_refused"


def test_the_guard_verdict_is_unavailable_when_the_browser_or_the_scratch_folder_cannot_be_used(tmp_path):
    assert C.guard_verdict(C.control_component(), browser=str(tmp_path / "no-browser"), scratch=str(tmp_path)) == "unavailable"
    assert C.guard_verdict(C.control_component(), browser="/bin/true", scratch=str(tmp_path / "no-scratch")) == "unavailable"


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


def test_the_command_line_writes_the_report_and_a_result_row(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "guard_verdict", good_guard)
    out = tmp_path / "out"
    out.mkdir()
    assert C.main(["--survey", str(make(tmp_path)), "--out", str(out)]) == 0
    assert json.loads((out / "result.json").read_text())["ok"] is True
    C.check_report(json.loads((out / "compat-report.json").read_text()))


def test_the_report_check_refuses_an_open_form():
    good = {"schema": 1, "commit": C.REGISTRY_COMMIT, "licence_sha256": "", "planted": {"total": 16, "refused": 16, "guarded": 14}, "components": []}
    assert C.check_report(good)
    for change in ({"planted": {"total": 16, "refused": 15, "guarded": 14}}, {"planted": {"total": 3, "refused": 3, "guarded": 3}}, {"planted": {"total": 16, "refused": 16}}, {"schema": 2}, {"extra": 1},
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
    report = C.run(str(survey), str(tmp_path), PRESETS, licence_root(tmp_path, monkeypatch), guard=good_guard)
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


# ---------------------------------------------------------------- the review's fixes

def enum_component(options, **row):
    spec = dict({"id": "mode", "type": "enum", "options": options}, **row)
    return POP.replace('data-composition-variables=\'[{"id":"text","type":"string","max":24,"required":true}]\'', "data-composition-variables='%s'" % json.dumps([spec]))


def test_an_enum_variable_is_a_choice_parameter_with_the_options_the_component_declares(tmp_path, monkeypatch):
    survey = tmp_path / "survey"
    survey.mkdir()
    write_survey(survey, {"aster-pick": {"aster-pick.html": enum_component([{"value": "coarse", "label": "Coarse"}, {"value": "med", "label": "Medium"}], default="med"),
                                         "registry-item.json": item("aster-pick")},
                          "aster-bad": {"aster-bad.html": enum_component([{"value": "Two Words"}]), "registry-item.json": item("aster-bad")},
                          "aster-none": {"aster-none.html": enum_component([]), "registry-item.json": item("aster-none")}})
    report = C.run(str(survey), str(tmp_path), PRESETS, licence_root(tmp_path, monkeypatch), guard=good_guard)
    got = by_name(report)
    assert got["aster-pick"]["verdict"] == "admit-candidate"
    assert got["aster-pick"]["params"] == {"mode": {"type": "choice", "values": ["coarse", "med"], "default": "med"}}
    assert got["aster-bad"]["verdict"] == "refuse:variables_untyped" and got["aster-none"]["verdict"] == "refuse:variables_untyped"
    C.check_report(report)
    bad = copy.deepcopy(report)
    for comp in bad["components"]:
        if comp["name"] == "aster-pick":
            comp["params"]["mode"]["values"] = ["Two Words"]
    with pytest.raises(ValueError):
        C.check_report(bad)


def test_hyperframes_py_does_not_load_the_admission_modules_until_compat_runs():
    code = ("import sys; sys.path.insert(0, %r); import hyperframes; print('hf_compat' in sys.modules, 'hf_wrap' in sys.modules, "
            "'hf_compat' in vars(hyperframes))" % str(FOLDER.parent))
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd="/", timeout=120, env={"PATH": os.environ["PATH"], "HOME": "/nonexistent"})
    assert done.stdout.split() == ["False", "False", "False"], done.stderr[-500:]
    assert H.COMPAT_OUT_NAMES == C.OUT_NAMES and H.SURVEY_MAX_FILES == C.MAX_FILES and H.SURVEY_MAX_BYTES == C.MAX_TOTAL_BYTES and H.SURVEY_FILE_CAP == C.MAX_FILE_BYTES


def test_a_survey_path_that_goes_through_a_link_is_refused_and_the_refusal_names_the_real_path(tmp_path):
    survey = make(tmp_path)
    link = tmp_path / "link"
    link.symlink_to(survey)
    with pytest.raises(Refusal) as caught:
        H.check_survey(str(link))
    assert caught.value.code == "bad_survey" and str(os.path.realpath(survey)) in caught.value.reason
