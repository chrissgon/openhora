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

## K4 fix: a web clip with no thumbnail

**Cause.** `_preview` of the web search took `thumb_url` or else `media_url` and always called the open-web provider's `preview` verb with `--kind image`. That verb accepts only PNG or JPEG, so the `.mp4` of a clip row with no
thumbnail was refused (`type_refused`, dropped as `preview`). The skill writes `thumb_url` only when the page shows a small version, so in the live run on 2026-11-23 both clip rows (an `.mp4` on a CDN host) were dropped, the slot
ended with 0 candidates, and the fetch then stopped (the pick defect, decision A1 of the V9b-3b decision file). The recorded design already said what to do: V9b spec 7.5 ("a clip with no thumbnail has no preview; its tile says so,
and it can still be picked"), its caps table, and `providers/stock/README.md`.

**Options (principle 13).**
1. Fetch the whole clip at search time under the clip cap (64 MiB) and let `asset-sheet` draw its frame. Saves: the person sees a frame before picking. Costs: up to 6 x 64 MiB per search from unchecked hosts for clips nobody
   picked, minutes of wall time, and it changes D9 step 1. Not chosen.
2. A provider `preview --kind clip` verb with a small cap. A byte-capped prefix of an MP4 is usually not a readable file (the `moov` box is often at the end), so most clips would drop, and it is a provider change. Rejected.
3. Require `thumb_url` for clip rows in the skill and its checker. A skill change (bump, partial and guard lab runs) that drops real clips whose page shows no small version. Rejected.
4. **Chosen, decision B1: the recorded rule.** A clip row with no `thumb_url` becomes a candidate with no preview: no provider call at search time, an empty cell at its column on the preview sheet (so "Picture N" is still
   the tile in column N), a line on the page that says so, and it can be picked. `fetch-picks` fetches it by the existing path, and its frame is on `sheet.png` before the set is approved, so nothing reaches a render that the
   person did not see and approve. Saves every byte of option 1 and keeps D9. Loses the frame before the pick: one wasted clip fetch, at most 64 MiB, when the person picks one and then rejects it. No skill, provider,
   renderer, fingerprinted file or image changes.

**How.** `_preview` returns the candidate at once for a clip row with no thumbnail; its item is `u-` and the first 12 hex digits of the sha256 of the link, so the link is named nowhere and one link always gives one pick.
`_record` builds the candidate for both paths. `_previewless` marks such a candidate (a clip of the open web with `preview`, `preview_in` and `preview_sha256` all null). `_compose` keeps and prunes only files that exist
and draws the sheet only when some candidate has a preview; `_preview_sheet` leaves a previewless candidate out and keeps the column of the others; `_carried` carries one, with the same words, with no file check.
`webLines` of the page's model adds `NO_PREVIEW_LINE` when the answer says `preview: false`.

**Tests** (offline): `test_a_web_clip_with_no_thumbnail_is_kept_with_no_preview_and_no_provider_call` (the live failure), `test_a_previewless_clip_keeps_the_column_of_the_others`,
`test_a_search_whose_candidates_all_lack_a_preview_draws_no_sheet`, `test_a_find_after_a_web_search_carries_a_previewless_clip_with_the_same_words_and_drops_it_when_they_change`,
`test_a_previewless_web_clip_can_be_picked_fetched_and_approved`, and the page model's `test_a_web_clip_with_no_preview_says_so_on_its_tile_and_one_with_a_preview_does_not`.
**Not verified.** How the page lays out a sheet with an empty cell (the renderer draws a missing cell as an empty tile, read in `_asset_sheet.py`); the live re-run of K4.

## L3 and C10 (2026-11-23)

**L3, the live leg.** The same complete run as in "K4, the live leg" of the V9b-3b decision file, made on the code of this pull request at 02904ef. One real web clip: 1080x1920, 8.033 s, `clip_fps` 30, kept with no preview
by the fix above, fetched, its own approval shown `sheet.png`, and drawn on both engines. The clip cutaway entry ran on output frames 98 to 177 (2.63 s) on both engines; it was not shortened, since the clip outlasts
the beat. The frame after the entry is the speaker's on both engines.

**C10 (L4).** A sheet of five frames inside the clip cutaway and the first frame after it, on each engine, was made locally, never committed, and deleted after the answer. The maintainer's answer to the supervisor's
question "Você aprova o C10 do clipe nos dois motores?" (2026-11-23) was: "Aprovo". validate: allow english-only -- the maintainer's own words, quoted
