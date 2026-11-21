## 2026-11-21: the frame band on the HyperFrames engine, image assets, the asset sheet and `oh:screenshot`, with the face gate loosened only inside the cut (V9b-2; spec `SPEC-video-V9b`, section 5, and its amendment of 2026-11-21)

**What was decided and built.**

- **Decision 6 of V9b, quoted** (2026-11-10, the gate): "Sim, só dentro do corte". The face gates are loosened only inside full-frame cutaway frames, and tests
  prove nothing changes outside them.
  - The saving: full-frame cutaways on the default engine (HyperFrames). Without the loosening every cutaway would be refused `overlay_hits_face` and
    `face_pixels_changed`, since the picture covers the face by design.
  - The loss: on those frames, and only those, no gate watches the face. The label chip's text and the picture are not judged against the face there.
  - What stays: the captions keep every rule on every frame (the face box, the line at 1560); a `frame`-zone box one frame outside the entry is
    `overlay_hits_face`; the pixel check judges the frame before and the frame after the entry as ever; the entries that open a span are read from the pinned
    catalogue (`may_cross_face` of a `frame`-band block), never from anything the drawing container wrote; and an encode stage given no catalogue
    (`--blocks` left out) opens no span, so leaving it out can only make the gate stricter. The tests are in `providers/renderer/tests/test_hf_gate.py`
    (the proof of decision 6, and the encode verb end to end with a black picture over the face on exactly the entry's frames).
  - Not chosen: letting the page's own report say which frames are a cut (a block could claim every frame); loosening for every `frame`-band block (`oh:pip`
    is of the band and may not cross the face); making the pixel check blind to a whole range.
- **The caption over a glass picture is approved**: "Sim, igual ao cartão" (C10 of V9d, 2026-11-11; validate: allow english-only -- the maintainer's own
  words, quoted). The caption band stays where it is, over the bottom of a centred picture, on both engines. The rule that captions keep every rule is unchanged.
- **The frame band on HyperFrames.** `oh:cutaway` is `blocks/engines/hyperframes.json`'s block for the `cutaway` preset. A frame-band entry is an iframe of the
  block's own `renderat` page, in the frame zone (under the cards and the captions, over the cuts), with `window.__imgs` filled from `assets/<slot>.png` and
  each `decode()` kept as a promise. The look is not copied: the page already draws the hard cut and the glass layout of V9d, and its looks come with the
  payload (`_payload.beat_data`). `renderat.html`, `renderer-presets.json` and `_payload.py` are unchanged. `pip` stays absent from this engine.
- **Pictures** on `hyperframes.py render`: `--asset SLOT=FILE` and `--asset-sha256 SLOT=HEX`, read on the host (PNG only), copied to `project/assets/`, named by
  their sha256 in `vars.json` (`assets`), which `hf_render.py` checks against the files (at most 12, regular, `<slot>.png`, within `asset_max_bytes`).
- **`asset-sheet`**, a common verb: checks and tiles pictures (`preview`), and normalises the picked ones (`full`): a metadata-free PNG, the long side scaled
  to 1920, never enlarged more than 1.5 times, named by its own bytes. The reading of the spec's "the smallest size that covers 1080x1920" is the long side to
  1920 (see the pull request).
- **`oh:screenshot`**, a second block of the `cutaway` preset: the picture whole, as a card on a backdrop in the theme's colour, a slow push-in, the label chip.
- **`asset_kinds`** in each engine file (`["image"]` on both) and `asset_kinds_by_engine` in the catalogue.

**The image tags changed.** `hf_render.py` (the HyperFrames image) and `_asset_sheet.py`, `_inner.py`, `_hf_compose.py`, `_hf_gate.py`, `_blocks.py` and the
blocks (the common image) changed, so both tags changed (HyperFrames `e5f2134dd1b8` to `12ff7f4128cb`, the last change being a `.png` entry in `hf_measure.mjs`'s MIME table; the common image `5aba516536a5` to `8206b171b52b`; the pin in `test_hf_fixes.py` is updated). Both images
must be rebuilt before a live render (the maintainer's, STOP 5).

**Readings of the spec, accepted by the supervisor.**

- `asset-sheet`'s "the smallest size that covers 1080x1920" is read as: the long side becomes 1920 and the aspect is kept, and a picture whose long side would
  grow more than 1.5 times (under 1280 px) is `asset_too_small`. The literal reading (cover both dimensions) would refuse every landscape picture under about
  2275 px wide.
- A frame entry is counted under `beats` (`beats_drawn` and the `beats` layer name), because the `hf-page` result allows four layer names and captions plus
  beats already fill them.

**Not verified.** No image was rebuilt and no live render ran; no C10 was shown (the maintainer's words for `oh:cutaway` on HyperFrames and `oh:screenshot` on
both engines go here once he gives them); the determinism at 4 and 8 cores (`F9`, `M4` of `test_engine_contract_live.py`) and spike S2 are the supervisor's.
The page tests run in the host's browser with a stand-in for GSAP's timeline, since GSAP is in the HyperFrames image only.
