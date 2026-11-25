## 2026-11-25: The CSS of a port reaches the page (PF-a4d; plan video quality v6)

**Context.** The same synthetic post was rendered three ways: the five ported blocks on the old HyperFrames engine, the same ports on the ffmpeg engine under the second contract (a blocks copy whose `engines/ffmpeg.json` presets name `hf:caption-highlight`, `hf:count-up` and `hf:testimonial-card`), and the ffmpeg engine's `oh:` pages. On the ffmpeg engine the ports were drawn with no CSS: text at the top-left of its band in the default font and size, words run together ("Hey,quickstory", "Lastyearl"), no badge or card background, no theme colours. The determinism records of PF-a4b (decision `2026-11-25-pf-a4b-ports-records.md`) were therefore measured on unstyled pages.

**Root cause, with evidence.** `_hf_port.build_port_page` put the theme (`:root{...}`), `.hf-inst{...}` and the fragment's CSS in `@scope (#oh-inst) {...}` in a `<style>` inside the `<template id="oh-port-template">`. The vendored runtime mounts that template and, for every `<style>` of a mounted composition, rewrites each selector through its scoping function (`Ov` and `DP` in `hyperframe.runtime.iife.js`, `scopeRootSelectors: true`): `:root` becomes the composition root and every other selector is prefixed with `[data-composition-id="oh-port"] `. The rewritten rules went into `document.head`; the original stayed unused in the template. The dump of the mounted page's DOM (chrome-headless-shell `--dump-dom` of a built page, in the image) showed:

```
[data-composition-id="oh-port"]:not(:has([data-hf-inner-root])), ... {--c-accent:...;--font-text:...}
@scope (#oh-inst) {
    [data-composition-id="oh-port"] .stage { position: absolute; inset: 0; display: flex; ... }
```

Inside `@scope (#oh-inst)` a selector can only match below the scope root, and the composition root is above `#oh-inst`, so no rule of the fragment ever matched. The custom properties survived (they sit on the composition root, which the page does inherit from), which is why the gold of a figure and the badge colour showed in a few places and nothing else did. The old engine puts the same CSS in the page itself, outside any mounted composition, where the runtime leaves it as written (the runtime's page-level pass uses an empty namespace).

**Decision.**
- **The fix.** `_hf_port.build_port_page` puts the theme, `.hf-inst{...}` and `@scope (#oh-inst) {<fragment css>}` in the page's own `<style>` in the head (the one with the faces and the body rules), as `_hf_compose` does. The template keeps the instance element (clipped to the band: `contain:paint; overflow:clip`) and the port's script; the composition root keeps `font-family:var(--font-text)` for the font check. Every guard of the second contract is unchanged: the page policy, both lints, the band clip, the alpha gates and the font check. `PORT_HOST_VERSION` is 2, so the served digest of every port changed and every earlier determinism record expired, as designed.
- **Look, before and after.** Rendered again on the same post and the same blocks copy; frames extracted from the video and looked at. Before: figure at the top-left of the band, small default font, `trackedeveryexpense`, a flat yellow bar and a bare "A wise friend" for the quote. After: the figure centred and large, the label under it, the caption in uppercase with the highlighted word in a gold chip and spaces between words, the quote in its dark rounded card with the gold border and the avatar disc. Frames: `/private/tmp/claude-501/portcss-scratch/look/before-{20,120,340}.png` and `after-{20,120,340}.png`.
- **The records on the styled page.**

| Port | frames | seconds | served_sha256 |
|---|---|---|---|
| `hf:caption-highlight` | 150 | 38.06 | `e2d761a6f72cf0e3b0590e53e955ea569d16d4c3225f9edcc92bc733eae8d117` |
| `hf:caption-pill-karaoke` | 150 | 36.57 | `03f94e1ca96d36c11d0aafd9340392eed72811173a79abcd9475cd8fa929bff6` |

  Image `openhora-renderer:32ddaac36e86`, runtime_sha256 `491a22ffea0bf65cedc4389ddda9c31e2906c7adac05726333e4d4f422bf42ea`, 3 samples, 4 runs, 0 blocked, 2026-11-25.
- **Three ports fail now.** Run one after another on the styled page, each twice with the same result:
  - `hf:count-up`: `determinism_failed sample 1 frame 52` (it passed on the unstyled page). Its old record is removed.
  - `hf:testimonial-card`: `determinism_failed sample 1 frame 24` (it passed on the unstyled page). Its old record is removed.
  - `hf:spring-pop`: `determinism_failed sample 1 frame 1`, the same as in PF-a4b. Not edited.
  So the ffmpeg engine can draw only the two caption ports by name; `count-up`, `testimonial-card` and `spring-pop` are on the HyperFrames engine only again (`test_hf_ports.py`: `NOT_ADMITTED`).
- **What was found about the failures (count-up, sample 1).** Only the run that seeks the last frame first differs, and only in 10 of 66 frames (the frames of the pulse, where the `.group` scale is between 1 and 1.07). The DOM state at frame 52 is the same in all four runs (a debug read of `getAttribute("style")`, the computed transform `matrix(1.02, 0, 0, 1.02, 0, 0)`, the opacity and the text); the pixels differ at the edges of the glyphs, by a sub-pixel. So the cause is in the browser's raster state, not in the page's. Tried on count-up sample 1, host-side only, in the image, none of which fixed it: `gsap.config({force3D:false})`; `will-change:transform` on `#oh-inst` and `#oh-inst *` (it fixed that sample and made the caption ports fail at frame 1, so it was dropped); `transform:translateZ(0)`, `isolation:isolate` with `backface-visibility:hidden`, and `text-rendering:geometricPrecision` on `#oh-inst`; `text-shadow:none` (to test the text-shadow; the failure stays, and the testimonial card, which has none, fails too); the band clip replaced by `overflow:visible`, `clip-path:inset(0)` or `contain:paint` alone. The mechanism is not isolated.
- **What does not change.** The ffmpeg engine's preset defaults stay `oh:<preset>`. No port's `gsap.html` was touched.

**What it saves and what it loses (principle 13).** It saves a false proof: a record measured on a page with no style said nothing about the page a viewer would see, and the ffmpeg engine drew the ports with no look. It loses two admissions (`count-up` and `testimonial-card`) that were only valid for the unstyled page, so no card port is available on the ffmpeg engine until their pulse is made reproducible.

**Verified.** The bug reproduced in the real image (frames before the fix); the mounted DOM dumped (rewritten selectors); the fix looked at on the same frames; the two caption records written by the tool and pinned; the three failures reproduced; the selected tests and the validator (numbers in the pull request).

**Not verified.** The mechanism of the reverse-run difference of the pulse (count-up frame 52, testimonial-card frame 24, spring-pop frame 1); a full render of a post with the two admitted caption ports against the HyperFrames engine's look frame by frame (the frames above were looked at, not measured); the live legs (`WB_RENDERER_DOCKER_TESTS`) other than the scratch render.
