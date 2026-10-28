"""The guards of the to-do list's effect and step, each tested on its own (package CB-5, after the review): `effect_tasks.execute` and `effect_tasks.preflight` against a fake `call`, and
`step_tasks_item._prepare` against a fake `tasks_read` service. No server, no provider, no model; every name fictional.

A guard that no test removes is a guard nothing holds: each test below fails when its guard is taken out (the mutants are listed in the pull request body, and `GUARDS` below names the
guard each test is for, so that a test that stops naming one is seen). Every group has a vacuity companion: the call without the fault goes through, so that a test that refused for another
reason would not pass.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_tasks_guards.py
"""
from __future__ import annotations

import copy
import types

import pytest

import standin_tree as st

effects = st.load("effects")
effect_tasks = st.load("effect_tasks")
project_config = st.load("project_config")
steps = st.load("steps")
step_tasks_item = st.load("step_tasks_item")
tasks_document = st.load("tasks_document")
tasks_reader = st.load("tasks_reader")

SHA = "a" * 64
OTHER_SHA = "b" * 64
LIST_G = "default"
LIST_M = "AAMkADIyAAAAABrJAAA="


def add_doc(**over):
    kw = dict(task_id=7, account="google", address="pat@example.com", list_name="tarefas", list_id=LIST_G, operation="add", title="comprar café", dry_run_sha256=SHA)
    kw.update(over)
    return tasks_document.document(**kw)


def done_doc(**over):
    kw = dict(task_id=8, account="google", address="pat@example.com", list_name="tarefas", list_id=LIST_G, operation="complete", title="ligar para o dentista", remote_id="t2",
              base_etag='"E1"', read_at="2026-10-28T12:00:00Z", dry_run_sha256=SHA)
    kw.update(over)
    return tasks_document.document(**kw)


def approval(doc, **over):
    out = {"scope": "action", "status": "pending-execution", "payload_sha256": tasks_document.sha(effects._text(doc))}
    out.update(over)
    return out


class Call:
    """The fake `call(verb, args, implementation=)` the effect is handed: it records every call and answers from `answers`."""

    def __init__(self, doc, task=None, shown=None, done=None):
        self.doc, self.calls = doc, []
        self.task = {"found": True, "task": {"id": doc["task_id"], "title": doc["title"], "status": "open", "etag": doc["base_etag"]}} if task is None else task
        self.shown = {"would_sha256": doc["dry_run_sha256"]} if shown is None else shown
        self.done = {"done": True, "replayed": False, "task_id": doc["task_id"] or "g9", "etag": '"E2"'} if done is None else done

    def __call__(self, verb, args, implementation=None):
        self.calls.append((verb, tuple(args), implementation))
        if verb == "task-get":
            return self.task
        return self.shown if "--dry-run" in args else self.done

    def verbs(self):
        return [(v, "--confirmed" in a) for v, a, _i in self.calls]


def run(doc, call=None, key=None, appr=None):
    call = call or Call(doc)
    return effect_tasks.execute(doc, appr if appr is not None else approval(doc), call, key if key is not None else doc["idempotency_key"]), call


def refused(doc, kind, **kw):
    call = kw.pop("call", None) or Call(doc, **kw)
    with pytest.raises(effects.EffectError) as e:
        run(doc, call)
    assert e.value.kind == kind
    return e.value, call


# --- execute: the approval, the key, the preview ------------------------------------------------------------------------------------------------


def test_vacuity_the_add_and_the_completion_go_through_when_nothing_is_wrong():
    done, call = run(add_doc())
    assert done["done"] is True and call.verbs() == [("task-insert", False), ("task-insert", True)]
    done, call = run(done_doc())
    assert done["operation"] == "complete" and call.verbs() == [("task-get", False), ("task-complete", False), ("task-complete", True)]


@pytest.mark.parametrize("make", (add_doc, done_doc), ids=("add", "complete"))
def test_guard_approval_hash_another_hash_or_another_scope_or_status_writes_nothing(make):
    """GUARD execute.approval: `payload_sha256` is the hash of exactly this document, scope `action`, status `pending-execution`."""
    doc = make()
    for bad in (approval(doc, payload_sha256=OTHER_SHA), approval(doc, scope="plan"), approval(doc, status="approved"), None, {}, "yes"):
        with pytest.raises(effects.EffectError) as e:
            effect_tasks.execute(doc, bad, call := Call(doc), doc["idempotency_key"])
        assert e.value.kind == "deviation" and call.calls == [], bad
    changed = copy.deepcopy(doc)
    changed["title"] = "comprar vinho" if doc["operation"] == "add" else "outra tarefa"      # a document that is not the one approved
    changed["idempotency_key"] = tasks_document.key_of(changed)
    with pytest.raises(effects.EffectError) as e:
        effect_tasks.execute(changed, approval(doc), call := Call(changed), changed["idempotency_key"])
    assert e.value.kind == "deviation" and call.calls == []


@pytest.mark.parametrize("make", (add_doc, done_doc), ids=("add", "complete"))
def test_guard_key_a_key_the_document_does_not_derive_writes_nothing(make):
    """GUARD execute.key: the key handed is the document's own."""
    doc = make()
    for bad in ("todo-" + "0" * 32, "", "wb-p1", doc["idempotency_key"] + "0"):
        with pytest.raises(effects.EffectError) as e:
            effect_tasks.execute(doc, approval(doc), call := Call(doc), bad)
        assert e.value.kind == "deviation" and call.calls == [], bad


@pytest.mark.parametrize("make", (add_doc, done_doc), ids=("add", "complete"))
def test_guard_dry_run_a_writer_that_would_send_another_request_is_never_confirmed(make):
    """GUARD execute.dry_run_hash: what the writer's dry run hashes to is the document's `dry_run_sha256`."""
    doc = make()
    for shown in ({"would_sha256": OTHER_SHA}, {"would_sha256": None}, {}, "x", None):
        e, call = refused(doc, "deviation", shown=shown if shown is not None else "null")
        assert not any(confirmed for _v, confirmed in call.verbs()), shown
    assert ("task-insert" if doc["operation"] == "add" else "task-complete", True) not in Call(doc).verbs()


def test_guard_dry_run_is_asked_before_the_confirmed_call_and_with_the_same_flags():
    doc = add_doc()
    _done, call = run(doc)
    (v1, a1, i1), (v2, a2, i2) = call.calls
    assert a1[-1] == "--dry-run" and a2[-1] == "--confirmed" and a1[:-1] == a2[:-1] and i1 == i2 == "google-tasks"
    assert "--spec-file" in a1 and "comprar café" not in " ".join(a1), "the words of the person are in a private file, never on a command line"


def test_a_done_answer_that_is_not_a_finished_request_is_unknown():
    doc = add_doc()
    for answer in ({"done": False}, {}, "x", {"done": "true"}):
        e, call = refused(doc, "unknown", done=answer if answer != "x" else "x")
        assert e.next and call.verbs()[-1] == ("task-insert", True)


# --- execute: the version a completion rests on --------------------------------------------------------------------------------------------------


def test_guard_unchanged_the_task_is_read_again_before_anything_is_confirmed():
    """GUARD execute.unchanged_call: a completion reads the task again first, with the account, the list and the task of the document."""
    doc = done_doc()
    _done, call = run(doc)
    assert call.calls[0][0] == "task-get" and call.calls[0][1] == tuple(tasks_document.get_args(doc))
    assert [v for v, _a, _i in Call(add_doc()).calls] == [] and run(add_doc())[1].calls[0][0] == "task-insert", "an add reads no task"


def test_guard_unchanged_the_same_status_with_another_etag_is_stale_and_nothing_is_sent():
    """GUARD execute.etag: an open task with another version than the one read is stale (L56)."""
    doc = done_doc()
    moved = {"found": True, "task": {"id": "t2", "title": doc["title"], "status": "open", "etag": '"E9"'}}
    e, call = refused(doc, "stale", task=moved)
    assert call.verbs() == [("task-get", False)] and isinstance(e, effect_tasks.StaleError) and e.answer


def test_guard_unchanged_a_task_that_is_gone_is_stale_and_a_reading_that_is_no_reading_is_unknown():
    """GUARD execute.found."""
    doc = done_doc()
    e, call = refused(doc, "stale", task={"found": False, "reason": "gone"})
    assert call.verbs() == [("task-get", False)]
    for odd in ({"found": "yes"}, {}, "x", {"found": True}, {"found": True, "task": "x"}):
        e, call = refused(doc, "unknown", task=odd)
        assert call.verbs() == [("task-get", False)], odd


def test_guard_unchanged_a_task_completed_already_goes_on_to_the_writer_which_tells_from_its_ledger():
    """GUARD execute.completed_passes: an earlier attempt of this very completion may have landed and lost its answer, so a completed task is not stale here; the writer's ledger
    answers `replayed`, or refuses `changed:` (a StaleError) when the key is not its own."""
    doc = done_doc()
    already = {"found": True, "task": {"id": "t2", "title": doc["title"], "status": "completed", "etag": '"E7"'}}
    replayed = {"done": True, "replayed": True, "task_id": "t2", "etag": '"E7"'}
    done, call = run(doc, Call(doc, task=already, done=replayed))
    assert done["replayed"] is True and call.verbs() == [("task-get", False), ("task-complete", False), ("task-complete", True)]


def test_vacuity_the_open_task_at_its_version_is_not_stale():
    doc = done_doc()
    assert run(doc, Call(doc, task={"found": True, "task": {"id": "t2", "title": "x", "status": "open", "etag": doc["base_etag"]}}))[0]["done"] is True


def test_a_writer_refusal_changed_is_stale_and_ambiguous_is_an_error_that_sends_nothing_again(monkeypatch):
    class Boom(Exception):
        pass
    resolve = project_config.resolver(str(st.REPO))
    changed = resolve.ProviderCallError("provider", "x", exit_code=1, stderr_last="error: changed: the task is not at the etag") if hasattr(resolve, "ProviderCallError") else None
    assert changed is not None
    monkeypatch.setattr(resolve, "call", lambda *a, **k: (_ for _ in ()).throw(changed))
    monkeypatch.setattr(effect_tasks, "serves", lambda root, impl: None)
    with pytest.raises(effects.EffectError) as e:
        effect_tasks.provider_call(str(st.REPO), "google-tasks", "task-complete", [], ())
    assert e.value.kind == "stale"
    ambiguous = resolve.ProviderCallError("provider", "x", exit_code=1, stderr_last="error: ambiguous: more than one open task")
    monkeypatch.setattr(resolve, "call", lambda *a, **k: (_ for _ in ()).throw(ambiguous))
    with pytest.raises(effects.EffectError) as e:
        effect_tasks.provider_call(str(st.REPO), "google-tasks", "task-insert", [], ())
    assert e.value.kind == "provider" and "ambiguous:" in e.value.reason and "Nothing was sent" in e.value.reason
    unknown = resolve.ProviderCallError("provider", "x", exit_code=4, stderr_last="")
    monkeypatch.setattr(resolve, "call", lambda *a, **k: (_ for _ in ()).throw(unknown))
    with pytest.raises(effects.EffectError) as e:
        effect_tasks.provider_call(str(st.REPO), "google-tasks", "task-insert", [], ())
    assert e.value.kind == "unknown"


# --- preflight ------------------------------------------------------------------------------------------------------------------------------------


def cfg_of(google=None, microsoft=None):
    raw = {}
    if google is not None:
        raw["google"] = google
    if microsoft is not None:
        raw["microsoft"] = microsoft
    return {"accounts": project_config._accounts(raw)}


GOOGLE = {"address": "pat@example.com", "task_lists": {"tarefas": "default", "mercado": "Abc_123"}}
MICROSOFT = {"address": "casey.rivera@mail.example", "task_lists": {"trabalho": "default"}}
ROOT = str(st.REPO)


def pre(doc, cfg=None):
    return effect_tasks.preflight(cfg or cfg_of(GOOGLE, MICROSOFT), doc, ROOT)


def test_vacuity_preflight_accepts_the_change_the_file_still_names():
    assert pre(add_doc()) is None and pre(done_doc()) is None and pre(add_doc(list_name="mercado", list_id="Abc_123")) is None


def test_guard_preflight_account_an_account_the_file_does_not_list_is_not_configured():
    code, why = pre(add_doc(), cfg_of(microsoft=MICROSOFT))
    assert code == 3 and "Nothing was written" in why


def test_guard_preflight_address_the_address_the_change_was_prepared_for_is_the_one_in_the_file():
    """GUARD preflight.address."""
    code, why = pre(add_doc(), cfg_of(dict(GOOGLE, address="other@example.com")))
    assert code == 1 and "address" in why


def test_guard_preflight_list_name_a_list_the_file_stopped_naming_is_refused():
    code, why = pre(add_doc(list_name="mercado", list_id="Abc_123"), cfg_of(dict(GOOGLE, task_lists={"tarefas": "default"})))
    assert code == 1 and "mercado" in why


def test_guard_preflight_list_id_the_id_behind_the_name_is_the_one_the_change_was_prepared_for():
    """GUARD preflight.list_id: a changed id behind the same name is another list."""
    code, why = pre(add_doc(list_name="mercado", list_id="Abc_123"), cfg_of(dict(GOOGLE, task_lists={"tarefas": "default", "mercado": "Other_456"})))
    assert code == 1 and "id of the list" in why


def test_guard_preflight_writer_a_writer_that_does_not_serve_the_class_is_refused(monkeypatch):
    monkeypatch.setattr(effect_tasks, "serves", lambda root, impl: "the writer does not declare it")
    code, why = pre(add_doc())
    assert code == 3 and "does not declare" in why


# --- the Microsoft default list is resolved again ------------------------------------------------------------------------------------------------------


def ms_doc(**over):
    kw = dict(task_id=9, account="microsoft", address="casey.rivera@mail.example", list_name="trabalho", list_id=LIST_M, operation="add", title="enviar o relatório",
              dry_run_sha256=SHA, default_list=True)
    kw.update(over)
    return tasks_document.document(**kw)


def lists_answer(*rows):
    return {"lists": [{"id": i, "name": n, "default": d} for i, n, d in rows], "external_content": True}


def test_guard_default_list_the_default_list_is_read_again_and_a_changed_one_is_refused(monkeypatch):
    """GUARD preflight.default_list: Microsoft's default list was resolved to an id when the change was prepared; it is resolved again now."""
    asked = []
    answer = {"lists": lists_answer((LIST_M, "Tasks", True), ("Other_1", "Groceries", False))}

    def read(root, account, verb, args, timeout=0):
        asked.append((account, verb))
        return answer["lists"]
    monkeypatch.setattr(tasks_reader, "provider_call", read)
    assert pre(ms_doc()) is None and asked == [("microsoft", "lists")], "vacuity: the same list is still the default one"
    answer["lists"] = lists_answer((LIST_M, "Tasks", False), ("Other_1", "Groceries", True))
    code, why = pre(ms_doc())
    assert code == 1 and "changed:" in why and "default list" in why
    answer["lists"] = lists_answer((LIST_M, "Tasks", False))      # none is marked: it cannot be shown to be the same
    assert pre(ms_doc())[0] == 1


def test_guard_default_list_a_reader_that_cannot_answer_refuses_and_a_file_that_stopped_saying_default_refuses(monkeypatch):
    def broken(root, account, verb, args, timeout=0):
        raise tasks_reader.ReaderError("provider_failed", "lists: down")
    monkeypatch.setattr(tasks_reader, "provider_call", broken)
    code, why = pre(ms_doc())
    assert code == 1 and "could not be read" in why
    monkeypatch.setattr(tasks_reader, "provider_call", lambda *a, **k: (_ for _ in ()).throw(tasks_reader.ReaderError("not_configured", "x")))
    assert pre(ms_doc())[0] == 3
    monkeypatch.setattr(tasks_reader, "provider_call", lambda *a, **k: lists_answer((LIST_M, "Tasks", True)))
    named = cfg_of(microsoft=dict(MICROSOFT, task_lists={"trabalho": LIST_M}))
    code, why = pre(ms_doc(), named)
    assert code == 1 and "default list" in why, "the file now names the id itself: the change was prepared for the default one"


def test_a_document_that_names_an_id_without_the_flag_is_not_read_again(monkeypatch):
    monkeypatch.setattr(tasks_reader, "provider_call", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no read")))
    named = cfg_of(microsoft=dict(MICROSOFT, task_lists={"trabalho": LIST_M}))
    assert pre(ms_doc(default_list=False), named) is None


# --- the step: _prepare -----------------------------------------------------------------------------------------------------------------------------


class Reader:
    """The fake `tasks_read` service."""

    def __init__(self, task=None, would=None, resolved=None, account="google"):
        self.account, self.would, self.task, self.resolved = account, would, task, resolved
        self.asked = []

    def enabled(self, account):
        return True

    def address(self, account):
        return "pat@example.com" if account == "google" else "casey.rivera@mail.example"

    def list_name(self, account, name):
        return name or "tarefas"

    def target(self, account, name):
        return ("default", None)

    def resolve_list(self, account, list_id):
        return self.resolved or list_id

    def task_get(self, account, address, list_id, task_id, field=None):
        self.asked.append(("task_get", task_id))
        return self.task if self.task is not None else {"found": True, "task": {"id": task_id, "title": "ligar para o dentista", "status": "open", "etag": '"E1"'}}

    def dry_run(self, doc):
        self.asked.append(("dry_run", doc["operation"]))
        if self.would is not None:
            return self.would
        if doc["operation"] == "add":
            would = {"method": "POST", "path": "/tasks/v1/lists/@default/tasks", "query": {}, "headers": {}, "body": {"title": doc["title"]}, "requires": None}
        else:
            would = {"method": "PATCH", "path": "/tasks/v1/lists/@default/tasks/t2", "query": {}, "headers": {}, "body": {"status": "completed"}, "requires": {"etag": doc["base_etag"]}}
        return {"would": would, "would_sha256": SHA}


class Files:
    def __init__(self):
        self.written = []

    def write(self, task_id, cycle, doc):
        self.written.append(doc)
        return "c" * 64


def ctx_of(args, files=None, **reader_kw):
    reader, files = Reader(**reader_kw), files or Files()
    return types.SimpleNamespace(args=args, services={"tasks_read": reader, "effect_files": files}, task_id=4, now=lambda: "2026-10-28T12:00:00Z"), reader, files


ADD = {"account": "google", "operation": "add", "title": "comprar café"}
COMPLETE = {"account": "google", "operation": "complete", "task": "t2"}


def prepare(args, state=None, **kw):
    ctx, reader, files = ctx_of(args, **kw)
    state = {} if state is None else state
    return step_tasks_item._prepare(ctx, state), state, reader, files


def failure(args, state=None, **kw):
    with pytest.raises(steps.StepFailure) as e:
        prepare(args, state, **kw)
    return e.value


def test_vacuity_the_add_and_the_completion_prepare_a_document():
    out, state, reader, files = prepare(ADD)
    assert out["operation"] == "add" and files.written[0]["title"] == "comprar café" and files.written[0]["default_list"] is False and "pinned_task" not in state
    out, state, reader, files = prepare(COMPLETE)
    assert files.written[0]["task_id"] == "t2" and files.written[0]["base_etag"] == '"E1"' and state["pinned_task"] == "t2"


GOOD_ADD = {"method": "POST", "path": "/tasks/v1/lists/@default/tasks", "query": {}, "headers": {}, "body": {"title": "comprar café"}, "requires": None}
GOOD_DONE = {"method": "PATCH", "path": "/tasks/v1/lists/@default/tasks/t2", "query": {}, "headers": {}, "body": {"status": "completed"}, "requires": {"etag": '"E1"'}}
PREVIEWS = (
    ("add: another method", ADD, dict(GOOD_ADD, method="PUT")),
    ("add: another title", ADD, dict(GOOD_ADD, body={"title": "comprar vinho"})),
    ("add: a due date", ADD, dict(GOOD_ADD, body={"title": "comprar café", "due": "2026-11-01T00:00:00Z"})),
    ("add: a note", ADD, dict(GOOD_ADD, body={"title": "comprar café", "notes": "x"})),
    ("add: a precondition", ADD, dict(GOOD_ADD, requires={"etag": '"E1"'})),
    ("add: a path that is not the tasks of a list", ADD, dict(GOOD_ADD, path="/tasks/v1/users/@me/lists")),
    ("add: a path that ends in a task", ADD, dict(GOOD_ADD, path="/tasks/v1/lists/@default/tasks/t9")),
    ("add: a key the writer does not print", ADD, dict(GOOD_ADD, extra="x")),
    ("complete: another method", COMPLETE, dict(GOOD_DONE, method="POST")),
    ("complete: another status", COMPLETE, dict(GOOD_DONE, body={"status": "needsAction"})),
    ("complete: a body with a title too", COMPLETE, dict(GOOD_DONE, body={"status": "completed", "title": "x"})),
    ("complete: a note", COMPLETE, dict(GOOD_DONE, body={"status": "completed", "notes": "x"})),
    ("complete: another version required", COMPLETE, dict(GOOD_DONE, requires={"etag": '"E9"'})),
    ("complete: no version required", COMPLETE, dict(GOOD_DONE, requires=None)),
    ("complete: a path with no task", COMPLETE, dict(GOOD_DONE, path="/tasks/v1/lists/@default/tasks")),
)


@pytest.mark.parametrize("name,args,would", PREVIEWS, ids=[p[0] for p in PREVIEWS])
def test_guard_same_a_preview_that_is_not_what_the_arguments_say_is_refused_and_nothing_is_written(name, args, would):
    """GUARD step._same: the method, the body, the version a completion requires and the path; and the writer's dry-run shape."""
    files = Files()
    e = failure(args, would={"would": would, "would_sha256": SHA}, files=files)
    assert e.code == "preview_mismatch" and files.written == [], name


def test_guard_same_a_preview_with_no_hash_or_a_bad_one_is_refused():
    for shown in ({"would": GOOD_ADD, "would_sha256": "xyz"}, {"would": GOOD_ADD}, {"would": GOOD_ADD, "would_sha256": None}, {"would_sha256": SHA}, {}, None, "x"):
        files = Files()
        assert failure(ADD, would=shown if shown is not None else "x", files=files).code == "preview_mismatch" and files.written == []


def test_guard_completed_already_a_task_that_is_completed_or_gone_or_has_no_version_makes_no_document():
    """GUARD step.completed_already, step.gone and step.no_version."""
    files = Files()
    done = {"found": True, "task": {"id": "t2", "title": "x", "status": "completed", "etag": '"E1"'}}
    assert failure(COMPLETE, task=done, files=files).code == "nothing_to_change"
    assert failure(COMPLETE, task={"found": False}, files=files).code == "task_gone"
    assert failure(COMPLETE, task={"found": True, "task": {"id": "t2", "title": "x", "status": "open"}}, files=files).code == "provider_failed"
    assert failure(COMPLETE, task={"found": True, "task": {"title": "x", "status": "open", "etag": '"E1"'}}, files=files).code == "provider_failed"
    assert failure(COMPLETE, task={"found": True, "task": {"id": "t2", "title": "x", "status": "inProgress", "etag": '"E1"'}}, files=files).code == "nothing_to_change", "only an open task is completed"
    assert files.written == []


def test_guard_pinned_task_a_start_over_prepares_the_same_task_or_refuses():
    """GUARD step.pinned_task: after a stale the task starts over, and it is the task of the card that waited or nothing."""
    other = failure(COMPLETE, state={"pinned_task": "t9"})
    assert other.code == "not_eligible" and other.field == "task"
    out, state, _r, files = prepare(COMPLETE, state={"pinned_task": "t2"})
    assert files.written[0]["task_id"] == "t2" and state["pinned_task"] == "t2"


def test_a_lost_answer_retry_of_a_completion_prepares_the_task_as_it_is_now_not_a_stale_one():
    """The retry after a lost answer starts over from the step that reads: a task that the first attempt completed is `nothing_to_change` (the writer's ledger settled it when the
    effect was approved again), and one that is still open is prepared again at the version it has now."""
    moved = {"found": True, "task": {"id": "t2", "title": "ligar para o dentista", "status": "open", "etag": '"E5"'}}
    out, state, _r, files = prepare(COMPLETE, state={"pinned_task": "t2"}, task=moved)
    assert files.written[0]["base_etag"] == '"E5"'
    done = {"found": True, "task": {"id": "t2", "title": "x", "status": "completed", "etag": '"E6"'}}
    assert failure(COMPLETE, state={"pinned_task": "t2"}, task=done).code == "nothing_to_change"


def test_the_default_list_flag_is_set_when_the_id_was_resolved_from_default():
    ms = {"account": "microsoft", "operation": "add", "title": "x"}
    ctx, reader, files = ctx_of(ms, resolved=LIST_M, account="microsoft")
    step_tasks_item._prepare(ctx, {})
    assert files.written[0]["default_list"] is True and files.written[0]["list_id"] == LIST_M
    ctx, reader, files = ctx_of(ADD, resolved="default")
    step_tasks_item._prepare(ctx, {})
    assert files.written[0]["default_list"] is False, "Google takes the word `default` as it is: nothing was resolved"


GUARDS = {
    "execute.approval": "test_guard_approval_hash_another_hash_or_another_scope_or_status_writes_nothing",
    "execute.key": "test_guard_key_a_key_the_document_does_not_derive_writes_nothing",
    "execute.dry_run_hash": "test_guard_dry_run_a_writer_that_would_send_another_request_is_never_confirmed",
    "execute.unchanged_call": "test_guard_unchanged_the_task_is_read_again_before_anything_is_confirmed",
    "execute.etag": "test_guard_unchanged_the_same_status_with_another_etag_is_stale_and_nothing_is_sent",
    "execute.found": "test_guard_unchanged_a_task_that_is_gone_is_stale_and_a_reading_that_is_no_reading_is_unknown",
    "execute.completed_passes": "test_guard_unchanged_a_task_completed_already_goes_on_to_the_writer_which_tells_from_its_ledger",
    "preflight.address": "test_guard_preflight_address_the_address_the_change_was_prepared_for_is_the_one_in_the_file",
    "preflight.list_id": "test_guard_preflight_list_id_the_id_behind_the_name_is_the_one_the_change_was_prepared_for",
    "preflight.default_list": "test_guard_default_list_the_default_list_is_read_again_and_a_changed_one_is_refused",
    "step._same": "test_guard_same_a_preview_that_is_not_what_the_arguments_say_is_refused_and_nothing_is_written",
    "step.completed_already": "test_guard_completed_already_a_task_that_is_completed_or_gone_or_has_no_version_makes_no_document",
    "step.pinned_task": "test_guard_pinned_task_a_start_over_prepares_the_same_task_or_refuses",
}


def test_every_guard_names_a_test_this_file_defines():
    defined = {name for name in globals() if name.startswith("test_")}
    assert set(GUARDS.values()) <= defined
