"""The dispatcher of the natural requests (package NR-2, runtime/ops_natural.py) through `ops.say`, on the stand-in tree with a stand-in router, the stand-in
answer skill and a stand-in clock: every class does what its class says and nothing more (R runs, N runs, D re-sends a card and decides nothing, G answers with
the command and runs nothing, E says it is not built yet), every operation is checked by `operations.refusal` with the channel and the sender as the typed
command is, a line that is a form of an operation runs no model, and a router-normalised time is confirmed before it makes anything. Limit L54 is
contracts/runtime.md; its tests are named test_limit_54_.... Offline; every name, id and sender is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_ops_natural.py
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import standin_tree as st
from sources_fixture import standin_convert
from test_ask import ANSWER, LEASE, NOTES, accept, add_source, run_files, runs, write_config
from test_chat import AGENTS, BRANCH, PACKS
from test_reminders import Clock

lab = st.load("lab")
ops = st.load("ops")
ops_core = st.load("ops_core")
ops_natural = st.load("ops_natural")
ops_reminders = st.load("ops_reminders")
ops_say = st.load("ops_say")
natural = st.load("natural")
operations = st.load("operations")
phrases = st.load("phrases")
plan = st.load("plan")
roles = st.load("roles")
router = st.load("router")
sources = st.load("sources")

OWNER, READER, NOTALK, MAILER, ASKER = "55119000000001", "55119000000002", "55119000000003", "55119000000004", "55119000000005"
KEY = {"owner": f"telegram:{OWNER}", "reader": f"telegram:{READER}", "notalk": f"telegram:{NOTALK}", "mailer": f"telegram:{MAILER}", "asker": f"telegram:{ASKER}"}
PROFILES = {"owner": ["read", "talk", "ask", "reminders", "brakes", "retry", "approve-plans", "answer", "release", "reject-cancel", "sources", "add-sources"],
            "reader": ["read"], "notalk": ["read", "ask"], "mailer": ["read", "talk", "ask", "ask-mail"], "asker": ["read", "talk", "ask"]}
SENDERS = {"telegram": [{"id": OWNER, "policy": "owner"}, {"id": READER, "policy": "reader"}, {"id": NOTALK, "policy": "notalk"},
                        {"id": MAILER, "policy": "mailer"}, {"id": ASKER, "policy": "asker"}]}
FLOW = "Route: flow-demo (flow, pending)\nWhy: a market question\nNext: the market task.\n"
OPERATION = "Route: none (operation)\nOperation: {name}\n"


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("WB_LOCAL_EVIDENCE_DIR", str(tmp_path / "evidence"))
    built = st.build(tmp_path, monkeypatch, lab)
    st.answer_skill(built["tree"])
    st.skill(built["tree"], router.ROUTER_SKILL, "docs/workbench/state.md", "")
    script = built["adapter"] / "run-prompt.sh"
    text = st.ADAPTER.replace("for name in demo-asks demo-writes;", "for name in demo-asks demo-writes core-orchestrator;")
    script.write_text(text.replace('case "$skill" in', BRANCH + 'case "$skill" in', 1), encoding="utf-8")
    monkeypatch.setattr(ops_core, "ROOT", str(built["tree"]))
    monkeypatch.setattr(ops_core, "_own_key", lambda variable: (None, None))      # never the real secret store
    packs = dict(PACKS, assist=[ANSWER])
    monkeypatch.setattr(plan, "resolve_pack", lambda pack, root: list(packs[pack]))
    monkeypatch.setattr(roles, "answer", lambda root=None, file=None: ANSWER)
    monkeypatch.setattr(sources, "provider_convert", lambda cfg, call=None: standin_convert)
    path = str(built["project"])
    write_config(path, area_agents={**AGENTS, "assistant": {"pack": "assist", "max_runs_per_day": 10}})
    ops.accept_config(path, ops.project_config.load(path)["sha256"])
    files = tmp_path / "files"
    files.mkdir()
    built.update(path=path, files=files, ctx=ops_core.context(path), clock=Clock(monkeypatch))
    (built["adapter"] / "router-reply.md").write_text(FLOW, encoding="utf-8")
    ops_natural.forget_all()
    yield built
    ops_natural.forget_all()


def with_senders(world):
    accept(world["path"], policies=PROFILES, messaging={"senders": SENDERS})


def router_says(world, text):
    (world["adapter"] / "router-reply.md").write_text(text, encoding="utf-8")


def say(world, line, channel="page", sender=None):
    return ops.say(world["path"], line, channel=channel, sender=sender)


def phone(world, who, line):
    return ops.say(world["path"], line, channel="messaging", sender=KEY[who])


def stored(world) -> list:
    ctx = ops_core.context(world["path"])
    return ctx["store"].messages_list(ctx["conn"], ops.CONVERSATION, limit=500)


def no_model(world):
    assert st.calls(world["adapter"]) == [], "a tier-1 line runs no model"


@pytest.fixture
def docs(world):
    add_source(world, "lease-contract", LEASE)
    add_source(world, "meeting-notes", NOTES)
    return world


# --- tier 1: the reads --------------------------------------------------------------------------------------------------------------------------


def test_a_tier_1_read_runs_at_once_with_no_model_no_request_and_the_list_is_written_by_code(docs):
    out = say(docs, "what files do you have?")
    assert out["ran"] is False and out["request_id"] is None and out["pending_id"] is None and out["queued"] is False
    assert out["reply"].splitlines() == ["- lease-contract (file, " + out["reply"].split("(file, ")[1].split(")")[0] + ")",
                                         "- meeting-notes (file, " + out["reply"].split("(file, ")[2].split(")")[0] + ")"]
    assert "Contrato" not in out["reply"] and "Clausula" not in out["reply"] and "printer" not in out["reply"], "no heading, no sample value"
    no_model(docs)
    assert ops.status(docs["path"])["requests"] == []
    pt = say(docs, "quais arquivos voce tem?")
    assert pt["reply"] == out["reply"]


def test_a_tier_1_read_on_the_conversation_the_page_and_the_terminal_does_not_wait_for_the_router(docs):
    with ops_core._route_lock(docs["ctx"]["cfg"]):      # the router is answering another request
        out = ops.say(docs["path"], "what files do you have?", channel="page")
        assert out["queued"] is False and out["reply"].startswith("- lease-contract")
        assert ops.say(docs["path"], "what files do you have?", channel="chat")["queued"] is False
    no_model(docs)


def test_the_state_forms_keep_answering_where_they_were_and_a_pending_list_is_a_form_of_its_own(world):
    assert "What waits for you:" in say(world, "how are we doing?")["reply"]
    assert say(world, "pendencias")["reply"] == "Nothing waits for you."
    plan_id = say(world, "Which market first?")["pending_id"]
    listed = say(world, "what do I need to approve?")["reply"]
    assert listed == f"#{plan_id} plan: " + ops.pending(world["path"], plan_id)["title"]
    assert st.calls(world["adapter"]) == ["core-orchestrator 1"], "only the line that was a request ran the router"


def test_a_read_that_needs_a_number_asks_for_it_and_one_that_has_it_runs(world):
    assert say(world, "tarefa 9")["reply"].startswith("error: ")
    assert ops.task is not None


def test_the_help_is_public_and_a_messaging_app_gets_its_own_list(world):
    assert say(world, "help")["reply"] == operations.chat_help()
    with_senders(world)
    assert phone(world, "reader", "ajuda")["reply"] == phrases.text("HELP", None)


def test_the_help_asks_no_policy_because_it_reads_nothing_of_the_project(world):
    accept(world["path"], policies={"nothing": ["talk"]}, messaging={"senders": {"telegram": [{"id": READER, "policy": "nothing"}]}})
    assert phone(world, "reader", "help")["reply"] == phrases.text("HELP", None)


def test_the_list_of_sources_a_messaging_sender_gets_has_no_heading_and_no_sample_value(docs):
    with_senders(docs)
    out = phone(docs, "owner", "quais arquivos voce tem?")
    assert out["ran"] is False and "lease-contract" in out["reply"] and "Clausula" not in out["reply"] and "Renew" not in out["reply"]
    no_model(docs)


# --- the policy, as the typed command ----------------------------------------------------------------------------------------------------------


def test_a_profile_without_the_group_gets_the_typed_commands_refusal_and_the_operation_is_not_called(world, monkeypatch):
    accept(world["path"], policies={**PROFILES, "nothing": ["talk"]}, messaging={"senders": {"telegram": [{"id": NOTALK, "policy": "nothing"}]}})
    calls = []
    monkeypatch.setattr(ops, "pending", lambda *a, **k: calls.append(a) or {"pending": []})
    typed = phone(world, "notalk", "/pending")["reply"]
    assert typed.startswith("error: /pending is not enabled for this channel")
    refused = phone(world, "notalk", "pendencias")["reply"]
    assert refused == typed == "error: " + operations.refusal("pending", "messaging", ops_core.context(world["path"])["cfg"]["channels"], sender=KEY["notalk"])
    assert calls == []


def test_a_read_a_profile_may_do_is_done_without_the_group_talk(docs):
    accept(docs["path"], policies={"readonly": ["read", "sources"]}, messaging={"senders": {"telegram": [{"id": READER, "policy": "readonly"}]}})
    out = phone(docs, "reader", "what files do you have?")
    assert out["reply"].startswith("- lease-contract") and out["ran"] is False
    refused = phone(docs, "reader", "Which market first?")      # not a form: a plain line is a model run, and needs talk (the bridge asks; the layer only records it)
    assert refused["ran"] is True or refused["reply"]


def test_the_bridge_asks_the_group_of_the_form_and_not_talk_for_a_tier_1_line_and_talk_for_any_other(docs):
    bridge = st.load("messaging_bridge")
    stand = type("B", (), {"ops": ops})()
    needs = bridge.Bridge.needs
    assert needs(stand, "what files do you have?") == "sources"
    assert needs(stand, "aprova o plano 3") == "pending"
    assert needs(stand, "/ask qual o prazo?") == "ask"
    assert needs(stand, "/pending") is None
    assert needs(stand, "escreva o post de lancamento") is None
    assert needs(stand, "cancela o pedido 3") is None


# --- D, W, G, E ----------------------------------------------------------------------------------------------------------------------------------


def test_a_decision_named_in_words_decides_nothing_and_sends_its_card_again_on_a_messaging_app(world):
    with_senders(world)
    made = phone(world, "owner", "Which market first?")
    plan_id = made["pending_id"]
    out = phone(world, "owner", f"aprova o plano {plan_id}")
    assert out["resend"] == plan_id and out["ran"] is False and out["reply"] == phrases.text("NAT_DECISION_CARD", None, id=plan_id)
    assert ops.pending(world["path"], plan_id)["status"] == "open" and ops.status(world["path"])["requests"][0]["state"] == "requested"
    for verb in ("rejeita o pedido", "libera a entrega", "approve", "reject", "release"):
        again = phone(world, "owner", f"{verb} {plan_id}")
        assert again.get("resend") == plan_id and ops.pending(world["path"], plan_id)["status"] == "open", verb
    assert [t for t in ops.status(world["path"])["requests"] if t["state"] != "requested"] == []


def test_a_decision_named_in_words_on_the_page_points_to_its_command_and_decides_nothing(world):
    plan_id = say(world, "Which market first?")["pending_id"]
    out = say(world, f"aprova o plano {plan_id}")
    assert out["reply"] == phrases.text("NAT_DECISION_TYPED", None, command=f"/approve {plan_id}") and "resend" not in out
    assert ops.pending(world["path"], plan_id)["status"] == "open"
    gone = say(world, "aprova o plano 99")["reply"]
    assert gone.startswith("error: ")


def test_a_decision_that_is_not_open_is_said_so_and_no_card_is_sent(world):
    with_senders(world)
    plan_id = phone(world, "owner", "Which market first?")["pending_id"]
    ops.reject(world["path"], plan_id)
    out = phone(world, "owner", f"approve {plan_id}")
    assert "resend" not in out and f"{plan_id}" in out["reply"] and "not open" in out["reply"]


def test_a_write_named_in_words_is_never_run_and_the_reply_is_the_command_to_send(world):
    with_senders(world)
    request = phone(world, "owner", "Which market first?")["request_id"]
    out = phone(world, "owner", f"cancela o pedido {request}")
    assert out["reply"] == phrases.text("NAT_TYPE_IT", None, command=f"/cancel {request}") and out["ran"] is False
    assert ops.status(world["path"])["requests"][0]["state"] == "requested"
    on_page = say(world, f"stop task 5")["reply"]
    assert on_page == phrases.text("NAT_TYPE_IT", None, command="/stop-task 5")
    assert phone(world, "owner", "add file 3")["reply"] == phrases.text("NAT_TYPE_IT", None, command="/add 3")
    assert phone(world, "owner", "discard attachment 3")["reply"] == phrases.text("NAT_TYPE_IT", None, command="/discard 3")


def test_a_gated_act_named_in_words_is_never_run_and_the_reply_names_the_place_and_the_command(world):
    before = ops.config(world["path"])["sha256"]
    out = say(world, "muda o modelo do agente")
    assert out["ran"] is False and "in the terminal or on the page" in out["reply"] and "set-model" in out["reply"]
    assert "--agent <agent>" in out["reply"] and "--model <model>" in out["reply"]
    sync = say(world, "sync the documents")["reply"]
    assert "sync" in sync and "in the terminal or on the page" in sync
    assert ops.config(world["path"])["sha256"] == before
    with_senders(world)
    phoned = phone(world, "owner", "muda o modelo do agente")["reply"]
    assert phoned.startswith("error: /set-model is done in the terminal or on the page") and "python3" in phoned


def test_a_planned_effect_says_it_is_not_built_yet_in_the_projects_language_and_runs_nothing(world):
    out = say(world, "marca na agenda o dentista sexta as 9")
    assert out["reply"] == "I cannot do that yet: create an event on your calendar (planned)." and out["ran"] is False
    accept(world["path"], language="pt-BR")
    pt = say(world, "marca na agenda o dentista sexta as 9")["reply"]
    assert pt == "Ainda n\u00e3o sei fazer isso: criar um evento na sua agenda (planejado)."  # validate: allow english-only -- the Portuguese sentence under test
    assert say(world, "edite o meu CV")["reply"] == "Ainda n\u00e3o sei fazer isso: editar um documento no seu drive (planejado)."  # validate: allow english-only -- the Portuguese sentence under test
    assert ops_core.context(world["path"])["store"].reminders_list(world["ctx"]["conn"], None) == []
    no_model(world)


# --- the conversation keeps no reminder words -------------------------------------------------------------------------------------------------------


def test_the_conversation_stores_the_line_of_a_read_and_a_neutral_word_for_the_words_of_a_reminder(docs, monkeypatch):
    say(docs, "what files do you have?")
    assert [m["text"] for m in stored(docs)][0] == "what files do you have?"
    import re
    monkeypatch.setitem(natural._COMPILED, "remind", (re.compile(r"lembrete secret words"),))      # package NR-1 owns the forms of this row; a stand-in form
    assert natural.private("lembrete secret words") and ops_natural.stored_line(docs["ctx"], "lembrete secret words") == "(a reminder)"
    assert not natural.private("what files do you have?")


# --- the drafts -----------------------------------------------------------------------------------------------------------------------------------


def test_a_draft_belongs_to_one_sender_waits_ten_minutes_and_a_line_that_is_not_its_answer_drops_it(world, monkeypatch):
    clock = {"t": 1000.0}
    monkeypatch.setattr(ops_natural, "monotonic", lambda: clock["t"])
    key = ops_natural._key(world["ctx"], "messaging", KEY["owner"])
    ops_natural._put(key, {"kind": "confirm", "when": "2026-10-19 13:00", "text": "x"})
    assert ops_natural.peek(world["ctx"], "yes", "messaging", KEY["owner"]) is True
    assert ops_natural.peek(world["ctx"], "yes", "messaging", KEY["reader"]) is False, "another sender's draft is not theirs"
    assert ops_natural.peek(world["ctx"], "yes", "page", None) is False
    assert ops_natural.peek(world["ctx"], "something else", "messaging", KEY["owner"]) is False
    clock["t"] += ops_natural.DRAFT_TTL + 1
    assert ops_natural.peek(world["ctx"], "yes", "messaging", KEY["owner"]) is False, "ten minutes, then it is gone"
    for n in range(ops_natural.DRAFTS_MAX + 5):
        ops_natural._put((world["ctx"]["cfg"]["project"], "messaging", f"s{n}"), {"kind": "confirm", "when": "w", "text": "t"})
    assert len(ops_natural._DRAFTS) <= ops_natural.DRAFTS_MAX
    assert world["ctx"]["cfg"]["project"] not in json.dumps({"log": "nothing is logged"}), "drafts are in memory only"


# --- limit L54 ----------------------------------------------------------------------------------------------------------------------------------


def spy_all(monkeypatch):
    """Every operation of the table replaced by a recorder: {name: [(args, kwargs)]}. A call that a class must never make is found in it. Armed after the
    configuration is written (the test's own `accept` reads `config`)."""
    seen = {}
    for row in operations.OPERATIONS:
        def spy(*args, sender=None, _name=row["name"], **kwargs):
            seen.setdefault(_name, []).append((args, dict(kwargs, sender=sender) if sender else kwargs))
            return {"pending": [], "status": "open", "sources": [], "reply": "spied", "open": [], "not_sent": [], "zone": "UTC"}
        monkeypatch.setattr(ops, row["call"], spy)
    return seen


def test_limit_54_a_decision_a_gated_act_a_write_and_a_planned_effect_named_by_a_line_run_nothing_on_any_channel(world, monkeypatch):
    """The walk of the table: every operation of class D, G or W and every planned effect, named on every channel, as an operation with every argument its
    row has. Nothing is called, except that a decision reads `pending` to know whether its card exists."""
    with_senders(world)
    spied = spy_all(monkeypatch)
    walked = 0
    for name in sorted(natural.CLASSES):
        cls = natural.CLASSES[name]
        if cls not in ("D", "G", "W", "E"):
            continue
        args = {param: 1 for _slot, (_kind, param) in natural.NATURAL[name]["slots"].items()}
        for channel, sender in (("page", None), ("chat", None), ("terminal", None), ("mcp", None), ("messaging", KEY["owner"])):
            spied.clear()
            ctx = ops_core.context(world["path"])
            reply = ops_natural.run(world["path"], ctx, name, args, "a line that names it", channel, sender, {})
            assert isinstance(reply, str) and reply, (name, channel)
            assert set(spied) <= ({"pending"} if cls == "D" else set()), (name, channel, sorted(spied))
            walked += 1
    assert walked == 5 * len([n for n, c in natural.CLASSES.items() if c in ("D", "G", "W", "E")]) >= 5 * 50


def test_limit_54_a_read_or_a_notice_without_its_group_gets_the_typed_refusal_and_the_operation_is_not_called(world, monkeypatch):
    accept(world["path"], policies={"nothing": ["talk"]}, messaging={"senders": {"telegram": [{"id": READER, "policy": "nothing"}]}})
    policy = ops_core.context(world["path"])["cfg"]["channels"]
    spied = spy_all(monkeypatch)
    walked = []
    for name in sorted(natural.CLASSES):
        if natural.CLASSES[name] not in ("R", "N") or name == "commands" or "messaging" not in operations.by_name(name)["channels"]:
            continue
        ctx = ops_core.context(world["path"])
        reply = ops_natural.run(world["path"], ctx, name, {}, "a line", "messaging", KEY["reader"], {})
        assert reply == "error: " + operations.refusal(name, "messaging", policy, sender=KEY["reader"]), (name, reply)
        walked.append(name)
    assert spied == {} and set(walked) >= {"status", "pending", "task", "agents", "sources", "reminders", "reminder-forget", "remind", "routines"}


def test_limit_54_an_operation_that_a_row_does_not_list_for_the_channel_is_the_typed_commands_sentence(world, monkeypatch):
    spied = spy_all(monkeypatch)
    ctx = ops_core.context(world["path"])
    reply = ops_natural.run(world["path"], ctx, "agents", {}, "a line", "chat", None, {})
    assert reply == "error: /agents is done in the terminal or on the page" and spied == {}


def test_limit_54_an_argument_the_line_does_not_bear_out_is_never_passed_to_an_operation(world, monkeypatch):
    spied = spy_all(monkeypatch)
    ctx = ops_core.context(world["path"])
    for name, args, line in (("reminder-forget", {"reminder_id": 9}, "forget reminder 3"), ("artifact", {"path": "docs/secret.md"}, "show docs/plan.md"),
                             ("remind", {"text": "buy milk"}, "remind me to call mom")):
        reply = ops_natural.run_routed(world["path"], ctx, {"name": name, "args": args, "when": None}, line, "page", None, {})
        assert reply == phrases.text("NAT_NOT_BELIEVED", None), name
    assert spied == {}


def test_limit_54_a_router_normalised_time_makes_no_reminder_until_the_person_confirms_it(world, monkeypatch):
    with_senders(world)
    spied = spy_all(monkeypatch)
    ctx = ops_core.context(world["path"])
    reply = ops_natural.run_routed(world["path"], ctx, {"name": "remind", "args": {"text": "cortarme el pelo"}, "when": "2026-10-19 13:00"},
                                   "recuerdame manana a las 13 cortarme el pelo", "messaging", KEY["owner"], {})
    assert reply.endswith("Answer yes to confirm.") and spied == {}, "asked, not made"
    done = ops_natural.take(world["path"], ctx, "yes", "messaging", KEY["owner"], {})
    assert spied["remind"][0][1]["when"] == "2026-10-19 13:00" and spied["remind"][0][1]["channel"] == "messaging"
    assert spied["remind"][0][1]["sender"] == KEY["owner"], "called with the carrying channel and the sender, as the typed command is"
    assert done == "spied"


# --- the rest of the contract ---------------------------------------------------------------------------------------------------------------


def test_a_tier_1_line_and_the_neutral_word_of_a_reminder_are_left_out_of_the_routers_memory(docs, monkeypatch):
    import re
    monkeypatch.setitem(natural._COMPILED, "remind", (re.compile(r"lembrete secret words"),))      # package NR-1 owns the forms of this row; a stand-in form
    say(docs, "what files do you have?")
    say(docs, "lembrete secret words")
    say(docs, "Which market first?")
    prompt = (docs["adapter"] / "last-router-prompt.md").read_text(encoding="utf-8")
    assert "what files do you have" not in prompt and "secret words" not in prompt and "(a reminder)" not in prompt
    assert [m["text"] for m in stored(docs)][:3] == ["what files do you have?", docs_first_reply(docs), "(a reminder)"]


def docs_first_reply(world) -> str:
    return [m["text"] for m in stored(world) if m["role"] == "assistant"][0]


def test_a_typed_ask_written_as_a_reminder_ends_with_one_hint_and_is_never_rerouted(docs, monkeypatch):
    import re
    monkeypatch.setitem(natural._COMPILED, "remind", (re.compile(r"remind me .*"),))      # a stand-in for the forms package NR-1 writes
    out = say(docs, "/ask remind me tomorrow at 1 pm about the haircut")
    assert out["reply"].endswith("\n\n" + phrases.text("NAT_ASK_REMIND_HINT", None)) and "write it in words" in out["reply"]
    assert st.calls(docs["adapter"]) == ["demo-answers 1"], "it stayed an ask: one answer run, no router"
    accept(docs["path"], language="pt-BR")
    pt = say(docs, "/ask remind me tomorrow at 1 pm about the haircut")["reply"]
    assert pt.endswith("'me lembra amanhã às 13h do corte de cabelo'.")      # validate: allow english-only -- the Portuguese sentence under test
    plain = say(docs, "/ask qual o prazo do contrato?")["reply"]
    assert "write it in words" not in plain and "escreva em palavras" not in plain
