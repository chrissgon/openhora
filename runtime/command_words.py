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
  stop_form(line)         whether the whole line is a stop word of the closed lists `STOP_WORDS` (six languages), which stops the sender's own running research (BL2b; the kind `research-run` of runtime/messaging_turn.py)

The lists are closed phrases in the six languages the interpreter reads (pt-BR, en, es, fr, de, it), folded the way tier 1 folds a line (`natural.ascii_normal`). A line is a form
only when it is, whole, polite words, one lead phrase and then at most `NAME_WORDS` words of a name; a longer tail is a request ("usa o projeto como base para planejar a feira") and
is None. The name is never executed: the bridge looks for it among the projects THIS sender is listed in, exactly as the typed `/project` does, and an unknown one is the typed
command's sentence ("No such project"). Nothing here reads a project, a policy or a store.

Standard library only. Runs on Python 3.9: python3 runtime/command_words.py --help
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import natural  # noqa: E402  (the same folder: the folding of a line)

# The closed words of the account question (mail-list-account, limit L65): a whole line, folded (`natural.normal`), that names every account at once, in the six languages; a longer wording
# ("both of them", "all of them") goes to the model. `ACCOUNT_LEADS` are the small words that may stand before ONE name ("o outlook", "from gmail"); "nos" is not one, so "nos dois" goes to the model.
ALL_ACCOUNTS = frozenset(("todas", "todos", "as duas", "os dois", "ambas", "ambos", "all", "both", "las dos", "los dos", "toutes", "tous", "les deux", "alle", "beide", "tutte", "tutti", "entrambe", "entrambi"))
ACCOUNT_LEADS = frozenset("o a os as the el la le il lo der die das do da de del du di no na em en in on of from".split())
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


# The stop words of a research that is running (BL2b moved them here from runtime/plan_confirm.py, which re-exports them: the messaging bridge reads a line with this module and the layer map does not
# let it import that one): the whole line, folded (`natural.ascii_normal`), polite words at its edges taken off. Closed lists by language; a line is a stop when it is in
# the union, since a person may write in any language. The research acknowledgement tells the person to send 'Pare' (pt-BR) or 'Stop' (the other languages): a test of the package
# that owns that text holds its word to be in the list of its language, so a word of the lists here is struck only with that text.
STOP_WORDS = {
    "pt-BR": ("cancela", "cancele", "cancelar", "para", "pare", "parar", "chega", "para a pesquisa", "pare a pesquisa", "cancela a pesquisa", "cancele a pesquisa", "esquece", "deixa pra la"),      # validate: allow english-only -- the stop words of a Portuguese list
    "en": ("stop", "cancel", "stop it", "cancel it", "stop the search", "cancel the search", "never mind", "forget it"),
    "es": ("para", "cancela", "detente", "stop", "cancela la busqueda", "olvidalo"),
    "fr": ("arrete", "annule", "stop", "laisse tomber", "annule la recherche"),
    "de": ("stopp", "stop", "abbrechen", "brich ab", "vergiss es"),
    "it": ("basta", "ferma", "annulla", "stop", "lascia stare"),
}
_STOP = frozenset(word for words in STOP_WORDS.values() for word in words)


def stop_form(line) -> bool:
    """Whether the whole line is a stop word (STOP_WORDS, any language): pure, reads no store."""
    if not isinstance(line, str) or line.lstrip().startswith("/") or "@" in line:
        return False
    flat = _trim(natural.ascii_normal(line))
    return flat in _STOP


def main(argv=None) -> int:
    print(__doc__.strip(), file=sys.stdout if (argv or sys.argv[1:]) in (["--help"], ["-h"]) else sys.stderr)
    return 0 if (argv or sys.argv[1:]) in (["--help"], ["-h"]) else 2


if __name__ == "__main__":
    sys.exit(main())
