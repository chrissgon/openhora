"""A list narrowed by words, a day or a week, and the unread state (package CB-1 MAIL-QUERY, runtime/ops_items.py, catalog version 2).

"Tem algum email do banco essa semana?" must list the messages of the bank this week and nothing else: never the whole list, never a web search. The narrowing is code over the snapshot's
own index (`natural_writes_mail.match_words`, the local day of `received`, the index's `unread` flag, which CB-2 writes from the readers' `unread`), and a filter the
person stated is never dropped silently. Here the real snapshots behind the real runtime/item_refs.py (test_calendar_write.py's world and the stand-in providers of test_sources_mail.py),
the real natural-request path (`ops_natural.run`) and, for the line of a model, the interpreter's own `check` over the catalog of version 2. Every expectation is a literal of this file; sentences are
asserted by phrase key (T8), except one English snapshot of the header and the list. Each oracle that filters has a vacuity case that fails on a planted wrong result. Offline; invented names.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_items_match.py
"""
from __future__ import annotations

import pytest

import interpreter_kit as kit
import standin_tree as st
import test_sources_mail as tsm
from test_calendar_write import Snapshots, world  # noqa: F401  (the calendar world and its real snapshots)
from test_items_fresh import mail_reads, project  # noqa: F401
from test_items_useful import clock, inbox, snaps  # noqa: F401
from test_ops_natural_writes import READER  # noqa: F401

ops = st.load("ops")
ops_core = st.load("ops_core")
ops_items = st.load("ops_items")
ops_sources = st.load("ops_sources")
ops_interpret = st.load("ops_interpret")
ops_natural = st.load("ops_natural")
phrases = st.load("phrases")
natural = st.load("natural")
operations = st.load("operations")
plan_confirm = st.load("plan_confirm")
interpreter = st.load("interpreter")
interpreter_catalog = st.load("interpreter_catalog")
nwm = st.load("natural_writes_mail")

TODAY, LAST_WEEK = "2026-10-19T09:00:00Z", "2026-10-12T09:00:00Z"      # the clock of these tests is Monday 19/10 at 09:00 in the world's zone (-03:00); this week is 19/10 to 25/10
BANK = "Banco Aurora <avisos@banco-aurora.example>"
CLINIC = "Clínica Sorriso Leve <contato@sorrisoleve.example>"      # validate: allow english-only -- an invented sender with an accent
SHOP = "Loja Pequena <oi@lojapequena.example>"


def mails(flags=None):
    """Three messages: the bank's statement today, the clinic's confirmation today, the bank's invoice a week ago (numbers 1, 2, 3 in the order the snapshot lists them: newest first). `flags` is {message id:
    true or false}: the provider's read flag as the readers print it (`unread`, CB-2); a message with no entry has none, as a provider that printed none."""
    out = [tsm.message(1, when=TODAY, sender=BANK, subject="Extrato de outubro"),
           tsm.message(2, when="2026-10-19T08:00:00Z", sender=CLINIC, subject="Consulta confirmada"),
           tsm.message(3, when=LAST_WEEK, sender=BANK, subject="Fatura fechada")]
    return [dict(m, unread=flags[m["id"]]) if m["id"] in (flags or {}) else m for m in out]


def numbers(out, source=None):
    """The numbers listed, over every mail source (or one)."""
    return sorted(i["n"] for e in out["sources"] if e["type"] == "mail" and source in (None, e["source"]) for i in e["items"])


def listed(world, **more):
    return ops.items(world["path"], kind="mail", channel="terminal", **more)


def run_items(world, line, args, extras=None, sender=READER):
    """The natural request the interpreter also ends in, with the arguments a decision of version 2 carries."""
    ctx = ops_core.context(world["path"])
    return ops_natural.run(world["path"], ctx, "items", dict(args), line, "messaging", sender, dict(extras or {}))


def cfg_of(world):
    return ops_core.context(world["path"])["cfg"]


# --- by words ----------------------------------------------------------------------------------------------------------------------------------------


def test_the_words_of_the_bank_list_the_bank_only(world, snaps, clock):
    inbox(world, snaps, mails())
    assert numbers(listed(world)) == [1, 2, 3], "the control: with no filter the list is whole"
    out = listed(world, match="do banco")
    assert numbers(out) == [1, 3], "the sender's words, every one of them, and the number each message has in the snapshot"
    assert [i["line"] for i in out["sources"][0]["items"]] == ["avisos@banco-aurora.example · Extrato de outubro", "avisos@banco-aurora.example · Fatura fechada"]
    assert numbers(listed(world, match="banco extrato")) == [1], "every word must be held"
    assert numbers(listed(world, match="banco clinica")) == [], "no message holds both words"


def test_a_word_of_the_subject_finds_the_message(world, snaps, clock):
    inbox(world, snaps, mails())
    assert numbers(listed(world, match="consulta")) == [2]


def test_a_filter_that_matches_nothing_lists_nothing_and_is_not_the_whole_list(world, snaps, clock):
    inbox(world, snaps, mails())
    out = listed(world, match="zebra")
    assert numbers(out) == [] and out["sources"][0]["items"] == [] and "match_empty" not in out


def test_vacuity_a_match_that_is_ignored_lists_everything_so_the_oracle_sees_it(world, snaps, clock, monkeypatch):
    inbox(world, snaps, mails())
    monkeypatch.setattr(nwm, "match_words", lambda entries, words, newest=False: list(entries))
    assert numbers(listed(world, match="do banco")) == [1, 2, 3] != [1, 3]


def test_a_target_with_no_content_word_filters_nothing_and_the_reply_says_so(world, snaps, clock):
    inbox(world, snaps, mails())
    out = listed(world, match="os e-mails")
    assert numbers(out) == [1, 2, 3] and out["match_empty"] is True and out["filter"] == {"words": [], "unread": False}
    reply = run_items(world, "mostra os emails", {"match": "os e-mails"})
    assert phrases.text("NW_ITEMS_MATCH_EMPTY", cfg_of(world)) in reply.splitlines(), "said once, it never passes for a filtered list"
    assert reply.splitlines()[0].startswith("Gmail ("), "no header names a filter that was not applied"


def test_a_typed_match_is_a_few_words_and_a_list_of_words_is_checked(world, snaps, clock):
    inbox(world, snaps, mails())
    assert numbers(listed(world, match=["banco"])) == [1, 3]
    for wrong in (["Banco"], ["banco aurora"], [3], ["a", "b", "c", "d", "e", "f", "g"]):
        with pytest.raises(ops_core.OpsError):
            listed(world, match=wrong)


# --- by a day or a week -----------------------------------------------------------------------------------------------------------------------------


def test_this_week_and_the_bank_is_the_one_statement_and_the_header_names_the_filter(world, snaps, clock):
    inbox(world, snaps, mails())
    reply = run_items(world, "tem algum email do banco essa semana?", {"match": "do banco", "day_span": "essa semana"})
    lines = reply.splitlines()
    assert lines[0] == "Your e-mails with “banco” between 19/10 and 25/10:"
    assert lines[1].startswith("Gmail (read at ") and len(lines) == 3 and lines[2].startswith("1. ")
    assert "Extrato de outubro" in reply and "Fatura" not in reply and "Consulta" not in reply and "avisos@" not in reply, "a phone's line shows who and what, not the address"


def test_the_day_keeps_the_messages_that_came_in_that_local_day(world, snaps, clock):
    inbox(world, snaps, mails())
    today = ops_items.items_args("lista os emails de hoje", clock.moment, None, {"day": "hoje"})
    assert (today["first"], today["last"]) == ("2026-10-19", "2026-10-19")
    out = listed(world, first="2026-10-19", last="2026-10-19")
    assert numbers(out) == [1, 2] and out["range"] == {"first": "2026-10-19", "last": "2026-10-19"}
    assert numbers(listed(world, first="2026-10-12", last="2026-10-18")) == [3]
    assert numbers(listed(world, first="2026-10-19", last="2026-10-25", match="banco")) == [1], "the words and the week together"


def test_a_message_with_no_time_in_the_index_is_left_out_of_a_day_filter_counted_and_said_once(world, snaps, clock, monkeypatch):
    inbox(world, snaps, mails())
    real = ops_items.item_refs.read_index

    def no_time(ctx, source_id, **more):
        snapshot = real(ctx, source_id, **more)
        return dict(snapshot, entries=[dict(e, received=None) if e["id"] == "m2" else e for e in snapshot["entries"]])
    monkeypatch.setattr(ops_items.item_refs, "read_index", no_time)
    out = listed(world, first="2026-10-19", last="2026-10-19")
    assert numbers(out) == [1] and out["sources"][0]["nodate"] == 1
    reply = run_items(world, "emails de hoje", {"day_span": "hoje"})
    assert reply.splitlines()[-1] == phrases.text("NW_ITEMS_MATCH_NODATE", cfg_of(world), n=1)


def test_vacuity_a_day_that_is_ignored_lists_the_other_week_so_the_oracle_sees_it(world, snaps, clock, monkeypatch):
    inbox(world, snaps, mails())
    monkeypatch.setattr(ops_items, "_received_on", lambda entry: __import__("datetime").date(2026, 10, 19))
    assert numbers(listed(world, first="2026-10-19", last="2026-10-19")) == [1, 2, 3] != [1, 2]


# --- unread -----------------------------------------------------------------------------------------------------------------------------------------


def test_unread_keeps_the_messages_the_provider_flags_and_never_the_unknown(world, snaps, clock, monkeypatch):
    inbox(world, snaps, mails({"m1": True, "m2": False}))      # message 3 has no flag: not known
    assert numbers(listed(world, unread=True)) == [1], "true is kept; false and not known are not"
    assert numbers(listed(world, unread=True, match="banco")) == [1]
    assert numbers(listed(world, unread=True, match="clinica")) == []
    assert numbers(listed(world)) == [1, 2, 3], "the control: no flag asked, nothing is dropped"


def test_vacuity_an_ignored_unread_lists_the_read_messages_so_the_oracle_sees_it(world, snaps, clock, monkeypatch):
    inbox(world, snaps, mails({"m1": True, "m2": False, "m3": False}))
    monkeypatch.setattr(ops_items, "_read_state", lambda span: None)
    assert numbers(run_out(world, "emails nao lidos", {"state_span": "nao lidos"})) == [1, 2, 3] != [1]


def run_out(world, line, args):
    """The result of `items` for the arguments `items_args` makes of a decision's spans (the data the reply is made from)."""
    spans = ops_items.span_args_of(args)
    return ops.items(world["path"], channel="terminal", **ops_items.items_args(line, ops_natural._clock(), None, spans))


def test_a_box_with_no_flag_is_read_once_more_and_then_says_it_does_not_know(world, snaps, clock, monkeypatch):
    inbox(world, snaps, mails())
    before = len(mail_reads(snaps))
    reply = run_items(world, "emails nao lidos", {"state_span": "nao lidos"})
    assert len(mail_reads(snaps)) == before + 1, "one read under the turn's budget, never a loop"
    assert reply.splitlines()[0] == phrases.text("NW_ITEMS_MATCH_HEAD", cfg_of(world), filter=" " + phrases.text("NW_ITEMS_MATCH_UNREAD", cfg_of(world)))
    assert phrases.text("NW_ITEMS_UNREAD_UNKNOWN", cfg_of(world), name="Gmail") in reply.splitlines()
    assert "Extrato" not in reply and "Consulta" not in reply, "nothing is listed for a box whose state is not known"
    out = listed(world, unread=True)
    assert out["sources"][0]["unread_unknown"] is True and out["sources"][0]["items"] == []


def test_a_box_that_has_a_flag_is_not_read_again(world, snaps, clock, monkeypatch):
    inbox(world, snaps, mails({"m1": True, "m2": False, "m3": False}))
    before = len(mail_reads(snaps))
    run_items(world, "emails nao lidos", {"state_span": "nao lidos"})
    assert len(mail_reads(snaps)) == before


def test_the_refresh_that_fails_keeps_the_note_and_writes_one_closed_line(world, snaps, clock, monkeypatch, capfd):
    inbox(world, snaps, mails())
    snaps.providers.fail = tsm.Failure(reason="the provider said ZEBRA-SECRET")
    capfd.readouterr()
    reply = run_items(world, "emails nao lidos", {"state_span": "nao lidos"})
    seen = capfd.readouterr()
    assert seen.err == "items: refresh of inbox failed (mail)\n" and "ZEBRA" not in reply + seen.err + seen.out
    assert phrases.text("NW_ITEMS_UNREAD_UNKNOWN", cfg_of(world), name="Gmail") in reply.splitlines()
    assert "Extrato de outubro" not in seen.err + seen.out, "no word of a subject in a log"


def test_one_box_unknown_and_the_other_known_lists_the_known_one(world, snaps, clock):
    project(world)
    snaps.providers.mail["gmail"] = mails()
    snaps.providers.mail["outlook"] = [tsm.message(1, when=TODAY, sender=SHOP, subject="Pedido enviado", source="outlook", unread=True)]
    ops_sources.source_mail(world["path"], "inbox", "gmail:box=inbox;days=7;max=50")
    ops_sources.source_mail(world["path"], "caixa", "outlook:box=inbox;days=7;max=50")
    out = listed(world, unread=True)
    by_source = {e["source"]: e for e in out["sources"]}
    assert [i["n"] for i in by_source["caixa"]["items"]] == [1] and "unread_unknown" not in by_source["caixa"]
    assert by_source["inbox"]["unread_unknown"] is True and by_source["inbox"]["items"] == []


# --- the calendar -----------------------------------------------------------------------------------------------------------------------------------


def calendar(world, snaps):
    project(world)
    snaps.calendar("agenda", "google", "pat@example.com", [
        tsm.event(1, "2026-10-20T09:00:00-03:00", "2026-10-20T10:00:00-03:00", "Dentist", id="ev1", response="accepted"),
        tsm.event(2, "2026-10-21T14:00:00-03:00", "2026-10-21T15:00:00-03:00", "Budget review", id="ev2", response="accepted", online_meeting=True),
        tsm.event(3, "2026-10-22T09:00:00-03:00", "2026-10-22T10:00:00-03:00", "Dentist follow-up", id="ev3", response="accepted")])


def test_a_calendar_list_keeps_the_events_whose_title_holds_every_word(world, snaps, clock):
    calendar(world, snaps)
    out = ops.items(world["path"], kind="calendar", channel="terminal", match="dentist")
    assert sorted(i["n"] for i in out["sources"][0]["items"]) == [1, 3]
    out = ops.items(world["path"], kind="calendar", channel="terminal", match="dentist follow")
    assert sorted(i["n"] for i in out["sources"][0]["items"]) == [3]
    assert sorted(i["n"] for i in ops.items(world["path"], kind="calendar", channel="terminal")["sources"][0]["items"]) == [1, 2, 3]


def test_a_flag_of_the_snapshot_line_is_not_a_word_of_the_event(world, snaps, clock):
    calendar(world, snaps)
    assert ops.items(world["path"], kind="calendar", channel="terminal", match="meeting")["sources"][0]["items"] == [], "`online meeting` is the snapshot's flag, not the title"
    assert ops.items(world["path"], kind="calendar", channel="terminal", match="accepted")["sources"][0]["items"] == []


def test_stop_words_only_filter_a_calendar_nothing_and_the_reply_says_so(world, snaps, clock):
    calendar(world, snaps)
    out = ops.items(world["path"], kind="calendar", channel="terminal", match="o meu")
    assert len(out["sources"][0]["items"]) == 3 and out["match_empty"] is True


# --- the sentence of the plan, the correction, the corrected-or-unchanged comparison ------------------------------------------------------------------


def test_the_plan_sentence_names_the_words_the_day_and_the_unread_state(world, snaps, clock):
    inbox(world, snaps, mails())
    ctx = ops_core.context(world["path"])
    t = lambda key, **more: phrases.text(key, ctx["cfg"], **more)  # noqa: E731
    args = ops_items.items_args("tem algum email do banco essa semana", clock.moment, None, {"target": "do banco", "day": "essa semana"})
    assert args["kind"] == "mail" and args["match"] == ["banco"] and (args["first"], args["last"]) == ("2026-10-19", "2026-10-25") and "unread" not in args
    sentence = plan_confirm.understood(ctx, "items", args, "tem algum email do banco essa semana")
    assert sentence == t("UNDERSTOOD_ITEMS_MAIL_MATCH", words="banco") + phrases.localize_dates(t("UNDERSTOOD_ON_DAY", day="Mon 19/10/2026–Sun 25/10/2026"), ctx["cfg"])
    with_unread = plan_confirm.understood(ctx, "items", dict(args, unread=True), "x")
    assert with_unread == t("UNDERSTOOD_ITEMS_MAIL_MATCH", words="banco") + " " + t("UNDERSTOOD_ITEMS_UNREAD") + phrases.localize_dates(t("UNDERSTOOD_ON_DAY", day="Mon 19/10/2026–Sun 25/10/2026"), ctx["cfg"])
    assert plan_confirm.understood(ctx, "items", {"kind": "mail"}, "lista os emails") == t("UNDERSTOOD_ITEMS_MAIL"), "no filter: today's sentence"


def test_the_plan_hash_binds_the_words_and_the_unread_state(world, snaps, clock):
    base = {"kind": "mail", "match": ["banco"]}
    one = plan_confirm.plan_sha256("p", "s", "items", base, None, True, "x")
    assert one != plan_confirm.plan_sha256("p", "s", "items", {"kind": "mail", "match": ["clinica"]}, None, True, "x")
    assert one != plan_confirm.plan_sha256("p", "s", "items", dict(base, unread=True), None, True, "x")


def test_a_correction_keeps_the_old_words_unless_the_new_line_gives_a_target(clock):
    now = clock.moment
    old = {"kind": "mail", "match": ["banco"], "account": "google"}
    kept = ops_items.items_args("nao, so os nao lidos", now, old, {"state": "nao lidos"})
    assert kept["match"] == ["banco"] and kept["unread"] is True and kept["account"] == "google" and kept["kind"] == "mail"
    replaced = ops_items.items_args("nao, os da clinica", now, old, {"target": "da clinica"})
    assert replaced["match"] == ["clinica"] and "unread" not in replaced
    assert "match" not in ops_items.items_args("nao, os emails", now, {"kind": "mail"}, None), "nothing to keep, nothing invented"


def test_a_correction_that_adds_a_filter_is_not_unchanged(world, snaps, clock):
    state = {"args": {"kind": "mail", "match": ["banco"]}}
    plain = {"op": "items", "args": {}, "spans": {}}
    narrower = {"op": "items", "args": {"state_span": "nao lidos"}, "spans": {"state": "nao lidos"}}
    assert ops_interpret._unchanged(plain, state, "nao, os emails do banco") is True, "the control: nothing new, nothing changed"
    assert ops_interpret._unchanged(narrower, state, "nao, so os nao lidos") is False, "a stated filter is a change: the plan is not dropped as if it were a no"


def test_a_day_or_a_state_code_cannot_read_is_a_sentence_and_no_list(world, snaps, clock):
    inbox(world, snaps, mails())
    before = len(mail_reads(snaps))
    cfg = cfg_of(world)
    assert run_items(world, "emails de qualquer dia", {"day_span": "qualquer dia"}) == phrases.text("NW_ITEMS_MATCH_DAY", cfg)
    assert run_items(world, "emails lidos", {"state_span": "lidos"}) == phrases.text("NW_ITEMS_MATCH_STATE", cfg)
    assert run_items(world, "emails de hoje", {"day_span": "hoje"}) != phrases.text("NW_ITEMS_MATCH_DAY", cfg), "the control: a day it reads is a list"
    assert ops_items.unreadable_filter({"day": "qualquer dia"}, clock.moment) == "NW_ITEMS_MATCH_DAY" and ops_items.unreadable_filter({}, clock.moment) is None
    assert len(mail_reads(snaps)) == before, "no provider was read for a sentence"


# --- the line of a model, version 2 ------------------------------------------------------------------------------------------------------------------


@pytest.fixture
def v2(monkeypatch):
    """The catalog of version 2 and the views over it (`natural.views(2)`): what a line reaches after the flip, which CB-9 alone makes."""
    classes, table = natural.views(2)
    monkeypatch.setattr(natural, "CLASSES", classes)
    monkeypatch.setattr(natural, "NATURAL", table)
    catalog = interpreter_catalog.generate(2)
    monkeypatch.setattr(interpreter, "SERVED_SHA256", interpreter.catalog_sha256(catalog))      # the check refuses a catalog that is not the served one: the flip is CB-9's
    return catalog


def decide(catalog, line, slots):
    obj = {"v": 1, "kind": "op", "op": "items", "slots": slots}
    return interpreter.check(obj, line, None, catalog, kit.NOW, kit.ZONE, frozenset(("items",)))


def test_a_line_of_version_2_reaches_the_slots_and_a_line_of_version_1_does_not(monkeypatch):
    line = "tem algum email do banco essa semana?"
    classes1, table1 = natural.views(1)
    monkeypatch.setattr(natural, "CLASSES", classes1)
    monkeypatch.setattr(natural, "NATURAL", table1)
    assert natural.check_operation("items", {"target": "do banco"}, None, line)["ok"] is False, "L54: at version 1 the slot is not reachable"
    classes, table = natural.views(2)
    monkeypatch.setattr(natural, "CLASSES", classes)
    monkeypatch.setattr(natural, "NATURAL", table)
    assert natural.check_operation("items", {"target": "do banco", "day": "essa semana"}, None, line) == {
        "ok": True, "name": "items", "args": {"match": "do banco", "day_span": "essa semana"}, "when": None}


def test_the_model_names_the_bank_and_this_week_and_only_the_bank_is_listed(world, snaps, clock, v2):
    inbox(world, snaps, mails())
    line = "tem algum email do banco essa semana?"
    decision = decide(v2, line, {"target": "do banco", "day": "essa semana"})
    assert decision["kind"] == "op" and decision["args"] == {"match": "do banco", "day_span": "essa semana"} and decision["spans"] == {"target": "do banco", "day": "essa semana"}
    reply = run_items(world, line, decision["args"], {"plan_words": decision["spans"]})
    assert "Gmail" in reply and "1. " in reply and "2. " not in reply, "one message of the bank this week"
    assert reply.splitlines()[0].startswith("Your e-mails with “banco” between 19/10 and 25/10")
    assert "Fatura" not in reply and "Consulta" not in reply


def test_vacuity_without_the_slots_in_the_view_the_model_cannot_name_the_bank(world, snaps, clock, monkeypatch):
    version1 = interpreter_catalog.generate(1)
    monkeypatch.setattr(interpreter, "SERVED_SHA256", interpreter.catalog_sha256(version1))      # CB-9: the served catalog is version 2; the catalog of version 1 must be the one the check accepts for the control to be a refusal of the slot
    classes1, table1 = natural.views(1)
    monkeypatch.setattr(natural, "CLASSES", classes1)
    monkeypatch.setattr(natural, "NATURAL", table1)
    decision = decide(version1, "tem algum email do banco essa semana?", {"target": "do banco"})
    assert decision["kind"] != "op", decision


def test_the_row_of_the_registry_carries_the_three_slots_of_version_2():
    rec = {r["op"]: r for r in st.load("registry").rows(2)}["items"]
    assert {slot: (spec["kind"], spec["param"], spec["since"]) for slot, spec in rec["slots"].items()} == {
        "target": ("span", "match", 2), "day": ("span", "day_span", 2), "state": ("span", "state_span", 2)}
    assert {r["op"]: r for r in st.load("registry").rows(1)}["items"]["slots"] == {}
    assert operations.LINE_CATALOG == 2, "CB-9 raised it"


# --- a target that names a mailbox is a source or a question, never a word filter (CB-9, round 2) --------------------------------------------------------------------------------------
# DeepSeek answered "liste os e-mails que chegaram hoje na caixa do trabalho" with the target "caixa do trabalho": as a word filter it keeps the messages that hold both words and shows a list that
# looks filtered while it is not. A span with a mailbox noun is the one source it names, or a question that lists the mail sources; a span of one source's words alone is that source.


def mailbox_reply(world, target, source_id="inbox"):
    return run_items(world, "liste os e-mails que chegaram hoje na caixa do trabalho", {"match": target})      # validate: allow english-only -- the Portuguese line under test


def test_a_target_with_a_mailbox_noun_that_names_no_source_is_a_question_and_no_list(world, snaps, clock):
    inbox(world, snaps, mails())
    names = ", ".join(e["name"] for e in st.load("source_names").catalog(ops_core.context(world["path"])).values() if e["type"] == "mail")
    reply = mailbox_reply(world, "caixa do trabalho")      # validate: allow english-only -- the Portuguese words under test
    assert names and reply == phrases.text("NW_ITEMS_MAILBOX", cfg_of(world), names=names), reply
    assert "Extrato de outubro" not in reply and "Consulta confirmada" not in reply


def test_a_target_that_names_a_source_is_that_source_and_filters_no_word(world, snaps, clock):
    inbox(world, snaps, mails(), source="trabalho")
    for target in ("caixa do trabalho", "trabalho"):      # validate: allow english-only -- the Portuguese words under test
        reply = mailbox_reply(world, target)
        assert "Extrato de outubro" in reply and "Consulta confirmada" in reply and "with “" not in reply and "No e-mail" not in reply, (target, reply)


def test_a_span_of_a_sender_or_a_subject_is_still_a_word_filter(world, snaps, clock):
    inbox(world, snaps, mails(), source="trabalho")
    reply = run_items(world, "tem algum email do banco essa semana?", {"match": "do banco"})      # validate: allow english-only -- the Portuguese line under test
    assert "with “banco”" in reply and "Extrato de outubro" in reply and "Consulta confirmada" not in reply, reply


def test_vacuity_without_the_mailbox_rule_the_box_becomes_a_word_filter(world, snaps, clock, monkeypatch):
    inbox(world, snaps, mails())
    monkeypatch.setattr(ops_items, "mailbox_target", lambda ctx, spans: None)
    reply = mailbox_reply(world, "caixa do trabalho")      # validate: allow english-only -- the Portuguese words under test
    assert "with “caixa trabalho”" in reply and "No e-mail with “caixa trabalho”" in reply, "a filter on `caixa` and `trabalho`, which no message holds: an empty list that looks filtered"
