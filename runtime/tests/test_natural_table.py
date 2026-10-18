"""The table of natural requests (package NR-2, runtime/natural.py): the walk of `operations.OPERATIONS` that fails when an operation has no row and no class,
the classes pinned (a change of class changes this file too, on purpose), the tier-1 forms, and the check that believes (or refuses) what a router named
against the person's line. Pure: no store, no model, no network. Every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_natural_table.py
"""
from __future__ import annotations

import re

import pytest

import standin_tree as st

natural = st.load("natural")
operations = st.load("operations")

R = {"status", "progress", "pending", "task", "agents", "skills", "costs", "artifacts", "artifact", "instructions", "routines", "sources", "attachments",
     "reminders", "flows", "flow-check", "connections", "commands"}
N = {"remind", "reminder-forget"}
W = {"cancel", "stop-task", "retry", "routine-pause", "routine-cancel", "routine-create", "routine-change", "attachment-add", "attachment-discard"}
D = {"approve", "reject", "release", "answer", "go-ahead"}
WORK = {"say", "request", "route", "ask"}
E = set(natural.PLANNED)
CLASS_SET = {"R", "N", "W", "D", "E", "G", "work"}
OPS = {row["name"] for row in operations.OPERATIONS}


def of(cls):
    return {name for name, c in natural.CLASSES.items() if c == cls}


# --- the walk -----------------------------------------------------------------------------------------------------------------------------------


def test_every_operation_of_the_table_has_a_row_and_one_class_so_that_nothing_is_left_unclassified():
    missing = sorted(OPS - set(natural.CLASSES))
    assert not missing, f"operations with no class in runtime/natural.py CLASSES: {missing}"
    assert not sorted(OPS - set(natural.NATURAL)), "operations with no row in NATURAL"
    assert set(natural.CLASSES) <= OPS | E, sorted(set(natural.CLASSES) - OPS - E)      # a class for something that is neither an operation nor planned
    assert set(natural.NATURAL) == set(natural.CLASSES)
    assert set(natural.CLASSES.values()) <= CLASS_SET


def test_every_operation_reachable_from_the_conversation_the_page_or_a_messaging_app_is_classified_and_none_is_left_to_a_guess():
    for row in operations.OPERATIONS:
        reachable = {"chat", "page", "messaging", "mcp"} & set(row["channels"])
        if reachable:
            assert natural.class_of(row["name"]) in CLASS_SET, row["name"]


def test_the_classes_are_pinned_a_move_between_classes_changes_this_file_too():
    assert (of("R"), of("N"), of("W"), of("D"), of("work"), of("E")) == (R, N, W, D, WORK, E)
    assert of("G") == OPS - R - N - W - D - WORK, "everything else is gated elsewhere, by name"
    assert of("G") >= {"give-consent", "set-mode", "set-model", "config", "accept-config", "routine-approve", "routine-resume", "instructions-set",
                       "instructions-add", "source-add", "flow-save", "stage-file", "sync", "hand-over", "dispatch", "verdict", "approve-policy"}


def test_a_planned_effect_is_not_an_operation_yet_and_leaves_the_list_when_it_becomes_one():
    assert not E & OPS, "an operation that exists is classified as what it is, and leaves PLANNED"
    for name in E:
        assert natural.CLASSES[name] == "E" and natural.NATURAL[name]["what"].endswith("(planned)")


def test_the_safety_of_the_classes_follows_from_the_groups_of_the_table():
    """The operations that decide, consent, change a mode, write the instructions, register or import a source, save a flow or sync are never run from a line."""
    for group in ("set-mode", "consent", "routine-approve", "instructions-write", "flow-write", "documents", "dispatch", "verdict"):
        for name in operations.GROUPS[group]["operations"]:
            assert natural.class_of(name) == "G", (group, name)
    for name in operations.GROUPS["sources"]["operations"]:
        assert natural.class_of(name) == ("R" if name == "sources" else "G"), name
    for name in ("approve", "reject", "release", "answer", "go-ahead"):
        assert natural.class_of(name) == "D"
    for name in R:      # a read changes nothing: it is in a read group, or a read of the person's own files, reminders or sources, and calls no model
        row = operations.by_name(name)
        assert row["model"] is False, name
        assert any(name in operations.GROUPS[g]["operations"] for g in ("read", "sources", "add-sources", "reminders")), name
    for name, cls in natural.CLASSES.items():      # an operation that is only the terminal's is never run from a line
        if name in OPS and operations.by_name(name)["channels"] == ("terminal",):
            assert cls == "G", name


def test_a_row_has_slots_of_known_kinds_that_fill_real_parameters_and_forms_belong_to_a_row():
    for name, row in natural.NATURAL.items():
        assert row["what"], name
        for slot, (kind, param) in row["slots"].items():
            assert kind in ("int", "word", "span", "when"), (name, slot)
            if name in OPS:
                assert param in {a["name"] for a in operations.by_name(name)["args"]}, (name, slot, param)
    assert set(natural.FORMS) <= set(natural.NATURAL)
    for forms in natural.FORMS.values():
        for form in forms:
            re.compile(form)
    phrases = st.load("phrases")
    for name in E:
        key = "NAT_E_" + name.upper().replace("-", "_")
        assert key in phrases.TABLE["en"] and key in phrases.TABLE["pt-BR"], key


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
    "approve": ["aprova o plano 12", "aprove 12", "approve plan 12", "aprova o 12", "approve decision number 12"],
    "reject": ["rejeita o pedido 3", "reject 3"],
    "release": ["libera a entrega 9", "release delivery 9"],
    "go-ahead": ["siga com a tarefa 4", "go ahead on task 4"],
    "cancel": ["cancela o pedido 4", "cancel request 4"],
    "stop-task": ["para a tarefa 7", "stop task 7"],
    "retry": ["tenta de novo a tarefa 7", "retry task 7"],
    "routine-pause": ["pausa a rotina 2", "pause routine 2"],
    "routine-cancel": ["cancela a rotina 2", "cancel the routine 2"],
    "routine-resume": ["retoma a rotina 2", "resume routine 2"],
    "routine-approve": ["aprova a rotina 2", "approve routine 2"],
    "routine-create": ["crie uma rotina que resume a semana", "create a routine for the weekly report"],
    "routine-change": ["muda a rotina 2 para as 8h", "change routine 2 to 8 am"],
    "attachment-add": ["adiciona o arquivo 3", "add file 3"],
    "attachment-discard": ["descarta o anexo 3", "discard attachment 3"],
    "task": ["tarefa 5", "como esta a tarefa 5", "show task 5"],
    "set-model": ["muda o modelo do agente de negócio", "change the model of the agent"],
    "set-mode": ["muda o modo do agente", "set the mode to autonomous"],
    "config": ["mostra a configuracao", "show the configuration"],
    "accept-config": ["aceita a configuracao", "accept the config"],
    "give-consent": ["dou meu consentimento", "give my consent"],
    "instructions-set": ["muda as instrucoes do projeto", "replace the instructions"],
    "instructions-add": ["adiciona uma instrucao", "add an instruction: always answer short"],
    "source-add": ["adiciona uma fonte", "register a new source"],
    "source-import": ["importa uma versao", "import a file"],
    "source-refresh": ["atualiza a fonte lease", "refresh the source"],
    "source-describe": ["descreve a fonte lease", "describe the source"],
    "flow-save": ["salva este plano", "save this flow"],
    "sync": ["sincroniza os documentos", "sync the tasks"],
    "dispatch": ["dispara o dispatcher", "run the dispatcher"],
    "run-next": ["roda a próxima tarefa", "run the next task"],
    "deps": ["instala as dependências", "install the dependencies"],
    "verdict": ["registre um veredito", "record a verdict"],
    "proof": ["mostra a prova", "show the proof"],
    "calendar-event-create": ["marca na agenda o dentista sexta às 9", "marque na agenda a reuniao", "agende a visita ao museu", "schedule the dentist friday at 9",
                              "put it on my calendar", "cria um evento para sábado"],
    "calendar-event-change": ["remarca a reuniao de sexta", "reschedule the meeting"],
    "calendar-event-cancel": ["cancela a reuniao de sexta", "cancel the appointment on friday"],
    "mail-send": ["manda um email para a Ana", "send an email to Ana"],
    "mail-reply": ["responde o email da Ana", "reply to Ana's email"],
    "mail-draft": ["rascunhe um email para a Ana", "draft an email to Ana"],
    "mail-organize": ["arquiva", "archive the newsletters", "marca como lido", "mark these as read", "apague o email da Ana"],
    "document-create": ["crie um documento novo sobre a viagem", "create a document about the trip"],
    "document-edit": ["edite o meu CV", "edit my resume", "edita o documento da viagem"],
    "document-save": ["salva este documento", "save the document"],
}


@pytest.mark.parametrize("op", sorted(SAMPLES))
def test_each_tier_1_form_reaches_its_operation_and_only_it(op):
    for line in SAMPLES[op]:
        found = natural.match(line)
        assert found is not None and found["op"] == op and found["tier"] == 1, (line, found)
        digits = re.findall(r"[0-9]+", natural.ascii_normal(line))
        slot = next((spec for spec in natural.NATURAL[op]["slots"].values() if spec[0] == "int"), None)
        if slot and "n" in {m for form in natural.FORMS[op] for m in re.compile(form).groupindex}:
            assert found["args"] == ({slot[1]: int(digits[0])} if digits else {}), (line, found)
        else:
            assert found["args"] == {}, (line, found)


def test_every_op_with_forms_has_a_sample_and_every_sample_op_has_forms():
    assert set(SAMPLES) == set(natural.FORMS)


@pytest.mark.parametrize("line", [
    "escreva o post de lancamento para amanha às 9", "write the launch post for tomorrow at 9", "aprova o plano e depois publica o post",
    "cancela tudo", "how are we going to launch the site", "qual o prazo do contrato?", "o que diz meu CV sobre Vue?", "aprova", "approve",
    "tarefa", "para a tarefa", "responde: qual o status?", "/approve 12", "mande o resumo da semana para o time", "", "   ",
    "approve 12 and then release 13", "aprova o plano 12 @lease",
])
def test_a_work_request_a_command_and_a_half_form_match_no_operation(line):
    assert natural.match(line) is None, line


def test_a_line_longer_than_a_form_is_a_request_not_a_form():
    assert natural.match("aprova o plano 12 " + "e " * natural.LINE_WORDS) is None


def test_needs_names_the_group_a_messaging_sender_must_hold_for_a_tier_1_line():
    assert natural.needs("quais arquivos voce tem?") == "sources"
    assert natural.needs("pendencias") == "pending"
    assert natural.needs("aprova o 12") == "pending", "a decision is a read of its card: the group that reads"
    for line in ("cancela o pedido 4", "muda o modelo", "marca na agenda o dentista", "escreva um post", "/status"):
        assert natural.needs(line) is None, line


def test_the_reminder_rows_are_the_class_and_the_slots_only_their_forms_and_their_time_parser_are_package_nr_1s():
    assert natural.CLASSES["remind"] == "N" and natural.CLASSES["reminders"] == "R" and natural.CLASSES["reminder-forget"] == "N"
    assert set(natural.NATURAL["remind"]["slots"]) >= {"text", "when"}
    assert "remind" not in natural.FORMS and "reminders" not in natural.FORMS


# --- believing what a router named ----------------------------------------------------------------------------------------------------------------

LINE = "me lembra amanha às 13h do corte de cabelo"


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


def test_a_text_is_a_span_of_the_normalised_line_in_any_script_and_a_text_the_line_does_not_hold_is_refused():
    assert check("remind", {"text": "corte de cabelo"})["args"] == {"text": "corte de cabelo"}
    assert check("remind", {"text": "Corte de Cabelo"})["ok"] is True, "case is the person's own spelling"
    assert check("remind", {"text": "cortar o cab\u00ealo"}, line="me lembra de cortar o cabelo")["ok"] is True, "and so are accents"
    assert check("remind", {"text": "CORTE DE CABELO."})["ok"] is True
    assert check("remind", {"text": "cortar o cabelo"})["ok"] is False
    assert check("remind", {"text": ""})["ok"] is False
    assert check("remind", {"text": "x" * 301}, line="x" * 400)["ok"] is False
    spanish = "recuérdame mañana a las 13 cortarme el pelo"
    assert check("remind", {"text": "cortarme el pelo"}, line=spanish)["ok"] is True
    assert check("remind", {"text": "recordar al dentista"}, line=spanish)["ok"] is False
    japanese = "明日の13時に髪を切ると私に思い出させて"
    assert check("remind", {"text": "髪を切る"}, line=japanese)["ok"] is True
    assert check("remind", {"text": "髪を染める"}, line=japanese)["ok"] is False


def test_a_when_line_has_the_shape_of_a_date_and_a_time_and_only_a_row_with_a_time_takes_one():
    assert check("remind", {"text": "corte de cabelo"}, when="2026-10-19 13:00")["when"] == "2026-10-19 13:00"
    for bad in ("2026-10-19", "19/10/2026 13:00", "2026-10-19 13:00:00", "tomorrow 13:00", "2026-10-19T13:00", "2026-13-40 25:61", "2026-02-30 10:00",
                "2026-10-19  13:00", " 2026-10-19 13:00"):
        assert check("remind", {"text": "corte de cabelo"}, when=bad)["ok"] is False, bad
    assert check("sources", when="2026-10-19 13:00", line="what files do you have")["ok"] is False
    assert check("ask", when="2026-10-19 13:00", line="what does it say?")["ok"] is False
    assert check("remind", {"when": "2026-10-19 13:00"})["ok"] is False, "a time is the When line, never an Argument line"


def test_with_no_line_nothing_is_believed():
    for line in (None, "", "   "):
        assert natural.check_operation("sources", {}, None, line)["ok"] is False
