"""A test event of a local model, offline (backlog N14): the options of eval_run.py that name one, the run of one command with a
model server (evals/execution.py run_group), and the event it leaves (its evidence file and the line's `local_model`). No docker,
no server, no model: the runner takes the stand-in adapter of test_eval_run.py for the real one, and the container executor is a
recording stand-in.

Run: uv run --with pytest pytest evals/tests/test_local_model_event.py
"""
from __future__ import annotations

import copy
import importlib.util
import json
import os
import subprocess
from pathlib import Path

import pytest


def load(module, name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(f"{module}.py"))
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


t = load("test_eval_run", "eval_run_tests_for_local_models")
lm_tests = load("test_local_models", "local_models_tests_for_events")
evidence_tests = load("test_evidence_lines", "evidence_lines_tests_for_local_models")
er = t.er
KIT = er.KIT
RUN = "0123456789abcdef"


@pytest.fixture(autouse=True)
def own_lock_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(er, "LOCK_DIR", str(tmp_path / "locks"))
    monkeypatch.setattr(KIT, "LOCK_DIR", str(tmp_path / "locks"))
    monkeypatch.setattr(er, "RETRY_PAUSE", 0)
    monkeypatch.setattr(KIT, "RETRY_PAUSE", 0)


@pytest.fixture()
def weights(tmp_path_factory):
    """The weights of a model, outside the (stand-in) checkout, and the local models file that names them."""
    folder = tmp_path_factory.mktemp("weights")
    path = lm_tests.gguf(folder / "example-coder.gguf")
    return path


def config_file(tmp_path_factory, monkeypatch, weights, **changes):
    entry = {"weights": str(weights), "context": 4096, "memory_gb": 8, "cpus": 4, **changes}
    path = tmp_path_factory.mktemp("config") / "local-models.json"
    path.write_text(json.dumps({"models": {"example-coder": entry}}))
    monkeypatch.setenv("WB_LOCAL_MODELS_FILE", str(path))
    return path


def full_id(weights):
    import hashlib
    return f"local/example-coder@{hashlib.sha256(Path(weights).read_bytes()).hexdigest()[:12]}"


# --- the options ------------------------------------------------------------------------------------------------------------------------

def test_a_local_model_is_resolved_to_its_full_id_and_runs_through_agents_dir_alone(tmp_path, tmp_path_factory, monkeypatch, weights, capsys):
    monkeypatch.setattr(er, "ROOT", str(tmp_path))
    monkeypatch.setattr(KIT, "ROOT", str(tmp_path))
    t.configure_gate(tmp_path)
    config_file(tmp_path_factory, monkeypatch, weights, parallel=2, timeout_seconds=900)
    o = er.parse(["--skill", "demo", "--model", "local/example-coder", "--jobs", "6"])
    assert o["models"] == [full_id(weights)] and o["model"] == full_id(weights)
    assert o["harness"] == "agents-dir" and o["adapters"] == {full_id(weights): "agents-dir"} and o["pass_envs"] == {full_id(weights): []}
    assert o["local"]["name"] == "example-coder" and o["local"]["weights_sha256"].startswith(full_id(weights).split("@")[1])
    assert o["local"]["id"] == full_id(weights) and o["local"]["alias"] == full_id(weights)[len("local/"):] and o["local"]["stat"] == lm_tests.lm.stat_of(str(weights))
    assert o["jobs"] == 2 and "--jobs 6 lowered to 2" in capsys.readouterr().err  # "parallel" caps --jobs, and says so
    assert o["timeout"] == 900  # the configured limit of this model, not the gate file's
    json.dumps(o)  # it is kept in the event's options


def test_a_typed_hash_that_does_not_match_the_weights_is_refused(tmp_path, tmp_path_factory, monkeypatch, weights, capsys):
    monkeypatch.setattr(er, "ROOT", str(tmp_path))
    monkeypatch.setattr(KIT, "ROOT", str(tmp_path))
    t.configure_gate(tmp_path)
    config_file(tmp_path_factory, monkeypatch, weights)
    with pytest.raises(SystemExit) as e:
        er.parse(["--skill", "demo", "--model", "local/example-coder@000000000000"])
    assert e.value.code == 2 and "not @000000000000" in capsys.readouterr().err
    assert er.parse(["--skill", "demo", "--model", full_id(weights)])["models"] == [full_id(weights)]


def test_an_explicit_timeout_wins_over_the_configured_one(tmp_path, tmp_path_factory, monkeypatch, weights):
    monkeypatch.setattr(er, "ROOT", str(tmp_path))
    monkeypatch.setattr(KIT, "ROOT", str(tmp_path))
    t.configure_gate(tmp_path, timeout_seconds=1800)
    config_file(tmp_path_factory, monkeypatch, weights, timeout_seconds=900)
    assert er.parse(["--skill", "demo", "--model", "local/example-coder", "--timeout", "600"])["timeout"] == 600
    config_file(tmp_path_factory, monkeypatch, weights)  # none configured: the gate file's
    assert er.parse(["--skill", "demo", "--model", "local/example-coder"])["timeout"] == 1800


@pytest.mark.parametrize("args, why", [
    (["--model", "m", "--model", "local/example-coder"], "tested alone"),
    (["--model", "local/example-coder", "--model", "m"], "tested alone"),
    (["--model", "local/example-coder", "--harness", "claude-code"], "agents-dir adapter only"),
    (["--model", "local/example-coder", "--regrade", "x"], "--routing and --regrade take a hosted model"),
    (["--model", "local/absent"], "not in the local models file"),
    (["--model", "local/Bad Name"], "not a model id"),
    (["--model", "local/BAD"], "not a local model id"),
])
def test_what_a_local_model_event_refuses(tmp_path, tmp_path_factory, monkeypatch, weights, capsys, args, why):
    monkeypatch.setattr(er, "ROOT", str(tmp_path))
    monkeypatch.setattr(KIT, "ROOT", str(tmp_path))
    t.configure_gate(tmp_path)
    config_file(tmp_path_factory, monkeypatch, weights)
    with pytest.raises(SystemExit) as e:
        er.parse(["--skill", "demo", *args])
    assert e.value.code == 2 and why in capsys.readouterr().err


def test_with_no_configuration_file_the_event_says_where_to_make_one(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(er, "ROOT", str(tmp_path))
    monkeypatch.setattr(KIT, "ROOT", str(tmp_path))
    t.configure_gate(tmp_path)
    monkeypatch.setenv("WB_LOCAL_MODELS_FILE", str(tmp_path / "absent.json"))
    with pytest.raises(SystemExit):
        er.parse(["--skill", "demo", "--model", "local/example-coder"])
    assert "there is no local models file" in capsys.readouterr().err


def test_a_dry_run_and_the_modes_that_run_nothing_do_not_hash_the_file(tmp_path, tmp_path_factory, monkeypatch, weights):
    monkeypatch.setattr(er, "ROOT", str(tmp_path))
    monkeypatch.setattr(KIT, "ROOT", str(tmp_path))
    t.configure_gate(tmp_path)
    config_file(tmp_path_factory, monkeypatch, weights)

    def never(*a, **k):
        raise AssertionError("the file was hashed")
    monkeypatch.setattr(er, "resolve_local", never)
    o = er.parse(["--skill", "demo", "--model", "local/example-coder", "--dry-run"])
    assert o["models"] == ["local/example-coder"] and o["local"]["id"] == "local/example-coder"


def test_a_case_on_the_web_is_refused_for_a_local_model_naming_the_cases(tmp_path, tmp_path_factory, monkeypatch, weights, capsys):
    t.write_demo(tmp_path, monkeypatch, t.FAKE, [{"id": 1, "prompt": "p", "assertions": ["a"], "allow_web": True},
                                                   {"id": 2, "prompt": "q", "assertions": ["a"]}])
    t.configure_gate(tmp_path)
    config_file(tmp_path_factory, monkeypatch, weights)
    with pytest.raises(SystemExit) as e:
        er.main(["--skill", "demo", "--model", "local/example-coder", "--runs", "1"])
    err = capsys.readouterr().err
    assert e.value.code == 2 and "case(s) 1 of demo" in err and "no web" in err and "--cases <ids>" in err
    assert not (tmp_path / "evals-workspace").exists()


# --- one command, with its model server ---------------------------------------------------------------------------------------------------------

class FakeExecutor:
    """The container executor as run_group sees it: it records what is started and stopped."""

    class ExecutorError(RuntimeError):
        pass

    def __init__(self, hold_error=None):
        self.calls, self.hold_error = [], hold_error

    def new_run_id(self):
        return RUN

    def held_route(self, *a, **k):
        self.calls.append(("held_route",))
        return None

    def host_cpus(self, env=None):
        return 6

    def hold_local(self, run_id, spec, env=None, image=None):
        self.calls.append(("hold_local", run_id, spec))
        if self.hold_error:
            raise self.ExecutorError(self.hold_error)

    def command(self, cmd, root, **kwargs):
        self.calls.append(("command", kwargs))
        return ["docker", "run"], f"wb-eval-run-{kwargs['run_id']}"

    def remove(self, name, env=None):
        self.calls.append(("remove", name))

    def release_local(self, run_id, env=None):
        self.calls.append(("release_local", run_id))

    def release(self, run_id, env=None):
        self.calls.append(("release", run_id))

    def read_meter(self, path):
        return None


@pytest.fixture()
def kit(monkeypatch):
    executor = FakeExecutor()
    monkeypatch.setattr(KIT, "EXECUTOR", "container")
    monkeypatch.setattr(KIT, "load_executor", lambda: executor)
    ran = []

    def fake_run(cmd, timeout, cwd, env, container):
        ran.append(container)
        return subprocess.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(KIT, "_run_group", fake_run)
    return executor, ran


def box_of(weights, **changes):
    lm = lm_tests.lm
    return {"root": "/r", "network": "proxy", "pass": [], "model": full_id(weights),
            "local": {"alias": full_id(weights)[6:], "weights": str(weights), "stat": lm.stat_of(str(weights)), "context": 4096, "memory_gb": 8,
                      "accelerator": "cpu", "cpus": None, "load_timeout_seconds": 900, **changes}}


def test_a_local_run_starts_its_server_then_its_container_and_removes_the_container_then_the_server(kit, weights):
    executor, ran = kit
    box = box_of(weights)
    result = KIT.run_group(["bash", "-c", "true"], 60, env={"PATH": "/usr/bin"}, box=box)
    assert result.returncode == 0 and ran == [f"wb-eval-run-{RUN}"]
    names = [c[0] for c in executor.calls]
    assert names == ["hold_local", "command", "remove", "release_local"]
    hold = executor.calls[0]
    assert hold[1] == RUN and hold[2]["cpus"] == 6 and hold[2]["alias"] == box["local"]["alias"]  # the docker host's count, when none is configured
    command = executor.calls[1][1]
    assert command["local"]["context"] == 4096
    assert command["network"] == "proxy" and command["run_id"] == RUN
    assert not KIT.LOCAL_HELD and not KIT.HELD  # nothing is left registered
    assert box["meter"] is None  # a local run has no key proxy and no meter


def test_a_weights_file_that_changed_fails_the_run_before_any_server_starts(kit, weights):
    executor, ran = kit
    box = box_of(weights)
    with open(weights, "ab") as f:
        f.write(b"x")
    result = KIT.run_group(["bash", "-c", "true"], 60, env={"PATH": "/usr/bin"}, box=box)
    assert result.returncode == 1 and "Error: the weights changed during the event" in result.stderr
    assert executor.calls == [] and ran == [] and not KIT.LOCAL_HELD


def test_a_server_that_does_not_start_fails_the_run_as_infrastructure_and_is_released(kit, weights):
    executor, ran = kit
    executor.hold_error = "the model server was not ready within 900 seconds (load_timeout_seconds): out of memory"
    result = KIT.run_group(["bash", "-c", "true"], 60, env={"PATH": "/usr/bin"}, box=box_of(weights))
    assert result.returncode == 1 and "not ready within 900 seconds" in result.stderr and ran == []
    assert [c[0] for c in executor.calls] == ["hold_local", "release_local"] and not KIT.LOCAL_HELD


def test_a_timeout_or_a_stop_of_the_run_still_releases_the_server(kit, weights, monkeypatch):
    executor, ran = kit

    def timing_out(cmd, timeout, cwd, env, container):
        raise subprocess.TimeoutExpired(cmd, timeout)
    monkeypatch.setattr(KIT, "_run_group", timing_out)
    with pytest.raises(subprocess.TimeoutExpired):
        KIT.run_group(["bash", "-c", "true"], 1, env={"PATH": "/usr/bin"}, box=box_of(weights))
    assert [c[0] for c in executor.calls] == ["hold_local", "command", "remove", "release_local"] and not KIT.LOCAL_HELD


def test_stopping_the_script_releases_every_model_server_still_up(kit):
    executor, _ = kit
    KIT.LOCAL_HELD.update({RUN, "fedcba9876543210"})
    try:
        KIT.stop_all_groups(grace=0.1)
    finally:
        KIT.STOPPING.clear()
        KIT.LOCAL_HELD.clear()
    assert sorted(c[1] for c in executor.calls if c[0] == "release_local") == sorted([RUN, "fedcba9876543210"])


def test_a_hosted_run_does_not_start_a_model_server(kit):
    executor, ran = kit
    KIT.run_group(["bash", "-c", "true"], 60, env={"PATH": "/usr/bin"}, box={"root": "/r", "network": "proxy", "pass": [], "model": "m"})
    assert [c[0] for c in executor.calls] == ["held_route", "command", "remove"] and "local" not in executor.calls[1][1]


def test_a_command_with_no_network_gets_no_server(kit, weights):
    executor, _ = kit
    KIT.run_group(["bash", "-c", "true"], 60, env={"PATH": "/usr/bin"}, box={**box_of(weights), "network": "none"})
    assert [c[0] for c in executor.calls] == ["held_route", "command", "remove"]


# --- the event and its evidence --------------------------------------------------------------------------------------------------------------

STUB_LINE = {"file_type": "MOSTLY_Q4_K_M", "context": 4096, "accelerator": "cpu", "server_image": "sha256:" + "d" * 64,
             "server_version": "version: 0.5.0-dev (build 11277, commit eae11d221)", "server_args_sha256": "e" * 64}


def local_event(tmp_path, tmp_path_factory, monkeypatch, weights, runner=t.FAKE, **config):
    """A tree with the stand-in adapter as agents-dir, a configured gate, a local models file; the boxes the runs were given."""
    skill = t.write_demo(tmp_path, monkeypatch, runner)
    adapter = tmp_path / "adapters" / "agents-dir"
    adapter.mkdir(parents=True)
    (adapter / "eval.json").write_text(t.EVAL_JSON)
    (adapter / "run-prompt.sh").write_text(runner)
    t.configure_gate(tmp_path)
    config_file(tmp_path_factory, monkeypatch, weights, **config)
    local = tmp_path_factory.mktemp("local-evidence")
    monkeypatch.setenv("WB_LOCAL_EVIDENCE_DIR", str(local))
    boxes = []

    def run(cmd, timeout, cwd=None, env=None, box=None):
        boxes.append(box)
        return er._run_group(cmd, timeout, cwd, env, None)
    monkeypatch.setattr(er, "run_group", run)
    monkeypatch.setattr(KIT, "run_group", run)
    monkeypatch.setattr(er, "describe_local", lambda spec: {spec["id"]: {"weights_sha256": spec["weights_sha256"], **STUB_LINE,
                                                                         "file_type": spec["file_type"]}})
    (tmp_path / ".gitignore").write_text("evals-workspace/\nlocks/\n")
    for command in (["git", "init", "-q"], ["git", "add", "-A"], ["git", "-c", "user.name=t", "-c", "user.email=t@example.test", "commit", "-q", "-m", "t"]):
        subprocess.run(command, cwd=tmp_path, check=True, capture_output=True)
    return skill, local, boxes


def test_an_event_of_a_local_model_leaves_its_evidence_in_the_persons_own_folder_with_the_local_model_line(tmp_path, tmp_path_factory, monkeypatch, weights, capsys):
    skill, local, boxes = local_event(tmp_path, tmp_path_factory, monkeypatch, weights, timeout_seconds=900)
    assert er.main(["--skill", "demo", "--model", "local/example-coder", "--runs", "1", "--jobs", "3"]) == 0
    err = capsys.readouterr()
    out = json.loads(err.out)
    model = full_id(weights)
    assert out["evidence"]["written"] is True and out["evidence"]["home"] == "local" and "not one of the gate file's lab models" in err.err
    written = Path(out["evidence"]["path"])
    assert written.parent == local / "demo" and t.evidence_of(skill) == []
    lines = [json.loads(l) for l in written.read_text().splitlines()]
    event, runs = lines[0], lines[1:]
    assert event["models"] == [model] and event["adapters"] == {model: "agents-dir"} and event["timeout_seconds"] == 900
    assert event["local_model"] == {model: {"weights_sha256": event["local_model"][model]["weights_sha256"], **STUB_LINE, "file_type": "MOSTLY_Q4_K_M"}}
    assert model.endswith(event["local_model"][model]["weights_sha256"][:12])
    assert {l["model"] for l in runs} == {model} and "upstream" not in event and all("cpu_platform" in l for l in runs)
    status = er.load_status()
    assert status.evidence_file_problems(str(written), str(tmp_path), "demo") == []
    # the boxes the model runs were given carry the description of the local model, and the grading calls do not
    model_boxes = [b for b in boxes if b and b.get("local")]
    assert model_boxes and all(b["network"] == "proxy" and b["local"]["context"] == 4096 and b["local"]["cpus"] == 4 for b in model_boxes)
    assert all(b["local"]["alias"] == model[len("local/"):] for b in model_boxes)
    assert any(b and not b.get("local") for b in boxes)  # the grader's calls are the gate file's, hosted


def test_an_event_whose_weights_changed_while_it_ran_is_a_trial(tmp_path, tmp_path_factory, monkeypatch, weights, capsys):
    changing = t.FAKE.replace('echo ok > "$out/response.md"', f'printf x >> "{weights}"\necho ok > "$out/response.md"')
    skill, local, boxes = local_event(tmp_path, tmp_path_factory, monkeypatch, weights, runner=changing)
    er.main(["--skill", "demo", "--model", "local/example-coder", "--runs", "1"])
    captured = capsys.readouterr()
    out = json.loads(captured.out)
    assert out["evidence"]["written"] is False
    assert "the weights changed during the event" in out["evidence"]["reason"] and "WARNING the weights changed during the event" in captured.err
    assert not list((local / "demo").glob("*")) if (local / "demo").exists() else True
    assert t.evidence_of(skill) == []


def test_an_event_with_another_timeout_than_the_configured_one_is_a_trial(tmp_path, tmp_path_factory, monkeypatch, weights, capsys):
    skill, local, _ = local_event(tmp_path, tmp_path_factory, monkeypatch, weights, timeout_seconds=900)
    er.main(["--skill", "demo", "--model", "local/example-coder", "--runs", "1", "--timeout", "600"])
    out = json.loads(capsys.readouterr().out)
    assert out["evidence"]["written"] is False
    assert "timeout 600, and the configured value is 900 (the local models file, timeout_seconds of example-coder)" in out["evidence"]["reason"]


def test_a_resumed_event_hashes_the_weights_again_and_refuses_another_file(tmp_path, tmp_path_factory, monkeypatch, weights, capsys):
    fail_one = t.FAKE.replace('echo ok > "$out/response.md"', 'if [ -f "$(dirname "$0")/fail" ]; then echo broken >&2; exit 7; fi\necho ok > "$out/response.md"')
    skill, local, _ = local_event(tmp_path, tmp_path_factory, monkeypatch, weights, runner=fail_one)
    (tmp_path / "adapters" / "agents-dir" / "fail").write_text("")
    er.main(["--skill", "demo", "--model", "local/example-coder", "--runs", "1"])
    out = json.loads(capsys.readouterr().out)
    assert out["failures"] > 0
    folder = str(tmp_path / out["iteration_dir"])
    lm_tests.gguf(weights, file_type=7)  # other bytes under the same name
    with pytest.raises(SystemExit) as e:
        er.main(["--resume", folder])
    assert e.value.code == 2 and "cannot be resumed" in capsys.readouterr().err
    event = json.loads((Path(folder) / "event.json").read_text())
    assert event["options"]["local"]["id"] == event["options"]["models"][0] and event["options"]["local"]["id"].startswith("local/example-coder@")


def test_a_resumed_event_of_unchanged_weights_runs_its_failed_runs_and_keeps_its_local_model_line(tmp_path, tmp_path_factory, monkeypatch, weights, capsys):
    fail_one = t.FAKE.replace('echo ok > "$out/response.md"', 'if [ -f "$(dirname "$0")/fail" ]; then echo broken >&2; exit 7; fi\necho ok > "$out/response.md"')
    skill, local, boxes = local_event(tmp_path, tmp_path_factory, monkeypatch, weights, runner=fail_one)
    (tmp_path / "adapters" / "agents-dir" / "fail").write_text("")
    er.main(["--skill", "demo", "--model", "local/example-coder", "--runs", "1"])
    out = json.loads(capsys.readouterr().out)
    (tmp_path / "adapters" / "agents-dir" / "fail").unlink()
    assert er.main(["--resume", str(tmp_path / out["iteration_dir"])]) == 0
    done = json.loads(capsys.readouterr().out)
    assert done["complete"] is True and done["evidence"]["written"] is True, done["evidence"]
    event = json.loads(Path(done["evidence"]["path"]).read_text().splitlines()[0])
    assert list(event["local_model"]) == [full_id(weights)] and [b["local"]["cpus"] for b in boxes if b and b.get("local")][-1] == 4


# --- the line ---------------------------------------------------------------------------------------------------------------------------------

def valid_local_event():
    committed = evidence_tests.COMMITTED[0]
    event = evidence_tests.read(committed)[0]
    new = {k: v for k, v in evidence_tests.as_list_shape([event])[0].items() if k not in ("upstream", "gate")}
    model = "local/example-coder@" + "ab" * 6
    line = {**new, "kind": "partial", "models": [model], "adapters": {model: "agents-dir"}, "adapter_sha256": {"agents-dir": "a" * 64},
            "counts": {}, "grader": "unknown", "complete": True,
            "local_model": {model: {"weights_sha256": "ab" * 6 + "0" * 52, **STUB_LINE}}}
    line.pop("complete_models", None)
    return line, model


def test_the_local_model_line_is_valid_in_its_closed_form():
    line, model = valid_local_event()
    assert evidence_tests.el.event_line_problems(line) == []


@pytest.mark.parametrize("change", [
    lambda l, m: l["local_model"][m].update(weights_sha256="cd" * 32),            # not the hash the id starts with
    lambda l, m: l["local_model"][m].update(weights_sha256="ab"),
    lambda l, m: l["local_model"][m].update(file_type="Q4_K_M"),                  # not llama.cpp's name
    lambda l, m: l["local_model"][m].update(context=0),
    lambda l, m: l["local_model"][m].update(context="4096"),
    lambda l, m: l["local_model"][m].update(accelerator="tpu"),
    lambda l, m: l["local_model"][m].update(server_image="ghcr.io/ggml-org/llama.cpp:server-b11277"),
    lambda l, m: l["local_model"][m].update(server_version="a version\nwith a second line"),
    lambda l, m: l["local_model"][m].update(server_args_sha256="e" * 63),
    lambda l, m: l["local_model"][m].update(note="free text"),                    # no free-text field
    lambda l, m: l["local_model"][m].pop("context"),
    lambda l, m: l.update(local_model={}),
    lambda l, m: l.update(local_model=[]),
    lambda l, m: l["local_model"].update({"another-model": dict(l["local_model"][m])}),   # not a model the line names, not a local id
    lambda l, m: l.update(local_model={"local/example-coder": dict(l["local_model"][m])}),  # a typed id, not a resolved one
])
def test_a_local_model_line_outside_its_closed_form_is_refused(change):
    line, model = valid_local_event()
    change(line, model)
    problems = evidence_tests.el.event_line_problems(line)
    assert any(p.startswith("local_model must be") for p in problems), problems


def test_the_line_of_a_hosted_event_has_no_local_model():
    assert "local_model" in evidence_tests.el.EVENT_OPTIONAL
    for path in evidence_tests.COMMITTED[:3]:
        assert "local_model" not in evidence_tests.read(path)[0]
