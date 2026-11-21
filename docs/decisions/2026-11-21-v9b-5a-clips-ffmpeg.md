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

- **The size rule of `asset-sheet` full mode, for images and clips** (the supervisor's rule after live leg K3 and the review of #821; it replaces V9b-2's reading "long side to
  1920, at most 1.5 times" and the first wording given to this package). K3: Openverse returned a CC BY 2.0 picture of 1024x683, the medium rendition Flickr serves and typical of
  Openverse; the old rule scaled it 1.875x and refused it `asset_too_small`, although a landscape picture is drawn in the glass layout at no more than 950x1700 (`SAFE` = 65,
  `MAX_FG_H` = 1700), here 0.93x. The rule, quoted: the display need `d` of the source, at ratio at or under 0.8 (cover) `max(1080/w, 1920/h)`, otherwise (glass)
  `min((1080 - 2*65)/w, 1700/h)`; refused `asset_too_small` when `d > 1.5`, judged on the source; the output scale is `s = min(1, max(1920 / max(w, h), d))`, the output long side
  capped at 3840; it never enlarges and shrinks only as far as the drawing still needs (1024x683 stays, 4000x3000 becomes 1920x1440, 800x2400 and 1080x2400 stay, 1080x5000 becomes
  829x3840); at render a clip with a side over 3840 is `asset_type`. The figures are named constants in `_asset_sheet.py`, and a test reads `SAFE`, `MAX_FG_H` from `renderat.html`
  and `glass_ratio_max` from the cutaway look. **The loss:** a theme whose `glass_ratio_max` differs, or a `fit` that forces cover on a landscape picture, can draw a picture
  enlarged more than 1.5 times.
- **Changes after the review of #821 at c8911fa.**
  - Two tests outside the new files were changed, with the supervisor's word: `test_renderer_blocks.py` `OLD_PINS["cutaway"]` (the whole-file hash of the cutaway page moved, since the
    page has a clip branch) and `test_the_cutaway_page_the_screenshot_page_follows_...`, reworded to compare the drawing code an image goes through (from `const img = ...` to the
    opacity line) with the V9b-2 page's, line for line and indentation aside. The proof that an image cutaway is unchanged is `test_clip_cutaway.py`'s golden-frames test, which draws
    both pages on the same pictures and times and finds the same frame bytes.
  - A codec whitelist and `-max_pixels 33177600` on every clip input. The forced software decoder is the whitelist of the normaliser, the frame grab and the compose; ffprobe opens a
    decoder for every stream, so its whitelist is the video decoders plus a fixed list of audio and subtitle decoders (`_media.PROBE_OTHER_DECODERS`), and an input with another audio
    codec is `asset_type`: this goes a little beyond "the allowed video decoders" and keeps clips with ordinary audio acceptable (the audio is dropped).
  - At probe: a frame rate over 120, or more than 1200 frames in the first 10 s, is `asset_type`; the video stream's own duration is used (the container's only when the stream has none).
  - A glass clip with no predominant colour is tinted with the theme's background colour, as the page does. The page reports the glass box of a clip as `window.__box`.
  - Only the `ftyp` brands of an MP4 or MOV (isom, iso2-iso6, mp41, mp42, avc1, M4V, qt) and the EBML doctypes webm and matroska are clips.
  - The host checks every row's `kind` against the input's own first bytes, an image row's `seconds` is 0, a clip's is over 0 and at most 10.1.
  - `clip_no_frames` is the closed refusal of an entry with no frame; a decoder missing from the image's list is `asset_type`; `software_decoders` skips the legend lines.
  - The live case `test_mac_m5` of `test_engine_contract_live.py`: a normalised synthetic moving clip in a cover and a glass cutaway on the ffmpeg engine, one sha256 at 4 and 8 cores.
  - The claim "the same bytes with 1 and 2 workers" is removed: it was never proved (see the finding on x264 below).

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
- **The result schema is in `_docker.py`, not `_host.py`** (stop rule 3, cleared by the supervisor): the row was widened by exactly one change, `kind=S, seconds=N` on the row dict of `RESULT_SCHEMAS["asset-sheet"]`. A host-side test proves `D.sanitise` keeps both.

**Verified (offline, on the host's ffmpeg 9.0.2, a headless Chromium and synthetic clips).** `asset-sheet` in both modes (the pinned form, the same bytes twice, the
first-video-stream-only rule with audio, two video streams and a data stream, av1 following the decoder list, the 10-second cut, the 1.5 and 1.6 times upscale,
the tile and its marker, `bad_fps`, the refusals from fake ffprobe facts); the compose graph for cover and glass (goldens), frame for frame on a counter clip (the
first frame, the held last frame, a clip shorter and longer than the entry, a 24 fps clip in a 30 fps output, transparent outside the entry), the same bytes twice;
the page (an image cutaway's frame bytes equal to the page of V9b-2 on five frames, a clip draws only the chip, a page that drew a clip draws a picture afterwards
as a fresh page does); whole renders of a generated recording with a cover clip and a glass clip (frame-exact), and the
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
