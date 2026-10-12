"""Offline tests of evals/run_attempts.py, the control of a run's attempts, with a stand-in for the runner: an
object of recording functions. No adapter, no container, no model.

Run: uv run --with pytest==9.1.1 pytest evals/tests/test_run_attempts.py
"""
from __future__ import annotations

import ast
import importlib.util
import os
import re
import shutil
import sys
import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

EVALS = Path(__file__).resolve().parents[1]
KIT = EVALS / "execution.py"


def load(name):
    spec = importlib.util.spec_from_file_location(f"{name}_under_test", EVALS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ra = load("run_attempts")


class StandIn:
    """The runner as run_attempts sees it. Each attempt follows the next entry of `script`: {"why": the
    adapter's failure or None, "reply": the text of response.md, "log": the text of error.log, "write": {relative
    path: text} written into the copy}. Markers in the texts drive the stand-in readers: LIMIT (the account
    limit), REFUSED (a provider's refusal), AUTH (a refused key), EARLY (an early end)."""

    KEPT_PREFIXES = ("early-end-", "failed-", "paused-", "before-resume-")
    RETRY_KINDS = {"timeout": "timeouts", "refused": "refusals", "adapter": "adapter_failures", "early_end": "early_ends"}
    RETRY_PAUSE = 5.0

    def __init__(self, tmp, script):
        self.tmp, self.script, self.log, self.roots = Path(tmp), list(script), [], {}
        self.STOPPING = threading.Event()
        self.calls = 0

    # the fresh folder and its return
    def new_run_root(self, dest, names=()):
        self.log.append(("new_run_root", tuple(names)))
        root = tempfile.mkdtemp(prefix="eval-", dir=str(self.tmp))
        os.makedirs(os.path.join(root, "case"))
        os.makedirs(os.path.join(root, "out"))
        self.roots[root] = dest
        return root

    def return_run(self, root):
        self.log.append(("return_run",))
        dest = self.roots.pop(root, None)
        if dest is None:
            return
        os.makedirs(dest, exist_ok=True)
        for name, final in (("case", "cwd"), ("out", "outputs"), ("prompt.md", "prompt.md")):
            src, target = os.path.join(root, name), os.path.join(dest, final)
            if not os.path.lexists(src):
                continue
            if os.path.isdir(target):
                shutil.rmtree(target)
            elif os.path.lexists(target):
                os.remove(target)
            shutil.move(src, target)
        shutil.rmtree(root, ignore_errors=True)

    def contained_env(self, root, pass_env=()):
        self.log.append(("contained_env", tuple(pass_env)))
        return {"PATH": "/bin"}

    def isolate_git(self, case_dir, env, box=None):
        self.log.append(("isolate_git", box))

    def settings_in(self, case_dir, names):
        self.log.append(("settings_in",))
        for name in sorted(names):
            if os.path.lexists(os.path.join(case_dir, name)):
                return name
        return None

    def file_index(self, case_dir, staged=()):
        self.log.append(("file_index",))
        found = {}
        for dp, _, fns in os.walk(case_dir):
            for fn in fns:
                path = os.path.join(dp, fn)
                found[os.path.relpath(path, case_dir)] = Path(path).read_text()
        return found

    def changes(self, case_dir, before, staged=()):
        self.log.append(("changes",))
        after = self.file_index(case_dir, staged)
        self.log.pop()
        return {"created": sorted(set(after) - set(before)),
                "modified": sorted(p for p in after if p in before and after[p] != before[p]),
                "deleted": sorted(set(before) - set(after)), "unchanged": []}

    def run_failure(self, runner, prompt_path, case_dir, model, out, env, timeout, max_cost, web, start_dir=None, box=None):
        self.log.append(("run_failure", box, dict(env)))
        self.calls += 1
        step = self.script.pop(0) if self.script else {}
        Path(out, "response.md").write_text(step.get("reply", "done"))
        if step.get("log"):
            Path(out, "error.log").write_text(step["log"])
        for rel, text in (step.get("write") or {}).items():
            Path(case_dir, rel).write_text(text)
        if step.get("raise"):
            raise step["raise"]
        return step.get("why")

    def redact_folder(self, folder, values, staged=()):
        self.log.append(("redact_folder", os.path.basename(folder)))
        return 1 if values else 0

    # the account and the lock
    def wait_while_paused(self, key, probe=None):
        self.log.append(("wait_while_paused", key))

    def start_pause(self, key, what):
        self.log.append(("start_pause", key, what))

    def account_limit(self, out_dir, markers):
        text = self.read_text(os.path.join(out_dir, "error.log"), 4000)
        return "LIMIT" if "LIMIT" in text and "LIMIT" in markers else None

    def Slots(self, control, tier, web=False):
        stand_in = self

        class Held:
            def __enter__(self):
                stand_in.log.append(("slots", tier, web))
                return self

            def __exit__(self, *exc):
                stand_in.log.append(("slots_released",))
                return False

        return Held()

    # what a failed attempt left
    def read_text(self, path, limit=4000):
        try:
            with open(path, encoding="utf-8") as f:
                return f.read(limit)
        except OSError:
            return ""

    def provider_refusal(self, out_dir, markers):
        text = self.read_text(os.path.join(out_dir, "error.log"))
        return "the provider refused" if "REFUSED" in text else None

    def auth_refusal(self, out_dir):
        text = self.read_text(os.path.join(out_dir, "error.log"))
        return "HTTP 401" if "AUTH" in text else None

    def early_end(self, response, changed):
        return "it announced work and stopped" if "EARLY" in response else None

    def run_ending(self, out_dir):
        return {"stop_reason": "end_turn"}


def spec_for(dest, **more):
    spec = {"dest": str(dest), "names": ["demo-writes"], "label": "task run 31", "runner": "/x/run-prompt.sh",
            "model": "m", "account": {"key": "h", "markers": ["LIMIT"], "probe": None},
            "refusal_markers": ["REFUSED"], "pass_env": ["H_KEY"], "values": ["secret-value"],
            "settings": [".tool"], "control": {"total_jobs": 2}, "tier": "strong", "web": False, "timeout": 30,
            "max_cost": None, "retries": 2, "prompt": "do it\n", "response_limit": 200000, "counts": None,
            "env_extra": None}
    spec.update(more)
    return spec


@pytest.fixture
def no_sleep(monkeypatch):
    slept = []
    monkeypatch.setattr(ra.time, "sleep", lambda seconds: slept.append(seconds))
    return slept


def names(log):
    return [entry[0] for entry in log]


def test_the_steps_of_one_attempt_run_in_the_labs_order(tmp_path, no_sleep):
    lab = StandIn(tmp_path / "t", [{"write": {"new.md": "x"}}])
    (tmp_path / "t").mkdir()
    seen = []
    hooks = SimpleNamespace(
        build=lambda case_dir, root: (seen.append("build"), Path(case_dir, "input.md").write_text("in")),
        after_base=lambda case_dir, root: seen.append("after_base"),
        stage=lambda case_dir: (seen.append("stage"), ["skills/demo"])[1],
        before_run=lambda case_dir, root, staged: seen.append(("before_run", Path(root, "prompt.md").read_text(), staged)),
        after_run=lambda case_dir, root, why, delta, staged: seen.append(("after_run", why, delta["created"])),
    )
    result = ra.run(lab, spec_for(tmp_path / "run"), hooks)
    assert result["status"] == "ok" and result["failure"] is None
    assert seen == ["build", "after_base", "stage", ("before_run", "do it\n", ["skills/demo"]), ("after_run", None, ["new.md"])]
    order = [n for n in names(lab.log) if n != "contained_env"]
    assert order == ["wait_while_paused", "slots", "new_run_root", "isolate_git", "settings_in", "file_index",
                     "run_failure", "redact_folder", "redact_folder", "changes", "redact_folder", "redact_folder",
                     "return_run", "slots_released"]
    run_call = next(entry for entry in lab.log if entry[0] == "run_failure")
    assert run_call[1] == {"root": run_call[1]["root"], "runner": "/x/run-prompt.sh", "pass": ["H_KEY"], "network": "proxy"}
    assert next(entry for entry in lab.log if entry[0] == "isolate_git")[1]["network"] == "none"
    assert result["delta"]["created"] == ["new.md"] and result["changed"] == ["new.md"]
    assert result["staged"] == ["skills/demo"] and result["timing"] == {"stop_reason": "end_turn"}
    assert result["counts"]["attempts"] == 1 and result["counts"]["redactions"] == 4
    assert (tmp_path / "run" / "cwd" / "new.md").is_file() and (tmp_path / "run" / "prompt.md").is_file()
    assert result["response"] == "done"


def test_env_extra_is_set_in_the_adapter_call_and_named_in_its_box_never_replaced(tmp_path, no_sleep):
    (tmp_path / "t").mkdir()
    lab = StandIn(tmp_path / "t", [{}])
    ra.run(lab, spec_for(tmp_path / "run", env_extra={"TMPDIR": "/run/tmp"}, web=True))
    run_call = next(entry for entry in lab.log if entry[0] == "run_failure")
    assert run_call[1]["pass"] == ["H_KEY", "TMPDIR"] and run_call[1]["network"] == "open"
    assert run_call[2]["TMPDIR"] == "/run/tmp"
    assert ("slots", "strong", True) in lab.log
    roots = []
    lab = StandIn(tmp_path / "t", [{}])
    ra.run(lab, spec_for(tmp_path / "run2", env_extra=lambda root: roots.append(root) or {"TMPDIR": root + "/tmp"}))
    run_call = next(entry for entry in lab.log if entry[0] == "run_failure")
    assert len(roots) == 1 and run_call[2]["TMPDIR"] == roots[0] + "/tmp" and run_call[1]["root"] == roots[0]


@pytest.mark.parametrize("step, kind, detail", [
    ({"why": "timeout: stopped after 30s", "log": "REFUSED AUTH"}, "timeout", None),
    ({"why": "adapter exit 1", "log": "REFUSED AUTH"}, "refused", "the provider refused"),
    ({"why": "adapter exit 1", "log": "AUTH"}, "auth", "HTTP 401"),
    ({"why": "adapter exit 1", "log": "boom"}, "adapter", None),
    ({"reply": "EARLY"}, "early_end", "it announced work and stopped"),
    ({"reply": "fine"}, None, None),
])
def test_a_timeout_a_refusal_a_refused_key_an_adapter_failure_and_an_early_end_are_told_apart_in_the_labs_order(
        tmp_path, no_sleep, step, kind, detail):
    (tmp_path / "t").mkdir()
    lab = StandIn(tmp_path / "t", [step])
    result = ra.run(lab, spec_for(tmp_path / "run", retries=0))
    if kind is None:
        assert result["status"] == "ok" and result["failure"] is None
    else:
        assert result["status"] == "failed"
        assert result["failure"] == {"kind": kind, "reason": step.get("why"), "detail": detail}
    out = tmp_path / "run" / "outputs"
    assert ra.classify(lab, step.get("why"), str(out), ["REFUSED"], step.get("reply", "done"), []) == (kind, detail)


def test_a_failed_attempt_is_made_again_until_the_retries_are_spent_and_each_one_is_kept(tmp_path, no_sleep):
    (tmp_path / "t").mkdir()
    lab = StandIn(tmp_path / "t", [{"why": "timeout: stopped after 30s"}] * 3)
    result = ra.run(lab, spec_for(tmp_path / "run", retries=2))
    assert result["failure"]["kind"] == "timeout" and lab.calls == 3
    assert result["counts"]["attempts"] == 3 and result["counts"]["timeouts"] == 3
    assert sorted(p.name for p in (tmp_path / "run").iterdir()) == ["cwd", "failed-1", "failed-2", "outputs", "prompt.md"]
    assert [(e["event"], e["kind"], e["attempt"]) for e in result["events"]] == [("retry", "timeout", 1), ("retry", "timeout", 2)]
    assert result["events"][0]["kept"] == str(tmp_path / "run" / "failed-1")


def test_a_refused_key_is_never_retried(tmp_path, no_sleep):
    (tmp_path / "t").mkdir()
    lab = StandIn(tmp_path / "t", [{"why": "adapter exit 1", "log": "AUTH"}] * 3)
    result = ra.run(lab, spec_for(tmp_path / "run", retries=2))
    assert result["failure"]["kind"] == "auth" and lab.calls == 1 and result["events"] == []
    assert not any(result["counts"][k] for k in ("timeouts", "refusals", "adapter_failures", "early_ends"))


def test_the_account_limit_pauses_and_the_attempt_does_not_count(tmp_path, no_sleep):
    (tmp_path / "t").mkdir()
    lab = StandIn(tmp_path / "t", [{"why": "adapter exit 1", "log": "LIMIT"}, {}])
    result = ra.run(lab, spec_for(tmp_path / "run", retries=0))
    assert result["status"] == "ok" and lab.calls == 2
    assert result["counts"]["attempts"] == 1 and result["counts"]["pauses"] == 1
    assert ("start_pause", "h", "task run 31") in lab.log
    assert [e["event"] for e in result["events"]] == ["paused"]
    assert (tmp_path / "run" / "paused-1" / "outputs" / "error.log").is_file()
    assert names(lab.log).count("wait_while_paused") == 2 and no_sleep == []


def test_an_adapter_failure_waits_before_the_next_attempt_and_an_early_end_does_not(tmp_path, no_sleep):
    (tmp_path / "t").mkdir()
    lab = StandIn(tmp_path / "t", [{"why": "adapter exit 1", "log": "boom"}, {"reply": "EARLY"}, {}])
    result = ra.run(lab, spec_for(tmp_path / "run", retries=2))
    assert result["status"] == "ok" and lab.calls == 3
    assert no_sleep == [5.0]
    assert [(e["event"], e["kind"]) for e in result["events"]] == [("retry", "adapter"), ("early_end", "early_end")]
    assert (tmp_path / "run" / "failed-1").is_dir() and (tmp_path / "run" / "early-end-1").is_dir()


def test_settings_in_the_copy_end_the_run_before_the_adapter_is_called(tmp_path, no_sleep):
    (tmp_path / "t").mkdir()
    lab = StandIn(tmp_path / "t", [{}])
    hooks = SimpleNamespace(build=lambda case_dir, root: os.makedirs(os.path.join(case_dir, ".tool")),
                            stage=lambda case_dir: pytest.fail("staged although the copy carries settings"))
    result = ra.run(lab, spec_for(tmp_path / "run"), hooks)
    assert result["failure"] == {"kind": "settings", "reason": None, "detail": ".tool"}
    assert lab.calls == 0 and "return_run" in names(lab.log)
    assert (tmp_path / "run" / "cwd" / ".tool").is_dir()


def test_a_stop_ends_the_run_and_the_folders_still_return(tmp_path, no_sleep):
    (tmp_path / "t").mkdir()
    lab = StandIn(tmp_path / "t", [{"why": "adapter exit 1", "log": "boom"}] * 3)
    hooks = SimpleNamespace(after_run=lambda case_dir, root, why, delta, staged: lab.STOPPING.set())
    result = ra.run(lab, spec_for(tmp_path / "run"), hooks)
    assert result["failure"] == {"kind": "stopped", "reason": "adapter exit 1", "detail": None}
    assert lab.calls == 1 and (tmp_path / "run" / "outputs" / "response.md").is_file()
    assert lab.roots == {}


def test_the_folders_return_whatever_a_hook_raises(tmp_path, no_sleep):
    (tmp_path / "t").mkdir()
    lab = StandIn(tmp_path / "t", [{"write": {"made.md": "x"}}])

    def broken(case_dir, root, why, delta, staged):
        raise RuntimeError("the hook broke")

    with pytest.raises(RuntimeError, match="the hook broke"):
        ra.run(lab, spec_for(tmp_path / "run"), SimpleNamespace(after_run=broken))
    assert lab.roots == {} and list((tmp_path / "t").iterdir()) == []
    assert (tmp_path / "run" / "cwd" / "made.md").is_file()
    assert names(lab.log)[-3:] == ["redact_folder", "return_run", "slots_released"]


def test_after_run_is_called_when_the_adapter_call_raises_and_the_first_exception_goes_on(tmp_path, no_sleep):
    (tmp_path / "t").mkdir()
    lab = StandIn(tmp_path / "t", [{"raise": RuntimeError("stopping: no new run is started")}])
    seen = []

    def after_run(case_dir, root, why, delta, staged):
        seen.append((why, delta))
        raise OSError("the hook broke too")

    with pytest.raises(RuntimeError, match="stopping"):
        ra.run(lab, spec_for(tmp_path / "run"), SimpleNamespace(after_run=after_run))
    assert seen == [(None, None)] and lab.roots == {}
    assert names(lab.log)[-3:] == ["redact_folder", "return_run", "slots_released"]


def test_the_judge_hook_can_end_the_run_before_the_classification(tmp_path, no_sleep):
    (tmp_path / "t").mkdir()
    lab = StandIn(tmp_path / "t", [{"why": "adapter exit 1", "log": "boom"}, {}])
    seen = []

    def judge(info):
        seen.append(info["why"])
        return {"contaminated": "it read the harness"} if info["why"] else None

    result = ra.run(lab, spec_for(tmp_path / "run"), SimpleNamespace(judge=judge))
    assert result["status"] == "caller" and result["caller"] == {"contaminated": "it read the harness"}
    assert seen == ["adapter exit 1"] and lab.calls == 1 and result["counts"]["adapter_failures"] == 0


def test_a_name_replaced_on_the_runner_after_import_is_the_one_the_loop_uses(tmp_path, no_sleep):
    (tmp_path / "t").mkdir()
    lab = StandIn(tmp_path / "t", [{"why": "adapter exit 1", "log": "boom"}, {}])
    ra.run(lab, spec_for(tmp_path / "one"))
    lab.RETRY_PAUSE = 0.25
    lab.script = [{"why": "adapter exit 1", "log": "boom"}, {}]
    ra.run(lab, spec_for(tmp_path / "two"))
    assert no_sleep == [5.0, 0.25]


def test_what_an_earlier_call_left_is_set_aside_and_a_hook_stop_raises_before_any_folder(tmp_path, no_sleep):
    (tmp_path / "t").mkdir()
    dest = tmp_path / "run"
    (dest / "outputs").mkdir(parents=True)
    (dest / "failed-1").mkdir()
    lab = StandIn(tmp_path / "t", [{}])

    class Stopped(Exception):
        pass

    def before_attempt():
        raise Stopped()

    with pytest.raises(Stopped):
        ra.run(lab, spec_for(dest), SimpleNamespace(before_attempt=before_attempt))
    assert sorted(p.name for p in dest.iterdir()) == ["before-resume-1", "failed-1"]
    assert lab.calls == 0 and "new_run_root" not in names(lab.log)
    assert not (tmp_path / "never").exists()
    ra.run(StandIn(tmp_path / "t", [{}]), spec_for(tmp_path / "never", counts={"attempts": 0}))
    assert sorted(p.name for p in (tmp_path / "never").iterdir()) == ["cwd", "outputs", "prompt.md"]


def test_the_module_reads_the_runner_only_through_the_object_it_is_given():
    source = (EVALS / "run_attempts.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    stdlib = getattr(sys, "stdlib_module_names", None)
    assert imported <= (set(stdlib) | {"__future__"} if stdlib else {"__future__", "json", "os", "shutil", "sys", "time"})
    # Nothing of the repository is loaded by path either: no importlib, no __import__, no exec.
    assert "importlib" not in imported and "runpy" not in imported
    assert not {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)} & {"__import__", "exec", "eval"}
    read = {node.attr for node in ast.walk(tree)
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "lab"}
    assert read, "the module reads nothing of the runner"
    if not KIT.is_file():
        pytest.skip("evals/execution.py is absent: the names cannot be checked against its list")
    kit = KIT.read_text(encoding="utf-8")
    found = re.search(r"^__all__ = \((.*?)\n\)", kit, re.S | re.M)
    assert found, "__all__ not found in evals/execution.py"
    listed = set(re.findall(r'"([A-Za-z_][A-Za-z0-9_]*)"', re.sub(r"#[^\n]*", "", found.group(1))))
    assert read <= listed, sorted(read - listed)
