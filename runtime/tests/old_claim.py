"""The old reading of the reminder engine, FROZEN as a test stand-in (S41-11 PR 2b, CANDIDATE-OUT 2). Not a test file.

Until S41-11 `natural.understand(line, now, "trigger")` cut the trigger words out of the reminder's text (`_trigger_span`: the head of `triggers.remind`, a scheduling verb and a reminder noun, or a
"remind me" anywhere in the line, and for the ways `bare` and `note` the head of `triggers.note`), and `natural.claim(line)` was `natural.candidate` for a site that CLAIMS the line for a closed form.
The product keeps neither: the interpreter names the operation (L63), and the reminder question engine is carried out with `how="command"`. Since CANDIDATE-OUT 2 the product keeps `candidate`
no more either (the question engine tells a new request from an answer with the code guard `turn_gate.new_request`), nor the three helpers it alone read, nor the repeat scope of CB-9 (nothing
read it), nor the ten table keys those helpers read. The tests of the bridge and of the operations that enter through a plain line, and the pre-states of the entry replay that put a question in the
world by saying a line, need the old reading; `closed_heads.py` puts it back for them alone, for the length of a test (a draft made under it has the way `trigger`). The functions are the old ones,
copied byte for byte except for the names of the helpers that stayed in `natural.py`, and the ten keys are literals per language below (`FROZEN_WORDS`).

Every word and every name here is the test tree's own and invented.
"""
from __future__ import annotations

import datetime
import re

import standin_tree as st

natural = st.load("natural")
nt = st.load("natural_time")


# --- the frozen reading of the reminder question engine (CANDIDATE-OUT 2) -------------------------------------------------------------------------------------------------------------------
# `natural.candidate` and the three helpers only it read (`_forget`, `_undo`, `_verb_noun`) are copied here, byte for byte but for the names of the helpers that stayed in `natural.py`, with the ten
# table keys they read as literals per language (the tables no longer hold them). The copy is the test tree's own: nothing in the product reads it, and `closed_heads.py` and the pre-states of the
# entry replay read it. PR 2 showed on its head that it equals the product function it was copied from, on the 1,848 lines of the interpreter's sets and the entry corpus.

LIST_WORDS_MAX = 5          # "what reminders do I have": a list request is short
FORGET_WORDS_MAX = 5        # "cancel the reminder about the florist": what the person says of the reminder is short
MANY_IDS_MAX = 5            # "cancel reminders 1 and 2": a few numbers are shown and confirmed; more are asked

FROZEN_WORDS = {
    "en": {
        "problem_words": ["not", "never", "broken", "bug", "bugs", "fail", "fails", "failed", "failing", "error", "errors", "doesnt", "dont", "wont", "isnt", "arent",
                          "late", "why", "stuck", "wrong", "missing", "work", "works", "working"],
        "calendar_noun_reads": ["of", "for", "on", "today", "tomorrow", "this", "next", "view", "full"],
        "remind_nouns": ["reminder", "reminders"],
        "triggers": {"reminders": ["my reminders", "list my reminders", "list reminders", "show my reminders", "show reminders", "what reminders", "which reminders"],
                     "reminders_bare": ["reminders"],
                     "undo": ["undo", "undo that", "undo it", "bring it back", "bring that back", "restore it"],
                     "note": ["note"]},
        "forget": {"verbs": ["forget", "cancel", "delete", "remove", "drop"], "id_words": ["number", "n", "num", "nr"], "id_marked": ["no"]},
    },
    "pt-BR": {      # validate: allow english-only -- the Portuguese words of the frozen copy of the old reading (folded, no accent), invented for the test tree
        "problem_words": ["nao", "nunca", "chegou", "chegaram", "funciona", "funcionam", "quebrado", "quebrados", "bug", "erro", "erros", "falha", "falhou", "falhando", "atrasado", "atrasados", "porque", "pq", "errado", "errados", "travou"],      # validate: allow english-only -- Portuguese words of the frozen copy
        "calendar_noun_reads": ["de", "da", "do", "dos", "das", "para", "hoje", "amanha", "semana", "mes", "completa", "cheia", "lotada"],      # validate: allow english-only -- Portuguese words of the frozen copy
        "remind_nouns": ["lembrete", "lembretes"],      # validate: allow english-only -- Portuguese words of the frozen copy
        "triggers": {"reminders": ["meus lembretes", "quais lembretes", "quais sao meus lembretes", "quais sao os lembretes", "lista os lembretes", "liste os lembretes", "lista meus lembretes", "liste meus lembretes", "mostra meus lembretes", "mostre meus lembretes", "mostra os lembretes", "que lembretes"],      # validate: allow english-only -- Portuguese words of the frozen copy
                     "reminders_bare": ["lembretes"],      # validate: allow english-only -- Portuguese words of the frozen copy
                     "undo": ["desfaz", "desfazer", "desfaca", "desfaz isso", "volta o lembrete", "restaura o lembrete", "traz de volta"],      # validate: allow english-only -- Portuguese words of the frozen copy
                     "note": ["anote", "anota", "anotar"]},      # validate: allow english-only -- Portuguese words of the frozen copy
        "forget": {"verbs": ["esquece", "esqueca", "esquecer", "cancela", "cancele", "cancelar", "apaga", "apague", "apagar", "remove", "remova", "tira", "tire"], "id_words": ["numero", "n", "num", "nr"], "id_marked": ["no"]},      # validate: allow english-only -- Portuguese words of the frozen copy
    },
}


def _frozen_tables(languages):
    """The tables of `natural._tables(languages)`, each with the ten keys of the old reading put back from `FROZEN_WORDS` (by its tag; a table of another tag, a stub, gets them empty), whatever the
    live table holds. A table this function made is kept as it is, so the function is idempotent."""
    out = []
    for table in natural._tables(languages):
        if table.get("frozen_words"):
            out.append(table)
            continue
        words = FROZEN_WORDS.get(table.get("tag"), {})
        out.append({**table, "frozen_words": True,
                    "problem_words": list(words.get("problem_words", [])), "calendar_noun_reads": list(words.get("calendar_noun_reads", [])), "remind_nouns": list(words.get("remind_nouns", [])),
                    "triggers": {**table["triggers"], **{k: list(words.get("triggers", {}).get(k, [])) for k in ("reminders", "reminders_bare", "undo", "note")}},
                    "forget": {**table["forget"], **{k: list(words.get("forget", {}).get(k, [])) for k in ("verbs", "id_words", "id_marked")}}})
    return out


def _forget(norm: str, tables: list):
    """The facts of a line that asks to forget a reminder, or None. An EXPLICIT number names it ("reminder 9", "reminder #9", "reminder number 9": the number is the
    whole object) and is acted on at once; a number with any other word before it ("reminder of 3", "reminder no 3" in a language where "no" is a preposition) is
    shown and confirmed, and so are several numbers ("reminder 1 and 2"); anything else the line says after "of"/"about" is words to look for among the person's own
    reminders (whole words, numbers too: "about the 9 o'clock one" is words, never the id 9), or an hour ("the reminder at 9") matched against the moment of the
    reminders and confirmed. A word right after the noun with no connective ("reminder emails from inbox") is not about a reminder of the person's."""
    for table in tables:
        forget = table["forget"]
        verbs, nouns, fillers = nt._alt(forget["verbs"]), nt._alt(forget["nouns"]), nt._alt(forget["fillers"])
        if not verbs or not nouns:
            continue
        polite = nt._alt(table["polite"])
        lead = f"(?:{polite}\\s+)*" if polite else ""
        fill = f"(?:{fillers}\\s+)*" if fillers else ""
        tail = f"(?:\\s+{polite})*" if polite else ""
        m = re.match(f"[^a-z0-9]*{lead}{verbs}\\s+{fill}{nouns}(?![a-z0-9])", norm)
        if not m:
            bare = re.fullmatch(f"[^a-z0-9]*{lead}{verbs}\\s+(?:{fillers}\\s+)*#?\\s*([0-9]{{1,6}}){tail}[\\s?!.]*", norm) if fillers else None
            if bare and int(bare.group(1)) >= 1:          # "cancela #3", "cancela o 3": no noun, so it is shown and confirmed, and a sender who has no such reminder gets a plain line
                return {"id": int(bare.group(1)), "confirm": True, "bare": True}
            last = re.match(f"[^a-z0-9]*{lead}{verbs}\\s+{fill}(?P<mid>.+?)\\s+{nouns}[\\s?!.]*$", norm)
            if last:          # "cancel the 9am reminder": an hour in front of the noun
                found = nt.find(last.group("mid"), tables)
                stop = natural._stop(tables)
                left = natural._tidy(nt.without(last.group("mid"), nt._spans(found)), tables)
                if any(h["kind"] == "clock" for h in found["hits"]) and not [w for w in natural._words(left) if w not in stop]:
                    return {"id": None, "at": last.group("mid").strip(), "confirm": True}
            continue
        rest = norm[m.end():]
        idw = nt._alt(forget["id_words"])
        idm = nt._alt(forget["id_marked"])
        idp = f"(?:{idw}\\.?\\s*" + (f"|{idm}(?:\\.\\s*|(?=#?[0-9]))" if idm else "") + ")?" if idw else (f"(?:{idm}(?:\\.\\s*|(?=#?[0-9])))?" if idm else "")
        one = re.fullmatch(f"\\s*{idp}#?\\s*([0-9]{{1,6}}){tail}[\\s?!.]*", rest)
        if one and int(one.group(1)) >= 1:
            return {"id": int(one.group(1))}
        soft = re.fullmatch(f"\\s*(?:{fillers}\\s+)+#?\\s*([0-9]{{1,6}}){tail}[\\s?!.]*", rest) if fillers else None
        if soft and int(soft.group(1)) >= 1:
            return {"id": int(soft.group(1)), "confirm": True}
        tokens = natural._words(rest)
        stop = natural._stop(tables)
        numbers = [int(t) for t in tokens if t.isdigit()]
        if len(numbers) >= 2 and all(t.isdigit() or t in stop for t in tokens) and all(n >= 1 for n in numbers):
            ids = sorted(set(numbers))
            return {"id": None, "ids": ids, "confirm": True} if len(ids) <= MANY_IDS_MAX else {"id": None, "many": True}
        found = nt.find(rest, tables)
        if any(h["kind"] == "clock" for h in found["hits"]):
            left = natural._tidy(nt.without(rest, nt._spans(found)), tables)
            if not [w for w in natural._words(left) if w not in stop]:
                return {"id": None, "at": rest.strip(), "confirm": True}
        said = [t for t in tokens if t not in stop]
        if not said:
            return {"id": None}
        if len(tokens) > FORGET_WORDS_MAX or tokens[0] not in stop:
            return None
        return {"id": None, "words": said}
    return None


def _undo(norm: str, tables: list) -> bool:
    """Whether the line is the bare word that brings a cancelled reminder back ("undo", "desfaz"), optionally with "the reminder" and nothing else: "undo the deploy"
    and "desfaz o commit" are requests for something else."""
    for table in tables:
        alt = nt._alt(table["triggers"]["undo"])
        if not alt:
            continue
        polite = nt._alt(table["polite"])
        lead = f"(?:{polite}\\s+)*" if polite else ""
        forget = table["forget"]
        nouns, fillers = nt._alt(forget["nouns"]), nt._alt(forget["fillers"])
        noun = f"(?:\\s+(?:{fillers}\\s+)*{nouns})?" if nouns and fillers else (f"(?:\\s+{nouns})?" if nouns else "")
        trail = f"(?:\\s+{polite})*" if polite else ""
        if re.fullmatch(f"[^a-z0-9]*{lead}{alt}{noun}{trail}[\\s.!]*", norm):
            return True
    return False


def _verb_noun(norm: str, tables: list):
    """The end, in the folded line, of "<scheduling verb> [a word or two] <reminder noun>" at the start of the line ("marca um lembrete", "schedule a reminder"), or None."""
    best = None
    for table in tables:
        triggers = table["triggers"]
        verbs, nouns = nt._alt(triggers["calendar_verb"] + triggers["calendar_loose"] + triggers["calendar_noun"]), nt._alt(table["remind_nouns"])
        if not verbs or not nouns:
            continue
        polite = nt._alt(table["polite"])
        lead = f"(?:{polite}\\s+)*" if polite else ""
        m = re.match(f"[^a-z0-9]*{lead}{verbs}\\s+(?:[a-z0-9]+\\s+){{0,2}}?{nouns}(?![a-z0-9])", norm)
        if m and (best is None or m.end() > best):
            best = m.end()
    return best


def candidate(line, languages=None):
    """What the line is, with no clock (see the module's text), or None. Pure. S41-11 PR 2b: no site CLAIMS a line with it any more (the interpreter reads a line of words, L63); what is left reading
    it is the reminder question engine, to tell a reply that starts a request of its own (a new line) from the answer to the open question: `short_answer` and `complete` below."""
    tables = _frozen_tables(languages)
    text = line if isinstance(line, str) else ""
    if not text.strip() or text.lstrip().startswith("/"):
        return None
    norm, origin = nt.normalise(text)
    tokens = natural._words(norm)
    problem = {w for t in tables for w in t["problem_words"]} & set(tokens)
    if "?" not in text and _undo(norm, tables):
        return {"op": "reminder-restore", "how": "trigger"}
    forget = _forget(norm, tables)
    if forget:
        return {"op": "reminder-forget", "how": "trigger", **forget}
    listed = natural._head(norm, tables, "reminders")
    if listed is not None and len(natural._words(norm[listed:])) <= LIST_WORDS_MAX and not problem:
        return {"op": "reminders", "how": "trigger"}
    plain = natural._head(norm, tables, "reminders_bare")
    if plain is not None and not natural._words(norm[plain:]) and not problem:
        return {"op": "reminders", "how": "trigger"}
    if natural._head(norm, tables, "calendar") is not None:
        return {"op": "calendar-event-create", "how": "trigger"}
    if _verb_noun(norm, tables) is not None and not problem:          # "marca um lembrete", "schedule a reminder": the word reminder wins over the scheduling verb
        return {"op": "remind", "how": "trigger"}
    noun_head = natural._head(norm, tables, "remind")
    if noun_head is not None:
        verbal = any(re.match(f"[^a-z0-9]*{nt._alt(t['triggers']['remind_anywhere'])}(?![a-z0-9])", norm) for t in tables if t["triggers"]["remind_anywhere"])
        if not (problem and not verbal):          # "reminder 3 did not arrive" is a report, not a request
            return {"op": "remind", "how": "trigger"}
        return None
    hits = nt.find(text, tables)["hits"]
    if hits and natural._anywhere(norm, tables, "remind_anywhere"):
        return {"op": "remind", "how": "trigger"}
    if hits and natural._head(norm, tables, "calendar_verb") is not None:
        return {"op": "calendar-event-create", "how": "trigger"}
    if hits and natural._head(norm, tables, "calendar_loose") is not None:
        return {"op": "calendar-event-create", "how": "ask"}
    noun = natural._head(norm, tables, "calendar_noun")
    if noun is not None:                          # a bare calendar noun is a read ("calendar for tomorrow?"); only a request to put something on it, with a time, is asked about
        after = natural._words(norm[noun:])[:1]
        reads = {w for t in tables for w in t["calendar_noun_reads"]}
        if any(h["kind"] in ("clock", "relative") for h in hits) and "?" not in text and not (after and after[0] in reads):
            return {"op": "calendar-event-create", "how": "ask"}
        return None
    if natural._head(norm, tables, "note") is not None:
        return {"op": "remind", "how": "bare" if hits else "note"}
    if not any(h["kind"] in ("clock", "relative") for h in hits) or "?" in text or nt.recurring(text, tables):
        return None
    first = re.match(r"[^a-z0-9]*([a-z0-9]+)", norm)
    starters = {w for table in tables for w in table["work_starters"]}
    if first and first.group(1) in starters:
        return None
    rest = nt.without(text, nt._spans({"origin": origin, "hits": hits}))
    if not rest or len(rest.split()) > natural.BARE_WORDS_MAX:
        return None
    return {"op": "remind", "how": "bare"}


def claim(line, languages=None):
    """CB-9 (frozen): `candidate`, for a site that CLAIMS the line for a closed form (the bridge's reading of an update). The scope of a repeating line is gone from the product, so there is nothing
    left to take into account: this is `candidate`. Every site that only RECOGNISES a request of its own reads `candidate` too."""
    return candidate(line, languages)


def _trigger_span(norm: str, tables: list, how: str):
    """(start, end), in the folded line, of the trigger words to take out of the reminder's words, or None."""
    if how == "trigger":
        end = natural._head(norm, tables, "remind")
        if end is None:
            end = _verb_noun(norm, tables)
        return (0, end) if end is not None else natural._anywhere(norm, tables, "remind_anywhere")
    if how in ("bare", "note"):
        end = natural._head(norm, tables, "note")
        return (0, end) if end is not None else None
    return None


def understand(line, now, how="trigger", languages=None, trust=False, confirm=False):
    """The reminder `line` asks for at the clock `now` (see the module's text). `how` is "trigger", "bare", "note", "command" or "write" (package NR-5: the caller has cut the head of
    a write to the person's accounts, there is no trigger to cut, and the words that are left are the event's title). `trust` is true when the person has
    just answered a question about this line, so that a word the parse did not use is not asked about again; `confirm` makes the reading a confirmation whatever the line
    says (the answer to "which day next week?" is always shown with the day it resolved to)."""
    tables = _frozen_tables(languages)
    text = line if isinstance(line, str) else ""
    if nt.recurring(text, tables):
        return {"ask": natural._draft("recurring", how, text, "")}
    flagged, typos = nt.doubts(text, tables)
    for start, end, meant in sorted(typos, reverse=True):          # a day word with a typo is read as the word it is one letter from; with two such words it stays in the words
        if meant:
            text = text[:start] + meant + text[end:]
    norm, origin = nt.normalise(text)
    week = natural._week(norm, tables)
    if week:          # "next week at 10", "tuesday next week": the week is named; with no day of it the day is asked, with one it is the day of THAT week, shown and confirmed
        line2 = " ".join((text[:origin[week[0]]] + " " + text[origin[week[1] - 1] + 1:]).split())
        found2 = nt.find(line2, tables)
        if not any(h["kind"] in ("date", "slash") for h in found2["hits"]):
            norm2, origin2 = nt.normalise(line2)
            parsed = nt.parse(line2, now, tables)
            cuts = list(parsed["spans"]) if parsed else []
            trigger = _trigger_span(norm2, tables, how)
            if trigger:
                cuts.append((origin2[trigger[0]], origin2[trigger[1] - 1] + 1))
            return {"ask": natural._draft("weekday", how, line2, natural._tidy(nt.without(line2, cuts), tables))}
        inner = understand(line2, now, how, tables, trust=True)
        shape = inner["ask"] if "ask" in inner else {**inner, "readings": [inner["reading"]], "how": how, "line": line2, "doubt": False, "day": None, "need": "ready"}
        if shape["need"] in ("confirm", "kind", "text", "ready") and shape["readings"] and any(h["kind"] == "date" and h["spec"]["k"] == "wd" for h in found2["hits"]):
            reading = natural._next_week(shape["readings"][0], now) if shape["readings"][0].get("date") else shape["readings"][0]
            return natural._next(natural._draft("ready", how, line2, shape["text"], readings=[reading], doubt=True), reading)
        return inner
    found = nt.find(text, tables)
    parsed = nt.parse(text, now, tables)
    cuts = list(parsed["spans"]) if parsed else []
    if parsed and any(h.get("topic") for h in found["hits"]):          # "the meeting of friday": the weekday stays in the words, it may be what the reminder is about
        cuts = nt._spans({"origin": found["origin"], "hits": [h for h in found["hits"] if not h.get("topic")]})
    trigger = _trigger_span(norm, tables, how)
    if trigger:
        cuts.append((origin[trigger[0]], origin[trigger[1] - 1] + 1))
    words = natural._tidy(nt.without(text, cuts), tables)
    if parsed is None or "missing" in parsed:
        return {"ask": natural._draft("time", how, text, words, day=(parsed or {}).get("day"))}
    if "ask" in parsed:
        return {"ask": natural._draft("reading", how, text, words, readings=parsed["ask"])}
    reading = parsed["reading"]
    if reading.get("relative") and reading["relative"].endswith("d") and int(reading["relative"][3:-1]) <= 366 and not any(h["kind"] == "clock" for h in found["hits"]):
        return {"ask": natural._draft("time", how, text, words, day=nt._info(datetime.date.fromisoformat(reading["date"]), now))}          # "in 3 days": the day, and the hour is asked
    shipped = (trigger is not None and how in ("trigger", "note")) or how == "write"          # a write's head ("marca", "put on my calendar") was cut by the caller and is a shipped trigger
    dated = any(h["kind"] in ("date", "slash", "relative") for h in found["hits"])
    guard = nt.leftover_doubt(found, trigger, tables, unknown=how != "command" and not shipped and not dated)
    doubt = confirm or (not trust and (bool(parsed.get("vague")) or reading["assumed_year"] or flagged or guard))
    return natural._next(natural._draft("ready", how, text, words, readings=[reading], doubt=doubt), reading)

