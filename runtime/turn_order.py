# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The order in which a line is claimed: the one table (package S41-2; PLAN-BRAIN section 4 step 1, "one precedence table").

WHAT IT IS. `ORDER` is data: the names, in order, of everything that may take a line a person sends, on every shell. Who takes a line first is not decided by a chain of `if` and `elif`
spread over three modules, it is decided by the position of a row in this tuple. A shell has a dispatcher that walks the rows of its stage in this order, runs the code of each row, and
stops at the first one that says it took the line (runtime/messaging_turn.py for the messaging bridge; the operations stage is added to this file by package S41-3). This file holds no code
of any claimer and imports nothing: it can be read, checked and diffed by itself, which is the point (a claimer that moves or goes away changes a line here, and a test reads the line).

THE STAGES. `bridge` is the messaging bridge's handling of one update (`Bridge._handle`): the envelope (an update that is dropped, ignored or refused before anything reads its words), the frame
rows (a line that answers a question that is open, a word that decides a card, a plan or a search), and one row for each kind of line the parse returns. `bridge-say` is the start of
`Bridge.say`: the two claims made before a free line is queued, and the queueing itself (the last row of every stage always takes the line).

THE LIMITS. The order is where limits L63(3), L64 and L65 live (code claimers before the interpreter; the OK of a plan before the words that decide a card; the research stop after them), so
it is checked: the contract's written order is read against this table by a test (package S41-3 adds it), and `runtime/tests/test_turn_order.py` replays the entry corpus with each row
disabled and with neighbouring rows swapped. A row is removed only in a change that names, in `RETIRED`, what replaces it and when (L63(3): a claimer is never dropped silently).

`names(stage)` is the one reading of the order. The names equal the bridge part of `CLAIMER_NAMES` of runtime/tests/entry_kit.py.

Standard library only. Runs on Python 3.9. `python3 runtime/turn_order.py --help` says what it is; `python3 runtime/turn_order.py` lists the rows.
"""
from __future__ import annotations

import argparse
import sys

STAGES = ("bridge", "bridge-say")


def _rows(stage: str, rows: tuple) -> tuple:
    return tuple({"name": name, "stage": stage, "what": what} for name, what in rows)


ORDER = _rows("bridge", (
    # the envelope: nothing of the person's words is read before these have decided
    ("drop-unlisted", "An update that is not a private line of a listed sender is dropped with no reply; a listed sender of a project whose configuration is not accepted is told so, once (S12)."),
    ("drop-invalid-attachments", "An update whose attachments are not valid is dropped with one log line and no reply."),
    ("ignore", "An update with no text, no action and no attachment is ignored."),
    ("forwarded-refusal", "A forwarded message is never a request: one sentence, and nothing of it is read by a draft, a reminder, a write or a card (FWD)."),
    ("reply-to-card", "A natural line that is a reply to a card (not a reminder) becomes the kind reply: it answers that card (NR-1). It takes no line; the rows after it see the rewrite."),
    # the frame: a line that answers what is open, before any line is read as a new request
    ("reminder-draft-answer", "The next line of a chat with a question open about a reminder answers it, or drops it and goes on as a new line (NR-1)."),
    ("reminder-expired-yes", "A yes to a reminder question that expired is told so (NR-1)."),
    ("write-draft-answer", "A line that answers an open question about a write to the person's accounts (NR-5); any other line drops that question and goes on."),
    ("plan-confirm-word", "The OK or the refusal of a plan the operations layer asked (the question \"Posso?\"), or a correction: before the card words (D5, limits L64 and L65)."),
    ("card-word", "An approve or reject word decides the one decision card it can, or lists the cards to choose from (S2, limit L64)."),
    ("research-stop", "A stop word of the sender's own running research: after the card words, so that a \"no\" with a card as the last message still rejects the card (BL2b, limit L64)."),
    ("card-revise", "A change of the card that waits, said in words (S13, limit L64)."),
    ("project-switch", "\"Change to the project X\", the typed /project said in words (S20)."),
    ("help-in-words", "\"help\" in words is the typed /help (the fixed list), unless the line is a greeting the sender may talk to (S5)."),
    ("attachment-line", "A line about the file just sent: discard it, add it to the project (ATT-3)."),
    # one row for each kind of line the parse returns
    ("attachment-arrived", "A file arrived (ATT-1b)."),
    ("attachment-typed", "/add <n> and /discard <n> (ATT-1b)."),
    ("remind-typed", "/remind <time> <text> in the strict grammar (RM-1)."),
    ("write-form", "A write to the person's accounts said in words, a form the parse read before any reminder (NR-5)."),
    ("reminder-form", "A reminder or its listing or removal said in words, done by code with no model (NR-1)."),
    ("say-natural", "Any other natural line goes to `say`."),
    ("reminders-list", "/reminders (RM-1)."),
    ("forget-typed", "/forget <n> (RM-1)."),
    ("tap", "A tap on a button (a card or a question)."),
    ("usage", "A command typed without its argument is answered with its usage line."),
    ("help-typed", "/help or /start: the fixed list of this app."),
    ("project-typed", "/project <name>."),
    ("pending-typed", "/pending."),
    ("decision-typed", "/approve, /reject, /release and /answer, typed."),
    ("reply", "A reply to a card or to a message of the chat: a question card is answered, any other goes to `say`."),
    ("say", "Every other line goes to `say`. This row always takes the line."),
)) + _rows("bridge-say", (
    ("delete-refusal-before-queue", "A request to delete a file is answered at once, before any queue, run or model, when the sender may talk and may not move a file to the trash (S14b)."),
    ("closed-form-without-slot", "A decision or an act said in a closed form is answered by code and started without a model slot, so that a brake said in words works while the planning agent answers (S20)."),
    ("say-queue", "The line goes to the planning agent: started, or kept in the queue of the project (BQ-1). This row always takes the line."),
))

# A row that left the table: {"name", "replaced_by", "date"} (filled by S41-8 and S41-11; L63(3) names the replacement in its row).
RETIRED: tuple = ()


def names(stage: str) -> tuple:
    """The names of the rows of a stage, in the order they take a line."""
    if stage not in STAGES:
        raise ValueError(f"no stage {stage!r}: {', '.join(STAGES)}")
    return tuple(row["name"] for row in ORDER if row["stage"] == stage)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0], epilog="Without arguments, lists every row: stage, name, what.")
    parser.add_argument("--stage", choices=STAGES, help="list only the rows of this stage")
    args = parser.parse_args(argv)
    for row in ORDER:
        if args.stage in (None, row["stage"]):
            print(f"{row['stage']}\t{row['name']}\t{row['what']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
