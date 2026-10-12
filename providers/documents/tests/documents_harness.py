"""How a person changes documents without the provider, per implementation of integration:documents: what the
contract tests (test_documents_contract.py) use to play the person. Not a test file.

Every implementation the resolver lists needs an entry in HARNESSES, or the contract tests fail. An entry is a class
whose instance gives:
  config(tmp_path) -> dict          the documents object of a project configuration, for a fresh place
  env() -> dict                     the environment variables the implementation needs (stand-in values only)
  person_edits(id, markdown)        a person replaces a document's text where it lives
  person_comments(id, text)         a person adds a comment to a document
  expected(markdown) -> str         what a read returns for a text that was written: the text itself for an
                                    implementation that stores Markdown, notion_blocks.round_trip(text) for one that
                                    stores blocks
  notices(id) -> list               the texts of the runtime's notices the document holds, where it lives, in order
  first_is_notice(id) -> bool       whether the document's first block is a notice
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LocalDocuments:
    """The local implementation: the documents are Markdown files in a folder a person edits by hand."""

    def config(self, tmp_path) -> dict:
        self.dir = Path(tmp_path) / "documents"
        self.dir.mkdir()
        return {"provider": "local", "dir": str(self.dir)}

    def env(self) -> dict:
        return {}

    def person_edits(self, ident: str, markdown: str) -> None:
        (self.dir / ident).write_text(markdown, encoding="utf-8")

    def person_comments(self, ident: str, text: str) -> None:
        side = self.dir / (ident + ".comments.md")
        before = side.read_text(encoding="utf-8") if side.is_file() else ""
        side.write_text(before + f"- {text}\n", encoding="utf-8")

    def expected(self, markdown: str) -> str:
        return markdown

    def notices(self, ident: str) -> list:
        prefix = "> [notice] "
        return [line[len(prefix):] for line in (self.dir / ident).read_text(encoding="utf-8").splitlines()
                if line.startswith(prefix)]

    def first_is_notice(self, ident: str) -> bool:
        return (self.dir / ident).read_text(encoding="utf-8").startswith("> [notice] ")


class NotionDocuments:
    """The Notion implementation, against the stand-in service of fake_notion.py: the documents are pages under a
    parent page of the stand-in, and the person edits them there."""

    fake_notion = None

    def config(self, tmp_path) -> dict:
        if NotionDocuments.fake_notion is None:
            NotionDocuments.fake_notion = _load("fake_notion_for_documents", HERE / "fake_notion.py")
        self.blocks = _load("notion_blocks_for_documents_harness", HERE.parent / "notion_blocks.py")
        self.fake = NotionDocuments.fake_notion.shared()
        self.parent = self.fake.create_root()
        self.ledger = Path(tmp_path) / "ledger" / "documents-notion.json"
        return {"provider": "notion", "parent": self.parent, "expires": "2099-12-31"}

    def env(self) -> dict:
        return {"NOTION_TOKEN": self.fake.token, "INTEGRATION_DOCUMENTS_NOTION_API_BASE": self.fake.base,
                "INTEGRATION_DOCUMENTS_NOTION_LEDGER": str(self.ledger)}

    def person_edits(self, ident: str, markdown: str) -> None:
        self.fake.person_replaces_body(ident, self.blocks.to_blocks(markdown))

    def person_comments(self, ident: str, text: str) -> None:
        self.fake.comment(ident, text)

    def expected(self, markdown: str) -> str:
        return self.blocks.round_trip(markdown)

    def _top(self, ident: str) -> list:
        with self.fake.lock:
            return [self.fake.blocks[i] for i in self.fake.children[ident] if not self.fake.blocks[i]["in_trash"]]

    def notices(self, ident: str) -> list:
        icon = "\U0001F512"
        return ["".join(r["text"]["content"] for r in b["callout"]["rich_text"]) for b in self._top(ident)
                if b["type"] == "callout" and (b["callout"].get("icon") or {}).get("emoji") == icon]

    def first_is_notice(self, ident: str) -> bool:
        top = self._top(ident)
        return bool(top) and top[0]["type"] == "callout" and (top[0]["callout"].get("icon") or {}).get(
            "emoji") == "\U0001F512"


HARNESSES = {"local": LocalDocuments, "notion": NotionDocuments}
