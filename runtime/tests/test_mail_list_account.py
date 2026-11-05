"""The account question of a list of mail, and the display and the numbers of a list of two accounts (package mail-list-account, limit L65; runtime/plan_confirm.py, runtime/ops_items.py,
runtime/item_refs.py, runtime/ops_interpret.py, runtime/ops_turn.py).

A project with two mail sources and a line that asks for "the e-mails" with no account used to be asked "Shall I go ahead?" and then got both lists. Now the question is "Which account?", the person's
choice is the OK, and a list of two accounts is one message with each source set off. Over the REAL snapshots behind the real runtime/item_refs.py (the world and the stand-in providers of
test_calendar_write.py and test_sources_mail.py), the real natural-request path (`ops_natural.run`) and the real `ops.say` for the person's OK, a stand-in clock and a stand-in model. Every
expectation is a literal of this file; every oracle that counts, searches or compares has a vacuity case that fails on a planted wrong result. Offline; every name, address and word is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_mail_list_account.py
"""
from __future__ import annotations

import json

import pytest

import standin_tree as st
import test_sources_mail as tsm
from test_calendar_write import Snapshots, world  # noqa: F401  (the calendar world and its real snapshots)
from test_mail_read import IDS, SENDERS, gmail, outlook
from test_reminders import Clock

ops = st.load("ops")
ops_core = st.load("ops_core")
ops_items = st.load("ops_items")
ops_natural = st.load("ops_natural")
ops_sources = st.load("ops_sources")
ops_natural_mail = st.load("ops_natural_mail")
interpreter_route = st.load("interpreter_route")
ops_interpret = st.load("ops_interpret")
interpreter = st.load("interpreter")
interpreter_enable = st.load("interpreter_enable")
item_refs = st.load("item_refs")
pending_items = st.load("pending_items")
plan_confirm = st.load("plan_confirm")
phrases = st.load("phrases")
source_names = st.load("source_names")

ASKING, READER = SENDERS["asking"], SENDERS["reader"]      # `asking` is asked "Shall I go ahead?" (and now "Which account?"); `reader` holds confirm-reads-off
PROFILES = {"asking": ["read", "talk", "ask-mail", "read-mail-body", "interpret"],
            "reader": ["read", "talk", "ask-mail", "read-mail-body", "confirm-reads-off"]}
EN_QUESTION = "I understood: list your e-mails. Which account? Gmail, Outlook or all."
PT_QUESTION = "Entendi: listar seus e-mails. De qual conta? Gmail, Outlook ou todas."      # validate: allow english-only -- the Portuguese words under test
GMAIL_ROW = "1. Bia Costa · Appointment confirmed · today 06:00"      # the stand-in provider prints a message at 09:00 UTC, which is 06:00 in the world's zone
OUTLOOK_ROW = "1. Dan Reis · Weekly report · today 06:00"


@pytest.fixture
def clock(monkeypatch):
    return Clock(monkeypatch, wall="2026-10-17 08:00")


@pytest.fixture
def snaps(world, monkeypatch):  # noqa: F811
    s = Snapshots(world, monkeypatch)
    monkeypatch.setattr(ops_items, "SNAPSHOT_CLOCK", lambda: s.now)
    ops_items._CHECKED.clear()
    pending_items.clear()
    item_refs._LISTED.clear()
    monkeypatch.setattr(item_refs, "LISTED_CLOCK", lambda: s.listed)
    s.listed = 1000.0
    yield s
    pending_items.clear()
    item_refs._LISTED.clear()


def configure(world, language="en", profiles=PROFILES):
    """The accepted policy: the listed senders, each with a profile of its own, in the language given."""
    path = world["path"] + "/docs/workbench/runtime.json"
    raw = json.loads(open(path).read())
    raw["policies"] = profiles
    raw["language"] = language
    raw["messaging"] = {"senders": {"telegram": [{"id": IDS[name], "policy": name} for name in profiles]}}
    open(path, "w").write(json.dumps(raw))
    shown = ops.config(world["path"])
    ops.accept_config(world["path"], shown["sha256"], widen=shown["widening_sha256"])


def boxes(world, snaps, language="en", mails=None, others=None, second=True, profiles=PROFILES):
    """The policy, a Gmail source `inbox` (and, unless `second` is False, an Outlook source `work`) each read once; the provider's count of reads starts at zero."""
    configure(world, language, profiles)
    snaps.providers.mail["gmail"] = [tsm.message(1, "2026-10-17T09:00:00Z", "Bia Costa <bia@clinic.example>", "Appointment confirmed", "Your visit is confirmed.")] if mails is None else mails
    snaps.providers.mail["outlook"] = [tsm.message(1, "2026-10-17T09:00:00Z", "Dan Reis <dan@work.example>", "Weekly report", "Weekly numbers attached.", source="outlook")] if others is None else others
    ops_sources.source_mail(world["path"], "inbox", "gmail:box=inbox;days=7;max=50")
    if second:
        ops_sources.source_mail(world["path"], "work", "outlook:box=inbox;days=7;max=50")
    del snaps.providers.calls[:]


def mail_reads(snaps):
    return [c for c in snaps.providers.calls if c["cls"] == "reader:email"]


def call(world, line, args=None, sender=ASKING, name="items"):
    """(the reply, the extras) of the natural-request path for `name` with the arguments the interpreter would give."""
    ctx = ops_core.context(world["path"])
    extras = {}
    return ops_natural.run(world["path"], ctx, name, dict(args or {}), line, "messaging", sender, extras), extras


def plan_ok(extras, choice=None):
    got = extras["plan_confirm"]
    return {"item": got["item"], "sha256": got["sha256"], **({"choice": choice} if choice is not None else {})}


def accept(world, extras, choice=None, sender=ASKING):
    """The reply of the person's OK, through the real `ops.say` (the row `confirmed-plan`: no model reads it)."""
    return ops.say(world["path"], "yes", channel="messaging", sender=sender, plan_ok=plan_ok(extras, choice))["reply"]


def live(world, sender=ASKING):
    return plan_confirm.live(world["path"], sender)


# --- the question -------------------------------------------------------------------------------------------------------------------------------


def test_a_list_of_mail_with_no_account_asks_which_one_and_reads_nothing(world, snaps, clock):
    boxes(world, snaps)
    reply, extras = call(world, "list my e-mails")
    assert reply == EN_QUESTION
    assert mail_reads(snaps) == [] and extras["plan_confirm"]["choices"] == ["Gmail", "Outlook", "All"]
    plan = live(world)
    assert plan["state"]["question"] == EN_QUESTION and "source" not in plan["state"]["args"] and "account" not in plan["state"]["args"], "one plan; no account in its call"
    assert [c["value"] for c in plan["state"]["choices"]] == ["inbox", "work", "*"]


def test_the_same_question_in_portuguese(world, snaps, clock):
    boxes(world, snaps, "pt-BR")
    reply, extras = call(world, "quais são meus últimos e-mails?")      # validate: allow english-only -- the Portuguese words under test
    assert reply == PT_QUESTION
    assert extras["plan_confirm"]["choices"] == ["Gmail", "Outlook", "Todas"] and mail_reads(snaps) == []


def test_no_question_when_the_line_or_the_call_already_says_which_account_or_how_many_or_what_word(world, snaps, clock):
    boxes(world, snaps, "pt-BR")
    asked_plainly = "Entendi: listar seus e-mails{}. Posso?"      # validate: allow english-only -- the Portuguese words under test
    for line, args, then in [("e-mails do outlook", None, " do Outlook"), ("emails via outlook", {"match": "outlook"}, " do Outlook"), ("meu último e-mail", None, ""),
                             ("os 3 últimos e-mails", None, ""), ("tem algum email do banco", {"match": "banco"}, " com “banco”")]:      # validate: allow english-only -- the Portuguese words under test
        reply, extras = call(world, line, args)
        assert reply == asked_plainly.format(then), line
        assert "choices" not in extras["plan_confirm"] and "choices" not in live(world)["state"], line
    reply, extras = call(world, "meus eventos")      # a calendar list is untouched, byte for byte
    assert reply == "Entendi: mostrar os eventos da sua agenda. Posso?" and "choices" not in extras["plan_confirm"]      # validate: allow english-only -- the Portuguese words under test


def test_one_mail_source_is_asked_the_plain_question(world, snaps, clock):
    boxes(world, snaps, second=False)
    reply, extras = call(world, "list my e-mails")
    assert reply == "I understood: list your e-mails. Shall I go ahead?" and "choices" not in extras["plan_confirm"]


def test_a_list_of_unread_mail_or_of_a_day_still_asks_which_account(world, snaps, clock):
    boxes(world, snaps, "pt-BR")
    reply, _ = call(world, "lista os emails não lidos", {"state_span": "não lidos"})      # validate: allow english-only -- the Portuguese words under test
    assert reply == "Entendi: listar seus e-mails (só os não lidos). De qual conta? Gmail, Outlook ou todas."      # validate: allow english-only -- the Portuguese words under test
    reply, _ = call(world, "lista os emails de amanhã")      # validate: allow english-only -- the Portuguese words under test
    assert reply.endswith(". De qual conta? Gmail, Outlook ou todas.") and reply.startswith("Entendi: listar seus e-mails de ")      # validate: allow english-only -- the Portuguese words under test


def test_a_sender_who_holds_confirm_reads_off_gets_both_lists_at_once_and_no_question(world, snaps, clock):
    boxes(world, snaps)
    reply, extras = call(world, "list my e-mails", sender=READER)
    assert reply == f"**Gmail** (read at 07:12):\n{GMAIL_ROW}\n\n**Outlook** (read at 07:12):\n{OUTLOOK_ROW}" and "plan_confirm" not in extras


# --- the choice is the OK of the plan: `take` -----------------------------------------------------------------------------------------------


def refused(world, extras, bad):
    """Whether `take` refused `bad` and left the sender's plan alive (the oracle of the next tests)."""
    return plan_confirm.take(world["path"], ASKING, dict(plan_ok(extras), **bad)) is None and live(world) is not None


def test_take_refuses_a_question_plan_without_a_valid_choice_and_leaves_the_plan(world, snaps, clock):
    boxes(world, snaps)
    _, extras = call(world, "list my e-mails")
    assert plan_confirm.take(world["path"], ASKING, plan_ok(extras)) is None and live(world) is not None, "no choice"
    for bad in ({"choice": 3}, {"choice": 9}, {"choice": -1}, {"choice": True}, {"choice": "1"}, {"choice": 1.0}, {"choice": None}):
        assert refused(world, extras, bad), bad
    taken = plan_confirm.take(world["path"], ASKING, plan_ok(extras, 1))
    assert taken is not None and taken["state"]["choices"][1]["value"] == "work" and live(world) is None, "a valid choice pops the plan, once"


def test_take_refuses_a_choice_on_a_plain_plan_and_takes_it_without(world, snaps, clock):
    boxes(world, snaps)
    _, extras = call(world, "meus eventos")
    assert plan_confirm.take(world["path"], ASKING, plan_ok(extras, 0)) is None and live(world) is not None, "a plain plan takes no choice"
    assert plan_confirm.take(world["path"], ASKING, plan_ok(extras)) is not None and live(world) is None


def test_vacuity_a_take_that_ignores_the_choice_is_seen_by_the_same_oracle(world, snaps, clock, monkeypatch):
    boxes(world, snaps)
    _, extras = call(world, "list my e-mails")
    real = plan_confirm.take
    monkeypatch.setattr(plan_confirm, "take", lambda project, sender, ok: real(project, sender, dict(ok, choice=0)))      # planted: every plan_ok is taken as option 0
    assert not refused(world, extras, {"choice": 9}), "the planted take pops the plan for a choice that is not an option"


def test_the_hash_binds_the_options_and_a_plain_plans_hash_is_what_it_was(world, snaps, clock):
    boxes(world, snaps)
    call(world, "list my e-mails")
    state = live(world)["state"]
    key = ops_natural.project_key(world["path"])

    def hashed(choices):
        return plan_confirm.plan_sha256(key, ASKING, state["op"], state["args"], state["when"], state["routed"], state["said"], choices)
    options = state["choices"]
    assert hashed(options) == state["sha256"]
    assert len({hashed(options), hashed(options[:2]), hashed(options[::-1]), hashed([dict(options[0], value="other")] + options[1:])}) == 4, "other options, other hash"
    assert plan_confirm.plan_sha256("0123456789ab", "telegram:5102", "items", {"kind": "mail"}, None, False, "list my e-mails") == "a6744f404fb6e07e5f0fa8aea33432d25b00ea3be260f82d196a434dfb1642ea", "no choices: the digest the code made before this package"
    assert plan_confirm.plan_sha256("0123456789ab", "telegram:5102", "items", {"kind": "mail"}, None, False, "list my e-mails", []) == "a6744f404fb6e07e5f0fa8aea33432d25b00ea3be260f82d196a434dfb1642ea"


# --- each option runs ------------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("choice, expected", [(0, f"Gmail (read at 07:12):\n{GMAIL_ROW}"), (1, f"Outlook (read at 07:12):\n{OUTLOOK_ROW}"),
                                              (2, f"**Gmail** (read at 07:12):\n{GMAIL_ROW}\n\n**Outlook** (read at 07:12):\n{OUTLOOK_ROW}")])
def test_each_option_runs_the_list_of_that_account_alone_and_all_runs_both(world, snaps, clock, choice, expected):
    boxes(world, snaps)
    _, extras = call(world, "list my e-mails")
    assert accept(world, extras, choice) == expected
    assert live(world) is None and mail_reads(snaps) == [], "the plan ran once; the snapshots were fresh"


def test_the_display_of_a_list_of_two_accounts_is_one_message_and_a_one_account_list_is_as_it_was(world, snaps, clock, monkeypatch):
    boxes(world, snaps)
    _, extras = call(world, "list my e-mails")
    both = accept(world, extras, 2)
    assert "**Gmail**" in both and "\n\n**Outlook**" in both
    _, extras = call(world, "list my e-mails")
    one = accept(world, extras, 0)
    assert "**" not in one and "\n\n" not in one and one.startswith("Gmail (read at")
    real = ops_items.render
    monkeypatch.setattr(ops_items, "render", lambda out, cfg, **kw: real(out, cfg, **kw).replace("\n\n", "\n"))      # planted: a render with no blank line
    _, extras = call(world, "list my e-mails")
    assert "\n\n**Outlook**" not in accept(world, extras, 2), "the oracle sees the planted display"


# --- the closed words ------------------------------------------------------------------------------------------------------------------------

ONE = {"gmail": 0, "Gmail": 0, "GMAIL": 0, "outlook": 1, "google": 0, "hotmail": 1, "o outlook": 1, "do gmail": 0, "the outlook": 1, "from gmail": 0,
       "1": 0, "2": 1, "3": 2, "o segundo": 1, "a última": 2, "o do outlook": 1,      # validate: allow english-only -- the Portuguese words under test
       "todas": 2, "os dois": 2, "as duas": 2, "ambos": 2, "ambas": 2, "both": 2, "all": 2, "los dos": 2, "toutes": 2, "les deux": 2, "alle": 2, "beide": 2, "tutte": 2, "entrambe": 2, "de todas": 2}
NONE = ["nos dois", "o do trabalho", "sim", "ok", "não", "oi", "4", "0", "gmail?", "todas?", "outlook ?", "1?", "gmail por favor", "both of them", "all of them", "", "quero ver os e-mails",      # validate: allow english-only -- the Portuguese words under test
        "no gmail", "no outlook", "no 1", "no all", "no both", "no todas"]      # a refusal and a name: "no" is a lead only in a Portuguese project (see below)      # validate: allow english-only -- the Portuguese words under test


def table_failures(world):
    plan = live(world)
    wrong = [f"{line!r}: {plan_confirm.choice_of(plan, line)} != {want}" for line, want in ONE.items() if plan_confirm.choice_of(plan, line) != want]
    return wrong + [f"{line!r}: {plan_confirm.choice_of(plan, line)} != None" for line in NONE if plan_confirm.choice_of(plan, line) is not None]


def test_choice_of_reads_the_closed_words_and_only_them(world, snaps, clock):
    boxes(world, snaps)
    call(world, "list my e-mails")
    assert table_failures(world) == []


def test_a_line_in_question_form_is_no_answer_to_the_account_question(world, snaps, clock):
    boxes(world, snaps)
    call(world, "list my e-mails")
    plan = live(world)
    for line in ("gmail?", "todas?", "Outlook ?", "1?", "o segundo?", "gmail ？"):      # validate: allow english-only -- the Portuguese words under test
        assert plan_confirm.choice_of(plan, line) is None, line
    assert plan_confirm.choice_of(plan, "gmail") == 0 and plan_confirm.choice_of(plan, "gmail.") == 0 and plan_confirm.choice_of(plan, "gmail!") == 0, "the same words as a statement are the answer"


def test_vacuity_without_the_question_form_rule_the_same_lines_are_an_answer(world, snaps, clock, monkeypatch):
    boxes(world, snaps)
    call(world, "list my e-mails")
    monkeypatch.setattr(plan_confirm.card_words, "question_form", lambda line: False)      # planted: no line is a question
    plan = live(world)
    assert plan_confirm.choice_of(plan, "gmail?") == 0 and plan_confirm.choice_of(plan, "todas?") == 2, "the counter that is None above sees the answer"


def test_vacuity_a_choice_of_that_returns_zero_for_every_line_is_seen_by_the_table(world, snaps, clock, monkeypatch):
    boxes(world, snaps)
    call(world, "list my e-mails")
    monkeypatch.setattr(plan_confirm, "choice_of", lambda item, said: 0)
    assert table_failures(world) != []


def test_a_plan_without_options_names_no_option(world, snaps, clock):
    boxes(world, snaps)
    call(world, "meus eventos")
    assert plan_confirm.choice_of(live(world), "gmail") is None and plan_confirm.choice_item(live(world)) is None


# --- the options are the project's accounts --------------------------------------------------------------------------------------------------


def test_a_source_with_no_known_account_is_never_an_option_and_no_id_reaches_the_phone(world, snaps, clock, monkeypatch):
    boxes(world, snaps)
    ops_sources.source_mail(world["path"], "starred", "gmail:box=starred;days=7;max=50")
    real = source_names.account_of
    monkeypatch.setattr(source_names, "account_of", lambda row: None if row["id"] == "work" else real(row))      # the Outlook source's origin is not one this runtime reads
    reply, extras = call(world, "list my e-mails")
    assert reply == "I understood: list your e-mails. Which account? Gmail (inbox), Gmail (starred) or all."
    assert extras["plan_confirm"]["choices"] == ["Gmail (inbox)", "Gmail (starred)", "All"] and "work" not in json.dumps(extras["plan_confirm"]) + reply
    frame = ops_interpret.frame_for(None, live(world))
    assert "work" not in json.dumps(frame) and all(set(v) == {"n", "label"} for v in frame["items"][1]["values"]), "no source id and no code in the frame: a label and a number"


def test_two_sources_and_one_with_an_unknown_account_ask_no_question(world, snaps, clock, monkeypatch):
    boxes(world, snaps)
    real = source_names.account_of
    monkeypatch.setattr(source_names, "account_of", lambda row: None if row["id"] == "work" else real(row))
    reply, extras = call(world, "list my e-mails")
    assert reply == "I understood: list your e-mails. Shall I go ahead?" and "choices" not in extras["plan_confirm"]


def test_more_than_eight_accounts_ask_no_question(world, snaps, clock, monkeypatch):
    boxes(world, snaps)
    monkeypatch.setattr(ops_items, "ACCOUNT_OPTIONS_MAX", 1)      # the limit, made small: two accounts are over it
    reply, extras = call(world, "list my e-mails")
    assert reply == "I understood: list your e-mails. Shall I go ahead?" and "choices" not in extras["plan_confirm"]


# --- the typed frame ---------------------------------------------------------------------------------------------------------------------------


def test_the_frame_holds_the_plan_item_and_a_choice_item_with_the_labels_of_the_options_only(world, snaps, clock):
    boxes(world, snaps)
    call(world, "list my e-mails")
    frame = ops_interpret.frame_for(None, live(world))
    assert [(i["id"], i["kind"], i["need"]) for i in frame["items"]] == [("i1", "plan-confirm", "confirm"), ("i2", "choice", "option")]
    assert frame["items"][1]["options"] == 3 and frame["items"][1]["values"] == [{"label": "Gmail", "n": 1}, {"label": "Outlook", "n": 2}, {"label": "All", "n": 3}]
    assert interpreter.frame_problems(frame, interpreter.SERVED) == []
    assert "inbox" not in json.dumps(frame) and "work" not in json.dumps(frame), "no source id in the frame"


def test_the_enabled_interpreter_entry_still_names_this_checkouts_hashes():
    data = json.loads((st.REPO / "runtime" / "interpreter_enable.json").read_text(encoding="utf-8"))
    newest = data["entries"][-1]
    assert interpreter.SERVED_SHA256 == newest["catalog_sha256"], "the catalog the frame is checked against is the one the newest entry enabled"
    assert {k: newest[k] for k in interpreter_enable.HASH_KEYS} == interpreter_enable.checkout_hashes(newest["route"]), "the prompt, the catalog and the protocol did not change"


# --- a free answer: the model reads it, code checks it ---------------------------------------------------------------------------------------


class Model:
    """The model stood in at its route: what it answers is `says`, what it was shown is `calls`."""

    def __init__(self):
        self.calls, self.says = [], json.dumps({"v": 1, "kind": "route"})


@pytest.fixture
def model(monkeypatch):
    m = Model()

    def complete(route_id, system, user, **kw):
        m.calls.append(user)
        return {"ok": True, "text": m.says, "finish": "stop", "usage": {}, "latency_ms": 5, "upstream": "deepinfra"}
    monkeypatch.setattr(interpreter_route, "complete", complete)
    monkeypatch.setattr(ops_interpret, "_zone", lambda now: "America/Sao_Paulo")
    ops_interpret.forget_all()
    return m


@pytest.fixture
def reads(monkeypatch):
    """The calls of the one place a list runs (the test's own count), the real read still running."""
    found, real = [], ops_natural._read

    def spy(project, ctx, name, row, args, channel, sender):
        found.append((name, dict(args)))
        return real(project, ctx, name, row, args, channel, sender)
    monkeypatch.setattr(ops_natural, "_read", spy)
    return found


def answer(option, item="i2"):
    return json.dumps({"v": 1, "kind": "answer", "answers_item": item, "option": option})


def say(world, line, sender=ASKING):
    return ops.say(world["path"], line, channel="messaging", sender=sender)


def test_a_free_answer_the_model_places_states_a_plan_that_names_the_account_and_reads_nothing(world, snaps, clock, model, reads):
    boxes(world, snaps)
    call(world, "list my e-mails")
    model.says = answer(2)
    out = say(world, "the outlook one please")
    assert out["reply"] == "I understood: list your e-mails from Outlook. Shall I go ahead?" and len(model.calls) == 1 and reads == [], "one model call; nothing was read"
    state = live(world)["state"]
    assert "choices" not in state and state["args"]["source"] == "work" and out["plan_confirm"]["item"] == live(world)["id"] and "choices" not in out["plan_confirm"], "a plain plan now"
    assert accept(world, {"plan_confirm": out["plan_confirm"]}) == f"Outlook (read at 07:12):\n{OUTLOOK_ROW}" and [r[1].get("source") for r in reads] == ["work"], "only the person's own yes ran it"


def test_a_free_answer_for_all_the_accounts_states_that_plan(world, snaps, clock, model, reads):
    boxes(world, snaps)
    call(world, "list my e-mails")
    model.says = answer(3)
    out = say(world, "nos dois")      # validate: allow english-only -- the Portuguese words under test
    assert out["reply"] == "I understood: list your e-mails from all accounts. Shall I go ahead?" and reads == [] and "source" not in live(world)["state"]["args"]


def test_an_option_the_question_does_not_have_asks_again_and_keeps_the_plan(world, snaps, clock, model, reads):
    boxes(world, snaps)
    call(world, "list my e-mails")
    item = live(world)["id"]
    model.says = answer(9)
    out = say(world, "o quarto")      # validate: allow english-only -- the Portuguese words under test
    assert out["reply"] == EN_QUESTION and reads == [] and live(world)["id"] == item and out["plan_confirm"]["item"] == item and out["plan_confirm"]["choices"] == ["Gmail", "Outlook", "All"]


def test_a_clarify_or_a_model_yes_on_the_plans_item_asks_the_question_again_and_reads_nothing(world, snaps, clock, model, reads):
    boxes(world, snaps)
    call(world, "list my e-mails")
    item = live(world)["id"]
    for says in (json.dumps({"v": 1, "kind": "clarify"}), json.dumps({"v": 1, "kind": "answer", "answers_item": "i1", "confirm": "yes"})):
        model.says = says
        out = say(world, "o do trabalho")      # validate: allow english-only -- the Portuguese words under test
        assert out["reply"] == EN_QUESTION and live(world)["id"] == item and out["plan_confirm"]["item"] == item, says
    assert reads == [] and len(model.calls) == 2


def test_a_model_no_drops_the_plan_and_an_op_states_a_new_plan(world, snaps, clock, model, reads):
    boxes(world, snaps)
    call(world, "list my e-mails")
    model.says = json.dumps({"v": 1, "kind": "answer", "answers_item": "i1", "confirm": "no"})
    assert say(world, "no, thanks")["reply"] == "All right, I did nothing." and live(world) is None
    call(world, "list my e-mails")
    model.says = json.dumps({"v": 1, "kind": "op", "op": "items", "slots": {}})
    out = say(world, "show me the e-mails from outlook")
    assert out["reply"] == "I understood: list your e-mails from Outlook. Shall I go ahead?" and reads == []


def test_vacuity_a_model_option_that_runs_the_plan_is_seen_by_the_oracle(world, snaps, clock, model, reads, monkeypatch):
    boxes(world, snaps)
    call(world, "list my e-mails")
    real = plan_confirm.ask

    def runs(project, ctx, name, args, said, sender, extras, **kw):      # planted: the model's option runs the call at once
        return ops_natural.run(project, ctx, name, args, said, "messaging", sender, extras, confirmed=True)
    monkeypatch.setattr(plan_confirm, "ask", runs)
    model.says = answer(2)
    out = say(world, "the outlook one please")
    assert reads != [] and "(read at" in out["reply"], "the planted code read the list on a model's word: the other tests' `reads == []` would fail"
    monkeypatch.setattr(plan_confirm, "ask", real)


# --- the account named in free wording ---------------------------------------------------------------------------------------------------------


def test_a_target_that_is_only_the_name_of_the_account_the_line_names_is_the_account_and_no_word_filter(world, snaps, clock):
    boxes(world, snaps)
    reply, _ = call(world, "e-mails via outlook", {"match": "outlook"})
    assert reply == "I understood: list your e-mails from Outlook. Shall I go ahead?" and live(world)["state"]["args"] == {"kind": "mail", "account": "microsoft"}, "no `match`: the list is not filtered by the word Outlook"
    reply, _ = call(world, "e-mails do Google", {"match": "Google"})
    assert live(world)["state"]["args"]["match"] == ["google"] and "“google”" in reply, "a lone Google stays a word filter, said in the sentence"      # validate: allow english-only -- the Portuguese words under test
    call(world, "e-mails do trabalho", {"match": "trabalho"})
    assert live(world)["state"]["args"] == {"kind": "mail", "match": ["trabalho"]}      # validate: allow english-only -- the Portuguese words under test


def test_without_named_account_changes_only_a_target_that_is_the_accounts_own_name(world, snaps, clock, monkeypatch):
    boxes(world, snaps)
    ctx = ops_core.context(world["path"])

    def spans_after(spans, said, context=ctx):
        return ops_items.without_named_account(context, dict(spans), said)
    assert spans_after({"target": "outlook"}, "e-mails via outlook") == {}
    assert spans_after({"target": "o Outlook"}, "e-mails do Outlook") == {}
    assert spans_after({"target": "outlook", "day": "tomorrow"}, "e-mails via outlook tomorrow") == {"day": "tomorrow"}, "another span is kept"
    for spans, said in [({"target": "google"}, "e-mails do google"), ({"target": "outlook"}, "e-mails da ana"), ({"target": "banco"}, "e-mails via outlook"), ({"target": "gmail outlook"}, "e-mails via outlook"), ({}, "e-mails via outlook")]:
        assert spans_after(spans, said) == spans, (spans, said)
    real = ops_items.without_named_account
    monkeypatch.setattr(ops_items, "without_named_account", lambda context, spans, said: {})      # planted: every target dropped
    assert spans_after({"target": "banco"}, "e-mails via outlook", ctx) == {} != {"target": "banco"}, "the oracle sees the planted drop"
    monkeypatch.setattr(ops_items, "without_named_account", real)


def test_a_target_that_names_an_account_the_project_has_no_source_for_is_left_alone(world, snaps, clock):
    boxes(world, snaps, second=False)
    ctx = ops_core.context(world["path"])
    assert ops_items.without_named_account(ctx, {"target": "outlook"}, "e-mails via outlook") == {"target": "outlook"}, "no Outlook source in the project: nothing to name"


def test_account_named_words_say_the_account_a_call_is_narrowed_to(world, snaps, clock):
    boxes(world, snaps)
    ctx = ops_core.context(world["path"])
    assert ops_items.account_named_words(ctx, {"kind": "mail", "account": "microsoft"}) == "from Outlook"
    assert ops_items.account_named_words(ctx, {"kind": "mail", "source": "inbox"}) == "from Gmail"
    assert ops_items.account_named_words(ctx, {"kind": "mail"}) is None and ops_items.account_named_words(ctx, {"kind": "calendar", "account": "microsoft"}) is None


# --- the numbers after a list (N1) -----------------------------------------------------------------------------------------------------------


def listed(world, choice):
    """The person asks for the e-mails, answers the question with option `choice` and gets the list (the real `ops.say`, which counts the line)."""
    _, extras = call(world, "list my e-mails")
    return accept(world, extras, choice)


def next_line(world, sender=ASKING):
    """What `ops.say` does at the start of the next line of a messaging sender (the hook that counts it)."""
    item_refs.begin_turn(ops_core.context(world["path"]), "messaging", sender)


def read_plan(world, line="read e-mail 1", args=None, sender=ASKING):
    """The plan the line "read e-mail 1" states, as the call the interpreter would give."""
    reply, _ = call(world, line, dict({"number": 1}, **(args or {})), sender=sender, name="mail-read")
    return reply, dict(live(world, sender)["state"]["args"])


def test_after_a_list_of_one_account_the_number_of_the_next_line_means_that_list_and_the_plan_binds_it(world, snaps, clock):
    boxes(world, snaps)
    listed(world, 0)
    next_line(world)
    reply, args = read_plan(world)
    assert reply == "I understood: show the text of e-mail 1. Shall I go ahead?" and args == {"number": 1, "message": "inbox#1"}
    _, extras = call(world, "read e-mail 1", {"number": 1}, name="mail-read")
    assert accept(world, extras).startswith("Gmail · Bia Costa"), "the reply's head names the box, and it is Gmail's message"


def test_after_the_list_of_all_the_accounts_a_number_is_still_the_which_box_question(world, snaps, clock):
    boxes(world, snaps)
    listed(world, 2)
    next_line(world)
    reply, args = read_plan(world)
    assert args == {"number": 1}, "no binding"
    _, extras = call(world, "read e-mail 1", {"number": 1}, name="mail-read")
    shown = accept(world, extras)
    assert "Your visit is confirmed." not in shown and "Weekly numbers attached." not in shown, "two boxes hold a message 1: nothing is shown"


def test_an_account_named_in_the_line_wins_over_the_list_on_screen(world, snaps, clock):
    boxes(world, snaps)
    listed(world, 0)
    next_line(world)
    _, args = read_plan(world, "read e-mail 1 from outlook")
    assert args == {"number": 1}, "the line names the account: nothing is bound"
    _, args = read_plan(world, "read e-mail 1", {"account": "microsoft"})
    assert args == {"number": 1, "account": "microsoft"}


def test_the_memory_is_for_the_next_line_only_and_for_ten_minutes_and_for_the_version_listed(world, snaps, clock):
    boxes(world, snaps)
    listed(world, 0)
    next_line(world)
    next_line(world)
    assert read_plan(world)[1] == {"number": 1}, "the second line after the list"
    listed(world, 0)
    next_line(world)
    snaps.listed += 601
    assert read_plan(world)[1] == {"number": 1}, "after 600 seconds"
    listed(world, 0)
    next_line(world)
    snaps.listed += 600
    assert read_plan(world)[1] == {"number": 1, "message": "inbox#1"}, "inside the window, to its last second"
    listed(world, 0)
    snaps.providers.mail["gmail"] = [tsm.message(2, "2026-10-17T09:30:00Z", "Cora Dias <cora@clinic.example>", "New invoice", "Please pay.")] + snaps.providers.mail["gmail"]
    snaps.later(minutes=1)
    snaps.refresh("inbox")      # the source has a newer version than the one that was listed: the numbers moved
    next_line(world)
    assert call(world, "read e-mail 1", {"number": 1}, name="mail-read")[0] == "The list I showed has changed since: ask for the list again, then tell me the number.", "a new version of the listed source: the list is asked for again (MAIL-SUMMARY-FLIP review), no plan names no box"


def test_a_project_with_one_mail_source_keeps_no_memory_of_a_list(world, snaps, clock):
    boxes(world, snaps, second=False)
    _, extras = call(world, "list my e-mails")
    reply = ops.say(world["path"], "yes", channel="messaging", sender=ASKING, plan_ok=plan_ok(extras))["reply"]
    assert reply.startswith("Gmail (read at") and item_refs._LISTED == {}, "one mail source: the number is never ambiguous"


def test_the_write_path_gets_the_listed_source_after_one_list_and_asks_after_all(world, snaps, clock):
    boxes(world, snaps)
    ctx = ops_core.context(world["path"])
    listed(world, 0)
    next_line(world)
    account, refs, ask = ops_natural_mail._messages(ctx, {"numbers": [1]}, "messaging", ASKING)
    assert (account, refs, ask) == ("google", ["inbox#1"], None)
    listed(world, 2)
    next_line(world)
    account, refs, ask = ops_natural_mail._messages(ctx, {"numbers": [1]}, "messaging", ASKING)
    assert refs is None and ask is not None, "after both lists: which box?"


def test_vacuity_a_listed_source_that_ignores_the_version_is_seen_by_the_oracle(world, snaps, clock, monkeypatch):
    boxes(world, snaps)
    listed(world, 0)
    snaps.providers.mail["gmail"] = [tsm.message(2, "2026-10-17T09:30:00Z", "Cora Dias <cora@clinic.example>", "New invoice", "Please pay.")]
    snaps.later(minutes=1)
    snaps.refresh("inbox")
    next_line(world)
    ctx = ops_core.context(world["path"])

    def unversioned(context, channel, sender):      # planted: the version check left out
        found = item_refs._LISTED.get(item_refs._listed_key(context, sender))
        return found["source"] if found and found["seen"] == 1 else None
    assert item_refs.listed_source(ctx, "messaging", ASKING) is None
    monkeypatch.setattr(item_refs, "listed_source", unversioned)
    assert item_refs.listed_source(ctx, "messaging", ASKING) == "inbox", "the planted check would bind a number of a list that has moved"


def test_the_line_counter_is_wired_in_say(world, snaps, clock, model):
    """Through `ops.say`: the line after a list is counted, the one after that is not (the model is stood in to say the operation)."""
    boxes(world, snaps)
    listed(world, 0)
    model.says = json.dumps({"v": 1, "kind": "op", "op": "mail-read", "slots": {"message": "1"}})
    out = say(world, "read 1")
    assert out["reply"] == "I understood: show the text of e-mail 1. Shall I go ahead?" and live(world)["state"]["args"].get("message") == "inbox#1"
    listed(world, 0)
    say(world, "thanks for that")
    out = say(world, "read 1")
    assert "message" not in live(world)["state"]["args"], "the second line after the list"


# --- "no" is a lead only in Portuguese ------------------------------------------------------------------------------------------------------------


def test_no_before_a_name_is_a_lead_only_in_a_portuguese_project(world, snaps, clock):
    boxes(world, snaps, "pt-BR")
    call(world, "lista os emails")
    plan = live(world)
    assert plan_confirm.choice_of(plan, "no outlook") == 1 and plan_confirm.choice_of(plan, "no gmail") == 0, "in Portuguese it means 'in Gmail'"      # validate: allow english-only -- the Portuguese words under test
    assert plan_confirm.choice_of(plan, "no todas") is None and plan_confirm.choice_of(plan, "no all") is None, "and never names every account"      # validate: allow english-only -- the Portuguese words under test
    assert plan_confirm.choice_of(plan, "de todas") == 2


@pytest.mark.parametrize("language", ["en", "es", "fr", "de", "it"])
def test_in_any_other_language_a_no_before_a_name_goes_to_the_model(world, snaps, clock, language):
    boxes(world, snaps, language)
    call(world, "list my e-mails")
    plan = live(world)
    assert [plan_confirm.choice_of(plan, line) for line in ("no outlook", "no gmail", "no 1", "no all", "no both", "no todas")] == [None] * 6


def test_vacuity_with_no_as_a_lead_in_every_language_the_english_refusal_picks_an_account(world, snaps, clock, monkeypatch):
    boxes(world, snaps)
    call(world, "list my e-mails")
    monkeypatch.setattr(plan_confirm.command_words, "ACCOUNT_LEADS", plan_confirm.command_words.ACCOUNT_LEADS | {"no"})      # planted
    assert plan_confirm.choice_of(live(world), "no outlook") == 1


# --- a sender who may not read mail is told no account ---------------------------------------------------------------------------------------------


def test_a_sender_who_may_not_read_the_snapshots_gets_the_plain_question_and_no_account_names(world, snaps, clock):
    boxes(world, snaps, profiles=dict(PROFILES, plain=["read", "talk", "interpret"]))
    sender = SENDERS["plain"]
    reply, extras = call(world, "list my e-mails", sender=sender)
    assert reply == "I understood: list your e-mails. Shall I go ahead?" and "choices" not in extras["plan_confirm"] and "choices" not in live(world, sender)["state"]
    assert "Gmail" not in reply and "Outlook" not in reply
    reply, extras = call(world, "list my e-mails")
    assert reply == EN_QUESTION, "the sender who may read is asked as before"


def test_vacuity_with_the_reading_right_planted_the_same_sender_is_told_the_accounts(world, snaps, clock, monkeypatch):
    boxes(world, snaps, profiles=dict(PROFILES, plain=["read", "talk", "interpret"]))
    monkeypatch.setattr(item_refs, "may_read", lambda ctx, channel, sender=None: True)
    reply, _ = call(world, "list my e-mails", sender=SENDERS["plain"])
    assert reply == EN_QUESTION


# --- a list that does not fit one message -----------------------------------------------------------------------------------------------------------


def many(snaps, gmail_rows, outlook_rows, subject):
    snaps.providers.mail["gmail"] = [tsm.message(i, "2026-10-17T09:00:00Z", f"Pessoa Numero{i} <p{i}@clinic.example>", subject.format(i), "b") for i in range(1, gmail_rows + 1)]
    snaps.providers.mail["outlook"] = [tsm.message(i, "2026-10-17T09:00:00Z", f"Dan {i} <d{i}@work.example>", f"Report {i}", "b", source="outlook") for i in range(1, outlook_rows + 1)]
    snaps.refresh("inbox")
    snaps.refresh("work")
    ops_items._CHECKED.clear()


def rows_of(reply, heading):
    """The numbered lines under a heading (up to the blank line)."""
    block = reply.split(heading, 1)[1].split("\n\n", 1)[0]
    return [line for line in block.splitlines() if line[:1].isdigit()]


def test_a_list_of_all_accounts_that_would_be_cut_keeps_every_account_and_says_how_many_rows_did_not_fit(world, snaps, clock):
    boxes(world, snaps)
    many(snaps, 20, 5, "Assunto de tamanho comum numero {} da clinica")
    reply, _ = call(world, "list my e-mails", sender=READER)
    assert len(reply) <= 1800 and "…" not in reply, "whole rows only"
    assert len(rows_of(reply, "**Gmail**")) == 19 and len(rows_of(reply, "**Outlook**")) == 5
    assert "... 1 more did not fit in this message" in reply and reply.count("did not fit") == 1, "per account that was cut"


def test_long_rows_share_the_room_so_the_second_account_keeps_its_heading_and_its_first_rows(world, snaps, clock):
    boxes(world, snaps)
    many(snaps, 20, 5, "Assunto muito longo " + "x" * 80 + " {}")
    reply, _ = call(world, "list my e-mails", sender=READER)
    assert len(reply) <= 1800 and "…" not in reply
    gmail, outlook = rows_of(reply, "**Gmail**"), rows_of(reply, "**Outlook**")
    assert len(gmail) == 11 and len(outlook) == 5 and gmail[0].startswith("1. ") and outlook[0].startswith("1. "), "the room is shared: the second account keeps its heading and its rows"
    assert "... 9 more did not fit in this message" in reply and reply.count("did not fit") == 1


def test_a_cut_list_in_portuguese_says_it_in_portuguese(world, snaps, clock):
    boxes(world, snaps, "pt-BR")
    many(snaps, 20, 5, "Assunto muito longo " + "x" * 80 + " {}")
    reply, _ = call(world, "lista os emails", sender=READER)
    assert "... mais " in reply and " não couberam nesta mensagem" in reply and "**Outlook**" in reply      # validate: allow english-only -- the Portuguese words under test


def test_vacuity_a_render_that_ignores_the_budget_loses_the_second_account(world, snaps, clock, monkeypatch):
    boxes(world, snaps)
    many(snaps, 20, 5, "Assunto muito longo " + "x" * 80 + " {}")
    real = ops_items.render
    monkeypatch.setattr(ops_items, "render", lambda out, cfg, **kw: real(out, cfg, **dict(kw, budget=None)))      # planted: the old cut at 1,800 characters
    reply, _ = call(world, "list my e-mails", sender=READER)
    assert "**Outlook**" not in reply, "the hard cut removed the whole second account: the oracle above sees it"


def test_a_reply_that_fits_and_a_one_account_reply_are_not_touched(world, snaps, clock):
    boxes(world, snaps)
    many(snaps, 3, 2, "Assunto {}")
    reply, _ = call(world, "list my e-mails", sender=READER)
    assert "did not fit" not in reply and len(rows_of(reply, "**Gmail**")) == 3 and len(rows_of(reply, "**Outlook**")) == 2
    many(snaps, 20, 5, "Assunto muito longo " + "x" * 80 + " {}")
    _, extras = call(world, "list my e-mails")
    assert "did not fit" not in accept(world, extras, 0), "one account: the list is as it was (its own '... and N more' sentence)"


def test_a_calendar_in_a_reply_with_two_mail_sources_keeps_its_text(world, snaps, clock):
    """A call with no kind (the typed form) lists calendars and mail together: only the mail sources are set off and bold; the calendar's heading and rows are as they were."""
    boxes(world, snaps)
    snaps.calendar("agenda", "google", "primary", [tsm.event(1, id="ev1")])
    ctx = ops_core.context(world["path"])
    out = ops.items(world["path"], channel="terminal")
    names = {i: e["name"] for i, e in source_names.catalog(ctx).items()}
    text = ops_items.render(out, ctx["cfg"], phone=True, names=names)
    calendar_block = ops_items.render({**out, "sources": [e for e in out["sources"] if e["type"] == "calendar"]}, ctx["cfg"], phone=True, names=names)
    assert calendar_block in text and "**Agenda" not in text and "**Google" not in text, "the calendar text is byte for byte what it is alone"
    assert text.count("**Gmail**") == 1 and "\n\n**Outlook**" in text
