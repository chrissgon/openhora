## 2026-11-10: the key media.renderer and HyperFrames the default (V4; no measurement change, no skill changed, no lab run)

Package V4 of the video plan. It adds the project key `media.renderer`, makes HyperFrames the default engine of `renderer:video`, and gives
`hyperframes.py` the `block-params` verb that `ffmpeg.py` already had.

**The plan's condition is met.** V3c passed (#795, #797, #796) and C10 of the blocks is approved (2026-11-08 for V3b-3, 2026-11-09 for V3b-4, with the
highlight transition flaw left for later).

### Decisions

- **D1. The key** is `media.renderer` in the existing `media` object: `"auto"`, `"ffmpeg"` or `"hyperframes"`, and it may be absent. `runtime/project_config.py`
  `_media` checks it as `_outbox` checks `outbox.provider`: `auto`, or a name in `_implementations(workbench, "renderer:video")`. It is accepted with
  `accept-config` as part of the file's hash, with no code of its own (as `outbox` and `code`).
- **D2. What each value means.** It follows `outbox`. A name is passed by the runtime as the resolver's `implementation` (source `configuration`), so it wins over
  a variable. `auto` or absent passes nothing: a variable decides, then the class default. The class default is `hyperframes`, set in one place,
  `CLASS_DEFAULTS` of `providers/resolve.py`, so the runtime, `scripts/doctor.py --class renderer:video` and a person's direct call agree.
- **D3. A missing setup is refused, never replaced by the other engine.** The provider's exit 3 stays `not_configured`, and its next sentence names the key and
  says how to set the image up or to name the other renderer. An input only one engine draws stays refused by that engine's own code (`block_not_on_engine`,
  `preset_not_on_engine`). Nothing changes engines in the middle of a task. The engine decides the look the person approves, so a fallback would render with an
  engine the person did not pick (principle 5), and would need a probe verb and a recorded engine per task.
- **D4. No migration.** No project on `main` has a `media` step, so an absent key means the new default. A project of the integration branch keeps ffmpeg with
  `"renderer": "ffmpeg"` in `docs/workbench/runtime.json` and an `accept-config`.
- **D5. `block-params` on `hyperframes.py`** calls `_host.verb_block_params(args, ENGINE)`, as `ffmpeg.py` does, with the same arguments and the same refusal
  codes; it starts no container and prints no value. `block_check_unavailable` is removed: a refusal of `block-params` with no closed reason line is
  `block_check_failed`, and `test_renderer_contract.py` keeps that every implementation of the class answers `block-params`.
- **D6. The listing and the checker of "Add an animation"** (`media_animation.engine_name`, `listing`, `checker`, and the operation `video-catalogue`) read the
  project's key through the same store as `MediaEngine` (`MediaStore.renderer()`).

### What is refused

| Situation | Absent or `"auto"` | `"hyperframes"` | `"ffmpeg"` |
|---|---|---|---|
| Both images built and recorded | hyperframes (class default) | hyperframes | ffmpeg |
| `RENDERER_PROVIDER=ffmpeg` in the runtime's environment | ffmpeg (the variable wins over the class default) | hyperframes (the configuration wins) | ffmpeg |
| HF image not built, stale or not recorded | refused at `render`: `not_configured` and the new sentence; the review is kept | the same | not concerned |
| An added `hf:` animation | accepted on hyperframes | accepted | refused at the edit, `block_not_on_engine` (unchanged) |
| A script beat of `cutaway` or `pip` | `preset_not_on_engine` at `render` on hyperframes | the same | drawn on ffmpeg, but needs an asset slot that no M1 path fills |
| The key changed after a task's review | the render uses the accepted key's engine; an `hf:` animation on ffmpeg is refused at `render` (`block_not_on_engine`) | | |

### The cost (principle 13)

- **Saved.** No engine is ever chosen behind the person's back. No readiness probe enters the closed list of verbs. No engine is recorded per task. The hard
  limits stay where they are.
- **Given up.** A computer without the HyperFrames image fails at the render, after the caption review, instead of at the start. The review is kept.
- **Also given up.** Every default video now uses the HyperFrames caption block, which carries the highlight transition flaw left for later, and renders about 2.6
  times slower at real size. Measured on real runs (`providers/renderer/reports/engine-contract-2026-11-10-arm64.json`): the real-size case takes 963 s with
  hyperframes and 364 s with ffmpeg at 4 cpus, and 925 s and 296 s at 8 cpus; the 300 s case takes 1363 s with hyperframes at 8 cpus, under the 1800 s cap; both
  engines give the same sha256 at 4 and at 8 cpus.

### Also

- `scripts/doctor.py --class renderer:video` now resolves to `hyperframes` and runs `hyperframes.py --check` (a behaviour change; `doctor.py` itself is unchanged).
- No image changed: `hyperframes.py` and `_host.py` are host-only files, and no file of the image manifests was touched. No download. No skill changed, so no
  bump, no lab run and no measurement change.
- Stays open: G14 (picking another block for a script beat's preset) is a later package (V5); the engine shown on the video card and in the delivery document is
  not part of V4 (the block ids `hf:` and `oh:` already show it on the card).

### Live results

Run by the supervisor on 2026-11-10 on the Mac (arm64, 14 docker cpus) at 8a92ea4. Every leg passed.

- No image file changed: the diff of the image files is empty.
- Both images were rebuilt from the same pins, from the layer cache, with no download: common `openhora-renderer:17ff62c5792a`, HyperFrames
  `openhora-hyperframes:e5f2134dd1b8`.
- `hyperframes.py --check` is ok. The selfcheck reported HyperFrames 0.9.19, telemetry off, fonts as SHA256SUMS, and the network on loopback only.
- Existing live tests, unchanged by V4: `test_renderer_docker_live.py` 5 passed (407 s); `test_engine_contract_live.py -k "not mac_"` 14 passed (1243 s);
  `test_hf_docker_live.py` 1 passed (236 s).
- `test_engine_default_live.py`: 4 passed (421 s).
  - L1: with no renderer named, the engine is hyperframes, with the same sha256 as the host's direct render.
  - L2: naming ffmpeg renders with ffmpeg.
  - L3: `block-params` is answered by the named engine and refused by the other.
  - L4: a missing HyperFrames image is refused and never replaced by ffmpeg.
- `hyperframes.py block-params --block hf:spring-pop` on the host printed `{"ok": true, "block": "hf:spring-pop", "engine": "hyperframes", "params": ["text"]}` and exited 0.
