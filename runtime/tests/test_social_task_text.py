"""WP-7.3b: the social handler's task text is the text of the measured cases, byte for byte.

The agent's run is the one the battery measured, so the proof of mkt-engage and of mkt-vote-round stands for it
only when the task text is the one the cases ran with. These tests read the cases' prompts, take the data out of
them (the platform from the `Platform:` line, the comment or the vote state from the `json` block) and require
the handler's text, built from that data, to equal the prompt. A case is never edited to make one pass: a
changed case loses its evidence.
"""
import ast
import json
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
HANDLERS = REPO / "runtime" / "handlers"
sys.path.insert(0, str(HANDLERS))
import social  # noqa: E402
import social_vote  # noqa: E402

FIRST_LINE = 'This task comes from the agent runtime (contracts/runtime.md). Follow "Runtime mode" in the skill {skill}.'
JSON_BLOCK = re.compile(r"```json\n(.*?)\n```", re.S)
PLATFORM_LINE = re.compile(r"^Platform: (.+)$", re.M)
ANYWHERE = Path("/a/folder/that/the/text/must/not/name")


def runtime_cases(skill):
    """The cases of a skill whose prompt starts with the runtime's first line (the cases that measure a run
    the runtime starts)."""
    data = json.loads((REPO / "skills" / skill / "evals" / "evals.json").read_text(encoding="utf-8"))
    cases = data["evals"] if isinstance(data, dict) else data
    return [c for c in cases if c["prompt"].startswith(FIRST_LINE.format(skill=skill))]


def platform_of(prompt):
    (platform,) = PLATFORM_LINE.findall(prompt)
    return platform


def data_of(prompt):
    (block,) = JSON_BLOCK.findall(prompt)
    return json.loads(block)


def test_the_engage_task_text_is_the_prompt_of_the_measured_runtime_cases():
    cases = runtime_cases("mkt-engage")
    assert [c["id"] for c in cases] == [1, 2, 3]
    for case in cases:
        prompt = case["prompt"]
        text = social.task_text({"publisher": platform_of(prompt)}, ANYWHERE, data_of(prompt))
        assert text == prompt, f"mkt-engage case {case['id']}: the handler's text is not the measured one"


def test_the_vote_task_text_is_the_prompt_of_the_measured_runtime_cases():
    cases = runtime_cases("mkt-vote-round")
    assert [c["id"] for c in cases] == [1, 2]
    for case in cases:
        prompt = case["prompt"]
        text = social_vote.task_text(ANYWHERE, data_of(prompt), platform_of(prompt))
        assert text == prompt, f"mkt-vote-round case {case['id']}: the handler's text is not the measured one"


class StopRun(Exception):
    """Raised by the stand-in `run` at the contained run, so that nothing after it is needed."""


def engage_contained_command(monkeypatch, tmp_path, publisher):
    """The command handle_event() starts for the agent's run, with the parser and the store faked."""
    seen = []
    comment = {"parsed": True, "on_own_post": True, "comment_urn": "c1", "post_urn": "p1", "commenter": "Sam",
               "text": "Nice.", "received_at": "2026-10-12T10:05:00-03:00"}

    def fake_run(cmd, stdin=None, cwd=None, timeout=social.TIMEOUT):
        if "contained-run" in cmd:
            seen.append((cmd, timeout))
            raise StopRun()
        return 0, json.dumps(comment), ""  # the notification parser

    class Store:
        def __call__(self, verb, *args):
            return {"run_id": 1}

    monkeypatch.setattr(social, "run", fake_run)
    cfg = {"publisher": publisher, "agent": "social-manager", "data_dir": str(tmp_path / "data"),
           "timeout_seconds": 600,
           "paths": {"parser": tmp_path / "parse.py", "platform_file": tmp_path / "p.json",
                     "run_agent": tmp_path / "runtime" / "cli.py"}}
    with pytest.raises(StopRun):
        social.handle_event(cfg, tmp_path / "project", Store(), {"id": 1, "source": "pasted", "payload": {}})
    (call,) = seen
    return cfg, call


def test_a_contained_run_is_given_the_platform_the_cases_name(monkeypatch, tmp_path):
    for skill in ("mkt-engage", "mkt-vote-round"):
        for case in runtime_cases(skill):
            platform = platform_of(case["prompt"])
            assert platform in case.get("platforms", []), f"{skill} case {case['id']} names no platforms entry for {platform}"
    cfg, (cmd, timeout) = engage_contained_command(monkeypatch, tmp_path, "linkedin")
    assert cmd[1:3] == [str(cfg["paths"]["run_agent"]), "contained-run"]
    assert cmd[cmd.index("--platform") + 1] == cfg["publisher"] == "linkedin"
    assert cmd[cmd.index("--skill") + 1] == "mkt-engage"
    assert cmd[cmd.index("--timeout-seconds") + 1] == "600" and timeout == 600 + 300
    # The vote step starts its run in one place: the command's list holds --platform followed by cfg["publisher"].
    tree = ast.parse((HANDLERS / "social_vote.py").read_text(encoding="utf-8"))
    commands = [n for n in ast.walk(tree) if isinstance(n, ast.List)
                and any(isinstance(e, ast.Constant) and e.value == "contained-run" for e in n.elts)]
    assert len(commands) == 1
    elements = [ast.unparse(e) for e in commands[0].elts]
    assert elements[elements.index("'--platform'") + 1] == "cfg['publisher']"
    assert elements[elements.index("'--skill'") + 1] == "'mkt-vote-round'"
