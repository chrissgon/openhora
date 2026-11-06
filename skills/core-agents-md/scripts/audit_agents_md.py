#!/usr/bin/env python3
"""Detect a project's tooling facts and audit an AGENTS.md against them.

Usage:
  python3 audit_agents_md.py --root <dir> --detect
  python3 audit_agents_md.py --root <dir> --audit <path-to-AGENTS.md> [--fix] [--baseline <path>]

--detect  prints JSON: manifests and scripts, Makefile targets, lint/format/type configs, test
          frameworks and folders, CI and deploy files, root documents, instruction-like files,
          the existing AGENTS.md sections plus whether it has the workbench section, and two
          ready lists: "commands" (the install command from the lockfile and one line per package
          script or Makefile target, each with its source) and "tools" (each tool named by a
          config file, with that file).
--audit   checks every backticked command against package scripts, Makefile targets and
          binaries (PATH or node_modules/.bin), and every backticked path against the filesystem.
          For each problem it prints "suggestions": the existing scripts or paths that could
          replace it. It also reports whether the workbench section is byte-identical to the
          baseline: the file given with --baseline <path> (a copy of the previous AGENTS.md),
          or, without that option, the version of the file in the last git commit when there is
          one ("baseline" in the output says which). Exit 1 when the audit finds problems.
          The workbench section (between <!-- workbench:start --> and <!-- workbench:end -->) belongs
          to core-project-init: it is left out of the check, and what the check would flag inside it
          is listed under "in_workbench_section", never fixed and never counted against "ok".
          It also prints "carried_over": the lines of AGENTS.md (outside the workbench section) that the
          baseline lacks and that equal a non-heading line of an instruction-like file once bullet
          markers, backticks and closing punctuation are ignored. Reported only, not counted in "ok";
          with no baseline every matching line is listed.
--fix     with --audit: first replaces, outside the workbench section, every unknown command and
          missing path that has exactly one suggestion, touching nothing else, prints them under
          "fixed", then audits the result. A problem with no suggestion or several is left for a
          person. The workbench section is never edited.

Exit codes: 0 ok, 1 audit problems, 2 usage error (on stderr).
"""
import difflib
import hashlib
import json
import os
import re
import subprocess
import sys

MANIFESTS = ("package.json", "pyproject.toml", "go.mod", "Cargo.toml", "composer.json", "Gemfile", "Makefile")
CONFIG_PATTERNS = {
    "lint": (r"^\.?eslint", r"^\.oxlintrc", r"^biome\.json", r"^ruff\.toml", r"^\.golangci", r"^\.rubocop", r"^\.stylelintrc"),
    "format": (r"^\.prettierrc", r"^\.oxfmtrc", r"^\.editorconfig", r"^rustfmt\.toml"),
    "types": (r"^tsconfig", r"^mypy\.ini", r"^pyrightconfig"),
    "tests": (r"^vitest\.config", r"^jest\.config", r"^playwright\.config", r"^pytest\.ini", r"^cypress\.config", r"^karma\.conf"),
    "commits": (r"^commitlint", r"^\.commitlintrc", r"^\.husky$", r"^lefthook", r"^\.pre-commit-config"),
    "ci_deploy": (r"^\.github$", r"^\.gitlab-ci\.yml", r"^netlify\.toml", r"^vercel\.json", r"^Dockerfile", r"^docker-compose", r"^fly\.toml", r"^render\.yaml"),
}
TEST_DIRS = ("test", "tests", "__tests__", "e2e", "spec", "cypress")
EXCLUDED_STEMS = {"README", "LICENSE", "CHANGELOG", "CONTRIBUTING", "CODE_OF_CONDUCT", "SECURITY", "AGENTS"}
INSTRUCTION_HEADINGS = ("always", "never", "rules", "hard rules", "communication", "do", "don't", "workflow")
RUN_PREFIX = {"bun install": "bun run", "pnpm install": "pnpm run", "yarn install": "yarn run", "npm ci": "npm run"}
TOOL_NAMES = ((r"^\.?eslint", "ESLint"), (r"^\.oxlintrc", "Oxlint"), (r"^biome\.json", "Biome"), (r"^ruff\.toml", "Ruff"),
              (r"^\.golangci", "golangci-lint"), (r"^\.rubocop", "RuboCop"), (r"^\.stylelintrc", "Stylelint"),
              (r"^\.prettierrc", "Prettier"), (r"^\.editorconfig", "EditorConfig"), (r"^rustfmt\.toml", "rustfmt"),
              (r"^tsconfig", "TypeScript"), (r"^mypy\.ini", "mypy"), (r"^pyrightconfig", "Pyright"),
              (r"^vitest\.config", "Vitest"), (r"^jest\.config", "Jest"), (r"^playwright\.config", "Playwright"),
              (r"^pytest\.ini", "pytest"), (r"^cypress\.config", "Cypress"), (r"^karma\.conf", "Karma"),
              (r"^commitlint|^\.commitlintrc", "commitlint"), (r"^\.husky$", "Husky"), (r"^lefthook", "Lefthook"),
              (r"^\.pre-commit-config", "pre-commit"))
SKIP_DIRS = {"node_modules", "dist", "build", "target", "vendor", "__pycache__"}
START, END = "<!-- workbench:start -->", "<!-- workbench:end -->"


def looks_like_instructions(path):
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


def package_scripts(root):
    p = os.path.join(root, "package.json")
    if not os.path.isfile(p):
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return {"name": data.get("name"), "description": data.get("description"), "scripts": data.get("scripts") or {},
            "packageManager": data.get("packageManager")}


def makefile_targets(root):
    p = os.path.join(root, "Makefile")
    if not os.path.isfile(p):
        return []
    with open(p, encoding="utf-8", errors="ignore") as f:
        return sorted({m.group(1) for m in re.finditer(r"^([A-Za-z0-9_.-]+):", f.read(), re.M)})


def lockfile(root):
    for fn, cmd in (("bun.lock", "bun install"), ("bun.lockb", "bun install"), ("pnpm-lock.yaml", "pnpm install"),
                    ("yarn.lock", "yarn install"), ("package-lock.json", "npm ci"), ("poetry.lock", "poetry install"),
                    ("uv.lock", "uv sync"), ("Cargo.lock", "cargo build"), ("go.sum", "go mod download")):
        if os.path.isfile(os.path.join(root, fn)):
            return {"file": fn, "install": cmd}
    return None


def detect(root):
    entries = sorted(os.listdir(root))
    configs = {k: [] for k in CONFIG_PATTERNS}
    for e in entries:
        for kind, pats in CONFIG_PATTERNS.items():
            if any(re.search(p, e) for p in pats):
                configs[kind].append(e)
    ci_files = []
    wf = os.path.join(root, ".github", "workflows")
    if os.path.isdir(wf):
        ci_files = [os.path.join(".github/workflows", f) for f in sorted(os.listdir(wf)) if f.endswith((".yml", ".yaml"))]
    root_docs, instruction_like = [], []
    for e in entries:
        if e.lower().endswith(".md") and os.path.isfile(os.path.join(root, e)):
            stem = e[:-3]
            if stem.upper() in EXCLUDED_STEMS or stem.upper().startswith("README"):
                continue
            if stem == stem.upper():
                (instruction_like if looks_like_instructions(os.path.join(root, e)) else root_docs).append(e)
    agents = os.path.join(root, "AGENTS.md")
    agents_info = {"exists": False, "sections": [], "has_workbench_section": False, "workbench_sha256": None, "lines": 0}
    if os.path.isfile(agents):
        with open(agents, encoding="utf-8") as f:
            text = f.read()
        agents_info = {"exists": True, "sections": re.findall(r"^## (.+)$", text, re.M),
                       "has_workbench_section": START in text and END in text,
                       "workbench_sha256": section_sha(text), "lines": text.count("\n") + 1}
    lock, pkg = lockfile(root), package_scripts(root)
    commands = []
    if lock:
        commands.append({"task": "install", "command": lock["install"], "source": lock["file"]})
    prefix = RUN_PREFIX.get(lock["install"] if lock else "", "npm run")
    for name, body in (pkg.get("scripts") or {}).items():
        commands.append({"task": name, "command": f"{prefix} {name}", "runs": body, "source": f"package.json scripts.{name}"})
    for t in makefile_targets(root):
        commands.append({"task": t, "command": f"make {t}", "source": f"Makefile target {t}"})
    tools = []
    for e in entries:
        for pat, tool in TOOL_NAMES:
            if re.search(pat, e):
                tools.append({"name": tool, "source": e})
    return {
        "commands": commands,
        "tools": tools,
        "root": os.path.abspath(root),
        "manifests": [m for m in MANIFESTS if os.path.isfile(os.path.join(root, m))],
        "package": package_scripts(root),
        "makefile_targets": makefile_targets(root),
        "lockfile": lockfile(root),
        "configs": configs,
        "ci_workflows": ci_files,
        "test_dirs": [d for d in TEST_DIRS if os.path.isdir(os.path.join(root, d))],
        "root_docs": root_docs,
        "instruction_like": instruction_like,
        "agents_md": agents_info,
    }


def known_binaries(root):
    bins = set()
    nb = os.path.join(root, "node_modules", ".bin")
    if os.path.isdir(nb):
        bins.update(os.listdir(nb))
    for d in os.environ.get("PATH", "").split(os.pathsep):
        if os.path.isdir(d):
            try:
                bins.update(os.listdir(d))
            except OSError:
                pass
    return bins


def section(text):
    """The workbench section, markers included, or None when the text has none."""
    return text[text.index(START): text.index(END) + len(END)] if START in text and END in text else None


def split_section(text):
    """(text before the workbench section, the section with its markers, text after it); the section is ''
    when the text has none."""
    if START in text and END in text and text.index(START) < text.index(END):
        a, b = text.index(START), text.index(END) + len(END)
        return text[:a], text[a:b], text[b:]
    return text, "", ""


def replace_outside(text, old, new):
    """Replace `old` with `new` everywhere except inside the workbench section."""
    before, block, after = split_section(text)
    return before.replace(old, new) + block + after.replace(old, new)


def section_sha(text):
    sec = section(text)
    return hashlib.sha256(sec.encode("utf-8")).hexdigest() if sec is not None else None


def committed_version(root, agents_path):
    """The file as it is in the last git commit, or None (no git, no commit, or the file is not in it)."""
    rel = os.path.relpath(os.path.abspath(agents_path), os.path.abspath(root))
    if rel.startswith(".."):
        return None
    try:
        r = subprocess.run(["git", "-C", root, "show", "HEAD:./" + rel.replace(os.sep, "/")],
                           capture_output=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    try:
        return r.stdout.decode("utf-8")
    except UnicodeDecodeError:
        return None


def project_files(root, depth=3):
    """Paths relative to root, down to `depth` folders, without hidden and dependency folders."""
    found = []
    base = os.path.abspath(root)
    for cur, dirs, files in os.walk(base):
        rel = os.path.relpath(cur, base)
        level = 0 if rel == "." else rel.count(os.sep) + 1
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in SKIP_DIRS) if level < depth else []
        for fn in sorted(files):
            found.append(fn if rel == "." else os.path.join(rel, fn).replace(os.sep, "/"))
    return found


def suggest_command(span, scripts, targets):
    """Existing commands that could replace an unknown one: same runner, a script or target with a close name."""
    parts = span.split()
    idx = 2 if len(parts) > 2 and parts[1] == "run" else 1
    if idx >= len(parts):
        return []
    pool = targets if parts[0] == "make" else scripts
    close = difflib.get_close_matches(parts[idx], sorted(pool), n=3, cutoff=0.8)
    return [" ".join(parts[:idx] + [c] + parts[idx + 1:]) for c in close]


def suggest_path(span, files):
    """Existing files that could replace a missing path: same extension, and one name starts with the other or is close to it."""
    anchor = "#" + span.split("#", 1)[1] if "#" in span else ""
    want = os.path.basename(span.split("#")[0].rstrip("/"))
    stem, ext = os.path.splitext(want.lower())
    if not stem:
        return []
    out = []
    for f in files:
        s, e = os.path.splitext(os.path.basename(f).lower())
        if e != ext:
            continue
        if s.startswith(stem) or stem.startswith(s) or difflib.SequenceMatcher(None, s, stem).ratio() >= 0.8:
            out.append(f + anchor)
    return out


def check(root, text):
    """Return (commands checked, unknown commands, missing paths) for the backticked spans of text."""
    scripts = set((package_scripts(root).get("scripts") or {}).keys())
    targets = set(makefile_targets(root))
    bins = known_binaries(root)
    unknown_commands, missing_paths, checked = [], [], 0
    for span in re.findall(r"`([^`\n]+)`", text):
        s = span.strip()
        parts = s.split()
        if not parts:
            continue
        first = parts[0]
        if first in ("npm", "bun", "pnpm", "yarn"):
            rest = parts[1:]
            if rest and rest[0] == "run":
                rest = rest[1:]
            if rest and rest[0] in ("install", "ci", "i", "add", "test", "x", "exec", "dlx", "create", "prepare"):
                checked += 1
                continue
            if rest:
                checked += 1
                if rest[0] not in scripts:
                    unknown_commands.append(s)
            continue
        if first == "make":
            checked += 1
            if len(parts) > 1 and parts[1] not in targets:
                unknown_commands.append(s)
            continue
        if first in ("python", "python3", "node", "go", "cargo", "uv", "poetry", "docker", "git", "bash", "sh", "npx"):
            checked += 1
            continue
        if re.match(r"^[A-Za-z0-9_.-]+$", first) and len(parts) > 1 and first in bins:
            checked += 1
            continue
        if any(ch in s for ch in "<>{}*") or " " in s:
            continue  # placeholders and globs are not paths
        if ("/" in s or s.endswith((".md", ".json", ".ts", ".js", ".yml", ".yaml", ".toml", ".css"))) and not s.startswith(("http", "-", "@", ".")):
            target = s.split("#")[0].rstrip("/")
            if target and not os.path.exists(os.path.join(root, target)):
                missing_paths.append(s)
    dedup = lambda items: list(dict.fromkeys(items))
    return checked, dedup(unknown_commands), dedup(missing_paths)


def suggestions_for(root, unknown_commands, missing_paths):
    scripts = set((package_scripts(root).get("scripts") or {}).keys())
    targets = set(makefile_targets(root))
    files = project_files(root) if missing_paths else []
    out = {c: suggest_command(c, scripts, targets) for c in unknown_commands}
    out.update({p: suggest_path(p, files) for p in missing_paths})
    return out


BULLET_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")


def bare_line(line):
    """The line without its bullet marker or numbering, stripped."""
    return BULLET_RE.sub("", line).strip()


def normalise_line(line):
    """Bullet marker, backticks and closing punctuation removed, lowercase, whitespace collapsed."""
    t = bare_line(line).replace("`", "").lower()
    return " ".join(t.rstrip(".,;:!?").split())


def carried_over(root, new_text, old_text):
    """Lines of the new AGENTS.md (workbench section left out) that the baseline lacks and whose normalised
    text equals a non-heading line of an instruction-like file. Reported only."""
    seen = {normalise_line(l) for l in (old_text or "").splitlines()}
    before, _, after = split_section(new_text)
    found = []
    for name in detect(root)["instruction_like"]:
        try:
            with open(os.path.join(root, name), encoding="utf-8", errors="ignore") as f:
                source = {normalise_line(l): l for l in f.read().splitlines()
                          if l.strip() and not l.lstrip().startswith("#")}
        except OSError:
            continue
        for line in (before + "\n" + after).splitlines():
            n = normalise_line(line)
            if (line.strip() and not line.lstrip().startswith("#") and re.search(r"\w", n)
                    and n in source and n not in seen):
                item = {"line": bare_line(line), "from": name}
                if item not in found:
                    found.append(item)
    return found


def audit(root, agents_path, baseline, fix=False):
    with open(agents_path, encoding="utf-8") as f:
        text = f.read()
    committed = None if baseline else committed_version(root, agents_path)
    fixed = []
    if fix:
        before, _, after = split_section(text)
        _, unknown, missing = check(root, before + "\n" + after)
        for old, candidates in suggestions_for(root, unknown, missing).items():
            if len(candidates) == 1:
                text = replace_outside(text, f"`{old}`", f"`{candidates[0]}`")
                fixed.append({"from": old, "to": candidates[0],
                              "why": "the only existing path with a matching name" if old in missing
                              else "the only package script or Makefile target with a close name"})
        if fixed:
            with open(agents_path, "w", encoding="utf-8") as f:
                f.write(text)
    before, block, after = split_section(text)
    checked, unknown_commands, missing_paths = check(root, before + "\n" + after)
    _, block_commands, block_paths = check(root, block)
    in_section = [{"kind": "command", "span": c} for c in block_commands] + \
        [{"kind": "path", "span": p} for p in block_paths]
    section_state, source, old_text = "not checked", "none", None
    if baseline:
        with open(baseline, encoding="utf-8") as f:
            old_text = f.read()
        source = baseline
    elif committed is not None:
        old_text, source = committed, "last git commit"
    if source != "none":
        a, b = section(old_text), section(text)
        section_state = "unchanged" if a == b else ("missing" if b is None else "CHANGED")
        if a is None and b is None:
            section_state = "none in the file"
    ok = not unknown_commands and not missing_paths and section_state not in ("CHANGED", "missing")
    result = {"ok": ok, "commands_checked": checked, "unknown_commands": unknown_commands,
              "missing_paths": missing_paths,
              "suggestions": suggestions_for(root, unknown_commands, missing_paths),
              "fixed": fixed, "carried_over": carried_over(root, text, old_text),
              "workbench_section": section_state, "baseline": source,
              "in_workbench_section": {"owner": "core-project-init", "not_fixed": in_section},
              "workbench_sha256": section_sha(text), "lines": text.count("\n") + 1}
    print(json.dumps(result, indent=2))
    return 0 if ok else 1


def main(argv):
    if not argv:
        print(__doc__, file=sys.stderr)
        return 2
    if "--help" in argv or "-h" in argv:
        print(__doc__)
        return 0
    root, mode, target, baseline, fix = ".", None, None, None, False
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("--root", "--audit", "--baseline") and (i + 1 >= len(argv) or argv[i + 1].startswith("--")):
            print(f"Error: {a} needs a value. See --help.", file=sys.stderr)
            return 2
        if a == "--root":
            root = argv[i + 1]
            i += 2
        elif a == "--detect":
            mode = "detect"
            i += 1
        elif a == "--audit":
            mode, target = "audit", argv[i + 1]
            i += 2
        elif a == "--fix":
            fix = True
            i += 1
        elif a == "--baseline":
            baseline = argv[i + 1]
            i += 2
        else:
            print(f"Error: unknown option {a!r}. See --help.", file=sys.stderr)
            return 2
    if fix and mode != "audit":
        print("Error: --fix needs --audit <file>.", file=sys.stderr)
        return 2
    if not os.path.isdir(root):
        print(f"Error: --root {root!r} is not a directory.", file=sys.stderr)
        return 2
    if mode == "detect":
        print(json.dumps(detect(root), indent=2))
        return 0
    if mode == "audit":
        if not target or not os.path.isfile(target):
            print("Error: --audit needs the path to an existing AGENTS.md.", file=sys.stderr)
            return 2
        if baseline and not os.path.isfile(baseline):
            print(f"Error: --baseline {baseline!r} not found.", file=sys.stderr)
            return 2
        return audit(root, target, baseline, fix)
    print("Error: pass --detect or --audit <file>. See --help.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
