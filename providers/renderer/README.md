# Renderer provider (`renderer:video`)

Cuts a recording by silence, draws HTML presets over it frame by frame, and composes a vertical video, in a container. It is the
implementation of the class `renderer:video` (a class the runtime uses and no skill requires: decision D11 of the short-video plan).
Interface: `providers/CONTRACT.md` ("Verbs per class"). No model is involved: the edit list is built by code from a transcript and the
beats come from the post file's script block.

## What is here

| File | What it is |
|------|------------|
| `ffmpeg.py` | The host side, the one implementation file of the folder: checks flags, stages inputs into a private job folder, builds the `docker run` command, runs it, reads the result as untrusted. Python 3.9, standard library only. |
| `_docker.py`, `_browser.py` | The host side's helpers: the container's limits, the build, the state folders; the browser pin and the maintainer's one-time `pin-browser`. Not in the image. |
| `_inner.py` | The container's entry point (`python3 -I /opt/renderer/_inner.py <verb>`): `analyse`, `base`, `align`, `check`, `render`, `cover`, `selfcheck`. The tests run it directly on the host with a local Chromium. |
| `_edl.py`, `_timeline.py`, `_align.py`, `_vocab.py`, `_text.py` | The edit list and its check, the cuts, captions and retake proposals, the beats and their alignment, the vocabulary's typed parameters, the text rules. |
| `_cdp.py`, `_frames.py`, `_lint.py`, `_render.py`, `_media.py` | The DevTools-pipe driver, the frame loop and what is served to the page, the determinism lint, the render, ffprobe/ffmpeg and the one compose command. |
| `_redact.py` | A generated copy of `shared/scripts/redact.py` (the credential formats `check` scans with). |
| `templates/*.html`, `templates/pins.json` | The presets (`caption`, `keyword`, `list`, `number`, `quote`, `cutaway`, `pip`), each a pure `renderAt(t, data)`, each pinned by sha256. |
| `renderer-presets.json` | What the renderer decides about `shared/references/video-presets.json` (frame, zones, cuts, zoom, timing, limits). The vocabulary itself is read by flag. |
| `edl.schema.json` | The renderer-neutral edit list and beats. |
| `browser-pin.json`, `Dockerfile`, `.dockerignore`, `_fetch_browser.py` | The image's definition and the pins it is built from. |
| `assets/fonts/allowlist.json` | The fonts a render may use. Empty: no font is chosen yet (decision D6), so every render uses the image's free fallback font and says so. |

## The container (decision D22)

Everything that reads a recording, a transcript or a post runs inside a container, built from `Dockerfile` by `build --confirmed`,
a command the person starts. The pattern is `providers/transcriber/`'s. The image is run by the id `build` recorded; a tag pointed at
another image, or an image older than the files here, is refused. Every limit is in `_docker.container_argv` or `ffmpeg.py`, and a test
in `tests/test_renderer_docker.py` names it:

| Limit | Test |
|-------|------|
| no network, read-only root, `--cap-drop ALL`, `no-new-privileges`, none of `--privileged`, `-e`, `--env-file`, a host namespace | `test_the_container_has_no_network_a_read_only_root_no_capability_and_no_new_privileges` |
| pids, memory (swap included) and CPU limits, an init; CPUs never above the daemon's | `..._limited_in_processes_memory_swap_and_cpus...`, `test_the_cpus_are_clamped_to_the_daemons...` |
| `/tmp` and `/scratch` in memory, `noexec,nosuid,nodev` | `test_the_scratch_and_tmp_are_memory_backed...` |
| the image is never pulled, is run by its id, carries a reaping label and a deadline | `test_the_image_is_never_pulled...` |
| exactly three mounts: the recording and the job folder read-only, the output folder read-write | `test_exactly_three_folders_are_mounted...` |
| a `:` or control character in a mounted path, a recording that is a link or a folder | `test_a_colon_a_control_character...`, `test_a_recording_that_is_a_link...` |
| no variable of the host reaches the client or the container | `test_no_variable_of_the_host_reaches_the_docker_client...` |
| a local daemon only | `test_the_daemon_must_be_local` |
| a timeout kills the client, then `docker rm -f` by name; a stop signal does the same | `test_a_container_past_its_timeout...`, `test_a_stop_signal_removes...` |
| the output folder is looked at (links, FIFOs, too many files) and every file is read with `O_NOFOLLOW`, a size cap and a hash | `test_what_the_container_leaves_in_its_output_folder...`, `test_a_file_copied_out_is_capped_hashed...` |
| a refusal inside is the same refusal outside, in closed words only | `test_a_refusal_inside_the_container_is_the_same_refusal_outside...` |
| a killed run's leftovers are reaped | `test_reap_removes_containers_past_their_deadline...` |

### The browser's sandbox: a choice, with its price (principle 13)

Chrome's own sandbox needs user namespaces, which `--cap-drop ALL`, `no-new-privileges` and Docker's default seccomp profile take
away. Two ways out: a seccomp profile that allows Chrome's sandbox (a wider syscall surface for the whole container, and not testable
here), or `--no-sandbox` **inside the image only**, with the container as the boundary. The second is chosen.

- **What it saves:** every limit above stays as strict as it is; no custom seccomp profile to keep right.
- **What it gives up:** a renderer-process exploit is no longer contained by Chrome's sandbox, only by the container: no network, a
  read-only root, no capability, a non-root user, limits, three mounts. What reaches the page is small: the pinned templates, text drawn
  with `textContent`, and image assets the person uploaded (PNG or JPEG, checked by bytes, bounded, never animated, decoded by the
  browser). A page request is answered from memory or failed, and a content-security policy is set. The recording never reaches Chrome.
- **Never silent:** `_cdp.container_mode()` is true only when `RENDERER_IN_CONTAINER=1` **and** `/etc/openhora-renderer-image` exists (the
  image writes it). Nowhere else is the sandbox off; on the host it is on and a failed start is a failure with no retry. Every render's
  result says `browser_sandbox` (`on` or `off`). Tests: `test_the_browsers_own_sandbox_is_on_everywhere_but_the_image...`,
  `test_inside_the_image_the_sandbox_is_off_and_says_so`.

## Build it (the maintainer's commands, once)

Chrome for Testing publishes no sha256, only the size and md5 of each archive in its storage bucket's object metadata. The pin file
holds those; the sha256 is computed once, at your word, and recorded:

```
python3 providers/renderer/ffmpeg.py pin-browser --dry-run        # the URL, size and md5 it will check; nothing is downloaded
python3 providers/renderer/ffmpeg.py pin-browser --confirmed      # downloads ~124 MB once, checks size+md5, writes the sha256 into browser-pin.json: commit it
python3 providers/renderer/ffmpeg.py build --dry-run              # the exact docker build command
python3 providers/renderer/ffmpeg.py build --confirmed            # pulls the pinned base image, installs packages from the pinned Debian snapshot, downloads the browser, builds
python3 providers/renderer/ffmpeg.py --check                      # docker local and answering, the image current, its tools starting (versions printed)
```

`build` refuses while the sha256 of the daemon's architecture (`linux-arm64` on Apple silicon, `linux64` elsewhere) is not pinned, and
the image's own build (`_fetch_browser.py`) refuses an archive whose size, md5 or sha256 differs from the pin: a later build whose archive
changed under the same version fails. The base image is pinned by digest, the packages by a dated Debian snapshot, the browser by version
and the three values. Nothing in the repository builds, pulls or downloads by itself.

## Contract: replacing this implementation (lego)

The class is the verbs of `providers/CONTRACT.md` and two renderer-neutral files (`edl.schema.json`): another implementation (a Remotion
one, an external service) replaces this one behind the same verbs and the same edit list.

- `base` writes the edit list: frame ranges of the recording, the live words on the output timeline, caption chunks as word indices, the
  theme tokens, the face box, the zoom, the retake proposals. It holds no filter text, no path, no URL and no ASS field.
- `align` writes `beats.json`: overlays and layouts as preset names from `shared/references/video-presets.json`, typed parameters, word
  indices, slot ids (never a description or a file).
- `render` takes both, the recording, the platform file and the person's asset files by slot, and writes `render-<sha12>.mp4`, 0400,
  never rewritten, after checking the file against the platform's video spec. What an implementation owns is only how it draws.
- Selection is `RENDERER_VIDEO_PROVIDER` / `RENDERER_PROVIDER` (or the runtime's configuration), as for every class.

## What the edit does

- **Cuts.** Silence is the signal (`silencedetect`, -35 dB, 0.25 s), minus a margin (0.08 s) on each side; words only protect speech (a
  word stretched far past what it takes to say is protected only for that time, so a silence inside its span is still cut). No kept
  range is shorter than 0.4 s: one with no word is cut, one with a word is joined to its neighbour. Without audio, word gaps over 0.5 s decide.
- **A real transcript's shapes.** Words of zero length are spread evenly to the next word (at least 40 ms) and flagged `estimated`; a start
  that goes back in time is clamped; a segment of three or more words faster than 8 words a second (a repeated sentence squeezed into
  a fraction of a second) is dropped, all reported in `normalisation`. Word indices are never renumbered. Data streams of an iPhone `.mov`
  are ignored; only the first video and audio streams are mapped.
- **Retakes** are found by rule (a run of four or more words that recurs within 20 s; a sentence cut midway and begun again) and written
  into the edit list as proposals, none applied. The page shows them struck through; `base --confirm <id>` cuts only the confirmed ones.
- **Beats.** `align` runs the post-writing skill's own checker (isolated, inside the container) and refuses a post it does not pass;
  NFKC, casefold and punctuation normalised, best window per beat, figures excluded from scoring, a tie goes to the last occurrence, an
  order check, a threshold (0.6 until calibrated in C2). `--anchor <beat>=<from>-<to>` places a beat the aligner could not.
- **Face box and zones.** The person gives the face box once per recording (`--face-box x,y,w,h`; a default is used otherwise). Cards sit in
  the band above it, captions in the band below; every drawn card and caption is measured after each frame and the render fails when one
  touches the face box.
- **Zoom.** Every second kept range is drawn at 1.10 centred on the face box (`--zoom none` turns it off); an optional slow push-in
  (`--push-in 0.04`, per-frame `zoompan`: not yet looked at for jitter).
- **Captions** come in chunks of one to three words, big, with the current word highlighted and popped. **Sound** fades 15 ms at each end
  of every range (a dip, not an overlap: sound and picture stay in step).
- **Output.** 1080x1920 at 30 fps whatever the input (a 4K 60 fps HEVC iPhone clip is scaled down and its frame rate halved; a landscape
  clip is cropped to the centre), H.264 high with AAC, bt709 limited range, metadata (a location) stripped, `-fs` capped, faststart.

## Tests

`uv run --with pytest pytest providers/renderer/tests` (the whole suite takes about three and a half minutes). Browser and ffmpeg tests
skip with a reason where those are absent; the host side runs against a fake docker that executes `_inner.py` with a local Chromium.
`UPDATE_GOLDEN=1` rewrites `tests/golden/*.json` (the exact ffmpeg argv of a plan).

## Not verified here

- **The image has never been built or run**: no build or pull was made. Its package list (the libraries the headless shell links against)
  is from knowledge; the build fails by design at the `ldd` line when one is missing.
- **Chrome with `--no-sandbox` inside the container, and `--disable-dev-shm-usage`, are untested in Docker.**
- Render time in the container, the quality of the presets on a real recording (condition C2), the push-in's jitter, and the font (D6).
- Clips (video assets) are not supported: an asset is a PNG or JPEG; the intake normalises everything else. Transitions other than the
  cutaway's slide are not offered. A brand font is used only from the allow-list, which is empty.
