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

And: no call when two accounts qualify and none was named or chosen; no call from a work request; no call whose line came from the MCP mode.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_natural_writes_mail_dialogues.py
"""
from __future__ import annotations

import copy
import re

import pytest

import natural_writes_mail_cases as cases
import standin_tree as st

nwm = st.load("natural_writes_mail")
onm = st.load("ops_natural_mail")
onw = st.load("ops_natural_writes")
nt = st.load("natural_time")
natural = st.load("natural")
item_refs = st.load("item_refs")
TABLES = nt.languages()
ACCOUNTS = ("google", "microsoft")
SERVICES = {a: {tuple(p.split()) for p in phrases} for table in TABLES for a, phrases in table["requests"]["writes"]["services"].items()}


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


def normal(text) -> str:
    return natural.normal(text)


def says_account(said, account) -> bool:
    for line in said:
        toks = [t.norm for t in nwm.tokenize(line) or []]
        for phrase in SERVICES[account]:
            n = len(phrase)
            if any(tuple(toks[i:i + n]) == phrase for i in range(len(toks) - n + 1)):
                return True
    return False


def written_numbers(line: str) -> set:
    """The numbers a line writes: its digit groups, and every number between two digit groups joined by a range word (`1 a 3`, `1 to 3`, `1-3`)."""
    out = {int(n) for n in re.findall(r"[0-9]{1,9}", line)}
    for a, b in re.findall(r"([0-9]{1,9})\s*(?:-|a|ate|até|to|through)\s*([0-9]{1,9})", line):
        out |= set(range(int(a), int(b) + 1)) if int(a) <= int(b) <= int(a) + 40 else set()
    return out


def says_state(said, state) -> bool:
    for line in said:
        got = (nwm.answer("state", line, {}, TABLES) or {}).get("slots")
        found = nwm.read(line, TABLES)
        if (got and got["state"] == state) or (found and found["slots"].get("state") == state):
            return True
    return False


class Walk:
    """One person's dialogue: the lines said so far, the options chosen, and the call the resolution finally returned (recorded, never made)."""

    def __init__(self, world, line):
        self.world, self.said, self.chosen, self.call, self.refused, self.asked = world, [line], {}, None, None, []
        self.found = nwm.read(line, TABLES)
        self.slots = dict(self.found["slots"]) if self.found else None

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
        return False


def walk(world, line, answers):
    w = Walk(world, line)
    more = w.step()
    for answer in answers:
        if not more:
            break
        more = w.step(answer)
    return w


def violations(w) -> list:
    """Everything a recorded call holds that the person did not say, choose or leave to a unique match of what was said."""
    op, args = w.call
    world, said, found = w.world, w.said, w.found
    bad = []
    joined = [normal(line) for line in said]

    def span(text):
        return any(normal(text) in line for line in joined)
    for name in ("subject", "text", "body"):
        if name in args and not span(args[name]):
            bad.append(f"{name} {args[name]!r} is no span of what was said")
    if "to" in args:
        for address in args["to"].split(","):
            if not any(address.lower() in line.lower() for line in said):
                bad.append(f"address {address} was never written")
    if op in ("mail-reply",) or "message" in args:
        if "to" in args or "cc" in args or "bcc" in args or "subject" in args:
            bad.append("a reply or a reply draft carries a recipient or a subject")
    refs = args["messages"].split(",") if "messages" in args else [args["message"]] if "message" in args else []
    words = found["slots"].get("words")
    for ref in refs:
        source, _hash, number = ref.partition("#")
        number = int(number)
        written = any(number in written_numbers(line) for line in said) or any(ref in line.replace(",", " ").split() for line in said)
        strong = [e["n"] for e in nwm.match_words(world.indexes[source], words, False)] if words else []
        first = found["slots"].get("newest") and number == 1 and not words
        newest = found["slots"].get("newest") and words and strong and number == strong[0]
        by_words = number in strong and (found["slots"].get("plural") and not found["slots"].get("newest") and len(strong) <= 20 or len(strong) == 1)
        picked = (w.chosen.get("message") or {}).get("chosen") or []
        chosen = ref in ([picked] if isinstance(picked, str) else picked)
        if not (written or first or newest or by_words or chosen):
            bad.append(f"{ref} was neither written, chosen nor the unique match")
        if source not in {s["id"] for s in world.sources}:
            bad.append(f"{source} is no mailbox")
    if words and found["slots"].get("plural") and not found["slots"].get("newest") and refs and not w.chosen.get("message"):
        strong = {f"{r.partition('#')[0]}#{e['n']}" for r in refs[:1] for e in nwm.match_words(world.indexes[r.partition('#')[0]], words, False)}
        if set(refs) != strong:
            bad.append("a plural object by words is exactly the strong set")
    account = args.get("account")
    if account not in ACCOUNTS:
        bad.append(f"account {account!r}")
    else:
        named = says_account(said[:1], account) and not any(says_account(said[:1], a) for a in ACCOUNTS if a != account)      # a service word of the LINE, not of an answer that is a subject or a body
        only = world.accounts == (account,)
        default = world.default == account
        chose = (w.chosen.get("account") or {}).get("account") == account
        via_source = refs and all(world.account_of(r.partition("#")[0]) == account for r in refs) and (
            len(world.sources) == 1 or (w.chosen.get("source") or w.chosen.get("message") or any(r.partition("#")[0] + "#" in " ".join(said) for r in refs))
            or len([s for s in world.sources if s["account"] == account]) == 1 and (says_account(said, account)))
        if not (named or only or default or chose or via_source):
            bad.append(f"the account {account} was not named, chosen, the only one, the default or the account of the mailbox")
    if "folder" in args:
        folded = {normal(n): n for n in ("contas", "viagens")}
        if args["folder"] not in folded.values():
            bad.append("a folder the project does not list")
        written = any(normal(args["folder"]) in line for line in joined)
        if not (written or (w.chosen.get("folder") or {}).get("folder_name") == args["folder"]):
            bad.append("a folder nobody wrote or chose")
    if "state" in args and not (says_state(said, args["state"]) or (w.chosen.get("state") or {}).get("state") == args["state"]):
        bad.append("a state nobody said")
    return bad


LANGUAGES = {"pt-BR": cases.corpus("pt-BR"), "en": cases.corpus("en")}
ANSWERS = {"pt-BR": cases.ANSWERS_PT, "en": cases.ANSWERS_EN}


@pytest.mark.parametrize("config", sorted(CONFIGS))
@pytest.mark.parametrize("language", sorted(LANGUAGES))
def test_no_call_is_recorded_with_a_slot_the_code_guessed_one_answer_deep_from_every_line(monkeypatch, language, config):
    world = World(monkeypatch, *CONFIGS[config])
    recorded = asked = 0
    for line in LANGUAGES[language]:
        for answers in [[]] + [[a] for a in ANSWERS[language]]:
            w = walk(world, line, answers)
            if w.found is None:
                assert w.call is None
                continue
            asked += bool(w.asked)
            if w.call is not None:
                recorded += 1
                assert violations(w) == [], (line, answers, w.call)
    assert recorded > 500 and asked > 200, "the walk must reach both the calls and the questions"


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
