## 2026-11-26: One engine for renderer:video: the HyperFrames engine retired, "hyperframes" read as ffmpeg (PF-b; plan video quality v6; amends VD1 and V4)

**DRAFT.** This file is a draft for the maintainer (question B5). It is amended by the pull request that deletes the engine (PF-b3), which records B1-B5 word for word and the measured figures. Until then every line marked "pending" is open, and nothing that depends on it is written. PF-b1 (this pull request) ships only D2 and D3, the default and the alias; the old engine's code is untouched, so `hyperframes.py` still renders when called by its path.

**Context.** Since PF-a4 the ffmpeg engine draws the five kept ports under the second contract, and since PF-a4f (M2) its defaults for caption, keyword, number and quote are those ports, as on the HyperFrames engine. Every effect the old engine drew has a twin in the ffmpeg graph. The parity render (pending: section "Parity" below) compares a project configured for the old engine with the same project on ffmpeg.

**Decision.**
- D1. `renderer:video` has one implementation, `ffmpeg`. `hyperframes.py`, its image, its page, its gates and its pixel check are deleted (PF-b3, after B1-B5).
- D2. The class default is `ffmpeg` (`providers/resolve.py` `CLASS_DEFAULTS`). Shipped in PF-b1.
- D3. The name `hyperframes` is retired and read as `ffmpeg` wherever it is given: `media.renderer` in `runtime.json` (parsed as `ffmpeg`; the accepted hash is over the raw bytes, so no file is accepted again), `RENDERER_PROVIDER`, and a caller's implementation. It is never refused. The one table is `providers/resolve.py` `RETIRED`. Shipped in PF-b1.
- D4. A task re-rendered on the one engine has new bytes, so its `deliver` asks again (`stale`, or `deviation`), as for any re-render. Nothing is migrated.
- D5. The advice codes `caption_not_drawn` and `face_pixels_changed` keep their place in the closed lists with no producer (B3, pending).
- D6. The registry survey tools (`compat`, the tier-A wrapper, `fetch_registry.py`) and the HyperFrames image's lockfile are deleted; `hf-runtime/npm-pins.json` is the one pin of GSAP and the runtime (B4, pending). D19 is amended: GSAP and the runtime "are pinned in `hf-runtime/npm-pins.json`" instead of "come from the npm lockfile". The licence and its acceptance are unchanged.
- D7. The default font (B2, pending): either `default` draws Inter 800 / Inter 500 / JetBrains Mono 500 on ffmpeg, as the old engine did (recommended), or it stays the system font. In PF-b1 the first option is its own last commit, which is dropped if the answer is the second.

**Amends VD1** (`2026-11-07-v0-short-video-hyperframes.md`, section VD1). New text: "Engines are swappable behind one renderer-neutral edit list (`edl.json`, `beats.json`), which carries no executable text. One engine ships, `ffmpeg`; an engine added later passes the same contract tests, and the approval binds the bytes that come back. A project may name its engine by a key in `runtime.json`, accepted with `accept-config`; a retired engine's name is read as its successor."

**Amends V4** (`2026-11-10-v4-renderer-key.md`). D1: the key is `auto` or a shipped implementation (`ffmpeg`); `hyperframes` is accepted and read as `ffmpeg`. D2: the class default is `ffmpeg`. D3: a missing setup is refused `not_configured`; there is no other engine to replace it with. D4: still no migration (D3 and D4 above). D5: `block-params` is served by `ffmpeg.py`. D6: one implementation is listed. "What is refused": a variable naming `hyperframes` is no longer refused; a missing HyperFrames image no longer exists as a case.

**The maintainer's answers**, verbatim: B1 pending, B2 pending, B3 pending, B4 pending, B5 pending.

**Parity.** Pending (the supervisor's live legs L1-L3): inputs, the two themes, the frame-cell timing result, the PSNR per beat (full frame and overlay region), the effect peaks, the audio result and the seconds per render of both engines; the strips are kept outside the repository (project data stays out).

**What it saves and what it loses (principle 13).** Saves: one image (its build, its rebuilds, its pinned Chrome and npm tree), five CI legs on every video PR and nightly, about 10,500 non-test and 7,000 test lines, and one engine to keep at parity for every new effect. Loses: the face-region PSNR advice and the glyph-box caption advice (B3); a second engine to compare against when a picture looks wrong (the parity render is the last comparison, and git history keeps the engine); and every machine rebuilds the common image once.

**Verified and not verified.** Verified offline in PF-b1: the resolver default, the alias in the resolver and in the project configuration, the unchanged accepted hash, the unknown-name refusal. Not verified (supervisor's live legs): the look parity of the two engines, the frame-by-frame timing, the audio, the real-size render time, and the live default tests.
