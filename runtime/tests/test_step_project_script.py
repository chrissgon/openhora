"""Tests of the step kind `project-script` (package P9): its arguments, the files it reads and refuses, the steps on the engine against a
stand-in provider of script:project (runtime/tests/script_fixture.py: a real process started by providers/resolve.py with the minimum
environment, running no container), the version it makes of a source, and the rule that the dispatcher never starts it. The container
itself, the proxy and the image are tested in providers/script/tests/. Offline; invented names only.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_step_project_script.py
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path

import pytest

import script_fixture as fx
import standin_tree as st
from sources_fixture import standin_convert

lab = st.load("lab")
ops = st.load("ops")
ops_core = st.load("ops_core")
ops_steps = st.load("ops_steps")
dispatcher = st.load("dispatcher")
plan = st.load("plan")
sources = st.load("sources")
steps = st.load("steps")
kind = st.load("step_project_script")

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("WB_LOCAL_EVIDENCE_DIR", str(tmp_path / "evidence"))
    built = st.build(tmp_path, monkeypatch, lab)
    monkeypatch.setattr(ops_core, "ROOT", str(built["tree"]))
    monkeypatch.setattr(sources, "provider_convert", lambda cfg, call=None: standin_convert)
    fx.install(built["tree"])
    project = str(built["project"])
    ops.accept_config(project, ops.project_config.load(project)["sha256"])
    built["path"] = project
    return built


def ctx_of(world):
    return ops_core.context(world["path"])


def task(world, task_id):
    ctx = ctx_of(world)
    return ctx["store"].task_get(ctx["conn"], task_id)


def add(world, script="scripts/report.py", text="# fake: md=Hello from the script\n", source="report", destinations=(), lock=None,
        lock_text=None, key="report-script", sha=None):
    """A project-script step task for a script the test writes into the project; the arguments carry the hash of what was written."""
    digest = fx.write(world["project"], script, text)
    args = {"script": script, "sha256": sha or digest, "source": source, "destinations": list(destinations)}
    if lock:
        args.update(lock=lock, lock_sha256=fx.write(world["project"], lock, lock_text))
    ctx = ctx_of(world)
    return steps.add_task(ctx["store"], ctx["conn"], "project-script", args, key=key, title="Run the report", text="Run the report script.")


def run(world, made):
    return ops.run_step(world["path"], made["task"])


def calls(world):
    return fx.calls(world["tree"])


def key_text(n=16):
    return "AKIA" + "Q" * n       # a text in a credential's format, built at run time


# --- the kind -----------------------------------------------------------------------------------------------------------------------


def test_the_kind_is_registered_with_three_steps_an_empty_footprint_and_is_not_started_by_the_dispatcher():
    found = steps.kind_of("project-script")
    assert found.order == ("verify", "deps", "run") and found.stops == () and found.unattended is False
    assert found.brings_source is True and "project-script" in steps.sourcing_kinds()
    assert steps.footprint_of(found, {}) == []                       # it writes nothing in the project
    assert "project-script" in steps.load_builtin()


def test_the_arguments_are_checked_and_made_canonical_so_the_plan_hash_covers_exactly_what_runs():
    args = {"script": "scripts/report.py", "sha256": "a" * 64, "source": "report", "destinations": ["API.Example.:443", "b.example:8443", "api.example:443"]}
    assert steps.plan_task("project-script", args, key="k", title="T", text="X.")["args"] == {
        "script": "scripts/report.py", "sha256": "a" * 64, "source": "report", "destinations": ["api.example:443", "b.example:8443"]}
    with_lock = {**args, "lock": "scripts/requirements.lock", "lock_sha256": "b" * 64}
    assert steps.plan_task("project-script", with_lock, key="k", title="T", text="X.")["args"]["lock_sha256"] == "b" * 64
    base = steps.plan_task("project-script", args, key="k", title="T", text="X.")
    for change in ({"sha256": "c" * 64}, {"destinations": []}, {"source": "other"}, {"script": "scripts/other.py"}):
        other = steps.plan_task("project-script", {**args, **change}, key="k", title="T", text="X.")
        assert plan.plan_hash([base]) != plan.plan_hash([other]), change
    assert plan.plan_hash([base]) != plan.plan_hash([steps.plan_task("project-script", with_lock, key="k", title="T", text="X.")])


@pytest.mark.parametrize("change", [
    {"script": "/etc/passwd"}, {"script": "../report.py"}, {"script": "scripts/../report.py"}, {"script": ".hidden/report.py"},
    {"script": "scripts/.env.py"}, {"script": "scripts/report.rb"}, {"script": "scripts/report"}, {"script": "a/b/c/d/e/f/g.py"},
    {"script": "scripts\\report.py"}, {"script": ""}, {"script": None}, {"sha256": "A" * 64}, {"sha256": "a" * 63}, {"source": "Bad Id"},
    {"destinations": ["127.0.0.1:443"]}, {"destinations": ["[::1]:443"]}, {"destinations": ["localhost:80"]}, {"destinations": ["api.example"]},
    {"destinations": ["api.example:0"]}, {"destinations": ["api.example:65536"]}, {"destinations": ["*.example:443"]},
    {"destinations": ["2130706433:80"]}, {"destinations": ["0x7f000001:80"]}, {"destinations": ["1.2.3.0x7f:80"]},
    {"destinations": ["a.example:443"] * 9 + [f"h{i}.example:443" for i in range(9)]}, {"destinations": "api.example:443"},
    {"lock": "scripts/r.lock"}, {"lock_sha256": "a" * 64}, {"lock": "scripts/r.lock", "lock_sha256": "x"},
    {"unknown": 1}])
def test_a_bad_argument_is_refused_with_a_closed_code(change):
    args = {"script": "scripts/report.py", "sha256": "a" * 64, "source": "report", "destinations": [], **change}
    with pytest.raises(steps.StepFailure) as refused:
        steps.plan_task("project-script", args, key="k", title="T", text="X.")
    assert refused.value.code == "bad_args"


def test_a_shell_script_has_no_dependencies_and_a_missing_key_is_refused():
    args = {"script": "scripts/run.sh", "sha256": "a" * 64, "source": "report", "lock": "scripts/r.lock", "lock_sha256": "b" * 64}
    with pytest.raises(steps.StepFailure) as refused:
        kind.check(args)
    assert (refused.value.code, refused.value.field) == ("bad_args", "lock")
    for missing in ("script", "sha256", "source"):
        with pytest.raises(steps.StepFailure) as refused:
            kind.check({k: v for k, v in {"script": "scripts/run.sh", "sha256": "a" * 64, "source": "report"}.items() if k != missing})
        assert refused.value.field == missing


def test_the_declaration_rules_of_the_kind_and_of_the_proxy_are_the_same_rules():
    spec = importlib.util.spec_from_file_location("proxy_under_test", REPO / "providers" / "script" / "egress_proxy.py")
    proxy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(proxy)
    corpus = ["api.example:443", "API.Example.:443", "a-b.c-d.example:1", "x.y:65535", "x.example:65536", "x.example:0", "x.example:", "x.example",
              ":443", "127.0.0.1:80", "10.0.0.1:80", "[::1]:80", "::1:80", "localhost:80", "a.b.c.1:80", "a.b.0x7f:80", "0x7f000001:80",
              "2130706433:80", "-a.example:80", "a-.example:80", "a..example:80", "a b.example:80", "ü.example:80", "a.example:80 ", "*.example:80",
              "a.example:080", "a.example:+80", "a.example:００", ("a" * 64) + ".example:80", ".".join(["a"] * 130) + ".com:80", "A.COM:80"]
    for item in corpus:
        try:
            proxy.parse_declared([item])
            accepted = True
        except proxy.Refused:
            accepted = False
        try:
            kind.check_destination(item)
            same = True
        except steps.StepFailure:
            same = False
        assert accepted == same, item


def test_the_lock_rules_of_the_kind_and_of_the_build_container_are_the_same_rules():
    spec = importlib.util.spec_from_file_location("inner_under_test", REPO / "providers" / "script" / "_inner.py")
    inner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(inner)
    h = "a" * 64
    corpus = ["", "# c\n", "r==1 --hash=sha256:" + h + "\n", "r==1 \\\n --hash=sha256:" + h + "\n", "r==1 \\\n\n--hash=sha256:" + h, "r>=1 --hash=sha256:" + h,
              "r==1\n", "-r x\n", "--index-url https://x.example\n", "r==1 --hash=sha256:abc\n", "r==1 --hash=md5:" + h + "\n",
              "r==1 --hash=sha256:" + h + " --no-binary x\n", "r[x]==1 --hash=sha256:" + h, "r @ https://x.example/r.whl --hash=sha256:" + h,
              "r==1 --hash=sha256:" + h + "\n" * 3 + "s==2 --hash=sha256:" + h, "r==1 \\\n", "\r\n".join(["r==1 --hash=sha256:" + h] * 3),
              "\n".join(f"p{i}==1 --hash=sha256:{h}" for i in range(201)), "\n".join(f"p{i}==1 --hash=sha256:{h}" for i in range(200))]
    for text in corpus:
        try:
            inner.check_lock(text)
            clean = True
        except ValueError:
            clean = False
        assert (kind.lock_problem(text.encode()) is None) == clean, text[:40]
    assert kind.lock_problem(b"\xff\xfe") is not None


# --- prepare: the hashes and the credential scan before anything is approved ---------------------------------------------------------


def test_prepare_gives_the_arguments_with_the_hash_of_the_file_as_it_is_now(world):
    sha = fx.write(world["project"], "scripts/report.py", "# fake: md=Hi\nprint('x')\n")
    got = kind.prepare(world["path"], "scripts/report.py", "report", ["API.example:443"])
    assert got == {"script": "scripts/report.py", "sha256": sha, "source": "report", "destinations": ["api.example:443"]}
    lock = ("requests==2.32.3 \\\n    --hash=sha256:" + "a" * 64 + " \\\n    --hash=sha256:" + "b" * 64 + "\n")
    lock_sha = fx.write(world["project"], "scripts/requirements.lock", lock)
    got = kind.prepare(world["path"], "scripts/report.py", "report", [], "scripts/requirements.lock")
    assert got["lock"] == "scripts/requirements.lock" and got["lock_sha256"] == lock_sha


def test_prepare_refuses_a_credential_naming_the_line_and_never_printing_the_value(world, capsys):
    secret = key_text()
    fx.write(world["project"], "scripts/leaky.py", f"# fake: md=Hi\nimport os\nTOKEN = '{secret}'\n")
    with pytest.raises(steps.StepFailure) as refused:
        kind.prepare(world["path"], "scripts/leaky.py", "report")
    failure = refused.value
    assert (failure.code, failure.field) == ("script_has_credential", "line_3")
    assert secret not in failure.next and secret not in str(failure) and "line 3" in failure.next
    assert kind.main(["prepare", "--project", world["path"], "--script", "scripts/leaky.py", "--source", "report"]) == 1
    seen = capsys.readouterr()
    assert secret not in seen.out + seen.err and "script_has_credential line_3" in seen.err


def test_prepare_refuses_a_lock_file_that_holds_a_credential_or_is_not_a_hashed_lock(world):
    fx.write(world["project"], "scripts/report.py", "# fake: md=Hi\n")
    fx.write(world["project"], "scripts/loose.lock", "requests>=2\n")
    with pytest.raises(steps.StepFailure) as refused:
        kind.prepare(world["path"], "scripts/report.py", "report", [], "scripts/loose.lock")
    assert refused.value.code == "bad_lock"
    for text in ("--index-url https://pkgs.example/simple\nrequests==2.0 --hash=sha256:" + "a" * 64 + "\n",
                 "requests==2.0 --hash=sha256:" + "a" * 64 + " --find-links /tmp\n", "-r other.txt\n", "git+https://repo.example/x.git#egg=x\n",
                 "requests==2.0\n", "", "# only a comment\n"):
        fx.write(world["project"], "scripts/odd.lock", text)
        with pytest.raises(steps.StepFailure) as refused:
            kind.prepare(world["path"], "scripts/report.py", "report", [], "scripts/odd.lock")
        assert refused.value.code == "bad_lock", text
    fx.write(world["project"], "scripts/key.lock", f"requests==2.0 --hash=sha256:{'a' * 64}\n# {key_text()}\n")
    with pytest.raises(steps.StepFailure) as refused:
        kind.prepare(world["path"], "scripts/report.py", "report", [], "scripts/key.lock")
    assert (refused.value.code, refused.value.field) == ("script_has_credential", "line_2")


def test_a_hashed_lock_is_not_taken_for_a_credential(world):
    fx.write(world["project"], "scripts/report.py", "# fake: md=Hi\n")
    fx.write(world["project"], "scripts/ok.lock", "requests==2.32.3 --hash=sha256:" + "1a2b3c4d" * 8 + "\n")
    assert kind.prepare(world["path"], "scripts/report.py", "report", [], "scripts/ok.lock")["lock"] == "scripts/ok.lock"


def test_prepare_reads_a_script_that_is_not_text_a_link_or_a_missing_file_as_a_refusal(world):
    (world["project"] / "scripts").mkdir()
    (world["project"] / "scripts" / "bin.py").write_bytes(b"\xff\xfe\x00 not text")
    (world["project"] / "real.py").write_text("# fake: md=Hi\n")
    (world["project"] / "scripts" / "link.py").symlink_to(world["project"] / "real.py")
    (world["project"] / "linked").symlink_to(world["project"] / "scripts")
    for script, code in (("scripts/bin.py", "script_not_text"), ("scripts/link.py", "script_missing"), ("scripts/none.py", "script_missing"),
                         ("linked/bin.py", "path_unsafe")):
        with pytest.raises(steps.StepFailure) as refused:
            kind.prepare(world["path"], script, "report")
        assert refused.value.code == code, script


def test_a_script_in_the_sources_folder_is_not_read(world):
    sources_dir = Path(ctx_of(world)["cfg"]["sources_dir"])
    cfg = ctx_of(world)["cfg"]
    inside = sources_dir / "x.py"
    inside.write_text("# fake: md=Hi\n")
    with pytest.raises(steps.StepFailure) as refused:
        kind.read_project_file(str(sources_dir), "x.py", lambda path: sources.inside(cfg, path))
    assert refused.value.code == "protected_path"


# --- the steps on the engine ---------------------------------------------------------------------------------------------------------


def test_a_script_runs_from_a_fixture_and_its_output_is_a_new_version_of_the_source_labelled_with_the_script(world):
    made = add(world)
    out = run(world, made)
    assert out["ok"] is True and out["done"] is True and out["step"] == "project-script" and out["task_state"] == "done"
    assert out["steps"] == {"verify": "done", "deps": "done", "run": "done"}
    row = task(world, made["task"])
    result = row["step_state"]["steps"]["run"]["result"]
    assert result == {"source": "report", "version": 1, "made": True, "unchanged": False, "exit": 0, "duration_ms": 7}
    ctx = ctx_of(world)
    version = ctx["store"].source_latest(ctx["conn"], "report")
    assert version["version"] == 1 and version["converted_name"] == "converted.md" and version["by"] == "runtime"
    folder = Path(ctx["cfg"]["sources_dir"]) / "report" / "1"
    assert (folder / "converted.md").read_text() == "Hello from the script\n"
    manifest = json.loads((folder / "manifest.json").read_text())
    sha = hashlib.sha256(Path(world["project"] / "scripts" / "report.py").read_bytes()).hexdigest()
    assert manifest["produced_by"] == {"kind": "project-script", "script": "scripts/report.py", "script_sha256": sha, "destinations": []}
    assert manifest["converter"] == {"name": "project-script", "tools": {"script": "scripts/report.py", "script_sha256": sha, "destinations": []}}
    assert version["converter"] == "project-script" and sha in version["converter_version"]
    assert ctx["store"].task_runs_list(ctx["conn"], made["task"]) == []          # no model, no run row


def test_the_provider_is_called_with_the_staged_copy_in_a_private_folder_and_never_with_the_project_file(world):
    made = add(world, destinations=["B.example:443", "a.example:443"])
    run(world, made)
    (call,) = [c for c in calls(world) if c["verb"] == "run"]
    flags, cfg = call["flags"], ctx_of(world)["cfg"]
    assert flags["--kind"] == "py" and flags["--timeout"] == str(kind.SCRIPT_TIMEOUT) and "--image" not in flags
    assert call["destinations"] == ["a.example:443", "b.example:443"]
    assert flags["--script"].startswith(os.path.join(cfg["data_dir"], "sources-staging")) and str(world["project"]) not in flags["--script"]
    assert not os.path.exists(os.path.dirname(os.path.dirname(flags["--script"])))      # the staging folder is removed afterwards


def test_a_shell_script_runs_with_the_kind_sh(world):
    made = add(world, script="scripts/run.sh", text="# fake: md=From a shell script\n", source="shelled")
    assert run(world, made)["ok"] is True
    assert [c["flags"]["--kind"] for c in calls(world)] == ["sh"]


def test_the_same_output_again_makes_no_version_and_a_new_output_makes_the_next(world):
    first = add(world)
    run(world, first)
    again = add(world, key="again")
    out = run(world, again)
    assert out["ok"] is True and task(world, again["task"])["step_state"]["steps"]["run"]["result"]["unchanged"] is True
    changed = add(world, text="# fake: md=A different result\n", key="changed")
    run(world, changed)
    ctx = ctx_of(world)
    assert ctx["store"].source_latest(ctx["conn"], "report")["version"] == 2


def test_a_csv_result_goes_the_normal_way_through_the_converter(world):
    made = add(world, text="# fake: csv=name,price|apple,1.2\n", source="prices")
    assert run(world, made)["ok"] is True
    ctx = ctx_of(world)
    assert ctx["store"].source_latest(ctx["conn"], "prices")["converted_name"] == "converted.csv"


def test_a_changed_script_stops_the_step_before_anything_is_staged_and_nothing_runs(world):
    made = add(world)
    (world["project"] / "scripts" / "report.py").write_text("# fake: md=Not the approved script\n")
    out = run(world, made)
    assert out["ok"] is False and out["failed"] == "verify" and out["code"] == "script_changed" and out["task_state"] == "failed"
    assert "plan the step again" in out["next"] and "prepare" in out["next"]
    assert calls(world) == []                                         # the provider was never started
    ctx = ctx_of(world)
    assert ctx["store"].source_latest(ctx["conn"], "report") is None and not (Path(ctx["cfg"]["data_dir"]) / "sources-staging").exists() or \
        not list((Path(ctx["cfg"]["data_dir"]) / "sources-staging").iterdir())
    # a retry reads the file again and stops again; restoring the approved bytes lets it run
    assert ctx["store"].task_retry(ctx["conn"], made["task"])["state"] == "ready"
    assert run(world, made)["code"] == "script_changed"
    (world["project"] / "scripts" / "report.py").write_text("# fake: md=Hello from the script\n")
    ctx["store"].task_retry(ctx["conn"], made["task"])
    assert run(world, made)["ok"] is True


def test_a_script_changed_after_the_verify_step_is_still_stopped_by_the_run_step(world, monkeypatch):
    made = add(world)
    original = kind.KIND.executors["verify"]

    def swap(ctx, state):
        done = original(ctx, state)
        (world["project"] / "scripts" / "report.py").write_text("# fake: md=Swapped after the check\n")
        return done

    monkeypatch.setitem(kind.KIND.executors, "verify", swap)
    out = run(world, made)
    assert out["failed"] == "run" and out["code"] == "script_changed"
    assert [c for c in calls(world) if c["verb"] == "run"] == []


def test_a_script_with_a_credential_in_it_does_not_run_even_with_its_hash_in_the_plan(world):
    secret = key_text()
    made = add(world, text=f"# fake: md=Hi\nKEY = '{secret}'\n")
    out = run(world, made)
    assert out["ok"] is False and out["failed"] == "verify" and out["code"] == "script_has_credential" and out["field"] == "line_2"
    assert secret not in json.dumps(out) and secret not in task(world, made["task"])["note"] and calls(world) == []


def test_a_lock_file_is_built_once_by_the_provider_and_the_run_uses_its_image(world):
    lock = "requests==2.32.3 --hash=sha256:" + "a" * 64 + "\n"
    made = add(world, lock="scripts/requirements.lock", lock_text=lock)
    out = run(world, made)
    assert out["ok"] is True and out["steps"]["deps"] == "done"
    deps, running = calls(world)
    assert deps["verb"] == "deps" and deps["flags"]["--lock-sha256"] == hashlib.sha256(lock.encode()).hexdigest()
    assert deps["flags"]["--lock"].startswith(os.path.join(ctx_of(world)["cfg"]["data_dir"], "sources-staging"))
    assert running["verb"] == "run" and running["flags"]["--image"] == "sha256:" + "d" * 64
    assert task(world, made["task"])["step_state"]["steps"]["deps"]["result"] == {"deps": "built", "image": "sha256:" + "d" * 64}


def test_a_changed_lock_file_stops_the_step_and_nothing_is_built(world):
    lock = "requests==2.32.3 --hash=sha256:" + "a" * 64 + "\n"
    made = add(world, lock="scripts/requirements.lock", lock_text=lock)
    (world["project"] / "scripts" / "requirements.lock").write_text("evil==1.0 --hash=sha256:" + "c" * 64 + "\n")
    out = run(world, made)
    assert out["failed"] == "verify" and out["code"] == "lock_changed" and calls(world) == []


@pytest.mark.parametrize("mode,code,field", [
    ("exit=3", "script_failed", "exit_3"), ("signal=9", "script_killed", "signal_9"), ("none", "no_result", "result"),
    ("two", "output_refused", "result"), ("extra", "output_refused", "result"), ("big", "output_too_large", "result")])
def test_what_a_script_does_wrong_is_a_closed_failure_with_no_text_of_the_script_in_it(world, mode, code, field):
    made = add(world, text=f"# fake: {mode}\n")
    out = run(world, made)
    assert out["ok"] is False and out["failed"] == "run" and out["code"] == code and out["field"] == field and out["task_state"] == "failed"
    ctx = ctx_of(world)
    assert ctx["store"].source_latest(ctx["conn"], "report") is None            # a refusal leaves no version
    assert ctx["store"].task_get(ctx["conn"], made["task"])["step_state"]["failure"]["code"] == code


def test_the_provider_process_has_the_minimum_environment_and_no_credential_of_this_process(world, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "planted-" + "a1" * 10)
    monkeypatch.setenv("NOTION_TOKEN", "planted-" + "b2" * 10)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "planted-" + "c3" * 10)
    made = add(world, text="# fake: env\n", source="envs")
    assert run(world, made)["ok"] is True
    ctx = ctx_of(world)
    names = (Path(ctx["cfg"]["sources_dir"]) / "envs" / "1" / "converted.md").read_text()
    assert names.startswith("environment: ") and "PATH" in names
    for planted in ("OPENAI_API_KEY", "NOTION_TOKEN", "ANTHROPIC_API_KEY"):
        assert planted not in names


def test_a_result_source_of_another_type_is_refused_and_a_new_source_is_a_file_source(world):
    ctx = ctx_of(world)
    sources.register(ctx, "page", "notion", "0123456789abcdef0123456789abcdef")
    out = run(world, add(world, source="page"))
    assert out["failed"] == "run" and out["code"] == "source_type"
    run(world, add(world, source="fresh", key="fresh"))
    assert ctx["store"].source_get(ctx["conn"], "fresh")["type"] == "file"


def test_the_dispatcher_never_starts_this_kind_on_its_own_and_a_person_starts_it_with_run_step(world):
    made = add(world)
    ctx = ctx_of(world)
    assert ops_steps.unattended("project-script") is False and ops_steps.unattended("ingest") is True
    assert ops_steps.may_dispatch(ctx, task(world, made["task"])) is False
    assert ops_steps.held_reason(ctx, task(world, made["task"])) == dispatcher.BY_HAND
    held = ops.run_step(world["path"], made["task"], unattended=True)           # what the dispatcher's child does
    assert held["ran"] is None and held["held"] is True and held["reason"] == dispatcher.BY_HAND
    assert calls(world) == [] and task(world, made["task"])["state"] == "ready"
    assert run(world, made)["ok"] is True                                       # the person's own start runs it


def test_a_provider_that_cannot_start_is_a_closed_failure_with_the_word_the_provider_gave(world):
    made = add(world)
    (world["tree"] / "providers" / "script" / "container.py").write_text(
        "import sys\nsys.stderr.write('error: destination_not_public: the declared destinations were refused: refused not_public x.example')\nsys.exit(1)\n")
    out = run(world, made)
    assert out["failed"] == "run" and out["code"] == "destination_not_public"
    (world["tree"] / "providers" / "script" / "container.py").write_text("import sys\nsys.stderr.write('Traceback: boom')\nsys.exit(1)\n")
    ctx_of(world)["store"].task_retry(ctx_of(world)["conn"], made["task"])
    assert run(world, made)["code"] == "provider_failed"


def test_a_project_without_the_provider_folder_fails_cleanly(world):
    made = add(world)
    (world["tree"] / "providers" / "script" / "container.py").unlink()
    (world["tree"] / "providers" / "script").rmdir() if not list((world["tree"] / "providers" / "script").iterdir()) else None
    out = run(world, made)
    assert out["ok"] is False and out["code"] in ("provider_failed", "not_configured")


def test_a_workflow_task_after_a_project_script_receives_the_source_the_script_makes():
    flow_files = st.load("flow_files")
    flow = {"flow": "weekly", "tasks": [
        {"key": "script", "step": "project-script", "args": {"source": "figures"}},
        {"key": "report", "skill": "biz-market-analysis", "depends_on": ["script"]}]}
    assert flow_files.sources_of(flow, steps.sourcing_kinds()) == {"report": ["figures"]}
