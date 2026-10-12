# Vendored: Perfect UI

The styling library of the interface's panels, copied unchanged from its npm package.

- Package: `@chrissgon/perfectui` on npm (https://www.npmjs.com/package/@chrissgon/perfectui), fetched with `npm pack @chrissgon/perfectui@1.0.0` into a folder outside the repository
- Version: **1.0.0**
- Licence: MIT, the text is in `LICENSE` beside this file (copied from the package's `LICENSE`; the service does not serve a file with no known extension, and nothing needs it at run time)
- Copied: the package's `dist/` folder whole (`perfectui.css`, `css/`, `js/`, `types/`) and its `LICENSE`. The page loads
  `perfectui.css` and `js/index.js` by relative paths. `js/mode.js` is vendored with the rest and is not loaded: it keeps a
  cookie, which the page never does. The `types/` files are for editors; the service does not serve them either.

| File | Bytes | sha256 |
|---|---|---|
| `LICENSE` | 1079 | `0a296f87633a6826b70b291bc418d3cb931878d99f7a15228ba7777d801805b6` |
| `css/components/accordion.css` | 2127 | `55d3afee4645b2030ba98a867fbafec0db67734f80e4069d009f4efdaa90cca5` |
| `css/components/badge.css` | 406 | `645a2f3117fbe2cce7280d5d13751f5ae21f7eb81f715baf69f6724c60d1c38b` |
| `css/components/button.css` | 500 | `622b99ab0c0cd11fec4f494ddbbbfd9072dc3b5dade861ba00ba82f5b9acaeab` |
| `css/components/card.css` | 523 | `d607a52fb149ddda9e89395c1452de6188088675468dafb7102dd3f6841ccd45` |
| `css/components/chip.css` | 388 | `ae9d49f70f95a12941eef6fd8e5f22119ca0c8326fdc2c4006c2d5cf4907ba6a` |
| `css/components/dropdown.css` | 1263 | `a733c6d0886cee91109e64d867dbcb3100d5c817003a048afad85efdd41f2ef9` |
| `css/components/float.css` | 221 | `5936a2b6b302bdec01cc65aac381ccfa3215df5e52e8be582fe67c6e697305cf` |
| `css/components/form.css` | 3986 | `6f58158279ba9b8733b7a514a7a7846a99f468a5dd047f06a9d689b478eca035` |
| `css/components/group.css` | 1225 | `b22f176e812ced2a75106dd501e01a600dd5318d5b96eecc2dc8dd25e099ef1c` |
| `css/components/list.css` | 473 | `f7cbe600aa2de52f6775fc6fc4def1ec3ce53d7f061ccf571a0ec4947f9776a5` |
| `css/components/modal.css` | 358 | `f3c00b999cd41a17c85dcbe72d60b5a82c7c74d4f519d8d75ee39fb9b3252e91` |
| `css/components/table.css` | 695 | `d728f9259b0af23422dc2123f92d1cf4d878e50d90122179e0bf58704e8a2fa9` |
| `css/components/timeline.css` | 1351 | `2f093522a4ca0872d3444ed436c113812cfb6f95bb410440870f0bb1ad83a383` |
| `css/components/tooltip.css` | 897 | `48e1929fb73d68c499dabfbefd6b52581852a682409238d86c4889140bc087f8` |
| `css/core.css` | 2756 | `342854d15b79d1e5da6b407c12e8cd5519f7f63acbd087ece0de48abc88afde8` |
| `js/fallbacks/anchor-positioning.js` | 2116 | `3def8111752c28cc16970bfabbfc2ff8460d0a9bfd126b7e34d42115817fb34b` |
| `js/fallbacks/checkbox-indeterminate.js` | 672 | `136a57c7a396478e2a595ea228a3abf0eaadda8ffa49b7a30cdbfb384a9d356f` |
| `js/fallbacks/command-for.js` | 742 | `e094c71d9ea46ffc294caf7e4b70e4c868fed6e6ebcf897cfabcc6318c6d5762` |
| `js/fallbacks/dialog-closedby.js` | 566 | `08e5122757f28009c45e5b544b0ab5096c25d0de2c480f01d018566a13d7a5c4` |
| `js/fallbacks/interest-for.js` | 1610 | `dc38b78f22c7ed01126a560588aa7880b5f86e30dcf13de235e62585faa43a9d` |
| `js/index.js` | 1201 | `bf0436565b885772383f41823453b2ab4dbd437e2fef98c874fe325fffa77cdf` |
| `js/mode.js` | 577 | `75968250cc6d618727f0f739aeeb0ff5c47b8a83114d8cd9050a66964f818442` |
| `perfectui.css` | 15824 | `ad43ec726bc5b9fa12c477743498b5467d37dc6b120fe760e1ab05c26f5bd687` |
| `types/fallbacks/anchor-positioning.d.ts` | 760 | `751eaba882cbdff2784b974582d9454f1a21acc3ff916f0a42a13cf87098b8d4` |
| `types/fallbacks/checkbox-indeterminate.d.ts` | 721 | `06c1e8cd37b5a7ed54fc7412d78fb97b8ff335a3395834b99d1ede7cefdb6835` |
| `types/fallbacks/command-for.d.ts` | 399 | `2eff3f9f90c399a2e6e34af23a808155731be725e08005c222eb30113d08e70e` |
| `types/fallbacks/dialog-closedby.d.ts` | 293 | `a442b24e726e3ecd06bd9085c646391cc0943cfe4a85cfeb3e3ea09917a1b665` |
| `types/fallbacks/interest-for.d.ts` | 524 | `f4f234dcc5f1d497cc4559ced2ccc1df34f70b2216390c1264f3eeff73fd0a8a` |
| `types/index.d.ts` | 860 | `e0ec468935be7c9421a97d491208d757411168e3c764d312578761132b5ee6d4` |
| `types/mode.d.ts` | 630 | `c41425f434020bc6600b67003bd71f190676025be7dcc8fe1e5f416fd15d29fb` |

## To update

1. In a folder outside the repository: `npm pack @chrissgon/perfectui@<version>`, unpack the tarball.
2. Replace this folder's contents with the package's `dist/` and its `LICENSE`, unedited.
3. Rewrite the version and the table above (`shasum -a 256 <file>`), and run `pytest -q runtime/tests/test_interface_files.py`.
