"""Limit L39 (package S16): a password manager's tool is called only by the secret resolver, on the host, without a shell, never to sign in or
unlock, and never inside a run container. Fakes only: a FAKE `op` written into a temporary folder (providers/secrets/tests/fake_op.py), a
temporary mapping file, SENTINEL values; no real 1Password, no real secret. evals/executor.py is read and never changed.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_password_manager_limit.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

import standin_tree as st

REPO = st.REPO
SENTINEL = "zz-not-a-real-value-l39"
NAME = "VCS_GITHUB_TOKEN"
REF = "op://Example Vault/github-read/credential"


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


fake_op = load("fake_op_for_l39", "providers/secrets/tests/fake_op.py")
resolver = load("resolver_for_l39", "providers/secrets/resolver.py")
managers = resolver._managers()
executor = load("executor_for_l39", "evals/executor.py")


class World:
    def __init__(self, tmp_path):
        self.op = fake_op.FakeOp(tmp_path / "bin")
        self.op.answer(REF, stdout=SENTINEL)
        self.op.answer("whoami", stdout="signed in\n")
        config = tmp_path / "config" / "openhora"
        config.mkdir(parents=True)
        self.mapping = config / "password-manager.json"
        self.mapping.write_text(json.dumps({"backend": "1password", "references": {NAME: REF}}), encoding="utf-8")
        self.mapping.chmod(0o600)
        home = tmp_path / "home"
        home.mkdir()
        self.environ = {"PATH": f"{self.op.folder}{os.pathsep}/usr/bin{os.pathsep}/bin", "HOME": str(home),
                        "XDG_CONFIG_HOME": str(tmp_path / "config")}


class NoStore:
    @staticmethod
    def get_password(service, username):
        return None


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.delenv("WB_EVAL_CONTAINER", raising=False)
    return World(tmp_path)


def test_limit_39_password_manager_never_in_a_run(world, monkeypatch, tmp_path):
    # Outside a container the same lookup finds the value (the fake is reachable, so the next assertions are not vacuous).
    assert resolver.resolve_state(NAME, environ=world.environ, store=NoStore).state == "found"
    assert len(world.op.calls()) == 1
    before = len(world.op.calls())

    # Inside a container (the image sets WB_EVAL_CONTAINER=1): the lookup answers "unavailable" and calls nothing.
    monkeypatch.setenv("WB_EVAL_CONTAINER", "1")
    got = resolver.resolve_state(NAME, environ=world.environ, store=NoStore)
    assert got.state == "locked" and got.value == "" and resolver.store_failure() == "unavailable"
    assert "1Password" in got.detail and SENTINEL not in repr(got)
    assert resolver.probe_manager(world.environ)["state"] == "unavailable"
    # the same when only the environment the lookup was given says so
    monkeypatch.delenv("WB_EVAL_CONTAINER")
    inside = dict(world.environ, WB_EVAL_CONTAINER="1")
    assert resolver.resolve_state(NAME, environ=inside, store=NoStore).state == "locked"
    assert resolver.probe_manager(inside)["state"] == "unavailable"
    # and the backend itself, below the resolver, refuses to start the tool: the one place that spawns it
    backend = managers.BACKENDS["1password"]()
    monkeypatch.setenv("WB_EVAL_CONTAINER", "1")
    env = managers.minimum_environment(world.environ)
    assert backend.read(REF, env, 5).state == "unavailable" and backend.probe(env, 5).state == "unavailable"
    assert len(world.op.calls()) == before, "the fake recorded no call from a run"


def test_the_tool_is_started_without_a_shell_and_never_to_sign_in_or_unlock():
    text = (REPO / "providers" / "secrets" / "password_managers.py").read_text(encoding="utf-8")
    no_shell, with_shell = "shell=" + "False", "shell=" + "True"
    assert no_shell in text and with_shell not in text and "os.system" not in text and "os.popen" not in text
    assert "stdin=subprocess.DEVNULL" in text
    # the only verbs the module ever puts in an argument list are "read" and "whoami"
    verbs = {v for line in text.splitlines() if "self.argv(" in line for v in ("read", "whoami", "signin", "account", "add", "unlock") if f'"{v}"' in line}
    assert verbs == {"read", "whoami"}


def test_no_variable_of_the_password_manager_reaches_a_run_container(tmp_path):
    executor._NATIVE["platform"] = "linux/arm64"
    try:
        root = tmp_path / "eval-l39"
        (root / "case").mkdir(parents=True)
        (root / "out").mkdir()
        env = {"OP_SERVICE_ACCOUNT_TOKEN": SENTINEL, "OP_SESSION_demo": SENTINEL, "OP_CONNECT_TOKEN": SENTINEL, "OP_ACCOUNT": "example.1password.example"}
        argv, _ = executor.command(["true"], str(root), env=env)
    finally:
        executor._NATIVE.clear()
    assert SENTINEL not in " ".join(argv) and not any(a.startswith("OP_") or "OP_SERVICE_ACCOUNT_TOKEN" in a for a in argv)
    # nothing the harness is told to pass names one: the gate file's pass_env and the adapters' eval blocks
    gate = json.loads((REPO / "evals" / "eval-gate.json").read_text(encoding="utf-8"))
    named = [n for entry in gate["models"].values() for key in ("pass_env", "web_pass_env") for n in entry.get(key) or []]
    for manifest in sorted((REPO / "adapters").glob("*/eval.json")):
        block = json.loads(manifest.read_text(encoding="utf-8"))
        named += [n for n in (block.get("pass") or []) if isinstance(n, str)]
    assert not [n for n in named if n.startswith("OP_") or n == managers.OnePassword.token_name], named
    assert "OP_SERVICE_ACCOUNT_TOKEN" not in executor.FORWARD


def test_the_runners_contained_env_holds_no_variable_of_the_password_manager_even_when_passed(tmp_path, monkeypatch):
    kit = load("execution_for_l39", "evals/execution.py")
    names = ["OP_SERVICE_ACCOUNT_TOKEN", "OP_SESSION_demo", "OP_CONNECT_TOKEN", "OP_CONNECT_HOST"]
    for name in names:
        monkeypatch.setenv(name, SENTINEL)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    env = kit.contained_env(str(run_dir), pass_env=names)
    assert not [k for k in env if k.startswith("OP_")] and SENTINEL not in "".join(env.values())
    assert all(kit.token_var(n) for n in names)


def test_a_providers_process_gets_no_variable_of_the_password_manager():
    providers = load("providers_resolve_for_l39", "providers/resolve.py")
    env = {"PATH": "/bin", "OP_SERVICE_ACCOUNT_TOKEN": SENTINEL, "OP_SESSION_demo": SENTINEL, "OP_CONNECT_HOST": "x", "OP_ACCOUNT": "y"}
    assert providers.provider_environment("integration:vcs", env) == {"PATH": "/bin"}
