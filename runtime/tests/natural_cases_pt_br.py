"""The Brazilian Portuguese lines of the tests of natural requests (package NR-1), as data: what a person types and what the platform must make of it. Not a test file.

It is the one test file written in Portuguese on purpose (listed by name in .security-scan-allow, like runtime/phrases_pt_br.py): the tests that use it are English.
Every name is invented. The clock of the parser cases is Thursday 2026-10-22 14:00 at -03:00 (BRT); the clock of the bridge cases is Sunday 2026-10-18 14:00 at -03:00.

An expectation of a parser case is one of:  "<when>"  the one reading, in the grammar of runtime/reminders.py;  ("ask", [<when>, ...])  every reading offered;
"missing"  a day or a vague time and no hour;  None  no time phrase.
"""
from __future__ import annotations

PARSER_CLOCK = "2026-10-22 14:00"      # a Thursday

PARSER_CASES = [
    # the clock, 24-hour: an "h" is a 24-hour clock in Brazil
    ("corte de cabelo as 13hrs amanha", "2026-10-23 13:00"),
    ("amanhã às 13h", "2026-10-23 13:00"),
    ("amanha 13h30", "2026-10-23 13:30"),
    ("13h", "13:00"),
    ("13 hrs", "13:00"),
    ("13hs", "13:00"),
    ("9h", "09:00"),
    ("21h", "21:00"),
    ("13:00", "13:00"),
    ("9:30", "09:30"),
    ("09:00", "09:00"),
    ("às 13 horas", "13:00"),
    ("às 15", "15:00"),
    ("às 12", "12:00"),
    # an hour with no "h", no ":" and no marker is asked back
    ("às 9", ("ask", ["09:00", "21:00"])),
    ("as 3", ("ask", ["03:00", "15:00"])),
    ("às 9 horas", ("ask", ["09:00", "21:00"])),
    ("sexta às 9", ("ask", ["2026-10-23 09:00", "2026-10-23 21:00"])),
    ("sexta às 9h", "2026-10-23 09:00"),
    # 12-hour clocks, noon and midnight
    ("meio-dia", "12:00"),
    ("amanhã meio-dia", "2026-10-23 12:00"),
    ("meia-noite", "00:00"),
    ("9 da manhã", "09:00"),
    ("3 da tarde", "15:00"),
    ("9 da noite", "21:00"),
    ("3 da madrugada", "03:00"),
    # days
    ("hoje às 18h", "2026-10-22 18:00"),
    ("hoje 13h", "2026-10-22 13:00"),
    ("depois de amanhã às 8h", "2026-10-24 08:00"),
    ("depois de amanha 9h30", "2026-10-24 09:30"),
    # weekdays: the same weekday is today when the time is still ahead, else in 7 days; "next" is never today
    ("sexta-feira 14h", "2026-10-23 14:00"),
    ("quinta 15h", "2026-10-22 15:00"),
    ("quinta 13h", "2026-10-29 13:00"),
    ("próxima quinta às 10h", "2026-10-29 10:00"),
    ("próxima sexta 10h", "2026-10-23 10:00"),
    ("segunda às 10h", "2026-10-26 10:00"),
    ("sábado 10h", "2026-10-24 10:00"),
    ("domingo às 20h", "2026-10-25 20:00"),
    ("na quarta às 8h", "2026-10-28 08:00"),
    # day of the month and dates
    ("dia 25 às 8h", "2026-10-25 08:00"),
    ("dia 10 às 8h", "2026-11-10 08:00"),
    ("dia 22 às 15h", "2026-10-22 15:00"),
    ("dia 22 às 13h", "2026-11-22 13:00"),
    ("25/10 às 10h", "2026-10-25 10:00"),
    ("25/10/2027 10h", "2027-10-25 10:00"),
    ("5/11 9h", "2026-11-05 09:00"),
    ("2026-10-25 08:00", "2026-10-25 08:00"),
    ("25 de outubro às 14h", "2026-10-25 14:00"),
    ("5 de janeiro 9h", "2027-01-05 09:00"),
    ("30/02 10h", "2027-02-30 10:00"),
    # in a while
    ("daqui a 2 horas", "in 2h"),
    ("em 2 horas", "in 2h"),
    ("em 30 min", "in 30m"),
    ("daqui a 3 dias", "in 3d"),
    ("daqui a uma hora", "in 1h"),
    ("em meia hora", "in 30m"),
    ("daqui a 2 semanas", "in 14d"),
    # a day or a vague time with no hour: asked, never an invented hour
    ("amanhã", "missing"),
    ("sexta de manhã", "missing"),
    ("mais tarde", "missing"),
    ("à tarde", "missing"),
    ("daqui a pouco", "missing"),
    ("amanhã em 2 horas", "missing"),
    # two readings
    ("amanhã 9h ou 10h", ("ask", ["2026-10-23 09:00", "2026-10-23 10:00"])),
    ("sexta 9h ou sábado 9h", ("ask", ["2026-10-23 09:00", "2026-10-24 09:00"])),
    # no time at all
    ("nada de hora aqui", None),
    ("comprar 3 pães", None),
    # a line in two languages: every table is tried on every line
    ("amanhã at 3pm", "2026-10-23 15:00"),
    ("tomorrow às 15h", "2026-10-23 15:00"),
    ("me lembra in 2 hours", "in 2h"),
]

# (a line, what `natural.candidate` makes of it with no clock)
CANDIDATE_CASES = [
    ("me lembra amanhã às 13h do corte de cabelo", {"op": "remind", "how": "trigger"}),
    ("Me lembre sexta às 9 de ligar para a gráfica", {"op": "remind", "how": "trigger"}),
    ("lembra-me de pagar o aluguel dia 5 às 8h", {"op": "remind", "how": "trigger"}),
    ("me avisa daqui a 2 horas", {"op": "remind", "how": "trigger"}),
    ("lembrete: dentista amanhã 15h", {"op": "remind", "how": "trigger"}),
    ("pode me lembrar amanhã 9h do remédio", {"op": "remind", "how": "trigger"}),
    ("me lembra do corte de cabelo", {"op": "remind", "how": "trigger"}),
    ("quais lembretes eu tenho?", {"op": "reminders", "how": "trigger"}),
    ("meus lembretes", {"op": "reminders", "how": "trigger"}),
    ("lista os lembretes", {"op": "reminders", "how": "trigger"}),
    ("esquece o lembrete 3", {"op": "reminder-forget", "how": "trigger", "id": 3}),
    ("cancela o lembrete 12 por favor", {"op": "reminder-forget", "how": "trigger", "id": 12}),
    ("apague o lembrete", {"op": "reminder-forget", "how": "trigger", "id": None}),
    ("marca na agenda o dentista sexta às 9", {"op": "calendar-event-create", "how": "trigger"}),
    ("agende reunião amanhã 10h", {"op": "calendar-event-create", "how": "trigger"}),
    ("anote corte de cabelo amanhã às 13hrs", {"op": "remind", "how": "bare"}),
    ("corte de cabelo amanhã 13h", {"op": "remind", "how": "bare"}),
    ("dentista sexta às 15h", {"op": "remind", "how": "bare"}),
    # what must not become a reminder
    ("escreva o post de lançamento para amanhã às 9", None),
    ("o que vence amanhã às 9?", None),
    ("como estamos hoje?", None),
    ("quais arquivos você tem", None),
    ("aprova o plano 12", None),
    ("amanhã", None),
    ("anote comprar leite", None),
    ("preciso revisar o relatório de vendas do trimestre e mandar para a diretoria até amanhã às 15h", None),
]

# (a line, the words of the reminder it makes: the line minus the trigger, the time phrases and one leading connector)
TEXT_CASES = [
    ("me lembra amanhã às 13h do corte de cabelo", "corte de cabelo"),
    ("me lembra de pagar a conta dia 10 às 9h", "pagar a conta"),
    ("Me lembre sexta às 9h que o gás acaba", "o gás acaba"),
    ("lembra-me em 2 horas de tirar o bolo do forno", "tirar o bolo do forno"),
    ("pode me lembrar hoje às 18h para ligar para o Rui", "ligar para o Rui"),
    ("lembrete: dentista amanhã 15h", "dentista"),
]

# The bridge's conversations (the clock reads Sunday 2026-10-18 14:00 at -03:00, the project's language is pt-BR). Each step: the line, then the replies it must get.
REPLY_CUT = "Lembrete #1: amanhã, seg 19/10, às 13:00 (BRT): corte de cabelo. Para desfazer: /forget 1."
REPLY_CUT_COUNT = "Lembrete #1: amanhã, seg 19/10, às 13:00 (BRT). Para desfazer: /forget 1."
SLASH_ASK_WHEN = "Quando? Ex.: /remind amanhã 13h corte de cabelo"
ASK_WHEN = "Quando? Ex.: me lembra amanhã às 13h do corte de cabelo"
ASK_NINE = ("Qual horário você quer: sex 23/10 às 09:00 ou sex 23/10 às 21:00? Responda com a hora.")
REPLY_FRIDAY_21 = "Lembrete #1: sex 23/10 às 21:00 (BRT): ligar para a gráfica. Para desfazer: /forget 1."
ASK_KIND = "Amanhã, seg 19/10, às 13:00: corte de cabelo. Um lembrete aqui no chat, ou um evento na sua agenda? A agenda ainda não está disponível."
ASK_KIND_COUNT = "Amanhã, seg 19/10, às 13:00. Um lembrete aqui no chat, ou um evento na sua agenda? A agenda ainda não está disponível."
NOT_BUILT = "Ainda não sei fazer isso: colocar um evento na sua agenda (planejado). Posso enviar um lembrete aqui no chat."
PAST_TODAY = "Lembrete #1: 13:00 de hoje já passou: amanhã, seg 19/10, às 13:00 (BRT): corte de cabelo. Para desfazer: /forget 1."
ASK_TIME_TOMORROW = "Amanhã, seg 19/10: a que horas? Responda com uma hora, por exemplo 13h."
WHICH = "Qual deles? Envie /forget <n>."
FORGOT = "Lembrete #1 cancelado."
