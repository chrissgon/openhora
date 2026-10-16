"""Tests for run-prompt.sh with RUN_PROMPT_CMD standing in for a runner (no model is called).

Run: uv run --with pytest pytest adapters/agents-dir/tests
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "run-prompt.sh"


@pytest.fixture
def case(tmp_path):
    skill = tmp_path / "skills" / "demo"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("demo\n")
    (tmp_path / "cwd").mkdir()
    (tmp_path / "prompt.md").write_text("hello\n")
    return tmp_path


def run(t, model="m", *extra, cmd="cat {prompt_file}; echo {model}", **more):
    # WB_EVAL_CONTAINER: the adapter starts only inside the eval container, which sets it.
    env = {"PATH": os.environ["PATH"], "HOME": str(t), "RUN_PROMPT_CMD": cmd, "WB_EVAL_CONTAINER": "1", **more}
    return subprocess.run(["bash", str(SCRIPT), "--prompt-file", str(t / "prompt.md"), "--cwd", str(t / "cwd"),
                           "--model", model, "--out", str(t / "out"), *extra], capture_output=True, text=True, env=env)


def test_the_adapter_installs_nothing(case):
    """The runner stages the skills before the adapter starts (scripts/stage_skills.py): the adapter runs the prompt."""
    r = run(case)
    assert r.returncode == 0, r.stderr
    assert list((case / "cwd").iterdir()) == []  # no skill folder, no shared folder
    assert (case / "out" / "response.md").read_text() == "hello\nm\n"


@pytest.mark.parametrize("flag", ["--skill-dir", "--extra-skill-dir"])
def test_the_options_that_made_the_adapter_copy_a_skill_are_gone(case, flag):
    r = run(case, "m", flag, str(case / "skills" / "demo"))
    assert r.returncode == 2 and "unknown option" in r.stderr
    assert not (case / "out").exists() and list((case / "cwd").iterdir()) == []


def test_a_skill_the_runner_staged_is_left_as_it_is(case):
    staged = case / "cwd" / ".agents" / "skills" / "demo"
    staged.mkdir(parents=True)
    (staged / "SKILL.md").write_text("staged by the runner\n")
    r = run(case)
    assert r.returncode == 0, r.stderr
    assert (staged / "SKILL.md").read_text() == "staged by the runner\n"
    assert sorted(p.name for p in (case / "cwd" / ".agents").iterdir()) == ["skills"]


def test_the_manifest_names_where_the_harness_finds_skills_and_what_carries_its_settings():
    manifest = json.loads((SCRIPT.parent / "adapter.json").read_text(encoding="utf-8"))
    block = json.loads((SCRIPT.parent / "eval.json").read_text(encoding="utf-8"))
    assert block["skills_dir"] == ".agents/skills"
    settings = set(block["settings"])
    assert {".agents", ".opencode", "opencode.json", "opencode.jsonc"} <= settings
    # What the default runner also reads at project level: another tool's folder and instruction file.
    assert {".claude", "CLAUDE.md"} <= settings and "AGENTS.md" not in settings
    assert set(manifest["consumes"]) == set(manifest["strategy"])  # nothing consumed without saying how


def test_the_model_id_cannot_add_commands(case):
    r = run(case, "m; touch pwned")
    assert r.returncode == 0, r.stderr
    assert not (case / "cwd" / "pwned").exists()
    assert (case / "out" / "response.md").read_text() == "hello\nm; touch pwned\n"


def test_max_cost_is_accepted_and_said_to_be_unenforced(case):
    r = run(case, "m", "--max-cost-usd", "0.50")
    assert r.returncode == 0, r.stderr
    assert "--max-cost-usd is not enforced" in r.stderr


def run_local(t, model, keep_home=False, **more):
    """Run with a fake `opencode` on PATH that prints the configuration it was given."""
    bindir = t / "bin"
    bindir.mkdir(exist_ok=True)
    fake = bindir / "opencode"
    fake.write_text('#!/usr/bin/env bash\ncat "$XDG_CONFIG_HOME/opencode/opencode.json" 2>/dev/null || echo "no config"\n')
    fake.chmod(0o755)
    env = {"PATH": f"{bindir}:{os.environ['PATH']}", "HOME": str(t), "WB_EVAL_CONTAINER": "1", **more}
    if keep_home:
        env["RUN_PROMPT_KEEP_HOME"] = "1"
    return subprocess.run(["bash", str(SCRIPT), "--prompt-file", str(t / "prompt.md"), "--cwd", str(t / "cwd"),
                           "--model", model, "--out", str(t / "out")], capture_output=True, text=True, env=env)


def test_a_local_model_gets_its_provider_in_the_throwaway_home(case):
    import json
    r = run_local(case, "ollama/demo-model:27b")
    assert r.returncode == 0, r.stderr
    cfg = json.loads((case / "out" / "response.md").read_text())
    provider = cfg["provider"]["ollama"]
    assert provider["options"]["baseURL"] == "http://127.0.0.1:11434/v1"
    assert list(provider["models"]) == ["demo-model:27b"]
    assert not list((case / "cwd").rglob("opencode.json"))  # nothing is written into the case folder


def test_a_hosted_model_gets_no_local_provider(case):
    r = run_local(case, "vendor/some-model")
    assert r.returncode == 0 and "no config" in (case / "out" / "response.md").read_text()


@pytest.mark.parametrize("model", ["ollama/", "ollama/a b", 'ollama/x"; rm -rf ~', "ollama/$(id)"])
def test_a_malformed_local_model_id_is_refused(case, model):
    r = run_local(case, model)
    assert r.returncode == 2 and "local model id" in r.stderr


KEY_PROXY = "http://wb-eval-keys-0123456789ab:8890/api/v1"


def test_an_openrouter_model_is_pointed_at_the_key_proxy_in_the_throwaway_home(case):
    r = run_local(case, "openrouter/vendor/some-model", OPENROUTER_BASE_URL=KEY_PROXY)
    assert r.returncode == 0, r.stderr
    cfg = json.loads((case / "out" / "response.md").read_text())
    assert cfg["provider"] == {"openrouter": {"options": {"baseURL": KEY_PROXY}}}  # the base URL alone: no key in it
    assert not list((case / "cwd").rglob("opencode.json"))  # nothing is written into the case folder


@pytest.mark.parametrize("model, base", [("openrouter/vendor/some-model", ""), ("vendor/some-model", KEY_PROXY)])
def test_without_a_key_proxy_or_for_another_provider_no_base_url_is_written(case, model, base):
    r = run_local(case, model, OPENROUTER_BASE_URL=base)
    assert r.returncode == 0 and "no config" in (case / "out" / "response.md").read_text()


@pytest.mark.parametrize("base", ["file:///etc/passwd", "http://host/x y", 'http://host/"; id', "http://host/$(id)"])
def test_a_base_url_that_is_not_a_plain_url_is_refused(case, base):
    r = run_local(case, "openrouter/vendor/some-model", OPENROUTER_BASE_URL=base)
    assert r.returncode == 2 and "OPENROUTER_BASE_URL" in r.stderr


def test_a_local_model_needs_the_throwaway_home(case):
    r = run_local(case, "ollama/demo-model:27b", keep_home=True)
    assert r.returncode == 2 and "throwaway HOME" in r.stderr


def test_outside_the_eval_container_the_adapter_refuses_to_start(case):
    r = run(case, WB_EVAL_CONTAINER="")
    assert r.returncode == 2 and "only inside the container" in r.stderr
    assert not (case / "out").exists() and list((case / "cwd").iterdir()) == []


# --- stopping the adapter stops what the runner started --------------------------------------------

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


def wait_for(path, seconds=10):
    import time
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if path.exists() and path.read_text().strip():
            return path.read_text().strip()
        time.sleep(0.05)
    raise AssertionError(f"{path} was not written")


def test_what_the_runner_leaves_in_the_background_stops_when_it_returns(case):
    r = run(case, cmd="sleep 300 & echo $! > child.pid; echo done")
    assert r.returncode == 0, r.stderr
    assert (case / "out" / "response.md").read_text() == "done\n"
    assert gone(int((case / "cwd" / "child.pid").read_text()))


def test_a_stopped_adapter_stops_the_runner_and_its_children(case):
    import signal
    env = {"PATH": os.environ["PATH"], "HOME": str(case), "WB_EVAL_CONTAINER": "1",
           "RUN_PROMPT_CMD": "sleep 300 & echo $! > child.pid; echo $$ > runner.pid; sleep 300"}
    proc = subprocess.Popen(["bash", str(SCRIPT), "--prompt-file", str(case / "prompt.md"), "--cwd", str(case / "cwd"),
                             "--model", "m", "--out", str(case / "out")], env=env, start_new_session=True)
    child, runner = int(wait_for(case / "cwd" / "child.pid")), int(wait_for(case / "cwd" / "runner.pid"))
    proc.send_signal(signal.SIGTERM)
    assert proc.wait(timeout=15) == 143
    assert gone(child) and gone(runner)


def test_the_manifest_names_what_an_exhausted_account_answers():
    block = json.loads((SCRIPT.parent / "eval.json").read_text(encoding="utf-8"))
    assert block["account_limit"] and all(isinstance(m, str) and m for m in block["account_limit"])



# The events `opencode run --format json` prints (opencode 1.18.32: type, timestamp, sessionID, part), with a
# model that narrates between its tool calls.
EVENTS = [
    {"type": "step_start", "part": {"type": "step-start"}},
    {"type": "text", "part": {"type": "text", "text": "I will load the skill first."}},
    {"type": "tool_use", "part": {"type": "tool", "tool": "skill", "state": {"status": "completed", "input": {"name": "demo"}}}},
    {"type": "step_finish", "part": {"type": "step-finish", "tokens": {"input": 100, "output": 10, "reasoning": 5,
                                                                       "cache": {"read": 50, "write": 0}}, "cost": 0.002}},
    {"type": "step_start", "part": {"type": "step-start"}},
    {"type": "text", "part": {"type": "text", "text": "Now reading the dependency."}},
    {"type": "tool_use", "part": {"type": "tool", "tool": "read", "state": {"status": "completed",
                                                                           "input": {"filePath": "/eval/case/.agents/skills/dep/SKILL.md"}}}},
    {"type": "step_finish", "part": {"type": "step-finish", "tokens": {"input": 200, "output": 20, "reasoning": 0,
                                                                       "cache": {"read": 0, "write": 0}}, "cost": 0.003}},
    {"type": "step_start", "part": {"type": "step-start"}},
    {"type": "text", "part": {"type": "text", "text": "The final answer."}},
    {"type": "text", "part": {"type": "text", "text": "Its second paragraph."}},
    {"type": "step_finish", "part": {"type": "step-finish", "tokens": {"input": 300, "output": 30, "reasoning": 0,
                                                                       "cache": {"read": 0, "write": 0}}, "cost": 0.005}},
]


def fake_runner(t, body):
    bindir = t / "bin"
    bindir.mkdir(exist_ok=True)
    fake = bindir / "opencode"
    fake.write_text("#!/usr/bin/env bash\n" + body)
    fake.chmod(0o755)
    return {"PATH": f"{bindir}:{os.environ['PATH']}", "HOME": str(t), "WB_EVAL_CONTAINER": "1"}


def run_fake(t, env, *extra):
    return subprocess.run(["bash", str(SCRIPT), "--prompt-file", str(t / "prompt.md"), "--cwd", str(t / "cwd"), "--model", "m",
                           "--out", str(t / "out"), *extra], capture_output=True, text=True, env=env)


def test_the_reply_is_the_last_message_and_the_stream_is_kept_beside_it(case):
    lines = "\n".join(json.dumps(e) for e in EVENTS)
    env = fake_runner(case, f'echo "$@" > {case}/args.txt\n' f"cat <<'EOF'\n{lines}\nEOF\n")
    r = run_fake(case, env)
    assert r.returncode == 0, r.stderr
    out = case / "out"
    assert (out / "response.md").read_text() == "The final answer.\n\nIts second paragraph.\n"
    assert "I will load the skill first." in (out / "stream.jsonl").read_text()
    timing = json.loads((out / "timing.json").read_text())
    assert timing["total_tokens"] == 165 + 220 + 330 and timing["cost_usd"] == 0.01  # the floor tier's tokens, recorded
    assert timing["skills_loaded"] == ["demo", "dep"]
    assert "--format json" in (case / "args.txt").read_text()


def test_without_the_web_the_page_fetch_tool_is_denied_and_with_it_search_is_on(case):
    env = fake_runner(case, f'echo "$OPENCODE_PERMISSION|${{OPENCODE_ENABLE_EXA:-}}" > {case}/seen.txt\n')
    assert run_fake(case, env).returncode == 0
    assert json.loads((case / "seen.txt").read_text().split("|")[0]) == {"webfetch": "deny"}
    assert run_fake(case, env, "--allow-web").returncode == 0
    assert (case / "seen.txt").read_text().strip() == "|1"


def test_an_error_event_is_kept_where_the_eval_runner_looks_and_the_run_fails(case):
    events = [{"type": "step_start", "part": {}}, {"type": "error", "error": {"name": "APIError", "data": {"message": "Insufficient credits"}}}]
    lines = "\n".join(json.dumps(e) for e in events)
    env = fake_runner(case, f"cat <<'EOF'\n{lines}\nEOF\nexit 1\n")
    r = run_fake(case, env)
    assert r.returncode == 1
    assert "Insufficient credits" in (case / "out" / "stderr.log").read_text()
    assert (case / "out" / "response.md").read_text() == "" and json.loads((case / "out" / "timing.json").read_text())["skills_loaded"] == []


def test_a_custom_runner_prints_text_and_that_text_is_the_reply(case):
    r = run(case)
    assert r.returncode == 0, r.stderr
    assert (case / "out" / "response.md").read_text() == "hello\nm\n"
    assert json.loads((case / "out" / "timing.json").read_text())["total_tokens"] is None


# --- the two eval adapters agree with each other and with the contract ------------------------------

@pytest.mark.parametrize("flag", ["--prompt-file", "--cwd", "--model", "--out", "--max-cost-usd"])
def test_a_flag_given_last_without_its_value_is_a_usage_error(case, flag):
    r = subprocess.run(["bash", str(SCRIPT), flag], capture_output=True, text=True, env={"PATH": os.environ["PATH"], "HOME": str(case), "WB_EVAL_CONTAINER": "1"})
    assert r.returncode == 2 and f"{flag} needs a value" in r.stderr and "unbound" not in r.stderr


def test_a_flag_followed_by_another_flag_is_a_usage_error(case):
    r = subprocess.run(["bash", str(SCRIPT), "--model", "--out", "x"], capture_output=True, text=True, env={"PATH": os.environ["PATH"], "HOME": str(case), "WB_EVAL_CONTAINER": "1"})
    assert r.returncode == 2 and "--model needs a value" in r.stderr


@pytest.mark.parametrize("value", ["", "abc", "1;rm", "-1", "1.", ".5"])
def test_max_cost_must_be_a_number(case, value):
    r = run(case, "m", "--max-cost-usd", value)
    assert r.returncode == 2 and ("needs a number" in r.stderr or "needs a value" in r.stderr)


@pytest.mark.parametrize("code", [1, 2, 3, 7, 127])
def test_a_failed_runner_is_exit_1_whatever_its_own_code_and_2_is_kept_for_usage(case, code):
    r = run(case, cmd=f"echo partial; exit {code}")
    assert r.returncode == 1 and json.loads((case / "out" / "timing.json").read_text())["exit_code"] == code


def test_allow_web_reaches_a_custom_runner(case):
    r = run(case, "m", "--allow-web", cmd="echo web=$RUN_PROMPT_ALLOW_WEB")
    assert r.returncode == 0 and (case / "out" / "response.md").read_text() == "web=1\n"
    r = run(case, cmd="echo web=$RUN_PROMPT_ALLOW_WEB")
    assert r.returncode == 0 and (case / "out" / "response.md").read_text() == "web=0\n"


# --- R12: what a run did with a skill's folder (skills_loaded, skills_used) -------------------------------

def timing_after(case, *calls):
    """The timing.json of a run whose events are one tool_use per call: (tool, input)."""
    events = [{"type": "step_start", "part": {"type": "step-start"}}]
    for tool, args in calls:
        events.append({"type": "tool_use", "part": {"type": "tool", "tool": tool, "state": {"status": "completed", "input": args}}})
    events.append({"type": "text", "part": {"type": "text", "text": "done"}})
    lines = "\n".join(json.dumps(e) for e in events)
    r = run_fake(case, fake_runner(case, f"cat <<'EOF'\n{lines}\nEOF\n"))
    assert r.returncode == 0, r.stderr
    return json.loads((case / "out" / "timing.json").read_text())


def test_a_follow_up_that_only_ran_the_skills_script_used_the_skill_and_did_not_load_it(case):
    timing = timing_after(case, ("bash", {"command": "python3 .agents/skills/demo/scripts/check.py --help"}))
    assert (timing["skills_loaded"], timing["skills_used"]) == ([], ["demo"])


def test_reading_the_skills_text_with_a_shell_command_is_loading_it(case):
    timing = timing_after(case, ("bash", {"command": "cat /eval/case/.agents/skills/demo/SKILL.md | head -40"}),
                          ("grep", {"pattern": "Stop rules", "path": ".agents/skills/dep/SKILL.md"}))
    assert (timing["skills_loaded"], timing["skills_used"]) == (["demo", "dep"], ["demo", "dep"])


def test_a_reference_read_or_a_listing_of_the_skills_folder_is_use_and_a_listing_of_all_skills_is_neither(case):
    timing = timing_after(case, ("read", {"filePath": "/eval/case/.agents/skills/demo/references/guide.md"}),
                          ("bash", {"command": "ls .agents/skills"}), ("bash", {"command": "ls .agents/skills/"}),
                          ("bash", {"command": "ls '.agents/skills/dep'"}))
    assert (timing["skills_loaded"], timing["skills_used"]) == ([], ["demo", "dep"])
    assert timing_after(case, ("bash", {"command": "ls .agents/skills"}))["skills_used"] == []


@pytest.mark.parametrize("path", [".agents/skills/../demo/SKILL.md", ".agents/skills/./demo/SKILL.md", ".agents/skills/.hidden/SKILL.md",
                                  "/eval/case/x.agents/skills/demo/SKILL.md"])
def test_a_path_that_does_not_name_a_skill_folder_is_neither(case, path):
    timing = timing_after(case, ("read", {"filePath": path}))
    assert (timing["skills_loaded"], timing["skills_used"]) == ([], [])


def test_the_skill_tool_loads_and_uses(case):
    timing = timing_after(case, ("skill", {"name": "demo"}), ("skill", {"name": "dep"}))
    assert (timing["skills_loaded"], timing["skills_used"]) == (["demo", "dep"], ["demo", "dep"])
