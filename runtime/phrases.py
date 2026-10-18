#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The phrase table (package LR-1): the sentences the runtime says to a person in the project's language, and the one function that picks them.

One table, `TABLE = {"en": {key: text}, "pt-BR": {key: text}}`. The English column is a pure literal here, and the Portuguese column is the pure literal
of its own data module, runtime/phrases_pt_br.py (the one file written in Portuguese on purpose, so that the check that every other file is English stays on
this one), so that a reviewer reads the two columns side by side. English is the source: each key is the name of the constant it replaced (`STALE`, `QUEUED`,
`ASK_HINT`...), and the module that had the constant keeps it as the English text (`phrases.en(key)`), so that a project with no `language`
key, and every test written before the table, sees the sentences byte for byte as they were. A key that two modules had as a name of its own
carries the area as a prefix (`ATT_` for a file a sender sent, `RM_` for a reminder, `ASK_` where the answer from sources shares a name with
another sentence).

`text(key, cfg, **fields)` is the one function a module calls. `cfg` is anything that maps `language` to the project's setting (the
configuration, the bridge's settings, `{"language": "pt-BR"}`) or None; the tag is `language.effective(None, cfg["language"])[0]`, the order
runtime/language.py defines: the project's key, else `en`. The language a request asks for its deliverable is NOT used here: it is the
language of an artifact, and these are the runtime's own sentences. A tag with no table (`fr`) gets English, and so does a key a table lacks.

What is in scope: the sentences of the messaging bridge and its cards, `/help` and the usage lines, the files a sender sends, the reminders,
the conversation's own sentences (the answer to a question about the state, the plan reply's lines, the refusals of the planning agent) and
the answer from sources (AQ-1) with its checked-quote frame. What is out: the texts of `OpsError` (the operations layer, read by tests and shown
after "error:"), logs, the terminal's output, the page's own text, file names, commands and ids. A command inside a sentence (`/approve 12`,
`/pending`, `@id`) is the same in every language, and so is the angle-bracket argument after it. The Portuguese column says "plataforma",
never "bancada" (the maintainer's rule); the maintainer reviews it in the pull request.

A value a sentence holds is the sentence's own: `localize` says only the fields `reason`, `declared`, `sniffed` and `status` of a sentence, never a file name or a
text of a person that happens to be a word of the table. Sizes in a Portuguese sentence use a decimal comma (`decimal`).

  text(key, cfg, **fields)    the sentence in the project's language, its `{fields}` filled in
  en(key)                     the English sentence, unfilled (what a module keeps as its constant)
  tag(cfg)                    the tag text() uses: the project's, else `en`
  kind_word(kind, cfg)        a decision's kind (`plan`, `effect`...) as a word of the language; the kind itself when the table has none
  heads(key)                  the part of a sentence before its first `[` in every language of the table, for the check of an imitated quote
  every(key)                  the sentence of a key in every language of the table (the forms a model must not write, the headings a model's line may imitate)
  decimal(text, cfg)          a number written with a point, as the language writes it (a comma in Portuguese)
  localize(sentence, cfg)     an English sentence of a reminder or a file, as an operation raised it, in the project's language; any other text unchanged
  status(word, cfg)           a status word of the store as a word of the language (the word itself when unknown or the language has no table)
  heading(title, cfg)         the title of a decision that code wrote whole, as a word of the language; any other title unchanged
  body(text, cfg)             the body of a decision that code wrote whole, in the language; any other body unchanged

Standard library only. Runs on Python 3.9: python3 runtime/phrases.py --help
"""
from __future__ import annotations

import os
import re
import string
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import language  # noqa: E402  (the same folder: the order that decides the tag)
import phrases_pt_br  # noqa: E402  (the same folder: the Portuguese column, data only)

TABLE = {
    "en": {
        # --- the messaging bridge (messaging_bridge.py) ---
        "STALE": "This button is no longer valid. Send /pending.",
        "NO_CARD": "Act on the card sent to you (send /pending).",
        "CHANGED": "This decision changed since you saw it.",
        "STILL_WORKING": "Still working on the last message.",
        "RUN_BUSY": "The planning agent is answering another request. Send it again in a moment.",
        "NOT_ACCEPTED": "This project's configuration is not accepted: run accept-config in the terminal.",
        "EFFECT_REPLY": "An effect is approved on the page or in the terminal, with its hash:",
        "TOO_LONG": "Too long to approve here: approve it on the page or in the terminal, with its hash:",
        "WRONG_HASH": "The hash you typed is not the one of the card you saw. Send /pending.",
        "NOT_OPEN": "Pending decision {number} is {status}, not open.",
        "NOT_OFFERED": "That card did not offer an approval. Send /pending for the current one.",
        "REPLY_TO_CARD": "Reply to the card of this decision to act on it.",
        "UNREAD_ONE": "A message sent to this channel could not be read and was set aside: nothing was done with it. If it was yours, send it again.",
        "UNREAD_MANY": "{n} messages sent to this channel could not be read and were set aside: nothing was done with them. If one was yours, send it again.",
        "QUEUED": "Got it: I will answer this after the current one.",
        "QUEUE_EXPIRED": "Not answered: the project stayed busy for 30 minutes. Send it again.",
        "QUEUE_STOPPED": "Not answered: the bridge stopped. Send it again.",
        "NO_REPLY": "(no reply)",
        "PROJECT_NOW": "Your lines go to {name}. Projects: {projects}.",
        "PROJECT_NONE": "No such project. Projects: {projects}.",
        "PROJECT_SET": "Your lines now go to {name}.",
        "NOTHING_WAITS": "{name}: nothing waits for you.",
        "NOTHING_TO_ACT": "{name}: nothing waits for you to act on.",
        "ANSWERED": "Answered #{id}.",
        "REJECTED": "Rejected #{id}.",
        "APPROVED": "Approved #{id}.",
        "RELEASED": "Released #{id}.",
        "NOT_APPROVABLE": "Pending decision {number} is a {kind}: approve takes a plan or an acceptance.",
        # --- /help and the usage lines (messaging_inbound.py) ---
        "HELP": ("Commands:\n/pending            what waits for you\n/approve <id>       approve what the last card of <id> showed\n"
                 "/reject <id> [note] reject it\n/release <id>       release a delivery\n/answer <id> <text> answer a question\n"
                 "/ask <question>     answer a question from the project's sources\n"
                 "/add <n>            add a file you sent as a source\n/discard <n>        delete a file you sent\n"
                 "/remind <time> <text> a reminder sent back to you once (15:00, 2026-10-20 09:30 or in 2h)\n/reminders          the reminders that wait\n"
                 "/forget <n>         cancel a reminder\n"
                 "/project [name]     choose the project your lines go to\n/help               this list\n"
                 "Any other line goes to the planning agent. Which of these your project turns on is in its configuration "
                 "(channels.messaging)."),
        "USAGE_APPROVE": "Usage: /approve <id>",
        "USAGE_REJECT": "Usage: /reject <id> [note]",
        "USAGE_RELEASE": "Usage: /release <id>",
        "USAGE_ANSWER": "Usage: /answer <id> <text>",
        "USAGE_ADD": "Usage: /add <n>",
        "USAGE_DISCARD": "Usage: /discard <n>",
        "USAGE_FORGET": "Usage: /forget <n>",
        # --- the card frames (messaging_cards.py) ---
        "LABEL_APPROVE": "Approve",
        "LABEL_REJECT": "Reject",
        "LABEL_RELEASE": "Release",
        "LABEL_ADD": "Add",
        "LABEL_DISCARD": "Discard",
        "EFFECT_LABEL": "Approve this exact content",
        "PAGE_LABEL": "Open the page",
        "CUT": "(continues on the page)",
        "WHOLE": "(the whole text follows as a document)",
        "WHOLE_ABOVE": "(the whole text is in the file above)",
        "DOCUMENT_NOTE": "The whole text of this decision, as a file. The card with the buttons follows once this file has arrived.",
        "DOCUMENT_LINE": "The file with the whole text did not arrive, so this card cannot be approved here: approve it on the page or in the terminal, or send /pending to try the file again.",
        "PAGE_LINE": "Act on it on the page or in the terminal.",
        "REPLY_LINE": "Reply to this message to answer.",
        "EFFECT_LINE": "Approve it on the page or in the terminal:",
        "TOO_LONG_LINE": "Too long to approve here: approve it on the page or in the terminal.",
        "APPROVES_LINE": "Approving applies exactly the text above (sha256 {sha}).",
        "MORE_LINE": "And {n} more waiting. Send /pending to list them.",
        "SEND_LINE": "Send {line}",
        "HEADER": "{project} · {kind} #{id}",
        "HEADER_FILE": "{project} · file #{id}",
        "WAITS_COUNT": "A {kind} waits for you.",
        "ATTACH_ASK": "File from you on {platform}: {name} ({size}, {kind}).\nAdd it to {project} as the source `{id}`?",
        "ATTACH_ASK_VERSION": "File from you on {platform}: {name} ({size}, {kind}).\nAdd it to {project} as version {n} of the source `{id}`?",
        "ATTACH_COUNT": "A file from you waits for your answer.",
        "A_MESSAGING_APP": "a messaging app",
        "FILE_WORD": "file",
        "KIND_PLAN": "plan",
        "KIND_QUESTION": "question",
        "KIND_REVIEW": "review",
        "KIND_EFFECT": "effect",
        "KIND_ACCEPTANCE": "acceptance",
        "KIND_YOUR_DOCUMENT": "your_document",
        # --- the files a sender sends (messaging_attach.py, attachments.py) ---
        "ATT_OFF": "Files are not taken from this app for this project. Add it on the page or in the terminal (source-import).",
        "ATT_NO_FILES": "This app's connection does not take files yet.",
        "ATT_MEDIA": "Photos, voice notes, videos and stickers are not taken as sources: send a PDF, a Word document, a spreadsheet, a presentation, an HTML page or a text file.",
        "ATT_TOO_LARGE": "{name} is {size}; a file from this app is at most {cap}.",
        "ATT_DAY": "This project took {n} files ({size}) from messaging apps today, its limit. Send it again tomorrow, or add it on the page.",
        "ATT_HELD_FULL": "{n} files wait for your answer already. Answer them first (/pending).",
        "ATT_GONE": "That file can no longer be fetched from {platform}. Send it again.",
        "ATT_MISMATCH": "{name} says it is a {declared} and its bytes are a {sniffed}, so it was not taken.",
        "ATT_REFUSED": "{name} was not added and was deleted: {reason}.",
        "ATT_DUPLICATE": "{name} already waits for your answer (file {id}).",
        "ATT_CAPTION_IGNORED": "The text sent with a file is not read; send it as its own message.",
        "ATT_OVER_MESSAGE": "At most {n} files are taken from one message; the rest were not.",
        "ATT_BUSY": "Another file is being fetched. Send this one again in a moment.",
        "ATT_FETCH_FAILED": "The file could not be fetched. Send it again.",
        "ATT_ADDED": "Added {name} as `{id}`, version {n}.",
        "ATT_ADDED_SAME": "{name} is already the newest version of `{id}` (version {n}): nothing changed.",
        "ATT_TARGET_TYPE": "`{id}` is a {type} source: a file cannot be added to it. Send the file without that text, or name a source of the type file.",
        "ATT_TARGET_CHANGED": "The source `{id}` changed since this file arrived. Discard it (/discard {n}) and send it again.",
        "ATT_DISCARDED": "Discarded {name}.",
        "ATT_NOT_HELD": "That file is {status}, not waiting for your answer.",
        "ATT_NO_SUCH": "No file {n} waits for you.",
        "ATT_EXPIRED": "{name} waited more than {days} days and was deleted. Send it again.",
        "ATT_LOST": "The held file is gone from this machine. Send it again.",
        "ATT_KEPT_FAILED": "{name} could not be kept on this machine. Send it again in a while.",
        "ATT_MACHINE": "This machine could not do that now. Try again later, or use the page or the terminal.",
        "ATT_NOTE": "Note: {note}",
        "ATT_WAITING_HEAD": "{project}: files waiting for your answer",
        "ATT_WAITING_LINE": "file #{id} {name}: /add {id} or /discard {id}",
        "ATT_REASON_CREDENTIAL": "it holds what looks like a credential",
        "ATT_REASON_SIZE": "its text is too large for one source",
        "ATT_REASON_CONVERT": "it could not be read as a document",
        "ATT_REASON_MACRO": "it holds macros, which are never converted",
        "ATT_REASON_TYPE": "it is not a type that is read as a source",
        "ATT_REASON_CHANGED": "it changed on this machine while it waited",
        "ATT_REASON_MISMATCH": "its bytes are not what it says",
        "ATT_REASON_TARGET": "the source it names is not a file source",
        "ATT_SUBTYPE_PDF": "PDF",
        "ATT_SUBTYPE_DOCX": "Word document",
        "ATT_SUBTYPE_XLSX": "spreadsheet",
        "ATT_SUBTYPE_PPTX": "presentation",
        "ATT_SUBTYPE_OOXML": "Office document",
        "ATT_SUBTYPE_HTML": "HTML page",
        "ATT_SUBTYPE_CSV": "spreadsheet (csv)",
        "ATT_SUBTYPE_TEXT": "text file",
        # --- reminders (messaging_remind.py, reminders.py) ---
        "RM_USAGE": "Usage: /remind HH:MM <text>, /remind YYYY-MM-DD HH:MM <text> or /remind in <n>m|h|d <text> (24-hour clock, two digits).",
        "RM_TEXT_LINE": "Reminder: {text}",
        "RM_COUNT_LINE": "A reminder is due (#{id}).",
        "RM_COUNT_LATE": " It was due at {at}.",
        "RM_TEXT_LATE": " (due at {at})",
        "RM_NO_SUCH": "No reminder {n} waits for you.",
        "RM_NOT_WAITING": "Reminder {n} is {status}, not waiting.",
        "RM_BEING_SENT": "Reminder {n} is being sent now.",
        "RM_OPEN_FULL": "There are already {n} reminders waiting in this project. Forget one first.",
        "RM_CHAT_FULL": "There are already {n} reminders waiting for this chat. Forget one first.",
        "RM_DAY_FULL": "{n} reminders were already made for this chat today. Try again tomorrow.",
        "RM_SET": "Reminder #{id} set for {wall} ({zone}).",
        "RM_FORGOT": "Forgot reminder #{id}.",
        "RM_NOT_LISTED": "You are not a listed sender of this project.",
        "RM_NOT_A_TIME": "{given} is not a time of day (00:00 to 23:59).",
        "RM_NO_SUCH_DATE": "{given} is not a day of the calendar.",
        "RM_NO_SUCH_TIME": "{given} does not exist on that day (the clock skips it). Pick another time.",
        "RM_PAST": "That time has passed. Now it is {now}.",
        "RM_TOO_SOON": "A reminder is at least one minute ahead. Now it is {now}.",
        "RM_TOO_FAR": "A reminder is at most 366 days ahead.",
        "RM_NO_TEXT": "A reminder needs the words to send.",
        "RM_TOO_LONG": "A reminder is at most {max} characters; yours has {n}.",
        "RM_CREDENTIAL": "That text looks like a credential ({labels}); a reminder is a message sent to your phone, so it is not stored.",
        "RM_WHY_LATE": "missed, it was more than 6 hours past its time when the bridge looked",
        "RM_WHY_SENDER_REMOVED": "not sent, you are no longer a listed sender",
        "RM_WHY_NOT_PERMITTED": "not sent, reminders are off for you now",
        "RM_WHY_OTHER": "not sent",
        "RM_NONE_WAIT": "no reminders wait.",
        "RM_WAITING_HEAD": "reminders that wait ({zone})",
        "RM_NOT_SENT_HEAD": "Not sent lately:",
        # --- the conversation (ops_say.py) ---
        "PLAN_NEXT": "Approve with /approve {pending}",
        "ASK_NEXT": "Answer with a plain line, or start again with /new <text>",
        "ANSWERED_AS": "(answered from the sources: request {request})",
        "BODY_NOT_NAMED": "The planning agent did not name a flow or a skill for request {request}",
        "NOT_NAMED_NEXT": "Cancel it with /cancel {request}, name a flow in the terminal with: {route}, or start again with /new <text>",
        "QUEUED_REQUEST": "Recorded as request {request}. The planning agent routes it when the run ends.",
        "PROPOSES": "The planning agent proposes: ",
        "PLANNING_NOT_STARTED": "The planning agent may not start now: {why}. Nothing was run.",
        "ROUTER_FAILED": "The router could not run: {failure}",
        "PLAN_ESTIMATE": "Estimate: {runs} runs",
        "PLAN_NOT_PLANNED": "Not planned {n}: {item}. The router's reply:",
        "PLAN_STEP": "step {step}",
        "QUEUE_DEAD_LINE": "A queued line was not answered: the service stopped while it was routed. Send it again.",
        "QUEUE_DROPPED_LINE": "A queued line was not answered: {why}",
        "REQUEST_NOT_ROUTED": "Request {id} was not routed: {why}. Route it again when you want it planned.",
        "QUEUE_DEAD_WHY": "the service stopped while it was routed",
        "TITLE_ROUTER_ASKS": "The router asks",
        "TITLE_ROUTE_UNRECOGNISED": "The route was not recognised",
        "TITLE_NO_DELIVERY_ROUTED": "No delivery was routed",
        "TITLE_REROUTE_ACCEPT": "Accept the tasks of delivery {k}, routed after its brief",
        "TITLE_REROUTE_FAILED": "Delivery {k} was not routed after its brief",
        "STATE_RECORDED": "Request {id}, \"{title}\": recorded; it waits for its route.",
        "STATE_PROGRESS": "Request {id}, \"{title}\": {done} of {total} tasks done{names}.",
        "STATE_RUNNING": "Running now: {names}.",
        "STATE_WAITING": "Waiting for you: {names}.",
        "STATE_READY": "Ready: task {id}, \"{title}\"{held}.",
        "STATE_HELD": " (held: {reason})",
        "STATE_STUCK": "Stuck: task {id}, \"{title}\", is {state}{note}.",
        "STATE_NONE_OPEN": "No request is open.",
        "STATE_FINISHED": " {n} finished.",
        "STATE_WAITS": "What waits for you: {items}.",
        "STATE_WAIT_ITEM": "{kind} \"{title}\" (decision {id})",
        "STATE_NOTHING": "nothing",
        "NAMES_MORE": " and {n} more",
        # --- the answer from sources (ops_ask.py, ask_reply.py) ---
        "NOT_BUILT": "No skill answers from the sources in this checkout yet (asst-answer is planned).",
        "NO_SOURCES": "This project has no source with a version to answer from. Import one first.",
        "NO_MATCH": "No source of this project seems to be about this. Name one with @<id>: {ids}.",
        "TOO_MANY": "A question reads at most {max} sources, and you named {n}.",
        "ASK_TOO_LARGE": "The text of these sources is too large for one question (at most {kib} KiB in all): {named}. Name fewer or smaller ones.",
        "SKIPPED": "Not read, too large for one question: {named}.",
        "NOT_STARTED": "The {agent} agent may not start now: {why}. Nothing was run.",
        "SOURCE_REFUSED": "A source could not be handed over: {why} Nothing was run.",
        "HAND_CHANGED": ("The newest version of a source for this question is a file you changed by hand: it is read only by a question asked in the "
                         "terminal. Ask there, or import a new file for the source. Nothing was run."),
        "WITHHELD": "The answer was withheld: you may no longer ask on this channel.",
        "ASK_FAILED": "The answer run failed ({kind}): {reason}. Nothing was answered.",
        "ASK_HINT": "To answer from your sources, send /ask <question>.",
        "ASK_CANCELLED": "The question was cancelled. Nothing was answered.",
        "SNAPSHOT_HERE": "A mailbox or a calendar is read only by a question asked in the terminal or on the page: ask there. Nothing was run.",
        "UNCHECKED": "This answer is not in the expected form; check it against the sources.",
        "UNKNOWN_SOURCE": "This source was not given to the run: {id}.",
        "QUOTE_NOT_FOUND": "This quote is not in {id}:",
        "QUOTE_TOO_LONG": "This quote is longer than {max} characters and was not checked ({id}):",
        "QUOTE_TOO_SHORT": "This quote is too short to check ({id}):",
        "QUOTE_CHECKED": "Checked quote [{id}]: \"{text}\"",
        "QUOTE_IMITATED": "A line of the answer imitated a checked quote and was left out.",
        "AFTER_INSTRUCTIONS": "Text after the instructions line was left out.",
        "INSTRUCTION_UNVERIFIED": "An instruction found in a source was left out: its quoted passage is not in that source.",
        "BIDI_LEFT_OUT": "A line with text-direction controls was left out.",
        "INSTRUCTION_LINE": "[{id}] \"{passage}\" (not followed)",
        "UNVERIFIED": "No quote of this answer could be checked against the sources; check it yourself.",
        "NOT_FOUND": "Not found in the sources read: {read}.",
        "READ": "Read: {read}",
        "READ_VERSION": "{source} (version {version})",
        "UNPROVEN": "Unproven: {skill} has no passing test on {model}; check the answer against the quotes.",
        "INSTRUCTIONS": "Instructions found in external content:",
        "EMPTY_REPLY": "(empty reply)",
        # --- the natural requests (ops_natural.py, source_resolve.py, package NR-2) ---
        "NAT_PRIVATE_LINE": "(a reminder)",
        "NAT_PRIVATE_REPLY": "(reminder)",
        "NAT_PLANNED": "I cannot do that yet: {what} (planned).",
        "NAT_E_CALENDAR_EVENT_CREATE": "create an event on your calendar",
        "NAT_E_CALENDAR_EVENT_CHANGE": "change an event on your calendar",
        "NAT_E_CALENDAR_EVENT_CANCEL": "cancel an event on your calendar",
        "NAT_E_MAIL_SEND": "send an e-mail from your account",
        "NAT_E_MAIL_REPLY": "reply to an e-mail",
        "NAT_E_MAIL_DRAFT": "draft an e-mail",
        "NAT_E_MAIL_ORGANIZE": "archive, label, move or mark e-mails",
        "NAT_E_DOCUMENT_CREATE": "create a document in your drive",
        "NAT_E_DOCUMENT_EDIT": "edit a document in your drive",
        "NAT_E_DOCUMENT_SAVE": "save a document in your drive",
        "NAT_NOT_BELIEVED": "I could not match that to what you wrote, so nothing was done. Please say it again.",
        "NAT_ASK_ID": "Which number? Say it again with the number in the line.",
        "NAT_ASK_TEXT": "What should I remind you of?",
        "NAT_ASK_WHEN": "When? Say the day and the time.",
        "NAT_CONFIRM_REMIND": "Create a reminder for {when}{words}? Answer yes to confirm.",
        "NAT_DROPPED": "Ok, nothing was created.",
        "NAT_CONFIRM_FORGET": "Forget reminder #{id}? Answer yes to confirm.",
        "NAT_READ_REPLY": "(shown where it was asked)",
        "NAT_NO_DECISION": "There is no open decision #{id}.",
        "NAT_WEEKDAYS": "Mon,Tue,Wed,Thu,Fri,Sat,Sun",
        "NAT_TODAY": "today",
        "NAT_TOMORROW": "tomorrow",
        "NAT_AT": "at",
        "NAT_TYPE_IT": "This changes something, so it is done by its command, not by a line of words. Send: {command}",
        "NAT_DECISION_TYPED": "A decision is made by its command, never from a line of words. Send: {command}",
        "NAT_DECISION_CARD": "A decision is made from its card, never from a line of words: use the button on the card of #{id}.",
        "NAT_DECISION_NO_CARD": "A decision is made from its card, never from a line of words, and its card could not be sent now. Send /pending.",
        "NAT_GATED": "That is not done from a line of words. Do it {place}{command}",
        "NAT_PLACE_TERMINAL": "in the terminal",
        "NAT_PLACE_PAGE": "on the page",
        "NAT_PLACE_BOTH": "in the terminal or on the page",
        "NAT_NOTHING_WAITS": "Nothing waits for you.",
        "NAT_NO_SOURCES": "No sources yet.",
        "NAT_NOTHING": "Nothing to show.",
        "NAT_ASK_WHICH": "Which file do you mean? Answer with its number.\n{list}",
        "NAT_NO_SOURCE": "No source of this project matches that. Searching your accounts is planned, not built yet.",
        "NAT_USED": "I used: {name}.",
        "NAT_ASK_REMIND_HINT": "That looks like a reminder: write it in words, for example 'remind me tomorrow at 1 pm about the haircut'.",
    },
    "pt-BR": phrases_pt_br.TABLE,
}

# The store's own status words (providers/store/sqlite.py: the CHECK lists of the tables and the state lists of its state machines), said to a person. They stay
# English in the store, the operations layer, the logs, the terminal, the MCP mode and the API; only a sentence rendered for a person in a project whose language
# has a table shows the translated word (`status`). A test reads the store's lists, so a new status cannot be added without a word here.
STATUS = {
    "en": {
        "requested": "requested",
        "planned": "planned",
        "ready": "ready",
        "running": "running",
        "waiting": "waiting",
        "blocked": "blocked",
        "done": "done",
        "failed": "failed",
        "cancelled": "cancelled",
        "pending": "pending",
        "claimed": "claimed",
        "to_inbox": "to_inbox",
        "ok": "ok",
        "timeout": "timeout",
        "open": "open",
        "approved": "approved",
        "rejected": "rejected",
        "resolved": "resolved",
        "mirrored": "mirrored",
        "read_only": "read_only",
        "used": "used",
        "dismissed": "dismissed",
        "pending-execution": "pending-execution",
        "executed": "executed",
        "active": "active",
        "expired": "expired",
        "revoked": "revoked",
        "cleared": "cleared",
        "dropped": "dropped",
        "created": "created",
        "asked": "asked",
        "skipped": "skipped",
        "held": "held",
        "added": "added",
        "refused": "refused",
        "discarded": "discarded",
        "sending": "sending",
        "sent": "sent",
        "missed": "missed",
        "draft": "draft",
        "paused": "paused",
        "stopped": "stopped",
    },
    "pt-BR": phrases_pt_br.STATUS,
}

DEFAULT = language.DEFAULT
HEADINGS = ("TITLE_",)      # the family of keys for the headings of a decision that code writes whole
BODIES = ("BODY_",)         # ... and for a body that code writes whole, with nothing of a person's or a model's in it
LOCALIZED = ("ATT_", "RM_")      # the families of keys `localize` knows by their English sentence
VALUE_FAMILIES = ("ATT_REASON_", "ATT_SUBTYPE_")      # a field of such a sentence that is itself one of these English words is translated too
VALUE_FIELDS = ("reason", "declared", "sniffed")      # ... but only in these fields: a file named `presentation` is not a word of the table
NUMBER_FIELDS = ("size", "cap")                         # fields that hold a size written with a decimal point (`3.5 KiB`)
DECIMAL = {"pt-BR": ","}                                # the decimal mark of a language that does not use a point
_patterns = {}


def tag(cfg=None) -> str:
    """The tag of the table `text` reads: the project's `language` (language.effective), else `en`."""
    return language.effective(None, cfg.get("language") if cfg else None)[0]


def en(key: str) -> str:
    """The English sentence, unfilled: what a module keeps as its constant."""
    return TABLE[DEFAULT][key]


def text(key: str, cfg=None, **fields) -> str:
    """The sentence of `key` in the project's language with `fields` filled in. A tag with no table, and a key the table of the tag lacks, get
    English; a key English lacks is a KeyError (a typo in the code, not a thing to hide)."""
    sentence = (TABLE.get(tag(cfg)) or {}).get(key)
    if sentence is None:
        sentence = TABLE[DEFAULT][key]
    return sentence.format(**fields) if fields else sentence


def decimal(number, cfg=None):
    """A number as text written with a point (`3.5 KiB`), with the decimal mark of the language; unchanged for English and for a language with no table."""
    mark = DECIMAL.get(tag(cfg))
    return number.replace(".", mark) if mark and isinstance(number, str) else number


def every(key: str) -> list:
    """The sentence of `key` in every language of the table, English first."""
    return [t[key] for t in TABLE.values() if key in t]


def kind_word(kind: str, cfg=None) -> str:
    """A decision's kind as a word of the language (`plan`, `effect`, `question`...); the kind as it is when the table has no word for it."""
    key = "KIND_" + str(kind).upper()
    return text(key, cfg) if key in TABLE[DEFAULT] else str(kind)


def heads(key: str) -> list:
    """The part of the sentence of `key` before its first `[`, in every language of the table (whitespace trimmed): the words a model must not
    write at the start of a line (ask_reply.imitates)."""
    return [t[key].split("[", 1)[0].strip() for t in TABLE.values() if key in t]


def _pattern(key: str, numbers: bool = False):
    """The regular expression that matches the English sentence of `key` with any text in its fields, or with whole numbers only (a heading or a body that code
    writes whole holds the number of a delivery or a request and nothing else of anyone's), cached."""
    found = _patterns.get((key, numbers))
    if found is None:
        seen, parts = set(), []
        for literal, name, _spec, _conv in string.Formatter().parse(en(key)):
            parts.append(re.escape(literal))
            if name is not None:
                parts.append(f"(?P={name})" if name in seen else f"(?P<{name}>" + (r"\d+" if numbers else ".+?") + ")")
                seen.add(name)
        found = _patterns[(key, numbers)] = re.compile("".join(parts), re.S)
    return found


def status(word, cfg=None):
    """A status word of the store (`approved`, `cancelled`, `sent`...) as a word of the project's language, for a sentence rendered for a person; the word unchanged
    when it is not in the closed list (STATUS) or the language has no table. Never for a status that is parsed, stored, compared, logged or sent to a shell."""
    table = STATUS.get(tag(cfg))
    return table.get(word, word) if table and isinstance(word, str) else word


def _match(sentence, families, skip=()):
    """(key, {field: text}) of the English template of a key of `families` that equals `sentence` whole, the template with the most fixed words first; else None."""
    keys = sorted((k for k in TABLE[DEFAULT] if k.startswith(families) and not k.startswith(skip)), key=lambda k: -len(re.sub(r"\{[^}]*\}", "", en(k))))
    for key in keys:
        found = _pattern(key, numbers=families in (HEADINGS, BODIES)).fullmatch(sentence)
        if found:
            return key, found.groupdict()
    return None


def heading(title, cfg=None):
    """The title of a decision as it is rendered for a person: when code wrote it whole (a key of the family TITLE_, such as "The router asks"), in the project's
    language; a title with a flow, a skill or any person's or model's word in it, and any title in a project whose language has no table, comes back as it was. The
    stored title is never changed: a card's hash is made of it."""
    if not isinstance(title, str) or tag(cfg) not in TABLE or tag(cfg) == DEFAULT:
        return title
    found = _match(title, HEADINGS)
    return text(found[0], cfg, **found[1]) if found else title


def body(text_, cfg=None):
    """The body of a decision as it is rendered for a person: when code wrote it whole (a key of the family BODY_, such as the question of an unrecognised route), in
    the project's language; any other body, and any body in a project whose language has no table, comes back as it was. The stored body is never changed: it is
    English in the store, the operations layer, the terminal, the MCP mode and the API, and a card's hash is made of it."""
    if not isinstance(text_, str) or tag(cfg) not in TABLE or tag(cfg) == DEFAULT:
        return text_
    found = _match(text_, BODIES)
    return text(found[0], cfg, **found[1]) if found else text_


def localize(sentence, cfg=None):
    """An English sentence that an operation raised for a reminder or a file (the families LOCALIZED), as it is in the project's language; any
    other text, and any text in a project whose language has no table, comes back as it was. The sentence is matched against the English
    template of each key whole (the fields may hold any text), the template with the most fixed words first. Only the fields `status` (`status`), `reason`, `declared`
    and `sniffed` (the table's own words) and `size` and `cap` (the decimal mark) are said; every other field, a file's name first, is the sentence's own and stays."""
    if not isinstance(sentence, str) or tag(cfg) not in TABLE or tag(cfg) == DEFAULT:
        return sentence
    found = _match(sentence, LOCALIZED, VALUE_FAMILIES)
    if not found:
        return sentence
    words = {en(k): k for k in TABLE[DEFAULT] if k.startswith(VALUE_FAMILIES)}

    def said(name, value):
        if name == "status":
            return status(value, cfg)
        if name in NUMBER_FIELDS:
            return decimal(value, cfg)
        return text(words[value], cfg) if name in VALUE_FIELDS and value in words else value
    return text(found[0], cfg, **{n: said(n, v) for n, v in found[1].items()})


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
