## 2026-11-23: a picture beat wins over a text overlay that overlaps it (V9b-3e; spec `SPEC-video-V9b-3e-picture-wins-2026-11-23`)

**The old rule.** `_edl.resolve_timeline` keeps one beat track. Overlays and layouts are sorted by `(start_frame, end_frame)`; for each neighbouring pair, when the earlier one ends after the later one
starts, the earlier one ends where the later one starts, and one left with no frame is dropped (`timeline["dropped"]`). So when a picture layout and a text overlay started on the same frame, the shorter was
cut to nothing, whatever its kind (V9b-3d made the picture of such a dropped beat leave the render instead of refusing it, and left open which beat should win).

**The maintainer's choice, 2026-11-23**, asked whether an approved picture and a text overlay that start on the same word should have the picture win or the shorter lose as before:
"A imagem ganha" (Portuguese for "the picture wins"). validate: allow english-only -- the maintainer's own words, quoted

**The new rule.** A picture beat is a beat of `beats["layouts"]` whose preset has at least one asset slot parameter present in its params (`_vocab.slot_params`, the test `_edl.classify_slots` uses). Every
other beat (every overlay, a layout with no slot) is a text beat. Before the existing neighbour pass, a picture keeps its own range against every text beat it overlaps, and the text beat yields:

- it starts before the picture: it ends where the picture starts (as before);
- it starts at or after the picture's start and before its end: it starts where the picture ends, keeping its own end, marked `clipped`;
- no frame is left: it is dropped, listed in `timeline["dropped"]` and with a row `{id, reason: "under_picture"}` in `timeline["dropped_reasons"]` (the list `_layout.py` fills with `pip_no_room`; the
  answer's `beats_dropped_reasons` schema is unchanged, the row has the same shape);
- it overlaps more than one picture, or spans one: one range per beat, so it keeps the part before the first picture or the part after the last, whichever is longer (the earlier on a tie).

Then the existing pass runs unchanged on the result: picture against picture and text against text, as before (two pictures that start together: the shorter is dropped and its slot is `assets_dropped`).

**Minimum length (added in review, supersedes the first spec's "no new minimum").** A text beat the picture pass shortens must keep at least its preset's `min_duration`, in frames (`int(round(min_duration * fps))`, at least 1). When the side it keeps is shorter, it is dropped with `under_picture`, like one wholly under a picture. Why: on the live K4 shape overlay b1 was left with 2 frames (68-70) after picture a1 pushed its start, a 67 ms flash that no one can read. The minimum applies only in the picture pass; the neighbour pass (text against text, picture against picture) is unchanged.

**What did not change.** Captions, punches, grades, the pip room (`_layout.py`), the V9b-3d handling of a dropped picture (still possible when two pictures collide) and the runtime. `resolve_timeline` is shared:
both engines, the preview, the host's dropped-slot check and the asset-sheet path all call it, so each agrees with the render.

**Verified.** Offline, `providers/renderer/tests/test_picture_wins.py` (the live shape: a3 drawn on its own range, b4 starting at its end, b1 and b2 dropped `under_picture` for lack of their minimum, the ffmpeg dry run with no `assets_dropped`; the minimum, exact and one frame short, and no kept text beat on the live shape below its preset minimum;
a text beat before, inside and spanning a picture; two pictures; two text beats; a layout with no slot; the HyperFrames compose) and `test_dropped_beat_picture.py`, whose fixture now makes the dropped beat
a picture that loses to a longer picture, since a text overlay no longer causes a picture's drop. **Not verified:** a live render of a real recording with the engines, which the supervisor runs.
