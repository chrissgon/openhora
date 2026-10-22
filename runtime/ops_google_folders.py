#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""A Google folder given as a path in the configuration, resolved to its id when the person accepts the file (slice S11).

`accounts.google.folders` holds a folder id, or, as OneDrive's does, a path from the top of the drive: "/Documentos", "/Clientes/2026". A write must never go to a folder the person
has not seen as an id, so a path is turned into the folder's id at the one moment the person says the file is right, `accept_config` (runtime/ops_config.py), which calls
these under the configuration lock:

  resolve(cfg)   {path: id} for every Google folder path of the file: the Drive provider's `resolve-path` verb (providers/documents/gdrive.py), one GET of the files list for each
                 name of a path, folders only, never a write; paths are resolved at the same time (they are independent). A folder that is missing, a name that two folders hold or a
                 provider that cannot be reached is an OpsError that names the path, and nothing is accepted.
  with_ids(cfg, resolved)   the configuration with the paths replaced by the ids, in memory: the widening list the person confirms and the accounts the acceptance records
                 are the ones with ids, so a folder that now resolves to another id is a widening like any other changed target.
  keep(cfg, resolved)   once every check passed, write the ids where `project_config.load` reads them (`google-folders.json` in data_dir); a file with no path removes an
                 older record. Nothing is written by a refused acceptance.

The ids are the person's acceptance: a folder renamed or moved later is not followed until the file is accepted again, and a path that was never resolved is refused by
`project_config.account_target` (the write kinds) and fails to list (the read of a file by its name). The network is used only here; the tests replace `provider_call`.

Sibling of runtime/ops_config.py. Standard library only. Runs on Python 3.9: python3 runtime/ops_google_folders.py --help
"""
from __future__ import annotations

import concurrent.futures
import re
import sys

import ops_core as core
import project_config
import sources

WORKERS = 4
ID = re.compile(r"[A-Za-z0-9_-]{10,128}")
provider_call = None     # a test replaces it: call(cls, verb, args, root=, implementation=, timeout=, env=) -> dict, as providers/resolve.py `call`


def _one(cfg: dict, path: str) -> str:
    """The id of one path, or an OpsError that names it."""
    try:
        got = sources.drive_call(cfg, "resolve-path", ["--path", path], call=provider_call)
    except sources.SourcesError as e:
        why = str(e).partition("): ")[2] or str(e)
        raise core.OpsError(f"the configuration was not accepted: the Google folder {path} could not be resolved: {why}", 1) from None
    ident = got.get("id")
    if not isinstance(ident, str) or not ID.fullmatch(ident) or got.get("path") != path:
        raise core.OpsError(f"the configuration was not accepted: the Google folder {path} could not be resolved: the Drive provider's answer is not one this runtime reads", 1)
    return ident


def resolve(cfg: dict) -> dict:
    """{path: id} of every Google folder path the file gives (see the module's text)."""
    paths = sorted({shown["path"] for shown in (cfg.get("google_folders") or {}).values()})
    if not paths:
        return {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(WORKERS, len(paths))) as pool:
        futures = [pool.submit(_one, cfg, path) for path in paths]
        done = [f.exception() or f.result() for f in futures]
    for found in done:
        if isinstance(found, BaseException):
            raise found
    return dict(zip(paths, done))


def with_ids(cfg: dict, resolved: dict) -> dict:
    """The configuration as it will be once `resolved` is kept: the same file, its Google folder paths replaced by their ids (in memory; nothing is written)."""
    if not resolved and not cfg.get("google_folders"):
        return cfg
    accounts, shown = project_config.with_google_ids(project_config.file_accounts(cfg), resolved)
    return dict(cfg, accounts=accounts, google_folders=shown)


def keep(cfg: dict, resolved: dict) -> None:
    """Write the ids where `project_config.load` reads them, after the acceptance passed every check; with none to keep, an older record is removed."""
    if not resolved and not project_config.resolved_google_paths(cfg["data_dir"]):
        return
    try:
        project_config.write_google_paths(cfg["data_dir"], resolved)
    except OSError as e:
        raise core.OpsError(f"the configuration was not accepted: the resolved Google folders cannot be kept in {cfg['data_dir']}: {e.strerror}", 1) from None


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
