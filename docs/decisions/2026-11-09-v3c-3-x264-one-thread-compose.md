## 2026-11-09: x264 on one thread in the compose and the proxy (V3c-3; no measurement change, no skill changed, no lab run)

**What.** In `providers/renderer/_media.py`, `ENCODE_THREADS = 1` is now x264's thread count for every encode of the common image, with
`X264_PARAMS = "threads=1:lookahead_threads=1:sliced-threads=0"`. `output_options` defaults to both, so the ffmpeg engine's compose writes
`-threads 1 -x264-params ...`; `proxy_argv` (the HyperFrames engine's input) does the same. The decoders' and the filter graphs' counts (`THREADS = 4`) are unchanged.
`encode_argv` and `preview_argv` use `X264_PARAMS` and their argv is identical. The common image's tag changes from `72b41c3cfa17` (`_media.py` is in
`image-manifest.json`); the HyperFrames image's tag, `e5f2134dd1b8`, does not. Dockerfile, manifests and pins are untouched: no download.

**Correction.** `2026-11-08-encode-x264-one-thread.md` says "`THREADS = 4` is unchanged: the ffmpeg engine's render and the proxy still use it". That
stays true of the decoders and graphs; it is no longer true of their x264, which this entry moves to one thread.

**The finding (CI run 42721633048, amd64, ubuntu-24.04).** `test_f3_the_same_input_gives_one_sha256_twice_and_at_two_cpus[ffmpeg]` gave sha256
`a576e772...` twice at (4, "0-3") and `abd66a50...` at (2, "0-1"); the first video packet was 61674 against 61672 bytes, so frame 0 differs, and the audio was
identical. The same test passed on run 42717147564 and always on the Mac (arm64). Frame 0 differing rules out the end-of-stream race of
`2026-11-07-v3a-1-determinism.md`; the compose already pinned every count at four, so the cause is timing inside a fixed count, as in the 2026-11-08 encode.
The proxy ran the same x264 at four threads (F4 passed in that run).

**The decision.** The maintainer, 2026-11-09: "1 thread e medir" (x264 on one thread, measure the cost, merge if stable, report the cost to him). validate: allow english-only -- a quotation of the maintainer

**Cost (to be filled by the supervisor after measuring; not measured by the executor).**

| Figure | Before (committed report) | After |
|---|---|---|
| ffmpeg short render, 4 / 8 cores | 36.34 / 28.47 s | TBD |
| ffmpeg real size render, 4 / 8 cores | 316.94 / 221.01 s | TBD |
| HF proxy, short 4 / 8, real 4 / 8 | 18.91 / 14.05, 123.52 / 80.57 s | TBD |
| HF wall, real 4 / 8; M3 at 8 | 1011.1 / 945.1; 1377.5 s | TBD |

**CI runs (to be filled by the supervisor).** Run ids and minutes: TBD.

**Not verified at the time of writing.** That one-thread x264 is deterministic on amd64 (CI decides); the cost; the cause of the frame-0 difference.

No measurement change, no skill changed, no lab run.
