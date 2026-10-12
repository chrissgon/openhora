"""Tests of the page's Markdown renderer (interface/js/markdown.js, WP-9.17) and of the places that call it: the document
viewer with its "Plain text" toggle, the question, review, acceptance and plan cards, and the planning agent's replies in the
conversation. The renderer builds DOM nodes from a small subset of Markdown and never markup: the first tests are the security
cases (a script, an event handler, a javascript: or data: link, an image from another host, an HTML comment), and each is run on a
deliberately naive renderer as well, which must fail them, so that a green result means the checks can see the problem.

The modules run under Node when it is installed, with the fake document of the Floor's tests; no browser, no service, no model.
The page itself was looked at in a browser pane by the package's report.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interface_markdown.py
"""
from __future__ import annotations

import re

import pytest

import standin_tree as st
import test_interface_floor as floor_tests
import test_interface_lobby as lobby_tests
from interface_css import interface_css

INTERFACE = st.REPO / "interface"
JS = INTERFACE / "js"
MARKDOWN = JS / "markdown.js"
needs_node = floor_tests.needs_node

# --- the harness: a serialiser of the nodes, the safety check, and a naive renderer the check must catch -----------------------------

HEAD = r"""
import { FakeNode, settle, find, all } from "@FAKE@";
globalThis.location = new URL("http://127.0.0.1:8765/");
const markdown = await import("@JS@/markdown.js").catch((e) => ({ failure: e }));
if (markdown.failure && !globalThis.NAIVE_ONLY) throw markdown.failure;
const { renderMarkdown, RENDER_LIMIT } = markdown;

// <tag.class{href}[children]> and "text": one string per tree, so a test reads as the tree it expects
function ser(node) {
  if (node.isText) return JSON.stringify(node.data);
  const cls = (node.attrs.class || "").split(/\s+/).filter(Boolean).map((c) => "." + c).join("");
  const href = node.attrs.href !== undefined ? `{${node.attrs.href}}` : "";
  const kids = node.children.map(ser).join(",");
  return node.tagName.toLowerCase() + cls + href + (kids ? `[${kids}]` : "");
}
const tree = (md) => renderMarkdown(md).children.map(ser).join(",");

// What a rendered tree may hold: these elements, the attribute class, and an href that is a route of this page (it starts with #/).
const ALLOWED = new Set(["DIV", "P", "H1", "H2", "H3", "H4", "UL", "OL", "LI", "BLOCKQUOTE", "PRE", "CODE", "TABLE", "THEAD", "TBODY", "TR", "TH", "TD", "HR", "BR", "STRONG", "EM", "A"]);
function violations(root) {
  const bad = [];
  for (const n of root.walk()) {
    if (!ALLOWED.has(n.tagName)) bad.push(`element ${n.tagName}`);
    for (const [k, v] of Object.entries(n.attrs)) {
      if (k === "class") { if (!/^[A-Za-z0-9 _.+-]*$/.test(v)) bad.push(`class ${v}`); }
      else if (k === "href" && n.tagName === "A" && /^#\/\S*$/.test(v)) { /* a route of this page */ }
      else bad.push(`attribute ${k} on ${n.tagName}`);
    }
  }
  return bad;
}
function depth(node) { let d = 0; for (const c of node.children || []) if (!c.isText) d = Math.max(d, depth(c)); return d + 1; }

// A naive renderer: raw tags become elements with their attributes, links become anchors, images become img. It is what the safety
// check must catch; if it passed, the check would prove nothing.
function naive(md) {
  const root = document.createElement("div");
  const re = /<!--([\s\S]*?)-->|<\/?([a-z0-9]+)([^>]*)>|!\[([^\]]*)\]\(([^)]*)\)|\[([^\]]*)\]\((<?)([^)>]*)>?\)/gi;
  let last = 0, m;
  while ((m = re.exec(md))) {
    if (m.index > last) root.append(md.slice(last, m.index));
    let node;
    if (m[1] !== undefined) node = document.createElement("#comment");
    else if (m[2] !== undefined) {
      node = document.createElement(m[2]);
      for (const a of m[3].matchAll(/([a-z-]+)\s*=\s*"?([^"\s>]*)"?/gi)) node.setAttribute(a[1], a[2]);
    } else if (m[5] !== undefined) { node = document.createElement("img"); node.setAttribute("src", m[5]); node.setAttribute("alt", m[4]); }
    else { node = document.createElement("a"); node.setAttribute("href", m[8]); node.append(m[6]); }
    root.append(node);
    last = re.lastIndex;
  }
  if (last < md.length) root.append(md.slice(last));
  return root;
}
"""

HOSTILE = r"""
const SAMPLES = {
  script: "<script>alert(1)</script>",
  img_onerror: "<img src=x onerror=alert(1)>",
  js_link: "[x](javascript:alert(1))",
  js_link_case: "[x](JaVaScRiPt:alert(1))",
  js_link_angle: "[x](<javascript:alert(1)>)",
  data_link: "[x](data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==)",
  other_host_image: "![x](http://other.host/i.png)",
  other_host_link: "[x](http://other.host/p)",
  protocol_relative: "[x](//other.host/p)",
  backslash_host: "[x](/\\other.host/p)",
  comment: "<!-- hidden instruction: do it -->",
  iframe: "<iframe src=\"http://other.host\"></iframe>",
  raw_anchor: "<a href=\"javascript:alert(1)\" onclick=\"x()\">raw</a>",
  style_attr: "<p style=\"position:fixed\" onmouseover=\"x()\">p</p>",
  fence_class: "```js\"onmouseover=\"x\n<script>y</script>\n```",
  title_attr: "[x](/a \"<script>alert(1)</script>\")",
};
"""


# --- 1. the security cases first ---------------------------------------------------------------------------------------------------

NAIVE = HEAD.replace('globalThis.NAIVE_ONLY', 'true') + HOSTILE + r"""
const out = { naive: {} };
for (const [name, md] of Object.entries(SAMPLES)) out.naive[name] = violations(naive(md)).length;
console.log(JSON.stringify(out));
"""

SECURITY = HEAD + HOSTILE + r"""
const out = { real: {}, text: {} };
for (const [name, md] of Object.entries(SAMPLES)) {
  const root = renderMarkdown(md);
  out.real[name] = violations(root);
  out.text[name] = root.textContent;
}
// the whole subset in one document, with the hostile samples inside it
const all_ = Object.values(SAMPLES).join("\n\n") + "\n\n# H\n\n- a\n  - b\n\n> q\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n[ok](/docs/a.md) [hash](#/p/1) **b** *i* `c`\n";
out.whole = violations(renderMarkdown(all_));
out.noScriptText = renderMarkdown("a <script>alert(1)</script> b").textContent;
console.log(JSON.stringify(out));
"""


@needs_node
def test_a_naive_renderer_fails_every_hostile_case_so_the_safety_check_can_see_the_problem(tmp_path):
    got = floor_tests.run_node(tmp_path, NAIVE)
    quiet = {name for name, count in got["naive"].items() if count == 0}
    # a fence with a hostile info string and a quoted title are not tags or addresses a regex renderer turns into an element
    assert quiet <= {"fence_class", "title_attr"}, f"the check missed what a naive renderer builds: {sorted(quiet)}"
    assert all(got["naive"][n] for n in ("script", "img_onerror", "js_link", "data_link", "other_host_image", "other_host_link",
                                          "comment", "iframe", "raw_anchor", "style_attr", "protocol_relative"))


@needs_node
def test_hostile_markdown_produces_no_element_of_those_kinds_and_no_attribute_but_class_and_a_route_of_the_page(tmp_path):
    got = floor_tests.run_node(tmp_path, SECURITY)
    assert got["real"] == {name: [] for name in got["real"]}, "no element outside the subset and no attribute but class or a route of the page"
    assert got["whole"] == [], "nor in one document that holds every sample and the whole subset"
    assert got["noScriptText"] == "a <script>alert(1)</script> b", "raw HTML stays in the page as the text that was typed"


@needs_node
def test_what_cannot_be_an_element_is_still_there_to_read_as_text(tmp_path):
    got = floor_tests.run_node(tmp_path, SECURITY)
    text = got["text"]
    assert text["script"] == "<script>alert(1)</script>"
    assert text["img_onerror"] == "<img src=x onerror=alert(1)>"
    assert text["comment"] == "<!-- hidden instruction: do it -->", "a comment is shown, not hidden from the person"
    assert text["js_link"] == "x (javascript:alert(1))", "a link that is not of this page is its text and its address as text"
    assert text["js_link_case"] == "x (JaVaScRiPt:alert(1))"
    assert text["other_host_image"] == "x (http://other.host/i.png)", "an image is its alt text and address as text: nothing is fetched"
    assert text["other_host_link"] == "x (http://other.host/p)"
    assert text["protocol_relative"] == "x (//other.host/p)"
    assert text["backslash_host"] == "x (/\\other.host/p)"
    assert text["data_link"].startswith("x (data:text/html;base64,")
    assert text["title_attr"] == "x (/a)", "a link title is dropped: it would be an attribute; the address is not a route of the page, so it is text"


# --- 2. the subset: each element renders the nodes it should (CommonMark reading of the subset) -------------------------------------------

SUBSET = HEAD + r"""
const cases = {
  headings: "# One\n## Two\n### Three\n#### Four\n##### Five\n#NoSpace",
  paragraphs: "first line\nsecond line\n\nnext paragraph",
  hardBreak: "a  \nb\\\nc",
  emphasis: "**b** *i* __b2__ _i2_ ***both***",
  intraword: "snake_case_name and 5 * 3 * 2",
  unclosed: "**open and `tick and [link",
  nestedEmphasis: "**bold *and italic* text**",
  inlineCode: "`a*b*` and ``x`y`` and `` `lead ``",
  fenced: "```js\nlet a = 1;\n\n  # not a heading\n```\n\n~~~\nplain\n~~~\n\n```\nunclosed\nto the end",
  indentedCode: "para\n\n    code line\n    more\n\nafter",
  indentedContinues: "para\n    continued",
  bullets: "- a\n- b\n  - c\n  - d\n- e",
  ordered: "1. a\n2. b\n\n3) c\n\n7. seven",
  mixedNest: "1. a\n   - x\n   - y\n2. b",
  looseList: "- a\n\n- b\n\npara after",
  itemParagraphs: "- a\n\n  more\n- b",
  lazyItem: "- a\ncont\n- b",
  markerChange: "- a\n* b",
  quote: "> a\n> b\n>\n> c\n\n>> deep\n\n> - in list",
  table: "| A | B |\n|---|:-:|\n| 1 | **2** |\n| 3 |",
  tableBare: "A | B\n--|--\n1 | 2",
  tablePipe: "| a\\|b | c |\n|---|---|\n| x | y |",
  notTable: "a | b\n\n| c |\n| d |",
  rules: "---\n\n***\n\n___\n\n- - -\n\ntext",
  linkRoute: "[h](#/p/1) [t2](#/x \"a title\") [**b**](#/y) [enc](#/d/a%2Fb.md)",
  linkNotRoute: "[rel](docs/a.md) [path](/docs/a.md) [api](/api/projects) [abs](http://127.0.0.1:8765/x) [abs2](http://127.0.0.1:8765/#/p/1) [top](#top) [js](#javascript:x) [empty]()",
  linkOther: "[t](http://other.host/x) [**b**](https://other.host/y) [http://o.h/x](http://o.h/x)",
  bareUrl: "see http://o.h/x and <http://o.h/y>",
  image: "![alt text](http://other.host/i.png) ![a](/i.png)",
  escapes: "\\*not em\\* \\# \\[x\\]\\(y\\) \\\\",
  entities: "&lt;b&gt; &amp; <b>x</b>",
  empty: "",
  spaces: "   \n\n  \n",
  crlf: "a\r\nb\r\n\r\nc",
};
const out = {};
for (const [name, md] of Object.entries(cases)) out[name] = tree(md);
out.nullInput = renderMarkdown(null).children.length;
out.rootClass = renderMarkdown("x").attrs.class;
out.rootTag = renderMarkdown("x").tagName;
console.log(JSON.stringify(out));
"""

EXPECTED = {
    "headings": 'h1["One"],h2["Two"],h3["Three"],h4["Four"],p["##### Five\\n#NoSpace"]',
    "paragraphs": 'p["first line\\nsecond line"],p["next paragraph"]',
    "hardBreak": 'p["a",br,"b",br,"c"]',
    "emphasis": 'p[strong["b"]," ",em["i"]," ",strong["b2"]," ",em["i2"]," ",em[strong["both"]]]',
    "intraword": 'p["snake_case_name and 5 * 3 * 2"]',
    "unclosed": 'p["**open and `tick and [link"]',
    "nestedEmphasis": 'p[strong["bold ",em["and italic"]," text"]]',
    "inlineCode": 'p[code["a*b*"]," and ",code["x`y"]," and ",code["`lead"]]',
    "fenced": 'pre[code.language-js["let a = 1;\\n\\n  # not a heading"]],pre[code["plain"]],pre[code["unclosed\\nto the end"]]',
    "indentedCode": 'p["para"],pre[code["code line\\nmore"]],p["after"]',
    "indentedContinues": 'p["para\\ncontinued"]',
    "bullets": 'ul[li["a"],li["b",ul[li["c"],li["d"]]],li["e"]]',
    "ordered": 'ol[li["a"],li["b"]],ol[li["c"]],ol[li["seven"]]',
    "mixedNest": 'ol[li["a",ul[li["x"],li["y"]]],li["b"]]',
    "looseList": 'ul[li["a"],li["b"]],p["para after"]',
    "itemParagraphs": 'ul[li["a",p["more"]],li["b"]]',
    "lazyItem": 'ul[li["a\\ncont"],li["b"]]',
    "markerChange": 'ul[li["a"]],ul[li["b"]]',
    "quote": 'blockquote[p["a\\nb"],p["c"]],blockquote[blockquote[p["deep"]]],blockquote[ul[li["in list"]]]',
    "table": 'table[thead[tr[th["A"],th.wb-md-center["B"]]],tbody[tr[td["1"],td.wb-md-center[strong["2"]]],tr[td["3"],td.wb-md-center]]]',
    "tableBare": 'table[thead[tr[th["A"],th["B"]]],tbody[tr[td["1"],td["2"]]]]',
    "tablePipe": 'table[thead[tr[th["a|b"],th["c"]]],tbody[tr[td["x"],td["y"]]]]',
    "notTable": 'p["a | b"],p["| c |\\n| d |"]',
    "rules": 'hr,hr,hr,hr,p["text"]',
    "linkRoute": 'p[a.pui-link.pui-theme{#/p/1}["h"]," ",a.pui-link.pui-theme{#/x}["t2"]," ",a.pui-link.pui-theme{#/y}[strong["b"]]," ",a.pui-link.pui-theme{#/d/a%2Fb.md}["enc"]]',
    "linkNotRoute": 'p["rel (docs/a.md) path (/docs/a.md) api (/api/projects) abs (http://127.0.0.1:8765/x) abs2 (http://127.0.0.1:8765/#/p/1) top (#top) js (#javascript:x) empty"]',
    "linkOther": 'p["t (http://other.host/x) ",strong["b"]," (https://other.host/y) http://o.h/x"]',
    "bareUrl": 'p["see http://o.h/x and <http://o.h/y>"]',
    "image": 'p["alt text (http://other.host/i.png) a (/i.png)"]',
    "escapes": 'p["*not em* # [x](y) \\\\"]',
    "entities": 'p["&lt;b&gt; &amp; <b>x</b>"]',
    "empty": "",
    "spaces": "",
    "crlf": 'p["a\\nb"],p["c"]',
}


@needs_node
def test_each_element_of_the_subset_renders_the_nodes_it_should(tmp_path):
    got = floor_tests.run_node(tmp_path, SUBSET)
    assert got["rootTag"] == "DIV" and got["rootClass"] == "wb-md" and got["nullInput"] == 0
    wrong = {name: (got[name], want) for name, want in EXPECTED.items() if got[name] != want}
    assert not wrong, "\n".join(f"{name}:\n  got  {a}\n  want {b}" for name, (a, b) in wrong.items())


# --- 3. the size bound, hostile shapes and the time they take ----------------------------------------------------------------------------

SIZE = HEAD + r"""
const out = {};
const lines = Array.from({ length: 30000 }, (_, i) => `line ${i} **x**`);
const big = lines.join("\n");
const cut = big.lastIndexOf("\n", RENDER_LIMIT) + 1;
const root = renderMarkdown(big);
const rest = [...root.walk()].filter((n) => (n.attrs.class || "").includes("wb-md-rest"));
const notes = [...root.walk()].filter((n) => (n.attrs.class || "").includes("wb-md-note"));
out.big = { limit: RENDER_LIMIT, length: big.length, restCount: rest.length, restTag: rest[0] && rest[0].tagName, restIsTail: rest[0] && rest[0].textContent === big.slice(cut), note: notes[0] && notes[0].textContent,
  renderedPart: root.children[0].textContent.length > 0, noMarkdownInRest: rest[0] && rest[0].children.length === 1 };
const small = renderMarkdown("# t\n\nbody");
out.small = [...small.walk()].filter((n) => (n.attrs.class || "").match(/wb-md-(rest|note)/)).length;
const exact = renderMarkdown("a\n".repeat(RENDER_LIMIT / 2));
out.exact = [...exact.walk()].filter((n) => (n.attrs.class || "").match(/wb-md-(rest|note)/)).length;

function timed(md) { const t = performance.now(); const r = renderMarkdown(md); return { ms: Math.round(performance.now() - t), depth: depth(r), bad: violations(r).length }; }
const N = 199000;   // one paragraph over the inline cap: it falls back to text
const M = 49000;    // one paragraph inside the cap: the worst case the parser really parses
out.shapes = {
  brackets: timed("[".repeat(N)), bracketsIn: timed("[".repeat(M)),
  bracketsLink: timed("[a](".repeat(N / 4)), bracketsLinkIn: timed("[a](".repeat(M / 4)), bracketsClose: timed("[a]".repeat(M / 3)),
  backticks: timed("`a ".repeat(N / 3)), backticksIn: timed("`a ".repeat(M / 3)),
  backtickRuns: timed(Array.from({ length: 4000 }, (_, i) => "`".repeat(1 + (i % 50)) + "x").join(" ")),
  emphasis: timed("*a ".repeat(N / 3)), emphasisIn: timed("*a ".repeat(M / 3)), emphasisTight: timed("*a".repeat(M / 2)),
  underscores: timed("_a_b ".repeat(M / 5)), nestedEmphasis: timed("**a *b ".repeat(M / 7)),
  quotes: timed(">".repeat(N)), quoteLines: timed(">>>>>>>>>>>>>>>>>>>>>>>> x\n".repeat(N / 30)),
  lists: timed("- ".repeat(5000) + "x"), orderedLists: timed("1. ".repeat(5000) + "x"),
  indentedLists: timed(Array.from({ length: 1500 }, (_, i) => " ".repeat(i * 2) + "- x").join("\n")),
  table: timed("|" + " a |".repeat(20) + "\n|" + "---|".repeat(20) + "\n" + ("|" + " b |".repeat(20) + "\n").repeat(N / 90)),
  longLine: timed("word ".repeat(N / 5)),
  fences: timed("```\n".repeat(N / 4)),
  spaces: timed(" ".repeat(N) + "x"),
  hashes: timed("#".repeat(N)),
  tabs: timed("\t".repeat(N) + "x"),
  hardBreaks: timed("a  \n".repeat(N / 4)),
  fourParagraphs: timed(["[".repeat(M), "[a](".repeat(M / 4), "![".repeat(M / 2), "[a](<".repeat(M / 5)].join("\n\n")),
  fourParagraphsB: timed(["[a]".repeat(M / 3), "[a](b ".repeat(M / 6), "[a](<b ".repeat(M / 7), "[a](" + " ".repeat(M - 10)].join("\n\n")),
  manyParagraphs: timed("p\n\n".repeat(N / 3)),
};
console.log(JSON.stringify(out));
"""


@needs_node
def test_a_document_over_200_kb_renders_its_first_200_kb_and_says_the_rest_is_plain(tmp_path):
    got = floor_tests.run_node(tmp_path, SIZE)
    big = got["big"]
    assert big["limit"] == 200000 and big["length"] > big["limit"]
    assert big["restCount"] == 1 and big["restTag"] == "PRE" and big["restIsTail"], "the rest is one plain block holding exactly the text after the cut, which falls at a line end"
    assert big["noMarkdownInRest"], "the rest holds no element but its text"
    assert big["note"] and "plain" in big["note"].lower(), "a sentence says that the rest is plain text"
    assert big["renderedPart"]
    assert got["small"] == 0 and got["exact"] == 0, "a document within the limit has no note and no rest"


@needs_node
def test_hostile_shapes_of_200_kb_end_quickly_and_neither_nest_deeply_nor_build_an_unsafe_node(tmp_path):
    got = floor_tests.run_node(tmp_path, SIZE)
    for name, shape in got["shapes"].items():
        assert shape["bad"] == 0, name
        assert shape["ms"] < (100 if name.startswith("fourParagraphs") else 3000), f"{name} took {shape['ms']} ms in the fake document"
        assert shape["depth"] <= 80, f"{name} nests {shape['depth']} levels deep"


# --- 4. the viewer: the rendered document, the "Plain text" toggle, remembered for the session ---------------------------------------------------

VIEWER = r"""
import { FakeNode, settle, find, all } from "@FAKE@";
import { setToken } from "@JS@/token.js";
import { createViewer } from "@JS@/floor/viewer.js";

globalThis.location = new URL("http://127.0.0.1:8765/");
setToken("t".repeat(40));
let answer;
globalThis.fetch = async () => answer;
const reply = (status, body) => ({ ok: status === 200, status, json: async () => body });
const doc = (path, text) => reply(200, { path, text, size: text.length, modified_at: "2026-10-03T09:05:00Z" });
const state = (viewer) => {
  const md = find(viewer.el, ".wb-md");
  const pre = find(viewer.el, "pre.wb-viewer-text");
  const toggle = find(viewer.el, "button[data-key=plain]");
  return { md: md ? !md.hidden : null, pre: pre ? !pre.hidden : null, toggle: toggle ? [toggle.textContent, toggle.attrs["aria-pressed"]] : null, strong: all(viewer.el, ".wb-md strong").length };
};
const TEXT = "# Title\n\nsome **bold** text <script>alert(1)</script>";
const out = {};

const viewer = createViewer({ onClose() {} });
answer = doc("docs/a.md", TEXT);
await viewer.load("p", "docs/a.md");
out.first = state(viewer);
out.preText = find(viewer.el, "pre.wb-viewer-text").textContent === TEXT;
out.noScript = [...viewer.el.walk()].filter((n) => n.tagName === "SCRIPT").length;
find(viewer.el, "button[data-key=plain]").click();
out.plain = state(viewer);
find(viewer.el, "button[data-key=plain]").click();
out.back = state(viewer);
find(viewer.el, "button[data-key=plain]").click();       // plain again, then a new viewer in the same page session
const second = createViewer({ onClose() {} });
await second.load("p", "docs/b.md");
out.remembered = state(second);
find(second.el, "button[data-key=plain]").click();
const third = createViewer({ onClose() {} });
await third.load("p", "docs/c.md");
out.rendered = state(third);

answer = doc("docs/data.json", '{"a": "**not bold**"}');
await third.load("p", "docs/data.json");
out.json = state(third);
answer = reply(400, { error: "usage", message: "refused **x**" });
await third.load("p", "../.env");
out.refused = { toggle: find(third.el, "button[data-key=plain]"), md: find(third.el, ".wb-md"), text: find(third.el, ".wb-refusal").textContent };
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_viewer_renders_a_markdown_document_and_a_plain_text_toggle_shows_the_typed_text_and_is_remembered(tmp_path):
    got = floor_tests.run_node(tmp_path, VIEWER)
    assert got["first"] == {"md": True, "pre": False, "toggle": ["Plain text", "false"], "strong": 1}
    assert got["preText"], "the plain view is the text exactly as it came"
    assert got["noScript"] == 0
    assert got["plain"] == {"md": False, "pre": True, "toggle": ["Plain text", "true"], "strong": 1}
    assert got["back"]["md"] is True and got["back"]["pre"] is False and got["back"]["toggle"][1] == "false"
    assert got["remembered"]["pre"] is True and got["remembered"]["md"] is False, "the choice is kept for the page session: a later document opens plain"
    assert got["rendered"]["md"] is True and got["rendered"]["pre"] is False, "and toggling back is kept too"


@needs_node
def test_a_file_that_is_not_markdown_and_a_refusal_stay_plain_text_with_no_toggle(tmp_path):
    got = floor_tests.run_node(tmp_path, VIEWER)
    assert got["json"]["md"] is None and got["json"]["toggle"] is None and got["json"]["pre"] is True, "a data file is a wrapped block of text"
    assert got["refused"]["toggle"] is None and got["refused"]["md"] is None
    assert got["refused"]["text"].endswith("refused **x**"), "the operation's message is shown as it is"


# --- 5. the cards ------------------------------------------------------------------------------------------------------------------------

CARDS = r"""
import { FakeNode, settle, find, all } from "@FAKE@";
import { createCard } from "@JS@/floor/cards.js";
globalThis.location = new URL("http://127.0.0.1:8765/");
const env = () => ({ project: "p", now: () => new Date("2026-10-08T12:00:00Z"), api: {}, requestIds: new Set([1]),
  links: { floor: (a) => `#/p/p/floor/${a}`, lobby: () => "#/p/p/lobby", open: (item, path) => `#/open/${path}`, parent: () => "#/p/p" }, reread: async () => null, changed() {}, gone() {} });
const item = (kind, actions, extra = {}) => ({ id: 21, kind, title: `T ${kind}`, body: "body", payload: {}, payload_sha256: null, status: "open", actions, agent: "marketing", task_id: 7, run_id: null, created_at: "2026-10-08T09:00:00Z", ...extra });
const BODY = "Intro **bold**\n\n- one\n- two\n\n<img src=x onerror=alert(1)> [x](javascript:alert(1))";
const strong = (card) => all(card.el, "strong").map((n) => n.textContent);
const bad = (card) => [...card.el.walk()].filter((n) => ["IMG", "SCRIPT", "IFRAME"].includes(n.tagName) || n.tagName === "A" && /javascript/.test(n.attrs.href || "")).length;
const out = {};
for (const kind of ["question", "acceptance", "review", "mystery"]) {
  const card = createCard(item(kind, ["answered", "accepted", "released"], { body: BODY, title: "**Title** stays text" }), env());
  out[kind] = { strong: strong(card), items: all(card.el, "li").map((n) => n.textContent), bad: bad(card), title: card.el.querySelector("h3").textContent, text: card.el.textContent.includes("<img src=x onerror=alert(1)>") };
}
const effect = createCard(item("effect", ["approved", "rejected"], { body: "Publish **this** exactly.\n- not a list", payload_sha256: "a".repeat(64) }), env());
out.effect = { strong: strong(effect), pre: effect.el.querySelector("pre").textContent, items: all(effect.el, "li").length };
const planBody = "Source: the router\n\n| # | Task |\n|---|---|\n| 1 | build |\n\nPlan hash: " + "b".repeat(64);
const plan = createCard(item("plan", ["approved", "rejected"], { body: planBody, payload: { tasks: [], limits: {}, plan_sha256: "b".repeat(64) } }), env());
out.plan = { tables: all(plan.el, ".wb-md table").length, hash: plan.el.querySelector("[data-hash=plan]").textContent, cells: all(plan.el, ".wb-md td").map((n) => n.textContent) };
const toggle = plan.el.querySelector("button[data-key=plain]");
const view = () => ({ md: !plan.el.querySelector(".wb-md").hidden, pre: !plan.el.querySelector("details pre").hidden, text: plan.el.querySelector("details pre").textContent === planBody, pressed: toggle.attrs["aria-pressed"] });
out.planToggle = { before: view() };
toggle.click();
out.planToggle.after = view();
toggle.click();
out.planToggle.again = view();
console.log(JSON.stringify(out));
"""


@needs_node
def test_question_review_and_acceptance_bodies_render_as_markdown_and_the_effects_exact_content_stays_plain(tmp_path):
    got = floor_tests.run_node(tmp_path, CARDS)
    for kind in ("question", "acceptance", "review", "mystery"):
        card = got[kind]
        assert card["strong"] == ["bold"], kind
        assert card["items"] == ["one", "two"], kind
        assert card["bad"] == 0, kind
        assert card["title"] == "**Title** stays text", "a title is a title: plain text"
        assert card["text"], "the raw HTML of the body is still there to read, as text"
    assert got["effect"] == {"strong": [], "pre": "Publish **this** exactly.\n- not a list", "items": 0}, \
        "what will be sent is shown exactly as it is: it is the content that is approved"
    assert got["plan"]["tables"] == 1 and got["plan"]["cells"] == ["1", "build"]
    assert got["plan"]["hash"] == "b" * 64, "the plan hash is the card's own text and is never rendered"
    assert got["planToggle"] == {"before": {"md": True, "pre": False, "text": True, "pressed": "false"},
                                 "after": {"md": False, "pre": True, "text": True, "pressed": "true"},
                                 "again": {"md": True, "pre": False, "text": True, "pressed": "false"}}, \
        "the plan's body has the viewer's Plain text toggle: the exact text is one click away"


# --- 6. the conversation and the Lobby's plan card ---------------------------------------------------------------------------------------

THREAD = r"""
import { FakeNode, find, byClass, textOf } from "@FAKE@";
import { createThread } from "@JS@/views/lobby-thread.js";
import { createPlanCard } from "@JS@/cards/plan.js";
globalThis.location = new URL("http://127.0.0.1:8765/");
const NOW = new Date("2026-10-08T12:00:00Z");
const api = { approve: async () => ({}), reject: async () => ({}), pollJob: async () => ({ state: "done" }), cancel: async () => ({}) };
const thread = createThread({ api, project: "p1", signal: undefined, onChanged: async () => {}, onCancel: () => {}, onRoute: () => {} });
const TEXT = "I will do **this**:\n\n1. first\n2. second\n\n<script>alert(1)</script> ![x](http://other.host/i.png)";
const messages = [{ id: 1, role: "user", text: TEXT, created_at: "2026-10-08T08:00:00Z" }, { id: 2, role: "assistant", text: TEXT, created_at: "2026-10-08T08:01:00Z" }];
thread.update({ messages, requests: [], pending: [], bodies: {}, now: NOW, loading: false, routing: new Set() });
const bubbles = byClass(thread.el, "wb-bubble");
const strongs = (n) => find(n, (x) => x.tagName === "STRONG").map(textOf);
const out = {
  user: { text: textOf(bubbles[0]), strong: strongs(bubbles[0]).length, children: bubbles[0].children.length },
  agent: { strong: strongs(bubbles[1]), items: find(bubbles[1], (x) => x.tagName === "LI").map(textOf), bad: find(bubbles[1], (x) => ["SCRIPT", "IMG"].includes(x.tagName)).length, text: textOf(bubbles[1]).includes("<script>alert(1)</script>") },
};
const hash = "ab".repeat(32);
const plan = createPlanCard({ api, project: "p1", now: NOW, onChanged: async () => {}, item: { id: 22, kind: "plan", title: "Plan", body: "Source: **router**\n\n| # | Task |\n|---|---|\n| 1 | build |", task_id: 14, agent: null, status: "open",
  created_at: "2026-10-08T08:00:00Z", actions: ["approved", "rejected"], payload: { plan_sha256: hash, tasks: [], limits: {}, estimate: {} } } });
out.plan = { cells: find(plan.el, (x) => x.tagName === "TD").map(textOf).filter((t) => t === "build"), strong: strongs(plan.el), hash: textOf(byClass(plan.el, "wb-plan-hash")[0]) };
const lobbyToggle = find(plan.el, (x) => x.tagName === "BUTTON" && x.attrs["data-key"] === "plain")[0];
const lobbyView = () => ({ md: !byClass(plan.el, "wb-md")[0].hidden, pre: !byClass(plan.el, "wb-plan-pre")[0].hidden, text: textOf(byClass(plan.el, "wb-plan-pre")[0]) });
out.lobbyToggle = { before: lobbyView() };
lobbyToggle.listeners.click[0]();
out.lobbyToggle.after = lobbyView();
lobbyToggle.listeners.click[0]();
console.log(JSON.stringify(out));
"""


@pytest.mark.skipif(lobby_tests.NODE is None, reason="node is not installed")
def test_the_planning_agents_reply_renders_as_markdown_and_the_persons_message_stays_plain_text(tmp_path):
    got = lobby_tests.run_node(tmp_path, THREAD)
    assert got["user"]["strong"] == 0 and got["user"]["children"] == 1 and "**this**" in got["user"]["text"], "what the person typed is shown as typed"
    assert got["agent"]["strong"] == ["this"] and got["agent"]["items"] == ["first", "second"]
    assert got["agent"]["bad"] == 0 and got["agent"]["text"], "raw HTML in a reply is text"
    assert got["plan"]["cells"] == ["build"] and got["plan"]["strong"] == ["router"], "the Lobby's plan card draws its stored body with the renderer"
    assert got["plan"]["hash"] == "ab" * 32, "the hash is never rendered"
    text = "Source: **router**\n\n| # | Task |\n|---|---|\n| 1 | build |"
    assert got["lobbyToggle"] == {"before": {"md": True, "pre": False, "text": text}, "after": {"md": False, "pre": True, "text": text}}, "the Lobby's plan card has the toggle too"


# --- 7. the files: one renderer, and what it may not contain ----------------------------------------------------------------------------------

def own_js():
    return sorted(p for p in JS.rglob("*.js"))


def test_markdown_js_builds_nodes_only_and_nothing_else_in_the_page_renders_markdown():
    text = MARKDOWN.read_text(encoding="utf-8")
    for word in ("innerHTML", "outerHTML", "insertAdjacentHTML", "createContextualFragment", "DOMParser", "document.write", "srcdoc", "Function(", "eval(",  # security-scan: allow dynamic-eval -- a word the renderer's file must not hold; nothing runs it
                 "setAttributeNS", "setAttributeNode", ".attributes", ".style", "createElement(\"img\"", "createElement(\"script\"", "createElement(\"iframe\"", "localStorage", "sessionStorage", "fetch("):
        assert word not in text, f"markdown.js holds {word}"
    assert not re.search(r"https?:", text), "no address of any host, and no scheme name: nothing in the file is fetched or compared with one"
    assert not re.search(r"\.(?:href|src|srcset|id|title|className|outerText|textContent\s*=|on[a-z]+)\s*=[^=]", text), "no property assignment that would set an attribute"
    calls = re.findall(r"setAttribute\(\s*([^,)]*)", text)
    assert calls and all(arg in ('"class"', '"href"') for arg in calls), f"every setAttribute call names class or href as a literal: {calls}"
    assert not re.search(r"setAttribute\(\s*(?!\"class\"|\"href\")", text)
    # who imports the renderer: the file that places it with its toggle, the cards' text and the conversation; who imports that
    # file: the viewer and the two plan cards. No other own file may import either.
    importers = {"markdown.js": set(), "markdown-view.js": set()}
    for path in own_js():
        name = str(path.relative_to(JS))
        body = path.read_text(encoding="utf-8")
        for target in importers:
            if re.search(r"(?:from\s+|import\s*\(\s*|import\s+)[\"'][^\"']*" + re.escape(target) + r"[\"']", body):
                importers[target].add(name)
        if path != MARKDOWN:
            assert "blockquote" not in body and "language-" not in body, f"{name} renders Markdown itself"
    assert importers["markdown.js"] == {"markdown-view.js", "floor/cards.js", "views/lobby-thread.js"}, importers
    assert importers["markdown-view.js"] == {"floor/viewer.js", "floor/cards.js", "cards/plan.js"}, importers


def test_every_class_markdown_js_builds_is_a_rule_of_the_stylesheet_and_none_sets_a_colour_of_its_own():
    css = interface_css()
    classes = set(re.findall(r"\bwb-md[a-z0-9-]*", MARKDOWN.read_text(encoding="utf-8") + (JS / "markdown-view.js").read_text(encoding="utf-8")))
    assert {"wb-md", "wb-md-tools"} <= classes
    for cls in classes:
        assert re.search(re.escape("." + cls) + r"(?![A-Za-z0-9_-])", css), f".{cls} has no rule in the stylesheets"
    block = "\n".join(line for line in css.splitlines() if ".wb-md" in line)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(", block), "the renderer's rules use the page's tokens, no colour literal"
    assert "overflow-x" not in block and "scroll" not in block, "code and tables wrap: nothing scrolls sideways"
