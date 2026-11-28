## 2026-11-28: One added animation may take several pictures (video P4e; plan v6 section 5 P4)

**Status.** Package P4e is built. The maintainer's answer P4-4 is recorded below. It merges after P4d (the carousel block), which is the first block to use it. The maintainer's answer P4-8 (the real render through the review) is asked before the merge and is not yet given.

**Context.** `media_animation.why_not` answered `slot` for any block with more than one picture parameter, so the review could add only layouts with one picture. The script path already served several pictures to one beat (slot ids `beat<N>-<param>`), and the media set already fetches and approves slots one by one. The carousel (P4d) takes one to six pictures.

**Decision.**
- D1. An `oh:` layout with several picture parameters can be added in the caption review. Its slots are `a<n>` for the first picture parameter and `a<n>-<param>` for each other, kept in the stored animation as `more_params`. The renderer's checker is shown a slot id for every picture parameter; a picture parameter typed in `params` stays `bad_params`.
- D2. Each slot is searched with the existing `slot_search` op, picked and approved in the media set like any slot. `show`, `search` and `want` given with the add fill the first slot. Removing the animation clears every slot's search, pick and choice.
- D3. The step draws the beat when its first picture is approved, with every other picture that has an approved pick; it writes one slot row for each picture used (the description from that slot's search words, else a plain word). A beat whose first picture is not approved is not drawn, as before.
- D4. `hf:` blocks that take a picture are still not addable. A picture parameter whose name is longer than 28 characters keeps its block out of the addable list, because the slot id `a<n>-<param>` must fit the renderer's 32 characters (validity).
- D5. No limit changes: `STOCK_SLOTS_MAX` (6, the media set's security bound), the media set's budget and the asset sheet's rows are untouched. A review with one picture per animation stores, views and renders as before.

**The maintainer's answers**, verbatim.

- P4-2 (when the review's choices reach the script): "A" (validate: allow english-only -- the maintainer's own words, quoted)
  Gloss: the review's choices now; the script gets them in P8.
- P4-4 (the carousel; the options were pictures, 1 to 6, with the review change, or something smaller): "A" (validate: allow english-only -- the maintainer's own words, quoted)
  Gloss: pictures, 1 to 6, with the review change (P4d and P4e). Six is the media set's security bound, not a taste cap.
- P4-7 (how the carousel moves; context only, the motion is P4d's): "Pode, os três como opção, padrão o C" (validate: allow english-only -- the maintainer's own words, quoted)
  Gloss: all three motions as a choice, the row sliding sideways as the default.
- P4-8 (the real render of P4e through the review): not yet asked.

**What it saves and what it loses (principle 13).** Saves: one review path for every layout with pictures, with no new engine code. Loses nothing in safety: every picture still goes through the media set's search, pick, fetch and approval, within the same six-slot bound, and the renderer checks the parameters again.

**Verified and not verified.**
- Verified offline: the catalogue rule (`oh:` block with several pictures addable, `hf:` with a picture not, an over-long parameter name not); the checker shows `a1`, `a1-asset2` and so on to the renderer's checker and returns `more_params` only when there are several; the stored shape is closed (a bad `more_params` is `review_unreadable`); `stock_slot_ids`, the view rows, removal and the media set's slot list cover every slot; `slot_search` past the bound is still `too_many_slots`; the step writes the params and slot rows of the approved pictures only, draws nothing without the first, and the render step is given every approved file.
- Not verified: a real carousel through the review and the render (supervisor leg L4, after P4d merges); the page shows each slot as `Slot a1-asset2` with the block's `show` words, with no "picture 2" label.
