## 2026-11-09: x264 on four slice threads in the compose, the proxy and the final encode (V3c-3; no measurement change, no skill changed, no lab run)

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

**First attempt: one thread (commit c061ea1).** The maintainer, 2026-11-09: "1 thread e medir" (x264 on one thread, measure the cost, merge if
stable). validate: allow english-only -- a quotation of the maintainer
The Mac run measured the HyperFrames proxy at real size going from 124 / 81 s to 277 / 254 s at 4 / 8 cores, which the maintainer found too slow.

| Figure, one thread (c061ea1) | Before (committed report) | One thread |
|---|---|---|
| ffmpeg short render, 4 / 8 cores | 36.34 / 28.47 s | TBD |
| ffmpeg real size render, 4 / 8 cores | 316.94 / 221.01 s | TBD |
| HF proxy, short 4 / 8, real 4 / 8 | 18.91 / 14.05, 123.52 / 80.57 s | TBD (real: 277 / 254 s) |
| HF wall, real 4 / 8; M3 at 8 | 1011.1 / 945.1; 1377.5 s | TBD |

**The change: sliced threads at four.** x264's frame threads let several frames be in flight, each reading state another is still writing, so the bytes
can depend on timing. Sliced threading encodes the slices of one frame in parallel and has no such state, so it should be repeatable at any core count
and keep most of the parallel speed. Trade-off to be measured: slices cost some compression, so the bytes at the same CRF grow (the report's `bytes`
give it), and the rate control sees slightly different frames.

| Figure, sliced threads at four | Before (committed report) | Sliced x4 |
|---|---|---|
| ffmpeg short render, 4 / 8 cores | 36.34 / 28.47 s | TBD |
| ffmpeg real size render, 4 / 8 cores | 316.94 / 221.01 s | TBD |
| HF proxy, short 4 / 8, real 4 / 8 | 18.91 / 14.05, 123.52 / 80.57 s | TBD |
| HF wall, real 4 / 8; M3 at 8 | 1011.1 / 945.1; 1377.5 s | TBD |
| Output bytes at the same CRF (report `bytes`), against the committed report | TBD | TBD |

**CI runs (to be filled by the supervisor).** Run ids and minutes: TBD.

**Not verified at the time of writing.** That sliced-thread x264 is deterministic on amd64 (CI decides); the cost; the bytes; the cause of the frame-0 difference.

No measurement change, no skill changed, no lab run.
