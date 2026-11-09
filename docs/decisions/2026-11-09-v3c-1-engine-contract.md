## 2026-11-09: the engine contract, one live test set for both engines (V3c-1; no measurement change, no skill changed, no lab run)

**What.** One live file, `providers/renderer/tests/test_engine_contract_live.py`, runs the same synthetic inputs through `ffmpeg.py` and `hyperframes.py` (the
engine is a pytest parameter) with the same assertions; its kit, `tests/contract_kit.py`, makes the inputs, holds the report's closed schema and the memory
sampler; `tests/test_engine_contract.py` tests the kit offline. `_hf_gate.check_boxes` gains `caption_not_drawn`, `PIXEL_GROUP` goes, `ffmpeg.py render` gains
`--cpuset` and stages `_blocks.blocks_dir()`, and the renderer job of `checks.yml` runs the new file. `hyperframes-image/` and the common `Dockerfile`, the
manifests and the pins are untouched: no download. The common image's tag changes from `87b3425417e3` to `72b41c3cfa17` (`_hf_gate.py` is in its manifest);
the HyperFrames image's tag, `e5f2134dd1b8`, does not.

**Decisions (D1 to D6 of the spec, all as recommended).**

- D1. One parametrised file, gated by the variable each image already has (`WB_RENDERER_DOCKER_TESTS`, `WB_HYPERFRAMES_DOCKER_TESTS`), per engine
  parameter; no pytest marker. The composed and the planted tests of `test_hf_docker_live.py` moved into it (F1, F3, F5, F6), with every assertion carried
  over; that file keeps the base-only render at 4 and 8 cores.
- D2. Two kinds of leg: functional (F1 to F8, short inputs, CI and the Mac) and machine (M1 to M3, `test_mac_*`, `WB_ENGINE_MAC_LEGS=1`, one after another).
- D3. The edit list is read from the pixels: the synthetic recording carries its frame number as 14 cells of 72 px at the top of the picture.
- D4. Host-side parity only: `ffmpeg.py render --cpuset` and the test blocks folder (RENDERER_TEST=1 and RENDERER_BLOCKS_DIR). Neither is in an image.
- D5. The gate hole closes (C12): a caption entry of 6 frames or more with no glyph box of area in its span is refused `caption_not_drawn` ("caption <k>
  frames <first> to <last>"), entries in order.
- D6. Measure, never fix, the limits: no limit, thread count or timeout changed.

**The contract (derived from the code at 3472cdd, 12 promises).** C1 name, mode 0400, never rewritten, verified in a fresh container; C2 the platform's spec;
C3 audio kept; C4 the edit list is what is drawn; C5 nothing touches the face box; C6 no caption below 1560; C7 a beat the engine cannot draw is refused first;
C8 the recording is the one the list was made from, at most 300 s; C9 same input, same bytes, whatever the cores; C10 limits in code; C11 a refusal leaves
nothing; C12 a caption with words draws glyphs. Before this package C3, C4 and C12 were asserted nowhere, C5 and C6 only offline on the ffmpeg engine, and
the ffmpeg engine's render was never compared across cores live.

**`caption_not_drawn` and its cost (principle 13).** Saved: a caption that draws nothing can no longer pass both gates silently. Given up: an entry shorter than
6 frames (0.2 s at 30 fps, possibly all entry animation) is not judged, and a deliberately empty caption is refused (none exists: captions are words). It is
the HyperFrames engine's gate only: the ffmpeg engine's pages load their fonts in their own setup, and a missing font fails the render before frame zero.
The existing gate tests that draw no glyphs run with the rule out of reach (their subject is the other rules) and two encode tests now give their clean
boxes one glyph per caption entry.

**Departures and notes.**

- The real-size legs (M2) keep the base edit list's zoom, so the exact frame check there covers the kept ranges drawn unzoomed (`contract_kit.compare_frames
  (only_unzoomed=True)`); F2, on the short case, uses `--zoom none --push-in 0` and checks every frame.
- `ffmpeg.py` had to put `providers/` on the path before importing `_container` (the import was found failing offline).
- M3's limit outcome (`render_timeout`, `no_space`, `intermediate_too_large`) fails the test after its row is recorded: stop rule 4 reports it; nothing is raised.

**Report and Mac run.** `providers/renderer/reports/engine-contract-2026-11-09-arm64.json` (committed unchanged, checked by `contract_kit.check_report`) was
written by the supervisor's run at 559bd7d (Docker Desktop, 14 CPUs, 27013 MiB; common `72b41c3cfa17`, HyperFrames `e5f2134dd1b8`, HyperFrames 0.9.19). By count:
the functional legs (`-k "not mac_"`) 14 passed, 0 failed, 20.6 min; `test_hf_docker_live.py` 1 passed; the machine legs (`-k mac_`) 5 passed, 0 failed, 74.6
min; no stop rule fired.

- M1, the short case (19.5 s in, 6 kept ranges, 412 out frames): one sha256 per engine at 4 and at 8 cores (ffmpeg 14108988 bytes, HyperFrames 11263635).
  ffmpeg 36.3 s at 4 cores, 28.5 s at 8; HyperFrames wall 125.5 s and 114.0 s.
- M2, real size (186.5 s in, 37 ranges, 4556 out frames): one sha256 per engine at 4 and at 8 cores; the exact frame check on the 8-core output of each engine
  checked 1962 frames (the unzoomed ranges), 0 bad. ffmpeg 154414509 bytes, 317 s at 4 cores and 221 s at 8. HyperFrames 121882799 bytes, stage seconds at 4
  cores page 5.5, proxy 123.5, hf 434.5, encode 447.4, measure 97.9, pixel 159.7 (wall 1011 s; at 8 cores 945 s). HyperFrames drawing container: cgroup
  `memory.peak` 6053 MiB (6045 at 8 cores; it counts page cache), sampled maximum 3404 MiB; the common containers' sampled maximum 525 MiB (ffmpeg engine 1194
  MiB at most). Intermediate 2034054143 bytes. Gate figures: 24042 boxes, lowest caption bottom 1416.8, minimum PSNR 35.64 dB over 37 ranges.
- M3, 297.9 s in, 63 ranges, 7125 out frames, HyperFrames at 8 cores: ok, wall 1377.5 s (under the 1800 s cap), cgroup peak 6144 MiB (the cap), sampled
  maximum 4341 MiB (under the 5530 MiB stop line), common sampled 527 MiB, intermediate 3169315822 bytes.
- The first finding on C9: both engines, composed, give one sha256 at 4 and at 8 cores on arm64 (not measured before for either).

**Not measured.** amd64 (until V3c-2); the OOM counts (`oom_events` is null in every row: `docker events` gave no count, and the code is not changed here);
that `docker stats` on Docker Desktop subtracts the file cache as on Linux (unverified), and a one-second sample can miss a short peak; the zoomed ranges' frames
at real size (the exact check covers the unzoomed ones); determinism on amd64 of x264 at four threads in the compose and the proxy. The band's reading inside the
image's own ffmpeg, the frame-exactness of HyperFrames at cuts and the planted `cover` and `low` blocks in HyperFrames iframes, listed as unverified before the
run, were exercised by it and passed. No measurement change, no skill changed, no lab run.
