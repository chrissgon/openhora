"""What the dynamic run of tier A (step 7.8) is made of, shared by its live test and its offline tests: the temporary blocks folder that holds one
candidate as a test allowlist entry (never the committed allowlist), the temporary registry folder with the candidate's two files (checked against the
hashes of the compatibility report), the planted component that the text lint admits and the guard stops, and the closed report."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from pathlib import Path

import renderer_kit as K
import _blocks

REGISTRY_COMMIT = "b4cc674f7f312e77ded32e0b53006cc0bad6723b"
NOTICE = "Apache-2.0; adapted from the HyperFrames registry at b4cc674f; notices in providers/renderer/hyperframes-image/NOTICE.md"
PLANTED_NAME = "planted-escape"
# A planted run-time escape the text lint admits: the tag is built from two strings, so no rule sees `canvas`; the guard's `createElement` allows
# only a short list of tags and stops it (`hf-escape`), which sets the page flag the measure step reads.
PLANTED_SNIPPET = 'var t = "can" + "vas"; document.createElement(t);'
CODE = re.compile(r"refuse:[a-z_]{1,40}")
NAME = re.compile(r"[a-z][a-z0-9-]{0,39}")
HEX64 = re.compile(r"[0-9a-f]{64}")


def short_of(comp: dict) -> str:
    assert NAME.fullmatch(comp["name"]), comp["name"]
    return comp["name"]


def entry_for(comp: dict) -> dict:
    """The test allowlist entry of a candidate: the keyword preset (a beat of it needs a text and an icon, which the entry declares), tier A, the
    component's own two files by hash. The component's variables are not the preset's, so the dynamic run draws it with its own defaults."""
    short = short_of(comp)
    return {"name": "hf:" + short, "kind": "overlay", "preset": "keyword", "band": "card", "may_cross_face": False, "license": ["Apache-2.0"],
            "source": "hyperframes-registry", "use_when": "a registry component drawn on one beat by the dynamic run, used by the tests only",
            "params": {"text": {"type": "text", "max": 24, "required": True}, "icon": {"type": "icon"}}, "samples": [{"text": "Name every dollar"}],
            "natural_duration": float(comp["natural_duration"]), "implementations": {"gsap": short + ".html"}, "tier": "A", "commit": REGISTRY_COMMIT,
            "notice": NOTICE, "files": dict(comp["files"])}


def blocks_folder(tmp, comp: dict) -> str:
    """A copy of the committed blocks with `comp` as the one tier-A entry and the HyperFrames engine drawing the keyword preset with it (gsap and
    renderat runtimes), pinned again. The committed allowlist is not touched."""
    folder = Path(tmp) / ("blocks-" + short_of(comp))
    shutil.copytree(K.BLOCKS, folder)
    allow = json.loads((folder / "hf" / "allowlist.json").read_text(encoding="utf-8"))
    allow.update(registry_commit=REGISTRY_COMMIT, blocks=[entry_for(comp)])
    (folder / "hf" / "allowlist.json").write_text(json.dumps(allow, indent=1), encoding="utf-8")
    presets = dict(K.OH_PRESETS, keyword="hf:" + short_of(comp))
    (folder / "engines" / "hyperframes.json").write_text(json.dumps(
        {"schema_version": 1, "engine": "hyperframes", "note": "the dynamic run of tier A, used by the tests only", "runtimes": ["gsap", "renderat"], "presets": presets}, indent=1),
        encoding="utf-8")
    _blocks.write_pins(str(folder))
    _blocks.load_catalogue(str(folder))
    return str(folder)


def registry_folder(tmp, survey, comps: list) -> str:
    """`<tmp>/registry-<n>/registry/components/<short>/<file>` for each candidate, copied from the survey folder, each file checked against the
    sha256 the compatibility report recorded (AssertionError otherwise). The result is mounted over `/opt/hf-registry` in test mode."""
    root = Path(tmp) / ("registry-" + hashlib.sha256("|".join(sorted(c["name"] for c in comps)).encode()).hexdigest()[:8])
    for comp in comps:
        folder = root / "registry" / "components" / short_of(comp)
        folder.mkdir(parents=True)
        for rel, digest in sorted(comp["files"].items()):
            raw = (Path(survey) / short_of(comp) / rel).read_bytes()
            assert hashlib.sha256(raw).hexdigest() == digest, "the survey's %s/%s differs from the report" % (comp["name"], rel)
            (folder / rel).write_bytes(raw)
    for path in [root, *root.rglob("*")]:
        os.chmod(path, 0o755 if path.is_dir() else 0o644)
    return str(root)


def planted_component() -> dict:
    """A comp-like dict of the planted escape, with the files written into `files_text` form by `planted_files`."""
    files = planted_files()
    return {"name": PLANTED_NAME, "files": {rel: hashlib.sha256(raw).hexdigest() for rel, raw in files.items()}, "natural_duration": 2.5}


def planted_files() -> dict:
    import importlib.util
    spec = importlib.util.spec_from_file_location("hf_compat_for_kit", K.RENDERER / "hyperframes-image" / "hf_compat.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    html = module.planted_component(("x", "script", PLANTED_SNIPPET, None, False))[1]
    return {PLANTED_NAME + ".html": html.encode("utf-8"), "registry-item.json": json.dumps({"name": PLANTED_NAME, "type": "hyperframes:component"}).encode("utf-8")}


def planted_survey(tmp) -> str:
    folder = Path(tmp) / "planted-survey" / PLANTED_NAME
    folder.mkdir(parents=True)
    for rel, raw in planted_files().items():
        (folder / rel).write_bytes(raw)
    return str(folder.parent)


def candidate_row(comp: dict, runs: list) -> dict:
    """The report row of one candidate from its two renders, each `(returncode, result object or None)`: `fit` when both rendered, drew the block on a
    beat, passed the gates and gave the same bytes; else `refuse:<the refusal code>` (`not_repeatable`, `not_drawn`, `no_result`)."""
    row = {"name": comp["name"], "dynamic": "", "render_sha256": None, "repeatable": None, "gate": {}}
    outs = [out for rc, out in runs if rc == 0 and isinstance(out, dict)]
    failed = [out for rc, out in runs if rc != 0]
    if failed:
        code = failed[0].get("code") if isinstance(failed[0], dict) else None
        row["dynamic"] = "refuse:" + (code if isinstance(code, str) and re.fullmatch(r"[a-z_]{1,40}", code) else "no_result")
        return row
    if len(outs) != 2:
        row["dynamic"] = "refuse:no_result"
        return row
    row["render_sha256"] = outs[0].get("sha256") if isinstance(outs[0].get("sha256"), str) and HEX64.fullmatch(outs[0]["sha256"]) else None
    row["repeatable"] = outs[0].get("sha256") == outs[1].get("sha256")
    gate = outs[0].get("gate") if isinstance(outs[0].get("gate"), dict) else {}
    row["gate"] = {k: gate[k] for k in ("frames", "boxes", "lowest_caption_bottom", "pixel_min_psnr_db", "pixel_ranges") if isinstance(gate.get(k), (int, float))}
    drawn = outs[0].get("beats_drawn", 0) >= 1 and outs[0].get("runtimes", {}).get("hf:" + comp["name"]) == "gsap"
    row["dynamic"] = "fit" if row["repeatable"] and drawn and row["render_sha256"] else ("refuse:not_drawn" if not drawn else "refuse:not_repeatable")
    return row


def check_report(doc) -> dict:
    """The dynamic report is closed: names, closed codes, hashes and numbers; nothing a component or a log said."""
    def bad():
        raise ValueError("dynamic report")
    if not isinstance(doc, dict) or not set(doc) <= {"schema", "commit", "candidates", "planted"} or doc.get("schema") != 1 or doc.get("commit") != REGISTRY_COMMIT:
        bad()
    for row in doc.get("candidates", []):
        if not isinstance(row, dict) or set(row) != {"name", "dynamic", "render_sha256", "repeatable", "gate"} or not NAME.fullmatch(row["name"]) \
                or not (row["dynamic"] == "fit" or CODE.fullmatch(row["dynamic"])) or not (row["render_sha256"] is None or HEX64.fullmatch(str(row["render_sha256"]))) \
                or row["repeatable"] not in (None, True, False) or not isinstance(row["gate"], dict) \
                or not all(isinstance(k, str) and isinstance(v, (int, float)) and not isinstance(v, bool) for k, v in row["gate"].items()):
            bad()
    planted = doc.get("planted")
    if planted is not None and (not isinstance(planted, dict) or set(planted) != {"name", "code", "field"} or planted["name"] != PLANTED_NAME
                                or not re.fullmatch(r"[a-z_]{1,40}", str(planted["code"])) or not re.fullmatch(r"[A-Za-z0-9_.:\- ]{0,40}", str(planted["field"]))):
        bad()
    return doc


def update_report(path: str, **parts) -> dict:
    """Merge `parts` (`candidates` replaces the list, `planted` the row) into the report at `path`, written whole each time (a new file the first time)."""
    doc = {"schema": 1, "commit": REGISTRY_COMMIT}
    if os.path.exists(path):
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    doc.update(parts)
    check_report(doc)
    tmp = path + ".part"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, sort_keys=True, indent=1)
        fh.write("\n")
    os.replace(tmp, path)
    return doc
