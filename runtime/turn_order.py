# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The order in which a line is claimed: the one table (package S41-2; PLAN-BRAIN section 4 step 1, "one precedence table").

WHAT IT IS. `ORDER` is data: the names, in order, of everything that may take a line a person sends, on every shell. Who takes a line first is not decided by a chain of `if` and `elif`
spread over three modules, it is decided by the position of a row in this tuple. A shell has a dispatcher that walks the rows of its stage in this order, runs the code of each row, and
stops at the first one that says it took the line (runtime/messaging_turn.py for the messaging bridge, runtime/ops_turn.py for the operations layer). This file holds no code
of any claimer and imports nothing: it can be read, checked and diffed by itself, which is the point (a claimer that moves or goes away changes a line here, and a test reads the line).

THE STAGES. `bridge` is the messaging bridge's handling of one update (`Bridge._handle`): the envelope (an update that is dropped, ignored or refused before anything reads its words), the frame
rows (a line that answers a question that is open, a word that decides a card, a plan or a search), and one row for each kind of line the parse returns. `bridge-say` is the start of
`Bridge.say`: the two claims made before a free line is queued, and the queueing itself (the last row of every stage always takes the line). `ops` is the operations layer's turn
(`ops_say.say` and the queue's drain, through `ops_turn.dispatch`): the OK of a plan, a typed command, the lines code answers (a greeting, a request to delete a file, a question about the state, the
answer to a draft, a number after a list, a write form, a tier-1 form), the router's open question, the interpreter and the planning agent. A row of this stage names, in `channels`, the shells whose
lines it can take as the code reads them today (`SHELLS`); the dispatcher skips the row for another shell. The page, the terminal, the MCP mode and the conversation's own shell pass through
this stage like the messaging bridge, and the row `interpreter` is a row of the messaging shell only (L63(1): the interpreter reads a messaging line only).

THE LIMITS. The order is where limits L63(3), L64 and L65 live (code claimers before the interpreter; the OK of a plan before the words that decide a card; the research stop after them), so
it is checked: the list of the contract's L63 row is read against this table by `runtime/tests/test_ops_turn.py` (the names, in order, and every retired name with its replacement), and
`runtime/tests/test_turn_order.py` and `test_ops_turn.py` replay the entry corpus with each row disabled and with neighbouring rows swapped. A row is removed only in a change that names, in `RETIRED`, what replaces it and when (L63(3): a claimer is never dropped silently).

`names(stage)` is the one reading of the order, `channels(name)` the shells a row applies to. The names equal `CLAIMER_NAMES` of runtime/tests/entry_kit.py.

Standard library only. Runs on Python 3.9. `python3 runtime/turn_order.py --help` says what it is; `python3 runtime/turn_order.py` lists the rows.
"""
from __future__ import annotations

import argparse
import sys

STAGES = ("bridge", "bridge-say", "ops")
SHELLS = ("messaging", "page", "terminal", "mcp", "chat", "queue")      # the shells a line can arrive on: `chat` is the conversation's own shell, `queue` is the drain, which acts as the page
EVERY_SHELL = SHELLS
NOT_MCP = ("messaging", "page", "terminal", "chat", "queue")
MESSAGING = ("messaging",)


def _rows(stage: str, rows: tuple) -> tuple:
    """The rows of a stage as dicts. A row of the stage `ops` is `(name, what, channels)`; the other stages' rows are `(name, what)` and have no `channels`."""
    return tuple({"name": row[0], "stage": stage, "what": row[1], **({"channels": tuple(row[2])} if len(row) == 3 else {})} for row in rows)


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
)) + _rows("ops", (
    # before the line is stored: the OK of a plan runs out of the dispatch of the turn (`ops_turn.confirmed`)
    ("confirmed-plan", "The OK of a plan the operations layer asked (`plan_ok`, passed by the bridge after it read the yes under L64's conditions, or the Yes button) runs that plan once and nothing else; no model reads the line (L65).", MESSAGING),
    # the lines code answers, before any model and before the router's open question
    ("command", "A line that starts with `/` is one command of the table of operations, done as the typed command is: the channel's rows, the sender's profile.", EVERY_SHELL),
    ("greeting", "A greeting, or a plain request for help, from a sender who may talk is answered by code, before any open question and any model (S5).", EVERY_SHELL),
    ("plan-bare-word", "A bare yes or no with a live plan, which the bridge did not take as the answer to the plan's question, never runs the plan: yes is told it is not the last message, no drops the plan (L65).", MESSAGING),
    ("delete-file", "A request to delete a file is one plain sentence, or the card of the file moved to the trash, never a delete: before the open question, the lists of code and the interpreter (S14, S14b, R2-A).", MESSAGING),
    # the frame
    ("router-question", "The router's open question bound to the sender (on a phone, the sender's own) is the frame of a line that is no request code recognises (LIVE-2, S4). It takes no line where it stands: it sets the frame, and the line it binds is taken at the end of the order by `planning-agent`, which the trace names `router-question` for that line.", EVERY_SHELL),
    ("state-question", "A question about the state, with no router question open, is answered by code from the store's records, or by the plan's question on a messaging app (L65).", EVERY_SHELL),
    # the forms of code
    ("draft-answer", "The line that answers the sender's live draft (a question about a reminder, about a write to the person's accounts, or the choice of a file); any other line drops the draft and goes on (NR-1, NR-5).", EVERY_SHELL),
    ("event-list-number", "A number said right after a list of events means that entry (S11).", MESSAGING),
    ("file-list-number", "A number said right after a list of files picks that file (S17).", MESSAGING),
    ("write-form-ops", "A write to the person's accounts said in words opens the card of its exact content and writes nothing (NR-5, L61).", NOT_MCP),
    ("tier-1-form", "A tier-1 form, a closed whole-line form of the table of natural requests, is executed by `ops_natural.run` and checked exactly as the typed command is (L54).", EVERY_SHELL),
    # what no list of code took
    ("talk-refusal", "A sender who may not talk, and whose line no form of code took, gets the refusal of the typed `talk`, never the router.", EVERY_SHELL),
    ("interpreter", "A plain line of a messaging sender whom the interpreter reads, which no list of code took, is read by the natural-language interpreter: messaging only, the documentation of `ops_interpret.enabled` (L63(1)).", MESSAGING),
    ("planning-agent", "Every other line goes to the planning agent, or is the answer to its open question. This row always takes the line.", EVERY_SHELL),
))

# A row that left the table: {"name", "replaced_by", "date"} (filled by S41-8 and S41-11; L63(3) names the replacement in its row, in the sentence "Replaced so far", and a test reads it there).
# `s20-verb-lists` is a claimer that left before the table existed: the closed verb lists of slice S20, replaced by the plan-confirm OK of L65 (2026-10-24).
RETIRED: tuple = (
    {"name": "s20-verb-lists", "replaced_by": "the plan-confirm OK of L65", "date": "2026-10-24"},
)


def names(stage: str) -> tuple:
    """The names of the rows of a stage, in the order they take a line."""
    if stage not in STAGES:
        raise ValueError(f"no stage {stage!r}: {', '.join(STAGES)}")
    return tuple(row["name"] for row in ORDER if row["stage"] == stage)


def channels(name: str) -> tuple:
    """The shells whose lines a row can take, as the code reads them today. A row of the stages `bridge` and `bridge-say` is the messaging bridge's alone."""
    for row in ORDER:
        if row["name"] == name:
            return row.get("channels", MESSAGING)
    raise ValueError(f"no row {name!r}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0], epilog="Without arguments, lists every row: stage, name, what (and, for the rows of the stage ops, the shells it applies to).")
    parser.add_argument("--stage", choices=STAGES, help="list only the rows of this stage")
    args = parser.parse_args(argv)
    for row in ORDER:
        if args.stage in (None, row["stage"]):
            print(f"{row['stage']}\t{row['name']}\t{row['what']}" + (f"\t{','.join(row['channels'])}" if "channels" in row else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
