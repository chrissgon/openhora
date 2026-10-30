"""The plain name a phone shows for a mail or calendar source (package BL5D, runtime/source_names.py).

The live case (2026-10-25, a pt-BR project, Telegram): "apague o e-mail do github" was answered "De qual caixa? 1. caixa-gmail 2. caixa-outlook", and the answer "1" "O retrato mais novo de
caixa-gmail tem mais de 26 horas...". The person asked for "Gmail / Outlook". Held here, for every place a phone read a source id:

  (a) the names: "Gmail", "Outlook", "Agenda do Google", twins told apart by their box, by "main" or by the person's description, whatever is still equal numbered; the names of any
      catalog of up to four sources are pairwise different (every multiset of the origins below), and an unreadable origin keeps its id;
  (b) the question "De qual caixa?": the options read "1. Gmail", "2. Outlook", while the stored values stay the ids; the conversation (`chat`) keeps the ids;
  (c) the answers: the number, the name, the provider's word ("google", "hotmail", "drive") or the id typed as it is select the same source as before;
  (d) twins are never merged: a word that fits two options asks again and opens nothing, the shown name of one selects it;
  (e) the sentences that name a source (nothing matched, a snapshot too old) and the question of several numbers say the name on a phone and the id elsewhere;
  (f) the phone list and what it says of a source it could not read: a name and one sentence with none of the English words; the terminal keeps `<id>: <why>`;
  (g) the list of events of two calendars ends each line with the name of its calendar;
  (h) the phone form of a reply card says "3 do Gmail" from a copy: the stored card and its hash are the approval's and do not move, two targets still read differently;
  (i) no reply of a phone in (b) to (g) holds a registered source id as a word.

Every wording is compared with the phrase table by its key (T8); the values (an id, a name of a provider's brand) are literals of this file; the stand-ins are the world of
test_calendar_write.py and the providers of test_sources_mail.py; every name is invented. No model and no provider is called. Offline.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_source_names.py
"""
from __future__ import annotations

import datetime
import itertools
import json
import re
import types

import pytest

import phrase_kit as pk
import standin_tree as st
import test_sources_mail as tsm
from test_calendar_write import world  # noqa: F401  (the calendar world and its real snapshots)
from test_items_fresh import ask, project, snaps  # noqa: F401  (the mail desk of the stand-in providers)
from test_ops_natural_writes import READER, forget  # noqa: F401  (a sender that may read; the drafts are cleared around each test)
from test_phone_card_targets import item, line, mail_reply
from closed_heads import closed_heads, tier1_forms  # noqa: F401  (S41-11: the claim of the write families and of every closed form, as fixtures: these tests are about the readers and resolvers, not the claim)

pytestmark = pytest.mark.usefixtures("tier1_forms")      # S41-11: every closed form claims a line in this file, as it did

cards = st.load("messaging_cards")
event_lookup = st.load("event_lookup")
messaging_bridge = st.load("messaging_bridge")
ops = st.load("ops")
ops_natural_writes = st.load("ops_natural_writes")
ops_sources = st.load("ops_sources")
drafts = st.load("drafts")
phrases = st.load("phrases")
source_names = st.load("source_names")
sources = st.load("sources")

PT, EN = {"language": "pt-BR"}, {"language": "en"}
IDS = ("caixa-gmail", "caixa-outlook", "agenda-google", "agenda-outlook")
ID_AS_A_WORD = re.compile(r"(?<![\w-])(?:" + "|".join(map(re.escape, IDS)) + r")(?![\w-])")
GMAIL, OUTLOOK = "Gmail", "Outlook"      # the providers' own brand names: the oracle of a name that is not a sentence
BOX = {"inbox": "SRC_BOX_INBOX", "important": "SRC_BOX_IMPORTANT", "starred": "SRC_BOX_STARRED", "unread": "SRC_BOX_UNREAD"}


def twin(cfg, name, detail_key=None, detail=None):
    """`SRC_TWIN` as the table says it, for the detail given by its key or as a word."""
    return phrases.text("SRC_TWIN", cfg, name=name, detail=phrases.text(detail_key, cfg) if detail_key else detail)


def assert_twin(text, cfg, name, detail_key=None, detail=None):
    """`text` says `SRC_TWIN` with `name` and, as its detail, the sentence of `detail_key` or the word `detail`."""
    pk.assert_said(text, "SRC_TWIN", cfg, name=name, **({"detail": detail} if detail else {}))
    if detail_key:
        assert text.startswith(name + " (") and text.endswith(")"), text
        pk.assert_said(text[len(name) + 2:-1], detail_key, cfg)      # the detail is what sits between the parentheses of the template


def mail(cfg, service):
    return source_names.plain("mail", service, cfg)      # the provider's brand: a mailbox has no phrase of the table (a sentence that is only a field would pass every text of the phone net)


def calendar(cfg, service):
    return phrases.text("NW_ITEMS_NAME_CAL", cfg, service=service)


def row(source_id, origin, description=None, kind=None):
    """A catalog row of a mail or calendar source as `sources.list_catalog` gives it (only the fields the names read); the type is the origin's own unless `kind` says another."""
    return {"id": source_id, "type": kind or ("mail" if origin.startswith("gmail:") or origin.startswith("outlook:box") else "calendar"), "origin": origin, "description": description}


def named(monkeypatch, rows, cfg=PT):
    monkeypatch.setattr(sources, "list_catalog", lambda ctx, hashes=True, **kw: rows)
    return {i: e["name"] for i, e in source_names.catalog({"cfg": cfg}).items()}


def no_id(*replies):
    """(i): what a phone is told holds none of the registered source ids as a word."""
    for reply in replies:
        assert not ID_AS_A_WORD.search(reply), reply


# --- (a) the names ----------------------------------------------------------------------------------------------------------------------------------


def test_the_names_of_mail_and_calendar_sources_in_portuguese_and_in_english(monkeypatch):
    rows = [row("caixa-gmail", "gmail:box=inbox;days=7;max=50"), row("caixa-outlook", "outlook:box=inbox;days=7;max=50"),
            row("agenda-google", "google:calendar=primary;past=0;ahead=14"), row("agenda-outlook", "outlook:calendar=default;past=0;ahead=14")]
    assert named(monkeypatch, rows, PT) == {"caixa-gmail": "Gmail", "caixa-outlook": "Outlook", "agenda-google": calendar(PT, "Google"), "agenda-outlook": calendar(PT, "Outlook")}
    assert named(monkeypatch, rows, EN) == {"caixa-gmail": "Gmail", "caixa-outlook": "Outlook", "agenda-google": calendar(EN, "Google"), "agenda-outlook": calendar(EN, "Outlook")}
    for cfg in (PT, EN):
        names = named(monkeypatch, rows, cfg)
        pk.assert_said(names["agenda-google"], "NW_ITEMS_NAME_CAL", cfg, service="Google")
        pk.assert_said(names["agenda-outlook"], "NW_ITEMS_NAME_CAL", cfg, service="Outlook")
    assert named(monkeypatch, rows, PT)["agenda-google"] == calendar(PT, "Google") and named(monkeypatch, rows, EN)["caixa-gmail"] == mail(EN, GMAIL)


def test_the_entry_of_a_source_holds_its_type_and_its_account_and_a_failed_catalog_is_empty(monkeypatch):
    monkeypatch.setattr(sources, "list_catalog", lambda ctx, hashes=True, **kw: [row("caixa-outlook", "outlook:box=inbox;days=7;max=50"), row("notas", "notas.md", kind="folder")])
    entries = source_names.catalog({"cfg": PT})
    assert entries == {"caixa-outlook": {"name": "Outlook", "type": "mail", "account": "microsoft"}}, "a source that is neither mail nor calendar is not named here"

    def broken(ctx, hashes=True, **kw):
        raise sources.SourcesError("the registry is not readable", "usage")
    monkeypatch.setattr(sources, "list_catalog", broken)
    assert source_names.catalog({"cfg": PT}) == {}, "presentation, never a refusal: a phone then shows the ids"
    assert source_names.shown("caixa-outlook", {}, PT) == "caixa-outlook"


def test_twins_are_told_apart_by_their_box_and_by_main_or_the_description(monkeypatch):
    two = named(monkeypatch, [row("a", "gmail:box=inbox;days=7;max=50"), row("b", "gmail:box=unread;days=7;max=50"), row("c", "outlook:box=inbox;days=7;max=50")])
    assert two == {"a": twin(PT, "Gmail", "SRC_BOX_INBOX"), "b": twin(PT, "Gmail", "SRC_BOX_UNREAD"), "c": "Outlook"}, "only the twins get a detail"
    assert_twin(two["a"], PT, "Gmail", "SRC_BOX_INBOX")
    assert_twin(two["b"], PT, "Gmail", "SRC_BOX_UNREAD")
    calendars = named(monkeypatch, [row("p", "google:calendar=primary;past=0;ahead=14"), row("w", "google:calendar=work.calendar@example.com;past=0;ahead=14", "Trabalho"),
                                    row("h", "outlook:calendar=default;past=0;ahead=14")])
    assert calendars == {"p": twin(PT, calendar(PT, "Google"), "SRC_CAL_MAIN"), "w": twin(PT, calendar(PT, "Google"), detail="Trabalho"), "h": calendar(PT, "Outlook")}
    assert_twin(calendars["p"], PT, calendar(PT, "Google"), "SRC_CAL_MAIN")
    pk.assert_said(calendars["h"], "NW_ITEMS_NAME_CAL", PT, service="Outlook")
    cut = named(monkeypatch, [row("p", "google:calendar=primary;past=0;ahead=14"), row("w", "google:calendar=w@example.com;past=0;ahead=14", "x" * 40 + "\n{evil}")])
    assert cut["w"] == twin(PT, calendar(PT, "Google"), detail="x" * 23 + "…"), "one line, 24 characters at most, control characters out"


def test_what_is_still_equal_after_the_detail_is_numbered_in_the_registry_order(monkeypatch):
    names = named(monkeypatch, [row("one", "gmail:box=inbox;days=7;max=50"), row("two", "gmail:box=inbox;days=3;max=50"), row("three", "gmail:box=starred;days=7;max=50")])
    inbox, starred = twin(PT, "Gmail", "SRC_BOX_INBOX"), twin(PT, "Gmail", "SRC_BOX_STARRED")
    assert names == {"one": inbox + " 1", "two": inbox + " 2", "three": starred}
    bare = named(monkeypatch, [row("p", "google:calendar=a@example.com;past=0;ahead=14"), row("q", "google:calendar=b@example.com;past=0;ahead=14")])
    assert bare == {"p": calendar(PT, "Google") + " 1", "q": calendar(PT, "Google") + " 2"}, "two calendars with nothing to tell them apart are numbered, never merged"


def test_a_source_whose_origin_cannot_be_read_keeps_its_id(monkeypatch):
    names = named(monkeypatch, [row("caixa-estranha", "gmail:box=whatever"), row("caixa-gmail", "gmail:box=inbox;days=7;max=50")])
    assert names == {"caixa-estranha": "caixa-estranha", "caixa-gmail": "Gmail"}


ORIGINS = [("gmail:box=inbox;days=7;max=50", None), ("gmail:box=important;days=7;max=50", None), ("gmail:box=starred;days=7;max=50", None), ("gmail:box=unread;days=7;max=50", None),
           ("outlook:box=inbox;days=7;max=50", None), ("outlook:box=unread;days=7;max=50", None),
           ("google:calendar=primary;past=0;ahead=14", None), ("google:calendar=other@example.com;past=0;ahead=14", None), ("google:calendar=other@example.com;past=0;ahead=14", "Trabalho"),
           ("outlook:calendar=default;past=0;ahead=14", None), ("outlook:calendar=AAMk01;past=0;ahead=14", "Casa"), ("gmail:box=weird", None)]


def catalogs():
    """Every multiset of one to four sources of ORIGINS, as registered in that order: no randomness."""
    for size in range(1, 5):
        for chosen in itertools.combinations_with_replacement(ORIGINS, size):
            yield [row(f"s{k}", origin, description) for k, (origin, description) in enumerate(chosen)]


def collisions(monkeypatch, language):
    bad = []
    for rows in catalogs():
        names = list(named(monkeypatch, rows, language).values())
        if len(set(names)) != len(names):
            bad.append((rows, names))
    return bad


def test_the_names_of_any_catalog_of_up_to_four_sources_are_pairwise_different(monkeypatch):
    assert sum(1 for _ in catalogs()) > 1000, "the enumeration is not empty"
    assert collisions(monkeypatch, PT) == [] and collisions(monkeypatch, EN) == []


def test_the_property_can_fail_without_the_numbering(monkeypatch):
    """Vacuity of the test above: with step 3 removed, the catalog of two Gmail inboxes has two sources of one name."""
    monkeypatch.setattr(source_names, "_number", lambda names: None)
    bad = collisions(monkeypatch, PT)
    assert bad and any([r["origin"] for r in rows] == ["gmail:box=inbox;days=7;max=50"] * 2 for rows, _ in bad)


# --- the shown form of a value --------------------------------------------------------------------------------------------------------------------


def test_a_source_id_and_a_reference_are_named_and_every_other_text_is_left_as_it_is():
    table = {"caixa-gmail": {"name": "Gmail"}, "caixa-outlook": {"name": "Outlook"}}
    assert source_names.shown("caixa-gmail", table, PT) == "Gmail"
    assert source_names.shown("caixa-outlook#7", table, PT) == phrases.text("SRC_ITEM", PT, name="Outlook", n=7) == "Outlook, mensagem 7"
    assert source_names.shown("caixa-gmail#3", {"caixa-gmail": "Gmail"}, EN) == phrases.text("SRC_ITEM", EN, name="Gmail", n=3), "a table of plain names works as well"
    for kept in ("ana@clinic.example · Pedido #12", "caixa-gmail#3 e mais", "outra-caixa#3", "#3", "Gmail", "", "caixa-gmail #3", "caixa-gmail#0003x"):
        assert source_names.shown(kept, table, PT) == kept, kept
    assert source_names.shown(["caixa-gmail"], table, PT) == ["caixa-gmail"] and source_names.shown("caixa-gmail", {}, PT) == "caixa-gmail"


def test_the_service_words_are_the_account_s_language_data():
    assert {"google", "gmail", "drive"} <= set(source_names.words({"account": "google"}))
    assert "hotmail" in source_names.words({"account": "microsoft"}) and source_names.words({"account": None}) == [] and source_names.words({}) == []


# --- the world: two mail sources and two calendar sources -----------------------------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def the_snapshots_are_as_old_as_the_stand_in_clock(world, snaps, monkeypatch):  # noqa: F811
    """A snapshot is read for a line against the stand-in clock of `snaps` (`sources.snapshot_age`), as test_send_own_account.py does for its desk."""
    original = sources.snapshot_age
    monkeypatch.setattr(sources, "snapshot_age", lambda stamp, clock=None: original(stamp, clock or (lambda: snaps.now)))


def two_mailboxes(world, snaps, language="pt-BR", extra=()):
    project(world, language)
    ops_sources.source_mail(world["path"], "caixa-gmail", "gmail:box=inbox;days=7;max=50")
    ops_sources.source_mail(world["path"], "caixa-outlook", "outlook:box=inbox;days=7;max=50")
    for source_id, origin in extra:
        ops_sources.source_mail(world["path"], source_id, origin)


def natural(world, text, channel="messaging", sender=READER):
    return ops.natural_write(world["path"], text, channel=channel, sender=sender)


def stored_options(channel="messaging", sender=READER):
    return drafts.get(*ops_natural_writes._slot(channel, sender))["options"]


def pending(world):
    ctx = st.load("ops_core").context(world["path"])
    return ctx["store"].pending_list(ctx["conn"], "open")


# --- (b) the question the person saw ----------------------------------------------------------------------------------------------------------------


def test_the_question_of_which_mailbox_reads_gmail_and_outlook_on_a_phone_and_stores_the_ids(world, snaps):
    two_mailboxes(world, snaps)
    out = natural(world, "arquiva o e-mail do github")
    assert out["asked"] and out["reply"] == phrases.text("NW_MAIL_ASK_SOURCE", PT) + "\n1. Gmail\n2. Outlook"
    asking, *options = out["reply"].split("\n")
    pk.assert_said(asking, "NW_MAIL_ASK_SOURCE", PT)
    assert options == ["1. Gmail", "2. Outlook"]
    no_id(out["reply"])
    assert [(o["value"], o["label"]) for o in stored_options()] == [("caixa-gmail", "Gmail"), ("caixa-outlook", "Outlook")], "the values are the ids"


def test_the_same_question_on_the_conversation_still_shows_the_ids(world, snaps):
    """Vacuity of the test above: the id is visible to the test where it is not hidden."""
    two_mailboxes(world, snaps)
    out = natural(world, "arquiva o e-mail do github", channel="chat", sender=None)
    assert out["reply"] == phrases.text("NW_MAIL_ASK_SOURCE", PT) + "\n1. caixa-gmail\n2. caixa-outlook"
    assert "words" not in stored_options("chat", None)[0]


def test_the_question_of_which_calendar_names_the_calendars_on_a_phone(world, snaps):
    project(world, "pt-BR")
    snaps.calendar("agenda-google", "google", "primary", [tsm.event(1, id="ev1")])
    snaps.calendar("agenda-outlook", "outlook", "default", [tsm.event(1, id="ev2")])
    out = natural(world, "cancela o evento 1")
    assert out["asked"] and out["reply"] == phrases.text("NW_ASK_SOURCE", PT) + "\n1. " + calendar(PT, "Google") + "\n2. " + calendar(PT, "Outlook")
    no_id(out["reply"])
    assert [o["value"] for o in stored_options()] == ["agenda-google", "agenda-outlook"]


# --- (c) the answers --------------------------------------------------------------------------------------------------------------------------------


def chosen(world, answer):
    """The source the draft holds after `answer` to the question of which mailbox, or None when it asked again."""
    out = natural(world, "arquiva o e-mail do github")
    assert out["asked"]
    natural(world, answer)
    left = drafts.get(*ops_natural_writes._slot("messaging", READER))
    return left["slots"].get("source") if left else "gone"


@pytest.mark.parametrize("answer, source", [("1", "caixa-gmail"), ("2", "caixa-outlook"), ("Gmail", "caixa-gmail"), ("gmail", "caixa-gmail"), ("google", "caixa-gmail"),
                                            ("drive", "caixa-gmail"), ("Outlook", "caixa-outlook"), ("hotmail", "caixa-outlook"), ("caixa-gmail", "caixa-gmail"),
                                            ("caixa-outlook", "caixa-outlook")])
def test_a_number_a_name_a_service_word_or_the_id_selects_the_same_source_as_before(world, snaps, answer, source):
    two_mailboxes(world, snaps)
    natural(world, "arquiva o e-mail do github")
    assert ops_natural_writes._option({"options": stored_options(), "multi": False}, answer) == source


def test_a_word_of_no_option_selects_nothing_and_the_question_is_asked_again(world, snaps):
    two_mailboxes(world, snaps)
    natural(world, "arquiva o e-mail do github")
    options = stored_options()
    for answer in ("yahoo", "3", "0", "caixa", "gmail outlook"):
        assert ops_natural_writes._option({"options": options, "multi": False}, answer) is None, answer


# --- (d) twins are never merged ---------------------------------------------------------------------------------------------------------------------


def test_a_word_that_fits_two_sources_of_one_account_asks_again_and_opens_nothing(world, snaps):
    two_mailboxes(world, snaps, extra=(("caixa-gmail-nao-lidos", "gmail:box=unread;days=7;max=50"),))
    out = natural(world, "arquiva os e-mails 2 e 4 no gmail")
    options = stored_options()
    assert [o["value"] for o in options] == ["caixa-gmail", "caixa-gmail-nao-lidos"]
    listed = out["reply"].splitlines()[1:]
    assert len(listed) == 2 and listed[0].startswith("1. ") and listed[1].startswith("2. ")
    assert_twin(listed[0][3:], PT, "Gmail", "SRC_BOX_INBOX")
    assert_twin(listed[1][3:], PT, "Gmail", "SRC_BOX_UNREAD")
    again = natural(world, "gmail")
    assert again["asked"] and again["reply"].splitlines()[0] == phrases.text("NW_MAIL_ASK_SOURCE", PT), "one match only: gmail names both"
    assert drafts.get(*ops_natural_writes._slot("messaging", READER))["slots"].get("source") is None and pending(world) == []
    assert ops_natural_writes._option({"options": options, "multi": False}, "gmail (nao lidos)") == "caixa-gmail-nao-lidos"
    assert ops_natural_writes._option({"options": options, "multi": False}, "Gmail (não lidos)") == "caixa-gmail-nao-lidos"      # validate: allow english-only -- the shown name
    assert ops_natural_writes._option({"options": options, "multi": False}, "2") == "caixa-gmail-nao-lidos"
    assert ops_natural_writes._option({"options": options, "multi": False}, "caixa-gmail") == "caixa-gmail", "the id typed as it is is a key"


# --- (e) the sentences ------------------------------------------------------------------------------------------------------------------------------


def test_a_sentence_that_says_a_source_says_its_name_on_a_phone_and_its_id_on_the_conversation(world, snaps):
    two_mailboxes(world, snaps)
    on_phone = natural(world, "arquiva o e-mail do github no gmail")["reply"]
    assert on_phone == phrases.text("NW_MAIL_NONE", PT, source="Gmail", words="github")
    on_chat = natural(world, "arquiva o e-mail do github no gmail", channel="chat", sender=None)["reply"]
    assert on_chat == phrases.text("NW_MAIL_NONE", PT, source="caixa-gmail", words="github")
    no_id(on_phone)
    asked = natural(world, "arquiva o e-mail do github")
    assert asked["asked"]
    assert natural(world, "2")["reply"] == phrases.text("NW_MAIL_NONE", PT, source="Outlook", words="github"), "the answer by number reaches the same sentence"


def test_the_stale_snapshot_sentence_names_the_source_on_a_phone(world, snaps, monkeypatch):
    two_mailboxes(world, snaps)
    snaps.later(hours=30)
    monkeypatch.setattr(st.load("mail_refresh"), "refresh_once", lambda *a: "not-allowed")      # BL5E: a phone's line by words refreshes a stale snapshot itself; this test is about the sentence of the lines that cannot (a number, a written reference), so the refresh is off here
    on_phone = natural(world, "arquiva o e-mail do github no gmail")["reply"]
    assert on_phone == phrases.text("ACCT_MAIL_REF_STALE", PT, ref="Gmail")
    no_id(on_phone)
    on_chat = natural(world, "arquiva o e-mail do github no gmail", channel="chat", sender=None)["reply"]
    assert on_chat == phrases.text("ACCT_MAIL_REF_STALE", PT, ref="caixa-gmail")


def test_a_reply_that_names_several_numbers_lists_them_by_the_name_of_the_source_and_the_choice_is_the_reference(world, snaps):
    two_mailboxes(world, snaps)
    ctx = st.load("ops_core").context(world["path"])
    spec = st.load("ops_natural_mail").resolve(ctx, "mail-reply", {"numbers": [3, 7], "body": "ok", "source": "caixa-gmail"}, "messaging", READER)
    assert [o["label"] for o in spec["ask"]["options"]] == ["caixa-gmail#3", "caixa-gmail#7"], "the family asks with the references"
    state = ops_natural_writes.new_state(ctx, {"op": "mail-reply", "family": "mail", "slots": {"numbers": [3, 7], "source": "caixa-gmail"}}, "x")
    said = ops_natural_writes._ask(ctx, state, spec, "messaging", READER, {})
    assert said == phrases.text("NW_MAIL_ASK_MESSAGE", PT, count=2) + "\n1. " + phrases.text("SRC_ITEM", PT, name="Gmail", n=3) + "\n2. " + phrases.text("SRC_ITEM", PT, name="Gmail", n=7)
    no_id(said)
    assert [o["value"] for o in stored_options()] == ["caixa-gmail#3", "caixa-gmail#7"]
    assert ops_natural_writes._option({"options": stored_options(), "multi": False}, "2") == "caixa-gmail#7"
    assert ops_natural_writes._option({"options": stored_options(), "multi": False}, "caixa-gmail#3") == "caixa-gmail#3", "the reference typed as it is"
    drafts.clear()
    state = ops_natural_writes.new_state(ctx, {"op": "mail-reply", "family": "mail", "slots": {}}, "x")
    assert ops_natural_writes._ask(ctx, state, spec, "chat", None, {}).splitlines()[1:] == ["1. caixa-gmail#3", "2. caixa-gmail#7"], "the conversation keeps the references"


# --- (f) the phone list ------------------------------------------------------------------------------------------------------------------------------


def test_the_phone_list_names_a_source_it_could_not_read_in_one_sentence_and_the_terminal_keeps_the_id_and_the_reason(world, snaps):
    project(world, "pt-BR")
    ops_sources.source_mail(world["path"], "caixa-outlook", "outlook:box=inbox;days=7;max=50")
    snaps.later(hours=30)
    ops_sources.source_mail(world["path"], "caixa-gmail", "gmail:box=inbox;days=7;max=50")      # read now: fresh; the Outlook one is older than 26 hours
    snaps.providers.fail = tsm.Failure("failed", "exit 1")
    on_phone = ask(world, "lista meus emails")
    assert phrases.text("NW_ITEMS_REFUSED_PHONE", PT, name="Outlook") in on_phone.splitlines()
    assert on_phone.splitlines()[0].startswith("Gmail (") and pk.said(on_phone, "NW_ITEMS_REFUSED_PHONE", PT, name="Outlook")
    no_id(on_phone)
    for word in ("snapshot", "refresh", "retrato", "atualize"):
        assert word not in on_phone.lower(), word
    on_terminal = ask(world, "lista meus emails", sender=None, channel="chat")
    refused = [text for text in on_terminal.splitlines() if text.startswith("caixa-outlook: ")]
    assert len(refused) == 1 and "snapshot" in refused[0], "the terminal keeps the id and the reason as before"


def test_the_phone_list_of_twins_uses_the_names_of_the_whole_catalog(world, snaps):
    two_mailboxes(world, snaps, language="en", extra=(("caixa-gmail-lidos", "gmail:box=starred;days=7;max=50"),))
    heads = [text.partition(" (read")[0] for text in ask(world, "list my emails").splitlines() if text.endswith("):")]
    assert heads == [twin(EN, "Gmail", "SRC_BOX_INBOX"), twin(EN, "Gmail", "SRC_BOX_STARRED"), "Outlook"], "in the registry's order"


# --- (g) the list of events -------------------------------------------------------------------------------------------------------------------------


def test_the_list_of_events_of_two_calendars_ends_each_line_with_the_name_of_its_calendar(world, snaps):
    project(world, "pt-BR")
    snaps.calendar("agenda-google", "google", "primary", [tsm.event(1, id="ev1")])
    snaps.calendar("agenda-outlook", "outlook", "default", [tsm.event(1, id="ev2")])
    ctx = st.load("ops_core").context(world["path"])
    found = [{"source": "agenda-google", "n": 1, "day": datetime.date(2026, 10, 22), "time": "14:00-15:00", "title": "dentista"},
             {"source": "agenda-outlook", "n": 1, "day": datetime.date(2026, 10, 22), "time": "14:30-15:30", "title": "dentista 2"}]
    lines = event_lookup._list(ctx, "event-cancel", found).splitlines()
    assert lines[1].endswith(f" ({calendar(PT, 'Google')})") and lines[2].endswith(f" ({calendar(PT, 'Outlook')})"), lines
    no_id("\n".join(lines))
    one = event_lookup._list(ctx, "event-cancel", found[:1]).splitlines()
    assert one[1].endswith("dentista") and "(" not in one[1], "one source: no parenthesis, as before"
    unknown = event_lookup._list(ctx, "event-cancel", [found[0], {**found[1], "source": "agenda-velha"}]).splitlines()
    assert unknown[2].endswith(" (agenda-velha)"), "a source the catalog does not name keeps its id"


# --- (h) the phone form of a reply card -------------------------------------------------------------------------------------------------------------


def phone_card(lines, cfg):
    return cards.effect_card_text(item(lines), cfg, True, False, False)


def test_the_reply_card_on_a_phone_says_the_message_by_its_number_and_the_name_of_its_source():
    cfg = {"language": "pt-BR", "source_names": {"caixa-gmail": "Gmail", "caixa-outlook": "Outlook"}}
    lines = mail_reply(ref="caixa-gmail#3")
    text = phone_card(lines, cfg)
    assert phrases.text("SRC_ITEM_CARD", cfg, name="Gmail", n=3) == "3 do Gmail"
    assert phrases.text("PHONE_MAIL_REPLY_TO", cfg, address="ana@example.com", ref="3 do Gmail", subject="Budget") in text.splitlines()
    assert "caixa-gmail" not in text
    assert phone_card(lines, {"language": "pt-BR"}).count("caixa-gmail#3") == 1, "without names: today's text"
    assert phone_card(lines, {"language": "pt-BR", "source_names": {"outro": "Outro"}}).count("caixa-gmail#3") == 1, "an unknown source keeps its reference"


def test_the_stored_card_and_its_hash_are_not_touched_by_drawing_it_for_a_phone():
    cfg = {"language": "pt-BR", "source_names": {"caixa-gmail": "Gmail"}}
    lines = mail_reply(ref="caixa-gmail#3")
    stored = item(lines)
    before, sha = json.dumps(stored["payload"]["card"], sort_keys=True), cards.content_sha256(stored)
    for approvable in (False, True):
        cards.effect_card_text(stored, cfg, True, False, approvable)
    assert json.dumps(stored["payload"]["card"], sort_keys=True) == before and cards.content_sha256(stored) == sha
    assert [l[1]["ref"] for l in stored["payload"]["card"] if l[0] == "CARD_MAIL_REPLY_TO"] == ["caixa-gmail#3"]


def test_two_reply_cards_that_differ_only_in_their_source_read_differently_and_the_terminal_is_unchanged():
    cfg = {"language": "pt-BR", "source_names": {"caixa-gmail": "Gmail", "caixa-outlook": "Outlook"}}
    first, second = mail_reply(ref="caixa-gmail#3"), mail_reply(ref="caixa-outlook#3")
    assert phone_card(first, cfg) != phone_card(second, cfg)
    assert phone_card(mail_reply(ref="caixa-gmail#3"), cfg) != phone_card(mail_reply(ref="caixa-gmail#7"), cfg)
    plain = {"language": "pt-BR"}
    terminal = lambda lines, c: cards.effect_card_text(item(lines), c, True, False, True)  # noqa: E731
    assert terminal(first, cfg) == terminal(first, plain), "the terminal never names a source by its plain name"


def test_a_card_without_a_message_reference_or_with_a_text_that_only_looks_like_one_is_not_renamed():
    cfg = {"language": "pt-BR", "source_names": {"caixa-gmail": "Gmail"}}
    for ref in ("ana@x · Pedido #12", "caixa-gmail#3 e mais", "x caixa-gmail#3", "caixa-gmail"):
        assert phone_card(mail_reply(ref=ref), cfg) == phone_card(mail_reply(ref=ref), {"language": "pt-BR"}), ref
    assert phone_card([line("CARD_MAIL_SEND"), line("CARD_MAIL_TO", addresses="caixa-gmail#3")], cfg).count("caixa-gmail#3") == 1, "only the reply lines carry a reference"


def test_the_rendering_without_the_name_would_not_tell_two_targets_apart(monkeypatch):
    """Vacuity of the test above: a `SRC_ITEM_CARD` that leaves the name out makes the two cards read alike."""
    cfg = {"language": "pt-BR", "source_names": {"caixa-gmail": "Gmail", "caixa-outlook": "Outlook"}}
    monkeypatch.setitem(phrases.TABLE["pt-BR"], "SRC_ITEM_CARD", "{n}")
    assert phone_card(mail_reply(ref="caixa-gmail#3"), cfg).replace("Gmail", "") == phone_card(mail_reply(ref="caixa-outlook#3"), cfg).replace("Outlook", "")


def test_the_reference_shape_of_the_card_module_is_the_one_of_the_item_references():
    assert cards.REFERENCE.pattern == st.load("item_refs").ITEM_REF.pattern, "messaging_cards keeps its own copy (the layer diagram gives it no edge to item_refs.py)"


def test_no_sentence_of_the_phrase_table_is_only_fields():
    """A sentence that is only a field would match every text in `phone_errors.spoken` and pass any English through to a phone (found by this package: the mail name was `{service}`)."""
    import string
    for tag, table in phrases.TABLE.items():
        for key, sentence in table.items():
            literals = "".join(lit for lit, _name, _spec, _conv in string.Formatter().parse(sentence))
            assert literals.strip(), (tag, key)


# --- the facade and the bridge hand the names to the card -------------------------------------------------------------------------------------------


def test_the_facade_gives_the_names_of_a_project_and_nothing_when_it_cannot_(world, snaps):
    two_mailboxes(world, snaps)
    assert ops.source_names(world["path"]) == {"caixa-gmail": "Gmail", "caixa-outlook": "Outlook"}
    assert ops.source_names(world["path"] + "/nowhere") == {}, "any failure is an empty table"
    assert "source_names" not in {r["call"] for r in st.load("operations").OPERATIONS}


def test_the_bridge_adds_the_names_to_the_settings_of_a_project_and_an_empty_table_when_it_has_none():
    shown = {"accepted": True, "language": "pt-BR", "messaging": {}}
    project_row = {"path": "/p"}

    def settings(facade):
        bridge = types.SimpleNamespace(ops=facade, platform="telegram")
        bridge.source_names = lambda p: messaging_bridge.Bridge.source_names(bridge, p)
        return messaging_bridge.Bridge.settings(bridge, project_row)
    ops_with = types.SimpleNamespace(config=lambda path: shown, source_names=lambda path: {"caixa-gmail": "Gmail"})
    assert settings(ops_with)["source_names"] == {"caixa-gmail": "Gmail"}
    assert settings(types.SimpleNamespace(config=lambda path: shown))["source_names"] == {}, "a facade without the helper"
    assert settings(types.SimpleNamespace(config=lambda path: shown, source_names=lambda path: 1 / 0))["source_names"] == {}, "a failure is not a refusal"
    assert settings(types.SimpleNamespace(config=lambda path: {"accepted": False}, source_names=lambda path: {})) is None
