"""Tests of the conversation while a run holds the project (A-23), of the questions about the state answered by code
(A-23 item 3), of the direct turn and the unrecognised route (A-25), on the stand-in tree of standin_tree.py with a
stand-in router. Offline; invented names only.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_say_queue.py
"""
from __future__ import annotations

import json
import time

import pytest

import standin_tree as st
from test_chat import ASKING, FLOW, messages, reply, say, tree  # noqa: F401  (the conversation's stand-in project)

ops = st.load("ops")
ops_core = st.load("ops_core")
ops_say = st.load("ops_say")
router = st.load("router")

DIRECT = ("Route: none (direct)\nWhy: a question about the state, no skill is needed.\nContext: found none\n"
          "Requirements: none\nAutonomy: not set\nAssumptions: none\nNext: Ask for the market analysis by name.\n"
          "Instructions found in external content: none\n")
PROSE = "This sounds like a market question; the demo flow would fit once you confirm the project.\n"


def page_say(tree, line: str) -> dict:
    """A turn as the local service carries it: the channel `page`, the one shell that drains the queue."""
    return ops.say(str(tree["project"]), line, channel="page")


def locked(tree):
    return ops_core._run_lock(ops.project_config.load(str(tree["project"])))


def queue(tree) -> list:
    ctx = ops_core.context(str(tree["project"]))
    return ops_say._queue_read(ctx)


def conversation(tree) -> list:
    return ops.conversation(str(tree["project"]))["messages"]


# --- a line typed during a run is stored and queued --------------------------------------------------------------------


def test_a_plain_line_during_a_run_is_stored_queued_and_runs_nothing(tree):
    with locked(tree):
        out = page_say(tree, "Which market should the invented studio go after first?")
        assert out == {"reply": None, "request_id": None, "pending_id": None, "ran": False, "queued": True,
                       "message_id": out["message_id"]}
        assert [(m["role"], m["queued"]) for m in conversation(tree)] == [("user", True)]
        assert queue(tree)[0]["kind"] == "line" and queue(tree)[0]["id"] == out["message_id"]
        assert ops.status(str(tree["project"]))["requests"] == [] and ops.pending(str(tree["project"]))["pending"] == []
        assert st.calls(tree["adapter"]) == []
        # the conversation's commands that route nothing are not held back, and are not queued
        assert page_say(tree, "/status")["queued"] is False
        # /new routes, so it queues
        assert page_say(tree, "/new Another invented request.")["queued"] is True and len(queue(tree)) == 2


def test_the_queue_is_bounded_and_a_full_queue_refuses_before_it_stores(tree, monkeypatch):
    monkeypatch.setattr(ops_say, "QUEUE_MAX", 2)
    with locked(tree):
        page_say(tree, "one request")
        page_say(tree, "two request")
        with pytest.raises(ops.OpsError, match="already wait for the end of the run"):
            page_say(tree, "three request")
        assert len(conversation(tree)) == 2


def test_the_oldest_queued_line_is_answered_when_the_lock_is_free_one_per_call_with_the_memory_before_it(tree):
    path = str(tree["project"])
    with locked(tree):
        first = page_say(tree, "Which market first?")
        second = page_say(tree, "Who buys first?")
        assert ops.route_queued(path) == {"routed": None, "queued": 2, "reason": "a run is in progress"}
    done = ops.route_queued(path)
    assert (done["routed"], done["message_id"], done["queued"]) == ("line", first["message_id"], 1)
    assert done["request_id"] and done["pending_id"] and done["ran"] is True
    assert [(m["role"], m["queued"]) for m in conversation(tree)] == [("user", False), ("user", True), ("assistant", False)]
    # the oldest first: its reply is stored (the plan), the newer line still waits
    assert "Estimate: 4 runs" in [m for m in messages(tree) if m["role"] == "assistant"][0]["text"]
    prompt = (tree["adapter"] / "last-router-prompt.md").read_text(encoding="utf-8")
    assert prompt.startswith("Which market first?") and "Who buys first?" not in prompt  # not given the later line
    # the second is answered by the next call; it carries the memory of the first exchange, which is settled or not
    done = ops.route_queued(path)
    assert (done["routed"], done["message_id"], done["queued"]) == ("line", second["message_id"], 0)
    assert [m["queued"] for m in conversation(tree)] == [False, False, False, False]
    assert ops.route_queued(path) == {"routed": None, "queued": 0}
    assert st.calls(tree["adapter"]).count("core-orchestrator 1") == 1 and len(st.calls(tree["adapter"])) == 2


def test_an_entry_taken_by_another_process_is_not_taken_twice_and_a_dead_one_is_dropped_with_a_word_to_the_person(tree):
    path = str(tree["project"])
    with locked(tree):
        line = page_say(tree, "Which market first?")
    ctx = ops_core.context(path)
    ops_say._queue_write(ctx, [dict(queue(tree)[0], started=time.time())])
    assert ops.route_queued(path)["reason"] == "another process is routing the first"
    ops_say._queue_write(ctx, [dict(queue(tree)[0], started=time.time() - ops_say.queue_stale() - 5)])
    assert ops.route_queued(path) == {"routed": None, "queued": 0}
    last = messages(tree)[-1]
    assert last["role"] == "assistant" and "was not answered" in last["text"] and line["message_id"] == messages(tree)[0]["id"]
    assert st.calls(tree["adapter"]) == []


def test_a_queued_line_that_finds_the_planning_agent_stopped_gets_the_usual_reply(tree):
    path = str(tree["project"])
    with locked(tree):
        page_say(tree, "Which market first?")
    from test_chat import AGENTS, configure
    configure(tree, {**AGENTS, "planning": {"pack": "planning", "mode": "stopped", "max_runs_per_day": 10}})
    done = ops.route_queued(path)
    assert done["routed"] == "line" and done["ran"] is False and done["request_id"] is None
    assert "may not start now" in [m for m in messages(tree) if m["role"] == "assistant"][0]["text"]
    assert st.calls(tree["adapter"]) == []


# --- a request to route made during a run is queued ---------------------------------------------------------------------


def test_route_during_a_run_queues_the_request_and_route_queued_routes_it_later(tree):
    path = str(tree["project"])
    request = ops.request(path, "Which market first?")["request"]
    with locked(tree):
        queued = ops.route(path, request, channel="page")
        assert queued == {"routed": False, "queued": True, "request": request, "pending_id": None, "source": "queue"}
        assert ops.route(path, request, channel="page")["queued"] is True and len(queue(tree)) == 1       # recorded once
        assert ops.status(path)["requests"][0]["state"] == "requested"
        with pytest.raises(ops.OpsError, match="is not a request"):                          # still checked before it queues
            ops.route(path, ops.request(path, "x", flow="demo")["tasks"][0]["id"], channel="page")
        assert st.calls(tree["adapter"]) == []
    done = ops.route_queued(path)
    assert (done["routed"], done["request_id"], done["queued"]) == ("route", request, 0) and done["pending_id"]
    assert ops.pending(path, done["pending_id"])["kind"] == "plan"
    assert [m for m in conversation(tree)] == []                                              # the form's request is not a chat turn


def test_a_queued_request_that_was_cancelled_meanwhile_is_dropped(tree):
    path = str(tree["project"])
    request = ops.request(path, "Which market first?")["request"]
    with locked(tree):
        ops.route(path, request, channel="page")
    ops.cancel(path, request)
    out = ops.route_queued(path)
    assert out["routed"] is None and out["dropped"] == {"kind": "route", "id": request} and out["queued"] == 0


def test_route_with_a_flow_takes_no_run_lock_and_leaves_a_running_task_alone(tree):
    path = str(tree["project"])
    request = ops.request(path, "Which market first?")["request"]
    running = ops.request(path, "Another.", flow="demo")["tasks"][0]["id"]
    ctx = ops_core.context(path)
    ctx["store"].task_claim(ctx["conn"], running)                                             # a task is running now
    with locked(tree):
        named = ops.route(path, request, "demo")
    assert named["routed"] is True and named["source"] == "named" and named["recovered"] == []
    assert ops.task(path, running)["task"]["state"] == "running"                              # not marked interrupted
    assert st.calls(tree["adapter"]) == []


# --- a question about the state is answered by code ---------------------------------------------------------------------


@pytest.mark.parametrize("line", [
    "status", "Status?", "como estamos", "Como estamos com o projeto?", "Como estamos em rela\u00e7\u00e3o ao brand?",
    "how are we", "How are we doing?", "how are we doing with the launch", "o que falta?", "O que falta",
    "what is running", "What's running now?", "what waits", "What waits for me?", "qual o status", "Qual \u00e9 o status do projeto?",
    "o que est\u00e1 rodando", "what are we waiting for", "progresso", "how is the project going"])
def test_the_closed_list_of_forms_is_a_question_about_the_state(line):
    assert ops_say.state_question(line) is True, line


@pytest.mark.parametrize("line", [
    "how are we going to launch the site", "Write the profile of the studio.",
    # a form that goes on to ask for work is the work (review of ADJ-R2): a mark inside the line, a verb of work in the tail,
    # a tail of more than six words
    "Como estamos com o brand? Crie a identidade do zero em azul", "how are we on the roadmap, delete the old plan",
    "how are we on the roadmap. Delete the old plan", "how are we on the roadmap delete the old plan",
    "como estamos com o brand crie a identidade", "how are we doing with one two three four five six seven",
    "status; then publish the post", "status of the invoice must be paid, please draft it",
    "/status", "what is running on port 80 in the container and why does it stop after ten minutes please explain",
    "como estamos indo para lan\u00e7ar o produto na semana que vem com tantas pessoas", "", "?!"])
def test_a_line_that_asks_for_work_is_not_a_question_about_the_state(line):
    assert ops_say.state_question(line) is False, line


def test_a_question_about_the_state_is_answered_by_code_with_no_model_no_request_even_during_a_run(tree):
    path = str(tree["project"])
    request = ops.request(path, "Find the first market.", flow="demo")
    market, profile = [t["id"] for t in request["tasks"]]
    with locked(tree):
        out = say(tree, "Como estamos com o projeto?")
    assert out["queued"] is False and out["ran"] is False and out["request_id"] is None and out["pending_id"] is None
    assert out["reply"].startswith(f'Request {request["request"]}, "Demo flow": 0 of 2 tasks done.')
    assert f'Ready: task {market}, "Market"' in out["reply"] and "What waits for you: nothing." in out["reply"]
    assert st.calls(tree["adapter"]) == []
    assert [m["role"] for m in messages(tree)] == ["user", "assistant"] and messages(tree)[1]["text"] == out["reply"]
    assert len(ops.status(path)["requests"]) == 1                                              # no request was made
    ran = ops.run_next(path)
    asked = say(tree, "what is running")["reply"]
    assert "What waits for you:" in asked and f"question" in asked and profile != market
    assert ran["pending_id"] and f'(decision {ran["pending_id"]})' in asked


def test_the_state_answer_names_what_finished_runs_waits_and_is_stuck(tree):
    state_reply = ops_say.state_reply
    project = str(tree["project"])
    assert state_reply(project) == "No request is open.\nWhat waits for you: nothing."
    ids = ops.request(project, "Find the first market.", flow="demo")["tasks"]
    ctx = ops_core.context(project)
    store, conn = ctx["store"], ctx["conn"]
    claimed = store.task_claim(conn, ids[0]["id"])["task"]
    assert claimed["state"] == "running"
    text = state_reply(project, proposed="Ask for the market analysis by name.")
    assert "Running now: Market." in text and "0 of 2 tasks done" in text
    assert text.endswith("\n\nThe planning agent proposes: Ask for the market analysis by name.")


# --- the direct turn ------------------------------------------------------------------------------------------------


def test_the_router_reads_a_direct_reply_with_its_next_line():
    assert router.read_route(DIRECT) == {"kind": "direct", "next": "Ask for the market analysis by name."}
    assert router.read_route("Route: none (direct)\nWhy: x\n") == {"kind": "direct", "next": ""}
    assert router.read_route("Route: core-critique (direct, ready)\nNext: answer it.\n") == {"kind": "direct", "next": "answer it."}
    assert router.read_route("Route: none (direct)\nNext: Q1: Which project? Recommended: this one.\n") == {"kind": "question"}
    for other in ("Route: none (capability, pending)\nWhy: x", "Route: none\nWhy: x", "Route: none (direct)\nRoute: none (direct)",
                  "Route: none (indirect)", "Route: none (direct) and more"):
        assert router.read_route(other)["kind"] == "unclassified", other


def test_a_direct_reply_is_answered_by_code_cancels_its_request_and_opens_no_decision(tree):
    path = str(tree["project"])
    reply(tree, DIRECT)
    out = say(tree, "Tell me something about the studio.")
    assert out["ran"] is True and out["request_id"] is None and out["pending_id"] is None and out["queued"] is False
    assert out["reply"].endswith("The planning agent proposes: Ask for the market analysis by name.")
    assert "Route: none" not in out["reply"] and "What waits for you:" in out["reply"]     # never the router's block
    assert ops.pending(path)["pending"] == []
    [recorded] = ops.status(path)["requests"]
    assert recorded["state"] == "cancelled"                                                  # cancelled by code, in the same call
    assert st.calls(tree["adapter"]) == ["core-orchestrator 1"]
    stored = [m for m in messages(tree) if m["role"] == "assistant"]
    assert stored[0]["text"] == out["reply"] and stored[0]["task_id"] is None and stored[0]["run_id"]
    # a direct reply to a form's route is left to the form: the request stays, the answer says what the planner proposes
    other = ops.request(path, "And the second?")["request"]
    routed = ops.route(path, other)
    assert routed["kind"] == "direct" and routed["next"] == "Ask for the market analysis by name." and routed["routed"] is False
    assert [r["state"] for r in ops.status(path)["requests"]] == ["cancelled", "requested"]
    assert ops.pending(path)["pending"] == []


def test_a_direct_reply_to_a_line_that_answers_the_routers_question_cancels_that_request_too(tree):
    path = str(tree["project"])
    reply(tree, ASKING)
    asked = say(tree, "Which market first?")
    reply(tree, DIRECT)
    out = say(tree, "Never mind, how is it going?")  # not a closed form: it answers the router's question
    assert out["ran"] is True and out["request_id"] is None
    assert ops.status(path)["requests"][0]["id"] == asked["request_id"]
    assert ops.status(path)["requests"][0]["state"] == "cancelled"


# --- the unrecognised route -------------------------------------------------------------------------------------------


def test_a_reply_that_names_no_route_opens_one_sentence_with_the_reply_whole_and_two_actions(tree):
    path = str(tree["project"])
    reply(tree, PROSE)
    out = say(tree, "Something unclear.")
    request = out["request_id"]
    item = ops.pending(path, out["pending_id"])
    assert item["kind"] == "question" and item["title"] == "The route was not recognised"
    assert item["body"] == f"The planning agent did not name a flow or a skill for request {request}"
    assert item["payload"]["raw"] == PROSE and item["payload"]["actions"] == ["choose-flow", "cancel"]
    assert item["payload"]["ending"] == "unclassified" and PROSE.strip() not in out["reply"]
    assert out["reply"].startswith(item["body"]) and f"/cancel {request}" in out["reply"] and "--flow <name>" in out["reply"]
    assert ops.status(path)["requests"][0]["state"] == "requested"                           # still waiting: the person decides


BUSY = "another run of this project is in progress: one task at a time per project"


def test_the_conversations_own_shell_drains_no_queue_so_it_refuses_a_line_during_a_run(tree, monkeypatch, capsys):
    import io
    chat = st.load("chat")
    monkeypatch.setattr("sys.stdin", io.StringIO("Which market first?\n/new Another request.\n/status\n"))
    with locked(tree):
        assert chat.main(["--project", str(tree["project"]), "--json"]) == 0      # the shell goes on after a refusal
        kept = messages(tree)
    captured = capsys.readouterr()
    assert captured.err.count(f"error: {BUSY}") == 2                                # the two lines that route are refused
    assert [(m["role"], m["text"]) for m in kept[:1]] == [("user", "/status")] and len(kept) == 2   # only the command was kept
    assert queue(tree) == [] and st.calls(tree["adapter"]) == []


def test_the_terminals_say_and_route_refuse_during_a_run_and_store_nothing(tree):
    cli = st.load("cli")
    path = str(tree["project"])
    request = ops.request(path, "Which market first?")["request"]
    with locked(tree):
        with pytest.raises(ops.OpsError) as refused:
            cli.run(["say", "--project", path, "--text", "Which market first?"])
        assert refused.value.code == 1 and str(refused.value) == BUSY
        with pytest.raises(ops.OpsError) as refused:
            cli.run(["route", "--project", path, "--request", str(request)])
        assert refused.value.code == 1 and str(refused.value) == BUSY
        assert queue(tree) == [] and messages(tree) == []
    assert ops.status(path)["requests"][0]["state"] == "requested"


def test_the_mcp_mode_drains_no_queue_so_its_say_and_route_are_refused_during_a_run(tree):
    import io
    import test_mcp as tm
    mcp = st.load("mcp")
    path = str(tree["project"])
    request = ops.request(path, "Which market first?")["request"]
    server = mcp.Server(ops, [{"id": mcp.project_id(path), "name": "p", "path": path}], log=lambda line: None, grace=2)
    described = {t["name"]: t["description"] for t in server.tools()}
    assert "refused, not queued" in described["say"] and "refused, not queued" in described["route"]
    with locked(tree):
        assert tm.refusal_of(tm.tool(server, "say", {"text": "Which market first?"})) == BUSY
        assert tm.refusal_of(tm.tool(server, "route", {"request_id": request})) == BUSY
        assert queue(tree) == [] and messages(tree) == []
    assert ops.status(path)["requests"][0]["state"] == "requested" and st.calls(tree["adapter"]) == []


def test_only_the_page_is_a_channel_that_queues(tree):
    assert ops_say.QUEUING_CHANNELS == ("page",)
    with locked(tree):
        for channel in (None, "chat", "terminal", "mcp"):
            with pytest.raises(ops.OpsError, match="in progress"):
                ops.say(str(tree["project"]), "Which market first?", channel=channel)
        assert ops.say(str(tree["project"]), "Which market first?", channel="page")["queued"] is True


def test_a_line_that_finds_the_lock_taken_after_the_check_is_recorded_as_a_request_and_queued(tree, monkeypatch):
    """The race between the check and the router's run: the request is recorded, `route` queues it, the person is told."""
    path = str(tree["project"])
    real = ops_say.run_busy
    monkeypatch.setattr(ops_say, "run_busy", lambda ctx: False)       # the check saw no run; one began since
    with locked(tree):
        out = page_say(tree, "Which market first?")
    assert out["queued"] is False and out["ran"] is False and out["pending_id"] is None and out["request_id"]
    assert out["reply"] == ops_say.QUEUED_REQUEST.format(request=out["request_id"])
    assert [(e["kind"], e["id"]) for e in queue(tree)] == [("route", out["request_id"])]
    assert [m["role"] for m in messages(tree)] == ["user", "assistant"] and messages(tree)[1]["task_id"] == out["request_id"]
    monkeypatch.setattr(ops_say, "run_busy", real)
    assert ops.route_queued(path)["routed"] == "route" and ops.pending(path)["pending"][0]["kind"] == "plan"


def test_a_queued_line_that_can_no_longer_be_answered_is_dropped_with_a_word_to_the_person(tree, monkeypatch):
    path = str(tree["project"])
    with locked(tree):
        page_say(tree, "Which market first?")
    monkeypatch.setattr(ops_say, "_turn", lambda *args: (_ for _ in ()).throw(ops.OpsError("the decision it answers is closed", 1)))
    out = ops.route_queued(path)
    assert out["routed"] is None and out["dropped"]["kind"] == "line" and queue(tree) == []
    assert messages(tree)[-1]["text"] == "A queued line was not answered: the decision it answers is closed"


def test_the_questions_about_the_state_are_not_part_of_the_routers_memory(tree):
    say(tree, "Como estamos?")
    say(tree, "Which market first?")
    prompt = (tree["adapter"] / "last-router-prompt.md").read_text(encoding="utf-8")
    assert prompt.startswith("Which market first?\n") and ops.MEMORY_HEAD not in prompt  # the first line of an exchange reaches the router plain


def test_the_terminal_verb_routes_one_queued_entry(tree, capsys):
    cli = st.load("cli")
    path = str(tree["project"])
    with locked(tree):
        page_say(tree, "Which market first?")
        assert cli.run(["route-queued", "--project", path])["reason"] == "a run is in progress"
    assert cli.run(["route-queued", "--project", path])["routed"] == "line"
    assert cli.main(["route-queued", "--project", path]) == 0
    assert json.loads(capsys.readouterr().out) == {"routed": None, "queued": 0}


def test_a_one_word_answer_that_looks_like_a_state_form_reaches_the_router_while_it_has_a_question_open(tree):
    path = str(tree["project"])
    reply(tree, ASKING)
    asked = say(tree, "Which market first?")
    reply(tree, FLOW, "router-reply-2.md")
    answered = say(tree, "progress")
    assert answered["request_id"] == asked["request_id"] and answered["ran"] is True and answered["pending_id"]
    assert "--- the user's answer 1 ---\nprogress" in (tree["adapter"] / "last-router-prompt.md").read_text(encoding="utf-8")
    assert ops.pending(path, answered["pending_id"])["kind"] == "plan"
    # with nothing open it is a state question again
    assert say(tree, "progress")["ran"] is False
    # and on the page, during a run, it is the answer to be queued, not a status
    reply(tree, ASKING)
    again = say(tree, "/new Who buys first?")
    assert again["pending_id"]
    with locked(tree):
        assert page_say(tree, "progress")["queued"] is True


# --- first in, first out ---------------------------------------------------------------------------------------------


def test_a_page_line_behind_older_entries_waits_behind_them_even_when_the_run_is_over(tree):
    path = str(tree["project"])
    with locked(tree):
        first = page_say(tree, "Which market first?")
    assert queue(tree)                                           # the run is over; the drain has not come yet
    second = page_say(tree, "Who buys first?")
    assert second["queued"] is True and second["reply"] is None and st.calls(tree["adapter"]) == []
    request = ops.request(path, "A request from the form.")["request"]
    assert ops.route(path, request, channel="page")["queued"] is True            # a request behind them waits too
    assert [(e["kind"], e["id"]) for e in queue(tree)] == [("line", first["message_id"]), ("line", second["message_id"]),
                                                          ("route", request)]
    answered = [ops.route_queued(path) for _ in range(3)]
    assert [(a["routed"], a.get("message_id") or a.get("request_id")) for a in answered] == [
        ("line", first["message_id"]), ("line", second["message_id"]), ("route", request)]
    assert queue(tree) == []
    # a shell that drains nothing is not made to wait for an entry: it is refused only when a run holds the project
    assert say(tree, "Another request.")["ran"] is True


def test_a_state_question_and_a_command_are_never_queued_behind_anything(tree):
    with locked(tree):
        page_say(tree, "Which market first?")
    assert page_say(tree, "Como estamos?")["queued"] is False and page_say(tree, "/status")["queued"] is False
    assert len(queue(tree)) == 1


def test_one_entry_is_taken_at_a_time_and_the_oldest_first(tree):
    path = str(tree["project"])
    with locked(tree):
        page_say(tree, "Which market first?")
        page_say(tree, "Who buys first?")
    ctx = ops_core.context(path)
    entries = queue(tree)
    ops_say._queue_write(ctx, [dict(entries[0], started=time.time()), entries[1]])            # the first is being routed
    assert ops.route_queued(path) == {"routed": None, "queued": 2, "reason": "another process is routing the first"}
    assert st.calls(tree["adapter"]) == []                                                     # the second was not taken


# --- the review's nits ------------------------------------------------------------------------------------------------


def test_a_queued_request_that_cannot_be_routed_leaves_a_note_the_person_reads(tree):
    path = str(tree["project"])
    request = ops.request(path, "Which market first?")["request"]
    with locked(tree):
        ops.route(path, request, channel="page")
    ops.cancel(path, request)
    out = ops.route_queued(path)
    assert out["dropped"] == {"kind": "route", "id": request}
    note = messages(tree)[-1]
    assert note["role"] == "assistant" and note["task_id"] == request
    assert note["text"].startswith(f"Request {request} was not routed: ") and "only a request that waits for its route" in note["text"]
    # one the service died on leaves the same kind of note
    other = ops.request(path, "Who buys first?")["request"]
    with locked(tree):
        ops.route(path, other, channel="page")
    ctx = ops_core.context(path)
    ops_say._queue_write(ctx, [dict(queue(tree)[0], started=time.time() - ops_say.queue_stale() - 5)])
    assert ops.route_queued(path) == {"routed": None, "queued": 0}
    assert messages(tree)[-1]["text"] == f"Request {other} was not routed: the service stopped while it was routed. Route it again when you want it planned."


def test_an_entry_that_is_dropped_leaves_the_queue_even_when_the_note_cannot_be_written(tree, monkeypatch):
    path = str(tree["project"])
    request = ops.request(path, "Which market first?")["request"]
    with locked(tree):
        ops.route(path, request, channel="page")
    ops.cancel(path, request)
    monkeypatch.setattr(ops_say, "_note_request", lambda *args: (_ for _ in ()).throw(RuntimeError("the store went away")))
    with pytest.raises(RuntimeError):
        ops.route_queued(path)
    assert queue(tree) == []                                    # not left behind, to be reported as "not answered" later


def test_a_taken_entry_is_dead_only_after_the_run_timeout_of_the_gate_file_plus_a_minute(tree, monkeypatch):
    path = str(tree["project"])
    timeout = ops.lab.reference("strong")["timeout_seconds"]
    assert ops_say.queue_stale() == timeout + 60
    with locked(tree):
        page_say(tree, "Which market first?")
        page_say(tree, "Who buys first?")
    ctx = ops_core.context(path)
    first, second = queue(tree)
    ops_say._queue_write(ctx, [dict(first, started=time.time() - timeout - 30), second])
    assert ops.route_queued(path)["reason"] == "another process is routing the first"      # younger than timeout + 60: kept
    ops_say._queue_write(ctx, [dict(first, started=time.time() - timeout - 90), second])
    assert ops.route_queued(path)["routed"] == "line"                                      # older: dropped, the next is routed
    assert "was not answered" in [m for m in messages(tree) if m["role"] == "assistant"][0]["text"]
    # the bound follows the gate file, not a number of this module
    real = ops.lab.reference
    monkeypatch.setattr(ops.lab, "reference", lambda tier="strong": dict(real(tier), timeout_seconds=1800))
    assert ops_say.queue_stale() == 1860
    monkeypatch.setattr(ops.lab, "reference", lambda tier="strong": (_ for _ in ()).throw(ops.lab.LabError("gate", "unreadable")))
    assert ops_say.queue_stale() == ops_say.QUEUE_STALE_FALLBACK + ops_say.QUEUE_STALE_MARGIN
