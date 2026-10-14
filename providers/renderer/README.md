# Renderer provider (`renderer:video`)

Cuts a recording by silence, draws HTML presets over it frame by frame, and composes a vertical video, in a container, and checks the finished file in a second, fresh container before it is given its name. It is the
implementation of the class `renderer:video` (a class the runtime uses and no skill requires: decision D11 of the short-video plan).
Interface: `providers/CONTRACT.md` ("Verbs per class"). No model is involved: the edit list is built by code from a transcript and the
beats come from the post file's script block.

## What is here

| File | What it is |
|------|------------|
| `ffmpeg.py` | The host side, the one implementation file of the folder: checks flags, stages inputs into a private job folder, builds the `docker run` command, runs it, reads the result as untrusted. Python 3.9, standard library only. |
| `_docker.py`, `_browser.py` | The host side's helpers: the container's limits, the build, the state folders; the browser pin and the maintainer's one-time `pin-browser`. Not in the image. |
| `_inner.py` | The container's entry point (`python3 -I /opt/renderer/_inner.py <verb>`): `analyse`, `base`, `align`, `check`, `render`, `cover`, `still`, `selfcheck`. The tests run it directly on the host with a local Chromium. |
| `_edl.py`, `_timeline.py`, `_align.py`, `_vocab.py`, `_text.py` | The edit list and its check, the cuts, captions and retake proposals, the beats and their alignment, the vocabulary's typed parameters, the text rules. |
| `_cdp.py`, `_frames.py`, `_lint.py`, `_render.py`, `_media.py` | The DevTools-pipe driver, the frame loop and what is served to the page, the determinism lint, the render, ffprobe/ffmpeg and the one compose command. |
| `_redact.py` | A generated copy of `shared/scripts/redact.py` (the credential formats `check` scans with). |
| `templates/*.html`, `templates/pins.json` | The presets (`caption`, `keyword`, `list`, `number`, `quote`, `cutaway`, `pip`), each a pure `renderAt(t, data)`, each pinned by sha256. |
| `renderer-presets.json` | What the renderer decides about `shared/references/video-presets.json` (frame, zones, cuts, zoom, timing, limits). The vocabulary itself is read by flag. |
| `edl.schema.json` | The renderer-neutral edit list and beats. |
| `browser-pin.json`, `Dockerfile`, `.dockerignore`, `_fetch_browser.py` | The image's definition and the pins it is built from. |
| `assets/fonts/` | The fonts a render may use (decision D6): Inter 500 and 800 and JetBrains Mono 500 as woff2, their SIL OFL 1.1 texts and `allowlist.json` (sha256, licence, source). The provenance is the weaker one the file says: Fontsource's Latin subsets, package version not recorded. A font not listed is never used; the render says which font each role used (`fonts`). |

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
| a refusal inside is the same refusal outside, in closed words only; what the host prints is rebuilt from a closed schema (only understood fields, short strings without control characters, finite numbers, an integer `beat`) | `test_a_refusal_inside_the_container_is_the_same_refusal_outside...`, `test_what_the_host_prints_is_rebuilt_from_a_closed_schema`, `test_problems_hold_an_integer_beat_and_closed_words_only` |
| the container's stderr is read up to 64 KiB (the rest is thrown away) and never printed: a crash is a closed code, not a traceback; an error nobody foresaw inside is a result with the code `internal` | `test_the_containers_stderr_is_read_up_to_a_cap_and_never_printed`, `test_a_container_that_crashed_prints_no_traceback_only_a_closed_code`, `test_an_unforeseen_error_in_the_container_writes_a_closed_internal_result` |
| the output is checked outside the container that made it: `render` copies the candidate into a private file (hashed on the way, capped by the platform's byte limit), runs `verify` in a fresh container (the render read-only, no network, every limit as above: ffprobe facts against the platform's spec, bt709 tags, length, sha256), and names the file only after that passes | `test_the_host_stores_a_render_only_after_a_fresh_container_has_verified_it`, `test_verify_*` |
| the scratch is memory-backed and counts against the memory limit: it may not exceed the memory less 2048 MB (a refusal, not an OOM kill); memory is at least 3072 MB | `test_the_scratch_never_exceeds_the_memory_less_a_margin` |
| room for the output is checked before a run; a file system without hard links still gets a named, never rewritten copy (copied, fsynced) | `test_there_must_be_room_for_the_output_before_the_container_runs`, `test_a_file_system_without_hard_links...` |
| a killed run's leftovers are reaped | `test_reap_removes_containers_past_their_deadline...` |

### The browser's sandbox: a choice, with its price (principle 13)

Chrome's own sandbox needs user namespaces, which `--cap-drop ALL`, `no-new-privileges` and Docker's default seccomp profile take
away. Two ways out: a seccomp profile that allows Chrome's sandbox (a wider syscall surface for the whole container, and not testable
here), or `--no-sandbox` **inside the image only**, with the container as the boundary. The second is chosen.

- **What it saves:** every limit above stays as strict as it is; no custom seccomp profile to keep right.
- **What it gives up:** a renderer-process exploit is no longer contained by Chrome's sandbox, only by the container: no network, a
  read-only root, no capability, a non-root user, limits, three mounts. **The residual risk is what those three mounts allow:** code
  running in the container can read the recording (`/in/recording`) and everything staged in `/job` (the transcript, the post, the
  assets), and can write `/out`, which the host then reads as untrusted (looked at, size-capped, hashed, never followed, and the render
  verified in a fresh container before it is kept). It cannot reach the network, so nothing can leave the machine. What reaches the page is small: the pinned templates, text drawn
  with `textContent`, and image assets the person uploaded (PNG or JPEG, checked by bytes, bounded, never animated, decoded by the
  browser). A page request is answered from memory or failed, and a content-security policy is set. The recording never reaches Chrome.
- **Never silent:** `_cdp.container_mode()` is true only when `RENDERER_IN_CONTAINER=1` **and** `/etc/openhora-renderer-image` exists (the
  image writes it). Nowhere else is the sandbox off; on the host it is on and a failed start is a failure with no retry. Every render's
  result says `browser_sandbox` (`on` or `off`). Tests: `test_the_browsers_own_sandbox_is_on_everywhere_but_the_image...`,
  `test_inside_the_image_the_sandbox_is_off_and_says_so`.
- **A browser that does not start says why.** `browser_failed` carries a `reason`: the kind of error and the first four lines of the
  browser's own log, each redacted, control characters removed, at most 200 characters. It crosses the closed result schema as one
  plain string, is printed on stderr as `  reason: ...` and is a `reason` key of the failure's JSON on stdout.
  The browser is started without a shell (a short interpreter step puts the pipes on fd 3 and 4 and replaces itself with the browser; when
  that fails it writes `exec failed: <errno name>` to the browser's log, which the reason then carries), so the image's `/bin/sh`
  (dash) is not involved.

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
  indices, slot ids (never a description or a file). A beat's optional `role` and `emphasis` (closed lists of the vocabulary's `script`
  section, version 2 of the file) are written into its entry and its `report` item, and the script header's `title` and `loop` into an
  optional `script` object; the rest of the header stays in the post file. A beats file without these fields stays valid and stays
  `schema_version` 1. The vocabulary file is read at version 1 or 2, never 3.
- `render` takes both, the recording, the platform file and the person's asset files by slot, and writes `render-<sha12>.mp4`, 0400,
  never rewritten, after checking the file against the platform's video spec. What an implementation owns is only how it draws.
- Selection is `RENDERER_VIDEO_PROVIDER` / `RENDERER_PROVIDER` (or the runtime's configuration), as for every class.

## The still frame (`still`)

`still --in <recording> --at-ms <n> --out <dir>` writes one PNG of the recording at that time, framed exactly as the render frames the source
(`_media.framing_filter`, the one text the render's graph and the still share: scaled to cover twice the frame, the centre cropped, then
the plain scale of an unzoomed range down to 1080x1920), so the face box the person draws on it is in the render's pixels. The page builds no
images and nothing outside the container decodes a recording: this is the one place a still is made. The recording is read with
`-f mov -protocol_whitelist file -enable_drefs 0` and the container has every limit of `analyse` and `render`. The host stores the file as
`still-<sha12>.png` (0400, never rewritten, the same bytes are a replay) after checking, itself, the hash, the PNG header, the 1080x1920
size and an 8 MiB cap. An offset outside the recording is `bad_still_offset`. Test: `tests/test_renderer_still.py`, which also holds the
still equal, within the codec's loss, to the render's own first picture of a range that starts at that frame.

## What the edit does

- **Cuts.** Silence is the signal (`silencedetect`, -35 dB, 0.25 s): every silence is cut, less 0.14 s after its start (the tail of the
  word before it, `--pad-tail`) and 0.10 s before its end (the attack of the word after it, `--pad-head`). Words only protect speech,
  and only the words that have energy: a word that silence covers for 80 percent of its span is a phantom (a transcriber puts words
  into the quiet start of a recording) and protects nothing; a word stretched far past what it takes to say is protected only for that
  time, so a silence inside its span is still cut. No range with a word is kept shorter than 0.4 s (it is joined to its neighbour), and
  a range with no real word that is shorter than 1.5 s (`wordless_keep`: a cough, the speaker moving) is cut. **A long cut takes the
  wordless sound at its edges:** after a cut of 2 s or more (`--long-cut`), a range that begins with more than 0.3 s (`--wordless-max`)
  of sound before its first word (a breath, a head turning back to the camera) begins at that word less `--pad-head`; symmetrically a
  range before such a cut ends at its last word plus `--pad-tail`. Without audio, word gaps over 0.5 s decide.
- **Audio and picture start together.** The streams' `start_time` is read: the picture is started at zero (`fps=...:start_time=0`) and the
  sound is padded to zero (`aresample=async=1:first_pts=0`) before either is cut, so an audio stream that starts after the video stays in
  step. The renderer's clock is the container's; the transcript's times are taken to be on it (a transcriber that cuts the audio out of a
  recording must keep an audio stream's offset).
- **A real transcript's shapes.** Words of zero length are spread evenly to the next word (at least 40 ms) and flagged `estimated`; a start
  that goes back in time is clamped; a segment of three or more words faster than 8 words a second (a repeated sentence squeezed into
  a fraction of a second) is dropped, all reported in `normalisation`. A word that silence covers by at least 80% is misplaced, not absent (a transcriber squeezes words it could not time into the quiet next to them, such as an opening hook into the leading silence): it keeps its caption and its index and is moved into the voiced span next to it (before the cuts are planned, so the cuts protect it where it is said; a short word, 0.25 s or less, in a pause under 0.5 s between two words is a soft word in its place and stays), after the silence when a live word follows inside the same kept range (spread evenly up to that word, each at least 0.12 s), else before it; `normalisation.retimed_words` lists `{index, from, to}` for the caption review, and `unplaced_words` the ones with no voiced span, left out of the captions (index and source times, never the text). Word indices are never renumbered. The edit list is `schema_version` 2 (a version 1 list is refused as `edl_schema_outdated`). Data streams of an iPhone `.mov`
  are ignored; only the first video and audio streams are mapped.
- **Retakes** are found by rule (a run of four or more words that recurs within 20 s; a sentence cut midway and begun again) and written
  into the edit list as proposals, none applied. The page shows them struck through; `base --confirm <id>` cuts only the confirmed ones.
- **Beats.** `align` runs the post-writing skill's own checker (isolated, inside the container) and refuses a post it does not pass;
  NFKC, casefold and punctuation normalised, best window per beat, figures excluded from scoring, a tie goes to the last occurrence, an
  order check, a threshold (0.6 until calibrated in C2). `--anchor <beat>=<from>-<to>` places a beat the aligner could not.
- **Face box and zones.** The person gives the face box once per recording (`--face-box x,y,w,h`; a default is used otherwise). Cards sit in
  the band above it (from y 110 down to the face less 18 px), captions in the band below it (from the face plus 18 px down to y 1620); the
  type is the largest that fits the band (a short band gives small type, never a card over the face). Every drawn card, chip and caption
  word is measured after each frame and the render fails when one touches the face box. **The box is the zoomed one:** a zoomed range
  is a punch-in about a fixed point (the face's horizontal centre, a quarter of its height down from its top, `--zoom-anchor-y`), so the
  face's box grows about that point; the bands of a card or caption are computed from the union of the face's box over every range it
  lives through (factor and push-in included), and `base` refuses a face box that leaves less than 80 px above or 120 px below at the
  largest zoom.
- **Zoom.** Every second kept range is drawn at 1.10 (`--zoom none` turns it off) about the anchor, from a picture cut at twice the output
  size so a zoom never upscales; a range of 5 s or more also pushes in by 2 percent (`--push-in`, at most 3 percent).
- **Captions** come in chunks of one to three words on one line, as big as fits, with the current word highlighted and popped over a dark stroke. **Sound** fades 15 ms at each end
  of every range (a dip, not an overlap: sound and picture stay in step).
- **Output.** 1080x1920 at 30 fps whatever the input (a 4K 60 fps HEVC iPhone clip is scaled down and its frame rate halved; a landscape
  clip is cropped to the centre), H.264 high with AAC, bt709 limited range, metadata (a location) stripped, `-fs` capped, faststart.

## What makes a render the same bytes, and what can still differ

Pinned in the compose command (`_media.compose_argv`): the encoder's threads (`-threads 4`: x264's output depends on its thread count, and
the automatic count follows the cores the machine shows, 14 inside the container whatever the CPU quota), the filter graph's threads
(`-filter_threads`, `-filter_complex_threads`, 4, which also fix swscale's slice count), `-sws_flags` and the flags of every explicit
`scale` (`lanczos+accurate_rnd+bitexact`: the same arithmetic whatever SIMD the CPU has), `+bitexact` on the muxer, the video and the
audio, and no metadata. The decoder's threads are pinned too (4) but a decoder is exact whatever the count: that pin changes speed only.

Measured (15 s of the real 4K 60 fps recording, in the container, `docker run --cpuset-cpus` so that the container really sees 4, 8 or
14 cores): the pinned command gave the same sha256 at 0-3, 0-7 and 0-13; the same command without the pins gave a different sha256 at
each. (`--cpus` alone proves nothing: it is a quota, and the container still sees every core.)

What can still differ, and is not claimed away: an `amd64` image against the `arm64` one (another ffmpeg build, other SIMD paths; the
`zoompan` filter scales with its own bicubic call, which no flag reaches), another ffmpeg or x264 version (the image pins Debian's
snapshot, so a rebuild from the same definition gives the same ones), and Chrome's rasterisation of the overlay frames on another CPU
architecture (the frames are PNGs drawn by the browser; two browsers on one machine drew identical frames, a test checks it). A render is
reproducible on the same image and CPU architecture; across architectures it is expected to look the same, not to be byte-identical.

The container gets 8 CPUs by default (`--cpus`, never more than the daemon has): the compose of a 104.7 s render waits for the CPU quota,
and 8 against 4 took it from 366 s to 161 s, with the same bytes.

## Tests

`uv run --with pytest pytest providers/renderer/tests` (the whole suite takes about five minutes). Browser and ffmpeg tests
skip with a reason where those are absent; the host side runs against a fake docker that executes `_inner.py` with a local Chromium.
`UPDATE_GOLDEN=1` rewrites `tests/golden/*.json` (the exact ffmpeg argv of a plan).

## Not verified here

- **The `arm64` image was built and run on one machine** (Docker 29.3.1, Apple silicon): the build, its self-check, every verb and a
  render of a real 192 s 4K 60 fps recording (104.7 s out, 197 s at 8 CPUs, 408 s at 4) ran there, with Chrome's sandbox off and
  `--disable-dev-shm-usage`. **An `amd64` image has not been built or run**, and neither has any other machine's Docker. The package list
  is checked by the build (it fails at the `ldd` line when a library is missing).
- The quality of the presets beyond that one recording (condition C2), and the push-in's jitter.
- **Assets are only header-checked here** (PNG or JPEG by bytes, bounded, never animated). The renderer treats every asset as untrusted
  and the browser decodes it, so P4 and P4b must normalise assets (re-encode to a metadata-free PNG at frame size) before they reach it.
- Clips (video assets) are not supported: an asset is a PNG or JPEG; the intake normalises everything else. Transitions other than the
  cutaway's slide are not offered. A font is used only from the allow-list (Latin subsets of three Inter and JetBrains Mono files).

## Limits that match the plan

The recording length bound is 300 s (`limits.input_seconds_max`, decision D8): intake enforces it, and the renderer matches it as defence
in depth (`analyse`, `base` and `render` refuse longer). The output length is the platform file's maximum.
