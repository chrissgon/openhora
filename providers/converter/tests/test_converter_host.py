"""Tests of the host side of the document converter (providers/converter/container.py, class converter:document): the frames a
container prints, the definition of its image, the exact command of a conversion with every limit, the checks on its input and on
the folder it writes to, and the verbs. Offline: no container is started and no image is built; the container's run is a
stand-in that returns what a container would print. A conversion in a real container is test_converter_docker.py (opt in).

Run: uv run --with pytest==9.1.1 pytest providers/converter/tests/test_converter_host.py
"""
from __future__ import annotations

import ast
import importlib.util
import json
import os
import stat
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / "providers"))


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


container = load("converter_container_under_test", REPO / "providers" / "converter" / "container.py")
box = sys.modules["_container"]


def frames(*files, end=True, start=True) -> bytes:
    out = b"OHF1\n" if start else b""
    for name, data in files:
        out += f"FILE {name} {len(data)}\n".encode() + data
    return out + (b"END\n" if end else b"")


GOOD = frames(("converted.md", b"# Title\n\ntext\n"), ("info.json", b'{"converter": "document", "kind": "pdf"}'))


# --- the frames ----------------------------------------------------------------------------------------------------------------


def test_the_frames_are_parsed_with_fixed_rules_and_anything_else_is_refused():
    assert container.parse_frames(GOOD) == {"converted.md": b"# Title\n\ntext\n", "info.json": b'{"converter": "document", "kind": "pdf"}'}
    assert container.parse_frames(frames(("converted.csv", b"a,b\n1,2\n"))) == {"converted.csv": b"a,b\n1,2\n"}
    bad = {
        "no start marker": frames(("converted.md", b"x"), start=False),
        "no end marker": frames(("converted.md", b"x"), end=False),
        "after the end": GOOD + b"more",
        "an unknown name": frames(("converted.md", b"x"), ("script.sh", b"echo")),
        "a path as a name": frames(("../converted.md", b"x")),
        "a name twice": frames(("converted.md", b"x"), ("converted.md", b"y")),
        "two converted texts": frames(("converted.md", b"x"), ("converted.csv", b"y")),
        "no converted text": frames(("info.json", b"{}")),
        "nothing at all": frames(),
        "a size past the data": b"OHF1\nFILE converted.md 99\nshort\nEND\n",
        "a size that is not a number": b"OHF1\nFILE converted.md ten\nxEND\n",
        "a negative size": b"OHF1\nFILE converted.md -1\nEND\n",
        "a text over its cap": frames(("converted.md", b"x" * (container.CONVERTED_CAP + 1))),
        "an info over its cap": frames(("converted.md", b"x"), ("info.json", b"x" * (container.INFO_CAP + 1))),
        "text that is not frames": b"hello\n",
        "a cut frame": GOOD[:30],
    }
    for why, data in bad.items():
        with pytest.raises(container.ProviderError):
            container.parse_frames(data)
        assert why
    assert len(container.parse_frames(frames(("converted.md", b"x" * container.CONVERTED_CAP)))["converted.md"]) == container.CONVERTED_CAP


def test_the_outputs_are_written_as_new_regular_files_with_mode_0600_and_never_over_a_link(tmp_path):
    out = tmp_path / "out"
    out.mkdir(mode=0o700)
    assert container.write_outputs(str(out), {"converted.md": b"text", "info.json": b"{}"}) == ["converted.md", "info.json"]
    for name in ("converted.md", "info.json"):
        info = (out / name).lstat()
        assert stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o600
    other = tmp_path / "other"
    other.mkdir(mode=0o700)
    (tmp_path / "target").write_text("do not touch")
    os.symlink(tmp_path / "target", other / "converted.md")
    with pytest.raises(OSError):
        container.write_outputs(str(other), {"converted.md": b"overwritten"})
    assert (tmp_path / "target").read_text() == "do not touch"
    with pytest.raises(OSError):
        container.write_outputs(str(out), {"converted.md": b"again"})   # a name taken is never replaced


# --- the definition and the command ---------------------------------------------------------------------------------------------


def test_the_image_is_named_by_the_hash_of_its_definition_and_a_change_to_a_file_of_it_changes_the_name(tmp_path):
    assert set(container.DEFINITION_FILES) == {"Dockerfile", ".dockerignore", "_inner.py", "requirements.lock"}
    first = container.image_tag()
    assert first.startswith("openhora-converter:") and len(first.split(":")[1]) == 12 and container.image_tag() == first
    copy = tmp_path / "definition"
    copy.mkdir()
    for name in container.DEFINITION_FILES:
        (copy / name).write_bytes((HERE.parent / name).read_bytes())
    assert container.definition_hash(str(copy)) == container.definition_hash()
    (copy / "_inner.py").write_text((copy / "_inner.py").read_text() + "\n# changed\n")
    assert container.definition_hash(str(copy)) != container.definition_hash()


def test_the_dockerfile_pins_its_base_by_digest_and_its_packages_by_a_dated_snapshot_and_runs_unprivileged():
    text = (HERE.parent / "Dockerfile").read_text()
    import re
    assert re.search(r"^FROM debian@sha256:[0-9a-f]{64}$", text, re.M), "the base is pinned by digest"
    assert re.search(r"^ARG DEBIAN_SNAPSHOT=\d{8}T\d{6}Z$", text, re.M) and "snapshot.debian.org/archive/debian/${DEBIAN_SNAPSHOT}" in text
    for tool in ("poppler-utils", "pandoc", "python3-venv"):
        assert tool in text
    assert "USER 65534:65534" in text and "COPY _inner.py /opt/converter/_inner.py" in text
    assert (HERE.parent / ".dockerignore").read_text().split() == ["*", "!_inner.py", "!requirements.lock"]
    install = next(line for line in text.splitlines() if "pip install" in line)
    assert "--require-hashes" in install and "--only-binary=:all:" in install and "--no-deps" in install and "requirements.lock" in install
    assert "pip uninstall -y pip setuptools" in text, "the installer is removed from the environment after the install"


def lock_entries():
    """The packages of providers/converter/requirements.lock: [{name, version, hashes}]."""
    import re
    entries, current = [], None
    for line in (HERE.parent / "requirements.lock").read_text().splitlines():
        head = re.match(r"^([A-Za-z0-9_.\-]+)==(\S+)", line)
        if head:
            current = {"name": head.group(1).lower(), "version": head.group(2), "hashes": []}
            entries.append(current)
        elif line.strip().startswith("--hash=sha256:"):
            current["hashes"].append(re.fullmatch(r"\s*--hash=sha256:([0-9a-f]{64})( \\)?", line).group(1))
    return entries


def test_the_lock_names_every_package_by_an_exact_version_and_checks_every_file_by_sha256():
    entries = lock_entries()
    names = {e["name"] for e in entries}
    assert {"python-pptx", "openpyxl", "lxml"} <= names
    assert all(e["hashes"] for e in entries), "a package without a hash would not install under --require-hashes"
    text = (HERE.parent / "requirements.lock").read_text()
    for forbidden in ("git+", "http://", "https://", "--index-url", "--find-links", "-e "):
        assert forbidden not in text, forbidden
    package_lines = [ln for ln in text.splitlines() if ln and not ln.startswith((" ", "#"))]
    assert len(package_lines) == len(entries) and all("==" in ln for ln in package_lines), "every package line is pinned with =="


def test_the_lock_holds_only_the_two_libraries_and_what_they_need_and_nothing_that_reaches_out_or_calls_a_model():
    """MarkItDown was measured and not adopted (docs/decisions.md): neither it nor what only it needs (magika, onnxruntime, numpy, requests,
    an HTML or PDF parser, a model or cloud client) is in the image."""
    names = {e["name"] for e in lock_entries()}
    for out in ("markitdown", "magika", "onnxruntime", "numpy", "requests", "urllib3", "beautifulsoup4", "markdownify", "pandas",
                "pdfminer-six", "pdfplumber", "mammoth", "youtube-transcript-api", "azure-identity", "speechrecognition", "pydub",
                "openai", "anthropic"):
        assert out not in names, out
    assert names == {"python-pptx", "openpyxl", "lxml", "pillow", "xlsxwriter", "typing-extensions", "et-xmlfile"}
    lines = [ln for ln in (HERE.parent / "requirements.in").read_text().splitlines() if ln and not ln.startswith("#")]
    assert lines == ["python-pptx==1.0.2", "openpyxl==3.1.5"]


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_the_command_of_a_conversion_carries_every_limit_of_the_shared_helper(monkeypatch, platform):
    monkeypatch.setattr(sys, "platform", platform)
    command = container.command_for("openhora-converter-abc", "sha256:" + "a" * 64, "/work/in/input", "pdf", 120)
    joined = " ".join(command)
    for flag in ("--network none", "--read-only", "--cap-drop ALL", "--security-opt no-new-privileges", "--pull never",
                 "--pids-limit 128", f"--memory {container.MEMORY_MB}m", f"--memory-swap {container.MEMORY_MB}m", f"--cpus {container.CPUS}"):
        assert flag in joined, flag
    assert f"/scratch:rw,noexec,nosuid,nodev,size={container.SCRATCH_MB}m,mode=1777" in joined
    assert "-v /work/in/input:/in/input:ro" in joined and joined.count("-v ") == 1, "the input is the only mount, and read-only"
    assert command[-8:] == ["sha256:" + "a" * 64, "/opt/venv/bin/python", "-I", "/opt/converter/_inner.py", "--type", "pdf", "--input", "/in/input"]
    assert "--env" not in joined and "-e " not in joined and "--privileged" not in joined and "--network host" not in joined
    assert ("--user" in command) == (platform == "linux")


# --- one conversion ---------------------------------------------------------------------------------------------------------------


class Run:
    """A stand-in for the container's run: records the command and the cap, returns what a container would have printed."""

    def __init__(self, stdout=GOOD, code=0, stderr="", fail=None):
        self.stdout, self.code, self.stderr, self.fail, self.calls = stdout, code, stderr, fail, []

    def __call__(self, command, name, timeout, stdout_cap=None):
        self.calls.append({"command": command, "name": name, "timeout": timeout, "stdout_cap": stdout_cap})
        if self.fail:
            raise self.fail
        return box.Finished(self.code, self.stderr, False, self.stdout)


def make_input(tmp_path, data=b"%PDF-1.4 fake"):
    path = tmp_path / "input"
    path.write_bytes(data)
    return str(path)


def make_out(tmp_path, name="out"):
    folder = tmp_path / name
    folder.mkdir(mode=0o700)
    return str(folder)


def test_a_conversion_writes_the_outputs_the_container_printed_and_reports_what_it_found(tmp_path):
    run = Run()
    out = make_out(tmp_path)
    done = container.convert(make_input(tmp_path), "pdf", out, run=run, image="sha256:" + "b" * 64)
    assert done["converter"] == "document" and done["kind"] == "pdf" and done["outputs"] == ["converted.md", "info.json"]
    assert sorted(os.listdir(out)) == ["converted.md", "info.json"] and (Path(out) / "converted.md").read_bytes() == b"# Title\n\ntext\n"
    [call] = run.calls
    assert call["stdout_cap"] == container.STDOUT_CAP and call["timeout"] == container.DEFAULT_TIMEOUT and call["name"].startswith("openhora-converter-")
    assert call["command"][call["command"].index("--name") + 1] == call["name"]
    assert container.STDOUT_CAP > container.CONVERTED_CAP + container.INFO_CAP


def test_the_inputs_that_are_not_a_regular_file_of_a_fair_size_and_an_out_folder_that_is_not_private_and_empty_are_refused(tmp_path):
    ok = dict(run=Run(), image="sha256:" + "b" * 64)
    path, out = make_input(tmp_path), make_out(tmp_path)
    for kwargs, why in (({"input_path": "relative"}, "absolute"), ({"input_path": str(tmp_path / "missing")}, "does not exist"),
                        ({"input_path": str(tmp_path)}, "regular file"), ({"kind": "exe"}, "--type"), ({"timeout": 0}, "--timeout"),
                        ({"timeout": 99999}, "--timeout")):
        args = {"input_path": path, "kind": "pdf", "out_dir": out, "timeout": 60, **kwargs}
        with pytest.raises(container.ProviderError) as refused:
            container.convert(args["input_path"], args["kind"], args["out_dir"], args["timeout"], **ok)
        assert why in str(refused.value) and refused.value.code == container.EXIT_USAGE, why
    os.symlink(path, tmp_path / "link")
    with pytest.raises(container.ProviderError):
        container.convert(str(tmp_path / "link"), "pdf", out, **ok)
    big = tmp_path / "big"
    with open(big, "wb") as f:
        f.truncate(container.INPUT_CAP + 1)
    with pytest.raises(container.ProviderError) as refused:
        container.convert(str(big), "pdf", out, **ok)
    assert "over the" in str(refused.value)
    (Path(out) / "left").write_text("x")
    with pytest.raises(container.ProviderError) as refused:
        container.convert(path, "pdf", out, **ok)
    assert "empty" in str(refused.value)
    loose = make_out(tmp_path, "loose")
    os.chmod(loose, 0o755)
    with pytest.raises(container.ProviderError):
        container.convert(path, "pdf", loose, **ok)
    with pytest.raises(container.ProviderError):
        container.convert(path, "pdf", str(tmp_path / "nowhere"), **ok)
    assert ok["run"].calls == [], "no container was started for any of them"


def test_a_container_that_fails_or_prints_the_wrong_thing_leaves_nothing_in_the_out_folder(tmp_path):
    path = make_input(tmp_path)
    image = "sha256:" + "b" * 64
    for run, why in ((Run(code=3, stderr="error: pdftotext failed: Syntax Error"), "pdftotext failed"),
                     (Run(stdout=b"garbage"), "not a conversion"),
                     (Run(stdout=frames(("converted.md", b"x"), ("evil", b"x"))), "not taken"),
                     (Run(fail=box.ContainerError("time_limit", "container")), "time_limit"),
                     (Run(fail=box.ContainerError("output_too_large", "container")), "output_too_large")):
        out = make_out(tmp_path, "out-" + "".join(c if c.isalnum() else "-" for c in why))
        with pytest.raises(container.ProviderError) as refused:
            container.convert(path, "pdf", out, run=run, image=image)
        # the program's own exit 3 is the file being refused (exit 4: a caller that holds the file for a person tells it from a machine that failed)
        assert why in str(refused.value) and refused.value.code == (container.EXIT_REFUSED if run.code == 3 else container.EXIT_FAILED)
        assert os.listdir(out) == []


# --- the verbs --------------------------------------------------------------------------------------------------------------------


def test_the_verbs_check_their_arguments_and_the_build_can_be_seen_before_it_is_made(tmp_path, capsys):
    assert container.main([]) == container.EXIT_USAGE and container.main(["--help"]) == container.EXIT_OK
    assert container.main(["build"]) == container.EXIT_USAGE and container.main(["build", "--dry-run", "--confirmed"]) == container.EXIT_USAGE
    capsys.readouterr()
    assert container.main(["build", "--dry-run"]) == container.EXIT_OK
    shown = json.loads(capsys.readouterr().out)
    assert shown["dry_run"] is True and shown["would"]["tag"] == container.image_tag()
    assert shown["would"]["command"][:2] == ["docker", "build"] and f"DEFINITION_HASH={container.definition_hash()}" in shown["would"]["command"]
    for argv in (["convert"], ["convert", "--input", "/x"], ["convert", "--input", "/x", "--type", "pdf"], ["frobnicate"], ["convert", "--bogus", "1"],
                 ["--check", "convert"], ["convert", "--input"]):
        assert container.main(argv) == container.EXIT_USAGE, argv
    assert container.main(["convert", "--input", "/x", "--type", "pdf", "--out-dir", "/y", "--timeout", "soon"]) == container.EXIT_USAGE


def test_without_docker_the_provider_says_it_is_not_configured(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.delenv("DOCKER_HOST", raising=False)
    assert container.main(["--check"]) == container.EXIT_NOT_CONFIGURED
    path, out = make_input(tmp_path), make_out(tmp_path)
    assert container.main(["convert", "--input", path, "--type", "pdf", "--out-dir", out]) == container.EXIT_NOT_CONFIGURED


def test_the_provider_imports_only_the_standard_library_and_the_shared_helper_and_runs_on_python_39():
    tree = ast.parse((HERE.parent / "container.py").read_text(encoding="utf-8"))
    names = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    names |= {(n.module or "").split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert names <= {"__future__", "hashlib", "json", "os", "re", "stat", "subprocess", "sys", "time", "uuid", "_container"}, names
    head = (HERE.parent / "container.py").read_text(encoding="utf-8")[:300]
    assert 'requires-python = ">=3.9"' in head and "dependencies = []" in head


def test_the_class_resolves_to_this_provider_and_no_skill_may_require_it():
    resolve = load("resolve_for_converter_test", REPO / "providers" / "resolve.py")
    assert resolve.folder("converter:document") == "converter" and resolve.variables("converter:document") == [
        "CONVERTER_DOCUMENT_PROVIDER", "CONVERTER_PROVIDER"]
    assert resolve.resolve("converter:document", root=REPO, env={})["path"] == str(REPO / "providers" / "converter" / "container.py")
    assert resolve.implementations("converter:document", root=REPO, env={}) == ["container"], "_inner.py is the container's program, not an implementation"
    assert "converter:document" not in resolve.LISTED
    assert "converter" in resolve.ROLES
