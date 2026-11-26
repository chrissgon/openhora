## 2026-11-26: One engine for renderer:video: the HyperFrames engine retired, "hyperframes" read as ffmpeg (PF-b; plan video quality v6; amends VD1 and V4)

**Status.** Approved by the maintainer (B5, answered). This file is the PF-b1 draft completed in place by PF-b3, the pull request that deletes the engine, and it records B1-B5 word for word. PF-b1 shipped D2, D3 and D7 (the default, the alias and the font); PF-b3 ships D1, D4, D5 and D6 (the deletion). The live figures of L4 and L5 are added below without changing any decision.

**Context.** Since PF-a4 the ffmpeg engine draws the five kept ports under the second contract, and since PF-a4f (M2) its defaults for caption, keyword, number and quote are those ports, as on the HyperFrames engine. Every effect the old engine drew has a twin in the ffmpeg graph. The parity render (pending: section "Parity" below) compares a project configured for the old engine with the same project on ffmpeg.

**Decision.**
- D1. `renderer:video` has one implementation, `ffmpeg`. `hyperframes.py`, its image, its page, its gates and its pixel check are deleted (PF-b3).
- D2. The class default is `ffmpeg` (`providers/resolve.py` `CLASS_DEFAULTS`). Shipped in PF-b1.
- D3. The name `hyperframes` is retired and read as `ffmpeg` wherever it is given: `media.renderer` in `runtime.json` (parsed as `ffmpeg`; the accepted hash is over the raw bytes, so no file is accepted again), `RENDERER_PROVIDER`, and a caller's implementation. It is never refused. The one table is `providers/resolve.py` `RETIRED`. Shipped in PF-b1.
- D4. A task re-rendered on the one engine has new bytes, so its `deliver` asks again (`stale`, or `deviation`), as for any re-render. Nothing is migrated.
- D5. The advice codes `caption_not_drawn` and `face_pixels_changed` keep their place in the closed lists with no producer (B3, answered): `runtime/step_media.py` `ADVICE_CODES` keeps both, as it keeps `pip_no_room`, so an old task's advice still reads. D4 of the video plan (face-changing transitions and grades) is enforced in P1 by counting in `_edl.py`, not by a pixel check.
- D6. The registry survey tools (`compat`, the tier-A wrapper, `fetch_registry.py`) and the HyperFrames image's lockfile are deleted; `hf-runtime/npm-pins.json` is the one pin of GSAP and the runtime (B4, answered). D19 is amended: GSAP and the runtime "are pinned in `hf-runtime/npm-pins.json`" instead of "come from the npm lockfile". The licence and its acceptance are unchanged.
- D7. The default font (B2, answered): `default` draws Inter 800 / Inter 500 / JetBrains Mono 500 on ffmpeg, as the old engine did. Shipped in PF-b1 as its font commits.

**Amends VD1** (`2026-11-07-v0-short-video-hyperframes.md`, section VD1). New text: "Engines are swappable behind one renderer-neutral edit list (`edl.json`, `beats.json`), which carries no executable text. One engine ships, `ffmpeg`; an engine added later passes the same contract tests, and the approval binds the bytes that come back. A project may name its engine by a key in `runtime.json`, accepted with `accept-config`; a retired engine's name is read as its successor."

**Amends V4** (`2026-11-10-v4-renderer-key.md`). D1: the key is `auto` or a shipped implementation (`ffmpeg`); `hyperframes` is accepted and read as `ffmpeg`. D2: the class default is `ffmpeg`. D3: a missing setup is refused `not_configured`; there is no other engine to replace it with. D4: still no migration (D3 and D4 above). D5: `block-params` is served by `ffmpeg.py`. D6: one implementation is listed. "What is refused": a variable naming `hyperframes` is no longer refused; a missing HyperFrames image no longer exists as a case.

**The maintainer's answers**, verbatim.

- B1, asked: "Você aceita esse visual para os vídeos que já existem?" (validate: allow english-only -- the maintainer's own words, quoted)
  Answer: "Aceito (Recomendado)" (validate: allow english-only -- the maintainer's own words, quoted)
  Gloss: he accepts the one engine's look for existing videos; the known differences are text edges, tint about 1 level darker, punch resampling, and audio shifts of at most 0.33 ms.
- B2, asked: "Qual fonte o motor único deve usar nesses projetos?" (validate: allow english-only -- the maintainer's own words, quoted)
  Answer: "Inter, como antes (Recomendado)" (validate: allow english-only -- the maintainer's own words, quoted)
  Gloss: the default theme draws Inter and JetBrains Mono on ffmpeg (B2 (a)), so the font commits of PF-b1 stay.
- B3, asked: "Os dois avisos antigos podem sair junto com o motor?" (validate: allow english-only -- the maintainer's own words, quoted)
  Answer: "Podem sair (Recomendado)" (validate: allow english-only -- the maintainer's own words, quoted)
  Gloss: `face_pixels_changed` and `caption_not_drawn` lose their producer; the codes stay in the closed lists.
- B4, asked: "Essas ferramentas e o lockfile antigo podem sair?" (validate: allow english-only -- the maintainer's own words, quoted)
  Answer: "Podem sair (Recomendado)" (validate: allow english-only -- the maintainer's own words, quoted)
  Gloss: the `compat` verb, the tier-A wrapper, `fetch_registry.py` and the old HyperFrames lockfile are retired; `hf-runtime/npm-pins.json` is the one pin, and D19's wording is amended (D6).
- B5, asked: "Você aprova esse texto?" (validate: allow english-only -- the maintainer's own words, quoted)
  Answer: "Aprovo (Recomendado)" (validate: allow english-only -- the maintainer's own words, quoted)
  Gloss: he approves this decision text; the L4 and L5 figures are added without changing any decision.

**Parity.** The supervisor's live legs on the PF-b1 branch (synthetic inputs only; the strips stay outside the repository). Timing is equal frame for frame, 1184 frames. Whole video, old engine against ffmpeg on the default theme: mean 38.9 dB, minimum 31.0 dB. The testimonial-card quote, which drew bold on the default theme, is fixed by #849 and the follow-up of PF-b1. The 300 s synthetic post on the default limits renders in 903 s with a peak scratch of 631 MiB of 2048 and an estimate of 1.27 GB. Seconds on the T1 post: old engine about 290 s, ffmpeg about 220 s.

**What it saves and what it loses (principle 13).** Saves: one image (its build, its rebuilds, its pinned Chrome and npm tree), five CI legs on every video PR and nightly (about 27 runner-minutes per run that started them, from the CI-1b figures; the saving is runner-minutes, not wall time: see L5 below), 10,470 non-test and 7,950 test lines deleted (428 added or edited in all, 259 of them tests), about 400 tests, and one engine to keep at parity for every new effect. Loses: the face-region PSNR advice and the glyph-box caption advice (B3); a second engine to compare against when a picture looks wrong (the parity render is the last comparison, and git history keeps the engine); and every machine rebuilds the common image once more (its manifest lost three modules).

**What PF-b3 kept that a reader might expect gone, and what it dropped that the spec had not named.** Kept: the whole second contract and the five ports with their records (`blocks/hf/*`, `hf-runtime/` staged entries, shims and `npm-pins.json`), `base_graph` and its keyword options, `_blocks.SOURCES` and `HF_KEYS`, and `usable()`'s branch for an engine that runs `gsap` without `hf` (the tests' fictional engine `twin` runs on it, so removing it would break kept tests; the regenerated catalogue is the same either way). Contract schema 1 stays frozen in `contract_kit` so the two committed reports still validate; a new report is schema 2. Dropped beyond the spec's table: `providers/renderer/tests/test_renderer_encode.py`'s `proxy` and `encode` tests (the verbs they tested are gone; its recording-check and mount tests stay), `test_hf_cutaway.py` whole (PF-b2 had already moved its kept tests), the `hf-page` schema row and its tests, `contract_kit.planted_blank`, and the live legs F4, F8, M3 and M6.

**Verified and not verified.** Verified offline in PF-b3: the selection of tests (`select_tests.py --base origin/main`) green through the slots, the validator at zero errors, `pin-blocks --confirmed` changing the catalogue only in the engine lists, `asset_kinds_by_engine` and the pins of the deleted engine file, and the kept tests unchanged in what they assert. Verified live by the supervisor on the PF-b1 branch (L1 to L3): the parity render and its figures above, the frame-by-frame timing, the audio shifts of at most 0.33 ms, the 300 s input under the cap, B1 and B2.

Verified live on PF-b3's commit cd85fa7 (L4, all passed): the common image `openhora-renderer:b747ff06dee1` rebuilt in about 99 s; `ffmpeg.py --check` ok (ffmpeg 5.1.9, Chrome for Testing 155.0.8059.39, libass true); the renderer legs of `test_engine_contract_live.py` (f1, f10, f11, f2, f3: 5 passed, 761 s); `test_engine_default_live.py` (4 passed, 338 s); `runtime/tests/test_media_clip_live.py` (3 passed, 177 s); drawing equality against the PF-b1 image (the port-defaults short render and a `renderat`-only short render each have the same sha256 in both images, 8aa105e8... and 8567dee0...); and `doctor.py --remove-old-images --dry-run` lists the old `openhora-hyperframes` tags (13 on the supervisor's machine) and removed nothing.

L5: PF-b3's own CI run (the checks workflow) took 13 min 38 s of wall time, against 12.5 min after CI-1b. The critical path is now `live / renderer 3 of 3` at 13 min 18 s, so wall time did not drop; the saving is the five HyperFrames legs' runner-minutes (about 27 per run) and one image, not speed.

Not verified live: the machine-only legs of the live file (`WB_ENGINE_MAC_LEGS`), which hold the `.job-` folder check and the schema-2 report writer.
