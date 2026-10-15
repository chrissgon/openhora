"""Tests of the program that runs inside the converter's container (providers/converter/_inner.py), on the host, with the adopted tools
where this machine has them: pandoc for a Word document and an HTML page, poppler's pdftotext for a PDF, openpyxl for a workbook;
CSV and plain text need none. A test that needs a tool this machine lacks is skipped and says which; the container test
(test_converter_docker.py) runs all of them in the image. Fictional fixtures (providers/converter/tests/fixtures).

Run: uv run --with pytest==9.1.1 pytest providers/converter/tests/test_converter_inner.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures"
INNER = HERE.parent / "_inner.py"


def tool_path() -> str:
    """The folders the tools are found in on this machine (the program looks on /usr/local/bin:/usr/bin:/bin in the container)."""
    return os.pathsep.join(sorted({os.path.dirname(p) for p in (shutil.which("pandoc"), shutil.which("pdftotext")) if p}
                                  | {"/usr/local/bin", "/usr/bin", "/bin"}))


@pytest.fixture(scope="module")
def inner():
    os.environ["CONVERTER_TOOL_PATH"] = tool_path()
    spec = importlib.util.spec_from_file_location("converter_inner_under_test", INNER)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    os.environ.pop("CONVERTER_TOOL_PATH", None)


needs_pandoc = pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not on this machine")
needs_pdftotext = pytest.mark.skipif(shutil.which("pdftotext") is None, reason="poppler's pdftotext is not on this machine")


def convert(inner, kind, name, tmp_path):
    return inner.convert(kind, str(FIXTURES / name), str(tmp_path))


def test_a_csv_with_another_delimiter_comes_out_with_commas_and_keeps_its_quoted_cells(inner, tmp_path):
    kind, name, data, tools, notes = convert(inner, "csv", "data.csv", tmp_path)
    assert (kind, name) == ("csv", "converted.csv") and tools == {}
    assert data.decode() == 'name,price,qty\napple,"1,20",10\npear,"3,10",4\n' and "';'" in notes[0]


def test_plain_text_is_kept_as_text_and_a_byte_order_mark_and_nul_characters_go(inner, tmp_path):
    source = tmp_path / "t.txt"
    source.write_bytes(b"\xef\xbb\xbfcaf\xc3\xa9\x00 notes\n")
    kind, name, data, _, _ = inner.convert("text", str(source), str(tmp_path))
    assert (kind, name) == ("text", "converted.md") and data.decode() == "café notes\n"
    legacy = tmp_path / "legacy.txt"
    legacy.write_bytes("café au lait\n".encode("cp1252"))
    assert inner.convert("text", str(legacy), str(tmp_path))[2].decode() == "café au lait\n"


@needs_pandoc
def test_a_word_document_comes_out_as_markdown_with_its_headings_and_lists(inner, tmp_path):
    kind, name, data, tools, _ = convert(inner, "docx", "notes.docx", tmp_path)
    text = data.decode()
    assert (kind, name) == ("docx", "converted.md") and text.startswith("# Interview notes") and "**shorter forms**" in text
    assert "## Prices" in text and "- apple 1.2" in text and "pandoc" in tools["pandoc"].lower()
    assert convert(inner, "ooxml", "notes.docx", tmp_path)[0] == "docx", "an undetermined package is read from its content types"


@needs_pandoc
def test_an_html_page_loses_its_scripts_and_styles_and_keeps_its_text_and_tables(inner, tmp_path):
    kind, name, data, _, notes = convert(inner, "html", "page.html", tmp_path)
    text = data.decode()
    assert (kind, name) == ("html", "converted.md") and "# Fruit market" in text and "Apples sell best in autumn." in text
    assert "| apple | 1.2" in text and "alert" not in text and "hidden script text" not in text and "color" not in text
    assert any("script" in n for n in notes)


@needs_pdftotext
def test_a_pdf_comes_out_page_by_page(inner, tmp_path):
    kind, name, data, tools, notes = convert(inner, "pdf", "brief.pdf", tmp_path)
    text = data.decode()
    assert (kind, name) == ("pdf", "converted.md") and "[page 1]\n\nClinics want shorter forms." in text
    assert "[page 2]\n\nPrices vary by region." in text and "pdftotext" in tools["pdftotext"].lower() and notes == []


def test_a_workbook_with_one_visible_sheet_is_a_csv_and_one_with_several_is_markdown_and_a_hidden_sheet_is_not_read(inner, tmp_path):
    pytest.importorskip("openpyxl")
    kind, name, data, tools, notes = convert(inner, "xlsx", "answers.xlsx", tmp_path)
    assert (kind, name) == ("xlsx", "converted.csv") and data.decode() == "clinic,forms per day\nNorth clinic,12\nSouth clinic,30\n"
    assert "openpyxl" in tools
    kind, name, data, _, notes = convert(inner, "xlsx", "survey.xlsx", tmp_path)
    text = data.decode()
    assert name == "converted.md" and "## Sheet: Prices" in text and "## Sheet: Costs" in text and "```csv" in text
    assert "hidden sheet text" not in text and "Internal" not in text
    assert any("hidden sheet 'Internal'" in n for n in notes)
    assert "apple,1.2,10" in text and "apple,0.5" in text


def test_a_package_that_declares_too_much_or_too_many_entries_is_refused_before_any_tool_reads_it(inner, tmp_path, monkeypatch):
    path = tmp_path / "bomb.docx"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", "a" * 200000)
    monkeypatch.setattr(inner, "ZIP_BYTES_MAX", 1000)
    with pytest.raises(inner.Failed) as refused:
        inner.check_package(str(path))
    assert "too much" in str(refused.value)
    monkeypatch.setattr(inner, "ZIP_BYTES_MAX", 10 ** 9)
    monkeypatch.setattr(inner, "ZIP_ENTRIES_MAX", 1)
    with pytest.raises(inner.Failed):
        inner.check_package(str(path))
    plain = tmp_path / "plain.docx"
    plain.write_bytes(b"not a zip at all")
    with pytest.raises(inner.Failed):
        inner.check_package(str(plain))
    other = tmp_path / "other.zip"
    with zipfile.ZipFile(other, "w") as z:
        z.writestr("readme.txt", "x")
    with pytest.raises(inner.Failed):
        inner.ooxml_kind(str(other))


def test_the_text_is_cut_one_byte_over_the_cap_so_the_host_can_refuse_it(inner, tmp_path):
    source = tmp_path / "big.txt"
    source.write_bytes(b"word " * (inner.CAP // 5 + 1000))
    kind, name, data, _, notes = inner.convert("text", str(source), str(tmp_path))
    assert len(data) == inner.CAP + 1 and "the text was cut at the cap" in notes


def test_a_tool_that_is_missing_or_fails_is_a_failure_with_a_reason_and_nothing_is_printed(inner, tmp_path, capsys):
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"%PDF-1.4\nnot a real pdf")
    code = inner.main(["--type", "pdf", "--input", str(broken), "--work", str(tmp_path / "w")])
    captured = capsys.readouterr()
    assert code != 0 and captured.out == "" and captured.err.startswith("error:")
    code = inner.main(["--type", "exe", "--input", str(broken), "--work", str(tmp_path / "w")])
    assert code == 3 and capsys.readouterr().out == ""


def test_the_program_prints_frames_and_nothing_else_on_standard_output(inner, tmp_path):
    done = subprocess.run([sys.executable, "-I", str(INNER), "--type", "csv", "--input", str(FIXTURES / "data.csv"), "--work", str(tmp_path / "w")],
                          capture_output=True, timeout=60, env={"PATH": os.environ.get("PATH", ""), "CONVERTER_TOOL_PATH": tool_path()})
    assert done.returncode == 0 and done.stdout.startswith(b"OHF1\nFILE converted.csv ") and done.stdout.endswith(b"END\n")
    container = importlib.util.spec_from_file_location("converter_container_for_inner_test", HERE.parent / "container.py")
    sys.path.insert(0, str(HERE.parents[1]))
    module = importlib.util.module_from_spec(container)
    sys.modules[container.name] = module
    container.loader.exec_module(module)
    parsed = module.parse_frames(done.stdout)
    assert set(parsed) == {"converted.csv", "info.json"} and json.loads(parsed["info.json"])["kind"] == "csv"
