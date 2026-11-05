"""A long sender-and-subject target is grounded (package BL7-5, gap G3; limits L54, L60, L61, L63).

A mail `target` the model gave with a sender and a subject ("Nadia Ferreira about the volunteer schedule for the book fair") has more than `TARGET_WORDS_MAX` (6) content words, so the
product gave it no seed and said `IX_CANNOT_WRITE`. Now the check grounds such a target by the sender and the subject without the marker word (`interpreter._own_subject_ground`), recorded as
`target_ground` (and `target_sender`, the person's part), and the seed reads up to `GROUND_WORDS_MAX` (10) content words with `natural_writes_mail.ground_words`. `match_words` still requires
EVERY word, so the ground only decides between a search and a refusal and never reaches a message with fewer of the target's words.

Held here, every expectation a literal of this file (invented names, `.example` addresses, non-ASCII as `\\u` escapes):
  * `_own_subject_ground` / `_own_subject_split`: the four targets of the blind set and the cases that get none (a marker first or last, a target that is grounded today, a ground of more than
    ten content words, a line with no marker);
  * `target_words` with no `cap`: byte-identical outputs on a list of targets recorded on the base before the change (CB-1, CB-3 and BL7-1 rely on it); `ground_words` keeps up to ten;
  * `interpreter.check` on the recorded answers of the blind set: `target_ground` and `target_sender` are the literals; a target of five words with a marker has none;
  * the product's own turn: a card for the planted match, `NW_MAIL_NONE` for the miss, a plural archive that takes only the message that holds every word;
  * vacuity: `GROUND_WORDS_MAX` patched to 6 fails the card rows, and `match_words` patched to "any one word" makes the plural row take both messages.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_mail_long_target.py
"""
from __future__ import annotations

import json

import pytest

import interpreter_kit as kit
import standin_tree as st
import test_sources_mail as tsm
from test_mail_compose_flow import setup, phone, op, clock, forget  # noqa: F401  (the mail desk world, the stand-in model, the clock)
from test_send_own_account import world  # noqa: F401

interp = st.load("interpreter")
nwm = st.load("natural_writes_mail")
natural = st.load("natural")
ops_natural_mail = st.load("ops_natural_mail")
ops_core = st.load("ops_core")
phrases = st.load("phrases")

TABLES = natural._tables(None)

# The four targets of the blind set, each with the ground code gives it and the person's part (the lines are the person's, the targets are what the model gave).
BLIND = (
    ("Nadia Ferreira about the volunteer schedule for the book fair", "Nadia Ferreira", "Nadia Ferreira the volunteer schedule for the book fair"),
    ("Priya's note about the thing with the broken projector in room B", "Priya's note", "Priya's note the thing with the broken projector in room B"),
    ("Teodoro, da Vela Azul Contabilidade, sobre a papelada do imposto de renda", "Teodoro, da Vela Azul Contabilidade,", "Teodoro, da Vela Azul Contabilidade, a papelada do imposto de renda"),
    ("Caio Fontana sobre o convite pra palestrar no congresso de logística", "Caio Fontana", "Caio Fontana o convite pra palestrar no congresso de logística"),      # validate: allow english-only -- a Portuguese line or word is the input under test
    ("Mei Su about the volunteer schedule for the book fair", "Mei Su", "Mei Su the volunteer schedule for the book fair"),          # "su" is a marker of another language and a name: the marker that follows it is the subject's
    ("Lia Sur regarding the quarterly budget review with the board", "Lia Sur", "Lia Sur the quarterly budget review with the board"),          # so is "sur"
)
NO_GROUND = (
    "Marta Siqueira sobre o reembolso da viagem a Curitiba",          # five content words today: seeded as it was, no ground
    "the volunteer schedule for the book fair and the lunch menu too",          # no subject marker
    "about the volunteer schedule for the book fair and the lunch menu too",          # the marker comes first: no person
    "Nadia Ferreira about",          # the marker is the last word: no subject
    "Nadia Ferreira about the volunteer schedule for the book fair and the lunch menu on tuesday of next week ok",          # a ground of more than ten content words
    "",
    "... about the volunteer schedule for the book fair please",          # the part before the marker holds no letter or digit
)


@pytest.mark.parametrize("target, person, ground", BLIND, ids=[row[1] for row in BLIND])
def test_the_blind_targets_get_the_person_and_the_subject_without_the_marker_word(target, person, ground):
    assert interp._own_subject_ground(target) == ground
    assert interp._own_subject_split(target) == (person, ground)


@pytest.mark.parametrize("target", NO_GROUND)
def test_a_target_that_is_seeded_today_or_has_no_subject_gets_no_ground(target):
    assert interp._own_subject_ground(target) is None and interp._own_subject_split(target) is None


def test_the_ground_is_made_of_the_targets_own_words_in_order():
    for target, _person, ground in BLIND:
        words = ground.split()
        position = 0
        for word in words:
            position = target.index(word, position) + len(word)          # every word of the ground is a word of the target, in the target's order


# --- target_words with no cap -------------------------------------------------------------------------------------------------------------------

# The outputs recorded on the base (feature/delegation-platform at 7c142392) before the change: the contract CB-1, CB-3 and BL7-1 rely on.
RECORDED = (
    ("Marta Siqueira", ["marta", "siqueira"]),
    ("the email from the bank", ["bank"]),
    ("o e-mail da Carla sobre o contrato", ["carla", "contrato"]),
    ("Gideon Farrow about the warehouse lease", ["gideon", "farrow", "warehouse", "lease"]),
    ("Marta Siqueira sobre o reembolso da viagem a Curitiba", ["marta", "siqueira", "reembolso", "viagem", "curitiba"]),
    ("my newest emails", []),
    ("os e-mails do banco itau", ["banco", "itau"]),
    ("Nadia Ferreira about the volunteer schedule for the book fair", []),
    ("Caio Fontana sobre o convite pra palestrar no congresso de logística", []),      # validate: allow english-only -- a Portuguese line or word is the input under test
    ("Priya's note about the thing with the broken projector in room B", []),
    ("a b c d e f", ["b", "c", "d", "f"]),
    ("a b c d e f g", ["b", "c", "d", "f", "g"]),
    ("please the latest messages from Bo regarding the lease", ["bo", "lease"]),
    ("Orla Whitcombe about the greenhouse lease", ["orla", "whitcombe", "greenhouse", "lease"]),
    ("", []),
    ("   ", []),
    ("Ana a respeito do orçamento", ["ana", "respeito", "orcamento"]),      # validate: allow english-only -- a Portuguese line or word is the input under test
    ("the volunteer schedule for the book fair and the lunch menu too", []),
    ("Tiago Valente sobre o orçamento do forro", ["tiago", "valente", "orcamento", "forro"]),      # validate: allow english-only -- a Portuguese line or word is the input under test
    ("rápido e-mails da Loja Mar Azul sobre a promoção de inverno", ["rapido", "loja", "mar", "azul", "promocao", "inverno"]),      # validate: allow english-only -- a Portuguese line or word is the input under test
)


@pytest.mark.parametrize("target, words", RECORDED, ids=[str(i) for i in range(len(RECORDED))])
def test_target_words_with_no_cap_is_what_it_was(target, words):
    assert nwm.target_words(target, TABLES) == words


def test_ground_words_keeps_up_to_ten_content_words_and_target_words_stays_at_six():
    seven = "Nadia Ferreira about the volunteer schedule for the book fair"
    assert nwm.target_words(seven, TABLES) == []
    assert nwm.target_words(seven, TABLES, cap=10) == ["nadia", "ferreira", "volunteer", "schedule", "for", "book", "fair"]
    assert nwm.ground_words(seven, TABLES) == ["nadia", "ferreira", "volunteer", "schedule", "for", "book", "fair"]
    eleven = "alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo"
    assert len(nwm.ground_words(eleven, TABLES)) == 0 and len(nwm.ground_words("alpha bravo charlie delta echo foxtrot golf hotel india juliet", TABLES)) == 10
    assert nwm.GROUND_WORDS_MAX == 10 and nwm.TARGET_WORDS_MAX == 6


# --- the check on the recorded answers -------------------------------------------------------------------------------------------------------------

# (item, the line of the blind set 2, the model's recorded answer's target, its body)
RECORDED_ANSWERS = (
    ("test-en-70002", "Reply to Nadia Ferreira about the volunteer schedule for the book fair, thank her and politely decline the Saturday shift.",
     "Nadia Ferreira about the volunteer schedule for the book fair", "thank her and politely decline the Saturday shift",
     "Nadia Ferreira the volunteer schedule for the book fair", "Nadia Ferreira"),
    ("test-en-70006", "Answer Priya's note about the thing with the broken projector in room B, saying the technician comes tomorrow at 10.",
     "Priya's note about the thing with the broken projector in room B", "the technician comes tomorrow at 10",
     "Priya's note the thing with the broken projector in room B", "Priya's note"),
    ("test-pt-br-70030", "Responde o Caio Fontana sobre o convite pra palestrar no congresso de logística agradecendo muito e recusando com educação, porque estou de licença em março.",      # validate: allow english-only -- a Portuguese line or word is the input under test
     "Caio Fontana sobre o convite pra palestrar no congresso de logística", "agradecendo muito e recusando com educação, porque estou de licença em março",      # validate: allow english-only -- a Portuguese line or word is the input under test
     "Caio Fontana o convite pra palestrar no congresso de logística", "Caio Fontana"),      # validate: allow english-only -- a Portuguese line or word is the input under test
)


def check(line, slots, name="mail-reply"):
    return interp.check({"v": 1, "kind": "op", "op": name, "slots": slots}, line, None, kit.CATALOG, kit.NOW, kit.ZONE, kit.ALL_OPS)


@pytest.mark.parametrize("item, line, target, body, ground, person", RECORDED_ANSWERS, ids=[row[0] for row in RECORDED_ANSWERS])
def test_the_check_grounds_the_recorded_long_targets(item, line, target, body, ground, person):
    got = check(line, {"target": target, "body": body})
    assert got["kind"] == "op" and got["spans"]["target"] == target, got
    assert got["target_ground"] == ground and got["target_sender"] == person, got


def test_a_name_that_is_a_marker_of_another_language_does_not_split_the_target_early():
    for name, target, line in (("Mei Su", "Mei Su about the volunteer schedule for the book fair", "Reply to Mei Su about the volunteer schedule for the book fair, saying yes."),
                               ("Lia Sur", "Lia Sur regarding the quarterly budget review with the board", "Reply to Lia Sur regarding the quarterly budget review with the board, saying yes.")):
        got = check(line, {"target": target, "body": "saying yes"})
        assert got["kind"] == "op" and got["target_sender"] == name and got["target_ground"].startswith(name + " the "), got


def test_a_target_with_a_marker_and_five_words_has_no_ground_and_a_widened_target_keeps_its_own():
    line = "Responde o e-mail da Marta Siqueira sobre o reembolso da viagem a Curitiba, por favor."
    got = check(line, {"target": "Marta Siqueira sobre o reembolso da viagem a Curitiba"})
    assert got["kind"] == "op" and "target_ground" not in got and "target_sender" not in got, got
    widened = check("reply to Orla Whitcombe about the greenhouse lease and say we accept", {"target": "Orla Whitcombe", "body": "we accept"})
    assert widened["target_ground"] == "Orla Whitcombe the greenhouse lease" and widened["target_sender"] == "Orla Whitcombe", widened          # BL7-1's ground is untouched; GROUNDING-FROM records the person's part for it too (the model's own target, before the widening)


# --- the product's own turn --------------------------------------------------------------------------------------------------------------------

GROUPS = ("read", "talk", "interpret", "mail-send", "mail-organize", "ask-mail")
SCHEDULE = tsm.message(1, "2026-10-20T10:00:00Z", sender="Nadia Ferreira <nadia.ferreira@feira.example>", subject="Volunteer schedule for the book fair", id="p1", thread_id="t1",
                       text="Here is the schedule.", headers={"Message-ID": "<c1@x.example>"})
PARKING = tsm.message(2, "2026-10-20T08:00:00Z", sender="Nadia Ferreira <nadia.ferreira@feira.example>", subject="Book fair parking", id="p2", thread_id="t2",
                      text="Here is the map.", headers={"Message-ID": "<c2@x.example>"})
CAIO = tsm.message(1, "2026-10-20T10:00:00Z", sender="Caio Fontana <caio.fontana@congresso.example>", subject="Convite pra palestrar no congresso de logística", id="p1", thread_id="t1",      # validate: allow english-only -- a Portuguese line or word is the input under test
                   text="Segue o convite.", headers={"Message-ID": "<c1@x.example>"})
EN_REPLY = "Reply to Nadia Ferreira about the volunteer schedule for the book fair, saying: yes, I will be there on Saturday."
EN_TARGET = "Nadia Ferreira about the volunteer schedule for the book fair"


def run(world, monkeypatch, language, line, answer, messages):
    model = setup(world, monkeypatch, interpret=answer, compose=json.dumps({"subject": "S", "body": "B"}), groups=GROUPS, language=language)
    world["desk"].providers.mail["gmail"] = [dict(m) for m in messages]
    world["desk"].refresh("inbox")
    monkeypatch.setattr(ops_natural_mail, "_mail_sources", lambda ctx: [{"id": "inbox", "account": "google"}])
    resolved = []
    real = ops_natural_mail.resolve

    def spy(ctx, op_name, slots, channel, sender, said=None):
        got = real(ctx, op_name, slots, channel, sender, said)
        resolved.append(got)
        return got
    monkeypatch.setattr(ops_natural_mail, "resolve", spy)
    return phone(world, line), resolved, model


def args_of(resolved):
    return [got["args"] for got in resolved if "args" in got]


def test_a_reply_named_by_a_sender_and_a_seven_word_subject_opens_the_card_for_that_message(world, clock, monkeypatch):
    out, resolved, model = run(world, monkeypatch, "en", EN_REPLY, op("mail-reply", {"target": EN_TARGET, "body": "saying: yes, I will be there on Saturday"}), (SCHEDULE,))
    assert model.of("interpret") and out["resend"], out["reply"]
    assert args_of(resolved)[0]["message"] == "inbox#1"


def test_a_message_that_lacks_a_word_of_the_ground_is_not_found_and_nothing_opens(world, clock, monkeypatch):
    out, resolved, _ = run(world, monkeypatch, "en", EN_REPLY, op("mail-reply", {"target": EN_TARGET, "body": "saying: yes, I will be there on Saturday"}), (PARKING,))
    cfg = ops_core.context(world["path"])["cfg"]
    assert not out.get("resend") and not args_of(resolved)
    assert out["reply"] == phrases.text("NW_MAIL_NONE", cfg, source="Gmail", words="nadia ferreira volunteer schedule for book fair"), out["reply"]


def test_a_pt_br_reply_named_by_a_sender_and_an_eight_word_subject_opens_the_card(world, clock, monkeypatch):
    line = "Responde o Caio Fontana sobre o convite pra palestrar no congresso de logística dizendo: obrigado, aceito."      # validate: allow english-only -- a Portuguese line or word is the input under test
    target = "Caio Fontana sobre o convite pra palestrar no congresso de logística"      # validate: allow english-only -- a Portuguese line or word is the input under test
    out, resolved, _ = run(world, monkeypatch, "pt-BR", line, op("mail-reply", {"target": target, "body": "dizendo: obrigado, aceito"}), (CAIO,))
    assert out["resend"], out["reply"]
    assert args_of(resolved)[0]["message"] == "inbox#1"


def test_a_plural_archive_takes_only_the_message_that_holds_every_word(world, clock, monkeypatch):
    line = "Archive the emails from Nadia Ferreira about the volunteer schedule for the book fair"
    out, resolved, _ = run(world, monkeypatch, "en", line, op("mail-archive", {"target": EN_TARGET}), (SCHEDULE, PARKING))
    assert [a["messages"] for a in args_of(resolved)] == ["inbox#1"], out["reply"]


# --- vacuity -----------------------------------------------------------------------------------------------------------------------------------


def test_vacuity_a_ground_cap_of_six_gives_the_card_rows_no_seed(world, clock, monkeypatch):
    monkeypatch.setattr(nwm, "GROUND_WORDS_MAX", 6)
    out, resolved, _ = run(world, monkeypatch, "en", EN_REPLY, op("mail-reply", {"target": EN_TARGET, "body": "saying: yes, I will be there on Saturday"}), (SCHEDULE,))
    assert not out.get("resend") and not args_of(resolved)


def test_vacuity_a_match_on_any_one_word_takes_both_messages_where_the_real_one_takes_one(world, clock, monkeypatch):
    def any_word(entries, words, newest=False, sender=()):          # GROUNDING-FROM: a G3 seed also carries the person's words, which this plant ignores
        wanted = [w for w in words if w]
        return [e for e in sorted(entries, key=lambda e: e["n"]) if set(wanted) & nwm.entry_words(e)]
    monkeypatch.setattr(nwm, "match_words", any_word)
    line = "Archive the emails from Nadia Ferreira about the volunteer schedule for the book fair"
    out, resolved, _ = run(world, monkeypatch, "en", line, op("mail-archive", {"target": EN_TARGET}), (SCHEDULE, PARKING))
    assert [a["messages"] for a in args_of(resolved)] == ["inbox#1,inbox#2"], out["reply"]
