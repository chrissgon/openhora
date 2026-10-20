"""A phone never reads a command or a path (package LIVE-2, limit L62; runtime/messaging_guard.py, runtime/phrases.py family PHONE_, runtime/ops_natural.py).

Three layers are tested here. (1) The finder and the net: what counts as a command of this platform's shell or a path of this machine, what does not (a slash
command of a messaging app, a URL, a relative path, a bare verb, a date), what the net cuts and what it adds. (2) The sentences: every key of the phrase table, in both
languages, with the page link set or not, carries no command and no path in its messaging rendering. (3) The answers: every operation a plain line can name that is not a
read, asked on a messaging channel by a sender who may and by one who may not, is answered with no command, no path and no word `terminal`. Over the real operations layer
(the chat tree of test_ops_natural, a stand-in router) for (3); offline, no model; every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_phone_guard.py
"""
from __future__ import annotations

import string

import pytest

import standin_tree as st
from test_ops_natural import KEY, OWNER, OPERATION, READER, router_says, with_senders, world  # noqa: F401  (the real-operations world fixture)

guard = st.load("messaging_guard")
phrases = st.load("phrases")
natural = st.load("natural")
ops = st.load("ops")
ops_core = st.load("ops_core")
ops_natural = st.load("ops_natural")
operations = st.load("operations")

COMMANDS = [
    "uv run --with keyring==25.7.0 python3 ~/projects/openhora-integration/runtime/cli.py event-create --project ~/projects/shop --account google --title Dentist --start 2026-10-22T15:00",
    "python3 runtime/cli.py approve --project <project> --id 3 --sha256 abc",
    "python3 /Users/ana/co/runtime/cli.py status --project /Users/ana/shop",
    "keyring set openhora messenger-telegram",
    "run it with --project /srv/shop and --sha256 abc",
    "python3 providers/documents/gdrive_auth.py authorize",
]
PATHS = ["see /Users/ana/shop/docs/plan.md for it", "in ~/projects/shop", "on C:\\Users\\ana\\shop today", "/var/folders/ab/cd/T/x.sqlite is busy", "the file /home/ana/a/b.txt"]
NOT_FOUND = [
    "/approve 12", "/pending", "Send /add 3", "Reply with /new <text>", "https://page.example/open/now", "http://a.example/x/y/z", "docs/workbench/plan.md",
    "accept-config", "run-next", "Wed 21/10/2026 13:00-14:00", "10/20/2026", "America/Sao_Paulo", "and/or", "1/2", "uv", "sha256 of the card",
]


@pytest.mark.parametrize("text", COMMANDS)
def test_a_command_of_this_platforms_shell_is_found_and_cut(text):
    assert [kind for kind, _span in guard.find(text)] == ["command"]
    cleaned, kinds, _altered = guard.clean(text)
    assert kinds == ["command"] and guard.find(cleaned) == [] and "cli.py" not in cleaned and "--project" not in cleaned and "uv run" not in cleaned


@pytest.mark.parametrize("text", PATHS)
def test_a_path_of_this_machine_is_found_and_cut_and_the_rest_of_the_line_stays(text):
    assert [kind for kind, _span in guard.find(text)] == ["path"]
    cleaned, kinds, altered = guard.clean(text)
    assert kinds == ["path"] and altered is True and guard.find(cleaned) == [] and cleaned.strip()


@pytest.mark.parametrize("text", NOT_FOUND)
def test_what_a_phone_may_read_is_not_found(text):
    assert guard.find(text) == [] and guard.clean(text) == (text, [], False)


def test_a_line_that_was_only_a_label_for_a_command_is_dropped_and_is_not_an_alteration_of_the_text():
    text = "Approve exactly this: python3 runtime/cli.py approve --project <project> --id 7 --sha256 abc\nThe next line stays."
    cleaned, kinds, altered = guard.clean(text)
    assert cleaned == "The next line stays." and kinds == ["command"] and altered is False
    wrapped, _k, _a = guard.clean("Do it:\n`python3 runtime/cli.py status --project x`\nDone.")
    assert wrapped == "Do it:\nDone."


def test_the_net_cuts_the_text_the_footer_and_the_document_adds_one_sentence_and_records_an_event_without_the_text():
    guard.EVENTS.clear()
    seen = []
    message = {"text": "co · request #7\n\nbody ~/shop/docs/x.md\n\nApprove it:\n`uv run python3 runtime/cli.py approve --project x`", "actions": [], "link": None,
               "footer": ["Approve it:", "`uv run python3 runtime/cli.py approve --project x`"], "document": {"name": "a.txt", "text": "whole /Users/ana/b/c text"}}
    out = guard.guard_message(message, {"language": "pt-BR"}, seen.append)
    assert guard.find(out["text"]) == [] and out["text"].endswith(phrases.phone("PHONE_STRIPPED", {"language": "pt-BR"})) and "footer" not in out
    assert guard.find(out["document"]["text"]) == [] and out["document"]["text"].startswith("whole")
    assert list(guard.EVENTS) == [{"kinds": ["command", "path"]}] and seen == [["command", "path"]], "an event, the kinds only"
    assert message["text"].count("uv run") == 1, "the caller's message is not changed"
    clean = {"text": "nothing to cut here /pending", "actions": [], "link": None, "document": None}
    assert guard.guard_message(clean, None) == clean and list(guard.EVENTS) == [{"kinds": ["command", "path"]}]


def test_the_sentence_the_net_adds_names_the_page_with_its_link_when_there_is_one_and_never_a_terminal():
    for cfg, tail in (({"language": "pt-BR", "page_url": "https://page.example/open"}, "O resto se faz na página da plataforma: https://page.example/open"),
                      ({"language": "pt-BR"}, "O resto se faz na página da plataforma."), ({"page_url": "https://page.example/open"}, "The rest is done on the platform's page: https://page.example/open"),
                      (None, "The rest is done on the platform's page.")):
        assert guard.sentence(cfg) == tail
    assert phrases.where_page({"messaging": {"page_url": "https://page.example/x"}}) == "on the platform's page: https://page.example/x"


# --- (2) every sentence of the table -----------------------------------------------------------------------------------------------------------------


def rendering(key: str, tag: str, url):
    """The key in the language with every field `x` (a sentence that ends with {where} gets the place) and the page link set or not."""
    cfg = {"language": tag, **({"page_url": url} if url else {})}
    fields = {name: "x" for _lit, name, _spec, _conv in string.Formatter().parse(phrases.en(key)) if name}
    fields.pop("where", None)
    if "{where}" in phrases.en(key):
        return phrases.phone(key, cfg, **fields)
    return phrases.text(key, cfg, **fields)


# Keys whose English text is a template for a place that is not a phone, or that spells a command on purpose: the card lines of a stored effect (their approve line is cut
# from a phone card by messaging_cards), and the lines the terminal and the page print.
TERMINAL_ONLY = {"NOT_NAMED_NEXT", "NW_APPROVE_WITH", "CARD_MAIL_APPROVE", "CARD_FILE_APPROVE"}


@pytest.mark.parametrize("tag", ["en", "pt-BR"])
@pytest.mark.parametrize("url", [None, "https://page.example/open"])
def test_no_sentence_of_the_phrase_table_carries_a_command_or_a_path_on_a_phone(tag, url):
    found = {}
    for key in phrases.TABLE["en"]:
        if key in TERMINAL_ONLY:
            continue
        text = rendering(key, tag, url)
        if guard.find(text):
            found[key] = guard.find(text)
    assert found == {}


def test_the_sentences_that_end_with_the_place_say_it_in_both_languages_and_a_link_is_not_followed_by_a_full_stop():
    keys = [k for k, text in phrases.TABLE["en"].items() if text.endswith("{where}")]
    assert len(keys) >= 12 and all(phrases.TABLE["pt-BR"][k].endswith("{where}") for k in keys), "both columns end with the place"
    for key in keys:
        assert rendering(key, "en", None).endswith("on the platform's page.") and rendering(key, "pt-BR", None).endswith("na página da plataforma.")
        assert rendering(key, "en", "https://page.example/open").endswith("on the platform's page: https://page.example/open")
        assert rendering(key, "pt-BR", "https://page.example/open").endswith("na página da plataforma: https://page.example/open")


# --- (3) every operation a line can name that is not a read -------------------------------------------------------------------------------------------

NOT_READS = sorted(name for name, cls in natural.CLASSES.items() if cls in ("G", "E", "N", "W", "D"))


def asked(world, name, who, routed):
    ctx = ops_core.context(world["path"])
    return ops_natural.run(world["path"], ctx, name, {}, "a line of the person", "messaging", KEY[who], {}, routed=routed)


@pytest.mark.parametrize("who", ["owner", "reader"])
def test_every_operation_that_is_not_a_read_answers_a_phone_with_no_command_no_path_and_no_terminal(world, who):
    with_senders(world)
    found = {}
    for name in NOT_READS:
        for routed in (False, True):
            reply = asked(world, name, who, routed)
            if guard.find(reply) or "terminal" in reply.lower() or "python3" in reply or "uv run" in reply:
                found[(name, routed)] = reply
    assert found == {}


def test_what_a_phone_is_told_is_the_family_sentence_with_the_page_link_when_the_project_has_one(world):
    with_senders(world)
    ctx = ops_core.context(world["path"])
    assert ops_natural.phone_sentence(ctx, "accept-config") == "Settings, accounts and permissions are changed on the platform's page."
    assert ops_natural.phone_sentence(ctx, "source-add") == "Sources and files are added to the project on the platform's page."
    assert ops_natural.phone_sentence(ctx, "instructions-add") == "The project's standing instructions are changed on the platform's page."
    assert ops_natural.phone_sentence(ctx, "routine-create") == "A routine is created, changed and approved on the platform's page."
    assert ops_natural.phone_sentence(ctx, "dispatch") == "That is not done from a message. Do it on the platform's page."
    assert ops_natural.phone_sentence(ctx, "event-create") == "A change to your accounts is made on the platform's page."
    assert ops_natural.phone_sentence(ctx, "event-create", retry=True) == phrases.phone("PHONE_EVENT_AGAIN", ctx["cfg"])
    linked = dict(ctx, cfg=dict(ctx["cfg"], page_url="https://page.example/open", language="pt-BR"))
    assert ops_natural.phone_sentence(linked, "set-model") == "Configurações, contas e permissões se mudam na página da plataforma: https://page.example/open"  # validate: allow english-only -- the expected Portuguese sentence of the phrase table's pt-BR column


def test_the_terminal_the_page_and_the_conversation_keep_the_exact_command(world):
    ctx = ops_core.context(world["path"])
    for channel in ("page", "mcp"):
        said = ops_natural._gated(ctx, "set-model", {}, channel)
        assert "set-model" in said and ("in the terminal or on the page" in said)
    assert "python3" in ops_natural._gated(ctx, "accept-config", {}, "chat")
    assert ops_natural._command(ctx, "set-model", {}, "terminal", "messaging") is None, "a phone is never given the terminal's command"
    assert ops_natural._command(ctx, "cancel", {"request_id": 4}, "messaging", "messaging") == "/cancel 4", "a slash line a messaging app has is not a terminal command"


def test_a_routed_reminder_to_bring_back_and_a_go_ahead_by_words_name_the_place_not_a_command(world):
    with_senders(world)
    router_says(world, OPERATION.format(name="reminder-restore") + "Argument id: 3\n")
    reply = ops.say(world["path"], "what about number 3 then", channel="messaging", sender=KEY["owner"])["reply"]
    assert reply == phrases.phone("PHONE_RESTORE", ops_core.context(world["path"])["cfg"]) and guard.find(reply) == []


def test_limit_62_a_phone_is_never_given_a_command_or_a_path(world):
    """The limit in one place: the net cuts what the sentences should never carry, the sentences of the table carry none, and the answer to every operation a phone cannot do is one
    plain sentence with the page (the three layers are tested above, one by one)."""
    sent = guard.guard_message({"text": "do " + COMMANDS[0] + " in ~/shop", "actions": [], "link": None, "document": None}, None)
    assert guard.find(sent["text"]) == [] and "terminal" not in sent["text"].lower()
    with_senders(world)
    ctx = ops_core.context(world["path"])
    for name in NOT_READS:
        reply = ops_natural.run(world["path"], ctx, name, {}, "a line", "messaging", KEY["owner"], {}, routed=True)
        assert guard.find(reply) == [], (name, reply)
