"""Tests for run-prompt.sh with a stand-in `claude` on PATH (no model is called).

Run: uv run --with pytest pytest adapters/claude-code/tests
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "run-prompt.sh"
FAKE = """#!/usr/bin/env bash
python3 - "$@" <<'PY'
import json, os, sys
json.dump({"args": sys.argv[1:], "mcp": os.environ.get("ENABLE_CLAUDEAI_MCP_SERVERS"),
           "budget": os.environ.get("SLASH_COMMAND_TOOL_CHAR_BUDGET"),
           "credentials": {k: os.environ[k] for k in ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY", "CLAUDE_CODE_WEB_API_KEY")
                           if k in os.environ}}, open(os.environ["FAKE_LOG"], "w"))
PY
echo '{"result": "done"}'
"""


@pytest.fixture
def env(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "claude").write_text(FAKE)
    (bin_dir / "claude").chmod(0o755)
    skill = tmp_path / "skills" / "demo"
    (skill / "scripts").mkdir(parents=True)
    (skill / "SKILL.md").write_text("demo\n")
    (skill / "scripts" / "check.py").write_text("print(1)\n")
    dep = tmp_path / "skills" / "dep"
    dep.mkdir()
    (dep / "SKILL.md").write_text("dep\n")
    (tmp_path / "cwd").mkdir()
    (tmp_path / "prompt.md").write_text("hello\n")
    return {"tmp": tmp_path, "skill": skill, "dep": dep, "log": tmp_path / "log.json",
            "env": {"PATH": f"{bin_dir}:{os.environ['PATH']}", "HOME": str(tmp_path), "FAKE_LOG": str(tmp_path / "log.json"),
                    "WB_EVAL_CONTAINER": "1"}}


def run(e, *extra):
    t = e["tmp"]
    cmd = ["bash", str(SCRIPT), "--prompt-file", str(t / "prompt.md"), "--cwd", str(t / "cwd"), "--model", "m",
           "--out", str(t / "out"), *extra]
    return subprocess.run(cmd, capture_output=True, text=True, env=e["env"])


def test_the_adapter_installs_nothing_and_connectors_are_off(env):
    """The runner stages the skills before the adapter starts (scripts/stage_skills.py): the adapter runs the prompt."""
    r = run(env)
    assert r.returncode == 0, r.stderr
    assert list((env["tmp"] / "cwd").iterdir()) == []  # no skill folder, no shared folder: nothing was written
    log = json.loads(env["log"].read_text())
    assert "--strict-mcp-config" in log["args"] and log["mcp"] == "false"
    assert (env["tmp"] / "out" / "response.md").read_text() == "done"


@pytest.mark.parametrize("flag", ["--skill-dir", "--extra-skill-dir"])
def test_the_options_that_made_the_adapter_copy_a_skill_are_gone(env, flag):
    r = run(env, flag, str(env["skill"]))
    assert r.returncode == 2 and "unknown option" in r.stderr
    assert not env["log"].exists() and list((env["tmp"] / "cwd").iterdir()) == []


def test_a_skill_the_runner_staged_is_left_as_it_is(env):
    staged = env["tmp"] / "cwd" / ".claude" / "skills" / "demo"
    staged.mkdir(parents=True)
    (staged / "SKILL.md").write_text("staged by the runner\n")
    r = run(env)
    assert r.returncode == 0, r.stderr
    assert (staged / "SKILL.md").read_text() == "staged by the runner\n"
    assert sorted(p.name for p in (env["tmp"] / "cwd" / ".claude").iterdir()) == ["skills"]


def test_the_manifest_names_where_the_harness_finds_skills_and_what_carries_its_settings():
    manifest = json.loads((SCRIPT.parent / "adapter.json").read_text(encoding="utf-8"))
    block = json.loads((SCRIPT.parent / "eval.json").read_text(encoding="utf-8"))
    assert block["skills_dir"] == ".claude/skills"
    # Its settings folder, its server list and its project-instructions files: the runner refuses a case that carries one.
    assert set(block["settings"]) == {".claude", ".mcp.json", "CLAUDE.md", "CLAUDE.local.md"}
    assert manifest["eval_runner"] == "run-prompt.sh" and manifest["runtime_runner"] == "run-agent.sh"
    assert (SCRIPT.parent / manifest["runtime_runner"]).is_file()
    assert set(manifest["consumes"]) == set(manifest["strategy"])  # nothing consumed without saying how


def test_max_cost_becomes_a_budget_and_bad_values_are_refused(env):
    r = run(env, "--max-cost-usd", "0.50")
    assert r.returncode == 0, r.stderr
    args = json.loads(env["log"].read_text())["args"]
    assert args[args.index("--max-budget-usd") + 1] == "0.50"
    assert run(env, "--max-cost-usd", "0.5; rm -rf x").returncode == 2


# --- stopping the adapter stops what the CLI started; HOME is left alone ---------------------------

def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def gone(pid, seconds=8):
    import time
    end = time.monotonic() + seconds
    while alive(pid) and time.monotonic() < end:
        time.sleep(0.1)
    return not alive(pid)


def stand_in(e, body):
    cli = e["tmp"] / "bin" / "claude"
    cli.write_text("#!/usr/bin/env bash\n" + body)
    cli.chmod(0o755)


def test_what_the_cli_leaves_in_the_background_stops_when_it_returns(env):
    stand_in(env, f"sleep 300 &\necho $! > {env['tmp']}/child.pid\necho '{{\"result\": \"done\"}}'\n")
    r = run(env)
    assert r.returncode == 0, r.stderr
    assert (env["tmp"] / "out" / "response.md").read_text() == "done"
    assert gone(int((env["tmp"] / "child.pid").read_text()))


def test_a_stopped_adapter_stops_the_cli_and_its_children(env):
    import signal
    import time
    stand_in(env, f"sleep 300 &\necho $! > {env['tmp']}/child.pid\necho $$ > {env['tmp']}/cli.pid\nsleep 300\n")
    t = env["tmp"]
    proc = subprocess.Popen(["bash", str(SCRIPT), "--prompt-file", str(t / "prompt.md"), "--cwd", str(t / "cwd"),
                             "--model", "m", "--out", str(t / "out")], env=env["env"], start_new_session=True)
    end = time.monotonic() + 10
    while not ((t / "cli.pid").exists() and (t / "cli.pid").read_text().strip()) and time.monotonic() < end:
        time.sleep(0.05)
    child, cli = int((t / "child.pid").read_text()), int((t / "cli.pid").read_text())
    proc.send_signal(signal.SIGTERM)
    assert proc.wait(timeout=15) == 143
    assert gone(child) and gone(cli)


def test_inside_the_eval_container_every_tool_is_allowed_and_the_web_only_when_asked(env):
    r = run(env)
    assert r.returncode == 0, r.stderr
    args = json.loads(env["log"].read_text())["args"]
    assert "--dangerously-skip-permissions" in args and "--settings" not in args and "--allowedTools" not in args
    assert args[args.index("--disallowedTools") + 1] == "WebSearch,WebFetch"
    r = run(env, "--allow-web")
    assert r.returncode == 0, r.stderr
    assert "--disallowedTools" not in json.loads(env["log"].read_text())["args"]


def test_a_grading_call_gets_no_tool_at_all(env):
    """--no-tools: the grader holds the tier's credential and reads text a model wrote; it is given nothing to act with."""
    r = run(env, "--no-tools")
    assert r.returncode == 0, r.stderr
    args = json.loads(env["log"].read_text())["args"]
    assert args[args.index("--tools") + 1] == ""  # the CLI's way to disable every built-in tool
    assert "--dangerously-skip-permissions" not in args and "--disallowedTools" not in args and "--allowedTools" not in args
    assert "--strict-mcp-config" in args  # and no server's tools either
    assert (env["tmp"] / "out" / "response.md").read_text() == "done"
    env["log"].unlink()
    r = run(env, "--no-tools", "--allow-web")
    assert r.returncode == 2 and "do not go together" in r.stderr and not env["log"].exists()


def test_a_model_run_keeps_its_tools(env):
    r = run(env)
    assert r.returncode == 0, r.stderr
    assert "--tools" not in json.loads(env["log"].read_text())["args"]


def test_outside_the_eval_container_the_adapter_refuses_to_start(env):
    env["env"]["WB_EVAL_CONTAINER"] = ""
    r = run(env)
    assert r.returncode == 2 and "only inside the container" in r.stderr
    assert not env["log"].exists() and not (env["tmp"] / "out").exists()


def test_a_command_allowance_is_no_longer_an_option(env):
    assert run(env, "--allow-command", "git status").returncode == 2


def test_the_skill_listing_budget_is_raised_so_the_skill_keeps_its_description(env):
    r = run(env)
    assert r.returncode == 0, r.stderr
    assert int(json.loads(env["log"].read_text())["budget"]) >= 100000



def test_the_low_limit_key_of_a_web_case_replaces_the_accounts_token(env):
    """The runner passes CLAUDE_CODE_WEB_API_KEY, and not the token, to a run on the open network."""
    token, key = "value-of-the-token", "value-of-the-low-limit-key"
    env["env"]["CLAUDE_CODE_OAUTH_TOKEN"] = token
    r = run(env)
    assert r.returncode == 0, r.stderr
    assert json.loads(env["log"].read_text())["credentials"] == {"CLAUDE_CODE_OAUTH_TOKEN": token}
    env["env"]["CLAUDE_CODE_WEB_API_KEY"] = key
    r = run(env, "--allow-web")
    assert r.returncode == 0, r.stderr
    assert json.loads(env["log"].read_text())["credentials"] == {"ANTHROPIC_API_KEY": key}  # and no token


def test_the_manifest_names_what_an_exhausted_account_answers():
    block = json.loads((SCRIPT.parent / "eval.json").read_text(encoding="utf-8"))
    assert block["account_limit"] and all(isinstance(m, str) and m for m in block["account_limit"])



STREAM = [
    {"type": "system", "subtype": "init", "model": "m"},
    {"type": "assistant", "message": {"content": [{"type": "text", "text": "Let me look at the brief first."},
                                                  {"type": "tool_use", "name": "Skill", "input": {"skill": "demo"}}]}},
    {"type": "user", "message": {"content": [{"type": "tool_result", "content": "the skill's text"}]}},
    {"type": "assistant", "message": {"content": [{"type": "text", "text": "Now I read the other one."},
                                                  {"type": "tool_use", "name": "Read",
                                                   "input": {"file_path": "/eval/case/.claude/skills/dep/SKILL.md"}},
                                                  {"type": "tool_use", "name": "Read", "input": {"file_path": "/eval/case/notes.md"}}]}},
    {"type": "assistant", "message": {"content": [{"type": "text", "text": "The final answer, with its two parts."}]}},
    {"type": "result", "subtype": "success", "result": "The final answer, with its two parts.", "num_turns": 4,
     "usage": {"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 100, "cache_creation_input_tokens": 1},
     "total_cost_usd": 0.01, "duration_ms": 1234},
]


def test_the_reply_is_the_last_message_and_the_stream_is_kept_beside_it(env):
    """Narration between turns stays in the stream; the reply the grader gets is the assistant's last message."""
    lines = "\n".join(json.dumps(e) for e in STREAM)
    stand_in(env, f"cat > /dev/null\ncat <<'EOF'\n{lines}\nEOF\n")
    r = run(env)
    assert r.returncode == 0, r.stderr
    out = env["tmp"] / "out"
    assert (out / "response.md").read_text() == "The final answer, with its two parts."
    assert "Let me look at the brief first." in (out / "stream.jsonl").read_text()
    assert json.loads((out / "raw.json").read_text())["num_turns"] == 4  # the result event, which the runner reads
    timing = json.loads((out / "timing.json").read_text())
    assert (timing["total_tokens"], timing["cost_usd"], timing["duration_ms"]) == (116, 0.01, 1234)
    assert timing["skills_loaded"] == ["demo", "dep"]  # the skill tool, and a read of a skill's SKILL.md


def test_the_cli_is_asked_for_its_stream(env):
    r = run(env)
    assert r.returncode == 0, r.stderr
    args = json.loads(env["log"].read_text())["args"]
    assert args[args.index("--output-format") + 1] == "stream-json" and "--verbose" in args


def test_the_manifest_names_the_providers_refusal(env):
    block = json.loads((SCRIPT.parent / "eval.json").read_text(encoding="utf-8"))
    assert block["refusal_markers"] == ["safeguards flagged this message"]


# --- the two eval adapters agree with each other and with the contract ------------------------------

@pytest.mark.parametrize("flag", ["--prompt-file", "--cwd", "--model", "--out", "--max-cost-usd"])
def test_a_flag_given_last_without_its_value_is_a_usage_error(env, flag):
    r = subprocess.run(["bash", str(SCRIPT), flag], capture_output=True, text=True, env=env["env"])
    assert r.returncode == 2 and f"{flag} needs a value" in r.stderr and "unbound" not in r.stderr


def test_a_flag_followed_by_another_flag_is_a_usage_error(env):
    r = subprocess.run(["bash", str(SCRIPT), "--model", "--out", "x"], capture_output=True, text=True, env=env["env"])
    assert r.returncode == 2 and "--model needs a value" in r.stderr


@pytest.mark.parametrize("value", ["", "abc", "1;rm", "-1", "1.", ".5"])
def test_max_cost_must_be_a_number(env, value):
    r = run(env, "--max-cost-usd", value)
    assert r.returncode == 2 and ("needs a number" in r.stderr or "needs a value" in r.stderr)


@pytest.mark.parametrize("code", [1, 3, 7, 127])
def test_a_failed_cli_is_exit_1_whatever_its_own_code_and_2_is_kept_for_usage(env, code):
    stand_in(env, f"echo '{{\"result\": \"failed\"}}'\nexit {code}\n")
    r = run(env)
    assert r.returncode == 1 and json.loads((env["tmp"] / "out" / "timing.json").read_text())["exit_code"] == code


# --- R12: what a run did with a skill's folder (skills_loaded, skills_used) -------------------------------

def timing_after(env, *calls):
    """The timing.json of a run whose stream is one assistant event per call: (tool, input) or (tool, input, parent id)."""
    events = [{"type": "system", "subtype": "init", "model": "m"}]
    for call in calls:
        block = {"type": "tool_use", "name": call[0], "input": call[1]}
        events.append({"type": "assistant", "parent_tool_use_id": call[2] if len(call) > 2 else None,
                       "message": {"content": [block]}})
    events.append({"type": "result", "subtype": "success", "result": "done", "usage": {"input_tokens": 1, "output_tokens": 1}})
    lines = "\n".join(json.dumps(e) for e in events)
    stand_in(env, f"cat > /dev/null\ncat <<'EOF'\n{lines}\nEOF\n")
    r = run(env)
    assert r.returncode == 0, r.stderr
    return json.loads((env["tmp"] / "out" / "timing.json").read_text())


def test_a_follow_up_that_only_ran_the_skills_script_used_the_skill_and_did_not_load_it(env):
    timing = timing_after(env, ("Bash", {"command": "python3 .claude/skills/demo/scripts/check.py --help"}))
    assert (timing["skills_loaded"], timing["skills_used"]) == ([], ["demo"])


def test_reading_the_skills_text_with_a_shell_command_is_loading_it(env):
    timing = timing_after(env, ("Bash", {"command": "cat /eval/case/.claude/skills/demo/SKILL.md | head -40"}),
                          ("Grep", {"pattern": "Stop rules", "path": ".claude/skills/dep/SKILL.md"}))
    assert (timing["skills_loaded"], timing["skills_used"]) == (["demo", "dep"], ["demo", "dep"])


def test_a_reference_read_or_a_listing_of_the_skills_folder_is_use_and_a_listing_of_all_skills_is_neither(env):
    timing = timing_after(env, ("Read", {"file_path": "/eval/case/.claude/skills/demo/references/guide.md"}),
                          ("Bash", {"command": "ls .claude/skills"}), ("Bash", {"command": "ls .claude/skills/"}),
                          ("Bash", {"command": "ls \".claude/skills/dep\""}))
    assert (timing["skills_loaded"], timing["skills_used"]) == ([], ["demo", "dep"])
    assert timing_after(env, ("Bash", {"command": "ls .claude/skills"}))["skills_used"] == []


def test_a_subagents_read_of_a_skills_text_is_loading_it(env):
    timing = timing_after(env, ("Read", {"file_path": "/eval/case/.claude/skills/demo/SKILL.md"}, "toolu_parent"))
    assert (timing["skills_loaded"], timing["skills_used"]) == (["demo"], ["demo"])


@pytest.mark.parametrize("path", [".claude/skills/../demo/SKILL.md", ".claude/skills/./demo/SKILL.md", ".claude/skills/.hidden/SKILL.md",
                                  "/eval/case/x.claude/skills/demo/SKILL.md"])
def test_a_path_that_does_not_name_a_skill_folder_is_neither(env, path):
    timing = timing_after(env, ("Read", {"file_path": path}))
    assert (timing["skills_loaded"], timing["skills_used"]) == ([], [])


def test_the_skill_tool_loads_and_uses(env):
    timing = timing_after(env, ("Skill", {"skill": "demo"}), ("Skill", {"command": "dep"}))
    assert (timing["skills_loaded"], timing["skills_used"]) == (["demo", "dep"], ["demo", "dep"])
