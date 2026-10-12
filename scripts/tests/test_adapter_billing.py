"""Tests of the billing an adapter declares for each credential (package ADJ-R3, row A-38): the "billing" key of every entry of
the "secrets" list of adapters/<harness>/adapter.json and the "login_billing" key of a harness that holds a login itself.
The validator requires them (an error, not a warning), the secret resolver accepts them, and the manifests of this checkout
carry the values the contract states. Offline; invented names.

Run: uv run --with pytest pytest scripts/tests/test_adapter_billing.py
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


validate = load("validate_for_adapter_billing", "scripts/validate.py")
resolver = load("resolver_for_adapter_billing", "providers/secrets/resolver.py")
MANIFESTS = sorted((ROOT / "adapters").glob("*/adapter.json"))
WORDS = ("subscription", "metered", "free")


def entry(name="EXAMPLE_KEY", **extra):
    return {"name": name, "purpose": "invented", "permission": "invented", "readers": ["adapters/h/run.sh"], **extra}


def tree(tmp_path, manifests):
    """manifests: {harness: the manifest's data}."""
    for harness, data in manifests.items():
        (tmp_path / "adapters" / harness).mkdir(parents=True, exist_ok=True)
        (tmp_path / "adapters" / harness / "adapter.json").write_text(json.dumps(data), encoding="utf-8")
    return tmp_path


def check(tmp_path, manifests):
    report = validate.Report()
    validate.check_adapter_manifests(report, root=str(tree(tmp_path, manifests)))
    return report


# --- the validator -------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("word", WORDS)
def test_an_entry_with_one_of_the_three_words_is_accepted(tmp_path, word):
    report = check(tmp_path, {"h": {"harness": "h", "secrets": [entry(billing=word)]}})
    assert report.errors == [] and report.warnings == []


def test_an_entry_without_billing_is_an_error_naming_the_manifest_and_the_secret(tmp_path):
    report = check(tmp_path, {"h": {"harness": "h", "secrets": [entry("EXAMPLE_NO_BILLING"), entry("EXAMPLE_OK", billing="metered")]}})
    assert len(report.errors) == 1 and report.warnings == []
    assert "adapters/h/adapter.json" in report.errors[0]["where"]
    assert "EXAMPLE_NO_BILLING" in report.errors[0]["message"] and "billing" in report.errors[0]["message"]
    assert "EXAMPLE_OK" not in report.errors[0]["message"]


@pytest.mark.parametrize("bad", ["prepaid", "", "Metered", None, 3, ["metered"]])
def test_an_entry_with_a_word_outside_the_three_is_an_error(tmp_path, bad):
    report = check(tmp_path, {"h": {"harness": "h", "secrets": [entry(billing=bad)]}})
    assert len(report.errors) == 1 and "subscription, metered or free" in report.errors[0]["message"]


def test_login_billing_is_optional_but_must_be_one_of_the_three(tmp_path):
    assert check(tmp_path, {"h": {"harness": "h", "login_billing": "subscription", "secrets": []}}).errors == []
    assert check(tmp_path / "none", {"h": {"harness": "h", "secrets": []}}).errors == []
    bad = check(tmp_path / "bad", {"h": {"harness": "h", "login_billing": "prepaid", "secrets": []}})
    assert len(bad.errors) == 1 and "login_billing" in bad.errors[0]["message"]


def test_one_credential_listed_by_two_adapters_has_the_same_billing_in_both(tmp_path):
    agree = check(tmp_path / "a", {"one": {"secrets": [entry(billing="metered")]}, "two": {"secrets": [entry(billing="metered")]}})
    assert agree.errors == []
    differ = check(tmp_path / "b", {"one": {"secrets": [entry(billing="metered")]}, "two": {"secrets": [entry(billing="subscription")]}})
    assert len(differ.errors) == 1 and "EXAMPLE_KEY" in differ.errors[0]["message"] and "one" in differ.errors[0]["message"]


def test_a_manifest_that_is_not_json_or_lists_no_secrets_is_reported_only_when_it_is_broken(tmp_path):
    (tmp_path / "adapters" / "broken").mkdir(parents=True)
    (tmp_path / "adapters" / "broken" / "adapter.json").write_text("{nope", encoding="utf-8")
    report = check(tmp_path, {"plain": {"harness": "plain"}})
    assert len(report.errors) == 1 and "broken" in report.errors[0]["where"], "a manifest with no secrets has nothing to declare"


def test_a_tree_without_adapters_is_a_note_not_an_error(tmp_path):
    report = validate.Report()
    validate.check_adapter_manifests(report, root=str(tmp_path))
    assert report.errors == [] and report.warnings == []


def test_the_manifests_of_this_checkout_pass_the_check():
    report = validate.Report()
    validate.check_adapter_manifests(report, root=str(ROOT))
    assert report.errors == [] and report.warnings == []


# --- the values this checkout declares ---------------------------------------------------------------------------------------


def declared():
    out = {}
    for path in MANIFESTS:
        for secret in json.loads(path.read_text(encoding="utf-8")).get("secrets", []):
            out.setdefault(secret["name"], set()).add(secret["billing"])
    return out


def test_the_credentials_of_the_harnesses_carry_the_billing_the_contract_states():
    found = declared()
    assert found == {"CLAUDE_CODE_OAUTH_TOKEN": {"subscription"}, "CLAUDE_CODE_WEB_API_KEY": {"metered"},
                     "ANTHROPIC_API_KEY": {"metered"}, "OPENROUTER_API_KEY": {"metered"}, "DEEPSEEK_API_KEY": {"metered"}}


def test_the_harness_that_holds_a_login_declares_it_once_and_no_other_harness_does():
    logins = {p.parent.name: json.loads(p.read_text(encoding="utf-8")).get("login_billing") for p in MANIFESTS}
    assert logins == {"agents-dir": None, "api": None, "claude-code": "subscription"}


# --- the secret resolver ---------------------------------------------------------------------------------------------------------


def test_the_resolver_registers_an_entry_with_billing_and_joins_two_that_agree():
    names = resolver.register([entry("EXAMPLE_BILLED_A", billing="metered", store_username="example-a")], origin="one")
    assert names == ["EXAMPLE_BILLED_A"]
    resolver.register([entry("EXAMPLE_BILLED_A", billing="metered", store_username="example-a")], origin="two")
    with pytest.raises(ValueError):
        resolver.register([entry("EXAMPLE_BILLED_A", billing="subscription", store_username="example-a")], origin="three")
    with pytest.raises(ValueError):
        resolver.register([entry("EXAMPLE_BILLED_B", billing="prepaid")], origin="four")
    for path in MANIFESTS:
        assert resolver.register_file(path), path   # every manifest of the checkout registers
