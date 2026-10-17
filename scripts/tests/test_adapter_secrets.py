"""Tests for the secrets the adapters register (the "secrets" list of adapters/<harness>/adapter.json)
and for what the resolver resolves once they are merged.

The core's registry (providers/secrets/resolver.py) names no adapter; the eval runner, the doctor and
the API adapter hand the manifests to the resolver. These tests pin the merged registry to what the
single registry held before the split, so the move changed where a secret is listed, never how it is
looked up.

Run: uv run --with pytest pytest scripts/tests/test_adapter_secrets.py
"""
from __future__ import annotations

import atexit
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
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
    # G1 (SPEC-SECRETARY-INTEGRATIONS): the person's Google calendar as a source; one record of its own (token, client), two read scopes.
    "GOOGLE_CALENDAR_TOKEN": ((), "calendar-google", ("providers/calendar/google.py", "providers/calendar/google_auth.py")),
    # Decision D13 and secret S7 of the delegation plan (P4): the read-only token of the pages chosen as sources, never the one that writes.
    "NOTION_SOURCES_TOKEN": ((), "notion-sources", ("providers/documents/notion.py",)),
    # P7: the Google Drive files the person picked as sources; one record (token, client, Picker key), scope drive.file.
    "GDRIVE_SOURCES_TOKEN": ((), "gdrive-sources", ("providers/documents/gdrive.py", "providers/documents/gdrive_auth.py")),
    "MESSENGER_TELEGRAM_BOT_TOKEN": ((), "messenger-telegram", ("providers/messenger/telegram.py",)),
    "MESSENGER_DISCORD_BOT_TOKEN": ((), "messenger-discord", ("providers/messenger/discord.py",)),
    "MESSENGER_WHATSAPP_CLOUD_TOKEN": ((), "messenger-whatsapp-cloud", ("providers/messenger/whatsapp-cloud.py",)),
    "MESSENGER_WHATSAPP_CLOUD_APP_SECRET": ((), "messenger-whatsapp-cloud-app-secret", ("providers/messenger/whatsapp-cloud.py",)),
    "MESSENGER_WHATSAPP_CLOUD_VERIFY_TOKEN": ((), "messenger-whatsapp-cloud-verify-token", ("providers/messenger/whatsapp-cloud.py",)),
    "MESSENGER_WHATSAPP_TWILIO_API_KEY_SID": ((), "messenger-whatsapp-twilio-api-key-sid", ("providers/messenger/whatsapp-twilio.py",)),
    "MESSENGER_WHATSAPP_TWILIO_API_KEY_SECRET": ((), "messenger-whatsapp-twilio-api-key-secret", ("providers/messenger/whatsapp-twilio.py",)),
    "MESSENGER_WHATSAPP_TWILIO_AUTH_TOKEN": ((), "messenger-whatsapp-twilio-auth-token", ("providers/messenger/whatsapp-twilio.py",)),
    # EMAIL-SEND: the password of the outbox account that sends the e-mails the person approved.
    "MAILER_SMTP_PASSWORD": ((), "mailer-smtp", ("providers/mailer/smtp.py",)),
    "MESSENGER_EMAIL_PASSWORD": ((), "messenger-email", ("providers/messenger/email-imap.py",)),
    # S16: the sign-in of the password manager (1Password), found only in the environment, the credentials directory or the OS store.
    "OP_SERVICE_ACCOUNT_TOKEN": ((), "password-manager-1password", ("providers/secrets/resolver.py",)),
    # The key proxy of the eval network became a reader of the floor key on 2026-10-03: it holds the value of an eval run.
    "OPENROUTER_API_KEY": ((), "openrouter", ("evals/eval_run.py --pass-env", "adapters/agents-dir/run-prompt.sh",
                                              "evals/container/keyproxy/keyproxy.py", "adapters/api/run_agent.py")),
    "CLAUDE_CODE_OAUTH_TOKEN": ((), "claude-code-oauth", ("evals/eval_run.py models[<id>].pass_env",
                                                          "adapters/claude-code/run-prompt.sh")),
    "DEEPSEEK_API_KEY": ((), "deepseek", ("evals/eval_run.py --pass-env", "adapters/agents-dir/run-prompt.sh")),
    "ANTHROPIC_API_KEY": ((), "anthropic", ("adapters/api/run_agent.py",)),
    # Added since: the low-limit key of the eval cases that use the open network.
    "CLAUDE_CODE_WEB_API_KEY": ((), "claude-code-web-evals", ("evals/eval_run.py models[<id>].web_pass_env",
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


def test_the_names_passed_into_eval_runs_are_registered_by_the_adapter_of_their_model(merged):
    """The gate file is the one home of the pass-through names (each model's entry); the registry only confirms them."""
    gate = json.loads((ROOT / "evals" / "eval-gate.json").read_text(encoding="utf-8"))
    for model, found in gate["models"].items():
        manifest = json.loads((ROOT / "adapters" / found["adapter"] / "adapter.json").read_text(encoding="utf-8"))
        registered = {entry["name"] for entry in manifest.get("secrets", [])}
        for name in found["pass_env"] + found.get("web_pass_env", []):
            assert name in registered, f"{name} is passed to the runs of {model} and its adapter does not register it"
            assert any(r.startswith("evals/eval_run.py") for r in merged.REGISTRY[name].readers)
    for manifest in MANIFESTS:
        keys = set(json.loads(manifest.read_text(encoding="utf-8")))
        assert not {k for k in keys if "pass_env" in k}, "an adapter's manifest holds no list of variables to pass"


EMPTY_HOME = tempfile.mkdtemp(prefix="wb-doctor-home-")   # a child gets an empty home and config folder, never the person's (S16)
atexit.register(shutil.rmtree, EMPTY_HOME, ignore_errors=True)


def child_env(**more):
    return {"PATH": os.environ["PATH"], "HOME": EMPTY_HOME, "XDG_CONFIG_HOME": EMPTY_HOME, **more}


def test_the_doctor_child_never_reaches_a_mapping_under_the_real_home(tmp_path, monkeypatch):
    """The reviewer's probe: a fake home with a 0600 mapping for several registered names, a recording FAKE `op` first on the PATH and
    XDG_CONFIG_HOME unset: the doctor started the way the test above starts it makes zero calls."""
    import importlib.util as util
    spec = util.spec_from_file_location("fake_op_for_adapter_secrets", ROOT / "providers" / "secrets" / "tests" / "fake_op.py")
    fake = util.module_from_spec(spec)
    sys.modules[spec.name] = fake
    spec.loader.exec_module(fake)
    op = fake.FakeOp(tmp_path / "bin")
    op.answer("*", stdout=SENTINEL)
    home = tmp_path / "home"
    (home / ".config" / "openhora").mkdir(parents=True)
    mapping = home / ".config" / "openhora" / "password-manager.json"
    names = ("VCS_GITHUB_TOKEN", "NOTION_TOKEN", "GMAIL_CLIENT_ID", "LINKEDIN_CLIENT_ID")
    mapping.write_text(json.dumps({"backend": "1password", "references": {n: "op://Example Vault/item/credential" for n in names}}),
                       encoding="utf-8")
    mapping.chmod(0o600)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("PATH", f"{op.folder}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    for name in BEFORE:
        monkeypatch.delenv(name, raising=False)
    out = subprocess.run([sys.executable, str(ROOT / "scripts" / "doctor.py"), "--json"], capture_output=True, text=True,
                         env=child_env(), timeout=180)
    assert out.returncode == 0 and SENTINEL not in out.stdout + out.stderr
    assert op.calls() == []


def test_the_doctor_lists_core_and_adapter_secrets_without_a_value():
    env = child_env(**{name: SENTINEL for name in BEFORE})
    out = subprocess.run([sys.executable, str(ROOT / "scripts" / "doctor.py"), "--json"], capture_output=True, text=True,
                         env=env, timeout=120)
    assert out.returncode == 0, out.stderr
    assert SENTINEL not in out.stdout + out.stderr
    rows = {row["name"]: row for row in json.loads(out.stdout)["secrets"]}
    assert set(rows) == set(BEFORE) and all(row["found"] for row in rows.values())
