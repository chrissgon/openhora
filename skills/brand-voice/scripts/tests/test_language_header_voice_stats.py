"""A `- Language: <tag>` header line in voice.md changes nothing voice_stats.py `check --rules` decides.

Run: uv run --python 3.11 --with pytest==9.1.1 pytest -q skills/brand-voice/scripts/tests

Offline; every name below is fictional. The line sits right after the `- Owner:` header line, above the
```voice-rules block the script reads its limits from.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "skills/brand-voice/scripts/voice_stats.py"
TAGS = ("pt-BR", "en-US")

VOICE = """# Brand voice: Sam Rivera

- Owner: brand-voice
- Status: confirmed (2027-09-28)
- Date: 2027-09-28
- Reads: profile, strategy
- Applies to: posts and replies on the example network

## In one sentence

Plain and a little dry. [1]

## Checkable limits

```voice-rules
{"max_emojis": 1, "max_hashtags": 2, "max_exclamations": 0, "end_with_question": true, "no_emoji_line_start": true, "banned": ["game changer"]}
```
- Check: voice_stats.py check --rules docs/brand/voice.md < draft (script of brand-voice)

## Sources

[1] the person's words, 2027-09-28
"""

GOOD_DRAFT = {"id": "draft-1", "text": "A small parser in 900 lines.\nWhat would you cut first?\n#parsing"}
BAD_DRAFT = {"id": "draft-2", "text": "A game changer! \U0001F680 \U0001F680 It ships today. #a #b #c"}


def with_language(text: str, tag: str) -> str:
    """Insert `- Language: <tag>` after the `- Owner:` line, else after the first `- Key:` header line."""
    lines = text.split("\n")
    head = next(i for i, ln in enumerate(lines) if ln.startswith("## "))
    owner = [i for i in range(head) if lines[i].startswith("- Owner:")]
    first = [i for i in range(head) if re.match(r"- [A-Z][A-Za-z ]*:", lines[i])]
    at = (owner or first)[0]
    return "\n".join(lines[:at + 1] + [f"- Language: {tag}"] + lines[at + 1:])


def check(rules_file: Path, draft: dict) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), "check", "--rules", str(rules_file)], input=json.dumps(draft),
                          capture_output=True, text=True, timeout=60)


def same_result(a: subprocess.CompletedProcess, b: subprocess.CompletedProcess) -> None:
    assert (a.returncode, a.stdout, a.stderr) == (b.returncode, b.stdout, b.stderr)


def test_the_baseline_voice_guide_has_the_header_the_tests_edit():
    assert "- Owner: brand-voice" in VOICE and "- Language:" not in VOICE
    assert with_language(VOICE, "pt-BR").splitlines()[2:4] == ["- Owner: brand-voice", "- Language: pt-BR"]


@pytest.mark.parametrize("tag", TAGS)
def test_a_passing_draft_passes_the_same_with_the_language_line(tmp_path, tag):
    plain, lang = tmp_path / "plain.md", tmp_path / "lang.md"
    plain.write_text(VOICE, encoding="utf-8")
    lang.write_text(with_language(VOICE, tag), encoding="utf-8")
    a, b = check(plain, GOOD_DRAFT), check(lang, GOOD_DRAFT)
    assert a.returncode == 0, a.stdout
    same_result(a, b)
    out = json.loads(b.stdout)
    assert out["ok"] is True and out["violations"] == []


@pytest.mark.parametrize("tag", TAGS)
def test_a_failing_draft_fails_with_the_same_violations(tmp_path, tag):
    plain, lang = tmp_path / "plain.md", tmp_path / "lang.md"
    plain.write_text(VOICE, encoding="utf-8")
    lang.write_text(with_language(VOICE, tag), encoding="utf-8")
    a, b = check(plain, BAD_DRAFT), check(lang, BAD_DRAFT)
    assert a.returncode == 1
    assert json.loads(a.stdout)["violations"] == [
        "2 emojis, limit 1", "3 hashtags, limit 2", "1 exclamation marks, limit 0", "does not end with a question",
        "banned phrase: 'game changer'"]
    same_result(a, b)


@pytest.mark.parametrize("tag", TAGS)
def test_the_rules_block_is_still_found_and_a_broken_one_still_fails(tmp_path, tag):
    broken = VOICE.replace('"max_emojis": 1', '"max_emojis": "one"')
    plain, lang = tmp_path / "plain.md", tmp_path / "lang.md"
    plain.write_text(broken, encoding="utf-8")
    lang.write_text(with_language(broken, tag), encoding="utf-8")
    a, b = check(plain, GOOD_DRAFT), check(lang, GOOD_DRAFT)
    assert a.returncode == 2 and "unknown or has the wrong type" in a.stderr
    same_result(a, b)
    # a guide without the block is not JSON, with and without the line
    nothing = VOICE.replace("```voice-rules", "```json")
    plain.write_text(nothing, encoding="utf-8")
    lang.write_text(with_language(nothing, tag), encoding="utf-8")
    a, b = check(plain, GOOD_DRAFT), check(lang, GOOD_DRAFT)
    assert a.returncode == 2 and "has no ```voice-rules block and is not JSON" in a.stderr
    assert a.stderr.replace(str(plain), "RULES") == b.stderr.replace(str(lang), "RULES")
