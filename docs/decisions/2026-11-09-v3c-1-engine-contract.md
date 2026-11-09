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

**Report.** `providers/renderer/reports/engine-contract-<date>-<arch>.json` is written by the live file (`WB_ENGINE_REPORT=<new file>`) and committed unchanged by
this package after the supervisor's Mac run. Its figures (M1 and M2 sha256 equality per engine, stage seconds, the memory figures, the outcomes) are added to this
file's PR, not here, before the merge.

**Not measured.** amd64 (until V3c-2); `docker stats` on Docker Desktop subtracts the file cache as on Linux (unverified) and a one-second sample can miss a short
peak; the 300 s case if M3 was not run; the band's reading inside the image's own ffmpeg (the offline test uses the host's); that HyperFrames draws the proxy
frame-exact at cuts; that the renderat pages in HyperFrames iframes report boxes for the planted `cover` and `low`. No measurement change, no skill changed, no
lab run.
