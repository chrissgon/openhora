"""providers/model/ names no vendor and no model, and chat-http.py is the kind of file the resolver can start: a hyphenated name the resolver
accepts, a header with no dependencies, the standard library alone, a size under the budget. The words are written here in pieces so that this file
does not contain them: a vendor and a model live in runtime/ and evals/, never in providers/ (the specification of package IX-2b, section 2).
"""
import ast
import re
from pathlib import Path

import pytest

FOLDER = Path(__file__).resolve().parents[1]
REPO = FOLDER.parents[1]
PROVIDER = FOLDER / "chat-http.py"
WORDS = re.compile("|".join(["open" + "router", "anth" + "ropic", "deep" + "seek", "clau" + "de", "open" + "ai"]), re.I)
STDLIB = {"__future__", "hashlib", "http", "json", "os", "socket", "ssl", "sys", "time", "urllib"}


def files():
    return [p for p in FOLDER.rglob("*") if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"]


def found(text):
    return WORDS.findall(text)


def test_no_file_of_the_folder_names_a_vendor_or_a_model():
    assert files()
    assert {str(p.relative_to(FOLDER)): found(p.read_text(encoding="utf-8")) for p in files() if found(p.read_text(encoding="utf-8"))} == {}


@pytest.mark.parametrize("planted", ["Open" + "Router", "x ANTH" + "ROPIC y", "deep" + "seek-v4", "Clau" + "de Haiku", "Open" + "AI"])
def test_vacuity_the_word_oracle_catches_each_word_in_any_case(planted):
    assert found(planted) != [] and found("a neutral provider") == []


def test_the_provider_is_a_hyphenated_name_the_resolver_accepts():
    assert re.fullmatch(r"[a-z0-9][a-z0-9-]*", PROVIDER.stem) and PROVIDER.name == "chat-http.py"
    assert not (FOLDER / "chat_http.py").exists()


def test_the_header_declares_no_dependency_and_python_39():
    head = PROVIDER.read_text(encoding="utf-8")[:600]
    assert re.search(r'^# requires-python = ">=3\.9"$', head, re.M) and re.search(r"^# dependencies = \[\]$", head, re.M)


def test_the_file_imports_the_standard_library_only_and_stays_under_its_budget():
    tree = ast.parse(PROVIDER.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            names.add((node.module or "").split(".")[0])
    assert names and names <= STDLIB, names - STDLIB
    assert len(PROVIDER.read_text(encoding="utf-8").splitlines()) <= 600


def test_vacuity_the_import_oracle_catches_a_third_party_import():
    tree = ast.parse("import requests\nfrom json import dumps")
    names = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert not names <= STDLIB


def test_the_provider_prints_no_exception_text_and_never_a_format_of_a_body():
    """The only writes to stderr are the one code line: no traceback call, no print of an exception, no logging."""
    text = PROVIDER.read_text(encoding="utf-8")
    assert "traceback" not in text and "logging" not in text and "print(" not in text
    assert text.count("sys.stderr.write") == 1
