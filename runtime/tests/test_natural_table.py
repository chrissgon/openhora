"""The table of natural requests (package NR-2, runtime/natural.py): the walk of `operations.OPERATIONS` that fails when an operation has no class,
the classes pinned (a change of class changes this file too, on purpose), the tier-1 forms (language data, closed, no open tail), the lines of the review's
table that must reach the router, and the check that believes (or refuses) what a router named against the person's line. Pure: no store, no model, no
network. Every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_natural_table.py
"""
from __future__ import annotations

import re

import pytest

import standin_tree as st

natural = st.load("natural")
operations = st.load("operations")
phrases = st.load("phrases")
nt = st.load("natural_time")

R = {"status", "progress", "pending", "task", "agents", "skills", "costs", "artifacts", "artifact", "instructions", "routines", "sources", "attachments",
     "reminders", "flows", "flow-check", "connections", "commands", "items", "file-read", "research"}      # NR-5 (Q6): items, the numbered messages and events; S8: file-read, the text of a file by its name
N = {"remind", "reminder-forget", "reminder-restore"}
W = {"cancel", "stop-task", "retry", "routine-pause", "routine-cancel", "routine-create", "routine-change", "attachment-add", "attachment-discard"}
D = {"approve", "reject", "release", "answer", "go-ahead"}
E = {"event-create", "event-change", "event-cancel", "mail-send", "mail-reply", "mail-draft", "mail-archive", "mail-move", "mail-mark", "mail-trash",
     "file-create", "file-replace", "file-save", "file-trash"}
WORK = {"say", "request", "route", "ask"}
CLASS_SET = {"R", "N", "W", "D", "E", "G", "work"}
OPS = {row["name"] for row in operations.OPERATIONS}


def of(cls):
    return {name for name, c in natural.CLASSES.items() if c == cls}


def forms():
    """{operation: [form, ...]} over every language table."""
    out = {}
    for given in natural._requests():
        for op, compiled in given["forms"].items():
            out.setdefault(op, []).extend(f.pattern for f in compiled)
    return out


# --- the walk -----------------------------------------------------------------------------------------------------------------------------------


def test_every_operation_of_the_table_has_a_row_and_one_class_so_that_nothing_is_left_unclassified():
    missing = sorted(OPS - set(natural.CLASSES))
    assert not missing, f"operations with no class in runtime/natural.py CLASSES: {missing}"
    assert not sorted(OPS - set(natural.NATURAL)), "operations with no row in NATURAL"
    assert set(natural.CLASSES) == OPS, sorted(set(natural.CLASSES) ^ OPS)      # a class for something that is not an operation: nothing is planned any more
    assert set(natural.NATURAL) == set(natural.CLASSES)
    assert set(natural.CLASSES.values()) <= CLASS_SET


def test_every_operation_reachable_from_the_conversation_the_page_or_a_messaging_app_is_classified_and_none_is_left_to_a_guess():
    for row in operations.OPERATIONS:
        reachable = {"chat", "page", "messaging", "mcp"} & set(row["channels"])
        if reachable:
            assert natural.class_of(row["name"]) in CLASS_SET, row["name"]


def test_the_classes_are_pinned_a_move_between_classes_changes_this_file_too():
    assert (of("R"), of("N"), of("W"), of("D"), of("work"), of("E")) == (R, N, W, D, WORK, E)
    assert of("G") == OPS - R - N - W - D - WORK - E, "everything else is gated elsewhere, by name"
    assert of("G") >= {"give-consent", "set-mode", "set-model", "config", "accept-config", "routine-approve", "routine-resume", "instructions-set",
                       "instructions-add", "source-add", "flow-save", "stage-file", "sync", "hand-over", "dispatch", "verdict", "approve-policy"}


def test_nothing_is_planned_any_more_and_the_effects_are_operations_that_end_in_a_card():
    assert natural.PLANNED == () and not E - OPS, "the writes of SPEC-SECRETARY-WRITES exist: each is an operation, and a line only names it"
    for name in E:
        assert any(name in operations.GROUPS[g]["operations"] for g in operations.GROUPS), name      # in a group of the channel policy, like any other
    assert natural.operation_of("calendar-event-create") == "event-create" and natural.operation_of("remind") == "remind"


def test_the_safety_of_the_classes_follows_from_the_groups_of_the_table():
    """The operations that decide, consent, change a mode, write the instructions, register or import a source, save a flow or sync are never run from a line."""
    for group in ("set-mode", "consent", "routine-approve", "instructions-write", "flow-write", "documents", "dispatch", "verdict"):
        for name in operations.GROUPS[group]["operations"]:
            assert natural.class_of(name) == "G", (group, name)
    for name in operations.GROUPS["sources"]["operations"]:
        assert natural.class_of(name) == ("R" if name == "sources" else "G"), name
    for name in ("approve", "reject", "release", "answer", "go-ahead"):
        assert natural.class_of(name) == "D"
    for name in R - {"research"}:      # a read changes nothing: it is in a read group, or a read of the person's own files, reminders or sources, and calls no model
        row = operations.by_name(name)
        assert row["model"] is False, name
        assert any(name in operations.GROUPS[g]["operations"] for g in ("read", "sources", "add-sources", "reminders", "read-files")), name
    # R2-F1: `research` is the one read that calls a model (a web search run by the research skill). It changes nothing and reads nothing of the person's, and it has a group of its own,
    # in no default policy, so that no sender gets it from a group that was granted for another reason.
    row = operations.by_name("research")
    assert row["model"] is True and row["channels"] == ("terminal", "messaging")
    assert operations.GROUPS["research"] == {"operations": ("research",), "kind": None}
    assert [g for g, spec in operations.GROUPS.items() if "research" in spec["operations"]] == ["research"]
    for name, cls in natural.CLASSES.items():      # an operation that is only the terminal's is never run from a line
        if operations.by_name(name)["channels"] == ("terminal",):
            assert cls == "G", name
    for group in ("calendar-write", "files-write", "mail-send"):      # a write to the person's accounts is an effect: its card, never a line
        for name in operations.GROUPS[group]["operations"]:
            assert natural.class_of(name) == "E", name


def test_a_row_has_slots_of_known_kinds_that_fill_real_parameters_and_forms_belong_to_a_row():
    for name, row in natural.NATURAL.items():
        assert row["what"], name
        for slot, (kind, param) in row["slots"].items():
            assert kind in ("int", "ints", "word", "span", "when"), (name, slot)
            assert param in {a["name"] for a in operations.by_name(name)["args"]}, (name, slot, param)
    assert set(forms()) <= set(natural.NATURAL)
    assert not set(forms()) & {"remind", "reminders", "reminder-forget", "reminder-restore"}, "the reminders are the intents of `candidate`, not forms"


def test_the_forms_are_language_data_closed_phrases_with_the_same_operations_in_every_language():
    tables = nt.languages()
    assert len(tables) >= 2
    for table in tables:
        natural.check_requests(table)
        for op, given in table["requests"]["forms"].items():
            for form in given:
                assert ".*" not in form and ".+" not in form, (table["tag"], op, form)
                re.compile(form.replace("{n}", natural.NUMBER))
    assert set(tables[0]["requests"]["forms"]) == set(tables[1]["requests"]["forms"]), "a form of one language has its counterpart in the other"
    with_n = {op for op in natural.NATURAL if natural.CLASSES[op] != "E" and any(v[0] == "int" for v in natural.NATURAL[op]["slots"].values())}      # the E rows have slots for the write forms of NR-5, which are not tier-1 forms
    for op, given in tables[0]["requests"]["forms"].items():
        assert any("{n}" in f for f in given) == (op in with_n and op not in {"pending", "routines", "reminder-restore", "answer"}), op
    for open_ended in (r"approve .*", r"approve .+", r"show( \w+)*", r"show( \w+)+", r"show\S+", r"show\s", r"show *", r"show a+", r"show [a-z]+", r"show [a-z]", r"show{1,}",
                       r"show a{2,}", r"show \d", r"show (?=a)", r"show (?!a)", r"show (?P<x>a)", r"^show$", r"show.", r"show\b", r"show [^a]"):
        with pytest.raises(ValueError, match="not a closed phrase"):
            natural.check_requests(dict(tables[0], requests={"forms": {"approve": [open_ended]}}))
    for closed in (r"show( the)? task {n}", r"(?:show|tell me) it", r"show [ao]", r"show( it| them)?"):
        natural.check_requests(dict(tables[0], requests={"forms": {"approve": [closed]}}))
    with pytest.raises(ValueError, match="not an operation"):
        natural.check_requests(dict(tables[0], requests={"forms": {"no-such-operation": [r"x"]}}))
    with pytest.raises(ValueError, match="requests is a dict"):
        natural.check_requests(dict(tables[0], requests={"surprise": []}))


# --- tier 1: the forms ----------------------------------------------------------------------------------------------------------------------------

SAMPLES = {
    "pending": ["pendencias", "o que tenho para aprovar", "what do I need to approve?", "my pending decisions"],
    "sources": ["quais arquivos voce tem?", "que fontes voce tem", "what files do you have", "which sources do you have?", "list the files", "lista os documentos"],
    "attachments": ["meus anexos", "what files did I send"],
    "artifacts": ["lista os artefatos", "list the artifacts"],
    "routines": ["quais rotinas eu tenho", "list my routines"],
    "skills": ["quais skills voce tem", "what skills do you have"],
    "agents": ["quais agentes existem", "list the agents"],
    "costs": ["quanto gastei hoje", "how much did we spend this week"],
    "instructions": ["mostre as instrucoes", "what are the standing instructions"],
    "flows": ["quais fluxos existem", "list the flows"],
    "connections": ["quais as conexoes", "show the connections"],
    "commands": ["ajuda", "help", "o que voce sabe fazer", "what can you do"],
    "items": ["meus e-mails", "lista os eventos", "quais e-mails chegaram", "my emails", "list my events", "show my appointments"],
    "task": ["tarefa 5", "como esta a tarefa 5", "show task 5"],
    "approve": ["aprova a entrega 21", "aprove 21", "accept delivery 21", "aceita o 21", "approve decision number 21"],
    "reject": ["rejeita o pedido 3", "reject 3"],
    "release": ["libera a entrega 9", "release delivery 9"],
    "go-ahead": ["siga com a tarefa 4", "go ahead on task 4"],
    "cancel": ["cancela o pedido 8", "cancel request 8"],
    "stop-task": ["para a tarefa 7", "stop task 7"],
    "retry": ["tenta de novo a tarefa 7", "retry task 7"],
    "routine-pause": ["pausa a rotina 2", "pause routine 2"],
    "routine-cancel": ["cancela a rotina 2", "cancel the routine 2"],
    "routine-resume": ["retoma a rotina 2", "resume routine 2"],
    "routine-approve": ["aprova a rotina 2", "approve routine 2"],
    "routine-create": ["crie uma rotina", "create a routine"],
    "routine-change": ["muda a rotina 2", "change routine 2"],
    "attachment-add": ["adiciona o arquivo 3", "add file 3"],
    "attachment-discard": ["descarta o anexo 3", "discard attachment 3"],
    "set-model": ["muda o modelo do agente", "change the model of the agent"],
    "set-mode": ["muda o modo do agente", "set the mode"],
    "config": ["mostra a configuracao", "show the configuration"],
    "accept-config": ["aceita a configuracao", "accept the config"],
    "give-consent": ["dou meu consentimento", "give my consent"],
    "instructions-set": ["muda as instrucoes do projeto", "replace the instructions"],
    "instructions-add": ["adiciona uma instrucao", "add an instruction"],
    "source-add": ["adiciona uma fonte", "register a new source"],
    "source-import": ["importa uma versao", "import a file"],
    "source-refresh": ["atualiza a fonte", "refresh the source"],
    "source-describe": ["descreve a fonte", "describe the source"],
    "flow-save": ["salva este plano", "save this flow"],
    "sync": ["sincroniza os documentos", "sync the tasks"],
    "dispatch": ["dispara o dispatcher", "run the dispatcher"],
    "run-next": ["roda a proxima tarefa", "run the next task"],
    "deps": ["instala as dependencias", "install the dependencies"],
    "verdict": ["registre um veredito", "record a verdict"],
    "proof": ["mostra a prova", "show the proof"],
    "event-change": ["remarca a reuniao", "reschedule the meeting"],
    "event-cancel": ["cancela a reuniao", "cancel the appointment"],
    "mail-send": ["manda um email", "send an email"],
    "mail-reply": ["responde ao email", "reply to the email"],
    "mail-draft": ["rascunhe um email", "draft an email"],
    "mail-archive": ["arquiva os emails", "archive the emails"],
    "mail-mark": ["marca como lido", "mark these as read"],
    "mail-trash": ["apaga o email", "delete the email"],
    "file-create": ["cria um documento", "create a document"],
    "file-save": ["salva este documento", "save this file"],
}


@pytest.mark.parametrize("op", sorted(SAMPLES))
def test_each_tier_1_form_reaches_its_operation_and_only_it(op):
    for line in SAMPLES[op]:
        found = natural.match(line)
        assert found is not None and found["op"] == op and found["tier"] == 1, (line, found)
        digits = re.findall(r"[0-9]+", natural.ascii_normal(line))
        slot = next((spec for spec in natural.NATURAL[op]["slots"].values() if spec[0] == "int"), None)
        if slot and any("{n}" in f.pattern or "(?P<n>" in f.pattern for f in [x for g in natural._requests() for x in g["forms"].get(op, ())]):
            assert found["args"] == ({slot[1]: int(digits[0])} if digits else {}), (line, found)
        else:
            assert found["args"] == {}, (line, found)


def test_every_op_with_forms_has_a_sample_and_every_sample_op_has_forms():
    assert set(SAMPLES) == set(forms())


# The lines of the independent review's table (B3): what a person writes when they ask for WORK with the same words as an operation, and the short phrases that are
# operations. None of the first reaches a form: they go to the router.
TO_THE_ROUTER = [
    "schedule the post for tomorrow at 9am", "schedule the launch post for Friday", "book a table for two on friday", "agende o post para amanha as 9",
    "agendar a publicacao do post", "agenda para mim a reuniao com o fornecedor", "write a document about our launch plan",
    "crie um documento de requisitos para o app de delivery", "cria um novo documento com a proposta comercial", "edita o documento de visao para incluir o publico jovem",
    "update the document with the new pricing", "edite o meu CV para ter Vue", "atualiza o curriculo com meu novo emprego", "muda o modelo de negocio para assinatura",
    "change the model of the pricing page", "switch mode to dark on the landing page", "muda o modo escuro do app", "salva o plano de marketing em docs", "save the plan",
    "archive the old landing page drafts", "arquiva o projeto antigo", "move the logo files to the assets folder", "coloca as imagens na pasta de assets",
    "mark the task as read", "change the meeting notes template", "move the meeting to friday", "cancel the meeting room booking feature",
    "manda um email para o cliente sobre o lancamento", "send an email campaign to our list announcing the launch", "reply to the email from the supplier",
    "import the file into the database schema", "update the source code of the login page", "refresh the source data in the dashboard",
    "describe the source of truth for prices", "add a new source of revenue to the business model", "create a routine for the database backups",
    "set up a routine check of the website", "help me write a post", "show the costs of the new feature", "give a verdict on the design", "run the tasks",
    "add an instruction to always reply in English", "edit the instructions page of onboarding", "change the instructions to the installer",
    "edit my resume", "reschedule the meeting with the vendor to friday", "delete the email campaign draft from the repo", "apague o email de boas-vindas do site",
    "send an email to ana saying the report is late", "cria um documento sobre a viagem de agosto", "approve the pull request and merge it", "aprova 3 e publica",
]
ARE_FORMS = {"help": "commands", "ajuda": "commands", "task 3": "task", "tarefa 3": "task", "approve 12345": "approve", "para a tarefa 3": "stop-task",
             "dou consentimento": "give-consent", "sync": "sync", "record a verdict": "verdict", "accept the config": "accept-config", "show me the config": "config",
             "start the dispatcher": "dispatch", "como usar isso": "commands", "what are the costs": "costs", "accept 3": "approve", "create a routine": "routine-create"}  # validate: allow english-only -- a Portuguese line is the input under test


@pytest.mark.parametrize("line", TO_THE_ROUTER)
def test_a_line_that_asks_for_work_with_the_words_of_an_operation_reaches_the_router(line):
    assert natural.match(line) is None, line
    found = natural.candidate(line)
    assert found is None or found["op"] not in ("event-create",) or "calendar" in line or "agenda" in line, (line, found)      # the reminders' own intents decide the rest


@pytest.mark.parametrize("line, op", sorted(ARE_FORMS.items()))
def test_a_short_phrase_that_is_a_form_reaches_it(line, op):
    assert natural.match(line)["op"] == op, line


@pytest.mark.parametrize("line", [
    "escreva o post de lancamento para amanha as 9", "write the launch post for tomorrow at 9", "aprova a entrega e depois publica o post",
    "cancela tudo", "how are we going to launch the site", "qual o prazo do contrato?", "o que diz meu CV sobre Vue?", "aprova", "approve",
    "tarefa", "para a tarefa", "responde: qual o status?", "/approve 12", "mande o balanco do mes para a equipe", "", "   ",
    "approve 21 and then release 22", "aprova a entrega 21 @lease",
])
def test_a_work_request_a_command_and_a_half_form_match_no_operation(line):
    assert natural.match(line) is None, line


def test_a_line_longer_than_a_form_is_a_request_not_a_form():
    assert natural.match("aprova o pedido 21 " + "e " * natural.LINE_WORDS) is None


def test_needs_names_the_group_a_messaging_sender_must_hold_for_a_tier_1_line():
    assert natural.needs("quais arquivos voce tem?") == "sources"
    assert natural.needs("pendencias") == "pending"
    assert natural.needs("aprova o 12") == "pending", "a decision is a read of its card: the group that reads"
    for line in ("cancela o pedido 8", "muda o modelo", "marca na agenda o dentista", "escreva um post", "/status", "me lembra sexta as 18h de regar as samambaias"):
        assert natural.needs(line) is None, line


def test_private_and_the_confirmation_words_are_the_reminders_and_the_tables():
    assert natural.private("me lembra amanha as 15h de buscar a encomenda") and natural.private("remind me tomorrow at 2pm to water the plants")
    assert not natural.private("what files do you have?") and not natural.private("quais sao os meus lembretes?")
    for yes in ("yes", "sim", "Sim.", "ok", "はい", "si", "oui", "да"):
        assert natural.confirm_kind(yes) == "yes", yes
    for no in ("no", "nao", "cancel", "cancela", "いいえ", "nein"):
        assert natural.confirm_kind(no) == "no", no
    for other in ("maybe", "", "3pm", "what"):
        assert natural.confirm_kind(other) is None, other


def test_the_aliases_the_cues_and_the_function_words_are_the_tables_data():
    group = natural.aliases()
    assert group["curriculo"] == group["resume"] == group["cv"] and group["relatorio"] == group["report"]
    assert "arquivo" in natural.words_of("cues") and "file" in natural.words_of("cues") and "de" in natural.words_of("short_stop")


def test_the_questions_and_replies_of_a_reminder_are_said_in_one_place_in_the_projects_language():
    draft = {"need": "confirm", "text": "pay the rent", "readings": [{"date": "2026-10-19", "time": "09:00", "rel": 1, "far": False, "rolled": False}]}
    sentence, keep = natural.question(draft, None, True)
    assert sentence == "I understood: tomorrow, Mon 19/10, at 09:00: pay the rent. Confirm? (yes / another time)" and keep is True
    assert natural.question(draft, None, False)[0] == "I understood: tomorrow, Mon 19/10, at 09:00. Confirm? (yes / another time)"
    assert natural.question({"need": "recurring"}, None)[1] is False
    done = {"reminder": {"id": 4, "text": "pay the rent"}, "human": {"date": "2026-10-19", "time": "09:00", "rel": 1, "far": False, "zone": "BRT", "rolled": False}}
    assert natural.made_sentence(done, None, True) == "Reminder #4: tomorrow, Mon 19/10, at 09:00 (BRT): pay the rent. To undo: /forget 4."
    assert natural.made_sentence(done, None, False) == "Reminder #4: tomorrow, Mon 19/10, at 09:00 (BRT). To undo: /forget 4."
    assert natural.forgot_sentence(done, None, True).startswith("Reminder #4 cancelled: tomorrow, Mon 19/10, at 09:00 (BRT): pay the rent")
    sentence, forget = natural.forget_question([{"preview": {"id": 4, "text": "pay the rent"}, "human": done["human"]}], None, True)
    assert sentence.startswith("Cancel reminder #4: ") and forget["need"] == "forget" and forget["ids"] == [4]


# --- believing what a router named ----------------------------------------------------------------------------------------------------------------

LINE = "me lembra amanha às 15h de buscar a encomenda"


def check(name, slots=None, when=None, line=LINE):
    return natural.check_operation(name, slots or {}, when, line)


def test_an_operation_in_the_table_with_no_arguments_is_believed():
    assert check("sources", line="what files do you have?") == {"ok": True, "name": "sources", "args": {}, "when": None}
    assert check("ask", line="o que diz meu CV sobre Vue?")["ok"] is True


def test_a_name_that_is_not_in_the_table_or_is_the_planning_agents_own_work_is_refused():
    for name in ("delete-everything", "Sources", "", "run-next ", "say", "request", "route"):
        assert check(name)["ok"] is False, name
    assert check(None)["ok"] is False


def test_the_router_cannot_name_an_argument_a_row_does_not_have_and_ask_has_no_arguments_at_all():
    assert check("sources", {"text": "x"})["ok"] is False
    assert check("ask", {"question": "o que diz meu CV sobre Vue?"}, line="o que diz meu CV sobre Vue?")["ok"] is False


def test_an_id_is_a_number_written_in_the_line_and_nothing_else():
    assert check("reminder-forget", {"id": "3"}, line="esquece o lembrete 3")["args"] == {"reminder_id": 3}
    assert check("reminder-forget", {"id": "3"}, line="forget reminder 13")["ok"] is False, "13 is written, 3 is not"
    assert check("reminder-forget", {"id": "4"}, line="esquece o lembrete 3")["ok"] is False
    assert check("reminder-forget", {"id": "three"}, line="esquece o lembrete 3")["ok"] is False
    assert check("reminder-forget", {"id": "-3"}, line="esquece o lembrete 3")["ok"] is False
    assert check("reminder-forget", {"id": "3.0"}, line="esquece o lembrete 3")["ok"] is False
    assert check("reminder-forget", {"id": "3"}, line="esquece o lembrete ３")["ok"] is True, "a full-width digit is the digit"


def test_a_word_slot_is_a_piece_of_the_line_as_written_and_an_invented_path_is_refused():
    line = "mostra o arquivo docs/plans/launch.md"
    assert check("artifact", {"path": "docs/plans/launch.md"}, line=line)["args"] == {"path": "docs/plans/launch.md"}
    assert check("artifact", {"path": "docs/plans/other.md"}, line=line)["ok"] is False
    assert check("artifact", {"path": "../../etc/passwd"}, line=line)["ok"] is False
    assert check("artifact", {"path": "docs/plans/launch.md and more"}, line=line)["ok"] is False
    assert check("artifact", {"path": "docs/plans"}, line=line)["ok"] is False, "a piece inside a longer word is not a word of the line"
    assert check("artifact", {"path": "launch.md"}, line=line)["ok"] is False
    assert check("artifact", {"path": "docs/plans/launch.md"}, line="mostra docs/plans/launch.md.")["ok"] is True, "a full stop that ends the line is not part of the word"
    assert check("costs", {"since": "2026-10-01"}, line="what did it cost since 2026-10-01?")["ok"] is True
    assert check("costs", {"since": "2026-10"}, line="what did it cost since 2026-10-01?")["ok"] is False


def test_a_text_is_a_span_of_the_normalised_line_in_any_script_and_a_text_the_line_does_not_hold_is_refused():
    assert check("remind", {"text": "buscar a encomenda"})["args"] == {"text": "buscar a encomenda"}
    assert check("remind", {"text": "Buscar a Encomenda"})["ok"] is True, "case is the person's own spelling"
    assert check("remind", {"text": "trocar o filtro d\u00e1gua"}, line="me lembra de trocar o filtro dagua")["ok"] is True, "and so are accents"
    assert check("remind", {"text": "BUSCAR A ENCOMENDA."})["ok"] is True
    assert check("remind", {"text": "podar a cerca viva"})["ok"] is False
    assert check("remind", {"text": ""})["ok"] is False
    assert check("remind", {"text": "x" * 301}, line="x" * 400)["ok"] is False
    spanish = "recuérdame el viernes a las 17 recoger el paquete en la porteria"
    assert check("remind", {"text": "recoger el paquete en la porteria"}, line=spanish)["ok"] is True
    assert check("remind", {"text": "recordar al dentista"}, line=spanish)["ok"] is False
    japanese = "金曜の17時に荷物を受け取ると私に思い出させて"
    assert check("remind", {"text": "荷物を受け取る"}, line=japanese)["ok"] is True
    assert check("remind", {"text": "髪を染める"}, line=japanese)["ok"] is False


def test_a_when_line_has_the_shape_of_a_date_and_a_time_and_only_a_row_with_a_time_takes_one():
    assert check("remind", {"text": "buscar a encomenda"}, when="2026-10-19 13:00")["when"] == "2026-10-19 13:00"
    for bad in ("2026-10-19", "19/10/2026 13:00", "2026-10-19 13:00:00", "tomorrow 13:00", "2026-10-19T13:00", "2026-13-40 25:61", "2026-02-30 10:00",
                "2026-10-19  13:00", " 2026-10-19 13:00"):
        assert check("remind", {"text": "buscar a encomenda"}, when=bad)["ok"] is False, bad
    assert check("sources", when="2026-10-19 13:00", line="what files do you have")["ok"] is False
    assert check("ask", when="2026-10-19 13:00", line="what does it say?")["ok"] is False
    assert check("remind", {"when": "2026-10-19 13:00"})["ok"] is False, "a time is the When line, never an Argument line"


def test_with_no_line_nothing_is_believed():
    for line in (None, "", "   "):
        assert natural.check_operation("sources", {}, None, line)["ok"] is False
