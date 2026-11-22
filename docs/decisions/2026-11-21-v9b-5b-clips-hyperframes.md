## 2026-11-21: clips on the HyperFrames engine, Design B: a clip is a top-level video element of the composed page (V9b-5b; spec `SPEC-video-V9b`, the amendment "V9b-5b specified" of 2026-11-22; spike S2)

**The record that chose the design** (spike S2, K2 of V9b-2, recorded in the V9b spec on 2026-11-21, quoted):

> A synthetic 1080x1920, 30 fps, 4 s H.264 clip carrying a frame-number band, drawn over the cutaway beat (output frames 70-151) on HyperFrames, read back frame by frame.
> - **Design A**, a `<video>` inside the frame-band iframe: frame-exact only with `currentTime = t + 0.5/fps`. With `t` alone, 28 of 82 frames are wrong. With the offset, the same sha256 at 4, 4, 8 and 2 cores.
> - **Design B**, a top-level media element written the way the proxy is: frame-exact untuned, and the same sha256 at 4, 4, 8 and 2 cores.
>
> Both designs need `hf_render.py`'s allow-list to admit a clip (sha in `vars.json`, size cap), which means a HyperFrames image rebuild. The face gate excused the cut because the cutaway block stays declared over the clip.
>
> **V9b-5b is re-specified on Design B.**

Design A's `t + 0.5/fps` offset is not a fallback. A live leg that fails Design B is a stop (stop rule 8 of the amendment): the frames and figures are reported, nothing is tuned, and Design A is not switched to.

**What was decided and built.**

- **The host** (`providers/renderer/hyperframes.py`). `read_assets` splits the files with `_assets.split_clips`. A picture stays a PNG (`asset_type` otherwise); a clip goes
  through `_assets.read_clip`: an MP4 within `asset_max_bytes`, its `--asset-sha256` matched, and at most 12 files in all. A WebM, and a QuickTime MOV (the `qt  ` brand), are
  `asset_type`, since a render draws only what `asset-sheet` wrote. A clip is staged into the page job with `--asset SLOT=FILE` (a picture never is); every slot keeps its
  `--asset-sha256`. `put_clips` writes each clip into `project/media/clip-<slot>.mp4` (new, `O_EXCL`, `O_NOFOLLOW`, mode 0600, from the bytes the host hashed) after the
  proxy stage's checks and before the drawing stage, so the proxy container (which mounts `media/` read-write) never sees a clip. The name carries the slot, since a slot may be
  called `proxy`. The encode stage, its gates and its mounts are as they were.
- **The page stage** (`_inner.py`, verb `hf-page`). A new repeatable flag `--asset SLOT=FILE`, allowed only with `--blocks`. `_render.load_clips` probes each clip (H.264, yuv420p,
  constant rate, no audio and no other stream, ten seconds at most, sides within 3840) and reads its first-frame tint; the facts go to `_hf_compose.write_page(..., clip_assets=...)`.
  A file that is a picture is `asset_type`. The answer gains no key.
- **The compose** (`providers/renderer/_hf_compose.py`). With `clip_assets` absent or empty the written files do not change by a byte (the picture cutaway's `index.html` and
  `vars.json` have the sha256 recorded in `tests/golden/hf-cutaway-picture.sha256`, taken before the change). `draw_plan` refuses a clip whose rate differs from the edit list's by more than
  0.001 (`asset_type`), runs `_render.settle_clips` (a clip on any block but `oh:cutaway` is `asset_type`; a look that is not the hard cut is `clip_transition`) and
  `_render.clip_rows` (the look is never recomputed here), refuses an entry longer than its clip (`clip_too_short`) and puts `params_kind` and `clip_size` into the entry's
  payload, so the page, unchanged, draws only the label chip. `write_page` writes one clip layer per entry, as the first layers of the page: a `div.hf-clip` in the frame zone,
  hidden until one drive tween (`var CL`, on the frame index, the renderat drive's pattern) shows it on the entry's frames. **Cover**: one video scaled to cover 1080x1920.
  **Glass**, bottom first: the theme's background; a full-frame div with `filter:blur(<glass_blur_px>px)` holding the video at the page's cover-with-room size; the tint at
  `glass_tint_alpha`; a div at `_media.glass_box` with the radius, a black fill and `box-shadow:0 12px 48px rgba(0,0,0,0.45)`; and a second div at the box with
  `overflow:hidden` and the radius, holding the clip. The look is on the wrapping divs, never on the video. Each video has its own track, from `len(kept)` up, and
  `data-media-start="0"`. `vars.json` gains `clip_slots` (sorted), only when there is a clip. A clip slot is never put into `window.__imgs`, so a clip-only page has no picture script.
- **The image** (`providers/renderer/hyperframes-image/hf_render.py`; its tag is the hash of `manifest.json`'s files, so it changes). `CLIP_FILE` and `MP4_BRANDS` (a copy of
  `_media.MP4_BRANDS`; a test keeps them equal); `check_project` collects `media/clip-<slot>.mp4` (pictures and clips together at most 12); `check_assets` takes the clips too: `clip_slots` of
  `vars.json` is a sorted list of distinct slots, each a key of `assets`, the files found are exactly `assets/<slot>.png` and `media/clip-<slot>.mp4`, a clip is an `ftyp` box with a brand of
  `MP4_BRANDS`, and each sha256 matches. Any other file in `media/` but `proxy.mp4` is still `project_unexpected_file`.
- **`blocks/engines/hyperframes.json`**: only its `note` changed; `asset_kinds` **stays `["image"]` on both engines**, so the runtime still refuses a clip pick (`clip_not_drawn`); the flip
  is the later runtime package. `pins.json` and `catalogue.json` changed through `pin-blocks --confirmed` and nothing else in them.
- **The gates do not change** (`_hf_gate.py` is not edited). The clip layer has the class `hf-clip`, which `hf_measure.mjs` does not measure (it reads `.hf-inst` and `iframe.hf-ra`
  only), so the boxes are the page's own: the chip and `window.__box`, in the frame zone, allowed only inside the cutaway's crossing span. The pixel check skips exactly those frames,
  as for a picture; a clip frame that leaks one frame outside its entry changes the face region and is `face_pixels_changed`, which is the guard of frame exactness.

**What S2 left untested, decided.**

| Untested in S2 | Decision | Reason |
|---|---|---|
| Another frame rate | Refused on HyperFrames (`asset_type`) when it differs from the edit list's | `asset-sheet` writes the `--fps` the runtime passes, the edit list's; conforming would be an untested path. ffmpeg conforms |
| VFR | Refused (inherited) | `load_clips` refuses a clip that is not constant-rate in output mode |
| Another size | In scope | cover and glass place it by explicit geometry; live leg L2 (glass 1920x1080) and L4 (square) draw it |
| A cut that starts mid-clip | A media offset is not a feature; an entry that spans a kept-range cut is in scope | `data-media-start` is always 0, as ffmpeg plays from frame 0; the clip's times are the composition's |
| Several clips | In scope, offline (`test_hf_clip.py`) | each is the proxy's own mechanism; no live leg of its own |
| Clip audio | Refused (inherited) | `asset-sheet` drops it, `load_clips` refuses it, the element is `muted` |
| A clip shorter than its cut | Refused on HyperFrames (`clip_too_short`) | whether HyperFrames holds the last frame is unknown; ffmpeg holds it |
| Long cases | Out of scope | a clip is at most 10 s; the real-size M2 is not rerun |

**The saving and the loss of the gaps between the engines.** On ffmpeg a clip of another rate is conformed and a clip shorter than its cut holds its last frame; on HyperFrames both are
refused. The saving: no untested drawing path ships, and the runtime cannot reach either yet (`asset_kinds` is `["image"]`). The loss: the later runtime package must pass the edit list's rate
to `asset-sheet` (it does, by design) and trim a clip cutaway to its clip's length, or a probe must first show that HyperFrames holds the last frame.

**Readings of the spec.**

- A QuickTime MOV is refused by its `qt  ` brand at the host (the spec says a MOV is `asset_type`, and `_assets.read_clip` accepts any `mov`-demuxed file). The image's `MP4_BRANDS` keeps `qt  `
  because it is a copy of `_media.MP4_BRANDS`, which the spec says to keep equal; the host is where a MOV is refused.
- The clip's `slot` is checked as `SLOT_ID` at the host (a picture's is checked by `load_assets`), since the slot becomes part of a file name.
- `draw_plan` takes the entry's frames from the timeline entry, since the plan's `start` and `end` are set after the sort; the order of the clip rows against the marked frame entries is the
  timeline order, which the stable sort keeps for the frame zone.
- Two guard tests outside the spec's file row were widened by the supervisor's decision, because the spec itself requires what they forbid: `test_hf_fixes.py` pins the HyperFrames image tag (now `5bbbcd52f5e0`), and `test_renderer_common.py` lets `_hf_compose` and `verb_hf_page` import `_render` to reuse its clip look.
- A glass tint that is not `#RRGGBB` is `bad_color` naming the slot, as the spec says.

**The image tags change.** At the base (05309e2) the tags were `openhora-renderer:cc41c16fd797` and `openhora-hyperframes:12ff7f4128cb`. Both change: the common image holds `_inner.py` and
`_hf_compose.py`, the HyperFrames image holds `hf_render.py`. The new tags are the hashes of the two manifests' files (`_image.image_tag()`, `hf_image.image_tag()`), recorded by the
supervisor's rebuild (STOP 5, each downloads from an empty cache).

**Verified (offline).** The compose (goldens for cover and glass, each number checked against the page's `drawGlass`, the picture cutaway's two hashes unmoved, the layers before every iframe,
tracks that do not repeat, two clips and a picture in one project, the refusals), the host (staging, the order against the proxy stage with the fake docker, the refusals before any
container), the image's project check (every case of the spec), and `hf-page` with a real, synthetic clip (skipped without ffmpeg).

**Not verified** (the supervisor's live legs, after STOP 5): that HyperFrames draws a video clipped by an ancestor's `border-radius` and `overflow:hidden`, blurred by an ancestor's `filter`
and scaled to a size other than its own (L2, L4); a video two levels deep (glass); the name `media/clip-<slot>.mp4` instead of S2's `media/clip.mp4`; whether HyperFrames holds a clip's last frame
(refused instead); two different clip files in one render, live; every time and memory figure of a render with a clip on this engine.

**C10 of the clip cutaway on HyperFrames (STOP 7).** Not given yet. The supervisor quotes the maintainer's own words here when he gives them, after the sheet of leg L4 (the cover and the glass clip
and a square one, on HyperFrames beside the same on ffmpeg, five frames inside each beat).
