"""The `admit-block` verb of ffmpeg.py (PF-a3), the host side, with the fake docker: the plan alone starts no container and writes nothing; a confirmed
admission stages the component, the entry, the vocabulary and the blocks into the read-only job folder, reads the container's result through the closed
schema, and writes only after a result that matches the plan. The measurement itself is `test_admit.py`'s (the container's entry point on the host)."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import docker_kit as DK
import hf_second_kit as H
import renderer_kit as K
import _docker as D
from test_admit import COMPONENT, tree, world

RESULT = {"ok": True, "runs": 4, "blocked": 0, "samples": 2, "frames": 108, "seconds": 9.5, "browser": "HeadlessChrome/fake", "runtime_sha256": "d" * 64,
          "per_sample": [{"frames": 54, "digest": "a" * 64}, {"frames": 54, "digest": "b" * 64}], "planted": "x"}


def admit_args(w, *more):
    return ["admit-block", "--source", w["source"], "--component", COMPONENT, "--entry", w["entry"], "--vocabulary", K.VOCABULARY, *more]


def env_of(w, **extra):
    return {"RENDERER_TEST": "1", "RENDERER_HF_RUNTIME_DIR": w["runtime"], "RENDERER_BLOCKS_DIR": w["blocks"], **extra}


def fake_result(dk, w, planned_served, **over):
    dk.cfg["run"] = "files"
    dk.cfg["files"] = {"result.json": {"text": json.dumps(dict(RESULT, **dict({"served_sha256": planned_served}, **over)))}}
    dk.save()


def test_without_confirmed_the_plan_is_printed_and_nothing_is_written_and_no_container_starts(tmp_path):
    (tmp_path / "home").mkdir()
    dk = DK.World(tmp_path)
    w = world(tmp_path / "w")
    before = tree(w["tmp"])
    rc, out, err = dk.host(*admit_args(w), env=env_of(w))
    assert rc == 0, err
    assert out["dry_run"] is True and out["name"] == H.NAME and out["samples"] == 2 and out["name_taken"] is False and out["writes"][-1] == "blocks/hf/allowlist.json"
    assert tree(w["tmp"]) == before and dk.runs() == []


def test_a_clone_at_another_commit_is_refused_before_anything_else(tmp_path):
    (tmp_path / "home").mkdir()
    dk = DK.World(tmp_path)
    w = world(tmp_path / "w")
    (Path(w["runtime"]) / "registry.sha256").write_text("# commit %s\n" % ("a" * 40))
    rc, out, err = dk.host(*admit_args(w, "--confirmed"), env=env_of(w))
    assert rc == 1 and err.startswith("refused: admitted_commit source"), err
    assert dk.runs() == []


def test_a_confirmed_admission_stages_what_the_container_reads_and_writes_the_entry_after_the_result(tmp_path):
    (tmp_path / "home").mkdir()
    dk = DK.World(tmp_path)
    w = world(tmp_path / "w")
    from test_admit import plan
    served = plan(w)["entry"]["served_sha256"]
    pins_before = hashlib.sha256((Path(w["blocks"]) / "pins.json").read_bytes()).hexdigest()      # the world's own pins (an empty allowlist since P2r), staged before the entry is written
    fake_result(dk, w, served)
    rc, out, err = dk.host(*admit_args(w, "--confirmed"), env=env_of(w))
    assert rc == 0, err
    argv = dk.runs()[0]["argv"]
    mounts = [argv[i + 1] for i, a in enumerate(argv) if a == "-v"]
    assert len(mounts) == 2 and mounts[0].endswith(":/job:ro") and mounts[1].endswith(":/out:rw") and not any("/in/recording" in m for m in mounts)
    assert argv[argv.index("--network") + 1] == "none"
    inner = argv[argv.index("admit-check"):]
    assert inner[inner.index("--entry") + 1] == "/job/entry.json" and inner[inner.index("--component-dir") + 1] == "/job/component"
    assert inner[inner.index("--blocks") + 1] == "/job/blocks" and inner[inner.index("--blocks-sha256") + 1] == pins_before and "--in" not in inner
    assert out["ok"] is True and out["staged"] is False and out["determinism"]["runs"] == 4 and out["determinism"]["frames"] == 108
    assert out["determinism"]["image"] == D.image_tag() and "planted" not in json.dumps(out)
    allow = json.loads((Path(w["blocks"]) / "hf" / "allowlist.json").read_text())
    assert [b["name"] for b in allow["blocks"]] == [H.NAME] and allow["blocks"][0]["determinism"]["runtime_sha256"] == "d" * 64
    assert "%s/%s" % (COMPONENT, H.FILE) in (Path(w["runtime"]) / "registry.sha256").read_text()


def test_a_taken_name_is_staged_and_the_stderr_says_name_taken(tmp_path):
    (tmp_path / "home").mkdir()
    dk = DK.World(tmp_path)
    w = world(tmp_path / "w", name="hf:spring-pop")
    from test_admit import plan
    fake_result(dk, w, plan(w)["entry"]["served_sha256"])
    rc, out, err = dk.host(*admit_args(w, "--confirmed"), env=env_of(w))
    assert rc == 0 and out["staged"] is True and out["name_taken"] is True and "name_taken hf:spring-pop" in err, err
    assert (Path(w["runtime"]) / "staged" / "spring-pop.json").exists()
    assert json.loads((Path(w["blocks"]) / "hf" / "allowlist.json").read_text())["blocks"] == []


def test_a_result_that_is_not_the_plans_or_a_refusal_in_the_container_writes_nothing(tmp_path):
    (tmp_path / "home").mkdir()
    dk = DK.World(tmp_path)
    w = world(tmp_path / "w")
    from test_admit import plan
    served = plan(w)["entry"]["served_sha256"]
    before = tree(w["tmp"])
    for over in ({"served_sha256": "1" * 64}, {"blocked": 1}, {"runs": 3}, {"samples": 1}):
        fake_result(dk, w, served, **over)
        rc, out, err = dk.host(*admit_args(w, "--confirmed"), env=env_of(w))
        assert rc == 1 and err.startswith("refused: admit_result"), (over, err)
        assert tree(w["tmp"]) == before
    dk.cfg["files"] = {"result.json": {"text": json.dumps({"ok": False, "code": "determinism_failed", "field": "sample 2 frame 7", "problems": []})}}
    dk.cfg["rc"] = 1
    dk.save()
    rc, out, err = dk.host(*admit_args(w, "--confirmed"), env=env_of(w))
    assert rc == 1 and err.startswith("refused: determinism_failed sample 2 frame 7"), err
    assert tree(w["tmp"]) == before


def test_the_result_schema_keeps_only_the_fields_it_names():
    clean = D.sanitise(dict(RESULT, served_sha256="c" * 64), D.RESULT_SCHEMAS["admit-check"], "admit-check")
    assert "planted" not in clean and clean["per_sample"][0] == {"frames": 54, "digest": "a" * 64} and clean["frames"] == 108


def test_the_verb_is_host_only_and_the_container_module_is_in_the_image():
    assert "_admit.py" in D.HOST_ONLY and "_admit.py" not in D.definition_files()
    assert "_admit_check.py" in D.definition_files()
