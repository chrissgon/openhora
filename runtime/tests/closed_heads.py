"""The claim of the write families, as a test fixture (S41-11). Not a test file.

Until S41-11 a plain line that started with a write head ("marca dentista quinta as 10h", "arquiva o email 3") was read with no operation fixed: `natural_writes.read(line, now)` found the
family and the operation itself, and `natural_writes.candidate(line)` said what it was. The product no longer claims a line that way: the interpreter names the operation (L63), and the family
readers and resolvers are carried out with it fixed. The tests of those readers and resolvers (what a family reads, what it asks, which card it opens) entered through the claim, and the claim
is not what they test. This module puts the old claim back for them alone: a test module imports the fixture `closed_heads` (`from closed_heads import closed_heads  # noqa: F401`) and, for the
length of each test, `natural_writes.read` without an operation reads as it did, and `natural_writes.candidate` exists again. The product's `natural_writes.read(..., op=None)` is None
(proved in test_closed_heads_gone.py): nothing outside a test that imports this file claims a line.

Every name in a line here is the test file's own and invented.
"""
from __future__ import annotations

import pytest

import standin_tree as st

natural = st.load("natural")
nw = st.load("natural_writes")


def _read_closed(text, tables, now, shaped):
    """The closed forms of the families, in order, with no operation fixed (what `natural_writes._read_closed` was)."""
    for name in nw.FAMILIES:
        module = nw.family_module(name)
        if module.HEADS(tables) and shaped.lead(module.HEADS(tables), tables) is None:
            continue
        got = module.read(text, tables, now)
        if got:
            return nw._finish(got, name, shaped, tables, None)
    named = natural.candidate(text, tables)
    if named and named["op"] == "calendar-event-create" and named["how"] == "trigger" and "calendar" in nw.FAMILIES:
        got = nw.family_module("calendar").read(text, tables, now, op="event-create")
        return nw._finish(got, "calendar", shaped, tables, None)
    return None


def make(real):
    """(read, candidate): the old behaviour of the two functions, over the real `read` for a line with an operation fixed."""
    def read(line, now=None, languages=None, op=None, *, claim=True):
        if op is not None:
            return real(line, now, languages, op=op, claim=claim)
        tables = nw._tables(languages)
        text = line if isinstance(line, str) else ""
        if not nw._claim(text):
            return None
        found = _read_closed(text, tables, now, nw.Line(text))
        if found is not None and found["op"] == "event-create" and claim and natural.repeat_goes_on(text):
            return None
        return found

    def candidate(line, languages=None, *, claim=True):
        got = read(line, None, languages, claim=claim)
        return {"family": got["family"], "op": got["op"]} if got else None
    return read, candidate


def old_private(line, languages=None):
    """What `natural.private` was (the S41-9 oracle of the private-line detector, deleted with the claim): a reminder asked in words, or a write the closed heads of the families take."""
    found = natural.candidate(line, languages)
    if found is not None and found["op"] in natural.PRIVATE:
        return True
    _, candidate = make(nw.read)
    return candidate(line, languages, claim=False) is not None


@pytest.fixture(autouse=True)
def closed_heads(monkeypatch):
    """`natural_writes.read` reads a line with no operation as it did before S41-11, and `natural_writes.candidate` exists, for the length of the test."""
    read, candidate = make(nw.read)
    monkeypatch.setattr(nw, "read", read)
    monkeypatch.setattr(nw, "candidate", candidate, raising=False)
    return read, candidate


def _old_needs(line, languages=None):
    """What `natural.needs` was: the group a messaging sender must hold for a line `match` takes (a read or a notice its own, a decision `pending`, the other classes `talk`)."""
    found = natural.match(line, languages)
    if found is None:
        return None
    cls = natural.CLASSES[found["op"]]
    if cls in ("R", "N"):
        return found["op"]
    return "pending" if cls == "D" else None


@pytest.fixture
def tier1_forms(monkeypatch):
    """Every closed form of the tables claims a line again, as before S41-11: `natural.decision` is `natural.match` and `natural.needs` is the old one, for the length of the test. For the tests of
    `ops_natural.run` (the order of the checks, the policy, the number, the reply of each class) that entered through a plain line: the product's claim is a decision said in words alone, and the other
    classes are the interpreter's carry-out, which calls `run` too."""
    monkeypatch.setattr(natural, "decision", natural.match)
    monkeypatch.setattr(natural, "needs", _old_needs)
    return natural.match


# --- the interpreter's side of the bridge, for the tests that enter through a plain line (S41-11) -----------------------------------------------------------------------------------------------
# A test of the bridge that says a line in words used to meet a closed head ("lembra", "marca", "cancela o 2") that took the line with no model. The product reads such a line through the
# interpreter (L63): the sender holds `interpret` and a model names the operation. `words_interpreted` is that entry for a test: the sender holds `interpret` (every messaging sender of the
# test), and the model is a stand-in that answers what a model that read the line the way the old closed readers did would answer (`reader_text`): the test is about what the line does once
# it is read, not about who read it. A line the old readers did not take gets `route`, as a model that finds nothing would say.

def _op_text(op, slots=None, **more):
    import json
    return json.dumps({"v": 1, "kind": "op", "op": op, "slots": slots or {}, **more}, ensure_ascii=False)


def _slot_for(op, param):
    return next((name for name, spec in natural.NATURAL[op]["slots"].items() if spec[1] == param), None)


def reader_text(line, now):
    """The model text of a line, as the old closed readers read it, or None."""
    import json
    import interpreter_stand_in as sis
    interpreter = st.load("interpreter")
    served = {row["op"]: row["slots"] for row in interpreter.SERVED["ops"]}
    found = natural.match(line)
    if found is not None and found["op"] in served:
        slots = {}
        for param, value in found["args"].items():
            name = _slot_for(found["op"], param)
            if name in served[found["op"]]:
                slots[name] = str(value)
        return _op_text(found["op"], slots)
    written = nw.read(line, now)
    if written is not None and written["op"] in served:
        return sis.model_text(line, written["op"], now)
    named = natural.claim(line)
    if named is None:
        return None
    op = named["op"]
    if op in ("reminders", "reminder-restore"):
        return _op_text(op)
    if op == "reminder-forget":
        slots = {}
        if isinstance(named.get("id"), int):
            slots["id"] = str(named["id"])
        elif isinstance(named.get("words"), str) and named["words"] in line:
            slots["target"] = named["words"]
        return _op_text(op, slots)
    if op == "remind":
        reading = natural.understand(line, now, named.get("how", "trigger"))
        shape = reading.get("ask") or reading
        words = shape.get("text") or ""
        slots = {"text": words} if words and words in line else {}
        phrase = sis.time_phrase(line, None)
        if phrase:
            slots["when"] = phrase
        readings = shape.get("readings") or ([shape["reading"]] if shape.get("reading") else [])
        more = {}
        if readings and readings[0].get("date") and readings[0].get("time"):
            import datetime
            moment = datetime.datetime.fromisoformat(f"{readings[0]['date']}T{readings[0]['time']}")
            more = {"time_iso": moment.strftime("%Y-%m-%dT%H:%M"), "weekday": sis.WEEKDAYS[moment.weekday()]}
        return _op_text("remind", slots, **more)
    return None


REAL_HANDLE = []


@pytest.fixture
def words_interpreted(monkeypatch):
    """Every messaging sender of the test holds `interpret`, and the model is the stand-in above."""
    import json
    operations = st.load("operations")
    route = st.load("interpreter_route")
    reminders = st.load("ops_reminders")
    real = operations.holds

    def holds(group, channel, policy, sender=None):
        return True if group == "interpret" and channel == "messaging" else real(group, channel, policy, sender)
    monkeypatch.setattr(operations, "holds", holds)

    def complete(route_id, system, user, **kw):
        line = user.rsplit("\nline: ", 1)[-1] if "\nline: " in user else ""
        text = reader_text(line, reminders.now()) if line else None
        return {"ok": True, "text": text if text is not None else json.dumps({"v": 1, "kind": "route"}), "finish": "stop", "usage": {}, "latency_ms": 5, "upstream": "deepinfra"}
    monkeypatch.setattr(route, "complete", complete)
    bridge = st.load("messaging_bridge")
    real_handle = bridge.Bridge.handle
    REAL_HANDLE.append(real_handle)      # a timing test puts it back: it wants the bridge as it is, not waited for

    def handle(self, update):
        """A line the interpreter reads is decided in a job (the decide leg): a test that said a line and looked at once now waits for the jobs to end, up to six seconds (a held planner is waited for no longer)."""
        import time
        result = real_handle(self, update)
        end = time.monotonic() + 6.0
        while time.monotonic() < end and ([t for t in list(self.threads) if t.is_alive()] or self.exclusive):
            time.sleep(0.005)
        return result
    monkeypatch.setattr(bridge.Bridge, "handle", handle)
    gate = st.load("turn_gate")
    gate.forget_all()      # the gate's counts and its breaker are the process's: a test starts with them clear and leaves them clear
    yield complete
    gate.forget_all()
