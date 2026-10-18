#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The phrase table (package LR-1): the sentences the runtime says to a person in the project's language, and the one function that picks them.

One table, `TABLE = {"en": {key: text}, "pt-BR": {key: text}}`, a pure literal: no code, no import in it, so that a reviewer reads the
Portuguese column beside the English one. English is the source: each key is the name of the constant it replaced (`STALE`, `QUEUED`,
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

  text(key, cfg, **fields)    the sentence in the project's language, its `{fields}` filled in
  en(key)                     the English sentence, unfilled (what a module keeps as its constant)
  tag(cfg)                    the tag text() uses: the project's, else `en`
  kind_word(kind, cfg)        a decision's kind (`plan`, `effect`...) as a word of the language; the kind itself when the table has none
  heads(key)                  the part of a sentence before its first `[` in every language of the table, for the check of an imitated quote
  localize(sentence, cfg)     an English sentence of a reminder or a file, as an operation raised it, in the project's language; any other text unchanged

Standard library only. Runs on Python 3.9: python3 runtime/phrases.py --help
"""
from __future__ import annotations

import os
import re
import string
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import language  # noqa: E402  (the same folder: the order that decides the tag)

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
        "NOT_NAMED": "The planning agent did not name a flow or a skill for request {request}",
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
        "STATE_RECORDED": "Request {id}, \"{title}\": recorded; it waits for its route.",
        "STATE_PROGRESS": "Request {id}, \"{title}\": {done} of {total} tasks done{names}.",
        "STATE_RUNNING": "Running now: {names}.",
        "STATE_WAITING": "Waiting for you: {names}.",
        "STATE_READY": "Ready: task {id}, \"{title}\"{held}.",
        "STATE_HELD": " (held: {reason})",
        "STATE_STUCK": "Stuck: task {id}, \"{title}\", is {state}{note}.",
        "STATE_BLOCKED": "blocked",
        "STATE_FAILED": "failed",
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
    },
    "pt-BR": {
        # --- the messaging bridge ---
        "STALE": "Este botão não vale mais. Envie /pending.",
        "NO_CARD": "Use o cartão que foi enviado a você (envie /pending).",
        "CHANGED": "Esta decisão mudou desde que você a viu.",
        "STILL_WORKING": "Ainda estou trabalhando na última mensagem.",
        "RUN_BUSY": "O agente de planejamento está respondendo a outro pedido. Envie de novo daqui a pouco.",
        "NOT_ACCEPTED": "A configuração deste projeto não foi aceita: rode accept-config no terminal.",
        "EFFECT_REPLY": "Um efeito é aprovado na página ou no terminal, com o hash dele:",
        "TOO_LONG": "Longo demais para aprovar aqui: aprove na página ou no terminal, com o hash:",
        "WRONG_HASH": "O hash que você digitou não é o do cartão que você viu. Envie /pending.",
        "NOT_OPEN": "A decisão pendente {number} tem o status {status}: não está aberta.",
        "NOT_OFFERED": "Esse cartão não ofereceu uma aprovação. Envie /pending para ver o atual.",
        "REPLY_TO_CARD": "Responda ao cartão desta decisão para agir sobre ela.",
        "UNREAD_ONE": "Uma mensagem enviada a este canal não pôde ser lida e foi deixada de lado: nada foi feito com ela. Se era sua, envie de novo.",
        "UNREAD_MANY": "{n} mensagens enviadas a este canal não puderam ser lidas e foram deixadas de lado: nada foi feito com elas. Se alguma era sua, envie de novo.",
        "QUEUED": "Anotado: respondo a esta mensagem depois da atual.",
        "QUEUE_EXPIRED": "Sem resposta: o projeto ficou ocupado por 30 minutos. Envie de novo.",
        "QUEUE_STOPPED": "Sem resposta: a ponte de mensagens parou. Envie de novo.",
        "NO_REPLY": "(sem resposta)",
        "PROJECT_NOW": "Suas mensagens vão para {name}. Projetos: {projects}.",
        "PROJECT_NONE": "Esse projeto não existe. Projetos: {projects}.",
        "PROJECT_SET": "Suas mensagens agora vão para {name}.",
        "NOTHING_WAITS": "{name}: nada espera por você.",
        "NOTHING_TO_ACT": "{name}: nada espera por uma ação sua.",
        "ANSWERED": "#{id} respondida.",
        "REJECTED": "#{id} rejeitada.",
        "APPROVED": "#{id} aprovada.",
        "RELEASED": "#{id} liberada.",
        "NOT_APPROVABLE": "A decisão pendente {number} é do tipo {kind}: aprovar vale só para um plano ou um aceite.",
        # --- /help and the usage lines ---
        "HELP": ("Comandos:\n/pending            o que espera por você\n/approve <id>       aprova o que o último cartão de <id> mostrou\n"
                 "/reject <id> [note] rejeita\n/release <id>       libera uma entrega\n/answer <id> <text> responde a uma pergunta\n"
                 "/ask <question>     responde a uma pergunta com as fontes do projeto\n"
                 "/add <n>            adiciona como fonte um arquivo que você enviou\n/discard <n>        apaga um arquivo que você enviou\n"
                 "/remind <time> <text> um lembrete enviado a você uma vez (15:00, 2026-10-20 09:30 ou in 2h)\n/reminders          os lembretes que esperam\n"
                 "/forget <n>         cancela um lembrete\n"
                 "/project [name]     escolhe o projeto para onde vão suas mensagens\n/help               esta lista\n"
                 "Qualquer outra linha vai para o agente de planejamento. Quais destes comandos o seu projeto liga está na configuração dele "
                 "(channels.messaging)."),
        "USAGE_APPROVE": "Uso: /approve <id>",
        "USAGE_REJECT": "Uso: /reject <id> [note]",
        "USAGE_RELEASE": "Uso: /release <id>",
        "USAGE_ANSWER": "Uso: /answer <id> <text>",
        "USAGE_ADD": "Uso: /add <n>",
        "USAGE_DISCARD": "Uso: /discard <n>",
        "USAGE_FORGET": "Uso: /forget <n>",
        # --- the card frames ---
        "LABEL_APPROVE": "Aprovar",
        "LABEL_REJECT": "Rejeitar",
        "LABEL_RELEASE": "Liberar",
        "LABEL_ADD": "Adicionar",
        "LABEL_DISCARD": "Descartar",
        "EFFECT_LABEL": "Aprovar este conteúdo exato",
        "PAGE_LABEL": "Abrir a página",
        "CUT": "(continua na página)",
        "WHOLE": "(o texto inteiro segue como documento)",
        "WHOLE_ABOVE": "(o texto inteiro está no arquivo acima)",
        "DOCUMENT_NOTE": "O texto inteiro desta decisão, como arquivo. O cartão com os botões chega depois que este arquivo chegar.",
        "DOCUMENT_LINE": "O arquivo com o texto inteiro não chegou, então este cartão não pode ser aprovado aqui: aprove na página ou no terminal, ou envie /pending para tentar o arquivo de novo.",
        "PAGE_LINE": "Resolva isso na página ou no terminal.",
        "REPLY_LINE": "Responda a esta mensagem para dar a resposta.",
        "EFFECT_LINE": "Aprove na página ou no terminal:",
        "TOO_LONG_LINE": "Longo demais para aprovar aqui: aprove na página ou no terminal.",
        "APPROVES_LINE": "Aprovar aplica exatamente o texto acima (sha256 {sha}).",
        "MORE_LINE": "E mais {n} esperando. Envie /pending para listar.",
        "SEND_LINE": "Envie {line}",
        "HEADER": "{project} · {kind} #{id}",
        "HEADER_FILE": "{project} · arquivo #{id}",
        "WAITS_COUNT": "Aguardando você: {kind}.",
        "ATTACH_ASK": "Arquivo seu enviado por {platform}: {name} ({size}, {kind}).\nAdicionar a {project} como a fonte `{id}`?",
        "ATTACH_ASK_VERSION": "Arquivo seu enviado por {platform}: {name} ({size}, {kind}).\nAdicionar a {project} como a versão {n} da fonte `{id}`?",
        "ATTACH_COUNT": "Um arquivo seu espera pela sua resposta.",
        "A_MESSAGING_APP": "um aplicativo de mensagens",
        "FILE_WORD": "arquivo",
        "KIND_PLAN": "plano",
        "KIND_QUESTION": "pergunta",
        "KIND_REVIEW": "revisão",
        "KIND_EFFECT": "efeito",
        "KIND_ACCEPTANCE": "aceite",
        "KIND_YOUR_DOCUMENT": "documento",
        # --- the files a sender sends ---
        "ATT_OFF": "Arquivos não são recebidos por este aplicativo neste projeto. Adicione na página ou no terminal (source-import).",
        "ATT_NO_FILES": "A conexão deste aplicativo ainda não recebe arquivos.",
        "ATT_MEDIA": "Fotos, notas de voz, vídeos e figurinhas não são aceitos como fontes: envie um PDF, um documento Word, uma planilha, uma apresentação, uma página HTML ou um arquivo de texto.",
        "ATT_TOO_LARGE": "{name} tem {size}; um arquivo deste aplicativo pode ter no máximo {cap}.",
        "ATT_DAY": "Este projeto já recebeu {n} arquivos ({size}) de aplicativos de mensagens hoje, que é o limite. Envie de novo amanhã ou adicione na página.",
        "ATT_HELD_FULL": "{n} arquivos já esperam pela sua resposta. Responda a eles primeiro (/pending).",
        "ATT_GONE": "Esse arquivo não pode mais ser baixado de {platform}. Envie de novo.",
        "ATT_MISMATCH": "{name} declara o tipo {declared}, mas o conteúdo é outro ({sniffed}); por isso não foi aceito.",
        "ATT_REFUSED": "{name} não foi adicionado e foi apagado: {reason}.",
        "ATT_DUPLICATE": "{name} já espera pela sua resposta (arquivo {id}).",
        "ATT_CAPTION_IGNORED": "O texto enviado junto com um arquivo não é lido; envie-o em uma mensagem separada.",
        "ATT_OVER_MESSAGE": "No máximo {n} arquivos são aceitos de uma mensagem; os demais não foram.",
        "ATT_BUSY": "Outro arquivo está sendo baixado. Envie este de novo daqui a pouco.",
        "ATT_FETCH_FAILED": "Não foi possível baixar o arquivo. Envie de novo.",
        "ATT_ADDED": "{name} adicionado como `{id}`, versão {n}.",
        "ATT_ADDED_SAME": "{name} já é a versão mais nova de `{id}` (versão {n}): nada mudou.",
        "ATT_TARGET_TYPE": "`{id}` é uma fonte do tipo {type}: não dá para adicionar um arquivo a ela. Envie o arquivo sem esse texto ou indique uma fonte do tipo file.",
        "ATT_TARGET_CHANGED": "A fonte `{id}` mudou desde que este arquivo chegou. Descarte-o (/discard {n}) e envie de novo.",
        "ATT_DISCARDED": "{name} descartado.",
        "ATT_NOT_HELD": "Esse arquivo tem o status {status}: não está esperando pela sua resposta.",
        "ATT_NO_SUCH": "Não há arquivo {n} esperando por você.",
        "ATT_EXPIRED": "{name} esperou mais de {days} dias e foi apagado. Envie de novo.",
        "ATT_LOST": "O arquivo guardado sumiu desta máquina. Envie de novo.",
        "ATT_KEPT_FAILED": "Não foi possível guardar {name} nesta máquina. Envie de novo daqui a pouco.",
        "ATT_MACHINE": "Esta máquina não conseguiu fazer isso agora. Tente de novo mais tarde ou use a página ou o terminal.",
        "ATT_NOTE": "Nota: {note}",
        "ATT_WAITING_HEAD": "{project}: arquivos esperando pela sua resposta",
        "ATT_WAITING_LINE": "arquivo #{id} {name}: /add {id} ou /discard {id}",
        "ATT_REASON_CREDENTIAL": "contém algo que parece uma credencial",
        "ATT_REASON_SIZE": "o texto é grande demais para uma fonte",
        "ATT_REASON_CONVERT": "não pôde ser lido como documento",
        "ATT_REASON_MACRO": "contém macros, que nunca são convertidas",
        "ATT_REASON_TYPE": "não é um tipo que se leia como fonte",
        "ATT_REASON_CHANGED": "mudou nesta máquina enquanto esperava",
        "ATT_REASON_MISMATCH": "os bytes não são o que ele diz",
        "ATT_REASON_TARGET": "a fonte que ele indica não é uma fonte de arquivo",
        "ATT_SUBTYPE_PDF": "PDF",
        "ATT_SUBTYPE_DOCX": "documento Word",
        "ATT_SUBTYPE_XLSX": "planilha",
        "ATT_SUBTYPE_PPTX": "apresentação",
        "ATT_SUBTYPE_OOXML": "documento do Office",
        "ATT_SUBTYPE_HTML": "página HTML",
        "ATT_SUBTYPE_CSV": "planilha (csv)",
        "ATT_SUBTYPE_TEXT": "arquivo de texto",
        # --- reminders ---
        "RM_USAGE": "Uso: /remind HH:MM <text>, /remind YYYY-MM-DD HH:MM <text> ou /remind in <n>m|h|d <text> (relógio de 24 horas, dois dígitos).",
        "RM_TEXT_LINE": "Lembrete: {text}",
        "RM_COUNT_LINE": "Há um lembrete para agora (#{id}).",
        "RM_COUNT_LATE": " Era para {at}.",
        "RM_TEXT_LATE": " (era para {at})",
        "RM_NO_SUCH": "Não há lembrete {n} esperando por você.",
        "RM_NOT_WAITING": "O lembrete {n} tem o status {status}: não está esperando.",
        "RM_BEING_SENT": "O lembrete {n} está sendo enviado agora.",
        "RM_OPEN_FULL": "Já há {n} lembretes esperando neste projeto. Cancele um primeiro.",
        "RM_CHAT_FULL": "Já há {n} lembretes esperando neste chat. Cancele um primeiro.",
        "RM_DAY_FULL": "Já foram feitos {n} lembretes neste chat hoje. Tente de novo amanhã.",
        "RM_SET": "Lembrete #{id} marcado para {wall} ({zone}).",
        "RM_FORGOT": "Lembrete #{id} cancelado.",
        "RM_NOT_LISTED": "Você não é um remetente listado deste projeto.",
        "RM_NOT_A_TIME": "{given} não é uma hora do dia (00:00 a 23:59).",
        "RM_NO_SUCH_DATE": "{given} não é um dia do calendário.",
        "RM_NO_SUCH_TIME": "{given} não existe nesse dia (o relógio pula esse horário). Escolha outra hora.",
        "RM_PAST": "Esse horário já passou. Agora são {now}.",
        "RM_TOO_SOON": "Um lembrete precisa ser marcado com pelo menos um minuto de antecedência. Agora são {now}.",
        "RM_TOO_FAR": "Um lembrete pode ser marcado com no máximo 366 dias de antecedência.",
        "RM_NO_TEXT": "Um lembrete precisa de um texto para enviar.",
        "RM_TOO_LONG": "Um lembrete tem no máximo {max} caracteres; o seu tem {n}.",
        "RM_CREDENTIAL": "Esse texto parece uma credencial ({labels}); um lembrete é uma mensagem enviada ao seu celular, então não foi guardado.",
        "RM_WHY_LATE": "perdido: já tinham passado mais de 6 horas da hora marcada quando a ponte de mensagens olhou",
        "RM_WHY_SENDER_REMOVED": "não enviado: você não é mais um remetente listado",
        "RM_WHY_NOT_PERMITTED": "não enviado: os lembretes estão desligados para você agora",
        "RM_WHY_OTHER": "não enviado",
        "RM_NONE_WAIT": "nenhum lembrete espera.",
        "RM_WAITING_HEAD": "lembretes que esperam ({zone})",
        "RM_NOT_SENT_HEAD": "Não enviados há pouco:",
        # --- the conversation ---
        "PLAN_NEXT": "Aprove com /approve {pending}",
        "ASK_NEXT": "Responda com uma linha comum ou comece de novo com /new <text>",
        "ANSWERED_AS": "(respondido com base nas fontes: pedido {request})",
        "NOT_NAMED": "O agente de planejamento não indicou um fluxo nem uma skill para o pedido {request}",
        "NOT_NAMED_NEXT": "Cancele com /cancel {request}, indique um fluxo no terminal com: {route}, ou comece de novo com /new <text>",
        "QUEUED_REQUEST": "Registrado como pedido {request}. O agente de planejamento o encaminha quando a execução terminar.",
        "PROPOSES": "O agente de planejamento propõe: ",
        "PLANNING_NOT_STARTED": "O agente de planejamento não pode começar agora: {why}. Nada foi executado.",
        "ROUTER_FAILED": "O roteador não pôde rodar: {failure}",
        "PLAN_ESTIMATE": "Estimativa de execuções: {runs}",
        "PLAN_NOT_PLANNED": "Não planejado {n}: {item}. Resposta do roteador:",
        "PLAN_STEP": "etapa {step}",
        "QUEUE_DEAD_LINE": "Uma mensagem na fila ficou sem resposta: o serviço parou enquanto ela era encaminhada. Envie de novo.",
        "QUEUE_DROPPED_LINE": "Uma mensagem na fila ficou sem resposta: {why}",
        "REQUEST_NOT_ROUTED": "O pedido {id} não foi encaminhado: {why}. Encaminhe de novo quando quiser que ele seja planejado.",
        "QUEUE_DEAD_WHY": "o serviço parou enquanto ele era encaminhado",
        "STATE_RECORDED": "Pedido {id}, \"{title}\": registrado; espera pelo encaminhamento.",
        "STATE_PROGRESS": "Pedido {id}, \"{title}\": {done} de {total} tarefas feitas{names}.",
        "STATE_RUNNING": "Rodando agora: {names}.",
        "STATE_WAITING": "Esperando você: {names}.",
        "STATE_READY": "Pronta: tarefa {id}, \"{title}\"{held}.",
        "STATE_HELD": " (retida: {reason})",
        "STATE_STUCK": "Travada: tarefa {id}, \"{title}\", está {state}{note}.",
        "STATE_BLOCKED": "bloqueada",
        "STATE_FAILED": "com falha",
        "STATE_NONE_OPEN": "Nenhum pedido aberto.",
        "STATE_FINISHED": " Concluídos: {n}.",
        "STATE_WAITS": "O que espera por você: {items}.",
        "STATE_WAIT_ITEM": "{kind} \"{title}\" (decisão {id})",
        "STATE_NOTHING": "nada",
        "NAMES_MORE": " e mais {n}",
        # --- the answer from sources ---
        "NOT_BUILT": "Nenhuma skill desta instalação responde a partir das fontes ainda (asst-answer está planejada).",
        "NO_SOURCES": "Este projeto não tem fonte com versão para responder. Importe uma primeiro.",
        "NO_MATCH": "Nenhuma fonte deste projeto parece tratar disso. Indique uma com @<id>: {ids}.",
        "TOO_MANY": "Uma pergunta lê no máximo {max} fontes, e você indicou {n}.",
        "ASK_TOO_LARGE": "O texto destas fontes é grande demais para uma pergunta (no máximo {kib} KiB no total): {named}. Indique menos fontes ou fontes menores.",
        "SKIPPED": "Não lidas, grandes demais para uma pergunta: {named}.",
        "NOT_STARTED": "O agente {agent} não pode começar agora: {why}. Nada foi executado.",
        "SOURCE_REFUSED": "Não foi possível entregar uma fonte: {why} Nada foi executado.",
        "HAND_CHANGED": ("A versão mais nova de uma fonte desta pergunta é um arquivo que você mudou à mão: ele só é lido por uma pergunta feita no "
                         "terminal. Pergunte lá ou importe um novo arquivo para a fonte. Nada foi executado."),
        "WITHHELD": "A resposta foi retida: você não pode mais perguntar neste canal.",
        "ASK_FAILED": "A execução da resposta falhou ({kind}): {reason}. Nada foi respondido.",
        "ASK_HINT": "Para responder a partir das suas fontes, envie /ask <question>.",
        "ASK_CANCELLED": "A pergunta foi cancelada. Nada foi respondido.",
        "SNAPSHOT_HERE": "Uma caixa de e-mail ou uma agenda só é lida por uma pergunta feita no terminal ou na página: pergunte lá. Nada foi executado.",
        "UNCHECKED": "Esta resposta não está na forma esperada; confira com as fontes.",
        "UNKNOWN_SOURCE": "Esta fonte não foi entregue à execução: {id}.",
        "QUOTE_NOT_FOUND": "Esta citação não está em {id}:",
        "QUOTE_TOO_LONG": "Esta citação tem mais de {max} caracteres e não foi verificada ({id}):",
        "QUOTE_TOO_SHORT": "Esta citação é curta demais para verificar ({id}):",
        "QUOTE_CHECKED": "Citação verificada [{id}]: \"{text}\"",
        "QUOTE_IMITATED": "Uma linha da resposta imitou uma citação verificada e foi retirada.",
        "AFTER_INSTRUCTIONS": "O texto depois da linha de instruções foi retirado.",
        "INSTRUCTION_UNVERIFIED": "Uma instrução encontrada em uma fonte foi retirada: o trecho citado não está nessa fonte.",
        "BIDI_LEFT_OUT": "Uma linha com controles de direção de texto foi retirada.",
        "INSTRUCTION_LINE": "[{id}] \"{passage}\" (não seguida)",
        "UNVERIFIED": "Nenhuma citação desta resposta pôde ser verificada com as fontes; confira você mesmo.",
        "NOT_FOUND": "Não encontrado nas fontes lidas: {read}.",
        "READ": "Lidas: {read}",
        "READ_VERSION": "{source} (versão {version})",
        "UNPROVEN": "Sem prova: {skill} não tem teste aprovado em {model}; confira a resposta com as citações.",
        "INSTRUCTIONS": "Instruções encontradas em conteúdo externo:",
        "EMPTY_REPLY": "(resposta vazia)",
    },
}

DEFAULT = language.DEFAULT
LOCALIZED = ("ATT_", "RM_")      # the families of keys `localize` knows by their English sentence
VALUE_FAMILIES = ("ATT_REASON_", "ATT_SUBTYPE_")      # a field of such a sentence that is itself one of these English words is translated too
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


def kind_word(kind: str, cfg=None) -> str:
    """A decision's kind as a word of the language (`plan`, `effect`, `question`...); the kind as it is when the table has no word for it."""
    key = "KIND_" + str(kind).upper()
    return text(key, cfg) if key in TABLE[DEFAULT] else str(kind)


def heads(key: str) -> list:
    """The part of the sentence of `key` before its first `[`, in every language of the table (whitespace trimmed): the words a model must not
    write at the start of a line (ask_reply.imitates)."""
    return [t[key].split("[", 1)[0].strip() for t in TABLE.values() if key in t]


def _pattern(key: str):
    """The regular expression that matches the English sentence of `key` with any text in its fields (cached)."""
    found = _patterns.get(key)
    if found is None:
        seen, parts = set(), []
        for literal, name, _spec, _conv in string.Formatter().parse(en(key)):
            parts.append(re.escape(literal))
            if name is not None:
                parts.append(f"(?P={name})" if name in seen else f"(?P<{name}>.+?)")
                seen.add(name)
        found = _patterns[key] = re.compile("".join(parts), re.S)
    return found


def localize(sentence, cfg=None):
    """An English sentence that an operation raised for a reminder or a file (the families LOCALIZED), as it is in the project's language; any
    other text, and any text in a project whose language has no table, comes back as it was. The sentence is matched against the English
    template of each key whole (the fields may hold any text), the template with the most fixed words first."""
    if not isinstance(sentence, str) or tag(cfg) not in TABLE or tag(cfg) == DEFAULT:
        return sentence
    keys = sorted((k for k in TABLE[DEFAULT] if k.startswith(LOCALIZED) and not k.startswith(VALUE_FAMILIES)),
                  key=lambda k: -len(re.sub(r"\{[^}]*\}", "", en(k))))
    for key in keys:
        found = _pattern(key).fullmatch(sentence)
        if found:
            words = {en(k): k for k in TABLE[DEFAULT] if k.startswith(VALUE_FAMILIES)}
            return text(key, cfg, **{n: (text(words[v], cfg) if v in words else v) for n, v in found.groupdict().items()})
    return sentence


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
