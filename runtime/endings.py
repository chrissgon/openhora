#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""How a run ended, for a run that did not fail: the classifier of endings.

The failures (a timeout, a refusal by the provider, a refused credential, a failure of the adapter, an early
end) are decided before this, by the lab's own functions (runtime/lab.py). This module reads a run that
completed and says which of the closed list it is:

  done                   the skill delivered: a declared output was written, and nothing is asked
  question               the skill stopped to ask and wrote nothing
  draft_with_questions   the skill wrote a declared output and still asks (an OPEN-<n> in it, or a closing question)
  gate                   the skill stopped at its confirmation gate          (recognised from stage 2 on)
  blocked                the skill stopped on a missing input                 (recognised from stage 2 on)
  unclassified           none of the rules below holds

It never guesses. A reply no rule recognises is `unclassified` and reaches the person whole. Without facts
(classify(..., facts=None)) it applies the first classifier's six rules (stage 1 of the platform plan). With the
facts of the skill that ran (manifest.ending_facts(), plus the run's own `outputs_present`), it recognises every
ending of the closed list, each from the run's facts, what the skill declares, or a sentence that comes from the
skills' own text (the comment beside each constant names the file). It is tested against the corpus of archived
lab runs (runtime/tests/corpus/endings.jsonl, runtime/tests/corpus/labels.json).

Usage:
  python3 runtime/endings.py --help
  python3 runtime/endings.py --corpus runtime/tests/corpus/endings.jsonl
      classify every line of a corpus with the facts of the line's skill (manifest.ending_facts) and print one
      JSON object {"lines", "by_ending", "stopped": {ending: n}, "changed": {ending: n}, "unclassified_ids"}

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import path_rule  # noqa: E402  (the same folder, as the other modules import each other)
import skill_meta  # noqa: E402

ENDINGS = ("done", "question", "draft_with_questions", "gate", "blocked", "unclassified")
TMP_PREFIX = "<tmp>/"  # a gate's payload file under the run's temporary folder (runtime/lab.py, tmp_in_run)
# The opening of the reply the skills' asking template gives ("Nothing was searched or written yet: ...",
# "Nothing was written yet: ...").
ASK_OPENING = re.compile(r"^\W*Nothing was (?:searched or )?written yet\b", re.I)
RECOMMENDED = re.compile(r"\bRecommended:", re.I)
OPEN_MARK = re.compile(r"\bOPEN-\d+\b")
# The stop on a missing input: stop rule 1 of templates/capability.SKILL.md ("stop and tell the user that
# `<area>-<skill>` writes it and to run it first"), and the form "run `<skill>` first" of its Next line. A form a
# single skill writes otherwise ("writes them", "writes that section") is not here: it is the skill's own
# reply_phrases["missing_input"] in its runtime manifest, and reaches the classifier as facts["reply_phrases"].
MISSING_INPUT = re.compile(r"\bwrites it\b|\brun (?:it|`[a-z0-9-]+`) first\b", re.I)
# A skill that is not built is cited with the mark `(planned)`: the writing standard of AGENTS.md.
PLANNED = "(planned)"
# The asking reply of templates/capability.SKILL.md gives each question a "Recommended:" answer (RECOMMENDED).
# The question of a confirmation gate, asked as the reply's last line: "<question>? (yes/no)", the form of
# "Proceed? (yes/no)" of templates/capability.SKILL.md; a gate question in another form is the skill's own
# reply_phrases["gate_questions"]. And a question closed by its recommended answer, as the asking reply of
# templates/capability.SKILL.md writes each one ("<question>? Recommended: <answer>"). Read only with facts: the
# first classifier is unchanged.
YES_NO = re.compile(r"\?\s*\(yes/no\)$", re.I)
LEADING = "*_#>`- \t"
# A reply that closes with a list of questions (WP-3.20): its last paragraph is a numbered or bulleted list whose
# items each ask, or a list under a line that says questions follow. An item asks when it ends with a question mark
# or holds "Recommended:", the form of the asking reply of templates/capability.SKILL.md ("1. <question>
# Recommended: <answer>") and of the "Open questions" of the skills' templates; the router's items are "Q<n>:"
# (skills/core-orchestrator/SKILL.md). The lines that say questions follow, the canonical forms: "Open questions:"
# (templates/flow.SKILL.md), "Questions:" and "Questions for you:", as a heading, a bold line or a line that ends
# with a colon. A line a single skill writes otherwise ("Questions (<a note>):", "### Decisions needed") is that
# skill's own reply_phrases["question_intros"] in its runtime manifest. Read only with facts: the first classifier is
# unchanged.
LIST_ITEM = re.compile(r"^(\s*)(?:\d+[.)]|[-*+]|Q\d+:)\s+(.*)$")
QUESTIONS_FOLLOW = re.compile(r"^(?:open questions|questions)(?: for you)?:?$", re.I)
PHRASE_KEYS = ("missing_input", "question_intros", "gate_questions")


def _plain(text: str) -> str:
    """A line without its heading marks, emphasis and trailing colon, in lower case: what a phrase is compared as."""
    return text.strip().lstrip("#*_ ").rstrip("*_ ").rstrip(":").rstrip("*_ ").lower()


def _phrases(facts, key: str) -> list:
    """The phrases of one kind the skill's manifest gives (facts["reply_phrases"][key]); none when absent."""
    return [p for p in (((facts or {}).get("reply_phrases") or {}).get(key) or []) if isinstance(p, str) and p.strip()]


def _questions_follow(line: str, intros=()) -> bool:
    """A line that says questions follow: one of QUESTIONS_FOLLOW's forms, or one that starts like a phrase of the
    skill's `question_intros`, as a heading, a bold line or a line that ends with a colon."""
    raw = line.strip()
    text = raw.lstrip("#*_ ").rstrip("*_ ")
    if not QUESTIONS_FOLLOW.match(text) and not any(_plain(text).startswith(_plain(p)) for p in intros):
        return False
    return raw.startswith("#") or text.endswith(":") or (raw.startswith("**") and raw.endswith("**"))


def _item_asks(own: list, under: list) -> bool:
    """An item asks when one of its own lines (its first, or a line that continues it) ends with a question mark,
    or it holds "Recommended:"; the items under it (its options, say) do not decide it."""
    return any(line.rstrip("*_` ").endswith("?") for line in own) or any(RECOMMENDED.search(t) for t in own + under)


def _closes_with_question_list(response: str, intros=()) -> bool:
    """The reply's last paragraph (lines up to a blank line) is a list of questions: every item at the list's own
    depth asks, or the paragraph opens with, or follows a paragraph that is only, a line that says questions follow.
    A line of the paragraph that is not an item continues the item above it; an item deeper than the first is
    under the item above it."""
    paragraphs = [p for p in re.split(r"\n[ \t]*\n", (response or "").strip()) if p.strip()]
    if not paragraphs:
        return False
    rows = [r for r in paragraphs[-1].splitlines() if r.strip()]
    intro = not LIST_ITEM.match(rows[0]) and _questions_follow(rows[0], intros)
    if intro:
        rows = rows[1:]
    elif len(paragraphs) > 1 and len(paragraphs[-2].strip().splitlines()) == 1:
        intro = _questions_follow(paragraphs[-2], intros)
    first = LIST_ITEM.match(rows[0]) if rows else None
    if not first:
        return False
    depth, items = len(first.group(1)), []  # [(own lines, lines under it)]
    for row in rows:
        m = LIST_ITEM.match(row)
        if m and len(m.group(1)) <= depth:
            items.append(([m.group(2)], []))
        elif m:
            items[-1][1].append(m.group(2))
        else:
            items[-1][0].append(row.strip())
    return intro or all(_item_asks(own, under) for own, under in items)


def _lines(text: str) -> list:
    return [line.strip() for line in (text or "").splitlines() if line.strip()]


def _asks(response: str, lines: list, openings, yes_no: bool = False, facts=None) -> bool:
    """The reply is an asking reply: it holds a question mark, and its first line starts with an asking opening
    (the skill's own, or the template's), or it holds "Recommended:", or its last line ends with a question mark.
    With yes_no (only with facts) a reply that closes with a list of questions asks, with or without a question
    mark. `facts` carries the skill's reply phrases."""
    intros = _phrases(facts, "question_intros")
    if not lines or ("?" not in (response or "") and not (yes_no and _closes_with_question_list(response, intros))):
        return False
    first = lines[0].lstrip(LEADING)
    return (any(o and first.lower().startswith(o.lower()) for o in openings) or bool(ASK_OPENING.search(lines[0]))
            or bool(RECOMMENDED.search(response)) or _last_asks(lines, yes_no, facts)
            or (yes_no and _closes_with_question_list(response, intros)))


def _last_asks(lines: list, yes_no: bool = False, facts=None) -> bool:
    """The reply's last line ends with a question mark. With yes_no (only with facts) also when it ends with
    "? (yes/no)", or ends with one of the skill's `gate_questions`, or holds a question mark followed by
    "Recommended:" (a question of the asking reply, written with its recommended answer, as the last line)."""
    if not lines:
        return False
    last = lines[-1].rstrip("*_` ")
    if last.endswith("?"):
        return True
    return yes_no and (bool(YES_NO.search(last)) or ("?" in last and bool(RECOMMENDED.search(last.split("?", 1)[1])))
                       or any(last.lower().endswith(p.strip().lower()) for p in _phrases(facts, "gate_questions")))


def _names_missing_input(lines: list, skill: str, skills, phrases=()) -> bool:
    """A line of the reply holds `writes it` or `run it first` (or one of the skill's own `missing_input` phrases),
    and the same line names another skill of the workbench or the mark (planned)."""
    others = [name for name in (skills or []) if name and name != skill]
    for line in lines:
        if not MISSING_INPUT.search(line) and not any(p.strip().lower() in line.lower() for p in phrases):
            continue
        if PLANNED in line or any(re.search(r"(?<![\w-])" + re.escape(name) + r"(?![\w-])", line) for name in others):
            return True
    return False


SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
MISSING_LINE_MAX = 400


def missing_input_line(response: str, facts) -> str:
    """The first line of the reply that names the missing input and the skill that writes it (the line
    _names_missing_input reads for the ending `blocked`), without its heading and emphasis marks, on one line and cut
    at a sentence end to at most MISSING_LINE_MAX characters; "" when no line does. It is the note of a blocked task,
    so that the person sees what unblocks it beside Retry."""
    skill, others = (facts or {}).get("skill") or "", (facts or {}).get("skills")
    for line in _lines(response):
        if _names_missing_input([line], skill, others, _phrases(facts, "missing_input")):
            text = " ".join(line.lstrip(LEADING).replace("**", "").split())
            if len(text) <= MISSING_LINE_MAX:
                return text
            kept = ""
            for sentence in SENTENCE_END.split(text):
                if len(kept) + len(sentence) + 1 > MISSING_LINE_MAX:
                    break
                kept = f"{kept} {sentence}".strip()
            return kept or text[:MISSING_LINE_MAX]
    return ""


def classify(response: str, changes: dict, outputs_written, outputs_missing, output_texts, *, facts=None) -> tuple:
    """(ending, why) of a completed run.

    response         the reply, whole
    changes          {"created", "modified", "deleted", "unchanged"}: what the run did to its copy
    outputs_written  the declared outputs of the skill among the files the run created or modified
    outputs_missing  the declared outputs without a placeholder that the copy does not hold after the run
    output_texts     the text of each path of outputs_written that is a text file, in the same order
    facts            None (the first classifier), or {"skill", "asking_openings", "fixed_output", "side_effects",
                     "gate_payload", "skills", "reply_phrases"} from manifest.ending_facts(), and optionally
                     "outputs_present": the declared outputs without a placeholder that the run's copy held,
                     unchanged, after the run; reply_phrases (absent means none) are the skill's own phrases
                     for a missing input, the line that says questions follow and the question of its gate

    Without facts, the first that holds:
    1. No file was created, modified or deleted, the reply holds a question mark, and either its first line is
       the asking template's opening, or it holds "Recommended:", or its last line ends with a question mark:
       `question`.
    2. No file changed and rule 1 does not hold: `unclassified`.
    3. No declared output was written: `unclassified`.
    4. A written output holds OPEN-<n>, or the reply's last line ends with a question mark:
       `draft_with_questions`.
    5. A declared output is missing: `unclassified`.
    6. Otherwise: `done`.

    With facts, the first that holds:
    1. No file changed; a line holds "writes it" or "run it first" and, on the same line, another skill of
       facts["skills"] or "(planned)"; and the reply does not hold "Recommended:": `blocked`.
    2. facts["gate_payload"] is set, a created or modified path matches it, and the reply's last line ends with a
       question mark: `gate`. A payload under "<tmp>/" (a file the skill writes in a folder it makes under the
       temporary folder) is matched by its last part against facts["gate_files"], the files found under the run's
       returned temporary folder.
    3. No file changed, or only the state file (path_rule.STATE) changed, and the reply asks (rule 1 above, with
       the skill's own asking openings too): `question`. A run that changed only the state file and asks
       nothing goes on to rules 6 and 7.
    4. No file changed; a declared output is already in the copy (facts["outputs_present"]); the reply does not
       open with an asking opening, does not hold "Recommended:", and its last line does not end with a question
       mark: `done` (nothing was left to write: the delivery is the document already there).
    5. No file changed: `unclassified`.
    6. No declared output was written, facts["fixed_output"] is false, and the reply's last line does not end
       with a question mark: `done` (the skill's work is the project's own files).
    7. No declared output was written: `unclassified`.
    8. A written output holds OPEN-<n>, or the reply's last line ends with a question mark:
       `draft_with_questions`.
    9. A declared output without a placeholder is missing: `unclassified`.
    10. Otherwise: `done`.

    With facts, "the reply's last line ends with a question mark" also holds when the reply closes with a list of
    questions (_closes_with_question_list, WP-3.20): its last paragraph is a numbered or bulleted list whose items
    each end with a question mark or hold "Recommended:", or a list under a line that says questions follow."""
    lines = _lines(response)
    last_asks = _last_asks(lines)
    changed = list(changes.get("created") or []) + list(changes.get("modified") or []) + list(changes.get("deleted") or [])
    if facts is None:
        if not changed:
            if _asks(response, lines, ()):
                return "question", "no file changed and the reply asks"
            return "unclassified", "no file changed and the reply is not recognised as a question"
        if not outputs_written:
            return "unclassified", "files changed, none of them a declared output of the skill"
        if any(OPEN_MARK.search(text or "") for text in output_texts) or last_asks:
            return "draft_with_questions", "a declared output was written and a question is open"
        if outputs_missing:
            return "unclassified", "a declared output was written and another is missing: " + ", ".join(outputs_missing)
        return "done", "every declared output is there and nothing is asked"

    openings = list(facts.get("asking_openings") or [])
    intros = _phrases(facts, "question_intros")
    last_asks = _last_asks(lines, yes_no=True, facts=facts) or _closes_with_question_list(response, intros)
    if not changed and _names_missing_input(lines, facts.get("skill") or "", facts.get("skills"),
                                            _phrases(facts, "missing_input")) \
            and not RECOMMENDED.search(response or ""):
        return "blocked", "no file changed and the reply names a missing input and the skill that writes it"
    payload = facts.get("gate_payload")
    if payload and last_asks:
        left = list(changes.get("created") or []) + list(changes.get("modified") or [])
        if payload.startswith(TMP_PREFIX):
            name = payload.rsplit("/", 1)[-1]
            seen = any(p.rsplit("/", 1)[-1] == name for p in facts.get("gate_files") or [])
        else:
            seen = any(skill_meta.matches([payload], p) for p in left)
        if seen:
            return "gate", "the run wrote the file of its confirmation gate and asks for approval"
    # For telling `question` from the other endings, a change limited to the state file counts as having written
    # nothing (WP-2.13): the skills write their open questions and decisions there when they stop to ask.
    state_only = bool(changed) and all(p == path_rule.STATE for p in changed)
    if (not changed or state_only) and _asks(response, lines, openings, yes_no=True, facts=facts):
        return "question", ("only the state file changed and the reply asks" if state_only
                            else "no file changed and the reply asks")
    if not changed:
        first = lines[0].lstrip(LEADING).lower() if lines else ""
        opens_asking = bool(lines) and (bool(ASK_OPENING.search(lines[0]))
                                        or any(o and first.startswith(o.lower()) for o in openings))
        if facts.get("outputs_present") and lines and not last_asks and not opens_asking \
                and not RECOMMENDED.search(response or ""):
            return "done", "no file changed, a declared output is already there, and the reply asks nothing"
        return "unclassified", "no file changed and the reply is not recognised as a question"
    if not outputs_written:
        if not facts.get("fixed_output") and not last_asks:
            return "done", "the skill declares no fixed output; files changed and nothing is asked"
        return "unclassified", "files changed, none of them a declared output of the skill"
    if any(OPEN_MARK.search(text or "") for text in output_texts) or last_asks:
        return "draft_with_questions", "a declared output was written and a question is open"
    if outputs_missing:
        return "unclassified", "a declared output was written and another is missing: " + ", ".join(outputs_missing)
    return "done", "every declared output is there and nothing is asked"


def corpus_counts(corpus: str, root: str = ROOT) -> dict:
    """Classify every line of a corpus file with the facts of the line's skill (manifest.ending_facts). A corpus
    line does not record what the run's copy held, so no line has `outputs_present`."""
    import manifest  # the same folder; imported here because manifest.py reads the packs only for this command
    facts_of, out = {}, {"lines": 0, "by_ending": {}, "stopped": {}, "changed": {}, "unclassified_ids": []}
    with open(corpus, encoding="ascii") as f:
        for raw in f:
            line = json.loads(raw)
            if line["skill"] not in facts_of:
                facts_of[line["skill"]] = manifest.ending_facts(root, line["skill"])
            ending = classify_line(line, facts_of[line["skill"]])[0]
            out["lines"] += 1
            out["by_ending"][ending] = out["by_ending"].get(ending, 0) + 1
            side = "stopped" if line["stopped"] else "changed"
            out[side][ending] = out[side].get(ending, 0) + 1
            if ending == "unclassified":
                out["unclassified_ids"].append(line["id"])
    for key in ("by_ending", "stopped", "changed"):
        out[key] = dict(sorted(out[key].items()))
    return out


def classify_line(line: dict, facts: dict) -> tuple:
    """(ending, why) of one corpus line, with the facts of its skill. The corpus keeps no output's text, so an
    OPEN-<n> inside a written output is not seen; a missing output is not known either."""
    changes = {"created": line["created"], "modified": line["modified"], "deleted": line["deleted"], "unchanged": []}
    return classify(line["response"], changes, line["outputs_written"], [], [], facts=facts)


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) == 2 and argv[0] == "--corpus":
        try:
            print(json.dumps(corpus_counts(argv[1])))
        except (OSError, ValueError, KeyError) as e:
            print(f"error: the corpus cannot be read: {e}", file=sys.stderr)
            return 1
        return 0
    print(__doc__.strip(), file=sys.stdout if argv in (["--help"], ["-h"]) else sys.stderr)
    return 0 if argv in (["--help"], ["-h"]) else 2


if __name__ == "__main__":
    sys.exit(main())
