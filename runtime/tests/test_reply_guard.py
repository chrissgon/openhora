"""The code guard that tells a new request from an answer to the reminder question (CANDIDATE-OUT PR 1). Offline, no model, no network, no clock but the pinned one; invented lines.

What it holds: (1) the reply set is the set that was frozen before the guard existed (its bytes, its split, its ids), (2) the bars on the test split (B1 hard, B2) and the published agreement,
which a decision file states and this file recomputes, (3) an oracle per step of `turn_gate.new_request` with the test's own literals and a twin that differs by the word that matters, (4) the
kind question and the yes with an amendment, each with its twin, (5) the time answers, (6) no gate and no model call in the guard, (7) every product call of `natural.complete` and
`natural.short_answer` passes the guard's verdict. Each invariant has a vacuity case that fails on a planted wrong result.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_reply_guard.py
"""
from __future__ import annotations

import ast
import hashlib
import inspect
import json
import re
from pathlib import Path

import pytest

import reply_guard_build as rgb
import reply_guard_measure as rgm
import standin_tree as st

natural = st.load("natural")
turn_gate = st.load("turn_gate")
phrases = st.load("phrases")
NOW = rgb.now_clock()
REPO = Path(__file__).resolve().parents[2]
DECISIONS = sorted((REPO / "docs" / "decisions").glob("*-candidate-out-reply-guard.md"))


def draft(seed, lang="pt-BR"):
    return rgb.make_draft(natural, phrases, seed, lang)


def complete(seed, line, lang="pt-BR"):
    """The product's call on a recipe's draft and a line."""
    return turn_gate.complete_reminder(draft(seed, lang), line, NOW)


@pytest.fixture(scope="module")
def pairs():
    header, rows = rgb.read_rows()
    return header, rows


@pytest.fixture(scope="module")
def figures(pairs):
    return rgm.measure(pairs[1], natural, turn_gate, phrases)


# --- 1. the set is the set that was frozen --------------------------------------------------------------------------------------------------------------

def test_the_set_hashes_to_the_frozen_split_file(pairs):
    frozen = json.loads(rgm.SPLIT_FILE.read_text(encoding="utf-8"))
    header, rows = pairs
    assert rgm.file_sha256() == frozen["sha256"]
    assert len(rows) == frozen["count"] == header["count"]
    assert header["base_commit"] == frozen["base_commit"] and len(frozen["base_commit"]) == 40
    assert {s: sum(1 for r in rows if r["split"] == s) for s in ("dev", "test")} == frozen["split_counts"]
    assert {g: sum(1 for r in rows if r["gold"] == g) for g in ("answer", "new", "unclear")} == frozen["gold_counts"]


def test_the_ids_the_split_and_the_labels_follow_their_rules(pairs):
    _header, rows = pairs
    for row in rows:
        assert row["id"] == "rg-" + hashlib.sha256(f"{row['lang']}|{row['need']}|{row['line']}".encode("utf-8")).hexdigest()[:8]
        assert row["split"] == ("dev" if int(hashlib.sha256(row["line"].encode("utf-8")).hexdigest()[:8], 16) % 100 < 40 else "test")
        assert row["gold"] in ("answer", "new", "unclear") and row["old"] in ("answer", "retry", "new")
        assert row["lang"] in ("pt-BR", "en") and row["need"] in rgb.NEEDS
    assert len({r["id"] for r in rows}) == len(rows)
    assert len({r["line"]: r["split"] for r in rows}) == len({r["line"] for r in rows}), "a line is in one split only"


def test_every_pair_has_a_draft_of_its_need_and_a_question_the_person_could_have_seen(pairs):
    _header, rows = pairs
    questions = set()
    for row in rows:
        made = rgb.make_draft(natural, phrases, row["draft_seed"], row["lang"])
        assert made["need"] == row["need"]
        questions.add(rgb.question_of(natural, phrases, made, row["lang"]))
    assert len(questions) >= 20 and all(q.strip() for q in questions)


def test_the_set_covers_the_kinds_the_families_and_both_languages(pairs):
    _header, rows = pairs
    assert {r["need"] for r in rows} == set(rgb.NEEDS)
    assert {r["lang"] for r in rows} == {"pt-BR", "en"}
    families = {rgb.group_of(r["source"]).split(":", 1)[1] for r in rows if rgb.group_of(r["source"]).startswith("request:")}
    assert families == set(rgb.FAMILIES)
    assert sum(1 for r in rows if r["source"] == "authored:amend") >= 24 and sum(1 for r in rows if r["source"] == "authored:giveup") >= 12


def test_vacuity_a_changed_label_or_line_no_longer_hashes_to_the_frozen_file():
    frozen = json.loads(rgm.SPLIT_FILE.read_text(encoding="utf-8"))["sha256"]
    raw = rgb.LINES.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == frozen
    assert hashlib.sha256(raw.replace(b'"gold": "answer"', b'"gold": "new"', 1)).hexdigest() != frozen
    assert hashlib.sha256(raw + b" ").hexdigest() != frozen


# --- 2. the bars and the agreement -----------------------------------------------------------------------------------------------------------------------

def test_b1_no_answer_the_old_engine_kept_becomes_a_new_request(figures):
    assert figures["b1"]["pairs_at_risk"] > 100, "the bar must have pairs to measure"
    assert figures["b1"]["violations"] == 0, figures["b1"]["ids"]


def test_b2_the_new_requests_taken_as_answers_are_no_more_than_the_old_engines(figures):
    b2 = figures["b2"]
    assert b2["gold_new_pairs"] > 100
    assert b2["passes"], (b2["new_takes_new_as_answer"], b2["old_takes_new_as_answer"], b2["new_listed"])


def test_the_figures_of_the_decision_file_are_the_ones_this_replay_computes(figures):
    assert len(DECISIONS) == 1, "one decision file states the figures"
    block = re.search(r"```json\n(.*?)\n```", DECISIONS[0].read_text(encoding="utf-8"), re.S)
    assert block, "the figures are a json block"
    stated = json.loads(block.group(1))
    assert stated == figures


def test_the_figures_are_internally_consistent(figures):
    agreement = figures["agreement"]
    assert agreement["all"]["n"] == figures["labelled"]["all"] and agreement["test"]["n"] == figures["labelled"]["test"]
    assert sum(agreement["transitions"].values()) == agreement["all"]["n"]
    assert agreement["all"]["same"] == sum(v for k, v in agreement["transitions"].items() if k.split("->")[0] == k.split("->")[1])
    for table in (agreement["by_lang"], agreement["by_need"]):
        assert sum(t["n"] for t in table.values()) == agreement["all"]["n"]
        for t in table.values():
            assert t["wilson95"][0] <= (t["rate"] or 0) <= t["wilson95"][1]
    assert figures["unclear"]["all"] == 53 and figures["labelled"]["all"] + figures["unclear"]["all"] == figures["pairs"]


def test_wilson_band_oracle():
    assert rgm.wilson(0, 0) == [0.0, 1.0]
    low, high = rgm.wilson(50, 100)
    assert (low, high) == (0.404, 0.596)
    low, high = rgm.wilson(100, 100)
    assert high == 1.0 and 0.96 < low < 0.97


def test_vacuity_a_guard_that_drops_every_line_breaks_b1_and_one_that_keeps_every_line_breaks_b2(pairs):
    rows = pairs[1]
    drop_all = rgm.measure(rows, natural, turn_gate, phrases, complete=lambda d, said, now, languages=None: None)
    assert drop_all["b1"]["violations"] > 50
    keep_all = rgm.measure(rows, natural, turn_gate, phrases, complete=lambda d, said, now, languages=None: natural.complete(d, said, now))
    assert keep_all["b1"]["violations"] == 0 and not keep_all["b2"]["passes"]
    assert keep_all["b2"]["new_takes_new_as_answer"] > keep_all["b2"]["old_takes_new_as_answer"]


# --- 3. an oracle per step of the guard, each with a twin ------------------------------------------------------------------------------------------------

STEPS = [
    # (line, verdict, the step that holds it)
    ("me lembra de ligar para o Bruno amanhã às 9h", "reminder", "a: a lead of the reminder words"),  # validate: allow english-only -- Portuguese line, invented
    ("remind me to call Bruno tomorrow at 9am", "reminder", "a: a lead of the reminder words"),
    ("lembrete", "reminder", "a: the lead alone (the kind question exempts it, see below)"),
    ("cria um evento: workshop de design sábado às 10h", "write", "b/c: a new event"),  # validate: allow english-only -- Portuguese line, invented
    ("book the dentist friday at 9am", "write", "b/c: a scheduling verb with a time"),
    ("schedule a meeting with Marta tomorrow at 2pm", "write", "b/c: a scheduling verb with a time"),
    ("meus lembretes", "form", "d: a reminder noun in a short line"),
    ("my reminders", "form", "d: a reminder noun in a short line"),
    ("cancela o lembrete 3", "form", "d: a reminder noun in a short line"),
    ("a reminder", "form", "d: the noun alone"),
    ("aprova 2", "form", "e: a closed form of an operation"),
    ("approve 1", "form", "e: a closed form of an operation"),
    ("para a tarefa 5", "form", "e: a brake"),  # validate: allow english-only -- Portuguese line, invented
    ("mostra minha agenda", "form", "e: a read"),
    ("ligar para a Ana amanhã às 15h", "bare", "f: the bare step (a time and a few words)"),  # validate: allow english-only -- Portuguese line, invented
    ("call Ana tomorrow at 3pm", "bare", "f: the bare step"),
    ("sim mas às 15h", "bare", "f: a yes with an hour reads as the bare step"),  # validate: allow english-only -- Portuguese line, invented
    ("yes but at 3pm", "bare", "f: a yes with an hour reads as the bare step"),
]

ANSWERS = [
    "amanhã às 10h", "9h", "sexta", "22/10", "13.30", "9", "sim", "não", "yes", "no", "outra hora", "another time", "sexta às 14h", "friday at 2pm",   # validate: allow english-only -- Portuguese lines, invented
    "ligar para a Ana", "responde o email da Ana dizendo que aceito", "evento", "event", "na agenda", "meus planos", "desfaz", "undo",   # validate: allow english-only -- Portuguese lines, invented
    "o lembrete que eu pedi ontem para a Ana",   # validate: allow english-only -- Portuguese line, invented
]


@pytest.mark.parametrize("line,verdict,_step", STEPS)
def test_each_step_of_the_guard_names_its_line(line, verdict, _step):
    assert turn_gate.new_request(line) == verdict


@pytest.mark.parametrize("line", ANSWERS)
def test_the_twins_that_lack_the_word_that_matters_are_no_request(line):
    assert turn_gate.new_request(line) is None


def test_a_command_an_empty_line_and_a_non_string_are_no_request():
    assert [turn_gate.new_request(x) for x in ("/pending", "  /remind amanhã 9h", "", "   ", None, 7)] == [None] * 6   # validate: allow english-only -- Portuguese line, invented


def test_the_twin_pairs_differ_only_by_the_trigger():
    assert turn_gate.new_request("meus lembretes") == "form" and turn_gate.new_request("meus planos") is None
    assert turn_gate.new_request("me lembra de ligar para o Bruno") == "reminder" and turn_gate.new_request("ligar para o Bruno") is None   # validate: allow english-only -- Portuguese line, invented
    assert turn_gate.new_request("remind me to call Bruno tomorrow at 9am") == "reminder" and turn_gate.new_request("call Bruno") is None
    assert turn_gate.new_request("approve 1") == "form" and turn_gate.new_request("approve of it") is None
    assert turn_gate.new_request("o lembrete que eu pedi ontem para a Ana") is None, "a noun in a long line (over NOUN_WORDS_MAX words) is no request"   # validate: allow english-only -- Portuguese line, invented
    assert len("o lembrete que eu pedi ontem para a Ana".split()) > turn_gate.NOUN_WORDS_MAX   # validate: allow english-only -- Portuguese line, invented


def test_the_guard_never_executes_a_form():
    before = natural.match("approve 1")
    assert before is not None and before["tier"] == 1 and before["args"] == {"pending_id": 1}
    assert turn_gate.new_request("approve 1") == "form" and natural.match("approve 1") == before


# --- 4. the kind question, the yes with an amendment -----------------------------------------------------------------------------------------------------

def test_the_words_of_the_kind_question_are_answers_to_it_and_new_lines_to_any_other():
    made = complete("kind_bare:0", "lembrete")
    assert made is not None and made["when"] == "2026-10-19 10:00" and made["text"] == "ligar para a Ana"
    assert complete("kind_bare:0", "evento") == {"event": True}
    assert complete("time_day:0", "lembrete") is None                 # the twin: the same word after another question starts a request
    assert complete("kind_bare:0", "reminder", "en")["text"] == "call Ana" and complete("time_day:0", "reminder", "en") is None
    assert complete("weekday_next:0", "lembrete") is None


def test_the_kind_question_still_retries_a_short_reply_that_is_neither():
    got = complete("kind_bare:0", "talvez")
    assert got is not None and got["ask"]["need"] == "kind" and got["ask"]["retries"] == 1


def test_a_short_kind_answer_with_the_noun_is_asked_once_more_not_dropped():
    for line, lang in (("um lembrete mesmo", "pt-BR"), ("só lembrete", "pt-BR"), ("a reminder is fine", "en")):   # validate: allow english-only -- Portuguese lines, invented
        assert turn_gate.new_request(line) == "form"
        got = complete("kind_bare:0", line, lang)
        assert got is not None and got["ask"]["need"] == "kind" and got["ask"]["retries"] == 1, line
        assert complete("time_day:0", line, lang) is None, "the twin: after any other question the same line starts a request"


def test_a_yes_with_an_amendment_changes_the_reading_shown_and_is_not_made_at_once():
    for seed, line, lang, when in (("confirm_plain:0", "sim mas às 15h", "pt-BR", "2026-10-19 15:00"), ("confirm_plain:0", "yes but at 3pm", "en", "2026-10-19 15:00")):   # validate: allow english-only -- Portuguese line, invented
        got = complete(seed, line, lang)
        assert got["ask"]["need"] == "confirm" and got["ask"]["readings"][0]["when"] == when and not got["ask"].get("confirmed"), (line, got)
    assert "when" not in complete("confirm_plain:0", "sim mas às 15h")   # validate: allow english-only -- Portuguese line, invented


def test_an_amendment_that_starts_a_request_of_its_own_is_a_new_line():
    assert complete("confirm_plain:0", "sim mas me lembra de pagar o aluguel amanhã às 9h") is None   # validate: allow english-only -- Portuguese line, invented
    assert complete("confirm_plain:0", "yes but remind me to pay the rent tomorrow at 9am", "en") is None


def test_a_no_with_an_hour_is_a_new_line_as_before_the_guard():
    assert complete("confirm_plain:0", "não, às 16h") is None   # validate: allow english-only -- Portuguese line, invented: the old engine read it as the bare reading and dropped it too (the reply set's old outcome says so)
    old = {r["line"]: r["old"] for r in rgb.read_rows()[1] if r["need"] == "confirm" and r["lang"] == "pt-BR"}
    assert old["não, às 16h"] == "new"   # validate: allow english-only -- Portuguese line, invented


# --- 5. the time answers ---------------------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("seed,line", [("time_day:0", "10h"), ("time_open:0", "amanhã às 10h"), ("time_day:0", "13.30"), ("text_tomorrow:0", "pagar o aluguel"), ("reading_nine:0", "amanhã")])   # validate: allow english-only -- Portuguese lines, invented
def test_the_time_answers_answer_the_question_they_fit(seed, line):
    got = complete(seed, line)
    assert got is not None and ("ask" in got or "when" in got)


def test_a_bare_nine_is_still_asked_as_nine_or_twenty_one():
    got = complete("time_day:0", "9")
    assert got["ask"]["need"] == "reading" and [r["when"] for r in got["ask"]["readings"]] == ["2026-10-19 09:00", "2026-10-19 21:00"]


def test_a_day_answers_the_weekday_and_the_again_questions():
    assert complete("weekday_next:0", "sexta")["ask"]["need"] == "time"   # validate: allow english-only -- Portuguese line, invented
    assert complete("again_after_confirm:0", "sexta")["ask"]["need"] == "time"   # validate: allow english-only -- Portuguese line, invented
    assert complete("time_day:0", "22/10")["ask"]["need"] == "time"


def test_a_request_after_a_question_is_a_new_line_and_a_yes_to_forget_cancels():
    for line in ("meus lembretes", "aprova 2", "me lembra de ligar para o Bruno amanhã às 9h", "marca uma reunião com a Marta amanhã às 14h"):   # validate: allow english-only -- Portuguese lines, invented
        for seed in ("time_day:0", "confirm_plain:0", "text_tomorrow:0", "reading_nine:0", "weekday_next:0", "again_after_confirm:0", "forget_one:0"):
            assert complete(seed, line) is None, (seed, line)
    assert complete("forget_one:0", "sim") == {"forget": [3]}   # validate: allow english-only -- Portuguese line, invented


def test_the_default_verdict_none_counts_a_line_as_an_answer():
    got = natural.complete(draft("time_day:0"), "meus lembretes", NOW)      # the engine alone, with no verdict: a line is no request, and is asked once more or answered
    assert got is None or "ask" in got
    assert natural.short_answer("hmm") and not natural.short_answer("hmm", new="form")
    assert not natural.short_answer("um dois três quatro")   # validate: allow english-only -- Portuguese line, invented


# --- 6. no gate and no model call -----------------------------------------------------------------------------------------------------------------------

def count_gate_calls(monkeypatch, run):
    calls = []
    for name in ("admit", "call", "record", "_call_route"):
        monkeypatch.setattr(turn_gate, name, lambda *a, _n=name, **k: calls.append(_n))
    run()
    return calls


def test_the_guard_makes_no_gate_or_model_call(monkeypatch, pairs):
    lines = sorted({r["line"] for r in pairs[1]})
    assert count_gate_calls(monkeypatch, lambda: [turn_gate.new_request(line) for line in lines]) == []


def test_vacuity_a_guard_that_asks_the_gate_is_counted(monkeypatch):
    assert count_gate_calls(monkeypatch, lambda: turn_gate.admit({}, "sender")) == ["admit"]


FORBIDDEN = re.compile(r"\b(?:admit|call|record|interpreter\w*|requests|urllib|subprocess|open)\(|\bimport (?:interpreter|urllib|requests|subprocess)")


def test_the_source_of_the_guard_reads_no_gate_interpreter_or_configuration():
    assert not FORBIDDEN.search(inspect.getsource(turn_gate.new_request))
    assert not FORBIDDEN.search(inspect.getsource(turn_gate._bare_reminder))
    assert FORBIDDEN.search("def new_request(line):\n    return admit(ctx, sender)\n")      # vacuity: the pattern can fire


# --- 7. every product call passes the verdict -------------------------------------------------------------------------------------------------------------

# A call that passes no verdict, on purpose: the `eventorother` question of the bridge, which only pre-states and stand-ins reach since `reminder-form` carries /remind intents alone (OPEN-CO-5, left for 44-B).
UNGUARDED = {("messaging_remind.py", "short_answer")}


def unguarded_calls(source: str, name: str):
    """The calls of `natural.complete` and `natural.short_answer` in `source` that pass no `new=`: [(file name, method)]."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in ("complete", "short_answer") \
                and isinstance(node.func.value, ast.Name) and node.func.value.id == "natural" and not any(k.arg == "new" for k in node.keywords):
            found.append((name, node.func.attr))
    return found


def test_every_product_call_of_the_engine_passes_the_verdict_or_is_listed():
    found = []
    for path in sorted((REPO / "runtime").glob("*.py")):
        if path.name != "natural.py":
            found += unguarded_calls(path.read_text(encoding="utf-8"), path.name)
    assert set(found) == UNGUARDED, found
    guarded = [p.name for p in sorted((REPO / "runtime").glob("*.py")) if "new=new_request(" in p.read_text(encoding="utf-8") or "new=turn_gate.new_request(" in p.read_text(encoding="utf-8")]
    assert guarded == ["ops_natural_writes.py", "turn_gate.py"]


def test_every_other_product_caller_goes_through_the_one_home():
    homes = {p.name for p in (REPO / "runtime").glob("*.py") if "turn_gate.complete_reminder(" in p.read_text(encoding="utf-8")}
    assert homes == {"ops_natural.py", "ops_natural_writes.py", "ops_reminders.py"}


def test_vacuity_a_planted_call_without_the_verdict_is_found():
    assert unguarded_calls("natural.complete(draft, said, clock)\n", "x.py") == [("x.py", "complete")]
    assert unguarded_calls("natural.short_answer(said, tables)\n", "x.py") == [("x.py", "short_answer")]
    assert unguarded_calls("natural.complete(draft, said, clock, new=verdict)\nnatural.short_answer(said, new=v)\n", "x.py") == []


def test_card_revise_reads_the_guard_and_the_four_lines_of_the_probe_agree_with_the_card_words():
    import card_words
    for line in ("aprova 2", "approve 1", "reject 2", "aprova 9"):   # validate: allow english-only -- Portuguese lines, invented
        assert turn_gate.new_request(line) == "form" and card_words.card_word(line) is not None
    assert turn_gate.new_request("muda para as 10h") == "bare"   # validate: allow english-only -- Portuguese line, invented: the bare reading, as `candidate` named it (the card revise treats it as recognised, unchanged by this package)
