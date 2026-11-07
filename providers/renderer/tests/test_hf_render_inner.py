"""The inner entry of the HyperFrames image, `hyperframes-image/hf_render.py` (V3a-2), loaded by path: no docker, no HyperFrames, no browser.
The font guard, the project folder's checks, the command it would run (with the process faked) and the environment of that process.
Every input is synthetic."""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
FOLDER = ROOT / "providers" / "renderer" / "hyperframes-image"
ALLOWLIST = ROOT / "providers" / "renderer" / "assets" / "fonts" / "allowlist.json"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


R = load("hf_render_under_test", FOLDER / "hf_render.py")
BASE_PAGE = """<!doctype html><html><head><style>html, body { margin: 0; background: #0b1020; }
.zw { position: absolute; inset: 0; }</style></head><body><div id="root"></div><script>var main = gsap.timeline({ paused: true });</script></body></html>"""


def make_project(folder: Path, page=BASE_PAGE, vars_text='{"duration":3.0,"fps":30,"zooms":[]}\n') -> Path:
    (folder / "media").mkdir(parents=True)
    (folder / "index.html").write_text(page, encoding="utf-8")
    (folder / "vars.json").write_text(vars_text, encoding="utf-8")
    (folder / "media" / "proxy.mp4").write_bytes(b"\0" * 64)
    return folder


def refusal(call, *args):
    with pytest.raises(R.Refuse) as caught:
        call(*args)
    return caught.value.code, caught.value.field


# ---------------------------------------------------------------- the font guard

def test_the_base_page_and_a_page_naming_inter_or_a_generic_family_pass_the_font_guard():
    R.check_fonts(BASE_PAGE)
    R.check_fonts("<style>.a { font-family: Inter, sans-serif; } .b { font-family: 'JetBrains Mono', monospace; }</style>")
    R.check_fonts("<style>.a { font-family: var(--font-body); }</style><script>ctx.font = '500 40px Inter';</script>")


@pytest.mark.parametrize("page", ["<style>.a { font-family: Comic Sans MS; }</style>", "<style>.a { font-family: 'Papyrus', serif; }</style>",
                                  "<script>ctx.font = \"16px Papyrus\";</script>", "<script>ctx.font = '12px Menlo, monospace';</script>"])
def test_a_page_that_names_a_font_outside_the_allow_list_is_refused(page):
    assert refusal(R.check_fonts, page) == ("font_not_allowed", "index.html")


def test_the_allowed_families_are_the_allow_lists_families_in_lower_case():
    rows = json.loads(ALLOWLIST.read_text(encoding="utf-8"))["fonts"]
    assert R.ALLOWED_FAMILIES == {row["family"].lower() for row in rows}


# ---------------------------------------------------------------- the project folder

def test_a_project_of_exactly_the_three_files_is_accepted_and_the_page_is_returned(tmp_path):
    project = make_project(tmp_path / "project")
    assert R.check_project(str(project)) == BASE_PAGE


@pytest.mark.parametrize("extra", ["notes.txt", "media/other.mp4", "gsap.min.js", "sub/index.html"])
def test_an_extra_file_is_refused(tmp_path, extra):
    project = make_project(tmp_path / "project")
    (project / extra).parent.mkdir(parents=True, exist_ok=True)
    (project / extra).write_bytes(b"x")
    assert refusal(R.check_project, str(project))[0] == "project_unexpected_file"


@pytest.mark.parametrize("missing", ["index.html", "vars.json", "media/proxy.mp4"])
def test_a_missing_file_is_refused_by_name(tmp_path, missing):
    project = make_project(tmp_path / "project")
    (project / missing).unlink()
    assert refusal(R.check_project, str(project)) == ("project_unexpected_file", missing)


def test_a_symlink_in_place_of_a_file_or_of_the_media_folder_is_refused(tmp_path):
    project = make_project(tmp_path / "project")
    (tmp_path / "elsewhere.json").write_text("{}")
    (project / "vars.json").unlink()
    (project / "vars.json").symlink_to(tmp_path / "elsewhere.json")
    assert refusal(R.check_project, str(project)) == ("project_unexpected_file", "vars.json")
    other = make_project(tmp_path / "other")
    (tmp_path / "folder").mkdir()
    (other / "media" / "proxy.mp4").unlink()
    (other / "media").rmdir()
    (other / "media").symlink_to(tmp_path / "folder")
    assert refusal(R.check_project, str(other))[0] == "project_unexpected_file"


def test_an_oversized_vars_json_is_refused(tmp_path):
    project = make_project(tmp_path / "project", vars_text="1" * (R.VARS_MAX_BYTES + 1))
    assert refusal(R.check_project, str(project)) == ("project_unexpected_file", "vars.json")


def test_an_oversized_page_is_refused(tmp_path):
    project = make_project(tmp_path / "project", page="<p>" + "a" * R.INDEX_MAX_BYTES)
    assert refusal(R.check_project, str(project)) == ("project_unexpected_file", "index.html")


# ---------------------------------------------------------------- the command and its environment

def test_the_command_is_exactly_hyperframes_render_with_the_fixed_flags_and_none_of_the_commands_that_reach_a_network():
    argv = R.render_argv("/work/out", 30)
    assert argv == ["hyperframes", "render", "--output", "/work/out/intermediate.mov", "--format", "mov", "--prores-profile", "hq",
                    "--variables-file", "vars.json", "--workers", "4", "--frames-cache-dir", "off", "--fps", "30", "--quiet"]
    assert not set(R.NEVER_CALLED) & set(argv) and argv[1] == "render"
    assert set(R.NEVER_CALLED) == {"cloud", "billing", "publish", "lambda", "tts", "transcribe", "skills", "upgrade", "update"}


def test_the_environment_has_exactly_the_named_keys_and_nothing_of_the_callers():
    caller = {"PATH": "/opt/hf/node_modules/.bin:/usr/bin", "PRODUCER_HEADLESS_SHELL_PATH": "/opt/chrome/chrome-headless-shell",
              "PUPPETEER_EXECUTABLE_PATH": "/opt/chrome/chrome-headless-shell", "AWS_SECRET_ACCESS_KEY": "no", "HYPERFRAMES_API_KEY": "no", "HOME": "/tmp"}
    env = R.render_env("/work/tmp", caller)
    assert env == {"PATH": caller["PATH"], "PRODUCER_HEADLESS_SHELL_PATH": caller["PRODUCER_HEADLESS_SHELL_PATH"],
                   "PUPPETEER_EXECUTABLE_PATH": caller["PUPPETEER_EXECUTABLE_PATH"], "HOME": "/work/tmp", "TMPDIR": "/work/tmp",
                   "HYPERFRAMES_NO_TELEMETRY": "1", "DO_NOT_TRACK": "1"}


def fake_world(tmp_path, monkeypatch, run_render):
    gsap = tmp_path / "gsap.min.js"
    gsap.write_text("/* gsap */")
    package = tmp_path / "package.json"
    package.write_text(json.dumps({"name": "hyperframes", "version": "0.9.19"}))
    monkeypatch.setattr(R, "GSAP_SOURCE", str(gsap))
    monkeypatch.setattr(R, "HF_PACKAGE", str(package))
    monkeypatch.setattr(R, "MEMORY_PEAK", str(tmp_path / "no-memory-peak"))
    monkeypatch.setattr(R, "run_render", run_render)
    project, out, tmp = (tmp_path / name for name in ("project", "out", "tmp"))
    make_project(project)
    out.mkdir()
    tmp.mkdir()
    return project, out, tmp


def test_a_render_copies_gsap_in_runs_the_command_once_in_the_project_and_writes_the_result(tmp_path, monkeypatch):
    seen = []

    def fake_run(argv, project, env, log_path, timeout):
        seen.append((argv, project, env, timeout))
        Path(argv[argv.index("--output") + 1]).write_bytes(b"prores bytes")

    project, out, tmp = fake_world(tmp_path, monkeypatch, fake_run)
    assert R.main(["--project", str(project), "--out", str(out), "--tmp", str(tmp), "--fps", "30", "--timeout", "120"]) == 0
    assert len(seen) == 1 and seen[0][0] == R.render_argv(str(out), 30) and seen[0][1] == str(project) and seen[0][3] == 120
    assert (project / "gsap.min.js").read_text() == "/* gsap */"
    result = json.loads((out / "result.json").read_text())
    assert result["ok"] is True and result["bytes"] == len(b"prores bytes") and result["hyperframes"] == "0.9.19" and result["memory_peak_bytes"] is None
    assert result["sha256"] == __import__("hashlib").sha256(b"prores bytes").hexdigest()


def test_a_refusal_is_written_as_a_closed_row_and_exits_1_and_no_process_starts(tmp_path, monkeypatch):
    project, out, tmp = fake_world(tmp_path, monkeypatch, lambda *a: pytest.fail("HyperFrames was started"))
    (project / "index.html").write_text("<style>.a { font-family: Papyrus; }</style>")
    assert R.main(["--project", str(project), "--out", str(out), "--tmp", str(tmp), "--fps", "30", "--timeout", "120"]) == 1
    assert json.loads((out / "result.json").read_text()) == {"ok": False, "code": "font_not_allowed", "field": "index.html"}
    assert not (project / "gsap.min.js").exists()


def test_a_render_that_leaves_no_file_is_refused(tmp_path, monkeypatch):
    project, out, tmp = fake_world(tmp_path, monkeypatch, lambda *a: None)
    assert R.main(["--project", str(project), "--out", str(out), "--tmp", str(tmp), "--fps", "30", "--timeout", "120"]) == 1
    assert json.loads((out / "result.json").read_text())["code"] == "hf_no_output"


# ---------------------------------------------------------------- the process: log cap, exit code, timeout (a harmless Python child stands in)

def test_the_log_keeps_the_first_megabyte_and_a_non_zero_exit_is_hf_failed(tmp_path):
    log = tmp_path / "hf.log"
    code = "import sys; sys.stdout.write('x' * (3 * 1024 * 1024)); sys.exit(3)"
    assert refusal(R.run_render, [sys.executable, "-c", code], str(tmp_path), {"PATH": os.environ["PATH"]}, str(log), 60) == ("hf_failed", "render")
    assert log.stat().st_size == R.LOG_CAP


def test_a_render_past_its_time_is_killed_as_a_group_and_refused_as_hf_timeout(tmp_path):
    started = __import__("time").monotonic()
    code = "import time; time.sleep(60)"
    assert refusal(R.run_render, [sys.executable, "-c", code], str(tmp_path), {"PATH": os.environ["PATH"]}, str(tmp_path / "hf.log"), 1) == ("hf_timeout", "render")
    assert __import__("time").monotonic() - started < 30


def test_a_good_exit_returns_and_the_child_sees_only_the_given_environment(tmp_path):
    log = tmp_path / "hf.log"
    code = "import os, sys; sys.stdout.write(','.join(sorted(os.environ)))"
    R.run_render([sys.executable, "-c", code], str(tmp_path), {"ONLY": "1"}, str(log), 60)
    assert "ONLY" in log.read_text() and "PATH" not in log.read_text().split(",")
