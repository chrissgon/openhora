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
  --max-chars  the size limit in characters (default 60000: the real tree is about 33000 with two models, and each
               further model of the gate file adds one proof line to every skill, about 3.9 KB). Over it, the script
               exits 2 and writes nothing: the catalog is never cut in silence

Sources, all read from --root: skills/*/SKILL.md (the frontmatter), flows/*.json, the `(planned)` rows of
skills/core-orchestrator/references/routing.md (with the backlog id of the row in docs/inventory.md),
evals/eval-gate.json (the models, their adapters, the measurement version), packs/*.txt and runtime/roles.json.
`runtime:` follows the runtime's rule (runtime/manifest.py, runtime/ops.py `_contained_scope`): `yes` when the skill is
in a pack of `packs_in_use` and its runtime manifest (skills/<name>/evals/runtime-manifest.json) has every key, so a
task runs it; `contained` when its manifest is whole and it is in another pack that a project can give an area agent
(any pack but the catch-all `default` and `all`), so only a contained run of it is possible; `no` otherwise.

Output: a header, then one entry per line, sorted by name (two runs on the same tree and inputs are identical):

  - skill `<name>` | <area> | <kind> | v<version> | runtime: yes|contained|no | effects: <list>|none | requires: <list>|none | in: <paths>|none | out: <paths>|none | does: <sentence>
    - proof `<model>`: <band> (<runs> runs, source <source>)   or   unknown (no evidence in the status|proof file)
  - flow `<name>` | <title> | tasks: <key> (<skill>) -> <key> (step <kind>) -> ...
  - planned `<name>` | <area> | intent: <the routing table's intent> | backlog: <id>|none

`does` is the first sentence of the skill's description, cut at 200 characters on a word with "...".

A proof line of a skill whose proof was computed for another version than the frontmatter's ends with
` (proof of v<x>)`. `Commit:` ends with ` (uncommitted changes)` when skills/ or flows/ differ from HEAD.

Exit codes: 0 ok, 2 usage error, unreadable or malformed input, or catalog over the limit. Diagnostics go to standard error.
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
DEFAULT_MAX = 60000
DOES_MAX = 200
MANIFEST_KEYS = ("skill", "documents", "machine_files", "mandatory_milestone", "asking_openings", "gate")
ROUTING = os.path.join("skills", "core-orchestrator", "references", "routing.md")
NAME = re.compile(r"[a-z][a-z0-9-]*\Z")
PROOF_VERSION = 4  # the version of the runtime's proof file (runtime/proof.py VERSION); a test compares the two
PREFIX_AREA = {"biz-": "business", "product-": "product", "brand-": "brand", "design-": "design", "eng-": "engineering",
               "ops-": "delivery", "mkt-": "marketing", "ai-": "ai", "core-": "core", "asst-": "assistant"}  # AGENTS.md table
CATCH_ALL_PACKS = ("default", "all")  # runtime/plan.py CATCH_ALL_PACKS: a test compares the two


class CatalogError(Exception):
    """An input is unreadable or the catalog is over the limit; the message is for standard error."""


def note(message):
    print("note: " + message, file=sys.stderr)


def one_line(text):
    """Collapse whitespace; a pipe would break the grammar, so it becomes a slash, or `\\|` inside a code span."""
    text = re.sub(r"\s+", " ", str(text).replace("\\|", "|")).strip()
    parts = re.split(r"(`[^`]*`)", text)
    return "".join(p.replace("|", "\\|") if p.startswith("`") and p.endswith("`") and len(p) > 1 else p.replace("|", "/")
                   for p in parts)


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


def count(value):
    """A run count as text: a non-negative whole number, else `unknown`."""
    if isinstance(value, float) and value == int(value):
        value = int(value)
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return str(value)
    return "unknown"


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
        try:
            fm_text, _ = split_frontmatter(path)
            front = (load_yaml(fm_text) or {}) if fm_text else None
        except Exception as e:  # noqa: BLE001  (any parse failure: name the skill and go on)
            note("skills/%s/SKILL.md: frontmatter not readable (%s); skipped" % (name, e))
            continue
        if front is None:
            note("skills/%s/SKILL.md has no frontmatter; skipped" % name)
            continue
        meta = front.get("metadata") if isinstance(front, dict) else None
        if not isinstance(meta, dict):
            note("skills/%s/SKILL.md: the frontmatter has no `metadata` object; skipped" % name)
            continue
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
    """name -> `yes`, `contained` or `no`, the runtime's rule (runtime/manifest.py, runtime/ops.py `_contained_scope`):
    `yes`: in a pack of `packs_in_use` (runtime/roles.json) and a whole runtime manifest, so a task runs it;
    `contained`: a whole manifest and a place in another pack a project can give an area agent (any pack but the
    catch-all ones), so a contained run of it is possible; `no`: otherwise. No roles file: every skill reads `no`
    (the catalog never guesses `yes`)."""
    result = dict((name, "no") for name in skills)
    path = os.path.join(root, "runtime", "roles.json")
    if not os.path.isfile(path):
        note("runtime/roles.json not found: every skill reads `runtime: no`")
        return result
    roles = read_json(path)
    in_use = roles.get("packs_in_use") if isinstance(roles, dict) else None
    if not isinstance(in_use, list) or not all(isinstance(p, str) for p in in_use):
        raise CatalogError("%s has no `packs_in_use` list of pack names" % path)
    packs = read_packs(root)
    used, other = set(), set()
    for pack in in_use:
        if pack in packs:
            used |= pack_members(packs[pack], skills)
        else:
            note("pack `%s` of packs_in_use has no file in packs/" % pack)
    for pack in packs:
        if pack not in in_use and pack not in CATCH_ALL_PACKS:
            other |= pack_members(packs[pack], skills)
    for name in sorted(used | other):
        manifest = os.path.join(root, "skills", name, "evals", "runtime-manifest.json")
        try:
            data = read_json(manifest)
        except CatalogError:
            continue
        if isinstance(data, dict) and data.get("skill") == name and all(k in data for k in MANIFEST_KEYS):
            result[name] = "yes" if name in used else "contained"
    return result


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


def area_words(skills):
    """prefix -> the `metadata.area` word most skills of that prefix carry (`biz-` -> business): one vocabulary."""
    tally = {}
    for name, s in skills.items():
        counts = tally.setdefault(name.split("-")[0] + "-", {})
        counts[s["area"]] = counts.get(s["area"], 0) + 1
    return dict((prefix, sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]) for prefix, c in tally.items())


def read_planned(root, skills):
    """[(name, area, intent, backlog id or None)]: the `(planned)` rows of the routing table, sorted by name. The area is
    the `metadata.area` word of the section's prefix (the built skills' word, else the AGENTS.md table's; else the
    section's title in lowercase). A planned name that is also
    a built skill is dropped with a note (the table's mark is stale; the built skill wins)."""
    path = os.path.join(root, ROUTING)
    if not os.path.isfile(path):
        note("%s not found: no planned skill listed" % ROUTING.replace(os.sep, "/"))
        return []
    ids = read_backlog_ids(root)
    words = area_words(skills)
    out, seen, area = [], set(), "unknown"
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if line.startswith("## "):
                prefix = re.search(r"\(`([a-z]+-)`\)\s*$", line)
                title = one_line(re.sub(r"\s*\(`[^)]*`\)\s*$", "", line[3:]))
                area = (words.get(prefix.group(1)) or PREFIX_AREA.get(prefix.group(1))) if prefix else None
                area = area or title.lower()
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
            if name in skills:
                note("`%s` is marked planned in the routing table but is built; not listed as planned" % name)
                continue
            out.append((name, area, one_line(cells[0]), ids.get(name)))
    return sorted(out, key=lambda p: p[0])


# --- the proof -----------------------------------------------------------------------

def proof_from_status(path):
    """skill -> (version or None, {model: (band, runs, source)}) from the JSON of `eval_status.py status`; source `lab`."""
    data = read_json(path)
    if not isinstance(data, dict) or not isinstance(data.get("skills"), list):
        raise CatalogError("%s is not the JSON that `eval_status.py status` prints (no `skills` list)" % path)
    out = {}
    for entry in data["skills"]:
        if not isinstance(entry, dict) or not isinstance(entry.get("skill"), str):
            raise CatalogError("%s: an entry of `skills` is not an object with a `skill` name" % path)
        models = entry.get("models")
        if models is None:
            models = {}
        if not isinstance(models, dict):
            raise CatalogError("%s: `models` of `%s` is not an object" % (path, entry["skill"]))
        rows = {}
        for model, figures in models.items():
            if isinstance(figures, dict):
                rows[model] = (one_line(figures.get("band") or "unknown"), figures.get("runs"), "lab")
        version = entry.get("version")
        out[entry["skill"]] = (one_line(version) if isinstance(version, str) else None, rows)
    return out


def proof_from_file(path):
    """skill -> (version or None, {model: (band, runs, source)}) from the runtime's proof file (runtime/proof.py):
    skills[name].pairs. A file of another version is refused, as the runtime refuses it."""
    data = read_json(path)
    if not isinstance(data, dict) or not isinstance(data.get("skills"), dict):
        raise CatalogError("%s is not a proof file (no `skills` object)" % path)
    if data.get("version") != PROOF_VERSION:
        raise CatalogError("%s is a proof file of version %r; this script reads version %d. Let the runtime rebuild it "
                           "(its `proof` verb) or use --status" % (path, data.get("version"), PROOF_VERSION))
    out = {}
    for name, entry in data["skills"].items():
        pairs = entry.get("pairs") if isinstance(entry, dict) else None
        rows = {}
        for pair in pairs if isinstance(pairs, list) else []:
            if isinstance(pair, dict) and isinstance(pair.get("model"), str) and pair["model"]:
                rows[pair["model"]] = (one_line(pair.get("band") or "unknown"), pair.get("runs"),
                                       one_line(pair.get("source") or "none"))
        if not rows:
            note("`%s` has no usable pair in the proof file" % name)
        version = entry.get("skill_version") if isinstance(entry, dict) else None
        out[name] = (one_line(version) if isinstance(version, str) else None, rows)
    return out


def order_models(models, model_order):
    """The models of a proof row: the gate file's, in its order, then any other the row names, sorted."""
    return list(model_order) + sorted(m for m in models if m not in model_order)


# --- the catalog ---------------------------------------------------------------------

def git_commit(root):
    """The first 12 characters of HEAD, with ` (uncommitted changes)` when skills/ or flows/ differ from it; else `unknown`."""
    def git(*args):
        env = dict((k, v) for k, v in os.environ.items() if not k.startswith("GIT_"))  # never the caller's repository
        return subprocess.run(["git", "-C", root] + list(args), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=60,
                              env=env)
    try:
        done = git("rev-parse", "HEAD")
        sha = done.stdout.decode("ascii", "replace").strip()
        if done.returncode != 0 or not re.fullmatch(r"[0-9a-f]{40,64}", sha):
            return "unknown"
        dirty = git("status", "--porcelain", "--", "skills", "flows")
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return sha[:12] + (" (uncommitted changes)" if dirty.returncode == 0 and dirty.stdout.strip() else "")


def gate_facts(root):
    """(measurement version, [(model, adapter)] with the lab models first) from evals/eval-gate.json. A model's entry is
    an object (its `adapter`) or the older list of aliases (adapter `unknown`), as evals/eval_status.py reads both."""
    path = os.path.join(root, "evals", "eval-gate.json")
    if not os.path.isfile(path):
        note("evals/eval-gate.json not found: no models listed")
        return "unknown", []
    gate = read_json(path)
    if not isinstance(gate, dict):
        raise CatalogError("%s is not a JSON object" % path)
    models = gate.get("models")
    if models is None:
        models = {}
    if not isinstance(models, dict):
        raise CatalogError("%s: `models` is not an object" % path)
    lab = gate.get("lab_models") or []
    if not isinstance(lab, list):
        raise CatalogError("%s: `lab_models` is not a list" % path)
    lab = [m for m in lab if m in models]
    order = lab + sorted(m for m in models if m not in lab)
    adapters = [(m, one_line(models[m].get("adapter") or "unknown") if isinstance(models[m], dict) else "unknown")
                for m in order]
    return one_line(gate.get("measurement_version", "unknown")), adapters


def proof_lines(name, skill, table, source, model_order):
    """The proof lines of one skill (two spaces of indent, one per model of the gate file or the proof)."""
    if table is None:
        return ["  - proof: unknown (no status given)"]
    if name not in table:
        return ["  - proof: unknown (not in the %s)" % source]
    version, rows = table[name]
    stale = " (proof of v%s)" % version if version and version != skill["version"] else ""
    lines = []
    for model in order_models(rows, model_order):
        if model in rows:
            band, runs, src = rows[model]
            lines.append("  - proof `%s`: %s (%s runs, source %s)%s" % (model, band, count(runs), src, stale))
        else:
            lines.append("  - proof `%s`: unknown (no evidence in the %s)%s" % (model, source, stale))
    return lines or ["  - proof: unknown (no evidence in the %s)%s" % (source, stale)]


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
             "- Runtime: `yes` = a task of the runtime can run the skill; `contained` = only a contained run of it is "
             "possible, when an area agent has its pack; `no` = the runtime does not run it (it runs in a coding tool)",
             "", "## Skills", ""]
    for name in sorted(skills):
        s = skills[name]
        lines.append("- skill `%s` | %s | %s | v%s | runtime: %s | effects: %s | requires: %s | in: %s | out: %s | does: %s" % (
            name, s["area"], s["kind"], s["version"], in_runtime[name], joined(s["effects"]),
            joined(s["requires"]), joined(s["in"]), joined(s["out"]), first_sentence(s["description"])))
        lines += proof_lines(name, s, table, source, model_order)
    lines += ["", "## Flows", ""]
    for name, title, tasks in flows:
        lines.append("- flow `%s` | %s | tasks: %s" % (name, title, " -> ".join(tasks) or "none"))
    lines += ["", "## Planned skills", ""]
    for name, area, intent, backlog in planned:
        lines.append("- planned `%s` | %s | intent: %s | backlog: %s" % (name, area, intent, backlog or "none"))
    return "\n".join(lines) + "\n"


def write_atomic(path, text):
    """Write the file by a temporary file and a rename; on any failure the temporary file is removed."""
    folder = os.path.dirname(os.path.abspath(path))
    tmp = os.path.join(folder, ".skill-catalog-%d.tmp" % os.getpid())
    try:
        os.makedirs(folder, exist_ok=True)
        with open(tmp, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        os.replace(tmp, path)
    except OSError as e:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise CatalogError("cannot write %s: %s" % (path, e.strerror or e))


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
    if opts["date"] is not None:
        try:
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", opts["date"]):
                raise ValueError(opts["date"])
            datetime.date.fromisoformat(opts["date"])
        except ValueError:
            raise CatalogError("--date must be a real date as YYYY-MM-DD, got %r" % opts["date"])
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
        if opts["out"]:
            write_atomic(opts["out"], text)
    except CatalogError as e:
        print("Error: %s" % e, file=sys.stderr)
        return 2
    if not opts["out"]:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
