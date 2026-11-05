"""The name a line gives a file, and the retry with the name alone (runtime/ops_file_read.py `_search`, `_bare_name`; spec P6 as the supervisor amended it, row 28b).

The interpreter gives the file as a span of the line, and a span may carry words that are not part of the name: the noun for the object ("planilha", "o arquivo") before it and the
service phrase ("do drive", "no onedrive") after it. The search needs every word of the span in the file's name, so those words found nothing. The span is searched as it is first (a real
name that starts with "Planilha" is found by its full name); only when that finds nothing that fits, `_search` tries `_bare_name` of the span on the walk it already made (the leading files noun and
the trailing service phrase of the language tables cut, inner words never), the service phrase naming the account when it names one. Every name is invented; no provider, no model, no network.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_file_read_target.py
"""
from __future__ import annotations

import pytest

import phrase_kit as pk
import standin_tree as st
from test_file_read import NONE_FOLDERS, PT, READER_KEY, drives, item, one_line, op, phone  # noqa: F401  (the two drives, the senders and the stand-in model)
from test_ops_natural import world  # noqa: F401  (the real-operations world fixture)

ops_file_read = st.load("ops_file_read")
CFG = {"language": "pt-BR"}


@pytest.mark.parametrize("span, name", [
    ("planilha orcamento-teste do drive", "orcamento-teste"),
    ("a planilha orcamento-teste", "orcamento-teste"),
    ("o arquivo contrato.pdf do onedrive", "contrato.pdf"),
    ("o documento Contrato de locação no google drive", "Contrato de locação"),      # validate: allow english-only -- the Portuguese line under test
    ("arquivo contrato.pdf do meu google drive", "contrato.pdf"),
    ("the spreadsheet budget-test on my drive", "budget-test"),
    ("the file contract.pdf on onedrive", "contract.pdf"),
])
def test_the_object_noun_and_the_service_phrase_are_cut_from_the_name(span, name):
    assert ops_file_read._bare_name(span) == name


@pytest.mark.parametrize("span", ["Notas de teste", "orcamento-teste", "Atividades da semana", "contrato.pdf", "Planilha", "arquivo", "o arquivo", "do drive", "Lista do drive de ideias"])
def test_inner_words_and_a_span_that_would_be_left_empty_are_kept_whole(span):
    assert ops_file_read._bare_name(span) == span


def test_line_target_keeps_the_span_the_check_verified():
    span = "planilha orcamento-teste do drive"
    assert ops_file_read.line_target(CFG, {"file": span}, f"abre a {span}?")[0] == span


def spy(monkeypatch):
    seen = []
    real = ops_file_read._search
    monkeypatch.setattr(ops_file_read, "_search", lambda cfg, wanted, account=None, said=None: (seen.append((wanted, account)), real(cfg, wanted, account, said))[1])
    return seen


def add(drives, service, folder, ident, name, text):
    drives["drives"].folders[(service, folder)].append(item(ident, name))
    drives["drives"].files[(service, ident)] = text.encode("utf-8")


def test_a_span_with_the_noun_and_the_drive_word_finds_the_file_by_the_name_alone(drives, monkeypatch):
    seen = spy(monkeypatch)
    add(drives, "microsoft", "/Documentos", "drv1/it!30", "orcamento-teste.txt", "Total: 4200 reais")
    span = "planilha orcamento-teste do drive"
    drives["answer"]["text"] = op("file-read", {"file": span})
    assert "Total: 4200 reais" in phone(drives, f"quanto deu o total na {span}?")
    assert seen == [(span, None)], "one search, one walk: the name alone is tried on the same tree"


def test_the_cut_service_phrase_narrows_the_retry_to_its_account(drives):
    for service, folder, ident in (("microsoft", "/Documentos", "drv1/it!31"), ("google", "GDRIVEFOLDER0001", "gfile0000000031")):
        add(drives, service, folder, ident, "contrato.pdf", f"Clausula do {service}.")
    span = "o arquivo contrato.pdf do onedrive"
    drives["answer"]["text"] = op("file-read", {"file": span})
    reply = phone(drives, f"abre {span}")
    assert "Clausula do microsoft." in reply and "google" not in reply, "the file of OneDrive only: the phrase names the account"
    drives["answer"]["text"] = op("file-read", {"file": "o arquivo contrato.pdf do drive"})
    pick = phone(drives, "abre o arquivo contrato.pdf do drive")
    pk.assert_said(pick.split("\n")[0], "FR_SEVERAL_PICK", PT, count=2)      # "drive" alone names no account: both files are listed


def test_a_real_name_that_starts_with_the_noun_is_found_by_the_full_span_first(drives, monkeypatch):
    add(drives, "microsoft", "/Documentos", "drv1/it!32", "Planilha de custos da obra.txt", "Cimento: 12 sacos")
    add(drives, "microsoft", "/Documentos", "drv1/it!33", "custos da obra.txt", "Outro arquivo")
    span = "Planilha de custos da obra"
    drives["answer"]["text"] = op("file-read", {"file": span})
    reply = phone(drives, f"abre o arquivo {span}")
    assert "Cimento: 12 sacos" in reply and "Outro arquivo" not in reply, "the full name wins; the name alone is only the retry"


def test_nothing_found_in_either_try_says_what_the_first_search_said(drives):
    span = "planilha inexistente-teste do drive"
    drives["answer"]["text"] = op("file-read", {"file": span})
    one_line(phone(drives, f"abre a {span}"), "FR_NONE_SUB", folders=NONE_FOLDERS)
