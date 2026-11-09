"""The kit of the engine contract (V3c), offline: the frame band round-trips and reads back from a recording made by the host's ffmpeg, the
real-size and the maximum transcripts have the shape the live legs need, the planted blocks differ from the committed ones by one file each, the
report's schema is closed, every committed report passes it and the live file lists both engines for the legs they share. No container, no
browser, no network; every input is invented.
"""
from __future__ import annotations

import copy
import json
import re
import subprocess
from pathlib import Path

import pytest

import renderer_kit as K
import contract_kit as C
import _blocks
import _edl
from _vocab import load_data, load_vocabulary

DATA = load_data()
VOCAB = load_vocabulary(str(K.VOCABULARY))
needs_media = pytest.mark.skipif(not K.HAVE_FFMPEG, reason=K.SKIP_MEDIA)
REPORTS = K.RENDERER / "reports"


# ---------------------------------------------------------------- the band

def test_the_band_round_trips_every_kind_of_frame_number_and_draws_the_least_significant_bit_on_the_left():
    for n in (0, 1, 2, 3, 29, 30, 255, 256, 4893, 7262, 8191, 8192, 9000, 16383):
        cells = C.band_cells(n)
        assert len(cells) == 14 and set(cells) <= {0, 255} and C.band_index(cells) == n
    assert C.band_cells(1)[0] == 255 and set(C.band_cells(1)[1:]) == {0}
    assert C.band_cells(2)[:2] == [0, 255]
    raw = b"".join(bytes(C.band_cells(n)) for n in (5, 0, 9000))
    assert C.read_band(raw) == [5, 0, 9000]
    assert C.band_index([127] * 13 + [128]) == 1 << 13            # 128 is a one, 127 a zero
    for bad in (-1, 1 << 14, True, 1.5):
        with pytest.raises(ValueError):
            C.band_cells(bad)
    with pytest.raises(ValueError):
        C.read_band(b"\x00" * 15)


def test_the_band_sits_above_the_cards_and_holds_the_longest_input():
    assert (C.BAND_W, C.BAND_H) == (1008, 96) and C.BAND_H <= DATA["zones"]["card_top"]
    assert (1 << C.BAND_BITS) > DATA["limits"]["input_seconds_max"] * 30


def test_the_expected_sources_follow_the_kept_ranges_in_order():
    assert C.expected_sources([[0, 3], [10, 12], [20, 21]]) == [0, 1, 2, 10, 11, 20]


def test_the_commands_are_lists_with_no_shell_and_end_at_the_named_file():
    args = C.source_args(C.short_transcript(), "/out/in.mp4")
    assert args[-1] == "/out/in.mp4" and "-filter_complex" in args and C.band_filter() == args[args.index("-filter_complex") + 1]
    assert "geq=lum=" in C.band_filter() and "overlay=0:0" in C.band_filter()
    read = C.band_read_args("/out/a.mp4", "/out/band.raw")
    assert "crop=1008:96:0:0,scale=14:1:flags=area,format=gray" in read and read[-1] == "/out/band.raw"
    long = C.long_recording_args("/out/long.mp4")
    assert "duration=301" in " ".join(long) and long[-1] == "/out/long.mp4"


@needs_media
def test_the_band_reads_back_zero_to_n_minus_one_from_a_recording_the_host_ffmpeg_makes(tmp_path):
    doc = C.short_transcript()
    src, raw = tmp_path / "in.mp4", tmp_path / "band.raw"
    subprocess.run([K.FFMPEG, *C.source_args(doc, str(src))], check=True, timeout=300)
    subprocess.run([K.FFMPEG, *C.band_read_args(str(src), str(raw))], check=True, timeout=300)
    frames = C.read_band(raw.read_bytes())
    assert len(frames) >= int(doc["duration"] * 30) - 1
    assert frames == list(range(len(frames)))
    info = subprocess.run([K.FFPROBE, "-v", "error", "-show_entries", "stream=codec_type,width,height,avg_frame_rate", "-of", "json", str(src)],
                          capture_output=True, text=True, check=True, timeout=60)
    streams = {s["codec_type"]: s for s in json.loads(info.stdout)["streams"]}
    assert (streams["video"]["width"], streams["video"]["height"], streams["video"]["avg_frame_rate"]) == (1080, 1920, "30/1") and "audio" in streams


@needs_media
def test_the_band_survives_a_cut_and_a_re_encode_at_the_kept_frames(tmp_path):
    """The reading holds on frames that went through an encoder after a cut, the way a render's output has: keep source frames 30-39 and 100-104."""
    doc = C.short_transcript()
    src, cut, raw = tmp_path / "in.mp4", tmp_path / "cut.mp4", tmp_path / "band.raw"
    subprocess.run([K.FFMPEG, *C.source_args(doc, str(src))], check=True, timeout=300)
    keep = "select='between(n,30,39)+between(n,100,104)',setpts=N/30/TB"
    subprocess.run([K.FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-i", str(src), "-an", "-vf", keep, "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-crf", "23", "-r", "30", str(cut)], check=True, timeout=300)
    subprocess.run([K.FFMPEG, *C.band_read_args(str(cut), str(raw))], check=True, timeout=300)
    assert C.read_band(raw.read_bytes()) == C.expected_sources([[30, 40], [100, 105]])


# ---------------------------------------------------------------- the transcripts

def silence_pairs(doc):
    return [(s["start"], s["end"]) for s in C.silences_of(doc)]


@pytest.mark.parametrize("make, seconds, ranges", [(C.real_size_transcript, (185.0, 200.0), (32, 40)), (C.max_transcript, (295.0, 300.0), (60, 80))])
def test_the_real_size_and_the_maximum_transcripts_have_the_shape_the_live_legs_need(make, seconds, ranges):
    doc = make()
    assert seconds[0] <= doc["duration"] <= seconds[1] <= DATA["limits"]["input_seconds_max"]
    edl = C.base_of(doc, DATA)
    assert ranges[0] <= len(edl["kept"]) <= ranges[1]
    assert edl["out_frames"] == sum(b - a for a, b in edl["kept"]) and edl["fps"] == 30
    assert edl["proposals"] == [] and C.retake_proposals(doc, DATA) == []        # a repeat would be cut by V3e and move the ranges
    assert doc["words"][0]["text"] == "Hey," and [s["text"] for s in doc["segments"][:9]] == [t for _, t in K.SENTENCES]
    assert all(6 <= len(s["text"].split()) <= 10 for s in doc["segments"][9:])
    assert make() == doc and C.base_of(make(), DATA) == edl                       # identical over two calls


def test_the_filler_sentences_are_distinct_and_the_pauses_between_them_are_0_9_to_1_6_seconds():
    texts = [t for _, t in K.SENTENCES] + C.FILLER_LONG + C.FILLER_SHORT
    assert len(set(texts)) == len(texts)
    assert min(C.PAUSES) >= 0.9 and max(C.PAUSES) <= 1.6


def test_the_short_case_is_the_first_four_sentences_and_the_hf_post_aligns_to_it_and_to_the_longer_ones():
    assert C.short_transcript() == K.build_transcript(K.SHORT_SENTENCES)
    for doc in (C.short_transcript(), C.real_size_transcript()):
        first = doc["segments"][:4]
        assert [s["text"] for s in first] == [t for _, t in K.SENTENCES[:4]]


def test_a_source_that_names_a_301_second_recording_passes_the_edit_list_check():
    """`check_edl` reads no duration bound: the long-input leg's refusal comes from the recording check, which is what the leg is for."""
    edl = copy.deepcopy(C.base_of(C.short_transcript(), DATA))
    edl["source"].update(duration=301.0, sha256="d" * 64, has_audio=True)
    _edl.check_edl(edl, DATA, VOCAB, {"fixture-800": {"id": "fixture-800"}})
    assert edl["source"]["duration"] > DATA["limits"]["input_seconds_max"]


def test_the_plain_post_has_four_beats_and_no_overlay_preset():
    assert "preset:" not in C.PLAIN_POST and C.PLAIN_POST.count("beat: ") == 4
    assert [line.split(": ", 1)[1] for line in C.PLAIN_POST.splitlines() if line.startswith("line: ")] == [t for _, t in K.SENTENCES[:4]]


# ---------------------------------------------------------------- the planted blocks

def tree(folder) -> dict:
    folder = Path(folder)
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in sorted(folder.rglob("*")) if p.is_file()}


@pytest.mark.parametrize("which", ["cover", "low"])
def test_a_planted_renderat_folder_differs_from_the_plain_compose_folder_by_one_file_and_its_pins_verify(tmp_path, which):
    plain = tmp_path / "plain"
    __import__("shutil").copytree(K.BLOCKS, plain)
    K.write_hf_compose_blocks(plain)
    folder = C.planted_renderat(tmp_path, which)
    a, b = tree(plain), tree(folder)
    assert set(a) == set(b)
    changed = sorted(k for k in a if a[k] != b[k])
    assert changed == sorted([C.PLANTS[which][0], "pins.json"]), changed
    catalogue = _blocks.load_catalogue(str(folder))                    # every hash checked
    assert catalogue["sha256"] == C.pins_sha256(folder)
    assert catalogue["engines"]["hyperframes"]["presets"] == dict(K.OH_PRESETS) and catalogue["engines"]["hyperframes"]["runtimes"] == ["renderat"]
    assert C.PLANTS[which][2].strip() in b[C.PLANTS[which][0]].decode()
    assert tree(K.BLOCKS)["pins.json"] and C.pins_sha256(K.BLOCKS) == K.BLOCKS_SHA256        # the committed folder is untouched


def test_the_two_plants_edit_two_different_pages_and_the_cover_text_lands_inside_the_face_box():
    assert C.PLANTS["cover"][0] != C.PLANTS["low"][0]
    face = DATA["face_box_default"]
    assert face["y"] < 650 < face["y"] + face["h"]


def test_the_blank_caption_block_is_pinned_set_as_the_captions_of_the_hyperframes_engine_and_draws_words_at_no_size(tmp_path):
    folder = C.planted_blank(tmp_path)
    catalogue = _blocks.load_catalogue(str(folder))
    assert catalogue["engines"]["hyperframes"]["presets"]["caption"] == "hf:demo-blank"
    block = catalogue["blocks"]["hf:demo-blank"]
    assert block["preset"] == "caption" and block["tier"] == "B"
    page = (folder / "hf" / "demo-blank" / "gsap.html").read_text()
    assert "font-size: 0px" in page and "font-size: 48px" not in page and "data.words" in page
    assert not (K.BLOCKS / "hf" / "demo-blank").exists()


# ---------------------------------------------------------------- the memory sampler

def test_a_memory_usage_field_is_read_in_mib():
    assert C.parse_mib("512MiB / 6GiB") == 512.0
    assert C.parse_mib("1.5GiB / 6GiB") == 1536.0
    assert C.parse_mib("1024KiB / 6GiB") == 1.0
    assert C.parse_mib("nonsense") is None and C.parse_mib("12XB / 3") is None


def test_the_largest_usage_of_each_family_is_kept_and_other_containers_are_ignored():
    lines = ["openhora-hyperframes-aaaa 3.1GiB / 6GiB", "openhora-renderer-bbbb 700MiB / 6GiB", "openhora-renderer-cccc 900MiB / 6GiB",
             "someone-else 9GiB / 10GiB", "openhora-renderer-dddd garbage"]
    assert C.read_stats(lines) == {"hf": 3.1 * 1024, "common": 900.0}
    assert C.read_stats([]) == {"hf": None, "common": None}


class FakeDocker:
    def __init__(self, outputs, code=0):
        self.outputs, self.code, self.calls = list(outputs), code, []

    def __call__(self, argv, **kwargs):
        self.calls.append(argv)
        out = self.outputs.pop(0) if self.outputs else ""
        return subprocess.CompletedProcess(argv, self.code, out, "")


def test_the_sampler_keeps_the_maximum_over_its_samples_and_stops():
    fake = FakeDocker(["openhora-hyperframes-a 1GiB / 6GiB\n", "openhora-hyperframes-a 3GiB / 6GiB\nopenhora-renderer-b 800MiB / 6GiB\n",
                       "openhora-hyperframes-a 2GiB / 6GiB\n"])
    sampler = C.Sampler(run=fake, interval=0.01)
    for _ in range(3):
        sampler.sample()
    assert sampler.figures() == {"hf_sampled_max_mib": 3072, "common_sampled_max_mib": 800}
    assert fake.calls[0][:3] == ["docker", "stats", "--no-stream"] and fake.calls[0][-1] == "{{.Name}} {{.MemUsage}}"
    with C.Sampler(run=FakeDocker([]), interval=0.01) as live:
        assert live.started is not None
    assert live.figures() == {"hf_sampled_max_mib": None, "common_sampled_max_mib": None}
    broken = C.Sampler(run=FakeDocker(["x"], code=1))
    broken.sample()
    assert broken.figures()["hf_sampled_max_mib"] is None


def test_oom_events_are_counted_by_docker_events_between_two_instants():
    fake = FakeDocker(["abc\ndef\n\n"])
    assert C.count_oom(fake, 100, 200) == 2
    assert fake.calls[0][:6] == ["docker", "events", "--since", "100", "--until", "200"] and "event=oom" in fake.calls[0]
    assert C.count_oom(FakeDocker([""]), 1, 2) == 0
    with pytest.raises(RuntimeError):
        C.count_oom(FakeDocker([""], code=1), 1, 2)


# ---------------------------------------------------------------- the report

def refuses(doc):
    with pytest.raises(C.ReportError):
        C.check_report(doc)


def test_the_placeholder_of_the_spec_passes_the_schema():
    assert C.check_report(C.placeholder_report())["schema"] == 1


def test_the_schema_refuses_an_unknown_key_at_every_level_and_a_missing_one():
    for path in ((), ("machine",), ("images",), ("cases", 0), ("cases", 0, "same_sha256"), ("cases", 0, "runs", 0)):
        doc = C.placeholder_report()
        node = doc
        for p in path:
            node = node[p]
        node["extra"] = 1
        refuses(doc)
    for path, key in (((), "commit"), (("cases", 0), "words"), (("cases", 0, "runs", 0), "gate")):
        doc = C.placeholder_report()
        node = doc
        for p in path:
            node = node[p]
        del node[key]
        refuses(doc)
    for block, key in (("stage_seconds", "extra"), ("memory", "extra"), ("gate", "extra")):
        doc = C.placeholder_report()
        doc["cases"][0]["runs"][0][block][key] = 1.0
        refuses(doc)


@pytest.mark.parametrize("edit", [
    lambda d: d.update(commit="b" * 39),
    lambda d: d.update(date="2026-1-10"),
    lambda d: d.update(arch="x86"),
    lambda d: d.update(schema=2),
    lambda d: d["images"].update(common="C" * 12),
    lambda d: d.update(hyperframes_version="v0.9"),
    lambda d: d["cases"][0].update(case="huge"),
    lambda d: d["cases"][0]["runs"][0].update(cpuset="0,1"),
    lambda d: d["cases"][0]["runs"][0].update(cpuset="0-3 "),
    lambda d: d["cases"][0]["runs"][0].update(engine="chrome"),
    lambda d: d["cases"][0]["runs"][0].update(outcome="maybe"),
    lambda d: d["cases"][0]["runs"][0].update(sha256="A" * 64),
    lambda d: d["cases"][0]["runs"][0].update(code="Render Timeout"),
    lambda d: d["cases"][0]["runs"][0].update(code="a" * 41),
    lambda d: d["cases"][0]["runs"][0].update(bytes=-1),
    lambda d: d["cases"][0]["runs"][0].update(bytes=True),
    lambda d: d["cases"][0]["runs"][0].update(wall_seconds="12"),
    lambda d: d["cases"][0]["runs"][0].update(frames_ok="yes"),
    lambda d: d["cases"][0]["runs"][0]["memory"].update(oom_events="0"),
    lambda d: d["cases"][0]["runs"][0].update(sha256=None),
    lambda d: d["cases"][0].update(runs=[]),
    lambda d: d.update(cases=[]),
])
def test_the_schema_refuses_a_value_outside_its_type_or_pattern(edit):
    doc = C.placeholder_report()
    edit(doc)
    refuses(doc)


def test_the_schema_refuses_a_path_a_host_name_and_a_free_text_field():
    for key, value in (("code", "/Users/someone/recording"), ("cpuset", "~/x"), ("engine", "../ffmpeg")):
        doc = C.placeholder_report()
        doc["cases"][0]["runs"][0][key] = value
        refuses(doc)
    doc = C.placeholder_report()
    doc["machine"]["host"] = "a-laptop.local"
    refuses(doc)
    doc = C.placeholder_report()
    doc["cases"][0]["note"] = "the speaker says money"
    refuses(doc)
    for text in ("/tmp/x", "a\\b", "x" * 65, "~root"):
        with pytest.raises(C.ReportError):
            C._no_free_text({"k": [text]})
    C._no_free_text({"k": ["short_closed_word", 1, None, True]})


def test_null_stands_for_a_key_an_engine_does_not_have_and_a_refused_run_has_no_figures():
    doc = C.placeholder_report()
    run = doc["cases"][0]["runs"][0]
    run.update(engine="ffmpeg", stage_seconds={"render": 31.5}, memory={"hf_cgroup_peak_mib": None, "hf_sampled_max_mib": None, "common_sampled_max_mib": 800, "oom_events": 0},
               gate=None)
    C.check_report(doc)
    doc["cases"][0]["runs"].append({"engine": "hyperframes", "cpus": 8, "cpuset": "0-7", "outcome": "refused", "code": "render_timeout", "sha256": None, "bytes": None,
                                    "frames_ok": None, "wall_seconds": 1800.2, "stage_seconds": None, "memory": None, "gate": None})
    C.check_report(doc)


def test_rows_built_from_what_a_render_printed_pass_the_schema_and_the_same_sha_is_computed_per_engine():
    hf = {"ok": True, "sha256": "e" * 64, "bytes": 1000, "stage_seconds": {"page": 1.0, "proxy": 2.0, "hf": 3.0, "encode": 4.0, "measure": 0.5, "pixel": 0.25},
          "gate": {"frames": 10, "boxes": 20, "lowest_caption_bottom": 1500.0, "pixel_min_psnr_db": 40.0, "pixel_ranges": 2}, "memory_peak_bytes": 6144 * 1024 * 1024}
    ff = {"ok": True, "sha256": "f" * 64, "bytes": 900, "seconds": {"total": 12.5, "frames": 3.0}}
    mem = {"hf_sampled_max_mib": 3000, "common_sampled_max_mib": 700, "oom_events": 0}
    rows = [C.run_row("hyperframes", 4, "0-3", hf, None, 100.04, mem, True), C.run_row("hyperframes", 8, "0-7", hf, None, 90.0, mem, True),
            C.run_row("ffmpeg", 4, "0-3", ff, None, 12.6, mem, True), C.run_row("ffmpeg", 8, "0-7", dict(ff, sha256="0" * 64), None, 12.0, mem),
            C.run_row("hyperframes", 8, "0-7", None, "render_timeout", 1800.0, None)]
    assert rows[0]["memory"]["hf_cgroup_peak_mib"] == 6144 and rows[2]["stage_seconds"] == {"render": 12.5} and rows[2]["gate"] is None
    assert rows[4]["outcome"] == "refused" and rows[4]["code"] == "render_timeout" and rows[4]["sha256"] is None
    edl = C.base_of(C.short_transcript(), DATA)
    case = C.case_row("short", C.short_transcript(), edl, rows[:4])
    assert case["same_sha256"] == {"ffmpeg": False, "hyperframes": True}
    doc = C.placeholder_report()
    doc["cases"] = [case, C.case_row("max", C.short_transcript(), edl, rows[4:])]
    C.check_report(doc)
    assert doc["cases"][1]["same_sha256"] == {"ffmpeg": None, "hyperframes": None}


def test_every_committed_report_passes_the_schema_and_its_name_says_its_date_and_architecture():
    for path in sorted(REPORTS.glob("*")) if REPORTS.is_dir() else []:
        m = C.REPORT_NAME.fullmatch(path.name)
        assert m, "%s is not named engine-contract-<date>-<arch>.json" % path.name
        doc = C.check_report(json.loads(path.read_text(encoding="utf-8")))
        assert (doc["date"], doc["arch"]) == m.groups(), path.name


# ---------------------------------------------------------------- the live file

def test_the_live_file_lists_both_engines_for_the_functional_legs_and_only_hyperframes_for_the_blank_caption():
    import test_engine_contract_live as live
    legs = live.LIVE_LEGS
    for name in ("F1", "F2", "F3", "F5", "F6", "F7"):
        assert legs[name] == ("ffmpeg", "hyperframes"), name
    assert legs["F8"] == ("hyperframes",)
    for name in ("M1", "M2"):
        assert legs[name] == ("ffmpeg", "hyperframes"), name
    assert legs["M3"] == ("hyperframes",)
    assert "F4" in legs
    tests = sorted(n for n in dir(live) if n.startswith("test_"))
    assert [n for n in tests if n.startswith("test_mac_")], "the machine legs are named test_mac_*"
    assert not [n for n in tests if "mac" in n and not n.startswith("test_mac_")]


def test_the_live_file_never_builds_an_image_and_names_no_real_recording():
    text = (K.HERE / "test_engine_contract_live.py").read_text(encoding="utf-8")
    assert not re.search(r"\"build\"|'build'|--confirmed|docker\", \"pull|docker\", \"build", text)
    assert "/Users/" not in text and "Library/" not in text


# ---------------------------------------------------------------- the frame comparison

def edl_of(kept, mode="alternate", push_in=0.02):
    return {"fps": 30, "kept": kept, "zoom": {"mode": mode, "factor": 1.1, "push_in": push_in, "anchor_y": 0.25}}


def test_the_comparison_is_exact_and_says_how_many_frames_are_wrong_and_by_how_much():
    edl = edl_of([[0, 4], [10, 13]], mode="none", push_in=0)
    good = C.expected_sources(edl["kept"])
    assert C.compare_frames(edl, good) == {"checked": 7, "bad": 0, "largest_offset": 0, "first_bad": None, "frames": 7}
    off = list(good)
    off[4] = 11                                                     # the first frame of the second range is the next source frame
    off[6] = 20
    assert C.compare_frames(edl, off) == {"checked": 7, "bad": 2, "largest_offset": 8, "first_bad": 4, "frames": 7}
    short = C.compare_frames(edl, good[:5])
    assert short["bad"] == 2 and short["frames"] == 5 and short["first_bad"] == 5


def test_a_zoomed_range_is_skipped_only_when_asked_and_a_push_in_counts_as_zoom():
    edl = edl_of([[0, 4], [10, 13], [20, 24]])                      # alternate: the second range is drawn at 1.1
    assert C.unzoomed_ranges(edl) == [0, 2]
    scrambled = C.expected_sources(edl["kept"])
    scrambled[4:7] = [99, 99, 99]
    assert C.compare_frames(edl, scrambled)["bad"] == 3
    only = C.compare_frames(edl, scrambled, only_unzoomed=True)
    assert only["bad"] == 0 and only["checked"] == 8
    pushed = edl_of([[0, 200]], mode="none", push_in=0.02)           # 6.7 s: a push-in from 5 s on
    assert C.unzoomed_ranges(pushed) == [] and C.unzoomed_ranges(edl_of([[0, 200]], mode="none", push_in=0)) == [0]
