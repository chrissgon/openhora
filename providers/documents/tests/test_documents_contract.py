"""The contract of integration:documents (providers/CONTRACT.md, "Verbs per class"), tested on every implementation
the resolver lists: a new implementation is tested by adding its harness to documents_harness.py and nothing else.
Offline: no network, no real credential.

Run: uv run --with pytest==9.1.1 pytest providers/documents/tests
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(HERE))
import documents_harness  # noqa: E402

spec = importlib.util.spec_from_file_location("provider_resolve_for_documents", REPO / "providers" / "resolve.py")
resolve = importlib.util.module_from_spec(spec)
spec.loader.exec_module(resolve)
IMPLEMENTATIONS = resolve.implementations("integration:documents", root=REPO)
TEXT = "# Brand strategy\n\n- Owner: brand-strategy\n- Status: draft\n\n## Goal\n\nPeople using the tool.\n"


class Documents:
    """One implementation, one fresh place: run(verb...) runs the script and returns (exit code, JSON or None,
    stderr)."""

    def __init__(self, name: str, tmp_path: Path):
        self.harness = documents_harness.HARNESSES[name]()
        self.script = REPO / "providers" / "documents" / f"{name}.py"
        self.config = tmp_path / "documents.json"
        self.config.write_text(json.dumps(self.harness.config(tmp_path)), encoding="utf-8")
        self.tmp = tmp_path
        self.count = 0

    def run(self, *argv, config=None):
        env = {**os.environ, **self.harness.env()}
        args = [sys.executable, str(self.script), *argv, "--config-file", str(config or self.config)]
        done = subprocess.run(args, capture_output=True, text=True, timeout=60, env=env)
        try:
            out = json.loads(done.stdout) if done.stdout.strip() else None
        except ValueError:
            out = None
        return done.returncode, out, done.stderr

    def write(self, markdown: str, path="docs/brand/strategy.md", ident=None, key=None, mode="--confirmed",
              notice=None):
        self.count += 1
        source = self.tmp / f"doc-{self.count}.md"
        source.write_text(markdown, encoding="utf-8")
        argv = ["write", "--path", path, "--markdown-file", str(source), "--idempotency-key",
                key or f"key-{self.count}", mode] + (["--id", ident] if ident else []) + (
                    ["--notice", notice] if notice is not None else [])
        return self.run(*argv)

    def read(self, ident: str) -> dict:
        code, out, err = self.run("read", "--id", ident)
        assert code == 0, err
        return out


@pytest.fixture(params=IMPLEMENTATIONS)
def documents(request, tmp_path):
    assert request.param in documents_harness.HARNESSES, f"{request.param} has no harness in documents_harness.py"
    return Documents(request.param, tmp_path)


def test_every_implementation_has_a_harness():
    assert IMPLEMENTATIONS and set(IMPLEMENTATIONS) <= set(documents_harness.HARNESSES)


def test_a_document_that_was_written_is_read_back_as_the_harness_expects(documents):
    code, out, err = documents.write(TEXT)
    assert code == 0 and out["created"] is True and out["url"], err
    got = documents.read(out["id"])
    assert got["markdown"] == documents.harness.expected(TEXT) and got["version"] == out["version"]
    assert got["comments"] == []


def test_a_write_replaces_the_whole_document(documents):
    ident = documents.write(TEXT)[1]["id"]
    documents.harness.person_edits(ident, TEXT + "\nA paragraph a person added.\n")
    code, out, err = documents.write("# Brand strategy\n\nShorter.\n", ident=ident)
    assert code == 0 and out["created"] is False and out["id"] == ident, err
    got = documents.read(ident)["markdown"]
    assert got == documents.harness.expected("# Brand strategy\n\nShorter.\n") and "a person added" not in got


def test_the_version_is_the_same_until_a_person_edits(documents):
    # The version covers the content (WP-3.15): a comment may or may not move it, so nothing here asserts either.
    ident = documents.write(TEXT)[1]["id"]
    seen = [documents.read(ident)["version"]]
    assert documents.read(ident)["version"] == seen[-1]  # reading changes nothing
    documents.harness.person_edits(ident, TEXT + "\nEdited.\n")
    seen.append(documents.read(ident)["version"])
    assert len(set(seen)) == 2


def test_comments_lists_a_documents_open_comments_whatever_its_version(documents):
    ident = documents.write(TEXT)[1]["id"]
    code, out, err = documents.run("comments", "--id", ident)
    assert code == 0 and out == {"id": ident, "comments": []}, err
    documents.harness.person_comments(ident, "Say who it is for.")
    documents.harness.person_comments(ident, "Drop the last claim.")
    code, out, err = documents.run("comments", "--id", ident)
    assert code == 0 and [c["text"] for c in out["comments"]] == ["Say who it is for.", "Drop the last claim."], err
    assert all(c["id"] and set(c) >= {"id", "author", "created_at", "text"} for c in out["comments"])
    assert [c["id"] for c in out["comments"]] == [c["id"] for c in documents.read(ident)["comments"]]
    assert documents.run("comments", "--id", "docs/brand/none.md")[0] == 1


def test_stat_reports_the_version_read_reports(documents):
    ident = documents.write(TEXT)[1]["id"]
    documents.harness.person_comments(ident, "Shorter, please.")
    code, out, err = documents.run("stat", "--id", ident)
    assert code == 0 and out["version"] == documents.read(ident)["version"] and out["archived"] is False, err
    code, _, _ = documents.run("stat", "--id", "docs/brand/none.md")
    assert code == 1


def test_open_comments_are_read_with_the_document(documents):
    ident = documents.write(TEXT)[1]["id"]
    documents.harness.person_comments(ident, "Say who it is for.")
    documents.harness.person_comments(ident, "Drop the last claim.")
    comments = documents.read(ident)["comments"]
    assert [c["text"] for c in comments] == ["Say who it is for.", "Drop the last claim."]
    assert all(c["id"] and set(c) >= {"id", "author", "created_at", "text"} for c in comments)


def test_a_write_without_confirmation_is_refused_and_a_dry_run_changes_nothing(documents):
    ident = documents.write(TEXT)[1]["id"]
    before = documents.read(ident)
    code, _, _ = documents.write("# Other\n", ident=ident, mode="--neither")
    assert code == 2
    source = documents.tmp / "other.md"
    source.write_text("# Other\n", encoding="utf-8")
    code, _, _ = documents.run("write", "--id", ident, "--path", ident, "--markdown-file", str(source),
                               "--idempotency-key", "k-none")
    assert code == 2
    code, out, _ = documents.write("# Other\n", ident=ident, mode="--dry-run")
    assert code == 0 and out["dry_run"] is True and out["would"]
    code, out, _ = documents.write("# New\n", path="docs/brand/voice.md", mode="--dry-run")
    assert code == 0 and out["would"]["create"] is True
    assert documents.read(ident) == before and documents.run("stat", "--id", "docs/brand/voice.md")[0] == 1
    for bad in ("/etc/x.md", "docs/../x.md", "docs/brand/strategy.txt"):
        assert documents.write("# x\n", path=bad)[0] == 2


def test_the_same_idempotency_key_creates_one_document(documents):
    first = documents.write(TEXT, key="plan-1-strategy")[1]
    second = documents.write(TEXT + "\nAgain.\n", key="plan-1-strategy")[1]
    assert first["created"] is True and second["created"] is False and second["id"] == first["id"]
    code, out, err = documents.run("resolve", "--idempotency-key", "plan-1-strategy", "--not-created", "--confirmed")
    assert code == 0 and out["resolved"] is True, err
    code, out, err = documents.run("resolve", "--idempotency-key", "plan-1-strategy", "--id", first["id"], "--dry-run")
    assert code == 0 and out["dry_run"] is True, err


def test_check_says_not_configured_with_exit_3_and_prints_no_secret(documents, tmp_path):
    code, out, err = documents.run("--check")
    assert code == 0 and out == {"ok": True}, err
    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({"provider": "local"}), encoding="utf-8")
    code, out, err = documents.run("--check", config=empty)
    assert code == 3 and out is None and err
    for value in documents.harness.env().values():
        assert value not in err
    code, _, _ = documents.run("--check", config=tmp_path / "missing.json")
    assert code == 3


NOTICE = "Read-only here: edits are not imported, and the page is not overwritten while it differs."


def test_a_notice_is_the_pages_first_block_once_and_never_part_of_what_is_read(documents):
    code, out, err = documents.write(TEXT, notice=NOTICE)
    assert code == 0 and out["created"] is True, err
    ident = out["id"]
    got = documents.read(ident)
    assert got["markdown"] == documents.harness.expected(TEXT) and got["notice"] == NOTICE
    assert documents.harness.notices(ident) == [NOTICE] and documents.harness.first_is_notice(ident)
    shorter = "# Brand strategy\n\nShorter.\n"
    for _ in range(2):  # a write keeps the notice it finds: still one, still first
        assert documents.write(shorter, ident=ident, notice=NOTICE)[0] == 0
        got = documents.read(ident)
        assert got["markdown"] == documents.harness.expected(shorter) and got["notice"] == NOTICE
        assert documents.harness.notices(ident) == [NOTICE] and documents.harness.first_is_notice(ident)
    assert documents.write(shorter, ident=ident)[0] == 0  # a write without --notice leaves none
    assert documents.read(ident)["notice"] is None and documents.harness.notices(ident) == []
    plain = documents.write(TEXT, path="docs/brand/voice.md")[1]["id"]
    assert documents.read(plain)["notice"] is None and documents.harness.notices(plain) == []
    for bad in ("", "two\nlines"):
        assert documents.write(TEXT, ident=ident, notice=bad)[0] == 2


def test_notice_adds_the_notice_to_a_page_that_has_none_and_nothing_to_one_that_has_it(documents):
    ident = documents.write(TEXT)[1]["id"]
    before = documents.read(ident)
    code, out, err = documents.run("notice", "--id", ident, "--text", NOTICE, "--dry-run")
    assert code == 0 and out["dry_run"] is True and documents.read(ident) == before, err
    assert documents.run("notice", "--id", ident, "--text", NOTICE)[0] == 2  # neither --dry-run nor --confirmed
    code, out, err = documents.run("notice", "--id", ident, "--text", NOTICE, "--confirmed")
    assert code == 0 and out == {"id": ident, "added": True}, err
    got = documents.read(ident)
    assert got["markdown"] == before["markdown"] and got["notice"] == NOTICE
    assert documents.harness.notices(ident) == [NOTICE] and documents.harness.first_is_notice(ident)
    code, out, err = documents.run("notice", "--id", ident, "--text", NOTICE, "--confirmed")
    assert code == 0 and out == {"id": ident, "added": False} and documents.harness.notices(ident) == [NOTICE], err
    assert documents.run("notice", "--id", "docs/brand/none.md", "--text", NOTICE, "--confirmed")[0] == 1


def test_the_class_resolves_by_its_folder_and_is_not_in_the_listed_classes():
    assert resolve.resolve("integration:documents", root=REPO, implementation="local")["path"].endswith(
        os.path.join("providers", "documents", "local.py"))
    assert "integration:documents" not in resolve.LISTED
