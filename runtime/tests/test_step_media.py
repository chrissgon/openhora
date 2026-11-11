"""Tests of the step kind `media` (runtime/step_media.py, package V1b1-4): its order and gate, its arguments, `take`, each step's engine arguments, the
two stops, the failures by closed code and what a step prepared again removes. The engine is a fake that writes the synthetic output of a verb; the
store of recordings is the real one over a temporary folder; nothing is called and every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_step_media.py
"""
from __future__ import annotations

import json
import os

import pytest

import standin_tree as st
cap = st.load("captions")
from media_kit import (FakeEngine, KEY, POST, RENDER_BLOCKS, add, flag, media, open_items, ops, ops_core, ops_steps, ops_step_seams, post_text, run_task, sha,
                       step_media, steps, task_row, to_gate, to_review, work_file, world)  # noqa: F401  (world is a fixture)

dd = st.load("deliver_document")

FRESH = "0123456789abcdef"


def test_the_kind_registers_in_vd10s_order_with_the_gate_redoing_remap_and_no_footprint_and_not_unattended():
    kind = steps.kind_of("media")
    assert kind.order == ("take", "transcribe", "analyse", "still", "retakes", "align-proposal", "review", "remap", "base", "align", "check",
                          "render", "cover", "verify", "preview", "document", "deliver")
    assert kind.stops == ("review",) and set(kind.side_steps) == {"still", "preview"} and kind.unattended is False and kind.effectful == ()
    assert kind.gates["deliver"].redo == "remap" and kind.gates["deliver"].word == "deliver" and kind.footprint({"media": FRESH, "post": POST}) == ()


@pytest.mark.parametrize("args", [None, {}, {"media": FRESH}, {"media": FRESH, "post": POST, "extra": 1}, {"media": "ABCDEF0123456789", "post": POST},
                                  {"media": "abc", "post": POST}, {"media": FRESH, "post": "docs/other/x.md"}, {"media": FRESH, "post": "../docs/marketing/content/x.md"},
                                  {"media": FRESH, "post": "docs/marketing/content/x.comments.md"}])
def test_check_refuses_a_bad_id_a_post_outside_the_content_folder_a_comments_file_and_an_extra_key(args):
    with pytest.raises(steps.StepFailure) as refused:
        step_media.check(args)
    assert refused.value.code == "bad_args"


def test_check_takes_the_rule_of_the_publishing_path_for_a_post_so_the_two_never_differ():
    long_ok = "docs/marketing/content/" + "a" * 80 + ".md"
    long_bad = "docs/marketing/content/" + "a" * 81 + ".md"
    assert step_media.check({"media": FRESH, "post": long_ok}) == {"media": FRESH, "post": long_ok}
    with pytest.raises(steps.StepFailure):
        step_media.check({"media": FRESH, "post": long_bad})


def test_the_default_model_is_a_name_pinned_with_a_sha256_in_the_transcribers_table_which_this_test_reads_as_a_file():
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "providers", "transcriber", "models.json")
    with open(path, encoding="utf-8") as f:
        pinned = {m["name"]: m for m in json.load(f)["models"]}
    assert step_media.DEFAULT_TRANSCRIBER_MODEL in pinned and pinned[step_media.DEFAULT_TRANSCRIBER_MODEL]["sha256"]
    assert pinned[step_media.DEFAULT_TRANSCRIBER_MODEL]["multilingual"] is True and step_media.DEFAULT_LANGUAGE == "pt"


def test_a_full_run_stops_at_the_review_and_after_continue_at_the_deliver_gate_with_the_hash_of_the_written_document(world):
    task = to_review(world)
    assert [c["verb"] for c in world["engine"].calls] == ["transcribe", "analyse", "still", "base", "align"]
    [review] = open_items(world, task)
    assert review["kind"] == "question" and review["title"] == "Check the captions" and "words were transcribed" in review["body"]
    assert "Edit the captions, then continue." in review["body"] and "Aster" not in review["body"]
    ops.answer(world["path"], review["id"], "continue")
    out = run_task(world, task)
    assert out["stopped"] == "deliver"
    [gate] = open_items(world, task)
    assert gate["kind"] == "effect" and gate["payload"]["gate"] == "deliver" and gate["payload"]["step"] == {"kind": "media", "step": "deliver"}
    ctx = ops_core.context(world["path"])
    effect = ops_step_seams.EffectFiles(ctx["cfg"]).read(task, 0, gate["payload_sha256"])
    assert effect["video"]["sha256"] == sha(b"the rendered video of Aster Lane " + b"one") and effect["recording"] == world["rid"]
    assert effect["platform"] == "instagram" and effect["post"] == POST
    assert effect["preview"] == {"sha256": effect["video"]["sha256"], "size": effect["video"]["size"], "from_sha256": effect["video"]["sha256"]}, "the render is its own preview"
    assert dd.on_cards(effect) is True and gate["payload"]["card"] == dd.card_lines(effect, gate["payload_sha256"]) and gate["title"] == "Deliver the video"
    assert effect["blocks"] == [{"id": k, "sha256": v} for k, v in sorted(RENDER_BLOCKS.items())] and effect["cover"]["size"] > 0
    assert effect["verify"] == {"passed": True, "platform": "instagram"} and gate["payload_sha256"] in gate["body"]


def test_take_refuses_a_post_with_no_network_line_a_platform_with_no_video_entry_and_a_post_with_no_script(world):
    project = world["path"]
    for text, code in ((post_text(network=None), "no_platform"), (post_text(network="linkedin"), "platform_has_no_video"), (post_text(script=False), "no_script")):
        with open(os.path.join(project, POST), "w", encoding="utf-8") as f:
            f.write(text)
        task = add(world)
        out = run_task(world, task)
        assert out["ok"] is False and out["failed"] == "take" and out["code"] == code, (code, out)
    assert world["engine"].calls == []


def test_take_refuses_a_missing_post_and_a_recording_bound_to_another_live_task_and_one_whose_task_failed_may_be_taken(world):
    os.unlink(os.path.join(world["path"], POST))
    assert run_task(world, add(world))["code"] == "post_missing"
    with open(os.path.join(world["path"], POST), "w", encoding="utf-8") as f:
        f.write(post_text())
    first = add(world)
    assert run_task(world, first)["stopped"] == "review"
    second = add(world)
    out = run_task(world, second)
    assert out["ok"] is False and out["failed"] == "take" and out["code"] == "recording_taken"
    ctx = ops_core.context(world["path"])
    ctx["store"].step_task_move(ctx["conn"], first, state="failed", note="x", by="code")      # the first task failed: the recording is free again
    assert run_task(world, second)["stopped"] == "review"
    assert media.load(world["data"], world["rid"])["task"] == second


def test_each_engine_call_has_the_arguments_of_its_step(world):
    to_review(world)
    engine, root = world["engine"], world["tmp"]
    folder = media.folder_of(world["data"], world["rid"])
    [tr] = engine.of("transcribe")
    assert tr["cls"] == "transcriber:speech" and tr["timeout"] == 1920
    assert tr["args"] == ["--in", os.path.join(folder, "raw.mp4"), "--model", "small", "--language", "pt", "--timestamps", "dtw",
                          "--out", os.path.join(folder, "transcript.json"), "--max-seconds", "300"]
    [an] = engine.of("analyse")
    assert an["cls"] == "renderer:video" and an["args"] == ["--in", os.path.join(folder, "raw.mp4"), "--out", os.path.join(folder, "analysis.json")]
    [still] = engine.of("still")
    assert still["args"] == ["--in", os.path.join(folder, "raw.mp4"), "--at-ms", "1500", "--out", folder]
    retakes, align = engine.of("base")[0], engine.of("align")[0]
    assert retakes["args"] == ["--transcript", os.path.join(folder, "transcript.json"), "--analysis", os.path.join(folder, "analysis.json"),
                               "--out", os.path.join(folder, "proposal.edl.json"), "--retakes", "propose"]
    assert flag(align["args"], "--post").endswith(POST) and flag(align["args"], "--transcript") == os.path.join(folder, "transcript.json")
    assert flag(align["args"], "--checker").endswith(os.path.join("skills", "mkt-social-copy", "scripts", "check_script.py"))
    assert flag(align["args"], "--vocabulary").endswith(os.path.join("shared", "references", "video-presets.json"))
    assert flag(align["args"], "--out") == os.path.join(folder, "proposal.beats.json")


def test_the_steps_after_the_review_call_the_engine_with_their_arguments_and_write_the_render_and_verify_files(world):
    task, gate = to_gate(world)
    engine = world["engine"]
    folder = media.folder_of(world["data"], world["rid"])
    platform = os.path.join(os.path.dirname(ops_step_seams.__file__), "..", "shared", "references", "platforms", "instagram.json")
    assert [c["verb"] for c in engine.calls][5:] == ["base", "align", "check", "render", "cover", "verify"]
    base, align, check, render, cover, verify = engine.calls[5:]
    assert base["args"][:8] == ["--transcript", os.path.join(folder, "transcript.edited.json"), "--analysis", os.path.join(folder, "analysis.json"),
                                "--out", os.path.join(folder, "edl.json"), "--retakes", "propose"] and "--confirm" not in base["args"]
    assert flag(align["args"], "--edl") == os.path.join(folder, "edl.json") and flag(align["args"], "--out") == os.path.join(folder, "beats.json")
    assert check["args"][:4] == ["--edl", os.path.join(folder, "edl.json"), "--beats", os.path.join(folder, "beats.json")]
    assert os.path.realpath(flag(check["args"], "--platform-file")) == os.path.realpath(platform)
    assert render["timeout"] == 2700 and flag(render["args"], "--in") == os.path.join(folder, "raw.mp4") and flag(render["args"], "--out") == folder
    digest = sha(b"the rendered video of Aster Lane " + b"one")
    assert flag(cover["args"], "--in") == os.path.join(folder, f"render-{digest[:12]}.mp4") and flag(cover["args"], "--offset-ms") == "0"
    assert flag(cover["args"], "--out") == os.path.join(folder, f"cover-{digest[:12]}.png")      # the temporary name; the file is then named by its own hash
    cover_bytes = b"\x89PNG\r\n\x1a\ncover"
    assert sorted(p.name for p in work_file(world, 'x').parent.glob('cover-*.png')) == [f"cover-{sha(cover_bytes)[:12]}.png"]
    assert flag(verify["args"], "--sha256") == digest and flag(verify["args"], "--edl") == os.path.join(folder, "edl.json") and verify["timeout"] == 300
    record = json.loads(work_file(world, "render.json").read_text())
    assert record == {"name": f"render-{digest[:12]}.mp4", "sha256": digest, "size": len(b"the rendered video of Aster Lane one"), "duration_ms": 8000,
                      "blocks": [{"id": k, "sha256": v} for k, v in sorted(RENDER_BLOCKS.items())], "blocks_sha256": "c" * 64}
    assert json.loads(work_file(world, "verify.json").read_text()) == {"passed": True, "platform": "instagram"}


def test_the_still_is_a_side_step_made_while_the_review_is_open_and_its_failure_is_skipped_and_never_fails_the_task(world):
    world["engine"].fail["still"] = RuntimeError("no frame")
    task = to_review(world)
    state = task_row(world, task)["step_state"]
    assert state["steps"]["still"]["status"] == "skipped" and task_row(world, task)["state"] == "waiting"
    assert "no still was made" in open_items(world, task)[0]["body"].lower()


def test_an_engine_that_is_not_configured_fails_the_step_not_configured_and_a_refused_verb_or_a_failure_have_their_codes(world):
    class Boom(Exception):
        def __init__(self, code):
            super().__init__(code)
            self.code = code
    for code, want in (("not_configured", "not_configured"), ("refused", "engine_refused"), ("engine_failed", "engine_failed"), ("odd", "engine_failed")):
        world["engine"].fail["transcribe"] = Boom(code)
        task = add(world, rid=None)
        out = run_task(world, task)
        assert out["ok"] is False and out["failed"] == "transcribe" and out["code"] == want, (code, out)
        ctx = ops_core.context(world["path"])
        ctx["store"].step_task_move(ctx["conn"], task, state="failed", note="x", by="code")      # free the recording for the next try


def test_an_engine_that_is_not_configured_says_in_its_next_sentence_how_to_set_up_or_name_the_other_renderer():
    class Missing(Exception):
        code = "not_configured"

    def call():
        raise Missing()
    with pytest.raises(steps.StepFailure) as caught:
        step_media._asked(call)
    assert caught.value.code == "not_configured" and "media.renderer" in caught.value.next and "hyperframes" in caught.value.next


def test_a_verify_result_that_is_not_ok_fails_the_verify_step_and_nothing_is_written_for_the_gate(world):
    world["engine"].verify_ok = False
    task = to_review(world)
    [item] = open_items(world, task)
    ops.answer(world["path"], item["id"], "continue")
    out = run_task(world, task)
    assert out["ok"] is False and out["failed"] == "verify" and out["code"] == "verify_failed"
    assert not work_file(world, "verify.json").exists() and open_items(world, task) == []


def test_prepare_again_from_remap_removes_the_edl_beats_render_cover_and_verify_files_and_keeps_the_persons_work(world):
    task, gate = to_gate(world)
    work_file(world, "review.json").write_text(json.dumps({"keep": True}))
    ctx = ops_core.context(world["path"])
    pctx = ops_steps._context(ctx, task_row(world, task))
    kind = steps.kind_of("media")
    state = steps.state_of(kind, task_row(world, task)["step_state"])
    names = sorted(p.name for p in work_file(world, "x").parent.iterdir())
    assert "edl.json" in names and "beats.json" in names and "render.json" in names and "verify.json" in names and "transcript.edited.json" in names
    steps.prepare_again(pctx, kind, state, "remap")
    left = sorted(p.name for p in work_file(world, "x").parent.iterdir() if not p.name.startswith("."))
    assert not any(n.startswith(("render-", "cover-")) or n in ("edl.json", "beats.json", "render.json", "verify.json") for n in left), left
    assert "transcript.edited.json" in left and "review.json" in left and "transcript.json" in left and "proposal.edl.json" in left
    assert state["cycle"] == 1 and "remap" not in state["steps"] and "document" not in state["steps"]


def test_preparing_the_proposals_again_starts_the_review_over_and_the_still_pattern_removes_every_still(world):
    task = to_review(world)
    ctx = ops_core.context(world["path"])
    pctx = ops_steps._context(ctx, task_row(world, task))
    kind = steps.kind_of("media")
    state = steps.state_of(kind, task_row(world, task)["step_state"])
    work_file(world, "review.json").write_text(json.dumps({"x": 1}))
    work_file(world, "transcript.edited.json").write_text(json.dumps({"x": 1}))
    steps.prepare_again(pctx, kind, state, "align-proposal")
    names = {p.name for p in work_file(world, "x").parent.iterdir()}
    assert not names & {"proposal.beats.json", "review.json", "transcript.edited.json"} and "proposal.edl.json" in names
    steps.prepare_again(pctx, kind, state, "analyse")
    names = {p.name for p in work_file(world, "x").parent.iterdir()}
    assert not [n for n in names if n.startswith("still-")] and "analysis.json" not in names and "transcript.json" in names


# ---------------------------------------------------------------- retakes: the rule's defaults and the person's choices

def retake(ident, first, last, default, seconds=0.8, reason="continues"):
    return {"id": ident, "kind": "repeat", "word_from": first, "word_to": last, "keep_from": last + 1, "seconds": seconds, "confirmed": False,
            "default": default, "reason": reason}


CUT, KEPT = retake("retake-1", 1, 2, "cut"), retake("retake-2", 4, 5, "keep", reason="complete")


def base_calls(engine):
    return engine.of("base")


def result_of(world, task, step):
    state = steps.state_of(steps.kind_of("media"), task_row(world, task)["step_state"])
    return state["steps"][step]["result"]


def confirms(call):
    return [call["args"][i + 1] for i, a in enumerate(call["args"]) if a == "--confirm"]


def test_the_proposals_are_made_with_propose_and_the_result_counts_what_the_rule_cuts(world):
    world["engine"].proposals = [CUT, KEPT]
    task = to_review(world)
    first = base_calls(world["engine"])[0]
    assert flag(first["args"], "--retakes") == "propose" and "--confirm" not in first["args"]
    got = result_of(world, task, "retakes")
    assert got["proposals"] == 2 and got["cut_by_rule"] == 1


@pytest.mark.parametrize("cuts,line", [([CUT, KEPT], "1 repeated take will be cut by rule; open the captions to keep one."),
                                       ([CUT, retake("retake-3", 6, 6, "cut")], "2 repeated takes will be cut by rule; open the captions to keep one."),
                                       ([], "0 repeated takes will be cut by rule; open the captions to keep one.")])
def test_the_review_question_has_one_more_fixed_line_with_the_count_and_no_word(world, cuts, line):
    world["engine"].proposals = cuts
    task = to_review(world)
    [item] = open_items(world, task)
    lines = item["body"].splitlines()
    assert lines[3] == line and lines[4] == "Edit the captions, then continue."          # the new line sits before the one that says what to do next
    assert "Aster" not in item["body"]


def test_a_rule_default_that_the_person_did_not_keep_is_confirmed_in_the_final_base_and_a_kept_one_is_not(world):
    world["engine"].proposals = [CUT, KEPT]
    task = to_review(world)
    [item] = open_items(world, task)
    ops.answer(world["path"], item["id"], "continue")
    run_task(world, task)
    final = base_calls(world["engine"])[-1]
    assert flag(final["args"], "--retakes") == "propose" and confirms(final) == ["retake-1"]          # the rule's cut; the kept proposal stays
    got = result_of(world, task, "base")
    assert got["retakes_confirmed"] == 1 and got["retakes_by_rule"] == 1 and got["retakes_unmatched"] == 0


def test_a_take_the_person_kept_is_not_confirmed_even_though_the_rule_says_cut(world):
    world["engine"].proposals = [CUT, KEPT]
    task = to_review(world)
    review = cap.new_review()
    review["kept_retakes"] = [{"id": "retake-1", "from": 1, "to": 2, "seconds": 0.8}]
    work_file(world, "review.json").write_text(json.dumps(review))
    [item] = open_items(world, task)
    ops.answer(world["path"], item["id"], "continue")
    run_task(world, task)
    final = base_calls(world["engine"])[-1]
    assert confirms(final) == [] and "--confirm" not in final["args"] and len(base_calls(world["engine"])) == 2
    assert result_of(world, task, "base")["retakes_by_rule"] == 0


def test_a_take_the_person_cut_is_confirmed_with_the_rules_cuts(world):
    world["engine"].proposals = [CUT, KEPT]
    task = to_review(world)
    review = cap.new_review()
    review["confirmed_retakes"] = [{"id": "retake-2", "from": 4, "to": 5, "seconds": 0.8}]
    work_file(world, "review.json").write_text(json.dumps(review))
    [item] = open_items(world, task)
    ops.answer(world["path"], item["id"], "continue")
    run_task(world, task)
    assert sorted(confirms(base_calls(world["engine"])[-1])) == ["retake-1", "retake-2"]


def test_a_rule_default_with_no_matching_proposal_is_counted_and_never_stops_the_step(world):
    world["engine"].proposals = [CUT, KEPT]
    world["engine"].final_proposals = [KEPT]            # the rule finds nothing where the person saw the first take
    task = to_review(world)
    [item] = open_items(world, task)
    ops.answer(world["path"], item["id"], "continue")
    out = run_task(world, task)
    assert out["ok"] is True and out.get("stopped") == "deliver"
    assert confirms(base_calls(world["engine"])[-1]) == [] or "--confirm" not in base_calls(world["engine"])[-1]["args"]
    got = result_of(world, task, "base")
    assert got["retakes_unmatched"] == 1 and got["retakes_by_rule"] == 0 and got["retakes_confirmed"] == 0


def test_a_lost_confirmation_of_the_person_still_stops_with_retake_lost(world):
    world["engine"].proposals = [CUT, KEPT]
    world["engine"].final_proposals = [CUT]
    task = to_review(world)
    review = cap.new_review()
    review["confirmed_retakes"] = [{"id": "retake-2", "from": 4, "to": 5, "seconds": 0.8}]
    work_file(world, "review.json").write_text(json.dumps(review))
    [item] = open_items(world, task)
    ops.answer(world["path"], item["id"], "continue")
    out = run_task(world, task)
    assert out["ok"] is False and out["failed"] == "base" and out["code"] == "retake_lost"
    assert json.loads(work_file(world, "review.json").read_text())["confirmed_retakes"] == []


def test_the_align_result_counts_the_punches_and_the_effects(world):
    task = to_review(world)
    [item] = open_items(world, task)
    ops.answer(world["path"], item["id"], "continue")
    run_task(world, task)
    got = result_of(world, task, "align")
    assert got["punches"] == 0 and got["effects"] == 0
