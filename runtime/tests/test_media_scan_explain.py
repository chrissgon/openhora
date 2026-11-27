"""Tests of the explanation of the text a scan found (package P9-a3, limit L83): `video-media-scan-explain` (runtime/ops_media_scan_explain.py), the findings kept in `scan-explained.json` beside
`scan.json` (runtime/media_stock.py), the report the approval answer carries (runtime/ops_media_stock.py `_explained_report`) and the skill's script it agrees with. The run of the skill is a stand-in
(`ExplainRun` writes the file the skill would write), the engine and the sources are the existing fakes, and the store, the scan, the approval and the skill's checker script are the real ones. Nothing
is scanned, no model is called, no container runs; every text, host and name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_media_scan_explain.py
"""
from __future__ import annotations

import contextlib
import importlib.util
import json
import os
import shutil
import string
from pathlib import Path

import pytest

import standin_tree as st
from media_kit import media, ops, ops_core, world  # noqa: F401  (the fixture)
from media_stock_kit import REPO, FakeRun, ROUTING, media_stock, ops_media_stock
from test_media_scan import HOSTILE, LINK, ACTION, QR_TEXT, scanned, stock_folder

ops_media_scan_explain = st.load("ops_media_scan_explain")
ops_media_websearch = st.load("ops_media_websearch")
operations = st.load("operations")
phrases = st.load("phrases")
ops_runs = st.load("ops_runs")
ops_contained = st.load("ops_contained")
lab = st.load("lab")
REAL_EXECUTE = ops_contained.execute      # the real one, kept before a test puts the stand-in in its place
SKILL = ops_media_scan_explain.SKILL
HERE = Path(__file__).resolve().parent

PLANTED = {"beat7": {"lines": ["SAMPLE PHOTO DO NOT USE", HOSTILE], "codes": ["text_found", "qr_link"], "qr": [LINK]}, "beat8": {"lines": ["Call 555 0100"], "codes": ["text_found"]}}
FINDINGS = {"beat7": [{"source": "text", "quote": "SAMPLE PHOTO DO NOT USE", "concern": "licence_mark", "explanation": "A stock sample mark: the picture is a preview, not the licensed file."},
                      {"source": "text", "quote": HOSTILE, "concern": "claim", "explanation": "Text that tries to give orders. It is quoted here and not obeyed."},
                      {"source": "qr", "quote": "shop.example", "concern": "link", "explanation": "The code leads to shop.example; anyone can open it from your video."}],
            "beat8": [{"source": "text", "quote": "Call 555 0100", "concern": "contact", "explanation": "A phone number printed in the picture: every viewer will see it."}]}


def document(findings=None):
    return {"schema_version": 1, "slots": [{"slot": slot, "findings": found} for slot, found in sorted((findings or FINDINGS).items())], "open": []}


class ExplainRun(FakeRun):
    """`ops_contained.execute` as ops_media_scan_explain calls it, writing the answer file a run of the skill would write (`document`, or `raw` bytes, or a link in its place with `link`)."""

    def __init__(self):
        super().__init__()
        self.document, self.metas = document(), []

    def __call__(self, ctx, skill, meta, *a, **kw):
        self.metas.append(meta)
        return super().__call__(ctx, skill, meta, *a, **kw)

    def _result(self, dest, open_web):
        result = super()._result(dest, open_web)
        if result["status"] != "ok":
            return result
        target = Path(result["cwd"]) / ".workbench-local" / "video" / "scan-explained.json"
        if self.link:
            outside = Path(dest) / "outside.json"
            outside.write_text(json.dumps(self.document), encoding="utf-8")
            target.symlink_to(outside)
        elif self.raw is not None:
            target.write_bytes(self.raw)
        elif self.document is not None:
            target.write_text(json.dumps(self.document), encoding="utf-8")
        return result


def explain_world(world, monkeypatch, planted=None, autonomy="supervised"):
    """Two fetched slots (one per-item source, one library) whose scan holds `planted`, the skill in the stand-in tree with the real checker script, and `ExplainRun` in place of the run."""
    found, got = scanned(world, monkeypatch, PLANTED if planted is None else planted)
    folder = st.skill(Path(world["tree"]), SKILL, "", ".workbench-local/video/scan-explained.json", area="marketing")
    shutil.copy(REPO / "skills" / SKILL / "scripts" / "check_explained.py", folder / "scripts" / "check_explained.py")
    run, routing = ExplainRun(), dict(ROUTING, web=False, autonomy=autonomy, model="m-test")
    meta = {"web": False, "requires": [], "side_effects": [], "inputs": [], "outputs": [".workbench-local/video/scan-explained.json"], "updates": []}
    monkeypatch.setattr(ops_media_scan_explain.ops_contained, "routed", lambda ctx, skill: (meta, None, routing))
    monkeypatch.setattr(ops_media_scan_explain.ops_contained, "execute", run)
    monkeypatch.setattr(ops_media_scan_explain.lab, "skill_identity", lambda skill: {"version": "0.1.0", "content_sha256": "e" * 64})
    monkeypatch.setattr(ops_media_scan_explain.lab, "reported_usage", lambda dest: None)
    return dict(found, run=run, routing=routing, got=got)


def items_of(world) -> list:
    """What the scan of the fetched set holds that could be explained, as the operation reads it."""
    data_dir = ops_core.context(world["path"])["cfg"]["data_dir"]
    return media_stock.explain_items(media_stock.read_doc(data_dir, world["rid"], media_stock.SET)["assets"], media_stock.read_scan(data_dir, world["rid"]))


def explain(world, task, confirm=True, **kw):
    return ops.video_media_scan_explain(world["path"], task, confirm=confirm, **kw)


def refused(call, *args, **kw) -> str:
    with pytest.raises(ops_core.OpsError) as caught:
        call(*args, **kw)
    return str(caught.value)


def rows(world) -> list:
    ctx = ops_core.context(world["path"])
    return ctx["store"].runs_since(ctx["conn"], "2000-01-01T00:00:00Z")


def explained_file(world) -> Path:
    return stock_folder(world) / "scan-explained.json"


def everything_stored(world) -> str:
    """Every byte a run leaves in the store of the project: the database and the run rows."""
    ctx = ops_core.context(world["path"])
    return "\n".join(ctx["conn"].iterdump())


# --- the button: what would be sent, to whom, and nothing sent ---------------------------------------------------------------------------------------


def test_without_confirm_it_says_what_is_sent_and_to_whom_and_runs_nothing(world, monkeypatch):
    w = explain_world(world, monkeypatch)
    shown = explain(world, w["task"], confirm=False)
    assert shown["confirmed"] is False and shown["left_out"] == [] and shown["model"] == "m-test" and shown["supervised"] is True
    assert shown["slots"] == [{"slot": "beat7", "lines": ["SAMPLE PHOTO DO NOT USE", HOSTILE], "qr": [{"kind": "link", "host": "shop.example"}]}, {"slot": "beat8", "lines": ["Call 555 0100"], "qr": []}]
    assert shown["message"] == phrases.text("VID_SCAN_EXPLAIN_PREVIEW", ops_core.context(world["path"])["cfg"], model="m-test") and "m-test" in shown["message"]
    assert "no picture, no frame, no search words and nothing of your recording" in shown["message"]
    assert shown["confirm"] == "Send this text and explain it" and "no proven result" in shown["supervised_note"]
    assert w["run"].calls == [] and rows(world) == [] and not explained_file(world).exists()
    assert HOSTILE not in shown["message"], "the lines are a field of their own, never part of the sentence"


def test_the_approval_answer_offers_the_button_and_holds_no_explanation_before_it_is_asked_for(world, monkeypatch):
    w = explain_world(world, monkeypatch)
    shown = ops.video_media_approve(world["path"], w["task"])
    assert shown["explained"] == {"available": True, "button": "Explain the text found", "by": None, "slots": []}


def test_a_set_whose_scan_found_nothing_does_not_offer_the_button(world, monkeypatch):
    clean = explain_world(world, monkeypatch, planted={})
    assert ops.video_media_approve(world["path"], clean["task"])["explained"] == {"available": False, "button": "Explain the text found", "by": None, "slots": []}


# --- what is sent -----------------------------------------------------------------------------------------------------------------------------


def test_the_prompt_is_the_slot_ids_the_lines_and_the_qr_items_and_nothing_else(world, monkeypatch):
    w = explain_world(world, monkeypatch)
    explain(world, w["task"])
    [call] = w["run"].calls
    items = items_of(world)
    assert call["prompt"].strip() == ops_media_scan_explain._render_prompt(items, "English")
    assert call["prompt"].strip() == ('Explain the text found in these pictures of a short video. Write each explanation in English. Slot `beat7`: text lines ["SAMPLE PHOTO DO NOT USE", %s]. '
                                      'QR code opening a link on host "shop.example". Slot `beat8`: text lines ["Call 555 0100"].' % json.dumps(HOSTILE))
    assert call["open_web"] is False and call["sourced"] == () and call["platforms"] == () and call["skill"] == SKILL and call["around"] is True
    assert call["timeout"] == 300 and call["max_cost"] == 0.6
    for private in ("market stall", "fruit crate", "a screenshot of a shop", "asset-", "sheet", world["rid"]):
        assert private not in call["prompt"], private + ": the slot's words, its description, a file and the recording are never sent"
    [meta] = w["run"].metas
    assert meta["inputs"] == [] and meta["outputs"] == [] and meta["updates"] == [], "no artifact of the project is declared to the run, so none enters it"


def test_the_real_execute_hands_the_lab_no_file_of_the_project_and_no_web(world, monkeypatch):
    w = explain_world(world, monkeypatch)
    monkeypatch.setattr(ops_media_scan_explain.ops_contained, "execute", REAL_EXECUTE)
    monkeypatch.setattr(lab, "run_skill", w["run"].lab_call)
    monkeypatch.setattr(lab, "session", lambda: contextlib.nullcontext())
    monkeypatch.setattr(ops_runs, "_key_in_environment", lambda routing, keys: contextlib.nullcontext())
    (Path(world["path"]) / "docs" / "workbench").mkdir(parents=True, exist_ok=True)
    (Path(world["path"]) / "docs" / "workbench" / "state.md").write_text("# State\n", encoding="utf-8")
    (Path(world["path"]) / "docs" / "marketing").mkdir(parents=True, exist_ok=True)
    (Path(world["path"]) / "docs" / "marketing" / "plan.md").write_text("# Plan\n", encoding="utf-8")
    assert explain(world, w["task"])["confirmed"] is True
    [call] = w["run"].calls
    assert call["files"] == [] and call["open_web"] is False and call["retries"] == 0 and call["platforms"] == ()


def test_the_prompt_of_the_first_eval_case_is_what_the_runtime_renders(world):
    cases = json.loads((REPO / "skills" / SKILL / "evals" / "evals.json").read_text(encoding="utf-8"))["evals"]
    items = [{"slot": "cafe-sign", "lines": ["Café Aurora – Ligue (11) 5555-0100"], "qr": []},
             {"slot": "city-night", "lines": ["© StockPix Images", "PREVIEW ONLY"], "qr": []},
             {"slot": "poster", "lines": [], "qr": [{"kind": "link", "host": "promo.example"}]}]
    assert ops_media_scan_explain._render_prompt(items, "English") == cases[0]["prompt"], "the skill was measured on the form the runtime sends"


def test_a_value_that_is_not_in_the_form_that_may_be_sent_refuses_everything(world, monkeypatch):
    base = {"slot": "beat7", "sha256": "0" * 64, "source": "shelf", "lines": ["ok"], "qr": []}
    for bad in (dict(base, slot="Beat 7"), dict(base, lines=["x" * 161]), dict(base, lines=["two  spaces"]), dict(base, lines=["bell\u0007"]), dict(base, lines=["a" * 3] * 9),
                dict(base, lines=[], qr=[{"kind": "link", "host": "not a host"}]), dict(base, lines=[], qr=[{"kind": "action", "scheme": "ftp"}]), dict(base, lines=[], qr=[{"kind": "text", "text": "y" * 121}]),
                dict(base, lines=[], qr=[])):
        assert "explain_invalid" in refused(ops_media_scan_explain._check_sent, [bad]), bad
    ops_media_scan_explain._check_sent([base, dict(base, lines=[], qr=[{"kind": "action", "scheme": "tel"}, {"kind": "text", "text": "hello"}])])


def test_the_text_of_an_asset_whose_source_is_not_a_stock_or_web_source_is_left_out_whatever_it_holds(world, monkeypatch):
    w = explain_world(world, monkeypatch)
    data_dir = ops_core.context(world["path"])["cfg"]["data_dir"]
    doc = media_stock.read_doc(data_dir, world["rid"], media_stock.SET)
    doc["assets"][1]["source"] = "mine"      # a source with no licence tier: a future upload of the person's own files
    media_stock.write_doc(data_dir, world["rid"], media_stock.SET, doc)
    shown = explain(world, w["task"], confirm=False)
    assert [s["slot"] for s in shown["slots"]] == ["beat7"] and shown["left_out"] == [{"slot": "beat8", "reason": "source_not_stock", "message": phrases.text("VID_SCAN_EXPLAIN_LEFT_OUT",
                                                                                                                                                            ops_core.context(world["path"])["cfg"], slot="beat8")}]
    w["run"].document = document({"beat7": FINDINGS["beat7"]})
    done = explain(world, w["task"])
    [call] = w["run"].calls
    assert "Call 555 0100" not in call["prompt"] and "beat8" not in call["prompt"], "the left-out file's text never reaches the prompt"
    assert [s["slot"] for s in done["explained"]["slots"]] == ["beat7"] and done["left_out"][0]["slot"] == "beat8"
    doc["assets"][0]["source"] = "mine"
    media_stock.write_doc(data_dir, world["rid"], media_stock.SET, doc)
    w["run"].calls.clear()
    assert "nothing_to_explain" in refused(explain, world, w["task"]) and w["run"].calls == []


# --- the gates, in order, with nothing run ----------------------------------------------------------------------------------------------------


def test_a_set_with_nothing_found_is_refused_with_the_sentence_and_nothing_is_run(world, monkeypatch):
    w = explain_world(world, monkeypatch, planted={})
    assert "nothing_to_explain" in refused(explain, world, w["task"]) and phrases.text("VID_SCAN_EXPLAIN_NOTHING", ops_core.context(world["path"])["cfg"]) in refused(explain, world, w["task"])
    (stock_folder(world) / "scan.json").unlink()
    assert "nothing_to_explain" in refused(explain, world, w["task"]), "a set that was never scanned has nothing to explain"
    assert w["run"].calls == []


def test_each_gate_refuses_in_its_order_and_nothing_is_run(world, monkeypatch):
    w2 = explain_world(world, monkeypatch)
    skill_md = Path(world["tree"]) / "skills" / SKILL / "SKILL.md"
    keep = skill_md.read_text(encoding="utf-8")
    skill_md.write_text(keep.replace("requires: []", "requires: [search:web]"), encoding="utf-8")
    assert "declares a requirement" in refused(explain, world, w2["task"]), "a skill that needs a tool is not this skill"
    skill_md.write_text(keep.replace("side_effects: []", "side_effects: [send]"), encoding="utf-8")
    assert "declares a requirement or a side effect" in refused(explain, world, w2["task"])
    skill_md.unlink()
    assert "not in this checkout" in refused(explain, world, w2["task"])
    assert w2["run"].calls == []
    ctx = ops_core.context(world["path"])
    ctx["store"].step_task_move(ctx["conn"], w2["task"], state="running", note=None, by="code")
    assert "not_at_review" in refused(explain, world, w2["task"])
    assert "not_at_review" in refused(explain, world, w2["task"], confirm=False)


def test_a_set_that_is_not_fetched_is_refused_and_a_bad_confirm_or_channel_too(world, monkeypatch):
    w = explain_world(world, monkeypatch)
    for bad in ("yes", 1, [True]):
        assert "confirm is true or false" in refused(explain, world, w["task"], confirm=bad)
    for channel in ("messaging", "mcp", "lan", "whatsapp"):
        assert refused(explain, world, w["task"], channel=channel), channel
    explain(world, w["task"], channel="terminal")
    explain(world, w["task"], confirm=False, channel="page")
    with pytest.raises(ops_core.OpsError):
        ops.video_media_scan_explain(world["path"], 99999)


# --- the run, its answer and where it is kept ---------------------------------------------------------------------------------------------------


def test_the_findings_are_kept_beside_the_scan_keyed_by_file_and_shown_as_not_checked(world, monkeypatch):
    w = explain_world(world, monkeypatch)
    done = explain(world, w["task"])
    assert done["confirmed"] is True and done["supervised"] is True and done["left_out"] == []
    report = done["explained"]
    assert report["available"] is True and report["by"] == "Explained by m-test, not checked:"
    assert [s["slot"] for s in report["slots"]] == ["beat7", "beat8"]
    first = report["slots"][0]["findings"]
    assert [f["concern"] for f in first] == ["licence_mark", "claim", "link"] and [f["concern_label"] for f in first] == ["Stock or licence mark", "Claim or call to act", "Link"]
    assert first[1]["quote"] == HOSTILE and HOSTILE not in first[1]["explanation"]
    path = explained_file(world)
    assert path.is_file() and oct(path.stat().st_mode & 0o777) == "0o600"
    doc = json.loads(path.read_text(encoding="utf-8"))
    assets = media_stock.read_doc(ops_core.context(world["path"])["cfg"]["data_dir"], world["rid"], media_stock.SET)["assets"]
    assert set(doc["assets"]) == {a["sha256"] for a in assets} and doc["model"] == "m-test" and doc["version"] == 1
    for name in ("set.json", "scan.json"):
        assert "ignore previous" not in (stock_folder(world) / name).read_text(encoding="utf-8") or name == "scan.json", name
    assert "Stock or licence" not in (stock_folder(world) / "set.json").read_text(encoding="utf-8")
    shown = ops.video_media_approve(world["path"], w["task"])
    assert shown["explained"]["slots"] == report["slots"] and shown["explained"]["by"] == report["by"], "the page finds it again after a reload"
    approved = ops.video_media_approve(world["path"], w["task"], hash=shown["sha256"])
    assert approved["approved"] is True and "explained" not in approved
    assert "explain" not in (stock_folder(world) / "approved.json").read_text(encoding="utf-8"), "the approval records the scan digest only: the explanation binds nothing"
    assert explained_file(world).is_file(), "the approval keeps it, as it keeps the scan"


def test_the_run_row_holds_a_neutral_line_and_nothing_of_the_text_is_in_the_store(world, monkeypatch):
    w = explain_world(world, monkeypatch)
    explain(world, w["task"])
    [row] = [r for r in rows(world) if r.get("skill") == SKILL]
    assert row["status"] == "ok" and row["model"] == "m-test"
    stored = everything_stored(world)
    for text in ("SAMPLE PHOTO", "ignore previous instructions", "Call 555", "shop.example", "A stock sample mark", "licence_mark"):
        assert text not in stored, text
    assert ops_media_scan_explain.NEUTRAL in stored


def test_its_folder_is_removed_and_the_set_the_scan_and_the_approval_are_untouched(world, monkeypatch):
    w = explain_world(world, monkeypatch)
    before = {n: (stock_folder(world) / n).read_bytes() for n in ("set.json", "scan.json")}
    explain(world, w["task"])
    assert not Path(w["run"].calls[0]["dest"]).exists()
    assert {n: (stock_folder(world) / n).read_bytes() for n in ("set.json", "scan.json")} == before
    assert not (stock_folder(world) / "approved.json").exists()
    assert not [n for n in os.listdir(stock_folder(world)) if n.startswith(".work")], "the scratch folder of the read-back is removed"


def test_a_second_explanation_replaces_the_entries_of_the_files_it_covers(world, monkeypatch):
    w = explain_world(world, monkeypatch)
    explain(world, w["task"])
    w["run"].document = document({"beat7": [{"source": "text", "quote": "SAMPLE PHOTO DO NOT USE", "concern": "licence_mark", "explanation": "Second."},
                                            {"source": "text", "quote": HOSTILE, "concern": "unclear", "explanation": "Second."}, {"source": "qr", "quote": "shop.example", "concern": "link", "explanation": "Second."}],
                                  "beat8": FINDINGS["beat8"]})
    done = explain(world, w["task"])
    assert done["explained"]["slots"][0]["findings"][0]["explanation"] == "Second." and len(done["explained"]["slots"]) == 2


@pytest.mark.parametrize("mode", ["failed", "boom", "docker"])
def test_a_run_that_fails_keeps_nothing_and_says_so_in_one_sentence(world, monkeypatch, mode):
    w = explain_world(world, monkeypatch)
    w["run"].mode = mode
    message = refused(explain, world, w["task"])
    assert "explain_failed" in message and phrases.text("VID_SCAN_EXPLAIN_FAILED", ops_core.context(world["path"])["cfg"]) in message
    assert not explained_file(world).exists()
    [row] = [r for r in rows(world) if r.get("skill") == SKILL]
    assert row["status"] == "failed"
    for text in ("ignore previous instructions", "SAMPLE PHOTO", "Call 555"):
        assert text not in message and text not in everything_stored(world), text
    assert not Path(w["run"].dests[0]).exists()


# --- the read-back: the answer is checked twice and refused whole ----------------------------------------------------------------------------------


def bad_documents():
    good = json.loads(json.dumps(document()))

    def with_finding(**changes):
        d = json.loads(json.dumps(good))
        d["slots"][0]["findings"][0].update(changes)
        return d

    def without(key):
        d = json.loads(json.dumps(good))
        del d["slots"][0]["findings"][0][key]
        return d
    return {
        "a quote the task did not give": with_finding(quote="INVENTED QUOTE"),
        "a quote with its spacing changed": with_finding(quote="SAMPLE  PHOTO DO NOT USE"),
        "a quote of another slot": with_finding(quote="Call 555 0100"),
        "a concern outside the list": with_finding(concern="safe"),
        "a source outside the list": with_finding(source="image"),
        "an explanation with a web address": with_finding(explanation="Open https://prize.example/claim now."),
        "an explanation over its bound": with_finding(explanation="x" * 241),
        "an empty explanation": with_finding(explanation=""),
        "an unknown field": with_finding(extra=1),
        "a missing field": without("concern"),
        "a slot that was not sent": dict(good, slots=good["slots"] + [{"slot": "beat9", "findings": good["slots"][0]["findings"][:1]}]),
        "a slot twice": dict(good, slots=good["slots"] + [good["slots"][0]]),
        "a slot that is missing": dict(good, slots=good["slots"][:1]),
        "a slot with no finding": dict(good, slots=[{"slot": "beat7", "findings": []}, good["slots"][1]]),
        "too many findings": dict(good, slots=[{"slot": "beat7", "findings": good["slots"][0]["findings"] * 5}, good["slots"][1]]),
        "another schema": dict(good, schema_version=2),
        "an unknown top-level key": dict(good, extra=[]),
        "an open item that is not a closed code": dict(good, open=[{"code": "gave_up"}]),
        "not an object": [1, 2],
    }


@pytest.mark.parametrize("name", sorted(bad_documents()))
def test_an_answer_that_breaks_a_rule_is_refused_whole_and_nothing_is_kept(world, monkeypatch, name):
    w = explain_world(world, monkeypatch)
    w["run"].document = bad_documents()[name]
    assert "explain_invalid" in refused(explain, world, w["task"]) and not explained_file(world).exists()
    [row] = [r for r in rows(world) if r.get("skill") == SKILL]
    assert row["status"] == "ok", "the run itself ended; its answer was refused"
    assert not [n for n in os.listdir(stock_folder(world)) if n.startswith(".work")]


def test_each_of_the_two_checks_refuses_the_file_alone(world, monkeypatch):
    w = explain_world(world, monkeypatch)
    w["run"].document = bad_documents()["a quote the task did not give"]
    monkeypatch.setattr(ops_media_scan_explain, "_check_with_script", lambda *a: True)
    assert "explain_invalid" in refused(explain, world, w["task"]), "the code's own check refuses what the script let through"
    w["run"].document = document()
    monkeypatch.setattr(ops_media_scan_explain, "_check_with_script", lambda *a: False)
    assert "explain_invalid" in refused(explain, world, w["task"]), "the script refuses what the code would have let through"
    assert not explained_file(world).exists()
    monkeypatch.undo()


def test_the_scripts_own_check_runs_isolated_with_the_lines_that_were_sent_as_the_grounding(world, monkeypatch):
    w = explain_world(world, monkeypatch)
    seen = []
    real = ops_media_scan_explain._check_with_script

    def spy(copy, task_file, slots):
        seen.append((json.loads(Path(task_file).read_text(encoding="utf-8")), sorted(slots)))
        return real(copy, task_file, slots)
    monkeypatch.setattr(ops_media_scan_explain, "_check_with_script", spy)
    explain(world, w["task"])
    assert seen == [({"slots": {"beat7": ["SAMPLE PHOTO DO NOT USE", HOSTILE, "shop.example"], "beat8": ["Call 555 0100"]}}, ["beat7", "beat8"])]


@pytest.mark.parametrize("how", ["raw", "huge", "link", "none"])
def test_a_file_that_is_not_a_plain_small_json_file_is_refused(world, monkeypatch, how):
    w = explain_world(world, monkeypatch)
    if how == "raw":
        w["run"].raw = b"not json {"
    elif how == "huge":
        w["run"].raw = b" " * (ops_media_scan_explain.ANSWER_LIMIT + 1)
    elif how == "link":
        w["run"].link = True
    else:
        w["run"].document = None
    assert "explain_invalid" in refused(explain, world, w["task"]) and not explained_file(world).exists()


def test_the_explanation_is_cleaned_and_the_quote_is_exact(world, monkeypatch):
    w = explain_world(world, monkeypatch)
    d = document()
    d["slots"][1]["findings"][0]["explanation"] = "A phone  number,   printed in the picture."
    w["run"].document = d
    done = explain(world, w["task"])
    assert done["explained"]["slots"][1]["findings"][0]["explanation"] == "A phone number, printed in the picture."
    assert done["explained"]["slots"][1]["findings"][0]["quote"] == "Call 555 0100"


# --- the store of the findings ----------------------------------------------------------------------------------------------------------------


def test_the_stored_findings_are_read_as_untrusted_and_cleaned(world, monkeypatch):
    w = explain_world(world, monkeypatch)
    explain(world, w["task"])
    data_dir = ops_core.context(world["path"])["cfg"]["data_dir"]
    doc = json.loads(explained_file(world).read_text(encoding="utf-8"))
    digest = next(iter(doc["assets"]))
    doc["assets"][digest] = [{"source": "text", "quote": "a\u202ebc\x07d", "concern": "link", "explanation": "x\u200by " + "z" * 400}, {"source": "text", "quote": "q", "concern": "safe", "explanation": "dropped"},
                             {"source": "voice", "quote": "q", "concern": "link", "explanation": "dropped"}, "not a finding", {"source": "qr", "quote": "", "concern": "link", "explanation": "dropped"}] * 4
    doc["assets"] = {digest: doc["assets"][digest], "not-a-digest": [FINDINGS["beat8"][0]]}
    doc["model"] = "m\x00odel"
    media_stock.write_doc(data_dir, world["rid"], media_stock.EXPLAINED, doc)
    read = media_stock.read_explained(data_dir, world["rid"])
    assert set(read["assets"]) == {digest} and len(read["assets"][digest]) == 3, "the first twelve entries are read, and only the well-formed ones are kept"
    first = read["assets"][digest][0]
    assert first["quote"] == "a bc d" and first["explanation"].startswith("x y ") and len(first["explanation"]) == media_stock.EXPLAIN_TEXT_MAX and read["model"] == "m odel"


def test_a_new_find_or_search_removes_the_explanation_with_the_scan_and_the_approval_keeps_both(world, monkeypatch):
    w = explain_world(world, monkeypatch)
    explain(world, w["task"])
    data_dir = ops_core.context(world["path"])["cfg"]["data_dir"]
    assert explained_file(world).is_file() and (stock_folder(world) / "scan.json").is_file()
    media_stock.clear_candidates(data_dir, world["rid"])
    assert explained_file(world).is_file(), "the approval clears the previews and keeps what was read"
    for clear in (media_stock.clear_licensed, media_stock.clear_web):
        media_stock.write_doc(data_dir, world["rid"], media_stock.EXPLAINED, {"version": 1, "model": "m", "assets": {}, "at": media_stock.now_stamp()})
        clear(data_dir, world["rid"])
        assert not explained_file(world).exists(), clear.__name__


def test_the_explanation_is_never_served_and_a_step_may_not_read_it(world, monkeypatch):
    w = explain_world(world, monkeypatch)
    explain(world, w["task"])
    data_dir = ops_core.context(world["path"])["cfg"]["data_dir"]
    with pytest.raises(media_stock.StockError):
        media_stock.read_served(data_dir, world["rid"], "scan-explained.json")
    assert not media.STOCK_FILE.fullmatch("stock/scan-explained.json"), "the name is not one a step may read or hand the engine"
    assert ops.video_media_sheet_file.__name__ and "explain" not in json.dumps(ops.video_media_approve(world["path"], w["task"])["set"])


def test_explain_items_takes_only_what_a_model_could_be_asked_about(world, monkeypatch):
    doc = {"assets": {"a" * 64: {"codes": ["text_found"], "text": {"lines": ["one", "two"]}, "qr": [dict(LINK), dict(LINK), dict(LINK, host=None), ACTION, dict(ACTION, scheme=None), QR_TEXT,
                                                                                                        dict(QR_TEXT, text=None), {"kind": "link", "host": "other.example"}]},
                       "b" * 64: {"codes": [], "text": {"lines": ["noise only"]}, "qr": []}, "c" * 64: {"codes": ["qr_unreadable"], "text": {"lines": []}, "qr": []}}}
    assets = [{"slot": "s2", "sha256": "b" * 64, "source": "shelf"}, {"slot": "s1", "sha256": "a" * 64, "source": "shelf"}, {"slot": "s3", "sha256": "c" * 64, "source": "shelf"},
              {"slot": "s4", "sha256": "d" * 64, "source": "shelf"}]
    assert media_stock.explain_items(assets, doc) == [{"slot": "s1", "sha256": "a" * 64, "source": "shelf", "lines": ["one", "two"],
                                                      "qr": [{"kind": "link", "host": "shop.example"}, {"kind": "action", "scheme": "tel"}, {"kind": "text", "text": "hello from a code"},
                                                             {"kind": "link", "host": "other.example"}]}]
    assert [i["slot"] for i in media_stock.explain_items(assets, {"assets": {}})] == []


# --- the sentences, the closed lists and the one route ----------------------------------------------------------------------------------------------


def test_every_sentence_of_the_operation_is_built_from_the_closed_fields_in_both_languages(world):
    for key in ops_media_scan_explain.PHRASE_KEYS:
        for sentence in phrases.every(key):
            fields = {f for _, f, _, _ in string.Formatter().parse(sentence) if f}
            assert fields <= ops_media_scan_explain.PHRASE_FIELDS, (key, fields)
    assert phrases.text("VID_SCAN_EXPLAIN_BUTTON", {"language": "pt-BR"}) == "Explicar o texto encontrado"
    assert phrases.text("VID_SCAN_EXPLAIN_BUTTON", {"language": "en"}) == "Explain the text found"
    assert set(ops_media_stock.CONCERN_PHRASE) == set(media_stock.EXPLAIN_CONCERNS)


def test_the_closed_lists_equal_the_skills_script():
    spec = importlib.util.spec_from_file_location("check_explained_for_runtime_tests", REPO / "skills" / SKILL / "scripts" / "check_explained.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    assert tuple(script.SOURCES) == media_stock.EXPLAIN_SOURCES and tuple(script.CONCERNS) == media_stock.EXPLAIN_CONCERNS
    assert (script.MAX_QUOTE, script.MAX_EXPLANATION, script.MAX_FINDINGS) == (media_stock.EXPLAIN_QUOTE_MAX, media_stock.EXPLAIN_TEXT_MAX, media_stock.EXPLAIN_FINDINGS_MAX)
    assert media_stock.EXPLAIN_QUOTE_MAX >= media_stock.SCAN_LINE_MAX, "a quote may be any line the scan kept"


def test_the_operation_is_internal_terminal_and_page_only_and_never_on_the_local_network_or_messaging(world):
    [row] = [r for r in operations.OPERATIONS if r["name"] == "video-media-scan-explain"]
    assert tuple(row["channels"]) == ("terminal", "page") and row["model"] is True and row["natural"]["class"] == "G" and row["natural"]["privacy"] == "off-host"
    assert "video-media-scan-explain" in operations.LAN_REFUSED_OPS
    gated = json.loads((REPO / "runtime" / "gated_ops.json").read_text(encoding="utf-8"))
    [entry] = [o for o in next(v for v in gated.values() if isinstance(v, list)) if o["op"] == "video-media-scan-explain"]
    assert entry["kind"] == "internal" and entry["group"] == "media"


def test_limit_83_the_text_a_scan_read_leaves_only_by_the_button_to_the_routed_model_and_nothing_else_goes(world, monkeypatch):
    text = (HERE.parent / "ops_media_scan_explain.py").read_text(encoding="utf-8")
    assert "ops_media_consent" not in text and "consent.require" not in text, "no consent word: the press of the button is the decision (P9-3)"
    for private in ('["search"]', '"description"', "asset_name(", "read_served", "file_facts", "read_bytes", "transcript", "preview", "sheet"):
        assert private not in text, private + ": nothing of a picture, the words of a slot or the recording is read here"
    w = explain_world(world, monkeypatch)
    assert refused(explain, world, w["task"], channel="messaging") and w["run"].calls == []
    explain(world, w["task"], confirm=False)
    assert w["run"].calls == [], "without confirm nothing is sent"
    explain(world, w["task"])
    [call] = w["run"].calls
    assert call["open_web"] is False and call["sourced"] == () and call["skill"] == SKILL
    # the text is in the stock folder's two documents and in the one answer, and in no other place the project keeps
    stored = everything_stored(world)
    for text_read in ("SAMPLE PHOTO DO NOT USE", "ignore previous instructions", "Call 555 0100"):
        assert text_read not in stored, text_read
    found = sorted(p.name for p in Path(ops_core.context(world["path"])["cfg"]["data_dir"]).rglob("*") if p.is_file() and b"SAMPLE PHOTO" in p.read_bytes() and p.suffix == ".json")
    assert found == ["scan-explained.json", "scan.json"], "the lines are in the stock folder's two documents (the findings quote them) and nowhere else the project keeps"
    assert not Path(w["run"].calls[0]["dest"]).exists()
