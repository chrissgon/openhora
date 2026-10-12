"""Tests for the secret resolver (no real secret store: a fake object stands in for keyring).

Run: uv run --with pytest pytest providers/secrets/tests
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "resolver.py"
ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("workbench_secret_resolver_test", SCRIPT)
res = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = res
spec.loader.exec_module(res)

SENTINEL = "zz-not-a-real-value-41"


class FakeStore:
    def __init__(self, values=None, fail=False):
        self.values, self.fail, self.asked = values or {}, fail, []

    def get_password(self, service, username):
        self.asked.append((service, username))
        if self.fail:
            raise RuntimeError("locked")
        return self.values.get(username)


def test_environment_wins_then_aliases_then_store():
    store = FakeStore({"github": "from-store"})
    assert res.resolve("VCS_GITHUB_TOKEN", environ={"VCS_GITHUB_TOKEN": "a", "GITHUB_TOKEN": "b"}, store=store) \
        == ("a", "environment (VCS_GITHUB_TOKEN)")
    assert res.resolve("VCS_GITHUB_TOKEN", environ={"VCS_GITHUB_TOKEN": "  ", "GITHUB_TOKEN": "b"}, store=store) \
        == ("b", "environment (GITHUB_TOKEN)")
    assert store.asked == []
    assert res.resolve("VCS_GITHUB_TOKEN", environ={}, store=store) == ("from-store", "secret store")
    assert store.asked == [("openhora", "github")]


class ServiceStore:
    """A secret store that keeps its values per (service, username), as the real one does, and records each question."""

    def __init__(self, values=None, fail_for=()):
        self.values, self.fail_for, self.asked = values or {}, set(fail_for), []

    def get_password(self, service, username):
        self.asked.append((service, username))
        if service in self.fail_for:
            raise RuntimeError("locked")
        return self.values.get((service, username))


def test_the_service_is_openhora_and_the_legacy_service_is_the_old_name():
    assert res.SERVICE == "openhora" and res.LEGACY_SERVICE == "ai-workbench"


def test_a_secret_found_under_the_new_service_is_read_from_it_alone():
    store = ServiceStore({("openhora", "github"): "new-value"})
    assert res.resolve("VCS_GITHUB_TOKEN", environ={}, store=store) == ("new-value", "secret store")
    assert store.asked == [("openhora", "github")], "the old service is not asked when the new one answers"
    assert res.resolve_detail("VCS_GITHUB_TOKEN", environ={}, store=store) == ("new-value", "secret store", "openhora")


def test_a_secret_found_only_under_the_old_service_is_read_and_says_legacy():
    store = ServiceStore({("ai-workbench", "github"): "old-value"})
    assert res.resolve("VCS_GITHUB_TOKEN", environ={}, store=store) == ("old-value", "secret store")
    assert store.asked == [("openhora", "github"), ("ai-workbench", "github")]
    got = res.resolve_detail("VCS_GITHUB_TOKEN", environ={}, store=store)
    assert got == ("old-value", "secret store", "ai-workbench (legacy)")


def test_the_new_service_wins_when_both_hold_the_secret():
    store = ServiceStore({("openhora", "github"): "new-value", ("ai-workbench", "github"): "old-value"})
    assert res.resolve("VCS_GITHUB_TOKEN", environ={}, store=store)[0] == "new-value"
    assert ("ai-workbench", "github") not in store.asked


def test_a_value_that_is_blank_under_the_new_service_falls_to_the_old_one():
    store = ServiceStore({("openhora", "github"): "   ", ("ai-workbench", "github"): "old-value"})
    assert res.resolve_detail("VCS_GITHUB_TOKEN", environ={}, store=store)[2] == "ai-workbench (legacy)"


def test_a_locked_new_service_still_lets_the_old_one_answer_and_a_locked_store_is_not_found():
    store = ServiceStore({("ai-workbench", "github"): "old-value"}, fail_for={"openhora"})
    assert res.resolve("VCS_GITHUB_TOKEN", environ={}, store=store)[0] == "old-value"
    locked = ServiceStore({("ai-workbench", "github"): "old-value"}, fail_for={"openhora", "ai-workbench"})
    assert res.resolve("VCS_GITHUB_TOKEN", environ={}, store=locked) is None
    assert res.resolve_detail("VCS_GITHUB_TOKEN", environ={}, store=ServiceStore()) is None


def test_the_environment_answer_has_no_service():
    store = ServiceStore({("openhora", "github"): "new-value"})
    assert res.resolve_detail("VCS_GITHUB_TOKEN", environ={"VCS_GITHUB_TOKEN": "env"}, store=store) \
        == ("env", "environment (VCS_GITHUB_TOKEN)", None)
    assert store.asked == []


def test_report_says_which_service_answered_and_never_carries_a_value():
    store = ServiceStore({("ai-workbench", "github"): SENTINEL, ("openhora", "notion"): SENTINEL})
    rows = {r["name"]: r for r in res.report(environ={"GMAIL_CLIENT_ID": SENTINEL}, store=store)}
    assert rows["VCS_GITHUB_TOKEN"]["found"] and rows["VCS_GITHUB_TOKEN"]["service"] == "ai-workbench (legacy)"
    assert rows["NOTION_TOKEN"]["found"] and rows["NOTION_TOKEN"]["service"] == "openhora"
    assert rows["GMAIL_CLIENT_ID"]["found"] and rows["GMAIL_CLIENT_ID"]["service"] is None
    assert rows["LINKEDIN_CLIENT_ID"]["found"] is False and rows["LINKEDIN_CLIENT_ID"]["service"] is None
    assert SENTINEL not in json.dumps(list(rows.values()))


def test_cli_check_and_list_name_the_legacy_service(monkeypatch, capsys):
    store = ServiceStore({("ai-workbench", "github"): SENTINEL, ("openhora", "notion"): SENTINEL})
    monkeypatch.setattr(res, "_keyring", lambda: store)
    monkeypatch.setattr(res, "REGISTRY", dict(res.REGISTRY))
    for name in res.REGISTRY:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert res.main(["--check", "VCS_GITHUB_TOKEN"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out == {"name": "VCS_GITHUB_TOKEN", "found": True, "source": "secret store", "service": "ai-workbench (legacy)"}
    assert res.main(["--check", "NOTION_TOKEN"]) == 0
    assert json.loads(capsys.readouterr().out)["service"] == "openhora"
    assert res.main(["--list", "--json"]) == 0
    listed = {r["name"]: r for r in json.loads(capsys.readouterr().out)}
    assert listed["VCS_GITHUB_TOKEN"]["service"] == "ai-workbench (legacy)" and listed["NOTION_TOKEN"]["service"] == "openhora"
    assert res.main(["--list"]) == 0
    text = capsys.readouterr().out
    assert "ai-workbench (legacy)" in text and SENTINEL not in text


def test_the_command_that_stores_a_secret_names_the_new_service_only():
    assert res.how_to_set(res.REGISTRY["NOTION_TOKEN"]).endswith("keyring set openhora notion")
    assert "ai-workbench" not in res.how_to_set(res.REGISTRY["VCS_GITHUB_TOKEN"])
    assert "keyring set openhora <username>" in res.__doc__ and "keyring set ai-workbench" not in res.__doc__


def test_store_is_skipped_when_not_allowed_or_unavailable():
    store = FakeStore({"gmail-client-id": "x"})
    assert res.resolve("GMAIL_CLIENT_ID", allow_store=False, environ={}, store=store) is None
    assert store.asked == []
    assert res.resolve("GMAIL_CLIENT_ID", environ={}, store=None) is None
    assert res.resolve("GMAIL_CLIENT_ID", environ={}, store=FakeStore(fail=True)) is None


def test_unregistered_names_are_refused():
    with pytest.raises(res.NotRegistered):
        res.resolve("HOME", environ={"HOME": "/root"})


def test_report_never_carries_a_value():
    env = {name: SENTINEL for name in res.REGISTRY}
    rows = res.report(environ=env, store=None)
    assert {r["name"] for r in rows} == set(res.REGISTRY)
    assert all(r["found"] for r in rows)
    assert SENTINEL not in json.dumps(rows)


def run(*args, env=None):
    base = {"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", "/tmp")}
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True,
                          env={**base, **(env or {})}, timeout=60)


def test_cli_check_and_list_print_no_value():
    found = run("--check", "GMAIL_CLIENT_ID", env={"GMAIL_CLIENT_ID": SENTINEL})
    assert found.returncode == 0 and SENTINEL not in found.stdout + found.stderr
    assert json.loads(found.stdout)["source"] == "environment (GMAIL_CLIENT_ID)"
    listed = run("--list", env={name: SENTINEL for name in res.REGISTRY})
    assert listed.returncode == 0 and SENTINEL not in listed.stdout + listed.stderr
    assert run("--check", "NOT_A_SECRET").returncode == 2
    assert run("--bogus").returncode == 2


def table_cells(secret):
    """The row contracts/secrets.md must carry for a registry entry, cell by cell."""
    def tick(items):
        return ", ".join(f"`{x}`" for x in items) or "none"
    return [f"`{secret.name}`", tick(secret.aliases), secret.purpose, secret.permission, tick(secret.readers),
            f"`{secret.store_username}`" if secret.store_username else "none",
            secret.set_local or "`keyring set`", secret.note or "none"]


def contract_table():
    """The rows of the table under "## Registry" in contracts/secrets.md, as lists of cells."""
    text = (ROOT / "contracts" / "secrets.md").read_text(encoding="utf-8")
    section = text.split("\n## Registry\n", 1)[1].split("\n## ", 1)[0]
    lines = [line for line in section.splitlines() if line.startswith("|")]
    return [[cell.strip() for cell in line.strip().strip("|").split("|")] for line in lines]


def test_every_reader_exists():
    for secret in res.REGISTRY.values():
        for reader in secret.readers:
            assert (ROOT / reader.split()[0]).exists(), reader


def test_the_contract_table_equals_the_registry_cell_by_cell():
    header, rule, *rows = contract_table()
    assert len(header) == 8 and set("".join(rule)) == {"-"}
    assert [row[0] for row in rows] == [f"`{name}`" for name in res.REGISTRY], "one row per secret, in the registry's order"
    for row, secret in zip(rows, res.REGISTRY.values()):
        assert len(row) == len(header), secret.name
        for title, cell, expected in zip(header, row, table_cells(secret)):
            assert cell == expected, f"contracts/secrets.md, {secret.name}, column {title!r}"


def test_the_core_registry_names_no_adapter():
    """Principles 1 and 2: an adapter's secrets are registered by the adapter, never listed here."""
    for secret in res.REGISTRY.values():
        assert not any(reader.startswith(("adapters/", "evals/")) for reader in secret.readers), secret.name
    source = SCRIPT.read_text(encoding="utf-8")
    contract = (ROOT / "contracts" / "secrets.md").read_text(encoding="utf-8")
    for text in (source, contract):
        assert not [line for line in text.splitlines() if "adapters/" in line and "adapters/<harness>/" not in line]


@pytest.fixture
def registry(monkeypatch):
    """A copy of the registry that a test may merge into."""
    monkeypatch.setattr(res, "REGISTRY", dict(res.REGISTRY))
    return res.REGISTRY


DEMO = {"name": "DEMO_MODEL_KEY", "purpose": "a demo key", "permission": "none", "readers": ["a/reader.sh"],
        "store_username": "demo"}


def test_register_merges_entries_given_from_outside(registry):
    core = dict(registry)
    assert res.register([DEMO], origin="demo") == ["DEMO_MODEL_KEY"]
    assert {k: registry[k] for k in core} == core, "what the core registers is untouched"
    store = FakeStore({"demo": "from-store"})
    assert res.resolve("DEMO_MODEL_KEY", environ={"DEMO_MODEL_KEY": "e"}, store=store) == ("e", "environment (DEMO_MODEL_KEY)")
    assert res.resolve("DEMO_MODEL_KEY", environ={}, store=store) == ("from-store", "secret store")
    assert "DEMO_MODEL_KEY" in {row["name"] for row in res.report(environ={}, store=None)}


def test_a_name_registered_twice_joins_its_readers_and_must_agree_on_the_lookup(registry):
    res.register([DEMO, {**DEMO, "purpose": "said again", "readers": ["b/reader.py", "a/reader.sh"]}])
    assert registry["DEMO_MODEL_KEY"].readers == ("a/reader.sh", "b/reader.py")
    assert registry["DEMO_MODEL_KEY"].purpose == "a demo key"
    with pytest.raises(ValueError, match="already registered"):
        res.register([{**DEMO, "store_username": "elsewhere"}])
    with pytest.raises(ValueError, match="already registered"):
        res.register([{**DEMO, "name": "GMAIL_CLIENT_ID"}])  # a core secret cannot be pointed at another store entry
    assert registry["GMAIL_CLIENT_ID"].store_username == "gmail-client-id"


@pytest.mark.parametrize("entries", [
    "not a list", ["not an object"], [{"name": "X_KEY"}], [{**DEMO, "extra": 1}], [{**DEMO, "name": "lower_case"}],
    [{**DEMO, "name": "1_KEY"}], [{**DEMO, "readers": "a/reader.sh"}], [{**DEMO, "aliases": [3]}], [{**DEMO, "note": 3}],
])
def test_a_malformed_registry_is_refused_whole(registry, entries):
    before = dict(registry)
    with pytest.raises(ValueError):
        res.register([{**DEMO, "name": "GOOD_KEY"}] + entries if isinstance(entries, list) else entries)
    assert registry == before, "nothing is merged from a registry with a bad entry"


def test_register_file_reads_the_secrets_list_of_a_manifest(registry, tmp_path):
    manifest = tmp_path / "adapter.json"
    manifest.write_text(json.dumps({"harness": "demo", "secrets": [DEMO]}), encoding="utf-8")
    assert res.register_file(manifest) == ["DEMO_MODEL_KEY"]
    (tmp_path / "none.json").write_text(json.dumps({"harness": "demo"}), encoding="utf-8")
    assert res.register_file(tmp_path / "none.json") == []
    (tmp_path / "broken.json").write_text("{", encoding="utf-8")
    for bad in (tmp_path / "broken.json", tmp_path / "absent.json"):
        with pytest.raises(ValueError, match="cannot be read"):
            res.register_file(bad)


def test_cli_registry_flag_merges_before_list_and_check(tmp_path):
    manifest = tmp_path / "adapter.json"
    manifest.write_text(json.dumps({"secrets": [DEMO]}), encoding="utf-8")
    assert run("--check", "DEMO_MODEL_KEY").returncode == 2, "not registered until a caller hands the file over"
    found = run("--registry", str(manifest), "--check", "DEMO_MODEL_KEY", env={"DEMO_MODEL_KEY": SENTINEL})
    assert found.returncode == 0 and SENTINEL not in found.stdout + found.stderr
    listed = run("--registry", str(manifest), "--list", "--json", env={"DEMO_MODEL_KEY": SENTINEL})
    assert listed.returncode == 0 and SENTINEL not in listed.stdout
    assert [r["name"] for r in json.loads(listed.stdout)][-1] == "DEMO_MODEL_KEY"
    assert run("--registry").returncode == 2
    assert run("--registry", str(manifest)).returncode == 2
    assert run("--registry", str(tmp_path / "absent.json"), "--list").returncode == 2


def test_the_pull_request_token_has_a_row_of_its_own_and_the_everyday_token_lost_that_permission():
    """WP-4.11 of the platform plan: open-pr reads VCS_GITHUB_PR_TOKEN (store username github-pr), and the
    everyday token's row no longer names the pull-request permission."""
    everyday, own = res.REGISTRY["VCS_GITHUB_TOKEN"], res.REGISTRY["VCS_GITHUB_PR_TOKEN"]
    assert own.store_username == "github-pr" and own.aliases == () and everyday.store_username == "github"
    assert "Pull requests: Read and write" in own.permission and "Pull requests" not in everyday.permission
    assert "pull request" not in everyday.purpose and own.purpose == "open a pull request (open-pr); nothing else"
    assert own.readers == ("providers/vcs/github.py", "runtime/effects.py")
    store = FakeStore({"github": "everyday", "github-pr": "own"})
    assert res.resolve("VCS_GITHUB_PR_TOKEN", environ={"VCS_GITHUB_TOKEN": "x", "GITHUB_TOKEN": "y"}, store=store) \
        == ("own", "secret store")
