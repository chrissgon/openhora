"""Tests of the mirror of tasks with the task board (runtime/board.py) and of `sync`: the local provider on a
temporary folder, the stand-in tree and adapter (standin_tree.py), no network.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_board_mirror.py
"""
from __future__ import annotations

import json
import shutil

import pytest

import standin_tree as st

lab = st.load("lab")
ops = st.load("ops")
ops_core = st.load("ops_core")

# A provider that stands for one on a platform: it records every call and keeps no board.
STUB = '''#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
import json, os, sys
argv = sys.argv[1:]
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "stub-calls.txt"), "a") as f:
    f.write(" ".join(a for a in argv if not a.startswith("/")) + "\\n")
verb = argv[0]
if verb == "list":
    print(json.dumps({"items": [], "truncated": False}))
elif verb == "upsert":
    print(json.dumps({"id": "s" + str(abs(hash(" ".join(argv))) % 1000), "version": "v1", "created": True}))
else:
    print(json.dumps({"ok": True}))
'''


def configure(built, board, **extra):
    path = built["project"] / "docs" / "workbench" / "runtime.json"
    cfg = json.loads(path.read_text(encoding="utf-8"))
    cfg["task_board"] = board
    cfg.update(extra)
    path.write_text(json.dumps(cfg), encoding="utf-8")


def accept(project):
    ops.accept_config(project, ops.project_config.load(project)["sha256"])


@pytest.fixture
def tree(tmp_path, monkeypatch):
    built = st.build(tmp_path, monkeypatch, lab)
    folder = built["tree"] / "providers" / "issue-tracker"
    folder.mkdir(parents=True)
    shutil.copyfile(st.REPO / "providers" / "issue-tracker" / "local.py", folder / "local.py")
    (folder / "stub.py").write_text(STUB, encoding="utf-8")
    board = tmp_path / "board"
    board.mkdir()
    configure(built, {"provider": "local", "dir": str(board)})
    monkeypatch.setattr(ops_core, "ROOT", str(built["tree"]))
    monkeypatch.setattr(ops.plan, "pack_skills", lambda cfg, root: ["demo-asks", "demo-writes"])
    accept(str(built["project"]))
    return {**built, "board": board, "stub_calls": folder / "stub-calls.txt"}


def project_of(tree) -> str:
    return str(tree["project"])


def planned(tree) -> dict:
    """A request planned from the demo flow and approved: {"request", "market", "profile"} task ids."""
    project = project_of(tree)
    request = ops.request(project, "Find the first market.")["request"]
    opened = ops.route(project, request, flow="demo")
    tasks = ops.approve(project, opened["pending_id"])["tasks"]
    return {"request": request, **{t["key"]: t["id"] for t in tasks}}


def store(tree):
    ctx = ops_core.context(project_of(tree))
    return ctx["store"], ctx["conn"]


def task(tree, task_id) -> dict:
    s, conn = store(tree)
    return s.task_get(conn, task_id)


def item_file(tree, task_id):
    return tree["board"] / (task(tree, task_id)["remote_id"] + ".md")


def edit_item(tree, task_id, old, new):
    path = item_file(tree, task_id)
    text = path.read_text(encoding="utf-8")
    assert old in text, (old, text)
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def items(tree) -> list:
    return sorted(p.name for p in tree["board"].glob("*.md"))


def test_an_approved_plan_appears_on_the_board_one_item_per_task_and_one_for_the_request(tree):
    ids = planned(tree)
    out = ops.sync(project_of(tree))
    assert sorted(out["board"]["pushed"]) == sorted(ids.values()) and out["board"]["failed"] == []
    assert out["documents"] is None and len(items(tree)) == 3
    market = item_file(tree, ids["market"]).read_text(encoding="utf-8")
    assert market.startswith("# Market\n") and "State: ready" in market and "do the market analysis." in market
    assert "- skill: demo-asks" in market and f"- request: {ids['request']}" in market
    assert "State: planned" in item_file(tree, ids["request"]).read_text(encoding="utf-8")


def test_a_second_sync_with_nothing_changed_writes_nothing_and_reads_no_item(tree):
    planned(tree)
    ops.sync(project_of(tree))
    before = {p.name: p.read_bytes() for p in tree["board"].glob("*.md")}
    again = ops.sync(project_of(tree))["board"]
    assert again["pushed"] == [] and again["pulled"] == [] and again["created"] == []
    assert {p.name: p.read_bytes() for p in tree["board"].glob("*.md")} == before


def test_a_title_a_person_edited_on_the_board_reaches_the_store_and_is_never_written_back(tree):
    ids = planned(tree)
    ops.sync(project_of(tree))
    edit_item(tree, ids["market"], "# Market\n", "# Market, for clinics first\n")
    edit_item(tree, ids["market"], "do the market analysis.", "do the market analysis for clinics.")
    out = ops.sync(project_of(tree))["board"]
    assert out["edited"] == [ids["market"]]
    got = task(tree, ids["market"])
    assert got["title"] == "Market, for clinics first" and got["text"] == "do the market analysis for clinics."
    s, conn = store(tree)
    s.request_cancel(conn, ids["request"], by="user")  # the state changes in the store: the item is written again
    assert ops.sync(project_of(tree))["board"]["pushed"]
    text = item_file(tree, ids["market"]).read_text(encoding="utf-8")
    assert text.startswith("# Market, for clinics first\n") and "State: cancelled" in text


def test_a_failed_task_set_to_ready_on_the_board_is_retried(tree):
    ids = planned(tree)
    s, conn = store(tree)
    s.task_claim_next(conn)
    s.task_fail_running(conn, "the run was interrupted")
    ops.sync(project_of(tree))
    assert "State: failed" in item_file(tree, ids["market"]).read_text(encoding="utf-8")
    edit_item(tree, ids["market"], "State: failed", "State: ready")
    out = ops.sync(project_of(tree))["board"]
    assert out["refused"] == [] and task(tree, ids["market"])["state"] == "ready"


def test_a_request_cancelled_on_the_board_is_cancelled_with_what_is_open_under_it(tree):
    ids = planned(tree)
    ops.sync(project_of(tree))
    edit_item(tree, ids["request"], "State: planned", "State: cancelled")
    ops.sync(project_of(tree))
    assert [task(tree, i)["state"] for i in (ids["request"], ids["market"], ids["profile"])] == ["cancelled"] * 3
    assert "State: cancelled" in item_file(tree, ids["market"]).read_text(encoding="utf-8")


def test_a_review_set_to_done_on_the_board_is_released_and_a_question_is_not(tree):
    ids = planned(tree)
    project = project_of(tree)
    asked = ops.run_next(project)
    assert asked["ending"] == "question"
    ops.sync(project)
    edit_item(tree, ids["market"], "State: waiting", "State: done")
    out = ops.sync(project)["board"]
    assert [r["task"] for r in out["refused"]] == [ids["market"]] and task(tree, ids["market"])["state"] == "waiting"
    assert ops.pending(project, asked["pending_id"])["status"] == "open"
    assert "State: waiting" in item_file(tree, ids["market"]).read_text(encoding="utf-8")
    ops.answer(project, asked["pending_id"], "Clinics in Portugal.")
    delivered = ops.run_next(project)
    assert ops.pending(project, delivered["pending_id"])["kind"] == "review"
    ops.sync(project)
    edit_item(tree, ids["market"], "State: waiting", "State: done")
    out = ops.sync(project)["board"]
    assert out["refused"] == [] and task(tree, ids["market"])["state"] == "done"
    assert ops.pending(project, delivered["pending_id"])["resolved_by"] == "board"
    assert task(tree, ids["profile"])["state"] == "ready"


def test_a_state_change_the_table_does_not_list_is_refused_and_written_back(tree):
    ids = planned(tree)
    ops.sync(project_of(tree))
    edit_item(tree, ids["profile"], "State: planned", "State: done")
    out = ops.sync(project_of(tree))["board"]
    assert [(r["task"], r["state"]) for r in out["refused"]] == [(ids["profile"], "done")]
    assert task(tree, ids["profile"])["state"] == "planned" and ids["profile"] in out["pushed"]
    assert "State: planned" in item_file(tree, ids["profile"]).read_text(encoding="utf-8")


def test_an_item_a_person_wrote_on_the_board_waits_for_acceptance_and_cannot_be_routed_before_it(tree):
    project = project_of(tree)
    (tree["board"] / "blog-post.md").write_text("# Write the launch post\n\nFor the newsletter.\n", encoding="utf-8")
    out = ops.sync(project)["board"]
    assert len(out["created"]) == 1 and out["created"][0]["item"] == "blog-post"
    request, pending_id = out["created"][0]["request"], out["created"][0]["pending_id"]
    got = task(tree, request)
    assert (got["title"], got["text"], got["state"]) == ("Write the launch post", "For the newsletter.", "requested")
    assert ops.pending(project, pending_id)["kind"] == "acceptance"
    with pytest.raises(ops.OpsError):
        ops.route(project, request, flow="demo")
    assert ops.sync(project)["board"]["created"] == []  # the same item never makes a second request
    ops.approve(project, pending_id)
    assert ops.route(project, request, flow="demo")["routed"] is True


def test_a_comment_is_saved_once_and_enters_an_answer_only_on_the_persons_command(tree):
    ids = planned(tree)
    project = project_of(tree)
    asked = ops.run_next(project)
    ops.sync(project)
    edit_item(tree, ids["market"], "## Comments\n", "## Comments\n\n- Start with dental clinics.\n")
    synced = ops.sync(project)["board"]  # a comment does not move the version: listed, the item not read (WP-3.15)
    assert synced["pulled"] == [] and synced["comments"] == 1
    edit_item(tree, ids["market"], "do the market analysis.", "do the market analysis now.")
    ops.sync(project)
    s, conn = store(tree)
    saved = s.comments_list(conn, task_id=ids["market"])
    assert [c["text"] for c in saved] == ["Start with dental clinics."]
    assert ops.status(project)["requests"][0]["tasks"][0]["open_comments"] == 1
    plain = ops.answer(project, asked["pending_id"], "Clinics in Portugal.")
    assert "comments" not in plain and "dental" not in ops.pending(project, asked["pending_id"])["answer"]
    delivered = ops.run_next(project)
    out = ops.answer(project, delivered["pending_id"], "Narrow it.", with_comments=True)
    answer = ops.pending(project, delivered["pending_id"])["answer"]
    assert answer == "Narrow it.\n\nComments left on the platform:\n- unknown: Start with dental clinics."
    assert out["comments"] == [saved[0]["id"]] and s.comments_list(conn, task_id=ids["market"]) == []


def test_a_comment_added_on_an_unchanged_item_is_saved_by_the_next_pull(tree):
    # WP-3.15: on the live service a comment does not move an item's version (N3), and the local provider's version
    # leaves out the comments, so the item is not read; its comments are listed at every pull all the same.
    ids = planned(tree)
    project = project_of(tree)
    ops.sync(project)
    version = task(tree, ids["profile"])["remote_version"]
    edit_item(tree, ids["profile"], "## Comments\n", "## Comments\n\n- Keep it short.\n")
    out = ops.sync(project)["board"]
    assert out["pulled"] == [] and out["comments"] == 1 and task(tree, ids["profile"])["remote_version"] == version
    s, conn = store(tree)
    assert [c["text"] for c in s.comments_list(conn, task_id=ids["profile"])] == ["Keep it short."]
    assert ops.sync(project)["board"]["comments"] == 0  # saved once


def test_a_dry_run_reads_nothing_and_prints_every_write(tree):
    ids = planned(tree)
    (tree["board"] / "by-hand.md").write_text("# By hand\n\nA request.\n", encoding="utf-8")
    out = ops.sync(project_of(tree), dry_run=True)["board"]
    assert out["pulled"] == [] and out["created"] == [] and out["pushed"] == []
    assert sorted(w["task"] for w in out["would"]) == sorted(ids.values())
    assert all(w["dry_run"] is True and w["would"]["create"] is True for w in out["would"])
    assert items(tree) == ["by-hand.md"] and task(tree, ids["market"])["remote_id"] is None


def test_no_write_is_made_after_the_date_the_configuration_gives_or_under_an_unaccepted_hash(tree):
    project = project_of(tree)
    configure(tree, {"provider": "stub", "expires": "2020-01-31"})
    accept(project)
    ids = planned(tree)
    out = ops.sync(project)["board"]
    assert out["pushed"] == [] and sorted(f["task"] for f in out["failed"]) == sorted(ids.values())
    assert all("expired on 2020-01-31" in f["reason"] for f in out["failed"])
    calls = tree["stub_calls"].read_text().splitlines()
    assert calls and not any(c.startswith("upsert") for c in calls)
    configure(tree, {"provider": "stub", "expires": "2999-12-31"})
    with pytest.raises(ops.OpsError) as refused:
        ops.sync(project)
    assert refused.value.code == 3
    assert not any(c.startswith("upsert") for c in tree["stub_calls"].read_text().splitlines())
    accept(project)
    assert sorted(ops.sync(project)["board"]["pushed"]) == sorted(ids.values())
    assert sum(c.startswith("upsert") and "--confirmed" in c for c in tree["stub_calls"].read_text().splitlines()) == 3


def test_a_board_dir_inside_docs_or_inside_the_checkout_is_refused(tree):
    project = project_of(tree)
    for folder in (tree["project"] / "docs" / "board", tree["tree"] / "board"):
        folder.mkdir()
        configure(tree, {"provider": "local", "dir": str(folder)})
        with pytest.raises(ops.project_config.ConfigError) as refused:
            ops.project_config.load(project)
        assert "task_board.dir is inside" in str(refused.value)
        with pytest.raises(ops.OpsError) as e:
            ops.status(project)
        assert e.value.code == 3
    for board in ({"provider": "local", "dir": "board"}, {"provider": "nowhere"}, {"provider": "stub"},
                  {"provider": "stub", "expires": "soon"}):
        configure(tree, board)
        with pytest.raises(ops.project_config.ConfigError):
            ops.project_config.load(project)


def test_the_shown_fields_never_come_back_into_the_store(tree):
    ids = planned(tree)
    ops.sync(project_of(tree))
    edit_item(tree, ids["market"], "- skill: demo-asks", "- skill: demo-writes")
    edit_item(tree, ids["market"], "- note: ", "- note: written on the board")
    edit_item(tree, ids["market"], "- milestone: no", "- milestone: yes")
    out = ops.sync(project_of(tree))["board"]
    got = task(tree, ids["market"])
    assert out["pulled"] == [ids["market"]] and out["edited"] == [] and out["refused"] == []
    assert (got["skill"], got["note"], got["milestone"]) == ("demo-asks", None, 0)


def test_a_task_already_final_when_the_board_is_configured_is_never_mirrored_and_the_count_is_said(tree):
    # WP-3.17: the first sync of a real board made an item for every task of the store, those finished long before.
    project = project_of(tree)
    old = planned(tree)
    s, conn = store(tree)
    s.request_cancel(conn, old["request"], by="user")  # final before any sync: the request and its two tasks
    dry = ops.sync(project, dry_run=True)["board"]
    assert dry["left_out_final"] == 3 and s.cursor_get(conn, "board:configured") is None
    assert sorted(w["task"] for w in dry["would"]) == []
    assert ops.status(project)["board"] == {"left_out_final": 3}
    new = planned(tree)
    first = ops.sync(project)["board"]
    assert sorted(first["pushed"]) == sorted(new.values()) and first["left_out_final"] == 3
    assert s.cursor_get(conn, "board:configured") is not None and len(items(tree)) == 3
    assert all(task(tree, i)["remote_id"] is None for i in old.values())
    again = ops.sync(project)["board"]
    assert again["pushed"] == [] and again["left_out_final"] == 3 and len(items(tree)) == 3
    assert ops.status(project)["board"] == {"left_out_final": 3}


def test_a_task_that_becomes_final_after_the_board_is_configured_keeps_its_item_and_the_item_moves(tree):
    project = project_of(tree)
    first = planned(tree)
    assert ops.sync(project)["board"]["left_out_final"] == 0
    second = planned(tree)  # planned after the board was configured, and final before the next sync
    s, conn = store(tree)
    s.request_cancel(conn, first["request"], by="user")
    s.request_cancel(conn, second["request"], by="user")
    out = ops.sync(project)["board"]
    assert out["left_out_final"] == 0 and sorted(out["pushed"]) == sorted(list(first.values()) + list(second.values()))
    for task_id in list(first.values()) + list(second.values()):
        assert "State: cancelled" in item_file(tree, task_id).read_text(encoding="utf-8")
    assert len(items(tree)) == 6 and ops.status(project)["board"] == {"left_out_final": 0}


def test_status_says_nothing_of_a_board_when_none_is_configured(tree):
    project = project_of(tree)
    path = tree["project"] / "docs" / "workbench" / "runtime.json"
    cfg = json.loads(path.read_text(encoding="utf-8"))
    del cfg["task_board"]
    path.write_text(json.dumps(cfg), encoding="utf-8")
    accept(project)
    assert ops.status(project)["board"] is None
