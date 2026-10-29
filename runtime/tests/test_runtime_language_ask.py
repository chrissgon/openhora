"""The answer from sources and the conversation in the project's language (package LR-1, runtime/phrases.py): the refusals and the checked answer of `ask`
(AQ-1), the hint to send `/ask`, the answer to a question about the state, the refusal to start the planning agent, the line of a router that could not
run, and the placeholder a reader that did not ask is shown. A project with no `language`, and a project whose tag has no table, gets the English
sentences it always got. The stand-in tree and adapter of test_ask.py; no model, no network; every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_runtime_language_ask.py
"""
from __future__ import annotations

import phrase_kit as pk
import standin_tree as st
from test_ask import (OWNER_KEY, PROFILES, SENDERS, accept, add_source, ask, direct_router, ops, ops_core, ops_say, roles,  # noqa: F401
                      tree, two)


phrases = st.load("phrases")
PT_CFG = {"language": "pt-BR"}


def in_parts(text, cfg, *specs) -> bool:
    """`text` is made of the sentences of these (key, fields) one right after the other (a piece of the table may start with a space)."""
    if not specs:
        return text == ""
    key, fields = specs[0]
    return any(pk.said(text[:cut], key, cfg, **fields) and in_parts(text[cut:], cfg, *specs[1:]) for cut in range(1, len(text) + 1))


def proposes(text, cfg, proposal) -> bool:
    """The last paragraph of `text` (after a blank line) is the sentence of PROPOSES followed by `proposal`."""
    _head, blank, last = text.rpartition("\n\n")
    return bool(blank) and last.endswith(proposal) and pk.said(last[: len(last) - len(proposal)], "PROPOSES", cfg)


def proposes_line(line, cfg, proposal) -> bool:
    """`line` is the sentence of PROPOSES followed by `proposal`."""
    return line.endswith(proposal) and pk.said(line[: len(line) - len(proposal)], "PROPOSES", cfg)


def ends_with_hint(text, cfg) -> bool:
    """The last paragraph of `text` (after a blank line) is the hint to send /ask."""
    _head, blank, last = text.rpartition("\n\n")
    return bool(blank) and pk.said(last, "ASK_HINT", cfg)


def assert_idle(text, cfg, finished):
    """The answer about the state of a project with nothing open: no request is open and `finished` finished, then what waits for the person is nothing."""
    first, waits = text.split("\n")
    assert in_parts(first, cfg, ("STATE_NONE_OPEN", {}), ("STATE_FINISHED", {"n": finished})), first
    key, fields = pk.which(waits, cfg)
    assert key == "STATE_WAITS", waits
    pk.assert_said(fields["items"], "STATE_NOTHING", cfg)


def speak(tree_, tag):
    accept(tree_["path"], language=tag)


def test_the_configuration_read_carries_the_language_the_bridge_says_its_sentences_in(tree):
    assert ops.config(tree["path"])["language"] is None
    speak(tree, "pt-BR")
    assert ops.config(tree["path"])["language"] == "pt-BR"


# --- what `ask` answers when it cannot ------------------------------------------------------------------------------------------------------------------


def test_the_refusals_of_ask_are_in_the_projects_language(tree, monkeypatch):
    speak(tree, "pt-BR")
    pk.assert_said(ask(tree)["reply"], "NO_SOURCES", PT_CFG)
    for n in range(6):
        add_source(tree, f"doc-{n}", f"# Document {n}\n\nSome text about topic {n}.\n")
    pk.assert_said(ask(tree, "qual o prazo do contrato?")["reply"], "NO_MATCH", PT_CFG, ids="@doc-0, @doc-1, @doc-2, @doc-3, @doc-4, @doc-5")
    pk.assert_said(ask(tree, " ".join(f"@doc-{n}" for n in range(6)) + " what is in them?")["reply"], "TOO_MANY", PT_CFG, max=5, n=6)
    add_source(tree, "ledger-a", "# Ledger\n" + "x" * (200 * 1024))
    add_source(tree, "ledger-b", "# Ledger\n" + "y" * (100 * 1024))
    pk.assert_said(ask(tree, "compare @ledger-a and @ledger-b")["reply"], "ASK_TOO_LARGE", PT_CFG, kib=256, named="ledger-a (200 KiB), ledger-b (100 KiB)")
    monkeypatch.setattr(roles, "answer", lambda root=None, file=None: None)
    pk.assert_said(ask(tree)["reply"], "NOT_BUILT", PT_CFG)


def test_the_same_refusals_in_a_project_with_no_language_are_the_english_ones(tree, monkeypatch):
    pk.assert_said(ask(tree)["reply"], "NO_SOURCES", None)
    for tag in ("fr", "en"):
        speak(tree, tag)
        pk.assert_said(ask(tree)["reply"], "NO_SOURCES", {"language": tag})
    monkeypatch.setattr(roles, "answer", lambda root=None, file=None: None)
    pk.assert_said(ask(tree)["reply"], "NOT_BUILT", None)


def read_after_blank(reply, cfg) -> bool:
    """A line of the reply says which two sources were read, and the line before it is blank."""
    read = ", ".join(phrases.text("READ_VERSION", cfg, source=name, version=1) for name in ("lease-contract", "meeting-notes"))
    lines = reply.split("\n")
    return any(i > 0 and lines[i - 1] == "" and pk.said(line, "READ", cfg, read=read) for i, line in enumerate(lines))


def test_a_checked_answer_has_its_frame_in_the_language_and_the_skills_own_words_are_not_touched(two):
    english = ask(two)
    assert english["answer"] == "found" and pk.said(english["reply"], "QUOTE_CHECKED", None)
    assert read_after_blank(english["reply"], None)
    speak(two, "pt-BR")
    portuguese = ask(two)
    assert portuguese["answer"] == "found" and portuguese["flags"] == []
    assert pk.said(portuguese["reply"], "QUOTE_CHECKED", PT_CFG) and not pk.said(portuguese["reply"], "QUOTE_CHECKED", None)
    assert read_after_blank(portuguese["reply"], PT_CFG) and not pk.said(portuguese["reply"], "READ", None)
    assert "O prazo do contrato e de 12 meses" in portuguese["reply"], "the answer is the skill's own text, in the language of the question"
    speak(two, "fr")
    assert pk.said(ask(two)["reply"], "QUOTE_CHECKED", {"language": "fr"})


# --- the conversation ---------------------------------------------------------------------------------------------------------------------------------


def test_the_answer_to_a_question_about_the_state_is_in_the_projects_language(two):
    ask(two)
    english = ops_say.state_reply(two["path"])
    assert_idle(english, None, 1)
    speak(two, "pt-BR")
    assert_idle(ops_say.state_reply(two["path"]), PT_CFG, 1)
    said = ops.say(two["path"], "how are we doing?", channel="terminal")["reply"]
    assert_idle(said, PT_CFG, 1)
    speak(two, "fr")
    assert ops_say.state_reply(two["path"]) == english


def test_the_state_of_a_project_with_work_open_names_every_part_in_portuguese(two, monkeypatch):
    """Each line of the answer, from a status and a progress read that hold one of every kind of row."""
    state = {"requests": [{"id": 4, "title": "Launch", "state": "planned", "tasks": [
        {"id": 5, "title": "Copy", "state": "done"}, {"id": 6, "title": "Images", "state": "running"}, {"id": 7, "title": "Review", "state": "waiting"},
        {"id": 8, "title": "Post", "state": "ready"}, {"id": 9, "title": "Send", "state": "blocked", "note": "needs a key"},
        {"id": 10, "title": "Tidy", "state": "failed"}]}, {"id": 11, "title": "Later", "state": "requested", "tasks": []}],
        "held": [{"task_id": 8, "reason": "paused"}]}
    progress = {"progress": {"waiting_for_you": [{"kind": "plan", "title": "Launch", "pending_id": 12}, {"kind": "effect", "title": "Post", "pending_id": 13}]}}
    fake = type("Ops", (), {"status": staticmethod(lambda project: state), "progress": staticmethod(lambda project: progress)})
    monkeypatch.setattr(ops_say, "_ops", lambda: fake)
    def expected(cfg):
        """The lines of the answer, as the phrase keys that say them (the status words and the kind words are the table's own)."""
        word = lambda status: phrases.status(status, cfg)      # noqa: E731
        kind = lambda name: phrases.kind_word(name, cfg)      # noqa: E731
        return [("STATE_PROGRESS", {"id": 4, "title": "Launch", "done": 1, "total": 6, "names": " (Copy)"}), ("STATE_RUNNING", {"names": "Images"}), ("STATE_WAITING", {"names": "Review"}),
                ("STATE_READY", {"id": 8, "title": "Post", "held": phrases.text("STATE_HELD", cfg, reason="paused")}),
                ("STATE_STUCK", {"id": 9, "title": "Send", "state": word("blocked"), "note": ": needs a key"}), ("STATE_STUCK", {"id": 10, "title": "Tidy", "state": word("failed"), "note": ""}),
                ("STATE_RECORDED", {"id": 11, "title": "Later"}),
                ("STATE_WAITS", {"items": phrases.text("STATE_WAIT_ITEM", cfg, kind=kind("plan"), title="Launch", id=12) + "; " + phrases.text("STATE_WAIT_ITEM", cfg, kind=kind("effect"), title="Post", id=13)})]
    for tag in (None, "pt-BR"):
        cfg = {"language": tag}
        lines = ops_say.state_reply(two["path"], cfg=cfg).splitlines()
        assert len(lines) == len(expected(cfg)), lines
        for line, (key, fields) in zip(lines, expected(cfg)):
            pk.assert_said(line, key, cfg, **fields)
    assert proposes(ops_say.state_reply(two["path"], "Say hello.", PT_CFG), PT_CFG, "Say hello.")
    assert proposes(ops_say.state_reply(two["path"], "Say hello.", {}), {}, "Say hello.")
    many = [{"id": n, "title": f"T{n}", "state": "done"} for n in range(20, 28)]
    state["requests"] = [{"id": 4, "title": "Big", "state": "planned", "tasks": many}]
    for cfg in ({}, PT_CFG):
        assert pk.said(ops_say.state_reply(two["path"], cfg=cfg), "STATE_PROGRESS", cfg, id=4, title="Big", done=8, total=8,
                       names=f" (T20, T21, T22, T23, T24{phrases.text('NAMES_MORE', cfg, n=3)})")


def test_a_direct_turn_ends_with_the_hint_in_the_language(two, monkeypatch):
    direct_router(two, monkeypatch)
    speak(two, "pt-BR")
    said = ops.say(two["path"], "thanks, nothing else", channel="terminal")["reply"]
    assert pk.said(said.split("\n")[0], "STATE_NONE_OPEN", PT_CFG) and ends_with_hint(said, PT_CFG)
    assert any(proposes_line(line, PT_CFG, "nothing to do.") for line in said.split("\n")) and not any(proposes_line(line, None, "nothing to do.") for line in said.split("\n"))
    speak(two, None)
    assert ends_with_hint(ops.say(two["path"], "thanks again", channel="terminal")["reply"], None)


def test_the_planning_agent_that_may_not_start_is_told_in_the_language(two, monkeypatch):
    monkeypatch.setattr(ops_say, "_planning_may_start", lambda ctx: (False, "its day is spent"))
    pk.assert_said(ops.say(two["path"], "plan the launch", channel="terminal")["reply"], "PLANNING_NOT_STARTED", None, why="its day is spent")
    speak(two, "pt-BR")
    pk.assert_said(ops.say(two["path"], "plan the launch", channel="terminal")["reply"], "PLANNING_NOT_STARTED", PT_CFG, why="its day is spent")


def test_the_line_of_a_router_that_could_not_run_and_the_queued_request_are_in_the_language(two, monkeypatch):
    ctx = ops_core.context(two["path"])
    fake = type("Ops", (), {"request": staticmethod(lambda project, text, **kw: {"request": 3}),
                            "route": staticmethod(lambda project, request_id, channel=None: {"failure": {"reason": "boom"}, "run_id": None})})
    monkeypatch.setattr(ops_say, "_ops", lambda: fake)
    monkeypatch.setattr(ops_say, "_planning_may_start", lambda ctx: (True, ""))
    pk.assert_said(ops_say._say_route(two["path"], ctx, "plan it", 10 ** 9, "terminal")[0], "ROUTER_FAILED", None, failure="boom")
    speak(two, "pt-BR")
    ctx = ops_core.context(two["path"])
    pk.assert_said(ops_say._say_route(two["path"], ctx, "plan it", 10 ** 9, "terminal")[0], "ROUTER_FAILED", PT_CFG, failure="boom")
    fake.route = staticmethod(lambda project, request_id, channel=None: {"queued": True})
    pk.assert_said(ops_say._say_route(two["path"], ctx, "plan it", 10 ** 9, "terminal")[0], "QUEUED_REQUEST", PT_CFG, request=3)


def test_the_placeholder_a_reader_that_did_not_ask_is_shown_is_in_the_language(two):
    accept(two["path"], policies=PROFILES, messaging={"senders": SENDERS})
    speak(two, "pt-BR")
    ops.say(two["path"], "/ask qual o prazo do contrato?", channel="messaging", sender=OWNER_KEY)
    request = ops.conversation(two["path"], channel="mcp")["messages"][-1]
    assert pk.said(request["text"], "ANSWERED_AS", PT_CFG)
    speak(two, None)
    assert pk.said(ops.conversation(two["path"], channel="mcp")["messages"][-1]["text"], "ANSWERED_AS", None)


def test_what_a_shell_reads_keeps_the_english_status_word_in_a_portuguese_project(two):
    speak(two, "pt-BR")
    out = ask(two)
    state = ops.status(two["path"])
    [row] = [r for r in state["requests"] if r["id"] == out["request_id"]]
    assert row["state"] == "done", "status, the API and the MCP mode read the operations layer: the store's word"
    store, conn = two["ctx"]["store"], two["ctx"]["conn"]
    assert store.task_get(conn, out["request_id"])["state"] == "done" and store.task_run_get(conn, out["run_id"])["status"] == "ok"
    assert "done" in repr(ops.status(two["path"])["requests"]) and "concluído" not in repr(ops.status(two["path"]))
