"""The gate's fourth section (S41-7, limits L55, L60 and L61): provenance by origin per argument, checked before any card opens from a line.

A card that a person's line opens is opened by the operation's own function with arguments that a resolver made. Until S41-7 each came from code BY CONSTRUCTION (the family resolvers, the spans the
interpreter checked) and the only check that read them was the value oracle `natural_writes.problems`, which the fuzzers ran and nothing else did. Now every resolver (and every seed) says where each
argument came from, in `{"args", "origins"}`, and `turn_gate.provenance(op, args, origins)` checks that against a closed table before `_call_operation` (and before the trash card, and before an event
card is revised). FAIL CLOSED (OPEN-41-8, recommended): an operation that is not in the table, an argument the operation does not take, an argument with no origin, an origin outside the closed
vocabulary and an origin its key may not have each open no card; the person is asked again in a plain sentence on a phone (L62) and the stored row is the neutral word.

Held here:
  * the table (a row for every key every operation takes; the closed vocabulary; L60: no address from `grounded`, `listed`, `picked`, `held`, `time-engine` or `composed`, and a reply has no
    recipient argument at all; `composed` only on the text of an e-mail), and the control of every pair of key and origin, so a row cannot be widened without this file saying which;
  * integration: for each of the 13 operations a planted resolver result with an argument missing its origin or with an origin its key may not have opens no card (no `_call_operation`), asks again,
    drops the draft, stores the neutral word and leaves stderr with the operation and the argument NAMES only (never a value); the same result with every origin right opens (the control);
  * vacuity: with `turn_gate.provenance` patched to return [] the planted address of origin `grounded` opens its card, so a test that did not look at the gate would not see it removed;
  * every opener from a line (AST): `_opened`, the trash card and the event card's revision call the check before they open anything, and the set of callers of `account_start.start`, of
    `_call_operation` and of `start_card` is the one listed here: a new opener fails the test until it is listed and gated;
  * the resolvers' origins: the real resolvers' outputs for one line of each operation carry an origin for every argument; the composed wording is `composed` and only the text; a written number is
    `line-number`, a message found by words `grounded`, a pick `picked`, an account of the configuration `config`;
  * the value oracle moved unchanged: the sha256 of every moved function, frozen from `runtime/natural_writes.py` at 764c9a3 (the file did not change up to 72cbec3), and `natural_writes.problems` is a
    delegate that answers as the gate's `value_problems`; what the oracle still asks of natural_writes is a short list (S41-11 deletes the line-claiming heads and must keep these).
The two fuzzers (test_natural_writes_dialogues.py, test_natural_writes_mail_dialogues.py) record the gate's refusals: none is a refusal of a call the oracle accepts.

Offline: stand-ins record the calls; every name and line is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_turn_gate_provenance.py
"""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

import pytest

import standin_tree as st
from test_calendar_write import world  # noqa: F401  (the calendar world: a real project to read the configuration of)
from test_natural_writes_dialogues import CONFIGS, NOW, Env, forget, moment  # noqa: F401  (the walk's world and its stand-ins; `forget` and `moment` are its fixtures)
from test_natural_writes_mail import Desk, read as read_mail  # noqa: F401  (the mail family's stand-in desk)

turn_gate = st.load("turn_gate")
natural_writes = st.load("natural_writes")
ops_natural_writes = st.load("ops_natural_writes")
ops_natural_calendar = st.load("ops_natural_calendar")
ops_natural_files = st.load("ops_natural_files")
ops_natural_mail = st.load("ops_natural_mail")
mail_compose = st.load("mail_compose")
drafts = st.load("drafts")
phrases = st.load("phrases")

RUNTIME = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
FAMILY = {"event-create": "calendar", "event-change": "calendar", "event-cancel": "calendar", "file-create": "files", "file-replace": "files", "file-save": "files",
          "mail-send": "mail", "mail-reply": "mail", "mail-draft": "mail", "mail-archive": "mail", "mail-trash": "mail", "mail-move": "mail", "mail-mark": "mail"}
LINES = {"event-create": "coloca na agenda troca de pneus depois de amanhã 9h", "event-change": "muda o título do evento 2 para ensaio da banda", "event-cancel": "desmarca o evento 7",      # validate: allow english-only -- a Portuguese line is the input under test
         "file-create": "cria um documento chamado ideias.md na pasta viagens com o texto: rascunho da lista de convidados",      # validate: allow english-only -- a Portuguese line is the input under test
         "file-replace": "atualiza o texto do arquivo notas da reunião com o texto rascunho da lista de convidados", "file-save": "sobe esse pdf",      # validate: allow english-only -- a Portuguese line is the input under test
         "mail-send": "manda um e-mail pra bia@exemplo.example dizendo que o contrato segue amanhã", "mail-reply": "responde o e-mail 3 dizendo que chego às 9",      # validate: allow english-only -- a Portuguese line is the input under test
         "mail-draft": "rascunha uma resposta ao e-mail 5 dizendo que confirmo", "mail-archive": "arquiva os e-mails 2 e 4", "mail-move": "move o e-mail 6 para a pasta contas",      # validate: allow english-only -- a Portuguese line is the input under test
         "mail-mark": "marca os e-mails 1 a 3 como lidos", "mail-trash": "apaga o e-mail 7"}      # validate: allow english-only -- a Portuguese line is the input under test
SECRET = {"bia@exemplo.example", "Dentist", "notes.txt", "Hello there", "inbox#3", "agenda#2", "roteiro", "2026-10-22T10:00", "rascunho"}      # values of the planted arguments: none may ever be printed
# One right result for each operation: the arguments and, for each, an origin its key may have.
GOOD = {
    "event-create": ({"account": "google", "title": "Dentist", "start": "2026-10-22T10:00", "end": "2026-10-22T11:00", "calendar": "personal"},
                     {"account": "config", "title": "line-span", "start": "time-engine", "end": "time-engine", "calendar": "line-span"}),
    "event-change": ({"account": "google", "event": "agenda#2", "title": "Dentist", "start": "2026-10-22T10:00"}, {"account": "config", "event": "line-number", "title": "line-span", "start": "time-engine"}),
    "event-cancel": ({"account": "google", "event": "agenda#2"}, {"account": "config", "event": "grounded"}),
    "file-create": ({"account": "google", "file_name": "notes.txt", "content": "rascunho", "folder": "cv"}, {"account": "line-span", "file_name": "line-span", "content": "line-span", "folder": "picked"}),
    "file-replace": ({"account": "google", "file": "roteiro", "content": "rascunho"}, {"account": "config", "file": "grounded", "content": "line-span"}),
    "file-save": ({"account": "google", "attachment": 11, "folder": "cv"}, {"account": "config", "attachment": "held", "folder": "config"}),
    "mail-send": ({"account": "google", "to": "bia@exemplo.example", "subject": "Hello there", "text": "rascunho"}, {"account": "config", "to": "line-span", "subject": "composed", "text": "composed"}),
    "mail-reply": ({"account": "google", "message": "inbox#3", "text": "rascunho"}, {"account": "line-span", "message": "line-number", "text": "composed"}),
    "mail-draft": ({"account": "google", "message": "inbox#3", "body": "rascunho"}, {"account": "picked", "message": "grounded", "body": "line-span"}),
    "mail-archive": ({"account": "google", "messages": "inbox#3,inbox#4"}, {"account": "config", "messages": "picked"}),
    "mail-trash": ({"account": "google", "messages": "inbox#3"}, {"account": "config", "messages": "line-number"}),
    "mail-move": ({"account": "google", "messages": "inbox#3", "folder": "contas"}, {"account": "config", "messages": "grounded", "folder": "picked"}),
    "mail-mark": ({"account": "google", "messages": "inbox#3", "state": "read"}, {"account": "config", "messages": "grounded", "state": "line-span"}),
}


# --- the table ------------------------------------------------------------------------------------------------------------------------------------------------


def test_every_key_every_operation_takes_has_a_row_and_every_origin_of_a_row_is_in_the_vocabulary():
    taken = {key for keys in turn_gate.OPS.values() for key in keys}
    assert taken <= set(turn_gate.ALLOWED), sorted(taken - set(turn_gate.ALLOWED))
    assert set(turn_gate.ALLOWED) <= taken | {"cc", "bcc", "name", "mail_folder"}, "a row for a key no operation takes is a loosening nobody asked for (the four listed are the spec's)"
    for key, origins in turn_gate.ALLOWED.items():
        assert origins and set(origins) <= set(turn_gate.ORIGINS), key
    assert set(GOOD) == set(turn_gate.OPS) - {"file-trash"}, "every operation but the trash card (its own test below) has a planted result here"
    for op, (args, origins) in GOOD.items():
        assert set(args) <= set(turn_gate.OPS[op]) and set(args) == set(origins), op
        assert turn_gate.provenance(op, args, origins) == [], (op, turn_gate.provenance(op, args, origins))


def test_l60_a_recipient_is_the_persons_words_the_configuration_a_cards_own_or_the_index_from_and_never_anything_else():
    for key in ("to", "cc", "bcc"):
        assert set(turn_gate.ALLOWED[key]) == {"line-span", "config", "index-from", "card-copy"}
        for origin in set(turn_gate.ORIGINS) - set(turn_gate.ALLOWED[key]):
            assert turn_gate.provenance("mail-send", {"account": "google", key: "bia@exemplo.example"}, {"account": "config", key: origin}) != [], (key, origin)
    assert "grounded" not in turn_gate.ALLOWED["to"], "an address is never read from a message found by words"
    for op in ("mail-reply", "mail-draft"):          # a reply goes to the index's From, chosen by the effect: it has no recipient argument at all, whatever the origin
        for origin in turn_gate.ORIGINS:
            found = turn_gate.provenance(op, {"account": "google", "message": "inbox#3", "to": "bia@exemplo.example"}, {"account": "config", "message": "grounded", "to": origin})
            if op == "mail-reply":
                assert found == ["to: not an argument of mail-reply"], (origin, found)


def test_the_composed_origin_is_the_text_of_an_e_mail_only():
    holders = sorted(key for key, origins in turn_gate.ALLOWED.items() if "composed" in origins)
    assert holders == ["body", "subject", "text"], holders
    for key in ("title", "content", "name", "file_name", "event", "account", "start", "attachment", "state", "to"):
        assert "composed" not in turn_gate.ALLOWED[key], key


def test_the_closed_table_refuses_what_it_does_not_name():
    good_args, good_origins = GOOD["mail-trash"]
    assert turn_gate.provenance("mail-forward", good_args, good_origins) == ["mail-forward: not an operation opened from a line"]
    assert turn_gate.provenance("mail-trash", dict(good_args, bcc="x@exemplo.example"), dict(good_origins, bcc="line-span")) == ["bcc: not an argument of mail-trash"]
    assert turn_gate.provenance("mail-trash", {**good_args, "mystery": 1}, {**good_origins, "mystery": "line-span"}) == ["mystery: not an argument of mail-trash"]
    assert turn_gate.provenance("mail-trash", good_args, {}) == ["account: no origin", "messages: no origin"]
    assert turn_gate.provenance("mail-trash", good_args, {**good_origins, "account": "the-model"}) == ["account: no origin"], "an origin outside the vocabulary is none"
    assert turn_gate.provenance("mail-trash", good_args, {**good_origins, "messages": ["picked"]}) == ["messages: no origin"]
    assert turn_gate.provenance("mail-trash", good_args, None) == ["arguments: no origins"] and turn_gate.provenance("mail-trash", None, {}) == ["arguments: no origins"]
    assert turn_gate.provenance(None, good_args, good_origins) == ["?: not an operation opened from a line"], "a name that is not a closed word is printed as ?"
    assert turn_gate.provenance("mail-trash", {"Bia <bia@exemplo.example>": 1}, {}) == ["?: not an argument of mail-trash"], "an argument's name is a word of code or `?`: never a value"


@pytest.mark.parametrize("op", sorted(GOOD))
def test_each_key_of_each_operation_refuses_every_origin_it_may_not_have_and_a_missing_one(op):
    args, origins = GOOD[op]
    for key in args:
        for origin in turn_gate.ORIGINS:
            found = turn_gate.provenance(op, args, dict(origins, **{key: origin}))
            assert (found == []) == (origin in turn_gate.ALLOWED[key]), (op, key, origin, found)
            assert all("Dentist" not in line and "bia@" not in line for line in found)
        gone = {k: v for k, v in origins.items() if k != key}
        assert turn_gate.provenance(op, args, gone) == [f"{key}: no origin"], (op, key)


def test_a_refusal_names_the_operation_and_the_arguments_and_never_a_value():
    args, origins = GOOD["mail-send"]
    found = turn_gate.provenance("mail-send", args, dict(origins, to="grounded", subject="grounded"))
    line, text = turn_gate.refusal_line("mail-send", found), turn_gate.refusal_text("mail-send", found)
    assert line == "gate: provenance refused mail-send (subject, to)"
    assert text == "error: nothing was opened: an argument of mail-send was not from your words or your choice (subject, to)"
    for out in (line, text, " ".join(found)):
        assert not any(value in out for value in SECRET), out


# --- integration: a planted resolver result opens no card ----------------------------------------------------------------------------------------------------------


def planted(monkeypatch, env, op, args, origins):
    """The family's resolver of `op` answers `args` with `origins`, whatever the line said; returns the box that says whether it was reached."""
    box = {"reached": 0}

    def resolve(ctx, name, slots, channel, sender, said=None):
        box["reached"] += 1
        return {"args": dict(args), "origins": dict(origins)}
    monkeypatch.setattr(ops_natural_writes.family_ops(FAMILY[op]), "resolve", resolve)
    return box


def run_line(env, op):
    drafts.clear()
    env.calls.clear()
    extras = {}
    reply = ops_natural_writes.open_line(env.project, env.ctx, LINES[op], "terminal", None, extras)
    return reply, extras


@pytest.mark.parametrize("op", sorted(GOOD))
def test_a_planted_result_with_every_origin_right_opens_its_card(world, moment, monkeypatch, op):  # noqa: F811
    env = Env(world, monkeypatch, CONFIGS["default"], "two")
    args, origins = GOOD[op]
    box = planted(monkeypatch, env, op, args, origins)
    reply, extras = run_line(env, op)
    assert box["reached"] == 1 and env.calls == [(op, args)] and extras.get("resend") == 7, (reply, env.calls)      # the control: the stand-in's card is made


@pytest.mark.parametrize("op", sorted(GOOD))
def test_a_planted_result_with_an_argument_missing_its_origin_or_of_an_origin_its_key_may_not_have_opens_no_card(world, moment, monkeypatch, capsys, op):  # noqa: F811
    env = Env(world, monkeypatch, CONFIGS["default"], "two")
    args, origins = GOOD[op]
    refused = 0
    for key in args:
        wrong = next(o for o in turn_gate.ORIGINS if o not in turn_gate.ALLOWED[key])
        for broken in ({k: v for k, v in origins.items() if k != key}, dict(origins, **{key: wrong})):
            box = planted(monkeypatch, env, op, args, broken)
            capsys.readouterr()
            reply, extras = run_line(env, op)
            err = capsys.readouterr().err
            refused += 1
            assert box["reached"] == 1, "the resolver was reached: the refusal is the gate's"
            assert env.calls == [] and "resend" not in extras, (op, key, env.calls)
            assert reply == turn_gate.refusal_text(op, [f"{key}: x"]), (op, key, reply)      # the terminal's precise error text (L62: only a phone gets IX_ASK_AGAIN)
            assert err == f"gate: provenance refused {op} ({key})\n", (op, key, err)
            assert not any(value in reply + err for value in SECRET), (reply, err)
            assert extras["stored"] == phrases.text("NW_PRIVATE_REPLY", env.ctx["cfg"]), "the stored row is the neutral word"
            assert ops_natural_writes.live("terminal", None) is None, "the draft is dropped"
    assert refused == 2 * len(args)


def test_a_phone_is_asked_again_in_one_plain_sentence_and_nothing_is_stored_but_the_neutral_word(world, monkeypatch, capsys):  # noqa: F811
    env = Env(world, monkeypatch, CONFIGS["default"], "two")
    extras = {}
    reply = ops_natural_writes.refused_sentence(env.ctx, "mail-send", ["to: origin grounded not allowed"], "messaging", extras)
    assert reply == phrases.text("IX_ASK_AGAIN", env.ctx["cfg"]) and "mail-send" not in reply and "error" not in reply
    assert extras["stored"] == phrases.text("NW_PRIVATE_REPLY", env.ctx["cfg"])
    assert capsys.readouterr().err == "gate: provenance refused mail-send (to)\n"


def test_an_address_taken_from_a_found_messages_body_opens_no_card_and_with_the_gate_patched_it_does(world, moment, monkeypatch, capsys):  # noqa: F811
    env = Env(world, monkeypatch, CONFIGS["default"], "two")
    args, origins = GOOD["mail-send"]
    box = planted(monkeypatch, env, "mail-send", args, dict(origins, to="grounded"))
    run_line(env, "mail-send")
    assert env.calls == [] and box["reached"] == 1, "L60: an address of the origin `grounded` opens no card"
    monkeypatch.setattr(turn_gate, "provenance", lambda op, a, o: [])          # VACUITY: the same result with the gate patched open opens the card, so this test sees the gate removed
    run_line(env, "mail-send")
    assert env.calls == [("mail-send", args)], "the control: without the gate the planted address opens its card"


def test_a_reply_that_carries_a_recipient_opens_no_card_whatever_its_origin(world, moment, monkeypatch):  # noqa: F811
    env = Env(world, monkeypatch, CONFIGS["default"], "two")
    args, origins = GOOD["mail-reply"]
    planted(monkeypatch, env, "mail-reply", dict(args, to="bia@exemplo.example"), dict(origins, to="index-from"))
    run_line(env, "mail-reply")
    assert env.calls == [], "L60: the index's From is chosen by the effect; a reply's arguments never carry it"


def test_a_resolver_that_returns_no_origins_at_all_opens_no_card(world, moment, monkeypatch):  # noqa: F811
    env = Env(world, monkeypatch, CONFIGS["default"], "two")
    args, _origins = GOOD["event-cancel"]
    monkeypatch.setattr(ops_natural_writes.family_ops("calendar"), "resolve", lambda ctx, op, slots, channel, sender, said=None: {"args": dict(args)})
    run_line(env, "event-cancel")
    assert env.calls == [], "fail closed: a resolver that cannot say where its arguments came from opens nothing"


# --- the trash card and the revision of an event's card ---------------------------------------------------------------------------------------------------------


def test_the_trash_card_opens_only_for_a_file_the_search_found_or_the_person_picked_and_a_folder_of_the_configuration(world, monkeypatch, capsys):  # noqa: F811
    ops_file_trash = st.load("ops_file_trash")
    env = Env(world, monkeypatch, CONFIGS["default"], "two")
    started = []
    monkeypatch.setattr(ops_file_trash, "start_card", lambda *a, **k: started.append(a) or {"pending": 9})
    monkeypatch.setattr(ops_file_trash, "_alias", lambda cfg, service, root: "cv")
    monkeypatch.setattr(ops_natural_writes, "_admit", lambda ctx, op, channel, sender: None)
    monkeypatch.setattr(ops_natural_writes, "_card_lines", lambda *a, **k: "")
    monkeypatch.setattr(ops_file_trash.account_start, "reply_text", lambda cfg, started_: "card sent")
    match = {"service": "google", "root": "FolderId0001", "id": "FILE-ID-1", "name": "Plan.docx", "exact": True}
    for origin in ("grounded", "picked"):
        started.clear()
        assert ops_file_trash._card("p", env.ctx, match, True, "terminal", None, {}, origin=origin) == "card sent" and len(started) == 1, origin
    for wrong in ("line-span", "composed", "held", "index-from"):
        started.clear()
        extras = {}
        reply = ops_file_trash._card("p", env.ctx, match, True, "terminal", None, extras, origin=wrong)
        assert started == [] and reply == turn_gate.refusal_text("file-trash", ["file: x"]) and "FILE-ID-1" not in reply + capsys.readouterr().err, wrong


def test_the_revision_of_an_events_card_is_checked_before_the_old_card_is_ended(capsys):
    revise = st.load("ops_event_revise")
    creating = {"account": "google", "title": "Dentist", "start": "2026-10-22T10:00", "end": "2026-10-22T11:00", "calendar": "personal", "location": None, "reminder_minutes": 10, "notes": "bring the file"}
    assert revise._refused({}, {"account": "google"}, "event_create", creating, "Dentist", {"local": "2026-10-22T10:00"}) is False, "the title and the time the line gave, the card's own parts"
    other = dict(creating, account="microsoft", calendar=None)
    assert revise._refused({}, {"account": "google"}, "event_create", other, None, None) is False, "an account the line named for a card that creates an event is the person's word"
    changing = {"account": "google", "event": "agenda#2", "calendar": "personal", "title": "Dentist"}
    assert revise._refused({}, {"account": "google"}, "event_change", changing, "Dentist", None) is False and capsys.readouterr().err == ""
    for planted in (dict(changing, to="bia@exemplo.example"), dict(changing, attachment=11), {"account": "google", "event": "agenda#2", "mail_folder": "x"}):
        assert revise._refused({}, {"account": "google"}, "event_change", planted, None, None) is True, planted
        assert "bia@" not in capsys.readouterr().err


# --- every opener from a line (AST) ---------------------------------------------------------------------------------------------------------------------------------


def parse(name: str):
    return ast.parse((RUNTIME / name).read_text(encoding="utf-8"))


def calls_in(tree, wanted):
    """[(enclosing function name, line)] of every call whose callee, written `x.name(...)` or `name(...)`, is `wanted`."""
    found = []

    def walk(node, scope):
        for child in ast.iter_child_nodes(node):
            inner = child.name if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else scope
            if isinstance(child, ast.Call):
                fn = child.func
                if (isinstance(fn, ast.Attribute) and fn.attr == wanted) or (isinstance(fn, ast.Name) and fn.id == wanted):
                    found.append((scope, child.lineno))
            walk(child, inner)
    walk(tree, "<module>")
    return found


def first_line(tree, scope, wanted):
    lines = [line for fn, line in calls_in(tree, wanted) if fn == scope]
    return min(lines) if lines else None


def test_every_opener_from_a_line_checks_provenance_before_it_opens_anything():
    writes = parse("ops_natural_writes.py")
    assert first_line(writes, "_opened", "provenance") is not None and first_line(writes, "_opened", "provenance") < first_line(writes, "_opened", "_call_operation")
    trash = parse("ops_file_trash.py")
    assert first_line(trash, "_card", "provenance") is not None and first_line(trash, "_card", "provenance") < first_line(trash, "_card", "start_card")
    revise = parse("ops_event_revise.py")
    assert first_line(revise, "_refused", "provenance") is not None, "the event card's revision asks the gate"
    assert first_line(revise, "revise", "_refused") is not None and first_line(revise, "revise", "_refused") < first_line(revise, "revise", "swap"), "before the old card is ended and the new one opened"


def account_start_callers() -> list:
    """[(file, function)] of every `account_start.start(...)` of the runtime: the one function that opens an effect's card."""
    found = []
    for path in sorted(RUNTIME.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))

        def walk(node, scope):
            for child in ast.iter_child_nodes(node):
                inner = child.name if isinstance(child, ast.FunctionDef) else scope
                if (isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute) and child.func.attr == "start" and isinstance(child.func.value, ast.Name)
                        and child.func.value.id == "account_start"):
                    found.append((path.name, scope))
                walk(child, inner)
        walk(tree, "<module>")
    return found


def test_the_set_of_callers_that_open_a_card_is_the_one_listed_here():
    """A line reaches `account_start.start` through the typed operations only (the typed command's own functions, whose arguments the person typed: `ops_calendar`, `ops_files`, `ops_mailbox`,
    `ops_mail_send`) and through `ops_file_trash.start_card`. The typed operations are called from `_call_operation` (after `_opened`'s check) and from the event card's revision (after
    `_refused`'s); `start_card` from `_card` (after its check) and from the typed `file_trash`. A caller that is not listed here is a way to open a card from a line that skips the gate."""
    assert account_start_callers() == [("ops_calendar.py", "_start"), ("ops_file_trash.py", "start_card"), ("ops_files.py", "file_create"), ("ops_files.py", "file_replace"),
                                       ("ops_files.py", "file_save"), ("ops_mail_send.py", "_start"), ("ops_mailbox.py", "_start")], account_start_callers()
    callers = {"_call_operation": [], "start_card": [], "swap": []}
    for path in sorted(RUNTIME.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for wanted in callers:
            callers[wanted] += [(path.name, scope) for scope, _line in calls_in(tree, wanted)]
    assert callers["_call_operation"] == [("ops_natural_writes.py", "_opened")], callers["_call_operation"]
    assert sorted(callers["start_card"]) == [("ops_file_trash.py", "_card"), ("ops_file_trash.py", "file_trash")], callers["start_card"]      # `file_trash` is the typed command
    assert sorted(callers["swap"]) == [("ops_card_revise.py", "_mail"), ("ops_event_revise.py", "revise")], callers["swap"]      # `_mail` opens through `natural_write`: `_opened`


def test_the_modules_that_open_a_card_for_a_line_name_no_typed_function_directly():
    """The typed operations are reached by name (`getattr(ops, row["call"])`) in `_call_operation` and in the event card's revision (`getattr(ops, name)` under `swap`, checked by `_refused`)."""
    tree = parse("ops_event_revise.py")
    assert [scope for scope, _line in calls_in(tree, "getattr")] == ["open_new"]
    tree = parse("ops_natural_writes.py")
    assert [scope for scope, _line in calls_in(tree, "getattr") if scope == "_call_operation"] == ["_call_operation"], "the one place a typed operation is called by name for a line"


# --- the origins the real resolvers give --------------------------------------------------------------------------------------------------------------------------


def resolved(desk, line, **more):
    found = read_mail(line)
    assert found is not None, line
    return ops_natural_mail.resolve(desk.ctx, found["op"], dict(found["slots"], **more.pop("slots", {})), "chat", None, [line])


def test_the_mail_resolver_gives_every_argument_its_origin(monkeypatch):
    desk = Desk(monkeypatch, accounts=("google",), sources=(("inbox", "google"),), folders={"contas": "L1"})
    out = resolved(desk, "arquiva os e-mails 2 e 4")      # validate: allow english-only -- a Portuguese line is the input under test
    assert out["args"] == {"account": "google", "messages": "inbox#2,inbox#4"} and out["origins"] == {"account": "config", "messages": "line-number"}
    out = resolved(desk, "responde o último e-mail dizendo que ok")      # validate: allow english-only -- a Portuguese line is the input under test
    assert out["origins"] == {"account": "config", "message": "grounded", "text": "line-span"}, "the newest is found in the index: grounded, and the text is the person's"
    out = resolved(desk, "move o e-mail 3 para a pasta contas")      # validate: allow english-only -- a Portuguese line is the input under test
    assert out["origins"] == {"account": "config", "messages": "line-number", "folder": "line-span"}
    out = resolved(desk, "marca os e-mails 1 a 3 como lidos")      # validate: allow english-only -- a Portuguese line is the input under test
    assert out["origins"] == {"account": "config", "messages": "line-number", "state": "line-span"}
    out = resolved(desk, "manda um e-mail pra bia@exemplo.example com o assunto Oi dizendo que tudo bem")      # validate: allow english-only -- a Portuguese line is the input under test
    assert out["origins"] == {"account": "config", "to": "line-span", "subject": "line-span", "text": "line-span"}
    for out in (resolved(desk, "arquiva os e-mails 2 e 4"), resolved(desk, "apaga o e-mail 7")):      # validate: allow english-only -- a Portuguese line is the input under test
        assert turn_gate.provenance("mail-archive" if "inbox#2" in out["args"]["messages"] else "mail-trash", out["args"], out["origins"]) == []


def test_a_message_chosen_among_those_listed_is_picked_and_the_account_of_an_answer_is_picked(monkeypatch):
    desk = Desk(monkeypatch, accounts=("google", "microsoft"), sources=(("inbox", "google"),))
    out = resolved(desk, "arquiva o e-mail 3", slots={"account": "google", "_origins": {"account": "picked"}})      # validate: allow english-only -- a Portuguese line is the input under test
    assert out["origins"]["account"] == "picked", "the account the person chose among the two asked"
    out = resolved(desk, "arquiva o e-mail 3", slots={"chosen": "inbox#9", "_origins": {"chosen": "picked"}})      # validate: allow english-only -- a Portuguese line is the input under test
    assert out["args"]["messages"] == "inbox#9" and out["origins"]["messages"] == "picked"


def test_the_model_s_wording_is_composed_the_persons_own_subject_stays_theirs_and_no_address_is_ever_composed(monkeypatch):
    desk = Desk(monkeypatch, accounts=("google",))
    slots = {"to": ["bia@exemplo.example"], "body": "avisa que o contrato segue amanhã", "_compose": True, "_ai_subject": True}      # validate: allow english-only -- a Portuguese line is the input under test
    monkeypatch.setattr(mail_compose, "write", lambda ctx, channel, sender, to, subject, text, ai=False, **k: {"subject": "Contrato", "body": "O contrato segue amanhã.", "composed": True})      # validate: allow english-only -- a Portuguese line is the input under test
    out = ops_natural_mail.resolve(desk.ctx, "mail-send", dict(slots), "chat", None, ["manda um e-mail"])
    assert out["origins"] == {"account": "config", "to": "line-span", "subject": "composed", "text": "composed"}
    assert turn_gate.provenance("mail-send", out["args"], out["origins"]) == []
    out = ops_natural_mail.resolve(desk.ctx, "mail-send", dict(slots, subject="Oi"), "chat", None, ["manda um e-mail"])
    assert out["origins"]["subject"] == "line-span" and out["origins"]["text"] == "composed", "a subject the person gave is theirs even when the body is worded"
    monkeypatch.setattr(mail_compose, "write", lambda ctx, channel, sender, to, subject, text, ai=False, **k: {"subject": "Oi", "body": "ok", "composed": False})
    out = ops_natural_mail.resolve(desk.ctx, "mail-send", dict(slots), "chat", None, ["manda um e-mail"])
    assert out["origins"]["subject"] == "line-span" and out["origins"]["text"] == "line-span", "a call that failed leaves the person's own words, which say so"
    revised = ops_natural_mail.resolve(desk.ctx, "mail-send", {"to": ["bia@exemplo.example"], "subject": "Novo", "body": "texto", "account": "google",
                                                            "_origins": {"account": "card-copy", "to": "card-copy", "subject": "composed", "body": "composed"}}, "chat", None, [])
    assert revised["origins"] == {"account": "card-copy", "to": "card-copy", "subject": "composed", "text": "composed"}
    assert turn_gate.provenance("mail-send", revised["args"], revised["origins"]) == []


def test_an_account_the_person_picked_is_picked_and_one_the_person_wrote_is_theirs(world, moment, monkeypatch):  # noqa: F811
    """The draft records `picked` for the slot a pick fills (`ops_natural_writes.answer`); an account a service word of the line names is the person's own words."""
    env = Env(world, monkeypatch, CONFIGS["two"], "one")
    origins = []
    real = turn_gate.provenance
    monkeypatch.setattr(turn_gate, "provenance", lambda op, args, got: origins.append(dict(got)) or real(op, args, got))
    env.step("coloca na agenda troca de pneus depois de amanhã 9h")      # validate: allow english-only -- a Portuguese line is the input under test
    state = ops_natural_writes.live("terminal", None)
    assert state is not None and state["need"] == "account" and not state["origins"], state
    env.step("2")
    assert env.calls == [("event-create", {"account": "microsoft", "title": "troca de pneus", "start": "2026-10-21T09:00"})], env.calls
    assert origins == [{"account": "picked", "title": "line-span", "start": "time-engine"}], origins
    env.calls.clear()
    env.step("coloca na agenda troca de pneus depois de amanhã 9h no outlook")      # validate: allow english-only -- a Portuguese line is the input under test
    assert env.calls and env.calls[-1][1]["account"] == "microsoft" and origins[-1]["account"] == "line-span", (origins, env.calls)


def test_the_origins_of_a_seed_reach_the_gate_and_a_seed_part_with_no_declared_origin_has_none_and_opens_no_card(world, moment, monkeypatch, capsys):  # noqa: F811
    """A card's revision opens its new card through a seed whose parts are the card's own (`card-copy`) and the reviser's wording (`composed`); an event found by words is `grounded`. The tags
    travel with the seed object, which equals a plain dict, to the gate. A part the seed supplies and does not declare has NO origin (`undeclared`) and the argument made of it opens no card."""
    env = Env(world, monkeypatch, CONFIGS["default"], "two")
    seen = []
    real = turn_gate.provenance
    monkeypatch.setattr(turn_gate, "provenance", lambda op, args, got: seen.append((op, dict(got))) or real(op, args, got))
    parts = {"op": "mail-send", "slots": {"account": "google", "to": ["bia@exemplo.example"], "subject": "Novo", "body": "texto"}}
    seed = turn_gate.Seed(parts, {"account": "card-copy", "to": "card-copy", "subject": "composed", "body": "composed"})
    assert seed == parts and isinstance(seed, dict) and seed.origins["to"] == "card-copy"
    ops_natural_writes.open_line(env.project, env.ctx, "", "terminal", None, {}, seed=seed)
    assert seen == [("mail-send", {"account": "card-copy", "to": "card-copy", "subject": "composed", "text": "composed"})], seen
    assert env.calls[-1][1]["to"] == "bia@exemplo.example" and env.gate_refusals == []
    seen.clear()
    env.calls.clear()
    reply = ops_natural_writes.open_line(env.project, env.ctx, "", "terminal", None, {}, seed=dict(parts))      # a plain dict declares nothing
    assert seen == [("mail-send", {"account": "undeclared", "to": "undeclared", "subject": "undeclared", "text": "undeclared"})] and env.calls == [], (seen, env.calls)
    assert reply == turn_gate.refusal_text("mail-send", ["account: x", "subject: x", "text: x", "to: x"]) and "bia@" not in reply + capsys.readouterr().err
    partly = turn_gate.Seed(parts, {"account": "card-copy", "to": "card-copy", "subject": "composed"})      # the body declares nothing
    ops_natural_writes.open_line(env.project, env.ctx, "", "terminal", None, {}, seed=partly)
    assert env.calls == [] and seen[-1][1]["text"] == "undeclared", seen[-1]
    monkeypatch.setattr(turn_gate, "provenance", lambda op, a, o: [])          # VACUITY: with the gate patched open the same plain-dict seed opens its card
    ops_natural_writes.open_line(env.project, env.ctx, "", "terminal", None, {}, seed=dict(parts))
    assert env.calls and env.calls[-1][0] == "mail-send", "the control: without the gate the undeclared card opens"
    monkeypatch.setattr(turn_gate, "provenance", lambda op, args, got: seen.append((op, dict(got))) or real(op, args, got))
    seen.clear()
    env.calls.clear()
    found = turn_gate.Seed({"op": "event-cancel", "slots": {"event": 2, "source": "agenda"}}, {"event": "grounded"})
    ops_natural_writes.open_line(env.project, env.ctx, "desmarca o evento 2", "terminal", None, {}, seed=found)      # validate: allow english-only -- a Portuguese line is the input under test
    assert seen == [("event-cancel", {"account": "config", "event": "grounded"})], seen
    seen.clear()
    env.calls.clear()
    ops_natural_writes.open_line(env.project, env.ctx, "desmarca o evento 2", "terminal", None, {}, seed={"op": "event-cancel", "slots": {"event": 2, "source": "agenda"}})      # validate: allow english-only -- a Portuguese line is the input under test
    assert seen == [("event-cancel", {"account": "config", "event": "undeclared"})] and env.calls == [], (seen, env.calls)


def test_a_seed_with_no_slots_is_the_closed_reading_and_its_defaults_stand(world, moment, monkeypatch):  # noqa: F811
    """The messaging modules' `{"op": "event-create"}` supplies no part of its own: the line is read by the closed forms and each argument has the default origin of what the reading made."""
    env = Env(world, monkeypatch, CONFIGS["default"], "two")
    seen = []
    real = turn_gate.provenance
    monkeypatch.setattr(turn_gate, "provenance", lambda op, args, got: seen.append((op, dict(got))) or real(op, args, got))
    ops_natural_writes.open_line(env.project, env.ctx, "coloca na agenda troca de pneus depois de amanhã 9h no google", "terminal", None, {}, seed={"op": "event-create"})      # validate: allow english-only -- a Portuguese line is the input under test
    assert seen and seen[-1][1] == {"account": "line-span", "title": "line-span", "start": "time-engine"} and env.calls, seen


def test_a_plain_dict_seed_may_declare_its_origins_in_an_origins_key_for_a_module_that_cannot_import_the_gate(world, moment, monkeypatch):  # noqa: F811
    """The messaging modules build the seed of a held file's save as data: `origins` is a key of it. A seed with the account and no declaration is refused; with it, the card opens."""
    env = Env(world, monkeypatch, CONFIGS["two"], "one")
    monkeypatch.setattr(ops_natural_files, "held_files", lambda ctx, channel, sender: [{"id": 11, "name": "Contract.pdf", "kind": "pdf", "bytes": 1000}])
    seen = []
    real = turn_gate.provenance
    monkeypatch.setattr(turn_gate, "provenance", lambda op, args, got: seen.append((op, dict(got))) or real(op, args, got))
    plain = {"op": "file-save", "attachment": 11, "account": "google", "folders": "first"}
    ops_natural_writes.open_line(env.project, env.ctx, "", "terminal", None, {}, seed=dict(plain))
    assert env.calls == [] and seen[-1][1]["account"] == "undeclared", seen
    ops_natural_writes.open_line(env.project, env.ctx, "", "terminal", None, {}, seed=dict(plain, origins={"account": "picked"}))
    assert env.calls and env.calls[-1][1]["account"] == "google" and seen[-1][1]["account"] == "picked", seen


def test_the_producers_of_a_seed_declare_the_origin_of_every_part_they_supply():
    """mail_compose.seed, the interpreter's event seed, the mail target seed and the messaging modules' file-save seeds."""
    compose = st.load("mail_compose")
    decision = {"spans": {"to": "bia@exemplo.example", "subject": "Oi", "body": "avisa que ok"}, "args": {}}      # validate: allow english-only -- a Portuguese span is the input under test
    seed = compose.seed("mail-send", decision, "manda um e-mail pra bia@exemplo.example com o assunto Oi avisando que ok")      # validate: allow english-only -- a Portuguese line is the input under test
    assert isinstance(seed, turn_gate.Seed) and seed.origins == {"to": "line-span", "subject": "line-span", "body": "line-span"}, seed
    target = ops_natural_mail.mail_target_seed("mail-move", {"spans": {"target": "banco", "state": None}, "args": {"folder": "contas"}}, None, "move o e-mail do banco para contas")      # validate: allow english-only -- a Portuguese line is the input under test
    assert isinstance(target, turn_gate.Seed) and target.origins == {"folder_name": "line-span"}, target
    for name in ("messaging_attach.py",):
        text = (RUNTIME / name).read_text(encoding="utf-8")
        assert text.count('"op": "file-save"') == 2 and text.count('"origins": {"account":') == 2, name
    assert 'origins={"start": "time-engine", "title": "line-span"}' in (RUNTIME / "messaging_remind.py").read_text(encoding="utf-8"), "the kind question answered event: the engine's reading and the person's words"
    interpret = (RUNTIME / "ops_interpret.py").read_text(encoding="utf-8")
    assert "turn_gate.time_origin(time_)" in interpret and "turn_gate.Seed(" in interpret


def test_a_time_the_model_read_is_not_labelled_as_the_engines(world, moment, monkeypatch):  # noqa: F811
    """The interpreter says who read a time (`{"local", "source"}`: "code" or "model"). `time-engine` is the engine's; the model's is `time-model`, allowed for a start and an end pending the
    maintainer's decision (it keeps slice S1: the card shows the time and is approved by hash); refusing it is deleting the word from `turn_gate.ALLOWED`."""
    assert turn_gate.time_origin({"local": "2026-10-20T15:00", "source": "code"}) == "time-engine"
    for time_ in ({"local": "2026-10-20T15:00", "source": "model"}, {"local": "2026-10-20T15:00"}, None, "2026-10-20T15:00"):
        assert turn_gate.time_origin(time_) == "time-model", time_
    assert "time-model" in turn_gate.ORIGINS and "time-model" in turn_gate.ALLOWED["start"] and "time-model" in turn_gate.ALLOWED["end"]
    assert not any("time-model" in origins for key, origins in turn_gate.ALLOWED.items() if key not in ("start", "end")), "only a time may be the model's"
    ops_interpret = st.load("ops_interpret")
    env = Env(world, monkeypatch, CONFIGS["default"], "two")
    caught, real_open_line = [], ops_natural_writes.open_line
    monkeypatch.setattr(ops_natural_writes, "open_line", lambda project, ctx, said, channel, sender, extras, *, seed=None, hint=None: caught.append(seed) or "card")
    for source, wanted in (("code", "time-engine"), ("model", "time-model")):
        decision = {"op": "event-create", "time": {"local": "2026-10-20T15:00", "source": source}, "spans": {"title": "dentista"}, "args": {}}
        ops_interpret._carry_out(env.project, env.ctx, decision, "pon dentista mañana a las 3", None, {})      # validate: allow english-only -- a Spanish line is the input under test
        assert isinstance(caught[-1], turn_gate.Seed) and caught[-1].origins["start"] == wanted and caught[-1].origins["title"] == "line-span", (source, caught[-1])
    monkeypatch.setattr(ops_natural_writes, "open_line", real_open_line)
    model_seed = caught[-1]
    ops_natural_writes.open_line(env.project, env.ctx, "pon dentista mañana a las 3", "terminal", None, {}, seed=model_seed)      # validate: allow english-only -- a Spanish line is the input under test
    assert env.calls and env.calls[-1][0] == "event-create", "allowed today: the card shows the time and is approved by hash (slice S1)"
    env.calls.clear()
    monkeypatch.setitem(turn_gate.ALLOWED, "start", ("time-engine", "card-copy"))          # the one-line change that refuses the model's time
    ops_natural_writes.open_line(env.project, env.ctx, "pon dentista mañana a las 3", "terminal", None, {}, seed=model_seed)      # validate: allow english-only -- a Spanish line is the input under test
    assert env.calls == [], "with `time-model` out of ALLOWED the model's time opens no card"


def test_the_number_said_after_a_list_opens_the_card_with_the_time_of_whoever_read_it(world, moment, monkeypatch):  # noqa: F811
    """The list of events remembers who read the new time of a change (`note_start_source`); the card a number opens from it declares `time-engine` or `time-model` accordingly."""
    env = Env(world, monkeypatch, CONFIGS["default"], "two")
    lookup = st.load("event_lookup")
    lookup.forget_lists()
    for source, wanted in (("code", "time-engine"), ("model", "time-model"), (None, "time-model")):
        lookup._remember(env.ctx, "messaging", "owner", "event-change", "2026-10-22T15:00", [("agenda", 2, "2026-10-19T09:00")])
        lookup.note_start_source(env.ctx, "owner", source)
        record = lookup._LISTS[lookup._slot(env.ctx, "messaging", "owner")]
        assert record["start_source"] == source and turn_gate.time_origin({"source": record.get("start_source")}) == wanted, (source, record)
    lookup.forget_lists()
    lookup.note_start_source(env.ctx, "owner", "code")      # no list: nothing to note, and nothing raised
    lookup.note_start_source({}, "owner", "code")


def test_a_reply_draft_has_no_recipient_and_no_subject():
    args, origins = {"account": "google", "message": "inbox#3", "body": "b"}, {"account": "config", "message": "grounded", "body": "line-span"}
    assert turn_gate.provenance("mail-draft", args, origins) == []
    for key in ("to", "cc", "bcc", "subject"):
        found = turn_gate.provenance("mail-draft", {**args, key: "x"}, {**origins, key: "card-copy" if key != "subject" else "line-span"})
        assert found == [f"{key}: not an argument of mail-draft"], (key, found)
    new = {"account": "google", "to": "bia@exemplo.example", "subject": "Hi", "body": "b"}
    assert turn_gate.provenance("mail-draft", new, {"account": "config", "to": "line-span", "subject": "line-span", "body": "line-span"}) == [], "a new draft keeps them"


# --- the value oracle moved unchanged -----------------------------------------------------------------------------------------------------------------------------

FROZEN_AT = "764c9a3"
ORACLE_SHA256 = {      # sha256 of the source of each function, class and constant of the oracle in runtime/natural_writes.py at 764c9a3 (`problems` under its old name)
    "TEXT_ARGS": "e93cb67094df2d44ca8c2708f03b88eb9f5196658e7d3637bb2bd28c089d6d6c",
    "SECTION_OF": "cd7ccc28402f1955c90e585219bc53938bdf3291c784fb9ce352eaa51e8db976",
    "ADDRESS": "37862268d2d73a3791725c1c8b65768927269e2d6f8b26b9581e77a7897cf19b",
    "_words": "088ac91e35e1fe338a0f1443c2620fc439c19a46b3570fdffa709004b693d9e4",
    "_subsequence": "b3fe2ac0a615d8c0c5b0004199e59b2c61e118031657bd819beb92f9ece6e4f4",
    "_contiguous": "db9e322c8342f6d9f4538bf45806cf5fdee60ac0e6d9325e7ece714532b85dae",
    "problems": "3183c4574c38e98918f0df49cb47036c082df7f99e976282015a062fb5eba332",
    "_Frame": "d599240f16691fef1ff43ac4e1efabb5668f4a1f20fdae32b3e0633d0b5d9f34",
    "_address_problems": "63dbef9311610702808c527db2077e7205b6328614a7901247f901e5d41394d6",
    "_written_numbers": "0148836a14d3faeeda1d3923aedaa39af5e0e3752d7e464cc4838695b6137cd9",
    "_entry_words": "62fd949f541c019341911857ed3169ba9bfb234da827ba34130fe3d5787e83fb",
    "_words_of_the_line": "2fc4349181cccfef387bbd851a80a1a6ad6282e91883b56bdf39e1157977526e",
    "_message_problems": "9227ec44813d6addb0c953ef1b640878bad45ded72c58ba446b014f9a3fabbd1",
    "_state_said": "f302c894be6fd0fe478205412c83c521904b0897c9d82292697521dcfca0cca1",
    "_of_service": "de6c0d7a4bfcc5cfca6ee5f6e0dd717dc47157a70d7601cd9a94010b11295b25",
    "_mailbox_account": "8b337fec0aa376b57dc97a89b9e85fdc9d2802f2cfdeb23a9d8ef94722463372",
    "_named": "28163deb8de0a94341a068c23cc207ded1459b7f44ea5baa0c5fb3407504cee8",
    "_account_problems": "68f20ec3aa6dc5b73268b84d9d106ac19076936f6dabd28b070a02901fce09b7",
    "_hour_written": "530c97c9c840ae3d8afc8bff3ff58137c86b0e5a22b0d103b4764e39d6130ef7",
    "_range_texts": "0d8cfe31abc4c08fb138da98c930cd50ce53f0bc9cb6788c41355aed2aaf7ce9",
    "_norm": "9a82eac7ad16998080ac8cf74e3f5fb1b2c43ae44ef0190375e28e5b3a5803a1",
    "_variants": "9894799c384042ddb7513a974ac178eece5de3635cc7cb156f137ba7e0e82889",
    "_time_problems": "d16a73a9cf56dedac3ebd3ab16d80226b24803b21fbaa47d29521107c3abd78a",
}
FROM_NATURAL_WRITES = {"LIST_MAX", "Line", "_facts", "_tables", "listed", "service"}      # what the oracle still asks of natural_writes (S41-11 deletes the line-claiming heads and keeps these)


def segments(path: Path, names) -> dict:
    source = path.read_text(encoding="utf-8")
    out = {}
    for node in ast.parse(source).body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in names:
            out[node.name] = ast.get_source_segment(source, node)
        elif isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id in names:
            out[node.targets[0].id] = ast.get_source_segment(source, node)
    return out


def test_the_value_oracle_moved_unchanged():
    moved = segments(RUNTIME / "turn_gate.py", {name if name != "problems" else "value_problems" for name in ORACLE_SHA256})
    assert set(moved) == {name if name != "problems" else "value_problems" for name in ORACLE_SHA256}, "every function of the oracle is in the gate"
    moved["problems"] = moved.pop("value_problems").replace("def value_problems(", "def problems(", 1)      # the one change: its name
    for name, wanted in ORACLE_SHA256.items():
        assert hashlib.sha256(moved[name].encode("utf-8")).hexdigest() == wanted, f"{name} changed since {FROZEN_AT}: the fuzz's oracle moves, it is not edited"
    left = segments(RUNTIME / "natural_writes.py", set(ORACLE_SHA256) - {"problems"})
    assert left == {}, "the old home no longer holds a copy of the moved functions"


def test_natural_writes_problems_is_a_delegate_that_answers_as_the_gate_does():
    said = ["marca dentista quinta às 10h no google"]      # validate: allow english-only -- a Portuguese line is the input under test
    two = CONFIGS["two"]
    for args in ({"account": "google", "title": "dentista", "start": "2026-10-22T10:00"}, {"account": "google", "title": "Invented", "start": "2026-10-23T10:00"}):
        assert natural_writes.problems("event-create", args, said, two, {}, NOW) == turn_gate.value_problems("event-create", args, said, two, {}, NOW)
    assert natural_writes.problems("event-create", {"account": "google", "title": "Invented", "start": "2026-10-23T10:00"}, said, two, {}, NOW) != []
    body = (RUNTIME / "natural_writes.py").read_text(encoding="utf-8")
    assert "turn_gate" in body and "def problems(" in body and len(body.split("def problems(")[1].split("\n\n\n")[0].splitlines()) <= 5, "one line of body and its text"


def test_what_the_oracle_still_asks_of_natural_writes_is_the_short_list_s41_11_must_keep():
    tree = parse("turn_gate.py")
    imported = {alias.name for node in tree.body if isinstance(node, ast.ImportFrom) and node.module == "natural_writes" for alias in node.names}
    assert imported == FROM_NATURAL_WRITES, imported
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)} | {node.value.id for node in ast.walk(tree) if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)}
    assert "natural_writes" not in names, "the gate never reaches the heads of natural_writes by attribute"


def test_the_gate_imports_no_layer_above_it():
    tree = parse("turn_gate.py")
    modules = {alias.name for node in tree.body if isinstance(node, ast.Import) for alias in node.names} | {node.module for node in tree.body if isinstance(node, ast.ImportFrom)}
    assert modules <= {"__future__", "collections", "contextlib", "importlib", "os", "re", "sys", "threading", "time", "unicodedata", "natural", "natural_time", "natural_writes", "registry_data"}, modules


def test_the_walk_the_fuzzers_make_passes_through_the_gate_and_none_of_its_calls_is_refused(world, moment, monkeypatch):  # noqa: F811
    """The same walk as test_natural_writes_dialogues.py on a small sample of its corpus (that file asserts it over the whole sample): every card the walk opens went through `provenance`."""
    env = Env(world, monkeypatch, CONFIGS["default"], "two")
    rows = [json.loads(raw) for raw in (HERE / "natural_writes_corpus.jsonl").read_text(encoding="utf-8").splitlines() if raw.strip()]
    opened = 0
    for row in rows[::5]:
        drafts.clear()
        env.calls.clear()
        env.step(row["line"])
        env.check([row["line"]], row["op"] == "work")
        opened = env.opened
    assert env.bad == [] and env.gate_refusals == [] and env.gate_calls >= opened > 20, (env.gate_calls, opened, env.gate_refusals[:4])
