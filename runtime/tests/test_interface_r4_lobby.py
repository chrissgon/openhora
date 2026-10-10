"""Tests of the Lobby screen that look at its presentation (R4-S): the request line, the conversation's blocks, the composer, the tab modules' classes against
the stylesheet. A package for the Lobby edits this file and `test_interface_lobby.py`, `interface/css/lobby.css` and `interface/js/views/lobby*.js`; the tests of the
shared files (`test_interface_files.py`: routes, writes, text as text) stay where they are. The tests below were moved here from the shared files with their names and
their assertions unchanged; each reads what it needs through the module it came from.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interface_r4_lobby.py
"""
from __future__ import annotations

import re

from interface_css import interface_css
from test_interface_adj_b1 import REQUEST_ROUTE, ROUTE_BLOCK, ROUTE_VIEW, run_view
from test_interface_adjustments import COMPOSER, run_node
from test_interface_cards_fields import LINE, LOBBY, VIEW_A4, css_rules, run_node as run_node_cards_fields
from test_interface_files import INTERFACE, LOBBY_TAB_FILES
from test_interface_floor import needs_node


# --- moved from test_interface_files.py ------------------------------------------------------------------------------------------


def test_the_lobby_draws_a_plan_card_in_one_place_and_a_line_in_the_other():
    request = (INTERFACE / "js" / "views" / "lobby-request.js").read_text(encoding="utf-8")
    assert 'item.kind === "plan" && viaMessage' in request, "a plan under a message that names its request is the plan card; otherwise a line points at the Inbox"
    thread = (INTERFACE / "js" / "views" / "lobby-thread.js").read_text(encoding="utf-8")
    assert "blockFor(request, true)" in thread and "blockFor(request, false)" in thread, "a block under a message and a trailing one are told apart"
    lobby = (INTERFACE / "js" / "views" / "lobby.js").read_text(encoding="utf-8")
    assert "inboxParts(status, messages)" in lobby and 'router.lobbyHash(project, "inbox", result.pending_id)' in lobby, \
        "a request made from the form opens its plan in the Inbox when its route ends"


def test_every_class_the_lobbys_tab_modules_build_is_styled_and_the_tab_files_are_files_of_the_page():
    css = interface_css()
    missing = {}
    for name in LOBBY_TAB_FILES:
        assert (INTERFACE / "js" / name).is_file()
        text = (INTERFACE / "js" / name).read_text(encoding="utf-8")
        for cls in set(re.findall(r"\bwb-[a-z0-9]+(?:-[a-z0-9]+)*", text)):
            if not re.search(re.escape("." + cls) + r"(?![A-Za-z0-9_-])", css):
                missing.setdefault(cls, []).append(name)
    lobby = (INTERFACE / "js" / "views" / "lobby.js").read_text(encoding="utf-8")
    for cls in ("wb-lobby-scroll",):
        assert re.search(re.escape("." + cls) + r"(?![A-Za-z0-9_-])", css) and cls in lobby
    assert not missing, f"classes the Lobby's tab modules build that the stylesheets never name: {missing}"
    assert "LATER" not in lobby and "comes with the Floor package" not in lobby, "no placeholder is left for the three tabs"

# --- moved from test_interface_adj_b1.py -----------------------------------------------------------------------------------------


@needs_node
def test_the_request_route_opens_the_conversation_scrolls_to_the_block_and_focuses_its_title_once(tmp_path):
    got = run_view(tmp_path, REQUEST_ROUTE)
    assert got["ids"] == [True, True], "C-2: each request block has an id"
    assert got["focus"] == [True, False], "the title of request 3 has the focus"
    assert got["scrolled"][-1] == "wb-request-3", "the Lobby scrolled to the block"
    assert got["title"] == "Request #3: Docs page"
    assert got["rebuilt"] == ["Request #3: Docs page, renamed", True], "a block drawn again keeps the focus on its title"
    assert got["again"] == [True, 1], "a reload on the same route neither scrolls nor focuses again"
    assert got["second"] == [True, "wb-request-2"], "another request route follows"
    assert got["missing"] is True and got["plain"] is True, "no such request, or no request: the focus is left alone"


@needs_node
def test_the_request_line_that_waits_for_its_route_carries_a_flow_select_with_the_planning_agent_first(tmp_path):
    got = run_node(tmp_path, ROUTE_BLOCK)
    assert got["options"] == [["", "Let the planning agent route it"], ["design", "Design"], ["brand", "Brand of a product"], ["plain", "plain"]], \
        "the flows read once, labelled by their titles; one that failed to load is not offered"
    assert got["label"] == ["Flow for request 20", "Route request 20"] and got["order"] == ["wb-route-flow", "wb-route-button"], "the select stands beside the button"
    assert got["routed"] == [[20, ""], [20, "brand"]], "'Route it' sends the planning agent's route with no flow, or the chosen flow"
    assert got["restored"] == "design" and got["kept"] == ["brand"], "a block rebuilt by a reload gets the choice back, and tells the thread what was chosen"
    assert got["none"] == [True, True, True], "no flow to choose: no select"
    assert got["remembered"] is True and got["rememberedRoute"] == [20, "design"], "a flow chosen in the form this session is remembered: no select, the route sends it"
    assert got["routing"] is True
    assert got["notWaiting"] is True


@needs_node
def test_route_it_after_a_reload_sends_the_chosen_flow_or_none_and_never_creates_or_edits_a_request(tmp_path):
    got = run_view(tmp_path, ROUTE_VIEW)
    assert got["selectnull"] == ["", "design"] and got["selectdesign"] == ["", "design"], "the flows were read once and the select is on the request line"
    assert got["sentnull"] == [{}], "no flow chosen: `route` with no flow, the planning agent routes it"
    assert got["sentdesign"] == [{"flow": "design"}], "a flow chosen: `route` with the flow"
    assert got["textnull"] == 0 and got["textdesign"] == 0, "the page never writes the request again: its text is not changed"

# --- moved from test_interface_adjustments.py ------------------------------------------------------------------------------------


@needs_node
def test_the_composer_says_a_run_is_in_progress_a_queued_line_shows_the_word_and_the_form_sends_after(tmp_path):
    got = run_node(tmp_path, COMPOSER)
    assert got["idle"] == {"hidden": True}
    r = got["running"]
    assert r["hidden"] is False and r["role"] == "status" and r["send"] is False, "A-23: the line shows in place and Send stays on"
    assert r["text"].startswith("A run is in progress: your line will be routed when it ends; a question about the state is answered now.")
    assert r["link"] == ["Task #12 Build the page", "#/p/x/floor/engineering", False]
    assert got["notAccepted"] == {"hidden": True, "send": True}, "a project that is not accepted says that, not a run"
    assert got["after"] == {"hidden": True}
    assert got["hints"] == ["Type / to list the commands."], "R-45: the one hint; the second (`/new --after`) is gone"
    m = got["model"]
    assert m["meta"] == ["You · 1 h ago · queued", "You · 1 h ago", "You · queued"] and m["name"] == "You, 1 hour ago, queued"
    assert m["has"] == [True, False, False]
    assert m["readAfter"] == [4, 8, 0, 4], "a queued line is read again: the read asks above the message before the oldest queued one"
    assert m["running"] == [{"id": 2, "title": "Build", "agent": "engineering"}, None, None]
    assert m["hash"] == ["#/p/p/floor/engineering", "#/p/p/lobby", "#/p/p/lobby"]
    assert got["queued"] == {"meta": "You · just now · queued", "cls": "wb-msg is-user is-queued", "name": "You, just now, queued", "bubble": "Como estamos?"}, \
        "A-23: the line shows as typed with the word queued until its reply arrives"
    assert got["answered"] == {"meta": "You · just now", "cls": "wb-msg is-user", "same": True, "count": 2}, "the reply arrived: the word goes, the message node stays"
    assert got["form"]["sent"] == [{"text": "Landing page", "flow": "", "title": ""}, {"text": "Landing page", "flow": "", "title": "", "after": "3"}], "after is sent only when it was typed"
    assert got["form"]["label"] == "After request (optional)" and got["form"]["tag"] == "SELECT", "R-46: a select of the open requests"
    assert got["afterNumber"] == [{"value": 3}, {"value": 4}, {}, {"invalid": True}, {"invalid": True}, {"invalid": True}, {"value": 5}, {"invalid": True}, {"invalid": True}], \
        "an empty field is no after; a word, zero, a negative, a decimal or a huge number is refused"
    assert got["createCalls"] == [["request", "p1", "x", 3, None], ["route", "p1", 9, None], ["request", "p1", "y", None, "T"], ["route", "p1", 9, "design"]]
    assert got["queuedNotice"] == {"tone": "info", "title": "Recorded", "text": "A run is in progress. The request is recorded and will be routed when the run ends."}

# --- moved from test_interface_cards_fields.py -----------------------------------------------------------------------------------


def test_the_request_title_is_one_ellipsised_line():
    """A-1: the title took a narrow column and wrapped over many lines; it is now one line cut with an ellipsis."""
    rule = next(d for s, d in css_rules() if re.search(r"\.wb-lobby-request-title(?![\w-])", s) and "text-overflow" in d)
    assert rule.get("text-overflow") == "ellipsis" and rule.get("white-space") == "nowrap" and rule.get("overflow") == "hidden"
    assert "overflow-wrap" not in rule or rule["overflow-wrap"] != "anywhere"
    full = [d for s, d in css_rules() if re.search(r"\.wb-lobby-request-full(?![\w-])", s)]
    assert full and full[0].get("white-space") == "pre-wrap", "the expanded text shows the whole text, line breaks kept"


@needs_node
def test_the_request_line_is_one_line_with_the_whole_text_on_a_tooltip_and_an_expand(tmp_path):
    got = run_node_cards_fields(tmp_path, LINE)
    assert got["order"] == ["number", "title", "state"], "R-47: number, title, state chip on one line; the actions are on the line under it"
    assert got["title"]["tag"] == "BUTTON" and got["title"]["type"] == "button", "the title is the control that toggles the full text"
    assert got["title"]["text"].startswith("Marlowe is the brand") and not got["title"]["text"].startswith("Request"), "the badge says the number: the visible text is the title alone"
    assert got["title"]["name"].startswith("Request #16: Marlowe is the brand"), "the accessible name keeps the number and the word"
    assert got["title"]["tip"].startswith("Request #16: Marlowe") and "A second paragraph" in got["title"]["tip"], "the tooltip holds the whole text of the request, not the title"
    assert got["fullBefore"]["hidden"] is True and got["fullBefore"]["after"] is True, "the full text is under the line, hidden until asked for"
    assert got["fullOpen"] == {"hidden": False, "expanded": "true", "text": "Marlowe is the brand of a small studio that makes calm, readable software for shops. It needs a name system, a voice, a logo brief and a launch plan that a weak model can follow without guessing, written as one request.\nA second paragraph that the title never holds."}
    assert got["fullClosed"] == {"hidden": True, "expanded": "false"}
    assert got["reopened"] == {"expanded": "true", "hidden": False} and got["toggles"] == [True, False], "the thread keeps the open ids and gives them back to a rebuilt block"


@needs_node
def test_the_title_is_the_requests_title_else_the_text_and_the_number_only_when_there_is_neither(tmp_path):
    got = run_node_cards_fields(tmp_path, LINE)
    assert got["fromTitle"] == "Add a sale page"
    assert got["planTitleIgnored"] == "Request #3", "the runtime puts the computed title in `title`: no second field is read"
    assert got["fromText"] == "Add a sale page with a banner", "the text's line breaks are spaces in the one-line title"
    assert got["fromNothing"] == "Request #3", "no title and no text: the number alone, never 'Request 3' twice"


@needs_node
def test_a_failed_route_leaves_its_notice_under_the_request_line_and_route_it_repeats_the_route(tmp_path):
    got = run_node_cards_fields(tmp_path, LINE)
    assert got["notice"]["present"] and got["notice"]["under"] and got["notice"]["role"] == "alert"
    assert got["notice"]["text"].startswith("Not routed yet") and 'Use "Route it" on its request line.' in got["notice"]["text"]
    assert got["routeAgain"] == [16]
    assert got["noNotice"] == 0, "a request whose route did not fail has no notice"


@needs_node
def test_after_create_request_a_refused_route_puts_its_notice_on_the_request_line_not_in_the_composer(tmp_path):
    got = run_node_cards_fields(tmp_path, VIEW_A4)
    assert len(got["afterCreate"]["inBlock"]) == 1 and got["afterCreate"]["inBlock"][0].startswith("Not routed yet")
    assert "outside the pack in scope" in got["afterCreate"]["inBlock"][0], "the operation's sentence is shown as it came"
    assert got["afterCreate"]["composer"] == [], "the composer's notice is for a turn that was not sent"
    assert got["routeButton"] == 1
    assert got["routeCalls"] == 1 and len(got["afterAgain"]["inBlock"]) == 1 and got["afterAgain"]["composer"] == []
    assert got["afterRouted"]["inBlock"] == [] and got["afterRouted"]["composer"] == [], "a route that started clears the notice"


@needs_node
def test_the_lobbys_close_goes_back_to_the_desk_from_a_row_a_direct_hash_or_a_sheet(tmp_path):
    got = run_node_cards_fields(tmp_path, LOBBY)
    p = "#/p/0123456789ab/lobby"
    assert got["deskClose"] == {"hash": f"{p}/desk", "errors": []} and got["deskFocus"] == "docs/notes/a.md"
    assert got["directClose"] == {"hash": f"{p}/desk", "errors": []}
    assert got["sheetClose"] == p, "a sheet of the room opens the document from the Conversation, and Close returns to the tab it was opened from"
    assert got["selectedClose"] == {"hash": f"{p}/inbox/8", "errors": []} and got["agentClose"] == {"hash": f"{p}/agent", "errors": []}


@needs_node
def test_the_lobbys_inbox_open_closes_back_to_the_inbox_and_the_focus_is_the_open_link_not_a_stale_row(tmp_path):
    got = run_node_cards_fields(tmp_path, LOBBY)
    p = "#/p/0123456789ab/lobby"
    assert got["inboxLink"] == f"{p}/desk/docs%2Fnotes%2Fa.md"
    assert got["inboxClose"] == {"hash": f"{p}/inbox", "errors": []}
    assert got["inboxFocus"]["sameLink"] is True, got["inboxFocus"]
    assert got["phoneOpen"] is True and got["phoneClose"] == f"{p}/inbox"


# === R4-A5: the Lobby as `lobby.html` draws it (R-42 to R-48, P-6) ==================================================================
# Tests of the round's migration, written for the new behaviour: the DOM of the regions the package changes, the model's pure functions, the stylesheet's facts.
# They run under the fake document of the Floor's tests with the Lobby's extras (`run_view_node`), no browser, no model and no service.

import json  # noqa: E402

from test_interface_lobby import CARDS, JS, VIEWS, run_view_node  # noqa: E402

R4_HEAD = r"""
import { FakeNode, find, all, settle } from "@FAKE@";
const FakeText = document.createTextNode("").constructor;
globalThis.Node = class { static [Symbol.hasInstance](x) { return x instanceof FakeNode || x instanceof FakeText; } };   // a text node is a Node, as in the browser
const byClass = (root, name) => [...root.walk()].filter((n) => n.cls && n.cls().includes(name));
const textOf = (n) => n.textContent;
const click = (n) => (n.listeners.click || []).forEach((fn) => fn({ preventDefault() {}, stopPropagation() {}, target: n }));
const press = (n, init) => { let stopped = false; (n.listeners.keydown || []).forEach((fn) => fn({ preventDefault() { stopped = true; }, stopPropagation() {}, ...init })); return stopped; };
const typeInto = (n, value) => { n.value = value; (n.listeners.input || []).forEach((fn) => fn({ target: n })); };
const out = {};
"""

R4_MODEL = R4_HEAD + r"""
import * as m from "@JS@/views/lobby-model.js";
const reqs = [{ id: 9, title: "Autumn catalogue", state: "planned" }, { id: 4, title: "Old", state: "done" }, { id: 7, title: "Spring sale page", state: "running" },
  { id: 11, title: "Size guide", state: "requested" }, { id: 12, title: "Gone", state: "cancelled" }, { id: 13, title: "", state: "waiting", text: "Gift cards\nin three values" }];
out.after = m.afterOptions(reqs);
out.afterEmpty = [m.afterOptions(undefined), m.afterOptions([]).length];
const rows = [{ command: "/help", arguments: "", help: "list the commands" }, { command: "/release", arguments: "<id>", help: "release a delivery" }, { command: "/reject", arguments: "<id> [note]", help: "reject" },
  { command: "/retry", arguments: "<task id>", help: "retry" }, { command: "/status", arguments: "", help: "status" }];
out.match = { all: m.commandMatches(rows, "/").map((r) => r.command), re: m.commandMatches(rows, "/re").map((r) => r.command), exact: m.commandMatches(rows, "/help").map((r) => r.command),
  upper: m.commandMatches(rows, "/RE").length, none: m.commandMatches(rows, "/zzz"), plain: m.commandMatches(rows, "hello"), withArgs: m.commandMatches(rows, "/reject 3"), multiline: m.commandMatches(rows, "/\nx"),
  empty: m.commandMatches(rows, ""), unread: m.commandMatches(null, "/") };
out.fill = [m.commandFill(rows[0]), m.commandFill(rows[1])];
out.hint = m.HINT;
out.tabs = m.TABS.map((t) => t[1]);
out.tone = [m.requestLine({ id: 1, title: "x", state: "running" }, 0).tone, m.requestLine({ id: 1, title: "x", state: "requested" }, 0).tone, m.requestLine({ id: 1, title: "x", state: "failed" }, 0).tone];
const many = Array.from({ length: 70 }, (_, i) => ({ id: i + 1, title: "r", state: i % 3 === 0 ? "cancelled" : "planned", tasks: [] }));
const open = [{ id: 1, task_id: 2 }, { id: 2, task_id: 3 }];
const ids = m.inboxBodies(many, open);
out.inbox = { length: ids.length, first: ids.slice(0, 4), cap: m.MAX_INBOX_BODIES, cancelledIncluded: ids.includes(70) && ids.includes(1) === false || ids.includes(1), oldestLeft: ids.includes(3) };
out.inboxFew = m.inboxBodies([{ id: 5, state: "cancelled" }, { id: 2, state: "done" }, { id: 8, state: "planned" }], [{ id: 1, task_id: 2 }]);
out.inboxNone = [m.inboxBodies(undefined), m.inboxBodies([])];
console.log(JSON.stringify(out));
"""


def test_the_models_words_for_after_request_the_command_list_the_tabs_and_the_inbox_reads():
    got = run_view_node(Path_tmp(), R4_MODEL)
    assert got["after"][0] == {"value": "", "label": "None: it starts when it can"}, "R-46: the first option"
    assert [o["label"] for o in got["after"][1:]] == ["#7 Spring sale page · Running", "#9 Autumn catalogue · Planned", "#11 Size guide · Waiting for its route", "#13 Gift cards in three values · Waiting"], \
        "R-46: every request that is not final, by number, `#<n> <title> · <state>`; done and cancelled are not offered"
    assert [o["value"] for o in got["after"][1:]] == ["7", "9", "11", "13"]
    assert got["afterEmpty"] == [[{"value": "", "label": "None: it starts when it can"}], 1]
    assert got["match"]["all"] == ["/help", "/release", "/reject", "/retry", "/status"], "R-45: `/` lists every command in the service's order"
    assert got["match"]["re"] == ["/release", "/reject", "/retry"] and got["match"]["upper"] == 3 and got["match"]["exact"] == ["/help"]
    assert got["match"]["none"] == [] and got["match"]["plain"] == [] and got["match"]["withArgs"] == [] and got["match"]["multiline"] == [] and got["match"]["empty"] == [] and got["match"]["unread"] == [], \
        "the list is for one word that starts with / and nothing else"
    assert got["fill"] == ["/help", "/release "], "a command with arguments is filled with a space after it"
    assert got["hint"] == "Type / to list the commands."
    assert got["tabs"] == ["Conversation", "Inbox", "Tasks", "Desk", "Agent"], "R-43 (C-6)"
    assert got["tone"] == ["pui-theme pui-soft", "pui-muted pui-soft", "pui-error pui-soft"], "R-47, C-23: the request's chip takes the state's colour"
    assert got["inbox"]["length"] == 50 and got["inbox"]["cap"] == 50 and got["inbox"]["first"][:2] == [3, 2], \
        "P-6: the requests with a decision open first, then the newest, 50 at most; a cancelled request is read too"
    assert got["inbox"]["oldestLeft"] is True and got["inboxFew"] == [2, 8, 5], "with few requests every one is read: open first, then newest first"
    assert got["inboxNone"] == [[], []]


def Path_tmp():
    import tempfile
    from pathlib import Path
    return Path(tempfile.mkdtemp(prefix="r4-lobby-"))


R4_PIECES = R4_HEAD + r"""
import { createTabs } from "@JS@/views/lobby-tabs.js";
import { createForm } from "@JS@/views/lobby-form.js";
import { createComposer } from "@JS@/views/lobby-composer.js";
import { createBlock } from "@JS@/views/lobby-request.js";
import { createPlanCard } from "@JS@/cards/plan.js";

// the tabs (R-43): one list in a bar, Tasks before Desk, the count only on Inbox, hidden together
const tabs = createTabs();
tabs.set({ project: "aaaaaaaaaaaa", selected: "tasks", counts: { inbox: 2 } });
const tabButtons = all(tabs.el, "button");
out.tabs = { names: tabButtons.map((b) => b.attrs["aria-label"]), barHolds: tabs.bar.children[0] === tabs.el, barClass: tabs.bar.cls(), listClass: tabs.el.cls(), tabClass: tabButtons[0].cls(),
  selected: tabButtons.map((b) => b.cls().includes("is-selected")), count: byClass(tabs.el, "wb-lobby-tab-count").map((n) => [n.textContent, n.hidden]) };
tabs.setHidden(true);
out.tabsHidden = [tabs.bar.hidden, tabs.el.hidden];

// the form (R-44, R-46): hidden until opened, Back above the title, four fields in order, After request a select, the draft stays
let backs = 0;
const created = [];
const form = createForm({ onCreate: (v) => created.push(v), onBack: () => { backs += 1; } });
form.setFlows([{ flow: "design", title: "Design", tasks: 3 }]);
form.setRequests([{ id: 7, title: "Spring sale page", state: "running" }, { id: 9, title: "Autumn", state: "planned" }, { id: 3, title: "Done", state: "done" }]);
const kids = (n) => n.children.map((c) => c.tagName + "." + (c.attrs.class || "").split(" ")[0]);
const labels = all(form.el, "label").map((l) => l.children[0].textContent);
const selects = all(form.el, "select");
out.form = { hiddenAtFirst: form.el.hidden, open: [form.isOpen()], root: form.el.cls(), head: kids(form.el), back: textOf(byClass(form.el, "wb-newreq-back")[0]), title: textOf(byClass(form.el, "wb-newreq-title")[0]), labels,
  after: selects[1].children.map((o) => [o.attrs.value, textOf(o)]), hint: byClass(form.el, "wb-hint")[0].textContent, create: byClass(form.el, "pui-solid").map(textOf), details: all(form.el, "details").length, dialog: all(form.el, "dialog").length };
form.open(true);
out.form.shown = [form.el.hidden, form.isOpen()];
click(byClass(form.el, "wb-newreq-back")[0]);
out.form.backs = backs;
const area = all(form.el, "textarea")[0];
area.value = "Add a size guide";
selects[1].value = "9";
(all(form.el, "form")[0].listeners.submit || []).forEach((fn) => fn({ preventDefault() {} }));
selects[1].value = "";
(all(form.el, "form")[0].listeners.submit || []).forEach((fn) => fn({ preventDefault() {} }));
out.created = created;
// a request that is no longer offered resets the choice to None; one still offered keeps it
selects[1].value = "7";
form.setRequests([{ id: 7, title: "Spring sale page", state: "running" }]);
out.keptChoice = selects[1].value;
form.setRequests([{ id: 9, title: "Autumn", state: "planned" }]);
out.droppedChoice = selects[1].value;
form.reset();
out.reset = [area.value, selects[1].value];

// the composer (R-44, R-45): Send first in the keyboard order, "New request" beside it, the one hint, the list over the field
const sent = [];
let asked = 0;
const composer = createComposer({ onSend: (t) => sent.push(t), onNew: () => { asked += 1; } });
const field = all(composer.el, "textarea")[0];
const buttons = all(composer.el, "button");
out.composer = { order: buttons.map(textOf), classes: buttons.map((b) => b.cls().filter((c) => c.startsWith("pui-") || c.startsWith("wb-")).join(" ")), hints: byClass(composer.el, "wb-lobby-hint").map(textOf),
  list: byClass(composer.el, "wb-slash").map((n) => [n.attrs.role, n.hidden, n.attrs["aria-label"]]), combobox: [field.attrs.role, field.attrs["aria-expanded"], field.attrs["aria-controls"], field.attrs["aria-autocomplete"]] };
click(buttons[1]);
out.asked = asked;
const commands = [{ command: "/help", arguments: "", help: "list the commands" }, { command: "/status", arguments: "", help: "requests, tasks and what waits for you" },
  { command: "/release", arguments: "<id>", help: "release a delivery (it stays a draft)" }, { command: "/reject", arguments: "<id> [note]", help: "reject a plan" }, { command: "/retry", arguments: "<task id>", help: "retry" }];
typeInto(field, "/");
out.beforeCommands = byClass(composer.el, "wb-slash")[0].hidden;
composer.setCommands(commands);
const rows = () => byClass(composer.el, "wb-slash-row");
const state = () => ({ hidden: byClass(composer.el, "wb-slash")[0].hidden, rows: rows().map((r) => [textOf(r.children[0]), textOf(r.children[1]), r.attrs["aria-selected"], r.attrs.role]),
  expanded: field.attrs["aria-expanded"], active: field.attrs["aria-activedescendant"] || null });
out.open = state();
out.openIds = rows().map((r) => r.attrs.id);
typeInto(field, "/re");
out.narrow = state();
out.down = [press(field, { key: "ArrowDown" }), state().rows.map((r) => r[2]), state().active];
out.wrap = [press(field, { key: "ArrowDown" }), press(field, { key: "ArrowDown" }), state().rows.map((r) => r[2])];
out.up = [press(field, { key: "ArrowUp" }), state().rows.map((r) => r[2])];
out.tab = [press(field, { key: "Tab" }), field.value, state().hidden, field.attrs["aria-expanded"]];
typeInto(field, "/re");
out.enterFills = [press(field, { key: "Enter" }), field.value, sent.length];
out.enterThenSends = [press(field, { key: "Enter" }), sent.slice()];
typeInto(field, "/");
press(field, { key: "ArrowDown" });
out.escape = [press(field, { key: "Escape" }), state().hidden, field.value];
out.escapeAgain = press(field, { key: "Escape" });                  // no list: the key is the frame's (a field has the focus: it does nothing)
typeInto(field, "/he");
out.helpExact = (() => { typeInto(field, "/help"); return [press(field, { key: "Enter" }), sent.slice(-1)[0], field.value]; })();
typeInto(field, "/status now");
out.afterSpace = state().hidden;
typeInto(field, "hello");
out.plain = state().hidden;
typeInto(field, "/zzz");
out.nomatch = state().hidden;
typeInto(field, "/");
rows()[3].listeners.mousedown.forEach((fn) => fn({ preventDefault() {} }));
out.mouse = [field.value, state().hidden];
composer.set({ sending: true, notice: null, disabled: false });
out.sending = [buttons.map((b) => b.disabled), state().hidden];
composer.set({ sending: false, notice: { title: "Not sent", text: "A run is in progress for this project. Your message was not stored." }, disabled: false });
const note = byClass(composer.el, "wb-lobby-notice-card")[0];
out.notice = [note.cls().filter((c) => c === "notice" || c.startsWith("pui-")), textOf(note), note.attrs.role, buttons[1].disabled];
composer.set({ sending: false, notice: null, disabled: true });
out.blocked = buttons.map((b) => b.disabled);

// the request block (R-47)
const NOW = new Date("2026-10-08T12:00:00Z");
const api = { approve: async () => ({}), reject: async () => ({}), pollJob: async () => ({ state: "done" }), cancel: async () => ({}) };
const make = (request, extra = {}) => createBlock({ api, project: "p1", request, body: extra.body || null, open: extra.open || 0, now: NOW, onChanged: async () => {}, onCancel: () => {}, onRoute: () => {}, routing: false, routeNotice: extra.notice || null, flows: extra.flows || null });
const block = make({ id: 10, title: "Size guide", state: "requested", tasks: [] }, { notice: { title: "Not routed yet", text: "Request #10 was created. The router could not run." }, flows: [{ flow: "design", title: "Design", tasks: 3 }] });
const box = byClass(block.el, "wb-request-box")[0];
const cls = (n) => n.cls().filter((c) => c.startsWith("wb-") || c.startsWith("pui-")).join(" ");
out.block = { root: block.el.attrs.id, boxIn: block.el.children[0] === box, boxChildren: box.children.map(cls), line: byClass(box, "wb-lobby-request-line")[0].children.map(cls),
  actions: byClass(box, "wb-lr-actions")[0].children.map((n) => n.tagName + ":" + (n.attrs["aria-label"] || n.textContent)), noticeClasses: byClass(box, "wb-lobby-notice-card")[0].cls() };
const info = make({ id: 12, title: "Gift cards", state: "requested", tasks: [] }, { notice: { tone: "info", title: "Recorded", text: "A run is in progress." } });
const infoNote = byClass(info.el, "wb-lobby-notice-card")[0];
out.info = [infoNote.cls().includes("pui-error"), infoNote.cls().includes("pui-soft"), infoNote.attrs.role];
const running = make({ id: 7, title: "Spring", state: "running", tasks: [] });
out.running = [byClass(running.el, "wb-chip-small")[0].cls().filter((c) => c.startsWith("pui-")), byClass(running.el, "wb-lr-actions")[0].children.map((n) => n.textContent)];
const final = make({ id: 9, title: "Old", state: "done", tasks: [] });
out.final = [byClass(final.el, "wb-request-box").length, byClass(final.el, "wb-lobby-request-line").length];

// the plan card (R-47): blocks at every width, no table, Go ahead a checkbox under Before it starts, one solid button
const hash = "ab".repeat(32);
const item = { id: 41, kind: "plan", title: "Plan: Autumn catalogue (3 tasks)", body: "text", task_id: 9, agent: null, status: "open", created_at: "2026-10-08T08:00:00Z", actions: ["approved", "rejected"],
  payload: { plan_sha256: hash, limits: { one_task_at_a_time: true, timeout_seconds: 1800, retries: 2 }, estimate: { runs_at_least: 3 },
    waits: [{ task_key: "layout", task_id: 2, reason: "docs/brand/voice.md, written by task 1" }],
    tasks: [{ key: "voice", title: "Write the voice", skill: "brand-voice", agent: "brand", depends_on: [] }, { key: "layout", title: "Lay out", skill: "catalogue-layout", agent: "design", depends_on: ["voice"], milestone: true },
      { key: "accept", title: "Accept", skill: "accept-request", depends_on: ["layout"], milestone: true, mandatory_milestone: true }] } };
const card = createPlanCard({ api, project: "p1", item, now: NOW, onChanged: async () => {} });
const list = byClass(card.el, "wb-plan-list")[0];
out.plan = { tables: all(card.el, "table").length, stacks: byClass(card.el, "wb-plan-stack").length, list: [list.tagName, list.attrs["aria-label"]], tasks: list.children.map((li) => li.children.map(textOf)),
  skill: byClass(list, "wb-cell-skill").map(textOf), before: textOf(byClass(card.el, "wb-waits-title")[0]), box: all(card.el, "input").filter((i) => i.attrs.type === "checkbox").map((i) => [i.attrs.class, i.attrs["data-key"]]),
  goAhead: textOf(byClass(card.el, "wb-waits-task")[0]), solid: byClass(card.el, "pui-solid").map(textOf), outline: byClass(card.el, "pui-outline").map(textOf), error: byClass(card.el, "wb-card-error")[0].cls().filter((c) => c.startsWith("pui-") || c === "notice") };
console.log(JSON.stringify(out));
"""


def test_the_tabs_the_form_the_composer_the_request_block_and_the_plan_card_are_built_as_the_page_draws_them():
    got = run_view_node(Path_tmp(), R4_PIECES)
    t = got["tabs"]
    assert t["names"] == ["Conversation", "Inbox, 2 waiting", "Tasks", "Desk", "Agent"] and t["barHolds"] is True and "wb-lobby-tabbar" in t["barClass"] and t["listClass"] == ["wb-lobby-tabs"], "R-43"
    assert t["selected"] == [False, False, True, False, False] and t["count"][1] == ["2", False] and all(c[1] for i, c in enumerate(t["count"]) if i != 1), "only Inbox carries a count"
    assert got["tabsHidden"] == [True, True]
    f = got["form"]
    assert f["hiddenAtFirst"] is True and f["open"] == [False] and "wb-newreq" in f["root"], "R-44: a form of its own, hidden until New request"
    assert f["details"] == 0 and f["dialog"] == 0, "R-44: not a disclosure and not a modal"
    assert f["head"][0].endswith("wb-newreq-head") and f["title"] == "New request" and f["back"] == "Back to the conversation"
    assert f["labels"] == ["What do you want done?", "Flow", "Title (optional)", "After request (optional)"] and f["create"] == ["Create request"], "R-44, R-46: the four fields, the one solid button"
    assert f["after"] == [["", "None: it starts when it can"], ["7", "#7 Spring sale page · Running"], ["9", "#9 Autumn · Planned"]], "R-46: a select of the open requests"
    assert f["hint"] == "The request waits until the one you pick is done or cancelled. Only requests still open are listed."
    assert f["shown"] == [False, True] and f["backs"] == 1
    assert got["created"] == [{"text": "Add a size guide", "flow": "", "title": "", "after": "9"}, {"text": "Add a size guide", "flow": "", "title": ""}], "after is sent only when a request was chosen"
    assert got["keptChoice"] == "7" and got["droppedChoice"] == "" and got["reset"] == ["", ""]
    c = got["composer"]
    assert c["order"] == ["Send", "New request"], "the keyboard order is the field, Send, New request (lobby.md); the stylesheet draws New request at the left"
    assert "pui-solid" in c["classes"][0] and "pui-outline" in c["classes"][1] and "wb-new-btn" in c["classes"][1], "R-44, C-16: Send is the one solid button"
    assert c["hints"] == ["Type / to list the commands."], "R-45: the hint, and no second hint"
    assert c["list"] == [["listbox", True, "Commands"]] and c["combobox"] == ["combobox", "false", "wb-say-cmds", "list"]
    assert got["asked"] == 1 and got["beforeCommands"] is True, "until the commands are known no list opens"
    assert len(got["open"]["rows"]) == 5 and got["open"]["rows"][0] == ["/help ", "list the commands", "true", "option"] and got["open"]["rows"][2][0] == "/release <id>", \
        "R-45: one row for each command: the command, its arguments, its help line"
    assert got["open"]["expanded"] == "true" and got["open"]["active"] == got["openIds"][0] and len(set(got["openIds"])) == 5
    assert [r[0].split(" ")[0] for r in got["narrow"]["rows"]] == ["/release", "/reject", "/retry"], "typing narrows the list"
    assert got["down"][:2] == [True, ["false", "true", "false"]] and got["down"][2].endswith("-1"), "the arrows move"
    assert got["wrap"][2] == ["true", "false", "false"] and got["up"][1] == ["false", "false", "true"]
    assert got["tab"] == [True, "/retry ", True, "false"], "Tab fills the field with the row and closes the list"
    assert got["enterFills"] == [True, "/release ", 0], "Enter fills the field from the open list and sends nothing"
    assert got["enterThenSends"] == [True, ["/release "]], "with the list closed, Enter sends"
    assert got["escape"] == [True, True, "/"], "Escape closes the list and keeps the text"
    assert got["escapeAgain"] is False, "with no list open Escape is not the composer's"
    assert got["helpExact"] == [True, "/help", "/help"], "a command typed whole and taking no arguments is sent by Enter"
    assert got["afterSpace"] is True and got["plain"] is True and got["nomatch"] is True
    assert got["mouse"] == ["/reject ", True], "a click on a row fills the field"
    assert got["sending"][0] == [True, True] and got["sending"][1] is True
    assert got["notice"] == [["notice", "pui-soft", "pui-error"], "Not sentA run is in progress for this project. Your message was not stored.", "alert", False], "R-11: the soft error style"
    assert got["blocked"] == [True, True]
    b = got["block"]
    assert b["root"] == "wb-request-10" and b["boxIn"] is True, "the block keeps its id; the request line is a block of its own (R-47)"
    assert b["line"] == ["pui-badge pui-muted pui-soft pui-rounded-full", "pui-btn pui-link wb-lobby-request-title", "pui-chip pui-muted pui-soft wb-chip-small"], "R-47: number, title, state chip on one line"
    assert b["boxChildren"][0] == "wb-lobby-request-line" and b["boxChildren"][1] == "wb-lr-actions" and b["boxChildren"][-1].startswith("wb-lobby-notice-card")
    assert b["actions"] == ["SELECT:Flow for request 10", "BUTTON:Route request 10", "BUTTON:Cancel request 10"], "R-47, E-28: `Route it` and `Cancel request` under the line"
    assert "notice" in b["noticeClasses"] and "pui-soft" in b["noticeClasses"] and "pui-error" in b["noticeClasses"]
    assert got["info"] == [False, False, "status"], "the Recorded notice is information, not an error"
    assert got["running"] == [["pui-chip", "pui-theme", "pui-soft"], ["Cancel request"]], "C-23: Running takes the theme colour"
    assert got["final"] == [0, 0]
    p = got["plan"]
    assert p["tables"] == 0 and p["stacks"] == 0 and p["list"] == ["OL", "Plan tasks"], "R-47: the plan's tasks are blocks at every width, the table is gone"
    assert p["tasks"][0] == ["1", "Write the voicebrand-voice · brandAfter - · Milestone no · Web no"] and p["tasks"][1][1].endswith("After 1 · Milestone yes · Web no")
    assert [row[0] for row in p["tasks"]] == ["1", "2", "3"] and p["skill"] == ["brand-voice", "catalogue-layout", "accept-request"]
    assert p["before"] == "Before it starts" and p["box"] == [["wb-checkbox", "go-ahead-layout"]] and p["goAhead"] == "Go ahead on Lay out", "R-47: Go ahead is a checkbox under Before it starts"
    assert p["solid"] == ["Approve this plan"] and "Reject" in p["outline"], "C-16: one solid button"
    assert p["error"] == ["notice", "pui-soft", "pui-error"]


R4_VIEW = r"""
import { FakeNode, settle, find, all } from "@FAKE@";
import { setToken } from "@JS@/token.js";
import * as router from "@JS@/router.js";
import { createLobbyView } from "@JS@/views/lobby.js";

const FakeText = document.createTextNode("").constructor;
globalThis.Node = class { static [Symbol.hasInstance](x) { return x instanceof FakeNode || x instanceof FakeText; } };
setToken("t".repeat(40));
globalThis.ResizeObserver = class { observe() {} disconnect() {} };
document.removeEventListener = (type, fn) => { document.listeners[type] = (document.listeners[type] || []).filter((f) => f !== fn); };
const P = "0123456789ab";
const NOW = new Date("2026-10-08T12:00:00Z");
const sent = [];
const answers = new Map();
globalThis.fetch = async (url, init) => {
  sent.push({ method: init.method, url, body: init.body === undefined ? null : JSON.parse(init.body) });
  const key = `${init.method} ${url.split("?")[0]}`;
  let answer = url.includes("/conversation") && init.method === "GET" ? { status: 200, body: { messages: [] } } : answers.get(key);
  if (!answer && /\/tasks\/\d+$/.test(url)) answer = { status: 200, body: { task: { id: Number(url.split("/").pop()) }, runs: [], pending: [] } };
  answer = answer || { status: 200, body: {} };
  return { ok: answer.status < 400, status: answer.status, json: async () => answer.body };
};
const A = (path) => `/api/v1/projects/${P}${path}`;
answers.set(`GET ${A("/flows")}`, { status: 200, body: { flows: [{ flow: "design", title: "Design", tasks: 3 }] } });
answers.set(`GET ${A("/commands")}`, { status: 200, body: { commands: [{ command: "/help", arguments: "", help: "list the commands" }, { command: "/status", arguments: "", help: "requests" }] } });
answers.set(`POST ${A("/requests")}`, { status: 200, body: { request: 20, state: "requested", next: "route" } });
answers.set(`POST ${A("/requests/20/route")}`, { status: 202, body: { job: 7 } });
answers.set("GET /api/v1/jobs/7", { status: 200, body: { job: 7, state: "done", result: { routed: true } } });
const agent = (name) => ({ name, pack: "x", enabled: true, mode: "supervised", acting_mode: "supervised", max_runs_per_day: 8, max_usd_per_day: 4, runs_today: 1, usd_today: 0.1, runs_without_cost: 0, queued: 0 });
const states = ["done", "cancelled", "planned", "running", "requested", "cancelled", "done", "planned", "cancelled", "done", "requested", "cancelled"];
const requests = states.map((state, i) => ({ id: i + 1, title: `Request ${i + 1}`, state, tasks: [] }));
const resolvedBody = (id) => ({ task: { id }, runs: [], pending: [{ id: 100 + id, kind: "plan", title: `Plan of request ${id}`, status: states[id - 1] === "cancelled" ? "cancelled" : "resolved", resolution: states[id - 1] === "cancelled" ? null : "approved",
  created_at: "2026-10-08T08:00:00Z", resolved_at: `2026-10-08T09:${String(id).padStart(2, "0")}:00Z`, actions: [] }] });
for (let id = 1; id <= 12; id++) answers.set(`GET ${A("/tasks/" + id)}`, { status: 200, body: resolvedBody(id) });
const snapshot = { loaded: true, projects: [{ id: P, name: "northwind-shop", config: { accepted: true } }], tasks: {}, details: { [P]: { agents: [agent("planning")], status: { requests, pending: [] } } } };
const makeFrame = () => ({ el: new FakeNode("div"), main: new FakeNode("main"), sceneHost: new FakeNode("div"), track: { el: new FakeNode("div") }, noticeBox: new FakeNode("div"),
  insets: () => ({ left: 0, right: 0, top: 0, bottom: 0, pad: 1 }), sceneUnavailable() {}, announce() {}, acquireWorld: () => ({ show() {}, setOptions() {}, flyTo: () => Promise.resolve(false), stats() { return {}; } }), kpis: { el: new FakeNode("div") } });
const byClass = (root, name) => [...root.walk()].filter((n) => n.cls && n.cls().includes(name));
const click = (n) => (n.listeners.click || []).forEach((fn) => fn({ preventDefault() {}, stopPropagation() {}, target: n }));
const out = {};
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

// --- R-44, R-46, R-45: the form takes the thread's and the composer's place and gives them back with the draft kept ---
window.location.hash = `#/p/${P}/lobby`;
let frame = makeFrame();
let view = createLobbyView(frame, { project: P, onChanged: async () => {} });
view.update({ snapshot, route: router.parse(`#/p/${P}/lobby`), now: NOW, projectName: "northwind-shop" });
await wait(300); await settle();
const thread = byClass(frame.main, "wb-thread")[0];
const footer = byClass(frame.main, "wb-lobby-footer")[0];
const form = byClass(frame.main, "wb-newreq")[0];
const state = () => ({ thread: !thread.hidden, footer: !footer.hidden, form: !form.hidden });
out.start = state();
out.title = [byClass(frame.main, "wb-panel-title")[0].textContent, byClass(frame.main, "wb-panel-sub")[0].textContent];
out.options = all(form, "select")[1].children.map((o) => o.attrs.value);
out.commandsRead = sent.filter((s) => s.url === A("/commands")).length;
click(byClass(frame.main, "wb-new-btn")[0]);
out.opened = state();
out.focusedField = document.activeElement === all(form, "textarea")[0];
all(form, "textarea")[0].value = "Add a size guide";
all(form, "select")[1].value = "5";
click(byClass(form, "wb-newreq-back")[0]);
out.back = state();
click(byClass(frame.main, "wb-new-btn")[0]);
out.draft = [all(form, "textarea")[0].value, all(form, "select")[1].value];
(all(form, "form")[0].listeners.submit || []).forEach((fn) => fn({ preventDefault() {} }));
await wait(2500); await settle();
out.created = { requests: sent.filter((s) => s.url === A("/requests")).map((s) => s.body), route: sent.filter((s) => s.url === A("/requests/20/route")).length, after: state(), fields: [all(form, "textarea")[0].value, all(form, "select")[1].value] };
view.dispose();

// --- P-6: with the Inbox open every request's decisions are read and listed, a cancelled request's included ---
sent.length = 0;
window.location.hash = `#/p/${P}/lobby/inbox`;
frame = makeFrame();
view = createLobbyView(frame, { project: P, onChanged: async () => {} });
view.update({ snapshot, route: router.parse(`#/p/${P}/lobby/inbox`), now: NOW, projectName: "northwind-shop" });
await wait(500); await settle(); await wait(300); await settle();
const reads = sent.filter((s) => /\/tasks\/\d+$/.test(s.url)).map((s) => Number(s.url.split("/").pop()));
const items = all(frame.main, ".wb-resolved-item").map((n) => n.textContent);
out.inbox = { reads: [...new Set(reads)].sort((a, b) => a - b), lines: items.length, cancelled: items.filter((t) => t.includes("cancelled")).length, mentions: [items.some((t) => t.includes("Plan of request 12")), items.some((t) => t.includes("Plan of request 1"))] };
view.update({ snapshot, route: router.parse(`#/p/${P}/lobby/inbox`), now: NOW, projectName: "northwind-shop" });
await wait(300); await settle();
out.inboxAgain = sent.filter((s) => /\/tasks\/\d+$/.test(s.url)).length - reads.length;      // a second draw reads nothing more
// the Conversation alone reads the few it shows, not every request
sent.length = 0;
view.update({ snapshot, route: router.parse(`#/p/${P}/lobby`), now: NOW, projectName: "northwind-shop" });
await wait(300); await settle();
out.conversationReads = sent.filter((s) => /\/tasks\/\d+$/.test(s.url)).length;
view.dispose();
console.log(JSON.stringify(out));
process.exit(0);
"""


def test_the_form_takes_the_place_of_the_thread_and_the_composer_and_the_inbox_reads_and_lists_every_request_P6():
    got = run_view_node(Path_tmp(), R4_VIEW)
    assert got["title"] == ["Planning agent", "Lobby · floor 0"], "C-6: the page's title and sub line"
    assert got["start"] == {"thread": True, "footer": True, "form": False}
    assert got["opened"] == {"thread": False, "footer": False, "form": True} and got["focusedField"] is True, "R-44: the form is in the place of the thread and the composer, and the text area has the focus"
    assert got["back"] == {"thread": True, "footer": True, "form": False}, "Back to the conversation returns"
    assert got["draft"] == ["Add a size guide", "5"], "R-44: the draft is kept"
    assert got["options"] == ["", "3", "4", "5", "8", "11"], "R-46: the requests that are not done or cancelled, by number"
    assert got["commandsRead"] == 1, "R-45: the commands are read once"
    c = got["created"]
    assert c["requests"] == [{"text": "Add a size guide", "after": 5}] and c["route"] == 1, "request with `after`, then route"
    assert c["after"] == {"thread": True, "footer": True, "form": False} and c["fields"] == ["", ""], "a request made: the form is emptied and the conversation is back"
    i = got["inbox"]
    assert i["reads"] == list(range(1, 13)), "P-6: with the Inbox open the body of every request is read, a done or cancelled one too"
    assert i["lines"] == 12 and i["cancelled"] == 4 and i["mentions"] == [True, True], "P-6: every resolved or cancelled decision is listed, not the newest eight"
    assert got["inboxAgain"] == 0, "a second draw with the same data reads nothing more"
    assert got["conversationReads"] <= 8, "the Conversation reads the few requests it shows (MAX_BODIES), not every request"


DESK_MARKUP = r"""
import { FakeNode, settle, find, all } from "@FAKE@";
import { setToken } from "@JS@/token.js";
import { createLobbyDesk } from "@JS@/views/lobby-desk.js";
const FakeText = document.createTextNode("").constructor;
globalThis.Node = class { static [Symbol.hasInstance](x) { return x instanceof FakeNode || x instanceof FakeText; } };
setToken("t".repeat(40));
const P = "0123456789ab";
const answers = new Map();
globalThis.fetch = async (url, init) => { const a = answers.get(`${init.method} ${url.split("?")[0]}`) || { status: 200, body: {} }; return { ok: a.status < 400, status: a.status, json: async () => a.body }; };
const doc = (path, agent, owner, over = {}) => ({ path, owner, agent, size: 1843, modified_at: "2026-10-08T09:00:00Z", bound: false, kind: "markdown", ...over });
answers.set(`GET /api/v1/projects/${P}/artifacts`, { status: 200, body: { artifacts: [doc("docs/workbench/state.md", "planning", "state"), doc("docs/engineering/sale-route.md", "engineering", "implement-change"), doc("docs/notes/x.md", null, null, { modified_at: "2026-10-08T08:00:00Z" })], truncated: false } });
const opened = [];
const desk = createLobbyDesk({ project: P, open: (p) => opened.push(p), changed: () => {} });
desk.update({ tab: "desk", ready: true });
await settle();
const list = find(desk.el, "ul.wb-desk-list");
const rows = all(desk.el, "li.wb-desk-row");
const out = {
  list: [list.tagName, list.attrs["aria-label"], list.cls().includes("pui-card")], table: all(desk.el, "table").length,
  rows: rows.map((r) => r.children.map((c) => [c.tagName, (c.attrs.class || "").split(" ").filter((x) => x.startsWith("wb-") || x.startsWith("pui-")).join(" ")])),
  badges: all(desk.el, ".wb-desk-agent").map((n) => [n.textContent, n.cls().includes("pui-badge")]), meta: all(desk.el, ".wb-desk-meta").map((n) => n.textContent),
  owners: all(desk.el, ".wb-desk-owner").map((n) => n.textContent), filter: find(desk.el, "input").attrs.placeholder, order: all(desk.el, "button.wb-path-button").map((b) => b.attrs["data-path"]),
};
find(desk.el, "button.wb-path-button").click();
out.opened = opened;
console.log(JSON.stringify(out));
"""


def test_the_lobbys_desk_is_a_list_of_two_line_rows_with_the_agent_as_a_badge():
    got = run_view_node(Path_tmp(), DESK_MARKUP)
    assert got["list"] == ["UL", "Documents of the project, newest first", True] and got["table"] == 0, "R-40, R-47: a list, not a table"
    assert got["rows"][0][0][0] == "BUTTON" and got["rows"][0][1] == ["SPAN", "pui-badge pui-muted pui-soft wb-desk-agent"] and got["rows"][0][-1][1].startswith("wb-desk-meta"), \
        "the path, the agent's badge, then the meta line"
    assert got["badges"] == [["Engineering", True], ["Lobby", True], ["—", True]], "R-47: the agent as a badge, in the frame's word for it (the planning agent is the Lobby), a dash for none"
    assert got["meta"][1].startswith("state · 1.8 KB · Markdown · ") and got["meta"][1].count("2026-10-08") == 1, "the owner skill, the size and kind, the time"
    assert got["owners"] == ["implement-change", "state", ""] and got["filter"] == "Path or owner skill"
    assert got["order"] == ["docs/engineering/sale-route.md", "docs/workbench/state.md", "docs/notes/x.md"] and got["opened"] == ["docs/engineering/sale-route.md"]


def test_escape_leaves_the_new_request_form_before_a_menu_and_after_a_dialog_or_a_document():
    import subprocess
    script = f"""
import {{ escapeStep }} from {json.dumps((JS / 'frame' / 'escape.js').as_uri())};
import * as router from {json.dumps((JS / 'router.js').as_uri())};
const lobby = router.parse("#/p/0123456789ab/lobby");
const out = {{
  form: escapeStep({{ route: lobby, form: true }}), field: escapeStep({{ route: lobby, form: true, field: true }}), dialog: escapeStep({{ route: lobby, form: true, dialog: true }}),
  doc: escapeStep({{ route: router.parse("#/p/0123456789ab/lobby/desk/docs%2Fa.md"), form: true }}).step, menu: escapeStep({{ route: lobby, form: true, menu: true }}),
  none: escapeStep({{ route: lobby }}).step, floor: escapeStep({{ route: router.parse("#/p/0123456789ab/floor/design"), form: true }}).step,
}};
console.log(JSON.stringify(out));
"""
    path = Path_tmp() / "esc.mjs"
    path.write_text(script, encoding="utf-8")
    done = subprocess.run(["node", str(path)], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    got = json.loads(done.stdout.strip().splitlines()[-1])
    assert got["form"]["step"] == "form" and got["field"]["step"] == "none" and got["dialog"]["step"] == "dialog", "R-44 (R-45): Escape with a field focused does nothing; a dialog closes first"
    assert got["doc"] == "document" and got["menu"]["step"] == "form" and got["none"] == "up" and got["floor"] == "form"
    frame = (JS / "frame" / "frame.js").read_text(encoding="utf-8")
    assert 'step.step === "form"' in frame and ".wb-newreq:not([hidden])" in frame, "the frame turns the step into a click on Back"


def test_the_stylesheet_draws_the_lobby_as_the_page_does_M3():
    css = (INTERFACE / "css" / "lobby.css").read_text(encoding="utf-8")

    def rule(selector: str) -> dict:
        m = re.search(r"(?m)^" + re.escape(selector) + r"\s*\{([^}]*)\}", css)
        assert m, f"no rule for {selector}"
        return {k.strip(): v.strip() for k, v in (p.split(":", 1) for p in m.group(1).split(";") if ":" in p)}

    tab = rule(".wb-lobby-tab")
    assert tab["flex"].strip() == "1 1 0" and tab["font-weight"].strip() == "400" and "border-radius" in tab and tab["font-size"].strip() == "13px", "R-43: equal parts, the regular weight, a smaller size"
    assert "border-bottom" not in " ".join(rule(".wb-lobby-tab").keys()) and "background-color" in rule(".wb-lobby-tab.is-selected") and "box-shadow" in rule(".wb-lobby-tab.is-selected"), "a raised piece, no underline"
    assert "border-radius" in rule(".wb-lobby-tabs") and "padding" in rule(".wb-lobby-tabs")
    assert rule(".wb-composer")["grid-template-columns"].strip() == "minmax(0, 1fr) auto" and rule(".wb-composer")["position"].strip() == "relative"
    assert rule(".wb-new-btn")["grid-column"].strip() == "1" and rule(".wb-send")["grid-column"].strip() == "2", "New request at the left, Send at the right, in the keyboard's other order"
    assert rule(".wb-slash")["position"].strip() == "absolute" and rule(".wb-slash")["max-height"].strip() == "296px" and rule(".wb-slash")["bottom"].startswith("calc(100% + 6px)")
    assert "overflow" not in rule(".wb-lobby-footer"), "the list of commands stands over the thread: the footer clips nothing"
    assert rule(".wb-request-box")["border"].startswith("var(--pui-border-width) solid") and "border-radius" in rule(".wb-request-box"), "R-47: a small bordered block"
    assert rule(".wb-lobby-request-line")["grid-template-columns"].strip() == "auto minmax(0, 1fr) auto"
    assert rule(".wb-msg-meta")["font-size"].strip() == "11px" and "border-bottom-right-radius" in rule(".wb-msg.is-user .wb-bubble") and "border-bottom-left-radius" in rule(".wb-msg.is-agent .wb-bubble")
    assert "border" not in rule(".wb-lobby-run") and rule(".wb-lobby-run")["color"].strip() == "var(--pui-text-muted)", "(b)3: the run line is muted text, not a box"
    assert "border" not in rule(".wb-lobby-notice-card"), "R-11: no line round a notice"
    assert "border" not in rule(".wb-lobby-resolved") and "background-color" not in rule(".wb-lobby-resolved"), "the resolved line is plain; a pointer line has the sunken ground"
    assert "background-color" in rule(".wb-pointer")
    assert rule(".wb-desk-list .wb-desk-row")["grid-template-columns"].strip() == "minmax(0, 1fr) auto", "R-47: two-line rows"
    assert ".wb-panel-lobby .wb-plan-task" in css and "wb-plan-table" not in css, "R-47: blocks at every width"
    # M-3: the phone's layout is up to 899 px, and no block of the docked band is left
    assert "@media (max-width: 899px)" in css and "639px" not in css and "640px" not in css, "M-3: the phone applies up to 899 px, the docked band (640 to 899 px) is removed"
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(", css), "the Lobby's rules set no colour of their own"
    assert not re.search(r"bottom left|\.wb-dock|\.wb-nav|\.wb-back|\.wb-crumb", css), "M-4 was revoked (M-10): the stylesheet makes no assumption about the frame's bottom left, free or not"
    desk = (VIEWS / "lobby-desk.js").read_text(encoding="utf-8")
    assert "PHONE_QUERY" in desk and "max-width" not in desk, "M-3: the width is the frame's one query, not a literal"
    for source in (*VIEWS.glob("lobby*.js"), *CARDS.glob("*.js")):
        assert not re.search(r"max-width: ?\d+px|min-width: ?\d+px", source.read_text(encoding="utf-8")), f"{source.name} names a width"


R4_STICK = R4_HEAD + r"""
import { createThread } from "@JS@/views/lobby-thread.js";
const NOW = new Date("2026-10-08T12:00:00Z");
const api = { approve: async () => ({}), reject: async () => ({}), pollJob: async () => ({ state: "done" }), cancel: async () => ({}) };
const thread = createThread({ api, project: "p1", signal: undefined, onChanged: async () => {}, onCancel: () => {}, onRoute: () => {} });
const msg = (id) => ({ id, role: "user", text: `m${id}`, created_at: "2026-10-08T11:00:00Z" });
const draw = (n) => thread.update({ messages: Array.from({ length: n }, (_, i) => msg(i + 1)), requests: [], pending: [], bodies: {}, now: NOW, loading: false, routing: new Set() });
const el = thread.el;
el.scrollHeight = 1000; el.clientHeight = 300; el.scrollTop = 0;
const scrollTo = (top) => { el.scrollTop = top; (el.listeners.scroll || []).forEach((fn) => fn({})); };
draw(1);
out.opened = el.scrollTop;                                  // the first draw puts the thread at its end
el.scrollHeight = 1600;                                     // what was read later (a plan card) made it taller; the next draw follows
draw(2);
out.followed = el.scrollTop;
scrollTo(200);                                              // the person reads an older line
el.scrollHeight = 1900;
draw(3);
out.left = el.scrollTop;                                    // a new message does not pull them away
scrollTo(1900 - 300 - 10);                                  // back near the end
el.scrollHeight = 2200;
draw(4);
out.back = el.scrollTop;
console.log(JSON.stringify(out));
"""


def test_the_thread_opens_at_its_end_follows_it_and_lets_go_when_the_person_scrolls_away():
    got = run_view_node(Path_tmp(), R4_STICK)
    assert got == {"opened": 1000, "followed": 1600, "left": 200, "back": 2200}, "(b)5: the thread opens at its end, also when what it holds grows after the first draw"
