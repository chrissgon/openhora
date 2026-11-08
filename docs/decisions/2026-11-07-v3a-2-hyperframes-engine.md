## 2026-11-07: the HyperFrames engine of renderer:video (V3a-2; no measurement change, no skill changed, no lab run)

- `renderer:video` has a second implementation, `providers/renderer/hyperframes.py` (VD1); `ffmpeg` stays the class default.
- A render runs five containers: the page, the proxy and the encode in the common image, the drawing in the HyperFrames image, the
  verification in a fresh common container. Every one runs with `--network none`.
- Limits in code: memory 6144 MB by default and at least 4096, pids 1024, 4 workers, `/scratch` 256 MB; the frames and the ProRes
  intermediate go to a disk work folder (`<work>/hf-<id>/`), checked for free space first and removed when the render ends (VD8; a
  killed process leaves it to the media step's retention, decision 12).
- The free-space need assumes 28 MiB of intermediate per second (Apple's ProRes 422 HQ target). Measured on one real recording kept
  outside the repository (4K HEVC 60 fps; 2160x3840; source 192.66 s, output 113.967 s, 3419 frames at 30 fps), arm64, HyperFrames
  0.9.19, 2026-11-07, 2 runs (`--cpus 4 --cpuset 0-3`, then `--cpus 8 --cpuset 0-7`, in sequence); not checkable:
  - Final sha256, intermediate sha256 and proxy sha256 are equal at 4 and at 8 cores (check C2 holds on this input on arm64);
    the output was verified in both runs.
  - Intermediate: 2,706,100,880 bytes, 23,744,670 B/s (22.6 MiB/s), under the 28 MiB/s figure, so the free-space check and the cap stand.
  - Seconds per stage at 4 cores / 8 cores: page 2.93 / 4.45, proxy 350.74 / 265.01, hf 391.1 / 296.97, encode 137.26 / 128.69;
    wall time 883 s / 695 s.
  - `memory_peak_bytes` was 6,442,450,944 in both runs, exactly the 6144 MB limit, and neither run was killed. This figure is not
    informative: the cgroup peak counts the page cache of writing the 2.7 GB intermediate, so it reaches the limit; it does not show
    that the render needs 6 GiB. Open point for V3c: measure the anonymous memory, or run at 4096 MB (`HF_MEMORY_MB_MIN`).
- Local gates on the maintainer's Mac (arm64, at 13b231c): both images built; `hyperframes --version` is 0.9.19 and `render --help`
  has `--output`, `--format`, `--prores-profile`, `--variables-file`, `--workers`, `--frames-cache-dir`, `--fps` and `--quiet`;
  `test_hf_docker_live.py` passed (1 passed, 211.59 s, at 9a8057e).
- A page naming a font family outside the allow-list is refused before HyperFrames runs (its injector would add a bundled font).
- `hyperframes.py build --confirmed` writes a build record, and `--check` refuses an image that is not the recorded one, as the ffmpeg
  engine does. `doctor.py` lists the image family.
- Captions, cards, `hf:` blocks and the face-box and 1560 gates are V3b's; a render without `--base-only` is refused until then.
