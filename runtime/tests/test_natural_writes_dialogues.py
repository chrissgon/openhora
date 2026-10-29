"""Natural writes: a dialogue fuzz over the question-and-answer machine (package NR-5, SPEC-NATURAL-WRITES 9.1). The rule: a write is opened only with every slot from code, the
person's own lines or a list code made and the person chose from; a slot that is missing, or that has two readings, is asked and never filled by a guess. For every line of
the corpus (natural_writes_corpus.jsonl: every operation of the calendar and files families in pt-BR and en, and requests for work that merely start with a write verb), the
corpus of the other natural families (natural_writes*corpus.jsonl) and both corpora of the reminders (test_natural_corpus.py), and every answer of a list of 40, the dialogue
is walked two answers deep from a sample and one deep from all, in three configurations (one account; two accounts and no default; two with a default) and three states of the
snapshots and of the files a sender sent (none, one, two). The open step is a stand-in that records the call; each recorded call must pass `natural_writes.problems`, slot by
slot. Offline, no model, no network, no writer.

The default run walks a deterministic SAMPLE of the corpus (principle 13: the whole walk of nine cases took about eight minutes, and a CI job is limited to 25): every request for
work, the first lines of each operation in each language, and every SAMPLE_EVERY-th line of the rest, the starting line rotating with the case so that the nine cases together
cover the corpus. `WB_FULL_FUZZ=1` walks every line in every case (runtime/README.md, docs/decisions.md), each case in FULL_SHARDS tests of their own (one line in four, by its
index) so that no test runs for minutes: one case took 47 to 87 s alone and up to 190 s on a loaded runner, past the 120 s a CI worker waits before it dumps its stacks, and a
worker died in one of them in the whole-suite run of 2026-10-21 (the cause of the death was not found; the long test is the only thing that held, and the shards remove it).

S41-11 (re-targeted, never removed: L60, L61): the FIRST line of a dialogue no longer enters through the closed heads of the write families (the product has none). It enters as the product enters
it: a stand-in model answers with the decision built from the line's gold, the family reader's own reading of the line with the operation fixed (runtime/tests/interpreter_stand_in.py), the
interpreter's own parse and check (`ops_interpret.decide`) accepts or refuses it, and `ops_interpret._carry_out` carries it out through the same family resolvers; for every third line a PERTURBED
decision is carried out too (a span that is not in the line, a number the line does not write, an account the project does not list, an `inherit` with nothing to inherit). The walk after the first
line is unchanged: the family questions and the 40+ answers, the three configurations, the three states. A line that answers nothing is a new line, which the stand-in model sends to the router. The
oracle is the same (`natural_writes.problems`, which reads `turn_gate.value_problems`) on every recorded call, plus the gate's own counters.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_natural_writes_dialogues.py
     WB_FULL_FUZZ=1 uv run --with pytest==9.1.1 pytest runtime/tests/test_natural_writes_dialogues.py
"""
from __future__ import annotations

import copy
import datetime
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

import standin_tree as st
import interpreter_stand_in as si
import natural_kit
from test_calendar_write import world  # noqa: F401  (the calendar world: a real project to read the configuration of)
from test_natural_corpus import clock
from test_natural_dialogues import lines as reminder_lines
from test_reminders import Clock

ops = st.load("ops")
ops_core = st.load("ops_core")
ops_natural_calendar = st.load("ops_natural_calendar")
ops_natural_files = st.load("ops_natural_files")
ops_natural_mail = st.load("ops_natural_mail")
item_refs = st.load("item_refs")
ops_natural_writes = st.load("ops_natural_writes")
drafts = st.load("drafts")
natural = st.load("natural")
natural_writes = st.load("natural_writes")
natural_time = st.load("natural_time")
turn_gate = st.load("turn_gate")
ops_interpret = st.load("ops_interpret")
interpreter = st.load("interpreter")

HERE = Path(__file__).resolve().parent
NOW = clock("2026-10-19 09:00")
CHANNEL = "messaging"      # S41-11: the interpreter carries a decision out on the messaging channel only (`ops_interpret.CHANNEL`)
ALLOWED = {row["op"] for row in interpreter.SERVED["ops"]}
NOW_LOCAL = NOW.replace(tzinfo=None)      # the interpreter reads the wall clock of the zone
ANSWERS = ["sim", "yes", "não", "no", "cancela", "cancel", "1", "2", "3", "4", "5", "6", "8h", "às 15h", "9", "21", "amanhã", "sexta", "quinta às 10h", "dia todo", "o dia todo",      # validate: allow english-only -- a Portuguese line is the input under test
           "all day", "google", "outlook", "microsoft", "work", "personal", "trabalho", "ideias.md", "notas.txt", "documento google", "Dentista da Júlia", "Reunião com o time",      # validate: allow english-only -- a Portuguese line is the input under test
           "bia@exemplo.example", "um assunto qualquer", "um texto de corpo", "marca outra coisa quinta às 9h", "/status", "lista os e-mails", "hmm",
           "segunda", "dia 25", "9h", "daqui a 2 horas", "20/10 às 10h", "31/02 às 10h", "tomorrow at 3pm", "Friday"]      # validate: allow english-only -- answers in Portuguese, data of the case
GOOGLE = {"address": "pat@example.com", "calendars": {"personal": "pat@example.com", "side": "side.calendar@example.com"}, "folders": {"default": "FolderId0001", "cv": "Cv_Folder_0001"},
          "mail_folders": {"contas": "Label_1"}, "move_removes_inbox": True}
MICROSOFT = {"address": "casey.rivera@mail.example", "calendars": {"personal": "default", "work": "AAMkWork="}, "folders": {"default": "FolderId0002", "docs": "/Documents/openhora"},
             "mail_folders": {"contas": "AAMkBox="}, "move_removes_inbox": True}
CONFIGS = {"one": {"google": GOOGLE}, "two": {"google": GOOGLE, "microsoft": MICROSOFT}, "default": {"google": GOOGLE, "microsoft": MICROSOFT, "default": "google"}}
STATES = {"none": (0, 0), "one": (1, 1), "two": (2, 2)}
HELD = [{"id": 11, "name": "Contract.pdf", "kind": "pdf", "bytes": 1000}, {"id": 12, "name": "Minutes.docx", "kind": "docx", "bytes": 2000}]
CAL_SOURCES = [{"id": "agenda", "account": "google"}, {"id": "trabalho", "account": "google"}]
MAIL_SOURCES = [{"id": "inbox", "account": "google"}, {"id": "work", "account": "microsoft"}]      # the registered mail sources of a state (none, one, two), package NR-5b
MAIL_INDEX = [{"n": n, "from_address": f"{who}@{host}.example", "subject": subject}
              for n, (who, host, subject) in enumerate([("billing", "banco", "Fatura de outubro"), ("ana", "clinic", "Appointment confirmed"), ("bia", "exemplo", "Contrato novo"),
                                                        ("loja", "shop", "Seu pedido foi enviado"), ("noreply", "banco", "Fatura de setembro")] * 6, 1)]      # 30 messages, newest first
FILE_ROWS = [{"id": "lista-de-compras", "type": "drive", "origin": "x1", "description": "", "version": 1, "catalog": {"name": "lista de compras.md", "date": "2026-10-10"}},
             {"id": "roteiro", "type": "drive", "origin": "x2", "description": "", "version": 1, "catalog": {"name": "roteiro.md", "date": "2026-10-10"}}]


SAMPLE_EVERY = 7          # the default run walks one line in seven of the corpus (every line with WB_FULL_FUZZ=1)
NAMED_PER_GROUP = 2       # ... and the first lines of each operation in each language, which name the forms
FULL = os.environ.get("WB_FULL_FUZZ") == "1"
FULL_SHARDS = 4           # with WB_FULL_FUZZ=1 each case is this many tests; shard k walks the lines whose index is k modulo FULL_SHARDS
SHARDS = FULL_SHARDS if FULL else 1


def shard_of(indexes: list, shard: int, shards: int) -> list:
    """The part of a case's walk that one shard takes: the indexes equal to `shard` modulo `shards`. The shards of a case are disjoint and together make the walk."""
    return [index for index in indexes if index % shards == shard]


def sampled(rows: list, case: int) -> list:
    """The indexes of the corpus rows one case walks: all of them with WB_FULL_FUZZ=1; else every request for work, the first NAMED_PER_GROUP lines of each (language, operation),
    and every SAMPLE_EVERY-th line starting at `case` modulo SAMPLE_EVERY (so nine cases together cover the whole corpus). Deterministic: no random choice."""
    if FULL:
        return list(range(len(rows)))
    seen, chosen = {}, set()
    for index, row in enumerate(rows):
        key = (row["lang"], row["op"])
        seen[key] = seen.get(key, 0) + 1
        if row["op"] == "work" or seen[key] <= NAMED_PER_GROUP or index % SAMPLE_EVERY == case % SAMPLE_EVERY:
            chosen.add(index)
    return sorted(chosen)


def corpus():
    rows = []
    for path in sorted(HERE.glob("natural_writes*corpus.jsonl")):
        rows += [json.loads(raw) for raw in path.read_text(encoding="utf-8").splitlines() if raw.strip()]
    return rows


class Env:
    """One configuration and state of the world, the recorder of the calls and the walk."""

    def __init__(self, world, monkeypatch, config, state):
        self.project, self.accounts, self.calls, self.bad = world["path"], config, [], []
        self.opened = self.asked = 0
        self.gate_calls, self.gate_refusals = 0, []          # S41-7: every card the walk opens passes through the gate's provenance check first; a refusal here would be a false one (the oracle accepts them all)
        real_provenance = turn_gate.provenance

        def provenance(op, args, origins):
            found = real_provenance(op, args, origins)
            self.gate_calls += 1
            if found:
                self.gate_refusals.append((op, sorted(args), found))
            return found
        monkeypatch.setattr(turn_gate, "provenance", provenance)
        base = ops_core.context(self.project)
        self.ctx = dict(base, cfg=dict(base["cfg"], accounts=config))
        sources_n, files_n = STATES[state]
        self.sources, self.held = CAL_SOURCES[:sources_n], HELD[:files_n]
        self.file_rows = FILE_ROWS if files_n else []
        self.mail_sources = MAIL_SOURCES[:sources_n]
        self.offered = {"numbers": {h["id"] for h in self.held}, "sources": {r["id"] for r in self.file_rows}, "source_accounts": {s["account"] for s in self.sources},
                        "options": set(), "mail_sources": {s["id"]: s["account"] for s in self.mail_sources},
                        "mail_index": {s["id"]: copy.deepcopy(MAIL_INDEX) for s in self.mail_sources}}          # grows with every option code lists in a question the walk reaches
        monkeypatch.setattr(ops_natural_calendar, "calendar_sources", lambda ctx: list(self.sources))
        monkeypatch.setattr(ops_natural_files, "held_files", lambda ctx, channel, sender: list(self.held))
        monkeypatch.setattr(ops_natural_files, "sources", SimpleNamespace(list_catalog=lambda ctx, hashes=False: list(self.file_rows)))
        monkeypatch.setattr(ops_natural_mail, "_mail_sources", lambda ctx: list(self.mail_sources))
        monkeypatch.setattr(item_refs, "may_read", lambda ctx, channel, sender=None: channel != "mcp")
        monkeypatch.setattr(item_refs, "read_index", lambda ctx, source_id, **kw: {"source": source_id, "type": "mail", "entries": copy.deepcopy(MAIL_INDEX)})
        monkeypatch.setattr(ops_natural_writes, "_call_operation", self.record)
        monkeypatch.setattr(ops_natural_writes, "_admit", lambda ctx, op, channel, sender: None)      # the policy is not what the walk is about: the sender may do what the line asks
        self.carried = self.refused_by_check = 0

    def record(self, project, op, args, channel, sender):
        self.calls.append((op, dict(args)))
        return {"request": 1, "task": 1, "pending": 7, "word": "calendar", "on_cards": True}

    def first(self, text, op, text_of_model=None):
        """The first line of a dialogue, entered as the product enters it (S41-11): the stand-in model's answer (`text_of_model`, else the decision built from the line's gold, `op`), the interpreter's own
        parse and check, and `_carry_out`. `op` "work" is a request for work: the model says `route` and nothing is opened. Returns the decision's kind (None: the family reads nothing in the line)."""
        extras = {}
        if op == "work":
            decision = ops_interpret.decide(text, '{"v":1,"kind":"route"}', NOW_LOCAL, si.ZONE, ALLOWED)
            assert decision["kind"] == "route", text
            return "route"
        model = text_of_model if text_of_model is not None else si.model_text(text, op, NOW_LOCAL)
        if model is None:
            return None
        decision = ops_interpret.decide(text, model, NOW_LOCAL, si.ZONE, ALLOWED)
        if decision["kind"] == "op":
            self.carried += 1
            ops_interpret._carry_out(self.project, self.ctx, decision, text, None, extras)
            if ops_natural_writes.live(CHANNEL, None) is not None:
                self.asked += 1
        else:
            self.refused_by_check += 1
        return decision["kind"]

    def step(self, text):
        """The messaging bridge's `natural_write` for a later line: the sender's open question first. A line that answers nothing is a new line of its own, which the stand-in model sends to the router
        (nothing is opened). Returns (the reply, whether the line was taken as the answer to the open question)."""
        extras = {}
        draft = ops_natural_writes.live(CHANNEL, None)
        if draft is not None:
            self.offered["options"] |= {o["value"] for o in draft.get("options", []) if isinstance(o["value"], str)}
        reply = ops_natural_writes.answer(self.project, self.ctx, draft, text, CHANNEL, None, extras) if draft is not None else None
        taken = reply is not None
        if ops_natural_writes.live(CHANNEL, None) is not None:
            self.asked += 1
        return reply, taken

    def check(self, said, work=False):
        for op, args in self.calls:
            self.opened += 1
            found = natural_writes.problems(op, args, said, self.accounts, self.offered, NOW)
            if work:
                found.append("a request for work opened a write")
            if found:
                self.bad.append((said, op, args, found))
        self.calls.clear()

    def explore(self, said, depth, limit):
        state = ops_natural_writes.live(CHANNEL, None)
        if state is None:
            return
        snapshot = copy.deepcopy(state)
        for answer in ANSWERS:
            drafts.clear()
            drafts.put(CHANNEL, "", copy.deepcopy(snapshot), "write", ttl=600)
            self.calls.clear()
            _, taken = self.step(answer)
            lines = said + [answer] if taken else [answer]          # a line that answers nothing is a new line of its own
            self.check(lines)
            after = ops_natural_writes.live(CHANNEL, None)
            if depth + 1 < limit and after is not None:
                self.explore(lines, depth + 1, limit)
        drafts.clear()


@pytest.fixture(autouse=True)
def forget():
    drafts.clear()
    yield
    drafts.clear()


@pytest.fixture
def moment(monkeypatch):
    return Clock(monkeypatch, wall="2026-10-19 09:00")


@pytest.fixture
def shard():
    """The shard of the walk: the whole of it (shard 0 of 1) unless WB_FULL_FUZZ=1 parametrizes it below."""
    return 0


def sharded(test):
    """With WB_FULL_FUZZ=1 the test runs once per shard; otherwise once, with the fixture's shard 0 of 1."""
    return pytest.mark.parametrize("shard", range(FULL_SHARDS))(test) if FULL else test


@sharded
@pytest.mark.parametrize("config", sorted(CONFIGS))
@pytest.mark.parametrize("state", sorted(STATES))
def test_no_write_is_opened_with_a_guessed_slot(world, moment, monkeypatch, config, state, shard):  # noqa: F811
    env = Env(world, monkeypatch, CONFIGS[config], state)
    rows = corpus()
    case = sorted(CONFIGS).index(config) * len(STATES) + sorted(STATES).index(state)
    every = [(index, rows[index]["line"], rows[index]["op"]) for index in shard_of(sampled(rows, case), shard, SHARDS)]
    perturbed = 0
    for index, text, op in every:
        work = op == "work"
        drafts.clear()
        env.calls.clear()
        env.first(text, op)
        env.check([text], work)
        if work:
            assert ops_natural_writes.live(CHANNEL, None) is None, text
            continue
        held = copy.deepcopy(ops_natural_writes.live(CHANNEL, None))
        if index % 3 == 2:      # S41-11: for every third line a model that read it wrong: the checks that stand between a wrong decision and a card must hold, whatever the walk then asks
            drafts.clear()
            env.calls.clear()
            model = si.model_text(text, op, NOW_LOCAL)
            if model is not None:
                perturbed += 1
                env.first(text, op, si.perturbed(model, index // 3, env.accounts))
                env.check([text])
            drafts.clear()
            if held is not None:
                drafts.put(CHANNEL, "", held, "write", ttl=600)
        env.calls.clear()
        env.explore([text], 0, 2 if index % 9 == 0 else 1)
    assert perturbed > 10, perturbed
    assert env.bad == [], "\n".join(map(str, env.bad[:12]))
    assert env.opened > 100 and env.asked > 100, (env.opened, env.asked)          # the walk reaches both ends: calls made and questions asked
    assert env.gate_refusals == [] and env.gate_calls >= env.opened > 100, (env.gate_calls, env.opened, env.gate_refusals[:6])          # S41-7: the gate refused none of the calls the oracle accepts, and every call went through it


def test_the_shards_of_a_case_are_disjoint_and_together_the_whole_walk():
    walk = list(range(769))
    for shards in (1, 4):
        parts = [shard_of(walk, k, shards) for k in range(shards)]
        assert sorted(i for part in parts for i in part) == walk and sum(len(p) for p in parts) == len(walk), "every line in exactly one shard"
    assert FULL_SHARDS > 1 and shard_of(walk, 0, 4) != shard_of(walk, 1, 4)
    broken = [shard_of(walk, k, 4) for k in (0, 1, 2)]          # vacuity: a shard missing from the set loses lines, which the check above would see
    assert sorted(i for part in broken for i in part) != walk


def test_the_provenance_check_catches_a_slot_the_person_never_gave():
    two = {"google": GOOGLE, "microsoft": MICROSOFT}
    offered = {"numbers": {11}, "sources": set(), "source_accounts": set()}
    ok = natural_writes.problems("event-create", {"account": "google", "title": "dentista", "start": "2026-10-22T10:00"}, ["marca dentista quinta às 10h no google"], two, offered, NOW)
    assert ok == []
    bad = natural_writes.problems("event-create", {"account": "google", "title": "Invented", "start": "2026-10-23T10:00", "end": "2026-10-23T12:00"},
                                  ["marca dentista quinta às 10h"], two, offered, NOW)
    assert len(bad) == 4 and any("account" in b for b in bad) and any("title" in b for b in bad) and any("start" in b for b in bad) and any("end" in b for b in bad)
    assert natural_writes.problems("file-save", {"account": "google", "attachment": 99}, ["salva esse pdf no drive"], two, offered, NOW) != []
    assert natural_writes.problems("file-save", {"account": "google", "attachment": 11}, ["salva esse pdf no drive"], two, offered, NOW) == []
    assert natural_writes.problems("event-create", {"account": "microsoft", "title": "dentista", "start": "2026-10-22T10:00"}, ["marca dentista quinta às 10h", "2"], two, offered, NOW) == []


def remind_text(line: str, now) -> str:
    """What a model that read a reminder line would answer: the operation `remind` with the time as written, the moment the reminders' own engine reads, and the longest rest of the line (a span of
    it). "" when the line holds no time or the engine reads none."""
    phrase = si.time_phrase(line, natural_time.languages())
    if not phrase or phrase not in line:
        return ""
    before, _, after = line.partition(phrase)
    rest = max((before.strip(" ,;:-"), after.strip(" ,;:-")), key=len)
    when = natural_kit.made(natural, line, now).get("when")
    if not rest or not isinstance(when, str):
        return ""
    try:
        moment = datetime.datetime.strptime(when, "%Y-%m-%d %H:%M")
    except ValueError:      # a date that does not exist (31/02): the engine reads none, the model has nothing to say
        return ""
    return json.dumps({"v": 1, "kind": "op", "op": "remind", "slots": {"text": rest, "when": phrase}, "time_iso": moment.strftime("%Y-%m-%dT%H:%M"), "weekday": si.WEEKDAYS[moment.weekday()]},
                      ensure_ascii=False)


def test_both_reminder_corpora_through_the_interpreter_open_no_write_and_a_calendar_read_of_them_opens_nothing_with_a_guessed_slot(world, moment, monkeypatch):  # noqa: F811
    """S41-11 (re-targeted from the claim `natural.candidate`): every reminder line enters as a model's `remind` decision, checked by the interpreter and carried out; it opens no write. Every third
    line also enters as a model that took the reminder for an event (the decision the family's reader would give with `event-create` fixed): whatever card that opens must pass the oracle."""
    env = Env(world, monkeypatch, CONFIGS["two"], "one")
    carried = confused = 0
    for index, (text, now) in enumerate(reminder_lines()):
        moment.moment = now
        local = now.replace(tzinfo=None)
        drafts.clear()
        env.calls.clear()
        model = remind_text(text, now)
        if model:
            decision = ops_interpret.decide(text, model, local, si.ZONE, ALLOWED)
            if decision["kind"] == "op":
                carried += 1
                try:
                    ops_interpret._carry_out(env.project, env.ctx, decision, text, None, {})
                except ops_core.OpsError:      # the policy of the stand-in world may refuse a reminder to a sender it does not list: the line opened nothing either way
                    pass
            assert env.calls == [] and ops_natural_writes.live(CHANNEL, None) is None, (text, decision["kind"])
        if index % 3 == 2:
            wrong = si.model_text(text, "event-create", local)
            if wrong is not None:
                confused += 1
                env.first(text, "event-create", wrong)
        env.check([text])
        if index % 40 == 0:
            env.explore([text], 0, 1)
    assert carried > 100 and confused > 20, (carried, confused)
    assert env.bad == [], "\n".join(map(str, env.bad[:12]))
    assert env.gate_refusals == [], env.gate_refusals[:6]          # S41-7


def test_the_corpus_holds_what_the_spec_asks_of_it():
    rows = corpus()
    for lang in ("pt-BR", "en"):
        assert sum(1 for r in rows if r["lang"] == lang and r["op"] != "work") >= 150, lang
    assert sum(1 for r in rows if r["op"] == "work") >= 60 and len(ANSWERS) >= 30
    assert {r["op"] for r in rows} >= {"event-create", "event-change", "event-cancel", "file-create", "file-replace", "file-save", "work",
                                       "mail-send", "mail-reply", "mail-draft", "mail-archive", "mail-move", "mail-mark", "mail-trash"}
    for row in rows:      # S41-11: the families read a line with the operation of its row fixed; with no operation nothing reads it (no closed head claims a line any more)
        assert natural_writes.read(row["line"], NOW) is None, row
        if row["op"] != "work":
            found = natural_writes.read(row["line"], NOW, op=row["op"])
            assert found is not None and found["op"] == row["op"], row


def test_a_line_from_the_mcp_mode_opens_nothing_whatever_the_corpus(world, moment, monkeypatch):  # noqa: F811
    env = Env(world, monkeypatch, CONFIGS["default"], "two")
    for row in corpus():
        extras = {}
        assert ops_natural_writes.open_line(env.project, env.ctx, row["line"], "mcp", None, extras, hint=None if row["op"] == "work" else row["op"]) is None, row
    assert env.calls == []


def test_a_router_that_names_random_write_operations_with_random_spans_opens_a_write_only_where_the_code_parse_and_the_checks_hold(world, moment, monkeypatch):  # noqa: F811
    import random
    rng = random.Random(5)
    env = Env(world, monkeypatch, CONFIGS["default"], "two")
    names = ["event-create", "event-change", "event-cancel", "file-create", "file-replace", "file-save", "mail-send", "mail-reply"]
    for row in corpus():
        for _ in range(2):
            hint = rng.choice(names)
            drafts.clear()
            env.calls.clear()
            extras = {}
            reply = ops_natural_writes.open_line(env.project, env.ctx, row["line"], CHANNEL, None, extras, hint=hint)
            parsed = natural_writes.read(row["line"], NOW, op=hint)
            if parsed is None:
                assert reply is None and env.calls == [], (row["line"], hint)
            env.check([row["line"]])
    assert env.bad == [], "\n".join(map(str, env.bad[:12]))
    assert env.gate_refusals == [], env.gate_refusals[:6]          # S41-7


# --- vacuity of the walk (S41-11): the guards each fail on a planted wrong result -------------------------------------------------------------------------


EVENT_ROWS = [row for row in corpus() if row["op"] == "event-create" and row["lang"] == "pt-BR"][:40]


def test_vacuity_a_resolver_that_fills_a_slot_the_person_never_gave_is_reported_by_the_oracle(world, moment, monkeypatch):  # noqa: F811
    env = Env(world, monkeypatch, CONFIGS["two"], "one")
    real = ops_natural_writes.family_ops

    class Inventing:
        def __init__(self, family):
            self.family = real(family)

        def resolve(self, *args, **kwargs):
            out = self.family.resolve(*args, **kwargs)
            if "args" in out and "title" in out["args"]:
                out["args"]["title"] = "Invented title nobody wrote"
            return out

        def __getattr__(self, name):
            return getattr(self.family, name)
    monkeypatch.setattr(ops_natural_writes, "family_ops", lambda family: Inventing(family))
    for row in EVENT_ROWS:
        drafts.clear()
        env.calls.clear()
        env.first(row["line"], row["op"])
        env.check([row["line"]])
    assert env.bad, "the oracle must report a title the person never wrote"


def trusting(original: str):
    """An interpreter whose check lets a perturbed answer through: the decision of the ORIGINAL answer with the perturbed spans laid over it, as a model's wrong span would be believed by a check that does not look."""
    real = ops_interpret.decide

    def decide(line, text, now, zone, allowed, frame=None):
        decision = real(line, original, now, zone, allowed)
        if decision["kind"] == "op":
            decision["spans"] = dict(decision["spans"], **{k: v for k, v in json.loads(text)["slots"].items() if k in decision["spans"]})
        return decision
    return decide


def test_vacuity_the_check_patched_open_lets_a_wrong_span_open_a_card_and_the_oracle_reports_it_and_the_real_check_refuses_it(world, moment, monkeypatch):  # noqa: F811
    real_decide = ops_interpret.decide
    kinds, opened_wrong = [], 0
    for row in EVENT_ROWS:
        model = si.model_text(row["line"], row["op"], NOW_LOCAL)
        if model is None or "time" not in json.loads(model)["slots"] or "title" not in json.loads(model)["slots"]:
            continue
        wrong = si.perturbed(model, 0, ("google", "microsoft"))      # kind 0: a title that is not in the line
        assert json.loads(wrong)["slots"]["title"] != json.loads(model)["slots"]["title"]
        with monkeypatch.context() as inner:
            env = Env(world, inner, CONFIGS["two"], "one")
            drafts.clear()
            env.first(row["line"], row["op"], wrong)
            env.check([row["line"]])
            assert env.bad == [] and env.calls == [], "the real check refuses a span that is not in the line: no card, nothing to report"
            kinds.append(real_decide(row["line"], wrong, NOW_LOCAL, si.ZONE, ALLOWED)["kind"])
        with monkeypatch.context() as inner:
            env = Env(world, inner, CONFIGS["two"], "one")
            inner.setattr(ops_interpret, "decide", trusting(model))
            drafts.clear()
            env.first(row["line"], row["op"], wrong)
            env.check([row["line"]])
            opened_wrong += bool(env.bad)
    assert kinds and "op" not in kinds and opened_wrong >= 3, (kinds, opened_wrong)
