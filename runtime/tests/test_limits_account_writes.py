"""Two static limits of the writes to the person's own accounts (package FND; contracts/runtime.md L57 and L58), with the allow-lists they start from. The
packages that add a writer (providers/writer/, providers/mailer/gmail.py and outlook.py) add to these lists in their own pull request, one pair at a time,
each with the sentence that says why; today every list is empty, because no writer ships yet, and the tests prove the scanners work on samples.

  L57  No script anywhere holds a permanent-delete call: no `permanentDelete`, `batchDelete`, `emptyTrash`, no HTTP DELETE, no `"trashed": true`. The only
       removals are moves to a place the person restores from. The one pair a later package may add: the Google calendar's `events/{id}` DELETE, which Google
       sends to the calendar's trash for 30 days.
  L58  A writer is named (`writer:`) only by the effect modules of the writes and by the one read-only seam module: nothing else of runtime/ calls one.

Offline, no model.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_limits_account_writes.py
"""
from __future__ import annotations

import ast
import re

import pytest

import standin_tree as st

REPO = st.REPO

# L57 -- the files the scan reads, and the pairs (relative file, a text the same string must hold) that are allowed to hold a DELETE.
WRITER_FILES = ["providers/writer/*.py", "providers/mailer/gmail.py", "providers/mailer/outlook.py"]
ALLOWED_DELETE = ()          # W1 adds ("providers/writer/google-calendar.py", "events/"): Google sends an event to the calendar's trash [30 days]
DANGEROUS_WORDS = re.compile(r"permanent_?delete|batch_?delete|empty_?trash|permanentdelete|batchdelete|emptytrash", re.I)
DELETE_METHOD = re.compile(r"\bDELETE\b")
TRASHED_TRUE = re.compile(r"""["']?trashed["']?\s*[:=]\s*(?:true|True)""")
# L58 -- the modules of runtime/ that may name a writer.
WRITER_NAMERS = ("effect_calendar.py", "effect_mailbox.py", "effect_files.py", "ops_step_seams.py")


def _docstrings(tree):
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body and isinstance(node.body[0], ast.Expr) \
                and isinstance(node.body[0].value, ast.Constant) and isinstance(node.body[0].value.value, str):
            found.add(id(node.body[0].value))
    return found


def _strings(node) -> list:
    return [n.value for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str)]


def delete_findings(source: str, name: str = "<sample>", allowed=ALLOWED_DELETE) -> list:
    """What breaks L57 in a Python source: every string that is not a docstring, and every name, is read (a comment is not code and is not read). A DELETE
    string is allowed only inside a call that also holds the text an allowed pair names, in the file the pair names."""
    tree = ast.parse(source)
    skip = _docstrings(tree)
    parent = {id(child): node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in skip:
            text = node.value
            if DANGEROUS_WORDS.search(text):
                found.append((name, node.lineno, "a permanent-delete word in a string"))
            if TRASHED_TRUE.search(text):
                found.append((name, node.lineno, "trashed set to true"))
            if DELETE_METHOD.search(text):
                call, up = None, parent.get(id(node))
                while up is not None and call is None:
                    call = up if isinstance(up, ast.Call) else None
                    up = parent.get(id(up))
                if call is None or not any(name.endswith(file) and any(part in t for t in _strings(call)) for file, part in allowed):
                    found.append((name, node.lineno, "an HTTP DELETE"))
        elif isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and key.value == "trashed" and isinstance(value, ast.Constant) and value.value is True:
                    found.append((name, node.lineno, "trashed set to true"))
        elif isinstance(node, (ast.Name, ast.Attribute, ast.FunctionDef, ast.AsyncFunctionDef)):
            ident = node.id if isinstance(node, ast.Name) else node.attr if isinstance(node, ast.Attribute) else node.name
            if DANGEROUS_WORDS.search(ident) or ident in ("delete_file", "files_delete"):
                found.append((name, node.lineno, "a permanent-delete name"))
    return found


def writer_files() -> list:
    out = []
    for pattern in WRITER_FILES:
        out += sorted(p for p in REPO.glob(pattern) if p.is_file() and "tests" not in p.parts)
    return out


def test_limit_57_no_script_of_the_writers_holds_a_permanent_delete_today():
    scanned = writer_files()
    found = [f for path in scanned for f in delete_findings(path.read_text(encoding="utf-8"), str(path.relative_to(REPO)))]
    assert found == [], found
    assert ALLOWED_DELETE == (), "no pair is allowed until the package that needs it adds it, with the reason"


@pytest.mark.parametrize("source, kind", [
    ("requests.request('DELETE', url)", "an HTTP DELETE"),
    ("call(method='DELETE', path='x')", "an HTTP DELETE"),
    ("verb = 'permanentDelete'", "a permanent-delete word"),
    ("path = '/users/me/messages/batchDelete'", "a permanent-delete word"),
    ("path = 'trash/emptyTrash'", "a permanent-delete word"),
    ("body = {'trashed': True}", "trashed set to true"),
    ("body = '{\"trashed\": true}'", "trashed set to true"),
    ("def delete_file(x):\n    return x", "a permanent-delete name"),
    ("service.files_delete(id)", "a permanent-delete name"),
    ("api.permanentDelete(id)", "a permanent-delete name"),
])
def test_limit_57_the_scanner_finds_each_way_to_delete_for_good(source, kind):
    assert any(kind in f[2] for f in delete_findings(source)), (source, delete_findings(source))


def test_limit_57_a_docstring_a_comment_and_a_trash_move_are_not_findings():
    quiet = '"""Never DELETE, permanentDelete or emptyTrash: only moves to the trash."""\n# DELETE would be a finding if it were code\n' \
            'def move(x):\n    """A message goes to the trash with a POST, never DELETE."""\n    return {"trashed": False, "addLabelIds": ["TRASH"]}\n'
    assert delete_findings(quiet) == []


def test_limit_57_one_allowed_pair_lets_that_file_hold_that_path_and_nothing_else():
    allowed = (("providers/writer/google-calendar.py", "events/"),)
    ok = "request('DELETE', '/calendars/primary/events/abc')"
    assert delete_findings(ok, "providers/writer/google-calendar.py", allowed) == []
    assert delete_findings(ok, "providers/writer/gmail.py", allowed) != []
    assert delete_findings("request('DELETE', '/users/me/messages/abc')", "providers/writer/google-calendar.py", allowed) != []


def runtime_modules() -> list:
    return sorted((REPO / "runtime").glob("*.py")) + sorted((REPO / "runtime" / "handlers").glob("*.py"))


def test_limit_58_only_the_effect_modules_and_the_seam_name_a_writer():
    found = sorted(p.name for p in runtime_modules() if "writer:" in p.read_text(encoding="utf-8"))
    assert set(found) <= set(WRITER_NAMERS), found
