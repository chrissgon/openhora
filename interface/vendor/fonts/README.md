# Vendored: the brand typefaces

The three typefaces of the interface, as woff2 files of their latin subsets, copied unchanged. Nothing here is edited: a test
(`runtime/tests/test_interface_files.py`) compares every file listed below with the hash written here. `css/base.css` declares them with
`@font-face` (`font-display: swap`, so the text shows at once in the fallback stack) and loads them by relative paths; nothing is loaded
from another host and `index.html` preloads nothing.

- Package: three open typefaces as woff2 latin subsets, copied unchanged from the project's brand pack (the version of each font is in the table below, read from the file's own name table)
- Licence: SIL OFL 1.1 (https://openfontlicense.org); each family has its text in `LICENSE-<family>.txt`. The copyright line of each file is the one the font file itself carries (name table, id 0), followed by the licence text; the upstream projects' own `OFL.txt` files are the reference.
- Used: Inter 400 and 600 for text, JetBrains Mono 400 and 700 for code, hashes and commands, Space Grotesk 500 for the wordmark on the token prompt only.

| Family | Weights | Version (name table) | Files |
|---|---|---|---|
| Inter | 400, 600 | 4.001 | `inter-400.woff2`, `inter-600.woff2` |
| JetBrains Mono | 400, 700 | 2.211 | `jetbrains-mono-400.woff2`, `jetbrains-mono-700.woff2` |
| Space Grotesk | 500 | 2.000 | `space-grotesk-500.woff2` |

| File | Bytes | sha256 |
|---|---|---|
| `LICENSE-inter.txt` | 4376 | `7fbb0605bb42e9ea50dc4d7856290d8f049a24c6fcebb9e01c12581a2e528eba` |
| `LICENSE-jetbrains-mono.txt` | 4398 | `c1ab7c666206842a02b35b30770dac0d7a10156ed401c9defc3f02a754d89e90` |
| `LICENSE-space-grotesk.txt` | 4402 | `f0cc7c74df7e4bfa63638e78c881ed7b71b598fc89a031058fc3a7d5a89a2241` |
| `inter-400.woff2` | 23664 | `8909904ab6c872eb994093482a88a28eca2cd95912d7b6fecd72103b0dc07edc` |
| `inter-600.woff2` | 24452 | `f9a06e79cd3a2a20951c0f0e28f66dd0e6d3fda73911d640a2125c8fcb78f21a` |
| `jetbrains-mono-400.woff2` | 21168 | `14425ba9c695763c1547f48a206b7aa60350a33ae23de09f0407877f3fcd89eb` |
| `jetbrains-mono-700.woff2` | 21908 | `d0d4e818808f2a0ba39b2b09d1989366f63494e295f003c7ef436697378507e8` |
| `space-grotesk-500.woff2` | 13372 | `cedfe94cfb039ab89a4a655dce1dfe9a3ef5afa020dcee403e72d988cdadec99` |

The five font files together are 104,564 bytes.

## To update

1. Take the new woff2 latin subset of the same weight from the font's own project or its npm package; keep the file names.
2. Replace the file, rewrite its row (`shasum -a 256 <file>`) and the version in the table above, and keep the licence file of its family
   current with the copyright line the new file carries.
3. Run `pytest -q runtime/tests/test_interface_files.py runtime/tests/test_interface_adj_b1.py`.
