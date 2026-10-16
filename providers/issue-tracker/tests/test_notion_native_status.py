"""Tests of the board's native status on Notion (R13, providers/issue-tracker/notion.py): the opt-in key task_board.native_status,
against the stand-in service (providers/documents/tests/fake_notion.py), which gains a status property with groups and refuses a
status option the property does not list. Offline: no network, no real Notion.

Run: uv run --with pytest==9.1.1 pytest providers/issue-tracker/tests/test_notion_native_status.py
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import test_issue_tracker_notion as base_tests

STATES = ("requested", "planned", "ready", "running", "waiting", "blocked", "done", "failed", "cancelled")
GROUP_OF = {"requested": "Not started", "planned": "Not started", "ready": "Not started", "running": "In progress",
            "waiting": "In progress", "blocked": "In progress", "failed": "In progress", "done": "Done", "cancelled": "Done"}


def board_with(tmp_path: Path, native=True, state_kind="status", groups=None, config=None):
    """A board over a base that has a native status property named Progress (when native), and a task_board.native_status
    in the configuration (when config is not None)."""
    board = base_tests.Board(tmp_path)
    ident = board.fake.create_base(state_kind=state_kind, native="Progress" if native else None, groups=groups)
    board.harness.base = ident
    settings = json.loads(board.config.read_text(encoding="utf-8"))
    settings["base"] = ident
    if config is not None:
        settings["native_status"] = config
    board.config.write_text(json.dumps(settings), encoding="utf-8")
    return board


def progress(board, ident):
    return ((board.fake.pages[ident]["properties"]).get("Progress") or {}).get("status")


def test_off_by_default_nothing_new_is_written(tmp_path):
    board = board_with(tmp_path)   # the base has the property; the configuration does not name it
    made = board.upsert({"title": "Voice", "state": "done"}, key="k1")[1]
    assert progress(board, made["id"]) is None
    assert board.fake.pages[made["id"]]["properties"]["Status"]["status"]["name"] == "done"
    code, out, _ = board.run("--check")
    assert code == 0 and out == {"ok": True}


@pytest.mark.parametrize("state", STATES)
def test_each_of_the_nine_states_lands_in_its_group(tmp_path, state):
    board = board_with(tmp_path, config={"property": "Progress"})
    made = board.upsert({"title": "Voice", "state": "requested"}, key="k1")[1]
    assert progress(board, made["id"])["name"] == "Not started"
    board.upsert({"state": state}, key="k2", ident=made["id"])
    assert progress(board, made["id"])["name"] == GROUP_OF[state]
    assert board.fake.pages[made["id"]]["properties"]["Status"]["status"]["name"] == state   # the runtime's own state is still written


def test_a_row_created_in_a_state_gets_the_option_of_its_group(tmp_path):
    board = board_with(tmp_path, config={"property": "Progress"})
    made = board.upsert({"title": "Voice", "state": "failed"}, key="k1")[1]
    assert progress(board, made["id"])["name"] == "In progress"


def test_a_configured_option_wins_and_the_first_option_of_the_group_is_the_default(tmp_path):
    groups = [("To-do", ["Backlog", "Next"]), ("In progress", ["Working"]), ("Complete", ["Shipped", "Archived"])]
    board = board_with(tmp_path, groups=groups, config={"property": "Progress", "options": {"complete": "Archived", "to_do": "Next"}})
    made = board.upsert({"title": "Voice", "state": "ready"}, key="k1")[1]
    assert progress(board, made["id"])["name"] == "Next"
    board.upsert({"state": "done"}, key="k2", ident=made["id"])
    assert progress(board, made["id"])["name"] == "Archived"
    board.upsert({"state": "running"}, key="k3", ident=made["id"])
    assert progress(board, made["id"])["name"] == "Working"   # not configured: the first option of the group
    code, out, _ = board.run("--check")
    assert code == 0 and out["native_status"] == {"to_do": "Next", "in_progress": "Working", "complete": "Archived"}


def test_a_row_whose_state_does_not_change_keeps_what_a_person_moved_it_to(tmp_path):
    board = board_with(tmp_path, config={"property": "Progress"})
    made = board.upsert({"title": "Voice", "state": "ready"}, key="k1")[1]
    board.fake.person_sets(made["id"], "Progress", "Done")
    board.upsert({"state": "ready", "shown": {"note": "a new note"}}, key="k2", ident=made["id"])
    assert progress(board, made["id"])["name"] == "Done"            # shown changed, the state did not: never read back, never rewritten
    board.upsert({"state": "running"}, key="k3", ident=made["id"])
    assert progress(board, made["id"])["name"] == "In progress"     # the state changed: the group's option is written again


def test_the_option_is_not_written_when_the_row_already_holds_it(tmp_path):
    board = board_with(tmp_path, config={"property": "Progress"})
    made = board.upsert({"title": "Voice", "state": "ready"}, key="k1")[1]
    board.fake.person_sets(made["id"], "Progress", "Not started")
    before = len([r for r in board.fake.requests if r[0] == "PATCH" and r[1].startswith("/v1/pages/")])
    board.upsert({"state": "planned"}, key="k2", ident=made["id"])    # both states are in the group, the option is the same
    sent = [r for r in board.fake.requests if r[0] == "PATCH" and r[1].startswith("/v1/pages/")][before:]
    assert all("Progress" not in (r[2] or {}).get("properties", {}) for r in sent)


def test_the_runtimes_select_is_still_written_beside_the_native_status(tmp_path):
    board = board_with(tmp_path, state_kind="select", config={"property": "Progress"})
    made = board.upsert({"title": "Voice", "state": "done"}, key="k1")[1]
    assert board.fake.pages[made["id"]]["properties"]["Status"]["select"]["name"] == "done"
    assert progress(board, made["id"])["name"] == "Done"
    assert board.run("get", "--id", made["id"])[1]["state"] == "done"


@pytest.mark.parametrize("config", [
    {"property": "Status"},                                                       # the property that holds the runtime's states
    {"property": ""}, {"options": {"complete": "Done"}}, "Progress", {"property": "Progress", "extra": 1},
    {"property": "Progress", "options": {"later": "Done"}},                       # a group that does not exist
    {"property": "Progress", "options": {"to_do": "Done", "complete": "Done"}},   # two groups on one option
    {"property": "Progress", "options": {"complete": ""}},
])
def test_a_configuration_the_file_alone_shows_wrong_is_refused_with_exit_2(tmp_path, config):
    board = board_with(tmp_path, config=config)
    code, out, said = board.run("list")
    assert code == 2 and out is None and "native_status" in said


def test_a_property_that_is_not_a_status_property_is_refused_by_check_with_exit_3(tmp_path):
    board = board_with(tmp_path, config={"property": "Runtime"})   # a text property
    code, _, said = board.run("--check")
    assert code == 3 and "status property 'Runtime'" in said
    (tmp_path / "other").mkdir()
    code, _, said = board_with(tmp_path / "other", native=False, config={"property": "Progress"}).run("--check")
    assert code == 3 and "no status property 'Progress'" in said


def test_an_option_that_is_not_in_its_group_fails_check_with_exit_3_and_does_not_fail_the_state_write(tmp_path):
    board = board_with(tmp_path, config={"property": "Progress", "options": {"complete": "Not started"}})
    code, _, said = board.run("--check")
    assert code == 3 and "'Not started'" in said and "'Complete'" in said and "Done" in said
    made_code, made, said = board.upsert({"title": "Voice", "state": "done"}, key="k1")
    assert made_code == 0 and board.rows() == 1, "the runtime's own state is written whatever the native status is"
    assert said.count("warning: the native status of the board is skipped") == 1 and "'Not started'" in said
    assert progress(board, made["id"]) is None and board.fake.pages[made["id"]]["properties"]["Status"]["status"]["name"] == "done"


def test_a_base_whose_groups_cannot_be_found_is_refused_by_check_naming_what_it_found(tmp_path):
    groups = [("A fazer", ["Novo"]), ("Em curso", ["Fazendo"]), ("Pronto", ["Feito"])]
    board = board_with(tmp_path, groups=groups, config={"property": "Progress"})
    code, _, said = board.run("--check")
    assert code == 3 and "no group 'To-do'" in said and "A fazer" in said and "Em curso" in said


def test_an_option_a_person_deleted_meanwhile_skips_the_native_status_and_still_writes_the_state(tmp_path):
    board = board_with(tmp_path, config={"property": "Progress", "options": {"complete": "Done"}})
    made = board.upsert({"title": "Voice", "state": "ready"}, key="k1")[1]
    status = board.fake.bases[board.harness.base]["properties"]["Progress"]["status"]
    status["options"] = [o for o in status["options"] if o["name"] != "Done"]    # the person deleted the option meanwhile
    status["groups"][2]["option_ids"] = []
    code, _, said = board.upsert({"state": "done"}, key="k2", ident=made["id"])
    assert code == 0 and progress(board, made["id"])["name"] == "Not started", "the native status is left as it was"
    assert board.fake.pages[made["id"]]["properties"]["Status"]["status"]["name"] == "done" and "skipped" in said
    assert board.run("--check")[0] == 3


def test_the_stand_in_refuses_a_status_option_the_property_does_not_list_with_400(tmp_path):
    board = board_with(tmp_path, config={"property": "Progress"})
    parent = {"type": "data_source_id", "data_source_id": board.harness.base}
    with pytest.raises(Exception) as refused:
        board.fake.create_page(parent, {"Progress": {"status": {"name": "Nope"}}})
    assert getattr(refused.value, "status", None) == 400
    board.fake.create_page(parent, {"Progress": {"status": {"name": "Done"}}})   # an option it lists is taken
    board.fake.create_page(parent, {"Status": {"status": {"name": "any word"}}})  # the runtime's own property lists none: any word


def test_a_property_renamed_since_does_not_fail_the_states_write_and_check_exits_3(tmp_path):
    board = board_with(tmp_path, config={"property": "Progress"})
    made = board.upsert({"title": "Voice", "state": "ready"}, key="k1")[1]
    props = board.fake.bases[board.harness.base]["properties"]
    props["Avancement"] = props.pop("Progress")            # a person renamed the property
    for state in ("running", "done"):                      # an update, then a creation
        code, _, said = board.upsert({"state": state}, key="k-" + state, ident=made["id"])
        assert code == 0 and said.count("warning: the native status") == 1
        assert board.fake.pages[made["id"]]["properties"]["Status"]["status"]["name"] == state
    code, _, said = board.upsert({"title": "Another", "state": "ready"}, key="k2")
    assert code == 0 and "no status property 'Progress'" in said and board.rows() == 2
    code, _, said = board.run("--check")
    assert code == 3 and "no status property 'Progress'" in said


PT = [("A fazer", ["Novo"]), ("Em curso", ["Fazendo"]), ("Concluido", ["Feito", "Entregue"])]


def test_a_base_whose_groups_have_other_names_is_mapped_by_the_configuration(tmp_path):
    config = {"property": "Progress", "groups": {"A fazer": "to_do", "Em curso": "in_progress", "Concluido": "complete"}, "options": {"complete": "Entregue"}}
    board = board_with(tmp_path, groups=PT, config=config)
    code, out, _ = board.run("--check")
    assert code == 0 and out["native_status"] == {"to_do": "Novo", "in_progress": "Fazendo", "complete": "Entregue"}
    made = board.upsert({"title": "Voice", "state": "ready"}, key="k1")[1]
    assert progress(board, made["id"])["name"] == "Novo"
    board.upsert({"state": "done"}, key="k2", ident=made["id"])
    assert progress(board, made["id"])["name"] == "Entregue"
    # a mapped name that the base lacks is exit 3 and names the groups found
    wrong = board_with(tmp_path / "w", groups=PT, config={"property": "Progress", "groups": {"Pendente": "to_do"}}) if (tmp_path / "w").mkdir() is None else None
    code, _, said = wrong.run("--check")
    assert code == 3 and "no group 'Pendente'" in said and "A fazer" in said


def test_the_unmapped_groups_of_a_non_english_base_still_exit_3_and_a_bad_group_mapping_is_exit_2(tmp_path):
    board = board_with(tmp_path, groups=PT, config={"property": "Progress", "groups": {"A fazer": "to_do"}})
    code, _, said = board.run("--check")
    assert code == 3 and "no group 'In progress'" in said          # only one of the three is mapped: the rest is looked for by the reference's names
    for groups in ({"A fazer": "later"}, {"": "to_do"}, {"A fazer": "to_do", "Novo": "to_do"}, ["A fazer"]):
        folder = tmp_path / ("g" + str(abs(hash(json.dumps(groups)))))
        folder.mkdir()
        code, out, said = board_with(folder, groups=PT, config={"property": "Progress", "groups": groups}).run("list")
        assert code == 2 and "native_status" in said, groups
