## 2026-11-24: The taste caps leave the renderer and the review; only security and validity limits stay (video P0; plan v6 §3, D15)

**His words** (quoted, in the maintainer's own language; each line carries the english-only allowance).

- Principle: "Devemos apenas limitar por questoes de segurança, questoes criativa devemos liberar para o usuario fazer como lhe parecer melhor" (validate: allow english-only -- the maintainer's own words, quoted).
- D15, after that principle: "Liberar flashes também" (validate: allow english-only -- the maintainer's own words, quoted). The photosensitivity guideline (WCAG 2.3.1) was put to him and he declined it. No flash cap is added here under any name.
- His answers to the five questions of the spec (2026-11-24):
  - S1: "Remover agora (Recomendado)" (validate: allow english-only -- the maintainer's own words, quoted).
  - S2: "99 efeitos (Recomendado)" (validate: allow english-only -- the maintainer's own words, quoted).
  - S3: "Trocar por 10× (Recomendado)" (validate: allow english-only -- the maintainer's own words, quoted).
  - S4: "Manter padrões (Recomendado)" (validate: allow english-only -- the maintainer's own words, quoted).
  - S5: "Decidir no P5 (Recomendado)" (validate: allow english-only -- the maintainer's own words, quoted).

**Corrects** `docs/decisions/2026-11-10-v9a-3-effects.md`, section "What that costs, and the bounds in code". Its bound list (at most 6 review effects; a flash of at most 4 frames and a dip of at most 6, at most two of them in a video; mono and tint at most 4 s; two grades never share a word; the strength limits 0.85 and 0.18; a punch of 3 s at most and 1.25 at most) is replaced by the validity rules below. That entry is not edited.

**What changed.** A limit stays only when it is security (the face, VD12, the container boundary) or validity (what a filter, a document or the machine needs). A look is the person's. The 65 caps found were labelled one by one (the table below).

| # | Cap | Label | Action |
|---|-----|-------|--------|
| 1-4 | `EFFECTS_MAX` 6, `EFFECT_ID` `e[1-6]`, schema `maxItems` 6 and id pattern | taste | a closed-document ceiling of 99, ids `e1`-`e99` (S2) |
| 5 | `FLASHES_MAX` 2 (`too_many_flashes`) | taste (D15) | removed (S1) |
| 6, 7 | `FLASH_FRAMES_MAX` 4, `DIP_FRAMES_MAX` 6 | taste | removed: one frame per alpha of the ramp, cut at the range's end |
| 8, 9 | `GRADE_SECONDS_MAX` 4.0 s, `effects.grade_max_seconds` | taste (D15) | removed: mono and tint span their words, cut at the range's end |
| 10, 11 | `FLASH_ALPHA_MAX` 0.85, `TINT_ALPHA_MAX` 0.18 | taste | replaced by the validity clamp 0 to 1 |
| 12 | `zoom.push_in_max` 0.03 | taste | removed: finite, not negative, and `factor x (1 + push_in)` not past the zoom ceiling; `check_face` still refuses a box with no room |
| 13 | `zoom.factor_max` 1.25 | taste (S3) | replaced by `ZOOM_MAX` 10.0 on the factor, on `factor x (1 + push_in)` and on the punch level |
| 14 | `punch.max_seconds` 3.0 s | taste | removed: a punch spans its words, cut at its range's end and at the next punch |
| 15-19 | `punch.min_seconds`, `PUNCH_SHORT_SECONDS`, `grade_min_seconds`, each preset's `min_duration` and `max_duration`, `PUSH_MIN_SECONDS` | taste (S4) | kept as defaults; their owners are P2 (motion retune) and P8 (the director) |
| 20 | `effect_overlap` | validity for two colour-layer grades; taste for a pair with mono | narrowed: refused only when both grades are flash, dip or tint (they share the one `#fx` layer); mono is a filter and may share words |
| 21-23 | `punch_capped`, `grade_overlap`, `grade_short` | validity | kept (`punch_capped` now happens only at the zoom ceiling) |
| 24-26, 61-64 | `beats_max`, `ANIMATIONS_MAX`, `effect_repeated`, `effect_with_punch`, the checker's punch spacing, `preset_share_max` | taste | moved to P8 (the shared vocabulary and the skill's checker) |
| 27 | `STOCK_SLOTS_MAX` 6 | undecided (S5) | untouched; decided in P5 with the media conditions rule |
| 28-30 | the review's `EFFECTS_MAX`, `FLASHES_MAX`, `EFFECT_ID` | taste (twins of 1, 5, 2) | 99, removed, `e[1-9][0-9]?` |
| 31 | `EFFECT_ID_OUT` `[pe][0-9]{1,2}` | validity | kept (already admits `e1`-`e99`) |
| 32 | the `[:12]` cut of the render's dropped effects | taste | removed: no row is cut silently |
| 33, 34 | the `[:100]` cut of `left_out` and `LEFT_OUT_MAX` 100 | validity | `LEFT_OUT_MAX` 123 = 99 effects + 12 punches + 12 beats, and the cut reads it |
| 35 | the renderer's `effects_dropped` list bound 100 (`hf-page`, `render`) | security (a closed bound on what the host reads from the container) | resized to 111 = 99 + 12 |
| 36 | the `--push-in` help text "up to 0.03" | taste (text) | reworded |
| 37-57 | the card and caption zones, the 1560 caption line, `PIXEL_MIN_PSNR_DB`, `face_hit`, the platform length, fps, words, ranges, input seconds, frames, asset sizes, font and JSON bytes, render seconds, `MAX_EDITS`, the block contract, the block parameter bounds | security or validity | kept (row 41, D4's exempt frames, is not in code yet: P1) |
| 58-60 | `caption.max_words`, `max_chars`, `punch.factor` 1.12, `flash_alphas`, `dip_alphas`, `tint_alpha` | taste | kept as defaults; nothing chosen is clamped by a ceiling any more |

**The gap (S1).** The face-changing caps (rows 5-9) were the bounds the 2026-11-10 decision set as the price of comparing the face check against a reference with the grade applied. They go now, before D4 exists in code (P1). Between P0 and P1 a grade over the face has no length or count bound. That is accepted because a grade is a fixed filter that code writes from closed rows, so it can only recolour the picture; on HyperFrames every grade frame is still pixel-checked against the reference with the same grade, so nothing else can be drawn on the face; the ffmpeg engine never had a base-picture check; and the `aside` preset already puts a mono over the face for up to 12 s. P1 brings D4 into `_edl.py` and the C5 contract test, and ends the gap; P1's spec must say whether a code-written grade counts as an exempt frame.

**The validity rules that stay.** At most 99 review effects (a closed document; ids `e1` to `e99`, the width the runtime already reads). An alpha is clamped to 0-1. A zoom factor is 1.0 to `ZOOM_MAX` = 10 (the range of ffmpeg's `zoompan` filter zoom option, documented as 1 to 10 in ffmpeg's filter documentation; a figure from that documentation, not measured in this repository), and the face zones are still re-checked at the largest zoom. Two flash, dip or tint grades never share a word; a colour-layer grade that starts inside another is dropped (`grade_overlap`); an empty span is dropped (`grade_short`).

**What moves later.** Rows 24-26 and 61-64 to P8; row 27 to P5; row 41 (D4's exempt frames) to P1.

**Verified.** Offline tests: the grades have no length or count cap, the effects go up to 99, ids `e0`, `e01` and `e100` are refused, the zoom check has only validity bounds, the schema and the code agree and the removed constants are gone, an edit inside the old bounds keeps its rows and its filter text (literals produced at the base commit), the review's constants equal the renderer's, the render's dropped effects are not cut, the delivery document accepts 123 left-out rows and refuses 124, and the renderer's result schema accepts 111 dropped effects and refuses 112.

**Not verified.** Any render, in either engine. How longer or stronger grades look (C10). Whether the HyperFrames pixel check holds 30 dB on long grade spans: a longer grade puts more frames under that margin (the V9a-3 live leg L3 was never measured); a failure refuses the render, so it is safe, but it may block a long mono on HyperFrames until PF-b. Re-rendering an old task whose edit hit a removed cap gives different bytes; its `deliver` asks again, as today.
