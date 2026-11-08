"""`hyperframes-image/hf_measure.mjs` (package V3b-2) read as text: it runs only inside the HyperFrames image, so no test here starts it. What it may
reach, what it may write, its limits and the refusals it may give are checked against the host's own figures, in the way `test_hf_image.py`
checks the Dockerfile. A syntax check (`node --check`, which runs no program of the page and no HyperFrames command) runs when `node` is on the host."""
from __future__ import annotations

import importlib.util
import json
import math
import re
import shutil
import subprocess

import pytest

import renderer_kit as K
import _hf_gate as G

FOLDER = K.RENDERER / "hyperframes-image"
SCRIPT = FOLDER / "hf_measure.mjs"
TEXT = SCRIPT.read_text(encoding="utf-8")
CODE = "\n".join(line for line in TEXT.splitlines() if not line.lstrip().startswith("//"))     # the comments are not code


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


R = load("hf_render_for_measure_static", FOLDER / "hf_render.py")


def constant(name: str) -> str:
    return re.search(r"^const %s = (.+);$" % name, CODE, re.M).group(1)


def test_it_imports_only_the_file_the_http_and_the_path_modules_and_never_starts_a_process():
    imports = set(re.findall(r'^import .+? from "([^"]+)";', CODE, re.M))
    assert imports == {"node:module", "node:fs", "node:http", "node:path"}
    for banned in ("child_process", "spawn", "execFile", "ev" + "al(", "new Function", "fetch(", "WebSocket", "XMLHttpRequest", "node:net", "node:dns", "node:tls", "node:https", "node:dgram"):
        assert banned not in CODE, banned
    assert not re.search(r"(?<![.\w])ex" + r"ec(Sync)?\(", CODE)                    # a RegExp's own method of that name is not a program


def test_the_only_host_it_names_is_the_loopback_and_the_page_may_request_only_that_origin():
    assert constant("LOOPBACK") == '"127.0.0.1"'
    assert re.findall(r"https?://[^\s\"']+", CODE) == []                                  # every URL is built from LOOPBACK, none is written out
    assert re.findall(r'"https?://" \+ ', CODE) and "setRequestInterception(true)" in CODE and "req.abort()" in CODE
    assert "origin" in CODE and 'url.startsWith(origin) || url.startsWith("data:") || url.startsWith("blob:")' in CODE
    assert 'server.listen(0, LOOPBACK' in CODE


def test_it_reads_only_the_images_hyperframes_folder_the_project_and_its_arguments():
    absolute = set(re.findall(r'"(/opt[^"]*)"', CODE))
    assert absolute == {"/opt/hf", "/opt/hf/node_modules/hyperframes/dist/hyperframe.runtime.iife.js", "/opt/hf/package.json"} or all(p.startswith("/opt/hf") for p in absolute)
    assert all(p == "/opt/hf" or p.startswith("/opt/hf/") for p in absolute)
    for other in ("/work", "/etc", "/tmp", "/home", "/proc", "/sys", "/root"):
        assert '"%s' % other not in CODE
    reads = re.findall(r"fs\.(?:readFileSync|existsSync|statSync|createReadStream|realpathSync)\(([^)]*)\)", CODE)
    assert reads and all(any(token in arg for token in ("RUNTIME_FILE", "projectArg", "root", "file", "path.join(root")) for arg in reads)


def test_it_writes_only_to_the_boxes_path_it_was_given():
    writes = re.findall(r"fs\.(?:writeFileSync|writeSync|appendFileSync|mkdirSync|unlinkSync|rmSync|copyFileSync|renameSync)\(([^,)]*)", CODE)
    assert writes and set(writes) == {"outPath"}


def test_it_reads_one_environment_variable_the_browsers_path():
    assert set(re.findall(r"process\.env\.([A-Z_]+)", CODE)) == {"PUPPETEER_EXECUTABLE_PATH"} and "process.env[" not in CODE and "process.env," not in CODE


def test_its_limits_are_constants_and_the_same_figures_as_the_gate_and_the_inner_entry():
    assert int(constant("MAX_BOXES_PER_FRAME")) == G.MAX_BOXES_PER_FRAME == 2000
    assert math.prod(int(part) for part in constant("MAX_OUT_BYTES").split("*")) == G.BOXES_MAX_BYTES == R.BOXES_MAX_BYTES == 64 * 1024 ** 2
    assert int(constant("FONT_EVERY")) == 30
    assert re.findall(r'"([A-Za-z ]+)"', constant("ALLOWED_FAMILIES")) == list(G.ALLOWED_FAMILIES)


def test_the_refusals_it_can_write_are_the_ones_the_inner_entry_passes_on():
    codes = set(re.findall(r'(?:new Refusal|writeRefusal)\("([a-z_]+)"', CODE))
    assert codes == set(R.MEASURE_REFUSALS)


def test_the_output_is_the_shape_the_gate_reads_with_sorted_keys():
    assert "'{\"fonts\":'" in CODE and "',\"fps\":'" in CODE and "',\"frames\":'" in CODE and "',\"per_frame\":['" in CODE and "'],\"ready_ms\":'" in CODE and "',\"schema\":1}'" in CODE
    assert "{ glyph, h: R1(height), key, w: R1(width), x: R1(left), y: R1(top), zone }" in CODE        # keys in alphabetical order, rounded to 0.1 px
    assert "R1 = (x) => Math.round(x * 10) / 10" in CODE and "{ custom: true, family }" in CODE


def test_it_seeks_each_frame_with_the_renderers_own_function_and_measures_gsap_instances_and_renderat_pages():
    for needle in ("window.__player.renderSeek(t)", 'document.querySelectorAll(".hf-inst")', 'document.querySelectorAll("iframe.hf-ra")', '"[data-zone]"',
                   "createRange()", "getClientRects()", "getComputedStyle", "CSS.getPlatformFontsForNode", "isCustomFont !== true", "data-hf-zone", "data-hf-key"):
        assert needle in CODE, needle
    assert "Math.max(r.left, clip.left)" in CODE and "Math.min(r.bottom, clip.bottom)" in CODE            # the elements are clipped to the instance, the glyph rects are not
    assert CODE.index('glyphs(inst, () => zone, key, 0, 0)') > CODE.index("Math.min(r.bottom, clip.bottom)")


def test_a_page_error_a_console_error_or_a_failed_request_fails_the_measure():
    assert 'page.on("console"' in CODE and 'm.type() === "error"' in CODE and 'page.on("pageerror"' in CODE and 'page.on("requestfailed"' in CODE
    assert "problems.length" in CODE and 'throw new Refusal("measure_failed"' in CODE


def test_the_script_is_listed_in_the_definition_and_the_build_context():
    manifest = __import__("json").loads((FOLDER / "manifest.json").read_text(encoding="utf-8"))
    assert "hf_measure.mjs" in manifest["files"] and "!hf_measure.mjs" in (FOLDER / ".dockerignore").read_text(encoding="utf-8").splitlines()


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not on this host: the syntax check of hf_measure.mjs is skipped")
def test_the_script_has_no_syntax_error():
    done = subprocess.run([shutil.which("node"), "--check", str(SCRIPT)], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr[-800:]


def range_answers(header, size):
    """parseRange run by node on the function's own text (no page, no browser, no HyperFrames)."""
    source = re.search(r"^function parseRange\(.*?^}\n", TEXT, re.S | re.M).group(0)
    done = subprocess.run([shutil.which("node"), "--input-type=module", "-e", source + "\nconsole.log(JSON.stringify(parseRange(%s, %d)));" % (json.dumps(header), size)],
                          capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr[-400:]
    return json.loads(done.stdout)


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not on this host")
@pytest.mark.parametrize("header, size, expect", [
    (None, 100, None), ("bytes=0-", 100, {"start": 0, "end": 99}), ("bytes=10-19", 100, {"start": 10, "end": 19}), ("bytes=90-500", 100, {"start": 90, "end": 99}),
    ("bytes=-10", 100, {"start": 90, "end": 99}), ("bytes=-500", 100, {"start": 0, "end": 99}), ("bytes=100-", 100, "bad"), ("bytes=50-40", 100, "bad"),
    ("bytes=-0", 100, "bad"), ("bytes=-", 100, "bad"), ("bytes=0-1,5-6", 100, "bad"), ("items=0-1", 100, "bad"), ("bytes=0-", 0, "bad")])
def test_a_range_request_gets_one_checked_range_and_a_bad_one_is_refused(header, size, expect):
    assert range_answers(header, size) == expect


def test_the_server_answers_206_with_content_range_and_416_for_a_bad_range_and_waits_from_node():
    assert "res.writeHead(416" in CODE and '"content-range": "bytes " + start' in CODE and "waitForFunction" not in CODE
    assert 'r.resourceType() === "media" && why === "net::ERR_ABORTED"' in CODE


# What the three font files declare, read by node (zlib's brotli) from the files' own name and cmap tables: no font library, no download.
FONT_READER = r"""
import fs from "node:fs"; import zlib from "node:zlib";
const KNOWN=["cmap","head","hhea","hmtx","maxp","name","OS/2","post","cvt ","fpgm","glyf","loca","prep"];
const out = {};
for (const f of process.argv.slice(1)) {
  const b = fs.readFileSync(f); let p = 48; const n = b.readUInt16BE(12); const tabs = [];
  const base128 = () => { let v = 0; for (let i = 0; i < 5; i++) { const c = b[p++]; v = v * 128 + (c & 127); if (!(c & 128)) break; } return v; };
  for (let i = 0; i < n; i++) {
    const fl = b[p++]; let tag;
    if ((fl & 63) === 63) { tag = b.toString("latin1", p, p + 4); p += 4; } else tag = KNOWN[fl & 63] || "x" + (fl & 63);
    const tv = fl >> 6; const ol = base128(); let tl = ol;
    if (tag === "glyf" || tag === "loca" ? tv === 0 : tv !== 0) tl = base128();
    tabs.push({ tag, len: tl });
  }
  const data = zlib.brotliDecompressSync(b.subarray(p, p + b.readUInt32BE(20))); let o = 0; const T = {};
  for (const t of tabs) { T[t.tag] = data.subarray(o, o + t.len); o += t.len; }
  const nm = T["name"], cnt = nm.readUInt16BE(2), so = nm.readUInt16BE(4), names = {};
  for (let i = 0; i < cnt; i++) {
    const r = 6 + 12 * i, pid = nm.readUInt16BE(r), id = nm.readUInt16BE(r + 6), len = nm.readUInt16BE(r + 8), off = nm.readUInt16BE(r + 10);
    if (pid === 3 && !(id in names)) { const raw = nm.subarray(so + off, so + off + len); let s = ""; for (let k = 0; k < raw.length; k += 2) s += String.fromCharCode(raw.readUInt16BE(k)); names[id] = s; }
  }
  const cm = T["cmap"], set = []; const nt = cm.readUInt16BE(2);
  for (let i = 0; i < nt; i++) {
    const off = cm.readUInt32BE(4 + 8 * i + 4), fmt = cm.readUInt16BE(off);
    if (fmt === 4) { const sc = cm.readUInt16BE(off + 6) / 2, e = off + 14, st0 = e + sc * 2 + 2; for (let k = 0; k < sc; k++) { const end = cm.readUInt16BE(e + 2 * k), st = cm.readUInt16BE(st0 + 2 * k); for (let c = st; c <= end && c < 0xffff; c++) set.push(c); } }
    if (fmt === 12) { const ng = cm.readUInt32BE(off + 12); for (let k = 0; k < ng; k++) { const q = off + 16 + 12 * k, st = cm.readUInt32BE(q), en = cm.readUInt32BE(q + 4); for (let c = st; c <= en; c++) set.push(c); } }
  }
  out[f.split("/").pop()] = { family: names[1], typographic: names[16], cmap: set };
}
console.log(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def font_tables():
    if shutil.which("node") is None:
        pytest.skip("node is not on this host")
    files = sorted(str(p) for p in (K.RENDERER / "assets" / "fonts").glob("*.woff2"))
    done = subprocess.run([shutil.which("node"), "--input-type=module", "-e", FONT_READER, *files], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr[-400:]
    return json.loads(done.stdout)


def test_the_platform_names_are_what_the_three_font_files_declare_and_every_one_maps_to_an_allowed_family(font_tables):
    declared = {name: row["family"] for name, row in font_tables.items()}
    assert declared == {"inter-500.woff2": "Inter Medium", "inter-800.woff2": "Inter ExtraBold", "jetbrains-mono-500.woff2": "JetBrains Mono Medium"}
    assert {row["typographic"] for row in font_tables.values()} == set(G.ALLOWED_FAMILIES)
    table = dict(re.findall(r'"([A-Za-z ]+)": "([A-Za-z ]+)"', constant("PLATFORM_NAMES")))
    for name, family in declared.items():
        assert table[family] in G.ALLOWED_FAMILIES
    assert set(table.values()) == set(G.ALLOWED_FAMILIES) and set(table) >= set(declared.values()) | set(G.ALLOWED_FAMILIES)
    assert set(table) <= set(declared.values()) | set(G.ALLOWED_FAMILIES)                  # nothing else is accepted


def test_every_character_of_the_demo_text_is_in_the_fonts_so_nothing_falls_back_to_a_system_font(font_tables):
    text = K.HF_POST + K.POST + " ".join(w["text"] for w in K.build_transcript(K.SHORT_SENTENCES)["words"]) + " ".join(w["text"] for w in K.build_transcript()["words"])
    needed = {c for c in text if c.isprintable() and not c.isspace()}
    for name, row in font_tables.items():
        if name.startswith("inter"):
            assert {c for c in needed if ord(c) not in set(row["cmap"])} == set(), name
    assert len(needed) > 20


def test_a_font_that_is_not_ours_or_not_custom_is_described_in_the_refusal_in_closed_shapes():
    assert 'note("font", "frame " + frame + " family " + (family || "other") + " custom " + (f.isCustomFont === true) + " glyphs " + f.glyphCount + " in " + what)' in CODE
    assert 'if (!family || f.isCustomFont !== true)' in CODE and 'throw new Refusal("font_not_allowed", "drawn")' in CODE
