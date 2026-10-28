"""A person's name in a mail target must be in the From, not only in the subject (package GROUNDING-FROM, limits L60 and L61; BL7-1 review finding 6).

The interpreter widens a mail `target` ("Gideon") with the subject the line gives after it ("about the warehouse lease") and records the words a message is found by
(`target_ground`: the person and the subject) and the person's own part (`target_sender`). Before this package every ground word was looked for in ONE set made of the From words and
the subject words, so a message from somebody else whose subject said "Gideon warehouse lease" matched all three words and became the card. Now `ops_natural_mail.mail_target_seed`
adds `sender_words` (the person's content words, only when they are fewer than the ground's) and `_by_words` matches them in `natural_writes_mail.from_words` (the address half) as
well. When no From holds the person but the union still matches, the messages are a numbered list (`NW_MAIL_ASK_SENDER`), even when there is one: never a direct card on words that only the
subject carried. The gate's value oracle and L60 (a reply goes to the index's From) are unchanged.

Held here, with literals of this file and invented names (`.example` addresses): `match_words` and `from_words`; the seed, with and without a ground and for a ground whose person adds
nothing; the flow over a stand-in index (a list of one, the person's own message as the card, a target that was not widened, the plural fallback, the newest, a day), in English and in
pt-BR; the interpreter's own decision for a widened target (`target_sender`), and vacuity cases that fail on a planted wrong result. Every sentence is compared by its phrase key
(T8). No model call. Offline.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_mail_grounding_from.py
"""
from __future__ import annotations

import datetime
from zoneinfo import ZoneInfo

import pytest

import standin_tree as st

item_refs = st.load("item_refs")
natural = st.load("natural")
nwm = st.load("natural_writes_mail")
onm = st.load("ops_natural_mail")
ops_natural = st.load("ops_natural")
phrases = st.load("phrases")

NOW = datetime.datetime(2026, 10, 27, 9, 30, tzinfo=ZoneInfo("America/Sao_Paulo"))
ANA = "ana.silva@harbor.example"
GIDEON = "gideon.park@acme.example"
LEASE_REPLY = "reply to Gideon about the warehouse lease"
LEASE_TARGET = "Gideon about the warehouse lease"
LEASE_GROUND = "Gideon the warehouse lease"
BODY = "we accept"
LEASE_PT = "responde o Gideon sobre o aluguel do galpão"      # validate: allow english-only -- the Portuguese line under test
TARGET_PT = "Gideon sobre o aluguel do galpão"      # validate: allow english-only -- the Portuguese line under test
GROUND_PT = "Gideon o aluguel do galpão"      # validate: allow english-only -- the Portuguese line under test


def entry(n, sender, subject):
    return {"n": n, "id": f"m{n}", "thread_id": f"t{n}", "message_id": f"<g{n}@harbor.example>", "from_address": sender, "reply_to_address": None, "subject": subject, "change_key": None}


ENTRIES = [entry(1, ANA, "Gideon warehouse lease"), entry(2, GIDEON, "warehouse lease renewal"), entry(3, "bob@acme.example", "Lunch on Friday")]
ANA_ONLY = [ENTRIES[0], ENTRIES[2]]


def patched_index(monkeypatch, entries):
    monkeypatch.setattr(onm, "_mail_sources", lambda ctx: [{"id": "inbox", "account": "google"}])
    monkeypatch.setattr(item_refs, "read_index", lambda ctx, source_id, **kw: {"source": source_id, "type": "mail", "entries": [dict(e) for e in entries]})
    monkeypatch.setattr(ops_natural, "_clock", lambda: NOW)


def decision(op, target, ground=None, sender=None, **spans):
    out = {"op": op, "spans": {"target": target, **spans}, "args": {}}
    if ground:
        out["target_ground"] = ground
    if sender:
        out["target_sender"] = sender
    return out


def resolve(dec, said=""):
    seed = onm.mail_target_seed(dec["op"], dec, None, said)
    assert seed is not None
    cfg = {"cfg": {"accounts": {"google": {"address": "pat@example.com", "mail_folders": {"contas": "L1"}}}}}
    return onm.resolve(cfg, dec["op"], seed["slots"], "chat", None)


def listed(out):
    """(the sentence key, the values of the options, the fields) of the question a resolution returned."""
    asked = out["ask"]
    return asked["sentence_key"], [o["value"] for o in asked["options"]], asked["fields"]


# --- the words of a From -----------------------------------------------------------------------------------------------------------------------


def test_from_words_are_the_address_half_and_entry_words_stay_the_union():
    assert nwm.from_words(ENTRIES[0]) == {"ana", "silva", "harbor"}, "the local part split on . _ - + and the domain labels but the last"
    assert nwm.from_words(entry(9, "pat_lee+news@mail.corp.example", "x")) == {"pat", "lee", "news", "mail", "corp"}
    assert nwm.from_words({"subject": "Gideon"}) == set() and nwm.from_words({"from_address": "nobody"}) == {"nobody"}, "an address with no domain is all local part, a missing one holds none"
    assert nwm.entry_words(ENTRIES[0]) == {"ana", "silva", "harbor", "gideon", "warehouse", "lease"}
    assert nwm.entry_words(ENTRIES[1]) == nwm.from_words(ENTRIES[1]) | {"warehouse", "lease", "renewal"}


def test_a_sender_word_must_be_in_the_from_and_no_sender_is_the_rule_of_before():
    words = ["gideon", "warehouse", "lease"]
    assert [e["n"] for e in nwm.match_words(ENTRIES, words)] == [1, 2], "no sender: Ana's subject carries the name, so both messages match as before"
    assert [e["n"] for e in nwm.match_words(ENTRIES, words, sender=())] == [1, 2] and nwm.match_words(ENTRIES, words, False, ()) == nwm.match_words(ENTRIES, words)
    assert [e["n"] for e in nwm.match_words(ENTRIES, words, sender=["gideon"])] == [2], "the name in a From, and the other words anywhere: only Gideon's own message"
    assert [e["n"] for e in nwm.match_words(ENTRIES, words, sender=["acme"])] == [2], "a domain label but the last is a From word"


def test_the_strict_match_needs_every_ground_word_and_the_sender_in_the_from():
    own = [entry(1, ANA, "Gideon warehouse lease"), entry(2, GIDEON, "warehouse lease renewal"), entry(3, "gideon.park@acme.example", "Lease for the warehouse and the dock")]
    words = ["gideon", "warehouse", "lease"]
    assert [e["n"] for e in nwm.match_words(own, words, sender=["gideon"])] == [2, 3], "Gideon's own messages hold the name in the From and the other words in the subject; Ana's holds the name only in the subject"
    assert [e["n"] for e in nwm.match_words(own, words, sender=["acme"])] == [2, 3], "a domain label but the last is a From word"
    assert nwm.match_words(own, words, sender=["harbor", "gideon"]) == [], "every sender word is needed: Ana's From has harbor but not gideon"
    assert [e["n"] for e in nwm.match_words(own, words, sender=["ana"])] == [1] and nwm.match_words(own, ["gideon"], sender=["example"]) == [], "the last label (example) is no From word"
    assert [e["n"] for e in nwm.match_words(own, words, newest=True, sender=["gideon"])] == [2], "newest keeps the lowest number among the strict matches"
    assert nwm.match_words(own, [], sender=["gideon"]) == [], "no words match nothing, whatever the sender"
    assert [e["n"] for e in nwm.match_words(own, words, sender=["", "gideon"])] == [2, 3], "an empty sender word is no word"


def test_vacuity_a_from_words_that_is_the_whole_entry_makes_the_sender_rule_match_the_subject(monkeypatch):
    own = [ENTRIES[0], ENTRIES[1]]
    words = ["gideon", "warehouse", "lease"]
    assert [e["n"] for e in nwm.match_words(own, words, sender=["gideon"])] == [2]
    real = nwm.from_words
    monkeypatch.setattr(nwm, "from_words", lambda e: real(e) | set(nwm._words_of(e.get("subject"))))          # the planted fault: the sender is looked for in the subject too
    assert [e["n"] for e in nwm.match_words(own, words, sender=["gideon"])] == [1, 2], "vacuity: with the plant Ana's subject carries the name again, so the assertion above can fail"


# --- the seed ----------------------------------------------------------------------------------------------------------------------------------


def test_a_widened_target_carries_the_senders_words_and_any_other_does_not():
    widened = onm.mail_target_seed("mail-reply", decision("mail-reply", LEASE_TARGET, LEASE_GROUND, "Gideon", body=BODY))
    assert widened["slots"] == {"words": ["gideon", "warehouse", "lease"], "sender_words": ["gideon"], "body": BODY}
    assert onm.mail_target_seed("mail-reply", decision("mail-reply", "the warehouse lease", body=BODY))["slots"] == {"words": ["warehouse", "lease"], "body": BODY}, "not widened: nothing tells a person from a topic"
    assert "sender_words" not in onm.mail_target_seed("mail-reply", decision("mail-reply", "Gideon", body=BODY, ))["slots"], "a plain target, with no ground, has no sender part"
    same = onm.mail_target_seed("mail-trash", decision("mail-trash", "Gideon the", "Gideon the", "Gideon"))
    assert same["slots"]["words"] == ["gideon"] and "sender_words" not in same["slots"], "a person that adds nothing to the ground leaves no sender rule"
    assert "sender_words" not in onm.mail_target_seed("mail-reply", decision("mail-reply", LEASE_TARGET, LEASE_GROUND, "", body=BODY))["slots"], "a ground with no recorded sender: today's rule"
    assert "sender_words" not in onm.mail_target_seed("mail-reply", decision("mail-reply", LEASE_TARGET, LEASE_GROUND, "the", body=BODY))["slots"], "a sender with no content word: no rule"
    assert onm.mail_target_seed("mail-reply", decision("mail-reply", "Gideon Park about the warehouse lease", "Gideon Park the warehouse lease", "Gideon Park", body=BODY))["slots"]["sender_words"] == ["gideon", "park"], "a name of two words"


def test_the_senders_words_are_kept_only_when_they_are_words_of_the_ground():
    odd = onm.mail_target_seed("mail-reply", decision("mail-reply", LEASE_TARGET, LEASE_GROUND, "Marta", body=BODY))
    assert "sender_words" not in odd["slots"], "a sender whose words are not in the ground is a record that does not match: the rule is not applied"


# --- the flow ----------------------------------------------------------------------------------------------------------------------------------


def test_the_subject_alone_carrying_the_name_is_a_list_of_one_and_never_a_card(monkeypatch):
    patched_index(monkeypatch, ANA_ONLY)
    out = resolve(decision("mail-reply", LEASE_TARGET, LEASE_GROUND, "Gideon", body=BODY), LEASE_REPLY)
    assert "args" not in out, "no card: the name is in the subject of Ana's message, not in a From"
    key, values, fields = listed(out)
    assert (key, values, fields) == ("NW_MAIL_ASK_SENDER", ["inbox#1"], {"count": 1})
    assert out["ask"]["options"][0]["label"] == f"{ANA} · Gideon warehouse lease", "the person sees the address the reply would go to"
    assert out["ask"]["slot"] == "chosen" and out["ask"]["multi"] is False and out["ask"]["keep"]["_listed"]["source"] == "inbox"


def test_the_pick_of_that_list_is_the_card_and_goes_to_the_from_of_the_index(monkeypatch):
    patched_index(monkeypatch, ANA_ONLY)
    dec = decision("mail-reply", LEASE_TARGET, LEASE_GROUND, "Gideon", body=BODY)
    seed = onm.mail_target_seed("mail-reply", dec, None, LEASE_REPLY)
    cfg = {"cfg": {"accounts": {"google": {"address": "pat@example.com"}}}}
    monkeypatch.setattr(onm, "_same_list", lambda ctx, listed_, channel, sender: None)
    out = onm.resolve(cfg, "mail-reply", dict(seed["slots"], chosen="inbox#1"), "chat", None)
    assert out["args"]["message"] == "inbox#1" and out["origins"]["message"] == "picked", "a pick among the messages code listed: origin picked, as for every list"


def test_the_persons_own_message_is_the_card_even_when_another_subject_carries_the_name(monkeypatch):
    patched_index(monkeypatch, ENTRIES)
    out = resolve(decision("mail-reply", LEASE_TARGET, LEASE_GROUND, "Gideon", body=BODY), LEASE_REPLY)
    assert out["args"]["message"] == "inbox#2" and out["origins"]["message"] == "grounded", "Gideon's From and the subject words: one card, to the indexed From"


def test_without_the_rule_the_same_two_messages_are_a_list_of_two(monkeypatch):
    patched_index(monkeypatch, ENTRIES)
    out = resolve(decision("mail-reply", "Gideon warehouse lease", body=BODY), "reply to Gideon warehouse lease")
    assert listed(out) == ("NW_MAIL_ASK_MESSAGE", ["inbox#1", "inbox#2"], {"count": 2}), "a target that was not widened is read as before: the union of From and subject"


def test_a_target_that_was_not_widened_is_unchanged(monkeypatch):
    patched_index(monkeypatch, ANA_ONLY)
    out = resolve(decision("mail-reply", "the warehouse lease email", body=BODY), "reply to the warehouse lease email")
    assert out["args"]["message"] == "inbox#1", "no ground, no sender: the one message that holds the words is the card, as before"


def test_a_pt_br_line_is_read_the_same_way(monkeypatch):
    own = [entry(1, ANA, "Gideon aluguel galpão"), entry(2, GIDEON, "aluguel do galpão renovação")]      # validate: allow english-only -- an invented Portuguese subject
    patched_index(monkeypatch, own[:1])
    asked = resolve(decision("mail-reply", TARGET_PT, GROUND_PT, "Gideon", body="aceito"), LEASE_PT)      # validate: allow english-only -- the Portuguese line under test
    assert listed(asked) == ("NW_MAIL_ASK_SENDER", ["inbox#1"], {"count": 1})
    patched_index(monkeypatch, own)
    card = resolve(decision("mail-reply", TARGET_PT, GROUND_PT, "Gideon", body="aceito"), LEASE_PT)      # validate: allow english-only -- the Portuguese line under test
    assert card["args"]["message"] == "inbox#2"


def test_nothing_found_by_either_rule_is_the_plain_sentence_of_none(monkeypatch):
    patched_index(monkeypatch, [entry(3, "bob@acme.example", "Lunch on Friday")])
    out = resolve(decision("mail-reply", LEASE_TARGET, LEASE_GROUND, "Gideon", body=BODY), LEASE_REPLY)
    assert out["say"]["sentence_key"] == "NW_MAIL_NONE" and out["say"]["fields"]["words"] == "gideon warehouse lease"


def test_several_messages_that_hold_the_words_only_in_the_subject_are_a_list_of_all_of_them(monkeypatch):
    patched_index(monkeypatch, [entry(1, ANA, "Gideon warehouse lease"), entry(2, "li.wu@harbor.example", "Re: Gideon warehouse lease")])
    assert listed(resolve(decision("mail-reply", LEASE_TARGET, LEASE_GROUND, "Gideon", body=BODY), LEASE_REPLY)) == ("NW_MAIL_ASK_SENDER", ["inbox#1", "inbox#2"], {"count": 2})


def test_the_newest_keeps_its_rule_and_is_a_list_of_one_when_only_the_subject_carries_the_name(monkeypatch):
    patched_index(monkeypatch, [entry(1, ANA, "Gideon warehouse lease"), entry(2, "li.wu@harbor.example", "Re: Gideon warehouse lease")])
    dec = decision("mail-reply", LEASE_TARGET, LEASE_GROUND, "Gideon", body=BODY)
    seed = onm.mail_target_seed("mail-reply", dec, None, LEASE_REPLY)
    cfg = {"cfg": {"accounts": {"google": {"address": "pat@example.com"}}}}
    out = onm.resolve(cfg, "mail-reply", dict(seed["slots"], newest=True), "chat", None)
    assert listed(out) == ("NW_MAIL_ASK_SENDER", ["inbox#1"], {"count": 1}), "the newest of the union, shown, not taken"


def test_a_plural_line_falls_back_to_a_multiple_choice_list_and_takes_every_message_the_sender_holds(monkeypatch):
    several = [entry(1, ANA, "Gideon warehouse lease"), entry(2, GIDEON, "warehouse lease renewal"), entry(3, "gideon.park@acme.example", "Lease: warehouse keys")]
    patched_index(monkeypatch, several)
    plural = decision("mail-archive", "Gideon about the warehouse lease emails", "Gideon warehouse lease emails", "Gideon")
    said = "archive the emails from Gideon about the warehouse lease"
    out = resolve(plural, said)
    assert out["args"]["messages"] == "inbox#2,inbox#3", "the strict match: every message with the name in the From and the words, one card"
    patched_index(monkeypatch, ANA_ONLY)
    asked = resolve(plural, said)
    assert listed(asked) == ("NW_MAIL_ASK_SENDER", ["inbox#1"], {"count": 1}) and asked["ask"]["multi"] is True, "only the subject carries the name: a list to choose from, never a card"


def test_a_day_is_still_applied_to_the_messages_the_sender_rule_found(monkeypatch):
    dated = [dict(entry(1, ANA, "Gideon warehouse lease"), received="2026-10-26T12:00:00Z"), dict(entry(2, GIDEON, "warehouse lease renewal"), received="2026-10-20T12:00:00Z")]
    patched_index(monkeypatch, dated)
    dec = decision("mail-reply", LEASE_TARGET, LEASE_GROUND, "Gideon", body=BODY, day="dia 26/10/2026")      # validate: allow english-only -- the Portuguese line under test
    day = {"kind": "day", "value": "2026-10-26", "today": "2026-10-27", "zone": "America/Sao_Paulo"}
    seed = onm.mail_target_seed("mail-reply", dec, day, LEASE_REPLY)
    cfg = {"cfg": {"accounts": {"google": {"address": "pat@example.com"}}}}
    out = onm.resolve(cfg, "mail-reply", seed["slots"], "chat", None)
    assert out["say"]["sentence_key"] == "NW_MAIL_NONE", "Gideon's own message is of another day; Ana's is of the day but is not from Gideon, and the strict match found his, so the day leaves none"


def test_the_sentence_is_in_both_languages_and_names_no_count():
    for tag in ("en", "pt-BR"):
        text = phrases.TABLE[tag]["NW_MAIL_ASK_SENDER"]
        assert text and "{count}" not in text and "{" not in text, "a sentence that reads the same for one message and for several"
    assert phrases.TABLE["en"]["NW_MAIL_ASK_SENDER"] != phrases.TABLE["pt-BR"]["NW_MAIL_ASK_SENDER"]


# --- vacuity: a planted wrong result fails the assertions above ----------------------------------------------------------------------------------


def test_vacuity_without_the_fallback_rule_the_subject_alone_is_a_card(monkeypatch):
    patched_index(monkeypatch, ANA_ONLY)
    dec = decision("mail-reply", LEASE_TARGET, LEASE_GROUND, "Gideon", body=BODY)
    assert "args" not in resolve(dec, LEASE_REPLY)
    real = nwm.match_words
    monkeypatch.setattr(nwm, "match_words", lambda entries, words, newest=False, sender=(): real(entries, words, newest))          # the planted fault: the sender words are ignored
    out = resolve(dec, LEASE_REPLY)
    assert out["args"]["message"] == "inbox#1", "vacuity: with the plant Ana's subject is a card again, so the list assertion above can fail"


def test_vacuity_a_seed_without_the_senders_words_is_the_union_rule(monkeypatch):
    patched_index(monkeypatch, ENTRIES)
    dec = decision("mail-reply", LEASE_TARGET, LEASE_GROUND, "Gideon", body=BODY)
    assert resolve(dec, LEASE_REPLY)["args"]["message"] == "inbox#2"
    plain = dict(dec)
    del plain["target_sender"]
    assert listed(resolve(plain, LEASE_REPLY))[1] == ["inbox#1", "inbox#2"], "vacuity: with no sender recorded both messages are listed, so the card above is the sender rule's work"


# --- the interpreter's own decision, end to end -------------------------------------------------------------------------------------------------


import interpreter_kit as kit

interp = st.load("interpreter")


def checked(line, slots, operation="mail-reply"):
    got = interp.check({"v": 1, "kind": "op", "op": operation, "slots": slots}, line, None, kit.CATALOG, kit.NOW, kit.ZONE, kit.ALL_OPS)
    assert got["kind"] == "op", got
    return got


def test_the_check_records_the_persons_part_of_a_widened_target_and_of_a_target_with_its_own_subject():
    en = checked(LEASE_REPLY + " and say we accept", {"target": "Gideon", "body": BODY})
    assert en["spans"]["target"] == LEASE_TARGET and en["target_ground"] == LEASE_GROUND and en["target_sender"] == "Gideon", "BL7-1's widening: the person is the model's own target"
    pt = checked(LEASE_PT + " dizendo que aceito", {"target": "Gideon", "body": "que aceito"})      # validate: allow english-only -- the Portuguese line under test
    assert pt["spans"]["target"] == TARGET_PT and pt["target_ground"] == GROUND_PT and pt["target_sender"] == "Gideon"
    own = checked("Reply to Nadia Ferreira about the volunteer schedule for the book fair, thank her for the help", {"target": "Nadia Ferreira about the volunteer schedule for the book fair", "body": "thank her for the help"})
    assert own["target_sender"] == "Nadia Ferreira" and own["target_ground"].startswith("Nadia Ferreira "), "BL7-5's long target: unchanged"
    plain = checked("reply to Gideon and say we accept", {"target": "Gideon", "body": BODY})
    assert "target_ground" not in plain and "target_sender" not in plain, "a bare target has neither"


def test_the_decision_of_the_check_is_the_seed_that_wants_the_name_in_the_from(monkeypatch):
    dec = checked(LEASE_REPLY + " and say we accept", {"target": "Gideon", "body": BODY})
    assert onm.mail_target_seed("mail-reply", dec, None, LEASE_REPLY)["slots"]["sender_words"] == ["gideon"]
    patched_index(monkeypatch, ANA_ONLY)
    assert listed(resolve(dec, LEASE_REPLY))[0] == "NW_MAIL_ASK_SENDER", "Ana's subject carries the name: a list, not a card"
    patched_index(monkeypatch, ENTRIES)
    assert resolve(dec, LEASE_REPLY)["args"]["message"] == "inbox#2"


def test_a_long_target_names_its_person_too_and_a_subject_only_message_is_a_list(monkeypatch):
    line = "Reply to Nadia Ferreira about the volunteer schedule for the book fair, thank her for the help"
    dec = checked(line, {"target": "Nadia Ferreira about the volunteer schedule for the book fair", "body": "thank her for the help"})
    assert onm.mail_target_seed("mail-reply", dec, None, line)["slots"]["sender_words"] == ["nadia", "ferreira"]
    patched_index(monkeypatch, [entry(1, "li.wu@feira.example", "Nadia Ferreira volunteer schedule for the book fair")])
    assert listed(resolve(dec, line)) == ("NW_MAIL_ASK_SENDER", ["inbox#1"], {"count": 1})
    patched_index(monkeypatch, [entry(1, "nadia.ferreira@feira.example", "Volunteer schedule for the book fair")])
    assert resolve(dec, line)["args"]["message"] == "inbox#1"
