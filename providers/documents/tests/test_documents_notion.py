"""Tests of the documents on Notion (providers/documents/notion.py) beyond the contract, against the stand-in service
(fake_notion.py). Offline: no network, no real credential.

Run: uv run --with pytest==9.1.1 pytest providers/documents/tests/test_documents_notion.py
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


class Documents:
    def __init__(self, tmp_path: Path):
        self.harness = documents_harness.NotionDocuments()
        cfg = self.harness.config(tmp_path)
        self.fake = self.harness.fake
        self.config = tmp_path / "documents.json"
        self.config.write_text(json.dumps(cfg), encoding="utf-8")
        self.tmp = tmp_path
        self.count = 0

    def run(self, *argv, env=None):
        done = subprocess.run([sys.executable, str(SCRIPT), *argv] + ([] if "--config-file" in argv else ["--config-file", str(self.config)]),
                              capture_output=True, text=True, timeout=120,
                              env={**os.environ, **self.harness.env(), **(env or {})})
        try:
            out = json.loads(done.stdout) if done.stdout.strip() else None
        except ValueError:
            out = None
        return done.returncode, out, done.stdout + done.stderr

    def write(self, markdown: str, key: str, ident=None, mode="--confirmed"):
        self.count += 1
        source = self.tmp / f"doc-{self.count}.md"
        source.write_text(markdown, encoding="utf-8")
        return self.run("write", "--path", "docs/brand/strategy.md", "--markdown-file", str(source),
                        "--idempotency-key", key, mode, *(["--id", ident] if ident else []))


def nesting(blocks: list) -> int:
    return max((1 + nesting(b[b["type"]].get("children") or []) for b in blocks if b[b["type"]].get("children")),
               default=0)


def texts(value) -> list:
    if isinstance(value, dict):
        own = [value["text"]["content"]] if value.get("type") == "text" and isinstance(value.get("text"), dict) else []
        return own + [t for v in value.values() for t in texts(v)]
    if isinstance(value, list):
        return [t for v in value for t in texts(v)]
    return []


def test_the_token_is_never_printed_and_a_redirect_is_refused(tmp_path):
    docs = Documents(tmp_path)
    made = docs.write("# Strategy\n\nThe why.\n", key="k1")[1]
    docs.fake.redirect_next = True
    code, out, said = docs.run("read", "--id", made["id"])
    assert code == 1 and out is None and "redirect" in said and docs.fake.redirected == 0
    assert docs.fake.token not in said
    code, _, said = docs.run("stat", "--id", made["id"], env={"NOTION_TOKEN": "fake-wrong-token"})
    assert code == 3 and "401" in said and "fake-wrong-token" not in said
    for argv in (("stat", "--id", made["id"]), ("read", "--id", made["id"]), ("--check",)):
        code, _, said = docs.run(*argv)
        assert code == 0 and docs.fake.token not in said
    code, out, said = docs.write("# Other\n", key="k2", ident=made["id"], mode="--dry-run")
    assert code == 0 and out["dry_run"] is True and docs.fake.token not in said


def test_the_provider_names_itself_openhora_in_the_user_agent(tmp_path):
    docs = Documents(tmp_path)
    assert docs.run("--check")[0] == 0
    assert docs.fake.user_agents and set(docs.fake.user_agents) == {"openhora-documents-notion"}


def test_a_base_address_that_is_not_loopback_is_refused(tmp_path):
    docs = Documents(tmp_path)
    before = len(docs.fake.requests)
    for address in ("https://api.notion.example", "http://192.168.1.10:8080"):
        env = {"INTEGRATION_DOCUMENTS_NOTION_API_BASE": address}
        for argv in (("--check",), ("stat", "--id", docs.harness.parent)):
            code, out, said = docs.run(*argv, env=env)
            assert code == 2 and out is None and "loopback" in said and docs.fake.token not in said
    assert len(docs.fake.requests) == before


def test_a_long_document_is_written_in_calls_no_larger_than_the_limit(tmp_path):
    docs = Documents(tmp_path)
    nb = docs.harness.blocks
    lines = ["# A long document", ""]
    for n in range(1, 291):
        lines += [f"Paragraph {n}: " + "word " * (500 if n == 7 else 5), ""]
    lines += ["- one", "  - two", "    - three", "      - four", "", "| a | b |", "|---|---|", "| 1 | 2 |", ""]
    markdown = "\n".join(lines)
    assert len(nb.to_blocks(markdown)) >= 290 and nesting(nb.to_blocks(markdown)) == 3
    start = len(docs.fake.requests)
    code, out, said = docs.write(markdown, key="long")
    assert code == 0 and out["created"] is True, said
    appends = [body for method, path, body in docs.fake.requests[start:]
               if method == "PATCH" and path.endswith("/children")]
    assert len(appends) >= 3
    for body in appends:
        assert len(body["children"]) <= 100 and nesting(body["children"]) <= 1
        assert all(len(t) <= 2000 for t in texts(body["children"]))
    assert docs.run("read", "--id", out["id"])[1]["markdown"] == nb.round_trip(markdown)
    # A second write replaces every block, the nested ones too, in calls of the same size.
    start = len(docs.fake.requests)
    code, _, said = docs.write(markdown.replace("Paragraph 1:", "Paragraph one:"), key="long", ident=out["id"])
    assert code == 0, said
    assert all(len(body["children"]) <= 100 for method, path, body in docs.fake.requests[start:]
               if method == "PATCH" and path.endswith("/children"))
    assert docs.run("read", "--id", out["id"])[1]["markdown"] == nb.round_trip(
        markdown.replace("Paragraph 1:", "Paragraph one:"))


def top_ids(docs, ident: str) -> list:
    with docs.fake.lock:
        return [i for i in docs.fake.children[ident] if not docs.fake.blocks[i]["in_trash"]]


def test_a_write_appends_the_new_blocks_before_it_deletes_the_old_ones(tmp_path):
    """The page write order (notion.py): the new blocks are appended first, then the old ones are deleted, so a write
    that fails never leaves the page empty."""
    docs = Documents(tmp_path)
    nb = docs.harness.blocks
    made = docs.write("# Strategy\n\nThe first why.\n\n- one\n- two\n", key="k1")[1]
    old = top_ids(docs, made["id"])
    start = len(docs.fake.requests)
    code, _, said = docs.write("# Strategy\n\nThe second why.\n", key="k2", ident=made["id"])
    assert code == 0, said
    sent = docs.fake.requests[start:]
    appends = [n for n, (method, path, _) in enumerate(sent) if method == "PATCH" and path.endswith("/children")]
    deletes = [n for n, (method, _, _) in enumerate(sent) if method == "DELETE"]
    assert appends and deletes and max(appends) < min(deletes), "an old block was deleted before every new one was appended"
    assert sorted(path.rsplit("/", 1)[1] for method, path, _ in sent if method == "DELETE") == sorted(old)
    second = docs.run("read", "--id", made["id"])[1]["markdown"]
    assert second == nb.round_trip("# Strategy\n\nThe second why.\n")
    # A write whose append fails deletes nothing: the page keeps what it held.
    docs.fake.fail_next("append_children", 400)
    start = len(docs.fake.requests)
    code, _, said = docs.write("# Strategy\n\nThe third why.\n", key="k3", ident=made["id"])
    assert code == 1, said
    assert not [path for method, path, _ in docs.fake.requests[start:] if method == "DELETE"]
    assert docs.run("read", "--id", made["id"])[1]["markdown"] == second


def test_a_creation_with_an_unknown_outcome_blocks_its_key_until_resolve(tmp_path):
    docs = Documents(tmp_path)
    docs.fake.fail_next("create_page", 504, carried_out=True)
    code, _, said = docs.write("# Strategy\n", key="plan-1-strategy")
    assert code == 1 and "504" in said
    made = next(i for i, p in docs.fake.pages.items() if p["parent"].get("page_id") == docs.harness.parent)
    calls = docs.fake.count("create_page")
    code, _, said = docs.write("# Strategy\n", key="plan-1-strategy")
    assert code == 1 and "pending" in said and docs.fake.count("create_page") == calls
    assert docs.run("resolve", "--idempotency-key", "plan-1-strategy", "--id", made, "--confirmed")[0] == 0
    code, out, said = docs.write("# Strategy\n\nWritten.\n", key="plan-1-strategy")
    assert code == 0 and out["created"] is False and out["id"] == made, said


def test_too_many_requests_exits_1_with_the_status_and_is_not_retried(tmp_path):
    docs = Documents(tmp_path)
    made = docs.write("# Strategy\n", key="k1")[1]
    docs.fake.fail_next("retrieve_page", 429)
    calls = docs.fake.count("retrieve_page")
    code, out, said = docs.run("stat", "--id", made["id"])
    assert code == 1 and out is None and "429" in said and docs.fake.count("retrieve_page") == calls + 1


def test_a_parent_the_integration_was_not_given_is_not_configured(tmp_path):
    docs = Documents(tmp_path)
    other = tmp_path / "other.json"
    other.write_text(json.dumps({"provider": "notion", "parent": "0" * 32}), encoding="utf-8")
    code, out, said = docs.run("--check", "--config-file", str(other))
    assert code == 3 and out is None and "404" in said
    other.write_text(json.dumps({"provider": "notion", "parent": "not a page"}), encoding="utf-8")
    assert docs.run("--check", "--config-file", str(other))[0] == 2


def test_a_comment_on_one_block_is_read_with_the_document(tmp_path):
    # Measured on the live service (README.md, N4): a comment on a block is listed under that block, not the page's.
    docs = Documents(tmp_path)
    made = docs.write("# Strategy\n\nThe why.\n\n- one\n  - nested\n", key="k1")[1]
    page = made["id"].replace("-", "")
    page = next(i for i in docs.fake.pages if i.replace("-", "") == page)
    top = docs.fake.children[page]
    nested = docs.fake.children[top[-1]][0]
    docs.fake.comment(page, "On the page.")
    docs.fake.comment(top[1], "On the paragraph.")
    docs.fake.comment(nested, "On the nested item.")
    texts_read = [c["text"] for c in docs.run("read", "--id", made["id"])[1]["comments"]]
    assert texts_read == ["On the page.", "On the paragraph.", "On the nested item."]
    code, out, said = docs.write("# Strategy\n\nReplaced.\n", key="k2", ident=made["id"])
    assert code == 0, said
    texts_read = [c["text"] for c in docs.run("read", "--id", made["id"])[1]["comments"]]
    assert sorted(texts_read) == ["On the nested item.", "On the page.", "On the paragraph."]  # each once


def test_comments_is_one_listing_of_the_pages_own_comments_and_a_comment_does_not_move_the_version(tmp_path):
    # Measured on the live service (README.md, N3): a comment does not move the version, so the runtime lists the
    # page's own comments at every pull with this one call (WP-3.15); the comments on blocks come with read.
    docs = Documents(tmp_path)
    made = docs.write("# Strategy\n\nThe why.\n\nThe how.\n", key="k1")[1]
    page = next(i for i in docs.fake.pages if i.replace("-", "") == made["id"].replace("-", ""))
    before = docs.run("stat", "--id", made["id"])[1]["version"]
    docs.fake.comment(page, "On the page.")
    docs.fake.comment(docs.fake.children[page][1], "On the paragraph.")
    assert docs.run("stat", "--id", made["id"])[1]["version"] == before
    listed = docs.fake.count("list_comments")
    code, out, said = docs.run("comments", "--id", made["id"])
    assert code == 0, said
    assert [c["text"] for c in out["comments"]] == ["On the page."]
    assert docs.fake.count("list_comments") == listed + 1


def test_a_fenced_block_whose_language_the_service_does_not_know_goes_up_as_plain_text_and_comes_back_unchanged(tmp_path):
    # Measured on the live service (README.md, N11): a code block whose language is not on the service's list is
    # refused (400), and the stand-in refuses it too. Words a skill made up go up as "plain text" and come back.
    docs = Documents(tmp_path)
    markdown = ("# Identity\n\n```brand-tokens\nprimary: #1a2b3c\naccent: #fafafa\n```\n\nBetween.\n\n"
                "```python\nprint(1)\n```\n\n```voice-rules\n\nnever: shouting\n```\n\n```\nDRAFT\nno word\n```\n")
    start = len(docs.fake.requests)
    code, out, said = docs.write(markdown, key="fences")
    assert code == 0, said
    sent = [b["code"] for _, path, body in docs.fake.requests[start:] if path.endswith("/children") and body
            for b in body["children"] if b["type"] == "code"]
    assert [c["language"] for c in sent] == ["plain text", "python", "plain text", "plain text"]
    assert [c["rich_text"][0]["text"]["content"] for c in sent] == [
        "brand-tokens\nprimary: #1a2b3c\naccent: #fafafa", "print(1)", "voice-rules\n\nnever: shouting", "\nDRAFT\nno word"]
    assert docs.run("read", "--id", out["id"])[1]["markdown"] == markdown
    with pytest.raises(Exception, match="code.language") as refused:  # the stand-in's own answer to the old body
        docs.fake.checked_children({"children": [{"type": "code", "code": {"rich_text": [], "language": "brand-tokens"}}]})
    assert refused.value.status == 400


def test_the_notice_is_a_callout_added_at_the_start_of_an_existing_page_and_kept_by_a_write(tmp_path):
    docs = Documents(tmp_path)
    ident = docs.write("# Brand name\n\nA first paragraph.\n", key="k-notice")[1]["id"]
    seen = len(docs.fake.requests)
    code, out, err = docs.run("notice", "--id", ident, "--text", "Read-only here.", "--confirmed")
    assert code == 0 and out["added"] is True, err
    appends = [body for method, path, body in docs.fake.requests[seen:] if method == "PATCH"]
    assert len(appends) == 1 and appends[0]["position"] == {"type": "start"}
    with docs.fake.lock:
        top = [docs.fake.blocks[i] for i in docs.fake.children[ident]]
    assert top[0]["type"] == "callout" and top[0]["callout"]["icon"] == {"type": "emoji", "emoji": "\U0001F512"}
    assert texts(top[0]["callout"]) == ["Read-only here."] and top[1]["type"] == "heading_1"
    seen = len(docs.fake.requests)
    source = tmp_path / "again.md"
    source.write_text("# Brand name\n\nAnother paragraph.\n", encoding="utf-8")
    code, out, err = docs.run("write", "--id", ident, "--path", "docs/brand/name.md", "--markdown-file", str(source),
                              "--idempotency-key", "k-notice-2", "--notice", "Read-only here.", "--confirmed")
    assert code == 0, err
    later = docs.fake.requests[seen:]
    assert not any((body or {}).get("position") for _, _, body in later)  # the notice was kept, not written again
    with docs.fake.lock:
        top = [docs.fake.blocks[i] for i in docs.fake.children[ident] if not docs.fake.blocks[i]["in_trash"]]
    assert [b["type"] for b in top] == ["callout", "heading_1", "paragraph"]
