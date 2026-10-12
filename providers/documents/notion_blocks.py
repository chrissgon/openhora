#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Markdown to the block objects of a Notion page, and back. A pure conversion: no network, no credential.

Usage:
  python3 providers/documents/notion_blocks.py to-blocks < document.md > blocks.json
  python3 providers/documents/notion_blocks.py to-markdown < blocks.json > document.md
  python3 providers/documents/notion_blocks.py round-trip < document.md > document-after.md

This file is a helper of the documents provider for Notion (class integration:documents, stage 3 of the
platform plan), not an implementation of a class: providers/resolve.py lists a file as an implementation only
when its name is lowercase letters, digits and hyphens, and this one has an underscore.

What is promised is one direction of fidelity: a document that goes to blocks and comes back still passes the
checker of the skill that owns it. It is not promised to come back byte for byte. What changes on the way:
  - blocks are separated by one blank line, except the items of one list and the rows of one table;
  - a numbered list is numbered again from 1;
  - "*" and "+" bullets come back as "-";
  - a heading of level 4 or deeper has no block of its own: it travels as a paragraph that keeps its "#"
    marks as text, and comes back as it was;
  - of inline Markdown only **bold**, `code` and [text](address) become annotations; everything else,
    emphasis with one "*" or "_" included, travels as the characters it is.

A fenced block's language word comes back as it was. The service accepts only the languages of its list
(LANGUAGES, below) and refuses a write that carries any other (measured on the live service, README.md, N11). A
block whose word is not on the list, a word the document's skill made up included, goes up as "plain text" with
the word alone as the block's first line, and that line becomes the fence's word again on the way back. So that a
block written with no word cannot be read as one that had one, a block with no word whose first line is empty or is
a lone word that is not on the list goes up with one empty line in front, which the way back removes. A person who
writes a "plain text" block on the page in either of those two shapes gets the same reading.

The block shapes are those of the service's public API reference (block objects with "type" and a key of that
name holding "rich_text"; "table" with "table_row" children; "to_do" with "checked"). They were written from
that reference and have not been checked against the live service by this file's tests, which are offline.
A text object holds at most TEXT_LIMIT characters; longer text is cut into several objects.

Exit codes: 0 ok, 2 usage error. Standard library only.
"""
from __future__ import annotations

import json
import re
import sys

TEXT_LIMIT = 2000
HEADING = re.compile(r"^(#{1,3})\s+(.*?)\s*$")
FENCE = re.compile(r"^(`{3,}|~{3,})\s*([\w+-]*)\s*$")
TODO = re.compile(r"^(\s*)[-*+]\s+\[([ xX])\]\s+(.*)$")
BULLET = re.compile(r"^(\s*)[-*+]\s+(.*)$")
NUMBERED = re.compile(r"^(\s*)\d+[.)]\s+(.*)$")
QUOTE = re.compile(r"^>\s?(.*)$")
DIVIDER = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$")
TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")
TABLE_RULE = re.compile(r"^\s*\|?\s*:?-{1,}:?\s*(?:\|\s*:?-{1,}:?\s*)*\|?\s*$")
INLINE = re.compile(r"\*\*(?P<bold>[^*\n]+?)\*\*|`(?P<code>[^`\n]+)`|\[(?P<text>[^\]\n]+)\]\((?P<url>[^)\s]+)\)")
LIST_TYPES = ("bulleted_list_item", "numbered_list_item", "to_do")
PLAIN = "plain text"
# The values the service accepts for a code block's "language": the public API reference, page "Block" (section
# "Code", https://developers.notion.com/reference/block), read on 2026-10-06. The live service's refusal of
# 2026-10-06 named further values (README.md, N11); they are left out until the reference lists them, and a block
# that carries one travels as an unknown word does, coming back unchanged.
LANGUAGES = frozenset((
    "abap", "arduino", "bash", "basic", "c", "clojure", "coffeescript", "c++", "c#", "css", "dart", "diff", "docker",
    "elixir", "elm", "erlang", "flow", "fortran", "f#", "gherkin", "glsl", "go", "graphql", "groovy", "haskell", "html",
    "java", "javascript", "json", "julia", "kotlin", "latex", "less", "lisp", "livescript", "lua", "makefile",
    "markdown", "markup", "matlab", "mermaid", "nix", "objective-c", "ocaml", "pascal", "perl", "php", "plain text",
    "powershell", "prolog", "protobuf", "python", "r", "reason", "ruby", "rust", "sass", "scala", "scheme", "scss",
    "shell", "sql", "swift", "typescript", "vb.net", "verilog", "vhdl", "visual basic", "webassembly", "xml", "yaml",
    "java/c/c++/c#"))
WORD = re.compile(r"[\w+-]+")  # a fence's language word, as FENCE reads it


def unknown_word(line: str) -> bool:
    """A line that is a lone language word the service does not accept: the marker of a "plain text" block."""
    return bool(WORD.fullmatch(line)) and line not in LANGUAGES


def code_block(language: str, body: list) -> dict:
    """A fenced block: a word on the list is the block's language; any other word goes up as "plain text" with the
    word as the first line; a block with no word is escaped with one empty line when it could be read as marked."""
    if language in LANGUAGES:
        lines = body
    elif language:
        language, lines = PLAIN, [language] + body
    else:
        language = PLAIN
        lines = [""] + body if body and (body[0] == "" or unknown_word(body[0])) else body
    return {"object": "block", "type": "code", "code": {"rich_text": text_object("\n".join(lines)), "language": language}}


def fence_of(body: dict) -> tuple:
    """A code block's body back to (fence word, text): the reverse of code_block."""
    language = body.get("language") or ""
    text = "".join((i.get("text") or {}).get("content", "") for i in body.get("rich_text") or [])
    if language != PLAIN:
        return language, text
    first, sep, rest = text.partition("\n")
    if first == "" and sep:
        return "", rest
    if unknown_word(first):
        return first, rest
    return "", text


def text_object(content: str, bold: bool = False, code: bool = False, url=None) -> list:
    """One run of text as text objects, cut at TEXT_LIMIT characters."""
    return [{"type": "text", "text": {"content": content[i:i + TEXT_LIMIT], "link": {"url": url} if url else None},
             "annotations": {"bold": bold, "italic": False, "strikethrough": False, "underline": False, "code": code,
                             "color": "default"}}
            for i in range(0, len(content), TEXT_LIMIT)]


def rich_text(text: str) -> list:
    out, at = [], 0
    for m in INLINE.finditer(text):
        if m.start() > at:
            out += text_object(text[at:m.start()])
        if m.group("bold") is not None:
            out += text_object(m.group("bold"), bold=True)
        elif m.group("code") is not None:
            out += text_object(m.group("code"), code=True)
        else:
            out += text_object(m.group("text"), url=m.group("url"))
        at = m.end()
    if at < len(text):
        out += text_object(text[at:])
    return out


def plain(rich: list) -> str:
    """Rich text back to inline Markdown. Adjacent runs with the same marks are one run (a long text was cut)."""
    runs = []
    for item in rich or []:
        content = (item.get("text") or {}).get("content", item.get("plain_text", ""))
        notes, link = item.get("annotations") or {}, (item.get("text") or {}).get("link") or {}
        marks = (bool(notes.get("code")), bool(notes.get("bold")), bool(notes.get("italic")), link.get("url"))
        if runs and runs[-1][0] == marks:
            runs[-1][1] += content
        else:
            runs.append([marks, content])
    parts = []
    for (code, bold, italic, url), content in runs:
        if code:
            content = f"`{content}`"
        if bold:
            content = f"**{content}**"
        if italic:
            content = f"*{content}*"
        if url:
            content = f"[{content}]({url})"
        parts.append(content)
    return "".join(parts)


def block(kind: str, text: str, **more) -> dict:
    return {"object": "block", "type": kind, kind: {"rich_text": rich_text(text), **more}}


def cells(line: str) -> list:
    body = line.strip()
    body = body[1:] if body.startswith("|") else body
    body = body[:-1] if body.endswith("|") and not body.endswith("\\|") else body
    return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", body)]


def to_blocks(markdown: str) -> list:
    """The blocks of a Markdown document, top level first; a nested list item is in its parent's "children"."""
    lines, blocks, i = markdown.replace("\r\n", "\n").split("\n"), [], 0
    stack = []  # [(indent, list item block)]: the open list items a deeper item nests under

    def add(new: dict, indent=None):
        while stack and (indent is None or stack[-1][0] >= indent):
            stack.pop()
        if stack:
            stack[-1][1][stack[-1][1]["type"]].setdefault("children", []).append(new)
        else:
            blocks.append(new)
        if indent is not None:
            stack.append((indent, new))

    while i < len(lines):
        line = lines[i]
        fence = FENCE.match(line)
        if fence:
            body, i = [], i + 1
            while i < len(lines) and not lines[i].startswith(fence.group(1)):
                body.append(lines[i])
                i += 1
            add(code_block(fence.group(2), body))
            i += 1
            continue
        if not line.strip():
            i += 1
            if i < len(lines) and not (TODO.match(lines[i]) or BULLET.match(lines[i]) or NUMBERED.match(lines[i])):
                stack.clear()  # a blank line ends a list unless the list goes on
            continue
        heading = HEADING.match(line)
        if heading:
            add(block(f"heading_{len(heading.group(1))}", heading.group(2)))
        elif DIVIDER.match(line):
            add({"object": "block", "type": "divider", "divider": {}})
        elif TABLE_ROW.match(line) and i + 1 < len(lines) and TABLE_RULE.match(lines[i + 1]) and "-" in lines[i + 1]:
            rows = [cells(line)]
            i += 2
            while i < len(lines) and TABLE_ROW.match(lines[i]):
                rows.append(cells(lines[i]))
                i += 1
            width = max(len(r) for r in rows)
            add({"object": "block", "type": "table", "table": {
                "table_width": width, "has_column_header": True, "has_row_header": False,
                "children": [{"object": "block", "type": "table_row",
                              "table_row": {"cells": [rich_text(c) for c in r + [""] * (width - len(r))]}} for r in rows]}})
            continue
        elif TODO.match(line):
            m = TODO.match(line)
            add(block("to_do", m.group(3), checked=m.group(2) != " "), indent=len(m.group(1)))
        elif BULLET.match(line):
            m = BULLET.match(line)
            add(block("bulleted_list_item", m.group(2)), indent=len(m.group(1)))
        elif NUMBERED.match(line):
            m = NUMBERED.match(line)
            add(block("numbered_list_item", m.group(2)), indent=len(m.group(1)))
        elif QUOTE.match(line):
            body = []
            while i < len(lines) and QUOTE.match(lines[i]):
                body.append(QUOTE.match(lines[i]).group(1))
                i += 1
            add(block("quote", "\n".join(body)))
            continue
        else:  # a paragraph: the plain lines up to a blank line or to a line that starts another block
            body = [line.strip()]
            i += 1
            while i < len(lines) and lines[i].strip() and not any(
                    rx.match(lines[i]) for rx in (HEADING, FENCE, TODO, BULLET, NUMBERED, QUOTE, DIVIDER, TABLE_ROW)):
                body.append(lines[i].strip())
                i += 1
            add(block("paragraph", "\n".join(body)))
            continue
        i += 1
    return blocks


def to_markdown(blocks: list) -> str:
    """Blocks back to Markdown: one blank line between blocks, none inside a list or a table."""
    out = []

    def item_lines(item: dict, depth: int, number: int) -> list:
        kind, body = item["type"], item[item["type"]]
        mark = {"bulleted_list_item": "-", "numbered_list_item": f"{number}.",
                "to_do": "- [x]" if body.get("checked") else "- [ ]"}[kind]
        first, *rest = (plain(body.get("rich_text")) or "").split("\n")
        lines = ["  " * depth + f"{mark} {first}"] + ["  " * (depth + 1) + r for r in rest]
        count = 0
        for child in body.get("children") or []:
            if child["type"] in LIST_TYPES:
                count = count + 1 if child["type"] == "numbered_list_item" else 0
                lines += item_lines(child, depth + 1, count)
        return lines

    previous, count = None, 0
    for b in blocks:
        kind, body = b["type"], b.get(b["type"]) or {}
        if kind in LIST_TYPES:
            count = count + 1 if kind == "numbered_list_item" and previous == kind else 1
            if previous not in LIST_TYPES and out:
                out.append("")
            out += item_lines(b, 0, count)
            previous = kind
            continue
        if out:
            out.append("")
        if kind in ("heading_1", "heading_2", "heading_3"):
            out.append("#" * int(kind[-1]) + " " + plain(body.get("rich_text")))
        elif kind == "paragraph":
            out.append(plain(body.get("rich_text")))
        elif kind == "quote":
            out += ["> " + line for line in plain(body.get("rich_text")).split("\n")]
        elif kind == "code":
            language, text = fence_of(body)
            out += ["```" + language, text, "```"]
        elif kind == "divider":
            out.append("---")
        elif kind == "table":
            rows = [[plain(c).replace("|", "\\|").replace("\n", " ") for c in r["table_row"]["cells"]] for r in body.get("children") or []]
            for n, row in enumerate(rows):
                out.append("| " + " | ".join(row) + " |")
                if n == 0:
                    out.append("|" + "|".join(["---"] * len(row)) + "|")
        else:  # a block this file does not write: its text is kept, as a paragraph
            out.append(plain(body.get("rich_text")) if isinstance(body, dict) else "")
        previous = kind
    return "\n".join(out).rstrip("\n") + "\n"


def round_trip(markdown: str) -> str:
    return to_markdown(to_blocks(markdown))


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv not in (["to-blocks"], ["to-markdown"], ["round-trip"]):
        print(__doc__.strip(), file=sys.stdout if argv in (["--help"], ["-h"]) else sys.stderr)
        return 0 if argv in (["--help"], ["-h"]) else 2
    data = sys.stdin.read()
    if argv == ["to-blocks"]:
        print(json.dumps(to_blocks(data), ensure_ascii=False, indent=1))
    elif argv == ["to-markdown"]:
        sys.stdout.write(to_markdown(json.loads(data)))
    else:
        sys.stdout.write(round_trip(data))
    return 0


if __name__ == "__main__":
    sys.exit(main())
