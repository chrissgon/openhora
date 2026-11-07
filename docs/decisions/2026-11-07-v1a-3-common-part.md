## 2026-11-07: the common part of the renderer apart from the drawing, and the 1560 line (V1a-3; no measurement change, no skill changed, no lab run)

- The modules both engines need (edit list, alignment, layout, assets, cover, still, verify) import nothing of the browser, the frames or
  the storyboard; a test walks their imports. The HyperFrames engine (V3a) reuses them without the ffmpeg engine's drawing.
- `zones.caption_bottom` is 1560 (VD12). A drawn caption below it fails the render with `caption_below_line`; this is the ffmpeg engine's
  half of the gate, and V3b adds the HyperFrames half.
- `ffmpeg.py verify` is a host verb, so a caller can verify an output without rendering it again.
- `selfcheck` is the one verb of `_inner.py` that names the drawing part and is not a drawing verb: it reports the browser's version and the
  template pins, so it imports `_cdp` and `_frames` inside its own function. `analyse`, `base`, `align`, `check`, `verify`, `cover` and `still`
  load none of them.
- The image tag changes (three modules joined the manifest and the presets file changed); CI's `renderer` job builds the new one.
