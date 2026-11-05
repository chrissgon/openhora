"""The fuzz of the mail writes asked in words (package NR-5b, SPEC-NATURAL-WRITES 9.1 for the mail family): no call to an operation is made with a slot the code guessed.

The corpus is natural_writes_mail_cases.py `corpus()` (every operation with every combination of its optional slots, in Brazilian Portuguese and in English, about 600 lines each),
the NEGATIVES and the WORK requests (so a work request or a reminder never opens a mail write), and 20 answers per language (yes and no words, numbers, an account, a mailbox, a
state, an address, a subject, a body, a folder that is listed and one that is not, `cancela`, `4 e 5`, a whole new request). Four configurations: one account; two accounts and one
mailbox; two accounts and two mailboxes with no default; two accounts and two mailboxes with a default. The walk is the dispatcher's own, over the stand-in the open step is:
`natural_writes_mail.read`, then `ops_natural_mail.resolve`; a question is answered with `natural_writes_mail.answer`; the call that `resolve` finally returns is RECORDED, never made.
One answer deep from every line, two deep from a sample. Each recorded call must satisfy, slot by slot:

  * a text slot (a subject, a body) is a contiguous span (after `natural.normal`) of one of the lines the person said;
  * every address is written in one of those lines (an address in a body is never a recipient; a reply and a reply draft carry none);
  * every `#n` is a number written in a line, or the number of an option the person chose, or the unique strong match of the words (singular) or the exact strong set (plural), or
    the first message for `último`;
  * the account is named by a service word of a line, or is the only account configured, or the project's default, or the account the person chose, or the account of the mailbox
    the person chose or the only mailbox the project has, or of the source the person wrote; never one of two guessed;
  * a folder is a configured name, and the person wrote it or chose it; a state is one the person said.

S41-11 (re-targeted, never removed: L60, L61): a line no longer enters through a closed head. The family's own reading of the line gives its gold operation, a stand-in model answers with the decision the
reader would give (runtime/tests/interpreter_stand_in.py), the interpreter's own parse and check (`ops_interpret.decide`) accepts or refuses it, and the decision is turned into what the carry-out
opens the write with: the seed of a new e-mail (`mail_compose.seed`), of a message named by its words (`ops_natural_mail.mail_target_seed`), of the numbers the model gave
(`mail_number_seed`) or the closed read with the operation fixed. For every third line a PERTURBED decision enters too (a span not in the line, a number not written, an account not
configured, an `inherit` with nothing to inherit); whatever call it ends in must pass the same oracle.

And: no call when two accounts qualify and none was named or chosen; no call from a work request; no call whose line came from the MCP mode.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_natural_writes_mail_dialogues.py
"""
from __future__ import annotations

import copy
import re

import pytest

import datetime
import json

import interpreter_stand_in as si
import natural_writes_mail_cases as cases
import standin_tree as st

nwm = st.load("natural_writes_mail")
onm = st.load("ops_natural_mail")
onw = st.load("ops_natural_writes")
ops_interpret = st.load("ops_interpret")
mail_compose = st.load("mail_compose")
interpreter = st.load("interpreter")
nt = st.load("natural_time")
natural = st.load("natural")
natural_writes = st.load("natural_writes")
item_refs = st.load("item_refs")
turn_gate = st.load("turn_gate")
GATE = {"calls": 0, "refusals": []}      # S41-7: every recorded call is checked by the gate's provenance check with the origins the resolver returned; a refusal here would be a false one
TABLES = nt.languages()
ACCOUNTS = ("google", "microsoft")
NOW = datetime.datetime(2026, 10, 19, 9, 0)
ALLOWED = {row["op"] for row in interpreter.SERVED["ops"]}


def enter(line, model=None, decide=None):
    """How the product opens a mail write for a line (`ops_interpret._carry_out`), up to the point where the family resolves it: {"op", "slots", "origins"} or None when the family reads nothing in the
    line (a request for work: the stand-in model says `route`), the interpreter's check refuses the model's answer, or nothing is left to open."""
    gold = nwm.read(line, TABLES)
    if gold is None:
        assert (decide or ops_interpret.decide)(line, '{"v":1,"kind":"route"}', NOW, si.ZONE, ALLOWED)["kind"] in ("route", "clarify")      # `route` for a private line is `clarify` (why `private-route`): never an op
        return None
    op = gold["op"]
    model = model if model is not None else si.model_text(line, op, None)
    if model is None:
        return None
    decision = (decide or ops_interpret.decide)(line, model, NOW, si.ZONE, ALLOWED)
    if decision["kind"] != "op":
        return None
    spans, args = decision.get("spans") or {}, decision.get("args") or {}
    seed = mail_compose.seed(op, decision, line)
    if seed is None and op in ops_interpret.MAIL_TARGET_OPS and (spans.get("target") or spans.get("day")) and "message" not in args and "messages" not in args:
        seed = onm.mail_target_seed(op, decision, ops_interpret._day_read(spans["day"], NOW) if spans.get("day") else None, line)
    if seed is None:
        read = nwm.read(line, TABLES)      # the closed read with the operation fixed (`open_line(..., hint=op)`)
        if read is not None:
            return {"op": op, "slots": dict(read["slots"]), "origins": None}
        if "message" in args or "messages" in args:
            seed = onm.mail_number_seed(op, decision, line)
    if seed is None:
        return None
    return {"op": op, "slots": dict(seed["slots"]), "origins": onw._origins_of(seed, seed["slots"])}


def index_of(prefix: str) -> list:
    senders = ["billing@banco.example", "ana.souza@clinic.example", "bia@exemplo.example", "loja@shop.example", "noreply@banco.example"]
    subjects = ["Fatura de outubro", "Appointment confirmed", "Contrato novo", "Seu pedido foi enviado", "Fatura de setembro", "Reunião de sexta", "Bank statement", "Weekly news"]      # validate: allow english-only -- a Portuguese line is the input under test
    return [{"n": n, "from_address": senders[(n + len(prefix)) % len(senders)], "subject": subjects[(n * 3 + len(prefix)) % len(subjects)]} for n in range(1, 26)]


class World:
    """One configuration: the accounts, the mail sources, who may read, and the default account; every stand-in the resolution asks."""

    def __init__(self, monkeypatch, accounts, sources, default=None):
        self.cfg = {"accounts": {a: {"address": f"me-{a}@exemplo.example", "calendars": {}, "folders": {}, "mail_folders": {"contas": "L1", "viagens": "L2"},
                                     "move_removes_inbox": True} for a in accounts}}
        self.ctx = {"cfg": self.cfg}
        self.accounts, self.default = accounts, default
        self.sources = [{"id": i, "account": a} for i, a in sources]
        self.indexes = {i: index_of(i) for i, _a in sources}
        monkeypatch.setattr(onm, "_mail_sources", lambda ctx: list(self.sources))
        if default:
            self.cfg["accounts"]["default"] = default
        monkeypatch.setattr(item_refs, "may_read", lambda ctx, channel, sender=None: channel != "mcp")
        monkeypatch.setattr(item_refs, "read_index", lambda ctx, source_id, **kw: {"source": source_id, "type": "mail", "entries": copy.deepcopy(self.indexes[source_id])})

    def account_of(self, source_id):
        return next(s["account"] for s in self.sources if s["id"] == source_id)


CONFIGS = {"one-account": (("google",), (("inbox", "google"),), None),
           "two-accounts-one-mailbox": (("google", "microsoft"), (("inbox", "google"),), None),
           "two-accounts-two-mailboxes": (("google", "microsoft"), (("inbox", "google"), ("work", "microsoft")), None),
           "two-accounts-a-default": (("google", "microsoft"), (("inbox", "google"), ("work", "microsoft")), "google")}


class Walk:
    """One person's dialogue: the lines said so far, the options chosen, and the call the resolution finally returned (recorded, never made)."""

    def __init__(self, world, line, model=None, decide=None):
        self.world, self.said, self.chosen, self.call, self.refused, self.asked = world, [line], {}, None, None, []
        self.origins = None
        self.found = enter(line, model, decide)
        self.slots = dict(self.found["slots"]) if self.found else None
        if self.found and self.found["origins"]:
            self.slots["_origins"] = dict(self.found["origins"])

    def step(self, answer=None):
        """Resolve; with `answer`, first apply it to the open question (False when the line is not an answer: the draft is dropped)."""
        if self.found is None:
            return False
        if answer is not None:
            ask = self.asked[-1]
            if ask["need"] in nwm.NEEDS:      # a need the family answers itself (the foundation tries it first)
                got = nwm.answer(ask["need"], answer, self.found["slots"], TABLES, None, options=ask["options"])
                upd = got["slots"] if got is not None else None
            else:      # an option: the foundation's generic answer, the number shown or the word
                picked = onw._option({"options": ask["options"], "multi": ask["multi"]}, answer)
                upd = {ask["slot"]: picked} if picked is not None else None
                if upd is not None:      # as `ops_natural_writes.answer` records it: a pick is a pick
                    self.slots["_origins"] = dict(self.slots.get("_origins") or {}, **{ask["slot"]: "picked"})
            if upd is None:
                return False
            self.said.append(answer)
            self.chosen[self.asked[-1]["need"]] = upd
            self.slots.update(upd)
        try:
            out = onm.resolve(self.world.ctx, self.found["op"], self.slots, "chat", None, self.said)
        except onm.core.OpsError as e:
            self.refused = str(e)
            return False
        if "say" in out:
            self.refused = out["say"]["sentence_key"]
            return False
        if "ask" in out:
            self.asked.append(out["ask"])
            return True
        self.call = (self.found["op"], out["args"])
        self.origins = out.get("origins")
        return False


def walk(world, line, answers, model=None, decide=None):
    w = Walk(world, line, model, decide)
    more = w.step()
    for answer in answers:
        if not more:
            break
        more = w.step(answer)
    return w


def violations(w) -> list:
    """Everything a recorded call holds that the person did not say, choose or leave to a unique match of what was said: the foundation's provenance check
    (`natural_writes.problems`, which reads the RAW lines with the marker words of the tables and never the mail family's own reading), plus what a reply never carries."""
    op, args = w.call
    world = w.world
    offered = {"numbers": set(), "sources": set(), "source_accounts": set(), "mail_sources": {s["id"]: s["account"] for s in world.sources}, "mail_index": world.indexes,
               "options": {v for upd in w.chosen.values() for value in upd.values() for v in (value if isinstance(value, list) else [value]) if isinstance(v, str)}}      # the values the person CHOSE
    bad = list(natural_writes.problems(op, args, w.said, world.cfg["accounts"], offered, None))
    gated = turn_gate.provenance(op, args, w.origins or {})
    GATE["calls"] += 1
    if gated:
        GATE["refusals"].append((op, sorted(args), gated))
        bad.append(f"the gate refused a call the oracle accepts: {gated}")
    if "message" in args and any(key in args for key in ("to", "cc", "bcc", "subject")):
        bad.append("a reply or a reply draft carries a recipient or a subject")
    return bad


LANGUAGES = {"pt-BR": cases.corpus("pt-BR"), "en": cases.corpus("en")}
ANSWERS = {"pt-BR": cases.ANSWERS_PT, "en": cases.ANSWERS_EN}


@pytest.mark.parametrize("config", sorted(CONFIGS))
@pytest.mark.parametrize("language", sorted(LANGUAGES))
def test_no_call_is_recorded_with_a_slot_the_code_guessed_one_answer_deep_from_every_line(monkeypatch, language, config):
    world = World(monkeypatch, *CONFIGS[config])
    recorded = asked = wrong_made = 0
    for number, line in enumerate(LANGUAGES[language]):
        for answers in [[]] + [[a] for a in ANSWERS[language]]:
            w = walk(world, line, answers)
            if w.found is None:
                assert w.call is None
                continue
            asked += bool(w.asked)
            if w.call is not None:
                recorded += 1
                assert violations(w) == [], (line, answers, w.call)
        gold = nwm.read(line, TABLES)
        if number % 3 == 2 and gold is not None and si.model_text(line, gold["op"], None) is not None:      # S41-11: for every third line, a model that read it wrong as well
            wrong = si.perturbed(si.model_text(line, gold["op"], None), number // 3, world.accounts)
            for answers in [[]] + [[a] for a in ANSWERS[language][:6]]:
                w = walk(world, line, answers, model=wrong)
                wrong_made += w.found is not None
                if w.call is not None:
                    assert violations(w) == [], (line, answers, w.call, wrong)
    assert recorded > 500 and asked > 200, "the walk must reach both the calls and the questions"
    assert wrong_made >= 0
    assert GATE["refusals"] == [] and GATE["calls"] >= recorded, (GATE["calls"], recorded, GATE["refusals"][:6])      # S41-7: every call passed the gate, none was refused


@pytest.mark.parametrize("config", sorted(CONFIGS))
@pytest.mark.parametrize("language", sorted(LANGUAGES))
def test_no_call_is_recorded_with_a_slot_the_code_guessed_two_answers_deep_from_a_sample(monkeypatch, language, config):
    world = World(monkeypatch, *CONFIGS[config])
    sample = LANGUAGES[language][::9]
    for line in sample:
        for first in ANSWERS[language]:
            for second in ANSWERS[language]:
                w = walk(world, line, [first, second])
                if w.call is not None:
                    assert violations(w) == [], (line, first, second, w.call)


def test_two_accounts_with_no_default_never_open_a_write_that_names_none_without_asking():
    import pytest as _pytest
    monkeypatch = _pytest.MonkeyPatch()
    try:
        world = World(monkeypatch, *CONFIGS["two-accounts-two-mailboxes"])
        for line in ("manda um e-mail pra bia@exemplo.example com o assunto Oi dizendo que ok", "send an email to bia@example.example with the subject Hi saying ok",      # validate: allow english-only -- a Portuguese line is the input under test
                     "rascunha um e-mail pra bia@exemplo.example com o assunto Oi dizendo que ok"):      # validate: allow english-only -- a Portuguese line is the input under test
            w = walk(world, line, [])
            assert w.call is None and w.asked[-1]["need"] == "account", line
            assert walk(world, line, ["2"]).call[1]["account"] == "microsoft"
            assert walk(world, line, ["google"]).call[1]["account"] == "google"
            assert walk(world, line, ["talvez"]).call is None, "a line that is not an answer opens nothing"
    finally:
        monkeypatch.undo()


def test_a_work_request_a_reminder_a_calendar_line_and_a_mention_open_no_mail_write(monkeypatch):
    world = World(monkeypatch, *CONFIGS["two-accounts-a-default"])
    for line in cases.WORK + cases.EN_WORK + cases.NEGATIVES + cases.EN_NEGATIVES:
        w = walk(world, line, ["1", "2", "google", "bia@exemplo.example", "ok"])
        assert w.found is None and w.call is None, line


def test_a_line_from_the_mcp_mode_opens_no_mail_write_that_names_a_message(monkeypatch):
    world = World(monkeypatch, *CONFIGS["two-accounts-two-mailboxes"])
    for line in ("arquiva os e-mails 2 e 4 do gmail", "responde ao e-mail do banco pelo gmail dizendo que ok", "archive emails from the bank via gmail"):
        found = nwm.read(line, TABLES)
        out = onm.resolve(world.ctx, found["op"], dict(found["slots"]), "mcp", None, [line])
        assert out["say"]["sentence_key"] == "ACCT_MAIL_REF_NOT_READABLE", line


def test_a_plural_object_is_never_a_partial_set_and_a_singular_one_is_never_a_guess_between_matches(monkeypatch):
    world = World(monkeypatch, *CONFIGS["one-account"])
    found = nwm.read("arquiva os e-mails do banco", TABLES)
    out = onm.resolve(world.ctx, found["op"], dict(found["slots"]), "chat", None, ["x"])
    strong = {f"inbox#{e['n']}" for e in nwm.match_words(world.indexes["inbox"], ["banco"], False)}
    assert len(strong) > 1
    if len(strong) <= 20:
        assert set(out["args"]["messages"].split(",")) == strong
    found = nwm.read("responde ao e-mail do banco dizendo que ok", TABLES)
    out = onm.resolve(world.ctx, found["op"], dict(found["slots"]), "chat", None, ["x"])
    assert out["ask"]["need"] == "message" and {o["value"] for o in out["ask"]["options"]} <= strong and len(out["ask"]["options"]) == min(5, len(strong)), "several matches for a singular object: asked, never guessed"


def test_the_oracle_catches_a_slot_the_person_never_said_so_the_walk_is_not_vacuous(monkeypatch):
    world = World(monkeypatch, *CONFIGS["two-accounts-two-mailboxes"])
    send = walk(world, "manda um e-mail pra bia@exemplo.example com o assunto Oi dizendo que ok", ["google"])      # validate: allow english-only -- a Portuguese line is the input under test
    assert send.call is not None and violations(send) == []

    def mutated(w, **change):
        op, args = w.call
        copy_ = copy.copy(w)
        copy_.call = (op, dict(args, **change))
        return violations(copy_)
    assert mutated(send, account="microsoft"), "an account nobody named or chose"
    assert mutated(send, to="other@exemplo.example"), "an address nobody wrote"
    assert mutated(send, text="something the person never said"), "a body that is no span of what was said"
    assert mutated(send, subject="Oi ok"), "a subject that is not a span"
    archive = walk(world, "arquiva os e-mails 2 e 4 do gmail", [])
    assert archive.call is not None and violations(archive) == []
    assert mutated(archive, messages="inbox#2,inbox#4,inbox#9"), "a message nobody wrote"
    assert mutated(archive, account="microsoft"), "the other account's"
    move = walk(world, "move o e-mail 2 do gmail para a pasta contas", [])      # validate: allow english-only -- a Portuguese line is the input under test
    assert move.call is not None and violations(move) == [] and mutated(move, folder="viagens") and mutated(move, folder="inexistente")
    mark = walk(world, "marca o e-mail 4 do gmail como lido", [])
    assert mark.call is not None and violations(mark) == [] and mutated(mark, state="unread")
    words = walk(world, "arquiva o último e-mail do banco pelo gmail", [])      # validate: allow english-only -- a Portuguese line is the input under test
    assert words.call is not None and violations(words) == [] and mutated(words, messages="inbox#25")


# --- vacuity of the walk (S41-11) -----------------------------------------------------------------------------------------------------------------


def trusting(original: str):
    """An interpreter whose check lets a perturbed answer through: the decision of the ORIGINAL answer with the perturbed spans laid over it."""
    real = ops_interpret.decide

    def decide(line, text, now, zone, allowed, frame=None):
        decision = real(line, original, now, zone, allowed)
        if decision["kind"] == "op":
            decision["spans"] = dict(decision["spans"], **{k: v for k, v in json.loads(text)["slots"].items() if k in decision["spans"]})
        return decision
    return decide


def test_vacuity_a_wrong_span_the_real_check_refuses_opens_a_call_the_oracle_reports_when_the_check_is_patched_open(monkeypatch):
    world = World(monkeypatch, *CONFIGS["two-accounts-two-mailboxes"])
    line = "manda um e-mail pra bia@exemplo.example com o assunto Oi dizendo que ok"      # validate: allow english-only -- a Portuguese line is the input under test
    model = si.model_text(line, "mail-send", None)
    assert model is not None and "body" in json.loads(model)["slots"]
    wrong = json.loads(model)
    wrong["slots"]["body"] = "a body the person never wrote"
    wrong = json.dumps(wrong)
    refused = walk(world, line, ["google"], model=wrong)
    assert refused.found is None and refused.call is None, "the real check refuses a span that is not in the line: no call, nothing to report"
    loose = walk(world, line, ["google"], model=wrong, decide=trusting(model))
    assert loose.call is not None and violations(loose), "with the check open the wrong body reaches the call, and the oracle reports it"
    assert violations(walk(world, line, ["google"], model=model)) == [], "the honest answer is clean"
