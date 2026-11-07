## 2026-11-07: the common side of the two-stage encode (V3a-1; no measurement change, no skill changed, no lab run)

- `providers/_container.py` takes `cpuset` and `shm_mb`, both off by default; with both off every provider's command is byte-equal to
  before (the GOLDEN tests). `check_free_space` refuses a long job before it starts when its disk folder cannot hold it.
- The HyperFrames engine's x264 output followed the cores a container saw (S2, check C2). The fix is two stages (V0 condition 2,
  decision 4): HyperFrames writes a ProRes HQ intermediate, and the common image encodes the final H.264 with a fixed thread count,
  through `_media.output_options`, the same output options as the ffmpeg engine. Measured in CI: one intermediate gives one sha256 at
  two and four cpus. S2 measured one sha256 at 4 and 8 cores on a synthetic input.
- The proxy (decision 5) is made by the common image: 1080x1920, the edit list's fps, x264 CRF 14 with fixed threads and bitexact
  scaling, at most 2 GiB.
- The base page of the HyperFrames engine (cuts and zoom, numbers only) is written by `_hf_page.py` in the common image, so no word of
  the edit list reaches the drawing image in V3a.
- `time_limit_for`, `check_documents` and the recording checks moved from the drawing module to `_output.py`. Saving: the second engine
  imports no drawing code. Loss: none; `_render` re-imports them.
