#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The step kind `tool-check`: tell the person when the reference fetcher's tool has a newer release (package V7c, the pin routine).

Two steps:

  check    asks the `tool_check` service (runtime/ops_step_seams.py, class fetcher:video, the one verb `pin-latest`) for the tool's latest release
           metadata and compares it with the pin in force. That is one read of metadata: it downloads nothing, writes no pin and builds nothing, and
           the service has no way to do any of them (it takes no verb). When the pin is current the step marks `review` done itself and the task ends
           `done` with no question: the engine skips a step whose state says `done` (runtime/steps.py `run`), and a test runs the real engine over
           this kind to hold that coupling.
  review   a stop of the engine (`review`): a question card that names both versions and the two commands the person types in the terminal, in this
           order: `pin-raise --version <latest> --confirmed`, which records the person's own pin, and `build --confirmed`, which downloads the tool and
           the packages of the image. The card offers to run nothing; the only answer it takes is the engine's own, `continue` (seen) or `stop`.

A raise is a typed yes each time (decision 15 and package V7, section 6.4): the tool is a large third-party program that runs with network and parses
hostile pages, and an unattended raise would trust a release nobody looked at. A routine over `flows/fetch-tool-check.json` (weekly is recommended)
only tells. The kind is `unattended` (a routine may start it) and `networked` (the check reaches a host through the provider), so a plan or a routine
that holds it is approved and changed only in the terminal or on the page (limits L33 and L36).

Arguments: none (`{}`). The result is closed words: two versions of the form `2026.10.26`, whether the latest is newer, a date.

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import steps  # noqa: E402

VERSION = re.compile(r"[0-9]{4}\.[0-9]{2}\.[0-9]{2}(\.[0-9]{1,8})?")
DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
SERVICE_CODES = {"not_configured": "not_configured", "check_failed": "check_failed"}
NEXT = {"not_configured": "build the fetch tool first: providers/fetcher/README.md gives the command, run by you",
        "check_failed": "run `python3 providers/fetcher/ytdlp.py pin-latest` in the terminal to read the reason"}
RAISE_COMMAND = "python3 providers/fetcher/ytdlp.py pin-raise --version %s --confirmed"
BUILD_COMMAND = "python3 providers/fetcher/ytdlp.py build --confirmed"
SKIPPED = {"skipped": True}


def check(args) -> dict:
    """The arguments of a tool-check: none."""
    if args not in (None, {}):
        raise steps.StepFailure("bad_args", "args")
    return {}


def _check(ctx: steps.Context, state: dict) -> dict:
    service = ctx.services.get("tool_check")
    if service is None:
        raise steps.StepFailure("not_configured", "tool_check", "", NEXT["not_configured"])
    try:
        answer = service.latest()
    except steps.StepFailure:
        raise
    except Exception as e:      # a service error carries a `code`; anything else is a failed check
        code = SERVICE_CODES.get(getattr(e, "code", ""), "check_failed")
        raise steps.StepFailure(code, "tool_check", "", NEXT[code]) from None
    current, latest, newer = answer.get("current"), answer.get("latest"), answer.get("newer")
    if not isinstance(current, str) or not VERSION.fullmatch(current) or not isinstance(latest, str) or not VERSION.fullmatch(latest) \
            or not isinstance(newer, bool):
        raise steps.StepFailure("check_failed", "tool_check", "", NEXT["check_failed"])
    published = answer.get("published_at")
    day = published[:10] if isinstance(published, str) and DATE.fullmatch(published[:10]) else None
    if not newer:
        # Nothing to tell: the stop is passed here, so the engine goes on past it and the task ends done, with no question.
        state["steps"]["review"] = {"status": "done", "at": ctx.now(), "result": dict(SKIPPED)}
    return {"current": current, "latest": latest, "newer": newer, "published": day}


def _review(ctx: steps.Context, state: dict) -> dict:
    found = state["steps"]["check"]["result"]
    published = " (published %s)" % found["published"] if found.get("published") else ""
    body = ("A newer release of the reference fetch tool exists: %s%s. The pin in force is %s.\n\n"
            "Nothing was downloaded, pinned or built. To raise it, type these two commands yourself in the terminal, in this order:\n"
            "1. `%s` records your own pin from the release's metadata (no download).\n"
            "2. `%s` downloads the tool and the packages of the image and builds it.\n\n"
            "Until then the old one stays; a fetch that fails may mean it is out of date. This question runs nothing."
            % (found["latest"], published, found["current"], RAISE_COMMAND % found["latest"], BUILD_COMMAND))
    return {"title": "A newer fetch tool release exists: %s" % found["latest"], "body": body}


KIND = steps.register(steps.Kind(
    name="tool-check",
    order=("check", "review"),
    executors={"check": _check},
    stops=("review",),
    decisions={"review": _review},
    footprint=lambda args: (),
    check=check,
    unattended=True,
    networked=True,
))


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
