#!/usr/bin/env python3
"""The compatibility run of tier A (package V3b-3): the admission of registry components, inside the HyperFrames image, with no network.

Run as

    python3 -I /opt/hf-run/hf_compat.py --survey /work/survey --out /work/out [--presets /work/in/presets.json]

`--survey` is a folder the supervisor fetched, mounted read-only: `survey.json` and `<component>/<file>` for every text file of the registry's
`registry/components/*` at the pinned commit. For each component the run decides `admit-candidate` or `refuse:<code>`, from, in this order:
the licence (the image's own copy of the registry's LICENSE file must hash to the Apache-2.0 text we reviewed: `licence_unknown`), the
component's name (`name_invalid`), every file fetched (`bundled_media`), the two files tier A needs (`<name>.html` and `registry-item.json`:
`no_implementation`), its kind from its own registry item (`caption_tier_b_only`: a caption is only ever a reviewed port; `kind_not_supported`),
the admission lint of `hf_wrap.py` (its closed codes), and its parameters (`param_name`).

Before any verdict is written the run tries the PLANTED ESCAPES: more than a dozen fictional components, each doing one thing a block may not
do, and a clean control. The control must be admitted by the lint (a lint that refuses everything proves nothing). Each planted escape must be
refused by the lint or, when the lint admits it, by the Proxy guard of the wrapper, run in the image's browser; one admitted fails the whole run
(`planted_escape_admitted`), and no report is written. Nothing here has an option that skips this step.

The report, `out/compat-report.json`, holds closed codes, hashes, numbers, the component's folder name and the parameters' names and types
(identifiers that passed the parameter-name rule); no registry prose, no author, no description. `result.json` says whether the run finished.
Standard library only.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))

REGISTRY_COMMIT = "b4cc674f7f312e77ded32e0b53006cc0bad6723b"
LICENCE_SHA256 = "4259155fb06f127687ee7b0a8a3682d45132db0f2da26cbc0b7a2d1e796436b8"       # the registry's LICENSE at the pinned commit: Apache-2.0
LICENCE_NAME = "Apache-2.0"
REGISTRY_ROOT = "/opt/hf-registry"
BROWSER = "/opt/chrome/chrome-headless-shell"
SCRATCH = "/scratch"

MAX_FILE_BYTES = 256 * 1024
MAX_TOTAL_BYTES = 20 * 1024 * 1024
MAX_FILES = 2000
MAX_COMPONENTS = 500
TEXT_SUFFIXES = (".html", ".json", ".md", ".css", ".js", ".txt")
NAME = re.compile(r"[a-z][a-z0-9-]{0,39}")
REL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,60}(/[A-Za-z0-9][A-Za-z0-9._-]{0,60}){0,3}")
HEX64, HEX40 = re.compile(r"[0-9a-f]{64}"), re.compile(r"[0-9a-f]{40}")
PARAM_NAME = re.compile(r"[a-z][a-z0-9_]{0,31}")
FILE_NAME = re.compile(r"[a-z][a-z0-9-]{0,30}\.html")
NATURAL_DURATION = 2.5
TEXT_MAX_DEFAULT = 60
NUMBER_RANGE = (0, 1000000000)                      # a declared number with no bounds of its own: assumed, written into the block's parameter
REPORT_NAME, RESULT_NAME = "compat-report.json", "result.json"
OUT_NAMES = (REPORT_NAME, RESULT_NAME)
SURVEY_CODES = ("licence_unknown", "name_invalid", "bundled_media", "no_implementation", "caption_tier_b_only", "kind_not_supported", "param_name")
RUN_CODES = ("survey_invalid", "survey_hash_mismatch", "survey_too_large", "survey_unreadable", "presets_invalid", "control_refused",
             "planted_escape_admitted", "guard_unavailable")
GUARD_TIMEOUT = 30


def _load(name: str):
    """A sibling module, loaded by path: `python3 -I` puts nothing of this folder on the path."""
    path = os.path.join(HERE, name + ".py")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(name, module)
    spec.loader.exec_module(module)
    return module


W = _load("hf_wrap")
LINT_CODES = W.CODES


class RunFailed(Exception):
    def __init__(self, code: str, field: str = ""):
        super().__init__("%s %s" % (code, field))
        self.code, self.field = code, field[:80]


# ---------------------------------------------------------------- the planted escapes

CONTROL = """<template>
<style>.card { position: absolute; font-family: "Inter", sans-serif; }{{STYLE}}</style>
<div id="root" data-composition-id="planted" data-duration="2">{{MARKUP}}<div class="card">Aster</div></div>
<script>
(function () {
  var root = document.getElementById("root");
  var tl = gsap.timeline({ paused: true });
  tl.to(root, { opacity: 1, duration: 1 });
{{SCRIPT}}
  window.__timelines = window.__timelines || {};
  window.__timelines["planted"] = tl;
})();
</script>
</template>
"""

# (id, where, snippet, expected lint code, acts at run time): a fictional component doing one thing a block may not do. `where` is script, markup,
# style or special. The lint must refuse each one WITH its expected code; the ones that act at run time must also be stopped by the guard, run in
# the image's browser with the lint out of the way.
PLANTED = (
    ("window_dot", "script", "window.foo = 1;", "writes_window", True),
    ("window_bracket", "script", 'window["foo"] = 1;', "writes_window", True),
    ("globalthis", "script", "globalThis.x = 1;", "writes_window", True),
    ("indirect_eval", "script", '(0, eval)("1");', "dynamic_code", False),
    ("body_parent", "script", "document.body.parentNode;", "escapes_scope", False),
    ("closest", "script", 'root.closest("body");', "escapes_scope", False),
    ("root_node", "script", "root.getRootNode();", "escapes_scope", False),
    ("show_modal", "script", "dialog.showModal();", "top_layer", False),
    ("fullscreen", "script", "root.requestFullscreen();", "top_layer", False),
    ("fetch", "script", 'fetch("/x");', "network", True),
    ("image_src", "script", 'new Image().src = "//x";', "media", True),
    ("timeout_string", "script", 'setTimeout("x", 1);', "dynamic_code", True),
    ("random", "script", "Math.random();", "nondeterministic", True),
    ("local_storage", "script", "localStorage.x = 1;", "storage", True),
    ("top_location", "script", "var t = top.location;", "frames", False),
    ("prototype_of_window", "script", "Object.getPrototypeOf(window).x = 1;", "writes_window", False),
    ("web_socket", "script", 'new WebSocket("wss://x.example/");', "network", True),
    ("xhr", "script", "new XMLHttpRequest();", "network", True),
    ("date_now", "script", "var d = Date.now();", "nondeterministic", True),
    ("animation_frame", "script", "requestAnimationFrame(function () {});", "timers", True),
    ("interval", "script", "setInterval(function () {}, 5);", "timers", True),
    ("constructor_chain", "script", '({}).constructor.constructor("return 1")();', "dynamic_code", False),
    ("inner_html", "script", 'root.innerHTML = "<b>x</b>";', "dynamic_code", False),
    ("cookie", "script", 'document.cookie = "a=1";', "storage", False),
    ("parent_post", "script", 'parent.postMessage("x", "*");', "frames", False),
    ("opener", "script", "var o = opener;", "frames", False),
    ("timelines_replaced", "script", "window.__timelines = {};", "writes_window", True),
    ("define_property", "script", 'Object.defineProperty(window, "x", { value: 1 });', "writes_window", True),
    ("dynamic_import", "script", 'import("x");', "network", False),
    ("beacon", "script", 'navigator.sendBeacon("/x");', "network", False),
    ("canvas_font", "script", 'var f = "16px Papyrus";', "fonts", False),
    ("untyped_variables", "script", "var v = window.__hyperframes.getVariables();", "variables_untyped", False),
    ("timelines_key_call", "script", "window.__timelines[Math.random()] = tl;", "nondeterministic", False),
    ("gsap_random", "script", "var r = gsap.utils.random(1, 2);", "gsap_api", False),
    ("gsap_delayed", "script", "gsap.delayedCall(1, function () {});", "gsap_api", False),
    ("gsap_global_tween", "script", "gsap.to(root, { x: 1 });", "gsap_api", False),
    ("random_string", "script", 'tl.to(root, { x: "random(1, 5)" });', "nondeterministic", False),
    ("unicode_escape", "script", 'var f = "\\u0066etch";', "dynamic_code", False),
    ("comment_split", "script", "window/**/.foo = 1;", "writes_window", True),
    ("computed_key", "script", 'var p = root["par" + "entNode"];', "dynamic_code", False),
    ("variable_key", "script", "var p = root[k];", "dynamic_code", False),
    ("unbalanced", "script", "}); var a = 1;", "unbalanced", False),
    ("prototype_write", "script", "Object.prototype.x = 1;", "writes_window", False),
    ("img", "markup", '<img alt="x">', "media", False),
    ("iframe", "markup", "<iframe></iframe>", "media", False),
    ("link", "markup", '<link rel="stylesheet" href="https://x.example/a.css">', "network", False),
    ("video", "markup", "<video></video>", "media", False),
    ("audio", "markup", "<audio></audio>", "media", False),
    ("canvas", "markup", "<canvas></canvas>", "media", False),
    ("object", "markup", "<object></object>", "media", False),
    ("embed", "markup", "<embed>", "media", False),
    ("src_scheme", "markup", '<div src="https://x.example/a"></div>', "network", False),
    ("inline_handler", "markup", '<div onclick="x()"></div>', "dynamic_code", False),
    ("dialog", "markup", "<dialog open>x</dialog>", "top_layer", False),
    ("svg_image", "markup", "<svg><image></image></svg>", "media", False),
    ("svg_use_external", "markup", '<svg><use href="x.svg#a"></use></svg>', "network", False),
    ("meta_refresh", "markup", '<meta http-equiv="refresh" content="0">', "media", False),
    ("css_import", "style", '@import "x.css";', "network", False),
    ("css_url_scheme", "style", ".a { background: url(https://x.example/a.png); }", "network", False),
    ("css_url_slashes", "style", ".a { cursor: url(//x.example/a.cur), auto; }", "network", False),
    ("css_url_relative", "style", ".a { background: url(x.png); }", "network", False),
    ("background_image", "style", ".a { background-image: linear-gradient(red, blue); }", "media", False),
    ("font_face", "style", '@font-face { font-family: "Inter"; src: local("x"); }', "fonts", False),
    ("font_family", "style", '.a { font-family: "Papyrus", serif; }', "fonts", False),
    ("bad_variable_type", "special", "", "variables_untyped", False),
    ("enum_without_options", "special", "", "variables_untyped", False),
    ("too_large", "special", "", "too_large", False),
)
MIN_PLANTED = 16


def planted_component(item):
    """(id, html) of one planted escape, built from the control."""
    ident, where, snippet = item[:3]
    html = CONTROL
    fill = {"{{STYLE}}": "", "{{MARKUP}}": "", "{{SCRIPT}}": ""}
    if where == "script":
        fill["{{SCRIPT}}"] = "  " + snippet
    elif where == "markup":
        fill["{{MARKUP}}"] = snippet
    elif where == "style":
        fill["{{STYLE}}"] = "\n" + snippet + "\n"
    for key, value in fill.items():
        html = html.replace(key, value)
    if ident == "bad_variable_type":
        html = html.replace('data-duration="2"', 'data-duration="2" data-composition-variables=\'[{"id":"flag","type":"boolean"}]\'')
    elif ident == "enum_without_options":
        html = html.replace('data-duration="2"', 'data-duration="2" data-composition-variables=\'[{"id":"mode","type":"enum"}]\'')
    elif ident == "too_large":
        html = html.replace("</template>", "<!-- %s -->\n</template>" % ("x" * (W.MAX_BYTES + 1)))
    return ident, html


def control_component() -> str:
    return planted_component(("control", "none", "", None, False))[1]


# ---------------------------------------------------------------- the guard, in the image's browser

GUARD_PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>pending</title>
<script>window.gsap = {timeline: function () { var t = {paused: function () { return t; }, add: function () { return t; }, set: function () { return t; },
  to: function () { return t; }, from: function () { return t; }, fromTo: function () { return t; }, seek: function () { return t; }}; return t; }};</script>
</head><body><div id="stage">
%s
</div><script>
var verdict = "ran";
try {
  var main = gsap.timeline();
  window.__hfTierA[0](main, {inst: [{}]}, gsap);
} catch (e) { verdict = e && e.message === "hf-escape" ? "escaped-refused" : "error"; }
document.title = verdict;
</script></body></html>
"""


def guard_verdict(html: str, browser: str = BROWSER, scratch: str = SCRATCH) -> str:
    """What the wrapper's guard does with `html` when it is run once in the image's headless browser, with no network, from a page in the scratch
    folder: "ran" (the component ran through), "escaped-refused" (the guard stopped it), "error" (another failure), or "unavailable" (the browser
    could not be run or said nothing). The wrapper is built WITHOUT the lint, so a planted escape reaches the guard."""
    inst = {"n": 0, "zone": "card", "top": 0, "height": 100, "start": 0.0, "end": 1.0}
    try:
        text = W.wrap_unchecked(html, inst, {}, W.typed_variables(html))
    except (W.WrapRefusal, ValueError):
        return "unavailable"
    try:
        folder = tempfile.mkdtemp(dir=scratch)
    except OSError:
        return "unavailable"
    try:
        path = os.path.join(folder, "guard.html")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(GUARD_PAGE % text)
        profile = os.path.join(folder, "profile")
        try:
            done = subprocess.run([browser, "--headless", "--no-sandbox", "--disable-gpu", "--user-data-dir=" + profile, "--virtual-time-budget=2000",
                                   "--dump-dom", "file://" + path], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                  timeout=GUARD_TIMEOUT, env={"HOME": folder, "PATH": os.environ.get("PATH", "")})
        except (OSError, subprocess.SubprocessError):
            return "unavailable"
        for verdict in ("ran", "escaped-refused", "error"):
            if ("<title>%s</title>" % verdict).encode() in done.stdout:
                return verdict
        return "unavailable"
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def try_planted(guard=guard_verdict) -> dict:
    """{"total", "refused", "admitted": [ids], "guarded": n}: every planted escape must be refused by the lint WITH its own expected code, and every
    one that acts at run time must also be stopped by the guard in the image's browser. The guard is proven first: the clean control must pass the
    lint and must run to the end in the browser (`ran`), else the run fails `control_refused` or `guard_unavailable`."""
    if W.lint(control_component()):
        raise RunFailed("control_refused", "control")
    if guard(control_component()) != "ran":
        raise RunFailed("guard_unavailable", "control")
    admitted, refused, guarded = [], 0, 0
    for item in PLANTED:
        ident, html = planted_component(item)
        code, runtime = item[3], item[4]
        if code not in W.lint(html):
            admitted.append(ident)
            continue
        if runtime:
            if guard(html) != "escaped-refused":
                raise RunFailed("guard_unavailable", ident)
            guarded += 1
        refused += 1
    return {"total": len(PLANTED), "refused": refused, "admitted": admitted, "guarded": guarded}


# ---------------------------------------------------------------- the survey

def read_regular(path: str, cap: int):
    """The bytes of a regular file (no link followed) of at most `cap` bytes, or None."""
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError:
        return None
    try:
        info = os.fstat(fd)
        if (info.st_mode & 0o170000) != 0o100000 or info.st_size > cap:
            return None
        with os.fdopen(fd, "rb", closefd=False) as fh:
            return fh.read(cap + 1)
    finally:
        os.close(fd)


def load_survey(folder: str) -> dict:
    raw = read_regular(os.path.join(folder, "survey.json"), 8 * 1024 * 1024)
    if raw is None:
        raise RunFailed("survey_unreadable", "survey.json")
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise RunFailed("survey_invalid", "survey.json") from None
    if not isinstance(doc, dict) or doc.get("commit") != REGISTRY_COMMIT or not isinstance(doc.get("components"), list) or len(doc["components"]) > MAX_COMPONENTS:
        raise RunFailed("survey_invalid", "survey.json")
    total = files = 0
    for comp in doc["components"]:
        if not isinstance(comp, dict) or not isinstance(comp.get("name"), str) or not isinstance(comp.get("files"), list):
            raise RunFailed("survey_invalid", "survey.json")
        for row in comp["files"]:
            if not isinstance(row, dict) or not isinstance(row.get("rel"), str) or not isinstance(row.get("fetched"), bool) \
                    or isinstance(row.get("bytes"), bool) or not isinstance(row.get("bytes"), int) or row["bytes"] < 0 \
                    or not (row.get("sha256") is None or (isinstance(row["sha256"], str) and HEX64.fullmatch(row["sha256"]))) \
                    or row["fetched"] != (row.get("sha256") is not None):
                raise RunFailed("survey_invalid", "survey.json")
            files += 1
            total += row["bytes"] if row["fetched"] else 0
    if files > MAX_FILES or total > MAX_TOTAL_BYTES:
        raise RunFailed("survey_too_large", "survey.json")
    return doc


def licence_known(root: str = REGISTRY_ROOT) -> bool:
    raw = read_regular(os.path.join(root, "LICENSE"), 1024 * 1024)
    return raw is not None and hashlib.sha256(raw).hexdigest() == LICENCE_SHA256


def read_component_files(folder: str, comp: dict) -> dict:
    """{rel: bytes} of the fetched files of one component, each checked against the survey's size and sha256 (a difference fails the run:
    `survey_hash_mismatch`, the survey was altered after it was written). The component's name was checked first."""
    out = {}
    for row in comp["files"]:
        if not row["fetched"]:
            continue
        rel = row["rel"]
        if not REL.fullmatch(rel):
            continue
        data = read_regular(os.path.join(folder, comp["name"], rel), MAX_FILE_BYTES)
        if data is None or len(data) != row["bytes"] or hashlib.sha256(data).hexdigest() != row["sha256"]:
            raise RunFailed("survey_hash_mismatch", "%s/%s" % (comp["name"], rel))
        out[rel] = data
    return out


def kind_of(name: str, item) -> str:
    """"overlay", "caption" or "unsupported" from the component's own registry item."""
    tags = [t.lower() for t in item.get("tags", []) if isinstance(t, str)] if isinstance(item.get("tags"), list) else []
    if name.startswith("caption") or "caption" in tags or "captions" in tags:
        return "caption"
    kind = item.get("type")
    return "overlay" if isinstance(kind, str) and kind.lower().endswith("component") else "unsupported"


def natural_duration(html: str) -> float:
    found = re.search(r"data-duration\s*=\s*[\"']?([0-9]+(?:\.[0-9]+)?)", html)
    if found:
        value = float(found.group(1))
        if 0.2 <= value <= 60:
            return value
    return NATURAL_DURATION


def param_specs(variables: list):
    """({param name: spec}, ok) from the typed variables: names and types by the 7.5 rules. ok is False when a name is not a parameter name
    or two variables share one."""
    specs = {}
    for var in variables:
        name, declared = var["name"], var["declared"]
        if not PARAM_NAME.fullmatch(name) or name in specs:
            return {}, False
        spec = {"type": var["type"]}
        if var["type"] == "choice":
            spec["values"] = list(var["values"])
            if declared.get("default") in var["values"]:
                spec["default"] = declared["default"]
        elif var["type"] == "text":
            maximum = declared.get("max", declared.get("maxLength"))
            spec["max"] = maximum if isinstance(maximum, int) and not isinstance(maximum, bool) and 1 <= maximum <= 240 else TEXT_MAX_DEFAULT
        elif var["type"] == "number":
            lo, hi = declared.get("min"), declared.get("max")
            good = all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in (lo, hi)) and lo <= hi
            spec["min"], spec["max"] = (lo, hi) if good else NUMBER_RANGE
        if declared.get("required") is True:
            spec["required"] = True
        specs[name] = spec
    return specs, True


def preset_for(params: dict, presets: dict):
    """The first overlay preset (by name) whose parameters include every parameter of the block with the same type and whose required parameters
    are all among the block's; None when there is none."""
    for preset in sorted(presets):
        decl = presets[preset]
        if all(name in decl and decl[name]["type"] == spec["type"] for name, spec in params.items()) \
                and all(name in params for name, spec in decl.items() if spec.get("required")):
            return preset
    return None


def judge(folder: str, comp: dict, presets: dict, licence_ok: bool) -> dict:
    """The report entry of one component."""
    name = comp["name"]
    entry = {"name": name if NAME.fullmatch(name) else "invalid", "files": {}, "bytes": 0, "verdict": "", "dynamic": None, "params": {}, "preset": None,
             "natural_duration": None}
    entry["bytes"] = sum(row["bytes"] for row in comp["files"] if row["fetched"])
    if not licence_ok:
        entry["verdict"] = "refuse:licence_unknown"
        return entry
    if not NAME.fullmatch(name):
        entry["verdict"] = "refuse:name_invalid"
        return entry
    if any(not row["fetched"] for row in comp["files"]):
        entry["verdict"] = "refuse:bundled_media"
        return entry
    files = read_component_files(folder, comp)
    impl, item_name = name + ".html", "registry-item.json"
    if impl not in files or item_name not in files or not FILE_NAME.fullmatch(impl):
        entry["verdict"] = "refuse:no_implementation"
        return entry
    try:
        item = json.loads(files[item_name].decode("utf-8"))
        if not isinstance(item, dict):
            raise ValueError("item")
    except (ValueError, UnicodeDecodeError):
        entry["verdict"] = "refuse:kind_not_supported"
        return entry
    kind = kind_of(name, item)
    if kind != "overlay":
        entry["verdict"] = "refuse:caption_tier_b_only" if kind == "caption" else "refuse:kind_not_supported"
        return entry
    html = files[impl].decode("utf-8", "replace")
    codes = W.lint(html)
    if codes:
        entry["verdict"] = "refuse:" + codes[0]
        return entry
    params, ok = param_specs(W.typed_variables(html))
    if not ok:
        entry["verdict"] = "refuse:param_name"
        return entry
    entry["files"] = {rel: hashlib.sha256(files[rel]).hexdigest() for rel in (impl, item_name)}
    entry.update(verdict="admit-candidate", params=params, preset=preset_for(params, presets), natural_duration=natural_duration(html))
    return entry


# ---------------------------------------------------------------- the report

def check_report(doc) -> dict:
    """The report as a closed document: raises ValueError for anything outside the forms below (the host reads the container's file with
    this)."""
    def bad():
        raise ValueError("compat report")
    if not isinstance(doc, dict) or set(doc) != {"schema", "commit", "licence_sha256", "planted", "components"} or doc["schema"] != 1 \
            or doc["commit"] != REGISTRY_COMMIT or not isinstance(doc["licence_sha256"], str) or not (HEX64.fullmatch(doc["licence_sha256"]) or doc["licence_sha256"] == ""):
        bad()
    planted = doc["planted"]
    if not isinstance(planted, dict) or set(planted) != {"total", "refused", "guarded"} or not all(type(v) is int and v >= 0 for v in planted.values()) \
            or planted["refused"] != planted["total"] or planted["total"] < MIN_PLANTED:
        bad()
    rows, comps = [], doc["components"]
    if not isinstance(comps, list) or len(comps) > MAX_COMPONENTS:
        bad()
    keys = {"name", "files", "bytes", "verdict", "dynamic", "params", "preset", "natural_duration"}
    for comp in comps:
        if not isinstance(comp, dict) or set(comp) != keys or not isinstance(comp["name"], str) or not (NAME.fullmatch(comp["name"]) or comp["name"] == "invalid"):
            bad()
        if type(comp["bytes"]) is not int or comp["bytes"] < 0 or comp["dynamic"] is not None:
            bad()
        verdict = comp["verdict"]
        allowed = {"admit-candidate"} | {"refuse:" + c for c in SURVEY_CODES + LINT_CODES}
        if verdict not in allowed or not isinstance(comp["files"], dict) or not isinstance(comp["params"], dict):
            bad()
        if not all(isinstance(k, str) and REL.fullmatch(k) and isinstance(v, str) and HEX64.fullmatch(v) for k, v in comp["files"].items()):
            bad()
        if verdict == "admit-candidate":
            if len(comp["files"]) != 2 or not isinstance(comp["natural_duration"], (int, float)) or isinstance(comp["natural_duration"], bool) \
                    or not (comp["preset"] is None or (isinstance(comp["preset"], str) and re.fullmatch(r"[a-z][a-z0-9_]{0,31}", comp["preset"]))):
                bad()
            for pname, spec in comp["params"].items():
                if not PARAM_NAME.fullmatch(pname) or not isinstance(spec, dict) or spec.get("type") not in ("text", "color", "number", "choice") \
                        or not set(spec) <= {"type", "max", "min", "required", "values", "default"}:
                    bad()
                if spec["type"] == "choice" and (not isinstance(spec.get("values"), list) or not 1 <= len(spec["values"]) <= W.CHOICE_MAX
                                                 or not all(isinstance(v, str) and W.CHOICE_VALUE.fullmatch(v) for v in spec["values"])
                                                 or ("default" in spec and spec["default"] not in spec["values"])):
                    bad()
        elif comp["files"] or comp["params"] or comp["preset"] is not None or comp["natural_duration"] is not None:
            bad()
        rows.append(comp)
    return doc


def run(survey: str, out: str, presets: dict, registry_root: str = REGISTRY_ROOT, guard=None) -> dict:
    tried = try_planted(guard or guard_verdict)
    if tried["admitted"]:
        raise RunFailed("planted_escape_admitted", tried["admitted"][0])
    doc = load_survey(survey)
    licence_ok = licence_known(registry_root)
    components = [judge(survey, comp, presets, licence_ok) for comp in doc["components"]]
    report = {"schema": 1, "commit": REGISTRY_COMMIT, "licence_sha256": LICENCE_SHA256 if licence_ok else "",
              "planted": {"total": tried["total"], "refused": tried["refused"], "guarded": tried["guarded"]}, "components": sorted(components, key=lambda c: (c["name"], c["verdict"]))}
    check_report(report)
    return report


def write_json(path: str, doc) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, sort_keys=True, indent=1)
        fh.write("\n")


def load_presets(path):
    if not path:
        return {}
    raw = read_regular(path, 1024 * 1024)
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (AttributeError, ValueError, UnicodeDecodeError):
        raise RunFailed("presets_invalid", "presets") from None
    if not isinstance(doc, dict) or not all(isinstance(k, str) and isinstance(v, dict) and all(
            isinstance(n, str) and isinstance(s, dict) and s.get("type") in ("text", "color", "number", "icon", "choice") for n, s in v.items())
            for k, v in doc.items()):
        raise RunFailed("presets_invalid", "presets")
    return doc


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--survey", required=True, help="the survey folder (read only): survey.json and <component>/<file>")
    p.add_argument("--out", required=True, help="an existing folder for compat-report.json and result.json")
    p.add_argument("--presets", help="a JSON file {preset: {parameter: {type, required}}} of the overlay presets, for the preset rule")
    args = p.parse_args(argv)
    try:
        report = run(args.survey, args.out, load_presets(args.presets))
    except RunFailed as err:
        write_json(os.path.join(args.out, RESULT_NAME), {"ok": False, "code": err.code, "field": err.field})
        return 1
    write_json(os.path.join(args.out, REPORT_NAME), report)
    admitted = sum(1 for c in report["components"] if c["verdict"] == "admit-candidate")
    write_json(os.path.join(args.out, RESULT_NAME), {"ok": True, "components": len(report["components"]), "admit_candidates": admitted})
    return 0


if __name__ == "__main__":
    sys.exit(main())
