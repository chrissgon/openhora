## 2026-11-28: A full-screen keyword card, an X over a phrase, a big X sticker, and no solid backdrop (video P4c; plan v6 §5 P4)

**Status.** Draft for the maintainer's approval (P4-9). P4-6 is answered and recorded below word for word. The real render (P4-8) and the live leg (L2) are still to come, and a survey of registry animations may still change some look constants; they are kept in one place each (`renderer-presets.json` `presets.title_card.looks`, the `CROSS` constants of `oh:mark` and `oh:sticker`).

**Context.** The references show one keyword large on a full-screen card, an X stamped over a wrong phrase and a big X alone. P4b built the blurred shot and the picture card; this package adds the text card and the X, and takes the solid backdrop out of every P4 preset after the maintainer saw P4b on the real renderer.

**Decision.**
- D1. `title_card` is a review-only text layout drawn by `oh:title-card` (renderAt): `text` (40 characters), `note` (the small line above, 60), `style` `a`, `b` or `c` (default `c`), `color`, `backdrop`. The three styles are the maintainer's A, B and C; their numbers are those of the picked file. It is not the video-title layer removed with V9a-2 (D9). Two-line phrases are sized by the largest-fit loop, so a phrase fills its box as a single word does.
- D2. `backdrop` is `blur` (the default, the "medio" look of P4b) or `none` (the sharp shot), for every P4 preset. `solid` is removed: from `_edl.BACKDROPS`, the `focus_card` and `title_card` presets, the `oh:focus-card` block and page, the tests and the docs. A beats file that still asks for `backdrop: "solid"` is refused with the existing closed-value code `bad_choice`; it is never mapped to another value (`test_a_beats_file_asking_for_a_solid_backdrop_is_refused_with_the_closed_value_code_and_never_mapped`). P4b's merged decision file (`2026-11-28-p4b-focus-card-blur.md`) is not edited: this entry supersedes its D3 on that one value.
- D3. The P4d carousel will also have only `blur` and `none`.
- D4. `mark` gains `cross` (two diagonals over the words) and `strike` (one stroke through them); `sticker` gains the glyph `cross` (a big X alone, red or the accent colour through its `color` parameter, default the accent colour). The sticker's colour is read from the picked file's look block (accent); its note said red, so the red is one `color` value away.
- D5. A post with no P4 beat has the same edit list, beats, argv and render bytes as before: the code path for it is untouched (the new key `blurs` appears only on a timeline with a blurred span, as in P4b).

**The maintainer's answers**, verbatim.

- P4-6 (how the title card looks, and the X), asked on the L0 sheets.
  Answer: "Os textos com o fundo em blur ficaram melhores que o fundo solido. Sobre os riscos, os dois tipos ficaram bons, seja num formato de X ou o risco por cima da palavra. O X em cima do rosto tambem ficou bom 1. Todos os estilos de titulos ficaram bons, acho que nao há motivo para manter apena 1 2. Fundo sempre será um blur, nao uma cor lisa apenas por baixo 3. Acho que podemos manter todos os tipos, porque precisamos escolher apenas 1?" (validate: allow english-only -- the maintainer's own words, quoted)
- Follow-up.
  Answer: "Pode, padrão C, podemos deixar a opcao de cor lisa, mas o padrao será blur" (validate: allow english-only -- the maintainer's own words, quoted)
- After seeing P4b on the real renderer, superseding the solid option above.
  Answer: "Pode fazer o merge, mas quero mudar algo. A cor lisa realmente não é boa, podemos tirar ela das opções. Deixamos apenas o blur. Tiramos a cor lisa de todas as 3 animacoes que tratamos antes tambem" (validate: allow english-only -- the maintainer's own words, quoted)
- Asked whether "sem fundo" stays, with the options "Só blur" or "Blur e sem fundo".
  Answer: "Blur e sem fundo" (validate: allow english-only -- the maintainer's own words, quoted)
- P4-8 (the real render), pending the supervisor's live leg L2.
- P4-9 (this text), pending.

**What it saves and what it loses (principle 13).** Saves: the reference's keyword card and X without a new engine or page contract, and one fewer backdrop value to draw and test. Loses nothing in safety: the pages are renderAt pages (freeze, lint, CSP), draw only the person's own text, and the blur is the P4b filter. Removing `solid` loses a look the maintainer chose to drop.

**Interpretations the picked file left open.** The title card's note sits above the keyword with a gap of half the note's size, and the keyword and note are centred as one group; the loop stops at 12 px so that it always ends; `cross` strokes ease out cubic; `strike` is one cubic curve inside 52 to 66 percent of the text height; the mark's text is capped at 118 px and its band comes from the card zone as for the other marks (the file's `top` and `band_h` were the L0 sheet's own frame); the sticker's dark outline is the theme's background colour.

**Verified and not verified.**
- Verified offline in the executor's clone, on the host's headless browser: the title card page is pure, lints, keeps the keyword inside the safe margins and the look's box for the three styles and for a word, a 40-character phrase, an accented phrase and a long one; the colours and the small line of each style; transparency for `blur`, `none` and the default; the timeline row for a title card; the `mark` and `sticker` paths are fixed and finite and hold their room; `solid` is refused by the vocabulary check for both presets.
- Not verified here (the supervisor's L2): the title card, the X and the sticker on a real render over a real shot; F14 with a title card; the image tag changes (`renderer-presets.json`), so the maintainer rebuilds once after the last image-changing P4 package.
