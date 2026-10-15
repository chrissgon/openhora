"""Tests of the program that runs inside the renderer's container (providers/exporter/_render.py, package P8) on the
host, with the adopted tools where this machine has them: the standard library for a CSV file (always), pandoc for a Word document,
openpyxl for a workbook, WeasyPrint for a PDF. A test that needs a tool this machine lacks is skipped and says which; the container
test (test_exporter_docker.py) runs all four in the image. The formula guard (finding S9) has a test for each character it guards, in
a CSV file and in a workbook. Fictional fixtures.

Run: uv run --with pytest==9.1.1 pytest providers/exporter/tests/test_exporter_inner.py
"""
from __future__ import annotations

import csv
import importlib.util
import io
import json
import os
import shutil
import sys
import zipfile
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
INNER = HERE.parent / "_render.py"

# Every character the guard names, with a cell that starts with it: the text a spreadsheet would run.
GUARDED = {"=": "=1+1", "+": "+1+1", "-": "-1+1", "@": "@SUM(A1:A2)", "TAB": "\tcmd", "CR": "\rcmd", "LF": "\ncmd",
           "fullwidth =": "＝1+1", "fullwidth +": "＋1+1", "fullwidth -": "－1+1", "fullwidth @": "＠SUM(A1)"}
SAFE = ["plain", "a=b", "1-2", "x+y", "mail@host.example", " leading space", "", "12", "0.5", "(=1+1)", "'=1+1"]


@pytest.fixture(scope="module")
def inner():
    spec = importlib.util.spec_from_file_location("render_inner_under_test", INNER)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    if shutil.which("pandoc"):      # the program looks for its tools on the container's PATH; here they are where this machine keeps them
        module.ENV["PATH"] = os.path.dirname(shutil.which("pandoc")) + os.pathsep + module.ENV["PATH"]
    return module


needs_pandoc = pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not on this machine")


def table(*cells):
    """A CSV text with a header row and one row holding the cells, quoted so that a tab, a CR or a LF in a cell is part of it."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n", quoting=csv.QUOTE_ALL)
    writer.writerow([f"h{i}" for i in range(len(cells))])
    writer.writerow(cells)
    return buffer.getvalue()


# --- the guard ---------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(GUARDED))
def test_a_cell_that_starts_with_each_guarded_character_is_written_to_a_csv_file_as_text_with_a_quote_in_front(inner, name, tmp_path):
    cell = GUARDED[name]
    assert inner.guarded(cell) is True
    kind, data, counts, tools = inner.render_csv(table("safe", cell), str(tmp_path))
    text = data.decode("utf-8")
    assert text.startswith("\ufeff")
    rows = list(csv.reader(io.StringIO(text.lstrip("\ufeff"), newline="")))
    assert rows[1] == ["safe", "'" + cell], "the cell is the same text with one quote in front of it"
    assert counts == {"rows": 2}


@pytest.mark.parametrize("name", sorted(GUARDED))
def test_the_guard_looks_past_the_spaces_and_invisible_characters_that_come_before_the_character(inner, name):
    for lead in (" ", "   ", " ", "\u200b", "\ufeff", " \u200b "):
        assert inner.guarded(lead + GUARDED[name]) is True, repr(lead)


@pytest.mark.parametrize("cell", SAFE)
def test_a_cell_that_starts_with_none_of_them_is_written_as_it_is(inner, cell, tmp_path):
    assert inner.guarded(cell) is False
    rows = list(csv.reader(io.StringIO(inner.render_csv(table("x", cell), str(tmp_path))[1].decode("utf-8").lstrip("\ufeff"), newline="")))
    assert rows[1] == ["x", cell]


def test_the_header_row_is_guarded_too_and_a_quote_is_not_added_twice_to_a_cell_that_does_not_need_it(inner, tmp_path):
    csv_text = '"=header","-also","fine"\n"1","2","3"\n'
    rows = list(csv.reader(io.StringIO(inner.render_csv(csv_text, str(tmp_path))[1].decode("utf-8").lstrip("\ufeff"))))
    assert rows[0] == ["'=header", "'-also", "fine"] and rows[1] == ["1", "2", "3"]


def test_a_workbook_cell_that_starts_with_each_guarded_character_is_a_text_cell_never_a_formula(inner, tmp_path):
    pytest.importorskip("openpyxl")
    names = sorted(GUARDED)
    text = table(*[GUARDED[n] for n in names] + ["plain", "12", "007", "3.50", "-5"])
    kind, data, counts, tools = inner.render_xlsx(text, str(tmp_path))
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        sheet = z.read("xl/worksheets/sheet1.xml").decode("utf-8")
        styles = z.read("xl/styles.xml").decode("utf-8")
    assert "<f>" not in sheet and "<f " not in sheet, "no cell holds a formula"
    import re
    cells = {m.group(1): (m.group(2), m.group(3)) for m in re.finditer(r'<c r="([A-Z]+2)"([^>]*)>(.*?)</c>', sheet, re.S)}
    for index, name in enumerate(names):
        attrs, inner_xml = cells["ABCDEFGHIJK"[index] + "2"]
        assert 't="inlineStr"' in attrs or 't="s"' in attrs, f"{name} is a text cell: {attrs}"
        assert "<f" not in inner_xml
    assert 'quotePrefix="1"' in styles, "the style that keeps a guarded cell text when the person edits it"
    extra = {"plain": 'L2', "12": "M2", "007": "N2", "3.50": "O2", "-5": "P2"}
    assert 't="n"' in cells["M2"][0] and "<v>12</v>" in cells["M2"][1], "a plain unsigned number is a number"
    assert 't="inlineStr"' in cells["N2"][0] or 't="s"' in cells["N2"][0], "a leading zero is an identifier: text"
    assert 't="n"' in cells["O2"][0] and "<v>3.5</v>" in cells["O2"][1]
    assert 't="inlineStr"' in cells["P2"][0] or 't="s"' in cells["P2"][0], "a signed number is text on purpose: the guard cannot tell -5 from -5+cmd"
    assert extra and tools["openpyxl"]


def test_an_error_code_typed_cell_stays_text_in_a_workbook(inner, tmp_path):
    pytest.importorskip("openpyxl")
    kind, data, _, _ = inner.render_xlsx(table("#REF!", "#N/A"), str(tmp_path))
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        sheet = z.read("xl/worksheets/sheet1.xml").decode("utf-8")
    assert 't="e"' not in sheet


# --- the other limits --------------------------------------------------------------------------------------------------------------


def test_the_delimiter_is_the_commonest_of_four_on_the_first_line_and_a_comma_on_a_tie(inner):
    assert inner.read_rows("a;b;c\n1;2;3\n") == [["a", "b", "c"], ["1", "2", "3"]]
    assert inner.read_rows("a\tb\n1\t2\n") == [["a", "b"], ["1", "2"]]
    assert inner.read_rows("a|b\n1|2\n") == [["a", "b"], ["1", "2"]]
    assert inner.read_rows("a,b;c\n1,2;3\n")[0] == ["a", "b;c"], "a tie goes to the comma"
    assert inner.read_rows('name,note\n"x, y",z\n')[1] == ["x, y", "z"]


def test_a_table_over_a_limit_or_an_empty_one_is_refused_never_cut(inner, monkeypatch):
    monkeypatch.setattr(inner, "ROWS_MAX", 2)
    with pytest.raises(inner.Failed):
        inner.read_rows("a\n1\n2\n")
    monkeypatch.setattr(inner, "COLUMNS_MAX", 2)
    with pytest.raises(inner.Failed):
        inner.read_rows("a,b,c\n")
    monkeypatch.setattr(inner, "CELL_MAX", 3)
    with pytest.raises(inner.Failed):
        inner.read_rows("abcd\n")
    for empty in ("", " \n", ",\n,\n"):
        with pytest.raises(inner.Failed):
            inner.read_rows(empty)


def test_the_render_checks_its_input_format_and_size(inner, tmp_path):
    with pytest.raises(inner.Failed):
        inner.render("odt", b"x", str(tmp_path))
    with pytest.raises(inner.Failed):
        inner.render("csv", b"x" * (inner.CAP_INPUT + 1), str(tmp_path))
    with pytest.raises(inner.Failed):
        inner.render("csv", b"  \n", str(tmp_path))
    with pytest.raises(inner.Failed):
        inner.render("csv", b"\xff\xfe\x00bad", str(tmp_path))
    assert inner.render("csv", b"\xef\xbb\xbfa,b\n1,2\n", str(tmp_path))[0] == "csv", "a byte order mark in the input is dropped"


def test_the_frames_are_the_start_the_files_and_the_end(inner):
    assert inner.frames([("output.csv", b"ab"), ("info.json", b"{}")]) == b"OHF1\nFILE output.csv 2\nabFILE info.json 2\n{}END\n"


def test_main_prints_nothing_on_standard_output_when_it_fails_and_the_frames_when_it_works(inner, tmp_path, capsys):
    source = tmp_path / "in.csv"
    source.write_text("a,b\n=1,2\n", encoding="utf-8")
    assert inner.main(["--format", "csv", "--input", str(source), "--work", str(tmp_path / "w")]) == 0
    raw = capsys.readouterr().out
    assert raw.startswith("OHF1\nFILE output.csv ") and raw.endswith("END\n") and "'=1" in raw
    assert inner.main(["--format", "odt", "--input", str(source), "--work", str(tmp_path / "w")]) == 3
    captured = capsys.readouterr()
    assert captured.out == "" and "not made" in captured.err
    assert inner.main(["--format", "csv", "--input", str(tmp_path / "missing"), "--work", str(tmp_path / "w")]) == 1
    assert capsys.readouterr().out == ""


# --- a document: the cleaning before a writer reads it -----------------------------------------------------------------------------

MARKDOWN = """# Harbour market report

The market opened on **Saturday**.

| fruit | price |
|-------|-------|
| apple | =1+1  |

<script>alert("raw html is dropped")</script>

![the stall](file:///etc/passwd)

[a safe link](https://example.invalid/page) and [a file link](file:///etc/passwd) and [a share](smb://host.example/share) and [a script](javascript:alert(1))
"""


@needs_pandoc
def test_a_picture_becomes_its_text_a_raw_fragment_goes_and_only_safe_links_keep_their_address(inner, tmp_path):
    document = inner.markdown_document(MARKDOWN, str(tmp_path))
    tree = json.loads(Path(document).read_text(encoding="utf-8"))
    dumped = json.dumps(tree)
    assert "file:///" not in dumped and "smb://" not in dumped and "javascript:" not in dumped and "alert" not in dumped
    words = []

    def walk(node):
        if isinstance(node, dict):
            if node.get("t") == "Str":
                words.append(node["c"])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
    walk(tree["blocks"])
    assert "https://example.invalid/page" in dumped and "the stall" in " ".join(words) and "a file link" in " ".join(words)
    assert tree["meta"] == {}


@needs_pandoc
def test_a_metadata_block_is_text_not_a_setting(inner, tmp_path):
    document = inner.markdown_document("---\nreference-doc: /etc/passwd\ntitle: x\n---\n\nBody.\n", str(tmp_path))
    tree = json.loads(Path(document).read_text(encoding="utf-8"))
    assert tree["meta"] == {} and "Body" in json.dumps(tree["blocks"])


@needs_pandoc
def test_a_word_document_holds_the_text_and_neither_a_picture_nor_a_script_nor_a_file_address(inner, tmp_path):
    kind, data, _, tools = inner.render_docx(MARKDOWN, str(tmp_path))
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = z.namelist()
        body = z.read("word/document.xml").decode("utf-8")
        rels = z.read("word/_rels/document.xml.rels").decode("utf-8")
    assert kind == "docx" and "pandoc" in tools["pandoc"].lower()
    assert "Harbour market report" in body and "the stall" in body and "=1+1" in body
    assert not any(n.startswith("word/media") for n in names) and "alert" not in body
    assert "file:///" not in rels + body and "smb://" not in rels and "https://example.invalid/page" in rels


def test_a_pdf_holds_the_text_when_weasyprint_is_here(inner, tmp_path):
    pytest.importorskip("weasyprint")
    pytest.importorskip("pydyf")
    if shutil.which("pandoc") is None:
        pytest.skip("pandoc is not on this machine")
    kind, data, _, tools = inner.render_pdf(MARKDOWN, str(tmp_path))
    assert kind == "pdf" and data.startswith(b"%PDF-") and "weasyprint" in tools
