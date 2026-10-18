#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The table of natural requests (package NR-2): what a line in the person's own words may reach, and the class of each thing.

`CLASSES` is the ONE pure literal that says what a line may do with each operation of runtime/operations.py (and with each planned one): one
line per operation, moved between classes by changing that line and nothing else. `NATURAL` gives each operation its slots, `FORMS` the tier-1 phrase forms
(pt-BR and en; closed lists of words, matched on the whole normalised line) that reach it with no model, and `PLANNED` the effects of the person's accounts
that SPEC-SECRETARY-WRITES builds later. A test walks `operations.OPERATIONS` and fails when an operation has no row, so "everything" stays true as
operations are added (runtime/tests/test_natural_table.py). The dispatcher that executes what was chosen is runtime/ops_natural.py; this file calls
nothing and reads nothing (pure: text in, a choice out).

The classes (contracts/runtime.md, "Natural requests"):

  R  a read: runs at once, checked by the policy as the typed command is
  N  a notice or an own write of the person's (a reminder): runs at once with the reading shown; a slot a router normalised asks first
  W  a confirmed write (cancel, stop, retry, a routine's brakes and edits, a held file): never run from a line; the reply is the exact command to send
     (the package NR-4 replaces that with a card bound to the hash of the exact call)
  D  a decision (approve, reject, release, answer, go ahead): never decided from a line; the reply points to the decision's card, which is sent again
  E  an effect on the person's accounts (planned): never run from a line; until it is built the reply says it is not built yet
  G  gated elsewhere (consent, mode, model, configuration, sources, the instructions, the terminal's own verbs): never run; the reply names the place and the command
  work  the planning agent's own work (say, request, route) and `ask`, which only the router's `Operation: ask` reaches

The two kinds of tier-1 argument are an integer written in the line and nothing else; every other argument a line gives reaches the dispatcher through
the router's `Operation:` outcome and is checked here against the person's line (`check_operation`): a number must be written in the line, a word
(an id, a path) must be a piece of the line as it is written, a text must be a span of the normalised line, and a time is the one slot code cannot check
against the line, so it travels as the typed `When:` line and an operation that receives it asks the person first (contracts/runtime.md, limit L54).

Standard library only. Runs on Python 3.9: python3 runtime/natural.py --help
"""
from __future__ import annotations

import datetime
import re
import sys
import unicodedata

# --- the classes: the one literal ---------------------------------------------------------------------------------------------------------

CLASSES = {
    # R: reads
    "status": "R", "progress": "R", "pending": "R", "task": "R", "agents": "R", "skills": "R", "costs": "R", "artifacts": "R", "artifact": "R",
    "instructions": "R", "routines": "R", "sources": "R", "attachments": "R", "reminders": "R", "flows": "R", "flow-check": "R",
    "connections": "R", "commands": "R",
    # N: a notice and the person's own writes
    "remind": "N", "reminder-forget": "N",
    # W: confirmed writes
    "cancel": "W", "stop-task": "W", "retry": "W", "routine-pause": "W", "routine-cancel": "W", "routine-create": "W", "routine-change": "W",
    "attachment-add": "W", "attachment-discard": "W",
    # D: decisions
    "approve": "D", "reject": "D", "release": "D", "answer": "D", "go-ahead": "D",
    # G: gated elsewhere
    "give-consent": "G", "set-mode": "G", "set-model": "G", "config": "G", "accept-config": "G", "routine-approve": "G", "routine-resume": "G",
    "instructions-set": "G", "instructions-add": "G", "source-add": "G", "source-import": "G", "source-refresh": "G", "source-describe": "G",
    "source-drive": "G", "source-onedrive": "G", "source-mail": "G", "source-calendar": "G", "flow-save": "G", "stage-file": "G", "sync": "G",
    "hand-over": "G", "dispatch": "G", "verdict": "G", "deps": "G", "run-next": "G", "run-task": "G", "run-step": "G", "proof": "G",
    "approve-policy": "G", "revoke-policy": "G", "standing": "G", "execute-under-policy": "G", "contained-run": "G", "poll": "G", "handler": "G",
    "pin": "G", "stop-runs": "G", "service-check": "G", "route-queued": "G", "attachment-hold": "G", "conversation": "G", "version": "G",
    "artifact-raw": "G",
    # work: the planning agent's own work, and the answer from sources
    "say": "work", "request": "work", "route": "work", "ask": "work",
    # E: the effects of SPEC-SECRETARY-WRITES, planned (PLANNED: none of them is an operation yet)
    "calendar-event-create": "E", "calendar-event-change": "E", "calendar-event-cancel": "E", "mail-send": "E", "mail-reply": "E",
    "mail-draft": "E", "mail-organize": "E", "document-create": "E", "document-edit": "E", "document-save": "E",
}

# What is planned and not an operation yet: the key of the phrase that names it. An entry here is removed when the operation exists (a test ties both ways).
PLANNED = ("calendar-event-create", "calendar-event-change", "calendar-event-cancel", "mail-send", "mail-reply", "mail-draft", "mail-organize",
           "document-create", "document-edit", "document-save")

# A slot: "<slot the router writes>": [kind, the parameter of the operation it fills]. Kinds: int (digits written in the line), word (a piece of the line as
# it is written: an id, a path), span (a span of the normalised line: a text), when (the router's normalised time, the typed `When:` line).
NATURAL = {
    "status": {"slots": {}, "what": "where the work stands"},
    "progress": {"slots": {"since": ["word", "since"]}, "what": "what happened lately"},
    "pending": {"slots": {"id": ["int", "pending_id"]}, "what": "what waits for the person; with an id, that decision"},
    "task": {"slots": {"id": ["int", "task_id"]}, "what": "one task or request with its runs"},
    "agents": {"slots": {}, "what": "each area agent and its use of today"},
    "skills": {"slots": {}, "what": "the skills in scope with their proof"},
    "costs": {"slots": {"since": ["word", "since"]}, "what": "the runs by day, agent and model with their cost"},
    "artifacts": {"slots": {}, "what": "the project's files under docs/"},
    "artifact": {"slots": {"path": ["word", "path"]}, "what": "the text of one file under docs/"},
    "instructions": {"slots": {}, "what": "the project's standing instructions"},
    "routines": {"slots": {"id": ["int", "routine_id"]}, "what": "the routines and their state"},
    "sources": {"slots": {}, "what": "the project's sources: what files there are"},
    "attachments": {"slots": {}, "what": "the files people sent through a messaging app"},
    "reminders": {"slots": {}, "what": "the reminders that wait"},
    "flows": {"slots": {}, "what": "the flows the project can run"},
    "flow-check": {"slots": {"flow": ["word", "flow"]}, "what": "the check of one flow"},
    "connections": {"slots": {}, "what": "which provider each requirement class resolves to"},
    "commands": {"slots": {}, "what": "what can be asked and the commands"},
    "remind": {"slots": {"text": ["span", "text"], "when": ["when", "when"]}, "what": "a reminder sent back once at a time"},   # NR-1 owns the forms and the time slot of this row
    "reminder-forget": {"slots": {"id": ["int", "reminder_id"]}, "what": "cancel a reminder that waits"},
    "cancel": {"slots": {"id": ["int", "request_id"]}, "what": "cancel a request"},
    "stop-task": {"slots": {"id": ["int", "task_id"]}, "what": "stop a running task"},
    "retry": {"slots": {"id": ["int", "task_id"]}, "what": "make a failed or blocked task ready again"},
    "routine-pause": {"slots": {"id": ["int", "routine_id"]}, "what": "pause a routine"},
    "routine-cancel": {"slots": {"id": ["int", "routine_id"]}, "what": "cancel a routine"},
    "routine-create": {"slots": {}, "what": "create a routine"},
    "routine-change": {"slots": {"id": ["int", "routine_id"]}, "what": "change a routine"},
    "attachment-add": {"slots": {"id": ["int", "attachment_id"]}, "what": "add a file that was sent as a source"},
    "attachment-discard": {"slots": {"id": ["int", "attachment_id"]}, "what": "delete a file that was sent"},
    "approve": {"slots": {"id": ["int", "pending_id"]}, "what": "approve a plan or an acceptance (from its card)"},
    "reject": {"slots": {"id": ["int", "pending_id"]}, "what": "reject a decision (from its card)"},
    "release": {"slots": {"id": ["int", "pending_id"]}, "what": "release a delivery (from its card)"},
    "answer": {"slots": {"id": ["int", "pending_id"]}, "what": "answer a question a task asked (from its card)"},
    "go-ahead": {"slots": {"id": ["int", "task_id"]}, "what": "go ahead on a task that waits for another request"},
    "give-consent": {"slots": {}, "what": "the consent an autonomous agent needs"},
    "set-mode": {"slots": {}, "what": "move an agent's autonomy mode"},
    "set-model": {"slots": {}, "what": "fix an agent to a model"},
    "config": {"slots": {}, "what": "the configuration and its hash"},
    "accept-config": {"slots": {}, "what": "accept the configuration's hash"},
    "routine-approve": {"slots": {"id": ["int", "routine_id"]}, "what": "approve a routine by its hash"},
    "routine-resume": {"slots": {"id": ["int", "routine_id"]}, "what": "resume a paused routine"},
    "instructions-set": {"slots": {}, "what": "replace the standing instructions"},
    "instructions-add": {"slots": {}, "what": "add a line to the standing instructions"},
    "source-add": {"slots": {}, "what": "register a source"},
    "source-import": {"slots": {}, "what": "import a version of a source"},
    "source-refresh": {"slots": {}, "what": "refresh a source"},
    "source-describe": {"slots": {}, "what": "describe a source"},
    "source-drive": {"slots": {}, "what": "make Drive files sources"},
    "source-onedrive": {"slots": {}, "what": "make OneDrive files sources"},
    "source-mail": {"slots": {}, "what": "a window of the mailbox as a source"},
    "source-calendar": {"slots": {}, "what": "a calendar's window as a source"},
    "flow-save": {"slots": {}, "what": "save an approved plan as a flow"},
    "stage-file": {"slots": {}, "what": "hand a file over for a request's plan"},
    "sync": {"slots": {}, "what": "mirror the tasks and the documents"},
    "hand-over": {"slots": {}, "what": "copy a file into a task's file drop"},
    "dispatch": {"slots": {}, "what": "one round of the dispatcher"},
    "verdict": {"slots": {}, "what": "record a verdict on a run"},
    "deps": {"slots": {}, "what": "install the dependency sets"},
    "run-next": {"slots": {}, "what": "run the next ready task"},
    "run-task": {"slots": {}, "what": "run one named task"},
    "run-step": {"slots": {}, "what": "run one named step task"},
    "proof": {"slots": {}, "what": "the model each skill would run on"},
    "approve-policy": {"slots": {}, "what": "a standing approval of a policy file"},
    "revoke-policy": {"slots": {}, "what": "end a standing approval"},
    "standing": {"slots": {}, "what": "whether a standing approval covers a policy"},
    "execute-under-policy": {"slots": {}, "what": "execute an effect inside a standing approval"},
    "contained-run": {"slots": {}, "what": "run one skill in the container"},
    "poll": {"slots": {}, "what": "the short job"},
    "handler": {"slots": {}, "what": "start one verb of a handler"},
    "pin": {"slots": {}, "what": "write the pin of the dispatcher's jobs"},
    "stop-runs": {"slots": {}, "what": "end the runs this process started"},
    "service-check": {"slots": {}, "what": "what the local service checks at its start"},
    "route-queued": {"slots": {}, "what": "route the oldest queued line"},
    "attachment-hold": {"slots": {}, "what": "the bridge's own call for a file that arrived"},
    "conversation": {"slots": {}, "what": "the messages of the project's conversation"},
    "version": {"slots": {}, "what": "the change signal of the store"},
    "artifact-raw": {"slots": {}, "what": "the bytes of one image under docs/"},
    "say": {"slots": {}, "what": "one turn of the conversation with the planning agent"},
    "request": {"slots": {}, "what": "record what the person wants"},
    "route": {"slots": {}, "what": "plan a request"},
    "ask": {"slots": {}, "what": "answer a question from the text of the project's sources (the question is the person's whole line)"},
    "calendar-event-create": {"slots": {"text": ["span", "text"], "when": ["when", "when"]}, "what": "create a calendar event (planned)"},
    "calendar-event-change": {"slots": {"text": ["span", "text"], "when": ["when", "when"]}, "what": "change a calendar event (planned)"},
    "calendar-event-cancel": {"slots": {"text": ["span", "text"]}, "what": "cancel a calendar event (planned)"},
    "mail-send": {"slots": {"text": ["span", "text"]}, "what": "send an e-mail from the person's account (planned)"},
    "mail-reply": {"slots": {"text": ["span", "text"]}, "what": "reply to an e-mail (planned)"},
    "mail-draft": {"slots": {"text": ["span", "text"]}, "what": "draft an e-mail (planned)"},
    "mail-organize": {"slots": {"text": ["span", "text"]}, "what": "archive, label, move, mark or trash e-mails (planned)"},
    "document-create": {"slots": {"text": ["span", "text"]}, "what": "create a document in the person's drive (planned)"},
    "document-edit": {"slots": {"text": ["span", "text"]}, "what": "edit a document in the person's drive (planned)"},
    "document-save": {"slots": {"text": ["span", "text"]}, "what": "save a document in the person's drive (planned)"},
}

# Tier 1: the forms of a line that reach an operation with no model. Each is matched on the WHOLE line, lower case, no accents, every run of other
# characters one space (`ascii_normal`), in Portuguese and English; a form with a number has the group `n`. A line that matches the forms of two
# operations matches none (it goes to the router). Closed lists: a verb that is not here does not reach an operation.
NUMBER = r"(?P<n>[0-9]{1,9})"
ART = r"(?: (?:o|a|os|as|um|uma|an?|the|meu|minha|my|este|esse|this|that))*"      # the articles and possessives that may stand before a noun
ID_WORDS = r"(?: (?:o|a|the|de|do|da|numero|number|n|id))*(?: (?:plano|pedido|entrega|decisao|pendencia|plan|request|delivery|decision|pending|acceptance|aceite))?(?: (?:o|a|the|de|do|da|numero|number|n|id))*"
FORMS = {
    "pending": (r"pendencias?( para mim)?", r"minhas pendencias", r"o que (tenho|preciso|devo) (para|pra|de) (aprovar|decidir|responder)",  # validate: allow english-only -- Portuguese phrase forms, the closed list of tier-1 forms this file exists to hold
                r"o que espera (por|de) mim", r"what (do i need to|must i|should i|am i supposed to) (approve|decide|answer)", r"my pending( decisions| items)?",
                r"(list|show) (my )?pending( decisions| items)?"),
    "sources": (r"(quais|que) (arquivos|documentos|fontes|planilhas) (voce|vc) tem", r"(quais|que) (sao )?(os |as |meus |minhas )?(arquivos|documentos|fontes)( (que )?(voce|vc) (tem|conhece))?",
                r"(lista|liste|mostra|mostre) (os |as |meus |minhas )?(arquivos|documentos|fontes)", r"(what|which) (files|documents|sources|spreadsheets) do you (have|know)",
                r"(what|which) (are )?(the |my )?(files|documents|sources)( do you have)?", r"(list|show) (me )?(the |my )?(files|documents|sources)"),
    "attachments": (r"(quais|que) (arquivos|anexos) (eu )?(mandei|enviei|enviados|segurando)", r"(meus )?anexos( pendentes)?", r"(what|which) (files|attachments) did i send",
                    r"(list|show) (my )?(attachments|held files)"),
    "artifacts": (r"(lista|liste|mostra|mostre) (os |as )?(artefatos|entregas do projeto|arquivos do projeto)", r"(list|show) (the )?(project )?artifacts"),
    "routines": (r"(quais|que) (sao )?(as |minhas )?rotinas( eu tenho| existem)?", r"(lista|liste|mostra|mostre) (as |minhas )?rotinas( " + NUMBER + r")?",
                 r"(what|which) routines( do i have| exist)?", r"(list|show) (my |the )?routines"),
    "skills": (r"(quais|que) (habilidades|skills) (voce|vc) tem", r"(what|which) skills do you have", r"(list|show) (the )?skills"),
    "agents": (r"(quais|que) (sao )?(os |meus )?agentes( eu tenho| existem)?", r"(what|which) agents( do i have| exist)?", r"(list|show) (the |my )?agents"),
    "costs": (r"(quanto|quanto eu) (gastei|gastamos|custou|custa)( hoje| esta semana| este mes)?", r"(quais|qual) (sao )?(os )?(custos|gastos)( do projeto)?",
              r"how much (did|have) (i|we) (spend|spent)( today| this week| this month)?", r"(what|show) (are )?(the |my )?costs?"),
    "instructions": (r"(quais|que) (sao )?(as )?(minhas )?instrucoes( do projeto| fixas)?", r"(mostra|mostre) (as |minhas )?instrucoes", r"(what|show) (are )?(the |my )?(standing )?instructions"),
    "flows": (r"(quais|que) (sao )?(os )?fluxos( existem| tem)?", r"(lista|liste|mostra|mostre) (os )?fluxos", r"(what|which) flows( are there| exist| do you have)?", r"(list|show) (the )?flows"),
    "connections": (r"(quais|que) (sao )?(as )?conexoes", r"(what|show) (are )?(the )?connections"),
    "task": (r"(como esta|me fala d[oa]|status d[oa]|what about|show) (a |o |the )?(tarefa|task)" + ID_WORDS + " " + NUMBER, r"(tarefa|task)" + ID_WORDS + " " + NUMBER),
    "commands": (r"ajuda", r"help( me)?", r"(que|quais) (comandos|coisas) (voce|vc) (tem|sabe fazer|faz|entende)", r"o que (voce|vc) (sabe|consegue|pode) fazer",
                 r"what can you do", r"what (commands|can i ask)( do you (have|know))?", r"como (eu )?(uso|usar)( isso| voce)?", r"how (do|can) i use (this|you)"),  # validate: allow english-only -- Portuguese phrase forms, the closed list of tier-1 forms this file exists to hold
    "reject": (r"(rejeita|rejeite|rejeitar|recusa|recuse|recusar|reject|decline)" + ID_WORDS + " " + NUMBER,),
    "approve": (r"(aprova|aprove|aprovar|approve|accept|aceita|aceite)" + ID_WORDS + " " + NUMBER,),
    "release": (r"(libera|libere|liberar|release)" + ID_WORDS + " " + NUMBER,),
    "go-ahead": (r"(siga|siga em frente|prossiga|prosseguir|go ahead|proceed)( com| on| with)?( a| the)? (tarefa|task)" + ID_WORDS + " " + NUMBER,),
    "cancel": (r"(cancela|cancele|cancelar|cancel)( o| a| the)? (pedido|request|solicitacao)" + ID_WORDS + " " + NUMBER,),
    "stop-task": (r"(para|pare|parar|stop|interrompe|interrompa)( a| the)? (tarefa|task)" + ID_WORDS + " " + NUMBER,),
    "retry": (r"(tenta|tente|tentar|refaz|refaca|retry|try)( de novo| novamente| again)?( a| the)? (tarefa|task)( de novo| novamente| again)?" + ID_WORDS + " " + NUMBER,),
    "routine-pause": (r"(pausa|pause|pausar)( a| the)? (rotina|routine)" + ID_WORDS + " " + NUMBER,),
    "routine-cancel": (r"(cancela|cancele|cancelar|cancel)( a| the)? (rotina|routine)" + ID_WORDS + " " + NUMBER,),
    "routine-resume": (r"(retoma|retome|retomar|resume)( a| the)? (rotina|routine)" + ID_WORDS + " " + NUMBER,),
    "routine-approve": (r"(aprova|aprove|aprovar|approve)( a| the)? (rotina|routine)" + ID_WORDS + " " + NUMBER,),
    "routine-create": (r"(cria|crie|criar|create|make|set up)( uma| a| an)? (nova )?(rotina|routine)( .*)?",),
    "routine-change": (r"(muda|mude|mudar|altera|altere|change|edit|edite)( a| the)? (rotina|routine)" + ID_WORDS + " " + NUMBER + r"( .*)?",),
    "attachment-add": (r"(adiciona|adicione|adicionar|add)( o| a| the)? (arquivo|anexo|file|attachment)" + ID_WORDS + " " + NUMBER,),
    "attachment-discard": (r"(descarta|descarte|descartar|apaga|apague|discard|delete)( o| a| the)? (arquivo|anexo|file|attachment)" + ID_WORDS + " " + NUMBER,),
    "set-model": (r"(muda|mude|mudar|troca|troque|trocar|altera|altere|change|set|switch)( o| the)? modelo( .*)?", r"(change|set|switch)( the)? model( .*)?"),
    "set-mode": (r"(muda|mude|mudar|troca|troque|altera|altere|change|set|switch)( o| the)? modo( de autonomia)?( .*)?", r"(change|set|switch)( the)? (autonomy )?mode( .*)?"),
    "config": (r"(mostra|mostre|ver|show)( me)?( a| the)? (configuracao|config|configuration)", r"(qual|what) (e |is )?(a |the )?(configuracao|configuration)"),
    "accept-config": (r"(aceita|aceite|aceitar|accept)( a| the)? (configuracao|config|configuration)( .*)?",),
    "give-consent": (r"(dou|dar|da|give)( o| meu| my)? consentimento( .*)?", r"give( my)? consent( .*)?"),
    "instructions-set": (r"(muda|mude|troca|troque|altera|altere|edita|edite|change|replace|edit)( as| minhas| the| my)? instrucoes( .*)?", r"(change|replace|edit)( the| my)?( standing)? instructions( .*)?"),
    "instructions-add": (r"(adiciona|adicione|acrescenta|acrescente|add)( uma| mais uma| an| a)? (instrucao|instruction)( .*)?",),
    "source-add": (r"(adiciona|adicione|registra|registre|cadastra|cadastre|add|register)( uma| um| a| an)? (nova |novo |new )?(fonte|source)( .*)?",),
    "source-import": (r"(importa|importe|importar|import)( uma| um| a| an| o| the)? (versao|version|fonte|source|arquivo|file)( .*)?",),
    "source-refresh": (r"(atualiza|atualize|atualizar|refresh|update)( a| the)? (fonte|source)( .*)?",),
    "source-describe": (r"(descreve|descreva|describe)( a| the)? (fonte|source)( .*)?",),
    "flow-save": (r"(salva|salve|salvar|save)( este| esse| o| this| the)? (plano|fluxo|plan|flow)( .*)?",),
    "sync": (r"(sincroniza|sincronize|sincronizar|sync|synchronize)( os| as| the)?( documentos| tarefas| documents| tasks)?",),
    "dispatch": (r"(dispara|dispare|roda|rode|run|start)( o| the)? (dispatcher|despachante)", r"(dispara|dispare|roda|rode|run|start)( as| the)? tarefas( prontas)?"),
    "run-next": (r"(roda|rode|executa|execute|run)( a| the)? (proxima|next) (tarefa|task)", r"run( the)? next task"),
    "deps": (r"(instala|instale|install)( as| the)? dependencias", r"install( the)? dependencies"),
    "verdict": (r"(registra|registre|record|give)( um| a| my)? (veredito|verdict)( .*)?",),
    "proof": (r"(mostra|mostre|show)( a| the)? (prova|proof)", r"(qual|which) (modelo|model) (cada|each) (skill|habilidade)( usaria| would use)?"),
    # E: the effects on the person's accounts, planned
    "calendar-event-create": (r"(marca|marque|marcar) (na|no|a minha|minha|em minha) (agenda|calendario)( .*)?", r"(agende|agendar|agenda (para|pra) mim)( .*)?",  # validate: allow english-only -- Portuguese phrase forms, the closed list of tier-1 forms this file exists to hold
                              r"(coloca|coloque|colocar|poe|ponha|bota|bote) (na|no|em) (minha |meu )?(agenda|calendario)( .*)?", r"(cria|crie|criar|create) (um |an? )?(evento|event)( .*)?",
                              r"(schedule|book)( .*)?", r"(put|add)( it| this| that)? (on|to|in) my (calendar|agenda)( .*)?"),
    "calendar-event-change": (r"(muda|mude|remarca|remarque|reagenda|reagende|move|mova|reschedule|change|move) (o |a |meu |minha |my |the )?(evento|reuniao|compromisso|event|meeting|appointment)( .*)?",),
    "calendar-event-cancel": (r"(cancela|cancele|cancel|delete) (o |a |meu |minha |my |the )?(evento|reuniao|compromisso|event|meeting|appointment)( .*)?",),
    "mail-send": (r"(manda|mande|mandar|envia|envie|enviar|send)" + ART + r" (e mail|email|mensagem de e mail)( .*)?",),
    "mail-reply": (r"(responde|responda|responder|reply|respond)( ao| a| o| to| the)?( .*)? (e mail|email)( .*)?",),
    "mail-draft": (r"(rascunha|rascunhe|draft)" + ART + r" (e mail|email)( .*)?",),
    "mail-organize": (r"(arquiva|arquive|archive)( .*)?", r"(marca|marque|mark)( .*)? (como lido|as read|como nao lido|as unread)( .*)?", r"(apaga|apague|delete|trash|move|mova)( o| os| a| as| this| the)? (e mail|email|e mails|emails)( .*)?",
                       r"(poe|ponha|coloca|coloque|move|mova|label|rotula|rotule)( .*)? (no|em|para|pra|to|as) (rotulo|pasta|label|folder)( .*)?"),  # validate: allow english-only -- Portuguese phrase forms, the closed list of tier-1 forms this file exists to hold
    "document-create": (r"(cria|crie|criar|create|make|write)" + ART + r" (novo |nova |new )?(documento|doc|document)( .*)?",),
    "document-edit": (r"(edita|edite|editar|altera|altere|edit|update|atualiza|atualize)" + ART + r" (documento|doc|document|cv|curriculo|resume|planilha|spreadsheet)( .*)?",),
    "document-save": (r"(salva|salve|salvar|save)" + ART + r" (documento|doc|document)( .*)?",),
}
_COMPILED = {op: tuple(re.compile(form) for form in forms) for op, forms in FORMS.items()}
LINE_WORDS = 40          # a longer line is a request, not a form

# --- text rules --------------------------------------------------------------------------------------------------------------------------------

WHEN_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}")
WORD_RE = re.compile(r"[^\s]{1,200}")
SPAN_MAX = 300           # characters of a text slot
PRIVATE = ("remind",)    # an operation whose line is the person's private words: the conversation does not store them (limit L51)


def ascii_normal(text: str) -> str:
    """Lower case, no accents, every run of other characters one space (a-z and 0-9 only): the form tier 1 matches on (the rule of ops_say._normal)."""
    plain = "".join(c for c in unicodedata.normalize("NFKD", str(text).lower()) if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", plain).strip()


def normal(text: str) -> str:
    """The rule a text is compared by in any language: compatibility form (full-width digits become digits), case folded, accents removed, every run of
    characters that are neither a letter nor a digit one space. A script with no spaces (Japanese, Chinese) stays one run."""
    plain = "".join(c for c in unicodedata.normalize("NFKD", str(text)).casefold() if not unicodedata.combining(c))
    return re.sub(r"[\W_]+", " ", plain).strip()


def class_of(name: str):
    """The class of an operation, or None when the table has none."""
    return CLASSES.get(name)


def match(line: str):
    """Tier 1: {"op", "args": {parameter: value}, "tier": 1} when the line is one form of exactly one operation, else None. The only argument a form
    gives is the integer written in the line."""
    if not isinstance(line, str) or line.startswith("/") or "@" in line:
        return None
    flat = ascii_normal(line)
    if not flat or len(flat.split()) > LINE_WORDS:
        return None
    found = []
    for op, forms in _COMPILED.items():
        for form in forms:
            hit = form.fullmatch(flat)
            if hit:
                found.append((op, hit))
                break
    if len(found) != 1:
        return None
    op, hit = found[0]
    args = {}
    if "n" in hit.groupdict() and hit.group("n") is not None:
        slot = next((v for v in NATURAL[op]["slots"].values() if v[0] == "int"), None)
        if slot is None:
            return None
        args[slot[1]] = int(hit.group("n"))
    return {"op": op, "args": args, "tier": 1}


def needs(line: str):
    """The operation whose group a messaging sender must hold for this line to be tier 1, or None for a line that is not (it needs the group `talk`, as
    every plain line does): a read or a notice needs its own group, a decision needs to read (`pending`), and the other classes need `talk`."""
    found = match(line)
    if found is None:
        return None
    cls = CLASSES[found["op"]]
    if cls in ("R", "N"):
        return found["op"]
    return "pending" if cls == "D" else None


def private(line: str) -> bool:
    """Whether the line is a tier-1 form of an operation whose words are the person's private ones (a reminder): the conversation stores a neutral word."""
    found = match(line)
    return found is not None and found["op"] in PRIVATE


def _numbers(line: str) -> set:
    return {int(n) for n in re.findall(r"[0-9]+", unicodedata.normalize("NFKC", line)) if len(n) <= 9}


def check_operation(name, slots: dict, when, line) -> dict:
    """Whether the router's `Operation:` outcome can be believed against the person's line, by code only: {"ok": True, "name", "args": {parameter:
    value}, "when": the normalised time or None} or {"ok": False, "why"}. `slots` is {slot: words} from the `Argument <slot>:` lines. The name must be
    in the table and not one of the work operations other than `ask`; a slot must be one the row has and must be of its kind (an integer written in the
    line; a word that is a piece of the line as written; a text that is a span of the normalised line); `when` must have the shape YYYY-MM-DD HH:MM, be
    a date and a time, and belong to a row that has a time slot. Nothing is read from the catalog or the router's other lines."""
    if not isinstance(line, str) or not line.strip():
        return {"ok": False, "why": "an operation is read only for the person's line"}
    if name not in NATURAL or name not in CLASSES:
        return {"ok": False, "why": f"{name!r} is not an operation a line may reach"}
    if CLASSES[name] == "work" and name != "ask":
        return {"ok": False, "why": f"{name!r} is the planning agent's own work, not an operation a line names"}
    row = NATURAL[name]["slots"]
    flat, args = normal(line), {}
    for slot, words in slots.items():
        spec = row.get(slot)
        if spec is None or spec[0] == "when":
            return {"ok": False, "why": f"the operation {name} has no argument {slot!r}"}
        kind, param = spec
        if kind == "int":
            if not (words.isascii() and words.isdigit() and len(words) <= 9) or int(words) not in _numbers(line):
                return {"ok": False, "why": f"the argument {slot!r} is not a number written in the line"}
            args[param] = int(words)
        elif kind == "word":
            if not WORD_RE.fullmatch(words) or words not in unicodedata.normalize("NFKC", line):
                return {"ok": False, "why": f"the argument {slot!r} is not a piece of the line"}
            args[param] = words
        else:
            mine = normal(words)
            if not mine or len(words) > SPAN_MAX or mine not in flat:
                return {"ok": False, "why": f"the argument {slot!r} is not a span of the line"}
            args[param] = words
    if when is not None:
        if "when" not in row:
            return {"ok": False, "why": f"the operation {name} takes no time"}
        if not WHEN_RE.fullmatch(when):
            return {"ok": False, "why": "the When line is not YYYY-MM-DD HH:MM"}
        try:
            datetime.datetime.strptime(when, "%Y-%m-%d %H:%M")
        except ValueError:
            return {"ok": False, "why": "the When line is not a date and a time"}
    return {"ok": True, "name": name, "args": args, "when": when}


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
