"""The registry (package CB-0, PLAN-BRAIN section 4.2): the `natural` record on every row of `operations.OPERATIONS`, the two views `natural.CLASSES` and `natural.NATURAL`
built from the records, the catalog version `operations.LINE_CATALOG`, the catalog generated from the rows and the reader `runtime/registry.py`.

The key invariant: with `LINE_CATALOG == 1` nothing a line can reach changes. The views equal, hash for hash, the two literals they replaced (pinned at commit ed6ea6b in
scripts/tests/pinned_hashes.json), the served catalog is byte for byte the one the newest enabling entry pins, so the interpreter stays on and the entry replay is identical.

Every invariant is checked against the test's OWN literals (the closed words, the sets of operations, the origins of a few slots), never against the code under test; the
pins are read from scripts/tests/pinned_hashes.json. Each family of checks has a vacuity case: the same check, run on a copy of the rows with one planted fault, must see it.
Offline, no model, no network, no provider. Every name that is planted is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_registry_rows.py
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import standin_tree as st
from expected_kit import extend

# Every pinned hash of the test suite is in scripts/tests/pinned_hashes.json, with what it hashes and why it is pinned.
PINNED_HASHES = json.loads((Path(__file__).resolve().parents[2] / "scripts" / "tests" / "pinned_hashes.json").read_text(encoding="utf-8"))["pins"]

REPO = Path(__file__).resolve().parents[2]
RUNTIME = REPO / "runtime"
natural = st.load("natural")
operations = st.load("operations")
registry = st.load("registry")
catalog = st.load("interpreter_catalog")
interpreter = st.load("interpreter")
interpreter_enable = st.load("interpreter_enable")
plan_confirm = st.load("plan_confirm")
turn_gate = st.load("turn_gate")

# The test's own literals.
KEYS = {"class", "since", "order", "privacy", "cost", "what", "about", "slots"}
SLOT_KEYS = {"kind", "param", "since"}
CLASS_WORDS = {"R", "N", "W", "D", "E", "G", "work"}
KIND_WORDS = {"int", "ints", "word", "span", "when"}
PRIVACY_WORDS = {"own", "account", "off-host"}
COST_WORDS = {"none", "provider", "model"}
OFF_HOST = extend("registry_rows.OFF_HOST", {"research", "ask"})
EFFECTS = extend("registry_rows.EFFECTS", {"event-create", "event-change", "event-cancel", "mail-send", "mail-reply", "mail-draft", "mail-archive", "mail-move", "mail-mark", "mail-trash",
           "file-create", "file-replace", "file-save", "file-trash"})
MODEL_ROWS = extend("registry_rows.MODEL_ROWS", {"route", "route-queued", "run-next", "run-task", "contained-run", "dispatch", "say", "ask", "research"})      # the rows whose `model` column is not False
ALWAYS_NOW = ("research", "ask")
SERVED_NOW, REFUSED_NOW = 65, 21
FINDER = ("target", "day")
# The words a text of a confusable row holds to separate it from what it is not (the groups the spec of CB-0 names).
SEPARATES = extend("registry_rows.SEPARATES", {"status": "to-do list", "progress": "to-do list", "pending": "to-do list", "task": "to-do list", "items": "another operation", "remind": "calendar event",
             "research": "own mail", "file-read": "mail message", "reminder-forget": "cancel", "ask": "web search", "event-create": "reminder", "cancel": "reminder-forget"})


def canonical(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha(obj) -> str:
    return hashlib.sha256(canonical(obj)).hexdigest()


def planted(monkeypatch, change):
    """Replace `operations.OPERATIONS` with a deep copy of the rows on which `change(rows_by_name)` made one planted fault; returns the copy."""
    rows = [copy.deepcopy(row) for row in operations.OPERATIONS]
    change({row["name"]: row for row in rows})
    monkeypatch.setattr(operations, "OPERATIONS", tuple(rows))
    return rows


def hashes_of(classes: dict, table: dict) -> tuple:
    """(the classes of the rows the literals held, the table, its order, its slot order) as hashes. `CLASSES` keeps every row, a row of a later version included, so that a typed command
    of a new operation works at once; the literal at ed6ea6b held the rows of version 1 only, so the classes are taken for the rows the table of that version holds."""
    return (sha({op: cls for op, cls in classes.items() if op in table}), sha(table), sha(list(table)), sha([[op, list(row["slots"])] for op, row in table.items()]))


def views_hashes(version=1) -> tuple:
    return hashes_of(*natural.views(version))


def pinned_views() -> tuple:
    return (PINNED_HASHES["natural_classes_ed6ea6b"], PINNED_HASHES["natural_table_ed6ea6b"], PINNED_HASHES["natural_order_ed6ea6b"],
            PINNED_HASHES["natural_slot_order_ed6ea6b"])


def entry_catalog_sha() -> str:
    return json.loads((RUNTIME / "interpreter_enable.json").read_text(encoding="utf-8"))["entries"][-1]["catalog_sha256"]


# --- the views equal the literals they replace --------------------------------------------------------------------------------------------------------


def test_the_views_equal_the_literals_they_replace():
    """The classes, the table, its order and its slot order hash to what the literals at ed6ea6b hashed to."""
    assert operations.LINE_CATALOG == 1
    assert views_hashes(1) == pinned_views()
    assert hashes_of(natural.CLASSES, natural.NATURAL) == pinned_views()
    assert [op for op in natural.CLASSES if op in natural.NATURAL] == list(natural.NATURAL), "the classes are in the order of the table"      # CB-3: a row of a later catalog version has a class and no row of the table
    assert len(natural.NATURAL) == 99 and len(natural.CLASSES) == len(operations.OPERATIONS) >= 99


def test_vacuity_a_changed_class_a_changed_order_or_a_new_v1_slot_moves_the_pinned_hashes(monkeypatch):
    planted(monkeypatch, lambda rows: rows["status"]["natural"].update({"class": "G"}))
    assert views_hashes(1)[0] != pinned_views()[0]
    monkeypatch.undo()
    planted(monkeypatch, lambda rows: rows["status"]["natural"].update({"order": 99, "since": 1}) or rows["ask"]["natural"].update({"order": 1}))
    assert views_hashes(1)[2] != pinned_views()[2]
    monkeypatch.undo()
    planted(monkeypatch, lambda rows: rows["status"]["natural"]["slots"].update({"extra": {"kind": "word", "param": "extra", "since": 1}}))
    assert views_hashes(1)[1] != pinned_views()[1] and views_hashes(1)[3] != pinned_views()[3]


def test_a_row_and_a_slot_of_a_later_version_are_invisible_to_a_line_but_not_to_the_classes(monkeypatch):
    """A since-2 row has a class (a typed command works) and no row of the table; a since-2 slot is not in the row of version 1."""
    rows = [copy.deepcopy(row) for row in operations.OPERATIONS]
    by_name = {row["name"]: row for row in rows}
    by_name["items"]["natural"]["slots"]["state"] = {"kind": "span", "param": "state", "since": 2}
    extra = copy.deepcopy(by_name["status"])
    extra["name"] = "demo-note"
    extra["natural"].update({"class": "R", "since": 2, "order": 100, "what": "demo", "about": "A demo row.", "slots": {}})
    monkeypatch.setattr(operations, "OPERATIONS", tuple(rows + [extra]))
    classes1, table1 = natural.views(1)
    classes2, table2 = natural.views(2)
    assert classes1["demo-note"] == "R" == classes2["demo-note"]
    assert "demo-note" not in table1 and "demo-note" in table2
    assert "state" not in table1["items"]["slots"] and "state" in table2["items"]["slots"]
    assert views_hashes(1) == pinned_views(), "a row and a slot of version 2 change nothing of version 1"
    assert sha(catalog.generate(version=1)) == PINNED_HASHES["interpreter_catalog_blite"]
    # the router's check believes only the table of version 1: the new operation and the new slot are refused while the catalog is at 1
    monkeypatch.setattr(natural, "CLASSES", classes1)
    monkeypatch.setattr(natural, "NATURAL", table1)
    assert natural.check_operation("demo-note", {}, None, "show the demo")["ok"] is False
    assert natural.check_operation("items", {"state": "unread"}, None, "list the unread")["ok"] is False
    monkeypatch.setattr(natural, "CLASSES", classes2)
    monkeypatch.setattr(natural, "NATURAL", table2)
    assert natural.check_operation("demo-note", {}, None, "show the demo")["ok"] is True
    assert natural.check_operation("items", {"state": "unread"}, None, "list the unread")["ok"] is True


# --- the served catalog is byte for byte the one an enabling entry pins -------------------------------------------------------------------------------


def test_the_served_catalog_is_byte_identical_at_version_1():
    generated = catalog.generate(version=1)
    assert sha(generated) == PINNED_HASHES["interpreter_catalog_blite"] == entry_catalog_sha() == interpreter.SERVED_SHA256
    assert catalog.generate() == generated and catalog.sha256(generated) == sha(generated)
    assert (RUNTIME / "interpreter_catalog.json").read_text(encoding="utf-8") == catalog.text(generated), "the file on disk is exactly what the rows generate"
    assert (len(generated["ops"]), len(generated["refused"])) == (SERVED_NOW, REFUSED_NOW)
    done = subprocess.run([sys.executable, str(RUNTIME / "interpreter_catalog.py"), "--check"], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    assert interpreter_enable.active("pt-BR") is not None, "the interpreter stays on with the entry in force"


def test_vacuity_the_switch_is_load_bearing_a_catalog_of_version_2_turns_the_entry_off(monkeypatch):
    """With LINE_CATALOG at 2 the generated catalog differs, and a served file written from it makes no entry match: the interpreter is off until a new entry."""
    assert interpreter_enable.active("pt-BR") is not None
    monkeypatch.setattr(operations, "LINE_CATALOG", 2)
    flipped = catalog.generate()
    assert sha(flipped) != PINNED_HASHES["interpreter_catalog_blite"] and flipped["v"] == 2
    monkeypatch.setattr(interpreter, "SERVED_SHA256", sha(flipped))      # what the served file would hash to once CB-9 writes it
    assert interpreter_enable.active("pt-BR") is None


def test_vacuity_a_slot_added_to_a_version_1_row_breaks_the_byte_identity(monkeypatch):
    planted(monkeypatch, lambda rows: rows["status"]["natural"]["slots"].update({"extra": {"kind": "word", "param": "extra", "since": 1}}))
    assert sha(catalog.generate(version=1)) != PINNED_HASHES["interpreter_catalog_blite"]


def test_the_catalog_of_version_2_prints_without_writing_and_words_each_row_with_its_about():
    before = (RUNTIME / "interpreter_catalog.json").read_bytes()
    done = subprocess.run([sys.executable, str(RUNTIME / "interpreter_catalog.py"), "--version", "2", "--print"], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    printed = json.loads(done.stdout)
    assert printed == catalog.generate(version=2) and printed["v"] == 2
    assert done.stderr.strip() == sha(printed)
    assert (RUNTIME / "interpreter_catalog.json").read_bytes() == before, "printing writes nothing"
    about = {rec["op"]: rec["about"] for rec in registry.rows(2)}
    first = [r["op"] for r in catalog.generate(version=1)["ops"]]
    later = [r["op"] for r in printed["ops"] if r["op"] not in first]
    assert [r["op"] for r in printed["ops"] if r["op"] in first] == first, "the operations of version 1 keep their order"
    assert later and set(later) == {r["op"] for r in registry.rows(2) if r["since"] == 2 and r["class"] in ("R", "N", "W", "E")}, "version 2 adds the served rows of version 2, and only those"
    assert all(row["what"] == about[row["op"]] for row in printed["ops"] + printed["refused"])
    wrong = subprocess.run([sys.executable, str(RUNTIME / "interpreter_catalog.py"), "--version", "2", "--check"], capture_output=True, text=True, timeout=60)
    assert wrong.returncode == 2, "a version goes with --print only"


# --- every row has a closed record ---------------------------------------------------------------------------------------------------------------------


def record_problems(rows) -> list:
    """The problems of the records of a tuple of rows, by the test's own literals."""
    out = []
    orders = []
    for row in rows:
        name, rec = row["name"], row.get("natural")
        if not isinstance(rec, dict) or set(rec) != KEYS:
            out.append(f"{name}: keys")
            continue
        orders.append((rec["since"], rec["order"]))
        if rec["class"] not in CLASS_WORDS or rec["since"] not in (1, 2) or not isinstance(rec["order"], int) or isinstance(rec["order"], bool) or rec["order"] < 1:
            out.append(f"{name}: class, since or order")
        if rec["privacy"] not in PRIVACY_WORDS or rec["cost"] not in COST_WORDS:
            out.append(f"{name}: privacy or cost")
        if not isinstance(rec["what"], str) or not rec["what"].strip():
            out.append(f"{name}: what")
        if not isinstance(rec["about"], str) or not 1 <= len(rec["about"]) <= 300 or "@" in rec["about"] or re.search(r"[0-9]{8}", rec["about"]):
            out.append(f"{name}: about")
        for slot, spec in rec["slots"].items():
            if set(spec) != SLOT_KEYS or spec["kind"] not in KIND_WORDS or spec["since"] not in (1, 2) or spec["since"] < rec["since"] or not spec["param"]:
                out.append(f"{name}: slot {slot}")
    numbers = [order for _since, order in orders]
    if len(set(numbers)) != len(numbers):
        out.append("order: not unique")
    if sorted(order for since, order in orders if since == 1) != list(range(1, len([1 for since, _o in orders if since == 1]) + 1)):
        out.append("order: the rows of version 1 are not 1..n")
    return out


def test_every_row_has_a_closed_natural_record():
    assert record_problems(operations.OPERATIONS) == []
    assert sorted(rec["order"] for rec in registry.rows(1)) == list(range(1, 100))


def test_the_privacy_and_cost_classes_follow_the_columns_of_the_row():
    for row in operations.OPERATIONS:
        rec = row["natural"]
        assert (rec["cost"] == "model") == (row["name"] in MODEL_ROWS) == (row["model"] is not False), row["name"]      # a metered call is the row's `model` column
        assert (rec["privacy"] == "off-host") == (row["name"] in OFF_HOST), row["name"]
        if row["name"] in EFFECTS:
            assert (rec["privacy"], rec["cost"]) == ("account", "provider"), row["name"]
    for name in ("items", "file-read"):
        assert registry.privacy(name) == "account" and registry.cost(name) == "provider"
    assert (registry.privacy("status"), registry.cost("status")) == ("own", "none")


def test_the_texts_hold_the_rules_and_separate_the_confusable_rows():
    for rec in [registry.row(row["name"]) for row in operations.OPERATIONS]:      # every row, a row of a later version included
        for key in ("about", "what"):
            assert 1 <= len(rec[key]) <= 300 and "@" not in rec[key] and not re.search(r"[0-9]{8}", rec[key]), (rec["op"], key)
        assert not re.search(r"\b(ignore|you must|you should|system prompt|respond with|reply with)\b", rec["about"], re.I), rec["op"]      # it describes the operation, it does not instruct
    about = {row["name"]: row["natural"]["about"].lower() for row in operations.OPERATIONS}
    for op, words in SEPARATES.items():
        assert words in about[op], (op, words)
    assert about["items"] != about["file-read"] and about["research"] != about["ask"]


def test_vacuity_the_record_check_sees_each_planted_fault(monkeypatch):
    for fault in ({"class": "X"}, {"since": 3}, {"order": 2}, {"privacy": "world"}, {"cost": "free"}, {"about": ""}, {"about": "x" * 301}, {"about": "write to a@b.example"},
                  {"about": "a number 12345678 in it"}, {"what": " "}):
        rows = [copy.deepcopy(row) for row in operations.OPERATIONS]
        rows[3]["natural"].update(fault)
        assert record_problems(rows), fault
    rows = [copy.deepcopy(row) for row in operations.OPERATIONS]
    rows[3]["natural"]["slots"]["bad"] = {"kind": "number", "param": "x", "since": 1}
    assert record_problems(rows)
    rows = [copy.deepcopy(row) for row in operations.OPERATIONS]
    del rows[5]["natural"]["cost"]
    assert record_problems(rows)


# --- the origins come from the gate ---------------------------------------------------------------------------------------------------------------


def test_origins_come_from_the_gate():
    seen = 0
    for rec in registry.rows(1):
        if rec["class"] != "E":
            continue
        for slot, spec in rec["slots"].items():
            got = registry.origins(rec["op"], slot)
            seen += 1
            if spec["param"] in FINDER:
                assert got == ("line-span",), (rec["op"], slot)
                assert spec["param"] not in turn_gate.OPS[rec["op"]] and spec["param"] not in turn_gate.ALLOWED, (rec["op"], slot)      # read by code, never an argument of the card
                continue
            assert got == tuple(turn_gate.ALLOWED[spec["param"]]), (rec["op"], slot)
            assert spec["param"] in turn_gate.OPS[rec["op"]], (rec["op"], slot, "a slot fills an argument the gate lets this card take")
            assert set(got) <= set(turn_gate.ORIGINS), (rec["op"], slot)
    assert seen >= 30 and {rec["op"] for rec in registry.rows(1) if rec["class"] == "E"} == EFFECTS


def test_origins_by_their_own_literals():
    assert registry.origins("mail-send", "to") == ("line-span", "config", "index-from", "card-copy")
    assert registry.origins("mail-send", "body") == ("line-span", "composed", "card-copy")
    assert registry.origins("event-create", "time") == ("time-engine", "time-model", "card-copy")
    assert registry.origins("event-create", "service") == ("config", "picked", "line-span", "card-copy")
    assert registry.origins("file-save", "attachment") == ("held",)
    assert registry.origins("mail-mark", "state") == ("line-span", "picked")
    assert registry.origins("mail-archive", "messages") == ("line-number", "listed", "picked", "grounded")
    assert registry.origins("event-cancel", "target") == ("line-span",) == registry.origins("mail-trash", "day")
    assert registry.origins("pending", "id") == ("line-number", "listed")
    assert registry.origins("remind", "text") == ("line-span",) and registry.origins("remind", "when") == ("time-engine",)
    assert registry.origins("research", "question") == ("line-span",)
    for op, slot in (("nothing", "id"), ("pending", "nothing")):
        try:
            registry.origins(op, slot)
        except KeyError:
            continue
        raise AssertionError((op, slot))


def test_vacuity_a_slot_the_gate_does_not_declare_is_refused_not_guessed(monkeypatch):
    planted(monkeypatch, lambda rows: rows["mail-send"]["natural"]["slots"]["subject"].update({"param": "bogus_param"}))
    try:
        registry.origins("mail-send", "subject")
    except ValueError as err:
        assert "bogus_param" in str(err)
    else:
        raise AssertionError("an undeclared parameter of a card slot gave an origin")


# --- the reader --------------------------------------------------------------------------------------------------------------------------------------


def test_rows_row_and_the_fields_read_the_records_and_give_copies(monkeypatch):
    rows = registry.rows()
    assert [rec["op"] for rec in rows] == list(natural.NATURAL), "the served order is the table's order"
    assert [rec["op"] for rec in registry.rows(2) if rec["since"] == 1] == [rec["op"] for rec in rows], "version 2 has the rows of version 1, in their order, and the rows a package added at version 2"
    whole = registry.row("event-change")
    assert whole["class"] == "E" and whole["slots"]["target"] == {"kind": "span", "param": "target", "since": 1}
    assert registry.row("nothing") is None and registry.privacy("nothing") is None and registry.cost("nothing") is None and registry.about("nothing") is None
    assert registry.about("status") == whole_about("status") and registry.what("status") == "where the work stands"
    rows[0]["slots"]["planted"] = 1
    rows[0]["about"] = "changed"
    assert registry.rows()[0]["about"] != "changed" and "planted" not in registry.rows()[0]["slots"], "a caller cannot change the literal"
    assert registry.data.private_words()["v"] == 1, "the data of S41-9 is re-exported unchanged"
    # the version filters rows and slots by `since`
    def change(by_name):
        by_name["items"]["natural"]["slots"]["state"] = {"kind": "span", "param": "state", "since": 2}
    planted(monkeypatch, change)
    assert "state" not in registry.rows(1)[[r["op"] for r in registry.rows(1)].index("items")]["slots"]
    assert "state" in registry.row("items")["slots"]
    assert "state" in registry.rows(2)[[r["op"] for r in registry.rows(2)].index("items")]["slots"]


def whole_about(op):
    return next(row["natural"]["about"] for row in operations.OPERATIONS if row["name"] == op)


def planted_later_row(monkeypatch):
    """Plants a since-2 copy of `status` named `demo-note` and the views of version 1 over it: it has a class and no row of the table."""
    rows = [copy.deepcopy(row) for row in operations.OPERATIONS]
    extra = copy.deepcopy(next(row for row in rows if row["name"] == "status"))
    extra["name"] = "demo-note"
    extra["natural"].update({"since": 2, "order": 100})
    monkeypatch.setattr(operations, "OPERATIONS", tuple(rows + [extra]))
    classes, table = natural.views(1)
    assert "demo-note" in classes and "demo-note" not in table
    monkeypatch.setattr(natural, "CLASSES", classes)
    monkeypatch.setattr(natural, "NATURAL", table)


DEMO_TABLE = {"tag": "xx", "requests": {"forms": {"demo-note": ["show the demo"]}}}


def test_a_form_of_an_operation_a_line_may_not_reach_is_refused_and_never_claimed(monkeypatch):
    """L54: a tier-1 form belongs to an operation of `NATURAL` (what a line may reach), not of `CLASSES`, so a row of a later catalog version claims no line before the flip."""
    planted_later_row(monkeypatch)
    try:
        natural.check_requests(DEMO_TABLE)
    except ValueError as err:
        assert "demo-note" in str(err)
    else:
        raise AssertionError("a form of a row that is not in NATURAL was accepted")
    monkeypatch.setattr(natural, "_requests", lambda languages=None: [{"forms": {"demo-note": [re.compile("show the demo( [0-9]+)?")]}}])
    assert natural.match("show the demo") is None and natural.match("show the demo 3") is None, "match skips an operation that is not in NATURAL, and never indexes it"


def test_vacuity_the_refusal_follows_natural_not_classes(monkeypatch):
    """The same form is accepted and claimed once the operation is in `NATURAL` (version 2): the refusal above is the table's, and a check that fell back to CLASSES would pass the first case."""
    planted_later_row(monkeypatch)
    classes2, table2 = natural.views(2)
    monkeypatch.setattr(natural, "CLASSES", classes2)
    monkeypatch.setattr(natural, "NATURAL", table2)
    natural.check_requests(DEMO_TABLE)      # no ValueError
    monkeypatch.setattr(natural, "_requests", lambda languages=None: [{"forms": {"demo-note": [re.compile("show the demo")]}}])
    found = natural.match("show the demo")
    assert found is not None and found["op"] == "demo-note"


def test_the_one_work_operation_a_line_may_name_is_the_one_check_operation_believes():
    """`natural.LINE_WORK` is read by the registry; `check_operation` (whose source is pinned and so unchanged) names `ask` by hand: the two agree on every operation of class work."""
    for name in ("say", "request", "route", "ask"):
        assert natural.CLASSES[name] == "work"
        believed = natural.check_operation(name, {}, None, "a line")["ok"]
        assert believed == (name == "ask") == (name in natural.LINE_WORK), name


def test_always_is_derived_and_unchanged():
    assert registry.always() == registry.always(1) == ALWAYS_NOW == plan_confirm.ALWAYS


def test_vacuity_always_follows_the_cost_and_the_privacy_and_a_mistyped_class_is_seen(monkeypatch):
    planted(monkeypatch, lambda rows: rows["status"]["natural"].update({"privacy": "off-host"}))
    assert registry.always() == ("status",) + ALWAYS_NOW, "a read that leaves the host is added by its record alone"
    monkeypatch.undo()
    planted(monkeypatch, lambda rows: rows["research"]["natural"].update({"class": "G"}))
    assert registry.always() != ALWAYS_NOW, "a mistyped class shrinks the derived set, and the pinned test above fails with it"
    monkeypatch.undo()
    planted(monkeypatch, lambda rows: rows["event-create"]["natural"].update({"cost": "model"}))
    assert registry.always() == ALWAYS_NOW, "an effect is a card, never a read that always asks"


def test_every_served_read_has_a_sentence_so_that_a_new_read_cannot_skip_the_question():
    for rec in registry.rows():
        if rec["class"] == "R" or rec["op"] in natural.LINE_WORK:
            assert rec["op"] in plan_confirm.NOT_ASKED or rec["op"] in plan_confirm.SENTENCES, rec["op"]
    assert plan_confirm.NOT_ASKED == ("commands",)
    reads = {rec["op"] for rec in registry.rows() if rec["class"] == "R"}
    assert len(reads) == 21 and set(plan_confirm.SENTENCES) >= reads - {"commands"}


def test_vacuity_a_served_read_with_no_sentence_would_be_seen(monkeypatch):
    def change(rows):
        extra = copy.deepcopy(rows["status"])
        extra["name"] = "demo-list"
        extra["natural"].update({"order": 100, "since": 1})
        rows["demo-list"] = extra
    rows = [copy.deepcopy(row) for row in operations.OPERATIONS]
    by_name = {row["name"]: row for row in rows}
    change(by_name)
    monkeypatch.setattr(operations, "OPERATIONS", tuple(rows + [by_name["demo-list"]]))
    missing = [rec["op"] for rec in registry.rows() if rec["class"] == "R" and rec["op"] not in plan_confirm.NOT_ASKED and rec["op"] not in plan_confirm.SENTENCES]
    assert missing == ["demo-list"]


# --- the import has no cycle and the command line is plain -------------------------------------------------------------------------------------------


def test_the_modules_import_in_any_order_and_the_registry_does_not_load_the_gate_at_import():
    for first in ("registry", "natural", "operations", "interpreter_catalog", "plan_confirm", "turn_gate", "interpreter"):
        code = ("import sys; sys.path.insert(0, %r); import %s; import registry, natural, operations, interpreter_catalog, plan_confirm, turn_gate; "
                "assert natural.CLASSES and registry.always() == ('research', 'ask')" % (str(RUNTIME), first))
        done = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, timeout=60)
        assert done.returncode == 0, (first, done.stderr[-400:])
    done = subprocess.run([sys.executable, "-I", "-c", "import sys; sys.path.insert(0, %r); import registry; print('turn_gate' in sys.modules)" % str(RUNTIME)],
                          capture_output=True, text=True, timeout=60)
    assert done.stdout.strip() == "False", "turn_gate is loaded inside `origins`, never at import"


def test_the_command_line_helps_and_lists():
    helped = subprocess.run([sys.executable, str(RUNTIME / "registry.py"), "--help"], capture_output=True, text=True, timeout=60)
    assert helped.returncode == 0 and "--list" in helped.stdout and "--version" in helped.stdout
    listed = subprocess.run([sys.executable, str(RUNTIME / "registry.py"), "--list"], capture_output=True, text=True, timeout=60)
    assert listed.returncode == 0
    lines = listed.stdout.splitlines()
    assert len(lines) == 99 and lines[0].split("\t")[:2] == ["status", "R"] and all(len(line.split("\t")) == 6 for line in lines)
    plain = subprocess.run([sys.executable, str(RUNTIME / "registry.py")], capture_output=True, text=True, timeout=60)
    assert plain.returncode == 0 and "usage" in plain.stdout.lower()
