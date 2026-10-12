"""Tests of OH-3: the mark in the page. The modules run under Node with a fake document, so what the token prompt and the top bar
build is checked: an image of the mark file with the alt text, at the sizes the identity names, in the places it names. The served
page was looked at in a browser pane by the package's report.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interface_brand.py
"""
from __future__ import annotations

import pytest

from test_interface_plates_meters import needs_node, run_node

BRAND = r"""
import { FakeNode, find, all } from "@FAKE@";
import { markImage } from "@JS@/brand.js";
import { createBrand, createNav } from "@JS@/frame/header.js";
import { showTokenPrompt } from "@JS@/views/token-prompt.js";

const out = {};
const small = markImage(20);
out.small = { tag: small.tagName, src: small.attrs.src, alt: small.attrs.alt, width: small.attrs.width, height: small.attrs.height, cls: small.attrs.class, style: small.attrs.style || null };
const big = markImage(48);
out.big = { width: big.attrs.width, height: big.attrs.height, alt: big.attrs.alt };

// the top row (R-1): the mark (28 px) and the wordmark in one box; the wordmark is not read twice
const brand = createBrand();
const brandMark = find(brand, "img.wb-mark");
out.brand = { cls: brand.attrs.class, mark: brandMark && { alt: brandMark.attrs.alt, width: brandMark.attrs.width, height: brandMark.attrs.height, src: brandMark.attrs.src },
  word: find(brand, ".wb-wordmark").textContent, wordHidden: find(brand, ".wb-wordmark").attrs["aria-hidden"] };

// Back and the crumbs (R-2): no mark between them any more, and the City's crumb keeps its place
const nav = createNav();
nav.set([{ label: "City", href: "#/" }], null);
const order = nav.el.children.map((c) => c.attrs.class || c.tagName);
out.navOrder = order;
const mark = find(nav.el, "img.wb-mark");
out.navMark = mark;
out.crumb = find(nav.el, ".wb-crumb").textContent;
nav.set([{ label: "City", href: "#/" }, { label: "northwind-shop", href: null }], "#/");
out.crumbsAfter = all(nav.el, ".wb-crumb").map((n) => n.textContent);
out.marksAfter = all(nav.el, "img").length;

// the token prompt (R-13): the bar holds the mark (24 px, no alt: the text beside it names it) and the text "openhora"; the title names the product
const root = new FakeNode("div");
showTokenPrompt(root, { message: null, onSubmit: async () => {} });
const walk = [...root.walk()].map((n) => n.attrs && (n.attrs.id || n.attrs.class || n.tagName));
const markAt = walk.findIndex((x) => x && String(x).includes("wb-mark"));
const fieldAt = walk.findIndex((x) => x === "token-field");
out.prompt = { header: find(root, "h1.tk-title").textContent, mark: find(root, "img.wb-mark").attrs, word: find(root, ".wb-wordmark").textContent, markBeforeField: markAt > 0 && markAt < fieldAt,
  images: all(root, "img").length };
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_mark_is_an_img_of_the_file_with_its_alt_text_in_the_top_bar_and_on_the_token_prompt(tmp_path):
    got = run_node(tmp_path, BRAND)
    assert got["small"] == {"tag": "IMG", "src": "./brand/openhora-mark.svg", "alt": "openhora", "width": "20", "height": "20", "cls": "wb-mark", "style": None}, \
        "an img of the mark file, same origin, sized by attributes and a class, with no style attribute"
    assert (got["big"]["width"], got["big"]["height"], got["big"]["alt"]) == ("48", "48", "openhora"), "the default alt is the product's name"
    assert got["brand"] == {"cls": "wb-brand", "mark": {"alt": "openhora", "width": "28", "height": "28", "src": "./brand/openhora-mark.svg"}, "word": "openhora", "wordHidden": "true"}, \
        "R-1: the mark and the wordmark in one box at the top left; the mark carries the name"
    assert got["navOrder"] == ["pui-btn pui-surface pui-outline wb-back", "wb-crumb-nav"] and got["navMark"] is None, f"R-2: Back, then the breadcrumbs, no mark between them: {got['navOrder']}"
    assert got["crumb"] == "City" and got["crumbsAfter"] == ["City", "northwind-shop"], "the crumbs keep their words and places"
    assert got["marksAfter"] == 0, "the mark is in the brand, not in the navigation"
    prompt = got["prompt"]
    assert prompt["header"] == "Paste the openhora service token" and prompt["word"] == "openhora"
    assert prompt["mark"]["alt"] == "" and prompt["mark"]["width"] == "24" and prompt["mark"]["height"] == "24", "R-13: 24 px in the bar, the name beside it as text"
    assert prompt["markBeforeField"] is True and prompt["images"] == 1, "one image (the owl at the right is a drawing, not an image), before the field"
