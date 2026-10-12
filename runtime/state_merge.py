#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The one module that decides what a run may change in the project's state file (docs/workbench/state.md),
limit L10 of the platform plan. No other module writes the state file.

The form of the file is contracts/state.md: a head (the lines before the first "## "), then the sections
"## Autonomy", "## Artifacts" (a table: Artifact, Owner skill, Status, Updated), "## Decisions" (lines
"- <date>: <text>. (<who>)"), "## Approvals" (a table) and "## Open questions" (lines "- [ ] <text>").

Of the state file a run left, the merge accepts three things, line by line, on top of what the project has now:
  - a row of ## Artifacts owned by the skill that ran, with the status `draft`, whose row the project did not
    change while the run was in progress;
  - a new line of ## Decisions attributed to the skill that ran (its last parenthesis starts with the skill's
    name and no item of it holds the word "user");
  - a new open question of ## Open questions, read in any list form ("- ...", "* ...", "1. ...", with or
    without "[ ]"; an OPEN-<n> mark stays part of its text) and written in the form of contracts/state.md,
    "- [ ] <text>", unless it is attributed to the person or to another skill. A question the project has is
    never closed, reworded or removed by a run, and each of those is refused with its own reason.
Everything else stays as the project has it, and each line refused is reported with its reason. Only code
writes what is the person's: an answer (with_answer()), "approved", the autonomy mode, the approval rows
(write_generated(), a copy of the store's approvals table).

Usage (a library): python3 runtime/state_merge.py --help

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import difflib
import re
import sys

ARTIFACTS = "Artifacts"
DECISIONS = "Decisions"
QUESTIONS = "Open questions"
OPEN_QUESTION = "- [ ]"
ANSWER_MAX = 2000
CUT = " [cut: the whole answer is in the runtime's records]"
WHITESPACE = re.compile(r"\s+")
SEPARATOR = re.compile(r"^\|?\s*:?-{3,}")
LAST_PARENTHESIS = re.compile(r"\(([^()]*)\)\s*\.?\s*$")
WORD_USER = re.compile(r"\buser\b", re.I)
PROTECTED = {"Autonomy": "only code writes the autonomy mode", "Approvals": "only code writes an approval row"}
# A list item of ## Open questions as a run may write it: "- ", "* ", "+ ", "1. " or "1) ", then the text, with
# or without the checkbox of contracts/state.md ("[ ]", or "[x]" when closed). The merge writes "- [ ] <text>".
LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.*)$")
CHECKBOX = re.compile(r"^\[([ xX])\]\s*(.*)$")
# Who raised an open question: its last parenthesis, as in the template of contracts/state.md ("(raised by
# flow-fix-bug, phase 9, pull request)"). The person, or a skill named by the area prefixes of AGENTS.md.
RAISED_BY = re.compile(r"^raised\s+by\s+", re.I)
THE_USER = re.compile(r"^(?:(?:raised|asked|added|decided|approved|confirmed)\s+by\s+)?(?:the\s+)?user$", re.I)
SKILL_PREFIXES = ("biz", "product", "brand", "design", "eng", "ops", "mkt", "ai", "core", "asst", "flow")
SKILL_NAME = re.compile(r"^(?:%s)(?:-[a-z0-9]+)+$" % "|".join(SKILL_PREFIXES))


class Conflict(Exception):
    """The run's state file cannot be brought back; the message says why. Nothing was written."""


def parse(text: str) -> dict:
    """{"head": [lines], "sections": [[title, [lines]]]} in the file's order; a title is the text after "## "."""
    head, sections = [], []
    for line in (text or "").splitlines():
        if line.startswith("## "):
            sections.append([line[3:].strip(), []])
        elif sections:
            sections[-1][1].append(line)
        else:
            head.append(line)
    return {"head": head, "sections": sections}


def _section(parsed: dict, title: str):
    for name, lines in parsed["sections"]:
        if name == title:
            return lines
    return None


def _cells(line: str):
    """The cells of a table row, or None when the line is not a row (or is the separator)."""
    stripped = line.strip()
    if not stripped.startswith("|") or SEPARATOR.match(stripped):
        return None
    return [cell.strip() for cell in stripped.strip("|").split("|")]


def _rows(lines) -> dict:
    """{Artifact cell: line} of the rows of an ## Artifacts table, the header row left out."""
    out = {}
    for line in lines or []:
        cells = _cells(line)
        if cells and cells[0] and cells[0] != "Artifact":
            out.setdefault(cells[0], line)
    return out


def _render(parsed: dict) -> str:
    lines = list(parsed["head"])
    for title, body in parsed["sections"]:
        lines.append("## " + title)
        lines.extend(body)
    return "\n".join(lines).rstrip("\n") + "\n"


def _append(lines: list, line: str) -> None:
    """Add a line after the last non-blank line of a section, keeping the blank lines that end it."""
    at = len(lines)
    while at > 0 and not lines[at - 1].strip():
        at -= 1
    lines.insert(at, line)


def _attributed_to(line: str, skill: str):
    """None when the decision line is attributed to the skill that ran; otherwise the reason it is refused."""
    found = LAST_PARENTHESIS.search(line)
    items = [item.strip() for item in found.group(1).split(",")] if found else []
    if any(WORD_USER.search(item) for item in items):
        return "a decision of the person is written by code"
    if not items or items[0] != skill:
        who = ", ".join(items) if items else "nobody"
        return f"a decision attributed to {who}, not to the skill that ran"
    return None


def merge_report(base, current, returned, skill: str) -> dict:
    """{"text", "accepted": [{"section", "line"}], "rejected": [{"section", "line", "reason"}]}: the project's
    state file after a run of `skill`.

    base      the state file's text as the run was given it, or None when the project had none
    current   the project's state file's text now, or None when it has none
    returned  the text the run left
    Raises Conflict when the run's text cannot be read (empty, or no "## Artifacts") or the project has no
    state file."""
    if not isinstance(returned, str) or not returned.strip() or "## Artifacts" not in returned.splitlines():
        raise Conflict("the run left a state file that cannot be read: nothing was merged")
    if current is None:
        raise Conflict("the project has no state file: core-project-init writes it")
    old, now, new = parse(base or ""), parse(current), parse(returned)
    accepted, rejected = [], []

    def refuse(section: str, line: str, reason: str) -> None:
        rejected.append({"section": section, "line": line, "reason": reason})

    # Head, Autonomy, Approvals and every other section: as the project has them.
    for line in new["head"]:
        if line not in old["head"]:
            refuse("head", line, "a run does not change this part of the state file")
    for title, lines in new["sections"]:
        if title in (ARTIFACTS, DECISIONS, QUESTIONS):
            continue
        before = _section(old, title) or []
        for line in lines:
            if line not in before:
                refuse(title, line, PROTECTED.get(title, "a run does not change this part of the state file"))
    # Artifacts: a draft row of the skill that ran, on a row the project did not change meanwhile.
    rows_before, rows_now = _rows(_section(old, ARTIFACTS)), _rows(_section(now, ARTIFACTS))
    target = _section(now, ARTIFACTS)
    for artifact, line in _rows(_section(new, ARTIFACTS)).items():
        if rows_before.get(artifact) == line:
            continue
        cells = _cells(line)
        if len(cells) < 3 or cells[1] != skill:
            refuse(ARTIFACTS, line, "the row belongs to another skill")
        elif cells[2] != "draft":
            refuse(ARTIFACTS, line, "only the person approves: a run may set draft only")
        elif rows_now.get(artifact) != rows_before.get(artifact):
            refuse(ARTIFACTS, line, "changed at the origin since the copy was made")
        elif target is None:
            refuse(ARTIFACTS, line, "the project's state file has no such section")
        else:
            if artifact in rows_now:
                target[target.index(rows_now[artifact])] = line
            else:
                last = max((i for i, l in enumerate(target) if _cells(l) is not None), default=None)
                if last is None:
                    _append(target, line)
                else:
                    target.insert(last + 1, line)
            rows_now[artifact] = line
            accepted.append({"section": ARTIFACTS, "line": line})
    # Decisions: new lines attributed to the skill that ran.
    before, target = _section(old, DECISIONS) or [], _section(now, DECISIONS)
    for line in _section(new, DECISIONS) or []:
        if not line.strip() or line in before:
            continue
        reason = _attributed_to(line, skill)
        if reason:
            refuse(DECISIONS, line, reason)
        elif target is None:
            refuse(DECISIONS, line, "the project's state file has no such section")
        else:
            if line not in target:
                _append(target, line)
            accepted.append({"section": DECISIONS, "line": line})
    for line in before:
        if line.strip() and line not in (_section(new, DECISIONS) or []):
            refuse(DECISIONS, line, "a run may add a decision of its own, never change or remove one")
    # Open questions: read tolerantly, written strictly (WP-2.12). A new list item in any form is added as
    # "- [ ] <text>"; none the project has is closed, reworded or removed.
    target = _section(now, QUESTIONS)
    for kind, line in _question_changes(_section(old, QUESTIONS) or [], _section(new, QUESTIONS) or []):
        if kind != "new":
            refuse(QUESTIONS, line, kind)
            continue
        item = _question(line)
        reason = _question_refused(item, skill)
        if reason:
            refuse(QUESTIONS, line, reason)
        elif target is None:
            refuse(QUESTIONS, line, "the project's state file has no such section")
        else:
            written = f"{OPEN_QUESTION} {item[0]}"
            if item[0] not in {q[0] for q in map(_question, target) if q}:
                _append(target, written)
            accepted.append({"section": QUESTIONS, "line": written})
    return {"text": _render(now), "accepted": accepted, "rejected": rejected}


def _question(line: str):
    """(text, checked) of a list item of ## Open questions ("- ", "* ", "+ ", "1. " or "1) ", with or without a
    checkbox), or None when the line is not a list item."""
    found = LIST_ITEM.match(line)
    if not found:
        return None
    body = found.group(1).strip()
    box = CHECKBOX.match(body)
    if box:
        return box.group(2).strip(), box.group(1) != " "
    return body, False


def _question_refused(item, skill: str):
    """None when a new line of ## Open questions may be added; otherwise the reason it is refused."""
    if item is None or not item[0]:
        return "an open question is a list item with a text"
    if item[1]:
        return "a run adds an open question unchecked: a checked one is closed"
    found = LAST_PARENTHESIS.search(item[0])
    items = [part.strip() for part in found.group(1).split(",")] if found else []
    if any(THE_USER.match(part) for part in items):
        return "an open question of the person is written by code"
    who = RAISED_BY.sub("", items[0]).strip() if items else ""
    if SKILL_NAME.match(who) and who != skill:
        return f"an open question attributed to {who}, not to the skill that ran"
    return None


def _question_changes(before: list, returned: list) -> list:
    """[(kind, line)] of what a run did to ## Open questions, its lines compared with the base's as sequences:
    kind "new" for a line it added (the returned line), or the reason of a refusal for a question of the project
    it closed, reworded (the returned line) or removed (the base line). A question moved, or only rewritten in
    another list form, is no change."""
    old = [line for line in before if line.strip()]
    new = [line for line in returned if line.strip()]
    text_of = lambda line: (_question(line) or (line.strip(), False))  # noqa: E731
    old_texts, new_texts = {text_of(l)[0] for l in old}, {text_of(l)[0] for l in new}
    still_open = {text_of(l)[0] for l in old if not text_of(l)[1]}
    out = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        if op == "equal":
            continue
        gone, came = old[i1:i2], new[j1:j2]
        paired = min(len(gone), len(came)) if op == "replace" else 0
        for b, r in zip(gone[:paired], came[:paired]):
            (bt, _), (rt, _) = text_of(b), text_of(r)
            if rt in old_texts:  # moved, rewritten in another form, or closed (below)
                if bt not in new_texts:
                    out.append(("a run may not remove an open question the project has", b))
            elif bt in new_texts:  # the base line moved elsewhere: this one is new
                out.append(("new", r))
            else:
                out.append(("a run may not reword an open question the project has", r))
        for r in came[paired:]:
            if text_of(r)[0] not in old_texts:
                out.append(("new", r))
        for b in gone[paired:]:
            if text_of(b)[0] not in new_texts:
                out.append(("a run may not remove an open question the project has", b))
    for r in new:
        text, checked = text_of(r)
        if checked and text in still_open:
            out.append(("a run may not close an open question the project has", r))
    return out


def merge(base, current, returned: str, skill: str) -> str:
    """merge_report(...)["text"]. Raises Conflict as merge_report() says."""
    return merge_report(base, current, returned, skill)["text"]


def with_answer(text: str, *, date: str, skill: str, pending_id: int, answer: str) -> str:
    """The state file's text with the person's answer added as the last line of ## Decisions. Code calls it; no
    run can produce its effect (merge_report() refuses a decision that names the user)."""
    parsed = parse(text)
    target = _section(parsed, DECISIONS)
    if target is None:
        raise Conflict("the state file has no ## Decisions section: the answer was not written into it")
    said = WHITESPACE.sub(" ", answer or "").strip()
    if len(said) > ANSWER_MAX:
        said = said[:ANSWER_MAX] + CUT
    _append(target, f"- {date}: Answer to {skill} (pending decision {pending_id}): {said} (user)")
    return _render(parsed)


def with_go_ahead(text: str, *, date: str, skill: str, task_id: int, waited: list) -> str:
    """The state file's text with the person's decision to go ahead on a task, as the last line of ## Decisions: what the
    task did not wait for (the reasons of the derived waits, runtime/plan.py). Code calls it; no run can produce its
    effect (merge_report() refuses a decision that names the user)."""
    parsed = parse(text)
    target = _section(parsed, DECISIONS)
    if target is None:
        raise Conflict("the state file has no ## Decisions section: the go-ahead was not written into it")
    said = "; ".join(WHITESPACE.sub(" ", w).strip() for w in waited) or "no wait held it when it was approved"
    _append(target, f"- {date}: Go ahead on {skill} (task {task_id}) without waiting for: {said} (user)")
    return _render(parsed)


APPROVALS = "Approvals"
AUTONOMY = "Autonomy"
RUNTIME_MARK = re.compile(r"\(runtime #\d+\)$")


def write_standing(state_text: str, rows, owned) -> tuple:
    """(text, written, superseded): the state file's ## Approvals table with its standing rows generated from the
    store. rows are the cells of the rows to write (Scope, What, Payload hash, Approved, Expires, Status), the What of
    each ending " (runtime #<id>)"; owned is every "policy:<sha256>" third cell of a standing approval of the store.
    As write_generated() tells a generated row, a row whose third cell is owned is code's: it is removed, and the rows
    are written after the table's last row. A removed row without the runtime mark was written by a session and is
    superseded by the store's row for the same file: superseded counts them. Every other row stays. Raises Conflict
    when the file has no ## Approvals section."""
    # T23: workaround 5, the standing approval copied into the state file until the policy gate reads the runtime's record
    parsed = parse(state_text)
    target = _section(parsed, APPROVALS)
    if target is None:
        raise Conflict("the state file has no ## Approvals section: the standing rows were not written into it")
    owned = set(owned)
    superseded, kept = 0, []
    for line in target:
        cells = _cells(line)
        if cells and len(cells) >= 3 and cells[2] in owned:
            if not RUNTIME_MARK.search(cells[1]):
                superseded += 1
            continue
        kept.append(line)
    target[:] = kept
    for cells in rows:
        clean = [" ".join(str(cell).replace("|", "/").split()) or "-" for cell in cells]
        _append(target, "| " + " | ".join(clean) + " |")
    return _render(parsed), len(rows), superseded
CHECKPOINTS_LINE = re.compile(r"^(\s*-\s*Checkpoints:[ \t]*)([^\s#]*)(.*)$")


def with_checkpoints(state_text: str, value: str) -> tuple:
    """(text, written): the state file's text with the value of the "- Checkpoints:" line of ## Autonomy replaced by
    value (only the word between "Checkpoints: " and the comment changes), and whether a line was found. A file
    without ## Autonomy or without the line is returned as it is. Only code calls it, with the most careful
    checkpoints of the enabled area agents (runtime/autonomy.py): the line is a generated copy of the configuration."""
    parsed = parse(state_text)
    target = _section(parsed, AUTONOMY)
    if target is None:
        return state_text, False
    for i, line in enumerate(target):
        found = CHECKPOINTS_LINE.match(line)
        if found:
            target[i] = found.group(1) + value + found.group(3)
            return _render(parsed), True
    return state_text, False


def write_generated(state_text: str, rows) -> str:
    """The state file's text with generated approval rows added to, or replaced in, its ## Approvals table, and
    nothing else touched. rows is a list of the cells of runtime/effects.py approval_row() (Scope, What, Payload
    hash, Approved, Expires, Status); a row whose Payload hash is already in the table replaces that row, any other is
    added after the table's last row. Only code calls it, with the runtime's record of the approval (the approvals
    table of the store, limit L17); no run can write an approval row (merge_report() refuses it). Raises Conflict
    when the file has no ## Approvals section."""
    # T23: the approvals are copied into the state file until the policy gate reads the runtime's record
    parsed = parse(state_text)
    target = _section(parsed, APPROVALS)
    if target is None:
        raise Conflict("the state file has no ## Approvals section: the approval row was not written into it")
    for cells in rows:
        clean = [" ".join(str(cell).replace("|", "/").split()) or "-" for cell in cells]
        line = "| " + " | ".join(clean) + " |"
        found = next((i for i, existing in enumerate(target)
                      if (_cells(existing) or [None, None, None])[2:3] == [clean[2]]), None)
        if found is None:
            _append(target, line)
        else:
            target[found] = line
    return _render(parsed)

if __name__ == "__main__":
    print(__doc__.strip())
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
