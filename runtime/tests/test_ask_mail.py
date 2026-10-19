"""The group `ask-mail` (package NR-2, the maintainer's decision of 2026-10-18, superseding the RT-1 rule for its holders): a messaging sender whose profile lists it
may ask about the mail and calendar sources of the project from a messaging app, and those sources join the automatic selection of that sender's questions; a
sender without it keeps the RT-1 rule exactly (only `@<id>`, only the terminal, the conversation's own shell and the page), the terminal is unchanged, the group
adds to `ask` and never grants it, it is valid on a messaging app alone, and a file that gives a profile the group is accepted only with `--widen`. The stand-in
tree and answer skill of runtime/tests/standin_tree.py; every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_ask_mail.py
"""
from __future__ import annotations

import pytest

import standin_tree as st
from test_ask import OWNER, OWNER_KEY, STAFF, STAFF_KEY, accept, ask, run_files, runs, tree, two, write_config  # noqa: F401
from test_ask_snapshots import AGENDA, INBOX, copied, snapshot

ops = st.load("ops")
ops_ask = st.load("ops_ask")
operations = st.load("operations")
project_config = st.load("project_config")

MAILER, ASK_ONLY, MAIL_NO_ASK = "55119000000010", "55119000000011", "55119000000012"
PROFILES = {"mailer": ["read", "talk", "ask", "ask-mail"], "asker": ["read", "talk", "ask"], "mail-only": ["read", "talk", "ask-mail"]}
SENDERS = {"telegram": [{"id": MAILER, "policy": "mailer"}, {"id": ASK_ONLY, "policy": "asker"}, {"id": MAIL_NO_ASK, "policy": "mail-only"}]}
KEYS = {n: f"telegram:{n}" for n in (MAILER, ASK_ONLY, MAIL_NO_ASK)}


@pytest.fixture
def mixed(two):
    snapshot(two, "inbox", "mail", INBOX, "gmail:box=inbox;days=7;max=50")
    snapshot(two, "agenda", "calendar", AGENDA, "google:calendar=primary;past=0;ahead=14")
    accept(two["path"], policies=PROFILES, messaging={"senders": SENDERS})
    return two


def read_sources(out) -> set:
    return {s["source"] for s in out["sources"]}


def test_a_holder_may_name_a_mail_or_calendar_source_from_a_messaging_app(mixed):
    out = ask(mixed, "what is the prazo in @inbox and what is in @agenda?", channel="messaging", sender=KEYS[MAILER])
    assert out["ran"] is True and [s["source"] for s in out["sources"]] == ["inbox", "agenda"] and out["refusal"] is None
    assert any(f.endswith("inbox/converted.md") for f in copied(mixed, out))


def test_the_snapshots_join_the_automatic_selection_of_a_holders_questions(mixed):
    out = ask(mixed, "o que ha de novo?", channel="messaging", sender=KEYS[MAILER])
    assert out["ran"] is True and read_sources(out) == {"lease-contract", "meeting-notes", "inbox", "agenda"}


def test_a_sender_without_the_group_keeps_the_rt_1_rule_exactly(mixed):
    for text in ("what is the prazo in @inbox?", "compare @lease-contract with @agenda"):
        out = ask(mixed, text, channel="messaging", sender=KEYS[ASK_ONLY])
        assert out["reply"] == ops_ask.SNAPSHOT_HERE and out["refusal"] == "snapshot-channel" and out["ran"] is False and out["sources"] == [], text
    before = len(runs(mixed))
    plain = ask(mixed, "o que ha de novo?", channel="messaging", sender=KEYS[ASK_ONLY])
    assert read_sources(plain) == {"lease-contract", "meeting-notes"}, "no snapshot in the automatic selection of a sender without the group"
    assert len(runs(mixed)) == before + 1


def test_the_terminal_the_conversation_and_the_page_are_unchanged(mixed):
    for channel in ("terminal", "chat", "page"):
        named = ask(mixed, "what is in @inbox?", channel=channel)
        assert read_sources(named) == {"inbox"}, channel
        auto = ask(mixed, "o que ha de novo?", channel=channel)
        assert read_sources(auto) == {"lease-contract", "meeting-notes"}, f"{channel}: a snapshot is read only when it is named"


def test_the_group_adds_to_ask_and_never_grants_it(mixed):
    out = None
    with pytest.raises(ops.OpsError, match="not enabled"):
        out = ask(mixed, "what is in @inbox?", channel="messaging", sender=KEYS[MAIL_NO_ASK])
    assert out is None
    cfg = ops.config(mixed["path"])
    policy = project_config.load(mixed["path"])["channels"]
    assert operations.permitted("ask", "messaging", policy, None, KEYS[MAIL_NO_ASK]) is False
    assert operations.permitted("ask", "messaging", policy, None, KEYS[MAILER]) is True and cfg


def test_a_holder_is_one_who_lists_the_group_and_no_channel_without_an_entry_holds_it(mixed):
    policy = project_config.load(mixed["path"])["channels"]
    assert operations.holds("ask-mail", "messaging", policy, KEYS[MAILER]) is True
    assert operations.holds("ask-mail", "messaging", policy, KEYS[ASK_ONLY]) is False
    assert operations.holds("ask-mail", "messaging", policy, "telegram:unknown") is False
    for channel in ("terminal", "chat", "page", "mcp"):
        assert operations.holds("ask-mail", channel, policy, None) is False, channel
    assert operations.holds("ask-mail", "messaging", None, KEYS[MAILER]) is False
    assert operations.holds("nonsense", "messaging", policy, KEYS[MAILER]) is False


def test_the_group_is_valid_on_a_messaging_app_alone_and_is_in_no_default(two):
    assert "ask-mail" in operations.MESSAGING_ONLY_GROUPS and "ask-mail" not in operations.DEFAULT_POLICY["messaging"]
    for channel in ("page", "mcp"):
        assert "messaging app alone" in operations.group_refusal(channel, "ask-mail") or "valid on a messaging app only" in operations.group_refusal(channel, "ask-mail")
    assert operations.group_refusal("messaging", "ask-mail") is None
    write_config(two["path"], channels={"page": ["read", "ask-mail"]})
    with pytest.raises(project_config.ConfigError, match="ask-mail"):
        project_config.load(two["path"])


def test_a_file_that_gives_a_profile_the_group_is_accepted_only_with_widen(two):
    accept(two["path"], policies={"asker": ["read", "talk", "ask"]}, messaging={"senders": {"telegram": [{"id": ASK_ONLY, "policy": "asker"}]}})
    write_config(two["path"], policies={"asker": ["read", "talk", "ask", "ask-mail"]})
    shown = ops.config(two["path"])
    assert any("ask-mail" in str(line) for line in shown["widening"]), "the widening list names the group"
    with pytest.raises(ops.OpsError, match="widen"):
        ops.accept_config(two["path"], shown["sha256"])
    ops.accept_config(two["path"], shown["sha256"], widen=shown["widening_sha256"])
    assert operations.holds("ask-mail", "messaging", project_config.load(two["path"])["channels"], KEYS[ASK_ONLY]) is True


def test_the_group_text_says_what_the_holder_gives_away():
    assert "mail and calendar" in operations.GROUP_TEXT["ask-mail"] and "never grants it" in operations.GROUP_TEXT["ask-mail"] and len(operations.GROUP_TEXT["ask-mail"]) < 220


# --- the supervisor's decision from the review of #481: ask-mail is a sender's own, never a channel's -------------------------------------------------

item_refs = st.load("item_refs")
cards = st.load("messaging_cards")
ops_core = st.load("ops_core")


def test_ask_mail_is_given_in_one_listed_senders_profile_and_never_to_a_whole_channel(two):
    sentence = "never to a whole channel"
    write_config(two["path"], channels={"messaging": ["read", "talk", "ask", "ask-mail"]})
    with pytest.raises(project_config.ConfigError, match=sentence):
        project_config.load(two["path"])
    write_config(two["path"], channels={"messaging": "holder"}, policies={"holder": ["read", "talk", "ask", "ask-mail"]})
    with pytest.raises(project_config.ConfigError, match=sentence):      # a profile the CHANNEL names is channel-wide too
        project_config.load(two["path"])
    write_config(two["path"], channels={"messaging": ["read", "talk", "ask"]}, policies={"holder": ["read", "talk", "ask", "ask-mail"]},
                 messaging={"senders": {"telegram": [{"id": MAILER, "policy": "holder"}]}})
    assert project_config.load(two["path"])["channels"]["senders"][KEYS[MAILER]] == ["read", "talk", "ask", "ask-mail"]


def test_the_private_lines_of_a_card_and_a_reference_into_a_snapshot_are_the_holders_alone(mixed):
    policy = project_config.load(mixed["path"])["channels"]
    ctx = ops_core.context(mixed["path"])
    assert cards.reads_private(policy, KEYS[MAILER], operations) is True
    assert cards.reads_private(policy, KEYS[ASK_ONLY], operations) is False and cards.reads_private(policy, "telegram:unknown", operations) is False
    assert cards.reads_private(policy, None, operations) is False and cards.reads_private(None, KEYS[MAILER], operations) is False
    assert item_refs.may_read(ctx, "messaging", KEYS[MAILER]) is True
    assert item_refs.may_read(ctx, "messaging", KEYS[ASK_ONLY]) is False and item_refs.may_read(ctx, "mcp", None) is False
    assert item_refs.may_read(ctx, "terminal", None) is True and item_refs.may_read(ctx, "page", None) is True


def test_a_file_that_gives_the_group_to_a_sender_is_a_widening_that_needs_the_hash(two):
    accept(two["path"], policies={"asker": ["read", "talk", "ask"]}, messaging={"senders": {"telegram": [{"id": ASK_ONLY, "policy": "asker"}]}})
    write_config(two["path"], policies={"asker": ["read", "talk", "ask", "ask-mail"]})
    shown = ops.config(two["path"])
    assert any("ask-mail" in str(line) for line in shown["widening"])
    with pytest.raises(ops.OpsError, match="widen"):
        ops.accept_config(two["path"], shown["sha256"])
