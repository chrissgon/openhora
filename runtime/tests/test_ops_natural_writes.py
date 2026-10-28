"""The card-opening path of the natural writes (package NR-5, runtime/ops_natural_writes.py with its family modules): a plain line opens the card of the exact content of a
write to the person's own accounts, through the operation's own function, and executes nothing. Over the REAL operations layer and the W1 stand-in writers on loopback
(test_calendar_write.py's world: no Google or Microsoft host is called), a stand-in clock (Monday 2026-10-19 09:00 at -03:00) and no model. Every name, address and file is
invented. The limit held here is L61 (contracts/runtime.md). The files family has its own file, test_ops_natural_writes_files.py; the drafts, the bridge and the privacy have
theirs. The Portuguese lines are in natural_writes_cases_pt_br.py.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_ops_natural_writes.py
"""
from __future__ import annotations

from phone_literals import PLAIN_REFUSAL  # noqa: E402

import json

import pytest

import standin_tree as st
from test_calendar_write import GRAPH_SEEDED, SEEDED, install_item_refs, rows, seed_google, seed_graph, world  # noqa: F401  (the calendar world)
from test_channel_grants import accept
from test_reminders import Clock

ops = st.load("ops")
ops_core = st.load("ops_core")
ops_natural = st.load("ops_natural")
ops_natural_writes = st.load("ops_natural_writes")
drafts = st.load("drafts")
account_start = st.load("account_start")
phrases = st.load("phrases")
project_config = st.load("project_config")

SENDER, READER = "telegram:830461975213", "telegram:5151"
PLAIN = "telegram:6161"
BLIND = "telegram:7171"
GROUPS = ["read", "talk", "calendar-write"]
PROFILES = {"owner": GROUPS + ["mail-organize"], "reader": GROUPS + ["ask-mail", "mail-organize"], "plain": ["read", "talk"], "blind": ["talk", "calendar-write"]}      # mail-organize: for the stand-in family of test_natural_writes_family.py
IDS = {"owner": "830461975213", "reader": "5151", "plain": "6161", "blind": "7171"}
OPEN = "waits for your approval"


@pytest.fixture
def clock(monkeypatch):
    return Clock(monkeypatch, wall="2026-10-19 09:00")


@pytest.fixture
def spy(monkeypatch):
    """Every start of an account write: (kind, args, the keywords), the real start still running."""
    seen = []
    real = account_start.start

    def start(project, kind, args, **kw):
        seen.append((kind, dict(args), dict(kw)))
        return real(project, kind, args, **kw)
    monkeypatch.setattr(account_start, "start", start)
    return seen


@pytest.fixture(autouse=True)
def forget():
    drafts.clear()
    yield
    drafts.clear()


def policy(world, page=("read", "calendar-write")):
    """Four listed senders, each with a profile of its own (a messaging channel never holds `ask-mail`, only a sender does), and a page that may ask."""
    path = world["path"] + "/docs/workbench/runtime.json"
    raw = json.loads(open(path).read())
    raw["policies"] = PROFILES
    raw["channels"] = {"page": list(page)}
    raw["messaging"] = {"senders": {"telegram": [{"id": IDS[name], "policy": name} for name in PROFILES]}}
    open(path, "w").write(json.dumps(raw))
    shown = ops.config(world["path"])
    ops.accept_config(world["path"], shown["sha256"], widen=shown["widening_sha256"])


def phone(world, text, sender="telegram:830461975213"):
    return ops.natural_write(world["path"], text, channel="messaging", sender=sender)


def say(world, text, channel=None, sender=None):
    return ops.say(world["path"], text, channel=channel, sender=sender)


def body(world, out):
    return ops.pending(world["path"], out["resend"])["body"]


# --- the order of 5.1 ------------------------------------------------------------------------------------------------------------------------------


def test_a_plain_line_opens_the_card_of_the_event_on_a_phone_and_writes_nothing(world, clock, spy):
    policy(world)
    out = phone(world, "marca dentista quinta às 10h no google")
    assert out["asked"] is False and out["resend"] and OPEN in out["reply"]
    lines = body(world, out).splitlines()
    assert "Title: dentista" in lines and "When: Thu 22/10/2026 10:00-11:00 (America/Sao_Paulo)" in lines and "Account: google (pat@example.com)" in lines
    assert world["google"].requests == [] and world["graph"].requests == [], "a line opens a card: the approval writes"
    assert [kind for kind, _, _ in spy] == ["calendar-event"]


def test_the_terminal_shell_gets_the_cards_lines_and_the_approve_command_with_the_exact_hash_and_the_page_gets_the_notice(world, clock):
    policy(world)
    terminal = say(world, "marca dentista quinta às 10h no google")["reply"]
    number = int(terminal.split("#")[1].split()[0])
    item = ops.pending(world["path"], number)
    assert "Title: dentista" in terminal and item["payload_sha256"] in terminal and "cli.py approve" in terminal
    on_page = say(world, "marca dentista sexta às 10h no google", channel="page")["reply"]
    assert OPEN in on_page and "cli.py approve" not in on_page, "the pending card is the page's"


def test_the_open_calls_the_operations_own_function_with_the_carrying_channel_and_sender_as_the_typed_command_does(world, clock, spy):
    policy(world)
    phone(world, "marca dentista quinta às 10h no google")
    ops.event_create(world["path"], "google", "dentista", "2026-10-22T10:00", channel="messaging", sender=SENDER)
    written, typed = spy
    assert written[0] == typed[0] and written[1] == typed[1] and written[2] == typed[2], (written, typed)
    assert written[2]["channel"] == "messaging" and written[2]["sender"] == SENDER and written[2]["key_words"] == "event-create"


@pytest.mark.parametrize("channel, sender, carried", [(None, None, "terminal"), ("page", None, "page"), ("messaging", SENDER, "messaging")])
def test_the_card_opens_from_every_channel_that_carries_the_line(world, clock, spy, channel, sender, carried):
    policy(world)
    reply = say(world, "marca dentista quinta às 10h no google", channel=channel, sender=sender)["reply"]
    assert OPEN in reply and spy and spy[-1][2]["channel"] == carried, "the conversation's shell is the terminal's equal"


@pytest.mark.parametrize("line", ["marca dentista quinta às 10h no google", "remarca o evento 2 para sexta às 15h", "cancela o evento 4",
                                  "cria um arquivo chamado ideias.md com o texto: comprar tinta", "substitui o texto do arquivo lista de compras por: pão, leite",
                                  "salva esse pdf no drive"])
def test_a_profile_without_the_operations_group_gets_the_typed_sentence_and_nothing_starts(world, clock, spy, line):
    policy(world)
    out = phone(world, line, PLAIN)
    assert out["reply"] == PLAIN_REFUSAL and spy == [] and rows(world) == ([], [])


def test_a_messaging_sender_who_cannot_be_sent_a_card_gets_a_sentence_and_nothing_is_opened(world, clock, spy):
    policy(world)
    out = phone(world, "marca dentista quinta às 10h no google", BLIND)
    assert out["reply"] == phrases.text("NW_NO_CARDS", None) and spy == [] and rows(world) == ([], [])


def test_the_mcp_mode_never_opens_a_write_from_a_line(world, clock, spy):
    ctx = ops_core.context(world["path"])
    assert ops_natural_writes.open_line(world["path"], ctx, "marca dentista quinta às 10h no google", "mcp", None, {}) is None
    assert ops_natural.peek(ctx, "marca dentista quinta às 10h no google", "mcp", None) is False and spy == [] and rows(world) == ([], [])


def test_a_refusal_of_the_start_is_the_reply_and_leaves_no_request_behind(world, clock, monkeypatch):
    policy(world)
    seed_graph(world, attendees=[{"emailAddress": {"address": "guest@example.org"}}])      # a meeting: the start of a removal refuses it (an Outlook removal itself is on since S21)
    install_item_refs(world, monkeypatch, {"agenda#1": {"id": GRAPH_SEEDED, "calendar": "default", "account": "microsoft"}})
    out = say(world, "cancela o evento 1 no outlook")
    assert out["reply"].startswith("error: ") and "other attendees" in out["reply"], out["reply"]
    tasks, pending = rows(world)
    assert pending == [] and {t["state"] for t in tasks} <= {"cancelled"}
    assert not [r for r in world["graph"].graph_requests() if r["method"] != "GET"]


# --- the slots, and what is asked back --------------------------------------------------------------------------------------------------------------


def test_two_accounts_and_no_default_are_asked_and_the_answer_is_a_number_or_a_word(world, clock, spy):
    policy(world)
    first = phone(world, "marca dentista quinta às 10h")
    assert first["asked"] is True and first["reply"].startswith("Which account?\n1. Google (pat@example.com)\n2. Microsoft") and spy == []
    second = phone(world, "2")
    assert second["resend"] and "Account: microsoft (casey.rivera@mail.example)" in body(world, second)
    phone(world, "marca dentista sexta às 10h")
    third = phone(world, "google")
    assert "Account: google (pat@example.com)" in body(world, third)


def test_a_default_account_in_the_configuration_settles_it_and_is_a_widening_of_the_terminal(world, clock, spy):
    path = world["path"] + "/docs/workbench/runtime.json"
    raw = json.loads(open(path).read())
    raw["accounts"]["default"] = "microsoft"
    open(path, "w").write(json.dumps(raw))
    shown = ops.config(world["path"])
    assert any("default-account=microsoft" in w["group"] for w in shown["widening"]), "a default account is accepted with --widen, like a default calendar"
    ops.accept_config(world["path"], shown["sha256"], widen=shown["widening_sha256"])
    assert project_config.account_default(ops_core.context(world["path"])["cfg"]) == "microsoft"
    policy(world)
    out = phone(world, "marca dentista quinta às 10h")
    assert out["asked"] is False and "Account: microsoft" in body(world, out)
    named = phone(world, "marca dentista sexta às 10h no google")
    assert "Account: google" in body(world, named), "a service word in the line beats the default"


def test_a_default_that_names_an_account_the_file_does_not_list_is_refused():
    with pytest.raises(project_config.ConfigError):
        project_config._accounts({"google": {"address": "pat@example.com"}, "default": "microsoft"})
    with pytest.raises(project_config.ConfigError):
        project_config._accounts({"google": {"address": "pat@example.com"}, "default": "yahoo"})
    assert project_config._accounts({"google": {"address": "pat@example.com"}, "default": "google"})["default"] == "google"


def test_a_calendar_the_account_does_not_list_is_answered_with_the_ones_it_lists_never_a_near_match(world, clock, spy):
    policy(world)
    out = phone(world, "marca dentista quinta às 10h na agenda traballho no google")
    assert out["asked"] and "I do not have the calendar 'traballho'" in out["reply"] and "personal, side" in out["reply"] and spy == []
    done = phone(world, "side")
    assert "Calendar: side" in body(world, done)
    named = phone(world, "marca dentista sexta às 10h na agenda side no google")
    assert "Calendar: side" in body(world, named)


def test_a_missing_time_is_asked_and_the_answer_fills_the_start(world, clock, spy):
    policy(world)
    first = phone(world, "cria um evento viagem sexta no google")
    assert first["asked"] and first["reply"].startswith("Fri 23/10: at what time?") and spy == []
    done = phone(world, "8h")
    assert "When: Fri 23/10/2026 08:00-09:00" in body(world, done) and "Title: viagem" in body(world, done)


def test_a_missing_title_is_asked_with_the_day_and_the_answer_is_the_title_verbatim(world, clock, spy):
    policy(world)
    first = phone(world, "marca quinta às 10h no google")
    assert first["asked"] and "Thu 22/10" in first["reply"] and spy == []
    done = phone(world, "Dentista da Júlia, às pressas")
    assert "Title: Dentista da Júlia, às pressas" in body(world, done)


def test_a_time_the_engine_can_read_two_ways_is_asked_and_the_pick_opens_the_card(world, clock, spy):
    policy(world)
    first = phone(world, "marca dentista quinta às 9 no google")
    assert first["asked"] and spy == []
    done = phone(world, "21h")
    assert "Thu 22/10/2026 21:00" in body(world, done)


def test_a_range_gives_the_end_and_an_end_before_the_start_is_asked_not_swapped(world, clock, spy):
    policy(world)
    ranged = phone(world, "marca yoga amanhã das 7h às 8h30 no google")
    assert "Tue 20/10/2026 07:00-08:30" in body(world, ranged)
    first = phone(world, "marca yoga amanhã das 8h às 7h no google")
    assert first["asked"] and "after the start" in first["reply"]
    late = phone(world, "6h")
    assert late["asked"] is True, "an end before the start is asked again"
    done = phone(world, "9h")
    assert "Tue 20/10/2026 08:00-09:00" in body(world, done)


def test_an_all_day_event_with_no_day_asks_the_day_and_with_one_has_no_hour(world, clock, spy):
    policy(world)
    first = phone(world, "marca na agenda viagem dia todo no google")
    assert first["asked"] and "Which day" in first["reply"]
    done = phone(world, "sexta")
    assert "Fri 23/10/2026" in body(world, done) and "10:00" not in body(world, done)
    direct = phone(world, "marca feira de livros sábado dia todo no google")
    assert "Sat 24/10/2026" in body(world, direct)


def test_a_line_that_repeats_is_refused_in_words_and_opens_nothing_at_catalog_version_1(world, clock, spy, monkeypatch):
    monkeypatch.setattr(st.load("operations"), "LINE_CATALOG", 1)      # CB-9: since version 2 the closed form does not claim it (the next test)
    policy(world)
    out = phone(world, "marca yoga toda segunda às 7h no google")
    assert out["reply"] == phrases.text("NW_RECURRING_EVENT", None) and spy == [] and not drafts.count()


def test_since_catalog_version_2_a_line_that_repeats_is_no_write_form_and_opens_nothing_here(world, clock, spy, monkeypatch):
    monkeypatch.setattr(st.load("operations"), "LINE_CATALOG", 2)
    policy(world)
    out = phone(world, "marca yoga toda segunda às 7h no google")
    assert out["reply"] is None and spy == [] and not drafts.count(), "the caller handles it as any plain line: the interpreter reads it"


def test_a_reading_the_engine_is_unsure_of_opens_the_card_with_a_line_that_says_which_part_to_check(world, clock):
    policy(world)
    out = phone(world, "marca festa de natal quinta às 10h no google")
    assert out["reply"].startswith("Check the date: I understood Thu 22/10 at 10:00.") and OPEN in out["reply"]


def test_a_time_of_day_that_has_passed_says_so_before_the_card(world, clock):
    policy(world)
    out = phone(world, "marca dentista às 8h no google")
    assert out["reply"].startswith("08:00 today has passed: tomorrow, Tue 20/10, at 08:00") and "Tue 20/10/2026 08:00" in body(world, out)


def test_a_moment_is_pinned_when_the_slots_are_filled_not_when_the_card_is_approved(world, clock):
    policy(world)
    out = phone(world, "marca dentista daqui a 2 horas no google")
    assert "Mon 19/10/2026 11:00" in body(world, out)
    clock.set("2026-10-19 09:30")
    again = phone(world, "marca dentista daqui a 2 horas no google")
    assert "Mon 19/10/2026 11:30" in body(world, again)


# --- the references: a change and a removal ---------------------------------------------------------------------------------------------------------


def test_a_change_names_the_event_by_the_number_in_the_line_and_the_card_shows_it_as_it_is_now(world, clock, monkeypatch):
    policy(world)
    seed_google(world)
    install_item_refs(world, monkeypatch, {"agenda#2": {"id": SEEDED, "calendar": "pat@example.com", "account": "google"}})
    out = phone(world, "remarca o evento 2 para sexta às 15h", READER)
    lines = body(world, out).splitlines()
    assert any(line.startswith("After: When: Fri 23/10/2026 15:00") for line in lines)
    removal = phone(world, "cancela o evento 2", READER)
    assert "Removing, title: Dentist" in body(world, removal)
    assert world["google"].events and not [r for r in world["google"].requests if r["method"] in ("PATCH", "DELETE")], "a card writes nothing"


def test_a_removal_with_no_number_asks_which_event_and_the_answer_is_a_number(world, clock, monkeypatch):
    policy(world)
    seed_google(world)
    install_item_refs(world, monkeypatch, {"agenda#3": {"id": SEEDED, "calendar": "pat@example.com", "account": "google"}})
    first = phone(world, "cancela a reunião", READER)
    assert first["asked"] and "Which event?" in first["reply"]
    done = phone(world, "3", READER)
    assert "Removing, title: Dentist" in body(world, done)


def test_two_calendar_sources_are_listed_and_asked_and_none_is_said(world, clock, monkeypatch):
    policy(world)
    none = phone(world, "cancela o evento 2", READER)
    assert none["reply"] == phrases.text("NW_NO_CALENDAR_SOURCE", None)
    seed_google(world)
    install_item_refs(world, monkeypatch, {"agenda#2": {"id": SEEDED, "calendar": "pat@example.com", "account": "google"},
                                           "trabalho#2": {"id": SEEDED, "calendar": "side.calendar@example.com", "account": "google"}})
    asked = phone(world, "cancela o evento 2", READER)
    assert asked["asked"] and (phrases.text("NW_ASK_SOURCE", None) + "\n1. " + phrases.text("NW_ITEMS_NAME_CAL", None, service="Google") + " 1\n2. " + phrases.text("NW_ITEMS_NAME_CAL", None, service="Google") + " 2") in asked["reply"]


def test_a_sender_who_may_not_read_a_snapshot_is_told_so_and_nothing_of_the_calendar_is_named(world, clock, monkeypatch, spy):
    policy(world)
    seed_google(world)
    install_item_refs(world, monkeypatch, {"agenda-privada#2": {"id": SEEDED, "calendar": "pat@example.com", "account": "google"}})
    out = phone(world, "cancela o evento 2")
    assert out["reply"] == phrases.text("NW_REF_NOT_READABLE", None) and "agenda-privada" not in out["reply"] and spy == []
    assert OPEN in phone(world, "cancela o evento 2", READER)["reply"]


# --- the limit --------------------------------------------------------------------------------------------------------------------------------------


def test_limit_61_a_line_opens_a_write_only_as_its_card_with_every_slot_from_code(world, clock, monkeypatch, spy):
    """No effect, writer or approval is reached from a line; each start gets the arguments the code read."""
    called = []
    real_approve = ops.approve
    monkeypatch.setattr(ops, "approve", lambda *a, **k: (called.append("ops.approve"), real_approve(*a, **k))[1])
    steps_effects = st.load("ops_step_effects")
    for name in [n for n in ("approve", "execute", "run_effect") if hasattr(steps_effects, n)]:
        real = getattr(steps_effects, name)
        monkeypatch.setattr(steps_effects, name, lambda *a, _n=name, _r=real, **k: (called.append(_n), _r(*a, **k))[1])
    policy(world)
    for line in ("marca dentista quinta às 10h no google", "cria um evento viagem sexta no google", "8h", "marca quinta às 11h no google", "Café com a Bia"):
        phone(world, line)
    assert called == [] and world["google"].requests == [] and world["graph"].requests == []
    assert len(spy) == 3
    for kind, args, keywords in spy:
        assert kind == "calendar-event" and args["operation"] == "create" and keywords["channel"] == "messaging" and args["account"] == "google"
        assert args["title"] and args["start"][:10] in {"2026-10-22", "2026-10-23"}
# chunk:ops_more


def test_a_write_the_router_named_is_read_again_by_code_and_its_when_is_never_used(world, clock, spy):
    policy(world)
    ctx = ops_core.context(world["path"])
    extras = {}
    out = ops_natural.run_routed(world["path"], ctx, {"name": "event-create", "args": {}, "when": None}, "cria um evento viagem no google", "messaging", SENDER, extras)
    assert spy == [] and "When is the event" in out, "a time the line's words do not give is asked, never the router's"
    refused = ops_natural.run_routed(world["path"], ctx, {"name": "event-create", "args": {}, "when": "2026-10-23 08:00"}, "cria um evento viagem no google", "messaging", SENDER, {})
    assert spy == [] and "could not match" in refused, "a router time the line does not hold is not believed at all"
    again = ops_natural_writes.open_line(world["path"], ctx, "marca dentista quinta às 10h no google", "messaging", SENDER, {}, hint="event-create")
    assert spy[-1][1]["start"] == "2026-10-22T10:00" and OPEN in again
    assert ops_natural_writes.open_line(world["path"], ctx, "marca dentista quinta às 10h no google", "messaging", SENDER, {}, hint="file-save") is None
    spy.clear()
    via_router = ops_natural.run_routed(world["path"], ctx, {"name": "event-create", "args": {}, "when": None}, "marca dentista quinta às 10h no google", "messaging", SENDER, {})
    assert OPEN in via_router and spy[-1][1]["title"] == "dentista"


def test_a_line_in_words_never_uses_a_standing_approval_and_never_approves(world, clock, monkeypatch):
    called = []
    for name in ("execute_under_policy", "approve_policy", "standing", "approve"):
        real = getattr(ops, name)
        monkeypatch.setattr(ops, name, lambda *a, _n=name, _r=real, **k: (called.append(_n), _r(*a, **k))[1])
    policy(world)
    for line in ("marca dentista quinta às 10h no google", "cria um evento viagem sexta no google", "8h"):
        phone(world, line)
        say(world, line)
    assert called == [] and world["google"].requests == []


@pytest.mark.parametrize("line, title, start, end", [
    ("marca reunião quinta 13-15h no google", "reunião", "2026-10-22T13:00", "2026-10-22T15:00"),
    ("marca reunião quinta das 10 às 11h no google", "reunião", "2026-10-22T10:00", "2026-10-22T11:00"),
    ("marca reunião quinta das 10 às 11 no google", "reunião", "2026-10-22T10:00", "2026-10-22T11:00"),
    ("add to my calendar meeting Thursday 1-2pm on google", "meeting", "2026-10-22T13:00", "2026-10-22T14:00"),
])
def test_a_range_written_with_bare_numbers_is_read_as_a_range_and_the_card_shows_both_ends(world, clock, spy, line, title, start, end):
    policy(world)
    out = phone(world, line)
    assert OPEN in out["reply"] and spy[-1][1]["title"] == title and spy[-1][1]["start"] == start and spy[-1][1]["end"] == end


def test_a_number_left_in_the_title_is_checked_before_the_card_and_the_title_is_never_cut_silently(world, clock, spy):
    policy(world)
    out = phone(world, "marca prova 20 às 14h no google")
    assert out["reply"].startswith("Check the date: I understood") and spy[-1][1]["title"] == "prova 20"


def test_a_time_that_has_passed_today_is_checked_before_the_card(world, clock, spy):
    policy(world)
    out = phone(world, "marca dentista hoje às 8h no google")
    assert out["reply"].startswith("Check the date: I understood") and spy[-1][1]["start"] == "2026-10-19T08:00"


def test_a_date_that_does_not_exist_is_asked_again_with_a_plain_sentence_and_the_time_is_kept(world, clock, spy):
    policy(world)
    for line in ("marca dentista 31/02 às 10h no google", "marca dentista 10/20 às 10h no google"):
        out = phone(world, line)
        assert out["asked"] and out["reply"] == "That date does not exist. Which day is the event?" and spy == [] and "error" not in out["reply"]
        done = phone(world, "sexta")
        assert OPEN in done["reply"] and spy[-1][1]["start"] == "2026-10-23T10:00" and spy[-1][1]["title"] == "dentista"
        spy.clear()


def test_a_change_line_that_is_no_change_form_is_answered_by_number_and_never_becomes_a_new_event(world, clock, spy):
    policy(world)
    for line in ("remarca o evento 2 para quinta às 10h na sala", "remarca o evento 0 para quinta às 10h"):          # a typed number form that is not one: the hint says how to name it
        out = phone(world, line)
        assert out["asked"] is False and out["reply"] == phrases.text("NW_CHANGE_BY_NUMBER", None) and spy == [] and drafts.count() == 0
    assert "event 2" in phrases.text("NW_CHANGE_BY_NUMBER", None)


def test_a_change_line_with_the_name_of_the_event_is_looked_up_by_name_never_hinted_and_never_a_new_event(world, clock, spy):
    """Slice S16b: "remarca o dentista para quinta às 10h" names the event, not its number. A sender who may not read a snapshot is told so, and nothing of the calendar is named."""
    policy(world)
    for line in ("remarca o dentista para quinta às 10h", "reschedule the dentist to Thursday 10am"):
        out = phone(world, line)
        assert out["asked"] is False and out["reply"] == phrases.text("NW_REF_NOT_READABLE", None) and spy == [] and drafts.count() == 0, (line, out["reply"])
        assert out["reply"] != phrases.text("NW_CHANGE_BY_NUMBER", None), "vacuity: it is not the hint"


def test_a_zone_with_a_clock_change_the_hour_that_does_not_exist_is_refused_in_a_sentence_and_the_hour_that_happens_twice_is_its_first_time(world, monkeypatch, spy):
    import time
    import zoneinfo
    monkeypatch.setenv("TZ", "Europe/Lisbon")
    time.tzset()
    try:
        Clock(monkeypatch, wall="2026-10-19 09:00", zone=zoneinfo.ZoneInfo("Europe/Lisbon"))
        policy(world)
        twice = phone(world, "marca dentista 25/10 às 01:30 no google")
        assert OPEN in twice["reply"] and spy[-1][1]["start"] == "2026-10-25T01:30" and "Europe/Lisbon" in body(world, twice)
        spy.clear()
        missing = phone(world, "marca dentista 28/03 às 01:30 no google")
        assert OPEN not in missing["reply"] and "does not exist" in missing["reply"] and "Traceback" not in missing["reply"]
    finally:
        monkeypatch.undo()          # the zone of the process is put back by this test itself
        time.tzset()
