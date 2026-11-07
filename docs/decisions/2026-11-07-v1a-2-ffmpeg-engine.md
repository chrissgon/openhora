## 2026-11-07: the ffmpeg engine of renderer:video, ported (V1a-2; no measurement change, no skill changed, no lab run)

- `renderer:video` is served by `providers/renderer/ffmpeg.py`, ported onto `providers/_container.py` (VD4). It resolves to `ffmpeg` by a
  class default, so a second engine (VD1) never changes what a caller that names no implementation gets.
- The image is built from the files `image-manifest.json` lists, and `.dockerignore` lets in the same list; a test keeps them equal (review
  finding F11). A host-only edit no longer changes the image tag.
- The container's stderr is kept from its end (the last 64 KiB), as every other provider image; the old branch kept the start.
- The amd64 browser sha256 is the one V3a-image computed; this package downloads nothing.
- CI builds both images on the runner and runs one render on a synthetic input; no model is downloaded there.
- Known limit, against condition 6 of the V0 decision (OPEN-3): the ffmpeg image still installs `fonts-dejavu-core` and has no last layer that
  fails on a font outside the allow-list (the HyperFrames image has one). The port keeps the image as the old branch built it; the purge layer
  is left to V3b0 or V3c.
- Two assertions of the ported tests changed because the port makes them say something else: the second-implementation case of
  `test_renderer_contract.py` now expects the class default (`ffmpeg`, source `class-default`) where a second `renderer` module used to need
  a choice, and the import check allows `_container`, the shared box in `providers/`, beside the provider's own modules.
