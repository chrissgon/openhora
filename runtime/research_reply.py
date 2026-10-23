#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The reply of a web research, written by code (slice R2-F1): what the research skill left becomes a few plain lines and the links of its sources.

The skill `core-research` replies in its own form (a capability line, "Answer in brief" lines with a kind, a source number and a confidence) and writes its brief to
`docs/workbench/research/<topic>.md` in the copy of the run, with the sources and their URLs. A chat is not given that form: this module reads the brief (and, when the brief is
not there, the reply's own lines) and writes the answer in plain words, then the sources as short links, within the limit of a message. It is pure: it opens one folder of a copy,
calls nothing and keeps nothing. The model's words are data: a line is cleaned (a link, a code span, a path, a skill or a file name never reaches the chat), the links are the
ones of the brief's source list only, checked as links (http or https, a host with a dot and no address, no user name, no tracking parameter, at most LINK_MAX characters), and
the section "Instructions found in external content" of the skill's reply is never read.

  read_brief(cwd)                         the text of the newest brief under <cwd>/docs/workbench/research/, or None (a link, a folder that leaves the copy, or a file over BRIEF_MAX is never read)
  parse(response, brief)                  {"status", "claims": [{"text", "kind", "confidence", "cites": [n]}], "links": {n: short link}}; status is one of
                                          answer | no-web | ask-again | nothing | unreadable
  render(parsed, cfg, proven, limit)      the reply: the claims, the sources, and, when the run is not proven, one sentence that says so; within `limit` characters
  short_link(url)                         the link as it is shown, or None when it is not a link a chat may carry

Standard library only. Runs on Python 3.9: python3 runtime/research_reply.py --help
"""
from __future__ import annotations

import ipaddress
import os
import re
import sys
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import card_words  # noqa: E402  (the same folder: the closed list of the words that decide a card)
import phrases  # noqa: E402  (the same folder)

BRIEF_DIR = ("docs", "workbench", "research")
BRIEF_MAX = 128 * 1024          # bytes of a brief that are read
CLAIMS_MAX = 6                  # claims a reply carries
LINKS_MAX = 5                   # links a reply carries
LINK_MAX = 120                  # characters of a link as it is shown
CLAIM_MAX = 400                 # characters of one claim
TRACKING = re.compile(r"(?:utm_[a-z0-9_]+|fbclid|gclid|dclid|msclkid|mc_cid|mc_eid|igshid|ref_src|ref_url)", re.I)
URL = re.compile(r"https?://[^\s<>\"'`)\]]+", re.I)
UNSAFE_URL = re.compile(r"[^\x21-\x7e]|[<>\"'`\\^{}|]")      # anything but printable ASCII (a space, a control, a bidi override, any Unicode format character) and the characters a chat or a URL cannot carry
LOCAL_SUFFIXES = (".local", ".localhost", ".internal", ".lan", ".home", ".corp", ".intranet")
# What a chat is never shown: a path of the project, the skill, a file of the brief, a code span, the workbench.
NOT_FOR_A_CHAT = re.compile(r"docs/|core-research|SKILL\.md|\.md\b|\.json\b|workbench|check_brief|```|Instructions found in external content", re.I)
KINDS = ("fact", "estimate", "opinion")
CONFIDENCE = re.compile(r"[—–-]+\s*confidence:\s*(high|medium|low)\b[^\n]*$", re.I)
CITE = re.compile(r"\[(\d{1,3})(?:\s+single-source)?\]")
KIND_TAG = re.compile(r"\((fact|estimate|opinion)\)", re.I)
CAPABILITY = re.compile(r"Search capability:\s*([A-Za-z]+)", re.I)
# What would read as a decision of the person's, or as a card, in a chat: a slash line, a whole card word (runtime/card_words.py, "sim", "approve"...), a card's number or hash, a command of
# the decisions anywhere in the line. A claim of that shape is dropped, never sent.
CARD_LIKE = re.compile(r"^\s*#\d+|(?:^|\s)/(?:approve|reject|release|answer|go-ahead|cancel|retry|stop-task|set-mode|pending|add|discard)\b|\b[0-9a-f]{64}\b", re.I)
NOTHING_NEW = re.compile(r"^-?\s*Nothing established\b", re.I)
ASKS = re.compile(r"Nothing was written and nothing was searched", re.I)


def read_brief(cwd: str):
    """The text of the newest brief (a regular `.md` file, not a link, whose real path stays in the copy, at most BRIEF_MAX bytes) under <cwd>/docs/workbench/research/, or None."""
    if not isinstance(cwd, str) or not cwd:
        return None
    root = os.path.realpath(cwd)
    folder = os.path.join(cwd, *BRIEF_DIR)
    try:
        if os.path.islink(folder) or not os.path.isdir(folder):
            return None
        entries = list(os.scandir(folder))
    except OSError:
        return None
    best = None
    for entry in entries:
        try:
            if not entry.name.endswith(".md") or entry.is_symlink() or not entry.is_file(follow_symlinks=False):
                continue
            real = os.path.realpath(entry.path)
            info = entry.stat(follow_symlinks=False)
        except OSError:
            continue
        if not real.startswith(root + os.sep) or info.st_size > BRIEF_MAX:
            continue
        key = (info.st_mtime_ns, entry.name)
        if best is None or key > best[0]:
            best = (key, entry.path)
    if best is None:
        return None
    try:
        with open(best[1], encoding="utf-8", errors="replace") as f:
            return f.read(BRIEF_MAX + 1)
    except OSError:
        return None


def short_link(url):
    """The link as a chat shows it, or None. A link is http or https, has a host of letters with a dot (never an address, a local name, a user name or a port other than the default), and
    holds no space, quote, bracket or control character. The fragment and the tracking parameters (utm_*, fbclid, gclid...) are dropped; a link over LINK_MAX characters loses
    its query, then its path, and what is left is the site itself."""
    if not isinstance(url, str) or not url or len(url) > 2000 or UNSAFE_URL.search(url):
        return None
    try:
        parts = urllib.parse.urlsplit(url)
        port = parts.port
    except ValueError:
        return None
    host = (parts.hostname or "").lower().rstrip(".")
    if parts.scheme.lower() not in ("http", "https") or not host or "@" in parts.netloc or port not in (None, 80, 443):
        return None
    if "." not in host or host.endswith(LOCAL_SUFFIXES) or host == "localhost" or not re.fullmatch(r"[a-z0-9.-]+", host) or ".." in host or host.startswith((".", "-")):
        return None
    try:
        ipaddress.ip_address(host)
        return None          # an address is not a source a person can read
    except ValueError:
        pass
    pieces = [p for p in parts.query.split("&") if p and not TRACKING.fullmatch(p.split("=", 1)[0])]
    base = f"{parts.scheme.lower()}://{host}"
    path = parts.path if parts.path not in ("", "/") else ""
    for candidate in (base + path + ("?" + "&".join(pieces) if pieces else ""), base + path, base):
        if len(candidate) <= LINK_MAX:
            return candidate
    return None


def _section(text: str, heading: str) -> list:
    """The lines under `## <heading>` of a Markdown text, up to the next `## `."""
    out, inside = [], False
    for line in text.splitlines():
        if line.startswith("## "):
            if inside:
                break
            inside = line[3:].strip().lower().startswith(heading.lower())
            continue
        if inside:
            out.append(line)
    return out


def _bullets(lines: list) -> list:
    return [re.sub(r"^\s*[-*]\s+", "", line).strip() for line in lines if re.match(r"^\s*[-*]\s+\S", line)]


def _reply_lines(response: str) -> list:
    """The lines the skill's reply gives under "Answer in brief" (the line that starts with the words, and the bullets that follow it)."""
    out, inside = [], False
    for line in (response or "").splitlines():
        head = re.match(r"^\s*(?:[-*]\s*)?Answer in brief:?\s*(.*)$", line, re.I)
        if head:
            inside = True
            if head.group(1).strip():
                out.append(head.group(1).strip())
            continue
        if inside:
            if re.match(r"^\s*[-*]\s+\S", line) and not re.match(r"^\s*[-*]\s*(Unknowns|Consumer|Brief)\b", line, re.I):
                out.append(re.sub(r"^\s*[-*]\s+", "", line).strip())
            elif line.strip():
                break
    return out


def _capability(response: str, brief) -> object:
    found = CAPABILITY.search((response or "")[:800])
    if found is None and brief:
        found = CAPABILITY.search(brief)
    return found.group(1).lower() if found else None


def _claim(line: str):
    """{"text", "kind", "confidence", "cites"} of one answer line, or None when nothing is left of it once it is cleaned."""
    kind = KIND_TAG.search(line)
    confidence = CONFIDENCE.search(line)
    cites = [int(n) for n in CITE.findall(line)]
    text = CONFIDENCE.sub("", line)
    text = KIND_TAG.sub("", text)
    text = CITE.sub("", text)
    text = URL.sub("", text)
    text = re.sub(r"`+|\*{1,3}|__", "", text)      # code spans, bold and italics (an underscore inside a word stays)
    text = re.sub(r"\s+", " ", text).strip().rstrip(" —–-,;:")
    if not text or NOT_FOR_A_CHAT.search(text) or NOTHING_NEW.match(text) or text.startswith("/") or CARD_LIKE.search(text) or card_words.card_word(text) is not None:
        return None
    if len(text) > CLAIM_MAX:
        text = text[:CLAIM_MAX - 1].rstrip() + "…"
    return {"text": text, "kind": kind.group(1).lower() if kind else "fact", "confidence": confidence.group(1).lower() if confidence else None,
            "cites": [n for i, n in enumerate(cites) if n not in cites[:i]]}


def parse(response, brief) -> dict:
    """What the skill left, as data: {"status", "claims", "links"}. `response` is the skill's reply, `brief` the text read_brief gave (or None).
    answer      claims were read (and links, as many as the brief's source list gave)
    no-web      the skill's reply or its brief says the search was not full (no search, or a limited brief): nothing is answered from it
    ask-again   the skill asked for the question to be said again (its stop rule); nothing was searched
    nothing     the skill established nothing
    unreadable  no claim could be read"""
    response = response if isinstance(response, str) else ""
    if ASKS.search(response):
        return {"status": "ask-again", "claims": [], "links": {}}
    capability = _capability(response, brief)
    limited = bool(brief) and re.search(r"^\s*-?\s*Status:\s*limited\b", brief, re.I | re.M) is not None
    if (capability is not None and capability != "full") or limited:
        return {"status": "no-web", "claims": [], "links": {}}
    lines = _bullets(_section(brief, "Answer in brief")) if brief else []
    if not lines:
        lines = _reply_lines(response)
    if not lines:
        return {"status": "unreadable", "claims": [], "links": {}}
    if all(NOTHING_NEW.match(line) for line in lines):
        return {"status": "nothing", "claims": [], "links": {}}
    if capability is None and brief is None:
        return {"status": "unreadable", "claims": [], "links": {}}
    claims = [c for c in (_claim(line) for line in lines) if c][:CLAIMS_MAX]
    if not claims:
        return {"status": "unreadable", "claims": [], "links": {}}
    links = {}
    for line in _section(brief, "Sources") if brief else []:
        head = re.match(r"^\s*\[(\d{1,3})\]\s", line)
        found = URL.search(line)
        if head and found:
            link = short_link(found.group(0).rstrip(".,;:"))
            if link and int(head.group(1)) not in links:
                links[int(head.group(1))] = link
    return {"status": "answer", "claims": claims, "links": links}


def _cut(text: str, room: int) -> str:
    if len(text) <= room:
        return text
    room = max(room, 2)
    head = text[:room - 1]
    for mark in ("\n", " "):
        at = head.rfind(mark)
        if at > room // 2:
            head = head[:at]
            break
    return head.rstrip() + "…"


def render(parsed: dict, cfg, proven: bool, limit: int) -> str:
    """The reply for an `answer`: one line per claim (an estimate or an opinion says so, a claim of low confidence says so, and its source numbers close the line), the sources as short links
    (those a claim cites, at most LINKS_MAX), and, when the run is not proven, the sentence that says so. The claims are cut to leave room for the rest; the sources are never cut."""
    t = lambda key, **fields: phrases.text(key, cfg, **fields)  # noqa: E731
    lines, cited = [], []
    for claim in parsed["claims"]:
        marks = [t("RS_ESTIMATE")] if claim["kind"] == "estimate" else [t("RS_OPINION")] if claim["kind"] == "opinion" else []
        if claim["confidence"] == "low":
            marks.append(t("RS_LOW"))
        shown = [n for n in claim["cites"] if n in parsed["links"]]
        cited += [n for n in shown if n not in cited]
        lines.append(claim["text"] + (f" ({', '.join(marks)})" if marks else "") + ("".join(f" [{n}]" for n in shown)))
    cited = cited[:LINKS_MAX]
    tail = "\n\n" + (t("RS_SOURCES") + "\n" + "\n".join(f"[{n}] {parsed['links'][n]}" for n in cited) if cited else t("RS_NO_LINKS"))
    if not proven:
        tail += "\n\n" + t("RS_UNPROVEN")
    return _cut("\n".join(lines), max(limit - len(tail), 40)) + tail


def main(argv=None) -> int:
    print(__doc__.strip(), file=sys.stdout if (argv or sys.argv[1:]) in (["--help"], ["-h"]) else sys.stderr)
    return 0 if (argv or sys.argv[1:]) in (["--help"], ["-h"]) else 2


if __name__ == "__main__":
    sys.exit(main())
