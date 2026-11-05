"""The lines of the tests of the mail writes asked in words (package NR-5b, runtime/natural_writes_mail.py), as data: what a person types, in Brazilian Portuguese and in English,
and what the platform must make of it. Not a test file.

It is a test file written in Portuguese on purpose (listed by name in .security-scan-allow, like runtime/tests/natural_cases_pt_br.py): the tests that use it are English.
Every name, address and subject is invented (`.example` addresses). None of the lines is a line of a real person: the shapes are the ones SPEC-NATURAL-WRITES 2.3 lists.

  READS     (line, operation, {slots the line must give}, [need])    a line that is a closed form of the family
  NEGATIVES lines that are NOT a form of the family and must go on as they did before (a request for work, a reminder, a calendar line, a scheduled send, a mention)
  WORK      requests for work that start with a write verb (the SPEC's 60 work requests, here those that start with a mail verb)
  PROBES    lines that look like a form and are contained (a reply to several messages, a name with no body marker...)
  corpus(language)   the lines of the fuzz: every operation with every combination of the optional slots, deterministic
"""
from __future__ import annotations

import itertools

PT_READS = [
    # --- mail-send
    ("manda um e-mail pra bia@exemplo.example dizendo que o contrato segue amanhã", "mail-send", {"to": ["bia@exemplo.example"], "body": "o contrato segue amanhã"}, ["subject"]),
    ("manda um e-mail pra bia@exemplo.example", "mail-send", {"to": ["bia@exemplo.example"]}, ["subject", "body"]),
    ("envia um e-mail para caio@exemplo.example com o assunto Reunião de sexta dizendo que chego às 9", "mail-send",
     {"to": ["caio@exemplo.example"], "subject": "Reunião de sexta", "body": "chego às 9"}, []),
    ("escreve um e-mail pra bia@exemplo.example e dora@exemplo.example com o assunto \"Fatura de outubro\": segue anexa.", "mail-send",
     {"to": ["bia@exemplo.example", "dora@exemplo.example"], "subject": "Fatura de outubro", "body": "segue anexa."}, []),
    ("por favor, manda um e-mail pelo gmail pra bia@exemplo.example dizendo que oi", "mail-send", {"to": ["bia@exemplo.example"], "service": "google", "body": "oi"}, ["subject"]),
    ("manda um e-mail pelo outlook para dora@exemplo.example dizendo que tudo certo?", "mail-send", {"service": "microsoft", "body": "tudo certo?"}, ["subject"]),
    ("manda um e-mail pra Bia dizendo que o contrato segue amanhã", "mail-send", {"to_names": ["Bia"], "body": "o contrato segue amanhã"}, ["to", "subject"]),
    ("manda um e-mail para a Dora dizendo que confirmo", "mail-send", {"to_names": ["Dora"], "body": "confirmo"}, ["to", "subject"]),
    ("manda um e-mail pra bia@exemplo.example: nos vemos às 15h, combinado?", "mail-send", {"body": "nos vemos às 15h, combinado?"}, ["subject"]),
    # --- mail-reply
    ("responde o e-mail 3 dizendo que chego às 9", "mail-reply", {"numbers": [3], "body": "chego às 9"}, []),
    ("responde ao e-mail 12 falando que fecho hoje, sem falta", "mail-reply", {"numbers": [12], "body": "fecho hoje, sem falta"}, []),
    ("responde o e-mail 3", "mail-reply", {"numbers": [3]}, ["body"]),
    ("responde o e-mail inbox#4 dizendo que sim", "mail-reply", {"refs": ["inbox#4"], "body": "sim"}, []),
    ("responde ao e-mail da Bia sobre a fatura dizendo que pago hoje", "mail-reply", {"words": ["bia", "fatura"], "body": "pago hoje"}, []),
    ("responde o último e-mail do banco dizendo que ok", "mail-reply", {"newest": True, "words": ["banco"], "body": "ok"}, []),
    ("responde o último e-mail dizendo que ok", "mail-reply", {"newest": True, "body": "ok"}, []),
    ("responde o e-mail 3 pelo outlook dizendo que chego às 9", "mail-reply", {"numbers": [3], "service": "microsoft", "body": "chego às 9"}, []),
    # --- mail-draft
    ("rascunha uma resposta ao e-mail 5 dizendo que confirmo", "mail-draft", {"numbers": [5], "body": "confirmo"}, []),
    ("rascunha um e-mail pra bia@exemplo.example com o assunto Oi dizendo que tudo bem", "mail-draft", {"to": ["bia@exemplo.example"], "subject": "Oi", "body": "tudo bem"}, []),
    ("faz um rascunho de e-mail pra dora@exemplo.example dizendo que volto segunda", "mail-draft", {"to": ["dora@exemplo.example"], "body": "volto segunda"}, ["subject"]),
    # --- mail-archive
    ("arquiva os e-mails 2 e 4", "mail-archive", {"numbers": [2, 4]}, []),
    ("arquiva os e-mails 2, 4 e 7", "mail-archive", {"numbers": [2, 4, 7]}, []),
    ("arquive o e-mail 9", "mail-archive", {"numbers": [9]}, []),
    ("arquiva os e-mails do banco", "mail-archive", {"words": ["banco"], "plural": True}, []),
    ("arquiva o último e-mail da Bia", "mail-archive", {"words": ["bia"], "newest": True}, []),
    ("arquiva os e-mails 2 e 4 do gmail", "mail-archive", {"numbers": [2, 4], "service": "google"}, []),
    ("arquiva os e-mails inbox#2 e work#3", "mail-archive", {"refs": ["inbox#2", "work#3"]}, []),
    # --- mail-move
    ("move o e-mail 6 para a pasta contas", "mail-move", {"numbers": [6], "folder_name": "contas"}, []),
    ("move os e-mails 2 e 3 para a pasta viagens", "mail-move", {"numbers": [2, 3], "folder_name": "viagens"}, []),
    ("move os e-mails sobre a viagem para a pasta viagens", "mail-move", {"words": ["viagem"], "folder_name": "viagens"}, []),
    # --- mail-mark
    ("marca os e-mails 1 a 3 como lidos", "mail-mark", {"numbers": [1, 2, 3], "state": "read"}, []),
    ("marca o e-mail 4 como não lido", "mail-mark", {"numbers": [4], "state": "unread"}, []),
    ("marque os e-mails do banco como lidos", "mail-mark", {"words": ["banco"], "state": "read"}, []),
    ("marca o e-mail 4", "mail-mark", {"numbers": [4]}, ["state"]),
    # --- mail-trash
    ("apaga o e-mail 7", "mail-trash", {"numbers": [7]}, []),
    ("joga fora os e-mails 2 e 3", "mail-trash", {"numbers": [2, 3]}, []),
    ("exclua os e-mails da loja", "mail-trash", {"words": ["loja"]}, []),
]

EN_READS = [
    ("send an email to bia@example.example saying the contract goes out tomorrow", "mail-send", {"to": ["bia@example.example"], "body": "the contract goes out tomorrow"}, ["subject"]),
    ("send an email to bia@example.example with the subject Contract saying it goes out tomorrow", "mail-send",
     {"subject": "Contract", "body": "it goes out tomorrow"}, []),
    ("write an email to bia@example.example and dora@example.example with the subject \"October invoice\": attached.", "mail-send",
     {"to": ["bia@example.example", "dora@example.example"], "subject": "October invoice", "body": "attached."}, []),
    ("please send an email via outlook to caio@example.example saying hello", "mail-send", {"service": "microsoft", "body": "hello"}, ["subject"]),
    ("write an email to Bia saying hello", "mail-send", {"to_names": ["Bia"], "body": "hello"}, ["to", "subject"]),
    ("reply to email 3 saying I will be there at 9", "mail-reply", {"numbers": [3], "body": "I will be there at 9"}, []),
    ("reply to the email from Bia about the invoice saying I pay today", "mail-reply", {"words": ["bia", "invoice"], "body": "I pay today"}, []),
    ("reply to the latest email from the bank saying ok", "mail-reply", {"newest": True, "words": ["bank"], "body": "ok"}, []),
    ("draft a reply to email 5 saying I confirm", "mail-draft", {"numbers": [5], "body": "I confirm"}, []),
    ("draft an email to bia@example.example with the subject Hi saying all good", "mail-draft", {"subject": "Hi", "body": "all good"}, []),
    ("archive emails 2 and 4", "mail-archive", {"numbers": [2, 4]}, []),
    ("archive emails 1 to 3", "mail-archive", {"numbers": [1, 2, 3]}, []),
    ("archive the emails from the bank", "mail-archive", {"words": ["bank"], "plural": True}, []),
    ("archive emails 2 and 4 from gmail", "mail-archive", {"numbers": [2, 4], "service": "google"}, []),
    ("move email 6 to the folder bills", "mail-move", {"numbers": [6], "folder_name": "bills"}, []),
    ("move emails 1 to 3 to bills", "mail-move", {"numbers": [1, 2, 3], "folder_name": "bills"}, []),
    ("mark emails 1 through 3 as read", "mail-mark", {"numbers": [1, 2, 3], "state": "read"}, []),
    ("mark email 4 as unread", "mail-mark", {"numbers": [4], "state": "unread"}, []),
    ("mark email 4", "mail-mark", {"numbers": [4]}, ["state"]),
    ("delete email 7", "mail-trash", {"numbers": [7]}, []),
    ("trash the emails from the shop", "mail-trash", {"words": ["shop"]}, []),
]

# Lines the family must NOT take: they go on to the other families, the reminders or the router as they did before.
NEGATIVES = [
    "manda um e-mail pra Bia",                                                        # a name and no body marker: a request for work
    "manda um e-mail",
    "manda um e-mail para todos os clientes sobre a promoção",
    "manda um e-mail pra bia@exemplo.example amanhã às 9 dizendo que segue",           # a scheduled send is not offered
    "envia um e-mail para @bia dizendo que oi",                                        # a mention is never an address
    "envia um e-mail para bia@ dizendo que oi",
    "arquiva os e-mails",                                                              # no reference
    "arquiva",
    "marca dentista quinta às 10h",                                                    # a calendar line
    "marca uma reunião com a Bia amanhã às 15h",
    "apaga o evento 4",                                                                # an event, not a message
    "move o evento 2 para sexta às 15h",
    "me lembra de mandar um e-mail pra bia@exemplo.example",                           # the head is not at the start
    "lembra de responder o e-mail 3 amanhã às 9",
    "o que você acha de arquivar os e-mails 2 e 4",
    "responde os e-mails 3 e 4 dizendo que ok",                                        # a reply answers one message
    "responde aos e-mails do banco dizendo que ok",
    "move o e-mail 6",                                                                 # no folder
    "manda o e-mail 3 pra lixeira",
    "/archive 2",
    "",
    "   ",
]
EN_NEGATIVES = [
    "send an email to Bia",
    "send an email",
    "send an email to all the customers about the promotion",
    "send an email to bia@example.example tomorrow at 9 saying hello",
    "send an email to @bia saying hello",
    "archive emails",
    "archive",
    "schedule the dentist on Thursday at 10am",
    "delete the event 4",
    "remind me to send an email to bia@example.example",
    "reply to emails 3 and 4 saying ok",
    "move email 6",
    "please can you tell me about archive emails 2 and 4",
]

WORK = [
    "manda um e-mail para todos os clientes sobre a promoção de novembro",
    "escreve um e-mail de boas-vindas para novos clientes",
    "escreve um e-mail para a equipe sobre a mudança de horário",
    "envia um e-mail para o fornecedor cobrando o pedido atrasado",
    "manda uma mensagem de agradecimento para os participantes do evento",
    "escreve um e-mail para os investidores sobre o trimestre",
    "manda um e-mail pro time explicando o novo processo",
    "arquivar a conversa e resumir o que ficou decidido",
    "redige um e-mail de cobrança educado e curto",
    "mande um e-mail para os alunos sobre a prova",
]
EN_WORK = [
    "send an email to all the customers about the november promotion",
    "write a welcome email for new customers",
    "write an email to the team about the schedule change",
    "send a thank-you message to the people who came to the event",
    "compose an email to the investors about the quarter",
    "send an email to the team explaining the new process",
    "archive the old project and summarise what was decided",
    "draft a polite and short payment reminder email",
]


def _combine(values):
    return [item for item in values if item]


def corpus(language: str) -> list:
    """The lines of the fuzz: every operation of the family with every combination of its optional slots. Deterministic, built from a few fictional shapes."""
    pt = language == "pt-BR"
    verbs = ["manda um e-mail", "envia um e-mail", "escreve um e-mail", "rascunha um e-mail"] if pt else ["send an email", "write an email", "draft an email", "compose an email"]
    services = ["", "pelo gmail", "pelo outlook"] if pt else ["", "via gmail", "via outlook"]
    recipients = (["pra bia@exemplo.example", "para caio@exemplo.example e dora@exemplo.example", "pra Bia"] if pt
                  else ["to bia@example.example", "to caio@example.example and dora@example.example", "to Bia"])
    subjects = ["", "com o assunto Reunião de sexta", "com o assunto \"Fatura de outubro\""] if pt else ["", "with the subject Friday meeting", "with the subject \"October invoice\""]
    bodies = ["", "dizendo que chego às 9", "falando que o contrato segue amanhã"] if pt else ["", "saying I will be there at 9", "saying the contract goes out tomorrow"]
    out = []
    for verb, service, to, subject, body in itertools.product(verbs, services, recipients, subjects, bodies):
        out.append(" ".join(_combine([verb, service, to, subject, body])))
    refs = ["3", "2 e 4", "1 a 3", "inbox#2", "do banco", "da Bia sobre a fatura", "o último do banco"] if pt else ["3", "2 and 4", "1 to 3", "inbox#2", "from the bank", "from Bia about the invoice", "latest from the bank"]
    heads = (["responde o e-mail", "responde ao e-mail", "arquiva os e-mails", "apaga o e-mail", "marca os e-mails", "move os e-mails", "rascunha uma resposta ao e-mail"] if pt
             else ["reply to email", "archive emails", "delete email", "mark emails", "move emails", "draft a reply to email"])
    tails = ["", "pelo outlook", "dizendo que ok", "como lidos", "como não lido", "para a pasta contas", "para a pasta inexistente"] if pt else \
        ["", "via outlook", "saying ok", "as read", "as unread", "to the folder bills", "to the folder missing"]
    for head, ref, tail in itertools.product(heads, refs, tails):
        out.append(" ".join(_combine([head, ref, tail])))
    return list(dict.fromkeys(out))


ANSWERS_PT = ["1", "2", "3", "google", "outlook", "inbox", "work", "lido", "não lido", "bia@exemplo.example", "Reunião de sexta", "chego às 9", "contas", "viagens", "pasta nenhuma",
              "sim", "não", "cancela", "4 e 5", "manda um e-mail pra caio@exemplo.example dizendo que oi"]
ANSWERS_EN = ["1", "2", "3", "google", "outlook", "inbox", "work", "read", "unread", "bia@example.example", "Friday meeting", "I will be there at 9", "bills", "travel", "no such folder",
              "yes", "no", "cancel", "4 and 5", "send an email to caio@example.example saying hello"]
