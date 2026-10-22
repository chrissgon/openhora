#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The text of a new e-mail worded by the model from what the person described (slice S7), and the seed that opens its card from the interpreter's decision.

The maintainer's rule (2026-10-20): for an e-mail he describes what it should say and the AI writes the better-worded text. It is a second call on the SAME daily route
the interpreter uses (runtime/ops_interpret.py), with its own fixed prompt (runtime/mail_compose_prompt.txt), and it is only ever a proposal: the card shows the From, the
To, the Subject and the WHOLE text, and nothing is sent until the person approves that card by its hash (limit L55). Nothing here sends, approves or opens a card.

  seed(op, decision, line)          the seed of `ops_natural_writes.open_line` for a new mail the interpreter decided (mail-send, mail-draft with no message), or None
                                    (a reply draft, and any other operation, go through `open_line(..., hint=op)` as before). The slots are read from the decision's spans, which
                                    `interpreter.check` already proved are substrings of the line; here the recipient is checked again: an address is taken only when it is one
                                    the sender typed, as a whole address token of the line (`natural_writes_mail.tokenize`); a word without `@` becomes a name the family asks
                                    the address of; anything else with `@` is dropped and the family asks. The seed sets `_compose` (and `_ai_subject` when the person gave no subject).
  strip_marker(text)                (text, True) when the person's text starts with the closed marker of a literal text ("exact text:", "texto exato:", and the same in es, fr, de,
                                    it): the marker is removed and the rest is sent as written; else (text, False)
  available(ctx, channel, sender)   whether composing is on for this sender now: the interpreter is on for them (messaging, the group `interpret`, the newest entry of
                                    runtime/interpreter_enable.json in force) AND that entry pins THIS prompt's sha256 (`compose_prompt_sha256`). A changed prompt turns composing
                                    off and leaves the interpreter on
  write(ctx, channel, sender, to, subject, text, ai_subject)
                                    {"subject": str | None, "body": str, "composed": bool}. The model is called once, through the same limits as the interpreter's (the sender's
                                    rate, the project's day, the breaker: `ops_interpret._admit` and `_record`). When the call is not made, fails or the answer is not valid, the
                                    person's own text is the body and the subject is the one the person gave, or, when the seed left it to the model (`ai_subject`), the first sentence of the person's own
                                    words cut at 60 characters (None when the person gave none and the seed did not ask the model: the family asks)
  validate(text, to, subject)       {"subject", "body"} for the model's text, or None. Code decides: strict JSON with exactly the two keys; a subject of one line; a body of
                                    plain text of at most 4000 characters; no header line, no HTML, no code fence, no link, no web address and no e-mail address other than the
                                    recipients the person typed; nothing the card refuses (`send_document.text_problem`). A body that ends with a closing formula alone
                                    ("Atenciosamente,", "Best regards,", a bracketed placeholder name...) loses those last lines (`without_dangling_close`): a name after the
                                    formula keeps it
  spelled(typed, shown)             the subject the person typed, with its spelling fixed when the model's `shown` is the SAME subject (S12): after NFKC, accent stripping and case
                                    folding the same words in the same order, none added or removed, each within a small edit distance (0 for a word of 1-2 letters, 1 up to 6, 2
                                    above; a word with a digit exactly), a name's capital letters as typed (only the first letter of the first word may become a capital), and the
                                    checks of a model-written subject; else `typed`

What the model may see: five lines made of the date, the chat's language, the typed recipient addresses, the subject span (or empty) and the person's own words for the body
(at most 1000 characters, else the text is sent as written). Never a message of the mailbox, a file, or any third-party text.

Privacy (limit L63, D2): the person's words go to the model provider under the same retention terms the group `interpret` was widened with, exactly as the interpreter's line
does. Nothing is logged, printed or written by this file: no span, no composed text, no exception message. The composed text exists in memory until the family opens the card,
which stores it as it stores every card (the card is the one record of an e-mail, runtime/send_document.py); the draft that waits for a question is the family's, in memory only.

Standard library only (the other modules are imported when a function needs them). Runs on Python 3.9: python3 runtime/mail_compose.py --help
"""
from __future__ import annotations

import hashlib
import importlib
import json
import os
import re
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
PROMPT_FILE = os.path.join(HERE, "mail_compose_prompt.txt")
NEW_MAIL = ("mail-send", "mail-draft")
PARAMS = {"temperature": 0.3, "max_tokens": 700, "reasoning": "off"}
DEADLINE_MS = 6000
DESCRIPTION_MAX = 1000        # characters of the person's own words that are sent (the interpreter's own limit for a line); a longer text is already an e-mail and is sent as written
SUBJECT_MAX = 200
SUBJECT_FALLBACK = 60         # characters of the person's own first sentence that stand as the subject when the model gave none
BODY_MAX = 4000
OUTPUT_MAX = 8192             # bytes of the model's answer that are read
DAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
MARKER = re.compile(r"\s*(?:exact\s+text|texto\s+exato|texto\s+exacto|texte\s+exact|genauer\s+text|testo\s+esatto)\s*:\s*", re.I)
FENCE = re.compile(r"```json[ \t]*\r?\n(.*?)\r?\n?```\s*", re.S)
HEADER = re.compile(r"^\s*(?:to|cc|bcc|from|subject|reply-to|in-reply-to|references|date|received|message-id|mime-version|content-[a-z-]+|x-[a-z0-9-]+|assunto|para|cco)\s*:",
                    re.I | re.M)
HTML = re.compile(r"</?[a-z][a-z0-9]*(?:\s[^>]*)?/?>|<!--", re.I)
LINK = re.compile(r"(?i:[a-z][a-z0-9+.-]*://|\bwww\.|\bmailto:)|(?<![\w.-])[^\W_](?:[\w-]*[^\W_])?(?:\.[\w-]+)*\.[^\W\d_]{2,24}\b")      # a scheme or "www." in any case; a name.tld in any case and any script (a false hit only falls back)
FORWARDED = re.compile(r"\s*(?:re|fwd?|res|enc|rv|aw|wg|vs)\s*:", re.I)      # a model-written subject must not pose as a reply or a forward
WHITE = re.compile(r"\s+")
PLACEHOLDER = re.compile(r"\[[^\]\n]{1,40}\]")      # "[Your name]": a signature the model left for the person to fill
CLOSINGS = frozenset((      # the closing formulas of the six languages, folded (_fold); a last line that is one of these, with or without a comma, closes nothing
    "atenciosamente", "abracos", "abraco", "um abraco", "att", "att.", "cordialmente", "obrigado", "obrigada", "cordiais saudacoes", "saudacoes",
    "best regards", "regards", "kind regards", "warm regards", "best wishes", "sincerely", "yours sincerely", "yours truly", "thanks", "thank you", "best", "cheers",
    "saludos", "un saludo", "saludos cordiales", "atentamente", "cordiales saludos", "gracias",
    "cordialement", "bien cordialement", "bien a vous", "merci", "cordiales salutations", "bien a toi",
    "mit freundlichen grussen", "freundliche grusse", "viele grusse", "beste grusse", "mit besten grussen", "liebe grusse", "danke",
    "cordiali saluti", "distinti saluti", "saluti", "un caro saluto", "grazie", "a presto"))


def prompt_template() -> str:
    with open(PROMPT_FILE, encoding="utf-8") as handle:
        return handle.read()


def prompt_sha256() -> str:
    """The sha256 of the compose prompt's bytes: the version that interpreter_enable.json pins."""
    with open(PROMPT_FILE, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def _fold(text: str) -> str:
    """The text as the spelling check compares it: NFKC, case folded, accents removed."""
    folded = unicodedata.normalize("NFD", unicodedata.normalize("NFKC", text).casefold())
    return unicodedata.normalize("NFC", "".join(c for c in folded if unicodedata.category(c) != "Mn"))


def _bare(text: str) -> str:
    """The text with its accents removed and its capitals kept (a name's case is compared on this)."""
    return "".join(c for c in unicodedata.normalize("NFD", unicodedata.normalize("NFKC", text)) if unicodedata.category(c) != "Mn")


def _distance(a: str, b: str) -> int:
    """The Damerau-Levenshtein distance (adjacent swaps count one) of two short words."""
    rows = [[j for j in range(len(b) + 1)]] + [[i] + [0] * len(b) for i in range(1, len(a) + 1)]
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            rows[i][j] = min(rows[i - 1][j] + 1, rows[i][j - 1] + 1, rows[i - 1][j - 1] + (a[i - 1] != b[j - 1]))
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                rows[i][j] = min(rows[i][j], rows[i - 2][j - 2] + 1)
    return rows[len(a)][len(b)]


def _same_words(typed: str, shown: str) -> bool:
    """Whether `shown` is `typed` with its spelling fixed (see `spelled`)."""
    before, after = re.findall(r"[^\W_]+", _fold(typed)), re.findall(r"[^\W_]+", _fold(shown))
    raw_before, raw_after = re.findall(r"[^\W_]+", _bare(typed)), re.findall(r"[^\W_]+", _bare(shown))
    if not before or len(before) != len(after) or len(raw_before) != len(raw_after) or len(before) != len(raw_before):
        return False
    for at, (old, new) in enumerate(zip(before, after)):
        allowed = 0 if any(c.isdigit() for c in old + new) else (0 if len(old) <= 2 else 1 if len(old) <= 6 else 2)
        if _distance(old, new) > allowed:
            return False
        was, now = raw_before[at], raw_after[at]
        if old == new:
            if was != now and not (at == 0 and was[:1].islower() and now == was[:1].upper() + was[1:]):
                return False      # only the accent may change, not the capitals
        elif (was[:1].isupper() != now[:1].isupper() and not (at == 0 and was[:1].islower())) or was.isupper() != now.isupper():
            return False
    return True


def _subject_problem(shown: str) -> bool:
    """Whether a model-written subject cannot stand: empty, long, several lines, an address, a link, a header, markup, a reply or forward mark, or what the card refuses."""
    return bool(not shown or len(shown) > SUBJECT_MAX or "\n" in shown or "@" in shown or "=?" in shown or FORWARDED.match(shown) or HEADER.search(shown) or HTML.search(shown)
                or LINK.search(_plain(shown)) or _problem(shown, False))


def spelled(typed: str, shown) -> str:
    """The subject the person typed with its spelling fixed when the model's `shown` is the same subject (see the module's text), else the typed one."""
    if not isinstance(shown, str):
        return typed
    shown = shown.strip()
    return shown if shown != typed and not _subject_problem(shown) and _same_words(typed, shown) else typed


def without_dangling_close(body: str) -> str:
    """The body without the closing formula that has nothing after it (and the bracketed placeholder name that may follow it): "Atenciosamente," as the last line is dropped,
    a closing followed by a name stays, a finished courtesy sentence ("Obrigado.") stays."""
    lines = body.split("\n")
    while lines:
        last = lines[-1].strip()
        if last and not PLACEHOLDER.fullmatch(last) and _fold(last).rstrip(",").strip() not in CLOSINGS:
            break
        lines.pop()
    return "\n".join(lines).strip()


def strip_marker(text):
    """(the text without the marker, True) when it starts with the closed marker of a literal text, else (text, False)."""
    found = MARKER.match(text or "")
    return (text[found.end():].strip(), True) if found else (text, False)


# --- the seed ------------------------------------------------------------------------------------------------------------------------------------


def _plain(text: str) -> str:
    """The text with the full-width and ideographic forms read as the plain ones (NFKC, and the ideographic full stops as dots), the form every check below looks at."""
    return unicodedata.normalize("NFKC", text).replace("\u3002", ".").replace("\uff61", ".")


def _typed_address(span: str, line: str):
    """The address as the sender typed it (capitals kept) when `span` is a whole address token of the line, compared without regard to case, else None."""
    nwm = importlib.import_module("natural_writes_mail")
    for tok in nwm.tokenize(line) or []:
        typed = line[tok.start:tok.end]
        if tok.kind == "addr" and tok.value.lower() == span.lower() and typed.lower() == span.lower():
            return typed
    return None


def seed(op: str, decision: dict, line: str):
    """The seed of a new mail (see the module's text), or None when the operation is not a new mail."""
    spans = decision.get("spans") or {}
    if op not in NEW_MAIL or "message" in spans or "message" in (decision.get("args") or {}) or (op == "mail-draft" and not spans.get("to")):
        return None      # a draft with no recipient may be a reply draft the model could not name a message for: the closed forms decide, as before
    slots = {}
    to = spans.get("to")
    if to:
        typed = _typed_address(to, line)
        if typed:
            slots["to"] = [typed]
        elif "@" not in to:
            slots["to_names"] = [to]
    subject = " ".join((spans.get("subject") or "").split())
    if subject:
        slots["subject"] = subject
    if spans.get("body"):
        slots["body"] = spans["body"]
    slots["_compose"] = True
    if not subject:
        slots["_ai_subject"] = True
    return {"op": op, "slots": slots}


# --- the call ------------------------------------------------------------------------------------------------------------------------------------


def available(ctx: dict, channel, sender) -> bool:
    """Whether the model words an e-mail for this sender now (see the module's text). Any fault is "no"."""
    try:
        interpret = importlib.import_module("ops_interpret")
        enable = importlib.import_module("interpreter_enable")
        return bool(interpret.enabled(ctx, channel, sender)) and enable.compose_active(interpret._tag(ctx["cfg"])) is not None
    except Exception:      # noqa: BLE001
        return False


def _call(entry: dict, system: str, user: str) -> dict:
    """The one model call: the entry's daily route (kind http, the hash the entry was decided on), as ops_interpret._daily_call does it, with this file's settings."""
    route = importlib.import_module("interpreter_route")
    rows = [r for r in route.daily_routes() if r["id"] == entry["route"]]
    if len(rows) != 1 or rows[0].get("kind") != "http" or route.route_sha256(rows[0]) != entry["route_sha256"]:
        return {"ok": False, "code": "E_ROUTE"}
    return route.complete(rows[0]["id"], system, user, accepted=[entry["route_sha256"]], deadline_ms=DEADLINE_MS, **PARAMS)


def _pairs(pairs) -> dict:
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("repeated key")
        out[key] = value
    return out


def _problem(text: str, multiline: bool) -> bool:
    """Whether a text cannot be on the card as it is (the card's own check, runtime/send_document.py)."""
    send_document = importlib.import_module("send_document")
    return bool(send_document.text_problem(text, multiline))


def validate(text, to, subject=None):
    """{"subject", "body"} for the model's text, or None (see the module's text). `to` is the list of typed recipient addresses; `subject` the person's, when given."""
    if not isinstance(text, str) or len(text.encode("utf-8")) > OUTPUT_MAX:
        return None
    found = FENCE.fullmatch(text.strip())
    try:
        obj = json.loads(found.group(1) if found else text, object_pairs_hook=_pairs, parse_constant=lambda _name: (_ for _ in ()).throw(ValueError("constant")))
    except (ValueError, RecursionError):
        return None
    if not isinstance(obj, dict) or set(obj) != {"subject", "body"} or not all(isinstance(obj[k], str) for k in obj):
        return None
    body = without_dangling_close(obj["body"].replace("\r\n", "\n").replace("\r", "\n").strip())
    shown = obj["subject"].strip()
    if not body or len(body) > BODY_MAX or "```" in body or HTML.search(body) or HEADER.search(body) or _problem(body, True):
        return None
    clean = _plain(body)      # a full-width "@" or dot is read as the plain one
    for address in to:
        clean = re.sub(r"(?<![\w.+-])" + re.escape(unicodedata.normalize("NFKC", address)) + r"(?![\w-])(?!\.[\w])", "", clean, flags=re.I)      # only the whole typed address
    if "@" in clean or LINK.search(clean):
        return None
    if subject is None and _subject_problem(shown):
        return None
    return {"subject": spelled(subject, shown) if subject is not None else shown, "body": body}


def _subject_of(described: str) -> str:
    """The subject when the model gave none: the first sentence of the person's own words, cut at a word within SUBJECT_FALLBACK characters."""
    first = re.split(r"(?<=[.!?])\s", described, maxsplit=1)[0]
    if len(first) > SUBJECT_FALLBACK:
        cut = first[:SUBJECT_FALLBACK + 1]
        first = cut.rsplit(" ", 1)[0] if " " in cut else cut[:SUBJECT_FALLBACK]
    return "" if "=?" in first else first.rstrip(".!?,;: ")


def write(ctx: dict, channel, sender, to, subject, text: str, ai_subject: bool = False) -> dict:
    """The subject and the body of the e-mail (see the module's text). Never raises, never blocks: the person's own words are the fallback."""
    body, exact = strip_marker(text)
    described = WHITE.sub(" ", body).strip()
    out = {"subject": subject or (_subject_of(described) if ai_subject and described else None), "body": body, "composed": False}
    if exact or not described or len(described) > DESCRIPTION_MAX or not available(ctx, channel, sender):
        return out
    interpret = importlib.import_module("ops_interpret")
    if not interpret._admit(ctx, sender):
        return out
    proposal, ok = None, False
    try:
        enable = importlib.import_module("interpreter_enable")
        entry = enable.compose_active(interpret._tag(ctx["cfg"]))["entry"]
        now = importlib.import_module("ops_natural")._clock()
        user = "\n".join([f"date: {now.strftime('%Y-%m-%d')} {DAY_NAMES[now.weekday()]}", f"language: {interpret._tag(ctx['cfg'])}", "to: " + ", ".join(to),
                          "subject: " + (subject or ""), "description: " + described])
        got = _call(entry, prompt_template(), user)
        ok = bool(got.get("ok"))
        if ok:
            proposal = validate(got.get("text"), to, subject or None)
    except Exception:      # noqa: BLE001 - nothing of the fault is kept: it can hold the person's words
        ok, proposal = False, None
    interpret._record(ok)
    if proposal is None:
        return out
    return {"subject": proposal["subject"] or out["subject"], "body": proposal["body"], "composed": True}


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
