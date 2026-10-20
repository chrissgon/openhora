"""The page's part of the files people send through a messaging app (package ATT-1): the client's three calls, the service's three routes, the section of the
Building that lists the held files with what each would become, "Add as a source" and "Discard", the sentence of a refusal shown as it came, the policy, and the
demo's answers. Run with Node over the real modules, a fake document and a stand-in client. No browser, no service, no model. Every name below is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interface_attachments.py
"""
from __future__ import annotations

import re

import standin_tree as st
from test_interface_lobby import INTERFACE, needs_node, run_node  # noqa: F401  (the Node runner and the fake document the Lobby's tests use)

service = st.load("service")
operations = st.load("operations")

API = r"""
import { setToken } from "@JS@/token.js";

const seen = [];
globalThis.fetch = async (url, init) => { seen.push([init.method, url, init.body ? JSON.parse(init.body) : null]); return { ok: true, status: 200, json: async () => ({}) }; };
setToken("t".repeat(40));
const api = await import("@JS@/api.js");
await api.attachments("abc");
await api.attachmentAdd("abc", 7);
await api.attachmentDiscard("abc", 8);
console.log(JSON.stringify(seen));
"""


@needs_node
def test_the_client_has_one_call_for_reading_adding_and_discarding(tmp_path):
    got = run_node(tmp_path, API)
    base = "/api/v1/projects/abc/attachments"
    assert got[0] == ["GET", base, None]
    assert got[1][:2] == ["POST", base + "/7/add"] and got[2][:2] == ["POST", base + "/8/discard"]


def test_the_service_has_a_route_for_each_and_the_rows_are_the_pages_to_call_and_never_the_mcp_modes():
    for method, path, op in (("GET", "/api/v1/projects/abcdef012345/attachments", "attachments"),
                             ("POST", "/api/v1/projects/abcdef012345/attachments/7/add", "attachment-add"),
                             ("POST", "/api/v1/projects/abcdef012345/attachments/7/discard", "attachment-discard")):
        found = service.match(method, path)
        assert found is not None and found[0]["op"] == op, (method, path)
    assert service.match("POST", "/api/v1/projects/abcdef012345/attachments/x/add") is None
    assert service.match("POST", "/api/v1/projects/abcdef012345/attachments/hold") is None, "the hold is the messaging bridge's call alone"
    for name in ("attachments", "attachment-add", "attachment-discard"):
        row = operations.by_name(name)
        assert "page" in row["channels"] and "mcp" not in row["channels"], name


SECTION = r"""
import { byClass, click, textOf } from "@FAKE@";
import { createAttachments, sizeWords, fromWords, becomesWords, decidedWords, HEAD, LEAD } from "@JS@/views/lobby-attachments.js";
const settle = async () => { for (let i = 0; i < 10; i++) await new Promise((r) => setTimeout(r, 0)); };
const tag = (root, name) => [...root.walk()].filter((n) => n.tagName === name.toUpperCase());
const labelled = (root, text) => tag(root, "button").find((b) => textOf(b) === text);

const held = (id, extra = {}) => ({ id, platform: "telegram", profile: "staff", name: `Q3 plan ${id}.pdf`, kind: "pdf", bytes: 3584, target: `q3-plan-${id}`, label: "import",
  status: "held", created_at: "2026-10-16T10:00:00.000000Z", expires_at: "2026-10-23T10:00:00.000000Z", ...extra });
let state = { held: [held(1), held(2, { label: "refresh", target: "board-notes", profile: null })], recent: [{ id: 5, name: "x.csv", status: "discarded" },
  { id: 4, name: "bad.pdf", status: "refused", code: "credential" }, { id: 3, name: "old.docx", status: "added", source_id: "old", version: 2 }], today: { files: 4, bytes: 9000 }, limits: {} };
const calls = [];
let refuse = null;
const api = {
  attachments: async () => state,
  attachmentAdd: async (p, id) => {
    calls.push(["add", p, id]);
    if (refuse) throw Object.assign(new Error(refuse), { name: "ApiError", status: 409 });
    state = { ...state, held: state.held.filter((r) => r.id !== id) };
    return { added: true, reply: "Added Q3 plan 1.pdf as `q3-plan-1`, version 1." };
  },
  attachmentDiscard: async (p, id) => { calls.push(["discard", p, id]); state = { ...state, held: state.held.filter((r) => r.id !== id) }; return { discarded: true, reply: "Discarded." }; },
};
let policy = null;
let refreshed = 0;
const section = createAttachments({ api, project: "p", entry: () => policy, refresh: async () => { refreshed += 1; } });
const out = {};
out.pure = [sizeWords(0), sizeWords(812), sizeWords(3584), sizeWords(12 * 1024 * 1024), sizeWords(-1), sizeWords("x"), fromWords({ platform: "telegram", profile: "staff" }),
  fromWords({ platform: "discord", profile: "default" }), fromWords(null), becomesWords({ target: "survey", label: "import" }), becomesWords({ target: "survey", label: "refresh" }),
  decidedWords({ status: "added", source_id: "old", version: 2 }), decidedWords({ status: "refused", code: "credential" }), decidedWords({ status: "expired" }), HEAD, LEAD.includes("not read by any task")];
out.hiddenAtStart = section.el.hidden;
section.update({}, true, 1);
await settle();
const items = byClass(section.el, "wb-at-item");
out.drawn = { hidden: section.el.hidden, count: items.length, first: textOf(items[0]), second: textOf(items[1]), buttons: tag(items[0], "button").map(textOf),
  latest: byClass(section.el, "wb-at-done").map(textOf) };
click(tag(items[0], "button")[0]); await settle();
out.added = { calls: calls.slice(), note: textOf(byClass(section.el, "wb-at-note")[0]), left: byClass(section.el, "wb-at-item").length, refreshed };
refuse = "Q3 plan 2.pdf was not added and was deleted: it holds what looks like a credential.";
click(labelled(section.el, "Add as a source")); await settle();
out.refused = { text: textOf(byClass(section.el, "wb-form-error")[0]), calls: calls.length };
refuse = null;
click(labelled(section.el, "Discard")); await settle();
out.discarded = { calls: calls.slice(-1), left: byClass(section.el, "wb-at-item").length, error: byClass(section.el, "wb-form-error")[0].children.length };
// nothing held and nothing decided: the section is not drawn
state = { held: [], recent: [], today: { files: 0, bytes: 0 }, limits: {} };
const fresh = createAttachments({ api, project: "p", entry: () => policy, refresh: async () => {} });
fresh.update({}, true, 1); await settle();
out.empty = fresh.el.hidden;
// a name that is markup is text, and a row never shows who sent it
state = { held: [held(9, { name: "<img src=x onerror=alert(1)>.pdf", sender: "4242424242" })], recent: [], today: { files: 1, bytes: 1 }, limits: {} };
section.update({}, true, 2); await settle();
out.hostile = { text: textOf(byClass(section.el, "wb-at-item")[0]), elements: [...section.el.walk()].filter((n) => ["IMG", "SCRIPT"].includes(n.tagName)).length };
// a save-only image (ATT-3) has no source to become: no "Add as a source", and the line says it is never added
state = { held: [held(10, { name: "photo.jpg", kind: "jpeg", save_only: true, target: null, label: null })], recent: [], today: { files: 1, bytes: 1 }, limits: {} };
section.update({}, true, 4); await settle();
const image = byClass(section.el, "wb-at-item")[0];
out.image = { buttons: tag(image, "button").map(textOf), text: textOf(image), words: [becomesWords({ save_only: true, target: "x" }), becomesWords({ target: null }), becomesWords(null)] };
// the policy: with no group there are no buttons and no read
policy = { permissions: { allowed: ["status"] } };
section.update({}, true, 3); await settle();
out.withheld = { buttons: tag(section.el, "button").map(textOf) };
out.notShown = (() => { section.update(null, false); return section.el.hidden; })();
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_section_lists_the_held_files_adds_or_discards_one_and_shows_a_refusal_as_it_came(tmp_path):
    got = run_node(tmp_path, SECTION)
    assert got["pure"] == ["0 bytes", "812 bytes", "3.5 KiB", "12.0 MiB", "", "", "telegram, profile staff", "discord", "a messaging app",
                           "the new source survey", "a new version of the source survey", "added as old, version 2", "refused (credential)", "expired",
                           "Files from messaging apps", True]
    assert got["hiddenAtStart"] is True
    assert got["drawn"]["hidden"] is False and got["drawn"]["count"] == 2 and got["drawn"]["buttons"] == ["Add as a source", "Discard"]
    assert got["drawn"]["first"].startswith("Q3 plan 1.pdf (pdf, 3.5 KiB)") and "From telegram, profile staff. Adding it makes the new source q3-plan-1." in got["drawn"]["first"]
    assert "It is deleted on 2026-10-23 if you do not answer." in got["drawn"]["first"]
    assert "Adding it makes a new version of the source board-notes." in got["drawn"]["second"] and "From telegram." in got["drawn"]["second"]
    assert got["drawn"]["latest"] == ["x.csv: discarded", "bad.pdf: refused (credential)", "old.docx: added as old, version 2"]
    assert got["added"]["calls"] == [["add", "p", 1]] and got["added"]["note"].startswith("Added Q3 plan 1.pdf") and got["added"]["left"] == 1 and got["added"]["refreshed"] == 1
    assert got["refused"]["text"].endswith("it holds what looks like a credential.") and got["refused"]["calls"] == 2
    assert got["discarded"]["calls"] == [["discard", "p", 2]] and got["discarded"]["left"] == 0 and got["discarded"]["error"] == 0
    assert got["empty"] is True
    assert got["hostile"]["text"].startswith("<img src=x onerror=alert(1)>.pdf (pdf") and got["hostile"]["elements"] == 0 and "4242424242" not in got["hostile"]["text"]
    assert got["image"]["buttons"] == ["Discard"] and "never added as a source" in got["image"]["text"] and "null" not in got["image"]["text"] and got["image"]["words"] == ["", "", ""]
    assert got["withheld"]["buttons"] == [] and got["notShown"] is True


def test_the_module_is_text_only_stores_nothing_and_loads_nothing_from_another_host():
    source = (INTERFACE / "js" / "views" / "lobby-attachments.js").read_text(encoding="utf-8")
    assert not re.search(r"innerHTML|outerHTML|insertAdjacentHTML|document\.write|localStorage|sessionStorage|\.style\b|https?://", source)
    assert "permissions.js" in source and re.search(r"\bmay\(", source)
    assert "attachmentAdd" in source and "attachmentDiscard" in source


def test_the_demo_has_no_messaging_app_so_it_lists_nothing_and_refuses_the_writes():
    reads = (INTERFACE / "demo" / "world-reads.js").read_text(encoding="utf-8")
    world = (INTERFACE / "demo" / "world.js").read_text(encoding="utf-8")
    assert "export function attachments()" in reads and 'case "attachments": return get(reads.attachments());' in world
    assert 'parts[0] === "attachments") throw notInDemo(' in world
