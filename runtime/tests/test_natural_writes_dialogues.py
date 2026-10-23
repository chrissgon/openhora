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

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_natural_writes_dialogues.py
     WB_FULL_FUZZ=1 uv run --with pytest==9.1.1 pytest runtime/tests/test_natural_writes_dialogues.py
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

import standin_tree as st
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

HERE = Path(__file__).resolve().parent
NOW = clock("2026-10-19 09:00")
CHANNEL = "terminal"
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

    def record(self, project, op, args, channel, sender):
        self.calls.append((op, dict(args)))
        return {"request": 1, "task": 1, "pending": 7, "word": "calendar", "on_cards": True}

    def step(self, text):
        """The messaging bridge's `natural_write` without the seed: the sender's open question first, then the line as a new write. Returns (the reply, whether the line was
        taken as the answer to the open question)."""
        extras = {}
        draft = ops_natural_writes.live(CHANNEL, None)
        if draft is not None:
            self.offered["options"] |= {o["value"] for o in draft.get("options", []) if isinstance(o["value"], str)}
        reply = ops_natural_writes.answer(self.project, self.ctx, draft, text, CHANNEL, None, extras) if draft is not None else None
        taken = reply is not None
        if reply is None:
            reply = ops_natural_writes.open_line(self.project, self.ctx, text, CHANNEL, None, extras)
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
    every = [(index, rows[index]["line"], rows[index]["op"] == "work") for index in shard_of(sampled(rows, case), shard, SHARDS)]
    for index, text, work in every:
        drafts.clear()
        env.calls.clear()
        env.step(text)
        env.check([text], work)
        if work:
            assert ops_natural_writes.live(CHANNEL, None) is None, text
            continue
        env.explore([text], 0, 2 if index % 9 == 0 else 1)
    assert env.bad == [], "\n".join(map(str, env.bad[:12]))
    assert env.opened > 100 and env.asked > 100, (env.opened, env.asked)          # the walk reaches both ends: calls made and questions asked


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


def test_both_reminder_corpora_never_open_a_write_and_the_calendar_lines_among_them_open_nothing_with_a_guessed_slot(world, moment, monkeypatch):  # noqa: F811
    env = Env(world, monkeypatch, CONFIGS["two"], "one")
    for index, (text, now) in enumerate(reminder_lines()):
        moment.moment = now
        drafts.clear()
        env.calls.clear()
        named = natural.candidate(text)
        env.step(text)
        if named is not None and named["op"] in ("remind", "reminders", "reminder-forget", "reminder-restore"):
            assert env.calls == [] and ops_natural_writes.live(CHANNEL, None) is None, (text, named)
        env.check([text])
        if index % 40 == 0:
            env.explore([text], 0, 1)
    assert env.bad == [], "\n".join(map(str, env.bad[:12]))


def test_the_corpus_holds_what_the_spec_asks_of_it():
    rows = corpus()
    for lang in ("pt-BR", "en"):
        assert sum(1 for r in rows if r["lang"] == lang and r["op"] != "work") >= 150, lang
    assert sum(1 for r in rows if r["op"] == "work") >= 60 and len(ANSWERS) >= 30
    assert {r["op"] for r in rows} >= {"event-create", "event-change", "event-cancel", "file-create", "file-replace", "file-save", "work",
                                       "mail-send", "mail-reply", "mail-draft", "mail-archive", "mail-move", "mail-mark", "mail-trash"}
    for row in rows:
        found = natural_writes.read(row["line"], NOW)
        assert (found["op"] if found else "work") == row["op"], row


def test_a_line_from_the_mcp_mode_opens_nothing_whatever_the_corpus(world, moment, monkeypatch):  # noqa: F811
    env = Env(world, monkeypatch, CONFIGS["default"], "two")
    for row in corpus():
        extras = {}
        assert ops_natural_writes.open_line(env.project, env.ctx, row["line"], "mcp", None, extras) is None, row
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
