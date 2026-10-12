"""Tests of the derived waits (A-29) through the operations layer on the stand-in tree of standin_tree.py: three
requests whose skills chain (brand, design, marketing), the plan that says what waits and what nothing writes, the
override `after`, the go-ahead, the re-derivation, the state file, the read results and the task board's note and
`after #n`. Offline; every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_derived_waits_ops.py
"""
from __future__ import annotations

import json
import shutil

import pytest

import standin_tree as st

lab = st.load("lab")
ops = st.load("ops")
ops_core = st.load("ops_core")
ops_waits = st.load("ops_waits")
plan = st.load("plan")
board = st.load("board")

PACKS = {"all": ["wk-brand", "wk-voice", "wk-design", "wk-market"], "default": ["wk-brand", "wk-voice", "wk-design", "wk-market"]}
AGENTS = {"everything": {"pack": "all", "mode": "supervised", "max_runs_per_day": 9, "max_usd_per_day": 5.0}}
INPUTS = ("\n## Inputs\n\n| Artifact | Required | If missing |\n|----------|----------|------------|\n"
          "{rows}\n\n## Stop rules\n\n1. Stop.\n")
TABLES = {  # skill: [(path, required cell)]
    "wk-voice": [("docs/brand/profile.md", "yes")],
    "wk-design": [("docs/brand/identity.md", "yes"), ("docs/workbench/state.md", "no")],
    "wk-market": [("docs/design/system.md", "yes"), ("docs/brand/voice.md", "no")],
}


def add_skill(tree, name, inputs, outputs):
    folder = st.skill(tree, name, inputs, outputs)
    rows = "\n".join(f"| {p} | {r} | Stop. |" for p, r in TABLES.get(name, []))
    if rows:
        with open(folder / "SKILL.md", "a", encoding="utf-8") as f:
            f.write(INPUTS.format(rows=rows))


@pytest.fixture
def tree(tmp_path, monkeypatch):
    built = st.build(tmp_path, monkeypatch, lab)
    root = built["tree"]
    add_skill(root, "wk-brand", "docs/workbench/state.md", "docs/brand/identity.md")
    add_skill(root, "wk-voice", "docs/workbench/state.md, docs/brand/profile.md", "docs/brand/voice.md")
    add_skill(root, "wk-design", "docs/workbench/state.md, docs/brand/identity.md", "docs/design/system.md")
    add_skill(root, "wk-market", "docs/design/system.md, docs/brand/voice.md", "docs/marketing/posts.md")
    flows = {"wk-brand": [("identity", "wk-brand", []), ("voice", "wk-voice", [])],
             "wk-design": [("system", "wk-design", [])], "wk-market": [("posts", "wk-market", [])]}
    for name, tasks in flows.items():
        (root / "flows" / f"{name}.json").write_text(json.dumps({"flow": name, "title": name.title(), "tasks": [
            {"key": k, "skill": s, "title": k.title(), "text": f"do {k}.", "depends_on": d} for k, s, d in tasks]}),
            encoding="utf-8")
    monkeypatch.setattr(ops_core, "ROOT", str(root))
    monkeypatch.setattr(plan, "resolve_pack", lambda pack, _root: list(PACKS[pack]))
    path = built["project"] / "docs" / "workbench" / "runtime.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["area_agents"] = AGENTS
    path.write_text(json.dumps(raw), encoding="utf-8")
    project = str(built["project"])
    ops.accept_config(project, ops.project_config.load(project)["sha256"])
    return built


def path_of(tree) -> str:
    return str(tree["project"])


def requested(tree, flow, **kwargs) -> dict:
    return ops.request(path_of(tree), f"Invented {flow}.", flow=flow, **kwargs)


def by_key(made) -> dict:
    return {t["key"]: t for t in made["tasks"]}


def row(tree, task_id) -> dict:
    for request in ops.status(path_of(tree))["requests"]:
        for t in request["tasks"]:
            if t["id"] == task_id:
                return t
    raise AssertionError(task_id)


def finish(tree, task_id):
    """Run a task to a review and release it, as a person does: the task is done."""
    ctx = ops_core.context(path_of(tree))
    s = ctx["store"]
    claimed = s.task_claim(ctx["conn"], task_id)["task"]
    run = s.task_run_start(ctx["conn"], claimed["id"], skill=claimed["skill"], model="m", adapter="h")
    done = s.task_run_finish(ctx["conn"], run["run_id"], status="ok", ending="done", task_state="waiting",
                             pending={"kind": "review", "title": "t", "body": "draft"})
    return ops.release(path_of(tree), done["pending_id"])


def test_a_design_request_made_behind_the_brand_chain_waits_for_the_identity_with_its_reason(tree):
    brand = requested(tree, "wk-brand")
    design = requested(tree, "wk-design")
    identity = by_key(brand)["identity"]["id"]
    [system] = design["tasks"]
    assert system["state"] == "planned"  # the store never made it ready
    assert design["waits"] == [{"task_key": "system", "task_id": identity,
                                "reason": f"docs/brand/identity.md, written by task #{identity}"}]
    waiting = row(tree, system["id"])["waiting_for"]
    assert waiting == [{"task_id": identity, "request_id": brand["request"],
                        "reason": f"docs/brand/identity.md, written by task #{identity}"}]
    assert row(tree, identity)["waiting_for"] == [] and row(tree, identity)["state"] == "ready"


@pytest.mark.parametrize("order", [("wk-brand", "wk-design", "wk-market"), ("wk-market", "wk-design", "wk-brand"),
                                   ("wk-design", "wk-market", "wk-brand"), ("wk-market", "wk-brand", "wk-design")])
def test_the_chain_orders_itself_whatever_the_order_the_requests_were_made_in(tree, order):
    made = {flow: requested(tree, flow) for flow in order}
    ids = {flow: by_key(m) for flow, m in made.items()}
    identity, voice = ids["wk-brand"]["identity"]["id"], ids["wk-brand"]["voice"]["id"]
    system, posts = ids["wk-design"]["system"]["id"], ids["wk-market"]["posts"]["id"]
    got = {t: sorted(w["task_id"] for w in row(tree, t)["waiting_for"]) for t in (identity, voice, system, posts)}
    assert got == {identity: [], voice: [], system: [identity], posts: sorted([voice, system])}
    assert row(tree, identity)["state"] == "ready" and row(tree, voice)["state"] == "ready"
    assert row(tree, system)["state"] == "planned" and row(tree, posts)["state"] == "planned"


def test_the_store_gives_the_waiting_task_to_no_run_and_the_dispatcher_does_not_see_it_ready(tree):
    brand = requested(tree, "wk-brand")
    system = requested(tree, "wk-design")["tasks"][0]["id"]
    ctx = ops_core.context(path_of(tree))
    assert ctx["store"].task_peek_next(ctx["conn"])["task"]["id"] == by_key(brand)["identity"]["id"]
    snapshot = ops._snapshot(ctx, {})
    assert system not in [t["id"] for t in snapshot["ready"]]
    assert system not in [h["task_id"] for h in ops.status(path_of(tree))["held"]]  # it is waiting, not held ready


def test_the_wait_ends_when_the_awaited_task_is_released_and_the_task_becomes_ready(tree):
    brand = requested(tree, "wk-brand")
    system = requested(tree, "wk-design")["tasks"][0]["id"]
    finish(tree, by_key(brand)["identity"]["id"])
    after = row(tree, system)
    assert after["state"] == "ready" and after["waiting_for"] == []


def test_the_wait_ends_when_the_file_appears_in_the_project_even_if_no_task_ended(tree):
    brand = requested(tree, "wk-brand")
    system = requested(tree, "wk-design")["tasks"][0]["id"]
    identity = by_key(brand)["identity"]["id"]
    (tree["project"] / "docs" / "brand").mkdir(parents=True)
    (tree["project"] / "docs" / "brand" / "identity.md").write_text("# Identity\n", encoding="utf-8")
    ops.poll(path_of(tree))  # the short job derives again
    assert row(tree, system)["waiting_for"] == [] and row(tree, system)["state"] == "ready"
    assert row(tree, identity)["state"] == "ready"  # the identity task itself is untouched


def test_a_request_cancelled_frees_what_waited_for_it(tree):
    brand = requested(tree, "wk-brand")
    system = requested(tree, "wk-design")["tasks"][0]["id"]
    ops.cancel(path_of(tree), brand["request"])
    assert row(tree, system)["state"] == "ready" and row(tree, system)["waiting_for"] == []


def test_a_request_cancelled_while_its_task_waited_leaves_no_open_wait_on_the_cancelled_task(tree):
    requested(tree, "wk-brand")
    design = requested(tree, "wk-design")
    system = design["tasks"][0]["id"]
    assert len(row(tree, system)["waiting_for"]) == 1
    ops.cancel(path_of(tree), design["request"])
    assert row(tree, system)["state"] == "cancelled" and row(tree, system)["waiting_for"] == []


def test_a_task_that_failed_keeps_waiting_tasks_waiting_and_retrying_it_derives_again(tree):
    brand = requested(tree, "wk-brand")
    system = requested(tree, "wk-design")["tasks"][0]["id"]
    identity = by_key(brand)["identity"]["id"]
    ctx = ops_core.context(path_of(tree))
    s = ctx["store"]
    s.task_claim(ctx["conn"], identity)
    run = s.task_run_start(ctx["conn"], identity, skill="wk-brand", model="m", adapter="h")
    s.task_run_finish(ctx["conn"], run["run_id"], status="failed", failure="timeout", task_state="failed")
    assert row(tree, system)["state"] == "planned" and len(row(tree, system)["waiting_for"]) == 1
    ops.retry(path_of(tree), identity)
    assert row(tree, identity)["state"] == "ready" and row(tree, system)["state"] == "planned"


def test_the_plan_lists_the_waits_before_approval_and_the_hash_it_asks_for_does_not_move(tree):
    brand = requested(tree, "wk-brand")
    identity = by_key(brand)["identity"]["id"]
    request = ops.request(path_of(tree), "Design it.", title="Design")["request"]
    opened = ops.route(path_of(tree), request, flow="wk-design")
    item = ops.pending(path_of(tree), opened["pending_id"])
    assert item["payload"]["waits"] == [{"task_key": "system", "task_id": identity,
                                         "reason": f"docs/brand/identity.md, written by task #{identity}"}]
    assert item["payload"]["missing"] == [] and item["payload"]["cycles"] == []
    assert f"- System waits: docs/brand/identity.md, written by task #{identity}" in item["body"]
    assert item["body"].index("Waits (derived") < item["body"].index("Plan hash: ")
    assert plan.plan_hash(item["payload"]["tasks"]) == item["payload"]["plan_sha256"]
    approved = ops.approve(path_of(tree), opened["pending_id"], item["payload"]["plan_sha256"])
    system = approved["tasks"][0]
    assert system["state"] == "planned"  # created waiting, not ready
    assert approved["waits"] == item["payload"]["waits"]


def test_the_plan_says_a_required_input_nothing_writes_and_who_owns_it(tree):
    request = ops.request(path_of(tree), "Brand it.", title="Brand")["request"]
    item = ops.pending(path_of(tree), ops.route(path_of(tree), request, flow="wk-brand")["pending_id"])
    assert item["payload"]["waits"] == []
    [missing] = item["payload"]["missing"]
    assert (missing["task_key"], missing["skill"], missing["path"]) == ("voice", "wk-voice", "docs/brand/profile.md")
    assert missing["sentence"] == ("wk-voice needs docs/brand/profile.md; nothing writes it: add the file or go ahead and it "
                                   "will stop")
    assert "Inputs nothing writes:" in item["body"] and "- Voice: wk-voice needs docs/brand/profile.md" in item["body"]
    # A required input the project has is not missing.
    (tree["project"] / "docs" / "brand").mkdir(parents=True)
    (tree["project"] / "docs" / "brand" / "profile.md").write_text("# Profile\n", encoding="utf-8")
    again = ops.request(path_of(tree), "Brand it again.", title="Brand")["request"]
    assert ops.pending(path_of(tree), ops.route(path_of(tree), again, flow="wk-brand")["pending_id"])["payload"]["missing"] == []


def test_go_ahead_on_a_plan_task_drops_its_wait_and_the_state_file_records_the_persons_decision(tree):
    brand = requested(tree, "wk-brand")
    identity = by_key(brand)["identity"]["id"]
    request = ops.request(path_of(tree), "Design it.", title="Design")["request"]
    opened = ops.route(path_of(tree), request, flow="wk-design")
    with pytest.raises(ops.OpsError, match="does not have"):
        ops.approve(path_of(tree), opened["pending_id"], go_ahead=["nothing"])
    assert ops.pending(path_of(tree), opened["pending_id"])["status"] == "open"  # the refusal leaves the plan open
    out = ops.approve(path_of(tree), opened["pending_id"], go_ahead=["system"])
    system = out["tasks"][0]["id"]
    assert out["tasks"][0]["state"] == "ready" and row(tree, system)["waiting_for"] == [] and out["state"] == {"written": True}
    text = (tree["project"] / "docs" / "workbench" / "state.md").read_text(encoding="utf-8")
    assert (f"Go ahead on wk-design (task {system}) without waiting for: docs/brand/identity.md, written by task "
            f"#{identity} (user)") in text
    # The decision is about the waits that were shown: the same wait is not derived again ...
    ops.poll(path_of(tree))
    assert row(tree, system)["waiting_for"] == [] and row(tree, system)["state"] == "ready"
    # ... but a writer that replaces the one the person went ahead of is a new wait (a cancelled brand request, a new one).
    ops.cancel(path_of(tree), brand["request"])
    replacement = requested(tree, "wk-brand")
    again = row(tree, system)
    assert again["state"] == "planned"
    assert [w["task_id"] for w in again["waiting_for"]] == [by_key(replacement)["identity"]["id"]]


def test_go_ahead_takes_the_keys_as_a_list_or_joined_by_commas_and_only_on_a_plan(tree):
    requested(tree, "wk-brand")
    request = ops.request(path_of(tree), "Design it.", title="Design")["request"]
    opened = ops.route(path_of(tree), request, flow="wk-design")
    approved = ops.approve(path_of(tree), opened["pending_id"], go_ahead="system, system")
    assert approved["state"]["written"] is True and [t["state"] for t in approved["tasks"]] == ["ready"]
    ctx = ops_core.context(path_of(tree))
    other = ctx["store"].request_from_board(ctx["conn"], title="t", text="x", remote_id="r", remote_version="v", by="board")
    with pytest.raises(ops.OpsError, match="go ahead is said on the tasks of a plan"):
        ops.approve(path_of(tree), other["pending_id"], go_ahead=["x"])


def test_go_ahead_on_a_key_that_waits_for_nothing_is_refused_naming_the_key_and_the_plan_stays_open(tree):
    request = ops.request(path_of(tree), "Brand it.", title="Brand")["request"]
    opened = ops.route(path_of(tree), request, flow="wk-brand")
    with pytest.raises(ops.OpsError, match="voice.*waits for no task to derive"):
        ops.approve(path_of(tree), opened["pending_id"], go_ahead=["voice"])
    assert ops.pending(path_of(tree), opened["pending_id"])["status"] == "open"
    assert "Go ahead" not in (tree["project"] / "docs" / "workbench" / "state.md").read_text(encoding="utf-8")
    assert [t for t in ops.status(path_of(tree))["requests"] if t["id"] == request][0]["tasks"] == []


def test_the_override_after_holds_every_task_of_the_request_with_the_reason_and_ends_with_the_request(tree):
    first = requested(tree, "wk-brand")
    second = requested(tree, "wk-market", after=first["request"])
    [posts] = second["tasks"]
    reasons = [w["reason"] for w in row(tree, posts["id"])["waiting_for"]]
    assert f"after request #{first['request']}" in reasons
    shown = [r for r in ops.status(path_of(tree))["requests"] if r["id"] == second["request"]][0]
    assert shown["after"] == first["request"]
    found = ops.task(path_of(tree), second["request"])["task"]
    assert found["after"] == first["request"] and "after_request" not in found and found["waiting_for"] == []
    waits = ops.task(path_of(tree), posts["id"])["task"]["waiting_for"]
    assert {"task_id": None, "request_id": first["request"], "reason": f"after request #{first['request']}"} in waits
    for t in first["tasks"]:
        finish(tree, t["id"])
    assert row(tree, posts["id"])["state"] in ("ready", "planned")
    assert all(w["reason"] != f"after request #{first['request']}" for w in row(tree, posts["id"])["waiting_for"])


def test_after_on_a_request_that_waits_for_its_route_reaches_its_tasks_when_the_plan_is_approved(tree):
    first = requested(tree, "wk-brand")
    request = ops.request(path_of(tree), "Design it.", title="Design", after=first["request"])
    assert request["state"] == "requested"
    opened = ops.route(path_of(tree), request["request"], flow="wk-design")
    shown = ops.pending(path_of(tree), opened["pending_id"])["payload"]["waits"]
    assert {"task_key": "system", "task_id": None, "reason": f"after request #{first['request']}"} in shown
    system = ops.approve(path_of(tree), opened["pending_id"])["tasks"][0]
    assert system["state"] == "planned"


def test_after_names_a_request_of_the_project_and_not_itself(tree):
    first = requested(tree, "wk-brand")
    task = by_key(first)["identity"]["id"]
    with pytest.raises(ops.OpsError):
        ops.request(path_of(tree), "x", flow="wk-design", after=task)  # a task is not a request
    with pytest.raises(ops.OpsError):
        ops.request(path_of(tree), "x", after=9999)
    assert len(ops.status(path_of(tree))["requests"]) == 1  # neither refused call left a request behind


def test_two_requests_whose_skills_read_each_others_outputs_are_never_made_to_wait_in_a_circle(tree, monkeypatch):
    real = plan.skill_facts
    circular = lambda root: dict(real(root), **{  # noqa: E731  (the brand skill is made to read the design skill's output)
        "wk-brand": dict(real(root)["wk-brand"], inputs=["docs/design/system.md"], required=set())})
    monkeypatch.setattr(plan, "skill_facts", circular)
    brand = requested(tree, "wk-brand")
    design = requested(tree, "wk-design")
    identity, system = by_key(brand)["identity"]["id"], design["tasks"][0]["id"]
    kinds = (row(tree, identity)["waiting_for"], row(tree, system)["waiting_for"])
    assert [len(w) for w in kinds] == [1, 0]  # the older task waits; the other would close the circle
    assert [w["task_id"] for w in kinds[0]] == [system]


def test_status_and_task_carry_the_waits_in_the_shape_the_page_reads(tree):
    brand = requested(tree, "wk-brand")
    system = requested(tree, "wk-design")["tasks"][0]["id"]
    for t in ops.status(path_of(tree))["requests"][0]["tasks"]:
        assert set(t) >= {"id", "key", "title", "agent", "skill", "state", "note", "waiting_for"}
    assert set(ops.status(path_of(tree))["requests"][0]) >= {"after"}
    [wait] = ops.task(path_of(tree), system)["task"]["waiting_for"]
    assert set(wait) == {"task_id", "request_id", "reason"} and wait["request_id"] == brand["request"]
    assert ops.task(path_of(tree), brand["request"])["task"]["after"] is None


def test_request_after_is_a_flag_of_the_terminal_and_approve_takes_go_ahead_repeated(tree, capsys):
    cli = st.load("cli")
    first = requested(tree, "wk-brand")
    out = cli.run(["request", "--project", path_of(tree), "--text", "Market it.", "--flow", "wk-market",
                   "--after", str(first["request"])])
    shown = [r for r in ops.status(path_of(tree))["requests"] if r["id"] == out["request"]][0]
    assert shown["after"] == first["request"]
    request = ops.request(path_of(tree), "Design it.", title="Design")["request"]
    opened = ops.route(path_of(tree), request, flow="wk-design")
    approved = cli.run(["approve", "--project", path_of(tree), "--id", str(opened["pending_id"]), "--go-ahead", "system",
                        "--go-ahead", "system"])
    assert approved["tasks"][0]["state"] == "ready"


def test_chat_new_takes_after_before_the_text():
    operations = st.load("operations")
    assert operations.split_new("--after 12 Design the app") == (12, "Design the app")
    assert operations.split_new("Design the app") == (None, "Design the app")
    assert operations.split_new("--after twelve Design") == (None, "--after twelve Design")
    assert operations.parse_chat("/new --after 3 Design it") == ("new", "--after 3 Design it")
    assert operations.parse_chat("/new --after 3") is None  # no text
    assert operations.chat_line("new", text="Design it", after=3) == "/new --after 3 Design it"
    assert operations.chat_line("new", text="Design it") == "/new Design it"


# --- the task board -------------------------------------------------------------------------------------------------


@pytest.fixture
def mirrored(tree, tmp_path, monkeypatch):
    folder = tree["tree"] / "providers" / "issue-tracker"
    folder.mkdir(parents=True)
    shutil.copyfile(st.REPO / "providers" / "issue-tracker" / "local.py", folder / "local.py")
    place = tmp_path / "board"
    place.mkdir()
    path = tree["project"] / "docs" / "workbench" / "runtime.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["task_board"] = {"provider": "local", "dir": str(place)}
    path.write_text(json.dumps(raw), encoding="utf-8")
    ops.accept_config(path_of(tree), ops.project_config.load(path_of(tree))["sha256"])
    return {**tree, "board": place}


def test_the_mirrored_item_of_a_waiting_task_says_what_it_waits_for_in_its_note(mirrored):
    brand = requested(mirrored, "wk-brand")
    system = requested(mirrored, "wk-design")["tasks"][0]["id"]
    identity = by_key(brand)["identity"]["id"]
    ops.sync(path_of(mirrored))
    ctx = ops_core.context(path_of(mirrored))
    remote = ctx["store"].task_get(ctx["conn"], system)["remote_id"]
    text = (mirrored["board"] / f"{remote}.md").read_text(encoding="utf-8")
    assert f"- note: waiting for #{identity}" in text and "State: planned" in text
    finish(mirrored, identity)
    ops.sync(path_of(mirrored))
    freed = (mirrored["board"] / f"{remote}.md").read_text(encoding="utf-8")
    assert "waiting for" not in freed and "State: ready" in freed


def test_an_item_a_person_wrote_with_after_n_becomes_a_request_that_runs_after_request_n(mirrored):
    first = requested(mirrored, "wk-brand")
    (mirrored["board"] / "design-it.md").write_text(f"# Design it\n\nDo the design.\nafter #{first['request']}\n", encoding="utf-8")
    out = ops.sync(path_of(mirrored))["board"]
    [made] = out["created"]
    assert ops.task(path_of(mirrored), made["request"])["task"]["after"] == first["request"]
    ops.approve(path_of(mirrored), made["pending_id"])
    planned = ops.route(path_of(mirrored), made["request"], flow="wk-design")
    shown = ops.pending(path_of(mirrored), planned["pending_id"])["payload"]["waits"]
    assert {"task_key": "system", "task_id": None, "reason": f"after request #{first['request']}"} in shown


def test_an_after_that_names_a_task_means_its_request_and_one_that_names_nothing_is_said(mirrored):
    first = requested(mirrored, "wk-brand")
    task = by_key(first)["identity"]["id"]
    (mirrored["board"] / "a.md").write_text(f"# A\n\nAfter task #{task}.\n", encoding="utf-8")
    (mirrored["board"] / "b.md").write_text("# B\n\nAfter #9999 please.\n", encoding="utf-8")
    out = ops.sync(path_of(mirrored))["board"]
    afters = {c["item"]: ops.task(path_of(mirrored), c["request"])["task"]["after"] for c in out["created"]}
    assert afters == {"a": first["request"], "b": None}
    assert any(r.get("item") == "b" and "names no request or task" in r["reason"] for r in out["refused"])


def test_after_is_added_later_to_the_text_of_a_request_that_is_not_planned_yet(mirrored):
    first = requested(mirrored, "wk-brand")
    (mirrored["board"] / "later.md").write_text("# Later\n\nDo it.\n", encoding="utf-8")
    [made] = ops.sync(path_of(mirrored))["board"]["created"]
    ops.sync(path_of(mirrored))  # the request has its own item now
    ctx = ops_core.context(path_of(mirrored))
    remote = ctx["store"].task_get(ctx["conn"], made["request"])["remote_id"]
    item = mirrored["board"] / f"{remote}.md"
    text = item.read_text(encoding="utf-8")
    item.write_text(text.replace("Do it.", f"Do it.\nAfter request #{first['request']}."), encoding="utf-8")
    ops.sync(path_of(mirrored))
    assert ops.task(path_of(mirrored), made["request"])["task"]["after"] == first["request"]
    item.write_text(item.read_text(encoding="utf-8").replace(f"After request #{first['request']}.", ""), encoding="utf-8")
    ops.sync(path_of(mirrored))  # the words that said it are gone: so is the override
    assert ops.task(path_of(mirrored), made["request"])["task"]["after"] is None


def test_the_words_of_an_override_in_an_items_text():
    assert board.after_of("Design", "after #12") == 12
    assert board.after_of("Do it\nAfter Request #7.\nplease") == 7 and board.after_of("After #9 the rest") == 9
    # Inside prose it is prose: only the start of a text, or a line of its own, is an instruction.
    for prose in ("Do it after #12 please", "thereafter #3", "x\nafter #4 please", "after 12", "see after #3, then"):
        assert board.after_of(prose) is None, prose
    assert board.after_of(None, "") is None and board.after_of("first", "after #4 and after #5") == 4


def test_the_note_names_at_most_two_awaited_tasks_and_counts_the_rest():
    waits = [{"awaited_id": n, "kind": "input"} for n in (10, 12, 13, 14)] + [{"awaited_id": 3, "kind": "after"}]
    assert board._waiting_note(waits[:1]) == "waiting for #10" and board._waiting_note(waits[:2]) == "waiting for #10, #12"
    assert board._waiting_note(waits) == "waiting for #10, #12 (+3)"
    assert board._waiting_note([waits[4]]) == "waiting for request #3"
    shown = board.item_payload({"id": 1, "state": "planned", "note": "the task's own note", "depends_on": []}, None,
                               waits=waits)["shown"]["note"]
    assert shown == "waiting for #10, #12 (+3); the task's own note"


# --- go ahead on a task already created ---------------------------------------------------------------------------------


def test_go_ahead_on_a_waiting_task_ends_its_derived_wait_and_writes_the_decision(tree):
    brand = requested(tree, "wk-brand")
    identity = by_key(brand)["identity"]["id"]
    system = requested(tree, "wk-design")["tasks"][0]["id"]
    out = ops.go_ahead(path_of(tree), system)
    assert out["state"] == "ready" and out["waiting_for"] == [] and out["decision"] == {"written": True}
    assert out["dropped"] == [f"docs/brand/identity.md, written by task #{identity}"]
    text = (tree["project"] / "docs" / "workbench" / "state.md").read_text(encoding="utf-8")
    assert (f"Go ahead on wk-design (task {system}) without waiting for: docs/brand/identity.md, written by task "
            f"#{identity} (user)") in text
    requested(tree, "wk-brand")  # a later derivation does not bring the wait back
    ops.poll(path_of(tree))
    assert row(tree, system)["waiting_for"] == [] and row(tree, system)["state"] == "ready"


def test_go_ahead_never_drops_an_after_override_and_refuses_a_task_that_is_not_waiting(tree):
    first = requested(tree, "wk-brand")
    posts = by_key(requested(tree, "wk-brand", after=first["request"]))["identity"]["id"]  # no input another request writes
    with pytest.raises(ops.OpsError, match="after"):
        ops.go_ahead(path_of(tree), posts)  # it waits only for the request it was told to follow
    identity = by_key(first)["identity"]["id"]
    with pytest.raises(ops.OpsError):
        ops.go_ahead(path_of(tree), identity)  # ready, waits for nothing
    with pytest.raises(ops.OpsError):
        ops.go_ahead(path_of(tree), first["request"])
    assert any(w["reason"] == f"after request #{first['request']}" for w in row(tree, posts)["waiting_for"])


def test_go_ahead_keeps_the_override_of_a_task_that_both_waits_for_a_writer_and_follows_a_request(tree):
    first = requested(tree, "wk-brand")
    design = requested(tree, "wk-design")
    third = requested(tree, "wk-design", after=design["request"])["tasks"][0]["id"]
    waits = row(tree, third)["waiting_for"]
    assert {w["reason"].split(",")[0].split(" #")[0] for w in waits} >= {"after request"}
    out = ops.go_ahead(path_of(tree), third)
    assert [w["reason"] for w in out["waiting_for"]] == [f"after request #{design['request']}"] and out["state"] == "planned"
    assert first["request"] != design["request"]


def test_go_ahead_is_a_verb_of_the_terminal_with_the_task_flag(tree):
    cli = st.load("cli")
    requested(tree, "wk-brand")
    system = requested(tree, "wk-design")["tasks"][0]["id"]
    assert cli.run(["go-ahead", "--project", path_of(tree), "--task", str(system)])["state"] == "ready"


def test_go_ahead_with_drop_after_ends_the_override_for_that_task_and_the_decision_is_recorded(tree):
    first = requested(tree, "wk-brand")
    second = requested(tree, "wk-brand", after=first["request"])
    one, other = by_key(second)["identity"]["id"], by_key(second)["voice"]["id"]
    out = ops.go_ahead(path_of(tree), one, drop_after=True)
    assert out["state"] == "ready" and out["waiting_for"] == [] and out["dropped"] == [f"after request #{first['request']}"]
    assert [w["reason"] for w in row(tree, other)["waiting_for"]] == [f"after request #{first['request']}"]  # the other stays
    text = (tree["project"] / "docs" / "workbench" / "state.md").read_text(encoding="utf-8")
    assert f"Go ahead on wk-brand (task {one}) without waiting for: after request #{first['request']} (user)" in text
    ops.poll(path_of(tree))
    assert row(tree, one)["state"] == "ready"
    with pytest.raises(ops.OpsError, match="no request"):
        ops.go_ahead(path_of(tree), one, drop_after=True)


def test_a_retried_task_begins_with_its_waits_and_run_next_says_who_waits_for_what(tree):
    design = requested(tree, "wk-design")
    system = design["tasks"][0]["id"]
    posts = requested(tree, "wk-market")["tasks"][0]["id"]
    ctx = ops_core.context(path_of(tree))
    s = ctx["store"]
    s.task_claim(ctx["conn"], system)
    run = s.task_run_start(ctx["conn"], system, skill="wk-design", model="m", adapter="h")
    s.task_run_finish(ctx["conn"], run["run_id"], status="failed", failure="timeout", task_state="failed")
    # Nothing is ready, and the tasks that wait are named with why.
    said = ops.run_next(path_of(tree))
    assert said["ran"] is None and said["reason"].startswith("no task is ready; waiting: ")
    assert f"task {posts} for docs/design/system.md, written by task #{system}" in said["reason"]
    # A task that fails and is retried while another request's writer is open begins planned, with the wait.
    brand = requested(tree, "wk-brand")
    assert row(tree, system)["state"] == "failed"
    out = ops.retry(path_of(tree), system)
    assert out["state"] == "planned" and [w["task_id"] for w in row(tree, system)["waiting_for"]] == [by_key(brand)["identity"]["id"]]
    claimed = ops._claim_and_run(ops_core.context(path_of(tree)), None, system)
    assert claimed["ran"] is None and claimed["reason"].startswith(f"task {system} is waiting: docs/brand/identity.md")
