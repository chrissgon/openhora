"""A file named inside a long line is searched by its span, never by the whole line (B''-lite, step 4: no catalog change; runtime/ops_file_read.py `line_target`, `_search`).

`file-read`, `file-trash` and `file-replace` take the file as a span of the line (the slot `file`), checked to be a piece of it, and search the person's folders with that span. The
line itself goes to `_search` only so that a folder named in it narrows the search. Held here over the stand-in drives of test_file_read.py: a long line with the name in the middle
of it searches with exactly the span, and a planted `line_target` that hands the whole line over is seen by the same oracle. Every name is invented. Offline.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_blite_files_span.py
"""
from __future__ import annotations

import pytest

import standin_tree as st
from test_file_read import READER_KEY, drives, op, phone  # noqa: F401  (the two drives, the senders and the stand-in model)
from test_ops_natural import world  # noqa: F401  (the real-operations world fixture)

ops_file_read = st.load("ops_file_read")

SPAN = "Planilha de custos da obra Ipê Amarelo"      # validate: allow english-only -- the Portuguese line under test
LINE = f"abre pra mim o arquivo {SPAN}, aquele que a Beatriz comentou ontem na reunião do condomínio"      # validate: allow english-only -- the Portuguese line under test


def spy_on_search(monkeypatch):
    seen = []
    real = ops_file_read._search

    def search(cfg, wanted, account=None, said=None):
        seen.append({"wanted": wanted, "account": account, "said": said})
        return real(cfg, wanted, account, said)

    monkeypatch.setattr(ops_file_read, "_search", search)
    return seen


def test_a_long_line_searches_with_the_span_the_check_verified_and_the_line_only_for_a_folder(drives, monkeypatch):
    seen = spy_on_search(monkeypatch)
    drives["answer"]["text"] = op("file-read", {"file": SPAN})
    phone(drives, LINE)
    assert [s["wanted"] for s in seen] == [SPAN], "the search words are the span, exactly"
    assert [s["said"] for s in seen] == [LINE], "the line is given only so that a folder named in it can narrow the search"
    assert LINE != SPAN


def test_a_span_that_is_not_in_the_line_is_asked_again_and_nothing_is_searched(drives, monkeypatch):
    seen = spy_on_search(monkeypatch)
    drives["answer"]["text"] = op("file-read", {"file": "Planilha de custos da obra Ipê Roxo"})      # validate: allow english-only -- the Portuguese line under test
    phone(drives, LINE)
    assert seen == [] and drives["drives"].calls == []


def test_vacuity_a_line_target_that_hands_the_whole_line_over_is_seen_by_the_oracle(drives, monkeypatch):
    seen = spy_on_search(monkeypatch)
    real = ops_file_read.line_target
    monkeypatch.setattr(ops_file_read, "line_target", lambda cfg, args, said: (said, real(cfg, args, said)[1], None))      # the planted fault: the line, not the span
    drives["answer"]["text"] = op("file-read", {"file": SPAN})
    phone(drives, LINE)
    assert [s["wanted"] for s in seen] == [LINE] != [SPAN], "vacuity: with the plant the search words are the whole line, and the oracle above fails"
