"""AF-1 TASKS-FAIL (SPEC-ACEITE-FIX-CODE): a Google Tasks read or write that the service refuses is told with its cause, and logged as a closed word.

  1. the reader turns a provider whose last stderr line starts `error: api_disabled:` into `ReaderError("api_disabled")`; any other failure keeps its code;
  2. `ops_todo` keeps each account's failure code and says `TODO_API_OFF`, `TODO_NOT_CONNECTED` or the plain `TODO_UNAVAILABLE`, and prints one closed line per failed read;
  3. the writer's refusal reaches the phone as `FAIL_TASKS_API_OFF` (checked before the authorization rule); a code-3 text still says `FAIL_NOT_AUTHORIZED`;
  4. `from_step(..., "event_gone", ...)` says `FAIL_EVENT_GONE`;
  5. stderr holds the closed code and no title, no list name, no address.

Offline: stand-in provider errors for the unit tests, and the stand-in Google Tasks service of providers/tasks/tests/ for the end-to-end ones; no model, every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_aceite_fix_tasks_words.py
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

import standin_tree as st
from test_tasks_ops import MICROSOFT, approve, configure, fg, open_decisions, world  # noqa: F401  (the tasks world: the real operations over the stand-in services)

ops = st.load("ops")
ops_todo = st.load("ops_todo")
effect_tasks = st.load("effect_tasks")
effects = st.load("effects")
failure = st.load("messaging_failure")
ops_step_effects = st.load("ops_step_effects")
phrases = st.load("phrases")
project_config = st.load("project_config")
tasks_reader = st.load("tasks_reader")

PT = {"language": "pt-BR"}
EN = {"language": "en"}
API_OFF = "api_disabled: Google Tasks API is not enabled for this OAuth client's project (GET /tasks/v1/lists/@default/tasks): Tasks API has not been used"
DISABLED = {"details": [{"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": "SERVICE_DISABLED"}]}


class FakeProviderCallError(Exception):
    """What providers/resolve.py raises when a provider ends with a failure: the fields the callers read."""

    def __init__(self, kind="failed", reason="the provider exited with code 1", exit_code=1, stderr_last=""):
        super().__init__(reason)
        self.kind, self.reason, self.exit_code, self.stderr_last = kind, reason, exit_code, stderr_last


def resolver_failing(error):
    def call(*args, **kwargs):
        raise error
    return SimpleNamespace(ProviderCallError=FakeProviderCallError, call=call, provider_environment=lambda *a, **k: {})


def fail_with(monkeypatch, error):
    monkeypatch.setattr(project_config, "resolver", lambda root: resolver_failing(error))


# --- the reader ---------------------------------------------------------------------------------------------------------------------------


def test_a_provider_that_says_api_disabled_is_a_reader_error_with_that_code(monkeypatch):
    fail_with(monkeypatch, FakeProviderCallError(stderr_last=f"error: {API_OFF}"))
    with pytest.raises(tasks_reader.ReaderError) as got:
        tasks_reader.provider_call("/nowhere", "google", "lists", [])
    assert got.value.code == "api_disabled" and "comprar" not in got.value.reason


def test_api_disabled_is_read_before_the_exit_code_rule_and_other_failures_keep_their_codes(monkeypatch):
    fail_with(monkeypatch, FakeProviderCallError(exit_code=3, stderr_last=f"error: {API_OFF}"))
    with pytest.raises(tasks_reader.ReaderError) as first:
        tasks_reader.provider_call("/nowhere", "google", "lists", [])
    assert first.value.code == "api_disabled"
    for error, code in ((FakeProviderCallError(exit_code=3, stderr_last="error: scope_missing: the token lacks the Google Tasks scope"), "not_configured"),
                        (FakeProviderCallError(kind="not-configured", exit_code=None), "not_configured"),
                        (FakeProviderCallError(stderr_last="error: Google refused the request (GET lists)"), "provider_failed"),
                        (FakeProviderCallError(stderr_last=""), "provider_failed")):
        fail_with(monkeypatch, error)
        with pytest.raises(tasks_reader.ReaderError) as got:
            tasks_reader.provider_call("/nowhere", "google", "lists", [])
        assert got.value.code == code


# --- the list and the completion by words -----------------------------------------------------------------------------------------------


def failing_read(monkeypatch, code):
    monkeypatch.setattr(ops_todo, "_lists_of", lambda cfg, account: {"minhas-tarefas": "default"})
    monkeypatch.setattr(tasks_reader, "default_list", lambda root, account: "default")

    def refuse(*args, **kwargs):
        raise tasks_reader.ReaderError(code, "open: refused")
    monkeypatch.setattr(tasks_reader, "open_tasks", refuse)


@pytest.mark.parametrize("code, key", [("api_disabled", "TODO_API_OFF"), ("not_configured", "TODO_NOT_CONNECTED"), ("provider_failed", "TODO_UNAVAILABLE"), ("refused", "TODO_UNAVAILABLE")])
def test_a_failed_read_says_its_cause_in_the_list_and_in_the_completion(monkeypatch, code, key):
    failing_read(monkeypatch, code)
    read = ops_todo._read_account(PT, "google")
    assert read["failed"] is True and read["code"] == code and read["lists"] == []
    service = ops_todo._label(PT, "google")
    expected = phrases.text(key, PT, service=service)
    got = {"status": "unavailable", "count": 0, "services": [{"account": "google", "failed": True, "code": code, "lists": []}]}
    assert ops_todo._render_list(PT, got) == expected
    mixed = {"status": "ok", "count": 0, "services": [{"account": "google", "failed": True, "code": code, "lists": [{"list": "x", "truncated": False, "tasks": []}]}]}
    assert expected in ops_todo._render_list(PT, mixed).splitlines()
    ctx = {"cfg": PT}
    monkeypatch.setattr(ops_todo, "_accounts_with_lists", lambda cfg: ["google"])
    assert ops_todo._reply_done("/nowhere", ctx, {"target": "comprar café"}, "google", None, None, {}) == expected


def test_the_three_sentences_differ_and_the_new_two_hold_no_command_and_no_link():
    seen = set()
    for language in (PT, EN):
        for key in ("TODO_API_OFF", "TODO_NOT_CONNECTED", "TODO_UNAVAILABLE", "FAIL_TASKS_API_OFF", "FAIL_EVENT_GONE"):
            said = phrases.text(key, language, service="Google Tasks")
            assert said and said not in seen and "://" not in said and "uv run" not in said and "google_auth" not in said
            seen.add(said)
    assert "Google Tasks" in phrases.text("TODO_NOT_CONNECTED", PT, service="Google Tasks")


def test_a_failed_read_prints_one_closed_line_and_no_title_no_list_name(monkeypatch, capsys):
    failing_read(monkeypatch, "api_disabled")
    ops_todo._read_account(PT, "google")
    err = capsys.readouterr().err
    assert err.splitlines() == ["tasks: read of google failed (api_disabled)"]
    assert "minhas-tarefas" not in err and "comprar" not in err


# --- the write ----------------------------------------------------------------------------------------------------------------------------


def test_a_writer_that_says_api_disabled_is_an_effect_error_that_keeps_the_word(monkeypatch):
    monkeypatch.setattr(effect_tasks, "serves", lambda root, implementation: None)
    fail_with(monkeypatch, FakeProviderCallError(stderr_last=f"error: {API_OFF}"))
    with pytest.raises(effects.EffectError) as got:
        effect_tasks.provider_call("/nowhere", "google", "task-insert", ["--list", "default"])
    assert got.value.kind == "provider" and got.value.reason.startswith("task-insert: api_disabled:") and "error:" not in got.value.reason


def approval_text(reason):
    """The text ops_step_effects raises for a write that was refused (its final branch)."""
    return (f"nothing was written: {reason}; the effect stays open, and approving it again with the same hash tries again")


class Refusal(Exception):
    def __init__(self, text, code=1):
        super().__init__(text)
        self.code = code


def test_the_phone_is_told_the_tasks_api_is_off_before_the_authorization_rule():
    text = approval_text("task-insert: " + API_OFF)
    for code in (1, 3):      # the writer's exit code for it is 1; the word wins over a code 3 as well
        for cfg in (PT, EN):
            assert failure.from_error(Refusal(text, code), cfg, word="tasks", account="google") == phrases.text("FAIL_TASKS_API_OFF", cfg)


def test_a_text_of_the_authorization_kind_still_says_not_authorized(monkeypatch):
    service = phrases.text("FAIL_SERVICE_TASKS_GOOGLE", PT)
    for text, code in ((approval_text("task-insert: scope_missing: the token lacks the Google Tasks scope; run: uv run <workbench>/providers/accounts/google_auth.py authorize"), 3),
                       (approval_text("task-insert: Google rejected the access token"), 3), ("the account is not configured", 1)):
        assert failure.from_error(Refusal(text, code), PT, word="tasks", account="google") == phrases.phone("FAIL_NOT_AUTHORIZED", PT, service=service)
    assert failure.from_error(Refusal("something odd", 1), PT, word="tasks", account="google") == phrases.phone("FAIL_NOT_DONE", PT)


def test_an_event_that_is_gone_has_its_own_sentence_on_the_phone():
    for cfg in (PT, EN):
        assert failure.from_step("calendar-event", "google", "event_gone", "", None, cfg, said="that event is not on this calendar any more") == phrases.text("FAIL_EVENT_GONE", cfg)
    assert failure.from_step("calendar-event", "google", "gone", "", None, PT) == phrases.text("FAIL_GONE", PT), "the other closed codes are as they were"


# --- stderr: one closed line per refused approval -------------------------------------------------------------------------------------------


def test_a_refused_approval_prints_the_word_the_kind_and_the_closed_prefix_only(capsys):
    ops_step_effects.refused_line(32, "tasks", effects.EffectError("provider", "task-insert: " + API_OFF))
    ops_step_effects.refused_line(33, "tasks", effects.EffectError("stale", "task-complete: the task moved (changed: not as it was read)"))
    ops_step_effects.refused_line(34, "write", effects.EffectError("provider", "Google refused the request (a title of mine)"))
    lines = capsys.readouterr().err.splitlines()
    assert lines == ["effect: decision 32 not written (tasks, provider, api_disabled)", "effect: decision 33 not written (tasks, stale)",
                     "effect: decision 34 not written (write, provider)"]


# --- end to end, against the stand-in service --------------------------------------------------------------------------------------------


def added(fake) -> int:
    return [t["title"] for t in fake.tasks[fg.DEFAULT_LIST].values()].count("comprar leite")


def test_a_tasks_api_that_is_off_is_said_in_the_list_and_in_the_stderr_of_the_read(world, capsys):  # noqa: F811
    configure(world, accounts={"google": {"address": fg.ACCOUNT, "task_lists": {"tarefas": "default"}}, "microsoft": MICROSOFT})
    world["google"].fail_get_next, world["google"].error_extra = 403, DISABLED
    got = ops.todo_list(world["path"], "google")
    assert got["status"] == "unavailable" and got["services"][0]["code"] == "api_disabled"
    assert ops_todo._render_list(PT, got) == phrases.text("TODO_API_OFF", PT)
    err = capsys.readouterr().err
    assert "tasks: read of google failed (api_disabled)" in err.splitlines() and "comprar" not in err and "tarefas" not in err


def test_a_403_with_another_reason_on_the_read_is_the_plain_sentence(world):  # noqa: F811
    configure(world, accounts={"google": {"address": fg.ACCOUNT, "task_lists": {"tarefas": "default"}}, "microsoft": MICROSOFT})
    world["google"].fail_get_next, world["google"].error_extra = 403, {"details": [{"reason": "RATE_LIMIT_EXCEEDED"}]}
    got = ops.todo_list(world["path"], "google")
    assert got["services"][0]["code"] == "provider_failed" and ops_todo._render_list(PT, got) == phrases.text("TODO_UNAVAILABLE", PT, service=ops_todo._label(PT, "google"))


def test_a_write_refused_because_the_api_is_off_says_so_logs_it_and_the_same_card_tries_again(world, capsys):  # noqa: F811
    google = world["google"]
    started = ops.todo_add(world["path"], "google", "comprar leite")
    google.refuse_next, google.error_extra = (403, "Tasks API has not been used"), DISABLED
    with pytest.raises(ops.OpsError) as refused:
        approve(world, started)
    assert "api_disabled:" in str(refused.value) and "the effect stays open" in str(refused.value) and added(google) == 0
    assert failure.from_error(refused.value, PT, word="tasks", account="google") == phrases.text("FAIL_TASKS_API_OFF", PT)
    err = capsys.readouterr().err
    assert f"effect: decision {started['pending']} not written (tasks, provider, api_disabled)" in err.splitlines()
    assert "comprar" not in err and "Tasks API has not been used" not in err
    assert [d["id"] for d in open_decisions(world)] == [started["pending"]], "the decision stays open"
    assert approve(world, started)["result"]["done"] is True and added(google) == 1, "approving again with the same hash tries again"
