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
        text = re.sub(r"/\*.*?\*/", "", path.read_text(encoding="utf-8"), flags=re.S)      # a class named in a comment is not a class the library defines
        found |= set(re.findall(r"\.(pui-[a-z0-9][a-z0-9_-]*)", text))
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
    assert {"pui-btn", "pui-chip", "pui-badge", "pui-input", "pui-card", "pui-field-group", "pui-solid", "pui-outline", "pui-theme"} <= known, "the class list was read from the vendored css"


def test_no_script_or_page_uses_a_pui_class_the_library_does_not_define():
    known = defined() | set(OURS)
    missing = {name: sorted(files) for name, files in used(["js/**/*.js", "demo/**/*.js", "*.html", "demo/**/*.html"]).items() if name not in known}
    assert not missing, f"pui classes that the vendored PerfectUI does not define (they draw nothing): {missing}"


def test_no_stylesheet_of_the_page_styles_a_pui_class_the_library_does_not_define():
    known = defined() | set(OURS)
    missing = {name: sorted(files) for name, files in used(["css/*.css"]).items() if name not in known}
    assert not missing, f"pui classes in the page's stylesheets that the library does not define: {missing}"


DYNAMIC = re.compile(r"pui-\$\{|pui-[\"']\s*\+|[\"']pui-[\"']")
TONES = ("theme", "warn", "success", "error", "muted")      # the tone words of the library's colours: the only names these three files build
DYNAMIC_OK = {"js/frame/panel.js": TONES, "js/frame/kpis.js": TONES, "js/views/floor.js": TONES}      # a file -> the names its `pui-${tone}` can build


def test_no_pui_class_is_built_from_parts_where_this_test_cannot_see_it():
    """`pui-${name}` or `"pui-" + name` names a class this test cannot read; the page writes each class whole, or lists the file here with the names it can build."""
    found = {}
    for pattern in ("js/**/*.js", "demo/**/*.js", "*.html"):
        for path in sorted(INTERFACE.glob(pattern)):
            if "vendor" not in path.parts and DYNAMIC.search(path.read_text(encoding="utf-8")) and str(path.relative_to(INTERFACE)) not in DYNAMIC_OK:
                found[str(path.relative_to(INTERFACE))] = DYNAMIC.search(path.read_text(encoding="utf-8")).group(0)
    assert not found, f"a pui class built from parts (the test cannot check it): {found}"


def test_a_class_named_only_in_a_comment_of_the_library_is_not_defined(tmp_path):
    """The reader of the library's class list ignores comments."""
    import test_interface_pui_classes as me
    assert "pui-comment-only-class" not in me.defined()


def test_every_name_a_listed_file_can_build_is_a_class_the_library_defines():
    known = defined()
    missing = {f"pui-{tone}" for tones in DYNAMIC_OK.values() for tone in tones} - known
    assert not missing, f"names a file builds from parts that the library does not define: {sorted(missing)}"
