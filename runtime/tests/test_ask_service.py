"""The page asks (package AQ-1): `POST /projects/{p}/ask` on the local service over the real operations layer and the stand-in tree. The route is a
job (its row calls a model), the page's policy refuses it before a job exists when it does not list the group `ask`, and the permissions the
page reads list `ask` unless the policy narrows it. No model is called; every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_ask_service.py
"""
from __future__ import annotations

import json

import pytest

import standin_tree as st
from test_ask import accept, ops, runs, tree, two  # noqa: F401  (the ask tree and its two sources)
from test_service import run_serve, service
from test_service_conversation import Page


@pytest.fixture
def served(two, monkeypatch):
    monkeypatch.setattr(service, "QUEUE_EVERY", 0.1)
    run = run_serve(ops, [two["path"]], service.Server, dispatch_every=None, token_file=str(two["data"] / "service.token"))
    try:
        yield Page(run, two["project"]), two, run
    finally:
        assert run.finish() == 0


def test_the_page_asks_through_a_job_and_the_answer_is_the_jobs_result(served):
    page, tree, run = served
    done = page.job("/ask", {"text": "qual o prazo do contrato?"})
    assert done["state"] == "done" and done["result"]["ran"] is True and done["result"]["answer"] == "found"
    assert "Read: lease-contract (version 1), meeting-notes (version 1)" in done["result"]["reply"]
    assert len(runs(tree)) == 1
    status, listed = page.json("GET", "/pending")
    assert status == 200 and listed["pending"] == []
    assert page.json("POST", "/ask", {})[0] == 400                                       # no text: a usage error, and no job
    assert len(runs(tree)) == 1


def test_a_page_policy_without_the_group_ask_refuses_the_route_before_a_job_exists(served):
    page, tree, run = served
    accept(tree["path"], channels={"page": ["read", "talk"]})
    status, body = page.json("POST", "/ask", {"text": "qual o prazo do contrato?"})
    assert status == 409 and "is not enabled for this channel" in json.dumps(body) and "channels.page" in json.dumps(body)
    assert runs(tree) == [] and st.calls(tree["adapter"]) == []
    accept(tree["path"], channels={"page": ["read", "talk", "ask"]})                      # a policy that names it again
    assert page.job("/ask", {"text": "qual o prazo do contrato?"})["result"]["ran"] is True


def test_the_permissions_the_page_reads_list_ask_unless_its_policy_narrows_it(served):
    page, tree, run = served
    assert page.call("GET", "/status")[0] == 200
    assert "ask" in ops.operations.permissions("page", ops.config(tree["path"]).get("channels"))
    accept(tree["path"], channels={"page": ["read", "talk"]})
    assert "ask" not in ops.operations.permissions("page", ops.config(tree["path"]).get("channels"))
