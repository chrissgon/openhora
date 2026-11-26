## 2026-11-26: The ffmpeg engine's defaults for caption, keyword, number and quote are the ports (PF-a4f; plan video quality v6, question M2)

**Context.** After PF-a4e all five tier-B ports (`hf:caption-highlight`, `hf:caption-pill-karaoke`, `hf:count-up`, `hf:testimonial-card`, `hf:spring-pop`) have determinism records on the ffmpeg engine, so each is drawable there by name. Until now the ffmpeg engine's preset map named the `oh:` pages (`oh:caption`, `oh:keyword`, `oh:number`, `oh:quote`) as defaults, while the old engine (HyperFrames) named the ports. The spec of the second contract left the choice to the maintainer as M2.

**The question (M2), in plain words.** When a project renders on ffmpeg and a beat names no block, should the four presets be drawn by the `oh:` pages ffmpeg has always used, or by the same ports the old engine draws, so that a project keeps its look when the old engine is deleted (PF-b)?

**The sheet.** The supervisor showed the maintainer a side-by-side sheet: each port on the old engine, the same port on ffmpeg, and the `oh:` page on ffmpeg. PSNR of the port on ffmpeg against the same port on the old engine, average over each entry (a figure to read, not a gate): caption 27.4 dB, keyword 21.9 dB, number 24.6 dB, quote 22.8 dB. The differences seen were line wraps of a few caption chunks.

**His answer, verbatim:**

"As portas (Recomendado)" (validate: allow english-only -- the maintainer's own words, quoted)

The option read: on ffmpeg the defaults become caption `hf:caption-highlight`, keyword `hf:spring-pop`, number `hf:count-up` and quote `hf:testimonial-card`, the same as the old engine; when PF-b deletes the old engine, projects on today's default keep their look.

**The change.** `providers/renderer/blocks/engines/ffmpeg.json` `presets`: the four entries above; every other preset (`aside`, `cutaway`, `list`, `mark`, `nametag`, `pip`, `split`, `sticker`) is unchanged and stays an `oh:` page. `pin-blocks --confirmed` rewrote `blocks/pins.json` and the generated catalogue (`blocks_sha256` changed). No runtime code changed: the storyboard's `drawn_block` reads the engine's preset map, so it follows (spec 7.2). The `oh:` pages remain in the catalogue and selectable by name on ffmpeg; `hf:caption-pill-karaoke` stays selectable by name.

**What changes for projects that name ffmpeg.** A re-render of a post with a caption, keyword, number or quote beat that names no block now draws the port, so its bytes change. A stored render is not touched, and deliver asks the person again for the re-rendered file, as it does for any render whose bytes differ.

**Relation to PF-b.** PF-b deletes the old engine. Because both engines now name the same four defaults, deleting it removes no look from a project on the default. The open questions of PF-b (VD1, V4) about overlays need not be decided by this change.

**Cost (F1).** The live leg F1 (the default `lab.short()` render on ffmpeg, in the real image, one run each on the same machine) took 86.5 s with the ports as defaults against 44.0 s with the `oh:` pages on origin/main: about twice as long. Each caption chunk and each beat is now its own admitted page, drawn through `seek_admitted` with the repaint of PF-a4e. This is one measurement of one short post, not a benchmark.

**The tests.** No digest pinned for a render changed: no live test pins the sha256 of a default render (F1 to F11 compare renders with each other). What changed is the tests that assumed the committed ffmpeg defaults are `oh:` pages: `test_hf_ports.py`, `test_renderer_blocks.py`, `runtime/tests/test_media_animation.py` and `runtime/tests/test_media_storyboard.py` now expect the ports. The offline tests that are not about the ports (the render, storyboard, clip, pip and docker suites) draw with `renderer_kit.oh_blocks()`, a copy of the committed blocks whose ffmpeg engine names the `oh:` pages, through the test-mode folder (`RENDERER_TEST`, `RENDERER_BLOCKS_DIR`, `--blocks`) and, for the four modules that draw in this process, the fixture `oh_defaults` of `renderer_kit.py` (`pytestmark`); the suite's conftest.py is untouched, since every provider suite carries the same loopback guard. The modules that test the committed defaults keep the committed folder. They cannot draw the ports on the host: a port needs the image's gsap runtime and a determinism record at the image's hashes. One line of code changed: `ffmpeg.py` `verb_storyboard` stages `_blocks.blocks_dir()` as `render` already does (the committed folder unless test mode), so a storyboard test can bring its own folder; with no test mode it is the committed folder as before.

**Verified.** 20,029 offline tests of the selection and the loopback-guard test passed; the live legs `test_engine_contract_live.py` and `test_renderer_docker_live.py` passed in the real image (13 passed and 2 fixed and re-run, 17 skipped by the legs that are for the old engine); the validator, the security scan and the table check.

**Not verified.** That a full post looks right frame by frame against the old `oh:` look (the sheet compared ports with each other and showed the `oh:` page for reference; the PSNR is a figure, not a gate); the render time of a long post (one short post measured); the maintainer's real recording; `test_engine_default_live.py` (a leg outside the two the task names).
