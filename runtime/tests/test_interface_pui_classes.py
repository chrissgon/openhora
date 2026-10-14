"""Every `pui-*` class the page's scripts and stylesheets use is one the vendored PerfectUI defines (interface/vendor/perfectui/css).

A class that the library does not have draws nothing: the element falls back to the browser's own look (the send-back comment box of the video card was written
`pui-textarea`, which does not exist, and rendered with browser defaults). The page's own classes are `wb-*`; if one ever has to be named `pui-*`, it goes in
OURS with the reason beside it. No browser here: the class lists are read from the files.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interface_pui_classes.py
"""
from __future__ import annotations

import re

from test_interface_floor import INTERFACE

VENDOR = INTERFACE / "vendor" / "perfectui"
OURS: dict = {}      # class -> why the page may use it though the library does not define it (none today)

CLASS = re.compile(r"(?<![\w-])(pui-[a-z0-9][a-z0-9_-]*)")


def defined() -> set:
    found: set = set()
    for path in [VENDOR / "perfectui.css", *sorted((VENDOR / "css").rglob("*.css"))]:
        found |= set(re.findall(r"\.(pui-[a-z0-9][a-z0-9_-]*)", path.read_text(encoding="utf-8")))
    return found


def used(globs) -> dict:
    where: dict = {}
    for pattern in globs:
        for path in sorted(INTERFACE.glob(pattern)):
            if "vendor" in path.parts:
                continue
            for name in CLASS.findall(path.read_text(encoding="utf-8")):
                where.setdefault(name, set()).add(str(path.relative_to(INTERFACE)))
    return where


def test_the_library_is_read_and_has_the_classes_the_page_leans_on():
    known = defined()
    assert {"pui-btn", "pui-badge", "pui-badge", "pui-input", "pui-card", "pui-field-group", "pui-solid", "pui-outline", "pui-theme"} <= known, "the class list was read from the vendored css"


def test_no_script_or_page_uses_a_pui_class_the_library_does_not_define():
    known = defined() | set(OURS)
    missing = {name: sorted(files) for name, files in used(["js/**/*.js", "demo/**/*.js", "*.html", "demo/**/*.html"]).items() if name not in known}
    assert not missing, f"pui classes that the vendored PerfectUI does not define (they draw nothing): {missing}"


def test_no_stylesheet_of_the_page_styles_a_pui_class_the_library_does_not_define():
    known = defined() | set(OURS)
    missing = {name: sorted(files) for name, files in used(["css/*.css"]).items() if name not in known}
    assert not missing, f"pui classes in the page's stylesheets that the library does not define: {missing}"
