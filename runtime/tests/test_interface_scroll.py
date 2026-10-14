"""The place of a reader in a long page (interface/js/dom.js `sync` and `keepScroll`, floor/tasks-tab.js, captions-view.js, video-card.js).

A person who checks 400 words of captions scrolls the panel down; every update of the page (the poll, a store change) must leave the panel where it is. Run under Node
with a fake document in which a scrolled panel loses its place the moment anything inside it changes (the worst a browser can do), so a redraw that replaces nodes
is caught twice: by the count of nodes it touched, and by the position it leaves. No browser, no service, no network. The page itself was looked at in a browser pane
by the package's report.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interface_scroll.py
"""
from __future__ import annotations

import pytest

from test_interface_captions import run
from test_interface_floor import JS, needs_node, run_node

HOLDS = r"""
import { createTasksTab } from "@JS@/floor/tasks-tab.js";
import { setToken } from "@JS@/token.js";
setToken("t".repeat(40));
const NOW = new Date("2026-10-14T12:00:00Z");
globalThis.location = { hostname: "127.0.0.1" };
globalThis.fetch = async (url) => {         // the body of a task: the same each time it is read
  const m = String(url).match(/\/tasks\/(\d+)$/);
  const id = m ? Number(m[1]) : 0;
  return { ok: Boolean(id), status: id ? 200 : 404, json: async () => ({ task: { id, state: id === 3 ? "failed" : "waiting", created_at: "2026-10-14T08:00:00Z", updated_at: "2026-10-14T10:00:00Z" }, runs: [], pending: [] }) };
};
const tabApi = { ...api, videoCard: async (p, rid) => ({ recording: rid, status: "open", platforms: ["instagram"], platform: "instagram", render: null, cover: null, caption: null, approval: null, sent_back: null, can_download: false, download_name: null, problems: [] }) };
const task = (id, key, extra = {}) => ({ id, key, title: `Task ${id}`, skill: null, state: "waiting", note: null, agent: "engineering", requestId: 1, ...extra });
const tab = createTasksTab({ project: "@PROJECT@", now: () => NOW, refresh: () => {}, api: tabApi, links: { request: () => "#r", inbox: () => "#i", open: () => "#o" } });
const panel = new FakeNode("div");          // the scrolled panel the tab lives in
panel.scrollTop = 0;
panel.append(tab.el);

// a browser may move a scrolled panel whenever what is inside it changes: here it always sends it to the top
let touched = 0;
const trace = new Map();
const touch = (node, moved) => { touched += 1; const k = (node.attrs.class || node.tagName) + (node.attrs["data-part"] ? ":" + node.attrs["data-part"] : ""); trace.set(k, (trace.get(k) || 0) + 1); if (moved) detached.set(moved, (detached.get(moved) || 0) + 1); for (let up = node; up; up = up.parent) if (up.scrollTop > 0) up.scrollTop = 0; };
const detached = new Map();
const { replaceChildren, insertBefore, remove } = FakeNode.prototype;
FakeNode.prototype.replaceChildren = function (...items) { touch(this); this.children.forEach((c) => detached.set(c, (detached.get(c) || 0) + 1)); return replaceChildren.apply(this, items); };
FakeNode.prototype.insertBefore = function (node, before) { touch(this, node); return insertBefore.call(this, node, before); };
FakeNode.prototype.remove = function () { if (this.parent) touch(this.parent, this); return remove.call(this); };

const tasks = (extra = {}) => [task(1, "media:@RID@", { title: "Edit the recording" }), task(2, "plain"), task(3, "other", { state: "failed" }), ...(extra.more || [])];
const data = (reload, list = tasks()) => ({ tasks: list, requests: [{ id: 1, title: "R", state: "ready" }], pending: [], loading: false, reload });
tab.update(data(1)); await settle();
find(tab.el, "[data-key=toggle-1]").click(); await settle();
tab.update(data(1)); await settle();
const li = (id) => all(tab.el, "li.wb-task").find((n) => n.attrs["data-task"] === String(id));
const held = { li1: li(1), li2: li(2), li3: li(3), media: find(tab.el, ".wb-media-task"), review: find(tab.el, "section.wb-rev"), words: find(tab.el, ".wb-rev-transcript"), group: find(tab.el, "details.wb-task-group") };
out.opened = { review: held.review !== null, words: all(tab.el, ".wb-rev-word").length > 50 };
const same = () => ({ li1: li(1) === held.li1, li2: li(2) === held.li2, media: find(tab.el, ".wb-media-task") === held.media, review: find(tab.el, "section.wb-rev") === held.review, words: find(tab.el, ".wb-rev-transcript") === held.words, group: find(tab.el, "details.wb-task-group") === held.group });

// 1. the person reads far down; a store change that changes nothing they see touches nothing
panel.scrollTop = 4000; touched = 0; detached.clear(); trace.clear();
tab.update(data(2)); await settle();
tab.update(data(3)); await settle();
out.quiet = { top: panel.scrollTop, touched, same: same() };
out.trace = [...trace];

// 2. a change that shows (a title, a task that moved group) redraws what changed and nothing else: the row that holds the review keeps every node, and the place is kept
panel.scrollTop = 4000; touched = 0; detached.clear();
tab.update(data(4, [task(1, "media:@RID@", { title: "Edit the recording" }), task(2, "plain", { title: "Renamed" }), task(3, "other", { state: "done" })])); await settle();
out.shown = { top: panel.scrollTop, touched: touched > 0, same: same(), title: find(li(2), ".wb-task-title").textContent, mediaDetached: detached.get(held.media) || 0, reviewDetached: detached.get(held.review) || 0 };

// 3. the review itself changes (one word) and is drawn again: its place is kept as well
panel.scrollTop = 4000; touched = 0;
const changed = clone(script.view); changed.revision += 1; changed.words[60].text = "changed"; script.view = changed;
tab.update(data(5, [task(1, "media:@RID@", { title: "Edit the recording" }), task(2, "plain", { title: "Renamed" }), task(3, "other", { state: "done" })])); await settle();
out.review = { top: panel.scrollTop, touched: touched > 0, word: find(tab.el, '[data-index="60"]').textContent.includes("changed"), same: same() };
held.words = find(tab.el, ".wb-rev-transcript");      // the words were drawn again, as they had to be

// 4. a row opened by the person is drawn without leaving the panel where it was
panel.scrollTop = 4000;
find(tab.el, "[data-key=toggle-2]").click(); await settle();
out.toggled = { top: panel.scrollTop, expanded: find(tab.el, "[data-key=toggle-2]").attrs["aria-expanded"], same: same() };
console.log(JSON.stringify(out));
process.exit(0);
"""


@needs_node
def test_every_update_of_the_page_leaves_a_scrolled_panel_where_it_was_and_the_row_of_the_review_keeps_its_nodes(tmp_path):
    got = run(tmp_path, HOLDS)
    assert got["opened"] == {"review": True, "words": True}
    all_same = {"li1": True, "li2": True, "media": True, "review": True, "words": True, "group": True}
    assert got["quiet"] == {"top": 4000, "touched": 0, "same": all_same}, "a store change that changed nothing shown touches no node"
    assert got["shown"]["top"] == 4000 and got["shown"]["touched"] is True and got["shown"]["title"] == "Renamed"
    assert got["shown"]["same"] == all_same, "the rows, the group and the review are the same nodes after a change elsewhere"
    assert got["shown"]["mediaDetached"] == 0 and got["shown"]["reviewDetached"] == 0, "the review and the video are never taken out of the row, so a video keeps playing"
    assert got["review"]["top"] == 4000 and got["review"]["touched"] is True and got["review"]["word"] is True and got["review"]["same"] == {**all_same, "words": False}, "only the words the review draws again are new nodes"
    assert got["toggled"] == {"top": 4000, "expanded": "true", "same": all_same}


KEEP = r"""
import { fill, h, keepScroll, sync } from "@JS@/dom.js";
const out = {};
const box = h("div", {});
const a = h("p", { text: "a" }), b = h("p", { text: "b" }), c = h("p", { text: "c" });
fill(box, a, b, c);
let moves = 0;
const { insertBefore, remove } = FakeNode.prototype;
FakeNode.prototype.insertBefore = function (n, before) { moves += 1; return insertBefore.call(this, n, before); };
FakeNode.prototype.remove = function () { moves += 1; return remove.call(this); };
sync(box, a, b, c);
out.same = { moves, order: box.children.map((n) => n.textContent) };
const d = h("p", { text: "d" });
moves = 0; sync(box, a, d, c);                       // b out, d in: a and c are not taken out
out.swap = { moves, order: box.children.map((n) => n.textContent), a: a.parent === box, c: c.parent === box };
moves = 0; sync(box, [c, [a]], null, false, undefined, "t");   // order changes, nested lists and text are accepted
out.order = box.children.map((n) => n.textContent);
sync(box);
out.empty = box.children.length;

// keepScroll puts back every scrolled ancestor, and leaves an unscrolled one alone
const outer = new FakeNode("div"), inner = new FakeNode("div"), leaf = new FakeNode("div");
outer.scrollTop = 0; inner.scrollTop = 120;
outer.append(inner); inner.append(leaf);
const result = keepScroll(leaf, () => { inner.scrollTop = 0; outer.scrollTop = 7; return "drawn"; });
out.scroll = { inner: inner.scrollTop, outer: outer.scrollTop, result };
const lone = new FakeNode("div");
out.lone = keepScroll(lone, () => 5);
console.log(JSON.stringify(out));
process.exit(0);
"""


@needs_node
def test_sync_keeps_the_children_that_stay_in_place_and_keepscroll_puts_a_scrolled_ancestor_back(tmp_path):
    script = "import { FakeNode } from \"@FAKE@\";\nimport { setToken } from \"@JS@/token.js\";\n" + KEEP
    got = run_node(tmp_path, script)
    assert got["same"] == {"moves": 0, "order": ["a", "b", "c"]}, "the same children in the same order: nothing is moved"
    assert got["swap"] == {"moves": 2, "order": ["a", "d", "c"], "a": True, "c": True}, "one removed and one inserted, the others untouched"
    assert got["order"] == ["c", "a", "t"] and got["empty"] == 0
    assert got["scroll"] == {"inner": 120, "outer": 7, "result": "drawn"}, "an ancestor that was scrolled is put back; one that was not is left to the redraw"
    assert got["lone"] == 5


def test_the_one_place_that_redraws_the_review_and_the_row_use_the_two_helpers():
    for name, helpers in (("floor/tasks-tab.js", ("keepScroll", "sync")), ("floor/captions-view.js", ("keepScroll",)), ("floor/video-card.js", ("keepScroll",))):
        code = (JS / name).read_text(encoding="utf-8")
        for helper in helpers:
            assert f"{helper}(" in code and helper in code.split("dom.js")[0].splitlines()[-1], f"{name} uses {helper}"
