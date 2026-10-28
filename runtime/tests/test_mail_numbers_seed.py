"""A message number the model gave opens the mail family when the closed forms read none (package BL7-5, gap G1; limits L54, L60, L61, L63).

`ops_interpret._carry_out` used to re-read a line with the closed forms whenever the model gave `message` or `messages`, and a miss was `IX_CANNOT_WRITE`: "joga no lixo os emails 2, 4 e 7" and
"trash emails 4 and 9 pls" are words no closed head reads. Now, when the closed forms read nothing, `ops_natural_mail.mail_number_seed` opens the family with the numbers, and only when they are
EXACTLY the numbers the line writes as words of their own (`natural_writes_mail.free_numbers`) and no `target`, `day`, `to` or `subject` stands beside them.

Held here, every expectation a literal of this file (invented names, `.example` addresses, non-ASCII as `\\u` escapes):
  * `free_numbers`: the lines of the spec with their outputs, a range, a text span and a time phrase that keeps a number out, an unmappable time hit failing closed;
  * `mail_number_seed`: the slots and origins of the seed of each operation, and None for a subset, an extra number, a number of a time phrase and for words beside the numbers;
  * the product's own turn (the mail desk world of `test_mail_compose_flow.py`, as `test_interpreter_card_parity.py` sets it up): the rows open the card the family prepares, or say what is
    missing, with the sentence KEY asserted; a numbered line never refreshes a snapshot, a stale one is refused, a closed-form line never reaches the seed, a project language with no write
    forms still says `IX_WRITE_LANGUAGE`, and `turn_gate.provenance` passes on every opened row with `line-number`;
  * vacuity: `free_numbers` patched to return the decision's own numbers opens the rows it must refuse, and the branch of `_carry_out` patched off fails the card rows.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_mail_numbers_seed.py
"""
from __future__ import annotations

import json

import pytest

import standin_tree as st
import test_sources_mail as tsm
from test_mail_compose_flow import setup, phone, op, clock, forget  # noqa: F401  (the mail desk world, the stand-in model, the clock)
from test_send_own_account import world  # noqa: F401

nwm = st.load("natural_writes_mail")
natural = st.load("natural")
ops = st.load("ops")
ops_natural_mail = st.load("ops_natural_mail")
ops_core = st.load("ops_core")
mail_refresh = st.load("mail_refresh")
turn_gate = st.load("turn_gate")
phrases = st.load("phrases")
interpreter_pipeline = st.load("interpreter_pipeline")

GROUPS = ("read", "talk", "interpret", "mail-send", "mail-organize", "ask-mail")
FIRST = tsm.message(1, "2026-10-20T09:00:00Z", sender="Marta Siqueira <marta.siqueira@agencia.example>", subject="Budget for the spring fair", id="p1", thread_id="t1",
                    text="Here is the budget.", headers={"Message-ID": "<c1@x.example>"})
SECOND = tsm.message(2, "2026-10-20T10:00:00Z", sender="Nadia Ferreira <nadia.ferreira@feira.example>", subject="Volunteer schedule for the book fair", id="p2", thread_id="t2",
                     text="Here is the schedule.", headers={"Message-ID": "<c2@x.example>"})

# --- free_numbers ----------------------------------------------------------------------------------------------------------------------------

FREE = (
    ("joga no lixo os emails 2, 4 e 7", (), [2, 4, 7]),
    ("trash emails 4 and 9 pls", (), [4, 9]),
    ("marca o email 1 e o 2 como lido", ("lido",), [1, 2]),
    ("marca o 1 e o 2 como lido", ("lido",), []),          # no mail noun, no "#": not a message number (principle 13, the stricter rule stays)
    ("reply to email 8 with can we move it to next week", ("can we move it to next week",), [8]),
    ("reply to email 8 saying the meeting is at 10", ("the meeting is at 10",), [8]),
    ("trash the email about room 4 from the 2 o'clock meeting", (), []),          # a room and a clock: neither follows a mail noun
    ("trash the email about the 2 o'clock meeting", (), []),
    ("trash email 2 o'clock", (), []),          # "o'clock" after a number that does follow a mail noun: a time
    ("apaga o e-mail 3 de 12:30", (), [3]),
    ("arquiva o 5, recebi 3 dias atrás", (), []),
    ("arquiva o email 5, recebi 3 dias atrás", (), [5]),
    ("trash the 2 budgets pls", (), []),          # a count noun
    ("trash the email about the 2026 budget", (), []),          # a year
    ("call 555 1234 and trash email 3", (), [3]),          # a phone number is no message number
    ("trash the email from room 4", (), []),
    ("arquiva o email da sala 4", (), []),
    ("move 4 and 9 to the Receipts folder", (), []),
    ("trash email 2 and the room 4", (), [2]),
    ("trash emails 2, the 5 or 7", (), [2, 5, 7]),          # chained by a comma, an article and "or"
    ("trash email 2 , 4", (), [2, 4]),
    ("joga no lixo os emails 2 4 e 7", (), [2, 4, 7]),          # a number written right after a counted one is still anchored to the mail noun
    ("trash email 3 about room 4 5", (), [3]),          # ... but not one after a number that does not count ("room 4")
    ("reply to #7 ok", (), [7]),
    ("trash email 4 of 25 euros", (), [4]),
    ("trash email 6 and 6 again", (), [6]),
    ("archive email 3 for $40", (), [3]),
    ("archive email 5 at 10", (), [5]),
    ("trash email 3 on 15/11", (), [3]),
)


@pytest.mark.parametrize("line, spans, expected", FREE, ids=[row[0] for row in FREE])
def test_free_numbers_are_the_whole_numbers_the_line_writes_as_words_of_their_own(line, spans, expected):
    assert nwm.free_numbers(line, spans) == expected


@pytest.mark.parametrize("line", ["archive 1-3", "arquiva os e-mails 1 a 3", "trash emails 1 to 3", "trash emails 1 - 3", "apaga os emails 2 até 5", "trash emails 1-3 and 5",
                                  "trash email 5 and emails 1-3", "arquiva os emails do 1 ao 3", "trash emails between 1 and 3"])
def test_a_range_gives_no_free_number_at_all(line):
    assert nwm.free_numbers(line, ()) == []


def test_a_span_that_holds_a_number_keeps_it_out():
    assert nwm.free_numbers("reply to email 8 saying call me at 555", ("call me at 555",)) == [8]
    assert nwm.free_numbers("reply to email 8 saying 3", ("3",)) == [8]          # the text is "3" and the number 8 is not inside it
    assert nwm.free_numbers("reply to email 3 saying 3", ("3",)) == []          # the text occurs where the number is: nothing is free there (fail closed)


def test_a_time_hit_that_cannot_be_mapped_to_the_line_gives_nothing(monkeypatch):
    real = nwm.nt.find

    def broken(text, languages=None):
        found = real(text, languages)
        return dict(found, hits=[{"s": 0, "e": len(found["origin"]) + 5}])
    monkeypatch.setattr(nwm.nt, "find", broken)
    assert nwm.free_numbers("trash emails 4 and 9 pls", ()) == []


def test_a_line_with_no_number_or_a_non_string_has_none():
    assert nwm.free_numbers("trash the last one", ()) == [] and nwm.free_numbers(None, ()) == [] and nwm.free_numbers("", ()) == []


# --- mail_number_seed ------------------------------------------------------------------------------------------------------------------------


def decision(op_name, args, spans):
    return {"kind": "op", "error": None, "op": op_name, "args": args, "spans": spans, "time": None, "inherited": [], "time_disagree": False}


def test_a_seed_of_each_operation_has_the_numbers_and_what_the_family_reads_beside_them():
    got = ops_natural_mail.mail_number_seed("mail-trash", decision("mail-trash", {"messages": [4, 9]}, {"messages": "4,9"}), "trash emails 4 and 9 pls")
    assert got == {"op": "mail-trash", "by": "numbers", "slots": {"numbers": [4, 9]}} and got.origins == {"numbers": "line-number"}
    got = ops_natural_mail.mail_number_seed("mail-archive", decision("mail-archive", {"messages": [3]}, {"messages": "3"}), "stash email 3 away")
    assert got["slots"] == {"numbers": [3]}
    got = ops_natural_mail.mail_number_seed("mail-mark", decision("mail-mark", {"messages": [1, 2]}, {"messages": "1,2", "state": "lido"}), "marca o email 1 e o 2 como lido")
    assert got["slots"] == {"numbers": [1, 2], "state": "read"} and got.origins == {"numbers": "line-number", "state": "line-span"}
    got = ops_natural_mail.mail_number_seed("mail-move", decision("mail-move", {"messages": [3], "folder": "Trabalho"}, {"messages": "3", "folder": "Trabalho"}), "move o email 3 pra pasta Trabalho")      # validate: allow english-only -- a Portuguese line or word is the input under test
    assert got["slots"] == {"numbers": [3], "folder_name": "Trabalho"} and got.origins == {"numbers": "line-number", "folder_name": "line-span"}
    line = "reply to email 8 with can we move it to next week"
    got = ops_natural_mail.mail_number_seed("mail-reply", decision("mail-reply", {"message": 8}, {"message": "8", "body": "can we move it to next week"}), line)
    assert got["slots"] == {"numbers": [8], "body": "can we move it to next week"} and got.origins == {"numbers": "line-number", "body": "line-span"}
    got = ops_natural_mail.mail_number_seed("mail-draft", decision("mail-draft", {"message": 2}, {"message": "2", "body": "sounds good"}), "put together a draft answer to email 2 with sounds good")
    assert got["slots"] == {"numbers": [2], "body": "sounds good"}


def test_a_body_that_describes_the_reply_is_marked_for_wording_and_a_dictated_one_is_not():
    described = "thanking her and explaining that i will send the numbers on friday"
    line = f"reply to email 3 {described}"
    got = ops_natural_mail.mail_number_seed("mail-reply", decision("mail-reply", {"message": 3}, {"message": "3", "body": described}), line)
    assert got["slots"].get("_compose_reply") is True
    dictated = "saying: yes, friday works"
    line = f"reply to email 3 {dictated}"
    got = ops_natural_mail.mail_number_seed("mail-reply", decision("mail-reply", {"message": 3}, {"message": "3", "body": dictated}), line)
    assert "_compose_reply" not in got["slots"]


@pytest.mark.parametrize("name, op_name, args, spans, line", [
    ("a subset", "mail-trash", {"messages": [1]}, {"messages": "1"}, "trash emails 1 and 2 pls"),
    ("an extra number", "mail-trash", {"messages": [1, 2, 5]}, {"messages": "1,2,5"}, "trash emails 1 and 2 pls"),
    ("a number of a time phrase", "mail-trash", {"messages": [3, 12]}, {"messages": "3,12"}, "trash email 3 at 12:30"),
    ("a count noun", "mail-trash", {"messages": [2]}, {"messages": "2"}, "trash the 2 budgets pls"),
    ("a clock with a mail noun in the line", "mail-trash", {"messages": [2]}, {"messages": "2"}, "trash the email about the 2 o'clock meeting"),
    ("a room beside a number that counts", "mail-trash", {"messages": [2, 4]}, {"messages": "2,4"}, "trash email 2 and the room 4"),
    ("bare numbers with no mail noun", "mail-mark", {"messages": [1, 2]}, {"messages": "1,2", "state": "lido"}, "marca o 1 e o 2 como lido"),
    ("a number of a quantity", "mail-trash", {"messages": [4, 25]}, {"messages": "4,25"}, "trash email 4 of 25 euros"),
    ("a range read by the model", "mail-archive", {"messages": [1, 3]}, {"messages": "1,3"}, "archive emails 1 to 3"),
    ("a target beside the numbers", "mail-trash", {"messages": [1, 2]}, {"messages": "1,2", "target": "Marta"}, "trash emails 1 and 2 from Marta pls"),
    ("a day beside the numbers", "mail-trash", {"messages": [1, 2]}, {"messages": "1,2", "day": "yesterday"}, "trash emails 1 and 2 from yesterday pls"),
    ("a recipient on a reply draft", "mail-draft", {"message": 2}, {"message": "2", "to": "ana@clinic.example"}, "draft a reply to email 2 for ana@clinic.example saying ok"),
    ("a subject on a reply draft", "mail-draft", {"message": 2}, {"message": "2", "subject": "the lease"}, "draft a reply to email 2 about the lease saying ok"),
    ("no number at all", "mail-trash", {"messages": []}, {}, "trash the last one"),
    ("a boolean for a number", "mail-trash", {"messages": [True]}, {"messages": "1"}, "trash email 1 pls"),
    ("an operation that is not a mail operation on messages", "mail-send", {"message": 1}, {"message": "1"}, "send email 1"),
])
def test_no_seed_when_the_model_numbers_are_not_exactly_the_lines_or_words_stand_beside_them(name, op_name, args, spans, line):
    assert ops_natural_mail.mail_number_seed(op_name, decision(op_name, args, spans), line) is None, name


# --- the product's own turn --------------------------------------------------------------------------------------------------------------------


def run(world, monkeypatch, language, line, answer, messages=(FIRST, SECOND)):
    """The product's turn for the line, the stand-in model answering `answer`: (the reply tuple of `ops.say`, the list of what `ops_natural_mail.resolve` returned, the stand-in model)."""
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


def sentence(world, key):
    return phrases.text(key, ops_core.context(world["path"])["cfg"])


def args_of(resolved):
    return [got["args"] for got in resolved if "args" in got]


def card_body(world, out):
    return ops.pending(world["path"], out["resend"])["body"]


def test_a_numbered_mark_the_closed_forms_do_not_read_resolves_the_messages_and_the_state(world, clock, monkeypatch):
    out, resolved, model = run(world, monkeypatch, "pt-BR", "marca o email 1 e o 2 como lido", op("mail-mark", {"messages": "1,2", "state": "lido"}))
    assert model.of("interpret"), "the line did not reach the interpreter"
    got = args_of(resolved)
    assert len(got) == 1 and got[0]["messages"] == "inbox#1,inbox#2" and got[0]["state"] == "read", (got, out["reply"])


def test_numbered_trash_resolves_the_numbered_messages(world, clock, monkeypatch):
    out, resolved, model = run(world, monkeypatch, "en", "trash emails 1 and 2 pls", op("mail-trash", {"messages": "1,2"}))
    assert model.of("interpret") and [a["messages"] for a in args_of(resolved)] == ["inbox#1,inbox#2"], out["reply"]


def test_a_subset_of_the_lines_numbers_is_cannot_write(world, clock, monkeypatch):
    out, resolved, _ = run(world, monkeypatch, "en", "trash emails 1 and 2 pls", op("mail-trash", {"messages": "1"}))
    assert not resolved and out["reply"] == sentence(world, "IX_CANNOT_WRITE") and not out.get("resend")


def test_numbers_with_words_beside_them_are_cannot_write(world, clock, monkeypatch):
    out, resolved, _ = run(world, monkeypatch, "en", "trash emails 1 and 2 from Marta pls", op("mail-trash", {"messages": "1,2", "target": "Marta"}))
    assert not resolved and out["reply"] == sentence(world, "IX_CANNOT_WRITE")


@pytest.mark.parametrize("line, numbers", [
    ("trash the email about room 1 from the 2 o'clock meeting", "1"),
    ("trash the email about room 1 from the 2 o'clock meeting", "1,2"),
    ("trash the email about the 2 o'clock meeting", "2"),
    ("trash the 2 budgets pls", "2"),
    ("marca o 1 e o 2 como lido", "1,2"),
])
def test_numbers_that_are_a_room_a_clock_a_count_or_bare_are_not_message_numbers(world, clock, monkeypatch, line, numbers):
    out, resolved, _ = run(world, monkeypatch, "en", line, op("mail-trash", {"messages": numbers}))
    assert not resolved and out["reply"] == sentence(world, "IX_CANNOT_WRITE"), out["reply"]


def test_a_reply_by_number_with_a_body_opens_the_card_with_that_text(world, clock, monkeypatch):
    out, resolved, _ = run(world, monkeypatch, "en", "reply to email 1 with can we move it to next week", op("mail-reply", {"message": "1", "body": "can we move it to next week"}))
    assert out["resend"], out["reply"]
    assert "can we move it to next week" in card_body(world, out)
    assert args_of(resolved)[0]["message"] == "inbox#1"


def test_a_reply_by_number_with_no_body_asks_for_the_body(world, clock, monkeypatch):
    out, resolved, _ = run(world, monkeypatch, "en", "answer email 1 please", op("mail-reply", {"message": "1"}))
    assert not out.get("resend") and out["reply"] == sentence(world, "NW_MAIL_ASK_BODY_REPLY")
    assert not args_of(resolved)


def test_a_reply_draft_by_number_is_a_reply_draft_with_no_recipient_and_no_subject(world, clock, monkeypatch):
    out, resolved, _ = run(world, monkeypatch, "en", "put together a draft answer to email 2 with sounds good", op("mail-draft", {"message": "2", "body": "sounds good"}))
    got = args_of(resolved)
    assert len(got) == 1 and got[0]["message"] == "inbox#2" and got[0]["body"] == "sounds good" and "to" not in got[0] and "subject" not in got[0], (got, out["reply"])


def test_a_number_past_the_snapshots_end_is_refused_by_the_reference_and_opens_no_card(world, clock, monkeypatch):
    out, _, _ = run(world, monkeypatch, "en", "reply to email 9 with can we move it to next week", op("mail-reply", {"message": "9", "body": "can we move it to next week"}))
    assert not out.get("resend") and "inbox#9 names a message past the end of its snapshot" in out["reply"], out["reply"]


def test_a_move_by_number_with_no_folder_named_does_not_resolve(world, clock, monkeypatch):
    out, resolved, _ = run(world, monkeypatch, "en", "stash email 1 somewhere else", op("mail-move", {"messages": "1"}))
    assert not args_of(resolved) and not out.get("resend") and out["reply"] != sentence(world, "IX_CANNOT_WRITE"), out["reply"]


def test_a_project_language_with_no_write_forms_still_says_so(world, clock, monkeypatch):
    out, resolved, _ = run(world, monkeypatch, "de", "Lösch bitte die Mails 1 und 2", op("mail-trash", {"messages": "1,2"}))
    assert not resolved and out["reply"] == sentence(world, "IX_WRITE_LANGUAGE")


def test_a_numbered_line_never_refreshes_and_a_stale_snapshot_is_refused_with_no_card(world, clock, monkeypatch):
    calls = []
    monkeypatch.setattr(mail_refresh, "refresh_once", lambda *a, **k: calls.append(1) or {"ok": False})
    model = setup(world, monkeypatch, interpret=op("mail-trash", {"messages": "1,2"}), compose="{}", groups=GROUPS, language="en")
    world["desk"].providers.mail["gmail"] = [dict(FIRST), dict(SECOND)]
    world["desk"].refresh("inbox")
    world["desk"].later(hours=30)          # the snapshot is older than 26 hours: "a number from an old reading may name another item today"
    monkeypatch.setattr(ops_natural_mail, "_mail_sources", lambda ctx: [{"id": "inbox", "account": "google"}])
    out = phone(world, "trash emails 1 and 2 pls")
    assert model.of("interpret") and not calls and not out.get("resend"), (calls, out["reply"])
    assert "old" in out["reply"].lower() or "refresh" in out["reply"].lower(), out["reply"]


def test_a_line_the_closed_forms_read_never_reaches_the_numbers_seed(world, clock, monkeypatch):
    seen = []
    real = ops_natural_mail.mail_number_seed
    monkeypatch.setattr(ops_natural_mail, "mail_number_seed", lambda *a, **k: seen.append(a) or real(*a, **k))
    out, resolved, _ = run(world, monkeypatch, "pt-BR", "arquiva os e-mails 1 e 2", op("mail-archive", {"messages": "1,2"}))
    assert not seen and [a["messages"] for a in args_of(resolved)] == ["inbox#1,inbox#2"], out["reply"]


def test_the_gate_accepts_the_origins_of_every_opened_row(world, clock, monkeypatch):
    checked = []
    real = turn_gate.provenance

    def spy(*args, **kwargs):
        checked.append((args, kwargs))
        return real(*args, **kwargs)
    monkeypatch.setattr(turn_gate, "provenance", spy)
    out, resolved, _ = run(world, monkeypatch, "en", "trash emails 1 and 2 pls", op("mail-trash", {"messages": "1,2"}))
    assert args_of(resolved) and checked and "line-number" in repr(checked), (checked, out["reply"])


# --- vacuity -----------------------------------------------------------------------------------------------------------------------------------


def test_vacuity_a_free_numbers_that_echoes_the_decision_opens_the_rows_it_must_refuse(world, clock, monkeypatch):
    monkeypatch.setattr(nwm, "free_numbers", lambda line, spans=(), tables=None: [1])
    out, resolved, _ = run(world, monkeypatch, "en", "trash emails 1 and 2 pls", op("mail-trash", {"messages": "1"}))
    assert args_of(resolved), "the planted free_numbers must open the subset row (the real one refuses it)"


def test_vacuity_a_free_numbers_that_counts_every_digit_word_opens_the_count_noun_row(world, clock, monkeypatch):
    monkeypatch.setattr(nwm, "free_numbers", lambda line, spans=(), tables=None: [int(w) for w in line.replace(",", " ").split() if w.isdigit()])
    out, resolved, _ = run(world, monkeypatch, "en", "trash the 2 budgets pls", op("mail-trash", {"messages": "2"}))
    assert args_of(resolved), "the planted free_numbers must open the count-noun row (the real one refuses it)"


def test_vacuity_a_chain_rule_that_always_chains_counts_the_room_and_a_range_rule_that_never_fires_misses_the_range(monkeypatch):
    assert nwm.free_numbers("trash email 2 and the room 4", ()) == [2]
    with monkeypatch.context() as patch:
        patch.setattr(nwm, "_chained", lambda *a, **k: True)
        assert nwm.free_numbers("trash email 2 and the room 4", ()) == [2, 4]
    assert nwm.free_numbers("trash email 5 and emails 1-3", ()) == []
    with monkeypatch.context() as patch:
        patch.setattr(nwm, "_NUMBER_RANGE", nwm.re.compile(r"(?!x)x"))
        assert nwm.free_numbers("trash email 5 and emails 1-3", ()) == [5]


def test_vacuity_an_adjacent_rule_that_ignores_whether_the_earlier_number_counted_counts_the_room_number(monkeypatch):
    assert nwm.free_numbers("trash email 3 about room 4 5", ()) == [3]
    real = nwm._chained

    def loose(toks, folded, at, counted, articles, joiners):
        return (at > 0 and toks[at - 1][2].isdigit()) or real(toks, folded, at, counted, articles, joiners)
    monkeypatch.setattr(nwm, "_chained", loose)
    assert nwm.free_numbers("trash email 3 about room 4 5", ()) == [3, 5]


def test_vacuity_without_the_branch_of_carry_out_the_card_rows_fail(world, clock, monkeypatch):
    monkeypatch.setattr(ops_natural_mail, "mail_number_seed", lambda *a, **k: None)
    out, resolved, _ = run(world, monkeypatch, "en", "trash emails 1 and 2 pls", op("mail-trash", {"messages": "1,2"}))
    assert not resolved and out["reply"] == sentence(world, "IX_CANNOT_WRITE")


def test_vacuity_the_mirror_without_its_numbers_step_calls_a_subset_a_card(monkeypatch):
    item = {"id": "n-1", "split": "dev", "lang": "en", "hard": False, "clock": "2026-10-21T10:00", "zone": "America/Sao_Paulo", "channel": "messaging", "forwarded": False, "frame": None,
            "line": "trash emails 1 and 2 pls", "gold": {"outcome": "op"}, "also": []}

    def outcome():
        def call(system, user):
            return {"ok": True, "text": op("mail-trash", {"messages": "1"}), "finish": "stop", "usage": {}, "latency_ms": 1, "upstream": "stand-in"}
        return interpreter_pipeline.run_item(item, 1, call)["observed"]
    assert outcome() == "clarify"
    monkeypatch.setattr(interpreter_pipeline, "_numbers_step", lambda op_name, decision, line: None)
    assert outcome() == "card"
