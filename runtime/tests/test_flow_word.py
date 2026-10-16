"""The word for the entity is "flow" everywhere a person or a model reads (FLOW-WORD, decision of 2026-10-16): the runtime's code,
help and messages, the page, the public site, the contract of the runtime, the pages of the platform's map and the READMEs say
"flow", never "workflow". The word stays where it names something else: GitHub Actions' workflows (`.github/workflows`, a
reusable workflow, `workflow_dispatch`), a dated line of a changelog (history is not rewritten), and the few lines in ALLOWED,
each with its reason. A planted line in a temporary copy proves the scan fails. Offline.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_flow_word.py
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WORD = re.compile(r"(?i)\bwork-?flows?\b")

# GitHub Actions' meaning of the word.
ACTIONS = re.compile(r"\.github/workflows|\.github\" / \"workflows|workflow_(call|dispatch|run|sha|ref)|CI workflows?|reusable workflow|"
                     r"official workflow|checks workflow|caller's workflow", re.IGNORECASE)
CHANGELOG = re.compile(r"^- \d{4}-\d{2}-\d{2}:")

# (path relative to the repository, a text that must be in the line, the reason)
ALLOWED = (
    ("runtime/tests/test_flow_word.py", "", "this test names the word it looks for"),
    ("runtime/routines.py", "(version 1 called it `workflow`", "the comment of CONTENT_VERSION: version 1 called the key of the flow `workflow`"),
    ("runtime/routines.py", "the rename of `workflow` to `flow` did", "the docstring of content() says why the content version moved"),
    ("runtime/routines.py", 'old.get("workflow")', "differences() reads the key of a content stored as version 1, to say that only the format differs"),
    ("runtime/tests/test_routines.py", '"workflow" not in new', "the content of version 2 has no `workflow` key"),
    ("runtime/tests/test_routines.py", 'old["workflow"] = 1', "the tests build a content as version 1 stored it"),
    ("runtime/tests/test_ops_routines.py", '"workflow" not in now', "the content of version 2 has no `workflow` key"),
    ("runtime/tests/test_ops_routines.py", "the key was `workflow`", "the test builds a routine's record as version 1 stored it"),
    ("runtime/tests/test_ops_routines.py", 'old["workflow"] = 1', "the test builds a routine's record as version 1 stored it"),
    ("runtime/tests/test_channel_policy.py", '"workflows" not in operations.GROUPS', "no alias for the old group name"),
    ("runtime/tests/test_channel_policy.py", 'for stale in ("workflows", "flows")', "the old group name is refused naming the known groups"),
    ("runtime/handlers/social_vote_job.py", "profile's own workflow", "a profile repository's own CI workflow (GitHub Actions)"),
    ("contracts/runtime.md", 'replaced "workflow" as the key', "the contract says that the routine content's key was once `workflow` (content version 2)"),
    ("docs/architecture/platform/contracts-and-references.md", "workflow files", "workflow files of a project are GitHub Actions files, not declared artifacts"),
)

# The surfaces a person or a model reads: the runtime (not the recorded corpus), the page, the site, the contracts and the platform map.
SURFACES = (
    "runtime/**/*.py", "interface/js/**/*.js", "interface/css/**/*.css", "interface/README.md", "site/*.html", "contracts/runtime.md",
    "docs/architecture/platform/*.md", "README.md", "runtime/README.md", "providers/store/sqlite.py", "interface/index.html",
    "interface/demo/**/*.js", "interface/demo/**/*.css", "interface/demo/**/*.html", "interface/demo/**/*.json",
)
SKIPPED = ("runtime/tests/corpus/",)


def surface_files(root: Path) -> list:
    seen, out = set(), []
    for pattern in SURFACES:
        for path in sorted(root.glob(pattern)):
            rel = path.relative_to(root).as_posix()
            if path.is_file() and rel not in seen and not rel.startswith(SKIPPED):
                seen.add(rel)
                out.append(path)
    return out


def allowed(rel: str, line: str) -> bool:
    if ACTIONS.search(line) or CHANGELOG.match(line):
        return True
    return any(rel == path and needle in line for path, needle, _reason in ALLOWED)


def findings(root: Path) -> list:
    out = []
    for path in surface_files(root):
        rel = path.relative_to(root).as_posix()
        for number, line in enumerate(path.read_text(encoding="utf-8").split("\n"), 1):
            if WORD.search(line) and not allowed(rel, line):
                out.append(f"{rel}:{number}: {line.strip()[:100]}")
    return out


def test_no_surface_a_person_or_a_model_reads_says_workflow_for_the_entity():
    found = findings(REPO)
    assert not found, 'the entity is called "flow" (FLOW-WORD); use it, or allow the line with its reason:\n' + "\n".join(found)


def test_every_allowed_line_still_exists_so_that_the_list_does_not_outlive_its_reasons():
    for path, needle, reason in ALLOWED:
        assert reason and (REPO / path).is_file(), path
        lines = [l for l in (REPO / path).read_text(encoding="utf-8").split("\n") if WORD.search(l)]
        assert any(needle in l for l in lines) or path.endswith("test_flow_word.py"), f"{path} has no line with the word and {needle!r}: remove the entry"


def test_a_planted_line_in_a_copy_is_found_and_the_actions_and_changelog_lines_pass(tmp_path):
    for rel, body in {"runtime/cli.py": "# a workflow of the project\n", "README.md": "- 2026-10-16: workflows renamed\nCI workflows run on GitHub\n",
                      "site/index.html": "<p>skills, agents and workflows</p>\n", "interface/js/x.js": "const t = 'Save workflow';\n",
                      "docs/architecture/platform/a.md": "see .github/workflows/checks.yml\n",
                      "runtime/routines.py": 'old.get("workflow")\n"the workflow template changed"\n',      # one allowed line, and a planted one in the same file
                      "interface/index.html": "<p>a workflow</p>\n", "interface/demo/content.js": "export const t = 'workflows';\n"}.items():
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    assert sorted(findings(tmp_path)) == sorted(["runtime/cli.py:1: # a workflow of the project", "runtime/routines.py:2: \"the workflow template changed\"",
                                  "interface/js/x.js:1: const t = 'Save workflow';", "interface/index.html:1: <p>a workflow</p>",
                                  "interface/demo/content.js:1: export const t = 'workflows';", "site/index.html:1: <p>skills, agents and workflows</p>"])
