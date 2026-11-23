## 2026-11-23: a picture whose beat the timeline dropped no longer refuses the whole render (V9b-3d; spec `SPEC-video-V9b-3d-dropped-beat-picture-2026-11-23`)

**The defect (found in the live leg of V9b-3c, present before it).** `_edl.resolve_timeline` has one beat track: overlays and layouts together are sorted by `(start_frame, end_frame)`, the earlier of two
that overlap ends where the later starts, and one left with no frame is dropped (`timeline["dropped"]`). Of two beats that start on the same word the shorter sorts first and is cut to nothing. The
runtime hands over the approved picture of every layout slot `beats.json` lists (it does not resolve the timeline), so a layout the timeline dropped had its picture handed over, and both engines refused
the whole render with `asset_unused` (ffmpeg `_render.py`, HyperFrames `_hf_compose.draw_plan`), which the runtime reports as `engine_refused` on `media`. Live case, in one line: a picture layout and a text
overlay on the same first word, the layout the shorter; the task failed, no data of it is kept here.

**What changed.** A handed-over slot is classified against `beats.json`, not only against the kept beats (`_edl.classify_slots`, shared by both engines and by both host files):

| Slot | Before | After |
|------|--------|-------|
| used by a kept beat | drawn | drawn |
| used by no beat of `beats.json` | `asset_unused` | `asset_unused` |
| used only by beats the timeline dropped | `asset_unused` | not read, not staged, not drawn; listed in the answer's `assets_dropped` |
| used by a kept beat but given no file | `asset_missing` | `asset_missing` |

- **Answer field.** `render` on both engines carries `assets_dropped: [<slot>, ...]`, sorted, only when non-empty (a dry run too); `hf-page` carries it when the composed page left a slot out. The result schemas of
  `_docker.py` list it (`opt(lst(S, 36))`): `sanitise` keeps only listed keys, so without the line the field would have been dropped silently. The id of the dropped beat stays in `beats_dropped` (ffmpeg).
- **The host does not stage it.** `_host.dropped_asset_slots` resolves the timeline from the same three documents the render reads, before a file is read or copied: `ffmpeg.py` stages no file of a dropped slot into
  the job folder, `hyperframes.py` neither reads, hashes, stages nor puts it in the project's `assets/`, and its `--asset-sha256` is accepted and ignored. A document the host cannot read or resolve gives no
  dropped slot, so the container reads and refuses it itself with its own reason, as before. The host's list and the container's are merged in the answer.
- **The runtime.** `step_media._render` reads `assets_dropped`: a list of strings, each a slot this call handed over and none twice, else `provider_output_invalid` on `render`. Those slots leave `pictures` before
  `render.json` is written, so the record's `assets` (the delivery's assets and credits) lists only what was drawn, and has no key when none was. The step result's `pictures` counts the drawn ones and
  `pictures_dropped: [<slot>, ...]` lists the others, beside `effects_dropped`. `_used_slots` and `_drawn_pictures` are unchanged: the renderer is the one that knows the timeline.
- **How the person is told.** `effects_dropped` reaches the person nowhere but the step result (no phrase, no page and no card reads it); `pictures_dropped` is shown the same way and no phrase pair is added.

**What did not change.** The editing rule of the timeline: which beat wins a tie on the same word is a product question left open (today the shorter loses, whatever its kind; a rule that an approved picture layout
wins over an overlay is the maintainer's to decide). `asset_unused` for a slot no beat uses at all, `asset_missing` for a kept slot with no file, and `hyperframes.py`'s refusal of any file given to a base-only render.

**Verified.** Offline, `providers/renderer/tests/test_dropped_beat_picture.py` (the timeline drops the shorter beat; both engines' composes and the ffmpeg dry run list the slot and read no file; the live shape of the
defect; the refusals unchanged; the schema keeps a list and refuses anything else), `test_renderer_docker.py` and `test_hf_engine.py` (each host stages nothing of a dropped slot and lists it) and
`runtime/tests/test_step_media_assets.py` (the record and the step result, and the invalid answers). **Not verified:** a K4-style render of a real recording with the live engines, which the supervisor runs.
