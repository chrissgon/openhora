"""Tests of `read --as-source` of the documents provider on Notion (providers/documents/notion.py): the verb the sources module
(runtime/sources.py) calls to read a page the person chose as a source. It uses a SEPARATE read-only secret, NOTION_SOURCES_TOKEN,
and never NOTION_TOKEN; it needs no documents configuration; it asks for no comments. Against the stand-in service
(fake_notion.py): no network, no real workspace, no real credential.

Run: uv run --with pytest==9.1.1 pytest providers/documents/tests/test_documents_notion_as_source.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
SCRIPT = REPO / "providers" / "documents" / "notion.py"
sys.path.insert(0, str(HERE))
import documents_harness  # noqa: E402
import pytest  # noqa: E402

SECRETS = ("NOTION_TOKEN", "NOTION_SOURCES_TOKEN")


class Case:
    def __init__(self, tmp_path: Path):
        self.harness = documents_harness.NotionDocuments()
        self.config = tmp_path / "documents.json"
        self.config.write_text(json.dumps(self.harness.config(tmp_path)), encoding="utf-8")
        self.fake, self.tmp = self.harness.fake, tmp_path
        self.count = 0

    def run(self, *argv, tokens=None):
        """The provider with an environment that holds exactly the tokens named (a dict), the stand-in service and no other secret."""
        base = {k: v for k, v in os.environ.items() if k not in SECRETS}
        env = {**base, "INTEGRATION_DOCUMENTS_NOTION_API_BASE": self.fake.base, **(tokens or {}),
               "INTEGRATION_DOCUMENTS_NOTION_LEDGER": str(self.tmp / "ledger" / "documents-notion.json")}
        done = subprocess.run([sys.executable, str(SCRIPT), *argv], capture_output=True, text=True, timeout=120, env=env)
        try:
            out = json.loads(done.stdout) if done.stdout.strip() else None
        except ValueError:
            out = None
        return done.returncode, out, done.stdout + done.stderr

    def page(self, markdown: str) -> str:
        """A page made with the token that writes (what the person owns); returns its id."""
        self.count += 1
        source = self.tmp / f"page-{self.count}.md"
        source.write_text(markdown, encoding="utf-8")
        code, out, said = self.run("write", "--config-file", str(self.config), "--path", "docs/notes.md", "--markdown-file", str(source),
                                   "--idempotency-key", f"k{self.count}", "--confirmed", tokens={"NOTION_TOKEN": self.fake.token})
        assert code == 0, said
        return out["id"]


@pytest.fixture
def case(tmp_path):
    return Case(tmp_path)


def test_a_page_is_read_as_a_source_with_the_read_only_secret_alone_and_no_documents_configuration(case):
    ident = case.page("# Survey notes\n\nThe clinics said they want shorter forms.\n")
    start = len(case.fake.requests)
    code, out, said = case.run("read", "--id", ident, "--as-source", tokens={"NOTION_SOURCES_TOKEN": case.fake.token})
    assert code == 0, said
    assert out["id"] == ident and out["as_source"] is True and out["comments"] == [] and out["notice"] is None
    assert "Survey notes" in out["markdown"] and "shorter forms" in out["markdown"] and out["version"]
    asked = [(m, p) for m, p, _ in case.fake.requests[start:]]
    assert asked and all(m == "GET" for m, _ in asked), "a source is only read"
    assert not any("/v1/comments" in p for _, p in asked), "no comment is asked for"
    assert case.fake.token not in said


def test_the_token_that_writes_is_never_used_for_a_source(case):
    ident = case.page("# Notes\n")
    start = len(case.fake.requests)
    code, out, said = case.run("read", "--id", ident, "--as-source", tokens={"NOTION_TOKEN": case.fake.token})
    assert code == 3 and out is None and "NOTION_SOURCES_TOKEN" in said and "keyring set openhora notion-sources" in said
    assert len(case.fake.requests) == start, "no request was made with the other token"
    both = case.run("read", "--id", ident, "--as-source", tokens={"NOTION_TOKEN": "fake-write-token", "NOTION_SOURCES_TOKEN": case.fake.token})
    assert both[0] == 0, "with both set, the source verb uses the source token and the page is read"
    wrong = case.run("read", "--id", ident, "--as-source", tokens={"NOTION_TOKEN": case.fake.token, "NOTION_SOURCES_TOKEN": "fake-wrong"})
    assert wrong[0] == 3 and "401" in wrong[2] and "fake-wrong" not in wrong[2], "the write token does not rescue a wrong source token"


def test_the_flag_belongs_to_read_alone_and_the_ordinary_read_still_needs_its_configuration(case):
    ident = case.page("# Notes\n")
    for verb in ("stat", "comments"):
        code, _, said = case.run(verb, "--id", ident, "--as-source", "--config-file", str(case.config), tokens={"NOTION_TOKEN": case.fake.token})
        assert code == 2 and "read only" in said
    code, _, said = case.run("read", "--id", ident, tokens={"NOTION_TOKEN": case.fake.token})
    assert code == 2 and "--config-file" in said
    code, out, said = case.run("read", "--id", ident, "--config-file", str(case.config), tokens={"NOTION_TOKEN": case.fake.token})
    assert code == 0 and "as_source" not in out


def test_an_id_that_is_not_a_page_and_a_page_the_integration_was_not_given_are_refused_with_a_reason(case):
    tokens = {"NOTION_SOURCES_TOKEN": case.fake.token}
    code, _, said = case.run("read", "--id", "not-a-page", "--as-source", tokens=tokens)
    assert code == 1 and "no document" in said
    code, _, said = case.run("read", "--id", "0" * 32, "--as-source", tokens=tokens)
    assert code == 1 and "does not exist" in said or "no document" in said
