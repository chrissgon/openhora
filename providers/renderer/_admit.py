"""The admission of a HyperFrames registry component to the second page contract (PF-a3, the host side): `ffmpeg.py admit-block`.

What an admission does, in the order it does it:

  1. runs the lint's own planted table (`_hf_lint.self_test`), so that a loosened rule stops every admission;
  2. reads the component's file from a local clone of the registry, after checking that the clone is at the commit `hf-runtime/registry.sha256` pins
     (`admitted_commit` otherwise), hashes it, applies the entry's edits (E1 and E2 only: `block_edit` for anything else), hashes the served bytes and
     lints them;
  3. (the container's: `_admit_check`) measures determinism and the exact gates; the verb in `ffmpeg.py` runs it and hands the result here;
  4. writes what the admission changes: the `registry.sha256` rows and a NOTICE entry (so that the image fetches the file at its next build, pinned),
     and the allowlist entry with its recorded determinism test, or, when staging was asked or the name is already held by another block (the tier-B
     port holds `hf:spring-pop` until the port is deleted), `hf-runtime/staged/<id>.json`, which the catalogue never loads.

Without `--confirmed` the plan is printed and nothing is written, and no container is started. Nothing is downloaded: the source is a folder on this machine.
A refusal leaves every file as it was. Standard library only.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
import time

import _blocks
import _hf_host
import _hf_lint
from _text import Refusal

HERE = os.path.dirname(os.path.abspath(__file__))
STAGED_FOLDER = "staged"
SOURCE_KEYS = frozenset(("name", "kind", "preset", "band", "license", "notice", "use_when", "params", "samples", "natural_duration", "bind", "fixed",
                         "theme_vars", "edits", "font_map"))
REQUIRED_KEYS = frozenset(("name", "preset", "use_when", "params", "samples", "natural_duration", "bind", "fixed", "theme_vars", "edits", "font_map"))
HEX40 = re.compile(r"[0-9a-f]{40}")
ID = re.compile(r"[a-z][a-z0-9-]{0,39}")
NOTICE_MARK = "<!-- admitted: %s -->"
MAX_ENTRY = 1 << 16


def runtime_dir() -> str:
    return _hf_host.runtime_dir(HERE)


# ---------------------------------------------------------------- the registry manifest

def read_manifest(path: str) -> tuple:
    """(commit, rows) of `registry.sha256`: rows are [(sha256, path)] in the file's order."""
    commit, rows = None, []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line.startswith("# commit "):
                    commit = line.split()[2] if len(line.split()) > 2 else None
                elif line and not line.startswith("#"):
                    digest, name = line.split(None, 1)
                    rows.append((digest, name.strip()))
    except (OSError, ValueError):
        raise Refusal("admit_manifest", "registry.sha256") from None
    if not commit or not HEX40.fullmatch(commit):
        raise Refusal("admit_manifest", "registry.sha256")
    return commit, rows


def manifest_text(path: str, add: dict) -> str:
    """The manifest with `add` ({path: sha256}) merged in: the header lines first, then the rows sorted by path. A path already there with another
    hash is `registry_row_differs`; with the same hash it stays as it is."""
    commit, rows = read_manifest(path)
    with open(path, encoding="utf-8") as fh:
        header = [line.rstrip("\n") for line in fh if line.startswith("#")]
    have = {name: digest for digest, name in rows}
    for name, digest in add.items():
        if name in have and have[name] != digest:
            raise Refusal("registry_row_differs", name[:80])
        have[name] = digest
    return "\n".join(header + ["%s  %s" % (have[name], name) for name in sorted(have)]) + "\n"


# ---------------------------------------------------------------- steps 1 and 2: the plan

def git_head(source: str) -> str:
    try:
        done = subprocess.run(["git", "-C", source, "rev-parse", "HEAD"], capture_output=True, text=True, timeout=30,
                              env={"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", ""), "GIT_CONFIG_NOSYSTEM": "1"})
    except (OSError, subprocess.SubprocessError):
        raise Refusal("admitted_commit", "source") from None
    head = done.stdout.strip()
    if done.returncode != 0 or not HEX40.fullmatch(head):
        raise Refusal("admitted_commit", "source")
    return head


def read_source(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            raw = fh.read(MAX_ENTRY + 1)
        obj = json.loads(raw) if len(raw) <= MAX_ENTRY else None
    except (OSError, ValueError):
        raise Refusal("admit_entry", "entry") from None
    if not isinstance(obj, dict) or not REQUIRED_KEYS <= set(obj) or not set(obj) <= SOURCE_KEYS:
        raise Refusal("admit_entry", "entry")
    return obj


def holds_name(name: str, blocks_dir: str) -> bool:
    """Whether a block of the committed catalogue (a tier-B port or an allowlist entry) already has this name."""
    return name in _blocks.load_catalogue(blocks_dir)["blocks"]


def build_entry(source: dict, commit: str, component: str, file_name: str, files: dict, served: str) -> dict:
    """The allowlist entry, without its determinism record: our fields from the person's file, the registry's from the source."""
    entry = {"name": source["name"], "kind": source.get("kind", "overlay"), "preset": source["preset"], "band": source.get("band", "card"),
             "may_cross_face": False, "license": source.get("license", ["Apache-2.0"]), "source": "hyperframes-registry", "use_when": source["use_when"],
             "params": source["params"], "samples": source["samples"], "natural_duration": source["natural_duration"], "implementations": {"hf": file_name},
             "tier": "A", "commit": commit,
             "notice": source.get("notice", "Apache-2.0; HyperFrames registry at %s; notices in providers/renderer/hf-runtime/NOTICE.md" % commit[:8]),
             "files": files, "component": component, "edits": source["edits"], "font_map": source["font_map"], "served_sha256": served,
             "bind": source["bind"], "fixed": source["fixed"], "theme_vars": source["theme_vars"]}
    return entry


def plan(*, source: str, component: str, entry_path: str, stage: bool, blocks_dir=None, runtime=None) -> dict:
    """Steps 1 and 2. Returns {entry (no determinism), files_text ({name: bytes}, the source's), commit, id, name_taken, staged, rows ({manifest path: sha256}),
    summary}. Nothing is written and no container is started. Refusals: `block_lint`, `block_edit`, `admitted_commit`, `admit_entry`, `block_schema`,
    `admit_manifest`."""
    _hf_lint.self_test()
    runtime = runtime or runtime_dir()
    commit, _rows = read_manifest(os.path.join(runtime, "registry.sha256"))
    if git_head(source) != commit:
        raise Refusal("admitted_commit", "source")
    if not isinstance(component, str) or not _blocks.REGISTRY_PATH.fullmatch(component):
        raise Refusal("admit_entry", "component")
    src = read_source(entry_path)
    short = component.rsplit("/", 1)[-1]
    file_name = short + ".html"
    folder = os.path.join(source, *component.split("/"))
    path = os.path.join(folder, file_name)
    if os.path.islink(path) or not os.path.isfile(path) or os.path.commonpath([os.path.realpath(path), os.path.realpath(source)]) != os.path.realpath(source):
        raise Refusal("admit_entry", "component")
    if os.path.getsize(path) > _hf_host.MAX_COMPONENT_FILE:
        raise Refusal("admit_entry", "component")
    with open(path, "rb") as fh:
        raw = fh.read()
    files = {file_name: _sha(raw)}
    served_files = _hf_host.apply_edits({file_name: raw}, src["edits"], src["font_map"])
    _hf_lint.check(served_files)
    served = _hf_host.served_digest(served_files)
    entry = build_entry(src, commit, component, file_name, files, served)
    probe = dict(entry, determinism={"served_sha256": served, "runtime_sha256": "0" * 64, "samples": 1, "frames": 1, "runs": 4, "blocked": 0,
                                     "date": "2000-01-01", "image": "probe", "seconds": 0})
    _blocks.check_block(probe, "admit:entry", "hf", registry_commit=commit)           # the schema of an entry, before any container is started
    taken = holds_name(entry["name"], blocks_dir or _blocks.blocks_dir())
    ident = entry["name"].split(":", 1)[1]
    if not ID.fullmatch(ident):
        raise Refusal("admit_entry", "name")
    staged = bool(stage or taken)
    target = os.path.join(runtime, STAGED_FOLDER, ident + ".json") if staged else os.path.join(blocks_dir or _blocks.blocks_dir(), "hf", "allowlist.json")
    rows = {"%s/%s" % (component, n): d for n, d in files.items()}
    return {"entry": entry, "raw": {file_name: raw}, "commit": commit, "id": ident, "name_taken": taken, "staged": staged, "rows": rows, "target": target,
            "runtime": runtime, "blocks_dir": blocks_dir or _blocks.blocks_dir(),
            "summary": {"ok": True, "plan": True, "name": entry["name"], "component": component, "files": files, "served_sha256": served,
                        "edits": entry["edits"], "samples": len(entry["samples"]), "commit": commit, "name_taken": taken,
                        "writes": ["registry.sha256", "NOTICE.md", "staged/%s.json" % ident if staged else "blocks/hf/allowlist.json"]}}


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


# ---------------------------------------------------------------- step 4: what is written

def record_of(result: dict, planned: dict, image: str, date: str = None) -> dict:
    """The determinism record from the container's measurement, checked against the plan: the same served hash, four runs, no blocked request, the
    samples of the entry. `date` is `date +%F` of the day it was measured."""
    served = planned["entry"]["served_sha256"]
    ok = result.get("served_sha256") == served and result.get("runs") == 4 and result.get("blocked") == 0 \
        and result.get("samples") == len(planned["entry"]["samples"]) and isinstance(result.get("frames"), int) and result["frames"] > 0
    if not ok or not isinstance(result.get("runtime_sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", result["runtime_sha256"]):
        raise Refusal("admit_result", "determinism")
    return {"served_sha256": served, "runtime_sha256": result["runtime_sha256"], "samples": result["samples"], "frames": result["frames"], "runs": 4,
            "blocked": 0, "date": date or time.strftime("%Y-%m-%d"), "image": image, "seconds": float(result["seconds"])}


def notice_text(current: str, planned: dict, record: dict) -> str:
    mark = NOTICE_MARK % planned["entry"]["name"]
    if mark in current:
        return current
    e = planned["entry"]
    section = ("\n%s\n## Admitted component `%s`\n\n"
               "`%s` of the registry repository at commit `%s` (Apache License 2.0, notices in the repository's own LICENSE, which the image carries). "
               "Fetched at image build from the raw-file URL at that commit, pinned by sha256 in `registry.sha256`; not committed here. Served with the edits %s "
               "(the CDN GSAP line becomes the vendored one; a font family name becomes the host's) and no other. Determinism test recorded %s: %d samples, "
               "%d frames, 4 runs.\n") % (mark, e["name"], "%s/%s" % (e["component"], e["implementations"]["hf"]), planned["commit"],
                                          ", ".join("`%s`" % x for x in e["edits"]) or "none", record["date"], record["samples"], record["frames"])
    return current.rstrip("\n") + "\n" + section


def _write(path: str, text: str) -> None:
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".admit-", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def write_all(planned: dict, record: dict) -> dict:
    """Write what the admission changes, all computed before the first write (a refusal leaves every file as it was). Returns the paths written."""
    entry = dict(planned["entry"], determinism=record)
    _blocks.check_block(entry, "admit:entry", "hf", registry_commit=planned["commit"])
    runtime = planned["runtime"]
    manifest_path = os.path.join(runtime, "registry.sha256")
    manifest = manifest_text(manifest_path, planned["rows"])
    notice_path = os.path.join(runtime, "NOTICE.md")
    with open(notice_path, encoding="utf-8") as fh:
        notice = notice_text(fh.read(), planned, record)
    target = planned["target"]
    if planned["staged"]:
        text = json.dumps(entry, indent=1, sort_keys=True) + "\n"           # ASCII only: a sample with accents is written as escapes (the repository is English-only text)
        if os.path.exists(target):
            with open(target, encoding="utf-8") as fh:
                if fh.read() != text:
                    raise Refusal("staged_exists", planned["id"])
        outputs = [(manifest_path, manifest), (notice_path, notice), (target, text)]
    else:
        with open(target, encoding="utf-8") as fh:
            allow = json.load(fh)
        if allow.get("registry_commit") not in (None, planned["commit"]):
            raise Refusal("admitted_commit", "allowlist")
        if any(b.get("name") == entry["name"] for b in allow["blocks"]):
            raise Refusal("name_taken", entry["name"].replace(":", "-")[:80])
        allow["registry_commit"] = planned["commit"]
        allow["blocks"] = sorted(allow["blocks"] + [entry], key=lambda b: b["name"])
        outputs = [(manifest_path, manifest), (notice_path, notice), (target, json.dumps(allow, indent=1) + "\n")]
    for path, text in outputs:
        _write(path, text)
    written = [p for p, _ in outputs]
    if not planned["staged"]:
        _blocks.write_pins(planned["blocks_dir"])
        _blocks.write_catalogue(planned["blocks_dir"])
        written += [os.path.join(planned["blocks_dir"], "pins.json"), os.path.join(planned["blocks_dir"], "catalogue.json")]
    return {"written": written, "staged": planned["staged"], "entry": entry}


def read_staged(path: str, registry_commit: str) -> dict:
    """A staged entry, checked by the same rules as an allowlist entry (`block_schema` otherwise). The catalogue never loads one: it reads the
    pinned files of `blocks/` only, and this folder is not there."""
    try:
        with open(path, encoding="utf-8") as fh:
            obj = json.load(fh)
    except (OSError, ValueError):
        raise Refusal("block_schema", "staged") from None
    return _blocks.check_block(obj, "staged:" + os.path.basename(path)[:60], "hf", registry_commit=registry_commit)
