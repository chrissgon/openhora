## 2026-11-07: the final encode names every count that could follow the machine (V3a-1; no measurement change, no skill changed, no lab run)

- The live encode leg of V3a-1 gave two different sha256 for one intermediate at `--cpus 2` and `--cpus 4` in one CI run, and one sha256
  in two others. `--cpus` is a quota: the container sees the same cores in both, so no automatic count differed. What was left to
  chance was timing. `encode_argv` pinned only x264's `-threads`; the decoder's threads, the filter graph's (and with them swscale's
  slices for the 4:2:2 10-bit to 4:2:0 conversion), x264's lookahead and sliced threads, and the end of the streams (`-shortest`
  with `-frames:v` under ffmpeg's threaded pipeline) were automatic. `output_options`' docstring said the graph was pinned; only
  `compose_argv` pins it, in its own prefix.
- Now `encode_argv` writes `-filter_threads 4 -filter_complex_threads 4 -threads 4` before the input, `-x264-params
  threads=4:lookahead_threads=1:sliced-threads=0`, no `-shortest`, and `-t out_frames/fps` beside `-frames:v`, so both streams end at
  an exact count. `deterministic=1` is left out: it is x264's default and the image's x264 was not checked to accept the key.
  `output_options(plan, threads, shortest=True, x264_params="")` keeps compose's bytes (its golden files are unchanged).
- The cause was found by reading the code; it is a hypothesis until CI shows it. The live leg now encodes eight times over
  (cpus, cpuset) pairs that change both the quota and the visible cores, from one intermediate, and on a mismatch prints per-stream
  packet and decoded-frame checksums. If it still mismatches, the next step is one thread everywhere (S2's choice), not before.
- Cost: none at four threads; the threads and the x264 options are the ones the encoder already used.
