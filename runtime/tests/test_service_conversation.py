"""Integration tests of the local service with the real operations layer (ADJ-R2): a project on the stand-in tree
(standin_tree.py), the service started by `serve` on a loopback port with no dispatch (`--no-dispatch`), a stand-in router,
and a stand-in that holds the project's run lock the way a task's run does. What a person on the page does is done
with HTTP requests: a line typed while a run holds the project is queued and answered when it ends, a question about
the state is answered by code, a request made during a run is routed after it, an image of the project is served as
bytes. No model is called.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_service_conversation.py
"""
from __future__ import annotations

import http.client
import json
import os
import struct
import time

import pytest

import standin_tree as st
from test_chat import FLOW, reply, tree  # noqa: F401  (the conversation's stand-in project and router)
from test_service import WAIT, run_serve, service

ops = st.load("ops")
ops_core = st.load("ops_core")

PNG = b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + b"\x00" * 40
DIRECT = "Route: none (direct)\nWhy: no skill is needed.\nNext: Ask for the market analysis by name.\n"


class Page:
    """What the page does: one HTTP request at a time, with the token the service wrote."""

    def __init__(self, run, project):
        self.run, self.port = run, run.service.port
        self.token = open(json.loads(run.out.getvalue())["token_file"], encoding="utf-8").read().strip()
        self.base = f"/api/v1/projects/{service.project_id(str(project))}"

    def call(self, method, path, body=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=WAIT)
        headers = {"Authorization": f"Bearer {self.token}"}
        data = None
        if method == "POST":
            data = json.dumps(body or {}).encode("utf-8")
            headers.update({"Origin": f"http://127.0.0.1:{self.port}", "Content-Type": "application/json"})
        connection.request(method, self.base + path, body=data, headers=headers)
        answer = connection.getresponse()
        payload = answer.read()
        out = (answer.status, dict(answer.getheaders()), payload)
        connection.close()
        return out

    def json(self, method, path, body=None):
        status, headers, payload = self.call(method, path, body)
        return status, json.loads(payload)

    def job(self, path, body=None):
        """POST a route that returns a job, and the job when it ends."""
        status, job = self.json("POST", path, body)
        assert status == 202, (status, job)
        deadline = time.monotonic() + WAIT
        while time.monotonic() < deadline:
            _status, shown = self.job_state(job["job"])
            if shown["state"] != "running":
                return shown
            time.sleep(0.02)
        raise AssertionError("the job did not end")

    def job_state(self, number):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=WAIT)
        connection.request("GET", f"/api/v1/jobs/{number}", headers={"Authorization": f"Bearer {self.token}"})
        answer = connection.getresponse()
        out = answer.status, json.loads(answer.read())
        connection.close()
        return out

    def messages(self):
        return self.json("GET", "/conversation")[1]["messages"]


@pytest.fixture
def served(tree, monkeypatch):
    monkeypatch.setattr(service, "QUEUE_EVERY", 0.1)
    run = run_serve(ops, [str(tree["project"])], service.Server, dispatch_every=None,
                    token_file=str(tree["data"] / "service.token"))
    try:
        yield Page(run, tree["project"]), tree, run
    finally:
        assert run.finish() == 0


def wait_for(check, what):
    deadline = time.monotonic() + WAIT
    while time.monotonic() < deadline:
        found = check()
        if found:
            return found
        time.sleep(0.05)
    raise AssertionError(f"never happened: {what}")


def test_a_line_typed_during_a_run_is_queued_and_the_service_answers_it_when_the_run_ends(served):
    page, tree, run = served
    lock = ops_core._run_lock(ops.project_config.load(str(tree["project"])))
    with lock:                                               # a task's run holds the project
        done = page.job("/conversation", {"text": "Which market should the invented studio go after first?"})
        assert done["state"] == "done" and done["result"]["queued"] is True and done["result"]["reply"] is None
        [line] = page.messages()
        assert (line["role"], line["queued"], line["task_id"]) == ("user", True, None)
        time.sleep(0.4)                                      # several rounds of the queue loop: the lock is still held
        assert st.calls(tree["adapter"]) == [] and [m["queued"] for m in page.messages()] == [True]
    answered = wait_for(lambda: [m for m in page.messages() if m["role"] == "assistant"], "the reply of the queued line")
    assert "Estimate: 4 runs" in answered[0]["text"] and answered[0]["task_id"]
    assert [m["queued"] for m in page.messages()] == [False, False]
    assert st.calls(tree["adapter"]) == ["core-orchestrator 1"]
    status, pending = page.json("GET", "/pending")
    assert status == 200 and [p["kind"] for p in pending["pending"]] == ["plan"]


def test_a_question_about_the_state_is_answered_at_once_during_a_run_with_no_model_and_no_request(served):
    page, tree, run = served
    ops.request(str(tree["project"]), "Find the first market.", flow="demo")
    with ops_core._run_lock(ops.project_config.load(str(tree["project"]))):
        done = page.job("/conversation", {"text": "Como estamos com o projeto?"})
        result = done["result"]
        assert result["queued"] is False and result["ran"] is False and result["request_id"] is None
        assert result["reply"].startswith('Request 1, "Demo flow": 0 of 2 tasks done.')
        assert "What waits for you: nothing." in result["reply"]
        assert [(m["role"], m["queued"]) for m in page.messages()] == [("user", False), ("assistant", False)]
    assert st.calls(tree["adapter"]) == []
    status, shown = page.json("GET", "/status")
    assert [r["id"] for r in shown["requests"]] == [1]       # the question made no request


def test_a_request_made_during_a_run_is_recorded_and_routed_when_the_run_ends(served):
    page, tree, run = served
    request = page.json("POST", "/requests", {"text": "Which market first?"})[1]["request"]
    with ops_core._run_lock(ops.project_config.load(str(tree["project"]))):
        done = page.job(f"/requests/{request}/route")
        assert done["state"] == "done" and done["result"]["queued"] is True and done["result"]["routed"] is False
        assert page.json("GET", "/pending")[1]["pending"] == []
        # a flow the person names takes no run lock: it is opened at once, during the run
        other = page.json("POST", "/requests", {"text": "Another."})[1]["request"]
        named = page.job(f"/requests/{other}/route", {"flow": "demo"})
        assert named["state"] == "done" and named["result"]["routed"] is True and named["result"]["source"] == "named"
    plans = wait_for(lambda: [p for p in page.json("GET", "/pending")[1]["pending"] if p["task_id"] == request], "the queued route")
    assert plans[0]["kind"] == "plan" and st.calls(tree["adapter"]) == ["core-orchestrator 1"]


def test_a_direct_reply_to_a_line_is_answered_by_code_through_the_service(served):
    page, tree, run = served
    reply(tree, DIRECT)
    result = page.job("/conversation", {"text": "Tell me about the studio."})["result"]
    assert result["queued"] is False and result["request_id"] is None and result["pending_id"] is None
    assert result["reply"].endswith("The planning agent proposes: Ask for the market analysis by name.")
    assert page.json("GET", "/pending")[1]["pending"] == []
    assert [r["state"] for r in page.json("GET", "/status")[1]["requests"]] == ["cancelled"]


def test_an_image_of_the_project_is_listed_as_an_image_and_served_as_bytes(served):
    page, tree, run = served
    folder = tree["project"] / "docs" / "brand" / "pieces"
    folder.mkdir(parents=True)
    (folder / "github-readme-banner-accent.png").write_bytes(PNG)
    (folder / "notes.md").write_text("# Notes\n", encoding="utf-8")
    (folder / "inter.woff2").write_bytes(b"wOF2" + b"\x00" * 16)
    listed = {a["path"].rsplit("/", 1)[1]: a["kind"] for a in page.json("GET", "/artifacts")[1]["artifacts"]}
    assert listed == {"github-readme-banner-accent.png": "image", "notes.md": "markdown", "inter.woff2": "other"}
    status, headers, body = page.call("GET", "/artifact/raw?path=docs/brand/pieces/github-readme-banner-accent.png")
    assert (status, body) == (200, PNG) and headers["Content-Type"] == "image/png"
    assert headers["Cache-Control"] == "no-store" and headers["X-Content-Type-Options"] == "nosniff"
    assert headers["Content-Disposition"] == "inline" and headers["Content-Security-Policy"] == service.CSP
    status, headers, body = page.call("GET", "/artifact/raw?path=docs/brand/pieces/inter.woff2")
    assert status == 400 and "a woff2 font" in json.loads(body)["message"]
    assert page.call("GET", "/artifact/raw?path=docs/../AGENTS.md")[0] == 400
    assert page.call("GET", "/artifact?path=docs/brand/pieces/github-readme-banner-accent.png")[0] == 400   # the text read refuses it
