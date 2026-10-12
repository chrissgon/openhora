# The public website

Static files, no build step for the pages. `netlify.toml` (repository root) publishes this folder. The one generated part is `site/demo/`, the demo
of the Interface page: the deploy builds it from `interface/` with `python3 scripts/build_demo.py --out site/demo`, and it is git-ignored.

## Look at it

    python3 scripts/build_demo.py --out site/demo --replace
    python3 -m http.server 8813 --directory site

`/proof` works on Netlify because it serves `proof.html`; a plain static server needs `/proof.html`.

## Check it

    node --test site/tests/website.test.mjs

Needs Node 24, Python 3 and Chromium or Chrome (set `CHROMIUM` to its path when it is not at `/usr/bin/chromium` or the macOS Chrome path). Nothing is
installed. The tests build the demo into a temporary folder, serve the site and that demo with the headers of `netlify.toml`, and run the pages at
1280 and 375 px in light and dark. They are not in CI yet: the CI runner's Node and Chrome versions are not pinned in `.github/workflows/checks.yml`.

Other tools: `python3 site/tools/check_links.py` lists the GitHub links that point at a missing path; `python3 site/tools/build_css.py` rebuilds the
per-page stylesheets from `assets/css/src/site.css`.
