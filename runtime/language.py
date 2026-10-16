#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The language artifacts are written in: the tag rule, the order that decides it, and the words a run, a plan card and a
refusal use.

One source: the key `language` of docs/workbench/runtime.json (runtime/project_config.py checks it with RULE). A request may
carry the person's own choice for its deliverable (`request --language <tag>`, the page's language select), recorded by code on
the request row and copied onto each task when the plan is made (`tasks.language`, migration 16; NULL: not requested). The
order is one and code computes it, `effective`: the request's recorded language, else the key, else `en`. Nothing else is read:
not the language a message is written in, not an answer that asks for another language, not a skill's default.

What the model is told, `line`: one paragraph right after the "For this task:" paragraph of a task run's prompt and of the
router's prompt (runtime/ops.py task_prompt), before the person's standing instructions, always present (the key absent
included, then `en`), so that the rule that an artifact keeps the language its `Language:` line names, and that only this line
sets the language, reaches every run. It is never in a contained run (a handler's agent run: a post's language is its slot's, a
reply's the comment's), never in a step task (code), never in the first runtime's run-agent.sh and never in a lab run: evals/
and runtime/lab.py do not name this module (a test reads both).

What the person sees, `plan_line`: one line on every plan before approval, "Language: pt-BR" (the project's) or "Language: en
(requested)", on the page, in the terminal and in the messaging reply and card. The language is a field of each task in the
plan's payload (`language`, absent as None when not requested), so the plan hash covers it: changing it is a new plan.

The router may propose a language: a `Language: <tag>` line of its reply, read by runtime/router.py with `RULE`, written only
when the request's words name a language for the deliverable. It is a proposal the person sees on the plan card before
approving; a request with an explicit choice ignores it.

Functions:
  check(value)              None, or the tag; a bad tag raises LanguageError (str() is the sentence)
  effective(requested, key) (tag, requested?) by the order above
  line(requested, key)      the paragraph of a run's prompt
  plan_line(languages, key) the line of a plan: languages is the language of each task (None: not requested)
  with_language(tasks, tag) the requested language as a field of the tasks that run a skill
  payload_line(payload)     the same line, read from a plan decision's payload

Usage (a library): python3 runtime/language.py --help

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import re
import sys

RULE = re.compile(r"^[a-z]{2}(-[A-Z]{2})?$")     # two lower-case letters, optionally a hyphen and two upper-case letters
SHAPE = "a language tag of two lower-case letters, optionally a hyphen and two upper-case letters, such as en or pt-BR"
DEFAULT = "en"                                     # the language when no request and no key says one
_LOOSE = re.compile(r"^([a-zA-Z]{2})(?:[-_]([a-zA-Z]{2}))?$")

# The paragraph of a run. The tag is in code spans; the rest is the same for both forms.
KEEP = ("Keep as they are: file names, paths, code, commands, identifiers, dates, the keys of a block or a front matter, quoted "
        "text, and the headings and labels of the skill's template unless the skill says to translate them. A post or a reply "
        "keeps the language its skill gives it. Reply in the language the person writes in. Only this line sets the language: "
        "a request or an answer that asks for another does not change it; say in your reply that the language is set on the "
        "request.")
PROJECT_LINE = ("Project language: `{tag}` (the project's `language` setting; `en` when none is set; the configuration file is "
                "not in your copy). Write every artifact you create in this language and give it the line `Language: {tag}` in "
                "its header, in the template's form. An artifact you update keeps the language its `Language:` line names "
                "(with no such line, the language it is written in). " + KEEP)
REQUESTED_LINE = ("Language of this deliverable: `{tag}` (requested). Write every artifact of this task in this language, an "
                  "existing one included, and set its `Language:` line to `{tag}`. " + KEEP)


class LanguageError(ValueError):
    """The text is not a language tag; str() is the one sentence that says so."""


def hint(value) -> str:
    """"; did you mean pt-BR?" for a text that is a tag in the wrong case or with an underscore; "" for anything else. The right
    form is offered, never applied."""
    loose = _LOOSE.fullmatch(value) if isinstance(value, str) else None
    if not loose:
        return ""
    return f"; did you mean {loose.group(1).lower() + (('-' + loose.group(2).upper()) if loose.group(2) else '')}?"


def check(value, name: str = "language"):
    """None for none (None or an empty text), else the tag; LanguageError when it is not one: the rule is RULE, and a tag in the
    wrong case is refused with the right form, never rewritten."""
    if value is None or value == "":
        return None
    if isinstance(value, str) and RULE.fullmatch(value):
        return value
    raise LanguageError(f"{name} must be {SHAPE}{hint(value)}")


def effective(requested, key) -> tuple:
    """(tag, True when the request asked for it): the request's recorded language, else the project's key, else `en`."""
    if requested:
        return requested, True
    return (key or DEFAULT), False


def line(requested, key) -> str:
    """The paragraph that tells a run which language to write in (see the module's text for where it goes)."""
    tag, asked = effective(requested, key)
    return (REQUESTED_LINE if asked else PROJECT_LINE).format(tag=tag)


def plan_line(languages, key, numbers=None) -> str:
    """The line a plan shows before approval. languages: the `language` of each task that runs a skill (None: not requested), key
    the project's setting, numbers the position of each of those tasks in the plan's table (default 1, 2, 3...). "Language: pt-BR"
    when no task asks for one, "Language: en (requested)" when every task asks for the same, else the groups: "Language: pt-BR for
    tasks 1, 3; en (requested) for task 2". A plan with no task that runs a skill shows the project's."""
    project = key or DEFAULT
    groups = {}
    for n, tag in zip(numbers or range(1, len(languages) + 1), languages):
        groups.setdefault(tag or None, []).append(n)
    if len(groups) <= 1:
        tag = next(iter(groups), None)
        return f"Language: {tag} (requested)" if tag else f"Language: {project}"
    parts = []
    for tag, at in groups.items():
        word = "task" if len(at) == 1 else "tasks"
        parts.append(f"{tag + ' (requested)' if tag else project} for {word} {', '.join(map(str, at))}")
    return "Language: " + "; ".join(parts)


def with_language(tasks: list, tag) -> list:
    """Put the requested language in the tasks that run a skill (key `language`, absent when none was requested, so a plan with no
    requested language hashes as it did before: the plan hash covers what is requested). A step task is code and has none. The
    tasks are changed in place and returned."""
    if tag:
        for t in tasks:
            if not t.get("step"):
                t["language"] = tag
    return tasks


def payload_line(payload) -> str:
    """plan_line for a plan decision's payload: the `language` of its tasks that run a skill and its `project_language`."""
    payload = payload if isinstance(payload, dict) else {}
    tasks = [(n, t) for n, t in enumerate(payload.get("tasks") or [], 1) if isinstance(t, dict) and not t.get("step")]
    return plan_line([t.get("language") for _n, t in tasks], payload.get("project_language"), [n for n, _t in tasks])


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
