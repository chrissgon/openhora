"""Who may start the media pipeline and read or change the caption review: the terminal and the loopback page, never the MCP mode
or the messaging bridge, never the LAN socket; and what the page can never do (build an image, fetch a model, accept a
configuration, give a time). The operations layer is the real one over the stand-in tree of test_media_pipeline.py.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_media_pipeline_channels.py
"""
from __future__ import annotations

import json
import time
import types

import pytest

import pipeline_kit as kit
import standin_tree as st
from test_channel_policy import sentence, set_channels
from test_media_pipeline import make_world
from test_service import PORT, TOKEN

ops = st.load("ops")
operations = st.load("operations")
service = st.load("service")
mcp = st.load("mcp")
media = st.load("media")

LAN = "192.168.1.20"
NAMES = ("media-pipeline", "captions-read", "captions-edit", "captions-done", "prepare-again")


@pytest.fixture
def world(tmp_path, monkeypatch):
    made = make_world(tmp_path, monkeypatch)
    pid = service.project_id(made.project)
    svc = service.Service(ops, [{"id": pid, "name": "p", "path": made.project}], TOKEN, PORT, None, log=lambda line: None)
    return types.SimpleNamespace(made=made, svc=svc, pid=pid, base=f"/api/v1/projects/{pid}/media/{made.rid}")


def request(world, method, path, body=None, *, lan=False, host=None, origin="default", token=True):
    data = json.dumps(body).encode("utf-8") if body is not None else b""
    host = host or f"127.0.0.1:{PORT}"
    headers = {"Host": host}
    if origin == "default":
        origin = f"http://{host}" if method == "POST" else None
    if origin:
        headers["Origin"] = origin
    if token:
        headers["Authorization"] = f"Bearer {TOKEN}"
    if method == "POST":
        headers.update({"Content-Type": "application/json", "Content-Length": str(len(data))})
    status, _, payload = service.handle(world.svc, method, path, headers, data, lan=lan)
    return status, payload


def answer(payload):
    return json.loads(payload)


def wait_job(world, number):
    deadline = time.monotonic() + 60
    while True:
        status, payload = request(world, "GET", f"/api/v1/jobs/{number}")
        job = answer(payload)
        if job["state"] != "running" or time.monotonic() > deadline:
            return job
        time.sleep(0.02)


def go_to_review(world):
    return ops.media_pipeline(world.made.project, world.made.rid, post=kit.POST_PATH)


# --- the table: terminal and page, nothing else ------------------------------------------------------------------------------------------


def test_the_pipeline_and_the_caption_review_are_for_the_terminal_and_the_page_and_no_other_channel():
    for name in NAMES:
        row = operations.by_name(name)
        assert row["channels"] == ("terminal", "page") and row["model"] is False, name
        for channel in ("mcp", "messaging", "chat"):
            assert not operations.permitted(name, channel, None), (name, channel)
            assert operations.refusal(name, channel, {channel: ["read", "talk", "answer", "release", "request", "media", "dispatch"]}) == sentence(name, channel), (name, channel)
        assert name in operations.GROUPS["media"]["operations"] and sum(name in g["operations"] for g in operations.GROUPS.values()) == 1
    assert operations.by_name("captions-read") in [r for r in operations.OPERATIONS if "page" in r["channels"]]
    assert not set(NAMES) & {r["name"] for r in mcp.operation_rows(ops)}, "a model client has no tool that reads the person's words"
    assert set(NAMES) <= set(operations.terminal_verbs())
    assert not set(NAMES) & set(operations.chat_commands() and [c["name"] for c in operations.chat_commands()])


def test_the_page_may_run_them_only_with_the_media_group_and_a_policy_without_it_is_a_409_before_a_job_exists(world):
    go_to_review(world)
    set_channels(world.made.project, {"page": ["read", "talk"]})
    for method, tail, body in (("POST", "/pipeline", {"post": kit.POST_PATH}), ("GET", "/captions", None),
                               ("POST", "/captions", {"revision": 0, "text": "[]"}), ("POST", "/captions/done", {}),
                               ("POST", "/prepare-again", {"step": "base"})):
        status, payload = request(world, method, world.base + tail, body)
        op = {"/pipeline": "media-pipeline", "/captions": "captions-read" if method == "GET" else "captions-edit", "/captions/done": "captions-done",
              "/prepare-again": "prepare-again"}[tail]
        assert status == 409 and answer(payload)["message"] == sentence(op), (tail, status)
    set_channels(world.made.project, {"page": ["read", "media"]})
    status, payload = request(world, "GET", world.base + "/captions")
    assert status == 200 and answer(payload)["revision"] == 0


# --- the loopback socket only -------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("method,tail,body", [("GET", "/captions", None), ("POST", "/captions", {"revision": 0, "text": "[]"}),
                                              ("POST", "/captions/done", {}), ("POST", "/pipeline", {}), ("POST", "/prepare-again", {"step": "base"})])
def test_the_routes_answer_the_loopback_socket_and_are_the_404_of_no_route_on_the_lan_socket(world, method, tail, body):
    go_to_review(world)
    world.svc.lan_ip = LAN
    lan_host = f"{LAN}:{PORT}"
    status, payload = request(world, method, world.base + tail, body, lan=True, host=lan_host)
    assert status == 404 and answer(payload)["error"] == "not_found", "the socket of --lan: no such route"
    for word in ("gente", "dinheiro", "words", "chunks"):
        assert word not in payload.decode("utf-8")
    status, _ = request(world, method, world.base + tail, body, lan=True)            # a loopback Host on the LAN socket: refused by the Host rule
    assert status == 403
    status, _ = request(world, method, world.base + tail, body, lan=False, host=lan_host)   # the LAN Host on the loopback socket: the same
    assert status == 403
    status, _ = request(world, method, world.base + tail, body, lan=False)
    assert status not in (403, 404), "the loopback socket reaches the route (a refusal of the operation is another status)"


def test_the_five_routes_carry_the_loopback_flag_and_sit_under_the_recording():
    flagged = {r["op"] for r in service.ROUTES if r["loopback"]}
    assert set(NAMES) <= flagged
    for route in service.ROUTES:
        if route["loopback"] and route["op"] in NAMES:
            assert "page" in operations.by_name(route["op"])["channels"] and route["pattern"].startswith("/projects/{p}/media/{rid}/")


# --- the page works the review ---------------------------------------------------------------------------------------------------------------


def test_the_page_starts_the_pipeline_reads_the_captions_edits_them_and_says_done_and_the_rest_runs_as_a_job(world):
    status, payload = request(world, "POST", world.base + "/pipeline", {"post": kit.POST_PATH})
    job = answer(payload)
    assert status == 202 and job["op"] == "media-pipeline"
    result = wait_job(world, job["job"])
    assert result["state"] == "done" and result["result"]["stopped"] == "review"
    status, payload = request(world, "GET", world.base + "/captions")
    shown = answer(payload)
    assert status == 200 and shown["editable"] and shown["retakes"][0]["id"] == "retake-1"
    status, payload = request(world, "POST", world.base + "/captions", {"revision": 0, "text": json.dumps(
        [{"op": "retake", "id": "retake-1", "confirmed": True}, {"op": "edit", "index": 2, "text": "tá"}])})
    assert status == 200 and answer(payload)["revision"] == 1 and answer(payload)["retakes"][0]["confirmed"] is True
    status, payload = request(world, "POST", world.base + "/captions", {"revision": 0, "text": json.dumps([{"op": "delete", "index": 2}])})
    assert status == 409 and "stale_revision" in answer(payload)["message"]
    status, payload = request(world, "POST", world.base + "/captions/done", {"revision": 1})
    job = answer(payload)
    assert status == 202
    done = wait_job(world, job["job"])
    assert done["state"] == "done" and done["result"]["stopped"] == "approval" and done["result"]["steps"]["render"] == "done"


def test_a_time_a_wrong_type_and_an_unknown_key_are_refused_by_the_route_and_by_the_operation(world):
    go_to_review(world)
    status, payload = request(world, "POST", world.base + "/captions", {"revision": 0, "text": json.dumps([{"op": "edit", "index": 2, "text": "tá", "start": 4.2}])})
    assert status == 409 and "time_not_accepted" in answer(payload)["message"]
    for body in ({"revision": "0", "text": "[]"}, {"revision": 0, "text": ["[]"]}, {"revision": 0, "text": "[]", "start": 3}, {"text": "[]"}):
        status, _ = request(world, "POST", world.base + "/captions", body)
        assert status == 400, body
    assert ops.captions_read(world.made.project, world.made.rid)["revision"] == 0


# --- what the page can never do ------------------------------------------------------------------------------------------------------------------


def test_the_page_cannot_build_an_image_fetch_a_model_pin_a_browser_or_accept_a_configuration(world):
    page_ops = {r["name"] for r in operations.OPERATIONS if "page" in r["channels"]}
    assert not page_ops & {"accept-config", "deps", "pin", "run-next", "run-task", "media-purge", "contained-run", "handler", "proof"}
    assert not any(word in name for name in page_ops for word in ("build", "fetch", "pin-browser"))
    for route in service.ROUTES:
        if route["op"]:
            row = operations.by_name(route["op"])
            taken = set(route["take"]) if route["take"] is not None else {a["name"] for a in row["args"]} - set(route["bind"]) - set(route["hidden"])
            assert not {"model", "language", "media", "config", "confirmed", "accept"} & taken, route["op"]
    for tail in ("/build", "/pin-browser", "/fetch-model", "/accept-config", "/config", "/models"):
        for method in ("GET", "POST"):
            assert request(world, method, world.base + tail, {} if method == "POST" else None)[0] == 404, tail
    for body in ({"accept": True}, {"build": True}, {"confirmed": True}, {"model": "tiny"}, {"language": "en"}, {"media": {"model": "tiny"}}):
        status, _ = request(world, "POST", world.base + "/pipeline", {"post": kit.POST_PATH, **body})
        assert status == 400, body
    assert media.load(world.made.data, world.made.rid)["tasks"] == {}, "the refused calls started nothing"
    assert kit.verbs(world.made.tree, "transcriber") == [] and kit.verbs(world.made.tree, "renderer") == []


def test_the_model_and_the_language_are_the_ones_of_the_accepted_file_not_of_a_request(world):
    go_to_review(world)
    first = kit.calls(world.made.tree, "transcriber")[0]
    assert first[first.index("--model") + 1] == "small" and first[first.index("--language") + 1] == "pt"


def test_a_job_started_on_the_page_is_not_a_model_job_and_does_not_take_the_project_slot_of_one(world):
    row = operations.by_name("media-pipeline")
    assert row["model"] is False and row["job"] is True
    status, payload = request(world, "POST", world.base + "/pipeline", {"post": kit.POST_PATH})
    assert status == 202 and answer(payload)["state"] == "running"
    wait_job(world, answer(payload)["job"])
