"""What a phone is told when it is refused (slice S10, limit L62; runtime/phone_refusal.py, `ops_interpret._refusal`, the typed-command and natural-request paths of
runtime/ops_say.py and runtime/ops_natural.py, and the net in `Bridge.reply`): ONE plain sentence in the chat's language, with no slash command, no "error:" and no name of an
operation. The page, the terminal and the conversation keep the precise text.

THE ORACLE reads the text with this file's own literals (the two sentences, the words it must not hold). It never calls the code under test to decide what is right. The sweep
walks every operation the table lists (only for the NAMES; the expectation is the literal) on the channel `messaging`; the vacuity cases plant the old text and show the same
oracle flags it, and a text that is not a refusal and shows the net leaves it alone.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_phone_refusal.py
"""
from __future__ import annotations

import pytest

import standin_tree as st
from phone_literals import PLAIN_REFUSAL, PLAIN_REFUSAL_PT

phone_refusal = st.load("phone_refusal")
operations = st.load("operations")
phrases = st.load("phrases")

EN_ELSEWHERE = "That is not done from a message. Do it on the platform's page."
PT_ELSEWHERE = "Isso não é feito por mensagem. Faça na página da plataforma."  # validate: allow english-only -- the Portuguese sentence under test
OLD = "/file-read is not enabled for this channel; the project's configuration (channels.messaging) turns it on"
EN, PT = {}, {"language": "pt-BR"}


def a_phone_may_read(text: str, name: str) -> bool:
    """The oracle: a plain sentence holds no slash, no `error`, no internal key of the configuration and not the operation's name."""
    low = text.lower()
    return "/" not in text and "error" not in low and "channels." not in low and name not in low and "configuration" not in low


def test_the_sentence_in_both_languages_and_with_the_page_link():
    assert phone_refusal.sentence(EN) == PLAIN_REFUSAL and phone_refusal.sentence(None) == PLAIN_REFUSAL
    assert phone_refusal.sentence(PT) == PLAIN_REFUSAL_PT
    assert phone_refusal.sentence({"messaging": {"page_url": "https://page.example/open"}}) == (
        "You do not have permission for that here yet. It can be enabled on the platform's page: https://page.example/open")      # a link is never closed by a stop


def test_on_a_phone_the_reply_is_the_plain_sentence_and_everywhere_else_the_precise_text():
    assert phone_refusal.said(OLD, "messaging", EN) == PLAIN_REFUSAL and phone_refusal.said(OLD, "messaging", PT) == PLAIN_REFUSAL_PT
    for channel in ("page", "terminal", "chat", "mcp", None):
        assert phone_refusal.said(OLD, channel, EN) == "error: " + OLD, channel


NAMES = [row["name"] for row in operations.OPERATIONS]


@pytest.mark.parametrize("name", NAMES)
def test_every_refusal_the_operations_layer_can_word_reaches_a_phone_as_a_plain_sentence(name):
    for text in (operations.not_enabled(name, "messaging"), "error: " + operations.not_enabled(name, "messaging"), f"error: /{name} is not done from a messaging app"):
        said = phone_refusal.plain(text, EN)
        assert said in (PLAIN_REFUSAL, EN_ELSEWHERE), (name, text)
        assert a_phone_may_read(said, name), (name, said)
        assert phone_refusal.plain(text, PT) in (PLAIN_REFUSAL_PT, PT_ELSEWHERE)


def test_vacuity_the_old_text_fails_the_oracle_and_a_text_that_is_not_a_refusal_is_left_alone():
    assert not a_phone_may_read(OLD, "file-read") and not a_phone_may_read("error: " + OLD, "file-read")      # the oracle sees the old wording
    for text in ("Noted.", "Checked quote [lease-contract]", f"I read: {OLD} and then more", "/pending is not enabled", "", "error: ", "the /ask line is not enabled for this channel"):
        assert phone_refusal.plain(text, EN) == text, text
    assert phone_refusal.plain(None, EN) is None


def test_ops_interpret_refusal_is_the_plain_sentence_and_its_fallback_has_no_error_prefix():
    ops_interpret = st.load("ops_interpret")
    ctx = {"cfg": {"channels": {"messaging": ["talk"]}}}
    assert ops_interpret._refusal(ctx, "pending", "telegram:1") == PLAIN_REFUSAL      # the group `read` is not held
    ctx_pt = {"cfg": {"channels": {"messaging": ["talk"]}, "language": "pt-BR"}}
    assert ops_interpret._refusal(ctx_pt, "pending", "telegram:1") == PLAIN_REFUSAL_PT
    allowed = {"cfg": {"channels": {"messaging": ["read", "talk"]}}}
    again = ops_interpret._refusal(allowed, "pending", "telegram:1")      # the policy lets it through now: the interpreter asks again, as a sentence and not as an error
    assert again == phrases.text("IX_ASK_AGAIN", allowed["cfg"]) and not again.startswith("error")


def test_a_place_where_it_is_done_is_not_told_as_a_permission():
    for refused in ("/set-mode is done in the terminal or on the page", "/sync is done in the terminal", "/x is not done on this channel"):
        assert phone_refusal.said(refused, "messaging", EN) == EN_ELSEWHERE, refused
        assert phone_refusal.said(refused, "messaging", PT) == PT_ELSEWHERE
        assert phone_refusal.said(refused, "page", EN) == "error: " + refused
