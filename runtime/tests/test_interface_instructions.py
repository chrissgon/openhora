"""The page's part of the project's standing instructions (package INSTRUCTIONS): the client's three calls, the Instructions section of the Building (the text,
the count against the cap, the short hash, Save sending the text with the hash it read, the refusal shown as it was returned, the policy), and the Conversation's
"Add to instructions" for a live proposal. Run with Node over the real modules, a fake document and a stand-in client. No browser, no service, no model.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interface_instructions.py
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
await api.instructions("abc");
await api.instructionsSet("abc", "Keep it short.\nIn Portuguese.", "none");
await api.instructionsSet("abc", "", "h".repeat(64));
await api.instructionsAdd("abc", "Never name a competitor.", "h".repeat(64));
console.log(JSON.stringify(seen));
"""


@needs_node
def test_the_client_has_one_call_for_reading_setting_and_adding(tmp_path):
    got = run_node(tmp_path, API)
    base = "/api/v1/projects/abc/instructions"
    assert got[0] == ["GET", base, None]
    assert got[1] == ["POST", base, {"text": "Keep it short.\nIn Portuguese.", "base_sha256": "none"}]
    assert got[2] == ["POST", base, {"text": "", "base_sha256": "h" * 64}]
    assert got[3] == ["POST", base + "/add", {"line": "Never name a competitor.", "base_sha256": "h" * 64}]


def test_the_service_has_a_route_for_each_of_the_three_and_the_writes_are_rows_the_page_may_call():
    for method, path, op in (("GET", "/api/v1/projects/abcdef012345/instructions", "instructions"),
                             ("POST", "/api/v1/projects/abcdef012345/instructions", "instructions-set"),
                             ("POST", "/api/v1/projects/abcdef012345/instructions/add", "instructions-add")):
        found = service.match(method, path)
        assert found is not None and found[0]["op"] == op, (method, path)
    assert "page" in operations.by_name("instructions-set")["channels"] and "mcp" not in operations.by_name("instructions-add")["channels"]


SECTION = r"""
import { byClass, click, textOf } from "@FAKE@";
import { createInstructions, countOf, countWords, baseOf, HEAD, LEAD } from "@JS@/views/lobby-instructions.js";
const settle = async () => { for (let i = 0; i < 10; i++) await new Promise((r) => setTimeout(r, 0)); };
const tag = (root, name) => [...root.walk()].filter((n) => n.tagName === name.toUpperCase());
const labelled = (root, text) => tag(root, "button").find((b) => textOf(b) === text);
const type = (node, value) => { node.value = value; (node.listeners.input || []).forEach((fn) => fn({ target: node })); };

const SHA = "ab".repeat(32);
let file = { path: "docs/workbench/instructions.md", present: true, sha256: SHA, characters: 31, cap: 4000, problem: null, text: "Write every post in Portuguese." };
const calls = [];
let refuse = null;
const api = {
  instructions: async () => file,
  instructionsSet: async (p, text, base) => {
    calls.push(["set", p, text, base]);
    if (refuse) throw Object.assign(new Error(refuse), { name: "ApiError", status: 409 });
    file = { ...file, text, sha256: "cd".repeat(32), characters: text.length };
  },
};
let policy = null;
let refreshed = 0;
const section = createInstructions({ api, project: "p", entry: () => policy, refresh: async () => { refreshed += 1; } });
const out = {};
out.pure = [countOf("a\r\nb"), countOf("é😀"), countOf(""), countWords(31, 4000, SHA), countWords(0, 4000, null), baseOf(file), baseOf({ sha256: null }), baseOf(null), HEAD, LEAD.startsWith("Every model run")];
out.hiddenAtStart = section.el.hidden;
section.update({}, true);
await settle();
const field = tag(section.el, "textarea")[0];
const count = byClass(section.el, "wb-in-count")[0];
out.drawn = { hidden: section.el.hidden, value: field.value, readOnly: field.readOnly, count: textOf(count), buttons: tag(section.el, "button").map(textOf) };
// typing keeps the draft; Save sends the whole text with the hash of the file that was read
type(field, "Write every post in Portuguese.\nNever name a competitor.");
out.typed = textOf(count);
click(labelled(section.el, "Save the instructions")); await settle();
out.saved = { calls: calls.slice(), refreshed, value: field.value, count: textOf(count), error: byClass(section.el, "wb-form-error")[0].children.length };
// a refusal is shown as returned and the text stays in the field
refuse = "docs/workbench/instructions.md changed since you read it (its sha256 is now " + "ee".repeat(32) + ", not " + "cd".repeat(32) + "): read it again and repeat the change; nothing was written";
type(field, "A draft that will be refused.");
click(labelled(section.el, "Save the instructions")); await settle();
out.refused = { text: textOf(byClass(section.el, "wb-form-error")[0]), value: field.value, calls: calls.length };
refuse = null;
// the file changed by hand while the person typed: a line says so, and the draft is kept until the person reloads it
file = { ...file, text: "Changed by hand.", sha256: "ff".repeat(32), characters: 16 };
click(labelled(section.el, "Reload the file")); await settle();
out.reloaded = { value: field.value, count: textOf(count) };
// a problem of the file is shown whole, as the service gave it
file = { ...file, problem: "the project's instructions are too long (4,500 of 4,000 characters): shorten or fix docs/workbench/instructions.md", characters: 4500 };
section.update({}, true);
await (async () => { click(labelled(section.el, "Reload the file")); await settle(); })();
const problem = byClass(section.el, "wb-in-problem")[0];
out.problem = { hidden: problem.hidden, text: textOf(problem) };
// a project with no file: the field is empty, `none` is the base, and the line says so
file = { path: "docs/workbench/instructions.md", present: false, sha256: null, characters: 0, cap: 4000, problem: null, text: "" };
click(labelled(section.el, "Reload the file")); await settle();
type(field, "First rule.");
click(labelled(section.el, "Save the instructions")); await settle();
out.first = { count: calls[calls.length - 1], line: textOf(count) };
// the policy: with no group the field is read-only and there is no button, only the terminal's command
policy = { permissions: { allowed: ["status"] } };
section.update({}, true);
out.withheld = { readOnly: field.readOnly, buttons: tag(section.el, "button").map(textOf), line: textOf(tag(section.el, "p").filter((p) => (p.attrs.class || "").includes("wb-steps-line")).pop()) };
out.notShown = (() => { section.update(null, false); return section.el.hidden; })();
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_instructions_section_shows_the_file_counts_it_and_saves_it_with_the_hash_it_read(tmp_path):
    got = run_node(tmp_path, SECTION)
    assert got["pure"] == [3, 2, 0, "31 of 4000 characters · file " + "ab" * 6, "0 of 4000 characters · no file yet", "ab" * 32, "none", "none",
                           "Instructions", True]
    assert got["hiddenAtStart"] is True
    assert got["drawn"]["hidden"] is False and got["drawn"]["value"] == "Write every post in Portuguese." and got["drawn"]["readOnly"] is False
    assert got["drawn"]["count"] == "31 of 4000 characters · file " + "ab" * 6
    assert got["drawn"]["buttons"] == ["Save the instructions", "Reload the file"]
    assert got["typed"].startswith("56 of 4000 characters") and "ab" * 6 in got["typed"]
    assert got["saved"]["calls"] == [["set", "p", "Write every post in Portuguese.\nNever name a competitor.", "ab" * 32]]
    assert got["saved"]["refreshed"] == 1 and got["saved"]["error"] == 0 and got["saved"]["value"].endswith("competitor.")
    assert "cd" * 6 in got["saved"]["count"], "the hash shown is the new file's"
    assert got["refused"]["text"].endswith("nothing was written") and "ee" * 32 in got["refused"]["text"]
    assert got["refused"]["value"] == "A draft that will be refused." and got["refused"]["calls"] == 2
    assert got["reloaded"]["value"] == "Changed by hand." and "ff" * 6 in got["reloaded"]["count"]
    assert got["problem"] == {"hidden": False, "text": "the project's instructions are too long (4,500 of 4,000 characters): shorten or fix docs/workbench/instructions.md"}
    assert got["first"]["count"] == ["set", "p", "First rule.", "none"] and "First rule." not in got["first"]["line"]
    assert got["withheld"]["readOnly"] is True and got["withheld"]["buttons"] == []
    assert "terminal" in got["withheld"]["line"] and got["notShown"] is True


PROPOSAL = r"""
import { byClass, click, textOf } from "@FAKE@";
import { createProposal } from "@JS@/views/lobby-instructions.js";
const settle = async () => { for (let i = 0; i < 10; i++) await new Promise((r) => setTimeout(r, 0)); };
const tag = (root, name) => [...root.walk()].filter((n) => n.tagName === name.toUpperCase());
const labelled = (root, text) => tag(root, "button").find((b) => textOf(b) === text);
const calls = [];
let refuse = null;
let allowed = true;
let refreshed = 0;
const api = { instructionsAdd: async (p, line, base) => { calls.push([p, line, base]); if (refuse) throw Object.assign(new Error(refuse), { name: "ApiError", status: 409 }); } };
const box = createProposal({ api, project: "p", may: (op) => allowed && op === "instructions-add", refresh: async () => { refreshed += 1; } });
const hostile = "<img src=x onerror=alert(1)> **not bold**";
const PROPOSAL = { line: hostile, base_sha256: "none", command: "python3 /x/cli.py instructions-add --project /p --line 'x' --base-sha256 none", text: "ignored" };
const out = {};
out.start = box.el.hidden;
box.show(null); box.show({}); box.show({ line: "" });
out.nothing = box.el.hidden;
box.show(PROPOSAL);
out.shown = { hidden: box.el.hidden, line: textOf(byClass(box.el, "wb-in-line")[0]), buttons: tag(box.el, "button").map(textOf), elements: [...box.el.walk()].filter((n) => ["IMG", "SCRIPT"].includes(n.tagName)).length };
refuse = "docs/workbench/instructions.md changed since you read it: nothing was written";
click(labelled(box.el, "Add to instructions")); await settle();
out.refused = { error: textOf(byClass(box.el, "wb-form-error")[0]), calls: calls.length, still: tag(box.el, "button").map(textOf) };
refuse = null;
click(labelled(box.el, "Add to instructions")); await settle();
out.added = { calls: calls.slice(), said: textOf(tag(box.el, "p").find((p) => textOf(p) === "Added to the project's instructions.")), buttons: tag(box.el, "button").map(textOf), refreshed };
box.show(PROPOSAL);
click(labelled(box.el, "Not now"));
out.dismissed = box.el.hidden;
allowed = false;
box.show(PROPOSAL);
out.withheld = { buttons: tag(box.el, "button").map(textOf), command: textOf(tag(box.el, "p").filter((p) => textOf(p).startsWith("Adding it is done in the terminal"))[0]) };
console.log(JSON.stringify(out));
"""


@needs_node
def test_a_live_proposal_is_offered_with_add_to_instructions_and_nothing_else_is(tmp_path):
    got = run_node(tmp_path, PROPOSAL)
    assert got["start"] is True and got["nothing"] is True, "no proposal, no block, no button"
    assert got["shown"]["hidden"] is False and got["shown"]["buttons"] == ["Add to instructions", "Not now"]
    assert got["shown"]["line"] == "<img src=x onerror=alert(1)> **not bold**" and got["shown"]["elements"] == 0, "the line is text"
    assert got["refused"]["error"].endswith("nothing was written") and got["refused"]["calls"] == 1 and "Add to instructions" in got["refused"]["still"]
    assert got["added"]["calls"][1] == ["p", "<img src=x onerror=alert(1)> **not bold**", "none"], "the line and the hash are the service's, sent back as they came"
    assert got["added"]["buttons"] == [] and got["added"]["refreshed"] == 1
    assert got["dismissed"] is True
    assert got["withheld"]["buttons"] == ["Not now"] and "instructions-add" in got["withheld"]["command"]


def test_the_module_is_text_only_stores_nothing_and_loads_nothing_from_another_host():
    source = (INTERFACE / "js" / "views" / "lobby-instructions.js").read_text(encoding="utf-8")
    assert not re.search(r"innerHTML|outerHTML|insertAdjacentHTML|document\.write|localStorage|sessionStorage|\.style\b|https?://", source)
    assert "permissions.js" in source and re.search(r"\bmay\(", source)
    assert "instructionsSet" in source and "instructionsAdd" in source


DEMO_WORLD = r"""
import { createWorld } from "@DEMO@/world.js";
const timers = [];
const world = createWorld({ now: () => Date.UTC(2026, 9, 11, 12, 0, 0), later: (fn, ms) => timers.push([fn, ms]) || timers.length, cancelLater: () => {} });
const P = "3f9a1c07d2b4";
const read = await world.handle("GET", `/api/v1/projects/${P}/instructions`);
const wrote = await world.handle("POST", `/api/v1/projects/${P}/instructions`, new URLSearchParams(), { text: "x", base_sha256: "none" });
const added = await world.handle("POST", `/api/v1/projects/${P}/instructions/add`, new URLSearchParams(), { line: "x", base_sha256: "none" });
console.log(JSON.stringify({ read, wrote, added }));
"""


@needs_node
def test_the_demo_answers_the_read_with_the_keys_of_the_operation_and_refuses_the_writes_as_not_part_of_it(tmp_path):
    got = run_node(tmp_path, DEMO_WORLD.replace("@DEMO@", (INTERFACE / "demo").as_uri()))
    assert got["read"]["status"] == 200 and set(got["read"]["body"]) == {"path", "present", "sha256", "characters", "cap", "problem", "text"}
    assert got["read"]["body"]["present"] is False and got["read"]["body"]["text"] == ""
    for key in ("wrote", "added"):
        assert got[key]["status"] != 200 and "not part of the demo" in got[key]["body"]["message"]
