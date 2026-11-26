## 2026-11-26: Transitions at joins on the one engine; no count of the face; C5 restated (video P1a; plan v6 section 5)

**Status.** Approved by the maintainer (T3, answered). T1, T2 and T3 are recorded below word for word. This file is the P1a decision; P1b completes it.

**Context.** The references cut on words, with 2-4 frame effects tied to one place: a glitch into B-roll, a bloom on a reveal, a blur into a dark card (plan section 1). S0 drew glitch, bloom and zoom blur with ffmpeg at 3 frames per join, and the maintainer judged them at HyperFrames' level. Since 2026-11-24 nothing is refused for touching the face, and creative limits are advice (P0b). The plan's D4 asked for a count of the frames where code changes the speaker's face; T1 asked whether it stays.

**Decision.**
- D1. `beats.json` `transitions`: rows {id t1-t99, kind, word | beat}; default none (a hard cut and the theme's cutaway look). Kinds glitch, bloom, zoom_blur, blur_to_card, dip (ffmpeg, over the composed picture, under the captions) and slide, zoom (the cutaway page, for one beat). Any kind at any join; at most 99 (a closed document).
- D2. A transition never starts inside a word (validity): its lead frames inside a word are dropped, and an anchor inside a word moves forward to the first frame that is not.
- D3. The cutaway's entry look is per beat; the theme value is the default. `clip_transition` is refused only for slide or zoom on a clip.
- D4. Withdrawn for transitions (T1, "Sem contagem"): no count of the frames a transition changes on the face, no limit per join or per video, no advice code and no phrase about it, and no report of them in `check`. D4 of the video plan (2026-11-24, "Sim, com esses limites") is not enforced anywhere. (validate: allow english-only -- the maintainer's own words, quoted)
- D5. C5 now reads: the speaker's picture is changed only on the frames of the transitions and grades the edit list names (F12 and the offline framemd5 test prove it frame by frame). It corrects the C5 row of `providers/renderer/README.md` as stated since PF-a4a ("nothing drawn touches the face box"), which was stale: F5 proves a card over the face is drawn. This is validity, not a limit on the face.
- D6. `graph_too_long` (validity): a filter graph past 131071 bytes, the kernel's limit on one argument, is refused before any frame is drawn.

**The maintainer's answers**, verbatim.

- T1, asked: "Como deve ficar?" (validate: allow english-only -- the maintainer's own words, quoted), about how the face is treated by the transitions (glitch, bloom, zoom blur, blur to card, dip).
  Answer: "Sem contagem" (validate: allow english-only -- the maintainer's own words, quoted)
  Gloss: no count, no limit and no warning about the face for transitions; D4 of the video plan is withdrawn for transitions.
- T2 (the C10 look), asked: "As cinco podem entrar assim?" (validate: allow english-only -- the maintainer's own words, quoted)
  Answer: "Entram assim (Recomendado)" (validate: allow english-only -- the maintainer's own words, quoted)
  Gloss: all five kinds ship with their current defaults. The supervisor showed him that glitch is strong at intensity 1.0, and that a dip anchored on a word lands its black peak on the last frame of a clip cutaway.
- T3 (this text), asked: "Você aprova esse texto?" (validate: allow english-only -- the maintainer's own words, quoted)
  Answer: "Aprovo (Recomendado)" (validate: allow english-only -- the maintainer's own words, quoted)
  Gloss: he approves this text.

His D4 answer of 2026-11-24, "Sim, com esses limites" (validate: allow english-only -- the maintainer's own words, quoted), stands for what it covered then and is not carried over to transitions by this entry.

**Corrects** `docs/decisions/2026-11-24-video-p0-taste-caps.md` ("The gap": whether a code-written grade counts as an exempt frame is moot, no frame is counted) and `docs/decisions/2026-11-25-p0b-refusals-to-advice.md` (row 58: D4 is withdrawn, not a note for P1). `docs/decisions/2026-11-26-pf-b-retire-hyperframes.md` D5 said D4 would be enforced by counting in `_edl.py`; it is not.

**What it saves and what it loses (principle 13).** Saves: transitions without a second engine or page effects, drawn by code from closed rows, on 3-frame segments only (S0: +13.5 s of compose for 24 effect frames and a frosted card on the short case), and no count, advice code or card sentence to maintain. Loses: any guarantee about how many frames change the face; a video can have up to 99 transitions of 3 frames each, shown in the answer of `render` (`transitions_drawn`) and never limited or warned. That is the maintainer's choice. The graph limit refuses a post that would otherwise fail at the operating system with a less clear error.

**Verified and not verified.** Verified offline on the host's ffmpeg (not the image's 5.1): the five chains run, every output frame outside the rows has the md5 of the render with no rows, every frame inside differs, the same plan twice gives one md5 list, the caption layer is identical on a transition frame and the layer under it is not, the folded glitch equals the unfolded expression, and the cutaway page draws a beat's own look as the theme value would.

Verified live by the supervisor (image `openhora-renderer:28665c30436d` at bacf028, ffmpeg 5.1.9): `--check` ok with the five new filters found; renderer legs 1-3, 6 passed, F12 included, in 242 s; posts without transitions give the same sha256 as the PF-b3 image (port 8aa105e8..., renderat-only 8567dee0...); the sheet post with rows renders twice to one sha256; the real-size shape (195.9 s, 37 ranges) with 8 joins takes 604.1 s against 584.9 s without (+3.3%); captions stay sharp over every kind; no transition starts inside a word.

Not verified: the Portuguese wording of the two new left-out phrases; real recordings.
