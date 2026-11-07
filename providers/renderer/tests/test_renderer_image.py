"""The ffmpeg engine's image is built from the files image-manifest.json lists, and only those (review finding F11): the manifest, the
.dockerignore and the modules the container runs agree, and an edit to a host-only file never changes the image tag.

Run: uv run --with pytest pytest providers/renderer/tests/test_renderer_image.py
"""
from __future__ import annotations

import ast
import json
import shutil

import renderer_kit as K
import _docker as D
import _image as I

FOLDER = K.RENDERER


def manifest():
    return json.loads((FOLDER / "image-manifest.json").read_text(encoding="utf-8"))


def dockerignore_lines():
    return [line for line in (FOLDER / ".dockerignore").read_text(encoding="utf-8").splitlines() if line.strip()]


def test_the_dockerignore_lets_in_exactly_the_manifests_files_and_the_top_folder_of_each_manifest_folder():
    lines = dockerignore_lines()
    assert lines[0] == "*"
    allowed = [line[1:] for line in lines[1:]]
    assert all(line.startswith("!") for line in lines[1:])
    wanted = list(manifest()["files"]) + sorted({sub.split("/")[0] for sub in manifest()["folders"]})
    assert sorted(allowed) == sorted(wanted)
    assert len(set(allowed)) == len(allowed)
    for name in manifest()["files"]:
        assert (FOLDER / name).is_file(), name
    for sub in manifest()["folders"]:
        assert (FOLDER / sub).is_dir(), sub


def imports_of(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module.split(".")[0])
    return found


def test_every_module_the_inner_entry_point_imports_directly_or_not_is_in_the_manifest():
    own = {p.stem: p.name for p in FOLDER.glob("_*.py")}
    seen, todo = set(), ["_inner"]
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        todo += [m for m in imports_of(FOLDER / (name + ".py")) if m in own and m not in seen]
    needed = {own[name] for name in seen}
    assert needed <= set(manifest()["files"]), needed - set(manifest()["files"])


def test_no_host_only_file_is_in_the_manifest_and_the_tag_does_not_change_when_ffmpeg_py_does(tmp_path):
    files = set(manifest()["files"])
    for name in D.HOST_ONLY + ("_image.py", "ffmpeg.py"):
        assert name not in files, name
    copy = tmp_path / "renderer"
    shutil.copytree(FOLDER, copy, ignore=shutil.ignore_patterns("tests", "__pycache__", "hyperframes-image"))
    before = I.definition_hash(str(copy))
    assert before == I.definition_hash()
    for name in ("ffmpeg.py", "_docker.py", "_browser.py", "_image.py"):
        (copy / name).write_text((copy / name).read_text(encoding="utf-8") + "\n# a host-only edit\n", encoding="utf-8")
        assert I.definition_hash(str(copy)) == before, name
    (copy / "_inner.py").write_text((copy / "_inner.py").read_text(encoding="utf-8") + "\n# an edit of a file the container runs\n", encoding="utf-8")
    assert I.definition_hash(str(copy)) != before
    assert I.image_tag(str(copy)).startswith("openhora-renderer:")
