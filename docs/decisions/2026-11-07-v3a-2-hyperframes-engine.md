## 2026-11-07: the HyperFrames engine of renderer:video (V3a-2; no measurement change, no skill changed, no lab run)

- `renderer:video` has a second implementation, `providers/renderer/hyperframes.py` (VD1); `ffmpeg` stays the class default.
- A render runs five containers: the page, the proxy and the encode in the common image, the drawing in the HyperFrames image, the
  verification in a fresh common container. Every one runs with `--network none`.
- Limits in code: memory 6144 MB by default and at least 4096, pids 1024, 4 workers, `/scratch` 256 MB; the frames and the ProRes
  intermediate go to a disk work folder (`<work>/hf-<id>/`), checked for free space first and removed when the render ends (VD8; a
  killed process leaves it to the media step's retention, decision 12).
- The free-space need assumes 28 MiB of intermediate per second (Apple's ProRes 422 HQ target, not measured here). The measurement on
  one real recording kept outside the repository is NOT RUN YET: it waits on the maintainer's word for the local builds and for the
  recording (the spec's STOP B, D and C). Until it is run this entry states no rate, no seconds per stage, no peak memory and no answer
  on whether the final sha256 is equal at 4 and 8 cores; the figures and their provenance line replace this sentence before the pull
  request is marked ready.
- A page naming a font family outside the allow-list is refused before HyperFrames runs (its injector would add a bundled font).
- `hyperframes.py build --confirmed` writes a build record, and `--check` refuses an image that is not the recorded one, as the ffmpeg
  engine does. `doctor.py` lists the image family.
- Captions, cards, `hf:` blocks and the face-box and 1560 gates are V3b's; a render without `--base-only` is refused until then.
