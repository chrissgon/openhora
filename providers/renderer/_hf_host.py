"""The host page of the second contract: one page per beat of an admitted block, built from the entry's files and our own values.

A block of the second contract (a HyperFrames registry component an admission tool pinned and tested) is a `<template>` component that reads
its variables through the runtime and draws wherever it likes. This module serves it: the runtime's five injected scripts and GSAP from the
image's vendor folder (every hash checked), the component's own files from the image's registry folder (every hash checked, only the two
edits E1 and E2 applied, the reduced escape lint run), our theme's fonts, and one host root that holds the component at the card zone's box.
Nothing is fetched at render time; the page policy allows no connection of any kind.

An edit beyond E1 and E2 does not exist here: any other difference between the served bytes and what the entry pinned (`served_sha256`)
is `block_hash`. A block with no recorded determinism test at the served hashes and at the loaded runtime's hash is `block_not_proven`.

Standard library only.
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import re

import _hf_lint
from _text import Refusal

HOST_VERSION = "1"
CDN_GSAP = '<script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>'
LOCAL_GSAP = '<script src="/h/vendor/gsap.min.js"></script>'
VENDOR_FILES = ("gsap.min.js", "hyperframe.runtime.iife.js", "hyperframe.manifest.json")
SHIMS = ("early_stub.js", "capture_mode_shim.js", "virtual_time_shim.js", "render_mode.js", "bridge.js")
MAX_COMPONENT_FILE = 1 << 20

# The runtime says a composition is seekable; the host's own checks add that the component was mounted into the host root (the runtime renames the
# component's `data-composition-id` while it mounts, so the root is looked at by its children) and that no font is still loading.
READY_JS = ('!!(window.__hf && typeof window.__hf.seek === "function" && window.__hf.duration > 0) && '
            '!!document.querySelector("#oh-host > *") && document.fonts.status === "loaded"')

FONT_FORMAT = {"ttf": "truetype", "otf": "opentype", "woff": "woff", "woff2": "woff2"}
THEME_FONT_VARS = re.compile(r"font:(display|text|mono)")
CSS_PROP = re.compile(r"--[a-z][a-z0-9-]{0,40}")
CSS_VALUE = re.compile(r"[#A-Za-z0-9 ._%+-]{1,60}")
E2 = re.compile(r"E2:([A-Za-z][A-Za-z0-9 ]{0,40})")


def runtime_dir(here: str) -> str:
    """The folder of the pins and the shims: `hf-runtime/` next to the renderer's code, or another folder in test mode only (RENDERER_TEST=1 and
    RENDERER_HF_RUNTIME_DIR), the pattern of `_assets.fonts_dir`. Nothing else turns the override on."""
    if os.environ.get("RENDERER_TEST") == "1" and os.environ.get("RENDERER_HF_RUNTIME_DIR"):
        return os.environ["RENDERER_HF_RUNTIME_DIR"]
    return os.path.join(here, "hf-runtime")


def test_registry_dir():
    """The folder of registry files a live test mounts read-only over the image's `/opt/renderer/hf-registry`: only in test mode (RENDERER_TEST=1 and
    RENDERER_HF_REGISTRY_DIR), an absolute real folder with no link in its path. None otherwise. The render still checks every file against the hash the
    allowlist entry pins, so the folder can only supply files an entry already names."""
    if os.environ.get("RENDERER_TEST") != "1" or not os.environ.get("RENDERER_HF_REGISTRY_DIR"):
        return None
    path = os.environ["RENDERER_HF_REGISTRY_DIR"]
    try:
        ok = os.path.isabs(path) and os.path.isdir(path) and not os.path.islink(path) and os.path.realpath(path) == path
    except OSError:
        ok = False
    if not ok:
        raise Refusal("bad_registry_dir", "registry")
    return path


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _read_hashed(path: str, expected: str, code: str, field: str, limit: int = 8 << 20) -> bytes:
    try:
        with open(path, "rb") as fh:
            raw = fh.read(limit + 1)
    except OSError:
        raise Refusal(code, field) from None
    if len(raw) > limit or _sha256(raw) != expected:
        raise Refusal(code, field)
    return raw


def _sums(path: str) -> dict:
    out = {}
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line and not line.startswith("#"):
                    digest, name = line.split(None, 1)
                    out[name.strip()] = digest
    except (OSError, ValueError):
        raise Refusal("vendor_hash", "sums") from None
    return out


# ---------------------------------------------------------------- the runtime

def load_runtime(vendor_dir: str, shims_dir: str, fps: int, browser_version: str = "") -> dict:
    """The three vendor files and the five shims, each checked against its pin (`vendor_hash` on any difference), the shims' fps filled in.
    Returns {gsap, runtime, shims (the five as served, in order), runtime_sha256}: the sha256 over the gsap, the runtime, the five shims
    as served, the host's version and the browser's version string, so that a change of any of them expires every recorded determinism test."""
    pins_path = os.path.join(os.path.dirname(os.path.abspath(shims_dir)), "npm-pins.json")
    try:
        with open(pins_path, encoding="utf-8") as fh:
            pins = json.load(fh)
        wanted = {os.path.basename(m): d for pkg in pins["packages"] for m, d in pkg["files"].items()}
    except (OSError, ValueError, KeyError, TypeError):
        raise Refusal("vendor_hash", "npm-pins") from None
    vendor = {}
    for name in VENDOR_FILES:
        if name not in wanted:
            raise Refusal("vendor_hash", "vendor:" + name[:40])
        vendor[name] = _read_hashed(os.path.join(vendor_dir, name), wanted[name], "vendor_hash", "vendor:" + name[:40])
    sums = _sums(os.path.join(shims_dir, "SHA256SUMS"))
    shims = []
    for name in SHIMS:
        if name not in sums:
            raise Refusal("vendor_hash", "shims:" + name[:40])
        raw = _read_hashed(os.path.join(shims_dir, name), sums[name], "vendor_hash", "shims:" + name[:40])
        if name == "render_mode.js":
            if raw.count(b"__OH_FPS__") != 1 or not isinstance(fps, int) or not 1 <= fps <= 240:
                raise Refusal("vendor_hash", "shims:" + name[:40])
            raw = raw.replace(b"__OH_FPS__", str(fps).encode("ascii"))
        shims.append(raw)
    h = hashlib.sha256()
    for part in [vendor["gsap.min.js"], vendor["hyperframe.runtime.iife.js"]] + shims + [HOST_VERSION.encode(), str(browser_version).encode("utf-8")]:
        h.update(_sha256(part).encode("ascii") + b"\n")
    return {"gsap": vendor["gsap.min.js"], "runtime": vendor["hyperframe.runtime.iife.js"], "shims": shims, "runtime_sha256": h.hexdigest()}


# ---------------------------------------------------------------- the entry's files

def served_digest(files: dict) -> str:
    """The sha256 over the served files after the edits: the lines `<sha256>  <name>`, sorted by name."""
    return _sha256("".join("%s  %s\n" % (_sha256(files[n]), n) for n in sorted(files)).encode("utf-8"))


def apply_edits(files: dict, edits: list, font_map: dict) -> dict:
    """The entry's edits, nothing else. `E1`: the exact CDN GSAP script line becomes the vendored one (exactly once over the files). `E2:<Family>`:
    the font family name becomes the host's family of the entry's map (`oh-display`, `oh-text`, `oh-mono`), at least once. A count that differs, or
    an edit that is not one of these, is `block_edit`; the caller then compares the result with the pinned digest."""
    out = dict(files)
    for edit in edits:
        if edit == "E1":
            hits = sum(raw.decode("utf-8", "replace").count(CDN_GSAP) for raw in out.values())
            if hits != 1:
                raise Refusal("block_edit", "E1")
            out = {n: raw.decode("utf-8").replace(CDN_GSAP, LOCAL_GSAP).encode("utf-8") if CDN_GSAP.encode() in raw else raw for n, raw in out.items()}
        else:
            m = E2.fullmatch(edit) if isinstance(edit, str) else None
            if m is None or m.group(1) not in font_map:
                raise Refusal("block_edit", str(edit)[:40])
            family = m.group(1)
            rx = re.compile(r"(?<![\w-])%s(?![\w-])" % re.escape(family))
            hits = 0
            replaced = {}
            for n, raw in out.items():
                text, count = rx.subn(font_map[family], raw.decode("utf-8", "replace"))
                hits += count
                replaced[n] = text.encode("utf-8") if count else raw
            if hits == 0:
                raise Refusal("block_edit", str(edit)[:40])
            out = replaced
    return out


def read_entry_files(block: dict, registry: str) -> dict:
    """The entry's files from the registry folder, each checked against the sha256 the entry pinned (`block_hash`)."""
    files = {}
    for name, digest in sorted(block["files"].items()):
        files[name] = _read_hashed(os.path.join(registry, block["component"], name), digest, "block_hash", ("hf:%s" % name)[:80], MAX_COMPONENT_FILE)
    return files


def check_edited(block: dict, registry: str) -> dict:
    """The served files of an entry: read, edited, linted and compared with the pinned digest (`block_hash` on any other difference)."""
    files = apply_edits(read_entry_files(block, registry), block["edits"], block["font_map"])
    _hf_lint.check(files)
    if served_digest(files) != block["served_sha256"]:
        raise Refusal("block_hash", block["name"].replace(":", "-")[:80])
    return files


def prove(block: dict, served_sha256: str, runtime_sha256) -> None:
    """The recorded determinism test must be at these hashes: `block_not_proven` otherwise. `runtime_sha256` None (a dry run, which has no browser to
    name) checks the served hash alone."""
    det = block.get("determinism") or {}
    if det.get("served_sha256") != served_sha256 or (runtime_sha256 is not None and det.get("runtime_sha256") != runtime_sha256) \
            or det.get("runs") != 4 or det.get("blocked") != 0:
        raise Refusal("block_not_proven", block["name"].replace(":", "-")[:80])


# ---------------------------------------------------------------- the values

def declared_variables(files: dict, block: dict) -> list:
    """The variables the component declares: the JSON of `data-composition-variables` on its html element."""
    raw = files[block["implementations"]["hf"]].decode("utf-8")
    m = re.search(r"""data-composition-variables\s*=\s*'([^']*)'""", raw) or re.search(r'''data-composition-variables\s*=\s*"([^"]*)"''', raw)
    if not m:
        return []
    try:
        rows = json.loads(html.unescape(m.group(1)))
    except ValueError:
        raise Refusal("admitted_unbound", "variables") from None
    if not isinstance(rows, list) or not all(isinstance(r, dict) and isinstance(r.get("id"), str) for r in rows):
        raise Refusal("admitted_unbound", "variables")
    return rows


def values_for(block: dict, files: dict, params: dict, colors: dict, fonts: dict) -> tuple:
    """(variables {id: value}, css {--prop: value}) of one beat: every declared variable has a value from `bind` or `fixed`, a theme variable maps to
    a theme role (the default of a property that no parameter is bound to), `--bg` is never mapped. `admitted_unbound` for a declared variable left without a value, a name that is not declared or the `--bg` map;
    `param_out_of_bounds` for a number outside the component's own declared range or of the wrong type."""
    declared = {r["id"]: r for r in declared_variables(files, block)}
    variables, css = {}, {}
    for pname, target in block["bind"].items():
        if pname not in params:
            continue                               # an optional parameter the beat left out: the component's own default stays
        kind, _, name = target.partition(":")
        if kind == "var":
            if name not in declared:
                raise Refusal("admitted_unbound", name[:40])
            variables[name] = params[pname]
        else:
            if not CSS_PROP.fullmatch(name) or name == "--bg":
                raise Refusal("admitted_unbound", name[:40])
            value = str(params[pname])
            if not CSS_VALUE.fullmatch(value):
                raise Refusal("param_out_of_bounds", pname[:40])
            css[name] = colors.get(value, value)       # a palette token (`accent`) is the theme's colour; a hex value stays as it is
    for name, value in block["fixed"].items():
        if name not in declared:
            raise Refusal("admitted_unbound", name[:40])
        variables.setdefault(name, value)
    for name in declared:
        if name not in variables:
            bound = {t.partition(":")[2] for p, t in block["bind"].items() if t.startswith("var:")}
            if name in bound:                      # bound to an optional parameter the beat did not give: the declared default
                variables[name] = declared[name].get("default")
            else:
                raise Refusal("admitted_unbound", name[:40])
    for name, row in declared.items():
        v = variables[name]
        if row.get("type") == "number":
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not (row.get("min", v) <= v <= row.get("max", v)):
                raise Refusal("param_out_of_bounds", name[:40])
        elif row.get("type") == "string" and not isinstance(v, str):
            raise Refusal("param_out_of_bounds", name[:40])
    for prop, role in block["theme_vars"].items():
        if not CSS_PROP.fullmatch(prop) or prop == "--bg":
            raise Refusal("admitted_unbound", str(prop)[:40])
        if prop in css:
            continue                               # a parameter bound to the same property wins over the theme's default for it
        m = THEME_FONT_VARS.fullmatch(role)
        if m:
            css[prop] = fonts[m.group(1)]
        elif role in colors:
            css[prop] = colors[role]
        else:
            raise Refusal("admitted_unbound", str(prop)[:40])
    return variables, css


# ---------------------------------------------------------------- the page

def _esc_script(src: str) -> str:
    """Inline script text that cannot close its own tag or open a comment."""
    return re.sub(r"<!--", r"\\x3C!--", re.sub(r"</script", lambda m: "<\\/" + m.group(0)[2:], src, flags=re.I))


def _tags(parts: list, label: str) -> str:
    return "\n".join("<script>%s\n//# sourceURL=hyperframes://injected/%s/%d</script>" % (_esc_script(p.decode("utf-8")), label, i) for i, p in enumerate(parts))


def theme_fonts(font_serve: dict, edl_fonts: dict, allow: dict = None) -> list:
    """The faces the host declares: [{family, role, path, weight, format}] for each role the theme serves (a role on the system default declares none).
    A role's family `oh-<role>` carries its own file at its own weight and, as the old engine's one family per typeface does (the retired `_hf_compose.font_face_css`),
    the file of every other served role of the same typeface (the allow-list's `family`) at that file's weight, so `var(--font-display)` at
    `var(--weight-text)` picks the text file when the typeface has it (PF-a4g). A weight the typeface does not have is the browser's nearest face among
    that typeface's files only, as on the old engine. `allow` ({id: row}) names the typeface of each role; with none, or a row with no `family`, a role
    declares its own file alone. Nothing new is served: every face is a path `load_fonts` already checked against its sha256."""
    import _assets
    served = {}
    for path in sorted(font_serve):
        m = re.fullmatch(r"/fonts/(display|text|mono)\.(ttf|otf|woff|woff2)", path)
        if m:
            served[m.group(1)] = {"path": path, "weight": str(edl_fonts[m.group(1)]["weight"]), "format": FONT_FORMAT[m.group(2)]}
    typeface = {role: (allow or {}).get(_assets.font_id_of(role, edl_fonts[role].get("id")), {}).get("family") for role in served}
    out = []
    for owner in sorted(served):
        seen = set()
        for role in [owner] + [r for r in sorted(served) if r != owner and typeface[owner] and typeface[r] == typeface[owner]]:
            if served[role]["weight"] in seen:
                continue                                 # the same typeface at the same weight is the same file: one face
            seen.add(served[role]["weight"])
            out.append({"family": "oh-" + owner, "role": owner, "path": served[role]["path"], "weight": served[role]["weight"], "format": served[role]["format"]})
    return out


def box_of(data: dict, face: dict) -> dict:
    """The card zone as the host root's box: top `card_top`, bottom `face.y - gap`, left and right the frame's safe margins."""
    z = data["zones"]
    safe = data["frame"]["safe"]
    top, bottom = z["card_top"], face["y"] - z["gap"]
    return {"x": safe["left"], "y": top, "w": data["frame"]["width"] - safe["left"] - safe["right"], "h": max(0, bottom - top)}


def _composition(files: dict, block: dict) -> tuple:
    """(composition id, the `<template>` inner html) of the component's file."""
    raw = files[block["implementations"]["hf"]].decode("utf-8")
    m = re.search(r"<template\b[^>]*>(.*)</template>", raw, re.S | re.I)
    cid = re.search(r"""data-composition-id\s*=\s*["']([A-Za-z0-9_-]{1,40})["']""", m.group(1)) if m else None
    if not m or not cid:
        raise Refusal("admitted_unbound", "template")
    return cid.group(1), m.group(1)


def build_page(block: dict, files: dict, runtime: dict, variables: dict, css: dict, box: dict, faces: list, duration: float, index: int) -> bytes:
    """The page of one beat at `/h/b<index>/index.html`. The head starts with the three early scripts (the virtual-time shim among them), then the
    vendored GSAP, then the runtime; the component's template is placed with the id the runtime looks for, so it never fetches the component; the host
    root holds it at the box; render mode and the bridge come last."""
    cid, inner = _composition(files, block)
    decl = re.search(r"""data-composition-variables\s*=\s*('[^']*'|"[^"]*")""", files[block["implementations"]["hf"]].decode("utf-8"))
    html_attr = (" data-composition-variables=%s" % decl.group(1)) if decl else ""
    font_css = "".join("@font-face{font-family:%s;src:url(%s) format('%s');font-weight:%s;font-style:normal}" % (f["family"], f["path"], f["format"], f["weight"]) for f in faces)
    style = "".join("%s:%s;" % (k, v) for k, v in sorted(css.items()))
    host_style = "position:absolute;left:%dpx;top:%dpx;width:%dpx;height:%dpx;%s" % (box["x"], box["y"], box["w"], box["h"], style)
    page = (
        "<!doctype html>\n<html lang=\"en\"%s>\n<head>\n<meta charset=\"utf-8\">\n%s\n"
        "<script src=\"/h/vendor/gsap.min.js\"></script>\n%s\n"
        "<style>%shtml,body{margin:0;padding:0;background:transparent}body{position:relative;width:1080px;height:1920px;overflow:hidden}</style>\n</head>\n<body>\n"
        "<template id=\"%s-template\">%s</template>\n"
        "<div id=\"oh-host\" data-composition-id=\"%s\" data-composition-src=\"/h/b%d/%s.html\" data-start=\"0\" data-duration=\"%s\" data-variable-values=\"%s\" style=\"%s\"></div>\n"
        "<script>window.__timelines = window.__timelines || {}; window.__timelines[\"oh-host\"] = gsap.timeline({paused: true});</script>\n%s\n</body>\n</html>\n"
    ) % (html_attr, _tags(runtime["shims"][:3], "early"), _tags([runtime["runtime"]], "runtime"), font_css, cid, inner, cid, index, cid,
         repr(float(duration)), html.escape(json.dumps(variables, ensure_ascii=False, sort_keys=True), quote=True), html.escape(host_style, quote=True),
         _tags(runtime["shims"][3:], "late"))
    return page.encode("utf-8")


def fonts_spec(faces: list, fallbacks: dict = None) -> dict:
    """What the page's font check compares with: the declared faces as [family, weight, style], and the first family of the theme's own system
    fallback of every role that has no face (a theme on the system default draws with those and with no declared face)."""
    have = {f["role"] for f in faces}
    system = sorted({v.split(",")[0].strip().strip("\"'") for role, v in (fallbacks or {}).items() if role not in have})
    return {"faces": [[f["family"], f["weight"], "normal"] for f in faces], "system": system}


# ---------------------------------------------------------------- one render's admitted blocks

def prepare(*, catalogue: dict, engine: str, timeline: dict, data: dict, edl: dict, font_serve: dict, vendor: str, registry: str, shims: str,
            browser_version=None) -> dict:
    """Everything the render needs from the entries of the timeline whose block runs on the second contract: {serve, pages ({key: {entry index: path}}: the key is
    a beat's block name, or "caption" for the caption chunks), ready, fonts, proofs ({block name: {served_sha256, runtime_sha256}}), blocks (names)}. A registry
    component (runtime `hf`) gets a page per beat from `registry`; one of our own ports (runtime `gsap`, PF-a4) gets a page per beat and per caption chunk from
    `_hf_port`, its fragment read from the staged blocks folder by its pin. Refuses before any frame is drawn. `browser_version` None (a dry run: no browser)
    leaves the runtime hash out of the proof."""
    import _assets
    import _blocks
    import _hf_port
    caption_block = _blocks.resolve(catalogue, engine, "caption", None, "edl.captions")
    caption_runtime = _blocks.second_contract_runtime(catalogue, caption_block, engine)
    rows = []                                   # (track, entry index, entry, block, runtime)
    if caption_runtime:
        rows += [("caption", k, e, caption_block, caption_runtime) for k, e in enumerate(timeline["captions"])]
    for k, e in enumerate(timeline["beats"]):
        block = catalogue["blocks"][e["block"]]
        runtime = _blocks.second_contract_runtime(catalogue, block, engine)
        if runtime:
            rows.append(("beat", k, e, block, runtime))
    if not rows:
        return {"serve": {}, "pages": {}, "ready": READY_JS, "fonts": {"faces": [], "system": []}, "proofs": {}, "blocks": []}
    runtime_doc = load_runtime(vendor, shims, edl["fps"], browser_version or "")
    faces = theme_fonts(font_serve, edl["theme"]["fonts"], _assets.font_allowlist() if font_serve else None)
    fonts = {f["role"]: "%s, %s" % (f["family"], data["theme"]["system_fallback"][f["role"]]) for f in faces}
    for role in data["theme"]["font_roles"]:
        fonts.setdefault(role, data["theme"]["system_fallback"][role])
    by_index = {w["index"]: w for w in edl.get("words", [])}
    serve = {"/h/vendor/gsap.min.js": (runtime_doc["gsap"], "text/javascript; charset=utf-8")}
    pages, proofs, checked, names = {}, {}, {}, set()
    for track, k, e, block, runtime in rows:
        name = block["name"]
        if name not in checked:
            if runtime == "gsap":
                fragment = _hf_port.read_fragment(catalogue, block)
                served = _hf_port.served_digest(fragment["raw"])
                prove(block, served, runtime_doc["runtime_sha256"] if browser_version is not None else None)
                checked[name] = fragment
            else:
                files = check_edited(block, registry)
                served = block["served_sha256"]
                prove(block, served, runtime_doc["runtime_sha256"] if browser_version is not None else None)
                checked[name] = files
            proofs[name] = {"served_sha256": served, "runtime_sha256": runtime_doc["runtime_sha256"] if browser_version is not None else ""}
        names.add(name)
        if runtime == "gsap":
            path = "/h/%s%d/index.html" % ("c" if track == "caption" else "b", k)
            serve[path] = (_hf_port.page_for(block=block, fragment=checked[name], runtime=runtime_doc, faces=faces, stacks=fonts, data=data, edl=edl, entry=e,
                                             track=track, index=k, by_index=by_index), "text/html; charset=utf-8")
            pages.setdefault("caption" if track == "caption" else name, {})[k] = path
            continue
        files = checked[name]
        variables, css = values_for(block, files, e["params"], edl["theme"]["colors"], fonts)
        box = box_of(data, e["face"])
        if box["h"] <= 0:
            raise Refusal("admitted_unbound", "box")
        path = "/h/b%d/index.html" % k
        serve[path] = (build_page(block, files, runtime_doc, variables, css, box, faces, block["natural_duration"], k), "text/html; charset=utf-8")
        pages.setdefault(name, {})[k] = path
    return {"serve": serve, "pages": pages, "ready": READY_JS, "fonts": fonts_spec(faces, data["theme"]["system_fallback"]), "proofs": proofs, "blocks": sorted(names)}
