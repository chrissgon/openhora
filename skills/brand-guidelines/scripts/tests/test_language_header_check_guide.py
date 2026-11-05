"""The `- Language: <tag>` header line must change neither the return code nor the report of
skills/brand-guidelines/scripts/check_guide.py, with the default heading or a translated --examples-heading.
Offline; every name and number is fictional.

Run: uv run --python 3.11 --with pytest==9.1.1 pytest -q skills/brand-guidelines/scripts/tests
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
CHECK_GUIDE = "skills/brand-guidelines/scripts/check_guide.py"
OWNER = "- Owner: brand-guidelines\n"
TAGS = ["pt-BR", "en-US"]

BRAND_FILES = {
    "profile.md": "Maker of small garden tools\n",
    "name.md": "Name: Verde Tools\n",
    "strategy.md": "label: Builder of small tools\n",
    "identity.md": "accent #07B6F0\n",
    "voice.md": '> "NEW BLOG POST!!!"\n',
}
HEAD = "# Brand guide: Verde Tools\n\n" + OWNER + "- Status: draft\n- Date: 2026-10-01\n\n"
BODY_CITES = ("- Who: small garden tools [profile.md]\n- Name: Verde Tools [name.md]\n"
              '- Label: "Builder of small tools" [strategy.md]\n- Accent #07B6F0 [identity.md]\n- Voice [voice.md]\n\n')
PASSING = (HEAD + "## 1. Who the brand is\n" + BODY_CITES +
           "## 8. Do and don't\n| Do | Don't |\n|---|---|\n"
           '| "NEW BLOG POST!!!" | "NEW BLOG POST!!!" |\n')
# not passing: a colour that identity.md lacks, a stale quote, a missing source and an unquoted example
FAILING = (HEAD + "## 1. Who the brand is\n" + BODY_CITES +
           'Never write "a sentence nobody ever wrote" and keep #FF0000 out. [ghost.md]\n\n'
           "## 8. Do and don't\n| Do | Don't |\n|---|---|\n"
           '| "NEW BLOG POST!!!" | Too many emojis |\n')
# translated heading: the default "Do and don't" matches none of its headings
TRANSLATED = (HEAD + "## 1. Quem e a marca\n" + BODY_CITES +
              "## 8. Fazer e evitar\n| Fazer | Evitar |\n|---|---|\n"
              '| "NEW BLOG POST!!!" | Emojis demais |\n')


def brand_dir(tmp_path: Path) -> Path:
    d = tmp_path / "brand"
    if not d.exists():
        d.mkdir()
        for name, text in BRAND_FILES.items():
            (d / name).write_text(text, encoding="utf-8")
    return d


def check(tmp_path: Path, sub: str, text: str, *flags: str):
    folder = tmp_path / sub
    folder.mkdir()
    guide = folder / "guide.md"
    guide.write_text(text, encoding="utf-8")
    r = subprocess.run([sys.executable, str(ROOT / CHECK_GUIDE), "--guide", str(guide),
                        "--brand-dir", str(brand_dir(tmp_path)), *flags],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode in (0, 1), r.stderr
    return r.returncode, json.loads(r.stdout)


def with_language(text: str, tag: str) -> str:
    assert OWNER in text
    return text.replace(OWNER, OWNER + f"- Language: {tag}\n", 1)


@pytest.mark.parametrize("tag", TAGS)
@pytest.mark.parametrize("text,flags,passing", [
    (PASSING, (), True), (FAILING, (), False),
    (TRANSLATED, (), True),  # default heading: the translated table is not looked at
    # with the flag the unquoted cell "Emojis demais" is reported, so this one does not pass
    (TRANSLATED, ("--examples-heading", "Fazer e evitar"), False)])
def test_language_line_changes_neither_code_nor_report(tmp_path, tag, text, flags, passing):
    base_rc, base = check(tmp_path, "base", text, *flags)
    new_rc, new = check(tmp_path, "with", with_language(text, tag), *flags)
    assert (base_rc == 0) == passing, base
    assert new_rc == base_rc
    assert new == base  # the script reports no line numbers, so the reports are identical


def test_baseline_documents_pass_and_fail_as_intended(tmp_path):
    rc, report = check(tmp_path, "pass", PASSING)
    assert rc == 0 and report["ok"] is True
    rc, report = check(tmp_path, "fail", FAILING)
    assert rc == 1
    assert report["stale_quotes"] == ["a sentence nobody ever wrote"]
    assert report["hex_not_in_identity"] == ["#FF0000"]
    assert report["missing_sources"] == ["ghost.md"]
    assert report["unquoted_examples"] == ["Too many emojis"]


@pytest.mark.parametrize("tag", TAGS)
def test_translated_heading_flag_decides_what_is_reported_not_the_language_line(tmp_path, tag):
    text = with_language(TRANSLATED, tag)
    rc, default = check(tmp_path, "default", text)
    assert rc == 0 and default["unquoted_examples"] == []
    rc, flagged = check(tmp_path, "flagged", text, "--examples-heading", "Fazer e evitar")
    assert rc == 1 and flagged["unquoted_examples"] == ["Emojis demais"]
    # the same two answers without the Language line
    assert check(tmp_path, "d0", TRANSLATED)[1] == default
    assert check(tmp_path, "f0", TRANSLATED, "--examples-heading", "Fazer e evitar")[1] == flagged


def test_language_line_directly_after_the_title_also_changes_nothing(tmp_path):
    title = "# Brand guide: Verde Tools\n\n"
    rc, report = check(tmp_path, "x", PASSING.replace(title, title + "- Language: pt-BR\n", 1))
    assert rc == 0 and report["ok"] is True
