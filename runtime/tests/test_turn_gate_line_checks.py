"""The gate's second section (S41-5, limits L54 and L63, slice R2-F1): the line checks. Taint (a question about the person's own data is not a web search), private routing (a reminder or a
write in words never leaves the host) and decision numbers from the line (a decision a model chose is believed only for the one number the line writes).

Held here:
  * one home each (AST): no module but runtime/turn_gate.py assigns `POSSESSIVES` or `NOUNS`; no module but turn_gate.py (and natural.py, which defines them) names the `private` or the
    `decision_numbers` of natural.py; research_guard.py and command_words.vet are gone; the scan finds a planted use in a scratch copy (the control);
  * the moved lists are byte-identical to those of research_guard.py at 764c9a3 (their sha256, frozen here), so no word was lost in the move, and every line of the deleted
    test_research_guard.py is held here (36 possessive forms, 16 general questions);
  * taint: 20 possessive questions in the six languages never start the research stand-in and the reply is IX_ASK_AGAIN, 10 bare-noun questions reach it; with `research_allowed` patched
    open the same possessive question reaches it and the assertion fails (the control);
  * private routing: a private line (a reminder, a write) whose daily call fails gets IX_OUTAGE and never the planning agent; the stored row is the neutral word; a long private line is
    the `long-line` clarify; with `private_line` patched to False the private line reaches the agent and the assertion fails (the control);
  * decision numbers: for every operation of `ops_natural.VETTED` chosen with a number, a line with no number, with two, with a date or a time, or with another number than the model's
    asks which (`NAT_WHICH_DECISION` for a decision, `NAT_ASK_ID` for an act) and calls no operation; the line with exactly the model's number reaches the plan question (D5); with
    `number_believed` patched to True the same lines get past the check and the assertion fails (the control).

Offline: the research run, the daily route and the operations are stand-ins that count their calls; every name and line is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_turn_gate_line_checks.py
"""
from __future__ import annotations

import ast
import hashlib
import json
import shutil
from pathlib import Path

import pytest

import standin_tree as st
import test_ops_interpret_limits as til
from plan_confirm_kit import OWNER, ops_natural, ops_say, phrases, plan_confirm, rig  # noqa: F401
from test_ask import accept, write_config
from test_ops_interpret_dispatch import IX_PROFILES, IX_SENDERS, phone, prepare  # noqa: F401
from test_ops_natural import world  # noqa: F401  (the real-operations world fixture)
from test_research import research, set_limits  # noqa: F401  (the world of the research stand-in)

turn_gate = st.load("turn_gate")
natural = st.load("natural")
interpreter = st.load("interpreter")
interpreter_route = st.load("interpreter_route")
command_words = st.load("command_words")
ops = st.load("ops")
ops_core = st.load("ops_core")
ops_research = st.load("ops_research")
ops_interpret = st.load("ops_interpret")

RUNTIME = Path(__file__).resolve().parents[1]
GATE_AND_NATURAL = {"turn_gate.py", "natural.py"}
NATURAL_NAMES = {"private", "decision_numbers"}
LIST_NAMES = {"POSSESSIVES", "NOUNS"}
FROZEN_AT = "764c9a3"
LISTS_SHA256 = "490dedad1ad6e04a17f4e0ffdf8c09d705cccec778289cb8ec9872bcacc28891"      # sha256 of the JSON of [POSSESSIVES, CLITIC_POSSESSIVES, NOUNS] of runtime/research_guard.py at 764c9a3
ITEMS_MAIL_NOUNS = {"email", "mail", "message", "mensagem", "mensaje", "courriel", "nachricht", "messaggio", "correo"}      # runtime/items_mail.py has a list of its own with the name NOUNS: the singular names of a message
NONE = '{"v":1,"kind":"none"}'


# --- one home each --------------------------------------------------------------------------------------------------------------------------------


def python_files(folder: Path) -> list:
    return sorted(list(folder.glob("*.py")) + list(folder.glob("handlers/*.py")))


def natural_uses(folder: Path) -> list:
    """(file, line) of every way to the `private` or the `decision_numbers` of natural.py that the python files of `folder` hold, found by the shape of the code: any attribute of that
    name however the module was reached (a name, `importlib.import_module("natural")` itself, an alias, `sys.modules`), a string of that name given to `getattr`, a subscript by that name,
    and `from natural import private`, `from natural import decision_numbers` or `from natural import *`."""
    found = []
    for path in python_files(folder):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), filename=str(path))):
            hit = False
            if isinstance(node, ast.Attribute):
                hit = node.attr in NATURAL_NAMES
            elif isinstance(node, ast.ImportFrom) and node.module == "natural":
                hit = bool({a.name for a in node.names} & (NATURAL_NAMES | {"*"}))
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "getattr":
                hit = any(isinstance(a, ast.Constant) and a.value in NATURAL_NAMES for a in node.args)
            elif isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant):
                hit = node.slice.value in NATURAL_NAMES
            if hit:
                found.append((path.name, node.lineno))
    return found


def list_assignments(folder: Path) -> list:
    """(file, line) of every assignment, annotated assignment, augmented assignment or `setattr` of the names `POSSESSIVES` and `NOUNS` in the python files of `folder`."""
    found = []
    for path in python_files(folder):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), filename=str(path))):
            targets = []
            if isinstance(node, ast.Assign):
                targets = node.targets
            elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
                targets = [node.target]
            names = {t.id for t in targets if isinstance(t, ast.Name)} | {t.attr for t in targets if isinstance(t, ast.Attribute)}
            if (path.name == "items_mail.py" and names == {"NOUNS"} and isinstance(getattr(node, "value", None), ast.Set)
                    and {e.value for e in node.value.elts if isinstance(e, ast.Constant)} == ITEMS_MAIL_NOUNS):
                continue      # that list is not the taint's: it holds the nine names of a message and nothing else (a changed one is found)
            if names & LIST_NAMES or (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "setattr"
                                      and any(isinstance(a, ast.Constant) and a.value in LIST_NAMES for a in node.args)):
                found.append((path.name, node.lineno))
    return found


def test_no_module_but_the_gate_assigns_the_possessive_lists():
    found = list_assignments(RUNTIME)
    assert {name for name, _ in found} == {"turn_gate.py"}, found      # the control: the scan sees the two assignments in the gate, and nowhere else
    assert len([1 for name, _ in found if name == "turn_gate.py"]) == 2
    assert [name for name, _ in found if name != "turn_gate.py"] == []


def test_no_module_but_the_gate_asks_the_private_line_or_the_decision_numbers_of_natural():
    found = natural_uses(RUNTIME)
    assert "turn_gate.py" in {name for name, _ in found}, found      # the control: the scan sees the gate's two calls
    assert [n for n in found if n[0] not in GATE_AND_NATURAL] == [], "every other module asks the gate (turn_gate.private_line, the_number, number_believed)"


def test_the_old_homes_are_gone():
    assert not (RUNTIME / "research_guard.py").exists()
    assert not hasattr(command_words, "vet")
    for name in ("research_allowed", "personal", "private_line", "the_number", "number_believed", "POSSESSIVES", "CLITIC_POSSESSIVES", "NOUNS", "FORMS", "fold"):
        assert hasattr(turn_gate, name), name


PLANTS = {
    "ops_research.py": 'def p1():\n    POSSESSIVES = ["my"]\n',
    "ops_say.py": 'def p2():\n    NOUNS: list = []\n',
    "ops_items.py": 'def p3():\n    return natural.private("x")\n',
    "ops_natural_mail.py": 'def p4():\n    return importlib.import_module("natural").decision_numbers("x")\n',
    "ops_file_read.py": 'def p5():\n    from natural import private\n    return private("x")\n',
    "ops_ask.py": 'def p6():\n    return getattr(natural, "decision_numbers")("x")\n',
    "ops_cancel.py": 'def p7():\n    return vars(natural)["private"]("x")\n',
    "ops_files.py": 'def p8():\n    setattr(turn_gate, "NOUNS", [])\n',
}


def test_vacuity_the_scans_find_every_planted_use_in_a_scratch_copy(tmp_path):
    copy = tmp_path / "runtime"
    (copy / "handlers").mkdir(parents=True)
    for path in python_files(RUNTIME):
        shutil.copy(path, copy / path.relative_to(RUNTIME))
    for name, text in PLANTS.items():
        assert (copy / name).exists(), name
        with open(copy / name, "a", encoding="utf-8") as handle:
            handle.write("\n\n" + text)
    outside = ({name for name, _ in natural_uses(copy)} - GATE_AND_NATURAL) | ({name for name, _ in list_assignments(copy)} - {"turn_gate.py"})
    assert outside == set(PLANTS), set(PLANTS) ^ outside


# --- the moved lists are the lists of 764c9a3 ------------------------------------------------------------------------------------------------------------


def test_the_moved_lists_are_byte_identical():
    """No word was lost in the move: the three lists equal those of `git show 764c9a3:runtime/research_guard.py` (frozen as their sha256). The two patterns are built from them by the
    moved code; their text is not frozen because the order of the words of one length inside an alternation depends on the process's hash seed, and what they accept is held by the cases below."""
    lists = json.dumps([turn_gate.POSSESSIVES, turn_gate.CLITIC_POSSESSIVES, turn_gate.NOUNS], ensure_ascii=False, separators=(",", ":"))
    assert hashlib.sha256(lists.encode("utf-8")).hexdigest() == LISTS_SHA256, f"the lists changed since {FROZEN_AT}"
    assert len(turn_gate.FORMS) == 2
    assert (len(turn_gate.POSSESSIVES), len(turn_gate.CLITIC_POSSESSIVES), len(turn_gate.NOUNS)) == (19, 1, 60)


# --- taint: the closed possessive forms, in six languages, both ways (the cases of the deleted test_research_guard.py) ------------------------------------------


PERSONAL = [
    "mostra minha agenda", "liste meus emails", "liste meus e-mails de hoje", "qual o meu email", "quais sao meus arquivos", "abra minha pasta de contratos", "minha pasta",
    "meus ultimos 3 emails", "o que tem na minha agenda de amanhã",  # validate: allow english-only -- a Portuguese line under test
    "what is on my calendar", "show my e-mails", "my latest emails", "list my files", "open my folder", "my google drive", "is my inbox empty", "My Calendar",
    "que tengo en mi agenda", "mis correos de hoy", "mi ultimo correo", "mis archivos", "mi carpeta",
    "qu'y a-t-il dans mon agenda", "lis mes e-mails", "mon dossier", "ma boite mail", "mes fichiers",
    "was steht in meinem Kalender", "zeig mir meine E-Mails", "mein Ordner", "meine Dateien", "meinen Posteingang",
    "cosa c'e nella mia agenda", "leggi le mie email", "la mia cartella", "i miei file", "il mio calendario",
]
GENERAL = [
    "agenda cultural de Sao Paulo neste fim de semana", "quanto custa uma pasta de dente", "como vai estar o tempo em SP capital amanha?", "what is the calendar of public holidays in Brazil",
    "how do I send an email to the White House", "best free file hosting", "quem criou o formato de arquivo PDF", "the price of bitcoin in euros",
    "que agenda tem o presidente amanha", "cotacao do dolar hoje", "wetter in Berlin morgen", "il meteo a Roma domani", "la meteo a Paris demain", "mi dici il meteo a Roma",
    "o meu amigo trabalha na agenda cultural", "quem sao meus vizinhos famosos do bairro",
]


@pytest.mark.parametrize("line", PERSONAL)
def test_a_possessive_form_of_a_source_is_personal(line):
    assert turn_gate.personal(line) is True and turn_gate.research_allowed(line, line) is False, line


@pytest.mark.parametrize("line", GENERAL)
def test_a_general_question_or_a_bare_noun_is_allowed(line):
    assert turn_gate.personal(line) is False and turn_gate.research_allowed(line, line) is True, line


def test_vacuity_the_same_noun_with_and_without_the_possessive():
    assert turn_gate.personal("minha agenda") is True and turn_gate.personal("a agenda") is False
    assert turn_gate.personal("my emails") is True and turn_gate.personal("the emails of the project") is False


def test_any_of_the_texts_counts_and_a_non_text_is_nothing():
    assert turn_gate.personal("agenda de amanha", "mostra a minha agenda de amanha") is True
    assert turn_gate.personal(None, "", 5) is False and turn_gate.personal() is False
    assert turn_gate.research_allowed("agenda de amanha", "mostra a minha agenda de amanha") is False and turn_gate.research_allowed(None, None) is True


def test_accents_case_and_punctuation_do_not_matter():
    assert turn_gate.personal("MINHA   AGENDA!!") is True and turn_gate.personal("Mon  Dossier?") is True and turn_gate.personal("e-mail: my E-MAIL") is True


# --- taint behaviour: the research stand-in is never started by a possessive question --------------------------------------------------------------------------

TWENTY = ["mostra minha agenda", "liste meus emails", "quais sao meus arquivos de marco", "abra minha pasta de contratos", "meus ultimos 3 emails",
          "what is on my calendar tomorrow", "show my e-mails", "list my files", "open my folder", "is my inbox empty",
          "que tengo en mi agenda", "mis correos de hoy", "mis archivos", "mi carpeta de contratos",
          "qu'y a-t-il dans mon agenda", "lis mes e-mails de ce matin", "mon dossier de factures",
          "zeig mir meinen Kalender", "meine Dateien von gestern", "cosa c'e nella mia agenda"]
TEN = ["agenda cultural de Sao Paulo neste fim de semana", "the calendar of holidays", "quanto custa uma pasta de dente", "what is the calendar of public holidays in Brazil",
       "best free file hosting", "quem criou o formato de arquivo PDF", "how do I send an email to the White House", "wetter in Berlin morgen",
       "il meteo a Roma domani", "la meteo a Paris demain"]


def ask_the_terminal(world, question):
    return ops.research(world["path"], question, channel="terminal")


def taint_scenario(world):
    """The possessive questions must not start the stand-in and are answered by the one sentence that asks again; the bare nouns must reach it. Returns what the stand-in was asked."""
    cfg = ops_core.context(world["path"])["cfg"]
    again = phrases.text("IX_ASK_AGAIN", cfg)
    assert len(TWENTY) == 20 and len(TEN) == 10
    for question in TWENTY:
        got = ask_the_terminal(world, question)
        assert got["reply"] == again and got["status"] == "personal" and got["ran"] is False, question
        assert world["run"].calls == [], f"the research stand-in was started by {question!r}"
    for question in TEN:
        before = len(world["run"].calls)
        got = ask_the_terminal(world, question)
        assert got["status"] != "personal" and len(world["run"].calls) == before + 1, question
    return world["run"].calls


def test_twenty_possessive_questions_never_start_the_research_and_ten_bare_nouns_do(research):
    set_limits(research, max_per_day=50)
    calls = taint_scenario(research)
    assert len(calls) == 10


def test_vacuity_with_the_gate_patched_open_a_possessive_question_reaches_the_research(research, monkeypatch):
    set_limits(research, max_per_day=50)
    monkeypatch.setattr(turn_gate, "research_allowed", lambda *a: True)
    with pytest.raises(AssertionError):
        taint_scenario(research)
    assert len(research["run"].calls) == 1, "the first possessive question was run: the control fails where it should"


# --- private routing --------------------------------------------------------------------------------------------------------------------------------------

PRIVATE_REMINDER = "me lembra de ligar para o Zebulon amanha as 10h"      # validate: allow english-only -- the Portuguese line under test
PRIVATE_WRITE = "remind me tomorrow at 2pm to water the plants"
PRIVATE_WRITE_PT = "marca dentista quinta as 10h no google"      # validate: allow english-only -- the Portuguese line under test (a write to the person's calendar)
PLAIN = "me conta algo sobre os unicornios"      # validate: allow english-only -- the Portuguese line under test


def private_scenario(world, monkeypatch):
    """A private line whose call fails: the outage sentence, and the planning agent never sees it. Returns the lines the planning agent was given."""
    calls = []
    til.prepare(world, monkeypatch, calls, {"text": NONE})
    monkeypatch.setattr(interpreter_route, "complete", til.failing(calls))
    write_config(world["path"], language="pt-BR")
    accept(world["path"], policies=IX_PROFILES, messaging={"senders": IX_SENDERS})
    outage = phrases.text("IX_OUTAGE", ops_core.context(world["path"])["cfg"])
    assert phone(world, PRIVATE_REMINDER)["reply"] == outage
    assert til.routed(calls) == [], "the planning agent was given a private line"
    return til.routed(calls)


def test_a_private_line_with_the_daily_call_failing_gets_the_outage_and_never_the_agent(world, monkeypatch):
    assert private_scenario(world, monkeypatch) == []


def test_a_plain_line_in_the_same_state_goes_to_the_agent_so_the_scenario_is_not_vacuous(world, monkeypatch):
    private_scenario(world, monkeypatch)
    calls = []
    til.prepare(world, monkeypatch, calls, {"text": NONE})
    monkeypatch.setattr(interpreter_route, "complete", til.failing(calls))
    assert phone(world, PLAIN)["reply"] == "ROUTED" and len(til.routed(calls)) == 1


def test_vacuity_with_private_line_patched_to_false_the_private_line_reaches_the_agent(world, monkeypatch):
    monkeypatch.setattr(turn_gate, "private_line", lambda line: False)
    with pytest.raises(AssertionError):
        private_scenario(world, monkeypatch)


def no_decision_scenario(world):
    """`ops_interpret._no_decision` (no call was made or it failed) for a reminder, a write and a plain line in a pt-BR project: the first two get the outage sentence and are not marked as sent to the
    agent; the plain one goes to the agent (None, `interpreted` False)."""
    write_config(world["path"], language="pt-BR")
    accept(world["path"])
    ctx = ops_core.context(world["path"])
    outage = phrases.text("IX_OUTAGE", ctx["cfg"])
    for said in (PRIVATE_REMINDER, PRIVATE_WRITE_PT):
        extras = {"interpreted": True}
        got = ops_interpret._no_decision(ctx, said, extras)
        assert got is not None and got[0] == outage and extras["interpreted"] is True, f"the line {said!r} was given to the agent"
    extras = {"interpreted": True}
    assert ops_interpret._no_decision(ctx, PLAIN, extras) is None and extras["interpreted"] is False


def test_a_private_reminder_or_write_with_no_decision_gets_the_outage_and_a_plain_line_goes_to_the_agent(world):
    no_decision_scenario(world)


def test_vacuity_with_private_line_patched_to_false_no_decision_gives_the_private_lines_to_the_agent(world, monkeypatch):
    monkeypatch.setattr(turn_gate, "private_line", lambda line: False)
    with pytest.raises(AssertionError):
        no_decision_scenario(world)


def test_the_stored_row_of_a_reminder_and_of_a_write_is_the_neutral_word(world):
    ctx = ops_core.context(world["path"])
    assert turn_gate.private_line(PRIVATE_WRITE) is True and turn_gate.private_line("quero ver meus e-mails") is False
    assert ops_natural.stored_line(ctx, PRIVATE_WRITE) == phrases.text("NAT_PRIVATE_LINE", ctx["cfg"]) != PRIVATE_WRITE
    assert ops_natural.stored_line(ctx, "what files do you have?") == "what files do you have?"
    writing = PRIVATE_WRITE_PT
    assert turn_gate.private_kind(writing) == "write"      # S41-11: the families' claim (`natural_writes.candidate`) is gone; the gate's words say what the line is
    assert ops_natural.stored_line(ctx, writing) == phrases.text("NW_PRIVATE_LINE", ctx["cfg"]) != writing


def test_a_newly_private_write_line_is_stored_as_a_request_to_the_accounts_not_as_a_reminder(world):
    """S41-9: a line the gate reads as a write to the person's accounts that the old detector and the families did not take whole ("cancel event 2 on my calendar") is stored with the
    write's neutral word, never as "(a reminder)"; a reminder keeps its own."""
    ctx = ops_core.context(world["path"])
    line = "cancel event 2 on my calendar"
    assert turn_gate.private_kind(line) == "write"      # S41-11: the old detector and the families' claim are gone; the gate's words alone say it
    assert ops_natural.stored_line(ctx, line) == phrases.text("NW_PRIVATE_LINE", ctx["cfg"]) != phrases.text("NAT_PRIVATE_LINE", ctx["cfg"])
    assert turn_gate.private_kind(PRIVATE_REMINDER) == "reminder"
    assert ops_natural.stored_line(ctx, PRIVATE_REMINDER) == phrases.text("NAT_PRIVATE_LINE", ctx["cfg"])


def test_a_long_private_line_is_the_long_line_clarify_and_a_long_plain_line_is_routed():
    protocol = interpreter.PROTOCOL
    long_private = PRIVATE_WRITE + " " + "water " * (protocol["max_line_chars"] // 6 + 5)
    long_plain = "tell me about " + "unicorns " * (protocol["max_line_chars"] // 9 + 5)
    assert len(long_private) > protocol["max_line_chars"] and len(long_plain) > protocol["max_line_chars"]
    assert turn_gate.private_line(long_private) is True and turn_gate.private_line(long_plain) is False
    assert interpreter.precheck(long_private)["kind"] == "clarify" and interpreter.precheck(long_private)["why"] == "long-line"
    assert interpreter.precheck(long_plain) == {"kind": "route", "error": None}


def test_vacuity_with_private_line_patched_to_false_a_long_private_line_is_routed(monkeypatch):
    long_private = PRIVATE_WRITE + " " + "water " * (interpreter.PROTOCOL["max_line_chars"] // 6 + 5)
    monkeypatch.setattr(turn_gate, "private_line", lambda line: False)
    assert interpreter.precheck(long_private) == {"kind": "route", "error": None}, "the long private line would reach the agent"


# --- decision numbers from the line ----------------------------------------------------------------------------------------------------------------------

DECISIONS = ("approve", "reject", "release")
# (the operation the model chose, the parameter of its number, a verb that is only English words for the line)
VETTED_LINES = {"approve": "approve", "reject": "reject", "release": "release", "cancel": "cancel request", "stop-task": "stop task", "retry": "retry task",
                "attachment-add": "add attachment", "attachment-discard": "discard attachment", "routine-pause": "pause routine"}
MODEL_NUMBER = 3
NO_NUMBER = "{verb} please"
TWO_NUMBERS = "{verb} 3 and 4"
DATE = "{verb} 3 on 25 October"
TIME = "{verb} 3 at 15:00"
OTHER_NUMBER = "{verb} 5"
EXACT = "{verb} 3"


def test_the_table_of_vetted_operations_is_the_one_this_test_covers():
    assert set(ops_natural.VETTED) == set(VETTED_LINES), "an operation was added to or removed from VETTED: add its line here"


def test_the_number_helpers():
    assert turn_gate.the_number("reject question 7") == 7 and turn_gate.the_number("reject question #7.") == 7
    assert turn_gate.the_number("reject it") is None and turn_gate.the_number("reject 3 and 4") is None and turn_gate.the_number(None) is None and turn_gate.the_number(7) is None
    assert turn_gate.the_number("reject 25 October") is None and turn_gate.the_number("reject 3 at 15:00") is None and turn_gate.the_number("reject 25%") is None
    assert turn_gate.number_believed("cancel request 9", 9) is True
    assert turn_gate.number_believed("cancel request 9", 8) is False and turn_gate.number_believed("cancel request nine", 9) is False
    assert turn_gate.number_believed("cancel request 9 and 10", 9) is False and turn_gate.number_believed("cancel request 9", None) is False
    assert turn_gate.number_believed("cancel request 9", True) is False and turn_gate.number_believed("cancel request 1", True) is False and turn_gate.number_believed("cancel 9", "9") is False
    assert turn_gate.number_believed(None, 9) is False


class Spies:
    """Counts of every stage an operation chosen by a model could reach after the number was checked (the plan question and the operation itself)."""

    def __init__(self, rig):
        self.names = []
        monkeypatch = rig.monkeypatch
        for owner, name in ((plan_confirm, "ask"), (ops_natural, "_decision"), (ops_natural, "_typed"), (ops_natural, "_call"), (ops_natural, "_notice"), (ops_natural, "hand_over"),
                            (ops_say, "_say_command")):
            monkeypatch.setattr(owner, name, self._spy(name, getattr(owner, name)))

    def _spy(self, name, real):
        def spy(*args, **kwargs):
            self.names.append(name)
            if name == "ask":
                return "PLAN-QUESTION"
            return "STAGE-REPLY" if name != "_typed" else None
        return spy


def run_chosen(rig, spies, op, line):
    """What `ops_natural.run` says for an operation the interpreter chose with the number `MODEL_NUMBER`, on the line, as the interpreter calls it (messaging, `routed`)."""
    param = ops_natural.VETTED[op]
    extras = {}
    before = list(spies.names)
    reply = ops_natural.run(rig.world["path"], ops_core.context(rig.world["path"]), op, {param: MODEL_NUMBER}, line, "messaging", OWNER, extras, routed=True)
    return reply, spies.names[len(before):], extras


def vetting_scenario(rig):
    spies = Spies(rig)
    cfg = rig.cfg
    which, ask_id = phrases.text("NAT_WHICH_DECISION", cfg), phrases.text("NAT_ASK_ID", cfg)
    for op, verb in VETTED_LINES.items():
        wanted = which if op in DECISIONS else ask_id
        for template in (NO_NUMBER, TWO_NUMBERS, DATE, TIME, OTHER_NUMBER):
            line = template.format(verb=verb)
            reply, stages, extras = run_chosen(rig, spies, op, line)
            assert reply == wanted and stages == [] and "plan_confirm" not in extras, f"{op}: {line!r} -> {reply!r} {stages}"
        reply, stages, _ = run_chosen(rig, spies, op, EXACT.format(verb=verb))      # the one number the model named, written once: the check passes
        reaches = ["_decision"] if op in DECISIONS else ["ask"]      # D5: a call that needs the person's OK reaches its plan question; a decision (approve sends the card again, reject and release are handed over) reaches `_decision`
        assert stages[:1] == reaches and reply not in (which, ask_id), f"{op}: {stages} {reply!r}"


def test_a_model_chosen_decision_or_act_is_believed_only_for_the_one_number_the_line_writes(rig):
    vetting_scenario(rig)


def test_vacuity_with_number_believed_patched_to_true_a_line_without_the_number_gets_past_the_check(rig, monkeypatch):
    monkeypatch.setattr(turn_gate, "number_believed", lambda line, number: True)
    with pytest.raises(AssertionError):
        vetting_scenario(rig)
    spies = Spies(rig)
    reply, stages, _ = run_chosen(rig, spies, "cancel", "cancel request please")
    assert stages == ["ask"], "the act's plan was asked for a number the line never wrote"


def test_the_decision_named_by_the_model_takes_its_number_from_the_line_only(rig, monkeypatch):
    """`ops_interpret._decided`: the one number written, else NAT_WHICH_DECISION (the model gives none)."""
    calls = []
    monkeypatch.setattr(ops_natural, "run", lambda project, ctx, name, args, said, channel, sender, extras, when=None, routed=False, confirmed=False: calls.append((name, args)) or "RUN-REPLY")
    ctx = ops_core.context(rig.world["path"])
    which = phrases.text("NAT_WHICH_DECISION", rig.cfg)
    for said in ("reject 3 and 4", "reject it", "reject 25 October", "reject 3 at 15:00"):
        assert ops_interpret._decided(rig.world["path"], ctx, "reject", said, OWNER, {})[0] == which, said
    assert calls == []
    assert ops_interpret._decided(rig.world["path"], ctx, "reject", "reject 25", OWNER, {})[0] == "RUN-REPLY" and calls == [("reject", {"pending_id": 25})]
    monkeypatch.setattr(turn_gate, "the_number", lambda line: 25)
    assert ops_interpret._decided(rig.world["path"], ctx, "reject", "reject it", OWNER, {})[0] == "RUN-REPLY" and calls[-1] == ("reject", {"pending_id": 25}), "the control: the gate decides the number"
