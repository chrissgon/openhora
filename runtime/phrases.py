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
carries the area as a prefix (`ATT_` for a file a sender sent, `RM_` for a reminder, `NW_` for a write asked in words, `ASK_` where the answer from sources shares a name with
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
  card_without_private(card)  the lines of a card that are not private (CARD_PRIVATE); hidden_note_key(card, kept) the key of the note that ends a card drawn without them
  card_valid(card)            whether a decision's `card` (a list of [key, {field: text}] lines, every key of the family CARD_) can be said line by line
  card_text(card, cfg)        the lines of a valid card said in the project's language, one per line (the stored body of an effect that carries one is this in English)

Standard library only. Runs on Python 3.9: python3 runtime/phrases.py --help
"""
from __future__ import annotations

import os
import re
import string
import sys
import unicodedata

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
        "RM_NOTHING_TO_RESTORE": "There is no reminder of yours cancelled in the last 10 minutes to bring back.",
        "RM_RESTORE_TOO_LATE": "Reminder {n} is too close to its time to bring back.",
        "RM_ALREADY_BACK": "Reminder {n} is already back.",
        "RM_BACK": "Reminder #{old} is back as #{new}.",
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
        # --- reminders asked in the person's own words (natural.py, messaging_remind.py; package NR-1) ---
        "NT_WD_0": "Mon",
        "NT_WD_1": "Tue",
        "NT_WD_2": "Wed",
        "NT_WD_3": "Thu",
        "NT_WD_4": "Fri",
        "NT_WD_5": "Sat",
        "NT_WD_6": "Sun",
        "NT_REL_0": "today",
        "NT_REL_1": "tomorrow",
        "NT_WHEN_REL": "{rel}, {wd} {dm}, at {time}",
        "NT_WHEN_FAR": "{wd} {dm} at {time}",
        "NT_ROLLED": "{time} today has passed: {when}",
        "NT_SET_TEXT": "Reminder #{id}: {when}: {text}. To undo: /forget {id}.",
        "NT_SET_COUNT": "Reminder #{id}: {when}. To undo: /forget {id}.",
        "NT_ASK_WHEN": "When? Example: remind me tomorrow at 1 pm to water the plants",
        "NT_ASK_WHEN_SLASH": "When? Example: /remind tomorrow 1 pm water the plants",
        "NT_ASK_TIME_DAY": "{day}: at what time? Reply with a time, for example 1 pm.",
        "NT_ASK_TIME": "At what time? Reply with a time, for example 1 pm.",
        "NT_ASK_TEXT": "What should I remind you of? Reply with the words to send.",
        "NT_ASK_READINGS": "Which time do you mean: {options}? Reply with the time.",
        "NT_OR": "or",
        "NT_ASK_KIND_TEXT": "{when}: {text}. A reminder here in the chat, or an event in your calendar?",
        "NT_ASK_KIND_COUNT": "{when}. A reminder here in the chat, or an event in your calendar?",
        "NT_WHICH": "Which one? Send /forget <n>.",
        "NT_ASK_NOTE": "Do you want a reminder? Then tell me when, for example: tomorrow at 1 pm",
        "NT_ASK_EVENT_OR_OTHER": "An event in your calendar, or something else? Reply calendar, or something else to send the line on.",
        "NT_NO_MATCH": "No waiting reminder of yours matches that. Send /reminders to see them.",
        "NT_FORGOT_TEXT": "Reminder #{id} cancelled: {when}: {text}. To get it back, send: undo",
        "NT_FORGOT_COUNT": "Reminder #{id} cancelled: {when}. To get it back, send: undo",
        "NT_RESTORED_TEXT": "Reminder #{old} is back as #{id}: {when}: {text}.",
        "NT_RESTORED_COUNT": "Reminder #{old} is back as #{id}: {when}.",
        "NT_CONFIRM_TEXT": "I understood: {when}: {text}. Confirm? (yes / another time)",
        "NT_CONFIRM_COUNT": "I understood: {when}. Confirm? (yes / another time)",
        "NT_RECURRING": "A reminder here happens once. Something that repeats is a routine: set it up in the terminal or on the page. For a single reminder, tell me when.",
        "NT_CANCELLED": "Ok, no reminder was made.",
        "NT_KEPT": "Ok, nothing was cancelled.",
        "NT_BTN_YES": "Yes",
        "NT_ASK_AGAIN": "For when? Reply with a day and a time, for example tomorrow at 1 pm.",
        "NT_ASK_WEEKDAY": "Which day next week? Reply with the weekday, for example Tuesday.",
        "NT_ASK_FORGET_TEXT": "Cancel reminder #{id}: {when}: {text}? (yes / no)",
        "NT_ASK_FORGET_COUNT": "Cancel reminder #{id}: {when}? (yes / no)",
        "NT_ASK_FORGET_MANY": "Cancel these reminders? (yes / no)",
        "NT_EXPIRED": "That question is no longer open: it waits ten minutes. Send the line again.",
        "NT_DISCARDED": "The previous question was discarded.",
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
        "NAT_NOT_BELIEVED": "I could not match that to what you wrote, so nothing was done. Please say it again.",
        "NAT_ASK_ID": "Which number? Say it again with the number in the line.",
        "NAT_READ_REPLY": "(shown where it was asked)",
        "NAT_NO_DECISION": "There is no open decision #{id}.",
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
        "NAT_ASK_REMIND_HINT": "That looks like a reminder: write it in words, for example 'remind me Friday at 5 pm to pick up the parcel at the front desk'.",
        "NW_PRIVATE_LINE": "(a request to your accounts)",
        "NW_PRIVATE_REPLY": "(request to your accounts)",
        "NW_CANCELLED": "Nothing was opened.",
        "NW_NO_CARDS": "You do not receive cards here: ask in the terminal or on the page.",
        "NW_CARD_NOT_SENT": "Card #{pending} was opened, but it could not be sent to this chat. Approve it in the terminal or on the page, or send /pending.",
        "NW_CHECK_DATE": "Check the date: I understood {when}.",
        "NW_CHECK_DATE_ASSISTED": "Check the date on the card: the assistant read it.",
        "NW_APPROVE_WITH": "To approve it, with its hash: {command}",
        "NW_NO_ACCOUNT": "None of your accounts is set up for this: the key accounts of runtime.json lists them, with what each may write to.",
        "NW_ASK_ACCOUNT": "Which account?",
        "NW_ASK_CALENDAR": "I do not have the calendar '{name}'. The calendars set up: {names}. Which one?",
        "NW_ASK_FOLDER": "I do not have the folder '{name}'. The folders set up: {names}. Which one?",
        "NW_ASK_FOLDER_NONE": "Which folder? The folders set up: {names}.",
        "NW_ASK_SOURCE": "From which calendar?",
        "NW_ASK_TIME": "When is the event '{title}'? (or 'all day')",
        "NW_ASK_TIME_PLAIN": "When is the event? (or 'all day')",
        "NW_ASK_TITLE": "What is the title of the event on {when}?",
        "NW_ASK_TITLE_PLAIN": "What is the title of the event?",
        "NW_ASK_DAY": "Which day is the all-day event?",
        "NW_ASK_END": "The end has to be after the start. At what time does it end?",
        "NW_ASK_EVENT": "Which event? Say its number (ask 'list my events' to see them).",
        "NW_ASK_FILE_NAME": "What is the file name? Give it with its extension (for example notes.md), or say 'google doc'.",
        "NW_ASK_FILE": "Which file do you mean?",
        "NW_ASK_ATTACHMENT": "Which file?",
        "NW_NO_HELD": "I have no file of yours waiting. Send the file, then ask again.",
        "NW_NO_HELD_KIND": "None of your waiting files is a {kind}. Send it, then ask again.",
        "NW_NO_CALENDAR_SOURCE": "No calendar of yours is a source of this project, so I cannot tell which event you mean.",
        "NW_REF_NOT_READABLE": "Messages and events are numbered in a snapshot of your mailbox or calendar, and this channel may not read it: ask in the terminal or on the page, or have the project's configuration give you the group ask-mail.",
        "NW_RECURRING_EVENT": "An event that repeats is not available yet. For a single event, tell me the day and the time.",
        "NW_ITEMS_HEAD": "{source} (read {read_at}):",
        "NW_ITEMS_MORE": "... and {n} more",
        "NW_ITEMS_NONE": "No numbered items yet: a mail or calendar source needs a snapshot first.",
        # --- an e-mail from the person's own account (package W2: runtime/send_document.py, runtime/mail_refs.py) ---
        "TITLE_MAIL_SEND": "Mail: send from your account",
        "TITLE_MAIL_REPLY": "Mail: reply from your account",
        "CARD_MAIL_SEND": "Code sends this e-mail from your own account after your approval, to exactly these recipients and no one else, and nothing else.",
        "CARD_MAIL_REPLY": "Code sends this reply from your own account after your approval, to exactly the recipient below and no one else, and nothing else.",
        "CARD_MAIL_FROM_ACCOUNT": "From your own account: {address} ({account})",
        "CARD_MAIL_TO": "To: {addresses}",
        "CARD_MAIL_CC": "Cc: {addresses}",
        "CARD_MAIL_BCC": "Bcc (hidden from the others, listed here for you): {addresses}",
        "CARD_MAIL_SUBJECT": "Subject: {subject}",
        "CARD_MAIL_SUBJECT_REPLY": "Subject: {subject}",
        "CARD_MAIL_REPLY_TO": "Reply to: {address}, the sender of {ref} (in the snapshot read at {read_at}): {subject}",
        "CARD_MAIL_REPLY_TO_DIFFERS": "The message asks replies to go to {other}: this reply goes to the sender above, not there.",
        "CARD_MAIL_IN_REPLY": "In reply to the message {message_id}",
        "CARD_MAIL_COUNT": "Recipients in all: {count}",
        "CARD_MAIL_MESSAGE": "----- the message, exactly as it will be sent (every line starts with \u2502) -----\n{body}\n----- end of the message -----",
        "CARD_MAIL_ATTACHMENTS": "Attachments ({count}), each a copy of a file of the project, sent only if it is still the same file:",
        "CARD_MAIL_ATTACHMENT": "Attachment: {name}, {bytes} bytes, sha256 {sha} (from {path})",
        "CARD_MAIL_ATTACH_NOTE": "The file itself is not on this card: read it in the project before you approve.",
        "CARD_MAIL_HASH": "Hash of this effect (it covers every recipient above, the text and the attachments): {sha}",
        "CARD_MAIL_APPROVE": "Approve exactly this: {command}",
        "CARD_MAIL_ONCE": "It is sent once, whatever the number of approvals of this hash. Or answer with what to change, or reject it: nothing is sent until you approve.",
        "ACCT_MAIL_NO_SENDER": "That message has no single sender address, so a reply cannot be addressed to anyone.",
        "ACCT_MAIL_NOT_REPLIABLE": "That message cannot be answered from here: its snapshot does not hold what the account needs to put the reply in the conversation. Refresh the source, then ask again.",
        "ACCT_MAIL_REPLY_MOVED": "{ref} no longer names the message you asked to answer (the snapshot was refreshed and its items were renumbered): nothing was prepared; ask again.",
        "ACCT_MAIL_OTHER_ACCOUNT": "{ref} is a message of another account than {account}: a reply is sent from the account that received the message.",
        "ACCT_MAIL_BCC_GMAIL": "A Bcc is not sent from a Google account in this version: send to To and Cc, or use the project's outbox.",
        "ACCT_MAIL_REPLY_FIELDS": "A reply has no To, Cc, Bcc, subject or attachment of its own: it goes to the sender of the message, with its subject after Re:.",
        "ACCT_MAIL_FRAME": "A line of the text begins like the frame of the card (five hyphens, or a look-alike): rewrite that line, so that the text cannot be taken for the end of the message.",
        "ACCT_MAIL_TEXT_HIDDEN": "The text or the subject holds a hidden character (a control, direction or invisible one) that the card cannot show: remove it.",
        "ACCT_MAIL_REF_MALFORMED": "{ref} is not a reference to a message: write <source id>#<number>, for example inbox#3.",
        "ACCT_MAIL_REF_ZERO": "The numbers of a snapshot start at 1: {ref} names no message.",
        "ACCT_MAIL_REF_NOT_READABLE": "{ref} is a snapshot of your mailbox, and this channel may not read it: ask in the terminal or on the page, or have the project's configuration give the sender the group ask-mail.",
        "ACCT_MAIL_REF_PAST_END": "{ref} names a message past the end of its snapshot.",
        "ACCT_MAIL_REF_NO_SOURCE": "There is no mail source for {ref}: a reference names a registered mail source.",
        "ACCT_MAIL_REF_NOT_SNAPSHOT": "{ref} is not a mail source: only a mail snapshot has numbered messages.",
        "ACCT_MAIL_REF_WRONG_KIND": "{ref} is not a message of a mail snapshot: a reply answers a message.",
        "ACCT_MAIL_REF_NO_VERSION": "The source of {ref} has no snapshot yet: refresh it first.",
        "ACCT_MAIL_REF_STALE": "The newest snapshot of {ref} is more than 26 hours old, or its time cannot be trusted: refresh it, then ask again.",
        "ACCT_MAIL_REF_NO_INDEX": "The newest snapshot of {ref} was made before messages could be referred to: refresh it first.",
        "ACCT_MAIL_REF_INTEGRITY": "The snapshot of {ref} does not match its record, or its index does not match its text: refresh it, then ask again.",
        # --- the mailbox of the person's own account (package W3, runtime/mailbox_document.py and runtime/ops_mailbox.py) ---
        "TITLE_BOX_ARCHIVE": "Mailbox: archive messages",
        "TITLE_BOX_MOVE": "Mailbox: move messages to a folder",
        "TITLE_BOX_MARK": "Mailbox: mark messages as read or unread",
        "TITLE_BOX_TRASH": "Mailbox: move messages to the trash",
        "TITLE_BOX_DRAFT": "Mailbox: save a draft",
        "CARD_BOX_CODE": "Code makes this change in your mailbox {address} after your approval. Nothing is sent and nothing is deleted.",
        "CARD_BOX_CODE_DRAFT": "Code saves this draft in your mailbox {address} after your approval. It is not sent: it waits in your Drafts for you to read and send yourself.",
        "CARD_BOX_ARCHIVE": "Archive: {n} message(s)",
        "CARD_BOX_MOVE": "Move to \"{folder}\": {n} message(s)",
        "CARD_BOX_READ": "Mark as read: {n} message(s)",
        "CARD_BOX_UNREAD": "Mark as unread: {n} message(s)",
        "CARD_BOX_TRASH_GMAIL": "Move to the trash (Gmail empties it after 30 days): {n} message(s)",
        "CARD_BOX_TRASH_OUTLOOK": "Move to Deleted Items (Outlook deletes them from there after 30 days): {n} message(s)",
        "CARD_BOX_ITEM": "{i}. {date} \u00b7 from {sender} \u00b7 {subject}",
        "CARD_BOX_READ_AT": "Read from your mailbox at {read_at}. Nothing is changed unless every message is still as listed.",
        "CARD_BOX_SNAPSHOT": "Chosen from a snapshot read at {snapshot_at}.",
        "CARD_BOX_DRAFT_TO": "To: {to}",
        "CARD_BOX_DRAFT_CC": "Cc: {cc}",
        "CARD_BOX_DRAFT_BCC": "Bcc: {bcc}",
        "CARD_BOX_DRAFT_SUBJECT": "Subject: {subject}",
        "CARD_BOX_DRAFT_REPLY_TO": "To: {to}",
        "CARD_BOX_DRAFT_REPLY_SUBJECT": "Subject: {subject}",
        "CARD_BOX_DRAFT_REPLY": "Reply to: {address}, the sender of {ref} ({date}, '{subject}')",
        "CARD_BOX_DRAFT_REPLY_DIFFERS": "The message asks replies to go to {other}: this draft goes to the sender above, not there.",
        "CARD_BOX_DRAFT_TEXT": "The draft's text, exactly as it will be saved (every line starts with \u2502):\n{body}",
        "CARD_BOX_DRAFT_END": "----- end of the draft -----",
        "ACCT_MBOX_NO_MESSAGES": "Name at least one message: <source id>#<number>, several separated by commas.",
        "ACCT_MBOX_TOO_MANY": "One card changes at most {max} messages; {n} were named.",
        "ACCT_MBOX_DUPLICATE": "{ref} is named twice.",
        "ACCT_MBOX_OTHER_ACCOUNT": "{ref} is a message of another account than the {account} account.",
        "ACCT_MBOX_NO_ID": "{ref} cannot be changed: its snapshot could not keep the message's id. Refresh the source and name it again.",
        "ACCT_MBOX_REF_MALFORMED": "{ref} is not a reference to a message: write <source id>#<number>, for example inbox#3.",
        "ACCT_MBOX_REF_ZERO": "The numbers of a snapshot start at 1: {ref} names no message.",
        "ACCT_MBOX_REF_NOT_READABLE": "{ref} points into a snapshot of your mailbox, and this channel may not read it: ask in the terminal or on the page, or have the project's configuration give the sender the group ask-mail.",
        "ACCT_MBOX_REF_PAST_END": "{ref} does not exist: the newest snapshot of {source} has fewer messages.",
        "ACCT_MBOX_REF_NO_SOURCE": "There is no source {source}: a message is named by a registered mail source and a number.",
        "ACCT_MBOX_REF_NOT_SNAPSHOT": "{source} is not a mail source.",
        "ACCT_MBOX_REF_WRONG_KIND": "{ref} does not name a message of your mailbox: a message is named <source id>#<number> of a mail source.",
        "ACCT_MBOX_REF_NO_VERSION": "{source} has no snapshot yet: refresh {source} first.",
        "ACCT_MBOX_REF_STALE": "The newest snapshot of {source} is too old to name a message: refresh {source} first.",
        "ACCT_MBOX_REF_NO_INDEX": "The newest snapshot of {source} was made before messages could be named: refresh {source} first.",
        "ACCT_MBOX_REF_INTEGRITY": "The snapshot of {source} cannot be trusted to name a message (its files were changed outside the runtime, or do not match its text): refresh {source} first.",
        "ACCT_MBOX_REF_EVENT": "{ref} names an event, not a message.",
        # --- writes to the person's own accounts (package FND, runtime/account_start.py; the lines of each kind's card are CARD_, added with the kind) ---
        "ACCT_CARD_SENT": "Card #{pending} waits for your approval.",
        "ACCT_NOT_CONFIGURED": "The account {account} is not set up for this project: the key accounts of runtime.json lists it, with its address and what it may write to.",
        "CARD_ACCOUNT": "Account: {account} ({address})",
        # --- the card of a change to the person's own calendar (package W1, runtime/calendar_document.py) ---
        "TITLE_CAL_CREATE": "Calendar: new event",
        "TITLE_CAL_CHANGE": "Calendar: change an event",
        "TITLE_CAL_CANCEL": "Calendar: remove an event",
        "CARD_CAL_CREATE": "Code creates this event after your approval, and nothing else.",
        "CARD_CAL_CHANGE": "Code changes this event after your approval, only if it is still as read at {read_at}.",
        "CARD_CAL_CANCEL": "Code removes this event after your approval. Google is expected to move it to the calendar's trash, where you can restore it for 30 days (Google Calendar, Trash); this has not been verified yet.",
        "CARD_CAL_EVENT": "Event: {event_id}",
        "CARD_CAL_NOW_WHEN": "The event now is at: {when}",
        "CARD_CAL_NOW_TITLE": "The event now: {title}",
        "ACCT_REF_MALFORMED": "That is not a reference to an item: write <source id>#<number>, for example inbox#3, or created:<card number> for an event you created.",
        "ACCT_REF_ZERO": "The numbers of a snapshot start at 1.",
        "ACCT_REF_NOT_READABLE": "{source} is a snapshot of your mailbox or calendar, and this channel may not read it: ask in the terminal or on the page, or have the project's configuration give the sender the group ask-mail.",
        "ACCT_REF_PAST_END": "{source} has fewer items than that in its newest snapshot.",
        "ACCT_REF_NO_SOURCE": "There is no source {source}: references name a registered mail or calendar source.",
        "ACCT_REF_NOT_SNAPSHOT": "{source} is not a mail or calendar source: only those have numbered items.",
        "ACCT_REF_WRONG_KIND": "{source} is not a calendar source: an event is named by an item of a calendar source.",
        "ACCT_REF_NO_VERSION": "{source} has no snapshot yet: refresh {source} first.",
        "ACCT_REF_STALE": "The newest snapshot of {source} is more than 26 hours old, or its time cannot be trusted: refresh {source} first.",
        "ACCT_REF_NO_INDEX": "The newest snapshot of {source} was made before items could be referred to: refresh {source} first.",
        "ACCT_REF_INTEGRITY": "The newest snapshot of {source} does not match its record, or names a calendar its source does not: refresh {source} first.",
        "ACCT_REF_CREATED_UNKNOWN": "That card did not create an event, or its result is not recorded.",
        "ACCT_REF_NOT_AN_EVENT": "That reference does not name an event of your Google or Microsoft account.",
        "CARD_CAL_SNAPSHOT": "Named as {reference}, from the snapshot read at {read_at}.",
        "CARD_CAL_DROP_TITLE": "Removing, title: {title}",
        "CARD_CAL_DROP_WHERE": "Removing, where: {location}",
        "CARD_CAL_DROP_NOTES": "Removing, notes: {notes}",
        "CARD_HIDDEN_NOTE": "Some of the current text of the event or the message is not shown here: the page and the terminal show all of it.",
        "CARD_HIDDEN_NOTE_FILE": "Some of the file's name is not shown here: the page and the terminal show all of it.",
        "CARD_HIDDEN_NOTE_MAIL": "Some of the addresses, subjects and text of the e-mail are not shown here: the page and the terminal show all of it.",
        "CARD_HIDDEN_NOTE_WHOLE": "The card of this change is not shown here: the page and the terminal show it.",
        "CARD_CAL_CALENDAR": "Calendar: {calendar}",
        "CARD_CAL_TITLE": "Title: {title}",
        "CARD_CAL_WHEN": "When: {when}",
        "CARD_CAL_WHERE": "Where: {location}",
        "CARD_CAL_REMIND": "Calendar reminder: {minutes} min before",
        "CARD_CAL_NOTES": "Notes: {notes}",
        "CARD_CAL_NOBODY": "No one is invited: no e-mail is sent.",
        "CARD_CAL_BASE": "Based on version {etag_short} of the event.",
        "CARD_CAL_BEFORE_TITLE": "Before: Title: {title}",
        "CARD_CAL_BEFORE_WHEN": "Before: When: {when}",
        "CARD_CAL_BEFORE_WHERE": "Before: Where: {location}",
        "CARD_CAL_BEFORE_REMIND": "Before: Calendar reminder (min before): {minutes}",
        "CARD_CAL_BEFORE_NOTES": "Before: Notes: {notes}",
        "CARD_CAL_AFTER_TITLE": "After: Title: {title}",
        "CARD_CAL_AFTER_WHEN": "After: When: {when}",
        "CARD_CAL_AFTER_WHERE": "After: Where: {location}",
        "CARD_CAL_AFTER_REMIND": "After: Calendar reminder (min before): {minutes}",
        "CARD_CAL_AFTER_NOTES": "After: Notes: {notes}",
        "CARD_CAL_KEPT_TITLE": "Unchanged: Title: {title}",
        "CARD_CAL_KEPT_WHEN": "Unchanged: When: {when}",
        "CARD_CAL_KEPT_WHERE": "Unchanged: Where: {location}",
        "CARD_CAL_KEPT_REMIND": "Unchanged: Calendar reminder (min before): {minutes}",
        "CARD_CAL_KEPT_NOTES": "Unchanged: Notes: {notes}",
        # --- files: create, replace, save (package W4a, runtime/files_document.py) ---
        "TITLE_FILE_CREATE": "Files: new file",
        "TITLE_FILE_REPLACE": "Files: new revision",
        "TITLE_FILE_SAVE": "Files: save the file you sent",
        "CARD_FILE_CODE_NEW": "Code creates this file after your approval, and nothing else.",
        "CARD_FILE_CODE_REPLACE": "Code writes a new revision of this file after your approval, only if it is still the file as read at {read_at}.",
        "CARD_FILE_CODE_SAVE": "Code saves the file you sent after your approval, and nothing else.",
        "CARD_FILE_NAME": "File: {name} ({service})",
        "CARD_FILE_NOW": "File as it is now: {name} ({service})",
        "CARD_FILE_SENT": "File sent: {name} ({service})",
        "CARD_FILE_FOLDER": "Folder: {folder}",
        "CARD_FILE_SOURCE": "Source: @{source}",
        "CARD_FILE_NEW": "A new file: nothing that exists is replaced.",
        "CARD_FILE_GDOC": "It is made as a Google Doc from this text.",
        "CARD_FILE_BASE": "Replaces revision {revision} (changed {modified}).",
        "CARD_FILE_KEPT_DRIVE": "Drive keeps the replaced revision for ever (a file keeps at most 200 revisions for ever); if it cannot, nothing is written.",
        "CARD_FILE_KEPT_DOC": "A Google Doc keeps its own revision history, which Google may thin out over time: the replaced version is not kept for ever.",
        "CARD_FILE_KEPT_ONEDRIVE": "OneDrive keeps earlier versions by its own retention settings, not for ever.",
        "CARD_FILE_OWNED": "The file belongs to this account: {address}.",
        "ACCT_FILE_NOT_OWNED": "The file named on the request is not owned by your {service} account (it is shared with you, or it belongs to another drive): only a file the account owns is replaced.",
        "ACCT_FILE_RETARGET": "The target is no longer the one the card you were asked about named (the source or the folder now points somewhere else): name it again and start over.",
        "ACCT_FILE_TAKEN_ANSWER": "Nothing was written: a file with that name is in the folder now. The task starts over from the step that reads; start it again.",
        "CARD_FILE_SAVE": "Saves the file you sent: {name}, {size}, sha256 {sha_short}.",
        "CARD_FILE_PROJECT": "A file of the project: {path}, {size}, sha256 {sha_short}. Its content is not on this card.",
        "CARD_FILE_TEXT": "----- the new text; the mark │ at the start of each line is not part of it -----\n{content}\n----- end of the new text -----",
        "CARD_FILE_HASH": "Hash of this effect (it covers the account, the target, the name and every byte): {sha}",
        "CARD_FILE_APPROVE": "Approve exactly this: {command}",
        "ACCT_FILE_NAME_BAD": "A file name is 1 to 120 characters: letters, digits, spaces and . _ - ( ), not starting with a hyphen or ending in a dot.",
        "ACCT_FILE_NAME_EXT": "The file name must end in one of: {extensions}.",
        "ACCT_FILE_TEXT_EMPTY": "The text is empty.",
        "ACCT_FILE_TEXT_BIG": "The text is over {max} bytes: write it to a file of the project and name that file.",
        "ACCT_FILE_TEXT_HIDDEN": "The text holds a control or invisible character (a right-to-left override, a zero-width character, a stray control code): remove it.",
        "ACCT_FILE_ONE_CONTENT": "Give the new text or a file of the project, one of the two.",
        "ACCT_FILE_TEXT_FRAME": "The text holds a line that looks like a rule of the card (it starts with five dashes): change that line.",
        "ACCT_FILE_NAME_TAKEN": "A file with the name on the request is already in that folder: a new file never replaces one. Choose another name, or replace the file from its source.",
        "ACCT_FILE_BEHIND": "The source @{source} was read at version {read}, but the file is now at {now}: refresh the source first, then ask again.",
        "ACCT_FILE_KIND": "A file of type {kind} cannot be written yet: .md, .txt, .csv, .docx, .pdf, .xlsx, .pptx and Google Docs can.",
        "ACCT_FILE_TYPE": "A {given} cannot replace a {wanted}: give a file of the project of the same type.",
        "ACCT_FILE_SOURCE": "The source @{source} is not a file of your {service} account: only a source added from that account is replaced.",
        "ACCT_FILE_NOT_FILE": "The item is not a file that can be written ({reason}).",
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
LOCALIZED = ("ATT_", "RM_", "ACCT_")      # the families of keys `localize` knows by their English sentence
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


# --- the card of an effect, line by line (package FND) ---------------------------------------------------------------------------------------------------

CARD_FAMILY = re.compile(r"CARD_[A-Z0-9_]{1,40}")
CARD_LINES_MAX = 300        # lines in one card
# The lines that show the CURRENT text of something the person owns (an event's title, place and notes as the service holds them, the message a reply answers) and the lines of an
# e-mail (who it goes to, its subject, its text, the names of its attachments): a messaging app draws them only for a
# sender who also holds the group CARD_PRIVATE_GROUP (the answer from mail and calendar), and a card with such a line left out is not whole, so it is not approved there.
CARD_PRIVATE = tuple(f"CARD_CAL_{prefix}_{word}" for prefix in ("BEFORE", "KEPT", "DROP") for word in ("TITLE", "WHERE", "NOTES")) + ("CARD_CAL_NOW_TITLE", "CARD_FILE_NOW") \
    + ("CARD_MAIL_REPLY_TO", "CARD_MAIL_REPLY_TO_DIFFERS", "CARD_MAIL_IN_REPLY", "CARD_MAIL_SUBJECT_REPLY") \
    + ("CARD_BOX_ITEM", "CARD_BOX_DRAFT_REPLY", "CARD_BOX_DRAFT_REPLY_DIFFERS", "CARD_BOX_DRAFT_REPLY_TO", "CARD_BOX_DRAFT_REPLY_SUBJECT") \
    + ("CARD_BOX_DRAFT_TO", "CARD_BOX_DRAFT_CC", "CARD_BOX_DRAFT_BCC", "CARD_BOX_DRAFT_SUBJECT", "CARD_BOX_DRAFT_TEXT")      # W2: what a reply shows of the message answered; W3: the same of a mailbox card, and who a draft goes to, its subject and its text
CARD_PRIVATE += ("CARD_MAIL_TO", "CARD_MAIL_CC", "CARD_MAIL_BCC", "CARD_MAIL_SUBJECT", "CARD_MAIL_MESSAGE", "CARD_MAIL_ATTACHMENT")      # the maintainer's decision of 2026-10-19: who an e-mail goes to, its subject, its text and the names of its attachments
# W4a: the name of a file a sender sent (CARD_FILE_SAVE) is shown to that sender, who may approve the save, and to a reader of the person's own items, and to no one else: not to the MCP
# mode, not to another messaging sender. (The name of a file the service holds now, CARD_FILE_NOW, is in CARD_PRIVATE above.)
CARD_PRIVATE_OWNER = ("CARD_FILE_SENT", "CARD_FILE_SAVE")
CARD_PRIVATE_GROUP = "ask-mail"
CARD_MULTILINE = ("body", "text", "notes", "content", "change")      # the fields that may hold line ends and tabs (a message, a note, a file's text, a diff); every other field is one line
CARD_REFUSED = ("Cc", "Cf", "Zl", "Zp", "Cs", "Co")      # control, format (a right-to-left override, a zero-width character), line and paragraph separator, surrogate, private use


def _fields_of(sentence: str) -> set:
    return {name for _lit, name, _spec, _conv in string.Formatter().parse(sentence) if name}


def _field_ok(name: str, value: str) -> bool:
    """Whether a field's value can be on a card: no control, format, separator, surrogate or private-use character, except the line end and the tab in a
    field of CARD_MULTILINE. A card with one is no card (a hidden character could make a line say what it does not)."""
    allowed = "\n\t" if name in CARD_MULTILINE else ""
    return all(c in allowed or unicodedata.category(c) not in CARD_REFUSED for c in value)


def card_valid(card) -> bool:
    """Whether `card` is a well-formed card: a non-empty list of at most CARD_LINES_MAX pairs [key, {field: text}], every key of the family `CARD_` and in the
    English table, every field a text with no control, format or separator character (`_field_ok`), and the fields exactly the ones the English sentence of the key has. Anything else (a key outside the family, a field
    that is not a text, a missing or an extra field) is no card, and `text` is never asked about it."""
    if not isinstance(card, (list, tuple)) or not 0 < len(card) <= CARD_LINES_MAX:
        return False
    english = TABLE[DEFAULT]
    for line in card:
        if not isinstance(line, (list, tuple)) or len(line) != 2:
            return False
        key, fields = line
        if not isinstance(key, str) or not CARD_FAMILY.fullmatch(key) or key not in english:
            return False
        if not isinstance(fields, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in fields.items()):
            return False
        if set(fields) != _fields_of(english[key]) or not all(_field_ok(k, v) for k, v in fields.items()):
            return False
    return True


def hidden_note_key(card, kept) -> str:
    """The key of the note that says some lines were left out: the file's when every line left out is a file's line, the e-mail's when every one is a line of an
    e-mail or of the mailbox (CARD_MAIL_, CARD_BOX_: addresses, subjects, text), else the event's."""
    left_out = [line[0] for line in card if line not in kept]
    if left_out and all(key.startswith("CARD_FILE") for key in left_out):
        return "CARD_HIDDEN_NOTE_FILE"
    return "CARD_HIDDEN_NOTE_MAIL" if left_out and all(key.startswith(("CARD_MAIL_", "CARD_BOX_")) for key in left_out) else "CARD_HIDDEN_NOTE"


def card_without_private(card, owner: bool = False) -> list:
    """The lines of a valid card that are not in CARD_PRIVATE and, unless `owner` (the reader sent the held file the card saves), not in CARD_PRIVATE_OWNER."""
    hidden = set(CARD_PRIVATE) | (set() if owner else set(CARD_PRIVATE_OWNER))
    return [line for line in card if line[0] not in hidden]


def card_text(card, cfg=None) -> str:
    """The lines of a valid card (card_valid) said in the project's language and joined by line ends. The values of the fields are the person's or a
    service's own words and are never changed; with `cfg` None the text is English, which is what an effect stores as its body."""
    return "\n".join(text(key, cfg, **fields) for key, fields in card)


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
