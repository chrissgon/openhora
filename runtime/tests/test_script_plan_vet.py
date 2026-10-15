"""A project script is checked when the plan is built and again before the plan is approved (package P9, review finding M3): the
files its arguments name are read from the project, the hash compared and the credential scan made, so a sha256 written by hand
into a workflow does not get to a person's approval unchecked. Offline; invented names only.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_script_plan_vet.py
"""
from __future__ import annotations

import hashlib

import pytest

import script_fixture as fx
from test_ops_flows import new_request, ops, ops_core, pending, tasks_of, world, write_flow  # noqa: F401


def flow(sha, lock=None, lock_sha=None):
    args = {"script": "scripts/report.py", "sha256": sha, "source": "report", "destinations": []}
    if lock:
        args.update(lock=lock, lock_sha256=lock_sha)
    return {"flow": "weekly-report", "title": "A weekly report", "params": {},
            "tasks": [{"key": "report", "step": "project-script", "title": "Run the report script", "text": "Run it.", "args": args}]}


def sha_of(text):
    return hashlib.sha256(text.encode()).hexdigest()


def test_a_plan_with_the_right_hash_opens_and_is_approved(world):
    fx.write(world["project"], "scripts/report.py", "# fake: md=Hi\n")
    write_flow(world, "weekly-report", flow(sha_of("# fake: md=Hi\n")))
    opened = ops.route(world["path"], new_request(world), flow="weekly-report")
    shown = pending(world, opened["pending_id"])
    assert shown["payload"]["tasks"][0]["args"]["sha256"] == sha_of("# fake: md=Hi\n")
    assert ops.approve(world["path"], opened["pending_id"], shown["payload"]["plan_sha256"])["tasks"]


def test_a_hash_written_by_hand_that_is_not_the_files_opens_no_plan(world):
    fx.write(world["project"], "scripts/report.py", "# fake: md=Hi\n")
    write_flow(world, "weekly-report", flow("a" * 64))
    with pytest.raises(ops.OpsError) as refused:
        ops.route(world["path"], new_request(world), flow="weekly-report")
    assert "no plan can be built" in str(refused.value) and "script_changed" in str(refused.value) and "report" in str(refused.value)


def test_a_script_with_a_credential_opens_no_plan_even_when_its_hash_is_right_and_the_value_is_never_shown(world):
    secret = "AKIA" + "Q" * 16
    text = f"# fake: md=Hi\nKEY = '{secret}'\n"
    fx.write(world["project"], "scripts/report.py", text)
    write_flow(world, "weekly-report", flow(sha_of(text)))
    with pytest.raises(ops.OpsError) as refused:
        ops.route(world["path"], new_request(world), flow="weekly-report")
    assert "script_has_credential line_2" in str(refused.value) and secret not in str(refused.value)


def test_a_lock_file_with_a_loose_requirement_opens_no_plan(world):
    fx.write(world["project"], "scripts/report.py", "# fake: md=Hi\n")
    fx.write(world["project"], "scripts/requirements.lock", "requests>=2\n")
    write_flow(world, "weekly-report", flow(sha_of("# fake: md=Hi\n"), "scripts/requirements.lock", sha_of("requests>=2\n")))
    with pytest.raises(ops.OpsError) as refused:
        ops.route(world["path"], new_request(world), flow="weekly-report")
    assert "bad_lock" in str(refused.value)


def test_a_script_changed_after_the_plan_was_opened_is_not_approved(world):
    fx.write(world["project"], "scripts/report.py", "# fake: md=Hi\n")
    write_flow(world, "weekly-report", flow(sha_of("# fake: md=Hi\n")))
    rid = new_request(world)
    opened = ops.route(world["path"], rid, flow="weekly-report")
    fx.write(world["project"], "scripts/report.py", "# fake: md=Another script\n")
    with pytest.raises(ops.OpsError) as refused:
        ops.approve(world["path"], opened["pending_id"], pending(world, opened["pending_id"])["payload"]["plan_sha256"])
    assert "nothing was approved" in str(refused.value) and "script_changed" in str(refused.value)
    assert tasks_of(world, rid) == {} and pending(world, opened["pending_id"])["status"] == "open"
