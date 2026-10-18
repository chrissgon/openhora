"""Two static measures of the writes to the person's own accounts (package FND; contracts/runtime.md L57 and L58), with the allow-lists they start from. Both are
MEASURES, not the limits: a script can build a request that a scan of its text does not read (a path computed at run time, a library call the scan does not know),
and a grep cannot see a module that is loaded by a name made at run time. The limits themselves are in the writers (each one's constant `ALLOWED`, a tuple of
`(method, path regex)` pairs, and a request function that refuses any other request, with fake servers that fail on it; packages W1 to W4a) and in the structure of
the approval (`ops_step_effects.approve`). What these tests do is catch the plain ways to break them early, and they say so.

  L57  No writer script holds a permanent-delete call: no `permanentDelete`, `batchDelete`, `emptyTrash`, no HTTP DELETE (in a string, in any case, joined from
       pieces, as bytes, as a method name of a library, or as a name of a function), no `trashed` set to anything but false. The only removals are moves to a place
       the person restores from. The one pair a later package may add: the Google calendar's `events/{id}` DELETE, which Google sends to the calendar's trash for
       30 days. It is honoured only as a pair of the file's own constant, `ALLOWED = (("DELETE", r"<the approved regex>"), ...)`, with the regex the allow-list
       below names for that file; a DELETE written anywhere else in that file (a call with the path in another argument, a decoy) is a finding.
  L58  A writer is named (`writer:`) only by the effect modules of the writes and by the one read-only seam module: nothing else of runtime/, at any depth, does.

Offline, no model.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_limits_account_writes.py
"""
from __future__ import annotations

import ast
import re

import pytest

import standin_tree as st

REPO = st.REPO

# L57 -- the files the scan reads (writers, the mailers of the person's own account, the shared helpers, the authorize scripts and the readers, which send GET only)
SCANNED = ["providers/writer/**/*.py", "providers/mailer/gmail.py", "providers/mailer/outlook.py", "providers/_*.py", "providers/accounts/**/*.py",
           "providers/mailbox/*.py", "providers/calendar/*.py", "providers/documents/gdrive*.py", "providers/documents/onedrive*.py"]
# (relative file, the approved path regex): W1 adds ("providers/writer/google-calendar.py", r"<the events/{id} regex>"), with the reason
ALLOWED_DELETE = ()
WORD = re.compile(r"(?<![A-Za-z])delete(?![A-Za-z])", re.I)               # the word `delete` alone (not `deleted`, `deleteditems`)
METHODISH = re.compile(r"\s*delete(?![A-Za-z-])", re.I)                    # a string that starts with the method: "DELETE", "delete /x"
DANGEROUS = re.compile(r"permanent_?delete|batch_?delete|empty_?trash", re.I)
TRASHED_TRUE = re.compile(r"""trashed["']?\s*[:=]\s*(?:true|1)\b""", re.I)
# The one thing a script may delete: its own record in the local OS secret store (`forget` of the authorize scripts), which is no data of an account.
LOCAL_RECORD_NAMES = ("delete_password",)
LOCAL_RECORD_TEXT = re.compile(r"secret store", re.I)
TOKEN = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+")
CASE_METHODS = ("upper", "lower", "title", "casefold", "capitalize", "swapcase", "strip", "lstrip", "rstrip")
# L58 -- the modules of runtime/ that may name a writer.
WRITER_NAMERS = ("effect_calendar.py", "effect_mailbox.py", "effect_files.py", "ops_step_seams.py")


def _docstrings(tree) -> set:
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body and isinstance(node.body[0], ast.Expr) \
                and isinstance(node.body[0].value, ast.Constant) and isinstance(node.body[0].value.value, str):
            found.add(id(node.body[0].value))
    return found


def _fold(node):
    """The text a node is made of when it is made of constants alone: a string, bytes, pieces joined with `+`, a case method applied to a constant
    (`'del'.upper()`); None otherwise."""
    if isinstance(node, ast.Constant):
        if isinstance(node.value, str):
            return node.value
        return node.value.decode("latin-1") if isinstance(node.value, bytes) else None
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _fold(node.left), _fold(node.right)
        return left + right if left is not None and right is not None else None
    if isinstance(node, ast.Call) and not node.args and not node.keywords and isinstance(node.func, ast.Attribute) and node.func.attr in CASE_METHODS:
        inner = _fold(node.func.value)
        return getattr(inner, node.func.attr)() if inner is not None else None
    return None


def _tokens(ident: str) -> list:
    return [t.lower() for t in TOKEN.findall(ident)]


def _falsy(node) -> bool:
    return isinstance(node, ast.Constant) and node.value in (False, None, 0) and node.value is not True


def _declared(tree, name: str, allowed, file: str) -> tuple:
    """(ids of the constants of the approved pairs of the module's constant `name`, whether the file holds one). A pair ("DELETE", regex) is approved only
    when the allow-list names this file with this very regex."""
    ids, held = set(), False
    for node in tree.body:
        target = node.targets[0] if isinstance(node, ast.Assign) and len(node.targets) == 1 else getattr(node, "target", None)
        value = getattr(node, "value", None)
        if not (isinstance(target, ast.Name) and target.id == name and isinstance(value, (ast.Tuple, ast.List))):
            continue
        for pair in value.elts:
            if isinstance(pair, (ast.Tuple, ast.List)) and len(pair.elts) == 2 and all(isinstance(e, ast.Constant) and isinstance(e.value, str) for e in pair.elts):
                method, regex = pair.elts
                if method.value.lower() == "delete" and any(file.endswith(f) and regex.value == r for f, r in allowed):
                    ids.update((id(method), id(regex)))
                    held = True
    return ids, held


def delete_findings(source: str, name: str = "<sample>", allowed=ALLOWED_DELETE) -> list:
    """What breaks L57 in a Python source, as (file, line, what). Every string that is not a docstring is read after it is joined from its pieces, in any case and
    as bytes; every name, attribute, argument and keyword is read by its words (`event_delete` has the word `delete`); a comment is not code and is not read. In a
    file with no approved pair the word `delete` anywhere is a finding. In a file that holds an approved pair in its constant `ALLOWED` the word may name a
    function or a verb, and what stays a finding is the method itself: a string that starts with it, outside the approved pair, and an attribute named `delete`."""
    tree = ast.parse(source)
    skip = _docstrings(tree)
    approved, holds_pair = _declared(tree, "ALLOWED", allowed, name)
    found = set()

    def add(node, what):
        found.add((name, getattr(node, "lineno", 0), what))

    for node in ast.walk(tree):
        text = _fold(node)
        if text is not None and id(node) not in skip and id(node) not in approved:
            if DANGEROUS.search(text):
                add(node, "a permanent-delete word in a string")
            if TRASHED_TRUE.search(text):
                add(node, "trashed set to true")
            if (holds_pair and METHODISH.match(text) or not holds_pair and WORD.search(text)) and not LOCAL_RECORD_TEXT.search(text):
                add(node, "an HTTP DELETE")
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and key.value == "trashed" and not _falsy(value):
                    add(node, "trashed set to true")
        if isinstance(node, ast.keyword) and node.arg == "trashed" and not _falsy(node.value):
            add(node.value, "trashed set to true")
        if isinstance(node, ast.Assign) and not _falsy(node.value):
            for target in node.targets:
                if isinstance(target, ast.Subscript):
                    index = target.slice.value if hasattr(ast, "Index") and isinstance(target.slice, ast.Index) else target.slice
                    if _fold(index) == "trashed":
                        add(node, "trashed set to something other than false")      # `body['trashed'] = x`
        idents = []
        if isinstance(node, ast.Name):
            idents = [node.id]
        elif isinstance(node, ast.Attribute):
            idents = [node.attr]
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            idents = [node.name]
        elif isinstance(node, ast.arg):
            idents = [node.arg]
        elif isinstance(node, ast.keyword) and node.arg:
            idents = [node.arg]
        elif isinstance(node, ast.alias):
            idents = [node.asname or node.name]
        for ident in idents:
            tokens = _tokens(ident)
            if ident in LOCAL_RECORD_NAMES:
                continue
            if DANGEROUS.search(ident) or ident in ("delete_file", "files_delete"):
                add(node, "a permanent-delete name")
            elif "delete" in tokens and (not holds_pair or (isinstance(node, ast.Attribute) and node.attr.lower() == "delete")):
                add(node, "a name for deleting")
    return sorted(found)


def scanned_files() -> list:
    out = set()
    for pattern in SCANNED:
        out.update(p for p in REPO.glob(pattern) if p.is_file() and "tests" not in p.parts and "__pycache__" not in p.parts)
    return sorted(out)


def test_limit_57_measure_no_script_of_the_writers_helpers_or_readers_holds_a_permanent_delete_today():
    scanned = scanned_files()
    assert scanned, "the scan reads no file"
    found = [f for path in scanned for f in delete_findings(path.read_text(encoding="utf-8"), str(path.relative_to(REPO)))]
    assert found == [], found
    assert ALLOWED_DELETE == (), "no pair is allowed until the package that needs it adds it, with the reason"


SAMPLES = {
    "an HTTP DELETE": ["requests.request('DELETE', url)", "conn.request('delete', p)", "Request(url, method='delete'.upper())", "conn.request('DEL' + 'ETE', p)",
                       "conn.request(b'DELETE', p)", "m = 'del' + 'ete'", "Request(url, method='DELETE')", "f = 'Delete'", "x = ('de' + 'lete').upper()"],
    "a name for deleting": ["requests.delete(url)", "s.delete(url)", "service.users().messages().delete(userId='me', id=x).execute()", "def delete_event(x):\n    return x",
                            "def eventDelete(x):\n    return x", "client.deleteEvent(x)", "def f(delete=False):\n    return delete", "delete = 1", "api.Delete(x)"],
    "a permanent-delete word": ["verb = 'permanentDelete'", "path = '/users/me/messages/batchDelete'", "path = 'trash/emptyTrash'",
                                "getattr(api, 'perm' + 'anentDelete')(x)", "getattr(api, 'permanent' + '_delete')(x)"],
    "a permanent-delete name": ["api.permanentDelete(id)", "service.batch_delete(x)", "def empty_trash(x):\n    return x"],
    "trashed set to": ["body = {'trashed': True}", "body = {'trashed': flag}", "body = '{\"trashed\": true}'", "body = dict(trashed=True)", "body = dict(trashed=flag)",
                       "body['trashed'] = True", "body['trashed'] = flag", "body['tra' + 'shed'] = 1", "files.update(fileId=i, trashed=True)"],
}


@pytest.mark.parametrize("kind, source", [(k, s) for k, many in SAMPLES.items() for s in many])
def test_limit_57_measure_the_scan_finds_each_plain_way_to_delete_for_good(kind, source):
    found = delete_findings(source)
    assert any(kind in f[2] for f in found), (source, found)


@pytest.mark.parametrize("source", [
    '"""Never DELETE, permanentDelete or emptyTrash: only moves to the trash."""\n# DELETE would be a finding if it were code\n'
    'def move(x):\n    """A message goes to the trash with a POST, never DELETE."""\n    return {"trashed": False, "addLabelIds": ["TRASH"]}\n',
    "folder = 'deleteditems'\nlabel = 'Deleted Items'\nstate = 'deleted'\n", "body = {'trashed': False}\nbody2 = dict(trashed=False)\nbody['trashed'] = False\n",
    "def undelete_nothing():\n    return 'restore from the trash'\n"])
def test_limit_57_measure_a_docstring_a_comment_a_trash_move_and_a_folder_name_are_not_findings(source):
    assert delete_findings(source) == []


# the shape W1's spec gives: a constant of the file, and a request function that refuses what it does not list
APPROVED = r"/calendars/[^/]+/events/[^/]+"
ALLOW = (("providers/writer/google-calendar.py", APPROVED),)
FILE = "providers/writer/google-calendar.py"
LEGIT = f'''ALLOWED = (("GET", r"/calendars/[^/]+/events"), ("POST", r"/calendars/[^/]+/events"), ("DELETE", r"{APPROVED}"))

def event_delete(calendar, event):
    """Remove one event: Google sends it to the calendar's trash."""
    return request("DELETE" if False else method_for("event-delete"), f"/calendars/{{calendar}}/events/{{event}}")

def request(method, path):
    if not any(m == method and re.fullmatch(p, path) for m, p in ALLOWED):
        raise ValueError("refused")
'''


def test_limit_57_measure_an_approved_pair_in_the_files_own_constant_is_honoured_and_its_verb_may_be_named_for_it():
    assert delete_findings(LEGIT.replace('"DELETE" if False else ', ""), FILE, ALLOW) == []


def test_limit_57_measure_a_decoy_a_wrong_regex_a_wrong_file_and_a_second_delete_are_findings():
    decoy = LEGIT + "\nrequest('DELETE', '/calendars/' + cal, note='events/')\n"
    assert any("HTTP DELETE" in f[2] for f in delete_findings(decoy, FILE, ALLOW))
    assert delete_findings(LEGIT.replace(APPROVED, "/calendars/.*"), FILE, ALLOW) != []                        # not the regex the allow-list names
    assert delete_findings(LEGIT.replace(APPROVED, APPROVED + "|/users/.*"), FILE, ALLOW) != []
    assert delete_findings(LEGIT, "providers/writer/gmail.py", ALLOW) != []                                      # not the file the allow-list names
    assert delete_findings(LEGIT, FILE, ()) != []                                                                 # an empty allow-list allows nothing
    two = LEGIT.replace('("DELETE", r"%s"))' % APPROVED, '("DELETE", r"%s"), ("DELETE", r"/users/me/messages/[^/]+"))' % APPROVED)
    assert any("HTTP DELETE" in f[2] for f in delete_findings(two, FILE, ALLOW))
    assert any("name for deleting" in f[2] for f in delete_findings(LEGIT + "\nrequests.delete(url)\n", FILE, ALLOW))
    assert any("permanent-delete" in f[2] for f in delete_findings(LEGIT + "\nverb = 'permanentDelete'\n", FILE, ALLOW))
    assert any("trashed" in f[2] for f in delete_findings(LEGIT + "\nbody = {'trashed': True}\n", FILE, ALLOW))


def runtime_modules() -> list:
    return sorted(p for p in (REPO / "runtime").rglob("*.py") if "tests" not in p.parts and "__pycache__" not in p.parts)


def test_limit_58_measure_only_the_effect_modules_and_the_seam_name_a_writer_at_any_depth_of_runtime():
    modules = runtime_modules()
    assert any(p.parent.name == "handlers" for p in modules) and (REPO / "runtime" / "ops.py") in modules
    found = sorted(p.name for p in modules if "writer:" in p.read_text(encoding="utf-8"))
    assert set(found) <= set(WRITER_NAMERS), found
