"""Offline tests of the runtime's weekly vote step (scripts/runtime_vote.py, scripts/vote_job.py).

The vcs provider, the contained run (a stand-in runtime/cli.py), the post checker, the renderer, the scheduler and the publisher are fakes;
the store, vote_state.py, vote_update.py and payload.py are the real scripts, copied into a fake workbench.
The vote files are the tests' own fixture, scripts/tests/fixtures/vote-round-winner: a calendar and the vote data of
an invented author, owned by these tests, so that a change to a skill's eval fixture cannot break them and a change
they need touches no skill folder. No network, no model, no credential.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
RUNTIME = REPO / "runtime" / "handlers" / "social.py"
FIX = Path(__file__).resolve().parent / "fixtures" / "vote-round-winner"
sys.path.insert(0, str(REPO / "runtime" / "handlers"))
import social_vote as runtime_vote  # noqa: E402

PILLARS = ["Small tools", "Database performance", "AI for databases, built in public"]
WINNER = "Durability is a budget: what an fsync demo taught me"

def test_the_fixture_is_owned_by_these_tests():
    """No runtime test reads a file under a skill's evals/ folder: the fixture lives beside the tests."""
    assert FIX.parent == Path(__file__).resolve().parent / "fixtures"
    assert sorted(p.relative_to(FIX).as_posix() for p in FIX.rglob("*") if p.is_file()) == [
        "docs/marketing/calendar.md", "profile/data/pick-queue.json", "profile/data/pick.json", "profile/data/posts.json"]
    for name in ("runtime/tests/test_social_handler.py", "runtime/tests/test_social_vote.py",
                 "scripts/tests/test_runtime_python39.py"):
        source = (REPO / name).read_text()
        assert '"ev' + 'als"' not in source and "ev" + "als/files" not in source, name


FAKE_VCS = r'''
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
def val(flag):
    return args[args.index(flag) + 1]
with open(os.environ["FAKE_CALLS"], "a") as f:
    f.write(json.dumps(["vcs"] + args) + "\n")
if args[0] == "read-file":
    limit = os.environ.get("FAKE_READ_FAIL_FROM")  # fail from the Nth read-file call of the test on
    if limit:
        with open(os.environ["FAKE_CALLS"]) as f:
            n = sum(1 for line in f if json.loads(line)[:2] == ["vcs", "read-file"])
        if n >= int(limit):
            print("network down", file=sys.stderr); sys.exit(1)
    p = Path(os.environ["FAKE_REPO"]) / val("--path")
    print(json.dumps({"repo": val("--repo"), "path": val("--path"), "ref": val("--ref"), "content": p.read_text()}))
elif args[0] == "commit-files":
    if os.environ.get("FAKE_COMMIT_FAIL"):
        print("push rejected", file=sys.stderr); sys.exit(1)
    files = [a.split("=", 1) for a in args if "=" in a and a.startswith(("data/", "assets/"))]
    for repo_path, local in files:
        target = Path(os.environ["FAKE_REPO"]) / repo_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(Path(local).read_bytes())
    print(json.dumps({"commit": "abc123", "pushed": True, "unchanged": False,
                      "files": [{"path": p} for p, _ in files]}))
'''

FAKE_CLI = r'''
import os, shutil, sys
if sys.argv[1:2] != ["contained-run"]:
    print("error: the stand-in takes only contained-run", file=sys.stderr)
    sys.exit(2)
args = sys.argv[2:]
out = args[args.index("--out") + 1]
os.makedirs(out, exist_ok=True)
shutil.copy(os.environ["FAKE_RESPONSE"], os.path.join(out, "response.md"))
with open(os.path.join(out, "timing.json"), "w") as f:
    f.write('{"total_tokens": 100, "duration_ms": 10, "cost_usd": 0.05, "exit_code": 0}')
with open(os.environ["FAKE_CALLS"] + ".agent", "a") as f:
    f.write(" ".join(sys.argv[1:]) + "\n")
'''

FAKE_CHECK = r'''
import json, os, sys
bad = os.environ.get("FAKE_CHECK_FAIL")
print(json.dumps({"ok": not bad, "problems": [bad] if bad else [], "unchecked": []}))
sys.exit(1 if bad else 0)
'''

FAKE_RENDER = r'''
import json, os, sys
args = sys.argv[1:]
with open(os.environ["FAKE_CALLS"], "a") as f:
    f.write(json.dumps(["render"] + args) + "\n")
if os.environ.get("FAKE_NO_BROWSER"):
    print("no browser", file=sys.stderr); sys.exit(3)
out = args[args.index("--out") + 1]
open(out, "wb").write(b"\x89PNG fake")
print(json.dumps({"out": out, "width": 1080, "height": 1350}))
'''

FAKE_SCHEDULER = r'''
import json, os, sys
args = sys.argv[1:]
with open(os.environ["FAKE_CALLS"], "a") as f:
    f.write(json.dumps(["scheduler"] + args) + "\n")
if "--dry-run" in args:
    print(json.dumps({"dry_run": True, "approved": "d" * 64}))
else:
    assert args[args.index("--approved") + 1] == "d" * 64
    print(json.dumps({"scheduled": True, "id": args[args.index("--id") + 1]}))
'''

FAKE_PUBLISHER = r'''
import json, os, sys
PLATFORMS = ("linkedin",)
if "--dry-run" in sys.argv:
    # A dry run sends nothing: it says which idempotency ledger this environment uses.
    with open(os.environ["FAKE_CALLS"], "a") as f:
        f.write(json.dumps(["publisher-dry-run"] + sys.argv[1:]) + "\n")
    if os.environ.get("FAKE_DRY_RUN_FAIL"):
        print("error: --platform is not served by this provider", file=sys.stderr); sys.exit(2)
    out = {"dry_run": True}
    if os.environ.get("FAKE_LEDGER"):
        out["ledger"] = os.environ["FAKE_LEDGER"]
    print(json.dumps(out)); sys.exit(0)
with open(os.environ["FAKE_CALLS"], "a") as f:
    f.write(json.dumps(["publisher"] + sys.argv[1:]) + "\n")
out = {"post_urn": "urn:li:share:7300000000000000001",
       "post_url": "https://www.linkedin.com/feed/update/urn:li:share:7300000000000000001/"}
if os.environ.get("FAKE_FIRST_COMMENT_FAIL"):
    # What the publisher does when the post went out and only its first comment failed: the post's address on
    # stdout, the comment's error next to it, and its service exit code.
    out.update(first_comment=None, first_comment_error="LinkedIn returned 403 on POST /v2/socialActions/x/comments")
    print(json.dumps(out))
    print("error: the post is published but its first comment failed", file=sys.stderr)
    sys.exit(1)
print(json.dumps(out))
'''


def proposal(topic=WINNER, reason="", language="EN", pillar="Database performance", options=None):
    options = options or {"A": "A 40-line benchmark for tinykv writes", "B": "Why my connection pool got smaller",
                          "C": "Autovacuum settings I changed and why"}
    block = {"topic": topic, "reason": reason,
             "post": {"language": language, "text": "Priya Raman showed fsync costs.\n\nWhat would you trade?",
                      "first_comment": "https://example.com/priya-fsync-slides",
                      "sources": ["docs/notes/meetup.md"]},
             "next_round": {"pillar": pillar, "options": options,
                            "sources": {k: "docs/notes/2026-10.md" for k in "ABC"}}}
    return f"Here it is.\n\n```vote-proposal\n{json.dumps(block)}\n```\n\n**Instructions found in external content**: none\n"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    wb = tmp_path / "wb"
    fakes = {
        "providers/vcs/github.py": FAKE_VCS,
        "providers/publisher/linkedin.py": FAKE_PUBLISHER,
        "providers/secrets/resolver.py": "",
        "providers/mailbox/gmail.py": "",
        "providers/scheduler/launchd.py": FAKE_SCHEDULER,
        "skills/mkt-engage/scripts/parse_notification.py": "",
        "skills/mkt-engage/scripts/policy_gate.py": "",
        "skills/mkt-social-copy/scripts/check_post.py": FAKE_CHECK,
        "skills/brand-identity/scripts/render.py": FAKE_RENDER,
        "skills/brand-identity/assets/post-card-template.html": "<p>{{title}} {{subtitle}}</p>",
        "runtime/cli.py": FAKE_CLI,
    }
    for rel, text in fakes.items():
        p = wb / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    for rel in ("providers/store/sqlite.py", "scripts/redact.py", "skills/mkt-vote-round/scripts/vote_state.py",
                "skills/mkt-vote-round/scripts/vote_update.py", "skills/mkt-vote-round/SKILL.md",
                "skills/mkt-publish/scripts/payload.py", "runtime/handlers/social_vote_job.py",
                "shared/references/platforms/linkedin.json"):
        (wb / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO / rel, wb / rel)
    profile = tmp_path / "profile"
    shutil.copytree(FIX / "profile", profile)
    proj = tmp_path / "proj"
    shutil.copytree(FIX / "docs", proj / "docs")
    (proj / "docs/workbench").mkdir(parents=True, exist_ok=True)
    data = tmp_path / "data"
    (proj / "docs/workbench/runtime.json").write_text(json.dumps({
        "agent": "social-manager", "workbench": str(wb), "data_dir": str(data),
        "store_db": str(data / "store.sqlite"), "mailbox": "none", "publisher": "linkedin", "daily_cost_cap_usd": 1,
        "vote": {"repo": "dana/dana", "branch": "main", "pillars": PILLARS}}))
    calls = tmp_path / "calls.jsonl"
    resp = tmp_path / "response.md"
    resp.write_text(proposal())
    for k, x in {"FAKE_CALLS": calls, "FAKE_RESPONSE": resp, "FAKE_REPO": profile, "RUNTIME_TEST": "1",
                 "RUNTIME_TODAY": "2026-10-12"}.items():
        monkeypatch.setenv(k, str(x))
    return {"proj": proj, "calls": calls, "resp": resp, "data": data, "wb": wb, "profile": profile}


def rt(env, *args):
    r = subprocess.run([sys.executable, str(RUNTIME), *args, "--project", str(env["proj"])],
                       capture_output=True, text=True, timeout=300, env=os.environ.copy())
    return r.returncode, (json.loads(r.stdout) if r.stdout.strip() else None), r.stderr


def calls(env, kind):
    if not env["calls"].exists():
        return []
    rows = [json.loads(line) for line in env["calls"].read_text().splitlines()]
    return [r[1:] for r in rows if r[0] == kind]


def file_paths(cmd):
    return [cmd[i + 1].split("=")[0] for i, a in enumerate(cmd) if a == "--file"]


def inbox(env):
    code, out, err = rt(env, "inbox")
    assert code == 0, err
    return out["items"]


def test_tick_builds_one_vote_item_and_acts_on_nothing(env):
    before = (env["profile"] / "data/pick-queue.json").read_text()
    code, out, err = rt(env, "tick")
    assert code == 0, err
    assert out["vote"]["status"] == "to_inbox", out
    items = inbox(env)
    assert len(items) == 1 and items[0]["kind"] == "vote"
    b = items[0]["payload"]
    assert b["ready"] is True, b["problems"]
    assert b["topic"] == WINNER and b["slot"]["when"] == "2026-10-14T09:00:00-03:00"
    assert b["key"].startswith("2026-10-14-vote-durability-is-a-budget")
    assert [c["path"] for c in b["changed"]] == ["data/pick-queue.json"]
    content = Path(b["files"]["content"]["path"]).read_text()
    assert "```post" in content and "- Approval: plan" in content and "```first-comment" in content
    job = json.loads(Path(b["files"]["job"]["path"]).read_text())
    for flag in ("--post-file", "--comment-file", "--image", "--publisher", "--vcs", "--vote-update", "--vote-state"):
        assert job["argv"][job["argv"].index(flag) + 1] in job["snapshot"]
    assert calls(env, "publisher") == [] and calls(env, "scheduler") == []
    assert not [c for c in calls(env, "vcs") if c[0] == "commit-files"]
    assert (env["profile"] / "data/pick-queue.json").read_text() == before


def edit_data_file(env, change):
    path = env["wb"] / "shared/references/platforms/linkedin.json"
    data = json.loads(path.read_text())
    change(data)
    path.write_text(json.dumps(data))
    return path


def test_the_payload_builder_gets_the_data_file_and_the_publisher(env):
    # Row 46 made payload.py read the platform's limits from --platform-file and take the publisher's path; the
    # runtime passed neither, so a post was checked against no limit of the platform and no job.json was written.
    scripts = env["wb"] / "skills/mkt-publish/scripts"
    (scripts / "payload.py").rename(scripts / "payload_real.py")
    (scripts / "payload.py").write_text(  # records its arguments, then is the real payload.py
        "import json, os, runpy, sys\nfrom pathlib import Path\n"
        "with open(os.environ['FAKE_CALLS'], 'a') as f:\n    f.write(json.dumps(['payload'] + sys.argv[1:]) + '\\n')\n"
        "runpy.run_path(str(Path(__file__).with_name('payload_real.py')), run_name='__main__')\n")
    code, out, err = rt(env, "tick")
    assert code == 0, err
    b = inbox(env)[0]["payload"]
    assert b["ready"] is True, b["problems"]
    (build,) = calls(env, "payload")
    data_file = str(env["wb"].resolve() / "shared/references/platforms/linkedin.json")
    assert build[build.index("--platform") + 1] == "linkedin" and build[build.index("--platform-file") + 1] == data_file
    assert build[build.index("--publisher") + 1] == str(env["wb"].resolve() / "providers/publisher/linkedin.py")
    post = Path(b["files"]["post"]["path"])
    job = json.loads((post.parent / "job.json").read_text())  # written by payload.py only when given --publisher
    assert job["argv"][job["argv"].index("run") + 1] == str(env["wb"].resolve() / "providers/publisher/linkedin.py")


def test_the_vote_job_carries_the_data_file_and_hands_it_to_the_address_check(env, tmp_path):
    # Row 48 made vote_update.py --record-post check the post's address against the data file; the job neither
    # carried the file nor passed it, so only a generic https address was checked at the slot.
    rt(env, "tick")
    b = inbox(env)[0]["payload"]
    job = json.loads(Path(b["files"]["job"]["path"]).read_text())
    data_file = job["argv"][job["argv"].index("--platform-file") + 1]
    assert data_file == str(env["wb"].resolve() / "shared/references/platforms/linkedin.json")
    assert data_file in job["snapshot"]
    assert job["argv"][job["argv"].index("--platform") + 1] == "linkedin"
    other = tmp_path / "other.json"  # the same platform, whose posts live on another host
    data = json.loads(Path(data_file).read_text())
    data["post"]["url"]["hosts"] = ["www.example.com"]
    data["hosts"] = ["www.example.com"]
    other.write_text(json.dumps(data))
    argv = [str(other) if a == data_file else a for a in job["argv"]]
    r = subprocess.run([sys.executable] + argv[1:], capture_output=True, text=True, timeout=120,
                       env=os.environ.copy(), cwd=job["cwd"])
    out = json.loads(r.stdout)
    assert r.returncode == 1 and out["published"] is True and out["recorded"] is False, r.stderr
    assert "vote_update.py exited 1" in out["error"]
    assert not [c for c in calls(env, "vcs") if c[0] == "commit-files"]


def test_the_vote_job_has_no_default_platform_and_names_no_provider(env):
    # Coupling row 11: --platform defaulted to one platform, and the usage named that platform's provider files.
    rt(env, "tick")
    job = json.loads(Path(inbox(env)[0]["payload"]["files"]["job"]["path"]).read_text())
    i = job["argv"].index("--platform")
    without = job["argv"][1:i] + job["argv"][i + 2:]
    r = subprocess.run([sys.executable] + without, capture_output=True, text=True, timeout=60, cwd=job["cwd"])
    assert r.returncode == 2 and "--platform" in r.stderr
    assert calls(env, "publisher") == []
    source = (REPO / "runtime/handlers/social_vote_job.py").read_text().lower()
    assert "linkedin" not in source and "github" not in source


def test_a_round_id_that_is_not_one_builds_nothing(env):
    # RT15: the round id from the repository's vote file became a folder name (later removed with rmtree), and
    # only the skill's vote_state.py checked it.
    (env["wb"] / "skills/mkt-vote-round/scripts/vote_state.py").write_text(
        "import json\nprint(json.dumps({'pending': True, 'round': {'round': '../../escaped', 'pillar': 'x'}, "
        "'slot': None, 'rotation': {}}))\n")
    code, out, err = rt(env, "tick")
    assert code == 0, err
    assert out["vote"]["status"] == "failed" and "round id" in out["vote"]["note"], out
    assert not (env["data"].parent / "escaped").exists() and inbox(env) == []


def test_a_round_is_handled_once(env):
    rt(env, "tick")
    code, out, _ = rt(env, "tick")
    assert code == 0 and out["vote"]["status"] == "none" and "already handled" in out["vote"]["note"]
    assert len(inbox(env)) == 1


def test_rejecting_a_vote_item_lets_the_next_tick_redo_the_round(env):
    # RT1: the messages tell the person to reject so that the next tick retries; the round's cursor must go.
    rt(env, "tick")
    first = inbox(env)[0]
    code, out, err = rt(env, "reject", "--id", str(first["id"]), "--note", "the calendar has a row now")
    assert code == 0, err
    assert out["status"] == "rejected" and out["vote"] == {"round": "2026-10-05", "cursor_cleared": True}
    code, out, err = rt(env, "tick")
    assert code == 0, err
    assert out["vote"]["status"] == "to_inbox", out
    items = inbox(env)
    assert len(items) == 1 and items[0]["id"] != first["id"] and items[0]["payload"]["ready"] is True


def test_a_failure_after_the_agent_run_does_not_lose_the_round(env, monkeypatch):
    # RT1: the second read of the vote files fails (calls 4 to 6 are build_bundle's). No inbox item exists, so
    # the round is not marked as handled and the next tick redoes it.
    monkeypatch.setenv("FAKE_READ_FAIL_FROM", "4")
    code, out, err = rt(env, "tick")
    assert code == 0, err
    assert out["vote"]["status"] == "failed" and "read-file" in out["vote"]["note"]
    assert inbox(env) == []
    monkeypatch.delenv("FAKE_READ_FAIL_FROM")
    code, out, err = rt(env, "tick")
    assert code == 0, err
    assert out["vote"]["status"] == "to_inbox", out
    assert len(inbox(env)) == 1
    code, out, _ = rt(env, "tick")
    assert out["vote"]["status"] == "none" and "already handled" in out["vote"]["note"]


def test_an_unexpected_error_in_the_vote_step_is_recorded_and_the_round_is_redone(env):
    # RT6: the content folder cannot be created (a file is in its place), so build_bundle raises an OSError.
    # The tick ended in a traceback; with RT1 the round was also lost.
    content = env["proj"] / "docs/marketing/content"
    if content.is_dir():
        shutil.rmtree(content)
    content.write_text("not a folder\n")
    code, out, err = rt(env, "tick")
    assert code == 0, err
    assert out["vote"]["status"] == "failed" and "Error" in out["vote"]["note"], out
    assert "Traceback" in err
    assert inbox(env) == []
    code, status, _ = rt(env, "status")
    assert [r["status"] for r in status["runs"]] == ["ok"]  # the agent's run had ended before the failure
    content.unlink()
    code, out, err = rt(env, "tick")
    assert code == 0, err
    assert out["vote"]["status"] == "to_inbox", out


def test_an_unexpected_error_during_the_vote_run_ends_the_run_row(env):
    # RT6: the agent's task cannot be written, between run-start and run-end; the run row stayed "running".
    (env["data"] / "runs").mkdir(parents=True)
    (env["data"] / "runs" / "1").write_text("not a folder\n")
    code, out, err = rt(env, "tick")
    assert code == 0, err
    assert out["vote"]["status"] == "failed", out
    code, status, _ = rt(env, "status")
    assert [r["status"] for r in status["runs"]] == ["failed"]


def test_approve_schedules_the_post_and_commits_only_the_queue(env):
    rt(env, "tick")
    item = inbox(env)[0]
    code, shown, err = rt(env, "approve", "--id", str(item["id"]))
    assert code == 0, err
    assert shown["topic"] == WINNER and shown["sha256"] == item["payload_sha256"]
    assert calls(env, "scheduler") == []
    code, out, err = rt(env, "approve", "--id", str(item["id"]), "--confirmed", "--sha256", item["payload_sha256"])
    assert code == 0, err
    sched = calls(env, "scheduler")
    assert [("--dry-run" in c, "--confirmed" in c) for c in sched] == [(True, False), (False, True)]
    assert sched[1][sched[1].index("--at") + 1] == "2026-10-14T09:00:00-03:00"
    commits = [c for c in calls(env, "vcs") if c[0] == "commit-files"]
    assert len(commits) == 1
    c = commits[0]
    assert file_paths(c) == ["data/pick-queue.json"]
    assert c[c.index("--allow") + 1] == "data/pick-queue.json" and "--confirmed" in c
    queue = json.loads((env["profile"] / "data/pick-queue.json").read_text())
    assert queue[-1]["pillar"] == "Database performance"
    assert calls(env, "publisher") == []
    assert inbox(env) == []


def test_wrong_hash_or_edited_post_does_nothing(env):
    rt(env, "tick")
    item = inbox(env)[0]
    code, _, err = rt(env, "approve", "--id", str(item["id"]), "--confirmed", "--sha256", "0" * 64)
    assert code == 1 and "not this item" in err
    post = Path(item["payload"]["files"]["post"]["path"])
    post.chmod(0o600)
    post.write_text("something else\n")
    code, _, err = rt(env, "approve", "--id", str(item["id"]), "--confirmed", "--sha256", item["payload_sha256"])
    assert code == 1 and "changed since the proposal: post" in err
    assert calls(env, "scheduler") == []


def test_a_stored_bundle_changed_after_the_proposal_refuses(env):
    # RT12: the vote item's bundle in the store was never re-hashed, so its slot was covered by the database only.
    import sqlite3
    rt(env, "tick")
    item = inbox(env)[0]
    bundle = item["payload"]
    bundle["slot"]["when"] = "2026-10-13T09:00:00-03:00"
    with sqlite3.connect(str(env["data"] / "store.sqlite")) as db:
        db.execute("UPDATE inbox SET payload = ? WHERE id = ?",
                   (json.dumps(bundle, ensure_ascii=False, indent=1), item["id"]))
    code, _, err = rt(env, "approve", "--id", str(item["id"]), "--confirmed", "--sha256", item["payload_sha256"])
    assert code == 1 and "no longer has the hash" in err
    assert calls(env, "scheduler") == []


def test_queue_moved_in_the_repository_refuses(env):
    rt(env, "tick")
    item = inbox(env)[0]
    q = env["profile"] / "data/pick-queue.json"
    q.write_text("[]\n")
    code, _, err = rt(env, "approve", "--id", str(item["id"]), "--confirmed", "--sha256", item["payload_sha256"])
    assert code == 1 and "changed in the repository" in err
    assert calls(env, "scheduler") == []


def test_unusable_proposal_is_not_approvable(env):
    env["resp"].write_text(proposal(topic="A fourth topic nobody voted for"))
    code, out, _ = rt(env, "tick")
    assert out["vote"]["status"] == "to_inbox" and "not the winner" in out["vote"]["note"]
    item = inbox(env)[0]
    code, _, err = rt(env, "approve", "--id", str(item["id"]))
    assert code == 2 and "not ready" in err


def test_used_topic_in_next_round_is_refused_by_code(env):
    env["resp"].write_text(proposal(options={"A": "Reading EXPLAIN without guessing", "B": "Pool sizing notes",
                                             "C": "Autovacuum settings I changed and why"}))
    rt(env, "tick")
    b = inbox(env)[0]["payload"]
    assert b["ready"] is False and any("vote_update.py" in p for p in b["problems"])


def test_no_browser_degrades_to_text_only(env, monkeypatch):
    monkeypatch.setenv("FAKE_NO_BROWSER", "1")
    rt(env, "tick")
    b = inbox(env)[0]["payload"]
    assert b["ready"] is True and "image" not in b["files"]
    assert any("text-only" in n for n in b["notes"])
    job = json.loads(Path(b["files"]["job"]["path"]).read_text())
    assert "--image" not in job["argv"]


def test_failed_post_check_is_not_ready(env, monkeypatch):
    monkeypatch.setenv("FAKE_CHECK_FAIL", "a link in the body")
    rt(env, "tick")
    b = inbox(env)[0]["payload"]
    assert b["ready"] is False and "a link in the body" in b["problems"][0]


def test_the_vote_task_names_the_configured_platform(env):
    code, out, err = rt(env, "tick")
    assert code == 0, err
    (task,) = sorted((env["data"] / "runs").glob("*/task.md"))
    head = task.read_text().split("```", 1)[0]
    assert "\nPlatform: linkedin\n" in head, "above the vote state, which is data"
    assert runtime_vote.task_text(Path("/p"), {}, "demo-net").split("```", 1)[0].count("Platform: demo-net") == 1


def test_parse_proposal_rules():
    state = {"round": {"round": "2026-10-05", "winner": None, "winner_topic": None,
                       "options": {"A": "One", "B": "Two", "C": "Three"}},
             "slot": {"language": "PT"}, "rotation": {"next_pillar": "Small tools"}}
    limits = {"post": 3000, "first_comment": 1250}
    text = proposal(topic="Two", reason="It has material in the notes.", language="PT", pillar="Small tools")
    assert runtime_vote.parse_proposal(text, state, limits)["topic"] == "Two"
    for bad, message in ((proposal(topic="Two", language="PT", pillar="Small tools"), "reason"),
                         (proposal(topic="Two", reason="x", language="EN", pillar="Small tools"), "language"),
                         (proposal(topic="Two", reason="x", language="PT", pillar="Other"), "pillar"),
                         (proposal(topic="Two", reason="x", language="PT", pillar="Small tools",
                                   options={"A": "", "B": "b", "C": "c"}), "without material"),
                         (text + text, "found 2")):
        with pytest.raises(ValueError, match=message):
            runtime_vote.parse_proposal(bad, state, limits)
    with pytest.raises(ValueError, match="at most 20 characters"):
        runtime_vote.parse_proposal(text, state, {**limits, "post": 20})
    with pytest.raises(ValueError, match="first_comment must have at most 0"):
        runtime_vote.parse_proposal(text, state, {**limits, "first_comment": 0})


def test_the_limits_and_the_image_size_come_from_the_data_file(env):
    # CT2: the post's 3000 characters, the first comment's 1250 and the image's 1080 x 1350 were constants of the
    # runtime; they are the platform's, and its data file holds them.
    def change(d):
        d["post"]["max_characters"] = 30
        d["media"]["post_image"] = {"width": 600, "height": 400}
    edit_data_file(env, change)
    code, out, err = rt(env, "tick")
    assert code == 0, err
    assert out["vote"]["status"] == "to_inbox" and "at most 30 characters" in out["vote"]["note"], out
    assert rt(env, "reject", "--id", str(inbox(env)[0]["id"]))[0] == 0
    edit_data_file(env, lambda d: d["post"].update(max_characters=3000))
    code, out, err = rt(env, "tick")
    assert inbox(env)[0]["payload"]["ready"] is True, err
    (render,) = calls(env, "render")
    assert render[render.index("--width") + 1] == "600" and render[render.index("--height") + 1] == "400"


def test_vote_job_publishes_then_records_the_post(env, tmp_path):
    rt(env, "tick")
    b = inbox(env)[0]["payload"]
    job = json.loads(Path(b["files"]["job"]["path"]).read_text())
    r = subprocess.run([sys.executable] + job["argv"][1:], capture_output=True, text=True, timeout=120,
                       env=os.environ.copy(), cwd=job["cwd"])
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["published"] and out["recorded"]
    pub = calls(env, "publisher")[0]
    assert "--media" in pub and pub[pub.index("--idempotency-key") + 1] == b["key"]
    commit = [c for c in calls(env, "vcs") if c[0] == "commit-files"][0]
    paths = sorted(file_paths(commit))
    assert paths == [f"assets/posts/{b['key']}.png", "data/pick.json", "data/posts.json"]
    pick = json.loads((env["profile"] / "data/pick.json").read_text())
    closed = [h for h in pick["history"] if h["round"] == "2026-10-05"][0]
    assert closed["post_url"] == out["post_url"]
    posts = json.loads((env["profile"] / "data/posts.json").read_text())
    assert posts[-1]["url"] == out["post_url"] and posts[-1]["image"] == f"assets/posts/{b['key']}.png"


def test_vote_job_records_a_post_whose_first_comment_failed(env, monkeypatch):
    # FR-I12: with only the first comment failing, the publisher prints post_url and exits with its service
    # code. The job then said "publish failed; nothing was recorded" for a post that is public, and a rerun
    # of the round could publish it again.
    rt(env, "tick")
    b = inbox(env)[0]["payload"]
    job = json.loads(Path(b["files"]["job"]["path"]).read_text())
    monkeypatch.setenv("FAKE_FIRST_COMMENT_FAIL", "1")
    r = subprocess.run([sys.executable] + job["argv"][1:], capture_output=True, text=True, timeout=120,
                       env=os.environ.copy(), cwd=job["cwd"])
    out = json.loads(r.stdout)
    assert out["published"] is True and out["recorded"] is True, r.stderr
    assert "403" in out["first_comment_error"] and "first comment" in out["error"]
    assert "nothing was recorded" not in r.stdout
    assert r.returncode == 1  # a step failed: the scheduler shows the job as failed, with the post's address
    pick = json.loads((env["profile"] / "data/pick.json").read_text())
    closed = [h for h in pick["history"] if h["round"] == "2026-10-05"][0]
    assert closed["post_url"] == out["post_url"]
    assert len([c for c in calls(env, "vcs") if c[0] == "commit-files"]) == 1


def test_the_vote_job_carries_the_ledger_the_publisher_named(env, tmp_path, monkeypatch):
    # FR-I12: the scheduler starts the job without the variable that selects the publisher's ledger, so the
    # job could look its key up in another ledger than the one it was approved with. The job now carries the
    # ledger's path, from the publisher's dry run, and hands it to the publisher at the slot.
    ledger = tmp_path / "state" / "publisher.json"
    ledger.parent.mkdir()
    ledger.write_text("{}")  # it exists: the scheduler must not take it for a file to snapshot
    monkeypatch.setenv("FAKE_LEDGER", str(ledger))
    code, out, err = rt(env, "tick")
    assert code == 0 and out["vote"]["status"] == "to_inbox", err
    b = inbox(env)[0]["payload"]
    assert b["ready"] is True, b["problems"]
    dry = calls(env, "publisher-dry-run")
    assert len(dry) == 1 and dry[0][0] == "publish" and "--confirmed" not in dry[0]
    assert calls(env, "publisher") == []  # the tick still publishes nothing
    job = json.loads(Path(b["files"]["job"]["path"]).read_text())
    assert job["argv"][job["argv"].index("--ledger") + 1] == str(ledger)
    assert job["outputs"] == [str(ledger)] and str(ledger) not in job["snapshot"]
    r = subprocess.run([sys.executable] + job["argv"][1:], capture_output=True, text=True, timeout=120,
                       env=os.environ.copy(), cwd=job["cwd"])
    assert r.returncode == 0, r.stderr
    pub = calls(env, "publisher")[0]
    assert pub[pub.index("--ledger") + 1] == str(ledger)


def test_a_publisher_that_names_no_ledger_gets_none_and_a_failing_dry_run_is_a_problem(env, monkeypatch):
    code, out, err = rt(env, "tick")
    b = inbox(env)[0]["payload"]
    job = json.loads(Path(b["files"]["job"]["path"]).read_text())
    assert b["ready"] is True and "--ledger" not in job["argv"] and "outputs" not in job
    code, _, _ = rt(env, "reject", "--id", str(inbox(env)[0]["id"]))
    monkeypatch.setenv("FAKE_DRY_RUN_FAIL", "1")
    code, out, err = rt(env, "tick")
    b = inbox(env)[0]["payload"]
    assert b["ready"] is False and any("dry run" in p for p in b["problems"])


def test_vote_job_without_a_post_address_records_nothing(env, tmp_path):
    rt(env, "tick")
    b = inbox(env)[0]["payload"]
    job = json.loads(Path(b["files"]["job"]["path"]).read_text())
    (env["wb"] / "providers/publisher/linkedin.py").write_text(
        "import sys\nprint('error: LinkedIn returned 400', file=sys.stderr)\nsys.exit(1)\n")
    argv = [str(env["wb"] / "providers/publisher/linkedin.py") if a.endswith("linkedin.py") else a for a in job["argv"]]
    r = subprocess.run([sys.executable] + argv[1:], capture_output=True, text=True, timeout=120,
                       env=os.environ.copy(), cwd=job["cwd"])
    out = json.loads(r.stdout)
    assert r.returncode == 1 and out["published"] is False and "nothing was recorded" in out["error"]
    assert not [c for c in calls(env, "vcs") if c[0] == "commit-files"]


def test_vote_job_with_its_publisher_gone_records_nothing(env, tmp_path):
    # Test gap of the report: vote_job.py when the publisher is not found.
    rt(env, "tick")
    job = json.loads(Path(inbox(env)[0]["payload"]["files"]["job"]["path"]).read_text())
    i = job["argv"].index("--publisher")
    argv = job["argv"][:i + 1] + [str(tmp_path / "gone.py")] + job["argv"][i + 2:]
    r = subprocess.run([sys.executable] + argv[1:], capture_output=True, text=True, timeout=120,
                       env=os.environ.copy(), cwd=job["cwd"])
    out = json.loads(r.stdout)
    assert r.returncode == 1 and out["published"] is False and "nothing was recorded" in out["error"]
    assert calls(env, "publisher") == [] and not [c for c in calls(env, "vcs") if c[0] == "commit-files"]


def test_the_vote_job_uses_the_system_interpreter_and_carries_the_configured_folders(env, tmp_path):
    # RT4: the job was scheduled as a bare "python3" (hashed wherever the approver's PATH found it, so an
    # interpreter upgrade before the slot refused the job) and called "uv" by name on the scheduler's fixed
    # PATH, without the folders runtime.json lists for exactly that.
    tools = tmp_path / "tools"
    tools.mkdir()
    uv = tools / "uv"  # stands for a uv installed outside the scheduler's PATH: "uv run <script> ..."
    uv.write_text(f'#!/bin/sh\nshift\nexec "{sys.executable}" "$@"\n')
    uv.chmod(0o755)
    edit_config(env, path=[str(tools)])
    code, out, err = rt(env, "tick")
    assert code == 0 and out["vote"]["status"] == "to_inbox", err
    job = json.loads(Path(inbox(env)[0]["payload"]["files"]["job"]["path"]).read_text())
    system = "/usr/bin/python3"
    assert job["argv"][0] == (system if Path(system).exists() else sys.executable)
    # SC5: the scheduler's default limit for a one-shot command is 10 minutes; the job's own steps may take 27.
    assert job["timeout_minutes"] == 30
    assert [job["argv"][i + 1] for i, a in enumerate(job["argv"]) if a == "--path"] == [str(tools)]
    empty = tmp_path / "empty"
    empty.mkdir()
    bare = {**os.environ, "PATH": str(empty)}  # a scheduler's PATH, on which uv is not
    i = job["argv"].index("--path")
    without = job["argv"][1:i] + job["argv"][i + 2:]
    r = subprocess.run([sys.executable] + without, capture_output=True, text=True, timeout=120, env=bare, cwd=job["cwd"])
    assert r.returncode == 1 and "publish failed (127)" in r.stdout
    assert calls(env, "publisher") == []
    r = subprocess.run([sys.executable] + job["argv"][1:], capture_output=True, text=True, timeout=120, env=bare,
                       cwd=job["cwd"])
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["published"] and len(calls(env, "publisher")) == 1


# --- the scheduler and the vcs provider are resolved by class (providers/resolve.py) ---

def add_systemd(env):
    (env["wb"] / "providers/scheduler/systemd.py").write_text(
        FAKE_SCHEDULER.replace('["scheduler"] + args', '["scheduler-systemd"] + args'))


def edit_config(env, **changes):
    path = env["proj"] / "docs/workbench/runtime.json"
    cfg = json.loads(path.read_text())
    cfg.update(changes)
    path.write_text(json.dumps(cfg))


def test_vote_step_chooses_the_scheduler_the_platform_resolves_to(env, monkeypatch):
    sys.path.insert(0, str(REPO / "runtime" / "handlers"))
    import social as runtime
    add_systemd(env)
    monkeypatch.setenv("PATH", os.environ["PATH"])  # load_config puts the configured folders first
    for name in [n for n in os.environ if n.endswith("_PROVIDER")]:
        monkeypatch.delenv(name)
    folder = env["wb"].resolve() / "providers" / "scheduler"
    for platform, script in (("linux", "systemd.py"), ("darwin", "launchd.py")):
        monkeypatch.setattr(sys, "platform", platform)
        paths = runtime.load_config(env["proj"])["vote"]["paths"]
        assert paths["scheduler"] == folder / script
        assert paths["vcs"] == env["wb"].resolve() / "providers/vcs/github.py"  # the only vcs provider
        assert paths["resolver"] == env["wb"].resolve() / "providers/secrets/resolver.py"
    monkeypatch.setattr(sys, "platform", "linux")
    edit_config(env, scheduler="launchd")  # an implementation named in runtime.json wins
    assert runtime.load_config(env["proj"])["vote"]["paths"]["scheduler"] == folder / "launchd.py"


def test_approve_schedules_with_the_systemd_provider_when_it_is_the_one_resolved(env, monkeypatch):
    add_systemd(env)
    monkeypatch.setenv("SCHEDULER_PROVIDER", "systemd")
    rt(env, "tick")
    item = inbox(env)[0]
    code, out, err = rt(env, "approve", "--id", str(item["id"]), "--confirmed", "--sha256", item["payload_sha256"])
    assert code == 0, err
    sched = calls(env, "scheduler-systemd")
    assert [("--dry-run" in c, "--confirmed" in c) for c in sched] == [(True, False), (False, True)]
    assert calls(env, "scheduler") == []  # the launchd provider was not called


def test_a_second_vcs_provider_needs_a_choice_and_the_configured_name_still_works(env, monkeypatch):
    (env["wb"] / "providers/vcs/gitlab.py").write_text("")
    monkeypatch.delenv("INTEGRATION_VCS_PROVIDER", raising=False)
    code, out, err = rt(env, "status")
    assert code == 3 and "INTEGRATION_VCS_PROVIDER" in err
    cfg = json.loads((env["proj"] / "docs/workbench/runtime.json").read_text())
    edit_config(env, vote={**cfg["vote"], "vcs": "github"})  # a runtime.json written before resolution by class
    code, out, err = rt(env, "tick")
    assert code == 0 and out["vote"]["status"] == "to_inbox", err
    assert all(c[0] == "read-file" for c in calls(env, "vcs")) and calls(env, "vcs")


# --- RT7: nothing that looks like a credential is published ------------------------------------------

FAKE_TOKEN = "ghp" + "_" + "Q7" * 18  # built at run time: no credential-shaped literal in the repository


def test_a_proposal_holding_a_credential_is_masked_and_cannot_be_approved(env):
    text = proposal().replace("https://example.com/priya-fsync-slides", f"the key is {FAKE_TOKEN}")
    env["resp"].write_text(text)
    code, out, err = rt(env, "tick")
    assert code == 0, err
    (item,) = inbox(env)
    b = item["payload"]
    assert b["ready"] is False and any("looks like a credential (GitHub token)" in p for p in b["problems"])
    assert FAKE_TOKEN not in json.dumps(b) and "<redacted GitHub token>" in b["post"]["first_comment"]
    for f in b["files"].values():
        assert FAKE_TOKEN.encode() not in Path(f["path"]).read_bytes(), f["path"]
    code, _, err = rt(env, "approve", "--id", str(item["id"]))
    assert code == 2 and "not ready" in err
    assert calls(env, "scheduler") == [] and calls(env, "publisher") == []
