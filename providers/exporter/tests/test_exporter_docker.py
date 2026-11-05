"""The document renderer in a real container (providers/exporter/container.py with the image of providers/exporter/): each of
the four formats made from a fixture by the adopted tools, the formula guard read back out of the real workbook and CSV file, a Word
document and a PDF that carry neither a picture nor a file address, a PDF whose text the converter's container reads back, and the
limits of the container as the image really holds them (no network, a read-only root, no secret in the environment).

Opt in: these tests need a local docker daemon, build the renderer's image once (a network step: the Debian snapshot archive, the base
image and the wheels of requirements.lock, as `build --confirmed` does) and, for the PDF read-back, the converter's image; they take a
few minutes the first time. They run only with

    WB_CONVERTER_DOCKER_TESTS=1 uv run --with pytest==9.1.1 pytest providers/exporter/tests/test_exporter_docker.py

Everything they start carries the label org.openhora.exporter and is removed by name; the image is the provider's own tag.
"""
from __future__ import annotations

import csv
import importlib.util
import io
import json
import os
import re
import sys
import uuid
import zipfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("WB_CONVERTER_DOCKER_TESTS") != "1",
                                reason="a real container: set WB_CONVERTER_DOCKER_TESTS=1 (builds the renderer's image once)")

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / "providers"))


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


render = load("render_docker_test", REPO / "providers" / "exporter" / "container.py")
converter = load("converter_for_the_render_docker_test", REPO / "providers" / "converter" / "container.py")
box = sys.modules["_container"]

GUARDED = ["=1+1", "+1+1", "-1+1", "@SUM(A1:A2)", "\tcmd", "\rcmd", "\ncmd", "＝1+1", "  =lead"]
TABLE = ("name,note\n" + "".join(f'row{i},"{cell}"\n' for i, cell in enumerate(GUARDED)) + "plain,fine\nnum,12\nid,007\n")
MARKDOWN = """# Harbour market report

The market opened on **Saturday** with forty stalls. Accents: café.

| fruit | price |
|-------|-------|
| apple | =1+1  |

<script>alert("raw html")</script>

![the stall](file:///etc/passwd)

[a safe link](https://example.invalid/page) and [a share](smb://host.example/share)
"""


@pytest.fixture(scope="module")
def image():
    render.local_daemon()
    try:
        return render.image_id(render.image_tag())
    except render.ProviderError:
        assert render.cmd_build({"--confirmed": True}) == 0
        return render.image_id(render.image_tag())


def make(image, fmt, text):
    return render.render(fmt, text.encode("utf-8"), image=image)


def test_a_csv_file_has_each_guarded_cell_as_text_with_a_quote_in_front(image):
    made = make(image, "csv", TABLE)
    assert made["format"] == "csv" and made["image"] == image and made["counts"] == {"rows": len(GUARDED) + 4}
    rows = list(csv.reader(io.StringIO(made["output"].decode("utf-8").lstrip("\ufeff"), newline="")))
    assert [r[1] for r in rows[1:1 + len(GUARDED)]] == ["'" + c for c in GUARDED]
    assert rows[-3:] == [["plain", "fine"], ["num", "12"], ["id", "007"]]


def test_a_workbook_has_each_guarded_cell_as_a_text_cell_and_no_formula_anywhere(image):
    made = make(image, "xlsx", TABLE)
    with zipfile.ZipFile(io.BytesIO(made["output"])) as z:
        sheet = z.read("xl/worksheets/sheet1.xml").decode("utf-8")
        styles = z.read("xl/styles.xml").decode("utf-8")
        shared = z.read("xl/sharedStrings.xml").decode("utf-8") if "xl/sharedStrings.xml" in z.namelist() else ""
    assert "<f>" not in sheet and "<f " not in sheet and 'quotePrefix="1"' in styles
    cells = {m.group(1): (m.group(2), m.group(3)) for m in re.finditer(r'<c r="(B\d+)"([^>]*)>(.*?)</c>', sheet, re.S)}
    for index in range(len(GUARDED)):
        attrs, body = cells[f"B{index + 2}"]
        assert 't="inlineStr"' in attrs or 't="s"' in attrs, (index, attrs)
        assert "<f" not in body
    assert "openpyxl" in made["tool_versions"] and shared is not None
    numbers = re.findall(r'<c r="B(\d+)"[^>]*t="n"', sheet)
    assert numbers == [str(len(GUARDED) + 3)], "only the plain number is a number; the id with a leading zero is text"


def test_a_word_document_has_the_text_and_neither_a_picture_nor_a_script_nor_a_file_address(image):
    made = make(image, "docx", MARKDOWN)
    with zipfile.ZipFile(io.BytesIO(made["output"])) as z:
        names = z.namelist()
        body = z.read("word/document.xml").decode("utf-8")
        rels = z.read("word/_rels/document.xml.rels").decode("utf-8")
    assert "Harbour market report" in body and "the stall" in body and "café" in body and "=1+1" in body
    assert not any(n.startswith("word/media") for n in names) and "alert" not in body
    assert "file:///" not in rels + body and "smb://" not in rels and "https://example.invalid/page" in rels


def test_a_pdf_holds_the_text_and_the_converters_container_reads_it_back(image, tmp_path):
    made = make(image, "pdf", MARKDOWN)
    assert made["output"].startswith(b"%PDF-") and "weasyprint" in made["tool_versions"]
    source = tmp_path / "made.pdf"
    source.write_bytes(made["output"])
    out = tmp_path / "out"
    out.mkdir(mode=0o700)
    try:
        converter.convert(str(source), "pdf", str(out))
    except converter.ProviderError as e:
        if e.code == converter.EXIT_NOT_CONFIGURED:
            pytest.skip("the converter's image is not built here")
        raise
    text = (out / "converted.md").read_text(encoding="utf-8")
    assert "Harbour market report" in text and "forty stalls" in text and "café" in text and "alert" not in text
    assert json.loads((out / "info.json").read_text())["hidden_text"]["count"] == 0, "what the renderer prints is not hidden text"


def test_an_empty_input_or_a_table_with_nothing_in_it_fails_and_prints_nothing(image):
    for fmt, text in (("csv", " \n,\n"), ("xlsx", ",\n,\n"), ("docx", "   "), ("pdf", "\n")):
        with pytest.raises(render.ProviderError):
            make(image, fmt, text)


def probe(image, tmp_path, code):
    name = f"openhora-exporter-probe-{uuid.uuid4().hex[:8]}"
    source = tmp_path / "probe-input"
    source.write_bytes(b"x")
    command = box.argv(name, image, ["python3", "-I", "-c", code], label=render.LABEL_RUN, deadline=2 ** 31,
                       mounts=[(str(source), "/in/input", "ro")], memory_mb=render.MEMORY_MB, cpus=render.CPUS,
                       scratch_mb=render.SCRATCH_MB, pids_limit=render.PIDS)
    done = box.run(command, name, 60, stdout_cap=65536)
    return done.returncode, done.stderr, done.stdout.decode()


def test_the_image_really_has_no_network_a_read_only_root_no_secret_and_no_compiler_or_pip(image, tmp_path):
    code, err, out = probe(image, tmp_path, "import socket\ntry:\n socket.create_connection(('1.1.1.1', 53), 3)\n print('REACHED')\n"
                                           "except OSError:\n print('NO NETWORK')")
    assert code == 0 and out.strip() == "NO NETWORK", (code, err, out)
    code, err, out = probe(image, tmp_path, "open('/etc/should-not-be-here', 'w')")
    assert code != 0 and "Read-only file system" in err
    code, err, out = probe(image, tmp_path, "import os\nprint(sorted(k for k in os.environ if 'KEY' in k or 'TOKEN' in k or 'SECRET' in k))")
    assert out.strip() == "[]"
    code, err, out = probe(image, tmp_path, "import os\nprint(os.getuid() != 0)")
    assert out.strip() == "True"
    tools = probe(image, tmp_path, "import shutil\nprint([shutil.which(t) is not None for t in ('pandoc', 'gcc', 'pip', 'pip3')])")[2].strip()
    assert tools == "[True, False, False, False]"


def test_the_label_that_marks_the_containers_leaves_none_behind(image):
    done = box.docker(["ps", "-a", "--filter", f"label={render.LABEL_RUN}=1", "--format", "{{.ID}}"])
    assert done.returncode == 0 and re.findall(r"[0-9a-f]{12}", done.stdout) == []
