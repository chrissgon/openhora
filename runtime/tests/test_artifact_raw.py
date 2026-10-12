"""Tests of the kind of a file and of the raw read of an image (A-33 item 1): `artifacts[].kind` and `artifact-raw`,
decided by the bytes; the route of the local service that answers them. Offline; invented names only.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_artifact_raw.py
"""
from __future__ import annotations

import os
import struct
import types

import pytest

import standin_tree as st
from test_read_ops import tree, write  # noqa: F401  (the stand-in project the read operations are tested on)

ops = st.load("ops")
ops_reads = st.load("ops_reads")
operations = st.load("operations")

PNG = b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + b"\x00" * 40
JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x00" * 40
WEBP = b"RIFF" + struct.pack("<I", 20) + b"WEBPVP8 " + b"\x00" * 40
SVG = '<?xml version="1.0"?>\n<svg xmlns="http://www.w3.org/2000/svg" width="4" height="4"><rect width="4" height="4"/></svg>\n'
SVG_DOCTYPE = '<!DOCTYPE svg>\n<svg xmlns="http://www.w3.org/2000/svg"/>\n'          # a document type with no identifier
SVG_FRAGMENTS = ('<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"><defs>'
                 '<linearGradient id="g"/><rect id="r" width="1" height="1"/></defs><style>.a { fill: url(#g); }</style>'
                 '<use xlink:href="#r"/><use href="#r" style="fill:url( \'#g\' )"/><a href="#top"><rect fill="url(#g)"/></a></svg>')
SVG_EXTERNAL_DOCTYPE = ('<?xml version="1.0"?>\n<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" '
                        '"http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">\n<svg xmlns="http://www.w3.org/2000/svg"/>\n')
XL = 'xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"'
BAD_SVGS = {
    "external-doctype.svg": SVG_EXTERNAL_DOCTYPE,
    "stylesheet-pi.svg": '<?xml-stylesheet href="#s" type="text/css"?><svg xmlns="http://www.w3.org/2000/svg"/>',
    "foreign-object.svg": f'<svg {XL}><foreignObject><div xmlns="http://www.w3.org/1999/xhtml">x</div></foreignObject></svg>',
    "iframe.svg": f'<svg {XL}><iframe src="https://example.test/"/></svg>',
    "object.svg": f'<svg {XL}><object data="#x"/></svg>',
    "embed.svg": f'<svg {XL}><embed src="#x"/></svg>',
    "animate.svg": f'<svg {XL}><a id="a" href="#x"><animate attributeName="href" values="javascript:alert(1)"/></a></svg>',
    "animate-transform.svg": f'<svg {XL}><rect><animateTransform attributeName="transform" values="0"/></rect></svg>',
    "set.svg": f'<svg {XL}><a href="#x"><set attributeName="href" to="javascript:alert(1)"/></a></svg>',
    "external-href.svg": f'<svg {XL}><image href="https://example.test/p.png"/></svg>',
    "external-xlink.svg": f'<svg {XL}><image xlink:href="//example.test/p.png"/></svg>',
    "data-href.svg": f'<svg {XL}><image href="data:image/png;base64,AAAA"/></svg>',
    "javascript-href.svg": f'<svg {XL}><a href="javascript:alert(1)"><rect/></a></svg>',
    "javascript-spaced.svg": f'<svg {XL}><a href="#x" target="java&#9;script:alert(1)"/></svg>',
    "javascript-value.svg": f'<svg {XL}><rect fill="JavaScript:alert(1)"/></svg>',
    "style-import.svg": f'<svg {XL}><style>@import "https://example.test/a.css";</style></svg>',
    "style-url.svg": f'<svg {XL}><style>.a {{ fill: url(https://example.test/a.svg#g); }}</style></svg>',
    "style-attribute-url.svg": f'<svg {XL}><rect style="fill:url(\'https://example.test/a.svg#g\')"/></svg>',
    "fill-url.svg": f'<svg {XL}><rect fill="url(//example.test/a.svg#g)"/></svg>',
    "script.svg": '<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
    "upper-script.svg": '<svg xmlns="http://www.w3.org/2000/svg"><SCRIPT>alert(1)</SCRIPT></svg>',
    "nested.svg": '<svg xmlns="http://www.w3.org/2000/svg"><g><g><script type="x"/></g></g></svg>',
    "handler.svg": '<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"/>',
    "entity.svg": '<!DOCTYPE svg [<!ENTITY a "aaaa">]><svg xmlns="http://www.w3.org/2000/svg">&a;</svg>',
    "html.svg": '<html><body><svg xmlns="http://www.w3.org/2000/svg"/></body></html>',
    "other-namespace.svg": '<svg xmlns="http://example.test/ns"/>',
    "broken.svg": '<svg xmlns="http://www.w3.org/2000/svg"><g></svg>',
    "not-xml.svg": '<svg width="1"',
}


def put(tree, rel: str, data) -> None:
    target = tree["project"].joinpath(*rel.split("/"))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))


def kinds(tree) -> dict:
    return {a["path"]: a["kind"] for a in ops.artifacts(str(tree["project"]))["artifacts"]}


def test_the_kind_of_a_file_is_decided_by_its_bytes_never_by_its_extension(tree):
    put(tree, "docs/brand/pieces/banner.png", PNG)
    put(tree, "docs/brand/pieces/photo.jpg", JPEG)
    put(tree, "docs/brand/pieces/hero.webp", WEBP)
    put(tree, "docs/brand/pieces/mark.svg", SVG)
    put(tree, "docs/brand/pieces/old.svg", SVG_DOCTYPE)
    put(tree, "docs/brand/pieces/refs.svg", SVG_FRAGMENTS)
    put(tree, "docs/brand/notes.md", "# Notes\n")
    put(tree, "docs/brand/readme.txt", "plain words\n")
    put(tree, "docs/brand/accents.md", "café " * 3000)             # a multi-byte character may sit at the edge of the head
    put(tree, "docs/brand/fonts/inter.woff2", b"wOF2" + b"\x00" * 64)
    put(tree, "docs/brand/spec.pdf", b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
    put(tree, "docs/brand/archive.zip", b"PK\x03\x04" + b"\x00" * 30)
    # the name lies in both directions
    put(tree, "docs/brand/not-an-image.png", "this is text\n")
    put(tree, "docs/brand/really-an-image.md", PNG)
    put(tree, "docs/brand/binary-notes.md", b"\xff\xfe\x00\x01")
    for name, text in BAD_SVGS.items():
        put(tree, f"docs/brand/bad/{name}", text)
    put(tree, "docs/brand/big.md", "x" * (ops.ARTIFACT_MAX_BYTES + 1))
    got = kinds(tree)
    assert {k: v for k, v in got.items() if "/pieces/" in k} == {
        "docs/brand/pieces/banner.png": "image", "docs/brand/pieces/photo.jpg": "image", "docs/brand/pieces/hero.webp": "image",
        "docs/brand/pieces/mark.svg": "image", "docs/brand/pieces/old.svg": "image", "docs/brand/pieces/refs.svg": "image"}
    assert got["docs/brand/notes.md"] == "markdown" and got["docs/brand/readme.txt"] == "text"
    assert got["docs/brand/accents.md"] == "markdown"
    assert got["docs/brand/fonts/inter.woff2"] == "other" and got["docs/brand/spec.pdf"] == "other"
    assert got["docs/brand/archive.zip"] == "other"
    assert got["docs/brand/not-an-image.png"] == "text" and got["docs/brand/really-an-image.md"] == "image"
    assert got["docs/brand/binary-notes.md"] == "other" and got["docs/brand/big.md"] == "other"
    # an SVG the page may not serve as an image is still text the Desk can show as text
    assert {got[f"docs/brand/bad/{n}"] for n in BAD_SVGS} == {"text"}
    assert set(got.values()) <= set(ops_reads.KINDS)


def test_a_hidden_file_or_folder_is_neither_listed_nor_read(tree):
    put(tree, "docs/brand/.secret.png", PNG)
    put(tree, "docs/brand/.hidden/pic.png", PNG)
    put(tree, "docs/brand/pic.png", PNG)
    assert list(kinds(tree)) == ["docs/brand/pic.png"]
    for rel in ("docs/brand/.secret.png", "docs/brand/.hidden/pic.png"):
        for read in (ops.artifact, ops.artifact_raw):
            with pytest.raises(ops.OpsError) as raised:
                read(str(tree["project"]), rel)
            assert raised.value.code == 2 and "hidden" in str(raised.value), rel


def test_the_raw_read_returns_the_bytes_and_the_media_type_of_an_image(tree):
    path = str(tree["project"])
    for rel, data, media in (("docs/a/one.png", PNG, "image/png"), ("docs/a/two.jpeg", JPEG, "image/jpeg"),
                             ("docs/a/three.webp", WEBP, "image/webp"), ("docs/a/four.svg", SVG.encode(), "image/svg+xml"),
                             ("docs/a/five.svg", SVG_DOCTYPE.encode(), "image/svg+xml"),
                             ("docs/a/six.svg", SVG_FRAGMENTS.encode(), "image/svg+xml"),
                             ("docs/a/no-extension", PNG, "image/png"), ("docs/a/png.md", PNG, "image/png")):
        put(tree, rel, data)
        got = ops.artifact_raw(path, rel)
        assert (got["path"], got["media_type"], got["data"], got["size"]) == (rel, media, data, len(data)), rel
        assert got["modified_at"].endswith("Z")
    assert ops.artifact_raw(path, "./docs//a/one.png")["path"] == "docs/a/one.png"           # normalised first


def test_the_raw_read_refuses_what_the_artifact_read_refuses_and_every_file_that_is_not_an_image(tree, tmp_path):
    path = str(tree["project"])
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.png").write_bytes(PNG)
    os.symlink(outside / "secret.png", tree["project"] / "docs" / "link.png")
    os.symlink(outside, tree["project"] / "docs" / "linked")
    put(tree, "docs/ok.png", PNG)
    put(tree, "docs/notes.md", "# Notes\n")
    put(tree, "docs/spec.pdf", b"%PDF-1.7\n")
    put(tree, "docs/font.woff2", b"wOF2\x00\x00")
    put(tree, "docs/data.bin", b"\xff\xfe\x00\x01")
    put(tree, "docs/archive.zip", b"PK\x03\x04\x00")
    (tree["project"] / "docs" / "folder.png").mkdir()
    (tree["project"] / "README.png").write_bytes(PNG)
    for refused in ("README.png", "../outside/secret.png", "/etc/hosts", "docs", "docs/workbench/runtime.json", "docs/link.png",
                    "docs/linked/secret.png", "docs/folder.png", "", "~/x"):
        with pytest.raises(ops.OpsError) as raised:
            ops.artifact_raw(path, refused)
        assert raised.value.code == 2, refused
    with pytest.raises(ops.OpsError) as missing:
        ops.artifact_raw(path, "docs/nothing.png")
    assert missing.value.code == 1
    sentences = {}
    for rel in ("docs/notes.md", "docs/spec.pdf", "docs/font.woff2", "docs/data.bin", "docs/archive.zip"):
        with pytest.raises(ops.OpsError) as raised:
            ops.artifact_raw(path, rel)
        assert raised.value.code == 2
        sentences[rel] = str(raised.value)
    assert sentences["docs/spec.pdf"] == "docs/spec.pdf is a PDF document, 9 bytes: the Desk shows text, Markdown and images"
    assert "a woff2 font" in sentences["docs/font.woff2"] and "a zip archive" in sentences["docs/archive.zip"]
    assert sentences["docs/data.bin"].startswith("docs/data.bin is a binary file, 4 bytes")
    assert sentences["docs/notes.md"] == "docs/notes.md is text, 8 bytes, not an image: it opens as text"
    for name in BAD_SVGS:
        put(tree, f"docs/bad/{name}", BAD_SVGS[name])
        with pytest.raises(ops.OpsError) as raised:
            ops.artifact_raw(path, f"docs/bad/{name}")
        assert raised.value.code == 2, name


def test_the_raw_read_has_a_size_limit_of_its_own(tree, monkeypatch):
    path = str(tree["project"])
    monkeypatch.setattr(ops_reads, "IMAGE_MAX_BYTES", 100)
    put(tree, "docs/exact.png", PNG[:20] + b"\x00" * 80)
    put(tree, "docs/over.png", PNG[:20] + b"\x00" * 81)
    assert len(ops.artifact_raw(path, "docs/exact.png")["data"]) == 100
    with pytest.raises(ops.OpsError, match="over the 100 the Desk shows as an image") as raised:
        ops.artifact_raw(path, "docs/over.png")
    assert raised.value.code == 2
    assert kinds(tree)["docs/over.png"] == "other"                                          # the list says so before the click
    assert ops_reads.IMAGE_MAX_BYTES == 100 and 25 * 1024 * 1024 == st.load("drop").MAX_BYTES  # the real limit is the drop's


def test_the_text_read_still_refuses_an_image_with_its_own_sentence(tree):
    put(tree, "docs/brand/banner.png", PNG)
    with pytest.raises(ops.OpsError, match="is not UTF-8 text") as raised:
        ops.artifact(str(tree["project"]), "docs/brand/banner.png")
    assert raised.value.code == 2


def test_the_row_of_the_raw_read_is_for_the_page_only(tree):
    row = operations.by_name("artifact-raw")
    assert row["channels"] == ("page",) and row["call"] == "artifact_raw" and row["model"] is False and not row.get("job")
    assert [a["name"] for a in row["args"]] == ["path"]


# --- through the service: the headers --------------------------------------------------------------------------------


def served(tree):
    import test_service as ts
    path = str(tree["project"])
    projects = [{"id": ts.service.project_id(path), "name": "p", "path": path}]
    world = types.SimpleNamespace(svc=ts.service.Service(ops, projects, ts.TOKEN, ts.PORT, None, log=lambda line: None),
                                  projects=projects)
    return ts, world


def test_the_service_answers_the_bytes_with_the_media_type_and_every_header_of_the_rule(tree):
    ts, world = served(tree)
    put(tree, "docs/brand/banner.png", PNG)
    put(tree, "docs/brand/mark.svg", SVG)
    base = f"/api/v1/projects/{world.projects[0]['id']}/artifact/raw"
    status, headers, body = ts.call(world, "GET", base + "?path=docs/brand/banner.png")
    assert (status, body) == (200, PNG) and headers["Content-Type"] == "image/png"
    for name, value in (("Cache-Control", "no-store"), ("X-Content-Type-Options", "nosniff"), ("Content-Disposition", "inline"),
                        ("Content-Security-Policy", ts.service.CSP), ("Referrer-Policy", "no-referrer")):
        assert headers[name] == value, name
    status, headers, body = ts.call(world, "GET", base + "?path=docs/brand/mark.svg")
    assert (status, body) == (200, SVG.encode()) and headers["Content-Type"] == "image/svg+xml"
    assert headers["Content-Security-Policy"] == ts.service.CSP and headers["Content-Disposition"] == "inline"
    # a refusal is the usual JSON with the sentence the page shows
    put(tree, "docs/brand/spec.pdf", b"%PDF-1.7\n")
    status, headers, body = ts.call(world, "GET", base + "?path=docs/brand/spec.pdf")
    assert status == 400 and body["error"] == "usage" and "the Desk shows text, Markdown and images" in body["message"]
    assert headers["Content-Type"] == "application/json; charset=utf-8"
    assert ts.call(world, "GET", base + "?path=docs/brand/missing.png")[0] == 409
    assert ts.call(world, "GET", base + "?path=../AGENTS.md")[0] == 400
    # the token is needed, a query key other than path is refused, the path is capped, POST is not a method of it
    assert ts.call(world, "GET", base + "?path=docs/brand/banner.png", auth=False)[0] == 401
    assert ts.call(world, "GET", base + "?path=docs/brand/banner.png&token=x")[0] == 400
    assert ts.call(world, "GET", base + "?path=" + "a" * 513)[0] == 400
    assert ts.call(world, "GET", base)[0] == 400
    assert ts.call(world, "POST", base, {"path": "docs/brand/banner.png"})[0] == 405
