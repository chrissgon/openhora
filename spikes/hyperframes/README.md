# Spike: HyperFrames as a second `renderer:video` (decision D21)

Throwaway code, not part of the workbench core and not meant to merge. It tests whether the open-source renderer HyperFrames can draw the
same edit as `providers/renderer`, behind the same renderer-neutral edit list (`edl.schema.json`).

HyperFrames and everything it depends on is third-party code. It is installed, built and run **only inside a container** defined here:
the network exists while the image is built and never again. Nothing of HyperFrames is installed or run on the host, and none of its
files is stored in this repository (the adapter fetches the component files it needs at image build, at a pinned commit, and checks the sha256 of each).

| File | What it is |
|------|------------|
| `Dockerfile`, `build.sh` | The image: base by digest, Debian snapshot, the same pinned Chrome as `providers/renderer`, HyperFrames and GSAP from `package-lock.json` (`npm ci --ignore-scripts`), registry components from `registry.sha256`. |
| `package.json`, `package-lock.json` | The exact pins (integrity hashes for every package). |
| `registry.sha256`, `fetch_registry.py` | The commit and the sha256 of each registry file used. |
| `run.sh` | Runs a command in the image: no network, read-only root, no capability, non-root, cpu/memory/pids limits, scratch in memory. |
| `synth.sh`, `render.sh` | Build a project from an edit list and render it, recording wall time and peak memory. |
| `adapter/hf_adapter.py` | Edit list + beats -> a HyperFrames project (cuts as trimmed `<video>` clips, zoom, captions, overlays). Reuses our planning code read-only. |
| `adapter/ports.py` | The text patches that turn registry components into 1080x1920 compositions with our words; each patch asserts how many times it matches. |
| `adapter/make_synthetic.py` | A fictional test case (test pattern, invented words) for the offline and determinism checks. |
| `adapter/compare.py`, `adapter/sheet.py` | Frame alignment and sound sync against another render; the sheet of stills. |

The write-up (results, licences, verdict) is in the plan folder, `research/reels-2026-10-14/5-hyperframes-spike.md`, not here.
