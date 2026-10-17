#!/usr/bin/env python3
"""Bring a skill from outside the repository, check it, test it, and show what the result means (package IMPORT-CLI).

Usage:
  python3 scripts/skill_import.py fetch --from <local path | https git URL> [--path <subfolder>] [--ref <branch or tag>] [--yes] [--home <dir>]
  python3 scripts/skill_import.py normalize --name <area-prefix>-<name> [--quarantine <folder>] [--area <area>]
                                  [--declare key=value]... [--drop <path>]... [--home <dir>]
  python3 scripts/skill_import.py check --name <name> [--jobs 4] [--home <dir>]
  python3 scripts/skill_import.py audit --name <name> --record <vetting record file> [--home <dir>]
  python3 scripts/skill_import.py cases-template --name <name> [--home <dir>]
  python3 scripts/skill_import.py test --name <name> [--model <id>]... --max-cost-usd <amount> [--jobs 4] [--allow-web-cases] [--yes] [--home <dir>]
  python3 scripts/skill_import.py status [--name <name>] [--home <dir>]
  python3 scripts/skill_import.py refresh --name <name> [--declare key=value]... [--yes] [--apply] [--home <dir>]
  python3 scripts/skill_import.py bump --name <name> [--class x|y|z] [--home <dir>]

A skill from outside is text written to instruct a model, by someone the workbench has not read. This tool puts one where the
lab can test it, checks it the workbench's way, and refuses to go on where a decision is the person's. It never installs the
skill into a harness's skills folder and never executes, imports or runs a file of it, its scripts and their tests included:
its files are read, copied and hashed, and a model runs them only inside the eval container, as a model in a run does.

Where it lives. <home>/<name>/ is a skill folder (SKILL.md, references/, assets/, scripts/) and <home>/<name>/evals/ is the
person's: evals.json (their cases), files/ (their fixtures), versions.jsonl (written here), import/ (the import record and the
review files below). evals/ is outside the content hash and is stripped from every staged copy, so no model reads it. The
home is <XDG data home>/openhora/skills by default (the local evidence base is beside it), WB_IMPORT_HOME names another, and
--home <dir> names one for a call, for example a project's git-ignored <project>/.workbench-local/skills. It is refused when it
is inside the workbench checkout (by device and inode) or when its path holds the skills folder of any adapter
(adapters/*/eval.json "skills_dir", read at run time, never named here), so an import is never installed by accident. The skill's
name has an area prefix, is not the name of a folder of skills/ and is the folder's name. The tests of a skill from outside are
local evidence, under <local evidence base>/imported/<name>/.

State is computed, never stored as a word. Each step looks at the folder and its record: fetched (a quarantine folder),
normalized (the folder and evals/import/record.json), checked (evals/import/check.json names the folder's current content
hash and said ok), audited (evals/import/audit.json holds a verdict that is not "do not install" at the folder's current content
hash), cases (evals/evals.json with no "<fill:" left and an origin line for every case), tested (a local evidence file).

Every verb prints one JSON object to stdout and diagnostics to stderr, takes flags only (no prompt), and exits 0 (done), 1 (not
done: the object says why), 2 (usage) or 3 (a stop: {"stopped": "<why>", "questions": [{"key", "question", "recommended",
"why"}]}, nothing written before the answer; a "go" or "proceed" is not an answer).

Verbs.
  fetch      Copies a source into a fresh quarantine folder under <home>/.quarantine/, and runs nothing in it. A local path is
             copied file by file; a symbolic link, a device, a pipe, a socket or a hard-linked file is refused and listed (staging
             would copy the content a link points at into a run), and so is a source over 2,000 files or 20 MB (the caps are
             these two numbers). A https git URL (no user, no password; ssh, file and ext are refused) is a download of text
             written to instruct a model, so without --yes only the plan is printed and the call stops; with --yes it clones at
             depth 1 with no hooks, no submodules, no tags, no credential helper, a throwaway HOME and no system or global git
             configuration (nothing of your environment reaches it, a proxy setting included), refuses the entries it lists as
             links, and drops .git/. A folder that holds several skills lists
             the candidates and stops (one import per skill: --path). Private repositories: clone them yourself and give the path.
             Records the origin: its kind, location, commit, subpath, date and the sha256 of the tree.
  normalize  Builds <home>/<name>/ from the quarantine, by shape only: an Agent Skills folder (SKILL.md with name and description
             frontmatter) or one Markdown file (with or without frontmatter, wrapped as SKILL.md). A flow, an agent file and a
             body that hands work to other skills by name are refused. The body is never rewritten: only the frontmatter is. The
             name is yours (--name); description and license are kept verbatim; the standard's keys the workbench refuses at the
             top level (compatibility, allowed-tools) and the foreign metadata go to the record, and tool limits are not enforced
             by the workbench (the container is the boundary). The area follows the name's prefix. requires and side_effects must
             be answered (--declare requires=none, --declare side_effects=none) before any test; inputs, outputs and updates may
             be left, and are then written [] and listed as assumed. A file a harness reads as settings or instructions (the
             "settings" names of adapters/*/eval.json) stops the import and is listed; --drop <path> leaves it out, recorded. The
             origin's own evals/ is never imported: the cases are yours. Writes evals/versions.jsonl (0.1.0, class "new").
  check      Runs four independent jobs at once (--jobs), each written under evals/import/: the scan of the folder
             (scan.json: scripts/security_scan.py on a copy laid out as skills/<name>, so its rules for a skill apply; a finding
             the skill silenced with its own allow comment is still a finding), the component list (components.json), the
             validator's per-skill checks (foreign-check.json: scripts/validate.py --foreign) and, once cases exist, the runner's
             preflight (check-cases.json). A scan error stops. The effect stop: a remote write while side_effects is [], or a
             non-empty side_effects with no "## Confirmation gate" section, stops the import; the skill is testable only after the
             effect is declared and the gate written (templates/capability.SKILL.md has the section), and every declared effect
             needs a case assertion tagged guard:<effect>. The rule of the scan that checks the workbench's own sentence for
             skills that read external content (untrusted-content) is reported under "conventions" and stops nothing: it is a rule
             for those who write skills of the repository, and the whole skill is read as external content here anyway.
  audit      The model reading is skills/core-security-audit in vetting mode, which you run in your own tool on <home>/<name>
             (the scan and component files are already in evals/import/). This copies the record to
             evals/import/vetting-<date>.md, reads its "Verdict:" line and stores verdict, record sha256 and the content hash at
             acceptance in evals/import/audit.json. A record inside the workbench checkout is copied and you are told to delete the
             original (it is never committed). Any later change of the content hash voids the audit. No test runs before an audit
             whose verdict is not "do not install"; a web case needs the verdict "install".
  cases-template  Writes evals/evals.json (never over one that exists) with two cases to fill, each part marked "<fill: ...>",
             and evals/import/cases-origin.json, one line per case saying which real request it came from. It asks for your own
             material only: a request you actually made, the files it used (copy them into evals/files/), what a good answer holds
             and what must not happen. It never writes a prompt or an assertion. check refuses a "<fill:" left anywhere and a case
             with no origin line. The rules of evals/README.md hold: at least two cases, at least one assertion that is not a guard,
             a guard when the skill has stop rules, a gate or reads external content, guard:<effect> per declared effect, no
             language, conditional or command assertion.
  test       Needs the steps above. Prints the plan of eval_run.py --skill-dir <folder> --quick (runs, models, the evidence home)
             and an upper bound of what it can spend (runs x --max-cost-usd for the model runs, plus one grading call per run on the
             gate file's grader, on your own key, taken at the same amount; a failed guard verdict is graded once more), and
             stops; with --yes it runs one quick event for all the models (--model, repeated; the gate file's lab models without
             it). --pass-env and --harness are refused. A web case (allow_web) is refused unless the audit verdict is "install"
             and --allow-web-cases is given: on the open network a hostile skill could send your fixtures anywhere. Your
             fixtures reach the model provider and the grader, as in any lab run.
  status     Per skill: the computed step, the audit verdict and whether it is current, the assumed keys, the origin, and for each
             model the figures of eval_status.py status --skill-dir. A quick test alone is "preliminary: quick test only"; the
             band is measured against your own cases, which nobody else has read, and counts on your machine only.
  refresh    Fetches the recorded origin again into a new quarantine, builds the folder as it would be now, and shows the
             difference and its class (eval_status.change_class). It stops for your answer; with --apply it replaces the files,
             raises the version by that class, appends one line to evals/versions.jsonl and voids the audit by changing the hash
             (the audit file stays, and says it is void). --declare answers a key again.
  bump       Records an edit you made by hand (the effect stop asks you to edit SKILL.md): the class of the change against the
             last record, the version raised by it, one line appended to evals/versions.jsonl. The bump of eval_status.py is based
             on the checkout's version control and is not used for an imported skill.

Standard library only (Python 3.9). A skill from outside never becomes a skill of the repository by this tool: that is "Adding a
skill" in a pull request, with the cases rewritten under fictional names (AGENTS.md, principle 8). Local evidence never travels.
"""
import argparse
import datetime
import difflib
import hashlib
import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CAP_FILES = 2000
CAP_BYTES = 20 * 1024 * 1024
WALK_LIMIT = 50000  # entries looked at while listing the candidates of a folder that holds several skills
SOURCE_SKIP = (".git", ".hg", ".svn")  # version control of a source: never copied
DEPTH = 4  # how deep a folder is searched for the skills it holds

IMPORT_REL = "evals/import"
RECORD, SNAPSHOT, CHECK, AUDIT, CASES_ORIGIN = ("record.json", "snapshot.json", "check.json", "audit.json", "cases-origin.json")
SCAN, COMPONENTS, FOREIGN, CASES_CHECK = ("scan.json", "components.json", "foreign-check.json", "check-cases.json")
DECLARABLE = ("description", "license", "requires", "side_effects", "inputs", "outputs", "updates")
MUST_ANSWER = ("requires", "side_effects")
MAY_ASSUME = ("inputs", "outputs", "updates")
CONVENTION_RULES = ("untrusted-content",)  # rules of the scan for the authors of skills of the repository: reported, never a stop
VERDICTS = ("do not install", "install after changes", "install")
VERDICT_RE = re.compile(r"^[\s>*_#-]*\**Verdict\**\s*[:\-]\s*\**\s*(do not install|install after changes|install)\b(.*)$", re.I | re.M)
FILL = "<fill:"
LIST_PATH_RE = re.compile(r"^[A-Za-z0-9._/<>-]+$")
REQUIRES_RE = re.compile(r"^[a-z0-9]+:[A-Za-z0-9<>._-]+$")
NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/@-]*$")
SKILL_REF_RES = (
    re.compile(r"(?i)\b(?:invoke|run|call|use|execute)\s+the\s+`([a-z0-9]+(?:-[a-z0-9]+)+)`\s+skill\b"),
    re.compile(r"(?i)\b(?:invoke|run|call|use|execute)\s+the\s+skill\s+`([a-z0-9]+(?:-[a-z0-9]+)+)`"),
    re.compile(r"(?i)\bhand\s+(?:it|the\s+request|the\s+task)\s+over\s+to\s+`([a-z0-9]+(?:-[a-z0-9]+)+)`"),
)
LANGUAGE_RE = re.compile(r"(?i)\b(?:written in english|is in english|in the user'?s language|reply is in)\b")


# --- the outcome of a verb ------------------------------------------------------------------------------------------

class Stop(Exception):
    """A decision that is the person's: exit 3 with {"stopped", "questions"}; nothing was written before the answer."""

    def __init__(self, why, questions=(), **extra):
        super().__init__(why)
        self.why, self.questions, self.extra = why, list(questions), extra


class Refused(Exception):
    """A step that cannot be done: exit 1 with {"refused": why, ...}."""

    def __init__(self, why, **extra):
        super().__init__(why)
        self.why, self.extra = why, extra


def ask(key, question, recommended, why):
    return {"key": key, "question": question, "recommended": recommended, "why": why}


def say(message):
    print(message, file=sys.stderr)


# --- the workbench's own modules, loaded by path (never a file of the skill) ----------------------------------------

_MODULES = {}


def load_module(rel, name):
    path = os.path.join(ROOT, *rel.split("/"))
    if path not in _MODULES:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        _MODULES[path] = module
    return _MODULES[path]


def status_module():
    return load_module("evals/eval_status.py", "skill_import_eval_status")


def validate_module():
    return load_module("scripts/validate.py", "skill_import_validate")


def run_command(argv, cwd=None, env=None, timeout=900):
    """One subprocess of the workbench's own scripts or of git, with an argument list and the output captured."""
    return subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)


def run_streaming(argv, timeout):
    """A subprocess whose stderr is the person's own terminal (progress while it runs) and whose stdout is captured."""
    return subprocess.run(argv, stdout=subprocess.PIPE, stderr=None, text=True, timeout=timeout)


def today():
    return datetime.date.today().isoformat()


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


# --- the home --------------------------------------------------------------------------------------------------------

def adapter_data():
    """({skills_dir of each adapter}, {names of settings of each adapter}) read from adapters/*/eval.json: which folder a
    harness discovers skills in, and which names carry its settings. Read at run time; no harness is named here."""
    skills_dirs, settings = set(), set()
    base = os.path.join(ROOT, "adapters")
    for name in sorted(os.listdir(base)) if os.path.isdir(base) else []:
        data = read_json(os.path.join(base, name, "eval.json"), {})
        if isinstance(data.get("skills_dir"), str) and data["skills_dir"].strip("/"):
            skills_dirs.add(data["skills_dir"].strip("/"))
        settings.update(s for s in data.get("settings") or [] if isinstance(s, str) and s)
    return skills_dirs, settings


def home_problem(home):
    """Why `home` cannot hold skills from outside, or None: inside the checkout, or under a folder a harness discovers skills in."""
    if status_module().inside_checkout(home, ROOT):
        return (f"{home} is inside the workbench checkout {ROOT}: a skill from outside never lives in the shared repository "
                "(its home is outside it, by device and inode)")
    parts = os.path.realpath(home).split(os.sep)
    for skills_dir in sorted(adapter_data()[0]):
        want = skills_dir.split("/")
        if any(parts[i:i + len(want)] == want for i in range(len(parts))):
            return (f"{home} holds the folder {skills_dir}, where a harness discovers skills: an imported skill would be "
                    "installed by accident, and the workbench never installs one")
    return None


def resolve_home(arg):
    """The home folder: --home, else WB_IMPORT_HOME, else <XDG data home>/openhora/skills. Refused when home_problem says so."""
    explicit = arg or os.environ.get("WB_IMPORT_HOME", "").strip()
    if explicit:
        home = os.path.abspath(os.path.expanduser(explicit))
    else:
        data = os.environ.get("XDG_DATA_HOME", "").strip() or os.path.join(os.path.expanduser("~"), ".local", "share")
        home = os.path.join(os.path.abspath(data), "openhora", "skills")
    problem = home_problem(home)
    if problem:
        raise Refused(problem, home=home)
    return home


def ensure_home(home):
    for folder in (home, os.path.join(home, ".quarantine")):
        os.makedirs(folder, mode=0o700, exist_ok=True)
    return home


def quarantine_root(home):
    return os.path.join(home, ".quarantine")


def skill_folder(home, name):
    return os.path.join(home, name)


def import_dir(folder):
    return os.path.join(folder, *IMPORT_REL.split("/"))


# --- names -----------------------------------------------------------------------------------------------------------

def name_questions(name, area_flag):
    """([questions], prefix, area): why `name` cannot be the name of a skill from outside. Nothing is guessed: a name with no
    area prefix is asked, and the area is the prefix's."""
    v = validate_module()
    prefixes = v.PREFIX_TO_AREA
    questions = []
    if not NAME_RE.match(name or "") or len(name) > 64:
        questions.append(ask("name", f"{name!r} is not a skill name: 1 to 64 characters, lowercase letters, digits and single hyphens.",
                             "a name of that form", "the folder's name is the skill's name"))
        return questions, None, None
    prefix = name.split("-")[0]
    if prefix not in prefixes:
        area_prefix = next((p for p, a in sorted(prefixes.items()) if a == area_flag and p != "flow"), None)
        recommended = f"{area_prefix}-{name}" if area_prefix else "none: the area is yours to choose, nothing in the folder says it"
        questions.append(ask("name", f"{name!r} has no area prefix. Which area is the skill in? The prefixes are "
                             f"{', '.join(sorted(p for p in prefixes if p != 'flow'))}.", recommended,
                             "a skill from outside is named like the workbench's own: <area prefix>-<name>"))
        return questions, None, None
    if prefix == "flow":
        raise Refused("a flow is refused in this version: a flow hands work to other skills by name, and an imported skill has none "
                      "of its phases beside it")
    area = prefixes[prefix]
    if area_flag and area_flag != area:
        questions.append(ask("area", f"--area {area_flag} disagrees with the prefix {prefix}- of the name, whose area is {area}.",
                             f"drop --area, or use the name {next((p for p, a in sorted(prefixes.items()) if a == area_flag), '<prefix>')}-...",
                             "the area follows the prefix"))
    if os.path.isdir(os.path.join(ROOT, "skills", name)):
        questions.append(ask("name", f"{name} is the name of a skill of the repository (skills/{name}); an imported skill has a name of "
                             "its own, so that its evidence is never mistaken for that skill's.", f"{name}-imported",
                             "the lab keys evidence by name, and the folder skills/ is read by the battery"))
    return questions, prefix, area


# --- reading a tree safely --------------------------------------------------------------------------------------------

def scan_tree(root):
    """(files, refused, bytes) of the tree at `root`, read without following a link: files is [relative path], refused is
    [(relative path, why)] for a symbolic link, a device, a pipe, a socket or a hard-linked file. SOURCE_SKIP folders are left out."""
    files, refused, total = [], [], 0
    for dp, dns, fns in os.walk(root, followlinks=False):
        keep = []
        for d in sorted(dns):
            path = os.path.join(dp, d)
            rel = os.path.relpath(path, root).replace(os.sep, "/")
            if os.path.islink(path):
                refused.append((rel, "a symbolic link"))
            elif d not in SOURCE_SKIP:
                keep.append(d)
        dns[:] = keep
        for fn in sorted(fns):
            path = os.path.join(dp, fn)
            rel = os.path.relpath(path, root).replace(os.sep, "/")
            mode = os.lstat(path)
            if stat.S_ISLNK(mode.st_mode):
                refused.append((rel, "a symbolic link"))
            elif not stat.S_ISREG(mode.st_mode):
                refused.append((rel, "not a regular file (a device, a pipe or a socket)"))
            elif mode.st_nlink > 1:
                refused.append((rel, "a hard-linked file"))
            else:
                files.append(rel)
                total += mode.st_size
    return files, refused, total


def copy_regular(src, dst):
    """Copy one regular file by descriptor: never through a link, and never a file that is not regular or is hard-linked.
    The mode is 0644, or 0755 when the source is executable."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(src, flags)
    except OSError as e:
        raise Refused(f"{src} cannot be opened as a plain file ({e.strerror}): a link is never followed")
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink > 1:
            raise Refused(f"{src} is not a plain file with one name: a link, a device or a hard-linked file is never copied")
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with os.fdopen(fd, "rb", closefd=False) as source, open(dst, "wb") as out:
            shutil.copyfileobj(source, out)
    finally:
        os.close(fd)
    os.chmod(dst, 0o755 if info.st_mode & 0o100 else 0o644)


def copy_tree(src_root, files, dst_root, skip=()):
    skip = tuple(s.rstrip("/") for s in skip)
    for rel in files:
        if any(rel == s or rel.startswith(s + "/") for s in skip):
            continue
        copy_regular(os.path.join(src_root, *rel.split("/")), os.path.join(dst_root, *rel.split("/")))


def tree_hash(root, files=None):
    """sha256 over every file of a tree: sorted relative paths and their bytes (all files, unlike a skill's content hash)."""
    h = hashlib.sha256()
    for rel in sorted(files if files is not None else scan_tree(root)[0]):
        with open(os.path.join(root, *rel.split("/")), "rb") as f:
            data = f.read()
        h.update(rel.encode("utf-8") + b"\0" + str(len(data)).encode() + b"\0" + data)
    return h.hexdigest()


def clean_subpath(value):
    if not value:
        return ""
    parts = [p for p in value.replace("\\", "/").split("/") if p not in ("", ".")]
    if os.path.isabs(value) or ".." in parts:
        raise Refused(f"--path {value!r} must be a relative path inside the source, without '..'")
    return "/".join(parts)


def find_candidates(base):
    """The folders under `base` (relative paths, "" for base itself) that hold a SKILL.md, looked for to DEPTH levels without
    following a link and without going into version control or a hidden folder."""
    found, seen = [], 0
    for dp, dns, fns in os.walk(base, followlinks=False):
        rel = os.path.relpath(dp, base).replace(os.sep, "/")
        depth = 0 if rel == "." else rel.count("/") + 1
        seen += len(dns) + len(fns)
        if seen > WALK_LIMIT:
            break
        if "SKILL.md" in fns and not os.path.islink(os.path.join(dp, "SKILL.md")):
            found.append("" if rel == "." else rel)
        dns[:] = sorted(d for d in dns if not d.startswith(".") and not os.path.islink(os.path.join(dp, d))) if depth < DEPTH else []
    return found


# --- git -------------------------------------------------------------------------------------------------------------

def parse_git_url(url):
    """The https URL of a repository, or Refused: https only, no user, no password, no ssh, file or ext, nothing that git could
    read as an option."""
    from urllib.parse import urlsplit
    if not isinstance(url, str) or not url or url != url.strip() or any(ord(c) < 33 or ord(c) == 127 for c in url) or url.startswith("-"):
        raise Refused("the URL is empty, has a space or a control character, or starts with '-'")
    if re.match(r"^[^/@:]+@[^/:]+:", url):
        raise Refused("an ssh address is refused: only https is fetched, and a private repository is cloned by you and given as a path")
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise Refused(f"the scheme {parts.scheme!r} is refused: only https is fetched (ssh, file, ext and git are not)")
    if "@" in parts.netloc or parts.username or parts.password:
        raise Refused("a URL with a user or a password is refused: no credential goes through this tool")
    if not parts.hostname or parts.query or parts.fragment:
        raise Refused("the URL needs a host and no query or fragment")
    return url


def git_plan(url, ref, dest, scratch_home):
    """The plan of a clone, built and not run: {"argv", "env", "ls_files", "rev_parse"}. Pure; the tests read it. The clone is shallow
    (depth 1), with no tag, no submodule, no hook, no symbolic link, no credential helper and only the https protocol, in an
    environment of its own: a throwaway HOME, no system or global configuration, no terminal prompt, no large-file download."""
    url = parse_git_url(url)
    if ref is not None and (not REF_RE.match(ref) or ref.endswith("/") or ".." in ref or re.fullmatch(r"[0-9a-f]{7,40}", ref)):
        raise Refused(f"--ref {ref!r} is a branch or a tag name; a commit cannot be cloned at depth 1")
    path = os.environ.get("PATH", "/usr/bin:/bin")
    env = {"PATH": path, "HOME": scratch_home, "LANG": "C", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
           "GIT_TERMINAL_PROMPT": "0", "GIT_LFS_SKIP_SMUDGE": "1", "GIT_ALLOW_PROTOCOL": "https"}
    safe = ["-c", "core.hooksPath=" + os.devnull, "-c", "core.symlinks=false", "-c", "credential.helper=",
            "-c", "protocol.allow=never", "-c", "protocol.https.allow=always"]
    argv = ["git"] + safe + ["clone", "--depth", "1", "--no-tags", "--no-recurse-submodules"] + (["--branch", ref] if ref else []) + ["--", url, dest]
    return {"argv": argv, "env": env, "ls_files": ["git"] + safe + ["-C", dest, "ls-files", "-s"],
            "rev_parse": ["git"] + safe + ["-C", dest, "rev-parse", "HEAD"]}


def clone_links(listing):
    """The paths a `git ls-files -s` listing gives as links (mode 120000), and as submodules (160000)."""
    bad = []
    for line in listing.splitlines():
        head, _, path = line.partition("\t")
        mode = head.split(" ")[0]
        if mode in ("120000", "160000"):
            bad.append((path, "a symbolic link" if mode == "120000" else "a submodule"))
    return bad


# --- fetch -----------------------------------------------------------------------------------------------------------

def new_quarantine(home):
    ensure_home(home)
    return tempfile.mkdtemp(prefix="q-", dir=quarantine_root(home))


def resolve_quarantine(home, given):
    root = quarantine_root(home)
    if given:
        folder = os.path.abspath(given)
        if os.path.realpath(os.path.dirname(folder)) != os.path.realpath(root) or not os.path.isfile(os.path.join(folder, "origin.json")):
            raise Refused(f"{folder} is not a quarantine folder of this home ({root})")
        return folder
    found = sorted(os.path.join(root, n) for n in os.listdir(root)
                   if os.path.isfile(os.path.join(root, n, "origin.json"))) if os.path.isdir(root) else []
    if len(found) == 1:
        return found[0]
    raise Stop("no quarantine was named" if not found else "more than one quarantine exists",
               [ask("quarantine", "Which quarantine folder do you mean?" if found else "Nothing was fetched; fetch a source first.",
                    found[-1] if found else "python3 scripts/skill_import.py fetch --from <path or https URL>",
                    "normalize reads one quarantine")], quarantines=found)


def acquire_local(source):
    """The absolute path of a local source. Refused when it is a symbolic link or does not exist."""
    path = os.path.abspath(os.path.expanduser(source))
    if os.path.islink(path):
        raise Refused(f"{path} is a symbolic link: give the path it points at")
    if not os.path.exists(path):
        raise Refused(f"{path} does not exist")
    return path


def refusal_stop(refused, files, total, where):
    reasons = []
    if refused:
        reasons.append(f"{len(refused)} entr{'y' if len(refused) == 1 else 'ies'} refused: " + "; ".join(f"{p} ({w})" for p, w in refused[:20]))
    if len(files) > CAP_FILES or total > CAP_BYTES:
        reasons.append(f"over the caps ({len(files)} files of at most {CAP_FILES}; {total} bytes of at most {CAP_BYTES})")
    if reasons:
        raise Stop(f"the source cannot be copied: {'. '.join(reasons)}",
                   [ask("source", f"Remove what is listed from {where}, or point --path at a smaller folder, and fetch again?",
                        "remove the entries from the source: a link is copied as the content it points at, and a hard link, a device "
                        "or a pipe is never copied", "staging copies a link's target into a run, so a link to a private file would reach one")],
                   refused=[{"path": p, "why": w} for p, w in refused], files=len(files), bytes=total)


def fetch(args):
    home = ensure_home(resolve_home(args.home))
    subpath = clean_subpath(args.path)
    source = args.src
    is_url = bool(re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", source)) or bool(re.match(r"^[^/@:]+@[^/:]+:", source))
    quarantine = None
    try:
        if is_url:
            url = parse_git_url(source)
            plan = git_plan(url, args.ref, os.path.join("<quarantine>", "raw"), "<a throwaway HOME>")
            shown = {"url": url, "ref": args.ref or "the default branch", "depth": 1, "destination": quarantine_root(home),
                     "argv": plan["argv"][:-1] + ["<quarantine>/raw"], "environment": sorted(plan["env"])}
            if not args.yes:
                raise Stop("a download of text written to instruct a model waits for an explicit yes",
                           [ask("download", f"Download {url} ({args.ref or 'its default branch'}, depth 1) into a quarantine folder under "
                                f"{quarantine_root(home)}? Nothing in it is run.", "yes: run the same command again with --yes",
                                "the files are text a model would follow; they are only copied and read here")], plan=shown)
            quarantine = new_quarantine(home)
            raw = os.path.join(quarantine, "raw")
            scratch_home = tempfile.mkdtemp(prefix="home-", dir=quarantine)
            plan = git_plan(url, args.ref, raw, scratch_home)
            say("git clone --depth 1 " + url)
            cloned = run_command(plan["argv"], env=plan["env"], timeout=900)
            if cloned.returncode != 0:
                raise Refused("the clone failed: " + (cloned.stderr.strip().splitlines() or ["no message"])[-1])
            listing = run_command(plan["ls_files"], env=plan["env"])
            commit = run_command(plan["rev_parse"], env=plan["env"]).stdout.strip() or None
            bad = clone_links(listing.stdout)
            shutil.rmtree(os.path.join(raw, ".git"), ignore_errors=True)
            if bad:
                raise Stop("the repository holds links", [ask("source", "Clone it yourself, remove the links and give the path?",
                                                          "yes", "a link is copied as the content it points at")],
                           refused=[{"path": p, "why": w} for p, w in bad])
            kind, location, base_root, single = "git", url, raw, None
        else:
            path = acquire_local(source)
            kind, location, commit = "local", path, None
            if os.path.isfile(path):
                if subpath:
                    raise Refused("--path goes with a folder")
                info = os.lstat(path)
                if info.st_nlink > 1 or not stat.S_ISREG(info.st_mode):
                    refusal_stop([(os.path.basename(path), "a hard-linked or special file")], [], 0, path)
                if info.st_size > CAP_BYTES:
                    refusal_stop([], [path], info.st_size, path)
                base_root, single = os.path.dirname(path), os.path.basename(path)
            else:
                base_root, single = path, None
        # --- what is the skill inside the source
        if single is not None:
            root, files, selected = base_root, [single], ""
        else:
            start = os.path.join(base_root, *subpath.split("/")) if subpath else base_root
            if not os.path.isdir(start):
                raise Refused(f"--path {subpath!r} is not a folder of the source")
            for i in range(len(subpath.split("/")) if subpath else 0):
                if os.path.islink(os.path.join(base_root, *subpath.split("/")[:i + 1])):
                    raise Refused(f"--path {subpath!r} goes through a symbolic link")
            candidates = find_candidates(start)
            if "" in candidates:
                selected = subpath
                root = start
            elif len(candidates) > 1:
                listed = [(subpath + "/" + c if subpath else c) for c in candidates]
                raise Stop("the source holds several skills: one import per skill",
                           [ask("path", "Which skill? Run fetch again with --path <folder>.", listed[0], "an import is one skill")],
                           candidates=listed)
            elif len(candidates) == 1:
                selected = subpath + "/" + candidates[0] if subpath else candidates[0]
                root = os.path.join(base_root, *selected.split("/"))
            else:
                raise Stop("no SKILL.md was found in the source",
                           [ask("source", "Is the skill a single Markdown file? Give that file as --from (with or without frontmatter).",
                                "the path of the .md file", "an Agent Skills folder has a SKILL.md; one file is wrapped as one")])
            files, refused, total = scan_tree(root)
            refusal_stop(refused, files, total, root)
        if single is not None:
            total = os.lstat(os.path.join(root, single)).st_size
        if quarantine is None:
            quarantine = new_quarantine(home)
        tree = os.path.join(quarantine, "tree")
        copy_tree(root, files, tree)
        origin = {"kind": kind, "location": location, "commit": commit, "subpath": selected if single is None else "",
                  "ref": args.ref if kind == "git" else None, "date": today(), "tree_sha256": tree_hash(tree)}
        if kind == "git":
            shutil.rmtree(os.path.join(quarantine, "raw"), ignore_errors=True)
        for leftover in os.listdir(quarantine):
            if leftover.startswith("home-"):
                shutil.rmtree(os.path.join(quarantine, leftover), ignore_errors=True)
        write_json(os.path.join(quarantine, "origin.json"), origin)
        return {"quarantine": quarantine, "origin": origin, "files": len(files), "bytes": total,
                "next": "python3 scripts/skill_import.py normalize --quarantine " + quarantine + " --name <area prefix>-<name> "
                        "--declare requires=none --declare side_effects=none"}
    except BaseException:
        if quarantine and not os.path.isfile(os.path.join(quarantine, "origin.json")):
            shutil.rmtree(quarantine, ignore_errors=True)
        raise


# --- reading the origin's SKILL.md -----------------------------------------------------------------------------------

def split_text(text):
    """(frontmatter text or None, the rest) of a SKILL.md text, as scripts/validate.py splits a file: the rest begins right after the
    closing fence, so it is kept byte for byte."""
    if not text.startswith("---\n"):
        return None, text
    end = text.find("\n---", 4)
    if end == -1:
        return None, text
    return text[4:end], text[end + 4:]


def read_origin(tree, files):
    """What the quarantine holds, by shape: {"shape", "md", "text", "fm", "fm_error", "body"}. Raises Stop when it is neither an Agent
    Skills folder nor one Markdown file."""
    v = validate_module()
    if "SKILL.md" in files:
        shape, md = "agent-skills-folder", "SKILL.md"
    else:
        docs = [f for f in files if "/" not in f and f.lower().endswith((".md", ".markdown"))]
        if len(files) == 1 and docs:
            shape, md = "single-markdown-file", docs[0]
        else:
            raise Stop("the quarantine holds neither a SKILL.md nor one Markdown file",
                       [ask("source", "Is this one skill? Fetch the folder that has its SKILL.md, or the single Markdown file.",
                            "fetch again with --path", "the import reads two shapes only")], files=files[:30])
    try:
        text = open(os.path.join(tree, md), "rb").read().decode("utf-8")
    except UnicodeDecodeError:
        raise Refused(f"{md} is not UTF-8 text")
    fm_text, body = split_text(text)
    fm, error = None, None
    if fm_text is not None:
        try:
            fm = v.load_yaml(fm_text)
        except Exception as e:  # noqa: BLE001 -- the workbench's reader is a subset of YAML; a skill that needs more is told so
            error = f"the frontmatter cannot be read by the workbench's reader (a subset of YAML: key: value, [a, b] lists, one nested map): {e}"
    return {"shape": shape, "md": md, "text": text, "fm": fm, "fm_error": error, "body": body}


def first_paragraph(body):
    for block in re.split(r"\n\s*\n", body.strip()):
        block = block.strip()
        if block and not block.startswith(("#", "```", "---")):
            return " ".join(block.split())
    return ""


def parse_list(value):
    value = (value or "").strip()
    if value.lower() in ("", "none", "[]"):
        return []
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1]
    return [v.strip().strip("\"'") for v in value.split(",") if v.strip()]


def parse_declares(items):
    found = {}
    for item in items or []:
        key, sep, value = item.partition("=")
        key = key.strip()
        if not sep or key not in DECLARABLE:
            raise ValueError(f"--declare {item!r}: use key=value with a key of {', '.join(DECLARABLE)}")
        found[key] = value
    return found


def yaml_scalar(value):
    if re.fullmatch(r"[A-Za-z0-9._+/-][A-Za-z0-9._+/ -]*", value) and not value.endswith(" "):
        return value
    return '"' + value + '"' if '"' not in value else "'" + value + "'" if "'" not in value else re.sub(r"[\"']", "", value)


def flow_list(values):
    return "[" + ", ".join(values) + "]"


def frontmatter_text(name, description, license_, area, answers, version):
    lines = ["---", f"name: {name}", "description: >", f"  {description}"]
    if license_:
        lines.append(f"license: {yaml_scalar(license_)}")
    lines += ["metadata:", f"  area: {area}", "  kind: capability"]
    lines += [f"  {key}: {flow_list(answers[key])}" for key in ("inputs", "outputs", "updates", "requires", "side_effects")]
    lines += [f'  version: "{version}"', "---"]
    return "\n".join(lines)


def settings_found(files, settings):
    return sorted(f for f in files if any(part in settings for part in f.split("/")))


def hands_work_over(body):
    """The skills a body names as ones it hands work to (invoke the `x` skill, hand the request over to `x`)."""
    return sorted({m for rx in SKILL_REF_RES for m in rx.findall(body)})


def plan_skill(origin_info, tree, files, name, area_flag, declares, drops, previous=None):
    """Everything normalize and refresh decide before a byte is written: (plan dict, [questions]). The plan holds the new SKILL.md
    text, the files to copy, what was dropped and what is recorded. Raises Refused for a flow or an agent file."""
    v = validate_module()
    questions, prefix, area = name_questions(name, area_flag)
    info, fm = origin_info, origin_info["fm"] or {}
    answers = dict((previous or {}).get("declared") or {})
    answers.update({k: parse_list(declares[k]) if k in ("requires", "side_effects", "inputs", "outputs", "updates") else declares[k]
                    for k in declares})
    meta = fm.get("metadata") if isinstance(fm.get("metadata"), dict) else {}
    if info["fm_error"]:
        questions.append(ask("frontmatter", info["fm_error"], "rewrite the frontmatter with plain key: value lines and fetch again",
                             "the workbench reads frontmatter with one reader on every machine"))
    # a flow, an agent file, a body that hands work over
    kind = meta.get("kind") or fm.get("kind")
    if kind == "flow" or (info["fm"] and str(fm.get("name", "")).startswith("flow-")):
        raise Refused("a flow is refused in this version: it orchestrates other skills by name, and none of them is here")
    if info["shape"] == "single-markdown-file" and info["fm"] and set(fm) & {"tools", "model", "skills"}:
        raise Refused("this is an agent file (it names tools, a model or skills), not a skill: agent files are refused in this version")
    handed = hands_work_over(info["body"])
    if len(handed) >= 2:
        raise Refused(f"the body hands work to other skills by name ({', '.join(handed)}): a flow, refused in this version")
    # settings and instructions of a harness
    _, settings = adapter_data()
    found = settings_found([f for f in files if not (f == "evals" or f.startswith("evals/"))], settings)  # the origin's evals/ is dropped whole
    drops = [d.strip("/") for d in drops]
    missing_drops = [d for d in drops if not any(f == d or f.startswith(d + "/") for f in files)]
    if missing_drops:
        raise Refused(f"--drop {', '.join(missing_drops)}: no such path in the quarantine")
    undropped = [f for f in found if not any(f == d or f.startswith(d + "/") for d in drops)]
    if undropped:
        questions.append(ask("drop", f"A harness would read {', '.join(undropped[:10])} as settings or instructions. Leave "
                             f"{'it' if len(undropped) == 1 else 'them'} out of the import?", "yes: " + " ".join(f"--drop {p}" for p in undropped[:10]),
                             "such a file would apply its rules, hooks or servers to every run"))
    # description and license
    kept_text = (previous or {}).get("declared_text") or {}
    description = declares.get("description") or kept_text.get("description") or (fm.get("description") if isinstance(fm.get("description"), str) else "")
    description = " ".join(str(description or "").split())
    if not description and not info["fm_error"]:
        paragraph = first_paragraph(info["body"])
        questions.append(ask("description", "The skill has no description. Use the file's first paragraph?",
                             f"--declare description=\"{paragraph}\"" if paragraph else "write one: what it does and when to use it",
                             "a description is what decides when a harness loads a skill"))
    elif len(description) > 1024:
        questions.append(ask("description", f"The description has {len(description)} characters; the limit is 1024.", "a shorter one with --declare description=...",
                             "every session loads every description"))
    license_ = declares.get("license") or kept_text.get("license") or (fm.get("license") if isinstance(fm.get("license"), str) else None)
    # the keys that decide credentials and effects
    side_effects = answers.get("side_effects")
    for key in MUST_ANSWER:
        if key not in answers:
            foreign = meta.get(key) if isinstance(meta.get(key), list) else None
            recommended = (f"--declare {key}={','.join(foreign)}" if foreign else f"--declare {key}=none")
            why = ("it decides which credentials a run needs; a class is <role>:<target>, for example integration:issue-tracker"
                   if key == "requires" else
                   f"it decides what the skill may do outside; one of {', '.join(v.SIDE_EFFECTS)}, and a skill that has any needs a "
                   "Confirmation gate section")
            questions.append(ask(key, f"Does the skill {'need an environment requirement' if key == 'requires' else 'act outside the project (publish, send, push, ...)'}?"
                                 " It must be answered before any test.", recommended + (" (the scan will say if a script writes to a remote)" if key == "side_effects" else ""), why))
    for key in MUST_ANSWER + MAY_ASSUME:
        if key in answers and not isinstance(answers[key], list):
            answers[key] = parse_list(answers[key])
    bad_effects = [e for e in answers.get("side_effects", []) if e not in v.SIDE_EFFECTS]
    if bad_effects:
        questions.append(ask("side_effects", f"{', '.join(bad_effects)} is not a side effect the workbench knows ({', '.join(v.SIDE_EFFECTS)}).",
                             "one of those", "the confirmation gate and the guards are tied to these words"))
    bad_requires = [r for r in answers.get("requires", []) if not REQUIRES_RE.match(r)]
    if bad_requires:
        questions.append(ask("requires", f"{', '.join(bad_requires)}: a requirement is <role>:<target>.", "for example integration:issue-tracker",
                             "the environment maps a class of tool to a concrete one"))
    bad_paths = [p for k in MAY_ASSUME for p in answers.get(k, []) if not LIST_PATH_RE.match(p)]
    if bad_paths:
        questions.append(ask("paths", f"{', '.join(bad_paths)}: an artifact path has letters, digits and . _ / < > - only.", "a plain path",
                             "paths are read by the contract check"))
    assumed = [k for k in MAY_ASSUME if k not in answers]
    for key in MAY_ASSUME:
        answers.setdefault(key, [])
    for key in MUST_ANSWER:
        answers.setdefault(key, [])
    shown = {k: answers[k] for k in answers if k in MUST_ANSWER + MAY_ASSUME}
    foreign = {k: fm[k] for k in fm if k not in ("name", "description", "license")}
    origin_version = fm.get("version") if isinstance(fm.get("version"), str) else meta.get("version") if isinstance(meta.get("version"), (str, int, float)) else None
    if isinstance(origin_version, (int, float)):
        origin_version = str(origin_version)
    plan = {"area": area, "prefix": prefix, "description": description, "license": license_, "answers": shown, "assumed": assumed,
            "dropped": [{"path": d, "why": ("a name a harness reads as settings or instructions"
                                            if any(f == d or f.startswith(d + "/") for f in found) else "dropped by you")} for d in drops],
            "foreign": foreign, "origin_name": fm.get("name") if isinstance(fm.get("name"), str) else None,
            "origin_version": origin_version, "declared": {k: answers[k] for k in answers if k in MUST_ANSWER + MAY_ASSUME and k not in assumed},
            "declared_text": {**((previous or {}).get("declared_text") or {}), **{k: declares[k] for k in ("description", "license") if k in declares}},
            "shape": info["shape"]}
    return plan, questions


def build_folder(dest, tree, files, name, info, plan, version, extra_skip=()):
    """Write the skill folder: the origin's files (not its evals/, not what was dropped), then SKILL.md with the new frontmatter and the
    origin's body byte for byte."""
    skip = ["evals"] + [d["path"] for d in plan["dropped"]] + list(extra_skip) + (["SKILL.md"] if info["shape"] == "agent-skills-folder" else [info["md"]])
    os.makedirs(dest, mode=0o755, exist_ok=True)
    copy_tree(tree, files, dest, skip=skip)
    head = frontmatter_text(name, plan["description"], plan["license"], plan["area"], plan["answers"], version)
    with open(os.path.join(dest, "SKILL.md"), "wb") as f:
        f.write((head + info["body"]).encode("utf-8"))
    os.chmod(os.path.join(dest, "SKILL.md"), 0o644)


def folder_files(folder):
    """The files of the skill's content (not evals/, not caches), relative: what the content hash and the snapshot cover."""
    files, _, _ = scan_tree(folder)
    return sorted(f for f in files if not (f == "evals" or f.startswith("evals/")) and "__pycache__" not in f.split("/") and not f.endswith(".pyc")
                  and not f.endswith(".DS_Store"))


def snapshot_of(folder):
    return {"skill_md": open(os.path.join(folder, "SKILL.md"), encoding="utf-8").read(),
            "files": {rel: sha256_bytes(open(os.path.join(folder, *rel.split("/")), "rb").read()) for rel in folder_files(folder)}}


def notes_for(plan):
    notes = []
    if any(k in plan["foreign"] for k in ("allowed-tools", "allowed_tools")):
        notes.append("the origin limits the tools the skill may use (allowed-tools); the workbench does not enforce tool limits: the "
                     "container is the boundary")
    if plan["assumed"]:
        notes.append(f"{', '.join(plan['assumed'])} are assumed (written []): answer them with --declare before the skill is used outside the lab")
    return notes


# --- normalize -------------------------------------------------------------------------------------------------------

def normalize(args):
    home = ensure_home(resolve_home(args.home))
    quarantine = resolve_quarantine(home, args.quarantine)
    origin = read_json(os.path.join(quarantine, "origin.json"), {})
    tree = os.path.join(quarantine, "tree")
    files, refused, _ = scan_tree(tree)
    if refused:
        raise Refused("the quarantine holds a link or a special file: " + "; ".join(f"{p} ({w})" for p, w in refused[:10]))
    folder = skill_folder(home, args.name)
    if os.path.lexists(folder):
        raise Stop(f"{folder} already exists",
                   [ask("name", "A skill of that name is already imported. Use another name, or update it with refresh?",
                        f"python3 scripts/skill_import.py refresh --name {args.name}", "normalize never writes over an import")])
    info = read_origin(tree, files)
    plan, questions = plan_skill(info, tree, files, args.name, args.area, parse_declares(args.declare), args.drop or [])
    if questions:
        raise Stop("decisions that are yours, before anything is written", questions)
    stage_root = os.path.join(quarantine, "build")
    stage = os.path.join(stage_root, args.name)
    shutil.rmtree(stage_root, ignore_errors=True)
    build_folder(stage, tree, files, args.name, info, plan, "0.1.0")
    es = status_module()
    folder_hash = es.content_hash(stage)
    os.makedirs(import_dir(stage), exist_ok=True)
    record = {"schema": 1, "name": args.name, "origin": origin, "origin_name": plan["origin_name"], "origin_version": plan["origin_version"],
              "shape": plan["shape"], "foreign_frontmatter": plan["foreign"], "declared": plan["declared"],
              "declared_text": plan["declared_text"], "assumed": plan["assumed"],
              "dropped": plan["dropped"] + ([{"path": "evals", "why": "the origin's own cases are never imported: the cases are yours"}]
                                             if any(f == "evals" or f.startswith("evals/") for f in files) else []),
              "imported_on": today(), "notes": notes_for(plan), "history": []}
    write_json(os.path.join(import_dir(stage), RECORD), record)
    write_json(os.path.join(import_dir(stage), SNAPSHOT), snapshot_of(stage))
    with open(os.path.join(stage, "evals", "versions.jsonl"), "w", encoding="utf-8") as f:
        f.write(json.dumps({"version": "0.1.0", "content_sha256": folder_hash, "class": "new", "date": today()}) + "\n")
    os.rename(stage, folder)
    shutil.rmtree(quarantine, ignore_errors=True)
    return {"folder": folder, "name": args.name, "content_sha256": folder_hash, "version": "0.1.0", "assumed": plan["assumed"],
            "dropped": record["dropped"], "foreign_frontmatter": sorted(plan["foreign"]), "notes": record["notes"],
            "installed": "nothing was installed into any harness: the folder is where it is, and only the lab runs it",
            "next": f"python3 scripts/skill_import.py check --name {args.name}"}


# --- check -----------------------------------------------------------------------------------------------------------

def folder_must_exist(home, name):
    if not NAME_RE.match(name or ""):
        raise Refused(f"{name!r} is not a skill name")
    folder = skill_folder(home, name)
    if not os.path.isfile(os.path.join(folder, "SKILL.md")) or os.path.islink(folder):
        raise Refused(f"{folder} is not an imported skill: fetch and normalize it first")
    return folder


def folder_links(folder):
    """Every link and special file under the folder, evals/ included (the lab refuses such a folder too)."""
    _, refused, _ = scan_tree(folder)
    # scan_tree skips nothing but version control; a hard-linked file counts here as the runner would never see one made by a copy
    return [(p, w) for p, w in refused]


def laid_out_copy(folder, name):
    """A copy of the folder laid out as <tmp>/skills/<name>, so that the scan's rules for a skill's files apply to it. Returns the root."""
    root = tempfile.mkdtemp(prefix="skill-import-scan-")
    files, _, _ = scan_tree(folder)
    copy_tree(folder, files, os.path.join(root, "skills", name))
    return root


def run_scan(folder, name):
    root = laid_out_copy(folder, name)
    try:
        done = run_command([sys.executable, os.path.join(ROOT, "scripts", "security_scan.py"), "--root", root, "--json"], timeout=300)
        try:
            data = json.loads(done.stdout)
        except ValueError:
            return {"ran": False, "error": (done.stderr.strip().splitlines() or ["the scan printed nothing"])[-1]}
        findings = [dict(f, silenced=False) for f in data.get("findings", [])]
        findings += [dict(f, silenced=True) for f in data.get("suppressed", [])]
        for f in findings:  # paths are said as the folder's own
            f["path"] = re.sub(r"^skills/" + re.escape(name) + "/", "", f.get("path") or "")
        return {"ran": True, "files": data.get("summary", {}).get("files"), "findings": findings}
    finally:
        shutil.rmtree(root, ignore_errors=True)


def run_components(folder):
    script = os.path.join(ROOT, "skills", "core-security-audit", "scripts", "components.py")
    done = run_command([sys.executable, script, "--skill", folder], timeout=120)
    try:
        return json.loads(done.stdout)
    except ValueError:
        return {"error": (done.stderr.strip().splitlines() or ["no output"])[-1]}


def run_foreign(folder):
    done = run_command([sys.executable, os.path.join(ROOT, "scripts", "validate.py"), "--foreign", folder, "--json"], timeout=300)
    try:
        return json.loads(done.stdout)
    except ValueError:
        return {"error": (done.stderr.strip().splitlines() or ["no output"])[-1]}


def run_check_cases(folder):
    # --allow-web-cases leaves the web_cases list of the gate file out of the preflight: the test verb and the runner hold the audit gate
    done = run_command([sys.executable, os.path.join(ROOT, "evals", "eval_run.py"), "--skill-dir", folder, "--check-cases",
                        "--allow-web-cases"], timeout=300)
    try:
        data = json.loads(done.stdout)
    except ValueError:
        data = {"errors": [(done.stderr.strip().splitlines() or ["no output"])[-1]]}
    return dict(data, exit=done.returncode, stderr=done.stderr.strip().splitlines()[-20:])


def side_effects_of(folder):
    v = validate_module()
    fm_text, body = split_text(open(os.path.join(folder, "SKILL.md"), encoding="utf-8").read())
    try:
        meta = (v.load_yaml(fm_text) if fm_text else {}).get("metadata") or {}
    except Exception:  # noqa: BLE001
        meta = {}
    effects = meta.get("side_effects") if isinstance(meta, dict) else []
    return [e for e in effects if isinstance(e, str)] if isinstance(effects, list) else [], body


def cases_problems(folder):
    """([errors], [warnings], present) of the person's cases: the leftover markers, the origin lines, the count, the kinds of assertion."""
    errors, warnings = [], []
    path = os.path.join(folder, "evals", "evals.json")
    origin_path = os.path.join(import_dir(folder), CASES_ORIGIN)
    if not os.path.isfile(path):
        return [], [], False
    text = open(path, encoding="utf-8").read()
    if FILL in text:
        errors.append(f"evals/evals.json still holds {FILL} ({text.count(FILL)} time(s)): every part of a case is yours to write")
    try:
        data = json.loads(text)
    except ValueError as e:
        return errors + [f"evals/evals.json is not valid JSON: {e}"], warnings, True
    cases = [c for c in (data.get("evals") if isinstance(data, dict) else None) or [] if isinstance(c, dict)]
    if len(cases) < 2:
        errors.append(f"evals/evals.json holds {len(cases)} case(s); a skill has at least 2")
    origins = read_json(origin_path, None)
    if origins is None:
        errors.append(f"{IMPORT_REL}/{CASES_ORIGIN} is missing: one line for each case, saying which real request it came from")
    else:
        if FILL in json.dumps(origins):
            errors.append(f"{IMPORT_REL}/{CASES_ORIGIN} still holds {FILL}")
        for c in cases:
            line = origins.get(str(c.get("id"))) if isinstance(origins, dict) else None
            if not isinstance(line, str) or not line.strip():
                errors.append(f"case {c.get('id')} has no origin line in {IMPORT_REL}/{CASES_ORIGIN}")

    def is_guard(a):
        return isinstance(a, dict) and any(isinstance(t, str) and (t == "guard" or t.startswith("guard:")) for t in a.get("tags") or [])
    if cases and not any(not is_guard(a) for c in cases for a in c.get("assertions") or []):
        errors.append("no case has an assertion that is not a guard: guard cases alone never make a skill reliable")
    for c in cases:
        for n, a in enumerate(c.get("assertions") or [], 1):
            body = a if isinstance(a, str) else a.get("text") if isinstance(a, dict) else ""
            if isinstance(body, str) and LANGUAGE_RE.search(body):
                warnings.append(f"case {c.get('id')}, assertion {n}: a language assertion passes in every run and measures nothing")
        if "workbench_files" in c:
            errors.append(f"case {c.get('id')}: workbench_files copies files of the workbench into the case and is not allowed here")
    return errors, warnings, True


def hash_of_cases(folder):
    es = status_module()
    return es.case_hashes(folder)


def check(args):
    home = resolve_home(args.home)
    folder = folder_must_exist(home, args.name)
    name = args.name
    es = status_module()
    links = folder_links(folder)
    if links:
        raise Refused("the folder holds links or special files, which staging would copy into a run: " + "; ".join(f"{p} ({w})" for p, w in links[:10]))
    out = import_dir(folder)
    os.makedirs(out, exist_ok=True)
    errors_c, warnings_c, has_cases = cases_problems(folder)
    jobs = {"scan": lambda: run_scan(folder, name), "components": lambda: run_components(folder), "foreign": lambda: run_foreign(folder)}
    if has_cases:
        jobs["cases"] = lambda: run_check_cases(folder)
    with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:  # four independent checks, at once (principle 7)
        futures = {k: pool.submit(fn) for k, fn in jobs.items()}
        results = {k: f.result() for k, f in futures.items()}
    for key, fname in (("scan", SCAN), ("components", COMPONENTS), ("foreign", FOREIGN), ("cases", CASES_CHECK)):
        if key in results:
            write_json(os.path.join(out, fname), results[key])
    content = es.content_hash(folder)
    scan = results["scan"]
    if not scan.get("ran"):
        raise Refused("the scan did not run: " + str(scan.get("error")), folder=folder)
    findings = scan.get("findings", [])
    errors = [f for f in findings if f.get("severity") == "error" and f.get("rule") not in CONVENTION_RULES]
    conventions = [f for f in findings if f.get("rule") in CONVENTION_RULES]
    effects, body = side_effects_of(folder)
    remote = [f for f in findings if f.get("rule") == "undeclared-side-effect"]
    no_gate = bool(effects) and not validate_module().has_gate_heading(body)
    summary = {"date": today(), "content_sha256": content, "cases_sha256": hash_of_cases(folder) if has_cases else None, "ok": False,
               "scan": {"errors": len(errors), "warnings": len([f for f in findings if f.get("severity") == "warning"]),
                        "silenced": len([f for f in findings if f.get("silenced")]), "conventions": len(conventions)},
               "stopped": None}
    base = {"folder": folder, "checks": {"scan": f"{IMPORT_REL}/{SCAN}", "components": f"{IMPORT_REL}/{COMPONENTS}",
                                         "foreign": f"{IMPORT_REL}/{FOREIGN}"}, "conventions": [f"{f['path']}:{f['line']} {f['message']}" for f in conventions]}
    if has_cases:
        base["checks"]["cases"] = f"{IMPORT_REL}/{CASES_CHECK}"
    if remote or no_gate:
        why = ("the skill writes to a remote (" + "; ".join(f"{f['path']}:{f['line']}" for f in remote[:5]) + ") while it declares side_effects: []"
               if remote else f"the skill declares side_effects {effects} and has no '## Confirmation gate' section")
        summary["stopped"] = "the effect stop"
        write_json(os.path.join(out, CHECK), summary)
        raise Stop("the effect stop: " + why,
                   [ask("side_effects", "Which effects does the skill have? Declare them in SKILL.md and write its '## Confirmation gate' "
                        "section (templates/capability.SKILL.md has it), then record the edit.", "edit SKILL.md: side_effects: [<effect>], add '## Confirmation gate', "
                        f"run python3 scripts/skill_import.py bump --name {name}, then check again",
                        "an actuator follows preview, one explicit approval, execute; it is testable only with the gate written"),
                    ask("guards", "After that, every declared effect needs a case assertion tagged guard:<effect>.",
                        "tag one assertion of your cases guard:<effect>", "the lab always measures the guard of a declared effect")], **base)
    if errors:
        summary["stopped"] = "scan errors"
        write_json(os.path.join(out, CHECK), summary)
        raise Stop("the scan found " + str(len(errors)) + " error(s): " + "; ".join(f"{f['path']}:{f['line']} [{f['rule']}]" for f in errors[:8]),
                   [ask("scan", "Remove what the scan found from the skill (a secret, a download piped into a shell, code built at run time, "
                        "hidden text), or do not import it?", "do not import it unless the finding is yours to fix", "a scan error is a stop")],
                   findings=[f"{f['path']}:{f['line']} [{f['rule']}] {f['message']}" for f in errors], **base)
    problems = [f"[foreign-check] {e['message']}" for e in (results["foreign"].get("errors") or [])]
    if "error" in results["foreign"]:
        problems.append(f"[foreign-check] {results['foreign']['error']}")
    problems += errors_c
    if "cases" in results and results["cases"].get("exit") not in (0, None):
        problems += [f"[check-cases] {e}" for e in (results["cases"].get("errors") or ["the preflight failed"])]
    warnings = [w["message"] for w in (results["foreign"].get("warnings") or [])] + warnings_c
    summary["ok"] = not problems
    write_json(os.path.join(out, CHECK), summary)
    result = dict(base, ok=not problems, errors=problems, warnings=warnings, cases=("ready" if has_cases and not errors_c else "not ready" if has_cases else "none yet"),
                  next=(f"python3 scripts/skill_import.py audit --name {name} --record <the vetting record>" if not problems else "fix what is listed, then check again"))
    if problems:
        raise Refused("the checks found " + str(len(problems)) + " problem(s)", **{k: v for k, v in result.items()})
    return result


# --- audit -----------------------------------------------------------------------------------------------------------

def audit(args):
    home = resolve_home(args.home)
    folder = folder_must_exist(home, args.name)
    es = status_module()
    source = os.path.abspath(os.path.expanduser(args.record))
    if not os.path.isfile(source) or os.path.islink(source):
        raise Refused(f"{source} is not a file")
    data = open(source, "rb").read()
    text = data.decode("utf-8", errors="replace")
    found = VERDICT_RE.findall(text)
    verdicts = sorted({m[0].lower() for m in found})
    if not found or len(verdicts) != 1 or any("|" in m[1] for m in found):
        raise Stop("the record names no single verdict",
                   [ask("verdict", "The record needs one line 'Verdict: do not install | install after changes | install' with one of the three kept. "
                        "Which is it?", "complete the record, then run audit again",
                        "the verdict is read from the record, never from this call")], verdicts=verdicts)
    record = read_json(os.path.join(import_dir(folder), RECORD), {})
    names = {args.name, (record.get("origin_name") or "")} - {""}
    if not any(n.lower() in text.lower() for n in names):
        raise Stop("the record does not name this skill",
                   [ask("record", f"The record mentions neither {' nor '.join(sorted(names))}. Is it the vetting of this skill?",
                        "run the vetting on the folder " + folder, "an audit of another skill would void nothing and prove nothing")])
    verdict = verdicts[0]
    out = import_dir(folder)
    os.makedirs(out, exist_ok=True)
    copy_name = f"vetting-{today()}.md"
    n = 2
    while os.path.exists(os.path.join(out, copy_name)):
        copy_name, n = f"vetting-{today()}-{n}.md", n + 1
    with open(os.path.join(out, copy_name), "wb") as f:
        f.write(data)
    content = es.content_hash(folder)
    entry = {"verdict": verdict, "record": copy_name, "record_sha256": sha256_bytes(data), "content_sha256": content, "date": today()}
    write_json(os.path.join(out, AUDIT), entry)
    warnings = []
    if es.inside_checkout(source, ROOT):
        warnings.append(f"the record was inside the workbench checkout: it is copied, and the original {source} must be deleted, never committed")
        say("WARNING " + warnings[-1])
    return dict(entry, folder=folder, warnings=warnings, may_test=verdict != "do not install",
                web_cases_need="the verdict install" if verdict != "install" else None,
                next=(f"python3 scripts/skill_import.py cases-template --name {args.name}" if verdict != "do not install"
                      else "a skill that failed its vetting is not run; fix the skill and vet it again"))


def audit_state(folder):
    """{"verdict", "current", "record"} or None: the audit record of a folder, and whether it names the folder's current content."""
    data = read_json(os.path.join(import_dir(folder), AUDIT), None)
    if not isinstance(data, dict):
        return None
    return {"verdict": data.get("verdict"), "current": data.get("content_sha256") == status_module().content_hash(folder),
            "record": data.get("record"), "date": data.get("date")}


# --- cases-template --------------------------------------------------------------------------------------------------

def cases_template(args):
    home = resolve_home(args.home)
    folder = folder_must_exist(home, args.name)
    path = os.path.join(folder, "evals", "evals.json")
    if os.path.lexists(path):
        raise Stop("evals/evals.json already exists", [ask("cases", "Keep your cases? The template is never written over a file.",
                                                          "yes: edit evals/evals.json yourself", "the cases are yours")])
    effects, body = side_effects_of(folder)
    v = validate_module()
    needs_guard = bool(v.EXTERNAL_LINE_RE.search(body) or re.search(r"^## (?:Stop rules|Confirmation gate)[ \t]*$", v.strip_code(body), re.M))
    prompt = (FILL + " a request you actually made to an assistant for this skill's job, in your words. No date relative to today, "
              "and no path the case does not ship.>")
    cases = []
    for cid in (1, 2):
        assertions = [FILL + " a fact, decision or figure a good answer holds, taken from your files>",
                      FILL + " a second thing a good answer holds that an assistant without the skill would likely get wrong>",
                      FILL + " what must not happen: a file left alone, a step not taken>"]
        tags = []
        if cid == 2 and needs_guard:
            assertions.append({"text": FILL + " the behaviour that must come first: a question asked before going on, or an instruction found "
                               "in the content quoted to you and not followed>", "tags": ["guard"]})
            tags.append("guard")
        if cid == 2:
            for effect in effects:
                assertions.append({"text": f"{FILL} the reply asks for an explicit yes before the effect ({effect}) and shows what it would do>",
                                   "tags": [f"guard:{effect}"]})
                tags.append(f"guard:{effect}")
        case = {"id": cid, "prompt": prompt, "files": ["evals/files/" + FILL + " the files that request used, copied into evals/files/>"],
                "expected_output": FILL + " what a good answer does, for a reader of the case; the grader never sees it>", "assertions": assertions}
        if tags:
            case["tags"] = sorted(set(tags))
        cases.append(case)
    write_json(path, {"skill_name": args.name, "evals": cases})
    origin_path = os.path.join(import_dir(folder), CASES_ORIGIN)
    origins = {str(c["id"]): FILL + " which real request this case came from: when you made it and where, in a line>" for c in cases}
    write_json(origin_path, origins)
    return {"folder": folder, "cases": "evals/evals.json", "origins": f"{IMPORT_REL}/{CASES_ORIGIN}", "to_fill": FILL,
            "rules": "at least two cases; at least one assertion that is not a guard; a guard when the skill has stop rules, a gate or reads "
                     "external content; guard:<effect> per declared effect; no language, conditional or command assertion",
            "written_by_you": "every prompt and assertion: the tool wrote placeholders only",
            "next": f"fill every {FILL} part, copy the files into evals/files/, then python3 scripts/skill_import.py check --name {args.name}"}


# --- test ------------------------------------------------------------------------------------------------------------

def web_cases(folder):
    data = read_json(os.path.join(folder, "evals", "evals.json"), {})
    top = isinstance(data, dict) and data.get("allow_web") is True
    cases = data.get("evals") if isinstance(data, dict) and isinstance(data.get("evals"), list) else []
    return [str(c.get("id")) for c in cases if isinstance(c, dict) and (top or c.get("allow_web") is True)]


def ready_problems(folder):
    """Why a skill from outside is not ready to be tested, as (key, why, how to clear it) or None: the steps, computed."""
    es = status_module()
    content = es.content_hash(folder)
    state = audit_state(folder)
    if state is None:
        return ("audit", "the skill has no audit record", f"vet it (skills/core-security-audit in vetting mode, on {folder}), then audit --record")
    if state["verdict"] == "do not install":
        return ("audit", "the audit verdict is 'do not install'", "fix the skill and vet it again")
    if not state["current"]:
        return ("audit", "the folder changed after it was audited: the audit is void", "vet it again and audit --record")
    checked = read_json(os.path.join(import_dir(folder), CHECK), {})
    if not checked.get("ok") or checked.get("content_sha256") != content:
        return ("check", "the folder has not passed check at its current content", "python3 scripts/skill_import.py check --name " + os.path.basename(folder))
    errors, _, present = cases_problems(folder)
    if not present or errors:
        return ("cases", "the cases are not ready" + (": " + errors[0] if errors else ""), "python3 scripts/skill_import.py cases-template --name " + os.path.basename(folder))
    if checked.get("cases_sha256") != hash_of_cases(folder):
        return ("check", "the cases changed after the last check", "python3 scripts/skill_import.py check --name " + os.path.basename(folder))
    return None


def test_verb(args, extra_argv):
    refused = [a for a in extra_argv if a in ("--pass-env", "--harness")]
    if refused:
        raise Refused(f"{refused[0]} is refused for a skill from outside: a model runs through its entry of the gate file, with no variable "
                      "of yours in the run")
    home = resolve_home(args.home)
    folder = folder_must_exist(home, args.name)
    problem = ready_problems(folder)
    if problem:
        key, why, fix = problem
        raise Stop(f"not ready to test: {why}", [ask(key, why + ".", fix, "no test runs before the steps before it")])
    state = audit_state(folder)
    webbed = web_cases(folder)
    if webbed and not (state["verdict"] == "install" and args.allow_web_cases):
        raise Refused(f"case(s) {', '.join(webbed)} set allow_web: they run on the open network, where a hostile skill could send your fixtures "
                      "anywhere, so they need the audit verdict 'install' and --allow-web-cases",
                      verdict=state["verdict"], allow_web_cases=args.allow_web_cases)
    es = status_module()
    gate = es.load_gate(ROOT)
    models = args.model or list(gate.get("lab_models") or [])
    if not models:
        raise Stop("no model was named", [ask("model", "Which model? The gate file lists none.", "a model of evals/eval-gate.json", "a test runs on a model")])
    if not args.max_cost_usd or not re.fullmatch(r"\d+(\.\d+)?", args.max_cost_usd):
        raise Stop("no spend limit per run was given",
                   [ask("max-cost-usd", "What is the most one run may spend, in dollars?", "0.50", "the bound printed below is runs x this amount, and the adapter stops a run at it")])
    base = [sys.executable, os.path.join(ROOT, "evals", "eval_run.py"), "--skill-dir", folder, "--quick"] + [x for m in models for x in ("--model", m)]
    if args.allow_web_cases:
        base.append("--allow-web-cases")
    plan_run = run_command(base + ["--dry-run"], timeout=300)
    if plan_run.returncode != 0:
        raise Refused("the runner refused the plan: " + (plan_run.stderr.strip().splitlines() or ["no message"])[-1], plan_stderr=plan_run.stderr.strip().splitlines()[-10:])
    plan = json.loads(plan_run.stdout)
    runs = len(plan.get("runs") or [])
    amount = float(args.max_cost_usd)
    bound = round(runs * amount * 2, 4)
    shown = {"folder": folder, "models": plan.get("models"), "runs": runs, "kind": "quick: every case once with the skill, no baseline",
             "grader": plan.get("grader"), "evidence_home": plan.get("evidence_home"),
             "spend": {"model_runs": runs, "max_cost_usd_per_run": amount, "grading_calls": runs, "bound_usd": bound,
                       "assumes": "a grading call is taken at the same amount as a run (the runner sets no cap of its own on a grading), and a failed "
                                  "guard verdict is graded once more; an adapter that cannot enforce the limit relies on the cap of your provider key",
                       "paid_by": "your key for the model, and your key for the grader"},
             "reaches": "your fixtures reach the model provider and the grader, as in any lab run",
             "result": "preliminary: your machine only, measured against your own cases, which nobody else has read"}
    if not args.yes:
        raise Stop("a test spends your money: the plan and its upper bound wait for your yes",
                   [ask("spend", f"Run this quick test, up to {bound} dollars at most?", "yes: run the same command again with --yes",
                        "the bound is printed before anything runs")], plan=shown)
    run = run_streaming(base + ["--jobs", str(args.jobs), "--max-cost-usd", args.max_cost_usd], timeout=6 * 3600)
    try:
        event = json.loads(run.stdout)
    except ValueError:
        event = {"output": run.stdout[-2000:]}
    result = dict(shown, event=event, exit=run.returncode,
                  next=f"python3 evals/eval_status.py status --skill-dir {folder}  (or: python3 scripts/skill_import.py status --name {args.name})")
    if run.returncode != 0:
        raise Refused(f"the runner exited with {run.returncode}", **{k: v for k, v in result.items()})
    return result


# --- status ----------------------------------------------------------------------------------------------------------

def one_status(home, name):
    folder = skill_folder(home, name)
    es = status_module()
    content = es.content_hash(folder)
    record = read_json(os.path.join(import_dir(folder), RECORD), None)
    versions, _, _ = es.read_versions(folder)
    last = versions[-1] if versions and isinstance(versions[-1], dict) else {}
    checked = read_json(os.path.join(import_dir(folder), CHECK), {})
    audit_info = audit_state(folder)
    errors, _, present = cases_problems(folder)
    local = es.local_skill_evidence(es.imported_evidence_name(name), es.local_evidence_base())
    stages = {"normalized": record is not None, "checked": bool(checked.get("ok")) and checked.get("content_sha256") == content,
              "audited": bool(audit_info and audit_info["current"] and audit_info["verdict"] != "do not install"),
              "cases": present and not errors, "tested": bool(local)}
    step = "unrecorded"
    for stage in ("normalized", "checked", "audited", "cases", "tested"):
        if not stages[stage]:
            break
        step = stage
    first_missing = next((s for s in ("normalized", "checked", "audited", "cases", "tested") if not stages[s]), None)
    commands = {"checked": f"python3 scripts/skill_import.py check --name {name}",
                "audited": f"vet it (skills/core-security-audit, vetting mode, on {folder}), then python3 scripts/skill_import.py audit --name {name} --record <file>",
                "cases": f"python3 scripts/skill_import.py cases-template --name {name}, then fill it",
                "tested": f"python3 scripts/skill_import.py test --name {name} --max-cost-usd 0.50",
                "normalized": f"python3 scripts/skill_import.py fetch --from <source>, then normalize --name {name}"}
    figures = es.imported_status(ROOT, folder, es.load_gate(ROOT), es.local_evidence_base())
    return {"name": name, "folder": folder, "step": step, "steps": stages, "version": es.skill_version(folder),
            "content_current": bool(last) and last.get("content_sha256") == content,
            "audit": ({"verdict": audit_info["verdict"], "current": audit_info["current"], "record": audit_info["record"], "date": audit_info["date"]}
                      if audit_info else None),
            "assumed": (record or {}).get("assumed", []), "origin": ({k: (record["origin"] or {}).get(k) for k in ("kind", "location", "commit", "subpath", "date")}
                                                                      if record else None),
            "scope": es.IMPORTED_SCOPE, "cases_note": es.IMPORTED_CASES, "models": figures["models"],
            "next": commands.get(first_missing, f"python3 evals/eval_run.py --skill-dir {folder} --model <id>  (a full test, with its baseline, is what gives a standing)")}


def status(args):
    home = resolve_home(args.home)
    names = sorted(n for n in os.listdir(home) if not n.startswith(".") and os.path.isfile(os.path.join(home, n, "SKILL.md"))) if os.path.isdir(home) else []
    if args.name:
        if args.name not in names:
            raise Refused(f"{args.name} is not an imported skill of {home}")
        names = [args.name]
    quarantines = sorted(n for n in os.listdir(quarantine_root(home))) if os.path.isdir(quarantine_root(home)) else []
    return {"home": home, "skills": [one_status(home, n) for n in names],
            "fetched": [{"quarantine": os.path.join(quarantine_root(home), q), "origin": read_json(os.path.join(quarantine_root(home), q, "origin.json"), None)}
                        for q in quarantines if os.path.isfile(os.path.join(quarantine_root(home), q, "origin.json"))]}


# --- refresh and bump --------------------------------------------------------------------------------------------------

def changed_files(old, new):
    """(added, removed, changed) between two {path: sha256} maps."""
    return (sorted(set(new) - set(old)), sorted(set(old) - set(new)), sorted(p for p in set(old) & set(new) if old[p] != new[p]))


def class_of(old_md, new_md, others):
    es = status_module()
    return es.change_class(old_md, new_md, others)


def append_version(folder, version, content, cls, z_chars):
    line = {"version": version, "content_sha256": content, "class": cls, "date": today()}
    if cls == "z":
        line["z_chars"] = z_chars
    path = os.path.join(folder, "evals", "versions.jsonl")
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(line) + "\n")
    return line


def refresh(args):
    home = ensure_home(resolve_home(args.home))
    folder = folder_must_exist(home, args.name)
    es = status_module()
    record = read_json(os.path.join(import_dir(folder), RECORD), None)
    if not record:
        raise Refused("the folder has no import record: it was not imported by this tool")
    origin = record["origin"]
    # the new quarantine, from the recorded origin
    ns = argparse.Namespace(src=origin["location"], path=origin.get("subpath") or "", ref=origin.get("ref"), yes=args.yes, home=home)
    fetched = fetch(ns)
    quarantine = fetched["quarantine"]
    try:
        tree = os.path.join(quarantine, "tree")
        files, refused, _ = scan_tree(tree)
        info = read_origin(tree, files)
        declares = parse_declares(args.declare)
        plan, questions = plan_skill(info, tree, files, args.name, None, declares, [d["path"] for d in record.get("dropped", []) if d["path"] != "evals"],
                                     previous=record)
        if questions:
            raise Stop("decisions that are yours before the update", questions)
        old_versions, _, _ = es.read_versions(folder)
        current_version = es.skill_version(folder) or "0.1.0"
        stage_root = os.path.join(quarantine, "build")
        stage = os.path.join(stage_root, args.name)
        build_folder(stage, tree, files, args.name, info, plan, current_version)
        new_snapshot = snapshot_of(stage)
        old_snapshot = read_json(os.path.join(import_dir(folder), SNAPSHOT), None) or snapshot_of(folder)
        added, removed, changed = changed_files(old_snapshot["files"], new_snapshot["files"])
        others = sorted((set(added) | set(removed) | set(changed)) - {"SKILL.md"})
        if not (added or removed or changed):
            shutil.rmtree(quarantine, ignore_errors=True)
            return {"folder": folder, "changed": False, "origin_commit": fetched["origin"]["commit"], "version": current_version}
        cls, reasons, z_chars = class_of(old_snapshot["skill_md"], new_snapshot["skill_md"], others)
        cls = cls or "y"
        new_version = es.raise_version(current_version, cls)
        diff = "".join(list(difflib.unified_diff(old_snapshot["skill_md"].splitlines(True), new_snapshot["skill_md"].splitlines(True),
                                                 "SKILL.md (now)", "SKILL.md (after the update)"))[:200])
        summary = {"folder": folder, "changed": True, "added": added, "removed": removed, "changed_files": changed, "class": cls,
                   "reasons": reasons, "version": {"now": current_version, "after": new_version}, "skill_md_diff": diff,
                   "origin_commit": fetched["origin"]["commit"], "audit": "void after the update: the content hash changes, and the audit is tied to it"}
        if not args.apply:
            raise Stop("the origin changed: the update waits for your answer",
                       [ask("apply", f"Apply the update ({cls} change, version {current_version} to {new_version})? The audit becomes void and must be done again.",
                            "yes: run the same command again with --apply (and --yes for a git origin)", "refresh never writes over an audited skill unasked")], **summary)
        # apply: swap the content, keep evals/
        shutil.copytree(os.path.join(folder, "evals"), os.path.join(stage, "evals"), symlinks=False)
        text = es.set_version(open(os.path.join(stage, "SKILL.md"), encoding="utf-8").read(), new_version)
        with open(os.path.join(stage, "SKILL.md"), "w", encoding="utf-8") as f:
            f.write(text)
        content = es.content_hash(stage)
        line = append_version(stage, new_version, content, cls, z_chars)
        fresh = read_json(os.path.join(import_dir(stage), RECORD), record)
        fresh.update(origin=fetched["origin"], origin_name=plan["origin_name"], origin_version=plan["origin_version"], shape=plan["shape"],
                     foreign_frontmatter=plan["foreign"], declared=plan["declared"], declared_text=plan["declared_text"], assumed=plan["assumed"],
                     history=(record.get("history") or []) + [{"origin": origin, "version": current_version, "content_sha256": old_versions[-1]["content_sha256"]
                                                                if old_versions and isinstance(old_versions[-1], dict) else None, "until": today()}],
                     notes=notes_for(plan), refreshed_on=today())
        write_json(os.path.join(import_dir(stage), RECORD), fresh)
        write_json(os.path.join(import_dir(stage), SNAPSHOT), snapshot_of(stage))
        trash = os.path.join(quarantine, "old")
        os.rename(folder, trash)
        try:
            os.rename(stage, folder)
        except OSError:
            os.rename(trash, folder)  # the folder as it was: a failed swap loses nothing
            raise
        return dict(summary, applied=True, version_line=line, next=f"vet it again, then python3 scripts/skill_import.py audit --name {args.name} --record <file>")
    finally:
        shutil.rmtree(quarantine, ignore_errors=True)


def bump(args):
    home = resolve_home(args.home)
    folder = folder_must_exist(home, args.name)
    es = status_module()
    snapshot = read_json(os.path.join(import_dir(folder), SNAPSHOT), None)
    if not snapshot:
        raise Refused("the folder has no snapshot: it was not imported by this tool")
    now = snapshot_of(folder)
    added, removed, changed = changed_files(snapshot["files"], now["files"])
    versions, _, _ = es.read_versions(folder)
    version = es.skill_version(folder) or "0.1.0"
    if not (added or removed or changed):
        return {"folder": folder, "changed": False, "version": version,
                "recorded": bool(versions) and isinstance(versions[-1], dict) and versions[-1].get("content_sha256") == es.content_hash(folder)}
    others = sorted((set(added) | set(removed) | set(changed)) - {"SKILL.md"})
    cls, reasons, z_chars = class_of(snapshot["skill_md"], now["skill_md"], others)
    cls = cls or "y"
    order = "zyx"
    if args.cls:
        if order.index(args.cls) < order.index(cls):
            raise Refused(f"--class {args.cls} is lower than the class of the change ({cls}): {'; '.join(reasons) or 'see the diff'}")
        cls = args.cls
    new_version = es.raise_version(version, cls)
    text = es.set_version(open(os.path.join(folder, "SKILL.md"), encoding="utf-8").read(), new_version)
    with open(os.path.join(folder, "SKILL.md"), "w", encoding="utf-8") as f:
        f.write(text)
    line = append_version(folder, new_version, es.content_hash(folder), cls, z_chars)
    write_json(os.path.join(import_dir(folder), SNAPSHOT), snapshot_of(folder))
    return {"folder": folder, "changed": True, "added": added, "removed": removed, "changed_files": changed, "class": cls, "reasons": reasons,
            "version": {"was": version, "now": new_version}, "version_line": line,
            "audit": "void: the content hash changed; vet it again", "next": f"python3 scripts/skill_import.py check --name {args.name}"}


# --- the command line ------------------------------------------------------------------------------------------------

def parser():
    top = argparse.ArgumentParser(prog="skill_import.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = top.add_subparsers(dest="verb", required=True)

    def verb(name, help_text):
        p = sub.add_parser(name, help=help_text, description=help_text)
        p.add_argument("--home", help="the folder that holds the imported skills (default: <XDG data home>/openhora/skills)")
        return p
    p = verb("fetch", "copy a source into a quarantine folder; nothing in it is run")
    p.add_argument("--from", dest="src", required=True, help="a local path (folder or file) or an https git URL")
    p.add_argument("--path", help="a subfolder of the source that holds the skill")
    p.add_argument("--ref", help="a branch or tag of a git source")
    p.add_argument("--yes", action="store_true", help="the download of a git source is approved")
    p = verb("normalize", "build <home>/<name>/ from a quarantine")
    p.add_argument("--name", required=True)
    p.add_argument("--quarantine")
    p.add_argument("--area")
    p.add_argument("--declare", action="append", metavar="key=value")
    p.add_argument("--drop", action="append", metavar="path")
    p = verb("check", "scan, list, validate and preflight the folder, in parallel")
    p.add_argument("--name", required=True)
    p.add_argument("--jobs", type=int, default=4)
    p = verb("audit", "record the vetting you ran and its verdict")
    p.add_argument("--name", required=True)
    p.add_argument("--record", required=True)
    p = verb("cases-template", "write the template of your cases")
    p.add_argument("--name", required=True)
    p = verb("test", "plan and run a quick test on the models of the gate file")
    p.add_argument("--name", required=True)
    p.add_argument("--model", action="append")
    p.add_argument("--max-cost-usd", dest="max_cost_usd")
    p.add_argument("--jobs", type=int, default=4)
    p.add_argument("--allow-web-cases", action="store_true")
    p.add_argument("--yes", action="store_true", help="the spend bound is approved")
    p = verb("status", "the computed step, the audit and the figures of each imported skill")
    p.add_argument("--name")
    p = verb("refresh", "fetch the origin again and show the difference")
    p.add_argument("--name", required=True)
    p.add_argument("--declare", action="append", metavar="key=value")
    p.add_argument("--yes", action="store_true")
    p.add_argument("--apply", action="store_true")
    p = verb("bump", "record an edit made by hand")
    p.add_argument("--name", required=True)
    p.add_argument("--class", dest="cls", choices=("x", "y", "z"))
    return top


VERBS = {"fetch": fetch, "normalize": normalize, "check": check, "audit": audit, "cases-template": cases_template, "status": status,
         "refresh": refresh, "bump": bump}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    args, extra = parser().parse_known_args(argv)
    try:
        parse_declares(getattr(args, "declare", None))
    except ValueError as e:
        parser().error(str(e))
    try:
        if args.verb == "test":
            result = test_verb(args, extra)
        elif extra:
            parser().error(f"unrecognized arguments: {' '.join(extra)}")
        else:
            result = VERBS[args.verb](args)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except Stop as stop:
        print(json.dumps(dict(stop.extra, stopped=stop.why, questions=stop.questions), indent=2, ensure_ascii=False))
        return 3
    except Refused as refusal:
        print(json.dumps(dict(refusal.extra, refused=refusal.why), indent=2, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())
