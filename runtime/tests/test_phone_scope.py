"""The scope of the phone's rule (package LIVE-2, review of #490): the rule is about what the PLATFORM writes, never about what is quoted from the person's data.

  1. a card shows the body exactly (minus the private-line rules and the platform's own lines for a terminal): a title, notes, subject or text of the person's that looks like a
     command or a path is theirs, is shown whole and stays approvable ("approve exactly what you read"); only the platform's two frame lines are touched (the approve how-to
     line, the publisher's ledger path) and the hash lines of the mail and file cards are not printed (the button binds to the hash);
  2. the net under the send point (`Bridge.deliver(guard_text=True)`, `reply(guard=True)`) is for the operations layer's own error text, and never for a reply that quotes data;
  3. an outcome that is unknown is told as unknown, from the real text of each effect module and from a provider's exit 4, never as "nothing was done".

Offline, no model; every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_phone_scope.py
"""
from __future__ import annotations

import pytest

import standin_tree as st
from test_messaging import world  # noqa: F401  (the stand-in world: a fake operations object)
from test_messaging import wait_for

phrases = st.load("phrases")
operations = st.load("operations")
cards = st.load("messaging_cards")
guard = st.load("messaging_guard")
failure = st.load("messaging_failure")
outcome = st.load("messaging_outcome")
effect_calendar = st.load("effect_calendar")
effect_files = st.load("effect_files")
effect_mailbox = st.load("effect_mailbox")
effect_send = st.load("effect_send")
ops_step_effects = st.load("ops_step_effects")

HASH = "e" * 64
CAPS = {"buttons": True, "max_buttons": 6, "max_text": 4096, "documents": False, "url_buttons": True, "reply_context": True}
SENDER = "telegram:42"


def effect(card, word, title="Calendar: new event"):
    return {"id": 7, "kind": "effect", "title": title, "body": phrases.card_text(card), "status": "open", "task_id": 1, "actions": ["approved", "rejected"],
            "effect_word": word, "effect_on_cards": True, "payload_sha256": HASH, "payload": {"card": card}}


def cal(title, notes):
    return [["CARD_CAL_CREATE", {}], ["CARD_ACCOUNT", {"account": "google", "address": "pat@mail.example"}], ["CARD_CAL_CALENDAR", {"calendar": "primary"}],
            ["CARD_CAL_TITLE", {"title": title}], ["CARD_CAL_WHEN", {"when": "Thu 22/10/2026 10:00-11:00 (America/Sao_Paulo)"}],
            ["CARD_CAL_NOTES", {"notes": notes}], ["CARD_CAL_NOBODY", {}]]


def mail(subject, body):
    return [["CARD_MAIL_SEND", {}], ["CARD_MAIL_FROM_ACCOUNT", {"address": "pat@mail.example", "account": "google"}], ["CARD_MAIL_TO", {"addresses": "ana@clinic.example"}],
            ["CARD_MAIL_SUBJECT", {"subject": subject}], ["CARD_MAIL_COUNT", {"count": "1"}], ["CARD_MAIL_MESSAGE", {"body": body}], ["CARD_MAIL_HASH", {"sha": HASH}], ["CARD_MAIL_ONCE", {}]]


def reply(msgid, body):
    return [["CARD_MAIL_REPLY", {}], ["CARD_MAIL_FROM_ACCOUNT", {"address": "pat@mail.example", "account": "google"}],
            ["CARD_MAIL_REPLY_TO", {"address": "ana@clinic.example", "ref": "inbox#3", "read_at": "2026-10-20 10:00", "subject": "Re: plan"}],
            ["CARD_MAIL_IN_REPLY", {"message_id": msgid}], ["CARD_MAIL_MESSAGE", {"body": body}], ["CARD_MAIL_HASH", {"sha": HASH}],
            ["CARD_MAIL_APPROVE", {"command": "uv run runtime/cli.py approve --project ~/p --id 7 --sha256 " + HASH}], ["CARD_MAIL_ONCE", {}]]


CASES = {
    "calendar notes start with a flag": (effect(cal("School trip", "--consent forms to sign before Friday"), "calendar"), "--consent forms to sign before Friday"),
    "calendar title is a command": (effect(cal("uv run demo with the team", "none"), "calendar"), "uv run demo with the team"),
    "calendar title with a path": (effect(cal("Review /docs/q3/plan", "x"), "calendar"), "Review /docs/q3/plan"),
    "mail subject is a script": (effect(mail("python3 report.py output", "\u2502 Hi Ana"), "send-own"), "python3 report.py output"),
    "mail body with uv run": (effect(mail("Hello", "\u2502 Hi Ana\n\u2502 to try it: uv run app.py --project acme\n\u2502 Pat"), "send-own"), "to try it: uv run app.py --project acme"),
    "mail body with keyring": (effect(mail("Hello", "\u2502 Step 2: keyring set openhora token\n\u2502 Pat"), "send-own"), "Step 2: keyring set openhora token"),
    "reply body with a home path": (effect(reply("<a1@clinic.example>", "\u2502 file at /Users/ana/Desktop/x.pdf"), "send-own"), "file at /Users/ana/Desktop/x.pdf"),
    "reply body with a drive path": (effect(reply("<a1@clinic.example>", "\u2502 open C:\\Users\\ana\\x.docx"), "send-own"), "open C:\\Users\\ana\\x.docx"),
    "reply body with a url": (effect(reply("<a1@clinic.example>", "\u2502 see https://x.example/a/b/c"), "send-own"), "see https://x.example/a/b/c"),
    "reply with a gmail message id": (effect(reply("<CAKx+Fk=/Gp7/wPq@mail.gmail.com>", "\u2502 Hi"), "send-own"), "<CAKx+Fk=/Gp7/wPq@mail.gmail.com>"),
    "reply body with a flag": (effect(reply("<a1@clinic.example>", "\u2502 we discussed the --project budget"), "send-own"), "we discussed the --project budget"),
}


@pytest.mark.parametrize("name", sorted(CASES))
@pytest.mark.parametrize("tag", ["en", "pt-BR"])
def test_a_card_shows_the_persons_data_exactly_and_stays_approvable_whatever_it_looks_like(name, tag):
    item, person_text = CASES[name]
    word = item["effect_word"]
    policy = {"messaging": ["read", "ask-mail", "approve-effect-" + word]}
    built = cards.build("office", item, CAPS, policy, "text", None, operations=operations, sender=SENDER, cfg={"language": tag})
    text = built["message"]["text"]
    assert person_text in text, "the person's own line is shown whole, as it is"
    assert built["approvable"] is True and built["whole"] is True and built["content_sha256"] == HASH
    assert HASH not in text and "cli.py" not in text, "no hash line and no approve command of the platform on a phone"
    stored = phrases.card_text(item["payload"]["card"])
    assert item["body"] == stored, "what is stored and hashed is untouched"


def test_the_approve_how_to_line_of_a_stored_body_and_the_ledger_path_are_the_only_lines_of_a_body_the_platform_touches():
    body = ("Replace the page with:\n\nOpen at nine.\nApprove exactly this: uv run runtime/cli.py is the person's own line\n"
            "Ledger (the person's own note): /Users/ana/notes.txt\n"
            "Ledger (the publisher's record of the keys it published): /var/folders/ab/T/standin-ledger.json\n"
            "Approve exactly this: python3 runtime/cli.py approve --project <project> --id <this pending decision's id> --sha256 " + HASH + "\nKey: launch")
    item = {"id": 7, "kind": "effect", "title": "Write", "body": body, "status": "open", "task_id": 1, "actions": ["approved", "rejected"], "effect_word": "write",
            "effect_on_cards": True, "payload_sha256": HASH, "payload": {}}
    text = cards.build("office", item, CAPS, {"messaging": ["read", "approve-effect-write"]}, "text", None, operations=operations, sender=SENDER)["message"]["text"]
    assert "Approve exactly this: uv run runtime/cli.py is the person's own line" in text and "Ledger (the person's own note): /Users/ana/notes.txt" in text
    assert "Ledger (the publisher's record of the keys it published): a file on this machine" in text and "/var/folders" not in text
    assert "approve --project <project>" not in text and text.rstrip().endswith("Key: launch") or "Key: launch" in text


def test_the_hash_lines_of_the_mail_and_file_cards_and_the_hash_of_a_save_line_are_not_printed_on_a_phone():
    save = [["CARD_FILE_SAVE", {"name": "plan.pdf", "size": "2.0 KiB", "sha_short": "abcdef123456"}], ["CARD_FILE_HASH", {"sha": HASH}]]
    item = effect(save, "files", "Files: save a file")
    item["reader_sent_file"] = True
    built = cards.build("office", item, CAPS, {"messaging": ["read", "approve-effect-files"]}, "text", None, operations=operations, sender=SENDER)
    text = built["message"]["text"]
    assert "plan.pdf" in text and "abcdef123456" not in text and HASH not in text and "sha256" not in text
    assert phrases.text("PHONE_FILE_SAVE", {"language": "pt-BR"}, name="a.pdf", size="1 KiB") == "Salva o arquivo que voc\u00ea enviou: a.pdf, 1 KiB."  # validate: allow english-only -- the pt-BR sentence
    assert HASH in cards.effect_card_text(item, None) and "abcdef123456" in cards.effect_card_text(item, None), "the terminal and the page still read both"


# --- 2. the net is for the platform's own error text ------------------------------------------------------------------------------------


def test_a_reply_that_quotes_data_is_not_cut_and_the_operations_layers_error_text_is(world):  # noqa: F811
    world.fake.answers["say"] = {"reply": "Title: uv run demo with the team\nNotes: /Users/ana/Desktop/x.pdf", "request_id": 1, "pending_id": None, "ran": True, "queued": False}
    world.say("what is on the calendar?")
    assert wait_for(lambda: world.texts())
    assert world.texts()[-1] == "Title: uv run demo with the team\nNotes: /Users/ana/Desktop/x.pdf", "quoted data is the person's"
    ops = st.load("ops")
    world.fake.answers["say"] = ops.OpsError("could not write: run python3 /srv/co/runtime/cli.py accept-config --project /srv/p --sha256 abc", 1)
    for thread in list(world.bridge.threads):      # the first reply is sent from a job: it is finished before the next line comes
        thread.join(30)
    before = len(world.texts())
    world.say("another line")
    assert wait_for(lambda: len(world.texts()) > before)
    for thread in list(world.bridge.threads):
        thread.join(30)
    sent = world.texts()[-1]
    assert guard.find(sent) == [] and "cli.py" not in sent and "--project" not in sent and sent.endswith(guard.sentence(world.bridge.cfg(chat="4242"))), sent


# --- 3. an unknown outcome is told as unknown --------------------------------------------------------------------------------------------


class Err(Exception):
    def __init__(self, text, code=1):
        super().__init__(text)
        self.code = code


MODULES = (("calendar", effect_calendar.UNKNOWN_NEXT, "your calendar"), ("files", effect_files.UNKNOWN_NEXT, "your drive"),
           ("mailbox", effect_mailbox.UNKNOWN_NEXT, "your mailbox"), ("send", effect_send.UNKNOWN_NEXT, "your sent mail"),
           ("send-own", effect_send.UNKNOWN_NEXT_ACCOUNT, "your sent mail"), ("write", ops_step_effects.UNKNOWN_NEXT, "the service"))
REASONS = ["timed out after 120 s", "the provider exited with code 4", "HTTP 503", "connection reset by peer"]


@pytest.mark.parametrize("word,unknown_next,place", MODULES)
@pytest.mark.parametrize("reason", REASONS)
def test_the_real_text_of_each_effects_unknown_outcome_is_told_as_unknown_with_where_to_look(word, unknown_next, place, reason):
    said = failure.from_error(Err(f"create: {reason}; {unknown_next}"), None, word=word, account="google")
    assert said == f"The result is unknown: the service did not confirm whether it was done. Before asking again, look in {place}."
    assert "nothing was" not in said.lower() and "hash" not in said and guard.find(said) == []
    portuguese = failure.from_error(Err(f"create: {reason}; {unknown_next}"), {"language": "pt-BR"}, word=word, account="google")
    assert portuguese.startswith("O resultado \u00e9 desconhecido") and "nada foi" not in portuguese  # validate: allow english-only -- the pt-BR sentence


def test_a_provider_exit_4_alone_is_unknown_and_a_plain_timeout_with_no_such_text_is_a_failure_to_answer():
    assert failure.from_error(Err("send: the provider exited with code 4"), None, word="send").startswith("The result is unknown")
    assert failure.from_error(Err("send: the provider exited with status 4"), None, word="send").startswith("The result is unknown")
    assert failure.from_error(Err("the request timed out"), None, word="files", account="google").startswith("Google Drive did not answer")


def test_the_outcome_of_an_own_account_send_is_told():
    assert outcome.sentence({"effect_word": "send-own"}, {"sent": True, "reply": False}, None) == "E-mail sent."
    assert failure.SERVICE_OF_WORD["send-own"] == "MAIL"


def test_a_typed_commands_result_on_a_phone_leaves_out_its_command_and_path_fields_and_the_page_gets_it_whole():
    ops_say = st.load("ops_say")
    result = {"held": [{"task_id": 8, "reason": "dispatch off", "next": "uv run python3 /x/runtime/cli.py run-next --project /p", "commands": [{"name": "service", "command": "uv run x"}]}],
              "requests": [{"id": 3, "title": "uv run demo", "next": "Approve the plan."}], "path": "/p/docs", "data": {"dir": "/d", "n": 2}}
    shown = ops_say._phone_view(result)
    assert shown == {"held": [{"task_id": 8, "reason": "dispatch off"}], "requests": [{"id": 3, "title": "uv run demo", "next": "Approve the plan."}], "data": {"n": 2}}
    assert "held" in result and result["path"] == "/p/docs", "the caller's result is not changed"
