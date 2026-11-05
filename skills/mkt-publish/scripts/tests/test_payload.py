"""Offline tests of skills/mkt-publish/scripts/payload.py: build, verify, the optional post image, the durable
payload folder, a plan hash that does not depend on where the folder lives or how the platform is spelled, the
platform's rules read from its data file, and the publisher's path taken from the caller, never built."""
import hashlib
import os
import re
import json
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
PAYLOAD = REPO / "skills/mkt-publish/scripts/payload.py"
DATA = REPO / "shared/references/platforms/linkedin.json"
PUBLISHER = REPO / "providers/publisher/linkedin.py"
re_hash = re.compile(r"\| plan \| [^|]+ \| ([0-9a-f]{64}) \|")
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64

CONTENT = """# Post: launch

- Slot: 2026-10-12T09:00:00-03:00 · Small tools · EN
- Approval: {scope}
{image}
```post
tinykv 0.5 ships TTL with zero dependencies. What would you cut next?
```

```first-comment
https://example.com/tinykv
```
"""


@pytest.fixture
def proj(tmp_path):
    (tmp_path / "content").mkdir()
    (tmp_path / "out").mkdir()
    return tmp_path


def write(proj, name="2026-10-12-tinykv", scope="action", image=""):
    f = proj / "content" / f"{name}.md"
    f.write_text(CONTENT.format(scope=scope, image=image), encoding="utf-8")
    return f


def run(proj, *args):
    r = subprocess.run([sys.executable, str(PAYLOAD), *map(str, args)], capture_output=True, text=True, cwd=proj, timeout=60)
    return r.returncode, (json.loads(r.stdout) if r.stdout.strip() else None), r.stderr


PLATFORM = ("--platform", "linkedin", "--platform-file", DATA)
WHERE = ("--publisher", PUBLISHER, "--workbench", REPO)


def build(proj, *content, out="out", platform=PLATFORM, where=WHERE):
    folder = ["--out", proj / out] if out else []
    return run(proj, "build", *[x for c in content for x in ("--content", c)], *folder, *platform, *where)


def verify(proj, out, *extra):
    return run(proj, "verify", "--manifest", out["manifest"], "--hash", out["plan_hash"], *WHERE, *extra)


def git_init(proj):
    subprocess.run(["git", "init", "-q", str(proj)], check=True, timeout=60)


def test_a_post_without_an_image_has_no_media(proj):
    code, out, err = build(proj, write(proj))
    assert code == 0, err
    job = json.loads(Path(out["posts"][0]["job_file"]).read_text())
    assert "--media" not in job["argv"] and "image_file" not in out["posts"][0]


def test_the_image_is_copied_hashed_attached_and_snapshotted(proj):
    (proj / "card.png").write_bytes(PNG)
    code, out, err = build(proj, write(proj, image="- Image: card.png"))
    assert code == 0, err
    e = out["posts"][0]
    job = json.loads(Path(e["job_file"]).read_text())
    copy = job["argv"][job["argv"].index("--media") + 1]
    assert copy == e["image_file"] and Path(copy).parent == proj / "out" / "2026-10-12-tinykv"
    assert copy in job["snapshot"] and Path(copy).read_bytes() == PNG
    assert e["image_source"] == "card.png"


def test_a_changed_image_fails_verification(proj):
    (proj / "card.png").write_bytes(PNG)
    code, out, err = build(proj, write(proj, image="- Image: card.png"))
    code, v, _ = verify(proj, out)
    assert code == 0 and v["ok"]
    Path(out["posts"][0]["image_file"]).write_bytes(PNG + b"x")
    code, v, _ = verify(proj, out)
    assert code == 1 and any("image.png changed" in p for p in v["problems"])


@pytest.mark.parametrize("name,data,message", [
    ("card.webp", PNG, "only .png"),
    ("card.png", b"<svg/>", "not a PNG"),
    ("missing.png", None, "not found"),
])
def test_a_bad_image_is_refused(proj, name, data, message):
    if data is not None:
        (proj / name).write_bytes(data)
    code, out, err = build(proj, write(proj, image=f"- Image: {name}"))
    assert code == 2 and message in err


def test_two_image_lines_are_refused(proj):
    (proj / "card.png").write_bytes(PNG)
    code, out, err = build(proj, write(proj, image="- Image: card.png\n- Image: card.png"))
    assert code == 2 and "at most one" in err


def test_without_out_the_payload_goes_to_a_private_durable_folder_named_by_the_first_slot(proj):
    code, out, err = build(proj, write(proj), out=None)
    assert code == 0, err
    folder = proj.resolve() / ".workbench-local" / "payloads" / "2026-10-12"
    assert Path(out["out"]) == folder and Path(out["manifest"]) == folder / "manifest.json"
    for d in (folder, folder.parent, folder.parent.parent):
        assert stat.S_IMODE(d.stat().st_mode) == 0o700
    assert out["git_ignored"] is None  # not a git repository: nothing can commit it
    code, second, err = build(proj, write(proj), out=None)
    assert code == 0 and Path(second["out"]) == folder.with_name("2026-10-12-2")
    assert second["plan_hash"] == out["plan_hash"]


def test_in_a_git_repository_the_payload_folder_must_be_ignored(proj):
    git_init(proj)
    code, out, err = build(proj, write(proj), out=None)
    assert code == 2 and "not git-ignored" in err and ".gitignore" in err
    assert not (proj / ".workbench-local").exists()
    (proj / ".gitignore").write_text(".workbench-local/\n")
    code, out, err = build(proj, write(proj), out=None)
    assert code == 0 and out["git_ignored"] is True, err


def test_the_manifest_holds_no_absolute_path_and_the_hash_survives_a_move(proj):
    (proj / "card.png").write_bytes(PNG)
    code, out, err = build(proj, write(proj, image="- Image: card.png"))
    assert code == 0, err
    text = Path(out["manifest"]).read_text()
    assert str(proj.resolve()) not in text and str(REPO) not in text
    assert out["plan_hash"] == hashlib.sha256(text.encode()).hexdigest()
    code, other, err = build(proj, write(proj, image="- Image: card.png"), out="elsewhere")
    assert code == 0 and other["plan_hash"] == out["plan_hash"], err

    shutil.move(str(proj / "out"), str(proj / "moved"))
    moved = dict(out, manifest=str(proj / "moved" / "manifest.json"))
    code, v, _ = verify(proj, moved)
    assert code == 1 and all("job.json" in p for p in v["problems"])  # the jobs still name the old place
    code, j, err = run(proj, "jobs", "--manifest", moved["manifest"], *WHERE)
    assert code == 0 and j["plan_hash"] == out["plan_hash"], err
    job = json.loads(Path(j["posts"][0]["job_file"]).read_text())
    assert str((proj / "moved").resolve()) in job["argv"][job["argv"].index("--text-file") + 1]
    code, v, _ = verify(proj, moved)
    assert code == 0 and v["ok"] and v["manifest_version"] == 2


def test_a_changed_job_or_another_workbench_fails_verification(proj):
    code, out, err = build(proj, write(proj))
    job_file = Path(out["posts"][0]["job_file"])
    job = json.loads(job_file.read_text())
    job["argv"][2] = str(proj / "other.py")
    job_file.write_text(json.dumps(job))
    code, v, _ = verify(proj, out)
    assert code == 1 and any("job.json" in p for p in v["problems"])
    code, out, err = build(proj, write(proj), out="second")
    code, v, _ = run(proj, "verify", "--manifest", out["manifest"], "--hash", out["plan_hash"],
                     "--publisher", PUBLISHER, "--workbench", proj)
    assert code == 1 and any("job.json" in p for p in v["problems"])
    other = proj / "providers" / "publisher" / "other.py"
    other.parent.mkdir(parents=True)
    other.write_text("")
    code, v, _ = run(proj, "verify", "--manifest", out["manifest"], "--hash", out["plan_hash"],
                     "--publisher", other, "--workbench", REPO)
    assert code == 1 and any("job.json" in p for p in v["problems"])
    code, v, err = run(proj, "verify", "--manifest", out["manifest"], "--hash", out["plan_hash"])
    assert code == 2 and "--publisher" in err and "--workbench" in err


def test_a_manifest_from_before_the_version_keeps_its_hash_and_is_checked_the_old_way(proj):
    d = proj / "out" / "2026-10-12-tinykv"
    d.mkdir()
    (d / "post.txt").write_text("old post\n")
    (d / "job.json").write_text('{"argv": ["uv"]}\n')
    sha = lambda f: hashlib.sha256(f.read_bytes()).hexdigest()
    manifest = proj / "out" / "manifest.json"
    manifest.write_text(json.dumps({"platform": "linkedin", "posts": [{
        "key": d.name, "post_file": str(d / "post.txt"), "post_sha256": sha(d / "post.txt"),
        "job_file": str(d / "job.json"), "job_sha256": sha(d / "job.json")}]}))
    code, v, err = run(proj, "verify", "--manifest", manifest, "--hash", sha(manifest))
    assert code == 0 and v["ok"] and v["manifest_version"] == 1, err
    (d / "job.json").write_text('{"argv": ["sh"]}\n')
    code, v, _ = run(proj, "verify", "--manifest", manifest, "--hash", sha(manifest))
    assert code == 1 and any("job.json changed" in p for p in v["problems"])
    code, _, err = run(proj, "jobs", "--manifest", manifest, *WHERE)
    assert code == 2 and "build a new payload" in err


# --- the platform: one name, its rules from its data file (FR-M8, FR-I9) ----------------------------------


def test_two_spellings_of_one_platform_give_one_plan_hash(proj):
    code, out, err = build(proj, write(proj))
    assert code == 0, err
    spelled = ("--platform", " LinkedIn ", "--platform-file", DATA)
    code, other, err = build(proj, write(proj), out="second", platform=spelled)
    assert code == 0, err
    assert other["plan_hash"] == out["plan_hash"] and other["platform"] == "linkedin"
    job = json.loads(Path(other["posts"][0]["job_file"]).read_text())
    assert job["argv"][job["argv"].index("--platform") + 1] == "linkedin"


@pytest.mark.parametrize("platform,message", [
    (("--platform", "mastodon", "--platform-file", DATA), "data file of 'linkedin', not of 'mastodon'"),
    (("--platform", "linked in", "--platform-file", DATA), "is not a platform name"),
    (("--platform", "linkedin", "--platform-file", "missing.json"), "--platform-file"),
])
def test_a_platform_without_its_data_file_is_refused(proj, platform, message):
    code, out, err = build(proj, write(proj), platform=platform)
    assert code == 2 and message in err and out is None
    assert not any((proj / "out").iterdir())


def test_the_platform_is_required(proj):
    code, out, err = build(proj, write(proj), platform=())
    assert code == 2 and "--platform" in err


def test_a_data_file_that_is_not_one_is_refused(proj):
    (proj / "bad.json").write_text('{"platform": "linkedin"}')
    code, out, err = build(proj, write(proj), platform=("--platform", "linkedin", "--platform-file", proj / "bad.json"))
    assert code == 2 and "not a platform data file" in err


def custom_data(proj, **changes):
    d = json.loads(DATA.read_text())
    d["platform"] = "demo-net"
    for path, value in changes.items():
        node = d
        keys = path.split("__")
        for k in keys[:-1]:
            node = node[k]
        node[keys[-1]] = value
    f = proj / "demo-net.json"
    f.write_text(json.dumps(d))
    return ("--platform", "demo-net", "--platform-file", f)


def test_the_limits_come_from_the_data_file(proj):
    code, out, err = build(proj, write(proj), platform=custom_data(proj, post__max_characters=20))
    assert code == 2 and "more than 20" in err
    code, out, err = build(proj, write(proj), platform=custom_data(proj, post__first_comment__max_characters=10))
    assert code == 2 and "first comment" in err and "more than 10" in err
    code, out, err = build(proj, write(proj), platform=custom_data(proj, post__first_comment__supported=False))
    assert code == 2 and "no first comment" in err
    (proj / "card.png").write_bytes(PNG)
    code, out, err = build(proj, write(proj, image="- Image: card.png"), platform=custom_data(proj, media__max_bytes=10))
    assert code == 2 and "more than 10" in err
    code, out, err = build(proj, write(proj, image="- Image: card.png"), platform=custom_data(proj, media__max_count=0))
    assert code == 2 and "no image" in err


def test_a_platform_whose_post_needs_no_text_takes_an_image_alone(proj):
    (proj / "card.png").write_bytes(PNG)
    f = proj / "content" / "2026-10-12-image.md"
    f.write_text("# Post\n\n- Slot: 2026-10-12T09:00:00-03:00\n- Approval: plan\n- Image: card.png\n\n```post\n```\n")
    code, out, err = build(proj, f)
    assert code == 2 and "needs text" in err
    code, out, err = build(proj, f, out="second", platform=custom_data(proj, post__requires_text=False))
    assert code == 0, err
    assert out["posts"][0]["post_chars"] == 0 and "image_file" in out["posts"][0]


def test_without_a_data_file_a_text_post_builds_and_an_image_is_refused(proj):
    code, out, err = build(proj, write(proj), platform=("--platform", "linkedin"))
    assert code == 0 and "no --platform-file" in err
    (proj / "card.png").write_bytes(PNG)
    code, out, err = build(proj, write(proj, image="- Image: card.png"), out="second", platform=("--platform", "linkedin"))
    assert code == 2 and "needs --platform-file" in err


# --- the publisher's path comes from the caller (default 68) -----------------------------------------------


def test_the_job_runs_the_publisher_the_caller_names_and_its_secret_resolver(proj, tmp_path):
    wb = tmp_path / "elsewhere"
    publisher = wb / "providers" / "publisher" / "impl.py"
    publisher.parent.mkdir(parents=True)
    publisher.write_text("")
    (wb / "providers" / "secrets").mkdir()
    (wb / "providers" / "secrets" / "resolver.py").write_text("")
    code, out, err = build(proj, write(proj), where=("--publisher", publisher, "--workbench", REPO))
    assert code == 0 and out["missing_providers"] == [], err
    job = json.loads(Path(out["posts"][0]["job_file"]).read_text())
    assert job["argv"][:3] == ["uv", "run", str(publisher.resolve())]
    assert str((wb / "providers" / "secrets" / "resolver.py").resolve()) in job["snapshot"]
    assert job["cwd"] == str(REPO)
    code, out, err = build(proj, write(proj), out="second", where=("--publisher", wb / "nope.py", "--workbench", REPO))
    assert code == 2 and "--publisher" in err


def test_without_a_publisher_no_job_is_written_until_jobs_is_run(proj):
    code, out, err = build(proj, write(proj), where=("--workbench", REPO))
    assert code == 0 and out["jobs_written"] is False and "no --publisher" in err
    job_file = Path(out["posts"][0]["job_file"])
    assert not job_file.exists()
    code, v, _ = verify(proj, out)
    assert code == 1 and any("job.json" in p for p in v["problems"])
    code, j, err = run(proj, "jobs", "--manifest", out["manifest"], *WHERE)
    assert code == 0 and j["plan_hash"] == out["plan_hash"], err
    code, v, _ = verify(proj, out)
    assert code == 0 and v["ok"]


def test_a_manifest_that_is_not_json_is_a_problem_not_a_traceback(proj):
    (proj / "out" / "manifest.json").write_text("{not json")
    code, v, err = run(proj, "verify", "--manifest", proj / "out" / "manifest.json", "--hash", "0" * 64, *WHERE)
    assert code == 1 and v["ok"] is False and any("not a readable manifest" in p for p in v["problems"])
    assert "Traceback" not in err


def test_a_git_check_that_cannot_answer_is_a_refusal(proj, tmp_path):
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "git").write_text('#!/bin/sh\ncase "$3" in rev-parse) echo /x; exit 0;; *) echo broken >&2; exit 128;; esac\n')
    (fake / "git").chmod(0o755)
    env = dict(os.environ, PATH=f"{fake}{os.pathsep}{os.environ['PATH']}")
    args = [sys.executable, str(PAYLOAD), "build", "--content", str(write(proj)), *map(str, PLATFORM), *map(str, WHERE)]
    r = subprocess.run(args, capture_output=True, text=True, cwd=proj, timeout=60, env=env)
    assert r.returncode == 2 and "check-ignore exited 128" in r.stderr and r.stdout == ""
    assert not (proj / ".workbench-local").exists()


def test_the_recorded_approval_of_the_eval_fixture_is_the_hash_its_files_build(tmp_path):
    """Case 3 of evals.json schedules under an approval already recorded: its hash must be what the fixture builds."""
    fixture = REPO / "skills/mkt-publish/evals/files/dana-publish-approved"
    work = tmp_path / "p"
    shutil.copytree(fixture, work)
    recorded = re_hash.search((fixture / "docs/workbench/state.md").read_text()).group(1)
    code, out, err = run(work, "build", "--content", "docs/marketing/content/2038-10-11-tinykv-05-ttl.md",
                         "--content", "docs/marketing/content/2038-10-13-fsync-budget.md", *PLATFORM,
                         "--publisher", work / "wb/providers/publisher/stub.py", "--workbench", work / "wb",
                         "--out", tmp_path / "out")
    assert code == 0 and out["plan_hash"] == recorded, err
    cases = (REPO / "skills/mkt-publish/evals/evals.json").read_text()
    assert recorded[:12] in cases
