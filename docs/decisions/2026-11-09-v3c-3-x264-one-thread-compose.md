## 2026-11-09: x264 with sliced threads at 4 in the compose, the proxy and the final encode (V3c-3; no measurement change, no skill changed, no lab run)

**What.** In `providers/renderer/_media.py`, `X264_THREADS = 4` and `X264_PARAMS = "threads=4:lookahead_threads=1:sliced-threads=1"` are the x264
settings of the ffmpeg engine's compose, the HyperFrames engine's proxy and its final encode (`encode_argv`); `output_options` defaults to both. The
preview stays on one thread (`ENCODE_THREADS = 1`, `PREVIEW_X264_PARAMS`, its argv unchanged). The decoders' and filter graphs' counts are unchanged
(`THREADS = 4`; one thread in the encode and the preview). The common image's tag changes from `72b41c3cfa17` (`_media.py` is in `image-manifest.json`);
the HyperFrames image's tag, `e5f2134dd1b8`, does not. Dockerfile, manifests and pins are untouched: no download.

**Correction.** `2026-11-08-encode-x264-one-thread.md` says "`THREADS = 4` is unchanged: the ffmpeg engine's render and the proxy still use it" and
moved the final encode to one x264 thread. That stays true of the decoders and graphs; the final encode's x264 now runs four slice threads, and the
compose and the proxy move from four frame threads to the same four slice threads.

**The finding (CI run 42721633048, amd64, ubuntu-24.04).** `test_f3_the_same_input_gives_one_sha256_twice_and_at_two_cpus[ffmpeg]` gave sha256
`a576e772...` twice at (4, "0-3") and `abd66a50...` at (2, "0-1"); the first video packet was 61674 against 61672 bytes, so frame 0 differs, and the
audio was identical. The same test passed on run 42717147564 and always on the Mac (arm64). Frame 0 differing rules out the end-of-stream race of
`2026-11-07-v3a-1-determinism.md`; the compose already pinned every count at four, so the cause is timing inside a fixed count, as in the 2026-11-08
encode. The proxy ran the same x264 at four frame threads (F4 passed in that run).

**First attempt: one thread (commit c061ea1, common image `cda683375f04`).** The maintainer, 2026-11-09: "1 thread e medir" (x264 on one thread, measure
the cost, merge if stable). validate: allow english-only -- a quotation of the maintainer
It was measured on the Mac and its report is not committed; its figures are quoted here. Every sha256 pair matched, but the cost crossed a bound.

**The change: sliced threads at 4.** x264 runs four slice threads (`threads=4:lookahead_threads=1:sliced-threads=1`) in the compose, the proxy and the
final encode; the preview stays on one thread; the decoders and filter graphs keep their counts. x264's frame threads let several frames be in flight,
each reading state another is still writing, so the bytes can depend on timing. Sliced threading encodes the slices of one frame in parallel and has no
such state, so it is repeatable at any core count and keeps most of the parallel speed. The trade-off is compression: slices cost a little at the same CRF.

**Cost, in seconds at 4 / 8 cores.** "Before" is four frame threads, from the committed `engine-contract-2026-11-09-arm64.json`; "one thread" is c061ea1;
"sliced" is cf3fe3f (common image `17ff62c5792a`, HF image `e5f2134dd1b8`), whose report is `providers/renderer/reports/engine-contract-2026-11-10-arm64.json`.

| Figure | Before (4 frame threads) | One thread (c061ea1) | Sliced x4 (cf3fe3f) |
|---|---|---|---|
| ffmpeg short render | 36.34 / 28.47 | 46.04 / 38.83 | 39.83 / 32.73 |
| ffmpeg real size render | 316.94 / 221.01 | 423.0 / 360.31 | 351.84 / 284.51 |
| HF short wall | not recorded here | 140.3 / 129.4 | 119.9 / 121.3 |
| HF real size wall | 1011 / 945 | 1285.2 / 1133.8 | 963.0 / 924.7 |
| HF real size proxy | 124 / 81 | 276.89 / 254.2 | 179.83 / 193.79 |
| M3 wall (8 cores) | 1377.5 | 1793.9 (proxy 410.49) | 1362.9 (proxy 241.44) |

One thread crossed the bound of 1620 s on M3 (1793.9 s), which is why sliced threads were chosen. Sliced threads crossed no bound: the ffmpeg real size
render stayed under 2x its before (633.9 / 442.0), every HF wall under 1620 s, and the CI renderer job under 50 minutes.

**Bytes at the same CRF, sliced against one thread (what the slices cost).**

| Case | Sliced | One thread | Change |
|---|---|---|---|
| ffmpeg short | 14183852 | 14109920 | +0.52% |
| ffmpeg real size | 155684648 | 154411039 | +0.82% |
| HF real size | 122585961 | 121605174 | +0.81% |
| M3 | 192597691 | 191092007 | +0.79% |

**Mac legs at cf3fe3f.** F legs: 14 passed in 1282 s (21.4 min; the one-thread run took 30.7 min). Renderer docker live: 5 passed in 397 s. M legs: 5 passed
in 4532.7 s. Every case had one sha256 at 4 and at 8 cores (`same_sha256` true for both engines).

**CI runs (amd64, run 42749118896 at cf3fe3f).** The renderer job ran 3 attempts, all green: 11.7, 14.2 and 14.1 minutes. Each attempt ran the contract
file: 13 passed, 12 skipped, with F3[ffmpeg] and F4 included. F3[ffmpeg] is the leg that failed at four frame threads (run 42721633048).

**Not verified.** The cause of the frame-0 difference at four frame threads (x264 against the filter graph) was not isolated; determinism is shown by the legs above on arm64 and by three CI attempts on amd64, not proved.

No measurement change, no skill changed, no lab run.
