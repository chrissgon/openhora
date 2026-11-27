## 2026-11-27: A video chooses its caption style, its camera and its fonts (video P2a; plan v6 section 5 P2, R3-25)

**Status.** Approved by the maintainer: P2-1, P2-2, P2-6 and P2-7 are answered and recorded below.

**Context.** The caption block was always the engine's default (`_blocks.templates_for`, `_hf_host.prepare`), so the admitted `hf:caption-pill-karaoke` and `oh:caption` were never drawn. No runtime path set the zoom, the slow push-in or the caption position, although the renderer's `base` took the flags. Fonts came only from the identity's `brand-tokens` block or from the default (Inter and JetBrains Mono).

**Decision.**
- D1. The caption review's `caption` op names a caption block that the catalogue holds and the engine draws, and its position (`bottom` or `center`). `base` writes it as `edl.captions.block` and `edl.captions.position`; the key is absent when nothing was chosen, so the engine's default draws (today `hf:caption-highlight`, which stays the default). It is not a theme choice (R3-25). `{"op": "caption", "clear": true}` goes back to the default.
- D2. The `zoom` op sets any of three things for one video: the jump between shots (`mode`, `alternate` or `none`), how close the jump goes (`factor`), and the slow push-in (`push_in`, 0 turns it off). The checks are validity only, the ones P0 kept: factor 1 to 10, push-in 0 or more, factor x (1 + push-in) at most 10. The runtime checks the pair on the merged values with the presets' defaults, and `base` checks it again (`_edl.check_zoom`).
- D3. The `font` op sets one allow-listed font for one role (`display`, `text`, `mono`) for one video, with an optional weight (default: the allow-list row's). The brand identity is not changed; a role with no choice keeps the identity's font or the default. `theme.with_fonts` replaces that role's `--font` pair, so the renderer never sees a role twice, and the theme record's hash follows the effective fonts, so the approval sees the change.
- D4. A video that chooses nothing has the same review choices, the same `base` arguments, the same edit list and the same render bytes as before.
- D5. A choice made while the video waits at the delivery approval reaches the next `base`: the edit answers the open decision by code, the redo starts at `remap`, and `base` runs again (a test proves it with a caption and a zoom choice).
- D6. No new limit: every check is the catalogue's own names (a caption block of the engine), the filter's own range (zoom) or the font allow-list. Nothing caps how many choices, which block or which font.

**The maintainer's answers**, verbatim.

- P2-1 (which zoom settings a video may change; the options were all three in one op, or only the slow push-in): "As três (Recomendado)" (validate: allow english-only -- the maintainer's own words, quoted)
  Gloss: mode, factor and push-in, in one op.
- P2-2 (may one video use other fonts than the brand's; the brand file is not changed): "Sim, por papel (Recomendado)" (validate: allow english-only -- the maintainer's own words, quoted)
  Gloss: one allowed font per role for one video; the identity is untouched.
- P2-6 (the caption styles to offer, asked after the L1 sheet; the options were all three as they are with `hf:caption-highlight` staying the default, a change to one style first, or another default): "Os três, padrão atual (Recomendado)" (validate: allow english-only -- the maintainer's own words, quoted)
  Gloss: all three styles (`hf:caption-highlight`, `hf:caption-pill-karaoke`, `oh:caption`) are offered per video; `hf:caption-highlight` stays the default. A change to a style's page, or to the default, is P2c's.
- P2-7 (the look of the four new fonts in videos, asked after the L1 font sheet): "Ficam as quatro (Recomendado)" (validate: allow english-only -- the maintainer's own words, quoted)
  Gloss: Montserrat, Anton, Poppins and Oswald stay choosable per video through the `font` op; Inter stays the default.

**What it saves and what it loses (principle 13).** Saves: the choices without a new engine or page code, and the admitted caption styles finally reachable. Loses nothing in safety: every name is checked against the pinned catalogue, every number against the filter's range, and every font against the allow-list; the renderer checks them again.

**Verified and not verified.**
- Verified offline: each op sets, merges and clears; each refusal has a closed code; a stored review without the three keys reads and views; the constants equal the renderer's own; the `base` argv of a review with no choice has no new flag and the step's result no new key; each choice adds exactly its flags; a choice made at the delivery approval reaches the next `base`; `build_base` and `check` write and accept `captions.block`, and refuse a bad name (`bad_caption_block`); `templates_for` and `_hf_host.prepare` draw the block the edit list names; the host passes `--caption-block` through to the inner verb.
- Measured by the supervisor (leg L1, 2026-11-27): the branch image was built from fe09311; renderer live groups 1 to 3 passed (F13 took 242 s); a post with no choice rendered byte-identical to main's image (sha256 8aa105e8...); every caption style and font variant rendered twice with an identical sha256 (21 of 21); karaoke took about the default's time and `oh:caption` about 25 s less; no advice was returned.
- Not verified: sizing was tested on short lines only (the wrapping of long lines is not verified); real recordings.
