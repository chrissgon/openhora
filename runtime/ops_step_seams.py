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
  account_mail     AccountMailReader (package W2): the project's `accounts` for an e-mail from the person's own account (`enabled`, `address`, `implementation`: the mailer
                   of the account), `reply_facts` (what the index of a snapshot recorded of the message a reply answers, through runtime/item_refs.py) and `dry_run(doc,
                   attachments)` (the account's mailer, which reads no credential, opens no connection and sends nothing). It has no way to send: the one flag it adds to
                   the mailer's `send` is that dry run
  publisher        PublisherReader: `provider`, `check` and `preview` for a platform (PUBLISH-EFFECT): the implementation of the class
                   publisher:<platform> the project resolves to, the provider's `--check`, and the post as the publishing skill's own script builds it
                   with the provider's dry run of it (what it would send, and what its ledger holds under the key). It reads no credential of its
                   own, publishes nothing and has no way to: the one flag it adds to the provider's `publish` is that dry run
  render           function(format, data) -> {"output", "tool_versions"}: the exporter (class exporter:document), called through the
                   resolver with the minimum environment; it makes a file from a text, on this machine, and changes nothing else
  calendar_read    CalendarReader (package W1): the project's `accounts` (`enabled`, `address`, `target`, `calendar_name`, `calendar_label`), the reference of an event
                   (`event_ref`: `created:<decision>` or `<source>#<n>`, through runtime/item_refs.py with the caller's channel and sender), `event_get` (the calendar writer's one
                   read, with the account's token, no other secret) and `dry_run` (the writer's dry run of a document: no credential, no connection). It has no
                   way to write: the only verbs it starts are `event-get` and a write verb with `--dry-run`
  tasks_read       TasksReader (package CB-5): the project's `accounts` (`enabled`, `address`, `list_name`, `target`), the id the writer is handed for a list (`resolve_list`: Microsoft's
                   default list is resolved by a read of the lists), `task_get` (the tasks writer's one read, with the account's token, no other secret) and `dry_run` (the writer's
                   dry run of a document: no credential, no connection). It has no way to write: the only verbs it starts are `task-get`, `lists` of the reader and a write verb with `--dry-run`
  files_read       FilesReader (package W4a): `meta(account, args)`, the ONE verb of the writers of files a step kind reaches, `file-meta`, a read of one
                   file or of a name in a folder of the person's own Drive or OneDrive (limit L58: the seam exposes only this; the write verbs are
                   runtime/effect_files.py's alone)
  file_grant       FileGrant (slice R2-A): `locate(account, root, id)`, whether a file is under a folder the project lists, by the walk the search makes (a read; it
                   writes nothing)
  held_files       HeldFiles (package W4a): `meta(attachment id)`, what a file a sender sent waits as (name, size, sha256, kind), read from the hold and
                   checked against its bytes; it moves nothing out of the hold
  file_source      FileSources (package W4a): `lookup(source id)`, a registered source's type, origin and the version of its newest copy
  accounts         AccountTargets (package W4a): `address(account)` and `target(account, section, name)` of the project's accepted `accounts` (limit L55)
  mailbox_read     MailboxReader (package W3): the project's `accounts` (`enabled`, `address`, `target`, `move_removes_inbox`), `message_meta` and `folder_get` (the mailbox
                   writer's two reads, with the account's token, no other secret) and `dry_run` (the writer's dry run of a document: no credential, no connection). It has
                   no way to write: the only verbs it starts are `message-meta`, `folder-get` and a write verb with `--dry-run`

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
import effect_mailbox  # noqa: E402
import effect_tasks  # noqa: E402
import effects  # noqa: E402
import item_refs  # noqa: E402
import files_document  # noqa: E402
import mail_refs  # noqa: E402
import mailbox_document  # noqa: E402
import ops_core as core  # noqa: E402
import ops_step_effects  # noqa: E402
import phrases  # noqa: E402
import project_config  # noqa: E402
import publish_document  # noqa: E402
import publish_payload  # noqa: E402
import send_document  # noqa: E402
import sources  # noqa: E402
import tasks_document  # noqa: E402
import tasks_reader  # noqa: E402

READ_VERBS = ("read", "stat", "table-read", "rows-state")      # the only verbs of the documents provider a step kind can reach
OUTBOX_CLASS = "sender:email"
OUTBOX_TIMEOUT = 120
PUBLISHER_TIMEOUT = 120
EXPORTER_CLASS = "exporter:document"
EXPORTER_TIMEOUT = 300
CALENDAR_TIMEOUT = 120
CALENDAR_READ_VERBS = ("event-get",)      # the only verb of a calendar writer a step kind can reach with a credential (a write verb is reached with --dry-run and none)
IMPLEMENTATION_ACCOUNT = {"google": "google", "outlook": "microsoft"}      # the implementation of a calendar source's origin (sources_mail.calendar_origin) -> the account
SNAPSHOT_CLOCK = None      # the clock item_refs reads a snapshot's age against (None: the real one); a test replaces it
MAILBOX_TIMEOUT = 300
TASKS_TIMEOUT = 120
TASKS_READ_VERBS = ("task-get",)      # the only verb of a tasks writer a step kind can reach with a credential (a write verb is reached with --dry-run and none)
MAILBOX_READ_VERBS = ("message-meta", "folder-get")      # the only verbs of a mailbox writer a step kind can reach with a credential (a write verb is reached with --dry-run and none)
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
            name = resolve.resolve(OUTBOX_CLASS, root=self._root, implementation=self._implementation())["implementation"]
        except (resolve.UnknownClass, resolve.Unresolved) as e:
            raise StepServiceError("not_configured", str(e)) from None
        if name in project_config.OWN_ACCOUNT_MAILERS:      # a variable chose a mailer of an own account: the outbox is an SMTP account
            raise StepServiceError("not_configured", "the outbox is an SMTP account; the mailers of the person's own accounts are not an outbox")
        return name

    def dry_run(self, doc: dict, attachments) -> dict:
        """The provider's dry run of `doc` (runtime/send_document.py): the subject, the text and each attachment are handed over as private
        files that are removed at once, and the provider starts with the minimum environment, with no secret in it."""
        return mailer_dry_run(self._root, self._implementation(), doc, attachments)


def mailer_dry_run(root: str, implementation, doc: dict, attachments) -> dict:
    """The dry run of a mailer of the class sender:email for `doc` (runtime/send_document.py): the subject, the text and each attachment are handed over as private
    files that are removed at once, and the mailer starts with the minimum environment, with no secret in it. `implementation` is None for the project's outbox
    ("auto") and the name of a mailer otherwise. StepServiceError with a closed code."""
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
        resolve = project_config.resolver(root)
        try:
            return resolve.call(OUTBOX_CLASS, "send", args, root=root, implementation=implementation, timeout=OUTBOX_TIMEOUT,
                                env=resolve.provider_environment(OUTBOX_CLASS, None, ()))
        except resolve.ProviderCallError as e:
            raise StepServiceError({"not-configured": "not_configured", "usage": "refused"}.get(e.kind, "provider_failed"), e.reason) from None
    finally:
        shutil.rmtree(folder, ignore_errors=True)


class AccountMailReader:
    """The person's own mail accounts, for reading only (package W2): where the platform may send from (the project's `accounts`), the message a reply answers, and the
    dry run of an e-mail by the account's mailer. It starts no verb that sends: `dry_run` hands the mailer `--dry-run` and no credential. A failure is a
    StepServiceError whose code is a closed word and whose reason, for a refusal, is a sentence written by code from the phrase table."""

    def __init__(self, ctx: dict):
        self._ctx, self._cfg, self._root = ctx, ctx["cfg"], os.path.dirname(HERE)

    def enabled(self, account) -> bool:
        return account in send_document.ACCOUNTS and project_config.account_entry(self._cfg, account) is not None

    def address(self, account) -> str:
        return project_config.account_entry(self._cfg, account)["address"]

    def implementation(self, account) -> str:
        """The mailer (an implementation of the class sender:email) that sends from the account: gmail for google, outlook for microsoft."""
        return send_document.ACCOUNTS[account]

    def reply_facts(self, reference, account, channel, sender=None) -> dict:
        """What the index of the snapshot recorded of the message `reference` names (`<source id>#<n>`), as a reply needs it (runtime/mail_refs.py): its sender, another
        address it asked replies to go to, its subject, the time of its snapshot, the service's id of the message, its Message-ID and, for Gmail, its conversation. The
        reference is resolved with the `channel` and the `sender` the operation wrote into the task's arguments (a messaging sender needs the group `ask-mail`);
        a caller that names none is refused, never read as the operations' own. StepServiceError `refused`, with the sentence, when it cannot be answered from this account."""
        try:
            if channel not in ("terminal", "page", "messaging"):
                raise StepServiceError("refused", mail_refs.ref_sentence("not_readable", reference))
            found = item_refs.resolve(self._ctx, reference, channel=channel, sender=sender, kinds=("mail",), clock=SNAPSHOT_CLOCK)
            return mail_refs.reply_facts(found, account)
        except item_refs.ItemRefError as e:
            raise StepServiceError("refused", mail_refs.ref_sentence(e.code, reference)) from None
        except mail_refs.MailRefError as e:
            raise StepServiceError("refused", e.sentence) from None
        except sources.SourcesError as e:
            raise StepServiceError("refused", " ".join(str(e).split())[:200]) from None

    def dry_run(self, doc: dict, attachments) -> dict:
        """The account's mailer's dry run of `doc`: what it would send, and nothing is sent, no credential is read and no connection is opened."""
        return mailer_dry_run(self._root, doc["provider"], doc, attachments)


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

    def event_ref(self, reference, channel=None, sender=None) -> dict:
        """What a reference to an event names: {"event_id", "account", "calendar" (the name the project gives the calendar, or None), "calendar_id" (the id the
        reference puts the event on), "reference" (for `<source>#<n>`: {"source", "n", "read_at"}, the snapshot it was read from; None for `created:`)}. The
        resolution is runtime/item_refs.py (package SNAP-IDX), with the caller's own `channel` and `sender`: a `<source>#<n>` into a snapshot of the person's calendar
        is usable only by a caller who may read it (a messaging sender needs the group `ask-mail`), and a `created:<decision>` needs no reading right. It FAILS
        CLOSED: the account is the one the SOURCE ROW's origin names (google or outlook, never the index), the calendar id is the origin's, and the caller compares
        both with the project's `accounts` exactly. Every refusal is a StepServiceError `refused` whose sentence is a phrase of the table (ACCT_REF_*)."""
        try:
            got = item_refs.resolve(self._ctx, reference, channel=channel, sender=sender, kinds=("calendar",), created=lambda ctx, pending: self._created_entry(ctx, pending, channel, sender), clock=SNAPSHOT_CLOCK)
        except item_refs.ItemRefError as e:
            raise StepServiceError("refused", ref_sentence(e.code, reference)) from None
        except sources.SourcesError:
            raise StepServiceError("refused", ref_sentence("integrity", reference)) from None
        entry = got.get("entry") if isinstance(got, dict) else None
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
            raise StepServiceError("refused", ref_sentence("not_an_event", reference))
        if got["kind"] == "created":
            return {"event_id": entry["id"], "account": entry["account"], "calendar": entry["calendar"], "calendar_id": entry["calendar_id"], "reference": None}
        account = IMPLEMENTATION_ACCOUNT.get(got.get("implementation"))
        calendar_id = got.get("calendar")
        if account is None or not isinstance(calendar_id, str) or entry.get("calendar") != calendar_id:      # the index and the source row's origin must say the same
            raise StepServiceError("refused", ref_sentence("integrity" if account else "not_an_event", reference))
        return {"event_id": entry["id"], "account": account, "calendar": self.calendar_label(account, calendar_id), "calendar_id": calendar_id,
                "reference": {"source": got["source"], "n": got["n"], "read_at": got["read_at"]}}

    def _created_entry(self, ctx: dict, pending_id: int, channel=None, sender=None):
        """The `created` function of item_refs.resolve: what the approved card `pending_id` recorded of the event it created, or None. Minimal on purpose: the id,
        the account and the calendar (its name and the id recorded then). Whoever may read the person's mail and calendar (item_refs.may_read) may use it; a
        messaging sender without that right only for an event they asked for themselves (`asker`); for anyone else it answers None, the same answer as for a
        card that created nothing, so that a guess learns nothing."""
        store = ctx["store"]
        try:
            item = store.pending_get(ctx["conn"], pending_id)
        except store.StoreError:
            return None
        payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
        result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
        step = payload.get("step") if isinstance(payload.get("step"), dict) else {}
        if item.get("kind") != "effect" or item.get("resolution") != "approved" or step.get("kind") != "calendar-event" or result.get("operation") != "create" \
                or not isinstance(result.get("event_id"), str) or result.get("account") not in calendar_document.ACCOUNTS:
            return None
        if not item_refs.may_read(ctx, channel, sender) and (not sender or result.get("asker") != sender):
            return None
        name = result.get("calendar") if isinstance(result.get("calendar"), str) else None
        listed = (project_config.account_entry(self._cfg, result["account"]) or {}).get("calendars") or {}
        recorded = result.get("calendar_id") if isinstance(result.get("calendar_id"), str) else None
        return {"id": result["event_id"], "account": result["account"], "calendar": name if name in listed else None, "calendar_id": recorded}


def ref_sentence(code: str, reference) -> str:
    """The sentence of a refused reference, from the phrase table (the family ACCT_REF_), with the source id the reference names when it names one."""
    source = reference.partition("#")[0] if isinstance(reference, str) and re.fullmatch(r"[a-z0-9][a-z0-9-]{0,39}#[0-9]{1,4}", reference.strip()) else "that source"
    english = phrases.TABLE[phrases.DEFAULT]
    key = "ACCT_REF_" + str(code).upper()
    return english.get(key, english["ACCT_REF_NOT_AN_EVENT"]).format(source=source)


class MailboxReader:
    """The project's mailbox writers, for reading only (package W3): where the platform may write (the project's `accounts`), the state of the messages a change is
    about, a folder's id, and the dry run of a request. It starts no verb that writes: `message_meta` and `folder_get` are the writer's reads, and `dry_run` hands a write
    verb `--dry-run` and no credential. A failure is a StepServiceError whose code is a closed word."""

    def __init__(self, ctx: dict):
        self._ctx, self._cfg, self._root = ctx, ctx["cfg"], os.path.dirname(HERE)

    def enabled(self, account) -> bool:
        return project_config.account_entry(self._cfg, account) is not None

    def address(self, account) -> str:
        return project_config.account_entry(self._cfg, account)["address"]

    def target(self, account, name):
        """(the id of the mail folder or label, None) the project lists under `name`, or (None, the sentence that refuses it): limit L55."""
        return project_config.account_target(self._cfg, account, "mail_folders", name)

    def move_removes_inbox(self, account) -> bool:
        return project_config.account_entry(self._cfg, account)["move_removes_inbox"] is True

    def _fail(self, e: "effects.EffectError"):
        code = {"not-configured": "not_configured", "usage": "refused"}.get(e.kind, "provider_failed")
        raise StepServiceError(code, e.reason) from None

    def _read(self, account: str, verb: str, args: list) -> dict:
        if verb not in MAILBOX_READ_VERBS:
            raise StepServiceError("refused", f"the mailbox service reads with {', '.join(MAILBOX_READ_VERBS)} and nothing else")
        implementation = mailbox_document.IMPLEMENTATION[account]
        try:
            return effect_mailbox.provider_call(self._root, implementation, verb, args, (mailbox_document.SECRET[account],), MAILBOX_TIMEOUT)
        except effects.EffectError as e:
            self._fail(e)

    def message_meta(self, account: str, ids: list) -> list:
        """The writer's `message-meta` for messages of the account: one row for each id, in the order asked, {"id", "found", ...} (subject and sender are another person's
        words). The one verb that carries the account's token to read mail."""
        got = self._read(account, "message-meta", ["--account", self.address(account), "--ids", ",".join(ids)])
        rows = got.get("messages") if isinstance(got, dict) else None
        if not isinstance(rows, list) or [r.get("id") if isinstance(r, dict) else None for r in rows] != list(ids):
            raise StepServiceError("provider_failed", "the writer's answer about the messages is not one this code understands")
        return rows

    def folder_get(self, account: str, folder: str) -> dict:
        """The writer's `folder-get` (Outlook): {"found": bool, "id"}."""
        return self._read(account, "folder-get", ["--account", self.address(account), "--folder", folder])

    def dry_run(self, doc: dict) -> dict:
        """The writer's dry run of `doc` (runtime/mailbox_document.py): the requests it would send and their hash. The words of the person are handed over as a private
        file that is removed at once, and the writer starts with the minimum environment, with no secret in it and with no connection to open."""
        folder = tempfile.mkdtemp(prefix="openhora-mailbox-dry-run-")
        try:
            args = mailbox_document.provider_args(doc, effect_mailbox.spec_file(folder, doc)) + ["--dry-run"]
            return effect_mailbox.provider_call(self._root, doc["implementation"], mailbox_document.verb_of(doc), args, (), MAILBOX_TIMEOUT)
        except effects.EffectError as e:
            self._fail(e)
        finally:
            shutil.rmtree(folder, ignore_errors=True)


class TasksReader:
    """The project's tasks writers and reader, for reading only (package CB-5): where the platform may write (the project's `accounts`), the id of a list, the one task a completion is
    about, and the dry run of a request. It starts no verb that writes: `task_get` is the writer's read, `resolve_list` is the reader's read of the lists, and `dry_run` hands a write verb
    `--dry-run` and no credential. A failure is a StepServiceError whose code is a closed word."""

    def __init__(self, ctx: dict):
        self._ctx, self._cfg, self._root = ctx, ctx["cfg"], os.path.dirname(HERE)

    def enabled(self, account) -> bool:
        return project_config.account_entry(self._cfg, account) is not None

    def address(self, account) -> str:
        return project_config.account_entry(self._cfg, account)["address"]

    def list_name(self, account, name):
        """The name the list goes by: `name`, else the first one listed; None when the account lists none."""
        listed = (project_config.account_entry(self._cfg, account) or {}).get("task_lists") or {}
        return name if name is not None else next(iter(listed), None)

    def target(self, account, name):
        """(the id of the list, None) the project lists under `name`, or (None, the sentence that refuses it): limit L55."""
        return project_config.account_target(self._cfg, account, "task_lists", name)

    def _fail(self, e):
        """A reader's error (a closed `code`) or a writer's (an effect error with a `kind`) as a StepServiceError."""
        if isinstance(e, tasks_reader.ReaderError):
            code = e.code if e.code in ("not_configured", "refused") else "provider_failed"
        else:
            code = {"not-configured": "not_configured", "usage": "refused"}.get(e.kind, "provider_failed")
        raise StepServiceError(code, str(e.reason)) from None

    def resolve_list(self, account: str, list_id: str) -> str:
        """The id the writer is handed for a list the project lists: `default` is Google's own word and, for Microsoft, the id of the list the service marks as its default one."""
        if list_id != "default":
            return list_id
        try:
            return tasks_reader.default_list(self._root, account)
        except tasks_reader.ReaderError as e:
            self._fail(e)

    def task_get(self, account: str, address: str, list_id: str, task_id: str) -> dict:
        """The writer's `task-get` for one task of a list: {"found": bool, "task": {...}}. The one verb that carries the account's token."""
        verb = "task-get"
        assert verb in TASKS_READ_VERBS
        implementation = tasks_document.IMPLEMENTATION[account]
        try:
            return effect_tasks.provider_call(self._root, implementation, verb, tasks_document.get_args({"address": address, "list_id": list_id, "task_id": task_id}),
                                              (tasks_document.SECRET[account],), TASKS_TIMEOUT)
        except effects.EffectError as e:
            self._fail(e)

    def dry_run(self, doc: dict) -> dict:
        """The writer's dry run of `doc` (runtime/tasks_document.py): the request it would send and its hash. The words of the person are handed over as a private file that is
        removed at once, and the writer starts with the minimum environment, with no secret in it and with no connection to open."""
        folder = tempfile.mkdtemp(prefix="openhora-tasks-dry-run-")
        try:
            args = tasks_document.provider_args(doc, effect_tasks.spec_file(folder, doc)) + ["--dry-run"]
            return effect_tasks.provider_call(self._root, doc["implementation"], tasks_document.verb_of(doc), args, (), TASKS_TIMEOUT)
        except effects.EffectError as e:
            self._fail(e)
        finally:
            shutil.rmtree(folder, ignore_errors=True)


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


# --- package W4a: the files of the person's own accounts ------------------------------------------------------------------------------------------

WRITER_FILES_CLASS = "writer:files"
FILES_READ_VERB = "file-meta"        # the one verb of a writer of files this module starts: a read
FILES_SECRETS = {"google": "GOOGLE_ACCOUNT_TOKEN", "microsoft": "MICROSOFT_ACCOUNT_TOKEN"}
FILES_TIMEOUT = 120


class FilesReader:
    """The writers of files, for one read: `file-meta`. The writer starts with the minimum environment and the one account secret of the account, reads one
    file (or looks for a name in a folder) and prints what it saw. It sends GET only, and nothing here can start another verb of it."""

    def __init__(self, cfg: dict, root: str):
        self._cfg, self._root = cfg, root

    def meta(self, account: str, args: list) -> dict:
        implementation = files_document.IMPLEMENTATION.get(account)
        if implementation is None:
            raise StepServiceError("refused", "the account is google or microsoft")
        resolve = project_config.resolver(self._root)
        entry = project_config.account_entry(self._cfg, account)
        if entry is None:
            raise StepServiceError("not_configured", project_config.clean_name(account, 20))
        args = list(args) + ["--account", entry["address"]]      # the writer reads only with the token of this account
        try:
            return resolve.call(WRITER_FILES_CLASS, FILES_READ_VERB, args, root=self._root, implementation=implementation, timeout=FILES_TIMEOUT,
                                env=resolve.provider_environment(WRITER_FILES_CLASS, None, (FILES_SECRETS[account],)))
        except resolve.ProviderCallError as e:
            if e.kind == "not-configured":
                raise StepServiceError("not_configured", e.reason) from None
            raise StepServiceError("refused" if e.exit_code == 1 or e.kind == "usage" else "provider_failed", e.reason) from None


class FileGrant:
    """The grant of a folder, asked again (slice R2-A): is this file under that configured folder, by the walk the search makes (runtime/ops_file_read.py `locate`)? A reader of the
    person's own folders through the documents providers; it writes nothing."""

    def __init__(self, cfg: dict):
        self._cfg = cfg

    def locate(self, account: str, root: str, ident: str):
        import ops_file_read  # noqa: PLC0415  (loaded when a trash is prepared)
        return ops_file_read.locate(self._cfg, account, root, ident)


class HeldFiles:
    """The files a listed sender sent through a messaging app and that wait for an answer (ATT-1), as a step kind may ask about one: what it is, never the
    sender. It reads the bytes of the held file to check them against the hash the hold recorded, and keeps nothing."""

    def __init__(self, cfg: dict):
        self._cfg = cfg

    def meta(self, attachment_id: int) -> dict:
        import attachments  # noqa: PLC0415  (the hold: loaded when a held file is asked about)
        ctx = core.context(self._cfg["project"])
        try:
            row = ctx["store"].attachment_get(ctx["conn"], attachment_id)
        except ctx["store"].StoreError:
            raise StepServiceError("gone", "no such file") from None
        if row["status"] != "held":
            raise StepServiceError("gone", row["status"])
        data = attachments.read_held(self._cfg["data_dir"], attachment_id)
        if data is None or len(data) != row["bytes"] or row["sha256"] != files_document.sha(data):
            raise StepServiceError("gone", "the held file is not there as it was kept")
        return {"id": row["id"], "name": row["name"], "bytes": row["bytes"], "sha256": row["sha256"], "kind": row["kind"]}


class FileSources:
    """The registered sources, for a replace: the type, the origin and the version of the newest copy the person read."""

    def __init__(self, cfg: dict):
        self._cfg = cfg

    def lookup(self, source_id: str):
        ctx = core.context(self._cfg["project"])
        try:
            row = sources.public_row(ctx["store"].source_get(ctx["conn"], source_id))
            latest = ctx["store"].source_latest(ctx["conn"], source_id)
        except ctx["store"].StoreError:
            return None
        return {"type": row["type"], "origin": row["origin"], "origin_version": latest.get("origin_version") if latest else None}


class AccountTargets:
    """The project's accepted `accounts` (runtime/project_config.py): the address of an account and the id of a folder it lists. Whatever the account's token
    could reach, only what the file lists is a target (limit L55)."""

    def __init__(self, cfg: dict):
        self._cfg = cfg

    def address(self, account: str) -> str:
        entry = project_config.account_entry(self._cfg, account)
        if entry is None:
            raise StepServiceError("not_configured", project_config.clean_name(account, 20))
        return entry["address"]

    def target(self, account: str, section: str, name=None) -> str:
        ident, why = project_config.account_target(self._cfg, account, section, name)
        if why:
            raise StepServiceError("refused", why)
        return ident


def services(ctx: dict) -> dict:
    """The services of the Context for the task a process runs: `ctx` is the operations layer's context (ops_core.context)."""
    cfg, root = ctx["cfg"], os.path.dirname(HERE)
    return {"config": cfg, "documents": DocumentsReader(cfg, root), "source_pin": source_pin(cfg["project"]), "effect_files": EffectFiles(cfg),
            "outbox": OutboxReader(cfg, root), "publisher": PublisherReader(cfg, root), "render": renderer(root), "calendar_read": CalendarReader(ctx),
            "files_read": FilesReader(cfg, root), "file_grant": FileGrant(cfg), "held_files": HeldFiles(cfg), "file_source": FileSources(cfg), "accounts": AccountTargets(cfg), "account_mail": AccountMailReader(ctx), "mailbox_read": MailboxReader(ctx), "tasks_read": TasksReader(ctx)}


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
