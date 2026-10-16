"""The password manager as the resolver's fourth place (package S16). A FAKE `op` (providers/secrets/tests/fake_op.py) stands in for the
vendor's tool and a fake store for the OS secret store: no real 1Password, no real keyring, no real secret. The value is SENTINEL.

Run: uv run --with pytest==9.1.1 pytest providers/secrets/tests/test_password_manager.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

from fake_op import FakeOp

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "resolver.py"
spec = importlib.util.spec_from_file_location("workbench_secret_resolver_pm_test", SCRIPT)
res = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = res
spec.loader.exec_module(res)
pm = res._managers()

SENTINEL = "zz-not-a-real-value-pm-31"
NAME = "VCS_GITHUB_TOKEN"
OTHER = "NOTION_TOKEN"
REF = "op://Example Vault/github-read/credential"
REF2 = "op://Example Vault/notion/section one/credential"
TOKEN = "OP_SERVICE_ACCOUNT_TOKEN"
KNOWN_EXTRA = {"__CF_USER_TEXT_ENCODING", "LC_CTYPE", "PYTHONCOERCECLOCALE", "PYTHONUTF8"}   # what the interpreter itself adds on some systems

NOT_SIGNED_IN = "[ERROR] 2026/10/15 10:00:00 You are not signed in. Please sign in to continue"
NO_ITEM = '[ERROR] 2026/10/15 10:00:00 "github-read" isn\'t an item in the "Example Vault" vault. Specify the item with its UUID, name, or domain.'


class KeyringLocked(Exception):
    pass


class FakeStore:
    def __init__(self, values=None, error=None):
        self.values, self.error, self.asked = values or {}, error, []

    def get_password(self, service, username):
        self.asked.append((service, username))
        if self.error is not None:
            raise self.error
        return self.values.get((service, username))


class World:
    """A temporary machine: the fake `op` on a PATH, a config folder, an empty home, and the environment dict a lookup is given."""

    def __init__(self, tmp_path):
        self.tmp = tmp_path
        self.op = FakeOp(tmp_path / "bin")
        self.cfg = tmp_path / "config"
        self.home = tmp_path / "home"
        self.home.mkdir()
        self.environ = {"PATH": f"{self.op.folder}{os.pathsep}/usr/bin{os.pathsep}/bin", "HOME": str(self.home),
                        "XDG_CONFIG_HOME": str(self.cfg), "LANG": "C.UTF-8", "USER": "demo"}

    @property
    def mapping(self):
        return self.cfg / "openhora" / "password-manager.json"

    def write_mapping(self, data=None, *, mode=0o600, text=None):
        self.mapping.parent.mkdir(parents=True, exist_ok=True)
        body = text if text is not None else json.dumps(data if data is not None else
                                                          {"backend": "1password", "references": {NAME: REF}})
        self.mapping.write_text(body, encoding="utf-8")
        self.mapping.chmod(mode)
        return self.mapping

    def lookup(self, name=NAME, *, store=None, **kw):
        return res.resolve_state(name, environ=self.environ, store=store if store is not None else FakeStore(), **kw)


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.delenv("WB_EVAL_CONTAINER", raising=False)
    monkeypatch.delenv("OPENHORA_CREDENTIALS_DIR", raising=False)
    monkeypatch.delenv("CREDENTIALS_DIRECTORY", raising=False)
    return World(tmp_path)


def signed_in(world, value=SENTINEL):
    world.op.answer(REF, stdout=value + "\n")
    world.op.answer(REF2, stdout=value + "\n")
    world.op.answer("whoami", stdout="URL: example-team.1password.example\n")


# --- the call ------------------------------------------------------------------------------------------------------------------------


def test_a_mapped_name_is_read_with_one_call_and_exactly_these_arguments(world):
    world.write_mapping()
    signed_in(world, "  " + SENTINEL + "  ")
    got = world.lookup()
    assert (got.state, got.value, got.source, got.backend) == ("found", SENTINEL, "password manager (1password)", "password-manager")
    [call] = world.op.calls()
    assert call["argv"][1:] == ["read", REF] and call["argv"][0].endswith("op")
    assert call["tty"] is False, "stdin is /dev/null: the tool cannot prompt on the terminal"
    assert REF not in repr(got) and "Example Vault" not in repr(got), "the reference is never put in the answer"


def test_the_account_follows_the_flag_and_only_when_it_is_set(world):
    world.write_mapping({"backend": "1password", "account": "example-team.1password.example", "references": {NAME: REF}})
    signed_in(world)
    assert world.lookup().state == "found"
    assert world.op.calls()[0]["argv"][1:] == ["read", REF, "--account", "example-team.1password.example"]


def test_the_call_gets_the_minimum_environment_and_no_token_unless_the_resolver_found_it(world):
    world.write_mapping()
    signed_in(world)
    world.environ.update({"ANTHROPIC_API_KEY": SENTINEL, "GITHUB_TOKEN_LIKE": SENTINEL, "OP_SESSION_demo": SENTINEL, "OP_CONNECT_TOKEN": SENTINEL,
                          "XDG_RUNTIME_DIR": "/run/user/1000", "LC_ALL": "C"})
    assert world.lookup().state == "found"
    env = world.op.calls()[0]["env"]
    assert set(env) <= set(pm.ENV_KEEP) | KNOWN_EXTRA, sorted(set(env) - set(pm.ENV_KEEP))
    assert SENTINEL not in json.dumps(env) and TOKEN not in env and "XDG_RUNTIME_DIR" in env


@pytest.mark.parametrize("where", ["environment", "credentials directory", "secret store"])
def test_the_service_account_token_is_passed_only_when_found_by_the_resolver_itself(world, where, tmp_path):
    world.write_mapping()
    signed_in(world)
    store = FakeStore()
    if where == "environment":
        world.environ[TOKEN] = "zz-token-sentinel"
    elif where == "credentials directory":
        folder = tmp_path / "creds"
        folder.mkdir(mode=0o700)
        file = folder / TOKEN
        file.write_text("zz-token-sentinel\n", encoding="utf-8")
        file.chmod(0o600)
        world.environ["OPENHORA_CREDENTIALS_DIR"] = str(folder)
    else:
        store = FakeStore({("openhora", "password-manager-1password"): "zz-token-sentinel"})
    assert world.lookup(store=store).state == "found"
    assert world.op.calls()[0]["env"][TOKEN] == "zz-token-sentinel"


def test_the_token_is_never_asked_of_the_manager_itself(world):
    world.write_mapping()
    signed_in(world)
    got = world.lookup(TOKEN)
    assert got.state == "missing" and world.op.calls() == []


# --- the states ----------------------------------------------------------------------------------------------------------------------


def test_the_item_or_field_that_does_not_exist_is_missing_with_the_fix(world):
    world.write_mapping()
    world.op.answer(REF, rc=1, stderr=NO_ITEM)
    got = world.lookup()
    assert got.state == "missing" and got.detail == f"check the reference of {NAME} in the mapping file"
    assert res.store_failure() is None and res.store_locked_note() == ""


def test_an_empty_value_is_missing_and_a_huge_one_is_refused(world):
    world.write_mapping()
    world.op.answer(REF, stdout="\n")
    assert world.lookup().state == "missing"
    world.op.answer(REF, stdout="x" * (pm.STDOUT_MAX + 1))
    got = world.lookup()
    assert got.state == "locked" and res.store_failure() == "unavailable"


def test_not_signed_in_is_locked_with_the_managers_sentence(world):
    world.write_mapping()
    world.op.answer(REF, rc=1, stderr=NOT_SIGNED_IN + " " + SENTINEL)
    got = world.lookup()
    assert got.state == "locked" and got.backend == "password-manager"
    assert "1Password" in got.detail and "unlock the app" in got.detail and TOKEN in got.detail
    assert res.store_failure() == "locked" and res.store_locked_note() == got.detail
    assert SENTINEL not in got.detail and "signed in. Please" not in got.detail, "the tool's text is dropped"


def test_a_prompt_left_unanswered_is_locked(world):
    world.write_mapping({"backend": "1password", "timeout_seconds": 1, "references": {NAME: REF}})
    world.op.answer(REF, stdout=SENTINEL, sleep=4)
    got = world.lookup()
    assert got.state == "locked" and res.store_failure() == "locked"


def test_a_tool_that_is_not_installed_is_unavailable_never_missing(world):
    world.write_mapping()
    world.environ["PATH"] = str(world.tmp / "empty-bin")
    got = world.lookup()
    assert got.state == "locked" and res.store_failure() == "unavailable" and "not installed or not on the PATH" in got.detail


def test_an_error_the_markers_do_not_recognise_is_never_missing(world):
    world.write_mapping()
    for text in ("[ERROR] something nobody has seen before", "", "[ERROR] network is unreachable"):
        world.op.answer(REF, rc=1, stderr=text)
        got = world.lookup()
        assert got.state == "locked" and res.store_failure() == "unavailable", text


def test_the_classifier_reads_the_markers_and_nothing_else():
    backend = pm.OnePassword()
    assert backend.classify(1, NO_ITEM.encode()) == "missing"
    assert backend.classify(1, NOT_SIGNED_IN.encode()) == "locked"
    assert backend.classify(1, b"authorization prompt dismissed, please try again") == "locked"
    assert backend.classify(1, b"") == "unavailable" and backend.classify(1, b"[ERROR] boom") == "unavailable"


# --- the order -----------------------------------------------------------------------------------------------------------------------


def test_the_environment_the_credentials_directory_and_the_store_each_win_and_the_manager_is_not_called(world, tmp_path):
    world.write_mapping()
    signed_in(world, "from-the-manager")
    world.environ[NAME] = "from-env"
    assert world.lookup().value == "from-env"
    del world.environ[NAME]
    folder = tmp_path / "creds"
    folder.mkdir(mode=0o700)
    (folder / NAME).write_text("from-directory\n", encoding="utf-8")
    (folder / NAME).chmod(0o600)
    world.environ["OPENHORA_CREDENTIALS_DIR"] = str(folder)
    assert world.lookup().value == "from-directory"
    del world.environ["OPENHORA_CREDENTIALS_DIR"]
    got = world.lookup(store=FakeStore({("openhora", "github"): "from-store"}))
    assert (got.value, got.source) == ("from-store", "secret store")
    assert world.op.calls() == []


def test_a_locked_store_and_a_manager_that_finds_it_is_found(world):
    world.write_mapping()
    signed_in(world)
    got = world.lookup(store=FakeStore(error=KeyringLocked("locked")))
    assert (got.state, got.value) == ("found", SENTINEL) and res.store_failure() is None


def test_an_empty_store_and_a_locked_manager_is_locked_with_the_managers_sentence(world):
    world.write_mapping()
    world.op.answer(REF, rc=1, stderr=NOT_SIGNED_IN)
    got = world.lookup()
    assert got.state == "locked" and got.detail.startswith("the password manager (1Password) is locked") and got.detail != res.LOCKED_SENTENCE


def test_when_both_fail_the_stores_sentence_comes_first(world):
    world.write_mapping()
    world.op.answer(REF, rc=1, stderr=NOT_SIGNED_IN)
    got = world.lookup(store=FakeStore(error=KeyringLocked("locked")))
    assert got.state == "locked" and got.detail == res.LOCKED_SENTENCE and res.store_locked_note() == res.LOCKED_SENTENCE
    # a locked store and a manager that says "no such item": the secret may be in the store, so the store's sentence stands
    world.op.answer(REF, rc=1, stderr=NO_ITEM)
    got = world.lookup(store=FakeStore(error=KeyringLocked("locked")))
    assert got.state == "locked" and got.detail == res.LOCKED_SENTENCE


def test_a_name_that_is_not_mapped_never_calls_the_tool(world):
    world.write_mapping()
    signed_in(world)
    assert world.lookup(OTHER).state == "missing" and world.op.calls() == []


def test_without_a_mapping_file_nothing_changes(world):
    signed_in(world)
    got = world.lookup()
    assert got.state == "missing" and got.detail == "" and got.backend is None and world.op.calls() == []
    assert world.lookup(allow_store=False).state == "missing"


def test_allow_store_false_asks_neither_the_store_nor_the_manager(world):
    world.write_mapping()
    signed_in(world)
    assert world.lookup(allow_store=False).state == "missing" and world.op.calls() == []


# --- the mapping file ----------------------------------------------------------------------------------------------------------------


def unsafe(world, what):
    signed_in(world)
    got = world.lookup()
    assert got.state == "unsafe", what
    assert world.op.calls() == [], what
    assert SENTINEL not in got.detail and res.store_locked_note() == got.detail, what
    return got.detail


def test_a_mapping_file_readable_by_others_is_unsafe_and_nothing_is_called(world):
    world.write_mapping(mode=0o644)
    assert "chmod 600" in unsafe(world, "0644")


def test_a_mapping_file_that_is_a_link_is_unsafe(world):
    real = world.tmp / "real.json"
    real.write_text(json.dumps({"backend": "1password", "references": {NAME: REF}}), encoding="utf-8")
    real.chmod(0o600)
    world.mapping.parent.mkdir(parents=True)
    world.mapping.symlink_to(real)
    assert "symbolic link" in unsafe(world, "link")


def test_a_mapping_file_that_is_not_a_regular_file_or_too_large_is_unsafe(world):
    world.mapping.parent.mkdir(parents=True)
    world.mapping.mkdir()
    assert "mapping" in unsafe(world, "directory")
    world.mapping.rmdir()
    world.write_mapping(text="{" + " " * (res.CREDENTIAL_MAX_BYTES + 10) + "}")
    assert "larger than" in unsafe(world, "large")


@pytest.mark.parametrize("data,why", [
    ("{not json", "not valid JSON"),
    ("[1, 2]", "one JSON object"),
    ({"backend": "1password", "references": {NAME: REF}, "extra": 1}, "unknown keys"),
    ({"backend": "bitwarden", "references": {NAME: REF}}, "backend this resolver does not have"),
    ({"references": {NAME: REF}}, "backend this resolver does not have"),
    ({"backend": "1password"}, "references"),
    ({"backend": "1password", "references": {}}, "references"),
    ({"backend": "1password", "references": {NAME: "https://example.test/x"}}, "does not start with op://"),
    ({"backend": "1password", "references": {NAME: "op://Vault/item"}}, "is not op://"),
    ({"backend": "1password", "references": {NAME: "op://Vault/item/field?attribute=otp"}}, "character"),
    ({"backend": "1password", "references": {NAME: "op://Vault/$APP_ENV/field"}}, "character"),
    ({"backend": "1password", "references": {NAME: "op://Vault//field"}}, "empty part"),
    ({"backend": "1password", "references": {NAME: "-op://Vault/item/field"}}, "does not start with op://"),
    ({"backend": "1password", "references": {NAME: "op://Vault/item/fi\neld"}}, "character"),
    ({"backend": "1password", "references": {NAME: 5}}, "reference"),
    ({"backend": "1password", "references": {"lowercase": REF}}, "capitals"),
    ({"backend": "1password", "references": {TOKEN: REF}}, "cannot be read through the manager"),
    ({"backend": "1password", "timeout_seconds": 0, "references": {NAME: REF}}, "timeout_seconds"),
    ({"backend": "1password", "timeout_seconds": 61, "references": {NAME: REF}}, "timeout_seconds"),
    ({"backend": "1password", "timeout_seconds": True, "references": {NAME: REF}}, "timeout_seconds"),
    ({"backend": "1password", "account": "-x", "references": {NAME: REF}}, "account"),
    ({"backend": "1password", "account": "", "references": {NAME: REF}}, "account"),
])
def test_a_mapping_that_cannot_be_parsed_or_is_not_valid_is_unsafe_with_its_reason(world, data, why):
    if isinstance(data, str):
        world.write_mapping(text=data)
    else:
        world.write_mapping(data)
    assert why in unsafe(world, str(data))


def test_the_mapping_file_is_found_under_xdg_else_under_the_home_folder(world):
    world.write_mapping()
    assert Path(res.mapping_path(world.environ)) == world.mapping
    del world.environ["XDG_CONFIG_HOME"]
    assert Path(res.mapping_path(world.environ)) == world.home / ".config" / "openhora" / "password-manager.json"
    assert res.mapping_path({"XDG_CONFIG_HOME": "relative/path"}) is None
    assert res.mapping_path({}) is None


def test_an_unsafe_mapping_does_not_hide_a_secret_found_earlier(world):
    world.write_mapping(mode=0o644)
    world.environ[NAME] = "from-env"
    assert world.lookup().state == "found"


# --- report, list, check -------------------------------------------------------------------------------------------------------------


def rows_by_name(world, store=None):
    return {r["name"]: r for r in res.report(environ=world.environ, store=store or FakeStore())}


def test_report_asks_a_failing_manager_once(world):
    world.write_mapping({"backend": "1password", "references": {NAME: REF, OTHER: REF2, "GMAIL_CLIENT_ID": REF2}})
    world.op.answer("*", rc=1, stderr=NOT_SIGNED_IN)
    rows = rows_by_name(world)
    assert len(world.op.calls()) == 1
    for name in (NAME, OTHER, "GMAIL_CLIENT_ID"):
        assert rows[name]["state"] == "locked" and rows[name]["detail"].startswith("the password manager (1Password) is locked"), name
    assert rows["LINKEDIN_CLIENT_ID"]["state"] == "missing", "a name that is not mapped is not touched by the manager's failure"


def test_report_marks_a_name_found_earlier_that_is_also_mapped_and_does_not_call(world):
    world.write_mapping({"backend": "1password", "references": {NAME: REF, OTHER: REF2}})
    signed_in(world)
    world.environ[NAME] = "from-env"
    rows = rows_by_name(world)
    assert rows[NAME]["found"] and rows[NAME]["also_mapped"] is True and rows[NAME]["backend"] is None
    assert rows[OTHER]["source"] == "password manager (1password)" and rows[OTHER]["also_mapped"] is False
    assert len(world.op.calls()) == 1


def test_list_and_check_say_where_and_never_the_value(world, monkeypatch, capsys):
    world.write_mapping({"backend": "1password", "references": {NAME: REF, OTHER: REF2}})
    world.op.answer(REF, stdout=SENTINEL)
    world.op.answer(REF2, rc=1, stderr=NO_ITEM + " " + SENTINEL)
    world.environ["GMAIL_CLIENT_ID"] = SENTINEL
    world.write_mapping({"backend": "1password", "references": {NAME: REF, OTHER: REF2, "GMAIL_CLIENT_ID": REF}})
    for key, value in world.environ.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(res, "_keyring", lambda: FakeStore())
    assert res.main(["--list"]) == 0
    out = capsys.readouterr()
    assert SENTINEL not in out.out + out.err
    line = next(l for l in out.out.splitlines() if l.startswith(NAME))
    assert "found (password manager (1password))" in line
    assert f"check the reference of {OTHER} in the mapping file" in out.out
    assert "mapped in the password manager, not asked: found earlier" in out.out
    assert res.main(["--check", NAME]) == 0
    out = capsys.readouterr()
    assert json.loads(out.out) == {"name": NAME, "found": True, "source": "password manager (1password)", "backend": "password-manager"}
    assert SENTINEL not in out.out + out.err
    assert res.main(["--check", OTHER]) == res.EXIT_NOT_FOUND
    assert "check the reference" in capsys.readouterr().err
    assert res.main(["--list", "--json"]) == 0
    assert SENTINEL not in capsys.readouterr().out


def test_check_exits_4_for_a_locked_or_unsafe_manager(world, monkeypatch, capsys):
    world.write_mapping()
    world.op.answer(REF, rc=1, stderr=NOT_SIGNED_IN)
    for key, value in world.environ.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(res, "_keyring", lambda: FakeStore())
    assert res.main(["--check", NAME]) == res.EXIT_LOCKED
    assert "the password manager (1Password) is locked" in capsys.readouterr().err
    world.mapping.chmod(0o644)
    assert res.main(["--check", NAME]) == res.EXIT_LOCKED
    assert "mapping" in capsys.readouterr().err


def test_the_help_text_has_the_password_manager_line_and_the_order(capsys):
    assert res.main(["--help"]) == 0
    text = capsys.readouterr().out
    assert "4. a password manager" in text and "password mgr" in text and "OP_SERVICE_ACCOUNT_TOKEN" in text


# --- the probe -----------------------------------------------------------------------------------------------------------------------


def test_the_probe_is_na_without_a_mapping_and_asks_whoami_otherwise(world):
    assert res.probe_manager(world.environ)["state"] == "na" and world.op.calls() == []
    world.write_mapping()
    signed_in(world)
    assert res.probe_manager(world.environ)["state"] == "ok"
    assert world.op.calls()[0]["argv"][1:] == ["whoami"]
    world.op.answer("whoami", rc=1, stderr=NOT_SIGNED_IN)
    got = res.probe_manager(world.environ)
    assert got["state"] == "locked" and "1Password" in got["detail"]
    world.environ["PATH"] = str(world.tmp / "empty-bin")
    assert res.probe_manager(world.environ)["state"] == "unavailable"
    world.mapping.chmod(0o644)
    assert res.probe_manager(world.environ)["state"] == "unsafe"


# --- nothing of the tool or the value leaks ------------------------------------------------------------------------------------------


def test_the_value_and_the_tools_text_never_appear_in_an_answer_or_an_exception(world, capsys):
    world.write_mapping()
    for stderr in (NOT_SIGNED_IN + " " + SENTINEL, NO_ITEM + " " + SENTINEL, "[ERROR] " + SENTINEL):
        world.op.answer(REF, rc=1, stdout=SENTINEL, stderr=stderr)
        got = world.lookup()
        assert SENTINEL not in repr(got) and SENTINEL not in res.store_locked_note() and SENTINEL not in str(res.store_failure())
    world.op.answer(REF, stdout=SENTINEL)
    found = world.lookup()
    assert found.value == SENTINEL and SENTINEL not in found.detail and SENTINEL not in (found.source or "")
    assert SENTINEL not in capsys.readouterr().out


def test_a_reference_the_backend_refuses_is_not_passed_even_when_a_caller_skips_the_check(world):
    backend = pm.OnePassword()
    env = pm.minimum_environment(world.environ)
    for ref in ("--help", "op://a/b/c?x=1", "op://a/b", "", None):
        assert backend.read(ref, env, 5).state == "unavailable"
    assert world.op.calls() == []


def test_the_reference_syntax():
    ok = pm.OnePassword.reference_ok
    assert ok("op://Example Vault/github-read/credential") and ok("op://v/i/s/f") and ok("op://a.b_c-d/e f/g")
    assert not ok("op://v/i") and not ok("op://v/i/s/f/g") and not ok("op://v/ i/f") and not ok("op:// v/i/f") and not ok("op://v/i/f?x=1")
    assert not ok("x" * 300) and not ok("OP://v/i/f") and not ok(" op://v/i/f")


def test_a_relative_path_entry_never_starts_a_file_of_the_working_folder(world, monkeypatch):
    world.write_mapping()
    signed_in(world)
    monkeypatch.chdir(world.op.folder)   # the fake is "op" in the working folder
    for path in ("", ".", "relative/bin", f".{os.pathsep}{world.tmp / 'empty-bin'}"):
        world.environ["PATH"] = path
        assert world.lookup().state == "locked" and res.store_failure() == "unavailable", path
    assert world.op.calls() == []
