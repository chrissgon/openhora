#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Brazilian Portuguese, as a language table of the natural-request engine (package NR-1): the words a person types, as data. A pure literal, no code and no import.

It is the second file in the repository written in Portuguese on purpose (the first is runtime/phrases_pt_br.py): the check that every other file is English
(`english-only`) stays on the engine and on everything else, and this file is listed by name in `.security-scan-allow`. The schema is in runtime/natural_time.py
(`check_table` refuses a table that breaks it); runtime/natural_lang_en.py is the model. The maintainer reviews this table in the pull request that changes it.

Every word is lower case and written WITHOUT accent (the engine folds a line the same way before it looks: "amanha" matches "amanhã", "às" matches "as"), and a
phrase is words separated by one space (a hyphen between two letters is read as a space: "sexta-feira" is "sexta feira", "meio-dia" is "meio dia"). A clock
written with an "h" ("13h", "13hrs", "9h30") is a 24-hour clock in Brazil; an hour with no "h", no ":" and no marker ("as 9") is asked back, 09:00 or 21:00.

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

TABLE = {
    "tag": "pt-BR",
    # only words that are not common in the other languages of the tables (the particles "de", "da", "do", "que" are in every sentence of a name too)
    "markers": ["lembra", "lembre", "lembrete", "lembretes", "avisa", "avise", "hoje", "hj", "amanha", "pra", "pro", "das", "dia", "proxima", "proximo", "daqui",
                "depois", "meu", "meus", "minha", "voce"],
    "slash_dates": "day-first",
    "days": {"today": ["hoje", "hj"], "tomorrow": ["amanha"], "day_after_tomorrow": ["depois de amanha"]},
    "weekdays": [["segunda feira", "2a feira", "segunda", "2a", "seg"], ["terca feira", "3a feira", "terca", "3a"], ["quarta feira", "4a feira", "quarta", "4a", "qua"],
                 ["quinta feira", "5a feira", "quinta", "5a", "qui"], ["sexta feira", "6a feira", "sexta", "6a", "sex"], ["sabado", "sab"], ["domingo"]],
    "weekday_next": ["proxima", "proximo", "na proxima", "no proximo"],
    "weekday_this": ["esta", "este", "nesta", "neste"],
    "weekday_after": ["que vem", "proxima", "proximo"],
    "months": [["janeiro", "jan"], ["fevereiro", "fev"], ["marco", "mar"], ["abril", "abr"], ["maio", "mai"], ["junho", "jun"], ["julho", "jul"],
               ["agosto", "ago"], ["setembro", "set"], ["outubro", "out"], ["novembro", "nov"], ["dezembro", "dez"]],
    "weak": ["seg", "qua", "qui", "sex", "sab", "2a", "3a", "4a", "5a", "6a", "jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"],
    "cued": [],
    "month_joiners": ["de"],
    "day_words": ["dia", "no dia"],
    "ordinal_prefixes": [],
    "ordinal_suffixes": [],
    "prefixes": ["as", "para", "pra", "pro", "no", "na", "em", "dia"],
    "hour_words_24": ["h", "hs", "hr", "hrs"],
    "hour_words_long": ["horas", "hora"],
    "meridiem": {"am": [], "pm": []},
    "dayparts": {"morning": ["da manha", "de manha"], "dawn": ["da madrugada", "de madrugada"], "afternoon": ["da tarde", "de tarde"], "evening": [],
                 "night": ["da noite", "de noite"]},
    "vague": ["mais tarde", "daqui a pouco", "a tarde", "a noite", "de manha", "de tarde", "de noite", "depois"],
    "noon": ["meio dia"],
    "midnight": ["meia noite"],
    "bare_hour_prefixes": ["as", "das", "pelas", "por volta das", "por volta de"],
    "relative_in": ["daqui a", "daqui", "em", "dentro de"],
    "relative_units": {"m": ["minutos", "minuto", "mins", "min"], "h": ["horas", "hora", "hrs", "hr", "h"], "d": ["dias", "dia"], "w": ["semanas", "semana"]},
    "number_words": {"um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "quatro": 4, "cinco": 5, "seis": 6, "sete": 7, "oito": 8, "nove": 9, "dez": 10,
                     "quinze": 15, "vinte": 20, "trinta": 30},
    "half_hour": ["meia hora"],
    "and_half": ["e meia"],
    "joiners": ["e"],
    "half_words": ["meia"],
    "time_words": ["semana", "semanas", "mes", "meses", "ano", "anos", "fim de semana", "final de semana", "fds", "proxima", "proximo", "proximas", "proximos",
                   "vem", "passada", "passado", "toda", "todo", "todas", "todos", "cedo", "tarde", "noite", "madrugada", "manha", "antes", "depois", "ate", "hora",
                   "horas", "minuto", "minutos", "ontem", "feira"],
    "not_typos": ["amanda", "terra", "terco", "tercas", "quarto", "quartos", "quartas", "quintal", "quintas", "quinto", "sextas", "sexto", "segundo", "segundos",
                  "segundas", "domingos", "sabados", "marcos", "marcas", "marca", "abrir", "abriu", "cerca", "junto", "julio", "gosto", "gostos", "maior"],
    "recurrence": ["a cada", "todo dia", "todos os dias", "toda semana", "todas as semanas", "todo mes", "todos os meses", "diariamente", "semanalmente",
                   "mensalmente", "quinzenalmente", "anualmente"],
    "recurrence_before_day": ["toda", "todo", "todas", "todos"],
    "recurrence_joiners": ["em"],
    "fraction_before": ["parcela", "parcelas", "capitulo", "pagina", "paginas", "item", "episodio", "nota", "placar", "passo", "volume", "vol", "rodada", "slide",
                        "questao", "fase", "ep", "cap"],
    "fraction_after": ["de", "do", "da", "dos", "das"],
    "date_cues": ["dia", "em", "no", "ate", "para", "pro", "por", "vence", "vencimento"],
    "edge_words": ["de", "do", "da", "dos", "das", "que", "para", "pra", "pro", "a", "ao", "aos", "as", "e", "ou", "em", "no", "na", "sobre", "por"],
    "problem_words": ["nao", "nunca", "chegou", "chegaram", "funciona", "funcionam", "quebrado", "quebrados", "bug", "erro", "erros", "falha", "falhou", "falhando",
                      "atrasado", "atrasados", "porque", "pq", "errado", "errados", "travou"],
    "work_verbs": ["escreva", "escrever", "crie", "criar", "faca", "fazer", "gere", "gerar", "monte", "montar", "prepare", "preparar", "analise", "analisa", "revise",
                   "revisa", "resuma", "resume", "pesquise", "pesquisa", "procure", "envie", "envia", "mande", "manda", "publique", "planeje", "desenhe",
                   "implemente", "corrija", "verifique", "rode", "mostre", "liste", "diga", "quero", "preciso", "gostaria", "pode", "poderia", "atualize",
                   "apague", "remova"],
    "calendar_noun_reads": ["de", "da", "do", "dos", "das", "para", "hoje", "amanha", "semana", "mes", "completa", "cheia", "lotada"],
    "triggers": {
        "remind": ["me lembra", "me lembre", "me lembrar", "lembre me", "lembra me", "me avisa", "me avise", "me avisar", "lembrete", "cria um lembrete",
                   "crie um lembrete", "criar lembrete", "criar um lembrete", "quero um lembrete", "novo lembrete", "pode me lembrar", "poderia me lembrar"],
        "remind_anywhere": ["me lembra", "me lembre", "me lembrar", "lembre me", "lembra me", "me avisa", "me avise", "me avisar"],
        "reminders": ["meus lembretes", "quais lembretes", "quais sao meus lembretes", "quais sao os lembretes", "lista os lembretes", "liste os lembretes",
                      "lista meus lembretes", "liste meus lembretes", "mostra meus lembretes", "mostre meus lembretes", "mostra os lembretes",
                      "que lembretes"],
        "reminders_bare": ["lembretes"],
        "calendar": ["marca na agenda", "marque na agenda", "marcar na agenda", "coloca na agenda", "coloque na agenda", "colocar na agenda", "agenda para mim",
                     "coloca no calendario", "coloque no calendario", "cria um evento", "crie um evento", "criar um evento", "adiciona na agenda",
                     "adicione na agenda", "poe na agenda", "ponha na agenda"],
        "calendar_verb": ["marca", "marque", "marcar"],
        "calendar_noun": ["agenda", "calendario"],
        "calendar_loose": ["agende", "agendar"],
        "note": ["anote", "anota", "anotar"],
        "undo": ["desfaz", "desfazer", "desfaca", "desfaz isso", "volta o lembrete", "restaura o lembrete", "traz de volta"],
    },
    "forget": {"verbs": ["esquece", "esqueca", "esquecer", "cancela", "cancele", "cancelar", "apaga", "apague", "apagar", "remove", "remova", "tira", "tire"],
              "nouns": ["lembrete"], "fillers": ["o", "a", "meu", "numero", "n", "no", "de", "do"]},
    "polite": ["por favor", "pode", "poderia", "consegue", "oi", "ola", "ei"],
    "connectors": ["de", "do", "da", "que", "para", "pra", "pro", "sobre"],
    "answers": {"yes": ["sim", "s", "isso", "pode", "ok", "certo", "confirma", "confirmo", "claro", "beleza"], "notice": ["lembrete", "aviso", "notificacao"],
                "event": ["evento", "agenda", "calendario", "compromisso"], "other": ["outra coisa", "outro", "outra", "nao", "nada", "nenhum", "nenhuma"],
                "cancel": ["cancela", "cancele", "esquece", "esqueca", "deixa pra la", "deixa para la", "deixa quieto", "deixa", "nao quero"],
                "thanks": ["obrigado", "obrigada", "valeu", "brigado", "brigada"]},
    "work_starters": ["escreva", "escrever", "crie", "criar", "faca", "fazer", "gere", "gerar", "monte", "montar", "prepare", "preparar", "analise", "revise",
                      "resuma", "pesquise", "procure", "envie", "mande", "publique", "planeje", "desenhe", "implemente", "corrija", "verifique", "rode",
                      "mostre", "liste", "diga", "o", "que", "qual", "quais", "como", "quando", "onde", "quem", "por", "porque", "quanto", "quantos", "ha", "tem",
                      "posso", "pode", "deve", "agende", "agendar", "marque"],
}
