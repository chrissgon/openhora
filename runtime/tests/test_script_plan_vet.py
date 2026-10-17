"""A project script is checked when the plan is built and again before the plan is approved (package P9, review finding M3): the
files its arguments name are read from the project, the hash compared and the credential scan made, so a sha256 written by hand
into a flow does not get to a person's approval unchecked. Offline; invented names only.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_script_plan_vet.py
"""
from __future__ import annotations

import hashlib

import pytest

import script_fixture as fx
import standin_tree as st
from test_ops_flows import new_request, ops, ops_core, pending, tasks_of, world, write_flow  # noqa: F401


@pytest.fixture(autouse=True)
def installed(world):
    """The files that define the script image sit in the stand-in tree: the plan's `image` argument is their hash."""
    fx.install(world["tree"])


def flow(world, sha, lock=None, lock_sha=None, image=None):
    args = {"script": "scripts/report.py", "sha256": sha, "source": "report", "image": image or fx.image(world["tree"]), "destinations": []}
    if lock:
        args.update(lock=lock, lock_sha256=lock_sha)
    return {"flow": "weekly-report", "title": "A weekly report", "params": {},
            "tasks": [{"key": "report", "step": "project-script", "title": "Run the report script", "text": "Run it.", "args": args}]}


def sha_of(text):
    return hashlib.sha256(text.encode()).hexdigest()


def test_a_plan_with_the_right_hash_opens_and_is_approved(world):
    fx.write(world["project"], "scripts/report.py", "# fake: md=Hi\n")
    write_flow(world, "weekly-report", flow(world, sha_of("# fake: md=Hi\n")))
    opened = ops.route(world["path"], new_request(world), flow="weekly-report")
    shown = pending(world, opened["pending_id"])
    assert shown["payload"]["tasks"][0]["args"]["sha256"] == sha_of("# fake: md=Hi\n")
    assert ops.approve(world["path"], opened["pending_id"], shown["payload"]["plan_sha256"], channel="terminal")["tasks"]


def test_a_hash_written_by_hand_that_is_not_the_files_opens_no_plan(world):
    fx.write(world["project"], "scripts/report.py", "# fake: md=Hi\n")
    write_flow(world, "weekly-report", flow(world, "a" * 64))
    with pytest.raises(ops.OpsError) as refused:
        ops.route(world["path"], new_request(world), flow="weekly-report")
    assert "no plan can be built" in str(refused.value) and "script_changed" in str(refused.value) and "report" in str(refused.value)


def test_a_script_with_a_credential_opens_no_plan_even_when_its_hash_is_right_and_the_value_is_never_shown(world):
    secret = "AKIA" + "Q" * 16
    text = f"# fake: md=Hi\nKEY = '{secret}'\n"
    fx.write(world["project"], "scripts/report.py", text)
    write_flow(world, "weekly-report", flow(world, sha_of(text)))
    with pytest.raises(ops.OpsError) as refused:
        ops.route(world["path"], new_request(world), flow="weekly-report")
    assert "script_has_credential line_2" in str(refused.value) and secret not in str(refused.value)


def test_a_lock_file_with_a_loose_requirement_opens_no_plan(world):
    fx.write(world["project"], "scripts/report.py", "# fake: md=Hi\n")
    fx.write(world["project"], "scripts/requirements.lock", "requests>=2\n")
    write_flow(world, "weekly-report", flow(world, sha_of("# fake: md=Hi\n"), "scripts/requirements.lock", sha_of("requests>=2\n")))
    with pytest.raises(ops.OpsError) as refused:
        ops.route(world["path"], new_request(world), flow="weekly-report")
    assert "bad_lock" in str(refused.value)


def test_a_script_changed_after_the_plan_was_opened_is_not_approved(world):
    fx.write(world["project"], "scripts/report.py", "# fake: md=Hi\n")
    write_flow(world, "weekly-report", flow(world, sha_of("# fake: md=Hi\n")))
    rid = new_request(world)
    opened = ops.route(world["path"], rid, flow="weekly-report")
    fx.write(world["project"], "scripts/report.py", "# fake: md=Another script\n")
    with pytest.raises(ops.OpsError) as refused:
        ops.approve(world["path"], opened["pending_id"], pending(world, opened["pending_id"])["payload"]["plan_sha256"], channel="terminal")
    assert "nothing was approved" in str(refused.value) and "script_changed" in str(refused.value)
    assert tasks_of(world, rid) == {} and pending(world, opened["pending_id"])["status"] == "open"


def test_limit_36_a_plan_that_holds_a_networked_step_is_approved_only_from_the_terminal_or_the_page(world):
    ops_waits = st.load("ops_waits")
    fx.write(world["project"], "scripts/report.py", "# fake: md=Hi\n")
    write_flow(world, "weekly-report", flow(world, sha_of("# fake: md=Hi\n")))
    rid = new_request(world)
    opened = ops.route(world["path"], rid, flow="weekly-report")
    item = pending(world, opened["pending_id"])
    digest = item["payload"]["plan_sha256"]
    assert ops_waits.networked_steps(item) == [("report", "project-script")]
    for channel in ("messaging", "mcp", "chat", "bogus", None):          # no channel at all fails closed too
        with pytest.raises(ops.OpsError) as refused:
            ops.approve(world["path"], opened["pending_id"], digest, channel=channel, sender=("telegram:4242" if channel == "messaging" else None))
        assert "terminal or on the page by default" in str(refused.value) and "Nothing was approved" in str(refused.value) and "report" in str(refused.value)
    # whatever the messaging policy grants: the rule is before the policy
    generous = {"messaging": ["read", "approve-plans", "go-ahead"]}
    with pytest.raises(ops.OpsError) as refused:
        ops_waits.only_on_plans(item, None, digest, "messaging", generous)
    assert "terminal or on the page" in str(refused.value)
    assert tasks_of(world, rid) == {} and pending(world, opened["pending_id"])["status"] == "open"
    assert st.load("operations").NETWORKED_PLAN_CHANNELS == ("terminal", "page"), "the default set is one named literal"
    assert ops.approve(world["path"], opened["pending_id"], digest, channel="page")["tasks"]       # the page approves it
    assert "report" in tasks_of(world, rid)


def test_a_plan_with_no_networked_step_is_still_approved_from_messaging_with_its_hash(world):
    ops_waits = st.load("ops_waits")
    item = {"id": 1, "kind": "plan", "payload": {"tasks": [{"key": "pull", "step": "ingest", "args": {"source": "s"}}, {"key": "think", "skill": "x"}]}}
    assert ops_waits.networked_steps(item) == []
    ops_waits.only_on_plans(item, None, "a" * 64, "messaging", {"messaging": ["read", "approve-plans"]})
    unknown = {"id": 2, "kind": "plan", "payload": {"tasks": [{"key": "odd", "step": "no-such-kind", "args": {}}]}}
    assert ops_waits.networked_steps(unknown) == [("odd", "no-such-kind")], "a kind that cannot be shown not to reach the network counts"
