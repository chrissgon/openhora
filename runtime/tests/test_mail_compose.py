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
    if re.search(r"[a-z0-9]\.[a-z]{2,}", plain.lower()) and not all(re.search(r"[a-z0-9]\.[a-z]{2,}", w.lower()) is None or w.strip(".,;:!?").lower() in [t.lower() for t in typed]
                                                                    for w in plain.split()):
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
]
SHAPE_BAD = [
    "not json at all", "", "[]", "null", '{"subject": "S"}', '{"body": "B"}', json.dumps({"subject": "S", "body": "B", "extra": "x"}),
    json.dumps({"subject": 5, "body": "B"}), json.dumps({"subject": "S", "body": ["B"]}), '{"subject": "S", "subject": "T", "body": "B"}',
    json.dumps({"subject": "S", "body": ""}), json.dumps({"subject": "S", "body": "   \n "}), json.dumps({"subject": "S", "body": "x" * 4001}),
    json.dumps({"subject": "Line one\nline two", "body": "B"}), json.dumps({"subject": "", "body": "B"}), json.dumps({"subject": "S" * 201, "body": "B"}),
    json.dumps({"subject": "Mail to bob@elsewhere.example", "body": "B"}), json.dumps({"subject": "Read https://elsewhere.example", "body": "B"}), json.dumps({"subject": "=?utf-8?q?x?=", "body": "B"}),
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
