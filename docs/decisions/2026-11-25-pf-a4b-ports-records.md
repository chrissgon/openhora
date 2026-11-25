## 2026-11-25: The determinism records of four ports on the ffmpeg engine (PF-a4b; plan video quality v6)

**Context.** PF-a4a moved the five kept ports (`hf:caption-highlight`, `hf:caption-pill-karaoke`, `hf:count-up`, `hf:testimonial-card`, `hf:spring-pop`) to the second contract in host code. PF-a4b measures them with `ffmpeg.py admit-block --port hf:<name> --vocabulary shared/references/video-presets.json --confirmed` and pins the records.

**Decision.**
- **The four records** (supervisor's run, image `openhora-renderer:cf79df31dbf0`, runtime_sha256 `491a22ffea0bf65cedc4389ddda9c31e2906c7adac05726333e4d4f422bf42ea`, 3 samples, 4 runs, 0 blocked, 2026-11-25):

| Port | frames | seconds | served_sha256 |
|---|---|---|---|
| `hf:caption-highlight` | 150 | 36.88 | `1b5fb1af6faca2bcd064f5467037c5cb8f2c957faac350bb3024c31a8b31cdd9` |
| `hf:caption-pill-karaoke` | 150 | 36.19 | `0d1666302b953b51c53e4a967b952ef7e4a123d40f8b805add1158c6a8d5bdad` |
| `hf:count-up` | 198 | 41.96 | `455bf65ad5f8221298a57f50c38000288f0a70b29b6879579a8da1276f496503` |
| `hf:testimonial-card` | 189 | 40.41 | `d041f753b7488a52832dfa50570df834102d04144f25a8760080f83f80feb6b9` |

- **What changes.** The four ports are drawable by name on the ffmpeg engine under the second contract. The ffmpeg engine's preset defaults stay `oh:<preset>`: M2 (switching the defaults) is not asked yet. `test_hf_ports.py` now expects the four on both engines and `hf:spring-pop` on the HyperFrames engine only.
- **Spring-pop, S5.** `hf:spring-pop` fails admission (`determinism_failed sample 1 frame 1`), reproducible on the same image. Two host-only tries (`will-change` on `#oh-inst`, and on `#oh-inst *`) did not fix it. Edits to the port, measured with a temporary diagnostic that named the differing runs (reverted):
  - Two opacity tweens on one element (intro 0 to 1, outro 1 to 0 with `immediateRender:false`) were a cause: moving the outro to the `.stage` wrapper moved the failure from frame 1 to frame 15.
  - Frame 15 (0.5 s at 30 fps) is the only frame that differs, and only in the reverse run; forward runs agree. So the remaining cause is history-dependent state of the `back.out` scale tween on `.badge`. The exact mechanism is not isolated.
  - Variants that still failed at frame 15: `force3D:false`; `force3D:true`; the outro without `immediateRender:false`; `will-change: transform` on `.badge` in the port's CSS. A diagnostic with `ease:"none"` gave `block_not_drawn frame 0` and is inconclusive.
  - The port is unchanged and stays unadmitted.
- **The maintainer's answer** on editing the port and comparing the look:

"Editar e comparar (Recomendado)" (validate: allow english-only -- the maintainer's own words, quoted)

  The edit was tried and found no variant that keeps the look and passes; no comparison sheet was made because nothing passed.
- **Pending.** M2 at C10 with a parity sheet; the spring-pop fix; the flipped live legs.

**What it saves and what it loses (principle 13).** It saves a guess: four ports are proven deterministic on the real runtime before anything can use them, and the unproven one stays out. It loses speed: spring-pop is not available on ffmpeg, and no video changes because the defaults are unchanged.

**Verified.** The four records are written by the tool and pinned; the selected tests (18627 passed) pass except 8 in `test_hf_ports.py`, which pinned the state before the records and are updated; the updated file passes (54).

**Not verified.** The root-cause mechanism of spring-pop's frame 15; whether any look-preserving fix exists; the parity look of the four ports on the ffmpeg engine against the HyperFrames engine.
