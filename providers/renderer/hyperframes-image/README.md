# The HyperFrames engine's image

The container image the HyperFrames engine of `renderer:video` draws in (package V3a-image). HyperFrames is an open-source renderer that
draws HTML and GSAP timelines into video frames with a headless browser; it is installed and run only inside this image, never on the
host. The engine's provider, `providers/renderer/hyperframes.py` (package V3a-2), uses this image; the ffmpeg engine has an
image of its own, which also does the verify step, so a project that renders with HyperFrames builds both.

## Files

| File | What it is | In the definition |
|------|------------|-------------------|
| `Dockerfile` | The image: base by digest, Debian snapshot, the headless shell, a static ffmpeg, HyperFrames and GSAP from the lockfile, the three fonts, the font purge, a non-root user | yes |
| `.dockerignore` | The build context: only the files the Dockerfile copies | yes |
| `manifest.json` | The list of the definition's files; the tag hashes them and nothing else | yes |
| `pins.json` | Every download, pinned for arm64 and amd64 | yes |
| `package.json`, `package-lock.json` | `hyperframes` 0.9.19 and `gsap` 3.14.2, and the 127 packages they need, each with its integrity hash | yes |
| `_fetch_browser.py` | Downloads the headless shell and refuses an archive whose size, md5 or sha256 differs from the pin (a copy of the ffmpeg engine's) | yes |
| `fetch_ffmpeg.py` | Downloads the static ffmpeg and refuses an archive whose sha256 differs from the pin | yes |
| `fonts/` | `inter-500.woff2`, `inter-800.woff2`, `jetbrains-mono-500.woff2`, their OFL texts and `SHA256SUMS` | yes |
| `hf_render.py` | The inner entry: checks the project folder and the page's fonts, runs `hyperframes render` into a ProRes intermediate, writes `result.json` | yes |
| `hf_image.py` | Builds the image (`build --confirmed`), says whether it is here (`--check`), checks a built image (`selfcheck`) | no: the build driver |
| `NOTICE.md` | What the image installs, and under which licence | no |
| `README.md` | This file | no |

The image's tag is `openhora-hyperframes:<the first 12 characters of the sha256 of the definition's files>`. A change to a listed file
gives a new tag, and `hf_image.py --check` then says the image is not built; a change anywhere else (the ffmpeg engine, a block, this
README) leaves the tag as it is. The tests are `providers/renderer/tests/test_hf_image.py`.

## Building it

The build is the one step that uses the network. It is a step the person starts, never something a render does:

```bash
python3 providers/renderer/hyperframes-image/hf_image.py build --dry-run     # the exact docker command, nothing run
python3 providers/renderer/hyperframes-image/hf_image.py build --confirmed   # builds for the docker daemon's architecture
python3 providers/renderer/hyperframes-image/hf_image.py --check             # exit 0: the image of this definition is here
python3 providers/renderer/hyperframes-image/hf_image.py selfcheck           # the five checks below, each with no network
```

`selfcheck` passes when all of these hold, each read in a container started with no network, a read-only root and every capability
dropped:

1. `hyperframes telemetry status` says telemetry is disabled by `HYPERFRAMES_NO_TELEMETRY`.
2. `hyperframes --version` prints 0.9.19.
3. The only font files in the image, outside HyperFrames' own `node_modules`, are `/opt/fonts/inter-500.woff2`, `inter-800.woff2` and
   `jetbrains-mono-500.woff2`. The ones inside `node_modules` are counted in the result, not failed: the provider's font guard keeps a
   page from using them (condition C5).
4. Those three files have the sha256 of `fonts/SHA256SUMS`.
5. The only network interface the container sees is `lo`.

The build itself already fails when a font file other than the three is left outside `node_modules`, when a pinned version is not the one
installed, and when any download differs from its pin.

What the build downloads (sizes as measured by the S2 spike on 2026-11-07, arm64): the base image (about 75 MB), Debian packages
(23.8 MB), the headless shell (124,553,121 bytes on arm64, 124,203,329 on amd64), the static ffmpeg (121,067,028 bytes on arm64; amd64
not measured) and the npm packages of the lockfile (`hyperframes` alone is 24.1 MB unpacked; the total was not measured).

## pins.json

- `base`: the base image's reference and the digest of its multi-architecture index; the Dockerfile's `FROM` line must equal them.
- `debian_snapshot`: the date of the Debian archive snapshot apt reads.
- `npm`: the versions of `hyperframes` and `gsap`, and the number of packages in the lockfile.
- `browser`: the headless shell's version and, for `arm64` and `amd64`, the archive's URL, size, md5, sha256 and the binary's path in it.
- `ffmpeg`: the static build's version and, for `arm64` and `amd64`, the archive's URL and sha256.

Each sha256 says where it came from in `sha256_source`. `build` refuses an architecture whose browser or ffmpeg sha256 is null.

## Pinning the browser for amd64

Chrome for Testing publishes a size and an md5 for each archive, and no sha256. The sha256 is computed once, from a download whose size
and md5 match the published ones, and written into `pins.json`. The download is about 124 MB and needs the maintainer's word. From an
empty scratch folder:

```bash
curl --fail --silent --show-error --proto '=https' --max-redirs 0 -o chrome-headless-shell-linux64.zip \
  https://storage.googleapis.com/chrome-for-testing-public/155.0.8059.39/linux64/chrome-headless-shell-linux64.zip
stat -f %z chrome-headless-shell-linux64.zip     # macOS; on Linux: stat -c %s. Must print 124203329
md5 -q chrome-headless-shell-linux64.zip         # macOS; on Linux: md5sum. Must print 042794dd01c0d40a7388ef8701caba43
shasum -a 256 chrome-headless-shell-linux64.zip  # the value to record
```

Only when the size and the md5 both match, the sha256 goes into `browser.platforms.amd64.sha256`, and `sha256_source` says the date of
the download. The ffmpeg engine's `browser-pin.json` pins the same archive; a test compares the two files when both are in the checkout.

## Not part of this image yet

- **Registry blocks admitted so far: none.** `registry.sha256` pins the registry's LICENSE at commit `b4cc674f` and, once a component is admitted,
  that component's two files (`<name>.html` and `registry-item.json`); `fetch_registry.py` fetches them at build time and refuses a hash that
  differs, into `/opt/hf-registry`. `hf_compat.py` (the admission run) and `hf_wrap.py` (the lint and the wrapper) sit beside `hf_render.py`.
- **The program that renders.** Package V3a adds the provider and what it runs in this image.

## What is never done

HyperFrames' commands that reach a network or an account are never called, at build time or at run time, and the instructions of its
own README to upgrade, update or install its skills are not followed. The image runs with no network; the build is the only step that
has one.

## The inner entry and the provider

`hf_render.py` is the one file of this folder the image runs (`python3 -I /opt/hf-run/hf_render.py`, copied after the font purge so that no
`RUN` follows it). It checks the project folder the common image prepared (exactly `index.html`, `vars.json` and `media/proxy.mp4`, each a
regular file within a cap), refuses a page that names a font outside the allow-list, copies GSAP in, runs `hyperframes render` once into a
ProRes HQ intermediate and writes `result.json`. It is in the definition, so a change to it gives a new tag. The provider is
`providers/renderer/hyperframes.py`: `build --confirmed` there calls `hf_image.build_image` and writes the build record that `--check` and
`render` read; `render --base-only` runs the page, the proxy and the final encode in the common image and only the drawing here.
