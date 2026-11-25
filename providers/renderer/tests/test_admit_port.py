"""The admission of one of our own ports to the ffmpeg engine's second contract (PF-a4): the plan (both lints, the pin, `HEAD`, the digest; nothing written), the
record written into the port's block.json and the blocks pinned again, and the measurement run offline with the host's Chromium and ffmpeg on the kit's
FICTIONAL card and caption ports with a stand-in runtime (a card port on its samples, a caption port on the caption lines). The five real ports are measured
in the image by the supervisor (PF-a4b). Skipped with a reason where a tool is absent."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

import pytest

import docker_kit as DK
import renderer_kit as K
import hf_port_kit as P
import _admit
import _admit_check
import _blocks
import _hf_host
import _hf_port
from _text import Refusal
from test_admit import git, tree

needs_all = pytest.mark.skipif(not (K.HAVE_FFMPEG and K.BROWSER), reason=K.SKIP_MEDIA + "; " + K.SKIP_BROWSER)


def refused(fn, *a, **k) -> Refusal:
    with pytest.raises(Refusal) as e:
        fn(*a, **k)
    return e.value


def repo(tmp_path, kinds=("card", "caption")):
    """A git repository whose `blocks/` holds the committed blocks and the kit's fictional ports (no record, not an engine default), all committed."""
    folder = P.blocks_folder(tmp_path, kinds, None, engine_presets=False)
    git("init", "-q", cwd=tmp_path)
    git("add", ".", cwd=tmp_path)
    git("commit", "-q", "-m", "c", cwd=tmp_path)
    return folder


def record_for(planned, **over):
    r = {"served_sha256": planned["served_sha256"], "runtime_sha256": "e" * 64, "samples": planned["samples"], "frames": 120, "runs": 4, "blocked": 0, "seconds": 3.5}
    r.update(over)
    return r


def test_the_plan_lints_hashes_and_counts_the_samples_and_writes_nothing(tmp_path):
    folder = repo(tmp_path)
    before = tree(folder)
    card = _admit.plan_port(P.CARD, folder, str(tmp_path))
    caption = _admit.plan_port(P.CAPTION, folder, str(tmp_path))
    assert tree(folder) == before
    assert card["samples"] == 1 and caption["samples"] == len(_admit_check.CAPTION_LINES) == 3
    assert re.fullmatch(r"[0-9a-f]{64}", card["served_sha256"]) and card["summary"]["plan"] is True and card["summary"]["had_record"] is False
    assert card["summary"]["writes"] == ["hf/oh-test-badge/block.json", "pins.json", "catalogue.json"]
    assert card["served_sha256"] == _hf_port.served_digest(P.fragment("card").encode())


def test_a_working_file_that_differs_from_head_is_admitted_commit_and_one_that_differs_from_its_pin_is_block_hash(tmp_path):
    folder = repo(tmp_path)
    path = Path(folder) / "hf" / "oh-test-badge" / "gsap.html"
    path.write_text(path.read_text() + "\n")
    assert refused(_admit.plan_port, P.CARD, folder, str(tmp_path)).code == "block_hash"          # the pin is the first guard
    _blocks.write_pins(folder)
    assert refused(_admit.plan_port, P.CARD, folder, str(tmp_path)).code == "admitted_commit"      # re-pinned, but not what is committed
    git("add", ".", cwd=tmp_path)
    git("commit", "-q", "-m", "d", cwd=tmp_path)
    assert _admit.plan_port(P.CARD, folder, str(tmp_path))["name"] == P.CARD


def test_a_file_that_is_not_tracked_is_admitted_commit(tmp_path):
    folder = repo(tmp_path, kinds=("card",))
    other = P.block_doc("caption")
    (Path(folder) / "hf" / "oh-test-line").mkdir()
    (Path(folder) / "hf" / "oh-test-line" / "gsap.html").write_text(P.fragment("caption"))
    (Path(folder) / "hf" / "oh-test-line" / "block.json").write_text(json.dumps(other, indent=1) + "\n")
    _blocks.write_pins(folder)
    assert refused(_admit.plan_port, P.CAPTION, folder, str(tmp_path)).code == "admitted_commit"


@pytest.mark.parametrize("name", ["oh:keyword", "hf:nothing-here", "keyword", "hf:", "hf:Bad Name"])
def test_a_tier_a_oh_or_unknown_name_is_admit_entry(tmp_path, name):
    folder = repo(tmp_path)
    assert refused(_admit.plan_port, name, folder, str(tmp_path)).code == "admit_entry"


def test_a_planted_fragment_the_lint_refuses_is_block_lint_at_the_plan(tmp_path):
    folder = repo(tmp_path, kinds=("card",))
    path = Path(folder) / "hf" / "oh-test-badge" / "gsap.html"
    path.write_text(path.read_text().replace("badge.textContent", "window.name = 1; badge.textContent"))
    _blocks.write_pins(folder)
    assert refused(_admit.plan_port, P.CARD, folder, str(tmp_path)).code == "block_lint"


def test_the_record_lands_in_the_block_json_the_blocks_are_pinned_again_and_the_ffmpeg_engine_then_lists_the_port(tmp_path):
    folder = repo(tmp_path)
    assert "ffmpeg" not in {e["name"]: e for e in json.loads(_blocks.catalogue_bytes(_blocks.load_catalogue(folder)))["blocks"]}[P.CARD]["engines"]
    planned = _admit.plan_port(P.CARD, folder, str(tmp_path))
    rec = _admit.record_of_port(record_for(planned), planned, "openhora-renderer:test", "2026-11-24")
    assert rec["date"] == "2026-11-24" and rec["image"] == "openhora-renderer:test" and rec["runs"] == 4 and rec["samples"] == 1
    out = _admit.write_port(planned, rec)
    assert len(out["written"]) == 3
    cat = _blocks.load_catalogue(folder)
    block = cat["blocks"][P.CARD]
    assert block["determinism"] == rec and _blocks.engines_of(cat, block) == ["ffmpeg", "hyperframes"] if "hyperframes" in cat["engines"] else True
    listed = {e["name"]: e for e in json.loads((Path(folder) / "catalogue.json").read_text())["blocks"]}
    assert "ffmpeg" in listed[P.CARD]["engines"] and "ffmpeg" not in listed[P.CAPTION]["engines"]
    assert _blocks.runtime_of(cat, block, "ffmpeg") == "gsap"
    assert (Path(folder) / "hf" / "oh-test-badge" / "gsap.html").read_text() == P.fragment("card")      # the port's file is never touched


@pytest.mark.parametrize("over", [{"runs": 3}, {"blocked": 1}, {"samples": 7}, {"frames": 0}, {"served_sha256": "f" * 64}, {"runtime_sha256": "short"}])
def test_a_measurement_that_does_not_match_the_plan_is_admit_result_and_writes_nothing(tmp_path, over):
    folder = repo(tmp_path)
    planned = _admit.plan_port(P.CARD, folder, str(tmp_path))
    before = tree(folder)
    assert refused(_admit.record_of_port, record_for(planned, **over), planned, "img").code == "admit_result"
    assert tree(folder) == before


def test_a_record_for_another_served_hash_is_refused_by_write_port_before_the_first_write(tmp_path):
    folder = repo(tmp_path)
    planned = _admit.plan_port(P.CARD, folder, str(tmp_path))
    good = _admit.record_of_port(record_for(planned), planned, "img", "2026-11-24")
    before = tree(folder)
    assert refused(_admit.write_port, planned, dict(good, served_sha256="a" * 64)).code == "admit_result"
    assert tree(folder) == before


def test_the_host_verb_takes_either_a_port_or_the_registry_flags_and_a_plan_starts_no_container(tmp_path):
    (tmp_path / "home").mkdir()
    dk = DK.World(tmp_path)
    rc, out, err = dk.host("admit-block", "--port", P.CARD, "--source", str(tmp_path), "--vocabulary", K.VOCABULARY)
    assert rc == 2 and "exclusive" in err, err
    rc, out, err = dk.host("admit-block", "--vocabulary", K.VOCABULARY)
    assert rc == 2 and "--port" in err, err
    rc, out, err = dk.host("admit-block", "--port", "oh:keyword", "--vocabulary", K.VOCABULARY)
    assert rc == 1 and err.startswith("refused: admit_entry"), err
    assert dk.runs() == []


def test_the_inner_verb_refuses_a_port_with_an_entry_and_needs_one_of_them(tmp_path):
    rc, out, err = K.run_verb("admit-check", "--port", P.CARD, "--entry", str(tmp_path / "e.json"), "--vocabulary", K.VOCABULARY, "--blocks", str(K.BLOCKS),
                              "--blocks-sha256", K.BLOCKS_SHA256, "--scratch", str(tmp_path))
    assert rc == 2, err
    rc, out, err = K.run_verb("admit-check", "--vocabulary", K.VOCABULARY, "--blocks", str(K.BLOCKS), "--blocks-sha256", K.BLOCKS_SHA256, "--scratch", str(tmp_path))
    assert rc == 2 and "--port" in err, err


# ---------------------------------------------------------------- the measurement

def check_args(tmp, monkeypatch, name, kinds=("card", "caption"), extra=""):
    rt = P.port_runtime(monkeypatch, tmp)
    folder = P.blocks_folder(tmp, kinds, None, extra=extra, engine_presets=False, name="blocks-m")
    sha = hashlib.sha256((Path(folder) / "pins.json").read_bytes()).hexdigest()
    scratch = Path(tmp) / "scratch"
    scratch.mkdir()
    args = ["admit-check", "--port", name, "--vocabulary", K.VOCABULARY, "--blocks", folder, "--blocks-sha256", sha, "--scratch", scratch, "--vendor", rt["vendor"], "--jobs", "2"]
    return args, {"RENDERER_TEST": "1", "RENDERER_HF_RUNTIME_DIR": rt["runtime_dir"]}


@needs_all
def test_a_clean_card_port_passes_the_whole_measurement_on_its_samples(tmp_path, monkeypatch):
    args, env = check_args(tmp_path, monkeypatch, P.CARD)
    rc, out, err = K.run_verb(*args, env=env)
    assert rc == 0, err
    assert out["served_sha256"] == _hf_port.served_digest(P.fragment("card").encode()) and out["runs"] == 4 and out["blocked"] == 0 and out["samples"] == 1
    assert re.fullmatch(r"[0-9a-f]{64}", out["runtime_sha256"]) and out["frames"] > 20 and out["per_sample"][0]["frames"] == out["frames"]


@needs_all
def test_a_clean_caption_port_passes_on_the_caption_lines_and_measures_caption_frames_only(tmp_path, monkeypatch):
    args, env = check_args(tmp_path, monkeypatch, P.CAPTION, kinds=("caption",))
    rc, out, err = K.run_verb(*args, env=env)
    assert rc == 0, err
    assert out["samples"] == len(_admit_check.CAPTION_LINES) and len(out["per_sample"]) == 3 and out["frames"] > 60
    assert not list(Path(tmp_path, "scratch").glob("*/frames"))


@needs_all
def test_a_port_that_draws_from_a_value_the_runtime_changes_is_refused_by_the_comparator_or_the_lint(tmp_path, monkeypatch):
    """The fragment lint catches `Math.random` before any drawing (`block_lint`): the port's own guard, which an admitted registry block does not have."""
    args, env = check_args(tmp_path, monkeypatch, P.CARD, kinds=("card",))
    folder = Path(args[args.index("--blocks") + 1])
    path = folder / "hf" / "oh-test-badge" / "gsap.html"
    path.write_text(path.read_text().replace("tl.fromTo(", "badge.style.left = (30 + Math.random() * 40) + '%'; tl.fromTo("))
    _blocks.write_pins(str(folder))
    args[args.index("--blocks-sha256") + 1] = hashlib.sha256((folder / "pins.json").read_bytes()).hexdigest()
    rc, out, err = K.run_verb(*args, env=env)
    assert rc == 1 and err.startswith("refused: block_lint"), err


@needs_all
def test_the_comparator_judges_a_caption_sample_and_the_unmeasurable_port_is_admit_entry(tmp_path, monkeypatch):
    args, env = check_args(tmp_path, monkeypatch, "oh:keyword", kinds=("card",))
    rc, out, err = K.run_verb(*args, env=env)
    assert rc == 1 and err.startswith("refused: admit_entry"), err
