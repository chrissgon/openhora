"""Tests of the Google Tasks writer (providers/writer/google-tasks.py; package CB-4; limits L55 to L59 as they apply to a writer). Against the stand-in service
(providers/tasks/tests/fake_gtasks.py) on 127.0.0.1: no Google host is reached and no real credential exists. Every write path records each request (method, path, query, body) and the
tests assert the exact list: one POST to add a task with a title and nothing else, one PATCH of {"status": "completed"} after a fresh read that matches the approved etag, no If-Match (no
page read documents one), no DELETE, no move, no clear. A dry run reads no credential and opens no connection. A moved etag is refused (exit 1, `changed:`) with nothing changed; a lost
answer is exit 4 and the same key finds what landed (`replayed`); an insert whose lookup finds two tasks of that title is exit 1 `ambiguous:` and sends nothing; a key that is done is not
sent again. The account record is required with the platform's five scopes (the four of before Google Tasks are refused, exit 3), and the token must belong to the `--account` named.

Run: uv run --with pytest==9.1.1 pytest providers/writer/tests/test_writer_google_tasks.py
"""
from __future__ import annotations

import datetime
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / "providers" / "tasks" / "tests"))
import fake_gtasks as fg  # noqa: E402

WRITER = REPO / "providers" / "writer" / "google-tasks.py"
_spec = importlib.util.spec_from_file_location("writer_google_tasks_under_test", WRITER)
writer = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(writer)
KEY = "task-0123456789abcdef0123456789abcdef"
LIST = fg.DEFAULT_LIST
TASKS = f"/tasks/v1/lists/{LIST}/tasks"
ACCOUNT = fg.ACCOUNT


@pytest.fixture
def fake():
    f = fg.FakeGoogleTasks()
    f.clock = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)      # the ledger stamps the real time: the stand-in's clock follows it
    f.add_task(LIST, "t1", "buy coffee")
    yield f
    f.close()


@pytest.fixture
def state(tmp_path):
    folder = tmp_path / "state"
    folder.mkdir()
    os.chmod(folder, 0o700)
    return folder


def env_of(fake, tmp_path, state, record=None, **extra):
    kept = {k: v for k, v in os.environ.items() if not k.startswith(("GMAIL_", "GOOGLE_", "WRITER_", "INTEGRATION_", "OPENHORA_"))}
    kept.update({"HOME": str(tmp_path / "home"), "OPENHORA_STATE_DIR": str(state), "GOOGLE_ACCOUNT_TOKEN": record or fake.record_json(), **fake.env("WRITER_TASKS_GOOGLE")})
    kept.update(extra)
    return kept


def spec_file(tmp_path, spec, name="spec.json"):
    path = tmp_path / name
    path.write_text(json.dumps(spec), encoding="utf-8")
    os.chmod(path, 0o600)
    return str(path)


def run(fake, tmp_path, state, *args, record=None, env=None):
    proc = subprocess.run([sys.executable, str(WRITER), *args], env=env or env_of(fake, tmp_path, state, record), capture_output=True, text=True, timeout=60)
    for stream in (proc.stdout, proc.stderr):    # no run ever prints a credential, not even partially (limit L59)
        for secret in fg.SECRETS:
            assert secret not in stream and secret[:16] not in stream, args
    return proc


def out(proc):
    assert proc.returncode == 0, (proc.returncode, proc.stderr)
    return json.loads(proc.stdout)


def insert_args(tmp_path, key=KEY, title="buy oat milk", mode="--confirmed", account=ACCOUNT, lst=LIST):
    return ["task-insert", "--account", account, "--list", lst, "--spec-file", spec_file(tmp_path, {"title": title}), "--idempotency-key", key, mode]


def complete_args(task="t1", etag='"LTE1001"', key=KEY, mode="--confirmed", account=ACCOUNT, lst=LIST):
    return ["task-complete", "--account", account, "--list", lst, "--task", task, "--base-etag", etag, "--idempotency-key", key, mode]


# --- an insert ----------------------------------------------------------------------------------------------------------------------------------


def test_an_insert_is_exactly_one_post_with_a_title_and_nothing_else(fake, tmp_path, state):
    done = out(run(fake, tmp_path, state, *insert_args(tmp_path)))
    assert done["done"] is True and done["replayed"] is False and done["task_id"] == "task0001" and done["etag"]
    [(method, path, query, body)] = fake.calls()
    assert (method, path, body) == ("POST", TASKS, {"title": "buy oat milk"}) and query == {"fields": "id,etag"}
    assert fake.unexpected() == [] and all(r["bearer"] and r["if_match"] is None for r in fake.requests if r["path"] != "/token")
    assert fake.tasks[LIST]["task0001"]["title"] == "buy oat milk" and "due" not in fake.tasks[LIST]["task0001"] and "notes" not in fake.tasks[LIST]["task0001"]
    assert "parent" not in query and "previous" not in query


def test_an_insert_into_the_default_list_sends_the_literal_at_default(fake, tmp_path, state):
    out(run(fake, tmp_path, state, *insert_args(tmp_path, lst="default")))
    assert fake.calls()[0][1] == "/tasks/v1/lists/@default/tasks" and "task0001" in fake.tasks[fg.DEFAULT_LIST]


def test_an_insert_into_another_list_is_percent_encoded(fake, tmp_path, state):
    fake.lists["bGlzdD09"], fake.tasks["bGlzdD09"] = "Padded", {}
    out(run(fake, tmp_path, state, *insert_args(tmp_path, lst="bGlzdD09")))
    assert fake.calls()[0][1] == "/tasks/v1/lists/bGlzdD09/tasks"
    fake.lists["bGlzdD0="], fake.tasks["bGlzdD0="] = "Padded", {}
    out(run(fake, tmp_path, state, *insert_args(tmp_path, key="task-other", lst="bGlzdD0=")))
    assert fake.calls()[-1][1] == "/tasks/v1/lists/bGlzdD0%3D/tasks"


def test_a_key_that_is_done_is_not_sent_again(fake, tmp_path, state):
    first = out(run(fake, tmp_path, state, *insert_args(tmp_path)))
    again = out(run(fake, tmp_path, state, *insert_args(tmp_path)))
    assert again == {"done": True, "replayed": True, "task_id": first["task_id"], "etag": first["etag"]}
    assert len(fake.writes()) == 1 and len(fake.tasks[LIST]) == 2


def test_a_key_used_for_another_request_is_a_usage_error_and_sends_nothing(fake, tmp_path, state):
    out(run(fake, tmp_path, state, *insert_args(tmp_path)))
    proc = run(fake, tmp_path, state, *insert_args(tmp_path, title="another title"))
    assert proc.returncode == 2 and "another request" in proc.stderr and len(fake.writes()) == 1


# --- the dry run --------------------------------------------------------------------------------------------------------------------------------


def test_a_dry_run_reads_no_credential_opens_no_connection_and_prints_the_exact_request_and_its_hash(fake, tmp_path, state):
    env = {k: v for k, v in env_of(fake, tmp_path, state).items() if not k.startswith(("GOOGLE_", "WRITER_TASKS"))}      # no token, no override: a connection would fail
    shown = out(run(fake, tmp_path, state, *insert_args(tmp_path, mode="--dry-run"), env=env))
    assert shown["dry_run"] is True and shown["ledger"] == "absent" and len(shown["would_sha256"]) == 64
    assert shown["would"] == {"method": "POST", "path": TASKS, "query": {"fields": "id,etag"}, "headers": {}, "body": {"title": "buy oat milk"}, "requires": None}
    assert fake.requests == []
    again = out(run(fake, tmp_path, state, *insert_args(tmp_path, mode="--dry-run"), env=env))
    assert again["would_sha256"] == shown["would_sha256"]


def test_the_hash_binds_the_title_the_list_and_the_base_etag(fake, tmp_path, state):
    def digest(*args):
        return out(run(fake, tmp_path, state, *args))["would_sha256"]
    base = digest(*insert_args(tmp_path, mode="--dry-run"))
    assert digest(*insert_args(tmp_path, title="buy oat milk!", mode="--dry-run")) != base
    assert digest(*insert_args(tmp_path, lst=fg.OTHER_LIST, mode="--dry-run")) != base
    one = digest(*complete_args(mode="--dry-run"))
    assert digest(*complete_args(etag='"LTE1002"', mode="--dry-run")) != one and digest(*complete_args(task="t2", mode="--dry-run")) != one
    shown = out(run(fake, tmp_path, state, *complete_args(mode="--dry-run")))
    assert shown["would"] == {"method": "PATCH", "path": f"{TASKS}/t1", "query": {"fields": "id,etag"}, "headers": {}, "body": {"status": "completed"}, "requires": {"etag": '"LTE1001"'}}


def test_vacuity_a_hash_that_ignored_the_title_could_not_tell_two_tasks_apart():
    """The oracle: the real hash tells two titles apart, and the same hash with the body left out (the planted fault) does not, so the `!=` above bites."""
    def digest(would):
        return writer._tasks.sha(writer._tasks.canonical(would))
    a, b = ({"method": "POST", "body": {"title": title}, "requires": None} for title in ("buy oat milk", "buy rice"))
    assert digest(a) != digest(b)
    planted = lambda would: digest({k: v for k, v in would.items() if k != "body"})      # noqa: E731
    assert planted(a) == planted(b)


# --- a completion -------------------------------------------------------------------------------------------------------------------------------


def test_a_completion_reads_the_task_again_compares_the_etag_and_sends_one_patch_of_the_status(fake, tmp_path, state):
    done = out(run(fake, tmp_path, state, *complete_args()))
    assert done["done"] is True and done["task_id"] == "t1" and done["etag"] and done["replayed"] is False
    methods = [(m, p) for m, p, _, _ in fake.calls()]
    assert methods == [("GET", f"{TASKS}/t1"), ("PATCH", f"{TASKS}/t1")], "a fresh read, then the one PATCH"
    assert fake.writes() == [("PATCH", f"{TASKS}/t1", {"fields": "id,etag"}, {"status": "completed"})]
    assert fake.tasks[LIST]["t1"]["status"] == "completed" and all(r["if_match"] is None for r in fake.requests) and fake.unexpected() == []


def test_a_task_at_another_etag_is_refused_with_nothing_changed_and_the_key_is_free(fake, tmp_path, state):
    fake.tick(5)
    fake.tasks[LIST]["t1"]["etag"] = '"LTE9999"'      # changed since the person approved
    proc = run(fake, tmp_path, state, *complete_args())
    assert proc.returncode == 1 and proc.stderr.startswith("error: changed:") and fake.writes() == []
    assert fake.tasks[LIST]["t1"]["status"] == "needsAction"
    fake.tasks[LIST]["t1"]["etag"] = '"LTE1001"'
    assert out(run(fake, tmp_path, state, *complete_args()))["done"] is True, "the same key may be tried again: nothing was sent"


def test_a_task_that_is_gone_or_already_completed_is_changed(fake, tmp_path, state):
    proc = run(fake, tmp_path, state, *complete_args(task="nope"))
    assert proc.returncode == 1 and "changed:" in proc.stderr and "gone" in proc.stderr and fake.writes() == []
    fake.tasks[LIST]["t1"]["status"] = "completed"
    proc = run(fake, tmp_path, state, *complete_args(key="task-second"))
    assert proc.returncode == 1 and "already completed" in proc.stderr and fake.writes() == []
    fake.tasks[LIST]["t1"].update(status="needsAction", deleted=True)
    proc = run(fake, tmp_path, state, *complete_args(key="task-third"))
    assert proc.returncode == 1 and "gone" in proc.stderr and fake.writes() == []


# --- task-get -----------------------------------------------------------------------------------------------------------------------------------


def test_task_get_prints_the_task_in_closed_words_and_a_gone_task_is_found_false(fake, tmp_path, state):
    shown = out(run(fake, tmp_path, state, "task-get", "--account", ACCOUNT, "--list", LIST, "--task", "t1"))
    assert shown == {"found": True, "task": {"id": "t1", "title": "buy coffee", "status": "open", "etag": '"LTE1001"', "updated": fake.tasks[LIST]["t1"]["updated"]}}
    fake.tasks[LIST]["t1"]["status"] = "completed"
    assert out(run(fake, tmp_path, state, "task-get", "--account", ACCOUNT, "--list", LIST, "--task", "t1"))["task"]["status"] == "completed"
    assert out(run(fake, tmp_path, state, "task-get", "--account", ACCOUNT, "--list", LIST, "--task", "zz")) == {"found": False, "reason": "gone"}
    fake.tasks[LIST]["t1"]["deleted"] = True
    assert out(run(fake, tmp_path, state, "task-get", "--account", ACCOUNT, "--list", LIST, "--task", "t1")) == {"found": False, "reason": "gone"}
    assert fake.writes() == []


def test_task_get_prints_a_title_on_one_line_and_never_on_stderr(fake, tmp_path, state):
    fake.add_task(LIST, "t9", "two\nlines\u202e\u200b and \x1b[2J" + "x" * 300)
    shown = out(run(fake, tmp_path, state, "task-get", "--account", ACCOUNT, "--list", LIST, "--task", "t9"))
    assert shown["task"]["title"].startswith("two lines and") and len(shown["task"]["title"]) == 200 and "\n" not in shown["task"]["title"] and "\u202e" not in shown["task"]["title"]
    fake.fail_get_next = 500
    proc = run(fake, tmp_path, state, "task-get", "--account", ACCOUNT, "--list", LIST, "--task", "t1")
    assert proc.returncode == 1 and "buy coffee" not in proc.stderr


# --- a lost answer (OPEN-CB-12) ------------------------------------------------------------------------------------------------------------------


def test_a_lost_insert_is_exit_4_and_the_same_key_finds_the_one_task_that_landed(fake, tmp_path, state):
    fake.lose_answer_once = True
    proc = run(fake, tmp_path, state, *insert_args(tmp_path))
    assert proc.returncode == 4 and len(fake.tasks[LIST]) == 2
    again = out(run(fake, tmp_path, state, *insert_args(tmp_path)))
    assert again["done"] is True and again["replayed"] is True and again["task_id"] == "task0001"
    assert len(fake.writes()) == 1 and len(fake.tasks[LIST]) == 2, "nothing was sent a second time"
    assert any(p == TASKS and q.get("updatedMin") for m, p, q, _ in fake.calls() if m == "GET"), "the lookup asked for tasks updated since the key went pending"


def test_an_older_task_with_the_same_title_does_not_count_as_the_one_that_landed(fake, tmp_path, state):
    fake.clock -= datetime.timedelta(days=2)
    fake.add_task(LIST, "old", "buy oat milk")      # the same title, long before the key went pending
    fake.clock += datetime.timedelta(days=2)
    fake.lose_answer_once = True
    assert run(fake, tmp_path, state, *insert_args(tmp_path)).returncode == 4
    again = out(run(fake, tmp_path, state, *insert_args(tmp_path)))
    assert again["replayed"] is True and again["task_id"] == "task0001", "only the new one"


def test_a_lost_insert_that_did_not_land_is_sent_again_exactly_once(fake, tmp_path, state):
    first = run(fake, tmp_path, state, *insert_args(tmp_path, title="never landed"), env=env_of(fake, tmp_path, state, WRITER_TASKS_GOOGLE_API_BASE="http://127.0.0.1:1"))
    assert first.returncode == 1 and "nothing was sent" in first.stderr      # the connection was refused before anything left: the key is free
    fake.lose_answer_once = False
    done = out(run(fake, tmp_path, state, *insert_args(tmp_path, title="never landed")))
    assert done["replayed"] is False and len(fake.writes()) == 1
    # a key left pending whose request did not land (the entry is written by hand, as an earlier crash would leave it) finds nothing and sends
    ledger = state / "writer-google-tasks" / "ledger.json"
    data = json.loads(ledger.read_text())
    digest = out(run(fake, tmp_path, state, *insert_args(tmp_path, key="task-pending", title="pending one", mode="--dry-run")))["would_sha256"]
    data["keys"]["task-pending"] = {"status": "pending", "operation": "insert", "payload_sha256": digest, "created_at": fake.clock.strftime("%Y-%m-%dT%H:%M:%SZ")}
    ledger.write_text(json.dumps(data))
    sent = out(run(fake, tmp_path, state, *insert_args(tmp_path, key="task-pending", title="pending one")))
    assert sent["replayed"] is False and len(fake.writes()) == 2


def test_two_tasks_with_the_title_since_the_pending_time_is_ambiguous_and_nothing_is_sent(fake, tmp_path, state):
    fake.lose_answer_once = True
    assert run(fake, tmp_path, state, *insert_args(tmp_path)).returncode == 4
    fake.tick(2)
    fake.add_task(LIST, "dup", "buy oat milk")      # another task with exactly that title, made by someone else since
    before = len(fake.writes())
    proc = run(fake, tmp_path, state, *insert_args(tmp_path))
    assert proc.returncode == 1 and proc.stderr.startswith("error: ambiguous:") and len(fake.writes()) == before and "buy oat milk" not in proc.stderr
    again = run(fake, tmp_path, state, *insert_args(tmp_path))
    assert again.returncode == 1 and "ambiguous:" in again.stderr, "the key stays pending: the person decides"


def test_a_lost_completion_is_settled_by_reading_the_task(fake, tmp_path, state):
    fake.lose_answer_once = True
    assert run(fake, tmp_path, state, *complete_args()).returncode == 4 and fake.tasks[LIST]["t1"]["status"] == "completed"
    again = out(run(fake, tmp_path, state, *complete_args()))
    assert again["done"] is True and again["replayed"] is True and len(fake.writes()) == 1


def test_a_redirect_on_a_write_is_not_followed_and_the_key_stays_pending(fake, tmp_path, state):
    fake.redirect_next = True
    proc = run(fake, tmp_path, state, *insert_args(tmp_path))
    assert proc.returncode == 4 and "redirect" in proc.stderr
    assert [r["path"] for r in fake.requests if r["path"] != "/token"] == [TASKS], "the redirect was not followed"
    peek = out(run(fake, tmp_path, state, *insert_args(tmp_path, mode="--dry-run")))
    assert peek["ledger"] == "pending"


def test_a_refused_write_changes_nothing_and_frees_the_key(fake, tmp_path, state):
    fake.refuse_next = (403, "forbidden")
    proc = run(fake, tmp_path, state, *insert_args(tmp_path))
    assert proc.returncode == 1 and "Google refused" in proc.stderr and len(fake.tasks[LIST]) == 1
    assert out(run(fake, tmp_path, state, *insert_args(tmp_path)))["done"] is True
    fake.refuse_next = (429, "rate")
    proc = run(fake, tmp_path, state, *insert_args(tmp_path, key="task-busy"))
    assert proc.returncode == 1 and "slow down" in proc.stderr and "Retry-After: 30" in proc.stderr


def test_a_server_error_on_a_write_is_exit_4_and_on_a_read_exit_1(fake, tmp_path, state):
    fake.refuse_next = (503, "later")
    assert run(fake, tmp_path, state, *insert_args(tmp_path)).returncode == 4
    fake.fail_get_next = 500
    assert run(fake, tmp_path, state, "task-get", "--account", ACCOUNT, "--list", LIST, "--task", "t1").returncode == 1


# --- the account and the scopes --------------------------------------------------------------------------------------------------------------------


def test_a_token_of_another_account_reads_and_writes_nothing(fake, tmp_path, state):
    for args in (insert_args(tmp_path, account="someone.else@example.com"), complete_args(account="someone.else@example.com"),
                 ["task-get", "--account", "someone.else@example.com", "--list", LIST, "--task", "t1"]):
        proc = run(fake, tmp_path, state, *args)
        assert proc.returncode == 1 and "another account" in proc.stderr, args
    assert [r["path"] for r in fake.requests] == [], "no call, the token endpoint included"
    assert out(run(fake, tmp_path, state, *insert_args(tmp_path, account=ACCOUNT.upper())))["done"] is True, "compared without case"


def test_a_token_of_the_four_of_before_google_tasks_is_refused_by_every_verb_and_nothing_is_sent(fake, tmp_path, state):
    previous = fake.record_json(scope=" ".join(fg.PREVIOUS_SET))
    fake.refresh_scope = " ".join(fg.PREVIOUS_SET)
    for args in (["--check"], insert_args(tmp_path), complete_args(), ["task-get", "--account", ACCOUNT, "--list", LIST, "--task", "t1"]):
        proc = run(fake, tmp_path, state, *args, record=previous)
        assert proc.returncode == 3 and "google_auth.py authorize" in proc.stderr and "Google Tasks" in proc.stderr, (args, proc.stderr)
    assert [r["path"] for r in fake.requests if r["path"] != "/token"] == []
    ledger = out(run(fake, tmp_path, state, *insert_args(tmp_path, mode="--dry-run")))["ledger"]
    assert ledger == "absent", "a refused session frees the key it made"


@pytest.mark.parametrize("granted", [" ".join(fg.PLATFORM_SET[1:]), " ".join(fg.PLATFORM_SET) + " https://mail.google.com/", fg.TASKS])
def test_a_token_that_lacks_a_scope_or_carries_another_is_refused(fake, tmp_path, state, granted):
    fake.refresh_scope = granted
    proc = run(fake, tmp_path, state, *insert_args(tmp_path))
    assert proc.returncode == 3 and "authorize" in proc.stderr and fake.writes() == []


def test_check_reads_one_list_entry_and_prints_the_five_scopes(fake, tmp_path, state):
    shown = out(run(fake, tmp_path, state, "--check"))
    assert shown == {"ok": True, "scope": sorted(fg.PLATFORM_SET), "account": ACCOUNT, "obtained_at": "2026-10-27T09:00:00Z"}
    assert [(m, p) for m, p, _, _ in fake.calls()] == [("GET", fg.LISTS)]


# --- the spec and the arguments --------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("spec", [{"title": "x", "due": "2026-11-01T00:00:00Z"}, {"title": "x", "notes": "n"}, {"title": "x", "parent": "p"}, {}, {"name": "x"}, {"title": ""},
                                  {"title": "  "}, {"title": "two\nlines"}, {"title": "a" * 201}, {"title": "hid\u200bden"}, {"title": "bell\x07"}, {"title": " padded"},
                                  {"title": 5}, {"title": None}, ["title"], "title"])
def test_a_spec_that_is_not_exactly_one_short_one_line_title_is_a_usage_error_before_any_call(fake, tmp_path, state, spec):
    proc = run(fake, tmp_path, state, "task-insert", "--account", ACCOUNT, "--list", LIST, "--spec-file", spec_file(tmp_path, spec), "--idempotency-key", KEY, "--confirmed")
    assert proc.returncode == 2 and fake.requests == [], spec
    dry = run(fake, tmp_path, state, "task-insert", "--account", ACCOUNT, "--list", LIST, "--spec-file", spec_file(tmp_path, spec), "--idempotency-key", KEY, "--dry-run")
    assert dry.returncode == 2


def test_a_title_of_200_characters_is_accepted(fake, tmp_path, state):
    assert out(run(fake, tmp_path, state, *insert_args(tmp_path, title="é" * 200)))["done"] is True


def test_a_spec_file_that_is_a_link_or_missing_is_refused(fake, tmp_path, state):
    real = spec_file(tmp_path, {"title": "x"})
    link = tmp_path / "link.json"
    link.symlink_to(real)
    for path in (str(link), str(tmp_path / "missing.json")):
        proc = run(fake, tmp_path, state, "task-insert", "--account", ACCOUNT, "--list", LIST, "--spec-file", path, "--idempotency-key", KEY, "--confirmed")
        assert proc.returncode == 2 and fake.requests == []


def test_a_bad_id_key_etag_or_account_is_a_usage_error_before_any_call(fake, tmp_path, state):
    bad = [insert_args(tmp_path, lst="a/b"), insert_args(tmp_path, lst="-x"), insert_args(tmp_path, key="has space"), insert_args(tmp_path, key="-k"), insert_args(tmp_path, account="no-at-sign"),
           insert_args(tmp_path, account="a@b@c"), complete_args(task="../x"), complete_args(task="a/b"), complete_args(etag="bad etag"), complete_args(etag="-e"), complete_args(lst="a b")]
    for args in bad:
        assert run(fake, tmp_path, state, *args).returncode == 2, args
    assert fake.requests == []


def test_the_flags_of_a_verb_are_checked(fake, tmp_path, state):
    for args in (["task-insert", "--account", ACCOUNT], ["task-insert", "--account", ACCOUNT, "--list", LIST, "--idempotency-key", KEY, "--confirmed"], insert_args(tmp_path, mode="--dry-run") + ["--confirmed"],
                 ["task-get", "--account", ACCOUNT, "--list", LIST, "--task", "t1", "--dry-run"], ["task-complete", "--account", ACCOUNT, "--list", LIST, "--task", "t1", "--idempotency-key", KEY, "--confirmed"],
                 ["--check", "--list", LIST], ["--check", "task-get"], [], ["task-get", "--account", ACCOUNT, "--list", LIST, "--task", "t1", "--spec-file", "x"]):
        assert run(fake, tmp_path, state, *args).returncode == 2, args
    assert run(fake, tmp_path, state, "--help").returncode == 0


def test_the_overrides_must_be_loopback_and_set_together(fake, tmp_path, state):
    env = env_of(fake, tmp_path, state)
    env["WRITER_TASKS_GOOGLE_API_BASE"] = "https://tasks.example.com"
    assert run(fake, tmp_path, state, "--check", env=env).returncode == 2
    env = env_of(fake, tmp_path, state)
    del env["WRITER_TASKS_GOOGLE_TOKEN_URL"]
    assert run(fake, tmp_path, state, "--check", env=env).returncode == 2


# --- the allow-list: GET, POST and PATCH on the list and task paths, and nothing else (L57) ----------------------------------------------------------


def test_the_allow_list_holds_no_removal_no_move_and_no_clearing():
    assert [m for m, _ in writer.ALLOWED] == ["GET", "GET", "GET", "POST", "PATCH"]
    assert writer.SERVES == "writer:tasks" and "DELETE" not in json.dumps(writer.ALLOWED) and "PUT" not in json.dumps(writer.ALLOWED)
    for entry, path in ((("DELETE", writer.GET_TASK[1]), "/tasks/v1/lists/x/tasks/y"), (("POST", writer.INSERT[1]), "/tasks/v1/lists/x/tasks/y/move"), (writer.INSERT, "/tasks/v1/lists/x/clear"),
                        (writer.PATCH, "/tasks/v1/lists/x/tasks/y/move"), (writer.GET_TASK, "/tasks/v1/lists/x/tasks/../y"), (writer.INSERT, "/tasks/v1/users/@me/lists"),
                        (("POST", r"/tasks/v1/users/@me/lists"), "/tasks/v1/users/@me/lists"), (writer.PATCH, "/tasks/v1/lists/x/tasks"), (writer.INSERT, "/tasks/v1/lists/x/tasks/y")):
        with pytest.raises(writer.ProviderError) as refused:
            writer.request(entry, "http://127.0.0.1:1", "token", path, {})
        assert refused.value.code == 2 and "allow-list" in str(refused.value), (entry, path)


def test_the_script_names_no_delete_call_in_any_spelling():
    import re
    code = re.sub(r'"""[\s\S]*?"""', "", WRITER.read_text(encoding="utf-8"))
    assert not re.search(r"(?i)\bdelete\b|permanent|\.clear\(|/clear|/move", code)


def test_every_request_a_run_makes_is_in_the_allow_list_and_no_title_is_on_stderr(fake, tmp_path, state):
    out(run(fake, tmp_path, state, *insert_args(tmp_path, title="private plan")))
    proc = run(fake, tmp_path, state, *complete_args(task="nope", key="task-x"))
    assert "private plan" not in proc.stderr and "buy coffee" not in proc.stderr and fake.unexpected() == []
