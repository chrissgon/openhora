"""Tests of publishing a drafted post as an external effect (runtime/step_publish_post.py, runtime/publish_document.py, runtime/publish_payload.py,
runtime/effect_publish.py, runtime/ops_step_effects.py, the publishing skill's own script skills/mkt-publish/scripts/payload.py; package
PUBLISH-EFFECT). The publisher is a stand-in provider (runtime/tests/standin_publisher.py) that keeps the ledger of a real one; the publishing skill's
script is the real one, copied into the stand-in tree and not edited. No platform is ever called, no credential is real, every name is invented.
The cases of the spec's "Done when": a post goes out only with the approval of its exact text's hash and once; the key is the publishing skill's, so
a post published by either path is not published again by the other; a changed post or image is stale; a post with an image is not whole on a
messaging card; the reply path of the same word is as it was.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_publish_post.py
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import standin_tree as st
from standin_publisher import PUBLISHER

lab = st.load("lab")
ops = st.load("ops")
ops_core = st.load("ops_core")
ops_steps = st.load("ops_steps")
effects = st.load("effects")
effect_publish = st.load("effect_publish")
effect_reply = st.load("effect_reply")
publish_document = st.load("publish_document")
publish_payload = st.load("publish_payload")
ops_step_effects = st.load("ops_step_effects")
ops_step_seams = st.load("ops_step_seams")
step_publish_post = st.load("step_publish_post")
project_config = st.load("project_config")
operations = st.load("operations")
steps = st.load("steps")

KEY = "2027-10-11-launch"
CONTENT = f"docs/marketing/content/{KEY}.md"
SLOT = "2027-10-11T09:00:00-03:00"
TEXT = "We shipped the new release today.\n\nWhat changed:\n- faster start\n- a smaller download\n\n#release"
COMMENT = "The notes are at https://example.org/notes"
IMAGE = "docs/assets/cover.png"
PNG = b"\x89PNG\r\n\x1a\n" + b"the cover image of the release"
ARGS = {"post": CONTENT, "platform": "linkedin"}


def sha(data):
    return hashlib.sha256(data if isinstance(data, bytes) else data.encode("utf-8")).hexdigest()


def content_file(text=TEXT, comment=COMMENT, image=IMAGE, status="draft", checks="ok", slot=SLOT):
    lines = ["# Post: the release", "", "- Owner: mkt-social-copy", f"- Status: {status}", f"- Slot: {slot} · product · en · calendar row 1",
             "- Network: linkedin", "- Format: text", "- Approval: action"]
    if image:
        lines.append(f"- Image: {image}")
    lines += ["", "## Post", "", "```post", text, "```", ""]
    if comment:
        lines += ["## First comment", "", "```first-comment", comment, "```", ""]
    lines += ["## Checks", "", f"- check_post.py: {checks}", ""]
    return "\n".join(lines)


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("WB_LOCAL_EVIDENCE_DIR", str(tmp_path / "evidence"))
    built = st.build(tmp_path, monkeypatch, lab)
    tree, project = built["tree"], built["project"]
    (tree / "providers" / "publisher").mkdir(parents=True, exist_ok=True)
    (tree / "providers" / "publisher" / "standin.py").write_text(PUBLISHER, encoding="utf-8")
    (tree / "skills" / "mkt-publish" / "scripts").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(st.REPO / "skills" / "mkt-publish" / "scripts" / "payload.py", tree / "skills" / "mkt-publish" / "scripts" / "payload.py")
    (tree / "shared" / "references" / "platforms").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(st.REPO / "shared" / "references" / "platforms" / "linkedin.json", tree / "shared" / "references" / "platforms" / "linkedin.json")
    (tree / "flows").mkdir(exist_ok=True)
    shutil.copyfile(st.REPO / "flows" / "publish-post.json", tree / "flows" / "publish-post.json")
    monkeypatch.setattr(ops_core, "ROOT", str(tree))
    real_services = ops_step_seams.services      # the seams read the checkout they run from; the stand-in tree is the one with the stand-in publisher
    monkeypatch.setattr(ops_step_seams, "services",
                        lambda ctx: {**real_services(ctx), "publisher": ops_step_seams.PublisherReader(ctx["cfg"], str(tree))})
    (project / "docs" / "marketing" / "content").mkdir(parents=True)
    (project / "docs" / "assets").mkdir(parents=True)
    (project / CONTENT).write_text(content_file(), encoding="utf-8")
    (project / IMAGE).write_bytes(PNG)
    ops.accept_config(str(project), ops.project_config.load(str(project))["sha256"])
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    yield {**built, "path": str(project), "tmp": tmp_path, "provider": tree / "providers" / "publisher"}


def mode(world, **values):
    (world["provider"] / "mode.json").write_text(json.dumps(values), encoding="utf-8")


def calls(world):
    path = world["provider"] / "calls.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.is_file() else []


def posts(world):
    path = world["provider"] / "posts.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.is_file() else []


def confirmed(world):
    return [c for c in calls(world) if "--confirmed" in c["argv"]]


def ledger(world):
    path = world["provider"] / "standin-ledger.json"
    return json.loads(path.read_text())["entries"] if path.is_file() else {}


def add(world, args=None, **extra):
    ctx = ops_core.context(world["path"])
    made = steps.add_task(ctx["store"], ctx["conn"], "publish-post", {**(args or ARGS), **extra}, key="publish", title="Publish the post", text="Publish it.")
    return made["task"]


def run_task(world, task):
    ctx = ops_core.context(world["path"])
    if ctx["store"].task_get(ctx["conn"], task)["state"] == "failed":
        ctx["store"].task_retry(ctx["conn"], task)
    return ops_steps.run_step(world["path"], task)


def pending_of(world, task):
    ctx = ops_core.context(world["path"])
    rows = [p for p in ctx["store"].pending_list(ctx["conn"], "open", task)]
    assert len(rows) == 1, rows
    return rows[0]


def task_state(world, task):
    ctx = ops_core.context(world["path"])
    return ctx["store"].task_get(ctx["conn"], task)["state"]


def opened(world, args=None, **extra):
    task = add(world, args, **extra)
    out = run_task(world, task)
    assert out["ok"] is True and out["task_state"] == "waiting", out
    return task, pending_of(world, task)


def effect_doc(world, task):
    cfg = ops_core.context(world["path"])["cfg"]
    return json.loads((Path(ops_step_effects.effect_dir(cfg, task, 0)) / "effect.json").read_text(encoding="ascii"))


def approve(world, item, channel="terminal"):
    return ops.approve(world["path"], item["id"], sha256=item["payload_sha256"], channel=channel)


def skill_job_argv(world, key=KEY):
    """What the publishing skill's own scheduled job would run for the post: the job file payload.py writes for the publisher (the script is the
    real one), with `uv run` replaced by the test's interpreter. Built from the project's content file, as the skill's step 4 does."""
    out = world["tmp"] / "skill-payload"
    shutil.rmtree(out, ignore_errors=True)
    publisher = world["provider"] / "standin.py"
    done = subprocess.run([sys.executable, str(world["tree"] / "skills" / "mkt-publish" / "scripts" / "payload.py"), "build", "--content", CONTENT,
                           "--platform", "linkedin", "--platform-file", str(world["tree"] / "shared" / "references" / "platforms" / "linkedin.json"),
                           "--publisher", str(publisher), "--workbench", str(world["tree"]), "--out", str(out)],
                          cwd=world["path"], capture_output=True, text=True, timeout=60, env={**os.environ, "HOME": str(world["tmp"])})
    assert done.returncode == 0, done.stderr
    job = json.loads((out / key / "job.json").read_text(encoding="utf-8"))
    assert job["argv"][:3] == ["uv", "run", str(publisher)]
    return [sys.executable, *job["argv"][2:]]


def run_skill_job(world):
    argv = skill_job_argv(world)
    return subprocess.run(argv, capture_output=True, text=True, timeout=60, cwd=world["path"],
                          env={k: v for k, v in os.environ.items() if k != "XDG_DATA_HOME"})


# --- what the person is shown ------------------------------------------------------------------------------------------------------------------


def test_the_task_opens_an_effect_with_the_hash_of_the_whole_post_and_publishes_nothing(world):
    task, item = opened(world)
    assert item["kind"] == "effect" and len(item["payload_sha256"]) == 64 and item["payload"]["step"] == {"kind": "publish-post", "step": "publish"}
    assert confirmed(world) == [] and posts(world) == [] and ledger(world) == {}, "preparing publishes nothing and records nothing in the ledger"
    body = item["body"]
    for needle in (TEXT, COMMENT, "linkedin", KEY, SLOT, "published NOW", "not at its slot", item["payload_sha256"], "approve", "--sha256", sha(PNG), IMAGE,
                   "The image itself is not on this card"):
        assert needle in body, needle
    assert "check line: ok" in body
    order = [body.index(x) for x in ("Platform:", "published NOW", "the post, exactly as written", "First comment", "Image:", "dry run says")]
    assert order == sorted(order), "the platform and the moment come first"
    assert TEXT not in json.dumps(item["payload"]) and COMMENT not in json.dumps(item["payload"]), "the state keeps counts and hashes"
    assert item["payload"]["effect"] == {"platform": "linkedin", "key": KEY, "characters": len(TEXT) + 1, "first_comment": True, "image": True,
                                         "text_sha256": sha(TEXT + "\n")}


def test_the_hash_is_the_hash_of_the_effect_file_which_holds_the_text_the_key_and_the_providers_dry_run(world):
    task, item = opened(world)
    cfg = ops_core.context(world["path"])["cfg"]
    path = Path(ops_step_effects.effect_dir(cfg, task, 0)) / "effect.json"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == item["payload_sha256"] and oct(path.stat().st_mode & 0o777) == "0o600"
    for folder in (path.parent, path.parent.parent, path.parent.parent.parent):
        assert oct(folder.stat().st_mode & 0o777) == "0o700", folder
    doc = effect_doc(world, task)
    assert doc["effect"] == "publish" and doc["operation"] == "post" and doc["provider"] == "standin" and doc["platform"] == "linkedin"
    assert doc["content"] == CONTENT and doc["idempotency_key"] == KEY and doc["slot"] == SLOT
    assert doc["text"] == TEXT + "\n" and doc["text_sha256"] == sha(TEXT + "\n") and doc["comment"] == COMMENT + "\n"
    assert doc["image"] == {"source": IMAGE, "name": "image.png", "bytes": len(PNG), "sha256": sha(PNG)}
    assert doc["checks"] == "ok" and doc["token_expires_at"] == "2099-01-01T00:00:00Z"
    dry = doc["dry_run"]
    assert dry["requests"][0]["body"]["commentary"] == TEXT, "the dry run's text is the text on the card"
    assert dry["requests"][0]["body"]["media"] == f"<{len(PNG)} bytes of <private>/payload/{KEY}/image.png>", "the private folder is not in the hash"
    assert "ledger" not in dry and not [k for k in dry if "existing_" in k], "what changes with the ledger is not in the hash"
    assert json.dumps(dry, indent=1, sort_keys=True, ensure_ascii=False) in item["body"], "the card shows the dry run as it is hashed"


def test_the_card_is_the_same_whatever_the_private_folder_it_was_prepared_in(world):
    first = effect_doc(world, opened(world)[0])
    second = effect_doc(world, opened(world)[0])
    assert first["dry_run"] == second["dry_run"] and first["text"] == second["text"]


def test_the_key_is_the_publishing_skills_and_the_files_are_the_files_its_own_job_runs(world):
    task, item = opened(world)
    doc = effect_doc(world, task)
    argv = skill_job_argv(world)
    assert argv[argv.index("--idempotency-key") + 1] == doc["idempotency_key"] == KEY
    assert Path(argv[argv.index("--text-file") + 1]).read_bytes() == doc["text"].encode("utf-8")
    assert Path(argv[argv.index("--first-comment-file") + 1]).read_bytes() == doc["comment"].encode("utf-8")
    assert sha(Path(argv[argv.index("--media") + 1]).read_bytes()) == doc["image"]["sha256"]


def test_a_different_text_comment_or_image_is_a_different_hash_and_one_approval_covers_one_post():
    base = dict(task_id=1, provider="standin", platform="linkedin", content=CONTENT, slot=SLOT, text=TEXT + "\n", comment=COMMENT + "\n",
                image={"source": IMAGE, "name": "image.png", "bytes": len(PNG), "sha256": sha(PNG)}, checks="ok", token_expires_at=None,
                ledger="/data/ledger.json", dry_run={"requests": []})
    docs = [publish_document.document(**base), publish_document.document(**{**base, "text": TEXT + " more\n"}),
            publish_document.document(**{**base, "comment": None}), publish_document.document(**{**base, "image": None}),
            publish_document.document(**{**base, "image": {**base["image"], "sha256": sha(b"x")}}),
            publish_document.document(**{**base, "content": "docs/marketing/content/other.md"}),
            publish_document.document(**{**base, "ledger": "/elsewhere/ledger.json"})]
    digests = [sha(effects._text(d)) for d in docs]
    assert len(set(digests)) == len(docs)
    approval = {"scope": "action", "status": "pending-execution", "payload_sha256": digests[0]}
    with pytest.raises(effects.EffectError) as refused:
        effect_publish.execute(docs[1], approval, lambda verb, args: pytest.fail("the provider was called"), docs[1]["idempotency_key"], project="/x")
    assert refused.value.kind == "deviation" and "no approval of this exact content" in refused.value.reason


def test_an_effect_file_edited_after_the_preview_is_not_the_approved_one_and_nothing_is_published(world):
    task, item = opened(world)
    cfg = ops_core.context(world["path"])["cfg"]
    path = Path(ops_step_effects.effect_dir(cfg, task, 0)) / "effect.json"
    doc = json.loads(path.read_text(encoding="ascii"))
    doc["text"] = "Buy now\n"
    path.write_text(json.dumps(doc, sort_keys=True, indent=1) + "\n", encoding="ascii")
    with pytest.raises(ops_core.OpsError) as refused:
        approve(world, item)
    assert "not the one approved" in str(refused.value) and "nothing was published" in str(refused.value)
    assert confirmed(world) == [] and task_state(world, task) == "waiting"


# --- the approval -------------------------------------------------------------------------------------------------------------------------------


def test_limit_43_a_post_without_the_approval_of_its_exact_text_is_refused_by_structure(world):
    task, item = opened(world)
    for channel in ("messaging", "mcp", "conversation", None):
        with pytest.raises(ops_core.OpsError) as refused:
            ops.approve(world["path"], item["id"], sha256=item["payload_sha256"], channel=channel)
        assert "approved in the terminal" in str(refused.value), channel
    with pytest.raises(ops_core.OpsError):
        ops.approve(world["path"], item["id"], sha256=None, channel="terminal")
    with pytest.raises(ops_core.OpsError) as refused:
        ops.approve(world["path"], item["id"], sha256="0" * 64, channel="terminal")
    assert "nothing was approved" in str(refused.value)
    with pytest.raises(ops_core.OpsError):
        ops.answer(world["path"], item["id"], "approve")      # a word typed into a conversation is no approval either
    assert confirmed(world) == [] and posts(world) == []
    doc = effect_doc(world, task)
    call = effect_publish.caller(ops_core.context(world["path"])["cfg"], ops_core.ROOT)
    for approval in (None, {}, {"scope": "plan", "status": "pending-execution", "payload_sha256": item["payload_sha256"]},
                     {"scope": "action", "status": "revoked", "payload_sha256": item["payload_sha256"]},
                     {"scope": "action", "status": "pending-execution", "payload_sha256": "0" * 64}):
        with pytest.raises(effects.EffectError):
            effect_publish.execute(doc, approval, call, doc["idempotency_key"], project=world["path"])
    assert confirmed(world) == [] and posts(world) == []


@pytest.mark.parametrize("channel", ["terminal", "page"])
def test_limit_43_with_the_approval_of_its_hash_from_the_terminal_or_the_page_it_is_published_once_now_and_recorded(world, channel):
    task, item = opened(world)
    done = approve(world, item, channel)
    assert done["task_state"] == "done" and done["result"]["published"] is True and done["result"]["replayed"] is False
    assert done["result"]["post_url"].startswith("https://www.linkedin.com/feed/update/urn:li:share:") and done["result"]["first_comment"] == "posted"
    [taken] = posts(world)
    assert taken == {"key": KEY, "text": TEXT, "comment": COMMENT, "media_sha256": sha(PNG)}
    [real] = confirmed(world)
    assert "--at" not in real["argv"] and "--ledger" not in real["argv"], "immediate only: no slot time, the provider's own ledger"
    assert real["argv"][:1] == ["publish"] and real["argv"][real["argv"].index("--idempotency-key") + 1] == KEY
    assert task_state(world, task) == "done"
    ctx = ops_core.context(world["path"])
    row = ctx["store"].approval_get(ctx["conn"], done["approval_id"])
    assert row["status"] == "executed" and row["scope"] == "action" and row["payload_sha256"] == item["payload_sha256"]
    settled = ctx["store"].pending_get(ctx["conn"], item["id"])
    assert settled["status"] == "resolved" and settled["resolution"] == "approved" and settled["payload"]["result"]["published"] is True
    assert TEXT not in json.dumps(settled["payload"]), "the record keeps the address of the post and counts, not the text"
    with pytest.raises(ops_core.OpsError):
        approve(world, item, channel)
    assert len(posts(world)) == 1
    assert list((world["tmp"] / "data").glob("openhora-publish-*")) == [], "the private folder is removed"


def test_the_state_file_gets_the_generated_row_of_the_executed_approval(world):
    task, item = opened(world)
    done = approve(world, item)
    text = (Path(world["path"]) / "docs" / "workbench" / "state.md").read_text(encoding="utf-8")
    assert done["state"]["written"] is True and f"sha256:{item['payload_sha256']}" in text and "publish a post on linkedin" in text and "executed" in text


def test_a_rejected_post_cancels_the_task_and_publishes_nothing(world):
    task, item = opened(world)
    ops.reject(world["path"], item["id"], "not now")
    assert task_state(world, task) == "cancelled" and confirmed(world) == []


def test_the_provider_is_given_no_secret_and_the_data_folders_variable(world, monkeypatch):
    monkeypatch.setenv("LINKEDIN_ACCESS_TOKEN", "x" * 24)
    monkeypatch.setenv("NOTION_TOKEN", "y" * 24)
    monkeypatch.setenv("XDG_DATA_HOME", str(world["tmp"] / "xdg-data"))
    task, item = opened(world)
    approve(world, item)
    seen = calls(world)
    assert seen and all("LINKEDIN_ACCESS_TOKEN" not in c["env"] and "NOTION_TOKEN" not in c["env"] for c in seen)
    assert all(c["xdg_data_home"] == str(world["tmp"] / "xdg-data") for c in seen)
    assert (world["tmp"] / "xdg-data" / "standin-ledger.json").is_file() and not (world["provider"] / "standin-ledger.json").exists()


# --- the same post cannot go out twice, by either path ---------------------------------------------------------------------------------------


def test_limit_43_a_post_the_publishing_skills_job_published_is_not_published_again_and_nothing_is_asked(world):
    run = run_skill_job(world)
    assert run.returncode == 0, run.stderr
    assert len(posts(world)) == 1 and ledger(world)[KEY]["status"] == "published"
    task = add(world)
    out = run_task(world, task)
    assert out["ok"] is False and out["code"] == "already_published" and "published already" in out["next"]
    ctx = ops_core.context(world["path"])
    assert ctx["store"].pending_list(ctx["conn"], "open", task) == []
    assert len(posts(world)) == 1 and confirmed(world)[-1]["argv"].count("--confirmed") == 1, "the only confirmed call is the skill's"


def test_limit_43_a_post_published_by_this_path_is_replayed_by_the_skills_job_and_not_published_again(world):
    task, item = opened(world)
    approve(world, item)
    assert len(posts(world)) == 1
    run = run_skill_job(world)
    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout)["replayed"] is True and len(posts(world)) == 1


def test_limit_43_a_post_the_skills_job_published_between_the_preview_and_the_approval_is_replayed_and_published_once(world):
    task, item = opened(world)
    assert run_skill_job(world).returncode == 0
    done = approve(world, item)
    assert done["result"]["replayed"] is True and len(posts(world)) == 1 and done["task_state"] == "done"


def test_the_same_document_approved_again_is_replayed_not_published_twice(world):
    task, item = opened(world)
    doc = effect_doc(world, task)
    approval = {"scope": "action", "status": "pending-execution", "payload_sha256": item["payload_sha256"]}
    cfg = ops_core.context(world["path"])["cfg"]
    call = effect_publish.caller(cfg, ops_core.ROOT)
    first = effect_publish.execute(doc, approval, call, doc["idempotency_key"], str(world["tmp"]), project=cfg["project"])
    second = effect_publish.execute(doc, approval, call, doc["idempotency_key"], str(world["tmp"]), project=cfg["project"])
    assert first["replayed"] is False and second["replayed"] is True and len(posts(world)) == 1


def test_a_post_edited_after_the_skills_job_published_it_is_refused_by_the_ledger_not_published_as_another(world):
    assert run_skill_job(world).returncode == 0
    (Path(world["path"]) / CONTENT).write_text(content_file(text=TEXT + "\n\nA new line."), encoding="utf-8")
    out = run_task(world, add(world))
    assert out["code"] == "already_published" and len(posts(world)) == 1


def test_a_key_left_pending_blocks_both_paths_and_is_named(world):
    mode(world, confirm="unknown")
    task, item = opened(world)
    with pytest.raises(ops_core.OpsError) as lost:
        approve(world, item)
    assert "may or may not" in str(lost.value) or "outcome is unknown" in str(lost.value)
    assert "resolve" in str(lost.value) and task_state(world, task) == "waiting"
    assert ledger(world)[KEY]["status"] == "pending"
    mode(world)
    assert run_skill_job(world).returncode == 1, "the skill's job is blocked by the same pending key"
    out = run_task(world, add(world))
    assert out["code"] == "outcome_unknown"
    with pytest.raises(ops_core.OpsError):
        approve(world, item)      # still pending: the ledger refuses, nothing published
    assert posts(world) == []


# --- a post that changed since the preview -----------------------------------------------------------------------------------------------------


def test_limit_43_an_image_changed_after_the_preview_stops_the_publication_and_asks_again_about_the_file_as_it_is(world):
    task, item = opened(world)
    (Path(world["path"]) / IMAGE).write_bytes(PNG + b" and a changed pixel")
    with pytest.raises(ops_core.OpsError) as stopped:
        approve(world, item)
    assert "is not the one the task read" in str(stopped.value) and "starts over" in str(stopped.value)
    assert confirmed(world) == [] and posts(world) == []
    ctx = ops_core.context(world["path"])
    old = ctx["store"].pending_get(ctx["conn"], item["id"])
    assert old["status"] == "resolved" and old["resolution"] == "answered" and task_state(world, task) == "ready"
    assert ctx["store"].approval_get(ctx["conn"], 1)["status"] == "revoked"
    out = run_task(world, task)
    assert out["ok"] is True and out["task_state"] == "waiting"
    new = pending_of(world, task)
    assert new["payload_sha256"] != item["payload_sha256"] and sha(PNG + b" and a changed pixel") in new["body"]
    assert approve(world, new)["task_state"] == "done" and len(posts(world)) == 1
    with pytest.raises(ops_core.OpsError):
        approve(world, item)


@pytest.mark.parametrize("change", ["text", "comment", "slot", "no-comment"])
def test_a_text_comment_or_slot_changed_after_the_preview_is_stale_too(world, change):
    task, item = opened(world)
    edits = {"text": dict(text=TEXT + "\n\nPS."), "comment": dict(comment=COMMENT + " (updated)"), "slot": dict(slot="2027-10-12T09:00:00-03:00"),
             "no-comment": dict(comment=None)}
    (Path(world["path"]) / CONTENT).write_text(content_file(**edits[change]), encoding="utf-8")
    with pytest.raises(ops_core.OpsError) as stopped:
        approve(world, item)
    assert "is not the one the task read" in str(stopped.value) and confirmed(world) == [] and task_state(world, task) == "ready"


def test_a_content_file_that_became_a_link_vanished_or_no_longer_builds_is_stale(world):
    task, item = opened(world)
    (Path(world["path"]) / CONTENT).write_text(content_file(text="x" * 4000), encoding="utf-8")      # over the platform's limit: payload.py refuses
    with pytest.raises(ops_core.OpsError) as stopped:
        approve(world, item)
    assert "can no longer be built as the task read it" in str(stopped.value) and confirmed(world) == [] and posts(world) == []


def test_an_image_that_became_a_link_is_stale_too(world):
    task, item = opened(world)
    (Path(world["path"]) / IMAGE).unlink()
    (Path(world["path"]) / IMAGE).symlink_to(Path(world["path"]) / "AGENTS.md")
    with pytest.raises(ops_core.OpsError):
        approve(world, item)
    assert confirmed(world) == [] and posts(world) == []


def test_a_provider_that_would_publish_another_text_than_the_one_previewed_publishes_nothing(world):
    task, item = opened(world)
    mode(world, dry_run_text="Buy now at a discount")
    with pytest.raises(ops_core.OpsError) as refused:
        approve(world, item)
    assert "something other than the post that was previewed" in str(refused.value) and posts(world) == [] and confirmed(world) == []


# --- what stops it before the effect is opened -------------------------------------------------------------------------------------------------------


def test_the_arguments_are_checked_when_the_task_is_planned_and_the_platform_is_lowercased():
    for args in ({}, {"post": CONTENT}, {"platform": "linkedin"}, {**ARGS, "extra": 1}, {"post": "docs/marketing/content/A.md", "platform": "linkedin"},
                 {"post": "docs/marketing/other/a.md", "platform": "linkedin"}, {"post": "docs/marketing/content/../a.md", "platform": "linkedin"},
                 {"post": "docs/marketing/content/a.md.comments.md", "platform": "linkedin"}, {**ARGS, "platform": "linked in"}, {**ARGS, "platform": ""},
                 {**ARGS, "platform": "../x"}, {**ARGS, "post": 5}, {**ARGS, "platform": 5}, {"post": "/etc/passwd", "platform": "linkedin"}):
        with pytest.raises(steps.StepFailure) as refused:
            steps.plan_task("publish-post", args, key="k", title="t", text="x")
        assert refused.value.code == "bad_args", args
    planned = steps.plan_task("publish-post", {"post": CONTENT, "platform": " LinkedIn "}, key="k", title="t", text="x")
    assert planned["args"] == ARGS


def test_a_blocked_post_a_missing_file_a_link_and_a_post_the_script_refuses_open_no_effect(world):
    root = Path(world["path"])
    (root / CONTENT).write_text(content_file(status="blocked (a sensitive topic)"), encoding="utf-8")
    assert run_task(world, add(world))["code"] == "post_blocked"
    other = "docs/marketing/content/2027-10-12-missing.md"
    assert run_task(world, add(world, {"post": other, "platform": "linkedin"}))["code"] == "post_missing"
    (root / "docs" / "real.md").write_text(content_file(), encoding="utf-8")
    link = "docs/marketing/content/2027-10-13-link.md"
    (root / link).symlink_to(root / "docs" / "real.md")
    assert run_task(world, add(world, {"post": link, "platform": "linkedin"}))["code"] == "path_unsafe"
    (root / CONTENT).write_text(content_file(text="x" * 4000), encoding="utf-8")
    out = run_task(world, add(world))
    assert out["code"] == "payload_refused" and "payload.py build" in out["next"] and "x" * 100 not in json.dumps(out)
    (root / CONTENT).write_text(content_file(image="../outside.png"), encoding="utf-8")
    assert run_task(world, add(world))["code"] == "payload_refused"
    assert posts(world) == [] and confirmed(world) == []


def test_an_image_outside_the_project_or_that_is_a_link_is_refused(world, tmp_path):
    root = Path(world["path"])
    outside = tmp_path / "outside.png"
    outside.write_bytes(PNG)
    (root / CONTENT).write_text(content_file(image=str(outside)), encoding="utf-8")
    assert run_task(world, add(world))["code"] == "payload_refused"
    (root / "docs" / "assets" / "link.png").symlink_to(outside)
    (root / CONTENT).write_text(content_file(image="docs/assets/link.png"), encoding="utf-8")
    assert run_task(world, add(world))["code"] == "payload_refused"
    assert confirmed(world) == []


def test_a_post_that_holds_a_credential_opens_no_effect_and_the_key_is_not_echoed(world):
    key = "sk-" + "ant-" + "api03-" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6"
    (Path(world["path"]) / CONTENT).write_text(content_file(text=f"The key: {key}"), encoding="utf-8")
    out = run_task(world, add(world))
    assert out["ok"] is False and out["code"] == "content_refused" and key not in json.dumps(out)
    (Path(world["path"]) / CONTENT).write_text(content_file(comment=f"The key: {key}"), encoding="utf-8")
    assert run_task(world, add(world))["code"] == "content_refused"
    assert confirmed(world) == []


def test_a_publisher_that_is_not_set_up_or_whose_token_ran_out_opens_no_effect(world):
    mode(world, check_exit=3)
    out = run_task(world, add(world))
    assert out["code"] == "not_configured" and "auth.py" in out["next"]
    mode(world, check={"ready": True, "token_expires_at": "2020-01-01T00:00:00Z"})
    assert run_task(world, add(world))["code"] == "not_configured"
    mode(world, check={"ready": False})
    assert run_task(world, add(world))["code"] == "not_configured"
    assert confirmed(world) == []


def test_a_platform_without_a_data_file_or_a_publisher_opens_no_effect(world):
    out = run_task(world, add(world, {"post": CONTENT, "platform": "nowhere"}))
    assert out["ok"] is False and out["code"] in ("not_configured", "payload_refused")
    assert confirmed(world) == []


# --- the configuration at the approval ---------------------------------------------------------------------------------------------------------


def test_the_publisher_must_still_resolve_to_the_one_the_post_was_prepared_for_and_be_ready_with_a_valid_token(world):
    task, item = opened(world)
    mode(world, check_exit=3)
    with pytest.raises(ops_core.OpsError) as refused:
        approve(world, item)
    assert "nothing was published" in str(refused.value) and refused.value.code == 3 and confirmed(world) == []
    mode(world, check={"ready": True, "token_expires_at": "2020-01-01T00:00:00Z"})
    with pytest.raises(ops_core.OpsError) as refused:
        approve(world, item)
    assert "token has expired" in str(refused.value) and refused.value.code == 3
    (world["provider"] / "other.py").write_text(PUBLISHER.replace('PLATFORMS = ("linkedin",)', 'PLATFORMS = ("linkedin",)  # another'), encoding="utf-8")
    os.environ["PUBLISHER_LINKEDIN_PROVIDER"] = "other"
    try:
        mode(world)
        with pytest.raises(ops_core.OpsError) as refused:
            approve(world, item)
        assert "not the one the post was prepared for" in str(refused.value) and refused.value.code == 1
    finally:
        del os.environ["PUBLISHER_LINKEDIN_PROVIDER"]
    (world["provider"] / "other.py").unlink()
    assert confirmed(world) == []
    assert approve(world, item)["task_state"] == "done" and len(posts(world)) == 1


# --- the outcomes that are not clean -------------------------------------------------------------------------------------------------------------


def test_limit_43_a_refusal_publishes_nothing_leaves_the_effect_open_and_releases_the_key(world):
    task, item = opened(world)
    mode(world, confirm="refuse")
    with pytest.raises(ops_core.OpsError) as refused:
        approve(world, item)
    assert "nothing was published" in str(refused.value) and "tries again" in str(refused.value) and posts(world) == []
    assert ledger(world) == {} and task_state(world, task) == "waiting"
    ctx = ops_core.context(world["path"])
    assert ctx["store"].pending_get(ctx["conn"], item["id"])["status"] == "open"
    mode(world)
    assert approve(world, item)["task_state"] == "done" and len(posts(world)) == 1


def test_limit_43_a_lost_answer_is_unknown_the_effect_stays_open_and_the_key_stays_blocked_until_the_person_settles_it(world, monkeypatch):
    task, item = opened(world)
    mode(world, confirm="sleep")
    monkeypatch.setattr(effect_publish, "CALL_TIMEOUT", 1)
    with pytest.raises(ops_core.OpsError) as lost:
        approve(world, item)
    assert "outcome is unknown" in str(lost.value) and "resolve" in str(lost.value) and "profile" in str(lost.value)
    ctx = ops_core.context(world["path"])
    assert ctx["store"].pending_get(ctx["conn"], item["id"])["status"] == "open" and task_state(world, task) == "waiting"
    assert ledger(world)[KEY]["status"] == "pending" and posts(world) == []
    mode(world)
    with pytest.raises(ops_core.OpsError) as still:
        approve(world, item)
    assert "outcome is unknown" in str(still.value) and posts(world) == []
    ledger_path = world["provider"] / "standin-ledger.json"      # the person looked, found nothing and settled the key (the provider's resolve)
    data = json.loads(ledger_path.read_text())
    del data["entries"][KEY]
    ledger_path.write_text(json.dumps(data))
    assert approve(world, item)["task_state"] == "done" and len(posts(world)) == 1


def test_a_failure_after_which_the_ledger_holds_the_key_as_published_stays_open_and_a_second_approval_does_not_post_twice(world):
    task, item = opened(world)
    mode(world, confirm="comment")
    with pytest.raises(ops_core.OpsError) as partial:
        approve(world, item)
    assert "ledger holds this key as published" in str(partial.value) and "retries only the comment" in str(partial.value)
    assert len(posts(world)) == 1 and task_state(world, task) == "waiting"
    mode(world)
    done = approve(world, item)
    assert done["task_state"] == "done" and done["result"]["replayed"] is True and done["result"]["first_comment"] == "posted" and len(posts(world)) == 1


# --- the long-content rule and the seam for POL-1 -----------------------------------------------------------------------------------------------------


def test_a_post_with_an_image_is_not_whole_on_a_messaging_card_and_one_without_is(world):
    task, item = opened(world)
    doc = effect_doc(world, task)
    assert effect_publish.on_cards(doc) is False and effect_publish.on_cards({"image": None}) is True and effect_publish.is_long(doc) is True
    kind = effects.module_for("publish")
    assert kind is effect_publish and kind.APPROVAL_GROUP == "approve-effect-publish"
    assert "terminal" in operations.EFFECT_CHANNELS and "page" in operations.EFFECT_CHANNELS
    assert not {"messaging", "mcp", "chat"} & set(operations.EFFECT_CHANNELS)
    (Path(world["path"]) / CONTENT).write_text(content_file(image=None), encoding="utf-8")
    task2, item2 = opened(world)
    assert effect_publish.on_cards(effect_doc(world, task2)) is True and "Image: (none)" in item2["body"]


def test_the_word_is_a_policy_kind_and_a_step_kind_and_a_bound_can_still_name_it_but_never_a_write_or_a_send(world, monkeypatch):
    monkeypatch.setattr(ops_core, "ROOT", str(st.REPO))      # the vocabulary of side effects is read from the checkout's scripts/validate.py
    kind = effects.module_for("publish")
    assert kind.POLICY is True and kind.STEP is True and kind.GATE is False and kind.PROVIDER_CLASS == "publisher:<platform>"
    assert "publish" in effects.policy_kinds() and "publish" in ops._bounds_words(), "the reply's bounds still name publish"
    assert effects.step_only_words() == ["send", "write"] and "send" not in ops._bounds_words() and "write" not in ops._bounds_words()
    assert effects.gate_kind("publish", ["publisher:linkedin"]) is None, "no skill's gate opens an effect of this kind: it opens a review, as before"
    assert ops_step_effects.step_effect_of is not None and "publish" in ops._effect_words()


def test_the_reply_path_of_the_same_word_is_the_replys_names_unchanged():
    kind = effects.module_for("publish")
    for name in ("PROVIDER_CLASS", "POLICY", "GATE", "VERB", "TARGET_CLASS", "policy_platform", "policy_effect", "policy_argv", "resolve_targets",
                 "policy_judgement"):
        assert getattr(kind, name) is getattr(effect_reply, name), name
    reply = {"policy": "p", "kind": "publish", "target": "t", "files": [], "items": 1, "idempotency_key": "k", "payload_sha256": "a" * 64,
             "args": ["--platform", "linkedin", "--post-id", "t", "--parent-comment-id", "c", "--text-file", "/x/r.txt"]}
    assert kind.describe(reply) == effect_reply.describe(reply) == "reply to a comment on post t"
    step = {"operation": "post", "platform": "linkedin", "idempotency_key": KEY, "text": "Hello there\n"}
    assert kind.describe(step) == f"publish a post on linkedin ({KEY}): Hello there"


# --- a published key's dry run names the post --------------------------------------------------------------------------------------------------


def real_shaped(posted=None):
    """A dry run of a post with a first comment, as providers/publisher/linkedin.py prints it: once the key is published, the comment's request names the
    post it comments on (raw in the body, percent-encoded in the address), and the ledger's lines say what it holds."""
    import urllib.parse
    out = {"dry_run": True, "platform": "linkedin", "idempotency_key": "k", "ledger": "/data/ledger.json",
           "requests": [{"method": "POST", "url": "https://api.example/rest/posts", "body": {"commentary": "the post"}},
                        {"method": "POST", "url": "https://api.example/v2/socialActions/" + (urllib.parse.quote(posted, safe="") if posted else "<URL-encoded post URN>")
                         + "/comments", "body": {"actor": "urn:li:person:<sub>", "object": posted or "<post URN returned by the Posts API>",
                                                 "message": {"text": "the comment"}}}],
           "existing_status": "published" if posted else None, "existing_post_urn": posted}
    return out


def test_the_dry_run_of_a_published_key_differs_only_where_it_names_the_post_and_a_changed_comment_still_differs():
    urn = "urn:li:share:7000000000000000001"
    before, after = publish_document.stable_dry_run(real_shaped()), publish_document.stable_dry_run(real_shaped(urn))
    assert before != after, "the real dry run does change once the key is published"
    assert urn not in json.dumps(after) and "urn%3Ali%3Ashare" not in json.dumps(after), "the post's id is a mark, in every form"
    assert publish_document.same_dry_run(before, after) and publish_document.same_dry_run(before, before)
    for change in (lambda d: d["requests"][1]["body"]["message"].update(text="another comment"), lambda d: d["requests"][0]["body"].update(commentary="x"),
                   lambda d: d["requests"][0].update(url="https://evil.example/rest/posts"), lambda d: d["requests"].append({}),
                   lambda d: d["requests"][1]["body"].update(object="a" * 400)):
        edited = real_shaped(urn)
        change(edited)
        assert not publish_document.same_dry_run(before, publish_document.stable_dry_run(edited)), change


# --- the ledger ------------------------------------------------------------------------------------------------------------------------------

SCHEDULER = '''# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
import json, os, sys
here = os.path.dirname(os.path.abspath(__file__))
json.dump({"SCHEDULER_HOME": os.environ.get("SCHEDULER_HOME")}, open(os.path.join(here, "env.json"), "w"))
mode = json.load(open(os.path.join(here, "mode.json"))) if os.path.isfile(os.path.join(here, "mode.json")) else {}
if mode.get("exit"):
    print("the scheduler failed", file=sys.stderr)
    sys.exit(mode["exit"])
if "raw" in mode:
    print(json.dumps(mode["raw"]))
    sys.exit(0)
path = os.path.join(here, "jobs.json")
print(json.dumps({"jobs": json.load(open(path)) if os.path.isfile(path) else []}))
'''


def scheduled(world, jobs):
    """A stand-in scheduler (class scheduler:job) whose list is `jobs`."""
    folder = world["tree"] / "providers" / "scheduler"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "standin.py").write_text(SCHEDULER, encoding="utf-8")
    (folder / "jobs.json").write_text(json.dumps(jobs), encoding="utf-8")


def test_the_ledger_is_in_the_document_and_on_the_card_and_the_provider_must_still_print_it_at_the_approval(world):
    task, item = opened(world)
    doc = effect_doc(world, task)
    where = str(world["provider"] / "standin-ledger.json")
    assert doc["ledger"] == where and where in item["body"] and item["title"].startswith("Publish now on linkedin")
    other = world["tmp"] / "moved"
    other.mkdir()
    os.environ["XDG_DATA_HOME"] = str(other)      # the provider now prints another ledger than the one the post was prepared with
    try:
        with pytest.raises(ops_core.OpsError) as refused:
            approve(world, item)
    finally:
        del os.environ["XDG_DATA_HOME"]
    assert "not the one the post was prepared with" in str(refused.value) and confirmed(world) == [] and posts(world) == []
    assert approve(world, item)["task_state"] == "done" and len(posts(world)) == 1


def test_a_ledger_variable_of_the_persons_environment_that_names_another_file_opens_no_effect(world, monkeypatch):
    monkeypatch.setenv("PUBLISHER_LINKEDIN_LEDGER", str(world["tmp"] / "mine" / "ledger.json"))
    out = run_task(world, add(world))
    assert out["ok"] is False and out["code"] == "ledger_differs" and "make them one file" in out["next"] and str(world["tmp"]) not in json.dumps(out)
    monkeypatch.setenv("PUBLISHER_LINKEDIN_LEDGER", str(world["provider"] / "standin-ledger.json"))      # the same file: nothing differs
    task, item = opened(world)
    monkeypatch.setenv("PUBLISHER_LINKEDIN_LEDGER", str(world["tmp"] / "mine" / "ledger.json"))      # changed after the preview
    with pytest.raises(ops_core.OpsError) as refused:
        approve(world, item)
    assert "your environment names the ledger" in str(refused.value) and posts(world) == []
    monkeypatch.delenv("PUBLISHER_LINKEDIN_LEDGER")
    assert approve(world, item)["task_state"] == "done" and len(posts(world)) == 1


def test_a_scheduled_job_for_this_key_pinned_to_another_ledger_opens_no_effect_and_blocks_the_approval(world):
    mine = str(world["provider"] / "standin-ledger.json")
    scheduled(world, [{"id": "2027-10-13-other", "argv": ["python", "/x/vote_job.py", "--key", "2027-10-13-other", "--ledger", "/elsewhere/l.json"]},
                      {"id": KEY, "argv": ["python", "/x/job.py", "--idempotency-key", KEY, "--ledger", mine]}, {"id": "no-argv"}, "junk"])
    task, item = opened(world)      # another key's job, and a job of this key on the same ledger, are no problem
    scheduled(world, [{"id": KEY, "argv": ["python", "/x/vote_job.py", "--key", KEY, "--ledger", "/elsewhere/l.json"]}])
    with pytest.raises(ops_core.OpsError) as refused:
        approve(world, item)
    assert "a scheduled job for this key is pinned to the ledger /elsewhere/l.json" in str(refused.value) and posts(world) == []
    out = run_task(world, add(world))
    assert out["code"] == "ledger_differs" and confirmed(world) == []
    scheduled(world, [])
    assert approve(world, item)["task_state"] == "done" and len(posts(world)) == 1


def scheduler_mode(world, **mode):
    (world["tree"] / "providers" / "scheduler" / "mode.json").write_text(json.dumps(mode), encoding="utf-8")


def test_a_scheduler_that_fails_or_answers_something_else_is_a_refusal_and_only_one_not_configured_is_no_jobs(world, monkeypatch):
    task, item = opened(world)      # no scheduler provider in the tree: not configured, so no job to compare with
    scheduled(world, [])
    for mode in ({"exit": 1}, {"raw": []}, {"raw": {"jobs": "none"}}, {"raw": {"nojobs": []}}):
        scheduler_mode(world, **mode)
        out = run_task(world, add(world))
        assert out["ok"] is False and out["code"] == "ledger_differs", mode
        with pytest.raises(ops_core.OpsError) as refused:
            approve(world, item)
        assert "not known whether a job for this key is pinned" in str(refused.value) and posts(world) == [], mode
    scheduler_mode(world, exit=3)      # the provider's own "not configured"
    assert approve(world, item)["task_state"] == "done" and len(posts(world)) == 1


def test_a_scheduler_that_times_out_is_a_refusal():
    class Resolve:
        class ProviderCallError(Exception):
            def __init__(self, kind, reason):
                super().__init__(reason)
                self.kind, self.reason = kind, reason

        @staticmethod
        def provider_environment(cls, env=None, passes=()):
            return {}

        @classmethod
        def call(cls, *a, **k):
            raise cls.ProviderCallError("timeout", "the provider ran over 60 s")
    why = publish_payload.ledger_problem(Resolve, "/nowhere", "linkedin", KEY, [], "/data/ledger.json")
    assert why and "not known whether a job for this key is pinned" in why


def test_the_scheduler_is_listed_with_the_folder_it_schedules_into_and_only_a_publishers_ledger_variable_is_passed_on(world, monkeypatch):
    scheduled(world, [])
    monkeypatch.setenv("SCHEDULER_HOME", str(world["tmp"] / "jobs-home"))
    monkeypatch.setenv("SOME_OTHER_LEDGER", str(world["tmp"] / "unrelated" / "ledger.json"))      # not a publisher's variable: never passed, never compared
    monkeypatch.setenv("PUBLISHER_NOWHERE_LEDGERS", str(world["tmp"] / "unrelated" / "ledger.json"))
    task, item = opened(world)
    assert json.loads((world["tree"] / "providers" / "scheduler" / "env.json").read_text())["SCHEDULER_HOME"] == str(world["tmp"] / "jobs-home")
    assert all(c["env"] and "SOME_OTHER_LEDGER" not in c["env"] and "PUBLISHER_NOWHERE_LEDGERS" not in c["env"] for c in calls(world))
    assert approve(world, item)["task_state"] == "done"


def test_the_mark_goes_only_inside_string_values_and_only_for_a_post_id_of_eight_characters_or_more():
    urn = "urn:li:share:7000000000000000001"
    answer = {"existing_post_urn": urn, "requests": [{"url": "https://api.example/" + urn + "/c", "body": {urn: 1, "object": urn, "n": 7}}]}
    kept = publish_document.stable_dry_run(answer)
    assert kept["requests"][0]["url"] == "https://api.example/" + publish_document.POST_MARK + "/c"
    assert kept["requests"][0]["body"] == {urn: 1, "object": publish_document.POST_MARK, "n": 7}, "a key and a number stay as they are"
    short = publish_document.stable_dry_run({"existing_post_urn": "abc", "requests": [{"url": "https://abc.example/abc", "abc": "abcabc"}]})
    assert short["requests"][0] == {"url": "https://abc.example/abc", "abc": "abcabc"}, "a short id is never swapped"
    with pytest.raises(effects.EffectError) as refused:
        publish_document.stable_dry_run({"a": object()})
    assert refused.value.kind == "usage"
    with pytest.raises(effects.EffectError):
        publish_document.stable_dry_run({"a": "b" * (publish_document.DRY_RUN_MAX + 1)})


# --- the structure: a step kind can reach nothing that publishes ----------------------------------------------------------------------------------


def test_the_publisher_service_a_step_kind_is_given_can_only_check_and_preview():
    reader = ops_step_seams.PublisherReader({"project": "/p", "data_dir": "/d"}, str(st.REPO))
    assert {name for name in dir(reader) if not name.startswith("_")} == {"provider", "check", "preview"}
    text = (st.REPO / "runtime" / "ops_step_seams.py").read_text(encoding="utf-8")
    assert "--confirmed" not in text, "the file holds no way to publish or send"


def test_the_step_kind_imports_only_the_pure_document_and_the_engine():
    import ast
    tree = ast.parse((st.REPO / "runtime" / "step_publish_post.py").read_text(encoding="utf-8"))
    imported = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    imported |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert imported - {"__future__", "os", "sys"} == {"publish_document", "steps"}
    strings = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    assert not strings & {"--confirmed", "--dry-run", "--at", "--ledger"}


# --- the publishing skill's script, whose fields this reads ---------------------------------------------------------------------------------------


def test_the_fields_of_payload_py_that_the_runtime_reads_are_where_it_expects_them(world, tmp_path):
    """A later change to skills/mkt-publish/scripts/payload.py that moves one of these fields fails here, not in a live publication."""
    out = tmp_path / "pinned" / "payload"
    done = subprocess.run([sys.executable, str(world["tree"] / "skills" / "mkt-publish" / "scripts" / "payload.py"), "build", "--content", CONTENT,
                           "--platform", "linkedin", "--platform-file", str(world["tree"] / "shared" / "references" / "platforms" / "linkedin.json"),
                           "--workbench", str(world["tree"]), "--out", str(out)],
                          cwd=world["path"], capture_output=True, text=True, timeout=60, env={**os.environ, "HOME": str(tmp_path)})
    assert done.returncode == 0, done.stderr
    answer = json.loads(done.stdout)
    assert {"out", "platform", "posts", "jobs_written"} <= set(answer) and answer["platform"] == "linkedin" and answer["jobs_written"] is False
    [entry] = answer["posts"]
    assert {"key", "at", "scope", "post_file", "post_sha256", "comment_file", "comment_sha256", "image_file", "image_sha256", "image_source"} <= set(entry)
    assert entry["key"] == KEY and entry["at"] == SLOT and entry["image_source"] == IMAGE
    assert Path(entry["post_file"]).read_bytes() == (TEXT + "\n").encode("utf-8") and sha(Path(entry["post_file"]).read_bytes()) == entry["post_sha256"]
    assert Path(entry["image_file"]).name == "image.png"
    built = publish_payload.build(str(world["tree"]), world["path"], CONTENT, "linkedin", work_dir=str(tmp_path))
    try:
        assert built.key == KEY and built.at == SLOT and built.text == TEXT + "\n" and built.comment == COMMENT + "\n"
        assert built.image == {"source": IMAGE, "name": "image.png", "bytes": len(PNG), "sha256": sha(PNG)}
        assert oct(Path(built.folder).stat().st_mode & 0o777) == "0o700"
    finally:
        built.cleanup()
    assert not Path(built.folder).exists()
    assert not list(Path(world["path"]).rglob("job.json")), "no --publisher: no job is written, nothing is scheduled"


def test_payload_py_runs_isolated_and_the_project_is_its_working_folder(world, tmp_path):
    seen = {}

    def spy(script, args, cwd, timeout):
        seen.update(script=script, args=args, cwd=cwd)
        return st.load("isolated").run_script(script, args, cwd=cwd, timeout=timeout)
    built = publish_payload.build(str(world["tree"]), world["path"], CONTENT, "linkedin", work_dir=str(tmp_path), run_script=spy)
    built.cleanup()
    assert seen["script"].endswith("skills/mkt-publish/scripts/payload.py") and seen["cwd"] == world["path"]
    assert "--publisher" not in seen["args"] and seen["args"][:1] == ["build"]
