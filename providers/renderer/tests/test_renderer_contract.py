"""The renderer in the provider contract: a runtime-only class (decision D11), one implementation in its folder, helpers that are not
implementations, a header the resolver can read, the contract's rows, and nothing imported from outside providers/."""
from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

import pytest

import renderer_kit as K

REPO = K.REPO
spec = importlib.util.spec_from_file_location("workbench_provider_resolve_for_renderer", REPO / "providers" / "resolve.py")
resolve = importlib.util.module_from_spec(spec)
spec.loader.exec_module(resolve)


def test_renderer_video_is_a_runtime_only_class_with_one_implementation_and_underscore_helpers_are_not_implementations():
    assert resolve.folder("renderer:video") == "renderer"
    assert resolve.variables("renderer:video") == ["RENDERER_VIDEO_PROVIDER", "RENDERER_PROVIDER"]
    assert resolve.split_class("renderer:video") == ("renderer", "video")
    assert resolve.implementations("renderer:video") == ["ffmpeg"]
    got = resolve.resolve("renderer:video", env={})
    assert got["implementation"] == "ffmpeg" and got["source"] == "only-implementation" and got["path"].endswith("providers/renderer/ffmpeg.py")
    assert resolve.platform_of("renderer:video") is None                    # a fixed target, not a class with a parameter
    assert "renderer:video" not in resolve.LISTED                           # no skill may require it ...
    assert "renderer:video" not in (REPO / "contracts" / "environment.md").read_text()      # ... so it is not in the environment contract
    assert "renderer:video" not in [row["class"] for row in resolve.listing(env={})["classes"]]


def test_a_workbench_with_the_providers_helpers_still_has_one_candidate(tmp_path):
    folder = tmp_path / "providers" / "renderer"
    folder.mkdir(parents=True)
    for name in ("ffmpeg.py", "_inner.py", "_cdp.py", "_docker.py", "_fetch_browser.py", "_redact.py"):
        (folder / name).write_text("")
    (folder / "Dockerfile").write_text("")
    assert resolve.implementations("renderer:video", root=tmp_path, env={}) == ["ffmpeg"]
    assert resolve.resolve("renderer:video", root=tmp_path, env={})["implementation"] == "ffmpeg"
    (folder / "remotion.py").write_text("")                                 # a second implementation behind the same class needs a choice
    with pytest.raises(resolve.Unresolved) as e:
        resolve.resolve("renderer:video", root=tmp_path, env={})
    assert "RENDERER_VIDEO_PROVIDER" in str(e.value)
    assert resolve.resolve("renderer:video", root=tmp_path, env={"RENDERER_VIDEO_PROVIDER": "remotion"})["implementation"] == "remotion"
    assert resolve.resolve("renderer:video", root=tmp_path, env={"RENDERER_PROVIDER": "remotion"})["implementation"] == "remotion"


def test_the_header_says_no_dependencies_so_the_caller_starts_it_with_its_own_interpreter():
    assert resolve.interpreter_for(str(K.RENDERER / "ffmpeg.py")) == [sys.executable]
    header = (K.RENDERER / "ffmpeg.py").read_text().split("\n")[:5]
    assert header[1:5] == ["# /// script", '# requires-python = ">=3.9"', "# dependencies = []", "# ///"]


def test_the_contract_has_the_class_row_and_the_verbs_row():
    text = (REPO / "providers" / "CONTRACT.md").read_text()
    assert "| `renderer:video` (a class the runtime uses" in text and "`providers/renderer/`" in text and "RENDERER_VIDEO_PROVIDER" in text
    row = next(l for l in text.split("\n") if l.startswith("| `renderer:video` | Runtime only"))
    for verb in ("`--check`", "`build (--dry-run", "`pin-browser (--dry-run", "`reap`", "`analyse --in", "`base --transcript", "`align --post", "`check --edl", "`render --edl", "`cover --in"):
        assert verb in row, verb
    for key in ("`path`", "`sha256`", "`browser_sandbox`", "`replayed`", "`slots`", "`unmatched`"):
        assert key in row, key


def test_the_provider_imports_nothing_outside_its_own_folder_and_the_standard_library():
    own = {p.stem for p in K.RENDERER.glob("*.py")}
    allowed_std = set(sys.stdlib_module_names)
    for path in K.RENDERER.glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                names = [node.module.split(".")[0]]
            for name in names:
                assert name in own or name in allowed_std or name == "__future__", (path.name, name)


def test_the_credential_formats_are_the_shared_copy():
    import subprocess
    done = subprocess.run([sys.executable, str(REPO / "scripts" / "sync_copies.py"), "--check"], capture_output=True, text=True)
    assert done.returncode == 0, done.stdout + done.stderr
    assert (K.RENDERER / "_redact.py").read_bytes() == (REPO / "shared" / "scripts" / "redact.py").read_bytes()
