"""The lines of the tests of the natural writes (package NR-5) in Portuguese and English, as data: what a person types and what code must read from it. The one test
data file of NR-5 written in Portuguese on purpose; every test that uses it is written in English. Every errand, name and file is invented.

The clock of the tests is Monday 2026-10-19 09:00 at -03:00, so "quinta" is 2026-10-22, "sexta" 2026-10-23 and "amanha" 2026-10-20.

CASES is [(line, operation, {slot: value})]: the slots listed must be exactly what the line gives (the others must be absent); a line whose operation is None is no write form.
"""
from __future__ import annotations

CASES = [
    # --- a new event: pt-BR
    ("marca dentista quinta às 10h", "event-create", {"title": "dentista", "start": "2026-10-22T10:00"}),
    ("marque a reunião com o contador amanhã às 15h", "event-create", {"title": "reunião com o contador", "start": "2026-10-20T15:00"}),
    ("coloca na agenda trocar o filtro do ar sexta 9h", "event-create", {"title": "trocar o filtro do ar", "start": "2026-10-23T09:00"}),
    ("cria um evento pegar a encomenda na portaria sexta às 18h30", "event-create", {"title": "pegar a encomenda na portaria", "start": "2026-10-23T18:30"}),
    ("marca yoga amanhã das 7h às 8h", "event-create", {"title": "yoga", "start": "2026-10-20T07:00", "end": "2026-10-20T08:00"}),
    ("marca yoga amanhã 7h-8h30", "event-create", {"title": "yoga", "start": "2026-10-20T07:00", "end": "2026-10-20T08:30"}),
    ("marca reunião quinta 13-15h", "event-create", {"title": "reunião", "start": "2026-10-22T13:00", "end": "2026-10-22T15:00"}),
    ("marca reunião quinta 10 às 11h", "event-create", {"title": "reunião", "start": "2026-10-22T10:00", "end": "2026-10-22T11:00"}),
    ("marca reunião quinta das 10 às 11", "event-create", {"title": "reunião", "start": "2026-10-22T10:00", "end": "2026-10-22T11:00"}),
    ("marca reunião quinta de 13 a 15", "event-create", {"title": "reunião", "start": "2026-10-22T13:00", "end": "2026-10-22T15:00"}),
    ("add to my calendar meeting Thursday 1-2pm", "event-create", {"title": "meeting", "start": "2026-10-22T13:00", "end": "2026-10-22T14:00"}),
    ("marca viagem sexta dia todo", "event-create", {"title": "viagem", "start": "2026-10-23"}),
    ("marca dentista quinta às 10h na agenda trabalho", "event-create", {"title": "dentista", "start": "2026-10-22T10:00", "calendar": "trabalho"}),
    ("marca yoga amanhã às 7h no google", "event-create", {"title": "yoga", "start": "2026-10-20T07:00", "account": "google"}),
    ("marca revisão do carro no outlook sexta às 8h", "event-create", {"title": "revisão do carro", "start": "2026-10-23T08:00", "account": "microsoft"}),
    ("marca dentista daqui a 2 horas", "event-create", {"title": "dentista", "start": "2026-10-19T11:00"}),
    ("cria um evento reunião de pais", "event-create", {"title": "reunião de pais"}),
    ("adiciona na agenda aula de violão sexta às 17h", "event-create", {"title": "aula de violão", "start": "2026-10-23T17:00"}),
    # --- a new event: en
    ("add to my calendar dentist Thursday at 10am", "event-create", {"title": "dentist", "start": "2026-10-22T10:00"}),
    ("put on my calendar lunch from 1pm to 3pm tomorrow", "event-create", {"title": "lunch", "start": "2026-10-20T13:00", "end": "2026-10-20T15:00"}),
    ("create an event car wash Friday 4pm", "event-create", {"title": "car wash", "start": "2026-10-23T16:00"}),
    ("create an event garage sale Saturday all day", "event-create", {"title": "garage sale", "start": "2026-10-24"}),
    ("add to my calendar yoga tomorrow 7am to 8am", "event-create", {"title": "yoga", "start": "2026-10-20T07:00", "end": "2026-10-20T08:00"}),
    ("add to my calendar book club Friday 7pm on my work calendar", "event-create", {"title": "book club", "start": "2026-10-23T19:00", "calendar": "work"}),
    ("add to my calendar flight check-in tomorrow 6am on my outlook", "event-create", {"title": "flight check-in", "start": "2026-10-20T06:00", "account": "microsoft"}),
    # --- a change and a removal: pt-BR
    ("remarca o evento 2 para sexta às 15h", "event-change", {"event": 2, "start": "2026-10-23T15:00"}),
    ("adia a reunião 5 para amanhã 10h", "event-change", {"event": 5, "start": "2026-10-20T10:00"}),
    ("reagenda o compromisso 3 para quinta das 14h às 16h", "event-change", {"event": 3, "start": "2026-10-22T14:00", "end": "2026-10-22T16:00"}),
    ("muda o título do evento 2 para Dentista novo", "event-change", {"event": 2, "title": "Dentista novo"}),
    ("renomeia o evento 7 para Reunião de pais", "event-change", {"event": 7, "title": "Reunião de pais"}),
    ("desmarca o evento 4", "event-cancel", {"event": 4}),
    ("cancela a reunião 2 por favor", "event-cancel", {"event": 2}),
    ("cancela o compromisso", "event-cancel", {}),
    # --- a change and a removal: en
    ("move event 2 to Friday 3pm", "event-change", {"event": 2, "start": "2026-10-23T15:00"}),
    ("reschedule meeting 3 to tomorrow at 9am", "event-change", {"event": 3, "start": "2026-10-20T09:00"}),
    ("rename event 2 to Dentist again", "event-change", {"event": 2, "title": "Dentist again"}),
    ("cancel event 4", "event-cancel", {"event": 4}),
    ("delete the appointment 6", "event-cancel", {"event": 6}),
    ("cancel the meeting", "event-cancel", {}),
    # --- files: pt-BR
    ("cria um arquivo chamado ideias.md com o texto: comprar tinta azul", "file-create", {"name": "ideias.md", "content": "comprar tinta azul"}),
    ("salva uma nota chamada compras.txt dizendo pão, leite e café", "file-create", {"name": "compras.txt", "content": "pão, leite e café"}),
    ("cria um documento google chamado roteiro com o texto: abertura e fechamento", "file-create", {"name": "roteiro", "content": "abertura e fechamento", "gdoc": True, "account": None}),
    ("cria um arquivo chamado plano.md na pasta projetos no drive com o texto: primeiro passo", "file-create", {"name": "plano.md", "content": "primeiro passo", "folder": "projetos", "account": "google"}),
    ("substitui o texto do arquivo lista de compras por: pão, leite", "file-replace", {"words": "lista de compras", "content": "pão, leite"}),
    ("guarda esse pdf no onedrive na pasta recibos", "file-save", {"kind": "pdf", "folder": "recibos", "account": "microsoft"}),
    ("salva o anexo 3", "file-save", {"attachment": 3}),
    ("guarda esse arquivo no onedrive", "file-save", {"account": "microsoft"}),
    # --- files: en
    ("create a file named ideas.md with the text: buy blue paint", "file-create", {"name": "ideas.md", "content": "buy blue paint"}),
    ("save a note called groceries.txt saying bread and milk", "file-create", {"name": "groceries.txt", "content": "bread and milk"}),
    ("replace the text of the file grocery list with: bread, milk", "file-replace", {"words": "grocery list", "content": "bread, milk"}),
    ("save this pdf to my onedrive in the folder invoices", "file-save", {"kind": "pdf", "folder": "invoices", "account": "microsoft"}),
    ("save attachment 2", "file-save", {"attachment": 2}),
    ("upload this file to my drive", "file-save", {"account": "google"}),
    # --- no write form: the line goes on as before
    ("cria um documento sobre o lançamento", None, {}),
    ("agende o post para sexta", None, {}),
    ("marca o dentista", None, {}),
    ("remarca o evento", None, {}),
    ("remarca o evento 2", None, {}),
    ("cancela o evento 4 porque choveu", None, {}),
    ("remarca o evento 2 para sexta às 15h porque choveu", "event-change", {}),          # no change form, and NR-1 would make a new event of it: the sentence "a change is asked by number"
    ("cria um arquivo chamado ideias.md", None, {}),
    ("cria um arquivo com o texto: comprar tinta", None, {}),
    ("salva o arquivo", None, {}),
    ("salva o relatório no servidor", None, {}),
    ("marca dentista quinta às 10h e me lembra de levar o cartão", None, {}),
    ("move o evento 2", None, {}),
    ("muda o modelo do agente", None, {}),
    ("what is on my calendar tomorrow", None, {}),
    ("cancel the subscription", None, {}),
    ("create a document about the launch", None, {}),
    ("save the report on the server", None, {}),
    ("reschedule the meeting", None, {}),
]
RECURRING = ["marca yoga toda segunda às 7h", "add to my calendar yoga every Monday at 7am"]
