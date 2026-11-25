"""One of our own ports drawn end to end by the ffmpeg engine under the second contract (PF-a4), offline, with the host's Chromium and ffmpeg and the stand-in
runtime: a FICTIONAL tier-B card port and caption port (the kit's) with a recorded determinism test, a render drawn twice byte-identical, caption frames
written as `cap_*`, the proofs in the summary; a port with no record is refused on the engine; a port whose record is at another runtime is not proven. The real
runtime and the five real ports are the live legs' and the supervisor's. Skipped with a reason where ffmpeg or Chromium is absent."""
from __future__ import annotations

import re

import pytest

import renderer_kit as K
import hf_second_kit as H
import hf_port_kit as P
import _cdp
import _hf_host

needs_all = pytest.mark.skipif(not (K.HAVE_FFMPEG and K.BROWSER), reason=K.SKIP_MEDIA + "; " + K.SKIP_BROWSER)


@pytest.fixture(scope="module")
def pipe(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("port")
    files = K.pipeline(tmp, K.build_transcript(K.SHORT_SENTENCES[:2]), H.POST)
    return {"files": files, "tmp": tmp}


def setup(pipe, monkeypatch, tag, kinds=("card", "caption"), record=True, runtime_hash=None):
    tmp = pipe["tmp"] / tag
    rt = P.port_runtime(monkeypatch, tmp)
    rsha = runtime_hash or _hf_host.load_runtime(rt["vendor"], rt["runtime_dir"] + "/shims", H.FPS, _cdp.browser_version(K.BROWSER))["runtime_sha256"]
    blocks = P.blocks_folder(tmp, kinds, rsha if record else None)
    tail = ["--blocks", blocks, "--vendor", rt["vendor"]]
    env = {"RENDERER_TEST": "1", "RENDERER_HF_RUNTIME_DIR": rt["runtime_dir"]}
    return tail, env, tmp


def render(pipe, tail, env, out, *more):
    return K.run_verb(*K.render_args(pipe["files"], out, "--jobs", "2", *tail, *more, slots=()), env=env)


def refusal(err: str) -> tuple:
    m = re.match(r"refused: (\S+)\s*(.*)", err)
    return (m.group(1), m.group(2).strip()) if m else (None, err[-300:])


@needs_all
def test_a_card_port_and_a_caption_port_are_drawn_twice_byte_identical_and_the_summary_carries_their_proofs(pipe, monkeypatch):
    tail, env, tmp = setup(pipe, monkeypatch, "both")
    rc1, one, err1 = render(pipe, tail, env, tmp / "o1")
    assert rc1 == 0, err1
    rc2, two, err2 = render(pipe, tail, env, tmp / "o2")
    assert rc2 == 0, err2
    assert one["sha256"] == two["sha256"] and one["frames_rendered"] > 40
    assert set(one["hf_proofs"]) == {P.CARD, P.CAPTION}
    for name, proof in one["hf_proofs"].items():
        assert re.fullmatch(r"[0-9a-f]{64}", proof["served_sha256"]) and re.fullmatch(r"[0-9a-f]{64}", proof["runtime_sha256"]) and one["blocks"][name] == proof["served_sha256"]
    assert set(one["layers"]) == {"beat", "caption"} and one["seconds"]["gates"] >= 0
    assert [e["block"] for e in one["beats_drawn"] if e["preset"] == "keyword"] == [P.CARD]


@needs_all
def test_a_caption_port_alone_draws_the_caption_track_and_a_card_port_alone_the_beat_track(pipe, monkeypatch):
    tail, env, tmp = setup(pipe, monkeypatch, "cap", kinds=("caption",))
    rc, out, err = render(pipe, tail, env, tmp / "o")
    assert rc == 0, err
    assert set(out["hf_proofs"]) == {P.CAPTION} and "oh:keyword" in {e["block"] for e in out["beats_drawn"]}
    tail, env, tmp = setup(pipe, monkeypatch, "card", kinds=("card",))
    rc, out, err = render(pipe, tail, env, tmp / "o")
    assert rc == 0, err
    assert set(out["hf_proofs"]) == {P.CARD}


@needs_all
def test_a_port_with_no_recorded_test_is_not_on_the_engine_and_a_record_at_another_runtime_is_not_proven(pipe, monkeypatch):
    # an engine default that names a port with no record does not even load: the catalogue is refused
    tail, env, tmp = setup(pipe, monkeypatch, "norecord", record=False)
    rc, out, err = render(pipe, tail, env, tmp / "o", "--dry-run")
    assert rc == 1 and refusal(err)[0] == "block_schema", err
    tail, env, tmp = setup(pipe, monkeypatch, "wrongruntime", runtime_hash="e" * 64)
    rc, out, err = render(pipe, tail, env, tmp / "o")                  # a dry run has no browser to name the runtime: only a render proves it
    assert rc == 1 and refusal(err)[0] == "block_not_proven", err


@needs_all
def test_a_changed_fragment_is_block_hash_at_render_even_when_the_pins_were_not_rewritten(pipe, monkeypatch):
    tail, env, tmp = setup(pipe, monkeypatch, "tamper", kinds=("card",))
    path = tmp / "blocks" / "hf" / "oh-test-badge" / "gsap.html"
    path.write_bytes(path.read_bytes() + b"\n")
    rc, out, err = render(pipe, tail, env, tmp / "o", "--dry-run")
    assert rc == 1 and refusal(err)[0] == "block_hash", err


@needs_all
def test_a_dry_run_reads_proves_and_names_the_ports_without_a_browser(pipe, monkeypatch):
    tail, env, tmp = setup(pipe, monkeypatch, "dry")
    rc, out, err = render(pipe, tail, env, tmp / "o", "--dry-run")
    assert rc == 0, err
    assert out["dry_run"] is True and out["hf_proofs"][P.CARD]["runtime_sha256"] == "" and out["hf_proofs"][P.CAPTION]["served_sha256"]
