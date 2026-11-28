# The public website

Static files, no build step for the pages. Beside the pages: `robots.txt`, `sitemap.xml` and `llms.txt`. `netlify.toml` (repository root) publishes this folder. The one generated part is `site/demo/`, the demo
of the Interface page: the deploy builds it from `interface/` with `python3 scripts/build_demo.py --out site/demo`, and it is git-ignored.

## Look at it

    python3 scripts/build_demo.py --out site/demo --replace
    python3 -m http.server 8813 --directory site

`/proof` works on Netlify because it serves `proof.html`; a plain static server needs `/proof.html`.

## The facts are generated

Every number, date, model list and band the pages state sits in a block between `<!-- facts:begin <name> -->` and `<!-- facts:end <name> -->`. Nothing
inside a block is edited by hand. The blocks are written from the two sources of the published bands and from counts of this checkout:

    python3 site/tools/build_proof_json.py       # docs/inventory.md and evals/eval-gate.json -> assets/data/proof.json
    python3 site/tools/build_facts.py --write    # proof.json and tools/count_facts.py -> every block of every page

Run both, in this order, in the pull request that regenerates `docs/inventory.md` (`python3 evals/eval_status.py inventory --write`), and whenever a skill,
agent, adapter, flow or pack is added or removed (the counts of the home page). `python3 site/tools/build_facts.py --check` and
`python3 site/tools/build_proof_json.py --check` say what is stale; `scripts/tests/test_site_facts.py` runs both in CI, so the `tests` check fails when the
inventory or the gate file changes and the site is not rebuilt. The pages stay static HTML: no script is needed to read the numbers. The dial and the
figures of the home page draw one ring and one figure for each lab model of the gate file, in its order, however many there are, and `assets/js/proof.js`
draws a row for each of them.

## Search engines and language models

`robots.txt` lets every crawler in and names `sitemap.xml`, which lists the canonical URL of each of the six pages (not `/demo/`, not the 404 page). Home carries one JSON-LD block (`WebSite` and `SoftwareSourceCode`) that states only what the page states. `/demo/` is kept out of search results by the header `X-Robots-Tag: noindex` in `netlify.toml`, not by `robots.txt`: a crawler that may not fetch a page cannot read its noindex. `llms.txt` (the llmstxt.org format) is written by hand and only quotes the pages. A page's link carries its title and its meta description, and a differentiator's link carries its heading on Home. Every other text is a sentence of a page, and never a figure from a facts block. `site/tests/website.test.mjs` fails when a page it quotes changes, and `tools/check_links.py` checks its GitHub links. A new page is added to `sitemap.xml`, to `llms.txt` and to `ROUTES` in the test. Verifying the domain in Search Console and submitting the sitemap are done by the maintainer, outside the repository.

## Check it

    node --test site/tests/website.test.mjs

Needs Node 24, Python 3 and Chromium or Chrome (set `CHROMIUM` to its path when it is not at `/usr/bin/chromium` or the macOS Chrome path). Nothing is
installed. The tests build the demo into a temporary folder, serve the site and that demo with the headers of `netlify.toml`, and run the pages at
1280 and 375 px in light and dark. They are not in CI yet: the CI runner's Node and Chrome versions are not pinned in `.github/workflows/checks.yml`.

Other tools: `python3 site/tools/check_links.py` lists the GitHub links of the pages and of `llms.txt` that point at a missing path; `python3 site/tools/build_css.py` rebuilds the
per-page stylesheets from `assets/css/src/site.css`; `python3 site/tools/build_proof_json.py` rebuilds `assets/data/proof.json` from the band and model tables of
`docs/inventory.md`; `python3 site/tools/count_facts.py` counts the facts the pages state (skills, guard assertions, skills that carry the external-content line).
