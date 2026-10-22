"""The key `accounts` of the project's configuration (package FND; runtime/project_config.py `_accounts`, `account_entry`, `account_target`): where the platform may
write in the person's own Google and Microsoft accounts. The file is closed, every name is lowercase letters, digits and hyphens, every id is checked by a
full-match pattern of its provider (a Google id holds no slash; a OneDrive path is `/` and names), and a target the file does not name is never one. Every
address is on `.example`; every id is fictional. Offline, no model.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_project_accounts.py
"""
from __future__ import annotations

import json
import re

import pytest

import standin_tree as st

lab = st.load("lab")
project_config = st.load("project_config")
phrases = st.load("phrases")

FULL = {
    "google": {"address": "ana@mail.example", "calendars": {"personal": "primary", "team": "c_abc123@group.calendar.google.example"},
               "folders": {"default": "Folder_ID_01", "invoices": "Folder-ID-02"}, "mail_folders": {"receipts": "Label_12", "later": "STARRED"},
               "move_removes_inbox": False},
    "microsoft": {"address": "ana@office.example", "calendars": {"personal": "default", "work": "AAMkAGI2TG93AAA="},
                  "folders": {"default": "/Documents/openhora", "ids": "01ABCDEF2345!678", "accents": "/Docs/Résumés (2026)"},
                  "mail_folders": {"archive": "archive", "bills": "AAMkAGI2TG93BBB="}},
}


@pytest.fixture
def project(tmp_path, monkeypatch):
    built = st.build(tmp_path, monkeypatch, lab)
    return built["project"]


def write(project, accounts="absent", **more):
    path = project / "docs" / "workbench" / "runtime.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw.update(more)
    if accounts != "absent":
        raw["accounts"] = accounts
    path.write_text(json.dumps(raw), encoding="utf-8")
    return project_config.load(str(project))


def refused(project, accounts):
    with pytest.raises(project_config.ConfigError) as why:
        write(project, accounts)
    return str(why.value)


def test_the_key_is_known_and_absent_means_the_platform_writes_to_no_account(project):
    assert "accounts" in project_config.TASK_RUNTIME_KEYS and "accounts" not in project_config.FIRST_RUNTIME_KEYS
    assert project_config.load(str(project))["accounts"] is None
    assert project_config.account_entry(project_config.load(str(project)), "google") is None


def test_a_full_entry_is_checked_and_completed(project):
    cfg = write(project, FULL)
    assert cfg["accounts"]["google"] == {**FULL["google"], "address": "ana@mail.example"}
    assert cfg["accounts"]["microsoft"]["move_removes_inbox"] is True, "absent means true"
    only = write(project, {"google": {"address": "ana@mail.example"}})["accounts"]
    assert only == {"google": {"address": "ana@mail.example", "calendars": {}, "folders": {}, "mail_folders": {}, "move_removes_inbox": True}}
    assert write(project, {})["accounts"] == {}


def test_the_hash_of_the_file_covers_the_accounts_so_a_changed_target_asks_to_be_accepted(project):
    first = write(project, FULL)["sha256"]
    changed = json.loads(json.dumps(FULL))
    changed["google"]["calendars"]["personal"] = "somewhere-else"
    assert write(project, changed)["sha256"] != first


@pytest.mark.parametrize("bad, part", [
    ([], "must be an object"), ("google", "must be an object"), ({"aws": {"address": "a@b.example"}}, "the keys google, microsoft"),
    ({"google": []}, "address is required"), ({"google": {}}, "address is required"), ({"google": {"address": "a@b.example", "token": "x"}}, "address is required"),
    ({"google": {"address": "not an address"}}, "accounts.google.address"), ({"google": {"address": "Ana <a@b.example>"}}, "accounts.google.address"),
    ({"google": {"address": "a@b.example", "calendars": []}}, "calendars must be an object"),
    ({"google": {"address": "a@b.example", "calendars": {"Upper": "primary"}}}, "a name is lowercase"),
    ({"google": {"address": "a@b.example", "calendars": {"has space": "primary"}}}, "a name is lowercase"),
    ({"google": {"address": "a@b.example", "calendars": {"x" * 33: "primary"}}}, "a name is lowercase"),
    ({"google": {"address": "a@b.example", "calendars": {"": "primary"}}}, "a name is lowercase"),
    ({"google": {"address": "a@b.example", "calendars": {"x": 5}}}, "is not the id of a google calendar"),
    ({"google": {"address": "a@b.example", "calendars": {"x": "has/slash"}}}, "a Google id holds no slash"),
    ({"google": {"address": "a@b.example", "calendars": {"x": "a b"}}}, "is not the id of a google calendar"),
    ({"google": {"address": "a@b.example", "calendars": {"x": ""}}}, "is not the id of a google calendar"),
    ({"google": {"address": "a@b.example", "calendars": {"x": ".."}}}, "is not the id of a google calendar"),
    ({"google": {"address": "a@b.example", "calendars": {"x": "."}}}, "is not the id of a google calendar"),
    ({"google": {"address": "a@b.example", "calendars": {"x": "victim#"}}}, "is not the id of a google calendar"),
    ({"google": {"address": "a@b.example", "calendars": {"x": "a%2eb"}}}, "is not the id of a google calendar"),
    ({"google": {"address": "a@b.example", "calendars": {"x": "a?b=c"}}}, "is not the id of a google calendar"),
    ({"google": {"address": "a@b.example", "calendars": {"x": "a\u202eb"}}}, "is not the id of a google calendar"),
    ({"microsoft": {"address": "a@b.example", "folders": {"x": "/Docs/%2e%2e"}}}, "is not the id of a microsoft folder"),
    ({"microsoft": {"address": "a@b.example", "folders": {"x": "/Docs/%2F..%2F"}}}, "is not the id of a microsoft folder"),
    ({"microsoft": {"address": "a@b.example", "folders": {"x": "/Docs#x"}}}, "is not the id of a microsoft folder"),
    ({"microsoft": {"address": "a@b.example", "folders": {"x": "/Docs/a?b"}}}, "is not the id of a microsoft folder"),
    ({"microsoft": {"address": "a@b.example", "folders": {"x": "/Docs/\u202eabc"}}}, "is not the id of a microsoft folder"),
    ({"microsoft": {"address": "a@b.example", "folders": {"x": "/Docs/a\u200bb"}}}, "is not the id of a microsoft folder"),
    ({"microsoft": {"address": "a@b.example", "folders": {"x": "/Docs/a\u2028b"}}}, "is not the id of a microsoft folder"),
    ({"google": {"address": "a@b.example", "folders": {"x": "folder/sub"}}}, "a Google id holds no slash"),
    ({"google": {"address": "a@b.example", "folders": {"x": "/Documents/../x"}}}, "a Google id holds no slash"),
    ({"google": {"address": "a@b.example", "folders": {"x": "/"}}}, "a Google id holds no slash"),
    ({"google": {"address": "a@b.example", "folders": {"x": "/Docs#x"}}}, "a Google id holds no slash"),
    ({"google": {"address": "a@b.example", "folders": {"x": "Documents/sub"}}}, "a Google id holds no slash"),
    ({"google": {"address": "a@b.example", "mail_folders": {"x": "INBOX/child"}}}, "a Google id holds no slash"),
    ({"google": {"address": "a@b.example", "mail_folders": {"x": "Label 1"}}}, "is not the id of a google mail folder"),
    ({"microsoft": {"address": "a@b.example", "folders": {"x": "/a/../b"}}}, "is not the id of a microsoft folder"),
    ({"microsoft": {"address": "a@b.example", "folders": {"x": "/a/./b"}}}, "is not the id of a microsoft folder"),
    ({"microsoft": {"address": "a@b.example", "folders": {"x": "/a//b"}}}, "is not the id of a microsoft folder"),
    ({"microsoft": {"address": "a@b.example", "folders": {"x": "/"}}}, "is not the id of a microsoft folder"),
    ({"microsoft": {"address": "a@b.example", "folders": {"x": "/a/b/"}}}, "is not the id of a microsoft folder"),
    ({"microsoft": {"address": "a@b.example", "folders": {"x": "/a:b"}}}, "is not the id of a microsoft folder"),
    ({"microsoft": {"address": "a@b.example", "folders": {"x": "/a\\b"}}}, "is not the id of a microsoft folder"),
    ({"microsoft": {"address": "a@b.example", "folders": {"x": "/a\nb"}}}, "is not the id of a microsoft folder"),
    ({"microsoft": {"address": "a@b.example", "folders": {"x": "/ a"}}}, "is not the id of a microsoft folder"),
    ({"microsoft": {"address": "a@b.example", "folders": {"x": "/a."}}}, "is not the id of a microsoft folder"),
    ({"microsoft": {"address": "a@b.example", "folders": {"x": "/" + "a" * 101}}}, "is not the id of a microsoft folder"),
    ({"microsoft": {"address": "a@b.example", "folders": {"x": "relative/path"}}}, "is not the id of a microsoft folder"),
    ({"microsoft": {"address": "a@b.example", "calendars": {"x": "has/slash"}}}, "is not the id of a microsoft calendar"),
    ({"microsoft": {"address": "a@b.example", "mail_folders": {"x": "/path"}}}, "is not the id of a microsoft mail folder"),
    ({"google": {"address": "a@b.example", "move_removes_inbox": "yes"}}, "move_removes_inbox must be true or false"),
    ({"google": {"address": "a@b.example", "move_removes_inbox": 1}}, "move_removes_inbox must be true or false"),
])
def test_a_wrong_entry_is_refused_naming_the_place(project, bad, part):
    assert part in refused(project, bad)


def test_a_map_has_a_limit_of_names(project):
    big = {f"n{i}": "primary" for i in range(project_config.ACCOUNT_SECTION_MAX + 1)}
    assert "at most" in refused(project, {"google": {"address": "a@b.example", "calendars": big}})
    assert write(project, {"google": {"address": "a@b.example", "calendars": dict(list(big.items())[:-1])}})["accounts"]["google"]["calendars"]


def test_the_closed_file_still_names_the_nearest_key(project):
    path = project / "docs" / "workbench" / "runtime.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["acounts"] = {}
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(project_config.ConfigError) as why:
        project_config.load(str(project))
    assert "did you mean accounts?" in str(why.value)


# --- the targets ---------------------------------------------------------------------------------------------------------------------------------


def test_limit_55_only_what_the_file_names_is_a_target(project):
    cfg = write(project, FULL)
    target = lambda *a: project_config.account_target(cfg, *a)      # noqa: E731
    assert target("google", "calendars", "team") == ("c_abc123@group.calendar.google.example", None)
    assert target("google", "calendars") == ("primary", None), "no name means the first one listed"
    assert target("google", "folders") == ("Folder_ID_01", None), "no name means the folder named default"
    assert target("microsoft", "folders", "accents") == ("/Docs/Résumés (2026)", None)
    assert target("google", "mail_folders", "receipts") == ("Label_12", None)
    for args, part in [(("google", "calendars", "not-listed"), "is not one of the calendars the project lists for the account google"),
                       (("google", "mail_folders"), "name one of the mail folders"),
                       (("google", "mail_folders", "INBOX"), "is not one of the mail folders"),
                       (("google", "folders", "../etc"), "is not one of the folders"),
                       (("aws", "calendars"), "is not set up for this project"),
                       (("google", "elsewhere"), "there is no kind of target")]:
        found, why = target(*args)
        assert found is None and part in why, (args, why)
    assert target("aws", "calendars")[1] == phrases.en("ACCT_NOT_CONFIGURED").format(account="aws")


def test_an_account_with_nothing_listed_has_no_target_and_says_so(project):
    cfg = write(project, {"google": {"address": "a@b.example"}})
    assert project_config.account_target(cfg, "google", "calendars")[0] is None and "none are listed" in project_config.account_target(cfg, "google", "calendars")[1]
    none = write(project, "absent")
    assert project_config.account_target(none, "google", "calendars")[0] is None
    assert project_config.account_entry({}, "google") is None and project_config.account_entry(None, "google") is None
    assert project_config.account_entry(cfg, "aws") is None and project_config.account_entry(cfg, ["google"]) is None


def test_a_long_name_asked_for_is_cut_in_the_sentence(project):
    cfg = write(project, FULL)
    why = project_config.account_target(cfg, "google", "calendars", "x" * 500)[1]
    assert "x" * 41 not in why and len(why) < 400


def test_a_name_that_is_not_a_text_or_a_section_that_is_not_a_text_is_a_refusal_never_an_error(project):
    cfg = write(project, FULL)
    for name in (["personal"], {"p": 1}, 5, 1.5, True, b"personal", ("a",), object()):
        found, why = project_config.account_target(cfg, "google", "calendars", name)
        assert found is None and "is not one of the calendars" in why or "a name is a text" in why, (name, why)
    for section in (["calendars"], {"calendars": 1}, 5, None):
        assert project_config.account_target(cfg, "google", section, None)[0] is None
    for account in (["google"], {"g": 1}, 5):
        assert project_config.account_target(cfg, account, "calendars")[0] is None


def test_a_name_echoed_in_a_refusal_holds_no_line_end_or_hidden_character(project):
    cfg = write(project, FULL)
    for name in ("a\nCalendar: work", "x\u202ey", "tab\there"):
        why = project_config.account_target(cfg, "google", "calendars", name)[1]
        assert "\n" not in why and "\u202e" not in why and "\t" not in why, repr(why)
    why = project_config.account_target(cfg, "a\nb", "calendars")[1]
    assert "\n" not in why


def test_the_patterns_have_no_way_to_hold_a_path_traversal_or_a_url(project):
    for provider in project_config.ACCOUNT_PROVIDERS:
        for section in project_config.ACCOUNT_SECTIONS:
            pattern = project_config.ACCOUNT_ID[(provider, section)]
            for risky in ("../x", "a/b", "http://x", "a?b=c", "a b", "a\n", "a\x00", "a\\b", "%2e%2e", "a;b", "a&b", "a'b", 'a"b'):
                assert pattern.fullmatch(risky) is None, (provider, section, risky)
    assert re.compile(project_config.ACCOUNT_NAME.pattern).fullmatch("good-name-1") and project_config.ACCOUNT_NAME.fullmatch("Bad") is None


def test_the_one_drive_path_branch_has_no_way_to_hold_a_traversal_a_fragment_a_query_or_a_percent_encoding(project):
    good = ["/Documents/openhora", "/Docs/Résumés (2026)", "/a/b c/d-e_f"]
    bad = ["/Docs/%2e%2e", "/Docs/%2E%2E", "/Docs/%2F..%2F", "/Docs/..%2f", "/Docs#x", "/Docs/a?b", "/Docs/\u202eabc", "/Docs/\u200b", "/Docs/\ufeff", "/Docs/a\u2028b",
           "/Docs/a\u2029b", "/Docs/\x00", "/Docs/\x7f", "/a//b", "/a/../b", "/a/./b", "/", "", "rel/ative", "/a\\b", "/a:b", "/a|b", "/a*b", "/a<b", '/a"b']
    for value in good:
        assert project_config._account_id("microsoft", "folders", value) is True, value
    for value in bad:
        assert project_config._account_id("microsoft", "folders", value) is False, repr(value)
    for value in (".", "..", "a#b", "a%2eb", "a?b", "a b", "a/b", "a\u202eb", "a\u200bb"):
        assert project_config._account_id("google", "calendars", value) is False, repr(value)
    assert project_config._account_id("google", "calendars", "primary") and project_config._account_id("google", "calendars", "a.b@c.example")
