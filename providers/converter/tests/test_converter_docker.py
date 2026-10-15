"""The document converter in a real container (providers/converter/container.py with the image of providers/converter/Dockerfile):
each format through the adopted tools, a key hidden in a PDF's compressed text found only after the conversion, and the limits
of the container as the image really holds them (no network, a read-only root, a memory-backed scratch with no exec).

Opt in: these tests need a local docker daemon, build the image once (a network step: the Debian snapshot archive and the base
image, as `build --confirmed` does) and take a few minutes the first time. They run only with

    WB_CONVERTER_DOCKER_TESTS=1 uv run --with pytest==9.1.1 pytest providers/converter/tests/test_converter_docker.py

Everything they start carries the label org.openhora.converter and is removed by name; the image is the provider's own tag.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
import uuid
import zipfile
import zlib
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("WB_CONVERTER_DOCKER_TESTS") != "1",
                                reason="a real container: set WB_CONVERTER_DOCKER_TESTS=1 (builds the converter image once)")

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
FIXTURES = HERE / "fixtures"
sys.path.insert(0, str(REPO / "providers"))


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


sys.path.insert(0, str(REPO / "runtime"))
import workcopy  # noqa: E402  (limit L14's scan, the one the sources import runs on the converted text)

container = load("converter_container_docker_test", REPO / "providers" / "converter" / "container.py")
box = sys.modules["_container"]


@pytest.fixture(scope="module")
def image():
    container.local_daemon()
    try:
        return container.image_id(container.image_tag())
    except container.ProviderError:
        assert container.cmd_build({"--confirmed": True}) == 0
        return container.image_id(container.image_tag())


def convert(tmp_path, image, name, kind):
    out = tmp_path / ("out-" + uuid.uuid4().hex[:6])
    out.mkdir(mode=0o700)
    done = container.convert(str(FIXTURES / name), kind, str(out), image=image)
    return done, {p.name: p.read_bytes() for p in out.iterdir()}


@pytest.mark.parametrize("name,kind,expects", [
    ("brief.pdf", "pdf", ["[page 1]\n\nClinics want shorter forms.", "[page 2]\n\nPrices vary by region."]),
    ("notes.docx", "docx", ["# Interview notes", "**shorter forms**", "pear 3.1"]),
    ("notes.docx", "ooxml", ["# Interview notes"]),
    ("review.pptx", "pptx", ["# Harbor Cafe Quarterly Review", "# Highlights", "Staff turnover fell to 8 percent",
                             "| Dock Street | 48200 | 9100 |", "### Notes\n\nSpeaker note: thank the Dock Street team."]),
    ("review.pptx", "ooxml", ["# Sites"]),
    ("rich.pptx", "pptx", ["- Unlock the doors\n  - Disarm the alarm", "net 30 \\| invoice by mail", "# Slide 4"]),
    ("review.docx", "docx", ["# Harbor Cafe Quarterly Review", "## Next steps", "| Site        | Revenue | Visits |"]),
    ("review.html", "html", ["## Highlights", "[the loyalty page](https://cafe.example/loyalty)", "| Mill Lane   | 39750   | 7400   |"]),
    ("review.pdf", "pdf", ["[page 1]", "[page 2]", "Dock Street"]),
    ("page.html", "html", ["# Fruit market", "Apples sell best in autumn.", "| apple | 1.2"]),
    ("plain.txt", "text", ["A second paragraph with an accent: caf\u00e9."]),
])
def test_each_text_format_comes_out_as_markdown(tmp_path, image, name, kind, expects):
    done, files = convert(tmp_path, image, name, kind)
    assert sorted(files) == ["converted.md", "info.json"] and done["outputs"] == ["converted.md", "info.json"]
    text = files["converted.md"].decode()
    for expected in expects:
        assert expected in text, expected
    assert "alert" not in text and "hidden script text" not in text
    info = json.loads(files["info.json"])
    ooxml = {"notes.docx": "docx", "review.pptx": "pptx"}
    assert info["converter"] == "document" and info["kind"] == (ooxml[name] if kind == "ooxml" else kind)
    assert done["image"] == image and (done["tool_versions"] or kind == "text"), "the tools that ran are recorded"
    if kind == "pptx" or (kind == "ooxml" and name == "review.pptx"):
        assert done["tool_versions"] == {"python-pptx": "1.0.2"}


def test_a_csv_with_semicolons_and_a_workbook_come_out_as_csv_or_as_markdown_with_a_section_per_sheet(tmp_path, image):
    done, files = convert(tmp_path, image, "data.csv", "csv")
    assert files["converted.csv"].decode() == 'name,price,qty\napple,"1,20",10\npear,"3,10",4\n'
    done, files = convert(tmp_path, image, "answers.xlsx", "xlsx")
    assert files["converted.csv"].decode() == "clinic,forms per day\nNorth clinic,12\nSouth clinic,30\n" and "openpyxl" in done["tool_versions"]
    done, files = convert(tmp_path, image, "survey.xlsx", "xlsx")
    text = files["converted.md"].decode()
    assert "## Sheet: Prices" in text and "## Sheet: Costs" in text and "hidden sheet text" not in text
    assert any("hidden sheet" in n for n in json.loads(files["info.json"])["notes"])


def test_a_key_in_the_compressed_text_of_a_pdf_is_in_the_converted_text_and_not_in_the_raw_bytes(tmp_path, image):
    key = "sk-" + "ant-" + "api03-" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6"
    content = zlib.compress(f"BT /F1 12 Tf 72 720 Td ({key}) Tj ET".encode())
    pdf = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
           b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj\n"
           b"4 0 obj<</Length " + str(len(content)).encode() + b"/Filter/FlateDecode>>stream\n" + content + b"\nendstream\nendobj\n"
           b"5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n")
    assert key.encode() not in pdf
    path = tmp_path / "planted.pdf"
    path.write_bytes(pdf)
    out = tmp_path / "out"
    out.mkdir(mode=0o700)
    container.convert(str(path), "pdf", str(out), image=image)
    assert key in (out / "converted.md").read_text()
    reason = workcopy.scan((out / "converted.md").read_bytes())
    assert reason and "credential" in reason and key not in reason, "the credential scan after the conversion refuses it"


def test_a_key_in_a_slide_is_in_the_converted_text_and_the_credential_scan_refuses_it(tmp_path, image):
    key = "sk-" + "ant-" + "api03-" + "Z9y8X7w6V5u4T3s2R1q0P9o8N7m6L5k4"
    planted = tmp_path / "planted.pptx"
    with zipfile.ZipFile(FIXTURES / "review.pptx") as source, zipfile.ZipFile(planted, "w", zipfile.ZIP_DEFLATED) as target:
        for member in source.infolist():
            data = source.read(member.filename)
            if member.filename == "ppt/slides/slide2.xml":
                assert b"Supplier costs stayed flat" in data
                data = data.replace(b"Supplier costs stayed flat", key.encode())
            target.writestr(member.filename, data)
    assert key.encode() not in planted.read_bytes()
    out = tmp_path / "out"
    out.mkdir(mode=0o700)
    container.convert(str(planted), "pptx", str(out), image=image)
    text = (out / "converted.md").read_text()
    assert key in text
    reason = workcopy.scan(text.encode())
    assert reason and "credential" in reason and key not in reason


def test_a_file_that_is_not_what_it_says_fails_in_the_container_and_leaves_nothing(tmp_path, image):
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"%PDF-1.4\nthis is not a pdf")
    out = tmp_path / "out"
    out.mkdir(mode=0o700)
    with pytest.raises(container.ProviderError) as failed:
        container.convert(str(broken), "pdf", str(out), image=image)
    assert "failed" in str(failed.value) and os.listdir(out) == []
    bad = tmp_path / "bad.docx"
    bad.write_bytes(b"PK\x03\x04 not a package")
    with pytest.raises(container.ProviderError):
        container.convert(str(bad), "docx", str(out), image=image)


def probe(image, tmp_path, code: str):
    """Run a small program in the image with the limits of a conversion; (return code, stderr, stdout)."""
    name = "openhora-converter-test-" + uuid.uuid4().hex[:12]
    source = tmp_path / "input"
    source.write_bytes(b"x")
    command = box.argv(name, image, [container.PYTHON, "-I", "-c", code], label=container.LABEL_RUN, deadline=2 ** 31,
                       mounts=[(str(source), "/in/input", "ro")], memory_mb=container.MEMORY_MB, cpus=container.CPUS,
                       scratch_mb=container.SCRATCH_MB, pids_limit=container.PIDS)
    done = box.run(command, name, 60, stdout_cap=65536)
    return done.returncode, done.stderr, done.stdout.decode()


def test_the_image_really_has_no_network_a_read_only_root_a_scratch_with_no_exec_and_no_secret(tmp_path, image):
    code, err, out = probe(image, tmp_path, "import socket\ntry:\n socket.create_connection(('1.1.1.1', 53), 3)\n print('REACHED')\n"
                                           "except OSError as e:\n print('NO NETWORK')")
    assert code == 0 and out.strip() == "NO NETWORK", (code, err, out)
    code, err, out = probe(image, tmp_path, "open('/etc/should-not-be-here', 'w')")
    assert code != 0 and "Read-only file system" in err
    code, err, out = probe(image, tmp_path, "open('/in/input', 'w')")
    assert code != 0 and "Read-only file system" in err
    code, err, out = probe(image, tmp_path, "import os, subprocess\nopen('/scratch/t.sh', 'w').write('#!/bin/sh\\necho hi\\n')\nos.chmod('/scratch/t.sh', 0o755)\n"
                                           "print(subprocess.run(['/scratch/t.sh']).returncode)")
    assert code != 0 and "Permission denied" in err
    code, err, out = probe(image, tmp_path, "import os\nprint(sorted(k for k in os.environ if 'KEY' in k or 'TOKEN' in k or 'SECRET' in k))")
    assert out.strip() == "[]"
    code, err, out = probe(image, tmp_path, "import os\nprint(os.getuid() != 0)")
    assert out.strip() == "True", "an unprivileged user"
    tools = probe(image, tmp_path, "import shutil\nprint([shutil.which(t) is not None for t in ('pdftotext', 'pandoc')])")[2].strip()
    assert tools == "[True, True]"


def test_python_pptx_in_the_image_is_the_pinned_version_with_no_pip_no_markitdown_and_an_address_refused(tmp_path, image):
    code = ("import sys, importlib.util\nsys.path.insert(0, '/opt/converter')\nimport pptx\n"
            "print(pptx.__version__, importlib.util.find_spec('markitdown'), importlib.util.find_spec('onnxruntime'), "
            "importlib.util.find_spec('numpy'))\n"
            "try:\n import pip\n print('pip present')\nexcept ImportError:\n print('no pip')")
    code_, err, out = probe(image, tmp_path, code)
    assert code_ == 0, err
    assert out.splitlines() == ["1.0.2 None None None", "no pip"]
    for address in ("https://cafe.example/menu.pptx", "file:///etc/passwd", "data:text/plain;base64,aGk="):
        code_, err, out = probe(image, tmp_path, "import subprocess, sys\nr = subprocess.run([sys.executable, '-I', '/opt/converter/_inner.py', "
                                                  f"'--type', 'pptx', '--input', {address!r}], capture_output=True)\n"
                                                  "print(r.returncode, r.stdout, r.stderr)")
        assert out.strip().startswith("3 b'' b'error: the input is a file path, never an address"), out
    code_, err, out = probe(image, tmp_path, "import sys, socket\nsys.path.insert(0, '/opt/converter')\nimport _inner\n"
                                              "try:\n _inner.convert_pptx('/in/input', '/scratch')\nexcept _inner.Failed as e:\n print('FAILED', e)\n"
                                              "try:\n socket.create_connection(('1.1.1.1', 53), 1)\nexcept OSError as e:\n print(e)")
    assert out.splitlines()[0].startswith("FAILED") and out.splitlines()[1] == "the converter makes no network connection"


def test_the_label_that_marks_the_containers_leaves_none_behind(image):
    done = box.docker(["ps", "-a", "--filter", f"label={container.LABEL_RUN}=1", "--format", "{{.ID}}"])
    assert done.returncode == 0 and re.findall(r"[0-9a-f]{12}", done.stdout) == []
