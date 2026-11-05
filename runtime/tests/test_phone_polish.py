"""What a phone reads of a card, a date and an approval (package LIVE-2; runtime/messaging_bridge.py, messaging_cards.py, messaging_outcome.py, messaging_failure.py,
phrases.py): the first live card of a project that writes in Portuguese worked end to end, and the polish it asked for.

  1. dates in the project's language ("qua 21/10/2026 13:00–14:00"), rendering only: the stored card, its hash and the approval are of the stored text;
  2. no sha256 line on a phone card, while the button still binds to the stored hash and a changed card is refused;
  3. the card's title is a plain word of the kind ("pedido #3", "request #3"), not "efeito"/"effect";
  4. the line that says a card waits is not sent when the card itself was just sent to the same chat, and stays where no card was shown;
  5. after an approval the chat is told what was done in plain words, or why it was not, with no step name, no command and no hash.

Over the real operations layer with the W1 stand-in writers (test_calendar_write.py's world) and a stand-in messenger; offline, no model; every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_phone_polish.py
"""
from __future__ import annotations

import json

import pytest

import phone_said as ps
import phrase_kit as pk
import standin_tree as st
from test_calendar_write import world  # noqa: F401  (the calendar world)
from test_messaging import decision, wait_for, world as fake_world  # noqa: F401  (the stand-in world: a fake operations object)
from test_messaging_natural_writes import OWNER, day, forget  # noqa: F401  (the real-operations bridge over the calendar world)
from closed_heads import closed_heads, tier1_forms, words_interpreted  # noqa: F401  (S41-11: the claim of the write families and of every closed form, as fixtures: these tests are about the readers and resolvers, not the claim)

pytestmark = pytest.mark.usefixtures("tier1_forms", "words_interpreted")      # S41-11: every closed form claims a line in this file, as it did

ops = st.load("ops")
bridge = st.load("messaging_bridge")
cards = st.load("messaging_cards")
outcome = st.load("messaging_outcome")
failure = st.load("messaging_failure")
guard = st.load("messaging_guard")
phrases = st.load("phrases")

LINE = "marca dentista quinta às 10h no google"      # validate: allow english-only -- a line the person types in Portuguese
THURSDAY = "Thu 22/10/2026 10:00-11:00"
PT = {"language": "pt-BR"}


def configure(day, language=None, approve=False, page_url=None):
    """Rewrite the project's configuration (language, the owner's right to approve a calendar effect, the page link) and accept it, widening what it must."""
    file = day.path + "/docs/workbench/runtime.json"
    raw = json.loads(open(file).read())
    if language:
        raw["language"] = language
    if approve:
        raw["policies"]["owner"] = [*raw["policies"]["owner"], "approve-effect-calendar"]
    if page_url:
        raw["messaging"]["page_url"] = page_url
    open(file, "w").write(json.dumps(raw))
    shown = ops.config(day.path)
    ops.accept_config(day.path, shown["sha256"], widen=shown["widening_sha256"])


def the_card(day):
    return next(r["message"] for r in reversed(day.sent(OWNER)) if "dentista" in r["message"]["text"] or "Dentista" in r["message"]["text"])


# --- 1. dates in the language ----------------------------------------------------------------------------------------------------


def test_a_card_says_the_weekday_in_the_projects_language_and_an_english_project_is_unchanged(day):
    day.say(OWNER, LINE)
    assert THURSDAY in the_card(day)["text"], "no language: the English abbreviation and the hyphen, as always"
    configure(day, language="pt-BR")
    day.say(OWNER, LINE)
    card = the_card(day)["text"]
    assert "qui 22/10/2026 10:00– 11:00".replace("– ", "–") in card and "Thu" not in card, card


def test_the_stored_card_its_hash_and_the_approval_are_of_the_stored_text_whatever_the_language(day):
    configure(day, language="pt-BR", approve=True)
    day.say(OWNER, LINE)
    [entry] = [e for e in ledger_cards(day) if e["kind"] == "effect"]
    started = [i for i in ops.pending(day.path)["pending"] if i["kind"] == "effect"][0]
    full = ops.pending(day.path, started["id"])
    assert THURSDAY in full["body"], "the stored body is English, with the English weekday"
    assert entry["content_sha256"] == full["payload_sha256"]


def ledger_cards(day):
    return day.bridge.ledger.data["cards"]


def test_the_dates_of_a_reply_are_said_in_the_language_too(fake_world):
    def told(line):
        before = len(fake_world.texts())
        fake_world.say(line)
        for thread in list(fake_world.bridge.threads):      # the reply is sent from a job: it is waited for, not guessed
            thread.join(30)
        assert wait_for(lambda: len(fake_world.texts()) > before)
        return fake_world.texts()[-1]
    fake_world.config["language"] = "pt-BR"
    fake_world.fake.answers["say"] = {"reply": "Quando: Wed 21/10/2026 13:00-14:00 (America/Sao_Paulo)", "request_id": 1, "pending_id": None, "ran": True, "queued": False}
    assert told("o que tenho?") == "Quando: qua 21/10/2026 13:00\u201314:00 (America/Sao_Paulo)"
    fake_world.config.pop("language")
    assert told("what do I have?") == "Quando: Wed 21/10/2026 13:00-14:00 (America/Sao_Paulo)"


def test_only_the_shape_of_a_date_is_read_so_a_word_of_a_persons_text_is_never_changed():
    cfg = {"language": "pt-BR"}
    assert phrases.localize_dates("Wed 21/10/2026 13:00-14:00", cfg) == "qua 21/10/2026 13:00–14:00"
    assert phrases.localize_dates("Mon 05/01/2027 09:00-10:30 and Sun 01/11/2026 08:00", cfg) == "seg 05/01/2027 09:00–10:30 and dom 01/11/2026 08:00"
    for text in ("Wed is a day", "Wed 5/1/2027", "the Mon 21/10 plan", "room 13:00-14:00", "Wednesday 21/10/2026"):
        assert phrases.localize_dates(text, cfg) == text, text
    assert phrases.localize_dates("Wed 21/10/2026 13:00-14:00", None) == "Wed 21/10/2026 13:00-14:00"
    assert phrases.localize_dates("Wed 21/10/2026 13:00-14:00", {"language": "fr"}) == "Wed 21/10/2026 13:00-14:00", "a tag with no table is English"
    assert phrases.localize_dates(None, cfg) is None
    assert [phrases.text(k, cfg) for k in phrases.WEEKDAY_KEYS] == ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]  # validate: allow english-only -- the weekday words of the pt-BR column


# --- 2 and 3. the hash is not printed, the kind is a plain word --------------------------------------------------------------------


def test_a_phone_card_prints_no_hash_says_pedido_in_portuguese_and_request_in_english(day):
    configure(day, approve=True)
    day.say(OWNER, LINE)
    card = the_card(day)
    assert "request #" in card["text"] and "effect #" not in card["text"]
    assert "sha256" not in card["text"] and cards.APPROVES_LINE in card["text"] and [a["label"] for a in card["actions"]]
    configure(day, language="pt-BR")
    day.say(OWNER, LINE)
    card = the_card(day)
    assert "pedido #" in card["text"] and "efeito" not in card["text"] and "sha256" not in card["text"]
    pk.assert_said(card["text"], "APPROVES_LINE", PT)


def test_the_kind_words_are_plain_in_both_columns():
    assert [phrases.kind_word(k, None) for k in ("plan", "effect", "question", "review", "acceptance")] == ["plan", "request", "question", "review", "acceptance"]
    assert [phrases.kind_word(k, {"language": "pt-BR"}) for k in ("plan", "effect", "question", "review", "acceptance")] == [
        "plano", "pedido", "pergunta", "revisão", "aceite"]  # validate: allow english-only -- the pt-BR words


def test_the_button_still_binds_to_the_stored_hash_and_a_card_that_changed_is_refused(day):
    configure(day, language="pt-BR", approve=True)
    day.say(OWNER, LINE)
    card = the_card(day)
    [approve] = [a for a in card["actions"] if "Aprovar" in a["label"] or "exact" in a["label"].lower() or "exato" in a["label"].lower()] or [card["actions"][0]]
    item = [i for i in ops.pending(day.path)["pending"] if i["kind"] == "effect"][0]
    stored = ops.pending(day.path, item["id"])
    [entry] = [e for e in ledger_cards(day) if e["pending_id"] == item["id"]]
    assert entry["content_sha256"] == stored["payload_sha256"] and "sha256" not in card["text"]
    ops.reject(day.path, item["id"], channel="terminal")      # the effect is gone: a tap on the old card is refused and writes nothing
    day.say(OWNER, "", action=approve["id"])
    assert day.world["google"].requests == [] and day.texts(OWNER)[-1] != phrases.text("APPROVED", {"language": "pt-BR"}, id=item["id"])


# --- 4. the card says it waits, once ------------------------------------------------------------------------------------------------


def test_a_doubt_about_the_date_is_still_told_beside_the_card(day):
    day.say(OWNER, "marca dentista dia 30 às 10h no google")
    assert not any(pk.said(t, "ACCT_CARD_SENT") for t in day.texts(OWNER))


# --- 5. what was done, in plain words -------------------------------------------------------------------------------------------------


def tap(day):
    """Approve the owner's effect card by its button; returns the text that follows."""
    message = the_card(day)
    [approve] = [a for a in message["actions"] if a["label"] in (phrases.text("EFFECT_LABEL", None), phrases.text("EFFECT_LABEL", {"language": "pt-BR"}))]
    before = len(day.texts(OWNER))
    day.say(OWNER, "", action=approve["id"])
    wait_for(lambda: len(day.texts(OWNER)) > before)
    return day.texts(OWNER)[before:]


def test_after_an_approval_the_chat_is_told_what_was_done_in_plain_words(day):
    configure(day, language="pt-BR", approve=True)
    day.say(OWNER, "marca Dentista da Júlia quinta às 10h no google")
    told = tap(day)
    assert pk.said(told[-1], "OUT_CAL_CREATE", PT, title="Dentista da Júlia", service=phrases.text("OUT_CAL_GOOGLE", PT)), told
    assert "sha256" not in told[-1] and "#" not in told[-1] and guard.find(told[-1]) == []
    assert len(day.world["google"].writes()) == 1, "written once"


def test_the_outcome_sentences_of_every_kind_of_account_write_in_both_languages():
    en, pt = None, PT
    event = {"effect_word": "calendar", "payload": {"card": [["CARD_CAL_TITLE", {"title": "Dentist"}], ["CARD_CAL_WHEN", {"when": "Wed 21/10/2026 13:00-14:00 (America/Sao_Paulo)"}]]}}
    done = {"done": True, "replayed": False, "operation": "create", "account": "google"}
    when = "Wed 21/10/2026 13:00-14:00 (America/Sao_Paulo)"

    def google(cfg):
        return phrases.text("OUT_CAL_GOOGLE", cfg)
    pk.assert_said(outcome.sentence(event, done, en), "OUT_CAL_CREATE", en, title="Dentist", when=when, service=google(en))
    pk.assert_said(outcome.sentence(event, dict(done, operation="change", account="microsoft"), pt), "OUT_CAL_CHANGE", pt, title="Dentist", when=when, service=phrases.text("OUT_CAL_MICROSOFT", pt))
    pk.assert_said(outcome.sentence(event, dict(done, operation="cancel"), en), "OUT_CAL_CANCEL", en, service=google(en))
    pk.assert_said(outcome.sentence({"effect_word": "calendar"}, done, en), "OUT_CAL_CREATE_BARE", en, service=google(en))      # the card showed no title: none is said
    pk.assert_said(outcome.sentence(event, dict(done, replayed=True), en), "OUT_REPLAYED", en)
    box = {"effect_word": "mailbox"}
    pk.assert_said(outcome.sentence(box, {"done": True, "action": "archive", "count": 3}, en), "OUT_BOX_ARCHIVE", en, n=3)
    pk.assert_said(outcome.sentence(box, {"done": True, "action": "mark", "state": "unread", "count": 2}, en), "OUT_BOX_UNREAD", en, n=2)
    pk.assert_said(outcome.sentence(box, {"done": True, "action": "trash", "count": 1}, pt), "OUT_BOX_TRASH", pt, n=1)
    pk.assert_said(outcome.sentence(box, {"done": True, "action": "draft", "count": 1}, en), "OUT_BOX_DRAFT", en)
    files = {"effect_word": "files"}
    pk.assert_said(outcome.sentence(files, {"written": True, "operation": "create", "account": "microsoft"}, en), "OUT_FILE_CREATE", en, service=phrases.text("OUT_ACCT_MICROSOFT", en))
    pk.assert_said(outcome.sentence({"effect_word": "send"}, {"sent": True, "reply": True}, en), "OUT_MAIL_REPLIED", en)
    pk.assert_said(outcome.sentence({"effect_word": "send"}, {"sent": True, "reply": False}, pt), "OUT_MAIL_SENT", pt)
    for item, result in ((event, None), (event, {"done": False}), ({"effect_word": "publish"}, {"done": True}), (None, done), (event, {"done": True, "operation": "teleport"})):
        assert outcome.sentence(item, result, en) is None, (item, result)
    pk.assert_said(outcome.sentence({"effect_word": "calendar", "payload": {"card": [["CARD_CAL_DROP_TITLE", {"title": "Secret"}]]}}, dict(done, operation="change"), en), "OUT_CAL_CHANGE_BARE", en, service=google(en))


def test_a_result_the_module_cannot_say_gets_the_plain_approval(fake_world):
    from test_channel_grants_cards import GRANTED, approve_action, effect, grant
    grant(fake_world, GRANTED)
    fake_world.items[7] = effect()
    fake_world.bridge.tick()
    fake_world.fake.answers["approve"] = {"task_state": "done"}
    fake_world.say(None, action=approve_action(fake_world))
    assert wait_for(lambda: pk.said(fake_world.texts()[-1], "APPROVED", id=7))


def test_an_approval_that_ran_says_the_outcome_to_the_chat_that_approved(fake_world):
    from test_channel_grants_cards import OPEN_POLICY, approve_action, effect, grant
    grant(fake_world, [*OPEN_POLICY, "approve-effect-calendar"])
    lines = [["CARD_CAL_TITLE", {"title": "Dentist"}], ["CARD_CAL_WHEN", {"when": "Wed 21/10/2026 13:00-14:00 (America/Sao_Paulo)"}]]
    assert phrases.card_valid(lines)
    fake_world.items[7] = effect(word="calendar", body=phrases.card_text(lines), payload={"card": lines})
    fake_world.bridge.tick()
    fake_world.fake.answers["approve"] = {"task_state": "done", "result": {"done": True, "replayed": False, "operation": "create", "account": "google"}}
    fake_world.say(None, action=approve_action(fake_world))
    assert wait_for(lambda: pk.said(fake_world.texts()[-1], "OUT_CAL_CREATE", title="Dentist", when="Wed 21/10/2026 13:00-14:00 (America/Sao_Paulo)", service=phrases.text("OUT_CAL_GOOGLE", None)))


# --- 5. and why it was not -----------------------------------------------------------------------------------------------------------


class Refusal(Exception):
    code = 1


ONEDRIVE = ("FAIL_SERVICE_FILES_MICROSOFT",)      # a field that is a tuple is a sentence of the table said in the language of the phone


def resolved(fields, cfg):
    return {name: phrases.text(value[0], cfg) if isinstance(value, tuple) else value for name, value in fields.items()}


def failed_with(text, key, fields, cfg):
    """True when `text` is the sentence of `key` with `fields` in the language of `cfg` (a place at the end is the page)."""
    fields = resolved(fields, cfg)
    return ps.placed(text, key, cfg, **fields) if key in ("FAIL_NOT_AUTHORIZED", "FAIL_NOT_DONE") else pk.said(text, key, cfg, **fields)


@pytest.mark.parametrize("text,code,key,fields", [
    ("storageQuotaExceeded: the drive is full", 1, "FAIL_QUOTA", {"service": ONEDRIVE}),
    ("the file is too large for the service", 1, "FAIL_TOO_LARGE", {}),
    ("a file with that name already exists", 1, "FAIL_NAME_TAKEN", {}),
    ("the account is not authorized", 1, "FAIL_NOT_AUTHORIZED", {"service": ONEDRIVE}),
    ("anything", 3, "FAIL_NOT_AUTHORIZED", {"service": ONEDRIVE}),
    ("the request timed out", 1, "FAIL_NETWORK", {"service": ONEDRIVE}),
    ("HTTP 503 from the service", 1, "FAIL_NETWORK", {"service": ONEDRIVE}),
    ("the writer's answer is not a finished request: the change may or may not have been made", 1, "FAIL_UNKNOWN", {"place": ("FAIL_LOOK_FILES",)}),
    ("a thing nobody foresaw", 1, "FAIL_NOT_DONE", {}),
])
def test_a_failed_approval_is_told_by_the_words_of_its_cause_and_never_by_the_engines_text(text, code, key, fields):
    error = ops.OpsError(f"nothing was written: {text}; the effect stays open, and approving it again with the same hash tries again", code)
    english = failure.from_error(error, None, word="files", account="microsoft")
    assert failed_with(english, key, fields, None), english
    said = failure.from_error(error, PT, word="files", account="microsoft")
    assert failed_with(said, key, fields, PT) and said != english and guard.find(said) == [] and "hash" not in said and "effect stays open" not in said and text not in said, said


def test_the_onedrive_folder_that_could_not_be_read_is_told_with_its_name_and_a_hint_and_no_step_jargon():
    said = failure.from_step("file-write", "microsoft", "refused", "folder", "default", {"language": "pt-BR"})
    assert said.startswith(phrases.text("FAIL_FOLDER", PT, folder="default", service=phrases.text("FAIL_SERVICE_FILES_MICROSOFT", PT))) and said.endswith(phrases.text("FAIL_FOLDER_HINT", PT))
    for jargon in ("prepare", "refused", "error", "task", "start this task again"):
        assert jargon not in said
    english = failure.from_step("file-write", "microsoft", "provider_failed", "folder", "reports", None)
    assert english.startswith(phrases.text("FAIL_FOLDER", None, folder="reports", service=phrases.text("FAIL_SERVICE_FILES_MICROSOFT", None))) and english.endswith(phrases.text("FAIL_FOLDER_HINT", None))
    assert not failure.from_step("file-write", "google", "refused", "folder", "reports", None).endswith(phrases.text("FAIL_FOLDER_HINT", None))


@pytest.mark.parametrize("code,field,key", [
    ("not_configured", "", "FAIL_NOT_AUTHORIZED"), ("refused", "file", "FAIL_FILE"), ("provider_failed", "", "FAIL_NETWORK"), ("refused", "", "FAIL_REFUSED"), ("gone", "file", "FAIL_GONE"),
    ("name_taken", "name", "FAIL_NAME_TAKEN"), ("file_too_large", "content", "FAIL_TOO_LARGE"), ("something_new", "x", "FAIL_NOT_DONE"),
])
def test_every_closed_code_of_a_failed_preparation_has_a_plain_sentence_in_both_languages(code, field, key):
    for cfg in (None, {"language": "pt-BR"}):
        said = failure.from_step("file-write", "google", code, field, "default", cfg)
        assert said and guard.find(said) == [] and "_" not in said and "prepare" not in said
        assert said.startswith(phrases.text(key, cfg, service="Google Drive", folder="default", where="")[:10].rstrip())
    pk.assert_said(failure.from_step("calendar-event", "microsoft", "provider_failed", "", None, None), "FAIL_NETWORK", None, service=phrases.text("OUT_CAL_MICROSOFT", None))
    assert failure.from_step("file-write", "google", "bad_args", "start", None, None, said="That hour does not exist on that day.") == "That hour does not exist on that day."


def test_a_refused_preparation_reaches_a_phone_as_its_plain_sentence_and_the_terminal_keeps_the_engines(day, monkeypatch):
    ops_natural_writes = st.load("ops_natural_writes")
    real = ops_natural_writes._call_operation

    def refuse(project, op, args, channel, sender):
        error = ops.OpsError("prepare: refused folder -- the folder could not be read: check that the account is authorized and that the folder is still there, then start this task again", 1)
        error.phone = failure.from_step("file-write", "microsoft", "refused", "folder", "default", None)
        raise error
    monkeypatch.setattr(ops_natural_writes, "_call_operation", refuse)
    day.say(OWNER, LINE)
    said = day.texts(OWNER)[-1]
    assert said.startswith(phrases.text("FAIL_FOLDER", None, folder="default", service=phrases.text("FAIL_SERVICE_FILES_MICROSOFT", None))) and "prepare" not in said and "error" not in said
    monkeypatch.setattr(ops_natural_writes, "_call_operation", real)


# --- the card that would have to be cut ----------------------------------------------------------------------------------------------


def test_a_granted_card_whose_text_holds_a_path_is_shown_whole_and_stays_approvable_and_the_platforms_ledger_line_is_said_as_a_file(fake_world):
    from test_channel_grants_cards import GRANTED, effect, grant, has_label
    grant(fake_world, GRANTED)
    fake_world.items[7] = effect(body="Replace the page with:\n\nOpen at nine, see /Users/ana/shop/docs/plan.md for the key.")
    fake_world.bridge.tick()
    [card] = fake_world.sent()
    assert has_label(card["message"]["actions"]) and "Open at nine, see /Users/ana/shop/docs/plan.md for the key." in card["message"]["text"], "the person's text is theirs"
    assert fake_world.bridge.ledger.data["cards"][-1]["approvable"] is True
    fake_world.items[8] = effect(number=8, body="Publish it.\nLedger (the publisher's record of the keys it published): /var/folders/ab/T/standin-ledger.json\nKey: launch")
    fake_world.bridge.tick()
    second = [s for s in fake_world.sent() if "request #8" in s["message"]["text"]][-1]["message"]
    [ledger] = [line for line in second["text"].split("\n") if line.startswith("Ledger (")]
    label, _, value = ledger.rpartition(": ")
    assert has_label(second["actions"]) and label == "Ledger (the publisher's record of the keys it published)" and pk.said(value, "PHONE_LEDGER_FILE") and "/var/folders" not in second["text"]      # literal: the label is the stand-in publisher's own line, not a table sentence
