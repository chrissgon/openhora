"""Tests of the Microsoft To Do reader (providers/tasks/microsoft.py, class integration:tasks; package CB-4). Against the stand-in service (fake_graph_tasks.py) on 127.0.0.1: no Microsoft host is
reached and no real credential exists. The reader lists the person's task lists (marking the one Graph calls `defaultList`) and the tasks of one list that are not completed, GET only, on two
paths, with no OData parameter (the pages read do not say which To Do takes); it needs the account record with the platform's six permissions (a token of the five of before To Do tasks is
refused with the authorize command named), follows a next-page address only when it is the request's own, prints no task title on stderr, and prints a title on one line.

Run: uv run --with pytest==9.1.1 pytest providers/tasks/tests/test_tasks_microsoft.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(HERE))
import fake_graph_tasks as fm  # noqa: E402

READER = REPO / "providers" / "tasks" / "microsoft.py"
_spec = importlib.util.spec_from_file_location("tasks_microsoft_under_test", READER)
reader = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(reader)
LISTS = fm.GRAPH + "/me/todo/lists"


@pytest.fixture
def fake():
    f = fm.FakeGraphTasks()
    f.add_task(fm.DEFAULT_LIST, "t1", "buy coffee")
    f.add_task(fm.DEFAULT_LIST, "t2", "call the dentist", status="inProgress")
    f.add_task(fm.DEFAULT_LIST, "t3", "an old one", status="completed")
    f.add_task(fm.OTHER_LIST, "g1", "oat milk")
    yield f
    f.close()


def env_of(fake, tmp_path, record=None, **extra):
    kept = {k: v for k, v in os.environ.items() if not k.startswith(("MICROSOFT_", "OUTLOOK_", "WRITER_", "INTEGRATION_", "MAILBOX_", "OPENHORA_"))}
    kept.update({"HOME": str(tmp_path / "home"), "MICROSOFT_ACCOUNT_TOKEN": record or fake.record_json(), **fake.env()})
    kept.update(extra)
    return kept


def run(fake, tmp_path, *args, record=None, env=None):
    proc = subprocess.run([sys.executable, str(READER), *args], env=env or env_of(fake, tmp_path, record), capture_output=True, text=True, timeout=60)
    for stream in (proc.stdout, proc.stderr):    # no run ever prints a credential, not even partially (limit L59)
        for secret in fm.SECRETS:
            assert secret not in stream and secret[:16] not in stream, args
    return proc


def out(proc):
    assert proc.returncode == 0, (proc.returncode, proc.stderr)
    return json.loads(proc.stdout)


def paths(fake):
    return [(r["method"], r["path"]) for r in fake.graph_requests()]


# --- the verbs ----------------------------------------------------------------------------------------------------------------------------------


def test_lists_marks_the_default_list_graph_names_and_no_other(fake, tmp_path):
    shown = out(run(fake, tmp_path, "lists"))
    assert shown == {"lists": [{"id": fm.DEFAULT_LIST, "name": "Tasks", "default": True}, {"id": fm.OTHER_LIST, "name": "Groceries", "default": False},
                               {"id": fm.FLAGGED_LIST, "name": "Flagged email", "default": False}], "truncated": False, "skipped": 0, "external_content": True}
    assert paths(fake) == [("GET", LISTS)] and fake.graph_requests()[0]["query"] == {}


def test_open_prints_the_tasks_that_are_not_completed_and_sends_no_odata_parameter(fake, tmp_path):
    shown = out(run(fake, tmp_path, "open", "--list", fm.DEFAULT_LIST))
    assert [t["id"] for t in shown["tasks"]] == ["t1", "t2"] and shown["skipped"] == 1 and shown["truncated"] is False and shown["list"] == fm.DEFAULT_LIST
    assert shown["tasks"][0] == {"id": "t1", "title": "buy coffee", "updated": "2026-10-27T12:00:00.0000000Z", "etag": 'W/"etag1001=="'}
    [(method, path)] = paths(fake)
    assert (method, path) == ("GET", f"{LISTS}/{fm.DEFAULT_LIST}/tasks") and fake.graph_requests()[0]["query"] == {}
    for word in ("due", "body", "categories", "importance"):
        assert word not in json.dumps(shown)
    assert fake.unexpected() == [] and all(r["if_match"] is None for r in fake.graph_requests())


def test_open_with_default_finds_the_default_list_first_and_reads_that_one(fake, tmp_path):
    shown = out(run(fake, tmp_path, "open", "--list", "default", "--max", "1"))
    assert shown["list"] == fm.DEFAULT_LIST and [t["id"] for t in shown["tasks"]] == ["t1"] and shown["truncated"] is True
    assert paths(fake) == [("GET", LISTS), ("GET", f"{LISTS}/{fm.DEFAULT_LIST}/tasks")]


def test_open_with_default_when_graph_marks_no_default_is_exit_1(fake, tmp_path):
    fake.lists[fm.DEFAULT_LIST] = ("Tasks", "none")
    proc = run(fake, tmp_path, "open", "--list", "default")
    assert proc.returncode == 1 and "default" in proc.stderr and paths(fake) == [("GET", LISTS)]


def test_the_pages_are_followed_by_the_next_page_address_and_a_cap_marks_the_answer_truncated(fake, tmp_path):
    for n in range(7):
        fake.add_task(fm.OTHER_LIST, f"x{n}", f"task {n}")
    fake.page_cap = 3
    shown = out(run(fake, tmp_path, "open", "--list", fm.OTHER_LIST, "--max", "100"))
    assert len(shown["tasks"]) == 8 and shown["truncated"] is False
    requests = [r for r in fake.graph_requests() if r["path"].endswith("/tasks")]
    assert [r["query"].get("$skip") for r in requests] == [None, "3", "6"], "each next page came from the address Graph named"
    fake.requests.clear()
    shown = out(run(fake, tmp_path, "open", "--list", fm.OTHER_LIST, "--max", "4"))
    assert len(shown["tasks"]) == 4 and shown["truncated"] is True and len(fake.graph_requests()) == 2


def test_a_next_page_address_on_another_host_is_not_followed_and_the_answer_is_truncated(fake, tmp_path):
    for n in range(5):
        fake.add_task(fm.OTHER_LIST, f"y{n}", f"task {n}")
    fake.page_cap, fake.link_base = 2, "http://127.0.0.1:1"
    proc = run(fake, tmp_path, "open", "--list", fm.OTHER_LIST)
    shown = out(proc)
    assert len(shown["tasks"]) == 2 and shown["truncated"] is True and "note:" in proc.stderr
    assert len(fake.graph_requests()) == 1, "the foreign address received nothing"


def test_a_title_is_one_line_with_control_and_invisible_characters_removed_and_cut_at_200(fake, tmp_path):
    fake.add_task(fm.OTHER_LIST, "g2", "line one\nline\ttwo\u202e\u200b \x1b[2J hidden" + "x" * 300)
    title = next(t["title"] for t in out(run(fake, tmp_path, "open", "--list", fm.OTHER_LIST))["tasks"] if t["id"] == "g2")
    assert title.startswith("line one line two") and "\n" not in title and "\u202e" not in title and "\u200b" not in title and "\x1b" not in title and len(title) == 200


def test_no_title_is_ever_written_to_stderr(fake, tmp_path):
    fake.add_task(fm.OTHER_LIST, "g9", "secret-sounding private title")
    for args in (("open", "--list", fm.OTHER_LIST), ("lists",), ("open", "--list", "not a list id")):
        proc = run(fake, tmp_path, *args)
        assert "secret-sounding" not in proc.stderr and "buy coffee" not in proc.stderr
    fake.fail_get_next = 500
    proc = run(fake, tmp_path, "open", "--list", fm.DEFAULT_LIST)
    assert proc.returncode == 1 and "buy coffee" not in proc.stderr


def test_check_reads_the_list_of_lists_and_prints_the_six_permissions(fake, tmp_path):
    shown = out(run(fake, tmp_path, "--check"))
    assert shown["ok"] is True and shown["scope"] == " ".join(fm.PLATFORM) and shown["record"] == "account" and shown["tenant"] == fm.TENANT
    assert paths(fake) == [("GET", LISTS)]


# --- the permissions: the six ------------------------------------------------------------------------------------------------------------------


def test_a_token_of_the_five_of_before_to_do_is_refused_with_the_authorize_command_and_nothing_is_read(fake, tmp_path):
    record = fake.record_json(scope=" ".join(fm.PREVIOUS))
    for args in (("--check",), ("lists",), ("open", "--list", "default")):
        proc = run(fake, tmp_path, *args, record=record)
        assert proc.returncode == 3 and "microsoft_auth.py authorize" in proc.stderr and "Tasks.ReadWrite" in proc.stderr, (args, proc.stderr)
    assert fake.requests == [], "the record was refused before any call, the token endpoint included"


def test_a_refresh_that_comes_back_with_the_five_or_another_set_is_refused(fake, tmp_path):
    for granted in (fm.GRANTED_PREVIOUS, fm.GRANTED + " " + fm.PREFIX + "Mail.Read", " ".join(fm.PREFIX + n for n in fm.PLATFORM[1:]) + " offline_access"):
        fake.scope_granted = granted
        proc = run(fake, tmp_path, "lists")
        assert proc.returncode == 3 and "authorize" in proc.stderr, granted
    assert fake.graph_requests() == []


def test_the_refresh_names_the_six_permissions(fake, tmp_path):
    out(run(fake, tmp_path, "lists"))
    [form] = fake.token_forms
    assert set(form["scope"].split()) == {fm.PREFIX + n for n in fm.PLATFORM} | {"offline_access"} and "client_secret" not in form


# --- only GET, only two paths -----------------------------------------------------------------------------------------------------------------


def test_only_get_reaches_graph_and_the_token_endpoint_is_the_one_post(fake, tmp_path):
    out(run(fake, tmp_path, "lists"))
    out(run(fake, tmp_path, "open", "--list", fm.DEFAULT_LIST))
    assert {r["method"] for r in fake.graph_requests()} == {"GET"} and fake.unexpected() == []


def test_the_request_check_refuses_anything_outside_the_allow_list_before_a_connection():
    assert reader.ALLOWED == (("GET", r"/me/todo/lists"), ("GET", r"/me/todo/lists/(?:[A-Za-z0-9_-]|%3D)+/tasks"))
    for entry, path in ((("POST", reader.LIST_TASKS[1]), "/me/todo/lists/x/tasks"), (reader.LIST_TASKS, "/me/todo/lists/x/tasks/y"), (reader.LIST_TASKS, "/me/todo/lists/x/y/tasks"),
                        (reader.LIST_LISTS, "/me/todo/lists/x"), (("DELETE", reader.LIST_TASKS[1]), "/me/todo/lists/x/tasks"), (reader.LIST_TASKS, "/me/todo/lists/../tasks")):
        with pytest.raises(reader.ProviderError) as refused:
            reader.check_request(entry, path)
        assert refused.value.code == 2 and "allow-list" in str(refused.value)


def test_an_id_is_percent_encoded_and_a_bad_one_is_a_usage_error_before_any_call(fake, tmp_path):
    out(run(fake, tmp_path, "open", "--list", fm.OTHER_LIST))
    assert paths(fake)[-1] == ("GET", f"{LISTS}/{fm.OTHER_LIST}/tasks")
    assert fake.graph_requests()[-1]["raw_path"].startswith(f"{LISTS}/AAMkADIyAAAEFTTrJAAA%3D/tasks")
    before = len(fake.requests)
    for bad in ("../x", "a/b", "a b", "-x", "", "x" * 301):
        assert run(fake, tmp_path, "open", "--list", bad).returncode == 2, bad
    assert len(fake.requests) == before


def test_a_redirect_is_not_followed(fake, tmp_path):
    fake.redirect_next = True
    proc = run(fake, tmp_path, "lists")
    assert proc.returncode == 1 and "redirect" in proc.stderr and len(fake.graph_requests()) == 1


def test_a_busy_service_is_reported_with_its_retry_after_and_is_not_retried(fake, tmp_path):
    fake.fail_get_next = 429
    proc = run(fake, tmp_path, "lists")
    assert proc.returncode == 1 and "busy" in proc.stderr and len(fake.graph_requests()) == 1


def test_the_flags_of_a_verb_are_checked(fake, tmp_path):
    for args in (("open",), ("lists", "--list", "default"), ("--check", "lists"), (), ("open", "--list", "default", "--max", "0"), ("open", "--list", "default", "--max", "101")):
        assert run(fake, tmp_path, *args).returncode == 2, args
    assert run(fake, tmp_path, "--help").returncode == 0


def test_vacuity_a_reader_that_kept_completed_tasks_would_fail_the_open_test(fake, monkeypatch):
    """The oracle: with the status test removed, the completed task of the fixture would be printed, so the open test above does see the difference."""
    monkeypatch.setattr(reader, "task_of", lambda item: {"id": item["id"], "title": item.get("title"), "updated": None, "etag": None})
    printed = [reader.task_of(t)["id"] for t in fake.tasks[fm.DEFAULT_LIST].values()]
    assert printed == ["t1", "t2", "t3"] and printed != ["t1", "t2"]
