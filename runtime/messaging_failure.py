#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Why a write to the person's accounts was not made, said to a phone in plain words (package LIVE-2).

A refusal of the preparation or of the write used to reach a messaging app as the engine's own line (`error: prepare: refused folder -- ...`): a step name, a closed code
and a sentence written for a terminal. A phone is told instead what failed and what to check, in the project's language, by the phrase keys of the family FAIL_; the
terminal, the page and the stored note keep the full English text. This module maps the closed codes of a step failure (`from_step`) and, for a write that failed after the
approval, the code and the words of the operations layer's error (`from_error`), to those keys. The mapping of an error by its words is best effort: the providers' own
sentences are free text, so a word list picks quota, size, name, network and authorization, and anything else is the plain "It was not done" (a test holds each).

  from_step(kind, account, code, field, folder, cfg)   the sentence for a failed preparation (account_start.start)
  from_error(error, cfg, word=None, account=None)      the sentence for a failed approval (the bridge)

No command, no path and no hash is ever in a sentence (limit L62). Standard library only. Runs on Python 3.9: python3 runtime/messaging_failure.py --help
"""
from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import phone_errors  # noqa: E402  (what an English sentence becomes on a phone that does not speak English)
import phrases  # noqa: E402  (the same folder: the sentences, in the project's language)

SERVICE_OF_KIND = {"file-write": "FILES", "mailbox-change": "MAIL", "send-email": "MAIL"}      # the step kinds whose service is Drive/OneDrive or Gmail/Outlook
SERVICE_OF_WORD = {"files": "FILES", "mailbox": "MAIL", "send": "MAIL", "send-own": "MAIL"}
PLACE_OF_WORD = {"calendar": "FAIL_LOOK_CALENDAR", "mailbox": "FAIL_LOOK_MAILBOX", "files": "FAIL_LOOK_FILES", "send": "FAIL_LOOK_SENT", "send-own": "FAIL_LOOK_SENT",
                 "publish": "FAIL_LOOK_POST"}      # where the person looks when the outcome of a write is unknown
QUOTA = re.compile(r"quota|insufficient ?storage|storage (limit|full)|no (space|room) left", re.I)
TOO_LARGE = re.compile(r"too (large|big)|size limit|payload too large|exceeds the (size|maximum)", re.I)
TAKEN = re.compile(r"already (exists|there|in)|name (is )?taken|conflict", re.I)
NETWORK = re.compile(r"time[ds]? ?out|network|connection|unreachable|did not answer|temporarily|try again|5\d\d\b", re.I)
AUTH = re.compile(r"not authori[sz]ed|authori[sz]e|unauthori[sz]ed|credential|token|not configured|not set up|\b40[13]\b", re.I)
# The words of an outcome that is not known: the effects' UNKNOWN_NEXT ("the outcome is unknown: look in ..."), the writer's "may or may not have been made", and a provider that
# exits with code 4 (the outcome is not known). An unknown outcome is never told as "nothing was done": the write may have landed.
UNKNOWN = re.compile(r"outcome is unknown|may or may not|whether .* (was|is) (written|made)|not known|exit(?:ed)?(?: with)?(?: status)?(?: code)? 4\b", re.I)


OUTLOOK_REMOVE = re.compile(r"removing an event from an Outlook calendar is not available")      # the writer's refusal of Q12, told by one sentence of its own


def _family(kind=None, word=None):
    if kind == "calendar-event" or word == "calendar":
        return "CALENDAR"
    return SERVICE_OF_KIND.get(kind) or SERVICE_OF_WORD.get(word)


def _service(family, account, cfg) -> str:
    if family in ("FILES", "MAIL") and account in ("google", "microsoft"):
        return phrases.text(f"FAIL_SERVICE_{family}_{account.upper()}", cfg)
    if family == "CALENDAR" and account in ("google", "microsoft"):
        return phrases.text("OUT_CAL_MICROSOFT" if account == "microsoft" else "OUT_CAL_GOOGLE", cfg)
    return phrases.text("FAIL_SERVICE_ANY", cfg)


def from_step(kind, account, code, field, folder, cfg, said=None) -> str:
    """The sentence for a preparation that stopped with this closed `code` and `field` (steps.StepFailure). `folder` is the name the project's accounts file gives the
    folder the person asked for (never a path); `said` is the step's own sentence for a code that is about the request itself. What failed and what to check; a code with
    no sentence of its own and no `said` is the plain "It was not done"."""
    service = _service(_family(kind), account, cfg)
    if code == "not_configured":
        return phrases.phone("FAIL_NOT_AUTHORIZED", cfg, service=service)
    if code in ("refused", "provider_failed") and field == "folder":
        hint = " " + phrases.text("FAIL_FOLDER_HINT", cfg) if account == "microsoft" else ""
        return phrases.text("FAIL_FOLDER", cfg, folder=folder or "default", service=service) + hint
    if code in ("refused", "provider_failed") and field in ("file", "source"):
        return phrases.text("FAIL_FILE", cfg, service=service)
    if code == "provider_failed":
        return phrases.text("FAIL_NETWORK", cfg, service=service)
    if code == "refused":
        return phrases.text("FAIL_REFUSED", cfg, service=service)
    if code == "gone":
        return phrases.text("FAIL_GONE", cfg)
    if code == "name_taken":
        return phrases.text("FAIL_NAME_TAKEN", cfg)
    if code in ("file_too_large", "too_large"):
        return phrases.text("FAIL_TOO_LARGE", cfg)
    if code == "not_available" and kind == "calendar-event" and account == "microsoft":      # removing an event from Outlook is off by decision (SPEC-SECRETARY-WRITES Q12): the plain sentence, never the writer's English
        return phrases.text("FAIL_OUTLOOK_REMOVE", cfg)
    if said:      # a code that is about the request itself (a day that does not exist, a file of another type): the step's own sentence for the person, localized; an English sentence no table knows is the plain one (S14b)
        return phone_errors.safe(phrases.localize(said, cfg), cfg)
    return phrases.phone("FAIL_NOT_DONE", cfg)


def from_error(error, cfg, word=None, account=None) -> str:
    """The sentence for a write that failed after the approval: `error` is the operations layer's (its `code`: 3 is "not configured", and its words, which a provider
    wrote). `word` is the effect's word (`files`, `calendar`, `mailbox`, `send`) and `account` its account, when the caller knows them."""
    text = str(error)
    service = _service(_family(None, word), account, cfg)
    if OUTLOOK_REMOVE.search(text):
        return phrases.text("FAIL_OUTLOOK_REMOVE", cfg)
    if UNKNOWN.search(text):
        return phrases.text("FAIL_UNKNOWN", cfg, place=phrases.text(PLACE_OF_WORD.get(word, "FAIL_LOOK_ANY"), cfg))
    if QUOTA.search(text):
        return phrases.text("FAIL_QUOTA", cfg, service=service)
    if TOO_LARGE.search(text):
        return phrases.text("FAIL_TOO_LARGE", cfg)
    if TAKEN.search(text):
        return phrases.text("FAIL_NAME_TAKEN", cfg)
    if getattr(error, "code", 1) == 3 or AUTH.search(text):
        return phrases.phone("FAIL_NOT_AUTHORIZED", cfg, service=service)
    if NETWORK.search(text):
        return phrases.text("FAIL_NETWORK", cfg, service=service)
    return phrases.phone("FAIL_NOT_DONE", cfg)


if __name__ == "__main__":
    if sys.argv[1:] in (["--help"], ["-h"]):
        print(__doc__.strip())
        sys.exit(0)
    print(__doc__.strip(), file=sys.stderr)
    sys.exit(2)
