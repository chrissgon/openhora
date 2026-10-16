#!/usr/bin/env python3
"""Initialize or update a project for the workbench.

Usage:
  python3 init_project.py --root <dir> --detect
  python3 init_project.py --root <dir> --apply --autonomy <mode> [--docs <docs>] [--input <file>] [--name <name>] [--register <path>=<slot>]... [--dry-run]
  python3 init_project.py --root <dir> [--set-autonomy <mode>] [--docs <docs>] [--input <file>] [--register <path>=<slot>]... [--dry-run]

--detect   prints JSON: is_project_root, name_guess, state_exists, autonomy (the current mode, or null),
           agents_md (exists, has_section), root_docs (specification-like *.md at the root),
           proposed_registrations (file, slot and the ready --register value, matched by file name),
           unmatched_root_docs (open them to pick a slot), excluded, docs_dir (count, names),
           not_registered (file and reason), docs_in_git (the recorded docs/ decision, or null),
           next ("init" or "update") and summary: one line to quote.
--apply    creates docs/workbench/state.md and the workbench section in AGENTS.md. Refuses if state exists.
Update     (no --apply) changes the autonomy mode or the docs/ decision, and/or adds registrations to an
           existing state.
           --apply and update print JSON with "report": the lines of the reply's report, filled in.
--register <path>=<slot>  registers an existing document as the artifact <slot> (docs/<area>/...), in place.
                          The path must stay inside --root.
--input <file>            a JSON file (or - for stdin) with the user's own words, which never go on the
                          command line where quotes or $( ) would break out:
                          {"name": "<name>", "decisions": ["<text>", ...], "open_questions": ["<text>", ...]}
                          Every key is optional. Decisions and open questions are recorded as stated;
                          a line break inside one becomes a space. A file named
                          .workbench-init-input.json is deleted after a run that wrote the state.
--name <name>             the project name, when it is only letters, digits, spaces, '.', '_' or '-';
                          any other name goes in --input.
--autonomy / --set-autonomy  one of: every-phase, milestones, end.
--docs <docs>  which workbench folders under docs/ go into git: all, code (only docs/product/, docs/design/,
               docs/engineering/, docs/ai/ and docs/delivery/; the rest is work data) or none. Recorded as the
               state line "- Docs in git: <docs>" and in the AGENTS.md section; for code and none the folders
               kept out are written to .gitignore between "# workbench:start" and "# workbench:end". Left out
               with --apply, the decision is recorded as undecided with an open question, and nothing is
               written to .gitignore.
--dry-run  prints the plan, writes nothing.

Never moves, renames or edits registered documents. Never edits AGENTS.md or .gitignore outside the markers.
Exit codes: 0 ok, 1 refused (state exists with --apply, missing path, bad slot), 2 usage error (on stderr).
"""
import datetime as dt
import json
import os
import re
import sys

MODES = ("every-phase", "milestones", "end")
DOCS_CHOICES = ("all", "code", "none")
UNDECIDED = "undecided"
# The workbench folders under docs/ (contracts/project-layout.md), by kind: what describes the code and the
# product, and the work data around it. End-user documentation elsewhere under docs/ is never touched.
CODE_DOCS = ("docs/product/", "docs/design/", "docs/engineering/", "docs/ai/", "docs/delivery/")
WORK_DOCS = ("docs/workbench/", "docs/business/", "docs/brand/", "docs/marketing/", "docs/security/")
LOCAL_FOLDERS = {"all": (), "code": WORK_DOCS, "none": WORK_DOCS + CODE_DOCS, UNDECIDED: ()}
IGNORE_START = "# workbench:start (folders under docs/ kept out of git; written by core-project-init)"
IGNORE_END = "# workbench:end"
DOCS_QUESTION = ("Which workbench folders under docs/ go into git: all, code (only docs/product/, docs/design/, "
                 "docs/engineering/, docs/ai/ and docs/delivery/) or none? Recommended: code. "
                 "(raised by core-project-init)")
START, END = "<!-- workbench:start -->", "<!-- workbench:end -->"
EXCLUDED_STEMS = {"README", "LICENSE", "CHANGELOG", "CONTRIBUTING", "CODE_OF_CONDUCT", "SECURITY", "AGENTS"}
MANIFESTS = ("package.json", "pyproject.toml", "go.mod", "Cargo.toml", "composer.json", "pom.xml", "build.gradle", "Gemfile")
HERE = os.path.dirname(os.path.abspath(__file__))
SECTION_TEMPLATE = os.path.join(HERE, "..", "assets", "agents-md-section.md")

STATE_TEMPLATE = """# Workbench state

- Project: {name}
- Current flow: none
- Current phase: none
- Updated: {date}
- Docs in git: {docs}

## Autonomy

- Checkpoints: {autonomy}

## Artifacts

| Artifact | Owner skill | Status | Updated |
|----------|-------------|--------|---------|
{rows}
## Decisions

- {date}: Project initialized for the workbench; autonomy {autonomy}. (core-project-init, confirmed by user)
{decisions}
## Open questions
{questions}
## Approvals

| Scope | What | Payload hash | Approved | Expires | Status |
|-------|------|--------------|----------|---------|--------|
"""


def usage_error(msg):
    print(f"Error: {msg} See --help.", file=sys.stderr)
    return 2


def refuse(msg):
    print(f"Error: {msg}", file=sys.stderr)
    return 1


INPUT_SCRATCH = ".workbench-init-input.json"

# File-name stems (upper case, "_" read as "-") and the slot they fill; first match wins. A stem that is
# ambiguous by name alone (DESIGN, SPEC, STYLE-GUIDE) is left out on purpose: the document must be opened.
SLOT_PATTERNS = (
    (("DESIGN-SYSTEM", "TOKENS", "THEME"), "docs/design/design-system.md"),
    (("ARCHITECTURE", "SYSTEM-DESIGN"), "docs/engineering/architecture.md"),
    (("ADR", "DECISIONS"), "docs/engineering/adr/"),
    (("INTERFACE", "SCREENS", "UI"), "docs/design/screens/"),
    (("JOURNEY", "FLOWS", "UX"), "docs/design/flows.md"),
    (("HANDOFF",), "docs/engineering/plans/handoff.md"),
    (("MIGRATION",), "docs/engineering/plans/migration.md"),
    (("PRD", "REQUIREMENTS"), "docs/product/prd.md"),
    (("ROADMAP",), "docs/product/roadmap.md"),
    (("BRAND", "VOICE"), "docs/brand/guidelines.md"),
    (("BUSINESS", "BUSINESS-PLAN", "PITCH"), "docs/business/business-plan.md"),
    (("MARKETING", "LAUNCH", "LAUNCH-PLAN"), "docs/marketing/launch-plan.md"),
)


def slot_for(filename):
    """The slot a root document fills by its name, or None when the name does not say."""
    stem = filename[:-3].upper().replace("_", "-")
    for stems, slot in SLOT_PATTERNS:
        if stem in stems:
            return slot
    return None


def current_autonomy(root):
    try:
        with open(os.path.join(root, "docs", "workbench", "state.md"), encoding="utf-8") as f:
            m = re.search(r"^- Checkpoints: *([a-z-]+)", f.read(), re.M)
    except OSError:
        return None
    return m.group(1) if m else None


def current_docs(root):
    """The recorded docs/ decision of a state file, or None when the state or the line is missing."""
    try:
        with open(os.path.join(root, "docs", "workbench", "state.md"), encoding="utf-8") as f:
            m = re.search(r"^- Docs in git: *([a-z]+)", f.read(), re.M)
    except OSError:
        return None
    return m.group(1) if m else None


INSTRUCTION_HEADINGS = ("always", "never", "rules", "hard rules", "communication", "do", "don't", "workflow")


def looks_like_instructions(path):
    """Heuristic: a root document addressed to an AI tool rather than describing the project."""
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            head = f.read(6000)
    except OSError:
        return False
    first_heading = next((l for l in head.splitlines() if l.startswith("#")), "")
    if re.search(r"\binstructions?\b", first_heading, re.I):
        return True
    headings = [l.strip("# ").strip().lower() for l in head.splitlines() if l.startswith("## ")]
    return sum(1 for h in headings if h in INSTRUCTION_HEADINGS) >= 2


def name_guess(root):
    pj = os.path.join(root, "package.json")
    if os.path.isfile(pj):
        try:
            with open(pj, encoding="utf-8") as f:
                n = json.load(f).get("name")
            if n:
                return n.split("/")[-1]
        except (OSError, ValueError):
            pass
    py = os.path.join(root, "pyproject.toml")
    if os.path.isfile(py):
        with open(py, encoding="utf-8") as f:
            m = re.search(r'^name\s*=\s*"([^"]+)"', f.read(), re.M)
        if m:
            return m.group(1)
    return os.path.basename(os.path.abspath(root))


def has_version_control(root):
    """True when .git is a folder, or a regular file whose first line is "gitdir: <path>" and <path> (relative to
    the root, or absolute) names an existing folder: a linked worktree or a submodule keeps a file there."""
    marker = os.path.join(root, ".git")
    if os.path.isdir(marker):
        return True
    if not os.path.isfile(marker):
        return False
    try:
        with open(marker, encoding="utf-8") as f:
            first = f.readline().rstrip("\r\n")
    except (OSError, ValueError):
        return False
    if not first.startswith("gitdir:"):
        return False
    target = first[len("gitdir:"):].strip()
    return bool(target) and os.path.isdir(os.path.join(root, target))


def detect(root):
    is_root = has_version_control(root) or any(os.path.isfile(os.path.join(root, m)) for m in MANIFESTS)
    root_docs, excluded = [], []
    for fn in sorted(os.listdir(root)):
        if not fn.lower().endswith(".md") or not os.path.isfile(os.path.join(root, fn)):
            continue
        stem = fn[:-3]
        if stem.upper() in EXCLUDED_STEMS or stem.upper().startswith("README"):
            excluded.append({"file": fn, "reason": "never registered"})
        elif stem == stem.upper():
            if looks_like_instructions(os.path.join(root, fn)):
                excluded.append({"file": fn, "reason": "instructions for an AI tool; leave untouched"})
            else:
                root_docs.append(fn)
    docs_dir = os.path.join(root, "docs")
    docs_files = []
    if os.path.isdir(docs_dir):
        for dp, _, fns in os.walk(docs_dir):
            for fn in fns:
                rel = os.path.relpath(os.path.join(dp, fn), root).replace(os.sep, "/")
                if fn.endswith(".md") and not rel.startswith("docs/workbench/"):
                    docs_files.append(rel)
    agents = os.path.join(root, "AGENTS.md")
    has_section = False
    if os.path.isfile(agents):
        with open(agents, encoding="utf-8") as f:
            has_section = START in f.read()
    state_exists = os.path.isfile(os.path.join(root, "docs", "workbench", "state.md"))
    registered = ""
    if state_exists:
        with open(os.path.join(root, "docs", "workbench", "state.md"), encoding="utf-8") as f:
            registered = f.read()
    proposed = [{"file": fn, "slot": slot_for(fn), "register": f"{fn}={slot_for(fn)}"}
                for fn in root_docs if slot_for(fn) and f"(at {fn})" not in registered]
    unmatched = [fn for fn in root_docs if not slot_for(fn) and f"(at {fn})" not in registered]
    not_registered = [{"file": e["file"], "reason": e["reason"]} for e in excluded] + [
        {"file": p, "reason": "end-user documentation under docs/; registered only when the user asks"}
        for p in sorted(docs_files)[:50] if f"(at {p})" not in registered]
    autonomy = current_autonomy(root) if state_exists else None
    docs_in_git = current_docs(root) if state_exists else None
    name = name_guess(root)
    agents_exists = os.path.isfile(agents)
    summary = "Detected: {root}; name guess `{name}`; state file {state}; AGENTS.md {agents}; root specifications: {specs}.".format(
        root="a project root" if is_root else "NOT a project root (no version control, no manifest)",
        name=name,
        state=f"exists, autonomy `{autonomy}`" if state_exists else "missing (not initialized)",
        agents=("exists, with the workbench section" if has_section else "exists, without the workbench section")
        if agents_exists else "missing",
        specs=", ".join(root_docs) or "none")
    return {
        "root": os.path.abspath(root),
        "is_project_root": is_root,
        "name_guess": name,
        "state_exists": state_exists,
        "autonomy": autonomy,
        "agents_md": {"exists": agents_exists, "has_section": has_section},
        "root_docs": root_docs,
        "proposed_registrations": proposed,
        "unmatched_root_docs": unmatched,
        "excluded": excluded,
        "docs_dir": {"count": len(docs_files), "files": sorted(docs_files)[:50]},
        "not_registered": not_registered,
        "docs_in_git": docs_in_git,
        "next": "update" if state_exists else "init",
        "summary": summary,
    }


def docs_line(docs, ignore_action):
    if docs == UNDECIDED:
        return "- Documents in git: undecided (an open question in the state file; .gitignore untouched)"
    kept = LOCAL_FOLDERS[docs]
    where = ("every workbench folder under docs/ is committed" if not kept
             else "kept out of git: " + ", ".join(kept))
    return f"- Documents in git: {docs}; {where} (.gitignore {ignore_action})"


def report_lines(root, name, state_action, autonomy, agents_action, rows, not_registered, docs=UNDECIDED,
                 ignore_action="untouched"):
    """The reply's report, filled in from what the script did; `rows` are (slot, path) of every registration."""
    lines = [f"## Project initialized: {name}" if state_action == "created" else f"## Project updated: {name}", "",
             f"- State: docs/workbench/state.md ({state_action}), autonomy {autonomy}",
             f"- Instructions: AGENTS.md ({agents_action}); other content untouched",
             docs_line(docs, ignore_action)]
    if rows:
        lines += ["- Registered as existing artifacts (in place, owner `existing`; nothing moved, renamed or edited):",
                  "  | Slot | At | Owner | Status |", "  |------|----|-------|--------|"]
        lines += [f"  | {s} | {p} | existing | approved |" for s, p in rows]
    else:
        lines.append("- Registered as existing artifacts: none")
    skipped = [f"{e['file']} ({e['reason']})" for e in not_registered
               if not any(p == e["file"] for _, p in rows)]
    lines.append("- Not registered: " + ("; ".join(skipped) or "none"))
    return lines


def registered_rows(state):
    """(slot, path) of every `existing` row in a state file's text."""
    return re.findall(r"^\| *(\S+) \(at ([^)|]+)\) *\| *existing *\|", state, re.M)


def parse_registrations(items, root):
    regs = []
    for item in items:
        if "=" not in item:
            raise ValueError(f"--register expects <path>=<slot>, got {item!r}")
        path, slot = item.split("=", 1)
        path, slot = path.strip(), slot.strip()
        base = os.path.realpath(root)
        if os.path.isabs(path) or os.path.commonpath([base, os.path.realpath(os.path.join(base, path))]) != base:
            raise ValueError(f"registered path must stay inside the project root, got {path!r}")
        if ".." in slot.split("/") or "|" in path + slot or "\n" in path + slot:
            raise ValueError(f"--register {item!r} has '..', '|' or a line break")
        if not os.path.exists(os.path.join(root, path)):
            raise FileNotFoundError(f"registered path does not exist: {path}")
        if not slot.startswith("docs/"):
            raise ValueError(f"slot must start with docs/, got {slot!r}")
        regs.append((path, slot))
    return regs


def row(slot, path, date):
    return f"| {slot} (at {path}) | existing | approved | {date} |"


def section_text(autonomy, docs=UNDECIDED):
    with open(SECTION_TEMPLATE, encoding="utf-8") as f:
        return f.read().replace("{autonomy}", autonomy).replace("{docs}", docs).rstrip("\n") + "\n"


def ignore_block(docs):
    folders = LOCAL_FOLDERS[docs]
    if not folders:
        return ""
    return "\n".join([IGNORE_START, *("/" + f for f in folders), IGNORE_END]) + "\n"


def apply_gitignore(root, docs, dry):
    """Write, refresh or remove the block of folders kept out of git; nothing else in .gitignore changes.
    Returns what happened: untouched, created, block added, block updated, block removed or unchanged."""
    path = os.path.join(root, ".gitignore")
    block = ignore_block(docs)
    content = ""
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            content = f.read()
    has = IGNORE_START in content and IGNORE_END in content
    if not block and not has:
        return "untouched"
    if has:
        pre = content[: content.index(IGNORE_START)]
        post = content[content.index(IGNORE_END) + len(IGNORE_END):].lstrip("\n")
        new = pre + block + post if block else (pre.rstrip("\n") + "\n" + post if pre.strip() else post)
        action = "unchanged" if new == content else ("block updated" if block else "block removed")
    else:
        sep = "" if not content or content.endswith("\n\n") else ("\n" if content.endswith("\n") else "\n\n")
        new = content + sep + block
        action = "block added" if content else "created"
    if new != content:
        write(path, new, dry)
    return action


def upsert_section(content, section):
    if START in content and END in content:
        pre = content[: content.index(START)]
        post = content[content.index(END) + len(END):]
        return pre + section.rstrip("\n") + post, "section updated"
    sep = "" if content.endswith("\n\n") else ("\n" if content.endswith("\n") else "\n\n")
    return content + sep + section, "section added"


def write(path, content, dry):
    if dry:
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def apply(root, name, autonomy, regs, dry, decisions=(), questions=(), docs=UNDECIDED):
    date = dt.date.today().isoformat()
    state_path = os.path.join(root, "docs", "workbench", "state.md")
    if os.path.isfile(state_path):
        return refuse("docs/workbench/state.md already exists; use --set-autonomy, --docs or --register to update.")
    rows = "".join(row(s, p, date) + "\n" for p, s in regs)
    decided = [] if docs == UNDECIDED else [f"Workbench folders under docs/ in git: {docs}."]
    dec = "".join(f"- {date}: {d} (user)\n" for d in [*decided, *decisions])
    open_items = ([DOCS_QUESTION] if docs == UNDECIDED else []) + list(questions)
    que = "".join(f"- [ ] {q}\n" for q in open_items)
    write(state_path, STATE_TEMPLATE.format(name=name, date=date, autonomy=autonomy, docs=docs, rows=rows,
                                            decisions=dec, questions=que), dry)
    agents = os.path.join(root, "AGENTS.md")
    section = section_text(autonomy, docs)
    if os.path.isfile(agents):
        with open(agents, encoding="utf-8") as f:
            content, action = upsert_section(f.read(), section)
    else:
        content, action = f"# {name}\n\n" + section, "created"
    skipped = detect(root)["not_registered"]
    write(agents, content, dry)
    ignore_action = apply_gitignore(root, docs, dry)
    print(json.dumps({
        "dry_run": dry, "action": "apply", "name": name, "autonomy": autonomy, "docs_in_git": docs,
        "state": "created", "agents_md": action, "gitignore": ignore_action,
        "registered": [{"slot": s, "at": p} for p, s in regs],
        "decisions": len(decisions), "open_questions": len(questions),
        "report": report_lines(root, name, "created", autonomy, action, [(s, p) for p, s in regs], skipped,
                               docs, ignore_action),
    }, indent=1))
    return 0


def update(root, set_autonomy, regs, dry, decisions=(), questions=(), set_docs=None):
    date = dt.date.today().isoformat()
    state_path = os.path.join(root, "docs", "workbench", "state.md")
    if not os.path.isfile(state_path):
        return refuse("no docs/workbench/state.md to update; run with --apply first.")
    with open(state_path, encoding="utf-8") as f:
        state = f.read()
    changes = []
    agents_action = "unchanged"
    before = re.search(r"^- Checkpoints: *([a-z-]+)", state, re.M)
    docs_m = re.search(r"^- Docs in git: *([a-z]+)", state, re.M)
    docs = docs_m.group(1) if docs_m else UNDECIDED
    ignore_action = "untouched"
    if set_autonomy:
        new = re.sub(r"^- Checkpoints: .*$", f"- Checkpoints: {set_autonomy}", state, count=1, flags=re.M)
        if new != state:
            state, changes = new, changes + [f"autonomy -> {set_autonomy}"]
    if set_docs:
        if docs_m:
            new = re.sub(r"^- Docs in git: .*$", f"- Docs in git: {set_docs}", state, count=1, flags=re.M)
        else:
            new = re.sub(r"^(- Updated: .*)$", rf"\1\n- Docs in git: {set_docs}", state, count=1, flags=re.M)
        new = new.replace(f"- [ ] {DOCS_QUESTION}", f"- [x] {DOCS_QUESTION}")
        if new != state:
            state, changes = new, changes + [f"docs in git -> {set_docs}"]
            line = f"- {date}: Workbench folders under docs/ in git: {set_docs}. (user)"
            if "\n## Open questions" in state:
                state = state.replace("\n## Open questions", f"{line}\n\n## Open questions", 1)
        docs = set_docs
        ignore_action = apply_gitignore(root, docs, dry)
    if set_autonomy or set_docs:
        mode_now = re.search(r"^- Checkpoints: *([a-z-]+)", state, re.M)
        agents = os.path.join(root, "AGENTS.md")
        if os.path.isfile(agents) and mode_now:
            with open(agents, encoding="utf-8") as f:
                content, agents_action = upsert_section(f.read(), section_text(mode_now.group(1), docs))
            write(agents, content, dry)
            changes.append("AGENTS.md section refreshed")
    added = []
    for p, s in regs:
        if f"(at {p})" in state:
            continue
        marker = "## Decisions"
        state = state.replace(marker, row(s, p, date) + "\n" + marker, 1) if marker in state else state + row(s, p, date) + "\n"
        added.append({"slot": s, "at": p})
    for d in decisions:
        line = f"- {date}: {d} (user)"
        if line not in state:
            state = state.replace("\n## Open questions", f"{line}\n\n## Open questions", 1) if "\n## Open questions" in state else state + line + "\n"
            changes.append("decision added")
    for q in questions:
        line = f"- [ ] {q}"
        if line not in state:
            state = state.replace("\n## Approvals", f"{line}\n\n## Approvals", 1) if "\n## Approvals" in state else state + line + "\n"
            changes.append("open question added")
    if changes or added:
        state = re.sub(r"^- Updated: .*$", f"- Updated: {date}", state, count=1, flags=re.M)
        write(state_path, state, dry)
    m = re.search(r"^- Project: *(.+)$", state, re.M)
    mode = re.search(r"^- Checkpoints: *([a-z-]+)", state, re.M)
    mode_text = mode.group(1) if mode else "unknown"
    if before and mode and before.group(1) != mode.group(1):
        mode_text = f"{mode.group(1)}: the mode was switched from {before.group(1)} to {mode.group(1)}"
    print(json.dumps({"dry_run": dry, "action": "update", "changes": changes, "registered": added,
                      "unchanged": not (changes or added),
                      "report": report_lines(root, m.group(1).strip() if m else "unknown",
                                             "updated" if changes or added else "unchanged",
                                             mode_text, agents_action,
                                             registered_rows(state), detect(root)["not_registered"],
                                             docs if docs in LOCAL_FOLDERS else UNDECIDED,
                                             ignore_action)}, indent=1))
    return 0


NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._-]{0,79}")


def one_line(text):
    return " ".join(str(text).split())


def read_input(src):
    """(name, decisions, questions) from a JSON file or stdin; ValueError when it is not that shape."""
    try:
        raw = sys.stdin.read() if src == "-" else open(src, encoding="utf-8").read()
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError) as e:
        raise ValueError(f"--input {src!r} is not a readable JSON file: {e}") from None
    if not isinstance(data, dict) or set(data) - {"name", "decisions", "open_questions"}:
        raise ValueError('--input must be an object with only "name", "decisions" and "open_questions"')
    lists = [data.get(k, []) for k in ("decisions", "open_questions")]
    if not all(isinstance(v, list) and all(isinstance(t, str) for t in v) for v in lists):
        raise ValueError('"decisions" and "open_questions" must be lists of strings')
    name = data.get("name")
    if name is not None and not isinstance(name, str):
        raise ValueError('"name" must be a string')
    return (one_line(name) if name else None), [one_line(t) for t in lists[0] if t.strip()], \
        [one_line(t) for t in lists[1] if t.strip()]


def consume(input_src, dry, code):
    """Delete the scratch input file after a real run that succeeded; any other file name is left alone."""
    if code == 0 and not dry and input_src and os.path.basename(input_src) == INPUT_SCRATCH and os.path.isfile(input_src):
        os.remove(input_src)
    return code


def main(argv):
    if not argv:
        print(__doc__, file=sys.stderr)
        return 2
    if "--help" in argv or "-h" in argv:
        print(__doc__)
        return 0
    root, mode, name, autonomy, set_autonomy, regs, dry, docs = ".", None, None, None, None, [], False, None
    decisions, questions, input_src = [], [], None
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("--decision", "--open-question"):
            return usage_error(f"{a} was replaced by --input <file>: free text never goes on the command line.")
        if a in ("--root", "--name", "--autonomy", "--set-autonomy", "--register", "--input", "--docs"):
            if i + 1 >= len(argv):
                return usage_error(f"{a} needs a value.")
            v = argv[i + 1]
            if a == "--root":
                root = v
            elif a == "--name":
                if not NAME_RE.fullmatch(v):
                    return usage_error(f"--name {v!r} has characters other than letters, digits, spaces, '.', '_' "
                                       "or '-'; put it in --input.")
                name = v
            elif a == "--autonomy":
                autonomy = v
            elif a == "--set-autonomy":
                set_autonomy = v
            elif a == "--input":
                input_src = v
            elif a == "--docs":
                if v not in DOCS_CHOICES:
                    return usage_error(f"--docs must be one of {DOCS_CHOICES}, got {v!r}.")
                docs = v
            else:
                regs.append(v)
            i += 2
        elif a == "--detect":
            mode = "detect"
            i += 1
        elif a == "--apply":
            mode = "apply"
            i += 1
        elif a == "--dry-run":
            dry = True
            i += 1
        else:
            return usage_error(f"unknown option {a!r}.")
    if not os.path.isdir(root):
        return usage_error(f"--root {root!r} is not a directory.")
    if mode == "detect":
        print(json.dumps(detect(root), indent=2))
        return 0
    if input_src:
        try:
            in_name, decisions, questions = read_input(input_src)
        except ValueError as e:
            return usage_error(str(e))
        name = in_name or name
    try:
        parsed = parse_registrations(regs, root)
    except (ValueError, FileNotFoundError) as e:
        return refuse(str(e))
    if mode == "apply":
        if not name or not autonomy:
            return usage_error("--apply requires a name (--name, or \"name\" in --input) and --autonomy.")
        if autonomy not in MODES:
            return usage_error(f"--autonomy must be one of {MODES}.")
        return consume(input_src, dry, apply(root, name, autonomy, parsed, dry, decisions, questions,
                                             docs or UNDECIDED))
    if set_autonomy and set_autonomy not in MODES:
        return usage_error(f"--set-autonomy must be one of {MODES}.")
    if not set_autonomy and not parsed and not decisions and not questions and not docs:
        return usage_error("nothing to do: pass --detect, --apply, --set-autonomy, --docs, --register or --input.")
    return consume(input_src, dry, update(root, set_autonomy, parsed, dry, decisions, questions, docs))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
