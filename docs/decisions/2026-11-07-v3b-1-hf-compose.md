## 2026-11-07: the composition generator of the HyperFrames engine (V3b-1; no measurement change, no skill changed, no lab run)

**What.** `hyperframes.py render` without `--base-only` now draws captions and beats. The page stage (`hf-page` with `--blocks` and
`--blocks-sha256`) stages and hashes the blocks like `ffmpeg.py`, and `_hf_compose.py` writes one root composition in the common image:
`index.html` (structure and numbers only), `vars.json` (every text, cleaned as `check_beats` cleans it) and `blocks/<ns>-<name>.html` for the
`renderat` blocks. A block is drawn with its `gsap.html` when the engine runs `gsap` (the fragment of `_gsap_lint.py`, inlined once per entry in an
instance clipped to its band with `contain: paint; overflow: clip` and scoped with `@scope (#hf-inst-N)`, its `build` run into a child timeline
that the root timeline places at the entry's start) and with its `renderat.html` otherwise (one full-frame iframe per block, the guard of
`_cdp.FREEZE_JS` and the theme set as the ffmpeg engine's driver sets it, driven by one getter/setter tween on the root timeline). The payload
functions (`pip_geometry`, `caption_data`, `beat_data`) moved byte for byte to the common `_payload.py`; `_frames` imports them back. The base
page's bytes and the ffmpeg engine's frames are unchanged. `_hf_page.py` is split into `check_target`, `build_parts`, `render_page`,
`write_files` and `write_page`, which the composer reuses. `hf_render.py` accepts a `blocks/` folder (at most 16 pages of at most 1 MiB, each
checked for fonts) and copies the three allow-listed font files into `fonts/` when a page uses them.

**Why.** Plan row V3b (conditions 1-9, decisions VD3, VD9, VD12, VD13, VD15 of `2026-11-07-v0-short-video-hyperframes.md`); V3b spec sections 5.1
to 5.12. The text rule of S2 (`vars.json` carries the text, `index.html` structure and numbers) and the one-timeline rule (a layer is inlined in
the root composition, because `--variables` reaches only the top-level composition) decide the design. The engine file
`blocks/engines/hyperframes.json` depended on the one-file measurement (spec 5.9), which waited on the
supervisor's local builds (STOP B); the measurement passed and the file is committed. A render that draws on the committed blocks is refused `gates_not_built` until V3b-2.

**Settled by the supervisor on the spec's recommendation (2026-11-07), not the maintainer's word.** OPEN-1: the one-file measurement passes when
both engines repeat their own bytes, the mean PSNR over all frames is at least 40 dB and no frame is below 30 dB. OPEN-2: the theme font `default`
maps to Inter 800 (display), Inter 500 (text) and JetBrains Mono 500 (mono) and `fonts_used` says so; a font id outside the allow-list, or a weight
that is not the file's, is `font_not_on_engine`. OPEN-3: `cutaway` and `pip` are not drawn on this engine (the engines file omits them, so a beat
of either is `preset_not_on_engine`, and a block of the `frame` band is refused the same way). OPEN-4 to OPEN-15 are for later parts.

**Measured.**

- The base page's golden, `providers/renderer/tests/golden/hf-page-base.sha256`, was computed on the untouched code (7e23eac) for the fixture of
  `test_hf_page.py` (`index.html` `788c6669...0893`, `vars.json` `2b934950...dd79`); after the split of `_hf_page.py` the same two values come out
  (run by the executor, offline, Python 3.12).
- The ffmpeg engine's render is unchanged: the same synthetic inputs (the kit's fictional post with every preset and the assets, `K.pipeline`,
  made once with the base) rendered by the base (7e23eac) twice and by this branch once, at the same time, through `_inner.py render` on the host
  (host ffmpeg and the local headless browser, no docker, `--jobs 2`), gave one sha256 for all three: `4ce2f18fa3ee4736...faed`, the seven blocks
  reported. No docker render of the ffmpeg engine was made here. In addition, two goldens computed on 7e23eac hold in
  `test_renderer_common.py`: the sha256 of the source of the three moved functions and the sha256 of the data they gave every caption chunk and
  beat of that post (29 captions, 6 beats).
- Offline tests: `test_hf_compose.py` (the composer, 38 tests including a `node --check` of every generated script), `test_gsap_lint.py` (73),
  the additions to `test_hf_page.py`, `test_hf_engine.py`, `test_hf_render_inner.py`, `test_renderer_common.py`, and the whole renderer test folder
  (684 passed, 6 skipped before the changes of the tests; the skips are the live tests and the ones that need images). Python 3.9 import test
  passes. See the PR body for the final counts.
- The one-file measurement (spec 5.9), run by the supervisor at 1b10907 on this Mac (arm64), synthetic inputs (412 output frames, 409 with a
  caption or a beat on), both engines drawing with the same font files, the HyperFrames engine from a temporary blocks folder with
  `runtimes: ["renderat"]` and the `oh:` defaults, `--cpus 4`: common image `openhora-renderer:aab28633881d` (`sha256:2ae02177...4f77`),
  HyperFrames image `openhora-hyperframes:cfe682d1c563` (`sha256:f260f120...7a4e`), `hyperframes` 0.9.19, all eight `render` flags present
  (D-help). Repeatability: ffmpeg engine twice `05b59f4c82d9...5d84` both; HyperFrames engine twice `695568005cf7...f73d` both. Stage seconds of
  one HyperFrames render: page 4.94, proxy 16.36, hf 43.31, encode 19.33; layers cuts, zoom, captions, beats; every block on `renderat`. PSNR of
  the HyperFrames final against the ffmpeg final: all 412 frames mean 40.33 dB, minimum 37.4 dB at frame 138; the 409 frames with a caption or a
  beat on, mean 40.311 dB, minimum 37.4 dB at frame 138. Verdict PASS (mean at least 40, minimum at least 30, each engine repeats its own
  bytes). Contact sheet (synthetic, not committed) sha256 `08c37409...68dd`, times 2.02, 4.12, 7.57, 7.58, 11.48 s, rows ffmpeg then
  hyperframes. Outcome: `blocks/engines/hyperframes.json` is committed (`renderat`; presets caption, keyword, list, number, quote to the `oh:`
  blocks) and `pin-blocks --confirmed` was run (blocks_sha256 `9e259583...1957`).
- The live test `test_hf_docker_live.py -k composed` (one sha256 at 4 cpus twice and at 2 cpus, result fields, no leftovers), run by the
  supervisor: 1 passed in 366.06 s.
- STOP C10, the maintainer's own words (2026-11-07): "Aprovo mas elas ainda estao simples demais. Porem acho que melhorar elas e questao de uma
  proxima etapa, onde irei trazer referencias de outros videos". The look is approved for merging V3b-1; the maintainer finds the blocks too
  simple, and richer blocks belong to a later stage built on reference videos (V7/V8 and V5's further blocks), not to V3b.
- No new ffmpeg stage was added, so no new stage needs a determinism measurement at 2 and 4 cpus: the page stage writes text, the encode stage is
  V3a-1's. The page's determinism is a byte comparison of two calls in `test_hf_compose.py`.

**Choices where the spec left room, and one place the code answered otherwise.**

- `hyperframes.GATES_BUILT = False`: until V3b-2 builds the face-box, 1560 and pixel gates, a render that draws is refused `gates_not_built`
  unless the blocks folder is the test folder of test mode (`RENDERER_TEST=1` and `RENDERER_BLOCKS_DIR`). The spec's rule is that nothing drawn
  reaches a render before the gates pass; without this check, committing `engines/hyperframes.json` on a PASS would open an unchecked path in
  production. V3b-2 removes the constant and its check.
- The child timelines of the gsap instances are created with `gsap.timeline()`, not `gsap.timeline({paused:true})` as the spec's sentence reads: in
  GSAP 3 a paused child placed in a parent is rendered at its end state (`paused(true)` sets its time scale to 0), whereas an unpaused child is
  driven by its parent, which is paused. Not run here (GSAP is only in the HyperFrames image); the live test shows it.
- `fonts/` is copied into the project only when the page or a block page names a font path (`fonts/` in `index.html`, or any block page), so the
  base-only page and the existing tests are unchanged. The base page names no font.
- `_gsap_lint.py` adds four rules the spec's contract implies without listing: the leading comment is inert (the token rules read what follows it),
  `<!--` is refused inside the fragment, the markup holds no text (`markup_text`), and the style holds no `@scope`, `:root`, `html`, `body` and has
  balanced braces (`style_scope`, `style_braces`), so a fragment cannot leave its `@scope`.
- A band with no height (a face box too high or too low for the card or caption band) is refused `band_too_small`; the ffmpeg engine has no such
  check and its page would set a negative height.
- `hf-page` with neither `--base-only` nor `--blocks` and `--blocks-sha256`, or with both, is a usage error (exit 2). The old test that expected
  `overlays_not_built` from the verb without flags became the test of that usage error (`test_hf_page.py`).
- `hf_render.check_fonts` also scans CSS for a pixel size followed by a word (a canvas font string), so a block's CSS such as `margin: 0 12px auto;`
  would be refused `font_not_allowed`. Not changed here; a port that meets it is written around it, and V3b-4 sees it in its live run.

**Not verified.** That HyperFrames serves `blocks/*.html` and `fonts/*.woff2` to iframes and seeks iframe content before it captures a frame; that a
getter/setter tween on the root timeline is rendered at every seek; that an unpaused child timeline is driven by the paused root in the
HyperFrames runtime; that `@scope` and `contain: paint` behave in Chrome headless shell 155 as in desktop Chrome; that a font that has not loaded
when the first seek runs (an iframe's `@font-face` loads lazily) draws in the allow-listed face; the PSNR between the two engines; any figure of the
real recording. Each is what the one-file measurement and the live test show, or the later parts' real-recording run.

**Saving and loss (principle 13).** The one place a check was chosen over another: the `gates_not_built` refusal saves nothing but costs one
constant and one line that V3b-2 deletes; what it saves is the unchecked production path between this part and the gates. The composer keeps all
text in `vars.json`, so a text value can never reach the page's markup or its scripts: it costs the second file and a driver that reads `V.inst` and
`V.ra`; nothing of safety is given up.
