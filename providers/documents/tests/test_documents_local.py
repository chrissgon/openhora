"""Tests of what is particular to providers/documents/local.py (the contract is test_documents_contract.py): where a
document and its comments live, the version, and the refusals. Offline.

Run: uv run --with pytest==9.1.1 pytest providers/documents/tests/test_documents_local.py
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "local.py"


def run(tmp_path, *argv, config=None):
    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps(config if config is not None else {"provider": "local", "dir": str(tmp_path / "docs-dir")}),
                   encoding="utf-8")
    done = subprocess.run([sys.executable, str(SCRIPT), *argv, "--config-file", str(cfg)], capture_output=True,
                          text=True, timeout=60)
    return done.returncode, (json.loads(done.stdout) if done.stdout.strip() else None), done.stderr


def write(tmp_path, text, path="docs/brand/strategy.md", key="k1"):
    source = tmp_path / "in.md"
    source.write_text(text, encoding="utf-8")
    return run(tmp_path, "write", "--path", path, "--markdown-file", str(source), "--idempotency-key", key, "--confirmed")


def test_the_id_is_the_project_path_and_the_file_lies_under_dir(tmp_path):
    (tmp_path / "docs-dir").mkdir()
    code, out, err = write(tmp_path, "# Strategy\n")
    assert code == 0 and out["id"] == "docs/brand/strategy.md", err
    stored = tmp_path / "docs-dir" / "docs" / "brand" / "strategy.md"
    assert stored.read_text(encoding="utf-8") == "# Strategy\n"
    assert out["version"] == hashlib.sha256(b"# Strategy\n").hexdigest()


def test_the_version_covers_the_document_only_and_a_write_leaves_the_side_file(tmp_path):
    # The version covers the content (WP-3.15): the side file of comments does not move it.
    (tmp_path / "docs-dir").mkdir()
    write(tmp_path, "# Strategy\n")
    side = tmp_path / "docs-dir" / "docs" / "brand" / "strategy.md.comments.md"
    side.write_text("- A comment.\nnot a comment\n", encoding="utf-8")
    code, out, _ = run(tmp_path, "stat", "--id", "docs/brand/strategy.md")
    assert out["version"] == hashlib.sha256(b"# Strategy\n").hexdigest()
    code, out, _ = run(tmp_path, "comments", "--id", "docs/brand/strategy.md")
    assert code == 0 and [c["text"] for c in out["comments"]] == ["A comment."]
    write(tmp_path, "# Strategy, again\n")
    assert side.read_text(encoding="utf-8") == "- A comment.\nnot a comment\n"
    code, out, _ = run(tmp_path, "read", "--id", "docs/brand/strategy.md")
    assert [c["text"] for c in out["comments"]] == ["A comment."]


def test_a_relative_or_missing_dir_and_a_side_file_id_are_refused(tmp_path):
    assert run(tmp_path, "--check", config={"provider": "local", "dir": "relative"})[0] == 2
    assert run(tmp_path, "--check")[0] == 3  # the folder does not exist
    (tmp_path / "docs-dir").mkdir()
    assert run(tmp_path, "stat", "--id", "docs/brand/strategy.md.comments.md")[0] == 2
    assert run(tmp_path, "stat", "--id", "docs/brand/strategy.md")[0] == 1
    assert run(tmp_path, "nonsense")[0] == 2
