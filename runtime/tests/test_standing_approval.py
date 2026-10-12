"""Tests of the standing approval of a policy (stage 6, WP-6.4): a row of the store's approvals table, bound to its
file by hash and with an expiry, and its generated row in the state file, the row the engagement gate reads. The
stand-in tree, a bounds file with invented names and an .example-style repository name.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_standing_approval.py
"""
from __future__ import annotations

import datetime
import hashlib
import importlib.util
import json
import re
import shutil

import pytest

import standin_tree as st

autonomy = st.load("autonomy")
lab = st.load("lab")
ops = st.load("ops")
ops_core = st.load("ops_core")
cli = st.load("cli")

POLICY = "docs/workbench/policies/published-posts.json"
BOUNDS = {"policy": "published-posts", "agent": "marketing", "effects": ["push"],
          "targets": ["example-owner/example-profile@main"], "files": ["data/posts.json", "assets/posts/*"],
          "max_per_day": 1, "max_items_per_run": 10}
SESSION_ROW = "| action | a reply sent by hand | sha256:" + "1" * 64 + " | 2026-10-01 | after execution | executed |"


def ahead(days: int) -> str:
    return (datetime.date.today() + datetime.timedelta(days=days)).isoformat()


@pytest.fixture
def tree(tmp_path, monkeypatch):
    built = st.build(tmp_path, monkeypatch, lab)
    monkeypatch.setattr(ops_core, "ROOT", str(built["tree"]))
    (built["tree"] / "scripts").mkdir(exist_ok=True)  # the one source of the vocabulary of side effects
    shutil.copyfile(st.REPO / "scripts" / "validate.py", built["tree"] / "scripts" / "validate.py")
    project = built["project"]
    config = project / "docs" / "workbench" / "runtime.json"
    data = json.loads(config.read_text())
    data["area_agents"] = {"planning": {"pack": "planning"},
                           "marketing": {"pack": "brand", "mode": "autonomous-with-policy"}}
    config.write_text(json.dumps(data))
    (project / "docs" / "workbench" / "policies").mkdir()
    (project / POLICY).write_text(json.dumps(BOUNDS, indent=2) + "\n")
    state = project / "docs" / "workbench" / "state.md"
    state.write_text(state.read_text().replace("|-------|------|--------------|----------|---------|--------|\n",
                                               "|-------|------|--------------|----------|---------|--------|\n"
                                               + SESSION_ROW + "\n"))
    ops.accept_config(str(project), ops.project_config.load(str(project))["sha256"])
    return built


def project_of(tree) -> str:
    return str(tree["project"])


def state_of(tree) -> str:
    return (tree["project"] / "docs" / "workbench" / "state.md").read_text()


def file_hash(tree) -> str:
    return hashlib.sha256((tree["project"] / POLICY).read_bytes()).hexdigest()


def approved(tree, days: int = 30) -> dict:
    return ops.approve_policy(project_of(tree), POLICY, "marketing", file_hash(tree), ahead(days))


def test_a_preview_shows_the_hash_and_writes_nothing(tree):
    before = state_of(tree)
    out = ops.approve_policy(project_of(tree), POLICY, "marketing")
    assert out["sha256"] == file_hash(tree) and out["policy"] == "published-posts" and out["agent"] == "marketing"
    assert out["bounds"] == dict(BOUNDS, file=POLICY) and out["sha256"] in out["next"]
    assert state_of(tree) == before
    assert ops_core.store_module().approvals_list(ops_core.store_module().open_db(str(tree["db"]))) == []
    for file, agent in (("../outside.json", "marketing"), ("AGENTS.md", "marketing"), (POLICY, "nobody"),
                        ("docs/workbench/policies/missing.json", "marketing")):
        with pytest.raises(ops.OpsError) as refused:
            ops.approve_policy(project_of(tree), file, agent)
        assert refused.value.code == 2, file
    (tree["project"] / POLICY).write_text(json.dumps(dict(BOUNDS, agent="planning")))
    with pytest.raises(ops.OpsError) as refused:
        ops.approve_policy(project_of(tree), POLICY, "marketing")
    assert refused.value.code == 2 and "agent" in str(refused.value)
    (tree["project"] / POLICY).write_text(json.dumps(dict(BOUNDS, colour="red")))
    with pytest.raises(ops.OpsError) as refused:
        ops.approve_policy(project_of(tree), POLICY, "marketing")
    assert "colour" in str(refused.value)
    (tree["project"] / POLICY).write_text(json.dumps(dict(BOUNDS, effects=["teleport"])))
    with pytest.raises(ops.OpsError) as refused:
        ops.approve_policy(project_of(tree), POLICY, "marketing")
    assert "effects" in str(refused.value) and "publish" in str(refused.value)


def test_an_approval_needs_the_hash_shown_and_a_future_expiry(tree):
    digest = file_hash(tree)
    for expires in (None, "soon", datetime.date.today().isoformat(), ahead(-1), ahead(366)):
        with pytest.raises(ops.OpsError) as refused:
            ops.approve_policy(project_of(tree), POLICY, "marketing", digest, expires)
        assert refused.value.code == 1 and "expires" in str(refused.value), expires
    out = approved(tree, 365)
    assert out["status"] == "active" and out["scope"] == "standing" and out["policy_sha256"] == digest
    assert out["expires_at"].startswith(ahead(365)) and out["approved_by"] == "user"


def test_a_changed_file_is_refused_with_the_hash_that_was_shown(tree):
    shown = ops.approve_policy(project_of(tree), POLICY, "marketing")["sha256"]
    (tree["project"] / POLICY).write_text(json.dumps(dict(BOUNDS, max_per_day=5)))
    with pytest.raises(ops.OpsError) as refused:
        ops.approve_policy(project_of(tree), POLICY, "marketing", shown, ahead(30))
    assert refused.value.code == 1 and shown in str(refused.value) and file_hash(tree) in str(refused.value)
    assert "runtime #" not in state_of(tree)


def test_a_new_approval_of_a_policy_revokes_the_earlier_one(tree):
    first = approved(tree)
    (tree["project"] / POLICY).write_text(json.dumps(dict(BOUNDS, max_items_per_run=5)))
    second = approved(tree)
    assert second["revoked"] == [first["id"]]
    conn = ops_core.store_module().open_db(str(tree["db"]))
    rows = ops_core.store_module().approvals_list(conn, scope="standing")
    assert [(r["id"], r["status"]) for r in rows] == [(first["id"], "revoked"), (second["id"], "active")]
    state = state_of(tree)
    assert f"(runtime #{second['id']})" in state and f"(runtime #{first['id']})" not in state


def test_the_state_file_row_is_generated_and_a_row_a_session_wrote_is_left_alone(tree):
    digest = file_hash(tree)
    state = tree["project"] / "docs" / "workbench" / "state.md"
    by_hand = f"| standing | the posts policy, approved in a session | policy:{digest} | 2026-10-01 | 2026-12-01 | active |"
    state.write_text(state.read_text().replace(SESSION_ROW, SESSION_ROW + "\n" + by_hand))
    out = approved(tree)
    assert out["state_rows"] == 1 and out["superseded_rows"] == 1
    text = state_of(tree)
    assert SESSION_ROW in text and by_hand not in text
    generated = [line for line in text.splitlines() if "runtime #" in line]
    assert generated == [f"| standing | published-posts (runtime #{out['id']}) | policy:{digest} | "
                         f"{out['approved_at'][:10]} | {ahead(30)} | active |"]
    again = ops.approve_policy(project_of(tree), POLICY, "marketing", digest, ahead(40), "weekly posts")
    assert [line for line in state_of(tree).splitlines() if "runtime #" in line] == [
        f"| standing | weekly posts (runtime #{again['id']}) | policy:{digest} | {again['approved_at'][:10]} | "
        f"{ahead(40)} | active |"]
    assert SESSION_ROW in state_of(tree)


def gate():
    path = st.REPO / "skills" / "mkt-engage" / "scripts" / "policy_gate.py"
    spec = importlib.util.spec_from_file_location("engage_policy_gate", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_generated_row_is_the_row_the_engagement_gate_reads(tree):
    out = approved(tree)
    policy_gate = gate()
    row = policy_gate.standing_row(tree["project"] / "docs" / "workbench" / "state.md", file_hash(tree))
    assert row is not None and row["status"] == "active" and row["what"].endswith(f"(runtime #{out['id']})")
    assert policy_gate.parse_time(row["expires"]) > datetime.datetime.now(datetime.timezone.utc)


def test_an_edited_bounds_file_is_not_covered(tree):
    approved(tree)
    assert ops.standing(project_of(tree), "published-posts")["covered"] is True
    (tree["project"] / POLICY).write_text(json.dumps(dict(BOUNDS, targets=["example-owner/another@main"])))
    out = ops.standing(project_of(tree), "published-posts")
    assert out["covered"] is False and "changed" in out["why"]


def test_an_expired_approval_is_shown_expired_and_covers_nothing(tree):
    out = approved(tree)
    store = ops_core.store_module()
    conn = store.open_db(str(tree["db"]))
    later = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=31)).isoformat()
    assert store.approvals_expire(conn, later) == 1
    written = ops._standing_rows(ops_core.context(project_of(tree)))
    assert written["state_rows"] == 1
    assert re.search(rf"\(runtime #{out['id']}\) \| policy:\w+ \| [\d-]+ \| [\d-]+ \| expired \|", state_of(tree))
    row = gate().standing_row(tree["project"] / "docs" / "workbench" / "state.md", file_hash(tree))
    assert row["status"] == "expired"
    covered = ops.standing(project_of(tree), "published-posts")
    assert covered["covered"] is False and covered["approval"] is None
    approval = store.approval_get(conn, out["id"])
    assert autonomy.covers(approval, file_hash(tree), {"kind": "push", "target": BOUNDS["targets"][0],
                                                       "files": ["data/posts.json"], "items": 1}, 0,
                           datetime.datetime.now(datetime.timezone.utc))[0] is False


def test_only_the_policy_mode_makes_an_approval_cover(tree, capsys):
    project = project_of(tree)
    approved(tree)
    covered = ops.standing(project, "published-posts")
    assert covered["covered"] is True and covered["mode"] == "autonomous-with-policy" and covered["executed_today"] == 0
    assert covered["approval"]["agent"] == "marketing"
    for mode in ("autonomous", "milestones", "supervised", "stopped"):
        changed = ops.set_mode(project, "marketing", mode)
        ops.accept_config(project, changed["config_sha256"])
        out = ops.standing(project, "published-posts")
        assert out["covered"] is False and out["mode"] == mode and mode in out["why"], mode
    assert cli.main(["standing", "--project", project, "--policy", "published-posts"]) == 0
    assert json.loads(capsys.readouterr().out)["covered"] is False
    assert ops.standing(project, "no-such-policy")["covered"] is False


def test_revoking_removes_the_row_from_the_state_file(tree, capsys):
    project = project_of(tree)
    out = approved(tree)
    assert f"(runtime #{out['id']})" in state_of(tree)
    assert cli.main(["revoke-policy", "--project", project, "--id", str(out["id"])]) == 0
    revoked = json.loads(capsys.readouterr().out)
    assert revoked["status"] == "revoked" and revoked["state_rows"] == 0
    assert "runtime #" not in state_of(tree) and SESSION_ROW in state_of(tree)
    assert ops.standing(project, "published-posts")["covered"] is False
    with pytest.raises(ops.OpsError) as refused:
        ops.revoke_policy(project, out["id"])
    assert refused.value.code == 2
