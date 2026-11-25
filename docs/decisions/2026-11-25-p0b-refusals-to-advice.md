## 2026-11-25: Creative refusals become advice; only security and technical validity refuse (video P0b; plan v6 §3)

**His words** (quoted, in the maintainer's own language; each line carries the english-only allowance).

- On the face rule (2026-11-24): "Pode tirar a regra do rosto para tudo. Pode haver animacoes que exibam conteudos acima do rosto do usuario, e tudo bem" (validate: allow english-only -- the maintainer's own words, quoted).
- His principle (2026-11-24): "Devemos apenas limitar por questoes de segurança, questoes criativa devemos liberar para o usuario fazer como lhe parecer melhor" (validate: allow english-only -- the maintainer's own words, quoted).
- On the rules that are left (2026-11-24): "Mantenha apenas os 5 itens que voce citou. Porém para que a criacao do design nao fique muito solta sem as regras, vamos pensar numa forma de ensinar "boas praticas" para guiar as animacoes. Dessa forma se a pessoa quiser ela ainda pode criar da maneira que quiser, mas por padrao teremos alguma forma de guiar a criacao para o usuario nao precisar detalhar tudo a mao toda a vez" (validate: allow english-only -- the maintainer's own words, quoted).
- M6, which the maintainer answered himself (2026-11-25): "Manter todos (Recomendado)" (validate: allow english-only -- the maintainer's own words, quoted).

**The supervisor's record of M1 to M5** (not his words: the supervisor decided each by recommendation, from his earlier answers, and recorded it in the spec's "Supervisor review (2026-11-25)"):

- M1: keep `STOCK_SLOTS_MAX` (6) unchanged; P5 decides it. It bounds outbound fetches, so it is security by his own rule.
- M2: both page checks become advice (the line gate of second-contract pages, and the old engine's 30 dB face-pixel check), and this file corrects the PF-a2 trade record.
- M3: the validity ceiling for beats, punches and animations is 99 (the id width already in use); `effects_dropped` goes from 111 to 198 and `LEFT_OUT_MAX` from 123 to 297.
- M4: `pip_no_room` and `split_no_room` are drawn with a fallback placement over the face, plus advice.
- M5: `PUSH_MIN_SECONDS` moves into `renderer-presets.json` as `zoom.push_min_seconds` (5.0, adjustable), with no advice row; the other span defaults stay.

**Corrects**, each file named (a decision file is never edited; these are the corrections):

- `docs/decisions/2026-11-24-video-p0-taste-caps.md`: the labels of its rows 37-41 and 15-19. Rows 37 and 38 (zone sizes, the 1560 line) were "security"; they are placement defaults now. Row 39 (`PIXEL_MIN_PSNR_DB`) is advice. Row 40 is split: `face_hit` left with PF-a4a and `caption_below_line` is advice. Row 41 (D4) is moot for overlays. Rows 15-19 stay defaults, except that the `punch_short` drop is advice and `PUSH_MIN_SECONDS` moved into the presets.
- `docs/decisions/2026-11-08-v3b-2-hf-gates.md`: the 1560 refusal, `caption_not_drawn` and `face_pixels_changed` of the old engine's gates become advice. The gate still refuses a box in a zone that does not exist and a boxes file that cannot be read.
- `docs/decisions/2026-11-24-pf-a2-second-contract.md`: the trade's kept list ("the alpha face and caption gates (exact)") loses the line gate. The face half left with PF-a4a (his decision of 2026-11-24); the line gate (`caption_below_line` and `block_not_drawn` on the second contract's frames) is advice (`drawn_below_line`, `block_not_drawn`). `frame_not_rgba` stays a refusal.
- `docs/decisions/2026-11-23-v9b-3f-left-out-notice.md`: `pip_no_room` and `split_no_room` are no longer produced by any render. They stay in the closed lists, so that a stored delivery document still checks.
- VD12 (the 1560 line "is a gate on every engine") is recorded in `docs/decisions/2026-11-07-v0-short-video-hyperframes.md` (its table, row VD12) and the ffmpeg engine's refusal in `docs/decisions/2026-11-07-v1a-3-common-part.md`. Both are corrected: 1560 is the default line that captions are placed above; a caption below it is advice.

**What changed.** Every rule that refused or silently dropped a creative choice, and is neither security nor one of his five items (image size, fps 24-60, the platform's maximum duration, zoom up to 10x, render time limits, file and JSON size limits, and the 300 s input), stops refusing. It keeps its value as a default. When an edit goes past it, the render proceeds and the answer carries an `advice` row.

**The advice contract.** A list `advice`, at most 24 rows, one row per code, sorted by code. A row is `{code, value, default, count, ids?}`: `value` and `default` finite numbers, `count` an integer of 1 or more, `ids` at most 12 ids of the closed pattern (beat and effect ids, `c<k>` for a caption entry, `r<k>` for a kept range). The renderer writes only the code and the numbers (`providers/renderer/_advice.py`); the host turns the code into one sentence from a closed table (`runtime/deliver_document.py` `ADVICE_WORDS`, phrase keys `CARD_VIDEO_ADVICE_<CODE>` in `runtime/phrases_parts/p0b.*.json`). The container never writes the sentence. The row is read through a closed schema in `_docker.py` and again by `runtime/step_media.py` `_advice`, and a wrong row is `provider_output_invalid`, never echoed. The key is added to a render's answer, record, step result and delivery document only when it is not empty, so an edit inside every old bound keeps its bytes and its document hash.

The closed codes: `card_room_small`, `caption_room_small`, `caption_below_line`, `drawn_below_line`, `block_not_drawn`, `caption_not_drawn`, `face_pixels_changed`, `beats_over_default`, `punches_over_default`, `aside_repeated`, `aside_with_punch`, `text_over_default`, `beat_shorter_than_default`, `punch_short`, `pip_card_over_face`, `split_band_over_face`.

**The table (rows 1-28 in full, rows 29-59 summarised).**

| # | Rule | Now |
|---|------|-----|
| 1 | `face_box_leaves_no_room` (card room under 80 px or caption room under 120 px) | advice `card_room_small`, `caption_room_small`; `_layout.zones` clamps the band to its minimum |
| 2 | ffmpeg engine, renderAt caption below 1560 (`caption_below_line`) | advice `caption_below_line` (the lowest bottom, the band's bottom, `c<k>`) |
| 3 | second-contract pages, alpha on or below the line | advice `drawn_below_line` (M2) |
| 4 | old engine, caption box below the band | advice `caption_below_line` |
| 5 | `block_not_drawn` | advice `block_not_drawn`; the range is composed as drawn |
| 6 | old engine `caption_not_drawn` | advice `caption_not_drawn` |
| 7 | old engine `face_pixels_changed` (30 dB) | advice `face_pixels_changed` (M2); a face region too small to crop skips the range with no advice |
| 8 | `too_many_beats` over the vocabulary's `beats_max` (12) | advice `beats_over_default`; refused only past 99 |
| 9 | `too_many_punches` over 12 | advice `punches_over_default`; refused only past 99 |
| 10 | `effect_repeated` | advice `aside_repeated` |
| 11 | `effect_with_punch` | advice `aside_with_punch` |
| 12 | beat text over the preset's `max` | advice `text_over_default`; refused only past 240; control characters and empty text still refused |
| 13 | block parameter text over the block's `max` | as row 12; number bounds unchanged |
| 14 | `under_picture` for a side shorter than `min_duration` | kept with advice `beat_shorter_than_default`; 0 frames still dropped |
| 15 | `punch_short` under 0.4 s | drawn with advice `punch_short`; 0 frames still dropped |
| 16 | `ANIMATIONS_MAX` 12, ids `a1`-`a12` | ceiling 99, ids `a1`-`a99` |
| 17 | `BEATS_MAX` 12 as a bound | stays the default; `BEATS_CEILING` 99 is the bound |
| 18 | the catalogue's `animations_max` and `beats_max` | return the ceilings (99) |
| 19 | `pip_no_room` | drawn: a card 240 rows tall ending at `caption_bottom`, advice `pip_card_over_face` (M4) |
| 20 | `split_no_room` | drawn with the band `[caption_bottom - 120, caption_bottom]`, advice `split_band_over_face` (M4) |
| 21-28 | an empty punch span, `punch_capped`, `grade_short`, `grade_overlap`, `under_picture` with 0 frames, `overlap`, an empty caption chunk, `clipped` | stay (validity: nothing can be drawn, one colour layer, one beat track, zoompan's range) |
| 29-35 | image size, fps 24-60, the platform's maximum duration, `ZOOM_MAX` 10, render time limits, file and JSON sizes, the 300 s input | kept (his five items) |
| 36-46 | `words_max`, `word_chars_max`, `kept_ranges_max`, `frames_max`, `MAX_EDITS`, `EFFECTS_MAX`, `PARAMS_MAX`, `PARAM_TEXT_MAX`, number bounds, `CLIP_MAX_SECONDS`, `frame_not_rgba`, the alpha clamps, the result-schema bounds, the storyboard's 12 beats, the delivery document's bounds | kept (M6: bounds a closed document or the machine needs) |
| 47-49 | clean text, `STOCK_SLOTS_MAX` and the fetch budget, the container, `connect-src 'none'`, interception, hash pins, determinism records, escape lints, consent | kept (security; M1) |
| 50 | `PUSH_MIN_SECONDS` 5.0 | `zoom.push_min_seconds` in `renderer-presets.json`, same value, same bytes (M5) |
| 51-56 | the preset `max_duration` cut, the stretches to `min_duration`, `punch.min_seconds`, `grade_min_seconds`, the zone sizes, `caption.max_words` and `max_chars` | defaults, unchanged |
| 57 | the face rule | PF-a4a (already removed before this package started) |
| 58 | D4 exempt frames | moot for overlays; a note for P1 below |
| 59 | `check_script.py` and `video-presets.json` caps | P8's X release |

**What it saves and what it loses (principle 13).** Saves: no creative choice is refused, and the person sees, before approving the delivery, every place where a choice goes past a default. Loses: the guarantees "no caption below 1560", "every block and caption draws" and, with M2, "an admitted page never draws below its line" and "the old engine never changes the face's pixels". They become advice. They are not security under his principle. The residual: until PF-b retires the old engine, nothing refuses a page that draws over the face's pixels; the page is pinned code (VD3) that runs offline, with `connect-src 'none'`, interception, a hash pin and a determinism record, and it can only change the pixels it draws. The security limits (container, network, hashes, clean text, consent, closed bounds, the advice row's own schema) stay in code.

**Notes.** For P1: with the face rule gone for every overlay, whether D4 (exempt frames) stays at all is P1's question to him, with a recommendation. For P8: the best-practices guide that his third answer asks for, the director's use of it, the `choices` rows that record what the person chose, and the checker's caps turning into warnings are P8's (the spec's section 8); nothing under `skills/`, `shared/` or `contracts/` changed here.

**Verified.** The offline tests of the renderer and the runtime (the new `test_advice.py`, the renamed tests of rows 1-20, the byte-identity tests inside the old bounds, the delivery document and its phrases).

**Not verified.** No render, no image build, no live leg and no look: that a 99-beat edit, a punch on an aside, an over-long text and the M4 fallbacks render and look right is for the supervisor's live legs and C10. How a block draws a text longer than its tested `max` (overflow, cut by its band clip, or shrink) is for C10 and P2. The Portuguese wording of the phrases is for the supervisor.
