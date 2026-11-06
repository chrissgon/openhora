"""Tests for skills/eng-tradeoffs/scripts/run_options.py: what it runs, what it refuses, what it measures.

Run: uv run --with pytest pytest skills/eng-tradeoffs/scripts/tests/test_run_options.py

Offline; every folder, script and number is invented for the test.
"""
from __future__ import annotations

import gzip
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "skills/eng-tradeoffs/scripts/run_options.py"

PROTOTYPE = "import os, sys\nprint(os.environ.get('TZ'), sys.argv[1:])\n"


def run(*args: str, cwd: Path, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, cwd=cwd,
                          env=env, timeout=60)


def scratch(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    (project / ".scratch" / "label-options").mkdir(parents=True)
    (project / "src").mkdir()
    return project


def test_help_exits_zero(tmp_path):
    r = run("--help", cwd=tmp_path)
    assert r.returncode == 0 and "runtimes NAME" in r.stdout


def test_run_covers_every_runtime_and_zone_in_order(tmp_path):
    project = scratch(tmp_path)
    proto = project / ".scratch" / "label-options" / "cases.py"
    proto.write_text(PROTOTYPE)
    r = run("run", "--runtime", sys.executable, "--tz", "UTC", "--tz", "Asia/Tokyo",
            ".scratch/label-options/cases.py", "a", "b", cwd=project)
    assert r.returncode == 0, r.stderr
    records = json.loads(r.stdout)
    assert [rec["tz"] for rec in records] == ["UTC", "Asia/Tokyo"]
    assert all(rec["exit_code"] == 0 for rec in records)
    assert records[0]["stdout"].strip() == "UTC ['a', 'b']"
    assert records[1]["stdout"].strip() == "Asia/Tokyo ['a', 'b']"
    assert records[0]["command"][0] == sys.executable


def test_run_reports_a_failing_prototype_without_failing_itself(tmp_path):
    project = scratch(tmp_path)
    proto = project / ".scratch" / "label-options" / "broken.py"
    proto.write_text("import sys\nprint('bad', file=sys.stderr)\nsys.exit(3)\n")
    r = run("run", "--runtime", sys.executable, str(proto), cwd=project)
    assert r.returncode == 0
    (record,) = json.loads(r.stdout)
    assert record["exit_code"] == 3 and record["stderr"].strip() == "bad" and record["tz"] is None


def test_run_refuses_a_script_in_the_source_tree(tmp_path):
    project = scratch(tmp_path)
    (project / "src" / "proto.py").write_text(PROTOTYPE)
    env = dict(os.environ, TMPDIR=str(tmp_path / "elsewhere"))
    (tmp_path / "elsewhere").mkdir()
    r = run("run", "--runtime", sys.executable, "src/proto.py", cwd=project, env=env)
    assert r.returncode == 2 and "outside the scratch folders" in r.stderr and r.stdout == ""


def test_run_hints_at_the_project_root_when_the_current_folder_is_in_the_temporary_folder(tmp_path):
    temp = tmp_path / "tmpdir"
    folder = temp / "work"
    folder.mkdir(parents=True)
    (folder / "runner.py").write_text(PROTOTYPE)
    env = dict(os.environ, TMPDIR=str(temp))
    r = run("run", "--runtime", sys.executable, str(folder / "runner.py"), cwd=folder, env=env)
    assert r.returncode == 2 and "run this command from the project root" in r.stderr


def test_run_refuses_a_link_that_leaves_the_scratch_folder(tmp_path):
    project = scratch(tmp_path)
    (project / "src" / "proto.py").write_text(PROTOTYPE)
    (project / ".scratch" / "label-options" / "link.py").symlink_to(project / "src" / "proto.py")
    env = dict(os.environ, TMPDIR=str(tmp_path / "elsewhere"))
    (tmp_path / "elsewhere").mkdir()
    r = run("run", "--runtime", sys.executable, ".scratch/label-options/link.py", cwd=project, env=env)
    assert r.returncode == 2 and "outside the scratch folders" in r.stderr


def test_run_refuses_an_unknown_runtime_a_bad_zone_and_a_missing_script(tmp_path):
    project = scratch(tmp_path)
    proto = project / ".scratch" / "label-options" / "cases.py"
    proto.write_text(PROTOTYPE)
    r = run("run", "--runtime", "no-such-runtime-zz", str(proto), cwd=project)
    assert r.returncode == 2 and "is not an executable" in r.stderr
    r = run("run", "--runtime", sys.executable, "--tz", "UTC; echo x", str(proto), cwd=project)
    assert r.returncode == 2 and "is not a time zone name" in r.stderr
    r = run("run", "--runtime", sys.executable, ".scratch/label-options/absent.py", cwd=project)
    assert r.returncode == 2 and "is not a file" in r.stderr
    r = run("run", str(proto), cwd=project)
    assert r.returncode == 2 and "--runtime" in r.stderr


def test_run_from_an_option_folder_and_never_from_outside_scratch(tmp_path):
    project = scratch(tmp_path)
    option = project / ".scratch" / "label-options" / "option-a"
    option.mkdir()
    proto = project / ".scratch" / "label-options" / "where.py"
    proto.write_text("import os\nprint(os.path.basename(os.getcwd()))\n")
    r = run("run", "--runtime", sys.executable, "--cwd", ".scratch/label-options/option-a",
            ".scratch/label-options/where.py", cwd=project)
    (record,) = json.loads(r.stdout)
    assert record["stdout"].strip() == "option-a" and record["cwd"] == str(option.resolve())
    env = dict(os.environ, TMPDIR=str(tmp_path / "elsewhere"))
    (tmp_path / "elsewhere").mkdir()
    r = run("run", "--runtime", sys.executable, "--cwd", "src", str(proto), cwd=project, env=env)
    assert r.returncode == 2 and "--cwd src is outside the scratch folders" in r.stderr


def test_run_writes_records_to_a_scratch_file_only(tmp_path):
    project = scratch(tmp_path)
    proto = project / ".scratch" / "label-options" / "cases.py"
    proto.write_text(PROTOTYPE)
    r = run("run", "--runtime", sys.executable, "--tz", "UTC", "--out", ".scratch/label-options/matrix.json",
            str(proto), cwd=project)
    assert r.returncode == 0, r.stderr
    summary = json.loads(r.stdout)
    assert summary["records"] == [{"runtime": sys.executable, "tz": "UTC", "exit_code": 0}]
    written = json.loads((project / ".scratch" / "label-options" / "matrix.json").read_text())
    assert written[0]["stdout"].strip() == "UTC []"
    env = dict(os.environ, TMPDIR=str(tmp_path / "elsewhere"))
    (tmp_path / "elsewhere").mkdir()
    r = run("run", "--runtime", sys.executable, "--out", "src/matrix.json", str(proto), cwd=project, env=env)
    assert r.returncode == 2 and "--out" in r.stderr and not (project / "src" / "matrix.json").exists()


def test_run_stops_a_prototype_that_hangs(tmp_path):
    project = scratch(tmp_path)
    proto = project / ".scratch" / "label-options" / "hang.py"
    proto.write_text("import time\ntime.sleep(30)\n")
    r = run("run", "--runtime", sys.executable, "--timeout", "1", str(proto), cwd=project)
    (record,) = json.loads(r.stdout)
    assert record["exit_code"] is None and "timed out" in record["stderr"]


def test_size_adds_the_files_of_a_folder(tmp_path):
    project = scratch(tmp_path)
    a, b = b"export const a = 1;\n" * 20, b"export const b = 2;\n"
    (project / "src" / "a.js").write_bytes(a)
    (project / "src" / "b.js").write_bytes(b)
    (project / "src" / "nested").mkdir()
    r = run("size", "src", cwd=project)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    expected = len(gzip.compress(a, 9, mtime=0)) + len(gzip.compress(b, 9, mtime=0))
    assert out["gzip_bytes"] == expected and out["raw_bytes"] == len(a) + len(b)
    assert [Path(f["path"]).name for f in out["files"]] == ["a.js", "b.js"]
    r = run("size", "absent.js", cwd=project)
    assert r.returncode == 2 and "not a file or a folder" in r.stderr


def test_runtimes_finds_path_and_version_manager_installs(tmp_path):
    home = tmp_path / "home"
    on_path = tmp_path / "bin"
    managed = home / ".nvm" / "versions" / "node" / "v20.1.0" / "bin"
    for folder, version in ((on_path, "v22.0.0"), (managed, "v20.1.0")):
        folder.mkdir(parents=True)
        exe = folder / "fakert"
        exe.write_text(f"#!/bin/sh\necho {version}\n")
        exe.chmod(0o755)
    (managed / "notexec").write_text("x")
    env = {"HOME": str(home), "PATH": str(on_path)}
    r = run("runtimes", "fakert", cwd=tmp_path, env=env)
    assert r.returncode == 0, r.stderr
    found = json.loads(r.stdout)
    assert [f["version"] for f in found] == ["v22.0.0", "v20.1.0"]
    assert found[1]["path"] == str(managed / "fakert")
    assert json.loads(run("runtimes", "notexec", cwd=tmp_path, env=env).stdout) == []
    r = run("runtimes", "../bin/sh", cwd=tmp_path, env=env)
    assert r.returncode == 2 and "not an executable name" in r.stderr
