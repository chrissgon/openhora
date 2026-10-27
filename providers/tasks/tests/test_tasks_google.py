"""Tests of the Google Tasks reader (providers/tasks/google.py, class integration:tasks; package CB-4). Against the stand-in service (fake_gtasks.py) on 127.0.0.1: no Google host is
reached and no real credential exists. The reader lists the person's task lists and the open tasks of one list, GET only, on two paths; it needs the account record with the platform's five
scopes (a token of the four of before Google Tasks is refused with the authorize command named), asks the service for no due date, note or parent, prints no task title on stderr, and
prints a title on one line with control and invisible characters removed.

Run: uv run --with pytest==9.1.1 pytest providers/tasks/tests/test_tasks_google.py
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
import fake_gtasks as fg  # noqa: E402

READER = REPO / "providers" / "tasks" / "google.py"
_spec = importlib.util.spec_from_file_location("tasks_google_under_test", READER)
reader = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(reader)


@pytest.fixture
def fake():
    f = fg.FakeGoogleTasks()
    f.add_task(fg.DEFAULT_LIST, "t1", "buy coffee")
    f.add_task(fg.DEFAULT_LIST, "t2", "call the dentist")
    f.add_task(fg.DEFAULT_LIST, "t3", "an old one", status="completed")
    f.add_task(fg.OTHER_LIST, "g1", "oat milk")
    yield f
    f.close()


def env_of(fake, tmp_path, record=None, **extra):
    kept = {k: v for k, v in os.environ.items() if not k.startswith(("GMAIL_", "GOOGLE_", "WRITER_", "INTEGRATION_", "OPENHORA_"))}
    kept.update({"HOME": str(tmp_path / "home"), "GOOGLE_ACCOUNT_TOKEN": record or fake.record_json(), **fake.env()})
    kept.update(extra)
    return kept


def run(fake, tmp_path, *args, record=None, env=None):
    proc = subprocess.run([sys.executable, str(READER), *args], env=env or env_of(fake, tmp_path, record), capture_output=True, text=True, timeout=60)
    for stream in (proc.stdout, proc.stderr):    # no run ever prints a credential, not even partially (limit L59)
        for secret in fg.SECRETS:
            assert secret not in stream and secret[:16] not in stream, args
    return proc


def out(proc):
    assert proc.returncode == 0, (proc.returncode, proc.stderr)
    return json.loads(proc.stdout)


# --- the verbs ----------------------------------------------------------------------------------------------------------------------------------


def test_lists_prints_the_lists_with_no_default_marked_because_the_reference_marks_none(fake, tmp_path):
    shown = out(run(fake, tmp_path, "lists"))
    assert shown == {"lists": [{"id": fg.DEFAULT_LIST, "name": "My Tasks", "default": None}, {"id": fg.OTHER_LIST, "name": "Groceries", "default": None}],
                     "truncated": False, "skipped": 0, "external_content": True}
    [(method, path, query, _)] = fake.calls()
    assert (method, path) == ("GET", fg.LISTS) and query == {"maxResults": "100", "fields": "items(id,title),nextPageToken"}


def test_open_prints_only_the_open_tasks_of_the_list_and_asks_for_no_due_date_note_or_parent(fake, tmp_path):
    shown = out(run(fake, tmp_path, "open", "--list", fg.DEFAULT_LIST))
    assert [t["id"] for t in shown["tasks"]] == ["t1", "t2"] and shown["truncated"] is False and shown["list"] == fg.DEFAULT_LIST
    assert shown["tasks"][0] == {"id": "t1", "title": "buy coffee", "updated": "2026-10-27T12:00:00.000Z", "etag": '"LTE1001"'}
    [(method, path, query, body)] = fake.calls()
    assert (method, path, body) == ("GET", f"/tasks/v1/lists/{fg.DEFAULT_LIST}/tasks", None)
    assert query["showCompleted"] == "false" and query["showHidden"] == "false" and query["showDeleted"] == "false" and query["maxResults"] == "100"
    asked = query["fields"]
    for word in ("due", "notes", "parent", "links", "assignmentInfo"):
        assert word not in asked, asked
    assert "due" not in json.dumps(shown) and fake.unexpected() == []


def test_open_with_default_sends_the_literal_at_default_and_reads_the_default_list(fake, tmp_path):
    shown = out(run(fake, tmp_path, "open", "--list", "default", "--max", "1"))
    assert shown["list"] == "default" and [t["id"] for t in shown["tasks"]] == ["t1"] and shown["truncated"] is True
    [(_, path, query, _)] = fake.calls()
    assert path == "/tasks/v1/lists/@default/tasks" and query["maxResults"] == "1"


def test_a_task_that_comes_completed_hidden_or_deleted_anyway_is_left_out_and_counted(fake, tmp_path):
    fake.add_task(fg.DEFAULT_LIST, "t4", "hidden", status="needsAction", hidden=True)
    fake.add_task(fg.DEFAULT_LIST, "t5", "gone", deleted=True)
    shown = out(run(fake, tmp_path, "open", "--list", fg.DEFAULT_LIST))
    assert [t["id"] for t in shown["tasks"]] == ["t1", "t2"]
    fake.page_cap = None
    # a stand-in that ignores the filters (a service answering more than was asked) is still read as open tasks only
    for task in fake.tasks[fg.DEFAULT_LIST].values():
        task.pop("hidden", None)
        task.pop("deleted", None)
    task = reader.task_of({"id": "z1", "title": "x", "status": "completed"})
    assert task is None and reader.task_of({"id": "z1", "title": "x", "status": "needsAction", "hidden": True}) is None and reader.task_of({"id": "z1", "status": "needsAction", "deleted": True}) is None


def test_the_next_page_marks_the_answer_truncated(fake, tmp_path):
    fake.page_cap = 1
    shown = out(run(fake, tmp_path, "open", "--list", fg.DEFAULT_LIST))
    assert len(shown["tasks"]) == 1 and shown["truncated"] is True and len(fake.calls()) == 1, "one page is read, never more"


def test_a_title_is_one_line_with_control_and_invisible_characters_removed_and_cut_at_200(fake, tmp_path):
    fake.add_task(fg.OTHER_LIST, "g2", "line one\nline\ttwo\u202e\u200b \x1b[2J hidden" + "x" * 300)
    shown = out(run(fake, tmp_path, "open", "--list", fg.OTHER_LIST))
    title = next(t["title"] for t in shown["tasks"] if t["id"] == "g2")
    assert title.startswith("line one line two") and "\n" not in title and "\u202e" not in title and "\u200b" not in title and "\x1b" not in title and len(title) == 200


def test_no_title_is_ever_written_to_stderr(fake, tmp_path):
    fake.add_task(fg.OTHER_LIST, "g9", "secret-sounding private title")
    for args in (("open", "--list", fg.OTHER_LIST), ("lists",), ("open", "--list", "not a list id")):
        proc = run(fake, tmp_path, *args)
        assert "secret-sounding" not in proc.stderr and "buy coffee" not in proc.stderr
    fake.fail_get_next = 500
    proc = run(fake, tmp_path, "open", "--list", fg.DEFAULT_LIST)
    assert proc.returncode == 1 and "buy coffee" not in proc.stderr and "Google returned 500" in proc.stderr


def test_check_reads_one_list_entry_and_prints_the_five_scopes(fake, tmp_path):
    shown = out(run(fake, tmp_path, "--check"))
    assert shown == {"ok": True, "scope": sorted(fg.PLATFORM_SET), "account": fg.ACCOUNT, "obtained_at": "2026-10-27T09:00:00Z"}
    assert [(m, p) for m, p, _, _ in fake.calls()] == [("GET", fg.LISTS)]


# --- the scope: the five, nothing else ------------------------------------------------------------------------------------------------------


def test_a_token_of_the_four_of_before_google_tasks_is_refused_with_the_authorize_command_and_nothing_is_read(fake, tmp_path):
    fake.refresh_scope = " ".join(fg.PREVIOUS_SET)
    for args in (("--check",), ("lists",), ("open", "--list", "default")):
        proc = run(fake, tmp_path, *args, record=fake.record_json(scope=" ".join(fg.PREVIOUS_SET)))
        assert proc.returncode == 3 and "google_auth.py authorize" in proc.stderr and "Google Tasks" in proc.stderr, (args, proc.stderr)
    assert [r["path"] for r in fake.requests if r["path"] != "/token"] == [], "no call reached the Tasks API"


@pytest.mark.parametrize("granted", [" ".join(fg.PLATFORM_SET[1:]), " ".join(fg.PLATFORM_SET) + " https://mail.google.com/",
                                     " ".join(fg.PLATFORM_SET[:2] + (fg.TASKS,)), fg.TASKS])
def test_a_token_that_lacks_a_scope_or_carries_another_is_refused(fake, tmp_path, granted):
    fake.refresh_scope = granted
    proc = run(fake, tmp_path, "lists")
    assert proc.returncode == 3 and "authorize" in proc.stderr
    assert [r for r in fake.requests if r["path"] != "/token"] == []


def test_the_overrides_must_be_loopback_and_set_together(fake, tmp_path):
    env = env_of(fake, tmp_path)
    env["INTEGRATION_TASKS_GOOGLE_API_BASE"] = "https://tasks.example.com"
    assert run(fake, tmp_path, "lists", env=env).returncode == 2
    env = env_of(fake, tmp_path)
    del env["INTEGRATION_TASKS_GOOGLE_TOKEN_URL"]
    assert run(fake, tmp_path, "lists", env=env).returncode == 2


# --- only GET, only two paths ---------------------------------------------------------------------------------------------------------------


def test_only_get_reaches_the_tasks_api_and_the_token_endpoint_is_the_one_post(fake, tmp_path):
    out(run(fake, tmp_path, "lists"))
    out(run(fake, tmp_path, "open", "--list", fg.DEFAULT_LIST))
    assert {r["method"] for r in fake.requests if r["path"] != "/token"} == {"GET"} and fake.unexpected() == []
    assert all(r["if_match"] is None for r in fake.requests)


def test_the_request_function_refuses_anything_outside_the_allow_list_before_a_connection():
    assert reader.ALLOWED == (("GET", r"/tasks/v1/users/@me/lists"), ("GET", r"/tasks/v1/lists/(?:@default|(?:[A-Za-z0-9_-]|%3D)+)/tasks"))
    for entry, path in ((("POST", reader.LIST_TASKS[1]), "/tasks/v1/lists/x/tasks"), (reader.LIST_TASKS, "/tasks/v1/lists/x/tasks/y"), (reader.LIST_TASKS, "/tasks/v1/lists/x/clear"),
                        (reader.LIST_LISTS, "/tasks/v1/users/@me/lists/x"), (("DELETE", reader.LIST_TASKS[1]), "/tasks/v1/lists/x/tasks")):
        with pytest.raises(reader.ProviderError) as refused:
            reader.request(entry, "http://127.0.0.1:1", "token", path, {})
        assert refused.value.code == 2 and "allow-list" in str(refused.value)


def test_an_id_is_percent_encoded_in_the_path_and_a_bad_one_is_a_usage_error_before_any_call(fake, tmp_path):
    fake.lists["MTIz=="], fake.tasks["MTIz=="] = "Padded", {}
    out(run(fake, tmp_path, "open", "--list", "MTIz=="))
    assert fake.calls()[-1][1] == "/tasks/v1/lists/MTIz%3D%3D/tasks"
    before = len(fake.requests)
    for bad in ("../x", "a/b", "a b", "-x", "", "x" * 201, "@default"):
        assert run(fake, tmp_path, "open", "--list", bad).returncode == 2, bad
    assert len(fake.requests) == before


def test_a_redirect_is_not_followed_and_a_rejected_token_names_the_authorize_command(fake, tmp_path):
    fake.redirect_next = True
    proc = run(fake, tmp_path, "lists")
    assert proc.returncode == 1 and "redirect" in proc.stderr
    assert [r["path"] for r in fake.requests if r["path"] != "/token"] == [fg.LISTS], "the redirect was not followed"


def test_the_flags_of_a_verb_are_checked(fake, tmp_path):
    for args in (("open",), ("lists", "--list", "default"), ("--check", "lists"), (), ("open", "--list", "default", "--max", "0"), ("open", "--list", "default", "--max", "101")):
        assert run(fake, tmp_path, *args).returncode == 2, args
    assert run(fake, tmp_path, "--help").returncode == 0


def test_an_unknown_list_is_exit_1_and_names_no_title(fake, tmp_path):
    proc = run(fake, tmp_path, "open", "--list", "bm90YWxpc3Q")
    assert proc.returncode == 1 and "task list" in proc.stderr


def test_vacuity_a_reader_that_kept_completed_tasks_would_fail_the_open_test(fake, tmp_path, monkeypatch):
    """The oracle: with the status test removed, the completed task of the fixture would be printed, so the open test above does see the difference."""
    monkeypatch.setattr(reader, "task_of", lambda item: {"id": item["id"], "title": item.get("title"), "updated": None, "etag": None})
    printed = [reader.task_of(t)["id"] for t in fake.tasks[fg.DEFAULT_LIST].values()]
    assert printed == ["t1", "t2", "t3"] and printed != ["t1", "t2"]
