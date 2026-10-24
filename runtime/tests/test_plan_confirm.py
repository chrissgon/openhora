"""D5 on the operations side (package BL2a, limit L65, runtime/plan_confirm.py): a read or an act asked in words on a messaging app runs only after the person's OK of the plan code stated.

The real operations world (test_ops_natural.py), a stand-in model and a stand-in clock. The sentence is checked by phrase keys and values (the snapshot of full sentences per language is
test_plan_confirm_phrases_snapshot.py); every expectation is a literal of this file. The guards come first: a plan runs only after `take` matched its id AND its hash, research and the
acts always ask, nothing of a plan is run by a model's yes. Offline; invented names.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_plan_confirm.py
"""
from __future__ import annotations

import pytest

import standin_tree as st
from plan_confirm_kit import (ASKER, OFF, OWNER, PROF, SENDER_LIST, ZONE, accept, ok_of, op, ops, ops_natural, ops_say, operations, pending_items,  # noqa: F401
                              phrases, plan_confirm, question, say, spy_read, text, world, rig)  # noqa: F401

ops_research = st.load("ops_research")
ops_natural_writes = st.load("ops_natural_writes")


# --- the guards ------------------------------------------------------------------------------------------------------------------------------


def test_a_plan_runs_only_after_take_matched_its_id_and_its_hash_and_never_before(rig, monkeypatch):
    """Guard (probe 2): patch `take` to return nothing and nothing runs, whatever the line said."""
    reads = spy_read(rig)
    out = say(rig, OWNER, "mostra minha agenda")
    assert reads == [] and "plan_confirm" in out
    monkeypatch.setattr(plan_confirm, "take", lambda project, sender, plan_ok: None)
    gone = say(rig, OWNER, "sim", plan_ok=ok_of(out))
    assert gone["reply"] == phrases.text("PLAN_GONE", rig.cfg) and reads == []


def test_a_plan_is_bound_to_the_operation_its_arguments_the_sender_and_the_line(rig):
    """Guard (probe 3): change one argument of the live item and the question's own hash no longer opens it."""
    reads = spy_read(rig)
    out = say(rig, OWNER, "mostra minha agenda")
    item = pending_items.find(plan_confirm._key(rig.world["path"], OWNER), "plan-confirm")
    item["state"]["args"] = {"kind": "mail"}      # a change of the call after the question was drawn
    assert say(rig, OWNER, "sim", plan_ok=ok_of(out))["reply"] == phrases.text("PLAN_GONE", rig.cfg) and reads == []
    other = say(rig, OWNER, "mostra minha agenda")
    item = pending_items.find(plan_confirm._key(rig.world["path"], OWNER), "plan-confirm")
    item["state"]["said"] = "mostra meus emails"      # the line is bound too
    assert say(rig, OWNER, "sim", plan_ok=ok_of(other))["reply"] == phrases.text("PLAN_GONE", rig.cfg) and reads == []
    a, b = (plan_confirm.plan_sha256("p", "telegram:1", "items", {}, None, False, "a"), plan_confirm.plan_sha256("p", "telegram:2", "items", {}, None, False, "a"))
    c, d = (plan_confirm.plan_sha256("p", "telegram:1", "items", {}, None, False, "b"), plan_confirm.plan_sha256("q", "telegram:1", "items", {}, None, False, "a"))
    assert len({a, b, c, d}) == 4, "the sender, the line and the project each change the hash"


def test_research_ask_and_the_acts_always_ask_even_with_confirm_reads_off(rig):
    """Guard: the group turns off the question for the reads and for nothing else."""
    off = {"cfg": rig.cfg}
    for name in plan_confirm.ALWAYS + plan_confirm.ACTS:
        assert plan_confirm.needed(off, name, "messaging", OFF, False) is True, name
    assert plan_confirm.needed(off, "items", "messaging", OFF, False) is False, "a read runs at once for a sender who holds the group"
    assert plan_confirm.needed(off, "items", "messaging", OWNER, False) is True, "and asks for one who does not"
    assert plan_confirm.needed(off, "commands", "messaging", OWNER, False) is False, "the help is never asked"
    assert plan_confirm.needed(off, "remind", "messaging", OWNER, False) is False and plan_confirm.needed(off, "event-create", "messaging", OWNER, False) is False


def test_confirm_reads_off_is_reachable_only_through_accept_config_widen_and_is_in_no_default(world, monkeypatch):
    """Guard (probe 4): in no default, messaging only, kind only; a file that lists it is refused without the hash of its widening list."""
    assert not any("confirm-reads-off" in groups for groups in operations.DEFAULT_POLICY.values())
    assert "confirm-reads-off" not in operations.default_groups("messaging") and "confirm-reads-off" in operations.MESSAGING_ONLY_GROUPS and "confirm-reads-off" in operations.KIND_ONLY
    assert operations.group_refusal("page", "confirm-reads-off") is not None and operations.group_refusal("messaging", "confirm-reads-off") is None
    assert operations.permitted("say", "messaging", {"messaging": ["confirm-reads-off"]}, None, None) is False, "it never grants say"
    import json
    from pathlib import Path
    file = Path(world["path"]) / "docs" / "workbench" / "runtime.json"
    raw = json.loads(file.read_text())
    raw["channels"] = {"messaging": ["read", "talk", "confirm-reads-off"]}
    file.write_text(json.dumps(raw))
    shown = ops.config(world["path"])
    assert shown["widening_sha256"], "the file widens the channel: `config` shows the hash to type"
    with pytest.raises(ops.OpsError) as refused:
        ops.accept_config(world["path"], shown["sha256"])      # no --widen hash: refused, and the refusal lists the group with its text
    assert "confirm-reads-off" in str(refused.value) and operations.GROUP_TEXT["confirm-reads-off"] in str(refused.value)
    with pytest.raises(ops.OpsError):
        ops.accept_config(world["path"], shown["sha256"], widen="0" * 64)      # the wrong hash: refused
    ops.accept_config(world["path"], shown["sha256"], widen=shown["widening_sha256"])


def test_a_models_yes_never_runs_a_plan_only_the_senders_ok_does(rig, monkeypatch):
    """Guard: the model says `answer confirm yes` to the plan item of a search: one sentence asking to reply to the question, the plan still live and nothing run. A yes the model reads
    and code does not read in the line is refused by the check before anything."""
    calls = []
    monkeypatch.setattr(ops_research, "reply", lambda *a: calls.append(a) or "SEARCH-REPLY")
    rig.says["text"] = op("research", {"question": "weather in Lisbon tomorrow"})
    first = say(rig, OWNER, "will it rain in Lisbon, weather in Lisbon tomorrow")
    assert "plan_confirm" in first
    rig.says["text"] = text("answer", answers_item="i1", confirm="yes", slot="question", span="weather in Lisbon")
    out = say(rig, OWNER, "yes, weather in Lisbon")      # code reads the yes in what is left of the line once the span is out, so the check passes: it still runs nothing
    assert out["reply"] == phrases.text("PLAN_NOT_LAST", rig.cfg) and calls == []
    assert ops.plan_live(rig.world["path"], OWNER)["item"] == first["plan_confirm"]["item"], "the plan is kept for a yes the bridge can take"
    rig.says["text"] = text("answer", answers_item="i1", confirm="yes", slot="question", span="Lisbon")
    refused = say(rig, OWNER, "ok, go on, Lisbon")      # a yes the model reads and code does not: the check refuses it
    assert refused["reply"] == phrases.text("IX_ASK_AGAIN", rig.cfg) and calls == []


# --- the plan --------------------------------------------------------------------------------------------------------------------------------


def test_a_tier_1_read_asks_first_with_the_sentence_code_wrote_and_runs_nothing(rig):
    reads = spy_read(rig)
    out = say(rig, OWNER, "mostra minha agenda")
    assert out["reply"] == question(rig, "UNDERSTOOD_ITEMS_CALENDAR")
    assert reads == [] and out["plan_confirm"]["op"] == "items" and len(out["plan_confirm"]["sha256"]) == 64 and len(out["plan_confirm"]["item"]) == 6
    assert ops.plan_live(rig.world["path"], OWNER) == out["plan_confirm"]
    assert rig.calls == [], "no model ran for a tier-1 line"
    context = ops_natural.stored_line  # noqa: F841
    ctx = st.load("ops_core").context(rig.world["path"])
    saved = ctx["store"].messages_list(ctx["conn"], ops.CONVERSATION, limit=500)
    assert saved[-1]["text"] == phrases.text("PLAN_STORED", rig.cfg), "the conversation keeps a neutral word for the question"


def test_vacuity_without_the_check_the_read_runs_at_once(rig, monkeypatch):
    """The assertions of the test above fail when `needed` says False: the read runs and no question is asked."""
    reads = spy_read(rig)
    monkeypatch.setattr(plan_confirm, "needed", lambda *a, **k: False)
    out = say(rig, OWNER, "mostra minha agenda")
    assert out["reply"] == "READ-REPLY" and len(reads) == 1 and "plan_confirm" not in out


def test_a_sender_who_holds_confirm_reads_off_reads_at_once(rig):
    reads = spy_read(rig)
    out = say(rig, OFF, "mostra minha agenda")
    assert out["reply"] == "READ-REPLY" and len(reads) == 1 and "plan_confirm" not in out and ops.plan_live(rig.world["path"], OFF) is None


def test_the_page_and_the_terminal_read_at_once_with_no_plan(rig):
    reads = spy_read(rig)
    for channel in ("page", "chat"):
        out = say(rig, None, "mostra minha agenda", channel=channel)
        assert out["reply"] == "READ-REPLY" and "plan_confirm" not in out
    assert len(reads) == 2


def test_the_ok_runs_the_read_once_and_a_second_ok_a_wrong_hash_and_an_old_plan_run_nothing(rig):
    reads = spy_read(rig)
    out = say(rig, OWNER, "mostra minha agenda")
    done = say(rig, OWNER, "sim", plan_ok=ok_of(out))
    assert done["reply"] == "READ-REPLY" and len(reads) == 1
    assert say(rig, OWNER, "sim", plan_ok=ok_of(out))["reply"] == phrases.text("PLAN_GONE", rig.cfg) and len(reads) == 1, "a plan is taken once"
    again = say(rig, OWNER, "mostra minha agenda")
    wrong = {"item": ok_of(again)["item"], "sha256": "0" * 64}
    assert say(rig, OWNER, "sim", plan_ok=wrong)["reply"] == phrases.text("PLAN_GONE", rig.cfg) and len(reads) == 1
    assert ops.plan_live(rig.world["path"], OWNER) is not None, "a wrong hash pops nothing"
    rig.now[0] += plan_confirm.PLAN_TTL
    assert say(rig, OWNER, "sim", plan_ok=ok_of(again))["reply"] == phrases.text("PLAN_GONE", rig.cfg) and len(reads) == 1, "a plan older than 600 s is gone"
    other = say(rig, OWNER, "mostra minha agenda")
    assert say(rig, ASKER, "sim", plan_ok=ok_of(other))["reply"] == phrases.text("PLAN_GONE", rig.cfg), "another sender's OK is nothing"
    assert len(reads) == 1


def test_a_plan_ok_is_a_messaging_argument(rig):
    out = say(rig, OWNER, "mostra minha agenda")
    with pytest.raises(ops.OpsError) as error:
        ops.say(rig.world["path"], "sim", channel="page", plan_ok=ok_of(out))
    assert "messaging" in str(error.value)


def test_a_research_decision_asks_even_with_confirm_reads_off_and_runs_only_after_the_ok(rig, monkeypatch):
    """The model chose research (a stand-in route); `ops_research.reply` is not called before the OK and is called once after it."""
    calls = []
    monkeypatch.setattr(ops_research, "reply", lambda project, ctx, args, said, channel, sender, extras: calls.append(args) or "SEARCH-REPLY")
    rig.says["text"] = op("research", {"question": "weather in Lisbon tomorrow"})
    line = "will it rain in Lisbon, weather in Lisbon tomorrow"
    for who in (OWNER, OFF):
        calls.clear()
        out = say(rig, who, line)
        assert out["reply"] == question(rig, "UNDERSTOOD_RESEARCH", question="weather in Lisbon tomorrow", cap=phrases.decimal(f"{rig.cfg['research']['max_cost_usd']:.2f}", rig.cfg)), who
        assert calls == [] and out["plan_confirm"]["op"] == "research"
        done = say(rig, who, "yes", plan_ok=ok_of(out))
        assert done["reply"] == "SEARCH-REPLY" and calls == [{"question": "weather in Lisbon tomorrow"}]


def test_a_sender_who_lost_the_right_between_the_question_and_the_ok_gets_the_refusal_and_nothing_runs(rig):
    reads = spy_read(rig)
    out = say(rig, OWNER, "mostra minha agenda")
    narrower = dict(PROF, owner=["talk", "interpret"])      # `read` is gone
    accept(rig.world["path"], policies=narrower, messaging={"senders": SENDER_LIST})
    done = say(rig, OWNER, "sim", plan_ok=ok_of(out))
    refused = operations.refusal("items", "messaging", ops_natural.core.context(rig.world["path"])["cfg"]["channels"], sender=OWNER)
    assert refused and reads == []
    assert done["reply"] == st.load("phone_refusal").said(refused, "messaging", rig.cfg)


def test_an_effect_decision_is_never_a_plan_and_approve_in_words_sends_the_card_again(rig, monkeypatch):
    """The card is the OK of an effect: an E operation reaches `open_line`, never `plan_confirm.ask`; `approve` in words re-sends the decision's card."""
    opened = []
    real = ops_natural_writes.open_line
    monkeypatch.setattr(ops_natural_writes, "open_line", lambda project, ctx, said, channel, sender, extras, *, seed=None, hint=None: (
        opened.append((seed, hint)) or "CARD-REPLY") if (seed is not None or hint is not None) else real(project, ctx, said, channel, sender, extras))
    rig.says["text"] = op("event-cancel", {"event": "4"})
    out = say(rig, OWNER, "supprime l'evenement numero 4")
    assert out["reply"] == "CARD-REPLY" and "plan_confirm" not in out and opened == [(None, "event-cancel")]
    assert ops.plan_live(rig.world["path"], OWNER) is None
    decision = ops.say(rig.world["path"], "Which market first?", channel="page")["pending_id"]
    again = say(rig, OWNER, f"approve {decision}")
    assert again["resend"] == decision and "plan_confirm" not in again and again["reply"] == phrases.text("NAT_DECISION_CARD", rig.cfg, id=decision)


def test_a_greeting_the_help_and_a_reminder_ask_no_plan(rig):
    reads = spy_read(rig)
    for line in ("oi", "ajuda", "me lembra de pagar o aluguel"):
        out = say(rig, OWNER, line)
        assert "plan_confirm" not in out, line
        assert ops.plan_live(rig.world["path"], OWNER) is None
    assert reads == []
    for key in (key for key in phrases.TABLE["en"] if key.startswith("UNDERSTOOD_")):
        assert "aluguel" not in phrases.TABLE["en"][key], "no sentence holds a reminder's words (limit L51)"


def test_the_answer_to_a_draft_asks_no_plan(rig):
    """The reminder's own question is the platform's own question: its answer is exempt."""
    first = say(rig, OWNER, "me lembra de pagar o aluguel")
    assert "plan_confirm" not in first
    reply = say(rig, OWNER, "amanha as 9h")
    assert "plan_confirm" not in reply and ops.plan_live(rig.world["path"], OWNER) is None


def test_a_state_question_asks_and_the_ok_answers_it(rig):
    out = say(rig, OWNER, "como estamos?")
    assert out["reply"] == question(rig, "UNDERSTOOD_STATUS") and out["plan_confirm"]["op"] == "status"
    done = say(rig, OWNER, "sim", plan_ok=ok_of(out))
    assert done["reply"] == ops_say.state_reply(rig.world["path"], cfg=rig.cfg)


def test_a_bare_yes_the_bridge_could_not_take_is_never_an_ok_and_a_bare_no_drops_the_plan(rig):
    reads = spy_read(rig)
    say(rig, OWNER, "mostra minha agenda")
    kept = say(rig, OWNER, "sim")      # the bridge did not pass plan_ok: the line is not a reply to the question
    assert kept["reply"] == phrases.text("PLAN_NOT_LAST", rig.cfg) and reads == [] and ops.plan_live(rig.world["path"], OWNER) is not None
    dropped = say(rig, OWNER, "nao")
    assert dropped["reply"] == phrases.text("PLAN_DROPPED", rig.cfg) and ops.plan_live(rig.world["path"], OWNER) is None and reads == []


def test_any_other_line_drops_the_plan_and_a_new_read_asks_a_new_one(rig):
    reads = spy_read(rig)
    first = say(rig, OWNER, "mostra minha agenda")
    second = say(rig, OWNER, "quais arquivos voce tem?")
    assert second["reply"] == question(rig, "UNDERSTOOD_SOURCES") and second["plan_confirm"]["item"] != first["plan_confirm"]["item"]
    assert say(rig, OWNER, "sim", plan_ok=ok_of(first))["reply"] == phrases.text("PLAN_GONE", rig.cfg), "the first question is gone"
    say(rig, OWNER, "oi")
    assert ops.plan_live(rig.world["path"], OWNER) is None and reads == []


def test_ops_plan_drop_drops_the_plan_and_says_whether_one_was_live(rig):
    say(rig, OWNER, "mostra minha agenda")
    assert ops.plan_drop(rig.world["path"], OWNER) is True and ops.plan_drop(rig.world["path"], OWNER) is False and ops.plan_live(rig.world["path"], OWNER) is None


def test_every_read_of_the_table_but_the_help_has_a_sentence_and_the_sets_hold():
    reads = sorted(name for name, cls in plan_confirm.natural.CLASSES.items() if cls == "R" and name not in plan_confirm.NOT_ASKED)
    assert [name for name in reads if name not in plan_confirm.SENTENCES] == [], "a read with no sentence could never ask"
    assert set(plan_confirm.ALWAYS + plan_confirm.ACTS) <= set(plan_confirm.SENTENCES)
    for key in plan_confirm.SENTENCES.values():
        assert key in phrases.TABLE["en"] and key in phrases.TABLE["pt-BR"], key
