## 2026-11-27: Fonts are admitted by conditions checked in code, each with a pinned open-licence source (P2b; replaces VD6)

**Context.** VD6 fixed one set of three fonts, with a weaker provenance said on purpose: the package version was not recorded and the licence inside the packages was not read. The maintainer wants fonts to be added by a rule, not by a decision for each font.

**What the maintainer decided.**
- P2-3, how to choose: "Folha de candidatas (Recomendado)". From the sheet he picked: "Montserrat,Anton,Poppins,Oswald". (validate: allow english-only -- the maintainer's own words, quoted)
- P2-4, the licences (SIL Open Font License 1.1, `@fontsource` 5.3.0, hashes checked): "Pode, as quatro (Recomendado)". (validate: allow english-only -- the maintainer's own words, quoted)
- P2-5 needed no decision: the three existing files are byte-identical to `@fontsource/inter@5.3.0` (`files/inter-latin-800-normal.woff2`, `files/inter-latin-500-normal.woff2`) and `@fontsource/jetbrains-mono@5.3.0` (`files/jetbrains-mono-latin-500-normal.woff2`), so they get that pinned source and need no grandfathered exception.

**The rule, in code** (`providers/renderer/_assets.py`, `font_allowlist`). A row is admitted only when all hold: an id, a plain file name, the file's sha256, a `weight` and a source text; a licence of `OFL-1.1` or `Apache-2.0`; a `licence_file` that is a plain name and is present in the fonts folder; a `family`; and a pinned source: `package`, `package_version` (X.Y.Z) and `integrity` (the sha512 of the package tarball, as the registry reports it). A row that fails any one refuses the whole list (`bad_font_allowlist`), so a font outside the conditions is never served. The serving checks are unchanged (`load_fonts` re-checks the sha256 and the magic bytes). The licence is not a free word: adding a licence to the two accepted ones is a change of code and of this decision.

**The fonts** (all `@fontsource` 5.3.0, Latin subset woff2, licence text of each package beside the files; the existing three files unchanged, their licence texts replaced by their packages' own).

| Font | File | sha256 |
|---|---|---|
| Inter 800 | `inter-800.woff2` | `a7d0a50f15d389cad679238466bdb5fc9787aa0715719064ce25abaff042820d` |
| Inter 500 | `inter-500.woff2` | `f3779f1efccc4bdcdf9c0a02ab95bf6bd092ed09c48c08cedc725889edd1d19f` |
| JetBrains Mono 500 | `jetbrains-mono-500.woff2` | `cb182feeed4d798ff6961d3c79f7026279448fca0676438aaecb21f3fc39553a` |
| Montserrat 800 | `montserrat-800.woff2` | `ba826fb84c2e961578adf3a08b5778b87905d4443445d1d56d84f9f157d5ea4b` |
| Montserrat 500 | `montserrat-500.woff2` | `2b53300fb9471520df2f4905847fb7a209879b2029ae893c05c6ee346b1320cd` |
| Anton 400 | `anton-400.woff2` | `d0fa07ff63dd60cbc0e2f58e29c802dca2a5ae0276c999f59c6111ab7bbaec3b` |
| Poppins 800 | `poppins-800.woff2` | `60bf0aba6526436f3930c58c12047687fbb6bff4dd180cce4613458ed3439ea2` |
| Poppins 500 | `poppins-500.woff2` | `cd36de204aca2d5fa263a731f7c20009b5e3d754ba1f1e03c33e93a48f3e7446` |
| Oswald 700 | `oswald-700.woff2` | `aae665c75af89ea7cb7d8ccc8b0911ea72267442ebcd84f6e3efa041ad3b3c16` |
| Oswald 400 | `oswald-400.woff2` | `e902b779e43944c300cf8ae5e4a1affa68cb8a823fd263dd2f479c4cdfbd213c` |

The integrity strings are in `allowlist.json`, one per package.

**What it saves and what it loses (principle 13).** It saves a decision per font and the weaker provenance of VD6, and it makes a font without a pinned open-licence source impossible to serve. It loses a little: a font must come from a package with an integrity, and the image grows by the new files (about the size of the existing ones each).

**Verified.** Every copied file's sha256 against the supervisor's record; the three existing files byte-identical to the packages' files; the rule's refusal of each condition, one at a time, offline; the shipped list passes the rule.

**Not verified.** The image was not rebuilt and no render was made here (the supervisor rebuilds and makes the font sheet). The ports' text sizing is tuned to Inter: Montserrat wraps the Portuguese and Spanish caption to two lines and Anton fills only about 60 to 70 percent of the width. P2b does not retune the ports; the sheet shows it and the maintainer decides later (P2-7). The upstream releases were not compared with Fontsource's subsets.
