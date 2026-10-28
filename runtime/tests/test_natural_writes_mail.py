"""The mail family of the writes asked in words (package NR-5b: runtime/natural_writes_mail.py, runtime/ops_natural_mail.py and the data `requests.writes.mail` of the language
tables): a plain line opens the card of a mail write only through the operation's own function, with every slot from code or asked back. Offline; no model is called, no
Google or Microsoft host is reached (the stand-ins are the ones test_mailbox_write.py and test_send_own_account.py use), every name and address is invented. Held here (the
limit is L61 of contracts/runtime.md, whose row package NR-5a writes; the mail part of its tests is this file):

  * each mail and mailbox form, in Brazilian Portuguese and in English, gives its operation and its slots; each containment negative goes on (a name and no body marker, a
    request for work, a scheduled send, a mention, a reply to several messages, a calendar line, a head that is not at the start of the line);
  * an address is only as written: a name asks for its address, an address inside a body is never a recipient, and the mailbox is never searched for one;
  * a subject and a body are exact slices of the person's line, with its punctuation, and a reply takes no recipient at all (limit L60 stays the operation's);
  * a message is `<source>#<n>` from digits written in the line, from the source written, the only mailbox of the account or the one the person chose; or it is found BY
    WORDS in the index of the newest snapshot: a singular object needs exactly one whole-word match (several are listed and asked), a plural object takes every match up to
    20 (more are asked); `último` picks the newest;
  * the snapshot is read, and a message is listed, only after the caller's right to read it was checked: a messaging sender without `ask-mail` gets the sentence of
    `item_refs` and nothing of the mailbox, not even the names of its sources;
  * a mail folder is a name the project lists, folded equal, never a near match; a message of the other account is refused by the operation's own sentence;
  * the answers to the questions a line leaves open (the account, the mailbox, the message, the address, the subject, the body, the folder, the state);
  * end to end on the stand-in tree: every arguments dict opens the card of the typed operation (the same `ops_natural._call` the dispatcher uses), and nothing is written.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_natural_writes_mail.py
"""
from __future__ import annotations

import copy

import pytest

import natural_writes_mail_cases as cases
import standin_tree as st
from test_channel_grants_mailbox import SENDER, accept
from test_mailbox_write import ACCOUNTS, calls, effect_doc, item_of, rows, world  # noqa: F401  (`world` is the fixture the end-to-end tests use)

nwm = st.load("natural_writes_mail")
onm = st.load("ops_natural_mail")
nt = st.load("natural_time")
natural = st.load("natural")
ops = st.load("ops")
ops_core = st.load("ops_core")
ops_natural = st.load("ops_natural")
operations = st.load("operations")
item_refs = st.load("item_refs")
phrases = st.load("phrases")
project_config = st.load("project_config")

TABLES = nt.languages()
ALL_READS = cases.PT_READS + cases.EN_READS


def read(line):
    return nwm.read(line, TABLES)


def ans(need, line, options=None):
    """The update of the slots that a line makes as the answer to a question of the family itself (the interface's `answer`), or None."""
    got = nwm.answer(need, line, {}, TABLES, options=options)
    return got["slots"] if got else None


def values(ask):
    return [o["value"] for o in ask["options"]]


def choose(ask, line):
    """The update a line makes to a question with options, as the foundation's generic answer takes it (the number shown, or the word): {slot: the value}, or None."""
    picked = st.load("ops_natural_writes")._option({"options": ask["options"], "multi": ask["multi"]}, line)
    return {ask["slot"]: picked} if picked is not None else None


class Said(Exception):
    """A final sentence the resolution gave ({"say": ...}) as the test reads it: the English sentence of the phrase table."""

    def __init__(self, say):
        super().__init__(phrases.en(say["sentence_key"]).format(**say["fields"]))
        self.say = say


def settle(out):
    if "say" in out:
        raise Said(out["say"])
    return {key: value for key, value in out.items() if key != "origins"}      # S41-7: the origins of the arguments are held by test_turn_gate_provenance.py; what these tests compare is the arguments


# --- the forms ---------------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("line,op,want,need", ALL_READS, ids=[c[0][:60] for c in ALL_READS])
def test_each_form_gives_its_operation_and_its_slots(line, op, want, need):
    found = read(line)
    assert found is not None, line
    assert found["op"] == op and found["need"] == need
    for key, value in want.items():
        assert found["slots"].get(key) == value, (line, key)


def test_the_forms_cover_every_mail_operation_in_both_languages():
    operations_seen = {c[1] for c in cases.PT_READS}, {c[1] for c in cases.EN_READS}
    wanted = {"mail-send", "mail-reply", "mail-draft", "mail-archive", "mail-move", "mail-mark", "mail-trash"}
    assert operations_seen[0] == wanted and operations_seen[1] == wanted


@pytest.mark.parametrize("line", cases.NEGATIVES + cases.EN_NEGATIVES + cases.WORK + cases.EN_WORK)
def test_a_line_that_is_not_a_closed_form_is_not_taken_and_goes_on(line):
    assert read(line) is None, line


def test_the_head_is_at_the_start_of_the_line_and_a_polite_word_may_come_first():
    assert read("me lembra de arquivar os e-mails 2 e 4") is None
    assert read("o que acha de arquivar os e-mails 2 e 4") is None
    assert read("por favor, arquiva os e-mails 2 e 4")["op"] == "mail-archive"
    assert read("could you archive emails 2 and 4")["op"] == "mail-archive"


def test_a_line_of_more_than_120_words_is_a_request_for_work_and_is_not_taken():
    assert read("responde o e-mail 3 dizendo que " + "palavra " * 130) is None
    assert read("responde o e-mail 3 dizendo que " + "palavra " * 40)["op"] == "mail-reply"


def test_a_scheduled_send_is_not_offered_and_a_time_inside_the_subject_or_the_body_is_the_persons_own_words():
    assert read("manda um e-mail pra bia@exemplo.example amanhã às 9 dizendo que segue") is None      # validate: allow english-only -- a Portuguese line is the input under test
    assert read("send an email to bia@example.example at 9am tomorrow saying hello") is None
    found = read("manda um e-mail pra bia@exemplo.example com o assunto reunião amanhã às 9 dizendo que chego às 9")      # validate: allow english-only -- a Portuguese line is the input under test
    assert found["slots"]["subject"] == "reunião amanhã às 9" and found["slots"]["body"] == "chego às 9"      # validate: allow english-only -- a Portuguese line is the input under test
    assert read("responde o e-mail 3 dizendo que amanhã às 9 eu ligo")["slots"]["body"] == "amanhã às 9 eu ligo"      # validate: allow english-only -- a Portuguese line is the input under test


def test_a_mention_is_never_part_of_a_write_and_an_address_that_is_not_plain_is_one():
    for line in ("manda um e-mail pra @bia dizendo oi", "manda um e-mail pra bia@ dizendo oi", "manda um e-mail pra bia@@exemplo.example dizendo oi",      # validate: allow english-only -- a Portuguese line is the input under test
                 "responde o e-mail 3 dizendo que fala com @caio"):
        assert read(line) is None, line
    assert read("manda um e-mail pra <bia@exemplo.example> dizendo oi")["slots"]["to"] == ["bia@exemplo.example"]      # validate: allow english-only -- a Portuguese line is the input under test


def test_what_a_wrong_pick_could_take_is_contained_a_work_request_with_a_write_verb_goes_on():
    for line in cases.WORK + cases.EN_WORK:
        assert read(line) is None, line


# --- an address only as written, a name asks, a body is verbatim -------------------------------------------------------------------------


def test_an_address_is_taken_only_as_written_in_the_line_and_a_name_is_asked_for_its_address():
    found = read("manda um e-mail pra Bia dizendo que o contrato segue amanhã")      # validate: allow english-only -- a Portuguese line is the input under test
    assert "to" not in found["slots"] and found["slots"]["to_names"] == ["Bia"] and found["need"] == ["to", "subject"]
    mixed = read("manda um e-mail pra Bia bia@exemplo.example dizendo oi")      # validate: allow english-only -- a Portuguese line is the input under test
    assert mixed is None, "a name beside an address is not guessed to be the same person: the line goes on"
    assert read("manda um e-mail pra bia@exemplo.example e caio@exemplo.example e BIA@Exemplo.Example dizendo oi")["slots"]["to"] == ["bia@exemplo.example", "caio@exemplo.example"]      # validate: allow english-only -- a Portuguese line is the input under test
    assert read("manda um e-mail pra " + ",".join(f"p{n}@exemplo.example" for n in range(21)) + " dizendo oi") is None, "more than the 20 recipients one e-mail takes"      # validate: allow english-only -- a Portuguese line is the input under test
    assert len(read("manda um e-mail pra " + ",".join(f"p{n}@exemplo.example" for n in range(20)) + " dizendo oi")["slots"]["to"]) == 20      # validate: allow english-only -- a Portuguese line is the input under test


def test_an_address_with_a_hyphen_a_dot_or_a_plus_is_read_whole_and_a_comma_or_a_semicolon_joins_recipients():
    assert read("manda um e-mail pra ana-maria@exemplo-corp.example dizendo oi")["slots"]["to"] == ["ana-maria@exemplo-corp.example"]      # validate: allow english-only -- a Portuguese line is the input under test
    assert read("manda um e-mail pra ana.maria+x@exemplo.example dizendo oi")["slots"]["to"] == ["ana.maria+x@exemplo.example"]      # validate: allow english-only -- a Portuguese line is the input under test
    assert read("manda um e-mail pra bia@exemplo.example;caio@exemplo.example, dora@exemplo.example dizendo oi")["slots"]["to"] == [      # validate: allow english-only -- a Portuguese line is the input under test
        "bia@exemplo.example", "caio@exemplo.example", "dora@exemplo.example"]
    assert read("manda um e-mail pra Ana-Maria dizendo oi")["slots"]["to_names"] == ["Ana-Maria"]      # validate: allow english-only -- a Portuguese line is the input under test
    assert read("manda um e-mail pra " + "a" * 65 + "@exemplo.example dizendo oi") is None, "an address the mail rules refuse is a mention, not a recipient"      # validate: allow english-only -- a Portuguese line is the input under test
    assert read("x" * 8001) is None and read("arquiva os e-mails 2 e 4 " + "y" * 8000) is None


def test_a_line_of_any_case_and_a_full_width_digit_are_read_and_a_hyphen_is_a_range_only_between_numbers():
    assert read("ARQUIVA OS E-MAILS 2 E 4")["slots"]["numbers"] == [2, 4]
    assert read("arquiva os e-mails ２ e ４")["slots"]["numbers"] == [2, 4]
    assert read("arquiva os e-mails 1-3")["slots"]["numbers"] == [1, 2, 3] and read("archive emails 1 - 3") is None
    assert read("archive e-mail 3")["slots"]["numbers"] == [3] and read("archive the e-mail 3")["slots"]["numbers"] == [3]
    assert read("move o e-mail 3 para a pasta contas-2026")["slots"]["folder_name"] == "contas-2026"      # validate: allow english-only -- a Portuguese line is the input under test


def test_an_address_inside_a_body_or_a_subject_is_never_a_recipient():
    found = read("manda um e-mail pra bia@exemplo.example dizendo que o caio@exemplo.example vai ligar")      # validate: allow english-only -- a Portuguese line is the input under test
    assert found["slots"]["to"] == ["bia@exemplo.example"] and found["slots"]["body"] == "o caio@exemplo.example vai ligar"
    reply = read("responde o e-mail 3 dizendo que escreve pra caio@exemplo.example")      # validate: allow english-only -- a Portuguese line is the input under test
    assert "to" not in reply["slots"] and "to_names" not in reply["slots"] and reply["op"] == "mail-reply", "a reply takes no recipient (limit L60)"
    draft = read("rascunha uma resposta ao e-mail 5 dizendo que caio@exemplo.example responde")
    assert "to" not in draft["slots"] and draft["op"] == "mail-draft" and draft["slots"]["numbers"] == [5]


def test_a_subject_and_a_body_are_exact_slices_of_the_line_with_its_punctuation():
    line = "manda um e-mail pra bia@exemplo.example com o assunto  Contrato novo (v2)  dizendo que Segue amanhã, ok? Abraço!  "      # validate: allow english-only -- a Portuguese line is the input under test
    found = read(line)
    folded = nt.normalise(line)[0]
    for name in ("subject", "body"):
        assert found["spans"][name] == found["slots"][name] and found["spans"][name] in line, "the person's own words, as written"
        start, end = found["ranges"][name]
        assert folded[start:end].strip() == nt.normalise(found["spans"][name])[0].strip(), "the range is in the folded line the reminder-trigger test reads"
    assert found["engine"] is None and found["doubt"] is False
    assert found["slots"]["subject"] == "Contrato novo (v2)" and found["slots"]["body"] == "Segue amanhã, ok? Abraço!"      # validate: allow english-only -- a Portuguese line is the input under test
    quoted = read("manda um e-mail pra bia@exemplo.example com o assunto \"Fatura\" dizendo \"confirmo\"")      # validate: allow english-only -- a Portuguese line is the input under test
    assert quoted["slots"]["subject"] == "Fatura" and quoted["slots"]["body"] == "confirmo"
    assert read("manda um e-mail pra bia@exemplo.example dizendo que " + "x" * 4001) is None, "the body written on a line is at most 4,000 characters"      # validate: allow english-only -- a Portuguese line is the input under test
    assert read("manda um e-mail pra bia@exemplo.example com o assunto " + "x" * 201 + " dizendo oi") is None      # validate: allow english-only -- a Portuguese line is the input under test
    assert "\n" in read("manda um e-mail pra bia@exemplo.example dizendo que oi\ncomo vai?\ntchau")["slots"]["body"], "a body may hold line ends"      # validate: allow english-only -- a Portuguese line is the input under test
    assert read("manda um e-mail pra bia@exemplo.example com o assunto linha um\nlinha dois dizendo oi") is None, "a subject is one line"      # validate: allow english-only -- a Portuguese line is the input under test


def test_a_colon_is_a_body_marker_but_a_colon_inside_a_subject_is_text():
    assert read("manda um e-mail pra bia@exemplo.example: oi, tudo bem?")["slots"]["body"] == "oi, tudo bem?"      # validate: allow english-only -- a Portuguese line is the input under test
    inside = read("manda um e-mail pra bia@exemplo.example com o assunto Fatura: outubro dizendo que segue")      # validate: allow english-only -- a Portuguese line is the input under test
    assert inside["slots"]["subject"] == "Fatura: outubro" and inside["slots"]["body"] == "segue"
    quoted = read("manda um e-mail pra bia@exemplo.example com o assunto \"Fatura\": segue anexa")      # validate: allow english-only -- a Portuguese line is the input under test
    assert quoted["slots"]["subject"] == "Fatura" and quoted["slots"]["body"] == "segue anexa"


def test_the_service_word_names_the_account_only_beside_the_head_or_alone_after_the_references():
    assert read("manda um e-mail pelo gmail pra bia@exemplo.example dizendo oi")["slots"]["service"] == "google"      # validate: allow english-only -- a Portuguese line is the input under test
    assert read("manda um e-mail pelo outlook pra bia@exemplo.example dizendo oi")["slots"]["service"] == "microsoft"      # validate: allow english-only -- a Portuguese line is the input under test
    assert read("manda um e-mail urgente pra bia@exemplo.example dizendo oi") is None      # validate: allow english-only -- a Portuguese line is the input under test
    assert "service" not in read("arquiva os e-mails do gmail do banco")["slots"], "`gmail` here is a word of the sender or the subject"
    assert read("arquiva os e-mails do gmail") is None, "all the e-mails of an account is no reference"
    assert read("arquiva os e-mails 2 e 4 do outlook")["slots"]["service"] == "microsoft"


def test_a_number_list_a_range_and_a_written_source_are_read_exactly_and_a_list_over_a_card_is_marked():
    assert read("arquiva os e-mails 2, 4 e 7")["slots"]["numbers"] == [2, 4, 7]
    assert read("arquiva os e-mails 2 4") is None, "two numbers with no joiner are not a list"
    assert read("arquiva os e-mails 3 a 1") is None, "a range backwards is no range"
    assert read("arquiva os e-mails 1 a 20")["slots"]["numbers"] == list(range(1, 21))
    assert read("arquiva os e-mails 1 a 21")["slots"]["over"] is True
    assert read("arquiva os e-mails 1-3")["slots"]["numbers"] == [1, 2, 3]
    assert read("arquiva os e-mails 2 e 2 e 4")["slots"]["numbers"] == [2, 4]
    assert read("arquiva os e-mails inbox#2, work#3")["slots"]["refs"] == ["inbox#2", "work#3"]
    assert read("arquiva os e-mails " + ", ".join(str(n) for n in range(1, 30)))["slots"]["over"] is True


def test_a_reply_answers_one_message_and_a_move_needs_its_folder_marker_and_a_mark_asks_for_the_state():
    assert read("responde os e-mails 3 e 4 dizendo ok") is None
    assert read("responde aos e-mails do banco dizendo ok") is None
    assert read("move o e-mail 6") is None
    assert read("marca o e-mail 4")["need"] == ["state"]
    assert read("mark email 4")["need"] == ["state"]
    assert read("marca o e-mail 4 como importante") is None


def test_the_data_of_the_tables_holds_no_regular_expression_character_and_a_broken_table_is_refused():
    for table in TABLES:
        mail = table["requests"]["writes"]["mail"]
        nwm.check_mail(mail, table["tag"])
        assert set(mail) == set(nwm.MAIL_KEYS)
        for key, phrases_ in mail.items():
            for phrase in phrases_:
                assert not nwm.PHRASE_BAD.search(phrase), (table["tag"], key, phrase)
                assert phrase == " ".join(phrase.split()) and phrase.isascii() and phrase == phrase.lower()
    good = copy.deepcopy(TABLES[0]["requests"]["writes"]["mail"])
    for mutate, why in ((lambda m: m.pop("body"), "a missing key"), (lambda m: m.update(extra=["x"]), "an extra key"), (lambda m: m["body"].append("dizendo (que"), "a bracket"),
                        (lambda m: m["body"].append("Dizendo"), "a capital"), (lambda m: m["body"].append("dizendo   que"), "a double space"),
                        (lambda m: m["body"].append("até"), "an accent"), (lambda m: m["body"].append(m["body"][0]), "a phrase twice"),
                        (lambda m: m["archive_verbs"].append(m["send_verbs"][0]), "a verb of two lists"), (lambda m: m.update(plural=["nothing"]), "a plural that is not a noun"),
                        (lambda m: m.update(body=[]), "an empty list"), (lambda m: m.update(to="para"), "a string")):
        broken = copy.deepcopy(good)
        mutate(broken)
        with pytest.raises(ValueError):
            nwm.check_mail(broken)
    assert nwm.check_mail(good) is None


def test_the_heads_are_the_verbs_of_the_tables():
    heads = nwm.HEADS(TABLES)
    assert heads == sorted(heads, key=lambda p: (-len(p), p))
    for verb in ("manda", "arquiva", "joga fora", "send", "archive", "faz um rascunho de"):
        assert verb in heads
    assert "marca" in heads and "move" in heads, "the verbs a calendar line shares are told apart by the noun, not by the verb"


def test_a_table_with_no_mail_part_reads_nothing_and_a_line_is_tried_with_the_table_of_every_language():
    bare = [{"tag": "xx", "requests": {}}]
    assert nwm.read("archive emails 2 and 4", bare) is None and nwm.HEADS(bare) == []
    assert nwm.read("arquiva os e-mails 2 e 4", TABLES)["op"] == "mail-archive" and nwm.read("archive emails 2 and 4", TABLES)["op"] == "mail-archive"
    assert nwm.read("archive emails 2 and 4", TABLES[::-1])["op"] == "mail-archive"


# --- the answers --------------------------------------------------------------------------------------------------------------------------


def test_an_answer_is_the_closed_thing_the_question_asked_for_and_anything_else_is_not_an_answer():
    answer = ans
    assert answer("to", "bia@exemplo.example") == {"to": ["bia@exemplo.example"], "to_names": None}
    assert answer("to", "bia@exemplo.example, caio@exemplo.example e bia@exemplo.example")["to"] == ["bia@exemplo.example", "caio@exemplo.example"]
    assert answer("to", "bia") is None and answer("to", "manda pra bia@exemplo.example") is None and answer("to", "@bia") is None and answer("to", "") is None      # validate: allow english-only -- a Portuguese line is the input under test
    assert answer("subject", "Reunião de sexta") == {"subject": "Reunião de sexta"} and answer("subject", "linha um\nlinha dois") is None and answer("subject", "x" * 201) is None      # validate: allow english-only -- a Portuguese line is the input under test
    assert answer("body", "chego às 9, ok?\nabraço") == {"body": "chego às 9, ok?\nabraço"} and answer("body", "   ") is None      # validate: allow english-only -- a Portuguese line is the input under test
    assert answer("state", "lido") == {"state": "read"} and answer("state", "não lido") == {"state": "unread"} and answer("state", "como lidos") == {"state": "read"}      # validate: allow english-only -- a Portuguese line is the input under test
    assert answer("state", "unread") == {"state": "unread"} and answer("state", "as read") == {"state": "read"} and answer("state", "talvez") is None
    shown = [{"value": "read", "label": "lido"}, {"value": "unread", "label": "nao lido"}]
    assert answer("state", "2", shown) == {"state": "unread"} and answer("state", "3", shown) is None and answer("state", "1") is None
    for need in ("account", "source", "message", "folder"):
        assert answer(need, "1", [{"value": "x", "label": "x"}]) is None, "an option is answered by the foundation's generic answer (the number shown or the word), not by the family"
    assert nwm.NEEDS == ("to", "subject", "body", "state")
    # the rules of the foundation for a text answer: a question, a work verb, a request or an over-long line is never the subject or the body
    assert answer("subject", "o que você acha?") is None and answer("body", "você vem hoje?") == {"body": "você vem hoje?"}      # validate: allow english-only -- a Portuguese line is the input under test
    assert answer("subject", "prepare um resumo do projeto") is None and answer("body", "escreve um resumo do projeto") is None, "a subject with a work verb, a body that starts with a mail verb"
    assert answer("subject", "uma frase que passa bastante do limite de palavras de um assunto de e-mail curto") is None
    assert answer("body", "chego as 9 e levo o bolo e depois a gente combina o resto com calma sem pressa nenhuma hoje") is not None
    assert answer("subject", "Fatura") == {"subject": "Fatura"} and answer("body", "chego às 9") == {"body": "chego às 9"}
    assert answer("nothing", "x", []) is None


# --- a message by words ---------------------------------------------------------------------------------------------------------------------

INDEX = [{"n": 1, "from_address": "ana.souza@clinic.example", "subject": "Appointment confirmed"},
         {"n": 2, "from_address": "billing@banco.example", "subject": "Fatura de outubro"},
         {"n": 3, "from_address": "bia@exemplo.example", "subject": "Contrato novo"},
         {"n": 4, "from_address": "noreply@banco.example", "subject": "Fatura de setembro"},
         {"n": 5, "from_address": "loja@shop.example", "subject": "Seu pedido foi enviado"}]


def test_a_message_matches_only_when_every_word_of_the_phrase_is_a_whole_word_of_its_sender_or_subject():
    ns = lambda *words, **kw: [e["n"] for e in nwm.match_words(INDEX, list(words), **kw)]  # noqa: E731
    assert ns("banco") == [2, 4] and ns("banco", "fatura") == [2, 4] and ns("banco", "setembro") == [4] and ns("fatura", "outubro") == [2]
    assert ns("bia") == [3] and ns("souza") == [1] and ns("ana") == [1], "the local part of the address is split on . _ - +"
    assert ns("ban") == [] and ns("example") == [] and ns("exemplo") == [3], "a piece of a word is no match, and the last label of a domain is not a word"
    assert ns("clinic") == [1] and ns("appointment") == [1]
    assert ns("banco", newest=True) == [2], "the newest is the lowest number: a snapshot is numbered newest first"
    assert ns() == [] and nwm.match_words(INDEX, [""]) == []
    assert ns("banco", "pedido") == []


def test_the_words_of_a_message_are_those_of_its_from_address_and_its_subject():
    assert nwm.entry_words({"from_address": "a.b-c_d+e@mail.big.example", "subject": "Fatura nº 12"}) >= {"a", "b", "c", "d", "e", "mail", "big", "fatura", "12"}
    assert "example" not in nwm.entry_words({"from_address": "a@mail.big.example", "subject": ""})
    assert nwm.entry_words({"from_address": None, "subject": None}) == set()
    assert "banco" in nwm.entry_words({"from_address": "Z@BANCO.example", "subject": ""})


# --- the resolution, over a stand-in index ---------------------------------------------------------------------------------------------------


class Desk:
    """A stand-in for what ops_natural_mail asks the project: the accounts of the configuration, the mail sources and the index of each, who may read. Nothing else."""

    def __init__(self, monkeypatch, accounts=("google", "microsoft"), sources=(("inbox", "google"), ("work", "microsoft")), indexes=None, readable=True, folders=None):
        self.cfg = {"accounts": {a: {"address": f"me-{a}@exemplo.example", "calendars": {}, "folders": {}, "mail_folders": (folders if folders is not None else {"contas": "L1", "viagens": "L2"}),
                                     "move_removes_inbox": True} for a in accounts}}
        self.ctx = {"cfg": self.cfg}
        self.sources = [{"id": i, "account": a} for i, a in sources]
        self.indexes = indexes if indexes is not None else {i: copy.deepcopy(INDEX) for i, _a in sources}
        self.reads, self.listed = [], []
        self.readable = readable
        monkeypatch.setattr(onm, "_mail_sources", lambda ctx: (self.listed.append(1), list(self.sources))[1])
        monkeypatch.setattr(item_refs, "may_read", lambda ctx, channel, sender=None: self.readable)
        monkeypatch.setattr(item_refs, "read_index", self.read_index)

    def read_index(self, ctx, source_id, *, channel, sender=None, kinds=None, evidence_base=None, clock=None):
        self.reads.append((source_id, channel, sender))
        if not self.readable:
            raise item_refs.ItemRefError("not_readable", "no")
        return {"source": source_id, "type": "mail", "entries": copy.deepcopy(self.indexes[source_id])}


def resolve(desk, line, channel="chat", sender=None, extra=None):
    found = read(line)
    assert found is not None, line
    slots = dict(found["slots"], **(extra or {}))
    return settle(onm.resolve(desk.ctx, found["op"], slots, channel, sender, [line]))


def test_one_configured_account_is_the_account_and_two_are_asked_unless_the_line_names_one_or_the_project_has_a_default(monkeypatch):
    one = Desk(monkeypatch, accounts=("google",))
    assert resolve(one, "manda um e-mail pra bia@exemplo.example com o assunto Oi dizendo que tudo bem") == {"args": {"account": "google", "to": "bia@exemplo.example", "subject": "Oi",      # validate: allow english-only -- a Portuguese line is the input under test
                                                                                                                       "text": "tudo bem"}}
    two = Desk(monkeypatch)
    asked = resolve(two, "manda um e-mail pra bia@exemplo.example com o assunto Oi dizendo que tudo bem")      # validate: allow english-only -- a Portuguese line is the input under test
    assert asked["ask"]["need"] == "account" and values(asked["ask"]) == ["google", "microsoft"] and asked["ask"]["sentence_key"] == "NW_ASK_ACCOUNT"
    assert [o["label"] for o in asked["ask"]["options"]] == ["Google (me-google@exemplo.example)", "Microsoft (me-microsoft@exemplo.example)"]
    assert choose(asked["ask"], "2") == {"account": "microsoft"} and choose(asked["ask"], "outlook") == {"account": "microsoft"} and choose(asked["ask"], "3") is None
    named = resolve(two, "manda um e-mail pelo outlook pra bia@exemplo.example com o assunto Oi dizendo que tudo bem")      # validate: allow english-only -- a Portuguese line is the input under test
    assert named["args"]["account"] == "microsoft"
    two.cfg["accounts"]["default"] = "microsoft"
    assert resolve(two, "manda um e-mail pra bia@exemplo.example com o assunto Oi dizendo que tudo bem")["args"]["account"] == "microsoft"      # validate: allow english-only -- a Portuguese line is the input under test
    assert resolve(two, "manda um e-mail pelo gmail pra bia@exemplo.example com o assunto Oi dizendo que tudo bem")["args"]["account"] == "google", "a service word beats the default"      # validate: allow english-only -- a Portuguese line is the input under test
    two.cfg["accounts"]["default"] = "google"
    none = Desk(monkeypatch, accounts=())
    with pytest.raises(Said) as why:
        resolve(none, "manda um e-mail pra bia@exemplo.example com o assunto Oi dizendo que tudo bem")      # validate: allow english-only -- a Portuguese line is the input under test
    assert str(why.value) == phrases.en("NW_NO_ACCOUNT")


def test_the_open_slots_of_a_new_e_mail_are_asked_one_at_a_time_in_a_fixed_order(monkeypatch):
    desk = Desk(monkeypatch, accounts=("google",))
    ask = resolve(desk, "manda um e-mail pra Bia dizendo que o contrato segue amanhã")["ask"]      # validate: allow english-only -- a Portuguese line is the input under test
    assert (ask["need"], ask["sentence_key"], ask["fields"]) == ("to", "NW_MAIL_ASK_TO", {"name": "Bia"})
    ask = resolve(desk, "manda um e-mail pra bia@exemplo.example dizendo que oi")["ask"]      # validate: allow english-only -- a Portuguese line is the input under test
    assert (ask["need"], ask["sentence_key"], ask["fields"]) == ("subject", "NW_MAIL_ASK_SUBJECT", {"to": "bia@exemplo.example"})
    ask = resolve(desk, "manda um e-mail pra bia@exemplo.example com o assunto Oi")["ask"]      # validate: allow english-only -- a Portuguese line is the input under test
    assert (ask["need"], ask["sentence_key"], ask["fields"]) == ("body", "NW_MAIL_ASK_BODY", {"to": "bia@exemplo.example"})
    assert resolve(desk, "rascunha um e-mail pra bia@exemplo.example com o assunto Oi dizendo que ok") == {"args": {"account": "google", "to": "bia@exemplo.example", "subject": "Oi", "body": "ok"}}      # validate: allow english-only -- a Portuguese line is the input under test
    assert desk.reads == [] and desk.listed == [], "an e-mail with no message in it reads no snapshot and lists no source"


def test_a_number_takes_the_only_mailbox_of_the_account_and_the_written_source_and_a_choice_decide_when_there_are_several(monkeypatch):
    desk = Desk(monkeypatch, accounts=("google",), sources=(("inbox", "google"),))
    assert resolve(desk, "arquiva os e-mails 2 e 4") == {"args": {"account": "google", "messages": "inbox#2,inbox#4"}}
    assert resolve(desk, "responde o e-mail 3 dizendo que chego às 9") == {"args": {"account": "google", "message": "inbox#3", "text": "chego às 9"}}
    assert resolve(desk, "rascunha uma resposta ao e-mail 5 dizendo que confirmo") == {"args": {"account": "google", "message": "inbox#5", "body": "confirmo"}}
    assert desk.reads == [], "a number needs no read of the snapshot: the operation reads it again with the caller's rights"
    both = Desk(monkeypatch)
    asked = resolve(both, "arquiva os e-mails 2 e 4")["ask"]
    assert asked["need"] == "source" and values(asked) == ["inbox", "work"] and asked["sentence_key"] == "NW_MAIL_ASK_SOURCE" and asked["slot"] == "source"
    assert resolve(both, "arquiva os e-mails 2 e 4", extra={"source": "work"}) == {"args": {"account": "microsoft", "messages": "work#2,work#4"}}
    assert resolve(both, "arquiva os e-mails 2 e 4 do outlook") == {"args": {"account": "microsoft", "messages": "work#2,work#4"}}
    assert resolve(both, "arquiva os e-mails 2 e 4 do gmail") == {"args": {"account": "google", "messages": "inbox#2,inbox#4"}}
    assert resolve(both, "arquiva os e-mails inbox#2 e inbox#3") == {"args": {"account": "google", "messages": "inbox#2,inbox#3"}}
    assert resolve(both, "arquiva os e-mails inbox#2 e work#3") == {"args": {"account": "google", "messages": "inbox#2,work#3"}}, "mixed sources: the operation refuses the other account's"
    with pytest.raises(Said) as why:
        resolve(both, "arquiva o e-mail nada#2")
    assert "nada" in str(why.value)
    none = Desk(monkeypatch, accounts=("google",), sources=())
    with pytest.raises(Said) as why:
        resolve(none, "arquiva os e-mails 2 e 4")
    assert str(why.value) == phrases.en("NW_MAIL_NO_SOURCE")
    nomail = Desk(monkeypatch, accounts=("google", "microsoft"), sources=(("inbox", "google"),))
    with pytest.raises(Said):
        resolve(nomail, "arquiva os e-mails 2 e 4 do outlook")


def test_the_newest_is_the_first_of_the_snapshot_and_a_list_over_a_card_is_refused_before_anything_is_read(monkeypatch):
    desk = Desk(monkeypatch, accounts=("google",), sources=(("inbox", "google"),))
    assert resolve(desk, "responde o último e-mail dizendo que ok") == {"args": {"account": "google", "message": "inbox#1", "text": "ok"}}
    assert desk.reads == [("inbox", "chat", None)], "the latest reads the snapshot (its age is checked)"
    desk.reads.clear()
    with pytest.raises(Said) as why:
        resolve(desk, "arquiva os e-mails 1 a 40")
    assert str(why.value) == phrases.en("NW_MAIL_TOO_MANY").format(max=20) and desk.reads == []
    assert len(resolve(desk, "arquiva os e-mails 1 a 20")["args"]["messages"].split(",")) == 20


def test_a_singular_object_by_words_needs_exactly_one_match_and_several_are_listed_and_asked(monkeypatch):
    desk = Desk(monkeypatch, accounts=("google",), sources=(("inbox", "google"),))
    assert resolve(desk, "responde ao e-mail da Bia dizendo que ok") == {"args": {"account": "google", "message": "inbox#3", "text": "ok"}}
    assert desk.reads == [("inbox", "chat", None)]
    asked = resolve(desk, "responde ao e-mail do banco dizendo que ok")["ask"]
    assert asked["need"] == "message" and values(asked) == ["inbox#2", "inbox#4"] and asked["sentence_key"] == "NW_MAIL_ASK_MESSAGE" and asked["fields"]["count"] == 2
    assert asked["slot"] == "chosen" and asked["multi"] is False
    assert [o["label"] for o in asked["options"]] == ["billing@banco.example · Fatura de outubro", "noreply@banco.example · Fatura de setembro"]
    assert resolve(desk, "responde ao último e-mail do banco dizendo que ok")["args"]["message"] == "inbox#2", "the newest is the lowest number"
    with pytest.raises(Said) as why:
        resolve(desk, "responde ao e-mail do cartorio dizendo que ok")
    assert str(why.value) == phrases.en("NW_MAIL_NONE").format(source="inbox", words="cartorio")
    # the chosen number goes back as the refs, and the next resolution has the message
    again = resolve(desk, "responde ao e-mail do banco dizendo que ok", extra=choose(asked, "2"))
    assert again == {"args": {"account": "google", "message": "inbox#4", "text": "ok"}}
    several = resolve(desk, "responde ao e-mail do banco dizendo que ok", extra={"chosen": ["inbox#2", "inbox#4"]})
    assert several["ask"]["need"] == "message", "a reply answers one message"


def test_a_plural_object_by_words_takes_every_match_up_to_20_and_asks_beyond(monkeypatch):
    desk = Desk(monkeypatch, accounts=("google",), sources=(("inbox", "google"),))
    assert resolve(desk, "arquiva os e-mails do banco") == {"args": {"account": "google", "messages": "inbox#2,inbox#4"}}
    assert resolve(desk, "arquiva os e-mails do banco sobre noreply") == {"args": {"account": "google", "messages": "inbox#4"}}
    assert resolve(desk, "arquiva o último e-mail do banco") == {"args": {"account": "google", "messages": "inbox#2"}}
    many = [{"n": n, "from_address": "banco@banco.example", "subject": f"Fatura {n}"} for n in range(1, 26)]
    big = Desk(monkeypatch, accounts=("google",), sources=(("inbox", "google"),), indexes={"inbox": many})
    asked = resolve(big, "apaga os e-mails do banco")["ask"]
    assert asked["need"] == "message" and asked["sentence_key"] == "NW_MAIL_ASK_MESSAGES_OVER" and len(asked["options"]) == 20 and asked["multi"] is True
    assert asked["fields"] == {"count": 25, "max": 20, "shown": 20}, "the newest twenty are listed (one card takes twenty), the count says there are more"
    chosen = choose(asked, "3, 7 e 20")
    assert resolve(big, "apaga os e-mails do banco", extra=chosen) == {"args": {"account": "google", "messages": "inbox#3,inbox#7,inbox#20"}}
    assert choose(asked, "21") is None, "a number the list did not show is not a choice"
    exact = Desk(monkeypatch, accounts=("google",), sources=(("inbox", "google"),), indexes={"inbox": many[:20]})
    assert len(resolve(exact, "apaga os e-mails do banco")["args"]["messages"].split(",")) == 20


def test_a_caller_who_may_not_read_the_snapshot_gets_the_sentence_of_item_refs_and_nothing_of_the_mailbox(monkeypatch):
    desk = Desk(monkeypatch, readable=False)
    for line in ("arquiva os e-mails 2 e 4", "responde ao e-mail da Bia dizendo que ok", "arquiva os e-mails do banco", "apaga o e-mail inbox#2", "responde o último e-mail dizendo ok"):
        with pytest.raises(Said) as why:
            resolve(desk, line, channel="messaging", sender="telegram:777")
        assert "may not read it" in str(why.value) and "ask-mail" in str(why.value), line
        assert "banco" not in str(why.value) and "Fatura" not in str(why.value)
    assert desk.reads == [] and desk.listed == [], "no snapshot was opened and no source was named to a caller who may not read"
    ok = Desk(monkeypatch, accounts=("google",), sources=(("inbox", "google"),))
    assert resolve(ok, "arquiva os e-mails do banco", channel="messaging", sender="telegram:830461975213")["args"]["messages"] == "inbox#2,inbox#4"
    assert ok.reads == [("inbox", "messaging", "telegram:830461975213")], "the snapshot is read with the caller's own channel and sender"


def test_the_listing_of_candidates_comes_only_after_read_index_accepted_the_caller(monkeypatch):
    desk = Desk(monkeypatch, accounts=("google",), sources=(("inbox", "google"),))
    order = []
    monkeypatch.setattr(item_refs, "may_read", lambda ctx, channel, sender=None: (order.append("may_read"), True)[1])
    real = desk.read_index

    def spy(ctx, source_id, **kw):
        order.append("read_index")
        return real(ctx, source_id, **kw)
    monkeypatch.setattr(item_refs, "read_index", spy)
    ask = resolve(desk, "responde ao e-mail do banco dizendo que ok")["ask"]
    assert order == ["may_read", "read_index"] and [o["label"] for o in ask["options"]] == ["billing@banco.example · Fatura de outubro", "noreply@banco.example · Fatura de setembro"]
    refused = Desk(monkeypatch, accounts=("google",), sources=(("inbox", "google"),))

    def stale(ctx, source_id, **kw):
        raise item_refs.ItemRefError("stale", "old")
    monkeypatch.setattr(item_refs, "read_index", stale)
    with pytest.raises(Said) as why:
        resolve(refused, "responde ao e-mail do banco dizendo que ok")
    assert "26 hours" in str(why.value) and "Fatura" not in str(why.value), "a refusal of the snapshot says nothing of the mailbox"


def test_a_folder_is_a_name_the_project_lists_folded_equal_and_never_a_near_match(monkeypatch):
    desk = Desk(monkeypatch, accounts=("google",), sources=(("inbox", "google"),), folders={"contas": "L1", "viagens-2026": "L2"})
    assert resolve(desk, "move os e-mails 2 e 3 para a pasta contas") == {"args": {"account": "google", "messages": "inbox#2,inbox#3", "folder": "contas"}}
    assert resolve(desk, "move o e-mail 2 para a pasta Contas")["args"]["folder"] == "contas"
    assert resolve(desk, "move o e-mail 2 para a pasta viagens 2026")["args"]["folder"] == "viagens-2026"
    ask = resolve(desk, "move o e-mail 2 para a pasta conta")["ask"]
    assert ask["need"] == "folder" and values(ask) == ["contas", "viagens-2026"] and ask["slot"] == "folder_name" and ask["sentence_key"] == "NW_ASK_FOLDER" and ask["fields"] == {"name": "conta", "names": "contas, viagens-2026"}
    assert resolve(desk, "move o e-mail 2 para a pasta conta", extra=choose(ask, "2"))["args"]["folder"] == "viagens-2026"
    assert choose(ask, "conta") is None, "a name that is not listed is no answer: the question stays"
    none = Desk(monkeypatch, accounts=("google",), sources=(("inbox", "google"),), folders={})
    with pytest.raises(Said) as why:
        resolve(none, "move o e-mail 2 para a pasta contas")
    assert str(why.value) == phrases.en("NW_MAIL_NO_FOLDERS").format(account="Google")


def test_a_mark_without_its_state_is_asked_and_the_answer_completes_it(monkeypatch):
    desk = Desk(monkeypatch, accounts=("google",), sources=(("inbox", "google"),))
    ask = resolve(desk, "marca o e-mail 4")["ask"]
    assert (ask["need"], values(ask), ask["sentence_key"]) == ("state", ["read", "unread"], "NW_MAIL_ASK_STATE")
    assert resolve(desk, "marca o e-mail 4", extra=ans("state", "não lido", ask["options"])) == {"args": {"account": "google", "messages": "inbox#4", "state": "unread"}}      # validate: allow english-only -- a Portuguese line is the input under test
    ask = resolve(desk, "responde o e-mail 3")["ask"]
    assert (ask["need"], ask["sentence_key"]) == ("body", "NW_MAIL_ASK_BODY_REPLY")


def test_every_phrase_the_resolution_can_ask_or_say_is_in_both_columns_with_the_same_fields():
    keys = [k for k in phrases.TABLE["en"] if k.startswith("NW_MAIL_")]
    assert len(keys) >= 14
    for key in keys:
        assert key in phrases.TABLE["pt-BR"], key
        assert phrases._fields_of(phrases.TABLE["en"][key]) == phrases._fields_of(phrases.TABLE["pt-BR"][key]), key
    used = {"NW_MAIL_NO_SOURCE", "NW_MAIL_NONE", "NW_MAIL_REFRESH_FAILED", "NW_MAIL_LIST_CHANGED", "NW_MAIL_TOO_MANY", "NW_MAIL_NO_FOLDERS", "NW_MAIL_BY_DATE", "NW_MAIL_NO_FORWARD", "NW_MAIL_ASK_SOURCE", "NW_MAIL_ASK_MESSAGE", "NW_MAIL_ASK_MESSAGES_OVER", "NW_MAIL_ASK_SENDER", "NW_MAIL_ASK_TO",
            "NW_MAIL_ASK_SUBJECT", "NW_MAIL_ASK_BODY", "NW_MAIL_ASK_BODY_REPLY", "NW_MAIL_ASK_STATE", "NW_MAIL_STATE_READ", "NW_MAIL_STATE_UNREAD"}
    assert used == set(keys), "a phrase nothing asks is a phrase to remove, and a question with no phrase would be a bug"
    fields = {"count": 2, "max": 20, "shown": 5, "name": "n", "names": "a, b", "to": "t", "source": "s", "words": "w", "account": "Google"}
    for key in used:
        for tag in ("en", "pt-BR"):
            text = phrases.text(key, {"language": tag}, **fields)
            assert text and "{" not in text, (key, tag)


# --- end to end: the arguments open the card of the typed operation on the stand-in tree and nothing is written ---------------------------------------------------


def line_args(world, line, channel="terminal", sender=None, extra=None):
    """The arguments the family resolves for `line` against the real project (its sources, its index, its accounts), and the operation they are for."""
    found = read(line)
    assert found is not None, line
    out = settle(onm.resolve(ops_core.context(world["path"]), found["op"], dict(found["slots"], **(extra or {})), channel, sender, [line]))
    return found["op"], out


def open_typed(world, op, args, channel=None, sender=None):
    """The operation's own function, called as the typed command is (the dispatcher's `_call` calls the same function with the carrying channel and sender)."""
    kwargs = dict(args)
    if channel == "messaging":
        kwargs.update(channel="messaging", sender=sender)
    return getattr(ops, operations.by_name(op)["call"])(world["path"], **kwargs)


def written(world):
    return [c for c in calls(world["google"]) if c[0] != "GET"] + [r for r in world["graph"].graph_requests() if r["method"] != "GET"]


def test_a_number_and_a_written_source_open_the_archive_card_of_those_messages_and_nothing_is_written(world):
    op, out = line_args(world, "arquiva os e-mails 1 e 2 do gmail")
    assert out == {"args": {"account": "google", "messages": "inbox#1,inbox#2"}}
    started = open_typed(world, op, out["args"])
    item = item_of(world, started)
    assert item["title"] == "Mailbox: archive messages"
    lines = item["body"].splitlines()
    assert lines[2] == "Archive: 2 message(s)" and "from ana@clinic.example" in lines[3] and "from bob@shop.example" in lines[4]
    assert written(world) == [] and rows(world)[1][0]["id"] == started["pending"]


def test_a_message_by_words_is_found_in_the_index_and_its_card_shows_it_as_the_mailbox_holds_it_now(world):
    op, out = line_args(world, "arquiva os e-mails do shop pelo gmail")
    assert out == {"args": {"account": "google", "messages": "inbox#2"}}, "the sender's domain label `shop` is a whole word of the message"
    started = open_typed(world, op, out["args"])
    assert "from bob@shop.example · Your order has shipped" in item_of(world, started)["body"]
    asked = line_args(world, "arquiva os e-mails do shop")[1]["ask"]
    assert asked["need"] == "source" and values(asked) == ["inbox", "work"], "two mailboxes: the person chooses"
    op, out = line_args(world, "arquiva os e-mails do shop", extra=choose(asked, "work"))
    assert out == {"args": {"account": "microsoft", "messages": "work#2"}}
    assert open_typed(world, op, out["args"], None)["word"] == "mailbox"
    assert written(world) == []


def test_a_singular_object_with_one_match_opens_that_message_and_the_newest_is_the_first_of_the_snapshot(world):
    op, out = line_args(world, "responde ao e-mail do clinic pelo gmail dizendo que confirmo")
    assert out == {"args": {"account": "google", "message": "inbox#1", "text": "confirmo"}}
    op, out = line_args(world, "responde ao último e-mail pelo gmail dizendo que confirmo")
    assert out["args"]["message"] == "inbox#1"


def test_a_reply_goes_to_the_sender_of_the_message_and_never_to_an_address_in_the_body(world):
    op, out = line_args(world, "responde ao e-mail da ana pelo gmail dizendo que escreve pra outro@elsewhere.example")      # validate: allow english-only -- a Portuguese line is the input under test
    assert out["args"] == {"account": "google", "message": "inbox#1", "text": "escreve pra outro@elsewhere.example"}      # validate: allow english-only -- a Portuguese line is the input under test
    started = open_typed(world, op, out["args"])
    doc = effect_doc(world, started)
    assert doc["to"] == ["ana@clinic.example"] and doc["cc"] == [] and doc["bcc"] == [], "limit L60: the recipient is the index's, not an address of the text"
    assert doc["reply"]["reply_to"] == "desk@clinic.example" and "outro@elsewhere.example" in doc["body"]
    assert written(world) == []


def test_a_new_e_mail_and_a_new_draft_open_their_cards_with_the_persons_own_words(world):
    op, out = line_args(world, "manda um e-mail pelo gmail pra bia@exemplo.example com o assunto Reunião de sexta dizendo que chego às 9")      # validate: allow english-only -- a Portuguese line is the input under test
    assert out == {"args": {"account": "google", "to": "bia@exemplo.example", "subject": "Reunião de sexta", "text": "chego às 9"}}      # validate: allow english-only -- a Portuguese line is the input under test
    started = open_typed(world, op, out["args"])
    doc = effect_doc(world, started)
    assert doc["to"] == ["bia@exemplo.example"] and doc["subject"] == "Reunião de sexta" and doc["body"] == "chego às 9" and doc["from"] == ACCOUNTS["google"]["address"]      # validate: allow english-only -- a Portuguese line is the input under test
    assert written(world) == []
    op, out = line_args(world, "rascunha um e-mail pelo outlook pra bia@exemplo.example com o assunto Oi dizendo que tudo bem")      # validate: allow english-only -- a Portuguese line is the input under test
    assert out["args"] == {"account": "microsoft", "to": "bia@exemplo.example", "subject": "Oi", "body": "tudo bem"}
    assert open_typed(world, op, out["args"])["word"] == "mailbox"
    op, out = line_args(world, "rascunha uma resposta ao e-mail inbox#2 dizendo que confirmo")
    assert out["args"] == {"account": "google", "message": "inbox#2", "body": "confirmo"}
    assert open_typed(world, op, out["args"])["word"] == "mailbox"


def test_a_move_a_mark_and_a_trash_open_their_cards_and_a_folder_the_project_does_not_list_is_asked(world):
    op, out = line_args(world, "move os e-mails 1 e 3 do gmail para a pasta bills")
    assert out["args"] == {"account": "google", "messages": "inbox#1,inbox#3", "folder": "bills"}
    assert open_typed(world, op, out["args"])["word"] == "mailbox"
    ask = line_args(world, "move os e-mails 1 e 3 do gmail para a pasta bill")[1]["ask"]
    assert ask["need"] == "folder" and values(ask) == ["bills", "later"]
    op, out = line_args(world, "marca os e-mails 1 a 3 do gmail como lidos")
    assert out["args"] == {"account": "google", "messages": "inbox#1,inbox#2,inbox#3", "state": "read"}
    assert open_typed(world, op, out["args"])["word"] == "mailbox"
    op, out = line_args(world, "apaga o e-mail 2 do outlook")
    assert out["args"] == {"account": "microsoft", "messages": "work#2"}
    assert open_typed(world, op, out["args"])["word"] == "mailbox"
    assert written(world) == []


def test_a_message_of_the_other_account_is_refused_by_the_operations_own_sentence_and_leaves_nothing(world):
    op, out = line_args(world, "arquiva o e-mail work#1", extra={"account": "google"})
    assert out == {"args": {"account": "google", "messages": "work#1"}}, "the line named an account and a message of the other: the operation decides"
    with pytest.raises(ops.OpsError) as why:
        open_typed(world, op, out["args"])
    assert "work#1" in str(why.value) and "google" in str(why.value)
    assert rows(world) == ([], []) and written(world) == []


def test_a_messaging_sender_needs_ask_mail_to_name_a_message_and_otherwise_learns_nothing_of_the_mailbox(world):
    accept(world["path"], {"messaging": ["read", "mail-organize"]})
    line = "arquiva os e-mails do shop pelo gmail"
    with pytest.raises(Said) as why:
        line_args(world, line, channel="messaging", sender=SENDER)
    assert "may not read it" in str(why.value) and "shop" not in str(why.value) and "Your order" not in str(why.value)
    assert rows(world) == ([], [])
    accept(world["path"], {"messaging": ["read", "mail-organize", "ask-mail"]})
    op, out = line_args(world, line, channel="messaging", sender=SENDER)
    assert out == {"args": {"account": "google", "messages": "inbox#2"}}
    started = open_typed(world, op, out["args"], channel="messaging", sender=SENDER)
    assert started["pending"] and written(world) == []
    accept(world["path"], {"messaging": ["read", "ask-mail"]})
    with pytest.raises(ops.OpsError) as why:
        open_typed(world, op, out["args"], channel="messaging", sender=SENDER)
    assert "not enabled" in str(why.value), "the operation's own group still decides: a line gets the typed command's refusal"


def test_the_mcp_mode_reads_no_snapshot_for_a_line_and_a_page_or_terminal_caller_may(world):
    for line in ("arquiva os e-mails 1 e 2 do gmail", "arquiva os e-mails do shop pelo gmail"):
        with pytest.raises(Said) as why:
            line_args(world, line, channel="mcp")
        assert "may not read it" in str(why.value)
    assert line_args(world, "arquiva os e-mails 1 e 2 do gmail", channel="page")[1]["args"]["messages"] == "inbox#1,inbox#2"
    assert line_args(world, "arquiva os e-mails 1 e 2 do gmail", channel="chat")[1]["args"]["messages"] == "inbox#1,inbox#2"


def test_the_family_reaches_no_effect_no_writer_and_no_approval_and_no_operation_of_the_layer():
    import ast
    allowed = {"__future__", "bisect", "datetime", "os", "re", "sys", "unicodedata", "zoneinfo", "mail_address", "natural_time", "item_refs", "mail_refs", "natural_writes_mail", "ops_core", "phrases", "project_config",
               "sources", "sources_mail", "natural", "mail_compose", "mail_refresh", "mail_reply_compose", "turn_gate"}      # mail_compose (slice S7) words a new e-mail through the daily route; it opens no card and executes nothing; turn_gate (S41-6) opens the line's refresh budget in `resolve` and holds no provider; mail_refresh (BL5E) reads a stale snapshot again through the source operations, once for a line; mail_reply_compose (BL7-2) decides when a reply's body is a description and words it through mail_compose.write, with no recipient and no subject; it opens no card and executes nothing
    for name in ("natural_writes_mail.py", "ops_natural_mail.py"):
        tree = ast.parse((st.RUNTIME / name).read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported.add((node.module or "").split(".")[0])
            elif isinstance(node, ast.Call) and ast.unparse(node.func).endswith("import_module"):
                imported.add("<dynamic>")
        assert imported <= allowed, (name, imported - allowed)
        called = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        assert not [c for c in called if any(word in c for word in ("approve", "execute", "effect", "account_start", "run_step", "ops."))], (name, called)
    assert (st.RUNTIME / "natural_writes_mail.py").read_text(encoding="utf-8").count("open(") == 0, "a pure module opens no file"


def test_the_registry_of_the_foundation_claims_every_mail_line_for_the_mail_family_and_leaves_the_rest():
    nw = st.load("natural_writes")
    assert list(nw.FAMILIES)[0] == "mail" and nw.FAMILIES["mail"] == "natural_writes_mail", "mail is read first: `marca o e-mail 3 como lido` is a mail form before it is a calendar verb"
    for line, op, _want, _need in ALL_READS:
        found = nw.read(line)
        assert found is not None and found["family"] == "mail" and found["op"] == op, line
        assert nw.read(line, op=op)["op"] == op
        assert nw.candidate(line) == {"family": "mail", "op": op}
    for line in cases.NEGATIVES + cases.EN_NEGATIVES + cases.WORK + cases.EN_WORK:
        found = nw.read(line)
        assert found is None or found["family"] != "mail", line      # a calendar line is another family's: what must hold is that the mail family does not take it
    found = nw.read("responde o e-mail 3 dizendo que me lembra amanhã de ligar")      # validate: allow english-only -- a Portuguese line is the input under test
    assert found["family"] == "mail" and found["spans"]["body"] == "me lembra amanhã de ligar", "a reminder trigger inside the body is the body"      # validate: allow english-only -- a Portuguese line is the input under test
    assert nw.read("me lembra de responder o e-mail 3 dizendo que oi") is None      # validate: allow english-only -- a Portuguese line is the input under test
    for table in TABLES:
        nw.check_writes(table)
        nwm.check_mail(table["requests"]["writes"]["mail"])


def test_a_line_read_with_a_router_named_operation_is_taken_only_when_the_parse_agrees():
    assert nwm.read("arquiva os e-mails 2 e 4", TABLES, op="mail-archive")["op"] == "mail-archive"
    assert nwm.read("arquiva os e-mails 2 e 4", TABLES, op="mail-trash") is None
    assert nwm.read("manda um e-mail pra Bia", TABLES, op="mail-send") is None, "a router cannot make a work request a write form"      # validate: allow english-only -- a Portuguese line is the input under test


# --- end to end through the card-opening path of the foundation (limit L61) ---------------------------------------------------------------------------------------


@pytest.fixture
def no_drafts():
    drafts = st.load("drafts")
    drafts.clear()
    yield drafts
    drafts.clear()


def test_limit_61_a_mail_line_opens_a_card_only_through_the_typed_operation_with_every_slot_from_the_line_or_the_persons_choice(world, no_drafts):
    onw = st.load("ops_natural_writes")
    ctx = ops_core.context(world["path"])
    extras = {}
    reply = onw.open_line(world["path"], ctx, "arquiva os e-mails 1 e 2 pelo gmail", "terminal", None, extras)      # validate: allow english-only -- a Portuguese line is the input under test
    assert "waits for your approval" in reply and "Archive: 2 message(s)" in reply and "approve" in reply, "the card is the confirmation: its lines and the approve command"
    pending = rows(world)[1]
    assert len(pending) == 1 and extras["resend"] == pending[0]["id"] and written(world) == [] and no_drafts.count() == 0
    # a reply: the body is asked, the answer is the line itself, and the recipient is the index's, never an address of the text
    extras = {}
    asked = onw.open_line(world["path"], ctx, "responde ao e-mail da ana pelo gmail", "terminal", None, extras)      # validate: allow english-only -- a Portuguese line is the input under test
    assert asked == phrases.text("NW_MAIL_ASK_BODY_REPLY", ctx["cfg"]) and extras["asked"] and no_drafts.count() == 1
    draft = onw.live("terminal", None)
    done = onw.answer(world["path"], ctx, draft, "confirmo, falo com outro@elsewhere.example depois", "terminal", None, extras)      # validate: allow english-only -- a Portuguese line is the input under test
    assert "waits for your approval" in done and no_drafts.count() == 0
    started = {"pending": extras["resend"], "task": max(t["id"] for t in ctx["store"].tasks_list(ctx["conn"]))}
    doc = effect_doc(world, started)
    assert doc["to"] == ["ana@clinic.example"] and doc["cc"] == [] and doc["bcc"] == [] and "outro@elsewhere.example" in doc["body"]
    assert written(world) == []


def test_limit_61_a_mail_line_names_a_message_only_for_a_caller_who_may_read_the_snapshot_and_a_question_lists_only_after_that(world, no_drafts):
    line = "arquiva os e-mails do shop pelo gmail"      # validate: allow english-only -- a Portuguese line is the input under test
    accept(world["path"], {"messaging": ["read", "mail-organize"]})
    refused = ops.natural_write(world["path"], line, channel="messaging", sender=SENDER)
    assert "may not read it" in refused["reply"] and "shop" not in refused["reply"] and "Your order" not in refused["reply"] and "resend" not in refused and no_drafts.count() == 0
    assert rows(world) == ([], [])
    accept(world["path"], {"messaging": ["read", "mail-organize", "ask-mail"]})
    opened = ops.natural_write(world["path"], "arquiva os e-mails do shop", channel="messaging", sender=SENDER)      # validate: allow english-only -- a Portuguese line is the input under test
    assert opened["asked"] is True and "mailbox" in opened["reply"].lower() and no_drafts.count() == 1, "two mailboxes: the question lists their ids only to a caller who may read"
    done = ops.natural_write(world["path"], "inbox", channel="messaging", sender=SENDER)
    assert done["asked"] is False and "waits for your approval" in done["reply"] and done["resend"] == rows(world)[1][0]["id"] and written(world) == []


def test_the_mail_family_keeps_the_contract_of_a_family_of_the_foundation():
    import inspect
    assert nwm.HEADS(TABLES) and all(isinstance(h, str) for h in nwm.HEADS(TABLES))
    assert list(inspect.signature(nwm.read).parameters) == ["line", "tables", "now", "op"]
    assert list(inspect.signature(nwm.answer).parameters) == ["need", "line", "slots", "tables", "now", "options"]
    found = nwm.read("responde o e-mail 3 dizendo que chego às 9", TABLES)      # validate: allow english-only -- a Portuguese line is the input under test
    assert set(found) == {"op", "slots", "spans", "ranges", "need", "engine", "doubt"} and set(found["spans"]) <= set(found["slots"]) and set(found["ranges"]) == set(found["spans"])
    sample = {"need": "state", "slot": "state", "sentence_key": "NW_MAIL_ASK_STATE", "fields": {}, "options": [{"value": "read", "label": "lido"}, {"value": "unread", "label": "nao lido"}],
              "multi": False, "engine": None}
    assert set(sample) == {"need", "slot", "sentence_key", "fields", "options", "multi", "engine"}


# --- the review of the package (M1 to M6 and the minor points): each probe is a test ----------------------------------------------------------------------------


def talk(world, lines, channel="terminal", sender=None):
    """The lines a person types one after the other to the card-opening path (the open question first, then the line as a new one): [(line, reply, the decision resent)]."""
    onw = st.load("ops_natural_writes")
    ctx = ops_core.context(world["path"])
    out = []
    for line in lines:
        extras = {}
        draft = onw.live(channel, sender)
        reply = onw.answer(world["path"], ctx, draft, line, channel, sender, extras) if draft is not None else None
        if reply is None:
            reply = onw.open_line(world["path"], ctx, line, channel, sender, extras)
        out.append((line, reply, extras.get("resend")))
    return out


def test_the_provenance_check_reads_the_raw_line_and_catches_a_misreading_of_the_family():
    """M1: the oracle of the fuzz is derived from the raw lines with the marker words of the tables, never from the family's own reading, so a misreading cannot vouch for itself."""
    nw = st.load("natural_writes")
    accounts = {"google": {"address": "me@exemplo.example", "calendars": {}, "folders": {}, "mail_folders": {"contas": "L1"}}}
    offered = {"mail_sources": {"inbox": "google"}, "mail_index": {"inbox": INDEX}, "options": set()}

    def check(op, args, *said):
        return nw.problems(op, args, list(said), accounts, offered, None)
    send = "manda um e-mail pra bia@exemplo.example com o assunto Oi dizendo que fala com ana@outra.example"      # validate: allow english-only -- a Portuguese line is the input under test
    assert check("mail-send", {"account": "google", "to": "bia@exemplo.example", "subject": "Oi", "text": "fala com ana@outra.example"}, send) == []
    assert check("mail-send", {"account": "google", "to": "bia@exemplo.example,ana@outra.example", "subject": "Oi", "text": "fala com ana@outra.example"}, send), "an address of the body is no recipient"
    subject = "manda um e-mail pra bia@exemplo.example com o assunto ana@outra.example dizendo oi"      # validate: allow english-only -- a Portuguese line is the input under test
    assert check("mail-send", {"account": "google", "to": "ana@outra.example", "subject": "x", "text": "oi"}, subject), "an address of the subject is no recipient"
    assert check("mail-send", {"account": "google", "to": "bia@exemplo.example", "subject": "ana@outra.example", "text": "oi"}, subject) == []
    assert check("mail-send", {"account": "google", "to": "ana@outra.example", "subject": "Oi", "text": "oi"}, "manda um e-mail pra Ana com o assunto Oi dizendo oi", "ana@outra.example") == []      # an address answer: a line of addresses      # validate: allow english-only -- a Portuguese line is the input under test
    reply = "responde o e-mail 1 dizendo que chego às 3"      # validate: allow english-only -- a Portuguese line is the input under test
    assert check("mail-reply", {"account": "google", "message": "inbox#1", "text": "chego às 3"}, reply) == []      # validate: allow english-only -- a Portuguese line is the input under test
    assert check("mail-reply", {"account": "google", "message": "inbox#3", "text": "chego às 3"}, reply), "a number of the body is no reference"      # validate: allow english-only -- a Portuguese line is the input under test
    bank = "arquiva os e-mails do banco"
    assert check("mail-archive", {"account": "google", "messages": "inbox#2,inbox#4"}, bank) == []
    assert check("mail-archive", {"account": "google", "messages": "inbox#2,inbox#3,inbox#4"}, bank), "a message that does not hold the words, however near"
    assert check("mail-archive", {"account": "google", "messages": "inbox#2"}, bank), "a plural object is the whole set of matches, not a part"
    body_words = "responde o e-mail 3 dizendo que o banco ligou"      # validate: allow english-only -- a Portuguese line is the input under test
    assert check("mail-reply", {"account": "google", "message": "inbox#2", "text": "que o banco ligou"}, body_words), "words of the body are no words of the message"
    widened = "arquiva os e-mails do banco sobre noreply"
    assert check("mail-archive", {"account": "google", "messages": "inbox#4"}, widened) == []
    assert check("mail-archive", {"account": "google", "messages": "inbox#2,inbox#4"}, widened), "words widened by the family: only the one that holds all of them is a match"
    mark = "marca o e-mail 4 como lido"
    assert check("mail-mark", {"account": "google", "messages": "inbox#4", "state": "read"}, mark) == []
    assert check("mail-mark", {"account": "google", "messages": "inbox#4", "state": "unread"}, mark), "a state nobody said"
    assert check("mail-mark", {"account": "google", "messages": "inbox#4", "state": "read"}, "marca o e-mail 4 como não lido") != [], "`nao lido` says unread, not read"      # validate: allow english-only -- a Portuguese line is the input under test
    assert check("mail-mark", {"account": "google", "messages": "inbox#4", "state": "read"}, "marca o e-mail 4 dizendo que li") != []      # validate: allow english-only -- a Portuguese line is the input under test
    middle = "manda um e-mail pelo gmail pra bia@exemplo.example dizendo que o e-mail foi lido"      # validate: allow english-only -- a Portuguese line is the input under test
    assert check("mail-mark", {"account": "google", "messages": "inbox#4", "state": "read"}, middle, "marca o e-mail 4"), "a state word inside a body is no state"      # validate: allow english-only -- a Portuguese line is the input under test


def test_a_yes_is_never_a_subject_a_body_or_an_address_and_the_question_is_asked_again_once_then_given_up(world, no_drafts):
    """M2: the foundation hands the needs of the family to the family before its own yes guard, so the family applies the guard itself."""
    for word in ("sim", "yes", "ok", "claro", "sure"):
        assert ans("subject", word) is None and ans("body", word) is None and ans("to", word) is None, word
    first = "manda um e-mail pelo gmail pra bia@exemplo.example com o assunto Oi"      # validate: allow english-only -- a Portuguese line is the input under test
    out = talk(world, [first, "sim"])
    assert out[0][1] == phrases.text("NW_MAIL_ASK_BODY", ops_core.context(world["path"])["cfg"], to="bia@exemplo.example") and "waits" not in out[1][1], out
    out = talk(world, [first, "sim", "sim"])
    assert out[2][1] == phrases.text("NW_GIVE_UP", None) and out[2][2] is None and no_drafts.count() == 0, "asked once more, then given up: no trap loop"
    out = talk(world, [first, "sim", "confirmo sexta"])
    assert out[2][2] is not None and "waits for your approval" in out[2][1], "a real body after the re-ask opens the card"


def test_a_name_with_a_verb_or_a_long_tail_is_a_sentence_and_not_a_message_and_a_request_is_never_a_body():
    """M3: the words after `do/da/de` are the name of a sender or a subject: at most three content words, and neither a verb nor a gerund."""
    for line in ("responde o e-mail do cliente explicando o atraso", "responde o e-mail do cliente pedindo desconto", "arquiva os e-mails do banco itau bradesco santander",      # validate: allow english-only -- a Portuguese line is the input under test
                 "reply to the email from the client explaining the delay saying ok", "archive the emails from the bank asking for a discount"):
        assert read(line) is None, line
    assert read("responde o e-mail do banco itau dizendo ok")["slots"]["words"] == ["banco", "itau"]
    assert read("arquiva os e-mails do banco itau bradesco")["slots"]["words"] == ["banco", "itau", "bradesco"]
    for text in ("escreve uma resposta educada dizendo que não posso", "write a polite reply saying no", "arquiva os e-mails 2 e 4", "manda um e-mail pra bia@exemplo.example"):      # validate: allow english-only -- a Portuguese line is the input under test
        assert ans("body", text) is None, text
    assert ans("body", "você pode vir amanhã?") == {"body": "você pode vir amanhã?"} and ans("body", "preciso do contrato até sexta") is not None      # validate: allow english-only -- a Portuguese line is the input under test
    for word in ("explica", "explique", "pede", "avisa", "escreve"):
        assert any(word in table["work_verbs"] for table in TABLES), word


def test_a_message_is_never_found_by_a_date_and_the_line_says_so(monkeypatch):
    """M4: a day, a month, a weekday or a relative time among the words is not the name of a sender or a subject; no match is made, however many words come with it."""
    for line in ("apaga os e-mails de ontem", "apaga os e-mails de hoje", "arquiva os e-mails de sexta", "arquiva os e-mails de setembro", "apaga os e-mails da semana passada",      # validate: allow english-only -- a Portuguese line is the input under test
                 "arquiva os e-mails do banco de ontem", "archive the emails from yesterday", "delete the emails from last week", "archive the emails from September", "trash emails from friday"):
        found = read(line)
        assert found is not None and found["slots"].get("by_date") is True, line
        desk = Desk(monkeypatch, accounts=("google",), sources=(("inbox", "google"),))
        out = onm.resolve(desk.ctx, found["op"], found["slots"], "chat", None, [line])
        assert out == {"say": {"sentence_key": "NW_MAIL_BY_DATE", "fields": {}}} and desk.reads == [], line
    assert "by_date" not in read("arquiva os e-mails do banco")["slots"] and "by_date" not in read("arquiva os e-mails da loja")["slots"]      # validate: allow english-only -- a Portuguese line is the input under test


def test_a_range_of_numbers_is_not_a_folder_and_a_move_needs_a_name_that_is_neither_a_number_nor_a_service():
    """M5: `to` is a range word and a folder marker; `move emails 1 to 3 via gmail` is a range and a service, not the folder `3 via gmail`."""
    assert read("move emails 1 to 3 via gmail") is None and read("move email 6 to 3") is None and read("move emails 1 to 3") is None
    found = read("move emails 1 to 3 via gmail to bills")
    assert found["slots"]["numbers"] == [1, 2, 3] and found["slots"]["folder_name"] == "bills" and found["slots"]["service"] == "google"
    assert read("move emails 1 to 3 to the folder bills")["slots"]["numbers"] == [1, 2, 3]
    assert read("move email 6 to google") is None and read("move email 6 via gmail") is None
    assert read("move os e-mails 1 a 3 para contas")["slots"]["numbers"] == [1, 2, 3]      # validate: allow english-only -- a Portuguese line is the input under test


def test_the_title_of_an_event_that_starts_with_a_bare_mail_verb_is_a_title_and_a_closed_head_is_a_request():
    """M6: `HEADS` are verbs for the prefilter; a line offered as a title is a request only when it starts with a closed head (verb, articles, object)."""
    onw = st.load("ops_natural_writes")
    for title in ("Passa no banco", "Envia proposta", "Send flowers", "Reply to Ana", "Archive old photos", "Marca presença"):      # validate: allow english-only -- a Portuguese line is the input under test
        assert onw._another_request(title, TABLES) is False, title
        assert nwm.is_head(title, TABLES) is False, title
    for request in ("manda um e-mail pra bia", "arquiva os e-mails 2 e 4", "responde o e-mail 3", "send an email to bia", "archive the emails from the bank"):      # validate: allow english-only -- a Portuguese line is the input under test
        assert nwm.is_head(request, TABLES) is True and onw._another_request(request, TABLES) is True, request


def test_a_reply_body_may_ask_and_is_kept_verbatim_with_its_question_mark_and_the_card_shows_it(world, no_drafts):
    """Minor 1 and 2: a body that is a question is a valid body; it is the person's words, kept as written (the final `?` too), and the card shows it whole."""
    out = talk(world, ["pode mandar um e-mail pelo gmail pra bia@exemplo.example com o assunto Oi dizendo você pode vir hoje?"])      # validate: allow english-only -- a Portuguese line is the input under test
    assert out[0][2] is not None and "você pode vir hoje?" in out[0][1], out      # validate: allow english-only -- a Portuguese line is the input under test
    ctx = ops_core.context(world["path"])
    started = {"pending": out[0][2], "task": max(t["id"] for t in ctx["store"].tasks_list(ctx["conn"]))}
    assert effect_doc(world, started)["body"] == "você pode vir hoje?"      # validate: allow english-only -- a Portuguese line is the input under test


def test_pro_is_a_marker_of_the_recipient_and_a_person_after_a_bare_to_is_not_a_folder(monkeypatch):
    """Minor 3 and 5: `pro joao` addresses a person; `move o e-mail da ana para o joao` is a forward, which is not built, and never a move to a folder called `o joao`."""
    assert read("manda um e-mail pro João dizendo oi")["slots"]["to_names"] == ["João"]      # validate: allow english-only -- a Portuguese line is the input under test
    assert read("manda um e-mail pros clientes dizendo oi")["slots"]["to_names"] == ["clientes"]      # validate: allow english-only -- a Portuguese line is the input under test
    found = read("move o e-mail da ana para o joão")      # validate: allow english-only -- a Portuguese line is the input under test
    assert found["slots"].get("folder_bare") is True and read("move o e-mail 6 para a pasta contas")["slots"].get("folder_bare") is None
    desk = Desk(monkeypatch, accounts=("google",), sources=(("inbox", "google"),))
    out = onm.resolve(desk.ctx, found["op"], found["slots"], "chat", None, [])
    assert out["say"]["sentence_key"] == "NW_MAIL_NO_FORWARD" and out["say"]["fields"]["names"] == "contas, viagens"
    ok = read("move o e-mail 6 para o contas")      # validate: allow english-only -- a Portuguese line is the input under test
    assert onm.resolve(desk.ctx, ok["op"], ok["slots"], "chat", None, [])["args"]["folder"] == "contas", "a bare marker still moves to a folder the project lists"


def test_the_latest_message_with_no_words_reads_the_snapshot_and_a_stale_one_names_nothing(monkeypatch):
    """Minor 4: `o ultimo e-mail` is message 1 of the newest snapshot, which is read (its age is checked: more than the limit of an unattended task names nothing)."""
    desk = Desk(monkeypatch, accounts=("google",), sources=(("inbox", "google"),))
    found = read("responde o último e-mail dizendo ok")      # validate: allow english-only -- a Portuguese line is the input under test
    out = onm.resolve(desk.ctx, found["op"], found["slots"], "chat", None, [])
    assert out["args"] == {"account": "google", "message": "inbox#1", "text": "ok"} and desk.reads == [("inbox", "chat", None)]

    def stale(ctx, source_id, **kw):
        raise item_refs.ItemRefError("stale", "old")
    monkeypatch.setattr(item_refs, "read_index", stale)
    out = onm.resolve(desk.ctx, found["op"], found["slots"], "chat", None, [])
    assert out["say"]["sentence_key"] == "ACCT_MAIL_REF_STALE"
