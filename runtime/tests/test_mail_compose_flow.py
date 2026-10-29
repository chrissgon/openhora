"""An e-mail asked in free words gets a card with a text the AI wrote (slice S7, runtime/mail_compose.py, limits L55 and L63).

Over the REAL operations layer, the real mail family and the W2 stand-in mailers on loopback (test_send_own_account.py's world: no Google or Microsoft host is called), a
stand-in clock (Wednesday 2026-10-21 10:00 at -03:00), and a stand-in model that answers the interpreter's call and the compose call by hand-written texts and counts
both. Every expectation is a literal of this file: the line, the model's texts, the card's lines. Every name and address is invented (`.example`).

Held here:
  * the line of the live bug opens a send card with the address the sender typed, the stand-in's subject and the stand-in's text, and sends nothing;
  * an address the model invented is never on a card (the family asks for it); a composed text with another address or a link, and a failed call, fall back to the
    person's own words and still open the card; composing is off for a sender without the group `interpret` and when the pinned prompt changed (the interpreter stays on);
  * the same path serves a line in Spanish; the guided dialogue (the family's own questions) words the answer to the body question, and "exact text:" sends it as written;
  * the composed text is kept nowhere but on the card: not in the conversation, not in the draft store, not in a log or on a stream.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_mail_compose_flow.py
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

import phrase_kit as pk
import standin_tree as st
from test_reminders import Clock
from test_send_own_account import ACCOUNTS, CFG, PT, assert_lines, world  # noqa: F401  (the own-account mail world)
from closed_heads import closed_heads, tier1_forms  # noqa: F401  (S41-11: the claim of the write families and of every closed form, as fixtures: these tests are about the readers and resolvers, not the claim)

pytestmark = pytest.mark.usefixtures("tier1_forms")      # S41-11: every closed form claims a line in this file, as it did
# Every pinned hash of the test suite is in scripts/tests/pinned_hashes.json, with what it hashes and why it is pinned.
PINNED_HASHES = json.loads((Path(__file__).resolve().parents[2] / "scripts" / "tests" / "pinned_hashes.json").read_text(encoding="utf-8"))["pins"]

ops = st.load("ops")
ops_core = st.load("ops_core")
ops_interpret = st.load("ops_interpret")
turn_gate = st.load("turn_gate")
ops_natural_writes = st.load("ops_natural_writes")
interpreter_route = st.load("interpreter_route")
mail_compose = st.load("mail_compose")
drafts = st.load("drafts")
phrases = st.load("phrases")

SENDER = "telegram:4242"
BARE = "telegram:5151"
ZONE = "America/Sao_Paulo"
ADDRESS = "joana.silva@clinica.example"
LIVE = "Envie um email para joana.silva@clinica.example. Quero falar de marcar uma reuniao para amanha as 16horas"      # validate: allow english-only -- a Portuguese line is the input under test
SPAN = "Quero falar de marcar uma reuniao para amanha as 16horas"      # validate: allow english-only -- a Portuguese line is the input under test
COMPOSED_SUBJECT = "Reunião amanhã às 16h"      # validate: allow english-only -- the stand-in model's Portuguese answer
COMPOSED_BODY = "Olá,\n\nGostaria de marcar uma reunião amanhã às 16h. Você teria disponibilidade?\n\nObrigado."      # validate: allow english-only -- the stand-in model's Portuguese answer
COMPOSED = json.dumps({"subject": COMPOSED_SUBJECT, "body": COMPOSED_BODY}, ensure_ascii=False)
ZEBRA = "ZEBRA-COMPOSED-TEXT-7731"


def op(name, slots, **more):
    return json.dumps({"v": 1, "kind": "op", "op": name, "slots": slots, **more}, ensure_ascii=False)


LIVE_DECISION = op("mail-send", {"to": ADDRESS, "body": SPAN})


@pytest.fixture
def clock(monkeypatch):
    return Clock(monkeypatch, wall="2026-10-21 10:00")


@pytest.fixture(autouse=True)
def forget():
    drafts.clear()
    ops_interpret.forget_all()
    yield
    drafts.clear()
    ops_interpret.forget_all()


class Model:
    """The stand-in for the daily route: `interpret` and `compose` are the texts (or an exception) it answers; `calls` lists what each call was shown."""

    def __init__(self, monkeypatch, interpret, compose):
        self.interpret, self.compose, self.calls = interpret, compose, []
        monkeypatch.setattr(interpreter_route, "complete", self.complete)
        monkeypatch.setattr(ops_interpret, "_zone", lambda now: ZONE)

    def complete(self, route_id, system, user, **kw):
        kind = "compose" if system == mail_compose.prompt_template() else "interpret"
        self.calls.append({"kind": kind, "route": route_id, "system": system, "user": user, "kw": kw})
        answer = self.compose if kind == "compose" else self.interpret
        if isinstance(answer, Exception):
            raise answer
        if answer is None:
            return {"ok": False, "code": "E_TIMEOUT"}
        return {"ok": True, "text": answer, "finish": "stop", "usage": {}, "latency_ms": 5, "upstream": "deepinfra"}

    def of(self, kind):
        return [c for c in self.calls if c["kind"] == kind]


def setup(world, monkeypatch, interpret=LIVE_DECISION, compose=COMPOSED, groups=("read", "talk", "interpret", "mail-send"), language=None):
    """The project with one account (google), a sender who may ask in words and send mail, one who may not interpret, and the stand-in model."""
    path = Path(world["path"]) / "docs" / "workbench" / "runtime.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["accounts"] = {"google": ACCOUNTS["google"]}
    if language:
        raw["language"] = language
    raw["policies"] = {"owner": list(groups), "bare": ["read", "talk", "mail-send"]}
    raw["channels"] = {"page": ["read"]}
    raw["messaging"] = {"senders": {"telegram": [{"id": "4242", "policy": "owner"}, {"id": "5151", "policy": "bare"}]}}
    path.write_text(json.dumps(raw), encoding="utf-8")
    shown = ops.config(world["path"])
    ops.accept_config(world["path"], shown["sha256"], widen=shown["widening_sha256"])
    return Model(monkeypatch, interpret, compose)


def phone(world, line, sender=SENDER):
    return ops.say(world["path"], line, channel="messaging", sender=sender)


def card(world, out):
    return ops.pending(world["path"], out["resend"])["body"]


def card_lines(world, out):
    return card(world, out).splitlines()


def has(lines, key, cfg=CFG, **fields):
    """True when a line of the card says the sentence of phrase key `key` with `fields`."""
    return pk.said("\n".join(lines), key, cfg, **fields)


def text_of(lines):
    """The person's text on a card: the lines behind the gutter mark between the two frame rules (the only lines that start with five hyphens)."""
    start, end = [i for i, line in enumerate(lines) if line.startswith("-----")]
    return [line[2:] if line.startswith("\u2502 ") else "" for line in lines[start + 1:end]]


def nothing_sent(world):
    assert world["gmail"].requests == [] and world["graph"].requests == []


# --- the live line ---------------------------------------------------------------------------------------------------------------------------------


def test_the_line_of_the_live_bug_opens_a_send_card_with_the_typed_address_and_the_text_the_model_wrote(world, clock, monkeypatch):
    model = setup(world, monkeypatch)
    out = phone(world, LIVE)
    assert out["resend"], out["reply"]
    lines = card_lines(world, out)
    assert_lines(lines[1:4], [("CARD_MAIL_FROM_ACCOUNT", {"address": "pat@example.com", "account": "google"}), ("CARD_MAIL_TO", {"addresses": ADDRESS}), ("CARD_MAIL_SUBJECT", {"subject": COMPOSED_SUBJECT})])
    assert text_of(lines) == ["Olá,", "", "Gostaria de marcar uma reunião amanhã às 16h. Você teria disponibilidade?", "", "Obrigado."]      # validate: allow english-only -- the stand-in model's answer
    assert [c["kind"] for c in model.calls] == ["interpret", "compose"]
    assert model.of("compose")[0]["user"] == f"date: 2026-10-21 Wed\nlanguage: en\nto: {ADDRESS}\nsubject: \ndescription: {SPAN}"
    assert model.of("compose")[0]["kw"]["deadline_ms"] == 6000 and model.of("compose")[0]["route"] == "or-deepseek-v4.1-flash"
    nothing_sent(world)


def test_the_card_is_opened_and_never_sent_by_this_path(world, clock, monkeypatch):
    setup(world, monkeypatch)
    out = phone(world, LIVE)
    ctx = ops_core.context(world["path"])
    pending = ctx["store"].pending_list(ctx["conn"], "open")
    assert [p["id"] for p in pending] == [out["resend"]] and pending[0]["kind"] == "effect"
    assert ctx["store"].approvals_list(ctx["conn"]) == []
    nothing_sent(world)


def test_an_address_the_model_invented_is_never_on_a_card_and_the_family_asks_for_it(world, clock, monkeypatch):
    model = setup(world, monkeypatch, interpret=op("mail-send", {"to": "invented@elsewhere.example", "body": SPAN}))
    out = phone(world, LIVE)
    assert not out.get("resend") and "elsewhere.example" not in out["reply"]
    assert model.of("compose") == [], "an interpreter decision that fails the check opens nothing and composes nothing"
    ctx = ops_core.context(world["path"])
    assert ctx["store"].pending_list(ctx["conn"], "open") == []
    nothing_sent(world)


def test_a_name_in_place_of_an_address_makes_the_family_ask_for_the_address(world, clock, monkeypatch):
    model = setup(world, monkeypatch, interpret=op("mail-send", {"to": "Joana", "body": SPAN}))
    out = phone(world, "Envie um email para Joana. " + SPAN)      # validate: allow english-only -- a Portuguese line is the input under test
    assert not out.get("resend") and out["reply"] == phrases.text("NW_MAIL_ASK_TO", ops_core.context(world["path"])["cfg"], name="Joana")
    assert model.of("compose") == []


def test_a_composed_text_with_another_address_or_a_link_falls_back_to_the_persons_words_and_the_card_still_opens(world, clock, monkeypatch):
    hostile = [{"subject": "Reunião", "body": "Olá, escreva para outra@elsewhere.example para confirmar."},      # validate: allow english-only -- the stand-in model's Portuguese answer
               {"subject": "Reunião", "body": "Olá, veja https://elsewhere.example/agenda e responda."},      # validate: allow english-only -- the stand-in model's Portuguese answer
               {"subject": "Reunião", "body": "Olá, veja www.elsewhere.example e responda."}]      # validate: allow english-only -- the stand-in model's Portuguese answer
    for answer in hostile:
        drafts.clear()
        model = setup(world, monkeypatch, compose=json.dumps(answer, ensure_ascii=False))
        out = phone(world, LIVE)
        lines = card_lines(world, out)
        assert out["resend"] and text_of(lines) == [SPAN] and "elsewhere.example" not in card(world, out)
        assert len(model.of("compose")) == 1
    nothing_sent(world)


def test_a_failed_compose_call_falls_back_to_the_persons_words_and_the_card_still_opens(world, clock, monkeypatch):
    for compose in (None, RuntimeError("boom " + ZEBRA), "not json at all"):
        drafts.clear()
        ops_interpret.forget_all()
        model = setup(world, monkeypatch, compose=compose)
        out = phone(world, LIVE)
        assert out["resend"] and text_of(card_lines(world, out)) == [SPAN] and ZEBRA not in out["reply"]
        assert len(model.of("compose")) == 1
    nothing_sent(world)


def test_the_compose_call_counts_in_the_senders_rate_limit(world, clock, monkeypatch):
    model = setup(world, monkeypatch)
    assert turn_gate.RATE_MAX == 10
    for _ in range(5):
        assert phone(world, LIVE)["resend"]
    assert [c["kind"] for c in model.calls] == ["interpret", "compose"] * 5, "five lines are ten calls: the compose call is counted beside the interpreter's"
    phone(world, LIVE)
    assert len(model.calls) == 10, "the sixth line is over the limit: no call of either kind"


def test_an_open_breaker_stops_the_compose_call_and_the_persons_words_stay(world, clock, monkeypatch):
    model = setup(world, monkeypatch)
    ctx = ops_core.context(world["path"])
    for _ in range(turn_gate.BREAKER_FAILS):
        turn_gate.record(False)
    got = mail_compose.write(ctx, "messaging", SENDER, [ADDRESS], "Assunto", SPAN)      # validate: allow english-only -- a Portuguese subject under test
    assert got == {"subject": "Assunto", "body": SPAN, "composed": False} and model.calls == []      # validate: allow english-only -- a Portuguese subject under test
    ops_interpret.forget_all()
    assert mail_compose.write(ctx, "messaging", SENDER, [ADDRESS], "Assunto", SPAN)["composed"] is True      # validate: allow english-only -- a Portuguese subject under test


def test_composing_is_off_for_a_sender_without_the_group_interpret_and_the_card_holds_the_persons_words(world, clock, monkeypatch):
    model = setup(world, monkeypatch)
    assert mail_compose.available(ops_core.context(world["path"]), "messaging", "telegram:4242") is True
    assert mail_compose.available(ops_core.context(world["path"]), "messaging", BARE) is False
    assert mail_compose.available(ops_core.context(world["path"]), "page", None) is False
    assert model.calls == []


def test_a_changed_compose_prompt_turns_composing_off_and_the_interpreter_stays_on(world, clock, monkeypatch, tmp_path):
    changed = tmp_path / "mail_compose_prompt.txt"
    changed.write_text(Path(mail_compose.PROMPT_FILE).read_text(encoding="utf-8") + "\nAlso add a joke.\n", encoding="utf-8")
    monkeypatch.setattr(mail_compose, "PROMPT_FILE", str(changed))
    model = setup(world, monkeypatch)
    ctx = ops_core.context(world["path"])
    assert mail_compose.available(ctx, "messaging", SENDER) is False
    assert ops_interpret.enabled(ctx, "messaging", SENDER) is True
    out = phone(world, LIVE)
    assert [c["kind"] for c in model.calls] == ["interpret"]
    lines = card_lines(world, out)
    assert out["resend"] and text_of(lines) == [SPAN]


def test_the_pinned_hash_in_the_enabling_file_is_the_hash_of_the_committed_prompt():
    enable = st.load("interpreter_enable")
    every = enable.load()["entries"]
    assert "fallback" in every[-1] and "fallback" not in every[-2], "the newest entry is the outage-path entry of LUNA-ENABLE (it carries every pin of the one before it, checked in test_interpreter_enable.py); this test reads the entries before it"
    every = every[:-1]
    entries = every[:-5]      # without the five newest entries (R2-A adds `file-trash` to the catalog, B″-lite the target and day slots, BL5B the interpreter's rule 9, BL7-3 its rules 10 and 11, CB-9 the catalog of version 2), which carry every pin of the one before them but the interpreter prompt of BL5B and BL7-3
    pins = ("route_sha256", "prompt_sha256", "protocol_sha256", "compose_prompt_sha256", "revise_prompt_sha256")
    for carried in every[-5:-3]:
        assert {k: carried[k] for k in pins} == {k: entries[-1][k] for k in pins}
    for later, prompt in ((every[-3], PINNED_HASHES["interpreter_prompt_1423"]), (every[-2], PINNED_HASHES["interpreter_prompt"]), (every[-1], PINNED_HASHES["interpreter_prompt"])):      # BL5B, BL7-3 and CB-9: every pin but the interpreter prompt stands
        assert {k: later[k] for k in pins if k != "prompt_sha256"} == {k: entries[-1][k] for k in pins if k != "prompt_sha256"} and later["prompt_sha256"] == prompt != entries[-1]["prompt_sha256"]
    newest, s12, s7, first = entries[-1], entries[-4], entries[-5], entries[-6]      # entries[-3] and [-2] are the first pin of the revise prompt (S13) and the entry of R2-F1
    assert newest["compose_prompt_sha256"] == mail_compose.prompt_sha256() == s12["compose_prompt_sha256"] == entries[-2]["compose_prompt_sha256"] == entries[-3]["compose_prompt_sha256"]      # the decisions after S12 carry its compose pin
    assert s12["date"] == "2026-10-22" and s12["basis"] == "maintainer-decision" and "a IA deve verificar a ortografia do assunto do email" in s12["reason"]
    assert s7["date"] == "2026-10-21" and "para emails eu iria pedir para a IA criar um texto melhor escrito" in s7["reason"], "the entry of the first compose prompt stays"
    assert s7["compose_prompt_sha256"] == PINNED_HASHES["compose_prompt_s7"] and s7["compose_prompt_sha256"] != newest["compose_prompt_sha256"]
    assert {k: s12[k] for k in enable.HASH_KEYS} == {k: s7[k] for k in enable.HASH_KEYS} == {k: first[k] for k in enable.HASH_KEYS}, "every hash of the earlier decisions stands"
    assert {k: newest[k] for k in enable.HASH_KEYS if k != "catalog_sha256"} == {k: s12[k] for k in enable.HASH_KEYS if k != "catalog_sha256"}, "and so does every one of the newest but the catalog, which R2-F1 changed"
    assert "compose_prompt_sha256" not in first and "revise_prompt_sha256" in newest and "revise_prompt_sha256" not in s12


def test_a_line_in_spanish_gets_a_card_by_the_same_path(world, clock, monkeypatch):
    line = "Manda un correo a joana.silva@clinica.example. Quiero hablar de una reunion para manana a las 16"      # validate: allow english-only -- a Spanish line is the input under test
    span = "Quiero hablar de una reunion para manana a las 16"      # validate: allow english-only -- a Spanish line is the input under test
    model = setup(world, monkeypatch, interpret=op("mail-send", {"to": ADDRESS, "body": span}))
    out = phone(world, line)
    assert out["resend"] and f"To: {ADDRESS}" in card_lines(world, out)
    assert text_of(card_lines(world, out))[0] == "Olá,"      # validate: allow english-only -- the stand-in model's Portuguese answer
    assert model.of("compose")[0]["user"].splitlines()[3:] == ["subject: ", "description: " + span]
    nothing_sent(world)


def test_a_subject_the_person_gave_is_kept_as_written_and_only_the_body_is_worded(world, clock, monkeypatch):
    model = setup(world, monkeypatch, interpret=op("mail-send", {"to": ADDRESS, "subject": "Reuniao de amanha", "body": SPAN}))      # validate: allow english-only -- a Portuguese line is the input under test
    line = "Envie um email para joana.silva@clinica.example, Reuniao de amanha. " + SPAN      # validate: allow english-only -- a Portuguese line is the input under test
    out = phone(world, line)
    lines = card_lines(world, out)
    assert out["resend"] and has(lines, "CARD_MAIL_SUBJECT", subject="Reuniao de amanha") and not has(lines, "CARD_MAIL_SUBJECT", subject=COMPOSED_SUBJECT)
    assert text_of(lines)[0] == "Olá,"      # validate: allow english-only -- the stand-in model's Portuguese answer
    assert model.of("compose")[0]["user"].splitlines()[3] == "subject: Reuniao de amanha"      # validate: allow english-only -- a Portuguese line is the input under test


# --- the spelling of the subject and the end of the body (S12) ------------------------------------------------------------------------------------


TYPED_SUBJECT = "Reuniao sobre o Openhora"      # validate: allow english-only -- the live subject typed without its accent
TYPED_LINE = "Envie um email para joana.silva@clinica.example, " + TYPED_SUBJECT + ". " + SPAN      # validate: allow english-only -- a Portuguese line is the input under test


def with_subject_typed(world, monkeypatch, composed_subject, body=COMPOSED_BODY):
    compose = json.dumps({"subject": composed_subject, "body": body}, ensure_ascii=False)
    return setup(world, monkeypatch, interpret=op("mail-send", {"to": ADDRESS, "subject": TYPED_SUBJECT, "body": SPAN}), compose=compose)


def test_the_model_may_fix_the_spelling_of_the_typed_subject_and_the_card_shows_the_fixed_one(world, clock, monkeypatch):
    model = with_subject_typed(world, monkeypatch, "Reunião sobre o Openhora")      # validate: allow english-only -- the stand-in model's Portuguese answer
    out = phone(world, TYPED_LINE)
    lines = card_lines(world, out)
    assert out["resend"] and pk.said(lines[3], "CARD_MAIL_SUBJECT", CFG, subject="Reunião sobre o Openhora")      # validate: allow english-only -- the stand-in model's Portuguese answer
    assert model.of("compose")[0]["user"].splitlines()[3] == "subject: " + TYPED_SUBJECT
    nothing_sent(world)


@pytest.mark.parametrize("composed", ["Convite para reunião", "Reunião Openhora", "Reunião sobre o Openhora amanhã", "Reunião sobre o Openhora https://elsewhere.example"])      # validate: allow english-only -- the stand-in model's Portuguese answers
def test_a_model_subject_that_is_not_the_same_subject_with_its_spelling_fixed_leaves_the_typed_one_on_the_card(world, clock, monkeypatch, composed):
    with_subject_typed(world, monkeypatch, composed)
    out = phone(world, TYPED_LINE)
    lines = card_lines(world, out)
    assert out["resend"] and pk.said(lines[3], "CARD_MAIL_SUBJECT", CFG, subject=TYPED_SUBJECT) and text_of(lines)[0] == "Olá,"      # validate: allow english-only -- the stand-in model's Portuguese answer


def test_a_model_subject_with_one_word_that_fails_the_rule_still_fixes_the_accents_of_the_others_on_the_card(world, clock, monkeypatch):
    with_subject_typed(world, monkeypatch, "Reunião sobre o OpenHora")      # validate: allow english-only -- the stand-in model's Portuguese answer
    out = phone(world, TYPED_LINE)
    lines = card_lines(world, out)
    assert out["resend"] and pk.said(lines[3], "CARD_MAIL_SUBJECT", CFG, subject="Reunião sobre o Openhora") and text_of(lines)[0] == "Olá,"      # validate: allow english-only -- the stand-in model's Portuguese answer


def test_a_composed_body_that_ends_with_a_closing_formula_alone_is_shown_without_it(world, clock, monkeypatch):
    with_subject_typed(world, monkeypatch, "Reunião sobre o Openhora", body="Olá,\n\nGostaria de marcar uma reunião amanhã às 16h.\n\nAtenciosamente,")      # validate: allow english-only -- the stand-in model's Portuguese answer
    out = phone(world, TYPED_LINE)
    lines = card_lines(world, out)
    assert out["resend"] and text_of(lines) == ["Olá,", "", "Gostaria de marcar uma reunião amanhã às 16h."] and "Atenciosamente" not in card(world, out)      # validate: allow english-only -- the stand-in model's Portuguese answer


def test_a_stand_in_that_accents_what_was_typed_without_accents_reaches_the_card_and_the_prompt_asks_for_it(world, clock, monkeypatch):
    typed = "Perguntar se voce pode fazer a reuniao amanha as 16hrs"      # validate: allow english-only -- a Portuguese description typed without accents
    body = "Olá,\n\nVocê pode fazer a reunião amanhã às 16h?\n\nObrigado."      # validate: allow english-only -- the stand-in model's Portuguese answer
    model = setup(world, monkeypatch, interpret=op("mail-send", {"to": ADDRESS, "body": typed}), compose=json.dumps({"subject": "Reunião amanhã", "body": body}, ensure_ascii=False))      # validate: allow english-only -- the stand-in model's Portuguese answer
    out = phone(world, "Envie um email para joana.silva@clinica.example. " + typed)      # validate: allow english-only -- a Portuguese line is the input under test
    assert text_of(card_lines(world, out)) == body.split("\n") and "voce" not in card(world, out)
    call = model.of("compose")[0]
    assert call["user"].splitlines()[-1] == "description: " + typed and call["system"] == mail_compose.prompt_template()
    assert "Write the subject and the body with the correct spelling, accents and punctuation of that language" in call["system"]
    assert "the person's typing is not the spelling to copy" in call["system"]


# --- the guided dialogue ---------------------------------------------------------------------------------------------------------------------------


SUBJECT_TYPED = "Reunião sobre Openhora"      # validate: allow english-only -- a Portuguese subject under test


def guided(world, monkeypatch, compose=COMPOSED):
    """S41-11: the interpreter names the send with the address and the subject the person wrote and no body: the dialogue asks the body (the exact-text marker is offered)."""
    model = setup(world, monkeypatch, interpret=op("mail-send", {"to": ADDRESS, "subject": SUBJECT_TYPED}), compose=compose, language="pt-BR")
    first = phone(world, "Envie um email para joana.silva@clinica.example assunto " + SUBJECT_TYPED)      # validate: allow english-only -- a Portuguese line is the input under test
    assert not first.get("resend") and "\n" not in first["reply"] and first["reply"] == phrases.text("MC_ASK_BODY", ops_core.context(world["path"])["cfg"], to=ADDRESS), first["reply"]
    return model


def test_the_guided_dialogue_words_the_answer_to_the_body_question_and_the_card_shows_the_text(world, clock, monkeypatch):
    model = guided(world, monkeypatch)
    cfg = ops_core.context(world["path"])["cfg"]
    assert "exact" in phrases.text("MC_ASK_BODY", {"language": "en"}, to="x")
    description = "Perguntar a disponibilidade de uma call amanha as 16hrs, para falarmos sobre o openhora"      # validate: allow english-only -- a Portuguese answer under test
    out = phone(world, description)
    lines = card_lines(world, out)
    assert out["resend"] and has(lines, "CARD_MAIL_SUBJECT", subject="Reunião sobre Openhora")      # validate: allow english-only -- a Portuguese answer under test
    assert text_of(lines) == ["Olá,", "", "Gostaria de marcar uma reunião amanhã às 16h. Você teria disponibilidade?", "", "Obrigado."]      # validate: allow english-only -- the stand-in model's answer
    assert model.of("compose")[0]["user"].splitlines()[-2:] == ["subject: Reunião sobre Openhora", "description: " + description]      # validate: allow english-only -- a Portuguese answer under test
    nothing_sent(world)


def test_the_marker_exact_text_sends_the_answer_as_written_with_no_model_call(world, clock, monkeypatch):
    model = guided(world, monkeypatch)
    out = phone(world, "texto exato: Oi Joana, amanhã às 16h. Pode?")      # validate: allow english-only -- a Portuguese answer under test
    assert out["resend"] and text_of(card_lines(world, out)) == ["Oi Joana, amanhã às 16h. Pode?"]      # validate: allow english-only -- a Portuguese answer under test
    assert model.of("compose") == []


def test_a_failed_compose_in_the_guided_dialogue_sends_the_answer_as_written(world, clock, monkeypatch):
    model = guided(world, monkeypatch, compose=None)
    out = phone(world, "Perguntar a disponibilidade de uma call amanha as 16hrs")      # validate: allow english-only -- a Portuguese answer under test
    assert out["resend"] and text_of(card_lines(world, out)) == ["Perguntar a disponibilidade de uma call amanha as 16hrs"]      # validate: allow english-only -- a Portuguese answer under test
    assert len(model.of("compose")) == 1


# --- what is kept ------------------------------------------------------------------------------------------------------------------------------


def test_the_composed_text_is_kept_nowhere_but_on_the_card(world, clock, monkeypatch, caplog, capsys):
    marked = json.dumps({"subject": "Assunto " + ZEBRA, "body": "Olá,\n\nTexto " + ZEBRA + " aqui.\n\nObrigado."}, ensure_ascii=False)      # validate: allow english-only -- the stand-in model's Portuguese answer
    setup(world, monkeypatch, compose=marked)
    with caplog.at_level(logging.DEBUG):
        out = phone(world, LIVE)
    assert out["resend"] and ZEBRA in card(world, out), "the card holds the whole text"
    assert ZEBRA not in out["reply"]
    ctx = ops_core.context(world["path"])
    stored = ctx["store"].messages_list(ctx["conn"], ops.CONVERSATION, limit=500)
    assert ZEBRA not in json.dumps(stored, ensure_ascii=False) and SPAN not in json.dumps(stored, ensure_ascii=False), "the conversation keeps a neutral word"
    assert drafts.get(*ops_natural_writes._slot("messaging", SENDER), "write") is None
    seen = capsys.readouterr()
    assert ZEBRA not in seen.out + seen.err + caplog.text


def test_the_card_a_pt_br_project_shows_has_the_typed_address_the_subject_and_the_whole_text(world, clock, monkeypatch):
    setup(world, monkeypatch, language="pt-BR")
    out = phone(world, LIVE)
    item = ops.pending(world["path"], out["resend"])
    shown = phrases.card_text(item["payload"]["card"], ops_core.context(world["path"])["cfg"]).splitlines()
    assert "\n" not in out["reply"] and pk.said(out["reply"], "ACCT_CARD_SENT", PT, pending=1), out["reply"]
    assert_lines(shown[1:4], [("CARD_MAIL_FROM_ACCOUNT", {"address": "pat@example.com", "account": "google"}), ("CARD_MAIL_TO", {"addresses": ADDRESS}), ("CARD_MAIL_SUBJECT", {"subject": COMPOSED_SUBJECT})], PT)
    assert text_of(shown)[0] == "Olá," and "Gostaria de marcar uma reunião amanhã às 16h. Você teria disponibilidade?" in text_of(shown)      # validate: allow english-only -- the Portuguese card under test


def test_vacuity_a_validator_that_accepts_everything_puts_the_foreign_link_on_the_card(world, clock, monkeypatch):
    hostile = json.dumps({"subject": "Reunião", "body": "Olá, veja https://elsewhere.example/agenda."}, ensure_ascii=False)      # validate: allow english-only -- the stand-in model's Portuguese answer
    setup(world, monkeypatch, compose=hostile)
    monkeypatch.setattr(mail_compose, "validate", lambda text, to, subject=None: json.loads(text))
    out = phone(world, LIVE)
    assert "elsewhere.example" in card(world, out), "the oracle of the hostile test sees a planted wrong result"


def test_a_sender_without_the_group_interpret_who_asks_for_a_mail_in_words_gets_the_typed_sentence_and_no_model_call(world, clock, monkeypatch):
    """S41-11 (the maintainer, 2026-10-28): the guided dialogue of a closed form is gone with the claim; a sender the interpreter does not read gets the typed-command sentence, and no model is asked."""
    model = setup(world, monkeypatch, language="pt-BR")
    out = phone(world, "Envie um email para joana.silva@clinica.example", sender=BARE)
    cfg = ops_core.context(world["path"])["cfg"]
    assert out["reply"] == phrases.text("IX_TYPE_WRITE", cfg)
    assert model.calls == [] and not out.get("resend")


def test_the_marker_with_nothing_after_it_asks_the_body_again_and_opens_no_card(world, clock, monkeypatch):
    model = guided(world, monkeypatch)
    out = phone(world, "texto exato:")      # validate: allow english-only -- a Portuguese answer under test
    assert not out.get("resend") and out["reply"] == phrases.text("MC_ASK_BODY", ops_core.context(world["path"])["cfg"], to=ADDRESS) and model.of("compose") == []
