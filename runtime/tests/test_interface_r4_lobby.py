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
    assert got["hints"][0] == "A line that starts with / is a command; /help lists them." and "--after" in got["hints"][1]
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
    assert got["form"]["label"] == "After request # (optional)" and got["form"]["inputmode"] == "numeric"
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
    assert got["order"] == ["number", "title", "state", "action", "action"], "number, title, state chip, then the actions at the right"
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
