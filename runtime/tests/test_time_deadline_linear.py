"""The deadline reading of the time engine reads a line once (runtime/natural_time.py `_deadlines`; decision 2026-10-30, fuzz-slow-deadlines).

`natural_time.find` sets a date apart as a deadline ("expires on the 15th") by looking at the words before each date, at the hits that end before it and at the clocks of the line. It used to do that by
scanning the whole text before EACH hit and the whole list of hits for EACH hit, so its time grew with the square of the line: a message of 10,000 characters of times took about a second, one of
40,000 about twenty, on text a person sends from a channel. It now builds its tables once.

What is proven here, each with its vacuity:

  * The new reading gives, for random lines and random hit lists (every kind of hit, touching, overlapping and cut-in-a-word spans, the deadline words, the destination words and the break
    words of both languages), the SAME split as the reading it replaced, kept here as the oracle with its own literals. Vacuity: an oracle that drops one condition (the clock that follows the
    date; the break words) differs from the new reading on some generated case, so the cases do reach those conditions; and the cases hold both deadlines and moments.
  * A line of 50,000 characters of times and deadline words is read in well under a second. Vacuity: the old reading takes more than ten times as long on a line of 8,000.

Offline, no model, no network. Invented words only.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_time_deadline_linear.py
"""
from __future__ import annotations

import random
import re
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import natural_time as nt  # noqa: E402


def old_deadlines(norm, hits, tables, *, ignore=()):
    """The reading before the fix, as it was written (a scan of the text before each hit and of the list of hits for each hit). `ignore` names one condition to leave out, for the vacuity cases."""
    words = {w for t in tables for w in t.get("deadline_words", [])}
    if not words:
        return hits, []
    stops = {w for t in tables for w in t.get("deadline_to", [])}
    breaks = [tuple(p.split()) for t in tables for p in t.get("deadline_breaks", [])]
    kept, deadline = [], []
    for h in hits:
        before = re.findall(r"[a-z0-9]+", norm[:h["s"]])[-2:]
        near = re.findall(r"[a-z0-9]+", norm[:h["s"]])[-3:]
        own = re.findall(r"[a-z0-9]+", norm[h["s"]:h["e"]])
        earlier = [g for g in hits if g is not h and g["e"] <= h["s"]]
        gap = re.findall(r"[a-z0-9]+", norm[max(g["e"] for g in earlier):h["s"]]) if earlier else []
        if (h["kind"] in ("date", "slash") and any(w in words for w in before)
                and not (own and own[0] in stops) and not any(w in stops for w in near)
                and (("breaks" in ignore) or not any(tuple(gap[i:i + len(b)]) == b for b in breaks for i in range(len(gap))))
                and any(g["kind"] in ("date", "slash", "relative") for g in earlier)
                and any(g is not h and g["kind"] == "clock" for g in hits)
                and (("clock-after" in ignore) or not any(g["kind"] == "clock" and g["s"] >= h["e"] for g in hits))):
            deadline.append(h)
        else:
            kept.append(h)
    return kept, deadline


TABLES = nt.languages()
VOCABULARY = ["tomorrow", "at", "9am", "on", "the", "15th", "expires", "due", "deadline", "to", "for", "until", "then", "again", "and", "also", "remind", "me", "renew", "permit",
              "vence", "prazo", "dia", "15", "para", "ate", "e", "depois", "de", "novo", "tambem", "amanha", "9h", "x9am"]
KINDS = ["clock", "date", "slash", "relative", "vague"]


def a_line(rng):
    """(norm, hits) of a random line: words and separators, and hits on spans of one to three words, sometimes cut inside a word, sometimes overlapping the one before."""
    words = [rng.choice(VOCABULARY) for _ in range(rng.randint(2, 14))]
    norm = ""
    spans = []
    for w in words:
        norm += rng.choice(["", " ", "  ", ", ", " - "]) if norm else ""
        start = len(norm)
        norm += w
        spans.append((start, len(norm)))
    hits = []
    for _ in range(rng.randint(0, 6)):
        a = rng.randrange(len(spans))
        b = min(len(spans) - 1, a + rng.randint(0, 2))
        s, e = spans[a][0], spans[b][1]
        if rng.random() < 0.1:
            s = min(e, s + 1)          # cut inside a word
        if rng.random() < 0.1:
            e = max(s, e - 1)
        hits.append({"kind": rng.choice(KINDS), "s": s, "e": e})
    hits.sort(key=lambda h: h["s"])
    return norm, hits


def split_ids(result, hits):
    kept, deadline = result
    return [hits.index(h) for h in kept], [hits.index(h) for h in deadline]


def run_all(count, seed, old):
    rng = random.Random(seed)
    counts = {"deadline": 0, "moment": 0, "differs": 0}
    for _ in range(count):
        norm, hits = a_line(rng)
        got = split_ids(nt._deadlines(norm, list(hits), TABLES), hits)
        want = split_ids(old(norm, list(hits), TABLES), hits)
        counts["deadline"] += bool(want[1])
        counts["moment"] += bool(want[0])
        counts["differs"] += got != want
    return counts


def test_the_new_reading_splits_every_random_line_as_the_old_one_did():
    counts = run_all(60000, 20261030, old_deadlines)
    assert counts["differs"] == 0
    assert counts["deadline"] > 300 and counts["moment"] > 30000      # the cases hold both outcomes, so that "no difference" is not "nothing was decided"


@pytest.mark.parametrize("ignored", ["clock-after", "breaks"])
def test_vacuity_an_oracle_without_one_condition_differs_on_some_case(ignored):
    counts = run_all(60000, 20261030, lambda norm, hits, tables: old_deadlines(norm, hits, tables, ignore=(ignored,)))
    assert counts["differs"] > 0


def test_the_real_lines_of_the_tests_that_pin_the_deadline_are_split_as_before():
    lines = ["Remind me tomorrow at 9am to renew the parking permit before it expires on the 15th.", "Me lembra amanha as 9h que o contrato vence em 15/11.",
             "tomorrow at 9am, then again on the due date, the 15th", "move tomorrow's 9am meeting to the deadline on the 20th", "due on the 15th at 3pm tomorrow 9am",
             "tomorrow at 9am and it is due on the 15th"]
    for line in lines:
        norm, _origin = nt.normalise(line)
        norm = nt._numerals(norm, TABLES)
        hits = sorted(nt._scan(norm, TABLES), key=lambda h: h["s"])
        assert split_ids(nt._deadlines(norm, list(hits), TABLES), hits) == split_ids(old_deadlines(norm, list(hits), TABLES), hits), line


# --- the time ----------------------------------------------------------------------------------------------------------------------------------------------

HEAD = "tomorrow at 9am "
SHAPES = {"deadlines": "due on 15th ", "clocks": "at 9am "}          # a moment and a clock, then dates that are all deadlines; or a clock again and again


def a_long_line(shape, size):
    """`size` characters of the head and then the shape's unit, and the hits of its clocks, its relative day and its dates, as the scan makes them."""
    unit = SHAPES[shape]
    norm = (HEAD + unit * (size // len(unit) + 1))[:size]
    hits = []
    for m in re.finditer(r"9am|tomorrow|15th", norm):
        hits.append({"kind": {"9am": "clock", "tomorrow": "relative", "15th": "date"}[m.group()], "s": m.start(), "e": m.end()})
    return norm, hits


def seconds(reading, shape, size):
    norm, hits = a_long_line(shape, size)
    start = time.perf_counter()
    got = reading(norm, hits, TABLES)
    return time.perf_counter() - start, got, hits


@pytest.mark.parametrize("shape, deadlines", [("deadlines", 3000), ("clocks", 0)])
def test_a_line_of_fifty_thousand_characters_of_times_and_deadlines_is_read_in_well_under_a_second(shape, deadlines):
    took, (kept, deadline), hits = seconds(nt._deadlines, shape, 50000)
    assert len(hits) > 3000
    assert len(kept) + len(deadline) == len(hits)
    assert len(deadline) >= deadlines          # the work was done: every date after "due on" has a moment before it, a clock in the line and none after it
    assert took < 1.0, f"{took:.2f} s for {len(hits)} hits"


@pytest.mark.parametrize("shape", ["deadlines", "clocks"])
def test_vacuity_the_old_reading_takes_more_than_ten_times_as_long_on_eight_thousand_characters(shape):
    samples = [seconds(nt._deadlines, shape, 8000) for _ in range(3)]          # the fastest of three: one slow sample of a millisecond-long call, on a busy machine, is not the call's cost
    new, got_new, hits = min(samples, key=lambda sample: sample[0])
    old, got_old, _ = seconds(old_deadlines, shape, 8000)
    assert split_ids(got_new, hits) == split_ids(got_old, hits)
    assert old > 10 * new, f"old {old:.3f} s, new {new:.3f} s"
