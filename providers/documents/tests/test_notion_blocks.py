"""Offline tests for providers/documents/notion_blocks.py: Markdown to the block objects of a Notion page and
back. No network and no credential: the conversion is pure.

The test that matters is the round trip of three documents, each written by a lab run of the skill that owns
it and kept in fixtures/round-trip.json: after going to blocks and coming back, each still passes the checker
of its skill. That is the one fidelity the documents design asks for; byte equality is not.

Run: uv run --with pytest==9.1.1 pytest providers/documents/tests
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "providers" / "documents" / "notion_blocks.py"
spec = importlib.util.spec_from_file_location("notion_blocks", SCRIPT)
nb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nb)
CASES = json.loads((Path(__file__).resolve().parent / "fixtures" / "round-trip.json").read_text(encoding="ascii"))["cases"]


def checked(case, folder):
    """Run every checker of the case in a folder that holds its files; {command: ok}."""
    out = {}
    for name, *args in case["checks"]:
        r = subprocess.run([sys.executable, str(REPO / "skills" / case["skill"] / "scripts" / name), *args],
                           capture_output=True, text=True, cwd=folder, timeout=60)
        out[name] = (r.returncode, json.loads(r.stdout).get("ok"))
    return out


@pytest.mark.parametrize("case", CASES, ids=[c["skill"] for c in CASES])
def test_a_document_that_went_to_blocks_and_came_back_still_passes_its_skills_checker(case, tmp_path):
    for rel, text in case["files"].items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text, encoding="utf-8")
    passing = {name: (0, True) for name, *_ in case["checks"]}
    assert checked(case, tmp_path) == passing, "the fixture itself must pass before the round trip"
    document = tmp_path / case["document"]
    after = nb.round_trip(document.read_text(encoding="utf-8"))
    document.write_text(after, encoding="utf-8")
    assert checked(case, tmp_path) == passing
    assert nb.round_trip(after) == after  # a second trip changes nothing: the page does not wear with each task


def kinds(blocks):
    return [b["type"] for b in blocks]


def test_each_markdown_block_becomes_the_block_of_its_kind():
    blocks = nb.to_blocks("# Title\n\n## Part\n### Detail\n\nA line.\nIts second line.\n\n- one\n- two\n\n1. first\n2. second\n\n"
                          "- [ ] open\n- [x] done\n\n> quoted\n> more\n\n---\n\n```python\nprint(1)\n```\n")
    assert kinds(blocks) == ["heading_1", "heading_2", "heading_3", "paragraph", "bulleted_list_item", "bulleted_list_item",
                             "numbered_list_item", "numbered_list_item", "to_do", "to_do", "quote", "divider", "code"]
    assert blocks[3]["paragraph"]["rich_text"][0]["text"]["content"] == "A line.\nIts second line."
    assert (blocks[8]["to_do"]["checked"], blocks[9]["to_do"]["checked"]) == (False, True)
    assert blocks[12]["code"]["language"] == "python" and blocks[12]["code"]["rich_text"][0]["text"]["content"] == "print(1)"
    assert all(b["object"] == "block" for b in blocks)


def test_a_table_keeps_its_header_its_width_and_a_pipe_inside_a_cell():
    text = "| Offer | Price (unit, date) | Source |\n|---|---|---|\n| Sites | EUR 10/month (2026) | [1] |\n| a \\| b | price not found | [2] |\n"
    table = nb.to_blocks(text)[0]["table"]
    assert (table["table_width"], table["has_column_header"], len(table["children"])) == (3, True, 3)
    assert table["children"][2]["table_row"]["cells"][0][0]["text"]["content"] == "a | b"
    assert nb.round_trip(text) == text


def test_a_nested_list_item_is_a_child_of_the_item_above_it():
    text = "- parent\n  - child\n    - grandchild\n- next\n"
    blocks = nb.to_blocks(text)
    assert kinds(blocks) == ["bulleted_list_item", "bulleted_list_item"]
    child = blocks[0]["bulleted_list_item"]["children"][0]
    assert child["bulleted_list_item"]["children"][0]["bulleted_list_item"]["rich_text"][0]["text"]["content"] == "grandchild"
    assert nb.round_trip(text) == text


def test_bold_code_and_links_become_annotations_and_everything_else_stays_text():
    rich = nb.rich_text("See **this** and `check_refs.py --file a_b.md` at [the site](https://example.com/a_b) or *that* [1].")
    seen = [(r["text"]["content"], r["annotations"]["bold"], r["annotations"]["code"], (r["text"]["link"] or {}).get("url")) for r in rich]
    assert seen == [("See ", False, False, None), ("this", True, False, None), (" and ", False, False, None),
                    ("check_refs.py --file a_b.md", False, True, None), (" at ", False, False, None),
                    ("the site", False, False, "https://example.com/a_b"), (" or *that* [1].", False, False, None)]
    assert nb.plain(rich) == "See **this** and `check_refs.py --file a_b.md` at [the site](https://example.com/a_b) or *that* [1]."


def test_a_long_text_is_cut_into_objects_of_at_most_the_limit_and_comes_back_whole():
    long = "word " * 1000
    rich = nb.rich_text(long.strip())
    assert len(rich) == 3 and all(len(r["text"]["content"]) <= nb.TEXT_LIMIT for r in rich)
    assert nb.plain(rich) == long.strip()
    bold = nb.rich_text("**" + "b" * 2500 + "**")
    assert len(bold) == 2 and nb.plain(bold) == "**" + "b" * 2500 + "**"


def test_what_changes_on_the_way_is_what_the_file_says_changes():
    assert nb.round_trip("* a\n+ b\n") == "- a\n- b\n"
    assert nb.round_trip("3. a\n7. b\n") == "1. a\n2. b\n"
    assert nb.round_trip("#### Deep heading\n") == "#### Deep heading\n"
    assert nb.round_trip("# T\ntext\n- a\n\n\n\n- b\n") == "# T\n\ntext\n\n- a\n- b\n"
    assert nb.round_trip("") == "\n"


def test_a_fence_word_the_service_does_not_know_goes_up_as_plain_text_and_a_known_one_is_unchanged():
    known = nb.to_blocks("```python\nprint(1)\n```\n")[0]["code"]
    assert (known["language"], known["rich_text"][0]["text"]["content"]) == ("python", "print(1)")
    unknown = nb.to_blocks("```brand-tokens\nprimary: #1a2b3c\n```\n")[0]["code"]
    assert (unknown["language"], unknown["rich_text"][0]["text"]["content"]) == ("plain text", "brand-tokens\nprimary: #1a2b3c")
    assert "brand-tokens" not in nb.LANGUAGES and {"python", "plain text", "yaml"} <= nb.LANGUAGES
    for text in ("```brand-tokens\nprimary: #1a2b3c\n```\n", "```python\nprint(1)\n```\n", "```Python\nx\n```\n",
                 "```voice-rules\n\nnever: shouting\n```\n"):
        assert nb.round_trip(text) == text


def test_a_block_with_no_word_is_never_read_back_as_one_that_had_one():
    for text in ("```\nDRAFT\nnot a language\n```\n", "```\n\nstarts empty\n```\n", "```\npython\n```\n",
                 "```\nplain words\n```\n", "```\n\n```\n"):
        blocks = nb.to_blocks(text)
        assert blocks[0]["code"]["language"] == "plain text"
        assert nb.round_trip(text) == text
    escaped = nb.to_blocks("```\nDRAFT\nnot a language\n```\n")[0]["code"]["rich_text"][0]["text"]["content"]
    assert escaped == "\nDRAFT\nnot a language"


def test_the_helper_is_not_an_implementation_of_a_class():
    """providers/resolve.py lists <name>.py as an implementation only when the name has no underscore."""
    spec2 = importlib.util.spec_from_file_location("resolve_for_documents", REPO / "providers" / "resolve.py")
    resolve = importlib.util.module_from_spec(spec2)
    spec2.loader.exec_module(resolve)
    assert "notion_blocks" not in resolve.implementations_in("documents", root=str(REPO))


def test_the_command_line_converts_in_both_directions_and_refuses_anything_else():
    run = lambda *args, data="": subprocess.run([sys.executable, str(SCRIPT), *args], input=data, capture_output=True, text=True, timeout=60)
    blocks = run("to-blocks", data="# T\n\n- a\n")
    assert blocks.returncode == 0 and kinds(json.loads(blocks.stdout)) == ["heading_1", "bulleted_list_item"]
    assert run("to-markdown", data=blocks.stdout).stdout == "# T\n\n- a\n"
    assert run("round-trip", data="# T\n- a\n").stdout == "# T\n\n- a\n"
    assert run("--help").returncode == 0 and run("upload").returncode == 2 and run().returncode == 2
