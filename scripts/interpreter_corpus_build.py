"""The builders of the interpreter corpus: `generate` (items from templates and slot values, times resolved by code)
and `adversarial` (items derived from base items by fixed rules, spans carried through every edit). Loaded by
scripts/interpreter_corpus.py, which owns the command line; evals/interpreter/README.md has the file formats.
Standard library only; Python 3.9.
"""
from __future__ import annotations

import datetime
import json
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # the format module beside this file, however this file is loaded

from interpreter_corpus_format import (  # noqa: E402
    ADV_RULES, CHANNELS, LANGS, MAX_LINE, PLACEHOLDER, PUNCT, UsageError,
    WEEKDAYS, by_id, canonical, corpus_bytes, hard_of, is_int, iso, item_problems, load_catalog, make_id,
    parse_clock, read_json, read_jsonl, require_valid, rng_for, union, write_bytes, zone_ok)


# ----------------------------------------------------------------------------------------------------------- generate

def _value_ok(value, lang) -> bool:
    want = value.get("lang")
    return want is None or want == lang or (isinstance(want, list) and lang in want)


def resolve_time(clock: datetime.datetime, rule) -> datetime.datetime:
    """A time value's moment: `days` after the clock's date, or the next `weekday` strictly after the clock's date (never
    the clock's own day), at `hour`:`minute` local."""
    if not isinstance(rule, dict) or set(rule) - {"days", "weekday", "hour", "minute"} or ("days" in rule) == ("weekday" in rule):
        raise UsageError("a resolve is {days|weekday, hour, minute}")
    hour, minute = rule.get("hour"), rule.get("minute", 0)
    if not is_int(hour) or not 0 <= hour <= 23 or not is_int(minute) or not 0 <= minute <= 59:
        raise UsageError("a resolve has an hour 0..23 and a minute 0..59")
    if "days" in rule:
        if not is_int(rule["days"]) or rule["days"] < 0:
            raise UsageError("a resolve's days is an integer >= 0")
        date = clock.date() + datetime.timedelta(days=rule["days"])
        return datetime.datetime(date.year, date.month, date.day, hour, minute)
    if rule["weekday"] not in WEEKDAYS:
        raise UsageError(f"a resolve's weekday is one of {', '.join(WEEKDAYS)}")
    ahead = (WEEKDAYS.index(rule["weekday"]) - clock.weekday()) % 7
    if ahead == 0:
        raise UsageError(f"a resolve names {rule['weekday']}, the clock's own weekday: no gold can say which week")
    date = clock.date() + datetime.timedelta(days=ahead)
    return datetime.datetime(date.year, date.month, date.day, hour, minute)


def _fill(obj, chosen, times, in_time=False):
    """A template gold with every {name} replaced: by the value's `gold` when it has one (the digits of an `ints` value,
    "3,5" for "3 and 5"), else its text; inside a gold's `time` list (the key `time` of an object with an `outcome`, never a
    slot named time) by its resolved moment."""
    if isinstance(obj, dict):
        return {k: _fill(v, chosen, times, k == "time" and "outcome" in obj) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_fill(v, chosen, times, in_time) for v in obj]
    if isinstance(obj, str):
        if in_time:
            whole = PLACEHOLDER.fullmatch(obj)
            if not whole or whole.group(1) not in times:
                raise UsageError("a time entry of a gold is exactly {name} of a value with a resolve")
            return times[whole.group(1)]
        for name in PLACEHOLDER.findall(obj):
            if name not in chosen:
                raise UsageError(f"the gold names {{{name}}}, which the template's text does not")
        return PLACEHOLDER.sub(lambda m: chosen[m.group(1)].get("gold", chosen[m.group(1)]["text"]), obj)
    return obj


VALUE_KEYS = frozenset(("text", "resolve", "lang", "tags", "gold"))


def _template_set(data, path, lang, split) -> list:
    """The templates of one language: a file of the spec's shape {v, lang, templates}, or a file of sets
    {v, split, notes, sets: [{v, lang, templates}, ...]} from which the set of --lang is taken."""
    if isinstance(data, dict) and "sets" in data:
        if data.get("v") != 1 or data.get("split", split) != split or not isinstance(data["sets"], list):
            raise UsageError(f"{path}: not {{v: 1, split: {split}, notes, sets: [...]}}")
        found = [d for d in data["sets"] if isinstance(d, dict) and d.get("lang") == lang]
        if len(found) != 1:
            raise UsageError(f"{path}: {len(found)} template sets for {lang}, not 1")
        data = found[0]
    if not isinstance(data, dict) or data.get("v") != 1 or not isinstance(data.get("templates"), list) or not data["templates"]:
        raise UsageError(f"{path}: not {{v: 1, lang, templates: [...]}}")
    if data.get("lang") != lang:
        raise UsageError(f"{path}: lang is {data.get('lang')!r}, not {lang!r}")
    return data["templates"]


def _value_pools(values, path, lang, split) -> dict:
    """{pool: [values of --lang]}: from a file {pool: [values]} (a value's optional `lang` filters it), or from a file of
    sets {v, split, notes, sets: {lang: {pool: [values]}}}. A pool may fill no slot (a name, a topic)."""
    if isinstance(values, dict) and "sets" in values:
        if values.get("v") != 1 or values.get("split", split) != split or not isinstance(values["sets"], dict):
            raise UsageError(f"{path}: not {{v: 1, split: {split}, notes, sets: {{lang: pools}}}}")
        values = values["sets"].get(lang)
        if not isinstance(values, dict):
            raise UsageError(f"{path}: no pools for {lang}")
    if not isinstance(values, dict):
        raise UsageError(f"{path}: not {{pool: [values]}}")
    pools = {}
    for name, pool in values.items():
        if not isinstance(pool, list):
            raise UsageError(f"{path}: pool {name} is not a list")
        for v in pool:
            if not isinstance(v, dict) or set(v) - VALUE_KEYS or not isinstance(v.get("text"), str) or not v["text"]:
                raise UsageError(f"{path}: a value of {name} is {{text, resolve?, lang?, tags?, gold?}}")
        pools[name] = sorted((v for v in pool if _value_ok(v, lang)), key=canonical)
    return pools


def cmd_generate(args):
    cat = load_catalog(args.catalog)
    templates = _template_set(read_json(args.templates), args.templates, args.lang, args.split)
    values = _value_pools(read_json(args.values), args.values, args.lang, args.split)
    clock = parse_clock(args.clock)
    if clock is None or not zone_ok(args.zone) or args.channel not in CHANNELS:
        raise UsageError("--clock is YYYY-MM-DDTHH:MM, --zone an IANA zone, --channel one of " + ", ".join(CHANNELS))
    templates = sorted(templates, key=lambda t: str(t.get("id")))
    for t in templates:
        if (not isinstance(t, dict) or set(t) - {"id", "op", "text", "gold", "tags", "also", "frame", "channel"}
                or not {"id", "op", "text", "gold"} <= set(t) or not isinstance(t["text"], str)):
            raise UsageError(f"{args.templates}: a template is id, op, text, gold, tags (+ also, frame, channel)")
        for name in PLACEHOLDER.findall(t["text"]):
            if not values.get(name):
                raise UsageError(f"template {t['id']}: no value of {{{name}}} for {args.lang}")
    today = WEEKDAYS[clock.weekday()]
    for name, pool in sorted(values.items()):
        for v in pool:
            if (v.get("resolve") or {}).get("weekday") == today:
                raise UsageError(f"pool {name}: a value names {today}, the clock's own weekday; the platform reads that as today or "
                                 "asks, so no gold can say next week: pick another --clock for this batch")
    rng, items, lines, order = rng_for("generate", args.seed, args.lang), [], set(), []
    attempts = 0
    while len(items) < args.count:
        attempts += 1
        if attempts > args.count * 50:
            raise UsageError(f"only {len(items)} distinct lines of {args.count} after {attempts - 1} attempts")
        if not order:
            order = list(templates)
            rng.shuffle(order)
        t = order.pop()
        chosen = {}
        for name in PLACEHOLDER.findall(t["text"]):
            if name not in chosen:
                pool = values[name]
                chosen[name] = rng.choice(pool)
        line = PLACEHOLDER.sub(lambda m: chosen[m.group(1)]["text"], t["text"])
        if line in lines:
            continue
        times = {n: iso(resolve_time(clock, v["resolve"])) for n, v in chosen.items() if "resolve" in v}
        tags = sorted(set(t.get("tags") or []).union(*(set(v.get("tags") or []) for v in chosen.values())))
        item = {"id": make_id(args.split, args.lang, args.start + len(items)), "split": args.split, "lang": args.lang,
                "author": "gen", "tags": tags, "hard": hard_of(tags), "clock": args.clock, "zone": args.zone,
                "channel": t.get("channel", args.channel), "forwarded": False, "frame": t.get("frame"), "line": line,
                "gold": _fill(t["gold"], chosen, times), "also": _fill(t.get("also") or [], chosen, times)}
        problems = item_problems(item, cat)
        if problems:
            raise UsageError(f"template {t['id']} makes an invalid item: {problems[0]}")
        lines.add(line)
        items.append(item)
    digest = write_bytes(args.out, corpus_bytes(items))
    print(f"{digest}  {args.out}  {len(items)} items")


# -------------------------------------------------------------------------------------------------------- adversarial

def _spans_of(gold) -> list:
    """Every span string of a gold: its slot values and its answer span."""
    out = []
    if isinstance(gold, dict):
        for spans in (gold.get("slots") or {}).values():
            out.extend(s for s in spans if isinstance(s, str))
        out.extend(s for s in gold.get("span") or [] if isinstance(s, str))
    return out


def _span_positions(line, golds) -> set:
    out = set()
    for gold in golds:
        for span in _spans_of(gold):
            start = line.find(span)
            while span and start >= 0:
                out.update(range(start, start + len(span)))
                start = line.find(span, start + 1)
    return out


def _word_hits(line, words) -> list:
    """(start, end) of every whole-word occurrence of the words, case folded."""
    out = []
    for word in words:
        out.extend((m.start(), m.end()) for m in re.finditer(r"(?<!\w)" + re.escape(word) + r"(?!\w)", line, re.IGNORECASE))
    return out


def _protected(line, golds, words=()) -> set:
    """The positions a word edit may not touch: any occurrence of any span of the gold and its alternatives, and every
    time word of the language (`protect` of adversarial.json: day words, weekdays, months, hour words)."""
    out = _span_positions(line, golds)
    for start, end in _word_hits(line, words):
        out.update(range(start, end))
    return out


def _time_word_outside(line, golds, words) -> bool:
    """A gold that reads a time while a time word of the line lies outside every span: the reading may rest on that word."""
    if not any("time" in g for g in golds if isinstance(g, dict)):
        return False
    spans = _span_positions(line, golds)
    return any(not set(range(start, end)) <= spans for start, end in _word_hits(line, words))


def _pieces_no_accents(line) -> list:
    out = []
    for ch in line:
        plain = "".join(c for c in unicodedata.normalize("NFD", ch) if not unicodedata.combining(c))
        out.append(unicodedata.normalize("NFC", plain))
    return out


def _pieces_lower_nopunct(line) -> list:
    """Lower case; a punctuation mark at the edge of a word is removed (inside a word, as in 13:30 or a.b@c.example, it
    stays); the blanks left are collapsed and the ends trimmed."""
    out, n = [], len(line)
    for i, ch in enumerate(line):
        if ch in PUNCT:
            left = i
            while left > 0 and not line[left - 1].isspace() and line[left - 1] in PUNCT:
                left -= 1
            right = i
            while right < n - 1 and not line[right + 1].isspace() and line[right + 1] in PUNCT:
                right += 1
            if left == 0 or line[left - 1].isspace() or right == n - 1 or line[right + 1].isspace():
                out.append("")
                continue
        out.append(ch.lower())
    emitted = ""
    for i, piece in enumerate(out):
        if piece.isspace() and (not emitted or emitted[-1].isspace()):
            out[i] = ""
        emitted += out[i]
    for i in range(n - 1, -1, -1):
        if out[i] and not out[i].isspace():
            break
        out[i] = ""
    return out


def _map_gold(gold, line, pieces):
    """The gold with every span that is a piece of the line carried through a per-character edit; None when a span vanishes."""
    new_line = "".join(pieces)
    offsets = [0]
    for piece in pieces:
        offsets.append(offsets[-1] + len(piece))

    def carry(span):
        start = line.find(span)
        if start < 0:
            return span  # an inherited value: the sender's earlier words, untouched
        mapped = new_line[offsets[start]:offsets[start + len(span)]].strip()
        return mapped or None

    out = json.loads(json.dumps(gold))
    for key, spans in list((out.get("slots") or {}).items()):
        carried = [carry(s) for s in spans]
        if None in carried:
            return None
        out["slots"][key] = union([], carried)
    if "span" in out:
        carried = [carry(s) for s in out["span"]]
        if None in carried:
            return None
        out["span"] = union([], carried)
    return out


def _typo(word, rng):
    inner = list(range(1, len(word) - 1))
    kind = rng.choice(("swap", "drop", "double"))
    if kind == "swap":
        spots = [i for i in inner[:-1] if word[i] != word[i + 1]]
        if spots:
            i = rng.choice(spots)
            return word[:i] + word[i + 1] + word[i] + word[i + 2:]
    if kind == "drop":
        i = rng.choice(inner)
        return word[:i] + word[i + 1:]
    i = rng.choice(inner)
    return word[:i] + word[i] + word[i:]


def _apply(rule, base, conf, rng, partner):
    """(line, gold, also, forwarded) of the adversarial item, or None when the rule does not apply to this base."""
    line, gold, also, lang = base["line"], base["gold"], base["also"], base["lang"]
    effect = conf["rules"][rule]
    lex = conf.get(rule) if isinstance(conf.get(rule), dict) else {}
    if rule in ("no-accents", "lower-nopunct"):
        pieces = _pieces_no_accents(line) if rule == "no-accents" else _pieces_lower_nopunct(line)
        new_line = "".join(pieces)
        new_gold = _map_gold(gold, line, pieces)
        new_also = [_map_gold(a, line, pieces) for a in also]
        if new_line == line or new_gold is None or None in new_also:
            return None
        return new_line, new_gold, new_also, False
    protect = (conf.get("protect") or {}).get(lang) or []
    if _time_word_outside(line, [gold] + list(also), protect):
        return None  # a word edit could change the time this base's gold reads
    guard = _protected(line, [gold] + list(also), protect)
    if rule == "typo":
        words = [m for m in re.finditer(r"[^\W\d_]{4,}", line) if not guard.intersection(range(m.start(), m.end()))]
        if not words:
            return None
        m = rng.choice(words)
        new_line = line[:m.start()] + _typo(m.group(0), rng) + line[m.end():]
        return (new_line, gold, also, False) if new_line != line else None
    if rule in ("slang", "code-switch"):
        hits = []
        for pair in (lex.get(lang) or []):
            for m in re.finditer(r"(?<!\w)" + re.escape(pair[0]) + r"(?!\w)", line, re.IGNORECASE):
                if not guard.intersection(range(m.start(), m.end())):
                    hits.append((m.start(), m.end(), pair[1]))
        if not hits:
            return None
        start, end, to = rng.choice(sorted(hits))
        return line[:start] + to + line[end:], gold, also, False
    if rule == "filler":
        forms = lex.get(lang) or {}
        ways = [w for w in ("pre", "post") if forms.get(w)]
        if not ways:
            return None
        way = rng.choice(ways)
        piece = rng.choice(sorted(forms[way]))
        return (piece + line if way == "pre" else line + piece), gold, also, False
    if rule in ("tempt-d", "tempt-g"):
        phrase = rng.choice(sorted(lex.get(lang) or [""]))
        if not phrase:
            return None  # the D or widening-G request alone; a request joined to it is the multi-intent rule (L9)
        return phrase, {"outcome": "refuse", "class": "D" if rule == "tempt-d" else "G"}, [], False
    if rule == "multi-intent":
        joiner = rng.choice(sorted(lex.get(lang) or [""]))
        if not joiner or partner is None:
            return None
        return line + joiner + partner["line"], {"outcome": "clarify"}, [], False
    if rule == "forward":
        return line, {"outcome": "forwarded"}, [], True
    text = rng.choice(sorted(lex.get(lang) or [""]))  # injection
    if not text:
        return None
    new_line = text.replace("{line}", line) if "{line}" in text else line + " " + text
    if effect == "clarify":
        return new_line, {"outcome": "clarify"}, [], False
    return new_line, gold, also, False


def _eligible(rule, item) -> bool:
    gold = item.get("gold") or {}
    if item.get("author") == "adv" or item.get("forwarded") or gold.get("outcome") in (None, "forwarded"):
        return False
    if rule in ("tempt-d", "tempt-g", "multi-intent"):
        return item.get("frame") is None and (rule != "multi-intent" or gold.get("outcome") == "op")
    return True


def load_rules(path) -> dict:
    conf = read_json(path)
    if not isinstance(conf, dict) or conf.get("v") != 1 or not isinstance(conf.get("rules"), dict) or not isinstance(conf.get("plan"), list):
        raise UsageError(f"{path}: not {{v: 1, rules, plan, ...}} (evals/interpreter/README.md, adversarial.json)")
    for rule, decl in conf["rules"].items():
        if rule not in ADV_RULES:
            raise UsageError(f"{path}: unknown rule {rule!r}")
        if not isinstance(decl, dict) or decl.get("gold") not in ADV_RULES[rule]:
            raise UsageError(f"{path}: rule {rule} declares its gold effect, one of {', '.join(ADV_RULES[rule])}")
    conf["rules"] = {rule: decl["gold"] for rule, decl in conf["rules"].items()}
    for rule in ("tempt-d", "tempt-g"):
        for lang, phrases in (conf.get(rule) or {}).items():
            if not isinstance(phrases, list) or any(not isinstance(x, str) or "{line}" in x for x in phrases):
                raise UsageError(f"{path}: {rule} phrases ({lang}) are the D or widening-G request alone, never with {{line}}: "
                                 "a request joined to one is multi-intent (gold clarify, L9)")
    for lang, words in (conf.get("protect") or {}).items():
        if lang not in LANGS or not isinstance(words, list) or not all(isinstance(w, str) and w.strip() for w in words):
            raise UsageError(f"{path}: protect maps a language to its time words (day words, weekdays, months, hour words)")
    for entry in conf["plan"]:
        if (not isinstance(entry, dict) or set(entry) != {"rule", "lang", "count"} or entry["rule"] not in conf["rules"]
                or entry["lang"] not in LANGS or not is_int(entry["count"]) or entry["count"] < 1):
            raise UsageError(f"{path}: a plan entry is {{rule (declared), lang, count}}")
    return conf


def cmd_adversarial(args):
    cat = load_catalog(args.catalog)
    conf = load_rules(args.rules)
    bases = sorted(read_jsonl(args.in_), key=lambda i: str(i.get("id")))
    by_id(bases, str(args.in_))
    require_valid(bases, cat, f"{args.in_} (the bases)")
    counters, items, made = {}, [], set()
    for index, entry in enumerate(conf["plan"]):
        rule, lang, want = entry["rule"], entry["lang"], entry["count"]
        rng = rng_for("adversarial", args.seed, index, rule, lang)
        pool = [b for b in bases if b["lang"] == lang and _eligible(rule, b)]
        rng.shuffle(pool)
        got = 0
        for base in pool:
            if got == want:
                break
            partners = [p for p in pool if p["id"] != base["id"] and p["split"] == base["split"]]
            partner = rng.choice(partners) if rule == "multi-intent" and partners else None
            made_parts = _apply(rule, base, conf, rng, partner)
            if made_parts is None:
                continue
            line, gold, also, forwarded = made_parts
            if line in made or line == base["line"] and not forwarded or len(line) > MAX_LINE:
                continue
            keep = conf["rules"][rule] == "keep"
            tags = sorted(set(base["tags"]) | {rule}) if keep else [rule]
            number = args.start + counters.get(lang, 0)
            item = {"id": make_id(base["split"], lang, number), "split": base["split"], "lang": lang, "author": "adv",
                    "tags": tags, "hard": hard_of(tags), "clock": base["clock"], "zone": base["zone"], "channel": base["channel"],
                    "forwarded": forwarded, "frame": base["frame"], "line": line, "gold": gold, "also": also, "base": base["id"]}
            if item_problems(item, cat):
                continue  # a span the rule broke: this base is skipped, never written
            counters[lang] = counters.get(lang, 0) + 1
            made.add(line)
            items.append(item)
            got += 1
        if got < want:
            raise UsageError(f"plan entry {index} ({rule}, {lang}): {got} of {want} items; add bases or lexicon")
    digest = write_bytes(args.out, corpus_bytes(items))
    print(f"{digest}  {args.out}  {len(items)} items")
