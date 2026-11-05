"""The dev arm of catalog version 4 (package P5, SPEC-P5-CATALOG-V4): `evals/interpreter/dev-reading-v4.jsonl`, 37 fictional lines (pt-BR 23, en 14: 31 written by the executor of P5, six added in round 2, P5b) written by the executor of P5, not by the author of
any `about` text: the lines the new row `agenda` is meant for with their confusables (the mail list, a series that is an event, a routine that is named, a name that looks like a file's, the ops code
completes by asking, an account word on a mail act). It is dev evidence, never blind, and a NEW file: the frozen corpora and the earlier dev files are not touched.

What it holds, each oracle with this test's own literals: the file is canonical (the bytes the corpus tool writes) and sorted; the ids are unique, in the 63000 range and carry their language; every
gold and every `also` is a served op and slot of catalog version 4 and every span is a piece of its line (`interpreter_pipeline.item_problems` and `scripts/interpreter_corpus.py check`); the counts
by language, by kind of line and by operation are literals; no line is a line of a frozen set and none holds an address or a phone-like run; no line is claimed by stages 0 to 3 (code), so every line
reaches the model; an echo model that answers each gold, and each `also` taken as the gold, is `correct` on every item and `interpreter.check` reads each answer as an op; with the gold as the decision,
an `agenda` line's call is a list of the calendar and a line that names an account on a mail act gives a seed that carries that account. Offline, no model, no network.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interpreter_dev_reading_v4.py
"""
# validate: allow english-only -- the file holds Portuguese lines under test
from __future__ import annotations

import collections
import copy
import datetime
import importlib.util
import json
import re
from pathlib import Path

import standin_tree as st
from test_interpreter_echo import echo_object, run as echo_run

interpreter = st.load("interpreter")
interpreter_measure = st.load("interpreter_measure")
interpreter_pipeline = st.load("interpreter_pipeline")
event_lookup = st.load("event_lookup")
ops_items = st.load("ops_items")
ops_interpret = st.load("ops_interpret")
ops_natural_mail = st.load("ops_natural_mail")
operations = st.load("operations")

ROOT = Path(__file__).resolve().parents[2]
FOLDER = ROOT / "evals" / "interpreter"
FILE = FOLDER / "dev-reading-v4.jsonl"      # evals/interpreter/dev-reading-v4.jsonl, named literally so the test selector picks this test when the file changes
FROZEN = ("dev.jsonl", "dev-relabelled.jsonl", "ix-test-v1.jsonl", "dev-long-v1.jsonl", "dev-long-v2.jsonl", "blite-blind-v2.jsonl", "dev-catalog-v1.jsonl", "dev-mail-ask-v1.jsonl", "question-dev-v1.jsonl")

IDS_BY_LANG = {"pt-BR": "dev-pt-br-63", "en": "dev-en-63"}
ZONES = {"pt-BR": "America/Sao_Paulo", "en": "America/New_York"}
LANG_COUNTS = {"en": 14, "pt-BR": 23}
CLOCK = "2026-11-04T14:30"      # a Wednesday
# The kind of line of each id (the test's own table of the spec): A agenda with no noun, N agenda with a noun, T agenda with title words, B the mail list, S a series that is an event, R a routine
# that is named, F a name that looks like a file's, X no file, E an op code completes by asking, M an account word on a mail act.
KIND = {"dev-pt-br-63000": "A", "dev-pt-br-63001": "A", "dev-en-63000": "A", "dev-en-63001": "A",
        "dev-pt-br-63002": "N", "dev-pt-br-63003": "N", "dev-en-63002": "N", "dev-pt-br-63004": "T",
        "dev-pt-br-63005": "B", "dev-pt-br-63006": "B", "dev-en-63003": "B", "dev-pt-br-63007": "B",
        "dev-pt-br-63008": "S", "dev-pt-br-63009": "S", "dev-en-63004": "S", "dev-pt-br-63010": "S",
        "dev-pt-br-63011": "R", "dev-en-63005": "R", "dev-en-63006": "R",
        "dev-pt-br-63012": "F", "dev-en-63007": "F", "dev-pt-br-63013": "F", "dev-pt-br-63014": "F", "dev-en-63008": "X",
        "dev-pt-br-63015": "E", "dev-en-63009": "E", "dev-pt-br-63016": "E", "dev-pt-br-63017": "E", "dev-pt-br-63020": "E", "dev-en-63011": "E",
        "dev-pt-br-63021": "B", "dev-en-63012": "B", "dev-pt-br-63022": "S", "dev-en-63013": "S",
        "dev-pt-br-63018": "M", "dev-en-63010": "M", "dev-pt-br-63019": "M"}
KIND_COUNTS = {"A": 4, "N": 3, "T": 1, "B": 6, "S": 6, "R": 3, "F": 4, "X": 1, "E": 6, "M": 3}
OP_COUNTS = {"agenda": 8, "ask": 1, "event-cancel": 6, "file-ask": 4, "items": 6, "mail-archive": 1, "mail-draft": 2, "mail-mark": 1, "mail-reply": 2, "mail-send": 2, "mail-trash": 1,
             "routine-cancel": 1, "routine-change": 1, "routine-pause": 1}
ACCOUNT_OF_WORD = {"outlook": "microsoft", "gmail": "google"}      # the brand words the F lines hold, and the account each names (the test's own literals)


def tool(name="interpreter_corpus"):
    """A file of the tooling (scripts/ is loaded by path, never imported from runtime/ code)."""
    spec = importlib.util.spec_from_file_location(f"{name}_under_test", ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def rows(path: Path) -> list:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def canon(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def normal(text: str) -> str:
    return re.sub(r"\W+", " ", text.casefold()).strip()


ITEMS = rows(FILE)
CATALOG = tool().load_catalog(ROOT / "runtime" / "interpreter_catalog.json")


def as_gold(item, gold):
    """The item with an accepted answer taken as its gold (and no other): the echo model then answers it."""
    return dict(copy.deepcopy(item), gold=copy.deepcopy(gold), also=[])


def test_the_file_is_canonical_sorted_and_loads_in_the_harness():
    raw = FILE.read_text(encoding="utf-8")
    assert raw.endswith("\n") and "\r" not in raw
    lines = raw.split("\n")[:-1]
    assert len(lines) == 37 == len(ITEMS)
    assert lines == [canon(item) for item in ITEMS], "every line is the canonical JSON of its item"
    ids = [item["id"] for item in ITEMS]
    assert ids == sorted(ids) and len(set(ids)) == 37
    loaded, data = interpreter_measure.load_corpus(str(FILE))
    assert len(loaded) == 37 and data == FILE.read_bytes()


def test_ids_are_in_the_63000_range_and_carry_their_language():
    for item in ITEMS:
        assert re.fullmatch(r"dev-(pt-br|en)-(63[0-9]{3})", item["id"]), item["id"]
        assert item["id"].startswith(IDS_BY_LANG[item["lang"]]), item["id"]
    for lang, n in LANG_COUNTS.items():
        assert sorted(item["id"] for item in ITEMS if item["lang"] == lang) == [f"{IDS_BY_LANG[lang]}{k:03d}" for k in range(n)], "the numbers of a language run from 63000 without a gap"
    others = {item["id"] for name in FROZEN for item in rows(FOLDER / name)}
    assert not others & {item["id"] for item in ITEMS}, "no id of another set"


def test_every_item_is_a_dev_line_with_the_clock_of_the_spec_and_the_zone_of_its_language():
    for item in ITEMS:
        assert item["split"] == "dev" and item["channel"] == "messaging" and item["author"] == "opus"
        assert item["forwarded"] is False and item["frame"] is None and item["tags"] == [] and item["hard"] is False
        assert item["clock"] == CLOCK, item["id"]
        assert item["zone"] == ZONES[item["lang"]], item["id"]


def test_every_item_passes_both_item_checks():
    for item in ITEMS:
        assert interpreter_pipeline.item_problems(item) == [], item["id"]
    assert tool().check_items(ITEMS, CATALOG) == []


def test_every_gold_and_every_also_is_a_served_op_and_slot_at_catalog_version_4_and_every_span_is_in_its_line():
    served = {row["op"]: row["slots"] for row in interpreter.SERVED["ops"]}
    assert operations.LINE_CATALOG == 4 and interpreter.SERVED["v"] == 4
    assert served["agenda"] == {"target": "span", "day": "span"}, "the row this file measures, with the slots the spec gives it"
    assert all(served[op]["service"] == "word" for op in ("mail-reply", "mail-draft", "mail-archive", "mail-move", "mail-mark", "mail-trash"))
    for item in ITEMS:
        for answer in [item["gold"]] + item["also"]:
            if answer["outcome"] == "clarify":
                continue
            assert answer["outcome"] == "op" and answer["op"] in served, item["id"]
            for slot, spans in answer["slots"].items():
                assert slot in served[answer["op"]], (item["id"], slot)
                assert spans and all(isinstance(s, str) and s and s in item["line"] for s in spans), (item["id"], slot)
                if served[answer["op"]][slot] == "int":
                    assert all(s.isdigit() for s in spans), (item["id"], slot)


def test_every_span_slot_lists_its_value_with_and_without_its_article_or_preposition():
    """Rule W1 of dev-long-v2: where the line writes an article or a preposition before the value, the values accepted hold the value with it and without it."""
    for item in ITEMS:
        for answer in [item["gold"]] + item["also"]:
            if answer["outcome"] != "op":
                continue
            for slot, spans in answer["slots"].items():
                if slot in ("id", "message", "messages", "service", "to") or not any(" " in s or "-" in s for s in spans) and len(spans) == 1:
                    continue
                for span in spans:
                    bare = re.sub(r"^(o|a|os|as|no|na|nos|nas|do|da|dos|das|de|em|pro|the|in|on|for|from) ", "", span, flags=re.I)
                    assert bare == span or bare in spans, (item["id"], slot, span)


def test_the_counts_by_language_by_kind_and_by_operation_are_literals():
    assert dict(sorted(collections.Counter(item["lang"] for item in ITEMS).items())) == LANG_COUNTS
    assert sorted(KIND) == [item["id"] for item in ITEMS], "every id has a kind"
    assert dict(sorted(collections.Counter(KIND.values()).items())) == KIND_COUNTS
    assert dict(sorted(collections.Counter(item["gold"]["op"] for item in ITEMS).items())) == OP_COUNTS
    assert sum(OP_COUNTS.values()) == sum(KIND_COUNTS.values()) == sum(LANG_COUNTS.values()) == 37
    by_id = {item["id"]: item for item in ITEMS}
    assert {i for i, k in KIND.items() if k in "ANT"} == {i for i, item in by_id.items() if item["gold"]["op"] == "agenda"}, "the A, N and T lines are the lines whose gold is agenda"
    assert {i for i, k in KIND.items() if k == "B"} == {i for i, item in by_id.items() if item["gold"]["op"] == "items"}
    assert all(item["gold"]["op"] == "event-cancel" for i, item in by_id.items() if KIND[i] == "S") and all(item["gold"]["op"] == "file-ask" for i, item in by_id.items() if KIND[i] == "F")
    assert [by_id[i]["gold"]["op"] for i in by_id if KIND[i] == "X"] == ["ask"]
    accounts = [i for i, k in KIND.items() if k == "M"]
    assert all("service" in by_id[i]["gold"]["slots"] and any("service" not in a["slots"] for a in by_id[i]["also"]) for i in accounts), "the F lines name the account in the gold and accept the answer without it"
    assert all("service" not in by_id[i]["gold"]["slots"] for i, k in KIND.items() if k == "E"), "the lines code completes by asking give no account word"
    assert not any(a["outcome"] == "clarify" for i, k in KIND.items() if k == "E" for a in [by_id[i]["gold"]] + by_id[i]["also"]), "none of the E lines accepts clarify"


def test_the_lines_are_new_and_hold_no_address_and_no_phone_like_run():
    frozen = {normal(item["line"]) for name in FROZEN for item in rows(FOLDER / name)}
    lines = [normal(item["line"]) for item in ITEMS]
    assert len(set(lines)) == 37
    assert not frozen & set(lines), "no line of a frozen set"
    for item in ITEMS:
        text = item["line"]
        assert "@" not in text and "http" not in text and not re.search(r"\.(com|br|org|net)\b", text), item["id"]
        assert not re.search(r"[0-9]{8,}", text.replace(" ", "").replace("-", "")), item["id"]


def test_no_line_is_claimed_by_stages_0_to_3_so_every_line_reaches_the_model():
    assert [item["id"] for item in ITEMS if interpreter_pipeline.pre_model(item) is not None] == []


ASKED_BY_CODE = {"dev-en-63009", "dev-pt-br-63015", "dev-pt-br-63016", "dev-pt-br-63017", "dev-pt-br-63020", "dev-en-63011"}      # the E lines: the gold is the op (the line names the op and leaves its missing slot out: code asks the person for it)


def test_an_echo_model_is_correct_on_every_item_but_the_six_lines_code_completes_by_asking_and_on_every_also_taken_as_the_gold():
    off = {item["id"]: echo_run(item) for item in ITEMS if echo_run(item)[0] != "correct"}
    assert set(off) == ASKED_BY_CODE and all(KIND[i] == "E" for i in off), off
    assert all(got == ("clarify", "clarify") for got in off.values()), "the measurement mirrors the product (`interpreter_pipeline.with_mail_step`): an op of the family that lacks a slot is observed as the question code asks, so the scorer counts it `clarify`; the answer the gold says is an op, and the checker reads it as one (the next test)"
    wrong = {}
    for item in ITEMS:
        for number, answer in enumerate(item["also"]):
            got = echo_run(as_gold(item, answer))[0]
            if got != "correct":
                wrong[(item["id"], number)] = got
    assert wrong == {}, wrong


def decision_of(item, answer=None):
    """The decision `interpreter.check` reads from the answer an ideal model gives for the item (the gold, or one accepted answer), at the served catalog."""
    taken = as_gold(item, answer or item["gold"])
    return interpreter.check(echo_object(taken), item["line"], item["frame"], interpreter_pipeline.SERVED, interpreter_pipeline.now_of(item), item["zone"], interpreter_pipeline.ALLOWED)


def test_the_gold_of_every_op_line_is_read_as_an_op_by_the_checker():
    for item in ITEMS:
        decision = decision_of(item)
        assert decision["kind"] == "op" and decision["op"] == item["gold"]["op"], (item["id"], decision)


def test_with_the_gold_as_the_decision_an_agenda_line_is_a_list_of_the_calendar():
    now = interpreter_pipeline.now_of(ITEMS[0])
    agenda = [item for item in ITEMS if item["gold"]["op"] == "agenda"]
    assert len(agenda) == 8
    for item in agenda:
        decision = decision_of(item)
        spans = ops_items.span_args_of(decision["args"])
        args = ops_items.items_args(item["line"], now, None, spans, default_kind="calendar")
        assert args["kind"] == "calendar", item["id"]
    for item in agenda:
        assert ops_items.items_args(item["line"], now, None, {}, default_kind="calendar")["kind"] == "calendar", "the calendar of an agenda decision wins when the line names no noun"
    mail = next(item for item in ITEMS if item["id"] == "dev-pt-br-63007")      # "mostra meus e-mails e a agenda de amanhã": the line names both; items, not agenda, is the gold      # validate: allow english-only -- the Portuguese line under test
    assert mail["gold"]["op"] == "items"


def test_with_the_gold_as_the_decision_a_line_that_names_an_account_gives_a_seed_that_carries_it():
    by_id = {item["id"]: item for item in ITEMS}
    for item_id in [i for i, kind in KIND.items() if kind == "M"]:
        item = by_id[item_id]
        decision = decision_of(item)
        assert decision["kind"] == "op", item_id
        word = " ".join(item["gold"]["slots"]["service"]).casefold()
        day = None
        seed = ops_natural_mail.mail_target_seed(decision["op"], decision, day, item["line"], service=ops_interpret._service_of(decision, item["line"]))
        assert seed is not None and seed["slots"].get("account") == ACCOUNT_OF_WORD[word], (item_id, seed)
        assert seed.origins.get("account") == "line-span", "the account is a word of the line"
        without = decision_of(item, item["also"][0])
        assert "service" not in item["also"][0]["slots"]
        seed_without = ops_natural_mail.mail_target_seed(without["op"], without, day, item["line"], service=ops_interpret._service_of(without, item["line"]))
        assert seed_without is not None and "account" not in seed_without["slots"], "an answer with no account word adds nothing: the family asks which box"


# P5b (round 2): the title of the event each S line is about, as a planted snapshot row (the test's own literals), and the day the rows are on.
S_TITLES = {"dev-en-63004": "Weekly yoga", "dev-en-63013": "Weekly piano lesson", "dev-pt-br-63008": "Aula de pilates", "dev-pt-br-63009": "Academia teste", "dev-pt-br-63010": "Academia teste",      # validate: allow english-only -- the Portuguese titles under test
            "dev-pt-br-63022": "Aula de natação"}      # validate: allow english-only -- the Portuguese titles under test
UNRELATED = "Reunião de equipe"      # validate: allow english-only -- the Portuguese titles under test
TODAY = datetime.date(2026, 11, 4)


def test_every_accepted_target_of_a_series_line_finds_its_event_and_not_an_unrelated_one():
    """The event search (`event_lookup.ranked`, the day read from the target's own words as `_by_target` reads it) finds the event with the recurrence words in the target, and nothing else."""
    series = [item for item in ITEMS if KIND[item["id"]] == "S"]
    assert sorted(item["id"] for item in series) == sorted(S_TITLES), "every S line has a planted title"
    for item in series:
        now = interpreter_pipeline.now_of(item)
        for answer in [item["gold"]] + item["also"]:
            if answer["outcome"] != "op":
                continue
            for target in answer["slots"]["target"]:
                kind, value = event_lookup._day_named(target, now)
                day = TODAY + datetime.timedelta(days=(value - TODAY.weekday()) % 7) if kind == "weekday" else value if kind == "day" else None
                rows_ = [{"source": "agenda", "n": 1, "day": day or TODAY + datetime.timedelta(days=6), "time": "18:00-19:00", "title": S_TITLES[item["id"]]},
                         {"source": "agenda", "n": 2, "day": day or TODAY + datetime.timedelta(days=6), "time": "09:00-10:00", "title": UNRELATED}]
                found = event_lookup.ranked(rows_, target, kind, value, TODAY)
                assert [r["title"] for r in found] == [S_TITLES[item["id"]]], (item["id"], target, found)


def test_with_the_gold_as_the_decision_the_two_account_lists_name_the_account_and_the_line_alone_does_not():
    by_id = {item["id"]: item for item in ITEMS}
    now = interpreter_pipeline.now_of(ITEMS[0])
    for item_id, account in (("dev-pt-br-63021", "microsoft"), ("dev-en-63012", "google")):
        item = by_id[item_id]
        decision = decision_of(item)
        assert decision["kind"] == "op" and decision["op"] == "items", item_id
        spans = ops_items.span_args_of(decision["args"])
        service = ops_interpret._service_of(decision, item["line"])
        spans = ops_items.service_spans(spans, service)
        assert "service" not in spans and service == account, (item_id, spans, service)
        assert ops_items.items_args(item["line"], now, None, spans, service=service)["account"] == account, item_id
    english = by_id["dev-en-63012"]
    assert ops_items._named_account(english["line"]) == {} and "account" not in ops_items.items_args(english["line"], now, None, {}), "the slot is what reads the account of this line"


def test_the_checks_are_not_vacuous():
    tooling = tool()
    base = next(item for item in ITEMS if item["id"] == "dev-pt-br-63018")
    assert base["line"] == "marca o email do banco do outlook como lido" and tooling.check_items([base], CATALOG) == []
    planted = copy.deepcopy(base)
    planted["gold"]["slots"]["service"] = ["gmail"]          # not a piece of the line
    assert any("not in the line" in problem for problem in tooling.check_items([planted], CATALOG))
    wrong_slot = copy.deepcopy(base)
    wrong_slot["gold"]["slots"]["place"] = ["outlook"]          # not a slot of the op
    assert tooling.check_items([wrong_slot], CATALOG) != []
    claimed = copy.deepcopy(base)
    claimed["line"] = "/status"          # a typed command is stage 3 (code), not the model's
    assert interpreter_pipeline.pre_model(claimed) is not None
    assert echo_run(base)[0] == "correct"
    unreadable = copy.deepcopy(base)
    unreadable["gold"]["slots"]["service"] = ["gmail"]          # an echo that answers this gold names a span that is not in the line: the checker refuses it
    assert echo_run(unreadable)[0] != "correct"
    seeded = decision_of(base)
    poisoned = dict(seeded, args=dict(seeded["args"], account="dropbox"), spans=dict(seeded["spans"], service="dropbox"))
    assert "account" not in ops_natural_mail.mail_target_seed(poisoned["op"], poisoned, None, base["line"], service=ops_interpret._service_of(poisoned, base["line"]))["slots"], "a word that names no account adds nothing"
