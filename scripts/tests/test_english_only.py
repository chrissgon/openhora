"""Tests for the english-only check of scripts/validate.py.

Run: uv run --with pytest pytest scripts/tests

Each test writes a few files to a temporary folder and runs the check on it. Portuguese strings
are written as escapes or assembled from pieces so that this file passes the check itself.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "validate.py"
spec = importlib.util.spec_from_file_location("validate", SCRIPT)
validate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validate)

NAO = "n\u00e3o"          # "not"
ACAO = "a\u00e7\u00e3o"   # "action"
COLLOQUIAL_FOR = "p" + "ra"


def write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def errors(root: Path) -> list[str]:
    report = validate.Report()
    validate.check_english(report, root=str(root))
    return [f"{e['where']} {e['message']}" for e in report.errors]


def test_english_text_passes(tmp_path):
    write(tmp_path, "skills/demo/SKILL.md", "# Demo\n\nOpen the pull request. Prague, practice, isosceles.\n")
    write(tmp_path, "docs/names.md", "Caf\u00e9 and na\u00efve r\u00e9sum\u00e9 are English loanwords.\n")
    assert errors(tmp_path) == []


def test_diacritic_is_an_error(tmp_path):
    write(tmp_path, "skills/demo/evals/evals.json", '{"prompt": "Escreve a ' + ACAO + '"}\n')
    found = errors(tmp_path)
    assert len(found) == 1
    assert found[0].startswith("skills/demo/evals/evals.json:1 [english-only]")


def test_portuguese_word_is_an_error_in_any_case(tmp_path):
    write(tmp_path, "notes.md", "fine\nsend it " + COLLOQUIAL_FOR.upper() + " review\n")
    found = errors(tmp_path)
    assert len(found) == 1 and found[0].startswith("notes.md:2 ")


def test_allow_with_reason_exempts_the_line(tmp_path):
    write(tmp_path, "docs/a.md", f'Quoted title "{NAO}" <!-- validate: allow english-only -- a source title -->\n')
    assert errors(tmp_path) == []


def test_allow_without_reason_is_an_error(tmp_path):
    write(tmp_path, "docs/a.md", f"{NAO} # validate: allow english-only\n")
    found = errors(tmp_path)
    assert len(found) == 1 and "needs a reason" in found[0]


def test_path_allow_file_exempts_the_file(tmp_path):
    write(tmp_path, "fixtures/pt/page.html", f"<p>{NAO}</p>\n")
    write(tmp_path, ".security-scan-allow", "fixtures/pt/page.html english-only -- a fixture that must stay Portuguese\n")
    assert errors(tmp_path) == []


def test_html_comment_allow_without_reason_is_an_error(tmp_path):
    # Before the fix, "-->" was read as "--" followed by the reason ">".
    write(tmp_path, "docs/a.md", f"{NAO} <!-- validate: allow english-only -->\n")
    found = errors(tmp_path)
    assert len(found) == 1 and "needs a reason" in found[0]


def test_comment_terminator_is_not_a_reason(tmp_path):
    write(tmp_path, "docs/a.md", f"{NAO} <!-- validate: allow english-only -- -->\n")
    write(tmp_path, "docs/b.css", f"/* {NAO} validate: allow english-only -- */\n")
    write(tmp_path, "docs/c.md", f"{NAO} <!-- validate: allow english-only --reason -->\n")
    found = errors(tmp_path)
    assert len(found) == 3 and all("needs a reason" in f for f in found)


def test_html_comment_allow_with_reason_exempts_the_line(tmp_path):
    write(tmp_path, "docs/a.md", f"{NAO} <!-- validate: allow english-only -- a quoted source title -->\n")
    write(tmp_path, "docs/b.css", f"/* {NAO} validate: allow english-only -- a fixture string */\n")
    assert errors(tmp_path) == []


def test_phrase_part_portuguese_file_passes_without_an_allow_line(tmp_path):
    write(tmp_path, "runtime/phrases_parts/demo-1.pt-BR.json",
          '{"package": "demo-1", "table": {"DEMO_KEY": "Voc\u00ea ' + NAO + ' tem a\u00e7\u00e3o"}}\n')
    assert errors(tmp_path) == []


def test_phrase_part_exemption_is_narrow(tmp_path):
    # Vacuity: the same Portuguese in any other file, or in a near-miss path, still fails.
    text = '{"table": {"DEMO_KEY": "' + NAO + '"}}\n'
    write(tmp_path, "runtime/phrases_parts/demo-1.en.json", text)
    write(tmp_path, "runtime/phrases_parts/sub/demo-1.pt-BR.json", text)
    write(tmp_path, "runtime/other/demo-1.pt-BR.json", text)
    write(tmp_path, "runtime/phrases_parts/demo-1.pt-BR.json.bak", text)
    write(tmp_path, "docs/notes.md", NAO + "\n")
    found = errors(tmp_path)
    assert len(found) == 5
    assert not any(f.startswith("runtime/phrases_parts/demo-1.pt-BR.json:") for f in found)
