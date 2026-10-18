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
  HIDDEN_STYLE_RE, style_hides   an inline style that hides an element from a reader (display:none, visibility:hidden, mso-hide:all, a zero
                             font-size, opacity:0, a zero width or height, a zero max-height or max-width with overflow:hidden)
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
# person never sees, so it is not message text. The declarations that hide by themselves: display:none, visibility:hidden, the Outlook
# mso-hide:all, a zero font-size, opacity:0 and a zero width or height (a number, with or without a unit, that is zero).
_ZERO = r"0(?:\.0+)?(?:px|pt|em|rem|ex|ch|%)?"
HIDDEN_STYLE_RE = re.compile(r"(?:^|;)\s*(?:display\s*:\s*none|visibility\s*:\s*hidden|mso-hide\s*:\s*all|font-size\s*:\s*" + _ZERO
                             + r"|opacity\s*:\s*0(?:\.0+)?|(?:width|height)\s*:\s*" + _ZERO + r")\s*(?:!\s*important\s*)?(?:;|$)", re.I)
# A zero max-height or max-width hides only together with overflow:hidden (the preheader trick); alone it hides nothing.
MAX_ZERO_RE = re.compile(r"(?:^|;)\s*max-(?:height|width)\s*:\s*" + _ZERO + r"\s*(?:!\s*important\s*)?(?:;|$)", re.I)
OVERFLOW_HIDDEN_RE = re.compile(r"(?:^|;)\s*overflow(?:-[xy])?\s*:\s*hidden\s*(?:!\s*important\s*)?(?:;|$)", re.I)


def style_hides(style: str) -> bool:
    """Whether an inline style hides the element it is on (see HIDDEN_STYLE_RE). A style sheet rule, a class, a colour and a position off the
    page are not looked at."""
    return bool(HIDDEN_STYLE_RE.search(style) or (MAX_ZERO_RE.search(style) and OVERFLOW_HIDDEN_RE.search(style)))


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
    """Text and links of an HTML body, with the standard library parser (no script is run). An element hidden by an
    inline display:none or visibility:hidden style, or by the hidden attribute, gives no text and no link."""

    SKIP = {"script", "style", "head", "title", "template", "noscript"}
    BLOCK = {"p", "div", "br", "tr", "li", "ul", "ol", "table", "h1", "h2", "h3", "h4", "h5", "h6",
             "blockquote", "section", "article", "header", "footer", "hr", "td", "th"}

    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.links: list[dict] = []
        self.skip_depth = 0
        self.anchor: dict | None = None
        # The hidden element being skipped: its tag, and how many elements of that tag are open inside it.
        self.hidden_tag: str | None = None
        self.hidden_depth = 0

    @staticmethod
    def hidden(attrs: dict) -> bool:
        return "hidden" in attrs or style_hides(attrs.get("style") or "")

    def handle_starttag(self, tag, attrs):
        if self.hidden_tag is not None:
            if tag != self.hidden_tag:
                return
            if tag != "p":  # a <p> cannot hold another one: a new <p> closes the hidden one
                self.hidden_depth += 1
                return
            self.hidden_tag, self.hidden_depth = None, 0
        if tag in self.SKIP:
            self.skip_depth += 1
            return
        attrs = dict(attrs)
        if self.hidden(attrs):
            if tag not in self.VOID:
                self.hidden_tag, self.hidden_depth = tag, 1
            return
        if tag in self.BLOCK:
            self.parts.append("\n")
        if tag == "a":
            self._close_anchor()
            href = (attrs.get("href") or "").strip()
            self.anchor = {"href": href, "text": []} if href else None
        elif tag == "img" and self.anchor is not None and attrs.get("alt"):
            self.anchor["text"].append(" " + attrs["alt"] + " ")

    def handle_endtag(self, tag):
        if self.hidden_tag is not None:
            if tag == self.hidden_tag:
                self.hidden_depth -= 1
                if self.hidden_depth == 0:
                    self.hidden_tag = None
            return
        if tag in self.SKIP:
            self.skip_depth = max(0, self.skip_depth - 1)
            return
        if tag == "a":
            self._close_anchor()
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if self.skip_depth or self.hidden_tag is not None:
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
