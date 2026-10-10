"""Tests of the local service (runtime/service.py): the rules of a request, the routes, the jobs, the loops, the static
files and the shutdown. A stand-in operations object records every call, so a test sees exactly what the service asked the
operations layer; the tests that need the real operations use the stand-in tree of standin_tree.py. Most tests open no
socket; the few that bind a real port on 127.0.0.1 (the loopback test and the token-file test) make their requests and close it.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_service.py
"""
from __future__ import annotations

import ast
import base64
import http.client
import inspect
import io
import json
import os
import re
import shlex
import socket
import stat
import subprocess
import sys
import threading
import time
import types

import pytest

import standin_tree as st
from test_effects import gate_project, provider_calls, tree  # noqa: F401  (the effect fixture of test_effects.py)

service = st.load("service")
ops = st.load("ops")
operations = st.load("operations")
drop = st.load("drop")

TOKEN = service.new_token()
PORT = 8765
WAIT = 10


class Standin:
    """The operations object of a test: the real table, the real OpsError and one recorder per function of the table. A
    call returns what `answers` holds for the function (a value, an exception to raise, or a function of the call), else
    {"op", "args"}. `calls` is [(function, project, kwargs)] in the order of the calls."""

    OpsError = ops.OpsError
    operations = operations

    def __init__(self, data_dir):
        self.calls = []
        self.answers = {}
        self.data_dir = str(data_dir)
        self.stopped = 0
        self.stop_entered = threading.Event()
        self.stop_release = threading.Event()
        self.stop_release.set()
        self.job_stop = threading.Event()
        self.lock = threading.Lock()

    def __getattr__(self, name):
        if name not in {row["call"] for row in operations.OPERATIONS}:
            raise AttributeError(name)

        def call(project, **kwargs):
            with self.lock:
                self.calls.append((name, project, kwargs))
            answer = self.answers.get(name)
            if callable(answer):
                return answer(project, **kwargs)
            if isinstance(answer, BaseException):
                raise answer
            return {"op": name, "args": kwargs} if answer is None else answer

        return call

    def config(self, project):
        with self.lock:
            self.calls.append(("config", project, {}))
        if "config" in self.answers:
            return self.answers["config"]
        return {"path": project + "/docs/workbench/runtime.json", "sha256": "a" * 64, "accepted": True, "data_dir": self.data_dir}

    def stop_runs(self, project=None):
        with self.lock:
            self.stopped += 1
        self.stop_entered.set()
        self.stop_release.wait(WAIT)
        self.job_stop.set()
        return {"stopped": True}

    def named(self, name):
        return [c for c in self.calls if c[0] == name]


STATUS = {"config": {"path": "x", "sha256": "a" * 64}, "requests": [{"id": 1, "title": "t", "tasks": [
    {"id": 2, "state": "waiting"}, {"id": 3, "state": "running"}]}], "pending": [{"id": 1}, {"id": 2}], "documents": [], "board": None}


@pytest.fixture
def world(tmp_path):
    fake = Standin(tmp_path / "data")
    fake.answers["status"] = STATUS
    interface = tmp_path / "interface"
    (interface / "js").mkdir(parents=True)
    (interface / "index.html").write_text("<!doctype html><title>x</title>", encoding="utf-8")
    (interface / "js" / "app.js").write_text("export const x = 1;\n", encoding="utf-8")
    (interface / "style.css").write_text("body {}\n", encoding="utf-8")
    (interface / "data.bin").write_text("x", encoding="utf-8")
    (interface / ".hidden.js").write_text("secret", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("outside the interface folder", encoding="utf-8")
    (interface / "link.txt").symlink_to(tmp_path / "secret.txt")
    projects = []
    for name in ("alpha", "beta"):
        folder = tmp_path / name
        folder.mkdir()
        projects.append({"id": service.project_id(str(folder)), "name": name, "path": str(folder)})
    lines = []
    svc = service.Service(fake, projects, TOKEN, PORT, str(interface), log=lines.append)
    return types.SimpleNamespace(svc=svc, fake=fake, projects=projects, lines=lines, interface=interface, tmp=tmp_path)


def headers_for(method, data, auth=True):
    out = {"Host": f"127.0.0.1:{PORT}"}
    if auth:
        out["Authorization"] = f"Bearer {TOKEN}"
    if method == "POST":
        out.update({"Origin": f"http://127.0.0.1:{PORT}", "Content-Type": "application/json", "Content-Length": str(len(data))})
    return out


def call(world, method, path, body=None, *, auth=True, extra=None, raw=None):
    """One request through handle(); (status, headers, parsed body). `extra` overrides or (None) removes a header."""
    data = raw if raw is not None else (json.dumps(body).encode("utf-8") if body is not None else b"")
    headers = headers_for(method, data, auth)
    headers.update(extra or {})
    headers = {k: v for k, v in headers.items() if v is not None}
    status, out, payload = service.handle(world.svc, method, path, headers, data)
    kind = out.get("Content-Type", "")
    return status, out, (json.loads(payload) if kind.startswith("application/json") else payload)


def api(world, tail="", n=0):
    return f"/api/v1/projects/{world.projects[n]['id']}" + tail


def wait_job(world, number):
    deadline = time.monotonic() + WAIT
    while True:
        status, _, job = call(world, "GET", f"/api/v1/jobs/{number}")
        assert status == 200
        if job["state"] != "running" or time.monotonic() > deadline:
            return job
        time.sleep(0.01)


ID = {"p": None, "id": "7", "name": "writer"}


def sample(row, route):
    """(body or query, the keyword arguments the operation must get) for a route, from its row."""
    args = {a["name"]: a for a in row["args"]}
    bound = {name: (int(ID[part]) if args[name]["kind"] == "int" else ID[part]) for name, part in route["bind"].items()}
    names = [n for n in (args if route["take"] is None else route["take"]) if n not in route["bind"] and n not in route["hidden"]]
    given = {}
    for name in names:
        kind = args[name]["kind"]
        given[name] = {"int": 3, "str": "7d", "text": "some words", "flag": True, "list": ["voice"]}.get(kind) or args[name]["choices"][0]
    return given, {**bound, **given}


def path_of(world, route):
    return "/api/v1" + route["pattern"].replace("{p}", world.projects[0]["id"]).replace("{id}", ID["id"]).replace("{name}", ID["name"])


OP_ROUTES = [r for r in service.ROUTES if r["op"] and not r["upload"]]
VIEW_READS = ("agents", "conversation", "skills", "costs", "connections", "artifacts", "artifact", "artifact-raw", "version", "commands")  # the reads of the views
READ_OPS = ("status", "pending", "flows", "task", "progress") + VIEW_READS


# --- rule 1: the loopback address -----------------------------------------------------------------------------------


def test_the_service_listens_on_the_loopback_address_only(tmp_path):
    fake = Standin(tmp_path / "data")
    fake.answers["status"] = STATUS
    project = tmp_path / "alpha"
    project.mkdir()
    started = {}
    stop = threading.Event()
    ready = threading.Event()

    def on_ready(svc):
        started["svc"] = svc
        ready.set()

    out = io.StringIO()
    lines = []
    runner = threading.Thread(target=service.serve, args=([str(project)],), kwargs={
        "port": 0, "poll_every": 0, "ops_module": fake, "stop": stop, "ready": on_ready, "out": out, "log": lines.append,
        "interface_dir": str(tmp_path)})
    runner.start()
    try:
        assert ready.wait(WAIT)
        svc = started["svc"]
        assert svc.address[0] == "127.0.0.1" and svc.address[1] == svc.port and svc.port != 0
        printed = json.loads(out.getvalue())
        assert printed["url"] == f"http://127.0.0.1:{svc.port}/" and TOKEN not in out.getvalue() and svc.token not in out.getvalue()
        assert printed["projects"] == [{"id": service.project_id(str(project)), "name": "alpha"}]
        connection = http.client.HTTPConnection("127.0.0.1", svc.port, timeout=WAIT)
        connection.request("GET", f"/api/v1/projects?token={svc.token}", headers={"Authorization": f"Bearer {svc.token}"})
        refused = connection.getresponse()
        assert refused.status == 400 and b"no query" in refused.read()  # a token in a URL is not read, whatever else
        connection.close()
        connection = http.client.HTTPConnection("127.0.0.1", svc.port, timeout=WAIT)
        connection.request("GET", "/api/v1/projects", headers={"Authorization": f"Bearer {svc.token}"})
        answer = connection.getresponse()
        body = json.loads(answer.read())
        assert answer.status == 200 and body["projects"][0]["config"]["accepted"] is True
        assert answer.getheader("Cache-Control") == "no-store" and answer.getheader("X-Content-Type-Options") == "nosniff"
        assert not [h for h, _ in answer.getheaders() if h.lower().startswith("access-control")]
        connection.close()
        connection = http.client.HTTPConnection("127.0.0.1", svc.port, timeout=WAIT)
        connection.putrequest("GET", "/api/v1/projects", skip_host=True)
        connection.putheader("Host", "evil.example")
        connection.putheader("Authorization", f"Bearer {svc.token}")
        connection.endheaders()
        assert connection.getresponse().status == 403
        connection.close()
        connection = http.client.HTTPConnection("127.0.0.1", svc.port, timeout=WAIT)
        connection.request("OPTIONS", "/api/v1/projects", headers={"Authorization": f"Bearer {svc.token}"})
        assert connection.getresponse().status == 405
        connection.close()
        # The lines the server logged: the method, the path without its query, the status and the time; no token.
        deadline = time.monotonic() + WAIT
        while len([x for x in lines if x.startswith(("GET", "OPTIONS"))]) < 4 and time.monotonic() < deadline:
            time.sleep(0.01)
        shown = [x for x in lines if x.startswith(("GET", "OPTIONS"))]
        assert all(re.fullmatch(r"(GET|OPTIONS) /api/v1/projects \d{3} \d+ms", x) for x in shown) and len(shown) == 4
        assert not [x for x in lines if svc.token in x]
        # No other interface answers: the machine's own address, when it has one that is not the loopback, is refused.
        try:
            other = socket.gethostbyname(socket.gethostname())
        except OSError:
            other = "127.0.0.1"
        if not other.startswith("127."):
            with pytest.raises(OSError):
                socket.create_connection((other, svc.port), timeout=2).close()
    finally:
        stop.set()
        runner.join(WAIT * 3)
    assert not runner.is_alive()
    assert "host" not in inspect.signature(service.serve).parameters and service.HOST == "127.0.0.1"
    with pytest.raises(service.Refused):
        service.parse(["--project", "x", "--host", "0.0.0.0"])
    with pytest.raises(service.Refused):
        service.parse(["--project", "x", "--bind", "0.0.0.0"])


# --- rules 2 to 4: host, origin, token ------------------------------------------------------------------------------


@pytest.mark.parametrize("host", ["evil.example:8765", "localhost:9999", "127.0.0.1", "127.0.0.1:8765.evil.example",
                                  "127.0.0.1.evil.example:8765", "0.0.0.0:8765", "[::1]:8765", "", None])
def test_a_request_with_another_host_header_is_refused(world, host):
    status, _, body = call(world, "GET", "/api/v1/projects", extra={"Host": host})
    assert (status, body["error"]) == (403, "host")
    status, _, body = call(world, "GET", "/", extra={"Host": host}, auth=False)
    assert (status, body["error"]) == (403, "host")  # the static page too
    assert call(world, "GET", "/api/v1/projects", extra={"Host": f"localhost:{PORT}"})[0] == 200
    assert call(world, "GET", "/api/v1/projects", extra={"Host": f"LOCALHOST:{PORT}"})[0] == 200


@pytest.mark.parametrize("origin", ["http://evil.example", f"http://evil.example:{PORT}", "null", "https://127.0.0.1:8765",
                                    f"http://127.0.0.1:{PORT + 1}", f"http://127.0.0.1:{PORT}.evil.example", ""])
def test_a_request_from_another_origin_is_refused_and_a_post_without_an_origin_is_refused(world, origin):
    status, _, body = call(world, "GET", "/api/v1/projects", extra={"Origin": origin})
    assert (status, body["error"]) == (403, "origin")
    status, _, body = call(world, "POST", api(world, "/requests"), {"text": "x"}, extra={"Origin": origin})
    assert (status, body["error"]) == (403, "origin")
    status, _, body = call(world, "POST", api(world, "/requests"), {"text": "x"}, extra={"Origin": None})
    assert (status, body["error"]) == (403, "origin")  # a POST without an Origin
    assert world.fake.named("request") == []
    for good in (f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"):
        assert call(world, "POST", api(world, "/requests"), {"text": "x"}, extra={"Origin": good})[0] == 200
    assert call(world, "GET", "/api/v1/projects", extra={"Origin": None})[0] == 200  # a same-origin GET carries none


def test_an_api_route_without_the_token_is_refused_and_the_static_page_needs_none(world):
    for extra in ({"Authorization": None}, {"Authorization": "Bearer " + "0" * 64}, {"Authorization": "Bearer"},
                  {"Authorization": "Bearer "}, {"Authorization": "Basic " + TOKEN}, {"Authorization": TOKEN},
                  {"Authorization": f"Bearer {TOKEN} "}, {"Authorization": f"Bearer {TOKEN[:-1]}"}, {"Authorization": f"Bearer {TOKEN}x"}):
        status, _, body = call(world, "GET", "/api/v1/projects", extra=extra)
        assert (status, body["error"]) == (401, "token"), extra
    for path in ("/api", "/api/", "/api/v1", "/api/v1/projects/", "/api/v1/nothing"):
        assert call(world, "GET", path, auth=False)[0] == 401, path  # unknown paths under /api/ need the token too
    # The token in a URL is never read: it does not open the door, and it is not an argument.
    assert call(world, "GET", f"/api/v1/projects?token={TOKEN}", auth=False)[0] == 401
    assert call(world, "POST", api(world, "/requests") + f"?token={TOKEN}", {"text": "x"}, auth=False)[0] == 401
    assert call(world, "GET", api(world, "/status") + f"?token={TOKEN}")[0] == 400
    status, headers, page = call(world, "GET", "/", auth=False)
    assert status == 200 and b"<title>x</title>" in page and headers["Content-Type"].startswith("text/html")
    assert call(world, "GET", "/js/app.js", auth=False)[0] == 200 and call(world, "GET", "/style.css", auth=False)[0] == 200
    assert call(world, "POST", api(world, "/requests"), {"text": "x"}, auth=False)[0] == 401
    assert world.fake.calls == []


def test_the_token_is_never_in_a_response_a_url_or_a_log_line(world):
    seen = []
    for method, path, body, auth in (("GET", "/api/v1/projects", None, True), ("GET", "/api/v1/projects", None, False),
                                     ("GET", f"/api/v1/projects?token={TOKEN}", None, True), ("GET", "/", None, False),
                                     ("POST", api(world, "/requests"), {"text": TOKEN[:8]}, True),
                                     ("GET", api(world, "/pending/99"), None, True), ("GET", "/nothing", None, False)):
        status, headers, payload = call(world, method, path, body, auth=auth)
        seen += [json.dumps(payload) if isinstance(payload, (dict, list)) else payload.decode("utf-8"), json.dumps(headers)]
        seen.append(service.request_line(method, path, status, 0.01))
    seen += world.lines + [repr(world.svc), json.dumps(service.ROUTES), service.__doc__]
    assert not [s for s in seen if TOKEN in s]
    # A line of the log holds the method, the path without its query, the status and the time, and nothing else.
    line = service.request_line("GET", f"/api/v1/projects?token={TOKEN}\nfake line", 200, 0.0123)
    assert line == "GET /api/v1/projects 200 12ms" and TOKEN not in line
    assert service.request_line("GET\r\nX", "/a\nb", 404, 0) == "GET  X /a b 404 0ms"
    # The routes carry no token argument, in a body or in a query.
    for row in operations.OPERATIONS:
        assert not [a for a in row["args"] if "token" in a["name"].lower()]


def test_the_token_file_is_for_its_owner_only_and_is_removed_when_the_service_stops(tmp_path):
    older = tmp_path / "a" / "service.token"
    older.parent.mkdir()
    older.write_text("old\n")
    older.chmod(0o644)
    service.write_token(str(older), "x" * 64)
    assert stat.S_IMODE(older.stat().st_mode) == 0o600 and older.read_text() == "x" * 64 + "\n"
    link = tmp_path / "b" / "service.token"
    link.parent.mkdir()
    elsewhere = tmp_path / "elsewhere.txt"
    elsewhere.write_text("keep\n")
    link.symlink_to(elsewhere)
    service.write_token(str(link), "y" * 64)  # the link is removed, never followed
    assert not link.is_symlink() and link.read_text() == "y" * 64 + "\n" and elsewhere.read_text() == "keep\n"
    made = tmp_path / "new" / "deeper" / "service.token"
    service.write_token(str(made), "z" * 64)
    assert stat.S_IMODE(made.stat().st_mode) == 0o600 and stat.S_IMODE(made.parent.stat().st_mode) == 0o700
    assert len(service.new_token()) == 64 and service.new_token() != service.new_token()
    # serve(): the file exists while the service runs, for its owner only, and is gone after it stops.
    fake = Standin(tmp_path / "data")
    project = tmp_path / "alpha"
    project.mkdir()
    outcome = run_serve(fake, [str(project)], FakeServer)
    try:
        path = tmp_path / "data" / "service.token"
        assert path.is_file() and stat.S_IMODE(path.stat().st_mode) == 0o600
        assert path.read_text() == outcome.service.token + "\n"
        assert json.loads(outcome.out.getvalue())["token_file"] == str(path) and outcome.service.token not in outcome.out.getvalue()
    finally:
        assert outcome.finish() == 0
    assert not path.exists()
    custom = tmp_path / "chosen" / "t.token"
    again = run_serve(fake, [str(project)], FakeServer, token_file=str(custom))
    assert custom.is_file() and not path.exists()
    again.finish()
    assert not custom.exists()


# --- rule 5 and 6: methods, bodies, no cross-origin header ----------------------------------------------------------


def test_no_cross_origin_header_is_ever_sent_and_options_is_refused(world):
    answers = []
    for method in ("OPTIONS", "HEAD", "PUT", "DELETE", "PATCH", "TRACE"):
        for path in ("/api/v1/projects", api(world, "/requests"), "/", "/nothing"):
            for extra in ({}, {"Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "authorization"},
                          {"Origin": "http://evil.example"}):
                answers.append(call(world, method, path, extra=extra)[:2])
    for status, headers in answers:
        assert status in (403, 405), (status, headers)
        assert not [h for h in headers if h.lower().startswith(("access-control", "cross-origin", "timing-allow"))]
    assert call(world, "OPTIONS", "/api/v1/projects")[0:3:2][0] == 405
    assert call(world, "OPTIONS", "/api/v1/projects", extra={"Origin": f"http://127.0.0.1:{PORT}"})[2]["error"] == "method"
    # a preflight carries no token: it is refused before anything else says yes
    assert call(world, "OPTIONS", "/api/v1/projects", auth=False)[0] == 401
    for method, path, body in (("GET", "/api/v1/projects", None), ("POST", api(world, "/requests"), {"text": "x"}),
                               ("GET", "/", None), ("GET", "/nothing", None)):
        status, headers, _ = call(world, method, path, body, auth=method == "POST" or path.startswith("/api"))
        assert not [h for h in headers if h.lower().startswith("access-control")]
    assert world.fake.named("request") == [("request", world.projects[0]["path"], {"text": "x"})]


def test_every_response_carries_the_cache_and_sniffing_headers_and_a_page_the_policy(world):
    battery = [("GET", "/api/v1/projects", None, True), ("GET", "/api/v1/projects", None, False), ("GET", "/", None, False),
               ("GET", "/js/app.js", None, False), ("GET", "/style.css", None, False), ("GET", "/nothing", None, False),
               ("POST", api(world, "/requests"), {"text": "x"}, True), ("POST", api(world, "/requests"), None, True),
               ("DELETE", "/", None, False)]
    for method, path, body, auth in battery:
        status, headers, _ = call(world, method, path, body, auth=auth, raw=b"" if body is None and method == "POST" else None)
        assert headers["Cache-Control"] == "no-store" and headers["X-Content-Type-Options"] == "nosniff", (path, status)
        page = headers["Content-Type"].startswith("text/html")
        assert (headers.get("Content-Security-Policy") == "default-src 'self'; img-src 'self' blob:; frame-ancestors 'none'") == page, path
        assert (headers.get("Referrer-Policy") == "no-referrer") == page, path
    (world.interface / "logo.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>")
    headers = call(world, "GET", "/logo.svg", auth=False)[1]
    assert headers["Content-Security-Policy"] == "default-src 'self'; img-src 'self' blob:; frame-ancestors 'none'"  # an svg can hold a script


def test_a_post_needs_json_a_known_length_and_a_body_the_route_takes(world):
    path = api(world, "/requests")
    cases = [({"Content-Type": "text/plain"}, 415), ({"Content-Type": "application/x-www-form-urlencoded"}, 415),
             ({"Content-Type": None}, 415), ({"Content-Type": "application/json; charset=utf-8"}, 200),
             ({"Content-Type": "Application/JSON"}, 200), ({"Content-Length": None}, 411), ({"Content-Length": "x"}, 400),
             ({"Content-Length": "-1"}, 400), ({"Content-Length": str(service.JSON_LIMIT + 1)}, 413),
             ({"Content-Length": str(service.JSON_LIMIT)}, 200), ({"Transfer-Encoding": "chunked"}, 400)]
    for extra, expected in cases:
        assert call(world, "POST", path, {"text": "x"}, extra=extra)[0] == expected, extra
    for raw in (b"", b"{", b"[]", b"null", b'"x"', b'{"text": "a", "text": "b"}', b"\xff\xfe", b'{"text": 1}', b'{"text": "x", "extra": 1}',
                b'{"text": "x", "channel": "terminal"}', b'{"text": "x", "flow": 3}'):
        status, _, body = call(world, "POST", path, raw=raw)
        assert (status, body["error"]) == (400, "usage"), raw
    assert call(world, "POST", path, {"flow": "demo"})[2]["message"] == "text is required"
    assert call(world, "POST", api(world, "/requests") + "?x=1", {"text": "x"})[0] == 400  # a POST takes no query
    # A null for an optional argument is the argument left out; for a required one it is missing.
    before = len(world.fake.calls)
    assert call(world, "POST", path, {"text": "x", "flow": None, "title": None})[0] == 200
    assert world.fake.calls[before][2] == {"text": "x"}
    assert call(world, "POST", path, {"text": None})[0] == 400
    # The body limit of a route is read before the body: the file route takes more, the others do not.
    big = {"Content-Length": str(2 * 1024 * 1024)}
    assert service.check_request("POST", api(world, "/requests"), {**headers_for("POST", b""), **big}, PORT, TOKEN) == (413, "too_large")
    assert service.check_request("POST", api(world, "/tasks/7/files"), {**headers_for("POST", b""), **big}, PORT, TOKEN) is None
    over = {"Content-Length": str(35 * 1024 * 1024)}
    assert service.check_request("POST", api(world, "/tasks/7/files"), {**headers_for("POST", b""), **over}, PORT, TOKEN) == (413, "too_large")


def test_an_unknown_project_route_or_method_is_refused(world):
    other = "0" * 12
    assert call(world, "GET", f"/api/v1/projects/{other}/status")[0] == 404
    assert call(world, "POST", f"/api/v1/projects/{other}/requests", {"text": "x"})[0] == 404
    assert call(world, "GET", "/api/v1/projects/ABCDEF123456/status")[0] == 404  # not the id's form
    assert call(world, "GET", "/api/v1/projects/../status")[0] == 404
    for path in ("/api/v1", "/api/v1/nothing", api(world, "/nothing"), api(world, "/status/extra"), api(world, "/pending/x"),
                 api(world, "/pending/1234567890"), api(world, "/pending/-1"), api(world, "/tasks/7/nothing"), "/api/v1/jobs/x",
                 api(world, "/agents/../mode"), api(world, "/agents/x%2Fy/mode")):
        assert call(world, "GET", path)[0] == 404, path
    assert call(world, "POST", api(world, "/status"), {})[0] == 405          # a read does not take a POST
    assert call(world, "GET", api(world, "/requests"))[0] == 405              # a write does not take a GET
    assert call(world, "GET", api(world, "/pending/7/approve"))[0] == 405
    assert call(world, "POST", "/api/v1/projects", {})[0] == 405
    assert call(world, "POST", "/", {}, auth=False)[0] == 405                  # no POST on the static side
    assert call(world, "GET", "http://127.0.0.1:8765/api/v1/projects")[0] == 400   # absolute-form
    assert call(world, "GET", "/api/v1/projects?" + "a=1&" * 600)[0] == 400
    assert call(world, "GET", "/api/v1/jobs/999")[0] == 404
    assert world.fake.calls == []


# --- rule 7 and 8: one route, one operation, the statuses ------------------------------------------------------------


@pytest.mark.parametrize("route", OP_ROUTES, ids=lambda r: f"{r['method']} {r['pattern']}")
def test_every_route_calls_exactly_one_operation_and_returns_what_it_returned(world, route):
    world.fake.answers.clear()
    row = operations.by_name(route["op"])
    given, expected = sample(row, route)
    if row.get("channel_arg"):
        expected = {**expected, "channel": "page"}
    path = path_of(world, route)
    if route["raw"]:  # the bytes of a file, with the media type the operation names
        world.fake.answers[row["call"]] = {"media_type": "image/png", "data": b"\x89PNG\r\n\x1a\nbytes"}
        status, headers, body = call(world, "GET", path + "?path=docs/x.png")
        assert (status, body, headers["Content-Type"]) == (200, b"\x89PNG\r\n\x1a\nbytes", "image/png")
        assert world.fake.calls == [(row["call"], world.projects[0]["path"], {"path": "docs/x.png"})]
        return
    if route["method"] == "GET":
        path += "?" + "&".join(f"{k}={v}" for k, v in given.items()) if given else ""
        status, _, body = call(world, "GET", path)
    else:
        status, _, body = call(world, "POST", path, given)
    if row.get("job"):
        assert status == 202 and body["state"] == "running" and body["op"] == row["name"]
        body = wait_job(world, body["job"])["result"]
    else:
        assert status == 200
    assert world.fake.calls == [(row["call"], world.projects[0]["path"], expected)]
    assert body == {"op": row["call"], "args": expected}


def test_every_route_is_built_from_a_row_the_page_may_call_and_names_only_arguments_of_that_row():
    names = []
    for route in service.ROUTES:
        if route["own"]:
            assert route["op"] is None and not route["bind"] and "kind" not in route
            continue
        row = operations.by_name(route["op"])
        assert "page" in row["channels"], route["op"]
        args = {a["name"]: a for a in row["args"]}
        assert set(route["bind"]) | set(route["take"] or ()) | set(route["hidden"]) <= set(args), route["op"]
        loose = {n for n, a in args.items() if a.get("required")} - set(route["bind"]) - set(route["hidden"])
        assert loose <= set(route["take"] if route["take"] is not None else args), (route["op"], loose)  # callable
        for name in (set(route["take"]) if route["take"] is not None else set(args) - set(route["bind"]) - set(route["hidden"])):
            assert args[name]["kind"] in service.EXPOSED_KINDS, (route["op"], name)
        names.append((route["method"], route["pattern"]))
        assert (route["method"] == "GET") == (route["op"] in READ_OPS), route["op"]
    assert len(names) == len(set(names))
    assert "channel" not in {a["name"] for row in operations.OPERATIONS for a in row["args"]}  # the channel is never an argument


def test_a_route_is_a_job_exactly_when_its_table_row_says_so(world):
    jobs, plain = set(), set()
    for route in OP_ROUTES:
        row = operations.by_name(route["op"])
        given, _ = sample(row, route)
        method = route["method"]
        path = path_of(world, route) + ("?" + "&".join(f"{k}={v}" for k, v in given.items()) if method == "GET" and given else "")
        status, _, body = call(world, method, path, given if method == "POST" else None)
        (jobs if status == 202 else plain).add(row["name"])
        assert (status == 202) == bool(row.get("job")), row["name"]
        if status == 202:
            wait_job(world, body["job"])
    assert {"route", "release", "approve", "sync", "dispatch", "say"} <= jobs
    assert not {"status", "pending", "answer", "reject", "request", "cancel", "retry", "task", "flows", "progress", "verdict",
                "set-mode"} & jobs
    assert not set(VIEW_READS) & jobs and set(VIEW_READS) <= plain
    # The table is the one source: a row that calls a model or a platform has the key, and only a boolean.
    for row in operations.OPERATIONS:
        assert row.get("job", False) in (True, False)
        if row["model"] is not False:
            assert row.get("job") is True, row["name"]
    assert {r["name"] for r in operations.OPERATIONS if r.get("job")} == \
        {"route", "route-queued", "release", "approve", "run-next", "sync", "contained-run", "dispatch", "handler", "say"}


def test_a_refused_operation_becomes_its_documented_status(world):
    path = api(world, "/pending/7")
    for error, status, word in ((ops.OpsError("no pending decision 7", 1), 409, "refused"),
                                (ops.OpsError("pending decision 7 is a plan", 2), 400, "usage"),
                                (ops.OpsError("the configuration has another hash", 3), 412, "not_configured")):
        world.fake.answers["pending"] = error
        got, headers, body = call(world, "GET", path)
        assert (got, body) == (status, {"error": word, "message": str(error)}), word
        assert headers["Content-Type"] == "application/json; charset=utf-8"
    for failure in (RuntimeError("secret detail at /home/example/x.py"), ops.OpsError("odd", 4), ValueError("v"), OSError("o")):
        world.fake.answers["pending"] = failure
        got, _, body = call(world, "GET", path)
        assert got == 500 and body == {"error": "internal", "message": "internal error"}
        assert "Traceback" not in json.dumps(body) and "/home/example" not in json.dumps(body)
    assert any("Traceback" in line and "RuntimeError" in line for line in world.lines)  # the traceback is on stderr's side
    world.lines.clear()
    # A job that fails ends failed with the same words, and a refusal of a job's operation does not hide in a 202.
    world.fake.answers["route"] = ops.OpsError("another run is in progress", 1)
    status, _, job = call(world, "POST", api(world, "/requests/7/route"), {})
    assert status == 202
    failed = wait_job(world, job["job"])
    assert failed["state"] == "failed" and failed["result"] is None
    assert failed["error"] == {"error": "refused", "message": "another run is in progress", "status": 409}
    world.fake.answers["sync"] = RuntimeError("boom")
    failed = wait_job(world, call(world, "POST", api(world, "/sync"), {})[2]["job"])
    assert failed["error"] == {"error": "internal", "message": "internal error", "status": 500}
    assert any("Traceback" in line for line in world.lines)


def test_a_route_that_calls_a_model_returns_a_job_and_the_job_ends_with_the_operations_result(world):
    gate = threading.Event()
    world.fake.answers["say"] = lambda project, text, channel=None: gate.wait(WAIT) and {"reply": "ok: " + text, "ran": True}
    status, _, job = call(world, "POST", api(world, "/conversation"), {"text": "a new request"})
    assert status == 202
    assert set(job) == {"job", "op", "project", "state", "result", "error", "started_at", "ended_at"}
    assert (job["op"], job["project"], job["state"], job["result"], job["error"], job["ended_at"]) == \
        ("say", world.projects[0]["id"], "running", None, None, None) and job["started_at"]
    status, _, again = call(world, "GET", f"/api/v1/jobs/{job['job']}")
    assert status == 200 and again["state"] == "running" and again["job"] == job["job"]
    gate.set()
    done = wait_job(world, job["job"])
    assert done["state"] == "done" and done["result"] == {"reply": "ok: a new request", "ran": True} and done["ended_at"]
    assert done["error"] is None and done["started_at"] == job["started_at"]
    # numbers go up, and a job of the other project is told apart
    second = call(world, "POST", api(world, "/conversation", 1), {"text": "other"})[2]
    assert second["job"] == job["job"] + 1 and second["project"] == world.projects[1]["id"]
    wait_job(world, second["job"])


def test_a_second_turn_while_a_job_that_calls_a_model_runs_is_not_refused_the_operation_queues_it(world):
    """A-23: `say` and `route` queue their call while a run is in progress (their rows say `queues`), so the service
    starts the second one without the model slot and the operation itself finds the run lock held; every other job that
    calls a model is still refused (busy) while the slot is held."""
    gate = threading.Event()
    world.fake.answers["say"] = lambda project, text, channel=None: gate.wait(WAIT) and {"reply": "ok"}
    first = call(world, "POST", api(world, "/conversation"), {"text": "one"})
    assert first[0] == 202
    status, _, second = call(world, "POST", api(world, "/conversation"), {"text": "two"})
    assert status == 202 and second["job"] != first[2]["job"]                     # not 409 busy
    assert call(world, "POST", api(world, "/requests/7/route"), {})[0] == 202    # a request to route is queued the same way
    assert call(world, "POST", api(world, "/dispatch"), {})[0] == 409            # a job that does not queue is refused
    deadline = time.monotonic() + WAIT
    while (len(world.fake.named("say")) < 2 or not world.fake.named("route")) and time.monotonic() < deadline:
        time.sleep(0.01)
    assert len(world.fake.named("say")) == 2 and len(world.fake.named("route")) == 1
    assert call(world, "POST", api(world, "/pending/7/approve"), {"sha256": "a" * 64})[0] == 202  # not a model: it runs
    assert call(world, "POST", api(world, "/conversation", 1), {"text": "other project"})[0] == 202  # another project
    gate.set()
    wait_job(world, first[2]["job"])
    deadline = time.monotonic() + WAIT
    while call(world, "POST", api(world, "/conversation"), {"text": "three"})[0] == 409 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert len(world.fake.named("say")) >= 3


# --- the loops --------------------------------------------------------------------------------------------------------


def test_the_dispatch_loop_calls_the_dispatcher_for_each_project_and_survives_an_error(world):
    rounds = {"n": 0}
    done = threading.Event()

    def dispatch(project):
        rounds["n"] += 1
        if rounds["n"] == 1:
            raise RuntimeError("the round failed")
        if rounds["n"] >= 6:
            done.set()
        return {"stopped": "no task is ready"}

    world.fake.answers["dispatch"] = dispatch
    stop = threading.Event()
    runner = threading.Thread(target=service.dispatch_loop, args=(world.svc, 0.01, stop))
    runner.start()
    assert done.wait(WAIT)
    stop.set()
    runner.join(WAIT)
    assert not runner.is_alive()
    paths = [c[1] for c in world.fake.named("dispatch")]
    assert paths[:2] == [world.projects[0]["path"], world.projects[1]["path"]]    # each project, in the order given
    assert set(paths) == {p["path"] for p in world.projects} and paths.count(paths[0]) >= 2
    assert [x for x in world.lines if "failed" in x] == [f"dispatch of {world.projects[0]['id']}: RuntimeError: the round failed"]
    assert not world.svc.exclusive                                                  # the model slot is given back


def test_the_queue_loop_calls_route_queued_for_each_project_holding_the_model_slot_and_skips_a_busy_one(world):
    """A-23: the lines and requests that waited for the end of a run are routed by the loop, one call per project and
    round, with the model slot held during the call; a project with a job running is skipped."""
    held, slots = threading.Event(), []

    def route_queued(project):
        slots.append(dict(world.svc.exclusive))
        if len(slots) >= 4:
            held.set()
        return {"routed": None, "queued": 0}

    world.fake.answers["route_queued"] = route_queued
    gate = threading.Event()
    world.fake.answers["say"] = lambda project, text, channel=None: gate.wait(WAIT) and {"reply": "ok"}
    job = call(world, "POST", api(world, "/conversation", 1), {"text": "busy"})[2]          # the second project has a job
    stop = threading.Event()
    runner = threading.Thread(target=service.dispatch_loop, args=(world.svc, 0.01, stop, "route_queued"))
    runner.start()
    assert held.wait(WAIT)
    stop.set()
    runner.join(WAIT)
    assert {c[1] for c in world.fake.named("route_queued")} == {world.projects[0]["path"]}  # not the project with a job
    first = world.projects[0]["id"]
    assert all(s.get(first) == "the route_queued loop" for s in slots) and not world.svc.exclusive.get(first)
    gate.set()
    wait_job(world, job["job"])
    assert service.QUEUE_EVERY == 5.0 and service.MODEL_LOOPS == ("dispatch", "route_queued")


def test_the_dispatch_loop_skips_a_project_that_has_a_job_running_and_the_poll_loop_calls_poll(world):
    gate = threading.Event()
    world.fake.answers["say"] = lambda project, text, channel=None: gate.wait(WAIT) and {"reply": "ok"}
    job = call(world, "POST", api(world, "/conversation", 1), {"text": "busy"})[2]
    assert job["state"] == "running"
    seen = threading.Event()
    world.fake.answers["dispatch"] = lambda project: seen.set() or {"stopped": "x"}
    stop = threading.Event()
    runner = threading.Thread(target=service.dispatch_loop, args=(world.svc, 0.01, stop))
    runner.start()
    assert seen.wait(WAIT)
    time.sleep(0.2)
    stop.set()
    runner.join(WAIT)
    assert {c[1] for c in world.fake.named("dispatch")} == {world.projects[0]["path"]}   # not the project with a job
    gate.set()
    wait_job(world, job["job"])
    # poll: the short job, no model slot; a project with a job running is skipped as well
    polled = threading.Event()
    world.fake.answers["poll"] = lambda project: (polled.set() if project == world.projects[1]["path"] else None) or {"synced": None}
    stop = threading.Event()
    runner = threading.Thread(target=service.dispatch_loop, args=(world.svc, 0.01, stop, "poll"))
    runner.start()
    assert polled.wait(WAIT)
    stop.set()
    runner.join(WAIT)
    assert {c[1] for c in world.fake.named("poll")} == {p["path"] for p in world.projects}
    assert world.fake.named("sync") == [] and not world.svc.exclusive


# --- static files -----------------------------------------------------------------------------------------------------


def test_a_static_path_never_leaves_the_interface_folder(world):
    outside = "outside the interface folder"
    for path in ("/../secret.txt", "/%2e%2e/secret.txt", "/..%2fsecret.txt", "/%2e%2e%2fsecret.txt", "/js/../../secret.txt",
                 "/js/..%2f..%2fsecret.txt", "/link.txt", "//secret.txt", "/js//app.js", "/./index.html", "/js/./app.js",
                 "/%252e%252e/secret.txt", "/js/", "/js", "/.hidden.js", "/js/.hidden.js", "/data.bin", "/index.html%00.js",
                 "/js\\app.js", "/nothing.js", "/index", "/%2e%2e", "/..", "/etc/passwd", "/robots", "/api%2Fv1/projects"):
        status, headers, payload = call(world, "GET", path, auth=False)
        assert status == 404, path
        assert outside.encode() not in (payload if isinstance(payload, bytes) else json.dumps(payload).encode()), path
    assert call(world, "GET", "/", auth=False)[0] == 200 and call(world, "GET", "/index.html", auth=False)[0] == 200
    assert call(world, "GET", "/js/app.js", auth=False)[1]["Content-Type"] == "text/javascript; charset=utf-8"
    assert call(world, "GET", "/js/%61pp.js", auth=False)[0] == 200                      # an encoded letter is the letter
    assert call(world, "GET", "/style.css?v=3", auth=False)[0] == 200                    # a query on a file is ignored
    # no interface folder at all: nothing is served, the API still answers
    world.svc.interface_dir = None
    assert call(world, "GET", "/", auth=False)[0] == 404 and call(world, "GET", "/api/v1/projects")[0] == 200
    world.svc.interface_dir = str(world.tmp / "no-such-folder")
    assert call(world, "GET", "/", auth=False)[0] == 404
    # a symlink inside that stays inside is served; one that leaves is not
    world.svc.interface_dir = str(world.interface)
    (world.interface / "inner.js").symlink_to(world.interface / "js" / "app.js")
    assert call(world, "GET", "/inner.js", auth=False)[0] == 200


def test_favicon_ico_is_answered_with_the_favicon_svg_and_needs_no_token(world):
    """Browsers ask for /favicon.ico by default; the page links ./favicon.svg. The static table answers the first with the
    bytes of the second (no new file), as a static file: no token, the page's headers, and nothing else changes."""
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"/>'
    (world.interface / "favicon.svg").write_bytes(svg)
    status, headers, payload = call(world, "GET", "/favicon.ico", auth=False)
    assert (status, payload) == (200, svg)
    assert headers["Content-Type"] == "image/svg+xml" and headers["Cache-Control"] == "no-store"
    assert call(world, "GET", "/favicon.svg", auth=False)[2] == svg
    assert call(world, "GET", "/favicon.ico", auth=False, extra={"Host": "evil.example"})[0] == 403   # the host rule still applies
    assert call(world, "POST", "/favicon.ico", {}, auth=False)[0] == 405                              # GET only
    assert call(world, "GET", "/api/v1/projects", auth=False)[0] == 401                               # the API still needs the token
    (world.interface / "favicon.svg").unlink()
    assert call(world, "GET", "/favicon.ico", auth=False)[0] == 404, "without the svg there is nothing to answer with"


# --- the file route --------------------------------------------------------------------------------------------------


def test_a_file_handed_over_from_the_page_is_written_by_the_service_and_removed_after_the_hand_over(world):
    seen = {}

    def hand(project, task_id, file):
        seen.update(task=task_id, name=os.path.basename(file), bytes=open(file, "rb").read(), dir=os.path.dirname(file),
                    mode=stat.S_IMODE(os.stat(file).st_mode), dirmode=stat.S_IMODE(os.stat(os.path.dirname(file)).st_mode))
        return {"task": task_id, "path": "x", "bytes": len(seen["bytes"])}

    world.fake.answers["hand_over"] = hand
    content = base64.b64encode(b"hello \x00 bytes").decode()
    status, _, body = call(world, "POST", api(world, "/tasks/7/files"), {"name": "logo.png", "content_base64": content})
    assert status == 200 and body == {"task": 7, "path": "x", "bytes": 13}
    assert (seen["task"], seen["name"], seen["bytes"], seen["mode"], seen["dirmode"]) == (7, "logo.png", b"hello \x00 bytes", 0o600, 0o700)
    uploads = world.tmp / "data" / "uploads"
    assert os.path.dirname(seen["dir"]) == str(uploads) and not os.path.exists(seen["dir"]) and os.listdir(uploads) == []
    # a refusal of the operation also removes the folder
    world.fake.answers["hand_over"] = lambda project, task_id, file: (_ for _ in ()).throw(ops.OpsError("a file of that name is already there", 1))
    assert call(world, "POST", api(world, "/tasks/7/files"), {"name": "logo.png", "content_base64": content})[0] == 409
    assert os.listdir(uploads) == []
    # the request never names the path, and a name is a plain file name
    world.fake.calls.clear()
    for body in ({"name": "a.txt", "content_base64": content, "file": "/etc/passwd"}, {"name": "a.txt"}, {"content_base64": content},
                 {"name": 3, "content_base64": content}, {"name": "a.txt", "content_base64": 3}, {"name": "a.txt", "content_base64": "!!"},
                 {"name": "a.txt", "content_base64": "aGVsbG8"}):
        assert call(world, "POST", api(world, "/tasks/7/files"), body)[0] == 400, body
    for name in ("../x", "a/b", "/etc/passwd", ".hidden", "x" * 101, "", " a", "a b", "é.txt", "..", ".", "a\nb", "a\\b"):
        status, _, body = call(world, "POST", api(world, "/tasks/7/files"), {"name": name, "content_base64": content})
        assert (status, body["error"]) == (400, "usage"), repr(name)
    assert world.fake.named("hand_over") == [] and os.listdir(uploads) == []
    world.fake.answers["hand_over"] = hand
    assert call(world, "POST", api(world, "/tasks/7/files"), {"name": "x" * 100, "content_base64": content})[0] == 200
    assert call(world, "POST", api(world, "/tasks/7/files") + "?file=/etc/passwd", {"name": "a", "content_base64": content})[0] == 400


def test_a_file_over_the_limit_is_refused_after_it_is_decoded_and_the_name_pattern_is_the_drops(world, monkeypatch):
    monkeypatch.setattr(service, "UPLOAD_BYTES", 10)
    status, _, body = call(world, "POST", api(world, "/tasks/7/files"),
                           {"name": "big.bin", "content_base64": base64.b64encode(b"x" * 11).decode()})
    assert (status, body["error"]) == (413, "too_large") and world.fake.named("hand_over") == []
    assert call(world, "POST", api(world, "/tasks/7/files"),
                {"name": "ok.bin", "content_base64": base64.b64encode(b"x" * 10).decode()})[0] == 200
    assert service.UPLOAD_NAME.pattern == drop.NAME.pattern and service.FILE_LIMIT >= service.UPLOAD_BYTES * 4 // 3 + 4096
    assert drop.MAX_BYTES == 25 * 1024 * 1024 and service.FILE_LIMIT == 34 * 1024 * 1024


# --- what the service may reach --------------------------------------------------------------------------------------


def test_the_service_reaches_the_store_and_the_facade_only_through_the_operations_layer():
    path = st.RUNTIME / "service.py"
    tree_ = ast.parse(path.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree_):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    siblings = {p.stem for p in st.RUNTIME.glob("*.py")}
    assert imported & siblings == {"ops", "shell_kit"}, imported & siblings  # of the runtime, the operations layer and the shells' kit only
    assert not imported & {"providers", "evals", "adapters", "scripts", "sqlite3", "lab", "store"}
    used = {n.id for n in ast.walk(tree_) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree_) if isinstance(n, ast.Attribute)}
    assert not used & {"lab", "store", "store_module", "open_db", "init_db", "context", "project_config", "sqlite3", "stop_all_groups"}
    # the only files the code opens are the static files, the token file and the upload; it reads no project file
    opens = {}
    for fn in [n for n in ast.walk(tree_) if isinstance(n, ast.FunctionDef)]:
        for node in ast.walk(fn):
            if isinstance(node, ast.Call):
                name = ast.unparse(node.func)
                if name in ("open", "os.open", "os.fdopen"):
                    opens.setdefault(fn.name, set()).add(name)
    assert set(opens) == {"write_token", "_upload", "_static"}, opens
    # the layer map allows it two arrows (the operations layer and the shells' kit) and no other
    sys.path.insert(0, str(st.REPO / "scripts" / "tests"))
    layer = __import__("test_layer_map")
    assert layer.allowed("runtime/service.py", "runtime/ops.py") and layer.allowed("runtime/service.py", "runtime/shell_kit.py")
    for target in ("runtime/lab.py", "providers/store/sqlite.py", "runtime/plan.py", "providers/resolve.py", "evals/execution.py",
                   "runtime/operations.py"):
        assert not layer.allowed("runtime/service.py", target), target


def test_the_read_routes_call_their_operations_with_the_query_they_take_and_refuse_any_other_key(world):
    reads = {r["op"]: r for r in service.ROUTES if r["op"] in VIEW_READS}
    assert set(reads) == set(VIEW_READS)
    for name, route in reads.items():
        assert route["method"] == "GET" and not operations.by_name(name).get("job"), name
        assert "page" in operations.by_name(name)["channels"], name
    project = world.projects[0]["path"]

    def last():
        return world.fake.calls[-1]

    # the routes that take no query: called with none, refused with any
    for name, tail in (("agents", "/agents"), ("skills", "/skills"), ("connections", "/connections"), ("artifacts", "/artifacts"),
                       ("commands", "/commands")):
        world.fake.calls.clear()
        status, _, body = call(world, "GET", api(world, tail))
        assert status == 200 and body == {"op": name, "args": {}}, name
        assert world.fake.calls == [(name, project, {})]
        world.fake.calls.clear()
        for query in ("?after=1", "?since=7d", "?path=docs/a.md", "?x=1"):
            assert call(world, "GET", api(world, tail + query))[0] == 400, (tail, query)
        assert world.fake.calls == []
    # conversation: both keys optional
    world.fake.calls.clear()
    assert call(world, "GET", api(world, "/conversation"))[0] == 200 and last() == ("conversation", project, {})
    assert call(world, "GET", api(world, "/conversation?after=0"))[0] == 200
    assert last() == ("conversation", project, {"after": 0})
    assert call(world, "GET", api(world, "/conversation?after=42&conversation=project"))[0] == 200
    assert last() == ("conversation", project, {"after": 42, "conversation": "project"})
    assert call(world, "GET", api(world, "/conversation?conversation=other"))[0] == 200
    assert last() == ("conversation", project, {"conversation": "other"})
    # costs: since is text, the operation checks it
    assert call(world, "GET", api(world, "/costs"))[0] == 200 and last() == ("costs", project, {})
    assert call(world, "GET", api(world, "/costs?since=2026-10-01"))[0] == 200
    assert last() == ("costs", project, {"since": "2026-10-01"})
    # artifact: the path in the query, required, passed through as it came (decoded)
    assert call(world, "GET", api(world, "/artifact?path=docs/business/model.md"))[0] == 200
    assert last() == ("artifact", project, {"path": "docs/business/model.md"})
    assert call(world, "GET", api(world, "/artifact?path=docs%2Fa%20b.md"))[0] == 200
    assert last() == ("artifact", project, {"path": "docs/a b.md"})
    assert call(world, "GET", api(world, "/artifact?path=../etc/passwd"))[0] == 200  # the operation refuses it, not the service
    assert last() == ("artifact", project, {"path": "../etc/passwd"})
    assert call(world, "GET", api(world, "/artifact?path=" + "d" * 512))[0] == 200  # exactly 512 bytes
    world.fake.calls.clear()
    for tail in ("/artifact", "/artifact?path=docs/a.md&since=7d", "/artifact?other=1", "/artifact?path=a&path=b",
                 "/artifact?path=" + "d" * 513, "/artifact?path=" + "%C3%A9" * 257, "/conversation?after=x",
                 "/conversation?after=-1", "/conversation?after=1.5", "/conversation?after=1&after=2",
                 "/conversation?since=7d", "/conversation?after=" + "9" * 13, "/costs?after=1", "/costs?since=a&since=b"):
        status, _, body = call(world, "GET", api(world, tail))
        assert (status, body["error"]) == (400, "usage"), tail
    assert world.fake.calls == []
    # an operation's refusal keeps its documented status; a read takes no body and no POST
    world.fake.answers["artifact"] = ops.OpsError("docs/x.md is a link", 2)
    assert call(world, "GET", api(world, "/artifact?path=docs/x.md"))[0] == 400
    world.fake.answers["artifact"] = ops.OpsError("no file docs/x.md", 1)
    assert call(world, "GET", api(world, "/artifact?path=docs/x.md"))[0] == 409
    for tail in ("/agents", "/skills", "/costs", "/connections", "/artifacts", "/artifact"):
        assert call(world, "POST", api(world, tail), {})[0] == 405, tail
    assert call(world, "GET", api(world, "/artifacts/docs/a.md"))[0] == 404
    # the token is needed, and an unknown project is not found
    assert call(world, "GET", api(world, "/agents"), auth=False)[0] == 401
    assert call(world, "GET", "/api/v1/projects/000000000000/agents")[0] == 404


def test_accepting_a_configuration_is_not_a_route(world):
    exposed = {r["op"] for r in service.ROUTES if r["op"]}
    never = {"accept-config", "run-next", "deps", "proof", "approve-policy", "revoke-policy", "standing", "execute-under-policy",
             "contained-run", "poll", "handler", "pin", "stop-runs", "config"}
    assert not exposed & never
    for row in operations.OPERATIONS:
        assert ("page" in row["channels"]) == (row["name"] in exposed | {"config"}), row["name"]
    for tail in ("/accept-config", "/accept_config", "/config", "/run-next", "/run_next", "/approve-policy", "/pin", "/poll", "/stop-runs"):
        for method in ("GET", "POST"):
            assert call(world, method, api(world, tail), {"sha256": "a" * 64} if method == "POST" else None)[0] == 404, tail
    assert world.fake.named("accept_config") == [] and world.fake.named("run_next") == []
    # an operation whose row does not list the page is no route even if a route named it
    route = service._route("GET", "/projects/{p}/proof", "proof")
    assert "page" not in operations.by_name("proof")["channels"]
    assert service._operation(world.svc, route, {"p": world.projects[0]["id"]}, "", b"")[0] == 404


def test_the_project_id_is_a_hash_of_the_real_path_and_a_path_is_never_in_a_url(tmp_path):
    folder = tmp_path / "one"
    folder.mkdir()
    link = tmp_path / "link"
    link.symlink_to(folder)
    first = service.project_id(str(folder))
    assert re.fullmatch(r"[0-9a-f]{12}", first) and service.project_id(str(link)) == first
    assert service.project_id(str(tmp_path / "two")) != first and str(folder) not in first and "one" not in first


# --- the projects, the real operations --------------------------------------------------------------------------------


@pytest.fixture
def real(tree, tmp_path):  # noqa: F811
    path = str(tree["project"])
    projects = [{"id": service.project_id(path), "name": "project", "path": path}]
    lines = []
    svc = service.Service(ops, projects, TOKEN, PORT, str(tmp_path / "no-interface"), log=lines.append)
    return types.SimpleNamespace(svc=svc, projects=projects, lines=lines, tmp=tmp_path, tree=tree, path=path)


def test_the_config_operation_never_refuses_an_unaccepted_configuration_and_the_project_list_shows_it(real):
    digest = ops.project_config.load(real.path)["sha256"]
    found = ops.config(real.path)
    assert found == {"path": os.path.join(real.path, "docs", "workbench", "runtime.json"), "sha256": digest, "accepted": False,
                     "data_dir": str(real.tree["data"])}
    with pytest.raises(ops.OpsError) as refused:
        ops.status(real.path)
    assert refused.value.code == 3 and digest in str(refused.value)
    status, _, body = call(real, "GET", "/api/v1/projects")
    assert status == 200
    [entry] = body["projects"]
    assert entry["config"] == {"sha256": digest, "accepted": False}
    assert "open_pending" not in entry and "running_task" not in entry
    assert entry["folder"] == real.path, "A-34: the folder is in the entry of a project that is not accepted too: the page cannot read it elsewhere"
    assert "accept-config" in entry["message"] and digest in entry["message"]
    refused = call(real, "GET", api(real, "/status"))
    assert (refused[0], {k: refused[2][k] for k in ("error", "message")}) == (412, {"error": "not_configured", "message": entry["message"]})
    assert refused[2]["next"] in entry["message"] and "accept-config" in refused[2]["next"]  # WP-9.14b: the command, as a field
    ops.accept_config(real.path, digest)
    assert ops.config(real.path)["accepted"] is True
    [entry] = call(real, "GET", "/api/v1/projects")[2]["projects"]
    assert entry["config"] == {"sha256": digest, "accepted": True} and entry["open_pending"] == 0 and entry["running_task"] is None
    assert "message" not in entry and set(entry) == {"id", "name", "folder", "config", "open_pending", "running_task"} \
        and entry["folder"] == real.path
    # a change of the file makes it unaccepted again, and the list still answers
    with open(ops.project_config.path(real.path), "ab") as f:
        f.write(b" ")
    [entry] = call(real, "GET", "/api/v1/projects")[2]["projects"]
    assert entry["config"]["accepted"] is False and entry["config"]["sha256"] != digest and "message" in entry
    # a folder that is not a project cannot be served at all
    outcome = io.StringIO()
    assert service.serve([str(real.tmp / "nothing")], port=0, out=outcome, ops_module=ops) == 3 and outcome.getvalue() == ""


def test_the_service_starts_on_a_configured_project_and_lists_it(real):
    ops.accept_config(real.path, ops.project_config.load(real.path)["sha256"])
    run = run_serve(ops, [real.path], FakeServer, poll_every=0)
    try:
        assert run.service.address == ("127.0.0.1", 4321)
        headers = {"Host": "127.0.0.1:4321", "Authorization": f"Bearer {run.service.token}"}
        status, _, payload = service.handle(run.service, "GET", "/api/v1/projects", headers, b"")
        listed = json.loads(payload)["projects"]
        assert status == 200 and [p["name"] for p in listed] == [os.path.basename(real.path)] and listed[0]["config"]["accepted"]
        printed = json.loads(run.out.getvalue())
        assert printed["projects"] == [{"id": listed[0]["id"], "name": listed[0]["name"]}]
        assert os.path.join(str(real.tree["data"]), "service.token") == printed["token_file"]
    finally:
        assert run.finish() == 0


def test_an_effect_is_approved_from_the_page_with_its_hash_and_never_from_chat(tree):  # noqa: F811
    case = gate_project(tree)
    path, item = case["path"], case["item"]
    assert item["kind"] == "effect" and ops.pending(path)["pending"][0]["actions"] == ["approved", "rejected"]
    projects = [{"id": service.project_id(path), "name": "p", "path": path}]
    world = types.SimpleNamespace(svc=service.Service(ops, projects, TOKEN, PORT, None, log=lambda line: None), projects=projects)
    target = api(world, f"/pending/{item['id']}/approve")
    # chat: refused, nothing sent
    said = ops.say(path, f"/approve {item['id']} {item['payload_sha256']}")["reply"]
    assert said.startswith("error: an effect is approved in the terminal, with its hash") and provider_calls(tree) == []
    with pytest.raises(ops.OpsError, match="an effect is approved in the terminal"):
        ops.approve(path, item["id"], item["payload_sha256"], channel="chat")
    # the request cannot name a channel, and an approval needs the hash
    assert call(world, "POST", target, {"sha256": item["payload_sha256"], "channel": "terminal"})[0] == 400
    assert call(world, "POST", target, {"sha256": item["payload_sha256"], "channel": "page"})[0] == 400
    assert provider_calls(tree) == []
    failed = wait_job(world, call(world, "POST", target, {})[2]["job"])
    assert failed["state"] == "failed" and failed["error"]["error"] == "usage" and "--sha256" in failed["error"]["message"]
    wrong = wait_job(world, call(world, "POST", target, {"sha256": "0" * 64})[2]["job"])
    assert wrong["error"]["error"] == "refused" and item["payload_sha256"] in wrong["error"]["message"] and provider_calls(tree) == []
    assert ops.pending(path, item["id"])["status"] == "open"
    # from the page, with the hash it showed: one commit, one pull request, and the decision is resolved
    done = wait_job(world, call(world, "POST", target, {"sha256": item["payload_sha256"]})[2]["job"])
    assert done["state"] == "done" and done["result"]["pull_request"]["number"] == 7
    assert [c["argv"][0] for c in provider_calls(tree)].count("open-pr") == 1
    assert ops.pending(path, item["id"])["status"] == "resolved"


# --- the shutdown -----------------------------------------------------------------------------------------------------


class FakeServer:
    """A server that opens no socket: serve() builds it, starts serve_forever in a thread and ends it with shutdown()."""

    instances = []

    def __init__(self, address, handler):
        self.requested = address
        self.RequestHandlerClass = handler
        self.server_address = ("127.0.0.1", 4321)
        self.down = threading.Event()
        self.closed = False
        FakeServer.instances.append(self)

    def serve_forever(self, poll_interval=0.5):
        self.down.wait(WAIT * 3)

    def shutdown(self):
        self.down.set()

    def server_close(self):
        self.closed = True


def run_serve(fake, projects, server_class, **kwargs):
    """serve() in a thread, ready when the service is built. finish() sets the stop and returns the exit code."""
    holder = types.SimpleNamespace(service=None, out=io.StringIO(), code=None, logs=[])
    ready = threading.Event()
    stop = threading.Event()

    def on_ready(svc):
        holder.service = svc
        ready.set()

    def target():
        holder.code = service.serve(projects, **{"port": 0, "poll_every": 0, "ops_module": fake, "stop": stop, "ready": on_ready,
                                                  "out": holder.out, "log": holder.logs.append, "server_class": server_class,
                                                  "interface_dir": None, **kwargs})

    holder.thread = threading.Thread(target=target)
    holder.thread.start()
    assert ready.wait(WAIT), "the service did not start"

    def finish():
        stop.set()
        holder.thread.join(WAIT * 3)
        assert not holder.thread.is_alive()
        return holder.code

    holder.finish, holder.stop = finish, stop
    return holder


def test_the_service_ends_the_runs_it_started_before_it_exits(tmp_path):
    fake = Standin(tmp_path / "data")
    project = tmp_path / "alpha"
    project.mkdir()
    run = run_serve(fake, [str(project)], FakeServer)
    svc = run.service
    server = FakeServer.instances[-1]
    assert server.requested == ("127.0.0.1", 0)                              # the only address it ever asks for
    # a job is running, and it ends only when the runs are ended
    fake.answers["say"] = lambda project, text, channel=None: fake.job_stop.wait(WAIT) and {"reply": "ended"}
    fake.stop_release.clear()                                                # stop_runs will take a while
    headers = {"Host": "127.0.0.1:4321", "Authorization": f"Bearer {svc.token}", "Origin": "http://127.0.0.1:4321",
               "Content-Type": "application/json"}
    body = json.dumps({"text": "go"}).encode()
    status, _, payload = service.handle(svc, "POST", f"/api/v1/projects/{svc.projects[0]['id']}/conversation",
                                        {**headers, "Content-Length": str(len(body))}, body)
    assert status == 202
    job = json.loads(payload)["job"]
    run.stop.set()                                                           # a signal
    assert fake.stop_entered.wait(WAIT) and fake.stopped >= 1
    time.sleep(0.2)
    assert run.thread.is_alive() and run.code is None                        # it does not exit before stop_runs returns
    assert svc.stopping.is_set() and server.down.is_set() and server.closed
    assert fake.job_stop.is_set() is False
    fake.stop_release.set()                                                  # stop_runs returns
    run.thread.join(WAIT * 3)
    assert not run.thread.is_alive() and run.code == 0
    assert svc.jobs[job]["state"] == "done" and svc.jobs[job]["result"] == {"reply": "ended"}   # the job ended with the runs
    assert not (tmp_path / "data" / "service.token").exists()
    # nothing starts after the stop
    status, _, payload = service.handle(svc, "POST", f"/api/v1/projects/{svc.projects[0]['id']}/conversation",
                                        {**headers, "Content-Length": str(len(body))}, body)
    assert status == 503 and json.loads(payload)["error"] == "stopping"
    # stop_runs is called at least once even when no job ever ran
    quiet = Standin(tmp_path / "data2")
    run = run_serve(quiet, [str(project)], FakeServer)
    assert run.finish() == 0 and quiet.stopped >= 1


def test_the_start_is_refused_for_a_bad_project_a_bad_port_and_a_bad_command_line(tmp_path, capsys):
    fake = Standin(tmp_path / "data")
    fake.answers["config"] = ops.OpsError(f"{tmp_path}/nothing is not a folder", 3)
    fake.config = lambda project: (_ for _ in ()).throw(fake.answers["config"])
    assert service.serve([str(tmp_path / "nothing")], port=0, ops_module=fake, server_class=FakeServer) == 3
    assert "nothing is not a folder" in capsys.readouterr().err
    busy = socket.socket()
    busy.bind(("127.0.0.1", 0))
    busy.listen(1)
    try:
        code = service.serve([str(tmp_path)], port=busy.getsockname()[1], ops_module=Standin(tmp_path / "d"), out=io.StringIO())
    finally:
        busy.close()
    assert code == 1 and "cannot listen" in capsys.readouterr().err and not (tmp_path / "d" / "service.token").exists()
    for argv in ([], ["--project"], ["--project", "x", "--port", "x"], ["--project", "x", "--port", "70000"],
                 ["--project", "x", "--poll-every", "-1"], ["--project", "x", "--dispatch-every", "0.5"], ["--project", "x", "extra"],
                 ["--project", "x", "--token"], ["--port", "8765"]):
        with pytest.raises(service.Refused):
            service.parse(argv)
    parsed = service.parse(["--project", "a", "--project", "b", "--port", "0", "--poll-every", "0", "--dispatch-every", "30",
                            "--token-file", "t"])
    assert parsed == {"projects": ["a", "b"], "port": 0, "poll_every": 0.0, "dispatch_every": 30.0, "token_file": "t"}
    assert service.parse(["--project", "a"])["dispatch_every"] == 30.0 and service.parse(["--project", "a"])["poll_every"] == 60.0  # dispatch is on by default (WP-9.14)
    assert service.parse(["--project", "a", "--no-dispatch"])["dispatch_every"] is None


def test_the_command_prints_its_help_and_refuses_an_unknown_call_and_a_missing_project(tmp_path):
    script = str(st.RUNTIME / "service.py")
    helped = subprocess.run([sys.executable, script, "--help"], capture_output=True, text=True, timeout=60)
    assert helped.returncode == 0 and helped.stdout.strip() == service.__doc__.strip() and "Traceback" not in helped.stderr
    for flag in ("--no-such-flag", "--host"):
        refused = subprocess.run([sys.executable, script, "--project", str(tmp_path), flag, "x"], capture_output=True, text=True, timeout=60)
        assert refused.returncode == 2 and "Traceback" not in refused.stderr
    assert subprocess.run([sys.executable, script], capture_output=True, text=True, timeout=60).returncode == 2
    missing = subprocess.run([sys.executable, script, "--project", str(tmp_path / "nothing")], capture_output=True, text=True, timeout=60)
    assert missing.returncode == 3 and str(tmp_path / "nothing") in missing.stderr and missing.stdout == ""


def test_the_policy_of_a_page_is_exactly_three_directives_and_never_allows_data():
    """The header is a security decision: `blob:` is there so that the page can show an image it fetched with the token
    (contracts/runtime.md, "The local service"); `default-src` and `frame-ancestors` are as they were."""
    assert service.CSP == "default-src 'self'; img-src 'self' blob:; frame-ancestors 'none'"
    assert [d.split()[0] for d in service.CSP.split("; ")] == ["default-src", "img-src", "frame-ancestors"]
    assert "data:" not in service.CSP and "unsafe" not in service.CSP and "http" not in service.CSP
    contract = (st.REPO / "contracts" / "runtime.md").read_text(encoding="utf-8")
    assert f"`Content-Security-Policy: {service.CSP}`" in contract
    assert all(d in contract for d in ("`default-src 'self'`", "`frame-ancestors 'none'`", "`img-src 'self' blob:`"))


# --- ADJ-B3 (A-39): the token file's path and the commands that read it, before the page holds a token -------------------------------

TOKEN_ROUTE = "/token-file"
HARD_PATH = "/home/demo/my shop/it's \"here\"/$HOME `x`/service.token"


def test_the_token_file_route_answers_the_path_and_the_commands_without_the_token_and_without_a_token(world):
    path = "/home/demo/shop/.openhora/service.token"
    world.svc.token_file = path
    status, headers, body = call(world, "GET", TOKEN_ROUTE, auth=False)
    assert status == 200 and headers["Content-Type"].startswith("application/json")
    assert body == {"token_file": path, "commands": {
        "macos": f"pbcopy < {path}", "linux": f"cat {path}", "powershell": f"Get-Content -LiteralPath '{path}' | Set-Clipboard"}}
    assert headers["Cache-Control"] == "no-store" and headers["X-Content-Type-Options"] == "nosniff"
    assert not [k for k in headers if k.lower().startswith("access-control")], "no CORS header, ever"
    assert world.fake.calls == [], "the route calls no operation: it answers from the service's own fact"
    # the same route with the bearer header is the same answer (a page that already holds a token may read it too)
    assert call(world, "GET", TOKEN_ROUTE)[2] == body


def test_the_commands_the_route_gives_for_a_hard_path_are_read_back_whole_by_the_shell(world):
    world.svc.token_file = HARD_PATH
    status, _, body = call(world, "GET", TOKEN_ROUTE, auth=False)
    assert status == 200 and body["token_file"] == HARD_PATH
    assert shlex.split(body["commands"]["macos"]) == ["pbcopy", "<", HARD_PATH]
    assert shlex.split(body["commands"]["linux"]) == ["cat", HARD_PATH]
    assert body["commands"]["powershell"] == "Get-Content -LiteralPath '/home/demo/my shop/it''s \"here\"/$HOME `x`/service.token' | Set-Clipboard"


@pytest.mark.parametrize("path", ["/home/demo/a\nb/service.token", "/home/demo/a\x00b", "/home/demo/a\x1b[2Jb", "/home/demo/a\rb",
                                  "/home/\udcff/x"])  # the last: a folder name that is not valid UTF-8, read with surrogateescape
def test_a_path_with_a_control_character_gives_no_path_and_no_command(world, path):
    world.svc.token_file = path
    status, _, body = call(world, "GET", TOKEN_ROUTE, auth=False)
    assert (status, body) == (200, {"token_file": None, "commands": None}), "the page then keeps its sentence about the first line"


def test_a_service_that_has_no_token_file_does_not_know_the_route(world):
    assert world.svc.token_file is None
    status, _, body = call(world, "GET", TOKEN_ROUTE, auth=False)
    assert (status, body["error"]) == (404, "not_found")


def test_the_token_file_route_is_under_the_same_host_and_origin_check_as_every_route(world):
    world.svc.token_file = "/home/demo/shop/service.token"
    for host in ("evil.example:8765", "localhost:9999", "127.0.0.1", "127.0.0.1:8765.evil.example", "[::1]:8765"):
        status, _, body = call(world, "GET", TOKEN_ROUTE, auth=False, extra={"Host": host})
        assert (status, body["error"]) == (403, "host"), host
    for origin in ("http://evil.example", "https://127.0.0.1:8765", "http://127.0.0.1:9999", "null", "http://localhost:8765.evil.example"):
        status, _, body = call(world, "GET", TOKEN_ROUTE, auth=False, extra={"Origin": origin})
        assert (status, body["error"]) == (403, "origin"), origin
    for origin in (f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"):
        assert call(world, "GET", TOKEN_ROUTE, auth=False, extra={"Origin": origin})[0] == 200
    assert call(world, "GET", TOKEN_ROUTE, auth=False, extra={"Host": f"localhost:{PORT}"})[0] == 200
    assert world.fake.calls == []


def test_the_token_file_route_takes_get_only_and_no_query(world):
    world.svc.token_file = "/home/demo/shop/service.token"
    for method in ("OPTIONS", "HEAD", "PUT", "DELETE", "PATCH"):
        status, headers, body = call(world, method, TOKEN_ROUTE, auth=False)
        assert (status, body["error"]) == (405, "method"), method
        assert not [k for k in headers if k.lower().startswith("access-control")]
    status, _, body = call(world, "POST", TOKEN_ROUTE, {}, auth=False)
    assert (status, body["error"]) == (405, "method")
    for tail in ("?x=1", f"?token={TOKEN}", "?"):
        assert call(world, "GET", TOKEN_ROUTE + tail, auth=False)[0] == (400 if tail != "?" else 200), tail
    for other in ("/token-file/", "/token-file.json", "/api/v1/token-file", "/TOKEN-FILE"):
        assert call(world, "GET", other, auth=False)[0] in (401, 404), other


def test_no_answer_to_a_request_without_the_token_carries_the_token(world):
    world.svc.token_file = HARD_PATH
    seen = []
    for method, path, extra in (("GET", TOKEN_ROUTE, None), ("GET", TOKEN_ROUTE + f"?token={TOKEN}", None), ("GET", TOKEN_ROUTE, {"Host": "evil.example"}),
                                ("GET", TOKEN_ROUTE, {"Origin": "http://evil.example"}), ("POST", TOKEN_ROUTE, None),
                                ("GET", "/", None), ("GET", "/api/v1/projects", None), ("GET", "/nothing", None)):
        status, headers, payload = call(world, method, path, {} if method == "POST" else None, auth=False, extra=extra)
        seen += [json.dumps(payload) if isinstance(payload, (dict, list)) else payload.decode("utf-8"), json.dumps(headers)]
    world.svc.token_file = None
    seen.append(json.dumps(call(world, "GET", TOKEN_ROUTE, auth=False)[2]))
    assert not [s for s in seen if TOKEN in s]
    assert TOKEN not in repr(world.svc) and TOKEN not in service.__doc__


def test_a_served_service_gives_its_token_files_path_over_a_real_socket_and_never_its_content(tmp_path, monkeypatch):
    fake = Standin(tmp_path / "data")
    project = tmp_path / "alpha"
    project.mkdir()
    monkeypatch.chdir(tmp_path)
    run = run_serve(fake, [str(project)], service.Server, token_file="some folder/t.token", interface_dir=str(tmp_path))
    try:
        svc = run.service
        expected = str(tmp_path / "some folder" / "t.token")
        connection = http.client.HTTPConnection("127.0.0.1", svc.port, timeout=WAIT)
        connection.request("GET", TOKEN_ROUTE)
        answer = connection.getresponse()
        raw = answer.read().decode("utf-8")
        body = json.loads(raw)
        assert answer.status == 200 and answer.getheader("Cache-Control") == "no-store"
        assert not [h for h, _ in answer.getheaders() if h.lower().startswith("access-control")]
        assert svc.token not in raw and svc.token not in json.dumps(answer.getheaders())
        assert os.path.realpath(body["token_file"]) == os.path.realpath(expected) and os.path.isabs(body["token_file"]), "an absolute path, whatever --token-file was"
        assert shlex.split(body["commands"]["linux"]) == ["cat", body["token_file"]]
        assert open(body["token_file"], encoding="utf-8").read() == svc.token + "\n", "and the path is the file that holds the token"
        connection.close()
        connection = http.client.HTTPConnection("127.0.0.1", svc.port, timeout=WAIT)
        connection.putrequest("GET", TOKEN_ROUTE, skip_host=True)
        connection.putheader("Host", "evil.example")
        connection.endheaders()
        assert connection.getresponse().status == 403
        connection.close()
        assert svc.token not in run.out.getvalue()
    finally:
        assert run.finish() == 0


def test_the_service_spells_no_command_and_the_contract_names_the_route():
    assert "/token-file" in service.__doc__, "the rules list names the route"
    source = (st.RUNTIME / "service.py").read_text(encoding="utf-8")
    assert "operations.token_commands" in source, "the commands come from the one place that spells commands"
    assert not re.search(r"shlex|pbcopy|Set-Clipboard", source), "the service spells no command of its own"
    contract = (st.REPO / "contracts" / "runtime.md").read_text(encoding="utf-8")
    assert "`GET /token-file`" in contract and "any local process" in contract, "the contract records who can read the path, and why that is accepted"


def test_the_answer_is_the_same_whether_the_token_file_is_there_absent_or_unreadable_because_the_route_never_reads_it(world, tmp_path):
    folder = tmp_path / "shop"
    folder.mkdir()
    target = folder / "service.token"
    target.write_text(TOKEN + "\n", encoding="utf-8")
    world.svc.token_file = str(target)
    present = call(world, "GET", TOKEN_ROUTE, auth=False)[2]
    target.chmod(0)
    try:
        unreadable = call(world, "GET", TOKEN_ROUTE, auth=False)[2]
    finally:
        target.chmod(0o600)
    target.unlink()
    absent = call(world, "GET", TOKEN_ROUTE, auth=False)[2]
    assert present == unreadable == absent and present["token_file"] == str(target)
    assert TOKEN not in json.dumps([present, unreadable, absent])
    source = (st.RUNTIME / "service.py").read_text(encoding="utf-8")
    body = source[source.index("def _token_file("):source.index("def _static(")]
    assert not re.search(r"\bopen\(|os\.stat|os\.path\.(?:exists|isfile)|read_text", body), "the route's function touches no file"
