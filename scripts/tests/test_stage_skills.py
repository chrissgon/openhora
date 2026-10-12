"""Tests for scripts/stage_skills.py: what a staged copy of a skill holds, for the eval runner and the installers.

Run: uv run --with pytest pytest scripts/tests/test_stage_skills.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "stage_skills.py"
spec = importlib.util.spec_from_file_location("stage_skills", SCRIPT)
st = importlib.util.module_from_spec(spec)
spec.loader.exec_module(st)
REPO = Path(st.ROOT)


@pytest.fixture
def workbench(tmp_path):
    """A small workbench: two skills and a shared folder with references, platform references and scripts."""
    root = tmp_path / "wb"
    demo = root / "skills" / "core-demo"
    for folder in ("references", "assets", "scripts/tests", "scripts/__pycache__", "evals/files/app", ".pytest_cache"):
        (demo / folder).mkdir(parents=True)
    (demo / "SKILL.md").write_text("# demo\nWalk [the checklist](../../shared/references/security.md), every item.\n")
    (demo / "references" / "guide.md").write_text("Read shared/references/writing.md. Not shared/references/absent.md.\n")
    (demo / "assets" / "template.md").write_text("It names shared/references/unrelated.md in an asset, which is not a citation.\n")
    (demo / "scripts" / "check.py").write_text("print(1)\n")
    (demo / "scripts" / "tests" / "test_check.py").write_text("def test_x():\n    assert True\n")
    (demo / "scripts" / "__pycache__" / "check.cpython-311.pyc").write_bytes(b"\0")
    (demo / ".DS_Store").write_bytes(b"\0")
    (demo / "evals" / "evals.json").write_text('{"evals": [{"expected_output": "the answer"}]}\n')
    (demo / "evals" / "files" / "app" / "SKILL.md").write_text("a fixture that looks like a skill\n")
    other = root / "skills" / "core-other"
    other.mkdir()
    (other / "SKILL.md").write_text("# other\nSee ../../shared/references/other-only.md.\n")
    refs = root / "shared" / "references"
    (refs / "platforms").mkdir(parents=True)
    for name in ("security.md", "writing.md", "unrelated.md", "other-only.md", "README.md",
                 "platforms/chirp.md", "platforms/chirp.json", "platforms/plain.md"):
        (refs / name).write_text(name + "\n")
    (root / "shared" / "scripts").mkdir()
    (root / "shared" / "scripts" / "tool.py").write_text("print(1)\n")
    return root


def files(folder):
    return sorted(str(p.relative_to(folder)) for p in Path(folder).rglob("*") if p.is_file() or p.is_symlink())


def test_a_staged_skill_is_a_copy_without_its_cases_its_tests_and_caches(workbench, tmp_path):
    target = tmp_path / "project" / ".tool" / "skills"
    manifest = st.stage([str(workbench / "skills" / "core-demo")], str(target), root=str(workbench))
    assert manifest == {"skills_dir": str(target), "skills": ["core-demo"], "shared_dir": None, "references": []}
    assert files(target) == ["core-demo/SKILL.md", "core-demo/assets/template.md", "core-demo/references/guide.md",
                             "core-demo/scripts/check.py"]
    assert not (tmp_path / "project" / ".tool" / "shared").exists()
    (target / "core-demo" / "SKILL.md").write_text("edited\n")  # a copy: the source is untouched
    assert (workbench / "skills" / "core-demo" / "SKILL.md").read_text().startswith("# demo")
    assert (workbench / "skills" / "core-demo" / "evals" / "evals.json").is_file()


def test_a_link_inside_a_skill_is_copied_as_its_content_and_never_points_back(workbench, tmp_path):
    demo = workbench / "skills" / "core-demo"
    os.symlink(workbench / "shared" / "references" / "writing.md", demo / "references" / "linked.md")
    os.symlink(demo / "no-such-file", demo / "references" / "dangling.md")
    target = tmp_path / "skills-out" / "x"
    st.stage([str(demo)], str(target), root=str(workbench))
    linked = target / "core-demo" / "references" / "linked.md"
    assert linked.is_file() and not linked.is_symlink() and linked.read_text() == "writing.md\n"
    assert not (target / "core-demo" / "references" / "dangling.md").exists()
    assert not [p for p in target.rglob("*") if p.is_symlink()]


def test_staging_again_replaces_the_copy_that_was_there(workbench, tmp_path):
    target = tmp_path / "p" / ".tool" / "skills"
    st.stage([str(workbench / "skills" / "core-demo")], str(target), root=str(workbench))
    (target / "core-demo" / "left-over.md").write_text("from an earlier version\n")
    st.stage([str(workbench / "skills" / "core-demo")], str(target), root=str(workbench))
    assert not (target / "core-demo" / "left-over.md").exists()


def test_the_runner_gets_only_the_references_its_skill_cites(workbench, tmp_path):
    demo, other = workbench / "skills" / "core-demo", workbench / "skills" / "core-other"
    assert st.cited_references(str(demo), str(workbench)) == ["security.md", "writing.md"]  # SKILL.md and references/, not assets/
    target = tmp_path / "case" / ".tool" / "skills"
    manifest = st.stage([str(demo), str(other)], str(target), root=str(workbench), references="cited", cite_from=[str(demo)])
    assert manifest["references"] == ["security.md", "writing.md"] and manifest["skills"] == ["core-demo", "core-other"]
    shared = tmp_path / "case" / ".tool" / "shared"
    assert manifest["shared_dir"] == str(shared) and files(shared) == ["references/security.md", "references/writing.md"]
    # The link a skill uses resolves by the staged path, and what only the dependency cites is not there.
    assert (target / "core-demo" / ".." / ".." / "shared" / "references" / "security.md").is_file()
    assert not (shared / "references" / "other-only.md").exists() and not (shared / "scripts").exists()


def test_a_skill_that_cites_nothing_gets_no_shared_folder(workbench, tmp_path):
    other = workbench / "skills" / "core-other"
    (other / "SKILL.md").write_text("# other\n")
    target = tmp_path / "case" / ".tool" / "skills"
    manifest = st.stage([str(other)], str(target), root=str(workbench), references="cited", cite_from=[str(other)])
    assert manifest["shared_dir"] is None and not (tmp_path / "case" / ".tool" / "shared").exists()


def test_a_case_gets_the_references_of_the_platforms_it_names(workbench, tmp_path):
    target = tmp_path / "case" / ".tool" / "skills"
    manifest = st.stage([str(workbench / "skills" / "core-other")], str(target), root=str(workbench), platforms=["chirp", "plain"])
    assert manifest["references"] == ["platforms/chirp.json", "platforms/chirp.md", "platforms/plain.md"]
    assert files(tmp_path / "case" / ".tool" / "shared") == ["references/platforms/chirp.json", "references/platforms/chirp.md",
                                                           "references/platforms/plain.md"]
    for bad in (["unknown"], ["../security"], ["Chirp"], [3]):
        with pytest.raises(st.StageError):
            st.stage([str(workbench / "skills" / "core-other")], str(tmp_path / "x" / "y"), root=str(workbench), platforms=bad)
    assert not (tmp_path / "x").exists()  # nothing is staged when a source is wrong


def test_an_installer_gets_every_reference_and_its_marker_and_never_the_shared_scripts(workbench, tmp_path):
    target = tmp_path / "home" / ".tool" / "skills"
    manifest = st.stage([str(workbench / "skills" / "core-demo")], str(target), root=str(workbench), references="all",
                        marker=".installed-by-openhora")
    assert manifest["references"] == ["README.md", "other-only.md", "platforms/chirp.json", "platforms/chirp.md",
                                      "platforms/plain.md", "security.md", "unrelated.md", "writing.md"]
    shared = tmp_path / "home" / ".tool" / "shared"
    assert (target / "core-demo" / ".installed-by-openhora").read_text() == ""
    assert (shared / ".installed-by-openhora").is_file() and not (shared / "scripts").exists()
    assert not (target / "core-demo" / "evals").exists() and not (target / "core-demo" / "scripts" / "tests").exists()


def test_what_is_stripped_is_the_callers_choice(workbench, tmp_path):
    demo = workbench / "skills" / "core-demo"
    st.stage([str(demo)], str(tmp_path / "a" / "skills"), root=str(workbench), strip=())
    assert (tmp_path / "a" / "skills" / "core-demo" / "evals" / "evals.json").is_file()
    assert (tmp_path / "a" / "skills" / "core-demo" / "scripts" / "tests" / "test_check.py").is_file()
    assert not list((tmp_path / "a").rglob("__pycache__"))  # caches go whatever the choice
    st.stage([str(demo)], str(tmp_path / "b" / "skills"), root=str(workbench), strip=("assets",))
    assert not (tmp_path / "b" / "skills" / "core-demo" / "assets").exists()
    assert (tmp_path / "b" / "skills" / "core-demo" / "evals").is_dir()


def test_a_folder_that_is_not_a_skill_and_two_skills_of_one_name_are_refused(workbench, tmp_path):
    with pytest.raises(st.StageError):
        st.stage([str(workbench / "shared")], str(tmp_path / "t" / "skills"), root=str(workbench))
    twin = tmp_path / "elsewhere" / "core-demo"
    twin.mkdir(parents=True)
    (twin / "SKILL.md").write_text("# twin\n")
    with pytest.raises(st.StageError):
        st.stage([str(workbench / "skills" / "core-demo"), str(twin)], str(tmp_path / "t" / "skills"), root=str(workbench))
    assert not (tmp_path / "t").exists()


def run(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, timeout=60)


def test_the_command_line_stages_and_prints_the_manifest(workbench, tmp_path):
    demo = str(workbench / "skills" / "core-demo")
    target = tmp_path / "case" / ".tool" / "skills"
    r = run("--skills-dir", str(target), "--skill", demo, "--references", "cited", "--cite-from", demo, "--platform", "chirp",
            "--root", str(workbench))
    assert r.returncode == 0, r.stderr
    manifest = json.loads(r.stdout)
    assert manifest["skills"] == ["core-demo"]
    assert manifest["references"] == ["platforms/chirp.json", "platforms/chirp.md", "security.md", "writing.md"]
    assert (target / "core-demo" / "SKILL.md").is_file() and not (target / "core-demo" / "evals").exists()
    r = run("--skills-dir", str(tmp_path / "n" / "skills"), "--skill", demo, "--no-strip", "--root", str(workbench))
    assert r.returncode == 0 and (tmp_path / "n" / "skills" / "core-demo" / "evals").is_dir()


@pytest.mark.parametrize("args, code", [
    ([], 2), (["--skill", "x"], 2), (["--skills-dir", "t", "--skill"], 2), (["--skills-dir", "t", "--skill", "x", "--frobnicate"], 2),
    (["--skills-dir", "t", "--skill", "x", "--references", "some"], 2), (["--skills-dir", "t", "--skill", "x", "--marker", "a/b"], 2),
    (["--skills-dir", "t", "--skill", "no-such-folder"], 1)])
def test_usage_errors_exit_2_and_a_missing_source_exits_1(tmp_path, args, code):
    r = subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, timeout=60, cwd=tmp_path)
    assert r.returncode == code and "Traceback" not in r.stderr
    assert (r.stdout if not args else r.stderr).strip() and not (tmp_path / "t").exists()
    assert run("--help").returncode == 0 and "--skills-dir" in run("--help").stdout


def test_the_module_depends_on_nothing_of_the_eval_harness():
    """Its two callers are the runner and the installers: it imports the standard library and nothing else."""
    import ast
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    imported = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    imported |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert imported <= {"fnmatch", "json", "os", "re", "shutil", "sys"}
    source = SCRIPT.read_text(encoding="utf-8")
    assert "eval_run" not in source.replace("evals/eval_run.py", "") and "importlib" not in source


def test_in_the_repository_a_citation_is_found_and_names_a_file_that_exists():
    """The skills that walk the security checklist cite it (the plan's default 21): their runs are given that file."""
    citing = {p.name: st.cited_references(str(p)) for p in sorted((REPO / "skills").iterdir()) if (p / "SKILL.md").is_file()}
    assert "security.md" in citing["core-security-audit"] and "security.md" in citing["core-skill-creator"]
    for found in citing.values():
        assert all((REPO / "shared" / "references" / rel).is_file() for rel in found)
