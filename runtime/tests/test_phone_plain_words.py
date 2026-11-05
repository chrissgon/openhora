"""No English and no internal words on a Portuguese phone (slice S14, limit L62): the lines `/pending` writes, the sentences of `/reject` and `/discard`, the net under the bridge's send
point for the operations layer's own errors, and a sweep of the phrase keys the messaging code uses.

THE ORACLE reads the phone's texts with phrase keys and their fields (runtime/tests/phrase_kit.py: the wording is pinned once by the phrase snapshot), this file's own literals for the words it must not
hold and the English function words of the layer's own errors. It never calls the code under test to decide what is right (the key sweep reads the tables as data and the sources as text). The vacuity
cases plant the live lines of the maintainer's screen and a Portuguese column that repeats the English, and show the same oracle flags them. Over the stand-in operations object and the
stand-in messenger of test_messaging.py; invented names.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_phone_plain_words.py
"""
from __future__ import annotations

import os
import re

import pytest

import phone_said as ps
import phrase_kit as pk
import standin_tree as st
from expected_kit import extend
from test_messaging import SENDER, decision, wait_for, world  # noqa: F401  (the bridge world of test_messaging.py)

ops = st.load("ops")
phone_errors = st.load("phone_errors")
messaging_pending = st.load("messaging_pending")
phrases = st.load("phrases")

INTERNAL = re.compile(r"\b(route|router|rota|rotas|roteador)\b|channels\.", re.I)
ENGLISH_WORDS = re.compile(r"\b(the|is|are|not|was|could|takes|acceptance|pending decision|you|your|with)\b")      # the function words of the layer's English (none is a Portuguese word)
REPO = st.REPO
SKILL_IDS = sorted(set(os.listdir(REPO / "skills")) | {"flow-" + n[:-5] for n in os.listdir(REPO / "flows") if n.endswith(".json")})


def problems(text: str) -> list:
    """What is wrong with a Portuguese phone's text: a word of the platform's internals, an identifier of a skill or a flow, or a word of the layer's English."""
    found = [f"internal {m.group(0)!r}" for m in INTERNAL.finditer(text)]
    found += [f"id {name!r}" for name in SKILL_IDS if re.search(r"(?<![\w-])" + re.escape(name) + r"(?![\w-])", text)]
    found += [f"english {m.group(0)!r}" for m in ENGLISH_WORDS.finditer(text)]
    return found


def question(number, body, title="The router asks", ending="question", **more):
    return decision("question", number, title=title, body=body, payload={"ending": ending}, **more)


def pt(world):
    world.config["language"] = "pt-BR"


ROUTER_BODY = ("Route: none (capability, pending)\nWhy: w\nNext: Q1: Which market first? Recommended: the home market, because it is closest.\n"
               "Q2: Which price? Recommended: the low one, because it is a start.\nInstructions found in external content: none\n")
LONG = "Which of the three launch dates in the plan would you like me to keep, given that the shop opens late and the printer is not ready?"
PT_CFG = {"language": "pt-BR"}


def listing(text):
    """A `/pending` reply as (project, the first row, the other lines): the first line is `<project>: <row>`."""
    first, *rest = text.split("\n")
    project, _, row = first.partition(": ")
    return project, row, rest


def is_row(row, number, kind_key, title, cfg=None):
    """True when `row` is `#<number> <kind word>: <title>`, the kind word being the key's sentence in the language of `cfg`."""
    head, _, said_title = row.partition(": ")
    mark, _, kind = head.partition(" ")
    return mark == f"#{number}" and pk.said(kind, kind_key, cfg) and said_title == title


def lines_said(text, expected, cfg=None):
    """True when the lines of `text` are, in order, the sentences of `expected` ((key, fields) pairs)."""
    lines = text.split("\n")
    return len(lines) == len(expected) and all(pk.said(line, key, cfg, **fields) for line, (key, fields) in zip(lines, expected))


# --- /pending -----------------------------------------------------------------------------------------------------------------------------------


def test_pending_says_what_is_asked_and_what_was_not_understood_and_how_to_dismiss(world):
    pt(world)
    world.items[1] = decision("plan", 1, title="Plan one")
    world.items[14] = question(14, ROUTER_BODY)
    world.items[25] = question(25, "The planning agent did not name a flow or a skill for request 3", title="The route was not recognised", ending="unclassified")
    world.items[28] = question(28, LONG + "\nA second line.", title="demo-asks: question")
    world.say("/pending")
    assert len(world.texts()[0].split("\n")[3].split(": ", 1)[1]) <= 80, "the question is cut at about 80 characters"
    project, row, rest = listing(world.texts()[0])
    assert project == "northwind-shop" and is_row(row, 1, "KIND_PLAN", "Plan one", PT_CFG)
    assert lines_said("\n".join(rest), [("PEND_QUESTION", {"id": 14, "text": "Which market first?"}), ("PEND_NOT_UNDERSTOOD", {"id": 25}),
                                        ("PEND_QUESTION", {"id": 28, "text": "Which of the three launch dates in the plan would you like me to keep, given…"}), ("PEND_DISMISS_TYPED", {})], PT_CFG)


def test_the_english_list_says_the_same_in_english_and_a_list_with_no_question_has_no_dismiss_line(world):
    world.items[1] = decision("plan", 1, title="Plan one")
    world.items[14] = question(14, ROUTER_BODY)
    world.say("/pending")
    project, row, rest = listing(world.texts()[0])
    assert project == "northwind-shop" and is_row(row, 1, "KIND_PLAN", "Plan one")
    assert lines_said("\n".join(rest), [("PEND_QUESTION", {"id": 14, "text": "Which market first?"}), ("PEND_DISMISS_TYPED", {})])
    del world.items[14]
    world.say("/pending")
    project, row, rest = listing(world.texts()[-1])
    assert project == "northwind-shop" and is_row(row, 1, "KIND_PLAN", "Plan one") and rest == []


def test_a_project_whose_notices_carry_none_of_its_text_lists_a_question_as_it_always_did(world):
    pt(world)
    world.config["messaging"]["notices"] = "count"
    world.items[14] = question(14, ROUTER_BODY)
    world.say("/pending")
    project, row, rest = listing(world.texts()[0])
    head, _, said_title = row.partition(": ")
    assert project == "northwind-shop" and head.startswith("#14 ") and pk.said(head[4:], "KIND_QUESTION", PT_CFG) and pk.said(said_title, "TITLE_ROUTER_ASKS", PT_CFG)
    assert lines_said("\n".join(rest), [("PEND_DISMISS_TYPED", {})], PT_CFG)


def test_the_dismiss_line_of_a_platform_whose_acts_are_replies_says_to_reply_to_the_message():
    listed = [{"kind": "question", "id": 1}]
    assert ps.alone(messaging_pending.footer(listed, {"actions_need_reply": True}, {"language": "en"}), "PEND_DISMISS_REPLY", {"language": "en"})
    assert ps.alone(messaging_pending.footer(listed, {"actions_need_reply": False}, {"language": "en"}), "PEND_DISMISS_TYPED", {"language": "en"})
    assert messaging_pending.footer([{"kind": "plan", "id": 1}], {}, {"language": "en"}) == ""


# --- /reject and /discard ----------------------------------------------------------------------------------------------------------------------


def rejected(world):
    return [c[2]["pending_id"] for c in world.calls("reject")]


@pytest.mark.parametrize("language", ["pt-BR", None])
def test_reject_on_a_question_calls_reject_once_and_says_it_was_dismissed(world, language):
    if language:
        world.config["language"] = language
    world.items[14] = question(14, ROUTER_BODY)
    world.bridge.tick()
    world.say("/reject 14")
    assert rejected(world) == [14] and ps.alone(world.texts()[-1], "QUESTION_DISMISSED", {"language": language}, id=14)


def test_reject_on_an_effect_is_as_before(world):
    pt(world)
    world.items[7] = decision("effect", 7, title="Write to the plan page", body="Replace the page with:\n\nOpen at nine.", payload_sha256="e" * 64, effect_word="write", effect_on_cards=True)
    world.bridge.tick()
    world.say("/reject 7")
    assert rejected(world) == [7] and ps.alone(world.texts()[-1], "REJECTED", PT_CFG, id=7)


def test_discard_on_a_number_that_is_a_question_and_no_file_rejects_it_and_on_nothing_points_to_the_card(world):
    pt(world)
    world.fake.answers["attachments"] = {"held": [], "recent": []}
    world.items[28] = question(28, ROUTER_BODY)
    world.bridge.tick()
    world.say("/discard 28")
    assert rejected(world) == [28] and ps.alone(world.texts()[-1], "QUESTION_DISMISSED", PT_CFG, id=28)
    world.fake.answers["pending"] = lambda project, pending_id=None, **k: (_ for _ in ()).throw(ops.OpsError(f"no pending decision {pending_id}", 1))
    world.say("/discard 99")
    assert rejected(world) == [28] and ps.alone(world.texts()[-1], "NO_CARD", PT_CFG)


def test_reject_on_a_kind_it_does_not_take_is_said_in_portuguese(world):
    pt(world)
    world.items[3] = decision("review", 3, title="Draft")
    world.bridge.tick()
    world.fake.answers["reject"] = ops.OpsError("pending decision 3 is a review: reject takes a plan, an acceptance, an effect or a question", 2)
    world.say("/reject 3")
    assert ps.alone(world.texts()[-1], "NOT_REJECTABLE", PT_CFG, number=3, kind=phrases.text("KIND_REVIEW", PT_CFG))


# --- the net under the send point ----------------------------------------------------------------------------------------------------------------

# The operations layer's own errors that reach a messaging app: the text, and the sentence a phone is told as a phrase key and its fields. A field that is a tuple is a word of
# the table said in the language of the phone: ("kind", "KIND_QUESTION") is the key's sentence, ("status", "approved") a status word.
ERRORS = [
    ("error: pending decision 14 is a question: reject takes a plan, an acceptance or an effect", "NOT_REJECTABLE", {"number": 14, "kind": ("kind", "KIND_QUESTION")}),
    ("error: no pending decision 77", "NO_SUCH_DECISION", {"number": 77}),
    ("error: pending decision 5 is approved, not open", "NOT_OPEN_DONE", {"number": 5, "status": ("status", "approved")}),
    ("error: pending decision 6 is pending-execution, not open", "NOT_OPEN", {"number": 6, "status": ("status", "pending-execution")}),
    ("error: use the card's button, or /approve <id> as the whole line", "PHONE_USE_CARD", {}),
    ("error: pending decision 4 is a plan: it is approved or rejected, not answered or released", "NOT_ANSWERABLE", {"number": 4, "kind": ("kind", "KIND_PLAN")}),
    ("error: something the layer did not expect", "PHONE_FAILED", {}),
]


def told(text, key, fields, cfg):
    """True when `text` is the sentence of `key` with `fields` in the language of `cfg` (a place at the end is the page)."""
    fields = {name: (phrases.status(value[1], cfg) if value[0] == "status" else phrases.text(value[1], cfg)) if isinstance(value, tuple) else value for name, value in fields.items()}
    return ps.placed(text, key, cfg, **fields) if key == "PHONE_FAILED" else ps.alone(text, key, cfg, **fields)


@pytest.mark.parametrize("raw,key,fields", ERRORS)
def test_an_error_of_the_operations_layer_is_one_sentence_in_the_language_on_a_portuguese_phone(world, raw, key, fields):
    pt(world)
    world.bridge.reply(SENDER, raw, world.projects[0])
    assert told(world.texts()[-1], key, fields, PT_CFG), world.texts()[-1]
    assert world.texts()[-1] != raw and problems(world.texts()[-1]) == [], world.texts()[-1]


ENGLISH_SETTLED = {"error: pending decision 5 is approved, not open": ("NOT_OPEN_DONE", {"number": 5, "status": "approved"})}


@pytest.mark.parametrize("raw,key,fields", ERRORS)
def test_an_english_phone_is_told_the_precise_text_as_before_except_for_a_decision_that_is_already_settled(world, raw, key, fields):
    world.bridge.reply(SENDER, raw, world.projects[0])
    if raw in ENGLISH_SETTLED:
        settled_key, settled_fields = ENGLISH_SETTLED[raw]
        assert ps.alone(world.texts()[-1], settled_key, {}, **settled_fields), world.texts()[-1]
    else:
        assert world.texts()[-1] == raw      # literal: the precise text of the operations layer, which an English phone is told as it is


@pytest.mark.parametrize("language", ["pt-BR", None])
def test_reject_on_a_decision_that_is_already_resolved_is_told_plainly(world, language):
    if language:
        world.config["language"] = language
    world.items[17] = decision("plan", 17, title="Plan seventeen")
    world.bridge.tick()
    world.fake.answers["reject"] = ops.OpsError("pending decision 17 is resolved, not open", 1)
    world.say("/reject 17")
    cfg = {"language": language} if language else {}
    assert ps.alone(world.texts()[-1], "NOT_OPEN_DONE", cfg, number=17, status=phrases.status("resolved", cfg))


def test_a_text_that_is_not_an_error_is_never_touched(world):
    pt(world)
    for text in ("Lembre de regar as plantas.", "Water the plants.", "northwind-shop: nada pendente para você."):  # validate: allow english-only -- the texts under test
        world.bridge.reply(SENDER, text, world.projects[0])
        assert world.texts()[-1] == text


def test_a_failure_the_bridge_reports_is_said_in_the_language(world):
    pt(world)
    world.fake.answers["reject"] = ops.OpsError("an effect of request 3 is executing; nothing was stopped; cancel again when it ends", 1)
    world.items[1] = decision("plan", 1, title="Plan one")
    world.bridge.tick()
    world.say("/reject 1")
    assert told(world.texts()[-1], ERRORS[-1][1], ERRORS[-1][2], PT_CFG)


# --- the sweep of the phrase keys ------------------------------------------------------------------------------------------------------------------

# Keys whose Portuguese is the English word (a name, a frame) and keys that only a page or a terminal is told (the phone has its own key since S14: PHONE_ROUTER_FAILED,
# PHONE_NOT_PLANNED, PHONE_NOT_UNDERSTOOD and the plain title/body of a card), each with the reason it is allowed.
SAME_AS_ENGLISH = {"HEADER": "a frame of three fields", "OUT_ACCT_GOOGLE": "a product name", "OUT_ACCT_MICROSOFT": "a product name"}
PAGE_ONLY = extend("phone_plain_words.PAGE_ONLY", {"NOT_NAMED_NEXT": "the page's and the terminal's tail", "PLAN_NOT_PLANNED": "the page's plan reply (PHONE_NOT_PLANNED on a phone)",
             "ROUTER_FAILED": "the page's failure line (PHONE_ROUTER_FAILED on a phone)", "TITLE_ROUTE_UNRECOGNISED": "only recognised, never said (messaging_pending)",
             "TITLE_ROUTER_ASKS": "only recognised, said as PEND_CARD_TITLE (ops_say._title)"})
MESSAGING_FILES = extend("phone_plain_words.MESSAGING_FILES", ["messaging*.py", "phone_*.py", "ops_natural*.py", "natural*.py", "ops_say.py", "ops_interpret.py", "ops_reminders.py", "ops_attachments.py", "greeting.py", "card_words.py"])


def keys_used() -> set:
    """The phrase keys that the code messaging reaches names, found by reading the sources as text."""
    found = set()
    for pattern in MESSAGING_FILES:
        for path in sorted(st.RUNTIME.glob(pattern)):
            found |= set(re.findall(r"""["']([A-Z][A-Z0-9_]{2,})["']""", path.read_text(encoding="utf-8")))
    return {k for k in found if k in phrases.TABLE["en"]}


def column_problems(keys, table_en, table_pt) -> list:
    out = []
    for key in sorted(keys):
        said = table_pt.get(key)
        if said is None:
            out.append((key, "missing"))
        elif said == table_en[key] and key not in SAME_AS_ENGLISH and key not in phrases.SAME_AS_ENGLISH:      # a phrase part declares its own (HOT-2)
            out.append((key, "same as the English"))
        elif key not in PAGE_ONLY and problems(said.replace("{", "").replace("}", "")) and not re.fullmatch(r"[^a-z]*", said):
            out.append((key, "internal or English words: " + str(problems(said))))
    return out


def test_every_phrase_key_the_messaging_code_uses_has_a_portuguese_sentence_that_is_not_the_english_and_holds_no_internal_word():
    keys = keys_used()
    assert len(keys) > 250, "the scan reads the sources: a rename that hides the keys would make the sweep vacuous"
    assert column_problems(keys, phrases.TABLE["en"], phrases.TABLE["pt-BR"]) == []


def test_the_allowed_exceptions_are_still_keys_the_table_has():
    assert set(SAME_AS_ENGLISH) | set(PAGE_ONLY) <= set(phrases.TABLE["en"]) and set(PAGE_ONLY) <= set(phrases.TABLE["pt-BR"])


def test_vacuity_a_column_that_repeats_the_english_or_says_the_router_is_noticed_and_the_live_lines_fail_the_oracle():
    en = {"A": "Nothing waits for you.", "B": "The router asks", "C": "Fine"}
    assert column_problems({"A", "B", "C"}, en, {"A": "Nothing waits for you.", "B": "O roteador pergunta", "C": "Certo"}) == [
        ("A", "same as the English"), ("B", "internal or English words: [\"internal 'roteador'\"]")]
    assert column_problems({"A"}, en, {}) == [("A", "missing")]
    for live in ("northwind-shop: #14 pergunta: A rota não foi reconhecida", "pending decision 14 is a question: reject takes a plan, an acceptance or an effect",  # validate: allow english-only -- the live lines of the maintainer's screen
                 "O roteador pergunta"):
        assert problems(live), live
    assert problems("Pergunta #14 dispensada.") == [] and problems("Para dispensar, responda: /reject <número>.") == []  # validate: allow english-only -- the Portuguese sentences under test


# --- /help ---------------------------------------------------------------------------------------------------------------------------------------


def padded(text: str) -> list:
    """The lines of a help text that are laid out in columns: a run of two spaces between words, which a proportional font does not align."""
    return [line for line in text.split("\n") if re.search(r"\S {2,}\S", line)]


def test_the_phones_help_is_one_command_per_line_with_no_padding_and_the_placeholders_in_the_language(world):
    pt(world)
    world.say("/help")
    pk.assert_said(world.texts()[-1], "HELP", PT_CFG)
    assert padded(world.texts()[-1]) == []
    assert "agente de planejamento" not in world.texts()[-1], "the old last line (every other message goes to the planning agent) is gone"
    for english in ("<text>", "<question>", "[note]", "[name]", "<time>"):
        assert english not in world.texts()[-1], english


def test_the_english_help_is_laid_out_the_same_way_and_ends_with_the_same_two_sentences(world):
    world.say("/help")
    pk.assert_said(world.texts()[-1], "HELP", {})
    assert padded(world.texts()[-1]) == []
    assert "<text>" in world.texts()[-1] and "planning agent" not in world.texts()[-1]


def test_the_page_and_the_terminal_keep_their_padded_list():
    operations = st.load("operations")
    assert padded(operations.chat_help()) != [], "the list of the page and the terminal is unchanged"


def test_vacuity_the_old_padded_help_is_noticed():
    old = "Comandos:\n/pending            o que espera por você\n/approve <id>       aprova o que o último card de <id> mostrou\n"  # validate: allow english-only -- the old help of the maintainer's screen
    assert len(padded(old)) == 2 and padded(phrases.text("HELP", PT_CFG)) == []


# --- the sweep of every refusal the calendar, mail, files and sources operations can return (S14b) ----------------------------------------------------------

import ast  # noqa: E402
import string  # noqa: E402

messaging_failure = st.load("messaging_failure")

SWEEP_FILES = extend("phone_plain_words.SWEEP_FILES", ["ops_calendar", "calendar_document", "step_calendar_event", "effect_calendar", "ops_mail_send", "ops_mailbox", "mailbox_document", "step_mailbox", "effect_mailbox",
               "step_send_email", "effect_send", "mail_compose", "ops_files", "files_document", "step_files", "effect_files", "ops_sources", "sources", "sources_mail",
               "sources_onedrive", "source_resolve", "ops_natural_calendar", "ops_natural_files", "ops_natural_mail", "account_start", "event_lookup", "ops_file_read"])
PT = {"language": "pt-BR"}


def _text(node):
    """The text of a string node; an f-string with each field as `x`; None for anything else."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(part.value if isinstance(part, ast.Constant) else "x" for part in node.values)
    return None


def refusals() -> list:
    """[(shape, text, file)] read from the sources as text: the message of every `raise OpsError(...)`, `_usage(...)`, `EffectError(...)`, the `next` (4th) argument of every
    `StepFailure(...)`, the text of every `return <int>, "..."` of an effect (the writer's exit reasons) and the value of a dict key `error`, `refused`, `reason` or `why`."""
    found = []
    for name in SWEEP_FILES:
        path = st.RUNTIME / f"{name}.py"
        if not path.is_file():
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call):
                callee = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
                if callee in ("OpsError", "_usage", "EffectError") and node.args and _text(node.args[0]):
                    found.append(("ops", _text(node.args[0]), name))
                elif callee == "StepFailure" and len(node.args) >= 4 and _text(node.args[3]):
                    found.append(("step", _text(node.args[3]), name))
            elif isinstance(node, ast.Return) and isinstance(node.value, ast.Tuple) and len(node.value.elts) == 2:
                code, text = node.value.elts
                if isinstance(code, ast.Constant) and isinstance(code.value, int) and _text(text):
                    found.append(("effect", _text(text), name))
            elif isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values):
                    if isinstance(key, ast.Constant) and key.value in ("error", "refused", "reason", "why") and _text(value):
                        found.append(("field", _text(value), name))
    return [(shape, text, name) for shape, text, name in found if len(re.findall(r"[A-Za-z]{3,}", text)) >= 3]


def _table_matcher():
    parts = []
    for sentence in phrases.TABLE["pt-BR"].values():
        made = "".join(re.escape(lit) + (".+?" if field is not None else "") for lit, field, _spec, _conv in string.Formatter().parse(sentence))
        if made:
            parts.append(made)
    return re.compile("|".join(parts), re.S)


def on_a_portuguese_phone(shape: str, text: str) -> str:
    """What the real net makes of one refusal on a Portuguese phone, by the shape it comes back in."""
    if shape == "step":
        return messaging_failure.from_step("calendar-event", "microsoft", "not_available", "operation", None, PT, said=text)
    if shape == "effect":
        return messaging_failure.from_error(ops.OpsError(text, 1), PT, word="calendar", account="microsoft")
    if shape == "field":
        return phone_errors.safe(text, PT)
    return phone_errors.said("error: " + text, PT)


def leaks(items, matcher=None) -> list:
    """The refusals that reach a Portuguese phone as English: not a sentence of the phrase table, and not the generic one."""
    matcher = matcher or _table_matcher()
    return [(shape, text, name) for shape, text, name in items if not matcher.fullmatch(on_a_portuguese_phone(shape, text))]


def test_no_refusal_of_the_calendar_mail_files_and_sources_operations_reaches_a_portuguese_phone_as_raw_english():
    items = refusals()
    assert len(items) > 150, "the scan reads the sources: a rename that hides the raises would make the sweep vacuous"
    assert {shape for shape, _, _ in items} >= {"ops", "step", "effect"} and {"step_calendar_event", "effect_calendar", "calendar_document"} <= {n for _, _, n in items}
    assert leaks(items) == []


def test_the_outlook_removal_refusal_is_raised_nowhere_since_s21():
    assert [i for i in refusals() if "Outlook calendar is not available" in i[1]] == [], "removing an Outlook event is on (S21): no source raises the refusal any more"


def test_vacuity_a_net_that_returns_the_text_is_noticed_by_the_sweep(monkeypatch):
    items = [("ops", "the title is not a string", "x")]
    assert leaks(items) == []
    monkeypatch.setattr(phone_errors, "safe", lambda text, cfg=None: text)
    monkeypatch.setattr(messaging_failure, "phone_errors", phone_errors)
    monkeypatch.setattr(phone_errors, "said", lambda text, cfg=None, failure=False: text)
    assert leaks([("field", "the title is not a string", "x")]) != [], "a net that passes the English through is a leak"


def test_a_refusal_a_result_carries_is_told_in_the_language_on_a_phone_and_kept_on_the_page():
    ops_natural = st.load("ops_natural")
    out = {"refused": "the file is too large for this account", "status": "held"}
    phone = ops_natural._render("task", out, PT, "messaging")
    assert ps.placed(phone.splitlines()[0], "PHONE_FAILED", PT) and phone.splitlines()[1] == "status: held"
    assert ops_natural._render("task", out, PT, "page").splitlines()[0] == "refused: the file is too large for this account"
    assert ops_natural._render("task", out, {}, "messaging").splitlines()[0] == "refused: the file is too large for this account", "an English phone keeps the precise text"




@pytest.mark.parametrize("language", ["pt-BR", None])
def test_the_bridge_answers_a_delete_a_file_line_at_once_before_any_queue_or_model(world, language):
    if language:
        world.config["language"] = language
    for line in ("Remova o arquivo openhora-mark.png do drive", "Remova o arquivo openhora-mark do drive em /openhora"):  # validate: allow english-only -- the live lines under test
        world.say(line)
        assert ps.alone(world.texts()[-1], "PHONE_NO_FILE_DELETE", {"language": language}), line
    assert world.calls("say") == [], "no operation of the conversation was called"
    world.say("Remova o evento de amanhã")  # validate: allow english-only -- the line under test
    assert wait_for(lambda: world.calls("say")), "an event line goes on to the conversation as before"
