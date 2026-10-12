"""Tests of how the local service starts (WP-9.14, items A-6 and A-9): it dispatches by default, every 30 seconds, and
a flag turns that off; it checks the secret store, the credential, docker and the eval image at its start, says what is
missing on standard error after the JSON line, and `connections` carries the answer. Offline; invented names.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_service_start.py
"""
from __future__ import annotations

import threading

import pytest

import standin_tree as st
from test_read_ops import tree  # noqa: F401  (the stand-in project the read operations are tested on)
from test_service import FakeServer, Standin, run_serve, service

dispatcher = st.load("dispatcher")
ops = st.load("ops")
operations = st.load("operations")

OK = {"secret_store": "ok", "credential": "ok", "docker": "ok", "image": "ok", "dispatch": "every 30 s", "problems": [],
      "start": "uv run --with keyring==25.7.0 python3 /w/runtime/service.py --project /p", "at": "2026-10-08T10:00:00+00:00"}
NO_STORE = dict(OK, secret_store="/usr/bin/python3 (Python 3.9.6) cannot read the secret store: ModuleNotFoundError: No module named 'keyring'",
                credential="the reference model's credential (EXAMPLE_KEY) is neither set nor found in the secret store")


@pytest.fixture(autouse=True)
def no_service():
    ops.SERVICE.clear()
    yield
    ops.SERVICE.clear()


# --- A-6: the flags --------------------------------------------------------------------------------------------------


def test_the_service_dispatches_every_thirty_seconds_unless_told_not_to():
    assert service.DISPATCH_EVERY == 30.0
    assert service.parse(["--project", "a"])["dispatch_every"] == 30.0
    assert service.parse(["--project", "a", "--dispatch-every", "5"])["dispatch_every"] == 5.0
    assert service.parse(["--project", "a", "--no-dispatch"])["dispatch_every"] is None
    assert service.parse(["--project", "a", "--dispatch-every", "0"])["dispatch_every"] == 0.0  # 0 was always off
    for argv in (["--project", "a", "--no-dispatch", "--dispatch-every", "5"], ["--project", "a", "--dispatch-every", "5", "--no-dispatch"]):
        with pytest.raises(service.Refused, match="--no-dispatch"):
            service.parse(argv)
    with pytest.raises(service.Refused):
        service.parse(["--project", "a", "--no-dispatch", "yes"])  # a flag takes no value: "yes" is an unknown argument


def test_main_hands_serve_the_default_or_nothing(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(service, "serve", lambda projects, port, poll_every, dispatch_every, token_file: seen.append(dispatch_every) or 0)
    assert service.main(["--project", str(tmp_path)]) == 0 and service.main(["--project", str(tmp_path), "--no-dispatch"]) == 0
    assert service.main(["--project", str(tmp_path), "--dispatch-every", "0"]) == 0
    assert seen == [30.0, None, None]


def test_the_help_and_the_docstring_say_it(capsys):
    assert service.main(["--help"]) == 0
    said = capsys.readouterr().out
    assert "--no-dispatch" in said and "30" in said and "off unless given" not in said
    assert "uv run --with keyring==25.7.0 python3 runtime/service.py" in said


def test_serve_starts_the_dispatch_loop_by_default_and_not_with_none(tmp_path, monkeypatch):
    loops = []
    monkeypatch.setattr(service, "dispatch_loop", lambda svc, every, stop, op="dispatch": loops.append((op, every)))
    fake = Standin(tmp_path / "d")
    project = tmp_path / "p"
    project.mkdir()
    run = run_serve(fake, [str(project)], FakeServer)
    assert run.finish() == 0
    # the dispatch loop, and the loop that routes the lines and requests queued while a run held the project
    assert loops == [("dispatch", 30.0), ("route_queued", service.QUEUE_EVERY)]
    loops.clear()
    run = run_serve(fake, [str(project)], FakeServer, dispatch_every=None)
    assert run.finish() == 0 and loops == [("route_queued", service.QUEUE_EVERY)]  # queued lines are routed without dispatch


# --- A-9: the check at the start -------------------------------------------------------------------------------------


def started(tmp_path, answer, **kwargs):
    fake = Standin(tmp_path / "d")
    fake.answers["service_check"] = answer
    project = tmp_path / "p"
    project.mkdir(exist_ok=True)
    return fake, run_serve(fake, [str(project)], FakeServer, **kwargs), str(project)


def test_the_service_checks_each_project_at_its_start_and_says_what_it_found_after_the_json_line(tmp_path):
    fake, run, project = started(tmp_path, OK, dispatch_every=30.0)
    try:
        assert fake.named("service_check") == [("service_check", project, {"dispatch_every": 30.0})]
        assert run.out.getvalue().count("\n") == 1  # the one JSON line on standard output, as before
        text = "\n".join(run.logs)
        for word in ("secret store", "credential", "docker", "image", "dispatch"):
            assert word in text
        assert "every 30 s" in text and "uv run" not in text  # nothing is missing: no start line
    finally:
        assert run.finish() == 0


def test_an_unreadable_secret_store_puts_the_uv_form_on_the_first_lines(tmp_path):
    fake, run, project = started(tmp_path, NO_STORE, dispatch_every=30.0)
    try:
        first = "\n".join(run.logs[:3])
        assert "uv run --with keyring==25.7.0 python3 /w/runtime/service.py --project /p" in first
        assert "cannot read the secret store" in "\n".join(run.logs)
        assert "EXAMPLE_KEY" in "\n".join(run.logs)
    finally:
        assert run.finish() == 0


def test_a_service_that_dispatches_nothing_tells_the_check_so(tmp_path):
    fake, run, project = started(tmp_path, dict(OK, dispatch="off"), dispatch_every=None)
    try:
        assert fake.named("service_check")[0][2] == {"dispatch_every": 0}
        assert "dispatch" in "\n".join(run.logs) and "off" in "\n".join(run.logs)
    finally:
        assert run.finish() == 0


def test_a_check_that_fails_does_not_stop_the_service(tmp_path):
    fake, run, project = started(tmp_path, ops.OpsError("the check broke", 1), dispatch_every=30.0)
    try:
        assert "the check broke" in "\n".join(run.logs)
        assert run.service is not None
    finally:
        assert run.finish() == 0


def test_connections_carries_what_the_service_found(tree, monkeypatch):  # noqa: F811
    path = str(tree["project"])
    assert ops.connections(path)["service"] is None
    monkeypatch.setattr(dispatcher, "inspect", lambda module: {
        "secret_store": "ok", "credential": "the reference model's credential (EXAMPLE_KEY) is neither set nor found in the secret store",
        "tools": {"docker": None, "uv": "/bin/uv", "git": "/bin/git"}, "modules": {"mcp.py": "ImportError: broken"}, "lab": "ok"})
    monkeypatch.setenv(operations.UV_MARK, "0")
    report = ops.service_check(path, 30)
    got = ops.connections(path)["service"]
    assert got == report
    assert got["secret_store"] == "ok" and "EXAMPLE_KEY" in got["credential"] and got["dispatch"] == "every 30 s"
    assert got["docker"] != "ok" and "docker" in got["docker"]
    assert got["problems"] == ["mcp.py: ImportError: broken"]
    assert got["start"] == f"uv run --with keyring==25.7.0 python3 {tree['tree']}/runtime/service.py --project {path}"
    assert ops.service_check(path, 0)["dispatch"] == "off" and ops.connections(path)["service"]["dispatch"] == "off"
    ops.SERVICE.clear()
    assert ops.service_check(path)["dispatch"] == "not a service" and ops.connections(path)["service"] is None  # a terminal check remembers nothing


def test_the_check_verb_of_the_scheduler_entry_reports_what_the_service_reads(tmp_path):
    report = dispatcher.inspect(ops)
    assert set(report) == {"python", "executable", "modules", "lab", "secret_store", "credential", "tools"}
    assert report["modules"]["ops.py"] == "ok" and set(report["tools"]) == {"docker", "uv", "git"}


def test_the_documents_say_what_the_review_asked(capsys):
    assert service.main(["--help"]) == 0
    said = capsys.readouterr().out
    assert "scheduler's two jobs" in said and "this service's own fact" in said
    readme = (st.REPO / "runtime" / "README.md").read_text(encoding="utf-8")
    assert "should be served with `--no-dispatch`" in readme
    contract = (st.REPO / "contracts" / "runtime.md").read_text(encoding="utf-8")
    assert "dispatch off in this service" in contract
    assert "token-gated page only" in contract and "never carries a secret's value" in contract


def test_a_verdict_of_the_service_check_is_bounded(tree, monkeypatch):  # noqa: F811
    path = str(tree["project"])
    monkeypatch.setattr(dispatcher, "inspect", lambda module: {
        "secret_store": "x" * 5000 + "\n", "credential": "ok", "tools": {"docker": "/bin/docker"},
        "modules": {"mcp.py": "y" * 5000}, "lab": "ok"})
    got = ops.service_check(path, 30)
    assert len(got["secret_store"]) <= 300 and "\n" not in got["secret_store"] and len(got["problems"][0]) <= 300
