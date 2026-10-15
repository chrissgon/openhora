"""Tests of the person's consent per agent (decision D38; review of package P3): the page gives it with the exact warning it
showed (give-consent), the terminal gives it with `--consent`, a flag of its own and distinct from `--accept`, and a move down
the order of the modes is never withheld. Offline; the stand-in tree of test_model_choice; every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_consent.py
"""
from __future__ import annotations

import hashlib
import json
import types

import pytest

import standin_tree as st
from test_model_choice import BUSINESS, agent_of, config_path, configure, tree  # noqa: F401  (autonomous business agent, model "fm" listed)

ops = st.load("ops")
ops_core = st.load("ops_core")
autonomy = st.load("autonomy")
operations = st.load("operations")
project_config = st.load("project_config")

WARNING_SHA = hashlib.sha256(autonomy.CONSENT_WARNING.encode("utf-8")).hexdigest()


def sha(tree) -> str:
    return project_config.load(str(tree["project"]))["sha256"]


def accepted(tree) -> str:
    ctx = ops_core.context(str(tree["project"]), check_config=False)
    return ctx["store"].cursor_get(ctx["conn"], project_config.ACCEPTED)


def consent(tree, **more):
    args = {"model": "fm", "mode": "autonomous", "config_sha256": sha(tree), "warning_sha256": WARNING_SHA, "channel": "page"}
    args.update(more)
    return ops.give_consent(str(tree["project"]), "business", args.pop("model"), args.pop("mode"), args.pop("config_sha256"),
                            args.pop("warning_sha256"), **args)


# --- the warning hash is the hash of the text the service holds -------------------------------------------------------------


def test_the_warning_hash_is_the_sha256_of_the_text_and_both_are_one_constant():
    assert autonomy.CONSENT_WARNING_SHA256 == WARNING_SHA
    assert "autonomy by consent" in autonomy.CONSENT_WARNING
    # P3b: the text says what is recorded, exactly: every run of a skill without reliable evidence on the model, a held run included
    assert autonomy.CONSENT_WARNING.startswith("Each run of a skill without reliable evidence on this model will be recorded as autonomy by consent")
    assert "a milestone later holds" in autonomy.CONSENT_WARNING


# --- the page's consent -----------------------------------------------------------------------------------------------------


def test_the_page_gives_the_consent_with_the_exact_warning_and_only_that_agents_model_and_consent_are_written(tree):
    path = str(tree["project"])
    before = json.loads(config_path(tree).read_text(encoding="utf-8"))
    out = consent(tree)
    assert out["accepted"] is True and out["by"] == "person:page" and out["consent"] == {"model": "fm", "mode": "autonomous"}
    assert out["warning"] == autonomy.CONSENT_WARNING and out["config_sha256"] == sha(tree) == accepted(tree)
    after = json.loads(config_path(tree).read_text(encoding="utf-8"))
    assert after["area_agents"]["business"] == dict(before["area_agents"]["business"], model="fm", consent={"model": "fm", "mode": "autonomous"})
    assert {k: v for k, v in after.items() if k != "area_agents"} == {k: v for k, v in before.items() if k != "area_agents"}, "nothing else changed"
    assert autonomy.consent_valid(agent_of(tree), "fm") is True
    assert ops.status(path)["config"]["sha256"] == sha(tree), "nothing refuses afterwards"
    again = consent(tree)
    assert again["unchanged"] is True and again["accepted"] is True


def test_a_wrong_warning_hash_writes_nothing(tree):
    file_before = config_path(tree).read_text(encoding="utf-8")
    for bad in ("0" * 64, hashlib.sha256(b"another text").hexdigest(), "", WARNING_SHA.upper()):
        with pytest.raises(ops.OpsError) as refused:
            consent(tree, warning_sha256=bad)
        assert refused.value.code == 2 and "warning" in str(refused.value)
    assert config_path(tree).read_text(encoding="utf-8") == file_before and accepted(tree) == sha(tree)


def test_a_model_or_a_mode_that_is_not_what_will_be_stored_writes_nothing(tree):
    file_before = config_path(tree).read_text(encoding="utf-8")
    cases = [dict(mode="autonomous-with-policy"),       # the agent is in autonomous mode: the consent names the mode it is in
             dict(mode="milestones"), dict(mode="supervised"),
             dict(model="auto"), dict(model="default"), dict(model=""), dict(model="not-a-model")]
    for case in cases:
        with pytest.raises(ops.OpsError) as refused:
            consent(tree, **case)
        assert refused.value.code == 2, case
    with pytest.raises(ops.OpsError) as refused:
        ops.give_consent(str(tree["project"]), "nobody", "fm", "autonomous", sha(tree), WARNING_SHA, channel="page")
    assert refused.value.code == 2
    assert config_path(tree).read_text(encoding="utf-8") == file_before


def test_an_agent_below_the_autonomous_modes_has_nothing_to_consent_to(tree):
    configure(tree, {"business": dict(BUSINESS, mode="milestones")})
    with pytest.raises(ops.OpsError) as refused:
        consent(tree, mode="milestones")
    assert refused.value.code == 2 and "model" not in agent_of(tree)


def test_a_stale_configuration_hash_or_an_unaccepted_configuration_is_refused(tree):
    file_before = config_path(tree).read_text(encoding="utf-8")
    with pytest.raises(ops.OpsError) as refused:
        consent(tree, config_sha256="f" * 64)  # the page read another file
    assert refused.value.code == 1 and "changed" in str(refused.value)
    assert config_path(tree).read_text(encoding="utf-8") == file_before
    raw = json.loads(file_before)
    raw["area_agents"]["business"]["max_runs_per_day"] = 99  # a change nobody accepted
    config_path(tree).write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ops.OpsError) as refused:
        consent(tree)
    assert refused.value.code == 3 and "accept-config" in str(refused.value), "nothing is accepted here but this consent"
    assert "consent" not in agent_of(tree) and accepted(tree) != sha(tree)


def test_only_the_page_gives_it_and_the_pages_policy_must_list_the_group_set_mode(tree):
    file_before = config_path(tree).read_text(encoding="utf-8")
    for channel in ("terminal", "chat", "mcp", "messaging", None):
        with pytest.raises(ops.OpsError) as refused:
            consent(tree, channel=channel)
        assert refused.value.code == 2 and "page" in str(refused.value), channel
    assert config_path(tree).read_text(encoding="utf-8") == file_before
    configure(tree, {"business": dict(BUSINESS)}, channels={"page": ["read", "answer"]})
    with pytest.raises(ops.OpsError) as refused:
        consent(tree)
    assert refused.value.code == 1 and "give-consent is not enabled for this channel" in str(refused.value)
    assert "model" not in agent_of(tree)


def test_a_page_set_model_on_an_autonomous_agent_is_refused_with_the_warning_and_the_consent_stays_the_pages_route(tree):
    with pytest.raises(ops.OpsError) as refused:
        ops.set_model(str(tree["project"]), "business", "fm", channel="page")
    assert refused.value.code == 2 and autonomy.CONSENT_WARNING in str(refused.value)
    assert "model" not in agent_of(tree)


# --- the route of the service ----------------------------------------------------------------------------------------------


@pytest.fixture
def world(tree, monkeypatch):
    monkeypatch.setenv("WORKBENCH_STARTED_WITH_UV", "0")
    import test_service as ts
    project = str(tree["project"])
    projects = [{"id": ts.service.project_id(project), "name": "p", "path": project}]
    return ts, types.SimpleNamespace(svc=ts.service.Service(ops, projects, ts.TOKEN, ts.PORT, None, log=lambda line: None), projects=projects)


def test_the_route_takes_the_four_fields_and_nothing_else_and_it_needs_the_token(tree, world):
    ts, w = world
    body = {"model": "fm", "mode": "autonomous", "config_sha256": sha(tree), "warning_sha256": WARNING_SHA}
    route = [r for r in ts.service.ROUTES if r["op"] == "give-consent"]
    assert len(route) == 1 and route[0]["method"] == "POST" and route[0]["pattern"] == "/projects/{p}/agents/{name}/consent"
    assert route[0]["take"] == ("model", "mode", "config_sha256", "warning_sha256")
    for extra in ({"accept": True}, {"consent": True}, {"channel": "terminal"}):
        status, _, answer = ts.call(w, "POST", ts.api(w, "/agents/business/consent"), {**body, **extra})
        assert status == 400 and answer["error"] == "usage", extra
    assert "consent" not in agent_of(tree)
    status, _, answer = ts.call(w, "POST", ts.api(w, "/agents/business/consent"), body, auth=False)
    assert status in (401, 403)
    status, _, answer = ts.call(w, "POST", ts.api(w, "/agents/business/consent"), {**body, "warning_sha256": "0" * 64})
    assert status == 400 and "warning" in answer["message"] and "consent" not in agent_of(tree)
    status, _, answer = ts.call(w, "POST", ts.api(w, "/agents/business/consent"), {**body, "mode": "milestones"})
    assert status == 400 and "consent" not in agent_of(tree)
    status, _, answer = ts.call(w, "POST", ts.api(w, "/agents/business/consent"), body)
    assert status == 200 and answer["by"] == "person:page" and answer["accepted"] is True
    assert answer["consent"] == {"model": "fm", "mode": "autonomous"}
    assert ts.call(w, "GET", ts.api(w, "/status"))[0] == 200


def test_the_page_ceiling_lists_it_and_every_other_shell_lists_none(tree):
    assert [r["name"] for r in operations.OPERATIONS if "give-consent" == r["name"] and r["channels"] != ("page",)] == []
    assert "give-consent" in operations.permissions("page", None) and "give-consent" not in operations.permissions("messaging", None)
    assert "give-consent" not in operations.terminal_verbs()
    assert not [r for r in operations.chat_commands() if "consent" in r["name"]]
    assert "give-consent" not in operations.permissions("page", {"page": ["read", "answer"]})
    assert "give-consent" in operations.permissions("page", {"page": ["read", "consent"]})
    # P3b: consent is a group of its own; set-mode, which used to cover it, does not
    assert "give-consent" not in operations.permissions("page", {"page": ["read", "set-mode"]})
    assert "give-consent" not in operations.GROUPS["set-mode"]["operations"] and operations.GROUPS["consent"]["operations"] == ("give-consent",)


def test_a_page_policy_with_set_mode_and_without_consent_cannot_consent_and_the_default_and_the_group_can(tree):
    configure(tree, {"business": dict(BUSINESS)}, channels={"page": ["read", "answer", "set-mode"]})
    file_before = config_path(tree).read_text(encoding="utf-8")
    with pytest.raises(ops.OpsError) as refused:
        consent(tree)
    assert refused.value.code == 1 and "give-consent is not enabled for this channel" in str(refused.value)
    assert config_path(tree).read_text(encoding="utf-8") == file_before and "model" not in agent_of(tree)
    configure(tree, {"business": dict(BUSINESS)}, channels={"page": ["read", "consent"]})
    assert consent(tree)["consent"] == {"model": "fm", "mode": "autonomous"}


def test_the_default_page_with_no_policy_may_consent(tree):
    assert "channels" not in json.loads(config_path(tree).read_text(encoding="utf-8"))
    assert operations.permitted("give-consent", "page", None)
    assert consent(tree)["accepted"] is True


# --- a move down is never withheld -----------------------------------------------------------------------------------------


def test_a_move_down_from_policy_to_autonomous_keeps_the_consent_without_asking(tree):
    path = str(tree["project"])
    ops.set_mode(path, "business", "autonomous-with-policy", channel="terminal", accept=True)  # no model fixed yet: no consent needed
    ops.set_model(path, "business", "fm", consent=True, accept=True, channel="terminal")
    assert agent_of(tree)["consent"] == {"model": "fm", "mode": "autonomous-with-policy"}
    done = ops.set_mode(path, "business", "autonomous", channel="page")  # a move down, from the page, with no flag
    assert (done["accepted"], done["by"]) == (True, "code:narrowing")
    assert done["consent"] == {"model": "fm", "mode": "autonomous"} and "warning" not in done
    assert agent_of(tree)["consent"] == {"model": "fm", "mode": "autonomous"}
    assert autonomy.consent_valid(agent_of(tree), "fm") is True


def test_a_move_down_without_a_valid_consent_is_not_refused_and_stores_none(tree):
    path = str(tree["project"])
    raw = json.loads(config_path(tree).read_text(encoding="utf-8"))
    raw["area_agents"]["business"].update(mode="autonomous-with-policy", model="fm")  # a hand-edited file with no consent
    config_path(tree).write_text(json.dumps(raw), encoding="utf-8")
    ops.accept_config(path, sha(tree))
    for target in ("autonomous", "milestones", "supervised", "stopped"):
        done = ops.set_mode(path, "business", target, channel="page")
        assert done["by"] == "code:narrowing" and done["consent"] is None, target
        assert "consent" not in agent_of(tree)
        raw = json.loads(config_path(tree).read_text(encoding="utf-8"))
        raw["area_agents"]["business"]["mode"] = "autonomous-with-policy"
        config_path(tree).write_text(json.dumps(raw), encoding="utf-8")
        ops.accept_config(path, sha(tree))


def test_a_move_up_still_asks_and_the_consent_flag_is_what_answers_it(tree):
    path = str(tree["project"])
    configure(tree, {"business": dict(BUSINESS, mode="milestones", model="fm")})
    with pytest.raises(ops.OpsError) as refused:
        ops.set_mode(path, "business", "autonomous", accept=True, channel="terminal")  # accept is the hash, not the consent
    assert refused.value.code == 2 and autonomy.CONSENT_WARNING in str(refused.value) and "--consent" in str(refused.value)
    done = ops.set_mode(path, "business", "autonomous", consent=True, accept=True, channel="terminal")
    assert done["warning"] == autonomy.CONSENT_WARNING and done["consent"] == {"model": "fm", "mode": "autonomous"}
    assert done["accepted"] is True and done["by"] == "person"


def test_the_wider_commands_of_the_agents_read_carry_the_consent_only_where_it_is_needed(tree):
    path = str(tree["project"])
    configure(tree, {"business": dict(BUSINESS, mode="milestones", model="fm")})
    [agent] = ops.agents(path)["agents"]
    wider = {w["mode"]: w["command"] for w in agent["wider"]}
    assert set(wider) == {"autonomous", "autonomous-with-policy"}
    assert all("--consent" in c and "--accept" in c for c in wider.values())
    configure(tree, {"business": dict(BUSINESS, mode="milestones")})  # no model fixed: a wider mode needs no consent
    [agent] = ops.agents(path)["agents"]
    assert all("--consent" not in w["command"] and w["command"].endswith("--accept") for w in agent["wider"])
