#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""What a step kind is handed to reach anything outside the project's files (package P8, limit L30): the services of the engine's Context.

A step kind (runtime/step_*.py) imports no module that calls a provider. Whatever it needs from one, it asks of `ctx.services`, and this
module builds those services, once, for the process that runs the task (runtime/ops_steps.py). Each is as narrow as the kind's need:

  config           the project's configuration (runtime/project_config.py load), read once
  documents        DocumentsReader: `read`, `stat` and `table_read` of the project's documents provider (a page's text; a page's existence;
                   a table's columns, row count and newest edit), and what the kind asks about it (`enabled`, `provider`, `problem`: why a
                   write to it is not allowed now). It has no `write`: the verbs it calls are three literals, all reads.
  source_pin       function(source id) -> {"sha256": the converted text of the source's newest version, "page": the source's page as a
                   normalised identifier or None} or None: what a write-back compares the target with
  effect_files     EffectFiles: write and read the effect document of a cycle of a task, by hash (runtime/ops_step_effects.py holds the
                   folder); the approval and the execution are not here
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
import sources  # noqa: E402

READ_VERBS = ("read", "stat", "table-read")      # the only verbs of the documents provider a step kind can reach
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

    def _call(self, verb: str, target: str) -> dict:
        assert verb in READ_VERBS
        try:
            return documents.call(self._cfg, self._root, verb, ["--id", target])
        except documents.DocumentsError as e:
            raise StepServiceError("not_configured" if e.kind == "not configured" else "provider_failed", e.detail) from None

    def read(self, target: str) -> dict:
        return self._call("read", target)

    def stat(self, target: str) -> dict:
        return self._call("stat", target)

    def table_read(self, table: str) -> dict:
        """A table's columns, their hash, its row count and the time of its newest edit (the provider's table-read; it changes nothing)."""
        return self._call("table-read", table)


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
            "render": renderer(root)}


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
