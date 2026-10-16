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

So the write to a platform has no function in a step kind's reach: the only code that makes it is runtime/effect_write.py `execute`,
called from runtime/ops_step_effects.py `approve`. What Python cannot do is stop a module from importing another: that a step kind does
not is held by a static test (runtime/tests/test_steps_gate.py), a tripwire and not a wall, and by the review of a new kind.

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import documents  # noqa: E402
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
        """{"post": {key, at, text, comment, image}, "dry_run": the provider's dry run without the ledger's lines, "recorded": what the ledger holds
        under the key ("published", "pending", None for nothing, or "unreported" when the provider does not say)}. The files the script wrote are
        handed to the provider where they are, in their private folder, which is removed when this returns."""
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
            return {"post": built.data(), "dry_run": shown, "recorded": answer.get("existing_status", "unreported")}
        finally:
            built.cleanup()


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
            "outbox": OutboxReader(cfg, root), "publisher": PublisherReader(cfg, root), "render": renderer(root)}


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
