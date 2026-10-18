"""Widening the accounts the platform may write to is a gain that needs the person's hash (package FND; runtime/policy_widening.py `account_items`,
`account_widening`, `dump_accounts`; runtime/ops_config.py `accept_config`; runtime/policy_grants.py `view`), exactly like a policy gain (POL-2): `accept-config`
stops, prints each gain and takes the hash of the list (`--widen`). A gain is a new account, a changed address, a new calendar, folder or mail folder name, a changed
id behind a name already there, and `move_removes_inbox` turned on for an account that was accepted. Removals and narrowing need no ceremony. Every address is on
`.example`, every id is fictional. Offline, no model.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_accounts_widening.py
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

import standin_tree as st

lab = st.load("lab")
ops = st.load("ops")
ops_core = st.load("ops_core")
policy_widening = st.load("policy_widening")

BASE = {
    "google": {"address": "ana@mail.example", "calendars": {"personal": "primary"}, "folders": {"default": "Folder_ID_01"}, "mail_folders": {"later": "Label_12"},
               "move_removes_inbox": False},
}


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("WB_LOCAL_EVIDENCE_DIR", str(tmp_path / "evidence"))
    built = st.build(tmp_path, monkeypatch, lab)
    monkeypatch.setattr(ops_core, "ROOT", str(built["tree"]))
    project = str(built["project"])
    ops.accept_config(project, ops.project_config.load(project)["sha256"])      # a project that was accepted before it named any account
    return project


def write(project, accounts):
    path = Path(project) / "docs" / "workbench" / "runtime.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw.pop("accounts", None)
    if accounts is not None:
        raw["accounts"] = accounts
    path.write_text(json.dumps(raw), encoding="utf-8")
    return ops.config(project)


def accept(project, accounts):
    """The person reads `config` and accepts with the hash of what it lists."""
    shown = write(project, accounts)
    return ops.accept_config(project, shown["sha256"], widen=shown["widening_sha256"])


def lines(project):
    return [f"{i['place']}:{i['group']}" for i in ops.config(project)["widening"] if i["place"] == "accounts"]


def gains(project, accounts):
    return [line.split(":", 1)[1] for line in (write(project, accounts) and lines(project))]


def refused_without_the_hash(project, accounts):
    shown = write(project, accounts)
    assert shown["widening_sha256"], "the file widens, so config shows a hash"
    with pytest.raises(ops.OpsError) as why:
        ops.accept_config(project, shown["sha256"])
    with pytest.raises(ops.OpsError):
        ops.accept_config(project, shown["sha256"], widen="0" * 64)
    assert "widens" in str(why.value) and "accounts:" in str(why.value) and "To accept it, run" in str(why.value)
    assert ops.config(project)["accepted"] is False, "nothing was accepted"
    return str(why.value)


def changed(accounts, edit):
    out = copy.deepcopy(accounts)
    edit(out)
    return out


# --- the first file that names an account -----------------------------------------------------------------------------------------------------------


def test_the_first_file_that_names_an_account_lists_everything_it_names_and_is_accepted_only_with_the_hash(world):
    said = refused_without_the_hash(world, BASE)
    for part in ("accounts:google:account", "accounts:google:address=ana@mail.example", "accounts:google:calendar:personal=primary",
                 "accounts:google:folder:default=Folder_ID_01", "accounts:google:mail-folder:later=Label_12"):
        assert part in said, part
    assert "move_removes_inbox" not in said, "it is off, so there is nothing to list"
    done = accept(world, BASE)
    assert "accounts:google:account" in lines_of(done) and "accounts:google:calendar:personal=primary" in lines_of(done)
    assert ops.config(world)["accepted"] is True and ops.config(world)["widening"] == [] and ops.config(world)["widening_sha256"] is None


def lines_of(done):
    return [f"{w['place']}:{w['group']}" for w in done["widened"]]


def test_the_same_file_accepted_again_widens_nothing(world):
    accept(world, BASE)
    shown = write(world, BASE)
    assert shown["widening"] == [] and shown["widening_sha256"] is None
    assert ops.accept_config(world, shown["sha256"])["widened"] == []


def test_config_shows_the_gain_of_a_file_that_is_not_accepted_yet_with_what_each_line_gives_away(world):
    shown = write(world, BASE)
    mine = [i for i in shown["widening"] if i["place"] == "accounts"]
    assert mine and all(i["channel"] == "accounts" and i["means"] for i in mine) and shown["accepted"] is False
    by_group = {i["group"]: i["means"] for i in mine}
    assert "create, change and remove events" in by_group["google:calendar:personal=primary"]
    assert "write new revisions" in by_group["google:folder:default=Folder_ID_01"]


# --- each gain, over an accepted file ---------------------------------------------------------------------------------------------------------------


GAINS = {
    "a new account": (lambda a: a.update(microsoft={"address": "ana@office.example", "calendars": {"personal": "default"}}),
                      ["microsoft:account", "microsoft:address=ana@office.example", "microsoft:calendar:personal=default"]),
    "a changed address": (lambda a: a["google"].update(address="other@mail.example"), ["google:address=other@mail.example"]),
    "a new calendar": (lambda a: a["google"]["calendars"].update(work="c_work@group.calendar.example"), ["google:calendar:work=c_work@group.calendar.example"]),
    "a new folder": (lambda a: a["google"]["folders"].update(invoices="Folder_ID_02"), ["google:folder:invoices=Folder_ID_02"]),
    "a new mail folder": (lambda a: a["google"]["mail_folders"].update(receipts="Label_77"), ["google:mail-folder:receipts=Label_77"]),
    "a changed id behind a name": (lambda a: a["google"]["calendars"].update(personal="elsewhere"), ["google:calendar:personal=elsewhere"]),
    "a changed folder id behind a name": (lambda a: a["google"]["folders"].update(default="Folder_ID_09"), ["google:folder:default=Folder_ID_09"]),
    "a changed mail folder id behind a name": (lambda a: a["google"]["mail_folders"].update(later="Label_99"), ["google:mail-folder:later=Label_99"]),
    "move_removes_inbox turned on": (lambda a: a["google"].update(move_removes_inbox=True), ["google:move_removes_inbox"]),
}


@pytest.mark.parametrize("name", list(GAINS))
def test_each_gain_stops_the_acceptance_lists_exactly_that_line_and_is_accepted_with_the_hash(world, name):
    edit, expected = GAINS[name]
    accept(world, BASE)
    wider = changed(BASE, edit)
    said = refused_without_the_hash(world, wider)
    assert gains(world, wider) == expected, name
    for line in expected:
        assert "accounts:" + line in said
    done = accept(world, wider)
    assert [w["group"] for w in done["widened"]] == expected
    assert ops.config(world)["accepted"] is True and gains(world, wider) == []


def test_a_new_account_does_not_list_move_removes_inbox_apart_it_is_part_of_the_account(world):
    accept(world, BASE)
    wider = changed(BASE, lambda a: a.update(microsoft={"address": "ana@office.example", "move_removes_inbox": True}))
    assert gains(world, wider) == ["microsoft:account", "microsoft:address=ana@office.example"]


# --- no ceremony for a removal or a narrowing -------------------------------------------------------------------------------------------------------


NARROWINGS = {
    "a calendar removed": lambda a: a["google"]["calendars"].clear(),
    "a folder removed": lambda a: a["google"]["folders"].pop("default"),
    "a mail folder removed": lambda a: a["google"]["mail_folders"].clear(),
    "the account removed": lambda a: a.pop("google"),
    "move_removes_inbox turned off": lambda a: a["google"].update(move_removes_inbox=False),
    "the keys written in another order": lambda a: a.update(google=dict(reversed(list(a["google"].items())))),
}


@pytest.mark.parametrize("name", list(NARROWINGS))
def test_a_removal_or_a_narrowing_is_accepted_without_the_hash(world, name):
    start = changed(BASE, lambda a: a["google"].update(move_removes_inbox=True)) if "turned off" in name else BASE
    accept(world, start)
    narrower = changed(start, NARROWINGS[name])
    shown = write(world, narrower)
    assert shown["widening"] == [] and shown["widening_sha256"] is None
    done = ops.accept_config(world, shown["sha256"])
    assert done["widened"] == [] and ops.config(world)["accepted"] is True


def test_what_was_removed_is_a_gain_again_when_it_comes_back(world):
    accept(world, BASE)
    smaller = changed(BASE, lambda a: a["google"]["calendars"].clear())
    ops.accept_config(world, write(world, smaller)["sha256"])
    assert gains(world, BASE) == ["google:calendar:personal=primary"]


def test_a_file_that_removes_one_target_and_adds_another_lists_only_the_new_one(world):
    accept(world, BASE)
    swapped = changed(BASE, lambda a: (a["google"]["calendars"].clear(), a["google"]["calendars"].update(work="c_work")))
    assert gains(world, swapped) == ["google:calendar:work=c_work"]


# --- what the hash binds ---------------------------------------------------------------------------------------------------------------------------


def test_the_hash_binds_the_id_so_a_hash_for_one_id_accepts_no_other(world):
    accept(world, BASE)
    first = write(world, changed(BASE, lambda a: a["google"]["calendars"].update(work="c_one")))["widening_sha256"]
    other = write(world, changed(BASE, lambda a: a["google"]["calendars"].update(work="c_two")))
    assert other["widening_sha256"] != first
    with pytest.raises(ops.OpsError):
        ops.accept_config(world, other["sha256"], widen=first)
    assert ops.accept_config(world, other["sha256"], widen=other["widening_sha256"])["widened"]


def test_a_gain_in_the_accounts_and_in_a_policy_is_one_list_and_one_hash(world):
    shown = write(world, BASE)
    path = Path(world) / "docs" / "workbench" / "runtime.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["channels"] = {"messaging": ["read", "release"]}
    path.write_text(json.dumps(raw), encoding="utf-8")
    both = ops.config(world)
    places = {i["place"] for i in both["widening"]}
    assert "accounts" in places and "messaging" in places
    done = ops.accept_config(world, both["sha256"], widen=both["widening_sha256"])
    assert {w["place"] for w in done["widened"]} == places


# --- the record ------------------------------------------------------------------------------------------------------------------------------------


def test_the_biggest_file_fits_the_cursor_and_is_read_back(world):
    names = lambda n: {f"n{i}": f"Id_{i:04d}" for i in range(n)}      # noqa: E731
    big = {p: {"address": f"ana@{p}.example", "calendars": names(50), "folders": names(50), "mail_folders": names(50), "move_removes_inbox": True}
           for p in ("google", "microsoft")}
    big["microsoft"]["calendars"] = {k: "Id" + v[3:] for k, v in big["microsoft"]["calendars"].items()}
    accept(world, big)
    ctx = ops_core.context(world)
    text = ctx["store"].cursor_get(ctx["conn"], policy_widening.ACCOUNTS)
    assert len(text) < 4096 and len(policy_widening.parse_accounts(text)) == 2 * (3 + 150)
    assert write(world, big)["widening"] == []


def test_a_record_that_is_not_one_holds_nothing():
    assert policy_widening.parse_accounts(None) is None and policy_widening.parse_accounts("") is None and policy_widening.parse_accounts("not json") is None
    for text in ('{"v":2,"items":""}', '{"v":1,"items":"abc"}', '{"v":1,"items":"zzzzzzzzzz"}', '{"v":1,"items":5}', "[]"):
        assert policy_widening.parse_accounts(text) is None, text
    cfg = {"accounts": {"google": {"address": "a@b.example", "calendars": {"x": "primary"}, "folders": {}, "mail_folders": {}, "move_removes_inbox": False}}}
    assert [i["group"] for i in policy_widening.account_widening("garbage", cfg)] == ["google:account", "google:address=a@b.example", "google:calendar:x=primary"]
    assert policy_widening.account_widening(policy_widening.dump_accounts(cfg), cfg) == []
    assert policy_widening.account_widening(None, {}) == [] and policy_widening.account_widening(None, {"accounts": None}) == []


def test_the_record_holds_no_address_no_name_and_no_id():
    cfg = {"accounts": {"google": {"address": "ana@mail.example", "calendars": {"personal": "primary"}, "folders": {}, "mail_folders": {}, "move_removes_inbox": False}}}
    text = policy_widening.dump_accounts(cfg)
    assert "ana" not in text and "personal" not in text and "primary" not in text and "mail.example" not in text
