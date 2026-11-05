"""What is sent is what is scanned (slice S18, limit L14; runtime/send_scan.py, runtime/ops_file_read.py), through `ops.say` and on the module itself.

The converter of a source writes the text a person reads; a file that is SENT is its bytes. Each probe below puts a fake credential (`ghp_` and 36 characters, built from two halves so that
this file holds none) where the converter's text does not reach, with the converter stand-in answering a CLEAN text, and the file must not be sent: the raw bytes of an HTML page (a
script), the properties of a Word file, the data link of a Markdown export, the /Title of a PDF, a deflated stream of a PDF, a hidden sheet of an Excel file. A package with an embedded object, a
part that is not text, a name that leaves the package, a stream with a filter the module does not read, one that does not inflate and every cap refuse the file. Each probe has a
`test_vacuity_` case: the check is replaced by one that reads only the converter's text and the same file goes out with the credential in it.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_file_send_scan.py
"""
from __future__ import annotations

from phone_literals import PLAIN_REFUSAL_PT  # noqa: E402,F401

import io
import zipfile
import zlib

import pytest

import standin_tree as st
from test_file_read import drives, item  # noqa: F401  (the fixture and its helpers)
from test_file_send import LIMITS, SENDER_KEY, WITHHELD, ask, sending  # noqa: F401
from test_ops_natural import world  # noqa: F401

ops_file_read = st.load("ops_file_read")
send_scan = st.load("send_scan")

CRED = "ghp_" + "a1B2" * 9
CLEAN_TEXT = "Relatorio do coral\n\nTotal: 10 vozes.\n"
FIXED = (2026, 1, 1, 0, 0, 0)      # a fixed date: the bytes of a package, and so the ids of the cases, are the same in every process of a parallel run
PICTURE = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40


def scan(data):
    return ops_file_read.sources._workcopy().scan(data)


def entry(name: str):
    info = zipfile.ZipInfo(name, FIXED)
    info.compress_type = zipfile.ZIP_DEFLATED
    return info


def package(parts: dict, kind="docx") -> bytes:
    """A zip package: the first part names the kind (word/, xl/ or ppt/) the way the intake reads it."""
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(entry("[Content_Types].xml"), "<Types/>")
        for name, body in parts.items():
            z.writestr(entry(name), body)
    return out.getvalue()


def docx(extra: dict | None = None) -> bytes:
    return package({"word/document.xml": "<w:document><w:t>ola</w:t></w:document>", **(extra or {})})


def xlsx(extra: dict | None = None) -> bytes:
    return package({"xl/workbook.xml": "<workbook/>", "xl/worksheets/sheet1.xml": "<worksheet><c><v>1</v></c></worksheet>", **(extra or {})})


def pdf(*objects: bytes, info: bytes = b"") -> bytes:
    return b"%PDF-1.7\n" + b"".join(objects) + info + b"trailer\n<< /Root 1 0 R >>\n%%EOF\n"


def stream(dictionary: bytes, body: bytes, number=4) -> bytes:
    return b"%d 0 obj\n<< %s /Length %d >>\nstream\n%s\nendstream\nendobj\n" % (number, dictionary, len(body), body)


def deflated(text: str) -> bytes:
    return stream(b"/Filter /FlateDecode", zlib.compress(text.encode("utf-8")))


def put(world, name, data, markdown=False):
    made = world["drives"]
    ident = f"drv1/it!{len(made.files) + 20}"
    made.folders[("microsoft", "/Documentos")] = made.folders[("microsoft", "/Documentos")] + [item(ident, name)]
    made.files[("microsoft", ident)] = data
    if markdown:
        made.markdown.add(("microsoft", ident))
    return name.rsplit(".", 1)[0]


def sent(world, name, data, markdown=False):
    span = put(world, name, data, markdown)
    return ask(world, f"Me traga o arquivo {span}", span)


def withheld(name):
    return WITHHELD.format(name=name, account="OneDrive")


def only_the_converted_text(monkeypatch):
    """The planted fault: the check reads nothing of the bytes (the old behaviour: only the converter's text was scanned)."""
    monkeypatch.setattr(ops_file_read.send_scan, "check", lambda *a, **k: None)


# --- the reviewer's probes, through ops.say ----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("name, data, markdown", [
    ("Pagina do coral.html", f"<!doctype html><html><body><p>ola</p><script>var key = '{CRED}';</script></body></html>".encode(), False),
    ("Ata do coral.docx", docx({"docProps/core.xml": f"<cp:coreProperties><dc:title>{CRED}</dc:title></cp:coreProperties>"}), False),
    ("Ata do coral.md", f"# Ata\n\nok\n\n![k](data:text/plain,{CRED})\n".encode(), True),
    ("Balanco do coral.pdf", pdf(b"1 0 obj\n<< /Title (" + CRED.encode() + b") >>\nendobj\n"), False),
    ("Balanco do coral.pdf", pdf(deflated(f"BT ({CRED}) Tj ET")), False),
    ("Custos do coral.xlsx", xlsx({"xl/worksheets/sheet2.xml": f"<worksheet><c t='inlineStr'><is><t>{CRED}</t></is></c></worksheet>"}), False),
    ("Custos do coral.pptx", package({"ppt/slides/slide9.xml": f"<p:sld><a:t>{CRED}</a:t></p:sld>"}), False),
], ids=["html-script", "docx-core-properties", "markdown-data-link", "pdf-title", "pdf-flate-stream", "xlsx-hidden-sheet", "pptx-hidden-slide"])
def test_a_credential_where_the_converter_text_does_not_reach_withholds_the_file_and_the_preview(sending, name, data, markdown):
    sending["converted"]["text"] = CLEAN_TEXT
    result = sent(sending, name, data, markdown)
    assert result["reply"] == withheld(name) and "attachment" not in result
    assert CRED not in result["reply"] and "Total: 10 vozes" not in result["reply"]


@pytest.mark.parametrize("name, data, markdown", [
    ("Pagina do coral.html", f"<html><body><script>var key = '{CRED}';</script></body></html>".encode(), False),
    ("Ata do coral.docx", docx({"docProps/core.xml": f"<dc:title>{CRED}</dc:title>"}), False),
    ("Ata do coral.md", f"# Ata\n\n![k](data:text/plain,{CRED})\n".encode(), True),
    ("Balanco do coral.pdf", pdf(b"1 0 obj\n<< /Title (" + CRED.encode() + b") >>\nendobj\n"), False),
    ("Balanco do coral.pdf", pdf(deflated(f"BT ({CRED}) Tj ET")), False),
    ("Custos do coral.xlsx", xlsx({"xl/worksheets/sheet2.xml": f"<c>{CRED}</c>"}), False),
], ids=["html-script", "docx-core-properties", "markdown-data-link", "pdf-title", "pdf-flate-stream", "xlsx-hidden-sheet"])
def test_vacuity_a_check_of_the_converter_text_alone_sends_the_credential(sending, monkeypatch, name, data, markdown):
    sending["converted"]["text"] = CLEAN_TEXT
    only_the_converted_text(monkeypatch)
    result = sent(sending, name, data, markdown)
    assert CRED.encode() in result["attachment"]["data"] or CRED.encode() in zlib_text(result["attachment"]["data"], name)


def zlib_text(data: bytes, name: str) -> bytes:
    """The text a reader of the file would find: the parts of a package, the inflated streams of a PDF (the vacuity cases look for the credential in what went out)."""
    out = b""
    if data[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            out = b"".join(z.read(n) for n in z.namelist())
    elif data[:5] == b"%PDF-":
        for part in data.split(b"stream\n")[1:]:
            try:
                out += zlib.decompressobj().decompress(part)
            except zlib.error:
                pass
    return out


def test_clean_files_of_every_kind_are_sent_as_they_are(sending):
    sending["converted"]["text"] = CLEAN_TEXT
    cases = {
        "Pagina limpa.html": b"<!doctype html><html><body><p>ola</p><script>var n = 1;</script></body></html>",
        "Ata limpa.docx": docx({"docProps/core.xml": "<dc:title>Ata</dc:title>", "word/media/image1.png": PICTURE, "word/_rels/document.xml.rels": "<Relationships/>"}),
        "Custos limpos.xlsx": xlsx({"xl/worksheets/sheet2.xml": "<worksheet/>", "docProps/thumbnail.jpeg": b"\xff\xd8\xff\xe0jpeg"}),
        "Slides limpos.pptx": package({"ppt/slides/slide1.xml": "<p:sld/>"}),
        "Relatorio limpo.pdf": pdf(deflated("BT (ola) Tj ET"), stream(b"/Subtype /Image /Filter /DCTDecode", b"\xff\xd8\xffjpeg", 5), stream(b"/Subtype /Image /Filter /FlateDecode /DecodeParms << /Predictor 15 >>", zlib.compress(b"\x00" * 99), 6)),
        "Planilha limpa.csv": b"a,b\n1,2\n3,4\n",
    }
    for name, data in cases.items():
        result = sent(sending, name, data)
        assert result["attachment"]["data"] == data and result["attachment"]["name"] == name, name


# --- what refuses the file ---------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("name, data", [
    ("Ata com objeto.docx", docx({"word/embeddings/oleObject1.bin": b"\xd0\xcf\x11\xe0 binary"})),
    ("Ata com macro.docx", docx({"word/vbaProject.bin": b"\xd0\xcf\x11\xe0 macro"})),
    ("Ata com fonte.docx", docx({"word/fonts/font1.odttf": b"\x00\x01 font"})),
    ("Custos com anexo.xlsx", xlsx({"xl/embeddings/Workbook1.xlsx": b"PK\x03\x04 inner"})),
    ("Slides com anexo.pptx", package({"ppt/slides/slide1.xml": "<p:sld/>", "ppt/embeddings/oleObject1.bin": b"x"})),
], ids=["ole-object", "macro-project", "embedded-font", "embedded-workbook", "pptx-ole-object"])
def test_a_package_with_an_embedding_or_a_part_that_is_not_text_or_a_picture_is_not_sent(sending, name, data):
    sending["converted"]["text"] = CLEAN_TEXT
    result = sent(sending, name, data)
    assert result["reply"] == withheld(name) and "attachment" not in result


def test_vacuity_the_same_package_without_the_embedding_is_sent(sending):
    sending["converted"]["text"] = CLEAN_TEXT
    assert "attachment" in sent(sending, "Ata sem objeto.docx", docx())


@pytest.mark.parametrize("name, data", [
    ("Relatorio ascii.pdf", pdf(stream(b"/Filter /ASCII85Decode", b"87cURD]i,\"Ebo80~>"))),
    ("Relatorio lzw.pdf", pdf(stream(b"/Filter /LZWDecode", b"\x80\x0b\x60"))),
    ("Relatorio cadeia.pdf", pdf(stream(b"/Filter [/ASCII85Decode /FlateDecode]", b"87cURD]i,\"Ebo80~>"))),
    ("Relatorio quebrado.pdf", pdf(stream(b"/Filter /FlateDecode", b"x\x9c\x00\x01 not deflate"))),
    ("Relatorio cortado.pdf", pdf(stream(b"/Filter /FlateDecode", zlib.compress(b"a" * 5000)[:-9]))),
    ("Relatorio cifrado.pdf", pdf(stream(b"/Filter /FlateDecode /Encrypt", zlib.compress(b"x")))),
    ("Relatorio previsto.pdf", pdf(stream(b"/Filter /FlateDecode /DecodeParms << /Predictor 12 >>", zlib.compress(b"x")))),
    ("Relatorio escapado.pdf", pdf(stream(b"/Filter /F#6cateDecode", zlib.compress(b"x")))),
], ids=["ascii85", "lzw", "filter-chain", "broken-flate", "cut-flate", "encrypted", "predictor", "escaped-filter"])
def test_a_pdf_stream_the_module_cannot_read_to_the_end_is_not_sent(sending, name, data):
    sending["converted"]["text"] = CLEAN_TEXT
    result = sent(sending, name, data)
    assert result["reply"] == withheld(name) and "attachment" not in result


def test_a_name_that_leaves_the_package_an_encrypted_part_and_a_package_that_is_not_one_are_not_sent():
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr(entry("word/document.xml"), "<w/>")
        z.writestr(entry("../evil.xml"), "<x/>")
    assert send_scan.check(out.getvalue(), "docx", scan) == "refused"
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr(entry("word/document.xml"), "<w/>")
        z.writestr(entry("/abs.xml"), "<x/>")
    assert send_scan.check(out.getvalue(), "docx", scan) == "refused"
    clean = docx()
    assert send_scan.check(clean, "docx", scan) is None
    encrypted = bytearray(clean)
    index = encrypted.find(b"PK\x03\x04")
    encrypted[index + 6] |= 1      # the local header says the part is encrypted
    central = encrypted.find(b"PK\x01\x02")
    while central >= 0:
        encrypted[central + 8] |= 1
        central = encrypted.find(b"PK\x01\x02", central + 1)
    assert send_scan.check(bytes(encrypted), "docx", scan) == "refused"
    assert send_scan.check(b"PK\x03\x04 not a zip", "docx", scan) == "refused"


def test_the_caps_refuse_the_file_and_the_same_file_under_the_caps_is_read(monkeypatch):
    big = docx({"word/media/x.xml": "<a>" + "b" * 5000 + "</a>"})
    assert send_scan.check(big, "docx", scan) is None
    monkeypatch.setattr(send_scan, "PART_MAX", 1000)
    assert send_scan.check(big, "docx", scan) == "refused"
    monkeypatch.setattr(send_scan, "PART_MAX", 32 * 1024 * 1024)
    monkeypatch.setattr(send_scan, "TOTAL_MAX", 2000)
    assert send_scan.check(big, "docx", scan) == "refused"
    monkeypatch.setattr(send_scan, "TOTAL_MAX", 128 * 1024 * 1024)
    monkeypatch.setattr(send_scan, "PARTS_MAX", 1)
    assert send_scan.check(big, "docx", scan) == "refused"
    monkeypatch.setattr(send_scan, "PARTS_MAX", 5000)
    flate = pdf(deflated("a" * 5000))
    assert send_scan.check(flate, "pdf", scan) is None
    monkeypatch.setattr(send_scan, "PART_MAX", 1000)
    assert send_scan.check(flate, "pdf", scan) == "refused"
    monkeypatch.setattr(send_scan, "PART_MAX", 32 * 1024 * 1024)
    monkeypatch.setattr(send_scan, "STREAMS_MAX", 0)
    assert send_scan.check(flate, "pdf", scan) == "refused"


def test_a_decompression_bomb_is_refused_without_being_inflated_whole(monkeypatch):
    bomb = pdf(stream(b"/Filter /FlateDecode", zlib.compress(b"\x00" * (40 * 1024 * 1024))))
    assert len(bomb) < 100000 and send_scan.check(bomb, "pdf", scan) == "refused"
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(entry("word/document.xml"), b"\x00" * (40 * 1024 * 1024))
    assert len(out.getvalue()) < 100000 and send_scan.check(out.getvalue(), "docx", scan) == "refused"


def test_a_credential_in_a_utf_16_string_a_hex_string_or_an_octal_escape_of_a_pdf_is_found():
    utf16 = (chr(0xFEFF) + CRED).encode("utf-16-be")
    assert send_scan.check(pdf(b"1 0 obj\n<< /Title (" + utf16 + b") >>\nendobj\n"), "pdf", scan) == "secret"
    assert send_scan.check(pdf(b"1 0 obj\n<< /Title <" + CRED.encode().hex().encode() + b"> >>\nendobj\n"), "pdf", scan) == "secret"
    octal = b"".join(b"\\%03o" % c for c in CRED.encode())
    assert send_scan.check(pdf(b"1 0 obj\n<< /Title (" + octal + b") >>\nendobj\n"), "pdf", scan) == "secret"
    assert send_scan.check(pdf(b"1 0 obj\n<< /Title (Ata do coral) >>\nendobj\n"), "pdf", scan) is None


def test_a_text_kind_is_scanned_whole_and_a_large_file_is_scanned_in_windows():
    assert send_scan.check(("a" * 3_000_000 + " " + CRED + " " + "b" * 3_000_000).encode(), "text", scan) == "secret"      # the scan itself refuses over 5 MiB; windows read it
    assert send_scan.check(("a" * 3_000_000 + "b" * 3_000_000).encode(), "csv", scan) is None
    half = send_scan.WINDOW - 20
    assert send_scan.check(("a" * half + " " + CRED + " " + "b" * 100).encode(), "html", scan) == "secret", "a credential across the edge of a window"
    assert send_scan.check(b"ola", "svg", scan) == "refused", "a kind this module does not read is not sent"


def test_pictures_are_the_stated_gap_and_are_sent_unscanned(sending):
    """A credential drawn in a picture, or written in the text chunk of a PNG, is not seen: the gap is stated in contracts/runtime.md and docs/decisions.md, and this test pins it."""
    text_chunk = PICTURE + b"tEXtComment\x00" + CRED.encode()
    sending["drives"].files[("microsoft", "drv1/it!5")] = text_chunk
    result = ask(sending, "Me traga o arquivo Foto do coral.png", "Foto do coral.png")
    assert result["attachment"]["data"] == text_chunk and result["attachment"]["kind"] == "photo"
