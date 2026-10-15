"""Tests of the choice of the model (package P3 of the delegation platform plan): a model named on a request, `auto`, the project's
default, the agent's fixed model and the person's consent for it (decisions D8, D22, D34, D38). On the stand-in tree of
standin_tree.py: "m" is reliable for every skill, "fm" has no evidence. Offline; invented names and prices.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_model_choice.py
"""
from __future__ import annotations

import json

import pytest

import standin_tree as st

autonomy = st.load("autonomy")
lab = st.load("lab")
ops = st.load("ops")
ops_core = st.load("ops_core")
ops_config = st.load("ops_config")
ops_models = st.load("ops_models")
operations = st.load("operations")
plan = st.load("plan")
project_config = st.load("project_config")
dispatcher = st.load("dispatcher")

PACKS = {"biz": ["demo-asks", "demo-writes"], "default": ["demo-asks", "demo-writes"]}
BUSINESS = {"pack": "biz", "mode": "autonomous", "max_runs_per_day": 20, "max_usd_per_day": 5.0, "max_parallel": 1}


@pytest.fixture
def tree(tmp_path, monkeypatch):
    built = st.build(tmp_path, monkeypatch, lab)
    monkeypatch.setattr(ops_core, "ROOT", str(built["tree"]))
    monkeypatch.setattr(plan, "resolve_pack", lambda pack, root: list(PACKS[pack]))
    (built["tree"] / "flows" / "single.json").write_text(json.dumps({"flow": "single", "title": "Single", "tasks": [
        {"key": "profile", "skill": "demo-writes", "title": "Profile", "text": "write the profile."}]}), encoding="utf-8")
    business = built["project"] / "docs" / "business"
    business.mkdir(parents=True)
    (business / "market.md").write_text("# Market analysis\n\n- Owner: demo-asks\n- Status: draft\n", encoding="utf-8")  # demo-writes' input
    configure(built, {"business": dict(BUSINESS)})
    return built


def config_path(tree):
    return tree["project"] / "docs" / "workbench" / "runtime.json"


def configure(tree, agents, **extra) -> None:
    raw = json.loads(config_path(tree).read_text(encoding="utf-8"))
    raw["area_agents"] = agents
    raw.update(extra)
    config_path(tree).write_text(json.dumps(raw), encoding="utf-8")
    project = str(tree["project"])
    ops.accept_config(project, project_config.load(project)["sha256"])


def agent_of(tree) -> dict:
    return json.loads(config_path(tree).read_text(encoding="utf-8"))["area_agents"]["business"]


def planned(tree, model=None) -> int:
    path = str(tree["project"])
    request = ops.request(path, "Invented request.", title="Invented", model=model)["request"]
    pending_id = ops.route(path, request, "single")["pending_id"]
    ops.approve(path, pending_id, ops.pending(path, pending_id)["payload"]["plan_sha256"])
    return request


def runs(tree) -> list:
    ctx = ops_core.context(str(tree["project"]))
    return [r for t in ctx["store"].tasks_list(ctx["conn"]) for r in ctx["store"].task_runs_list(ctx["conn"], t["id"])]


def run_one(tree, **more) -> dict:
    """Run the next task by hand, and let the person release its review, so that the agent's slot is free for the next."""
    path = str(tree["project"])
    out = ops.run_next(path, **more)
    assert out["ran"], out
    ops.release(path, out["pending_id"])
    return out


def open_reviews(tree) -> list:
    return [p for p in ops.pending(str(tree["project"]))["pending"] if p["kind"] == "review"]


# --- a model named on a request ---------------------------------------------------------------------------------------------


def test_a_request_carries_the_model_the_person_named_and_an_unknown_model_is_refused(tree):
    path = str(tree["project"])
    request = ops.request(path, "Invented request.", title="Invented", model="fm")["request"]
    ctx = ops_core.context(path)
    assert ctx["store"].task_get(ctx["conn"], request)["model"] == "fm"
    assert ctx["store"].task_get(ctx["conn"], ops.request(path, "Another.", title="Another")["request"])["model"] is None
    with pytest.raises(ops.OpsError) as refused:
        ops.request(path, "Invented request.", model="not-a-model")
    assert refused.value.code == 2 and "is not a model of evals/eval-gate.json" in str(refused.value)
    assert ops.request(path, "Auto.", title="Auto", model="auto")["request"]


def test_a_model_named_on_one_request_without_evidence_runs_supervised_and_is_marked_unproven(tree):
    path = str(tree["project"])
    planned(tree, model="fm")
    out = ops.run_next(path)
    routing = out["routing"]
    assert (routing["model"], routing["mode"], routing["named_by"], routing["proven"], routing["autonomy"]) == ("fm", "named", "request", False, "supervised")
    assert any("needs a test" in reason and "unproven" in reason for reason in routing["reasons"])
    [run] = runs(tree)
    assert (run["model"], run["autonomy"]) == ("fm", "supervised")
    # The agent is autonomous, and the review is still held: nothing releases an unproven pair that no agent was fixed to.
    result = ops.dispatch(path)
    assert result["released"] == [] and len(open_reviews(tree)) == 1


def test_a_proven_model_named_on_a_request_is_released_by_the_mode_as_before(tree):
    path = str(tree["project"])
    planned(tree, model="m")
    assert ops.run_next(path)["routing"]["autonomy"] == "proven"
    assert [r["autonomy"] for r in runs(tree)] == ["proven"]
    assert [r["by"] for r in ops.dispatch(path)["released"]] == ["mode:autonomous"]


def test_the_model_of_a_run_by_hand_wins_and_the_project_default_comes_after_the_agent(tree):
    path = str(tree["project"])
    planned(tree, model="m")
    assert run_one(tree, model="fm")["routing"]["model"] == "fm"  # the person's own choice for this run
    configure(tree, {"business": dict(BUSINESS, mode="supervised")}, default_model="fm")
    planned(tree)
    out = run_one(tree)
    assert (out["routing"]["model"], out["routing"]["named_by"]) == ("fm", "default")  # no request, no agent model: the project default
    assert out["routing"]["autonomy"] == "supervised"
    configure(tree, {"business": dict(BUSINESS, mode="supervised", model="m")}, default_model="fm")
    planned(tree)
    out = run_one(tree)
    assert (out["routing"]["model"], out["routing"]["named_by"]) == ("m", "agent")  # the agent's fixed model wins over the default


def test_without_a_model_the_choice_is_auto_the_cheapest_reliable_pair_and_a_default_that_names_auto_is_the_same(tree):
    path = str(tree["project"])
    planned(tree)
    out = run_one(tree)
    assert (out["routing"]["mode"], out["routing"]["model"], out["routing"]["proven"]) == ("auto", "m", True)
    configure(tree, {"business": dict(BUSINESS)}, default_model="auto")
    planned(tree)
    assert run_one(tree)["routing"]["mode"] == "auto"


# --- auto and the evidence's source ------------------------------------------------------------------------------------------


def test_a_pair_reliable_only_through_community_evidence_is_chosen_by_auto_and_its_output_is_held_for_review(tree, monkeypatch):
    st.cheaper_second_model(monkeypatch, lab)
    current = lab.standing

    def community(skill):
        found = current(skill)
        found["models"]["fm"] = dict(found["models"]["fm"], source="community")
        return found
    monkeypatch.setattr(lab, "standing", community)
    path = str(tree["project"])
    planned(tree)
    out = ops.run_next(path)
    assert (out["routing"]["model"], out["routing"]["mode"], out["routing"]["source"]) == ("fm", "auto", "community")
    assert (out["routing"]["proven"], out["routing"]["autonomy"]) == (False, "supervised")
    assert ops.dispatch(path)["released"] == [] and len(open_reviews(tree)) == 1  # the agent is autonomous: still reviewed


def test_when_auto_has_no_candidate_the_default_model_runs_supervised_with_the_reason(tree, monkeypatch):
    monkeypatch.setattr(lab, "standing", lambda skill: {
        "skill": skill, "version": "0.1.0", "lab_models": ["m", "fm"], "adapters": {"m": "h", "fm": "h"},
        "models": {"m": {"band": "watch", "cause": "a cause", "score": 0.5, "mean": 0.6, "runs": 6, "web_measured": False,
                         "usage_mean": None, "source": "lab"}}, "local": {}, "web_cases": [], "evidence_images": [st.STANDIN_IMAGE]})
    path = str(tree["project"])
    configure(tree, {"business": dict(BUSINESS)}, default_model="auto")
    planned(tree)
    routing = ops.run_next(path)["routing"]
    assert (routing["model"], routing["mode"], routing["autonomy"]) == ("m", "fallback", "supervised")  # no default id: the first lab model
    assert any("no model qualifies for auto" in reason for reason in routing["reasons"])


# --- the agent's fixed model and the person's consent (D38) -------------------------------------------------------------------


def test_fixing_a_model_on_an_autonomous_agent_asks_for_the_consent_and_writes_nothing_without_it(tree):
    path = str(tree["project"])
    before = config_path(tree).read_text(encoding="utf-8")
    with pytest.raises(ops.OpsError) as refused:
        ops.set_model(path, "business", "fm", channel="terminal")
    assert refused.value.code == 2 and autonomy.CONSENT_WARNING in str(refused.value)
    assert "set-model" in str(refused.value) and "--consent" in str(refused.value) and "--accept" in str(refused.value)  # the one command
    assert config_path(tree).read_text(encoding="utf-8") == before


def test_the_consent_is_a_flag_of_its_own_given_in_the_terminal_and_accept_alone_gives_none(tree):
    path = str(tree["project"])
    for channel in ("page", "chat", "mcp", "messaging", None):
        with pytest.raises(ops.OpsError) as refused:
            ops.set_model(path, "business", "fm", consent=True, channel=channel)
        assert refused.value.code == 2 and "in the terminal" in str(refused.value), channel
        with pytest.raises(ops.OpsError):
            ops.set_mode(path, "business", "autonomous-with-policy", consent=True, channel=channel)
        with pytest.raises(ops.OpsError):
            ops.set_model(path, "business", "fm", accept=True, channel=channel)
    assert "model" not in agent_of(tree)
    # accept (the hash) is not the consent: with it alone the call is refused with the warning, and nothing is written
    before = config_path(tree).read_text(encoding="utf-8")
    with pytest.raises(ops.OpsError) as refused:
        ops.set_model(path, "business", "fm", accept=True, channel="terminal")
    assert refused.value.code == 2 and autonomy.CONSENT_WARNING in str(refused.value) and "--consent" in str(refused.value)
    assert config_path(tree).read_text(encoding="utf-8") == before
    # consent alone stores the consent and the model and leaves the hash to accept; the answer carries the warning
    first = ops.set_model(path, "business", "fm", consent=True, channel="terminal")
    assert (first["accepted"], first["consent"], first["warning"]) == (False, {"model": "fm", "mode": "autonomous"}, autonomy.CONSENT_WARNING)
    ops.accept_config(path, first["config_sha256"])
    # both flags in one step: accepted by the person, warning in the answer
    ops.set_model(path, "business", "m", consent=True, accept=True, channel="terminal")
    done = ops.set_model(path, "business", "fm", consent=True, accept=True, channel="terminal")
    assert (done["accepted"], done["by"], done["consent"]) == (True, "person", {"model": "fm", "mode": "autonomous"})
    assert done["warning"] == autonomy.CONSENT_WARNING
    assert agent_of(tree)["model"] == "fm" and agent_of(tree)["consent"] == {"model": "fm", "mode": "autonomous"}


def test_the_terminal_prints_the_warning_the_consent_answered(tree, capsys):
    cli = st.load("cli")
    path = str(tree["project"])
    code = cli.main(["set-model", "--project", path, "--agent", "business", "--model", "fm", "--consent", "--accept"])
    assert code == 0
    captured = capsys.readouterr()
    assert autonomy.CONSENT_WARNING in captured.err and "consent recorded for business" in captured.err
    assert json.loads(captured.out)["warning"] == autonomy.CONSENT_WARNING
    assert cli.main(["set-model", "--project", path, "--agent", "business", "--model", "auto"]) == 0  # no consent, no warning
    assert "consent recorded" not in capsys.readouterr().err


def test_messaging_can_give_no_consent_because_it_has_no_operation_for_it(tree):
    for name in ("set-model", "set-mode"):
        row = operations.by_name(name)
        assert set(row["channels"]) == {"terminal", "page"}, name
        assert "messaging" not in row["channels"] and "mcp" not in row["channels"] and "chat" not in row["channels"]
        assert not operations.permitted(name, "messaging", {"messaging": ["read", "talk", "answer", "set-mode"]})
    # the page's consent is the page's alone: not the terminal (it has --consent), not the conversation, not the MCP mode, not messaging
    assert operations.by_name("give-consent")["channels"] == ("page",)
    for channel in ("messaging", "mcp", "chat", "terminal"):
        assert not operations.permitted("give-consent", channel, {channel: ["read", "talk", "answer", "set-mode"]}), channel
    assert operations.GROUPS["set-mode"]["operations"] == ("set-mode", "set-model", "give-consent")
    assert operations.refusal("give-consent", "messaging", {"messaging": ["read", "set-mode"]})


def test_with_the_consent_the_agents_reviews_on_an_unproven_model_are_released_and_the_runs_are_recorded_as_consent(tree):
    path = str(tree["project"])
    ops.set_model(path, "business", "fm", consent=True, accept=True, channel="terminal")
    planned(tree)
    result = ops.dispatch(path)
    assert len(result["ran"]) == 1
    [run] = runs(tree)
    assert (run["model"], run["autonomy"]) == ("fm", "consent")  # never "proven"
    assert [r["by"] for r in result["released"]] == ["mode:autonomous"] and open_reviews(tree) == []


def test_the_same_model_on_an_agent_below_autonomous_is_held_for_review(tree):
    path = str(tree["project"])
    configure(tree, {"business": dict(BUSINESS, mode="milestones")})
    done = ops.set_model(path, "business", "fm", channel="terminal")  # no consent is needed below the autonomous modes
    assert done["consent"] is None and "consent" not in agent_of(tree) and done["accepted"] is False
    ops.accept_config(path, done["config_sha256"])
    planned(tree)
    result = ops.dispatch(path)
    assert [r["autonomy"] for r in runs(tree)] == ["supervised"]
    assert result["released"] == [] and len(open_reviews(tree)) == 1


def test_changing_the_model_or_the_mode_asks_again_and_a_consent_that_no_longer_fits_is_not_in_force(tree):
    path = str(tree["project"])
    ops.set_model(path, "business", "fm", consent=True, accept=True, channel="terminal")
    # another model: the consent names the first one
    with pytest.raises(ops.OpsError) as refused:
        ops.set_model(path, "business", "m", channel="terminal")
    assert autonomy.CONSENT_WARNING in str(refused.value)
    assert agent_of(tree)["model"] == "fm"
    # another autonomous mode: the consent names the mode too
    with pytest.raises(ops.OpsError) as refused:
        ops.set_mode(path, "business", "autonomous-with-policy", channel="terminal")
    assert autonomy.CONSENT_WARNING in str(refused.value) and agent_of(tree)["mode"] == "autonomous"
    # the same model and the same mode again: nothing to ask, nothing to write
    again = ops.set_model(path, "business", "fm", channel="terminal")
    assert again["unchanged"] is True and again["accepted"] is True
    ops.set_mode(path, "business", "autonomous-with-policy", consent=True, accept=True, channel="terminal")
    assert agent_of(tree)["consent"] == {"model": "fm", "mode": "autonomous-with-policy"}
    ops.set_model(path, "business", "m", consent=True, accept=True, channel="terminal")
    assert agent_of(tree)["consent"] == {"model": "m", "mode": "autonomous-with-policy"}
    # a hand-edited file whose consent names another model is not in force: the run is supervised, not by consent
    raw = json.loads(config_path(tree).read_text(encoding="utf-8"))
    raw["area_agents"]["business"].update(model="fm", consent={"model": "m", "mode": "autonomous-with-policy"})
    config_path(tree).write_text(json.dumps(raw), encoding="utf-8")
    ops.accept_config(path, project_config.load(path)["sha256"])
    assert autonomy.consent_valid(agent_of(tree), "fm") is False
    planned(tree)
    ops.dispatch(path)
    assert [r["autonomy"] for r in runs(tree)] == ["supervised"]


def test_going_back_to_auto_to_the_default_or_below_autonomous_drops_the_consent_and_code_accepts_it(tree):
    path = str(tree["project"])
    ops.set_model(path, "business", "fm", consent=True, accept=True, channel="terminal")
    done = ops.set_model(path, "business", "auto", channel="page")  # auto fixes no model: no consent, nothing widens
    assert (done["accepted"], done["by"], done["consent"]) == (True, "code:narrowing", None)
    assert agent_of(tree)["model"] == "auto" and "consent" not in agent_of(tree)
    ops.set_model(path, "business", "fm", consent=True, accept=True, channel="terminal")
    done = ops.set_mode(path, "business", "milestones", channel="page")  # a move down: accepted by code, the consent leaves
    assert (done["accepted"], done["by"]) == (True, "code:narrowing") and "consent" not in agent_of(tree)
    assert agent_of(tree)["model"] == "fm"
    # raising it again with the model fixed asks again
    with pytest.raises(ops.OpsError) as refused:
        ops.set_mode(path, "business", "autonomous", channel="terminal")
    assert autonomy.CONSENT_WARNING in str(refused.value)
    ops.set_mode(path, "business", "autonomous", consent=True, accept=True, channel="terminal")
    assert agent_of(tree)["consent"] == {"model": "fm", "mode": "autonomous"}
    done = ops.set_model(path, "business", "default", channel="page")
    assert done["accepted"] is True and "model" not in agent_of(tree) and "consent" not in agent_of(tree)


def test_a_model_the_gate_file_does_not_list_cannot_be_fixed(tree):
    with pytest.raises(ops.OpsError) as refused:
        ops.set_model(str(tree["project"]), "business", "not-a-model", channel="terminal")
    assert refused.value.code == 2
    with pytest.raises(ops.OpsError):
        ops.set_model(str(tree["project"]), "nobody", "fm", channel="terminal")


def test_the_page_may_fix_a_model_only_when_its_policy_lists_the_group_set_mode(tree):
    path = str(tree["project"])
    configure(tree, {"business": dict(BUSINESS, mode="milestones")}, channels={"page": ["read"]})
    with pytest.raises(ops.OpsError) as refused:
        ops.set_model(path, "business", "fm", channel="page")
    assert refused.value.code == 1 and "set-model is not enabled for this channel" in str(refused.value)
    assert ops.set_model(path, "business", "auto", channel="page")["accepted"] is True  # going to auto widens nothing


def test_the_agents_read_says_the_model_the_consent_and_the_command_that_gives_it(tree):
    path = str(tree["project"])
    ops.set_model(path, "business", "fm", consent=True, accept=True, channel="terminal")
    found = ops.agents(path)
    [agent] = found["agents"]
    assert (agent["model"], agent["consent"], agent["consent_in_force"], agent["consent_needed"]) == (
        "fm", {"model": "fm", "mode": "autonomous"}, True, True)
    assert found["consent_warning"] == autonomy.CONSENT_WARNING and found["models"] == ["m", "fm"]
    commands = {c["model"]: c["command"] for c in agent["model_commands"]}
    assert set(commands) == {"m", "fm", "auto", "default"}
    assert "--consent" in commands["m"] and "--consent" in commands["fm"]  # a fixed model on this agent needs the consent
    assert "--accept" in commands["m"] and "--consent" not in commands["auto"] and "--accept" not in commands["default"]
    assert found["config_sha256"] == project_config.load(path)["sha256"]  # what the page sends back with the consent
    assert {c["model"]: c["consent"] for c in agent["model_commands"]} == {"m": True, "fm": True, "auto": False, "default": False}


# --- the rules in autonomy.py ------------------------------------------------------------------------------------------------


def test_review_action_releases_an_unproven_review_only_for_an_agent_with_the_consent():
    facts = {"enabled": True, "checkpoints": "end", "standing": False}
    task = {"milestone": 0}
    review = {"kind": "review", "payload": {"ending": "done"}}
    assert autonomy.review_action(task, review, facts, False, False) == "hold"
    assert autonomy.review_action(task, review, facts, False, False, True) == "release"
    assert autonomy.review_action(task, review, facts, True, False) == "release"
    assert autonomy.review_action(task, review, facts, False, True, True) == "hold"  # a mandatory milestone is held in every mode
    assert autonomy.review_action(task, review, {**facts, "checkpoints": "every-phase"}, False, False, True) == "hold"
    assert autonomy.review_action(task, {"kind": "question"}, facts, True, False, True) == "hold"


def test_the_consent_is_valid_only_for_the_agents_fixed_model_in_the_mode_it_names():
    entry = {"mode": "autonomous", "model": "fm", "consent": {"model": "fm", "mode": "autonomous"}}
    assert autonomy.consent_valid(entry, "fm") and not autonomy.consent_valid(entry, "m")
    assert not autonomy.consent_valid({**entry, "mode": "autonomous-with-policy"}, "fm")
    assert not autonomy.consent_valid({**entry, "mode": "milestones"}, "fm")
    assert not autonomy.consent_valid({**entry, "model": "auto"}, "auto")  # auto fixes no model
    assert not autonomy.consent_valid({"mode": "autonomous", "model": "fm"}, "fm")  # no consent stored
    assert autonomy.consent_needed({"mode": "autonomous", "model": "fm"}) and not autonomy.consent_needed({"mode": "autonomous", "model": "auto"})
    assert not autonomy.consent_needed({"mode": "supervised", "model": "fm"}) and not autonomy.consent_needed({"mode": "autonomous"})


def test_a_review_of_a_run_carries_what_the_dispatcher_reads(tree):
    path = str(tree["project"])
    ops.set_model(path, "business", "fm", consent=True, accept=True, channel="terminal")
    planned(tree)
    ops.run_next(path)
    ctx = ops_core.context(path)
    snapshot = ops._snapshot(ctx, ops_core._keys())
    [review] = snapshot["reviews"]
    assert (review["proven"], review["consent"]) == (False, True)
    # the person fixes another model afterwards: the old consent no longer covers the run on "fm"
    raw = json.loads(config_path(tree).read_text(encoding="utf-8"))
    raw["area_agents"]["business"]["model"] = "m"
    config_path(tree).write_text(json.dumps(raw), encoding="utf-8")
    ops.accept_config(path, project_config.load(path)["sha256"])
    ctx = ops_core.context(path)
    [review] = ops._snapshot(ctx, ops_core._keys())["reviews"]
    assert (review["proven"], review["consent"]) == (False, False)


def test_the_dispatcher_passes_consent_only_when_the_review_carries_it():
    seen = []

    def review_action(task, pending, facts, proven, mandatory, *rest):
        seen.append((proven, mandatory, rest))
        return "hold"

    base = {"pending": {"id": 1}, "task": {"id": 2}, "agent": "a", "proven": False, "mandatory": False}
    snapshot = {"reviews": [base, {**base, "consent": True}], "agents": {"a": {"facts": {"enabled": True, "checkpoints": "end", "standing": False}}},
                "ready": [], "running": [], "holding": [], "billing": {}, "waits": {}, "max_running": 1}
    dispatcher.decide(snapshot, review_action, lambda *a: (True, ""), lambda *a: (True, ""))
    assert seen == [(False, False, ()), (False, False, (True,))]
