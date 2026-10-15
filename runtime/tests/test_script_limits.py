"""The hard limits of a project script (L34 to L38 of contracts/runtime.md, package P9), one test each, named after the limit. Each test
is offline and reads the code that holds the limit: the commands the runner builds, the rules of the proxy, the checks of the step. The
same limits against real containers are in providers/script/tests/test_script_docker.py (opt-in, WB_SCRIPT_DOCKER_TESTS=1), which the
last assertion of each test names.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_script_limits.py
"""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

import script_fixture as fx
import standin_tree as st
from sources_fixture import standin_convert

REPO = Path(__file__).resolve().parents[2]
lab = st.load("lab")
ops = st.load("ops")
ops_core = st.load("ops_core")
ops_steps = st.load("ops_steps")
sources = st.load("sources")
steps = st.load("steps")
kind = st.load("step_project_script")


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


host = load("script_container_limits_test", "providers/script/container.py")
proxy = load("script_proxy_limits_test", "providers/script/egress_proxy.py")
IMAGE, NET, STEP_ID = "sha256:" + "1" * 64, "openhora-script-in-" + "0" * 16, "0" * 16


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


def add(world, text, **extra):
    ctx = ops_core.context(world["path"])
    args = {"script": "scripts/report.py", "sha256": fx.write(world["project"], "scripts/report.py", text), "source": "report", "destinations": [], **extra}
    return steps.add_task(ctx["store"], ctx["conn"], "project-script", args, key="report", title="Report", text="Run it.")


def options(command, name):
    return [command[i + 1] for i, w in enumerate(command) if w == name]


def test_limit_34_no_credential_reaches_a_project_script_its_environment_is_a_list_and_a_file_that_holds_one_is_refused_before_approval_and_again_before_it_runs(world, monkeypatch):
    # the environment of the container: only the pairs of ENV_ALLOWED, written as NAME=VALUE from the call's arguments, never this process's
    monkeypatch.setenv("OPENAI_API_KEY", "planted-" + "a1" * 10)
    monkeypatch.setenv("NOTION_TOKEN", "planted-" + "b2" * 10)
    command = host.run_command("openhora-script-run-" + STEP_ID, IMAGE, "py", "/work/script", deadline=5, network=NET,
                               env={"HTTPS_PROXY": "http://egress:3128"}, platform="darwin")
    assert "planted" not in " ".join(command) and options(command, "-e") == ["HTTPS_PROXY=http://egress:3128"]
    assert not [n for n in host.ENV_ALLOWED if any(w in n for w in ("KEY", "STEP_ID", "SECRET", "PASSWORD"))]
    with pytest.raises(host.ProviderError):
        host.env_args({"OPENAI_API_KEY": "x"})
    # the provider's own process: the resolver's minimum environment, no key (tested against the stand-in provider)
    assert "ENV_MINIMUM" in Path(REPO / "providers" / "resolve.py").read_text(encoding="utf-8")
    # before approval: prepare names the line and never prints the value
    secret = "AKIA" + "Q" * 16
    fx.write(world["project"], "scripts/leaky.py", f"# fake: md=Hi\nKEY = '{secret}'\n")
    with pytest.raises(steps.StepFailure) as refused:
        kind.prepare(world["path"], "scripts/leaky.py", "report")
    assert (refused.value.code, refused.value.field) == ("script_has_credential", "line_2") and secret not in str(refused.value) + refused.value.next
    # before it runs: a plan that names such a file by its hash still does not run it
    made = add(world, f"# fake: md=Hi\nKEY = '{secret}'\n")
    out = ops.run_step(world["path"], made["task"])
    assert out["code"] == "script_has_credential" and fx.calls(world["tree"]) == []
    # against a real container: test_script_docker.py::test_no_credential_of_the_calling_environment_is_inside_the_container


def test_limit_35_a_project_script_writes_only_through_the_import_of_a_source_its_footprint_is_empty_its_root_is_read_only_and_its_result_comes_back_as_frames(world):
    assert steps.footprint_of(steps.kind_of("project-script"), {}) == []
    command = host.run_command("openhora-script-run-" + STEP_ID, IMAGE, "py", "/work/script", deadline=5, platform="darwin")
    assert "--read-only" in command and options(command, "-v") == ["/work/script:/in/script:ro"]
    assert all(t.split(":", 1)[1].startswith("rw,noexec,nosuid,nodev") for t in options(command, "--tmpfs"))
    assert any("/scratch:rw" in t and "size=" in t for t in options(command, "--tmpfs"))        # the folder for the output is size-capped and in memory
    # the host takes names from a closed list, in a stream, under the cap
    with pytest.raises(host.ProviderError):
        host.parse_frames(b"OHF1\nFILE script.py 1\nxFILE info.json 2\n{}END\n")
    assert set(host.OUTPUT_NAMES) == {"result.md", "result.csv", "result.txt", "info.json"} == set(kind.OUTPUT_NAMES)
    # what comes back is read with the rules of L24 and becomes a version through import_version (nothing else writes the folder)
    folder = world["tmp"] if "tmp" in world else Path(ops_core.context(world["path"])["cfg"]["data_dir"]) / "out-folder"
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    (folder / "result.md").symlink_to("/etc/hosts")
    with pytest.raises(sources.SourcesError):
        sources.collect_outputs(str(folder), names=kind.OUTPUT_NAMES, entries_max=kind.OUTPUT_ENTRIES_MAX, who="script")
    text = Path(REPO / "runtime" / "step_project_script.py").read_text(encoding="utf-8")
    tree = ast.parse(text)
    writers = [fn.name for fn in ast.walk(tree) if isinstance(fn, ast.FunctionDef) and "O_WRONLY" in (ast.get_source_segment(text, fn) or "")]
    assert writers == ["stage"], "the one function that writes a file is the staging of the checked bytes, in the runtime's private folder"
    assert "sources.import_version(" in text
    assert not any(w in text for w in ("os.rename(", "os.replace(", "os.symlink(", "write_file(", ".write_text(", ".write_bytes(", "shutil.copy"))
    made = add(world, "# fake: md=Written by the script\n")
    assert ops.run_step(world["path"], made["task"])["ok"] is True
    ctx = ops_core.context(world["path"])
    assert ctx["store"].source_latest(ctx["conn"], "report")["version"] == 1
    assert sorted(p.relative_to(world["project"]).as_posix() for p in world["project"].rglob("*") if p.is_file() and ".git/" not in p.as_posix()) \
        == ["AGENTS.md", "docs/workbench/runtime.json", "docs/workbench/state.md", "scripts/report.py"]          # nothing new in the project
    # against a real container: test_script_docker.py::test_the_root_is_read_only_the_user_is_not_root_and_no_capability_is_held


def test_limit_36_a_project_script_reaches_no_network_except_the_destinations_declared_and_approved_none_by_default_an_internal_network_and_a_proxy_that_refuses_by_name_and_by_address():
    default = host.run_command("openhora-script-run-" + STEP_ID, IMAGE, "py", "/work/script", deadline=5, platform="darwin")
    assert options(default, "--network") == ["none"]
    # declared destinations: the script is on the internal network of its step and on no other; the proxy is the only way out
    for bad in ("bridge", "host", "default", "container:x", ""):
        with pytest.raises(host.ProviderError):
            host.run_command("n", IMAGE, "py", "/w/s", deadline=5, network=bad)
    # the proxy: declared pairs, a frozen resolution of public addresses, CONNECT only
    frozen = proxy.freeze({("api.example", 443)}, resolver=lambda host_, port: ["8.8.8.8"])
    table = {"api.example:443": True, "8.8.8.8:443": True, "other.example:443": False, "api.example:80": False, "8.8.4.4:443": False,
             "127.0.0.1:443": False, "2130706433:443": False, "169.254.169.254:80": False, "[::1]:443": False}
    for authority, allowed in table.items():
        assert proxy.decide(authority, frozen)[0] is allowed, authority
    with pytest.raises(proxy.Refused):
        proxy.freeze({("api.example", 443)}, resolver=lambda host_, port: ["10.0.0.1"])
    # the declaration is part of the plan hash and is checked the same way by the kind and by the proxy
    base = {"script": "scripts/report.py", "sha256": "a" * 64, "source": "report"}
    one = steps.plan_task("project-script", {**base, "destinations": ["api.example:443"]}, key="k", title="T", text="X.")
    two = steps.plan_task("project-script", {**base, "destinations": ["api.example:444"]}, key="k", title="T", text="X.")
    assert one["args"]["destinations"] == ["api.example:443"]
    assert hashlib.sha256(json.dumps([one], sort_keys=True).encode()).hexdigest() != hashlib.sha256(json.dumps([two], sort_keys=True).encode()).hexdigest()
    # against real networks: test_script_docker.py::test_the_proxy_serves_a_declared_name_and_refuses_every_other_way_in and
    # ::test_an_undeclared_name_cannot_be_resolved_from_the_script_container_and_there_is_no_way_out_but_the_proxy


def test_limit_37_a_changed_script_never_runs_and_the_kind_is_never_started_by_the_dispatcher(world):
    made = add(world, "# fake: md=The approved script\n")
    (world["project"] / "scripts" / "report.py").write_text("# fake: md=Another script\n")
    out = ops.run_step(world["path"], made["task"])
    assert out["code"] == "script_changed" and out["failed"] == "verify" and fx.calls(world["tree"]) == []
    assert steps.kind_of("project-script").unattended is False
    ctx = ops_core.context(world["path"])
    task = ctx["store"].task_get(ctx["conn"], made["task"])
    assert ops_steps.may_dispatch(ctx, task) is False and ops_steps.unattended("project-script") is False
    # the bytes mounted are the bytes hashed: the staged copy is written from the hashed bytes, not copied from the project again
    text = Path(REPO / "runtime" / "step_project_script.py").read_text(encoding="utf-8")
    tree = ast.parse(text)
    names = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert "files.script" in ast.get_source_segment(text, names["stage"]) and "shutil.copy" not in text and "os.link" not in text
    # the provider is handed the staged copy, never the project's path (tested in test_step_project_script.py)


def test_limit_38_a_dependency_build_has_no_mount_installs_only_what_a_hashed_lock_names_and_only_its_image_layer_reaches_a_run():
    command = host.build_command("openhora-script-build-" + STEP_ID, IMAGE, deadline=5, network=NET, env={"HTTPS_PROXY": "http://egress:3128"}, platform="darwin")
    for word in ("-v", "--volume", "--mount", "--volumes-from"):
        assert word not in command
    assert "-i" in command and options(command, "--network") == [NET] and options(command, "--cap-drop") == ["ALL"]
    inner = load("script_inner_limits_test", "providers/script/_inner.py")
    for text in ("requests>=2\n", "--index-url https://x.example/simple\n", "requests==2\n", "-r other.txt\n", "pkg @ https://x.example/p.whl\n"):
        with pytest.raises(ValueError):
            inner.check_lock(text)
    source = Path(REPO / "providers" / "script" / "_inner.py").read_text(encoding="utf-8")
    for flag in ("--require-hashes", "--only-binary=:all:", "--no-deps"):
        assert flag in source
    assert host.PACKAGE_INDEX == ("pypi.org:443", "files.pythonhosted.org:443")
    assert host.deps_tag("a" * 64).startswith("openhora-script-deps:" + "a" * 16)               # cached by the lock's sha256
    # a run receives an image only when this provider built it for a lock (its label), and reads it with a read-only root
    run = host.run_command("n", "sha256:" + "2" * 64, "py", "/w/s", deadline=5, platform="darwin")
    assert "--read-only" in run
    # against real containers: test_script_docker.py::test_the_build_container_runs_with_no_mount_gets_the_lock_on_standard_input_and_keeps_nothing_when_it_fails
