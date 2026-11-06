#!/usr/bin/env python3
"""Deterministic checks and state updates for a clarification.

Usage:
  clarify.py round --file <reply.md>            check a round of questions (or "-" to read stdin)
  clarify.py brief --file <brief.md>            check a written brief against the template
  clarify.py state --state <state.md> [--decision "<text> (<by>)"]... [--open "<question>"]...
                   [--artifact <brief path>] [--date YYYY-MM-DD]
                                                append to the state file without rewriting it
  clarify.py today                              print today's date

Every command prints JSON to stdout: {"ok": true|false, "errors": [...], "warnings": [...], "next": "..."}.
Do what "next" says. Exit code: 0 ok, 1 errors found, 2 usage error. Nothing is ever prompted.

A round is the part of a reply that asks. Each question is written as:

  **Q1. <one question, one decision>?**
  - Options: <optional, one line>
  - Recommended: <an answer the user can accept by saying "yes">
  - Why: <one sentence>
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sys

MAX_QUESTIONS = 3
MAX_WHY_WORDS = 35
NEXT_LINE = "Nothing is written yet, and every question above stays open until you answer it."
Q_RE = re.compile(r"^\s*(?:#{2,4}\s*|\*\*)Q(\d+)[.:]\s*(.+?)\s*(?:\*\*)?\s*$")
FIELD_RE = re.compile(r"^\s*[-*]\s*\**(Options|Recommended|Why)\**\s*:\**\s*(.*)$", re.I)
# A recommendation that hands the question back is not an answer.
NOT_AN_ANSWER = re.compile(
    r"^\W*(tell me|point me|let me know|share|send|provide|give me|paste|describe|it depends|depends|"
    r"up to you|your call|you decide|unknown|n/?a|none|tbd)\b", re.I)
PLACEHOLDER = re.compile(r"<(topic|YYYY-MM-DD|one sentence|fact|question|file or artifact|technical, time|what |"
                         r"the choice|one line|\.\.\.)[^<>\n]*>|^\W*\.\.\.\W*$")
BRIEF_SECTIONS = ["Goal", "Scope", "Constraints", "Decisions", "Facts established without asking",
                  "Open questions", "Contradictions surfaced"]
EMPTY_OUT = re.compile(r"^\W*(none|nothing|n/?a|tbd|-)?\W*$", re.I)


def out(errors, warnings, next_ok, extra=None):
    ok = not errors
    data = {"ok": ok, "errors": errors, "warnings": warnings,
            "next": next_ok if ok else "Fix every error, then run this command again."}
    data.update(extra or {})
    print(json.dumps(data, indent=2, ensure_ascii=False))
    return 0 if ok else 1


def read(path):
    if path == "-":
        return sys.stdin.read()
    with open(path, encoding="utf-8") as f:
        return f.read()


def sentences(text):
    """Count sentences: terminators followed by a space and a capital, plus the last one."""
    text = text.strip()
    return 0 if not text else 1 + len(re.findall(r"[.!?][\"')\]]*\s+(?=[A-Z])", text))


def parse_round(text):
    questions, cur = [], None
    for line in text.splitlines():
        m = Q_RE.match(line)
        if m:
            cur = {"n": int(m.group(1)), "title": m.group(2).strip("* "), "fields": {}, "extra": []}
            questions.append(cur)
            continue
        if cur is None:
            continue
        if re.match(r"^\s*#{1,6}\s", line):  # a heading ends the question
            cur = None
            continue
        f = FIELD_RE.match(line)
        if f:
            cur["fields"][f.group(1).lower()] = f.group(2).strip()
        elif line.strip():
            cur["extra"].append(line.strip())
    return questions


HOLDS_RE = re.compile(r"^which one holds\b", re.I)


def contradictions_listed(text):
    """True when the round's "### Contradictions" section holds a line other than "none"."""
    inside = False
    for line in text.splitlines():
        if re.match(r"^\s*#{1,6}\s", line):
            inside = bool(re.match(r"^\s*#{1,6}\s*Contradictions\s*$", line, re.I))
            continue
        if inside and line.strip() and not re.fullmatch(r"\W*none\W*", line.strip(), re.I):
            return True
    return False


def check_round(text):
    errors, warnings = [], []
    qs = parse_round(text)
    listed = contradictions_listed(text)
    if listed and qs and not HOLDS_RE.match(qs[0]["title"]):
        errors.append('Q1: a contradiction is listed, so Q1 asks "Which one holds: <what the request says>, or '
                      '<what the file says>?"')
    if not qs:
        errors.append('no question found: write each one as "**Q1. <question>?**" on its own line')
    if len(qs) > MAX_QUESTIONS:
        errors.append(f"{len(qs)} questions in the round: ask at most {MAX_QUESTIONS}, the ones other "
                      "decisions depend on; keep the rest for the next round")
    for q in qs:
        tag = f"Q{q['n']}"
        marks = q["title"].count("?")
        if marks == 0:
            errors.append(f"{tag}: the title is not a question (no question mark)")
        if marks > 1:
            errors.append(f"{tag}: {marks} question marks in the title: one question asks one thing; split it")
        holds = q is qs[0] and listed and HOLDS_RE.match(q["title"])
        if not holds and re.search(r"\band\b|;|, (?:or|plus|also)\b", q["title"], re.I):
            errors.append(f'{tag}: the title joins two things ("and", ";"): ask one decision, and move the '
                          "other to its own question or to the next round")
        asked_after = [e for e in q["extra"] if "?" in e]
        if asked_after or "?" in q["fields"].get("options", ""):
            errors.append(f"{tag}: more questions follow the title: keep one question, and put choices on "
                          'one "- Options:" line without a question mark')
        elif q["extra"]:
            warnings.append(f"{tag}: {len(q['extra'])} line(s) outside Options, Recommended and Why; keep the "
                            "question to its template")
        rec = q["fields"].get("recommended", "")
        if not rec:
            errors.append(f'{tag}: no "- Recommended:" line with an answer')
        elif NOT_AN_ANSWER.match(rec) or "?" in rec:
            errors.append(f'{tag}: the recommendation is not an answer ("{rec[:50]}"): write the answer you '
                          'would pick, which the user can accept by saying "yes"; when only the user knows '
                          "the fact, recommend the most likely value and say it is your reading")
        why = q["fields"].get("why", "")
        if not why:
            errors.append(f'{tag}: no "- Why:" line')
        else:
            if sentences(why) > 1:
                errors.append(f"{tag}: the Why has {sentences(why)} sentences: keep one sentence, on one line")
            if len(why.split()) > MAX_WHY_WORDS:
                errors.append(f"{tag}: the Why has {len(why.split())} words: at most {MAX_WHY_WORDS}")
    if " ".join(NEXT_LINE.lower().split()) not in " ".join(text.lower().split()):
        errors.append('the "### Next" section must open with the line "' + NEXT_LINE + '", copied as written')
    return out(errors, warnings, "Send the round as it is and end your turn; write no brief until the user answers.",
               {"questions": len(qs)})


def sections_of(text):
    found, cur = {}, None
    for line in text.splitlines():
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if m:
            cur = m.group(1)
            found[cur] = []
        elif cur is not None:
            found[cur].append(line)
    return found


def check_brief(text):
    errors, warnings = [], []
    if not re.search(r"^# Brief: \S", text, re.M):
        errors.append('the first line is not "# Brief: <topic>"')
    if not re.search(r"^- Date: \d{4}-\d{2}-\d{2}\s*$", text, re.M):
        errors.append('no "- Date: YYYY-MM-DD" line; take the date from `clarify.py today`')
    sec = sections_of(text)
    for name in BRIEF_SECTIONS:
        if name not in sec:
            errors.append(f'section "## {name}" is missing')
        elif not any(l.strip() for l in sec[name]):
            errors.append(f'section "## {name}" is empty: write its content, or "none" where the template allows it')
    for i, line in enumerate(text.splitlines(), 1):
        if PLACEHOLDER.search(line) or re.search(r"\|\s*\.\.\.\s*\|", line):
            errors.append(f"line {i}: a template placeholder is left: {line.strip()[:60]}")
    scope = sec.get("Scope", [])
    for label in ("In", "Out"):
        idx = next((i for i, l in enumerate(scope) if re.match(rf"^\s*[-*]\s*\**{label}\**\s*:", l)), None)
        if idx is None:
            errors.append(f'Scope has no "- {label}:" line')
            continue
        inline = scope[idx].split(":", 1)[1]
        nested = []
        for l in scope[idx + 1:]:
            if re.match(r"^\s+[-*]\s+\S", l):
                nested.append(l)
            elif l.strip():
                break
        if EMPTY_OUT.match(inline) and not nested:
            errors.append(f'Scope "{label}" is empty: list what is {label.lower()}; when the user named nothing '
                          "as out, park it as an open question and write \"Out: not decided, see open questions\"")
    rows = [l for l in sec.get("Decisions", []) if l.strip().startswith("|")]
    body = [r for r in rows[2:]] if len(rows) >= 2 else []
    if "Decisions" in sec and not body and not any("none" in l.lower() for l in sec["Decisions"]):
        errors.append('Decisions has no row: add one row per decision, or the line "none"')
    for r in body:
        cells = [c.strip() for c in r.strip().strip("|").split("|")]
        if len(cells) != 5:
            errors.append(f"decision row does not have 5 cells (#, Decision, Chosen, Why, By): {r.strip()[:60]}")
            continue
        if not cells[4]:
            errors.append(f'decision {cells[0]}: "By" is empty: name who decided (user, assumed, or the file that records it)')
        if re.search(r"\b(parked|open question|not decided|undecided|tbd)\b", cells[2], re.I):
            errors.append(f"decision {cells[0]}: a parked item is not a decision: remove the row and keep it under "
                          '"Open questions" only')
        if re.fullmatch(r"`?[\w./-]+\.md`?", cells[4]):
            errors.append(f'decision {cells[0]}: "By" is a file, not a decider: write who decided, then the file, '
                          'for example "user (recorded in docs/workbench/state.md)"')
        if not cells[3]:
            errors.append(f'decision {cells[0]}: "Why" is empty')
    for l in sec.get("Open questions", []):
        s = l.strip()
        if s and s.lower() != "none" and not re.match(r"^- \[[ x]\] \S", s):
            errors.append(f'open question is not a checkbox ("- [ ] ..."): {s[:60]}')
    for l in sec.get("Facts established without asking", []):
        s = l.strip()
        if s.startswith(("-", "*")) and "source:" not in s.lower() and s.lower().strip("-* ") != "none":
            errors.append(f"fact without a source: {s[:60]}")
    return out(errors, warnings, "The brief matches the template. Update the state file, then report.",
               {"decisions": len(body)})


def insert_in_section(lines, heading, new_lines):
    """Insert after the last non-empty line of the section; create the section at the end when missing."""
    start = next((i for i, l in enumerate(lines) if l.strip() == heading), None)
    if start is None:
        while lines and not lines[-1].strip():
            lines.pop()
        return lines + ["", heading, ""] + new_lines, True
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    last = start
    for i in range(start + 1, end):
        if lines[i].strip():
            last = i
    block = new_lines if last > start else [""] + new_lines
    return lines[:last + 1] + block + lines[last + 1:], False


def one_line(text):
    return " ".join(text.split())


def update_state(o):
    if not os.path.isfile(o.state):
        return out([f"no state file at {o.state}: do not create it; keep the decisions and open questions "
                    "in the brief only and say so in the report"], [], "")
    date = o.date or datetime.date.today().isoformat()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        print("--date must be YYYY-MM-DD", file=sys.stderr)
        return 2
    with open(o.state, encoding="utf-8") as f:
        original = f.read()
    lines = original.split("\n")
    trailing = original.endswith("\n")
    if trailing:
        lines = lines[:-1]
    before = [l for l in lines if l.strip()]
    errors, warnings, created = [], [], []
    for d in o.decision:
        if not re.search(r"\([^()]+\)\s*$", d.strip()):
            errors.append(f'decision does not end with who decided, in parentheses: "{d[:60]}" '
                          '(write "... (user)" or "... (core-clarify, assumed)")')
        if re.search(r"\b(parked|open question|not decided|undecided)\b", d, re.I):
            errors.append(f'a parked item is not a decision: pass it with --open instead: "{d[:60]}"')
    if errors:
        return out(errors, warnings, "")
    if o.decision:
        lines, made = insert_in_section(lines, "## Decisions", [f"- {date}: {one_line(d)}" for d in o.decision])
        created += ["## Decisions"] if made else []
    if o.open:
        new = [f"- [ ] {one_line(q)}" + ("" if q.rstrip().endswith(")") else " (raised by core-clarify)") for q in o.open]
        lines, made = insert_in_section(lines, "## Open questions", new)
        created += ["## Open questions"] if made else []
    if o.artifact:
        row = f"| {o.artifact} | core-clarify | draft | {date} |"
        hit = next((i for i, l in enumerate(lines) if l.startswith("|") and
                    l.strip("|").split("|")[0].strip() == o.artifact), None)
        if hit is not None:
            lines[hit] = row
        else:
            head = next((i for i, l in enumerate(lines) if l.strip() == "## Artifacts"), None)
            if head is None:
                warnings.append("no \"## Artifacts\" section: the brief was not registered")
            else:
                end = next((i for i in range(head + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
                last = max([i for i in range(head + 1, end) if lines[i].startswith("|")], default=None)
                if last is None:
                    lines[head + 1:head + 1] = ["", "| Artifact | Owner skill | Status | Updated |",
                                                "|----------|-------------|--------|---------|", row]
                else:
                    lines.insert(last + 1, row)
    kept = [l for l in lines if l.strip()]
    lost = [l for l in before if l not in kept and not (o.artifact and l.startswith("|") and o.artifact in l)]
    if lost:  # defensive: an append never removes a line
        return out([f"refusing to write: {len(lost)} existing line(s) would change"], warnings, "")
    with open(o.state, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return out([], warnings, "State updated; existing lines are unchanged. Report what was appended.",
               {"state": o.state, "date": date, "decisions_appended": len(o.decision),
                "open_questions_appended": len(o.open), "sections_created": created,
                "artifact_registered": bool(o.artifact) and not warnings})


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("round", "brief"):
        s = sub.add_parser(name)
        s.add_argument("--file", required=True, help='path of the text to check, or "-" for stdin')
    s = sub.add_parser("state")
    s.add_argument("--state", required=True)
    s.add_argument("--decision", action="append", default=[], help='"<what was decided> (<by>)"; repeatable')
    s.add_argument("--open", action="append", default=[], help="an open question; repeatable")
    s.add_argument("--artifact", help="path of the brief, registered as draft in the Artifacts table")
    s.add_argument("--date", help="YYYY-MM-DD; default: today")
    sub.add_parser("today")
    o = p.parse_args(argv)
    if o.cmd == "today":
        print(json.dumps({"ok": True, "date": datetime.date.today().isoformat()}))
        return 0
    if o.cmd == "state":
        return update_state(o)
    try:
        text = read(o.file)
    except OSError as e:
        print(f"cannot read {o.file}: {e}", file=sys.stderr)
        return 2
    return check_round(text) if o.cmd == "round" else check_brief(text)


if __name__ == "__main__":
    sys.exit(main())
