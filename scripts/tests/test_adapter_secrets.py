"""Tests for the secrets the adapters register (the "secrets" list of adapters/<harness>/adapter.json)
and for what the resolver resolves once they are merged.

The core's registry (providers/secrets/resolver.py) names no adapter; the eval runner, the doctor and
the API adapter hand the manifests to the resolver. These tests pin the merged registry to what the
single registry held before the split, so the move changed where a secret is listed, never how it is
looked up.

Run: uv run --with pytest pytest scripts/tests/test_adapter_secrets.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RESOLVER = ROOT / "providers" / "secrets" / "resolver.py"
MANIFESTS = sorted((ROOT / "adapters").glob("*/adapter.json"))
SENTINEL = "zz-not-a-real-value-57"

# name: (aliases, store username, readers), as the one registry held them before the adapters took theirs.
BEFORE = {
    "VCS_GITHUB_TOKEN": (("GITHUB_TOKEN",), "github", ("providers/vcs/github.py", ".github/workflows/dependabot-alerts.yml")),
    # The token that opens a pull request got a name of its own on 2026-10-06 (WP-4.11 of the platform plan).
    "VCS_GITHUB_PR_TOKEN": ((), "github-pr", ("providers/vcs/github.py", "runtime/effects.py")),
    # The two tokens gained auth.py as a reader when its --check began to read through the resolver.
    "LINKEDIN_ACCESS_TOKEN": ((), "publisher-linkedin", ("providers/publisher/linkedin.py",
                                                         "providers/publisher/auth.py")),
    "LINKEDIN_CLIENT_ID": ((), "linkedin-client-id", ("providers/publisher/auth.py",)),
    "LINKEDIN_CLIENT_SECRET": ((), "linkedin-client-secret", ("providers/publisher/auth.py",)),
    "GMAIL_REFRESH_TOKEN": ((), "mailbox-gmail", ("providers/mailbox/gmail.py", "providers/mailbox/auth.py")),
    "GMAIL_CLIENT_ID": ((), "gmail-client-id", ("providers/mailbox/auth.py", "providers/mailbox/gmail.py")),
    "GMAIL_CLIENT_SECRET": ((), "gmail-client-secret", ("providers/mailbox/auth.py", "providers/mailbox/gmail.py")),
    # The platform's token joined the core registry on 2026-10-06 (stage 3 of the platform plan, WP-3.10).
    "NOTION_TOKEN": ((), "notion", ("providers/issue-tracker/notion.py", "providers/documents/notion.py")),
    "MESSENGER_TELEGRAM_BOT_TOKEN": ((), "messenger-telegram", ("providers/messenger/telegram.py",)),
    "MESSENGER_DISCORD_BOT_TOKEN": ((), "messenger-discord", ("providers/messenger/discord.py",)),
    # The key proxy of the eval network became a reader of the floor key on 2026-10-03: it holds the value of an eval run.
    "OPENROUTER_API_KEY": ((), "openrouter", ("evals/eval_run.py --pass-env", "adapters/agents-dir/run-prompt.sh",
                                              "evals/container/keyproxy/keyproxy.py", "adapters/api/run_agent.py")),
    "CLAUDE_CODE_OAUTH_TOKEN": ((), "claude-code-oauth", ("evals/eval_run.py strong_pass_env",
                                                          "adapters/claude-code/run-prompt.sh")),
    "DEEPSEEK_API_KEY": ((), "deepseek", ("evals/eval_run.py --floor-pass-env", "adapters/agents-dir/run-prompt.sh")),
    "ANTHROPIC_API_KEY": ((), "anthropic", ("adapters/api/run_agent.py",)),
    # Added since: the low-limit key of the eval cases that use the open network.
    "CLAUDE_CODE_WEB_API_KEY": ((), "claude-code-web-evals", ("evals/eval_run.py strong_web_pass_env",
                                                              "adapters/claude-code/run-prompt.sh")),
}
ADAPTER_SECRETS = {"OPENROUTER_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY",
                   "CLAUDE_CODE_WEB_API_KEY"}


class FakeStore:
    def __init__(self, values):
        self.values, self.asked = values, []

    def get_password(self, service, username):
        self.asked.append((service, username))
        return self.values.get(username)


def load(name="workbench_secret_resolver_adapters_test"):
    spec = importlib.util.spec_from_file_location(name, RESOLVER)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def merged():
    res = load()
    for manifest in MANIFESTS:
        res.register_file(manifest)
    return res


def test_the_core_alone_registers_no_adapter_secret():
    assert set(load().REGISTRY) == set(BEFORE) - ADAPTER_SECRETS


def test_the_merged_registry_is_the_registry_from_before_the_split(merged):
    now = {s.name: (s.aliases, s.store_username, s.readers) for s in merged.REGISTRY.values()}
    assert now == BEFORE


def test_every_secret_resolves_as_before(merged):
    for name, (aliases, username, _readers) in BEFORE.items():
        store = FakeStore({username: "from-store"})
        assert merged.resolve(name, environ={name: SENTINEL}, store=store) == (SENTINEL, f"environment ({name})")
        for alias in aliases:
            assert merged.resolve(name, environ={alias: SENTINEL}, store=store) == (SENTINEL, f"environment ({alias})")
        assert store.asked == []
        assert merged.resolve(name, environ={}, store=store) == ("from-store", "secret store")
        assert store.asked == [("openhora", username)]
        assert merged.resolve(name, allow_store=False, environ={}, store=store) is None


def test_every_adapter_secret_names_readers_that_exist_and_its_own_adapter():
    seen = set()
    for manifest in MANIFESTS:
        for entry in json.loads(manifest.read_text(encoding="utf-8")).get("secrets", []):
            seen.add(entry["name"])
            for reader in entry["readers"]:
                assert (ROOT / reader.split()[0]).exists(), reader
            own = f"adapters/{manifest.parent.name}/"
            assert any(r.startswith(own) for r in entry["readers"]), \
                f"{manifest.parent.name} registers {entry['name']} and never reads it"
    assert seen == ADAPTER_SECRETS


def test_the_names_passed_into_eval_runs_are_registered_by_the_adapter_of_their_tier(merged):
    """The gate file is the one home of the pass-through names; the registry only confirms them."""
    gate = json.loads((ROOT / "evals" / "eval-gate.json").read_text(encoding="utf-8"))
    for tier in ("floor", "strong"):
        manifest = json.loads((ROOT / "adapters" / gate[f"{tier}_harness"] / "adapter.json").read_text(encoding="utf-8"))
        registered = {entry["name"] for entry in manifest.get("secrets", [])}
        for name in gate[f"{tier}_pass_env"] + (gate.get("strong_web_pass_env", []) if tier == "strong" else []):
            assert name in registered, f"{name} is passed to the {tier} runs and its adapter does not register it"
            assert any(r.startswith("evals/eval_run.py") for r in merged.REGISTRY[name].readers)
    for manifest in MANIFESTS:
        keys = set(json.loads(manifest.read_text(encoding="utf-8")))
        assert not {k for k in keys if "pass_env" in k}, "an adapter's manifest holds no list of variables to pass"


def test_the_doctor_lists_core_and_adapter_secrets_without_a_value():
    env = {"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", "/tmp"), **{name: SENTINEL for name in BEFORE}}
    out = subprocess.run([sys.executable, str(ROOT / "scripts" / "doctor.py"), "--json"], capture_output=True, text=True,
                         env=env, timeout=120)
    assert out.returncode == 0, out.stderr
    assert SENTINEL not in out.stdout + out.stderr
    rows = {row["name"]: row for row in json.loads(out.stdout)["secrets"]}
    assert set(rows) == set(BEFORE) and all(row["found"] for row in rows.values())
