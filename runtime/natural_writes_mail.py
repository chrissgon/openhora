#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The mail family of the writes asked in words (package NR-5b, SPEC-NATURAL-WRITES 2 and 3.3 to 3.4): the closed forms of an e-mail sent, a reply, a draft, and the messages
of the person's own mailbox archived, moved, marked or sent to the trash. Pure: no clock, no store, no file, no log; the words are the language tables' (the key
`requests.writes.mail` of `runtime/natural_lang_<tag>.py`), lists of phrases and never a regular expression.

A line is a CLOSED HEAD followed by slots with closed markers, read by code from those lists:

    [polite]* VERB [article] [newest] NOUN  [REFERENCE]  { MARKER SLOT }*  [BODY-MARKER BODY]

The head is at the START of the line (a write word in the middle of a line is never a head). A text slot (a subject, a body) is the person's own words between two markers
or after the last marker to the end of the line, cut at its edges and never rewritten: `spans` hold them as written and `ranges` say where they are. A line is taken only when its family's required
slot is there, so a request for work that starts with the same verb ("manda um e-mail para todos os clientes sobre a promocao") is not taken and goes on as it did before. A
line with an `@` that is not a plain address, with more than WORDS_MAX words, with a time in the words outside its text slots (a scheduled send is not offered) or with a
reply to several messages is not taken either.

  HEADS(tables)                                  the folded phrases a mail line may start with (the verbs of the tables), longest first, for the order of recognition
  read(line, tables, now=None, op=None)          {"op", "slots", "spans" ({slot: the person's words}), "ranges" ({slot: (start, end)} in the folded line of natural_time.normalise),
                                                 "need", "engine" (None), "doubt" (False)} or None (the interface of runtime/natural_writes.py). Nothing is looked up: an address only as written in the line, a number only as digits
                                                 written in it, a message by words only as the words, a service only as a word of the tables. `slots` may hold `to` (addresses,
                                                 1 to 20), `to_names` (a recipient written as a name: its address is asked, never searched for), `subject`, `body`, `numbers`
                                                 and `refs` (the digits and the `<source>#<n>` references written), `over` (more than one card takes), `words` (what the person
                                                 said of the messages), `newest`, `plural`, `service` (google | microsoft), `state` (read | unread) and `folder_name` (as
                                                 written); `need` lists, in the order they are asked, the slots the line leaves open (to, subject, body, state)
  answer(need, line, slots, tables, now=None, options=None)   {"slots": the update} that a line makes when it answers the question `need`, or None when it is not an answer
  match_words(entries, words, newest, sender=())  the entries of a snapshot's index whose from-address words and subject words hold EVERY one of `words`, as whole words; with `sender`
                                                 (GROUNDING-FROM: the words of a person's name that a target was widened from) every one of those must also be a from-address word
                                                 (`from_words`: the local part and the domain labels but the last), never a subject word only
  plural_mentioned(text, tables)                 whether `text` holds a noun of the tables' `plural` list ("e-mails", "mensagens"), the words the closed form reads as several messages
  target_words(span, tables, cap=TARGET_WORDS_MAX)  the content words of a `target` span the interpreter verified (B''-lite): the span's words without the tables' articles, polite
                                                 words, joiners, mail nouns, plural words, "of" words and "newest" words, in order, none twice; [] when more than `cap`
                                                 (default TARGET_WORDS_MAX) are left (a sentence, not a name). They are compared with the index (`match_words`) only to choose
                                                 a message, never an address
  ground_words(span, tables)                     `target_words` with the cap GROUND_WORDS_MAX (BL7-5): the words of a sender and a subject the interpreter grounded (`target_ground`);
                                                 every one of them is still required by `match_words`, so a longer set only reaches fewer messages, never more
  free_numbers(line, spans=(), tables=None)      the numbers a line writes as MESSAGE numbers, in order, none twice (BL7-5): `#7`, a number right after a mail noun ("email 4", "mensagem 3"),
                                                 or one chained to such a number (written right after it, or after a joiner and an optional article: "emails 2 4 and the 7"); never a number inside one of `spans`
                                                 (texts of the line), inside a time phrase of `natural_time.find`, followed by a unit, a currency mark or "o'clock", or preceded by a
                                                 currency, and [] in a line with a range ("1-3", "1 a 3", "do 1 ao 3", "between 1 and 3") or when a time hit cannot be mapped to the line.
                                                 It is what a message number the model gave must equal (`ops_natural_mail.mail_number_seed`)
  check_mail(mail, where)                        ValueError when the `mail` part of `requests.writes` of a language table is not of the shape below
  NEEDS                                          the needs this family asks (the draft of the ask-back dispatches an answer to `answer` for these)

The data, `requests.writes.mail`: `send_verbs`, `reply_verbs`, `draft_verbs`, `archive_verbs`, `move_verbs`, `mark_verbs`, `trash_verbs`, `nouns`, `plural`, `to`, `subject`,
`body`, `of`, `folder`, `read`, `unread`, `newest`; each a list of phrases (lower case, no accent, single-spaced words, no character a regular expression uses). The shared
lists of `requests.writes` it reads are `polite`, `articles`, `joiners`, `range`, `service_in` and `services` (a service of two words names an account alone, one word needs a word of
`service_in` before it: `pelo gmail`).

External content is data: a message's from-address and subject (the index of a snapshot) are another person's words. Here they are only compared with the words of the person's
own line; they are never read as an instruction and never listed: the listing is made by runtime/ops_natural_mail.py after the caller's right to read the snapshot was checked.

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import bisect
import os
import re
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import mail_address  # noqa: E402
import natural  # noqa: E402
import natural_time as nt  # noqa: E402

WORDS_MAX = 120          # a longer line is a request for work, not a write form
LINE_MAX = 8000          # characters: room for a body of BODY_MAX and the words round it; a longer line is not read at all
SUBJECT_MAX = 200        # characters of a subject (send_document.SUBJECT_MAX)
BODY_MAX = 4000          # characters of a body written on a line
ADDRESSES_MAX = 20       # recipients in all (W2's cap)
MESSAGES_MAX = 20        # messages in one card (mailbox_document.MESSAGES_MAX)
NAME_WORDS_MAX = 3       # words of a recipient written as a name
NUMBER_DIGITS_MAX = 9
TEXT_WORDS_MAX = 12        # a subject is short: a longer line is a new line (natural.TEXT_MAX_WORDS, the limit of every text answer)
FOLDER_MAX = 64          # characters of a folder name written in a line
TARGET_WORDS_MAX = 6     # content words of a `target` span the interpreter verified: a message is named by a sender and a subject; a longer span is a sentence, not a name
GROUND_WORDS_MAX = 10    # BL7-5: content words of a sender and a subject the interpreter grounded (a sender of up to four words and a subject of up to six, interpreter.SUBJECT_WORDS_MAX): every one is still required
WORDS_CAP = 3            # content words of a message named by words ("o e-mail do banco itau"): a longer tail is a sentence, not a name
MAIL_KEYS = ("send_verbs", "reply_verbs", "draft_verbs", "archive_verbs", "move_verbs", "mark_verbs", "trash_verbs", "nouns", "plural", "to", "subject", "body", "of",
             "folder", "read", "unread", "newest", "date_words")
SHARED_KEYS = ("polite", "articles", "joiners", "range", "service_in")
VERB_OPS = (("send_verbs", "mail-send"), ("reply_verbs", "mail-reply"), ("draft_verbs", "mail-draft"), ("archive_verbs", "mail-archive"), ("move_verbs", "mail-move"),
            ("mark_verbs", "mail-mark"), ("trash_verbs", "mail-trash"))
STATES = ("read", "unread")
ACCOUNTS = ("google", "microsoft")
NEEDS = ("to", "subject", "body", "state")      # the needs the family answers itself; the options (account, mailbox, message, folder) are the foundation's
LEAD = "\"'([{<¿¡“‘«"
DROP_TAIL = ".!?)]}>\"'”’»"
PUNCT_TAIL = ",;:"
ITEM_REF = re.compile(r"([a-z0-9][a-z0-9-]{0,39})#([0-9]{1,4})")      # item_refs.ITEM_REF, written again: this module is pure and imports no operation
PHRASE_BAD = re.compile(r"[\\.*+{}^$\[\]()|?#@:,;!]")
CLOSING_QUOTES = "\"\u201d\u2019\u00bb"
QUOTES = (("\"", "\""), ("“", "”"), ("‘", "’"), ("«", "»"))


class Tok:
    """One token of a line: `norm` (folded, lower case), `kind` (word, num, ref, addr, punct, range) and where it is in the ORIGINAL line."""
    __slots__ = ("norm", "kind", "start", "end", "value")

    def __init__(self, norm, kind, start, end, value=None):
        self.norm, self.kind, self.start, self.end, self.value = norm, kind, start, end, value

    def __repr__(self):
        return f"Tok({self.norm!r},{self.kind})"


# --- the data ----------------------------------------------------------------------------------------------------------------------------


def check_mail(mail, where: str = "requests.writes.mail") -> None:
    """ValueError(sentence) when `mail` is not what this family reads: exactly the keys MAIL_KEYS, each a non-empty list of phrases of single-spaced lower-case ASCII words with
    no regular-expression character, no phrase twice in a list, no verb phrase in two lists of verbs, and `plural` a subset of `nouns`."""
    if not isinstance(mail, dict) or set(mail) != set(MAIL_KEYS):
        raise ValueError(f"{where} is a dict with exactly the keys {', '.join(MAIL_KEYS)}")
    seen = {}
    for key in MAIL_KEYS:
        value = mail[key]
        if not isinstance(value, list) or not value:
            raise ValueError(f"{where}.{key} is a non-empty list of phrases")
        for phrase in value:
            if not isinstance(phrase, str) or not phrase or phrase != " ".join(phrase.split()) or phrase != phrase.lower() or not phrase.isascii() or PHRASE_BAD.search(phrase):
                raise ValueError(f"{where}.{key}: {phrase!r} is not a phrase of single-spaced lower-case ASCII words with no regular-expression character")
        if len(set(value)) != len(value):
            raise ValueError(f"{where}.{key} lists a phrase twice")
        if key.endswith("_verbs"):
            for phrase in value:
                if phrase in seen:
                    raise ValueError(f"{where}: {phrase!r} is a verb of both {seen[phrase]} and {key}")
                seen[phrase] = key
    if not set(mail["plural"]) <= set(mail["nouns"]):
        raise ValueError(f"{where}.plural lists a noun that {where}.nouns does not")


_COMPILED = {}


def _phrases(values) -> list:
    """Phrases as tuples of words, the longest first (the longest phrase that fits wins)."""
    return sorted({tuple(v.split()) for v in values if isinstance(v, str) and v.strip()}, key=lambda p: (-len(p), p))


def _data(table):
    """The compiled lists of one language table, or None when the table has no mail part."""
    key = id(table)
    if key not in _COMPILED or _COMPILED[key][0] is not table:      # an id can be reused by another table once the first is gone
        writes = (table.get("requests") or {}).get("writes") or {}
        mail = writes.get("mail")
        if not isinstance(mail, dict) or not mail:
            _COMPILED[key] = (table, None)
        else:
            services = {account: _phrases(words) for account, words in (writes.get("services") or {}).items() if isinstance(words, list)}
            shared = {name: _phrases(writes.get(name) or []) for name in SHARED_KEYS}
            single = {name: {p[0] for p in shared[name] if len(p) == 1} for name in ("joiners", "range")}
            stop = {w for name in ("articles", "joiners") for p in shared[name] for w in p} | {w for v in mail.get("of") or [] for w in v.split()}
            work = {w for name in ("work_verbs", "work_starters") for phrase in table.get(name) or [] for w in str(phrase).split()}
            dates = {w for v in mail.get("date_words") or [] for w in v.split()} | {w for names in (table.get("days") or {}).values() for v in names for w in v.split()}
            dates |= {w for names in table.get("weekdays") or [] for v in names for w in v.split()} | {w for names in table.get("months") or [] for v in names for w in v.split()}
            dates -= stop | set(table.get("weak") or [])      # an abbreviation that is also a common word ("mar", "may") is no date here
            service_words = {w for phrases in services.values() for p in phrases for w in p} | {w for p in shared["service_in"] for w in p}
            _COMPILED[key] = (table, {"mail": {name: _phrases(mail.get(name) or []) for name in MAIL_KEYS}, "shared": shared, "services": services,
                                      "plural": {tuple(v.split()) for v in mail.get("plural") or []}, "joiners": single["joiners"], "range": single["range"], "stop": stop,
                                      "work": work, "dates": dates, "service_words": service_words})
    return _COMPILED[key][1]


def _tables_with_mail(tables) -> list:
    return [t for t in tables if _data(t) is not None]


def HEADS(tables) -> list:  # noqa: N802  (the name the family interface gives it)
    """The folded phrases a line of this family may start with: every verb of the tables, the longest first."""
    out = set()
    for table in _tables_with_mail(tables):
        for key, _op in VERB_OPS:
            out |= {" ".join(p) for p in _data(table)["mail"][key]}
    return sorted(out, key=lambda p: (-len(p), p))


# --- tokens ------------------------------------------------------------------------------------------------------------------------------


def tokenize(line: str):
    """The tokens of `line`, or None when it holds an `@` that is not a plain address (a mention is never read as part of a write). An address keeps its case in `value` and is in its
    normal form; every other token is folded. Offsets are in the original line."""
    folded, origin = _fold_with_origin(line)
    out = []

    def at(a, b):
        return origin[a], origin[b - 1] + 1

    for chunk in re.finditer(r"\S+", folded):
        a, b = chunk.start(), chunk.end()
        while a < b and folded[a] in LEAD:
            a += 1
        tail = []
        while b > a and folded[b - 1] in DROP_TAIL + PUNCT_TAIL:
            if folded[b - 1] in PUNCT_TAIL:
                tail.append(b - 1)
            b -= 1
        for piece in re.finditer(r"[^,;]+|[,;]", folded[a:b]):
            p0, p1 = a + piece.start(), a + piece.end()
            text = piece.group()
            s, e = at(p0, p1)
            if text in (",", ";"):
                out.append(Tok(",", "punct", s, e))
            elif "@" in text:
                try:
                    address = mail_address.normalize_address(line[s:e])
                except mail_address.AddressError:
                    return None
                out.append(Tok(address.lower(), "addr", s, e, address))
            elif ITEM_REF.fullmatch(text):
                out.append(Tok(text, "ref", s, e, text))
            else:
                subs = list(re.finditer(r"[^\W_]+|-", text))
                for n, sub in enumerate(subs):
                    word = sub.group()
                    if word == "-":      # a hyphen is a range only between two numbers ("1-3"); between letters it joins words ("e-mail"), and means nothing else
                        if not (0 < n < len(subs) - 1 and subs[n - 1].group().isdigit() and subs[n + 1].group().isdigit()):
                            continue
                    s2, e2 = at(p0 + sub.start(), p0 + sub.end())
                    out.append(Tok(word, "range" if word == "-" else "num" if word.isdigit() else "word", s2, e2))
        for position in reversed(tail):
            s, e = at(position, position + 1)
            out.append(Tok(":" if folded[position] == ":" else ",", "punct", s, e))
    return out


def _fold_with_origin(line: str) -> tuple:
    """(folded, origin): the line in lower case with no accent and no format character, and for each folded character the index in the line it came from. Unlike the time
    parser's `normalise`, a hyphen between two letters stays: an address may hold one."""
    out, origin = [], []
    for i, ch in enumerate(line):
        for c in unicodedata.normalize("NFKD", ch):
            if not unicodedata.combining(c) and unicodedata.category(c) != "Cf":
                out.append(c.lower())
                origin.append(i)
    return "".join(out), origin


def _at(toks, i, phrases) -> int:
    """The length of the longest phrase of `phrases` that the tokens start with at i (0 when none); word and number tokens only."""
    for phrase in phrases:
        k = len(phrase)
        if i + k <= len(toks) and all(toks[i + j].kind in ("word", "num") and toks[i + j].norm == phrase[j] for j in range(k)):
            return k
    return 0


def _skip(toks, i, phrases) -> int:
    while True:
        k = _at(toks, i, phrases)
        if not k:
            return i
        i += k


def _is_comma(tok) -> bool:
    return tok.kind == "punct" and tok.norm == ","


def _is_joiner(tok, d) -> bool:
    return _is_comma(tok) or (tok.kind == "word" and tok.norm in d["joiners"])


def _unquote(text: str) -> str:
    text = text.strip()
    for left, right in QUOTES:
        if len(text) >= 2 and text[0] == left and text[-1] == right and left not in text[1:-1] and right not in text[1:-1]:
            return text[1:-1].strip()
    return text


def _text_slot(line: str, start: int, end: int, cap: int, one_line: bool, to_end: bool):
    """(text, (start, end)) of the text slot that lies in line[start:end], cut at its edges (blanks, and a comma, colon or semicolon before the next marker unless the slot runs to the
    end of the line, where the punctuation the person wrote stays), without a pair of quotes around the whole; ("", None) when there is none; None when it is too long or, for
    a one-line slot, holds a line end."""
    raw = line[start:end].strip()
    if not to_end:
        raw = raw.rstrip(" \t,;:")
    raw = raw.lstrip(" \t:") if raw.startswith(":") else raw
    text = _unquote(raw)
    if not text:
        return "", None
    if len(text) > cap or (one_line and ("\n" in text or "\r" in text)):
        return None
    inner = line.find(text, start, end)
    return text, ((inner, inner + len(text)) if inner >= 0 else (start, end))


# --- the services, the references --------------------------------------------------------------------------------------------------------


def _service_of(words, d, introduced: bool = False):
    """The account that a run of words names as a whole: a phrase of the shared `services`. A phrase of two words or more names it alone (`google calendar`); one word needs a
    word that introduces it (`service_in`: `pelo gmail`, `via outlook`) or `introduced` (the caller consumed one: `do gmail` after a number). Else None."""
    flat = tuple(t.norm for t in words)
    if not flat or any(t.kind not in ("word", "num") for t in words):
        return None
    leads = [()] + [p for p in d["shared"]["service_in"] if flat[:len(p)] == p and len(flat) > len(p)]
    for lead in leads:
        rest = flat[len(lead):]
        for account, phrases in d["services"].items():
            if rest in phrases and (len(rest) >= 2 or lead or introduced):
                return account
    return None


def _service_suffix(words, d):
    """(account, words before it) when a run of words ENDS with an introduced service (`... pelo gmail`) or a service phrase of two words or more; a single word at the end may be a
    word of the sender."""
    flat = tuple(t.norm for t in words)
    for account, phrases in d["services"].items():
        for phrase in phrases:
            for lead in ([()] if len(phrase) >= 2 else []) + list(d["shared"]["service_in"]):
                whole = lead + phrase
                if len(flat) > len(whole) and flat[-len(whole):] == whole:
                    return account, words[:-len(whole)]
    return None


def _number(tok: Tok):
    return int(tok.norm) if tok.kind == "num" and len(tok.norm) <= NUMBER_DIGITS_MAX else None


def _parse_numbers(reg, d):
    """(numbers, refs, over, rest) for a region that starts with digits or `<source>#<n>` references, joined by the joiners (a range is `1 a 3` or `1-3`); `over` is true when a
    list or a range is longer than one card takes; `rest` is the tokens after them. None when the region does not start with one."""
    numbers, refs, over, i = [], [], False, 0
    while i < len(reg):
        t = reg[i]
        if t.kind == "ref":
            if t.value not in refs:
                refs.append(t.value)
            i += 1
        elif _number(t) is not None:
            n = _number(t)
            mid = reg[i + 1] if i + 1 < len(reg) else None
            far = reg[i + 2] if i + 2 < len(reg) else None
            if mid is not None and (mid.kind == "range" or (mid.kind == "word" and mid.norm in d["range"])) and far is not None and _number(far) is not None:
                m = _number(far)
                if m < n:
                    return None
                if m - n + 1 > MESSAGES_MAX:
                    over = True
                else:
                    numbers += [x for x in range(n, m + 1) if x not in numbers]
                i += 3
            else:
                if n not in numbers:
                    numbers.append(n)
                i += 1
        else:
            break
        if len(numbers) + len(refs) > MESSAGES_MAX:
            over = True
        after = reg[i + 1] if i + 1 < len(reg) else None
        if i < len(reg) and _is_joiner(reg[i], d) and after is not None and (after.kind == "ref" or _number(after) is not None):
            i += 1
            continue
        break
    if not numbers and not refs and not over:
        return None
    return numbers, refs, over, reg[i:]


def _parse_reference(reg, d, plural: bool, newest: bool):
    """The messages a region names, or None when it names none: {"numbers", "refs", "over", "words" (the content words), "newest", "plural", "service"}."""
    ref = {"numbers": [], "refs": [], "over": False, "words": [], "newest": newest, "plural": plural, "service": None}
    k = _at(reg, 0, d["mail"]["newest"])
    if k:
        newest, ref["newest"] = True, True
        reg = reg[k:]
    found = _parse_numbers(reg, d)
    if found is not None:
        ref["numbers"], ref["refs"], ref["over"], rest = found
        if newest:
            return None
        if rest:
            skipped = _at(rest, 0, d["mail"]["of"])
            service = _service_of(rest[skipped:], d, introduced=bool(skipped)) or _service_of(rest, d)
            if service is None:
                return None
            ref["service"] = service
        return ref
    k = _at(reg, 0, d["mail"]["of"])
    if k:
        words = reg[k:]
        if not words or any(t.kind not in ("word", "num") for t in words):
            return None
        service = _service_of(words, d, introduced=True)
        if service is not None:
            if not newest:
                return None      # "the e-mails from gmail" names an account, not messages
            ref["service"] = service
            return ref
        suffix = _service_suffix(words, d)
        if suffix is not None:
            ref["service"], words = suffix
        content = [t.norm for t in words if t.norm not in d["stop"]]
        if not content or len(content) > WORDS_CAP or any(_gerund(w) or w in d["work"] for w in content):
            return None      # a long tail, a verb or a gerund is a sentence ("o e-mail do cliente explicando o atraso"), not the name of a sender or a subject
        ref["words"] = content
        if any(w in d["dates"] for w in content):
            ref["by_date"] = True      # "os e-mails de ontem": a message is not found by its date here, and the resolution says so
        return ref
    if newest:
        service = _service_of(reg, d) if reg else None
        if not reg or service is not None:
            ref["service"] = service
            return ref
    return None


def _gerund(word: str) -> bool:
    """Whether a word looks like a gerund ("explicando", "saying"): the verb that begins a clause after the name of a message."""
    return len(word) >= 6 and (word.endswith("ndo") or word.endswith("ing"))


def _slots_of_reference(ref: dict) -> dict:
    slots = {"numbers": ref["numbers"], "refs": ref["refs"], "plural": ref["plural"], "newest": ref["newest"]}
    if ref["over"]:
        slots["over"] = True
    if ref.get("by_date"):
        slots["by_date"] = True
    if ref["words"]:
        slots["words"] = ref["words"]
    if ref["service"]:
        slots["service"] = ref["service"]
    return slots


# --- the read ----------------------------------------------------------------------------------------------------------------------------


def _head(toks, d):
    """{"op", "i" (after the noun), "plural", "newest", "reply_draft"} of `[polite] VERB [article] [newest] NOUN`, or None."""
    i = 0
    while i < len(toks) and (_is_comma(toks[i]) or _at(toks, i, d["shared"]["polite"])):
        i += 1 if _is_comma(toks[i]) else _at(toks, i, d["shared"]["polite"])
    best = None
    for key, op in VERB_OPS:
        k = _at(toks, i, d["mail"][key])
        if k and (best is None or k > best[0]):
            best = (k, op)
    if best is None:
        return None
    i += best[0]
    op, reply_draft = best[1], False
    if op == "mail-draft":
        j = _skip(toks, i, d["shared"]["articles"])
        k = _at(toks, j, d["mail"]["reply_verbs"])
        if k:
            i, reply_draft = j + k, True
    j = _skip(toks, i, d["shared"]["articles"])
    newest = False
    k = _at(toks, j, d["mail"]["newest"])
    if k:
        newest, j = True, _skip(toks, j + k, d["shared"]["articles"])
    k = _at(toks, j, d["mail"]["nouns"])
    if not k:
        return None
    plural = tuple(t.norm for t in toks[j:j + k]) in d["plural"]
    if op in ("mail-send",) or (op == "mail-draft" and not reply_draft):
        if newest:
            return None
    return {"op": op, "i": j + k, "plural": plural, "newest": newest, "reply_draft": reply_draft}


def is_head(text, tables) -> bool:
    """Whether a line starts with a CLOSED head of this family: a verb, the articles, the object ("manda um e-mail", "arquiva os e-mails", "o ultimo e-mail"). The foundation asks
    it of a line offered as a title or a subject; a bare verb ("Passa no banco", "Send flowers", "Reply to Ana") is a title."""
    toks = tokenize(text) if isinstance(text, str) else None
    return bool(toks) and any(_head(toks, d) is not None for d in (_data(t) for t in _tables_with_mail(tables)))


def _recipients(seg, d):
    """The recipients a run of tokens names: {"to": [address tokens], "names": [name tokens]}, or None when the run is neither addresses (joined) nor a short name."""
    addresses = [t for t in seg if t.kind == "addr"]
    others = [t for t in seg if t.kind != "addr" and not _is_joiner(t, d)]
    if addresses:
        return {"to": addresses, "names": []} if not others else None
    words, i = [], 0
    while i < len(others):
        k = _at(others, i, d["shared"]["articles"]) if not words else 0
        if k:
            i += k
            continue
        words.append(others[i])
        i += 1
    if not words or len(words) > NAME_WORDS_MAX or any(t.kind != "word" for t in words):
        return None
    return {"to": [], "names": words}


def _time_outside(line: str, spans, tables) -> bool:
    """Whether the words of the line outside its text slots hold a clock or a relative time ("... amanha as 9"): a scheduled send is not offered, so such a line is not taken."""
    pieces, pos = [], 0
    for s, e in sorted(x for x in spans if x):
        pieces.append(line[pos:s])
        pos = e
    pieces.append(line[pos:])
    try:
        hits = nt.find(" ".join(pieces), tables)["hits"]
    except Exception:      # an engine that cannot read the text is no evidence of a time
        return False
    return any(h.get("kind") in ("clock", "relative") for h in hits)


def _compose(line: str, toks, head, d, tables):
    """A new e-mail or a new draft: `[service] to ADDRESSES [subject TEXT] [body TEXT]`, from the tokens after the noun."""
    n = len(toks)
    gap, to_seg, subject_seg = [], [], []
    current, seen_to, seen_subject = gap, False, False
    subject_from = body_from = body_marker_at = None
    j = head["i"]
    while j < n:
        t = toks[j]
        k = _at(toks, j, d["mail"]["body"])
        if k:
            body_from, body_marker_at = toks[j + k - 1].end, t.start
            break
        if t.kind == "punct" and t.norm == ":" and (current is not subject_seg or (t.start > 0 and line[t.start - 1] in CLOSING_QUOTES)):      # a colon after a quoted subject ends it
            body_from, body_marker_at = t.end, t.start
            break
        k = _at(toks, j, d["mail"]["subject"])
        if k and not seen_subject and current is not subject_seg:
            seen_subject, current = True, subject_seg
            subject_from, j = toks[j + k - 1].end, j + k
            if j < n and toks[j].kind == "punct" and toks[j].norm == ":":
                subject_from, j = toks[j].end, j + 1
            continue
        k = _at(toks, j, d["mail"]["to"])
        if k and current is to_seg:
            j += k      # "para a e para b": the second marker joins
            continue
        if k and not seen_to and current is gap:
            seen_to, current, j = True, to_seg, j + k
            continue
        current.append(t)
        j += 1
    if not seen_to:
        return None
    service = None
    if gap:
        service = _service_of(gap, d)
        if service is None:
            return None
    recipients = _recipients(to_seg, d)
    if recipients is None:
        return None
    slots, spans = {"plural": head["plural"]}, {}
    if recipients["to"]:
        addresses = []
        for t in recipients["to"]:
            if t.value.lower() not in [a.lower() for a in addresses]:
                addresses.append(t.value)
        if len(addresses) > ADDRESSES_MAX:
            return None
        slots["to"] = addresses
    else:
        if body_from is None:
            return None      # a name and no body marker: a request for work, not a write form
        slots["to_names"] = [line[recipients["names"][0].start:recipients["names"][-1].end]]
    end = len(line.rstrip())
    subject = _text_slot(line, subject_from, body_marker_at if body_marker_at is not None else end, SUBJECT_MAX, True, to_end=body_marker_at is None) if subject_from is not None else ("", None)
    text = _text_slot(line, body_from, end, BODY_MAX, False, to_end=True) if body_from is not None else ("", None)
    if subject is None or text is None:
        return None
    for name, got in (("subject", subject), ("body", text)):
        if got[0]:
            slots[name], spans[name] = got
    if service:
        slots["service"] = service
    if _time_outside(line, list(spans.values()), tables):
        return None
    return {"op": head["op"], "slots": slots, "at": spans, "need": [x for x in ("to", "subject", "body") if x not in slots]}


def _folder_tokens_ok(tail, d) -> bool:
    """Whether the words after a folder marker can be a folder name: not a number alone (`move emails 1 to 3`), none a service word (`to 3 via gmail`)."""
    if any(t.kind not in ("word", "num") for t in tail) or all(t.kind == "num" for t in tail):
        return False
    return not any(t.norm in d["service_words"] for t in tail)


def _last_phrase(toks, i, phrases):
    """(index, length) of the LAST place at or after i where one of `phrases` starts, or None."""
    found = None
    for j in range(i, len(toks)):
        k = _at(toks, j, phrases)
        if k:
            found = (j, k)
    return found


def _reference_op(line: str, toks, head, d, tables):
    """The operations that name messages: a reply (or a reply draft), archive, trash, move and mark."""
    op, i, n = head["op"], head["i"], len(toks)
    reply_like = op == "mail-reply" or head["reply_draft"]
    end, body_from, state, folder, bare = n, None, None, None, False
    if reply_like:
        j = i
        while j < n and not _at(toks, j, d["mail"]["body"]) and not (toks[j].kind == "punct" and toks[j].norm == ":"):
            j += 1
        end = j
        if j < n:
            k = _at(toks, j, d["mail"]["body"])
            body_from = toks[j + k - 1].end if k else toks[j].end
    elif op == "mail-mark":
        for key in ("unread", "read"):      # the state words end the line; "como nao lido" is not "como lido" (the longer phrase is tried first and the phrases do not overlap)
            got = _last_phrase(toks, i, d["mail"][key])
            if got is not None and got[0] + got[1] == n:
                end, state = got[0], key
                break
        else:
            if any(_last_phrase(toks, i, d["mail"][key]) for key in ("unread", "read")):
                return None      # a state word that does not end the line is not a closed form
    elif op == "mail-move":
        for j in range(n - 1, i - 1, -1):      # the last marker whose tail can be a folder: `1 to 3 via gmail` is a range and a service, not a folder `3 via gmail`
            k = _at(toks, j, d["mail"]["folder"])
            if k and j + k < n and _folder_tokens_ok(toks[j + k:], d):
                end, folder, bare = j, toks[j + k:], k == 1
                break
        else:
            return None
    region = toks[i:end]
    while region and _is_comma(region[-1]):
        region = region[:-1]
    ref = _parse_reference(region, d, head["plural"], head["newest"])
    if ref is None:
        return None
    if reply_like and (len(ref["numbers"]) + len(ref["refs"]) > 1 or ref["over"] or (ref["words"] and ref["plural"])):
        return None      # a reply answers one message
    slots, spans = _slots_of_reference(ref), {}
    text = _text_slot(line, body_from, len(line.rstrip()), BODY_MAX, False, to_end=True) if reply_like and body_from is not None else ("", None)
    if text is None:
        return None
    if text[0]:
        slots["body"], spans["body"] = text
    if op == "mail-mark" and state:
        slots["state"] = state
    if op == "mail-move":
        name = line[folder[0].start:folder[-1].end].strip()
        if not name or len(name) > FOLDER_MAX or any(t.kind not in ("word", "num") for t in folder):
            return None
        slots["folder_name"] = name
        if bare:
            slots["folder_bare"] = True      # `para o joao`: a person after a bare "to" is not a folder unless the project lists one by that name
    need = (["body"] if reply_like and "body" not in slots else []) + (["state"] if op == "mail-mark" and not state else [])
    if _time_outside(line, list(spans.values()), tables):
        return None
    return {"op": "mail-draft" if head["reply_draft"] else op, "slots": slots, "at": spans, "need": need}


def _read_with(line: str, toks, d, tables):
    head = _head(toks, d)
    if head is None:
        return None
    if head["op"] == "mail-send" or (head["op"] == "mail-draft" and not head["reply_draft"]):
        return _compose(line, toks, head, d, tables)
    return _reference_op(line, toks, head, d, tables)


def read(line, tables, now=None, op=None):
    """The mail write a line asks for (see the module's text), or None when the line is not a closed form of this family. `now` is not used: no slot of this family is a time.
    With `op`, the operation a router named: the line is read again by this parse and is taken only if it is that operation (the router's choice is a hint, never trusted alone)."""
    if not isinstance(line, str) or not line.strip() or line.lstrip().startswith("/") or len(line) > LINE_MAX or len(line.split()) > WORDS_MAX:
        return None
    toks = tokenize(line)
    if not toks:
        return None
    while toks and toks[-1].kind == "punct":
        toks = toks[:-1]
    for table in _tables_with_mail(tables):
        found = _read_with(line, toks, _data(table), tables)
        if found is not None and (op is None or found["op"] == op):
            return _shaped(line, found)
    return None


def _shaped(line: str, found: dict) -> dict:
    """The reading in the shape the family interface gives it (runtime/natural_writes.py): `spans` {slot: the person's own words}, `ranges` {slot: (start, end)} of those words in
    the folded line (`natural_time.normalise`, the coordinates the reminder-trigger test reads), `engine` None and `doubt` False (no slot of this family is a time)."""
    at = found.pop("at")
    origin = nt.normalise(line)[1]
    found["spans"] = {name: line[s:e] for name, (s, e) in at.items()}
    found["ranges"] = {name: (bisect.bisect_left(origin, s), bisect.bisect_left(origin, e)) for name, (s, e) in at.items()}
    found["engine"], found["doubt"] = None, False
    return found


# --- the answers to a question -----------------------------------------------------------------------------------------------------------


def fold(text: str) -> str:
    """The words of a text folded and joined by one space (a hyphen between letters is a space): the form two names are compared by."""
    return " ".join(t.norm for t in (tokenize(text) or []) if t.kind in ("word", "num"))


def folder_key(text: str) -> str:
    """A folder name as the person wrote it, to be compared with a configured name: folded, without the articles that stand first ("para o contas")."""
    words = fold(text).split()
    articles = {p[0] for table in nt.languages() if _data(table) for p in _data(table)["shared"]["articles"] if len(p) == 1}
    while words and words[0] in articles:
        words = words[1:]
    return " ".join(words)


def clean_shown(text: str, width: int = 40) -> str:
    """A name the person wrote, as a sentence may echo it: one line, cut."""
    return " ".join(str(text).split())[:width]


def _not_an_answer(need: str, text: str, tables) -> bool:
    """Whether a line offered as a subject or a body is rather a yes or a no, a question or a request (it is then a new line or is asked again, never the text).
    A yes or a no is never a subject or a body ("sim", "ok", "yes"). A SUBJECT follows the rules of the foundation's text answers (runtime/ops_natural_writes.py
    `_another_request`): a question mark, more than TEXT_WORDS_MAX words, and, at three words or more, a work verb anywhere or a question or request word first. A BODY is the
    person's sentence to somebody else and may ask, want or need ("voce pode vir?"): it is refused only when it starts with a closed head of this family or with a mail verb
    ("escreve uma resposta educada dizendo..."), which is the person talking to the platform. (A line that starts a write of another family or any other request was refused before the family is asked.)"""
    if natural.confirm_kind(text, tables) in ("yes", "no"):
        return True
    tokens = re.findall(r"[^\W_]+", nt.normalise(text)[0])
    verbs = {w for table in tables for w in table.get("work_verbs", [])}
    starters = {w for table in tables for w in table.get("work_starters", [])}
    if need == "body":
        first = {p[0] for table in _tables_with_mail(tables) for key, _op in VERB_OPS for p in _data(table)["mail"][key]}
        return bool(is_head(text, tables) or (tokens and tokens[0] in first))
    if text.endswith("?") or len(text.split()) > TEXT_WORDS_MAX:
        return True
    return len(text.split()) >= 3 and bool(verbs & set(tokens) or (tokens and tokens[0] in starters))


def answer(need, line, slots, tables, now=None, options=None):
    """{"slots": the update} that `line` makes when it answers the question `need` of this family (the interface's optional `answer`: the needs in NEEDS), or None when the line is
    not an answer. `options` are the options the question stored ([{"value", "label"}]). The account, the mailbox, the message and the folder are options and are answered by the
    foundation's generic answer (the number shown or the word); this answers what is not an option: an address (only addresses and what joins them), a subject and a body (the
    line itself, verbatim, unless it is a question or a request), and the state (its closed words, or the number of its option). Nothing is guessed."""
    update = _answer(need, line, options or [], tables)
    return {"slots": update} if update is not None else None


def _answer(need, line, options, tables):
    if not isinstance(line, str) or not line.strip() or need not in NEEDS:
        return None
    text = line.strip()
    live = _tables_with_mail(tables)
    joiners = set().union(*[_data(t)["joiners"] for t in live]) if live else set()
    if need in ("to", "subject", "body") and natural.confirm_kind(text, tables) in ("yes", "no"):
        return None      # "sim", "ok", "yes" answer a question of yes or no; they are never an address, a subject or a body
    if need == "to":
        toks = tokenize(text)
        if not toks or any(t.kind != "addr" and not (_is_comma(t) or (t.kind == "word" and t.norm in joiners)) for t in toks):
            return None
        out = []
        for t in toks:
            if t.kind == "addr" and t.value.lower() not in [a.lower() for a in out]:
                out.append(t.value)
        return {"to": out, "to_names": None} if 0 < len(out) <= ADDRESSES_MAX else None
    if need in ("subject", "body"):
        if _not_an_answer(need, text, tables):
            return None
        got = _text_slot(text, 0, len(text), SUBJECT_MAX if need == "subject" else BODY_MAX, need == "subject", to_end=True)
        return {need: got[0]} if got and got[0] else None
    if need == "state":
        digits = unicodedata.normalize("NFKC", text)
        if digits.isdigit() and 1 <= int(digits) <= len(options):
            return {"state": options[int(digits) - 1]["value"]}
        word = fold(text)
        for table in live:
            for key in ("unread", "read"):
                for phrase in _data(table)["mail"][key]:
                    if word in (" ".join(phrase), " ".join(phrase[1:])):
                        return {"state": key}
        return None
    return None


# --- a message by words ------------------------------------------------------------------------------------------------------------------


def _words_of(text) -> list:
    return re.findall(r"[^\W_]+", nt.normalise(str(text or ""))[0])


def from_words(entry: dict) -> set:
    """The whole words of the sender half of one message of an index: the words of the local part of its from-address (split on . _ - +) and the labels of its domain except the last,
    folded. The index holds no display name, only the address (`runtime/item_refs.py` `INDEX_KEYS`)."""
    local, _sign, domain = str(entry.get("from_address") or "").partition("@")
    labels = domain.lower().split(".")
    words = set(_words_of(local))
    for label in labels[:-1] if len(labels) > 1 else labels:
        words |= set(_words_of(label))
    return words


def entry_words(entry: dict) -> set:
    """The whole words of one message of an index: `from_words` (the local part of its from-address and the labels of its domain except the last) and the words of its subject,
    folded, in one set."""
    return from_words(entry) | set(_words_of(entry.get("subject")))


def target_words(span, tables, *, cap: int = TARGET_WORDS_MAX) -> list:
    """The words that name a message in a `target` span (B''-lite): the span's words folded as `_words_of` folds them, without the words of the tables' `articles`, `polite` and
    `joiners`, and of the mail `nouns`, `plural`, `of` and `newest` lists, in order, none twice; [] when more than `cap` are left (TARGET_WORDS_MAX unless a caller passes another cap: a
    sentence, not a name). Pure: they only choose a message among the index's own (`match_words`); nothing here reads a message or returns an address."""
    drop = set()
    for table in _tables_with_mail(tables):
        d = _data(table)
        for lists in (d["shared"]["articles"], d["shared"]["polite"], d["shared"]["joiners"], d["mail"]["nouns"], d["mail"]["of"], d["mail"]["newest"], d["plural"]):
            for phrase in lists:
                drop.update(w for part in phrase for w in _words_of(part))
    found = [w for w in dict.fromkeys(_words_of(span)) if w not in drop]
    return found if len(found) <= cap else []


def ground_words(span, tables) -> list:
    """BL7-5. `target_words` of a sender and a subject the interpreter grounded, with the cap GROUND_WORDS_MAX instead of TARGET_WORDS_MAX. `match_words` still needs EVERY word, so a
    longer set can only reach a subset of what a shorter set of the same words reaches: the cap decides between a search and a refusal, never how wide the search is."""
    return target_words(span, tables, cap=GROUND_WORDS_MAX)


_NUMBER_WORD = re.compile(r"#?[0-9]{1,9}")
_NUMBER_RANGE = re.compile(r"#?[0-9]+\s*[-\u2010-\u2015]\s*#?[0-9]+")
_RANGE_MARKS = frozenset(("-", "\u2010", "\u2011", "\u2012", "\u2013", "\u2014", "\u2015"))
_RANGE_MID_EXTRA = frozenset(("ao", "aos"))          # BL7-5: "do 1 ao 3" (the tables' `range` list holds `a` and `ate`): the person meant 1, 2 and 3
_RANGE_LEAD = frozenset(("between", "entre"))          # BL7-5: "between 1 and 3"
_JOINERS_EXTRA = frozenset(("or", "ou"))          # BL7-5: a number chained to another by "or" counts as the same list
_CLOCK_AFTER = ("o clock", "oclock")          # "the 2 o'clock meeting": a time, never a message number
_WORD_EDGE = ".,;:!?()[]\"'"


def free_numbers(line, spans=(), tables=None) -> list:
    """BL7-5. The whole numbers `line` writes as message numbers, in order, none twice. A word of digits (`#7`, `4,`), as `natural.decision_numbers` reads a number per word, counts only
    when ALL hold: it is written `#n`, or the word before it is a mail noun of the tables (`email 4`, `e-mails 2`, `mensagem 3`), or it is chained to such a number: written right after it (`emails 2 4 e 7`), or after a joiner
    (`and`, `e`, `or`, `ou`, a comma) with an optional article between (`emails 2, 4 e o 7`); it does not overlap an occurrence in the line of one of the texts of `spans` (a body, a
    folder, a state) nor a time phrase of `natural_time.find` (a clock, a date, a relative time); it is not followed by a unit (`natural.MEASURES`), by `o'clock` or by a currency mark and
    not preceded by a currency. So a count noun ("the 2 budgets"), a year, a room ("room 4", "sala 4") and a phone number are no message number, by construction (principle 13: the stricter
    rule stays). A line with a range between numbers (`1-3`, `1 a 3`, `1 to 3`, `do 1 ao 3`, `between 1 and 3`) gives [], and so does a time phrase that cannot be mapped to the line: it
    fails closed. Pure."""
    if not isinstance(line, str) or not line:
        return []
    found = nt.find(line)
    norm, origin = found["norm"], found["origin"]
    if len(norm) != len(origin):
        return []
    blocked = []
    for hit in found["hits"]:
        start, end = hit["s"], hit["e"]
        if not 0 <= start < end <= len(origin):
            return []
        blocked.append((origin[start], origin[end - 1] + 1))
    for text in spans or ():
        at = line.find(text) if isinstance(text, str) and text else -1
        while at >= 0:
            blocked.append((at, at + len(text)))
            at = line.find(text, at + 1)
    range_words, nouns, articles, joiners = set(_RANGE_MID_EXTRA), set(), set(), set(_JOINERS_EXTRA)
    for table in _tables_with_mail(natural._tables(tables)):
        d = _data(table)
        range_words |= {p[0] for p in d["shared"]["range"] if len(p) == 1}
        nouns |= set(d["mail"]["nouns"]) | set(d["plural"])
        articles |= {p[0] for p in d["shared"]["articles"] if len(p) == 1}
        joiners |= {p[0] for p in d["shared"]["joiners"] if len(p) == 1}
    toks = [(m.start(), m.end(), unicodedata.normalize("NFKC", m.group()).strip(_WORD_EDGE), unicodedata.normalize("NFKC", m.group())) for m in re.finditer(r"\S+", line)]
    folded = [_words_of(tok[2]) for tok in toks]
    free = lambda tok: not any(tok[0] < e and s < tok[1] for s, e in blocked)      # noqa: E731  (the word touches no span and no time phrase)
    shape = [bool(_NUMBER_WORD.fullmatch(tok[2])) for tok in toks]
    for at, tok in enumerate(toks):
        if free(tok) and _NUMBER_RANGE.fullmatch(tok[2]):
            return []
        if shape[at] and free(tok):
            if at + 2 < len(toks) and shape[at + 2] and (toks[at + 1][2] in _RANGE_MARKS or natural.ascii_normal(toks[at + 1][2]) in range_words):
                return []
            if at and natural.ascii_normal(toks[at - 1][2]) in _RANGE_LEAD:
                return []
    found_numbers, counted = [], set()
    for at, tok in enumerate(toks):
        if not shape[at] or not free(tok):
            continue
        after = natural.ascii_normal(toks[at + 1][2]) if at + 1 < len(toks) else ""
        before = toks[at - 1][2].lower() if at else ""
        if after.split(" ")[0] in natural.MEASURES or after in _CLOCK_AFTER or (at + 1 < len(toks) and toks[at + 1][2].lstrip().startswith(natural.CURRENCY_OR_MARK_AFTER)) or before.endswith(natural.CURRENCY_BEFORE):
            continue
        preceding = [w for k in range(max(0, at - 3), at) for w in folded[k]]
        if not (tok[2].startswith("#") or any(len(n) <= len(preceding) and tuple(preceding[len(preceding) - len(n):]) == n for n in nouns) or _chained(toks, folded, at, counted, articles, joiners)):
            continue
        counted.add(at)
        found_numbers.append(int(tok[2].lstrip("#")))
    return list(dict.fromkeys(found_numbers))


def _chained(toks, folded, at, counted, articles, joiners) -> bool:
    """Whether the number word at `at` is chained to a number already counted: written right after it ("emails 2 4 e 7": still anchored to the mail noun), or after an optional article, then
    a joiner word (or a comma stuck to the earlier number, or a comma word), then that number."""
    j = at - 1
    if j in counted:
        return True
    if j >= 0 and len(folded[j]) == 1 and folded[j][0] in articles:
        j -= 1
    if j < 0:
        return False
    if j in counted:
        return toks[j][3].rstrip(")]\"'").endswith((",", ";"))          # "2, 4": the comma is stuck to the number before
    word = folded[j]
    if (len(word) == 1 and word[0] in joiners) or toks[j][3] in (",", ";"):
        return j - 1 in counted
    return False


def plural_mentioned(text, tables) -> bool:
    """Whether `text` (a `target` span, or the line) holds a noun of the tables' `plural` list, as whole words in a row: the same words the closed form reads as several messages
    ("apague os e-mails do banco"). A line that names the message in the singular ("apague o e-mail do banco") holds none."""
    words = _words_of(text)
    for table in _tables_with_mail(tables):
        for phrase in _data(table)["plural"]:
            n = len(phrase)
            if any(tuple(words[i:i + n]) == tuple(phrase) for i in range(len(words) - n + 1)):
                return True
    return False


def match_words(entries, words, newest: bool = False, sender=()) -> list:
    """The entries of a snapshot's index (clean entries, `n` from 1, newest first) that hold EVERY one of `words` as a whole word, in the order of their numbers; with `newest`
    only the one with the lowest number. An empty `words` matches nothing. With `sender` (the words of the person's name), an entry must also hold every one of them in `from_words`
    (the address half), so a word only the subject carries is not the sender; `sender=()` is the rule without it."""
    wanted = [w for w in words if w]
    if not wanted:
        return []
    from_only = [w for w in sender if w]
    strong = sorted((e for e in entries if set(wanted) <= entry_words(e) and set(from_only) <= from_words(e)), key=lambda e: e["n"])
    return strong[:1] if newest else strong


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
