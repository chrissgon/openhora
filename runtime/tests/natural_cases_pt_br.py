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
    ("aula de violão as 13hrs amanha", "2026-10-23 13:00"),
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
    # minutes written in the ways people write them
    ("13h 30", "13:30"),
    ("13h30min", "13:30"),
    ("13h 30min", "13:30"),
    ("às 13.30", "13:30"),
    ("amanhã 13.30", "2026-10-23 13:30"),
    ("às 9.30", "09:30"),
    ("às 13 e 30", "13:30"),
    ("às 13 e meia", "13:30"),
    ("meio-dia e meia", "12:30"),
    ("13.30", None),
    ("custa 13.30 reais", None),
    ("às 9 30 da reunião", None),
    # an hour with no "h", no ":" and no marker is asked back
    ("às 9", ("ask", ["09:00", "21:00"])),
    ("as 3", ("ask", ["03:00", "15:00"])),
    ("às 3 e meia", ("ask", ["03:30", "15:30"])),
    ("às 9 horas", ("ask", ["09:00", "21:00"])),
    ("sexta às 9", ("ask", ["2026-10-23 09:00", "2026-10-23 21:00"])),
    ("sexta às 9h", "2026-10-23 09:00"),
    # 1h30 after a length-of-time word is a duration; alone it is asked
    ("daqui a 1h30", "in 90m"),
    ("em 1h 30min", "in 90m"),
    ("daqui a 2h15", "in 135m"),
    ("daqui a uma hora e meia", "in 90m"),
    ("daqui a 1 hora e 30 minutos", "in 90m"),
    ("1h30", ("ask", ["in 90m", "01:30"])),
    # 12-hour clocks, noon and midnight
    ("meio-dia", "12:00"),
    ("amanhã meio-dia", "2026-10-23 12:00"),
    ("meia-noite", "00:00"),
    ("sexta à meia-noite", ("ask", ["2026-10-23 00:00", "2026-10-24 00:00"])),
    ("9 da manhã", "09:00"),
    ("3 da tarde", "15:00"),
    ("9 da noite", "21:00"),
    ("3 da madrugada", "03:00"),
    # days
    ("hoje às 18h", "2026-10-22 18:00"),
    ("hoje 13h", "2026-10-22 13:00"),
    ("depois de amanhã às 8h", "2026-10-24 08:00"),
    ("depois de amanha 9h30", "2026-10-24 09:30"),
    # weekdays: the same weekday is today when the time is still ahead, else in 7 days; "next" and "que vem" offer the nearest and the one after
    ("sexta-feira 14h", "2026-10-23 14:00"),
    ("quinta 15h", "2026-10-22 15:00"),
    ("quinta 13h", "2026-10-29 13:00"),
    ("próxima quinta às 10h", ("ask", ["2026-10-29 10:00", "2026-11-05 10:00"])),
    ("próxima sexta 10h", ("ask", ["2026-10-23 10:00", "2026-10-30 10:00"])),
    ("quinta que vem às 15h30", ("ask", ["2026-10-29 15:30", "2026-11-05 15:30"])),
    ("sexta que vem 9h", ("ask", ["2026-10-23 09:00", "2026-10-30 09:00"])),
    ("segunda às 10h", "2026-10-26 10:00"),
    ("2a feira às 9h", "2026-10-26 09:00"),
    ("6a feira 14h", "2026-10-23 14:00"),
    ("sábado 10h", "2026-10-24 10:00"),
    ("hj às 15h", "2026-10-22 15:00"),
    ("na 2a às 9h", "2026-10-26 09:00"),
    ("2ª feira às 9h", "2026-10-26 09:00"),
    ("sexta dia 23 às 9h", "2026-10-23 09:00"),
    ("sexta dia 24 às 9h", ("ask", ["2026-10-23 09:00", "2026-10-24 09:00"])),
    ("dia 3 de mar às 9h", "2027-03-03 09:00"),
    ("domingo às 20h", "2026-10-25 20:00"),
    ("na quarta às 8h", "2026-10-28 08:00"),
    # day of the month and dates
    ("dia 25 às 8h", "2026-10-25 08:00"),
    ("dia 10 às 8h", "2026-11-10 08:00"),
    ("dia 22 às 15h", "2026-10-22 15:00"),
    ("dia 22 às 13h", "2026-10-22 13:00"),          # today with an hour that has passed stays today: resolve refuses it as past
    ("25/10 às 10h", "2026-10-25 10:00"),
    ("22/10 às 13h", "2026-10-22 13:00"),
    ("25/10/2027 10h", "2027-10-25 10:00"),
    ("5/11 9h", "2026-11-05 09:00"),
    ("2026-10-25 08:00", "2026-10-25 08:00"),
    ("25 de outubro às 14h", "2026-10-25 14:00"),
    ("5 de janeiro 9h", "2027-01-05 09:00"),
    ("30/02 10h", "2027-02-30 10:00"),
    # x/y is a date only when something says it is one
    ("parcela 3/10 vence amanhã 9h", "2026-10-23 09:00"),
    ("3/10 do aluguel amanhã 9h", "2026-10-23 09:00"),
    ("dia 3/10 9h", "2027-10-03 09:00"),
    ("3/10", None),
    ("nota 7/10 na prova", None),
    # in a while
    ("daqui a 2 horas", "in 2h"),
    ("em 2 horas", "in 2h"),
    ("em 30 min", "in 30m"),
    ("daqui 40 min", "in 40m"),
    ("daqui a 3 dias", "in 3d"),
    ("daqui a 2 dias às 9h", "2026-10-24 09:00"),
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
    # weak words (abbreviations) count only in a line of their language
    ("sex 15h", "2026-10-23 15:00"),
    ("Sex Shop", None),
    ("Maria da Silva", None),
    ("fui na loja sex 3", None),
]

# (a line, what `natural.candidate` makes of it with no clock)
CANDIDATE_CASES = [
    ("me lembra amanhã às 13h da aula de violão", {"op": "remind", "how": "trigger"}),
    ("Me lembre sexta às 9 de ligar para a gráfica", {"op": "remind", "how": "trigger"}),
    ("lembra-me de pagar o aluguel dia 5 às 8h", {"op": "remind", "how": "trigger"}),
    ("me avisa daqui a 2 horas", {"op": "remind", "how": "trigger"}),
    ("lembrete: veterinário amanhã 15h", {"op": "remind", "how": "trigger"}),
    ("pode me lembrar amanhã 9h do xarope", {"op": "remind", "how": "trigger"}),
    ("me lembra da aula de violão", {"op": "remind", "how": "trigger"}),
    ("em 25 min me avisa de desligar o fogão", {"op": "remind", "how": "trigger"}),
    ("às 9 me lembra de regar as plantas", {"op": "remind", "how": "trigger"}),
    ("mostra os lembretes que estão abertos", {"op": "reminders", "how": "trigger"}),
    ("meus lembretes", {"op": "reminders", "how": "trigger"}),
    ("lista os lembretes", {"op": "reminders", "how": "trigger"}),
    ("lembretes", {"op": "reminders", "how": "trigger"}),
    ("esquece o lembrete 3", {"op": "reminder-forget", "how": "trigger", "id": 3}),
    ("cancela o lembrete 12 por favor", {"op": "reminder-forget", "how": "trigger", "id": 12}),
    ("apague o lembrete", {"op": "reminder-forget", "how": "trigger", "id": None}),
    ("esquece o lembrete 3 4", {"op": "reminder-forget", "how": "trigger", "id": None, "ids": [3, 4], "confirm": True}),
    ("esquece o lembrete da aula de violão", {"op": "reminder-forget", "how": "trigger", "id": None, "words": ["aula", "violao"]}),
    ("marca na agenda o oculista sexta às 9", {"op": "calendar-event-create", "how": "trigger"}),
    ("agenda consulta com a nutricionista segunda que vem às 16h20 na clínica", {"op": "calendar-event-create", "how": "ask"}),
    ("agende reunião amanhã 10h", {"op": "calendar-event-create", "how": "ask"}),
    ("marca aula de violão sábado 10h", {"op": "calendar-event-create", "how": "trigger"}),
    ("desfaz", {"op": "reminder-restore", "how": "trigger"}),
    ("desfaz isso", {"op": "reminder-restore", "how": "trigger"}),
    ("esquece o lembrete #9", {"op": "reminder-forget", "how": "trigger", "id": 9}),
    ("cancela o lembrete 9", {"op": "reminder-forget", "how": "trigger", "id": 9}),
    ("cancela o lembrete das 9", {"op": "reminder-forget", "how": "trigger", "id": None, "at": "das 9", "confirm": True}),
    ("esquece o lembrete de pagar 2 boletos", {"op": "reminder-forget", "how": "trigger", "id": None, "words": ["pagar", "2", "boletos"]}),
    ("apaga o lembrete do dia 3", {"op": "reminder-forget", "how": "trigger", "id": None, "words": ["dia", "3"]}),
    ("anote aula de violão amanhã às 13hrs", {"op": "remind", "how": "bare"}),
    ("anota: trocar a areia do gato", {"op": "remind", "how": "note"}),
    ("aula de violão amanhã 13h", {"op": "remind", "how": "bare"}),
    ("13hrs aula de violão amanha", {"op": "remind", "how": "bare"}),
    ("veterinário sexta às 15h", {"op": "remind", "how": "bare"}),
    # what must not become a reminder
    ("escreva o post de lançamento para amanhã às 9", None),
    ("o que vence amanhã às 9?", None),
    ("como estamos hoje?", None),
    ("que arquivos há aqui", None),
    ("pode liberar a proposta 12", None),
    ("amanhã", None),
    ("lembretes funcionam no whatsapp?", None),
    ("lembretes não chegam no meu celular", None),
    ("meus lembretes não chegaram", None),
    ("lembrete 3 não chegou", None),
    ("agenda de amanhã?", None),
    ("agenda da semana", None),
    ("calendário de outubro?", None),
    ("toda quarta às 7h me manda a previsão do tempo", None),
    ("cancela o lembrete aviso de vencimento do site", None),
    ("agende", None),
    ("marca", None),
    ("preciso revisar o relatório de vendas do trimestre e mandar para a diretoria até amanhã às 15h", None),
]

# (a line, the words of the reminder it makes: the line minus the trigger, the time phrases and the connectives at its edges)
TEXT_CASES = [
    ("me lembra amanhã às 13h da aula de violão", "aula de violão"),
    ("me lembra de pagar a conta dia 10 às 9h", "pagar a conta"),
    ("Me lembre sexta às 9h que o gás acaba", "o gás acaba"),
    ("lembra-me em 2 horas de tirar o pão do forno", "tirar o pão do forno"),
    ("pode me lembrar hoje às 18h para ligar para o Rui", "ligar para o Rui"),
    ("lembrete: veterinário amanhã 15h", "veterinário"),
    ("em 25 min me avisa de desligar o fogão", "desligar o fogão"),
    ("às 9h me lembra de regar as plantas", "regar as plantas"),
    ("me lembra amanhã 9h de pagar a parcela 3/10", "pagar a parcela 3/10"),
]

# Lines the parse makes a reminder of only after asking: a word of the time that it did not use. (Asked, never made.)
UNSURE_LINES = [
    "me lembra amnha às 9h de pagar a conta",
    "me lembra fim de semana às 10h de ligar para a Ana",
    "me lembra amanhã às 9h do próximo mês",
]
# Lines that repeat: a reminder here happens once.
RECURRING_LINES = [
    "me lembra toda segunda às 8h de regar as plantas",
    "me lembra de tomar o xarope de 8 em 8 horas",
    "me lembra todo dia às 7h de abrir a janela",
    "me lembra a cada 2 horas de beber água",
]
# Lines with words that look like a day or a time and are not: made at once.
PLAIN_LINES = [
    "me lembra amanhã às 9h de arrumar o quarto",
    "me lembra amanhã às 9h de ligar para a Amanda",
    "me lembra amanhã às 9h do segundo andar",
    "me lembra amanhã às 9h do quintal",
    "me lembra amanhã às 9h de falar com o Marcos",
    "me lembra amanhã às 9h de abrir a loja",
]

# The bridge's conversations (the clock reads Sunday 2026-10-18 14:00 at -03:00, the project's language is pt-BR). Each step: the line, then the replies it must get.
REPLY_CLASS = "Lembrete #1: amanhã, seg 19/10, às 13:00 (BRT): aula de violão. Para desfazer: /forget 1."
REPLY_CLASS_COUNT = "Lembrete #1: amanhã, seg 19/10, às 13:00 (BRT). Para desfazer: /forget 1."
SLASH_ASK_WHEN = "Quando? Ex.: /remind amanhã 13h regar as plantas"
ASK_WHEN = "Quando? Ex.: me lembra amanhã às 13h de regar as plantas"
ASK_UNSURE = "Não tenho certeza de quando você quer. Quando? Ex.: me lembra amanhã às 13h de regar as plantas"
ASK_NOTE = "Quer um lembrete? Então diga para quando, por exemplo: amanhã às 13h"
ASK_NINE = "Qual horário você quer: sex 23/10 às 09:00 ou sex 23/10 às 21:00? Responda com a hora."
ASK_THURSDAY = "Qual horário você quer: qui 22/10 às 15:30 ou qui 29/10 às 15:30? Responda com a hora."
REPLY_FRIDAY_21 = "Lembrete #1: sex 23/10 às 21:00 (BRT): ligar para a gráfica. Para desfazer: /forget 1."
ASK_KIND = "Amanhã, seg 19/10, às 13:00: aula de violão. Um lembrete aqui no chat, ou um evento na sua agenda? A agenda ainda não está disponível."
ASK_KIND_COUNT = "Amanhã, seg 19/10, às 13:00. Um lembrete aqui no chat, ou um evento na sua agenda? A agenda ainda não está disponível."
ASK_EVENT_OR_OTHER = ("Evento na agenda, ou outra coisa? A agenda ainda não está disponível. "
                      "Responda agenda, ou outra coisa para enviar a mensagem adiante.")
NOT_BUILT = "Ainda não sei fazer isso: colocar um evento na sua agenda (planejado). Posso enviar um lembrete aqui no chat."
PAST_TODAY = "Lembrete #1: 13:00 de hoje já passou: amanhã, seg 19/10, às 13:00 (BRT): aula de violão. Para desfazer: /forget 1."
ASK_TIME_TOMORROW = "Amanhã, seg 19/10: a que horas? Responda com uma hora, por exemplo 13h."
WHICH = "Qual deles? Envie /forget <n>."
FORGOT = "Lembrete #1 cancelado: amanhã, seg 19/10, às 13:00 (BRT): aula de violão. Para tê-lo de volta, envie: desfaz"
FORGOT_BY_WORDS = "Lembrete #2 cancelado: amanhã, seg 19/10, às 13:00 (BRT): aula de violão. Para tê-lo de volta, envie: desfaz"
NO_MATCH = "Nenhum lembrete seu pendente corresponde a isso. Envie /reminders para ver a lista."

# The lines the bridge tests send, and a few more replies. (Fictional: a class, an optician, a cat, a stove, a friend.)
LINE_SLASH = "/remind aula de violão as 13hrs amanha"
LINE_CLASS = "me lembra amanhã às 13h da aula de violão"
LINE_CLASS_REORDER = "me lembra da aula de violão amanhã às 13h"
LINE_NINE = "me lembra sexta às 9 de ligar para a gráfica"
LINE_BARE = "aula de violão amanhã 13h"
LINE_NOTE_TIME = "anote aula de violão amanhã às 13hrs"
LINE_NO_HOUR = "me lembra de ligar amanhã"
LINE_NO_TIME = "me lembra de regar as plantas"
LINE_CALENDAR = "marca na agenda o oculista sexta às 9"
LINE_LOOSE = "agende reunião amanhã 10h"
LINE_FORTY = "em 25 min me avisa de desligar o fogão"
LINE_NINE_FIRST = "às 9 me lembra de regar as plantas"
LINE_NOTE = "anota: trocar a areia do gato"
LINE_LIST = "mostra os lembretes que estão abertos"
LINE_LIST_BARE = "meus lembretes"
LINE_FORGET_WORDS = "esquece o lembrete da aula de violão"
LINE_FORGET_NONE = "apaga o lembrete da manicure"
LINE_FORGET_NUM = "esquece o lembrete 1"
LINE_FORGET_ASK = "esquece o lembrete"
LINE_YEAR = "me lembra dia 5/1 às 9h de renovar o seguro"
LINE_TODAY_PAST = "me lembra dia 18/10 às 13h de ligar"
LINE_UNSURE = "me lembra fim de semana às 10h de pagar o aluguel"
LINE_THURSDAY = "me lembra quinta que vem às 15h30 do arquiteto"
LINE_WORK = "escreva o post de lançamento para amanhã às 9"
REPLY_FORTY = "Lembrete #1: hoje, dom 18/10, às 14:25 (BRT): desligar o fogão. Para desfazer: /forget 1."
ASK_NINE_FIRST = "Qual horário você quer: amanhã, seg 19/10, às 09:00 ou hoje, dom 18/10, às 21:00? Responda com a hora."
REPLY_PLANTS = "Lembrete #1: amanhã, seg 19/10, às 09:00 (BRT): regar as plantas. Para desfazer: /forget 1."
REPLY_NOTE = "Lembrete #1: amanhã, seg 19/10, às 10:00 (BRT): trocar a areia do gato. Para desfazer: /forget 1."
REPLY_YEAR = "Lembrete #1: ter 05/01/2027 às 09:00 (BRT): renovar o seguro. Para desfazer: /forget 1."
REPLY_PAST_DAY = "Esse horário já passou. Agora são 18/10/2026 14:00."
LIST_HEAD = "northwind-shop: lembretes pendentes (BRT)"
LIST_ONE = "#1 amanhã, seg 19/10, às 13:00: aula de violão"
LIST_NONE = "northwind-shop: nenhum lembrete pendente."
REPLY_THURSDAY = "Lembrete #1: qui 22/10 às 15:30 (BRT): arquiteto. Para desfazer: /forget 1."
LINE_UNDO = "desfaz"
LINE_RECURRING = "me lembra toda segunda às 8h de regar as plantas"
LINE_TWO_BOLETOS = "me lembra amanhã às 15h de pagar 2 boletos"
LINE_FORGET_BOLETOS = "esquece o lembrete de pagar 2 boletos"
LINE_FORGET_NINE = "cancela o lembrete das 7"
LINE_AGENDA_READ = "agenda de amanhã?"
LINE_MARCA = "marca aula de violão sábado 10h"
CONFIRM_YEAR = "Entendi: ter 05/01/2027 às 09:00: renovar o seguro. Confirma? (sim / outra hora)"
CONFIRM_AMNHA = "Entendi: amanhã, seg 19/10, às 09:00: pagar a conta. Confirma? (sim / outra hora)"
REPLY_AMNHA = "Lembrete #1: amanhã, seg 19/10, às 09:00 (BRT): pagar a conta. Para desfazer: /forget 1."
RECURRING = "Um lembrete aqui acontece uma vez. O que se repete é uma rotina: configure no terminal ou na página. Para um lembrete único, diga quando."
CANCELLED = "Certo, nenhum lembrete foi criado."
RESTORED = "O lembrete #1 está de volta como #2: amanhã, seg 19/10, às 13:00 (BRT): aula de violão."

# --- round 3 of the independent review of #474 -------------------------------------------------------------------------------------------------------
# A weak word of a day (an abbreviation that is also a common word) next to the time or a number is the day; anywhere else it may be a name, and the reading is
# confirmed (never dropped). (line, ("when" | "confirm", the moment)); the clock is Sunday 2026-10-18 14:00.
NAME_LINES = [
    ("me lembra Seg às 9h de ligar", ("confirm", "2026-10-19 09:00")),
    ("me lembra na Sex às 9h de ligar", ("confirm", "2026-10-23 09:00")),
    ("me lembra seg. às 10h da reunião", ("confirm", "2026-10-19 10:00")),
    ("me lembra ligar pra Sex Shop às 9h", ("confirm", "09:00")),
    ("me lembra ligar pra sex shop às 9h", ("confirm", "09:00")),
    ("me lembra sex shop às 9h", ("confirm", "09:00")),
]
# The repeating word is part of the time phrase: a routine's. The same words inside the reminder's own text are text: made at once.
REPEAT_LINES = [
    "me lembra todo dia às 9h de abrir a janela", "me lembra toda segunda às 8h de regar as plantas", "me lembra a cada 2 horas de beber água",
    "me lembra de 8 em 8 horas do xarope", "me lembra semanalmente de conferir o correio", "me lembra diariamente às 9h de abrir a loja",
]
REPEAT_TEXT_LINES = [
    "me lembra amanhã às 9h de conferir a cada um dos fornecedores", "me lembra amanhã às 9h de revisar todo dia da planilha",
    "me lembra amanhã às 9h do relatório semanal", "me lembra amanhã às 9h de falar com todos os clientes",
]
# A part of the day beside an hour with no marker says which hour; one that contradicts a marked hour is confirmed.
PART_LINES = [
    ("me lembra amanhã de manhã às 9 de acordar", ("confirm", "2026-10-19 09:00")),
    ("me lembra hoje à noite às 9 de ligar", ("confirm", "2026-10-18 21:00")),
    ("me lembra amanhã à tarde às 3 de buscar o pacote", ("confirm", "2026-10-19 15:00")),
    ("me lembra amanhã de manhã às 21h de ligar", ("confirm", "2026-10-19 21:00")),
]
# What a forget line is: an explicit number acts, a number after another word is confirmed, an hour is matched against the moment.
FORGET_FORMS = [
    ("cancela o lembrete 3", {"id": 3}), ("cancela o lembrete #3", {"id": 3}), ("esquece o lembrete numero 3", {"id": 3}),
    ("apaga o lembrete do 3", {"id": 3, "confirm": True}), ("esquece o lembrete de 2", {"id": 2, "confirm": True}),
    ("esquece o lembrete no 4", {"id": 4, "confirm": True}), ("apague os lembretes 1 e 2", {"id": None, "ids": [1, 2], "confirm": True}),
    ("cancela o lembrete das 9", {"id": None, "at": "das 9", "confirm": True}),
]
# Lines that are not an undo (the bare word only, optionally with "the reminder").
NOT_UNDO = ["desfaz o commit", "desfaz isso no código", "desfazer a última mudança do site"]
LINE_WEEK = "me lembra semana que vem às 10h de pagar o aluguel"
LINE_WEEK_NO_TIME = "me lembra semana que vem de pagar o aluguel"
ASK_WEEKDAY = "Qual dia da semana que vem? Responda com o dia da semana, por exemplo terça."
ASK_AGAIN = "Para quando? Responda com o dia e a hora, por exemplo amanhã às 13h."
DISCARDED = "A pergunta anterior foi descartada."
EXPIRED = "Essa pergunta não está mais aberta: ela espera dez minutos. Envie a frase de novo."
CONFIRM_OLEO = "me lembra amnhã às 13h do troca de óleo"
CONFIRM_OLEO_ASK = "Entendi: amanhã, seg 19/10, às 13:00: troca de óleo. Confirma? (sim / outra hora)"
YES_ANSWERS = ["sim", "sim, pode", "sim por favor", "isso mesmo", "pode ser", "sim sim", "ok obrigado", "Sim!", "claro que sim"]
LINE_MARCA_LEMBRETE = "marca um lembrete amanhã às 9h de pagar o boleto"
LINE_AGENDE_LEMBRETE = "agende um lembrete amanhã às 9h de pagar o boleto"
LINE_JUJHO = "me lembra amanhã às 9h de pagar jujho"
ASK_FORGET_ONE = "Cancelar o lembrete #1: amanhã, seg 19/10, às 13:00 (BRT): aula de violão? (sim / não)"
FORGOT_ONE = "Lembrete #1 cancelado: amanhã, seg 19/10, às 13:00 (BRT): aula de violão. Para tê-lo de volta, envie: desfaz"
KEPT = "Certo, nada foi cancelado."

# --- round 4: the guard, ordinals, the answers ---------------------------------------------------------------------------------------------------------
# What the line says outside the time it read may be a date it did not read: the reading is shown and confirmed, never made. The clock is Sunday 2026-10-18 14:00.
GUARD_LINES = [
    "me lembra no Natal às 9h de ligar pra vó", "me lembra em dezembro às 9h de comprar presentes", "me lembra de pagar o IPVA em janeiro às 9h",
    "me lembra amanhã às 9h do ano novo", "me lembra de comprar presente pro dia dos pais às 9h", "me lembra amanhã às 9h da reunião de sexta",
    "recuérdame mañana a las 15:00 llamar a mamá", "recuérdame el 25 de diciembre a las 10:00 comprar regalos", "recuérdame el próximo martes a las 10:00",
    "rappelle-moi vendredi à 21h30 de payer l'électricité", "rappelle-moi après-demain à 18h", "rappelle-moi lundi prochain à 10h",
    "erinnere mich am Freitag um 21:30 die Stromrechnung zu bezahlen",
]
# An ordinal of the first day is a 1, however it is written.
ORDINAL_LINES = [
    ("me lembra 1º de dezembro às 10h do curso", "2026-12-01 10:00"), ("me lembra 1° de dezembro às 10h do curso", "2026-12-01 10:00"),
    ("me lembra 1o de dezembro às 10h do curso", "2026-12-01 10:00"), ("me lembra primeiro de dezembro às 10h do curso", "2026-12-01 10:00"),
    ("me lembra dia 1º às 10h do curso", "2026-11-01 10:00"), ("me lembra dia primeiro às 10h do curso", "2026-11-01 10:00"),
]
# Q1: the forms of an explicit number ("n° 3", "n.3", "no. 3", "nº3" act at once), and the ones that are only shown.
ID_FORMS = ["cancela o lembrete n° 3", "cancela o lembrete N° 3", "cancela o lembrete n.3", "cancela o lembrete n. 3", "cancela o lembrete no. 3", "cancela o lembrete nº3",
            "cancela o lembrete numero 3", "cancela o lembrete 3", "cancela o lembrete #3"]
BARE_FORGET = ["cancela #3", "cancela o 3", "esquece o 3"]
# Repetitions that are not "every" followed by a unit.
REPEAT_MORE = ["me lembra todo santo dia às 8h de tomar vitamina", "me lembra a cada meia hora de alongar", "me lembra de hora em hora de beber água",
               "me lembra dia sim dia não às 9h de regar", "me lembra nos dias úteis às 9h de bater o ponto", "me lembra de segunda a sexta às 9h de bater o ponto"]
LINE_HOURS_TEXT = "me lembra amanhã às 9h de revisar todas as horas lançadas"
LINE_DAYS = "me lembra daqui a 3 dias de pagar"
LINE_SPOKEN = "me lembra amanhã às nove de ligar"
LINE_HALF_AFTERNOON = "me lembra amanhã às 3 e meia da tarde da reunião"
LINE_SUNDAY = "me lembra domingo às 20h de ligar"
LINE_WEEK_MONDAY = "me lembra semana que vem segunda às 9h da reunião"
LINE_WEEK_FRIDAY = "me lembra na sexta da semana que vem às 9h de pagar"
ASK_TIME_DAYS = "Qua 21/10: a que horas? Responda com uma hora, por exemplo 13h."
NO_THANKS = ["nao obrigado", "não, obrigada"]

# --- round 5: nothing in free text is made without a yes, and the readings that were shown wrong -----------------------------------------------------------------------
# Sunday 2026-10-18 14:00. (line, the reading shown)
SHOWN_RIGHT = [
    ("me lembra amanhã às 9:00h de regar as orquídeas", "2026-10-19 09:00"), ("me lembra amanhã às 15:00h de regar as orquídeas", "2026-10-19 15:00"),
    ("me lembra 30 min antes da reunião das 15h", "2026-10-18 14:30"), ("me lembra meia hora antes da reunião das 18h", "2026-10-18 17:30"),
    ("me lembra uma hora antes do voo das 21h", "2026-10-18 20:00"), ("remind me 1 hour before the meeting at 5pm", "2026-10-18 16:00"),
    ("me lembra às 9h de 12/12 de pagar o seguro", "2026-12-12 09:00"), ("me lembra em 12/12 às 9h de pagar o seguro", "2026-12-12 09:00"),
    ("me lembra dom às 9h de trocar a lâmpada", "2026-10-25 09:00"),
]
# A range is asked: the two hours are the two readings.
LINE_RANGE = "me lembra amanhã entre 9h e 10h de regar as orquídeas"
# A date that is not one: refused with the calendar's sentence.
IMPOSSIBLE_DATES = ["me lembra 32/10 às 9h de pagar o seguro", "me lembra 00/10 às 9h de pagar o seguro", "me lembra dia 32 às 9h de pagar o seguro", "me lembra 32 de outubro às 9h de pagar o seguro"]
# A day word that is the topic of the reminder: both readings are offered, and the word stays in the words.
TOPIC_LINES = ["me lembra às 9h que a reunião de sexta foi cancelada", "me lembra às 9h do jogo de sábado"]
# More routines.
REPEAT_PLURAL = ["me lembra todas as segundas às 9h de regar as orquídeas", "me lembra às segundas de regar as orquídeas", "me lembra nas segundas às 9h de regar as orquídeas",
                 "me lembra sempre às 9h de abrir a janela"]
LINE_ORCHID = "me lembra amanhã às 9h de regar as orquídeas"
ASK_ORCHID = "Entendi: amanhã, seg 19/10, às 09:00: regar as orquídeas. Confirma? (sim / outra hora)"
REPLY_ORCHID = "Lembrete #1: amanhã, seg 19/10, às 09:00 (BRT): regar as orquídeas. Para desfazer: /forget 1."
LABEL_YES = "Sim"
