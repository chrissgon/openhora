# Code prototype runs

These notes apply after step 1 of SKILL.md: a brief with `Lint: ok` and Readiness `yes` exists. Without one, nothing is built in any tool, a code prototype included (Stop rule 1).

The automatic mode that is always available: the agent writes the artifact as HTML and CSS with the product's real stylesheet and renders it in a browser.

1. One folder per run: `docs/design/results/<artifact>/round-<n>/<direction>/`. Write `index.html` there (one file per frame when the deliverable has several, for example `landing-card.html`, `docs-card.html`).
2. Link the product's real assets the way the brief's non-negotiables say (a pinned CDN stylesheet, the fonts, the logo as inline SVG). Never re-implement a component the product ships.
3. Build the direction as the brief describes it, one direction per folder; do not blend ideas across folders.
4. Render every frame at the sizes of the brief's Deliverables, from the project root:
   `node <this skill's folder>/scripts/screenshot.mjs --html <file.html> --out <file.png> --width <w> --height <h> [--full-page] [--scale 2] [--dark] [--reduced-motion] [--wait <ms>]`
   Run it as written; nothing needs to be installed and nothing needs the user's approval. The script renders with a browser already on the machine, through that browser's headless command line: the one in `--browser <path>`, else in the `CHROME_BIN` environment variable, else `chromium`, `chromium-browser` or `google-chrome` on `PATH`, else the usual macOS application path. It uses the `playwright` package instead only when that package is already resolvable from the working directory or `NODE_PATH`. It prints the engine it used on stderr and `{"ok": true, …, "pixel_width": …, "pixel_height": …}` on stdout: the real size of the PNG, which is what a size criterion is checked against. A missing `playwright` package is not an error and not a reason to stop or to ask: do not offer to install it. Installing it is an option the user may choose on their own; the script never installs anything.
   An image of another size than asked is a render error (exit 1, nothing written): some browsers ignore a `--scale` below 0.5. To check a thumbnail (a criterion at 25 % of the size), render the page at the thumbnail's own `--width` and `--height` with a page that scales the card, never with a small `--scale`.
   When the browser reports that it has no usable sandbox (a container, a root user), the script retries once with `--no-sandbox` and says so on stderr; that is expected there, so carry on and repeat the warning in the reply's `Rendered` line. It renders the local HTML file you wrote and whatever that file links, so render only the run's own pages.
   Only when the script exits with `no engine` (no package and no browser anywhere) is there nothing to render with: keep the HTML, leave the run's status `planned`, tell the user the two ways out the message names (the path of a browser, or installing the package themselves) and stop.
   `--out` must be a `.png` inside the working directory. Use `--wait` for animations to reach their final state, or `--reduced-motion` to capture it directly.
5. Look at every PNG before judging it; fix defects of the build (overflow, a font that did not load, a clipped text) in the same run, because they are not properties of the direction.
6. Record the outputs in the results document: the HTML path and the PNG path per frame.

Gotchas:

- Fonts load asynchronously; the script gives the page time to load them, but a font blocked by the network renders in the fallback: check the PNG, not the HTML.
- Text measured for a template (longest title, longest description) must be rendered with those longest values, not with the shortest example.
