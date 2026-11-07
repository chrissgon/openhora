# Notice: what the HyperFrames engine's image installs

This folder holds the definition of a container image, not the software the image installs. `hf_image.py build --confirmed` builds the
image on the person's own machine and fetches each piece below from its publisher at the pinned version; the workbench distributes none of
them, and none of their files is in this repository. The one exception is the three fonts, which are committed in `fonts/` with their
licence texts. This notice says what the built image holds and under which terms.

| What | Version | Where the build gets it | Licence |
|------|---------|-------------------------|---------|
| HyperFrames (npm package `hyperframes`) | 0.9.19 | registry.npmjs.org, from `package-lock.json` | Apache License 2.0, "Copyright 2026 HeyGen, Inc." |
| GSAP (npm package `gsap`) | 3.14.2 | registry.npmjs.org, from `package-lock.json` | GSAP's "Standard 'no charge' license" (https://gsap.com/standard-license), not an open-source licence; accepted by the maintainer on 2026-11-07 (plan v3, decision 7) |
| The other npm packages of `package-lock.json` | as locked | registry.npmjs.org | 127 packages in all; besides GSAP (the row above): MIT 82, Apache-2.0 20, LGPL-3.0-or-later 10, ISC 6, Apache-2.0 AND LGPL-3.0-or-later 3, BSD-3-Clause 2, Apache-2.0 AND LGPL-3.0-or-later AND MIT 1, CC0-1.0 1, 0BSD 1 (the `license` field of each row) |
| Static ffmpeg and ffprobe | n8.0.1-66-g27b8d1a017 (autobuild-2026-02-28-12-59) | github.com/BtbN/FFmpeg-Builds, the `gpl` variant | GPL; the build's own licence files were not read |
| Chrome for Testing, headless shell | 155.0.8059.39 | storage.googleapis.com/chrome-for-testing-public | its licence files travel inside the archive, unpacked in `/opt/chrome` |
| Debian packages (the browser's libraries, python3, ca-certificates) | snapshot 20261006T000000Z | snapshot.debian.org | each package's own; `/usr/share/doc/<package>/copyright` in the image |
| Base image, Node.js 22 on Debian bookworm | `node:22.23.4-bookworm-slim` by digest | Docker Hub | Node.js: MIT; the Debian part as above |
| Fonts: Inter (500, 800) and JetBrains Mono (500), Latin subsets | as in `fonts/SHA256SUMS` | committed in `fonts/` | SIL Open Font License 1.1; the texts are `fonts/Inter-OFL.txt` and `fonts/JetBrainsMono-OFL.txt`, copied with the fonts to `/opt/fonts` |

Notes:

- **The LGPL packages.** The 14 rows whose licence includes LGPL-3.0-or-later are `@img/sharp-libvips-*` and the builds of `sharp` that
  bundle it. They are optional: npm installs only those that match the build's platform. A render does not load them (S2, 2026-11-07).
- **GSAP is never committed.** It is installed from the lockfile at build time, and the pages a render writes load it from the image.
- **The fonts' provenance is weaker than the rest**, as the ffmpeg engine's `assets/fonts/allowlist.json` states: they are Fontsource's
  Latin subsets of the upstream fonts, and the exact package version they came from was not recorded. Their sha256 is pinned.
- **The registry blocks of HyperFrames are not in this image.** They come with package V3b and its allowlist, with their own entries in
  this notice.
- What the image installed is listed in `/opt/hf/npm-ls.txt` (every npm package) and in the image's labels (the pins).
