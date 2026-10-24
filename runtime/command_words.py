# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The commands of the messaging bridge that are not operations, asked for in words (slice S20): choosing the project the lines go to, a pure reading of one line.

Every other command a messaging sender can type has an operation (runtime/operations.py) and its words are tier 1 (runtime/natural.py, the `requests` of the language tables) or
the interpreter's (runtime/ops_interpret.py). `/project [name]` has none: it is the bridge's own state (which project this sender's lines go to), so its words are here.

  project(line)           {"name": ""} for a line that asks which project the lines go to ("qual projeto estou usando", "which project am I using") or that changes it without naming one
                          ("muda de projeto"), {"name": <the words after the lead phrase>, "weak": False | True} for a line that changes it ("muda para o projeto northwind"; `weak`: the lead
                          may begin a request about something else, so the bridge takes the line only when the name is a project of the sender), else None
  resolve(name, projects) the exact name of the listed project whose name or id is `name` once both are folded (case, accents, punctuation), else None
  vet(line, op, number)   None when a decision or an act that a MODEL or the router chose is believed against the line, else "number" or "again" (slice S20, review round): the line holds
                          that one number and no other (`natural.decision_numbers`). While D5 is not active (`plan_confirm.ACTIVE` False) it also holds the closed verb test: its leading verb
                          is one of the closed verbs of that operation in the six languages, the object it names is the operation's own, and nothing in it is a negation, a condition, a
                          time word or a question. Once D5 is active, what the line means is checked by the person, who is shown the sentence code wrote from the call and says yes (limit
                          L65), so the closed verb lists go (the package that sets `ACTIVE` deletes them). The tier-1 forms are closed phrases that satisfy the verb test by their shape

The lists are closed phrases in the six languages the interpreter reads (pt-BR, en, es, fr, de, it), folded the way tier 1 folds a line (`natural.ascii_normal`). A line is a form
only when it is, whole, polite words, one lead phrase and then at most `NAME_WORDS` words of a name; a longer tail is a request ("usa o projeto como base para planejar a feira") and
is None. The name is never executed: the bridge looks for it among the projects THIS sender is listed in, exactly as the typed `/project` does, and an unknown one is the typed
command's sentence ("No such project"). Nothing here reads a project, a policy or a store.

Standard library only. Runs on Python 3.9: python3 runtime/command_words.py --help
"""
from __future__ import annotations

import importlib
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import natural  # noqa: E402  (the same folder: the folding of a line)

NAME_WORDS = 5          # a longer tail than this is a request, not the name of a project
LEADS = {      # a lead that can only mean "go to this project": a name that is no project of the sender gets the typed command's "No such project"
    "pt-BR": ["muda para o projeto", "mude para o projeto", "muda para projeto", "mude para projeto", "troca para o projeto", "troque para o projeto", "passa para o projeto",
              "passe para o projeto", "vai para o projeto", "ir para o projeto"],
    "en": ["switch to the project", "switch to project", "change to the project", "change to project", "go to the project", "go to project"],
    "es": ["cambia al proyecto", "cambia de proyecto a", "pasa al proyecto", "ve al proyecto"],
    "fr": ["passe au projet", "change de projet pour", "bascule sur le projet", "va au projet"],
    "de": ["wechsle zum projekt", "wechsel zum projekt", "gehe zum projekt", "geh zum projekt"],
    "it": ["passa al progetto", "vai al progetto", "cambia al progetto"],
}
WEAK = {      # a lead that may begin a request about something else ("usa o projeto como base"): a form only when the words after it name a project of the sender
    "pt-BR": ["usa o projeto", "use o projeto", "trabalha no projeto", "trabalhe no projeto"],
    "en": ["use the project", "use project", "work on the project", "work on project", "open the project", "open project", "select the project", "select project", "choose the project",
           "choose project"],
    "es": ["usa el proyecto", "trabaja en el proyecto", "selecciona el proyecto"],
    "fr": ["utilise le projet", "travaille sur le projet", "choisis le projet"],
    "de": ["nutze das projekt", "benutze das projekt", "arbeite am projekt", "waehle das projekt"],
    "it": ["usa il progetto", "lavora sul progetto", "scegli il progetto"],
}
BARE = {      # asks which project, or changes it without naming one: the typed `/project` with no name
    "pt-BR": ["qual projeto", "qual projeto estou usando", "em qual projeto estou", "qual e o projeto", "qual o projeto atual", "quais projetos", "quais projetos eu tenho",
              "muda de projeto", "mude de projeto", "troca de projeto", "troque de projeto", "trocar de projeto", "mudar de projeto"],
    "en": ["which project", "which project am i using", "which project am i in", "what project am i in", "what project am i using", "which projects", "what projects do i have",
           "switch project", "switch projects", "change project", "change projects", "change the project"],
    "es": ["que proyecto estoy usando", "en que proyecto estoy", "cuales proyectos", "cuales son mis proyectos", "cambia de proyecto", "cambiar de proyecto"],
    "fr": ["quel projet", "quel projet j utilise", "dans quel projet suis je", "quels projets", "change de projet", "changer de projet"],
    "de": ["welches projekt", "welches projekt nutze ich", "in welchem projekt bin ich", "welche projekte", "wechsle das projekt", "projekt wechseln"],
    "it": ["quale progetto", "quale progetto sto usando", "in quale progetto sono", "quali progetti", "cambia progetto", "cambiare progetto"],
}
POLITE_BEFORE = ["por favor", "pode", "poderia", "please", "can you", "could you", "would you", "puedes", "podrias", "por favor", "peux tu", "pourrais tu", "s il te plait",
                 "kannst du", "koenntest du", "bitte", "puoi", "potresti", "per favore"]
POLITE_AFTER = ["por favor", "pf", "please", "pls", "bitte", "s il vous plait", "s il te plait", "per favore", "por favor"]
_FORMS = None


def _forms() -> tuple:
    """(the lead phrases as (phrase, weak), the bare phrases, the polite words before, the polite words after), every phrase folded and the longest first."""
    global _FORMS
    if _FORMS is None:
        fold = natural.ascii_normal
        leads = sorted({(fold(p), False) for phrases in LEADS.values() for p in phrases} | {(fold(p), True) for phrases in WEAK.values() for p in phrases},
                       key=lambda p: (-len(p[0]), p))
        bare = {fold(p) for phrases in BARE.values() for p in phrases}
        before = sorted({fold(p) for p in POLITE_BEFORE}, key=lambda p: (-len(p), p))
        after = sorted({fold(p) for p in POLITE_AFTER}, key=lambda p: (-len(p), p))
        _FORMS = (leads, bare, before, after)
    return _FORMS


def _trim(flat: str) -> str:
    """The folded line without the polite words at its edges."""
    _leads, _bare, before, after = _forms()
    changed = True
    while changed:
        changed = False
        for word in before:
            if flat.startswith(word + " "):
                flat, changed = flat[len(word) + 1:], True
        for word in after:
            if flat.endswith(" " + word):
                flat, changed = flat[:-(len(word) + 1)], True
    return flat


def project(line):
    """See the module's text. None for anything that is not, whole, one of the forms (a slash line, an empty line, a line of more than 14 words)."""
    if not isinstance(line, str) or line.lstrip().startswith("/") or "@" in line:
        return None
    flat = _trim(natural.ascii_normal(line))
    if not flat or len(flat.split()) > 14:
        return None
    leads, bare, _before, _after = _forms()
    if flat in bare:
        return {"name": ""}
    for lead, weak in leads:
        if flat == lead:
            return {"name": ""} if not weak else None
        if flat.startswith(lead + " "):
            tail = flat[len(lead) + 1:]
            return {"name": tail, "weak": weak} if len(tail.split()) <= NAME_WORDS else None
    return None


def resolve(name, projects):
    """The exact name of the project, among `projects` (pairs of name and id), whose folded name or folded id is the folded `name`, else None."""
    flat = natural.ascii_normal(name or "")
    if not flat:
        return None
    for found, ident in projects:
        if flat in (natural.ascii_normal(found), natural.ascii_normal(ident)):
            return found
    return None


# --- a decision or an act that a model chose (slice S20, review round) ------------------------------------------------------------------------------------

# The leading verbs of each operation, folded (no accent, lower case), in the six languages of the interpreter. A line is read as the operation only when its FIRST word after the
# polite words is one of these: "devo cancelar o 2" and "se der erro, para a tarefa 3" begin with something else.
VERBS = {
    "reject": "rejeite rejeita rejeitar recuse recusa recusar dispense dispensa dispensar descarte descarta descartar reject decline dismiss discard rechaza rechace rechazar descarta "
              "descartar ignora rejette rejeter refuse refuser ecarte lehne lehn ablehnen verwirf weise respingi respingere rifiuta rifiutare scarta scartare",
    "release": "libera libere liberar release libera liberar libere liberer libere gib gebe freigeben rilascia rilasciare",
    "approve": "aprova aprove aprovar aceita aceite aceitar approve accept aprueba apruebe aprobar acepta approuve approuver accepte genehmige genehmigen akzeptiere approva approvare accetta",
    "cancel": "cancela cancele cancelar cancel anula anule anular cancela annule annuler storniere stornieren annulla annullare cancella",
    "stop-task": "para pare parar interrompe interrompa interromper stop halt deten detene detener arrete arreter stoppe stoppen halte ferma fermare interrompi",
    "retry": "tenta tente tentar refaz refaca refazer retry try reintenta reintenta reintentar intenta reessaie reessayer reessayez wiederhole versuche riprova riprovare ritenta",
    "attachment-add": "adiciona adicione adicionar acrescenta add anade agrega agregar ajoute ajouter fuge fuege aggiungi aggiungere",
    "attachment-discard": "descarta descarte descartar apaga apague discard delete elimina elimine borra jette jeter supprime verwirf verwerfe loesche scarta scartare",
    "routine-pause": "pausa pause pausar suspende suspenda suspend pon mets met suspendre pausiere pausieren metti sospendi",
    "routine-cancel": "cancela cancele cancelar cancel anula annule storniere annulla cancella",
}
# The object each act is about; a decision is named by its number alone.
OBJECT = {"cancel": "request", "stop-task": "task", "retry": "task", "attachment-add": "file", "attachment-discard": "file", "routine-pause": "routine", "routine-cancel": "routine"}
NOUNS = {
    "request": "pedido pedidos solicitacao solicitacoes request requests solicitud solicitudes demande demandes anfrage anfragen richiesta richieste",
    "task": "tarefa tarefas task tasks tarea tareas tache taches aufgabe aufgaben compito compiti",
    "file": "arquivo arquivos anexo anexos file files attachment attachments archivo archivos adjunto adjuntos fichier fichiers piece datei dateien anhang anhange file allegato allegati documento",
    "routine": "rotina rotinas routine routines rutina rutinas routinen",
    "event": "evento eventos reuniao reunioes compromisso compromissos event events meeting meetings appointment appointments reunion cita citas evenement evenements rendez termin termine ereignis riunione appuntamento",
    "reminder": "lembrete lembretes reminder reminders recordatorio recordatorios rappel rappels erinnerung erinnerungen promemoria",
    "mail": "email emails mail mails mensagem mensagens message messages mensaje mensajes correo correos correio courriel courriels nachricht nachrichten messaggio messaggi posta",
}
NEGATION = set("nao no not never nunca jamais sem nem sin ni nicht kein keine keinen nie niemals ne pas non mai nessun nessuna dont cannot cant wont without evita evite evitar".split())
CONTRACTION = set("don doesn didn won can couldn shouldn wouldn isn aren mustn needn".split())      # "don't" is "don t" once folded
CONDITION = set("se caso qualora si if unless falls wenn sofern cas quando when whenever once after before depois antes apos avant apres nachdem vorher dopo prima cuando despues "
                "enquanto while until ate".split())      # a condition or a time: the act is not asked now
LINE_WORDS_MAX = 14      # a longer line is a request, not a command


def _bag(text: str) -> set:
    return set(text.split())


def names(line, op) -> bool:
    """Whether the whole line is the plain command `op` (see `vet`): leading verb, the operation's own object, and none of a negation, a condition, a time word or a question."""
    if not isinstance(line, str) or op not in VERBS or "?" in line or "\uff1f" in line or "@" in line:
        return False
    flat = _trim(natural.ascii_normal(line))
    words = flat.split()
    if not words or len(words) > LINE_WORDS_MAX or words[0] not in _bag(VERBS[op]):
        return False
    rest = words[1:]
    if (_bag(" ".join(NEGATION)) & set(words)) or (CONDITION & set(words)) or any(a in CONTRACTION and b == "t" for a, b in zip(words, words[1:])):
        return False
    wanted = OBJECT.get(op)
    others = [kind for kind in NOUNS if kind != wanted]
    if wanted is not None and not (_bag(NOUNS[wanted]) & set(rest)):
        return False
    return not any(_bag(NOUNS[kind]) & set(rest) for kind in others if not (wanted is None and kind == "request"))


def _active() -> bool:
    """Whether D5 is switched on (runtime/plan_confirm.py `ACTIVE`), read at call time so that this module imports nothing of the operations layer at module level."""
    return bool(importlib.import_module("plan_confirm").ACTIVE)


def vet(line, op, number):
    """None when the decision or act `op` on `number` that a model or the router chose is believed against the person's line; "number" when the line does not hold that one number
    (none, another, or two); "again" when D5 is not active and the line is not the plain command (see the module's text). Pure."""
    if not isinstance(number, int) or isinstance(number, bool) or natural.decision_numbers(line if isinstance(line, str) else "") != [number]:
        return "number"
    if _active():
        return None      # the person checks the meaning on the sentence code wrote from the call (limit L65)
    return None if names(line, op) else "again"


def main(argv=None) -> int:
    print(__doc__.strip(), file=sys.stdout if (argv or sys.argv[1:]) in (["--help"], ["-h"]) else sys.stderr)
    return 0 if (argv or sys.argv[1:]) in (["--help"], ["-h"]) else 2


if __name__ == "__main__":
    sys.exit(main())
