"""Tests of the read operations of the local interface (stage 9, WP-9.3a): agents, conversation, skills, costs,
connections, artifacts and artifact of runtime/ops.py, and the route-lock check of say, on the stand-in tree of
standin_tree.py. Offline; invented names, invented prices, invented secrets.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_read_ops.py
"""
from __future__ import annotations

import datetime
import json
import os
import platform as platform_module
import shutil
import socket
import subprocess
import sys
import time

import pytest

import standin_tree as st

lab = st.load("lab")
ops = st.load("ops")
ops_core = st.load("ops_core")
ops_reads = st.load("ops_reads")
plan = st.load("plan")
cli = st.load("cli")
proof_rules = st.load("proof")
costs = st.load("costs")

PACKS = {"biz": ["demo-asks", "demo-writes"], "code": ["demo-code"], "default": ["demo-asks", "demo-code", "demo-writes"]}
AGENTS = {"business": {"pack": "biz", "mode": "supervised", "max_runs_per_day": 3, "max_usd_per_day": 2.5},
          "engineering": {"pack": "code", "mode": "autonomous-with-policy", "max_runs_per_day": 1, "max_usd_per_day": 0.5},
          "design": {"pack": "code", "enabled": False, "max_runs_per_day": 2}}
PRICES = {"models": {"m": {"input_usd_per_mtok": 3.0, "output_usd_per_mtok": 15.0, "cache_read_usd_per_mtok": 0.3,
                           "cache_write_usd_per_mtok": 3.75, "source": "https://prices.example/models", "accessed": "2025-12-31"}}}
PLANTED_ONE = "invented-floor-key-0001-never-shown"
PLANTED_TWO = "invented-model-key-0002-never-shown"


@pytest.fixture
def tree(tmp_path, monkeypatch):
    built = st.build(tmp_path, monkeypatch, lab)
    monkeypatch.setattr(ops_core, "ROOT", str(built["tree"]))
    monkeypatch.setattr(plan, "resolve_pack", lambda pack, root: list(PACKS[pack]))
    # The stand-in tree lists two models, "m" and "fm"; the daily caps tell their runs apart by the billing of the model's
    # credential, so "fm" passes the invented variable the stand-in manifest declares metered.
    st.set_models(monkeypatch, lab, passes={"fm": ["STANDIN_FLOOR_PASS"]})
    (built["tree"] / "flows" / "single.json").write_text(json.dumps({"flow": "single", "title": "Single", "tasks": [
        {"key": "profile", "skill": "demo-writes", "title": "Profile", "text": "write the profile."}]}), encoding="utf-8")
    configure(built, AGENTS)
    return built


def configure(tree, agents, **extra) -> None:
    path = tree["project"] / "docs" / "workbench" / "runtime.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["area_agents"] = agents
    raw.update(extra)
    path.write_text(json.dumps(raw), encoding="utf-8")
    project = str(tree["project"])
    ops.accept_config(project, ops.project_config.load(project)["sha256"])


def planned(tree, flow: str) -> int:
    path = str(tree["project"])
    request = ops.request(path, "Invented request.", title="Invented")["request"]
    pending_id = ops.route(path, request, flow)["pending_id"]
    ops.approve(path, pending_id, ops.pending(path, pending_id)["payload"]["plan_sha256"])
    return request


@pytest.fixture
def utc(monkeypatch):
    """The local day is the system's: pin it to UTC for a test that compares a day with a UTC date."""
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def stored(tree):
    ctx = ops_core.context(str(tree["project"]))
    return ctx["store"], ctx["conn"]


# --- agents ------------------------------------------------------------------------------------------------------------


def test_the_agents_operation_reports_each_agents_mode_caps_and_use_of_today_from_the_records(tree):
    path = str(tree["project"])
    first = ops.agents(path)["agents"]
    assert [a["name"] for a in first] == ["business", "engineering", "design"]  # the configuration's order
    business, engineering, design = first
    assert (business["pack"], business["enabled"], business["mode"], business["acting_mode"]) == ("biz", True, "supervised", "supervised")
    assert (business["max_runs_per_day"], business["max_usd_per_day"]) == (3, 2.5)
    assert (business["runs_today"], business["usd_today"], business["runs_without_cost"], business["queued"]) == (0, 0.0, 0, 0)
    # A mode of autonomy with a policy that no approval backs acts as autonomous; an agent that is off acts as stopped.
    assert (engineering["mode"], engineering["acting_mode"]) == ("autonomous-with-policy", "autonomous")
    assert (design["enabled"], design["mode"], design["acting_mode"], design["max_usd_per_day"]) == (False, "milestones", "stopped", 0)
    # Records: a plan of the business pack makes one task ready for the business agent; a run of it is a run of today.
    planned(tree, "single")
    assert ops.agents(path)["agents"][0]["queued"] == 1
    assert ops.run_next(path)["status"] == "ok"
    seen = ops.agents(path)["agents"][0]
    assert (seen["runs_today"], seen["usd_today"], seen["queued"]) == (1, 0.0, 0)
    # The dollars of the day are the floor model's runs; one with no recorded cost counts at the per-run bound.
    store, conn = stored(tree)
    task = next(t for t in store.tasks_list(conn) if t["parent_id"] is not None)
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    for cost in (0.4, None):
        conn.execute("INSERT INTO task_runs (task_id, skill, model, adapter, status, started_at, cost_usd) VALUES (?, ?, 'fm', 'h', 'ok', ?, ?)",
                     (task["id"], task["skill"], now, cost))
    conn.commit()
    seen = ops.agents(path)["agents"][0]
    assert seen["runs_today"] == 1 and seen["usd_today"] == pytest.approx(0.4 + ops.PER_RUN_USD) and seen["runs_without_cost"] == 1
    # A run of an earlier day is not counted.
    conn.execute("UPDATE task_runs SET started_at = '2020-01-01T10:00:00.000000Z' WHERE model = 'fm'")
    conn.commit()
    assert ops.agents(path)["agents"][0]["usd_today"] == 0.0
    # A project with no area agents has no agents.
    raw = json.loads((tree["project"] / "docs" / "workbench" / "runtime.json").read_text(encoding="utf-8"))
    del raw["area_agents"]
    (tree["project"] / "docs" / "workbench" / "runtime.json").write_text(json.dumps(raw), encoding="utf-8")
    ops.accept_config(path, ops.project_config.load(path)["sha256"])
    assert ops.agents(path) == {"agents": []}


# --- conversation -----------------------------------------------------------------------------------------------------


def test_the_conversation_operation_returns_only_the_messages_after_an_id_in_order(tree):
    path = str(tree["project"])
    assert ops.conversation(path) == {"conversation": "project", "messages": []}
    for line in ("/status", "/progress 7d", "/pending"):
        ops.say(path, line)
    everything = ops.conversation(path)["messages"]
    assert [m["role"] for m in everything] == ["user", "assistant"] * 3
    assert [m["text"] for m in everything][::2] == ["/status", "/progress 7d", "/pending"]
    assert set(everything[0]) == {"id", "role", "text", "task_id", "run_id", "created_at", "queued"}
    ids = [m["id"] for m in everything]
    assert ids == sorted(ids) and len(set(ids)) == 6
    assert ops.conversation(path, after=ids[1])["messages"] == everything[2:]
    assert ops.conversation(path, "project", ids[-1]) == {"conversation": "project", "messages": []}
    assert ops.conversation(path, conversation=None, after=None)["messages"] == everything  # left out is the default
    assert ops.conversation(path, "another")["messages"] == []
    for bad in (-1, True, "1", 1.5):
        with pytest.raises(ops.OpsError) as raised:
            ops.conversation(path, after=bad)
        assert raised.value.code == 2
    # At most 500 come back: the newest of them, oldest first.
    store, conn = stored(tree)
    for n in range(510):
        store.message_add(conn, conversation=ops.CONVERSATION, role="user", text=f"line {n}")
    page = ops.conversation(path)["messages"]
    assert len(page) == 500 and page[-1]["text"] == "line 509"
    assert [m["id"] for m in page] == sorted(m["id"] for m in page)


def test_a_second_turn_during_a_run_is_queued_on_the_page_and_stores_no_request(tree):
    """A-23: a turn from the page that would route while another run holds the lock is stored and queued, with its reply pending;
    it makes no request, no decision and no router run until the lock is free (runtime/tests/test_say_queue.py)."""
    path = str(tree["project"])
    store, conn = stored(tree)
    cfg = ops.project_config.load(path)
    with ops_core._route_lock(cfg):  # the router answers another request: it holds the route lock
        for line in ("Which market should the invented studio go after first?", "/new Another invented request."):
            kept = len(store.messages_list(conn, ops.CONVERSATION, limit=500))
            with pytest.raises(ops.OpsError) as raised:        # a shell that drains no queue is refused, as it always was
                ops.say(path, line)
            assert raised.value.code == 1 and "answering another request" in str(raised.value)
            assert len(store.messages_list(conn, ops.CONVERSATION, limit=500)) == kept   # before anything is stored
            out = ops.say(path, line, channel="page")
            assert out["queued"] is True and out["reply"] is None and out["ran"] is False and out["request_id"] is None
        messages = store.messages_list(conn, ops.CONVERSATION, limit=500)
        assert [m["role"] for m in messages] == ["user", "user"]                       # both lines are kept
        assert [m["queued"] for m in ops.conversation(path)["messages"]] == [True, True]
        assert store.tasks_list(conn) == [] and store.pending_list(conn, "all") == []  # no request, no decision
        # A command that does not route is not held back by the lock.
        assert ops.say(path, "/status")["ran"] is False
    assert len(store.messages_list(conn, ops.CONVERSATION, limit=500)) == 4
    assert st.calls(tree["adapter"]) == []


# --- skills -----------------------------------------------------------------------------------------------------------


def test_the_skills_operation_reports_the_proof_as_the_proof_module_gives_it(tree, monkeypatch):
    path = str(tree["project"])
    found = ops.skills(path)
    cfg = ops.project_config.load(path)
    assert [s["name"] for s in found["skills"]] == ["demo-asks", "demo-code", "demo-writes"]  # the packs of the enabled agents
    assert [(s["version"], s["area"], s["manifest"], s["runs_here"]) for s in found["skills"]] == [
        ("0.1.0", "business", True, 0), ("0.1.0", "engineering", True, 0), ("0.1.0", "business", True, 0)]
    for skill in found["skills"]:
        entry = proof_rules.row(cfg, skill["name"])
        assert [{key: pair[key] for key in ("model", "adapter", "band", "cause", "score", "mean", "runs")} for pair in skill["proof"]] == [
            {key: pair[key] for key in ("model", "adapter", "band", "cause", "score", "mean", "runs")} for pair in entry["pairs"]]
        assert [(p["model"], p["band"]) for p in skill["proof"]] == [("m", "reliable"), ("fm", "needs a test")]
        assert skill["recommended"] == "m"  # the cheapest reliable pair with a key, a price and a measured usage
    assert [(m["model"], m["skills"], m["reliable"]) for m in found["models"]] == [("m", 3, 3), ("fm", 3, 0)]
    assert found["checks"] == {"measurement": "ok", "image": "ok"}
    # What the proof module gives is what is reported, never a recomputation: a canned entry comes out as it is.
    canned = {"inputs_sha256": "x", "skill_version": "9.9.9", "evidence_images": [st.STANDIN_IMAGE],
              "pairs": [{"tier": "strong", "model": "invented-model", "adapter": "invented-adapter", "band": "watch",
                         "cause": "invented cause", "score": 0.42, "mean": 0.5, "runs": 7, "extra": "not reported"}]}
    with monkeypatch.context() as patched:
        patched.setattr(proof_rules, "row", lambda cfg_, name: canned)
        (shown,) = ops.skills(path)["skills"][0]["proof"]
        assert {k: shown[k] for k in ("model", "adapter", "band", "cause", "score", "mean", "runs", "source")} == {
            "model": "invented-model", "adapter": "invented-adapter", "band": "watch", "cause": "invented cause", "score": 0.42,
            "mean": 0.5, "runs": 7, "source": None} and "extra" not in shown
    # The runs of the skill in this project, the manifest, and the two checks.
    planned(tree, "single")
    ops.run_next(path)
    os.remove(tree["tree"] / "skills" / "demo-code" / "evals" / "runtime-manifest.json")
    by_name = {s["name"]: s for s in ops.skills(path)["skills"]}
    assert by_name["demo-writes"]["runs_here"] == 1 and by_name["demo-asks"]["runs_here"] == 0
    assert by_name["demo-code"]["manifest"] is False and by_name["demo-writes"]["manifest"] is True
    monkeypatch.setattr(lab, "measurement_problem", lambda: "the measurement files differ from the recorded ones")
    assert ops.skills(path)["checks"]["measurement"] == "the measurement files differ from the recorded ones"
    monkeypatch.setattr(lab, "image", lambda: {"name": "standin", "digest": None, "platform": None})
    assert ops.skills(path)["checks"]["image"] == "the eval image is not on this machine"
    monkeypatch.setattr(lab, "image", lambda: {"name": "standin", "digest": "sha256:" + "6" * 64, "platform": None})
    assert "not the one the evidence of 3 skill(s) was measured in" in ops.skills(path)["checks"]["image"]
    # Without area agents the default pack is the scope.
    raw = json.loads((tree["project"] / "docs" / "workbench" / "runtime.json").read_text(encoding="utf-8"))
    del raw["area_agents"]
    (tree["project"] / "docs" / "workbench" / "runtime.json").write_text(json.dumps(raw), encoding="utf-8")
    ops.accept_config(path, ops.project_config.load(path)["sha256"])
    assert [s["name"] for s in ops.skills(path)["skills"]] == PACKS["default"]


# --- costs ------------------------------------------------------------------------------------------------------------


def test_the_costs_operation_recomputes_from_the_prices_and_counts_what_is_unknown(tree, utc, monkeypatch):
    path = str(tree["project"])
    prices = st.load("prices")
    monkeypatch.setattr(prices, "load", lambda path=None: {"models": {}})  # no price yet in the one price table
    planned(tree, "single")
    run = ops.run_next(path)
    assert run["status"] == "ok"
    empty = ops.costs(path)
    today = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    assert empty["since"] == (datetime.date.today() - datetime.timedelta(days=30)).isoformat()
    # The caps carry the day's use in the words of `agents` (WP-9.14b); the first three keys are the cap itself.
    assert [{k: c[k] for k in ("agent", "max_runs_per_day", "max_usd_per_day")} for c in empty["caps"]] == [
        {"agent": n, "max_runs_per_day": a["max_runs_per_day"], "max_usd_per_day": a["max_usd_per_day"]}
        for n, a in {"business": AGENTS["business"], "engineering": AGENTS["engineering"],
                     "design": {"max_runs_per_day": 2, "max_usd_per_day": 0}}.items()]
    assert all(set(c) == {"agent", "max_runs_per_day", "max_usd_per_day", "runs_today", "usd_today", "runs_without_cost",
                          "usd_recorded", "usd_reserved", "runs_total_today"} for c in empty["caps"])
    (row,) = empty["rows"]
    # The stand-in adapter leaves timing.json only: the total is there, the kinds are not. The run's credential is the harness's
    # login, billed as a subscription, so no cost is recorded for it (ADJ-R3): the adapter's figure, 0.01, is not billed.
    assert (row["day"], row["agent"], row["model"], row["adapter"], row["runs"], row["tokens"], row["recorded_usd"]) == (
        today, "business", "m", "h", 1, 100, None)
    assert row["recomputed_usd"] is None and row["unknown_runs"] == 1 and row["price"] is None
    # With a result event in the run folder and a price in the configuration, the cost is recomputed.
    event = {"type": "result", "usage": {"input_tokens": 1000, "output_tokens": 2000, "cache_read_input_tokens": 100000,
                                         "cache_creation_input_tokens": 4000}}
    with open(os.path.join(run["run_dir"], "outputs", "raw.json"), "w", encoding="utf-8") as f:
        json.dump(event, f)
    assert ops.costs(path)["rows"][0]["recomputed_usd"] is None  # no price yet: unknown, never a guess
    monkeypatch.setattr(prices, "load", lambda path=None: PRICES)  # the one price table gets a price: nothing in runtime.json
    (row,) = ops.costs(path)["rows"]
    assert row["recomputed_usd"] == pytest.approx(0.078) and row["unknown_runs"] == 0
    assert row["price"]["source"] == PRICES["models"]["m"]["source"] and row["price"]["accessed"] == "2025-12-31"
    assert row["price"]["stale"] is True and row["price"]["age_days"] > 90  # a price older than price_max_age_days is shown as stale
    # A run folder outside the data folder's task-runs is not read.
    elsewhere = tree["data"].parent / "elsewhere"
    shutil.copytree(run["run_dir"], elsewhere)
    store, conn = stored(tree)
    conn.execute("UPDATE task_runs SET run_dir = ?", (str(elsewhere),))
    conn.commit()
    (row,) = ops.costs(path)["rows"]
    assert row["recomputed_usd"] is None and row["unknown_runs"] == 1
    # since is a day; an earlier day leaves the run out; anything else is a usage error.
    assert ops.costs(path, since=(datetime.date.today() + datetime.timedelta(days=1)).isoformat())["rows"] == []
    assert ops.costs(path, since="2020-01-01")["since"] == "2020-01-01"
    for bad in ("7d", "yesterday", "2020-13-01"):
        with pytest.raises(ops.OpsError) as raised:
            ops.costs(path, since=bad)
        assert raised.value.code == 2


# --- connections ------------------------------------------------------------------------------------------------------


def with_needs(tree, requires: str) -> None:
    skill = tree["tree"] / "skills" / "demo-writes" / "SKILL.md"
    skill.write_text(skill.read_text(encoding="utf-8").replace("requires: []", f"requires: [{requires}]"), encoding="utf-8")


def test_the_connections_operation_never_returns_a_secrets_value(tree, monkeypatch):
    path = str(tree["project"])
    for rel in ("providers/secrets/resolver.py", "runtime/secrets.json"):
        (tree["tree"] / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(st.REPO / rel, tree["tree"] / rel)
    with_needs(tree, "integration:vcs, search:web, generator:image")
    resolver = ops_core._load("workbench_secret_resolver_runtime", str(tree["tree"] / "providers" / "secrets" / "resolver.py"))
    monkeypatch.setattr(resolver, "_keyring", lambda: None)  # the OS secret store is not asked in a test
    st.set_models(monkeypatch, lab, passes={"m": ["INVENTED_MODEL_KEY"]})
    monkeypatch.setenv("WB_RUNTIME_KEY_OPENROUTER_API_KEY", PLANTED_ONE)
    monkeypatch.setenv("INVENTED_MODEL_KEY", PLANTED_TWO)
    monkeypatch.setattr(lab, "image", lambda: {"name": "standin", "digest": st.STANDIN_IMAGE, "platform": "linux/arm64",
                                               "evidence_platform": "linux/arm64"})

    def never(*args, **kwargs):
        raise AssertionError("connections started a process or opened a connection")

    for module, name in ((subprocess, "run"), (subprocess, "Popen"), (socket, "create_connection"), (socket.socket, "connect")):
        monkeypatch.setattr(module, name, never)
    found = ops.connections(path)
    text = json.dumps(found)
    assert PLANTED_ONE not in text and PLANTED_TWO not in text
    classes = {c["class"]: c for c in found["classes"]}
    assert sorted(classes) == ["generator:image", "integration:vcs", "search:web"]
    assert (classes["integration:vcs"]["provider"], classes["integration:vcs"]["found"]) == ("github", True)
    assert classes["integration:vcs"]["skills"] == ["demo-writes"] and "only-implementation" in classes["integration:vcs"]["note"]
    for missing in ("search:web", "generator:image"):
        assert classes[missing]["found"] is False and classes[missing]["provider"] is None and classes[missing]["note"]
    secrets = {s["name"]: s for s in found["secrets"]}
    assert set(secrets["WB_RUNTIME_KEY_OPENROUTER_API_KEY"]) == {"name", "found", "where"}
    assert secrets["WB_RUNTIME_KEY_OPENROUTER_API_KEY"]["found"] is True
    assert secrets["WB_RUNTIME_KEY_OPENROUTER_API_KEY"]["where"] == "environment (WB_RUNTIME_KEY_OPENROUTER_API_KEY)"
    assert secrets["INVENTED_MODEL_KEY"] == {"name": "INVENTED_MODEL_KEY", "found": True, "where": "environment or secret store"}
    assert any(not s["found"] and s["where"] is None for s in found["secrets"])  # the providers' credentials, not set here
    assert os.environ["INVENTED_MODEL_KEY"] == PLANTED_TWO  # the environment is as it was
    assert found["image"] == {"name": "standin", "present": True, "evidence": True}
    assert found["platform"] == ops_reads._platform_row(platform_module.machine(), sys.platform, "linux/arm64")
    assert set(found["platform"]) == {"machine", "evidence", "here", "same"}
    assert found["platform"]["machine"] == platform_module.machine()
    # An image that is not the evidence's, and no image.
    monkeypatch.setattr(lab, "image", lambda: {"name": "standin", "digest": "sha256:" + "6" * 64, "platform": "linux/arm64",
                                               "evidence_platform": "linux/arm64"})
    assert ops.connections(path)["image"] == {"name": "standin", "present": True, "evidence": False}
    monkeypatch.setattr(lab, "image", lambda: {"name": None, "digest": None, "platform": None, "evidence_platform": None})
    assert ops.connections(path)["image"] == {"name": None, "present": False, "evidence": None}
    assert ops.connections(path)["platform"]["evidence"] is None
    monkeypatch.delitem(sys.modules, "workbench_secret_resolver_runtime", raising=False)


@pytest.mark.parametrize("machine,system,evidence,here,same", [
    ("arm64", "darwin", "linux/arm64", "linux/arm64", True),     # a Mac runs the Linux image on its own architecture
    ("aarch64", "linux", "linux/arm64", "linux/arm64", True),
    ("x86_64", "linux", "linux/arm64", "linux/amd64", False),    # another architecture: the evidence is not this machine's
    ("AMD64", "win32", "linux/amd64", "linux/amd64", True),
    ("arm64", "linux", None, "linux/arm64", None),               # the evidence's platform is unknown
    ("", "linux", "linux/arm64", None, None),                    # this machine's is unknown
    ("riscv64", "linux", "linux/arm64", None, None),             # an architecture the executor does not name
    ("arm64", "freebsd14", "linux/arm64", None, None),           # a system whose containers are not known
])
def test_the_platform_row_says_whether_this_machine_is_the_evidences(tree, monkeypatch, machine, system, evidence, here, same):
    path = str(tree["project"])
    monkeypatch.setattr(lab, "image", lambda: {"name": None, "digest": None, "platform": None, "evidence_platform": evidence})
    monkeypatch.setattr(platform_module, "machine", lambda: machine)
    monkeypatch.setattr(sys, "platform", system)
    assert ops.connections(path)["platform"] == {"machine": machine or None, "evidence": evidence, "here": here, "same": same}


def test_the_connections_operation_resolves_a_class_as_the_configuration_names_it(tree, monkeypatch):
    path = str(tree["project"])
    with_needs(tree, "integration:vcs")
    other = tree["tree"] / "providers" / "vcs" / "other.py"
    other.write_text((tree["tree"] / "providers" / "vcs" / "github.py").read_text(encoding="utf-8"), encoding="utf-8")
    assert ops.connections(path)["classes"][0]["found"] is False  # two providers and none selected
    configure(tree, AGENTS, code={"provider": "github", "repo": "example-org/web", "base": "main"})
    row = ops.connections(path)["classes"][0]
    assert (row["provider"], row["found"]) == ("github", True) and "configuration" in row["note"]


# --- artifacts --------------------------------------------------------------------------------------------------------


def write(tree, rel: str, text="text\n") -> None:
    target = tree["project"].joinpath(*rel.split("/"))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def test_artifacts_lists_only_documents_under_docs_with_their_owner_and_never_the_configuration(tree, tmp_path):
    path = str(tree["project"])
    # A run leaves a document and a machine file; its review binds them until the person decides.
    ops.request(path, "Invented request.", "demo")
    first = ops.run_next(path)
    ops.answer(path, first["pending_id"], "here")
    second = ops.run_next(path)
    assert second["returned"][1]["path"] == "docs/business/market.md"
    write(tree, "docs/business/icp.md", "# Profile\n")
    write(tree, "docs/notes/readme.md", "# Notes\n")
    write(tree, "docs/data/table.csv", "a,b\n")
    write(tree, "docs/.git/config", "[core]\n")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.md").write_text("# not the project's\n", encoding="utf-8")
    os.symlink(outside / "secret.md", tree["project"] / "docs" / "link.md")
    os.symlink(outside, tree["project"] / "docs" / "linked")
    found = ops.artifacts(path)
    by_path = {a["path"]: a for a in found["artifacts"]}
    assert list(by_path) == sorted(by_path) and found["truncated"] is False
    assert set(by_path) == {"docs/business/icp.md", "docs/business/market.lint.json", "docs/business/market.md",
                            "docs/data/table.csv", "docs/notes/readme.md"}
    assert by_path["docs/business/market.md"]["owner"] == "demo-asks" and by_path["docs/business/icp.md"]["owner"] == "demo-writes"
    assert by_path["docs/notes/readme.md"]["owner"] is None and by_path["docs/data/table.csv"]["owner"] is None
    assert by_path["docs/notes/readme.md"]["size"] == len("# Notes\n")
    assert datetime.datetime.strptime(by_path["docs/notes/readme.md"]["modified_at"], "%Y-%m-%dT%H:%M:%SZ")
    # Bound: the open review lists what the run returned; a file no decision lists is not bound.
    assert by_path["docs/business/market.md"]["bound"] is True and by_path["docs/business/market.lint.json"]["bound"] is True
    assert by_path["docs/business/icp.md"]["bound"] is False and by_path["docs/notes/readme.md"]["bound"] is False
    ops.release(path, second["pending_id"])
    assert ops.artifacts(path)["artifacts"][0]["bound"] is False
    # Never the configuration, the state file, a link, a file outside docs/, or what the path rule drops.
    for hidden in ("docs/workbench/runtime.json", "docs/workbench/state.md", "docs/link.md", "docs/linked/secret.md", "docs/.git/config",
                   "AGENTS.md"):
        assert hidden not in by_path
    # A project with no docs/ folder has no artifacts.
    shutil.rmtree(tree["project"] / "docs" / "business")
    shutil.rmtree(tree["project"] / "docs" / "notes")
    shutil.rmtree(tree["project"] / "docs" / "data")
    assert ops.artifacts(path)["artifacts"] == []


def without_area_agents(tree) -> None:
    path = str(tree["project"])
    raw = json.loads((tree["project"] / "docs" / "workbench" / "runtime.json").read_text(encoding="utf-8"))
    del raw["area_agents"]
    (tree["project"] / "docs" / "workbench" / "runtime.json").write_text(json.dumps(raw), encoding="utf-8")
    ops.accept_config(path, ops.project_config.load(path)["sha256"])


def test_the_status_task_rows_carry_their_title_and_agent(tree):
    path = str(tree["project"])
    request = planned(tree, "single")
    row = next(r for r in ops.status(path)["requests"] if r["id"] == request)
    assert [(t["key"], t["title"], t["agent"]) for t in row["tasks"]] == [("profile", "Profile", "business")]
    # The additions are the store's own columns and the derived waits (ops_waits.py): a task row carries nothing else
    # new, and a request row the request it runs after.
    assert set(row["tasks"][0]) == {"id", "key", "title", "agent", "skill", "state", "note", "on_board", "open_comments",
                                    "waiting_for", "holds_slot"}
    assert set(row) == {"id", "title", "flow", "state", "on_board", "open_comments", "after", "tasks", "routing", "model"}   # R4-L1: routing, the router's run on the request or None; P3: the model named on the request or None
    # Without area agents the agent of a task planned now is None; the title is still there.
    without_area_agents(tree)
    later = planned(tree, "single")
    row = next(r for r in ops.status(path)["requests"] if r["id"] == later)
    assert [(t["title"], t["agent"]) for t in row["tasks"]] == [("Profile", None)]


def test_a_pending_decision_carries_the_agent_of_its_task_and_none_for_a_request_level_decision(tree):
    path = str(tree["project"])
    request = ops.request(path, "Invented request.", title="Invented")["request"]
    plan_id = ops.route(path, request, "single")["pending_id"]
    # A plan waits on the request itself: no agent, in the list, as one item and in the status.
    assert [(p["id"], p["kind"], p["agent"]) for p in ops.pending(path)["pending"]] == [(plan_id, "plan", None)]
    assert ops.pending(path, plan_id)["agent"] is None
    assert [p["agent"] for p in ops.status(path)["pending"]] == [None]
    assert [p["agent"] for p in ops.task(path, request)["pending"]] == [None]
    ops.approve(path, plan_id, ops.pending(path, plan_id)["payload"]["plan_sha256"])
    # A run of the task leaves a decision on the task: the agent of the task.
    assert ops.run_next(path)["status"] == "ok"
    waiting = ops.pending(path)["pending"]
    assert len(waiting) == 1 and waiting[0]["task_id"] != request and waiting[0]["agent"] == "business"
    assert ops.pending(path, waiting[0]["id"])["agent"] == "business"
    assert [p["agent"] for p in ops.status(path)["pending"]] == ["business"]
    assert [p["agent"] for p in ops.task(path, waiting[0]["task_id"])["pending"]] == ["business"]
    # The request's own decisions, once resolved, still show no agent.
    assert [(p["kind"], p["agent"]) for p in ops.task(path, request)["pending"]] == [("plan", None)]
    # Without area agents a decision on a task planned now has no agent either.
    without_area_agents(tree)
    later = planned(tree, "single")
    assert ops.run_next(path)["status"] == "ok"
    newest = ops.pending(path)["pending"][-1]
    assert newest["task_id"] != later and newest["agent"] is None


def test_an_artifact_row_carries_the_agent_whose_pack_holds_its_owner(tree):
    path = str(tree["project"])
    write(tree, "docs/business/market.md", "# Market\n")
    write(tree, "docs/business/icp.md", "# Profile\n")
    write(tree, "docs/notes/readme.md", "# Notes\n")
    by_path = {a["path"]: a for a in ops.artifacts(path)["artifacts"]}
    assert (by_path["docs/business/market.md"]["owner"], by_path["docs/business/market.md"]["agent"]) == ("demo-asks", "business")
    assert (by_path["docs/business/icp.md"]["owner"], by_path["docs/business/icp.md"]["agent"]) == ("demo-writes", "business")
    # No owner, no agent. The key is always there.
    assert (by_path["docs/notes/readme.md"]["owner"], by_path["docs/notes/readme.md"]["agent"]) == (None, None)
    assert set(by_path["docs/notes/readme.md"]) == {"path", "owner", "agent", "size", "modified_at", "kind", "bound"}
    # A skill in the pack of two enabled agents has no one agent: None, not a guess.
    configure(tree, {**AGENTS, "assistant": {"pack": "biz", "mode": "supervised"}})
    assert {a["path"]: a["agent"] for a in ops.artifacts(path)["artifacts"] if a["owner"]} == {
        "docs/business/market.md": None, "docs/business/icp.md": None}
    # Without area agents no row has an agent.
    without_area_agents(tree)
    assert {a["agent"] for a in ops.artifacts(path)["artifacts"]} == {None}


def test_an_artifact_outside_docs_a_symlink_or_the_configuration_is_refused(tree, tmp_path):
    path = str(tree["project"])
    write(tree, "docs/business/market.md", "# Market\n\nUnicode: café.\n")
    got = ops.artifact(path, "docs/business/market.md")
    assert got["path"] == "docs/business/market.md" and got["text"] == "# Market\n\nUnicode: café.\n"
    assert got["size"] == len(got["text"].encode("utf-8")) and got["modified_at"].endswith("Z")
    assert ops.artifact(path, "./docs//business/market.md")["path"] == "docs/business/market.md"  # normalised first
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.md").write_text("OUTSIDE-CONTENT", encoding="utf-8")
    os.symlink(outside / "secret.md", tree["project"] / "docs" / "link.md")
    os.symlink(outside, tree["project"] / "docs" / "linked")
    write(tree, "docs/big.md", "x" * (ops.ARTIFACT_MAX_BYTES + 1))
    write(tree, "docs/exact.md", "x" * ops.ARTIFACT_MAX_BYTES)
    (tree["project"] / "docs" / "binary.bin").write_bytes(b"\xff\xfe\x00\x01")
    (tree["project"] / "docs" / "nul.md").write_bytes(b"text\x00more")
    (tree["project"] / "docs" / "folder.md").mkdir()
    for refused in ("AGENTS.md", "../outside/secret.md", "/etc/hosts", "docs/../AGENTS.md", "docs", "docs/workbench/runtime.json",
                    "./docs/workbench/runtime.json", "docs/workbench//runtime.json", "docs/link.md", "docs/linked/secret.md",
                    "docs/big.md", "docs/binary.bin", "docs/nul.md", "docs/folder.md", "", "~/x", "docs/.git/config", "README.md"):
        with pytest.raises(ops.OpsError) as raised:
            ops.artifact(path, refused)
        assert raised.value.code == 2, refused
        assert "OUTSIDE-CONTENT" not in str(raised.value)
    assert len(ops.artifact(path, "docs/exact.md")["text"]) == ops.ARTIFACT_MAX_BYTES  # the limit itself is read
    with pytest.raises(ops.OpsError) as raised:
        ops.artifact(path, "docs/business/missing.md")
    assert raised.value.code == 1
    for bad in (None, 7, ["docs/x.md"]):
        with pytest.raises(ops.OpsError):
            ops.artifact(path, bad)


# --- the terminal ----------------------------------------------------------------------------------------------------


def test_each_new_read_is_a_verb_of_the_terminal_with_its_own_flags(tree, capsys):
    path = str(tree["project"])
    write(tree, "docs/notes/readme.md", "# Notes\n")
    for argv, key in ((["agents"], "agents"), (["conversation", "--after", "0"], "messages"), (["skills"], "skills"),
                      (["costs", "--since", "2020-01-01"], "rows"), (["connections"], "classes"), (["artifacts"], "artifacts"),
                      (["artifact", "--path", "docs/notes/readme.md"], "text")):
        assert cli.main([*argv, "--project", path]) == 0, argv
        assert key in json.loads(capsys.readouterr().out)
    assert cli.main(["conversation", "--after", "x", "--project", path]) == 2
    assert cli.main(["artifact", "--project", path]) == 2  # --path is required
    assert cli.main(["artifact", "--path", "../x", "--project", path]) == 2
    capsys.readouterr()
    assert cli.main(["--help"]) == 0
    help_text = capsys.readouterr().out
    for verb in ("agents", "conversation", "skills", "costs", "connections", "artifacts", "artifact"):
        assert f"python3 runtime/cli.py {verb} " in help_text, verb


def test_a_resolved_decision_in_the_task_read_carries_the_text_the_person_saved(tree):
    """A-41 (ADJ-B4): the `pending[]` rows of the `task` read carry `answer`, the one column where the store keeps an answer to a
    question, a comment on a review or on an effect, and the note of a rejection; it is None when the person saved no text."""
    path = str(tree["project"])
    ops.request(path, "Invented request.", "demo")
    first = ops.run_next(path)
    ops.answer(path, first["pending_id"], "The price with tax, always.")
    second = ops.run_next(path)
    ops.answer(path, second["pending_id"], "Shorten the second paragraph.")
    third = ops.run_next(path)
    ops.release(path, third["pending_id"])

    def rows():
        found = {}
        for task_id in {t["id"] for r in ops.status(path)["requests"] for t in r["tasks"]}:
            for item in ops.task(path, task_id)["pending"]:
                found[item["id"]] = item
        return found

    seen = rows()
    said = seen[first["pending_id"]]
    assert (said["kind"], said["status"], said["resolution"], said["answer"]) == ("question", "resolved", "answered", "The price with tax, always.")
    comment = seen[second["pending_id"]]
    assert (comment["kind"], comment["resolution"], comment["answer"]) == ("review", "answered", "Shorten the second paragraph.")
    released = seen[third["pending_id"]]
    assert (released["kind"], released["resolution"], released["answer"]) == ("review", "released", None), "a release saves no text"
    # a rejected plan keeps its note in the same field, and a rejection without a note keeps none
    for note in ("Too early: wait for the sale page.", None):
        later = ops.request(path, "Another invented request.", title="Another")["request"]
        plan_id = ops.route(path, later, "single")["pending_id"]
        ops.reject(path, plan_id, note)
        row = next(p for p in ops.task(path, later)["pending"] if p["id"] == plan_id)
        assert (row["kind"], row["resolution"], row["answer"]) == ("plan", "rejected", note)
    approved = ops.request(path, "A third invented request.", title="Third")["request"]
    approved_plan = ops.route(path, approved, "single")["pending_id"]
    ops.approve(path, approved_plan, ops.pending(path, approved_plan)["payload"]["plan_sha256"])
    row = next(p for p in ops.task(path, approved)["pending"] if p["id"] == approved_plan)
    assert (row["resolution"], row["answer"]) == ("approved", None), "an approval saves no text"
