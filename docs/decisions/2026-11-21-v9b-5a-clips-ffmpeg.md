## 2026-11-21: clips on the ffmpeg engine: `asset-sheet` takes clips, and the compose draws a clip under an `oh:cutaway` entry (V9b-5a; spec `SPEC-video-V9b`, the amendment "V9b-5a specified" of 2026-11-21)

**What was decided and built.**

- **`asset-sheet` takes clips**, in both modes, beside pictures (`providers/renderer/_asset_sheet.py`, in the common image).
  - A clip is an MP4 or MOV (an `ftyp` box first) or a WebM (an EBML header), told by its first bytes, never by a name. The demuxer is forced (`mov` with
    `-enable_drefs 0`, or `matroska`), with `-protocol_whitelist file` and the decoder forced too. Only the first video stream is read: audio, subtitle and
    data streams are not mapped, metadata and chapters are dropped.
  - Decoders: h264, hevc, vp8, vp9, and av1 only when the image's ffmpeg has a software decoder for it. The list is read at run time from `ffmpeg -decoders`
    (`libdav1d` or `libaom-av1`), never assumed; the native `av1` decoder needs a hardware accelerator and does not count. With none, av1 is `asset_type`.
  - Limits: the byte cap, at most 7680x4320 (either way up), the first 10 seconds (a longer clip is cut, not refused).
  - `preview`: the tile is the clip's frame at 0.5 s (its first frame when shorter), with a small solid accent-coloured marker in the tile's corner.
  - `full`: H.264 High, yuv420p, bt709 tagged, a constant `--fps N` (new optional flag, 24 to 60, default 30), no audio, the size rule below (each side made even), the `lanczos+accurate_rnd+bitexact` scaler, x264 on one thread (decoder and filter graph too), faststart, written
    as `asset-<sha12>.mp4` (0400). The rows gain `kind` and `seconds`.
- **The ffmpeg engine draws a clip under an `oh:cutaway` entry** (`_media.clip_filters`, `_render.load_clips`, `_render.settle_clips`, `_render.clip_rows`).
  - The clip is loaded with the checks of the `full` output (H.264, yuv420p, one stream, a constant rate from 24 to 60, within the caps, at most ten seconds,
    its sha256 matched when given). It is never served to a page.
  - The compose draws it under the beat layer, over the speaker, on the entry's frames only: conformed to the output rate with `fps=`, playing from the entry's
    first frame, its last frame held to the entry's end. It is one stream the whole length of the output, transparent outside the entry (the pip's pattern, so no
    `enable` expression is used). The heavy filters (the blur, the scales) run on the entry's own frames, before the stream is padded to the length of the output.
  - `fit: cover` and a ratio at or under `glass_ratio_max`: scaled to cover 1080x1920, centred. Otherwise the glass, from the same look values: a cover copy
    blurred (`gblur`, sigma = `glass_blur_px` = the page's CSS blur deviation, 3 passes), a tint of the clip's first-frame predominant colour at
    `glass_tint_alpha` (the page's `predominant` rule ported to the host and tested), a shadow (the page's 0.45 / 48 / offset 12; a canvas blurs a shadow with half
    its `shadowBlur`, so sigma 24), and the clip whole within `SAFE` = 65 and `MAX_FG_H` = 1700 with the radius mask (the pip's `geq` pattern).
  - The page is told the asset is a clip with `data.params_kind = {"asset": "clip"}` (no such key existed; it is set on the entry by `settle_clips` and passed by
    `draw_frames`) and draws only the label chip on a transparent stage; `window.__imgs` holds nothing for a clip slot. `blocks/oh/cutaway/renderat.html` changed
    for that, so `pins.json` and `catalogue.json` changed through `pin-blocks --confirmed` (the `renderat.html` hash and `blocks_sha256`; nothing else).
  - The gate: the page reports the same boxes for a clip cutaway as for an image cutaway (none), so a clip frame is judged exactly as an image cutaway frame;
    the face rules of every card and caption are unchanged. The ffmpeg engine has no pixel check, so there is nothing that could not see the composed clip.
- **`asset_kinds` stays `["image"]`** in `blocks/engines/ffmpeg.json` (and in `hyperframes.json`).
  - The saving: no change in this part can reach the runtime. Its fetch, store and sheet route have not been taught to handle an `.mp4`, and the runtime keeps
    refusing a clip pick with `clip_not_drawn`. `catalogue.json` and `pins.json` change only through `pin-blocks --confirmed`.
  - The loss: no person can pick a clip until a later small runtime package flips it, after V9b-3a and this package have merged. The clip is reachable only by the
    renderer's own verbs (the live leg, C10).
- **The `cut`-only rule.** A clip cutaway draws the `cut` transition only (the default since V9d); a theme whose cutaway look is `slide` or `zoom` is refused
  `clip_transition` for a clip entry. The loss: those themes cannot use clips yet. A picture keeps both. Only `oh:cutaway` draws a clip: `oh:screenshot`, `oh:pip`
  and any other block with a clip slot are `asset_type` naming the slot.

- **The size rule of `asset-sheet` full mode, for images and clips** (the supervisor's correction after live leg K3; it replaces V9b-2's reading "long side to
  1920, at most 1.5 times"). K3: Openverse returned a CC BY 2.0 picture of 1024x683, the medium rendition Flickr serves and typical of Openverse; the old rule scaled it
  1.875x and refused it `asset_too_small`, so nearly every Openverse picture would be refused, although a landscape picture is drawn in the glass layout at no more than
  950x1700 (`SAFE` = 65, `MAX_FG_H` = 1700), here 0.93x. The rule: (1) never enlarge: a long side over 1920 is scaled down to 1920 with the aspect kept, otherwise the picture
  keeps its size; (2) `asset_too_small` only when the picture would be drawn more than 1.5 times its own size in the layout its ratio selects with the default look: ratio
  (w/h) at or under 0.8 the cover layout, refuse when `max(1080/w, 1920/h) > 1.5`; otherwise the glass layout, refuse when `min((1080 - 2*65)/w, 1700/h) > 1.5`; (3) the figures
  are named constants in `_asset_sheet.py`, and a test reads `SAFE`, `MAX_FG_H` from `renderat.html` and `glass_ratio_max` from the cutaway look. **The loss:** a theme whose
  `glass_ratio_max` differs, or a `fit` that forces cover on a landscape picture, can draw a picture enlarged more than 1.5 times.

**The image tag changed.** The common image's tag was `openhora-renderer:8206b171b52b` (V9b-2) and is `openhora-renderer:640490c4a634` (`_asset_sheet.py`, `_assets.py`,
`_frames.py`, `_inner.py`, `_media.py` and `_render.py` are in the image). The HyperFrames image's tag is unchanged (`openhora-hyperframes:12ff7f4128cb`); no file of it
changed. No test holds the common image's tag. The common image must be rebuilt before a live render (the maintainer's, STOP 5).

**Readings of the spec.**

- A clip is `asset_type` for every "not the normalised form" case at render (audio, another codec, a variable rate, over ten seconds, another container,
  rotation), so no new code is invented. New closed codes: `clip_transition` and `bad_fps` (the spec names the first; the second is `--fps` out of 24 to 60).
- A WebM or MP4 that declares no duration (some recorders write none) is `asset_corrupt`, rather than decoded to be measured.
- A file ffmpeg reads to its end with no decode error but that comes out shorter than it says (a cut-short MP4) is `asset_corrupt`: the output's length is
  compared with the input's declared one (a quarter of a second, or two frames, of room).
- crf 16 for the normalised clip (the spec does not say); the render's own encode (crf 18) reads it again.
- An output over the byte cap is `asset_dimensions`; the input's colour matrix is bt709 when it says so or says nothing and the clip is high definition, else
  the one it is tagged with.
- The tile's marker is a solid box in the accent colour, not a drawn word or glyph: a drawn glyph needs a font the image may not have.
- The glass looks come from `data["presets"]["cutaway"]["looks"]` as the page's payload does; a look with no `glass_blur_px` draws the clip as cover. The page would
  letterbox a `fit: contain` picture there; the compose does not, since no preset lacks the glass look and a letterbox on the theme's background is a layout the spec
  does not ask for.
- The 7680x4320 caps and the 10 seconds are constants in `_media.py` (`renderer-presets.json` is in the image's manifest and not in this package's row).
- **The result schema is in `_docker.py`, not `_host.py`** (stop rule 3, see the pull request): `kind` and `seconds` are validated by the host when present and are
  dropped by `D.sanitise` until the schema line (`_docker.py` 549) is changed by a package whose row has it. The host verb works with and without them.

**Verified (offline, on the host's ffmpeg 9.0.2, a headless Chromium and synthetic clips).** `asset-sheet` in both modes (the pinned form, the same bytes twice, the
first-video-stream-only rule with audio, two video streams and a data stream, av1 following the decoder list, the 10-second cut, the 1.5 and 1.6 times upscale,
the tile and its marker, `bad_fps`, the refusals from fake ffprobe facts); the compose graph for cover and glass (goldens), frame for frame on a counter clip (the
first frame, the held last frame, a clip shorter and longer than the entry, a 24 fps clip in a 30 fps output, transparent outside the entry), the same bytes twice;
the page (an image cutaway's frame bytes equal to the page of V9b-2 on five frames, a clip draws only the chip, a page that drew a clip draws a picture afterwards
as a fresh page does); whole renders of a generated recording with a cover clip and a glass clip (frame-exact, the same bytes with 1 and 2 workers), and the
refusals (`asset_type` on the pip and on `oh:screenshot`, `asset_hash`, `clip_transition`).

**Not verified.**

- The image rebuild and anything run inside it: the image's own ffmpeg (Debian bookworm's package, a different version from the host's), including whether it has a
  software av1 decoder (`libdav1d` or `libaom-av1`; the code reads the list at run time, and nothing here could read the image's build), and whether its `gblur`,
  `geq`, `tpad` and `alphamerge` behave as on the host's 9.0.2.
- The same bytes at 4 and 8 cores (the supervisor's live leg, `test_engine_contract_live.py`); the argv pins one thread for the normaliser and the same four slice
  threads as the rest of the compose.
- C10 of the clip cutaway (cover and glass, five frames inside the beat), on synthetic clips; and any clip that is not synthetic.
- **Byte determinism of the compose's final encode.** The filter graph is deterministic (its raw output has one hash over repeated runs, tested). On the host's ffmpeg
  9.0.2 the pinned four-slice-thread x264 gave different bytes for one identical raw input on moving content (6 runs, 6 hashes; one thread: 1 hash), while a
  flat plain compose is stable. This is the encoder's pinned setting, not this package; whether the image's x264 does it is the live leg's question (`F9`, `M4`). The tests
  therefore compare the graph's frames, not the mp4's bytes, for a clip render.
- The time of a glass clip's compose: measured on the host at about 0.5 s per entry frame, on four filter threads; the image's figure is not known.
- The HyperFrames engine draws no clip (V9b-5b).
