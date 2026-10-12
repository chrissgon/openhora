"""What the scheduler's jobs start runs on the system interpreter (stage 6, WP-6.7): every module of the runtime, and
every script a module starts with its own interpreter, is on the list the Python 3.9 job checks; what is not is
started through uv, git or bash, or by the lab through the facade. Offline: the sources are read, nothing is run.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_system_python_starts.py
"""
from __future__ import annotations

import ast
import glob
import json
import re

import standin_tree as st

REPO = st.REPO

# Every start of a script with sys.executable, per module of the runtime: one row per argument list the module's
# source opens with it (`[sys.executable`); a mention elsewhere (a report, a message) starts nothing. "<skill scripts>" stands for the scripts of skills the runtime runs isolated: the checkers a runtime manifest names (the third test) and the backlog reader;
# "<handlers>" for every file of runtime/handlers/ (the first test).
STARTS = {
    "runtime/ops.py": ["scripts/evidence.py", "<handlers>"],
    "runtime/plan.py": ["scripts/select_skills.py"],
    "runtime/isolated.py": ["<skill scripts>"],  # a manifest's checkers and the backlog reader, through run_script
    "runtime/handlers/published_posts.py": ["runtime/cli.py"],
    # The ported social agent (WP-7.1): the parser, the store, the gate twice (record, decide) and, since WP-7.3b,
    # the contained run (the agent's run is the operation `contained-run` of runtime/cli.py); the vote step's
    # checkers, the scheduler provider twice (dry run, then confirmed), the contained run of the vote agent;
    # the vote job's queue update.
    # the engagement gate is no longer started here (CONS-2a): the operations layer runs it through runtime/isolated.py;
    # the shell is started twice, for the contained run and for execute-under-policy
    "runtime/handlers/social.py": ["skills/mkt-engage/scripts/parse_notification.py", "providers/store/sqlite.py",
                                   "runtime/cli.py", "runtime/cli.py"],
    "runtime/handlers/social_vote.py": [
        "skills/mkt-vote-round/scripts/vote_state.py", "skills/mkt-vote-round/scripts/vote_update.py",
        "skills/mkt-social-copy/scripts/check_post.py", "skills/brand-identity/scripts/render.py",
        "skills/mkt-publish/scripts/payload.py", "<scheduler provider>", "<scheduler provider>", "runtime/cli.py"],
    "runtime/handlers/social_vote_job.py": ["skills/mkt-vote-round/scripts/vote_update.py"],
}
# The programs a module of the runtime starts by name; the lab's own starts (docker, the adapters) go through the
# facade, runtime/lab.py, and are the lab's.
PROGRAMS = ("git", "uv", "bash", "/usr/bin/osascript")  # osascript: the macOS notification the old script already sent
# A start whose argument list is built elsewhere in the module: where it is built.
BUILT_ELSEWHERE = {"runtime/effects.py": "def provider_call", "runtime/handlers/published_posts.py": "def _cli",
                   # the ported social agent (WP-7.1): its run() and call() take a list built by the callers
                   "runtime/handlers/social.py": "def parser_cmd", "runtime/handlers/social_vote_job.py": "def main("}


def system_list() -> list:
    tree = ast.parse((REPO / "scripts" / "tests" / "test_runtime_python39.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "ON_SYSTEM_PYTHON" for t in node.targets):
            return list(ast.literal_eval(node.value))
    raise AssertionError("ON_SYSTEM_PYTHON is gone from scripts/tests/test_runtime_python39.py")


def modules() -> list:
    found = sorted(glob.glob(str(REPO / "runtime" / "*.py")) + glob.glob(str(REPO / "runtime" / "handlers" / "*.py")))
    return [p[len(str(REPO)) + 1:] for p in found]


def test_every_module_of_the_runtime_is_on_the_system_python_list():
    listed = set(system_list())
    assert [m for m in modules() if m not in listed] == []


def test_everything_the_runtime_starts_with_its_own_interpreter_is_on_the_list():
    listed = set(system_list())
    for module in modules():
        count = len(re.findall(r"\[\s*sys\.executable\b", (REPO / module).read_text(encoding="utf-8")))
        assert count == len(STARTS.get(module, [])), \
            f"{module} starts {count} script(s) with sys.executable: add a row to STARTS for each script it starts"
    for module, paths in STARTS.items():
        for path in paths:
            if path.startswith("<"):
                continue
            assert path in listed, f"{module} starts {path} with its own interpreter: put it on ON_SYSTEM_PYTHON"


def test_every_checker_a_manifest_names_is_on_the_list():
    checked = 0
    for manifest in sorted(glob.glob(str(REPO / "skills" / "*" / "evals" / "runtime-manifest.json"))):
        data = json.loads(open(manifest, encoding="utf-8").read())
        skill_dir = manifest.rsplit("/evals/", 1)[0]
        for document in data.get("documents") or []:
            for check in document.get("checks") or []:
                source = open(f"{skill_dir}/scripts/{check[0]}", encoding="utf-8").read()
                ast.parse(source, feature_version=(3, 9))
                checked += 1
    assert checked, "no manifest names a checker: the test checks nothing"


def test_what_does_not_run_on_the_system_python_is_started_through_uv():
    for module in modules():
        if module == "runtime/lab.py":
            continue  # the facade: the lab's own starts
        source = (REPO / module).read_text(encoding="utf-8")
        for call in re.finditer(r"subprocess\.(?:run|Popen|check_output|check_call|call)\(\s*([^,)]+)", source):
            first = call.group(1).strip()
            head = first[1:].strip() if first.startswith("[") else ""
            # a list whose first element is a literal or sys.executable is checked here; one built from a
            # comprehension (`[str(c) for c in cmd]`) is built elsewhere, like a name
            if first.startswith("[") and (head.startswith('"') or head.startswith("sys.executable")):
                assert head.startswith("sys.executable") or any(head.startswith(f'"{p}"') for p in PROGRAMS), \
                    f"{module} starts {first[:60]!r}: use the system interpreter, {', '.join(PROGRAMS)}, or the facade"
            else:
                assert module in BUILT_ELSEWHERE and BUILT_ELSEWHERE[module] in source, \
                    f"{module} starts {first!r}, built where this test does not know: add it to BUILT_ELSEWHERE"
        for built in re.finditer(r"(?:return|run\()\s*\[\s*(\"[a-z0-9-]+\"|sys\.executable)", source):
            head = built.group(1)
            assert head == "sys.executable" or head.strip('"') in PROGRAMS, f"{module} builds a start of {head}"
