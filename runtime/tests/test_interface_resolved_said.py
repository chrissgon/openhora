"""Tests of A-41 (ADJ-B4): a resolved line of the Inbox, opened, shows what the person answered, commented or noted. The `answer` the `task`
read carries (test_read_ops.py) reaches `resolvedLines()` as `said`, and `floor/inbox.js` draws it under the date as plain text, in the Floor's
Inbox and, through the same code, in the Lobby's. No browser and no model: the modules run under Node with the fake document of the Floor's
tests. The served page was looked at in a browser pane by the package's report.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interface_resolved_said.py
"""
from __future__ import annotations

import json
import re
import subprocess

from test_interface_adjustments import FAKE_EXTRA  # what the Lobby's modules use
from test_interface_floor import FAKE_DOM, INTERFACE, needs_node, NODE
from interface_css import stylesheets

CSS = stylesheets()
JS = INTERFACE / "js"

SCRIPT = r"""
import { FakeNode, settle, find, all } from "@FAKE@";
import { setToken } from "@JS@/token.js";
import * as fm from "@JS@/floor-model.js";
import { createInbox } from "@JS@/floor/inbox.js";
import { createLobbyInbox } from "@JS@/views/lobby-inbox.js";

setToken("t".repeat(40));
const NOW = new Date("2026-10-09T12:00:00Z");
const ago = (h) => new Date(NOW.getTime() - h * 3600e3).toISOString();
const MARKUP = 'See <b>this</b> and <script>alert(1)</script> & <img src=x onerror=alert(2)>\nsecond line';
const row = (id, kind, resolution, answer) => ({ id, kind, status: "resolved", resolution, answer, title: `Decision ${id}`, created_at: "", resolved_at: "" });
const pending = [
  row(1, "question", "answered", "The price with tax, always."),
  row(2, "review", "answered", "Shorten the second paragraph."),
  row(3, "plan", "rejected", "Too early: wait for the sale page."),
  row(4, "effect", "rejected", "Not this week."),
  row(5, "effect", "answered", "Change the second line."),
  row(6, "review", "released", null),
  row(7, "plan", "rejected", null),
  row(8, "plan", "approved", null),
  row(9, "question", "answered", "   \n  "),
  row(10, "question", "answered", MARKUP),
  row(11, "review", "released", "text that a release never has"),
  row(12, "acceptance", "rejected", ""),
].map((r, i) => ({ ...r, resolved_at: ago(i + 1), created_at: ago(i + 2) }));
pending.push({ id: 13, kind: "effect", status: "cancelled", resolution: null, answer: "a cancelled decision", title: "Cancelled", created_at: ago(40), resolved_at: ago(30) });
pending.push({ id: 14, kind: "question", status: "resolved", resolution: "answered", title: "No field at all (an older read)", created_at: ago(51), resolved_at: ago(50) });
const lines = fm.resolvedLines({ 4: { task: { id: 4 }, runs: [], pending } }, [4], NOW, 20);
const out = {};
out.model = Object.fromEntries(lines.map((l) => [l.id, l.said === null || l.said === undefined ? null : [l.said.label, l.said.text]]));
out.unchanged = lines.map((l) => [l.id, l.text, l.tone, l.age]).slice(0, 3);

const links = { open: () => "#", floor: () => "#", lobby: () => "#", parent: () => "#" };
function blocks(root) {
  return Object.fromEntries(all(root, "details.wb-resolved-item").map((d) => {
    const title = find(d, ".wb-resolved-title").textContent;
    const said = find(d, ".wb-res-said");
    return [title, said === null ? null : { label: find(said, ".wb-card-label").textContent, text: find(said, "p").textContent, inP: find(said, "p").children.length, tag: find(said, "p").tagName, hint: find(d, ".wb-resolved-body").textContent.split("\n")[0] }];
  }));
}
const inbox = createInbox({ project: "p", now: () => NOW, api: {}, refresh() {}, links });
inbox.update({ decisions: [], requests: [], resolved: lines, selected: null, loading: false });
out.floor = blocks(inbox.el);
out.markup = [...inbox.el.walk()].filter((n) => ["B", "SCRIPT", "IMG", "I"].includes(n.tagName)).length;
out.attrs = [...inbox.el.walk()].filter((n) => "onerror" in n.attrs || "src" in n.attrs).length;
out.order = all(inbox.el, "details.wb-resolved-item")[0].children.map((c) => (c.attrs.class || c.tagName));

const lobby = createLobbyInbox({ project: "0123456789ab", now: () => NOW, refresh() {} });
lobby.update({ cards: [], pointers: [], requests: [], resolved: lines, selected: null, loading: false });
out.lobby = blocks(lobby.el);
console.log(JSON.stringify(out));
process.exit(0);
"""


def run(tmp_path, body):
    fake = tmp_path / "fake-dom.mjs"
    fake.write_text(FAKE_DOM + FAKE_EXTRA, encoding="utf-8")
    script = tmp_path / "check.mjs"
    script.write_text(body.replace("@JS@", JS.as_uri()).replace("@FAKE@", fake.as_uri()), encoding="utf-8")
    done = subprocess.run([NODE, str(script)], capture_output=True, text=True, timeout=90)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


MARKUP = 'See <b>this</b> and <script>alert(1)</script> & <img src=x onerror=alert(2)>\nsecond line'


@needs_node
def test_a_resolved_line_carries_the_text_with_the_label_of_what_the_person_did(tmp_path):
    got = run(tmp_path, SCRIPT)
    model = got["model"]
    assert model["1"] == ["Your answer", "The price with tax, always."], "a question answered"
    assert model["2"] == ["Your comment", "Shorten the second paragraph."], "a review sent back"
    assert model["3"] == ["Your note", "Too early: wait for the sale page."], "a plan rejected with a note"
    assert model["4"] == ["Your note", "Not this week."], "an effect rejected with a note"
    assert model["5"] == ["Your comment", "Change the second line."], "a comment on an effect is a comment"
    assert model["10"] == ["Your answer", MARKUP], "the text is kept as typed"
    assert got["unchanged"][0][1:] == ["Question answered", "pui-success pui-soft", "1 h"], "the chip, the tone and the age are as before"


@needs_node
def test_a_line_with_no_saved_text_has_no_block(tmp_path):
    got = run(tmp_path, SCRIPT)
    for none in ("6", "7", "8", "9", "11", "12", "13", "14"):
        assert got["model"][none] is None, f"decision {none} saved no text the person can see"
    shown = got["floor"]
    for title in ("Decision 6", "Decision 7", "Decision 8", "Decision 9", "Decision 11", "Decision 12", "Cancelled", "No field at all (an older read)"):
        assert shown[title] is None, f"{title}: no block"
    assert [t for t, b in shown.items() if b is not None] == ["Decision 1", "Decision 2", "Decision 3", "Decision 4", "Decision 5", "Decision 10"]


@needs_node
def test_the_block_sits_under_the_date_with_its_label_and_the_text_as_plain_text(tmp_path):
    got = run(tmp_path, SCRIPT)
    first = got["floor"]["Decision 1"]
    assert (first["label"], first["text"], first["inP"], first["tag"]) == ("Your answer", "The price with tax, always.", 1, "P")
    assert first["hint"].startswith("Resolved "), "the date line is still there"
    assert got["floor"]["Decision 3"]["label"] == "Your note" and got["floor"]["Decision 2"]["label"] == "Your comment"
    assert got["order"] == ["wb-resolved", "wb-card-hint wb-resolved-body", "wb-res-said"], "the line, the date, and the block under the date"


@needs_node
def test_a_text_holding_markup_is_shown_as_characters_and_creates_no_element(tmp_path):
    got = run(tmp_path, SCRIPT)
    shown = got["floor"]["Decision 10"]
    assert shown["text"] == MARKUP and shown["inP"] == 1, "one text node holding the characters as typed"
    assert got["markup"] == 0, "no <b>, <script> or <img> element exists anywhere in the Inbox"
    assert got["attrs"] == 0, "no element carries src or onerror"


@needs_node
def test_the_lobbys_inbox_draws_the_same_blocks_through_the_same_code(tmp_path):
    got = run(tmp_path, SCRIPT)
    assert got["lobby"] == got["floor"]
    source = (JS / "views" / "lobby-inbox.js").read_text(encoding="utf-8")
    assert "createInbox" in source and "wb-res-said" not in source, "the Lobby draws no block of its own"


def test_the_text_is_never_drawn_with_the_markdown_renderer_or_as_markup():
    source = (JS / "floor" / "inbox.js").read_text(encoding="utf-8")
    imports = re.findall(r'^import .* from "([^"]+)"', source, re.M)
    assert not [i for i in imports if "markdown" in i], "the Markdown renderer is not imported"
    assert "innerHTML" not in source and "insertAdjacentHTML" not in source
    model = (JS / "floor-model.js").read_text(encoding="utf-8")
    assert "innerHTML" not in model


def test_the_block_has_the_drawings_rule_with_tokens_only():
    css = CSS.read_text(encoding="utf-8")
    rules = {m.group(1).strip(): m.group(2) for m in re.finditer(r"(\.wb-res-said[^{]*)\{([^}]*)\}", css)}
    assert ".wb-res-said" in rules and ".wb-res-said p" in rules
    block = rules[".wb-res-said"]
    for part in ("display: grid", "max-height: 24rem", "overflow-y: auto", "border-left: 2px solid var(--pui-border)", "background-color: var(--wb-sunken)"):
        assert part in block, part
    assert "white-space: pre-wrap" in rules[".wb-res-said p"] and "overflow-wrap: anywhere" in rules[".wb-res-said p"], "a long or multi-line text wraps and keeps its lines"
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgb\(|hsl\(", "".join(rules.values())), "no colour literal"
