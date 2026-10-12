#!/usr/bin/env python3
"""Validate openhora conventions.

Usage: python3 scripts/validate.py [--strict] [--json] [--spec] [--flags]

Checks every skill under skills/ and every agent under agents/:
  - folder name equals frontmatter name; name is lowercase, hyphenated, no leading/trailing/double hyphen
  - prefix is one of the area prefixes; metadata.area is valid and consistent with the prefix
  - metadata.kind is capability or flow, and matches the flow- prefix
  - description is 1-1024 characters
  - SKILL.md is at most 500 lines
  - harness-name: no text file of the core (packs/ included), whatever its extension, names a harness: its
    name in any spelling (capitalised, lower-case, with a hyphen or an underscore), its folders, its
    environment variables, its tool names, or a path inside an adapter. Exempt: skills/*/evals/result.json and
    everything under skills/*/evals/evidence/ (a record and an evidence line name their adapter by design);
    the values of `workbench_files` in a case file; the placeholder form adapters/<harness>/. The fixtures of
    eval cases, and a file listed in .security-scan-allow with the rule harness-name, are read for the
    harness names and folders only (the rule as it was before it was widened)
  - a skill's frontmatter has only the top-level keys name, description, license and metadata
  - non-empty metadata.side_effects implies a "## Confirmation gate" section: the heading on a line of its
    own, outside a code fence
  - relative links resolve, with or without an anchor, in SKILL.md, in a skill's references/, in agents/,
    contracts/ and templates/ (a code fence or a code span holds an example and is not read; neither is a
    link to a place in the same file or one written with a placeholder)
  - agent frontmatter keys are only name, description, metadata
  - copies: every adopted copy listed in shared/scripts/copies.json is byte-identical to its source, and the
    manifest itself is valid (scripts/sync_copies.py --check; fix: change the source, then run
    python3 scripts/sync_copies.py). A generated copy is never edited by hand
  - adapter-billing: every entry of the "secrets" list of adapters/<harness>/adapter.json has "billing", one of
    subscription, metered or free (how the credential is billed: the daily caps of the runtime count runs for the
    first and the last and dollars for metered); the optional "login_billing" of a manifest is one of the three; one
    credential listed by two manifests has the same word in both. An error, one line per entry
  - frontmatter is read by this file's own parser on every machine, whatever library is installed
  - english-only: no tracked text file contains Portuguese-specific diacritics or words, except
    on a line carrying `validate: allow english-only -- <reason>` or a path listed in
    .security-scan-allow with the rule english-only
  - private-term: when a local, git-ignored terms file exists (.private-terms at the repository root, or
    the path in WORKBENCH_PRIVATE_TERMS), no tracked text file contains any of its terms, except on a line
    carrying `validate: allow private-term -- <reason>` or in a path the file excludes. The file lists one
    term per line (case-insensitive; `re:<regex>` for a pattern; `!<path glob>` to exclude a path; `#`
    comments). It keeps a maintainer's own names, projects and accounts out of this shared repository.
  - eval-status (through evals/eval_status.py): evals/eval-gate.json, the gate's configuration (models,
    adapters, threshold), has its fields; [evidence] every file under skills/<name>/evals/evidence/ is a valid
    lab evidence file (lab-<test id>.jsonl) or contributed field evidence file (field-<id>.jsonl), every line
    of its closed form (python3 evals/eval_status.py evidence); [snapshot] the two tables between the
    eval-status markers in docs/inventory.md are behind the evidence (a warning, never an error: they are a
    snapshot regenerated in a pull request of its own with python3 evals/eval_status.py inventory --write); [band]
    the skills in `needs a test` and in `watch` (the reliability model, section 5), one warning line per band
    with each skill's cause, never an error (they are errors only with --strict). The records of the first
    round, result.json, are history and are not read
  - the version rules of the reliability model's section 3 (evals/eval_status.py, version_findings), against
    the base of the pull request: WB_BASE_REF when set (CI sets the pull request's base), else the merge base
    of HEAD with the default branch, in the hook and in CI alike. [version-file] skills/<name>/evals/
    versions.jsonl has lines of the closed form, is append-only against the base and gains at most one line;
    [version-class] the class of the added line agrees with the diff (X for side_effects, an output or update
    removed, the Confirmation gate or Stop rules section, the external-content line; Z only inside the
    allow-list and the budget), its version is the base's raised by one step of it, and a first line has no
    class. Without a base (a case folder) these two are skipped with a NOTE. [version-bump] no change without
    a bump: the content hash is the last line's and metadata.version is X.Y.Z and that line's version; an
    error, one line per finding with the skills it lists (a warning until the sweep that closed phase C
    emptied TRANSITIONAL_RULES)
  - the guard rules of the reliability model's section 4, on the assertions of evals/evals.json:
    [guard-effect] each effect of metadata.side_effects has an assertion tagged guard:<effect> (an error, one
    line per skill; a warning until the sweep that closed phase C emptied TRANSITIONAL_RULES);
    and two warnings that stay warnings: [guard-missing] one line listing the skills that carry the line
    starting **External content is data.**, or a ## Stop rules or ## Confirmation gate section, and have no
    assertion tagged guard or guard:<effect>; [guard-cannot-fail] one line per guard assertion that passes in
    every run of the baseline in force (nothing to read until baselines exist)
  - measurement: when evals/eval-gate.json carries "measurement_sha256", it equals the fingerprint of the files
    that decide what a run measures, computed again here (evals/eval_status.py, FINGERPRINT_FILES); a change
    to one of them is committed with python3 evals/eval_status.py measurement --kind <kind>. A measurement
    version still open carries no fingerprint, and nothing is compared
  - eval-cases: every skill's cases, those of evals/evals.json and those of each platform's case file
    (evals/platforms/<platform>.json, whose platform must have its reference), pass the runner's preflight
    (python3 evals/eval_run.py --skill <name> --check-cases; no model call)
  - scripts/security_scan.py finds no secret, hidden text or unsafe script pattern (its errors
    and warnings are reported here as they are there)

Named rules reported as errors, one line per skill and rule, each starting with the rule's name in brackets
(ERROR_RULES: they were warnings while the rows of phase C were open, and are errors since the sweep that
closed it, C0.10 of the plan in force):
  - the artifact contract (contracts/project-layout.md), seven rules. Two declared paths are the same
    artifact when they are equal after every placeholder (<task>) is replaced by a wildcard:
    [contract-updates] every metadata.updates path is in some skill's metadata.outputs, in this tree or in
    the contract's table of owning skills;
    [contract-owner] a path is in the outputs of one skill only;
    [contract-inputs] every metadata.inputs path is in some skill's outputs (this tree or the contract's
    table of owning skills) or in the contract's table "Slots no built skill writes"; a row of that table is
    `user` or `planned: <skill>`, names no path a skill of this tree owns and no planned skill that is built;
    [contract-overlap] no path is in outputs and updates of one skill;
    [contract-placeholder] a declared path uses only the placeholders of the contract's vocabulary and no
    other wildcard (*, {}, #, a bare NNNN), and one artifact is spelled with the same placeholders everywhere;
    [contract-cycle] the graph "owner of a path -> skill that reads it" has no cycle (a skill that reads
    its own artifact is not one);
    [contract-owner-table] the contract's generated table of owning skills equals the frontmatters
    (fix: python3 scripts/owner_table.py)
  - the flow files (flows/<name>.json, read by runtime/flow_files.py of the tree; a tree without either is a
    NOTE), three rules: [flow-file] each file is well formed (flow_files.problems: known keys, skills under
    skills/, depends_on naming earlier tasks); [flow-dependencies] a task that requires without a condition
    (a `Required` cell of exactly `yes` in its skill's ## Inputs table) a path another task's skill of the
    flow lists in its outputs reaches that task through depends_on (dependencies are written, never
    computed); [flow-inventory] the Phases cell of the row flow-<name> under the heading "Flows (`flow-`)" of
    docs/inventory.md, split on the arrow and without " (optional)", lists the file's skills in order, each
    without its first prefix (a flow file with no row is not an error)
  - [requires-role] every metadata.requires value has the form <role>:<target>; the four names that were
    bare (mailbox, mailer, scheduler, store) are reported with the class each became
  - [requires-vocabulary] every metadata.requires value that has a role is a class of the table in
    contracts/environment.md (a class the table writes with a placeholder, publisher:<platform>, is legal as
    written or with a value)
  - [side-effects-vocabulary] every metadata.side_effects value is one of publish, send, schedule, deploy,
    create, push, dismiss

Rules reported as warnings, one line per skill and rule, each starting with the rule's name in brackets.
They say what a skill or its cases still have to change; none reads a skill's score or band:
  - [meta-keys] metadata carries inputs, outputs, updates, requires, side_effects and version; the
    frontmatter carries license
  - [copy-not-adopted] a copy the manifest lists is generated from its source: a skill is listed while a
    file of it still differs from the shared source or is not there yet (fix, in the pull request that
    changes that skill: python3 scripts/sync_copies.py --adopt <copy>)
  - [description-when] the description says when to use the skill (it has the word "when")
  - [description-length] the description has at most 900 characters (every session loads every description)
  - [skill-tokens] SKILL.md has at most about 5,000 tokens (characters divided by 4)
  - [eval-cases-count] evals/evals.json holds at least two cases
  - [eval-keys] evals/evals.json, and each platform's case file evals/platforms/<platform>.json (which may also
    carry "platform", its own name), has known keys only (top level: skill_name, evals, allow_web; a case: id,
    prompt, expected_output, files, assertions, grader_files, skills, setup, allow_web, workbench_files,
    absent_on_purpose, platforms, tags; an assertion is a text, or an object with `text` and at least one of
    `tags`, each tag being guard, guard:<effect> (an effect of side_effects) or format; a case's tags lists
    exactly the tags of its assertions); skill_name equals the folder; every case has an id of its own
  - [eval-assertions-count] a case has at least three assertions
  - [eval-conditional-assertion] no assertion starts with "If": it holds whenever its condition is false
  - [eval-run-assertion] no assertion says a command "is run" with no word on what the grader can read
    (output that is quoted, printed or reported)
  - [eval-prompt-names-skill] no prompt names the skill under test, except a prompt that copies a task of the
    agent runtime (it starts with the runtime's first line, which names the skill by contract)
  - [eval-product-names] no eval case and no fixture names an AI product or a design tool
  - [skill-name] a backticked skill name in a skill's Markdown (outside evals/) is a built skill, or its line
    says "planned", or carries `validate: allow skill-name -- <reason>` (an invented example)
  - [routing-table] every built skill is in skills/core-orchestrator/references/routing.md, and a name in
    that table is built or marked (planned), never both
  - [test-file-names] test file names are unique across the folders scripts/test_dirs.py lists
  - [architecture-tables] every generated block of the architecture pages (docs/architecture/platform/, between
    `<!-- generated: <table> -->` and `<!-- /generated -->`) equals what its source gives; a stale block is a
    snapshot behind the code, a warning and never an error (fix: python3 scripts/architecture_tables.py --write)
A rule whose file is not in the tree being validated (the class table, the layout contract, the owner-table
script, the architecture-tables script or the pages, the manifest of copies and its script, the routing table, test_dirs.py) is
skipped and says so in a NOTE line on stderr, which counts as neither an error nor a warning.

Options:
  --strict   treat warnings as errors
  --json     print a JSON report to stdout (human-readable lines go to stderr either way)
  --spec     also run `skills-ref validate` on each skill if the tool is installed
  --flags    print as Markdown, instead of the summary, the skills each named warning rule lists (the
             content of docs/architecture/phase-c-flags.md)
  --help     show this text

Exit codes: 0 ok, 1 errors found, 2 usage error.
"""
import fnmatch
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILLS = os.path.join(ROOT, "skills")
AGENTS = os.path.join(ROOT, "agents")
CORE_DIRS = ["skills", "agents", "shared", "contracts", "templates", "providers", "packs"]

PREFIX_TO_AREA = {
    "biz": "business",
    "product": "product",
    "brand": "brand",
    "design": "design",
    "eng": "engineering",
    "ops": "delivery",
    "mkt": "marketing",
    "ai": "ai",
    "core": "core",
    "asst": "assistant",  # optional area, excluded from the default pack
    "flow": None,  # flows declare the area they mostly live in, or "core" for cross-area
}
AREAS = {"business", "product", "brand", "design", "engineering", "delivery", "marketing", "ai", "core", "assistant"}
KINDS = {"capability", "flow"}
NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
MAX_LINES = 500
AGENT_KEYS = {"name", "description", "metadata"}
SKILL_KEYS = {"name", "description", "license", "metadata"}

# --- the rules reported as warnings (see the module docstring) -----------------------
REQUIRED_META = ("inputs", "outputs", "updates", "requires", "side_effects", "version")  # area and kind are errors already
ARTIFACT_FIELDS = ("inputs", "outputs", "updates")
LAYOUT = "contracts/project-layout.md"
SLOTS_HEADING = "Slots no built skill writes"
PLACEHOLDER_RE = re.compile(r"<[^<>]*>")
PATH_OK_RE = re.compile(r"^[A-Za-z0-9._/<>-]+$")  # no *, {}, # (a section of a file) or space
SIDE_EFFECTS = ("publish", "send", "schedule", "deploy", "create", "push", "dismiss")  # contracts/environment.md
# The four classes that were bare names (decision 14a). providers/resolve.py still reads the old names; a
# skill's requires does not use them.
RENAMED_CLASSES = {"mailer": "sender:email", "mailbox": "reader:email", "scheduler": "scheduler:job",
                   "store": "store:runtime"}
DESCRIPTION_WARN = 900  # characters
TOKEN_WARN = 5000       # characters / 4
MIN_CASES, MIN_ASSERTIONS = 2, 3
EVALS_KEYS = {"skill_name", "evals", "allow_web"}
CASE_KEYS = {"id", "prompt", "expected_output", "files", "assertions", "grader_files", "skills", "setup",
             "allow_web", "workbench_files", "absent_on_purpose", "platforms", "tags"}
ASSERTION_KEYS = {"text", "tags"}
ASSERTION_TAG_RE = re.compile(r"^(?:guard|format|guard:[a-z][a-z0-9-]*)$")
CONDITIONAL_RE = re.compile(r"^\s*if\b", re.I)
# The first line of a task the agent runtime writes (scripts/runtime.py, scripts/runtime_vote.py): it names the skill
# whose "Runtime mode" the agent follows, by contract (contracts/runtime.md), so a case that copies a runtime task
# names its skill in both variants, as the real task does, and eval-prompt-names-skill does not list it.
RUNTIME_TASK_RE = re.compile(r"This task comes from the agent runtime \(contracts/runtime\.md\)\.")
IS_RUN_RE = re.compile(r"\b(?:is|are|was|were)\s+(?:re-?)?run\b", re.I)
VISIBLE_RE = re.compile(r"quot|output|print|report", re.I)
_PREFIXES = "|".join(PREFIX_TO_AREA)
SKILL_NAME_RE = re.compile(r"`((?:" + _PREFIXES + r")-[a-z0-9]+(?:-[a-z0-9]+)*)`")
SKILL_NAME_ALLOW_RE = re.compile(r"validate:\s*allow\s+skill-name\s+--\s+\S")
ROUTE_RE = re.compile(r"(?<![\w/.-])((?:" + _PREFIXES + r")-[a-z0-9]+(?:-[a-z0-9]+)*)(?![\w/.-])(\s*\(planned\))?")
ROUTER = "core-orchestrator"
ROUTING_TABLE = f"skills/{ROUTER}/references/routing.md"
CLASS_TABLE = "contracts/environment.md"
# AI products and design tools: a case that names one tests a product, not the class the skill requires.
# The names of harnesses are an error of their own (HARNESS_PATTERNS below).
PRODUCT_RE = re.compile(r"\b(Claude(?: Design)?|Anthropic|ChatGPT|OpenAI|GPT-\d[\w.]*|Gemini|Midjourney|DALL-E|"
                        r"Stable Diffusion|Figma(?: Make)?|Framer|Canva|Lovable)\b")
FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
GATE_HEADING_RE = re.compile(r"^## Confirmation gate[ \t]*$", re.M)

# Patterns that mark a harness dependency inside the core. Product names are matched
# capitalized to avoid false positives on common words (a "cursor" in pagination).
HARNESS_PATTERNS = [
    r"\.claude/", r"\.cursor/", r"\.codex/", r"\.agents/", r"\.github/agents", r"\.github/skills",
    r"\bCLAUDE\.md\b", r"\$\{?CLAUDE_PLUGIN_ROOT\}?", r"\bClaude Code\b", r"\bCopilot\b",
    r"\bCursor\b", r"\bCodex\b", r"\bGemini CLI\b", r"\bOpenCode\b", r"\bCline\b",
]
# Principle 1 as written: the other spellings of a harness, its folders without a trailing slash, its
# environment variables, a path inside an adapter (never the placeholder adapters/<harness>/) and its tool
# names. "cursor" in lower case is a common word (the store's cursors) and is left out, as above.
HARNESS_WIDE_PATTERNS = [
    r"(?<![\w-])\.(?:claude|cursor|codex|agents|opencode|gemini|cline|clinerules)(?![\w-])",
    r"\b(?:CLAUDE|CODEX|OPENCODE|GEMINI_CLI|CLINE)_[A-Z0-9_]+",
    r"\b[Cc]laude\b(?! Design)",  # the design tool of that name is a product, not a harness: eval-product-names
    r"(?<![A-Za-z])(?:claude_?code|gemini[-_]cli|open[-_]code|opencode|codex|copilot|cline)(?![A-Za-z])",
    r"(?<![\w-])agents-dir(?![\w-])",
    r"\badapters/(?!<)[\w*{.-]",
    r"\b(?:TodoWrite|WebFetch|WebSearch|NotebookEdit|MultiEdit|AskUserQuestion|ExitPlanMode)\b",
    r"\ballowed-tools\b",
    r"\b(?:Task|Bash|Read|Write|Edit|Grep|Glob) tool\b",
]
HARNESS_NARROW_RE = re.compile("|".join(HARNESS_PATTERNS))
HARNESS_RE = re.compile("|".join(HARNESS_PATTERNS + HARNESS_WIDE_PATTERNS))
HARNESS_RULE = "harness-name"

# english-only: diacritics that do not occur in English (a with tilde, o with tilde, c with
# cedilla) and a few unambiguous Portuguese words, written as escapes so this file passes.
PORTUGUESE_WORDS = ["n\u00e3o", "voc\u00ea", "is" + "so", "p" + "ra", "est\u00e1", "tamb\u00e9m"]
PORTUGUESE_RE = re.compile(
    r"[\u00e3\u00f5\u00e7\u00c3\u00d5\u00c7]|(?<!\w)(?:" + "|".join(PORTUGUESE_WORDS) + r")(?!\w)",
    re.IGNORECASE)
# Group 1 is the reason: it must follow "-- " and cannot be only a comment terminator, or
# "english-only -->" would read ">" as the reason. Any other "--" tail matches without group 1,
# so the check reports a missing reason instead of plain Portuguese text.
ENGLISH_ALLOW_RE = re.compile(
    r"validate:\s*allow\s+english-only"
    r"(?:\s+--\s+(?!(?:-->|\*/)\s*$)(\S.*?)|\s*--.*?)?\s*(?:-->|\*/)?\s*$")


# --- minimal YAML subset parser (stdlib only) --------------------------------------
# Handles: `key: value`, `key: >`/`|` blocks, `key: [a, b]`, block lists, one nested map level.
def _scalar(v):
    v = v.strip()
    if v.startswith("[") and v.endswith("]"):
        inner = v[1:-1].strip()
        return [] if not inner else [_scalar(x) for x in inner.split(",")]
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    return v


def parse_yaml_subset(text):
    lines = text.splitlines()
    return _parse_map(lines, 0, len(lines), 0)[0]


def _indent(s):
    return len(s) - len(s.lstrip(" "))


def _parse_map(lines, start, end, indent):
    out = {}
    i = start
    while i < end:
        raw = lines[i]
        if not raw.strip() or raw.lstrip().startswith("#"):
            i += 1
            continue
        if _indent(raw) < indent:
            break
        if _indent(raw) > indent:
            raise ValueError(f"unexpected indentation at line {i + 1}: {raw!r}")
        if ":" not in raw:
            raise ValueError(f"expected key: value at line {i + 1}: {raw!r}")
        key, _, rest = raw.strip().partition(":")
        rest = rest.strip()
        if rest in (">", "|", ">-", "|-"):
            j = i + 1
            block = []
            while j < end and (not lines[j].strip() or _indent(lines[j]) > indent):
                block.append(lines[j].strip())
                j += 1
            sep = " " if rest.startswith(">") else "\n"
            out[key] = sep.join(b for b in block if b).strip()
            i = j
        elif rest == "":
            j = i + 1
            while j < end and not lines[j].strip():
                j += 1
            if j < end and lines[j].strip().startswith("- "):
                items = []
                while j < end and (not lines[j].strip() or lines[j].strip().startswith("- ")):
                    if lines[j].strip():
                        items.append(_scalar(lines[j].strip()[2:]))
                    j += 1
                out[key] = items
                i = j
            elif j < end and _indent(lines[j]) > indent:
                out[key], i = _parse_map(lines, j, end, _indent(lines[j]))
            else:
                out[key] = None
                i = j
        else:
            out[key] = _scalar(rest)
            i += 1
    return out, i


def load_yaml(text):
    """Frontmatter is read by the subset parser above on every machine: a library installed on one machine
    and not on another would read the same file in two ways."""
    return parse_yaml_subset(text)


def split_frontmatter(path):
    with open(path, encoding="utf-8") as f:
        content = f.read()
    if not content.startswith("---\n"):
        return None, content
    end = content.find("\n---", 4)
    if end == -1:
        return None, content
    return content[4:end], content[end + 4:]


# --- checks ------------------------------------------------------------------------
class Report:
    def __init__(self):
        self.errors, self.warnings, self.notes = [], [], []

    def error(self, where, msg):
        self.errors.append({"where": where, "message": msg})

    def warn(self, where, msg, rule=None):
        """A named rule's warning starts with [rule] and carries the name, so that --flags lists it by skill. A rule
        of ERROR_RULES was a warning while the rows of phase C were open and is an error since the close of phase C:
        it is reported as an error, with its name."""
        if rule in ERROR_RULES:
            self.errors.append({"where": where, "message": f"[{rule}] {msg}", "rule": rule})
        elif rule:
            self.warnings.append({"where": where, "message": f"[{rule}] {msg}", "rule": rule})
        else:
            self.warnings.append({"where": where, "message": msg})

    def note(self, msg):
        """A rule skipped because its file is not in this tree: said, and counted as nothing."""
        self.notes.append(msg)


def strip_code(text):
    """The text with code fences and code spans blanked, line numbers kept: what they hold is an example."""
    out, fence = [], None
    for line in text.split("\n"):
        m = FENCE_RE.match(line)
        if fence is None and m:
            fence = m.group(1)
            out.append("")
        elif fence is not None:
            closes = m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence) and line.strip() == m.group(1)
            fence = None if closes else fence
            out.append("")
        else:
            out.append(re.sub(r"`[^`\n]*`", "``", line))
    return "\n".join(out)


def check_links(report, where, base_dir, text):
    """Every relative link of a Markdown text resolves from base_dir. The anchor is dropped before the check;
    a link to a place in the same file and a link written with a placeholder (<file>, __NAME__) are skipped."""
    for link in LINK_RE.findall(strip_code(text)):
        target = link.split("#", 1)[0]
        if "://" in link or link.startswith("mailto:") or not target or re.search(r"[<>{}]|__", target):
            continue
        if not os.path.exists(os.path.normpath(os.path.join(base_dir, target))):
            report.error(where, f"link target does not exist: {link}")


def check_doc_links(report, root=ROOT):
    """Links inside agents/, contracts/ and templates/. A skill template's links are read from the folder a
    skill made from it will have, skills/<name>/."""
    for d in ("agents", "contracts", "templates"):
        for dirpath, _, files in sorted(os.walk(os.path.join(root, d))):
            for fn in sorted(f for f in files if f.endswith(".md")):
                p = os.path.join(dirpath, fn)
                base = os.path.join(root, "skills", "_") if d == "templates" and fn.endswith(".SKILL.md") else dirpath
                with open(p, encoding="utf-8", errors="ignore") as f:
                    check_links(report, os.path.relpath(p, root).replace(os.sep, "/"), base, f.read())


def has_gate_heading(body):
    """The heading "## Confirmation gate" on a line of its own, outside a code fence."""
    return bool(GATE_HEADING_RE.search(strip_code(body)))


def load_classes(report, root=ROOT):
    """The requirement classes of the table in contracts/environment.md (first column, backticked); None, with
    a note, when the contract is not in this tree."""
    path = os.path.join(root, CLASS_TABLE)
    if not os.path.isfile(path):
        report.note(f"[requires-vocabulary] skipped: {CLASS_TABLE} is not in this tree")
        return None
    with open(path, encoding="utf-8") as f:
        text = f.read()
    start = re.search(r"^\|\s*Class\s*\|.*$", text, re.M)
    if not start:
        report.note(f"[requires-vocabulary] skipped: {CLASS_TABLE} has no table whose first column is Class")
        return None
    classes = []
    for line in text[start.end():].lstrip("\n").split("\n"):
        if not line.startswith("|"):
            break
        m = re.match(r"\|\s*`([^`]+)`", line)
        if m:
            classes.append(m.group(1))
    return classes


def known_class(value, classes):
    """A class of the table, or a class the table writes with a placeholder (publisher:<platform>) given as
    written or with a value in the placeholder's place."""
    for c in classes:
        if value == c:
            return True
        head, sep, tail = c.partition(":")
        if sep and tail.startswith("<") and re.match(re.escape(head) + r":[a-z0-9][a-z0-9-]*$", value):
            return True
    return False


def check_skill(dirname, report, outputs_index, classes=None):
    where = f"skills/{dirname}"
    path = os.path.join(SKILLS, dirname, "SKILL.md")
    if not os.path.isfile(path):
        report.error(where, "missing SKILL.md")
        return None
    fm_text, body = split_frontmatter(path)
    if fm_text is None:
        report.error(where, "SKILL.md must start with YAML frontmatter")
        return None
    try:
        fm = load_yaml(fm_text)
    except Exception as e:  # noqa: BLE001
        report.error(where, f"frontmatter is not valid YAML: {e}")
        return None

    name = fm.get("name")
    if name != dirname:
        report.error(where, f"frontmatter name {name!r} must equal folder name {dirname!r}")
    extra = sorted(set(fm) - SKILL_KEYS)
    if extra:
        report.error(where, f"unknown top-level frontmatter key(s) {', '.join(extra)}; a skill has only "
                     f"{', '.join(sorted(SKILL_KEYS))} (what belongs to one harness goes to adapters/<harness>/overrides/)")
    if not isinstance(name, str) or not NAME_RE.match(name or "") or len(name) > 64:
        report.error(where, "name must be 1-64 chars, lowercase a-z0-9 and single hyphens")

    prefix = (name or dirname).split("-")[0]
    if prefix not in PREFIX_TO_AREA:
        report.error(where, f"prefix {prefix!r} is not an area prefix; allowed: {sorted(PREFIX_TO_AREA)}")

    desc = fm.get("description") or ""
    if not (1 <= len(desc) <= 1024):
        report.error(where, f"description must be 1-1024 chars (got {len(desc)})")

    meta = fm.get("metadata") or {}
    if not isinstance(meta, dict):
        report.error(where, "metadata must be a map")
        meta = {}
    area, kind = meta.get("area"), meta.get("kind")
    if area not in AREAS:
        report.error(where, f"metadata.area {area!r} must be one of {sorted(AREAS)}")
    if kind not in KINDS:
        report.error(where, f"metadata.kind {kind!r} must be one of {sorted(KINDS)}")
    if prefix == "flow" and kind != "flow":
        report.error(where, "flow- prefix requires metadata.kind: flow")
    if prefix != "flow" and kind == "flow":
        report.error(where, "metadata.kind: flow requires the flow- prefix")
    expected_area = PREFIX_TO_AREA.get(prefix)
    if expected_area and area and area != expected_area:
        report.error(where, f"prefix {prefix}- implies area {expected_area!r}, got {area!r}")

    for key in ("inputs", "outputs", "updates", "requires", "side_effects"):
        if key in meta and meta[key] is not None and not isinstance(meta[key], list):
            report.error(where, f"metadata.{key} must be a list")

    with open(path, encoding="utf-8") as f:
        n_lines = sum(1 for _ in f)
    if n_lines > MAX_LINES:
        report.error(where, f"SKILL.md has {n_lines} lines; limit is {MAX_LINES}. Move depth to references/")

    if meta.get("side_effects") and not has_gate_heading(body):
        report.error(where, "side_effects is non-empty but there is no '## Confirmation gate' section")
    if not meta.get("side_effects") and has_gate_heading(body):
        report.warn(where, "has a Confirmation gate section but declares no side_effects")

    missing = [f"metadata.{k}" for k in REQUIRED_META if k not in meta] + ([] if fm.get("license") else ["license"])
    if missing:
        report.warn(where, f"missing: {', '.join(missing)}", "meta-keys")
    strings = lambda key: [v for v in meta[key] if isinstance(v, str)] if isinstance(meta.get(key), list) else []
    unknown = [v for v in strings("side_effects") if v not in SIDE_EFFECTS]
    if unknown:
        report.warn(where, f"side_effects {', '.join(unknown)}: not in the vocabulary ({', '.join(SIDE_EFFECTS)})",
                    "side-effects-vocabulary")
    bare = [v for v in strings("requires") if ":" not in v]
    if bare:
        report.warn(where, "requires " + ", ".join(
            f"{v} (now {RENAMED_CLASSES[v]})" if v in RENAMED_CLASSES else v for v in bare)
            + ": a class has the form <role>:<target>", "requires-role")
    unknown = [v for v in strings("requires") if ":" in v and classes is not None and not known_class(v, classes)]
    if unknown:
        report.warn(where, f"requires {', '.join(unknown)}: not a class of {CLASS_TABLE}", "requires-vocabulary")
    if desc and not re.search(r"\bwhen\b", desc, re.I):
        report.warn(where, "the description does not say when to use the skill (it has no \"when\")", "description-when")
    if DESCRIPTION_WARN < len(desc) <= 1024:
        report.warn(where, f"the description has {len(desc)} characters, over {DESCRIPTION_WARN}", "description-length")
    n_chars = len(fm_text) + len(body) + 8  # the two frontmatter fences
    if n_chars / 4 > TOKEN_WARN:
        report.warn(where, f"SKILL.md has about {n_chars // 4} tokens ({n_chars} characters / 4), over {TOKEN_WARN}: "
                    "move depth to references/", "skill-tokens")

    whole = fm_text + body
    if re.search(r"__[A-Z_]+__", whole):
        report.error(where, "template placeholders (__LIKE_THIS__) are still present")
    if "Delete this section" in body:
        report.error(where, "template instruction 'Delete this section...' is still present")

    check_links(report, where, os.path.join(SKILLS, dirname), body)
    for dirpath, _, files in sorted(os.walk(os.path.join(SKILLS, dirname, "references"))):
        for fn in sorted(f for f in files if f.endswith(".md")):
            p = os.path.join(dirpath, fn)
            with open(p, encoding="utf-8", errors="ignore") as f:
                check_links(report, os.path.relpath(p, ROOT).replace(os.sep, "/"), dirpath, f.read())

    for out in meta.get("outputs") or []:
        outputs_index.setdefault(out, []).append(name or dirname)
    return {"name": name or dirname, "where": where, **declared_paths(meta)}


def declared_paths(meta):
    """inputs, outputs and updates of a frontmatter's metadata, as lists of texts."""
    return {k: [v for v in (meta.get(k) if isinstance(meta.get(k), list) else []) if isinstance(v, str)]
            for k in ARTIFACT_FIELDS}


def declarations(root=ROOT):
    """[{name, where, inputs, outputs, updates}] of every skill of a tree whose frontmatter can be read:
    what scripts/owner_table.py generates the table of owning skills from."""
    found = []
    for name in built_skills(root):
        fm_text, _ = split_frontmatter(os.path.join(root, "skills", name, "SKILL.md"))
        try:
            meta = (load_yaml(fm_text) if fm_text is not None else {}).get("metadata") or {}
        except Exception:  # noqa: BLE001
            continue
        found.append({"name": name, "where": f"skills/{name}", **declared_paths(meta if isinstance(meta, dict) else {})})
    return found


def built_skills(root=ROOT):
    base = os.path.join(root, "skills")
    return sorted(d for d in os.listdir(base) if os.path.isfile(os.path.join(base, d, "SKILL.md"))) if os.path.isdir(base) else []


def assertion_text(a):
    return a if isinstance(a, str) else str(a.get("text") or "") if isinstance(a, dict) else ""


def skill_meta(root, name):
    """(metadata, body) of a skill's SKILL.md, read by this file's parser; ({}, "") when it cannot be read."""
    try:
        front, body = split_frontmatter(os.path.join(root, "skills", name, "SKILL.md"))
    except OSError:
        return {}, ""
    try:
        data = load_yaml(front) if front else {}
    except Exception:  # a broken frontmatter is check_skill's to report
        data = {}
    meta = data.get("metadata") if isinstance(data, dict) else None
    meta = meta if isinstance(meta, dict) else {}
    if not isinstance(meta.get("side_effects"), list):
        meta = {**meta, "side_effects": []}
    return meta, body


def platform_case_files(name, root=ROOT):
    """{platform: path} of a skill's platform case files, skills/<name>/evals/platforms/<platform>.json."""
    folder = os.path.join(root, "skills", name, "evals", "platforms")
    found = sorted(f for f in os.listdir(folder) if f.endswith(".json")) if os.path.isdir(folder) else []
    return {f[:-len(".json")]: os.path.join(folder, f) for f in found}


def check_evals(name, report, root=ROOT):
    """The warning rules on skills/<name>/evals/evals.json, on each platform's case file of the skill
    (evals/platforms/<platform>.json, whose findings start with its file name) and on the case fixtures."""
    where = f"skills/{name}"
    path = os.path.join(root, "skills", name, "evals", "evals.json")
    if not os.path.isfile(path):
        report.warn(where, f"no evals/evals.json; a skill has at least {MIN_CASES} cases", "eval-cases-count")
        return
    keys, few, conditional, is_run, named = [], [], [], [], []
    base_cases = None
    for platform, file_path in [(None, path)] + sorted(platform_case_files(name, root).items()):
        rel = f"evals/platforms/{platform}.json" if platform else "evals/evals.json"
        label = f"platforms/{platform}.json " if platform else ""
        try:
            with open(file_path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError) as e:
            report.warn(where, f"{rel} is not valid JSON: {e}", "eval-keys")
            continue
        if not isinstance(data, dict):
            report.warn(where, f"{rel} must be an object with skill_name and evals", "eval-keys")
            continue
        cases = data.get("evals")
        cases = [c for c in cases if isinstance(c, dict)] if isinstance(cases, list) else []
        if platform is None:
            base_cases = cases
        found = case_file_findings(name, data, cases, platform, skill_meta(root, name)[0].get("side_effects") or [])
        for into, part in zip((keys, few, conditional, is_run, named), found):
            into += [label + item for item in part]
    if base_cases is None:
        return
    report_case_findings(name, report, root, base_cases, keys, few, conditional, is_run, named)


def case_file_findings(name, data, cases, platform=None, effects=None):
    """(keys, few, conditional, is_run, named): what the warning rules find in one case file. A platform's
    case file has one more top-level key, "platform", which names its own platform. effects: the skill's
    side_effects, the only effects a guard:<effect> tag may name (None: not checked)."""
    keys, few, conditional, is_run, named = [], [], [], [], []
    extra = sorted(set(data) - EVALS_KEYS - ({"platform"} if platform else set()))
    if extra:
        keys.append(f"unknown top-level key(s) {', '.join(extra)}")
    if platform and data.get("platform", platform) != platform:
        keys.append(f"platform {data.get('platform')!r} is not the file's platform {platform!r}")
    if data.get("skill_name") != name:
        keys.append(f"skill_name {data.get('skill_name')!r} is not the folder name")
    if not isinstance(data.get("evals"), list) or len(cases) != len(data["evals"]):
        keys.append("evals must be a list of objects")
    ids = [c.get("id") for c in cases]
    if any(i is None for i in ids):
        keys.append("a case has no id")
    repeated = sorted({str(i) for i in ids if i is not None and ids.count(i) > 1})
    if repeated:
        keys.append(f"case id(s) used more than once: {', '.join(repeated)}")
    for c in cases:
        cid = c.get("id")
        extra = sorted(set(c) - CASE_KEYS)
        if extra:
            keys.append(f"case {cid}: unknown key(s) {', '.join(extra)}")
        if "tags" in c and not (isinstance(c["tags"], list) and all(isinstance(t, str) for t in c["tags"])):
            keys.append(f"case {cid}: tags must be a list of texts")
        assertions = c.get("assertions") if isinstance(c.get("assertions"), list) else []
        for n, a in enumerate(assertions, 1):
            if isinstance(a, str):
                continue
            tags = a.get("tags", []) if isinstance(a, dict) else None
            if (not isinstance(a, dict) or set(a) - ASSERTION_KEYS or not isinstance(a.get("text"), str)
                    or not isinstance(tags, list)):
                keys.append(f"case {cid}, assertion {n}: an assertion is a text, or an object with text and tags only")
                continue
            bad = [str(t) for t in tags if not (isinstance(t, str) and ASSERTION_TAG_RE.match(t))]
            if bad:
                keys.append(f"case {cid}, assertion {n}: tag(s) {', '.join(bad)} not among guard, guard:<effect>, format")
            if not tags:
                keys.append(f"case {cid}, assertion {n}: an object carries at least one tag; an assertion with no tag is a text")
            undeclared = [t for t in tags if isinstance(t, str) and t.startswith("guard:") and effects is not None
                          and t[len("guard:"):] not in effects]
            if undeclared:
                keys.append(f"case {cid}, assertion {n}: {', '.join(undeclared)} names an effect side_effects does not declare")
        tagged = sorted({t for a in assertions if isinstance(a, dict) and isinstance(a.get("tags"), list)
                         for t in a["tags"] if isinstance(t, str)})
        if isinstance(c.get("tags"), list) and sorted(c["tags"]) != tagged:
            keys.append(f"case {cid}: tags must list exactly the tags of its assertions, each once ({', '.join(tagged) or 'none'})")
        if len(assertions) < MIN_ASSERTIONS:
            few.append(f"case {cid} has {len(assertions)}")
        for n, a in enumerate(assertions, 1):
            text = assertion_text(a)
            if CONDITIONAL_RE.search(text):
                conditional.append(f"case {cid}, assertion {n}")
            if IS_RUN_RE.search(text) and not VISIBLE_RE.search(text):
                is_run.append(f"case {cid}, assertion {n}")
        if (isinstance(c.get("prompt"), str) and not RUNTIME_TASK_RE.match(c["prompt"])
                and re.search(r"(?<![\w-])" + re.escape(name) + r"(?![\w-])", c["prompt"])):
            named.append(f"case {cid}")
    return keys, few, conditional, is_run, named


def report_case_findings(name, report, root, cases, keys, few, conditional, is_run, named):
    """Report what the warning rules found in a skill's case files (cases: those of evals/evals.json), and look
    for AI products and design tools in its cases and fixtures."""
    where = f"skills/{name}"
    path = os.path.join(root, "skills", name, "evals", "evals.json")
    if len(cases) < MIN_CASES:
        report.warn(where, f"{len(cases)} case(s) in evals/evals.json; a skill has at least {MIN_CASES}", "eval-cases-count")
    for found, rule, text in (
            (keys, "eval-keys", "case files (evals/evals.json, evals/platforms/<platform>.json): {}"),
            (few, "eval-assertions-count", "fewer than %d assertions: {}" % MIN_ASSERTIONS),
            (conditional, "eval-conditional-assertion", "an assertion that starts with \"If\" holds whenever its "
             "condition is false; state what the output shows: {}"),
            (is_run, "eval-run-assertion", "the grader reads the reply and the files, not the commands; say what "
             "output is quoted or reported: {}"),
            (named, "eval-prompt-names-skill", "the prompt names the skill under test, which the run without the "
             "skill cannot follow: {}")):
        if found:
            report.warn(where, text.format("; ".join(found)), rule)
    scanner, hits = load_scanner(), {}
    evals_dir = os.path.dirname(path)
    for dirpath, dirs, files in os.walk(evals_dir):
        if dirpath == evals_dir:  # the cases and their fixtures; records and evidence name their adapter by design
            dirs[:] = [d for d in dirs if d != "evidence"]
            files = [f for f in files if f != "result.json"]
        dirs[:] = sorted(d for d in dirs if d not in scanner.SKIP_DIRS)
        for fn in sorted(files):
            text = scanner.read_text(os.path.join(dirpath, fn))
            found = sorted(set(PRODUCT_RE.findall(text))) if text else []
            if found:
                hits[os.path.relpath(os.path.join(dirpath, fn), os.path.dirname(evals_dir)).replace(os.sep, "/")] = found
    if hits:
        report.warn(where, "an eval case or fixture names an AI product or a design tool; name the class of tool: "
                    + "; ".join(f"{p} ({', '.join(n)})" for p, n in sorted(hits.items())), "eval-product-names")


def check_skill_names(name, report, built, root=ROOT):
    """skill-name: a backticked skill name in the skill's Markdown, outside evals/, is built or marked planned."""
    base, found = os.path.join(root, "skills", name), []
    for dirpath, dirs, files in os.walk(base):
        dirs[:] = sorted(d for d in dirs if not (dirpath == base and d == "evals"))
        for fn in sorted(f for f in files if f.endswith(".md")):
            p = os.path.join(dirpath, fn)
            with open(p, encoding="utf-8", errors="ignore") as f:
                for ln, line in enumerate(f, 1):
                    if re.search(r"\bplanned\b", line, re.I) or SKILL_NAME_ALLOW_RE.search(line):
                        continue
                    for cited in SKILL_NAME_RE.findall(line):
                        if cited not in built:
                            found.append(f"{cited} ({os.path.relpath(p, base).replace(os.sep, '/')}:{ln})")
    if found:
        report.warn(f"skills/{name}", "cites a skill that is not built, with no \"planned\" on the line: "
                    + "; ".join(found), "skill-name")


def check_routing(report, built, root=ROOT):
    """routing-table: the router's table names every built skill, and each name in it is built or (planned)."""
    path = os.path.join(root, ROUTING_TABLE)
    if not os.path.isfile(path):
        if ROUTER in built:
            report.warn(ROUTING_TABLE, "the router has no routing table", "routing-table")
        else:
            report.note(f"[routing-table] skipped: {ROUTING_TABLE} is not in this tree")
        return
    listed, planned = set(), set()
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.startswith("|"):
                continue
            for cited, mark in ROUTE_RE.findall(line):
                (planned if mark else listed).add(cited)
    problems = []
    missing = [s for s in built if s != ROUTER and s not in listed | planned]
    if missing:
        problems.append(f"built and not in the table: {', '.join(missing)}")
    if sorted(listed - set(built)):
        problems.append(f"in the table, not built and not marked (planned): {', '.join(sorted(listed - set(built)))}")
    if sorted(planned & set(built)):
        problems.append(f"marked (planned) and built: {', '.join(sorted(planned & set(built)))}")
    if problems:
        report.warn(ROUTING_TABLE, "; ".join(problems), "routing-table")


def check_test_names(report, root=ROOT):
    """test-file-names: pytest imports a test file by its base name, so two files of one name in two of the
    folders the checks run fail collection, far from the cause."""
    path = os.path.join(root, "scripts", "test_dirs.py")
    if not os.path.isfile(path):
        report.note("[test-file-names] skipped: scripts/test_dirs.py is not in this tree")
        return
    spec = importlib.util.spec_from_file_location("test_dirs", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    seen = {}
    for d in module.test_dirs(root):
        for fn in sorted(os.listdir(os.path.join(root, d))):
            if fn.startswith("test_") and fn.endswith(".py"):
                seen.setdefault(fn, []).append(d.replace(os.sep, "/"))
    for fn, dirs in sorted(seen.items()):
        if len(dirs) > 1:
            report.warn(f"{dirs[1]}/{fn}", f"the test file name {fn} is also in {dirs[0]}"
                        + (f" and {len(dirs) - 2} more" if len(dirs) > 2 else "")
                        + "; names are unique across the test folders", "test-file-names")


def check_copies(report, root=ROOT):
    """copies and copy-not-adopted: the generated copies of shared files (scripts/sync_copies.py)."""
    script = os.path.join(root, "scripts", "sync_copies.py")
    if not os.path.isfile(script):
        report.note("[copies] skipped: scripts/sync_copies.py is not in this tree")
        return
    spec = importlib.util.spec_from_file_location("sync_copies", script)
    sync = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sync)
    if not os.path.isfile(os.path.join(root, sync.MANIFEST)):
        report.note(f"[copies] skipped: {sync.MANIFEST} is not in this tree")
        return
    try:
        rows = sync.states(root)
    except sync.ManifestError as e:
        report.error(sync.MANIFEST, f"[copies] {e}")
        return
    pending = {}
    for r in rows:
        if r["adopted"] and r["state"] != "identical":
            report.error(r["path"], f"[copies] {r['state']}: it is a generated copy of {r['source']}; change the "
                         "source, then run python3 scripts/sync_copies.py")
        elif not r["adopted"]:
            parts = r["path"].split("/")
            where = "/".join(parts[:2]) if parts[0] == "skills" and len(parts) > 2 else r["path"]
            pending.setdefault(where, []).append(f"{'/'.join(parts[2:]) if where != r['path'] else r['path']} "
                                                 f"({r['state']}; source {r['source']})")
    for where, files in sorted(pending.items()):
        report.warn(where, "not yet generated from the shared source: " + "; ".join(files)
                    + "; adopt each with python3 scripts/sync_copies.py --adopt <copy>", "copy-not-adopted")


def flags_markdown(report, skills):
    """The named warning rules and the skills each one lists, as the Markdown of docs/architecture/phase-c-flags.md."""
    by_rule = {}
    for w in report.warnings:
        if w.get("rule"):
            by_rule.setdefault(w["rule"], []).append(w)
    lines = ["# What the validator's warning rules list, by rule", "",
             "Generated by `python3 scripts/validate.py --flags`; never edited by hand. It is a snapshot of the tree "
             "it was generated on: a row of phase C reads the lines of its skill here, and the current list is "
             "always what the command prints. Each rule is described in the docstring of `scripts/validate.py`.", "",
             f"Skills validated: {skills}.", "", "| Rule | Skills listed |", "|------|---------------|"]
    skill_of = lambda w: w["where"].split("/")[1] if w["where"].startswith("skills/") else w["where"]
    for rule in WARNING_RULES:
        lines.append(f"| `{rule}` | {len({skill_of(w) for w in by_rule.get(rule, [])})} |")
    for rule in WARNING_RULES:
        lines += ["", f"## `{rule}`", ""]
        found = by_rule.get(rule, [])
        if not found:
            lines.append("Nothing listed.")
        for w in sorted(found, key=lambda w: w["where"]):
            lines.append(f"- `{skill_of(w)}`: {w['message'][len(rule) + 3:]}")
    return "\n".join(lines) + "\n"


WARNING_RULES = ("meta-keys", "description-when", "description-length", "skill-tokens", "eval-cases-count", "eval-keys",
                 "eval-assertions-count", "eval-conditional-assertion", "eval-run-assertion", "eval-prompt-names-skill",
                 "eval-product-names", "skill-name", "routing-table", "test-file-names", "copy-not-adopted",
                 "guard-missing", "guard-cannot-fail")
# Named rules that were warnings while the rows of phase C were open and are errors since the sweep that closed it
# (C0.10 of docs/architecture/final-plan-2026-10-02.md): the seven rules of the artifact contract (C0.1) and the
# three vocabulary rules (C0.2). Report.warn reports them as errors; version-bump and guard-effect, the two rules
# of the reliability model that were warnings until then, are errors through the empty TRANSITIONAL_RULES.
ERROR_RULES = ("requires-role", "requires-vocabulary", "side-effects-vocabulary", "contract-updates", "contract-owner",
               "contract-inputs", "contract-overlap", "contract-placeholder", "contract-cycle", "contract-owner-table")


def artifact_key(path):
    """What makes two declared paths the same artifact: every placeholder read as a wildcard."""
    return PLACEHOLDER_RE.sub("*", path)


def markdown_table(text, first_header, after=None):
    """The rows (lists of cells, backticks stripped) of the first Markdown table whose first header cell is
    `first_header`, looked for after the heading `after` when one is given; None when there is none."""
    if after is not None:
        m = re.search(r"^#+\s*" + re.escape(after) + r"\s*$", text, re.M)
        if not m:
            return None
        text = text[m.end():]
    m = re.search(r"^\|\s*" + re.escape(first_header) + r"\s*\|.*$", text, re.M)
    if not m:
        return None
    rows = []
    for line in text[m.end():].lstrip("\n").split("\n"):
        if not line.startswith("|"):
            break
        cells = [c.strip().strip("`").strip() for c in line.strip().strip("|").split("|")]
        if not re.fullmatch(r":?-+:?", cells[0]):
            rows.append(cells)
    return rows


def load_owner_table_script(report, root=ROOT):
    """scripts/owner_table.py of the tree being validated; None, with a note, when it is not there (a folder
    an eval case builds brings the validator and not the generator)."""
    path = os.path.join(root, "scripts", "owner_table.py")
    if not os.path.isfile(path):
        report.note("[contract-owner-table] skipped: scripts/owner_table.py is not in this tree")
        return None
    spec = importlib.util.spec_from_file_location("owner_table", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_layout(report, root=ROOT):
    """What the rules read in contracts/project-layout.md: {"vocabulary": set of placeholders, "slots":
    [(path, provided by)], "owned": set of artifact keys the table of owning skills gives an owner}; None,
    with a note, when the contract is not in this tree."""
    path = os.path.join(root, LAYOUT)
    if not os.path.isfile(path):
        report.note(f"[contract-placeholder] skipped: {LAYOUT} is not in this tree (no slot and no owner is read from it)")
        return None
    with open(path, encoding="utf-8") as f:
        text = f.read()
    vocabulary = markdown_table(text, "Placeholder")
    slots = markdown_table(text, "Path", after=SLOTS_HEADING)
    if vocabulary is None:
        report.note(f"[contract-placeholder] skipped: {LAYOUT} has no table whose first column is Placeholder")
    owned = set()
    block = re.search(r"<!-- owner-table:begin -->(.*?)<!-- owner-table:end -->", text, re.S)
    for line in (block.group(1) if block else "").splitlines():
        m = re.match(r"\|\s*`([^`]+)`\s*\|\s*([^|]*?)\s*\|", line)
        if m and m.group(2) not in ("", "-"):
            owned.add(artifact_key(m.group(1)))
    return {"vocabulary": None if vocabulary is None else {r[0] for r in vocabulary if PLACEHOLDER_RE.fullmatch(r[0])},
            "slots": [(r[0], r[1] if len(r) > 1 else "") for r in slots or []], "owned": owned}


def cycles(edges):
    """The groups of more than one node that reach each other, in a graph given as {node: set of nodes}
    (Tarjan's strongly connected components, without recursion)."""
    index, low, on_stack, stack, found, counter = {}, {}, set(), [], [], [0]
    for start in sorted(edges):
        if start in index:
            continue
        work = [(start, iter(sorted(edges.get(start, ()))))]
        index[start] = low[start] = counter[0]
        counter[0] += 1
        stack.append(start)
        on_stack.add(start)
        while work:
            node, successors = work[-1]
            advanced = False
            for nxt in successors:
                if nxt not in index:
                    index[nxt] = low[nxt] = counter[0]
                    counter[0] += 1
                    stack.append(nxt)
                    on_stack.add(nxt)
                    work.append((nxt, iter(sorted(edges.get(nxt, ())))))
                    advanced = True
                    break
                if nxt in on_stack:
                    low[node] = min(low[node], index[nxt])
            if advanced:
                continue
            work.pop()
            if work:
                low[work[-1][0]] = min(low[work[-1][0]], low[node])
            if low[node] == index[node]:
                group = []
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    group.append(member)
                    if member == node:
                        break
                if len(group) > 1:
                    found.append(sorted(group))
    return sorted(found)


def check_contract(skills, report, root=ROOT):
    """The seven rules of the artifact contract (see the module docstring), as errors (ERROR_RULES)."""
    layout = load_layout(report, root)
    built = {s["name"] for s in skills}
    owners, canonical = {}, {}  # canonical: the spelling of an artifact, its owner's when it has one
    for field in ("outputs", "updates", "inputs"):
        for s in skills:
            for path in s[field]:
                canonical.setdefault(artifact_key(path), (path, s["name"]))
                if field == "outputs" and s["name"] not in owners.setdefault(artifact_key(path), []):
                    owners[artifact_key(path)].append(s["name"])
    known = set(owners) | (layout["owned"] if layout else set())
    slots = {artifact_key(p) for p, _ in layout["slots"]} if layout else set()
    vocabulary = layout["vocabulary"] if layout else None

    for s in skills:
        where, own = s["where"], {artifact_key(p) for p in s["outputs"]}
        lost = [p for p in s["updates"] if artifact_key(p) not in known]
        if lost:
            report.warn(where, f"updates {', '.join(lost)}: no skill's outputs lists it, so it has no owner", "contract-updates")
        shared = [f"{p} (also {', '.join(o for o in owners[artifact_key(p)] if o != s['name'])})"
                  for p in s["outputs"] if len(owners[artifact_key(p)]) > 1]
        if shared:
            report.warn(where, f"outputs {'; '.join(shared)}: an artifact has one owner, and every other skill "
                        "that writes into it lists it in updates", "contract-owner")
        dangling = [p for p in s["inputs"] if artifact_key(p) not in known and artifact_key(p) not in slots]
        if dangling:
            report.warn(where, f"input {', '.join(dangling)}: no skill's outputs lists it and it is not in the table "
                        f"\"{SLOTS_HEADING}\" of {LAYOUT}", "contract-inputs")
        both = [p for p in s["updates"] if artifact_key(p) in own]
        if both:
            report.warn(where, f"{', '.join(both)} is in outputs and in updates: the owner lists it in outputs only",
                        "contract-overlap")
        bad = []
        for field in ARTIFACT_FIELDS:
            for path in s[field]:
                unknown = [] if vocabulary is None else sorted(set(PLACEHOLDER_RE.findall(path)) - vocabulary)
                stripped = PLACEHOLDER_RE.sub("", path)
                if unknown:
                    bad.append(f"{path} ({', '.join(unknown)} is not in the vocabulary of {LAYOUT})")
                elif not PATH_OK_RE.match(path) or "<" in stripped or ">" in stripped or re.search(r"(?<![A-Za-z])NNNN(?![A-Za-z])", stripped):
                    bad.append(f"{path} (a wildcard other than a placeholder: no *, {{}}, #, bare NNNN or space)")
                elif canonical[artifact_key(path)][0] != path:
                    bad.append("{} (the same artifact is spelled {} in {})".format(path, *canonical[artifact_key(path)]))
        if bad:
            report.warn(where, "declared path " + "; ".join(bad), "contract-placeholder")

    for path, provided in layout["slots"] if layout else []:
        problem = None
        planned = re.fullmatch(r"planned:\s*(\S+)", provided)
        if artifact_key(path) in owners:
            problem = f"{', '.join(owners[artifact_key(path)])} owns it now: remove the row"
        elif planned and planned.group(1) in built:
            problem = f"{planned.group(1)} is built: remove the row and declare the path in its outputs"
        elif provided != "user" and not planned:
            problem = f"\"Provided by\" is {provided!r}; it is user or planned: <skill>"
        if problem:
            report.warn(LAYOUT, f"slot {path}: {problem}", "contract-inputs")

    edges = {}
    for s in skills:
        for path in s["inputs"]:
            for owner in owners.get(artifact_key(path), []):
                if owner != s["name"]:
                    edges.setdefault(owner, set()).add(s["name"])
    for group in cycles(edges):
        report.warn("skills", f"the graph \"owner of a path -> skill that reads it\" has a cycle of {len(group)} "
                    f"skills, so it gives no order: {', '.join(group)}", "contract-cycle")

    generator = load_owner_table_script(report, root)
    if generator is not None and layout is not None:
        state = generator.current(skills, root)
        if state is None:
            report.note(f"[contract-owner-table] skipped: {LAYOUT} has no owner-table block")
        elif not state:
            report.warn(LAYOUT, "the table of owning skills differs from the skills' frontmatter: "
                        "run python3 scripts/owner_table.py", "contract-owner-table")


def check_architecture_tables(report, root=ROOT):
    """[architecture-tables]: each generated block of docs/architecture/platform/ that differs from its source, or
    that cannot be generated, is a warning (a snapshot behind the code, never an error). Reads
    scripts/architecture_tables.py of the tree by path; a tree without it or without the pages is a note."""
    path = os.path.join(root, "scripts", "architecture_tables.py")
    if not os.path.isfile(path) or not os.path.isdir(os.path.join(root, "docs", "architecture", "platform")):
        report.note("[architecture-tables] skipped: scripts/architecture_tables.py or docs/architecture/platform/ "
                    "is not in this tree")
        return
    spec = importlib.util.spec_from_file_location("architecture_tables_under_validate", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for page, name, problem in module.stale_blocks(root):
        report.warn(page, f"the generated block {name}: {problem}; run python3 scripts/architecture_tables.py --write",
                    "architecture-tables")


BILLING_WORDS = ("subscription", "metered", "free")


def check_adapter_manifests(report, root=ROOT):
    """[adapter-billing]: every entry of "secrets" in adapters/<harness>/adapter.json has "billing", one of BILLING_WORDS;
    "login_billing", when a manifest has it, is one of them; a credential two manifests list has one word. Each finding is
    an error. A manifest with no "secrets" list has nothing to declare; one that is not JSON is reported."""
    folder = os.path.join(root, "adapters")
    if not os.path.isdir(folder):
        report.note("[adapter-billing] skipped: adapters/ is not in this tree")
        return
    seen = {}
    for name in sorted(os.listdir(folder)):
        path = os.path.join(folder, name, "adapter.json")
        if not os.path.isfile(path):
            continue
        where = f"adapters/{name}/adapter.json"
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError) as e:
            report.error(where, f"[adapter-billing] cannot be read as JSON ({type(e).__name__})")
            continue
        if not isinstance(data, dict):
            report.error(where, "[adapter-billing] holds one JSON object")
            continue
        login = data.get("login_billing")
        if "login_billing" in data and login not in BILLING_WORDS:
            report.error(where, f"[adapter-billing] login_billing is {login!r}: one of {', '.join(BILLING_WORDS)}")
        for entry in data.get("secrets") or []:
            secret = entry.get("name") if isinstance(entry, dict) else None
            word = entry.get("billing") if isinstance(entry, dict) else None
            if word not in BILLING_WORDS:
                report.error(where, f"[adapter-billing] the secret {secret!r} has billing {word!r}: it states how the credential "
                                    f"is billed, subscription, metered or free")
                continue
            if secret in seen and seen[secret][0] != word:
                report.error(where, f"[adapter-billing] the secret {secret} is billed {word} here and {seen[secret][0]} in "
                                    f"adapters/{seen[secret][1]}/adapter.json: one credential has one billing")
            seen.setdefault(secret, (word, name))


FLOWS_HEADING = "Flows (`flow-`)"


def check_flows(skills, report, root=ROOT):
    """The three rules of the flow files (see the module docstring), as errors: [flow-file], [flow-dependencies],
    [flow-inventory]. Reads runtime/flow_files.py of the tree by path; a tree without flows/ or without that
    module is a note."""
    module_path = os.path.join(root, "runtime", "flow_files.py")
    folder = os.path.join(root, "flows")
    if not os.path.isdir(folder) or not os.path.isfile(module_path):
        report.note("[flow-file] [flow-dependencies] [flow-inventory] skipped: flows/ or runtime/flow_files.py "
                    "is not in this tree")
        return
    spec = importlib.util.spec_from_file_location("flow_files_under_validate", module_path)
    flow_files = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(flow_files)
    info = {}
    for s in skills:
        md = os.path.join(root, "skills", s["name"], "SKILL.md")
        try:
            with open(md, encoding="utf-8") as f:
                text = f.read()
        except OSError:
            text = ""
        info[s["name"]] = {"inputs": s["inputs"], "outputs": s["outputs"], "skill_md": text}
    rows = None
    inventory = os.path.join(root, "docs", "inventory.md")
    if os.path.isfile(inventory):
        with open(inventory, encoding="utf-8") as f:
            rows = markdown_table(f.read(), "Flow", after=FLOWS_HEADING)
    for name in flow_files.names(root):
        where = f"flows/{name}.json"
        try:
            with open(os.path.join(folder, name + ".json"), encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError) as e:
            report.error(where, f"[flow-file] not a readable JSON file: {e}")
            continue
        found = flow_files.problems(data, name, root)
        for text in found:
            report.error(where, f"[flow-file] {text}")
        if found:
            continue
        for text in flow_files.dependency_problems(data, info):
            report.error(where, f"[flow-dependencies] {text}")
        row = next((r for r in rows or [] if r and r[0] == f"flow-{name}"), None)
        if row is None:
            continue
        cell = row[2] if len(row) > 2 else ""
        phases = [p.strip() for p in cell.split("→")]
        phases = [p[:-len(" (optional)")].strip() if p.endswith(" (optional)") else p for p in phases]
        expected = [t["skill"].split("-", 1)[1] if "-" in t["skill"] else t["skill"] for t in data["tasks"]]
        if phases != expected:
            arrow = " → "
            report.error("docs/inventory.md", f"[flow-inventory] the Phases of flow-{name} are "
                         f"{arrow.join(phases)!r}; {where} plans {arrow.join(expected)!r}: write the "
                         "file's tasks, in order, in that cell")


def check_agent(filename, report):
    where = f"agents/{filename}"
    path = os.path.join(AGENTS, filename)
    fm_text, _ = split_frontmatter(path)
    if fm_text is None:
        report.error(where, "agent must start with YAML frontmatter")
        return
    try:
        fm = load_yaml(fm_text)
    except Exception as e:  # noqa: BLE001
        report.error(where, f"frontmatter is not valid YAML: {e}")
        return
    stem = filename[:-3]
    if fm.get("name") != stem:
        report.error(where, f"frontmatter name {fm.get('name')!r} must equal file stem {stem!r}")
    extra = set(fm) - AGENT_KEYS
    if extra:
        report.error(where, f"harness-specific keys belong in adapters/<harness>/overrides/: {sorted(extra)}")


def harness_scope(rel):
    """How a core file is read for harness names: None (not read), "narrow" (names and folders only: the
    fixtures of eval cases) or "wide"."""
    parts = rel.split("/")
    if parts[0] == "skills" and len(parts) > 3 and parts[2] == "evals":
        if parts[3:] == ["result.json"] or parts[3] == "evidence":
            return None  # an old record and an evidence line name their adapter by design
        if "files" in parts[3:-1]:
            return "narrow"  # evals/files/... and evals/platforms/<platform>/files/...
    return "wide"


def workbench_file_values(text):
    """The paths a case file brings from the repository (`workbench_files`): adapter paths, legally."""
    try:
        data = json.loads(text)
    except ValueError:
        return []
    cases = data.get("evals") if isinstance(data, dict) else None
    values = set()
    for c in cases if isinstance(cases, list) else []:
        listed = c.get("workbench_files") if isinstance(c, dict) else None
        values.update(v for v in (listed if isinstance(listed, list) else []) if isinstance(v, str))
    return sorted(values, key=len, reverse=True)


def check_harness_names(report, root=None):
    """harness-name: principle 1 (see the module docstring for what is read and what is exempt)."""
    root = root or ROOT
    scanner = load_scanner()
    entries, _ = scanner.load_allow_file(root)
    for path in sorted(scanner.list_files(root, None)):
        rel = os.path.relpath(path, root).replace(os.sep, "/")
        if rel.split("/")[0] not in CORE_DIRS:
            continue
        scope = harness_scope(rel)
        text = scanner.read_text(path) if scope else None
        if text is None:
            continue
        if scope == "wide" and scanner.path_allowed(entries, rel, HARNESS_RULE):
            scope = "narrow"
        pattern = HARNESS_RE if scope == "wide" else HARNESS_NARROW_RE
        exempt = []
        if scope == "wide" and re.fullmatch(r"skills/[^/]+/evals/(?:evals|platforms/[^/]+)\.json", rel):
            exempt = [json.dumps(v) for v in workbench_file_values(text)]
        for ln, line in enumerate(text.splitlines(), 1):
            for quoted in exempt:
                line = line.replace(quoted, '""')
            m = pattern.search(line)
            if m:
                report.error(f"{rel}:{ln}", f"[{HARNESS_RULE}] core file references a harness: {m.group(0)!r}")


def load_scanner():
    # Beside this file, whatever tree is being validated.
    spec = importlib.util.spec_from_file_location(
        "security_scan", os.path.join(os.path.dirname(os.path.abspath(__file__)), "security_scan.py"))
    scanner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scanner)
    return scanner


def check_english(report, root=ROOT):
    """english-only: tracked text files carry no Portuguese-specific diacritics or words.

    A line is exempt when it carries `validate: allow english-only -- <reason>`; a whole file
    when .security-scan-allow has `<path glob> english-only -- <reason>`.
    """
    scanner = load_scanner()
    entries, _ = scanner.load_allow_file(root)
    for path in sorted(scanner.list_files(root, None)):
        rel = os.path.relpath(path, root).replace(os.sep, "/")
        if rel.startswith(".git/") or scanner.path_allowed(entries, rel, "english-only"):
            continue
        text = scanner.read_text(path)
        if text is None:
            continue
        for ln, line in enumerate(text.splitlines(), 1):
            m = PORTUGUESE_RE.search(line)
            if not m:
                continue
            allow = ENGLISH_ALLOW_RE.search(line)
            if allow and allow.group(1):
                continue
            if allow:
                report.error(f"{rel}:{ln}", "[english-only] the allow needs a reason: "
                             "validate: allow english-only -- <reason>")
                continue
            report.error(f"{rel}:{ln}", f"[english-only] Portuguese text {m.group(0)!r}; "
                         "every file is written in English (AGENTS.md principle 6)")


PRIVATE_ALLOW_RE = re.compile(r"validate:\s*allow\s+private-term(?:\s+--\s+(\S.*?))?\s*(?:-->|\*/)?\s*$")


def load_private_terms(root=ROOT):
    """Return (patterns, excluded path globs, the file's path) from the local terms file; no patterns when there
    is none."""
    path = os.environ.get("WORKBENCH_PRIVATE_TERMS") or os.path.join(root, ".private-terms")
    try:
        lines = open(path, encoding="utf-8").read().splitlines()
    except OSError:
        return [], [], path
    patterns, excluded = [], []
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("!"):
            excluded.append(line[1:].strip())
        elif line.startswith("re:"):
            patterns.append(re.compile(line[3:], re.I))
        else:
            patterns.append(re.compile(re.escape(line), re.I))
    return patterns, excluded, os.path.abspath(path)


def check_private_terms(report, root=ROOT):
    """private-term: no tracked text file names what the local terms file lists (see the module docstring)."""
    patterns, excluded, terms_file = load_private_terms(root)
    if not patterns:
        return
    scanner = load_scanner()
    for path in sorted(scanner.list_files(root, None)):
        rel = os.path.relpath(path, root).replace(os.sep, "/")
        if (rel.startswith(".git/") or os.path.abspath(path) == terms_file
                or any(fnmatch.fnmatch(rel, g) for g in excluded)):
            continue
        text = scanner.read_text(path)
        if text is None:
            continue
        for ln, line in enumerate(text.splitlines(), 1):
            hit = next((m for p in patterns for m in [p.search(line)] if m), None)
            if not hit:
                continue
            allow = PRIVATE_ALLOW_RE.search(line)
            if allow and allow.group(1):
                continue
            report.error(f"{rel}:{ln}", f"[private-term] {hit.group(0)!r} is listed in the local private terms; "
                         "write it generically, and keep the case in the project that uses it")


def load_eval_status():
    spec = importlib.util.spec_from_file_location("eval_status", os.path.join(ROOT, "evals", "eval_status.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check_eval_cases(report, root=ROOT):
    """Every skill's eval cases pass the runner's preflight (evals/eval_run.py --check-cases; no model call):
    a file a prompt cites is shipped at the path it names, grader files and dependency skills exist."""
    from concurrent.futures import ThreadPoolExecutor
    runner = os.path.join(root, "evals", "eval_run.py")
    base = os.path.join(root, "skills")
    if not os.path.isfile(runner) or not os.path.isdir(base):
        return
    names = sorted(d for d in os.listdir(base) if os.path.isfile(os.path.join(base, d, "evals", "evals.json")))

    def one(name):
        return name, subprocess.run([sys.executable, runner, "--skill", name, "--check-cases"],
                                    capture_output=True, text=True, cwd=root)
    with ThreadPoolExecutor(max_workers=8) as pool:  # independent checks, run together (principle 7)
        results = list(pool.map(one, names))
    for name, r in results:
        if r.returncode != 0:
            lines = [l for l in r.stderr.strip().splitlines() if l.strip()]
            report.error(f"skills/{name}/evals/evals.json", "[eval-cases] " + ("; ".join(lines[-6:]) or "the preflight failed")
                         + f" (python3 evals/eval_run.py --skill {name} --check-cases)")


def check_eval_status(report, root=ROOT):
    """eval-status: the gate file is valid and its fingerprint is this checkout's, every evidence file and line is
    valid (errors); the snapshot tables of docs/inventory.md are not behind the evidence, and the skills of each
    band other than `reliable` are listed, one warning line per band, with their causes (warnings). A score, a
    band or a snapshot behind is never an error (the reliability model, sections 5 and 10)."""
    es = load_eval_status()
    problems = es.gate_problems(root)
    if problems:
        report.error("evals/eval-gate.json", f"[eval-status] {'; '.join(problems)}")
    elif es.fingerprint_problem(root):
        report.error("evals/eval-gate.json", f"[measurement] {es.fingerprint_problem(root)}")
    found, _ = es.evidence_problems(root)
    for path, problems in sorted(found.items()):
        report.error(path, f"[evidence] {'; '.join(problems[:5])}" + (f"; and {len(problems) - 5} more" if len(problems) > 5 else ""))
    try:
        if not es.inventory_current(root):
            report.warn("docs/inventory.md", "[snapshot] the snapshot tables are behind the evidence: they are regenerated "
                        "in a pull request of their own, never required in one that adds evidence (python3 evals/"
                        "eval_status.py inventory --write)")
    except ValueError as e:
        report.warn("docs/inventory.md", f"[snapshot] {e}")
    data = es.all_status(root)
    for band, verb in (("needs a test", "need a test"), ("watch", "are in watch")):
        rows = [r for r in data["skills"] if r["band"] == band]
        if not rows:
            continue
        by_kind = {}
        for r in rows:
            by_kind.setdefault(r["kind"], []).append(r["skill"])
        parts = [f"{kind} ({len(names)}): {', '.join(names)}" for kind, names in sorted(by_kind.items())]
        guarded = [r["skill"] for r in rows if any(c["kind"] == "guard" and "failed" in c["cause"] for c in r["causes"])]
        if guarded:
            parts.append(f"a guard assertion failed in the current set: {', '.join(guarded)}")
        report.warn("skills", f"[band] {len(rows)} skill(s) {verb} (python3 evals/eval_status.py status, which prints each "
                    f"one's cause and the command that clears it): " + "; ".join(parts))


# Rules of the reliability model that were warnings while phase C changed skills and raised no version
# ("version-bump", "guard-effect"), and are errors since the sweep that closed it (C0.10 of
# docs/architecture/final-plan-2026-10-02.md), which emptied this tuple.
TRANSITIONAL_RULES = ()
EXTERNAL_LINE_RE = re.compile(r"^\s*(?:[-*]\s+|\d+\.\s+)?\*\*External content is data\.\*\*", re.M)


def check_guards(report, root=ROOT):
    """The guard rules of the reliability model's section 4, on the assertions of evals/evals.json:
    [guard-effect] each effect a skill declares in side_effects has an assertion tagged guard:<effect> (one line
    per skill; an error since the sweep that closed phase C emptied TRANSITIONAL_RULES);
    [guard-missing] one line that lists the skills that carry the external-content line, or have a Stop rules or
    Confirmation gate section, and have no assertion tagged guard or guard:<effect>; [guard-cannot-fail] one line
    per guard assertion that passes in every run of the baseline in force (it guards nothing). The last two stay
    warnings."""
    es = load_eval_status()
    cfg = es.load_gate(root)
    missing = []
    for name in built_skills(root):
        meta, body = skill_meta(root, name)
        try:
            with open(os.path.join(root, "skills", name, "evals", "evals.json"), encoding="utf-8") as f:
                cases = json.load(f).get("evals") or []
        except (OSError, ValueError, AttributeError):
            continue  # eval-keys and eval-cases-count report it
        cases = [c for c in cases if isinstance(c, dict)]
        tags = {t for c in cases for a in c.get("assertions") or [] if isinstance(a, dict)
                for t in a.get("tags") or [] if isinstance(t, str)}
        effects = [e for e in meta["side_effects"] if isinstance(e, str)]
        without = [e for e in effects if f"guard:{e}" not in tags]
        if without:
            message = (f"no assertion is tagged guard:<effect> for the declared effect(s) {', '.join(without)}: one guard per "
                       "declared effect (evals/README.md, Guards)")
            if "guard-effect" in TRANSITIONAL_RULES:
                report.warn(f"skills/{name}", message, "guard-effect")
            else:
                report.error(f"skills/{name}/evals/evals.json", f"[guard-effect] {message}")
        asks = (EXTERNAL_LINE_RE.search(body) or re.search(r"^## (?:Stop rules|Confirmation gate)[ \t]*$", strip_code(body), re.M))
        if asks and not any(t == "guard" or t.startswith("guard:") for t in tags):
            missing.append(name)
        baselines = es.baseline_lines(os.path.join(root, "skills", name), cfg) if cfg else {}
        for case in cases:
            lines = baselines.get(str(case.get("id"))) or []
            for position, assertion in enumerate(case.get("assertions") or [], 1):
                guard = isinstance(assertion, dict) and any(isinstance(t, str) and (t == "guard" or t.startswith("guard:"))
                                                            for t in assertion.get("tags") or [])
                if guard and lines and all(len(l["results"]) >= position and l["results"][position - 1] == 1 for l in lines):
                    report.warn(f"skills/{name}", f"case {case.get('id')}, assertion {position}: a guard assertion that passes in "
                                f"every run of the baseline in force ({len(lines)} runs) cannot fail, and guards nothing: word it "
                                "on what a run without the skill gets wrong", "guard-cannot-fail")
    if missing:
        report.warn("skills", f"{len(missing)} skill(s) carry the external-content line, a Stop rules or a Confirmation gate "
                    f"section, and no assertion tagged guard: {', '.join(missing)}", "guard-missing")


def check_versions(report, root=ROOT):
    """The version rules of the reliability model's section 3, against the base of the pull request (the merge
    base with the default branch, or WB_BASE_REF): [version-bump] a change with no bump (one line per finding,
    listing the skills); [version-file] a version file outside its form or not append-only; [version-class] a
    declared class the diff contradicts. Without a base the last two are skipped and a NOTE says so."""
    es = load_eval_status()
    names = es.skill_names(root)
    if not names:
        return
    base = es.comparison_base(root)
    if base is None:
        report.note("[version-file] [version-class] skipped: no comparison base (not a git checkout, or no default branch)")
    bumps = {}
    for name in names:
        found = es.version_findings(root, name, base)
        for rule in ("file", "class"):
            for problem in found[rule]:
                report.error(f"skills/{name}/evals/versions.jsonl", f"[version-{rule}] {problem}")
        for problem in found["bump"]:
            bumps.setdefault(problem, []).append(name)
    fix = {"no version file": "python3 evals/eval_status.py bump --skill <name> writes a new skill's first line",
           "changed without a bump": "python3 evals/eval_status.py bump --skill <name> --class x|y|z",
           "metadata.version is not X.Y.Z": "write it as X.Y.Z with python3 evals/eval_status.py bump --skill <name> --class x|y|z",
           "metadata.version is not the version of the last line": "python3 evals/eval_status.py bump --skill <name> again"}
    for problem, skills in sorted(bumps.items()):
        message = f"{len(skills)} skill(s): {problem} ({fix.get(problem, '')}): {', '.join(skills)}"
        if "version-bump" in TRANSITIONAL_RULES:
            report.warn("skills", message, "version-bump")
        else:
            report.error("skills", f"[version-bump] {message}")


def check_security(report):
    scanner = load_scanner()
    _, active, _ = scanner.scan(ROOT)
    for f in active:
        add = report.error if f["severity"] == "error" else report.warn
        add(f"{f['path']}:{f['line']}", f"[{f['rule']}] {f['message']} (see scripts/security_scan.py)")


def run_spec_validator(report):
    tool = shutil.which("skills-ref")
    if not tool:
        report.warn("scripts/validate.py", "--spec requested but skills-ref is not installed; skipped")
        return
    for d in sorted(os.listdir(SKILLS)):
        if os.path.isdir(os.path.join(SKILLS, d)):
            r = subprocess.run([tool, "validate", os.path.join(SKILLS, d)], capture_output=True, text=True)
            if r.returncode != 0:
                report.error(f"skills/{d}", f"skills-ref: {r.stdout.strip() or r.stderr.strip()}")


def main(argv):
    if "--help" in argv or "-h" in argv:
        print(__doc__)
        return 0
    unknown = [a for a in argv if a not in ("--strict", "--json", "--spec", "--flags")]
    if unknown:
        print(f"Error: unknown option(s) {unknown}. See --help.", file=sys.stderr)
        return 2
    strict, as_json, spec, flags = "--strict" in argv, "--json" in argv, "--spec" in argv, "--flags" in argv
    if as_json and flags:
        print("Error: --json and --flags both print to stdout; give one. See --help.", file=sys.stderr)
        return 2
    report = Report()
    outputs_index, skills = {}, []

    built = built_skills()
    if os.path.isdir(SKILLS):
        classes = load_classes(report)
        for d in sorted(os.listdir(SKILLS)):
            if os.path.isdir(os.path.join(SKILLS, d)):
                s = check_skill(d, report, outputs_index, classes)
                if s:
                    skills.append(s)
                if d in built:
                    check_evals(d, report)
                    check_skill_names(d, report, built)
        check_routing(report, built)
    check_contract(skills, report)
    check_flows(skills, report)
    check_architecture_tables(report)
    check_adapter_manifests(report)
    if os.path.isdir(AGENTS):
        for fn in sorted(os.listdir(AGENTS)):
            if fn.endswith(".md"):
                check_agent(fn, report)
    check_doc_links(report)
    check_copies(report)
    check_test_names(report)
    check_harness_names(report)
    check_english(report)
    check_private_terms(report)
    check_eval_status(report)
    check_versions(report)
    check_guards(report)
    check_eval_cases(report)
    check_security(report)
    if spec:
        run_spec_validator(report)

    for e in report.errors:
        print(f"ERROR   {e['where']}: {e['message']}", file=sys.stderr)
    for w in report.warnings:
        print(f"WARNING {w['where']}: {w['message']}", file=sys.stderr)
    for n in report.notes:
        print(f"NOTE    {n}", file=sys.stderr)
    failed = bool(report.errors) or (strict and bool(report.warnings))
    summary = {
        "skills": len(skills),
        "errors": len(report.errors),
        "warnings": len(report.warnings),
        "ok": not failed,
    }
    if flags:
        print(flags_markdown(report, len(skills)), end="")
    elif as_json:
        print(json.dumps({"summary": summary, "errors": report.errors, "warnings": report.warnings}, indent=2))
    else:
        print(json.dumps(summary))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
