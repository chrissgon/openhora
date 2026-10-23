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


# --- presentations: python-pptx, local files only ----------------------------------------------------------------------------------


needs_pptx = pytest.mark.skipif(importlib.util.find_spec("pptx") is None,
                                reason="python-pptx is not on this machine (it is in the image, from the lock)")


@needs_pptx
def test_a_presentation_comes_out_as_markdown_with_a_section_per_slide_its_table_and_its_notes(inner, tmp_path):
    kind, name, data, tools, notes = convert(inner, "pptx", "review.pptx", tmp_path)
    text = data.decode()
    assert (kind, name) == ("pptx", "converted.md") and tools["python-pptx"] and notes == []
    assert [line for line in text.splitlines() if line.startswith("# ")] == ["# Harbor Cafe Quarterly Review", "# Highlights", "# Sites"]
    assert text.count("Harbor Cafe Quarterly Review") == 1, "the title is the heading and is not written again as text"
    assert "Fictional deck for the converter's tests" in text
    assert "- Opening day sales beat the forecast\n- Staff turnover fell to 8 percent\n- Supplier costs stayed flat" in text
    assert "| Site | Revenue | Visits |\n| --- | --- | --- |\n| Dock Street | 48200 | 9100 |\n| Mill Lane | 39750 | 7400 |" in text
    assert "### Notes\n\nSpeaker note: thank the Dock Street team." in text
    assert text.index("# Highlights") < text.index("### Notes") < text.index("# Sites"), "the notes stay with their slide"
    assert convert(inner, "ooxml", "review.pptx", tmp_path)[0] == "pptx", "an undetermined package is read from its content types"


@needs_pptx
def test_text_boxes_levels_a_pipe_in_a_cell_an_untitled_slide_and_a_hidden_slide(inner, tmp_path):
    kind, name, data, tools, notes = convert(inner, "pptx", "rich.pptx", tmp_path)
    text = data.decode()
    assert "- Unlock the doors\n  - Disarm the alarm\n- Count the cash float" in text, "a level is an indent"
    assert "Call the manager if the float is short" in text, "a text box that is no placeholder is read"
    assert "| Quay Beans | net 30 \\| invoice by mail |" in text, "a pipe in a cell is escaped"
    assert "# Slide 4\n\nA slide with no title" in text, "a slide with no title is headed by its number"
    assert "Draft pricing" not in text and notes == ["the hidden slide 3 was not read"]


def test_only_python_pptx_reads_a_presentation_and_the_process_cannot_open_a_connection_while_it_does(inner, monkeypatch):
    """Nothing in the program imports a converter library but the one for the format, and a presentation is read with the socket guard on."""
    import socket
    for attribute in ("connect", "connect_ex"):
        monkeypatch.setattr(socket.socket, attribute, getattr(socket.socket, attribute))
    monkeypatch.setattr(socket, "create_connection", socket.create_connection)
    monkeypatch.setattr(socket, "getaddrinfo", socket.getaddrinfo)
    source = INNER.read_text()
    assert "markitdown" not in source.lower()
    with pytest.raises(inner.Failed):
        inner.convert_pptx(str(FIXTURES / "notes.docx"), str(FIXTURES))     # a package that is not a presentation
    for attempt in (lambda: socket.create_connection(("127.0.0.1", 9), 1), lambda: socket.getaddrinfo("cafe.example", 80),
                    lambda: socket.socket().connect(("127.0.0.1", 9))):
        with pytest.raises(OSError) as refused:
            attempt()
        assert "no network connection" in str(refused.value), "the guard was switched on by the conversion"


@pytest.mark.parametrize("address", ["https://cafe.example/menu.pptx", "http://127.0.0.1:8080/x", "file:///etc/passwd",
                                     "data:text/plain;base64,aGk=", "ftp://cafe.example/a.pptx", "relative/path.pptx"])
def test_an_input_that_is_an_address_or_not_an_absolute_path_is_refused_before_anything_is_read_or_fetched(inner, tmp_path, capsys, address):
    code = inner.main(["--type", "pptx", "--input", address, "--work", str(tmp_path / "w")])
    captured = capsys.readouterr()
    assert code == 3 and captured.out == "" and "never an address" in captured.err


@needs_pptx
def test_a_broken_presentation_is_a_conversion_error_with_a_closed_message_and_nothing_on_standard_output(inner, tmp_path, capsys):
    broken = tmp_path / "broken.pptx"
    with zipfile.ZipFile(broken, "w") as z:
        z.writestr("[Content_Types].xml", "<Types xmlns='http://schemas.openxmlformats.org/package/2006/content-types'/>")
        z.writestr("ppt/presentation.xml", "<p:presentation/>")
    code = inner.main(["--type", "pptx", "--input", str(broken), "--work", str(tmp_path / "w")])
    captured = capsys.readouterr()
    assert code == 3 and captured.out == "" and captured.err.startswith("error: python-pptx could not convert the pptx file: ")
    assert str(tmp_path) not in captured.err, "no path of the machine in the message"
    fake = tmp_path / "fake.pptx"
    fake.write_bytes(b"not a package")
    assert inner.main(["--type", "pptx", "--input", str(fake), "--work", str(tmp_path / "w")]) == 3


# --- the kind of an Office package, the size caps of a presentation, the spreadsheet's link ------------------------------------------


@pytest.fixture
def sockets_restored(monkeypatch):
    """convert_pptx switches the socket guard on for the process; the monkeypatch puts the real functions back after the test."""
    import socket
    for attribute in ("connect", "connect_ex"):
        monkeypatch.setattr(socket.socket, attribute, getattr(socket.socket, attribute))
    monkeypatch.setattr(socket, "create_connection", socket.create_connection)
    monkeypatch.setattr(socket, "getaddrinfo", socket.getaddrinfo)


def package(path, names, types=""):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", f"<Types xmlns='http://schemas.openxmlformats.org/package/2006/content-types'>{types}</Types>")
        for name in names:
            z.writestr(name, "<x/>")
    return str(path)


def test_the_main_part_decides_the_kind_of_a_package_not_a_type_string_so_a_deck_with_a_chart_is_not_a_workbook(inner, tmp_path):
    sheet = ("<Override PartName='/ppt/embeddings/Microsoft_Excel_Sheet1.xlsx' "
             "ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'/>"
             "<Override PartName='/word/document.xml' ContentType='application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml'/>")
    deck = package(tmp_path / "deck.pptx", ["ppt/presentation.xml", "ppt/slides/slide1.xml", "ppt/embeddings/Microsoft_Excel_Sheet1.xlsx"], sheet)
    assert inner.ooxml_kind(deck) == "pptx"
    document = package(tmp_path / "doc.docx", ["word/document.xml", "word/embeddings/Microsoft_Excel_Sheet1.xlsx"], sheet)
    assert inner.ooxml_kind(document) == "docx"
    book = package(tmp_path / "book.xlsx", ["xl/workbook.xml", "xl/worksheets/sheet1.xml"], sheet)
    assert inner.ooxml_kind(book) == "xlsx"
    with pytest.raises(inner.Failed):
        inner.ooxml_kind(package(tmp_path / "other.zip", ["docProps/app.xml"], sheet))
    no_types = tmp_path / "no-types.pptx"
    with zipfile.ZipFile(no_types, "w") as z:
        z.writestr("ppt/presentation.xml", "<x/>")
    with pytest.raises(inner.Failed):
        inner.ooxml_kind(str(no_types))


def test_a_presentation_has_lower_caps_so_a_huge_deck_is_a_named_error_before_the_library_reads_it(inner, tmp_path, sockets_restored, monkeypatch):
    big = tmp_path / "big.pptx"
    with zipfile.ZipFile(big, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("ppt/slides/slide1.xml", "a" * 300000)
        z.writestr("ppt/media/image1.png", "b" * 300000)
    assert inner.PPTX_BYTES_MAX < inner.ZIP_BYTES_MAX and inner.PPTX_XML_MAX < inner.PPTX_BYTES_MAX
    monkeypatch.setattr(inner, "PPTX_XML_MAX", 100000)
    with pytest.raises(inner.Failed) as refused:
        inner.convert_pptx(str(big), str(tmp_path))
    assert "too much XML" in str(refused.value)
    monkeypatch.setattr(inner, "PPTX_XML_MAX", 10 ** 9)
    monkeypatch.setattr(inner, "PPTX_BYTES_MAX", 500000)
    with pytest.raises(inner.Failed) as refused:
        inner.convert_pptx(str(big), str(tmp_path))
    assert "too much data" in str(refused.value)
    assert inner.check_package(str(big), 10 ** 9, 10 ** 9)[0] == "[Content_Types].xml", "the media are not counted as XML"
    # a part saved under another name is counted: an Override can type a .bin as XML
    disguised = tmp_path / "disguised.pptx"
    with zipfile.ZipFile(disguised, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("ppt/slides/slide2.bin", "a" * 300000)
        z.writestr("ppt/media/photo.JPG", "b" * 300000)
    with pytest.raises(inner.Failed) as refused:
        inner.check_package(str(disguised), 10 ** 9, 100000)
    assert "too much XML" in str(refused.value)
    assert inner.check_package(str(disguised), 10 ** 9, 400000)


def test_two_spreadsheets_converted_with_one_work_folder_each_give_their_own_content(inner, tmp_path):
    pytest.importorskip("openpyxl")
    first = inner.convert("xlsx", str(FIXTURES / "answers.xlsx"), str(tmp_path))
    second = inner.convert("xlsx", str(FIXTURES / "survey.xlsx"), str(tmp_path))
    assert first[2].decode().startswith("clinic,forms per day") and b"## Sheet: Prices" in second[2]
    third = inner.convert("xlsx", str(FIXTURES / "review.xlsx"), str(tmp_path))
    assert b"Dock Street" in third[2], "a link left by an earlier conversion is never reused"


# --- macro-enabled packages are refused for every source (the content decides, never the name) -----------------------------------------

MAIN_PARTS = {"docx": "word/document.xml", "xlsx": "xl/workbook.xml", "pptx": "ppt/presentation.xml"}
MACRO_MAIN_TYPES = {
    "docm": "application/vnd.ms-word.document.macroEnabled.main+xml",
    "dotm": "application/vnd.ms-word.template.macroEnabledTemplate.main+xml",
    "xlsm": "application/vnd.ms-excel.sheet.macroEnabled.main+xml",
    "xltm": "application/vnd.ms-excel.template.macroEnabled.main+xml",
    "xlam": "application/vnd.ms-excel.addin.macroEnabled.main+xml",
    "pptm": "application/vnd.ms-powerpoint.presentation.macroEnabled.main+xml",
    "potm": "application/vnd.ms-powerpoint.template.macroEnabled.main+xml",
    "ppsm": "application/vnd.ms-powerpoint.slideshow.macroEnabled.main+xml",
    "sldm": "application/vnd.ms-powerpoint.slide.macroEnabled.main+xml",
}
KIND_OF = {"d": "docx", "x": "xlsx", "p": "pptx", "s": "pptx"}


def macro_package(path, kind, *, content_type=None, extra_parts=(), quote='"'):
    """A crafted package (fictional, empty parts): the main part of `kind`, and optionally a main content type and more parts."""
    types = ""
    if content_type:
        types = f"<Override PartName={quote}/{MAIN_PARTS[kind]}{quote} ContentType={quote}{content_type}{quote}/>"
    return package(path, [MAIN_PARTS[kind], *extra_parts], types)


@pytest.mark.parametrize("extension", sorted(MACRO_MAIN_TYPES))
def test_every_macro_enabled_main_content_type_is_refused_whatever_the_file_is_called(inner, tmp_path, extension):
    kind = KIND_OF[extension[0]]
    for name in (f"report.{extension}", "report.docx", "input"):       # the input is /in/input in the container: its name says nothing
        path = macro_package(tmp_path / name, kind, content_type=MACRO_MAIN_TYPES[extension])
        for declared in (kind, "ooxml"):
            with pytest.raises(inner.Failed) as refused:
                inner.convert(declared, path, str(tmp_path / "work"))
            assert str(refused.value) == inner.MACRO_REFUSAL


def test_a_vba_project_part_is_refused_by_its_name_at_any_depth_and_in_any_case_even_in_a_package_typed_as_plain(inner, tmp_path):
    plain_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
    for kind in ("docx", "xlsx", "pptx"):
        for part in ("word/vbaProject.bin", "xl/vbaProject.bin", "ppt/vbaProject.bin", "x/y/VBAPROJECT.BIN", "word/vbaProjectSignature.bin",
                     "word/vbaData.xml"):
            # the plain main type: a sender who relabels a .docm as a .docx still carries the project
            path = macro_package(tmp_path / f"{kind}-{part.replace('/', '_')}", kind, content_type=plain_type, extra_parts=[part])
            with pytest.raises(inner.Failed) as refused:
                inner.convert(kind, path, str(tmp_path / "work"))
            assert str(refused.value) == inner.MACRO_REFUSAL


def test_a_macro_sheet_or_a_vba_content_type_is_refused_even_without_a_project_part(inner, tmp_path):
    sheet = macro_package(tmp_path / "xlm.xlsx", "xlsx", extra_parts=["xl/macrosheets/sheet1.xml"])
    unrelated = macro_package(tmp_path / "unrelated.xlsx", "xlsx", extra_parts=["xl/sheetdata.bin"])
    for refused_path in (sheet,):
        with pytest.raises(inner.Failed) as refused:
            inner.refuse_macros(refused_path)
        assert str(refused.value) == inner.MACRO_REFUSAL
    for case, content_type in (("vba", "application/vnd.ms-office.vbaProject"), ("sig", "application/vnd.ms-office.vbaProjectSignature"),
                               ("sheet", "application/vnd.ms-excel.macrosheet+xml"), ("data", "application/vnd.ms-word.vbaData+xml")):
        pkg = package(tmp_path / f"{case}.xlsx", [MAIN_PARTS["xlsx"], "xl/blob.bin"], f"<Default Extension='bin' ContentType='{content_type}'/>")
        with pytest.raises(inner.Failed) as refused:
            inner.convert("xlsx", pkg, str(tmp_path / "work"))
        assert str(refused.value) == inner.MACRO_REFUSAL
    inner.refuse_macros(unrelated)     # an unrelated part is not a macro


def test_the_content_type_is_found_with_either_quote_and_in_any_case(inner, tmp_path):
    for quote in ('"', "'"):
        path = macro_package(tmp_path / f"q{ord(quote)}.docx", "docx", content_type=MACRO_MAIN_TYPES["docm"].upper(), quote=quote)
        with pytest.raises(inner.Failed):
            inner.refuse_macros(path)


def test_a_real_word_document_with_a_project_injected_is_refused_and_the_committed_fixtures_hold_no_macro(inner, tmp_path):
    clean = FIXTURES / "review.docx"
    for name in ("review.docx", "review.xlsx", "review.pptx", "notes.docx", "rich.docx", "rich.pptx", "survey.xlsx", "answers.xlsx"):
        inner.refuse_macros(str(FIXTURES / name))
    injected = tmp_path / "injected.docx"
    with zipfile.ZipFile(clean) as source, zipfile.ZipFile(injected, "w", zipfile.ZIP_DEFLATED) as target:
        for info in source.infolist():
            data = source.read(info.filename)
            if info.filename == "[Content_Types].xml":
                data = data.replace(b"</Types>", b"<Default Extension=\"bin\" ContentType=\"application/vnd.ms-office.vbaProject\"/></Types>")
            target.writestr(info.filename, data)
        target.writestr("word/vbaProject.bin", b"fictional bytes, never read")
    with pytest.raises(inner.Failed) as refused:
        inner.convert("docx", str(injected), str(tmp_path / "work"))
    assert str(refused.value) == inner.MACRO_REFUSAL


def test_a_workbook_with_macros_is_refused_before_openpyxl_is_imported(inner, tmp_path, monkeypatch):
    path = macro_package(tmp_path / "book.xlsm", "xlsx", content_type=MACRO_MAIN_TYPES["xlsm"], extra_parts=["xl/vbaProject.bin"])
    monkeypatch.setitem(sys.modules, "openpyxl", None)      # an import of it would raise ImportError: it is never reached
    with pytest.raises(inner.Failed) as refused:
        inner.convert("xlsx", path, str(tmp_path / "work"))
    assert str(refused.value) == inner.MACRO_REFUSAL


def test_the_macro_check_does_not_read_a_huge_content_types_part_and_an_old_binary_file_is_not_a_package(inner, tmp_path, monkeypatch):
    big = tmp_path / "big.docx"
    with zipfile.ZipFile(big, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "<Types>" + " " * 3000 + "</Types>")
        z.writestr(MAIN_PARTS["docx"], "<x/>")
    monkeypatch.setattr(inner, "XML_PARTS_CAP", 1000)
    with pytest.raises(inner.Failed) as refused:
        inner.refuse_macros(str(big))
    assert "too large" in str(refused.value)
    old = tmp_path / "old.doc"
    old.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1 an old binary .doc is not a zip")     # an OLE file: never a package
    with pytest.raises(inner.Failed) as refused:
        inner.convert("docx", str(old), str(tmp_path / "work"))
    assert "not a valid Office package" in str(refused.value)


def test_a_macro_enabled_file_exits_3_with_the_sentence_and_prints_nothing_on_standard_output(inner, tmp_path):
    path = macro_package(tmp_path / "input", "docx", content_type=MACRO_MAIN_TYPES["docm"], extra_parts=["word/vbaProject.bin"])
    for kind in ("docx", "ooxml"):
        done = subprocess.run([sys.executable, "-I", str(INNER), "--type", kind, "--input", path, "--work", str(tmp_path / "w")],
                              capture_output=True, timeout=60, env={"PATH": os.environ.get("PATH", ""), "CONVERTER_TOOL_PATH": tool_path()})
        assert done.returncode == 3 and done.stdout == b""
        assert done.stderr.decode().strip() == f"error: {inner.MACRO_REFUSAL}"


# --- the bypasses an independent review built: references, names, duplicates, relationships, damaged streams ------------------------------

PLAIN_DOC = "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
PLAIN_SHEET = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"
DOCM_TYPE = "application/vnd.ms-word.document.macroEnabled.main+xml"
VBA_REL = "http://schemas.microsoft.com/office/2006/relationships/vbaProject"
TYPES_HEAD = ('<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
              '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>')
FICTIONAL = b"fictional bytes, never read"


def content_types(*items):
    return TYPES_HEAD + "".join(items) + "</Types>"


def override(part, content_type):
    return f'<Override PartName="{part}" ContentType="{content_type}"/>'


def relationships(target, relation_type=VBA_REL, extra=""):
    return ('<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'<Relationship Id="rId9" Type="{relation_type}" Target="{target}"{extra}/></Relationships>')


def make_zip(path, entries):
    """A package with these (name, data) entries in this order; a name twice is allowed (zipfile warns, the test does not care)."""
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            for name, data in entries:
                z.writestr(name, data)
    return str(path)


def assert_macro_refusal(inner, path, tmp_path):
    for kind in ("docx", "xlsx", "pptx", "ooxml"):
        with pytest.raises(inner.Failed) as refused:
            inner.convert(kind, path, str(tmp_path / "work"))
        assert str(refused.value) == inner.MACRO_REFUSAL


REFERENCE_CASES = [
    ("charref-in-an-override-type", [("[Content_Types].xml", content_types(override("/word/document.xml", PLAIN_DOC),
                                                                         override("/word/blob.bin", "application/vnd.ms-office.vbaPr&#111;ject"))),
                                     ("word/document.xml", "<w/>"), ("word/blob.bin", FICTIONAL)]),
    ("charref-in-the-main-type", [("[Content_Types].xml", content_types(override("/word/document.xml",
                                                                               "application/vnd.ms-word.document.&#x6D;acroEnabled.main+xml"))),
                                  ("word/document.xml", "<w/>")]),
    ("charref-macro-sheet-renamed", [("[Content_Types].xml", content_types(override("/xl/workbook.xml", PLAIN_SHEET),
                                                                          override("/xl/worksheets/sheet9.xml", "application/vnd.ms-excel.m&#97;crosheet+xml"))),
                                     ("xl/workbook.xml", "<w/>"), ("xl/worksheets/sheet9.xml", "<x/>")]),
    ("default-extension-type", [("[Content_Types].xml", content_types('<Default Extension="bin" ContentType="application/vnd.ms-office.vba&#80;roject"/>')),
                                ("word/document.xml", "<w/>"), ("word/blob.bin", FICTIONAL)]),
    ("attribute-across-lines", [("[Content_Types].xml", content_types('<Override PartName="/word/document.xml"\n ContentType\n=\n"' + DOCM_TYPE + '"/>')),
                                ("word/document.xml", "<w/>")]),
    ("prefixed-namespace", [("[Content_Types].xml", '<?xml version="1.0"?><t:Types xmlns:t="http://schemas.openxmlformats.org/package/2006/content-types">'
                             f'<t:Override PartName="/word/document.xml" ContentType="{DOCM_TYPE}"/></t:Types>'),
                            ("word/document.xml", "<w/>")]),
    ("utf-16-content-types", [("[Content_Types].xml", content_types(override("/word/document.xml", DOCM_TYPE)).replace("UTF-8", "UTF-16").encode("utf-16")),
                              ("word/document.xml", "<w/>")]),
    ("relationship-to-a-renamed-project", [("[Content_Types].xml", content_types(override("/word/document.xml", PLAIN_DOC),
                                                                                 '<Default Extension="bin" ContentType="application/octet-stream"/>')),
                                           ("word/document.xml", "<w/>"), ("word/_rels/document.xml.rels", relationships("blob.bin")),
                                           ("word/blob.bin", FICTIONAL)]),
    ("relationship-to-a-macro-sheet", [("[Content_Types].xml", content_types(override("/word/document.xml", PLAIN_DOC))), ("word/document.xml", "<w/>"),
                                       ("_rels/.rels", relationships("x.xml", "http://schemas.microsoft.com/office/2006/relationships/xlMacrosheet")),
                                       ("x.xml", "<x/>")]),
    ("relationship-type-by-a-charref", [("[Content_Types].xml", content_types(override("/word/document.xml", PLAIN_DOC))), ("word/document.xml", "<w/>"),
                                        ("word/_rels/document.xml.rels", relationships("b.bin", "http://schemas.microsoft.com/office/2006/relationships/wordVba&#68;ata"))]),
]


@pytest.mark.parametrize("case, entries", REFERENCE_CASES, ids=[c[0] for c in REFERENCE_CASES])
def test_a_reference_or_a_relationship_cannot_hide_a_macro_word(inner, tmp_path, case, entries):
    assert_macro_refusal(inner, make_zip(tmp_path / case, entries), tmp_path)


@pytest.mark.parametrize("name", ["word/vbaProject%2Ebin", "word\\vbaProject.bin", "/word/vbaProject.bin", "word/vbaProject.bin ",
                                  "word/VBAProject.BIN", "word/%76baProject.bin"])
def test_a_part_name_is_compared_as_a_reader_would_read_it(inner, tmp_path, name):
    path = make_zip(tmp_path / "named", [("[Content_Types].xml", content_types(override("/word/document.xml", PLAIN_DOC))),
                                         ("word/document.xml", "<w/>"), (name, FICTIONAL)])
    assert_macro_refusal(inner, path, tmp_path)


@pytest.mark.parametrize("name", ["/xl/macrosheets/sheet1.xml", "xl\\macrosheets\\sheet1.xml", "XL/MacroSheets/sheet1.xml", "xl/macrosheets%2Fsheet1.xml"])
def test_a_macro_sheet_folder_is_found_whatever_the_spelling_of_its_name(inner, tmp_path, name):
    path = make_zip(tmp_path / "sheets", [("[Content_Types].xml", content_types(override("/xl/workbook.xml", PLAIN_SHEET))),
                                          ("xl/workbook.xml", "<w/>"), (name, "<x/>")])
    assert_macro_refusal(inner, path, tmp_path)


@pytest.mark.parametrize("first, second", [("benign", "macro"), ("macro", "benign")])
def test_a_package_with_two_content_types_parts_is_refused_whichever_one_a_reader_would_open(inner, tmp_path, first, second):
    chosen = {"benign": content_types(override("/word/document.xml", PLAIN_DOC)), "macro": content_types(override("/word/document.xml", DOCM_TYPE))}
    path = make_zip(tmp_path / "twice", [("[Content_Types].xml", chosen[first]), ("word/document.xml", "<w/>"), ("[Content_Types].xml", chosen[second])])
    for kind in ("docx", "ooxml"):
        with pytest.raises(inner.Failed) as refused:
            inner.convert(kind, path, str(tmp_path / "work"))
        assert "two parts with the same name" in str(refused.value)


def test_a_content_types_part_in_another_case_beside_the_real_one_is_refused(inner, tmp_path):
    path = make_zip(tmp_path / "case", [("[Content_Types].xml", content_types(override("/word/document.xml", PLAIN_DOC))), ("word/document.xml", "<w/>"),
                                        ("[CONTENT_TYPES].XML", content_types(override("/word/document.xml", DOCM_TYPE)))])
    with pytest.raises(inner.Failed) as refused:
        inner.convert("docx", path, str(tmp_path / "work"))
    assert "two parts with the same name" in str(refused.value)


def test_a_declared_office_package_without_content_types_is_refused_for_every_type(inner, tmp_path):
    path = make_zip(tmp_path / "none", [("word/document.xml", "<w/>"), ("word/blob.bin", FICTIONAL),
                                        ("word/_rels/document.xml.rels", relationships("blob.bin"))])
    for kind in ("docx", "xlsx", "pptx", "ooxml"):
        with pytest.raises(inner.Failed) as refused:
            inner.convert(kind, path, str(tmp_path / "work"))
        assert "no [Content_Types].xml" in str(refused.value)


def test_a_document_type_declaration_or_an_entity_is_refused_and_is_never_expanded(inner, tmp_path):
    declared = ('<?xml version="1.0"?><!DOCTYPE Types [<!ENTITY m "macroEnabled">]><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                + override("/word/document.xml", "application/vnd.ms-word.document.&m;.main+xml") + "</Types>")
    bomb = '<?xml version="1.0"?><!DOCTYPE Types [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">]><Types>&b;</Types>'
    for case, body in (("entity", declared), ("expansion", bomb)):
        path = make_zip(tmp_path / case, [("[Content_Types].xml", body), ("word/document.xml", "<w/>")])
        with pytest.raises(inner.Failed) as refused:
            inner.convert("docx", path, str(tmp_path / "work"))
        assert "document type declaration" in str(refused.value)
    rel = make_zip(tmp_path / "rels", [("[Content_Types].xml", content_types(override("/word/document.xml", PLAIN_DOC))), ("word/document.xml", "<w/>"),
                                       ("_rels/.rels", '<?xml version="1.0"?><!DOCTYPE r [<!ENTITY t "x">]><Relationships/>')])
    with pytest.raises(inner.Failed) as refused:
        inner.refuse_macros(rel)
    assert "document type declaration" in str(refused.value)


def test_an_xml_part_that_is_not_well_formed_or_has_an_undefined_entity_is_a_closed_failure(inner, tmp_path):
    for case, body in (("broken", "<Types><Override"), ("undefined", "<Types a='&nothing;'/>")):
        path = make_zip(tmp_path / case, [("[Content_Types].xml", body), ("word/document.xml", "<w/>")])
        with pytest.raises(inner.Failed) as refused:
            inner.refuse_macros(path)
        assert str(refused.value) == "an XML part of the package cannot be read"


def test_a_damaged_compressed_stream_is_a_closed_failure_and_the_program_exits_3_with_no_traceback(inner, tmp_path):
    path = tmp_path / "damaged"
    body = ("<Types>" + "<Override PartName='/x' ContentType='text/plain'/>" * 200 + "</Types>").encode()
    make_zip(path, [("[Content_Types].xml", body), ("word/document.xml", "<w/>")])
    data = bytearray(path.read_bytes())
    start = 30 + len("[Content_Types].xml")
    for i in range(start + 2, start + 12):
        data[i] ^= 0xFF
    path.write_bytes(bytes(data))
    with pytest.raises(inner.Failed) as refused:
        inner.refuse_macros(str(path))
    assert "cannot be read" in str(refused.value)
    done = subprocess.run([sys.executable, "-I", str(INNER), "--type", "docx", "--input", str(path), "--work", str(tmp_path / "w")],
                          capture_output=True, timeout=60, env={"PATH": os.environ.get("PATH", ""), "CONVERTER_TOOL_PATH": tool_path()})
    assert done.returncode == 3 and done.stdout == b"" and b"Traceback" not in done.stderr
    assert done.stderr.decode().strip() == "error: the package's XML part cannot be read"


def test_all_the_xml_read_for_the_check_has_a_total_budget(inner, tmp_path, monkeypatch):
    entries = [("[Content_Types].xml", content_types(override("/word/document.xml", PLAIN_DOC))), ("word/document.xml", "<w/>")]
    entries += [(f"word/_rels/part{n}.xml.rels", relationships(f"t{n}.xml", "http://example.invalid/rel") + " " * 600) for n in range(5)]
    path = make_zip(tmp_path / "many", entries)
    inner.refuse_macros(path)
    monkeypatch.setattr(inner, "XML_PARTS_TOTAL", 2000)
    with pytest.raises(inner.Failed) as refused:
        inner.refuse_macros(path)
    assert "too large" in str(refused.value)


def test_what_is_outside_the_scope_passes_the_check(inner, tmp_path):
    """The check judges macro parts, not ActiveX controls, OLE objects, ribbon callbacks, a remote template or a dialog sheet: the
    container has no network and runs nothing (providers/converter/README.md, "Not covered")."""
    template = relationships("https://example.invalid/t.dotm", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/attachedTemplate",
                             ' TargetMode="External"')
    path = make_zip(tmp_path / "outside", [
        ("[Content_Types].xml", content_types(override("/word/document.xml", PLAIN_DOC),
                                              '<Default Extension="bin" ContentType="application/vnd.ms-office.activeX"/>')),
        ("word/document.xml", "<w/>"), ("word/activeX/activeX1.bin", FICTIONAL), ("word/embeddings/oleObject1.bin", b"\xd0\xcf\x11\xe0" + FICTIONAL),
        ("customUI/customUI14.xml", '<customUI onLoad="RibbonLoaded"/>'), ("word/_rels/settings.xml.rels", template),
        ("xl/dialogsheets/sheet1.xml", "<x/>")])
    inner.refuse_macros(path)
