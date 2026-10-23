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
  question_lines(reply)       the `Q<n>: ... Recommended: ...` lines of a router reply that asks, and nothing else of its template
  asked_view(reply, cfg)      what a messaging app shows of such a reply: the framing (ROUTER_ASKS_FRAME) in the project's language, then the questions numbered, each with its
                              recommended answer below it (runtime/phone_questions.py)
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
        "NOT_ACCEPTED": "This project's configuration is not accepted yet. Accept it {where}",
        "EFFECT_REPLY": "An effect is approved where its whole text is shown, {where}",
        "TOO_LONG": "Too long to approve here. Approve it {where}",
        "WRONG_HASH": "The hash you typed is not the one of the card you saw. Send /pending.",
        "NOT_OPEN": "Pending decision {number} is {status}, not open.",
        "NOT_OFFERED": "That card did not offer an approval. Send /pending for the current one.",
        "REPLY_TO_CARD": "Reply to the card of this decision to act on it.",
        "FWD_NOT_A_REQUEST": "I don't act on forwarded messages. To ask for something, write it in your own words.",
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
        "HELP": ("Commands:\n\nRequests\n/pending \u2014 what waits for you\n/approve <id> \u2014 approve what the last card of <id> showed\n"
                 "/reject <id> [note] \u2014 reject it, or dismiss a question\n/release <id> \u2014 release a delivery\n/answer <id> <text> \u2014 answer a question\n"
                 "/ask <question> \u2014 answer a question from the project's sources\n\n"
                 "Files\n/add <n> \u2014 add a file you sent as a source\n/discard <n> \u2014 delete a file you sent\n\n"
                 "Reminders\n/remind <time> <text> \u2014 a reminder sent back to you once (15:00, 2026-10-20 09:30 or in 2h)\n/reminders \u2014 the reminders that wait\n"
                 "/forget <n> \u2014 cancel a reminder\n\n"
                 "Project\n/project [name] \u2014 choose the project your lines go to\n/help \u2014 this list\n\n"
                 "Every command above can also be asked for in your own words. Which of these are active depends on your permissions."),
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
        "LABEL_ADD": "Add to project",
        "LABEL_SAVE_GOOGLE": "Save to Google Drive",
        "LABEL_SAVE_MICROSOFT": "Save to OneDrive",
        "LABEL_DISCARD": "Discard",
        "EFFECT_LABEL": "Approve this exact content",
        "PAGE_LABEL": "Open the page",
        "CUT": "(continues on the page)",
        "WHOLE": "(the whole text follows as a document)",
        "WHOLE_ABOVE": "(the whole text is in the file above)",
        "DOCUMENT_NOTE": "The whole text of this decision, as a file. The card with the buttons follows once this file has arrived.",
        "DOCUMENT_LINE": "The file with the whole text did not arrive, so this card cannot be approved here: approve it on the platform's page, or send /pending to try the file again.",
        "PAGE_LINE": "Act on it on the platform's page.",
        "REPLY_LINE": "Reply to this message to answer.",
        "EFFECT_LINE": "Approve it on the platform's page.",
        "TOO_LONG_LINE": "Too long to approve here: approve it on the platform's page.",
        "APPROVES_LINE": "Approving applies exactly the text above.",
        "MORE_LINE": "And {n} more waiting. Send /pending to list them.",
        "SEND_LINE": "Send {line}",
        "HEADER": "{project} · {kind} #{id}",
        "HEADER_FILE": "{project} · file #{id}",
        "WAITS_COUNT": "A {kind} waits for you.",
        "ATTACH_ASK": "File from you on {platform}: {name} ({size}, {kind}).\nAdd it to {project} as the source `{id}`?",
        "ATTACH_ASK_VERSION": "File from you on {platform}: {name} ({size}, {kind}).\nAdd it to {project} as version {n} of the source `{id}`?",
        "ATTACH_COUNT": "A file from you waits for your answer.",
        "ATTACH_WHAT": "I received {name} ({size}, {kind}). What should I do?",
        "ATTACH_WHAT_ADD": "\"Add to project\" makes it a document the assistant can read in {project}, as `{id}`.",
        "ATTACH_WHAT_VERSION": "\"Add to project\" makes it version {n} of the document `{id}`.",
        "ATTACH_TYPED_SAVE_GOOGLE": "To save it, write \"save to Google Drive\".",
        "ATTACH_TYPED_SAVE_MICROSOFT": "To save it, write \"save to OneDrive\".",
        "A_MESSAGING_APP": "a messaging app",
        "FILE_WORD": "file",
        "KIND_PLAN": "plan",
        "KIND_QUESTION": "question",
        "KIND_REVIEW": "review",
        "KIND_EFFECT": "request",
        "KIND_ACCEPTANCE": "acceptance",
        "KIND_YOUR_DOCUMENT": "your_document",
        # --- the files a sender sends (messaging_attach.py, attachments.py) ---
        "ATT_OFF": "Files are not taken from this app for this project. Add it on the platform's page.",
        "ATT_NO_FILES": "This app's connection does not take files yet.",
        "ATT_MEDIA": "Voice notes, videos, audio and stickers are not taken yet, and neither are images other than PNG, JPEG, WebP, GIF or HEIC. Send a photo or an image of those types to save it to Drive or OneDrive, or a PDF, a Word document, a spreadsheet, a presentation, an HTML page or a text file to add it to the project.",
        "ATT_SAVE_OFF": "Saving files to Drive or OneDrive is not turned on for you in this project.",
        "ATT_ACCOUNT_MISSING": "{service} is not set up in this project.",
        "ATT_IMAGE_NOT_SOURCE": "Images are not added to the project; I can save them to Drive or OneDrive.",
        "ATT_TOO_LARGE": "{name} is {size}; a file from this app is at most {cap}.",
        "ATT_DAY": "This project took {n} files ({size}) from messaging apps today, its limit. Send it again tomorrow, or add it on the page.",
        "ATT_HELD_FULL": "{n} files wait for your answer already. Answer them first (/pending).",
        "ATT_GONE": "That file can no longer be fetched from {platform}. Send it again.",
        "ATT_MISMATCH": "{name} says it is a {declared} and its bytes are a {sniffed}, so it was not taken.",
        "ATT_REFUSED": "{name} was not added and was deleted: {reason}.",
        "ATT_DUPLICATE": "{name} already waits for your answer (file {id}).",
        "ATT_CAPTION_IGNORED": "The text sent with a file is read only as a request to save it; use the buttons on its card for anything else.",
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
        "ATT_MACHINE": "This could not be done now. Try again later, or use the platform's page.",
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
        "NT_RECURRING": "A reminder here happens once. Something that repeats is a routine: set it up on the platform's page. For a single reminder, tell me when.",
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
        "ASK_NEXT_PHONE": "Answer in a plain message.",
        "ANSWER_TAKEN": "I took that as the answer to question #{id}.",
        "ROUTER_ASKS_FRAME": "Questions:",
        "ROUTER_QUOTED_NOTE": "The request quoted instructions from external content; they were not followed. See them on the page.",
        # --- the router's questions on a phone (phone_questions.py, slice S9): the labels it says, and the plain names of installed skills and flows ---
        "PQ_LABEL_ROUTE": "Route",
        "PQ_LABEL_WHY": "Why",
        "PQ_LABEL_NEXT": "Next",
        "PQ_LABEL_QUESTION": "Question",
        "PQ_LABEL_RECOMMENDED": "Recommended",
        "PQ_NAME_FLOW_BRAND": "the brand flow",
        "PQ_NAME_FLOW_WEBSITE": "the website flow",
        "PQ_NAME_FLOW_NEW_PROJECT": "the new-project flow",
        "PQ_NAME_FLOW_DESIGN": "the design flow",
        "PQ_NAME_FLOW_FIX_BUG": "the bug-fix flow",
        "PQ_NAME_FLOW_BUILD_FEATURE": "the new-feature flow",
        "PQ_NAME_FLOW_CODE_CHANGE": "the code-change flow",
        "PQ_NAME_FLOW_IMPROVE_CODE": "the code-improvement flow",
        "PQ_NAME_FLOW_MARKET_POSITIONING": "the market-positioning flow",
        "PQ_NAME_FLOW_PUBLISH_POST": "the post-publishing flow",
        "PQ_NAME_FLOW_SEND_EMAIL": "the e-mail flow",
        "PQ_NAME_FLOW_SHORT_VIDEO": "the short-video flow",
        "PQ_NAME_CORE_RESEARCH": "the research",
        "PQ_NAME_CORE_CLARIFY": "the clarification step",
        "PQ_NAME_BRAND_PROFILE": "the brand profile",
        "PQ_NAME_BRAND_NAME": "the name check",
        "PQ_NAME_BRAND_STRATEGY": "the brand strategy",
        "PQ_NAME_BRAND_VOICE": "the brand voice",
        "PQ_NAME_BRAND_IDENTITY": "the visual identity",
        "PQ_NAME_MKT_PUBLISH": "the publishing step",
        "INSTR_PROPOSAL_ASK": "Add this line to the project's instructions?",
        "INSTR_WHERE_SAYS": "or on the page: Building > Instructions",
        "INSTR_WHERE_ELSEWHERE": "accept it on the page (Building > Instructions) or in the terminal",
        "ANSWERED_AS": "(answered from the sources: request {request})",
        "BODY_NOT_NAMED": "The planning agent did not name a flow or a skill for request {request}",
        "NOT_NAMED_NEXT": "Cancel it with /cancel {request}, name a flow in the terminal with: {route}, or start again with /new <text>",
        "NOT_NAMED_NEXT_PHONE": "Cancel it with /cancel {request}, name a flow {where}, or start again with /new <text>",
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
        "NAT_DECISION_CARD": "A decision is approved from its card, never from a line of words: I sent the card of #{id} again so that you see exactly what you approve; approve it with its button, or by saying \"approve\" right after it.",
        "NAT_WHICH_DECISION": "Which decision? Say its number in the same line.",
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
        # --- a phone never reads a command or a path (messaging_guard.py, package LIVE-2): each sentence ends with {where}, which `phone` fills ---
        "PHONE_WHERE": "on the platform's page",
        "PHONE_WHERE_LINK": "on the platform's page: {url}",
        "PHONE_ELSEWHERE": "That is not done from a message. Do it {where}",
        "PHONE_STRIPPED": "The rest is done {where}",
        "PHONE_SETTINGS": "Settings, accounts and permissions are changed {where}",
        "PHONE_SOURCES": "Sources and files are added to the project {where}",
        "PHONE_INSTRUCTIONS": "The project's standing instructions are changed {where}",
        "PHONE_ROUTINES": "A routine is created, changed and approved {where}",
        "PHONE_ACCOUNT_WRITE": "A change to your accounts is made {where}",
        "PHONE_APPROVE_EFFECT": "This is approved where all of its text is shown, {where}",
        "PHONE_EVENT_AGAIN": "I could not read that as a request for your calendar, so nothing was done. Say it again with the day and the time, for example: put the dentist on Thursday at 3 pm.",
        "PHONE_WRITE_AGAIN": "I could not read that as a clear request to your accounts, so nothing was done. Say it again with the details: what, and when or to whom.",
        "PHONE_RESTORE": "Bringing a reminder back, when I am not sure which one you mean, is done {where}",
        "PHONE_NOT_ALLOWED": "You do not have permission for that here yet. It can be enabled {where}",
        # --- why a write to the person's accounts was not made, said to a phone in plain words (messaging_failure.py, package LIVE-2) ---
        "FAIL_SERVICE_FILES_GOOGLE": "Google Drive", "FAIL_SERVICE_FILES_MICROSOFT": "OneDrive",
        "FAIL_SERVICE_MAIL_GOOGLE": "Gmail", "FAIL_SERVICE_MAIL_MICROSOFT": "Outlook",
        "FAIL_SERVICE_ANY": "Your account",
        "FAIL_NOT_AUTHORIZED": "Your {service} account is not connected yet, so nothing was done. Ask again after you connect it {where}",
        "FAIL_FOLDER": "I could not open the folder \"{folder}\" in your {service}. Check that it exists and that its name in the configuration is right.",
        "FAIL_FOLDER_HINT": "On an account set to another language, the default folder usually has that language's name (for example Documents).",
        "FAIL_FILE": "I could not open that file in your {service}. Check that it still exists and that you may write to it.",
        "FAIL_NAME_TAKEN": "A file with that name is already in the folder, and a new file never replaces one. Choose another name.",
        "FAIL_TOO_LARGE": "That is too large to be written there, so nothing was done.",
        "FAIL_QUOTA": "{service} has no room left for it, so nothing was written. Free some space there and ask again.",
        "FAIL_NETWORK": "{service} did not answer, so nothing was done. Try again in a moment.",
        "FAIL_GONE": "That item is no longer there, so nothing was done.",
        "FAIL_REFUSED": "{service} refused it, so nothing was done. Check the details and the permissions of the account.",
        "FAIL_UNKNOWN": "The result is unknown: the service did not confirm whether it was done. Before asking again, look in {place}.",
        "FAIL_LOOK_CALENDAR": "your calendar", "FAIL_LOOK_MAILBOX": "your mailbox", "FAIL_LOOK_FILES": "your drive", "FAIL_LOOK_SENT": "your sent mail",
        "FAIL_LOOK_POST": "the profile", "FAIL_LOOK_ANY": "the service",
        "FAIL_NOT_DONE": "It was not done, and nothing was written. Try again in a moment, or check it {where}",
        # --- the outcome of an approved effect, said to the chat that approved it (messaging_outcome.py, package LIVE-2) ---
        "PHONE_FILE_SAVE": "Saves the file you sent: {name}, {size}.",
        "PHONE_CAL_CHANGE": "Code changes this event after your approval, only if it is still as it is now.",
        "PHONE_CAL_DROP_WHERE": "Where: {location}",
        "PHONE_CAL_DROP_NOTES": "Notes: {notes}",
        "PHONE_MAIL_REPLY_TO": "Reply to: {address}, the sender of message {ref}: {subject}",
        "PHONE_FILE_BASE": "Replaces the version of {modified}.",
        "PHONE_MAIL_ATTACHMENT": "Attachment: {name}, {bytes} bytes",
        "PHONE_BOX_READ_AT": "Nothing is changed unless every message is still as listed.",
        "PHONE_BOX_DRAFT_REPLY": "Reply to: {address}, the sender of the message ({date}, '{subject}')",
        "PHONE_FILE_CODE_REPLACE": "Code writes a new revision of this file after your approval, only if it is still the file as it is now.",
        "PHONE_FILE_CODE_TRASH": "Code moves this file to the trash after your approval, only if it is still the file as it is now, and nothing else.",
        "PHONE_FILE_PROJECT": "A file of the project: {size}. Its content is not on this card.",
        "PHONE_LEDGER_FILE": "a file on this machine",
        "OUT_DONE": "Approved #{id} and carried out.",
        "OUT_REPLAYED": "It had already been done: nothing was repeated.",
        "OUT_CAL_GOOGLE": "Google Calendar",
        "OUT_CAL_MICROSOFT": "Outlook Calendar",
        "OUT_ACCT_GOOGLE": "Google",
        "OUT_ACCT_MICROSOFT": "Microsoft",
        "OUT_CAL_CREATE": "Event created: {title}, {when} ({service}).",
        "OUT_CAL_CREATE_BARE": "Event created ({service}).",
        "OUT_CAL_CHANGE": "Event changed: {title}, {when} ({service}).",
        "OUT_CAL_CHANGE_BARE": "Event changed ({service}).",
        "OUT_CAL_CANCEL": "Event removed ({service}).",
        "OUT_BOX_ARCHIVE": "Archived: {n} message(s).",
        "OUT_BOX_MOVE": "Moved: {n} message(s).",
        "OUT_BOX_READ": "Marked as read: {n} message(s).",
        "OUT_BOX_UNREAD": "Marked as unread: {n} message(s).",
        "OUT_BOX_TRASH": "Moved to the trash: {n} message(s).",
        "OUT_BOX_DRAFT": "Draft saved in your mailbox. It was not sent.",
        "OUT_FILE_CREATE": "File created ({service}).",
        "OUT_FILE_REPLACE": "File updated ({service}).",
        "OUT_FILE_SAVE": "File saved ({service}).",
        "OUT_MAIL_SENT": "E-mail sent.",
        "OUT_MAIL_REPLIED": "Reply sent.",
        # --- the weekday words said on a phone (localize_dates) ---
        "WD_MON": "Mon", "WD_TUE": "Tue", "WD_WED": "Wed", "WD_THU": "Thu", "WD_FRI": "Fri", "WD_SAT": "Sat", "WD_SUN": "Sun",
        "NW_PRIVATE_LINE": "(a request to your accounts)",
        "NW_PRIVATE_REPLY": "(request to your accounts)",
        "NW_CANCELLED": "Nothing was opened.",
        "NW_CHANGE_BY_NUMBER": "To change an event, name its number and the new time, for example: move event 2 to Friday at 3 pm. Ask for your calendar to see the numbers.",
        "NW_GIVE_UP": "I could not tell what you meant, so nothing was opened. Say the request again.",
        "NW_NO_CARDS": "You do not receive cards here: ask on the platform's page.",
        "NW_CARD_NOT_SENT": "Card #{pending} was opened, but it could not be sent to this chat. Approve it on the platform's page, or send /pending.",
        "NW_CHECK_DATE": "Check the date: I understood {when}.",
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
        "NW_ASK_DAY_INVALID": "That date does not exist. Which day is the event?",
        "NW_ASK_END": "The end has to be after the start. At what time does it end?",
        "NW_ASK_EVENT": "Which event? Say its number (ask 'list my events' to see them).",
        "NW_ASK_FILE_NAME": "What is the file name? Give it with its extension (for example notes.md), or say 'google doc'.",
        "NW_ASK_FILE": "Which file do you mean?",
        "NW_ASK_ATTACHMENT": "Which file?",
        "NW_NO_HELD": "I have no file of yours waiting. Send the file and say where to save it.",
        "NW_WHICH_FILE": "Which file? Choose on its card:",
        "NW_PICK_ON_CARD": "Choose where to save it on the file's card:",
        "NW_NO_HELD_KIND": "None of your waiting files is a {kind}. Send it, then ask again.",
        "NW_NO_CALENDAR_SOURCE": "No calendar of yours is a source of this project, so I cannot tell which event you mean.",
        "NW_REF_NOT_READABLE": "Messages and events are numbered in a snapshot of your mailbox or calendar, and this channel may not read it: ask on the platform's page, or have the project's configuration give you the group ask-mail.",
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
        "CARD_CAL_CANCEL_OUTLOOK": "Code removes this event after your approval. Outlook may not keep a copy of a removed event; once approved, it may not be possible to recover it.",
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
        "CARD_HIDDEN_NOTE": "Some of the current text of the event or the message is not shown here: the platform's page shows all of it.",
        "CARD_HIDDEN_NOTE_FILE": "Some of the file's name is not shown here: the platform's page shows all of it.",
        "CARD_HIDDEN_NOTE_MAIL": "Some of the addresses, subjects and text of the e-mail are not shown here: the platform's page shows all of it.",
        "CARD_HIDDEN_NOTE_WHOLE": "The card of this change is not shown here: the platform's page shows it.",
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
        # --- a mail write asked in words (package NR-5b, runtime/ops_natural_mail.py): the questions of a line left open and the refusals of one that can never be answered as asked ---
        "NW_MAIL_NO_SOURCE": "No mail source of your mailbox is registered for this: add one with source-mail first, then ask again.",
        "NW_MAIL_NONE": "No message of the newest snapshot of {source} has all of these words: {words}.",
        "NW_MAIL_TOO_MANY": "One card takes at most {max} messages: name fewer.",
        "NW_MAIL_BY_DATE": "I cannot pick e-mails by date yet: say their numbers (ask for your e-mails to see the list).",
        "NW_MAIL_NO_FORWARD": "I cannot forward an e-mail yet, and '{name}' is not one of your mail folders ({names}). A move goes to one of them.",
        "NW_MAIL_NO_FOLDERS": "No mail folders are set up for the {account} account, so nothing can be moved: the key accounts of runtime.json lists them.",
        "NW_MAIL_ASK_SOURCE": "From which mailbox?",
        "NW_MAIL_ASK_MESSAGE": "I found {count} e-mails. Which one? Answer with its number.",
        "NW_MAIL_ASK_MESSAGES_OVER": "I found {count} e-mails, and one card takes at most {max}. Which ones? Answer with their numbers (the newest {shown} are listed).",
        "NW_MAIL_ASK_TO": "What is the e-mail address of {name}?",
        "NW_MAIL_ASK_SUBJECT": "What is the subject of the e-mail to {to}?",
        "NW_MAIL_ASK_BODY": "What should the e-mail to {to} say?",
        "NW_MAIL_ASK_BODY_REPLY": "What should the reply say?",
        "MC_ASK_BODY": "What should the e-mail to {to} say? I will word the text, and you will see it on the card. To send your words exactly as you write them, start with \"exact text:\".",
        "RV_FAILED": "I could not make that change. Say it another way, or reject the card.",
        "RV_RECIPIENTS": "I cannot change who receives an e-mail by editing its card. Reject this card and ask for a new e-mail to the right person.",
        "RV_NOT_REVISABLE": "To change this card, reject it and ask again.",
        "RV_DONE_MAIL": "Done: here is the e-mail with your change. The previous card no longer works; approve or reject this one.",
        "RV_DONE_EVENT": "Done: here is the event with your change. The previous card no longer works; approve or reject this one.",
        "RV_ALREADY": "The e-mail already says that.",
        "RV_DECIDED": "That card was already decided before I could change it, so nothing was changed.",
        "RV_LOST": "I could not prepare the changed card, and the previous one is closed. Ask again.",
        "RV_REPLACED": "That card was replaced by a newer one. Change the newer card, or ask again.",
        "NW_MAIL_ASK_STATE": "Mark as read or as unread?",
        "NW_MAIL_STATE_READ": "read",
        "NW_MAIL_STATE_UNREAD": "unread",
        # --- a decision card decided by a word (package S2, runtime/card_words.py, limit L64), and a typed table command said as a sentence ---
        "REPLY_WORDS_LINE": "Reply yes to approve or no to decline.",
        "WORD_LIST_HEAD": "More than one decision waits. Say which one by its number, for example \"approve 2\":",
        "WORD_ONE_AT_A_TIME": "I approve one decision at a time. Say which one, for example \"approve 2\".",
        "CMD_CANCELLED": "Request {n} cancelled.",
        "CMD_CANCEL_ALREADY": "Request {n} was already cancelled.",
        "CMD_TASK_STOPPED": "Task {n} stopped.",
        "CMD_TASK_NOT_RUNNING": "Task {n} was not running.",
        "CMD_TASK_RETRY": "Task {n} is ready to run again.",
        "CMD_STATUS": "Open requests: {open}. Waiting for you: {waiting}.",
        "CMD_STATUS_HELD": "Task {n} is held: {reason}.",
        "CMD_ATTACHMENTS": "Files waiting for your answer: {n}.",
        "CMD_DONE": "Done.",
        "CMD_ROUTINE_PAUSED": "Routine {n} paused.",
        "PHONE_ROUTINE_CANCEL": "To stop a routine for now, say \"pause routine\" and its number. A routine is cancelled for good {where}",
        # --- a plain line the interpreter reads (package S1: runtime/ops_interpret.py): fixed sentences, no word of the model is ever shown ---
        "IX_PRIVATE_LINE": "(a message)",
        "IX_NONE": "I did not see a request in that message.",
        # --- the answer to a greeting (package S5: runtime/greeting.py, ops_say._greeting_reply): plain lines, one for each family of capabilities the sender's policy permits ---
        "GREET_HEAD": "Hello! Here is what I can do for you now:",
        "GREET_MAIL": "- read and summarise your e-mails",
        "GREET_REMIND": "- set reminders",
        "GREET_CALENDAR": "- create, change or cancel events on your calendar, after you approve",
        "GREET_SEND": "- draft and send e-mails, each one only after you approve it",
        "GREET_ORGANIZE": "- tidy your mailbox (drafts, archive, move, mark, trash), after you approve",
        "GREET_FILES": "- save files to your Drive or OneDrive, after you approve",
        "GREET_APPROVE": "- approve a card by replying \"approve\" or \"yes\", or refuse it by replying \"no\"",
        "GREET_OWN_WORDS": "- you can ask in your own words, in any of six languages",
        "GREET_ASK_WORK": "- send me a request in a sentence and I will pass it to the planning agent",
        "IX_ASK_TIME": "I am not sure of the day and the time. Say them again, with the day and the hour.",
        "IX_ASK_PAST": "That time has already passed. Say a time that is still ahead.",
        "IX_ASK_FAR": "That is more than a year away. Say a nearer day.",
        "IX_LONG_LINE": "That message is too long for me to read here. Send it in shorter parts.",
        "IX_ASK_AGAIN": "I was not sure what you meant, so I did nothing. Can you say it another way?",
        "IX_ANSWER_ON_QUESTION": "A question is answered by replying to it: write your answer.",
        "IX_WRITE_LANGUAGE": "For now, ask for that in Portuguese or in English.",
        "IX_OUTAGE": "I could not understand that right now. Try again in a few minutes.",
        "IX_CANNOT_EVENT_CREATE": "I understood that you want to create an event, but I could not prepare it. Tell me the title, the day and the time.",
        "IX_CANNOT_WRITE": "I understood that you want to change something in your accounts, but I could not prepare it, so I did nothing. Tell me what it is, which item and when.",
        "EV_NONE": "I did not find that event in your calendar in the next {days} days.",
        "EV_NONE_DAY": "I did not find that event in your calendar on that day.",
        "EV_ASK_DAY": "I could not read the day you mean. Say the event's name and the day, for example: tomorrow or 22/10.",
        "EV_MORE": "...and {k} more. Say the day to narrow it down.",
        "EV_MANY_CANCEL": "More than one event fits. Which one do you want to cancel?",
        "EV_MANY_CANCEL_HOW": "Say, for example: cancel event {n}.",
        "EV_MANY_CHANGE": "More than one event fits. Which one do you want to change?",
        "EV_MANY_CHANGE_HOW": "Say its number and the new time, for example: move event {n} to Friday at 3 pm.",
        "EV_CHANGE_WHAT": "I found the event, but not what to change. Tell me the new day and time, or the new name.",
        "EV_LIST_AGAIN": "That list is out of date, or the number is not clear any more. Tell me the event by its name and day.",
        "EV_LIST_WHAT": "What do you want to do with event {n}? Say, for example: cancel event {n}, or move event {n} to Friday at 3 pm.",
        "EV_ACCOUNT_NONE": "No {service} calendar is set up here, so I did nothing. Name another account, or leave the account out.",
        "NW_ITEMS_OLD": "(list from {time})",
        "NW_ITEMS_ADD_MAIL": "Your mailbox has not been added to this project yet, so there is nothing to list. It is added once, {where}",
        "NW_ITEMS_ADD_MAIL_ACCOUNT": "Your {service} mailbox has not been added to this project yet, so there is nothing to list. It is added once, {where}",
        "NW_ITEMS_ADD_CAL": "Your calendar has not been added to this project yet, so there is nothing to list. It is added once, {where}",
        "NW_ITEMS_ADD_CAL_ACCOUNT": "Your {service} calendar has not been added to this project yet, so there is nothing to list. It is added once, {where}",
        "NW_ITEMS_CMD_MAIL": "Your mailbox has not been added to this project yet. Add it once, in the terminal, then ask again:\n{commands}",
        "NW_ITEMS_CMD_MAIL_ACCOUNT": "Your {service} mailbox has not been added to this project yet. Add it once, in the terminal, then ask again:\n{commands}",
        "NW_ITEMS_CMD_CAL": "Your calendar has not been added to this project yet. Add it once, in the terminal, then ask again:\n{commands}",
        "NW_ITEMS_CMD_CAL_ACCOUNT": "Your {service} calendar has not been added to this project yet. Add it once, in the terminal, then ask again:\n{commands}",
        "NW_ITEMS_NAME_MAIL": "{service} inbox",
        "NW_ITEMS_NAME_CAL": "{service} calendar",
        "NW_ITEMS_HEAD_PHONE": "{name} (read {when}):",
        "NW_ITEMS_WHEN_TODAY": "at {time}",
        "NW_ITEMS_WHEN_DAY": "on {day} at {time}",
        "NW_ITEMS_ALLDAY": "all day",
        "NW_ITEMS_ALLDAY_UNTIL": "all day until {date}",
        "NW_ITEMS_ORG": "organized by {who}",
        "NW_ITEMS_R_ACCEPTED": "you accepted",
        "NW_ITEMS_R_DECLINED": "you declined",
        "NW_ITEMS_R_TENTATIVE": "you said maybe",
        "NW_ITEMS_R_NOANSWER": "no answer from you yet",
        "NW_ITEMS_T_CANCELLED": "cancelled",
        "NW_ITEMS_T_TENTATIVE": "tentative",
        "NW_ITEMS_T_ONLINE": "online meeting",
        "NW_ITEMS_T_RECURRING": "recurring",
        "EV_NONE_NO_SOURCE": "I did not find that event. No calendar of yours is added to this project yet, so I can only find events that I created here. Add your calendar to find the others.",
        "EV_ALLDAY_CLOCK": "That event lasts all day, so I did not change it: a clock time has no length to go with it. Tell me the start and the end, for example: from 10 am to 11 am.",
        "EV_FOUND": "I found: {title}, {when}. Is this the one?",
        "EV_NAME_NONE": "I did not find an event with a similar name in the next {days} days. Ask for your calendar to see the events.",
        "EV_NAME_NONE_DAY": "I did not find an event with a similar name on that day. Ask for your calendar to see the events.",
        "EV_CHECK_FAILED": "I could not check your calendar just now, so I did nothing. Try again in a moment.",
        "NW_ITEMS_HEAD_CHECKED": "{name} (checked {when}):",
        "NW_ITEMS_TODAY": "today",
        "NW_ITEMS_YESTERDAY": "yesterday",
        "NW_ITEMS_PREVIEW": "Start of the text: {text}",
        "NW_ITEMS_STATE_CHECKED": "checked {when}",
        "NW_ITEMS_STATE_READ": "read {when}",
        "NW_ITEMS_NAMEIN_MAIL": "{service} inbox",
        "NW_ITEMS_NAMEIN_CAL": "{service} calendar",
        "NW_ITEMS_EMPTY_MAIL": "No e-mail in the {name} in the last {days} days ({state}).",
        "NW_ITEMS_EMPTY_MAIL_ONE": "No e-mail in the {name} in the last day ({state}).",
        "NW_ITEMS_EMPTY_CAL": "No event in the {name} between {first} and {last} ({state}).",
        "NW_ITEMS_RANGE_HEAD": "Calendar {label}:",
        "NW_ITEMS_RL_TODAY": "for today, {day}",
        "NW_ITEMS_RL_TOMORROW": "for tomorrow, {day}",
        "NW_ITEMS_RL_DAY": "for {day}",
        "NW_ITEMS_RL_WEEK": "for the week, {first} to {last}",
        "NW_ITEMS_EW_TODAY": "today",
        "NW_ITEMS_EW_TOMORROW": "tomorrow",
        "NW_ITEMS_EW_DAY": "on {day}",
        "NW_ITEMS_EW_RANGE": "between {first} and {last}",
        "NW_ITEMS_EMPTY_CAL_AT": "No event in the {name} {when} ({state}).",
        "PHONE_NOT_UNDERSTOOD": "I did not understand the request and started nothing. Can you say it another way?",
        # --- one short acknowledgement when a reply takes time (slice S19: runtime/messaging_ack.py, runtime/line_stage.py): chosen by code from the stage the job had reached ---
        "ACK_GENERIC": "One moment, I am looking into it...",
        "ACK_THINK": "Let me see...",
        "ACK_MAIL": "Let me check your e-mails...",
        "ACK_CALENDAR": "Let me check your calendar...",
        "ACK_FILE": "Looking for the file...",
        "ACK_COMPOSE": "Writing the e-mail...",
        "ACK_CARD": "Preparing the card...",
        "ACK_RESEARCH": "Searching...",
        "ACK_PLAN": "I will work on that...",
        "FR_GOOGLE": "Google Drive",
        "FR_MICROSOFT": "OneDrive",
        "FR_HEAD": "{name} ({account}, folder {folder}):",
        "FR_MORE": "The text continues: {remaining} more characters are not shown.",
        "FR_SEVERAL": "I found {count} files with that name. Which one? Say its full name with the ending, and Google Drive or OneDrive.",
        "FR_ITEM": "{n}. {name} - folder {folder}, {account}",
        "FR_FOLDER": "{folder} ({account})",
        "FR_NONE": "I did not find a file with that name. I looked only in the folders set up for your accounts: {folders}.",
        "FR_PARTIAL": "I could not look through every file of those folders (some hold more files than I can list, or did not answer), so the file may be there.",
        "FR_NO_FOLDERS": "No folder of your Google Drive or OneDrive is set up in this project, so I cannot look for files.",
        "FR_UNAVAILABLE": "I could not look in your folders right now. Try again in a few minutes.",
        "FR_UNREADABLE": "I found {name} ({account}), but I cannot read this kind of file here.",
        "FR_WITHHELD": "I found {name} ({account}), but I did not show it: its text holds something that looks like a password or a key.",
        "FR_TOO_BIG": "I found {name} ({account}), but it is too large for me to read here.",
        "FR_EMPTY": "I found {name} ({account}), but there is no text in it to show.",
        "CONFIG_PENDING": "The project's configuration changed and must be accepted in the terminal before I can go on.",
        "FR_SEVERAL_PICK": "I found {count} files that fit. Which one? Say its number, for example \"the 2\".",
        "FR_NONE_SUB": "I did not find a file with that name. I looked only in the folders set up for your accounts, and the folders inside them: {folders}.",
        "FR_NO_SUCH_FOLDER": "I did not find that folder inside the folders set up for your accounts, and I do not look outside them: {folders}.",
        "FR_CUT": "I stopped looking before the end (the folders are deeper or larger than I search in one go), so the file may be further in.",
        "FR_INCOMPLETE": "I did not look through everything (the folders are deeper or larger than I search in one go, or one did not answer), so another file may fit as well.",
        "FR_SEVERAL_NAME": "I found {count} files that fit. Which one? Write its full name, or say the folder or the account it is in.",
        "FR_FOLDER_MISSING": "I did not find the folder \"{folder}\"; I looked in all your folders.",
        "FR_DRIVE_ROOT": "My Drive",
        "FS_SENT": "Here is {name} ({account}, folder {folder}).",
        "FS_WITHHELD": "I found {name} ({account}), but I will not send it here: the file seems to hold a password or a key.",
        "FS_TOO_BIG": "I found {name} ({account}), but it is too big to send here.",
        "FS_KIND": "I found {name} ({account}), but I cannot send this kind of file here.",
        "FS_NOT_SENT": "The file did not arrive. Try again in a few minutes.",
        "FS_RIGHT_CHANGED": "I did not send the file: what you may receive here changed after you asked.",
        "FS_FILE": "Here is the file {name} ({account}, folder {folder}).",
        "FS_FILE_ACCOUNT": "Here is the file {name} ({account}).",
        "FR_HEAD_ACCOUNT": "{name} ({account}):",
        "FR_ITEM_ACCOUNT": "{n}. {name} - {account}",
        "TITLE_FILE_TRASH": "Files: move a file to the trash",
        "CARD_FILE_CODE_TRASH": "Code moves this file to the trash after your approval, only if it is still the file as read at {read_at}, and nothing else.",
        "CARD_FILE_FOUND": "Found: {name} in {folder}. Is this the one?",
        "CARD_FILE_TRASH_SIZE": "Size: {size}",
        "CARD_FILE_TRASH_MODIFIED": "Last changed: {modified}",
        "CARD_FILE_TRASH_DRIVE": "Goes to the Google Drive trash (recoverable for about 30 days)",
        "CARD_FILE_TRASH_ONEDRIVE": "Goes to the OneDrive trash (recoverable while it is in the trash)",
        "ACCT_TRASH_NOT_GRANTED": "The file is not inside a folder this project lists for your account, so it is not moved to the trash.",
        "ACCT_TRASH_UNPROVEN": "I could not look through the folders to the end, so I cannot show that the file is inside a folder this project lists, and it is not moved to the trash.",
        "ACCT_TRASH_NOT_OWNED": "The file is not owned by your {service} account (it is shared with you, or it belongs to another drive): only a file the account owns is moved to the trash.",
        "ACCT_TRASH_NOT_FILE": "The item cannot be moved to the trash as a file ({reason}).",
        "FT_SEVERAL_PICK": "I found {count} files that fit. Which one goes to the trash? Say its number, for example \"the 2\".",
        "QUESTION_DISMISSED": "Question #{id} dismissed.",
        "PEND_QUESTION": "#{id} question from the assistant: {text}",
        "PEND_NOT_UNDERSTOOD": "#{id} request not understood",
        "PEND_DISMISS_TYPED": "To dismiss one, reply: /reject <number>.",
        "PEND_DISMISS_REPLY": "To dismiss one, reply to its message with: /reject <number>.",
        "NO_SUCH_DECISION": "I did not find decision {number}.",
        "NOT_ANSWERABLE": "Pending decision {number} is a {kind}: it is approved or rejected, not answered.",
        "NOT_RELEASABLE": "Pending decision {number} is a {kind}: it is answered, not released.",
        "NOT_REJECTABLE": "Pending decision {number} is a {kind}: reject takes a plan, an acceptance, an effect or a question.",
        "QUESTION_HAS_COMPANY": "Question {number} was not dismissed: its request still has other decisions open.",
        "PHONE_USE_CARD": "Use the card's button, or send /approve <id> as the whole line.",
        "PHONE_FAILED": "I could not finish that. Try again; if it keeps failing, see what happened {where}",
        "PHONE_ROUTER_FAILED": "I could not look at your request right now. Try again in a few minutes.",
        "PHONE_NOT_PLANNED": "Not planned {n}: {item}.",
        "NOT_OPEN_DONE": "Request #{number} was already {status}.",
        "PHONE_NO_FILE_DELETE": "I cannot delete files from a message yet. You can delete it in Google Drive or OneDrive.",
        "PEND_CARD_TITLE": "Question from the assistant",
        "PEND_NOT_UNDERSTOOD_TITLE": "Request not understood",
        # --- a question of general information answered by a web search (slice R2-F1: runtime/ops_research.py, runtime/research_reply.py) ---
        "RS_SOURCES": "Sources:",
        "RS_NO_LINKS": "I could not attach the sources.",
        "RS_UNPROVEN": "This search has not passed a full test on this model yet, so check the sources before relying on it.",
        "RS_ESTIMATE": "estimate",
        "RS_OPINION": "opinion",
        "RS_LOW": "not very sure",
        "RS_NO_WEB": "I cannot search the web right now.",
        "RS_NOTHING": "I searched but did not find a reliable answer to that.",
        "RS_ASK_AGAIN": "I could not tell what to look up. Can you write the question with more detail (a place, a date, a name)?",
        "RS_TIMEOUT": "The search took too long and was stopped.",
        "RS_CAP": "The search reached its cost limit and was stopped.",
        "RS_FAILED": "I could not do the search right now. Try again in a few minutes.",
        "RS_LIMIT": "I already did {count} searches today, which is the limit for a day.",
        "RS_LIMIT_ONE": "I already did 1 search today, which is the limit for a day.",
        "RS_BUSY": "I am already searching another question; try again in a moment.",
        "RS_STORED": "(answered by a web search)",
        "RS_NOT_BUILT": "Searching the web is not available in this installation.",
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


WEEKDAY_KEYS = ("WD_MON", "WD_TUE", "WD_WED", "WD_THU", "WD_FRI", "WD_SAT", "WD_SUN")
_DATE_WEEKDAY = re.compile(r"\b(Mon|Tue|Wed|Thu|Fri|Sat|Sun)(?= \d{2}/\d{2}/\d{4}\b)")
_DATE_RANGE = re.compile(r"(?<=\d{4} \d{2}:\d{2})-(?=\d{2}:\d{2}\b)")


def localize_dates(said, cfg=None):
    """The dates of a sentence rendered for a phone in the project's language: the English weekday abbreviation that the operations layer writes before a date
    (`Wed 21/10/2026 13:00-14:00`) as the language's word (`qua`), and the hyphen of a time range after a date as an en dash. Only that exact shape is read, so a word of a
    person's text that happens to be `Wed` elsewhere is not touched; English and a language with no table are unchanged. Rendering only: the stored card, its hash and the
    approval are of the stored text."""
    if not isinstance(said, str) or tag(cfg) not in TABLE or tag(cfg) == DEFAULT:
        return said
    words = dict(zip(("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"), (text(k, cfg) for k in WEEKDAY_KEYS)))
    return _DATE_RANGE.sub("\u2013", _DATE_WEEKDAY.sub(lambda m: words[m.group(1)], said))


def where_page(cfg=None) -> str:
    """Where a phone is sent for what it cannot do: "on the platform's page: <link>" in the project's language when the project has a `messaging.page_url` (in `cfg` as
    `page_url`, or under `messaging`), else "on the platform's page". No terminal and no path is ever named to a phone."""
    url = None
    if cfg:
        url = cfg.get("page_url") or (cfg.get("messaging") or {}).get("page_url")
    return text("PHONE_WHERE_LINK", cfg, url=url) if isinstance(url, str) and url else text("PHONE_WHERE", cfg)


def phone(key: str, cfg=None, **fields) -> str:
    """A sentence of the phone's family (PHONE_*, and the keys that end with {where}) with the place filled in (`where_page`); a full stop closes it unless the place is a
    link (a stop after a link would be part of it). A sentence that does not end with the place is as it is."""
    where = where_page(cfg)
    said = text(key, cfg, where=where, **fields)
    return said + "." if said.endswith(where) and "://" not in where else said


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


QUESTION_LINE = re.compile(r"^(?:Next: )?Q[0-9]+: ")      # the same shape as router.QUESTION_RE (a test compares the two); this module imports no sibling that reads the router


# A line that opens a field of the router's template (core-orchestrator): it ends the question before it. A `Recommended:` line is not one: it belongs to the last question.
FIELD_LINE = re.compile(r"^\s*\**(?:Route|Why|Context|Requirements|Sources|Autonomy|Assumptions|Next)\**:", re.I)
RECOMMENDED_LINE = re.compile(r"^\s*\**Recommended\**:", re.I)
# The heading of the section of instructions found in external content, with an optional markdown heading mark or list marker before it.
EXTERNAL_HEADING = re.compile(r"^\s*(?:#+\s*)?(?:[-*]\s+)?\**Instructions found in external content\**:?\**\s*(.*)$", re.I)


def _none_word(value: str) -> str:
    """The value on the section's heading line as one word: `none` for none, `(none)`, `None found.` and `n/a`; "" when empty; else the text."""
    one = " ".join(re.sub(r"[*().]", " ", value).lower().split())
    one = " ".join(w for w in one.split() if w != "found")
    return "none" if one in ("none", "n/a") else one


def _number(line: str) -> int:
    """The n of a `Q<n>: ` line (the label `Next: ` allowed before it)."""
    return int(re.match(r"^(?:Next: )?Q([0-9]+): ", line).group(1))


def read_question(reply) -> dict:
    """What a router reply that asks holds: {"questions": [...], "quoted": bool}. A question is its `Q<n>: <question>` line and the non-blank lines that follow it
    (a wrapped line) up to the next question, the next field of the template or a blank line; a `Recommended:` line belongs to the last question and to no question after a
    field of the template (a field line ends the attachment); the label `Next: ` of a question written on the template's `Next:` line is dropped, and a question written twice
    is listed once.

    The section of instructions found in external content is skipped, and only it. Its heading and the non-blank lines directly under it are never read, so a `Q<n>:` line
    there is never the router's question. The section lasts until the next field of the template; inside it a `Q<n>:` line is a question of the router only when ALL of
    these hold (the template puts the router's closing questions after the section, `core-orchestrator`): the line follows a blank line or the question before it, and its number is
    exactly one more than the last question read (Q1 when none was): an injected `Q9:` after a blank line inside the section, or a question that repeats a number, is skipped.
    A question that passes is still the router's own to the extent code can tell: the section's note (`quoted`, ROUTER_QUOTED_NOTE) tells the person that the reply quoted
    instructions. `quoted` is true when the section holds anything other than a `none` word (text after the heading, lines directly under it, or, under an empty heading,
    content before the first question or field)."""
    lines = [line.rstrip() for line in (reply or "").splitlines()]
    questions, current, last, quoted, at, section, count = {}, None, None, False, 0, False, 0
    blank = True
    while at < len(lines):
        line, at = lines[at], at + 1
        heading = EXTERNAL_HEADING.match(line)
        if heading:
            value, block = _none_word(heading.group(1)), []
            while at < len(lines) and lines[at].strip():
                block.append(lines[at])
                at += 1
            if value not in ("", "none") or (block and (value == "" or any(QUESTION_LINE.match(b) for b in block))):
                quoted = True
            elif value == "" and not block:      # an empty heading: what follows a blank line is the section unless it is a question or a field
                after = next((x for x in lines[at:] if x.strip()), None)
                quoted = quoted or (after is not None and not QUESTION_LINE.match(after) and not FIELD_LINE.match(after))
            current = last = None
            section, blank = True, False
        elif QUESTION_LINE.match(line):
            if section and not ((blank or current is not None) and _number(line) == count + 1):      # inside the section only the next question in order, after a blank line or a question
                current = None
                blank = False
                continue
            current = last = line[len("Next: "):] if line.startswith("Next: ") else line
            if current not in questions:
                questions[current] = [current]
            count = _number(line)
            blank = False
        elif RECOMMENDED_LINE.match(line) and last is not None:
            questions[last].append(line.strip())
            current = last
            blank = False
        elif not line.strip() or FIELD_LINE.match(line):
            current = None
            blank = not line.strip()
            if FIELD_LINE.match(line):
                last = None      # a `Recommended:` line after a field of the template is the field's, never the last question's
                section = False
        else:
            blank = False
            if current is not None:
                questions[current].append(line.strip())
    return {"questions": ["\n".join(parts) for parts in questions.values()], "quoted": quoted}


def question_lines(reply) -> list:
    """The questions of a router reply that asks, each as `Q<n>: <question>` with its `Recommended: ...` line (read_question). Nothing else of the reply is in the
    list: not the route line, the why, the context, the requirements, the sources, the autonomy, the assumptions or the section of instructions found in external
    content. An empty list for a reply that asks nothing."""
    return read_question(reply)["questions"]


def asked_view(reply, cfg=None) -> str:
    """What a messaging app shows of a router reply that asks (runtime/phone_questions.py, slice S9): the numbered questions under the framing in the project's language
    (`cfg` maps `language`), each with its recommended answer on the line below, one blank line between the items, and, when the section of instructions found in external
    content is not `none`, one line saying so (ROUTER_QUOTED_NOTE). A reply with no question that can be read comes back cleaned, not guessed: no code fence, the router's
    labels and the names of skills and flows said plainly. The page and the terminal show the reply whole; a phone shows the questions."""
    import phone_questions      # imported here: that module reads this one's table
    return phone_questions.view(reply, cfg)


def is_router_question(item) -> bool:
    """Whether a decision is the question the router asked about a request (ops._route_run writes it whole: the kind `question`, the title "The router asks" and
    the ending `question`). A messaging app shows such a question as the question alone, in the reply and on the card, by this one test."""
    payload = item.get("payload") if isinstance(item, dict) else None
    return isinstance(item, dict) and item.get("kind") == "question" and item.get("title") == en("TITLE_ROUTER_ASKS") \
        and isinstance(payload, dict) and payload.get("ending") == "question"


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
