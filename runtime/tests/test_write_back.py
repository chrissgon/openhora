"""Tests of the write-back to the documents platform as an external effect (runtime/step_write_back.py, runtime/effect_write.py,
runtime/ops_step_effects.py; package P8, decision D17 direction 2). The platform is the Notion provider against its stand-in service
(providers/documents/tests/fake_notion.py): no workspace is ever called. The cases of the plan's "Done when": a write without the
approval of its exact content is refused by structure; one with it runs once and records; a changed target id changes the hash and the
approval no longer covers it; a target edited since it was read stops the write and asks. Fictional names throughout.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_write_back.py
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

import standin_tree as st
from test_documents_mirror import Platform

lab = st.load("lab")
ops = st.load("ops")
ops_core = st.load("ops_core")
ops_steps = st.load("ops_steps")
docs = st.load("documents")
effects = st.load("effects")
effect_write = st.load("effect_write")
ops_step_effects = st.load("ops_step_effects")
step_write_back = st.load("step_write_back")
steps = st.load("steps")
operations = st.load("operations")

CONTENT = "# Plan for the harbour market\n\nOpen at nine.\n\n- stalls: forty\n- music: yes\n"
PATH = "docs/outputs/plan-update.md"
SEED = "# Plan\n\nOpen at ten.\n"


def sha(text):
    return hashlib.sha256(text if isinstance(text, bytes) else text.encode("utf-8")).hexdigest()


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("WB_LOCAL_EVIDENCE_DIR", str(tmp_path / "evidence"))
    built = st.build(tmp_path, monkeypatch, lab)
    folder = built["tree"] / "providers" / "documents"
    folder.mkdir(parents=True)
    for name in ("notion.py", "notion_blocks.py"):
        shutil.copyfile(st.REPO / "providers" / "documents" / name, folder / name)
    platform = Platform(tmp_path)
    config = json.loads(platform.config.read_text(encoding="utf-8"))
    path = built["project"] / "docs" / "workbench" / "runtime.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["documents"] = config
    path.write_text(json.dumps(raw), encoding="utf-8")
    monkeypatch.setattr(ops_core, "ROOT", str(built["tree"]))
    calls = []

    def call(cfg, root, verb, args, timeout=docs.TIMEOUT):
        calls.append(("write-dry-run" if verb == "write" and "--dry-run" in args else verb, [a for a in args if a != "--confirmed"]))
        return platform.mirror_call(cfg, root, verb, args, timeout)

    monkeypatch.setattr(docs, "call", call)
    project = str(built["project"])
    ops.accept_config(project, ops.project_config.load(project)["sha256"])
    seed = tmp_path / "seed.md"
    seed.write_text(SEED, encoding="utf-8")
    page = platform.call("write", ["--path", "docs/notes/plan.md", "--markdown-file", str(seed), "--idempotency-key", "seed-1", "--confirmed"])
    (built["project"] / "docs" / "outputs").mkdir(parents=True)
    (built["project"] / PATH).write_text(CONTENT, encoding="utf-8")
    return {**built, "path": project, "platform": platform, "page": page["id"], "calls": calls, "tmp": tmp_path}


def writes(world):
    return [c for c in world["calls"] if c[0] == "write"]


def add(world, **extra):
    ctx = ops_core.context(world["path"])
    args = {"target": world["page"], "content": PATH, **extra}
    made = steps.add_task(ctx["store"], ctx["conn"], "write-back", args, key="write-back", title="Write the plan back", text="Write it.")
    return made["task"]


def run_task(world, task):
    ctx = ops_core.context(world["path"])
    if ctx["store"].task_get(ctx["conn"], task)["state"] == "failed":      # a failed step is retried by the person, then runs again
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


def opened(world):
    task = add(world)
    out = run_task(world, task)
    assert out["ok"] is True and out["task_state"] == "waiting", out
    return task, pending_of(world, task)


# --- what the person is shown ------------------------------------------------------------------------------------------------------


def test_the_task_reads_the_page_and_opens_an_effect_with_the_hash_of_the_exact_content_and_writes_nothing(world):
    task, item = opened(world)
    assert item["kind"] == "effect" and len(item["payload_sha256"]) == 64
    assert writes(world) == [] and world["platform"].text(world["page"]) == SEED, "nothing was written to the platform"
    body = item["body"]
    assert CONTENT.rstrip("\n") in body, "the preview holds the content whole"
    for needle in (world["page"], PATH, sha(CONTENT.encode("utf-8").decode()), item["payload_sha256"], "approve", "--sha256"):
        assert needle in body, needle
    assert sha(world["platform"].text(world["page"])) in body, "and the hash of the text the page held when it was read"
    assert item["payload"]["step"] == {"kind": "write-back", "step": "write"} and item["payload"]["effect"]["target"] == world["page"]
    assert "content" not in json.dumps(item["payload"]).replace('"content_sha256"', ""), "the state keeps hashes, not the text"


def test_the_hash_is_the_hash_of_the_effect_file_and_covers_the_target_and_the_content(world):
    task, item = opened(world)
    cfg = ops_core.context(world["path"])["cfg"]
    path = Path(ops_step_effects.effect_dir(cfg, task, 0)) / "effect.json"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == item["payload_sha256"]
    doc = json.loads(path.read_text(encoding="ascii"))
    assert doc["target"]["id"] == world["page"] and doc["content"] == CONTENT and doc["effect"] == "write" and doc["provider"] == "notion"
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    for folder in (path.parent, path.parent.parent, path.parent.parent.parent):
        assert oct(folder.stat().st_mode & 0o777) == "0o700", folder


def test_a_different_target_is_a_different_hash_and_the_first_approval_covers_nothing_of_it(world):
    a = effect_write.document(task_id=1, provider="notion", target_id=world["page"], path=PATH, content=CONTENT,
                              base_text_sha256=sha(SEED), base_version=None)
    other = "f" * 32
    b = effect_write.document(task_id=1, provider="notion", target_id=other, path=PATH, content=CONTENT,
                              base_text_sha256=sha(SEED), base_version=None)
    digest_a, digest_b = sha(effects._text(a)), sha(effects._text(b))
    assert digest_a != digest_b and a["content_sha256"] == b["content_sha256"], "only the target id differs"
    approval = {"scope": "action", "status": "pending-execution", "payload_sha256": digest_a}
    with pytest.raises(effects.EffectError) as refused:
        effect_write.execute(b, approval, lambda verb, args: pytest.fail("the platform was called"), "k")
    assert refused.value.kind == "deviation" and "no approval of this exact content" in refused.value.reason


def test_an_effect_file_edited_after_the_preview_is_not_the_approved_one_and_nothing_is_written(world):
    task, item = opened(world)
    cfg = ops_core.context(world["path"])["cfg"]
    path = Path(ops_step_effects.effect_dir(cfg, task, 0)) / "effect.json"
    doc = json.loads(path.read_text(encoding="ascii"))
    doc["target"]["id"] = "f" * 32
    path.write_text(json.dumps(doc, sort_keys=True, indent=1) + "\n", encoding="ascii")
    with pytest.raises(ops_core.OpsError) as refused:
        ops.approve(world["path"], item["id"], sha256=item["payload_sha256"], channel="terminal")
    assert "not the one approved" in str(refused.value) and writes(world) == []
    assert world["platform"].text(world["page"]) == SEED and task_state(world, task) == "waiting"


# --- the approval ------------------------------------------------------------------------------------------------------------------


def test_limit_31_a_write_without_the_approval_of_its_exact_content_is_refused_by_structure(world):
    task, item = opened(world)
    sha_wrong = "0" * 64
    for channel in ("messaging", "mcp", "conversation", None):
        with pytest.raises(ops_core.OpsError) as refused:
            ops.approve(world["path"], item["id"], sha256=item["payload_sha256"], channel=channel)
        assert "approved in the terminal" in str(refused.value)
    with pytest.raises(ops_core.OpsError):
        ops.approve(world["path"], item["id"], sha256=None, channel="terminal")
    with pytest.raises(ops_core.OpsError) as refused:
        ops.approve(world["path"], item["id"], sha256=sha_wrong, channel="terminal")
    assert "nothing was approved" in str(refused.value)
    with pytest.raises(ops_core.OpsError):
        ops.answer(world["path"], item["id"], "approve")          # a word typed into a conversation is no approval either
    assert writes(world) == [] and world["platform"].text(world["page"]) == SEED
    # the effect module itself refuses what is not an approval of this document, whoever calls it
    cfg = ops_core.context(world["path"])["cfg"]
    doc = json.loads((Path(ops_step_effects.effect_dir(cfg, task, 0)) / "effect.json").read_text(encoding="ascii"))
    for approval in (None, {}, {"scope": "plan", "status": "pending-execution", "payload_sha256": item["payload_sha256"]},
                     {"scope": "action", "status": "revoked", "payload_sha256": item["payload_sha256"]},
                     {"scope": "action", "status": "executed", "payload_sha256": item["payload_sha256"]},
                     {"scope": "action", "status": "pending-execution", "payload_sha256": sha_wrong}):
        with pytest.raises(effects.EffectError):
            effect_write.execute(doc, approval, lambda verb, args: pytest.fail("the platform was called"), "k")
    assert writes(world) == []


@pytest.mark.parametrize("channel", ["terminal", "page"])
def test_with_the_approval_of_its_hash_from_the_terminal_or_the_page_it_writes_once_and_records(world, channel):
    task, item = opened(world)
    done = ops.approve(world["path"], item["id"], sha256=item["payload_sha256"], channel=channel)
    assert done["task_state"] == "done" and done["result"]["written"] is True and done["result"]["bytes"] == len(CONTENT.encode())
    assert done["result"]["content_sha256"] == sha(CONTENT)
    assert len(writes(world)) == 1 and world["platform"].text(world["page"]).startswith("# Plan for the harbour market")
    assert task_state(world, task) == "done"
    ctx = ops_core.context(world["path"])
    row = ctx["store"].approval_get(ctx["conn"], done["approval_id"])
    assert row["status"] == "executed" and row["scope"] == "action" and row["payload_sha256"] == item["payload_sha256"]
    settled = ctx["store"].pending_get(ctx["conn"], item["id"])
    assert settled["status"] == "resolved" and settled["resolution"] == "approved" and settled["payload"]["result"]["written"] is True
    # a second approval, or a second run of the task, writes nothing more
    with pytest.raises(ops_core.OpsError):
        ops.approve(world["path"], item["id"], sha256=item["payload_sha256"], channel=channel)
    assert len(writes(world)) == 1


def test_the_state_file_gets_the_generated_row_of_the_executed_approval(world):
    task, item = opened(world)
    done = ops.approve(world["path"], item["id"], sha256=item["payload_sha256"], channel="terminal")
    text = (Path(world["path"]) / "docs" / "workbench" / "state.md").read_text(encoding="utf-8")
    assert done["state"]["written"] is True
    assert f"sha256:{item['payload_sha256']}" in text and "write" in text and "executed" in text


def test_the_write_replaces_the_whole_page_with_the_exact_text(world):
    task, item = opened(world)
    ops.approve(world["path"], item["id"], sha256=item["payload_sha256"], channel="terminal")
    expected = world["platform"].blocks.round_trip(CONTENT)
    assert world["platform"].text(world["page"]) == expected


def test_a_rejected_effect_cancels_the_task_and_writes_nothing(world):
    task, item = opened(world)
    ops.reject(world["path"], item["id"], "not now")
    assert task_state(world, task) == "cancelled" and writes(world) == [] and world["platform"].text(world["page"]) == SEED


# --- the target edited since it was read ----------------------------------------------------------------------------------------------


def test_a_target_edited_since_it_was_read_stops_the_write_and_asks_again_about_the_page_as_it_is(world):
    task, item = opened(world)
    world["platform"].person_edits(world["page"], "Open at ten.", "Open at eleven, the council asked.")
    edited = world["platform"].text(world["page"])
    with pytest.raises(ops_core.OpsError) as stopped:
        ops.approve(world["path"], item["id"], sha256=item["payload_sha256"], channel="terminal")
    assert "not the one the task read" in str(stopped.value) and "starts over" in str(stopped.value)
    assert writes(world) == [] and world["platform"].text(world["page"]) == edited, "the person's edit is untouched"
    ctx = ops_core.context(world["path"])
    old = ctx["store"].pending_get(ctx["conn"], item["id"])
    assert old["status"] == "resolved" and old["resolution"] == "answered" and task_state(world, task) == "ready"
    assert ctx["store"].approval_get(ctx["conn"], 1)["status"] == "revoked", "the approval of the stopped attempt does not stay valid"
    # started again, the task reads the page as it is now and asks about that
    out = run_task(world, task)
    assert out["ok"] is True and out["task_state"] == "waiting"
    new = pending_of(world, task)
    assert new["id"] != item["id"] and new["payload_sha256"] != item["payload_sha256"] and new["payload"]["cycle"] == 1
    assert sha(edited) in new["body"], "the new preview names the page as the person left it"
    done = ops.approve(world["path"], new["id"], sha256=new["payload_sha256"], channel="terminal")
    assert done["task_state"] == "done" and len(writes(world)) == 1
    with pytest.raises(ops_core.OpsError):      # the old hash covers nothing now
        ops.approve(world["path"], item["id"], sha256=item["payload_sha256"], channel="terminal")


def test_the_check_is_the_text_not_the_version_so_a_page_touched_and_put_back_is_not_stale(world):
    task, item = opened(world)
    world["platform"].person_edits(world["page"], "Open at ten.", "Open at twelve.")
    world["platform"].person_edits(world["page"], "Open at twelve.", "Open at ten.")
    done = ops.approve(world["path"], item["id"], sha256=item["payload_sha256"], channel="terminal")
    assert done["task_state"] == "done" and len(writes(world)) == 1


def notion_source(world, text, source_id="notes", page=None):
    """A source bound to the target page (a Notion source), with one version holding `text`."""
    ctx = ops_core.context(world["path"])
    sources = st.load("sources")
    address = "https://www.notion.so/Plan-" + (page or world["page"]).replace("-", "")
    row = sources.register(ctx, source_id, "notion", address)
    sources.import_version(ctx, row, text.encode("utf-8"), convert=None, kind="notion")


def test_a_source_pin_that_no_longer_matches_the_page_stops_the_task_when_it_reads(world):
    # the version the task read (the source) is not the page now: the work was done on an older page
    task = add(world, source="notes")
    notion_source(world, SEED + "an older line\n")
    out = run_task(world, task)
    assert out["ok"] is False and out["code"] == "target_changed" and writes(world) == []


def test_a_source_pin_that_matches_the_page_lets_the_task_go_on_to_the_effect(world):
    task = add(world, source="notes")
    notion_source(world, SEED)
    out = run_task(world, task)
    assert out["ok"] is True and out["task_state"] == "waiting" and writes(world) == []


def test_a_source_that_is_not_the_target_page_stops_the_task_even_when_its_text_is_the_same(world):
    task = add(world, source="notes")
    notion_source(world, SEED, page="0123456789abcdef0123456789abcdef")
    out = run_task(world, task)
    assert out["ok"] is False and out["code"] == "source_not_target" and writes(world) == []


# --- what stops it before the effect is opened ---------------------------------------------------------------------------------------------


def test_content_that_is_missing_too_large_a_link_or_holds_a_credential_opens_no_effect(world):
    root = Path(world["path"])
    key = "sk-" + "ant-" + "api03-" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6"
    (root / PATH).write_text(f"The key: {key}\n", encoding="utf-8")
    task = add(world)
    out = run_task(world, task)
    assert out["ok"] is False and out["code"] == "content_refused" and key not in json.dumps(out)
    (root / PATH).write_text("x" * (effect_write.CONTENT_MAX + 1), encoding="utf-8")
    assert run_task(world, task)["code"] in ("content_too_large",)
    (root / PATH).unlink()
    assert run_task(world, task)["code"] == "content_missing"
    (root / "docs" / "real.md").write_text("fine\n", encoding="utf-8")
    (root / PATH).symlink_to(root / "docs" / "real.md")
    assert run_task(world, task)["code"] == "path_unsafe"
    assert writes(world) == []
    ctx = ops_core.context(world["path"])
    assert ctx["store"].pending_list(ctx["conn"], "open", task) == []


def test_the_arguments_are_checked_when_the_task_is_planned():
    for args in ({}, {"target": "x"}, {"target": "short", "content": "docs/a.md"}, {"target": "a" * 32, "content": "other/a.md"},
                 {"target": "a" * 32, "content": "docs/a.txt"}, {"target": "a" * 32, "content": "docs/../a.md"},
                 {"target": "a" * 32, "content": "docs/a.md", "extra": 1}, {"target": "a" * 32, "content": "docs/a.md", "source": "Bad Id"},
                 {"target": "https://www.notion.so/Plan-" + "a" * 32, "content": "docs/a.md"}):
        with pytest.raises(steps.StepFailure) as refused:
            steps.plan_task("write-back", args, key="k", title="t", text="x")
        assert refused.value.code == "bad_args", args
    ok = steps.plan_task("write-back", {"target": "a" * 32, "content": "docs/a.md"}, key="k", title="t", text="x")
    assert ok["footprint"] == [] and ok["step"] == "write-back"


def test_a_configuration_without_a_documents_platform_or_with_expired_bounds_opens_no_effect(world):
    task = add(world)
    path = Path(world["path"]) / "docs" / "workbench" / "runtime.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    expired = dict(raw, documents=dict(raw["documents"], expires="2020-01-01"))
    path.write_text(json.dumps(expired), encoding="utf-8")
    ops.accept_config(world["path"], ops.project_config.load(world["path"])["sha256"])
    assert run_task(world, task)["code"] == "bounds_expired"
    gone = {k: v for k, v in raw.items() if k != "documents"}
    path.write_text(json.dumps(gone), encoding="utf-8")
    ops.accept_config(world["path"], ops.project_config.load(world["path"])["sha256"])
    assert run_task(world, task)["code"] == "not_configured" and writes(world) == []


def test_bounds_that_expire_between_the_preview_and_the_approval_stop_the_write(world):
    task, item = opened(world)
    path = Path(world["path"]) / "docs" / "workbench" / "runtime.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps(dict(raw, documents=dict(raw["documents"], expires="2020-01-01"))), encoding="utf-8")
    ops.accept_config(world["path"], ops.project_config.load(world["path"])["sha256"])
    with pytest.raises(ops_core.OpsError) as refused:
        ops.approve(world["path"], item["id"], sha256=item["payload_sha256"], channel="terminal")
    assert "expired" in str(refused.value) and writes(world) == []


def test_a_provider_that_cannot_write_fails_with_nothing_written_and_the_effect_stays_open(world, monkeypatch):
    task, item = opened(world)
    real = docs.call

    def no_write(cfg, root, verb, args, timeout=docs.TIMEOUT):
        if verb == "write":
            raise docs.DocumentsError("failed", "write is not supported by this provider")
        return real(cfg, root, verb, args, timeout)
    monkeypatch.setattr(docs, "call", no_write)
    with pytest.raises(ops_core.OpsError) as refused:
        ops.approve(world["path"], item["id"], sha256=item["payload_sha256"], channel="terminal")
    assert "not supported" in str(refused.value) and "stays open" in str(refused.value)
    assert task_state(world, task) == "waiting" and world["platform"].text(world["page"]) == SEED


def test_the_effect_kind_names_no_provider_and_is_registered_as_a_word_of_the_vocabulary():
    assert effects.KINDS["write"] == "effect_write"
    module = effects.module_for("write")
    assert module.PROVIDER_CLASS == "integration:documents" and module.GATE is False and module.POLICY is False and module.STEP is True
    assert "write" not in effects.policy_kinds()
    text = Path(effect_write.__file__).read_text(encoding="utf-8")
    code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    body = code.split('"""', 2)[2]               # the code after the module's text
    for name in ("notion", "gdrive", "drive"):
        assert name not in body.lower(), name
    assert effects.gate_kind("write", ["integration:documents"]) is None, "no skill's confirmation gate opens a write"


def test_the_word_is_in_the_vocabulary_of_the_contract_and_of_the_validator():
    validate = (st.REPO / "scripts" / "validate.py").read_text(encoding="utf-8")
    assert '"write"' in validate.split("SIDE_EFFECTS = (", 1)[1].split(")", 1)[0]
    table = (st.REPO / "contracts" / "environment.md").read_text(encoding="utf-8")
    assert "| `write` |" in table
    assert "write" in ops._effect_words()


# --- a lost answer, a partial replace, a linked folder, the bounds ------------------------------------------------------------------------


def test_a_write_whose_answer_was_lost_is_recorded_as_replayed_when_the_same_hash_is_approved_again(world):
    task, item = opened(world)
    world["platform"].lost_answer = True                     # the next write is carried out and its answer is lost
    with pytest.raises(ops_core.OpsError) as lost:
        ops.approve(world["path"], item["id"], sha256=item["payload_sha256"], channel="terminal")
    assert "outcome is unknown: read the page" in str(lost.value) and "stays open" in str(lost.value)
    assert "Nothing was written" not in str(lost.value) and "nothing was written" not in str(lost.value)
    assert len(writes(world)) == 1 and task_state(world, task) == "waiting"
    assert world["platform"].text(world["page"]) == world["platform"].blocks.round_trip(CONTENT), "the page holds the content"
    world["platform"].lost_answer = False
    done = ops.approve(world["path"], item["id"], sha256=item["payload_sha256"], channel="terminal")
    assert done["task_state"] == "done" and done["result"]["replayed"] is True and done["result"]["written"] is True
    assert len(writes(world)) == 1, "the replay wrote nothing again"


def test_a_page_left_half_written_by_a_failed_replace_is_not_called_unwritten(world):
    task, item = opened(world)
    page = world["page"]
    blocks = world["platform"].blocks
    # a replace that appended the new blocks and failed before deleting the old ones: both are on the page
    world["platform"].fake.person_replaces_body(page, blocks.to_blocks(SEED + "\n" + CONTENT))
    with pytest.raises(ops_core.OpsError) as stopped:
        ops.approve(world["path"], item["id"], sha256=item["payload_sha256"], channel="terminal")
    text = str(stopped.value)
    assert "an earlier attempt of this write did not finish" in text and "Nothing was written by this attempt" in text
    assert writes(world) == [] and task_state(world, task) == "ready"


def test_a_write_call_that_fails_leaves_the_outcome_unknown_not_unwritten(world, monkeypatch):
    task, item = opened(world)
    real = docs.call

    def failing(cfg, root, verb, args, timeout=docs.TIMEOUT):
        if verb == "write" and "--confirmed" in args:
            raise docs.DocumentsError("failed", "the provider ran over 180 s")
        return real(cfg, root, verb, args, timeout)
    monkeypatch.setattr(docs, "call", failing)
    with pytest.raises(ops_core.OpsError) as unknown:
        ops.approve(world["path"], item["id"], sha256=item["payload_sha256"], channel="terminal")
    assert "outcome is unknown" in str(unknown.value) and "ran over 180 s" in str(unknown.value)
    assert task_state(world, task) == "waiting"


def test_content_read_through_a_linked_folder_is_refused_so_the_sources_folder_cannot_be_previewed(world):
    root = Path(world["path"])
    ctx = ops_core.context(world["path"])
    kept = Path(ctx["cfg"]["sources_dir"])
    (kept / "secret-source").mkdir(parents=True, exist_ok=True)
    (kept / "secret-source" / "page.md").write_text("Text of a source that is not for the platform.\n", encoding="utf-8")
    (root / "docs" / "linked").symlink_to(kept / "secret-source")
    task = add(world, content="docs/linked/page.md")
    out = run_task(world, task)
    assert out["ok"] is False and out["code"] in ("path_unsafe", "protected_path") and writes(world) == []
    ctx = ops_core.context(world["path"])
    assert ctx["store"].pending_list(ctx["conn"], "open", task) == []


def test_a_standing_approval_cannot_name_the_write_effect():
    bounds = {"policy": "write-back", "agent": "runtime", "effects": ["write"], "targets": ["*"], "files": ["docs/*"], "max_per_day": 1,
              "max_items_per_run": 1}
    with pytest.raises(ValueError):
        st.load("autonomy").bounds_of(bounds, "runtime", ops._bounds_words())
    assert "write" in ops._effect_words() and "write" not in ops._bounds_words() and "publish" in ops._bounds_words()
