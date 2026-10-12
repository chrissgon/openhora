"""Tests of the conversation with the planning agent (stage 6, WP-6.8): ops.say and its shell, runtime/chat.py, on the
stand-in tree of standin_tree.py with a stand-in router. Offline; invented names only.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_chat.py
"""
from __future__ import annotations

import io
import json
import re

import pytest

import standin_tree as st

lab = st.load("lab")
ops = st.load("ops")
ops_core = st.load("ops_core")
plan = st.load("plan")
router = st.load("router")
chat = st.load("chat")

PACKS = {"planning": ["core-clarify", "core-orchestrator"], "biz": ["demo-asks", "demo-writes"]}
AGENTS = {"planning": {"pack": "planning", "max_runs_per_day": 10}, "business": {"pack": "biz", "max_runs_per_day": 10}}
BRANCH = r'''
if [ "$skill" = core-orchestrator ]; then
  reply="$here/router-reply.md"
  if grep -q "the user's answer" "$prompt" && [ -f "$here/router-reply-2.md" ]; then reply="$here/router-reply-2.md"; fi
  cp "$prompt" "$here/last-router-prompt.md"
  cp "$reply" "$out/response.md"
  exit 0
fi
'''
FLOW = "Route: flow-demo (flow, pending)\nWhy: a market question\nNext: the market task.\n"
ASKING = "Route: flow-demo (flow, pending)\nWhy: a market question\nNext: Q1: Which project? Recommended: this one.\n"


@pytest.fixture
def tree(tmp_path, monkeypatch):
    built = st.build(tmp_path, monkeypatch, lab)
    st.skill(built["tree"], router.ROUTER_SKILL, "docs/workbench/state.md", "")
    script = built["adapter"] / "run-prompt.sh"
    text = st.ADAPTER.replace("for name in demo-asks demo-writes;", "for name in demo-asks demo-writes core-orchestrator;")
    script.write_text(text.replace('case "$skill" in', BRANCH + 'case "$skill" in', 1), encoding="utf-8")
    monkeypatch.setattr(ops_core, "ROOT", str(built["tree"]))
    monkeypatch.setattr(plan, "resolve_pack", lambda pack, root: list(PACKS[pack]))
    configure(built, AGENTS)
    reply(built, FLOW)
    return built


def configure(tree, agents) -> None:
    path = tree["project"] / "docs" / "workbench" / "runtime.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["area_agents"] = agents
    path.write_text(json.dumps(raw), encoding="utf-8")
    project = str(tree["project"])
    ops.accept_config(project, ops.project_config.load(project)["sha256"])


def reply(tree, text: str, name: str = "router-reply.md") -> None:
    (tree["adapter"] / name).write_text(text, encoding="utf-8")


def router_prompt(tree) -> str:
    return (tree["adapter"] / "last-router-prompt.md").read_text(encoding="utf-8")


def say(tree, line: str) -> dict:
    return ops.say(str(tree["project"]), line)


def messages(tree) -> list:
    ctx = ops_core.context(str(tree["project"]))
    return ctx["store"].messages_list(ctx["conn"], ops.CONVERSATION, limit=500)


def test_a_plain_line_becomes_a_request_and_the_reply_shows_its_plan(tree):
    out = say(tree, "Which market should the invented studio go after first?")
    assert out["ran"] is True and out["request_id"] and out["pending_id"]
    item = ops.pending(str(tree["project"]), out["pending_id"])
    assert item["kind"] == "plan"
    assert "- market: Market (demo-asks)" in out["reply"] and "- profile: Profile (demo-writes)" in out["reply"]
    assert "Estimate: 4 runs" in out["reply"] and out["reply"].endswith(f"Approve with /approve {out['pending_id']}")


def test_a_line_after_the_router_s_question_is_its_answer(tree):
    reply(tree, ASKING)
    reply(tree, FLOW, "router-reply-2.md")
    asked = say(tree, "Which market first?")
    assert asked["reply"].startswith(ASKING.rstrip("\n")) and asked["reply"].endswith(ops.ASK_NEXT)
    answered = say(tree, "The clinic project.")
    assert answered["request_id"] == asked["request_id"]
    assert ops.pending(str(tree["project"]), answered["pending_id"])["kind"] == "plan"
    assert "--- the user's answer 1 ---\nThe clinic project." in router_prompt(tree)


def test_new_starts_another_request_whatever_is_open(tree):
    reply(tree, ASKING)
    asked = say(tree, "Which market first?")
    other = say(tree, "/new Write the invented studio's profile.")
    assert other["request_id"] != asked["request_id"] and other["ran"] is True
    assert ops.pending(str(tree["project"]), asked["pending_id"])["status"] == "open"


def test_a_command_calls_its_operation_once_and_no_model(tree, monkeypatch):
    calls = []
    monkeypatch.setattr(ops, "release", lambda project, pending_id: calls.append(pending_id) or {"released": pending_id})
    out = say(tree, "/release 7")
    assert calls == [7] and json.loads(out["reply"]) == {"released": 7} and out["ran"] is False
    assert "Waiting for you" in say(tree, "/progress 7d")["reply"]
    assert json.loads(say(tree, "/status")["reply"])["requests"] == []
    assert st.calls(tree["adapter"]) == []


def test_an_unknown_command_gets_the_help_and_runs_nothing(tree):
    for line in ("/frobnicate", "/release", "/release seven", "/approve-policy x", "/set-mode a b", "/pin"):
        out = say(tree, line)
        assert out["reply"] == ops.operations.chat_help() and out["ran"] is False, line
    assert st.calls(tree["adapter"]) == [] and ops.pending(str(tree["project"]))["pending"] == []


def test_the_first_line_of_an_exchange_reaches_the_router_without_memory(tree):
    say(tree, "Which market first?")
    assert router_prompt(tree).startswith("Which market first?\n") and ops.MEMORY_HEAD not in router_prompt(tree)
    out = say(tree, "Which market first?")
    say(tree, f"/approve {out['pending_id']}")
    say(tree, "Write the profile next.")  # the earlier request is planned: a new exchange
    assert router_prompt(tree).startswith("Write the profile next.\n")


def test_the_memory_is_the_last_turns_cut_to_its_budget_oldest_dropped_first(tree):
    rows = [{"role": "user", "text": f"line {n} " + "x" * 900, "task_id": None} for n in range(8)]
    rows.insert(0, {"role": "assistant", "text": "settled plan", "task_id": 1})
    rows.insert(3, {"role": "user", "text": "/status", "task_id": None})
    memory = ops.chat_memory(rows, {1})
    lines = memory.split("\n")
    assert lines[0] == ops.MEMORY_HEAD and len(memory) <= ops.MEMORY_CHARS
    assert [re.match(r"user: line (\d)", line).group(1) for line in lines[1:]] == ["2", "3", "4", "5", "6", "7"]
    assert all(len(line) <= len("user: ") + ops.MEMORY_CUT for line in lines[1:]) and "/status" not in memory
    small = ops.chat_memory([{"role": "user", "text": f"turn {n}\n- not a delivery", "task_id": None} for n in range(9)], set())
    assert small.count("\n") == ops.MEMORY_TURNS and "turn 3" in small and "turn 2" not in small
    assert not [line for line in small.split("\n") if line.lstrip().startswith("- ")]  # no line reads as a delivery
    reply(tree, ASKING)
    say(tree, "Which market first?")
    say(tree, "/new And who buys first?")
    prompt = router_prompt(tree)
    assert prompt.startswith(ops.MEMORY_HEAD + "\nuser: Which market first?\nassistant: Route: flow-demo")
    assert f"\n\n{ops.MEMORY_TAIL}\nAnd who buys first?\n" in prompt


def test_a_reply_of_the_model_is_never_read_as_a_command(tree):
    first = say(tree, "Which market first?")
    reply(tree, f"/release {first['pending_id']}\n")
    out = say(tree, "Something else.")
    # The reply names no route: the person gets one sentence, the model's text is kept whole in the decision's payload
    # (A-25) and is shown, never executed.
    assert out["reply"].startswith(f"The planning agent did not name a flow or a skill for request {out['request_id']}")
    assert ops.pending(str(tree["project"]), out["pending_id"])["payload"]["raw"] == f"/release {first['pending_id']}\n"
    assert ops.pending(str(tree["project"]), first["pending_id"])["status"] == "open"


def test_the_planning_agent_at_its_cap_runs_nothing_and_says_why(tree, monkeypatch):
    stand_in = lab.reference
    monkeypatch.setattr(lab, "reference", lambda tier="strong": dict(stand_in(tier), model="m" if tier == "strong" else "fm"))
    configure(tree, {**AGENTS, "planning": {"pack": "planning", "max_runs_per_day": 1}})
    say(tree, "Which market first?")
    out = say(tree, "/new Who buys first?")
    assert out["ran"] is False and "cap: runs per day" in out["reply"] and out["request_id"] is None
    assert st.calls(tree["adapter"]) == ["core-orchestrator 1"]
    configure(tree, {**AGENTS, "planning": {"pack": "planning", "mode": "stopped", "max_runs_per_day": 10}})
    assert "stopped" in say(tree, "Who buys first?")["reply"]


def test_the_shell_reads_lines_from_standard_input_and_imports_only_the_operations_layer(tree, monkeypatch, capsys):
    source = (st.RUNTIME / "chat.py").read_text(encoding="utf-8")
    imported = re.findall(r"^\s*(?:import|from)\s+([a-z_]+)", source, re.M)
    assert [name for name in imported if name not in ("__future__", "json", "os", "sys")] == ["ops"]
    monkeypatch.setattr("sys.stdin", io.StringIO("Which market first?\n\n/status\n"))
    assert chat.main(["--project", str(tree["project"]), "--json"]) == 0
    printed = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert len(printed) == 2 and printed[0]["ran"] is True and printed[1]["ran"] is False
    assert chat.main(["--help"]) == 0 and chat.main(["--project"]) == 2


def test_both_sides_of_the_conversation_are_kept_in_the_store(tree):
    out = say(tree, "Which market first?")
    say(tree, "/status")
    rows = messages(tree)
    assert [(m["role"], m["task_id"]) for m in rows] == [("user", None), ("assistant", out["request_id"]),
                                                        ("user", None), ("assistant", None)]
    assert rows[0]["text"] == "Which market first?" and rows[1]["text"] == out["reply"] and rows[1]["run_id"]
