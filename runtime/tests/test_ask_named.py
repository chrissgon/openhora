"""A file named in the person's own words reaches `ask` (package NR-2, runtime/source_resolve.py through runtime/ops_ask.py): one strong match is used and the
reply says "I used: <name>", several or weak ones are listed and the question waits for the choice (a draft of the conversation), a line that names a kind of
document no source matches says so, `@<id>` always wins, and a line that names no file is selected as it always was. Code only: no model chooses. The stand-in
tree and answer skill of runtime/tests/standin_tree.py; every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_ask_named.py
"""
from __future__ import annotations

import pytest

import standin_tree as st
from test_ask import accept, add_source, ask, run_files, runs, tree, two, write_config  # noqa: F401
from test_ask_snapshots import AGENDA, INBOX, snapshot

ops = st.load("ops")
ops_natural = st.load("ops_natural")
drafts = st.load("drafts")
phrases = st.load("phrases")

CV = "# Curriculo\n\nAna Lima. Skills: Vue, TypeScript, prazo de entrega curto.\n"
REPORT_A = "# Report 2025\n\nSales grew. The prazo was met.\n"
REPORT_B = "# Report 2026\n\nSales fell. The prazo slipped.\n"


@pytest.fixture
def cv(two):
    add_source(two, "cv-2026", CV, name="curriculo-ana.txt")
    ops_natural.forget_all()
    return two


def read(out) -> list:
    return sorted(s["source"] for s in out["sources"])


def test_one_strong_match_is_the_only_source_read_and_the_reply_says_which_file_was_used(cv):
    out = ask(cv, "o que diz meu CV sobre Vue?")
    assert out["ran"] is True and read(out) == ["cv-2026"]
    assert out["reply"].endswith("I used: curriculo-ana.txt."), out["reply"]
    assert sorted(f for f in run_files(cv, out) if f.endswith("converted.md")) == ["./.workbench-local/sources/cv-2026/converted.md"]


@pytest.mark.parametrize("line", ["what does my resume say about Vue?", "o que diz o meu currículo?", "O QUE DIZ O MEU CURRICULO", "what does cv-2026 say about Vue?"])
def test_accents_case_the_alias_and_the_id_are_the_same_file(cv, line):
    out = ask(cv, line)
    assert read(out) == ["cv-2026"] and "I used: curriculo-ana.txt." in out["reply"], line


def test_an_at_mention_wins_and_says_nothing_of_a_choice(cv):
    out = ask(cv, "o que diz meu CV @lease-contract?")
    assert read(out) == ["lease-contract"] and "I used" not in out["reply"]


def test_a_line_that_names_no_file_is_selected_as_it_always_was(cv):
    out = ask(cv, "qual o prazo do contrato?")
    assert read(out) == ["cv-2026", "lease-contract", "meeting-notes"] and "I used" not in out["reply"]


def test_two_strong_matches_are_listed_and_nothing_runs_until_the_person_chooses(two):
    add_source(two, "report-2025", REPORT_A, name="report 2025.txt")
    add_source(two, "report-2026", REPORT_B, name="report 2026.txt")
    before = len(runs(two))
    out = ask(two, "what does the report say about the prazo?")
    assert out["ran"] is False and out["refusal"] == "which-source" and out["candidates"] == ["report-2026", "report-2025"] or out["candidates"] == ["report-2025", "report-2026"]
    assert out["reply"].startswith("Which file do you mean? Answer with its number.\n1. @report-")
    assert "(file, " in out["reply"] and len(runs(two)) == before and st.calls(two["adapter"]) == []


def test_a_description_names_a_file_for_a_line_that_says_it_is_one(two):
    add_source(two, "scan0042", "# Scan\n\nInvoice of the dentist: 120 reais. The prazo is Friday.\n", name="scan0042.txt")
    ops.source_describe(two["path"], "scan0042", "invoice from the dentist, october")
    out = ask(two, "how much was the dentist invoice in that document?")
    assert read(out) == ["scan0042"] and "I used: scan0042.txt." in out["reply"]
    weak = ask(two, "how much did the dentist cost me in that file?")
    assert weak["refusal"] == "which-source" and weak["candidates"] == ["scan0042"]


def test_a_kind_of_document_no_source_matches_says_so_and_runs_nothing(two):
    out = ask(two, "o que diz o meu passaporte?")
    assert out["ran"] is False and out["refusal"] == "no-source"
    assert out["reply"] == "No source of this project matches that. Searching your accounts is planned, not built yet."
    assert st.calls(two["adapter"]) == []
    accept(two["path"], language="pt-BR")
    assert "planejada" in ask(two, "o que diz o meu passaporte?")["reply"]


def test_a_mail_or_calendar_source_is_never_matched_by_words_for_a_sender_without_the_group(two):
    snapshot(two, "inbox", "mail", INBOX, "gmail:box=inbox;days=7;max=50")
    snapshot(two, "agenda", "calendar", AGENDA, "google:calendar=primary;past=0;ahead=14")
    out = ask(two, "what is new in the inbox?")
    assert read(out) == ["lease-contract", "meeting-notes"] and "I used" not in out["reply"], "the RT-1 rule: only by @id"
    named = ask(two, "what is new in @inbox?")
    assert read(named) == ["inbox"]


def test_a_choice_among_listed_files_asks_the_question_again_about_the_one_chosen(two):
    add_source(two, "report-2025", REPORT_A, name="report 2025.txt")
    add_source(two, "report-2026", REPORT_B, name="report 2026.txt")
    ops_natural.forget_all()
    first = ops.say(two["path"], "/ask what does the report say about the prazo?", channel="page")
    assert first["reply"].startswith("Which file do you mean?") and first["ran"] is False and drafts.count() == 1
    before = len(runs(two))
    chosen = ops.say(two["path"], "2", channel="page")
    assert len(runs(two)) == before + 1 and "Which file" not in chosen["reply"] and drafts.count() == 0
    last = [m for m in ops.conversation(two["path"], channel="page")["messages"] if m["role"] == "assistant"][-1]
    assert last["run_id"] and last["task_id"] is None, "stored with its answer run: only the page that asked reads it back"
    again = ops.say(two["path"], "/ask what does the report say about the prazo?", channel="page")
    assert again["reply"].startswith("Which file") and drafts.count() == 1
    outside = ops.say(two["path"], "report-2025", channel="page")      # the id of a listed file is a choice too
    assert len(runs(two)) == before + 2 and drafts.count() == 0 and outside["reply"]
