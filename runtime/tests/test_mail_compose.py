"""The pure parts of the e-mail compose step (slice S7, runtime/mail_compose.py): what code accepts of the model's answer, which words a seed takes from the interpreter's
decision, the closed marker of a literal text, and the pin of the compose prompt in runtime/interpreter_enable.json. Offline; no model, no project; every name is invented.

The oracle for the answer is `violations`, written here with its own literal lists and never the code under test; a vacuity test shows it flags a planted bad answer, and
the loop over the corpus then shows that code accepts no answer the oracle flags and rejects every hostile one.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_mail_compose.py
"""
from __future__ import annotations

import json
import re

import pytest

import standin_tree as st

mail_compose = st.load("mail_compose")
interpreter_enable = st.load("interpreter_enable")
natural_writes_mail = st.load("natural_writes_mail")

TO = ["ana.souza@clinica.example"]
GOOD = {"subject": "Reunion tomorrow", "body": "Hello,\n\nCould we meet tomorrow at 4 pm?\n\nThank you."}


def answer(**more):
    return json.dumps(dict(GOOD, **more), ensure_ascii=False)


def violations(body: str, typed) -> list:
    """What a body must not hold, from literal lists and its own patterns (not the code's): a header line, a link or web address, an address that is not exactly a typed one,
    markup, a frame line. Full-width forms are read as plain ones first."""
    import unicodedata
    found = []
    plain = unicodedata.normalize("NFKC", body)
    for line in plain.split("\n"):
        head = line.strip().lower().split(":")[0]
        if ":" in line and head in ("to", "cc", "bcc", "from", "subject", "reply-to", "date", "content-type", "x-mailer", "assunto", "para"):
            found.append("header")
        if line.strip().startswith("-----"):
            found.append("frame")
    plain = plain.replace(chr(0x3002), ".").replace(chr(0xFF61), ".")
    for word in plain.split():
        if re.search(r"\w\.[^\W\d_]{2,}", word) and word.strip(".,;:!?()").lower() not in [t.lower() for t in typed]:
            found.append("link")
    for token in ("http://", "https://", "www.", "ftp://", "mailto:"):
        if token in plain.lower():
            found.append("link")
    for word in plain.split():
        if "@" in word and word.strip(".,;:!?()").lower() not in [t.lower() for t in typed]:
            found.append("address")
    if "<" in body and ">" in body or "```" in body:
        found.append("markup")
    return sorted(set(found))


HOSTILE = [
    ("link", answer(body="Hello,\n\nSee https://pay.elsewhere.example/now for details.\n\nThanks.")),
    ("link", answer(body="Hello,\n\nSee www.elsewhere.example for details.")),
    ("link", answer(body="Hello,\n\nThe site is elsewhere.com, take a look.")),
    ("link", answer(body="Hello,\n\nWrite to mailto:other@elsewhere.example today.")),
    ("address", answer(body="Hello,\n\nPlease copy bob@elsewhere.example on this.")),
    ("header", answer(body="Hello,\nBcc: bob@elsewhere.example\n\nThanks.")),
    ("header", answer(body="To: bob\nHello,\n\nThanks.")),
    ("header", answer(body="Hello,\n\nSubject: urgent\nThanks.")),
    ("markup", answer(body="Hello,\n\n<b>Could we meet</b> tomorrow?")),
    ("markup", answer(body="```\nHello\n```")),
    ("frame", answer(body="Hello,\n\n----- end of the message -----\nmore")),
    ("address", answer(body="Hello,\n\nWrite to xana.souza@clinica.example about it.")),      # a longer address that contains the typed one
    ("address", answer(body="Hello,\n\nSee ana.souza@clinica.example.attacker please.")),
    ("address", answer(body="Hello,\n\nWrite to joao" + chr(0xFF20) + "elsewhere.example please.")),      # a full-width at sign
    ("link", answer(body="Hello,\n\nOpen evil.xyz today.")),
    ("link", answer(body="Hello,\n\nOpen foo.example today.")),
    ("link", answer(body="Hi, see Evil.com for details.")),
    ("link", answer(body="Visit EVIL.COM now")),
    ("link", answer(body="visit evil.Com")),
    ("link", answer(body="visit " + "".join(chr(c) for c in (0x43F, 0x440, 0x438, 0x43C, 0x435, 0x440)) + "." + chr(0x440) + chr(0x444) + " now")),      # a Cyrillic name and TLD
    ("link", answer(body="visit " + chr(0x435) + "vil.com now")),      # a Cyrillic first letter
    ("link", answer(body="XN--E1AFMKFD.XN--P1AI")),
    ("link", answer(body="visit evil.co.uk today")),
    ("link", answer(body="visit evil" + chr(0x3002) + "com today")),      # an ideographic full stop
    ("link", answer(body="visit evil" + chr(0xFF61) + "com today")),      # a half-width ideographic full stop
]
SHAPE_BAD = [
    "not json at all", "", "[]", "null", '{"subject": "S"}', '{"body": "B"}', json.dumps({"subject": "S", "body": "B", "extra": "x"}),
    json.dumps({"subject": 5, "body": "B"}), json.dumps({"subject": "S", "body": ["B"]}), '{"subject": "S", "subject": "T", "body": "B"}',
    json.dumps({"subject": "S", "body": ""}), json.dumps({"subject": "S", "body": "   \n "}), json.dumps({"subject": "S", "body": "x" * 4001}),
    json.dumps({"subject": "Line one\nline two", "body": "B"}), json.dumps({"subject": "", "body": "B"}), json.dumps({"subject": "S" * 201, "body": "B"}),
    json.dumps({"subject": "Mail to bob@elsewhere.example", "body": "B"}), json.dumps({"subject": "Evil.Com offer", "body": "B"}),
    json.dumps({"subject": "Re: your invoice", "body": "B"}), json.dumps({"subject": "FW: your invoice", "body": "B"}), json.dumps({"subject": "Fwd: x", "body": "B"}),
    json.dumps({"subject": "RES: x", "body": "B"}), json.dumps({"subject": "ENC: x", "body": "B"}), json.dumps({"subject": "Read https://elsewhere.example", "body": "B"}), json.dumps({"subject": "=?utf-8?q?x?=", "body": "B"}),
    json.dumps({"subject": "S", "body": "Hello" + chr(0x200B) + " there"}), '{"subject": NaN, "body": "B"}', "x" * 9000,
]


def test_the_oracle_flags_every_planted_bad_answer_and_none_of_the_good_one():
    assert violations(GOOD["body"], TO) == []
    assert violations("Hello ana.souza@clinica.example, thanks.", TO) == [], "the typed address itself is allowed"
    for label, text in HOSTILE:
        assert label in violations(json.loads(text)["body"], TO), (label, text)


@pytest.mark.parametrize("label, text", HOSTILE)
def test_a_hostile_answer_is_rejected(label, text):
    assert mail_compose.validate(text, TO, None) is None


@pytest.mark.parametrize("text", SHAPE_BAD)
def test_a_malformed_answer_is_rejected(text):
    assert mail_compose.validate(text, TO, None) is None


def test_a_good_answer_is_accepted_whole_fenced_and_with_the_typed_address_in_it():
    assert mail_compose.validate(answer(), TO, None) == {"subject": "Reunion tomorrow", "body": GOOD["body"]}
    assert mail_compose.validate("```json\n" + answer() + "\n```", TO, None) == {"subject": "Reunion tomorrow", "body": GOOD["body"]}
    assert mail_compose.validate(answer(body="Hello ana.souza@clinica.example,\n\nThanks."), TO, None)["body"] == "Hello ana.souza@clinica.example,\n\nThanks."
    assert mail_compose.validate(answer(body="Line one.\r\nLine two.\r\n"), TO, None)["body"] == "Line one.\nLine two."
    for body in ("Write to ana.souza@clinica.example.", "Write to (ana.souza@clinica.example), please.", "Write to Ana.Souza@Clinica.example today."):
        assert mail_compose.validate(answer(body=body), TO, None)["body"] == body, body      # the typed address, whole, in any case and next to punctuation


@pytest.mark.parametrize("body", ["Hello,\n\nSee you amanh\u00e3 \u00e0s 16h. Obrigado.", "Total: R$ 1.500,00 at\u00e9 10.11 please.", "Use e.g. this one.", "We meet at 4 p.m. ok", "Dr. Silva will call."])
def test_ordinary_text_with_dots_is_still_accepted(body):
    assert mail_compose.validate(answer(body=body), TO, None)["body"] == body.strip()


def test_the_subject_the_person_gave_wins_and_is_not_judged_but_the_body_still_is():
    assert mail_compose.validate(answer(subject="https://not-used.example"), TO, "My own subject") == {"subject": "My own subject", "body": GOOD["body"]}
    assert mail_compose.validate(answer(body="See www.elsewhere.example"), TO, "My own subject") is None


def test_nothing_the_oracle_flags_is_ever_accepted_over_a_generated_corpus():
    pieces = ["Hello,", "See https://elsewhere.example", "Write to eve@elsewhere.example", "Subject: x", "Thanks.", "<i>hi</i>", "visit site.com", "ana.souza@clinica.example", "Bye"]
    accepted = 0
    for i in range(len(pieces)):
        for j in range(len(pieces)):
            body = pieces[i] + "\n" + pieces[j]
            got = mail_compose.validate(json.dumps({"subject": "S", "body": body}), TO, None)
            if got is not None:
                accepted += 1
                assert violations(got["body"], TO) == [], body
    assert accepted > 0, "the corpus holds clean bodies too, so the loop is not vacuous"


def test_vacuity_an_accept_all_validator_would_fail_the_corpus_oracle():
    for label, text in HOSTILE:
        assert violations(json.loads(text)["body"], TO), "the oracle sees the plant, so an accept-all validator would be caught"


# --- the seed --------------------------------------------------------------------------------------------------------------------------------------

LINE = "Send an e-mail to ana.souza@clinica.example. I want to talk about moving the meeting to tomorrow at 4 pm"


def decision(**spans):
    return {"kind": "op", "op": "mail-send", "spans": spans, "args": {}}


def test_a_seed_takes_the_address_only_when_the_sender_typed_it_as_a_whole_address():
    seed = mail_compose.seed("mail-send", decision(to="ana.souza@clinica.example", body="I want to talk about moving the meeting to tomorrow at 4 pm"), LINE)
    assert seed == {"op": "mail-send", "slots": {"to": ["ana.souza@clinica.example"], "body": "I want to talk about moving the meeting to tomorrow at 4 pm", "_compose": True,
                                                  "_ai_subject": True}}
    for wrong in ("souza@clinica.example", "ana.souza@clinica.exampl", "ana.souza@clinica.example.", "someone@else.example"):
        slots = mail_compose.seed("mail-send", decision(to=wrong), LINE)["slots"]
        assert "to" not in slots and "to_names" not in slots, wrong


def test_an_address_typed_with_capitals_is_kept_as_typed():
    line = "Send to Ana.Souza@Clinica.example about it"
    seed = mail_compose.seed("mail-send", decision(to="Ana.Souza@Clinica.example", body="about it"), line)
    assert seed["slots"]["to"] == ["Ana.Souza@Clinica.example"]


def test_a_word_without_an_at_sign_is_a_name_the_family_asks_the_address_of_and_a_subject_stops_the_model_writing_one():
    slots = mail_compose.seed("mail-draft", decision(to="Ana", subject="The  meeting\nmoved", body="b"), "Draft to Ana")["slots"]
    assert slots == {"to_names": ["Ana"], "subject": "The meeting moved", "body": "b", "_compose": True}


def test_a_draft_with_no_recipient_may_be_a_reply_draft_and_gets_no_seed_and_a_marker_only_subject_never_blocks():
    assert mail_compose.seed("mail-draft", decision(body="say yes"), "x") is None
    assert mail_compose._subject_of("What is =?utf-8?q?x?= about") == ""


def test_a_reply_draft_and_every_other_operation_get_no_seed():
    assert mail_compose.seed("mail-draft", {"spans": {"message": "3", "body": "ok"}, "args": {"message": 3}}, "x") is None
    assert mail_compose.seed("mail-reply", decision(body="ok"), "x") is None
    assert mail_compose.seed("mail-archive", decision(), "x") is None
    assert mail_compose.seed("event-create", decision(), "x") is None


# --- the marker --------------------------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("text, rest", [("exact text: Hi Ana.", "Hi Ana."), ("Exact Text:Hi", "Hi"), ("texto exato: Oi", "Oi"), ("texto exacto: Hola", "Hola"),
                                         ("texte exact : Salut", "Salut"), ("genauer Text: Hallo", "Hallo"), ("testo esatto: Ciao", "Ciao"), ("  EXACT TEXT:   spaced  ", "spaced")])
def test_the_closed_marker_of_a_literal_text_is_removed_in_every_language(text, rest):
    assert mail_compose.strip_marker(text) == (rest, True)


@pytest.mark.parametrize("text", ["Please send the exact text: later", "exact text without a colon", "text exact: no", "", "exacto: no"])
def test_a_text_that_does_not_start_with_the_marker_is_left_alone(text):
    assert mail_compose.strip_marker(text) == (text, False)


# --- the pin -------------------------------------------------------------------------------------------------------------------------------------------


def variant(tmp_path, **changes):
    doc = json.loads((st.RUNTIME / "interpreter_enable.json").read_text(encoding="utf-8"))
    for key, value in changes.items():
        if value is None:
            doc["entries"][-1].pop(key, None)
        else:
            doc["entries"][-1][key] = value
    path = tmp_path / "enable.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return str(path)


def test_composing_is_in_force_only_while_the_newest_entry_pins_this_prompt_and_the_interpreter_stays_on(tmp_path):
    assert interpreter_enable.compose_active("en") is not None and interpreter_enable.compose_active("ja") is None
    for name, changes in (("another hash", {"compose_prompt_sha256": "0" * 64}), ("no pin", {"compose_prompt_sha256": None})):
        path = variant(tmp_path, **changes)
        assert interpreter_enable.compose_active("en", path=path) is None, name
        assert interpreter_enable.active("en", path=path) is not None, name + ": the interpreter does not depend on the compose prompt"
    assert interpreter_enable.compose_active("en", path=variant(tmp_path)) is not None, "the unchanged copy is in force: the others are not vacuous"


def test_the_committed_prompt_has_the_sha256_the_file_pins_and_holds_no_third_party_text():
    text = (st.RUNTIME / "mail_compose_prompt.txt").read_text(encoding="utf-8")
    assert re.fullmatch(r"[0-9a-f]{64}", mail_compose.prompt_sha256()) and mail_compose.prompt_template() == text
    assert "{{" not in text and "http" not in text and "@" not in text, "a fixed prompt: no placeholder, no address, no link"


# --- the spelling of the typed subject (S12) --------------------------------------------------------------------------------------------------------

import unicodedata      # noqa: E402


def plain_words(text: str) -> list:
    """The test's own reading of a subject: accents removed, lower case, the words in order."""
    flat = "".join(c for c in unicodedata.normalize("NFD", text.lower()) if unicodedata.category(c) != "Mn")
    return re.findall(r"[a-z0-9]+", flat)


def subject_violations(typed: str, result: str) -> list:
    """What a kept or corrected subject must never be, from the test's own rules: another word count, a non-letter character that is not the person's (digits, punctuation, symbols, spaces),
    a letter of another script, a compatibility form or an invisible character, a different capital on a name."""
    found = []
    if result == typed:
        return found
    if len(plain_words(typed)) != len(plain_words(result)):
        found.append("words")
    keep = lambda text: re.sub(r"\s+", " ", "".join(c for c in unicodedata.normalize("NFC", text) if unicodedata.category(c)[0] not in "LM" or c.isspace()))
    if keep(result) != keep(typed):
        found.append("non-letters")
    script = lambda text: {unicodedata.name(c).split(" ")[0] for c in text if unicodedata.category(c)[0] == "L"}
    if not script(result) <= script(typed):
        found.append("script")
    if unicodedata.normalize("NFKC", result) != result or any(unicodedata.category(c) in ("Cf", "Cc") for c in result):
        found.append("form")
    if "@" in result or "http" in result.lower() or "www." in result.lower():
        found.append("link")
    for old, new in zip(typed.split(), result.split()):
        if old[:1].isupper() != new[:1].isupper() and typed.split().index(old) > 0:
            found.append("capital")
    return found


SPELLING_KEPT = [      # (typed, the model's subject): the typed subject stays
    ("Reuniao sobre o Openhora", "Convite para reuni\u00e3o"),      # another subject
    ("Reuni\u00e3o sobre o Openhora", "Convite para reuni\u00e3o"),
    ("Reuniao sobre Openhora", "Reuni\u00e3o sobre o Openhora"),      # a word added
    ("Reuniao sobre o Openhora", "Reuni\u00e3o Openhora"),      # words removed
    ("Reuniao sobre o Openhora", "Openhora sobre o reuni\u00e3o"),      # another order
    ("Reuniao dia 12", "Reuni\u00e3o dia 13"),      # a new digit
    ("Reuniao dia 12", "Reuni\u00e3o dia 12 as 10"),
    ("Reuniao", "Reuni\u00e3o https://elsewhere.example"),      # a link
    ("Reuniao", "Reuni\u00e3o elsewhere.com"),
    ("Reuniao", "Reuni\u00e3o ana@elsewhere.example"),
    ("Reuniao sobre o Openhora", "Re: Reuni\u00e3o sobre o Openhora"),      # a reply mark
    ("Reuniao sobre o Openhora", "Reuni\u00e3o\nsobre o Openhora"),      # two lines
    ("Reuniao sobre o Openhora", ""),
    ("Reuniao sobre o Openhora", 5),
    ("Meeting tomorow", "Meeting tomorrow, urgent"),
    ("Opnehora", "Openhora"),      # an edit of a word typed with a capital
    ("Reuniao sobre o Openhora", "Reunao sobre o Openhora"),
    ("Reuniao com a Ana", "Reuni\u00e3o com o Ana"),      # a short word replaced: another word, not a case, keeps the whole typed subject (as S12 did)
    ("Reuniao amanha", "Reuni\u00e3o hoje"),      # a word replaced
    ("pagar conta nao", "pegar conta sim"),      # one word taken by the rule (pagar -> pegar), another replaced (nao -> sim): the whole typed subject stays
    ("aprovado", "reprovado"), ("possivel", "impossivel"), ("can attend", "cant attend"), ("is legal", "is illegal"),      # a letter added at the start, or a short word changed
    ("pago", "pagou"), ("ver", "vez"),
    ("Reuniao amanha", "Reuniao amanha."), ("Reuniao amanha", "Reuniao  amanha ?"),
]
SPELLING_FIXED = [      # (typed, the model's subject, the subject on the card)
    ("Reuniao sobre o Openhora", "Reuni\u00e3o sobre o Openhora", "Reuni\u00e3o sobre o Openhora"),
    ("reuniao sobre Openhora", "Reuni\u00e3o sobre Openhora", "Reuni\u00e3o sobre Openhora"),      # the first letter of the first word may become a capital
    ("Reuniao sobre as tarefas", "Reuniao sobre as tarefaz", "Reuniao sobre as tarefaz"),      # a small edit inside a lower-case word
    ("Meeting tomorow at 10", "Meeting tomorrow at 10", "Meeting tomorrow at 10"),
    ("Reunion de planificacion", "Reuni\u00f3n de planificaci\u00f3n", "Reuni\u00f3n de planificaci\u00f3n"),
    ("Reuniao Ana", "Reuni\u00e3o Ana", "Reuni\u00e3o Ana"),
    ("reuniao amanha", "Reuni\u00e3o amanh\u00e3", "Reuni\u00e3o amanh\u00e3"),
]


PROBES_KEPT = [      # every probe of the review that is not the same subject with its spelling fixed: (typed, the model's subject)
    ('Fatura paga', 'Fatura pagar'),
    ('Reuniao as 16h', 'Reuni\xe3o \xe0s 17h'),
    ('Pagamento 500', 'Pagamento 600'),
    ('Nao pagar', 'Pagar'),
    ('pode pagar', 'nao pagar'),
    ('vou aceitar', 'vou recusar'),
    ('Vou ir', 'Nao ir'),
    ('Reuniao com Ana', 'Reuniao com Ann'),
    ('Reuniao com Ana', 'Reuniao com Ama'),
    ('Reuniao com Joao', 'Reuniao com Jose'),
    ('Reuniao com Maria', 'Reuniao com Mario'),
    ('confirmo presenca', 'cancelo presenca'),
    ('aprovado', 'reprovado'),
    ('approved', 'unapproved'),
    ('can attend', 'cant attend'),
    ('I can come', 'I cant come'),
    ('is legal', 'is illegal'),
    ('possivel', 'impossivel'),
    ('sim', 'nao'),
    ('Oi', 'OI'),
    ('Reuniao', 'Reuni\u200bao'),
    ('Reuniao', 'Reuniao\u202e'),
    ('Reuniao amanha', 'Reuniao amanh\u0430'),
    ('Pagamento', 'Pagamento\xa0x'),
    ('Reuniao amanha', 'Reuni\xe3o, amanh\xe3!'),
    ('Reuniao amanha', 'Reuniao: amanha?'),
    ('Reuniao amanha', 'Reuniao - amanha (urgente)'),
    ('Reuniao amanha', 'Reuniao amanha 2'),
    ('Reuniao amanha', 'Reuniao amanha \U0001f600'),
    ('Reuniao amanha', 'Reuniao amanha $$$'),
    ('Reuniao amanha', 'Reuniao amanha <b>'),
    ('Re uniao', 'Reuniao'),
    ('teste', 'test@x.io'),
    ('site', 'site.com'),
    ('Reuniao x', 'Reuniao.com'),
    ('valor 1,5', 'valor 15'),
    ('valor 1.5', 'valor 1,5'),
    ('valor 1.5', 'valor 1-5'),
    ('valor R$ 10', 'valor US$ 10'),
    ('valor 10%', 'valor 10'),
    ('ate 10/11', 'at\xe9 11/10'),
    ('Reuniao amanha', 'Reuniao amanha \xbd'),
    ('item 2', 'item \xb2'),
    ('item 2', 'item \u2082'),
    ('I', 'l'),
    ('Hello Bob', 'Hello Rob'),
    ('Hi Al', 'Hi AI'),
    ('Prazo terca', 'Prazo quarta'),
    ('Meeting monday', 'Meeting sunday'),
    ('Encontro dia 5', 'Encontro dia cinco'),
    ('ok', 'ok!'),
    ('a b', 'ab'),
    ('Reuniao amanha', 'reuniao amanha'),
    ('Reuniao ANA', 'Reuniao Ana'),
    ('Reuniao Ana', 'Reuniao ANA'),
    ('Projeto x', 'Projeto \u2715'),
    ('Reuniao amanha', 'Reuniao\tamanha'),
    ('Reuniao amanha', 'Reuniao\u2028amanha'),
    ('Reuniao amanha', 'Reuniao amanha\u200f'),
    ('Reuniao amanha', 'Reuniao amanha\u0301'),
    ('Reuniao', 'R\u0435uniao'),
    ('Reuniao', 'Reunia\u043e'),
    ('Contrato', 'Contrat\u03bf'),
    ('Fwd teste', 'Fwd: teste'),
    ('Re teste', 'Re: teste'),
    ('Pagar 1000', 'Pagar 1 000'),
    ('caixa', 'caixa\ufe0f'),
    ('Pagar 1.500', 'Pagar 1,500'),
    ('Pagar 1.500', 'Pagar 1500'),
    ('Pagar -5', 'Pagar 5'),
    ('10:30', '10/30'),
    ('Desconto 10%', 'Desconto 10'),
    ('Custo \u20ac 10', 'Custo $ 10'),
    ('Custo 10 \u20ac', 'Custo 10 \xa3'),
    ('nota > 5', 'nota < 5'),
    ('Item #1', 'Item 1'),
    ('Reuniao confirmada', 'Reuniao confirmada?'),
    ('1/2 dia', '1-2 dia'),
    ('Reuniao amanha', 'Reuniao amanha \u26a0'),
    ('Reuniao amanha', 'Reuniao amanha \u274c'),
    ('Reuniao amanha', 'Reuniao amanha !!!'),
    ('Dr Silva', 'Dr. Silva'),
    ('McDonald reuniao', 'Mcdonald reuniao'),
    ('iPhone novo', 'Iphone novo'),
    ('Lista ABC', 'Lista ACB'),
    ('Codigo XKCD', 'Codigo XKDC'),
    ('senha Ab', 'senha Ab'),
    ('Reuniao', 'Reuniao\xad'),
    ('Reuniao', 'Reuni\u2060ao'),
    ('Reuniao', 'Reuniao\u3000'),
    ('Ola', '\uff9bla'),
    ('teste', '\uff54\uff45\uff53\uff54\uff45'),
    ('Reuniao', '\uff32euniao'),
    ('send now', 'send not'),
    ('will', 'wont'),
    ('do it', 'do not'),
]
PROBES_FIXED = [      # the probes that are spelling or a small edit inside a lower-case word: (typed, the model's subject)
    ('Reuniao amanha', 'Reuni\xe3o amanh\xe3'),
    ('pode pagar', 'pode pegar'),
    ('Fatura paga', 'Fatura para'),
    ('ana', 'Ana'),
    ('Prazo sexta', 'Prazo sesta'),
    ('Prazo terca', 'Prazo ter\xe7a'),
    ('Reuni\xe3o', 'Reuniao'),
    ('Nao vou', 'N\xe3o vou'),
    ('Joao e Ana', 'Jo\xe3o e Ana'),
    ('pedido abcdef', 'pedido abcdeg'),
    ('ola', 'ol\xe1'),
    ('Meeting at five', 'Meeting at fine'),
]


@pytest.mark.parametrize("typed, shown", SPELLING_KEPT + PROBES_KEPT)
def test_a_model_subject_that_is_not_the_same_words_with_the_spelling_fixed_keeps_the_typed_subject(typed, shown):
    assert mail_compose.spelled(typed, shown) == typed


@pytest.mark.parametrize("typed, shown, expected", SPELLING_FIXED)
def test_a_model_subject_that_is_the_same_words_with_the_spelling_fixed_replaces_the_typed_one(typed, shown, expected):
    assert mail_compose.spelled(typed, shown) == expected
    assert subject_violations(typed, expected) == []


@pytest.mark.parametrize("typed, shown", PROBES_FIXED)
def test_the_probes_that_are_spelling_or_a_small_edit_inside_a_lower_case_word_are_taken_and_pass_the_oracle(typed, shown):
    assert mail_compose.spelled(typed, shown) == shown.strip() and subject_violations(typed, shown) == []


@pytest.mark.parametrize("typed, shown, kind", [
    ("Pagar -5", "Pagar 5", "non-letters"), ("Custo \u20ac 10", "Custo $ 10", "non-letters"), ("nota > 5", "nota < 5", "non-letters"), ("Pagar 1.500", "Pagar 1,500", "non-letters"),
    ("Desconto 10%", "Desconto 10", "non-letters"), ("Item #1", "Item 1", "non-letters"), ("10:30", "10/30", "non-letters"), ("item 2", "item \u00b2", "form"),
    ("Reuniao", "R\u0435uniao", "script"), ("Reuniao", "Reuniao\u043e", "script"), ("Contrato", "Contrat\u03bf", "script"),      # Cyrillic and Greek lookalikes in a Latin word
    ("Reuniao", "\uff32euniao", "form"), ("teste", "\uff54\uff45\uff53\uff54\uff45", "form"), ("Reuniao", "Reuni\u200bao", "form"), ("Reuniao", "Reuniao\u202e", "form"),
    ("Reuniao amanha", "Reuniao amanha ?", "non-letters"), ("Re uniao", "Reuniao", "non-letters"),
])
def test_the_oracle_sees_what_the_review_changed_and_spelled_refuses_every_one_of_them(typed, shown, kind):
    assert kind in subject_violations(typed, shown), "vacuity: the oracle flags the plant"
    assert mail_compose.spelled(typed, shown) == typed


def test_validate_returns_the_corrected_subject_only_when_it_is_the_same_subject():
    assert mail_compose.validate(answer(subject="Reuni\u00e3o sobre o Openhora"), TO, "Reuniao sobre o Openhora")["subject"] == "Reuni\u00e3o sobre o Openhora"
    assert mail_compose.validate(answer(subject="Convite para reuni\u00e3o"), TO, "Reuniao sobre o Openhora")["subject"] == "Reuniao sobre o Openhora"
    assert mail_compose.validate(answer(subject="Reuni\u00e3o sobre o Openhora"), TO, None)["subject"] == "Reuni\u00e3o sobre o Openhora"      # no subject typed: the model's, as before
    assert mail_compose.validate(answer(subject="Reuni\u00e3o https://elsewhere.example"), TO, "Reuniao")["subject"] == "Reuniao"


def test_the_oracle_never_sees_a_violation_in_what_spelled_returns_over_the_corpus_and_sees_the_plant():
    for typed, shown in SPELLING_KEPT + [(t, s) for t, s, _ in SPELLING_FIXED]:
        assert subject_violations(typed, mail_compose.spelled(typed, shown)) == [], (typed, shown)
    assert "words" in subject_violations("Reuniao sobre o Openhora", "Convite para reuni\u00e3o"), "vacuity: an accept-all spelling check would be caught"
    assert "non-letters" in subject_violations("Reuniao dia 12", "Reuni\u00e3o dia 13")
    assert "link" in subject_violations("Reuniao", "Reuni\u00e3o https://elsewhere.example")
    assert "capital" in subject_violations("Reuniao sobre Openhora", "Reuni\u00e3o sobre openhora")


# --- no dangling closing formula (S12) ---------------------------------------------------------------------------------------------------------------

DANGLING = [      # (body, the body kept)
    ("Hello,\n\nCould we meet tomorrow?\n\nBest regards,", "Hello,\n\nCould we meet tomorrow?"),
    ("Ol\u00e1,\n\nGostaria de marcar uma reuni\u00e3o.\n\nAtenciosamente,", "Ol\u00e1,\n\nGostaria de marcar uma reuni\u00e3o."),
    ("Ol\u00e1,\n\nAgrade\u00e7o desde j\u00e1.\n\nAtenciosamente,\n[Seu nome]", "Ol\u00e1,\n\nAgrade\u00e7o desde j\u00e1."),
    ("Hola,\n\nGracias por todo.\n\nSaludos,\n", "Hola,\n\nGracias por todo."),
    ("Bonjour,\n\nMerci pour tout.\n\nCordialement,", "Bonjour,\n\nMerci pour tout."),
    ("Hallo,\n\nVielen Dank.\n\nMit freundlichen Gr\u00fc\u00dfen,", "Hallo,\n\nVielen Dank."),
    ("Ciao,\n\nGrazie mille.\n\nCordiali saluti", "Ciao,\n\nGrazie mille."),
    ("Ol\u00e1,\n\nUm abra\u00e7o.\n\nAbra\u00e7os,", "Ol\u00e1,\n\nUm abra\u00e7o."),
    ("Ol\u00e1,\n\nOk.\n\nObrigado,", "Ol\u00e1,\n\nOk."),
    ("Ol\u00e1,\n\nOk.\n\nAtt,\n\n", "Ol\u00e1,\n\nOk."),
    ("Hi,\n\nPlease see the list.\nThanks\nBest\nCheers", "Hi,\n\nPlease see the list.\nThanks\nBest"),      # at most one closing line is removed
    ("Hi,\nplease confirm.\nBest\n[Name]\n[Company]", "Hi,\nplease confirm.\nBest\n[Name]\n[Company]"),      # two placeholders: the last line is not the one placeholder after a closing
    ("Hi,\nplease confirm.\n\nBest\n\n[Name]", "Hi,\nplease confirm."),
    ("Prezados,\n\nSegue.\n\nAtt.,", "Prezados,\n\nSegue."),
    ("Hi,\n\nNew menu items:\nThank you\nMerci\nGrazie", "Hi,\n\nNew menu items:\nThank you\nMerci"),      # one closing line only, and not after a line that ends with a colon
]
KEPT_AS_IT_IS = [      # a name follows, or the line is a finished courtesy sentence
    "Ol\u00e1,\n\nOk.\n\nAtenciosamente,\nAna",
    "Hello,\n\nOk.\n\nBest regards,\nAna Souza",
    "Ol\u00e1,\n\nGostaria de marcar uma reuni\u00e3o.\n\nObrigado.",
    "Hello,\n\nCould we meet tomorrow?\n\nThank you.",
    "Hello,\n\nPlease reply. Best regards, Ana",
    "Hi,\n\nItems to buy:\n[milk]\n[eggs]",      # content, not a signature
    "Hi,\n\nThe answer is:\n[A]",
    "Hi,\n\nPlease reply with one word:\nThanks",      # the closing word is the answer to the line before
    "Oi,\n\nO nome do filme \u00e9:\nObrigado",
    "Hi,\n\nI said:\nDanke",
]


@pytest.mark.parametrize("body, kept", DANGLING)
def test_a_body_that_ends_with_a_closing_formula_alone_loses_it(body, kept):
    assert mail_compose.without_dangling_close(body) == kept
    got = mail_compose.validate(json.dumps({"subject": "S", "body": body}, ensure_ascii=False), TO, None)
    assert got["body"] == kept


@pytest.mark.parametrize("body", KEPT_AS_IT_IS)
def test_a_closing_with_a_name_after_it_and_a_finished_courtesy_sentence_stay(body):
    assert mail_compose.without_dangling_close(body) == body


def test_no_accepted_body_ends_with_a_closing_formula_alone_over_every_listed_formula():
    formulas = ["Atenciosamente", "Abra\u00e7os", "Att", "Cordialmente", "Obrigado", "Obrigada", "Best regards", "Regards", "Kind regards", "Saludos", "Cordialement",
                "Mit freundlichen Gr\u00fc\u00dfen", "Cordiali saluti"]
    for formula in formulas:
        for ending in (formula + ",", formula, formula.upper() + ",", formula + ",\n[Your name]"):
            got = mail_compose.validate(json.dumps({"subject": "S", "body": "Hello,\n\nCould we meet?\n\n" + ending}), TO, None)
            assert got["body"] == "Hello,\n\nCould we meet?", (formula, ending)
    assert mail_compose.validate(json.dumps({"subject": "S", "body": "Atenciosamente,"}), TO, None) is None, "a body that was only a closing is no body"


def test_vacuity_the_oracle_of_the_closing_sees_a_planted_dangling_one():
    last = lambda body: [line for line in body.split("\n") if line.strip()][-1].strip().lower().rstrip(",")
    assert last("Hello,\n\nOk.\n\nBest regards,") == "best regards", "the plant is a closing formula on its own last line"
    for body, _kept in DANGLING:
        assert last(mail_compose.validate(json.dumps({"subject": "S", "body": body}, ensure_ascii=False), TO, None)["body"]) not in ("best regards", "atenciosamente", "saludos", "cordialement", "cordiali saluti", "att", "abra\u00e7os", "obrigado")


# --- the prompt (S12) ------------------------------------------------------------------------------------------------------------------------------------


def test_the_prompt_asks_for_correct_spelling_and_accents_in_the_subject_and_the_body_and_no_dangling_closing():
    text = mail_compose.prompt_template()
    assert "Write the subject and the body with the correct spelling, accents and punctuation of that language, even when the description is typed without accents" in text
    assert "copy it into \"subject\" with only its spelling and accents corrected: the same words in the same order" in text
    assert "never a closing formula alone such as \"Best regards,\"" in text and "a placeholder for one such as [Your name]" in text


# --- S13b: the subject is taken word by word --------------------------------------------------------------------------------------------------------------
# One word that fails the rule no longer keeps the whole typed subject unaccented: the whole subject must still pass the frame (NFKC-stable, no format or control character, the typed
# scripts, the same non-letters in the same places, the same number of words), and then each word is the model's when it may stand for the typed word, else the typed one.

SPELLING_MERGED = [      # (typed, the model's subject, the subject that stays): the words that pass are taken, the others stay as typed
    ("Reuniao sobre o Openhora", "Reuni\u00e3o sobre o OpenHora", "Reuni\u00e3o sobre o Openhora"),      # the case of the live card: the capital inside a name changed
    ("Reuniao sobre Openhora", "Reuni\u00e3o sobre openhora", "Reuni\u00e3o sobre Openhora"),
    ("Reuniao sobre openhora", "Reuni\u00e3o sobre Openhora", "Reuni\u00e3o sobre openhora"),
    ("reuniao sobre Openhora", "reuni\u00e3o sobre OPENHORA", "reuni\u00e3o sobre Openhora"),
    ("reuniao ana", "Reuniao Ana", "Reuniao ana"),      # the capital of the first word is taken, the name's is not
    ("Reuniao dia 12 Openhora", "Reuni\u00e3o dia 12 OpenHora", "Reuni\u00e3o dia 12 Openhora"),
]


@pytest.mark.parametrize("typed, shown, expected", SPELLING_MERGED)
def test_the_subject_is_taken_word_by_word_and_every_word_that_fails_the_rule_stays_as_typed(typed, shown, expected):
    got = mail_compose.spelled(typed, shown)
    assert got == expected and subject_violations(typed, got) == []
    words = lambda text: re.findall(r"[^\W_]+", text)
    assert all(new in (old, model) for old, model, new in zip(words(typed), words(shown), words(got))), "no word is anyone's but the typed one or the model's"


def test_vacuity_the_whole_subject_predicate_alone_refuses_the_live_case_so_the_old_rule_kept_it_unaccented():
    assert mail_compose._same_words("Reuniao sobre o Openhora", "Reuni\u00e3o sobre o OpenHora") is False
    assert mail_compose.spelled("Reuniao sobre o Openhora", "Reuni\u00e3o sobre o OpenHora") != "Reuniao sobre o Openhora"


@pytest.mark.parametrize("typed, shown", [("Reuniao amanha", "Convite hoje"), ("Openhora ABC", "OpenHora abc"), ("Ana Silva", "Eva Souza"), ("a b", "x y")])
def test_a_subject_whose_every_word_fails_the_rule_stays_as_typed_byte_for_byte(typed, shown):
    assert mail_compose.spelled(typed, shown) == typed


@pytest.mark.parametrize("typed, shown", [("Reuniao sobre o Openhora", "Reuni\u00e3o sobre o OpenHora\u200b"), ("Reuniao sobre o Openhora", "Reunia\u0303o sobre o OpenHora"),
                                          ("Reuniao sobre o Openhora", "Reuni\u00e3o sobre o OpenHora."), ("Reuniao sobre o Openhora", "Reuni\u00e3o sobre OpenHora"),
                                          ("Reuniao sobre o Openhora", "\u0420euni\u00e3o sobre o OpenHora"), ("Reuniao dia 12", "Reuni\u00e3o dia 13"), ("Reuniao", "Reuni\u00e3o a@b.example"),
                                          ("Reuniao sobre o Openhora", "Re: Reuni\u00e3o sobre o OpenHora")])
def test_the_checks_of_the_whole_subject_still_come_before_any_word_is_taken(typed, shown):
    assert mail_compose.spelled(typed, shown) == typed      # an invisible character, a decomposed accent, a new mark, a word removed, another script, a digit, an address, a reply mark: nothing is taken


def test_only_a_word_refused_for_its_case_alone_lets_the_other_words_be_taken():
    assert mail_compose.spelled("pagar conta nao", "pegar conta sim") == "pagar conta nao", "a word refused for being another word keeps the whole typed subject"
    assert mail_compose.spelled("pagar conta nao", "pegar conta nao") == "pegar conta nao", "vacuity: with no such word the model's words are taken"
    assert mail_compose.spelled("Reuniao sobre o Openhora", "Reuni\u00e3o sobre o OpenHora") == "Reuni\u00e3o sobre o Openhora", "a capital inside a name is refused for its case alone: the accent is taken"
    assert mail_compose.spelled("Reuniao OpenHora ana", "Reuni\u00e3o Openhora Eva") == "Reuniao OpenHora ana", "a case and another word together: the whole typed subject"
