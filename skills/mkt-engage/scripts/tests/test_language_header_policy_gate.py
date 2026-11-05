"""A `- Language: <tag>` header line in the engagement policy changes no decision of policy_gate.py.

Run: uv run --python 3.11 --with pytest==9.1.1 pytest -q skills/mkt-engage/scripts/tests

Offline; every name below is fictional. The line sits right after the `- Owner:` header line of the policy, above the
```engagement-policy block. The policy file is hashed whole, so its hash changes with the line, by design: the
standing approval of the state file is bound to the hash, and these tests bind each variant to its own hash.
What must not change is that the block is found and that every decision, reason and count is the same.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
GATE = REPO / "skills/mkt-engage/scripts/policy_gate.py"
TAGS = ("pt-BR", "en-US")

POLICY = """# Engagement policy: Sam Rivera

- Owner: mkt-engage
- Network: the example network; comments come in as links the person pastes

## What replies on its own

Short thanks, and questions the profile answers.

## Machine-readable policy

```engagement-policy
{"auto_reply_categories": ["thanks_or_praise", "question_answerable_from_sources"], "languages": ["EN"],
 "max_replies_per_day": 2, "max_auto_replies_per_person_per_post": 1,
 "reply_rules": {"max_sentences": 3, "max_emojis": 0, "max_hashtags": 0, "allow_links": false, "banned": ["game changer"]},
 "never_in_replies": ["first computer"]}
```
"""
PROFILE = """```sensitive-topics
{"action": "never_reply_escalate_to_user", "topics": {"salary": {"keywords": ["salary"], "exclude": []}}}
```

| tinykv | 900 lines, zero deps |
"""


def with_language(text: str, tag: str) -> str:
    """Insert `- Language: <tag>` after the `- Owner:` line, else after the first `- Key:` header line."""
    lines = text.split("\n")
    head = next(i for i, ln in enumerate(lines) if ln.startswith("## "))
    owner = [i for i in range(head) if lines[i].startswith("- Owner:")]
    first = [i for i in range(head) if re.match(r"- [A-Z][A-Za-z ]*:", lines[i])]
    at = (owner or first)[0]
    return "\n".join(lines[:at + 1] + [f"- Language: {tag}"] + lines[at + 1:])


def make_project(root: Path, tag: str | None, bound_to: str | None = None) -> Path:
    """A project whose policy carries the Language line when `tag` is given. The standing approval is bound to the hash
    of `bound_to` (the policy text it approved), by default the policy of the project itself."""
    for sub in ("docs/marketing", "docs/brand", "docs/workbench"):
        (root / sub).mkdir(parents=True)
    policy = with_language(POLICY, tag) if tag else POLICY
    (root / "docs/marketing/engagement-policy.md").write_text(policy, encoding="utf-8")
    (root / "docs/brand/profile.md").write_text(PROFILE, encoding="utf-8")
    digest = hashlib.sha256((bound_to if bound_to is not None else policy).encode("utf-8")).hexdigest()
    (root / "docs/workbench/state.md").write_text(
        f"| standing | engagement | policy:{digest} | 2026-09-30 | 2099-01-01 | active |\n", encoding="utf-8")
    (root / "comment.json").write_text(json.dumps({
        "comment_urn": "urn:li:comment:(urn:li:activity:1,2)", "post_urn": "urn:li:activity:1",
        "commenter": "Sam", "text": "How big is tinykv?"}), encoding="utf-8")
    (root / "sources.json").write_text(json.dumps(["docs/brand/profile.md, proof table"]), encoding="utf-8")
    return root


def decide(root: Path, category: str = "question_answerable_from_sources", reply: str = "About 900 lines, and zero deps.",
          language: str = "EN", comment: dict | None = None) -> dict:
    (root / "reply.txt").write_text(reply, encoding="utf-8")
    if comment:
        (root / "comment.json").write_text(json.dumps(comment), encoding="utf-8")
    r = subprocess.run([sys.executable, str(GATE), "decide", "--policy", "docs/marketing/engagement-policy.md",
                        "--comment-file", "comment.json", "--category", category, "--language", language,
                        "--reply-file", "reply.txt", "--sources-file", "sources.json",
                        "--skills-dir", str(REPO / "skills")], capture_output=True, text=True, cwd=root, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def policy_hash(root: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(GATE), "policy-hash", "--policy", "docs/marketing/engagement-policy.md"],
                          capture_output=True, text=True, cwd=root, timeout=60)


def without_hash(out: dict) -> dict:
    return {k: v for k, v in out.items() if k != "policy_hash"}


# the decisions to compare: (label, arguments of decide, expected decision)
CASES = [
    ("a factual answer from the cited file", {}, "auto"),
    ("praise", {"category": "thanks_or_praise", "reply": "Thanks, Sam."}, "auto"),
    ("another language", {"category": "thanks_or_praise", "reply": "Valeu, Sam.", "language": "PT"}, "inbox"),
    ("a category that is not automatic", {"category": "complaint", "reply": "Sorry to hear that."}, "inbox"),
    ("a reply that breaks the rules", {"category": "thanks_or_praise",
                                       "reply": "Thanks! Game changer, see tinykv.dev #rust"}, "inbox"),
    ("a number the sources lack", {"reply": "About 900 lines, 0.8 ms p99."}, "inbox"),
    ("a sensitive comment", {"category": "thanks_or_praise", "reply": "Thanks, Kim.", "comment": {
        "comment_urn": "urn:li:comment:(urn:li:activity:1,3)", "post_urn": "urn:li:activity:1",
        "commenter": "Kim", "text": "Nice! What's your salary?"}}, "inbox"),
]


def test_the_baseline_policy_has_the_header_the_tests_edit():
    assert "- Owner: mkt-engage" in POLICY and "- Language:" not in POLICY
    assert with_language(POLICY, "pt-BR").splitlines()[2:4] == ["- Owner: mkt-engage", "- Language: pt-BR"]
    assert with_language(POLICY, "pt-BR").count("```engagement-policy") == 1


@pytest.mark.parametrize("tag", TAGS)
def test_every_decision_is_the_same_with_the_language_line(tmp_path, tag):
    plain = make_project(tmp_path / "plain", None)
    lang = make_project(tmp_path / "lang", tag)
    for label, kwargs, expected in CASES:
        a, b = decide(plain, **kwargs), decide(lang, **kwargs)
        assert a["decision"] == expected, (label, a["reasons"])
        assert without_hash(a) == without_hash(b), label
        assert a["policy_hash"] != b["policy_hash"], label


@pytest.mark.parametrize("tag", TAGS)
def test_the_policy_block_is_still_found_and_its_limits_are_read(tmp_path, tag):
    lang = make_project(tmp_path / "lang", tag)
    out = decide(lang, category="thanks_or_praise", reply="Thanks, Sam.")
    assert out["counts"] == {"auto_today": 0, "max_per_day": 2}
    # a policy file without the block still stops with the same error, with the line present
    path = lang / "docs/marketing/engagement-policy.md"
    path.write_text(path.read_text(encoding="utf-8").replace("```engagement-policy", "```json"), encoding="utf-8")
    r = policy_hash(lang)
    assert r.returncode == 2 and "has no ```engagement-policy block" in r.stderr and r.stdout == ""


@pytest.mark.parametrize("tag", TAGS)
def test_policy_hash_is_the_hash_of_the_whole_file_and_stable(tmp_path, tag):
    plain = make_project(tmp_path / "plain", None)
    lang = make_project(tmp_path / "lang", tag)
    first, second = policy_hash(lang), policy_hash(lang)
    assert first.returncode == second.returncode == 0 and first.stdout == second.stdout
    text = (lang / "docs/marketing/engagement-policy.md").read_text(encoding="utf-8")
    assert json.loads(first.stdout) == {"payload_hash": "policy:" + hashlib.sha256(text.encode("utf-8")).hexdigest()}
    assert policy_hash(plain).stdout != first.stdout, "the extra line is part of the hash, by design"
    assert policy_hash(plain).returncode == 0


@pytest.mark.parametrize("tag", TAGS)
def test_an_approval_of_the_policy_without_the_line_does_not_cover_the_policy_with_it(tmp_path, tag):
    # the hash binds the approval to the exact file: adding the line to an approved policy asks for a new approval
    stale = make_project(tmp_path / "stale", tag, bound_to=POLICY)
    out = decide(stale, category="thanks_or_praise", reply="Thanks, Sam.")
    assert out["decision"] == "inbox"
    assert out["reasons"] == ["no standing approval bound to this policy file (policy changed or never approved)"]
    # approved again, bound to the new hash: the same decision as before the line
    fresh = make_project(tmp_path / "fresh", tag)
    assert decide(fresh, category="thanks_or_praise", reply="Thanks, Sam.")["decision"] == "auto"


@pytest.mark.parametrize("tag", TAGS)
def test_the_log_and_the_daily_limit_work_the_same(tmp_path, tag):
    for name, t in (("plain", None), ("lang", tag)):
        root = make_project(tmp_path / name, t)
        log = root / "docs/marketing/engagement-log.jsonl"
        entry = root / "entry.json"
        entry.write_text(json.dumps({"action": "auto_replied", "comment_urn": "urn:li:comment:(urn:li:activity:9,1)",
                                     "post_urn": "urn:li:activity:9", "commenter": "Lee"}), encoding="utf-8")
        for _ in range(2):
            r = subprocess.run([sys.executable, str(GATE), "record", "--log", str(log), "--entry-file", str(entry)],
                               capture_output=True, text=True, cwd=root, timeout=60)
            assert r.returncode == 0, r.stderr
    outs = [decide(tmp_path / n, category="thanks_or_praise", reply="Thanks, Sam.") for n in ("plain", "lang")]
    assert outs[0]["decision"] == "inbox" and "daily limit reached (2/2)" in outs[0]["reasons"]
    assert without_hash(outs[0]) == without_hash(outs[1])
