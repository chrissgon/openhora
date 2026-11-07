# Notice: what the pages of spike S2 are derived from

The pages the adapter writes contain code of these files of **heygen-com/hyperframes**, tag v0.9.19, commit `b4cc674f7f312e77ded32e0b53006cc0bad6723b`,
licence **Apache License 2.0**, "Copyright 2026 HeyGen, Inc." (the repository's `LICENSE`; sha256 in `registry.sha256`). The repository has no `NOTICE` file
(it has `CREDITS.md`, which lists mediabunny, MPL-2.0, used by its studio only, not by these blocks). None of the block files carries a licence header of
its own and none of their `registry-item.json` files has a `license` field, so the repository's licence is the one that applies.

| Block | File of the repository | Used as |
|-------|------------------------|---------|
| caption-highlight | `registry/components/caption-highlight/caption-highlight.html` | caption style "highlight" |
| caption-pill-karaoke | `registry/components/caption-pill-karaoke/caption-pill-karaoke.html` | caption style "pill" |
| caption-kinetic-slam | `registry/components/caption-kinetic-slam/caption-kinetic-slam.html` | caption style "slam" |
| count-up | `registry/components/count-up/count-up.html` | the number card |
| testimonial-card | `registry/components/testimonial-card/testimonial-card.html` | the quote card |
| spring-pop | `registry/components/spring-pop/spring-pop.html` | the keyword card |

The adapter patches each block in memory at the moment it writes a page (`adapter/ports.py`; every replacement asserted); no block file is stored in this
repository. If a port were adopted, the patched files would be copied with this notice beside them and pinned by sha256.

Other third-party material the image holds (not in this repository): the npm packages of `package-lock.json` (mostly MIT and Apache-2.0; `gsap` 3.14.2
under GSAP's "Standard 'no charge' license", not an open-source licence; the optional `@img/sharp-libvips-*` binaries LGPL-3.0-or-later), a static
ffmpeg build (BtbN, GPL variant), Chrome for Testing's headless shell, and the three fonts of `providers/renderer/assets/fonts/` (SIL OFL 1.1).
