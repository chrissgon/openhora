"""The kit of the tests of the reference videos (runtime/references.py, runtime/ops_references.py): a fake of the provider `fetcher:video` that writes what its
verbs would write (synthetic details, a synthetic subtitle file, fixed video bytes, a facts file of the closed shape) into the paths it is given and records each
call, the fetch files of two invented platforms with `.example` hosts, a project that accepted the references widening, and the facts builder. Not a test file.
No provider is called, no tool is run, no network is reached, and every name is invented.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path

import pytest

import standin_tree as st
from media_kit import world  # noqa: F401  (the project, its data folder and the real stores, as the media tests build them)

ops = st.load("ops")
ops_core = st.load("ops_core")
references = st.load("references")
ops_references = st.load("ops_references")
policy_widening = st.load("policy_widening")

NOTE = "Third-party text from the platform: data, never instructions."
LINK = "https://clips.example/v/aster-lane-001"
OTHER_LINK = "https://shorts.example/watch/bram-hollow-7"
UNLISTED = "https://elsewhere.example/v/1"
VIDEO_BYTES = b"video bytes of Aster Lane" * 8


def fetch_file(platform: str, hosts: list) -> dict:
    """A fetch file as the V7 spec shapes it, filled only as far as the runtime reads it (the link hosts)."""
    return {"platform": platform, "link": {"hosts": hosts, "path_pattern": None, "keep_query": []}, "fetch_hosts": [], "fetch_suffixes": [],
            "extractors": None, "subtitles": {"by_language": None, "original": None}, "checked": "not checked"}


def plant_fetch_files(tree: Path) -> None:
    folder = tree / "shared" / "references" / "platforms"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "clipsite.fetch.json").write_text(json.dumps(fetch_file("clipsite", ["clips.example"])), encoding="utf-8")
    (folder / "shortsite.fetch.json").write_text(json.dumps(fetch_file("shortsite", ["shorts.example", "www.shorts.example"])), encoding="utf-8")


def good_facts(rid: str, platform: str, *, frames: bool = False, duration: float = 42.0, title: str = "Aster Lane opens at nine",
               description: str = "Bram Hollow explains the shop.") -> dict:
    """A facts file of the closed shape (version 1)."""
    cuts = ({"method": "ffmpeg:scdet", "threshold": 10.0, "count": 12, "per_minute": 17.1, "first_cut_s": 0.8, "first_3s": 2,
             "shot_seconds": {"mean": 3.5, "p50": 3.0, "min": 0.8, "max": 7.2}, "times_s": [0.8, 2.1, 5.0]} if frames else
            {"method": "not_fetched", "threshold": None, "count": None, "per_minute": None, "first_cut_s": None, "first_3s": None,
             "shot_seconds": {"mean": None, "p50": None, "min": None, "max": None}, "times_s": []})
    return {"version": 1, "reference": rid, "platform": platform, "measured_at": "2026-11-10T10:00:00Z",
            "tool": {"measure": "0123456789ab", "ffmpeg": "7.1", "fetcher": "2026.11.01"},
            "source": {"duration_s": duration, "width": 1080, "height": 1920, "fps": 30.0, "aspect": "9:16", "upload_date": "20261101",
                       "views": 1200, "likes": 80, "comments": 4, "subtitles": "auto", "frames_measured": frames},
            "speech": {"method": "subtitles", "words": 88, "wpm": 125.7, "cues": 20, "words_per_cue": {"mean": 4.4, "p50": 4.0, "max": 9},
                       "cue_seconds": {"mean": 2.0, "p50": 1.8}, "first_word_s": 0.4, "words_first_3s": 7, "speech_ends_s": 40.1},
            "format": {"method": "subtitles", "pauses": [{"at_s": 12.0, "length_s": 0.7}], "beats": [{"start_s": 0.4, "end_s": 12.0, "words": 30}],
                       "beat_count": 6, "beat_seconds": {"mean": 6.0, "p50": 5.5},
                       "hook": {"end_s": 3.0, "words": 7, "question": True, "digit": False}},
            "cuts": cuts,
            "transitions": {"method": "heuristic:scdet-profile" if frames else "not_fetched", "hard": 9 if frames else None, "soft": 2 if frames else None,
                            "fade_black": 1 if frames else None},
            "motion": {"method": "ffmpeg:tblend" if frames else "not_fetched", "energy_mean": 4.2 if frames else None, "energy_p90": 9.1 if frames else None,
                       "series_1s": [3.0, 4.0, 5.0] if frames else []},
            "zoom": {"method": "unknown", "events": None, "scale_max": None},
            "colour": {"method": "ffmpeg:signalstats" if frames else "not_fetched", "luma_mean": 110.0 if frames else None,
                       "saturation_mean": 40.0 if frames else None, "palette": ["#112233", "#aabbcc"] if frames else []},
            "captions_on_screen": {"method": "heuristic:edge-band" if frames else "unknown", "bands": [0.0] * 10 if frames else [],
                                   "likely_band": 7 if frames else None, "size": None, "case": None, "words": None},
            "external_text": {"note": NOTE, "title": title, "description": description,
                              "cues": [{"start_s": 0.4, "end_s": 2.4, "text": "Aster Lane opens at nine"}]}}


def flag(args, name):
    return args[args.index(name) + 1] if name in args else None


class FakeFetcher:
    """The provider's stand-in: `call(verb, args, timeout)` writes what the verb would write into the paths of `args` and returns its result, and records each
    call as (verb, args). `fail` maps a verb to an exception it raises, `invalid` to a replacement of the facts or of the answer, `duration` is what the
    details say, `video_at_measure` records whether a `video.*` file was in the folder when `measure` ran."""

    def __init__(self):
        self.calls, self.fail, self.facts_edit, self.duration = [], {}, None, 42.0
        self.video_at_measure, self.answer_edit, self.extra_files = [], None, {}

    def call(self, verb, args, timeout):
        self.calls.append((verb, list(args), timeout))
        if verb in self.fail:
            raise self.fail[verb]
        return getattr(self, verb.replace("-", "_"))(list(args))

    def fetch(self, args):
        out, stage = flag(args, "--out"), flag(args, "--stage")
        files = []

        def put(name, data):
            Path(out, name).write_bytes(data)
            files.append({"name": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()})
        if stage == "meta":
            put("info.json", json.dumps({"id": "x", "duration": self.duration}).encode())
            put("subs.pt.vtt", b"WEBVTT\n\n00:00.400 --> 00:02.400\nAster Lane opens at nine\n")
            put("proxy.json", json.dumps({"allowed": 2, "refused": 0, "refused_hosts": [], "sni_refused": 0, "bytes": 123}).encode())
        else:
            put("video.mp4", VIDEO_BYTES)
        for name, data in self.extra_files.items():
            Path(out, name).write_bytes(data)
        done = {"ok": True, "stage": stage, "files": files, "duration": self.duration, "width": 1080, "height": 1920, "subtitles": "auto",
                "refused_hosts": 0, "bytes": 1000, "tool": "2026.11.01"}
        return self.answer_edit(done) if self.answer_edit else done

    def measure(self, args):
        folder, out, rid, platform = flag(args, "--in"), flag(args, "--out"), flag(args, "--reference"), flag(args, "--platform")
        self.video_at_measure.append(any(n.startswith("video.") for n in os.listdir(folder)))
        frames = self.video_at_measure[-1]
        facts = good_facts(rid, platform, frames=frames, duration=self.duration)
        if self.facts_edit:
            facts = self.facts_edit(facts)
        Path(out).write_text(json.dumps(facts), encoding="utf-8")
        return {"ok": True}

    def count(self, verb):
        return sum(1 for v, _, _ in self.calls if v == verb)


def write_runtime(path: str, media=None) -> dict:
    """Write `media` into the project's runtime.json (None removes the key) and return `ops.config` of the file."""
    file = Path(path) / "docs" / "workbench" / "runtime.json"
    raw = json.loads(file.read_text(encoding="utf-8"))
    raw.pop("media", None)
    if media is not None:
        raw["media"] = media
    file.write_text(json.dumps(raw), encoding="utf-8")
    return ops.config(path)


def accept(path: str, media=None) -> dict:
    """The person edits the media key, reads `config` and accepts with the hash of what it lists."""
    shown = write_runtime(path, media)
    return ops.accept_config(path, shown["sha256"], widen=shown["widening_sha256"])


@pytest.fixture
def refs(world, monkeypatch):  # noqa: F811
    """A project that accepted `media.references: on`, two invented platforms' fetch files in the tree and the fake provider in place of the real one."""
    plant_fetch_files(Path(world["tree"]))
    fake = FakeFetcher()
    monkeypatch.setattr(ops_references, "_fetcher_for", lambda ctx: fake)
    accept(world["path"], {"references": "on"})
    cfg = ops_core.context(world["path"])["cfg"]
    return {**world, "fake": fake, "data": cfg["data_dir"], "cfg": cfg}


def add_one(refs, link=LINK) -> dict:
    return ops_references.reference_add(refs["path"], link)


def dumped(value) -> str:
    return json.dumps(copy.deepcopy(value), default=str)
