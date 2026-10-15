"""The sources folder of a test project, and the files a test imports (not a test file).

`sources_dir` is a mandatory key of runtime.json with no default (runtime/project_config.py, REQUIRED): a configuration
without it is refused, so every test that writes its own runtime.json adds the key through `with_sources`. The folder is a
sibling of the test's other folders, named `sources`; it does not exist yet, and accepting the configuration creates it
(0700, marked: runtime/sources.py accept_folder), as it does for a person. `make_folder` makes one the way acceptance does,
for a test of the sources that needs the folder before any acceptance.

The builders make the small files the tests of the sources import (a PDF whose text is compressed, a Word package, a
workbook package) from the standard library, so no binary file is committed for the runtime's tests; `standin_convert` is the
stand-in for the converter's provider, which reads exactly what the builders make.
"""
from __future__ import annotations

import csv
import html.parser
import io
import json
import os
import re
import zipfile
import zlib
from pathlib import Path

NAME = "sources"


def sources_path(base) -> str:
    """The sources folder a test project gets: <base>/sources, where base is a folder of the test (its tmp_path)."""
    return str(Path(base) / NAME)


def with_sources(config: dict, base) -> dict:
    """The configuration with `sources_dir` added (a key already there is kept). Returns the same dict."""
    config.setdefault("sources_dir", sources_path(base))
    return config


def make_folder(path) -> str:
    """A sources folder as acceptance leaves it: created 0700 and marked. Returns the path."""
    import sources
    target = str(path)
    sources.accept_folder(target)
    return target


# --- the files a test imports ---------------------------------------------------------------------------------------------------------


def make_pdf(text: str) -> bytes:
    """A one-page PDF whose text sits in a Flate-compressed content stream: a scan of the file's bytes finds none of it (the
    reason the converted text is scanned, not the raw file)."""
    content = zlib.compress(f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("latin-1"))
    return (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
            b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R>>endobj\n4 0 obj<</Length "
            + str(len(content)).encode() + b"/Filter/FlateDecode>>stream\n" + content
            + b"\nendstream\nendobj\ntrailer<</Root 1 0 R>>\n%%EOF\n")


def make_docx(paragraphs) -> bytes:
    """A Word package with the entries the sniffer reads ([Content_Types].xml first, word/document.xml) and a paragraph per line."""
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as z:
        z.writestr("[Content_Types].xml", '<Types><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        z.writestr("_rels/.rels", "<Relationships/>")
        z.writestr("word/document.xml", f"<w:document><w:body>{body}</w:body></w:document>")
    return out.getvalue()


def make_xlsx(sheets) -> bytes:
    """A workbook package: sheets is [(name, [[cell, ...], ...])], each cell an inline string."""
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as z:
        z.writestr("[Content_Types].xml", '<Types><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/></Types>')
        z.writestr("_rels/.rels", "<Relationships/>")
        z.writestr("xl/workbook.xml", "<workbook><sheets>"
                   + "".join(f'<sheet name="{n}" sheetId="{i}"/>' for i, (n, _) in enumerate(sheets, 1)) + "</sheets></workbook>")
        for i, (_, rows) in enumerate(sheets, 1):
            body = "".join("<row>" + "".join(f'<c t="inlineStr"><is><t>{v}</t></is></c>' for v in row) + "</row>" for row in rows)
            z.writestr(f"xl/worksheets/sheet{i}.xml", f"<worksheet><sheetData>{body}</sheetData></worksheet>")
    return out.getvalue()


class _Stripper(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.out, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        self.skip += tag in ("script", "style")

    def handle_endtag(self, tag):
        self.skip -= tag in ("script", "style")

    def handle_data(self, data):
        if not self.skip and data.strip():
            self.out.append(data.strip())


def standin_convert(input_path, subtype, out_dir):
    """A stand-in for the converter of converter:document (the provider runs adopted tools in a container; no tool is run
    here): it reads the formats the builders above make and writes what the provider writes, converted.md or converted.csv and
    info.json, into `out_dir`. It reads the file with the standard library only."""
    with open(input_path, "rb") as f:
        data = f.read()
    kind, name, text = subtype, "converted.md", ""
    if subtype == "pdf":
        parts = []
        for stream in re.findall(rb"stream\n(.*?)\nendstream", data, re.S):
            parts += re.findall(rb"\((.*?)\) Tj", zlib.decompress(stream))
        text = "[page 1]\n\n" + b"\n".join(parts).decode("latin-1") + "\n"
    elif subtype in ("docx", "xlsx", "ooxml"):
        with zipfile.ZipFile(input_path) as z:
            kind = "docx" if "word/document.xml" in z.namelist() else "xlsx"
            if kind == "docx":
                text = "\n\n".join(re.findall(r"<w:t>(.*?)</w:t>", z.read("word/document.xml").decode("utf-8"))) + "\n"
            else:
                tables = []
                for i, sheet in enumerate(re.findall(r'<sheet name="(.*?)"', z.read("xl/workbook.xml").decode("utf-8")), 1):
                    xml = z.read(f"xl/worksheets/sheet{i}.xml").decode("utf-8")
                    buffer = io.StringIO()
                    csv.writer(buffer, lineterminator="\n").writerows([re.findall(r"<t>(.*?)</t>", row) for row in re.findall(r"<row>(.*?)</row>", xml)])
                    tables.append((sheet, buffer.getvalue()))
                if len(tables) == 1:
                    name, text = "converted.csv", tables[0][1]
                else:
                    text = "\n\n".join(f"## Sheet: {s}\n\n```csv\n{t.rstrip()}\n```" for s, t in tables) + "\n"
    elif subtype == "html":
        stripper = _Stripper()
        stripper.feed(data.decode("utf-8"))
        text = "\n\n".join(stripper.out) + "\n"
    elif subtype == "csv":
        name, text = "converted.csv", data.decode("utf-8-sig")
    else:
        text = data.decode("utf-8-sig")
    with open(os.path.join(out_dir, name), "wb") as f:
        f.write(text.encode("utf-8"))
    with open(os.path.join(out_dir, "info.json"), "w", encoding="utf-8") as f:
        json.dump({"converter": "standin", "kind": kind, "tool_versions": {"standin": "1"}}, f)
    return {"converter": "standin", "kind": kind}
