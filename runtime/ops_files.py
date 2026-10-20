#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The operations that put a file in the person's own Drive or OneDrive (package W4a, SPEC-SECRETARY-WRITES section 3.5): a new file, a new revision of a file the
person registered as a source, and a file someone sent through a messaging app, saved to a folder. Each one only PREPARES: it makes one request with one step task
of the kind `file-write` (runtime/step_files.py), runs its preparation with no model, and stops at the card that asks the person to approve the hash of the exact
document. Nothing is written to any account here (limit L55); the write is runtime/effect_files.py `execute`, reached only from `approve`.

  file_create(project, account, file_name, content | content_file | from_path, [folder])   a NEW file in a folder the project lists under `accounts`; it never replaces one
  file_replace(project, account, file, content | content_file | from_path)                   a new revision of a file that is a source (the previous one stays in the history)
  file_save(project, account, attachment, [file_name], [folder])                            the file a sender sent (a document, or a save-only image: ATT-3), in a folder the project lists

Each returns what runtime/account_start.py returns: {"request", "task", "pending", "word", "on_cards"}; the messaging bridge sends that decision's card as it
sends every card and says `account_start.reply_text`. Who may ask is the table of operations (runtime/operations.py: the group `files-write`, in no default policy,
never on the MCP mode) and, for a messaging sender, `ops_actor.guard`; who may approve is `approve-effect-files` and the terminal and the page. A save from a
messaging app is for a file THAT sender sent, and only that sender approves it (runtime/ops_grants.py, Q9): a file of someone else is answered as one that does
not exist.

Sibling of runtime/ops.py, which exposes the operations under their names. The shared names come from ops_core, read as `core.<name>` at call time. It reaches no
operation of ops.py. Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import account_start  # noqa: E402
import ops_actor  # noqa: E402
import ops_attachments  # noqa: E402
import ops_core as core  # noqa: E402
import phrases  # noqa: E402

KIND = "file-write"


def _content(content, content_file, from_path) -> dict:
    """The one source of the new content the person gave: their text (typed, or the text of a file the terminal read), or a file of the project."""
    given = [(k, v) for k, v in (("content", content), ("content", content_file), ("from", from_path)) if v is not None]
    if len(given) != 1:
        raise core.OpsError(phrases.en("ACCT_FILE_ONE_CONTENT"), 2)
    return {given[0][0]: given[0][1]}


def file_create(project: str, account: str, file_name: str, content: str | None = None, content_file: str | None = None, from_path: str | None = None,
                folder: str | None = None, channel: str | None = None, sender: str | None = None) -> dict:
    """Prepare a new file and stop at its card. See the module's text. A refusal is an OpsError whose message is the sentence the person reads."""
    args = {"operation": "create", "account": account, "name": file_name, **_content(content, content_file, from_path)}
    if folder is not None:
        args["folder"] = folder
    return account_start.start(project, KIND, args, key_words="file-create", title_key="TITLE_FILE_CREATE", account=account, channel=channel, sender=sender)


def file_replace(project: str, account: str, file: str, content: str | None = None, content_file: str | None = None, from_path: str | None = None,
                 channel: str | None = None, sender: str | None = None) -> dict:
    """Prepare a new revision of a file that is a source and stop at its card."""
    args = {"operation": "replace", "account": account, "file": file, **_content(content, content_file, from_path)}
    return account_start.start(project, KIND, args, key_words="file-replace", title_key="TITLE_FILE_REPLACE", account=account, channel=channel, sender=sender)


def file_save(project: str, account: str, attachment: int, file_name: str | None = None, folder: str | None = None, channel: str | None = None,
              sender: str | None = None) -> dict:
    """Prepare the saving of a held file and stop at its card. From a messaging app the file must be one THAT sender sent (and still held)."""
    ctx = core.context(project)
    ops_actor.guard(ctx, "file-save", channel, sender)
    ops_attachments._held(ctx, attachment, channel, sender)      # a file of someone else, or one no longer held, is refused as one that does not exist
    args = {"operation": "save", "account": account, "attachment": attachment}
    if file_name is not None:
        args["name"] = file_name
    if folder is not None:
        args["folder"] = folder
    return account_start.start(project, KIND, args, key_words="file-save", title_key="TITLE_FILE_SAVE", account=account, channel=channel, sender=sender)


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
