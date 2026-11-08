## 2026-11-08: the final encode runs x264 on one thread (V3a-1; corrects 2026-11-07-v3a-1-determinism.md; no measurement change, no skill changed, no lab run)

- `2026-11-07-v3a-1-determinism.md` left x264 at four threads (`ENCODE_THREADS = THREADS`) once the decoder and the filter graph ran on one
  thread, on the reasoning that its frame threading is deterministic for identical input, and said the next step on a mismatch was one
  thread. This entry takes that step.
- CI evidence: on GitHub's amd64 runners the live leg `test_the_two_stage_encode_gives_one_sha256_at_two_and_four_cpus` still failed
  intermittently after #772: 1 of 8 encodes differed. The first differing decoded frame was index 55 of 134, mid-stream and not the tail;
  the audio was identical. So the input side was not the whole cause; x264's output depends on timing at four threads on amd64.
- Not reproduced on the maintainer's arm64 Mac: 12 repeats each at x264 threads 4 and threads 1 were all identical. The fix is therefore
  verified by CI's amd64 leg, not locally.
- Now `ENCODE_THREADS = 1`: `-threads 1` and `-x264-params threads=1:lookahead_threads=1:sliced-threads=0`. The input side stays at 1,
  `-frames:v` and `-t` stay, and there is still no `-shortest`. `THREADS = 4` is unchanged: the ffmpeg engine's render and the proxy still
  use it, and `ENCODE_THREADS` is read only by `encode_argv`.
- Cost, measured on the Mac for a 114 s 1080x1920 30 fps ProRes intermediate at `--cpus 4`: x264 at four threads took 85 s, at one thread
  179 s. On the real recording the encode stage was 129-137 s at four threads, so it is expected to take about twice that.
- The maintainer chose one thread in chat, after being shown those costs: "Siga com sua recomendação". (validate: allow english-only -- a quotation of the maintainer)
- `_media.py` is in `providers/renderer/image-manifest.json`, so the common image's definition hash and tag change with this edit; that is
  expected.
