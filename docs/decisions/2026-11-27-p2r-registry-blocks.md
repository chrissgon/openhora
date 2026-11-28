## 2026-11-27: Three registry text overlays join the block choices (video P2r)

**Status.** Approved by the maintainer; his answers are quoted below.

**Context.** The survey of the registry's text components found three that pass the determinism test and look like what a video wants: a name bar (`lt-mask-reveal`), a calm shimmer (`text-shimmer`) and a letter explosion (`char-slam-explode`). Only a few text blocks were choosable for a keyword or a name. The spec asked for one pull request per block; the three are in one, because they regenerate the same pins, the same catalogue and the same registry rows.

**Decision.**
- D1. `hf:text-shimmer` is admitted as a registry component (tier A): preset `keyword`, one parameter `text` (at most 24 characters), edit E1 only. Its `use_when`: a calm, short headline.
- D2. `hf:char-slam-explode` is admitted the same way, with `text` at most 12 characters and a `use_when` that says it is for one short word of impact only, never a phrase. The entry's parameter bound carries the limit, so the bound is in code and not only in the wording.
- D3. `hf:lt-mask-reveal` is a tier-B port (the registry's block has its text hard-coded, so it is a rewrite, as `hf:spring-pop` was): preset `quote` with its three parameters (`text`, `author`, `color`). The vocabulary has no `nametag` preset (`oh:nametag` is a block of the catalogue, not a preset of `shared/references/video-presets.json`), and a port must declare exactly its preset's parameters, so `quote` is the one that fits a name and a role. The role line is half the name's size and never under 36 px at 1080 wide (the survey's was about 25 px); the name is at most about 28 characters for the proportion to hold, said in its `use_when`; a longer name shrinks to a floor of 40 px.
- D4. None is a default of its preset: each is chosen by name. The ffmpeg engine's defaults do not change, so a video that chooses nothing renders the same bytes.
- D5. Each has its own determinism record (4 runs, 0 blocked) written by `admit-block`, and the registry rows and the notice entries the admission writes; the port has its row in the "Ports adapted from the registry" table of `hf-runtime/NOTICE.md`.

**The maintainer's answers**, verbatim.

- Shown the survey and a recommendation of only the name bar: "Por que não adicionar as três?" (validate: allow english-only -- the maintainer's own words, quoted)
- Shown the recommendation of all three (the name bar with a larger role line; the letter explosion limited to a short word): "Sim." (validate: allow english-only -- the maintainer's own words, quoted)

**What it saves and what it loses (principle 13).** Saves: three more looks with no new engine code. Loses nothing in safety: the same lint, the same page policy, the same determinism test and the same pinned files as the first admission. The letter explosion's tighter bound is the only limit added; it is a taste limit chosen by the maintainer for this one block, set in the block's own parameter and not a rule for the others.

**Verified and not verified.** Verified live: the three admissions (determinism, 4 runs, 0 blocked); each block rendered twice on a synthetic recording with an identical sha256 (look sheet, outside the repository). Not verified: long names above 28 characters (the layout shrinks to its floor and does not wrap); real recordings.
