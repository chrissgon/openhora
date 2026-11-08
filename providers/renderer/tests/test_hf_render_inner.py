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


# ---------------------------------------------------------------- the blocks folder and the fonts (V3b-1)

def add_blocks(project: Path, names=("oh-caption.html", "oh-keyword.html"), text="<!doctype html><title>block</title>") -> None:
    (project / "blocks").mkdir()
    for name in names:
        (project / "blocks" / name).write_text(text, encoding="utf-8")


def test_a_project_with_block_pages_is_accepted_and_the_pages_are_read(tmp_path):
    project = make_project(tmp_path / "project")
    add_blocks(project)
    assert R.check_project(str(project)) == BASE_PAGE
    assert sorted(R.block_pages(str(project))) == ["blocks:oh-caption.html", "blocks:oh-keyword.html"]
    assert R.block_pages(str(make_project(tmp_path / "plain"))) == {}


@pytest.mark.parametrize("name", ["Caption.html", "oh_caption.html", "oh-caption.htm", "oh-caption.html.bak", "-.HTML", ".hidden.html", "a" * 81 + ".html"])
def test_a_block_page_with_a_name_outside_the_pattern_is_refused(tmp_path, name):
    project = make_project(tmp_path / "project")
    add_blocks(project, names=(name,))
    assert refusal(R.check_project, str(project))[0] == "project_unexpected_file"


def test_more_than_sixteen_block_pages_and_a_page_over_one_mebibyte_are_refused(tmp_path):
    project = make_project(tmp_path / "project")
    add_blocks(project, names=tuple("p%02d.html" % k for k in range(16)))
    R.check_project(str(project))
    (project / "blocks" / "p16.html").write_text("x")
    assert refusal(R.check_project, str(project))[0] == "project_unexpected_file"
    other = make_project(tmp_path / "other")
    add_blocks(other, names=("big.html",), text="a" * (R.BLOCK_PAGE_MAX_BYTES + 1))
    assert refusal(R.check_project, str(other)) == ("project_unexpected_file", "blocks/big.html")
    fits = make_project(tmp_path / "fits")
    add_blocks(fits, names=("big.html",), text="a" * R.BLOCK_PAGE_MAX_BYTES)
    R.check_project(str(fits))


def test_a_block_folder_with_a_folder_a_link_or_a_non_page_inside_is_refused(tmp_path):
    project = make_project(tmp_path / "project")
    add_blocks(project)
    (project / "blocks" / "sub").mkdir()
    assert refusal(R.check_project, str(project))[0] == "project_unexpected_file"
    other = make_project(tmp_path / "other")
    add_blocks(other)
    (tmp_path / "elsewhere.html").write_text("x")
    (other / "blocks" / "link.html").symlink_to(tmp_path / "elsewhere.html")
    assert refusal(R.check_project, str(other))[0] == "project_unexpected_file"
    third = make_project(tmp_path / "third")
    (tmp_path / "folder").mkdir()
    (third / "blocks").symlink_to(tmp_path / "folder")
    assert refusal(R.check_project, str(third))[0] == "project_unexpected_file"
    for name in ("fonts", "other"):
        fourth = make_project(tmp_path / ("fourth-" + name))
        (fourth / name).mkdir()
        assert refusal(R.check_project, str(fourth))[0] == "project_unexpected_file"


def make_fonts(folder: Path, bad=None) -> Path:
    folder.mkdir()
    for name in R.FONT_FILES:
        (folder / name).write_bytes(b"not the font" if name == bad else b"font " + name.encode())
    return folder


def with_fake_fonts(monkeypatch, tmp_path, bad=None):
    """The image's three font files, stood in for by small files whose sha256 the guard's table is made to hold."""
    folder = make_fonts(tmp_path / "opt-fonts", bad)
    table = {name: __import__("hashlib").sha256(b"font " + name.encode()).hexdigest() for name in R.FONT_FILES}
    monkeypatch.setattr(R, "FONTS_SOURCE", str(folder))
    monkeypatch.setattr(R, "FONT_FILES", table)
    return folder


def test_the_font_table_holds_the_hashes_of_the_images_font_files():
    sums = dict(line.split("  ")[::-1] for line in (FOLDER / "fonts" / "SHA256SUMS").read_text().splitlines() if line.endswith(".woff2"))
    assert R.FONT_FILES == sums and set(R.FONT_FILES) == {"inter-500.woff2", "inter-800.woff2", "jetbrains-mono-500.woff2"}
    for name, digest in R.FONT_FILES.items():
        assert __import__("hashlib").sha256((FOLDER / "fonts" / name).read_bytes()).hexdigest() == digest


def test_the_fonts_are_copied_into_the_project_once_each_is_checked_and_the_copy_is_the_source(tmp_path, monkeypatch):
    folder = with_fake_fonts(monkeypatch, tmp_path)
    project = make_project(tmp_path / "project")
    R.copy_fonts(str(project))
    assert sorted(os.listdir(project / "fonts")) == sorted(R.FONT_FILES)
    assert all((project / "fonts" / name).read_bytes() == (folder / name).read_bytes() for name in R.FONT_FILES)


@pytest.mark.parametrize("bad", ["inter-500.woff2", "inter-800.woff2", "jetbrains-mono-500.woff2"])
def test_a_font_file_whose_hash_differs_is_refused_by_name(tmp_path, monkeypatch, bad):
    with_fake_fonts(monkeypatch, tmp_path, bad=bad)
    project = make_project(tmp_path / "project")
    assert refusal(R.copy_fonts, str(project)) == ("font_hash", bad)


def test_a_missing_font_file_is_a_font_hash_refusal_too(tmp_path, monkeypatch):
    folder = with_fake_fonts(monkeypatch, tmp_path)
    (folder / "inter-800.woff2").unlink()
    assert refusal(R.copy_fonts, str(make_project(tmp_path / "project"))) == ("font_hash", "inter-800.woff2")


def test_a_render_with_block_pages_checks_each_page_copies_the_fonts_and_runs_once(tmp_path, monkeypatch):
    with_fake_fonts(monkeypatch, tmp_path)
    seen = []

    def fake_run(argv, project, env, log_path, timeout):
        seen.append(sorted(os.listdir(os.path.join(project, "fonts"))))
        Path(argv[argv.index("--output") + 1]).write_bytes(b"prores")

    project, out, tmp = fake_world(tmp_path, monkeypatch, fake_run)
    add_blocks(project)
    assert R.main(["--project", str(project), "--out", str(out), "--tmp", str(tmp), "--fps", "30", "--timeout", "120"]) == 0
    assert seen == [sorted(R.FONT_FILES)] and (project / "gsap.min.js").exists()


def test_a_block_page_that_names_a_font_outside_the_allow_list_is_refused_naming_the_page_and_nothing_runs(tmp_path, monkeypatch):
    with_fake_fonts(monkeypatch, tmp_path)
    project, out, tmp = fake_world(tmp_path, monkeypatch, lambda *a: pytest.fail("HyperFrames was started"))
    add_blocks(project, names=("oh-caption.html",), text="<style>.a { font-family: Papyrus; }</style>")
    assert R.main(["--project", str(project), "--out", str(out), "--tmp", str(tmp), "--fps", "30", "--timeout", "120"]) == 1
    assert json.loads((out / "result.json").read_text()) == {"ok": False, "code": "font_not_allowed", "field": "blocks:oh-caption.html"}
    assert not (project / "fonts").exists() and not (project / "gsap.min.js").exists()


def fonts_seen_by_a_render(tmp_path, monkeypatch, page):
    """Run a render of a project whose page is `page`; whether the project had a `fonts` folder when HyperFrames started."""
    seen = []

    def fake_run(argv, project, env, log_path, timeout):
        seen.append(os.path.isdir(os.path.join(project, "fonts")))
        Path(argv[argv.index("--output") + 1]).write_bytes(b"x")

    project, out, tmp = fake_world(tmp_path, monkeypatch, fake_run)
    (project / "index.html").write_text(page)
    assert R.main(["--project", str(project), "--out", str(out), "--tmp", str(tmp), "--fps", "30", "--timeout", "120"]) == 0
    return seen[0]


def test_a_page_that_names_the_fonts_folder_gets_the_fonts(tmp_path, monkeypatch):
    with_fake_fonts(monkeypatch, tmp_path)
    page = BASE_PAGE.replace("</style>", '@font-face{font-family:"Inter";src:url("fonts/inter-500.woff2");}</style>')
    assert fonts_seen_by_a_render(tmp_path, monkeypatch, page) is True


def test_the_base_page_names_no_font_and_gets_no_fonts_folder(tmp_path, monkeypatch):
    with_fake_fonts(monkeypatch, tmp_path)
    assert fonts_seen_by_a_render(tmp_path, monkeypatch, BASE_PAGE) is False


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


# ---------------------------------------------------------------- tier A: instances.json, the registry files, the wrapper

import hashlib

COMPONENT = """<template>
<style>#root { font-family: "Inter", sans-serif; }</style>
<div id="root" data-composition-id="aster-pop" data-duration="3" data-composition-variables='[{"id":"text","type":"string"}]'></div>
<script>
(function () {
  var tl = gsap.timeline({ paused: true });
  window.__timelines = window.__timelines || {};
  window.__timelines["aster-pop"] = tl;
})();
</script>
</template>
"""
PLACEHOLDER = ('<div id="hf-inst-0" class="hf-inst" data-hf-zone="card" data-hf-tier-a="0" style="position:absolute; left:0; top:110px; width:1080px; '
               'height:300px; contain:paint; overflow:clip; visibility:hidden"></div>')


def tier_a_project(tmp_path, component=COMPONENT, tamper=None, drop=False):
    """(project folder, registry root): a base project whose page holds one placeholder, one row of instances.json and the component's files."""
    project = make_project(tmp_path / "project", page=BASE_PAGE.replace('<div id="root"></div>', '<div id="root">%s</div>' % PLACEHOLDER))
    root = tmp_path / "registry"
    folder = root / "registry" / "components" / "aster-pop"
    folder.mkdir(parents=True)
    files = {"aster-pop.html": component.encode(), "registry-item.json": b"{}"}
    row = {"name": "hf:aster-pop", "files": {k: hashlib.sha256(v).hexdigest() for k, v in files.items()}, "implementation": "aster-pop.html", "start": 1.0, "end": 3.0,
           "band": [110, 300]}
    for name, raw in files.items():
        if not (drop and name == "aster-pop.html"):
            (folder / name).write_bytes(raw if tamper != name else raw + b"\n")
    (project / "instances.json").write_text(json.dumps({"0": row}))
    return project, root


def test_a_project_with_instances_json_is_accepted_and_one_with_an_oversize_or_linked_one_is_not(tmp_path):
    project, _ = tier_a_project(tmp_path)
    assert R.check_project(str(project)).startswith("<!doctype html>")
    (project / "instances.json").write_bytes(b"x" * (R.INSTANCES_MAX_BYTES + 1))
    assert refusal(R.check_project, str(project)) == ("project_unexpected_file", "instances.json")
    (project / "instances.json").unlink()
    (project / "instances.json").symlink_to(project / "vars.json")
    assert refusal(R.check_project, str(project)) == ("project_unexpected_file", "instances.json")


def test_a_tier_a_instance_is_read_from_the_registry_folder_checked_linted_wrapped_and_put_in_place_of_its_placeholder(tmp_path):
    project, root = tier_a_project(tmp_path)
    page = R.inline_tier_a(str(project), (project / "index.html").read_text(), str(root))
    assert PLACEHOLDER not in page and 'id="hf-inst-0-root"' in page and "@scope (#hf-inst-0)" in page and "__hfTierA" in page
    assert (project / "index.html").read_text() == page
    R.check_fonts(page)


def test_a_registry_file_that_is_missing_or_changed_is_refused_before_anything_is_wrapped(tmp_path):
    project, root = tier_a_project(tmp_path, drop=True)
    before = (project / "index.html").read_text()
    assert refusal(R.inline_tier_a, str(project), before, str(root)) == ("tier_a_file_missing", "hf:aster-pop")
    project, root = tier_a_project(tmp_path / "two", tamper="registry-item.json")
    assert refusal(R.inline_tier_a, str(project), (project / "index.html").read_text(), str(root)) == ("tier_a_hash", "hf:aster-pop")
    assert PLACEHOLDER in (project / "index.html").read_text()


def test_a_component_the_lint_refuses_is_a_block_lint_refusal_even_when_its_hash_matches(tmp_path):
    project, root = tier_a_project(tmp_path, component=COMPONENT.replace("var tl", 'fetch("/x"); var tl'))
    assert refusal(R.inline_tier_a, str(project), (project / "index.html").read_text(), str(root)) == ("block_lint", "hf:aster-pop")


def test_a_page_with_a_different_number_of_placeholders_than_rows_is_refused(tmp_path):
    project, root = tier_a_project(tmp_path)
    page = (project / "index.html").read_text()
    assert refusal(R.inline_tier_a, str(project), page.replace(PLACEHOLDER, ""), str(root)) == ("block_lint", "instances")
    assert R.inline_tier_a(str(project / "nowhere"), page, str(root)) == page


def test_a_malformed_instances_row_is_refused(tmp_path):
    project, _ = tier_a_project(tmp_path)
    rows = json.loads((project / "instances.json").read_text())
    for change in ({"name": "oh:x"}, {"files": {}}, {"implementation": "other.html"}, {"start": 3.0, "end": 1.0}, {"band": [1]}, {"extra": 1}):
        (project / "instances.json").write_text(json.dumps({"0": dict(rows["0"], **change)}))
        assert refusal(R.read_instances, str(project)) == ("project_unexpected_file", "instances.json"), change


def test_a_render_whose_log_shows_the_guards_marker_is_refused_block_escaped_even_when_hyperframes_succeeded(tmp_path, monkeypatch):
    with_fake_fonts(monkeypatch, tmp_path)
    project, root = tier_a_project(tmp_path / "t")
    monkeypatch.setattr(R, "inline_tier_a", lambda p, page, registry_root=str(root): ORIGINAL_INLINE(p, page, registry_root))

    def fake_run(argv, project, env, log_path, timeout):
        Path(log_path).write_bytes(b"page error: hf-escape\n")
        Path(argv[argv.index("--output") + 1]).write_bytes(b"prores")

    out, tmp = tmp_path / "out", tmp_path / "tmp"
    out.mkdir()
    tmp.mkdir()
    gsap = tmp_path / "gsap.min.js"
    gsap.write_text("/* gsap */")
    monkeypatch.setattr(R, "GSAP_SOURCE", str(gsap))
    monkeypatch.setattr(R, "run_render", fake_run)
    assert R.main(["--project", str(project), "--out", str(out), "--tmp", str(tmp), "--fps", "30", "--timeout", "120"]) == 1
    assert json.loads((out / "result.json").read_text()) == {"ok": False, "code": "block_escaped", "field": "render"}


def test_a_failed_render_with_the_marker_in_its_log_is_block_escaped_and_without_it_hf_failed(tmp_path, monkeypatch):
    with_fake_fonts(monkeypatch, tmp_path)
    gsap = tmp_path / "gsap.min.js"
    gsap.write_text("/* gsap */")
    monkeypatch.setattr(R, "GSAP_SOURCE", str(gsap))
    for marker, code in ((b"hf-escape", "block_escaped"), (b"some other error", "hf_failed")):
        project, root = tier_a_project(tmp_path / code)
        monkeypatch.setattr(R, "inline_tier_a", lambda p, page, registry_root=str(root): ORIGINAL_INLINE(p, page, registry_root))

        def fake_run(argv, project, env, log_path, timeout, marker=marker):
            Path(log_path).write_bytes(marker)
            R.refuse("hf_failed", "render")

        monkeypatch.setattr(R, "run_render", fake_run)
        out, tmp = tmp_path / ("o" + code), tmp_path / ("t" + code)
        out.mkdir()
        tmp.mkdir()
        assert R.main(["--project", str(project), "--out", str(out), "--tmp", str(tmp), "--fps", "30", "--timeout", "120"]) == 1
        assert json.loads((out / "result.json").read_text())["code"] == code


ORIGINAL_INLINE = R.inline_tier_a


def test_the_guards_marker_is_kept_in_the_log_even_when_it_arrives_past_the_logs_cap_or_is_cut_by_it(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "LOG_CAP", 4096)
    for body in ("sys.stdout.write('x' * 20000 + ' page error: hf-escape ' + 'y' * 100)", "sys.stdout.write('x' * (4096 - 4) + 'hf-escape' + 'y' * 100)",
                 "sys.stdout.write('quiet')"):
        project, log = tmp_path / ("p%d" % len(body)), tmp_path / ("log%d" % len(body))
        project.mkdir()
        R.run_render([sys.executable, "-c", "import sys; " + body], str(project), {"PATH": os.environ["PATH"]}, str(log), 60)
        assert R.log_shows_escape(str(log)) is ("hf-escape" in body), body
        assert log.stat().st_size <= 4096 + 64 + len("\nhf-escape\n")


# ---------------------------------------------------------------- the measure step (V3b-2): a harmless Python child stands in for node

MEASURE_OK = ("import json, os, sys\nopen(sys.argv[1], 'w').write(json.dumps({'fonts': [], 'fps': 30, 'frames': 1, 'per_frame': [[]], 'schema': 1}))\n"
              "print('measure saw', sorted(k for k in os.environ if k in ('HOME', 'TMPDIR', 'AWS_SECRET_ACCESS_KEY')))")


def fake_measure(monkeypatch, code=MEASURE_OK):
    seen = []
    monkeypatch.setattr(R, "measure_argv", lambda project, boxes: seen.append((project, boxes)) or [sys.executable, "-c", code, boxes])
    return seen


def measured_world(tmp_path, monkeypatch, order=None):
    tmp_path.mkdir(parents=True, exist_ok=True)

    def fake_run(argv, project, env, log_path, timeout):
        (order if order is not None else []).append("render")
        Path(log_path).write_text("render output\n")
        Path(argv[argv.index("--output") + 1]).write_bytes(b"prores bytes")

    return fake_world(tmp_path, monkeypatch, fake_run)


def run_main(project, out, tmp, *more, timeout="120"):
    return R.main(["--project", str(project), "--out", str(out), "--tmp", str(tmp), "--fps", "30", "--timeout", timeout, *more])


def test_the_measure_command_is_node_and_the_one_script_on_the_project_and_the_boxes_path():
    assert R.measure_argv("/work/project", "/work/out/boxes.json") == ["node", "/opt/hf-run/hf_measure.mjs", "/work/project", "/work/out/boxes.json"]
    assert R.MEASURE_SCRIPT == "/opt/hf-run/hf_measure.mjs" and R.render_argv("/work/out", 30)[1] == "render" and not set(R.NEVER_CALLED) & set(R.measure_argv("a", "b"))


def test_with_measure_the_boxes_are_made_after_the_render_and_their_hash_and_seconds_are_in_the_result(tmp_path, monkeypatch):
    order = []
    project, out, tmp = measured_world(tmp_path, monkeypatch, order)
    seen = fake_measure(monkeypatch)
    assert run_main(project, out, tmp, "--measure") == 0
    result = json.loads((out / "result.json").read_text())
    boxes = (out / "boxes.json").read_bytes()
    assert order == ["render"] and seen == [(str(project), str(out / "boxes.json"))]
    assert result["boxes_sha256"] == __import__("hashlib").sha256(boxes).hexdigest() and result["measure_seconds"] >= 0 and result["ok"] is True
    assert result["sha256"] == __import__("hashlib").sha256(b"prores bytes").hexdigest()
    assert (out / "intermediate.mov").is_file() and (out / "boxes.json").is_file() and (out / "result.json").is_file()


def test_the_measure_runs_with_the_renders_environment_and_its_output_goes_on_after_the_renders_log(tmp_path, monkeypatch):
    project, out, tmp = measured_world(tmp_path, monkeypatch)
    fake_measure(monkeypatch)
    assert run_main(project, out, tmp, "--measure") == 0
    log = (out / "hf.log").read_text()
    assert log.startswith("render output\n") and "measure saw" in log and "AWS_SECRET_ACCESS_KEY" not in log


def test_without_measure_no_boxes_are_made_and_the_measure_program_never_starts(tmp_path, monkeypatch):
    project, out, tmp = measured_world(tmp_path, monkeypatch)
    monkeypatch.setattr(R, "measure_argv", lambda *a: pytest.fail("the measure step ran for a render that draws nothing"))
    assert run_main(project, out, tmp) == 0
    result = json.loads((out / "result.json").read_text())
    assert "boxes_sha256" not in result and "measure_seconds" not in result and not (out / "boxes.json").exists()


@pytest.mark.parametrize("row, expect", [
    ({"ok": False, "code": "font_not_allowed", "field": "drawn"}, ("font_not_allowed", "drawn")),
    ({"ok": False, "code": "boxes_too_many", "field": "frame 12"}, ("boxes_too_many", "frame 12")),
    ({"ok": False, "code": "boxes_too_large", "field": "frame 3"}, ("boxes_too_large", "frame 3")),
    ({"ok": False, "code": "block_escaped", "field": "frame 7"}, ("block_escaped", "frame 7")),
    ({"ok": False, "code": "measure_failed", "field": "page error at frame 4"}, ("measure_failed", "page error at frame 4")),
    ({"ok": False, "code": "hf_failed", "field": "x"}, ("measure_failed", "measure")),                       # not a code the script may use
    ({"ok": False, "code": "font_not_allowed", "field": "a/../b"}, ("measure_failed", "measure")),           # a field outside the closed shape
    ({"ok": True, "code": "font_not_allowed", "field": "drawn"}, ("measure_failed", "measure")),
])
def test_a_refusal_row_of_the_script_becomes_the_renders_refusal_and_leaves_no_boxes(tmp_path, monkeypatch, row, expect):
    project, out, tmp = measured_world(tmp_path, monkeypatch)
    fake_measure(monkeypatch, "import json, sys\nopen(sys.argv[1], 'w').write(json.dumps(%r))\nsys.exit(1)" % row)
    assert run_main(project, out, tmp, "--measure") == 1
    assert json.loads((out / "result.json").read_text()) == {"ok": False, "code": expect[0], "field": expect[1]} and not (out / "boxes.json").exists()


def test_a_script_that_dies_without_a_row_or_leaves_a_row_that_is_not_json_is_measure_failed(tmp_path, monkeypatch):
    for code in ("import sys; sys.exit(7)", "import sys; open(sys.argv[1], 'w').write('not json'); sys.exit(1)"):
        project, out, tmp = measured_world(tmp_path / ("w%d" % len(code)), monkeypatch)
        fake_measure(monkeypatch, code)
        assert run_main(project, out, tmp, "--measure") == 1
        assert json.loads((out / "result.json").read_text()) == {"ok": False, "code": "measure_failed", "field": "measure"} and not (out / "boxes.json").exists()


def test_a_script_that_exits_well_without_boxes_or_with_too_many_bytes_is_measure_failed(tmp_path, monkeypatch):
    project, out, tmp = measured_world(tmp_path / "a", monkeypatch)
    fake_measure(monkeypatch, "pass")
    assert run_main(project, out, tmp, "--measure") == 1 and json.loads((out / "result.json").read_text())["code"] == "measure_failed"
    project, out, tmp = measured_world(tmp_path / "b", monkeypatch)
    fake_measure(monkeypatch)
    monkeypatch.setattr(R, "BOXES_MAX_BYTES", 5)
    assert run_main(project, out, tmp, "--measure") == 1 and json.loads((out / "result.json").read_text())["code"] == "measure_failed"


def test_a_measure_step_past_the_time_left_is_killed_as_a_group_and_refused_as_hf_timeout(tmp_path):
    started = __import__("time").monotonic()
    out = tmp_path / "out"
    out.mkdir()
    R_argv = R.measure_argv
    try:
        R.measure_argv = lambda project, boxes: [sys.executable, "-c", "import time; time.sleep(60)"]
        assert refusal(R.run_measure, str(tmp_path), str(out), {"PATH": os.environ["PATH"]}, str(tmp_path / "hf.log"), 1) == ("hf_timeout", "measure")
    finally:
        R.measure_argv = R_argv
    assert __import__("time").monotonic() - started < 30 and not (out / "boxes.json").exists()


def test_a_render_that_leaves_less_than_the_least_time_for_the_measure_does_not_start_it(tmp_path, monkeypatch):
    project, out, tmp = measured_world(tmp_path, monkeypatch)
    monkeypatch.setattr(R, "measure_argv", lambda *a: pytest.fail("the measure step started with no time left"))
    assert run_main(project, out, tmp, "--measure", timeout=str(R.MEASURE_MIN_SECONDS - 1)) == 1
    assert json.loads((out / "result.json").read_text()) == {"ok": False, "code": "hf_timeout", "field": "measure"}


def test_the_measure_flag_is_the_only_way_the_inner_entry_runs_the_step_and_help_lists_it(tmp_path):
    env = {"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", "/nonexistent")}
    done = subprocess.run([sys.executable, "-I", str(FOLDER / "hf_render.py"), "--help"], capture_output=True, text=True, env=env, timeout=60, cwd=str(tmp_path))
    assert done.returncode == 0 and "--measure" in done.stdout


def test_what_the_page_reported_travels_with_the_refusal_in_closed_shapes_only(tmp_path, monkeypatch):
    rows = [{"code": "page_error", "field": "TypeError Cannot read properties of undefined"}, {"code": "state", "field": "player undefined timelines main"},
            {"code": "Bad Code", "field": "x"}, {"code": "console_error", "field": "a/b"}, "no", {"code": "request_failed", "field": "blocks oh-caption.html"}]
    row = {"ok": False, "code": "measure_failed", "field": "player", "problems": rows}
    project, out, tmp = measured_world(tmp_path, monkeypatch)
    fake_measure(monkeypatch, "import json, sys\nopen(sys.argv[1], 'w').write(json.dumps(%r))\nsys.exit(1)" % row)
    assert run_main(project, out, tmp, "--measure") == 1
    assert json.loads((out / "result.json").read_text()) == {"ok": False, "code": "measure_failed", "field": "player", "problems": [
        {"code": "page_error", "field": "TypeError Cannot read properties of undefined"}, {"code": "state", "field": "player undefined timelines main"},
        {"code": "request_failed", "field": "blocks oh-caption.html"}]}


def test_the_time_the_page_took_to_be_ready_is_read_from_the_end_of_boxes_json_and_reaches_the_result(tmp_path, monkeypatch):
    project, out, tmp = measured_world(tmp_path, monkeypatch)
    body = "{'fonts': [], 'fps': 30, 'frames': 1, 'per_frame': [[]], 'ready_ms': 4321, 'schema': 1}"
    fake_measure(monkeypatch, "import json, sys\nopen(sys.argv[1], 'w').write(json.dumps(%s, separators=(',', ':'), sort_keys=True))" % body)
    assert run_main(project, out, tmp, "--measure") == 0
    assert json.loads((out / "result.json").read_text())["measure_ready_ms"] == 4321
    path = tmp_path / "b.json"
    for text, expect in (('{"per_frame":[[]],"ready_ms":12,"schema":1}\n', 12), ('{"schema":1}', None), ('x' * 500 + '"ready_ms":7,"schema":1}', 7), ('"ready_ms":7,"schema":2}', None)):
        path.write_text(text)
        assert R.boxes_ready_ms(str(path)) == expect
    assert R.boxes_ready_ms(str(tmp_path / "missing")) is None
