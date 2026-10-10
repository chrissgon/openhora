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
    assert "flex-wrap: wrap" in by_selector[".wb-resolved"] and "min-width: 0" in by_selector[".wb-resolved-title"], "the Floor's resolved line wraps too"
    cards = (JS / "floor" / "cards.js").read_text(encoding="utf-8")
    assert 'h("div", { class: "mono", text: l })' in cards and 'class: "wb-card-line", text: l' in cards, "an id is mono, a sentence is prose"
    assert "lines.map((l) => h(\"div\", { class: \"mono\"" not in cards

# --- moved from test_interface_plates_meters.py ----------------------------------------------------------------------------------


@needs_node
def test_the_agent_tab_stops_and_supervises_with_two_buttons_shows_the_held_sentence_and_the_commands_the_service_gave(tmp_path):
    got = run_node_plates_meters(tmp_path, AGENT)
    assert got["select"] == 0, "the select is gone"
    assert got["labels"] == ["Stop agent", "Supervise"] and got["enabled"] == [False, False]
    assert "A wider mode is set in the terminal" in got["wider"], "a wider mode is the terminal's"
    assert got["standing"] != "Setting a mode changes the project's configuration. Every action of this page then refuses until you accept the new configuration in the terminal.", \
        "the standing notice would be false now: a narrowing is accepted at once"
    assert got["meters"] == ["Runs today 5 / 12", "Spend today $1.87 / $4.00", "Queued 1"] and got["meterTitles"][:2] == [True, True]
    assert got["stop"]["calls"] == [["setMode", "p", "engineering", "stopped"]], "one request with the word of the button"
    assert got["stop"]["refreshed"] == 1 and got["stop"]["commands"] == 0 and "Mode set to stopped" in got["stop"]["result"] and "Nothing works" not in got["stop"]["result"]
    assert got["afterStop"] == [True, True], "already stopped: both are off"
    assert got["supervised"] == [False, True], "Supervise is off at supervised; Stop agent is still on"
    assert got["supervise"] == [["setMode", "p", "engineering", "supervised"]]
    assert "changed while this call was running" in got["refused"]
    assert got["notAccepted"]["code"].endswith("--sha256 " + "e" * 64) and got["notAccepted"]["copy"] == 1
    assert got["unaccepted"] == {"buttons": [True, True], "waitingLine": True, "meters": 3, "formHidden": False}, "not accepted: the panel keeps its data and its buttons are off"
    assert got["held"]["text"].startswith("Held: The service is not dispatching tasks.") and got["held"]["code"].startswith("uv run --with keyring==25.7.0 python3 /ck/runtime/cli.py run-next")
    assert got["held"]["copy"] == 1
    assert got["heldNoCommand"]["code"] == 0 and "spend" in got["heldNoCommand"]["text"]
    assert got["heldGone"] == 0


@needs_node
def test_the_agent_tab_shows_a_command_for_each_wider_mode_and_for_the_credential_as_the_service_gave_them(tmp_path):
    got = run_node_plates_meters(tmp_path, WIDER)
    modes = ["milestones", "autonomous", "autonomous-with-policy"]
    assert got["three"]["line"] == "A wider mode is set in the terminal, not on this page:"
    assert got["three"]["codes"] == [f"python3 /ck/runtime/cli.py set-mode --project /work/shop --agent engineering --mode {m}" for m in modes], "the service's three commands, in its order, verbatim"
    assert got["three"]["sentences"] == modes and got["three"]["copies"] == 3
    assert got["top"] == {"wider": 0, "codes": 0}, "an agent at the widest mode has nothing wider: no line"
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
    grounds = [s for s, d in rules if any(p.startswith("background") for p in d)]
    assert len(grounds) == 1, f"one rule sets the one ground (header and body continue it): {grounds}"
    for selector, declarations in rules:
        assert declarations.get("border-radius", "").replace(" ", "") not in ("0", "0px"), f"{selector} squares a corner"
    item = next(d for s, d in rules if ".wb-resolved-item" in s and any(p.startswith("background") for p in d))
    assert item.get("border-radius") == "var(--pui-radius)", "the item, which holds the header and the body, has the panel's radius on every corner"
    assert item.get("background-color") == "var(--wb-sunken)", "the ground is a token"
    summary = next(d for s, d in rules if re.search(r"\.wb-resolved(?![\w-])", s) and "item" not in s)
    assert not any(p.startswith("background") for p in summary), "the header paints no ground of its own"


def test_the_resolved_line_is_the_librarys_accordion_item_with_a_body():
    inbox = (JS / "floor" / "inbox.js").read_text(encoding="utf-8")
    assert 'class: "pui-accordion-item wb-resolved-item"' in inbox
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
