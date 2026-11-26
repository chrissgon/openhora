## 2026-11-25: The seek of an admitted page repaints its instance (PF-a4e; plan video quality v6)

**Context.** After PF-a4d the ported blocks are drawn with their style, and three of the five (`count-up`, `testimonial-card`, `spring-pop`) failed the reverse run of the determinism test (`_admit.py`, `_admit_check.py`: 3 samples, each drawn 3 times forward and once last frame first, in fresh browsers, the four lists of frame hashes identical). Only the frames where a transform is fractional differed, and only at the edges of glyphs.

**Cause.** Raster history in Chrome. After a seek the DOM, the computed style and the layout are the same in every run (PF-a4d read them back); what differs is how the glyph edges were rasterised, and that depends on the frame drawn before. A run that starts at the last frame and walks back leaves different tiles than a run that walks forward.

**The fix.** `Page.seek_admitted` (`providers/renderer/_cdp.py`) runs `REPAINT_JS` after the seek, the font check and the page-state check, and before the screenshot: it sets `display:none` on `#oh-inst`, forces layout, restores the value, forces layout again, then waits two real animation frames. The tiles are dropped and the next frame draws the element from scratch, so the previous frame no longer reaches the pixels. The frame callbacks are the originals (`__HF_VIRTUAL_TIME__.originalRequestAnimationFrame`): the virtual-time shim replaces `window.requestAnimationFrame`, and a callback given to the shimmed one never fires. The constant has a comment saying so.

**Experiment (count-up sample 1, host side, in the image; the first four measured on the page before the repaint existed).**

| Tried | Result |
|---|---|
| `--num-raster-threads=1` | still `determinism_failed` |
| `--disable-font-subpixel-positioning` | still `determinism_failed` |
| `--disable-threaded-animation`, `--disable-threaded-scrolling` | still `determinism_failed` |
| `--disable-checker-imaging` | still `determinism_failed` |
| `--run-all-compositor-stages-before-draw` | still `determinism_failed` |
| other launch flags (raster and compositor switches) | no effect |
| `--deterministic-mode` | `block_failed` (the browser does not render under it) |
| hide and show `#oh-inst` with forced layout, then two original animation frames | all five ports pass every sample |

No digest pinned for a render changed: the `renderat`-only renders never take the admitted code path (so F1 and F3 are not reached) and the digests of F10 and F11 stayed the same.

**The registry pages.** An admitted registry page (hf runtime, our `_hf_host.build_page`) also screenshots through `seek_admitted`. Its root is `#oh-host` with the component mounted inside; it has no `#oh-inst`. Chosen: the repaint targets `#oh-inst` only, and on a registry page it reduces to the two-frame wait (the `if (e)` guard). Reason: the staged registry `spring-pop` (`hf-runtime/staged/spring-pop.json`, determinism record of 2026-11-24) passed the reverse run with no repaint, so no evidence asks for one; toggling the display of the runtime's own root could interact with what the runtime mounts there, and that is not tested. The staged entry is not activated and was not re-measured (it needs a local clone of the registry; see not verified). If a registry component fails the reverse run later, the fix is one constant with the element id chosen by the page kind (`oh-inst` for a port, `oh-host` for a registry page).

**The records, re-measured under the new image `openhora-renderer:e2db0ace7bd7`** (admission run twice, one after another, with `--confirmed`; each run rewrote `block.json` and ran pin-blocks; every per-sample digest of run 2 equals run 1's). Runtime sha256 `491a22ffea0bf65cedc4389ddda9c31e2906c7adac05726333e4d4f422bf42ea`, 3 samples, 4 runs, 0 blocked, 2026-11-25.

| Port | frames | seconds run 1 | seconds run 2 | served_sha256 |
|---|---|---|---|---|
| `hf:caption-highlight` | 150 | 49.15 | 48.54 | `e2d761a6f72cf0e3b0590e53e955ea569d16d4c3225f9edcc92bc733eae8d117` |
| `hf:caption-pill-karaoke` | 150 | 47.38 | 46.65 | `03f94e1ca96d36c11d0aafd9340392eed72811173a79abcd9475cd8fa929bff6` |
| `hf:count-up` | 198 | 56.42 | 56.45 | `bce38b01febd39193ef1264fe176f865b62248e636cc69c5ec9865435fa18ef7` |
| `hf:testimonial-card` | 189 | 55.52 | 55.43 | `0c2e4ed4778ee6b230adf3c22e66edb6c6cb05d6031397ef8c83c894b8a64a92` |
| `hf:spring-pop` | 162 | 47.87 | 48.23 | `5d838cc53820bcaa14ca6deae3ace0c5e5ff04e9600e91d395e404e612dd3125` |

The committed records are run 2's. All five ports are admitted on the ffmpeg engine now (`NOT_ADMITTED` of `test_hf_ports.py` is empty).

**Cost.** The repaint adds two animation frames and two forced layouts to every frame of an admitted page. The `caption-highlight` admission took 37.8 s before (PF-a4d: 38.06 s recorded) and 47.8 to 49 s after, about 25 percent more for a 150-frame measurement of 4 runs (roughly 17 ms per drawn frame).

**The render-time check.** A render accepts a port when its record exists and the served digest and runtime digest match (`_blocks`, `_admit`); the image tag is only validated as a tag. The capture JS is not part of the served digest, so an old record, measured without the repaint, would still be accepted at render time. With all five re-measured it is moot on this branch; a record made on another branch before this change is not invalidated by code, and should be re-measured.

**What it saves and what it loses (principle 13).** It saves three admissions that were lost, with a measurement that does not depend on the frame drawn before. It loses about a fifth of the admitted pages' capture speed and does not change what the F10 and F11 renders produce.

**Verified.** Five admissions twice in the real image, same per-sample digests; the offline test that the repaint runs between the checks and the screenshot; the selected tests, the live legs F1, F3, F10 and F11, the validator and the security scan (numbers in the pull request).

**Not verified.** The cost per frame on a long beat (measured on 150 to 198 frames only); the staged registry `spring-pop` under the repaint (the registry clone is not on this machine); that a render of a full post looks the same frame by frame as before (the determinism test compares runs with each other, not with the old pixels); that the repaint is enough for a port with other kinds of animation than the five.
