"""The page's own stylesheets, read the way the browser reads them (R4-S).

The page links `interface/css/*.css` from index.html, in an order: the order is the cascade. A test that looks at "the stylesheet" reads all of them
in that order, through `interface_css()`; a test of one screen can read one file with `css_file("lobby")`. `stylesheets()` is the same text with the
`read_text` of a Path, for a module that keeps a `CSS` constant. `scene.css` and the library's stylesheet are not part of it: they have their own tests.
"""
from __future__ import annotations

import re
from pathlib import Path

import standin_tree as st

INTERFACE = st.REPO / "interface"
LINK = re.compile(r'<link\s+rel="stylesheet"\s+href="\./(css/[a-z-]+\.css)"\s*>')


def css_paths() -> list[Path]:
    """The page's own stylesheets, in the order index.html links them."""
    html = (INTERFACE / "index.html").read_text(encoding="utf-8")
    return [INTERFACE / href for href in LINK.findall(html)]


def interface_css() -> str:
    """The text of all of them, in link order, one after the other."""
    return "\n".join(path.read_text(encoding="utf-8") for path in css_paths())


def css_file(name: str) -> str:
    """The text of one stylesheet by its name without the extension (`css_file("lobby")`)."""
    return (INTERFACE / "css" / f"{name}.css").read_text(encoding="utf-8")


class _Stylesheets:
    """Stands where `INTERFACE / "style.css"` stood: `read_text` gives all the stylesheets in link order."""

    def read_text(self, encoding: str = "utf-8") -> str:
        return interface_css()


def stylesheets() -> _Stylesheets:
    return _Stylesheets()
