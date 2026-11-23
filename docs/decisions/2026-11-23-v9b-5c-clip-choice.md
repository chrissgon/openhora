## 2026-11-23: a person can pick a clip for a cutaway (V9b-5c; spec `SPEC-video-V9b-5c-clip-choice-2026-11-22`)

**What was built.** Both engine files list `"asset_kinds": ["image", "clip"]` (`pin-blocks --confirmed`; the two engine hashes of `pins.json` and `asset_kinds_by_engine` of
`catalogue.json` change, nothing else). Neither image manifest lists `blocks/`, so no image tag changes. The runtime then reads a clip pick through the same path as a picture:
`fetch-picks` passes the edit list's rate to `asset-sheet`, adopts `asset-<sha12>.mp4`, checks its row (`kind` clip, `0 < seconds <= 10.1`), refuses a clip shorter than 1.5 s plus three
frames, and the align step ends a clip cutaway with its clip. Stacked on #824 (V9b-3b), which brings the open web as a source of clips.

**Decisions, each by recommendation, with what it saves and what it loses.**

- **D1, the flip.** Two lines in two files plus the pins. Saves an image rebuild and a lab battery (no skill or eval case reads the catalogue). Loses nothing the tests do not show.
- **D2, open-web clips are in scope** (OPEN-1, **answered by the maintainer in his own words: "Web aberta"**). Saves a later package and a key: the web source is the only one without a key that
  serves clips. Loses: a web clip carries the web tier's copyright risk, with the same warning and own approval as a picture, and this package waits for #824's merge.
- **D3, the rate is passed and checked once.** `fetch-picks` reads `fps` from `proposal.edl.json` (an int from 24 to 60), passes `--fps`, writes `clip_fps` beside the set (outside the hashed
  document); the align step refuses a set whose rate is not the final edit list's (`clip_fps_changed`). Both engines then draw a clip at the rate they share. Saves the ffmpeg
  conforming on one engine and the refusal on the other. Loses one more key in `set.json`.
- **D4, only a cutaway takes a clip**, decided before any fetch (`clip_block`): the catalogue gives `oh:cutaway`, `oh:screenshot` and `oh:pip` the same `asset` list, so only the block can tell them
  apart. Saves a download for a clip the renderer would refuse. Loses a copy of one block name in the runtime (`CLIP_BLOCK`), which a test reads from `_render.py`.
- **D5, the trim lives in the runtime** (OPEN-2, ruled by recommendation). `step_media.fit_clip_entries` lowers `word_to` so the beat fits the clip with two frames to spare. Saves a renderer edit and
  an image rebuild; both engines meet only inputs they draw alike. Loses three numbers copied from the renderer (`tail`, `min_duration`, `max_duration` of `cutaway`) and the timeline's
  arithmetic; a test compares the numbers and a seeded sweep (360 cases, five frame rates) runs the renderer's own `resolve_timeline`, the HyperFrames check and the ffmpeg clip rows on what
  the runtime wrote.
- **D6, sizes.** A clip is fetched with a cap of 64 MiB, the renderer's own staging cap, so a file the renderer would refuse is never downloaded; a clip shorter than 1.5 s plus 3/fps is refused after the
  sheet and the set goes back to its candidates.
- **D7, what the person sees.** The `fetch-picks` answer for a clip adds the trim phrase and each asset's `seconds`; the page shows only the set's sheet for a clip (`file` is null); `approve-asset` of a web clip
  shows `sheet.png` (OPEN-3, ruled by recommendation). The step's align result counts `clips` and `clips_shortened` only when a clip is drawn. A beat whose first word is longer than its clip fails the step with
  `clip_too_short` (OPEN-4, ruled by recommendation). The phone card still says "Picture" for a clip (OPEN-5, ruled by recommendation).
- **D8, stacked on #824.** The flip itself breaks three of #824's tests and both packages edit `fetch-picks`; building on main would reopen #824 after its review.

**Assertions that changed on purpose, and only these.** `providers/renderer/tests/test_renderer_blocks.py` (the two asset-kind lists of the shipped engines), `runtime/tests/test_media_animation.py`
(the same two lists), `runtime/tests/test_media_stock.py` (the refusal on an engine that draws no clips now monkeypatches `asset_kinds` to `["image"]`; the renderer-row test is renamed, same assertions; the list), and
#824's `test_media_websearch.py` (two tests) and `test_media_approve_asset.py` (one test), by the same monkeypatch.

**Departure from the spec (supervisor's ruling).** `runtime/tests/test_stock_licences_equal.py` compared `KIND_BYTES` with the provider's caps (clip 120 MiB); it now compares the clip cap with the renderer's `limits.asset_max_bytes` and requires it to be at or below the provider's cap. The spec's 3.2 missed this test; the provider files are untouched.

**Not verified offline.** That the runtime's engine call reaches the built images from a pytest (the live leg L1, `runtime/tests/test_media_clip_live.py`, skipped without its three variables), how long `asset-sheet` takes
on several 10 s clips against its 300 s limit, the decoded frame count of a normalised clip against `round(seconds * fps)` (the two spare frames cover one off), how often a web search returns a direct clip
link with a thumbnail, every figure of the live legs, and the maintainer's C10 quote (L4), which goes here when given.
