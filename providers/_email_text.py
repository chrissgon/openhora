#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""What the e-mail readers of the workbench share to turn a message into text: the reader of providers/mailbox/gmail.py (class
reader:email) and the e-mail channel of the messaging bridge (providers/messenger/email-imap.py) both load it by path. A name with an underscore
is never listed as an implementation by providers/resolve.py, so this file is a module, not a provider. The helpers were moved here from gmail.py
unchanged; gmail.py binds the same names, so `gmail.html_to_text` and the others are still there. `strip_quoted` and its marker lists were moved
here from providers/messenger/email-imap.py unchanged (the same text, the same behaviour), so that the Gmail reader's --own-words and the e-mail
channel cut the quoted history of a reply in one way.

  INVISIBLE_RE, HSPACE_RE    the invisible and direction-changing characters, and a run of horizontal space
  HIDDEN_STYLE_RE, style_hides   an inline style that hides an element and all that is in it from a reader (display:none, visibility:hidden,
                             mso-hide:all, opacity:0, a zero width, height, max-width or max-height with overflow:hidden); font_zero, a zero
                             font-size, hides the text written in that element unless a descendant sets a size of its own
  clean_line, clean_block    a line, and a block, with the invisible characters removed and the space folded
  HTMLText, html_to_text     the text and the links of an HTML body with the standard library parser (no script is run, no link is
                             followed, nothing is fetched); an element hidden by an inline style or the hidden attribute gives nothing
  dedupe_links               the links of a body, one for each address
  part_text                  the text of one MIME part, decoded; a wrong charset is read as UTF-8 with replacement
  strip_quoted               the sender's own words: the text before the first quoted line, signature delimiter, attribution ("On ... wrote:"
                             and its Portuguese and Spanish forms), forward or original-message marker, or Outlook header block

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser

# Invisible and direction-changing characters: e-mail preheaders pad with them, and they can hide
# text from a human reader. They are removed from every text the provider returns.
INVISIBLE_RE = re.compile("[\u00ad\u034f\u061c\u115f\u1160\u17b4\u17b5\u180e\u200b-\u200f\u202a-\u202e"
                          "\u2060-\u2064\u2066-\u2069\u3164\ufeff\uffa0]")
HSPACE_RE = re.compile(r"[^\S\n]+")
# An inline style that hides an element from a reader. Hidden text is a way to put words before a model that the
# person never sees, so it is not message text. Two kinds, by what a descendant can do about them:
#  - HIDDEN_STYLE_RE: declarations that hide the element and everything in it, which no child can undo: display:none, visibility:hidden,
#    the Outlook mso-hide:all and opacity:0;
#  - a box of zero width or height (also max-width and max-height) hides only together with overflow:hidden; alone its text overflows
#    and is seen (style_hides). A zero font-size hides only the text written in that element, and a descendant that sets its own
#    non-zero size shows its text again (HTMLText keeps a stack of the sizes): template e-mails set font-size:0 on a wrapper to kill
#    the gaps between inline blocks and size the text inside it.
_ZERO = r"0(?:\.0+)?(?:px|pt|em|rem|ex|ch|%)?"
_END = r"\s*(?:!\s*important\s*)?(?:;|$)"
HIDDEN_STYLE_RE = re.compile(r"(?:^|;)\s*(?:display\s*:\s*none|visibility\s*:\s*hidden|mso-hide\s*:\s*all|opacity\s*:\s*0(?:\.0+)?)" + _END, re.I)
ZERO_BOX_RE = re.compile(r"(?:^|;)\s*(?:max-)?(?:width|height)\s*:\s*" + _ZERO + _END, re.I)
OVERFLOW_HIDDEN_RE = re.compile(r"(?:^|;)\s*overflow(?:-[xy])?\s*:\s*hidden" + _END, re.I)
FONT_DECL_RE = re.compile(r"(?:^|;)\s*(font-size|font)\s*:\s*([^;]*)", re.I)
FONT_ZERO_RE = re.compile(_ZERO, re.I)
# Sizes that do not depend on the parent's: a child with one of these is seen even inside a font-size:0 wrapper.
FONT_ABSOLUTE_RE = re.compile(r"[0-9.]+(?:px|pt|pc|in|cm|mm|q|rem|vw|vh)|(?:xx-|x-)?small|medium|(?:x-|xx-|xxx-)?large", re.I)


def style_hides(style: str) -> bool:
    """Whether an inline style hides the element it is on and all that is in it (see above). A style sheet rule, a class, a colour, a
    position off the page and a zero font-size (see font_zero) are not looked at here."""
    return bool(HIDDEN_STYLE_RE.search(style) or (ZERO_BOX_RE.search(style) and OVERFLOW_HIDDEN_RE.search(style)))


def font_zero(style: str, inherited: bool) -> bool:
    """Whether the text in an element is of size zero. The last font-size or font declaration decides when there is one: a size of zero
    (also as the size token of the `font` shorthand, `font:0/0 Arial`) is zero; a size that does not depend on the parent's (13px, large,
    calc(...), min(...), the size token of `font:14px Arial`) is not; anything else (1em, 120%, smaller, inherit, a shorthand with no size)
    keeps what the parent had. With no declaration the element has what its parent had."""
    found = FONT_DECL_RE.findall(style)
    if not found:
        return inherited
    name, value = found[-1][0].lower(), re.sub(r"\s*!\s*important\s*$", "", found[-1][1].strip(), flags=re.I).lower()
    if value.startswith(("calc(", "clamp(", "min(", "max(")):
        return False
    tokens = [value] if name == "font-size" else [token.split("/", 1)[0] for token in value.split()]
    for token in tokens:
        if FONT_ZERO_RE.fullmatch(token):
            return True
        if FONT_ABSOLUTE_RE.fullmatch(token):
            return False
    return inherited


def clean_line(line: str) -> str:
    return HSPACE_RE.sub(" ", INVISIBLE_RE.sub("", line)).strip()


def clean_block(text: str, keep_blank_lines: bool) -> str:
    lines = [clean_line(line) for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    if not keep_blank_lines:
        return "\n".join(line for line in lines if line)
    out: list[str] = []
    for line in lines:
        if line or (out and out[-1]):
            out.append(line)
    return "\n".join(out).strip("\n")


class HTMLText(HTMLParser):
    """Text and links of an HTML body, with the standard library parser (no script is run). An element hidden by the hidden attribute or
    by an inline style (display:none, visibility:hidden, mso-hide:all, opacity:0, a zero width or height with overflow:hidden) gives no
    text and no link, nor does anything in it; text of font size zero gives none either, unless an element in it sets a size of its own.

    The open elements are a stack, kept the way a browser keeps them where it matters to what is shown: the cost is linear in the size of
    the body. An end tag with no open element of its name is ignored at once; one that closes an element with a block (a `special`
    element: p, div, li, td ...) open inside it is ignored too, as a browser ignores `</span>` when a `<p>` opened in the span is still open
    (so text after it stays inside the hidden or zero-size element); a start tag that a browser reads as ending an element ends it: a
    block ends an open p, an li an open li, a td or th an open td or th, a tr an open tr. The stack holds at most DEPTH_CAP elements: past it
    an element that would hide more than its parent hides the rest of the body, and any other has its parent's state."""

    SKIP = {"script", "style", "head", "title", "template", "noscript"}
    BLOCK = {"p", "div", "br", "tr", "li", "ul", "ol", "table", "h1", "h2", "h3", "h4", "h5", "h6",
             "blockquote", "section", "article", "header", "footer", "hr", "td", "th"}

    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
    # The elements that close what is open around them in a way no end tag of an inline element reaches (HTML's "special" category, in part).
    SPECIAL = {"p", "div", "li", "td", "th", "tr", "table", "tbody", "thead", "tfoot", "ul", "ol", "dl", "dd", "dt", "h1", "h2", "h3", "h4", "h5",
               "h6", "section", "article", "header", "footer", "nav", "aside", "blockquote", "form", "center", "pre", "main", "address",
               "figure", "fieldset", "menu"}
    # A start tag of one of these ends an open p.
    CLOSES_P = SPECIAL - {"td", "th", "tr", "tbody", "thead", "tfoot"} | {"hr"}
    DEPTH_CAP = 4096

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.links: list[dict] = []
        self.skip_depth = 0
        self.anchor: dict | None = None
        # The open elements, as [tag, zero font size, hidden, index of the nearest special element at or below it]; and, for each name, the
        # indexes in the stack of the open elements of that name (the last is the innermost).
        self.stack: list[list] = []
        self.at: dict[str, list[int]] = {}
        self.poisoned = False   # an element past the depth cap hid more than its parent: the rest of the body is not read

    @staticmethod
    def hidden(attrs: dict) -> bool:
        return "hidden" in attrs or style_hides(attrs.get("style") or "")

    @property
    def zero(self) -> bool:
        """Whether the text here is of font size zero."""
        return self.stack[-1][1] if self.stack else False

    @property
    def concealed(self) -> bool:
        """Whether what is here is hidden, by an element around it or by the depth cap."""
        return self.poisoned or (self.stack[-1][2] if self.stack else False)

    def _pop_to(self, index: int) -> None:
        """Close the element at `index` of the stack and everything open inside it."""
        while len(self.stack) > index:
            self.at[self.stack.pop()[0]].pop()

    def _push(self, tag: str, zero: bool, hidden: bool) -> None:
        if len(self.stack) >= self.DEPTH_CAP:
            if hidden and not self.concealed or zero and not self.zero:
                self.poisoned = True
            return
        nearest = len(self.stack) if tag in self.SPECIAL else (self.stack[-1][3] if self.stack else -1)
        self.at.setdefault(tag, []).append(len(self.stack))
        self.stack.append([tag, zero, hidden, nearest])

    def _innermost_special(self) -> str | None:
        return self.stack[self.stack[-1][3]][0] if self.stack and self.stack[-1][3] >= 0 else None

    def _auto_close(self, tag: str) -> None:
        """End what a browser ends when this start tag arrives."""
        if not self.stack:
            return
        if tag in self.CLOSES_P and self._innermost_special() == "p":
            self._pop_to(self.stack[-1][3])
        if tag == "li" and self._innermost_special() == "li":
            self._pop_to(self.stack[-1][3])
        elif tag in ("dd", "dt") and self._innermost_special() in ("dd", "dt"):
            self._pop_to(self.stack[-1][3])
        elif tag in ("td", "th") and self._innermost_special() in ("td", "th"):
            self._pop_to(self.stack[-1][3])
        elif tag == "tr":
            rows, tables = self.at.get("tr"), self.at.get("table")
            if rows and (not tables or rows[-1] > tables[-1]):
                self._pop_to(rows[-1])

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip_depth += 1
            return
        attrs = dict(attrs)
        self._auto_close(tag)
        hidden = self.concealed or self.hidden(attrs)
        base = False if tag == "font" and "size" in attrs else self.zero   # <font size=N> sets a size of its own
        zero = font_zero(attrs.get("style") or "", base)
        if tag not in self.VOID:
            self._push(tag, zero, hidden)
        if hidden:
            return
        if tag in self.BLOCK:
            self.parts.append("\n")
        if tag == "a":
            self._close_anchor()
            href = (attrs.get("href") or "").strip()
            self.anchor = {"href": href, "text": []} if href and not zero else None
        elif tag == "img" and self.anchor is not None and attrs.get("alt"):
            self.anchor["text"].append(" " + attrs["alt"] + " ")

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skip_depth = max(0, self.skip_depth - 1)
            return
        shown = not self.concealed
        if tag == "a":
            self._close_anchor()
        open_ = self.at.get(tag)
        if open_ and (tag in self.SPECIAL or self.stack[-1][3] <= open_[-1]):
            self._pop_to(open_[-1])
        if shown and tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if self.skip_depth or self.concealed or self.zero:
            return
        self.parts.append(data)
        if self.anchor is not None:
            self.anchor["text"].append(data)

    def _close_anchor(self):
        if self.anchor is not None:
            href = INVISIBLE_RE.sub("", self.anchor["href"])
            if not href.lower().startswith(("javascript:", "data:")):
                self.links.append({"href": href, "text": clean_line(" ".join("".join(self.anchor["text"]).split()))})
            self.anchor = None

    def result(self) -> tuple[str, list[dict]]:
        self._close_anchor()
        return clean_block("".join(self.parts), keep_blank_lines=False), self.links


def html_to_text(html: str) -> tuple[str, list[dict]]:
    parser = HTMLText()
    parser.feed(html)
    parser.close()
    return parser.result()


def dedupe_links(links: list[dict]) -> list[dict]:
    seen: dict[str, dict] = {}
    for link in links:
        existing = seen.get(link["href"])
        if existing is None:
            seen[link["href"]] = dict(link)
        elif not existing["text"] and link["text"]:
            existing["text"] = link["text"]
    return list(seen.values())


def part_text(part) -> str:
    try:
        content = part.get_content()
    except (LookupError, UnicodeError, ValueError):  # an unknown or wrong charset
        payload = part.get_payload(decode=True) or b""
        content = payload.decode("utf-8", errors="replace")
    return content if isinstance(content, str) else ""


# The sender's own words. A reply holds the history it answers; that history was written by someone else, earlier, and is not what the sender
# of this message said. The forms below are the attribution lines and markers the common mail clients write.
ATTRIBUTION = re.compile(
    r"^(?:on|em|el)\b.{1,400}\b(?:wrote|escreveu|escribi[oó]):$",      # validate: allow english-only -- attribution forms of Portuguese and Spanish mail clients
    re.I)
MARKERS = re.compile(
    r"^(?:[-_=]{10,}|[-_=* ]{0,40}(?:"
    r"original message|forwarded message|begin forwarded message:?|"
    r"mensagem original|mensagem encaminhada|mensagem reenviada|in[ií]cio da mensagem (?:reenviada|encaminhada):?|"      # validate: allow english-only -- forward markers of Portuguese mail clients
    r"mensaje original|mensaje reenviado|mensaje remitido|inicio del mensaje reenviado:?"      # validate: allow english-only -- forward markers of Spanish mail clients
    r")[-_=* ]{0,40})$", re.I)
HEADER_START = re.compile(r"^(?:from|de|von):", re.I)
HEADER_FOLLOW = re.compile(r"^(?:sent|date|to|cc|subject|enviado|enviada|enviado el|data|para|assunto|asunto|fecha):", re.I)


def strip_quoted(text: str) -> str:
    """The text before the first quoted line (`>`), signature delimiter (`-- `), attribution ("On ... wrote:", "Em ... escreveu:",
    "El ... escribio:", on one line or two), forward or original-message marker, or Outlook header block (From: then Sent:/To:/Subject:)."""
    lines = text.split("\n")
    for i, line in enumerate(lines):
        bare = line.strip()
        joined = (bare + " " + lines[i + 1].strip()).strip() if i + 1 < len(lines) else bare
        if bare.startswith(">") or bare == "--" or MARKERS.match(bare) or ATTRIBUTION.match(bare) \
                or (bare.lower().split(" ", 1)[0] in ("on", "em", "el") and ATTRIBUTION.match(joined)) \
                or (HEADER_START.match(bare) and any(HEADER_FOLLOW.match(n.strip()) for n in lines[i + 1:i + 5])):
            return "\n".join(lines[:i]).strip("\n")
    return text.strip("\n")
