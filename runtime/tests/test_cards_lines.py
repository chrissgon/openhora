"""The card of an effect said line by line in the project's language (package FND; runtime/phrases.py `card_valid` and `card_text`, runtime/messaging_cards.py
`effect_card_text`). A write to the person's own accounts stores, beside its English body, `payload["card"]`: its lines as [key, {field: text}] of the phrase
table's family CARD_. The messaging card says them in the language of the project when, and only when, the card is well formed AND its English lines are the
stored body; the values of the fields are the person's or a service's words and are never changed; the hash on the card is the effect's own in every language.
Offline, no model.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_cards_lines.py
"""
from __future__ import annotations

import string

import pytest

import phrase_kit as pk
import standin_tree as st

phrases = st.load("phrases")
cards = st.load("messaging_cards")
operations = st.load("operations")

HASH = "e" * 64
PT = {"language": "pt-BR"}
CAPS = {"buttons": True, "max_buttons": 6, "max_text": 4096, "documents": False, "url_buttons": True, "reply_context": True}
POLICY = {"messaging": ["read", "approve-effect-send"]}
TITLE_WORDS = "Dentist, 'Check-up' {account} {n}"      # the person's words: braces, quotes, a name the table never says


@pytest.fixture
def table(monkeypatch):
    monkeypatch.setitem(phrases.TABLE["en"], "CARD_TEST_BODY", "Message:\n{body}")
    monkeypatch.setitem(phrases.TABLE["pt-BR"], "CARD_TEST_BODY", "Mensagem:\n{body}")
    """Two lines of a pretend kind, in both columns of the table (the real kinds add their own with their packages)."""
    monkeypatch.setitem(phrases.TABLE["en"], "CARD_TEST_TITLE", "Title: {title}")
    monkeypatch.setitem(phrases.TABLE["en"], "CARD_TEST_NOBODY", "No one is invited: no e-mail is sent.")
    monkeypatch.setitem(phrases.TABLE["pt-BR"], "CARD_TEST_TITLE", "Título: {title}")
    monkeypatch.setitem(phrases.TABLE["pt-BR"], "CARD_TEST_NOBODY", "Ninguém é convidado: nenhum e-mail é enviado.")


def lines(title=TITLE_WORDS):
    return [["CARD_ACCOUNT", {"account": "google", "address": "ana@mail.example"}], ["CARD_TEST_TITLE", {"title": title}], ["CARD_TEST_NOBODY", {}]]


def effect(card, body=None, word="send", **more):
    body = phrases.card_text(card) if body is None and phrases.card_valid(card) else body if body is not None else "stored body"
    return {"id": 7, "kind": "effect", "title": "Mail: send", "body": body, "status": "open", "task_id": 1, "actions": ["approved", "rejected"],
            "effect_word": word, "effect_on_cards": True, "payload_sha256": HASH, "payload": {"card": card}, **more}


def build(item, cfg=None, **kw):
    return cards.build("northwind", item, CAPS, POLICY, "text", None, operations=operations, cfg=cfg, **kw)


# --- the rule of a well-formed card ---------------------------------------------------------------------------------------------------------------


def test_a_card_of_keys_of_the_family_with_exactly_their_fields_is_valid(table):
    assert phrases.card_valid(lines()) is True
    assert phrases.card_valid(tuple(tuple(line) for line in lines())) is True, "a stored JSON list or a tuple: the same"


@pytest.mark.parametrize("bad", [
    None, "CARD_ACCOUNT", [], {}, 5, [["CARD_ACCOUNT"]], [["CARD_ACCOUNT", {}, 1]], ["CARD_ACCOUNT"],
    [["STALE", {}]],                                                                   # a key outside the family
    [["card_account", {"account": "g", "address": "a"}]],                              # the wrong case
    [["CARD_NOT_IN_THE_TABLE", {}]],                                                   # a key the English table lacks
    [[7, {}]],
    [["CARD_ACCOUNT", {"account": "g"}]],                                              # a missing field
    [["CARD_ACCOUNT", {"account": "g", "address": "a", "extra": "b"}]],                # an extra field
    [["CARD_ACCOUNT", {"account": "g", "address": 5}]],                                # a field that is not a text
    [["CARD_ACCOUNT", {"account": "g", "address": None}]],
    [["CARD_ACCOUNT", [["account", "g"]]]],                                            # fields that are not an object
    [["CARD_ACCOUNT", {"account": "g", 4: "a"}]],
])
def test_anything_else_is_no_card(bad):
    assert phrases.card_valid(bad) is False


def test_a_card_has_a_limit_of_lines(table):
    one = ["CARD_TEST_NOBODY", {}]
    assert phrases.card_valid([one] * phrases.CARD_LINES_MAX) is True and phrases.card_valid([one] * (phrases.CARD_LINES_MAX + 1)) is False


def placeholders(sentence):
    """Every placeholder of a sentence whole: (name, format spec, conversion), in order and as many times as it appears."""
    return [(name, spec, conv) for _lit, name, spec, conv in string.Formatter().parse(sentence) if name]


def test_every_card_key_of_the_table_is_in_both_languages_with_the_same_placeholders_format_spec_included_and_the_portuguese_one_differs():
    keys = [k for k in phrases.TABLE["en"] if k.startswith("CARD_")]
    assert "CARD_ACCOUNT" in keys
    for key in keys:
        assert phrases.CARD_FAMILY.fullmatch(key) and key in phrases.TABLE["pt-BR"]
        assert sorted(placeholders(phrases.TABLE["en"][key])) == sorted(placeholders(phrases.TABLE["pt-BR"][key])), key
        assert phrases.TABLE["en"][key] != phrases.TABLE["pt-BR"][key], key


def test_a_placeholder_with_another_format_spec_in_the_other_column_is_found_by_the_parity_check():
    assert sorted(placeholders("Size: {n:>5}")) != sorted(placeholders("Tamanho: {n}")) and sorted(placeholders("A {n!r}")) != sorted(placeholders("B {n}"))


# --- the card, said in the language ---------------------------------------------------------------------------------------------------------------


def test_the_card_is_said_line_by_line_in_portuguese_and_the_persons_words_are_not_changed(table):
    item = effect(lines())
    said = build(item, PT)["message"]["text"]
    assert pk.said(said, "CARD_ACCOUNT", PT, account="google", address="ana@mail.example") and pk.said(said, "CARD_TEST_TITLE", PT, title=TITLE_WORDS) and pk.said(said, "CARD_TEST_NOBODY", PT)
    assert not pk.said(said, "CARD_ACCOUNT", None) and not pk.said(said, "CARD_TEST_TITLE", None) and not pk.said(said, "CARD_TEST_NOBODY", None)


def test_the_english_lines_are_the_stored_body_and_an_english_project_shows_it_unchanged(table):
    card = lines()
    body = phrases.card_text(card).split("\n")
    assert len(body) == 3
    pk.assert_said(body[0], "CARD_ACCOUNT", None, account="google", address="ana@mail.example")
    pk.assert_said(body[1], "CARD_TEST_TITLE", None, title=TITLE_WORDS)
    pk.assert_said(body[2], "CARD_TEST_NOBODY", None)
    item = effect(card)
    for cfg in (None, {}, {"language": "en"}, {"language": "fr"}):         # a tag with no table says English
        said = build(item, cfg)["message"]["text"]
        assert phrases.card_text(card) in said
    plain = {**item, "payload": {}}
    assert build(plain)["message"]["text"] == build(item)["message"]["text"], "a card with lines in English is the card of the stored body"


def test_the_hash_of_the_card_is_the_effects_own_in_both_languages_and_the_approval_line_carries_it(table):
    item = effect(lines())
    english, portuguese = build(item), build(item, PT)
    assert english["content_sha256"] == portuguese["content_sha256"] == HASH
    assert phrases.text("APPROVES_LINE", None, sha=HASH) in english["message"]["text"] and phrases.text("APPROVES_LINE", PT, sha=HASH) in portuguese["message"]["text"]
    assert english["whole"] is portuguese["whole"] is True and portuguese["approvable"] is True and english["approvable"] is True


def test_the_title_of_the_card_is_the_stored_one_and_a_translated_heading_is_still_the_tables_job(table):
    item = effect(lines())
    assert "Mail: send" in build(item, PT)["message"]["text"], "a title no table row covers is shown as stored: code wrote it, no model or person did"


def test_a_long_card_goes_as_a_document_with_the_translated_text(table):
    long_title = "x" * 5000
    item = effect(lines(long_title))
    card = cards.build("northwind", item, {**CAPS, "documents": True}, POLICY, "text", None, operations=operations, cfg=PT)
    assert card["message"]["document"] is not None and pk.said(card["message"]["document"]["text"], "CARD_TEST_TITLE", PT, title=long_title) and card["whole"] is True


def test_the_count_notice_carries_nothing_of_the_card(table):
    item = effect(lines())
    said = cards.build("northwind", item, CAPS, POLICY, "count", None, operations=operations, cfg=PT)["message"]["text"]
    assert "ana@mail.example" not in said and TITLE_WORDS not in said


# --- what falls back to the stored body ------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("card", [
    [["STALE", {}]],                                                                    # a key outside the family
    [["CARD_ACCOUNT", {"account": "g", "address": 5}]],                                 # a field that is not a text
    [["CARD_ACCOUNT", {"account": "g"}]],                                               # a missing field
    [["CARD_UNKNOWN_KEY", {}]],
    "CARD_ACCOUNT", [], None,
])
def test_a_card_that_is_not_well_formed_falls_back_to_the_stored_body(table, card):
    item = effect(card, body="Account: g (a)\nthe stored body")
    said = build(item, PT)["message"]["text"]
    assert "the stored body" in said and not pk.said(said, "CARD_ACCOUNT", PT)


def test_a_card_whose_english_lines_are_not_the_stored_body_falls_back_too(table):
    """A card that says one thing while the decision's body says another is never shown: the stored body is."""
    item = effect(lines(), body="Account: google (ana@mail.example)\nTitle: something else\nNo one is invited: no e-mail is sent.")
    said = build(item, PT)["message"]["text"]
    assert "something else" in said and not pk.said(said, "CARD_ACCOUNT", PT) and not pk.said(said, "CARD_TEST_TITLE", PT)


def test_a_card_on_a_decision_that_is_not_an_effect_is_ignored(table):
    other = {**effect(lines()), "kind": "question", "actions": ["answered"], "payload": {"card": lines()}}
    said = build(other, PT)["message"]["text"]
    assert not pk.said(said, "CARD_ACCOUNT", PT)


def test_the_values_of_the_fields_are_never_parsed_as_sentences(table):
    """Braces in a person's words are text: the table's format is applied to the template, never to a value."""
    card = [["CARD_TEST_TITLE", {"title": "{title} {0} {account!r} %s {{}}"}]]
    pk.assert_said(phrases.card_text(card, PT), "CARD_TEST_TITLE", PT, title="{title} {0} {account!r} %s {{}}")
    assert "{title} {0}" in build(effect(card), PT)["message"]["text"]


def test_the_stored_body_of_an_effect_with_lines_is_the_english_lines_joined(table):
    """The rule a kind's body() follows: the same function the card uses, with no language."""
    card = lines()
    assert phrases.card_text(card) == "\n".join(phrases.text(k, None, **f) for k, f in card)
    assert phrases.card_text(card, None) == phrases.card_text(card, {"language": "en"})


# --- hidden characters ---------------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["a\nb", "a\tb", "a\rb", "a\x00b", "a\x1bb", "a\u202eb", "a\u200bb", "a\u200db", "a\ufeffb", "a\u2028b", "a\u2029b",
                                   "a\u2066b", "a\udc80b", "a\ue000b", "\u202e"])
def test_a_field_with_a_control_format_separator_surrogate_or_private_use_character_makes_the_card_no_card(table, value):
    assert phrases.card_valid([["CARD_TEST_TITLE", {"title": value}]]) is False


@pytest.mark.parametrize("value", ["plain", "Dentist, 'Check-up' {x}", "Café — 14:00 (réunion)", "日本語", "emoji \U0001f600", ""])
def test_ordinary_text_in_any_script_is_fine(table, value):
    assert phrases.card_valid([["CARD_TEST_TITLE", {"title": value}]]) is True


def test_a_field_declared_multi_line_may_hold_line_ends_and_tabs_but_nothing_hidden(table):
    assert phrases.card_valid([["CARD_TEST_BODY", {"body": "line one\nline two\n\tindented"}]]) is True
    for bad in ("a\rb", "a\u202eb", "a\u2028b", "a\u200bb", "a\x00b", "a\x1bb"):
        assert phrases.card_valid([["CARD_TEST_BODY", {"body": bad}]]) is False, repr(bad)
    assert set(phrases.CARD_MULTILINE) == {"body", "text", "notes", "content", "change"}


def test_a_hidden_character_card_is_not_said_in_the_other_language_the_stored_body_is_shown(table):
    item = effect([["CARD_TEST_TITLE", {"title": "Dentist \u202e"}]], body="Title: Dentist \u202e")
    said = build(item, PT)["message"]["text"]
    assert not pk.said(said, "CARD_TEST_TITLE", PT) and pk.said(said, "CARD_TEST_TITLE", None, title="Dentist \u202e")
