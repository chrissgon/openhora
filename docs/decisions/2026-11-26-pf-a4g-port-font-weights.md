## 2026-11-26: A role's family on an admitted page carries every file of its typeface (PF-a4g; plan video quality v6)

**Context.** A parity render of `hf:testimonial-card` on the HyperFrames engine and on the ffmpeg engine showed the quote line in regular weight on the first and in bold on the second.

**Root cause, confirmed in code.** The port styles the quote as `font-family: var(--font-display); font-weight: var(--weight-text)` (`blocks/hf/testimonial-card/gsap.html`, line 8). The old engine (`_hf_compose.font_face_css`) declares one `@font-face` family per typeface ("Inter") with every theme file at its own weight, so display at weight 500 resolves to `inter-500`. The ffmpeg engine's admitted pages (`_hf_host.theme_fonts`, used by `_hf_port.build_port_page` and `_hf_host.build_page`) declared one family per role (`oh-display`, `oh-text`, `oh-mono`), each holding that role's one file, so `oh-display` held only `inter-800` and the browser drew it at 800: bold. (The `renderat` pages register `pv-<role>` the same way in `_cdp.SETUP_JS`; no `oh:` page mixes one role's family with another role's weight, so none is affected.) Any port or registry component that mixes a role's family with another role's weight on the same typeface drew the wrong face.

**Which ports.** Of the five, only `hf:testimonial-card` mixes them (its quote line: display family, text weight). `caption-highlight`, `caption-pill-karaoke`, `count-up` and `spring-pop` pair each family with its own weight and draw the same as before. Every `font-family` rule of the `oh:` pages pair a role with its own weight.

**The fix.** `_hf_host.theme_fonts(font_serve, edl_fonts, allow=None)` groups the served roles by the allow-list's `family`. A role's family `oh-<role>` declares its own file first and then the file of each other served role of the same typeface, each at that file's weight (one face per weight; two roles on one file are one face). A typeface that lacks a weight gives the browser's nearest face among that typeface's files only, the old engine's behaviour. With no allow-list, or a row with no `family`, a role declares its own file alone, as before: every golden of the default (system-font) theme is unchanged. `prepare` passes `_assets.font_allowlist()`. Nothing new is served: every face is a path `load_fonts` already read and checked against its sha256, so the allow-list check, the `font_hash` check and the page font check are untouched. The page font check lists every declared face (`fonts_spec`), forces each to load and requires the loaded set to be exactly the declared one, so the extra faces are held to it too. No new limit.

**What changes in bytes.** Only a theme that serves two roles of one typeface (the default theme: display `inter-800`, text `inter-500`). The port page and the registry page then declare four faces instead of two. No `renderat` page, no `FREEZE_JS`, no `oh:` page golden and no ffmpeg render of an `oh:` block changes. The offline goldens (default theme) are unchanged.

**The records.** The served digest of every port changed with `PORT_HOST_VERSION` 2 to 3 (the host's page changed shape), so all five records were re-measured with `ffmpeg.py admit-block --port hf:<name> --vocabulary shared/references/video-presets.json --confirmed` (3 samples, 4 runs, 0 blocked, 2026-11-26, image `openhora-renderer:b8702517828f`, runtime_sha256 `491a22ffea0bf65cedc4389ddda9c31e2906c7adac05726333e4d4f422bf42ea`; the tool wrote `block.json`, `pins.json` and `catalogue.json`; `pin-blocks --confirmed` after it changed nothing more).

| Port | frames | seconds | served_sha256 |
|---|---|---|---|
| `hf:caption-highlight` | 150 | 46.98 | `0d0abdd08a6f07a550d6aa8d229c6f190031f7309b59375b8b7e1bb8a30f7557` |
| `hf:caption-pill-karaoke` | 150 | 45.66 | `f7e96e5f830b01a7d84030a0f5a4f6d5cb4bc8e66acb1325cb226ccfe1c59217` |
| `hf:count-up` | 198 | 55.65 | `ee59c2d850b4970941170df182fd627d35c88e1a4883e5697cc38c7fdca88cc4` |
| `hf:testimonial-card` | 189 | 54.52 | `c51ada8dd2acbfad138f12d0e4dfe05ad6a0666d0a4f9ea0ededcd5a6a0d0659` |
| `hf:spring-pop` | 162 | 46.65 | `93daafab4257a2134fb5a73a554d30f3c9fb99bc8e603a49207991b926414297` |

**Tests.** `providers/renderer/tests/test_hf_port_fonts.py`: the declared faces, the fall-back to one file per role, the same-file case, the page font check's face list, and, where a headless Chromium is installed, the face the browser picks (`oh-display` at 500 is the text file, at 800 the display file). Before the fix the browser leg returned the 800 file for `oh-display@500`.

**What it saves and what it loses (principle 13).** It saves a wrong face on every mixed role-and-weight rule, with no limit added. It loses two extra font loads per page in the default theme (the already-served font files, decoded once) and a re-measure of five records.

**Not verified.** A live render of `hf:testimonial-card` on both engines compared frame by frame (the existing live kits draw no real-port parity; the face resolution was checked in the host's Chromium and the determinism of the page in the renderer image, not the quote's pixels); registry (`hf`) components, whose staged records were not re-measured and are not activated.
