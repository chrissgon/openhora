"""Tests of runtime/lab.py, the one file of runtime/ that talks to the lab: what a run sees, what comes back,
how a failed attempt is handled, and which names of evals/eval_run.py the file may read. Offline: the adapter is
a stand-in shell script and runs on this machine (runtime/tests/standin_tree.py); every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_lab_facade.py
"""
from __future__ import annotations

import ast
import os
import re
import sys
import threading
import time
from pathlib import Path

import pytest

import standin_tree as st

lab = st.load("lab")
REAL_PROOF_INPUTS = lab.proof_inputs  # the stand-in tree replaces it; one test needs the real one
REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def tree(tmp_path, monkeypatch):
    return st.build(tmp_path, monkeypatch, lab)


def run(tree, tmp_path, skill="demo-asks", prompt="please\n", files=(), **more):
    with lab.session():
        return lab.run_skill(skill, prompt, list(files), str(tmp_path / "data" / "run-1"), **more)


def test_a_run_sees_the_staged_skill_and_the_given_files_and_nothing_else(tree, tmp_path):
    state = tree["project"] / "docs" / "workbench" / "state.md"
    out = run(tree, tmp_path, files=[(str(state), "docs/workbench/state.md")])
    assert out["status"] == "ok" and out["failure"] is None and out["response"].startswith("Nothing was searched")
    seen = (Path(out["outputs"]) / "files.txt").read_text().split("\n")[:-1]
    assert "./docs/workbench/state.md" in seen and "./.h/skills/demo-asks/SKILL.md" in seen
    assert "./.h/skills/demo-asks/scripts/check.py" in seen
    assert not [p for p in seen if "/evals/" in p or "/scripts/tests/" in p]  # staged as in a lab run
    assert not [p for p in seen if "AGENTS.md" in p or "runtime.json" in p]  # only what the caller listed
    assert out["staged"] == [os.path.join(".h", "skills", "demo-asks")]
    assert out["changes"] == {"created": [], "modified": [], "deleted": [], "unchanged": ["docs/workbench/state.md"]}
    assert (out["model"], out["adapter"], out["tier"], out["web"]) == ("m", "h", "strong", False)
    assert out["timing"]["skills_loaded"] == ["demo-asks"] and out["counts"]["attempts"] == 1


def test_the_folders_of_a_run_come_back_to_its_run_folder_and_the_prompt_is_kept(tree, tmp_path):
    out = run(tree, tmp_path, prompt="first line\n--- the user's answer 1 ---\nhere\n")
    dest = tmp_path / "data" / "run-1"
    assert (out["run_dir"], out["cwd"], out["outputs"]) == (str(dest), str(dest / "cwd"), str(dest / "outputs"))
    assert (dest / "prompt.md").read_text() == "first line\n--- the user's answer 1 ---\nhere\n"
    assert (dest / "cwd" / "docs" / "business" / "market.md").is_file() and (dest / "outputs" / "response.md").is_file()
    assert out["changes"]["created"] == ["docs/business/market.lint.json", "docs/business/market.md",
                                         "docs/workbench/state.md", "notes.txt"]
    assert not [p for p in os.listdir(tmp_path) if p.startswith("eval-")]  # the fresh folder is outside and removed


def test_a_run_whose_adapter_fails_is_made_again_and_the_failed_attempt_is_kept(tree, tmp_path):
    st.fail(tree["adapter"], "adapter", 1)
    out = run(tree, tmp_path)
    assert out["status"] == "ok" and out["counts"]["attempts"] == 2 and out["counts"]["adapter_failures"] == 1
    assert st.calls(tree["adapter"]) == ["demo-asks 1", "demo-asks 2"]
    assert "the provider is down" in (tmp_path / "data" / "run-1" / "failed-1" / "outputs" / "error.log").read_text()


@pytest.mark.parametrize("kind, expected, calls", [("adapter", "adapter", 3), ("refused", "refused", 3),
                                                    ("early", "early_end", 3), ("auth", "auth", 1)])
def test_a_failure_on_every_attempt_is_returned_with_its_kind_and_a_refused_key_is_never_retried(tree, tmp_path, kind, expected, calls):
    st.fail(tree["adapter"], kind, 9)
    out = run(tree, tmp_path)
    assert out["status"] == "failed" and out["failure"]["kind"] == expected and out["changes"] is None
    assert len(st.calls(tree["adapter"])) == calls  # the gate's two retries, and none for a refused key
    if expected == "auth":
        assert out["failure"]["detail"] == "HTTP 401" and "no variable" in out["failure"]["reason"]


def test_a_run_past_its_timeout_is_stopped_and_fails_as_a_timeout(tree, tmp_path):
    st.fail(tree["adapter"], "timeout", 9)
    out = run(tree, tmp_path, timeout=1, retries=0)
    assert out["failure"]["kind"] == "timeout" and out["failure"]["reason"].startswith("timeout: stopped after 1s")
    assert out["counts"] == {"attempts": 1, "timeouts": 1, "refusals": 0, "adapter_failures": 0, "early_ends": 0,
                             "pauses": 0, "redactions": 0}


def test_a_run_that_meets_the_account_limit_pauses_and_starts_again_without_counting_as_a_failure(tree, tmp_path, capsys):
    st.fail(tree["adapter"], "limit", 1)
    out = run(tree, tmp_path, retries=0)  # one failure of any kind would end the run: the limit is none
    assert out["status"] == "ok" and out["counts"]["pauses"] == 1 and out["counts"]["attempts"] == 1
    assert (tree["adapter"] / "probes.txt").is_file() and "PAUSED" in capsys.readouterr().err
    assert (tmp_path / "data" / "run-1" / "paused-1" / "outputs" / "error.log").is_file()
    assert not list((tmp_path / "locks").glob("pause-*.json"))  # the pause is over


def test_a_copy_that_carries_a_tools_settings_is_refused_before_any_model_call(tree, tmp_path):
    planted = tmp_path / "h-settings.json"
    planted.write_text("{}")
    out = run(tree, tmp_path, files=[(str(planted), "config/h-settings.json")])
    assert out["failure"]["kind"] == "settings" and "config/h-settings.json" in out["failure"]["reason"]
    assert st.calls(tree["adapter"]) == []


def test_the_value_of_a_passed_variable_is_replaced_in_everything_a_run_leaves(tree, tmp_path, monkeypatch):
    monkeypatch.setenv("STANDIN_KEY", "invented-value-0123456789")
    out = run(tree, tmp_path, pass_env=["STANDIN_KEY"])
    left = (Path(out["cwd"]) / "leak.txt").read_text() + (Path(out["outputs"]) / "stderr.log").read_text()
    assert "invented-value-0123456789" not in left and "[redacted:STANDIN_KEY]" in left
    assert out["counts"]["redactions"] == 2


def test_what_cannot_run_at_all_is_an_error_that_names_no_value(tree, tmp_path, monkeypatch):
    monkeypatch.delenv("STANDIN_KEY", raising=False)
    for kwargs, word in (({"skill": "no-such-skill"}, "no skill"), ({"pass_env": ["STANDIN_KEY"]}, "STANDIN_KEY is not set"),
                         ({"adapter": "missing"}, "configuration")):
        with pytest.raises(lab.LabError) as e:
            run(tree, tmp_path, **kwargs)
        assert e.value.kind == "config" and word in e.value.reason
    link = tmp_path / "link.md"
    os.symlink(tree["project"] / "AGENTS.md", link)
    for files in ([(str(link), "docs/a.md")], [(str(tree["project"] / "AGENTS.md"), "../a.md")]):
        with pytest.raises(lab.LabError) as e:
            run(tree, tmp_path, files=files)
        assert e.value.kind == "copy"
    assert st.calls(tree["adapter"]) == []


def test_the_runtime_never_builds_the_eval_image_a_missing_one_is_an_error(tree, tmp_path, monkeypatch):
    """Lab evidence is bound to one built image; the executor's ensure() builds a missing one, so the facade
    looks for the image first and never reaches ensure() without it."""
    called = []

    class Executor:
        @staticmethod
        def names():
            return {"image": "wb-eval:invented"}

        @staticmethod
        def docker(*args, check=True, **kwargs):
            called.append(args[:2])
            return type("Result", (), {"returncode": 1, "stdout": "", "stderr": "No such image"})()

        @staticmethod
        def ensure():
            called.append(("ensure",))
            return {}

    er = lab.load()
    monkeypatch.setattr(er, "EXECUTOR", "container")
    monkeypatch.setattr(er, "load_executor", lambda: Executor)
    with pytest.raises(lab.LabError) as e:
        run(tree, tmp_path)
    assert e.value.kind == "container" and "never builds it" in e.value.reason
    assert called == [("image", "inspect")] and st.calls(tree["adapter"]) == []


# Names of the lab's runner (evals/eval_run.py): the event runner, the case files, the variants, the baseline's
# checks, the grading and the evidence rows. None of them is in the execution kit, so the facade cannot read them.
RUNNER_ONLY = (
    "run", "main", "parse", "regrade", "routing", "check_cases_only",
    "load_evals", "preflight", "case_files", "dependency_dirs", "workbench_files", "build_tree",
    "ablated_copy", "ablated_line_count", "contamination", "mount_patterns",
    "shared_passage", "skill_passages", "passages_of", "words_of", "folder_text",
    "grade", "grading_call", "template_hash", "version_control", "shown_in",
    "facts_block", "grading_prompt", "read_grading", "grading_summary", "score", "gate_passes",
    "at_threshold", "within_tolerance", "failed_guards", "confirmed_guards", "guard_positions",
    "run_record_hash", "write_evidence", "evidence_file", "ledger_add", "ledger_read",
    "scratch_reason", "later_test_id", "next_iteration", "find_event", "conditions_of", "agg", "exact_mean",
    "early_end_stats", "early_end_warning",
)


def test_the_facade_reads_only_names_of_the_kits_all_and_of_status_names_and_every_listed_name_exists():
    kit = lab.load()
    assert kit.__name__ == "workbench_eval_execution" and lab.MODULE == kit.__name__
    for name in kit.__all__:
        assert hasattr(kit, name), name
        getattr(lab.LAB, name)
    status = lab.LAB.load_status()
    for name in kit.STATUS_NAMES:
        assert hasattr(status, name), name
    for name in RUNNER_ONLY:
        assert name not in kit.__all__ and name not in kit.STATUS_NAMES, name
        with pytest.raises(AttributeError):
            getattr(lab.LAB, name)
    assert not [name for name in RUNNER_ONLY if name in vars(kit)], "the kit holds a name of the event runner"
    with pytest.raises(AttributeError):
        getattr(lab.LAB, "die")  # a helper of the kit that is not in its __all__


def _slow_counting_spec(monkeypatch, calls, fail_first=False):
    """Make the kit's load slow and counted, on a fresh state: no kit in sys.modules and none cached by the facade."""
    import importlib.util
    monkeypatch.delitem(sys.modules, lab.MODULE, raising=False)
    monkeypatch.setattr(lab, "_KIT", None, raising=False)
    real = importlib.util.spec_from_file_location

    def spec_from_file_location(*args, **kwargs):
        spec = real(*args, **kwargs)
        real_exec = spec.loader.exec_module

        def exec_module(module):
            calls.append(module)
            time.sleep(0.2)  # long enough for every other thread to reach load() while this one is inside it
            if fail_first and len(calls) == 1:
                raise RuntimeError("the first load fails")
            real_exec(module)
        spec.loader.exec_module = exec_module
        return spec
    monkeypatch.setattr(importlib.util, "spec_from_file_location", spec_from_file_location)


def test_the_kit_is_loaded_once_when_several_threads_ask_for_it_at_the_same_time(monkeypatch):
    calls, results, errors = [], [], []
    _slow_counting_spec(monkeypatch, calls)
    start = threading.Barrier(8)

    def ask(use_facade):
        try:
            start.wait()
            if use_facade:  # the path of the 500: a name read through the facade while another thread loads
                results.append(lab.LAB.load_status)
                results.append(lab.load())
            else:
                results.append(lab.load())
        except BaseException as e:  # noqa: BLE001 - the test reports whatever a thread raised
            errors.append(e)

    threads = [threading.Thread(target=ask, args=(i % 2 == 0,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert len(calls) == 1, "the kit's code ran more than once"
    modules = [r for r in results if hasattr(r, "__all__")]
    assert len(modules) == 8 and all(m is modules[0] for m in modules)
    assert sys.modules[lab.MODULE] is modules[0] and hasattr(modules[0], "__all__")


def test_a_failed_load_leaves_nothing_half_made_and_the_next_call_loads_again(monkeypatch):
    calls = []
    _slow_counting_spec(monkeypatch, calls, fail_first=True)
    with pytest.raises(RuntimeError):
        lab.load()
    assert lab.MODULE not in sys.modules
    kit = lab.load()
    assert len(calls) == 2 and hasattr(kit, "__all__") and sys.modules[lab.MODULE] is kit
    assert lab.load() is kit and len(calls) == 2


def test_no_other_module_of_the_runtime_reads_the_lab():
    """The rule of the facade: lab.py is the one file of runtime/ that names anything under evals/, and inside
    lab.py every read of the kit goes through LAB and every read of the status script is a name of STATUS_NAMES."""
    kit = lab.load()
    for path in sorted((st.REPO / "runtime").glob("*.py")):
        text = path.read_text(encoding="utf-8")
        code = "\n".join(line for line in text.split('"""')[2::2]) if path.name != "lab.py" else ""
        assert not re.search(r"eval_run|eval_status|executor\.py|measure\.py|execution\.py", code), path.name
    tree = ast.parse((st.REPO / "runtime" / "lab.py").read_text(encoding="utf-8"))
    read = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name) and node.value.id == "LAB"}
    assert read <= set(kit.__all__), read - set(kit.__all__)
    status_read = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
                   and ((isinstance(node.value, ast.Name) and node.value.id == "status")
                        or (isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name)
                            and node.value.func.id == "_lab_call" and node.value.args
                            and isinstance(node.value.args[0], ast.Attribute) and node.value.args[0].attr == "load_status"))}
    assert status_read and status_read <= set(kit.STATUS_NAMES), status_read - set(kit.STATUS_NAMES)


def test_the_names_of_a_tools_settings_come_from_the_adapters_lists(tree):
    assert lab.settings_names() == sorted(st.EVAL_JSON["settings"])


def test_the_standing_of_a_real_skill_has_a_band_for_the_reference_model_and_names_the_evidences_image():
    found = lab.standing("biz-market-analysis")
    strong = found["tiers"]["strong"]["model"]
    assert strong and strong in found["models"] and found["models"][strong]["band"]
    assert found["evidence_images"] and all(d.startswith("sha256:") for d in found["evidence_images"])
    assert found["version"] and found["tiers"]["floor"]["model"] and found["web_cases"]


class _Done:
    def __init__(self, code, out=""):
        self.returncode, self.stdout, self.stderr = code, out, ""


def test_the_image_is_only_inspected_and_never_built(monkeypatch):
    er = lab.load()
    seen = []

    def never(*args, **kwargs):
        raise AssertionError("lab.image() called ensure(): it may only inspect")

    def docker(*args, **kwargs):
        seen.append(args)
        return _Done(0, "sha256:" + "c" * 64 + "\n") if args[:2] == ("image", "inspect") else _Done(1)

    fake = type("Executor", (), {"names": staticmethod(lambda: {"image": "wb-eval:demo"}), "ensure": staticmethod(never),
                                 "image_platform": staticmethod(lambda: "linux/arm64"), "docker": staticmethod(docker),
                                 "IMAGE_PLATFORM": "linux/amd64"})
    monkeypatch.setattr(er, "EXECUTOR", "container")
    monkeypatch.setattr(er, "load_executor", lambda: fake)
    # platform is what the image runs as here; evidence_platform is the one the lab evidence is made on (the executor's
    # IMAGE_PLATFORM): the two may differ, and the proof holds for the second.
    assert lab.image() == {"name": "wb-eval:demo", "digest": "sha256:" + "c" * 64, "platform": "linux/arm64",
                           "evidence_platform": "linux/amd64"}
    assert seen and all(a[:2] == ("image", "inspect") for a in seen)
    monkeypatch.setattr(fake, "docker", staticmethod(lambda *a, **k: _Done(1)))
    assert lab.image()["digest"] is None
    monkeypatch.setattr(er, "EXECUTOR", "host")
    assert lab.image()["digest"] is None


def test_the_measurement_problem_is_the_status_scripts_own():
    assert lab.measurement_problem() is None


def test_the_proof_inputs_change_when_an_evidence_file_or_the_gate_file_changes(tree):
    evidence = tree["tree"] / "skills" / "demo-asks" / "evals" / "evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / "lab-1.jsonl").write_text("{}\n", encoding="utf-8")
    first = REAL_PROOF_INPUTS("demo-asks")
    assert first == REAL_PROOF_INPUTS("demo-asks") and len(first) == 64
    with open(evidence / "lab-1.jsonl", "ab") as f:
        f.write(b" ")
    second = REAL_PROOF_INPUTS("demo-asks")
    assert second != first
    gate = tree["tree"] / "evals" / "eval-gate.json"
    gate.parent.mkdir(parents=True, exist_ok=True)
    gate.write_text("{}\n", encoding="utf-8")
    assert REAL_PROOF_INPUTS("demo-asks") != second


def test_run_command_runs_with_no_model_no_credential_and_no_network_unless_asked(tree, tmp_path, monkeypatch):
    er = lab.load()
    seen = []
    real = er.run_group

    def spy(cmd, timeout, cwd=None, env=None, box=None):
        seen.append({"cmd": cmd, "box": box, "env": dict(env or {}), "timeout": timeout})
        return real(cmd, timeout, cwd=cwd, env=env, box=box)

    monkeypatch.setattr(er, "run_group", spy)
    monkeypatch.setenv("STANDIN_KEY", "invented-value-0123456789")
    root = tmp_path / "root"
    (root / "case").mkdir(parents=True)
    out = lab.run_command(["git", "--version"], str(root), cwd=str(root / "case"))
    assert out["returncode"] == 0 and out["stdout"].startswith("git version") and out["timed_out"] is False
    lab.run_command(["true"], str(root), network="open", timeout=7)
    assert [s["box"] for s in seen] == [{"root": str(root), "network": "none"}, {"root": str(root), "network": "open"}]
    assert seen[0]["timeout"] == er.SETUP_TIMEOUT and seen[1]["timeout"] == 7
    assert all("STANDIN_KEY" not in s["env"] for s in seen)  # no passed variable: no credential
    for kwargs in ({"network": "proxy"}, {"cwd": str(tmp_path)}):
        with pytest.raises(lab.LabError) as refused:
            lab.run_command(["true"], str(root), **kwargs)
        assert refused.value.kind == "config"
    with pytest.raises(lab.LabError):
        lab.run_command([], str(root))
    slow = lab.run_command(["sleep", "5"], str(root), timeout=1)
    assert slow == {"returncode": None, "stdout": "", "stderr": "", "timed_out": True}


def test_run_command_never_builds_the_eval_image(tree, tmp_path, monkeypatch):
    called = []

    class Executor:
        @staticmethod
        def names():
            return {"image": "wb-eval:invented"}

        @staticmethod
        def docker(*args, check=True, **kwargs):
            called.append(args[:2])
            return type("Result", (), {"returncode": 1, "stdout": "", "stderr": "No such image"})()

        @staticmethod
        def ensure():
            called.append(("ensure",))
            return {}

    er = lab.load()
    monkeypatch.setattr(er, "EXECUTOR", "container")
    monkeypatch.setattr(er, "load_executor", lambda: Executor)
    monkeypatch.setattr(er, "run_group", lambda *a, **k: called.append(("run",)))
    with pytest.raises(lab.LabError) as e:
        lab.run_command(["true"], str(tmp_path))
    assert e.value.kind == "container" and "never builds it" in e.value.reason
    assert called == [("image", "inspect")]


def test_prepare_runs_after_the_base_commit_and_finish_before_the_folders_return_on_every_attempt(tree, tmp_path):
    st.fail(tree["adapter"], "adapter", 1)
    seen = []

    def prepare(copy, root):
        head = lab.run_command(["git", "rev-parse", "HEAD"], root, cwd=copy)
        seen.append(("prepare", head["returncode"], os.path.exists(os.path.join(copy, "placed.txt"))))
        with open(os.path.join(copy, "placed.txt"), "w") as f:
            f.write("placed")

    def finish(copy, root):
        seen.append(("finish", os.path.exists(os.path.join(copy, "placed.txt"))))
        os.remove(os.path.join(copy, "placed.txt"))

    out = run(tree, tmp_path, prepare=prepare, finish=finish)
    assert out["status"] == "ok" and out["counts"]["attempts"] == 2
    assert seen == [("prepare", 0, False), ("finish", True), ("prepare", 0, False), ("finish", True)]
    assert "./placed.txt" in (Path(out["outputs"]) / "files.txt").read_text().split("\n")  # the run saw it
    assert "placed.txt" not in out["changes"]["created"]  # it entered before the index the changes are taken from
    assert not (Path(out["cwd"]) / "placed.txt").exists()  # removed before the folders returned
    assert not (tmp_path / "data" / "run-1" / "failed-1" / "cwd" / "placed.txt").exists()

    def broken(copy, root):
        raise OSError("disk full")

    for hooks in ({"prepare": broken}, {"finish": broken}):
        with pytest.raises(lab.LabError) as e:
            run(tree, tmp_path, **hooks)
        assert e.value.kind == "copy" and "disk full" in e.value.reason


def test_the_base_commit_of_the_copy_is_returned(tree, tmp_path):
    out = run(tree, tmp_path)
    head = lab.run_command(["git", "rev-parse", "HEAD"], out["run_dir"], cwd=out["cwd"])
    assert out["base_commit"] and out["base_commit"] == head["stdout"].strip()
    log = lab.run_command(["git", "log", "--format=%s"], out["run_dir"], cwd=out["cwd"])
    assert log["stdout"].strip() == "fixture"
