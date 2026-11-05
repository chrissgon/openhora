"""The `- Language: <tag>` header line must change neither the return code nor the report of
skills/brand-profile/scripts/check_profile.py. Offline; every name and number is fictional.

Run: uv run --python 3.11 --with pytest==9.1.1 pytest -q skills/brand-profile/scripts/tests
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
CHECK_PROFILE = "skills/brand-profile/scripts/check_profile.py"
OWNER = "- Owner: brand-profile\n"
TAGS = ["pt-BR", "en-US"]

HEAD = ("# Brand profile: Dana\n\n" + OWNER + "- Status: confirmed\n- Date: 2026-10-01\n"
        "- Language of posts: English [1]\n\n")
PASSING = HEAD + "\n".join([
    "## Who they are", "- Staff engineer since 2019 [1]", "",
    "## Never expose", "- Employer [2]", "", "## Voice", "- Samples written by them:", "  > hello network [3]", "",
    "## Sources", "[1] Export, provided 2026-09-29.", "[2] User in chat, 2026-09-29.",
    "[3] Post, 2022-11-04, https://www.linkedin.com/feed/update/urn:li:activity:6994304183386443776/", ""])
# contact data, an undefined and an unused reference, an empty never-expose list, unmarked samples, an undated source
FAILING = (PASSING.replace("- Employer [2]", "").replace("- Samples written by them:", "- Samples:")
           .replace("since 2019 [1]", "since 2019 [1][4], call +44 20 7946 0000")
           .replace("[3] Post, 2022-11-04,", "[3] Post, undated,"))
# translated headings, run with the matching flags
TRANSLATED = ("# Perfil da marca: Dana\n\n" + OWNER + "- Status: confirmado\n- Date: 2026-10-01\n\n" + "\n".join([
    "## Quem e", "- Engenheira desde 2019 [1]", "", "## Nunca expor", "- Empregador [2]", "",
    "## Voz", "- Amostras escritas por ela:", "  > ola rede [3]", "",
    "## Fontes", "[1] Exportacao, 2026-09-29.", "[2] Usuaria no chat, 2026-09-29.", "[3] Post, 2022-11-04.", ""]))
TRANSLATED_FLAGS = ("--sources-heading", "Fontes", "--samples-heading", "Voz", "--never-heading", "Nunca expor",
                    "--author-marker", "escritas por")


def check(tmp_path: Path, sub: str, text: str, *flags: str):
    folder = tmp_path / sub
    folder.mkdir()
    doc = folder / "profile.md"
    doc.write_text(text, encoding="utf-8")
    r = subprocess.run([sys.executable, str(ROOT / CHECK_PROFILE), "--file", str(doc), *flags],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode in (0, 1), r.stderr
    return r.returncode, json.loads(r.stdout)


def with_language(text: str, tag: str) -> str:
    assert OWNER in text
    return text.replace(OWNER, OWNER + f"- Language: {tag}\n", 1)


def unshift(report: dict) -> dict:
    """The new header line moves every reported "line N" down by one; undo that, change nothing else."""
    out = json.loads(json.dumps(report))
    out["contact_data"] = [re.sub(r"\d+", lambda m: str(int(m.group()) - 1), s) for s in out["contact_data"]]
    return out


@pytest.mark.parametrize("tag", TAGS)
@pytest.mark.parametrize("text,flags,passing", [(PASSING, (), True), (FAILING, (), False),
                                                (TRANSLATED, TRANSLATED_FLAGS, True)])
def test_language_line_changes_neither_code_nor_report(tmp_path, tag, text, flags, passing):
    base_rc, base = check(tmp_path, "base", text, *flags)
    new_rc, new = check(tmp_path, "with", with_language(text, tag), *flags)
    assert (base_rc == 0) == passing, base
    assert new_rc == base_rc
    assert unshift(new) == base
    if passing:
        assert new["ok"] is True


def test_failing_document_keeps_its_known_findings_with_the_language_line(tmp_path):
    base_rc, base = check(tmp_path, "base", FAILING)
    _, out = check(tmp_path, "with", with_language(FAILING, "pt-BR"))
    assert base["contact_data"] == ["line 9"] and out["contact_data"] == ["line 10"]  # only the line number moves
    assert out["undefined"] == ["4"] and out["unused"] == ["2"]
    assert out["never_empty"] is True and out["samples_unmarked"] is True
    assert out["no_date"] == ["3"]


def test_language_line_directly_after_the_title_also_changes_nothing(tmp_path):
    title = "# Brand profile: Dana\n\n"
    rc, report = check(tmp_path, "x", PASSING.replace(title, title + "- Language: en-US\n", 1))
    assert rc == 0 and report["ok"] is True
