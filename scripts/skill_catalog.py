#!/usr/bin/env python3
"""Write the catalog of the workbench's skills, flows and planned skills, with their proof per model.

The catalog is one compact text that a model reads as data: what each skill does, what it reads and writes, which
effects need an approval, whether the task runtime can run it, how well it is proven on each model, which flows
exist and which skills are planned. The process diagnosis (backlog NS40) maps a person's processes onto it; a person
can also read it by hand. It reads the workbench, not a project.

Usage:
  python3 scripts/skill_catalog.py [--root <workbench>] [--status <file> | --proof <file>] [--date YYYY-MM-DD]
                                   [--out <path>] [--max-chars <n>]

  --root       the workbench checkout (default: the one this script is in)
  --status     the JSON that `python3 evals/eval_status.py status` prints; the bands of each skill on each model
  --proof      the runtime's proof file (<data folder>/proof.json); the bands of each pair, with their source
               (lab, local or community). --status and --proof exclude each other. With neither, every proof
               line reads `unknown (no status given)`: this script never computes a band, the proof has one source
  --date       the date of the header (default: today, from the clock)
  --out        write the catalog to this file instead of standard output
  --max-chars  the size limit in characters (default 40000). Over it, the script exits 2 and writes nothing: the
               catalog is never cut in silence

Sources, all read from --root: skills/*/SKILL.md (the frontmatter), flows/*.json, the `(planned)` rows of
skills/core-orchestrator/references/routing.md (with the backlog id of the row in docs/inventory.md),
evals/eval-gate.json (the models, their adapters, the measurement version), packs/*.txt and runtime/roles.json (a
skill is `runtime: yes` when it is in a pack in use and its runtime manifest, skills/<name>/evals/runtime-manifest.json,
has every key; the runtime's own check of the manifest is runtime/manifest.py).

Output: a header, then one entry per line, sorted by name (two runs on the same tree and inputs are identical):

  - skill `<name>` | <area> | <kind> | v<version> | runtime: yes|no | effects: <list>|none | requires: <list>|none | in: <paths>|none | out: <paths>|none | does: <sentence>
    - proof `<model>`: <band> (<runs> runs, source <source>)
  - flow `<name>` | <title> | tasks: <key> (<skill>) -> <key> (step <kind>) -> ...
  - planned `<name>` | <area> | intent: <the routing table's intent> | backlog: <id>|none

`does` is the first sentence of the skill's description, cut at 200 characters on a word with "...".

Exit codes: 0 ok, 2 usage error, unreadable input or catalog over the limit. Diagnostics go to standard error.
Standard library only (the frontmatter reader is scripts/validate.py's). Runs on Python 3.9.
"""
import datetime
import fnmatch
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from validate import load_yaml, split_frontmatter  # noqa: E402

DEFAULT_ROOT = os.path.dirname(HERE)
DEFAULT_MAX = 40000
DOES_MAX = 200
MANIFEST_KEYS = ("skill", "documents", "machine_files", "mandatory_milestone", "asking_openings", "gate")
ROUTING = os.path.join("skills", "core-orchestrator", "references", "routing.md")
NAME = re.compile(r"[a-z][a-z0-9-]*\Z")


class CatalogError(Exception):
    """An input is unreadable or the catalog is over the limit; the message is for standard error."""


def note(message):
    print("note: " + message, file=sys.stderr)


def one_line(text):
    """Collapse whitespace; a pipe would break the grammar, so it becomes a slash."""
    return re.sub(r"\s+", " ", str(text).replace("\\|", "/").replace("|", "/")).strip()


def first_sentence(description, limit=DOES_MAX):
    """The description's first sentence, at most `limit` characters: cut on a word and ended with "..."."""
    text = one_line(description)
    match = re.search(r"(?<=[.!?])\s", text)
    if match:
        text = text[:match.start()]
    if len(text) <= limit:
        return text
    cut = text[:limit - 3]
    if text[limit - 3] != " " and " " in cut:
        cut = cut[:cut.rindex(" ")]
    return cut.rstrip(" ,;:") + "..."


def as_list(value):
    if isinstance(value, list):
        return [str(v) for v in value if str(v).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def joined(values):
    return ", ".join(one_line(v) for v in values) if values else "none"


def read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except OSError as e:
        raise CatalogError("cannot read %s: %s" % (path, e.strerror or e))
    except ValueError as e:
        raise CatalogError("%s is not valid JSON: %s" % (path, e))


def number(value):
    if isinstance(value, float) and value == int(value):
        value = int(value)
    return str(value)


# --- the workbench ---------------------------------------------------------------------

def read_skills(root):
    """name -> {area, kind, version, in, out, requires, effects, description}, for every skills/*/SKILL.md."""
    out = {}
    folder = os.path.join(root, "skills")
    if not os.path.isdir(folder):
        raise CatalogError("%s has no skills folder" % root)
    for name in sorted(os.listdir(folder)):
        path = os.path.join(folder, name, "SKILL.md")
        if not os.path.isfile(path):
            continue
        fm_text, _ = split_frontmatter(path)
        try:
            front = (load_yaml(fm_text) or {}) if fm_text else None
        except Exception as e:  # noqa: BLE001  (any parse failure: name the skill and go on)
            front = None
            note("skills/%s/SKILL.md: frontmatter not readable (%s); skipped" % (name, e))
        if not isinstance(front, dict):
            if fm_text is None:
                note("skills/%s/SKILL.md has no frontmatter; skipped" % name)
            continue
        meta = front.get("metadata") or {}
        out[name] = {
            "area": one_line(meta.get("area") or "unknown"),
            "kind": one_line(meta.get("kind") or "unknown"),
            "version": one_line(meta.get("version") or "unknown"),
            "in": as_list(meta.get("inputs")),
            "out": as_list(meta.get("outputs")),
            "requires": as_list(meta.get("requires")),
            "effects": as_list(meta.get("side_effects")),
            "description": front.get("description") or "",
        }
    return out


def read_packs(root):
    """pack name -> (inclusion patterns, exclusion patterns), from packs/*.txt (the format of scripts/select_skills.py)."""
    packs = {}
    folder = os.path.join(root, "packs")
    if not os.path.isdir(folder):
        return packs
    for file in sorted(os.listdir(folder)):
        if not file.endswith(".txt"):
            continue
        inc, exc = [], []
        with open(os.path.join(folder, file), encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s or s.startswith("#"):
                    continue
                (exc if s.startswith("!") else inc).append(s.lstrip("!"))
        packs[file[:-4]] = (inc, exc)
    return packs


def pack_members(pack, skills):
    inc, exc = pack

    def hit(pattern, name):
        if pattern.startswith("area:"):
            return skills[name]["area"] == pattern[5:]
        return fnmatch.fnmatchcase(name, pattern)
    chosen = set(n for n in skills if any(hit(p, n) for p in inc))
    return chosen - set(n for n in skills if any(hit(p, n) for p in exc))


def runtime_skills(root, skills):
    """The skills the task runtime can run: those of a pack in `packs_in_use` (runtime/roles.json) whose runtime manifest
    has every key. No roles file, no pack, no manifest: not runnable (the catalog says `no`, never guesses `yes`)."""
    path = os.path.join(root, "runtime", "roles.json")
    if not os.path.isfile(path):
        note("runtime/roles.json not found: every skill reads `runtime: no`")
        return set()
    in_use = read_json(path).get("packs_in_use") or []
    packs = read_packs(root)
    names = set()
    for pack in in_use:
        if pack in packs:
            names |= pack_members(packs[pack], skills)
        else:
            note("pack `%s` of packs_in_use has no file in packs/" % pack)
    whole = set()
    for name in sorted(names):
        manifest = os.path.join(root, "skills", name, "evals", "runtime-manifest.json")
        try:
            data = read_json(manifest)
        except CatalogError:
            continue
        if isinstance(data, dict) and data.get("skill") == name and all(k in data for k in MANIFEST_KEYS):
            whole.add(name)
    return whole


def read_flows(root):
    """[(name, title, [task text, ...])] from flows/*.json, sorted by name."""
    out = []
    folder = os.path.join(root, "flows")
    if not os.path.isdir(folder):
        return out
    for file in sorted(os.listdir(folder)):
        if not file.endswith(".json"):
            continue
        try:
            data = read_json(os.path.join(folder, file))
        except CatalogError as e:
            note("%s; flow skipped" % e)
            continue
        if not isinstance(data, dict) or not isinstance(data.get("tasks"), list):
            note("flows/%s has no task list; flow skipped" % file)
            continue
        tasks = []
        for task in data["tasks"]:
            if not isinstance(task, dict):
                continue
            key = one_line(task.get("key") or "?")
            if task.get("skill"):
                tasks.append("%s (%s)" % (key, one_line(task["skill"])))
            else:
                tasks.append("%s (step %s)" % (key, one_line(task.get("step") or "?")))
        out.append((one_line(data.get("flow") or file[:-5]), one_line(data.get("title") or ""), tasks))
    return sorted(out, key=lambda f: f[0])


def read_backlog_ids(root):
    """name -> backlog id, from the rows of docs/inventory.md that read `(backlog <id>` (first match wins)."""
    ids = {}
    path = os.path.join(root, "docs", "inventory.md")
    if not os.path.isfile(path):
        note("docs/inventory.md not found: every planned skill reads `backlog: none`")
        return ids
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.startswith("|"):
                continue
            cells = re.split(r"(?<!\\)\|", line.strip().strip("|"))
            name = cells[0].strip().strip("`")
            found = re.search(r"backlog ([A-Z]+[0-9]+)", line)
            if found and NAME.match(name) and name not in ids:
                ids[name] = found.group(1)
    return ids


def read_planned(root, built):
    """[(name, area, intent, backlog id or None)]: the `(planned)` rows of the routing table, sorted by name. A planned
    name that is also a built skill is dropped with a note (the table's mark is stale; the built skill wins)."""
    path = os.path.join(root, ROUTING)
    if not os.path.isfile(path):
        note("%s not found: no planned skill listed" % ROUTING.replace(os.sep, "/"))
        return []
    ids = read_backlog_ids(root)
    out, seen, area = [], set(), "unknown"
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if line.startswith("## "):
                area = one_line(re.sub(r"\s*\(`[^)]*`\)\s*$", "", line[3:]))
                continue
            if not line.startswith("|"):
                continue
            cells = re.split(r"(?<!\\)\|", line.strip().strip("|"))
            if len(cells) != 2 or not cells[1].strip().endswith("(planned)"):
                continue
            name = cells[1].strip()[:-len("(planned)")].strip()
            if not NAME.match(name) or name in seen:
                continue
            seen.add(name)
            if name in built:
                note("`%s` is marked planned in the routing table but is built; not listed as planned" % name)
                continue
            out.append((name, area, one_line(cells[0]), ids.get(name)))
    return sorted(out, key=lambda p: p[0])


# --- the proof -----------------------------------------------------------------------

def proof_from_status(path):
    """skill -> [(model, band, runs, source)] from the JSON of `eval_status.py status`; source is `lab`."""
    data = read_json(path)
    if not isinstance(data, dict) or not isinstance(data.get("skills"), list):
        raise CatalogError("%s is not the JSON that `eval_status.py status` prints (no `skills` list)" % path)
    out = {}
    for entry in data["skills"]:
        if not isinstance(entry, dict) or not entry.get("skill"):
            continue
        rows = []
        for model, figures in (entry.get("models") or {}).items():
            if isinstance(figures, dict):
                rows.append((model, one_line(figures.get("band") or "unknown"), figures.get("runs") or 0, "lab"))
        out[entry["skill"]] = rows
    return out


def proof_from_file(path):
    """skill -> [(model, band, runs, source)] from the runtime's proof file (runtime/proof.py): skills[name].pairs."""
    data = read_json(path)
    if not isinstance(data, dict) or not isinstance(data.get("skills"), dict):
        raise CatalogError("%s is not a proof file (no `skills` object)" % path)
    out = {}
    for name, entry in data["skills"].items():
        rows = []
        for pair in (entry or {}).get("pairs") or []:
            if isinstance(pair, dict) and pair.get("model"):
                rows.append((pair["model"], one_line(pair.get("band") or "unknown"), pair.get("runs") or 0,
                             one_line(pair.get("source") or "none")))
        out[name] = rows
    return out


def order_models(rows, model_order):
    rank = dict((m, i) for i, m in enumerate(model_order))
    return sorted(rows, key=lambda r: (rank.get(r[0], len(rank)), r[0]))


# --- the catalog ---------------------------------------------------------------------

def git_commit(root):
    try:
        done = subprocess.run(["git", "-C", root, "rev-parse", "HEAD"], stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    sha = done.stdout.decode("ascii", "replace").strip()
    return sha[:12] if done.returncode == 0 and re.fullmatch(r"[0-9a-f]{40,64}", sha) else "unknown"


def gate_facts(root):
    """(measurement version, [(model, adapter)] with the lab models first) from evals/eval-gate.json."""
    path = os.path.join(root, "evals", "eval-gate.json")
    if not os.path.isfile(path):
        note("evals/eval-gate.json not found: no models listed")
        return "unknown", []
    gate = read_json(path)
    models = gate.get("models") or {}
    lab = [m for m in gate.get("lab_models") or [] if m in models]
    order = lab + sorted(m for m in models if m not in lab)
    return one_line(gate.get("measurement_version", "unknown")), [
        (m, one_line((models[m] or {}).get("adapter") or "unknown")) for m in order]


def build(root, status=None, proof=None, date=None):
    """The catalog text. `status` and `proof` are file paths (at most one)."""
    skills = read_skills(root)
    in_runtime = runtime_skills(root, skills)
    version, models = gate_facts(root)
    model_order = [m for m, _ in models]
    if status:
        table, source = proof_from_status(status), "status"
        for name in sorted(set(table) - set(skills)):
            note("`%s` is in the status but not on disk; skipped" % name)
    elif proof:
        table, source = proof_from_file(proof), "proof file"
        for name in sorted(set(table) - set(skills)):
            note("`%s` is in the proof file but not on disk; skipped" % name)
    else:
        table, source = None, "none"
    flows = read_flows(root)
    planned = read_planned(root, skills)

    lines = ["# Skill catalog", "",
             "- Commit: %s" % git_commit(root),
             "- Date: %s" % (date or datetime.date.today().isoformat()),
             "- Proof from: %s" % source,
             "- Measurement version: %s" % version,
             "- Models: %s" % (", ".join("`%s` (adapter %s)" % m for m in models) or "unknown"),
             "- Counts: %d skills, %d flows, %d planned skills" % (len(skills), len(flows), len(planned)),
             "", "## Skills", ""]
    for name in sorted(skills):
        s = skills[name]
        lines.append("- skill `%s` | %s | %s | v%s | runtime: %s | effects: %s | requires: %s | in: %s | out: %s | does: %s" % (
            name, s["area"], s["kind"], s["version"], "yes" if name in in_runtime else "no", joined(s["effects"]),
            joined(s["requires"]), joined(s["in"]), joined(s["out"]), first_sentence(s["description"])))
        if table is None:
            lines.append("  - proof: unknown (no status given)")
        elif name not in table:
            lines.append("  - proof: unknown (not in the %s)" % source)
        else:
            for model, band, runs, src in order_models(table[name], model_order):
                lines.append("  - proof `%s`: %s (%s runs, source %s)" % (model, band, number(runs), src))
    lines += ["", "## Flows", ""]
    for name, title, tasks in flows:
        lines.append("- flow `%s` | %s | tasks: %s" % (name, title, " -> ".join(tasks) or "none"))
    lines += ["", "## Planned skills", ""]
    for name, area, intent, backlog in planned:
        lines.append("- planned `%s` | %s | intent: %s | backlog: %s" % (name, area, intent, backlog or "none"))
    return "\n".join(lines) + "\n"


def write_atomic(path, text):
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    tmp = os.path.join(folder, ".skill-catalog-%d.tmp" % os.getpid())
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    os.replace(tmp, path)


def parse(argv):
    opts = {"root": DEFAULT_ROOT, "status": None, "proof": None, "date": None, "out": None, "max_chars": DEFAULT_MAX}
    flags = {"--root": "root", "--status": "status", "--proof": "proof", "--date": "date", "--out": "out",
             "--max-chars": "max_chars"}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a not in flags:
            raise CatalogError("unknown option %r. See --help." % a)
        if i + 1 >= len(argv):
            raise CatalogError("%s needs a value. See --help." % a)
        opts[flags[a]] = argv[i + 1]
        i += 2
    if opts["status"] and opts["proof"]:
        raise CatalogError("--status and --proof exclude each other. See --help.")
    if opts["date"] is not None and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", opts["date"]):
        raise CatalogError("--date must be YYYY-MM-DD, got %r" % opts["date"])
    try:
        opts["max_chars"] = int(opts["max_chars"])
    except ValueError:
        raise CatalogError("--max-chars must be a whole number, got %r" % opts["max_chars"])
    if opts["max_chars"] < 1:
        raise CatalogError("--max-chars must be at least 1")
    return opts


def main(argv):
    if "--help" in argv or "-h" in argv:
        print(__doc__)
        return 0
    try:
        opts = parse(argv)
        text = build(os.path.abspath(opts["root"]), opts["status"], opts["proof"], opts["date"])
        if len(text) > opts["max_chars"]:
            raise CatalogError("the catalog is %d characters, over the limit of %d; nothing written. Raise --max-chars "
                               "on purpose, or shorten the descriptions" % (len(text), opts["max_chars"]))
    except CatalogError as e:
        print("Error: %s" % e, file=sys.stderr)
        return 2
    if opts["out"]:
        write_atomic(opts["out"], text)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
