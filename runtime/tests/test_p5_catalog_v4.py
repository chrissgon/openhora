"""Catalog version 4 and prompt rule 3 (package P5, SPEC-P5-CATALOG-V4): what the served catalog and the prompt say, what the checker believes of them, and the account word on the mail act ops.

What is checked, each with this test's own literals: `LINE_CATALOG` is 4 and the interpreter is served version 4; the row `agenda` is served with the slots `day` and `target` (both spans); the text
of `items` names the calendar only in the clause "asked together" and in the sentence that sends the calendar alone to `agenda`; the six mail act ops serve the slot `service` (a word); the catalog
file is what the rows generate (`interpreter_catalog.py --check`), version 1 still hashes to what it did and the copy of version 3 hashes to what MAIL-SUMMARY-FLIP pinned; the checker believes a
mark with a `service` word and an `agenda` decision, and refused the first one under version 3; the prompt carries the second exception of rule 3, the new reply example and the new sentence of rule 9;
the seed of a mail act carries the account the word names (`microsoft` for Outlook, `google` for Gmail), with the origin `line-span`, and a word that names no account adds nothing. Offline, no
model, no network.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_p5_catalog_v4.py
"""
# validate: allow english-only -- the file holds Portuguese lines under test
from __future__ import annotations

import datetime
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import standin_tree as st

interpreter = st.load("interpreter")
interpreter_catalog = st.load("interpreter_catalog")
natural = st.load("natural")
operations = st.load("operations")
ops_interpret = st.load("ops_interpret")
ops_natural_mail = st.load("ops_natural_mail")
interpreter_pipeline = st.load("interpreter_pipeline")

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "runtime"
PINNED_HASHES = json.loads((ROOT / "scripts" / "tests" / "pinned_hashes.json").read_text(encoding="utf-8"))["pins"]
MAIL_ACTS = ("mail-reply", "mail-draft", "mail-archive", "mail-move", "mail-mark", "mail-trash")
NOW = datetime.datetime(2026, 11, 4, 14, 30, tzinfo=datetime.timezone.utc)
ZONE = "America/Sao_Paulo"
MARK_LINE = "marca o email do banco do outlook como lido"
ALLOWED = {row["op"] for row in interpreter.SERVED["ops"]}


def sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def served_text(op, catalog=None):
    return next(row["what"] for row in (catalog or interpreter.SERVED)["ops"] if row["op"] == op)


def decide(op, slots, line, catalog=None):
    obj = {"v": 1, "kind": "op", "op": op, "slots": slots}
    return interpreter.check(obj, line, None, catalog or interpreter.SERVED, NOW, ZONE, ALLOWED)


# --- the catalog -------------------------------------------------------------------------------------------------------------------------------------


def test_the_catalog_is_version_4_and_serves_agenda_with_a_day_and_a_target():
    assert operations.LINE_CATALOG == 4 and interpreter.SERVED["v"] == 4
    row = next(r for r in interpreter.SERVED["ops"] if r["op"] == "agenda")
    assert row["slots"] == {"day": "span", "target": "span"} and row["class"] == "R"
    assert natural.CLASSES["agenda"] == "R" and "agenda" in natural.NATURAL


def test_items_is_the_mail_and_names_the_calendar_only_to_send_it_to_agenda():
    text = served_text("items")
    assert text.count("calendar") == 1 and "The calendar alone is agenda." in text
    assert text.count("events") == 1 and "messages and events asked together are items too" in text
    assert "mail snapshots" in text and "in state only the words for unread or read" in text and "are a count, not a state" in text
    assert "events of the person's own calendar" in served_text("agenda") and "Not the mail (items), not reminders (reminders)." in served_text("agenda")


def test_the_six_mail_act_ops_serve_the_account_word_and_say_when_to_use_it():
    served = {row["op"]: row for row in interpreter.SERVED["ops"]}
    for op in MAIL_ACTS:
        assert served[op]["slots"]["service"] == "word", op
        assert "service only when the line says Gmail or Outlook." in served[op]["what"], op
    assert "service" not in served["mail-send"]["slots"], "the card that sends a new e-mail has no account word: its account is asked or configured"
    assert served["items"]["slots"]["service"] == "word" and "service only when the line says Gmail or Outlook." in served["items"]["what"], "P5b: the list of the mail takes the account word"
    assert "or the recipient's name as the line writes it" in served["mail-send"]["what"], "P5b: a recipient's name stays in to"
    assert served["mail-send"]["slots"]["to"] == "word"


def test_the_routine_rows_the_series_and_the_file_name_are_worded_as_the_spec_says():
    for op in ("routine-pause", "routine-cancel", "routine-change"):
        text = served_text(op)
        assert "only when the line names a routine (rotina, routine) or its number" in text and "event-cancel or event-change" in text, op
    assert "A whole repeating series too (todas, a série inteira, all of them): target holds the event's words." in served_text("event-cancel")
    assert "orcamento-teste, contrato.pdf" in served_text("file-ask") and "file is the name alone, without planilha, arquivo, documento or the drive" in served_text("file-ask")
    assert "Never when the line holds a name that looks like a file's (that is file-ask)." in served_text("ask")


def test_the_catalog_file_is_what_the_rows_generate_version_1_is_unchanged_and_the_copy_of_version_3_is_the_flips():
    done = subprocess.run([sys.executable, str(RUNTIME / "interpreter_catalog.py"), "--check"], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    assert sha(interpreter_catalog.generate(version=1)) == PINNED_HASHES["interpreter_catalog_blite"]
    recorded1 = json.loads((ROOT / "evals" / "interpreter" / "replay" / "catalogs" / "catalog-a77f8a8f.json").read_text(encoding="utf-8"))
    assert sha(recorded1) == PINNED_HASHES["interpreter_catalog_blite"]
    recorded3 = json.loads((ROOT / "evals" / "interpreter" / "replay" / "catalogs" / "catalog-aed31af3.json").read_text(encoding="utf-8"))
    assert sha(recorded3) == PINNED_HASHES["interpreter_catalog_mail_ask"], "a byte copy of the catalog that was served from MAIL-SUMMARY-FLIP to RESERVE-V3"
    assert (ROOT / "evals" / "interpreter" / "replay" / "catalogs" / "catalog-aed31af3.json").read_bytes() != (RUNTIME / "interpreter_catalog.json").read_bytes()
    assert sha(json.loads((RUNTIME / "interpreter_catalog.json").read_text(encoding="utf-8"))) == PINNED_HASHES["interpreter_catalog_v4"] == interpreter.SERVED_SHA256
    assert "agenda" not in {row["op"] for row in recorded3["ops"]} and all("service" not in row["slots"] for row in recorded3["ops"] if row["op"] in MAIL_ACTS)


# --- the checker -------------------------------------------------------------------------------------------------------------------------------------


def test_a_mark_with_the_account_word_and_an_agenda_decision_are_ops_and_the_mark_was_refused_at_version_3(monkeypatch):
    slots = {"target": "do banco", "state": "lido", "service": "outlook"}
    got = decide("mail-mark", slots, MARK_LINE)
    assert got["kind"] == "op" and got["op"] == "mail-mark" and got["args"].get("account") == "outlook", got
    agenda = decide("agenda", {"day": "amanhã"}, "o que eu tenho amanhã?")      # validate: allow english-only -- the Portuguese line under test
    assert agenda["kind"] == "op" and agenda["op"] == "agenda" and agenda["spans"] == {"day": "amanhã"}, agenda      # validate: allow english-only -- the Portuguese line under test
    recorded3 = json.loads((ROOT / "evals" / "interpreter" / "replay" / "catalogs" / "catalog-aed31af3.json").read_text(encoding="utf-8"))
    classes3, table3 = natural.views(3)      # the router's table as it was at version 3 (the checker reads the catalog and the table together)
    monkeypatch.setattr(natural, "CLASSES", classes3)
    monkeypatch.setattr(natural, "NATURAL", table3)
    monkeypatch.setattr(interpreter, "SERVED_SHA256", PINNED_HASHES["interpreter_catalog_mail_ask"])      # the checker believes only the catalog it serves: serve version 3 for this case
    before = decide("mail-mark", slots, MARK_LINE, recorded3)
    assert before["kind"] != "op" and before.get("error") == "E_SLOT_UNKNOWN", before
    assert decide("agenda", {"day": "amanhã"}, "o que eu tenho amanhã?", recorded3)["kind"] != "op", "version 3 had no agenda"      # validate: allow english-only -- the Portuguese line under test


def test_a_span_that_is_not_in_the_line_is_still_refused_on_the_new_slot():
    got = decide("mail-mark", {"target": "do banco", "state": "lido", "service": "gmail"}, MARK_LINE)
    assert got["kind"] != "op" and got.get("error") == "E_SPAN", got


def test_items_takes_the_account_word_and_refused_it_before_round_2():
    line = "mostra os e-mails não lidos do outlook"      # validate: allow english-only -- the Portuguese line under test
    got = decide("items", {"state": "não lidos", "service": "outlook"}, line)      # validate: allow english-only -- the Portuguese words under test
    assert got["kind"] == "op" and got["op"] == "items" and got["spans"] == {"state": "não lidos", "service": "outlook"}, got      # validate: allow english-only -- the Portuguese words under test
    assert got["args"].get("service_word") == "outlook", got
    bad = decide("items", {"state": "não lidos", "service": "gmail"}, line)      # validate: allow english-only -- the Portuguese words under test
    assert bad["kind"] != "op" and bad.get("error") == "E_SPAN", "a word that is not in the line is refused on the new slot too"
    assert "service" not in {slot for row in interpreter.SERVED["ops"] if row["op"] == "agenda" for slot in row["slots"]}, "P5b: agenda has no account word"


def test_a_recipient_name_without_an_address_is_an_op_with_the_name_in_to_and_the_mail_step_asks_for_it():
    line = "manda um e-mail pro Gustavo"      # validate: allow english-only -- the Portuguese line under test
    got = decide("mail-send", {"to": "Gustavo"}, line)
    assert got["kind"] == "op" and got["op"] == "mail-send" and got["spans"] == {"to": "Gustavo"}, got
    seen = interpreter_pipeline.with_mail_step(got, line, NOW.replace(tzinfo=None), ZONE, "pt-BR")
    assert seen["kind"] == "clarify" and seen["slot"] == "to", "the scorer mirrors the product: the name is kept and code asks for the address"
    assert interpreter_pipeline.with_mail_step(decide("mail-send", {"to": "priya@example.test", "body": "hi"}, "send hi to priya@example.test"), "send hi to priya@example.test", NOW.replace(tzinfo=None), ZONE, "en")["kind"] == "op", "control: a complete send is not asked"


# --- the prompt --------------------------------------------------------------------------------------------------------------------------------------


def prompt_text() -> str:
    return (RUNTIME / "interpreter_prompt.txt").read_text(encoding="utf-8")


def test_the_prompt_carries_the_second_exception_of_rule_3_the_new_example_and_the_new_sentence_of_rule_9():
    prompt = prompt_text()
    rule3 = next(line for line in prompt.splitlines() if line.startswith("3. "))
    assert ("A second exception, for ops of class [E] that code completes by asking: when the line names such an op and leaves out the text of the e-mail, the reply or the draft, or gives the recipient's "
            "name but no address, name the op with the slots the line gives: a name given for the recipient goes in \"to\" as the line writes it, and only the missing text or address is left out; "
            "never answer clarify for them. Code asks the person for them.") in rule3
    assert "names the recipient by a name instead of an address" not in prompt, "P5b: the old words are gone"
    assert rule3.index("One exception, for ops of class [R]") < rule3.index("A second exception")
    assert 'line: reply to the email from Dana about the budget\n{"v":1,"kind":"op","op":"mail-reply","slots":{"target":"Dana about the budget"}}' in prompt
    reply = 'line: reply to the email from Dana about the budget\n{"v":1,"kind":"op","op":"mail-reply","slots":{"target":"Dana about the budget"}}\n\n'
    assert reply + 'line: write an e-mail to Priya\n{"v":1,"kind":"op","op":"mail-send","slots":{"to":"Priya"}}\n\nline: plan a three-day workshop' in prompt, "P5b: the new example stands right after the reply example"
    assert "write to Ana about the invoice" not in prompt and '"kind":"clarify","slot":"to"' not in prompt
    rule9 = next(line for line in prompt.splitlines() if line.startswith("9. "))
    assert ("Words that only say which items the person meant (the e-mails or the calendar; the unread ones; this morning's) keep the op of frame.last: items and agenda are one list here, "
            "and code reads which one from the line.") in rule9
    assert "the e-mails, not the calendar" not in rule9
    assert interpreter.build_messages(interpreter.SERVED, NOW, ZONE, None, "o que eu tenho amanhã?")[0].count("agenda") >= 2, "the catalog the model reads names the row"      # validate: allow english-only -- the Portuguese line under test
    assert hashlib.sha256(prompt.encode("utf-8")).hexdigest() == PINNED_HASHES["interpreter_prompt"] != PINNED_HASHES["interpreter_prompt_9e63"]


# --- the account word on a mail act: the seed --------------------------------------------------------------------------------------------------------


def seed_of(line, slots, op="mail-mark"):
    decision = decide(op, slots, line)
    assert decision["kind"] == "op", decision
    return ops_natural_mail.mail_target_seed(op, decision, None, line, service=ops_interpret._service_of(decision, line))


def test_the_seed_of_a_mail_act_carries_the_account_the_word_names():
    outlook = seed_of(MARK_LINE, {"target": "do banco", "state": "lido", "service": "outlook"})
    assert outlook["slots"]["account"] == "microsoft" and outlook.origins["account"] == "line-span" and outlook["slots"]["words"] == ["banco"]
    gmail = seed_of("archive the newsletter email in gmail", {"target": "the newsletter email", "service": "gmail"}, "mail-archive")
    assert gmail["slots"]["account"] == "google" and gmail.origins["account"] == "line-span"
    trash = seed_of("apaga o e-mail da promoção do gmail", {"target": "da promoção", "service": "gmail"}, "mail-trash")      # validate: allow english-only -- the Portuguese line under test
    assert trash["slots"]["account"] == "google"


def test_vacuity_without_the_word_or_with_a_word_that_names_no_account_the_seed_adds_no_account():
    plain = seed_of(MARK_LINE, {"target": "do banco", "state": "lido"})
    assert "account" not in plain["slots"] and "account" not in plain.origins, "no word: the family asks which box"
    decision = decide("mail-mark", {"target": "do banco", "state": "lido", "service": "outlook"}, MARK_LINE)
    for word in ("dropbox", "banco", "microsoft365", ""):
        poisoned = dict(decision, args=dict(decision["args"], account=word), spans=dict(decision["spans"], service=word))
        seed = ops_natural_mail.mail_target_seed("mail-mark", poisoned, None, MARK_LINE, service=ops_interpret._service_of(poisoned, MARK_LINE))
        assert "account" not in seed["slots"], word
    elsewhere = dict(decision, args=dict(decision["args"], account="gmail"), spans=dict(decision["spans"], service="gmail"))
    assert "account" not in ops_natural_mail.mail_target_seed("mail-mark", elsewhere, None, MARK_LINE, service=ops_interpret._service_of(elsewhere, MARK_LINE))["slots"], "a brand word the line does not hold is unreadable: nothing is added"


def test_the_seed_of_a_mail_act_named_by_number_carries_the_account_too():
    line = "marca o email 3 do outlook como lido"
    decision = decide("mail-mark", {"messages": "3", "state": "lido", "service": "outlook"}, line)
    assert decision["kind"] == "op" and decision["args"].get("messages") == [3], decision
    seed = ops_natural_mail.mail_number_seed("mail-mark", decision, line, service=ops_interpret._service_of(decision, line))
    assert seed is not None and seed["by"] == "numbers" and seed["slots"]["numbers"] == [3]
    assert seed["slots"]["account"] == "microsoft" and seed.origins["account"] == "line-span" and seed.origins["numbers"] == "line-number"
    bare = decide("mail-mark", {"messages": "3", "state": "lido"}, "marca o email 3 como lido")
    again = ops_natural_mail.mail_number_seed("mail-mark", bare, "marca o email 3 como lido", service=ops_interpret._service_of(bare, "marca o email 3 como lido"))
    assert again is not None and "account" not in again["slots"]
    poisoned = dict(decision, args=dict(decision["args"], account="dropbox"), spans=dict(decision["spans"], service="dropbox"))
    assert "account" not in ops_natural_mail.mail_number_seed("mail-mark", poisoned, line, service=ops_interpret._service_of(poisoned, line))["slots"]
