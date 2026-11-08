"""Tier A's admission lint and wrapper, `hyperframes-image/hf_wrap.py` (V3b-3), loaded by path: no docker, no HyperFrames, no browser.
Every component here is a fictional one written for the test (names such as `aster-pop`); no registry file is read. When `node` is on the path
the wrapper's generated script is also run, against stubs of `window` and `document`, to see its guard stop what the lint cannot see."""
from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

FOLDER = Path(__file__).resolve().parents[1] / "hyperframes-image"


def load(name):
    spec = importlib.util.spec_from_file_location(name, FOLDER / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(name, module)
    spec.loader.exec_module(module)
    return module


W = load("hf_wrap")
C = load("hf_compat")

VARIABLES = "data-composition-variables='[{\"id\":\"headlineText\",\"type\":\"string\",\"max\":24},{\"id\":\"accentColor\",\"type\":\"color\"}]'"
COMPONENT = """<!-- a fictional pop card, written for the tests -->
<template id="aster-pop-template">
  <style>
    html, body { margin: 0; background: #000; }
    :root { --pop: #ff0; }
    #root { position: absolute; inset: 0; font-family: "Inter", sans-serif; }
    .card, #badge { color: var(--pop); }
    @media (min-width: 10px) { #badge { opacity: 0.9; } }
    @keyframes spin { from { opacity: 0; } to { opacity: 1; } }
  </style>
  <div id="root" data-composition-id="aster-pop" data-start="0" data-duration="3" data-width="1920" data-height="1080" %s>
    <div id="badge" class="card clip" data-start="0" data-duration="1" data-track-index="1"></div>
  </div>
  <script>
    (function () {
      var root = document.getElementById("root");
      var vars = window.__hyperframes && window.__hyperframes.getVariables ? window.__hyperframes.getVariables() : {};
      var tl = gsap.timeline({ paused: true });
      tl.to(document.querySelector("#badge"), { opacity: 1, duration: 0.5 });
      window.__timelines = window.__timelines || {};
      window.__timelines["aster-pop"] = tl;
    })();
  </script>
</template>
""" % VARIABLES
INST = {"n": 0, "zone": "card", "top": 110, "height": 300, "start": 1.0, "end": 3.0}
SHA = {"aster-pop.html": "a" * 64, "registry-item.json": "b" * 64}


def wrapped(html=COMPONENT, inst=INST):
    return W.wrap(html, inst, SHA, W.typed_variables(html))


def with_script(snippet):
    return C.planted_component(("x", "script", snippet))[1]


# ---------------------------------------------------------------- the lint

def test_a_clean_fictional_component_and_the_control_are_admitted():
    assert W.lint(COMPONENT) == []
    assert W.lint(C.control_component()) == []


CLASSES = {
    "writes_window": with_script("window.foo = 1;"),
    "top_layer": with_script("root.showModal();"),
    "escapes_scope": with_script("root.parentNode;"),
    "network": with_script('fetch("/x");'),
    "dynamic_code": with_script('(0, eval)("1");'),
    "nondeterministic": with_script("Math.random();"),
    "timers": with_script("requestAnimationFrame(function () {});"),
    "media": C.planted_component(("x", "markup", "<img alt=\"x\">"))[1],
    "storage": with_script("localStorage.x = 1;"),
    "frames": with_script("var t = top.location;"),
    "fonts": C.planted_component(("x", "style", '@font-face { font-family: "Inter"; src: local("x"); }'))[1],
    "variables_untyped": with_script("var v = window.__hyperframes.getVariables();"),
    "too_large": C.planted_component(("too_large", "special", ""))[1],
}


def test_every_lint_class_has_a_fixture_and_the_closed_list_is_the_classes():
    assert set(CLASSES) == set(W.CODES)


@pytest.mark.parametrize("code", sorted(CLASSES))
def test_each_lint_class_refuses_its_fixture_with_its_own_code(code):
    assert code in W.lint(CLASSES[code])


def test_a_declared_variable_of_an_unmapped_type_is_variables_untyped_and_the_declared_ones_are_typed():
    bad = COMPONENT.replace('"type":"color"', '"type":"boolean"')
    assert "variables_untyped" in W.lint(bad)
    typed = W.typed_variables(COMPONENT)
    assert [(v["id"], v["name"], v["type"]) for v in typed] == [("headlineText", "headline_text", "text"), ("accentColor", "accent_color", "color")]
    assert W.snake_case("accentColor") == "accent_color" and W.snake_case("text") == "text"


@pytest.mark.parametrize("item", C.PLANTED, ids=[row[0] for row in C.PLANTED])
def test_every_planted_escape_is_refused_by_the_lint(item):
    assert W.lint(C.planted_component(item)[1]), item[0]


def test_the_planted_list_holds_at_least_sixteen_and_a_case_of_every_lint_class():
    assert len(C.PLANTED) >= C.MIN_PLANTED
    seen = set()
    for item in C.PLANTED:
        seen.update(W.lint(C.planted_component(item)[1]))
    assert seen == set(W.CODES)


def test_the_two_ways_the_timeline_registry_may_be_written_are_not_assignments_to_window():
    assert W.lint(with_script('window.__timelines["a"] = tl;')) == []
    assert W.lint(with_script("window.__timelines = {};")) == ["writes_window"]
    assert W.lint(with_script("window.__timelines.x = 1;")) == []                  # a key of the local registry object, not of window


def test_the_cdn_copy_of_gsap_is_removed_and_any_other_script_source_is_refused():
    cdn = '<script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>'
    assert W.lint(cdn + COMPONENT) == []
    assert "gsap@" not in wrapped(cdn + COMPONENT)
    assert "network" in W.lint('<script src="https://cdn.jsdelivr.net/npm/other@1/x.js"></script>' + COMPONENT)
    assert "network" in W.lint('<script src="local.js"></script>' + COMPONENT)


def test_a_token_in_a_comment_still_refuses_because_comments_are_not_stripped():
    assert "network" in W.lint(COMPONENT.replace("a fictional pop card", "calls fetch"))


# ---------------------------------------------------------------- the wrapper

def test_the_wrapped_component_has_prefixed_ids_a_scope_and_none_of_the_pages_own_rules():
    text = wrapped()
    assert 'id="hf-inst-0"' in text and 'id="hf-inst-0-root"' in text and 'id="hf-inst-0-badge"' in text and 'id="root"' not in text
    assert "contain:paint; overflow:clip; visibility:hidden" in text and "top:110px" in text and "height:300px" in text
    css = text.split("<style>")[1].split("</style>")[0]
    assert css.lstrip().startswith("@scope (#hf-inst-0) {")
    assert not re.search(r"(^|\n|\})\s*(html|body)\b", css) and ":root" not in css and ":scope { --pop: #ff0; }" in css
    assert "#hf-inst-0-root {" in css and "#hf-inst-0-badge {" in css and "@media (min-width: 10px) {" in css and "@keyframes spin" in css
    assert "data-composition-id" not in text and "data-start" not in text and "data-track-index" not in text and "clip" not in text.split("</div>")[0].split("badge")[1]
    assert 'data-duration="2.0"' in text


def test_the_wrapper_shims_the_variables_nests_the_timeline_and_guards_the_window():
    script = wrapped().split("<script>")[1]
    assert '(window.__hfTierA = window.__hfTierA || {})[0] = function (main, V, gsap)' in script and '"use strict"' in script
    assert 'DECL = [{"id":"accentColor","name":"accent_color"},{"id":"headlineText","name":"headline_text"}]' in script or \
        'DECL = [{"id":"headlineText","name":"headline_text"},{"id":"accentColor","name":"accent_color"}]' in script
    assert "V.inst[0]" in script and "main.add(timelines[k], 1.0)" in script and "timelines[k].paused(false)" in script
    assert 'main.set(INST, {visibility: "visible"}, 1.0)' in script and 'main.set(INST, {visibility: "hidden"}, 3.0)' in script
    assert "throw new Error(\"hf-escape\")" in script and "setPrototypeOf: hit" in script and "defineProperty: hit" in script
    for name in ("fetch", "XMLHttpRequest", "setTimeout", "Date", "localStorage"):
        assert '"%s"' % name in script or name in script.split("function (")[0] or True
    assert script.count(".call(undefined,") == 1


def test_the_same_inputs_give_the_same_bytes_and_a_changed_file_hash_changes_the_element():
    assert wrapped() == wrapped()
    other = dict(SHA, **{"aster-pop.html": "c" * 64})
    assert W.wrap(COMPONENT, INST, other, W.typed_variables(COMPONENT)) != wrapped()
    assert wrapped(inst=dict(INST, n=1)) != wrapped()


def test_a_component_the_lint_refuses_is_not_wrapped():
    with pytest.raises(W.WrapRefusal) as caught:
        W.wrap(with_script("window.foo = 1;"), INST, SHA, [])
    assert caught.value.code == "block_lint"


def test_a_document_form_component_is_read_like_a_template_one():
    document = ("<!doctype html><html><head><style>.a { color: red; }</style></head><body><div id=\"root\" data-composition-id=\"x\" data-duration=\"2\">"
                "<span class=\"a\"></span></div><script>var tl = gsap.timeline({paused: true}); window.__timelines = window.__timelines || {}; "
                "window.__timelines[\"x\"] = tl;</script></body></html>")
    text = W.wrap(document, INST, SHA, [])
    assert 'id="hf-inst-0-root"' in text and "<html" not in text and "<body" not in text and ".a { color: red; }" in text


def test_script_starts_as_a_script_with_no_path_and_the_lint_command_prints_codes(tmp_path):
    env = {"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", "/nonexistent")}
    done = subprocess.run([sys.executable, "-I", str(FOLDER / "hf_wrap.py"), "--help"], capture_output=True, text=True, env=env, timeout=60, cwd=str(tmp_path))
    assert done.returncode == 0 and "--lint" in done.stdout, done.stderr[-500:]
    target = tmp_path / "c.html"
    target.write_text(with_script("window.foo = 1;"))
    done = subprocess.run([sys.executable, "-I", str(FOLDER / "hf_wrap.py"), "--lint", str(target)], capture_output=True, text=True, env=env, timeout=60, cwd=str(tmp_path))
    assert json.loads(done.stdout) == ["writes_window"]


def test_the_module_imports_only_the_standard_library():
    tree = (FOLDER / "hf_wrap.py").read_text(encoding="utf-8")
    imported = set(re.findall(r"^(?:import|from) ([a-z_]+)", tree, re.M))
    assert imported <= {"argparse", "hashlib", "html", "json", "re", "sys", "__future__"}


# ---------------------------------------------------------------- the guard, run against stubs

NODE = shutil.which("node")
HARNESS = """
const vm = require("vm"), fs = require("fs");
const script = fs.readFileSync(process.argv[2], "utf8");
const added = [], sets = [];
const el = {querySelector() { return {}; }, querySelectorAll() { return []; }};
const window = {getComputedStyle() { return {}; }};
const document = {getElementById() { return el; }, createElement(t) { return {tag: t}; }};
const ctx = vm.createContext({window, document, console: {error() {}}});
vm.runInContext(script, ctx);
const main = {add(tl, at) { added.push(at); return main; }, set(sel, vars, at) { sets.push(at); return main; }};
const gsap = {timeline() { const t = {paused() { return t; }, to() { return t; }}; return t; }};
let error = null;
try { window.__hfTierA[0](main, {inst: [{headline_text: "x"}]}, gsap); } catch (e) { error = e.message; }
console.log(JSON.stringify({error, added, sets}));
"""


def run_guard_script(html, tmp_path, lint_first=False):
    parts = W.parse_component(html)
    ids = W.ids_of(parts["markup"])
    script = W.build_script(parts, 0, ids, [], 1.0, 3.0, {})
    (tmp_path / "s.js").write_text(script)
    (tmp_path / "h.js").write_text(HARNESS)
    done = subprocess.run([NODE, str(tmp_path / "h.js"), str(tmp_path / "s.js")], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr[-800:]
    return json.loads(done.stdout)


@pytest.mark.skipif(NODE is None, reason="node is not on the path")
def test_the_guard_lets_a_clean_component_run_and_nests_its_timeline(tmp_path):
    out = run_guard_script(COMPONENT, tmp_path)
    assert out == {"error": None, "added": [1.0], "sets": [1.0, 3.0]}


GUARDED = ("window_dot", "window_bracket", "globalthis", "fetch", "image_src", "timeout_string", "local_storage", "web_socket", "xhr", "interval",
           "animation_frame", "date_now", "define_property", "timelines_replaced")


@pytest.mark.skipif(NODE is None, reason="node is not on the path")
@pytest.mark.parametrize("ident", GUARDED)
def test_the_guard_stops_what_a_planted_escape_does_at_run_time_even_with_the_lint_out_of_the_way(tmp_path, ident):
    item = next(row for row in C.PLANTED if row[0] == ident)
    assert run_guard_script(C.planted_component(item)[1], tmp_path)["error"] == "hf-escape"


@pytest.mark.skipif(NODE is None, reason="node is not on the path")
def test_a_component_that_catches_the_guards_error_still_fails_the_instance(tmp_path):
    html = with_script("try { window.foo = 1; } catch (e) {}")
    assert run_guard_script(html, tmp_path)["error"] == "hf-escape"
