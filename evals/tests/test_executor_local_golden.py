"""The proof that package N14 changes nothing a hosted run measures (the measurement change is of kind infrastructure).

The two fingerprinted files N14 touches are evals/executor.py and adapters/agents-dir/run-prompt.sh. The claim is that every
run of every listed model is byte-identical to what it was before: the docker arguments and the call sequence of command(),
hold() and release(), and what run-prompt.sh writes and starts. Both are shown here against the BASE commit of the package
(aa31cfca, the last commit before it on feature/delegation-platform), read from git, with a fake docker and a stub runner:

  (a) for each model the gate file lists, on the networks none, proxy and open, with and without a held key: the arguments
      of command(), the calls (and the environment each call is given) of hold() and of release(), made by the base
      executor.py and by this one, are equal;
  (b) run-prompt.sh of the base and of this checkout, with a stub `opencode` that records its arguments, the variables it is
      given and the opencode.json written for it, leave the same record, and the same reply and timing, for an
      openrouter/* model (with and without the key proxy's base URL) and an ollama/* model.

If either differs, the change is an execution change (`eval_status.py measurement --kind execution`), not infrastructure.
Both tests are skipped when the base commit is not in the checkout (a shallow clone).

Run: uv run --with pytest pytest evals/tests/test_executor_local_golden.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
BASE = "aa31cfcaaea93cc88d701057a4a800adaf5fd051"  # the commit before package N14 (feature/delegation-platform)
GATE = json.loads((REPO / "evals" / "eval-gate.json").read_text())
LISTED = list(GATE["models"])


def from_git(path: str) -> bytes:
    known = subprocess.run(["git", "-C", str(REPO), "cat-file", "-e", f"{BASE}:{path}"], capture_output=True)
    if known.returncode != 0:
        pytest.skip(f"commit {BASE[:8]} is not in this checkout (a shallow clone): the base cannot be read")
    return subprocess.run(["git", "-C", str(REPO), "show", f"{BASE}:{path}"], capture_output=True, check=True).stdout


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def pair(tmp_path):
    """(base executor, this executor): the base file in a folder of its own that sees the same definition, gate file and
    lock as this checkout, so that both read the same routes and the same image names."""
    folder = tmp_path / "base" / "evals"
    folder.mkdir(parents=True)
    (folder / "executor.py").write_bytes(from_git("evals/executor.py"))
    for name in ("container", "eval-gate.json", "image-lock.json"):
        os.symlink(REPO / "evals" / name, folder / name)
    base, new = load(folder / "executor.py", "executor_base_n14"), load(REPO / "evals" / "executor.py", "executor_new_n14")
    for module in (base, new):
        module._NATIVE["platform"] = "linux/arm64"
    return base, new


class Recorder:
    """docker as hold() and release() see it: every call and the environment it was given, and the answers a started key proxy gives."""

    def __init__(self):
        self.calls = []

    def __call__(self, *args, env=None, check=True, timeout=1800):
        self.calls.append((args, dict(env or {}), check, timeout))
        err = "keyproxy: listening on port 8890\n" if args[0] == "logs" else ""
        return subprocess.CompletedProcess(["docker", *args], 0, "", err)


def scenarios():
    for model in LISTED:
        entry = GATE["models"][model]
        for network in ("none", "proxy", "open"):
            for held in (False, True):
                yield pytest.param(model, entry["pass_env"][0], network, held, id=f"{model}-{network}-{'held' if held else 'plain'}")


@pytest.mark.parametrize("model, key, network, held", list(scenarios()))
def test_the_arguments_and_the_call_sequence_of_a_hosted_run_are_those_of_the_base(pair, tmp_path, monkeypatch, model, key, network, held):
    base, new = pair
    runner = tmp_path / "run-prompt.sh"
    runner.write_text("#!/bin/bash\n")
    root = tmp_path / "run"
    (root / "case").mkdir(parents=True)
    run_id = "0123456789abcdef"
    env = {"PATH": os.environ.get("PATH", ""), **({key: "fake-key-for-the-golden-test"} if held else {})}
    argvs, sequences = [], []
    for module in (base, new):
        recorder = Recorder()
        monkeypatch.setattr(module, "docker", recorder)
        monkeypatch.setattr(module.time, "sleep", lambda s: None)
        meter = tmp_path / f"meter-{module.__name__}"
        meter.mkdir()
        argv, container = module.command(["bash", "-c", "true"], str(root), cwd=str(root / "case"), env=env, runner=str(runner),
                                         pass_names=[key] if held else [], network=network, model=model, run_id=run_id)
        if held and network != "none":
            module.hold(run_id, model, env, network, meter_dir=str(meter))
        module.release(run_id, env)
        argvs.append((argv, container))
        # the folder of the meter differs by module name only: replace it, as the arguments of hold() carry it
        sequences.append([(c[0], c[1], c[2], c[3]) for c in recorder.calls])
        sequences[-1] = json.loads(json.dumps(sequences[-1]).replace(str(meter), "<METER>").replace(str(os.path.realpath(meter)), "<METER>"))
    assert argvs[0] == argvs[1], "the docker arguments of command() differ from the base's"
    assert sequences[0] == sequences[1], "the calls hold() and release() make differ from the base's"
    if network != "none" and held:
        assert sequences[0], "the scenario exercised nothing"


def test_the_names_of_a_hosted_run_are_those_of_the_base_and_one_more(pair):
    base, new = pair
    old, now = base.run_names("0123456789abcdef"), new.run_names("0123456789abcdef")
    assert {k: now[k] for k in old} == old and set(now) - set(old) == {"model"}
    assert base.names() == new.names() and base.labels("0123456789abcdef") == new.labels("0123456789abcdef")


# --- (b) run-prompt.sh -----------------------------------------------------------------------------------------------

STUB = r'''#!/usr/bin/env python3
import json, os, sys
home = os.environ.get("XDG_CONFIG_HOME", "")
cfg = os.path.join(home, "opencode", "opencode.json")
record = {"argv": sys.argv[1:], "cwd": os.path.basename(os.getcwd()),
          "env": {k: v for k, v in sorted(os.environ.items())
                  if k.startswith(("OPENROUTER", "OPENCODE", "RUN_PROMPT", "LOCAL_MODEL", "WB_"))},
          "config": json.load(open(cfg)) if os.path.exists(cfg) else None,
          "home_is_throwaway": os.environ.get("HOME", "").startswith(os.environ.get("TMPDIR", "/tmp").rstrip("/")) or "tmp" in os.environ.get("HOME", "")}
open(os.environ["STUB_RECORD"], "w").write(json.dumps(record, sort_keys=True))
for event in ({"type": "step_start"}, {"type": "text", "part": {"text": "done"}},
              {"type": "step_finish", "part": {"tokens": {"input": 3, "output": 4, "reasoning": 0, "cache": {"read": 0, "write": 0}}, "cost": 0}}):
    print(json.dumps(event))
'''


def run_script(script: Path, tmp_path: Path, tag: str, model: str, env_extra: dict):
    stubs = tmp_path / f"stubs-{tag}"
    stubs.mkdir()
    stub = stubs / "opencode"
    stub.write_text(STUB)
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    cwd, out, prompt = tmp_path / f"cwd-{tag}" / "case", tmp_path / f"out-{tag}", tmp_path / f"prompt-{tag}.md"
    cwd.mkdir(parents=True)
    prompt.write_text("Say done.\n")
    record = tmp_path / f"record-{tag}.json"
    env = {"PATH": f"{stubs}:{os.environ.get('PATH', '')}", "WB_EVAL_CONTAINER": "1", "STUB_RECORD": str(record), **env_extra}
    r = subprocess.run(["bash", str(script), "--prompt-file", str(prompt), "--cwd", str(cwd), "--model", model, "--out", str(out)],
                       capture_output=True, text=True, env=env, timeout=120)
    timing = json.loads((out / "timing.json").read_text()) if (out / "timing.json").exists() else None
    if timing:
        timing.pop("duration_ms", None)  # a clock
    return {"rc": r.returncode, "stderr": r.stderr.replace(str(tmp_path), "<TMP>"),
            "record": json.loads(record.read_text()) if record.exists() else None,
            "reply": (out / "response.md").read_text() if (out / "response.md").exists() else None, "timing": timing,
            "stream": (out / "stream.jsonl").read_text() if (out / "stream.jsonl").exists() else None}


CASES = [
    ("openrouter-held", "openrouter/deepseek/deepseek-v4.1-flash",
     {"OPENROUTER_API_KEY": "held-by-the-eval-key-proxy", "OPENROUTER_BASE_URL": "http://wb-eval-keys-0123456789abcdef:8890/api/v1"}),  # security-scan: allow secret-assignment -- the placeholder a held run is given, not a key
    ("openrouter-plain", "openrouter/deepseek/deepseek-v4.1-flash", {"OPENROUTER_API_KEY": "placeholder"}),
    ("ollama", "ollama/example-coder", {}),
    ("ollama-url", "ollama/example-coder:32k", {"RUN_PROMPT_OLLAMA_URL": "http://host.example:11434/v1"}),
    ("bad-ollama", "ollama/bad name", {}),
]


@pytest.mark.parametrize("tag, model, env_extra", CASES, ids=[c[0] for c in CASES])
def test_run_prompt_of_a_hosted_or_ollama_model_does_what_the_base_did(tmp_path, tag, model, env_extra):
    if not shutil.which("python3") or not shutil.which("bash"):
        pytest.skip("bash and python3 are needed")
    base = tmp_path / "base-run-prompt.sh"
    base.write_bytes(from_git("adapters/agents-dir/run-prompt.sh"))
    before = run_script(base, tmp_path, "base-" + tag, model, env_extra)
    after = run_script(REPO / "adapters" / "agents-dir" / "run-prompt.sh", tmp_path, "new-" + tag, model, env_extra)
    for result in (before, after):  # the throwaway folders and the temporary paths are named differently from run to run
        if result["record"]:
            result["record"].pop("home_is_throwaway", None)
    assert before == after, "run-prompt.sh does something else for this model than it did at the base commit"
    if tag != "bad-ollama":
        assert before["rc"] == 0 and before["record"] is not None, before["stderr"]
        assert before["record"]["argv"][:1] == ["run"]
