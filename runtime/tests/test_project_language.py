"""Tests of the language a deliverable is written in, the runtime part of package LANGUAGE (runtime/language.py, runtime/ops_language.py):
the rule and the order (the request's choice, else the key `language`, else `en`), the paragraph a task run and the router's run always
get and a contained run, a step task and the lab never get, the per-request option from the terminal (`request --language`), the plan
field the hash covers, the line every plan shows, the router's optional `Language:` line, and the answer that never changes it. The key's
own check is in test_project_config_language.py; the migration is in providers/store/tests/test_sqlite_language.py. On the stand-in
trees of the other tests, with `lab.run_skill` wrapped to keep the prompt it was given (no model is called). Offline; invented names only.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_project_language.py
"""
from __future__ import annotations

import json
import re

import pytest

import phrase_kit as pk
import standin_tree as st
from test_chat import ASKING, FLOW, reply, router_prompt, say
from test_chat import tree as chat_tree  # noqa: F401
from test_contained_run import SOCIAL
from test_contained_run import tree as contained_tree  # noqa: F401
from test_instructions_runs import kept_prompts
from test_service import api, call, world  # noqa: F401  (the service over a stand-in for the operations)

PT = {"language": "pt-BR"}

lab = st.load("lab")
language = st.load("language")
ops = st.load("ops")
ops_core = st.load("ops_core")
ops_language = st.load("ops_language")
operations = st.load("operations")
plan = st.load("plan")
project_config = st.load("project_config")
router = st.load("router")

REQUEST = "Which market should the invented studio go after first?"
PROJECT_PT = "Project language: `pt-BR`"
REQUESTED_EN = "Language of this deliverable: `en` (requested)"
NO_KEY = language.line(None, None)


def configure(tree, **extra) -> str:
    """Write the keys into the project's runtime.json (a key of None removes it) and accept the file."""
    path = str(tree["project"])
    file = project_config.path(path)
    with open(file, encoding="utf-8") as f:
        raw = json.load(f)
    raw.update(extra)
    raw = {k: v for k, v in raw.items() if v is not None}
    with open(file, "w", encoding="utf-8") as f:
        json.dump(raw, f)
    ops.accept_config(path, project_config.load(path)["sha256"])
    return path


def rows(tree) -> list:
    ctx = ops_core.context(str(tree["project"]))
    return ctx["store"].tasks_list(ctx["conn"])


def planned(tree, text=REQUEST, **options) -> dict:
    """A request recorded with the options, routed (the stand-in router answers the flow), its plan opened: {request, pending, item}."""
    path = str(tree["project"])
    made = ops.request(path, text, **options)
    routed = ops.route(path, made["request"])
    return {"request": made["request"], "pending": routed["pending_id"], "item": ops.pending(path, routed["pending_id"])}


# --- the rule and the order --------------------------------------------------------------------------------------------------------------


def test_the_tag_rule_is_the_keys_and_a_bad_tag_is_refused_with_the_right_form():
    assert language.RULE is project_config.LANGUAGE_RE
    for good in ("en", "pt-BR", "en-US", "es", "fr", "de"):
        assert language.check(good) == good
    assert language.check(None) is None and language.check("") is None
    for bad, hint in (("pt_BR", "; did you mean pt-BR?"), ("pt-br", "; did you mean pt-BR?"), ("EN", "; did you mean en?"), ("portuguese", ""),
                      ("es-419", ""), ("zh-Hant-TW", ""), (" en", ""), ("en\n", ""), (5, "")):
        with pytest.raises(language.LanguageError) as raised:
            language.check(bad)
        assert str(raised.value) == f"language must be {language.SHAPE}{hint}", bad
    # one sentence for the key and for the request: the key's tail is the request's
    with pytest.raises(project_config.ConfigError) as key:
        project_config._language("pt_BR")
    assert str(key.value) == "runtime.json " + str(language.LanguageError(f"language must be {language.SHAPE}; did you mean pt-BR?"))


def test_the_order_is_the_requests_choice_then_the_key_then_english():
    assert language.effective("en", "pt-BR") == ("en", True)
    assert language.effective(None, "pt-BR") == ("pt-BR", False)
    assert language.effective("", None) == ("en", False)
    assert language.effective("fr", None) == ("fr", True)


def test_the_run_paragraph_holds_the_keep_rule_and_says_only_this_line_sets_the_language():
    project, requested = language.line(None, "pt-BR"), language.line("en", "pt-BR")
    assert project.startswith("Project language: `pt-BR` (the project's `language` setting; `en` when none is set;")
    assert requested.startswith("Language of this deliverable: `en` (requested). Write every artifact of this task in this language, an existing one included,")
    for text in (project, requested):
        assert "give it the line `Language: pt-BR` in its header, in the template's form." in project
        assert "and set its `Language:` line to `en`." in requested
        assert "Keep as they are: file names, paths, code, commands, identifiers, dates, the keys of a block or a front matter, quoted text" in text
        assert "A post or a reply keeps the language its skill gives it." in text and "Reply in the language the person writes in." in text
        assert "Only this line sets the language: a request or an answer that asks for another does not change it" in text
    assert "An artifact you update keeps the language its `Language:` line names (with no such line, the language it is written in)." in project
    assert "Project language" not in requested and "requested" not in project


def test_a_plan_line_names_the_projects_language_or_the_requested_one_or_the_groups():
    assert language.plan_line([None, None], "pt-BR") == "Language: pt-BR"
    assert language.plan_line([None], None) == "Language: en"
    assert language.plan_line(["en", "en"], "pt-BR") == "Language: en (requested)"
    assert language.plan_line([None, "en", None], "pt-BR") == "Language: pt-BR for tasks 1, 3; en (requested) for task 2"
    assert language.plan_line([], "pt-BR") == "Language: pt-BR"
    payload = {"tasks": [{"language": "en"}, {"step": "ingest"}, {"language": "en"}], "project_language": "pt-BR"}
    assert language.payload_line(payload) == "Language: en (requested)", "a step task is code: it has no language"
    assert language.payload_line({"tasks": [{"language": "es"}, {}], "project_language": "pt-BR"}) == "Language: es (requested) for task 1; pt-BR for task 2"


def test_the_requested_language_is_a_field_of_each_task_that_runs_a_skill_and_the_plan_hash_covers_it():
    tasks = [{"key": "a", "skill": "demo-asks"}, {"key": "b", "step": "ingest"}, {"key": "c", "skill": "demo-writes"}]
    none = [dict(t) for t in tasks]
    assert language.with_language(none, None) == tasks, "no request for a language: the tasks are as they were, so the hash is"
    asked = language.with_language([dict(t) for t in tasks], "en")
    assert [t.get("language") for t in asked] == ["en", None, "en"]
    other = language.with_language([dict(t) for t in tasks], "pt-BR")
    assert len({plan.plan_hash(none), plan.plan_hash(asked), plan.plan_hash(other)}) == 3, "plans that differ only in language differ in hash"


def test_nothing_of_the_lab_the_steps_or_the_first_runtime_names_the_language_modules():
    from pathlib import Path
    repo = Path(st.REPO)
    names = ("ops_language", "import language", "language.py", "language_rules", "language.line", "from language")
    held = [repo / "runtime" / "lab.py", repo / "runtime" / "steps.py", repo / "runtime" / "ops_steps.py", repo / "runtime" / "ops_contained.py",
            *sorted((repo / "runtime").glob("step_*.py")), *sorted((repo / "evals").glob("*.py")), *sorted((repo / "adapters").glob("*/run-agent.sh"))]
    assert held, "the files that must never name the module were found"
    for path in held:
        text = path.read_text(encoding="utf-8")
        assert not [n for n in names if n in text], f"{path.relative_to(repo)} names the language module"


def test_the_stores_tag_rule_is_the_runtimes():
    module = ops_core.store_module()
    assert module.LANGUAGE_RE.pattern == language.RULE.pattern.strip("^$").replace("(-", "(?:-")


# --- the request option: the terminal, the operation table, the refusal -------------------------------------------------------------------


def test_the_request_operation_takes_a_language_and_the_terminal_names_it():
    row = operations.by_name("request")
    assert "language" in {a["name"] for a in row["args"]} and "--language" in (st.REPO / "runtime" / "cli.py").read_text(encoding="utf-8")
    assert "language" in row["help"]


def test_a_bad_language_is_refused_before_anything_is_recorded(chat_tree):
    path = str(chat_tree["project"])
    for bad, hint in (("pt_BR", "; did you mean pt-BR?"), ("portuguese", ""), ("es-419", "")):
        with pytest.raises(ops_core.OpsError) as raised:
            ops.request(path, REQUEST, language=bad)
        assert raised.value.code == 2 and str(raised.value) == f"language must be {language.SHAPE}{hint}"
    assert rows(chat_tree) == [], "no request was recorded"


# --- end to end from the terminal: request --language -> row -> plan -> approval -> task row -> the run's prompt --------------------------


def test_a_requested_language_goes_from_the_request_to_the_plan_the_hash_the_task_row_and_the_runs_prompt_once(chat_tree, monkeypatch):
    path = str(chat_tree["project"])
    configure(chat_tree, language="pt-BR")
    seen = kept_prompts(monkeypatch)
    made = planned(chat_tree, language="en")
    request = next(r for r in rows(chat_tree) if r["id"] == made["request"])
    assert request["language"] == "en", "the request row records the person's choice"
    item = made["item"]
    tasks = item["payload"]["tasks"]
    assert [t["language"] for t in tasks] == ["en", "en"], "each task of the plan carries it"
    assert "Language: en (requested)" in item["body"].splitlines() and item["payload"]["project_language"] == "pt-BR"
    assert plan.plan_hash(tasks) == item["payload"]["plan_sha256"]
    assert plan.plan_hash([{k: v for k, v in t.items() if k != "language"} for t in tasks]) != item["payload"]["plan_sha256"]
    approved = ops.approve(path, made["pending"], sha256=item["payload"]["plan_sha256"])
    assert approved["plan_sha256"] == item["payload"]["plan_sha256"]
    assert [t["language"] for t in rows(chat_tree) if t["parent_id"] == made["request"]] == ["en", "en"], "the task rows hold it"
    ran = ops.run_next(path)
    assert ran["status"] == "ok"
    prompt = seen[-1]
    assert prompt.count(REQUESTED_EN) == 1 and "Project language" not in prompt
    assert prompt.index("For this task: do the market analysis.") < prompt.index(REQUESTED_EN)


def test_without_a_request_the_projects_key_decides_the_plan_line_and_the_runs_line_and_a_new_key_is_read_at_the_next_run(chat_tree, monkeypatch):
    path = str(chat_tree["project"])
    configure(chat_tree, language="pt-BR")
    seen = kept_prompts(monkeypatch)
    made = planned(chat_tree)
    assert "Language: pt-BR" in made["item"]["body"].splitlines() and all("language" not in t for t in made["item"]["payload"]["tasks"])
    ops.approve(path, made["pending"], sha256=made["item"]["payload"]["plan_sha256"])
    first = ops.run_next(path)
    assert first["status"] == "ok" and seen[-1].count(PROJECT_PT) == 1 and "(requested)" not in seen[-1]
    assert [t["language"] for t in rows(chat_tree) if t["parent_id"] == made["request"]] == [None, None]
    configure(chat_tree, language="es")      # the key is read at each start, so the run after the answer is told the new one
    ops.answer(path, first["pending_id"], "Portugal.")
    assert ops.run_next(path)["status"] == "ok"
    assert seen[-1].count("Project language: `es`") == 1 and PROJECT_PT not in seen[-1]


def test_a_project_that_sets_no_language_gets_english_in_every_task_run_and_the_router_run(chat_tree, monkeypatch):
    path = str(chat_tree["project"])
    seen = kept_prompts(monkeypatch)
    made = planned(chat_tree)
    assert "Language: en" in made["item"]["body"].splitlines()
    assert router_prompt(chat_tree).count("Project language: `en`") == 1
    ops.approve(path, made["pending"], sha256=made["item"]["payload"]["plan_sha256"])
    ops.run_next(path)
    assert seen[-1].count("Project language: `en`") == 1 and seen[-1].endswith(NO_KEY + "\n")


def test_the_routers_run_carries_the_requested_language_and_a_conversation_request_carries_the_projects(chat_tree):
    configure(chat_tree, language="pt-BR")
    planned(chat_tree, language="fr")
    assert router_prompt(chat_tree).count("Language of this deliverable: `fr` (requested by the person") == 1
    say(chat_tree, "Which market first?")
    assert router_prompt(chat_tree).count(PROJECT_PT) == 1


# --- the router's proposal: the optional Language line, read by code, seen on the card before approval ---------------------------------------


def test_the_router_reads_one_language_line_and_a_bad_tag_or_two_lines_leave_the_reply_unclassified():
    base = "Route: flow-demo (flow, pending)\nWhy: a market question\n"
    assert router.read_route(base + "Language: en\nNext: x\n")["language"] == "en"
    assert router.read_route(base + "Language: pt-BR\n")["language"] == "pt-BR"
    assert "language" not in router.read_route(base + "Next: x\n")
    for bad in ("Language: pt_BR\n", "Language: portuguese\n", "Language: en\nLanguage: pt-BR\n", "Language: es-419\n", "Language: <tag, for example en or pt-BR>\n"):
        read = router.read_route(base + bad)
        assert read["kind"] == "unclassified" and "Language" in read["why"], bad


def test_a_proposal_from_the_router_is_on_the_card_in_the_task_rows_after_approval_and_in_the_run(chat_tree, monkeypatch):
    path = str(chat_tree["project"])
    configure(chat_tree, language="pt-BR")
    seen = kept_prompts(monkeypatch)
    reply(chat_tree, FLOW + "Language: en\n")
    out = say(chat_tree, "Write the market spec in English for the invented studio.")
    assert "Language: en (requested)" in out["reply"].splitlines(), "the conversation's reply shows it before the estimate"
    lines = out["reply"].splitlines()
    assert lines.index("Language: en (requested)") < next(i for i, line in enumerate(lines) if pk.said(line, "PLAN_ESTIMATE", PT)), "the estimate line is the project's language (pt-BR), LR-1"
    item = ops.pending(path, out["pending_id"])
    assert "Language: en (requested)" in item["body"].splitlines() and [t["language"] for t in item["payload"]["tasks"]] == ["en", "en"]
    request = next(r for r in rows(chat_tree) if r["id"] == out["request_id"])
    assert request["language"] is None, "a proposal is not the person's recorded choice: it is on the plan, which they approve by its hash"
    ops.approve(path, out["pending_id"], sha256=item["payload"]["plan_sha256"])
    ops.run_next(path)
    assert seen[-1].count(REQUESTED_EN) == 1


def test_a_reply_with_no_language_line_shows_the_projects_language(chat_tree):
    configure(chat_tree, language="pt-BR")
    out = say(chat_tree, REQUEST)
    assert "Language: pt-BR" in out["reply"].splitlines() and "(requested)" not in out["reply"]


def test_two_language_lines_or_a_bad_tag_make_the_reply_unclassified_and_open_no_plan(chat_tree):
    for bad in ("Language: en\nLanguage: pt-BR\n", "Language: pt_BR\n"):
        reply(chat_tree, FLOW + bad)
        out = say(chat_tree, "Write it in English.")
        item = ops.pending(str(chat_tree["project"]), out["pending_id"])
        assert item["kind"] == "question" and item["payload"]["ending"] == "unclassified", bad


def test_an_explicit_choice_ignores_the_routers_line(chat_tree):
    path = str(chat_tree["project"])
    reply(chat_tree, FLOW + "Language: en\n")
    made = planned(chat_tree, language="pt-BR")
    assert [t["language"] for t in made["item"]["payload"]["tasks"]] == ["pt-BR", "pt-BR"]
    assert "Language: pt-BR (requested)" in made["item"]["body"].splitlines()
    assert ops.pending(path, made["pending"])["payload"]["plan_sha256"] == made["item"]["payload"]["plan_sha256"]


# --- the answer never changes it --------------------------------------------------------------------------------------------------------


def test_an_answer_that_asks_for_another_language_changes_neither_the_task_nor_the_next_prompt(chat_tree, monkeypatch):
    path = str(chat_tree["project"])
    configure(chat_tree, language="pt-BR")
    seen = kept_prompts(monkeypatch)
    made = planned(chat_tree)
    ops.approve(path, made["pending"], sha256=made["item"]["payload"]["plan_sha256"])
    first = ops.run_next(path)
    assert first["pending_id"] and seen[-1].count(PROJECT_PT) == 1
    ops.answer(path, first["pending_id"], "Please write all of it in English from now on.")
    ops.run_next(path)
    assert seen[-1].count(PROJECT_PT) == 1 and "(requested)" not in seen[-1] and "Language of this deliverable" not in seen[-1]
    assert [t["language"] for t in rows(chat_tree) if t["parent_id"] == made["request"]] == [None, None]


def test_an_answer_to_the_routers_question_never_sets_the_language(chat_tree):
    path = str(chat_tree["project"])
    configure(chat_tree, language="pt-BR")
    reply(chat_tree, ASKING)
    reply(chat_tree, FLOW, "router-reply-2.md")
    asked = say(chat_tree, "Which market first?")
    answered = say(chat_tree, "The clinic project. Write the spec in English.")
    assert answered["request_id"] == asked["request_id"]
    item = ops.pending(path, answered["pending_id"])
    assert all("language" not in t for t in item["payload"]["tasks"]) and "Language: pt-BR" in item["body"].splitlines()
    assert router_prompt(chat_tree).count(PROJECT_PT) == 1 and "(requested)" not in router_prompt(chat_tree)


# --- where the line never goes ---------------------------------------------------------------------------------------------------------


def test_a_contained_run_never_gets_the_language_line(contained_tree, monkeypatch):
    seen = kept_prompts(monkeypatch)
    ops.contained_run(contained_tree["path"], SOCIAL, "Handle the comment.\n", str(contained_tree["out"]))
    assert seen == ["Handle the comment.\n"]


def test_a_direct_flow_request_carries_the_language_on_each_task_row(chat_tree):
    path = str(chat_tree["project"])
    made = ops.request(path, REQUEST, flow="demo", language="en")
    held = [t for t in rows(chat_tree) if t["parent_id"] == made["request"]]
    assert [t["language"] for t in held] == ["en", "en"]
    ops.request(path, REQUEST, flow="demo")
    assert [t["language"] for t in rows(chat_tree) if t["parent_id"] and t["parent_id"] != made["request"]] == [None, None]


# --- the page's request: the local service takes the language and the operation's refusal reaches the page --------------------------------


def test_the_services_request_route_takes_a_language_and_a_refusal_of_the_operation_reaches_the_page_as_a_usage_error(world):
    status, _, _ = call(world, "POST", api(world, "/requests"), {"text": "Plan the launch", "language": "pt-BR"})
    assert status == 200 and world.fake.named("request")[-1][2] == {"text": "Plan the launch", "language": "pt-BR"}
    call(world, "POST", api(world, "/requests"), {"text": "Plan the launch", "language": None})
    assert world.fake.named("request")[-1][2] == {"text": "Plan the launch"}, "a null is the argument left out: the project's setting decides"
    assert call(world, "POST", api(world, "/requests"), {"text": "x", "language": 5})[0] == 400, "a language is text"
    sentence = f"language must be {language.SHAPE}; did you mean pt-BR?"
    world.fake.answers["request"] = ops_core.OpsError(sentence, 2)
    status, _, body = call(world, "POST", api(world, "/requests"), {"text": "x", "language": "pt_BR"})
    assert status == 400 and body["message"] == sentence



# --- review of the pull request: the router's own paragraph, the explicit choice, the sub-tasks of a delivery -----------------------------


def test_the_router_has_a_paragraph_of_its_own_that_tells_it_when_to_propose_a_language():
    project, requested = language.router_line(None, "pt-BR"), language.router_line("fr", "pt-BR")
    assert project.startswith("Project language: `pt-BR` (the project's `language` setting; `en` when none is set).")
    assert "write the `Language: <tag>` line of your template with that tag" in project and "a proposal the person approves on the plan" in project
    assert "Never write it from the language the request is written in." in project
    assert "does not change it" not in project, "the task run's sentence would make the router drop the proposal"
    assert requested.startswith("Language of this deliverable: `fr` (requested by the person") and "Write no `Language:` line" in requested
    assert language.line(None, "pt-BR") != project and "does not change it" in language.line(None, "pt-BR"), "a task run keeps its own sentence"


def test_the_router_run_gets_its_variant_and_a_task_run_does_not(chat_tree, monkeypatch):
    path = str(chat_tree["project"])
    configure(chat_tree, language="pt-BR")
    seen = kept_prompts(monkeypatch)
    made = planned(chat_tree)
    assert language.router_line(None, "pt-BR") in router_prompt(chat_tree) and language.line(None, "pt-BR") not in router_prompt(chat_tree)
    ops.approve(path, made["pending"], sha256=made["item"]["payload"]["plan_sha256"])
    ops.run_next(path)
    assert language.line(None, "pt-BR") in seen[-1] and language.router_line(None, "pt-BR") not in seen[-1]


def test_with_an_explicit_choice_the_routers_language_line_is_not_read_at_all(chat_tree):
    base = "Route: flow-demo (flow, pending)\nWhy: a market question\n"
    assert router.read_route(base + "Language: en\nLanguage: pt-BR\n")["kind"] == "unclassified"
    assert "language" not in router.read_route(base + "Language: en\n", ignore_language=True)
    assert router.read_route(base + "Language: en\nLanguage: pt-BR\n", ignore_language=True)["kind"] == "route"
    reply(chat_tree, FLOW + "Language: en\nLanguage: pt-BR\n")
    made = planned(chat_tree, language="fr")
    assert made["item"]["kind"] == "plan" and [t["language"] for t in made["item"]["payload"]["tasks"]] == ["fr", "fr"]
    reply(chat_tree, FLOW + "Language: pt_BR\n")
    again = planned(chat_tree, language="fr")
    assert again["item"]["kind"] == "plan"


def test_the_subtasks_of_a_backlog_task_take_its_own_language_then_the_requests_then_the_plans():
    approved = {"tasks": [{"key": "d1-backlog", "language": "en"}, {"key": "d2-backlog", "language": "es"}]}
    request = {"language": None}
    assert ops_language.of_plan(approved, request, {"language": "es"}) == "es", "the second delivery keeps its language"
    assert ops_language.of_plan(approved, request, {"language": "en"}) == "en", "and the first keeps its own"
    assert ops_language.of_plan(approved, {"language": "fr"}, {"language": None}) == "fr"
    assert ops_language.of_plan(approved, request, {"language": None}) == "en", "the last resort is the first language the plan carries"
    assert ops_language.of_plan({"tasks": [{"key": "a"}]}, request, None) is None


def test_the_backlog_subtasks_a_delivery_spawns_carry_its_language_and_the_card_of_those_outside_the_limits_says_it(chat_tree, monkeypatch):
    path = str(chat_tree["project"])
    made = ops.request(path, REQUEST)
    ctx = ops_core.context(path)
    approved = {"limits": {"subtask_skills": ["demo-writes"], "max_subtasks": 1},
                "tasks": [{"key": "d1-backlog", "language": "en"}, {"key": "d2-backlog", "language": "es"}]}
    proposed = [{"key": "t-1", "skill": "demo-writes", "title": "T-1", "text": "do it.", "depends_on": [], "milestone": False},
                {"key": "t-2", "skill": "demo-writes", "title": "T-2", "text": "do it.", "depends_on": [], "milestone": False}]
    monkeypatch.setattr(ops, "_approved_plan", lambda c, rid: approved)
    monkeypatch.setattr(plan, "backlog_tasks", lambda p, root=None: [dict(t) for t in proposed])
    created = []
    monkeypatch.setattr(ops.ops_waits, "add_subtasks", lambda c, rid, tasks: created.extend(tasks) or {"tasks": []})
    out = ops._backlog_subtasks(ctx, {"parent_id": made["request"], "language": "es", "key": "d2-backlog"})
    assert [(t["key"], t["language"]) for t in created] == [("t-1", "es")], "inside the limit: the second delivery's language"
    card = ops.pending(path, out["pending_id"])
    assert card["kind"] == "acceptance" and "Language: es (requested)" in card["body"].splitlines()
