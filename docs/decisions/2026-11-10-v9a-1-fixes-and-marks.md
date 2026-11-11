## 2026-11-10: The keyword and highlight fixes and three drawn review presets: mark, sticker, nametag (V9a-1; spec V9a, decisions D1, D4, D5)

**Decision.**

- **The keyword card (`hf:spring-pop`) draws centred and larger, on two lines when it is long.** The stage's layout is now set inline in `build`
  (`position`, `left`, `top`, `width`, `height`, `display`, `alignItems`, `justifyContent`), so the placement never depends on the scoped style. The size
  comes from a pure function `fit(text, bandHeight)`: type up to 150 px on a 950 px width, split at the space nearest the middle of a text longer than 12
  characters, shrunk by 0.94 steps until the lines and the mark fit 84 percent of the band. "Name every dollar" gives two lines at 110.5 px in the default
  band (it was one line at about 68 px). The cause of the top-left placement is not proven: the inline layout removes the one cause that code can rule out,
  and the live leg (L2, the badge's box in `boxes.json`) is the proof.
- **The caption highlight (`hf:caption-highlight`) lights one word at a time.** A pure function `spans(words)` gives each word a monotone start and an end
  that is never later than the next word's start; the fade-out of a word ends before the next word's fade-in starts, and a word whose span is shorter than
  0.02 s never lights. Before, word N faded out after word N+1 lit up, so two words were lit during a transition.
- **Three review-only presets: `mark`, `sticker`, `nametag` (D1, OPEN-1 of the spec).** They live in a new `review_presets` section of
  `renderer-presets.json`, in the vocabulary's shape; `_vocab.load_vocabulary` merges them into the vocabulary the renderer reads, marked `review_only`, and
  `_align.read_script` refuses a script row that names one (`preset_review_only`). The shared vocabulary `shared/references/video-presets.json`, and so the
  script checker of `mkt-social-copy`, never sees them. The person adds them at review. Each is drawn by one `oh:` renderat page (`oh:mark`, `oh:sticker`,
  `oh:nametag`) on both engines; each is an overlay in the card band and may not cross the face. A mark is a hand-drawn underline, circle or arrow stroke
  drawn from fixed numbers (never random); a sticker is one of twelve glyphs drawn from paths written in the page (no emoji font, OPEN-9); a nametag is a
  lower third in the band. The timings are in the same file (`mark` 1.2 to 2.4 s, `sticker` 0.8 to 1.8 s, `nametag` 2.5 to 4.0 s).
- **`hf:spring-pop` stays the HyperFrames default for `keyword` (OPEN-5).**

**Cost and saving.** A script cannot ask for a mark, a sticker or a name tag; the person adds them at review. Saving: no Y change of `mkt-social-copy` and no
full test on the lab models, because the vocabulary is hashed into every case of that skill (principle 12). Moving a review preset into the script later is
a Y change of that skill and a package of its own.

**Alternatives rejected.** A script preset for each (a vocabulary and skill change, a full test). A colour emoji font for the sticker (a download, a new font
family the font guard refuses, a licence question: STOP A). `oh:mark` with mark `none` as the keyword default (the C10 sheets decide, not this package).
A change of any gate number or zone: none moved (`test_the_gate_constants_are_unchanged`).

**Departures from the spec text, each small.**

- The build script of `hf:spring-pop` makes each text line by cloning a prototype `span` of its own markup, not with `document.createElement`: the
  gsap lint refuses every `document.` access in a build script (`page_reach`), so the spec's call could not be written.
- A vocabulary that already holds a review-only preset of the same name (a merged vocabulary written back to a file) is read again without a clash; a name
  that the vocabulary holds as its own preset (not marked) is still refused `vocabulary_clash`.
- `oh:mark` takes `WIDTH = 950 - 68` for a circle as well as `950 - 130` for an arrow, and shrinks the text until the text, its mark's room and the pop's
  overshoot fit 86 percent of the band; the zone element it marks is the text plus that room, so the face check sees the stroke. `oh:sticker` is 220 px or
  70 percent of the band, whichever is less. `oh:nametag` shrinks until the plate also fits the band.
- `blocks/oh/nametag` and `blocks/oh/sticker` and `blocks/oh/mark` hold samples with fictional names only.

**Verified offline.** The pure functions of both ports (`fit`, `spans`, and the whole highlight `build` against a stub of the elements it touches) run in
node over the cases of the spec and 200 seeded noisy word lists; the three pages pass the determinism lint and keep the hash pins; the merged vocabulary,
the clash, the script refusal, the skill checker's refusal and both engine files are tested; the gate constants and the HyperFrames image's files are
unchanged. **Not verified:** how any of it looks (the C10 contact sheets, STOP D), why the keyword drew at the top left (live leg L2), determinism of the
renders at 4 and 2 cores (live leg L1), the pages in a real browser (the browser tests of `test_renderer_engine.py` now include the three presets and
skip where no Chromium is installed). The NOTICE rows of the two changed ports wait for the maintainer's word (STOP E).
