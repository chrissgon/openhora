## 2026-11-28: A picture card over the speaker's blurred shot (video P4b; plan v6 §5 P4)

**Status.** Draft for the maintainer's approval (P4-9). P4-1, P4-2, P4-3 and P4-5 are answered and recorded below word for word. The real render of the card (P4-8) and the live legs (L1) are still to come; what they decide is marked pending.

**Context.** The references show pictures as cards over the speaker's own shot, blurred and greyed. The engine could blur a picture behind itself (the glass look) and blur the whole frame for three frames (`blur_to_card`), but not the speaker's shot under a beat. The plan's face STOP for this card (plan line 226) is moot: the face rule was removed for every overlay on 2026-11-24, and on 2026-11-26 the maintainer chose "Sem contagem" (validate: allow english-only -- the maintainer's own words, quoted) for transitions.

**Decision.**
- D1. A beat whose preset has a `backdrop` parameter set to `blur` makes ffmpeg blur, grey and darken the speaker's picture over the beat's frames, at `[base]`, under every card, picture and caption (`_edl.resolve_blurs`, `_media.blur_stage`, `_media.blur_filter`). The numbers are defaults in `renderer-presets.json` `backdrop.blur` (`sigma` 40, `darken` 0.5, `saturation` 0.5: the maintainer's "medio" look of P4-5); the bounds are validity only (`_edl.check_backdrop_config`).
- D2. The render's answer names each blurred span (`blurs_drawn`); C5 now reads "the frames of the transitions, of the grades and of the blurred spans it names". No count and no warning about the face (P4-1, "A").
- D3. `focus_card` is a review-only preset (`renderer-presets.json` `review_presets`), drawn by `oh:focus-card` (renderAt), with `stamp` (`none`, `x`, `check`; default `none`) and `backdrop` (`blur`, `solid`, `none`; default `blur`). The X is red (`#FF3B30`) and the check green (`#34C759`) by default. The script cannot ask for it until P8 (P4-2, "A"); the card is added at review. The card enters with no `blur_to_card` transition by default (that entry showed one dark frame in the L0 sheets); a review may still place the transition itself as today.
- D4. A post with no such beat has the same edit list, beats, argv and render bytes as before (checked on the kit's post: the dry-run answer, the compose graph and the timeline are identical to main's).
- D5. Only the card's `stamp` is in this package. The `cross` value of the `mark` preset and the `cross` sticker glyph (P4-3, "D") and the carousel (P4-4, "A") are later packages (P4c, P4d, P4e).

**The maintainer's answers**, verbatim.

- P4-1 (the blur over his face), asked whether the blur gets the same treatment as the aside's black and white and the transitions: no count and no warning, the render only listing the blurred spans.
  Answer: "A" (validate: allow english-only -- the maintainer's own words, quoted)
  Gloss: no count, no warning; the render lists `blurs_drawn`.
- P4-2 (how the containers reach a video), asked whether the new containers are review choices now and the script gets them in P8.
  Answer: "A" (validate: allow english-only -- the maintainer's own words, quoted)
  Gloss: review choices now; the shared vocabulary and the skill that cites it are untouched until P8.
- P4-3 (where the X goes), asked after a mockup.
  Answer: "D" (validate: allow english-only -- the maintainer's own words, quoted)
  Gloss: the card's `stamp` (`none`, `x`, `check`), the `mark` value `cross` and a sticker glyph `cross`. Only the card's stamp is in P4b; the mark and the sticker are P4c.
- P4-4 (the carousel), recorded here because it shapes the split.
  Answer: "A" (validate: allow english-only -- the maintainer's own words, quoted)
  Gloss: P4d and P4e, not this package.
- P4-5 (how the picture card looks), asked on the L0 sheets.
  Answer: "1. Desfoque medio. 2. X vermelho, e verde para o check 3. Eu desfocado" (validate: allow english-only -- the maintainer's own words, quoted)
  Gloss: the blur look "medio" (L0 numbers: `sigma` 40, `saturation` 0.5, `darken` 0.5, which are the parameters of `blur_filter` one for one); the X red and the check green; the card's default background is the blurred shot (`blur`).
- P4-8 (the real render), pending the supervisor's live leg L1.
- P4-9 (this text), pending.

**What it saves and what it loses (principle 13).** Saves: the reference's most common container without a new engine or page contract. Loses nothing in safety: the page is a renderAt page (freeze, lint, CSP), the picture was approved by hash and scanned (P9-a), and the blur is a filter with constants only, in the offline container. What the blur changes of the speaker's shot (the face included) is the person's choice per card, and nothing is limited or counted, as with the aside and the transitions.

**Verified and not verified.**
- Verified offline in the executor's clone, on the host's ffmpeg and headless browser: the rows of `resolve_blurs` (default, `solid`, `none`, clipped, dropped); the bounds of `check_backdrop_config`; the compose graph (the stage sits at `[base]` under the splits, cards, transitions and captions, every label `bk_`, constants only); frame by frame, every frame outside a span equals the render with no blur and every frame inside equals `blur_filter` applied to the plain picture, a card and a caption drawn over the span are the same bytes as without the blur; with `saturation` 1 the filter text is the `blur_to_card` text; the page is pure, lints, keeps the card inside the side margins and the look's height, draws the stamp only when asked and only after its time, in the picked colours; `blurs_drawn` passes the render result's schema; `colorchannelmixer` is required by the image check; the dry-run of a post with and without a card.
- Not verified here (the supervisor's L1): that the image's ffmpeg draws `blur_filter` as the host's does (`selfcheck`, F14); the cost of the blur per frame in the image (the L0 host timing was about 44 ms a frame for the blur alone); one sha256 of a render of a post with no P4 beat on the branch image and on main's image; the card and its stamp on a real recording with a real face; F14's seconds in CI; the maintainer's look on the real render (P4-8). The image tag changes with this package (`renderer-presets.json` and the Python files are in the manifest): the maintainer rebuilds his renderer once, after the last image-changing P4 package.
