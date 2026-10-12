"""Tests of why a ready task does not start (WP-9.14, item A-10): the dispatcher records, for the last round of each
project, every ready task it held and the reason; `status` carries them as `held`, `agents` counts them per agent, and
a service that dispatches nothing says `dispatch off` for every ready task. The pure function `held_of` and the
operations on the stand-in tree. Offline; invented names.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_held_tasks.py
"""
from __future__ import annotations

import pytest

import standin_tree as st
from test_dispatcher import AGENTS, agent, configure, decide, planned, ready, store_rows, tree  # noqa: F401

autonomy = st.load("autonomy")
dispatcher = st.load("dispatcher")
lab = st.load("lab")
ops = st.load("ops")
ops_reads = st.load("ops_reads")
ops_core = st.load("ops_core")
operations = st.load("operations")

WORDS = ("stopped", "cap: runs per day", "cap: usd per day", "credential", "secret store", "image", "dispatch off",
         "job running", "no enabled agent owns the task", "waiting", "other")


@pytest.fixture(autouse=True)
def no_service():
    ops.SERVICE.clear()
    yield
    ops.SERVICE.clear()


# --- the pure function ---------------------------------------------------------------------------------------------


def test_the_reasons_are_the_words_of_the_list():
    assert dispatcher.NO_AGENT == "no enabled agent owns the task" and dispatcher.JOB_RUNNING == "job running"
    assert set(dispatcher.REASONS) == set(WORDS)


def test_every_ready_task_a_decision_held_gets_its_reason_and_its_agent():
    snapshot = {"running": None, "ready": [ready(4, "a"), ready(5, "b"), ready(6, None), ready(7, "c")], "reviews": [],
                "agents": {"a": agent(mode="stopped"), "b": agent(runs=5, cap=5), "c": agent()},
                "tier": {4: "strong", 5: "strong", 7: "strong"}, "billing": {4: "subscription", 5: "subscription", 7: "subscription"}}
    decided = decide(snapshot)
    assert decided["start"] == 7
    assert dispatcher.held_of(snapshot, decided) == [
        {"task_id": 4, "agent": "a", "reason": "stopped"}, {"task_id": 5, "agent": "b", "reason": "cap: runs per day"},
        {"task_id": 6, "agent": None, "reason": "no enabled agent owns the task"}]


def test_a_task_that_runs_holds_every_ready_task_of_the_project():
    snapshot = {"running": {"id": 3}, "ready": [ready(4, "a"), ready(5, "a")], "reviews": [], "agents": {"a": agent()},
                "tier": {4: "strong", 5: "strong"}, "billing": {4: "subscription", 5: "subscription"}}
    decided = decide(snapshot)
    assert decided["held"] == [{"task_id": 3, "why": dispatcher.ONE_AT_A_TIME}]  # the decision itself is unchanged
    assert dispatcher.held_of(snapshot, decided) == [{"task_id": 4, "agent": "a", "reason": "job running"},
                                                     {"task_id": 5, "agent": "a", "reason": "job running"}]


def test_a_task_the_round_could_not_start_is_held_with_what_stopped_it():
    snapshot = {"running": None, "ready": [ready(4, "a"), ready(5, "a")], "reviews": [], "agents": {"a": agent()},
                "tier": {4: "strong", 5: "strong"}, "billing": {4: "subscription", 5: "subscription"}}
    decided = decide(snapshot)
    assert decided["start"] == 4
    assert dispatcher.held_of(snapshot, decided, {4: "credential"}) == [{"task_id": 4, "agent": "a", "reason": "credential"}]
    assert dispatcher.held_of(snapshot, decided) == []  # started, nothing else examined


# --- the operations ------------------------------------------------------------------------------------------------


def held(tree):
    return ops.status(str(tree["project"]))["held"]


def test_a_stopped_agent_s_ready_task_is_held_and_status_and_agents_say_so(tree):
    path = str(tree["project"])
    request = planned(tree, "chain")
    configure(tree, {"business": dict(AGENTS["business"], mode="stopped")})
    out = ops.dispatch(path)
    [ready_task] = [t for t in store_rows(tree, request) if t["state"] == "ready"]
    [entry] = held(tree)
    assert out["ran"] == [] and set(entry) == {"task_id", "agent", "reason", "at", "next", "commands"}
    assert entry["commands"] == []  # a stopped agent is past by a configuration change, not by a command
    assert (entry["task_id"], entry["agent"], entry["reason"]) == (ready_task["id"], "business", "stopped")
    assert entry["at"].endswith("+00:00") or entry["at"].endswith("Z")
    assert [a["held"] for a in ops.agents(path)["agents"]] == [1]


def test_the_two_caps_are_named(tree):
    path = str(tree["project"])
    planned(tree, "chain")
    configure(tree, {"business": dict(AGENTS["business"], max_runs_per_day=0)})
    ops.dispatch(path)
    assert [h["reason"] for h in held(tree)] == ["cap: runs per day"]


def test_a_missing_credential_and_an_unreadable_secret_store_are_told_apart(tree, monkeypatch):
    path = str(tree["project"])
    planned(tree, "chain")
    monkeypatch.setattr(lab, "credential_missing", lambda tier: ["EXAMPLE_REFERENCE_KEY"])
    monkeypatch.setattr(dispatcher, "store_readable", lambda: "ok")
    out = ops.dispatch(path)
    assert out["ran"] == [] and [h["reason"] for h in held(tree)] == ["credential"]
    monkeypatch.setattr(dispatcher, "store_readable", lambda: "/usr/bin/python3 (Python 3.9.6) cannot read the secret store: ModuleNotFoundError")
    ops.dispatch(path)
    [entry] = held(tree)
    assert entry["reason"] == "secret store"
    assert entry["next"].startswith("uv run --with keyring==25.7.0 python3 ") and "/runtime/service.py --project " in entry["next"]
    assert [t["state"] for t in store_rows(tree) if t["parent_id"]] == ["ready", "planned"]  # no task failed


def test_a_missing_image_holds_the_task_and_fails_nothing(tree, monkeypatch):
    path = str(tree["project"])
    planned(tree, "chain")
    monkeypatch.setattr(lab, "image", lambda: {"name": "example-eval-image", "digest": None, "platform": None, "evidence_platform": None})
    out = ops.dispatch(path)
    assert out["ran"] == [] and "example-eval-image" in out["stopped"] and "no run starts" in out["stopped"]
    assert [h["reason"] for h in held(tree)] == ["image"]
    assert [t["state"] for t in store_rows(tree) if t["parent_id"]] == ["ready", "planned"]


def test_a_task_that_runs_holds_the_next_one_with_job_running(tree):
    path = str(tree["project"])
    first, second = planned(tree, "single"), planned(tree, "single")
    ctx = ops_core.context(path)
    [one, two] = [t for t in ctx["store"].tasks_list(ctx["conn"]) if t["parent_id"] is not None and t["state"] == "ready"]
    ctx["store"].task_claim(ctx["conn"], one["id"])
    ops.dispatch(path)
    [entry] = held(tree)
    assert (entry["task_id"], entry["reason"]) == (two["id"], "job running")


def test_a_task_no_enabled_agent_owns_is_held_with_that_sentence(tree):
    path = str(tree["project"])
    ops.request(path, "Invented request.", flow="single")
    ops.dispatch(path)
    assert [h["reason"] for h in held(tree)] == ["no enabled agent owns the task"]


def test_without_area_agents_the_ready_tasks_are_held_too(tree):
    path = str(tree["project"])
    ops.request(path, "Invented request.", flow="single")
    configure(tree, {})
    ops.dispatch(path)
    assert [h["reason"] for h in held(tree)] == ["no enabled agent owns the task"]


def test_a_task_that_started_is_no_longer_held_and_a_round_that_holds_nothing_clears_the_list(tree):
    path = str(tree["project"])
    planned(tree, "chain")
    configure(tree, {"business": dict(AGENTS["business"], mode="stopped")})
    ops.dispatch(path)
    assert len(held(tree)) == 1
    ops.run_next(path)  # by hand: the task leaves `ready`
    assert held(tree) == []  # a record only lists tasks still ready
    configure(tree, AGENTS)
    ops.dispatch(path)
    assert held(tree) == []


def test_the_record_stays_inside_the_store_s_cap_when_many_tasks_are_held(tree):
    path = str(tree["project"])
    for _ in range(30):
        ops.request(path, "Invented request.", flow="single")
    ops.dispatch(path)
    got = held(tree)
    assert 1 <= len(got) <= ops.HELD_KEPT


def test_a_service_that_dispatches_nothing_says_dispatch_off_for_every_ready_task(tree, monkeypatch):
    path = str(tree["project"])
    planned(tree, "chain")
    monkeypatch.setattr(dispatcher, "inspect", lambda module: {"secret_store": "ok", "credential": "ok", "tools": {}, "modules": {}, "lab": "ok"})
    monkeypatch.setenv(operations.UV_MARK, "0")
    ops.service_check(path, 0)
    [entry] = held(tree)
    assert entry["reason"] == "dispatch off" and entry["agent"] == "business"
    assert entry["next"] == f"uv run --with keyring==25.7.0 python3 {tree['tree']}/runtime/cli.py run-next --project {path}"
    assert [a["held"] for a in ops.agents(path)["agents"]] == [1]
    ops.service_check(path, 30)  # a service that dispatches: the record of the last round is what is read
    assert held(tree) == []


# --- through the service ------------------------------------------------------------------------------------------


def served(tree):
    import types
    import test_service as ts
    path = str(tree["project"])
    projects = [{"id": ts.service.project_id(path), "name": "p", "path": path}]
    world = types.SimpleNamespace(svc=ts.service.Service(ops, projects, ts.TOKEN, ts.PORT, None, log=lambda line: None), projects=projects)
    return ts, world


def test_the_page_reads_the_held_tasks_and_the_count_per_agent_through_the_service(tree, monkeypatch):
    path = str(tree["project"])
    planned(tree, "chain")
    configure(tree, {"business": dict(AGENTS["business"], mode="stopped")})
    ops.dispatch(path)
    ts, world = served(tree)
    status, _, body = ts.call(world, "GET", ts.api(world, "/status"))
    assert status == 200 and [(h["agent"], h["reason"]) for h in body["held"]] == [("business", "stopped")]
    agents = ts.call(world, "GET", ts.api(world, "/agents"))[2]["agents"]
    assert [a["held"] for a in agents] == [1]
    monkeypatch.setattr(dispatcher, "inspect", lambda module: {"secret_store": "ok", "credential": "ok", "tools": {}, "modules": {}, "lab": "ok"})
    ops.service_check(path, 0)  # a service started with --no-dispatch
    held = ts.call(world, "GET", ts.api(world, "/status"))[2]["held"]
    assert [h["reason"] for h in held] == ["dispatch off"] and "run-next --project" in held[0]["next"]
    connections = ts.call(world, "GET", ts.api(world, "/connections"))
    assert connections[0] == 200 and connections[2]["service"]["dispatch"] == "off"


# --- review of WP-9.14 -----------------------------------------------------------------------------------------------


def test_an_unchanged_set_of_held_tasks_writes_nothing_and_keeps_its_time(tree):
    path = str(tree["project"])
    planned(tree, "chain")
    configure(tree, {"business": dict(AGENTS["business"], mode="stopped")})
    ops.dispatch(path)
    ctx = ops_core.context(path)
    first = ctx["store"].cursor_get(ctx["conn"], ops.HELD_CURSOR)
    before = ctx["store"].change_counter(ctx["conn"])
    for _ in range(3):
        ops.dispatch(path)
    assert ctx["store"].cursor_get(ctx["conn"], ops.HELD_CURSOR) == first  # `at` is when the set began
    assert ctx["store"].change_counter(ctx["conn"]) == before  # nothing a page would reload for
    configure(tree, {"business": dict(AGENTS["business"], max_runs_per_day=0)})
    ops.dispatch(path)
    assert ctx["store"].cursor_get(ctx["conn"], ops.HELD_CURSOR) != first  # another reason: written


def test_the_vocabulary_of_the_held_reasons_is_closed():
    free_text = lambda name, entries, f, spent, billing: (False, f"unknown billing {billing!r}")  # noqa: E731
    snapshot = {"running": None, "ready": [ready(4, "a")], "reviews": [], "agents": {"a": agent()}, "tier": {4: "strong"}, "billing": {4: "weird"}}
    decided = dispatcher.decide(snapshot, autonomy.review_action, free_text)
    assert dispatcher.held_of(snapshot, decided) == [{"task_id": 4, "agent": "a", "reason": "other"}]
    assert "other" in dispatcher.REASONS
    got = dispatcher.held_of(snapshot, decided, {4: "image"})
    assert got[0]["reason"] == "image"
    assert all(r in dispatcher.REASONS for r in (dispatcher.NO_AGENT, dispatcher.JOB_RUNNING, dispatcher.DISPATCH_OFF))


def test_a_narrowing_accepted_in_the_middle_of_a_round_stops_the_next_start(tree, monkeypatch):
    path = str(tree["project"])
    planned(tree, "chain")
    configure(tree, {"business": dict(AGENTS["business"], mode="autonomous")})
    real = ops._claim_and_run
    done = []

    def run_then_narrow(ctx, tier=None, task_id=None):
        out = real(ctx, tier, task_id)
        done.append(task_id)
        if len(done) == 1:  # the person (or the page) stops the agent while the round goes on
            assert ops.set_mode(path, "business", "stopped")["accepted"] is True
        return out

    monkeypatch.setattr(ops, "_claim_and_run", run_then_narrow)
    out = ops.dispatch(path)
    assert len(out["ran"]) == 1 and len(done) == 1
    assert "configuration" in out["stopped"] and "changed" in out["stopped"]
    assert [t["state"] for t in store_rows(tree) if t["parent_id"]].count("done") + [t["state"] for t in store_rows(tree) if t["parent_id"]].count("waiting") >= 1


# --- the commands as fields (A-22) ----------------------------------------------------------------------------------


def test_a_held_credential_carries_each_command_as_a_field_with_the_username_quoted_and_null_without_one(tree, monkeypatch):
    path = str(tree["project"])
    planned(tree, "chain")
    monkeypatch.setattr(lab, "credential_missing", lambda tier: ["EXAMPLE_KEY_A", "EXAMPLE_KEY_B", "EXAMPLE_KEY_C"])
    monkeypatch.setattr(lab, "credential_usernames", lambda names: {"EXAMPLE_KEY_A": "example-a", "EXAMPLE_KEY_B": "name with space"})
    monkeypatch.setattr(dispatcher, "store_readable", lambda: "ok")
    ops.dispatch(path)
    [entry] = [h for h in ops.status(path)["held"] if h["reason"] == "credential"]
    store = "uv run --with keyring==25.7.0 keyring set openhora "
    assert entry["commands"] == [{"name": "EXAMPLE_KEY_A", "command": store + "example-a"},
                                 {"name": "EXAMPLE_KEY_B", "command": store + "'name with space'"},
                                 {"name": "EXAMPLE_KEY_C", "command": None}]       # no username registered: no command to build
    assert entry["commands"][0]["command"] == operations.keyring_line("example-a")
    # A-34: the commands that are fields are not written a second time; the sentence keeps the one a field cannot give
    assert store + "example-a" not in entry["next"] and "name with space" not in entry["next"] and "EXAMPLE_KEY_A" not in entry["next"]
    assert "EXAMPLE_KEY_C: " + store + "<username>" in entry["next"] and "contracts/secrets.md" in entry["next"]
    [wide] = [a for a in ops.agents(path)["agents"]]
    assert wide["held"] == 1                                                            # agents carry the count, not the commands


def test_a_held_secret_store_carries_the_service_command_and_every_other_reason_none(tree, monkeypatch):
    path = str(tree["project"])
    planned(tree, "chain")
    monkeypatch.setattr(lab, "credential_missing", lambda tier: ["EXAMPLE_KEY_A"])
    monkeypatch.setattr(dispatcher, "store_readable", lambda: "cannot read the secret store: ModuleNotFoundError")
    ops.dispatch(path)
    [entry] = ops.status(path)["held"]
    assert entry["reason"] == "secret store"
    assert entry["commands"] == [{"name": "service", "command": entry["next"]}]
    assert entry["commands"][0]["command"] == operations.service_line(str(tree["tree"]), [path], uv=True)
    configure(tree, {"business": dict(AGENTS["business"], mode="stopped")})
    monkeypatch.setattr(lab, "credential_missing", lambda tier: [])
    ops.dispatch(path)
    assert [(h["reason"], h["commands"]) for h in ops.status(path)["held"]] == [("stopped", [])]


def test_the_keyring_command_is_spelled_in_one_place_with_the_username_quoted():
    assert operations.keyring_line("example-a") == "uv run --with keyring==25.7.0 keyring set openhora example-a"
    assert operations.keyring_line("two words; rm -rf") == "uv run --with keyring==25.7.0 keyring set openhora 'two words; rm -rf'"
    assert operations.keyring_line("<username>") == "uv run --with keyring==25.7.0 keyring set openhora <username>"


def test_a_held_credential_whose_commands_are_all_fields_is_one_sentence_that_writes_no_command(tree, monkeypatch):
    """A-34: the page draws `commands` and `next` side by side, so the sentence must not write the command again."""
    path = str(tree["project"])
    planned(tree, "chain")
    monkeypatch.setattr(lab, "credential_missing", lambda tier: ["EXAMPLE_KEY_A", "EXAMPLE_KEY_B"])
    monkeypatch.setattr(lab, "credential_usernames", lambda names: {"EXAMPLE_KEY_A": "example-a", "EXAMPLE_KEY_B": "example-b"})
    monkeypatch.setattr(dispatcher, "store_readable", lambda: "ok")
    ops.dispatch(path)
    [entry] = [h for h in ops.status(path)["held"] if h["reason"] == "credential"]
    assert entry["next"] == "The credential is in neither the environment nor the secret store."
    assert [c["name"] for c in entry["commands"]] == ["EXAMPLE_KEY_A", "EXAMPLE_KEY_B"] and all(c["command"] for c in entry["commands"])
    assert "keyring" not in entry["next"] and "<username>" not in entry["next"]


def test_the_held_sentence_of_a_credential_with_no_command_to_build_keeps_the_table_and_the_other_reasons_are_unchanged(tree, monkeypatch):
    path = str(tree["project"])
    monkeypatch.setattr(lab, "credential_usernames", lambda names: {})
    text = ops_reads.held_next(path, "credential", ["EXAMPLE_KEY_C"])
    assert text.startswith("The credential is in neither the environment nor the secret store. Store it once")
    assert "EXAMPLE_KEY_C: " in text and "contracts/secrets.md" in text and "<username>" in text, "the unregistered one is told where to look"
    monkeypatch.setattr(lab, "credential_usernames", lambda names: {"EXAMPLE_KEY_A": "example-a"})
    assert ops_reads.held_next(path, "credential", ["EXAMPLE_KEY_A"]) == "The credential is in neither the environment nor the secret store."
    assert "EXAMPLE_KEY_A" not in ops_reads.held_next(path, "credential", ["EXAMPLE_KEY_A", "EXAMPLE_KEY_C"]), \
        "a variable that has a command is left to its field, the other is still told"
    assert "EXAMPLE_KEY_C" in ops_reads.held_next(path, "credential", ["EXAMPLE_KEY_A", "EXAMPLE_KEY_C"])
    assert ops_reads.held_next(path, "stopped") is None
    assert ops_reads.held_next(path, "secret store").startswith("uv run --with keyring==25.7.0 python3 ")
