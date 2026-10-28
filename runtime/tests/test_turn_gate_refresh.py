"""The gate's third section (S41-6, limits L52 and L53): one refresh budget for a person's line, asked by the three paths that may read a chosen source again.

A line may make the runtime read a source the person chose again, never more than once for a source in one line and only through the source operation `source_refresh`: the calendar's
miss (`event_lookup.refresh`), the phone's fresh lists (`ops_items._refresh_failed`) and the mail lookup (`mail_refresh.refresh_once`, at most one provider read for a line). Each path used to
hold a budget of its own; `turn_gate.turn` is the one budget and `turn_gate.may_refresh` the one question. Held here:

  * outside a turn each of the three paths reads nothing (fail closed), and a source is read at most once in a turn, whichever path asks first, while another source is read once too;
    a turn belongs to its thread; the outermost exit clears it, an exception included; an inner turn reuses it;
  * one mail lookup read per line: two stale mail sources looked up in one turn make one read, the next line another;
  * the entry points open the turn (`ops_say.say`, `ops_natural_writes.natural_write`, `ops_card_revise.card_revise_check` and `card_revise`, `ops_items.items`, `ops_natural_mail.resolve`), by
    behaviour on the real operations layer and by the source of each;
  * over the whole corpus of the entry replay (`reads_problems`: run once per scenario, with the other observers, by `test_entry_observed.py`), with a counting stand-in over `ops_sources.source_refresh`: no source is read twice in a line, no mail lookup twice, and no read is made outside a
    turn. The corpus holds no stale source today, so it proves that nothing in it breaks the limit; the positive reads are the scripted tests above and the guard tests of the three paths;
  * the gate is load-bearing both ways (vacuity): `may_refresh` that always says yes reads twice and the oracle fails; one that always says no leaves a stale list unread and a scripted
    stale list fails;
  * by source: only the gate creates a refresh budget, the three paths each ask `turn_gate.may_refresh` before they read, and `source_refresh` is reached from a person's line by those three paths and
    by nothing else (the typed command, the routine's `ingest` and the export are not a line's refresh and never ask the gate).

Offline: the provider is a stand-in that counts its calls (or the real stand-in providers of the existing worlds), no model, no secret; every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_turn_gate_refresh.py
"""
from __future__ import annotations

import ast
import threading
from pathlib import Path

import pytest

import standin_tree as st
from test_items_fresh import NEW, add_message, ask, clock, mail_reads, project, snaps, with_inbox, world  # noqa: F401  (the calendar world, its snapshots and the stale phone list)
from test_ops_natural import world as line_world  # noqa: F401  (the real-operations world of the interpreter)
from test_ops_natural_writes import READER

turn_gate = st.load("turn_gate")
event_lookup = st.load("event_lookup")
mail_refresh = st.load("mail_refresh")
ops = st.load("ops")
ops_core = st.load("ops_core")
ops_card_revise = st.load("ops_card_revise")
ops_items = st.load("ops_items")
ops_natural_calendar = st.load("ops_natural_calendar")
ops_natural_mail = st.load("ops_natural_mail")
ops_natural_writes = st.load("ops_natural_writes")
ops_say = st.load("ops_say")
ops_sources = st.load("ops_sources")
ops_turn = st.load("ops_turn")
sources = st.load("sources")

RUNTIME = Path(__file__).resolve().parents[1]
CTX = {"cfg": {"project": "demo"}}


class Reads:
    """The reads a line makes, seen at the one provider read: every call of `ops_sources.source_refresh` (the source id; whether a turn was open on the calling thread), and the number of
    mail lookups the gate granted. `through` calls the real operation after counting (a world with providers); without it the stand-in answers at once."""

    def __init__(self, monkeypatch, through=False):
        self.sources, self.outside, self.mail_grants = [], [], 0
        real = ops_sources.source_refresh

        def counted(project, source_id, *args, **kwargs):
            self.sources.append(source_id)
            if getattr(turn_gate._TURN, "budget", None) is None:
                self.outside.append(source_id)
            return real(project, source_id, *args, **kwargs) if through else {"refreshed": True}
        monkeypatch.setattr(ops_sources, "source_refresh", counted)
        asked = turn_gate.may_refresh

        def watching(source_id, purpose):
            granted = asked(source_id, purpose)
            if granted and purpose == "mail-lookup":
                self.mail_grants += 1
            return granted
        monkeypatch.setattr(turn_gate, "may_refresh", watching)

    def twice(self):
        return sorted({s for s in self.sources if self.sources.count(s) > 1})


@pytest.fixture
def reads(monkeypatch):
    """The three paths over a counting stand-in provider, with no world: two calendar sources, no stored snapshot (so a list is stale), a mail source that is stale until it has been read."""
    seen = Reads(monkeypatch)
    monkeypatch.setattr(ops_natural_calendar, "calendar_sources", lambda ctx: [{"id": "agenda"}, {"id": "work-agenda"}])
    monkeypatch.setattr(sources, "_stored", lambda ctx, name, *args: None if name == "source_latest" else {"type": "mail"})
    monkeypatch.setattr(ops_items, "_CHECKED", {})
    monkeypatch.setattr(ops_items, "_DIRTY", set())
    monkeypatch.setattr(mail_refresh.item_refs, "may_read", lambda ctx, channel, sender: True)
    monkeypatch.setattr(mail_refresh, "_still_refused", lambda ctx, source_id, channel, sender: source_id not in seen.sources)
    mail_refresh.forget()
    yield seen
    mail_refresh.forget()


def calendar_miss():
    event_lookup.refresh("demo", CTX)


def stale_list(source_id):
    return ops_items._refresh_failed("demo", CTX, source_id)


def mail_lookup(source_id):
    return mail_refresh.refresh_once(CTX, source_id, "messaging", "telegram:5151")


# --- the budget ---------------------------------------------------------------------------------------------------------------------------------------


def test_no_refresh_outside_a_turn(reads):
    calendar_miss()
    assert stale_list("agenda") is False
    assert mail_lookup("inbox") == "spent"
    assert reads.sources == [], "the three paths read nothing when no turn is open"
    assert getattr(turn_gate._TURN, "budget", None) is None
    assert turn_gate.may_refresh("agenda", "calendar-miss") is False and turn_gate.may_refresh("inbox", "mail-lookup") is False


def test_a_source_is_read_at_most_once_in_a_line(reads):
    with turn_gate.turn():
        calendar_miss()
        calendar_miss()
        assert stale_list("agenda") is False and stale_list("agenda") is False
    assert reads.sources == ["agenda", "work-agenda"], "each calendar source once, whichever path and however often it asks"
    with turn_gate.turn():
        assert stale_list("agenda") is False and stale_list("inbox") is False
        assert mail_lookup("inbox") == "spent", "the list already read this source: not again for the mail lookup either"
        assert stale_list("work") is False
    assert reads.sources == ["agenda", "work-agenda", "agenda", "inbox", "work"], "a new line may read again; inside it two different sources are read once each"
    assert reads.twice() == ["agenda"], "(the same source in two lines is two reads, as it should)"


def test_one_mail_lookup_read_per_line(reads):
    with turn_gate.turn():
        assert mail_lookup("inbox") == "refreshed"
        assert mail_lookup("work") == "spent", "a second stale mail source in the same line is not read"
        assert mail_lookup("inbox") == "spent"
    assert reads.sources == ["inbox"] and reads.mail_grants == 1
    with turn_gate.turn():
        assert mail_lookup("work") == "refreshed"
    assert reads.sources == ["inbox", "work"], "the next line has a budget of its own"


def test_the_mail_lookup_budget_is_one_per_line_but_a_list_of_another_source_is_not_taken_by_it(reads):
    with turn_gate.turn():
        assert mail_lookup("inbox") == "refreshed"
        assert stale_list("work") is False
        calendar_miss()
    assert reads.sources == ["inbox", "work", "agenda", "work-agenda"], "the mail rule is about the mail lookup: lists and the calendar keep their own sources"


def test_an_unknown_purpose_an_empty_source_and_a_non_text_source_are_refused(reads):
    with turn_gate.turn():
        for source_id in ("", None, 5, ["a"]):
            assert turn_gate.may_refresh(source_id, "list-fresh") is False, repr(source_id)
        for purpose in ("", None, "refresh", "mail", "Calendar-Miss"):
            assert turn_gate.may_refresh("agenda", purpose) is False, repr(purpose)
        assert turn_gate.may_refresh("agenda", "list-fresh") is True, "the control: a known purpose and a source are granted"


def test_the_outermost_exit_clears_the_budget_an_exception_included_and_an_inner_turn_reuses_it(reads):
    with pytest.raises(RuntimeError):
        with turn_gate.turn():
            assert turn_gate.may_refresh("agenda", "list-fresh") is True
            raise RuntimeError("the line failed")
    assert getattr(turn_gate._TURN, "budget", None) is None, "nothing is left open on the thread after a line that raised"
    with turn_gate.turn():
        assert turn_gate.may_refresh("agenda", "list-fresh") is True, "the next line can refresh the same source"
        with turn_gate.turn():
            assert turn_gate.may_refresh("agenda", "calendar-miss") is False, "an inner turn is the same line"
            assert turn_gate.may_refresh("work-agenda", "calendar-miss") is True
        with pytest.raises(RuntimeError):
            with turn_gate.turn():
                raise RuntimeError("an inner entry failed")
        assert turn_gate._TURN.budget is not None and turn_gate.may_refresh("work-agenda", "list-fresh") is False, "the inner exit did not clear the outer budget"
    assert getattr(turn_gate._TURN, "budget", None) is None


def test_a_budget_belongs_to_its_thread(reads):
    inside, answers = threading.Event(), {}
    done = threading.Event()

    def other():
        answers["no turn"] = turn_gate.may_refresh("agenda", "list-fresh")
        inside.set()
        done.wait(5)
        with turn_gate.turn():
            answers["own turn"] = turn_gate.may_refresh("agenda", "list-fresh")
    thread = threading.Thread(target=other)
    with turn_gate.turn():
        assert turn_gate.may_refresh("agenda", "list-fresh") is True
        thread.start()
        assert inside.wait(5)
        assert answers["no turn"] is False, "the budget of this thread's line is not another thread's turn"
        done.set()
        thread.join(5)
        assert not thread.is_alive()
    assert answers["own turn"] is True, "two lines at once, each with a budget of its own: the same source may be read once by each"


def test_a_cooling_source_costs_the_line_nothing(reads):
    """`mail_refresh.refresh_once` asks `_cooling(key)` BEFORE the gate: a source that failed lately answers "spent" without spending the one mail-lookup grant of the line, so a second stale mail
    source of the same line is still read. With the gate asked first, the cooling source would take the grant and `work` would never be read."""
    with turn_gate.turn():
        mail_refresh._FAILED[("demo", "inbox")] = mail_refresh.MONOTONIC()
        assert mail_lookup("inbox") == "spent"
        assert reads.mail_grants == 0 and reads.sources == [], "the cooling source asked no grant and read nothing"
        assert mail_lookup("work") == "refreshed", "a cooling source left the mail-lookup budget unspent"
    assert reads.sources == ["work"] and reads.mail_grants == 1


def test_a_failed_list_read_keeps_its_old_note_on_a_second_list_of_the_line(reads, monkeypatch):
    """The gate refuses the second read of a source in a line; a read of this line that FAILED leaves the snapshot old, so the second list still says so (`_refresh_failed` returns True)."""
    def failing(project, source_id, *args, **kwargs):
        reads.sources.append(source_id)
        raise RuntimeError("provider down")
    monkeypatch.setattr(ops_sources, "source_refresh", failing)
    with turn_gate.turn():
        assert stale_list("agenda") is True, "the first list of the line: the read failed, the list is marked old"
        assert stale_list("agenda") is True, "the second list of the same line: no second read, and the same note"
        assert stale_list("work") is True and stale_list("work") is True, "each source on its own"
    assert reads.sources == ["agenda", "work"], "one read for each source"
    assert getattr(turn_gate._TURN, "budget", None) is None
    assert turn_gate.failed_in_turn("agenda") is False, "outside a turn nothing is remembered"
    turn_gate.mark_failed("agenda")
    assert turn_gate.failed_in_turn("agenda") is False, "marking outside a turn is a no-op"


def test_a_read_that_worked_or_was_never_made_is_not_old_and_a_failure_does_not_pass_to_the_next_line(reads, monkeypatch):
    with turn_gate.turn():
        assert stale_list("agenda") is False, "the read worked"
        assert stale_list("agenda") is False, "the second list of the line: nothing was needed, as before"
        assert turn_gate.failed_in_turn("agenda") is False
    real = ops_sources.source_refresh

    def failing(project, source_id, *args, **kwargs):
        raise RuntimeError("provider down")
    monkeypatch.setattr(ops_sources, "source_refresh", failing)
    with turn_gate.turn():
        assert stale_list("work") is True
    monkeypatch.setattr(ops_sources, "source_refresh", real)
    with turn_gate.turn():
        assert turn_gate.failed_in_turn("work") is False, "the next line starts clean"
        assert stale_list("work") is False, "and its read works"


# --- the entry points open the turn ------------------------------------------------------------------------------------------------------------------


def open_inside(spy):
    return lambda *args, **kwargs: spy.append(getattr(turn_gate._TURN, "budget", None) is not None)


def test_a_stale_phone_list_reads_a_source_once_in_a_line_and_the_next_line_reads_it_again(world, snaps, clock):  # noqa: F811
    with_inbox(world, snaps)
    add_message(snaps)
    snaps.later(minutes=11)
    with turn_gate.turn():      # one line that lists twice (the entry reuses the open turn): the second list finds the source spent and shows the snapshot as it is
        first = ops_items.items(world["path"], channel="messaging", sender=READER)
        assert len(mail_reads(snaps)) == 1 and "old" not in first["sources"][0]
        snaps.later(minutes=11)
        ops_items.items(world["path"], channel="messaging", sender=READER)
        assert len(mail_reads(snaps)) == 1, "the line has read the source: the second list reads nothing"
    ops_items.items(world["path"], channel="messaging", sender=READER)
    assert len(mail_reads(snaps)) == 2, "the next line has a budget of its own and the snapshot is stale again"


def test_the_entry_points_open_the_turn_on_the_real_operations_layer(world, snaps, clock, monkeypatch):  # noqa: F811
    project(world)
    path, core_ctx = world["path"], ops_core.context(world["path"])
    seen = []
    inside = open_inside(seen)
    real_catalog = sources.list_catalog
    with monkeypatch.context() as m:      # items: the catalog is read inside the turn
        m.setattr(ops_items.sources, "list_catalog", lambda *args, **kwargs: (inside(), real_catalog(*args, **kwargs))[1])
        ops_items.items(path, channel="messaging", sender=READER)
    assert seen == [True], "ops_items.items"
    seen.clear()
    with monkeypatch.context() as m:      # natural_write: the line is tried as a write form inside the turn
        m.setattr(ops_natural_writes, "open_line", lambda *args, **kwargs: inside())
        ops_natural_writes.natural_write(path, "a plain line", channel="messaging", sender=READER)
    assert seen == [True], "ops_natural_writes.natural_write"
    seen.clear()
    with monkeypatch.context() as m:      # the two entries of a revision: the card is looked at inside the turn
        m.setattr(ops_card_revise, "_taken", lambda *args, **kwargs: inside())
        assert ops_card_revise.card_revise_check(path, 1, "x" * 64, "make it shorter", "messaging", READER) is None
        assert ops_card_revise.card_revise(path, 1, "x" * 64, "make it shorter", "messaging", READER) == {"pass": True}
    assert seen == [True, True], "ops_card_revise.card_revise_check and card_revise"
    seen.clear()
    with monkeypatch.context() as m:      # the mail family's resolve: used directly it is an entry of its own, and inside a line it is the line's turn
        m.setattr(ops_natural_mail, "_compose_args", lambda *args, **kwargs: (inside(), {"args": {}})[1])
        ops_natural_mail.resolve(core_ctx, "mail-send", {}, "messaging", READER)
        assert seen == [True] and getattr(turn_gate._TURN, "budget", None) is None, "ops_natural_mail.resolve opens its own turn and clears it"
        with turn_gate.turn():
            outer = turn_gate._TURN.budget
            ops_natural_mail.resolve(core_ctx, "mail-send", {}, "messaging", READER)
            assert turn_gate._TURN.budget is outer, "inside a line it is the same turn"


def test_say_holds_the_turn_from_the_hooks_to_the_stored_reply(line_world, monkeypatch):  # noqa: F811
    seen = []
    hook = event_lookup.begin_turn
    monkeypatch.setattr(event_lookup, "begin_turn", lambda *args, **kwargs: (seen.append(getattr(turn_gate._TURN, "budget", None) is not None), hook(*args, **kwargs))[1])
    monkeypatch.setattr(ops_turn, "dispatch", lambda *args, **kwargs: (seen.append(getattr(turn_gate._TURN, "budget", None) is not None), ("done", None, None, False, None, None))[1])
    out = ops.say(line_world["path"], "a plain line of the person")
    assert out["reply"] == "done" and seen == [True, True], "the begin-turn hook and the dispatch both run inside the turn"
    assert getattr(turn_gate._TURN, "budget", None) is None, "the turn is closed when the reply is stored"

    def failing(*args, **kwargs):
        raise RuntimeError("a row failed")
    monkeypatch.setattr(ops_turn, "dispatch", failing)
    with pytest.raises(RuntimeError):
        ops.say(line_world["path"], "another line")
    assert getattr(turn_gate._TURN, "budget", None) is None, "a line that raised leaves no budget open: the next line can refresh"


def source_of(name):
    return (RUNTIME / name).read_text(encoding="utf-8")


def function_of(name, function):
    tree = ast.parse(source_of(name))
    found = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == function]
    assert len(found) == 1, (name, function)
    return found[0]


def opens_a_turn(node):
    """Whether the function holds a `with <something>.turn():` (the gate's, or the operations dispatcher's, which asks the gate)."""
    for item in (i for n in ast.walk(node) if isinstance(n, ast.With) for i in n.items):
        call = item.context_expr
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr == "turn" and isinstance(call.func.value, ast.Name) and call.func.value.id in ("turn_gate", "turns"):
            return True
    return False


ENTRIES = (("ops_say.py", "say"), ("ops_natural_writes.py", "natural_write"), ("ops_card_revise.py", "card_revise_check"), ("ops_card_revise.py", "card_revise"), ("ops_items.py", "items"),
           ("ops_natural_mail.py", "resolve"))


@pytest.mark.parametrize("name,function", ENTRIES)
def test_each_entry_point_opens_the_turn(name, function):
    assert opens_a_turn(function_of(name, function)), f"{name} {function} holds `with turn_gate.turn():`"


def test_the_turn_is_opened_by_the_entries_and_by_no_helper_that_a_line_does_not_end_in():
    """The opener of `say` is the dispatcher's (`ops_turn.turn`, which is `turn_gate.turn`); `mail_refresh` has no turn of its own any more."""
    assert not hasattr(mail_refresh, "turn") and not hasattr(mail_refresh, "_LOCAL"), "the mail lookup's own budget is gone"
    assert ops_turn.turn is not None and "turn_gate" in source_of("ops_turn.py")


# --- the corpus -------------------------------------------------------------------------------------------------------------------------------------


def reads_problems(results) -> list:
    """Run once per scenario with the other observers by `test_entry_observed.py`: `results` is `[(scenario, the `Reads` a hook built with `Reads(mp, through=True)` saw)]`. Every scenario of the entry
    replay, through the whole entry (the real bridge, the operations layer and the stand-ins), with a counting stand-in over the one provider read: no source is read twice in a line, no line makes two
    mail lookups, and no read is made with no turn open. (The outcome itself is the replay's; this is the budget's.)"""
    bad = []
    for scenario, reads in results:
        if reads.twice() or reads.mail_grants > 1 or reads.outside:
            bad.append(f"{scenario['id']}: reads {reads.sources}, mail lookups {reads.mail_grants}, outside a turn {reads.outside}")
    return bad


def test_the_counting_stand_in_sees_a_read_and_a_read_outside_a_turn(monkeypatch):
    """The control of the corpus test: the stand-in counts a read of the calendar made in a turn, and a planted read with no turn is reported as outside."""
    seen = Reads(monkeypatch)
    monkeypatch.setattr(ops_natural_calendar, "calendar_sources", lambda ctx: [{"id": "agenda"}])
    with turn_gate.turn():
        event_lookup.refresh("demo", CTX)
    assert seen.sources == ["agenda"] and seen.outside == [] and seen.twice() == []
    ops_sources.source_refresh("demo", "agenda")
    assert seen.sources == ["agenda", "agenda"] and seen.outside == ["agenda"] and seen.twice() == ["agenda"], "a planted read outside a turn, and a second read of a source, are both seen"


# --- vacuity: the gate is load-bearing both ways ---------------------------------------------------------------------------------------------------


def test_vacuity_a_gate_that_always_says_yes_reads_twice_and_the_oracle_fails(reads, monkeypatch):
    monkeypatch.setattr(turn_gate, "may_refresh", lambda source_id, purpose: True)
    with turn_gate.turn():
        calendar_miss()
        calendar_miss()
        stale_list("agenda")
    assert reads.twice() == ["agenda", "work-agenda"], "the probe sees it: with no budget the same source is read three times"
    with pytest.raises(AssertionError):
        assert reads.sources == ["agenda", "work-agenda"]      # the oracle of test_a_source_is_read_at_most_once_in_a_line


def test_vacuity_a_gate_that_always_says_no_leaves_a_stale_list_unread_and_the_stale_list_scenario_fails(world, snaps, clock, monkeypatch):  # noqa: F811
    def stale_list_scenario():
        with_inbox(world, snaps)
        add_message(snaps)
        snaps.later(minutes=11)
        reply = ask(world, "list my emails")
        assert len(mail_reads(snaps)) == 1 and NEW in reply, "the scenario of test_items_fresh.py: a stale list is read once and holds the new message"
    monkeypatch.setattr(turn_gate, "may_refresh", lambda source_id, purpose: False)
    with pytest.raises(AssertionError):
        stale_list_scenario()      # the gate that never allows a read leaves the list as the snapshot was: the scenario fails
    assert mail_reads(snaps) == [], "no read was made"


# --- by source ----------------------------------------------------------------------------------------------------------------------------------------
# The scans below read the SOURCE TEXT of a module (a function of the text, so that the controls can plant a bypass in a copy of a real module and require it to be flagged).

BUDGET_MODULES = ("threading", "contextvars", "_thread")
BUDGET_NAMES = ("local", "ContextVar")
PROVIDER_NAMES = {"snapshot_refresh", "snapshot_new", "source_mail", "source_calendar", "_snapshot"}      # the source operations' own way to the provider (`ops_sources._snapshot` and `sources_mail.snapshot_*`)
PROVIDER_HOMES = ("ops_sources.py", "sources_mail.py")
SKIPS = (ast.Return, ast.Continue, ast.Raise)


def calls_in(node, attr):
    return sorted(n.lineno for n in ast.walk(node) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == attr)


def thread_locals(text):
    """The lines that make a thread-local or a context variable, by name: `threading.local()`, `ContextVar(...)`, and `local()` after `from threading import local` (aliases included)."""
    tree = ast.parse(text)
    modules, names = {}, {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update({a.asname or a.name: a.name for a in node.names if a.name in BUDGET_MODULES})
        elif isinstance(node, ast.ImportFrom) and node.module in BUDGET_MODULES:
            names.update({a.asname or a.name: a.name for a in node.names if a.name in BUDGET_NAMES})
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in BUDGET_NAMES and isinstance(func.value, ast.Name) and func.value.id in modules:
            found.append(node.lineno)
        elif isinstance(func, ast.Name) and func.id in names:
            found.append(node.lineno)
    return found


class Names(ast.NodeVisitor):
    """Where any of the names `wanted` stands in a module (a call, an attribute, an import, a definition or a string): the function it is in, or <module>, <import>, <table>."""

    def __init__(self, module, wanted):
        self.module, self.wanted, self.stack, self.found = module, set(wanted), [], []

    def here(self):
        return self.stack[-1] if self.stack else "<module>"

    def visit_FunctionDef(self, node):
        if node.name in self.wanted:
            self.found.append((self.module, self.here()))
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    def visit_Attribute(self, node):
        if node.attr in self.wanted:
            self.found.append((self.module, self.here()))
        self.generic_visit(node)

    def visit_Name(self, node):
        if node.id in self.wanted:
            self.found.append((self.module, self.here()))

    def visit_ImportFrom(self, node):
        if any(a.name in self.wanted for a in node.names):
            self.found.append((self.module, "<import>"))

    def visit_Constant(self, node):
        if isinstance(node.value, str) and node.value in self.wanted:
            self.found.append((self.module, "<table>"))


def names_in(text, module, wanted):
    visitor = Names(module, wanted)
    visitor.visit(ast.parse(text))
    return set(visitor.found)


def reading_calls(node):
    return sorted(n.lineno for n in ast.walk(node) if isinstance(n, ast.Call) and ((isinstance(n.func, ast.Attribute) and n.func.attr == "source_refresh")
                                                                                   or (isinstance(n.func, ast.Name) and n.func.id == "refresh_one")))


def guard_problems(text, function):
    """What is wrong with the way `function` of the module text asks the gate before it reads: `turn_gate.may_refresh` must be the test (or a part of the boolean test) of an `if` whose body
    ends in a return, a continue or a raise, that stands before every read, and every call of it must be inside such a test, negated (`not`: the skip is taken when the gate refuses): a call whose
    answer is ignored, or an if that skips when the gate allows, guards nothing."""
    tree = ast.parse(text)
    found = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == function]
    if len(found) != 1:
        return [f"{function} is not one function"]
    node = found[0]
    asks = [n for n in ast.walk(node) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "may_refresh"]
    reads = reading_calls(node)
    problems = []
    if not asks:
        problems.append("it never asks the gate")
    if not reads:
        problems.append("no read found: the scan does not see the path")
    if any(not (isinstance(c.func.value, ast.Name) and c.func.value.id == "turn_gate") for c in asks):
        problems.append("it asks through a name other than turn_gate")
    guards = [n for n in ast.walk(node) if isinstance(n, ast.If) and n.body and isinstance(n.body[-1], SKIPS)
              and any(isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute) and c.func.attr == "may_refresh" for c in ast.walk(n.test))]
    guarded = {id(c) for g in guards for c in ast.walk(g.test)}
    refused = {id(u.operand) for g in guards for u in ast.walk(g.test) if isinstance(u, ast.UnaryOp) and isinstance(u.op, ast.Not)}      # `not turn_gate.may_refresh(...)`: skip when refused
    for call in asks:
        if id(call) not in guarded:
            problems.append(f"line {call.lineno}: the gate's answer is ignored (it is not the test of an if that skips the read)")
        elif id(call) not in refused:
            problems.append(f"line {call.lineno}: the skip is taken when the gate allows, not when it refuses (the answer is not negated)")
    for line in reads:
        if not any(g.end_lineno < line for g in guards):
            problems.append(f"line {line}: a read with no gate-guarded skip before it")
    return problems


def test_only_the_gate_creates_a_refresh_budget():
    held = {}
    for path in sorted(RUNTIME.glob("*.py")):
        lines = thread_locals(path.read_text(encoding="utf-8"))
        if lines:
            held[path.name] = lines
    # phrases.py (TT-2) holds the tag of the scope the fixed sentences are said in for one person: a language, not a refresh budget
    assert set(held) == {"messaging_bridge.py", "ops_actor.py", "ops_core.py", "phrases.py", "turn_gate.py"}, f"a new thread-local or context variable needs a reading: is it a refresh budget? {held}"
    for name in ("event_lookup.py", "ops_items.py", "mail_refresh.py", "ops_natural_mail.py"):
        assert name not in held and "_LOCAL" not in source_of(name), f"{name} holds no budget of its own"


PATHS = (("event_lookup.py", "refresh"), ("ops_items.py", "_refresh_failed"), ("mail_refresh.py", "refresh_once"))


@pytest.mark.parametrize("name,function", PATHS)
def test_each_path_asks_the_gate_before_it_reads_and_the_answer_guards_the_read(name, function):
    assert guard_problems(source_of(name), function) == []


def test_the_mail_lookup_asks_the_gate_after_its_cooldown_so_a_cooling_source_costs_the_line_nothing():
    """The order of `_cooling(key) or not turn_gate.may_refresh(...)` is load-bearing (see test_a_cooling_source_costs_the_line_nothing): the cooldown comes first."""
    node = function_of("mail_refresh.py", "refresh_once")
    tests = [n.test for n in ast.walk(node) if isinstance(n, ast.If) and any(isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute) and c.func.attr == "may_refresh" for c in ast.walk(n.test))]
    assert len(tests) == 1 and isinstance(tests[0], ast.BoolOp) and isinstance(tests[0].op, ast.Or)
    first, second = tests[0].values
    assert isinstance(first, ast.Call) and ast.unparse(first.func) == "_cooling", "the cooldown is asked first"
    assert "may_refresh" in ast.unparse(second)


def test_the_phone_only_condition_of_the_fresh_lists_stays_before_the_gate():
    node = function_of("ops_items.py", "items")
    called = [n for n in ast.walk(node) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_refresh_failed"]
    assert len(called) == 1
    line = source_of("ops_items.py").splitlines()[called[0].lineno - 1]
    assert "phone and _refresh_failed(" in line, "S15: a list for the terminal, the conversation or the page reads the provider never (the phone condition is asked first)"


def test_the_provider_read_is_reached_from_a_persons_line_by_these_three_paths_and_by_nothing_else():
    """Probe 1 of the review: every place the runtime's code names `source_refresh`, with the function it stands in. The typed operation (the table's row and its export), the routine's `ingest`
    step and the definition itself are not a line's refresh: none of them asks the gate."""
    found = set()
    for path in sorted(RUNTIME.glob("*.py")):
        found |= names_in(path.read_text(encoding="utf-8"), path.name, {"source_refresh"})
    assert found == {("event_lookup.py", "refresh"), ("mail_refresh.py", "refresh_once"), ("ops.py", "<import>"), ("operations.py", "<table>"), ("ops_items.py", "_refresh_failed"),
                     ("ops_sources.py", "<module>"), ("step_ingest.py", "_ingest")}, sorted(found)
    for name in ("ops_sources.py", "operations.py", "step_ingest.py"):
        assert "turn_gate" not in source_of(name), f"{name} is not a line's refresh and never asks the gate"


OTHER_NAMES_OF_THE_SAME_WORDS = {("operations.py", "<table>"),      # the rows `source-mail` and `source-calendar` of the table of operations (typed, terminal and page)
                                 ("ops.py", "<import>"),      # the export of the two typed operations
                                 ("ops.py", "<module>"), ("ops.py", "poll"), ("ops_runs.py", "_pass")}      # `ops._snapshot`: the dispatcher's own snapshot of the keys, a different function of the same name


def test_the_ways_to_the_provider_are_named_only_in_the_source_operations():
    """The reads a line may make are the three paths above through `source_refresh`. The source operations' own ways to the provider (`snapshot_refresh`, `snapshot_new`, `source_mail`,
    `source_calendar`, `ops_sources._snapshot`) are named in `ops_sources.py` and `sources_mail.py` and nowhere else but the typed operations' table and export (and an unrelated `_snapshot`)."""
    found = set()
    for path in sorted(RUNTIME.glob("*.py")):
        if path.name not in PROVIDER_HOMES:
            found |= names_in(path.read_text(encoding="utf-8"), path.name, PROVIDER_NAMES)
    assert found == OTHER_NAMES_OF_THE_SAME_WORDS, sorted(found ^ OTHER_NAMES_OF_THE_SAME_WORDS)


# --- the controls of the scans: a bypass planted in a copy of a real module is flagged ------------------------------------------------------------------


def planted(name, old, new):
    text = source_of(name)
    assert old in text, (name, old)
    return text.replace(old, new, 1)


def test_the_scans_flag_a_budget_made_with_a_bare_local_a_context_variable_or_an_alias():
    assert thread_locals(source_of("ops_items.py")) == []
    assert thread_locals(source_of("ops_items.py") + "\nfrom threading import local\n_BUDGET = local()\n"), "`from threading import local` then `local()`"
    assert thread_locals(source_of("ops_items.py") + "\nfrom threading import local as tl\n_BUDGET = tl()\n"), "an alias"
    assert thread_locals(source_of("ops_items.py") + "\nimport threading as t\n_BUDGET = t.local()\n"), "a module alias"
    assert thread_locals(source_of("ops_items.py") + "\nfrom contextvars import ContextVar\n_BUDGET = ContextVar('budget')\n"), "a context variable"
    assert thread_locals(source_of("turn_gate.py")) != [], "the control: the gate's own budget is seen"
    assert thread_locals(source_of("reminders.py")) == [], "a parameter that is called `local` is not a thread-local"


def test_the_scans_flag_a_planted_way_to_the_provider():
    bypass = '\n\ndef _planted(project):\n    return importlib.import_module("sources_mail").snapshot_refresh(project, "inbox")\n'
    for name in ("ops_items.py", "mail_refresh.py", "event_lookup.py"):
        found = names_in(source_of(name) + bypass, name, PROVIDER_NAMES)
        assert (name, "_planted") in found, name
        assert names_in(source_of(name), name, PROVIDER_NAMES) == set(), f"the control: {name} as it is names none"
    assert (("ops_items.py", "_planted") in names_in(source_of("ops_items.py") + bypass.replace("snapshot_refresh", "source_mail"), "ops_items.py", PROVIDER_NAMES))
    assert (("ops_items.py", "_planted") in names_in(source_of("ops_items.py") + "\n\ndef _planted(ctx):\n    return ops_sources._snapshot(ctx)\n", "ops_items.py", PROVIDER_NAMES))


def test_the_scan_flags_a_gate_that_is_called_and_ignored_one_that_guards_nothing_and_a_read_before_it():
    clean = {"event_lookup.py": "refresh", "ops_items.py": "_refresh_failed", "mail_refresh.py": "refresh_once"}
    for name, function in clean.items():
        assert guard_problems(source_of(name), function) == [], f"the control: {name} as it is"
    ignored = planted("event_lookup.py", '        if not turn_gate.may_refresh(source["id"], "calendar-miss"):\n            continue\n', '        turn_gate.may_refresh(source["id"], "calendar-miss")\n')
    assert any("ignored" in p for p in guard_problems(ignored, "refresh")), "the gate is called and its answer ignored"
    passing = planted("ops_items.py", 'if not turn_gate.may_refresh(source_id, "list-fresh"):', 'if turn_gate.may_refresh(source_id, "list-fresh"):')
    assert guard_problems(passing, "_refresh_failed") != [], "an if whose body does not skip the read (the answer is inverted)"
    after = planted("mail_refresh.py", '    if _cooling(key) or not turn_gate.may_refresh(source_id, "mail-lookup"):', '    if _cooling(key):')
    assert guard_problems(after, "refresh_once") != [], "no ask at all"
    late = planted("event_lookup.py", '        if not turn_gate.may_refresh(source["id"], "calendar-miss"):\n            continue\n        try:\n            refresh_one(project, source["id"])',
                   '        try:\n            refresh_one(project, source["id"])')
    assert guard_problems(late, "refresh") != [], "a read with no ask"
    other = planted("ops_items.py", 'turn_gate.may_refresh(source_id, "list-fresh")', 'gate.may_refresh(source_id, "list-fresh")')
    assert any("other than turn_gate" in p for p in guard_problems(other, "_refresh_failed"))


def test_a_typed_source_refresh_outside_a_turn_still_works(world, snaps, clock):  # noqa: F811
    """Probe 3: the terminal's and the page's `source-refresh` is not a line's refresh; with no turn open it reads, as it always did."""
    with_inbox(world, snaps)
    assert getattr(turn_gate._TURN, "budget", None) is None
    out = ops_sources.source_refresh(world["path"], "inbox")
    assert out["refreshed"] in (True, False) and len(mail_reads(snaps)) == 1, "the typed refresh read the provider with no turn"
