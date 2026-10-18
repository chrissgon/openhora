#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""What a step kind is handed to reach anything outside the project's files (package P8, limit L30): the services of the engine's Context.

A step kind (runtime/step_*.py) imports no module that calls a provider. Whatever it needs from one, it asks of `ctx.services`, and this
module builds those services, once, for the process that runs the task (runtime/ops_steps.py). Each is as narrow as the kind's need:

  config           the project's configuration (runtime/project_config.py load), read once
  documents        DocumentsReader: `read`, `stat`, `table_read` and `rows_state` of the project's documents provider (a page's text; a
                   page's existence and name; a table's columns, name, row count and newest edit; how many rows of a file the provider's
                   ledger holds that the table still lists), and what the kind asks about it (`enabled`, `provider`, `problem`: why a write to it is not
                   allowed now). It has no `write`: the verbs it calls are four literals, all reads.
  source_pin       function(source id) -> {"sha256": the converted text of the source's newest version, "page": the source's page as a
                   normalised identifier or None} or None: what a write-back compares the target with
  effect_files     EffectFiles: write and read the effect document of a cycle of a task, by hash (runtime/ops_step_effects.py holds the
                   folder); the approval and the execution are not here
  outbox           OutboxReader: `enabled`, `sender` and `provider` (the project's outbox, and the implementation of the class sender:email it
                   resolves to) and `dry_run(doc, attachments)`: the provider's `send --dry-run` for a document and the bytes of its
                   attachments (what it would send: its headers, its envelope, its text, each attachment's name, size and hash). It reads no
                   credential, opens no connection, sends nothing and has no way to: the one flag it adds to the provider's verb is that dry run
  publisher        PublisherReader: `provider`, `check` and `preview` for a platform (PUBLISH-EFFECT): the implementation of the class
                   publisher:<platform> the project resolves to, the provider's `--check`, and the post as the publishing skill's own script builds it
                   with the provider's dry run of it (what it would send, and what its ledger holds under the key). It reads no credential of its
                   own, publishes nothing and has no way to: the one flag it adds to the provider's `publish` is that dry run
  render           function(format, data) -> {"output", "tool_versions"}: the exporter (class exporter:document), called through the
                   resolver with the minimum environment; it makes a file from a text, on this machine, and changes nothing else
  calendar_read    CalendarReader (package W1): the project's `accounts` (`enabled`, `address`, `target`, `calendar_name`, `calendar_label`), the reference of an event
                   (`event_ref`: `created:<decision>` or, when the index of the snapshots is in this checkout, `<source>#<n>`), `event_get` (the calendar writer's one
                   read, with the account's token, no other secret) and `dry_run` (the writer's dry run of a document: no credential, no connection). It has no
                   way to write: the only verbs it starts are `event-get` and a write verb with `--dry-run`

So the write to a platform has no function in a step kind's reach: the only code that makes it is runtime/effect_write.py `execute`,
called from runtime/ops_step_effects.py `approve`. What Python cannot do is stop a module from importing another: that a step kind does
not is held by a static test (runtime/tests/test_steps_gate.py), a tripwire and not a wall, and by the review of a new kind.

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import os
import re
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import calendar_document  # noqa: E402
import documents  # noqa: E402
import effect_calendar  # noqa: E402
import effects  # noqa: E402
import ops_core as core  # noqa: E402
import ops_step_effects  # noqa: E402
import project_config  # noqa: E402
import publish_document  # noqa: E402
import publish_payload  # noqa: E402
import send_document  # noqa: E402
import sources  # noqa: E402

READ_VERBS = ("read", "stat", "table-read", "rows-state")      # the only verbs of the documents provider a step kind can reach
OUTBOX_CLASS = "sender:email"
OUTBOX_TIMEOUT = 120
PUBLISHER_TIMEOUT = 120
EXPORTER_CLASS = "exporter:document"
EXPORTER_TIMEOUT = 300
CALENDAR_TIMEOUT = 120
CALENDAR_READ_VERBS = ("event-get",)      # the only verb of a calendar writer a step kind can reach with a credential (a write verb is reached with --dry-run and none)
EVENT_REF = re.compile(r"[a-z0-9][a-z0-9_-]{0,39}#[1-9][0-9]{0,4}")      # <source id>#<n>: the n-th item of the newest version of a registered source (package SNAP-IDX)
CREATED_REF = re.compile(r"created:([1-9][0-9]{0,9})")                    # an event the runtime created: the decision whose approval created it
OUTPUT_MAX = 8 * 1024 * 1024       # the exporter's own cap (providers/exporter/container.py OUTPUT_CAP)


class StepServiceError(Exception):
    """A service failed in a way a kind turns into a closed code: `code` is a word, `reason` never reaches a state."""

    def __init__(self, code: str, reason: str = ""):
        super().__init__(f"{code} {reason}".strip())
        self.code, self.reason = code, reason


class DocumentsReader:
    """The project's documents provider, for reading only."""

    def __init__(self, cfg: dict, root: str):
        self._cfg, self._root = cfg, root

    def enabled(self) -> bool:
        return documents.enabled(self._cfg)

    def provider(self):
        return self._cfg[documents.KEY]["provider"] if self.enabled() else None

    def problem(self):
        """Why a write to the platform is not allowed now (its bounds expired), or None."""
        return project_config.bounds_problem(self._cfg, key=documents.KEY) if self.enabled() else None

    def _call(self, verb: str, target: str, extra=()) -> dict:
        assert verb in READ_VERBS
        try:
            return documents.call(self._cfg, self._root, verb, ["--id", target, *extra])
        except documents.DocumentsError as e:
            raise StepServiceError("not_configured" if e.kind == "not configured" else "provider_failed", e.detail) from None

    def read(self, target: str) -> dict:
        return self._call("read", target)

    def stat(self, target: str) -> dict:
        return self._call("stat", target)

    def rows_state(self, table: str, scope: str, table_bytes: bytes) -> dict:
        """How many of a table file's rows the provider's ledger already holds as written under a scope (an earlier approval of the same
        task) and the table still lists: the provider reads its ledger and lists the table (a read; it writes nothing). The rows are handed
        over as a private file, removed at once."""
        folder = tempfile.mkdtemp(prefix="openhora-rows-state-")
        try:
            path = os.path.join(folder, "table.json")
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(table_bytes)
            return self._call("rows-state", table, ["--scope", scope, "--table-file", path])
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    def table_read(self, table: str) -> dict:
        """A table's columns, their hash, its row count and the time of its newest edit (the provider's table-read; it changes nothing)."""
        return self._call("table-read", table)


class OutboxReader:
    """The project's outbox, for a dry run only: what the provider would send for a document, nothing sent and no credential read."""

    def __init__(self, cfg: dict, root: str):
        self._cfg, self._root = cfg, root

    def enabled(self) -> bool:
        return self._cfg.get("outbox") is not None

    def sender(self) -> str:
        return self._cfg["outbox"]["from"]

    def _implementation(self):
        chosen = self._cfg["outbox"].get("provider", "auto")
        return None if chosen == "auto" else chosen

    def provider(self) -> str:
        """The implementation of the class sender:email that this project and this machine resolve to."""
        resolve = project_config.resolver(self._root)
        try:
            return resolve.resolve(OUTBOX_CLASS, root=self._root, implementation=self._implementation())["implementation"]
        except (resolve.UnknownClass, resolve.Unresolved) as e:
            raise StepServiceError("not_configured", str(e)) from None

    def dry_run(self, doc: dict, attachments) -> dict:
        """The provider's dry run of `doc` (runtime/send_document.py): the subject, the text and each attachment are handed over as private
        files that are removed at once, and the provider starts with the minimum environment, with no secret in it."""
        folder = tempfile.mkdtemp(prefix="openhora-dry-run-")
        try:
            def put(name: str, data: bytes) -> str:
                path = os.path.join(folder, name)
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                with os.fdopen(fd, "wb") as f:
                    f.write(data)
                return path
            files = [put(f"attachment-{i}", data) for i, data in enumerate(attachments)]
            args = send_document.provider_args(doc, put("subject.txt", doc["subject"].encode("utf-8")), put("body.txt", doc["body"].encode("utf-8")),
                                               files) + ["--dry-run"]
            resolve = project_config.resolver(self._root)
            try:
                return resolve.call(OUTBOX_CLASS, "send", args, root=self._root, implementation=self._implementation(), timeout=OUTBOX_TIMEOUT,
                                    env=resolve.provider_environment(OUTBOX_CLASS, None, ()))
            except resolve.ProviderCallError as e:
                raise StepServiceError({"not-configured": "not_configured", "usage": "refused"}.get(e.kind, "provider_failed"), e.reason) from None
        finally:
            shutil.rmtree(folder, ignore_errors=True)


class PublisherReader:
    """The project's publisher for one platform, for a dry run only: the post as the publishing skill's script builds it and what the provider would
    send for it, nothing published and no credential read by this class. A failure is a StepServiceError whose code is a closed word."""

    def __init__(self, cfg: dict, root: str):
        self._cfg, self._root = cfg, root

    def _resolver(self):
        return project_config.resolver(self._root)

    def provider(self, platform: str) -> str:
        """The implementation of the class publisher:<platform> that this project and this machine resolve to."""
        resolve = self._resolver()
        try:
            return resolve.resolve(publish_payload.publisher_class(platform), root=self._root)["implementation"]
        except (resolve.UnknownClass, resolve.Unresolved) as e:
            raise StepServiceError("not_configured", str(e)) from None
        except effects.EffectError as e:
            raise StepServiceError("refused", e.reason) from None

    def _call(self, platform: str, verb, args: list) -> dict:
        resolve = self._resolver()
        try:
            return resolve.call(publish_payload.publisher_class(platform), verb, args, root=self._root, timeout=PUBLISHER_TIMEOUT,
                                env=publish_payload.environment(resolve, platform))
        except resolve.ProviderCallError as e:
            raise StepServiceError({"not-configured": "not_configured", "usage": "refused"}.get(e.kind, "provider_failed"), e.reason) from None

    def check(self, platform: str) -> dict:
        """The provider's `--check` for the platform (the provider reads its own token): its answer when it is ready and the token is not past its
        expiry, else StepServiceError not_configured."""
        ready = self._call(platform, None, ["--check", "--platform", platform])
        if publish_payload.token_problem(ready):
            raise StepServiceError("not_configured", publish_payload.token_problem(ready))
        return ready

    def preview(self, content: str, platform: str) -> dict:
        """{"post": {key, at, text, comment, image}, "dry_run": the provider's dry run without the ledger's lines, "ledger": the path it printed
        (or None), "recorded": what the ledger holds under the key ("published", "pending", None for nothing, or "unreported" when the provider does
        not say)}. The files the script wrote are handed to the provider where they are, in their private folder, which is removed when this returns.
        StepServiceError ledger_differs when the person's environment or a scheduled job for the key names another ledger (publish_payload.ledger_problem)."""
        try:
            built = publish_payload.build(self._root, self._cfg["project"], content, platform, work_dir=self._cfg["data_dir"])
        except publish_payload.PayloadError as e:
            raise StepServiceError("payload_refused", e.reason) from None
        except effects.EffectError as e:
            raise StepServiceError("refused", e.reason) from None
        try:
            paths = built.paths
            args = publish_document.provider_args(platform, built.key, paths["text"], paths["comment"], paths["image"])
            answer = self._call(platform, "publish", args + ["--dry-run"])
            try:
                shown = publish_document.stable_dry_run(answer, (built.folder,))
            except effects.EffectError as e:
                raise StepServiceError("provider_failed", e.reason) from None
            ledger = answer.get("ledger") if isinstance(answer.get("ledger"), str) else None
            why = publish_payload.ledger_problem(self._resolver(), self._root, platform, built.key, args, ledger)
            if why:
                raise StepServiceError("ledger_differs", why)
            return {"post": built.data(), "dry_run": shown, "ledger": ledger, "recorded": answer.get("existing_status", "unreported")}
        finally:
            built.cleanup()


class CalendarReader:
    """The project's calendar writers, for reading only (package W1): where the platform may write (the project's `accounts`), what an event reference names, the
    one event a change or a removal is about, and the dry run of a request. It starts no verb that writes: `event_get` is the writer's read, and `dry_run` hands a
    write verb `--dry-run` and no credential. A failure is a StepServiceError whose code is a closed word."""

    def __init__(self, ctx: dict):
        self._ctx, self._cfg, self._root = ctx, ctx["cfg"], os.path.dirname(HERE)

    def enabled(self, account) -> bool:
        return project_config.account_entry(self._cfg, account) is not None

    def address(self, account) -> str:
        return project_config.account_entry(self._cfg, account)["address"]

    def target(self, account, name):
        """(the id of the calendar, None) the project lists under `name` (the first one when None), or (None, the sentence that refuses it): limit L55."""
        return project_config.account_target(self._cfg, account, "calendars", name)

    def calendar_name(self, account, name):
        """The name the calendar goes by: `name`, else the first one listed; None when the account lists none."""
        listed = (project_config.account_entry(self._cfg, account) or {}).get("calendars") or {}
        return name if name is not None else next(iter(listed), None)

    def calendar_label(self, account, calendar_id):
        """The name the project gives the calendar with this id, or None."""
        listed = (project_config.account_entry(self._cfg, account) or {}).get("calendars") or {}
        return next((n for n, i in listed.items() if i == calendar_id), None)

    def _fail(self, e: "effects.EffectError"):
        code = {"not-configured": "not_configured", "usage": "refused"}.get(e.kind, "provider_failed")
        raise StepServiceError(code, e.reason) from None

    def event_get(self, account: str, calendar_id: str, event_id: str) -> dict:
        """The writer's `event-get` for one event of a calendar: {"found": bool, "event": {...}}. The one verb that carries the account's token."""
        verb = "event-get"
        assert verb in CALENDAR_READ_VERBS
        implementation = calendar_document.IMPLEMENTATION[account]
        try:
            return effect_calendar.provider_call(self._root, implementation, verb, calendar_document.event_get_args({"calendar_id": calendar_id, "event_id": event_id}),
                                                 (calendar_document.SECRET[account],), CALENDAR_TIMEOUT)
        except effects.EffectError as e:
            self._fail(e)

    def dry_run(self, doc: dict) -> dict:
        """The writer's dry run of `doc` (runtime/calendar_document.py): the request it would send and its hash. The words of the person are handed over as a
        private file that is removed at once, and the writer starts with the minimum environment, with no secret in it and with no connection to open."""
        folder = tempfile.mkdtemp(prefix="openhora-calendar-dry-run-")
        try:
            args = calendar_document.provider_args(doc, effect_calendar.spec_file(folder, doc)) + ["--dry-run"]
            return effect_calendar.provider_call(self._root, doc["implementation"], calendar_document.verb_of(doc), args, (), CALENDAR_TIMEOUT)
        except effects.EffectError as e:
            self._fail(e)
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    def event_ref(self, reference) -> dict:
        """What a reference to an event names: {"event_id", "account", "calendar" (the name the project gives the calendar, or None), "calendar_id" (the id the
        reference puts the event on, or None)}. It FAILS CLOSED: a reference that names no account, or whose account is not google or microsoft, is refused; the
        caller compares the account and the calendar id with the project's `accounts` exactly. `created:<decision>` is an event this runtime created, read from the
        result of that decision; `<source>#<n>` is the n-th item of a snapshot, resolved through the index of the snapshot (package SNAP-IDX: runtime/item_refs.py),
        which this checkout may not have yet. StepServiceError `refused` otherwise."""
        if not isinstance(reference, str):
            raise StepServiceError("refused", "an event is named by a reference")
        created = CREATED_REF.fullmatch(reference)
        if created:
            return self._created(int(created.group(1)))
        if not EVENT_REF.fullmatch(reference):
            raise StepServiceError("refused", "an event is named as <source>#<n> (the n-th item of a calendar snapshot) or created:<decision>")
        try:
            import item_refs      # package SNAP-IDX; absent from a checkout that does not have it yet
        except ImportError:
            raise StepServiceError("refused", "a reference to an event of a snapshot needs the index of the snapshots (package SNAP-IDX), which this checkout does not have") from None
        try:
            found = item_refs.resolve(self._ctx, reference)      # ASSUMED shape, to be aligned with the merged module: a dict with `id`, `calendar` (an id) and `account`
        except Exception as e:      # its refusal ("refresh <source> first", a number past the end...) is the sentence the person reads
            raise StepServiceError("refused", " ".join(str(e).split())[:200] or "the reference does not name an event") from None
        account = found.get("account") if isinstance(found, dict) else None
        if not isinstance(found, dict) or not isinstance(found.get("id"), str) or account not in calendar_document.ACCOUNTS:
            raise StepServiceError("refused", "the reference does not name an event of an account")
        calendar_id = found.get("calendar") if isinstance(found.get("calendar"), str) else None
        return {"event_id": found["id"], "account": account, "calendar": self.calendar_label(account, calendar_id) if calendar_id else None, "calendar_id": calendar_id}

    def _created(self, pending_id: int) -> dict:
        store = self._ctx["store"]
        try:
            item = store.pending_get(self._ctx["conn"], pending_id)
        except store.StoreError:
            raise StepServiceError("refused", f"there is no decision {pending_id}") from None
        payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
        result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
        step = payload.get("step") if isinstance(payload.get("step"), dict) else {}
        if item.get("kind") != "effect" or item.get("resolution") != "approved" or step.get("kind") != "calendar-event" or result.get("operation") != "create" \
                or not isinstance(result.get("event_id"), str) or result.get("account") not in calendar_document.ACCOUNTS:
            raise StepServiceError("refused", f"decision {pending_id} did not create an event")
        name = result.get("calendar") if isinstance(result.get("calendar"), str) else None
        listed = (project_config.account_entry(self._cfg, result["account"]) or {}).get("calendars") or {}
        return {"event_id": result["event_id"], "account": result["account"], "calendar": name if name in listed else None, "calendar_id": listed.get(name)}


class EffectFiles:
    """The effect documents of a write-back, by task and cycle, in the runtime's data folder (0700 at every level, files 0600)."""

    def __init__(self, cfg: dict):
        self._cfg = cfg

    def write(self, task_id: int, cycle: int, doc: dict) -> str:
        """Write the document; returns its sha256, the hash the person approves."""
        folder = ops_step_effects.make_effect_dir(self._cfg, task_id, cycle)
        path, digest = effects.write(folder, doc)
        os.chmod(path, 0o600)
        return digest

    def read(self, task_id: int, cycle: int, digest: str) -> dict:
        """The document, only if its bytes have this hash (effects.EffectError otherwise)."""
        return effects.read_document(os.path.join(ops_step_effects.effect_dir(self._cfg, task_id, cycle), effects.EFFECT_FILE), digest)


def source_pin(project: str):
    def look(source_id: str):
        found = core.context(project)
        try:
            latest = found["store"].source_latest(found["conn"], source_id)
            row = found["store"].source_get(found["conn"], source_id)
        except found["store"].StoreError:
            return None
        if not latest:
            return None
        try:
            page = sources.notion_page_id(row["origin"])
        except sources.SourcesError:
            page = None
        return {"sha256": latest["converted_sha256"], "page": page}
    return look


def _read_output(folder: str, name: str) -> bytes:
    """The one file the exporter left in the private out folder: a regular file with one link, opened without following a link, at most
    OUTPUT_MAX bytes, and nothing else in the folder."""
    path = os.path.join(folder, name)
    try:
        info = os.lstat(path)
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        raise StepServiceError("render_failed") from None
    with os.fdopen(fd, "rb") as f:
        if info.st_mode & 0o170000 != 0o100000 or info.st_nlink != 1 or info.st_size > OUTPUT_MAX or sorted(os.listdir(folder)) != [name]:
            raise StepServiceError("render_failed")
        return f.read(OUTPUT_MAX + 1)


def renderer(root: str):
    def render(fmt: str, data: bytes) -> dict:
        resolver = project_config.resolver(root)
        folder = tempfile.mkdtemp(prefix="openhora-export-")
        try:
            source, out = os.path.join(folder, "input"), os.path.join(folder, "out")
            os.mkdir(out, 0o700)
            fd = os.open(source, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            try:
                done = resolver.call(EXPORTER_CLASS, "render", ["--format", fmt, "--input", source, "--out-dir", out], root=root,
                                     timeout=EXPORTER_TIMEOUT, env=resolver.provider_environment(EXPORTER_CLASS, None, ()))
            except resolver.ProviderCallError as e:
                raise StepServiceError("not_configured" if e.kind == "not-configured" else "render_failed") from None
            tools = done.get("tool_versions") if isinstance(done, dict) and isinstance(done.get("tool_versions"), dict) else {}
            return {"output": _read_output(out, f"output.{fmt}"), "tool_versions": tools}
        finally:
            shutil.rmtree(folder, ignore_errors=True)
    return render


def services(ctx: dict) -> dict:
    """The services of the Context for the task a process runs: `ctx` is the operations layer's context (ops_core.context)."""
    cfg, root = ctx["cfg"], os.path.dirname(HERE)
    return {"config": cfg, "documents": DocumentsReader(cfg, root), "source_pin": source_pin(cfg["project"]), "effect_files": EffectFiles(cfg),
            "outbox": OutboxReader(cfg, root), "publisher": PublisherReader(cfg, root), "render": renderer(root), "calendar_read": CalendarReader(ctx)}


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
