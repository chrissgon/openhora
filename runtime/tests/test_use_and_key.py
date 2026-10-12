"""Tests of what the runtime records with the existing recorder (scripts/evidence.py): a use per run, and the
person's verdict on it; and of the key a floor run uses: the runtime's own when it is stored, which travels only
around a floor run, else the lab's key for the floor model, else none and the reference model. Offline: a stand-in recorder written by the test, the stand-in tree of runtime/tests/standin_tree.py, and
stand-in key values built at run time; no credential is read or printed.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_use_and_key.py
"""
from __future__ import annotations

import ast
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

import standin_tree as st

lab = st.load("lab")
ops = st.load("ops")
ops_core = st.load("ops_core")
cli = st.load("cli")
REPO = Path(__file__).resolve().parents[2]
RECORDER = '''import sys
with open(sys.argv[0] + ".calls", "a") as f:
    f.write(" ".join(sys.argv[1:]) + "\\n")
if "--fail" in open(sys.argv[0] + ".mode").read():
    print("the recorder refused", file=sys.stderr)
    sys.exit(1)
print("0a1b2c3d")
'''


@pytest.fixture
def tree(tmp_path, monkeypatch):
    built = st.build(tmp_path, monkeypatch, lab)
    monkeypatch.setattr(ops_core, "ROOT", str(built["tree"]))
    recorder = tmp_path / "recorder.py"
    recorder.write_text(RECORDER, encoding="utf-8")
    (tmp_path / "recorder.py.mode").write_text("ok", encoding="utf-8")
    monkeypatch.setattr(ops_core, "EVIDENCE", str(recorder))
    monkeypatch.setattr(ops_core, "_own_key", lambda: (None, None))  # never the real secret store
    path = str(built["project"])
    ops.accept_config(path, ops.project_config.load(path)["sha256"])
    ops.request(path, "Tell me which market to go after first.", "demo")
    return {**built, "path": path, "recorder": recorder}


def recorded(tree) -> list:
    calls = Path(str(tree["recorder"]) + ".calls")
    return calls.read_text(encoding="utf-8").splitlines() if calls.exists() else []


def test_every_run_records_a_use_with_the_model_and_adapter_of_the_routing_before_it_starts(tree):
    out = ops.run_next(tree["path"])
    lines = recorded(tree)
    assert len(lines) == 1 and lines[0].startswith("record --start --skill-dir ")
    args = lines[0].split()
    assert args[args.index("--model") + 1] == out["routing"]["model"] == "m"
    assert args[args.index("--adapter") + 1] == out["routing"]["adapter"] == "h"
    assert args[args.index("--project") + 1] == tree["path"]
    assert len(st.calls(tree["adapter"])) == 1  # the adapter ran once, after the use was recorded
    assert out["use"] == "0a1b2c3d" and ops.pending(tree["path"], out["pending_id"])["payload"]["use"] == "0a1b2c3d"
    ctx = ops_core.context(tree["path"])
    assert ctx["store"].cursor_get(ctx["conn"], f"use:{out['run_id']}") == "0a1b2c3d"
    ops.answer(tree["path"], out["pending_id"], "Portugal.")
    ops.run_next(tree["path"])
    assert len(recorded(tree)) == 2  # one use per run, also for a run made after an answer


def test_a_use_that_cannot_be_recorded_does_not_stop_the_run(tree, capsys):
    Path(str(tree["recorder"]) + ".mode").write_text("--fail", encoding="utf-8")
    out = ops.run_next(tree["path"])
    assert (out["status"], out["ending"], out["use"]) == ("ok", "question", None)
    assert "could not be recorded" in capsys.readouterr().err


def test_the_persons_verdict_is_recorded_on_the_use_of_that_run_and_only_once(tree):
    out = ops.run_next(tree["path"])
    got = ops.verdict(tree["path"], out["run_id"], "corrected")
    assert got == {"run_id": out["run_id"], "use": "0a1b2c3d", "verdict": "corrected"}
    assert recorded(tree)[-1] == f"record --verdict corrected --use 0a1b2c3d --project {tree['path']}"
    with pytest.raises(ops.OpsError) as again:
        ops.verdict(tree["path"], out["run_id"], "worked")
    assert again.value.code == 1 and "already has the verdict corrected" in str(again.value)
    with pytest.raises(ops.OpsError) as none:
        ops.verdict(tree["path"], out["run_id"] + 1, "worked")
    assert none.value.code == 1 and "has no recorded use" in str(none.value)
    assert cli.main(["verdict", "--project", tree["path"], "--run", str(out["run_id"]), "--word", "failed"]) == 1


def test_a_verdict_is_one_of_three_words_and_no_code_path_gives_one(tree):
    with pytest.raises(ops.OpsError) as wrong:
        ops.verdict(tree["path"], 1, "great")
    assert wrong.value.code == 2
    holders = []
    for file in sorted((REPO / "runtime").glob("*.py")):
        text = file.read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, ast.FunctionDef) and "--verdict" in (ast.get_source_segment(text, node) or ""):
                holders.append(f"{file.stem}.{node.name}")
    assert set(holders) <= {"ops.verdict", "cli.run"} and "ops.verdict" in holders


FLOOR_VAR = "STANDIN_FLOOR_PASS"


def floor_reliable(monkeypatch, missing=None):
    """The floor tier passes one stand-in variable, the stand-in skill is reliable on the floor model, and the lab's
    lookup of the floor tier's key answers `missing` (the names it did not find) without the real secret store."""
    control = {"total_jobs": 2, "web_jobs": {"strong": 1, "floor": 1}}
    monkeypatch.setattr(lab, "reference", lambda tier="strong": {
        "tier": tier, "model": "m" if tier == "strong" else "fm", "adapter": "h",
        "pass_env": [FLOOR_VAR] if tier == "floor" else [], "timeout_seconds": 60, "retries": 2, "control": control})
    reliable = lab.standing("demo-asks")
    reliable["models"]["fm"] = {"band": "reliable", "cause": None, "score": 0.9, "mean": 0.95, "runs": 6}
    monkeypatch.setattr(lab, "standing", lambda skill: reliable)
    monkeypatch.setattr(lab, "credential_missing", lambda tier: [FLOOR_VAR] if missing is None else missing)


def watch_the_key(monkeypatch) -> list:
    """What the floor tier's variable holds at the moment lab.run_skill is called, per call."""
    seen, real = [], lab.run_skill

    def run_skill(*args, **kwargs):
        seen.append((kwargs.get("tier"), os.environ.get(FLOOR_VAR)))
        return real(*args, **kwargs)

    monkeypatch.setattr(lab, "run_skill", run_skill)
    return seen


def test_a_floor_run_carries_the_runtimes_own_key_and_the_environment_is_restored(tree, monkeypatch):
    lab_value, own_value = "lab-" + "x" * 12, "own-" + "y" * 12
    floor_reliable(monkeypatch, missing=[])  # the lab's key is there too: the runtime's own wins
    monkeypatch.setattr(ops_core, "_own_key", lambda: (own_value, None))
    seen = watch_the_key(monkeypatch)
    monkeypatch.setenv(FLOOR_VAR, lab_value)
    out = ops.run_next(tree["path"])
    assert out["routing"]["tier"] == "floor" and out["routing"]["key"] == "runtime" and seen == [("floor", own_value)]
    assert os.environ.get(FLOOR_VAR) == lab_value
    assert own_value not in json.dumps(out) and own_value not in json.dumps(ops.pending(tree["path"], out["pending_id"]))
    ops.answer(tree["path"], out["pending_id"], "Portugal.")
    monkeypatch.delenv(FLOOR_VAR)
    ops.run_next(tree["path"])
    assert seen[-1] == ("floor", own_value) and FLOOR_VAR not in os.environ


def test_without_a_key_of_its_own_a_floor_run_uses_the_labs_key_and_the_runtime_sets_nothing(tree, monkeypatch):
    lab_value = "lab-" + "x" * 12
    floor_reliable(monkeypatch, missing=[])
    seen = watch_the_key(monkeypatch)
    monkeypatch.setenv(FLOOR_VAR, lab_value)  # the lab's key, as the lab's lookup finds it
    out = ops.run_next(tree["path"])
    assert out["status"] == "ok" and out["routing"]["tier"] == "floor" and out["routing"]["key"] == "lab"
    assert out["routing"]["model"] == "fm" and seen == [("floor", lab_value)]
    assert os.environ.get(FLOOR_VAR) == lab_value
    assert ops.pending(tree["path"], out["pending_id"])["payload"]["routing"]["key"] == "lab"
    shown = ops.proof(tree["path"], "demo-writes")["skills"]["demo-writes"]
    assert (shown["tier"], shown["key"]) == ("floor", "lab")


def test_without_any_key_no_run_goes_to_the_floor_model(tree, monkeypatch):
    floor_reliable(monkeypatch)  # the lab's lookup finds nothing either
    seen = watch_the_key(monkeypatch)
    out = ops.run_next(tree["path"])
    assert out["routing"]["tier"] == "strong" and out["routing"]["bands"]["floor"] == "reliable"
    assert out["routing"]["key"] is None and seen == [("strong", None)]
    reasons = out["routing"]["reasons"]
    assert "no key for the floor model was found" in reasons
    why = [r for r in reasons if r.startswith("no key for the floor model: ")]
    assert len(why) == 1 and "WB_RUNTIME_FLOOR_KEY" in why[0] and "is not stored" in why[0]
    assert f"({FLOOR_VAR}) is neither set nor in the secret store" in why[0]
    monkeypatch.setattr(ops_core, "_own_key", lambda: (None, "the secret resolver could not be used: ImportError"))
    shown = ops.proof(tree["path"], "demo-writes")["skills"]["demo-writes"]
    assert shown["tier"] == "strong" and shown["key"] is None
    assert any("the secret resolver could not be used: ImportError" in r for r in shown["reasons"])


def test_the_lab_lookup_of_a_tier_key_returns_names_and_puts_the_environment_back(monkeypatch):
    found = "found-" + "z" * 12

    class Lookup:
        def resolve_pass_env(self, names):  # the lab's lookup fills what it finds, as resolve_pass_env does
            os.environ["STANDIN_FOUND"] = found
            return ["STANDIN_FOUND (stand-in)"]

    monkeypatch.setattr(lab, "LAB", Lookup())
    monkeypatch.setattr(lab, "reference", lambda tier="strong": {"pass_env": ["STANDIN_FOUND", "STANDIN_ABSENT"]})
    monkeypatch.delenv("STANDIN_FOUND", raising=False)
    monkeypatch.delenv("STANDIN_ABSENT", raising=False)
    assert lab.credential_missing("floor") == ["STANDIN_ABSENT"]
    assert "STANDIN_FOUND" not in os.environ  # the value the lookup found is not kept
    monkeypatch.setenv("STANDIN_FOUND", "before")
    assert lab.credential_missing("floor") == ["STANDIN_ABSENT"] and os.environ["STANDIN_FOUND"] == "before"


def test_the_key_value_never_appears_in_what_the_operation_prints_or_logs(tree, monkeypatch, capsys):
    own_value = "own-" + "q" * 16
    floor_reliable(monkeypatch, missing=[])
    monkeypatch.setattr(ops_core, "_own_key", lambda: (own_value, None))
    assert cli.main(["proof", "--project", tree["path"], "--skill", "demo-asks"]) == 0
    assert cli.main(["run-next", "--project", tree["path"]]) == 0
    assert cli.main(["status", "--project", tree["path"]]) == 0
    printed = capsys.readouterr()
    assert '"key": "runtime"' in printed.out
    assert own_value not in printed.out and own_value not in printed.err
    for folder in (tree["data"], tree["db"].parent, tree["project"]):
        for file in Path(folder).rglob("*"):
            if file.is_file():
                assert own_value.encode() not in file.read_bytes(), file


def test_the_runtimes_secret_is_registered_in_the_form_the_resolver_accepts():
    spec = importlib.util.spec_from_file_location("workbench_secret_resolver_key_test",
                                                  REPO / "providers" / "secrets" / "resolver.py")
    resolver = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = resolver  # its dataclasses look their module up by name
    try:
        spec.loader.exec_module(resolver)
    except Exception as e:  # the resolver's header asks for a newer interpreter than some test runs have
        pytest.skip(f"the resolver cannot be imported on this interpreter: {type(e).__name__}")
    registry = REPO / "runtime" / "secrets.json"
    assert resolver.register_file(registry) == ["WB_RUNTIME_FLOOR_KEY"]
    assert set(json.loads(registry.read_text(encoding="utf-8"))) == {"secrets"}
    assert ops_core.FLOOR_KEY == "WB_RUNTIME_FLOOR_KEY"


def test_the_recorder_still_has_the_interface_the_runtime_calls():
    text = (REPO / "scripts" / "evidence.py").read_text(encoding="utf-8")
    assert "record --start --skill-dir" in text and "--model" in text and "--adapter" in text
    found = re.search(r"record --verdict ([a-z|]+) --use", text)
    assert found and tuple(found.group(1).split("|")) == ops.VERDICTS


def test_the_real_recorder_writes_a_use_line_for_a_run_of_the_runtime(tmp_path):
    model = lab.reference()["model"]
    project = tmp_path / "project"
    project.mkdir()
    done = subprocess.run([sys.executable, str(REPO / "scripts" / "evidence.py"), "record", "--start", "--skill-dir",
                           str(REPO / "skills" / "biz-market-analysis"), "--project", str(project), "--model", model],
                          capture_output=True, text=True, check=False)
    use = done.stdout.strip()
    assert done.returncode == 0 and re.fullmatch(r"[0-9a-f]{8}", use), done.stderr
    lines = [json.loads(line) for line in
             (project / ".workbench-local" / "evidence" / "biz-market-analysis.jsonl").read_text(encoding="utf-8").splitlines()]
    assert lines[-1]["model"] == model
