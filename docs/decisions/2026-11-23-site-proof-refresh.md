## 2026-11-23: the website's figures are generated from the inventory and the gate file (SITE-1)

**The defect.** The pages of `site/` stated the skills' bands from a snapshot of 2026-11-05 that was written by hand and never refreshed: `site/assets/data/proof.json` held 48 skills on two lab models (1 reliable on the first, none on the second), and the home page, the proof page and the page on how it is built repeated those counts, the dates and the lab models in hand-written text. Meanwhile `docs/inventory.md` had moved to 51 skills, reliable on all four lab models of `evals/eval-gate.json`. Nothing tied the site to the inventory, and no test noticed.

**The maintainer's words**, asked why the site showed most skills as not reliable when they are, answering the fix proposed to him on 2026-11-23:

> Corrija (validate: allow english-only -- the maintainer's own words, quoted)

**The fix.**
- `site/tools/build_proof_json.py` rebuilds `site/assets/data/proof.json` from the inventory and the gate file, with defaults that work from the repository root and a `--check` mode.
- `site/tools/build_facts.py` (new; `--write` and `--check`) rewrites every block between `<!-- facts:begin <name> -->` and `<!-- facts:end <name> -->` in `site/*.html` from `proof.json` and from `site/tools/count_facts.py` (now also counting agents, adapters, flows and packs). The pages stay static HTML; the content security policy is unchanged. It also checks that the constants of the gate widget in `assets/js/proof.js` agree with the gate file.
- `scripts/tests/test_site_facts.py` runs both checks in CI and fails with the command that fixes it; `scripts/select_tests.py` now names `docs/inventory.md` as a file a test can name, so a change to the inventory selects it.
- The dial and the figures of the home page draw one ring and one figure for each lab model of the gate file, in its order (four today), with no count written by hand. Where the figures are hand-written lines of the page that no source holds (the number of run lines, the field-evidence counts, the starting values of the gate widget) the claim was removed or reworded as a property, not a number.
- The text test of the site (`site/tests/website.test.mjs`) no longer compares the text of a generated block with the 2026-11 hand-off; it compares the static text around it.
- `AGENTS.md` and `site/README.md` say that the pull request that regenerates the inventory also runs the two site commands.

**Rejected.** Reading `proof.json` with a script on every page: the pages would show no number without script, and the figures are read by people who open the page as a file. A free-text snapshot date: the inventory carries a commit, not a date, so the pages state the commit and the dates of the last full tests.

**Not verified.** The dial and the figures at four lab models were looked at on screenshots at 1280 and 375 px, light and dark, in headless Chrome; no other browser. The node tests of the site are not in CI (`site/README.md`), so only the Python check guards the facts there. The site has not been deployed from this change.
