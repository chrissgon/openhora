# Spike S2: HyperFrames 0.9.19 as the drawing engine of `renderer:video` (decision hf-0)

Throwaway code, not part of the workbench core and not meant to merge. It continues the S1 spike (`archive/spike-hyperframes`, HyperFrames 0.8.155)
and tests whether HyperFrames **0.9.19** can draw the same edit as `providers/renderer` (the ffmpeg implementation on `origin/feature/short-video`),
behind the same renderer-neutral edit list (`edl.json`, `beats.json`), under the limits of `providers/_container.py` of `origin/main`.

HyperFrames and everything it depends on is third-party code. It is installed, built and run **only inside a container** defined here. The network
exists while the image is built and never again: every render, check and measurement runs with `--network none`, a read-only root, every capability
dropped, no new privileges, a non-root user, memory-backed `/tmp` and `/scratch`. Nothing of HyperFrames runs on the host, and none of its files is stored
in this repository (the image build fetches the registry files it needs at a pinned commit and checks the sha256 of each: `registry.sha256`).

| File | What it is |
|------|------------|
| `Dockerfile`, `build.sh`, `.dockerignore` | The image: base by digest (`node:22.23.4-bookworm-slim`), Debian snapshot, Chrome for Testing's headless shell (the pin of `providers/renderer/browser-pin.json`), the static ffmpeg HyperFrames pins (sha256), HyperFrames and GSAP from `package-lock.json` (`npm ci --ignore-scripts`), the registry files from `registry.sha256`. No system font is left in it. |
| `package.json`, `package-lock.json` | The exact pins (integrity hashes for every package). |
| `registry.sha256`, `fetch_registry.py`, `fetch_ffmpeg.py` | The commit and sha256 of each registry file; the ffmpeg fetcher that checks the archive's sha256. |
| `s2.py` | The host driver: every container job goes through `providers/_container.py` (imported from a detached worktree of `origin/main`, not copied), plus `--cpuset-cpus` for check C2 and a `docker stats` sampler for C7. |
| `matrix.py`, `ours.py` | Runs the whole matrix of one case (three renders, four renders on limited cores, `verify` of each, boxes, fonts); renders the same edit list with our ffmpeg renderer. |
| `adapter/hf_adapter.py` | Edit list + beats -> a HyperFrames project: `index.html` (structure and numbers only) and `vars.json` (every piece of text, read with `--variables-file`). Refuses a page that names a font outside the allow-list. |
| `adapter/ports.py` | The text patches that turn six registry blocks into parts of one 1080x1920 page that reads its words from the variables; each patch asserts how many times it matches. |
| `adapter/measure.mjs`, `adapter/c6.py`, `adapter/c8.py` | Per-frame boxes after HyperFrames' own seek (`window.__player.renderSeek`), the face-box check with our `face_hit`, the layout-fit numbers; the fonts the page drew with (CDP). |
| `adapter/fontcompile.mjs` | Calls HyperFrames' own font injector offline and prints what it would add. |
| `adapter/make_synthetic.py`, `adapter/compare.py`, `adapter/sheet.py` | The fictional pt-BR test case (invented words, a test pattern), the frame alignment and sound sync against another render, the contact sheet. |
| `fixtures/synth/` | The synthetic case's `edl.json`, `beats.json`, `transcript.json` and the sha256 of its recording. No real person, recording or text. |
| `NOTICE.md` | Where each ported block came from and its licence. |

The real recording and everything derived from it stay outside git (read in place, mounted read-only; its runs go to a folder outside this repository).
The write-up (results, verdict) is `report.md`, kept outside git.
