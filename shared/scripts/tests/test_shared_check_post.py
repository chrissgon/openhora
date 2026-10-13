"""Tests for shared/scripts/check_post.py, which had none. Offline; every name and number below is fictional.

Run: uv run --with pytest pytest shared/scripts/tests
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys

import pytest

from shared_helpers import SOURCES, clean_usage_error, run

CHECK_POST = "check_post.py"
spec = importlib.util.spec_from_file_location("check_post_under_test", SOURCES / CHECK_POST)
check_post = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_post)

VOICE = '# Voice\n\n```voice-rules\n{"max_emojis": 0, "max_hashtags": 2, "end_with_question": true}\n```\n'
PROFILE = ('# Profile\n\n```sensitive-topics\n{"action": "never_reply_escalate_to_user", '
           '"topics": {"salary": {"keywords": ["salary"], "exclude": []}}}\n```\n')
POST = "One index made deletes 200 times faster.\nWhich one do you run?\n#databases"


def content(post=POST, comment="Write-up: tinykv.example/deletes", extra=""):
    text = f"# Post: deletes\n\n- Owner: mkt-social-copy\n\n## Post\n\n```post\n{post}\n```\n"
    if comment is not None:
        text += f"\n## First comment\n\n```first-comment\n{comment}\n```\n"
    return text + extra


@pytest.fixture()
def project(tmp_path):
    (tmp_path / "docs/brand").mkdir(parents=True)
    (tmp_path / "docs/marketing/content").mkdir(parents=True)
    (tmp_path / "docs/brand/voice.md").write_text(VOICE, encoding="utf-8")
    (tmp_path / "docs/brand/profile.md").write_text(PROFILE, encoding="utf-8")

    def check(text, *args):
        path = tmp_path / "docs/marketing/content/2026-10-05-deletes.md"
        path.write_text(text, encoding="utf-8")
        return run(CHECK_POST, "--content", str(path.relative_to(tmp_path)), *args, cwd=tmp_path)
    check.root = tmp_path
    return check


def test_a_good_post_passes_every_check(project):
    r = project(content())
    assert r.returncode == 0, r.stdout + r.stderr
    out = json.loads(r.stdout)
    assert out["ok"] is True and out["unchecked"] == [] and out["problems"] == []
    assert out["post"]["chars"] == len(POST) and out["post"]["lines"] == 3 and out["post"]["links"] == []
    assert out["post"]["voice"]["ok"] is True and out["post"]["sensitive"]["locked"] is False
    assert out["first_comment"]["links"] == ["tinykv.example/deletes"]


def test_a_content_file_without_one_closed_post_block_is_a_bad_file(project):
    for text, message in (("# Post\n\nno block here\n", "no ```post block"),
                          (content() + "\n```post\nagain\n```\n", "more than one ```post block"),
                          ("```post\nnever closed\n", "is not closed"),
                          ("```post\n```\n", "no ```post block")):
        r = project(text)
        assert clean_usage_error(r) and message in r.stderr, text
    assert clean_usage_error(run(CHECK_POST, "--content", str(project.root / "absent.md")))
    (project.root / "bytes.md").write_bytes(b"\xff\xfe```post\nx\n```\n")
    assert clean_usage_error(run(CHECK_POST, "--content", str(project.root / "bytes.md")))


def test_a_failed_check_is_a_problem_and_exit_1(project):
    r = project(content(post="We doubled every salary this year!\n#a #b #c"))
    assert r.returncode == 1
    out = json.loads(r.stdout)
    assert out["ok"] is False and out["unchecked"] == []
    assert any("voice" in p and "3 hashtags, limit 2" in p for p in out["problems"])
    assert any("sensitive topics" in p and "salary" in p for p in out["problems"])
    r = project(content(comment="Ask me about my salary: tinykv.example"))
    assert r.returncode == 1 and json.loads(r.stdout)["problems"] == ["first comment: sensitive topics {'salary': ['salary']}"]


def test_a_check_that_cannot_run_is_unchecked_and_never_a_pass(project):
    (project.root / "docs/brand/voice.md").unlink()
    r = project(content(comment=None))
    out = json.loads(r.stdout)
    assert r.returncode == 1 and out["ok"] is False and out["problems"] == [] and out["first_comment"] is None
    assert out["unchecked"] == ["post: docs/brand/voice.md not found"]
    r = project(content(), "--voice", "docs/brand/voice.md", "--profile", "docs/brand/absent.md")
    assert sorted(json.loads(r.stdout)["unchecked"]) == [
        "first comment: docs/brand/absent.md not found", "post: docs/brand/absent.md not found",
        "post: docs/brand/voice.md not found"]


def test_the_two_scripts_are_found_next_to_this_one_first_then_in_a_skills_folder(tmp_path, project):
    """A skill carries generated copies of the scripts it calls, in its own scripts folder."""
    alone = tmp_path / "skill" / "scripts"
    alone.mkdir(parents=True)
    shutil.copy(SOURCES / CHECK_POST, alone / CHECK_POST)
    path = project.root / "docs/marketing/content/2026-10-05-deletes.md"
    path.write_text(content(), encoding="utf-8")

    def check(*args):
        r = subprocess.run([sys.executable, str(alone / CHECK_POST), "--content", str(path), *args],
                           capture_output=True, text=True, cwd=project.root, timeout=60)
        return r.returncode, json.loads(r.stdout)
    code, out = check()
    assert code == 1 and sorted(out["unchecked"]) == [
        "first comment: sensitive_topics.py not installed", "post: sensitive_topics.py not installed",
        "post: voice_stats.py not installed"]
    # The older layout: each script in the skill that owns it, under a skills folder.
    skills = tmp_path / "installed"
    for skill, script in (("brand-voice", "voice_stats.py"), ("brand-profile", "sensitive_topics.py")):
        (skills / skill / "scripts").mkdir(parents=True)
        shutil.copy(SOURCES / script, skills / skill / "scripts" / script)
    assert check("--skills-dir", str(skills)) == (0, check("--skills-dir", str(skills))[1])
    # Copies beside the script win over the skills folder: a broken one beside it is the one that runs.
    (alone / "voice_stats.py").write_text("import sys\nsys.exit(7)\n", encoding="utf-8")
    shutil.copy(SOURCES / "sensitive_topics.py", alone / "sensitive_topics.py")
    code, out = check("--skills-dir", str(skills))
    assert code == 1 and [u.strip() for u in out["unchecked"]] == ["post: voice_stats.py exited 7:"]
    shutil.copy(SOURCES / "voice_stats.py", alone / "voice_stats.py")
    assert check()[0] == 0


@pytest.mark.parametrize("text, found", [
    ("see short.example/x today", ["short.example/x"]),
    ("the course is at bit.ly/priya-course.", ["bit.ly/priya-course"]),
    ("read https://tinykv.example/docs, then reply", ["https://tinykv.example/docs"]),
    ("www.tinykv.example has it", ["www.tinykv.example"]),
    ("tinykv.dev is live, and so is tinykv.com.br", ["tinykv.dev", "tinykv.com.br"]),
    ("docs.tinykv.io/guide (new)", ["docs.tinykv.io/guide"]),
    ("open notes.md and run payload.py with node.js", []),
    ("version 1.2 costs 3.50/month, e.g. for a team", []),
    ("write to dana@tinykv.dev", []),
    ("no link at all", []),
])
def test_one_link_pattern(text, found):
    """The pattern knew seven endings and no host with a path, so a shortened address was not a link here
    while the reply gate of another skill counted it."""
    assert check_post.links(text) == found


def test_no_body_links_makes_a_link_in_the_post_a_problem_and_never_one_in_the_first_comment(project):
    with_link = content(post="The write-up is at tinykv.example/deletes\nWhich index do you run?")
    r = project(with_link)
    assert r.returncode == 0 and json.loads(r.stdout)["post"]["links"] == ["tinykv.example/deletes"]
    r = project(with_link, "--no-body-links")
    out = json.loads(r.stdout)
    assert r.returncode == 1 and out["ok"] is False
    assert out["problems"] == ["post: links in the body ['tinykv.example/deletes']; they go in the first comment"]
    assert project(content(), "--no-body-links").returncode == 0  # the link is in the first comment


def test_help_and_usage_errors():
    r = run(CHECK_POST, "--help")
    assert r.returncode == 0 and "--no-body-links" in r.stdout
    assert clean_usage_error(run(CHECK_POST))
    assert clean_usage_error(run(CHECK_POST, "--content"))
    assert clean_usage_error(run(CHECK_POST, "--content", "x.md", "--nope"))


# --platform-file: the caption limits of a platform's data file.

def platform_file(root, post, name="social.json"):
    path = root / name
    path.write_text(json.dumps({"platform": "social", "post": post}), encoding="utf-8")
    return str(path)


NO_VOICE_LIMITS = '# Voice\n\n```voice-rules\n{"max_emojis": 5}\n```\n'


def test_the_caption_limits_come_from_the_platform_file(project):
    (project.root / "docs/brand/voice.md").write_text(NO_VOICE_LIMITS, encoding="utf-8")
    limits = platform_file(project.root, {"max_characters": 40, "max_hashtags": 2, "max_mentions": 1,
                                          "first_comment": {"supported": True, "max_characters": 30}})
    fine = content(post="Short caption.\n#a #b @dana", comment="tinykv.example/x")
    r = project(fine, "--platform-file", limits)
    out = json.loads(r.stdout)
    assert r.returncode == 0, r.stdout
    assert out["post"]["length"] == len("Short caption.\n#a #b @dana") and out["post"]["unit"] == "characters"
    assert out["post"]["hashtags"] == 2 and out["post"]["mentions"] == ["@dana"]
    r = project(content(post="x" * 41, comment="y" * 31), "--platform-file", limits)
    out = json.loads(r.stdout)
    assert r.returncode == 1 and out["problems"] == ["post: 41 characters, limit 40",
                                                     "first comment: 31 characters, limit 30"]
    r = project(content(post="Hi\n#a #b #c @dana @ana", comment=None), "--platform-file", limits)
    assert json.loads(r.stdout)["problems"] == ["post: 3 hashtags, limit 2", "post: 2 mentions, limit 1"]


def test_the_limit_is_the_limit_itself_not_one_less(project):
    (project.root / "docs/brand/voice.md").write_text(NO_VOICE_LIMITS, encoding="utf-8")
    limits = platform_file(project.root, {"max_characters": 10, "max_hashtags": 1, "max_mentions": 1})
    assert project(content(post="x" * 7 + " #a", comment=None), "--platform-file", limits).returncode == 0
    assert project(content(post="x" * 8 + " #a", comment=None), "--platform-file", limits).returncode == 1


def test_a_null_or_missing_limit_is_not_checked(project):
    (project.root / "docs/brand/voice.md").write_text(NO_VOICE_LIMITS, encoding="utf-8")
    for post in ({"max_characters": None, "max_hashtags": None, "max_mentions": None, "first_comment": None},
                 {"unit": None}, {}):
        limits = platform_file(project.root, post)
        r = project(content(post="x" * 5000 + "\n" + " ".join(f"#t{i}" for i in range(60)), comment="y" * 5000),
                    "--platform-file", limits)
        assert r.returncode == 0, r.stdout
        assert json.loads(r.stdout)["post"]["hashtags"] == 60


def test_the_unit_utf_16_counts_code_units_and_the_default_counts_characters(project):
    """TikTok's limit counts UTF-16 code units: a character outside the basic plane is two of them."""
    (project.root / "docs/brand/voice.md").write_text(NO_VOICE_LIMITS, encoding="utf-8")
    post = "ab\U0001F600\U0001F600"  # 4 characters, 6 UTF-16 code units
    chars = platform_file(project.root, {"max_characters": 5}, "chars.json")
    units = platform_file(project.root, {"max_characters": 5, "unit": "utf-16"}, "units.json")
    r = project(content(post=post, comment=None), "--platform-file", chars)
    assert r.returncode == 0 and json.loads(r.stdout)["post"]["length"] == 4
    r = project(content(post=post, comment=None), "--platform-file", units)
    out = json.loads(r.stdout)
    assert r.returncode == 1 and out["post"]["length"] == 6 and out["post"]["unit"] == "utf-16"
    assert out["problems"] == ["post: 6 UTF-16 code units, limit 5"]


def test_hashtags_and_mentions_are_counted_by_one_pattern():
    assert check_post.hashtags("a #one #Two_2 #3 end # x #") == ["#one", "#Two_2", "#3"]
    assert check_post.hashtags("see tinykv.example/x#top and a&#38;b and ##double") == []
    assert check_post.mentions("thanks @dana.example and @ana, mail dana@tinykv.dev or @x.") == ["@dana.example", "@ana", "@x"]
    assert check_post.mentions("no one here, 5 @ 3") == []


def test_a_platform_without_a_first_comment_refuses_one(project):
    (project.root / "docs/brand/voice.md").write_text(NO_VOICE_LIMITS, encoding="utf-8")
    limits = platform_file(project.root, {"first_comment": {"supported": False}})
    r = project(content(), "--platform-file", limits)
    assert r.returncode == 1 and json.loads(r.stdout)["problems"] == ["first comment: the platform has none"]
    assert project(content(comment=None), "--platform-file", limits).returncode == 0


def test_without_the_flag_the_output_is_what_it_was(project):
    out = json.loads(project(content()).stdout)
    assert set(out["post"]) == {"chars", "lines", "links", "voice", "sensitive"}


def test_a_post_file_with_a_script_block_gives_its_post_block_only():
    text = content(extra="\n```script\nbeat: 1\nline: Hello.\n```\n")
    assert check_post.blocks(text) == {"post": POST, "first-comment": "Write-up: tinykv.example/deletes"}


def test_a_bad_platform_file_is_a_usage_error(project, tmp_path):
    bad = {"not json": "{", "no post": "{}", "post is a list": '{"post": []}',
           "limit is text": '{"post": {"max_characters": "40"}}', "negative": '{"post": {"max_hashtags": -1}}',
           "bool": '{"post": {"max_mentions": true}}', "unit is a number": '{"post": {"unit": 16}}'}
    for label, body in bad.items():
        path = tmp_path / "bad.json"
        path.write_text(body, encoding="utf-8")
        r = project(content(), "--platform-file", str(path))
        assert clean_usage_error(r) and ("platform data file" in r.stderr or "post." in r.stderr), label
    assert clean_usage_error(project(content(), "--platform-file", str(tmp_path / "absent.json")))


def test_the_real_data_files_load():
    for data in sorted((SOURCES.parent / "references/platforms").glob("*.json")):
        limits = check_post.load_limits(str(data))
        assert limits["unit"] in ("characters", "utf-16")
