"""Tests of the host side of the document renderer (providers/exporter/container.py, package P8): the definition and its hash, the exact
`docker run` command with each limit, the frames the container prints and the rules that parse them, the private copy of the input
and its removal, and the verbs. No container is started: a stand-in takes the place of the run. Fictional input.

Run: uv run --with pytest==9.1.1 pytest providers/exporter/tests/test_exporter_host.py
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


render = load("exporter_host_under_test", HERE.parent / "container.py")
box = sys.modules["_container"]
IMAGE = "sha256:" + "a" * 64


def frames(*files, end=b"END\n"):
    return b"OHF1\n" + b"".join(f"FILE {name} {len(data)}\n".encode() + data for name, data in files) + end


INFO = json.dumps({"counts": {"rows": 2}, "tool_versions": {"openpyxl": "3.0.9"}}).encode()


def stand_in(output=b"a,b\n", fmt="csv", info=INFO, code=0, seen=None):
    def run(command, name, timeout, stdout_cap=None):
        if seen is not None:
            seen.update(command=command, name=name, timeout=timeout, cap=stdout_cap)
            mount = next(command[i + 1] for i, a in enumerate(command) if a == "-v" or a == "--volume") if "-v" in command or "--volume" in command else None
            seen["mount"] = mount
            if mount:
                path = mount.split(":")[0]
                seen["input_during_run"] = Path(path).read_bytes()
        return SimpleNamespace(returncode=code, stdout=frames((f"output.{fmt}", output), ("info.json", info)), stderr="the tail")
    return run


def test_the_definition_is_four_files_and_the_tag_is_the_start_of_their_hash():
    digest = render.definition_hash()
    assert len(digest) == 64 and render.image_tag() == f"openhora-render:{digest[:12]}"
    for name in render.DEFINITION_FILES:
        assert (Path(render.DEFINITION_DIR) / name).is_file(), name
    assert Path(render.DEFINITION_DIR) == HERE.parent


def test_the_hash_changes_with_any_file_of_the_definition(tmp_path):
    folder = tmp_path / "def"
    folder.mkdir()
    for name in render.DEFINITION_FILES:
        (folder / name).write_text(name, encoding="utf-8")
    before = render.definition_hash(str(folder))
    (folder / "_render.py").write_text("changed", encoding="utf-8")
    assert render.definition_hash(str(folder)) != before


def test_the_dockerfile_pins_its_base_by_digest_and_installs_wheels_by_hash_and_leaves_no_compiler_or_pip():
    text = (Path(render.DEFINITION_DIR) / "Dockerfile").read_text(encoding="utf-8")
    assert "FROM debian@sha256:" in text and "--require-hashes" in text and "--only-binary=:all:" in text and "--no-deps" in text
    assert "purge -y --auto-remove python3-pip" in text and "build-essential" not in text and "gcc" not in text.replace("compiler", "")
    lock = (Path(render.DEFINITION_DIR) / "requirements.lock").read_text(encoding="utf-8")
    for line in lock.splitlines():
        if line and not line.startswith((" ", "#")) and "==" in line:
            assert "\\" in line, f"every pin is followed by its hashes: {line}"
    assert lock.count("--hash=sha256:") >= 20 and "weasyprint==" in lock


def test_the_command_has_every_limit_of_the_shared_container_and_mounts_only_the_input_read_only():
    command = render.command_for("openhora-render-x", IMAGE, "/tmp/in/input", "pdf", 120)
    text = " ".join(command)
    for needle in ("--network none", "--read-only", "--cap-drop ALL", "no-new-privileges", "--memory", "--cpus", "--pids-limit",
                   "/tmp/in/input:/in/input:ro", IMAGE, "python3 -I /opt/render/_render.py --format pdf --input /in/input"):
        assert needle in text, needle
    assert text.count(" -v ") == 1 and "org.openhora.render" in text


def test_a_render_returns_the_bytes_the_container_printed_and_leaves_no_copy_of_the_input(tmp_path):
    seen = {}
    made = render.render("csv", b"x,y\n1,2\n", run=stand_in(b"\xef\xbb\xbfx,y\n", seen=seen), image=IMAGE)
    assert made["output"] == b"\xef\xbb\xbfx,y\n" and made["bytes"] == 7 and made["format"] == "csv" and made["image"] == IMAGE
    assert made["counts"] == {"rows": 2} and made["tool_versions"] == {"openpyxl": "3.0.9"}
    assert seen["input_during_run"] == b"x,y\n1,2\n", "the container saw the input, mounted from a private file"
    assert seen["timeout"] == render.DEFAULT_TIMEOUT and seen["cap"] == render.STDOUT_CAP
    assert not Path(seen["mount"].split(":")[0]).exists(), "the private copy is removed"


def test_the_private_copy_is_a_folder_of_this_user_with_mode_0700_and_a_file_with_mode_0600():
    folder, path = render._private_input(b"data")
    try:
        assert oct(os.stat(folder).st_mode & 0o777) == "0o700" and oct(os.stat(path).st_mode & 0o777) == "0o600"
        assert Path(path).read_bytes() == b"data"
    finally:
        import shutil
        shutil.rmtree(folder)


@pytest.mark.parametrize("fmt,data,code", [("odt", b"x", 2), ("csv", b"", 2), ("csv", b"   \n", 2), ("csv", b"x" * (1024 * 1024 + 1), 2)])
def test_a_bad_format_or_input_is_refused_before_anything_runs(fmt, data, code):
    with pytest.raises(render.ProviderError) as refused:
        render.render(fmt, data, run=lambda *a, **k: pytest.fail("a container was started"), image=IMAGE)
    assert refused.value.code == code


def test_a_timeout_out_of_range_is_refused():
    for bad in (0, render.MAX_TIMEOUT + 1):
        with pytest.raises(render.ProviderError):
            render.render("csv", b"a\n", timeout=bad, run=stand_in(), image=IMAGE)


def test_a_container_that_fails_is_a_failure_with_the_tail_of_its_reason_and_the_input_is_removed():
    with pytest.raises(render.ProviderError) as failed:
        render.render("csv", b"a\n", run=stand_in(code=3), image=IMAGE)
    assert "the render failed: the tail" in str(failed.value) and failed.value.code == render.EXIT_FAILED

    def broken(command, name, timeout, stdout_cap=None):
        raise box.ContainerError("time_limit", "x")
    with pytest.raises(render.ProviderError) as ended:
        render.render("csv", b"a\n", run=broken, image=IMAGE)
    assert "time_limit" in str(ended.value)


# --- the frames --------------------------------------------------------------------------------------------------------------------


def parse(data, fmt="csv"):
    return render.parse_frames(data, fmt)


def test_the_frames_are_parsed_by_fixed_rules():
    got = parse(frames(("output.csv", b"a,b\n"), ("info.json", b'{"counts": {"rows": 1}}')))
    assert got["output"] == b"a,b\n" and got["info"] == {"counts": {"rows": 1}}
    assert parse(frames(("output.xlsx", b"PK"), ("info.json", b"not json")), "xlsx")["info"] == {}
    assert parse(frames(("output.pdf", b"%PDF")), "pdf")["info"] == {}


@pytest.mark.parametrize("data", [
    b"nothing", b"OHF1\n", frames(("output.csv", b"a")) + b"more", frames(("output.csv", b"a"), end=b"END\nmore"),
    frames(("output.csv", b"a"), ("output.csv", b"b")), frames(("output.xlsx", b"a")), frames(("other.csv", b"a")),
    frames(("output.csv", b"")), frames(("info.json", b"{}")), b"OHF1\nFILE output.csv 99\nab" + b"END\n",
    frames(("output.csv", b"a" * (render.OUTPUT_CAP + 1))), frames(("output.csv", b"a"), ("info.json", b"x" * (render.INFO_CAP + 1))),
    b"OHF1\nFILE output.csv x\nEND\n", b"OHF1\nFILE ../output.csv 1\naEND\n",
])
def test_a_stream_that_is_not_a_render_is_refused_and_nothing_is_kept(data):
    with pytest.raises(render.ProviderError):
        parse(data)


def test_the_out_folder_must_be_a_real_empty_folder_of_this_user_with_mode_0700(tmp_path):
    good = tmp_path / "good"
    good.mkdir(mode=0o700)
    render.check_out_dir(str(good))
    loose = tmp_path / "loose"
    loose.mkdir(mode=0o755)
    full = tmp_path / "full"
    full.mkdir(mode=0o700)
    (full / "x").write_text("x")
    link = tmp_path / "link"
    link.symlink_to(good)
    for bad in (loose, full, link, tmp_path / "missing"):
        with pytest.raises(render.ProviderError) as refused:
            render.check_out_dir(str(bad))
        assert refused.value.code == render.EXIT_USAGE


def test_the_render_verb_writes_one_new_file_into_the_out_folder(tmp_path, monkeypatch, capsys):
    source = tmp_path / "in.csv"
    source.write_text("a,b\n1,2\n", encoding="utf-8")
    out = tmp_path / "out"
    out.mkdir(mode=0o700)
    monkeypatch.setattr(render, "render", lambda fmt, data, timeout=0, **k: {"renderer": "document", "format": fmt, "output": b"BYTES",
                                                                              "bytes": 5, "image": IMAGE, "counts": {}, "tool_versions": {}})
    code = render.main(["render", "--format", "csv", "--input", str(source), "--out-dir", str(out)])
    assert code == 0 and (out / "output.csv").read_bytes() == b"BYTES" and oct((out / "output.csv").stat().st_mode & 0o777) == "0o600"
    printed = json.loads(capsys.readouterr().out)
    assert printed["output"] == "output.csv" and "BYTES" not in json.dumps(printed)


def test_the_verbs_refuse_what_they_should(tmp_path, capsys):
    assert render.main([]) == render.EXIT_USAGE
    assert render.main(["--help"]) == 0
    assert render.main(["render", "--format", "csv"]) == render.EXIT_USAGE
    assert render.main(["render", "--format", "csv", "--input", "relative.csv", "--out-dir", str(tmp_path)]) == render.EXIT_USAGE
    assert render.main(["build"]) == render.EXIT_USAGE
    assert render.main(["build", "--dry-run", "--confirmed"]) == render.EXIT_USAGE
    assert render.main(["--check", "build"]) == render.EXIT_USAGE
    assert render.main(["frobnicate"]) == render.EXIT_USAGE
    assert render.main(["build", "--dry-run"]) == 0
    printed = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert printed["dry_run"] is True and printed["would"]["tag"] == render.image_tag()
