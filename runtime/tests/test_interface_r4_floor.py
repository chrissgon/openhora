"""Tests of the Floor screen that look at its presentation (R4-S): the Agent tab, the Tasks tab, the decision cards, the resolved line, the Desk and the viewer's way
back, and the classes the Tasks tab builds against the stylesheet. A package for the Floor edits this file and `test_interface_floor.py`, `test_interface_tasks_tab.py`,
`test_interface_resolved_said.py`, `interface/css/floor.css` and `interface/js/floor/*`, `interface/js/cards/*`, `interface/js/views/floor.js` (the Lobby shows the
Floor's modules in its own panel, so a change there reaches it); the tests of the shared files (`test_interface_files.py`: routes, writes, text as text) stay where they
are. The tests below were moved here from the shared files with their names and their assertions unchanged; each reads what it needs through the module it came from.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interface_r4_floor.py
"""
from __future__ import annotations

import re

from interface_css import interface_css
from test_interface_adj_b1 import HAND_CARD, HAND_TAB
from test_interface_adjustments import CARDS, JS, TABS, _css, _rules, run_node
from test_interface_cards_fields import FLOOR, FOCUS, css_rules, run_node as run_node_cards_fields
from test_interface_files import INTERFACE, TASKS_TAB_FILES
from test_interface_floor import needs_node
from test_interface_plates_meters import AGENT, WIDER, run_node as run_node_plates_meters


# --- moved from test_interface_files.py ------------------------------------------------------------------------------------------


def test_every_class_the_tasks_tab_builds_is_styled_and_the_block_uses_tokens_and_no_literal_colour():
    css = interface_css()
    missing = {}
    for name in TASKS_TAB_FILES:
        assert (INTERFACE / "js" / name).is_file()
        for cls in set(re.findall(r"\bwb-[a-z0-9]+(?:-[a-z0-9]+)*", (INTERFACE / "js" / name).read_text(encoding="utf-8"))):
            if not re.search(re.escape("." + cls) + r"(?![A-Za-z0-9_-])", css):
                missing.setdefault(cls, []).append(name)
    assert not missing, f"classes the Tasks tab builds that the stylesheets never name: {missing}"
    start = css.index("/* --- the Tasks tab (WP-9.16)")
    block = css[start:]
    assert "wb-task" in block
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(", block), "the Tasks tab's rules name colours by token"

# --- moved from test_interface_adj_b1.py -----------------------------------------------------------------------------------------


@needs_node
def test_the_review_card_hands_a_file_over_in_two_steps_and_a_change_alone_sends_nothing(tmp_path):
    got = run_node(tmp_path, HAND_CARD)
    assert got["before"] == {"button": 0, "chosen": 0}, "no file chosen: no button"
    assert got["afterChange"]["calls"] == 0, "C-17: choosing a file sends nothing"
    assert got["afterChange"]["chosen"] == "logo.png" and got["afterChange"]["button"] == "Hand over to task #5" and got["afterChange"]["name"] == "Hand over to task #5"
    assert got["afterChange"]["line"] == "this file will be visible to a run with the open network", "the web line stays above the control"
    assert got["afterButton"]["calls"] == [["p", 5, "logo.png"]], "the button sends handOver with the file"
    assert got["afterButton"]["result"] == "Handed over: docs/inputs/logo.png (3 bytes)"
    assert got["afterButton"]["button"] == 0 and got["afterButton"]["chosen"] == 0, "the choice is spent once it was sent"
    assert got["bad"]["text"] == "The file name may hold letters, digits, ., _ and -, at most 100 characters." and got["bad"]["button"] == 0 and got["bad"]["calls"] == 1
    assert got["second"] == "second.png" and got["secondCalls"] == [[5, "second.png"]], "the button sends the file chosen last"
    assert got["failed"]["text"] == "The file is too large for this task." and got["failed"]["button"] == 1 and got["failed"]["chosen"] == "logo.png", "a failure leaves the choice so the button can be pressed again"


@needs_node
def test_the_agent_tab_hands_a_file_over_in_two_steps_and_names_the_task_the_button_sends_to(tmp_path):
    got = run_node(tmp_path, HAND_TAB)
    assert got["before"] == 0
    assert got["afterChange"] == {"calls": 0, "chosen": "logo.png", "button": "Hand over to task #11", "line": "this file will be visible to a run with the open network"}, \
        "C-17: the chooser, then the name and the button; a change sends nothing; the web line stays above"
    assert got["afterPoll"] == {"chosen": "logo.png", "button": "Hand over to task #11"}, "a reload keeps the choice"
    assert got["otherTarget"] == "Hand over to task #11" and got["hintAfterMove"] == "To task #12. At most 25 MiB.", "the hint follows the target, the button keeps the task the file was chosen for"
    assert got["afterButton"]["calls"] == [["0123456789ab", 11, "logo.png"]] and got["afterButton"]["result"] == "Handed over: docs/inputs/logo.png (3 bytes)" and got["afterButton"]["button"] == 0
    assert got["bad"]["text"] == "The file name may hold letters, digits, ., _ and -, at most 100 characters." and got["bad"]["button"] == 0 and got["bad"]["calls"] == 1

# --- moved from test_interface_adjustments.py ------------------------------------------------------------------------------------


@needs_node
def test_the_tasks_tab_and_the_agent_tab_draw_the_same_actions_and_a_blocked_current_task_has_retry_with_its_sentence(tmp_path):
    got = run_node(tmp_path, TABS)
    t = got["tasks"]
    assert t["waits5"] == ["waiting for #10: docs/brand/identity.md, written by task #10"]
    assert t["actions5"] == [["Go ahead", "Go ahead on task 5"]] and t["actions6"] == [["Drop the after", "Drop the after of task 6"]]
    assert t["actions7"] == [["Go ahead", "Go ahead on task 7"], ["Drop the after", "Drop the after of task 7"]] and t["actions8"] == 0
    assert t["waits6"] == ["waiting for request #3"]
    assert t["blocked"]["buttons"] == [["Retry", "Retry task 9"]]
    assert t["blocked"]["beside"] == "design-system needs docs/brand/identity.md; nothing writes it" and t["blocked"]["under"], "A-31: the sentence stands beside Retry, not under the row"
    assert t["failedNote"] == "Timed out"
    assert t["effect"] == ["The task starts without waiting; it may stop for the missing file."] and t["noEffect"] == 0, "what a go-ahead does is said beside it, and only beside it"
    assert t["sent"] == [["goAhead", "0123456789ab", 5, None], ["goAhead", "0123456789ab", 6, {"dropAfter": True}], ["goAhead", "0123456789ab", 7, None]], \
        "Go ahead sends the task; Drop the after sends dropAfter: true"
    assert t["refused"] == "That task waits for nothing to go ahead of." and t["refreshed"]
    b = got["blocked"]
    assert b["buttons"] == ["Retry task 11"], "A-32: a blocked current task has Retry in the Agent tab"
    assert b["note"] == "design-system needs docs/brand/identity.md; nothing writes it" and b["head"].startswith("#11 Task 11")
    assert b["sent"] == [["retry", "0123456789ab", 11]]
    assert got["failed"] == ["Retry task 12"]
    assert got["waiting"] == {"buttons": [], "link": "#/p/0123456789ab/floor/design/inbox/77", "text": "Open in the Inbox"}
    assert got["planned"]["buttons"] == ["Go ahead on task 14"] and got["planned"]["waits"] == ["waiting for #10: docs/brand/identity.md, written by task #10"]
    assert got["planned"]["sent"] == [["goAhead", "0123456789ab", 14, None]]
    assert got["running"] == {"buttons": [], "actions": 0}
    d = got["drop"]
    assert d["line"] == "this file will be visible to a run with the open network" and d["hidden"] is False and d["order"] == ["wb-drop-line", "wb-file"] and d["input"] is False, \
        "A-30: the Agent tab's hand-over shows the web line above the chooser"
    assert d["reads"] == 0, "the current task's body is used as it is"
    assert got["dropNonWeb"] == {"hidden": True, "input": False, "reads": [12]}, "another target is read once, however often the tab is drawn"
    assert got["dropRefuses"] == [True, True, [12, 13]] and got["noReader"] is True
    by_title = {o[0]: o for o in got["others"]}
    assert by_title["#17 Task 17"][1] == ["Retry task 17"] and by_title["#17 Task 17"][2] == ["needs a file"]
    assert by_title["#18 Task 18"][1] == ["Drop the after of task 18"] and by_title["#18 Task 18"][3] == ["waiting for request #3"]


@needs_node
def test_the_unrecognised_route_has_its_two_actions_the_done_card_wraps_its_result_and_a_review_hands_a_file_over(tmp_path):
    got = run_node(tmp_path, CARDS)
    assert got["is"] == [True, False, False, False]
    card = got["card"]
    assert card["body"] == "The planning agent did not name a flow or a skill for request 6", "A-25: the sentence is the body"
    assert card["words"] == [["choose-flow", "Choose a flow"], ["cancel-request", "Cancel the request"], ["answered", "Send answer"]], "the two actions, then the answer the decision still takes"
    assert card["disclosure"] == "Show the agent's reply" and card["raw"] == "Route: none (direct)\nWhy: a question\nNext: ask the flow list <b>x</b>" and card["rawElements"] == 0, "the reply whole, as plain text"
    assert got["plain"] == {"words": ["answered"], "disclosure": True}, "an ordinary question has neither the two buttons nor the reply"
    assert got["flows"]["options"] == [["", "Choose a flow..."], ["brand", "Brand of a product"], ["design", "Design"]], "a flow that failed to load is not offered"
    assert got["flows"]["calls"] == [["p"]]
    assert got["noFlow"] == {"hint": "Choose a flow.", "routes": 0}
    assert got["route"]["calls"] == [["route", "p", 6, {"flow": "design"}], ["pollJob", "j1", 1000]], "route with the request's id and the chosen flow, then the job"
    assert got["route"]["done"].startswith("Request routed")
    assert got["flowReads"] == 1
    assert got["cancel"]["calls"] == [["cancel", "p", 6]] and got["cancel"]["done"].startswith("Request cancelled")
    assert got["flowError"] == {"text": "The flows could not be read.", "select": True, "buttons": 3}
    assert got["unrouted"]["done"] is True and "no model" in got["unrouted"]["error"], "a route that was not made is an error on the card, not a done card"
    d = got["doneSentence"]
    assert "wb-card-done" in d["classes"] and d["children"][-1] == "wb-card-result", "the result is its own block after the chip and the title"
    assert d["mono"] == 0 and d["prose"] == ["an answer to the router is given to its next run, not recorded as a decision"], "A-26: a sentence is prose, not mono"
    assert d["title"] == "Brand voice <b>question</b>"
    assert "wb-card-done-title" in got["doneTitleClass"], "the title has its own class, so that it can wrap"
    ids = got["doneIds"]
    assert ids["mono"] == ["commit: abc1234", 'pull request: {"number":12}'], "an id is mono"
    assert ids["prose"] == ["kept: 2 files in the run folder"] and ids["folder"] == ["/work/shop/.runs/4"] and ids["copy"] == ["Copy the path"], "A-30: the files the run kept, and the run folder to copy"
    assert got["doneNoKept"] == {"result": False, "folder": 0}
    hand = got["hand"]
    assert hand["label"] == "Hand a file over" and hand["line"] == "this file will be visible to a run with the open network" and hand["hint"] == "To task #5. At most 25 MiB."
    assert hand["order"] == ["wb-drop-line", "wb-file"], "the line of the web task is shown before the file is chosen"
    assert got["handChosen"] == {"calls": 0, "name": "logo.png"}, "C-17: the file is chosen first and sent by the button"
    assert got["handSent"] == {"calls": [["p", 5, "logo.png", "AQID"]], "result": "Handed over: undefined (undefined bytes)"}, "the file goes to the review's task as base64; the stand-in client answers no path"
    assert got["handBad"] == "The file name may hold letters, digits, ., _ and -, at most 100 characters."
    assert got["nonWeb"] == {"control": True, "line": True} and got["refuses"] and got["unread"] and got["failedRead"]


def test_no_flex_row_of_the_cards_holds_free_text_without_wrap_and_the_done_card_wraps_its_result_on_its_own_line():
    css = _css()
    rules = _rules(css)
    family = re.compile(r"\.wb-(card|resolved|path-row|held|waits|lobby-resolved|lobby-notice|request-line|command|notice|verdicts)")
    # A flex row whose child is a text that can be long must wrap (flex-wrap: wrap), or give its text child `min-width: 0` with `overflow-wrap`. These rows hold
    # only controls or one text that already does the second: each is named with its reason.
    allowed = {
        ".wb-card-line": "one text node: an anonymous flex item that wraps with overflow-wrap: anywhere",
        ".wb-command-row": "the code child has min-width: 0 and white-space: pre-wrap; the Copy button is fixed",
        ".wb-waits-label": "a checkbox and a text span with min-width: 0 and overflow-wrap: anywhere",
        ".wb-plan-table td": "the phone's stacked row: a label and a value that wraps",
    }
    bad = []
    for selector, body in rules:
        if not re.search(r"display:\s*(inline-)?flex", body) or not family.search(selector):
            continue
        for one in [s.strip() for s in selector.split(",")]:
            if not family.search(one):
                continue
            if "flex-wrap: wrap" in body or one in allowed or any(one.endswith(a) for a in allowed):
                continue
            bad.append(one)
    assert not bad, f"a flex row of the cards with free text and no wrap: {bad}"
    by_selector = {s: b for s, b in rules}
    assert "flex-wrap: wrap" in by_selector[".wb-card-done"], "A-26: the done card wraps"
    result = by_selector[".wb-card-result"]
    assert "flex-basis: 100%" in result and "min-width: 0" in result, "A-26: the result takes its own line, full width, and can shrink"
    title = by_selector[".wb-resolved > .wb-card-done-title"]
    assert "flex: 1 1 8em" in title and "min-width: 0" in title and "white-space: normal" in title, "A-26: the done card's title takes the room left and wraps"
    order = [sel for sel, _ in rules]
    assert order.index(".wb-resolved > .wb-card-done-title") > order.index(".wb-resolved > .wb-muted"), "named after the rule it overrides"
    assert "flex-wrap: wrap" in by_selector[".wb-resolved"] and "overflow-wrap: anywhere" in by_selector[".wb-tl-title, .wb-resolved-title"], "the Floor's resolved line wraps too (R-38: its title wraps)"
    cards = (JS / "floor" / "cards.js").read_text(encoding="utf-8")
    assert 'h("div", { class: "mono", text: l })' in cards and 'class: "wb-card-line", text: l' in cards, "an id is mono, a sentence is prose"
    assert "lines.map((l) => h(\"div\", { class: \"mono\"" not in cards

# --- moved from test_interface_plates_meters.py ----------------------------------------------------------------------------------


@needs_node
def test_the_agent_tab_stops_and_supervises_with_two_buttons_shows_the_held_sentence_and_the_commands_the_service_gave(tmp_path):
    got = run_node_plates_meters(tmp_path, AGENT)
    assert got["select"] == 0, "the select is gone"
    assert got["labels"] == ["Stop agent", "Supervise"] and got["enabled"] == [False, False]
    assert "A wider mode is set in the terminal" in got["wider"], "a wider mode is the terminal's (R-35: the notice stands under the select)"
    assert got["standing"] != "Setting a mode changes the project's configuration. Every action of this page then refuses until you accept the new configuration in the terminal.", \
        "the standing notice would be false now: a narrowing is accepted at once"
    assert got["meters"] == ["Runs today 5 / 12", "Spend today $1.87 / $4.00", "Queued 1"] and got["meterTitles"][:2] == [True, True]
    assert got["stop"]["calls"] == [["setMode", "p", "engineering", "stopped"]], "one request with the word of the button"
    assert got["stop"]["refreshed"] == 1 and got["stop"]["commands"] == 0 and "Mode set to stopped" in got["stop"]["result"] and "Nothing works" not in got["stop"]["result"]
    assert got["afterStop"] == [True, True], "already stopped: both are off"
    assert got["supervised"] == [False, True], "Supervise is off at supervised; Stop agent is still on"
    assert got["supervise"] == [["setMode", "p", "engineering", "supervised"]]
    assert "changed while this call was running" in got["refused"]
    assert got["notAccepted"]["code"] == 0 and got["notAccepted"]["copy"] == 0 and got["notAccepted"]["text"].endswith("Accept the configuration in the terminal (the step below)."), \
        "A-62: the result points at the accept step and repeats no command: the step the tab draws while the configuration waits carries it"
    assert got["unaccepted"] == {"buttons": [True, True], "waitingLine": True, "meters": 3, "formHidden": False}, "not accepted: the panel keeps its data and its buttons are off"
    assert got["held"]["text"].startswith("Held: The service is not dispatching tasks.") and got["held"]["code"].startswith("uv run --with keyring==25.7.0 python3 /ck/runtime/cli.py run-next")
    assert got["held"]["copy"] == 1
    assert got["heldNoCommand"]["code"] == 0 and "spend" in got["heldNoCommand"]["text"]
    assert got["heldGone"] == 0


@needs_node
def test_the_agent_tab_shows_a_command_for_each_wider_mode_and_for_the_credential_as_the_service_gave_them(tmp_path):
    got = run_node_plates_meters(tmp_path, WIDER)
    modes = ["milestones", "autonomous", "autonomous-with-policy"]
    cmd = lambda m: f"python3 /ck/runtime/cli.py set-mode --project /work/shop --agent engineering --mode {m}"
    t = got["three"]
    assert t["line"] == "Run this command in the terminal: it sets the mode and accepts it." and t["label"] == "Mode" and t["labelFor"] is True, "R-35: the label over the select, the soft warn notice; A-62, M-21: one step, the service's command sets the mode and accepts it"
    assert t["options"] == modes and t["values"] == [cmd(m) for m in modes], "R-35: a select of the wider modes, each option holding the service's command verbatim, in its order"
    assert t["code"] == cmd("milestones") and got["chosen"] == cmd("autonomous"), "R-35: the command under the select follows the chosen mode"
    assert t["copies"] == 1 and t["icon"] is True and "pui-soft" in t["noteClass"] and "pui-warn" in t["noteClass"]
    assert got["top"] == {"wider": 0, "hidden": True, "codes": 0}, "an agent at the widest mode has nothing wider: nothing is drawn"
    assert got["none"]["codes"] == 0 and got["none"]["line"] == 1, "a service that gave no `wider` shows the sentence and builds no command"
    c = got["credential"]
    assert c["codes"] == ["uv run --with keyring==25.7.0 keyring set openhora user-a"] and c["copies"] == 1, "the command is the service's field, verbatim, with its own Copy"
    assert c["sentences"] == ["KEY_A"], "the Copy block is named by the credential"
    assert c["details"][-1] == "KEY_B: no username registered", "a credential with no username gets its name and the sentence, never a command with <username>"
    assert c["line"].startswith("Held: The reference model's credential is not set.")
    assert "The credential is in neither the environment nor the secret store" in c["text"], "the sentence stays as text"
    assert got["inline"] == {"codes": 0}, "nothing is taken out of a sentence"
    assert got["single"]["codes"] == ["python3 /ck/runtime/cli.py run-next --project /work/shop"], "a reason whose `next` is a command shows it as one"

# --- moved from test_interface_cards_fields.py -----------------------------------------------------------------------------------


def test_the_resolved_line_is_one_surface_with_the_panels_radius_and_no_seam():
    """A-5: header and body of the resolved accordion share one ground, and no `.wb-resolved*` rule squares a corner or sets a second ground."""
    rules = [(s, d) for s, d in css_rules() if re.search(r"\.wb-resolved", s)]
    assert rules, "the resolved line has rules"
    for selector, declarations in rules:
        assert declarations.get("border-radius", "").replace(" ", "") not in ("0", "0px"), f"{selector} squares a corner"
    # R-38: the resolved decisions are a timeline of accordions on the panel's own ground: the item paints none, only its summary on hover, in a token; a line joins the icons
    assert not [s for s, d in rules if ".wb-resolved-item" in s and any(p.startswith("background") for p in d)], "the timeline's item holds no ground of its own (R-38)"
    hover = next(d for s, d in css_rules() if s.strip() == ".wb-tl-acc > summary:hover")
    assert hover.get("background-color") == "var(--wb-ground)"
    line = next(d for s, d in css_rules() if s.strip() == ".wb-tl-item:not(:last-child)::before")
    assert line.get("background-color") == "var(--pui-border)" and line.get("width") == "1px"


def test_the_resolved_line_is_the_librarys_accordion_item_with_a_body():
    inbox = (JS / "floor" / "inbox.js").read_text(encoding="utf-8")
    assert 'class: "pui-timeline wb-tl"' in inbox and 'class: "wb-tl-acc wb-resolved-item"' in inbox, "R-38: an ordered timeline of accordions (the library's timeline, a details for each item)"
    assert "wb-resolved-body" in inbox, "the body has its own class, so that it can be padded and never given a ground"


@needs_node
def test_the_floors_close_button_works_from_a_desk_row_and_returns_the_focus_to_the_row(tmp_path):
    got = run_node_cards_fields(tmp_path, FLOOR)
    p = "#/p/0123456789ab/floor/engineering"
    assert got["deskOpened"]["viewer"] is True
    assert got["deskClose"] == {"hash": f"{p}/desk", "errors": []}, "Close did nothing: closeViewer was not defined"
    assert got["deskFocus"] == {"path": "docs/engineering/designs/order-history.md", "viewerShown": False}


@needs_node
def test_a_document_opened_from_an_inbox_card_closes_back_to_the_inbox_with_the_focus_on_its_open_link(tmp_path):
    got = run_node_cards_fields(tmp_path, FLOOR)
    p = "#/p/0123456789ab/floor/engineering"
    assert got["inboxLink"] == f"{p}/desk/docs%2Fengineering%2Fdesigns%2Forder-history.md"
    assert got["inboxClose"] == {"hash": f"{p}/inbox", "errors": []}
    assert got["inboxFocus"]["sameLink"] is True, got["inboxFocus"]


@needs_node
def test_a_document_opened_by_a_direct_hash_closes_to_the_desk_and_a_phones_dialog_closes_as_the_button_does(tmp_path):
    got = run_node_cards_fields(tmp_path, FLOOR)
    p = "#/p/0123456789ab/floor/engineering"
    assert got["directClose"] == {"hash": f"{p}/desk", "errors": []}
    assert got["phoneOpen"] is True and got["phoneClose"] == f"{p}/inbox", "the dialog's close goes back to the Inbox it was opened from"
    assert got["selectedClose"] == {"hash": f"{p}/inbox/7", "errors": []}, "a document opened from a selected decision closes back to that decision"
    assert got["agentClose"] == {"hash": f"{p}/agent", "errors": []}, "a document opened from the Agent tab closes back to the Agent tab"


@needs_node
def test_the_focus_on_an_open_link_survives_the_draws_that_move_its_card(tmp_path):
    got = run_node_cards_fields(tmp_path, FOCUS)
    assert got["afterFirstCard"]["focusOnA"] is True
    assert got["afterSecondCard"]["links"] == ["Open docs/a.md", "Open docs/b.md"]
    assert got["afterSecondCard"]["focusOnA"] is True, "a second card was drawn after the focus was set: the link must still have it"


# =================================================================================================================================
# R4-A4: the Floor as floor.html of round 4 draws it (R-31 to R-40). New tests; each states the ruling it checks.
# =================================================================================================================================

STRUCTURE = r"""
import { FakeNode, settle, find, all } from "@FAKE@";
import { setToken } from "@JS@/token.js";
import * as fm from "@JS@/floor-model.js";
import { createAgentTab } from "@JS@/floor/agent-tab.js";
import { createInbox } from "@JS@/floor/inbox.js";
import { createTasksTab } from "@JS@/floor/tasks-tab.js";
import { createDeskTab } from "@JS@/floor/desk-tab.js";
import { createViewer } from "@JS@/floor/viewer.js";
import { boardNode } from "@JS@/scene/plates.js";
import { ICONS } from "@JS@/frame/icons.js";

setToken("t".repeat(40));
const NOW = new Date("2026-10-10T12:00:00Z");
const ago = (m) => new Date(NOW.getTime() - m * 60000).toISOString();
const P = "0123456789ab";
const text = (n) => (n ? n.textContent : null);
const cls = (n) => (n.attrs.class || "").split(/\s+/).filter(Boolean);
const out = {};

// --- the model: how long, not since when (R-8), the board's lines (R-32), the head (C-6)
const task = (id, state, extra = {}) => ({ id, key: `k${id}`, title: `Task ${id}`, skill: "implement-change", state, note: null, agent: "engineering", requestId: 2, waiting_for: [], ...extra });
const agent = { name: "engineering", pack: "x", enabled: true, mode: "supervised", acting_mode: "supervised", max_runs_per_day: 6, max_usd_per_day: 2, runs_today: 3, usd_today: 0.03, runs_without_cost: 0, queued: 0, held: 0,
  usd_recorded: 0.03, usd_reserved: 0.5, wider: [{ mode: "milestones", command: "python3 /ck/cli.py set-mode --mode milestones" }, { mode: "autonomous", command: "python3 /ck/cli.py set-mode --mode autonomous" }] };
const run = { id: 118, skill: "implement-change", skill_version: "1.4.0", model: "reference", status: "running", attempts: 1, started_at: ago(12), tokens: 48210, cost_usd: null, duration_ms: null };
const body = (t, runs = [run], pending = []) => ({ task: { id: t.id, updated_at: ago(12) }, runs, pending, drop: { web: true, takes: true, line: "this file will be visible to a run with the open network" } });
const snap = (tasks, pending = []) => ({ projects: [{ id: P, name: "northwind-shop", config: { accepted: true } }], details: { [P]: { status: { requests: [{ id: 2, title: "Spring", state: "running", tasks }], pending, held: [] }, agents: [agent] } }, tasks: {}, loaded: true });
const view = (tasks, bodies, pending = []) => fm.floor(snap(tasks, pending), P, "engineering", bodies);
const running = view([task(52, "running"), task(53, "planned", { waiting_for: [] })], { 52: body(task(52, "running")) });
out.model = { state: fm.stateRow("working", 0, running.runningBody, NOW).line, stateNoRun: fm.stateRow("working", 0, null, NOW).line, header: running.header,
  board: fm.boardOf(running, NOW), sub: [fm.currentSub(task(52, "running"), body(task(52, "running")), [], NOW), fm.currentSub(task(57, "waiting"), body(task(57, "waiting")), [{ task_id: 57, created_at: ago(2880) }], NOW),
    fm.currentSub(task(52, "ready"), body(task(52, "ready")), [], NOW), fm.currentSub(task(52, "done"), body(task(52, "done")), [], NOW)],
  unknownCost: fm.boardOf(view([task(52, "running")], { 52: body(task(52, "running"), [{ ...run, cost_usd: 0.0123 }]) }), NOW).lines[1] };

// --- the Agent tab (R-35, R-36, R-8, floor.html (b) 1 to 3)
const tab = createAgentTab({ project: P, agent: "engineering", api: { setMode: async () => ({}), retry: async () => ({}), goAhead: async () => ({}), handOver: async () => ({}) }, refresh() {}, now: () => NOW });
tab.update(running);
await settle();
const rowsOf = (n) => n.children.map((c) => cls(c)[0] || c.tagName);
out.agent = {
  order: rowsOf(tab.el), state: text(find(tab.el, ".wb-state-row")), pips: all(tab.el, ".wb-pip").length, plate: text(find(tab.el, ".wb-mode-plate")),
  meters: all(tab.el, ".wb-meter-cell").map((c) => [text(find(c, ".wb-meter-label")), text(find(c, ".wb-meter-value")), all(c, ".wb-meter").length, text(find(c, ".wb-note"))]),
  reserved: all(tab.el, ".wb-meter-reserved").length,
  cur: { head: text(find(tab.el, ".wb-current .wb-cur-head")), sub: text(find(tab.el, ".wb-current .wb-cur-sub")), run: all(tab.el, ".wb-current dl.wb-run").length, card: cls(find(tab.el, ".wb-current")).includes("pui-card"),
    heading: text(find(tab.el, ".wb-section .wb-sec-head")) },
  other: text(find(tab.el, ".wb-other .wb-cur-head")),
  wider: { label: text(find(tab.el, ".wb-wider-label")), options: all(tab.el, ".wb-wider-box option").map(text), code: text(find(tab.el, ".wb-wider-code")), note: cls(find(tab.el, ".wb-wider-note")).join(" "), copy: text(find(tab.el, "button.wb-copy")) },
  hand: { heading: text(find(tab.el, ".wb-hand .wb-sec-head")), choose: text(find(tab.el, ".wb-hand button.wb-hand-choose")), input: cls(find(tab.el, ".wb-hand input")).join(" "), hint: text(find(tab.el, ".wb-hand .wb-hint")), name: all(tab.el, ".wb-hand-name").length, send: all(tab.el, ".wb-hand-send").length },
};
const input = find(tab.el, ".wb-hand input.wb-file");
input.files = [{ name: "sale-banner.png", size: 3, arrayBuffer: async () => new ArrayBuffer(3) }];
(input.listeners.change || []).forEach((fn) => fn());
await settle();
out.agent.picked = { name: text(find(tab.el, ".wb-hand-name")), send: text(find(tab.el, ".wb-hand-send")) };
find(tab.el, "button.wb-hand-choose").click();   // the visible button opens the file input
const idle = fm.floor(snap([]), P, "engineering", {});
tab.update(idle);
await settle();
out.agent.idle = { state: text(find(tab.el, ".wb-state-row")), current: text(find(find(tab.el, ".wb-section"), ".wb-empty-line")) };

// --- the Inbox: the timeline of resolved decisions (R-38), Plain text in a card's head (R-34), three lines (R-37)
const row = (id, kind, resolution, answer, hours) => ({ id, kind, status: "resolved", resolution, answer, title: `Decision ${id}`, created_at: new Date(NOW.getTime() - hours * 3600e3).toISOString(), resolved_at: new Date(NOW.getTime() - hours * 3600e3).toISOString() });
const lines = fm.resolvedLines({ 4: { task: { id: 4 }, runs: [], pending: [row(1, "question", "answered", "The price with tax.", 48), row(2, "review", "released", null, 72), row(3, "effect", "rejected", "Too early.", 120)] } }, [4], NOW);
out.lines = lines.map((l) => [l.icon, l.tone]);
const item = (id, kind, extra = {}) => ({ id, kind, title: `Card ${id}`, body: "A **bold** body", payload: {}, payload_sha256: kind === "effect" ? "e".repeat(64) : null, status: "open", actions: kind === "question" ? ["answered"] : kind === "review" ? ["released", "answered"] : ["approved", "rejected"], agent: "engineering", task_id: 4, created_at: ago(120), ...extra });
const items = new Map([[11, item(11, "question")], [12, item(12, "review", { payload: { returned: [], kept: [] }, run_id: 118 })], [13, item(13, "effect")], [14, item(14, "acceptance", { actions: ["accepted", "rejected"] })]]);
globalThis.fetch = async (url) => { const id = Number(String(url).match(/pending\/(\d+)/)[1]); return { ok: true, status: 200, json: async () => items.get(id) }; };
const inbox = createInbox({ project: P, now: () => NOW, api: {}, refresh() {}, links: { open: () => "#", floor: () => "#", lobby: () => "#", parent: () => "#" } });
inbox.update({ decisions: [11, 12, 13, 14].map((id) => ({ id, task_id: 4, kind: items.get(id).kind, agent: "engineering" })), requests: [], resolved: lines, selected: null, loading: false });
await settle();
const cards = all(inbox.el, "article.wb-card");
out.cards = cards.map((c) => [text(find(c, ".wb-card-title")), all(find(c, ".wb-card-head"), "button.wb-card-plain").length, find(c, "textarea") ? find(c, "textarea").attrs.rows : null]);
const q = cards[0];
const plain = find(q, ".wb-card-head button.wb-card-plain");
out.plain = { label: text(plain), pressed: plain.attrs["aria-pressed"], before: all(q, ".wb-md.is-plain").length };
plain.click();
const q2 = all(inbox.el, "article.wb-card")[0];
out.plain.after = { pressed: find(q2, ".wb-card-plain").attrs["aria-pressed"], plainBody: text(find(q2, ".wb-md.is-plain")), strong: all(q2, "strong").length };
find(q2, ".wb-card-plain").click();   // back: one choice for the session
const tl = find(inbox.el, "ol.wb-tl");
out.timeline = { aria: tl.attrs["aria-label"], items: all(tl, "li.wb-tl-item").length, icons: all(tl, ".wb-tl-icon .wb-icon").map((i) => cls(i).find((c) => /^wb-icon-/.test(c))), open: all(tl, "details").map((d) => d.open === true || "open" in d.attrs),
  firstSub: text(all(tl, ".wb-tl-sub")[0]), firstBody: all(find(tl, ".wb-tl-body"), "p").map(text), said: text(find(tl, ".wb-res-said")), heading: text(find(inbox.el, ".wb-resolved-tl .wb-sec-head")) };

// --- the Tasks tab (R-39)
const tasks = [task(52, "running"), task(53, "planned"), task(48, "done"), task(41, "done"), task(60, "failed"), task(61, "cancelled")];
const tt = createTasksTab({ project: P, now: () => NOW, refresh() {}, api: { retry: async () => ({}), goAhead: async () => ({}) }, links: { request: () => "#", inbox: () => "#", open: () => "#" } });
globalThis.fetch = async () => ({ ok: true, status: 200, json: async () => body(task(52, "running")) });
tt.update({ tasks, requests: [{ id: 2, title: "Spring" }], pending: [], loading: false, reload: 1, unaccepted: false });
await settle();
const groups = all(tt.el, "details.wb-task-group");
out.tasks = { groups: groups.map((g) => [text(find(g, ".wb-group-name")), cls(find(g, ".wb-group-tile")).filter((c) => /^pui-(theme|warn|muted|success|error)$/.test(c))[0], cls(find(g, ".wb-group-tile")).includes("is-none"), text(find(g, ".pui-badge")), cls(find(g, ".wb-group-tile .wb-icon")).find((c) => /^wb-icon-/.test(c))]),
  open: groups.map((g) => "open" in g.attrs || g.open === true) };
const toggle = find(tt.el, "button.wb-task-toggle");
out.tasks.row = { n: text(find(toggle, ".wb-task-num")), title: text(find(toggle, ".wb-task-title")), chip: text(find(toggle, ".pui-chip")), mark: all(toggle, ".wb-task-mark .wb-icon-chevron-down").length, expanded: toggle.attrs["aria-expanded"], bodyHidden: "hidden" in find(tt.el, ".wb-task-body").attrs };
toggle.click();
await settle();
out.tasks.opened = { expanded: find(tt.el, "button.wb-task-toggle").attrs["aria-expanded"], bodyHidden: "hidden" in find(tt.el, ".wb-task-body").attrs, runs: all(tt.el, "dl.wb-run").length };

// --- the Desk (R-40): two-line rows
const docs = [{ path: "docs/brand/voice.md", owner: "brand-voice", agent: "brand", size: 3174, modified_at: "2026-10-10T11:02:00Z", kind: "markdown", bound: true }, { path: "docs/brand/shot.png", owner: null, agent: null, size: 49152, modified_at: "2026-10-09T11:02:00Z", kind: "image", bound: false }];
const desk = createDeskTab({ project: P, agent: "brand", open() {} });
desk.update({ documents: docs, truncated: false, loading: false, error: null });
const lobbyDesk = createDeskTab({ project: P, agent: "planning", open() {}, agentColumn: true });
lobbyDesk.update({ documents: docs, truncated: false, loading: false, error: null });
const first = find(desk.el, "li.wb-desk-row");
out.desk = { list: cls(find(desk.el, "ul.wb-desk-list")).join(" "), aria: find(desk.el, "ul.wb-desk-list").attrs["aria-label"], rows: all(desk.el, "li.wb-desk-row").length, table: all(desk.el, "table").length, path: text(find(first, "button.wb-path-button")), bound: text(find(first, ".wb-chip-12")).trim(),
  meta: text(find(first, ".wb-desk-meta")), agents: all(desk.el, ".wb-desk-agent").length, lobby: all(lobbyDesk.el, "li.wb-desk-row .wb-desk-agent").map(text), lobbyAria: find(lobbyDesk.el, "ul.wb-desk-list").attrs["aria-label"] };

// --- the viewer's head: the path and the size line at the left, `Plain text` and `Close` at the right
globalThis.fetch = async (url) => ({ ok: true, status: 200, json: async () => ({ path: String(url).includes("md") ? "docs/a.md" : "docs/a.txt", text: "# A\n\nbody", size: 9, modified_at: "2026-10-10T11:02:00Z" }) });
const viewer = createViewer({ onClose() {}, listed: () => ({ kind: "markdown" }) });
await viewer.load(P, "docs/a.md");
const tools = (v) => all(find(v.el, ".wb-viewer-head"), "button").map(text);
out.viewer = { md: tools(viewer), left: all(find(viewer.el, ".wb-viewer-head"), ".wb-viewer-path").map(text), line: text(find(viewer.el, ".wb-viewer-line")), bodyHasToggle: all(find(viewer.el, ".wb-viewer-body"), "button").length };
const txt = createViewer({ onClose() {}, listed: () => ({ kind: "text" }) });
await txt.load(P, "docs/a.txt");
out.viewer.txt = tools(txt);

// --- the board's label (R-32) and the icons the screen draws
const label = boardNode({ title: "#52 Implement the change · current task", lines: ["skill x · Running · for 12 min", "run #118 Running"], dot: "theme" });
out.board = { cls: cls(label), title: text(find(label, ".wb-fp-name")), lines: all(label, ".wb-wb-line").map(text), dot: cls(find(label, ".wb-dot")).includes("is-theme") };
out.icons = ["triangle-alert", "list", "ban", "activity", "circle-alert", "clock", "check", "x", "chevron-down"].map((n) => ICONS.includes(n));
console.log(JSON.stringify(out));
process.exit(0);
"""


@needs_node
def test_the_floors_models_say_how_long_a_task_has_run_the_board_is_the_r32_label_and_the_head_names_the_agent_once(tmp_path):
    got = run_node(tmp_path, STRUCTURE)
    m = got["model"]
    assert m["state"] == "Running for 12 min" and m["stateNoRun"] == "Running", "R-8: how long, not since when"
    assert m["header"] == {"title": "Engineering agent", "sub": "floor 1 · Running", "icon": "building-2"}, "C-6, floor.html"
    assert m["board"]["title"] == "#52 Task 52 · current task" and m["board"]["lines"][0] == "skill implement-change · Running · for 12 min", "R-32: the title, then the skill, the state and how long"
    assert m["board"]["lines"][1] == "run #118 Running · attempt 1 · 48,210 tokens · unknown", "R-32: then the run; a cost not recorded reads unknown"
    assert m["unknownCost"] == "run #118 Running · attempt 1 · 48,210 tokens · $0.0123"
    assert [s["when"] for s in m["sub"]] == ["for 12 min", "asked 2 d ago", "queued 12 min ago", "12 min ago"] and m["sub"][0]["skill"] == "skill implement-change"
    assert got["icons"] == [True] * 9, "the three new icons are registered, with the six the groups and the timeline draw"


@needs_node
def test_the_agent_tab_is_the_page_s_rows_a_select_of_wider_modes_the_current_card_and_the_dashed_box(tmp_path):
    got = run_node(tmp_path, STRUCTURE)["agent"]
    assert got["order"] == ["wb-state-box", "wb-mode-row", "wb-mode-form", "wb-notice-card", "wb-result-box", "wb-wider-modes", "wb-agent-body"], "floor.html: state, mode, the two buttons, the standing line, the result, the wider modes, then the rest"
    assert got["state"] == "WorkingRunning for 12 min" and got["pips"] == 0 and got["plate"] == "supervised", "R-8, C-5: the word, no pips"
    names = [[m[0], m[1], m[2], m[3]] for m in got["meters"]]
    assert names == [["Runs today", "3 / 6", 1, None], ["Spend today", "$0.03 / $2.00", 1, "$0.03 recorded · up to $0.50 reserved"], ["Queued", "0", 0, None]], "R-36, R-6: name, figure, a track; Queued last with no track"
    assert got["reserved"] == 1
    assert got["cur"]["heading"] == "Current task" and got["cur"]["head"].startswith("#52 Task 52") and got["cur"]["sub"] == "skill implement-change · for 12 min" and got["cur"]["run"] == 1 and got["cur"]["card"]
    assert got["other"].startswith("#53 Task 53")
    w = got["wider"]
    assert w["label"] == "Mode" and w["options"] == ["milestones", "autonomous"] and w["code"].endswith("--mode milestones") and w["copy"] == "Copy" and "pui-soft" in w["note"] and "pui-warn" in w["note"], "R-35"
    h = got["hand"]
    assert h["heading"] == "Hand a file over" and h["choose"] == "Choose a file" and "wb-file" in h["input"] and h["hint"] == "To task #52. At most 25 MiB." and h["name"] == 0 and h["send"] == 0
    assert got["picked"] == {"name": "sale-banner.png", "send": "Hand over to task #52"}, "README (b) 3: the chosen name, then the button"
    assert got["idle"] == {"state": "IdleWaiting for the next task", "current": "This agent has no task yet."}


@needs_node
def test_the_inbox_resolved_decisions_are_a_timeline_of_accordions_and_a_card_that_renders_markdown_has_plain_text_in_its_head(tmp_path):
    got = run_node(tmp_path, STRUCTURE)
    assert got["lines"] == [["check", "pui-success pui-soft"], ["check", "pui-success pui-soft"], ["x", "pui-muted pui-soft"]], "R-38: a check for an outcome, a cross for a rejection"
    t = got["timeline"]
    assert t["aria"] == "Resolved decisions, newest first" and t["items"] == 3 and t["heading"] == "Resolved"
    assert t["icons"] == ["wb-icon-check", "wb-icon-check", "wb-icon-x"] and t["open"] == [True, False, False], "the newest is open until the person chooses"
    assert t["firstSub"] == "Question answered · 2 d ago" and t["firstBody"][0].startswith("Resolved 2026-10-08") and t["said"] == "Your answerThe price with tax.", "R-38: the date and what the person said"
    by = {c[0]: c[1:] for c in got["cards"]}
    assert by["Card 11"] == [1, "3"] and by["Card 12"] == [1, "3"] and by["Card 14"][0] == 1, "R-34: the question, the review and the acceptance render Markdown and carry the button; R-37: three lines"
    assert by["Card 13"] == [0, "None"] or by["Card 13"][0] == 0, "an effect is never rendered: no Plain text"
    p = got["plain"]
    assert p["label"] == "Plain text" and p["pressed"] == "false" and p["before"] == 0
    assert p["after"] == {"pressed": "true", "plainBody": "A **bold** body", "strong": 0}, "R-34: the card's text as it came, in the card"


@needs_node
def test_the_tasks_tab_has_a_bordered_group_with_its_states_icon_and_each_task_is_an_accordion_the_desk_is_two_line_rows(tmp_path):
    got = run_node(tmp_path, STRUCTURE)
    t = got["tasks"]
    assert t["groups"][0] == ["Running", "pui-theme", False, "1", "wb-icon-activity"] and t["groups"][1] == ["Waiting for you", "pui-warn", True, "0", "wb-icon-circle-alert"]
    assert [g[0] for g in t["groups"]] == ["Running", "Waiting for you", "Ready (queued)", "Planned or blocked", "Done", "Failed", "Cancelled"]
    assert [g[4] for g in t["groups"]] == [f"wb-icon-{n}" for n in ("activity", "circle-alert", "list", "clock", "check", "x", "ban")] and [g[1] for g in t["groups"]][4:] == ["pui-success", "pui-error", "pui-muted"], "R-39: the state's icon in the state's colour"
    assert [g[2] for g in t["groups"]] == [False, True, True, False, False, False, False] and t["open"] == [True, False, False, True, True, True, True], "an empty group is its header, faint"
    assert t["row"] == {"n": "#52", "title": "Task 52", "chip": "Running", "mark": 1, "expanded": "false", "bodyHidden": True}, "R-39: number, title, state and a marker"
    assert t["opened"] == {"expanded": "true", "bodyHidden": False, "runs": 1}
    d = got["desk"]
    assert d["rows"] == 2 and d["table"] == 0 and "pui-card" in d["list"] and d["aria"] == "Documents, newest first", "R-40: a list of rows, not a table"
    assert d["path"] == "docs/brand/voice.md" and d["bound"] == "bound to a decision" and d["meta"] == "brand-voice · 3.1 KB · Markdown · 2026-10-10 11:02" or d["meta"].startswith("brand-voice · 3.1 KB · Markdown ·"), "the path, then the owner skill, the size and kind, the time"
    assert d["agents"] == 0 and d["lobby"] == ["Brand", "Lobby"] and d["lobbyAria"] == "Documents of the project, newest first", "R-47: the Lobby's rows carry the agent as a badge"


@needs_node
def test_the_viewer_head_has_the_path_and_the_size_at_the_left_and_the_tools_at_the_right_and_the_board_label_is_the_pages(tmp_path):
    got = run_node(tmp_path, STRUCTURE)
    v = got["viewer"]
    assert v["md"] == ["Plain text", "Close"] and v["txt"] == ["Close"] and v["bodyHasToggle"] == 0, "floor.html: Plain text beside Close in the head, only for a Markdown document"
    assert v["left"] == ["docs/a.md"] and v["line"].startswith("9 B, modified ")
    b = got["board"]
    assert "wb-wallboard" in b["cls"] and "wb-label" in b["cls"] and b["title"] == "#52 Implement the change · current task" and b["lines"] == ["skill x · Running · for 12 min", "run #118 Running"] and b["dot"], "R-32"


def test_the_floors_stylesheet_draws_the_rows_the_three_line_fields_the_segmented_tabs_and_no_literal_colour():
    css = interface_css()
    rules = {}
    for selector, declarations in css_rules():
        rules.setdefault(selector.strip(), declarations)     # the first rule of a selector: a phone's override comes later
    assert "min-height: 76px" in "".join(f"{k}:{v}" for k, v in rules.get("textarea.wb-field-input", {}).items()) or rules.get("textarea.wb-field-input", {}).get("min-height") == "76px", "R-37"
    assert rules[".wb-meters"].get("grid-template-columns") == "minmax(0, 1fr)" and rules[".wb-meter-cell"].get("grid-template-columns") == "minmax(0, 1fr) auto", "R-36: rows"
    assert rules[".wb-floor-head"].get("border-bottom") == "0" and rules[".wb-tabbar > .wb-tabs, .wb-tabbar > .wb-tablist"].get("flex") == "0 1 auto", "R-33: no line under the head; the track is as wide as its tabs"
    assert rules[".wb-hand"].get("border") == "1px dashed var(--pui-muted)", "README (b) 3: a dashed box"
    assert rules[".wb-desk-row"].get("grid-template-columns") == "minmax(0, 1fr) auto" and rules[".wb-desk-meta"].get("grid-column") == "1 / -1", "R-40"
    assert "uppercase" in rules[".wb-task-group-name, .wb-group-name"].get("text-transform", ""), "R-39: the group's name in small capitals"
    floor = (INTERFACE / "css" / "floor.css").read_text(encoding="utf-8")
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(", floor), "tokens only"
    assert "max-width: 639px" not in floor and "min-width: 640px" not in floor, "M-3: the phone layout goes to 899 px and there is no docked band"
    assert "max-width: 899px" in floor
    assert '.wb-frame[data-screen="floor"] .wb-bottom-bar .wb-crumb-item:first-child' in floor, "README Floor (b) 6: on a phone the crumbs drop City"
    assert ".wb-floor-head > .wb-kpi-tile { display: inline-grid; }" in floor, "the head's tile stays on a phone, where the frame hides the KPI tiles' icons"


# --- the review of the PR: the soft notices on every path, Copy's fallback, one choice of Plain text for every card, the toggle of the newest line ---------------------------

REVIEW_FIXES = r"""
import { FakeNode, settle, find, all } from "@FAKE@";
import { setToken } from "@JS@/token.js";
import * as fm from "@JS@/floor-model.js";
import { notice } from "@JS@/floor/widgets.js";
import { createAgentTab } from "@JS@/floor/agent-tab.js";
import { createInbox } from "@JS@/floor/inbox.js";
import { createCard } from "@JS@/floor/cards.js";

setToken("t".repeat(40));
const NOW = new Date("2026-10-10T12:00:00Z");
const ago = (m) => new Date(NOW.getTime() - m * 60000).toISOString();
const P = "0123456789ab";
const text = (n) => (n ? n.textContent : null);
const cls = (n) => (n.attrs.class || "").split(/\s+/).filter(Boolean);
const out = {};

// every notice path: the library's soft style in the state's colour, and the old classes kept
out.notice = ["error", "warn", "info"].map((k) => { const n = notice("text", k); return [cls(n), n.attrs.role || null]; });

const agentRow = { name: "engineering", pack: "x", enabled: true, mode: "milestones", acting_mode: "milestones", max_runs_per_day: 6, max_usd_per_day: 2, runs_today: 0, usd_today: 0, runs_without_cost: 0, queued: 0, held: 0,
  wider: [{ mode: "autonomous", command: "python3 /ck/cli.py set-mode --mode autonomous" }, { mode: "autonomous-with-policy", command: "python3 /ck/cli.py set-mode --mode autonomous-with-policy" }] };
const task = { id: 4, key: "k", title: "T", skill: "s", state: "ready", note: null, agent: "engineering", requestId: 1, waiting_for: [] };
const view = () => fm.floor({ projects: [{ id: P, name: "n", config: { accepted: true } }], details: { [P]: { status: { requests: [{ id: 1, title: "R", state: "ready", tasks: [task] }], pending: [], held: [] }, agents: [agentRow] } }, tasks: {}, loaded: true }, P, "engineering", {});
let reply = async () => ({ mode: "supervised", accepted: true });
const tab = createAgentTab({ project: P, agent: "engineering", api: { setMode: (...a) => reply(...a), retry: async () => ({}), goAhead: async () => ({}), handOver: async () => ({}) }, refresh() {}, now: () => NOW });
tab.update(view());
await settle();
const press = async () => { find(tab.el, "button[data-key=stop-agent]").click(); await settle(); };
reply = async () => { throw Object.assign(new Error("refused"), { name: "ApiError", status: 500 }); };
await press();
out.failed = cls(find(tab.el, ".wb-form-error .wb-notice-card"));
reply = async () => ({ mode: "stopped", accepted: true });
await press();
out.accepted = cls(find(tab.el, ".wb-result-box .wb-notice-card"));
reply = async () => ({ mode: "stopped", accepted: false, next: "python3 /ck/cli.py accept-config --sha256 " + "a".repeat(64) });
await press();
out.unaccepted = cls(find(tab.el, ".wb-result-box .wb-notice-card"));
// a card whose request failed
const item = { id: 11, kind: "question", title: "Q", body: "body", payload: {}, status: "open", actions: ["answered"], agent: "engineering", task_id: 4, created_at: ago(5) };
const card = createCard(item, { project: P, now: () => NOW, api: { answer: async () => { throw Object.assign(new Error("nope"), { name: "ApiError", status: 500 }); } }, requestIds: new Set(), links: { floor: () => "#", lobby: () => "#", open: () => "#" }, changed() {}, gone() {} });
find(card.el, "textarea").value = "an answer";
find(card.el, "textarea").listeners.input.forEach((fn) => fn());
find(card.el, "button[data-word=answered]").click();
await settle();
out.cardError = cls(find(card.el, ".wb-notice-card"));

// R-35: Copy writes the chosen option's command whole; a refused clipboard selects the command
const written = [];
Object.defineProperty(globalThis, "navigator", { value: { clipboard: { writeText: async (v) => { written.push(v); } } }, configurable: true });
const select = find(tab.el, ".wb-wider-box select");
select.value = select.children[1].attrs.value;
select.listeners.change.forEach((fn) => fn());
find(tab.el, "button.wb-copy[data-key=wider-copy]").click();
await settle();
out.copy = { written, label: text(find(tab.el, "button.wb-copy[data-key=wider-copy]")), status: text(find(tab.el, ".wb-wider-box .wb-copy-status")), order: find(tab.el, ".wb-wider-box").children.map((c) => ["wb-wider-row", "wb-command-code", "wb-wider-note", "wb-copy-status"].find((k) => cls(c).includes(k))) };
let selected = null;
Object.defineProperty(globalThis, "navigator", { value: { clipboard: { writeText: async () => { throw new Error("refused"); } } }, configurable: true });
document.createRange = () => ({ selectNodeContents: (n) => { selected = n; } });
globalThis.window.getSelection = () => ({ removeAllRanges() {}, addRange() {} });
document.execCommand = () => false;
find(tab.el, "button.wb-copy[data-key=wider-copy]").click();
await settle();
out.fallback = { selected: selected === find(tab.el, ".wb-wider-code"), selectedText: selected ? selected.textContent : null, status: text(find(tab.el, ".wb-wider-box .wb-copy-status")) };

// the file input is described by the hint (and by the web line)
const input = find(tab.el, ".wb-hand input.wb-file");
const ids = (input.attrs["aria-describedby"] || "").split(" ").filter(Boolean);
out.describedby = { ids: ids.length, found: ids.map((id) => all(tab.el, `#${id}`).length) };

// R-34: two Markdown cards, one choice
const items = new Map([[21, { ...item, id: 21, title: "First", body: "A **bold** one" }], [22, { ...item, id: 22, title: "Second", body: "Another **bold** one" }]]);
globalThis.fetch = async (url) => ({ ok: true, status: 200, json: async () => items.get(Number(String(url).match(/pending\/(\d+)/)[1])) });
const inbox = createInbox({ project: P, now: () => NOW, api: {}, refresh() {}, links: { open: () => "#", floor: () => "#", lobby: () => "#", parent: () => "#" } });
const rows = (resolved) => ({ decisions: [21, 22].map((id) => ({ id, task_id: 4, kind: "question", agent: "engineering" })), requests: [], resolved, selected: null, loading: false });
const line = (id, hours) => ({ id, kind: "question", resolution: "answered", text: "Question answered", tone: "pui-success pui-soft", icon: "check", title: `Line ${id}`, stamp: ago(hours * 60), age: `${hours} h`, when: "2026-10-09 10:00", said: null });
inbox.update(rows([line(1, 5), line(2, 6)]));
await settle();
const cardsOf = () => all(inbox.el, "article.wb-card");
const state = () => cardsOf().map((c) => [find(c, ".wb-card-plain").attrs["aria-pressed"], all(c, ".wb-md.is-plain").length]);
out.two = { before: state() };
find(cardsOf()[0], ".wb-card-plain").click();
out.two.after = state();
find(cardsOf()[1], ".wb-card-plain").click();
out.two.back = state();

// A4-4: the toggle the browser fires for the newest line must not keep it open when a newer one arrives
const detailsOf = () => all(inbox.el, "details.wb-resolved-item");
for (const d of detailsOf()) { d.open = "open" in d.attrs; (d.listeners.toggle || []).forEach((fn) => fn()); }
inbox.update(rows([line(3, 1), line(1, 5), line(2, 6)]));
out.lines = detailsOf().map((d) => "open" in d.attrs);
detailsOf()[2].open = true; detailsOf()[2].listeners.toggle.forEach((fn) => fn());   // the person opens an older line: it stays open
inbox.update(rows([line(4, 0), line(3, 1), line(1, 5), line(2, 6)]));
out.kept = detailsOf().map((d) => "open" in d.attrs);
console.log(JSON.stringify(out));
process.exit(0);
"""


@needs_node
def test_every_notice_path_of_the_floor_is_the_soft_style_with_the_old_classes_kept(tmp_path):
    got = run_node(tmp_path, REVIEW_FIXES)
    error, warn, info = got["notice"]
    assert error == [["notice", "pui-soft", "pui-error", "wb-notice-card", "is-error"], "alert"] and warn == [["notice", "pui-soft", "pui-warn", "wb-notice-card", "is-warn"], "status"], "R-11"
    assert info[0] == ["notice", "pui-soft", "pui-muted", "wb-notice-card"] and info[1] is None
    for key in ("failed", "cardError"):
        assert {"notice", "pui-soft", "pui-error"} <= set(got[key]), f"{key}: an error on the Agent tab or on a card is the soft error style"
    assert {"notice", "pui-soft", "pui-success"} <= set(got["accepted"]) and {"notice", "pui-soft", "pui-warn", "is-warn"} <= set(got["unaccepted"]), "the mode result"
    js = INTERFACE / "js"
    for path in (js / "floor").glob("*.js"):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "wb-notice-card" in line and "class:" in line:
                assert "notice pui-soft" in line or 'h("p", { class: "wb-notice-card"' in line, f"{path.name}:{lineno} builds a notice that is not the soft style"


@needs_node
def test_copy_writes_the_chosen_modes_command_whole_and_a_refused_clipboard_selects_it(tmp_path):
    got = run_node(tmp_path, REVIEW_FIXES)
    assert got["copy"]["written"] == ["python3 /ck/cli.py set-mode --mode autonomous-with-policy"] and got["copy"]["label"] == "Copied" and got["copy"]["status"] == "Copied to the clipboard."
    assert got["copy"]["order"] == ["wb-wider-row", "wb-command-code", "wb-wider-note", "wb-copy-status"], "the block's DOM order is its visual order"
    assert got["fallback"]["selected"] is True and got["fallback"]["selectedText"].endswith("--mode autonomous-with-policy"), "a refused clipboard selects the command"
    assert "Select the command" in got["fallback"]["status"]
    assert got["describedby"] == {"ids": 1, "found": [1]} or got["describedby"]["ids"] >= 1 and all(n == 1 for n in got["describedby"]["found"]), "the file input is described by the hint (and the web line)"


@needs_node
def test_plain_text_is_one_choice_for_every_markdown_card_and_the_newest_resolved_line_does_not_keep_an_older_one_open(tmp_path):
    got = run_node(tmp_path, REVIEW_FIXES)
    two = got["two"]
    assert two["before"] == [["false", 0], ["false", 0]]
    assert two["after"] == [["true", 1], ["true", 1]], "R-34: flipping it on one card draws every card"
    assert two["back"] == [["false", 0], ["false", 0]]
    assert got["lines"] == [True, False, False], "a toggle event fired for the line that was newest does not keep it open beside the newer one"
    assert got["kept"] == [True, False, False, True], "a line the person opened stays open (here the oldest), the newest is open by default"


def test_the_board_label_is_not_drawn_on_a_phone_and_a_card_head_wraps_instead_of_cutting():
    floor = (INTERFACE / "css" / "floor.css").read_text(encoding="utf-8")
    phone = floor[floor.rindex("@media (max-width: 899px) {\n  .wb-card-plain"):]
    assert ".wb-wallboard { display: none; }" in phone, "floor.html draws no board label at 375 px: the label would lie under the tracking bar and the tiles"
    assert ".wb-card-plain { flex: 1 1 100%;" in phone, "Plain text has a row of its own on a phone"
    meta = next(d for s, d in css_rules() if s.strip() == ".wb-card-meta")
    assert "white-space" not in meta and "text-overflow" not in meta, "the card's meta is never cut: the head wraps"
    assert ":has(.wb-card-plain)" not in floor


# --- M-12 (the maintainer's word, A-52): no mode chip in the Floor's head; the soft notice of the Lobby's dialog and of the placeholder -------------------------------------

HEAD = r"""
import { FakeNode, settle, find, all } from "@FAKE@";
import { setToken } from "@JS@/token.js";
import * as router from "@JS@/router.js";
import { createFloorView } from "@JS@/views/floor.js";

setToken("t".repeat(40));
globalThis.ResizeObserver = class { observe() {} disconnect() {} };
document.removeEventListener = () => {};
const P = "0123456789ab";
globalThis.fetch = async () => ({ ok: true, status: 200, json: async () => ({}) });
const agent = (name) => ({ name, pack: "x", enabled: true, mode: "supervised", acting_mode: "supervised", max_runs_per_day: 8, max_usd_per_day: 4, runs_today: 1, usd_today: 0.1, runs_without_cost: 0, queued: 0, wider: [] });
const snapshot = { loaded: true, projects: [{ id: P, name: "northwind-shop", config: { accepted: true } }], tasks: {},
  details: { [P]: { agents: [agent("engineering"), agent("planning")], status: { requests: [], pending: [], documents: [] } } } };
const out = {};
for (const phone of [false, true]) {
  globalThis.window.matchMedia = () => ({ matches: phone, addEventListener() {}, removeEventListener() {} });
  const frame = { el: new FakeNode("div"), main: new FakeNode("main"), track: { el: new FakeNode("div") }, noticeBox: new FakeNode("div"), insets: () => ({ left: 0, right: 0, top: 0, bottom: 0, pad: 1 }),
    isPhone: () => phone, sceneUnavailable() {}, announce() {}, acquireWorld: () => ({ show() {}, setOptions() {}, refit() {}, stats() { return {}; } }) };
  const view = createFloorView(frame, { refresh() {} });
  for (const tab of ["agent", "inbox", "tasks", "desk"]) {
    view.update({ snapshot, route: router.parse(`#/p/${P}/floor/engineering/${tab}`), now: new Date("2026-10-10T12:00:00Z"), reload: 1 });
    await settle();
    const head = find(frame.main, ".wb-floor-head");
    out[`${phone ? "phone" : "desktop"}-${tab}`] = { chips: all(head, ".pui-chip").length, header: all(head, ".wb-header-mode, .wb-mode-plate").length, own: all(frame.main, ".wb-mode-row .wb-mode-plate").length, title: find(head, ".wb-panel-title").textContent };
  }
  view.dispose();
}
console.log(JSON.stringify(out));
process.exit(0);
"""


@needs_node
def test_the_floors_head_has_no_mode_chip_on_any_tab_or_width_and_the_mode_stays_in_the_agent_tab(tmp_path):
    from test_interface_adj_b1 import run_view
    got = run_view(tmp_path, HEAD)
    for key, value in got.items():
        assert value["chips"] == 0 and value["header"] == 0, f"M-12: {key}: the head names no mode"
        assert value["title"] == "Engineering agent"
    assert got["desktop-agent"]["own"] == 1 and got["phone-agent"]["own"] == 1, "M-12: the mode stays in the Agent tab"
    for name in ("views/floor.js",):
        source = (INTERFACE / "js" / name).read_text(encoding="utf-8")
        assert "wb-header-mode" not in source and "modeChip" not in source
    assert "wb-header-mode" not in interface_css()
    for path in sorted((INTERFACE / "js" / "views").glob("lobby*.js")):
        assert "wb-header-mode" not in path.read_text(encoding="utf-8"), f"M-12: {path.name}: the Lobby's head shows no mode chip either"


def test_every_notice_the_page_builds_is_the_soft_style_the_lobby_s_cancel_dialog_and_the_placeholder_included():
    bad = []
    for path in sorted((INTERFACE / "js").rglob("*.js")):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r'class: ["`]notice(?! pui-soft)', line):
                bad.append(f"{path.name}:{lineno}")
    assert not bad, f"a notice that is not the soft style (R-11), which no stylesheet draws: {bad}"
    assert 'class: "notice pui-soft pui-error wb-card-error"' in (INTERFACE / "js" / "views" / "lobby-request.js").read_text(encoding="utf-8")
    assert (INTERFACE / "js" / "views" / "placeholder.js").read_text(encoding="utf-8").count('class: "notice pui-soft pui-error"') == 3


# --- R4-A4b (A-61, M-19): the Agent tab's sections breathe ---------------------------------------------------------------------------------------------------------

def test_the_agent_tabs_sections_keep_the_tabs_gap_above_the_runs_total_the_other_tasks_and_the_hand_over_box():
    rules = {}
    for selector, declarations in css_rules():
        rules.setdefault(selector.strip(), declarations)
    root = rules[".wb-agent-tab, .wb-desk-tab, .wb-inbox, .wb-tasks-tab"]
    assert root.get("--wb-tab-gap") == "14px" and root.get("gap") == "var(--wb-tab-gap)", "the tab's gap is one property: the sections of the tab and of its body read the same"
    body = rules[".wb-agent-body"]
    assert body.get("display") == "grid" and body.get("gap") == "var(--wb-tab-gap, 14px)", "A-61: the body that holds the meters, the runs total, the current task, the others and the hand-over box has the tab's gap between them"
    assert rules[".wb-agent-body > :empty"].get("display") == "none", "an empty section adds no gap"
    assert rules[".wb-section"].get("gap") == "6px", "a section's heading keeps the smaller gap to its own rows"
    source = (INTERFACE / "js" / "floor" / "agent-tab.js").read_text(encoding="utf-8")
    assert 'h("div", { class: "wb-agent-body" }, waitingLine, metersBox, runsTotalLine, currentBox, othersBox, handBox)' in source, "the three gaps are above the runs total, the others (a .wb-section: heading and rows) and the hand-over box"
    assert 'const othersBox = h("div", { class: "wb-section" })' in source


# --- R4-A4b (A-62, M-20, M-21): how the mode comes back --------------------------------------------------------------------------------------------------------------

MODE_STEPS = r"""
import { FakeNode, settle, find, all } from "@FAKE@";
import * as fm from "@JS@/floor-model.js";
import { createAgentTab } from "@JS@/floor/agent-tab.js";

const P = "0123456789ab";
const text = (n) => (n ? n.textContent : null);
const wider = (names) => names.map((m) => ({ mode: m, command: `python3 /ck/cli.py set-mode --project /work/shop --agent engineering --mode ${m} --accept` }));
const agent = (mode, extra = {}) => ({ name: "engineering", pack: "x", enabled: true, mode, acting_mode: mode, max_runs_per_day: 6, max_usd_per_day: 2, runs_today: 0, usd_today: 0, runs_without_cost: 0, queued: 0, held: 0, ...extra });
const task = { id: 4, key: "k", title: "T", skill: "s", state: "ready", note: null, agent: "engineering", requestId: 1, waiting_for: [] };
const view = (a, error = null, accepted = true) => fm.floor({ projects: [{ id: P, name: "n", config: { accepted } }], details: { [P]: { status: { requests: [{ id: 1, title: "R", state: "ready", tasks: [task] }], pending: [], held: [] }, agents: [a], ...(error ? { error } : {}) } }, tasks: {}, loaded: true }, P, "engineering", {});
const tab = createAgentTab({ project: P, agent: "engineering", api: { setMode: async () => ({}), retry: async () => ({}), goAhead: async () => ({}), handOver: async () => ({}) }, refresh() {}, now: () => new Date() });
const out = {};
const read = () => ({ modeLine: text(find(tab.el, ".wb-mode-line")), note: text(find(tab.el, ".wb-wider-note")), select: all(tab.el, ".wb-wider-box select").length, options: all(tab.el, ".wb-wider-box option").map(text),
  step: text(find(tab.el, ".wb-accept-step .wb-card-line")), code: text(find(tab.el, ".wb-accept-step .wb-command-code")), copies: all(tab.el, ".wb-accept-step button.wb-copy").length });

tab.update(view(agent("stopped", { wider: wider(["supervised", "milestones", "autonomous"]) })));
await settle();
out.stopped = read();
tab.update(view(agent("supervised", { wider: wider(["milestones", "autonomous"]) })));
await settle();
out.chosen = read();
const accept = "python3 /ck/cli.py accept-config --project /work/shop --sha256 " + "a".repeat(64);
tab.update(view(agent("stopped", { wider: wider(["supervised", "milestones"]) }), { status: 412, word: "not_accepted", message: "not accepted", next: accept }, false));
await settle();
out.waiting = read();
tab.update(view(agent("supervised", { wider: wider(["milestones"]) }), { status: 412, word: "not_accepted", message: "not accepted", next: null }, false));
await settle();
out.waitingNoCommand = read();
tab.update(view(agent("stopped", { wider: wider(["supervised", "milestones"]) })));
await settle();
out.back = read();
console.log(JSON.stringify(out));
process.exit(0);
"""


@needs_node
def test_the_agent_tab_says_how_a_stopped_agent_comes_back_runs_one_step_and_shows_the_accept_step_while_the_configuration_waits(tmp_path):
    got = run_node(tmp_path, MODE_STEPS)
    one = "Run this command in the terminal: it sets the mode and accepts it."
    back = "To bring it back, choose supervised below and run its command in the terminal."
    stopped = got["stopped"]
    assert stopped["modeLine"] == f"Off, starts nothing. {back}", "A-62 (3): the stopped line says how to bring the agent back, in these words"
    assert stopped["options"][0] == "supervised" and stopped["note"] == one and stopped["select"] == 1, "the select starts with supervised, and the block is one step"
    assert got["chosen"]["note"] == one and got["chosen"]["modeLine"] == "Every review reaches you." and got["chosen"]["select"] == 1, "A-62, M-21 (1): a wider mode chosen is one step; no bring-back line off the stopped mode"
    waiting = got["waiting"]
    assert waiting["step"] == "The new mode takes effect once the configuration is accepted. Run this command in the terminal." and waiting["code"].endswith("--sha256 " + "a" * 64) and waiting["copies"] == 1, "A-62 (2): the accept step with its command (the service's, verbatim) and Copy"
    assert waiting["select"] == 0 and waiting["note"] is None and back not in waiting["modeLine"], "no other set-mode is offered while the configuration waits, and the bring-back line gives way to that step"
    assert got["waitingNoCommand"]["step"] == "The new mode takes effect once the configuration is accepted in the terminal." and got["waitingNoCommand"]["copies"] == 0 and got["waitingNoCommand"]["select"] == 0, "a refusal without a command says it without \"this command\" and builds none"
    assert got["back"]["select"] == 1 and got["back"]["step"] is None and back in got["back"]["modeLine"], "once accepted, the select and the line come back"
    source = (INTERFACE / "js" / "floor" / "agent-tab.js").read_text(encoding="utf-8")
    assert "cli.py" not in source and "accept-config" not in source and "--accept" not in source, "the page builds no command: it shows what the service sent"


# --- the ready floor: a task queued behind the one run at a time (M-24, A-65, R4-B6) -----------------------------------------------------------------

READY_JS = r"""
import * as fm from "@JS@/floor-model.js";
import * as model from "@JS@/model.js";
import { roomModel } from "@JS@/views/lobby-model.js";
import { stateRow, queuedFree, HELD_SENTENCES, QUEUED_NOTE, TURN_REASON } from "@JS@/floor-model.js";

const P = "0123456789ab";
const agent = (name, extra = {}) => ({ name, pack: "x", enabled: true, mode: "supervised", acting_mode: "supervised", max_runs_per_day: 8, max_usd_per_day: 2, runs_today: 0, usd_today: 0, runs_without_cost: 0, queued: 0, held: 0, ...extra });
const task = (id, state, agentName) => ({ id, key: `k${id}`, title: `Task ${id}`, skill: "s", state, note: null, agent: agentName });
const held = (id, agentName, reason) => ({ task_id: id, agent: agentName, reason, at: "2026-10-08T11:59:30Z", next: null });
const rowOf = (agents, tasks, extra = {}) => {
  const status = { requests: [{ id: 1, title: "R", state: "ready", tasks }], pending: [], held: [], ...extra };
  const snapshot = { projects: [{ id: P, name: "shop", config: { accepted: true } }], details: { [P]: { status, agents } }, tasks: {}, loaded: true };
  return { rows: fm.building(snapshot, P).rows, snapshot, status };
};
const stateOf = (r, name) => r.rows.find((x) => x.name === name).state;
"""


@needs_node
def test_a_floor_whose_task_is_queued_and_not_held_is_ready_and_every_other_case_keeps_its_state(tmp_path):
    got = run_node(tmp_path, READY_JS + r"""
const out = {};
const queued = [agent("design", { queued: 1 })];
// queued alone, and with nothing queued
out.alone = stateOf(rowOf(queued, [task(1, "ready", "design")]), "design");
out.none = stateOf(rowOf([agent("design")], [task(1, "planned", "design")]), "design");
// queued while another floor runs: this one is ready, the other works
const two = rowOf([agent("design", { queued: 1 }), agent("engineering")], [task(1, "ready", "design"), task(2, "running", "engineering")]);
out.whileOtherRuns = [stateOf(two, "design"), stateOf(two, "engineering")];
// held for each reason of the dispatcher's list: a hold keeps the idle look and its reason; a task that only waits for its turn (`job running`) is queued
out.reasons = {};
for (const reason of Object.keys(HELD_SENTENCES)) out.reasons[reason] = stateOf(rowOf([agent("design", { queued: 1, held: 1 })], [task(1, "ready", "design")], { held: [held(1, "design", reason)] }), "design");
// two queued, one of them held: the other is free, so it is ready; both held: idle
out.oneFree = stateOf(rowOf([agent("design", { queued: 2, held: 1 })], [task(1, "ready", "design"), task(2, "ready", "design")], { held: [held(1, "design", "cap: runs per day")] }), "design");
out.bothHeld = stateOf(rowOf([agent("design", { queued: 2, held: 2 })], [task(1, "ready", "design"), task(2, "ready", "design")], { held: [held(1, "design", "dispatch off"), held(2, "design", "dispatch off")] }), "design");
// the agent's own count when the status lists no hold at all (an older service)
out.countOnly = [stateOf(rowOf([agent("design", { queued: 1, held: 1 })], [task(1, "ready", "design")], { held: undefined }), "design"), queuedFree(agent("design", { queued: 3, held: 1 }), {})];
// queued and waiting for the person: waiting; queued and running: working; queued and stopped: off
const pendingRow = rowOf([agent("design", { queued: 1 })], [task(1, "ready", "design"), task(2, "waiting", "design")], { pending: [{ id: 5, kind: "question", title: "Q", task_id: 2, agent: "design", created_at: "2026-10-08T11:00:00Z" }] });
out.waiting = stateOf(pendingRow, "design");
out.running = stateOf(rowOf([agent("design", { queued: 1 })], [task(1, "ready", "design"), task(2, "running", "design")]), "design");
out.stopped = stateOf(rowOf([agent("design", { queued: 1, mode: "stopped", acting_mode: "stopped" })], [task(1, "ready", "design")]), "design");
console.log(JSON.stringify(out));
""")
    assert got["alone"] == "ready" and got["none"] == "idle", "M-24: a task queued and not held makes the floor ready; nothing queued is idle"
    assert got["whileOtherRuns"] == ["ready", "working"], "queued while another floor runs: ready, and the other floor works"
    for reason, state in got["reasons"].items():
        assert state == ("ready" if reason == "job running" else "idle"), f"a task held for {reason!r} keeps the idle look and its reason; one that only waits for its turn is queued"
    assert got["oneFree"] == "ready" and got["bothHeld"] == "idle", "two queued and one held: the other is free; both held: idle"
    assert got["countOnly"] == ["idle", 2], "with no list of holds the agent's own count is read"
    assert got["waiting"] == "waiting" and got["running"] == "working" and got["stopped"] == "off", "waiting for the person, working and off all outrank ready"


@needs_node
def test_a_ready_floor_is_lit_in_the_city_the_building_and_the_lobby_and_says_queued_where_a_sentence_fits(tmp_path):
    got = run_node(tmp_path, READY_JS + r"""
const out = {};
const r = rowOf([agent("design", { queued: 1 }), agent("brand")], [task(1, "ready", "design")]);
const row = r.rows.find((x) => x.name === "design");
const idle = r.rows.find((x) => x.name === "brand");
out.window = [row.window, idle.window];
out.plate = [row.plateWord, row.plateTone, row.cardWord, row.stateWord, row.dot, row.plateDot, idle.plateWord];
out.tip = [row.tip, row.linkName];
out.stateRow = [stateRow("ready", 0, null), stateRow("idle", 0, null).chip];
out.note = [QUEUED_NOTE, TURN_REASON];
// the City's window rule (model.js) lights it too, not an idle floor, not a stopped one
const city = model.buildingOf({ id: P, name: "shop", config: { accepted: true } }, { status: r.status, agents: [agent("design", { queued: 1 }), agent("brand"), agent("business", { queued: 1, mode: "stopped", acting_mode: "stopped" })] });
out.city = city.floors.map((f) => [f.agent, f.window]);
// the City's window with the agent's task held for a reason of its own: dark; held only for its turn: lit
const heldCity = (reason) => model.buildingOf({ id: P, name: "shop", config: { accepted: true } }, { status: { ...r.status, held: [held(1, "design", reason)] }, agents: [agent("design", { queued: 1, held: 1 })] }).floors[0].window;
out.cityHeld = [heldCity("dispatch off"), heldCity("job running")];
// the Floor's room and the scene's floor
out.scene = fm.buildingScene(fm.building(r.snapshot, P), null).floors.map((f) => [f.name, f.state, f.window]);
// the Lobby's room: the planning agent with a task queued and not held
const lobby = (extra) => roomModel({ working: false, decisions: 0, hasMessages: true, accepted: true, request: null, ...extra });
out.lobby = [lobby({ queued: true }), lobby({}), lobby({ queued: true, decisions: 2 }), lobby({ queued: true, working: true }), lobby({ queued: true, accepted: false })].map((m) => [m.state, m.window, m.tips.agent]);
console.log(JSON.stringify(out));
""")
    assert got["window"] == ["lit", "grey"], "R-21 extended: a queued floor's window is lit, an idle one's is dark"
    assert got["plate"][:4] == ["queued", "pui-muted", "Queued", "Queued"] and got["plate"][4:6] == ["theme", "theme"] and got["plate"][6] == "resting", "the plate says queued (a floor with nothing queued still says resting); its dot is the brand colour"
    assert ", queued" in got["tip"][0] and ", queued" in got["tip"][1], "the floor's tooltip and its link's name say queued"
    assert got["stateRow"][0] == {"tone": "pui-theme pui-soft", "chip": "Queued", "line": "Queued, starts when the current run ends", "off": False} and got["stateRow"][1] == "Idle", "the Agent tab's state line: the chip, and the sentence"
    assert got["note"] == ["starts when the current run ends", "job running"]
    assert got["city"] == [["design", "lit"], ["brand", "grey"], ["business", "grey"]], "the City's window rule lights a queued agent, not an idle or a stopped one"
    assert got["cityHeld"] == ["grey", "lit"], "a task held for a reason of its own leaves the window dark; one that only waits for its turn lights it"
    assert got["scene"][0][1:] == ["ready", "lit"] or any(s[1:] == ["ready", "lit"] for s in got["scene"]), "the scene's floor carries the state and the lit window"
    assert got["lobby"][0] == ["ready", "lit", "Planning agent · queued · starts when the current run ends"], "the Lobby's room: ready, lit, and the tooltip's sentence"
    assert got["lobby"][1][0] == "idle" and got["lobby"][2][0] == "waiting" and got["lobby"][3][0] == "working" and got["lobby"][4][0] == "off", "idle, waiting, working and off outrank or leave ready as before"


@needs_node
def test_a_queued_floor_is_muted_whatever_holds_it_and_what_the_page_can_tell_keeps_a_task_from_starting_is_not_queued(tmp_path):
    # review of R4-B6: the real ready case always carries the dispatcher's `job running` (it reports that for every ready task while a run is in progress); the page also knows a daily
    # cap (from the agents it reads) and an open wait (from the status rows) itself, and the planner that is stopped or disabled is off
    got = run_node(tmp_path, READY_JS + r"""
import { queuedFree as fromModel } from "@JS@/model.js";
const out = {};
// the plate's tone: a queued floor held only by `job running` is muted, not the amber of a hold; a task held for another reason keeps the amber
const turn = rowOf([agent("design", { queued: 1, held: 1 })], [task(1, "ready", "design")], { held: [held(1, "design", "job running")] }).rows.find((x) => x.name === "design");
const own = rowOf([agent("design", { queued: 1, held: 1 })], [task(1, "ready", "design")], { held: [held(1, "design", "dispatch off")] }).rows.find((x) => x.name === "design");
out.tone = [turn.state, turn.plateWord, turn.plateTone, turn.heldReason, own.state, own.plateWord, own.plateTone];
// a daily cap in use: runs, spend; a cap not in use (caps_in_use false) does not count
const capped = (extra) => stateOf(rowOf([agent("design", { queued: 1, held: 1, max_runs_per_day: 4, runs_today: 4, max_usd_per_day: 2, usd_today: 0, ...extra })], [task(1, "ready", "design")], { held: [held(1, "design", "job running")] }), "design");
out.caps = [capped({}), capped({ runs_today: 3 }), capped({ runs_today: 0, usd_today: 2 }), capped({ runs_today: 0, usd_today: 1.5 }), capped({ caps_in_use: { runs: false, spend: true } }), capped({ runs_today: 0, usd_today: 2, caps_in_use: { runs: true, spend: false } })];
// an open wait: a ready task that waits for another task is not free; one that does not is
const waitTask = (id) => ({ ...task(id, "ready", "design"), waiting_for: [{ task_id: 9, request_id: 1, reason: "needs docs/a.md" }] });
const waits = (tasks, queuedCount) => stateOf(rowOf([agent("design", { queued: queuedCount, held: queuedCount })], tasks, { held: tasks.map((t) => held(t.id, "design", "job running")) }), "design");
out.waits = [waits([waitTask(1)], 1), waits([waitTask(1), task(2, "ready", "design")], 2)];
out.same = fromModel === fm.queuedFree && fm.TURN_REASON === "job running";
// the Lobby's planner: stopped or disabled is off, whatever is queued (the view's predicate)
out.cityCap = model.buildingOf({ id: P, name: "shop", config: { accepted: true } }, { status: { requests: [], pending: [], held: [] }, agents: [agent("design", { queued: 1, max_runs_per_day: 2, runs_today: 2 })] }).floors[0].window;
console.log(JSON.stringify(out));
""")
    assert got["tone"] == ["ready", "queued", "pui-muted", "job running", "idle", "held: dispatch off", "pui-warn"], "a queued floor held only by `job running` is muted; a hold of another kind is amber and keeps the idle look"
    assert got["caps"] == ["idle", "ready", "idle", "ready", "ready", "ready"], "an agent at a daily cap in use (runs or spend) is not queued; a cap not in use does not count"
    assert got["waits"] == ["idle", "ready"], "a ready task with an open wait is not queued; one without is"
    assert got["same"] is True and got["cityCap"] == "grey", "one definition (model.js), read by the floors and by the City's window rule, which leaves a capped agent's window dark"
    lobby = (JS / "views" / "lobby.js").read_text(encoding="utf-8")
    assert 'planner.enabled !== false && planner.acting_mode !== "stopped" && fm.queuedFree(planner, status) > 0' in lobby, "the Lobby's planner that is stopped or disabled is off, not ready"
    readme = (INTERFACE / "README.md").read_text(encoding="utf-8")
    assert "during a run the dispatcher reports only" in readme, "the limit is written down"


# --- R4-A4c (A-67, M-25): a long reply opens in place; no inner scroll on a card's body --------------------------------------------------------------------------------

REPLY = r"""
import { FakeNode, settle, find, all } from "@FAKE@";
import { replyView, SHOW_WHOLE, SHOW_LESS } from "@JS@/floor/reply.js";
import { createCard } from "@JS@/floor/cards.js";

const observers = [];
globalThis.ResizeObserver = class { constructor(cb) { observers.push(cb); } observe() {} disconnect() {} };
const text = (n) => (n ? n.textContent : null);
const cls = (n) => (n.attrs.class || "").split(/\s+/).filter(Boolean);
const out = {};
const measure = (tall) => (body) => tall.value;

// the helper: the button is in the page only when the reply is taller than the preview (a measured height), toggles, and says so
const tall = { value: false };
const fit = replyView(new FakeNode("p"), { measure: measure(tall) });
out.fits = { buttons: all(fit.el, "button").length, cut: cls(fit.el).includes("is-cut") };
tall.value = true;
fit.update();
const button = find(fit.el, "button.wb-reply-toggle");
out.cut = { buttons: all(fit.el, "button").length, label: text(button), expanded: button.attrs["aria-expanded"], controls: button.attrs["aria-controls"] === find(fit.el, ".wb-reply-body").attrs.id, cut: cls(fit.el).includes("is-cut") };
button.click();
out.open = { label: text(button), expanded: button.attrs["aria-expanded"], open: cls(fit.el).includes("is-open"), cut: cls(fit.el).includes("is-cut"), buttons: all(fit.el, "button").length };
tall.value = false;      // open: the button stays, whatever the measure says
fit.update();
out.openStays = all(fit.el, "button").length;
button.click();
out.closed = { label: text(button), expanded: button.attrs["aria-expanded"], open: cls(fit.el).includes("is-open") };
out.labels = [SHOW_WHOLE, SHOW_LESS];

// a card: a long review opens in place, Plain text keeps working in both states, a short one has no button
const item = (id, body) => ({ id, kind: "review", title: `Review ${id}`, body, payload: { returned: [], kept: [] }, status: "open", actions: ["released", "answered"], agent: "engineering", task_id: 4, created_at: new Date().toISOString() });
const env = { project: "p", now: () => new Date(), api: {}, requestIds: new Set(), links: { floor: () => "#", lobby: () => "#", open: () => "#" }, changed() {}, gone() {} };
const card = createCard(item(1, "A **long** reply"), env);
const tallen = () => { for (const body of all(card.el, ".wb-reply-body")) { body.scrollHeight = 900; body.clientHeight = 96; } observers.forEach((cb) => cb()); };
tallen();
const toggle = () => find(card.el, "button.wb-reply-toggle");
out.card = { before: text(toggle()), scrollClass: all(card.el, ".wb-scroll").length };
toggle().click();
out.card.open = text(toggle());
find(card.el, "button.wb-card-plain").click();      // Plain text redraws the card: the reply stays open
tallen();
out.card.plainOpen = { label: text(toggle()), plain: all(card.el, ".wb-md.is-plain").length, pressed: find(card.el, "button.wb-card-plain").attrs["aria-pressed"] };
toggle().click();
out.card.plainClosed = text(toggle());
find(card.el, "button.wb-card-plain").click();
const short = createCard(item(2, "short"), env);
out.short = { buttons: all(short.el, "button.wb-reply-toggle").length };
console.log(JSON.stringify(out));
process.exit(0);
"""


@needs_node
def test_a_long_reply_opens_in_place_the_button_appears_only_when_the_body_is_taller_than_the_preview_and_plain_text_keeps_working(tmp_path):
    got = run_node(tmp_path, REPLY)
    assert got["fits"] == {"buttons": 0, "cut": False}, "a reply that fits shows whole: no button, no fade"
    assert got["cut"] == {"buttons": 1, "label": "Show the whole reply", "expanded": "false", "controls": True, "cut": True}, "A-67: the button, with aria-expanded and aria-controls"
    assert got["open"] == {"label": "Show less", "expanded": "true", "open": True, "cut": False, "buttons": 1} and got["openStays"] == 1
    assert got["closed"] == {"label": "Show the whole reply", "expanded": "false", "open": False}
    assert got["card"]["before"] == "Show the whole reply" and got["card"]["scrollClass"] == 0 and got["card"]["open"] == "Show less"
    assert got["card"]["plainOpen"] == {"label": "Show less", "plain": 1, "pressed": "true"}, "R-34: Plain text works on an open reply and the choice of the reply survives the redraw"
    assert got["card"]["plainClosed"] == "Show the whole reply"
    assert got["short"] == {"buttons": 0}


def test_no_card_body_scrolls_inside_the_card_the_preview_is_clipped_and_the_whole_is_the_only_other_state():
    css = interface_css()
    bad = []
    for selector, declarations in css_rules():
        if re.search(r"wb-(card|bubble|pre|res-said|md|plan|reply|scroll)", selector) and "max-height" in declarations and re.search(r"overflow(-y)?", " ".join(declarations)):
            if any(v in ("auto", "scroll") for k, v in declarations.items() if k.startswith("overflow")):
                bad.append(selector)
    assert not bad, f"M-25: a card body scrolls inside the card: {bad}"
    rules = {}
    for selector, declarations in css_rules():
        rules.setdefault(selector.strip(), declarations)
    preview = rules[".wb-reply:not(.is-open) .wb-reply-body"]
    assert preview.get("overflow") == "hidden" and "var(--wb-reply-lines)" in preview.get("max-height", "") and rules[".wb-reply"].get("--wb-reply-lines") == "8", "about eight lines, clipped, not scrolled"
    fade = rules[".wb-reply.is-cut:not(.is-open) .wb-reply-body"]
    assert "var(--pui-text)" in fade.get("mask-image", "") and not re.search(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(", str(fade)), "the fade is a mask of a token: no colour literal"
    for path in (INTERFACE / "js").rglob("*.js"):
        assert "wb-scroll" not in path.read_text(encoding="utf-8"), f"{path.name}: the scrolling class is gone"


# --- the review of PR #316 -----------------------------------------------------------------------------------------------------------------------------------------

REPLY_FIXES = r"""
import { FakeNode, settle, find, all } from "@FAKE@";
import { replyView } from "@JS@/floor/reply.js";
import { createCard } from "@JS@/floor/cards.js";

const out = {};
const cls = (n) => (n.attrs.class || "").split(/\s+/).filter(Boolean);

// 2: the focus enters the clipped part: the reply opens
const link = new FakeNode("a");
const inner = new FakeNode("div"); inner.append(link);
const view = replyView(inner, { measure: () => true });
out.before = { open: view.isOpen(), buttons: all(view.el, "button").length };
(view.el.listeners.focusin || []).forEach((fn) => fn({ target: link }));
out.focusOpens = { open: view.isOpen(), label: find(view.el, "button").textContent };
(view.el.listeners.focusin || []).forEach((fn) => fn({ target: find(view.el, "button") }));      // the focus on the button itself does not toggle it again
out.buttonFocus = view.isOpen();

// 5: closing keeps the button in view
let scrolled = null;
const button = find(view.el, "button");
button.scrollIntoView = (o) => { scrolled = o; };
button.click();
out.closed = { open: view.isOpen(), scrolled };

// 3: no way to measure (no ResizeObserver, no measure of its own): the reply is whole, not clipped with no button
delete globalThis.ResizeObserver;
const unmeasured = replyView(new FakeNode("p"));
out.unmeasured = { classes: cls(unmeasured.el), buttons: all(unmeasured.el, "button").length };

// 4: the review body no longer scrolls: it is no tab stop and has no name of a scroller
const card = createCard({ id: 1, kind: "review", title: "R", body: "text", payload: { returned: [], kept: [] }, status: "open", actions: ["released", "answered"], agent: "engineering", task_id: 4, created_at: new Date().toISOString() },
  { project: "p", now: () => new Date(), api: {}, requestIds: new Set(), links: { floor: () => "#", lobby: () => "#", open: () => "#" }, changed() {}, gone() {} });
const body = all(card.el, ".wb-card-body")[0];
out.review = { tabindex: body.attrs.tabindex === undefined, label: body.attrs["aria-label"] === undefined };
console.log(JSON.stringify(out));
process.exit(0);
"""


@needs_node
def test_the_reply_opens_when_the_focus_enters_it_closing_keeps_the_button_in_view_and_an_unmeasurable_reply_shows_whole(tmp_path):
    got = run_node(tmp_path, REPLY_FIXES)
    assert got["before"] == {"open": False, "buttons": 1}
    assert got["focusOpens"] == {"open": True, "label": "Show less"} and got["buttonFocus"] is True, "the focus on a link in the clipped part opens the reply; the focus on the button does not toggle it"
    assert got["closed"] == {"open": False, "scrolled": {"block": "nearest"}}, "closing scrolls the button into view"
    assert got["unmeasured"] == {"classes": ["wb-reply", "is-open"], "buttons": 0}, "without a measure the reply is not clipped and has no button"
    assert got["review"] == {"tabindex": True, "label": True}, "the review body no longer scrolls: no tab stop, no scroller's name"


def test_the_replys_button_reads_as_a_control_and_is_a_phone_tap_target_and_the_plan_text_keeps_its_choice_across_a_rebuild():
    rules = {}
    for selector, declarations in css_rules():
        rules.setdefault(selector.strip(), declarations)
    toggle = rules[".wb-reply-toggle"]
    assert toggle.get("color") == "var(--wb-ink-theme)" and toggle.get("text-decoration") == "underline", "it reads as a control, in tokens"
    base = (INTERFACE / "css" / "base.css").read_text(encoding="utf-8")
    assert "@media (max-width: 899px) { .wb-reply-toggle { min-height: 44px;" in base, "a phone's tap target"
    plan = (INTERFACE / "js" / "cards" / "plan.js").read_text(encoding="utf-8")
    assert "const planOpen = new Map()" in plan and "open: Boolean(planOpen.get(item.id)), onToggle: (value) => planOpen.set(item.id, value)" in plan, "the Lobby's plan text keeps the open choice across a rebuild"
