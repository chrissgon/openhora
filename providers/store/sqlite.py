#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Store provider on SQLite: the agent runtime's durable state in one local database file.

Tables: cursors (where a trigger source left off), events (triggers to handle, deduplicated and
claimed atomically), runs (one row per agent run), inbox (what waits for the user) and actions
(outward actions the runtime executed, for daily limits and audit). The first runtime (scripts/runtime.py) calls
this script through its CLI, so another implementation of the `store:runtime` class can replace it (STORE_PROVIDER).

Since schema version 2 the file also holds the tables of the task runtime (runtime/): tasks (a request and the
tasks of its plan), task_runs (one row per run of a skill on a task) and pending_decisions (what a task waits
for the person to decide). Those three are read and written through the functions of the section "the task
runtime" below, which runtime/ops.py imports: one function call is one transaction. They have no CLI verb;
`export` prints them. Schema version 4 adds a task's item on the task board (three columns of tasks), the
records of documents mirrored to a platform (document_records) and the comments saved from a platform
(platform_comments), under the same rule. Schema version 5 adds the approvals table (approvals): what the person
approved, of the three scopes of contracts/environment.md, a record that only grows. Schema version 6 adds the
messages of the conversation with the planning agent (conversation_messages), and the functions the dispatcher needs
(a named task claimed, tasks added to a plan, the runs of a period, the actions counted in process). Schema version 7
adds triggers that refuse to delete a task, a task run or a pending decision (limit L13, as for the approvals). Schema
version 8 adds the derived waits between requests: the `after_request` column of a request and the task_waits table (a
planned task waits for another task, or for a whole request, with the reason shown to the person), under the same rule.
Schema version 9 adds the `billing` column of task_runs: how the credential a run used is billed (or `unknown`), which the daily caps count by.
Schema version 10 adds the `model` column of tasks (a request or a task: a model id or `auto`, NULL for a row older than the column),
and the `autonomy` column of task_runs (`proven`, `consent` or `supervised`: how the run's pair was released, NULL for a run older than the column).
Schema version 15 adds a stop request to a request or a task (`stop_requested_at`, `stop_requested_by`) and the run status `cancelled`.
Schema version 16 adds the `language` column of tasks (a request or a task: the language tag the person asked the deliverable in, NULL when
not requested: the project's `language` setting decides then).
Schema version 17 adds the `actor` column of pending_decisions and of approvals (POL-2): who acted when a decision was resolved or an approval
was made (`terminal`, `page`, `mcp`, or `messaging:<platform>:<profile>:<sender id>`), NULL for a row older than the column. It names a person's
messaging account, so it lives in the store only; the approvals trigger refuses to change it, as it refuses every other column but the status.

Concurrency: the database runs in WAL mode (readers never block the writer) with a 10-second busy
timeout, and every write is one BEGIN IMMEDIATE transaction, so several agents and overlapping
scheduler firings can write at once and each change is all or nothing. Claiming events happens
inside one such transaction: two processes never receive the same event.

Standard library only. Every SQL statement is a constant with ? parameters; no value is ever
formatted into SQL. Payloads may hold text written by other people (notification e-mails,
comments): the store keeps it exactly as given and never interprets it.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import secrets
import sqlite3
import stat
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCHEMA_VERSION = 21
BUSY_TIMEOUT_SECONDS = 10
PATH_ENV = "STORE_SQLITE_PATH"

# Caps, in UTF-8 bytes. Above a cap the verb stops with exit 2 and stores nothing.
PAYLOAD_MAX = 64 * 1024   # --payload-file, --result-file
NOTE_MAX = 4 * 1024       # --note, --error
VALUE_MAX = 4 * 1024      # cursor values
TITLE_MAX = 1024          # inbox titles
REF_MAX = 512             # external ids, targets, idempotency keys
ACTOR_MAX = 384           # the actor of a resolution or an approval: "messaging:" + a platform (32) + a profile (32) + an id (254) and the colons
LABEL_MAX = 128           # source, name, kind, agent, trigger, by
PATH_MAX = 4096           # --out-dir, --db
TEXT_MAX = 64 * 1024      # the text of a request or a task, an answer
BODY_MAX = 1024 * 1024    # the body of a pending decision: a model's whole reply
INT_MIN, INT_MAX = -2 ** 63, 2 ** 63 - 1  # SQLite's INTEGER; a Python int past it cannot be stored or compared

LIMITS = {"event-next": (1, 1, 100), "runs": (20, 1, 1000), "inbox-list": (100, 1, 1000),
          "actions": (1000, 1, 10000)}  # verb: (default, min, max) for --limit
RECLAIM_DEFAULT_MINUTES = 60
RECLAIM_MIN_MINUTES = 1
RECLAIM_MAX_MINUTES = 7 * 24 * 60
# An event claimed this many times whose last claim expired too is not handed out again: it ends failed.
MAX_ATTEMPTS = 5

EVENT_DONE_STATUSES = ("done", "failed", "to_inbox")
RUN_END_STATUSES = ("ok", "failed", "timeout")
INBOX_STATUSES = ("open", "approved", "rejected", "done")
# inbox-resolve moves an item forward only: open -> approved | rejected | done, approved -> done.
INBOX_TRANSITIONS = {"open": ("approved", "rejected", "done"), "approved": ("done",)}

SHA256_RE = re.compile(r"[0-9a-f]{64}")
# Control characters. Single-line fields refuse all of them; notes and errors keep tab and newline.
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
CONTROL_MULTILINE_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")

EXIT_OK, EXIT_ERROR, EXIT_USAGE, EXIT_NOT_CONFIGURED = 0, 1, 2, 3

MIGRATIONS = {
    1: ("cursors, events, runs, inbox and actions", [
        """CREATE TABLE cursors (
            name TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL)""",
        """CREATE TABLE events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            external_id TEXT NOT NULL,
            payload TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'claimed', 'done', 'failed', 'to_inbox')),
            attempts INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            claimed_at TEXT,
            claim_token TEXT,
            finished_at TEXT,
            note TEXT,
            UNIQUE (source, external_id))""",
        "CREATE INDEX events_by_source_status ON events (source, status, id)",
        """CREATE TABLE runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent TEXT NOT NULL,
            event_id INTEGER REFERENCES events (id),
            trigger TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'running'
                CHECK (status IN ('running', 'ok', 'failed', 'timeout')),
            started_at TEXT NOT NULL,
            ended_at TEXT,
            exit_code INTEGER,
            cost_usd REAL,
            tokens INTEGER,
            duration_ms INTEGER,
            out_dir TEXT,
            error TEXT)""",
        "CREATE INDEX runs_by_agent ON runs (agent, id)",
        """CREATE TABLE inbox (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL,
            title TEXT NOT NULL,
            payload TEXT NOT NULL,
            payload_sha256 TEXT NOT NULL,
            event_id INTEGER REFERENCES events (id),
            status TEXT NOT NULL DEFAULT 'open'
                CHECK (status IN ('open', 'approved', 'rejected', 'done')),
            created_at TEXT NOT NULL,
            resolved_at TEXT,
            resolved_by TEXT,
            resolve_note TEXT,
            done_at TEXT,
            done_by TEXT,
            done_note TEXT)""",
        "CREATE INDEX inbox_by_status ON inbox (status, id)",
        """CREATE TABLE actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL,
            idempotency_key TEXT NOT NULL UNIQUE,
            target TEXT NOT NULL,
            payload_sha256 TEXT NOT NULL,
            result TEXT NOT NULL,
            created_at TEXT NOT NULL)""",
        "CREATE INDEX actions_by_kind_time ON actions (kind, created_at)",
    ]),
    2: ("tasks, task_runs and pending_decisions of the task runtime", [
        """CREATE TABLE tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            parent_id INTEGER REFERENCES tasks (id),
            flow TEXT,
            key TEXT,
            skill TEXT,
            agent TEXT,
            title TEXT NOT NULL,
            text TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'requested'
                CHECK (state IN ('requested', 'planned', 'ready', 'running', 'waiting', 'blocked', 'done',
                                 'failed', 'cancelled')),
            depends_on TEXT NOT NULL DEFAULT '[]',
            milestone INTEGER NOT NULL DEFAULT 0 CHECK (milestone IN (0, 1)),
            note TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL)""",
        "CREATE INDEX tasks_by_state ON tasks (state, id)",
        "CREATE INDEX tasks_by_parent ON tasks (parent_id, id)",
        """CREATE TABLE task_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL REFERENCES tasks (id),
            skill TEXT NOT NULL,
            skill_version TEXT,
            skill_sha256 TEXT,
            model TEXT NOT NULL,
            adapter TEXT NOT NULL,
            web INTEGER NOT NULL DEFAULT 0 CHECK (web IN (0, 1)),
            status TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'ok', 'failed')),
            failure TEXT CHECK (failure IS NULL OR failure IN ('timeout', 'refused', 'auth', 'adapter',
                                                                'early_end', 'settings', 'stopped', 'internal')),
            ending TEXT CHECK (ending IS NULL OR ending IN ('done', 'question', 'draft_with_questions', 'gate',
                                                              'blocked', 'unclassified')),
            attempts INTEGER NOT NULL DEFAULT 0,
            started_at TEXT NOT NULL,
            ended_at TEXT,
            cost_usd REAL,
            tokens INTEGER,
            duration_ms INTEGER,
            skill_loaded INTEGER CHECK (skill_loaded IS NULL OR skill_loaded IN (0, 1)),
            image_digest TEXT,
            run_dir TEXT,
            error TEXT)""",
        "CREATE INDEX task_runs_by_task ON task_runs (task_id, id)",
        """CREATE TABLE pending_decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL REFERENCES tasks (id),
            run_id INTEGER REFERENCES task_runs (id),
            kind TEXT NOT NULL
                CHECK (kind IN ('plan', 'question', 'review', 'effect', 'acceptance', 'your_document')),
            title TEXT NOT NULL,
            body TEXT NOT NULL,
            payload TEXT NOT NULL DEFAULT '{}',
            payload_sha256 TEXT,
            status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'resolved', 'cancelled')),
            resolution TEXT,
            answer TEXT,
            created_at TEXT NOT NULL,
            resolved_at TEXT,
            resolved_by TEXT)""",
        "CREATE INDEX pending_decisions_by_status ON pending_decisions (status, id)",
        "CREATE INDEX pending_decisions_by_task ON pending_decisions (task_id, id)",
    ]),
    3: ("the number of values the lab replaced in what a task run left", [
        "ALTER TABLE task_runs ADD COLUMN redactions INTEGER",
    ]),
    4: ("a task's item on the task board, the records of mirrored documents and saved platform comments", [
        "ALTER TABLE tasks ADD COLUMN remote_id TEXT",
        "ALTER TABLE tasks ADD COLUMN remote_version TEXT",
        "ALTER TABLE tasks ADD COLUMN remote_written_sha256 TEXT",
        """CREATE TABLE document_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            path TEXT NOT NULL UNIQUE,
            provider TEXT NOT NULL,
            remote_id TEXT,
            written_sha256 TEXT,
            remote_version TEXT,
            read_sha256 TEXT,
            status TEXT NOT NULL DEFAULT 'mirrored' CHECK (status IN ('mirrored', 'read_only', 'rejected')),
            note TEXT,
            updated_at TEXT NOT NULL)""",
        """CREATE TABLE platform_comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            provider TEXT NOT NULL,
            remote_id TEXT NOT NULL,
            subject TEXT NOT NULL CHECK (subject IN ('task', 'document')),
            task_id INTEGER REFERENCES tasks (id),
            document_path TEXT,
            author TEXT,
            text TEXT NOT NULL,
            created_at TEXT,
            saved_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'used', 'dismissed')),
            used_by_pending INTEGER REFERENCES pending_decisions (id),
            UNIQUE (provider, remote_id))""",
        "CREATE INDEX platform_comments_by_status ON platform_comments (status, id)",
    ]),
    5: ("the approvals table: what the person approved, a record that only grows", [
        """CREATE TABLE approvals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scope TEXT NOT NULL CHECK (scope IN ('action', 'plan', 'standing')),
            what TEXT NOT NULL,
            payload_sha256 TEXT,
            policy_sha256 TEXT,
            bounds TEXT,
            task_id INTEGER REFERENCES tasks (id),
            pending_id INTEGER REFERENCES pending_decisions (id),
            approved_at TEXT NOT NULL,
            approved_by TEXT NOT NULL,
            expires_at TEXT,
            status TEXT NOT NULL
                CHECK (status IN ('pending-execution', 'executed', 'active', 'expired', 'revoked')),
            executed_at TEXT)""",
        "CREATE INDEX approvals_by_pending ON approvals (pending_id, id)",
        "CREATE INDEX approvals_by_status ON approvals (status, id)",
        # Limit L13 in the database itself: no row is deleted, only status and executed_at change, and a status
        # moves only forward (pending-execution to executed or revoked; active to expired or revoked).
        """CREATE TRIGGER approvals_never_deleted BEFORE DELETE ON approvals
            BEGIN SELECT RAISE(ABORT, 'an approval is never deleted'); END""",
        """CREATE TRIGGER approvals_only_status_moves BEFORE UPDATE ON approvals
            WHEN NEW.id IS NOT OLD.id OR NEW.scope IS NOT OLD.scope OR NEW.what IS NOT OLD.what
              OR NEW.payload_sha256 IS NOT OLD.payload_sha256 OR NEW.policy_sha256 IS NOT OLD.policy_sha256
              OR NEW.bounds IS NOT OLD.bounds OR NEW.task_id IS NOT OLD.task_id OR NEW.pending_id IS NOT OLD.pending_id
              OR NEW.approved_at IS NOT OLD.approved_at OR NEW.approved_by IS NOT OLD.approved_by
              OR NEW.expires_at IS NOT OLD.expires_at
              OR (NEW.status IS NOT OLD.status AND NOT (
                    (OLD.status = 'pending-execution' AND NEW.status IN ('executed', 'revoked'))
                 OR (OLD.status = 'active' AND NEW.status IN ('expired', 'revoked'))))
            BEGIN SELECT RAISE(ABORT, 'an approval only moves forward: its status, never its content'); END""",
    ]),
    6: ("the messages of the conversation with the planning agent", [
        """CREATE TABLE conversation_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation TEXT NOT NULL,
            role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
            text TEXT NOT NULL,
            task_id INTEGER REFERENCES tasks (id),
            run_id INTEGER REFERENCES task_runs (id),
            created_at TEXT NOT NULL)""",
        "CREATE INDEX conversation_messages_by_conversation ON conversation_messages (conversation, id)",
    ]),
    # Limit L13 for the task runtime's own records: a task, a run and a pending decision are never deleted (a state,
    # a status or a resolution moves; the row stays), as migration 5 does for the approvals.
    7: ("tasks, task runs and pending decisions are never deleted", [
        """CREATE TRIGGER tasks_never_deleted BEFORE DELETE ON tasks
            BEGIN SELECT RAISE(ABORT, 'a task is never deleted'); END""",
        """CREATE TRIGGER task_runs_never_deleted BEFORE DELETE ON task_runs
            BEGIN SELECT RAISE(ABORT, 'a task run is never deleted'); END""",
        """CREATE TRIGGER pending_decisions_never_deleted BEFORE DELETE ON pending_decisions
            BEGIN SELECT RAISE(ABORT, 'a pending decision is never deleted'); END""",
    ]),
    8: ("derived waits between requests: a request's after_request and the task_waits table", [
        "ALTER TABLE tasks ADD COLUMN after_request INTEGER REFERENCES tasks (id)",
        # One row per wait of a planned task: kind `input` (a path another request's task writes: awaited_id is that
        # task) or `after` (the person's override: awaited_id is the request). A wait is open until its awaited row is
        # done or cancelled or the runtime derives it no longer (cleared), or the person goes ahead (dropped): a dropped
        # row is the person's decision about that path and that awaited task, and the runtime derives it no more.
        """CREATE TABLE task_waits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL REFERENCES tasks (id),
            awaited_id INTEGER NOT NULL REFERENCES tasks (id),
            kind TEXT NOT NULL CHECK (kind IN ('input', 'after')),
            path TEXT,
            reason TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'cleared', 'dropped')),
            created_at TEXT NOT NULL,
            ended_at TEXT,
            ended_by TEXT)""",
        "CREATE INDEX task_waits_by_task ON task_waits (task_id, status)",
        "CREATE INDEX task_waits_by_awaited ON task_waits (awaited_id, status)",
        # Limit L13, as for the other records of the task runtime: a wait is never deleted, it ends.
        """CREATE TRIGGER task_waits_never_deleted BEFORE DELETE ON task_waits
            BEGIN SELECT RAISE(ABORT, 'a task wait is never deleted'); END""",
    ]),
    # ADJ-R3 (row A-38): the billing of the credential a run used, written when the run starts. The daily caps count by it
    # (subscription and free: runs; metered and unknown: dollars). 'unknown' is a run whose route no manifest could bill; a run
    # older than the column has none (NULL): history only, counted by the tier rule it had.
    9: ("the billing of the credential a task run used", [
        "ALTER TABLE task_runs ADD COLUMN billing TEXT CHECK (billing IS NULL OR billing IN ('subscription', 'metered', 'free', 'unknown'))",
    ]),
    # P3: the choice of the model. A request or a task carries a model id or `auto` (NULL: none chosen, so the agent's fixed model, else the
    # project's default, decide). A run records how its pair was released: `proven` (lab or local evidence), `consent` (the person fixed the
    # agent's model with the agent autonomous, decisions D34 and D38) or `supervised` (held for review). A run older than the column has none.
    10: ("the model of a request or a task, and the autonomy of a task run", [
        "ALTER TABLE tasks ADD COLUMN model TEXT",
        "ALTER TABLE task_runs ADD COLUMN autonomy TEXT CHECK (autonomy IS NULL OR autonomy IN ('proven', 'consent', 'supervised'))",
    ]),
    # P4: the sources of a project. `sources` is the registry (an id, a type, an origin that holds no credential, a description the
    # person may change); `source_versions` one immutable row per imported version (hashes, sizes, the converter, the catalog entry
    # built by code, a hidden-text flag P8 fills in); `task_sources` the versions a run of a task received (decision D29). A task
    # carries the ids the approved plan chose for it in `tasks.sources` (a JSON list, NULL when none). Nothing here is deleted, and a
    # version is never changed: a refresh is a new version number (limit L13, as for the other records of the task runtime).
    11: ("the registry of sources, their versions, and the versions a task run received", [
        """CREATE TABLE sources (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL CHECK (type IN ('file', 'notion')),
            origin TEXT NOT NULL,
            description TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL)""",
        """CREATE TABLE source_versions (
            source_id TEXT NOT NULL REFERENCES sources (id),
            version INTEGER NOT NULL CHECK (version >= 1),
            label TEXT NOT NULL CHECK (label IN ('import', 'refresh', 'changed-by-person')),
            by TEXT NOT NULL CHECK (by IN ('runtime', 'person')),
            kind TEXT NOT NULL,
            original_name TEXT NOT NULL,
            original_sha256 TEXT NOT NULL,
            original_bytes INTEGER NOT NULL,
            converted_name TEXT NOT NULL,
            converted_sha256 TEXT NOT NULL,
            converted_bytes INTEGER NOT NULL,
            converter TEXT NOT NULL,
            converter_version TEXT,
            hidden_text INTEGER CHECK (hidden_text IS NULL OR hidden_text IN (0, 1)),
            warnings TEXT NOT NULL DEFAULT '[]',
            catalog TEXT NOT NULL,
            origin_version TEXT,
            imported_at TEXT NOT NULL,
            PRIMARY KEY (source_id, version))""",
        """CREATE TABLE task_sources (
            run_id INTEGER NOT NULL REFERENCES task_runs (id),
            task_id INTEGER NOT NULL REFERENCES tasks (id),
            source_id TEXT NOT NULL,
            version INTEGER NOT NULL,
            sha256 TEXT NOT NULL,
            copied_at TEXT NOT NULL,
            PRIMARY KEY (run_id, source_id))""",
        "CREATE INDEX task_sources_by_task ON task_sources (task_id, run_id)",
        "ALTER TABLE tasks ADD COLUMN sources TEXT",
        """CREATE TRIGGER sources_never_deleted BEFORE DELETE ON sources
            BEGIN SELECT RAISE(ABORT, 'a source is never deleted'); END""",
        """CREATE TRIGGER sources_only_description_moves BEFORE UPDATE ON sources
            WHEN NEW.id IS NOT OLD.id OR NEW.type IS NOT OLD.type OR NEW.origin IS NOT OLD.origin OR NEW.created_at IS NOT OLD.created_at
            BEGIN SELECT RAISE(ABORT, 'a source keeps its id, type and origin: only its description changes'); END""",
        """CREATE TRIGGER source_versions_never_deleted BEFORE DELETE ON source_versions
            BEGIN SELECT RAISE(ABORT, 'a source version is never deleted'); END""",
        """CREATE TRIGGER source_versions_never_changed BEFORE UPDATE ON source_versions
            BEGIN SELECT RAISE(ABORT, 'a source version is never changed: a refresh is a new version'); END""",
        """CREATE TRIGGER task_sources_never_deleted BEFORE DELETE ON task_sources
            BEGIN SELECT RAISE(ABORT, 'the record of a source a run received is never deleted'); END""",
        """CREATE TRIGGER task_sources_never_changed BEFORE UPDATE ON task_sources
            BEGIN SELECT RAISE(ABORT, 'the record of a source a run received is never changed'); END""",
    ]),
    # P5: the step task. A task that runs no skill: code runs it, in a process of its own, as the step engine of runtime/steps.py
    # (an ingestion, later the steps of a media pipeline or a file output). `step_kind` names its kind in the engine's registry
    # (NULL for every skill task and for every row older than the column); `step_args` is its arguments as canonical JSON, which
    # the plan's hash covers; `step_footprint` the project paths the kind declares it writes (a JSON list, derived from the kind,
    # never from free text), which the admission rule weighs against the files other tasks write; `step_state` the engine's
    # progress (each step and its closed result), so that a task stopped, failed or killed resumes at its step.
    12: ("the step task: its kind, arguments, footprint and state", [
        "ALTER TABLE tasks ADD COLUMN step_kind TEXT",
        "ALTER TABLE tasks ADD COLUMN step_args TEXT",
        "ALTER TABLE tasks ADD COLUMN step_footprint TEXT",
        "ALTER TABLE tasks ADD COLUMN step_state TEXT",
    ]),
    # P6a: a task that runs a skill without the web the skill requires. A flow may say "web": false for a task (the code-made
    # split of the flow check gives the skill that follows a research task this, so that a skill which requires the web never
    # reads sources with the open network). 1 means the run is routed with the web off whatever the skill requires; NULL (every
    # task that says nothing, and every row older than the column) leaves it to the skill. The plan's hash covers the word, and the run reads this column only.
    13: ("a task that runs its skill without the web", [
        "ALTER TABLE tasks ADD COLUMN web_off INTEGER CHECK (web_off IS NULL OR web_off = 1)",
    ]),
    # P6b: routines, their fires, and the Drive source type. A routine is a flow started by a schedule; it is created as a draft and
    # becomes active only when the person approves the sha256 of its exact content (decision D23, D35): `approved_sha256` is that hash and
    # any change to the record clears it. It carries no mode, cap, policy or standing approval of its own. A fire is keyed by the routine
    # and the slot (`UNIQUE (routine_id, slot)`), so one slot never creates tasks twice (finding I5): a fire, its skipped slots and the
    # stop that asks for a decision are rows, and a fire's request is created in the same transaction as its row. Nothing here is deleted
    # or changed once written (limit L13). The sources table is rebuilt to admit `drive` (P7 stored a Drive file as a `file` row whose
    # origin was `drive:<file id>`; those rows are rewritten to type `drive` and the bare id, and their versions are not touched).
    14: ("routines, their fires, and the Drive source type", [
        "PRAGMA defer_foreign_keys = ON",
        "CREATE TABLE sources_before_14 AS SELECT * FROM sources",
        "DROP TABLE sources",
        """CREATE TABLE sources (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL CHECK (type IN ('file', 'notion', 'drive')),
            origin TEXT NOT NULL,
            description TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL)""",
        """INSERT INTO sources (id, type, origin, description, created_at, updated_at)
            SELECT id,
                   CASE WHEN type = 'file' AND origin LIKE 'drive:%' THEN 'drive' ELSE type END,
                   CASE WHEN type = 'file' AND origin LIKE 'drive:%' THEN substr(origin, 7) ELSE origin END,
                   description, created_at, updated_at FROM sources_before_14""",
        "DROP TABLE sources_before_14",
        """CREATE TRIGGER sources_never_deleted BEFORE DELETE ON sources
            BEGIN SELECT RAISE(ABORT, 'a source is never deleted'); END""",
        """CREATE TRIGGER sources_only_description_moves BEFORE UPDATE ON sources
            WHEN NEW.id IS NOT OLD.id OR NEW.type IS NOT OLD.type OR NEW.origin IS NOT OLD.origin OR NEW.created_at IS NOT OLD.created_at
            BEGIN SELECT RAISE(ABORT, 'a source keeps its id, type and origin: only its description changes'); END""",
        """CREATE TABLE routines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            flow TEXT NOT NULL,
            params TEXT NOT NULL DEFAULT '{}',
            schedule TEXT NOT NULL,
            model TEXT,
            consent INTEGER NOT NULL DEFAULT 0 CHECK (consent IN (0, 1)),
            providers TEXT NOT NULL DEFAULT '[]',
            window_seconds INTEGER CHECK (window_seconds IS NULL OR window_seconds >= 60),
            state TEXT NOT NULL CHECK (state IN ('draft', 'active', 'paused', 'stopped', 'cancelled')),
            approved_sha256 TEXT,
            approved_content TEXT,
            approved_at TEXT,
            approved_by TEXT,
            resumed_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL)""",
        """CREATE TABLE routine_fires (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            routine_id INTEGER NOT NULL REFERENCES routines (id),
            slot TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('created', 'asked', 'skipped')),
            reason TEXT,
            request_id INTEGER REFERENCES tasks (id),
            fired_at TEXT NOT NULL,
            UNIQUE (routine_id, slot))""",
        "CREATE INDEX routine_fires_by_request ON routine_fires (request_id)",
        """CREATE TRIGGER routines_never_deleted BEFORE DELETE ON routines
            BEGIN SELECT RAISE(ABORT, 'a routine is never deleted: it is cancelled'); END""",
        """CREATE TRIGGER routine_fires_never_deleted BEFORE DELETE ON routine_fires
            BEGIN SELECT RAISE(ABORT, 'the record of a fire is never deleted'); END""",
        """CREATE TRIGGER routine_fires_never_changed BEFORE UPDATE ON routine_fires
            BEGIN SELECT RAISE(ABORT, 'the record of a fire is never changed'); END""",
    ]),
    # R18: cancel or stop at any moment. `stop_requested_at` and `stop_requested_by` record that the person asked to end what is
    # running: on a request row, "cancel this request"; on a task row, "stop this task". The request is written first, in one
    # transaction, and the run that ends reads it in its own, so that nothing a stopped run made comes back. A run that was stopped
    # ends `cancelled` (failure NULL), a status the table now admits: task_runs is rebuilt for the new CHECK, as migration 14 rebuilt
    # sources (every row, id, index, trigger and reference kept; the three tables that reference it are checked at the commit).
    15: ("a stop request on a request or a task, and the run status `cancelled`", [
        "ALTER TABLE tasks ADD COLUMN stop_requested_at TEXT",
        "ALTER TABLE tasks ADD COLUMN stop_requested_by TEXT",
        "PRAGMA defer_foreign_keys = ON",
        "CREATE TABLE task_runs_before_15 AS SELECT * FROM task_runs",
        "DROP TABLE task_runs",
        """CREATE TABLE task_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL REFERENCES tasks (id),
            skill TEXT NOT NULL,
            skill_version TEXT,
            skill_sha256 TEXT,
            model TEXT NOT NULL,
            adapter TEXT NOT NULL,
            web INTEGER NOT NULL DEFAULT 0 CHECK (web IN (0, 1)),
            status TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'ok', 'failed', 'cancelled')),
            failure TEXT CHECK (failure IS NULL OR failure IN ('timeout', 'refused', 'auth', 'adapter',
                                                                'early_end', 'settings', 'stopped', 'internal')),
            ending TEXT CHECK (ending IS NULL OR ending IN ('done', 'question', 'draft_with_questions', 'gate',
                                                              'blocked', 'unclassified')),
            attempts INTEGER NOT NULL DEFAULT 0,
            started_at TEXT NOT NULL,
            ended_at TEXT,
            cost_usd REAL,
            tokens INTEGER,
            duration_ms INTEGER,
            skill_loaded INTEGER CHECK (skill_loaded IS NULL OR skill_loaded IN (0, 1)),
            image_digest TEXT,
            run_dir TEXT,
            error TEXT,
            redactions INTEGER,
            billing TEXT CHECK (billing IS NULL OR billing IN ('subscription', 'metered', 'free', 'unknown')),
            autonomy TEXT CHECK (autonomy IS NULL OR autonomy IN ('proven', 'consent', 'supervised')))""",
        """INSERT INTO task_runs (id, task_id, skill, skill_version, skill_sha256, model, adapter, web, status, failure, ending,
                                attempts, started_at, ended_at, cost_usd, tokens, duration_ms, skill_loaded, image_digest, run_dir,
                                error, redactions, billing, autonomy)
            SELECT id, task_id, skill, skill_version, skill_sha256, model, adapter, web, status, failure, ending,
                   attempts, started_at, ended_at, cost_usd, tokens, duration_ms, skill_loaded, image_digest, run_dir,
                   error, redactions, billing, autonomy FROM task_runs_before_15 ORDER BY id""",
        "DROP TABLE task_runs_before_15",
        "CREATE INDEX task_runs_by_task ON task_runs (task_id, id)",
        """CREATE TRIGGER task_runs_never_deleted BEFORE DELETE ON task_runs
            BEGIN SELECT RAISE(ABORT, 'a task run is never deleted'); END""",
    ]),
    # LANGUAGE: the language the person asked a deliverable to be written in (`request --language`, the page's language select, or the
    # one the router proposed and the person saw on the plan card). A request carries it from the start; each task takes it from the plan
    # when the plan is approved, as `model` is carried. NULL: not requested, so the project's `language` setting (runtime.json) decides.
    # The tag has the shape runtime/language.py checks (two lower-case letters, optionally a hyphen and two upper-case letters).
    16: ("the language a request or a task asks its deliverable in", [
        "ALTER TABLE tasks ADD COLUMN language TEXT CHECK (language IS NULL OR language GLOB '[a-z][a-z]' "
        "OR language GLOB '[a-z][a-z]-[A-Z][A-Z]')",
    ]),
    # POL-2: who acted. A decision resolved from a messaging app records the platform, the profile the sender had and the sender's id (an account
    # of a person: the store only, never a file of the project); the terminal, the page and the MCP mode record their own name. `resolved_by` and
    # `approved_by` keep the kind of actor they always had ("user", "code", "mode:<mode>"). The approvals trigger is made again with the new
    # column in its list: an approval only moves forward, and its actor never changes.
    17: ("the actor of a resolution and of an approval", [
        "ALTER TABLE pending_decisions ADD COLUMN actor TEXT",
        "ALTER TABLE approvals ADD COLUMN actor TEXT",
        "DROP TRIGGER approvals_only_status_moves",
        """CREATE TRIGGER approvals_only_status_moves BEFORE UPDATE ON approvals
            WHEN NEW.id IS NOT OLD.id OR NEW.scope IS NOT OLD.scope OR NEW.what IS NOT OLD.what
              OR NEW.payload_sha256 IS NOT OLD.payload_sha256 OR NEW.policy_sha256 IS NOT OLD.policy_sha256
              OR NEW.bounds IS NOT OLD.bounds OR NEW.task_id IS NOT OLD.task_id OR NEW.pending_id IS NOT OLD.pending_id
              OR NEW.approved_at IS NOT OLD.approved_at OR NEW.approved_by IS NOT OLD.approved_by
              OR NEW.expires_at IS NOT OLD.expires_at OR NEW.actor IS NOT OLD.actor
              OR (NEW.status IS NOT OLD.status AND NOT (
                    (OLD.status = 'pending-execution' AND NEW.status IN ('executed', 'revoked'))
                 OR (OLD.status = 'active' AND NEW.status IN ('expired', 'revoked'))))
            BEGIN SELECT RAISE(ABORT, 'an approval only moves forward: its status, never its content'); END""",
    ]),
    # ATT-1: a file a listed sender sent through a messaging app. `attachments` is the record of one file from the moment its bytes are held in
    # <data_dir>/attachments/held/ until a person decides: it ends `added` (a source version, with its source id and number), `discarded`, `expired`
    # (a week without an answer) or `refused` (a rule of the intake or a refusal of the conversion). It keeps the sender's id (the only place that
    # does: a source version, its manifest and the catalog carry the platform and the profile name, never the id), the platform's reference only
    # as a hash (the reference is what the platform fetches the file by), the sniffed kind and the file's own sha256. The bytes of a refused,
    # discarded or expired file are deleted; the row stays. Nothing is deleted from this table, and a row leaves `held` once: its decision is final.
    # `source_versions.provenance` is how a version says where it came from ({"channel", "platform", "profile", "attachment"} as JSON; NULL for
    # a version a person added in the terminal or on the page).
    18: ("held attachments, and the provenance of a source version", [
        """CREATE TABLE attachments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            platform TEXT NOT NULL,
            ref_sha256 TEXT NOT NULL,
            sender TEXT NOT NULL,
            profile TEXT,
            name TEXT NOT NULL,
            declared_type TEXT,
            declared_bytes INTEGER,
            kind TEXT,
            sha256 TEXT,
            bytes INTEGER NOT NULL,
            target TEXT,
            label TEXT CHECK (label IS NULL OR label IN ('import', 'refresh')),
            direct INTEGER NOT NULL DEFAULT 0 CHECK (direct IN (0, 1)),
            status TEXT NOT NULL CHECK (status IN ('held', 'added', 'refused', 'discarded', 'expired')),
            code TEXT,
            source_id TEXT,
            version INTEGER,
            created_at TEXT NOT NULL,
            decided_at TEXT)""",
        "CREATE UNIQUE INDEX attachments_one_held ON attachments (platform, ref_sha256) WHERE status = 'held'",
        "CREATE INDEX attachments_by_status ON attachments (status, id)",
        "CREATE INDEX attachments_by_day ON attachments (created_at)",
        "ALTER TABLE source_versions ADD COLUMN provenance TEXT",
        """CREATE TRIGGER attachments_never_deleted BEFORE DELETE ON attachments
            BEGIN SELECT RAISE(ABORT, 'the record of an attachment is never deleted'); END""",
        """CREATE TRIGGER attachments_decided_once BEFORE UPDATE ON attachments
            WHEN OLD.status != 'held' OR NEW.status = 'held'
              OR NEW.id IS NOT OLD.id OR NEW.platform IS NOT OLD.platform OR NEW.ref_sha256 IS NOT OLD.ref_sha256
              OR NEW.sender IS NOT OLD.sender OR NEW.profile IS NOT OLD.profile OR NEW.name IS NOT OLD.name
              OR NEW.declared_type IS NOT OLD.declared_type OR NEW.declared_bytes IS NOT OLD.declared_bytes OR NEW.kind IS NOT OLD.kind
              OR NEW.sha256 IS NOT OLD.sha256 OR NEW.bytes IS NOT OLD.bytes OR NEW.target IS NOT OLD.target OR NEW.label IS NOT OLD.label
              OR NEW.direct IS NOT OLD.direct OR NEW.created_at IS NOT OLD.created_at
            BEGIN SELECT RAISE(ABORT, 'an attachment leaves held once: its decision is final and the rest of the row never changes'); END""",
    ]),
    # O2: OneDrive files as sources. The sources table is rebuilt to admit `onedrive` exactly as migration 14 rebuilt it to admit `drive`:
    # the same columns, the same two triggers, every row copied as it is (no row is rewritten, and the versions are not touched). The next
    # source type (mail, calendar: RT-1) is one more migration that rebuilds the table the same way, with its word added to the CHECK and
    # to SOURCE_TYPES below.
    19: ("the OneDrive source type", [
        "PRAGMA defer_foreign_keys = ON",
        "CREATE TABLE sources_before_19 AS SELECT * FROM sources",
        "DROP TABLE sources",
        """CREATE TABLE sources (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL CHECK (type IN ('file', 'notion', 'drive', 'onedrive')),
            origin TEXT NOT NULL,
            description TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL)""",
        """INSERT INTO sources (id, type, origin, description, created_at, updated_at)
            SELECT id, type, origin, description, created_at, updated_at FROM sources_before_19""",
        "DROP TABLE sources_before_19",
        """CREATE TRIGGER sources_never_deleted BEFORE DELETE ON sources
            BEGIN SELECT RAISE(ABORT, 'a source is never deleted'); END""",
        """CREATE TRIGGER sources_only_description_moves BEFORE UPDATE ON sources
            WHEN NEW.id IS NOT OLD.id OR NEW.type IS NOT OLD.type OR NEW.origin IS NOT OLD.origin OR NEW.created_at IS NOT OLD.created_at
            BEGIN SELECT RAISE(ABORT, 'a source keeps its id, type and origin: only its description changes'); END""",
    ]),
    # Migration 20 (RM-1, reminders; after O2's 19). A reminder is a stored one-shot notice that the messaging bridge sends to the chat that
    # made it, with the person's own words, at a moment: a notice and never an effect. `text` is the person's own words (never logged, never in an export,
    # a card or a catalog), `platform` and `chat` the one place it may be sent (a private chat whose id is a listed sender's), `created_by` the actor as
    # POL-2 records it, `due_local` the wall time as it was asked and `zone` its name, `due_utc` the instant (fixed-width UTC, so that times compare as
    # text). A reminder is `open`, claimed as `sending` by the one tick that sends it (a crash in between leaves it `sending`; after a while it is open
    # again, so a line may go twice and never zero times), then `sent`; or it ends `cancelled` (the person forgot it), `missed` (it was later than the late
    # window when a bridge looked: why `late`) or `dropped` (the sender was removed or narrowed before it fired: why `sender removed` or `not permitted`).
    # A send that failed gives the claim back (`attempts` counts the failures, `retry_after` is the earliest next try: 1, 2, 4, 8 ... minutes).
    # A row is never deleted; what it was asked and for whom never changes; an ended row stays as it ended.
    20: ("reminders, the one-shot notices the messaging bridge sends", [
        """CREATE TABLE reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT NOT NULL,
            due_local TEXT NOT NULL,
            due_utc TEXT NOT NULL,
            zone TEXT NOT NULL,
            platform TEXT NOT NULL,
            chat TEXT NOT NULL,
            created_by TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('open', 'sending', 'sent', 'cancelled', 'missed', 'dropped')),
            why TEXT CHECK (why IS NULL OR why IN ('late', 'sender removed', 'not permitted')),
            created_at TEXT NOT NULL,
            claimed_at TEXT,
            ended_at TEXT,
            attempts INTEGER NOT NULL DEFAULT 0,
            retry_after TEXT,
            CHECK ((status IN ('missed', 'dropped')) = (why IS NOT NULL)))""",
        "CREATE INDEX reminders_by_status ON reminders (status, due_utc)",
        "CREATE INDEX reminders_by_chat ON reminders (platform, chat, id)",
        """CREATE TRIGGER reminders_never_deleted BEFORE DELETE ON reminders
            BEGIN SELECT RAISE(ABORT, 'the record of a reminder is never deleted'); END""",
        """CREATE TRIGGER reminders_fixed BEFORE UPDATE ON reminders
            WHEN NEW.id IS NOT OLD.id OR NEW.text IS NOT OLD.text OR NEW.due_local IS NOT OLD.due_local OR NEW.due_utc IS NOT OLD.due_utc
              OR NEW.zone IS NOT OLD.zone OR NEW.platform IS NOT OLD.platform OR NEW.chat IS NOT OLD.chat OR NEW.created_by IS NOT OLD.created_by
              OR NEW.created_at IS NOT OLD.created_at
            BEGIN SELECT RAISE(ABORT, 'what a reminder says, when and to whom never changes'); END""",
        """CREATE TRIGGER reminders_move BEFORE UPDATE ON reminders
            WHEN OLD.status IN ('sent', 'cancelled', 'missed', 'dropped')
              OR (OLD.status = 'open' AND NEW.status NOT IN ('open', 'sending', 'cancelled', 'missed', 'dropped'))
              OR (OLD.status = 'sending' AND NEW.status NOT IN ('sending', 'sent', 'open', 'missed', 'dropped'))
            BEGIN SELECT RAISE(ABORT, 'a reminder that ended stays as it ended, and is sent only after it was claimed'); END""",
    ]),
    # RT-1: a mail window and a calendar window as sources. Number 20 is the reminders package's (RM-1, merged before this one): a store that applied 21 without 20, or the other way, is refused by
    # `open_ready` (`missing_migrations`) until `_init` applies every number the store lacks, so the two can reach a store in either order. The sources table is rebuilt to admit
    # `mail` and `calendar` exactly as migrations 14 and 19 rebuilt it: the same columns, the same two triggers, every row copied as it is (no row is
    # rewritten, and the versions are not touched).
    21: ("the mail and calendar source types", [
        "PRAGMA defer_foreign_keys = ON",
        "CREATE TABLE sources_before_21 AS SELECT * FROM sources",
        "DROP TABLE sources",
        """CREATE TABLE sources (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL CHECK (type IN ('file', 'notion', 'drive', 'onedrive', 'mail', 'calendar')),
            origin TEXT NOT NULL,
            description TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL)""",
        """INSERT INTO sources (id, type, origin, description, created_at, updated_at)
            SELECT id, type, origin, description, created_at, updated_at FROM sources_before_21""",
        "DROP TABLE sources_before_21",
        """CREATE TRIGGER sources_never_deleted BEFORE DELETE ON sources
            BEGIN SELECT RAISE(ABORT, 'a source is never deleted'); END""",
        """CREATE TRIGGER sources_only_description_moves BEFORE UPDATE ON sources
            WHEN NEW.id IS NOT OLD.id OR NEW.type IS NOT OLD.type OR NEW.origin IS NOT OLD.origin OR NEW.created_at IS NOT OLD.created_at
            BEGIN SELECT RAISE(ABORT, 'a source keeps its id, type and origin: only its description changes'); END""",
    ]),
}

HELP_EPILOG = f"""\
database:
  --db <path> on every verb, or {PATH_ENV}. Neither: exit 3. The file is
  created by init with mode 0600; a missing folder is created 0700. WAL
  mode, busy timeout {BUSY_TIMEOUT_SECONDS} s. Every verb except init needs a database at the
  current schema version (exit 3 otherwise: run init).

verbs:
  init            create the schema or migrate it to version {SCHEMA_VERSION}; idempotent
  cursor-get      --name <n>                                  -> {{name, value|null, updated_at}}
  cursor-set      --name <n> --value <v>
  cursor-clear    --name <n>                                  -> {{name, cleared}}; the cursor
                  reads as absent again (value null); clearing an absent one is harmless
  event-add       --source <s> --external-id <id> --payload-file <json>
                  -> {{id, created}}; the same source and external id is one event
  event-next      --source <s> [--limit n] [--reclaim-after-minutes m]
                  claims up to n pending events (default 1): status claimed,
                  a claim token per event. Claims older than m minutes
                  (default {RECLAIM_DEFAULT_MINUTES}, at least {RECLAIM_MIN_MINUTES}) return to pending first;
                  an event already claimed {MAX_ATTEMPTS} times (attempts) whose claim
                  expired again ends failed with a note instead, and its id is
                  listed in "failed"   -> {{source, events, reclaimed, failed}}
  event-done      --id <id> --token <claim token> --status done|failed|to_inbox [--note <t>]
                  exit 1 when the claim was lost (reclaimed, or finished)
  run-start       --agent <a> --event-id <id|none> --trigger <t>  -> {{run_id}}
  run-end         --run-id <id> --status ok|failed|timeout --exit-code <n|null>
                  --cost-usd <x|null> --tokens <n|null> --duration-ms <n|null>
                  --out-dir <path> [--error <text>]
  runs            [--limit n] [--agent <a>]                   newest first
                  -> {{runs, truncated}}
  inbox-add       --kind <k> --title <t> --payload-file <json> --payload-sha256 <hex>
                  [--event-id <id>]                 -> {{id, created, status}}; when the
                  event already has an open item of this kind, that item is returned
                  (created false) and nothing is added
  inbox-list      [--status open|approved|rejected|done|all] (default open) [--limit n]
                  -> {{status, items, truncated}}, oldest first
                  or --id <id>: that one item in items, whatever its status
                  (items is empty when there is no such item)
  inbox-resolve   --id <id> --status approved|rejected|done --by <who> [--note <t>]
                  open -> approved|rejected|done, approved -> done; nothing else
  action-add      --kind <k> --idempotency-key <k> --target <urn> --payload-sha256 <hex>
                  --result-file <json>   -> {{id, created}}; a key is recorded once
                  --payload-sha256, here and in inbox-add, is the approval hash the caller
                  computed (of what the person approves, or of what was executed); it may
                  be the hash of another file than the payload, and it is stored as given,
                  never compared with the payload
  actions         --since <ISO-8601> [--kind <k>] [--limit n]  -> {{since, kind, actions, truncated}}
                  "truncated": true, in runs, inbox-list and actions, means more rows
                  matched than --limit (defaults: runs {LIMITS["runs"][0]}, inbox-list {LIMITS["inbox-list"][0]}, actions {LIMITS["actions"][0]})
  action-count    --kind <k> --since <ISO-8601>              -> {{kind, since, count}}
  export          --format json [--since <ISO-8601>]         every table, for review

caps (UTF-8 bytes; above a cap: exit 2, nothing stored):
  payload and result files {PAYLOAD_MAX}; notes, errors and cursor values {NOTE_MAX};
  titles {TITLE_MAX}; external ids, targets, keys {REF_MAX}; labels {LABEL_MAX}.
  Payload and result files must be UTF-8 JSON. They are stored exactly as given.

output: JSON on stdout; diagnostics on stderr. Times are UTC, ISO-8601 with Z.
  --since takes YYYY-MM-DD, optionally with THH[:MM[:SS[.fraction]]] and then an
  offset (Z, +HH, +HHMM or +HH:MM); without an offset it is local time. The same
  forms are read on every Python version; other ISO-8601 forms are refused.
  Integers are at most {INT_MAX}; a larger one is a usage error (exit 2).

exit codes: 0 success, 1 store error (database locked past the timeout, no
  such id, a lost claim, a conflicting key), 2 usage error, 3 not configured.

examples:
  python3 providers/store/sqlite.py init --db ~/agent-state/agent.sqlite
  export {PATH_ENV}=~/agent-state/agent.sqlite
  python3 providers/store/sqlite.py --check
  python3 providers/store/sqlite.py event-add --source mailbox --external-id '<id@mail>' \\
      --payload-file event.json
  python3 providers/store/sqlite.py event-next --source mailbox --limit 5
  python3 providers/store/sqlite.py action-count --kind reply --since 2026-09-29T00:00:00-03:00
"""


class StoreError(Exception):
    """An error with an exit code and a one-line message for stderr."""

    def __init__(self, message: str, code: int = EXIT_ERROR):
        super().__init__(message)
        self.code = code


def log(message: str) -> None:
    print(message, file=sys.stderr)


def emit(data) -> int:
    # ASCII escapes keep the output valid wherever stdout's encoding is not UTF-8.
    print(json.dumps(data, indent=2, ensure_ascii=True))
    return EXIT_OK


# --- time -----------------------------------------------------------------------


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime) -> str:
    """Fixed-width UTC ISO-8601, so stored times compare correctly as text."""
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


# The ISO-8601 forms --since takes: a date, optionally a time (hours, minutes, seconds, a fraction with any number
# of digits after '.' or ','), and with a time an offset (Z, +HH, +HHMM, +HH:MM). datetime.fromisoformat reads
# more of them on Python 3.11 than on 3.9, where the runtime runs, so a value is first rewritten into the one
# form both read; anything else (a week date, the basic form without separators) is refused on both.
SINCE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})(?:[Tt ](\d{2})(?::(\d{2})(?::(\d{2})(?:[.,](\d+))?)?)?"
                      r"(?:\s*(?:([Zz])|([+-])(\d{2})(?::?(\d{2}))?))?)?")


def normalise_iso(raw: str) -> str:
    match = SINCE_RE.fullmatch(raw)
    if not match:
        raise ValueError("not an ISO-8601 date or time")
    date, hour, minute, second, fraction, zulu, sign, off_hour, off_minute = match.groups()
    if hour is None:
        return date
    text = f"{date}T{hour}:{minute or '00'}:{second or '00'}"
    if fraction:
        text += "." + (fraction + "000000")[:6]
    if zulu:
        text += "+00:00"
    elif sign:
        text += f"{sign}{off_hour}:{off_minute or '00'}"
    return text


def since_arg(value: str | None, flag: str = "--since") -> str | None:
    """Parse ISO-8601; Z means UTC; a value without offset is local time."""
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(normalise_iso(value.strip()))
        if parsed.tzinfo is None:
            parsed = parsed.astimezone()
        return iso(parsed)
    except (ValueError, OverflowError):
        raise StoreError(f"{flag} is not an ISO-8601 time: {value!r}", EXIT_USAGE) from None


# --- argument checks --------------------------------------------------------------


def text_arg(value: str | None, flag: str, cap: int, multiline: bool = False, required: bool = True) -> str | None:
    if value is None:
        if required:
            raise StoreError(f"{flag} is required", EXIT_USAGE)
        return None
    if not value.strip():
        raise StoreError(f"{flag} is empty", EXIT_USAGE)
    try:
        size = len(value.encode("utf-8"))
    except UnicodeEncodeError:
        raise StoreError(f"{flag} is not valid UTF-8", EXIT_USAGE) from None
    if size > cap:
        raise StoreError(f"{flag} is {size} bytes; the cap is {cap}", EXIT_USAGE)
    if (CONTROL_MULTILINE_RE if multiline else CONTROL_RE).search(value):
        raise StoreError(f"{flag} contains a control character", EXIT_USAGE)
    return value


def sha_arg(value: str) -> str:
    digest = (value or "").strip().lower()
    if not SHA256_RE.fullmatch(digest):
        raise StoreError("--payload-sha256 must be 64 hexadecimal characters (a SHA-256 digest)", EXIT_USAGE)
    return digest


def limit_arg(value: int | None, verb: str) -> int:
    default, low, high = LIMITS[verb]
    if value is None:
        return default
    if not low <= value <= high:
        raise StoreError(f"--limit must be between {low} and {high}", EXIT_USAGE)
    return value


def id_arg(value: str, flag: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise StoreError(f"{flag} must be a positive integer", EXIT_USAGE) from None
    if not 1 <= number <= INT_MAX:
        raise StoreError(f"{flag} must be a positive integer up to {INT_MAX}", EXIT_USAGE)
    return number


def nullable_number(value: str, flag: str, kind: type) -> int | float | None:
    """A number, or the literal null (or none) when the caller does not know it."""
    if value is None:
        raise StoreError(f"{flag} is required (use null when unknown)", EXIT_USAGE)
    if value.strip().lower() in ("null", "none"):
        return None
    try:
        number = kind(value)
    except ValueError:
        raise StoreError(f"{flag} must be a number or null", EXIT_USAGE) from None
    if kind is float and not math.isfinite(number):
        raise StoreError(f"{flag} must be finite", EXIT_USAGE)
    if kind is int and not INT_MIN <= number <= INT_MAX:
        raise StoreError(f"{flag} is out of range ({INT_MIN} to {INT_MAX})", EXIT_USAGE)
    if flag != "--exit-code" and number < 0:
        raise StoreError(f"{flag} must not be negative", EXIT_USAGE)
    return number


def reject_constant(name: str):
    raise ValueError(f"{name} is not valid JSON")


def json_file(path_arg: str | None, flag: str) -> str:
    """The file's text, exactly as given, after checking it is UTF-8 JSON under the payload cap."""
    if not path_arg:
        raise StoreError(f"{flag} is required", EXIT_USAGE)
    try:
        with open(path_arg, "rb") as f:
            data = f.read(PAYLOAD_MAX + 1)
    except OSError as exc:
        raise StoreError(f"{flag}: cannot read {path_arg}: {exc.strerror}", EXIT_USAGE) from None
    if len(data) > PAYLOAD_MAX:
        raise StoreError(f"{flag}: the file is over the cap of {PAYLOAD_MAX} bytes", EXIT_USAGE)
    try:
        text = data.decode("utf-8")
        json.loads(text, parse_constant=reject_constant)
    except (UnicodeDecodeError, ValueError) as exc:
        raise StoreError(f"{flag}: not UTF-8 JSON ({exc})", EXIT_USAGE) from None
    return text


# --- database ---------------------------------------------------------------------


def db_path(args) -> Path:
    value = getattr(args, "db", None) or os.environ.get(PATH_ENV)
    if not value:
        raise StoreError(f"no database: pass --db <path> or set {PATH_ENV}", EXIT_NOT_CONFIGURED)
    text_arg(value, "--db", PATH_MAX)
    if value.strip() == ":memory:" or value.startswith("file:"):
        raise StoreError("--db must be a file path", EXIT_USAGE)
    return Path(value).expanduser().resolve()


def connect(path: Path) -> sqlite3.Connection:
    # isolation_level=None: no implicit transactions; writes open BEGIN IMMEDIATE themselves.
    conn = sqlite3.connect(str(path), timeout=BUSY_TIMEOUT_SECONDS, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 10000")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


CHANGE_COUNTER_MAX = 2 ** 31 - 1   # the header's user-version field is a signed 32-bit integer


@contextmanager
def write(conn: sqlite3.Connection):
    """One write transaction. BEGIN IMMEDIATE takes the write lock up front, so a read inside
    the transaction cannot be overtaken by another writer before its update.

    The change counter: a transaction that changed at least one row raises the number kept in the database file's
    header (`PRAGMA user_version`, which nothing else here uses), in the same transaction, so that a reader learns
    with one cheap read that something was written (change_counter). One that changed nothing, such as a
    dispatcher tick with no task ready, and one that is rolled back leave it alone. After the largest value it
    starts again at 1: a reader compares two numbers for difference only."""
    conn.execute("BEGIN IMMEDIATE")
    changes = conn.total_changes
    try:
        yield
        if conn.total_changes != changes:
            raised = change_counter(conn) + 1
            # A pragma takes no parameter; the value is an integer computed here, never text from outside.
            conn.execute(f"PRAGMA user_version = {raised if raised <= CHANGE_COUNTER_MAX else 1}")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def change_counter(conn: sqlite3.Connection) -> int:
    """The number of write transactions that changed a row, kept in the database file's header (0 for a database
    that never had one). One read of the header, no table."""
    return conn.execute("PRAGMA user_version").fetchone()[0]


def enable_wal(conn: sqlite3.Connection) -> str:
    """Switch to WAL (persistent in the file). The switch needs an exclusive lock and SQLite may
    answer "locked" at once instead of waiting, when another process is initialising the same
    file: retry until the busy timeout."""
    deadline = time.monotonic() + BUSY_TIMEOUT_SECONDS
    while True:
        try:
            return conn.execute("PRAGMA journal_mode = WAL").fetchone()[0]
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc) or time.monotonic() > deadline:
                raise
            time.sleep(0.05)


def schema_version(conn: sqlite3.Connection) -> int | None:
    found = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_version'").fetchone()
    if not found:
        return None
    return conn.execute("SELECT COALESCE(MAX(version), 0) FROM schema_version").fetchone()[0]


def private_files(path: Path) -> None:
    """The database and its WAL and shared-memory files are readable by the user only. SQLite removes
    the WAL and shared-memory files when the last connection closes, so another process may delete one
    between the listing and the chmod: a file that is gone needs no mode."""
    for candidate in (path, Path(f"{path}-wal"), Path(f"{path}-shm")):
        try:
            os.chmod(candidate, 0o600)
        except FileNotFoundError:
            pass


# The columns that a migration which was changed before it merged defines (a dev store that applied the earlier shape passes the version check and
# then fails on a raw column error): {table: columns in order}. Only a table whose migration was reworded after a store could have applied it is listed.
EXPECTED_COLUMNS = {"reminders": ("id", "text", "due_local", "due_utc", "zone", "platform", "chat", "created_by", "status", "why", "created_at",
                                  "claimed_at", "ended_at", "attempts", "retry_after")}
UNMERGED = "this store applied an unmerged migration {number} (the table {table} has other columns than this script defines); delete the test store or re-create it"


def shape_problem(conn: sqlite3.Connection) -> str | None:
    """The sentence that refuses a store whose table of EXPECTED_COLUMNS has other columns than the migration of this script defines, else None."""
    for table, columns in EXPECTED_COLUMNS.items():
        found = tuple(r[1] for r in conn.execute(f"PRAGMA table_info({table})"))
        if found and found != columns:
            return UNMERGED.format(number=20, table=table)
    return None


def missing_migrations(conn: sqlite3.Connection) -> list:
    """The numbers of MIGRATIONS that the store has not applied, ascending (all of them when it has no version table)."""
    found = conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_version'").fetchone()
    have = {r[0] for r in conn.execute("SELECT version FROM schema_version")} if found else set()
    return sorted(set(MIGRATIONS) - have)


def open_ready(args) -> sqlite3.Connection:
    """A connection to an existing database at the current schema version: the highest applied number is the script's, and none of the script's
    migrations is missing (a number below the highest that was never applied is a gap, and init fills it)."""
    path = db_path(args)
    if not path.is_file():
        raise StoreError(f"no database at {path}: run init first", EXIT_NOT_CONFIGURED)
    conn = connect(path)
    version = schema_version(conn)
    if version is None or version < SCHEMA_VERSION:
        raise StoreError(f"{path} is at schema version {version or 0}, this script needs {SCHEMA_VERSION}: "
                         "run init to migrate", EXIT_NOT_CONFIGURED)
    if version > SCHEMA_VERSION:
        raise StoreError(f"{path} is at schema version {version}, newer than this script ({SCHEMA_VERSION}): "
                         "update the workbench", EXIT_ERROR)
    problem = shape_problem(conn)
    if problem:
        raise StoreError(f"{path}: {problem}", EXIT_NOT_CONFIGURED)
    gaps = missing_migrations(conn)
    if gaps:
        raise StoreError(f"{path} has not applied migration {', '.join(map(str, gaps))} of this script: run init to migrate", EXIT_NOT_CONFIGURED)
    return conn


def event_exists(conn: sqlite3.Connection, event_id: int | None) -> None:
    if event_id is not None and not conn.execute("SELECT 1 FROM events WHERE id = ?", (event_id,)).fetchone():
        raise StoreError(f"no event {event_id}", EXIT_ERROR)


def row_dict(row: sqlite3.Row, json_fields: tuple[str, ...] = (), drop: tuple[str, ...] = ()) -> dict:
    out = {key: row[key] for key in row.keys() if key not in drop}
    for key in json_fields:
        if out.get(key) is not None:
            out[key] = json.loads(out[key])
    return out


# --- verbs ------------------------------------------------------------------------


def cmd_check(args) -> int:
    path = db_path(args)
    if not path.is_file():
        raise StoreError(f"no database at {path}: run init first", EXIT_NOT_CONFIGURED)
    conn = open_ready(args)
    quick = conn.execute("PRAGMA quick_check").fetchone()[0]
    if quick != "ok":
        raise StoreError(f"{path} failed the integrity check: {quick}", EXIT_ERROR)
    journal = conn.execute("PRAGMA journal_mode").fetchone()[0]
    file_mode = stat.S_IMODE(path.stat().st_mode)
    folder_mode = stat.S_IMODE(path.parent.stat().st_mode)
    if file_mode & 0o077:
        log(f"warning: {path} is mode {file_mode:04o}; run init or chmod 600 it")
    if folder_mode & 0o077:
        log(f"warning: {path.parent} is mode {folder_mode:04o}; others can list it (0700 recommended)")
    return emit({
        "ok": True, "db": str(path), "schema_version": SCHEMA_VERSION, "journal_mode": journal,
        "file_mode": f"{file_mode:04o}", "folder_mode": f"{folder_mode:04o}",
        "pending_events": conn.execute("SELECT COUNT(*) FROM events WHERE status = 'pending'").fetchone()[0],
        "open_inbox": conn.execute("SELECT COUNT(*) FROM inbox WHERE status = 'open'").fetchone()[0],
    })


def _init(path: Path) -> dict:
    """Create the schema or migrate it to SCHEMA_VERSION. Returns what the init verb prints."""
    # exist_ok: several inits started at once all see the folder missing; only one of them creates it.
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)  # the umask of main() makes parents 0700 too
    created = not path.exists()
    conn = connect(path)
    private_files(path)
    journal = enable_wal(conn)
    applied = []
    with write(conn):
        conn.execute("CREATE TABLE IF NOT EXISTS schema_version ("
                     "version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL, description TEXT NOT NULL)")
        current = conn.execute("SELECT COALESCE(MAX(version), 0) FROM schema_version").fetchone()[0]
        if current > SCHEMA_VERSION:
            raise StoreError(f"{path} is at schema version {current}, newer than this script ({SCHEMA_VERSION})")
        # Every number the script knows that the store lacks, ascending: not only those above the highest applied. A store that reached 20 before 19
        # was merged (two packages took neighbouring numbers) gets 19 applied now, and `open_ready` refuses it until then.
        have = {r[0] for r in conn.execute("SELECT version FROM schema_version")}
        problem = shape_problem(conn)
        if problem:
            raise StoreError(f"{path}: {problem}", EXIT_NOT_CONFIGURED)
        for version in sorted(MIGRATIONS):
            if version in have:
                continue
            description, statements = MIGRATIONS[version]
            for statement in statements:
                conn.execute(statement)
            conn.execute("INSERT INTO schema_version (version, applied_at, description) VALUES (?, ?, ?)",
                         (version, iso(utcnow()), description))
            applied.append(version)
    private_files(path)
    return {"db": str(path), "created": created, "schema_version": SCHEMA_VERSION,
            "migrated_from": current, "applied": applied, "journal_mode": journal}


def cmd_init(args) -> int:
    return emit(_init(db_path(args)))


def cmd_cursor_get(args) -> int:
    name = text_arg(args.name, "--name", LABEL_MAX)
    conn = open_ready(args)
    row = conn.execute("SELECT name, value, updated_at FROM cursors WHERE name = ?", (name,)).fetchone()
    return emit(row_dict(row) if row else {"name": name, "value": None, "updated_at": None})


def cmd_cursor_set(args) -> int:
    name = text_arg(args.name, "--name", LABEL_MAX)
    value = text_arg(args.value, "--value", VALUE_MAX)
    conn = open_ready(args)
    now = iso(utcnow())
    with write(conn):
        conn.execute("INSERT INTO cursors (name, value, updated_at) VALUES (?, ?, ?) "
                     "ON CONFLICT (name) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
                     (name, value, now))
    return emit({"name": name, "value": value, "updated_at": now})


def cmd_cursor_clear(args) -> int:
    name = text_arg(args.name, "--name", LABEL_MAX)
    conn = open_ready(args)
    with write(conn):
        cleared = conn.execute("DELETE FROM cursors WHERE name = ?", (name,)).rowcount > 0
    return emit({"name": name, "cleared": cleared})


def cmd_event_add(args) -> int:
    source = text_arg(args.source, "--source", LABEL_MAX)
    external_id = text_arg(args.external_id, "--external-id", REF_MAX)
    payload = json_file(args.payload_file, "--payload-file")
    conn = open_ready(args)
    with write(conn):
        cur = conn.execute(
            "INSERT INTO events (source, external_id, payload, created_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT (source, external_id) DO NOTHING", (source, external_id, payload, iso(utcnow())))
        created = cur.rowcount == 1
        row = conn.execute("SELECT id, status FROM events WHERE source = ? AND external_id = ?",
                           (source, external_id)).fetchone()
    return emit({"id": row["id"], "created": created, "status": row["status"]})


def cmd_event_next(args) -> int:
    source = text_arg(args.source, "--source", LABEL_MAX)
    limit = limit_arg(args.limit, "event-next")
    minutes = args.reclaim_after_minutes
    if not RECLAIM_MIN_MINUTES <= minutes <= RECLAIM_MAX_MINUTES:
        raise StoreError(f"--reclaim-after-minutes must be between {RECLAIM_MIN_MINUTES} and {RECLAIM_MAX_MINUTES}",
                         EXIT_USAGE)
    conn = open_ready(args)
    now = utcnow()
    expired = iso(now - timedelta(minutes=minutes))
    claimed = []
    with write(conn):
        failed = [r["id"] for r in conn.execute(
            "SELECT id FROM events WHERE source = ? AND status = 'claimed' AND claimed_at < ? AND attempts >= ? "
            "ORDER BY id", (source, expired, MAX_ATTEMPTS))]
        for event_id in failed:
            conn.execute("UPDATE events SET status = 'failed', claim_token = NULL, finished_at = ?, note = ? "
                         "WHERE id = ?", (iso(now), f"gave up after {MAX_ATTEMPTS} attempts: every claim expired "
                                          "without a result (the run crashed or was stopped)", event_id))
        reclaimed = conn.execute(
            "UPDATE events SET status = 'pending', claim_token = NULL, claimed_at = NULL "
            "WHERE source = ? AND status = 'claimed' AND claimed_at < ?", (source, expired)).rowcount
        ids = [r["id"] for r in conn.execute(
            "SELECT id FROM events WHERE source = ? AND status = 'pending' ORDER BY id LIMIT ?", (source, limit))]
        for event_id in ids:
            conn.execute("UPDATE events SET status = 'claimed', claim_token = ?, claimed_at = ?, "
                         "attempts = attempts + 1 WHERE id = ? AND status = 'pending'",
                         (secrets.token_hex(16), iso(now), event_id))
            row = conn.execute("SELECT id, source, external_id, payload, attempts, created_at, claimed_at, "
                               "claim_token FROM events WHERE id = ?", (event_id,)).fetchone()
            claimed.append(row_dict(row, ("payload",)))
    return emit({"source": source, "events": claimed, "reclaimed": reclaimed, "failed": failed})


def cmd_event_done(args) -> int:
    event_id = id_arg(args.id, "--id")
    token = text_arg(args.token, "--token", LABEL_MAX)
    note = text_arg(args.note, "--note", NOTE_MAX, multiline=True, required=False)
    conn = open_ready(args)
    now = iso(utcnow())
    with write(conn):
        updated = conn.execute(
            "UPDATE events SET status = ?, finished_at = ?, note = ? "
            "WHERE id = ? AND status = 'claimed' AND claim_token = ?",
            (args.status, now, note, event_id, token)).rowcount
        row = conn.execute("SELECT status, claim_token, finished_at FROM events WHERE id = ?", (event_id,)).fetchone()
    if row is None:
        raise StoreError(f"no event {event_id}")
    if not updated:
        if row["status"] == args.status and row["claim_token"] == token:
            return emit({"id": event_id, "status": row["status"], "finished_at": row["finished_at"],
                         "already": True})
        raise StoreError(f"event {event_id}: the claim was lost (status {row['status']}); it was reclaimed "
                         "after the timeout or finished with another token, so this result is not recorded")
    return emit({"id": event_id, "status": args.status, "finished_at": now, "already": False})


def cmd_run_start(args) -> int:
    agent = text_arg(args.agent, "--agent", LABEL_MAX)
    trigger = text_arg(args.trigger, "--trigger", LABEL_MAX)
    raw_event = text_arg(args.event_id, "--event-id", LABEL_MAX)
    event_id = None if raw_event.strip().lower() == "none" else id_arg(raw_event, "--event-id")
    conn = open_ready(args)
    now = iso(utcnow())
    with write(conn):
        event_exists(conn, event_id)
        run_id = conn.execute("INSERT INTO runs (agent, event_id, trigger, started_at) VALUES (?, ?, ?, ?)",
                              (agent, event_id, trigger, now)).lastrowid
    return emit({"run_id": run_id, "agent": agent, "event_id": event_id, "started_at": now})


def cmd_run_end(args) -> int:
    run_id = id_arg(args.run_id, "--run-id")
    exit_code = nullable_number(args.exit_code, "--exit-code", int)
    cost = nullable_number(args.cost_usd, "--cost-usd", float)
    tokens = nullable_number(args.tokens, "--tokens", int)
    duration = nullable_number(args.duration_ms, "--duration-ms", int)
    out_dir = text_arg(args.out_dir, "--out-dir", PATH_MAX)
    error = text_arg(args.error, "--error", NOTE_MAX, multiline=True, required=False)
    conn = open_ready(args)
    now = iso(utcnow())
    with write(conn):
        updated = conn.execute(
            "UPDATE runs SET status = ?, ended_at = ?, exit_code = ?, cost_usd = ?, tokens = ?, duration_ms = ?, "
            "out_dir = ?, error = ? WHERE id = ? AND status = 'running'",
            (args.status, now, exit_code, cost, tokens, duration, out_dir, error, run_id)).rowcount
        row = conn.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()
    if row is None:
        raise StoreError(f"no run {run_id}")
    if not updated:
        raise StoreError(f"run {run_id} already ended with status {row['status']}")
    return emit({"run_id": run_id, "status": args.status, "ended_at": now})


def cmd_runs(args) -> int:
    agent = text_arg(args.agent, "--agent", LABEL_MAX, required=False)
    limit = limit_arg(args.limit, "runs")
    conn = open_ready(args)
    rows = conn.execute("SELECT * FROM runs WHERE (? IS NULL OR agent = ?) ORDER BY id DESC LIMIT ?",
                        (agent, agent, limit + 1)).fetchall()
    return emit({"runs": [row_dict(r) for r in rows[:limit]], "truncated": len(rows) > limit})


def cmd_inbox_add(args) -> int:
    kind = text_arg(args.kind, "--kind", LABEL_MAX)
    title = text_arg(args.title, "--title", TITLE_MAX)
    payload = json_file(args.payload_file, "--payload-file")
    digest = sha_arg(args.payload_sha256)
    event_id = id_arg(args.event_id, "--event-id") if args.event_id is not None else None
    conn = open_ready(args)
    now = iso(utcnow())
    with write(conn):
        event_exists(conn, event_id)
        # One open item per event and kind: an event escalated twice keeps its first item.
        row = conn.execute("SELECT id, created_at FROM inbox WHERE event_id = ? AND kind = ? AND status = 'open' "
                           "ORDER BY id LIMIT 1", (event_id, kind)).fetchone() if event_id is not None else None
        if row is None:
            item_id = conn.execute(
                "INSERT INTO inbox (kind, title, payload, payload_sha256, event_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)", (kind, title, payload, digest, event_id, now)).lastrowid
    if row is not None:
        return emit({"id": row["id"], "status": "open", "created_at": row["created_at"], "created": False})
    return emit({"id": item_id, "status": "open", "created_at": now, "created": True})


def cmd_inbox_list(args) -> int:
    limit = limit_arg(args.limit, "inbox-list")
    if args.id is not None:
        # One item by id, whatever its status: a caller reaches an item the list's limit leaves out.
        if args.status is not None:
            raise StoreError("inbox-list takes --id or --status, not both: --id finds the item whatever its status",
                             EXIT_USAGE)
        item_id = id_arg(args.id, "--id")
        conn = open_ready(args)
        rows = conn.execute("SELECT * FROM inbox WHERE id = ?", (item_id,)).fetchall()
        return emit({"status": "all", "id": item_id, "items": [row_dict(r, ("payload",)) for r in rows],
                     "truncated": False})
    status = args.status or "open"
    conn = open_ready(args)
    rows = conn.execute("SELECT * FROM inbox WHERE (? = 'all' OR status = ?) ORDER BY id LIMIT ?",
                        (status, status, limit + 1)).fetchall()
    return emit({"status": status, "items": [row_dict(r, ("payload",)) for r in rows[:limit]],
                 "truncated": len(rows) > limit})


def cmd_inbox_resolve(args) -> int:
    item_id = id_arg(args.id, "--id")
    by = text_arg(args.by, "--by", LABEL_MAX)
    note = text_arg(args.note, "--note", NOTE_MAX, multiline=True, required=False)
    conn = open_ready(args)
    now = iso(utcnow())
    with write(conn):
        row = conn.execute("SELECT status FROM inbox WHERE id = ?", (item_id,)).fetchone()
        if row is None:
            raise StoreError(f"no inbox item {item_id}")
        current = row["status"]
        if args.status not in INBOX_TRANSITIONS.get(current, ()):
            raise StoreError(f"inbox item {item_id} is {current}; it cannot become {args.status} "
                             "(open -> approved|rejected|done, approved -> done)")
        if current == "open":
            conn.execute("UPDATE inbox SET status = ?, resolved_at = ?, resolved_by = ?, resolve_note = ? "
                         "WHERE id = ? AND status = 'open'", (args.status, now, by, note, item_id))
        if args.status == "done":
            conn.execute("UPDATE inbox SET status = 'done', done_at = ?, done_by = ?, done_note = ? WHERE id = ?",
                         (now, by, note, item_id))
    return emit({"id": item_id, "status": args.status, "previous": current, "at": now, "by": by})


def cmd_action_add(args) -> int:
    kind = text_arg(args.kind, "--kind", LABEL_MAX)
    key = text_arg(args.idempotency_key, "--idempotency-key", REF_MAX)
    target = text_arg(args.target, "--target", REF_MAX)
    digest = sha_arg(args.payload_sha256)
    result = json_file(args.result_file, "--result-file")
    return emit(_action_write(open_ready(args), kind, key, target, digest, result))


def _action_write(conn: sqlite3.Connection, kind: str, key: str, target: str, digest: str, result: str) -> dict:
    """Record one outward action, idempotent by its key: the work of the verb action-add and of action_add(), on
    checked values. Returns {"id", "created", "created_at"}."""
    with write(conn):
        created = conn.execute(
            "INSERT INTO actions (kind, idempotency_key, target, payload_sha256, result, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (idempotency_key) DO NOTHING",
            (kind, key, target, digest, result, iso(utcnow()))).rowcount == 1
        row = conn.execute("SELECT id, kind, target, payload_sha256, created_at FROM actions "
                           "WHERE idempotency_key = ?", (key,)).fetchone()
    if not created and (row["kind"], row["target"], row["payload_sha256"]) != (kind, target, digest):
        raise StoreError(f"idempotency key {key!r} is already recorded for a different action "
                         f"(action {row['id']}: {row['kind']} on {row['target']})")
    return {"id": row["id"], "created": created, "created_at": row["created_at"]}


def cmd_actions(args) -> int:
    since = since_arg(args.since)
    kind = text_arg(args.kind, "--kind", LABEL_MAX, required=False)
    limit = limit_arg(args.limit, "actions")
    conn = open_ready(args)
    rows = conn.execute("SELECT * FROM actions WHERE created_at >= ? AND (? IS NULL OR kind = ?) "
                        "ORDER BY id LIMIT ?", (since, kind, kind, limit + 1)).fetchall()
    return emit({"since": since, "kind": kind, "actions": [row_dict(r, ("result",)) for r in rows[:limit]],
                 "truncated": len(rows) > limit})


def cmd_action_count(args) -> int:
    kind = text_arg(args.kind, "--kind", LABEL_MAX)
    since = since_arg(args.since)
    return emit({"kind": kind, "since": since, "count": _action_count(open_ready(args), kind, since)})


def _action_count(conn: sqlite3.Connection, kind: str, since: str) -> int:
    """How many actions of one kind were recorded at or after since: the work of the verb action-count and of
    action_count(), on checked values."""
    return conn.execute("SELECT COUNT(*) FROM actions WHERE kind = ? AND created_at >= ?", (kind, since)).fetchone()[0]


EXPORT_QUERIES = (
    # (table, query, JSON fields, dropped fields); ? is --since, or NULL for everything.
    ("cursors", "SELECT * FROM cursors WHERE ?1 IS NULL OR updated_at >= ?1 ORDER BY name", (), ()),
    ("events", "SELECT * FROM events WHERE ?1 IS NULL OR created_at >= ?1 OR claimed_at >= ?1 "
     "OR finished_at >= ?1 ORDER BY id", ("payload",), ("claim_token",)),
    ("runs", "SELECT * FROM runs WHERE ?1 IS NULL OR started_at >= ?1 OR ended_at >= ?1 ORDER BY id", (), ()),
    ("inbox", "SELECT * FROM inbox WHERE ?1 IS NULL OR created_at >= ?1 OR resolved_at >= ?1 OR done_at >= ?1 "
     "ORDER BY id", ("payload",), ()),
    ("actions", "SELECT * FROM actions WHERE ?1 IS NULL OR created_at >= ?1 ORDER BY id", ("result",), ()),
    ("tasks", "SELECT * FROM tasks WHERE ?1 IS NULL OR created_at >= ?1 OR updated_at >= ?1 ORDER BY id",
     ("depends_on", "step_args", "step_footprint", "step_state"), ()),
    ("task_runs", "SELECT * FROM task_runs WHERE ?1 IS NULL OR started_at >= ?1 OR ended_at >= ?1 ORDER BY id",
     (), ()),
    ("pending_decisions", "SELECT * FROM pending_decisions WHERE ?1 IS NULL OR created_at >= ?1 "
     "OR resolved_at >= ?1 ORDER BY id", ("payload",), ()),
    ("document_records", "SELECT * FROM document_records WHERE ?1 IS NULL OR updated_at >= ?1 ORDER BY id", (), ()),
    ("platform_comments", "SELECT * FROM platform_comments WHERE ?1 IS NULL OR saved_at >= ?1 ORDER BY id", (), ()),
    ("approvals", "SELECT * FROM approvals WHERE ?1 IS NULL OR approved_at >= ?1 OR executed_at >= ?1 ORDER BY id",
     ("bounds",), ()),
    ("conversation_messages", "SELECT * FROM conversation_messages WHERE ?1 IS NULL OR created_at >= ?1 ORDER BY id",
     (), ()),
    ("task_waits", "SELECT * FROM task_waits WHERE ?1 IS NULL OR created_at >= ?1 OR ended_at >= ?1 ORDER BY id", (), ()),
)


def cmd_export(args) -> int:
    since = since_arg(args.since)
    conn = open_ready(args)
    out = {"exported_at": iso(utcnow()), "db": str(db_path(args)), "schema_version": SCHEMA_VERSION,
           "since": since}
    conn.execute("BEGIN")  # one read snapshot for every table
    try:
        for table, query, json_fields, drop in EXPORT_QUERIES:
            out[table] = [row_dict(r, json_fields, drop) for r in conn.execute(query, (since,))]
    finally:
        conn.execute("COMMIT")
    return emit(out)


# --- the task runtime: functions, one transaction each -------------------------------
#
# The tables of migration 2 (tasks, task_runs, pending_decisions) are read and written through the functions
# below, imported in process by runtime/ops.py. They are the contract: one call is one BEGIN IMMEDIATE
# transaction, so a step that ends a run, opens a pending decision and moves its task is all or nothing.
# None of them has a CLI verb (export reads the tables). Text a model or another person wrote (a reply, a
# question, an answer) is stored as given and never interpreted. Every function takes the connection that
# open_db() returns and raises StoreError.

TASK_STATES = ("requested", "planned", "ready", "running", "waiting", "blocked", "done", "failed", "cancelled")
TASK_FINAL_STATES = ("done", "cancelled")  # nothing leaves them; failed and blocked go back to ready (task_retry)
PENDING_KINDS = ("plan", "question", "review", "effect", "acceptance", "your_document")
PENDING_STATUSES = ("open", "resolved", "cancelled")
RUN_FAILURES = ("timeout", "refused", "auth", "adapter", "early_end", "settings", "stopped", "internal")
RUN_ENDINGS = ("done", "question", "draft_with_questions", "gate", "blocked", "unclassified")
RUN_BILLINGS = ("subscription", "metered", "free", "unknown")
RUN_AUTONOMIES = ("proven", "consent", "supervised")
AUTO = "auto"  # the model word of "choose by the evidence and the price" (runtime/proof.py)


def _autonomy_arg(value):
    """How a run's pair was released: None, or one of RUN_AUTONOMIES (migration 10 checks the column the same way)."""
    if value is not None and value not in RUN_AUTONOMIES:
        raise StoreError(f"autonomy must be one of {', '.join(RUN_AUTONOMIES)}", EXIT_USAGE)
    return value


def _model_arg(value):
    """The model a request or a task carries: None, `auto`, or a model id (text, up to REF_MAX)."""
    return text_arg(value, "model", REF_MAX, required=False)


LANGUAGE_RE = re.compile(r"[a-z]{2}(?:-[A-Z]{2})?")   # the rule of runtime/language.py (a test holds the two equal); migration 16 checks the column the same way


def _language_arg(value):
    """The language a request or a task carries: None (not requested), or a tag of two lower-case letters and, optionally, a hyphen and
    two upper-case letters."""
    value = text_arg(value, "language", LABEL_MAX, required=False)
    if value is not None and not LANGUAGE_RE.fullmatch(value):
        raise StoreError("language must be a language tag such as en or pt-BR", EXIT_USAGE)
    return value


SOURCE_ID_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")
SOURCE_TYPES = ("file", "notion", "drive", "onedrive", "mail", "calendar")   # the CHECK of the sources table (migration 21) admits the same words
SOURCE_LABELS = ("import", "refresh", "changed-by-person")
SOURCE_BYS = ("runtime", "person")


def _sources_arg(value):
    """The source ids a plan chose for a task: None or an empty list (stored as NULL), else a list of distinct ids (lowercase
    letters, digits and hyphens, at most 40 characters, at most 20), kept in the order given."""
    if value is None or value == []:
        return []
    if not isinstance(value, list) or len(value) > 20 or len(set(value)) != len(value) \
            or not all(isinstance(v, str) and SOURCE_ID_RE.fullmatch(v) for v in value):
        raise StoreError("a task's sources are a list of at most 20 distinct source ids", EXIT_USAGE)
    return list(value)


# The columns of a task row that hold JSON text: row_dict reads them back as objects.
TASK_JSON = ("depends_on", "sources", "step_args", "step_footprint", "step_state")

# --- the step task (P5) ------------------------------------------------------------------------------------------------
#
# A step task is a task of a request that runs no skill: code runs it, in a process of its own, as the engine of
# runtime/steps.py. Its kind (`step_kind`) is a word of that engine's registry; the store checks its shape, never whether the
# kind exists (the registry is the runtime's). It is planned, ready and done under `depends_on` as a skill task is: _refresh
# makes it `ready` when every task it depends on is done, and NEXT_READY_TASK and task_claim give it out like any ready task of
# a request (neither asks for a skill; before P5 no task without a skill existed). It has no run row: the engine records its
# steps in `step_state`, and its states move through step_task_move. Its owner is the runtime's pseudo-agent, STEP_OWNER.
STEP_OWNER = "runtime"
STEP_KIND_RE = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")
STEP_KIND_MAX = 40
STEP_ARGS_MAX = 16 * 1024          # bytes of a step's arguments as canonical JSON
STEP_FOOTPRINT_MAX = 20            # paths a kind may declare for one task
STEP_STATE_MAX = 64 * 1024         # bytes of the engine's progress
STEP_STATES = ("running", "waiting", "failed", "done")
FOOTPRINT_PATH_RE = re.compile(r"[A-Za-z0-9._<>-]+(/[A-Za-z0-9._<>-]*)*")


def canonical_json(value) -> str:
    """A value as the JSON text the plan hash and the store agree on: sorted keys, no spaces, ASCII, no NaN."""
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise StoreError(f"not JSON ({exc})", EXIT_USAGE) from None


def is_step_task(task: dict) -> bool:
    """Whether a task row is a step task: it has a parent request, a step kind and no skill."""
    return task.get("parent_id") is not None and task.get("step_kind") is not None and task.get("skill") is None


def _step_kind_arg(value) -> str:
    kind = text_arg(value, "step", STEP_KIND_MAX)
    if not STEP_KIND_RE.fullmatch(kind):
        raise StoreError(f"step kind {kind!r} must be lowercase words joined by hyphens", EXIT_USAGE)
    return kind


def _step_args_arg(value) -> str:
    """A step's arguments (an object) as canonical JSON text, at most STEP_ARGS_MAX bytes."""
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise StoreError("a step's arguments are an object", EXIT_USAGE)
    text = canonical_json(value)
    if len(text.encode("utf-8")) > STEP_ARGS_MAX:
        raise StoreError(f"a step's arguments are over the cap of {STEP_ARGS_MAX} bytes", EXIT_USAGE)
    return text


def _step_footprint_arg(value) -> str:
    """The paths a kind declares it writes, as a JSON list: relative paths inside the project (a declared path may carry
    placeholders such as <task>), at most STEP_FOOTPRINT_MAX, once each."""
    paths = [] if value is None else value
    if not isinstance(paths, (list, tuple)) or len(paths) > STEP_FOOTPRINT_MAX or len(set(paths)) != len(paths):
        raise StoreError(f"a step's footprint is a list of at most {STEP_FOOTPRINT_MAX} distinct paths", EXIT_USAGE)
    for path in paths:
        if not isinstance(path, str) or not FOOTPRINT_PATH_RE.fullmatch(path) or path.startswith("/") or \
                any(part in (".", "..") for part in path.split("/")) or len(path) > PATH_MAX:
            raise StoreError(f"footprint path {path!r} must be a relative path inside the project", EXIT_USAGE)
    return canonical_json(sorted(paths))


def _step_state_arg(value) -> str:
    text = canonical_json(value)
    if len(text.encode("utf-8")) > STEP_STATE_MAX:
        raise StoreError(f"a step's state is over the cap of {STEP_STATE_MAX} bytes", EXIT_USAGE)
    return text


def _billing_arg(value):
    """The billing a run is started with: None, or one of RUN_BILLINGS (migration 9 checks the column the same way)."""
    if value is not None and value not in RUN_BILLINGS:
        raise StoreError(f"billing must be one of {', '.join(RUN_BILLINGS)}", EXIT_USAGE)
    return value
# What a resolution does to the task that waited: the resolutions of later kinds are added with their stage.
RESOLUTIONS = {"answered": "ready", "released": "done"}
RELEASABLE_KINDS = ("review",)
# The resolutions of an effect that pending_resolve writes: the comment sends the task back, a rejection cancels it.
# Its approval is effect_done's alone ("approved", after code executed the effect: the task is done).
EFFECT_RESOLUTIONS = {"answered": "ready", "rejected": "cancelled"}
APPROVAL_SCOPES = ("action", "plan", "standing")
APPROVAL_STATUSES = ("pending-execution", "executed", "active", "expired", "revoked")
# Limit L13: a status only moves forward, along these pairs; no approval is ever deleted.
APPROVAL_MOVES = {"pending-execution": ("executed", "revoked"), "active": ("expired", "revoked")}
# The resolutions of a plan and of an acceptance, by kind and word, with the state the request is left in. Only
# plan_approve, plan_reject and acceptance_resolve write them: each does more than move a state.
KIND_RESOLUTIONS = {("plan", "approved"): "planned", ("plan", "rejected"): "cancelled",
                    ("acceptance", "accepted"): "requested", ("acceptance", "rejected"): "cancelled"}
KEY_RE = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")
# A task with an open wait (task_waits) is never given out, whatever its state says: the store refuses, not the caller.
OPEN_WAIT = "EXISTS (SELECT 1 FROM task_waits w WHERE w.task_id = tasks.id AND w.status = 'open')"
# The oldest ready task (never a request) with no open wait: what a caller that picks one asks, then claims by its id
# (task_claim).
NEXT_READY_TASK = ("SELECT id FROM tasks WHERE state = 'ready' AND parent_id IS NOT NULL AND NOT " + OPEN_WAIT +
                   " ORDER BY id LIMIT 1")
WAIT_KINDS = ("input", "after")
WAIT_STATUSES = ("open", "cleared", "dropped")
DOCUMENT_FIELDS = ("remote_id", "written_sha256", "remote_version", "read_sha256", "status", "note")
DOCUMENT_UPDATES = {
    "remote_id": "UPDATE document_records SET remote_id = ? WHERE path = ?",
    "written_sha256": "UPDATE document_records SET written_sha256 = ? WHERE path = ?",
    "remote_version": "UPDATE document_records SET remote_version = ? WHERE path = ?",
    "read_sha256": "UPDATE document_records SET read_sha256 = ? WHERE path = ?",
    "status": "UPDATE document_records SET status = ? WHERE path = ?",
    "note": "UPDATE document_records SET note = ? WHERE path = ?",
}
DOCUMENT_STATUSES = ("mirrored", "read_only", "rejected")
COMMENT_SUBJECTS = ("task", "document")
COMMENT_STATUSES = ("open", "used", "dismissed")
ACCEPTANCE_WHATS = ("subtasks", "deliveries")  # payload["what"] of an acceptance a stage-6 operation opens
REROUTE_STATES = ("planned", "done")  # a request one of whose deliveries is routed again after its brief (stage 6)


def open_db(path) -> sqlite3.Connection:
    """A connection to an existing database at the current schema version: what every function below takes."""
    return open_ready(argparse.Namespace(db=str(path)))


def init_db(path) -> dict:
    """Create the schema or migrate it, as the init verb does, without printing. Returns what init prints.
    The database and a new folder are private to the user, as in main(); the caller's umask is put back."""
    previous = os.umask(0o077)
    try:
        return _init(db_path(argparse.Namespace(db=str(path))))
    finally:
        os.umask(previous)


def _task(conn: sqlite3.Connection, task_id: int) -> dict:
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if row is None:
        raise StoreError(f"no task {task_id}")
    return row_dict(row, TASK_JSON)


def _refresh(conn: sqlite3.Connection, now: str) -> tuple[list, list]:
    """Inside a transaction: a request whose tasks are all done becomes done, a wait ends (cleared) when its
    awaited row is done or cancelled, or when the task that waited is (a cancelled task waits for nothing), a planned task whose dependencies are all done and that has no open wait becomes ready.
    Returns (ids made ready, ids of the requests completed)."""
    ready, completed = [], []
    for row in conn.execute("SELECT id FROM tasks WHERE state = 'planned' AND parent_id IS NULL ORDER BY id").fetchall():
        states = [r["state"] for r in conn.execute("SELECT state FROM tasks WHERE parent_id = ?", (row["id"],))]
        if states and all(state == "done" for state in states):
            conn.execute("UPDATE tasks SET state = 'done', updated_at = ? WHERE id = ?", (now, row["id"]))
            completed.append(row["id"])
    conn.execute("UPDATE task_waits SET status = 'cleared', ended_at = ?, ended_by = 'runtime' WHERE status = 'open' "
                 "AND (awaited_id IN (SELECT id FROM tasks WHERE state IN ('done', 'cancelled')) "
                 "OR task_id IN (SELECT id FROM tasks WHERE state IN ('done', 'cancelled')))", (now,))
    for row in conn.execute("SELECT id, depends_on FROM tasks WHERE state = 'planned' AND parent_id IS NOT NULL "
                            "AND NOT " + OPEN_WAIT + " ORDER BY id").fetchall():
        needed = json.loads(row["depends_on"])
        done = sum(1 for dep in needed if conn.execute("SELECT 1 FROM tasks WHERE id = ? AND state = 'done'",
                                                         (dep,)).fetchone())
        if done == len(needed):
            conn.execute("UPDATE tasks SET state = 'ready', updated_at = ? WHERE id = ?", (now, row["id"]))
            ready.append(row["id"])
    return ready, completed


def request_add(conn: sqlite3.Connection, *, title: str, text: str, flow: str | None = None,
                tasks: list | None = None, after: int | None = None, waits: list | None = None,
                model: str | None = None, language: str | None = None) -> dict:
    """Record a request and, when its plan is given, the tasks of the plan, in one transaction.

    Without tasks the request stays `requested` (the router has not answered yet). With tasks, a list of
    {"key", "skill", "title", "text", "depends_on": [keys], "milestone": bool} in the flow file's order, the
    request becomes `planned`, every task is added `planned`, and the tasks with no dependency and no open wait
    become `ready`. A dependency names the key of a task earlier in the list, so the plan has no cycle.
    after is the request this one waits for (the person's override, kept on the request); waits are the waits the
    plan's tasks begin with, as _insert_waits reads them, so that no task is ever ready for a moment before its wait
    exists. model is the model id (or `auto`) the person chose for the request, None when none was chosen. language is the tag
    the person asked the deliverable in, None when not requested (the tasks of a plan carry their own, `language` of each item).
    Returns {"request": id, "state", "tasks": [{"id", "key", "skill", "state"}]}."""
    model = _model_arg(model)
    language = _language_arg(language)
    title = text_arg(title, "title", TITLE_MAX)
    text = text_arg(text, "text", TEXT_MAX, multiline=True)
    flow = text_arg(flow, "flow", LABEL_MAX, required=False)
    plan = _plan_items(tasks or [])
    if plan and not flow:
        raise StoreError("a plan names its flow", EXIT_USAGE)
    now = iso(utcnow())
    with write(conn):
        return _request_in(conn, title, text, flow, plan, after, waits, model, now, language)


def _request_in(conn: sqlite3.Connection, title: str, text: str, flow, plan: list, after, waits, model, now: str,
                language=None) -> dict:
    """Inside a write transaction: the request and its checked plan, as request_add makes them (a routine's fire makes its request
    in the transaction that writes the fire's row)."""
    after = _check_after(conn, None, after)
    request_id = conn.execute(
        "INSERT INTO tasks (flow, title, text, state, after_request, model, language, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (flow, title, text, "planned" if plan else "requested", after, model, language, now,
                                               now)).lastrowid
    ids = _insert_plan(conn, request_id, flow, plan, now)
    _insert_waits(conn, request_id, dict(zip([p["key"] for p in plan], ids)), waits or [], now)
    _refresh(conn, now)
    rows = conn.execute("SELECT id, key, skill, state FROM tasks WHERE parent_id = ? ORDER BY id",
                        (request_id,)).fetchall()
    state = conn.execute("SELECT state FROM tasks WHERE id = ?", (request_id,)).fetchone()["state"]
    return {"request": request_id, "state": state, "tasks": [row_dict(r) for r in rows]}


def _check_after(conn: sqlite3.Connection, request_id: int | None, after) -> int | None:
    """Inside a transaction: after is None, or the id of a request other than request_id (a task is not one)."""
    if after is None:
        return None
    if isinstance(after, bool) or not isinstance(after, int):
        raise StoreError("after is the id of a request", EXIT_USAGE)
    row = conn.execute("SELECT parent_id FROM tasks WHERE id = ?", (after,)).fetchone()
    if row is None or row["parent_id"] is not None:
        raise StoreError(f"after names {after}, which is not a request of this project", EXIT_USAGE)
    if after == request_id:
        raise StoreError("a request does not wait for itself", EXIT_USAGE)
    return after


def _insert_waits(conn: sqlite3.Connection, request_id: int, ids: dict, waits: list, now: str,
                  go_ahead=()) -> None:
    """Inside a transaction: the waits a plan's tasks begin with. ids maps the plan's keys to their task ids; a wait is
    {"key", "kind": input|after, "awaited_id", "path", "reason"}, the awaited row an existing task (input) or request
    (after) of another request. A key in go_ahead is the person's decision about the waits shown for it: its input waits
    are written as already dropped (they are not derived again; a new writer or path is another wait). A key with no
    input wait to drop is refused."""
    for key in go_ahead:
        if key not in ids:
            raise StoreError(f"go ahead names {key!r}, which is not a task of the plan", EXIT_USAGE)
        if not any(w.get("key") == key and w.get("kind") == "input" for w in waits):
            raise StoreError(f"go ahead names {key!r}, which waits for no task to derive", EXIT_USAGE)
    for wait in waits:
        key = wait.get("key")
        if key not in ids:
            raise StoreError("a wait names a task of the plan and is an input or an after", EXIT_USAGE)
        _insert_one_wait(conn, ids[key], request_id, set(ids.values()), wait, now,
                         dropped=wait.get("kind") == "input" and key in go_ahead)


def _insert_one_wait(conn: sqlite3.Connection, task_id: int, request_id: int, own: set, wait: dict, now: str,
                     dropped: bool = False) -> None:
    """Inside a transaction: one wait of a task, {"kind": input|after, "awaited_id", "path", "reason"}, the awaited row a
    task (input) or a request (after) outside the task's own request and outside `own`."""
    kind = wait.get("kind")
    if kind not in ("input", "after"):
        raise StoreError("a wait is an input or an after", EXIT_USAGE)
    awaited = conn.execute("SELECT id, parent_id FROM tasks WHERE id = ?", (wait.get("awaited_id"),)).fetchone()
    if awaited is None or awaited["id"] in own or (awaited["parent_id"] or awaited["id"]) == request_id \
            or (kind == "after") != (awaited["parent_id"] is None):
        raise StoreError(f"task {task_id}: a wait names a task, or for after a request, of another request", EXIT_USAGE)
    path = _rel_path(wait["path"]) if kind == "input" else None
    reason = text_arg(wait.get("reason"), "reason", NOTE_MAX)
    conn.execute("INSERT INTO task_waits (task_id, awaited_id, kind, path, reason, status, created_at, ended_at, "
                 "ended_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                 (task_id, awaited["id"], kind, path, reason, "dropped" if dropped else "open", now,
                  now if dropped else None, "user" if dropped else None))


def _plan_items(tasks, *, empty_text: bool = False, known=()) -> list:
    """The tasks of a plan, checked: a list of {"key", "skill", "title", "text", "depends_on": [keys], "milestone"
    [, "agent"]}, each dependency the key of a task earlier in the list or one of known (the keys a request already
    has, for tasks_add). empty_text allows a task with no text of its own (a plan of one skill, whose prompt is the
    plain request), stored as "". agent, when given, is the area agent that owns the task (stage 6)."""
    if not isinstance(tasks, list):
        raise StoreError("a plan's tasks are a list", EXIT_USAGE)
    plan = []
    for item in tasks:
        if not isinstance(item, dict):
            raise StoreError("a task of a plan is an object", EXIT_USAGE)
        key = text_arg(item.get("key"), "key", LABEL_MAX)
        if not KEY_RE.fullmatch(key) or key in [p["key"] for p in plan] or key in known:
            raise StoreError(f"task key {key!r} must be lowercase words joined by hyphens, once per plan", EXIT_USAGE)
        depends = item.get("depends_on") or []
        if not isinstance(depends, list) or any(d not in [p["key"] for p in plan] and d not in known for d in depends):
            raise StoreError(f"task {key!r}: depends_on names the keys of tasks earlier in the plan", EXIT_USAGE)
        text = item.get("text")
        if empty_text and isinstance(text, str) and not text.strip():
            text = ""
        else:
            text = text_arg(text, "text", TEXT_MAX, multiline=True)
        agent = text_arg(item.get("agent"), "agent", LABEL_MAX, required=False)
        step = {"step_kind": None, "step_args": None, "step_footprint": None}
        if item.get("step") is not None:     # a step task: a kind, its arguments and the footprint the kind declared
            if item.get("skill") is not None or item.get("sources"):
                raise StoreError(f"task {key!r}: a step task has no skill and receives no sources", EXIT_USAGE)
            if agent not in (None, STEP_OWNER):
                raise StoreError(f"task {key!r}: a step task belongs to the agent {STEP_OWNER!r}", EXIT_USAGE)
            if item.get("web_off"):
                raise StoreError(f"task {key!r}: a step task has no web to switch off", EXIT_USAGE)
            agent, skill = STEP_OWNER, None
            step = {"step_kind": _step_kind_arg(item["step"]), "step_args": _step_args_arg(item.get("args")),
                    "step_footprint": _step_footprint_arg(item.get("footprint"))}
        else:
            skill = text_arg(item.get("skill"), "skill", LABEL_MAX)
        plan.append({"key": key, "skill": skill,
                     "title": text_arg(item.get("title"), "title", TITLE_MAX), "text": text,
                     "depends_on": list(depends), "milestone": 1 if item.get("milestone") else 0,
                     "agent": agent, "model": _model_arg(item.get("model")), "language": _language_arg(item.get("language")),
                     "sources": _sources_arg(item.get("sources")),
                     "web_off": 1 if item.get("web_off") else None, **step})
    return plan


def _insert_plan(conn: sqlite3.Connection, request_id: int, flow: str | None, plan: list, now: str,
                 known: dict | None = None) -> list:
    """Inside a transaction: add the checked tasks of a plan under a request, every one `planned`. known maps the keys
    of the request's existing tasks to their ids (tasks_add). Returns the new ids, in order."""
    ids = dict(known or {})
    added = []
    for item in plan:
        ids[item["key"]] = conn.execute(
            "INSERT INTO tasks (parent_id, flow, key, skill, agent, title, text, state, depends_on, milestone, "
            "model, language, sources, step_kind, step_args, step_footprint, web_off, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'planned', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (request_id, flow, item["key"], item["skill"], item["agent"], item["title"], item["text"],
             json.dumps([ids[d] for d in item["depends_on"]]), item["milestone"], item.get("model"), item.get("language"),
             json.dumps(item["sources"]) if item["sources"] else None, item.get("step_kind"), item.get("step_args"),
             item.get("step_footprint"), item["web_off"], now, now)).lastrowid
        added.append(ids[item["key"]])
    return added


def task_run_start(conn: sqlite3.Connection, task_id: int, *, skill: str, model: str, adapter: str,
                   skill_version: str | None = None, skill_sha256: str | None = None, web: bool = False,
                   billing: str | None = None, autonomy: str | None = None) -> dict:
    """Record the start of a run of a task that is `running`. billing is how the credential the run uses is billed
    (RUN_BILLINGS; None when the runtime cannot tell): the daily caps count by it. autonomy is how the run's pair was
    released (RUN_AUTONOMIES; None when it is not recorded). Returns {"run_id", "task_id", "started_at"}."""
    billing = _billing_arg(billing)
    autonomy = _autonomy_arg(autonomy)
    skill = text_arg(skill, "skill", LABEL_MAX)
    model = text_arg(model, "model", REF_MAX)
    adapter = text_arg(adapter, "adapter", LABEL_MAX)
    skill_version = text_arg(skill_version, "skill_version", LABEL_MAX, required=False)
    if skill_sha256 is not None and not SHA256_RE.fullmatch(skill_sha256):
        raise StoreError("skill_sha256 must be 64 hexadecimal characters", EXIT_USAGE)
    now = iso(utcnow())
    with write(conn):
        if _task(conn, task_id)["state"] != "running":
            raise StoreError(f"task {task_id} is not running: a run starts on a task that task_claim gave out")
        run_id = conn.execute(
            "INSERT INTO task_runs (task_id, skill, skill_version, skill_sha256, model, adapter, web, started_at, billing, "
            "autonomy) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (task_id, skill, skill_version, skill_sha256, model, adapter, 1 if web else 0, now, billing, autonomy)).lastrowid
    return {"run_id": run_id, "task_id": task_id, "started_at": now}


def task_run_finish(conn: sqlite3.Connection, run_id: int, *, status: str, task_state: str,
                    failure: str | None = None, ending: str | None = None, attempts: int = 0,
                    cost_usd: float | None = None, tokens: int | None = None, duration_ms: int | None = None,
                    skill_loaded: bool | None = None, image_digest: str | None = None, run_dir: str | None = None,
                    error: str | None = None, task_note: str | None = None, pending: dict | None = None,
                    redactions: int | None = None) -> dict:
    """End a run and move its task, in one transaction; with `pending`, also open the pending decision the task
    then waits on. redactions is the number of passed values the lab replaced in what the run left, None when
    the lab did not report it. task_state is `waiting` (pending is required: a waiting task always points to a pending
    decision), `failed` or `blocked` (pending is refused). pending is {"kind", "title", "body"[, "payload":
    object][, "payload_sha256"]}. When the task or its request has a stop request (request_stop, task_stop) the run is
    recorded `cancelled` instead, with what it reported, no pending decision is opened, and the task ends as the stop says
    (R18, limit L41). Returns {"run_id", "task_id", "task_state", "pending_id" or None, "cancelled"}."""
    if status not in ("ok", "failed") or (status == "failed") != (failure is not None):
        raise StoreError("status is ok, or failed with the kind of failure", EXIT_USAGE)
    if failure is not None and failure not in RUN_FAILURES:
        raise StoreError(f"failure must be one of {', '.join(RUN_FAILURES)}", EXIT_USAGE)
    if ending is not None and ending not in RUN_ENDINGS:
        raise StoreError(f"ending must be one of {', '.join(RUN_ENDINGS)}", EXIT_USAGE)
    if task_state not in ("waiting", "failed", "blocked") or (task_state == "waiting") != (pending is not None):
        raise StoreError("task_state is waiting with a pending decision, or failed or blocked without one", EXIT_USAGE)
    error = text_arg(error, "error", NOTE_MAX, multiline=True, required=False)
    task_note = text_arg(task_note, "task_note", NOTE_MAX, multiline=True, required=False)
    run_dir = text_arg(run_dir, "run_dir", PATH_MAX, required=False)
    image_digest = text_arg(image_digest, "image_digest", REF_MAX, required=False)
    item = None if pending is None else _pending_item(pending)
    loaded = None if skill_loaded is None else (1 if skill_loaded else 0)
    if redactions is not None and (isinstance(redactions, bool) or not isinstance(redactions, int) or redactions < 0):
        raise StoreError("redactions is a count: a whole number, 0 or more", EXIT_USAGE)
    now = iso(utcnow())
    with write(conn):
        row = conn.execute("SELECT task_id, status FROM task_runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            raise StoreError(f"no task run {run_id}")
        if row["status"] != "running":
            raise StoreError(f"task run {run_id} already ended with status {row['status']}")
        task_id = row["task_id"]
        stop = stop_of(conn, task_id)
        if stop is not None:   # a stopped run returns nothing and opens nothing: it is recorded cancelled, whatever it found
            _end_stopped_run(conn, run_id, stop, now, {
                "attempts": int(attempts), "cost_usd": cost_usd, "tokens": tokens, "duration_ms": duration_ms,
                "skill_loaded": loaded, "image_digest": image_digest, "run_dir": run_dir, "redactions": redactions})
            return {"run_id": run_id, "task_id": task_id, "task_state": _settle_stopped_task(conn, task_id, stop, now),
                    "pending_id": None, "cancelled": True}
        conn.execute(
            "UPDATE task_runs SET status = ?, failure = ?, ending = ?, attempts = ?, ended_at = ?, cost_usd = ?, "
            "tokens = ?, duration_ms = ?, skill_loaded = ?, image_digest = ?, run_dir = ?, error = ?, redactions = ? "
            "WHERE id = ?",
            (status, failure, ending, int(attempts), now, cost_usd, tokens, duration_ms, loaded, image_digest,
             run_dir, error, redactions, run_id))
        moved = conn.execute("UPDATE tasks SET state = ?, note = ?, updated_at = ? WHERE id = ? AND state = 'running'",
                             (task_state, task_note, now, task_id)).rowcount
        if not moved:
            raise StoreError(f"task {task_id} is not running: the run's result is not recorded")
        pending_id = None
        if item is not None:
            pending_id = conn.execute(
                "INSERT INTO pending_decisions (task_id, run_id, kind, title, body, payload, payload_sha256, "
                "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (task_id, run_id, *item, now)).lastrowid
    return {"run_id": run_id, "task_id": task_id, "task_state": task_state, "pending_id": pending_id, "cancelled": False}


def _pending_item(pending: dict) -> tuple:
    """A pending decision to insert, checked: (kind, title, body, payload as JSON, payload_sha256)."""
    if not isinstance(pending, dict) or pending.get("kind") not in PENDING_KINDS:
        raise StoreError(f"a pending decision's kind is one of {', '.join(PENDING_KINDS)}", EXIT_USAGE)
    digest = pending.get("payload_sha256")
    if digest is not None and not SHA256_RE.fullmatch(digest):
        raise StoreError("payload_sha256 must be 64 hexadecimal characters", EXIT_USAGE)
    body = pending.get("body")
    if not isinstance(body, str) or len(body.encode("utf-8")) > BODY_MAX:
        raise StoreError(f"a pending decision's body is text of at most {BODY_MAX} bytes", EXIT_USAGE)
    payload = pending.get("payload") or {}
    if not isinstance(payload, dict):
        raise StoreError("a pending decision's payload is an object", EXIT_USAGE)
    return (pending["kind"], text_arg(pending.get("title"), "title", TITLE_MAX), body,
            json.dumps(payload, ensure_ascii=True, sort_keys=True), digest)


def pending_resolve(conn: sqlite3.Connection, pending_id: int, *, resolution: str, by: str,
                    answer: str | None = None, actor: str | None = None) -> dict:
    """Record the person's decision on an open pending decision and move the task that waited, in one
    transaction. `answered` (with the answer's text) makes the task ready again: its next run gets the answer.
    `released` (a review only) makes it done; then the tasks that depended on it become ready, and a request
    whose tasks are all done becomes done. A `plan` or an `acceptance` is never resolved here (plan_approve,
    plan_reject, acceptance_resolve). A question asked on a request (by the router, before any task exists) is
    only answered, and the request stays `requested`: a request is never given out to run. An `effect` is
    `answered` (the task is ready again, its next run gets the comment) or `rejected` (the task is cancelled); both
    revoke a `pending-execution` approval of it in the same transaction; it is approved through effect_done only.
    `actor` (POL-2) is who acted, kept beside `by`: see migration 17.
    Returns {"pending_id", "task_id", "task_state", "ready": [ids], "completed": [request ids]}."""
    if resolution not in RESOLUTIONS and resolution not in EFFECT_RESOLUTIONS:
        raise StoreError(f"resolution must be one of {', '.join(sorted({*RESOLUTIONS, *EFFECT_RESOLUTIONS}))}",
                         EXIT_USAGE)
    by = text_arg(by, "by", LABEL_MAX)
    actor = text_arg(actor, "actor", ACTOR_MAX, required=False)
    answer = text_arg(answer, "answer", TEXT_MAX, multiline=True, required=resolution == "answered")
    now = iso(utcnow())
    with write(conn):
        row = conn.execute("SELECT task_id, kind, status FROM pending_decisions WHERE id = ?", (pending_id,)).fetchone()
        if row is None:
            raise StoreError(f"no pending decision {pending_id}")
        if row["status"] != "open":
            raise StoreError(f"pending decision {pending_id} is {row['status']}, not open")
        if row["kind"] in {kind for kind, _ in KIND_RESOLUTIONS}:
            raise StoreError(f"pending decision {pending_id} is a {row['kind']}: it is approved or rejected, "
                             "not answered or released")
        if row["kind"] == "effect":
            if resolution not in EFFECT_RESOLUTIONS:
                raise StoreError(f"pending decision {pending_id} is an effect: it is answered or rejected here, and "
                                 "approved only through effect_done, after code executed it")
        elif resolution not in RESOLUTIONS:
            raise StoreError(f"pending decision {pending_id} is a {row['kind']}: only an effect is rejected here")
        if resolution == "released" and row["kind"] not in RELEASABLE_KINDS:
            raise StoreError(f"pending decision {pending_id} is a {row['kind']}: it is answered, not released")
        task = _task(conn, row["task_id"])
        if task["parent_id"] is None:
            if resolution != "answered" or task["state"] != "requested":
                raise StoreError(f"pending decision {pending_id} is on request {task['id']} ({task['state']}): "
                                 "it is only answered, while the request waits for its plan")
            conn.execute("UPDATE pending_decisions SET status = 'resolved', resolution = ?, answer = ?, "
                         "resolved_at = ?, resolved_by = ?, actor = ? WHERE id = ?", (resolution, answer, now, by, actor, pending_id))
            return {"pending_id": pending_id, "task_id": task["id"], "task_state": "requested", "ready": [],
                    "completed": []}
        conn.execute("UPDATE pending_decisions SET status = 'resolved', resolution = ?, answer = ?, resolved_at = ?, "
                     "resolved_by = ?, actor = ? WHERE id = ?", (resolution, answer, now, by, actor, pending_id))
        state = (EFFECT_RESOLUTIONS if row["kind"] == "effect" else RESOLUTIONS)[resolution]
        moved = conn.execute("UPDATE tasks SET state = ?, updated_at = ? WHERE id = ? AND state = 'waiting'",
                             (state, now, row["task_id"])).rowcount
        if not moved:
            raise StoreError(f"task {row['task_id']} is not waiting: the decision is not recorded")
        _revoke_pending_execution(conn, pending_id, now)
        ready, completed = _refresh(conn, now)
    return {"pending_id": pending_id, "task_id": row["task_id"], "task_state": state, "ready": ready,
            "completed": completed}


def task_retry(conn: sqlite3.Connection, task_id: int, waits: list | None = None) -> dict:
    """Make a failed or blocked task ready again, or, when the runtime derived waits for it (each {"kind", "awaited_id",
    "path", "reason"}), planned with those waits, in the same transaction. Returns {"task_id", "state", "previous"}."""
    now = iso(utcnow())
    with write(conn):
        task = _task(conn, task_id)
        previous = task["state"]
        if previous not in ("failed", "blocked"):
            raise StoreError(f"task {task_id} is {previous}: only a failed or a blocked task is retried")
        if task["parent_id"] is not None and stop_of(conn, task["parent_id"]) is not None:
            raise StoreError(f"request {task['parent_id']} is being cancelled: its tasks are not retried")
        state = "planned" if waits else "ready"
        conn.execute("UPDATE tasks SET state = ?, note = NULL, stop_requested_at = NULL, stop_requested_by = NULL, "
                     "updated_at = ? WHERE id = ?", (state, now, task_id))   # a task stopped on its own is retried: the stop ends
        for wait in waits or []:
            _insert_one_wait(conn, task_id, task["parent_id"], {task_id}, wait, now)
    return {"task_id": task_id, "state": state, "previous": previous}


def task_fail_orphans(conn: sqlite3.Connection, task_ids, run_ids, note: str, usage: dict | None = None) -> dict:
    """End what dead processes left. The caller holds the lock of each task it names, so no live process can claim it
    meanwhile, and found that no process held it. Each task of task_ids still `running` becomes `failed` with the
    note and every run row of it still `running` ends `failed` (failure `stopped`); each run of run_ids still
    `running` ends the same way. What is not running is skipped silently. What has a stop request (request_stop,
    task_stop) is not failed but ended as the stop says: its runs `cancelled`, its task `cancelled` or `blocked`
    (usage maps a run id to what it reported: tokens, cost_usd, run_dir). Returns the ids actually changed:
    {"tasks": [ids], "runs": [ids]}, and "cancelled": [run ids ended cancelled] when there are any."""
    note = text_arg(note, "note", NOTE_MAX, multiline=True)
    now = iso(utcnow())
    tasks, runs, cancelled, usage = [], set(), [], usage or {}
    with write(conn):
        for task_id in sorted({int(i) for i in task_ids}):
            if conn.execute("SELECT 1 FROM tasks WHERE id = ? AND state = 'running'", (task_id,)).fetchone() is None:
                continue
            tasks.append(task_id)
            found = [r["id"] for r in conn.execute("SELECT id FROM task_runs WHERE task_id = ? AND status = 'running'", (task_id,))]
            runs.update(found)
            stop = stop_of(conn, task_id)
            if stop is not None:
                for run_id in found:
                    _end_stopped_run(conn, run_id, stop, now, usage.get(run_id) or {})
                    cancelled.append(run_id)
                _settle_stopped_task(conn, task_id, stop, now)
                continue
            conn.execute("UPDATE tasks SET state = 'failed', note = ?, updated_at = ? WHERE id = ?", (note, now, task_id))
        runs.update(r["id"] for i in {int(i) for i in run_ids} for r in conn.execute(
            "SELECT id FROM task_runs WHERE id = ? AND status = 'running'", (i,)))
        for run_id in sorted(runs):
            row = conn.execute("SELECT task_id FROM task_runs WHERE id = ? AND status = 'running'", (run_id,)).fetchone()
            if row is None:
                continue
            stop = stop_of(conn, row["task_id"])
            if stop is not None:   # a run left running whose task the stop did not reach (the router's run on a request)
                _end_stopped_run(conn, run_id, stop, now, usage.get(run_id) or {})
                cancelled.append(run_id)
                _settle_stopped_task(conn, row["task_id"], stop, now)
                continue
            conn.execute("UPDATE task_runs SET status = 'failed', failure = 'stopped', ended_at = ?, error = ? "
                         "WHERE id = ? AND status = 'running'", (now, note, run_id))
    return {"tasks": tasks, "runs": sorted(runs), **({"cancelled": sorted(cancelled)} if cancelled else {})}


def step_task_add(conn: sqlite3.Connection, *, key: str, title: str, text: str, step: str, args: dict | None = None,
                  footprint=None, request_id: int | None = None, depends_on=None, milestone: bool = False) -> dict:
    """Add one step task, `planned` (then `ready` at once when it depends on nothing, or when every task it depends on is done,
    as a skill task becomes: _refresh). Without request_id a request is made for it, `planned`, with no flow; with one, that
    request must be `planned` or `done` (a done request gets work again and is `planned`). key is lowercase words joined by
    hyphens, once per request; depends_on names keys of tasks the request already has. step is the kind (a word of the engine's
    registry, runtime/steps.py), args its arguments (an object, stored as canonical JSON) and footprint the project paths the
    kind declares it writes, which the caller derived from the kind. The task belongs to the agent STEP_OWNER.
    Returns {"request": id, "task": id, "state"}."""
    item = {"key": key, "step": step, "args": args, "footprint": footprint, "title": title, "text": text,
            "depends_on": list(depends_on or []), "milestone": milestone}
    now = iso(utcnow())
    with write(conn):
        if request_id is None:
            plan = _plan_items([item])
            request_id = conn.execute("INSERT INTO tasks (title, text, state, created_at, updated_at) VALUES (?, ?, 'planned', ?, ?)",
                                      (plan[0]["title"], plan[0]["text"], now, now)).lastrowid
            known, flow = {}, None
        else:
            request = _request(conn, request_id)
            if request["state"] not in ("planned", "done"):
                raise StoreError(f"request {request_id} is {request['state']}: a step task is added to a planned or a done request")
            if request["stop_requested_at"]:
                raise StoreError(f"request {request_id} is being cancelled: a step task is not added to it")
            known = {r["key"]: r["id"] for r in conn.execute("SELECT id, key FROM tasks WHERE parent_id = ? ORDER BY id",
                                                               (request_id,)).fetchall() if r["key"] is not None}
            if key in known:
                raise StoreError(f"request {request_id} already has a task {key!r}")
            plan = _plan_items([item], known=tuple(known))
            flow = request["flow"]
            conn.execute("UPDATE tasks SET state = 'planned', updated_at = ? WHERE id = ?", (now, request_id))
        added = _insert_plan(conn, request_id, flow, plan, now, known)
        _refresh(conn, now)
        state = conn.execute("SELECT state FROM tasks WHERE id = ?", (added[0],)).fetchone()["state"]
    return {"request": request_id, "task": added[0], "state": state}


def step_task_move(conn: sqlite3.Connection, task_id: int, *, state: str, note: str | None = None, pending: dict | None = None,
                   resolve: dict | None = None, step_state=None, by: str = "code") -> dict:
    """Move a step task to `running`, `waiting`, `failed` or `done`, in one transaction. `waiting` needs `pending` ({"kind",
    "title", "body"[, "payload"]}, opened on the task, run_id NULL); the other states refuse one. Every decision of the task
    still open when it moves is cancelled, except `resolve` ({"id", "answer"}), which is resolved `answered` by `by` in the
    same transaction. step_state, when given (a JSON object), is stored with the move, so that the engine's progress and the
    task's state never differ. A task that is `done` or `cancelled` does not move; when it becomes `done`, the tasks that
    depended on it become ready and a request whose tasks are all done becomes done. Returns {"task_id", "state",
    "pending_id" or None, "ready": [ids]}."""
    if state not in STEP_STATES or (state == "waiting") != (pending is not None):
        raise StoreError("a step task moves to running, failed or done, or to waiting with a pending decision", EXIT_USAGE)
    note = text_arg(note, "note", NOTE_MAX, multiline=True, required=False)
    item = None if pending is None else _pending_item(pending)
    saved = None if step_state is None else _step_state_arg(step_state)
    now = iso(utcnow())
    with write(conn):
        task = _task(conn, task_id)
        if not is_step_task(task):
            raise StoreError(f"task {task_id} is not a step task")
        if task["state"] in TASK_FINAL_STATES:
            raise StoreError(f"task {task_id} is {task['state']}: it does not move")
        if task["state"] == "running" and stop_of(conn, task_id) is not None:   # R18: a stopped step ends through task_stopped
            raise StoreError(f"task {task_id} has a stop request: it does not move")
        if resolve is not None:
            row = conn.execute("SELECT task_id, status FROM pending_decisions WHERE id = ?", (resolve.get("id"),)).fetchone()
            if row is None or row["task_id"] != task_id or row["status"] != "open":
                raise StoreError(f"pending decision {resolve.get('id')} is not open on task {task_id}")
            answer = text_arg(resolve.get("answer"), "answer", NOTE_MAX, multiline=True)
            conn.execute("UPDATE pending_decisions SET status = 'resolved', resolution = 'answered', answer = ?, resolved_at = ?, "
                         "resolved_by = ? WHERE id = ?", (answer, now, text_arg(by, "by", LABEL_MAX), resolve["id"]))
        conn.execute("UPDATE pending_decisions SET status = 'cancelled', resolved_at = ?, resolved_by = 'code' WHERE task_id = ? "
                     "AND status = 'open'", (now, task_id))
        conn.execute("UPDATE tasks SET state = ?, note = ?, updated_at = ?, step_state = COALESCE(?, step_state) WHERE id = ?",
                     (state, note, now, saved, task_id))
        pending_id = None
        if item is not None:
            pending_id = conn.execute(
                "INSERT INTO pending_decisions (task_id, run_id, kind, title, body, payload, payload_sha256, created_at) "
                "VALUES (?, NULL, ?, ?, ?, ?, ?, ?)", (task_id, *item, now)).lastrowid
        ready, _completed = _refresh(conn, now)
    return {"task_id": task_id, "state": state, "pending_id": pending_id, "ready": ready}


def step_state_save(conn: sqlite3.Connection, task_id: int, step_state) -> dict:
    """Store the engine's progress of a step task (a JSON object, at most STEP_STATE_MAX bytes) without moving the task: what
    the engine does after each step, so that a task killed or stopped between two steps resumes at the next one. A task that is
    done or cancelled keeps its state. Returns {"task_id"}."""
    saved = _step_state_arg(step_state)
    with write(conn):
        task = _task(conn, task_id)
        if not is_step_task(task):
            raise StoreError(f"task {task_id} is not a step task")
        if task["state"] in TASK_FINAL_STATES:
            raise StoreError(f"task {task_id} is {task['state']}: its state does not change")
        conn.execute("UPDATE tasks SET step_state = ? WHERE id = ?", (saved, task_id))
    return {"task_id": task_id}


# The tasks of a request that hold a slot of their agent: running, waiting for the person, or ready because the person
# answered a decision the task's latest run opened (it is about to run again).
SLOT_HOLDERS = (
    "SELECT t.id, t.agent FROM tasks t WHERE t.parent_id IS NOT NULL AND ("
    " t.state = 'running' OR (t.state = 'waiting' AND t.step_kind IS NULL)"
    " OR (t.state = 'ready' AND EXISTS ("
    "  SELECT 1 FROM pending_decisions p WHERE p.task_id = t.id AND p.resolution = 'answered'"
    "   AND p.created_at >= (SELECT MAX(r.started_at) FROM task_runs r WHERE r.task_id = t.id)))) ORDER BY t.id")


def task_slot_holders(conn: sqlite3.Connection) -> list:
    """The tasks of a request that hold a slot of their agent, as {"id", "agent"}, ordered by id: `running`, `waiting`,
    or `ready` after the person answered a decision that the task's latest run opened. A task that never ran, or that
    failed after the answer and was retried, holds none."""
    return [row_dict(r) for r in conn.execute(SLOT_HOLDERS)]


def task_running_list(conn: sqlite3.Connection) -> list:
    """Every task in state `running`, oldest first, as {"task": the task as task_get gives it, "run": {"id",
    "started_at", "skill", "billing"} of its live run row (status `running`), or None when it has none yet}."""
    out = []
    for row in conn.execute("SELECT id FROM tasks WHERE state = 'running' ORDER BY id").fetchall():
        run = conn.execute("SELECT id, started_at, skill, billing FROM task_runs WHERE task_id = ? AND status = 'running' "
                           "ORDER BY id DESC LIMIT 1", (row["id"],)).fetchone()
        out.append({"task": _task(conn, row["id"]), "run": None if run is None else row_dict(run)})
    return out


def task_runs_since(conn: sqlite3.Connection, low_water: int) -> list:
    """The run rows of tasks of a request (not the router's) with id at or above low_water, ordered by id, every column."""
    return [row_dict(r) for r in conn.execute(
        "SELECT r.* FROM task_runs r JOIN tasks t ON t.id = r.task_id WHERE t.parent_id IS NOT NULL AND r.id >= ? "
        "ORDER BY r.id", (int(low_water),))]


def request_cancel(conn: sqlite3.Connection, request_id: int, *, by: str, keep=()) -> dict:
    """Cancel a request that nothing is running for: the request and each of its tasks that is not done or cancelled become
    `cancelled`, and their open pending decisions too. Refused while one of its tasks is running (a cancel that reaches a run in
    progress is `request_stop`). `keep`: ids of open pending decisions that
    stay open, and the task each belongs to stays as it is (an effect whose write is running: runtime/ops_cancel.py); the rest is
    cancelled. Returns {"request", "cancelled": [task ids], "pending": [pending ids]}, and "kept": [pending ids left open] when some were."""
    by = text_arg(by, "by", LABEL_MAX)
    now = iso(utcnow())
    with write(conn):
        return _cancel_request(conn, request_id, by, now, tuple(int(k) for k in keep))


def _cancel_rows(conn: sqlite3.Connection, ids, by: str, now: str) -> list:
    """Inside a transaction: each task of ids becomes `cancelled` and its open pending decisions too (an approval of an
    effect still waiting to execute is revoked). Returns the pending ids closed."""
    pending = []
    for task_id in ids:
        conn.execute("UPDATE tasks SET state = 'cancelled', updated_at = ? WHERE id = ?", (now, task_id))
        for p in conn.execute("SELECT id FROM pending_decisions WHERE task_id = ? AND status = 'open'",
                              (task_id,)).fetchall():
            conn.execute("UPDATE pending_decisions SET status = 'cancelled', resolved_at = ?, resolved_by = ? "
                         "WHERE id = ?", (now, by, p["id"]))
            _revoke_pending_execution(conn, p["id"], now)
            pending.append(p["id"])
    return pending


def _cancel_request(conn: sqlite3.Connection, request_id: int, by: str, now: str, keep=()) -> dict:
    """Inside a transaction: request_cancel's work."""
    root = _task(conn, request_id)
    if root["parent_id"] is not None:
        raise StoreError(f"task {request_id} is not a request: cancel the request it belongs to")
    rows = conn.execute("SELECT id, state FROM tasks WHERE id = ? OR parent_id = ? ORDER BY id",
                        (request_id, request_id)).fetchall()
    if any(r["state"] == "running" for r in rows) or conn.execute(
            "SELECT 1 FROM task_runs WHERE task_id = ? AND status = 'running'", (request_id,)).fetchone():
        raise StoreError(f"a task of request {request_id} is running: wait for its run to end")
    kept = {p["task_id"]: p["id"] for p in conn.execute("SELECT id, task_id FROM pending_decisions WHERE status = 'open'").fetchall()
            if p["id"] in keep}
    ids = [r["id"] for r in rows if r["state"] not in TASK_FINAL_STATES and r["id"] not in kept]
    pending = _cancel_rows(conn, ids, by, now)
    _refresh(conn, now)  # what waited for a cancelled task or request no longer does
    return {"request": request_id, "cancelled": ids, "pending": pending, **({"kept": sorted(kept.values())} if kept else {})}


# --- migration 15: cancel or stop at any moment (R18) -------------------------------------------------------------
#
# A stop request is written first, in one transaction (request_stop, task_stop): on a request row it says "cancel this
# request", on a task row "stop this task". Everything that ends after it reads it in its own transaction: a run that
# finishes is recorded `cancelled`, opens no pending decision, and its task ends as the request says. A request being
# cancelled is `cancelled` itself once none of its tasks is running and none of its runs (the router's included) is.

STOPPED_NOTE = "stopped by {by}: retry it or cancel the request"   # the note of a task stopped on its own
CANCELLED_ERROR = "cancelled by {by}"                              # the error of a run that was stopped


def stop_of(conn: sqlite3.Connection, task_id: int):
    """The stop request that reaches a task, or None: {"scope": "request", "at", "by"} when its request is being cancelled
    (it wins) or the row is a request that is, else {"scope": "task", "at", "by"} when the task itself was stopped."""
    row = conn.execute("SELECT parent_id, stop_requested_at, stop_requested_by FROM tasks WHERE id = ?",
                       (task_id,)).fetchone()
    if row is None:
        return None
    if row["parent_id"] is None:
        return {"scope": "request", "at": row["stop_requested_at"], "by": row["stop_requested_by"]} \
            if row["stop_requested_at"] else None
    top = conn.execute("SELECT stop_requested_at, stop_requested_by FROM tasks WHERE id = ?",
                       (row["parent_id"],)).fetchone()
    if top is not None and top["stop_requested_at"]:
        return {"scope": "request", "at": top["stop_requested_at"], "by": top["stop_requested_by"]}
    if row["stop_requested_at"]:
        return {"scope": "task", "at": row["stop_requested_at"], "by": row["stop_requested_by"]}
    return None


def _running_runs(conn: sqlite3.Connection, task_id: int) -> list:
    return [r["id"] for r in conn.execute(
        "SELECT id FROM task_runs WHERE task_id = ? AND status = 'running' ORDER BY id", (task_id,))]


def _kept(conn: sqlite3.Connection, request_id: int) -> dict:
    """{task id: pending id} of the open decisions a cancel of this request left open (request_stop's keep: an effect whose output write
    runs), read from the cursor `stop-keep:<request>` it wrote; what a later end of the request must not cancel."""
    row = conn.execute("SELECT value FROM cursors WHERE name = ?", (f"stop-keep:{request_id}",)).fetchone()
    try:
        wanted = {int(i) for i in json.loads(row["value"])} if row else set()
    except ValueError:
        wanted = set()
    return {p["task_id"]: p["id"] for p in conn.execute("SELECT id, task_id FROM pending_decisions WHERE status = 'open'") if p["id"] in wanted}


def _complete_cancel(conn: sqlite3.Connection, request_id: int, now: str) -> bool:
    """Inside a transaction: a request that is being cancelled becomes `cancelled`, with whatever is still open under it (but a decision
    that request_stop was told to keep, and the task it belongs to), once none of its tasks is `running` and none of its runs (the
    router's, on the request, included) is. Returns whether it did."""
    root = conn.execute("SELECT state, stop_requested_at, stop_requested_by FROM tasks WHERE id = ? AND parent_id IS NULL",
                        (request_id,)).fetchone()
    if root is None or not root["stop_requested_at"] or root["state"] == "cancelled":
        return False
    if conn.execute("SELECT 1 FROM tasks WHERE parent_id = ? AND state = 'running'", (request_id,)).fetchone() or conn.execute(
            "SELECT 1 FROM task_runs r JOIN tasks t ON t.id = r.task_id WHERE r.status = 'running' AND "
            "(t.id = ? OR t.parent_id = ?)", (request_id, request_id)).fetchone():
        return False
    kept = _kept(conn, request_id)
    ids = [r["id"] for r in conn.execute("SELECT id FROM tasks WHERE (id = ? OR parent_id = ?) AND state NOT IN "
                                         "('done', 'cancelled') ORDER BY id", (request_id, request_id)) if r["id"] not in kept]
    _cancel_rows(conn, ids, root["stop_requested_by"], now)
    _refresh(conn, now)
    return True


def request_stop(conn: sqlite3.Connection, request_id: int, *, by: str, keep=()) -> dict:
    """Cancel a request at any moment, the first half (R18): in one transaction the request records the stop request, every
    task of it that is not running and not final is cancelled at once (so nothing new is claimed), with its open pending
    decisions, and, when nothing of it is running, the request itself is cancelled. What is running is left for the caller to
    stop and finish (task_stopped ends a run whose holder is gone; a run that finishes reads the request). A request already
    cancelled, or already asked to be, is not written again. keep: ids of open pending decisions that stay open, with the task each
    belongs to (an effect whose output write runs: runtime/ops_cancel.py), as request_cancel keeps them; the request remembers them
    (the cursor `stop-keep:<request>`) so that its end, which may come from a run's finish, keeps them too. Returns {"request",
    "cancelled": [task ids cancelled, the request's included when it is], "pending": [pending ids cancelled], "running": [{"task", "run"
    (its running run row or None), "step"}], "router_run": the running run row of the router on the request, or None, "already"} and
    "kept": [pending ids left open] when some were."""
    by = text_arg(by, "by", LABEL_MAX)
    now = iso(utcnow())
    with write(conn):
        root = _task(conn, request_id)
        if root["parent_id"] is not None:
            raise StoreError(f"task {request_id} is not a request: cancel the request it belongs to")
        if root["state"] in TASK_FINAL_STATES:
            if root["state"] == "done" and _running_runs(conn, request_id):   # a delivery routed again: the run is not a stop's to end
                raise StoreError(f"a task of request {request_id} is running: wait for its run to end")
            return {"request": request_id, "cancelled": [], "pending": [], "running": [], "router_run": None,
                    "already": root["state"] == "cancelled"}
        already = root["stop_requested_at"] is not None
        if not already:
            conn.execute("UPDATE tasks SET stop_requested_at = ?, stop_requested_by = ? WHERE id = ?", (now, by, request_id))
        keep = {int(k) for k in keep}
        if keep:
            held = sorted(keep | set(_kept(conn, request_id).values()))
            conn.execute("INSERT INTO cursors (name, value, updated_at) VALUES (?, ?, ?) ON CONFLICT (name) DO UPDATE SET "
                         "value = excluded.value, updated_at = excluded.updated_at", (f"stop-keep:{request_id}", json.dumps(held), now))
        kept = _kept(conn, request_id)
        rows = conn.execute("SELECT id, state, step_kind FROM tasks WHERE parent_id = ? ORDER BY id", (request_id,)).fetchall()
        running = [{"task": r["id"], "run": (_running_runs(conn, r["id"]) or [None])[-1], "step": r["step_kind"] is not None}
                   for r in rows if r["state"] == "running"]
        ids = [r["id"] for r in rows if r["state"] not in TASK_FINAL_STATES and r["state"] != "running" and r["id"] not in kept]
        pending = _cancel_rows(conn, ids, root["stop_requested_by"] if already else by, now)
        router = (_running_runs(conn, request_id) or [None])[-1]
        if _complete_cancel(conn, request_id, now):
            ids.append(request_id)
        else:
            _refresh(conn, now)
        return {"request": request_id, "cancelled": ids, "pending": pending, "running": running, "router_run": router,
                "already": already, **({"kept": sorted(kept.values())} if kept else {})}


def task_stop(conn: sqlite3.Connection, task_id: int, *, by: str) -> dict:
    """Stop one running task at any moment, the first half: the task records the stop request. The run (or step) of it ends
    `cancelled` and the task `blocked` with a note saying so, and `retry` makes it ready again (task_retry clears the request).
    A task already asked to stop, or whose request is being cancelled, is not written again. Refused unless the task is running
    (or already stopped). Returns {"task", "run" (its running run row or None), "step", "already", "scope"}."""
    by = text_arg(by, "by", LABEL_MAX)
    now = iso(utcnow())
    with write(conn):
        task = _task(conn, task_id)
        if task["parent_id"] is None:
            raise StoreError(f"task {task_id} is a request: cancel it")
        found = stop_of(conn, task_id)
        run = (_running_runs(conn, task_id) or [None])[-1]
        step = task.get("step_kind") is not None
        if found is not None:
            return {"task": task_id, "run": run, "step": step, "already": True, "scope": found["scope"]}
        if task["state"] != "running":
            raise StoreError(f"task {task_id} is {task['state']}: only a running task is stopped")
        conn.execute("UPDATE tasks SET stop_requested_at = ?, stop_requested_by = ? WHERE id = ?", (now, by, task_id))
        return {"task": task_id, "run": run, "step": step, "already": False, "scope": "task"}


def _end_stopped_run(conn: sqlite3.Connection, run_id: int, stop: dict, now: str, fields: dict) -> None:
    """Inside a transaction: record a run as `cancelled` (failure none, no ending), with what it reported (fields: attempts,
    cost_usd, tokens, duration_ms, skill_loaded, image_digest, run_dir, redactions; each optional)."""
    conn.execute(
        "UPDATE task_runs SET status = 'cancelled', failure = NULL, ending = NULL, attempts = COALESCE(?, attempts), "
        "ended_at = ?, cost_usd = COALESCE(?, cost_usd), tokens = COALESCE(?, tokens), "
        "duration_ms = COALESCE(?, duration_ms), skill_loaded = ?, image_digest = COALESCE(?, image_digest), "
        "run_dir = COALESCE(?, run_dir), error = ?, redactions = COALESCE(?, redactions) WHERE id = ? AND status = 'running'",
        (fields.get("attempts"), now, fields.get("cost_usd"), fields.get("tokens"), fields.get("duration_ms"),
         fields.get("skill_loaded"), fields.get("image_digest"), fields.get("run_dir"),
         CANCELLED_ERROR.format(by=stop["by"]), fields.get("redactions"), run_id))


def _settle_stopped_task(conn: sqlite3.Connection, task_id: int, stop: dict, now: str) -> str:
    """Inside a transaction: a stopped task that was `running` ends as the stop says. A request being cancelled: the task is
    `cancelled` with its open pending decisions, and the request is `cancelled` too once nothing of it is running. A task
    stopped on its own: `blocked`, with the note, for `retry` (its dependents stay planned). Returns the task's state."""
    task = _task(conn, task_id)
    if stop["scope"] == "request":
        if task["state"] == "running":
            _cancel_rows(conn, [task_id], stop["by"], now)
        _complete_cancel(conn, task["parent_id"] if task["parent_id"] is not None else task_id, now)
        return _task(conn, task_id)["state"]
    if task["state"] == "running":
        conn.execute("UPDATE tasks SET state = 'blocked', note = ?, updated_at = ? WHERE id = ?",
                     (STOPPED_NOTE.format(by=stop["by"]), now, task_id))
    return _task(conn, task_id)["state"]


def task_stopped(conn: sqlite3.Connection, task_id: int, *, usage: dict | None = None) -> dict:
    """End a stopped task whose holder is gone: each run row of it still `running` ends `cancelled` (usage maps a run id to what it
    reported: tokens, cost_usd, run_dir), and the task ends as the stop says. The caller does not hold the task's lock (the canceller
    only found it free, or the holder exited after TERM): a task claimed again meanwhile is not possible, because a task with a stop
    request is not claimed (task_claim). A task with no stop request, or not `running`, is left alone. Returns {"task", "state", "runs": [ids]}."""
    now = iso(utcnow())
    with write(conn):
        stop = stop_of(conn, task_id)
        task = _task(conn, task_id)
        if stop is None or task["state"] != "running":
            return {"task": task_id, "state": task["state"], "runs": []}
        runs = _running_runs(conn, task_id)
        for run_id in runs:
            _end_stopped_run(conn, run_id, stop, now, (usage or {}).get(run_id) or {})
        return {"task": task_id, "state": _settle_stopped_task(conn, task_id, stop, now), "runs": runs}


# --- migration 4: the task board, the plan, mirrored documents, saved comments -------------------------------


def _request(conn: sqlite3.Connection, request_id: int) -> dict:
    task = _task(conn, request_id)
    if task["parent_id"] is not None:
        raise StoreError(f"task {request_id} is not a request")
    return task


def _open_pending(conn: sqlite3.Connection, task_id: int, kinds=None) -> list:
    rows = conn.execute("SELECT id, kind FROM pending_decisions WHERE task_id = ? AND status = 'open' ORDER BY id",
                        (task_id,)).fetchall()
    return [row_dict(r) for r in rows if kinds is None or r["kind"] in kinds]


def _open_of_kind(conn: sqlite3.Connection, pending_id: int, kind: str) -> dict:
    row = conn.execute("SELECT * FROM pending_decisions WHERE id = ?", (pending_id,)).fetchone()
    if row is None:
        raise StoreError(f"no pending decision {pending_id}")
    item = row_dict(row, ("payload",))
    if item["kind"] != kind:
        raise StoreError(f"pending decision {pending_id} is a {item['kind']}, not a {kind}")
    if item["status"] != "open":
        raise StoreError(f"pending decision {pending_id} is {item['status']}, not open")
    return item


def _resolve(conn: sqlite3.Connection, pending_id: int, resolution: str, by: str, now: str, answer=None, actor=None) -> None:
    conn.execute("UPDATE pending_decisions SET status = 'resolved', resolution = ?, answer = ?, resolved_at = ?, "
                 "resolved_by = ?, actor = ? WHERE id = ?", (resolution, answer, now, by, actor, pending_id))


def _rel_path(path: str) -> str:
    path = text_arg(path, "path", PATH_MAX)
    parts = path.split("/")
    if path.startswith(("/", "~")) or "\\" in path or any(p in ("", ".", "..") for p in parts):
        raise StoreError(f"path {path!r} must be a relative path inside the project", EXIT_USAGE)
    return path


def _sha_or_none(value, flag: str):
    if value is not None and not SHA256_RE.fullmatch(str(value)):
        raise StoreError(f"{flag} must be 64 hexadecimal characters", EXIT_USAGE)
    return value


def task_remote_set(conn: sqlite3.Connection, task_id: int, *, remote_id: str, remote_version: str | None,
                    written_sha256: str | None) -> dict:
    """Record the task's item on the task board: its id there, the version the board reported and the hash of
    what the runtime last wrote to it. Returns the task."""
    remote_id = text_arg(remote_id, "remote_id", REF_MAX)
    remote_version = text_arg(remote_version, "remote_version", REF_MAX, required=False)
    written_sha256 = _sha_or_none(written_sha256, "written_sha256")
    now = iso(utcnow())
    with write(conn):
        _task(conn, task_id)
        conn.execute("UPDATE tasks SET remote_id = ?, remote_version = ?, remote_written_sha256 = ?, updated_at = ? "
                     "WHERE id = ?", (remote_id, remote_version, written_sha256, now, task_id))
        return _task(conn, task_id)


def task_edit(conn: sqlite3.Connection, task_id: int, *, by: str, title: str | None = None,
              text: str | None = None) -> dict:
    """A person's edit of a task's title or text (on the task board). Refused on a task that is running, done or
    cancelled, and for an empty value or one over its cap. Returns the task."""
    text_arg(by, "by", LABEL_MAX)
    if title is None and text is None:
        raise StoreError("an edit changes the title, the text or both", EXIT_USAGE)
    title = text_arg(title, "title", TITLE_MAX, required=False)
    text = text_arg(text, "text", TEXT_MAX, multiline=True, required=False)
    now = iso(utcnow())
    with write(conn):
        state = _task(conn, task_id)["state"]
        if state in ("running", "done", "cancelled"):
            raise StoreError(f"task {task_id} is {state}: its title and text are not edited now")
        conn.execute("UPDATE tasks SET title = COALESCE(?, title), text = COALESCE(?, text), updated_at = ? "
                     "WHERE id = ?", (title, text, now, task_id))
        return _task(conn, task_id)


def request_from_board(conn: sqlite3.Connection, *, title: str, text: str, remote_id: str,
                       remote_version: str | None, by: str, after: int | None = None) -> dict:
    """An item a person wrote on the task board becomes a request in `requested`, with its item recorded and an
    open pending decision of kind `acceptance` on it, in one transaction. A second call with the same remote_id
    creates nothing and returns the existing request. after is the request the item's own words say it runs after
    ("after #n", runtime/board.py). Returns {"request", "pending_id", "existing"}."""
    title = text_arg(title, "title", TITLE_MAX)
    text = text_arg(text, "text", TEXT_MAX, multiline=True)
    remote_id = text_arg(remote_id, "remote_id", REF_MAX)
    remote_version = text_arg(remote_version, "remote_version", REF_MAX, required=False)
    by = text_arg(by, "by", LABEL_MAX)
    now = iso(utcnow())
    with write(conn):
        row = conn.execute("SELECT id FROM tasks WHERE parent_id IS NULL AND remote_id = ? ORDER BY id LIMIT 1",
                           (remote_id,)).fetchone()
        if row is not None:
            found = _open_pending(conn, row["id"], ("acceptance",))
            return {"request": row["id"], "pending_id": found[0]["id"] if found else None, "existing": True}
        request_id = conn.execute(
            "INSERT INTO tasks (title, text, state, remote_id, remote_version, after_request, created_at, updated_at) "
            "VALUES (?, ?, 'requested', ?, ?, ?, ?, ?)",
            (title, text, remote_id, remote_version, _check_after(conn, None, after), now, now)).lastrowid
        payload = json.dumps({"source": "board", "remote_id": remote_id, "by": by}, ensure_ascii=True, sort_keys=True)
        pending_id = conn.execute(
            "INSERT INTO pending_decisions (task_id, kind, title, body, payload, created_at) "
            "VALUES (?, 'acceptance', ?, ?, ?, ?)",
            (request_id, f"Accept a request written on the task board: {title}"[:TITLE_MAX], text, payload,
             now)).lastrowid
    return {"request": request_id, "pending_id": pending_id, "existing": False}


def acceptance_resolve(conn: sqlite3.Connection, pending_id: int, *, resolution: str, by: str,
                       note: str | None = None, waits: list | None = None, actor: str | None = None) -> dict:
    """The person's decision on an `acceptance`, by its payload's `what` (stage 6):

    no `what`   (a request written on the task board, stage 3) `accepted` leaves the request `requested` (it is
                routed next); `rejected` cancels it, with what is open under it
    subtasks    `accepted` adds the tasks of payload["tasks"] to the request as tasks_add adds them, in the same
                transaction; `rejected` adds nothing
    deliveries  the resolution and the note are recorded and nothing else changes

    note is kept as the decision's answer; waits are the waits the accepted sub-tasks begin with (tasks_add). Returns
    {"pending_id", "task_id", "task_state"}, and "added" (the rows of
    the added tasks) for accepted sub-tasks."""
    if ("acceptance", resolution) not in KIND_RESOLUTIONS:
        raise StoreError("an acceptance is accepted or rejected", EXIT_USAGE)
    by = text_arg(by, "by", LABEL_MAX)
    actor = text_arg(actor, "actor", ACTOR_MAX, required=False)
    note = text_arg(note, "note", NOTE_MAX, multiline=True, required=False)
    now = iso(utcnow())
    with write(conn):
        item = _open_of_kind(conn, pending_id, "acceptance")
        what = (item["payload"] or {}).get("what")
        if what is not None:
            if what not in ACCEPTANCE_WHATS:
                raise StoreError(f"pending decision {pending_id} accepts {what!r}, not one of "
                                 f"{', '.join(ACCEPTANCE_WHATS)}")
            _resolve(conn, pending_id, resolution, by, now, note, actor)
            out = {"pending_id": pending_id, "task_id": item["task_id"]}
            if what == "subtasks" and resolution == "accepted":
                out["added"] = _tasks_add(conn, item["task_id"], item["payload"].get("tasks"), now, waits)["tasks"]
            out["task_state"] = _task(conn, item["task_id"])["state"]
            return out
        _resolve(conn, pending_id, resolution, by, now, note, actor)
        task = _task(conn, item["task_id"])
        if resolution == "rejected" and task["parent_id"] is None:
            _cancel_request(conn, task["id"], by, now)
        elif resolution == "rejected":
            conn.execute("UPDATE tasks SET state = 'cancelled', updated_at = ? WHERE id = ? AND state NOT IN "
                         "('done', 'cancelled')", (now, task["id"]))
            _refresh(conn, now)
        state = _task(conn, item["task_id"])["state"]
    return {"pending_id": pending_id, "task_id": item["task_id"], "task_state": state}


def _router_run_in(conn: sqlite3.Connection, request_id: int, *, skill: str, model: str, adapter: str, skill_version, skill_sha256,
                   web: bool, reroute: bool, billing, autonomy, now: str) -> int:
    """Inside a write transaction: route_run_start's checks and its row. Returns the run's id."""
    request = _request(conn, request_id)
    if request["stop_requested_at"]:
        raise StoreError(f"request {request_id} is being cancelled: it is not routed")
    if reroute:
        if request["state"] not in REROUTE_STATES:
            raise StoreError(f"request {request_id} is {request['state']}: only a planned or done request has a "
                             "delivery routed again")
    elif request["state"] != "requested":
        raise StoreError(f"request {request_id} is {request['state']}: only a request waiting for its plan is routed")
    open_items = [] if reroute else _open_pending(conn, request_id)
    if open_items:
        raise StoreError(f"request {request_id} has an open {open_items[0]['kind']} (pending decision "
                         f"{open_items[0]['id']}): decide it first")
    if conn.execute("SELECT 1 FROM task_runs r JOIN tasks t ON t.id = r.task_id "
                    "WHERE r.status = 'running' AND t.parent_id IS NULL").fetchone():
        raise StoreError("a router run is in progress: one router run at a time per project")
    run_id = conn.execute(
        "INSERT INTO task_runs (task_id, skill, skill_version, skill_sha256, model, adapter, web, started_at, billing, "
        "autonomy) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (request_id, skill, skill_version, skill_sha256, model, adapter, 1 if web else 0, now, billing, autonomy)).lastrowid
    return run_id


def route_run_start(conn: sqlite3.Connection, request_id: int, *, skill: str, model: str, adapter: str,
                    skill_version: str | None = None, skill_sha256: str | None = None, web: bool = False,
                    reroute: bool = False, billing: str | None = None, autonomy: str | None = None) -> dict:
    """A run of the router on a request: a row of task_runs whose task is the request. Refused unless the request
    is `requested` with no open pending decision and no router run is running (task runs do not prevent it).
    With reroute (stage 6: one delivery of an approved plan routed again after its brief), the request is `planned`
    or `done` instead, and an open pending decision on it does not refuse the run.
    billing and autonomy are recorded as task_run_start records them. Returns {"run_id", "request_id", "started_at"}."""
    billing = _billing_arg(billing)
    autonomy = _autonomy_arg(autonomy)
    skill = text_arg(skill, "skill", LABEL_MAX)
    model = text_arg(model, "model", REF_MAX)
    adapter = text_arg(adapter, "adapter", LABEL_MAX)
    skill_version = text_arg(skill_version, "skill_version", LABEL_MAX, required=False)
    skill_sha256 = _sha_or_none(skill_sha256, "skill_sha256")
    now = iso(utcnow())
    with write(conn):
        run_id = _router_run_in(conn, request_id, skill=skill, model=model, adapter=adapter, skill_version=skill_version,
                                skill_sha256=skill_sha256, web=web, reroute=reroute, billing=billing, autonomy=autonomy, now=now)
    return {"run_id": run_id, "request_id": request_id, "started_at": now}


def route_run_finish(conn: sqlite3.Connection, run_id: int, *, status: str, failure: str | None = None,
                     ending: str | None = None, attempts: int = 0, cost_usd: float | None = None,
                     tokens: int | None = None, duration_ms: int | None = None, skill_loaded: bool | None = None,
                     image_digest: str | None = None, run_dir: str | None = None, error: str | None = None,
                     pending: dict | None = None, redactions: int | None = None) -> dict:
    """End a run of the router and, with `pending` (kind `plan` or `question`), open it on the request, all or
    nothing. The request stays `requested`. A run made with reroute opens an `acceptance` instead (payload["what"]
    `subtasks` or `deliveries`), on its `planned` or `done` request, whose state does not change. A request that is being
    cancelled (request_stop) has the run recorded `cancelled` and nothing opened (R18). Returns {"run_id", "request_id",
    "pending_id" or None, "cancelled"}."""
    if status not in ("ok", "failed") or (status == "failed") != (failure is not None):
        raise StoreError("status is ok, or failed with the kind of failure", EXIT_USAGE)
    if failure is not None and failure not in RUN_FAILURES:
        raise StoreError(f"failure must be one of {', '.join(RUN_FAILURES)}", EXIT_USAGE)
    if ending is not None and ending not in RUN_ENDINGS:
        raise StoreError(f"ending must be one of {', '.join(RUN_ENDINGS)}", EXIT_USAGE)
    if pending is not None and (not isinstance(pending, dict) or pending.get("kind") not in ("plan", "question", "acceptance")):
        raise StoreError("a router run opens a plan, a question or an acceptance", EXIT_USAGE)
    if pending is not None and pending["kind"] == "acceptance" and \
            (pending.get("payload") or {}).get("what") not in ACCEPTANCE_WHATS:
        raise StoreError(f"an acceptance a router run opens says what it accepts: {', '.join(ACCEPTANCE_WHATS)}", EXIT_USAGE)
    if pending is not None and status != "ok":
        raise StoreError("a failed run opens no pending decision", EXIT_USAGE)
    item = None if pending is None else _pending_item(pending)
    error = text_arg(error, "error", NOTE_MAX, multiline=True, required=False)
    run_dir = text_arg(run_dir, "run_dir", PATH_MAX, required=False)
    image_digest = text_arg(image_digest, "image_digest", REF_MAX, required=False)
    loaded = None if skill_loaded is None else (1 if skill_loaded else 0)
    if redactions is not None and (isinstance(redactions, bool) or not isinstance(redactions, int) or redactions < 0):
        raise StoreError("redactions is a count: a whole number, 0 or more", EXIT_USAGE)
    now = iso(utcnow())
    with write(conn):
        row = conn.execute("SELECT task_id, status FROM task_runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            raise StoreError(f"no task run {run_id}")
        if row["status"] != "running":
            raise StoreError(f"task run {run_id} already ended with status {row['status']}")
        request = _request(conn, row["task_id"])
        stop = stop_of(conn, request["id"])
        if stop is not None:   # the request is being cancelled: the router's run is recorded cancelled and opens nothing
            _end_stopped_run(conn, run_id, stop, now, {
                "attempts": int(attempts), "cost_usd": cost_usd, "tokens": tokens, "duration_ms": duration_ms,
                "skill_loaded": loaded, "image_digest": image_digest, "run_dir": run_dir, "redactions": redactions})
            _complete_cancel(conn, request["id"], now)
            return {"run_id": run_id, "request_id": request["id"], "pending_id": None, "cancelled": True}
        conn.execute(
            "UPDATE task_runs SET status = ?, failure = ?, ending = ?, attempts = ?, ended_at = ?, cost_usd = ?, "
            "tokens = ?, duration_ms = ?, skill_loaded = ?, image_digest = ?, run_dir = ?, error = ?, redactions = ? "
            "WHERE id = ?",
            (status, failure, ending, int(attempts), now, cost_usd, tokens, duration_ms, loaded, image_digest,
             run_dir, error, redactions, run_id))
        pending_id = None
        if item is not None:
            wanted = REROUTE_STATES if item[0] == "acceptance" else ("requested",)
            if request["state"] not in wanted:
                raise StoreError(f"request {request['id']} is {request['state']}: the router's result is not recorded")
            pending_id = conn.execute(
                "INSERT INTO pending_decisions (task_id, run_id, kind, title, body, payload, payload_sha256, "
                "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (request["id"], run_id, *item, now)).lastrowid
    return {"run_id": run_id, "request_id": request["id"], "pending_id": pending_id, "cancelled": False}


ASK_ACTOR_CURSOR = "ask-actor:{run}"   # who asked, kept beside an answer run (no column holds it): the same retention as the actor of a decision, never deleted
ANSWER_TITLE = "Question"             # the title code gives the request of a question, with its number ("Question 7"): what marks it as one
ANSWER_FAILED_BY = "code:answer-failed"   # the `by` of the request an answer run that failed cancels


def answer_run_start(conn: sqlite3.Connection, request_id: int | None = None, *, skill: str, model: str, adapter: str,
                     skill_version: str | None = None, skill_sha256: str | None = None, billing: str | None = None,
                     autonomy: str | None = None, title: str | None = None, text: str | None = None, web: bool = False) -> dict:
    """A run of the answer skill on the request a question made (the ask operation, runtime/ops_ask.py): the same row and the same
    checks as `route_run_start` (the request is `requested`, has no open decision and is not being cancelled; no router or answer run
    is running: one conversation model call per project at a time), on the web never; `web` is true only for the web research
    (runtime/ops_research.py, slice R2-F1), so that the row says what the run did. The row is a row of task_runs whose task is the
    request, so no new column, state or trigger exists. With no `request_id`, the request is made in the same transaction from `title`
    and `text`, so that no request of a question exists without its run (a mirror that reads the store between the two never sees it);
    its title is `title` and the request's number ("Question 7"), so that the text of a question is in the request's `text` and in no
    line that lists requests. Returns {"run_id", "request_id", "started_at"}."""
    billing = _billing_arg(billing)
    autonomy = _autonomy_arg(autonomy)
    skill = text_arg(skill, "skill", LABEL_MAX)
    model = text_arg(model, "model", REF_MAX)
    adapter = text_arg(adapter, "adapter", LABEL_MAX)
    skill_version = text_arg(skill_version, "skill_version", LABEL_MAX, required=False)
    skill_sha256 = _sha_or_none(skill_sha256, "skill_sha256")
    if request_id is None:
        title = text_arg(title, "title", TITLE_MAX)
        text = text_arg(text, "text", TEXT_MAX, multiline=True)
    now = iso(utcnow())
    with write(conn):
        if request_id is None:
            request_id = _request_in(conn, title, text, None, [], None, None, None, now)["request"]
            conn.execute("UPDATE tasks SET title = ? WHERE id = ?", (f"{title} {request_id}", request_id))
        run_id = _router_run_in(conn, request_id, skill=skill, model=model, adapter=adapter, skill_version=skill_version,
                                skill_sha256=skill_sha256, web=bool(web), reroute=False, billing=billing, autonomy=autonomy, now=now)
    return {"run_id": run_id, "request_id": request_id, "started_at": now}


def answers_abandoned_cancel(conn: sqlite3.Connection, router_skill: str) -> list:
    """Cancel, by `code:answer-failed`, the questions an ask left behind when its process died: a request that code made as a question
    (its title is ANSWER_TITLE and its number, which answer_run_start writes in the transaction that makes the request) AND that has no run of
    the router's skill (`router_skill`), with no task, in the state `requested`, that has runs, none running (the recovery has ended the
    run). Both are needed: a person's request that is called "Question 5" has the router's runs, and a request with a router run under a
    skill name this checkout no longer has is not called "Question N" by code. One whose run is still running is not touched. Returns
    the ids cancelled."""
    router_skill = text_arg(router_skill, "router_skill", LABEL_MAX)
    now = iso(utcnow())
    cancelled = []
    with write(conn):
        for row in conn.execute("SELECT id FROM tasks WHERE parent_id IS NULL AND state = 'requested' AND title = ? || ' ' || id ORDER BY id",
                                (ANSWER_TITLE,)).fetchall():
            if conn.execute("SELECT 1 FROM tasks WHERE parent_id = ?", (row["id"],)).fetchone():
                continue
            runs = conn.execute("SELECT id, skill, status FROM task_runs WHERE task_id = ?", (row["id"],)).fetchall()
            if not runs or any(r["status"] == "running" or r["skill"] == router_skill for r in runs):
                continue
            _cancel_request(conn, row["id"], ANSWER_FAILED_BY, now)
            cancelled.append(row["id"])
    return cancelled


def answer_run_finish(conn: sqlite3.Connection, run_id: int, *, status: str, failure: str | None = None, attempts: int = 0,
                      cost_usd: float | None = None, tokens: int | None = None, duration_ms: int | None = None,
                      skill_loaded: bool | None = None, image_digest: str | None = None, run_dir: str | None = None,
                      error: str | None = None, redactions: int | None = None) -> dict:
    """End a run that answer_run_start opened, all or nothing. `ok`: the run ends with the ending `done` and its request becomes
    `done`, in the same transaction. `failed` (with the kind of failure): the run is recorded failed and the request is cancelled by
    `code:answer-failed`, as `request_cancel` cancels it. A request that is being cancelled (request_stop) has the run recorded
    `cancelled` and the request settled as the stop says (R18). Returns {"run_id", "request_id", "state": the request's state,
    "cancelled": whether a stop request ended it}."""
    if status not in ("ok", "failed") or (status == "failed") != (failure is not None):
        raise StoreError("status is ok, or failed with the kind of failure", EXIT_USAGE)
    if failure is not None and failure not in RUN_FAILURES:
        raise StoreError(f"failure must be one of {', '.join(RUN_FAILURES)}", EXIT_USAGE)
    error = text_arg(error, "error", NOTE_MAX, multiline=True, required=False)
    run_dir = text_arg(run_dir, "run_dir", PATH_MAX, required=False)
    image_digest = text_arg(image_digest, "image_digest", REF_MAX, required=False)
    loaded = None if skill_loaded is None else (1 if skill_loaded else 0)
    if redactions is not None and (isinstance(redactions, bool) or not isinstance(redactions, int) or redactions < 0):
        raise StoreError("redactions is a count: a whole number, 0 or more", EXIT_USAGE)
    now = iso(utcnow())
    with write(conn):
        row = conn.execute("SELECT task_id, status FROM task_runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            raise StoreError(f"no task run {run_id}")
        if row["status"] != "running":
            raise StoreError(f"task run {run_id} already ended with status {row['status']}")
        request = _request(conn, row["task_id"])
        stop = stop_of(conn, request["id"])
        if stop is not None:
            _end_stopped_run(conn, run_id, stop, now, {
                "attempts": int(attempts), "cost_usd": cost_usd, "tokens": tokens, "duration_ms": duration_ms,
                "skill_loaded": loaded, "image_digest": image_digest, "run_dir": run_dir, "redactions": redactions})
            _complete_cancel(conn, request["id"], now)
            return {"run_id": run_id, "request_id": request["id"], "state": _request(conn, request["id"])["state"], "cancelled": True}
        if status == "ok" and request["state"] != "requested":
            raise StoreError(f"request {request['id']} is {request['state']}: the answer is not recorded")
        conn.execute(
            "UPDATE task_runs SET status = ?, failure = ?, ending = ?, attempts = ?, ended_at = ?, cost_usd = ?, "
            "tokens = ?, duration_ms = ?, skill_loaded = ?, image_digest = ?, run_dir = ?, error = ?, redactions = ? "
            "WHERE id = ?",
            (status, failure, "done" if status == "ok" else None, int(attempts), now, cost_usd, tokens, duration_ms, loaded,
             image_digest, run_dir, error, redactions, run_id))
        if status == "ok":
            conn.execute("UPDATE tasks SET state = 'done', updated_at = ? WHERE id = ?", (now, request["id"]))
        else:
            _cancel_request(conn, request["id"], ANSWER_FAILED_BY, now)
        state = _request(conn, request["id"])["state"]
    return {"run_id": run_id, "request_id": request["id"], "state": state, "cancelled": False}


def plan_open(conn: sqlite3.Connection, request_id: int, *, title: str, body: str, payload: dict) -> dict:
    """Open a `plan` pending decision on a request without a run (the person named the flow). In the same
    transaction an open `question` of the request is cancelled. Refused when a plan or an acceptance is open on the
    request, or the request is not `requested`. Returns {"pending_id", "request_id", "cancelled": [pending ids]}."""
    item = _pending_item({"kind": "plan", "title": title, "body": body, "payload": payload})
    now = iso(utcnow())
    with write(conn):
        request = _request(conn, request_id)
        if request["state"] != "requested":
            raise StoreError(f"request {request_id} is {request['state']}: only a request waiting for its plan is planned")
        blocking = _open_pending(conn, request_id, ("plan", "acceptance"))
        if blocking:
            raise StoreError(f"request {request_id} has an open {blocking[0]['kind']} (pending decision "
                             f"{blocking[0]['id']}): decide it first")
        if conn.execute("SELECT 1 FROM task_runs WHERE task_id = ? AND status = 'running'", (request_id,)).fetchone():
            raise StoreError(f"the router is running on request {request_id}: wait for its run to end")
        cancelled = [p["id"] for p in _open_pending(conn, request_id, ("question",))]
        for pid in cancelled:
            conn.execute("UPDATE pending_decisions SET status = 'cancelled', resolved_at = ?, resolved_by = ? "
                         "WHERE id = ?", (now, "plan", pid))
        pending_id = conn.execute(
            "INSERT INTO pending_decisions (task_id, kind, title, body, payload, payload_sha256, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)", (request_id, *item, now)).lastrowid
    return {"pending_id": pending_id, "request_id": request_id, "cancelled": cancelled}


def plan_approve(conn: sqlite3.Connection, pending_id: int, *, by: str, waits: list | None = None,
                 go_ahead=(), actor: str | None = None) -> dict:
    """Approve a `plan`: the tasks of its payload["tasks"] are created as request_add creates a plan's tasks, the
    request takes the payload's flow (None for a plan of one skill) and becomes `planned`, and the tasks with no
    dependency and no open wait become `ready`. waits are the waits the tasks begin with (request_add reads them
    alike); the keys in go_ahead are the person's decision that no derived wait holds them.
    Returns {"request", "tasks": [{"id", "key", "skill", "state"}], "ready": [ids]}."""
    by = text_arg(by, "by", LABEL_MAX)
    actor = text_arg(actor, "actor", ACTOR_MAX, required=False)
    now = iso(utcnow())
    with write(conn):
        item = _open_of_kind(conn, pending_id, "plan")
        request = _request(conn, item["task_id"])
        if request["state"] != "requested":
            raise StoreError(f"request {request['id']} is {request['state']}: its plan is not approved now")
        payload = item["payload"] or {}
        flow = text_arg(payload.get("flow"), "flow", LABEL_MAX, required=False)
        plan = _plan_items(payload.get("tasks"), empty_text=True)
        if not plan or (flow is None and len(plan) != 1):
            raise StoreError("a plan holds at least one task, and a plan of several tasks names its flow", EXIT_USAGE)
        _resolve(conn, pending_id, "approved", by, now, None, actor)
        conn.execute("UPDATE tasks SET flow = ?, state = 'planned', updated_at = ? WHERE id = ?",
                     (flow, now, request["id"]))
        ids = _insert_plan(conn, request["id"], flow, plan, now)
        _insert_waits(conn, request["id"], dict(zip([p["key"] for p in plan], ids)), waits or [], now, tuple(go_ahead))
        ready, _completed = _refresh(conn, now)
        rows = conn.execute("SELECT id, key, skill, state FROM tasks WHERE parent_id = ? ORDER BY id",
                            (request["id"],)).fetchall()
    return {"request": request["id"], "tasks": [row_dict(r) for r in rows], "ready": ready}


def plan_reject(conn: sqlite3.Connection, pending_id: int, *, by: str, note: str | None = None, actor: str | None = None) -> dict:
    """Reject a `plan`: it is resolved `rejected` (the note kept as its answer) and the request is cancelled as
    request_cancel cancels it. Returns {"pending_id", "request", "cancelled", "pending"}."""
    by = text_arg(by, "by", LABEL_MAX)
    actor = text_arg(actor, "actor", ACTOR_MAX, required=False)
    note = text_arg(note, "note", NOTE_MAX, multiline=True, required=False)
    now = iso(utcnow())
    with write(conn):
        item = _open_of_kind(conn, pending_id, "plan")
        _resolve(conn, pending_id, "rejected", by, now, note, actor)
        out = _cancel_request(conn, item["task_id"], by, now)
    return {"pending_id": pending_id, **out}


def request_after_set(conn: sqlite3.Connection, request_id: int, after: int | None) -> dict:
    """Set, or with None clear, the request this one waits for (the override "after request #n"): the column
    `after_request` of a request. The waits themselves are derived from it by the runtime (waits_sync). Refused for a
    task, for a request that is not named, and for a request that is done or cancelled. Returns the request."""
    now = iso(utcnow())
    with write(conn):
        request = _request(conn, request_id)
        if request["state"] in TASK_FINAL_STATES:
            raise StoreError(f"request {request_id} is {request['state']}: it waits for nothing now")
        target = _check_after(conn, request_id, after)
        conn.execute("UPDATE tasks SET after_request = ?, updated_at = ? WHERE id = ?", (target, now, request_id))
        return _task(conn, request_id)


def waits_go_ahead(conn: sqlite3.Connection, task_id: int, *, by: str, after: bool = False) -> dict:
    """The person's go-ahead on a task that is waiting: its open `input` waits end as `dropped` (the plan's go-ahead, on a
    task already created). A dropped wait is the decision about that path and that awaited task: the runtime derives it
    no more, and a new writer or another path is a new wait. With after, the one `after` wait of the task is what ends
    (the override is the person's own, so only they drop it, and only for this task). Refused for a task that is not
    planned or ready, and for one with no open wait of that kind. The store then refreshes: a task with no open wait left
    becomes ready. Returns {"task_id", "dropped": [wait ids], "paths", "reasons", "state", "ready": [ids]}."""
    by = text_arg(by, "by", LABEL_MAX)
    kind = "after" if after else "input"
    now = iso(utcnow())
    with write(conn):
        task = _task(conn, task_id)
        if task["parent_id"] is None or task["state"] not in ("planned", "ready"):
            raise StoreError(f"task {task_id} is {task['state'] if task['parent_id'] is not None else 'a request'}: "
                             "go ahead is said on a planned or ready task that waits")
        held = conn.execute("SELECT id, path, reason FROM task_waits WHERE task_id = ? AND status = 'open' "
                            "AND kind = ? ORDER BY id", (task_id, kind)).fetchall()
        if not held:
            raise StoreError(f"task {task_id} waits for no request it was told to follow" if after else
                             f"task {task_id} waits for no task to derive: go ahead drops a derived wait, and an "
                             "`after` request is the person's own (drop it with the after option)")
        for w in held:
            conn.execute("UPDATE task_waits SET status = 'dropped', ended_at = ?, ended_by = ? WHERE id = ?",
                         (now, by, w["id"]))
        ready, _completed = _refresh(conn, now)
        state = _task(conn, task_id)["state"]
    return {"task_id": task_id, "dropped": [w["id"] for w in held], "paths": [w["path"] for w in held],
            "reasons": [w["reason"] for w in held], "state": state, "ready": ready}


def waits_list(conn: sqlite3.Connection, *, task_id: int | None = None, status: str = "open") -> list:
    """The waits of one status (or "all"), oldest first; with task_id, those of one task. Each row is
    task_waits' columns and "request_id", the request of the awaited row (the awaited row itself for an `after`)."""
    if status not in (*WAIT_STATUSES, "all"):
        raise StoreError(f"status must be one of {', '.join(WAIT_STATUSES)} or all", EXIT_USAGE)
    rows = conn.execute(
        "SELECT w.*, COALESCE(a.parent_id, a.id) AS request_id FROM task_waits w JOIN tasks a ON a.id = w.awaited_id "
        "WHERE (?1 = 'all' OR w.status = ?1) AND (?2 IS NULL OR w.task_id = ?2) ORDER BY w.id", (status, task_id))
    return [row_dict(r) for r in rows]


def waits_sync(conn: sqlite3.Connection, desired: list, evaluated: list, *, by: str = "runtime") -> dict:
    """Bring the open waits of the evaluated tasks to the desired ones, in one transaction. desired is
    [{"task_id", "awaited_id", "kind": input|after, "path", "reason"}] as the runtime derived them (runtime/plan.py,
    derive); evaluated is the ids of every task it derived for. Of the evaluated tasks only the planned and the ready
    ones are touched. An open wait that is no longer desired is cleared; a desired one that is not open is opened,
    unless the person dropped that very wait (same task, awaited task and path); a ready task that gained a wait goes back to
    `planned`; then the store refreshes what became free. Returns {"opened": [wait ids], "cleared": [wait ids],
    "demoted": [task ids], "ready": [task ids]}."""
    by = text_arg(by, "by", LABEL_MAX)
    now = iso(utcnow())
    for d in desired:
        if not isinstance(d, dict) or d.get("kind") not in ("input", "after") or \
                any(isinstance(d.get(k), bool) or not isinstance(d.get(k), int) for k in ("task_id", "awaited_id")):
            raise StoreError("a desired wait is {task_id, awaited_id, kind input or after, path, reason}", EXIT_USAGE)
    with write(conn):
        live = {}
        for task_id in dict.fromkeys(evaluated):
            row = conn.execute("SELECT state, parent_id FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if row is not None and row["parent_id"] is not None and row["state"] in ("planned", "ready"):
                live[task_id] = row["state"]
        dropped = {(r["task_id"], r["awaited_id"], r["kind"], r["path"])
                   for r in conn.execute("SELECT task_id, awaited_id, kind, path FROM task_waits WHERE status = 'dropped'")}
        wanted = {}
        for d in desired:
            key = (d["task_id"], d["awaited_id"], d["kind"], d.get("path"))
            if d["task_id"] in live and key not in dropped:  # the person went ahead on this very wait
                wanted[key] = d
        kept, cleared, opened, gained = set(), [], [], []
        for r in conn.execute("SELECT id, task_id, awaited_id, kind, path FROM task_waits WHERE status = 'open' "
                              "ORDER BY id").fetchall():
            if r["task_id"] not in live:
                continue
            key = (r["task_id"], r["awaited_id"], r["kind"], r["path"])
            if key in wanted and key not in kept:
                kept.add(key)
                continue
            conn.execute("UPDATE task_waits SET status = 'cleared', ended_at = ?, ended_by = ? WHERE id = ?",
                         (now, by, r["id"]))
            cleared.append(r["id"])
        for key, d in wanted.items():
            if key in kept:
                continue
            awaited = conn.execute("SELECT parent_id FROM tasks WHERE id = ?", (d["awaited_id"],)).fetchone()
            if awaited is None or d["awaited_id"] == d["task_id"] or (d["kind"] == "after") != (awaited["parent_id"] is None):
                raise StoreError(f"task {d['task_id']}: a wait names another task, or for after a request", EXIT_USAGE)
            path = _rel_path(d["path"]) if d["kind"] == "input" else None
            opened.append(conn.execute(
                "INSERT INTO task_waits (task_id, awaited_id, kind, path, reason, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (d["task_id"], d["awaited_id"], d["kind"], path, text_arg(d.get("reason"), "reason", NOTE_MAX),
                 now)).lastrowid)
            gained.append(d["task_id"])
        demoted = [t for t in dict.fromkeys(gained) if live[t] == "ready" and conn.execute(
            "UPDATE tasks SET state = 'planned', updated_at = ? WHERE id = ? AND state = 'ready'", (now, t)).rowcount]
        ready, _completed = _refresh(conn, now)
    return {"opened": opened, "cleared": cleared, "demoted": demoted, "ready": ready}


def document_get(conn: sqlite3.Connection, path: str):
    """The record of a mirrored document by its path relative to the project, or None."""
    row = conn.execute("SELECT * FROM document_records WHERE path = ?", (_rel_path(path),)).fetchone()
    return row_dict(row) if row else None


def documents_list(conn: sqlite3.Connection) -> list:
    """Every document record, by path."""
    return [row_dict(r) for r in conn.execute("SELECT * FROM document_records ORDER BY path")]


def document_put(conn: sqlite3.Connection, path: str, *, provider: str, **fields) -> dict:
    """Create or update the record of a path: only the fields given change (of remote_id, written_sha256,
    remote_version, read_sha256, status, note), updated_at always. Returns the record."""
    path = _rel_path(path)
    provider = text_arg(provider, "provider", LABEL_MAX)
    unknown = sorted(set(fields) - set(DOCUMENT_FIELDS))
    if unknown:
        raise StoreError(f"a document record has no field {', '.join(unknown)}", EXIT_USAGE)
    for key in ("written_sha256", "read_sha256"):
        if key in fields:
            _sha_or_none(fields[key], key)
    for key in ("remote_id", "remote_version"):
        if key in fields:
            text_arg(fields[key], key, REF_MAX, required=False)
    if "status" in fields and fields["status"] not in DOCUMENT_STATUSES:
        raise StoreError(f"a document's status is one of {', '.join(DOCUMENT_STATUSES)}", EXIT_USAGE)
    if "note" in fields:
        text_arg(fields["note"], "note", NOTE_MAX, multiline=True, required=False)
    now = iso(utcnow())
    with write(conn):
        if conn.execute("SELECT 1 FROM document_records WHERE path = ?", (path,)).fetchone() is None:
            conn.execute("INSERT INTO document_records (path, provider, updated_at) VALUES (?, ?, ?)",
                         (path, provider, now))
        conn.execute("UPDATE document_records SET provider = ?, updated_at = ? WHERE path = ?", (provider, now, path))
        for key in DOCUMENT_FIELDS:
            if key in fields:
                conn.execute(DOCUMENT_UPDATES[key], (fields[key], path))
        return row_dict(conn.execute("SELECT * FROM document_records WHERE path = ?", (path,)).fetchone())


def comments_save(conn: sqlite3.Connection, comments, *, provider: str, subject: str, task_id: int | None = None,
                  document_path: str | None = None) -> dict:
    """Save open comments read from a platform before a page or an item is replaced: each {"id", "author",
    "created_at", "text"} not stored yet (by provider and id) is inserted `open`. A comment of a task names the
    task; one of a document names its path. Returns {"saved": n}."""
    provider = text_arg(provider, "provider", LABEL_MAX)
    if subject not in COMMENT_SUBJECTS:
        raise StoreError(f"a comment's subject is one of {', '.join(COMMENT_SUBJECTS)}", EXIT_USAGE)
    if (subject == "task") != (task_id is not None) or (subject == "document") != (document_path is not None):
        raise StoreError("a comment of a task names the task; one of a document names its path", EXIT_USAGE)
    document_path = _rel_path(document_path) if document_path is not None else None
    if not isinstance(comments, list):
        raise StoreError("comments are a list", EXIT_USAGE)
    items = []
    for c in comments:
        if not isinstance(c, dict):
            raise StoreError("a comment is an object", EXIT_USAGE)
        items.append((text_arg(c.get("id"), "id", REF_MAX), text_arg(c.get("author"), "author", LABEL_MAX, required=False),
                      text_arg(c.get("created_at"), "created_at", LABEL_MAX, required=False),
                      text_arg(c.get("text"), "text", TEXT_MAX, multiline=True)))
    now = iso(utcnow())
    saved = 0
    with write(conn):
        if task_id is not None:
            _task(conn, task_id)
        for remote_id, author, created_at, text in items:
            saved += conn.execute(
                "INSERT OR IGNORE INTO platform_comments (provider, remote_id, subject, task_id, document_path, author, "
                "text, created_at, saved_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (provider, remote_id, subject, task_id, document_path, author, text, created_at, now)).rowcount
    return {"saved": saved}


def comments_list(conn: sqlite3.Connection, *, status: str = "open", task_id: int | None = None,
                  document_path: str | None = None) -> list:
    """Saved comments of one status (or "all"), oldest first; with task_id or document_path, those of it."""
    if status not in (*COMMENT_STATUSES, "all"):
        raise StoreError(f"status must be one of {', '.join(COMMENT_STATUSES)} or all", EXIT_USAGE)
    rows = conn.execute("SELECT * FROM platform_comments WHERE (?1 = 'all' OR status = ?1) AND (?2 IS NULL OR task_id = ?2) "
                        "AND (?3 IS NULL OR document_path = ?3) ORDER BY id", (status, task_id, document_path)).fetchall()
    return [row_dict(r) for r in rows]


def comments_use(conn: sqlite3.Connection, ids, *, pending_id: int) -> dict:
    """Mark open comments `used` by one pending decision (their text entered the person's answer), all or none.
    Returns {"used": [ids], "pending_id"}."""
    if not isinstance(ids, list) or not ids or not all(isinstance(i, int) and not isinstance(i, bool) for i in ids):
        raise StoreError("ids are a non-empty list of comment ids", EXIT_USAGE)
    with write(conn):
        if conn.execute("SELECT 1 FROM pending_decisions WHERE id = ?", (pending_id,)).fetchone() is None:
            raise StoreError(f"no pending decision {pending_id}")
        for comment_id in ids:
            row = conn.execute("SELECT status FROM platform_comments WHERE id = ?", (comment_id,)).fetchone()
            if row is None or row["status"] != "open":
                raise StoreError(f"comment {comment_id} is {'missing' if row is None else row['status']}, not open")
            conn.execute("UPDATE platform_comments SET status = 'used', used_by_pending = ? WHERE id = ?",
                         (pending_id, comment_id))
    return {"used": list(ids), "pending_id": pending_id}


# --- migration 5: the approvals table (limits L13, L17) ----------------------------------------------------------
#
# An approval of the scope `action` binds one open `effect` by the hash of its exact content and waits for code to
# execute it (`pending-execution`, then `executed` through effect_done); `plan` binds one hash of a batch (first
# written in stage 10); `standing` is a policy with bounds and an expiry (`active`, first written in stage 6). A
# row is never deleted, its content never changes, and its status only moves forward (APPROVAL_MOVES; the
# migration's triggers refuse anything else at the database too).


def _approval(conn: sqlite3.Connection, approval_id: int) -> dict:
    row = conn.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,)).fetchone()
    if row is None:
        raise StoreError(f"no approval {approval_id}")
    return row_dict(row, ("bounds",))


def _approval_move(conn: sqlite3.Connection, approval_id: int, status: str, now: str) -> dict:
    """Inside a transaction: move one approval's status forward, or refuse (limit L13)."""
    item = _approval(conn, approval_id)
    if status not in APPROVAL_MOVES.get(item["status"], ()):
        raise StoreError(f"approval {approval_id} is {item['status']}: it cannot become {status} (an approval only "
                         "moves forward, and is never deleted)")
    if status == "executed":
        conn.execute("UPDATE approvals SET status = ?, executed_at = ? WHERE id = ?", (status, now, approval_id))
    else:
        conn.execute("UPDATE approvals SET status = ? WHERE id = ?", (status, approval_id))
    return _approval(conn, approval_id)


def _revoke_pending_execution(conn: sqlite3.Connection, pending_id: int, now: str) -> None:
    """Inside a transaction: revoke the approvals still waiting to be executed for one pending decision."""
    for row in conn.execute("SELECT id FROM approvals WHERE pending_id = ? AND status = 'pending-execution' ORDER BY id",
                            (pending_id,)).fetchall():
        _approval_move(conn, row["id"], "revoked", now)


def approval_add(conn: sqlite3.Connection, *, scope: str, what: str, by: str, payload_sha256: str | None = None,
                 policy_sha256: str | None = None, bounds: dict | None = None, task_id: int | None = None,
                 pending_id: int | None = None, expires_at: str | None = None, actor: str | None = None) -> dict:
    """Record an approval, in one transaction. Returns the row, with "existing": true or false. `actor` (POL-2) is who approved, kept beside `by`.

    action    payload_sha256 and pending_id are required; the pending decision must be open, of kind `effect`, with
              the same payload_sha256; the row is `pending-execution` and its task is the pending decision's. When a
              `pending-execution` row already exists for that pending decision and hash, that row is returned and
              nothing is inserted (approving twice is one approval)
    plan      payload_sha256 is required; `pending-execution`
    standing  bounds (a JSON object) and expires_at (ISO-8601) are required; policy_sha256 is the hash of the bounds
              file; `active`"""
    if scope not in APPROVAL_SCOPES:
        raise StoreError(f"scope must be one of {', '.join(APPROVAL_SCOPES)}", EXIT_USAGE)
    what = text_arg(what, "what", TITLE_MAX)
    by = text_arg(by, "by", LABEL_MAX)
    actor = text_arg(actor, "actor", ACTOR_MAX, required=False)
    _sha_or_none(payload_sha256, "payload_sha256")
    _sha_or_none(policy_sha256, "policy_sha256")
    if scope in ("action", "plan") and payload_sha256 is None:
        raise StoreError(f"an approval of scope {scope} needs payload_sha256", EXIT_USAGE)
    if scope == "action" and pending_id is None:
        raise StoreError("an approval of scope action needs pending_id", EXIT_USAGE)
    if scope == "standing":
        if not isinstance(bounds, dict) or expires_at is None:
            raise StoreError("an approval of scope standing needs bounds (an object) and expires_at", EXIT_USAGE)
    elif bounds is not None:
        raise StoreError(f"an approval of scope {scope} has no bounds", EXIT_USAGE)
    expires = since_arg(expires_at, "expires_at") if expires_at is not None else None
    bounds_text = json.dumps(bounds, ensure_ascii=True, sort_keys=True) if bounds is not None else None
    now = iso(utcnow())
    with write(conn):
        if scope == "action":
            item = conn.execute("SELECT task_id, kind, status, payload_sha256 FROM pending_decisions WHERE id = ?",
                                (pending_id,)).fetchone()
            if item is None:
                raise StoreError(f"no pending decision {pending_id}")
            if item["kind"] != "effect" or item["status"] != "open":
                raise StoreError(f"pending decision {pending_id} is a {item['status']} {item['kind']}: an action is "
                                 "approved only on an open effect")
            if item["payload_sha256"] != payload_sha256:
                raise StoreError(f"pending decision {pending_id} has the hash {item['payload_sha256']}, not "
                                 f"{payload_sha256}: nothing was approved")
            if task_id is not None and task_id != item["task_id"]:
                raise StoreError(f"pending decision {pending_id} belongs to task {item['task_id']}, not {task_id}")
            task_id = item["task_id"]
            found = conn.execute("SELECT id FROM approvals WHERE pending_id = ? AND payload_sha256 = ? "
                                 "AND status = 'pending-execution' ORDER BY id LIMIT 1",
                                 (pending_id, payload_sha256)).fetchone()
            if found is not None:
                return {**_approval(conn, found["id"]), "existing": True}
        elif pending_id is not None:
            _open_of_kind(conn, pending_id, "plan" if scope == "plan" else "effect")
        if task_id is not None:
            _task(conn, task_id)
        status = "active" if scope == "standing" else "pending-execution"
        approval_id = conn.execute(
            "INSERT INTO approvals (scope, what, payload_sha256, policy_sha256, bounds, task_id, pending_id, "
            "approved_at, approved_by, expires_at, status, actor) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (scope, what, payload_sha256, policy_sha256, bounds_text, task_id, pending_id, now, by, expires,
             status, actor)).lastrowid
        return {**_approval(conn, approval_id), "existing": False}


def approval_standing_add(conn: sqlite3.Connection, *, what: str, by: str, policy_sha256: str, bounds: dict,
                          expires_at: str) -> dict:
    """A standing approval of one policy for one agent, in one transaction (stage 6): every `active` standing row
    whose bounds name the same "policy" and "agent" becomes `revoked`, and the new row is added `active`, as
    approval_add adds one. bounds must name both. Returns the new row, with "revoked": [the ids revoked]."""
    _sha_or_none(policy_sha256, "policy_sha256")
    if policy_sha256 is None:
        raise StoreError("a standing approval of a policy needs policy_sha256", EXIT_USAGE)
    if not isinstance(bounds, dict) or not isinstance(bounds.get("policy"), str) or not isinstance(bounds.get("agent"), str):
        raise StoreError("the bounds of a standing approval name its policy and its agent", EXIT_USAGE)
    what = text_arg(what, "what", TITLE_MAX)
    by = text_arg(by, "by", LABEL_MAX)
    expires = since_arg(expires_at, "expires_at")
    if expires is None:
        raise StoreError("a standing approval has an expiry", EXIT_USAGE)
    now = iso(utcnow())
    with write(conn):
        revoked = []
        for row in conn.execute("SELECT id, bounds FROM approvals WHERE scope = 'standing' AND status = 'active' "
                                "ORDER BY id").fetchall():
            earlier = json.loads(row["bounds"] or "{}")
            if (earlier.get("policy"), earlier.get("agent")) == (bounds["policy"], bounds["agent"]):
                _approval_move(conn, row["id"], "revoked", now)
                revoked.append(row["id"])
        approval_id = conn.execute(
            "INSERT INTO approvals (scope, what, policy_sha256, bounds, approved_at, approved_by, expires_at, status) "
            "VALUES ('standing', ?, ?, ?, ?, ?, ?, 'active')",
            (what, policy_sha256, json.dumps(bounds, ensure_ascii=True, sort_keys=True), now, by, expires)).lastrowid
        return {**_approval(conn, approval_id), "revoked": revoked}


def approval_get(conn: sqlite3.Connection, approval_id: int) -> dict:
    """One approval, with bounds as an object."""
    return _approval(conn, approval_id)


def approvals_list(conn: sqlite3.Connection, *, status: str | None = None, scope: str | None = None,
                   task_id: int | None = None) -> list:
    """Approvals, oldest first, filtered by status, scope and task when given."""
    if status is not None and status not in APPROVAL_STATUSES:
        raise StoreError(f"status must be one of {', '.join(APPROVAL_STATUSES)}", EXIT_USAGE)
    if scope is not None and scope not in APPROVAL_SCOPES:
        raise StoreError(f"scope must be one of {', '.join(APPROVAL_SCOPES)}", EXIT_USAGE)
    rows = conn.execute("SELECT * FROM approvals WHERE (?1 IS NULL OR status = ?1) AND (?2 IS NULL OR scope = ?2) "
                        "AND (?3 IS NULL OR task_id = ?3) ORDER BY id", (status, scope, task_id)).fetchall()
    return [row_dict(r, ("bounds",)) for r in rows]


def approvals_expire(conn: sqlite3.Connection, now: str) -> int:
    """Turn every `active` approval whose expires_at is before now (ISO-8601) into `expired`, in one transaction;
    returns how many. Stage 6's poll calls it; nothing in stage 4 does."""
    now = since_arg(now, "now")
    with write(conn):
        ids = [r["id"] for r in conn.execute("SELECT id FROM approvals WHERE status = 'active' AND expires_at < ? "
                                             "ORDER BY id", (now,)).fetchall()]
        for approval_id in ids:
            _approval_move(conn, approval_id, "expired", now)
    return len(ids)


def approval_revoke(conn: sqlite3.Connection, approval_id: int, *, by: str) -> dict:
    """Revoke an approval that is `pending-execution` or `active`, in one transaction; anything else is refused.
    The table keeps no column for who revoked: by is checked and returned. Returns the row, with "revoked_by"."""
    by = text_arg(by, "by", LABEL_MAX)
    now = iso(utcnow())
    with write(conn):
        return {**_approval_move(conn, approval_id, "revoked", now), "revoked_by": by}


def effect_done(conn: sqlite3.Connection, pending_id: int, approval_id: int, *, by: str, result: dict, actor: str | None = None) -> dict:
    """After code executed an effect, all or nothing: the pending decision is resolved `approved`, with result kept
    under "result" of its payload; the approval is `executed`, with executed_at; the task goes from `waiting` to
    `done`; the tasks that depended on it become ready and a request whose tasks are all done completes, as for the
    resolution `released`. Refused for a pending decision that is not an open effect, and for an approval that is
    not `pending-execution` or belongs to another pending decision. Returns {"pending_id", "approval_id", "task_id",
    "task_state", "ready", "completed"}."""
    by = text_arg(by, "by", LABEL_MAX)
    actor = text_arg(actor, "actor", ACTOR_MAX, required=False)
    if not isinstance(result, dict):
        raise StoreError("the result of an effect is an object", EXIT_USAGE)
    now = iso(utcnow())
    with write(conn):
        item = _open_of_kind(conn, pending_id, "effect")
        approval = _approval(conn, approval_id)
        if approval["pending_id"] != pending_id or approval["scope"] != "action":
            raise StoreError(f"approval {approval_id} is not the approval of pending decision {pending_id}")
        if approval["payload_sha256"] != item["payload_sha256"]:
            raise StoreError(f"approval {approval_id} approved another hash than pending decision {pending_id}'s")
        _approval_move(conn, approval_id, "executed", now)
        payload = dict(item["payload"] or {}, result=result)
        conn.execute("UPDATE pending_decisions SET status = 'resolved', resolution = 'approved', payload = ?, "
                     "resolved_at = ?, resolved_by = ?, actor = ? WHERE id = ?",
                     (json.dumps(payload, ensure_ascii=True, sort_keys=True), now, by, actor, pending_id))
        moved = conn.execute("UPDATE tasks SET state = 'done', updated_at = ? WHERE id = ? AND state = 'waiting'",
                             (now, item["task_id"])).rowcount
        if not moved:
            raise StoreError(f"task {item['task_id']} is not waiting: the effect's result is not recorded")
        ready, completed = _refresh(conn, now)
    return {"pending_id": pending_id, "approval_id": approval_id, "task_id": item["task_id"], "task_state": "done",
            "ready": ready, "completed": completed}


# --- migration 6: the conversation's messages; what the dispatcher and the planning agent need ---------------------
#
# conversation_messages keeps the conversation with the planning agent as given (a text is never interpreted). The
# functions after it let the dispatcher claim one named task, let a plan grow by sub-tasks after its approval, and
# count a period's runs and a day's actions in process (action_add and action_count do the verbs' work, through the
# same internal code).

MESSAGE_ROLES = ("user", "assistant")
MESSAGES_LIMIT = (50, 1, 500)  # default, min, max


def message_add(conn: sqlite3.Connection, *, conversation: str, role: str, text: str, task_id: int | None = None,
                run_id: int | None = None) -> dict:
    """Record one message of a conversation, stored as given. role is `user` or `assistant`. Returns {"id",
    "conversation", "role", "created_at"}."""
    if role not in MESSAGE_ROLES:
        raise StoreError(f"role must be one of {', '.join(MESSAGE_ROLES)}", EXIT_USAGE)
    conversation = text_arg(conversation, "conversation", LABEL_MAX)
    text = text_arg(text, "text", TEXT_MAX, multiline=True)
    now = iso(utcnow())
    with write(conn):
        if task_id is not None:
            _task(conn, task_id)
        if run_id is not None and conn.execute("SELECT 1 FROM task_runs WHERE id = ?", (run_id,)).fetchone() is None:
            raise StoreError(f"no task run {run_id}")
        message_id = conn.execute(
            "INSERT INTO conversation_messages (conversation, role, text, task_id, run_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)", (conversation, role, text, task_id, run_id, now)).lastrowid
    return {"id": message_id, "conversation": conversation, "role": role, "created_at": now}


def messages_list(conn: sqlite3.Connection, conversation: str, *, limit: int = MESSAGES_LIMIT[0],
                  after_id: int | None = None) -> list:
    """The newest `limit` messages of a conversation whose id is above after_id, returned oldest first."""
    conversation = text_arg(conversation, "conversation", LABEL_MAX)
    _default, low, high = MESSAGES_LIMIT
    if isinstance(limit, bool) or not isinstance(limit, int) or not low <= limit <= high:
        raise StoreError(f"limit must be between {low} and {high}", EXIT_USAGE)
    rows = conn.execute("SELECT * FROM conversation_messages WHERE conversation = ? AND (? IS NULL OR id > ?) "
                        "ORDER BY id DESC LIMIT ?", (conversation, after_id, after_id, limit)).fetchall()
    return [row_dict(r) for r in reversed(rows)]


def task_claim(conn: sqlite3.Connection, task_id: int) -> dict:
    """Give out one named `ready` task of a request as `running`. Other running tasks do not prevent it: what may run
    at once is decided by the caller under its claim lock (runtime/parallel.py). Returns {"task": the task}. A task that does
    not exist, or is not a `ready` task of a request, is not claimed: task is None and "reason" is `unknown` or
    `not-ready`; a task with an open wait is not claimed either (`waiting`)."""
    now = iso(utcnow())
    with write(conn):
        row = conn.execute("SELECT id, parent_id, state FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            return {"task": None, "reason": "unknown"}
        if row["state"] != "ready" or row["parent_id"] is None:
            return {"task": None, "reason": "not-ready"}
        if stop_of(conn, task_id) is not None:   # a stop request is on it or on its request: nothing new is claimed (R18)
            return {"task": None, "reason": "not-ready"}
        if conn.execute("SELECT 1 FROM task_waits WHERE task_id = ? AND status = 'open'", (task_id,)).fetchone():
            return {"task": None, "reason": "waiting"}
        conn.execute("UPDATE tasks SET state = 'running', updated_at = ? WHERE id = ? AND state = 'ready'",
                     (now, task_id))
        return {"task": _task(conn, task_id)}


def _tasks_add(conn: sqlite3.Connection, request_id: int, tasks, now: str, waits: list | None = None) -> dict:
    """Inside a transaction: tasks_add's work."""
    request = _request(conn, request_id)
    if request["state"] not in ("planned", "done"):
        raise StoreError(f"request {request_id} is {request['state']}: tasks are added to a planned or a done request")
    if request["stop_requested_at"]:
        raise StoreError(f"request {request_id} is being cancelled: tasks are not added to it")
    known = {r["key"]: r["id"] for r in conn.execute("SELECT id, key FROM tasks WHERE parent_id = ? ORDER BY id",
                                                       (request_id,)).fetchall() if r["key"] is not None}
    if isinstance(tasks, list):
        taken = [item.get("key") for item in tasks if isinstance(item, dict) and item.get("key") in known]
        if taken:
            raise StoreError(f"request {request_id} already has a task {taken[0]!r}: nothing was added", EXIT_USAGE)
    plan = _plan_items(tasks, known=tuple(known))
    if not plan:
        raise StoreError("tasks_add adds at least one task", EXIT_USAGE)
    added = _insert_plan(conn, request_id, request["flow"], plan, now, known)
    _insert_waits(conn, request_id, dict(zip([p["key"] for p in plan], added)), waits or [], now)
    conn.execute("UPDATE tasks SET state = 'planned', updated_at = ? WHERE id = ?", (now, request_id))
    _refresh(conn, now)
    rows = [conn.execute("SELECT id, key, skill, agent, state FROM tasks WHERE id = ?", (task_id,)).fetchone()
            for task_id in added]
    return {"request": request_id, "tasks": [row_dict(r) for r in rows]}


def tasks_add(conn: sqlite3.Connection, request_id: int, tasks, waits: list | None = None) -> dict:
    """Add tasks to a request that is `planned` or `done` (a done request gets work again and is `planned`). Each item
    is {"key", "skill", "title", "text", "depends_on": [keys], "milestone"[, "agent"]}; a dependency names a task the
    request already has, or one earlier in this call. A key the request already has, or an unknown dependency, adds
    nothing. A new task whose dependencies are all done (or that has none) and that has no open wait (waits, as
    request_add reads them) is `ready`, else `planned`. Returns
    {"request", "tasks": [{"id", "key", "skill", "agent", "state"}]}."""
    now = iso(utcnow())
    with write(conn):
        return _tasks_add(conn, request_id, tasks, now, waits)


RUNS_SINCE = ("SELECT r.id, r.task_id, COALESCE(t.parent_id, t.id) AS request_id, t.agent, r.skill, r.model, "
              "r.adapter, r.status, r.failure, r.attempts, r.tokens, r.cost_usd, r.billing, r.started_at, r.ended_at FROM task_runs r "
              "JOIN tasks t ON t.id = r.task_id WHERE r.started_at >= ? AND (? IS NULL OR t.agent = ?) ORDER BY r.id")


def runs_since(conn: sqlite3.Connection, since: str, *, agent: str | None = None) -> list:
    """The runs started at or after since (ISO-8601), oldest first, each with the agent of its task and its request:
    {"id", "task_id", "request_id", "agent", "skill", "model", "adapter", "status", "failure", "attempts" (the attempts that
    began: 0 when none did), "tokens" (None when not reported), "cost_usd", "billing" (None for a run older than migration 9), "started_at", "ended_at"}. A run
    of the router belongs to its request, whose agent is None. With agent, only the runs of that agent's tasks."""
    since = since_arg(since, "since")
    agent = text_arg(agent, "agent", LABEL_MAX, required=False)
    return [row_dict(r) for r in conn.execute(RUNS_SINCE, (since, agent, agent)).fetchall()]


def action_add(conn: sqlite3.Connection, *, kind: str, idempotency_key: str, target: str, payload_sha256: str,
               result) -> dict:
    """The verb action-add, in process: the same checks and the same internal code. result is an object, or its
    JSON text. Returns {"id", "created", "created_at"}."""
    kind = text_arg(kind, "kind", LABEL_MAX)
    key = text_arg(idempotency_key, "idempotency_key", REF_MAX)
    target = text_arg(target, "target", REF_MAX)
    digest = sha_arg(payload_sha256)
    if isinstance(result, str):
        try:
            json.loads(result, parse_constant=reject_constant)
        except ValueError as exc:
            raise StoreError(f"result: not JSON ({exc})", EXIT_USAGE) from None
        text = result
    else:
        try:
            text = json.dumps(result, ensure_ascii=True, sort_keys=True, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise StoreError(f"result: not JSON ({exc})", EXIT_USAGE) from None
    if len(text.encode("utf-8")) > PAYLOAD_MAX:
        raise StoreError(f"result is over the cap of {PAYLOAD_MAX} bytes", EXIT_USAGE)
    return _action_write(conn, kind, key, target, digest, text)


def action_count(conn: sqlite3.Connection, *, kind: str, since: str) -> int:
    """The verb action-count, in process: how many actions of a kind were recorded at or after since (ISO-8601)."""
    kind = text_arg(kind, "kind", LABEL_MAX)
    since = since_arg(since, "since")
    if since is None:
        raise StoreError("since is required", EXIT_USAGE)
    return _action_count(conn, kind, since)


def acceptance_open(conn: sqlite3.Connection, *, task_id: int, what: str, title: str, body: str, payload: dict) -> dict:
    """Open a pending decision of kind `acceptance` on a request that is not cancelled, with payload["what"] set to
    what (`subtasks` or `deliveries`). The request's state does not change. Returns {"pending_id", "task_id"}."""
    if what not in ACCEPTANCE_WHATS:
        raise StoreError(f"what must be one of {', '.join(ACCEPTANCE_WHATS)}", EXIT_USAGE)
    if not isinstance(payload, dict):
        raise StoreError("an acceptance's payload is an object", EXIT_USAGE)
    item = _pending_item({"kind": "acceptance", "title": title, "body": body, "payload": dict(payload, what=what)})
    now = iso(utcnow())
    with write(conn):
        request = _request(conn, task_id)
        if request["state"] == "cancelled":
            raise StoreError(f"request {task_id} is cancelled: nothing is accepted on it")
        pending_id = conn.execute(
            "INSERT INTO pending_decisions (task_id, kind, title, body, payload, payload_sha256, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)", (task_id, *item, now)).lastrowid
    return {"pending_id": pending_id, "task_id": task_id}


def task_runs_of_skill(conn: sqlite3.Connection, skill: str) -> list:
    """Every run of one skill in this database, oldest first: what a plan's estimate counts."""
    skill = text_arg(skill, "skill", LABEL_MAX)
    return [row_dict(r) for r in conn.execute("SELECT * FROM task_runs WHERE skill = ? ORDER BY id", (skill,))]


def cursor_get(conn: sqlite3.Connection, name: str) -> str | None:
    """The value of a cursor, or None when there is no such cursor: the cursor-get verb, in process."""
    name = text_arg(name, "name", LABEL_MAX)
    with write(conn):
        row = conn.execute("SELECT value FROM cursors WHERE name = ?", (name,)).fetchone()
    return row["value"] if row else None


def cursor_peek(conn: sqlite3.Connection, name: str) -> str | None:
    """The value of a cursor as cursor_get reads it, with one plain SELECT and no transaction of its own: it takes no write
    lock, so it never queues behind a writer and works on a store opened read-only. For a reader that asks every second."""
    name = text_arg(name, "name", LABEL_MAX)
    row = conn.execute("SELECT value FROM cursors WHERE name = ?", (name,)).fetchone()
    return row["value"] if row else None


def cursor_set(conn: sqlite3.Connection, name: str, value: str) -> dict:
    """Insert or replace a cursor: the cursor-set verb, in process, with the same limits. Returns {"name",
    "value", "updated_at"}."""
    name = text_arg(name, "name", LABEL_MAX)
    value = text_arg(value, "value", VALUE_MAX)
    now = iso(utcnow())
    with write(conn):
        conn.execute("INSERT INTO cursors (name, value, updated_at) VALUES (?, ?, ?) "
                     "ON CONFLICT (name) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
                     (name, value, now))
    return {"name": name, "value": value, "updated_at": now}


def task_get(conn: sqlite3.Connection, task_id: int) -> dict:
    """One task, with depends_on as a list of task ids."""
    return _task(conn, task_id)


def tasks_list(conn: sqlite3.Connection, request: int | None = None) -> list:
    """Every task, oldest first; with request, that request and its tasks."""
    rows = conn.execute("SELECT * FROM tasks WHERE (?1 IS NULL OR id = ?1 OR parent_id = ?1) ORDER BY id",
                        (request,)).fetchall()
    return [row_dict(r, TASK_JSON) for r in rows]


def task_run_get(conn: sqlite3.Connection, run_id: int) -> dict:
    """One row of task_runs; StoreError when there is none."""
    row = conn.execute("SELECT * FROM task_runs WHERE id = ?", (run_id,)).fetchone()
    if row is None:
        raise StoreError(f"no task run {run_id}")
    return row_dict(row)


def task_runs_list(conn: sqlite3.Connection, task_id: int) -> list:
    """The runs of one task, oldest first."""
    return [row_dict(r) for r in conn.execute("SELECT * FROM task_runs WHERE task_id = ? ORDER BY id", (task_id,))]


def task_runs_running(conn: sqlite3.Connection) -> list:
    """Every run row in progress; a router run is the one whose task is a request. As {"id", "task_id", "skill",
    "started_at"}, oldest first: one query, whatever the number of tasks."""
    return [row_dict(r) for r in conn.execute(
        "SELECT id, task_id, skill, started_at FROM task_runs WHERE status = 'running' ORDER BY id")]


def pending_get(conn: sqlite3.Connection, pending_id: int) -> dict:
    """One pending decision, with its payload as an object."""
    row = conn.execute("SELECT * FROM pending_decisions WHERE id = ?", (pending_id,)).fetchone()
    if row is None:
        raise StoreError(f"no pending decision {pending_id}")
    return row_dict(row, ("payload",))


def pending_list(conn: sqlite3.Connection, status: str = "open", task_id: int | None = None) -> list:
    """Pending decisions of one status (or "all"), oldest first; with task_id, those of one task."""
    if status not in (*PENDING_STATUSES, "all"):
        raise StoreError(f"status must be one of {', '.join(PENDING_STATUSES)} or all", EXIT_USAGE)
    rows = conn.execute("SELECT * FROM pending_decisions WHERE (?1 = 'all' OR status = ?1) "
                        "AND (?2 IS NULL OR task_id = ?2) ORDER BY id", (status, task_id)).fetchall()
    return [row_dict(r, ("payload",)) for r in rows]


# --- entry point ------------------------------------------------------------------


VERBS = {
    "init": cmd_init, "cursor-get": cmd_cursor_get, "cursor-set": cmd_cursor_set,
    "cursor-clear": cmd_cursor_clear,
    "event-add": cmd_event_add, "event-next": cmd_event_next, "event-done": cmd_event_done,
    "run-start": cmd_run_start, "run-end": cmd_run_end, "runs": cmd_runs,
    "inbox-add": cmd_inbox_add, "inbox-list": cmd_inbox_list, "inbox-resolve": cmd_inbox_resolve,
    "action-add": cmd_action_add, "actions": cmd_actions, "action-count": cmd_action_count,
    "export": cmd_export,
}


# --- the sources of a project (migration 11; runtime/sources.py is the one caller) ------------------------------------------


def _source_row(conn: sqlite3.Connection, source_id: str):
    return conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()


# --- routines (P6b, migration 14) ---------------------------------------------------------------------------------------------
#
# A routine is a flow started by a schedule. The store keeps the record and the fires and knows no rule of the work: what a hash
# covers, when a slot is due and what a fire does are the runtime's (runtime/routines.py, runtime/ops_routines.py). Here: a draft
# becomes active only through routine_approve, with the sha256 the runtime computed; any change clears the approval; a fire is one row
# keyed by (routine, slot), written in the same transaction as the request it creates.

ROUTINE_STATES = ("draft", "active", "paused", "stopped", "cancelled")
ROUTINE_JSON = ("params", "schedule", "providers", "approved_content")
ROUTINE_FIELDS = ("flow", "params", "schedule", "model", "consent", "providers", "window_seconds")
FIRE_STATUSES = ("created", "asked", "skipped")
ROUTINE_NAME_RE = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")


def _routine_row(conn: sqlite3.Connection, routine_id) -> dict:
    row = conn.execute("SELECT * FROM routines WHERE id = ?", (routine_id,)).fetchone()
    if row is None:
        raise StoreError(f"no routine {routine_id}")
    return row_dict(row, ROUTINE_JSON)


def _routine_args(fields: dict) -> dict:
    out = {}
    if "flow" in fields:
        flow = text_arg(fields["flow"], "flow", LABEL_MAX)
        if not ROUTINE_NAME_RE.fullmatch(flow):
            raise StoreError("a routine's flow is the name of a flow", EXIT_USAGE)
        out["flow"] = flow
    for key in ("params", "schedule"):
        if key in fields:
            if not isinstance(fields[key], dict) or (key == "schedule" and not fields[key]):
                raise StoreError(f"a routine's {key} is an object", EXIT_USAGE)
            out[key] = json.dumps(fields[key], sort_keys=True, separators=(",", ":"))
    if "providers" in fields:
        if not isinstance(fields["providers"], list) or not all(isinstance(v, str) and v for v in fields["providers"]):
            raise StoreError("a routine's providers are a list of provider names", EXIT_USAGE)
        out["providers"] = json.dumps(sorted(set(fields["providers"])), separators=(",", ":"))
    if "model" in fields:
        out["model"] = _model_arg(fields["model"])
    if "consent" in fields:
        out["consent"] = 1 if fields["consent"] else 0
    if "window_seconds" in fields:
        window = fields["window_seconds"]
        if window is not None and (isinstance(window, bool) or not isinstance(window, int) or window < 60):
            raise StoreError("a routine's catch-up window is a whole number of seconds, at least 60", EXIT_USAGE)
        out["window_seconds"] = window
    if len(json.dumps(out)) > PAYLOAD_MAX:
        raise StoreError("a routine's record is over the cap", EXIT_USAGE)
    return out


def routine_add(conn: sqlite3.Connection, *, name: str, flow: str, params: dict, schedule: dict, model=None, consent=False,
                providers=(), window_seconds=None) -> dict:
    """Create a routine as a draft. The name is lowercase words joined by hyphens, once. Returns the row."""
    name = text_arg(name, "name", LABEL_MAX)
    if not ROUTINE_NAME_RE.fullmatch(name):
        raise StoreError("a routine's name is lowercase words joined by hyphens", EXIT_USAGE)
    args = _routine_args({"flow": flow, "params": params, "schedule": schedule, "model": model, "consent": consent,
                          "providers": list(providers), "window_seconds": window_seconds})
    now = iso(utcnow())
    with write(conn):
        if conn.execute("SELECT 1 FROM routines WHERE name = ?", (name,)).fetchone():
            raise StoreError(f"there is a routine named {name}", EXIT_USAGE)
        new = conn.execute(
            "INSERT INTO routines (name, flow, params, schedule, model, consent, providers, window_seconds, state, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?)",
            (name, args["flow"], args["params"], args["schedule"], args["model"], args["consent"], args["providers"],
             args["window_seconds"], now, now)).lastrowid
        return _routine_row(conn, new)


def routine_get(conn: sqlite3.Connection, routine_id: int) -> dict:
    return _routine_row(conn, routine_id)


def routines_list(conn: sqlite3.Connection) -> list:
    """Every routine, oldest first, each with its last fire ({"slot", "status", "reason", "request_id", "fired_at"} or None)."""
    out = []
    for row in conn.execute("SELECT * FROM routines ORDER BY id").fetchall():
        item = row_dict(row, ROUTINE_JSON)
        last = conn.execute("SELECT slot, status, reason, request_id, fired_at FROM routine_fires WHERE routine_id = ? "
                            "ORDER BY id DESC LIMIT 1", (item["id"],)).fetchone()
        item["last_fire"] = row_dict(last) if last else None
        out.append(item)
    return out


def routine_change(conn: sqlite3.Connection, routine_id: int, **fields) -> dict:
    """Change the fields of a routine (flow, params, schedule, model, consent, providers, window_seconds). The approval is cleared and the
    routine is a draft again: it fires nothing until the person approves the new content's hash. A cancelled routine is not changed."""
    unknown = sorted(set(fields) - set(ROUTINE_FIELDS))
    if unknown:
        raise StoreError(f"a routine has no field {', '.join(unknown)}", EXIT_USAGE)
    args = _routine_args(fields)
    now = iso(utcnow())
    with write(conn):
        row = _routine_row(conn, routine_id)
        if row["state"] == "cancelled":
            raise StoreError(f"routine {routine_id} is cancelled: it is not changed")
        sets = ", ".join(f"{k} = ?" for k in args)
        conn.execute(f"UPDATE routines SET {sets + ', ' if sets else ''}state = 'draft', approved_sha256 = NULL, approved_content = NULL, "
                     "approved_at = NULL, approved_by = NULL, updated_at = ? WHERE id = ?", (*args.values(), now, routine_id))
        return _routine_row(conn, routine_id)


def routine_approve(conn: sqlite3.Connection, routine_id: int, *, sha256: str, by: str, content: dict | None = None) -> dict:
    """Record the approval of a routine's content by its hash: it becomes active. content is what the hash covers, kept so that a fire
    that finds the hash changed can say what differs. A cancelled routine is not approved."""
    digest = sha_arg(sha256)
    kept = json.dumps(content or {}, sort_keys=True, separators=(",", ":"))
    if len(kept) > PAYLOAD_MAX:
        raise StoreError("a routine's approved content is over the cap", EXIT_USAGE)
    by = text_arg(by, "by", LABEL_MAX)
    now = iso(utcnow())
    with write(conn):
        row = _routine_row(conn, routine_id)
        if row["state"] == "cancelled":
            raise StoreError(f"routine {routine_id} is cancelled: it is not approved")
        conn.execute("UPDATE routines SET state = 'active', approved_sha256 = ?, approved_content = ?, approved_at = ?, approved_by = ?, "
                     "updated_at = ? WHERE id = ?", (digest, kept, now, by, now, routine_id))
        return _routine_row(conn, routine_id)


ROUTINE_MOVES = {"pause": (("active",), "paused"), "resume": (("paused",), "active"), "stop": (("active", "paused"), "stopped"),
                 "cancel": (("draft", "active", "paused", "stopped"), "cancelled")}


def routine_move(conn: sqlite3.Connection, routine_id: int, move: str) -> dict:
    """pause (active to paused), resume (paused to active: its approval stays, and `resumed_at` is the moment from which its slots count
    again: what passed while it was paused is not made up), stop (the runtime stops it when a fire finds its content
    changed) or cancel (a routine is never deleted). The approval is kept by all of them."""
    if move not in ROUTINE_MOVES:
        raise StoreError(f"a routine move is one of {', '.join(ROUTINE_MOVES)}", EXIT_USAGE)
    allowed, state = ROUTINE_MOVES[move]
    now = iso(utcnow())
    with write(conn):
        row = _routine_row(conn, routine_id)
        if row["state"] not in allowed:
            raise StoreError(f"routine {routine_id} is {row['state']}: it is {move}d only from {' or '.join(allowed)}")
        conn.execute("UPDATE routines SET state = ?, resumed_at = CASE WHEN ? = 'resume' THEN ? ELSE resumed_at END, updated_at = ? "
                     "WHERE id = ?", (state, move, now, now, routine_id))
        return _routine_row(conn, routine_id)


def routine_fire(conn: sqlite3.Connection, *, routine_id: int, slot: str, status: str, reason: str | None = None,
                 request: dict | None = None, question: dict | None = None, state: str | None = None,
                 approved_sha256: str | None = None) -> dict:
    """Write the fire of one slot, once: the row (routine, slot) and, in the same transaction, what it created. status `created`
    carries `request` ({"title", "text", "flow", "tasks", "waits", "model"}: the request and its plan, as request_add makes them);
    `asked` carries `question` ({"title", "body", "payload"}: a request that waits for its route with one question on it, which the
    person answers) and may move the routine to `state` (stopped); `skipped` carries neither. A slot already recorded creates nothing:
    {"fired": False, "duplicate": True}. Inside the transaction the routine must still be `active`, and, when approved_sha256 is given, still
    approved with that hash: a pause, a change or a new approval made between the caller's read and this write wins, and nothing is written
    ({"fired": False, "inactive": True}). Returns {"fired": True, "fire": the row, "request": id or None, "tasks": [...],
    "pending_id": id or None}."""
    if status not in FIRE_STATUSES:
        raise StoreError(f"a fire's status is one of {', '.join(FIRE_STATUSES)}", EXIT_USAGE)
    slot = text_arg(slot, "slot", LABEL_MAX)
    reason = text_arg(reason, "reason", NOTE_MAX, multiline=True, required=False)
    made = None
    if request is not None:
        title = text_arg(request.get("title"), "title", TITLE_MAX)
        text = text_arg(request.get("text"), "text", TEXT_MAX, multiline=True)
        flow = text_arg(request.get("flow"), "flow", LABEL_MAX)
        plan = _plan_items(request.get("tasks") or [])
        made = (title, text, flow, plan, request.get("waits"), _model_arg(request.get("model")))
    asking = None
    if question is not None:
        asking = (text_arg(question.get("title"), "title", TITLE_MAX), text_arg(question.get("body"), "body", TEXT_MAX, multiline=True),
                  json.dumps(question.get("payload") or {}, sort_keys=True))
    if (status == "created") != (made is not None) or (status == "asked") != (asking is not None):
        raise StoreError("a created fire carries a request and an asked fire a question, and no other does", EXIT_USAGE)
    now = iso(utcnow())
    with write(conn):
        routine = _routine_row(conn, routine_id)
        if routine["state"] != "active" or not routine["approved_sha256"] or (approved_sha256 is not None and routine["approved_sha256"] != approved_sha256):
            return {"fired": False, "inactive": True}
        if conn.execute("SELECT 1 FROM routine_fires WHERE routine_id = ? AND slot = ?", (routine_id, slot)).fetchone():
            return {"fired": False, "duplicate": True}
        result, request_id, pending_id = None, None, None
        if made is not None:
            result = _request_in(conn, made[0], made[1], made[2], made[3], None, made[4], made[5], now)
            request_id = result["request"]
        if asking is not None:
            request_id = conn.execute("INSERT INTO tasks (title, text, state, created_at, updated_at) VALUES (?, ?, 'requested', ?, ?)",
                                      (asking[0], asking[1], now, now)).lastrowid
            pending_id = conn.execute("INSERT INTO pending_decisions (task_id, kind, title, body, payload, created_at) "
                                      "VALUES (?, 'question', ?, ?, ?, ?)", (request_id, asking[0], asking[1], asking[2], now)).lastrowid
        fire = conn.execute("INSERT INTO routine_fires (routine_id, slot, status, reason, request_id, fired_at) VALUES (?, ?, ?, ?, ?, ?)",
                            (routine_id, slot, status, reason, request_id, now)).lastrowid
        if state is not None:
            if state not in ROUTINE_STATES:
                raise StoreError(f"a routine's state is one of {', '.join(ROUTINE_STATES)}", EXIT_USAGE)
            conn.execute("UPDATE routines SET state = ?, updated_at = ? WHERE id = ? AND state != 'cancelled'", (state, now, routine_id))
        row = conn.execute("SELECT * FROM routine_fires WHERE id = ?", (fire,)).fetchone()
        return {"fired": True, "fire": row_dict(row), "request": request_id, "tasks": (result or {}).get("tasks", []),
                "pending_id": pending_id, "routine": routine["name"]}


def routine_fires_list(conn: sqlite3.Connection, routine_id: int | None = None, limit: int = 50) -> list:
    """The fires, newest first (at most `limit`), of one routine or of all."""
    rows = conn.execute("SELECT * FROM routine_fires WHERE (?1 IS NULL OR routine_id = ?1) ORDER BY id DESC LIMIT ?2",
                        (routine_id, int(limit))).fetchall()
    return [row_dict(r) for r in rows]


def routine_of_request(conn: sqlite3.Connection, request_id: int):
    """The routine whose fire created a request, with the fire: {"routine": row, "fire": row}, or None."""
    fire = conn.execute("SELECT * FROM routine_fires WHERE request_id = ? AND status = 'created'", (request_id,)).fetchone()
    if fire is None:
        return None
    return {"routine": _routine_row(conn, fire["routine_id"]), "fire": row_dict(fire)}


def source_add(conn: sqlite3.Connection, *, source_id: str, source_type: str, origin: str, description: str | None = None) -> dict:
    """Register a source: an id (lowercase letters, digits, hyphens), a type (`file`, `notion`, `drive`, `onedrive`, `mail` or `calendar`), an origin (a file's name, or a
    Notion page's address or id: no credential is ever kept here) and an optional description. An id taken is refused: the
    registry only grows. Returns the row."""
    if not isinstance(source_id, str) or not SOURCE_ID_RE.fullmatch(source_id):
        raise StoreError("a source id is lowercase letters, digits and hyphens, at most 40 characters", EXIT_USAGE)
    if source_type not in SOURCE_TYPES:
        raise StoreError(f"a source's type is one of {', '.join(SOURCE_TYPES)}", EXIT_USAGE)
    origin = text_arg(origin, "origin", REF_MAX)
    description = text_arg(description, "description", NOTE_MAX, multiline=True, required=False)
    now = iso(utcnow())
    with write(conn):
        if _source_row(conn, source_id) is not None:
            raise StoreError(f"the source {source_id} is already registered", EXIT_USAGE)
        conn.execute("INSERT INTO sources (id, type, origin, description, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                     (source_id, source_type, origin, description, now, now))
    return source_get(conn, source_id)


def source_get(conn: sqlite3.Connection, source_id: str) -> dict:
    row = _source_row(conn, source_id)
    if row is None:
        raise StoreError(f"no source {source_id}")
    return row_dict(row)


def sources_list(conn: sqlite3.Connection) -> list:
    """Every source, by id."""
    return [row_dict(r) for r in conn.execute("SELECT * FROM sources ORDER BY id")]


def source_describe(conn: sqlite3.Connection, source_id: str, description: str | None) -> dict:
    """Set (or clear, with None) the person's description of a source: the one field of the registry that changes."""
    description = text_arg(description, "description", NOTE_MAX, multiline=True, required=False)
    with write(conn):
        if _source_row(conn, source_id) is None:
            raise StoreError(f"no source {source_id}")
        conn.execute("UPDATE sources SET description = ?, updated_at = ? WHERE id = ?", (description, iso(utcnow()), source_id))
    return source_get(conn, source_id)


def source_version_add(conn: sqlite3.Connection, *, source_id: str, version: int, label: str, by: str, kind: str,
                       original_name: str, original_sha256: str, original_bytes: int, converted_name: str,
                       converted_sha256: str, converted_bytes: int, converter: str, converter_version: str | None,
                       warnings, catalog: dict, origin_version: str | None, imported_at: str, hidden_text=None, provenance=None) -> dict:
    """Record one imported version, whole and final (no column of it is ever written again). The version must be the next
    number of the source. `provenance` (ATT-1) is where the version came from, a small object stored as JSON, or None for a version a
    person added in the terminal or on the page. Returns the row, with warnings, catalog and provenance as objects."""
    if label not in SOURCE_LABELS or by not in SOURCE_BYS:
        raise StoreError("an unknown label or author of a source version", EXIT_USAGE)
    for name, digest in (("original_sha256", original_sha256), ("converted_sha256", converted_sha256)):
        if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
            raise StoreError(f"{name} must be 64 hexadecimal characters", EXIT_USAGE)
    kind = text_arg(kind, "kind", LABEL_MAX)
    original_name = text_arg(original_name, "original_name", LABEL_MAX)
    converted_name = text_arg(converted_name, "converted_name", LABEL_MAX)
    converter = text_arg(converter, "converter", LABEL_MAX)
    converter_version = text_arg(converter_version, "converter_version", NOTE_MAX, required=False)
    origin_version = text_arg(origin_version, "origin_version", REF_MAX, required=False)
    warned = json.dumps(list(warnings or []))
    described = json.dumps(catalog, sort_keys=True)
    if len(described.encode("utf-8")) > PAYLOAD_MAX or len(warned.encode("utf-8")) > PAYLOAD_MAX:
        raise StoreError("the catalog entry is too large", EXIT_USAGE)
    if provenance is not None and (not isinstance(provenance, dict) or len(json.dumps(provenance).encode("utf-8")) > NOTE_MAX):
        raise StoreError("the provenance of a version is a small object", EXIT_USAGE)
    came = json.dumps(provenance, sort_keys=True) if provenance is not None else None
    with write(conn):
        if _source_row(conn, source_id) is None:
            raise StoreError(f"no source {source_id}")
        top = conn.execute("SELECT COALESCE(MAX(version), 0) AS top FROM source_versions WHERE source_id = ?", (source_id,)).fetchone()["top"]
        if version != top + 1:
            raise StoreError(f"the next version of {source_id} is {top + 1}, not {version}")
        conn.execute("INSERT INTO source_versions (source_id, version, label, by, kind, original_name, original_sha256, original_bytes, "
                     "converted_name, converted_sha256, converted_bytes, converter, converter_version, hidden_text, warnings, catalog, "
                     "origin_version, imported_at, provenance) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                     (source_id, version, label, by, kind, original_name, original_sha256, int(original_bytes), converted_name,
                      converted_sha256, int(converted_bytes), converter, converter_version, hidden_text, warned, described,
                      origin_version, imported_at, came))
    return source_version_get(conn, source_id, version)


def _version_dict(row) -> dict:
    return row_dict(row, ("warnings", "catalog", "provenance"))


def source_version_get(conn: sqlite3.Connection, source_id: str, version: int) -> dict:
    row = conn.execute("SELECT * FROM source_versions WHERE source_id = ? AND version = ?", (source_id, version)).fetchone()
    if row is None:
        raise StoreError(f"no version {version} of the source {source_id}")
    return _version_dict(row)


def source_latest(conn: sqlite3.Connection, source_id: str):
    """The newest version of a source, or None when it has none."""
    row = conn.execute("SELECT * FROM source_versions WHERE source_id = ? ORDER BY version DESC LIMIT 1", (source_id,)).fetchone()
    return _version_dict(row) if row is not None else None


def source_versions(conn: sqlite3.Connection, source_id: str) -> list:
    """Every version of a source, oldest first."""
    return [_version_dict(r) for r in conn.execute("SELECT * FROM source_versions WHERE source_id = ? ORDER BY version", (source_id,))]


def source_version_count(conn: sqlite3.Connection, source_id: str) -> int:
    return conn.execute("SELECT COUNT(*) AS n FROM source_versions WHERE source_id = ?", (source_id,)).fetchone()["n"]


def task_source_record(conn: sqlite3.Connection, *, run_id: int, task_id: int, source_id: str, version: int, sha256: str) -> dict:
    """Record the version of a source a run of a task received (decision D29): its id, version and the sha256 of the converted
    text that was copied. One row for each source of a run; nothing is changed after."""
    if not isinstance(sha256, str) or not SHA256_RE.fullmatch(sha256):
        raise StoreError("sha256 must be 64 hexadecimal characters", EXIT_USAGE)
    now = iso(utcnow())
    with write(conn):
        run = conn.execute("SELECT task_id FROM task_runs WHERE id = ?", (run_id,)).fetchone()
        if run is None or run["task_id"] != task_id:
            raise StoreError(f"run {run_id} is not a run of task {task_id}")
        version_row = conn.execute("SELECT converted_sha256 FROM source_versions WHERE source_id = ? AND version = ?",
                                   (source_id, version)).fetchone()
        if version_row is None or version_row["converted_sha256"] != sha256:
            raise StoreError(f"{source_id} version {version} is not recorded with that sha256")
        conn.execute("INSERT INTO task_sources (run_id, task_id, source_id, version, sha256, copied_at) VALUES (?, ?, ?, ?, ?, ?)",
                     (run_id, task_id, source_id, version, sha256, now))
    return {"run_id": run_id, "task_id": task_id, "source": source_id, "version": version, "sha256": sha256, "copied_at": now}


def task_sources_of(conn: sqlite3.Connection, task_id: int) -> list:
    """The sources every run of a task received, oldest first: {"run_id", "source_id", "version", "sha256", "copied_at"}."""
    return [row_dict(r, drop=("task_id",)) for r in conn.execute(
        "SELECT * FROM task_sources WHERE task_id = ? ORDER BY run_id, source_id", (task_id,))]


# --- held attachments (migration 18; runtime/ops_attachments.py is the one caller) ---------------------------------------------

ATTACHMENT_STATUSES = ("held", "added", "refused", "discarded", "expired")
ATTACHMENT_DECISIONS = ("added", "refused", "discarded", "expired")
ATTACHMENT_LABELS = ("import", "refresh")
ATTACHMENT_LIST_MAX = 500


def _attachment(row) -> dict:
    out = row_dict(row)
    out["direct"] = bool(out["direct"])
    return out


def attachment_add(conn: sqlite3.Connection, *, platform: str, ref_sha256: str, sender: str, profile: str | None, name: str,
                   declared_type: str | None, declared_bytes: int | None, kind: str | None, sha256: str | None, size: int,
                   target: str | None, label: str | None, direct: bool = False, status: str = "held", code: str | None = None,
                   created_at: str | None = None) -> dict:
    """Record one file of a messaging app that reached the hold. `status` is `held` (it waits for a person, or for the add that follows at
    once when `direct`) or `refused` (a rule refused it after its bytes arrived: `code` says which; it still counts against the day's
    limit, because its bytes were fetched). A held file whose platform reference is already held is refused (StoreError, code 1; a refused record may repeat a reference): delivery is at
    least once. `ref_sha256` is the hash of the reference, never the reference. Returns the row."""
    if status not in ("held", "refused"):
        raise StoreError("an attachment is recorded held or refused", EXIT_USAGE)
    if not isinstance(ref_sha256, str) or not SHA256_RE.fullmatch(ref_sha256):
        raise StoreError("ref_sha256 must be 64 hexadecimal characters", EXIT_USAGE)
    if sha256 is not None and (not isinstance(sha256, str) or not SHA256_RE.fullmatch(sha256)):
        raise StoreError("sha256 must be 64 hexadecimal characters", EXIT_USAGE)
    platform = text_arg(platform, "platform", LABEL_MAX)
    sender = text_arg(sender, "sender", ACTOR_MAX)
    profile = text_arg(profile, "profile", LABEL_MAX, required=False)
    name = text_arg(name, "name", REF_MAX)
    declared_type = text_arg(declared_type, "declared_type", LABEL_MAX, required=False)
    kind = text_arg(kind, "kind", LABEL_MAX, required=False)
    code = text_arg(code, "code", LABEL_MAX, required=False)
    if target is not None and not (isinstance(target, str) and SOURCE_ID_RE.fullmatch(target)):
        raise StoreError("an attachment's target is a source id", EXIT_USAGE)
    if label is not None and label not in ATTACHMENT_LABELS:
        raise StoreError(f"an attachment's label is one of {', '.join(ATTACHMENT_LABELS)}", EXIT_USAGE)
    if status == "refused" and not code:
        raise StoreError("a refused attachment carries the code of its refusal", EXIT_USAGE)
    now = created_at or iso(utcnow())
    with write(conn):
        if status == "held" and conn.execute("SELECT 1 FROM attachments WHERE platform = ? AND ref_sha256 = ? AND status = 'held'",
                                             (platform, ref_sha256)).fetchone():
            raise StoreError("this file is already held", EXIT_ERROR)
        row_id = conn.execute(
            "INSERT INTO attachments (platform, ref_sha256, sender, profile, name, declared_type, declared_bytes, kind, sha256, bytes, "
            "target, label, direct, status, code, created_at, decided_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (platform, ref_sha256, sender, profile, name, declared_type, declared_bytes, kind, sha256, int(size), target, label,
             1 if direct else 0, status, code, now, now if status == "refused" else None)).lastrowid
    return attachment_get(conn, row_id)


def attachment_get(conn: sqlite3.Connection, attachment_id: int) -> dict:
    row = conn.execute("SELECT * FROM attachments WHERE id = ?", (attachment_id,)).fetchone()
    if row is None:
        raise StoreError(f"no attachment {attachment_id}")
    return _attachment(row)


def attachments_list(conn: sqlite3.Connection, statuses=None, limit: int = ATTACHMENT_LIST_MAX, older_than: str | None = None) -> list:
    """The attachments, oldest first, the newest `limit` of them: those in `statuses` (default all) and, when `older_than` (an ISO time) is
    given, made before it."""
    wanted = tuple(statuses) if statuses else ATTACHMENT_STATUSES
    if not all(s in ATTACHMENT_STATUSES for s in wanted):
        raise StoreError(f"an attachment's status is one of {', '.join(ATTACHMENT_STATUSES)}", EXIT_USAGE)
    marks = ", ".join("?" for _ in wanted)
    query = f"SELECT * FROM attachments WHERE status IN ({marks})" + (" AND created_at < ?" if older_than else "") + " ORDER BY id DESC LIMIT ?"
    args = (*wanted, *((older_than,) if older_than else ()), min(int(limit), ATTACHMENT_LIST_MAX))
    return [_attachment(r) for r in reversed(conn.execute(query, args).fetchall())]


def attachment_held_by_ref(conn: sqlite3.Connection, platform: str, ref_sha256: str):
    """The held attachment of a platform reference (by its hash), or None."""
    row = conn.execute("SELECT * FROM attachments WHERE platform = ? AND ref_sha256 = ? AND status = 'held'", (platform, ref_sha256)).fetchone()
    return _attachment(row) if row is not None else None


def attachment_decide(conn: sqlite3.Connection, attachment_id: int, status: str, *, code: str | None = None, source_id: str | None = None,
                      version: int | None = None, decided_at: str | None = None) -> dict:
    """End the hold of a file: `added` (with the source and the version it became), `refused` (with the code), `discarded` or `expired`. Only
    a held attachment can be decided, and once (a second decision is a StoreError); the rest of the row never changes."""
    if status not in ATTACHMENT_DECISIONS:
        raise StoreError(f"an attachment's decision is one of {', '.join(ATTACHMENT_DECISIONS)}", EXIT_USAGE)
    code = text_arg(code, "code", LABEL_MAX, required=False)
    if status == "refused" and not code:
        raise StoreError("a refused attachment carries the code of its refusal", EXIT_USAGE)
    if status == "added" and not (isinstance(source_id, str) and SOURCE_ID_RE.fullmatch(source_id)
                                  and isinstance(version, int) and not isinstance(version, bool) and version >= 1):
        raise StoreError("an added attachment names the source and the version it became", EXIT_USAGE)
    with write(conn):
        row = conn.execute("SELECT status FROM attachments WHERE id = ?", (attachment_id,)).fetchone()
        if row is None:
            raise StoreError(f"no attachment {attachment_id}")
        if row["status"] != "held":
            raise StoreError(f"attachment {attachment_id} is {row['status']}, not held", EXIT_ERROR)
        conn.execute("UPDATE attachments SET status = ?, code = ?, source_id = ?, version = ?, decided_at = ? WHERE id = ?",
                     (status, code, source_id if status == "added" else None, version if status == "added" else None,
                      decided_at or iso(utcnow()), attachment_id))
    return attachment_get(conn, attachment_id)


def attachments_since(conn: sqlite3.Connection, since: str) -> dict:
    """What the messaging apps brought since an ISO time: {"files", "bytes"} of every row recorded from then (refused ones too: their bytes
    were fetched). The runtime asks for the start of the UTC day."""
    row = conn.execute("SELECT COUNT(*) AS files, COALESCE(SUM(bytes), 0) AS bytes FROM attachments WHERE created_at >= ?", (since,)).fetchone()
    return {"files": row["files"], "bytes": row["bytes"]}


# --- reminders (migration 20; runtime/ops_reminders.py is the one caller) -----------------------------------------------------------
# The table is not in the export: the text of a reminder is the person's own words and leaves the store through the operations alone.

REMINDER_STATUSES = ("open", "sending", "sent", "cancelled", "missed", "dropped")
REMINDER_WHYS = ("late", "sender removed", "not permitted")
REMINDER_TEXT_BYTES = 1280      # 300 characters of any script, with a margin; the runtime holds the 300 characters
REMINDER_LIST_MAX = 500
REMINDER_OPEN_FULL = "too many reminders wait in this project"
REMINDER_DAY_FULL = "too many reminders were made for this chat today"
REMINDER_CHAT_FULL = "too many reminders wait for this chat"
REMINDER_TIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z")


def reminder_add(conn: sqlite3.Connection, *, text: str, due_local: str, due_utc: str, zone: str, platform: str, chat: str, created_by: str,
                 max_open: int, max_day: int, day_since: str, max_open_chat: int | None = None, created_at: str | None = None) -> dict:
    """Record one reminder, `open`, if the project holds fewer than `max_open` that wait (open or being sent), this platform and chat fewer than
    `max_open_chat` (when given: one chat cannot fill the project), and fewer than `max_day` were made for
    this platform and chat since `day_since` (an ISO time): both counted in the transaction that writes, so two callers cannot both pass the last
    place. `due_utc` is a fixed-width UTC time (iso); `due_local` the wall time as asked. Returns the row."""
    text = text_arg(text, "text", REMINDER_TEXT_BYTES)
    due_local = text_arg(due_local, "due_local", LABEL_MAX)
    zone = text_arg(zone, "zone", LABEL_MAX)
    platform = text_arg(platform, "platform", LABEL_MAX)
    chat = text_arg(chat, "chat", ACTOR_MAX)
    created_by = text_arg(created_by, "created_by", ACTOR_MAX)
    if not (isinstance(due_utc, str) and REMINDER_TIME.fullmatch(due_utc)):
        raise StoreError("due_utc must be a fixed-width UTC time (iso)", EXIT_USAGE)
    now = created_at or iso(utcnow())
    with write(conn):
        waiting = conn.execute("SELECT COUNT(*) AS n FROM reminders WHERE status IN ('open', 'sending')").fetchone()["n"]
        if waiting >= int(max_open):
            raise StoreError(REMINDER_OPEN_FULL, EXIT_ERROR)
        if max_open_chat is not None and conn.execute("SELECT COUNT(*) AS n FROM reminders WHERE status IN ('open', 'sending') AND platform = ? AND chat = ?",
                                                      (platform, chat)).fetchone()["n"] >= int(max_open_chat):
            raise StoreError(REMINDER_CHAT_FULL, EXIT_ERROR)
        today = conn.execute("SELECT COUNT(*) AS n FROM reminders WHERE platform = ? AND chat = ? AND created_at >= ?",
                             (platform, chat, day_since)).fetchone()["n"]
        if today >= int(max_day):
            raise StoreError(REMINDER_DAY_FULL, EXIT_ERROR)
        row_id = conn.execute(
            "INSERT INTO reminders (text, due_local, due_utc, zone, platform, chat, created_by, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?)",
            (text, due_local, due_utc, zone, platform, chat, created_by, now)).lastrowid
    return reminder_get(conn, row_id)


def reminder_get(conn: sqlite3.Connection, reminder_id: int) -> dict:
    row = conn.execute("SELECT * FROM reminders WHERE id = ?", (reminder_id,)).fetchone()
    if row is None:
        raise StoreError(f"no reminder {reminder_id}")
    return row_dict(row)


def reminders_list(conn: sqlite3.Connection, statuses=None, platform: str | None = None, chat: str | None = None,
                   ended_since: str | None = None, limit: int = REMINDER_LIST_MAX) -> list:
    """The reminders in `statuses` (default all), of a platform and a chat when given: the waiting ones (open, sending) by the time they are due, the
    others newest first; `ended_since` keeps an ended one only if it ended at or after that ISO time."""
    wanted = tuple(statuses) if statuses else REMINDER_STATUSES
    if not all(s in REMINDER_STATUSES for s in wanted):
        raise StoreError(f"a reminder's status is one of {', '.join(REMINDER_STATUSES)}", EXIT_USAGE)
    marks = ", ".join("?" for _ in wanted)
    query, args = f"SELECT * FROM reminders WHERE status IN ({marks})", list(wanted)
    if platform is not None:
        query += " AND platform = ?"
        args.append(platform)
    if chat is not None:
        query += " AND chat = ?"
        args.append(chat)
    if ended_since is not None:
        query += " AND (ended_at IS NULL OR ended_at >= ?)"
        args.append(ended_since)
    waiting = all(s in ("open", "sending") for s in wanted)
    query += " ORDER BY " + ("due_utc, id" if waiting else "id DESC") + " LIMIT ?"
    args.append(min(int(limit), REMINDER_LIST_MAX))
    return [row_dict(r) for r in conn.execute(query, args).fetchall()]


def reminders_due(conn: sqlite3.Connection, platform: str, until: str, limit: int = REMINDER_LIST_MAX) -> list:
    """The open reminders of a platform whose time is at or before `until` (an ISO time) and that are not waiting out the pause after a failed send
    (`retry_after`), oldest due first."""
    return [row_dict(r) for r in conn.execute(
        "SELECT * FROM reminders WHERE status = 'open' AND platform = ? AND due_utc <= ? AND (retry_after IS NULL OR retry_after <= ?) "
        "ORDER BY due_utc, id LIMIT ?", (platform, until, until, min(int(limit), REMINDER_LIST_MAX))).fetchall()]


def reminder_claim(conn: sqlite3.Connection, reminder_id: int, at: str | None = None) -> bool:
    """Take an open reminder to send it: `open` becomes `sending`. True for the one caller that took it, False when it is not open any more."""
    with write(conn):
        changed = conn.execute("UPDATE reminders SET status = 'sending', claimed_at = ? WHERE id = ? AND status = 'open'",
                               (at or iso(utcnow()), reminder_id)).rowcount
    return changed == 1


def reminder_release(conn: sqlite3.Connection, reminder_id: int, retry_after: str | None = None) -> bool:
    """Give a claimed reminder back (the send failed or was deferred): `sending` becomes `open`, one more failure is counted, and it is not offered
    again before `retry_after` (an ISO time; none: at once). False when it was not `sending`."""
    if retry_after is not None and not (isinstance(retry_after, str) and REMINDER_TIME.fullmatch(retry_after)):
        raise StoreError("retry_after must be a fixed-width UTC time (iso)", EXIT_USAGE)
    with write(conn):
        changed = conn.execute("UPDATE reminders SET status = 'open', claimed_at = NULL, attempts = attempts + 1, retry_after = ? WHERE id = ? AND status = 'sending'",
                               (retry_after, reminder_id)).rowcount
    return changed == 1


def reminders_reclaim(conn: sqlite3.Connection, before: str) -> int:
    """Open again every reminder claimed at or before `before` (an ISO time) and still `sending`: the bridge that claimed it stopped. Returns how many."""
    with write(conn):
        return conn.execute("UPDATE reminders SET status = 'open', claimed_at = NULL WHERE status = 'sending' AND claimed_at <= ?", (before,)).rowcount


def reminder_end(conn: sqlite3.Connection, reminder_id: int, status: str, *, why: str | None = None, at: str | None = None) -> dict:
    """End a reminder: `sent` (it was `sending`), `cancelled` (it was `open`), `missed` or `dropped` (open, or sending that was given up), the last two with
    their `why`. An ended reminder is final; a second end is a StoreError."""
    if status not in ("sent", "cancelled", "missed", "dropped"):
        raise StoreError("a reminder ends sent, cancelled, missed or dropped", EXIT_USAGE)
    if (status in ("missed", "dropped")) != (why is not None) or (why is not None and why not in REMINDER_WHYS):
        raise StoreError(f"a missed or dropped reminder carries one of: {', '.join(REMINDER_WHYS)}", EXIT_USAGE)
    came_from = {"sent": ("sending",), "cancelled": ("open",), "missed": ("open", "sending"), "dropped": ("open", "sending")}[status]
    with write(conn):
        row = conn.execute("SELECT status FROM reminders WHERE id = ?", (reminder_id,)).fetchone()
        if row is None:
            raise StoreError(f"no reminder {reminder_id}")
        if row["status"] not in came_from:
            raise StoreError(f"reminder {reminder_id} is {row['status']}, not {' or '.join(came_from)}", EXIT_ERROR)
        conn.execute("UPDATE reminders SET status = ?, why = ?, ended_at = ? WHERE id = ?", (status, why, at or iso(utcnow()), reminder_id))
    return reminder_get(conn, reminder_id)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sqlite.py",
        description="Store provider on SQLite: cursors, events, runs, inbox and actions of the agent runtime "
        "in one local database file.",
        epilog=HELP_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--check", action="store_true",
                        help="verify the database is reachable and at the current schema version; changes nothing")
    parser.add_argument("--db", help=f"database file (default ${PATH_ENV})")
    common = argparse.ArgumentParser(add_help=False)
    # SUPPRESS keeps a --db given before the verb when none is given after it.
    common.add_argument("--db", default=argparse.SUPPRESS, help=f"database file (default ${PATH_ENV})")
    sub = parser.add_subparsers(dest="verb", metavar="verb")

    def verb(name: str, help_text: str) -> argparse.ArgumentParser:
        return sub.add_parser(name, parents=[common], help=help_text)

    verb("init", "create or migrate the schema (idempotent)")
    p = verb("cursor-get", "read a cursor")
    p.add_argument("--name")
    p = verb("cursor-set", "write a cursor")
    p.add_argument("--name")
    p.add_argument("--value")
    p = verb("cursor-clear", "delete a cursor")
    p.add_argument("--name")
    p = verb("event-add", "record a trigger once per source and external id")
    p.add_argument("--source")
    p.add_argument("--external-id")
    p.add_argument("--payload-file")
    p = verb("event-next", "claim pending events atomically")
    p.add_argument("--source")
    p.add_argument("--limit", type=int)
    p.add_argument("--reclaim-after-minutes", type=int, default=RECLAIM_DEFAULT_MINUTES)
    p = verb("event-done", "finish a claimed event")
    p.add_argument("--id")
    p.add_argument("--token")
    p.add_argument("--status", choices=EVENT_DONE_STATUSES, required=True)
    p.add_argument("--note")
    p = verb("run-start", "record the start of an agent run")
    p.add_argument("--agent")
    p.add_argument("--event-id")
    p.add_argument("--trigger")
    p = verb("run-end", "record the end of an agent run")
    p.add_argument("--run-id")
    p.add_argument("--status", choices=RUN_END_STATUSES, required=True)
    p.add_argument("--exit-code")
    p.add_argument("--cost-usd")
    p.add_argument("--tokens")
    p.add_argument("--duration-ms")
    p.add_argument("--out-dir")
    p.add_argument("--error")
    p = verb("runs", "list runs, newest first")
    p.add_argument("--limit", type=int)
    p.add_argument("--agent")
    p = verb("inbox-add", "put an item in the user's inbox")
    p.add_argument("--kind")
    p.add_argument("--title")
    p.add_argument("--payload-file")
    p.add_argument("--payload-sha256")
    p.add_argument("--event-id")
    p = verb("inbox-list", "list inbox items")
    p.add_argument("--status", choices=(*INBOX_STATUSES, "all"))  # default open; None tells --id it was not given
    p.add_argument("--limit", type=int)
    p.add_argument("--id")
    p = verb("inbox-resolve", "record the user's decision on an inbox item")
    p.add_argument("--id")
    p.add_argument("--status", choices=("approved", "rejected", "done"), required=True)
    p.add_argument("--by")
    p.add_argument("--note")
    p = verb("action-add", "record an outward action the runtime executed")
    p.add_argument("--kind")
    p.add_argument("--idempotency-key")
    p.add_argument("--target")
    p.add_argument("--payload-sha256")
    p.add_argument("--result-file")
    p = verb("actions", "list actions since a time")
    p.add_argument("--since", required=True)
    p.add_argument("--kind")
    p.add_argument("--limit", type=int)
    p = verb("action-count", "count actions of a kind since a time")
    p.add_argument("--kind")
    p.add_argument("--since", required=True)
    p = verb("export", "dump every table as JSON")
    p.add_argument("--format", choices=("json",), required=True)
    p.add_argument("--since")
    return parser


def main(argv: list[str] | None = None) -> int:
    os.umask(0o077)  # the database, its WAL files and a new folder are private to the user
    args = build_parser().parse_args(argv)
    try:
        if args.check:
            if args.verb:
                raise StoreError("--check takes no verb", EXIT_USAGE)
            return cmd_check(args)
        if not args.verb:
            raise StoreError("give a verb or --check; see --help", EXIT_USAGE)
        return VERBS[args.verb](args)
    except StoreError as exc:
        log(f"error: {exc}")
        return exc.code
    except OverflowError as exc:  # a number past what SQLite or a date can hold, that no check above caught
        log(f"error: a value is out of range: {exc}")
        return EXIT_USAGE
    except sqlite3.Error as exc:
        log(f"error: database: {exc}")
        return EXIT_ERROR
    except OSError as exc:
        log(f"error: {exc.strerror or exc}: {exc.filename or ''}".rstrip(": "))
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
