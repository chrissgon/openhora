"""The mail and calendar lists that are fresh, and the reply when no source exists (slice S15, runtime/ops_items.py).

The live case (2026-10-22, a pt-BR project, Telegram): "Liste o ultimo email do meu Outlook" was answered "no numbered items yet", a sentence that does not say what to do, and a project that
has a source only has a list as fresh as its last refresh. Here the real snapshots behind the real runtime/item_refs.py (test_calendar_write.py's world and the stand-in providers of
test_sources_mail.py), the real natural-request path (`ops_natural.run`, which the interpreter also ends in), a stand-in clock. Every expectation is a literal of this file; the count of
provider reads is the stand-in provider's own list of calls, and each oracle that counts or searches has a vacuity case that fails on a planted wrong result. Offline; invented names.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_items_fresh.py
"""
from __future__ import annotations

import json
import shlex

import pytest

import standin_tree as st
import test_sources_mail as tsm
from test_calendar_write import Snapshots, world  # noqa: F401  (the calendar world and its real snapshots)
from test_ops_natural_writes import PLAIN, READER, SENDER, policy  # noqa: F401
from test_reminders import Clock

ops = st.load("ops")
ops_core = st.load("ops_core")
ops_sources = st.load("ops_sources")
ops_items = st.load("ops_items")
ops_natural = st.load("ops_natural")
phrases = st.load("phrases")

OUTLOOK_LINE = "Liste o ultimo email do meu Outlook"
OLD, NEW = "Bia Costa · Appointment confirmed · today 06:00", "Cora Dias · New invoice · today 06:00"      # the stand-in provider prints every message at 09:00 UTC, which is 06:00 in the world's zone
OUTLOOK_MAIL = "Dan Reis · Weekly report · today 06:00"
NOTE = "(list from 07:12)"       # the stand-in clock reads at 10:12 UTC; the world's zone is America/Sao_Paulo (-03:00)
NOT_ADDED = "Your mailbox has not been added to this project yet, so there is nothing to list. It is added once, on the platform's page."


@pytest.fixture
def clock(monkeypatch):
    return Clock(monkeypatch, wall="2026-10-19 09:00")


def project(world, language="en", page_url=None):
    """The four listed senders of the natural-writes tests (READER holds ask-mail, SENDER and PLAIN do not), in the language given."""
    policy(world)
    path = world["path"] + "/docs/workbench/runtime.json"
    raw = json.loads(open(path).read())
    raw["language"] = language
    raw["policies"] = {name: [*groups, "confirm-reads-off"] for name, groups in raw["policies"].items()}      # D5 is tested in test_plan_confirm*.py and test_messaging_plan_confirm.py: these tests are about the lists themselves, which run at once for a sender who holds the group (accepted with --widen below)
    if page_url:
        raw["messaging"]["page_url"] = page_url
    open(path, "w").write(json.dumps(raw))
    shown = ops.config(world["path"])
    ops.accept_config(world["path"], shown["sha256"], widen=shown["widening_sha256"])


@pytest.fixture
def snaps(world, monkeypatch):  # noqa: F811
    s = Snapshots(world, monkeypatch)
    monkeypatch.setattr(ops_items, "SNAPSHOT_CLOCK", lambda: s.now)
    ops_items._CHECKED.clear()
    s.providers.mail["gmail"] = [tsm.message(1, sender="Bia Costa <bia@clinic.example>", subject="Appointment confirmed")]
    s.providers.mail["outlook"] = [tsm.message(1, sender="Dan Reis <dan@work.example>", subject="Weekly report", source="outlook")]
    return s


def ask(world, line, sender=READER, channel="messaging"):
    """The reply of the natural request for the items, through the real dispatcher the interpreter also ends in."""
    ctx = ops_core.context(world["path"])
    return ops_natural.run(world["path"], ctx, "items", {}, line, channel, sender, {})


def mail_reads(snaps):
    """The reads of a mailbox the stand-in provider has answered so far (the test's own count of the verbs it was sent)."""
    return [c for c in snaps.providers.calls if c["cls"] == "reader:email"]


def phone_problems(reply):
    """What a phone must never be told: a command, a path, a file name or a flag (limit L62)."""
    return [w for w in ("source-mail", "source-calendar", "--origin", "--source", "cli.py", ".py", "/", "uv run", "python") if w in reply]


def add_message(snaps):
    snaps.providers.mail["gmail"].append(tsm.message(2, sender="Cora Dias <cora@clinic.example>", subject="New invoice"))


def with_inbox(world, snaps):
    """One Gmail source read once (it holds Bia's message); the count of provider reads starts at zero."""
    project(world)
    ops_sources.source_mail(world["path"], "inbox", "gmail:box=inbox;days=7;max=50")
    del snaps.providers.calls[:]


# --- no source: what to add and where ----------------------------------------------------------------------------------------------------------------


def test_no_mail_source_on_a_phone_is_one_plain_sentence_with_no_command(world, snaps, clock):
    project(world)
    reply = ask(world, "list my emails")
    assert reply == NOT_ADDED and phone_problems(reply) == [] and mail_reads(snaps) == []


def test_the_live_line_without_a_source_names_the_outlook_mailbox_in_portuguese(world, snaps, clock):
    project(world, "pt-BR")
    reply = ask(world, OUTLOOK_LINE)
    assert reply == ("A sua caixa de e-mail do Outlook ainda não foi adicionada a este projeto, então não há o que listar. "      # validate: allow english-only -- the Portuguese sentence under test
                     "Ela é adicionada uma vez, na página da plataforma.")      # validate: allow english-only -- the Portuguese sentence under test
    assert phone_problems(reply) == []


def test_no_calendar_source_on_a_phone_says_the_calendar(world, snaps, clock):
    project(world)
    assert ask(world, "list my events") == ("Your calendar has not been added to this project yet, so there is nothing to list. "
                                            "It is added once, on the platform's page.")
    assert ask(world, "list my events on my outlook calendar").startswith("Your Outlook calendar has not been added to this project yet")


def test_the_page_link_is_the_place_when_the_project_has_one(world, snaps, clock):
    project(world, page_url="https://platform.example/p")
    assert ask(world, "list my emails").endswith("It is added once, on the platform's page: https://platform.example/p")


def test_a_calendar_source_alone_does_not_answer_a_request_for_mail(world, snaps, clock):
    project(world)
    snaps.calendar("agenda", "google", "pat@example.com", [tsm.event(1, title="Dentist", id="ev1")])
    assert ask(world, "list my emails") == NOT_ADDED
    assert "Dentist" in ask(world, "list my events")      # the control: the same project lists its calendar


def test_in_the_conversation_the_exact_command_is_given_for_each_configured_account(world, snaps, clock):
    project(world)
    reply = ask(world, "list my emails", sender=None, channel="chat")
    lead, *commands = reply.splitlines()
    assert lead == "Your mailbox has not been added to this project yet. Add it once, in the terminal, then ask again:"
    assert [c.partition(": ")[0] for c in commands] == ["Gmail", "Outlook"], "both accounts of the project, in a fixed order"
    for command, source, origin in zip(commands, ("mail-gmail", "mail-outlook"), ("gmail:box=inbox;days=7;max=50", "outlook:box=inbox;days=7;max=50")):
        words = shlex.split(command.partition(": ")[2])
        assert "source-mail" in words and words[words.index("--source") + 1] == source and words[words.index("--origin") + 1] == origin, command
    assert world["path"] in commands[0] and "cli.py" in commands[0]


def test_the_command_given_is_one_the_runtime_accepts_and_the_list_then_works(world, snaps, clock):
    project(world)
    for command in ask(world, "list my emails", sender=None, channel="chat").splitlines()[1:]:
        words = shlex.split(command.partition(": ")[2])
        ops_sources.source_mail(world["path"], words[words.index("--source") + 1], words[words.index("--origin") + 1])
    listed = ask(world, "list my emails")
    assert OLD in listed and OUTLOOK_MAIL in listed and "Gmail (read" in listed and "Outlook (read" in listed and "inbox" not in listed.lower()


def test_the_calendar_command_and_an_account_named_in_the_line_narrow_the_examples(world, snaps, clock):
    project(world)
    both = ask(world, "list my events", sender=None, channel="chat").splitlines()
    assert both[0] == "Your calendar has not been added to this project yet. Add it once, in the terminal, then ask again:"
    assert [c.partition(": ")[0] for c in both[1:]] == ["Google", "Outlook"] and all("source-calendar" in c for c in both[1:])
    one = ask(world, OUTLOOK_LINE, sender=None, channel="chat").splitlines()
    assert one[0] == "Your Outlook mailbox has not been added to this project yet. Add it once, in the terminal, then ask again:"
    assert len(one) == 2 and one[1].startswith("Outlook: ") and "gmail" not in one[1] and "outlook:box=inbox;days=7;max=50" in one[1]


def test_only_the_configured_accounts_get_an_example(world, snaps, clock):
    project(world)
    ctx = ops_core.context(world["path"])
    ctx["cfg"] = dict(ctx["cfg"], accounts={"google": ctx["cfg"]["accounts"]["google"]})
    out = ops_items.reply(world["path"], ctx, {"sources": [], "refused": [], "missing": {"kind": "mail", "account": None}}, "chat")
    assert [c.partition(": ")[0] for c in out.splitlines()[1:]] == ["Gmail"]


def test_a_line_that_names_outlook_with_only_a_gmail_source_says_the_outlook_mailbox_is_not_added(world, snaps, clock):
    with_inbox(world, snaps)
    reply = ask(world, OUTLOOK_LINE)
    assert reply == "Your Outlook mailbox has not been added to this project yet, so there is nothing to list. It is added once, on the platform's page."
    assert OLD not in reply and mail_reads(snaps) == [], "the other account's source is neither listed nor read"
    assert OLD in ask(world, "list my emails on my gmail"), "the control: the Gmail account lists its own source"


def test_the_phone_oracle_fails_on_a_reply_that_holds_a_command():
    assert phone_problems("Add it with: python3 /x/runtime/cli.py source-mail --project /p --source a --origin b") != []
    assert phone_problems(NOT_ADDED) == []


# --- fresh lists ---------------------------------------------------------------------------------------------------------------------------------


def test_a_stale_snapshot_is_read_again_once_and_the_list_holds_the_new_message(world, snaps, clock):
    with_inbox(world, snaps)
    add_message(snaps)
    snaps.later(minutes=11)
    reply = ask(world, "list my emails")
    assert len(mail_reads(snaps)) == 1, "one read of the one source"
    assert OLD in reply and NEW in reply and NOTE not in reply


def test_a_fresh_snapshot_is_listed_as_it_is_with_no_read(world, snaps, clock):
    with_inbox(world, snaps)
    add_message(snaps)
    snaps.later(minutes=9)
    reply = ask(world, "list my emails")
    assert mail_reads(snaps) == [] and OLD in reply and NEW not in reply, "the provider holds the new message; the list is the snapshot of 9 minutes ago"


def test_the_limit_is_ten_minutes_and_a_read_makes_the_next_line_fresh(world, snaps, clock):
    with_inbox(world, snaps)
    add_message(snaps)
    snaps.later(minutes=10)
    ask(world, "list my emails")
    assert mail_reads(snaps) == [], "ten minutes is still fresh"
    snaps.later(minutes=1)
    ask(world, "list my emails")
    assert len(mail_reads(snaps)) == 1
    ask(world, "list my emails")
    assert len(mail_reads(snaps)) == 1, "the read made a new version: the next line finds it fresh"


def test_a_failed_refresh_lists_the_old_snapshot_with_one_note_and_no_provider_text(world, snaps, clock, capfd):
    with_inbox(world, snaps)
    add_message(snaps)
    snaps.later(minutes=11)
    snaps.providers.fail = tsm.Failure(reason="the provider said ZEBRA-SECRET")
    reply = ask(world, "list my emails")
    assert len(mail_reads(snaps)) == 1
    assert reply.splitlines()[-1] == NOTE and reply.count("(list from") == 1
    assert OLD in reply and NEW not in reply and "ZEBRA" not in reply + " ".join(capfd.readouterr())
    assert ask(world, "list my emails").splitlines()[-1] == NOTE, "still stale and still failing: still the note"


def test_the_note_is_in_portuguese_for_a_portuguese_project(world, snaps, clock):
    with_inbox(world, snaps)
    project(world, "pt-BR")
    snaps.later(minutes=11)
    snaps.providers.fail = tsm.Failure()
    assert ask(world, "lista os emails").splitlines()[-1] == "(lista de 07:12)"


def test_an_account_named_in_the_line_reads_and_lists_only_that_accounts_sources(world, snaps, clock):
    project(world)
    ops_sources.source_mail(world["path"], "inbox", "gmail:box=inbox;days=7;max=50")
    ops_sources.source_mail(world["path"], "work", "outlook:box=inbox;days=7;max=50")
    snaps.later(minutes=11)
    del snaps.providers.calls[:]
    reply = ask(world, OUTLOOK_LINE)
    assert [c["implementation"] for c in mail_reads(snaps)] == ["outlook"]
    assert OUTLOOK_MAIL in reply and OLD not in reply and "Gmail" not in reply
    snaps.later(minutes=11)
    del snaps.providers.calls[:]
    both = ask(world, "list my emails")
    assert sorted(c["implementation"] for c in mail_reads(snaps)) == ["gmail", "outlook"], "no account named: each stale source is read once"
    assert OLD in both and OUTLOOK_MAIL in both


def test_a_stale_calendar_is_read_again_too(world, snaps, clock):
    project(world)
    snaps.calendar("agenda", "google", "pat@example.com", [tsm.event(1, title="Dentist", id="ev1")])
    snaps.providers.events[("google", "pat@example.com")].append(tsm.event(2, "2026-10-17T11:00:00-03:00", "2026-10-17T12:00:00-03:00", "Yoga", id="ev2"))
    del snaps.providers.calls[:]
    snaps.later(minutes=11)
    reply = ask(world, "list my events")
    assert len([c for c in snaps.providers.calls if c["cls"] != "reader:email"]) == 1 and "Yoga" in reply and "Dentist" in reply


def test_a_sender_without_the_read_right_gets_todays_refusal_and_no_read(world, snaps, clock):
    with_inbox(world, snaps)
    snaps.later(minutes=11)
    for sender in (SENDER, PLAIN):
        assert ask(world, "list my emails", sender=sender) == "error: " + phrases.en("NW_REF_NOT_READABLE")
    with pytest.raises(ops.OpsError):
        ops.items(world["path"], kind="mail", channel="messaging", sender=None)
    assert mail_reads(snaps) == []


def test_the_terminal_does_not_read_the_provider_for_a_list(world, snaps, clock):
    with_inbox(world, snaps)
    snaps.later(minutes=11)
    out = ops.items(world["path"], kind="mail", channel="terminal")
    assert mail_reads(snaps) == [] and [e["source"] for e in out["sources"]] == ["inbox"] and "old" not in out["sources"][0]


def test_the_counter_oracle_sees_a_read(world, snaps, clock):
    with_inbox(world, snaps)
    assert mail_reads(snaps) == []
    ops_sources.source_refresh(world["path"], "inbox")
    assert len(mail_reads(snaps)) == 1, "vacuity: the count is not always zero"


# --- a list written for a person (the phone) -----------------------------------------------------------------------------------------------------------


def calendar_world(world, snaps, language="en"):
    """One Google calendar with three events as the stand-in provider prints them: a timed one the person organizes (Saturday 17/10), one organized by another domain that the person
    has not answered, and an all-day one."""
    project(world, language)
    snaps.calendar("agenda-google", "google", "pat@example.com", [
        tsm.event(1, "2026-10-17T09:00:00-03:00", "2026-10-17T10:00:00-03:00", "Dentist", id="ev1", response="accepted"),
        tsm.event(2, "2026-10-17T14:00:00-03:00", "2026-10-17T15:00:00-03:00", "Budget review", id="ev2", organizer_self=False, organizer_domain="work.example", response="needsAction",
                  online_meeting=True),
        tsm.event(3, "2026-10-18", "2026-10-19", "Family lunch", id="ev3", all_day=True)])


def test_the_calendar_on_a_phone_has_a_plain_name_a_local_time_the_day_of_each_event_and_no_internal_word(world, snaps, clock):
    calendar_world(world, snaps)
    reply = ask(world, "list my events")
    assert reply.splitlines() == [
        "Google calendar (read at 07:12):",
        "1. Sat 17/10 09:00\u201310:00 \u00b7 Dentist \u00b7 you accepted",
        "2. Sat 17/10 14:00\u201315:00 \u00b7 Budget review \u00b7 organized by work.example \u00b7 no answer from you yet \u00b7 online meeting",
        "3. Sun 18/10 all day \u00b7 Family lunch \u00b7 you accepted"]
    for internal in ("agenda-google", "organizer", "you: ", "lido", "10:12", "2026"):
        assert internal not in reply, internal


def test_the_calendar_on_a_phone_in_portuguese(world, snaps, clock):
    calendar_world(world, snaps, "pt-BR")
    assert ask(world, "meus eventos").splitlines() == [
        "Agenda do Google (lido às 07:12):",      # validate: allow english-only -- the Portuguese sentence under test
        "1. sáb 17/10 09:00\u201310:00 \u00b7 Dentist \u00b7 você aceitou",      # validate: allow english-only -- the Portuguese sentence under test
        "2. sáb 17/10 14:00\u201315:00 \u00b7 Budget review \u00b7 organizado por work.example \u00b7 sem resposta sua ainda \u00b7 reunião online",      # validate: allow english-only -- the Portuguese sentence under test
        "3. dom 18/10 dia inteiro \u00b7 Family lunch \u00b7 você aceitou"]      # validate: allow english-only -- the Portuguese sentence under test


def test_the_mail_on_a_phone_has_a_plain_name_and_a_local_time(world, snaps, clock):
    with_inbox(world, snaps)
    reply = ask(world, "list my emails")
    assert reply.splitlines() == ["Gmail (read at 07:12):", "1. " + OLD]
    assert "bia@clinic.example" not in reply and "(read 2026" not in reply


def test_a_snapshot_read_on_another_day_says_the_day(world, snaps, clock):
    with_inbox(world, snaps)
    snaps.later(hours=20)
    snaps.providers.fail = tsm.Failure()
    assert ask(world, "list my emails").splitlines()[0] == "Gmail (read on 17/10 at 07:12):"


def test_two_sources_of_one_account_are_told_apart_by_their_box_and_then_by_a_number(world, snaps, clock):
    project(world)
    ops_sources.source_mail(world["path"], "inbox", "gmail:box=inbox;days=7;max=50")
    ops_sources.source_mail(world["path"], "starred", "gmail:box=starred;days=7;max=50")
    heads = [line for line in ask(world, "list my emails").splitlines() if line.endswith("):")]
    gmail = "Gmail"
    boxes = [phrases.text("SRC_TWIN", None, name=gmail, detail=phrases.text(key, None)) for key in ("SRC_BOX_INBOX", "SRC_BOX_STARRED")]      # BL5D: the box tells twins apart
    assert heads == [f"{name} (read at 07:12):" for name in boxes]
    ops_sources.source_mail(world["path"], "inbox-2", "gmail:box=inbox;days=3;max=50")
    heads = [line for line in ask(world, "list my emails").splitlines() if line.endswith("):")]
    assert [h.partition(" (read")[0] for h in heads] == [boxes[0] + " 1", boxes[0] + " 2", boxes[1]]      # equal after the detail: numbered in the registry's order (by id)


def test_the_conversation_and_the_terminal_keep_the_source_id_the_utc_time_and_the_line_as_the_snapshot_prints_it(world, snaps, clock):
    calendar_world(world, snaps)
    chat = ask(world, "list my events", sender=None, channel="chat").splitlines()
    assert chat[0] == "agenda-google (read 2026-10-17 10:12):" and chat[1].startswith("1. 09:00-10:00 \u00b7 Dentist \u00b7 ") and "organizer: you" in chat[1]
    rows = ops.items(world["path"], kind="calendar", channel="terminal")["sources"][0]["items"]
    assert [r["n"] for r in rows] == [1, 2, 3] and rows[0]["day"] == "2026-10-17" and rows[2]["day"] == "2026-10-18"


def test_the_numbers_are_the_snapshots_own_so_the_numbered_forms_still_point_at_the_same_events(world, snaps, clock):
    calendar_world(world, snaps)
    shown = {int(line.split(".")[0]): line for line in ask(world, "list my events").splitlines()[1:]}
    rows = {r["n"]: r["line"] for r in ops.items(world["path"], kind="calendar", channel="terminal")["sources"][0]["items"]}
    assert sorted(shown) == sorted(rows) == [1, 2, 3]
    assert all(rows[n].split(" \u00b7 ")[1] in shown[n] for n in shown), "each number carries the same event's title"
