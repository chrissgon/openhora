## 2026-11-11: The cutaway is a hard cut, and a picture that is not vertical is drawn over a glass background (V9d)

**Decision.** `renderer-presets.json` `presets.cutaway.looks.transition` is `"cut"` instead of `"slide"`, and the page `blocks/oh/cutaway/renderat.html` draws a glass layout for a picture that is not vertical.

**The maintainer's words, 2026-11-11, translated:**

> "the transition is not good. Too slow; you can clearly see something being pulled in from the right. The transition must be so smooth that you do not even notice it exists."
> "Hard cut."
> "For images that are not vertical, instead of leaving them filling the whole background, make them smaller and centred, and make the rest a glass layer with the predominant colour. That effect is better for the person to see the content of the image."

**The measurements behind it** (69 reference Shorts): transitions are 658 hard, 21 soft and 9 fade to black, so 96 % are hard cuts; 144 of 180 cutaway entries sit within 1 s of a measured hard cut; none of them slides.

**What the page does.**
- `"cut"`: the picture is on screen at the first and the last frame of the beat (no offset, opacity 1, scale 1), and the label chip is there at once. The `slide` and `zoom` branches stay as values a theme may pick.
- Let r be the decoded picture's width over its height. With `fit: cover` and r at most `glass_ratio_max` (0.8) the picture fills the frame as before. Otherwise (r above 0.8, or `fit: contain`) the glass layout is drawn on one canvas: the picture blurred and enlarged to cover the frame with room for the blur at every edge, a layer of the picture's predominant colour over it, and the whole picture centred, at most 950 px wide (the frame's safe margins of 65 px) and at most 1700 px high, with rounded corners and a soft shadow.
- The predominant colour is computed in the page: the picture drawn to 32 x 32, each channel cut to 16 steps, near-white (every channel 235 or more) and near-black (every channel 24 or less) samples skipped, the most frequent step wins (the first to reach a count wins a tie). With nothing left, the theme's `--c-bg` is the tint.
- The values are in `presets.cutaway.looks` so a theme can tune them: `glass_blur_px` 48, `glass_tint_alpha` 0.45, `glass_ratio_max` 0.8, `glass_radius_px` 24.

**Not changed.** `shared/references/video-presets.json` and `.md` (the preset keeps `fit: cover|contain`, default `cover`), every `hf:` block, the runtime and the skills. A clip asset is out of scope: the page does with it what it did.

**Not verified here.** Only the host's headless browser drew the page, on flat-colour pictures the test writes. The look on a real picture, the cost per frame of the canvas blur, and the render on the container's browser are the supervisor's live legs. The page is pinned again (`pin-blocks --confirmed`).
