"""The document of a change to the person's own mailbox (package W3, runtime/mailbox_document.py): the pure half of the kind. Its keys and checks, the key derived from
everything the person approves, the card line by line, the specs it hands the two writers (read back by the writers' own spec readers, so that the two sides cannot drift
apart), the closed facts, the places a move may go, the cleaning of another person's words, and the structure of the requests a dry run may show. Offline; no provider, no
store; every name and address is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_mailbox_document.py
"""
from __future__ import annotations

import copy
import importlib.util
import json
import os

import pytest

import phrase_kit as pk
import standin_tree as st

md = st.load("mailbox_document")
effects = st.load("effects")
phrases = st.load("phrases")
send_document = st.load("send_document")

SNAP = "2026-10-17T10:12:00Z"
READ = "2026-10-18T09:00:00Z"


def gmail_item(n, labels=("INBOX", "UNREAD"), subject="Hello", sender="ana@clinic.example"):
    return {"n": n, "ref": f"inbox#{n}", "id": f"m{n}", "subject": subject, "sender": sender, "date": "2026-10-17 06:00", "snapshot_at": SNAP, "labels": sorted(labels),
            "change_key": None, "folder_id": None, "is_read": None, "internet_id": None}


def outlook_item(n, is_read=False, folder="AAMkInbox0001="):
    return {"n": n, "ref": f"work#{n}", "id": f"AAMkMsg{n}=", "subject": "Hello", "sender": "ana@clinic.example", "date": "2026-10-17 06:00", "snapshot_at": SNAP, "labels": None,
            "change_key": f"CQ{n}", "folder_id": folder, "is_read": is_read, "internet_id": f"<o{n}@work.example>"}


def make(account="google", action="archive", **more):
    google = account == "google"
    pieces = dict(task_id=7, account=account, address="pat@example.com" if google else "casey@mail.example", action=action, zone="America/Sao_Paulo", read_at=READ,
                  dry_run_sha256="a" * 64)
    if action == "move":
        pieces.update(folder="bills", folder_id="Label_7" if google else "AAMkFolderBills1=", remove_inbox=google)
    elif not google and action in ("archive", "trash"):
        pieces.update(folder_id="archive" if action == "archive" else "deleteditems")
    if action == "mark":
        pieces.update(state="read")
    if action != "draft":
        pieces.update(messages=[gmail_item(1), gmail_item(2)] if google else [outlook_item(1), outlook_item(2)])
    else:
        pieces.update(draft={"to": ["joe@shop.example"], "cc": [], "bcc": [], "subject": "Hi", "body": "Hello Joe\n", "reply": None})
    pieces.update(more)
    return md.document(**pieces)


ALL = [(a, x) for a in ("google", "microsoft") for x in ("archive", "move", "mark", "trash", "draft")]


@pytest.mark.parametrize("account, action", ALL)
def test_a_document_of_every_action_on_both_accounts_is_in_its_form_and_its_card_is_a_valid_card_whose_english_lines_are_the_body(account, action):
    doc = make(account, action)
    assert md.check(doc) is doc and doc["effect"] == "mailbox" and doc["implementation"] == ("gmail" if account == "google" else "outlook-mail")
    card = md.card_lines(doc, "0" * 64)
    assert phrases.card_valid(card) and md.body(doc, "0" * 64) == phrases.card_text(card)
    assert card[0][0] in ("CARD_BOX_CODE", "CARD_BOX_CODE_DRAFT") and card[1] == ["CARD_ACCOUNT", {"account": account, "address": doc["address"]}]
    assert md.title(doc) == phrases.en(md.TITLE_KEY[action]) and "Hello" not in md.title(doc)
    assert md.describe(doc).count("Hello") == 0 and doc["address"] in md.describe(doc), "the one-line description holds none of the mail"
    assert md.summary(doc)["action"] == action and "Hello" not in json.dumps(md.summary(doc))
    if action != "draft":
        items = [line for line in card if line[0] == "CARD_BOX_ITEM"]
        assert [line[1]["i"] for line in items] == ["1", "2"] and len(card) == 2 + 1 + 2 + 2, "the code line, the account, the action, every message, the two times"
        assert all(line[0] in phrases.CARD_PRIVATE for line in items)


def test_the_key_derives_from_everything_the_person_approves_and_not_from_the_dry_run_hash():
    doc = make()
    assert md.KEY.fullmatch(doc["idempotency_key"]) and doc["idempotency_key"] == md.key_of(doc)
    assert make(dry_run_sha256="b" * 64)["idempotency_key"] == doc["idempotency_key"]
    changed = [make(task_id=8), make(read_at="2026-10-18T09:00:01Z"), make(messages=[gmail_item(1), gmail_item(2, labels=("INBOX",))]),
               make(messages=[gmail_item(1), gmail_item(2, subject="Other")]), make(action="trash", messages=doc["messages"]), make(zone="UTC")]
    assert len({doc["idempotency_key"], *(c["idempotency_key"] for c in changed)}) == len(changed) + 1


def broken(doc, **changes):
    out = copy.deepcopy(doc)
    for path, value in changes.items():
        target = out
        *head, last = path.split(".")
        for part in head:
            target = target[int(part)] if part.isdigit() else target[part]
        if isinstance(target, list):
            target[int(last)] = value
        else:
            target[last] = value
    return out


def refuses(doc):
    with pytest.raises(effects.EffectError) as why:
        md.check(doc)
    assert why.value.kind == "usage"
    return why.value.reason


@pytest.mark.parametrize("account, action, changes", [
    ("google", "archive", {"task": 0}), ("google", "archive", {"task": True}), ("google", "archive", {"effect": "calendar"}), ("google", "archive", {"account": "yahoo"}),
    ("google", "archive", {"implementation": "outlook-mail"}), ("google", "archive", {"address": "not an address"}), ("google", "archive", {"action": "erase"}),
    ("google", "archive", {"folder": "bills"}), ("google", "archive", {"remove_inbox": True}), ("google", "archive", {"state": "read"}), ("google", "archive", {"draft": {}}),
    ("google", "archive", {"folder_id": "archive"}), ("microsoft", "archive", {"folder_id": None}), ("microsoft", "trash", {"folder_id": "archive"}),
    ("google", "archive", {"messages": []}), ("google", "archive", {"messages": None}), ("google", "archive", {"zone": "bad zone!"}), ("google", "archive", {"read_at": "yesterday"}),
    ("google", "archive", {"dry_run_sha256": "xyz"}), ("google", "archive", {"idempotency_key": "box-" + "0" * 32}), ("google", "archive", {"idempotency_key": "send-" + "0" * 32}),
    ("google", "archive", {"messages.0.n": 2}), ("google", "archive", {"messages.0.ref": "inbox"}), ("google", "archive", {"messages.0.id": "../x"}),
    ("google", "archive", {"messages.0.labels": ["UNREAD", "INBOX"]}), ("google", "archive", {"messages.0.change_key": "CK"}), ("google", "archive", {"messages.0.subject": "x" * 81}),
    ("google", "archive", {"messages.0.subject": "hidden \u202e"}), ("google", "archive", {"messages.0.date": "yesterday"}), ("google", "archive", {"messages.0.snapshot_at": "then"}),
    ("google", "archive", {"messages.1.id": "m1"}), ("microsoft", "archive", {"messages.0.labels": ["INBOX"]}), ("microsoft", "archive", {"messages.0.change_key": None}),
    ("microsoft", "archive", {"messages.0.is_read": "no"}), ("microsoft", "mark", {"state": "seen"}), ("microsoft", "mark", {"state": None}),
    ("google", "move", {"folder": "Bills"}), ("google", "move", {"folder_id": "TRASH"}), ("google", "move", {"folder_id": "INBOX"}), ("google", "move", {"folder_id": "a/b"}),
    ("microsoft", "move", {"folder_id": "drafts"}), ("microsoft", "move", {"folder_id": "recoverableitemspurges"}), ("microsoft", "move", {"remove_inbox": True}),
    ("google", "move", {"remove_inbox": "yes"}),
    ("google", "draft", {"messages": [gmail_item(1)]}), ("google", "draft", {"draft": None}), ("google", "draft", {"draft.to": []}), ("google", "draft", {"draft.to": ["x"]}),
    ("google", "draft", {"draft.cc": ["joe@shop.example"]}), ("google", "draft", {"draft.subject": ""}), ("google", "draft", {"draft.subject": "a\nb"}),
    ("google", "draft", {"draft.body": "bad\x00"}), ("google", "draft", {"draft.body": "   "}), ("google", "draft", {"draft.extra": 1}),
    ("google", "draft", {"draft.body": "token ghp_" + "abcdefghijklmnopqrstuvwxyz0123456789"}),
    ("google", "draft", {"draft.to": [f"a{i}@x.example" for i in range(21)]})])
def test_a_document_that_is_not_in_its_form_is_refused_with_a_usage_error(account, action, changes):
    doc = make(account, action)
    if "draft.extra" in changes:
        doc["draft"]["extra"] = 1
        changes = {}
    refuses(broken(doc, **changes))


def test_a_reply_draft_is_checked_against_the_message_it_answers():
    reply = {"ref": "inbox#1", "id": "m1", "thread_id": "t1", "message_id": "<a1@mail.example>", "sender": "ana@clinic.example", "reply_to": "desk@clinic.example",
             "subject": "Appointment", "date": "2026-10-17 06:00", "snapshot_at": SNAP}
    draft = {"to": ["ana@clinic.example"], "cc": [], "bcc": [], "subject": "Re: Appointment", "body": "Yes\n", "reply": reply}
    doc = make(action="draft", draft=draft)
    assert md.check(doc) and [line[0] for line in md.card_lines(doc, "x")][2:6] == ["CARD_BOX_DRAFT_REPLY", "CARD_BOX_DRAFT_REPLY_DIFFERS", "CARD_BOX_DRAFT_REPLY_TO", "CARD_BOX_DRAFT_REPLY_SUBJECT"]
    for changes in ({"draft.to": ["other@clinic.example"]}, {"draft.cc": ["joe@shop.example"]}, {"draft.subject": "Something else"}, {"draft.reply.reply_to": "ana@clinic.example"},
                    {"draft.reply.thread_id": None}, {"draft.reply.message_id": "no-brackets"}, {"draft.reply.message_id": None}, {"draft.reply.sender": "not an address"},
                    {"draft.reply.id": "../x"}, {"draft.reply.subject": "hidden \u202e"}):
        refuses(broken(doc, **changes))
    refuses(broken(doc, **{"draft.reply.extra": 1}) if False else {**doc, "draft": {**draft, "reply": {**reply, "extra": 1}}})
    outlook = make("microsoft", "draft", draft={**draft, "reply": {**reply, "thread_id": None, "message_id": None, "id": "AAMkMsg1="}})
    assert md.check(outlook) and md.verb_of(outlook) == "draft-reply" and md.verb_of(make("microsoft", "draft")) == "draft-create"


@pytest.mark.parametrize("account, value, ok", [("google", "Label_7", True), ("google", "STARRED", True), ("google", "INBOX", False), ("google", "TRASH", False),
                                                ("google", "SPAM", False), ("google", "SENT", False), ("google", "DRAFT", False), ("google", "UNREAD", False), ("google", "CHAT", False),
                                                ("google", "a/b", False), ("google", "", False), ("google", None, False), ("google", "x" * 65, False),
                                                ("microsoft", "archive", True), ("microsoft", "deleteditems", False), ("microsoft", "inbox", True), ("microsoft", "junkemail", False), ("microsoft", "Junkemail", False),
                                                ("microsoft", "AAMkFolderBills1=", True), ("microsoft", "drafts", False), ("microsoft", "outbox", False), ("microsoft", "sentitems", False),
                                                ("microsoft", "recoverableitemsdeletions", False), ("microsoft", "msgfolderroot", False), ("microsoft", "a/b", False), ("microsoft", "-x", False)])
def test_a_move_goes_only_to_a_label_or_folder_that_is_a_place_and_not_something_else(account, value, ok):
    assert md.destination_ok(account, value) is ok


def test_another_persons_words_are_cleaned_cut_and_replaced_when_they_look_like_a_credential():
    assert md.clean_line("  two   spaces\tand\nbreaks \u202e \u200b hidden ", 80) == "two spaces and breaks hidden"
    assert md.clean_line("x" * 100, 80) == "x" * 79 + "…" and md.clean_line(None, 80) == ""
    live = {"id": "m1", "found": True, "labels": ["INBOX"], "subject": "my key is " + "AKIA" + "ABCDEFGHIJKLMNOP", "from_address": "ana@clinic.example", "date": "2026-10-17T09:00:00Z"}
    item = md.message_item("google", 1, "inbox#1", SNAP, live)
    assert item["subject"] == "" and item["sender"] == "" and item["date"] == "2026-10-17 06:00" if os.environ.get("TZ") == "America/Sao_Paulo" else item["subject"] == ""
    normal = md.message_item("google", 1, "inbox#1", SNAP, dict(live, subject="Hello"))
    assert normal["subject"] == "Hello" and normal["labels"] == ["INBOX"] and normal["snapshot_at"] == SNAP
    for bad in (None, {}, {"found": False, "id": "m1"}, dict(live, labels=None), dict(live, labels=[1])):
        with pytest.raises(effects.EffectError):
            md.message_item("google", 1, "inbox#1", SNAP, bad)
    assert md.reply_subject("Appointment") == "Re: Appointment" and md.reply_subject("re: Appointment") == "re: Appointment" and md.reply_subject("RE: x") == "RE: x"
    assert len(md.reply_subject("y" * 400)) <= send_document.SUBJECT_MAX and md.reply_subject("") == "Re: -"


def test_utc_text_reads_a_time_and_refuses_what_is_not_one():
    assert md.utc_text("2026-10-18T09:00:00Z") == "2026-10-18T09:00:00Z" and md.utc_text("2026-10-18T06:00:00-03:00") == "2026-10-18T09:00:00Z"
    assert md.utc_text("2026-10-18T09:00:00") == "2026-10-18T09:00:00Z"
    for bad in (None, "yesterday", 7):
        with pytest.raises(effects.EffectError):
            md.utc_text(bad)


def load_writer(name, filename):
    spec = importlib.util.spec_from_file_location(name, st.REPO / "providers" / "writer" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("account, action", [(a, x) for a, x in ALL])
def test_the_spec_the_document_hands_the_writer_is_one_the_writers_own_reader_accepts_and_the_verb_exists(account, action, tmp_path):
    doc = make(account, action)
    writer = load_writer(f"gmail_{action}" if account == "google" else f"outlook_{action}", "gmail.py" if account == "google" else "outlook-mail.py")
    verb = md.verb_of(doc)
    assert verb in writer.VERBS
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(md.spec_of(doc)), encoding="utf-8")
    os.chmod(path, 0o600)
    reader = {"modify": "spec_modify", "trash": "spec_trash", "draft-create": "spec_draft", "move": "spec_move", "mark": "spec_mark", "draft-reply": "spec_draft"}[verb]
    got = getattr(writer, reader)(str(path))
    if action != "draft":
        assert got["ids"] == [m["id"] for m in doc["messages"]]
    args = md.provider_args(doc, str(path))
    assert args[:2] == ["--account", doc["address"]] and args[-2:] == ["--idempotency-key", doc["idempotency_key"]] and "--spec-file" in args
    assert md.meta_args(make(account, "archive")) == ["--account", doc["address"], "--ids", ",".join(m["id"] for m in make(account, "archive")["messages"]),
                                                      "--key", make(account, "archive")["idempotency_key"]]
    built = writer.build(verb, got, *( [doc["address"], doc["idempotency_key"]] if account == "google" else [doc["idempotency_key"]] ))
    assert built["requests"], "the writer builds requests from it"


def test_the_gmail_label_changes_each_action_asks_for():
    assert md.labels_after(make("google", "archive")) == ([], ["INBOX"])
    assert md.labels_after(make("google", "move")) == (["Label_7"], ["INBOX"])
    assert md.labels_after(make("google", "move", remove_inbox=False)) == (["Label_7"], [])
    assert md.labels_after(make("google", "mark")) == ([], ["UNREAD"]) and md.labels_after(make("google", "mark", state="unread")) == (["UNREAD"], [])


def test_the_facts_a_decision_records_are_closed_words_numbers_and_ids_and_never_the_mail():
    doc = make("google", "move")
    facts = md.facts(doc, "done", {"done": True})
    assert facts == {"done": True, "replayed": False, "action": "move", "account": "google", "count": 2, "folder": "bills", "state": None, "idempotency_key": doc["idempotency_key"]}
    assert md.facts(doc, "replayed", {})["replayed"] is True and "Hello" not in json.dumps(facts)
    draft = make(action="draft")
    assert md.facts(draft, "done", {"draft_id": "r1"})["draft_id"] == "r1" and md.facts(draft, "done", {"draft_id": 5})["draft_id"] is None and md.facts(draft, "done", {})["count"] == 1


def test_the_card_of_a_draft_shows_every_recipient_first_the_subject_and_the_whole_text_and_says_it_is_not_sent():
    doc = make(action="draft", draft={"to": ["joe@shop.example"], "cc": ["amy@shop.example"], "bcc": ["boss@shop.example"], "subject": "Hi", "body": "Line one\nLine two\n", "reply": None})
    text = md.body(doc, "x").splitlines()
    pk.assert_said(text[0], "CARD_BOX_CODE_DRAFT", None, address="pat@example.com")
    assert len(text[2:6]) == 4
    pk.assert_said(text[2], "CARD_BOX_DRAFT_TO", None, to="joe@shop.example")
    pk.assert_said(text[3], "CARD_BOX_DRAFT_CC", None, cc="amy@shop.example")
    pk.assert_said(text[4], "CARD_BOX_DRAFT_BCC", None, bcc="boss@shop.example")
    pk.assert_said(text[5], "CARD_BOX_DRAFT_SUBJECT", None, subject="Hi")
    pk.assert_said("\n".join(text[6:-1]), "CARD_BOX_DRAFT_TEXT", None, body="\u2502 Line one\n\u2502 Line two")
    pk.assert_said(text[-1], "CARD_BOX_DRAFT_END", None)
    private = {line[0] for line in md.card_lines(doc, "x") if line[0] in phrases.CARD_PRIVATE}
    assert private == {"CARD_BOX_DRAFT_TO", "CARD_BOX_DRAFT_CC", "CARD_BOX_DRAFT_BCC", "CARD_BOX_DRAFT_SUBJECT", "CARD_BOX_DRAFT_TEXT"}, "who a draft goes to, its subject and its text are the mail's"
    assert {line[0] for line in md.card_lines(doc, "x")} - private == {"CARD_BOX_CODE_DRAFT", "CARD_ACCOUNT", "CARD_BOX_DRAFT_END"}


def raw_of(to, subject, text, bcc=None):
    import base64
    import email.message
    message = email.message.EmailMessage()
    message["From"], message["To"], message["Subject"] = "pat@example.com", to, subject
    if bcc:
        message["Bcc"] = bcc
    message.set_content(text)
    return base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")


def graph_draft(to, subject, text, bcc=()):
    wrap = lambda addresses: [{"emailAddress": {"address": a}} for a in addresses]      # noqa: E731
    return {"subject": subject, "body": {"contentType": "text", "content": text}, "toRecipients": wrap([to]), "ccRecipients": [], "bccRecipients": wrap(bcc)}


def test_a_draft_request_that_carries_other_recipients_text_or_subject_than_the_document_is_not_what_it_says():
    google, graph = make("google", "draft"), make("microsoft", "draft")
    good = {"requests": [{"method": "POST", "path": "/gmail/v1/users/me/drafts", "body": {"message": {"raw": raw_of("joe@shop.example", "Hi", "Hello Joe\n")}}}]}
    assert md.requests_match(google, good) is True
    for raw in (raw_of("joe@shop.example, evil@x.example", "Hi", "Hello Joe\n"), raw_of("joe@shop.example", "Hi", "Hello Joe\n", bcc="evil@x.example"),
                raw_of("joe@shop.example", "Other", "Hello Joe\n"), raw_of("joe@shop.example", "Hi", "Something else\n"), "!!not base64!!"):
        assert md.requests_match(google, {"requests": [dict(good["requests"][0], body={"message": {"raw": raw}})]}) is False, raw[:20]
    assert md.requests_match(google, {"requests": [dict(good["requests"][0], body={"message": {"raw": good["requests"][0]["body"]["message"]["raw"], "threadId": "t9"}})]}) is False
    ok = {"requests": [{"method": "POST", "path": "/me/messages", "body": graph_draft("joe@shop.example", "Hi", "Hello Joe\n")}]}
    assert md.requests_match(graph, ok) is True
    for body in (graph_draft("evil@x.example", "Hi", "Hello Joe\n"), graph_draft("joe@shop.example", "Hi", "Other"), graph_draft("joe@shop.example", "Hi", "Hello Joe\n", bcc=["evil@x.example"]),
                 dict(graph_draft("joe@shop.example", "Hi", "Hello Joe\n"), isDraft=False)):
        assert md.requests_match(graph, {"requests": [dict(ok["requests"][0], body=body)]}) is False


def test_the_requests_a_dry_run_may_show_are_exactly_those_of_the_action():
    cases = {
        ("google", "archive"): [{"method": "POST", "path": "/gmail/v1/users/me/messages/batchModify", "body": {"ids": ["m1", "m2"], "addLabelIds": [], "removeLabelIds": ["INBOX"]}}],
        ("google", "trash"): [{"method": "POST", "path": f"/gmail/v1/users/me/messages/m{n}/trash", "body": None} for n in (1, 2)],
        ("google", "draft"): [{"method": "POST", "path": "/gmail/v1/users/me/drafts", "body": {"message": {"raw": raw_of("joe@shop.example", "Hi", "Hello Joe\n")}}}],
        ("microsoft", "archive"): [{"method": "POST", "path": f"/me/messages/AAMkMsg{n}%3D/move", "body": {"destinationId": "archive"}} for n in (1, 2)],
        ("microsoft", "mark"): [{"method": "PATCH", "path": f"/me/messages/AAMkMsg{n}%3D", "body": {"isRead": True}} for n in (1, 2)],
        ("microsoft", "draft"): [{"method": "POST", "path": "/me/messages", "body": graph_draft("joe@shop.example", "Hi", "Hello Joe\n")}]}
    for (account, action), requests in cases.items():
        doc = make(account, action)
        assert md.requests_match(doc, {"requests": requests}) is True, (account, action)
        assert md.requests_match(doc, {"requests": requests + requests[:1]}) is False and md.requests_match(doc, {"requests": requests[:-1]}) is False or len(requests) == 1
        assert md.requests_match(doc, {"requests": [dict(requests[0], method="DELETE")] + requests[1:]}) is False
        assert md.requests_match(doc, {"requests": [dict(requests[0], path=requests[0]["path"] + "/send")] + requests[1:]}) is False
    for bad in (None, [], {}, {"requests": "x"}, {"requests": [1]}, {"requests": [{"method": "POST"}]}):
        assert md.requests_match(make(), bad) is False


def test_the_outlook_reply_requests_carry_the_approved_message_in_the_create_reply_and_in_the_patch():
    draft = {"to": ["ana@clinic.example"], "cc": [], "bcc": [], "subject": "Re: Hi", "body": "Yes\n",
             "reply": {"ref": "work#1", "id": "AAMkMsg1=", "thread_id": None, "message_id": None, "sender": "ana@clinic.example", "reply_to": None, "subject": "Hi",
                       "date": "2026-10-17 06:00", "snapshot_at": SNAP}}
    doc = make("microsoft", "draft", draft=draft)
    approved = graph_draft("ana@clinic.example", "Re: Hi", "Yes\n")
    first = {"method": "POST", "path": "/me/messages/AAMkMsg1%3D/createReply", "body": {"message": approved}}
    second = {"method": "PATCH", "path": "/me/messages/{the draft createReply makes}", "body": approved}
    assert md.requests_match(doc, {"requests": [first, second]}) is True
    for bad_first in ({**first, "body": {}}, {**first, "body": {"message": graph_draft("evil@x.example", "Re: Hi", "Yes\n")}}, {**first, "body": {"message": approved, "comment": "x"}}):
        assert md.requests_match(doc, {"requests": [bad_first, second]}) is False
    assert md.requests_match(doc, {"requests": [first, {**second, "body": graph_draft("evil@x.example", "Re: Hi", "Yes\n")}]}) is False


def test_a_gmail_draft_request_is_from_the_account_and_has_no_header_but_those_of_a_draft():
    import base64
    import email.message
    doc = make("google", "draft")

    def raw(sender="pat@example.com", extra=None):
        message = email.message.EmailMessage()
        message["From"], message["To"], message["Subject"] = sender, "joe@shop.example", "Hi"
        for name, value in (extra or {}).items():
            message[name] = value
        message.set_content("Hello Joe\n")
        return base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
    request = lambda text: {"requests": [{"method": "POST", "path": "/gmail/v1/users/me/drafts", "body": {"message": {"raw": text}}}]}      # noqa: E731
    assert md.requests_match(doc, request(raw())) is True
    assert md.requests_match(doc, request(raw(sender="someone@else.example"))) is False
    for extra in ({"Reply-To": "evil@x.example"}, {"X-Anything": "1"}, {"Return-Path": "<evil@x.example>"}):
        assert md.requests_match(doc, request(raw(extra=extra))) is False, extra
