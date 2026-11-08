"""The pieces of step 7.8 (the dynamic run of tier A) that need no container: the test allowlist entry and blocks folder of a candidate (drawn by the
composer offline), the registry folder with its hash check, the test-mode mount of the host, the planted escape (admitted by the lint, stopped by the
guard in `node`), the page that survives a stopped escape so the measure step can read its flag, and the closed report. The live part is
`test_hf_tier_a_live.py`, which the supervisor runs."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys

import pytest

import renderer_kit as K
import tier_a_kit as T
import _blocks
import _hf_compose as C
import hyperframes as H
from _text import Refusal
from test_hf_wrap import NODE, run_guard_script, W

POP = """<template>
<style>#root { font-family: "Inter", sans-serif; }</style>
<div id="root" data-composition-id="aster-pop" data-duration="3"></div>
<script>
(function () {
  var tl = gsap.timeline({ paused: true });
  window.__timelines = window.__timelines || {};
  window.__timelines["aster-pop"] = tl;
})();
</script>
</template>
"""


def comp_of(name="aster-pop", html=POP):
    files = {name + ".html": html.encode(), "registry-item.json": json.dumps({"name": name, "type": "hyperframes:component"}).encode()}
    return {"name": name, "files": {k: hashlib.sha256(v).hexdigest() for k, v in files.items()}, "natural_duration": 2.5}, files


def survey_of(tmp_path, comp_files):
    folder = tmp_path / "survey"
    for name, files in comp_files.items():
        (folder / name).mkdir(parents=True)
        for rel, raw in files.items():
            (folder / name / rel).write_bytes(raw)
    return str(folder)


@pytest.fixture(scope="module")
def docs(tmp_path_factory):
    return K.hf_documents(tmp_path_factory.mktemp("docs"))


def test_a_candidate_becomes_a_test_allowlist_entry_on_the_keyword_preset_and_the_committed_allowlist_is_untouched(tmp_path):
    before = (K.BLOCKS / "hf" / "allowlist.json").read_bytes()
    comp, _ = comp_of()
    folder = T.blocks_folder(tmp_path, comp)
    catalogue = _blocks.load_catalogue(folder)
    block = catalogue["blocks"]["hf:aster-pop"]
    assert block["tier"] == "A" and block["preset"] == "keyword" and block["files"] == comp["files"] and block["implementations"] == {"gsap": "aster-pop.html"}
    assert catalogue["engines"]["hyperframes"]["presets"]["keyword"] == "hf:aster-pop" and catalogue["engines"]["hyperframes"]["runtimes"] == ["gsap", "renderat"]
    assert (K.BLOCKS / "hf" / "allowlist.json").read_bytes() == before and json.loads(before)["blocks"] == []


def test_the_composer_draws_the_candidate_on_the_keyword_beat_offline_and_the_page_survives_a_stopped_escape(tmp_path, docs):
    comp, _ = comp_of()
    catalogue = _blocks.load_catalogue(T.blocks_folder(tmp_path, comp))
    data, edl, beats, vocab = copy.deepcopy(docs)
    os.makedirs(tmp_path / "page")
    result = C.write_page(data, edl, beats, vocab, catalogue, str(tmp_path / "page"), edl["fps"])
    assert result["runtimes"]["hf:aster-pop"] == "gsap" and result["beats_drawn"] >= 1
    page = (tmp_path / "page" / "index.html").read_text(encoding="utf-8")
    assert "try { __hfTierA[0](main, V, gsap); } catch (e) { if (!window.__hfEscape) throw e; }" in page
    rows = json.loads((tmp_path / "page" / "instances.json").read_text())
    assert rows["0"]["name"] == "hf:aster-pop" and rows["0"]["files"] == comp["files"]


def test_the_registry_folder_holds_exactly_the_two_files_of_each_candidate_and_refuses_a_file_that_differs_from_the_report(tmp_path):
    comp, files = comp_of()
    root = T.registry_folder(tmp_path, survey_of(tmp_path, {"aster-pop": dict(files, **{"README.md": b"docs"})}), [comp])
    folder = os.path.join(root, "registry", "components", "aster-pop")
    assert sorted(os.listdir(folder)) == ["aster-pop.html", "registry-item.json"]
    other = tmp_path / "two"
    other.mkdir()
    tampered = dict(files, **{"aster-pop.html": files["aster-pop.html"] + b"\n"})
    with pytest.raises(AssertionError):
        T.registry_folder(other, survey_of(other, {"aster-pop": tampered}), [comp])


def test_the_host_mounts_the_registry_folder_over_the_images_only_in_test_mode_and_only_a_real_absolute_folder(tmp_path, monkeypatch):
    registry = tmp_path / "reg"
    registry.mkdir()
    link = tmp_path / "link"
    link.symlink_to(registry)
    args = type("A", (), {"cpuset": None})()
    monkeypatch.setattr(H, "hf_limits", lambda a: (6144, 2))
    image = {"id": "sha256:" + "ef" * 32}

    def command():
        return H.hf_command(args, image, str(tmp_path), 30, 600)[1]

    for env in ({}, {"RENDERER_REGISTRY_DIR": str(registry)}, {"RENDERER_TEST": "1"}):
        for key in ("RENDERER_TEST", "RENDERER_REGISTRY_DIR"):
            monkeypatch.delenv(key, raising=False)
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        assert not any(w.endswith(":/opt/hf-registry:ro") for w in command()), env
    monkeypatch.setenv("RENDERER_TEST", "1")
    monkeypatch.setenv("RENDERER_REGISTRY_DIR", str(registry))
    assert "%s:/opt/hf-registry:ro" % registry in command() and command()[command().index("--network") + 1] == "none"
    for bad in (str(link), "relative", str(tmp_path / "missing")):
        monkeypatch.setenv("RENDERER_REGISTRY_DIR", bad)
        with pytest.raises(Refusal) as caught:
            command()
        assert caught.value.code == "bad_registry_dir"


def test_the_planted_escape_is_admitted_by_the_text_lint_and_its_files_hash_as_the_report_wants():
    comp, files = T.planted_component(), T.planted_files()
    assert W.lint(files[T.PLANTED_NAME + ".html"].decode()) == []
    assert comp["files"] == {rel: hashlib.sha256(raw).hexdigest() for rel, raw in files.items()}
    assert set(comp["files"]) == {T.PLANTED_NAME + ".html", "registry-item.json"}


@pytest.mark.skipif(NODE is None, reason="node is not on the path")
def test_the_guard_stops_the_planted_escape_and_sets_the_flag_the_measure_step_reads(tmp_path):
    out = run_guard_script(T.planted_files()[T.PLANTED_NAME + ".html"].decode(), tmp_path)
    assert out["error"] == "hf-escape" and out["flag"] is True


def test_a_candidate_is_fit_only_when_both_renders_agree_draw_the_block_and_pass_the_gates():
    comp, _ = comp_of()
    ok = {"sha256": "a" * 64, "beats_drawn": 4, "runtimes": {"hf:aster-pop": "gsap"}, "gate": {"frames": 90, "boxes": 12, "pixel_min_psnr_db": 40.5, "pixel_ranges": 2, "extra": 1}}
    row = T.candidate_row(comp, [(0, ok), (0, dict(ok))])
    assert row["dynamic"] == "fit" and row["repeatable"] is True and row["gate"] == {"frames": 90, "boxes": 12, "pixel_min_psnr_db": 40.5, "pixel_ranges": 2}
    assert T.candidate_row(comp, [(0, ok), (0, dict(ok, sha256="b" * 64))])["dynamic"] == "refuse:not_repeatable"
    assert T.candidate_row(comp, [(0, dict(ok, beats_drawn=0)), (0, ok)])["dynamic"] == "refuse:not_drawn"
    assert T.candidate_row(comp, [(1, {"ok": False, "code": "overlay_hits_face", "field": "x"})])["dynamic"] == "refuse:overlay_hits_face"
    assert T.candidate_row(comp, [(1, {"ok": False, "code": "Free Text!"})])["dynamic"] == "refuse:no_result"
    assert T.candidate_row(comp, [(1, None)])["dynamic"] == "refuse:no_result"
    assert T.candidate_row(comp, [(0, ok)])["dynamic"] == "refuse:no_result"


def test_the_report_is_closed_and_is_written_whole_each_time(tmp_path):
    comp, _ = comp_of()
    path = str(tmp_path / "dynamic.json")
    ok = {"sha256": "a" * 64, "beats_drawn": 1, "runtimes": {"hf:aster-pop": "gsap"}, "gate": {"frames": 9, "boxes": 1}}
    T.update_report(path, candidates=[T.candidate_row(comp, [(0, ok), (0, ok)])])
    doc = T.update_report(path, planted={"name": T.PLANTED_NAME, "code": "block_escaped", "field": "frame 0"})
    assert json.loads(open(path).read()) == doc and set(doc) == {"schema", "commit", "candidates", "planted"} and not os.path.exists(path + ".part")
    for bad in ({"candidates": [{"name": "x", "dynamic": "free text", "render_sha256": None, "repeatable": None, "gate": {}}]},
                {"planted": {"name": "other", "code": "block_escaped", "field": "frame 0"}},
                {"planted": {"name": T.PLANTED_NAME, "code": "Block Escaped", "field": "frame 0"}},
                {"candidates": [{"name": "x", "dynamic": "fit", "render_sha256": "zz", "repeatable": True, "gate": {}}]}):
        with pytest.raises(ValueError):
            T.check_report(dict(doc, **bad))


def test_the_live_file_skips_without_the_docker_flag_and_names_every_variable_it_needs():
    text = (K.RENDERER / "tests" / "test_hf_tier_a_live.py").read_text(encoding="utf-8")
    for name in ("WB_HYPERFRAMES_DOCKER_TESTS", "WB_TIER_A_SURVEY", "WB_TIER_A_REPORT", "WB_TIER_A_OUT", "WB_TIER_A_ONLY", "RENDERER_REGISTRY_DIR", "OPENHORA_STATE_DIR"):
        assert name in text, name
    done = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(K.RENDERER / "tests" / "test_hf_tier_a_live.py")],
                          capture_output=True, text=True, timeout=300, env={k: v for k, v in os.environ.items() if k != "WB_HYPERFRAMES_DOCKER_TESTS"}, cwd=str(K.RENDERER / "tests"))
    assert "2 skipped" in done.stdout, done.stdout[-600:] + done.stderr[-300:]


def test_the_live_file_reads_the_persons_variables_at_import_and_never_inside_a_function():
    """A conftest fixture points OPENHORA_STATE_DIR at a temporary folder before a test runs; a variable read when a fixture or a test runs would be that
    folder (the first run of step 7.8 failed this way: `image_not_recorded`). So the environment is read at module level only; inside a function it is only
    copied whole into a subprocess's environment (`dict(os.environ, ...)`), and the state folder is written back by the `real_state` fixture."""
    import ast
    path = K.RENDERER / "tests" / "test_hf_tier_a_live.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    top_reads, inside_reads = set(), []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "environ" and isinstance(node.value, ast.Name) and node.value.id == "os":
            owner = node
            while owner in parents and not isinstance(owner, (ast.FunctionDef, ast.AsyncFunctionDef)):
                owner = parents[owner]
            if not isinstance(owner, (ast.FunctionDef, ast.AsyncFunctionDef)):
                call = parents[parents[node]] if isinstance(parents.get(node), ast.Attribute) else None
                top_reads.add(call.args[0].value if isinstance(call, ast.Call) and call.args and isinstance(call.args[0], ast.Constant) else "?")
            else:
                call = parents.get(node)
                inside_reads.append(isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "dict")
    assert top_reads == {"OPENHORA_STATE_DIR", "WB_TIER_A_SURVEY", "WB_TIER_A_REPORT", "WB_TIER_A_OUT", "WB_TIER_A_ONLY", "WB_HYPERFRAMES_DOCKER_TESTS"}, top_reads
    assert inside_reads and all(inside_reads), "inside a function the environment is only copied whole with dict(os.environ, ...)"
    source = path.read_text(encoding="utf-8")
    assert 'monkeypatch.setenv("OPENHORA_STATE_DIR", need(REAL_STATE_DIR, "OPENHORA_STATE_DIR"))' in source and "def images(real_state)" in source
