# Renderer provider (`renderer:video`)

Cuts a recording by silence, draws HTML presets over it frame by frame, and composes a vertical video, in a container, and checks the finished file in a second, fresh container before it is given its name. It is the
implementation of the class `renderer:video` (a class the runtime uses and no skill requires: decision VD2 of `docs/decisions/2026-11-07-v0-short-video-hyperframes.md`).
Interface: `providers/CONTRACT.md` ("Verbs per class"). No model is involved: the edit list is built by code from a transcript and the
beats come from the post file's script block.

## What is here

| File | What it is |
|------|------------|
| `ffmpeg.py` | The host side, the one implementation file of the folder: the drawing verbs (`render`, `storyboard`, `pin-blocks`, `block-params`), `build`, `pin-browser`, `reap` and `--check`; the verbs that need no browser come from `_host.py`. Python 3.9, standard library only. |
| `_host.py` | The host side both engines share: one job in a container (stage the inputs into a private job folder, build the `docker run` command, run it, read the result as untrusted), the limit flags, and the common verbs `analyse`, `base`, `align`, `check`, `cover`, `still` and `verify` (`COMMON_VERBS`, `add_common_parsers`). `verify --in MP4 --platform-file F [--sha256 H] [--edl EDL]` checks a stored render in a fresh container, as `render` checks its own candidate. Not in the image. |
| `_docker.py`, `_browser.py` | The host side's helpers: the container's limits, the build, the state folders; the browser pin and the maintainer's one-time `pin-browser`. Not in the image. |
| `_inner.py` | The container's entry point (`python3 -I /opt/renderer/_inner.py <verb>`): `analyse`, `base`, `align`, `check`, `render`, `storyboard`, `verify`, `cover`, `still`, `selfcheck`. The tests run it directly on the host with a local Chromium. |
| `_retakes.py` | The retake rule (see "Retakes" below): standard library only, in the image. |
| `_edl.py`, `_timeline.py`, `_align.py`, `_vocab.py`, `_text.py`, `_media.py` | The common part, which imports nothing of the browser, the frames or the storyboard (a test walks the imports): the edit list and its check, the cuts, captions, the beats and their alignment, the vocabulary's typed parameters, the text rules, ffprobe/ffmpeg and the one compose command. |
| `_layout.py`, `_assets.py`, `_output.py` | Also common: the bands the face box leaves, the face test and the 1560 caption test (`zones`, `face_hit`, `caption_hit`); the allow-listed fonts and the image assets with the safe read (`font_allowlist`, `load_fonts`, `load_assets`, `read_regular`); the platform file's read, `cover`, `still` and the never-rewriting write (`read_platform`, `make_cover`, `make_still`, `png_size`, `write_once`). The old modules import the moved names back. |
| `_cdp.py`, `_frames.py`, `_lint.py`, `_render.py` | The drawing part, the ffmpeg engine's own: the DevTools-pipe driver, the frame loop and what is served to the page, the determinism lint, the render. `_inner.py` imports them inside `render`, `storyboard` and `selfcheck` only. |
| `_preview.py` | The storyboard (`storyboard --post FILE --checker SCRIPT \| --beat FILE`): synthetic words at 2.5 a second, the render's own checks, the render's frame loop given only each beat's rest frame, a flat neutral picture behind it, and a contact sheet from one ffmpeg command. No recording, no transcript. The catalogue verb reuses it. |
| `_redact.py` | A generated copy of `shared/scripts/redact.py` (the credential formats `check` scans with). |
| `_blocks.py` | Common: the catalogue of animation blocks. Loads and checks `blocks/` (every file against `blocks/pins.json`), resolves the block that draws a beat on an engine and refuses one the engine cannot draw (`block_not_on_engine`), checks a block's parameters (the renderer-side checker, VD15), writes the pins and the generated catalogue. |
| `blocks/` | The blocks (V3b0): `oh/<name>/block.json` and `renderat.html` for `caption`, `keyword`, `list`, `number`, `quote`, `cutaway`, `pip` (each page a pure `renderAt(t, data)`, byte for byte the old template; the `pip` page of V9e is a card: the speaker stays full frame, ffmpeg composes the asset into a rounded card below the face, `_layout.pip_cards` settles its box (the whole room from the face to the caption line) and the captions' band (the card's lower part, the caption drawn over it), a pip with no room is dropped with `pip_no_room` in the optional `beats_dropped_reasons`, and the page draws only the shadow and the label); `engines/ffmpeg.json` (the runtimes the engine runs and its block per preset); `hf/allowlist.json` (empty: no registry component is admitted) and `hf/<name>/` (`block.json` and `gsap.html` of the five tier-B ports of V3b-4); `pins.json` (sha256 of every file above); `catalogue.json` (generated, VD13); `block.schema.json` (the schema, for readers). Not in the image: each render or storyboard job stages a copy read-only. |
| `renderer-presets.json` | What the renderer decides about `shared/references/video-presets.json` (frame, zones, cuts, zoom, timing, limits). The vocabulary itself is read by flag. |
| `edl.schema.json` | The renderer-neutral edit list and beats. |
| `browser-pin.json`, `Dockerfile`, `.dockerignore`, `_fetch_browser.py` | The image's definition and the pins it is built from. |
| `assets/fonts/` | The fonts a render may use (decision VD6): Inter 500 and 800 and JetBrains Mono 500 as woff2, their SIL OFL 1.1 texts and `allowlist.json` (sha256, licence, source). The provenance is the weaker one the file says: Fontsource's Latin subsets, package version not recorded. A font not listed is never used; the render says which font each role used (`fonts`). |

## The container (decision VD4)

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
  verified in a fresh container before it is kept). It cannot reach the network, so nothing can leave the machine. What reaches the page is small: the pinned blocks, text drawn
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

## The blocks (V3b0)

A block is named `<namespace>:<name>`: `oh:` blocks are ours, `hf:` blocks come from the HyperFrames registry (V3b). `blocks/engines/<engine>.json`
says which drawing runtimes an engine runs (`ffmpeg`: `renderat`) and which block draws each preset by default; a beat may name another
block of the same preset (`block` in `beats.json`). A render or a storyboard copies `blocks/pins.json` and every file it pins into the
job's read-only folder, loads the catalogue from that copy, and passes its sha256 to the container, which checks it again; the result
names it (`blocks_sha256`) with the sha256 of each drawn block (`blocks`). The image holds no block, so a block change rebuilds nothing.
After a reviewed change of a block: `python3 providers/renderer/ffmpeg.py pin-blocks --confirmed` (pins and catalogue). Tests:
`tests/test_renderer_blocks.py`.

Three presets are review-only (V9a-1): `mark` (a short phrase with a hand-drawn underline, circle or arrow), `sticker` (one of twelve drawn glyphs) and
`nametag` (a lower third). They are declared in the `review_presets` section of `renderer-presets.json`, beside the timings in `presets`;
`_vocab.load_vocabulary` merges them into the vocabulary it returns with `review_only: true` (a name the vocabulary already holds as its own is refused
`vocabulary_clash`), and `_align.read_script` refuses a script row that names one (`preset_review_only`): the person adds them at review, and the script's
checker never sees them. Each is an `oh:` block (`blocks/oh/mark`, `sticker`, `nametag`: a `block.json` and a `renderat.html`, card band, never across the
face) named by both engine files. Tests: `tests/test_renderer_review_presets.py`.

## The HyperFrames engine's composed page (V3b-1)

`hyperframes.py render` without `--base-only` draws the captions and the beats. `hyperframes.py` answers `block-params` like `ffmpeg.py` (the same host function, with `engine` `hyperframes`). The page stage (`hf-page` with `--blocks` and `--blocks-sha256`)
runs in the common image: `_hf_compose.py` writes one root composition, `index.html` (structure and numbers only), `vars.json` (every text) and
`blocks/<ns>-<name>.html` for the `renderat` blocks. A block is drawn with its `gsap.html` when the engine runs `gsap` (the fragment of
`_gsap_lint.py`, inlined once per entry in an instance clipped to its band and scoped with `@scope`) and with its `renderat.html` otherwise (one
iframe per block, driven by one getter/setter tween). The theme's fonts are the three allow-listed files (`fonts/`, copied into the project by
`hyperframes-image/hf_render.py`); `default` means Inter 800, Inter 500 and JetBrains Mono 500 for display, text and mono (`fonts_used` says so).
The staging, the `blocks_sha256` check and the engine file work as in `ffmpeg.py`. Tests: `tests/test_hf_compose.py`, `tests/test_gsap_lint.py`.

Every render that draws runs the gates of V3b-2, and nothing turns them off. After the drawing, the HyperFrames container runs
`hyperframes-image/hf_measure.mjs`: it serves the project on the loopback, seeks every frame as the renderer does and writes the boxes the page
reports (every visible box inside a `gsap` instance clipped to its band, every `data-zone` box of a `renderat` page, and the rectangles of the text
unclipped) into `boxes.json`. The encode container (`_hf_gate.py`, in the common image where `_layout` and `_edl` live) reads it with its sha256 and
refuses, before the encode, a box that touches the face box of its frame (`overlay_hits_face`) or a caption box whose bottom is below the band's
bottom, 1560 on the presets (`caption_below_line`), with the ffmpeg engine's own arithmetic. After the encode it compares the face region of every
kept range of the intermediate with the same region of the base the ffmpeg engine would draw (the proxy, cut and zoomed by `_media.base_graph`) frame
by frame with `psnr`, and refuses `face_pixels_changed` under 30 dB: that is what sees a block that draws on the face with no box of its own. The
proxy is hashed again in the encode container, since the drawing container could write to it. Tests: `tests/test_hf_gate.py`,
`tests/test_hf_measure_static.py`.

## Tier A: registry components (V3b-3)

A component of the HyperFrames registry is drawn only after `hyperframes.py compat --survey <dir> --out <file>` ran its admission in the
HyperFrames image (no network, the survey mounted read-only): `hf_compat.py` first refuses every planted escape (a list of more than a dozen
fictional components, each doing one thing a block may not; one admitted fails the run, and there is no flag that skips the step), then gives each
component of the survey `admit-candidate` or `refuse:<code>` (licence, name, files all fetched, the two files needed, kind, the lint of `hf_wrap.py`,
parameter names). Tier A admits overlays only; a caption is only a reviewed port. An admitted block is an entry of `blocks/hf/allowlist.json` with
its files' sha256; a render that draws one writes a placeholder and a row of `instances.json`, and `hyperframes-image/hf_render.py` reads the files from the
image's registry folder, checks each hash, lints and wraps the component (`@scope`, a guarded `window` and `document`) and refuses
`tier_a_file_missing`, `tier_a_hash`, `block_lint` or `block_escaped`. Tests: `tests/test_hf_wrap.py`, `tests/test_hf_compat.py`,
`tests/test_hf_registry.py`.

## The HyperFrames ports (V3b-4)

Five blocks under `blocks/hf/` are our own rewrites of components of the HyperFrames registry at commit `b4cc674f`, each one a `gsap.html` of the
contract of `_gsap_lint.py` and nothing else (no `renderat` page: an `hf:` block draws on the HyperFrames engine only and is refused
`block_not_on_engine` on the ffmpeg engine). They are `hf:caption-highlight` and `hf:caption-pill-karaoke` (the caption), `hf:count-up` (`number`),
`hf:testimonial-card` (`quote`) and `hf:spring-pop` (`keyword`); each declares exactly its preset's parameters and draws every one of them. The
caption ports are bottom-anchored in the caption band and size their type by arithmetic from the band's height and the words' length, so the lowest
glyph stays above the band's bottom (1560 on the presets); the registry's slam style is not ported (S2 measured 50 face hits). The final
`blocks/engines/hyperframes.json` runs `gsap` and `renderat` and names `hf:caption-highlight`, `hf:spring-pop`, `hf:count-up`, `hf:testimonial-card`
and `oh:list` for `caption`, `keyword`, `number`, `quote` and `list`; any `oh:` block stays selectable by name, and the engine draws no `cutaway` and no
`pip`. The licence text of the registry (`hyperframes-image/LICENSE-registry-Apache-2.0.txt`) and one notice entry per port
(`hyperframes-image/NOTICE.md`) travel in the image folder, because nothing but pinned files may live under `blocks/`. Tests: `tests/test_hf_ports.py`.

Two of the ports were fixed in V9a-1. `hf:spring-pop` sets its stage's layout inline and sizes its type with a pure function `fit(text, bandHeight)` (up to 150
px on 950 px, two lines for a text longer than 12 characters, split at the space nearest the middle), so the card draws centred and large. `hf:caption-highlight`
gets each word's lit span from a pure function `spans(words)` (monotone starts, an end never later than the next start), so one word is lit at a time and a
word of no length never lights. Tests: `tests/test_hf_fixes.py`. Their rows of `hyperframes-image/NOTICE.md` are the maintainer's to approve (STOP E).

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
- Selection: a project's `media.renderer` (`auto`, absent, or a name), then `RENDERER_VIDEO_PROVIDER` / `RENDERER_PROVIDER` for `auto`, then the class default,
  `hyperframes` since V4.

## The engine contract (V3c)

Both engines promise the same things about a render, and one live file, `tests/test_engine_contract_live.py`, runs the same synthetic inputs
through `ffmpeg.py` and `hyperframes.py` (the engine is a pytest parameter) with the same assertions. The code that makes the inputs, the
report's closed schema and the memory sampler are in `tests/contract_kit.py`; the offline tests of the kit are `tests/test_engine_contract.py`.

| # | Promise | Where it is made | Leg |
|---|---|---|---|
| C1 | `render-<sha12>.mp4`, mode 0400, never rewritten, checked in a fresh container before it is named | `_host.finish_render` | F1 |
| C2 | the platform's video spec, bt709 tags, the length is `out_frames/fps` | `_inner.verb_verify`, `_media.check_output` | F1 |
| C3 | audio is kept when the recording has it | `_media.compose_argv`, `_inner.verb_encode` | F1 |
| C4 | the edit list is what is drawn: every output frame is the source frame the kept ranges name | `_media.base_graph`, `_hf_page` | F2 |
| C5 | nothing drawn touches the face box | `_frames.draw_frames`, `_hf_gate.check_boxes`, `pixel_check` | F5 |
| C6 | no caption ends below 1560 | the same | F6 |
| C7 | a beat the engine cannot draw is refused before drawing | `_blocks.resolve` | F7 |
| C8 | the recording is the one the list was made from, at most 300 s | `_output.check_recording` | F7 |
| C9 | same input, same bytes, whatever the cores | `compose_argv`, `encode_argv`, `proxy_argv` | F3, F4, M1, M2 |
| C10 | limits in code (memory, pids, workers, free space, 1800 s) | `hyperframes.py`, `_docker.py`, `_output.py` | M2, M3 |
| C11 | a refusal leaves no file, no container, no run folder | `finish_render`, `Job` | every leg |
| C12 | a caption with words draws glyphs (`caption_not_drawn`, HyperFrames) | `_hf_gate.check_boxes` | F8 |

Both engines also answer `block-params` (the host-side checker of an added animation, from the same function of `_host.py`; `test_renderer_contract.py` keeps that true for every implementation of the class).

Two kinds of leg. The functional legs F1-F8 run on short inputs, in CI's renderer job (the ffmpeg parameter, `WB_RENDERER_DOCKER_TESTS=1`), in CI's
`hyperframes` job (V3c-2: both images built on the runner, the amd64 `hyperframes.py --check`, then this file and `test_hf_docker_live.py` with
`WB_HYPERFRAMES_DOCKER_TESTS=1`) and on the maintainer's machine (both, with `WB_HYPERFRAMES_DOCKER_TESTS=1`). The machine legs `test_mac_*` (M1 the short case at 4 and 8 cores,
M2 a real-size case of about 196 s and 37 kept ranges at 4 and 8 cores, M3 a 298 s input on HyperFrames once) need 8 cores and run only with
`WB_ENGINE_MAC_LEGS=1`, one after another; with `WB_ENGINE_REPORT=<a new file>` they write the report, `reports/engine-contract-<date>-<arch>.json`,
checked by `contract_kit.check_report` (closed: hashes, numbers, closed words, a date; no path, no word of a transcript).

The band: the synthetic recording carries its own frame number as 14 cells of 72 px (black or white, least significant bit on the left) at the
top of the picture, above the cards, so F2 reads which source frame every output frame is. On the real-size legs the edit list keeps the real
shape, zoom included, so the check there covers the ranges drawn unzoomed (the band is scaled in a zoomed range).

The planted blocks (`contract_kit.planted_renderat`, `planted_blank`) live only in test temp folders and reach a render through
`RENDERER_TEST=1` and `RENDERER_BLOCKS_DIR`, which both engines now honour.

### Punches and grades (V9a-3)

The script's `emphasis: punch` (beats.json `punches`, written by `align` for a beat with or without a preset) and the review's effects (beats.json
`effects`: `punch`, `flash`, `dip`, `mono`, `tint`) change the base picture, never a zone. `_edl.resolve_timeline` turns them into whole-frame rows
(`punches`, `grades`, `effects_dropped`), `_edl.range_effects` into one table by kept range in the range's own frame index, and three drawings read that
table: `_media.base_graph` (the ffmpeg engine: a step in the `zoompan`/`perspective` expression, an exact per-plane blend (`lutyuv`, `_media.blend_filter`) for flash, dip and tint, `colorchannelmixer`
with the CSS `grayscale(1)` matrix for mono), `_hf_page.build_parts` (the HyperFrames page: one drive tween per punched range, one `#fx` layer under every
overlay, `filter: grayscale(1)` on the range's wrapper) and `_hf_gate.reference_graph` (the face check's reference holds the same punches and grades, so
the pixel check still catches anything else drawn on the face; the crop of a punched range is the union of its faces). The bounds are in code
(`_edl.EFFECTS_MAX`, `FLASH_FRAMES_MAX`, `DIP_FRAMES_MAX`, `FLASHES_MAX`, `GRADE_SECONDS_MAX`) and `renderer-presets.json` (`punch`, `effects`) cannot widen
them. A render with no punch and no effect writes the bytes it always wrote (a golden test of the graph and of the page).

## The still frame (`still`)

`still --in <recording> --at-ms <n> --out <dir>` writes one PNG of the recording at that time, framed exactly as the render frames the source
(`_media.framing_filter`, the one text the render's graph and the still share: scaled to cover twice the frame, the centre cropped, then
the plain scale of an unzoomed range down to 1080x1920), so the face box the person draws on it is in the render's pixels. The page builds no
images and nothing outside the container decodes a recording: this is the one place a still is made. The recording is read with
`-f mov -protocol_whitelist file -enable_drefs 0` and the container has every limit of `analyse` and `render`. The host stores the file as
`still-<sha12>.png` (0400, never rewritten, the same bytes are a replay) after checking, itself, the hash, the PNG header, the 1080x1920
size and an 8 MiB cap. An offset outside the recording is `bad_still_offset`. The host also refuses a result whose `at_ms` is not the request or whose `bytes` is not the file's size. Adding this verb changed the image definition, so the tag changed: until the maintainer runs `build --confirmed` the new tag does not exist and every renderer step reports `image_not_built` (not `image_stale`, which is for an image that exists and is older than the files). Test: `tests/test_renderer_still.py`, which also holds the
still equal, within the codec's loss, to the render's own first picture of a range that starts at that frame.

## The storyboard (`storyboard`)

What a script's beats will look like, before a recording exists. The verb takes a post (`--post`, with the post-writing skill's own checker, as `align` does) or one beat as JSON (`--beat`: `preset`, `params`, `line`), the vocabulary, and the theme flags of `base` (`--face-box`, `--color`, `--font`). **No recording and no transcript go in, and the container mounts none** (two mounts: the staged job folder and the output folder). In order: the checker refuses a post it does not pass (`--beat`: the typed parameters are checked by `_vocab.check_params`); each beat's line becomes words spoken at 2.5 words a second (`renderer-presets.json`, `storyboard`), one beat after another with 2 s between them and 2.5 s after the last, with no cut and no zoom; `_edl.build_base` makes the edit list and `_align.build_beats` the beats list; `check_documents` (the credential scan included) runs, **and a refusal there means no frame was drawn and no browser started**; then the render's frame loop (`_frames.draw_frames`, with an `only` filter that the render does not use) draws one frame per beat, the one where the overlay has settled (`settled` seconds into the beat, per preset, in `renderer-presets.json`; a beat too short for that, its end less its tail less one frame), over an opaque neutral picture, **and runs every other frame of every beat through the page and the face-box check without writing it** (a card overshoots while it pops in), so the face check is the render's, frame for frame; a layout's asset slot is a flat generated colour, never a file of the person; a card that touches the face box is the render's `overlay_hits_face`. `beat-<n>.png` (1080x1920) for each beat with a preset and `sheet.png` (a grid of 270x480 tiles, four to a row, no text) are written read-only, never over a file that is there; the host trusts nothing the container reports about them: every key must be there, a still is the frame's size, the sheet is the grid the presets give for that many tiles, all under a fixed ceiling, each file hashed and its header checked before it is named. A script over the 300 s input bound is refused as `script_too_long`. A platform file that is not a JSON object is refused as `bad_platform` by `render`, `verify` and `check`. The same inputs give the same bytes on the same image and architecture, whatever the cores or jobs.

## The preview (`preview`, V3d)

`preview --in <render> [--sha256 <hex>] --out <dir>` makes a smaller copy of a finished render for a phone, whose messaging app takes at
most 20 MiB (Telegram) or 16 MB (WhatsApp through Twilio): 720x1280 H.264 at CRF 23, capped by a rate computed from the render's length
so that the whole file fits 15 MiB with 6 % room (60 s: 1843 kbit/s; 300 s: 296 kbit/s), AAC at 96 kbit/s, the bt709 tags, the index
first. The numbers are the block `preview` of `renderer-presets.json`. The encode is pinned as the final encode is (decoder, filter
graph and x264 on one thread, bit-exact scaling), so the same render gives the same bytes at any CPU count. The container checks the
render's hash, its length, the copy's size, frame, length and audio; the host hashes the file on the way out, refuses more than 15 MiB, a
result that names another render, and a file that is not an MP4 with its index first, and stores it as `preview-<sha12>.mp4` (0400,
never rewritten). The runtime asks for it only for a render larger than 15 MiB (`runtime/step_media.py`, the side step `preview`). This
verb is not `_preview.py`, which is the storyboard's module. Adding it changed the image definition (no file was added), so the tag changed:
until `build --confirmed` runs again every renderer step reports `image_not_built`. Measured with a local ffmpeg on synthetic test
patterns: 60 s in 21 s (14,101,201 bytes), 300 s in 72 s (15,053,020 bytes). Tests: `tests/test_renderer_preview.py`; in a real container,
`test_the_preview_of_a_60_second_render_fits_15_mib_at_720x1280_and_is_the_same_bytes_at_two_and_four_cpus` of
`tests/test_renderer_docker_live.py`.

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
  a fraction of a second) is dropped, all reported in `normalisation`. A word that silence covers by at least 80% is misplaced, not absent (a transcriber squeezes words it could not time into the quiet next to them, such as an opening hook into the leading silence): it keeps its caption and its index and is moved into the voiced span next to it (before the cuts are planned, so the cuts protect it where it is said; a short word, 0.25 s or less, in a pause under 0.5 s between two words is a soft word in its place and stays), after the silence when a live word follows inside the same kept range (spread evenly up to that word, each at least 0.12 s), else before it; `normalisation.retimed_words` lists `{index, from, to}` for the caption review, and `unplaced_words` the ones with no voiced span, left out of the captions (index and source times, never the text). A run of `phantom_run_min` (3) or more words in a row, each at most `phantom_max_seconds` (0.02 s) long and starting inside a silence (within `phantom_edge_seconds`, 0.05 s, of it; the block `cuts` of `renderer-presets.json`), whose folded text also repeats the words said just before it (its first `phantom_repeat_min` tokens, 5, or all of them when the run is shorter, found in order among the last 40 or twice-the-run tokens before it) is a transcriber's repetition hallucination in silence (typically the last sentence written again at the end of a file): the words are dropped (`dropped`, like a dropped segment) before the retakes, the kept ranges and the captions are planned, so they make no island range and no caption; `normalisation.phantom_words` lists `{from, to, count}` index ranges (optional in the edit list: an older list has none), the caption review shows them as left out (`phantom`), and word indices are not renumbered. A recording with no audio has none. Any other run of zero-length words (a sentence opening a transcriber collapsed at the end of a silence, the words after it following at once) was spoken: it is kept and spread as before. Word indices are never renumbered. The edit list is `schema_version` 2 (a version 1 list is refused as `edl_schema_outdated`). Data streams of an iPhone `.mov`
  are ignored; only the first video and audio streams are mapped.
- **Retakes** are found by rule in `_retakes.py`, from the words and their times, with no model: a run of three or more content words that
  recurs within 20 s (`repeat`), a shorter run or a cut-off fragment that is begun again and carried on (`restart`), and two phrases that
  differ by a word or two (`near`). Hesitations, fillers and cues (a language's lists in the block `retakes` of `renderer-presets.json`) are
  skipped when comparing and go with the cut when they lie between the takes; accents are folded. Each proposal carries a `default`, `cut`
  or `keep`, and a closed `reason` (`far`, `cut_off`, `hesitation`, `continues`, `abandoned`, `pause`, `complete`, decided in that order;
  `redo` takes the place of `far` for a whole sentence said again right after itself in other words; its earlier take starts a phrase or follows a connector word of the language's `connector` list, as in "..., but <take>", and holds no sentence end; pauses inside the earlier take, such as a word DTW stretched over a silence, do not split it, a sentence end or a hesitation does), so the last take stays. A candidate is never proposed when it is a coordination: the earlier take ends in a coordinating conjunction of the language's `conjunction` list (pt: e, ou, nem; en: and, or, nor), right before the later take with no pause of `retake_pause`, and at least `coordination_between_min` (2) tokens lie between the matched run and the conjunction ("de que ele nos ama e de que ele apenas..." keeps both clauses; with nothing between it is still a restart). `base --retakes auto` (the default) cuts every proposal whose default is `cut` except those named with `--keep`,
  and `--confirm <id>` cuts one more; `--retakes propose` cuts only what `--confirm` names (what the runtime uses, so every word is shown in
  the review). A complete sentence said twice with under a second between is kept. The storyboard never cuts.
- **Beats.** `align` runs the post-writing skill's own checker (isolated, inside the container) and refuses a post it does not pass;
  NFKC, casefold and punctuation normalised, best window per beat, figures excluded from scoring, a tie goes to the last occurrence, an
  order check, a threshold (0.6 until calibrated in C2). `--anchor <beat>=<from>-<to>` places a beat the aligner could not.
- **Face box and zones.** The person gives the face box once per recording (`--face-box x,y,w,h`; a default is used otherwise). Cards sit in
  the band above it (from y 110 down to the face less 18 px), captions in the band below it (from the face plus 18 px down to y 1560); the
  type is the largest that fits the band (a short band gives small type, never a card over the face). Every drawn card, chip and caption
  word is measured after each frame and the render fails when one touches the face box (`overlay_hits_face`) or when a caption's bottom is
  below 1560 (`caption_below_line`, VD12: 1560 clears the apps' interface). **The box is the zoomed one:** a zoomed range
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

The engine contract's legs M1 and M2 measure this on both engines, composed, at 4 and at 8 cores (`reports/`); C9 in the table above.

Pinned in the compose command (`_media.compose_argv`): x264 on four slice threads (`-threads 4 -x264-params threads=4:lookahead_threads=1:sliced-threads=1`,
`X264_THREADS`, `X264_PARAMS`: x264's output depends on its thread count, and the automatic count follows the cores the machine shows, 14 inside
the container whatever the CPU quota; the proxy's and the HyperFrames final encode's x264 are pinned the same way; the preview stays on one thread; the 15 s 4K measurement below was at
four frame threads on arm64, and amd64 CI differed with frame threads: 2026-11-08 the final encode, mid-stream, and 2026-11-09 the compose, frame 0;
one thread was the first fix and cost about 2x on the proxy, so slice threads are the second: no state is shared between the frames in flight, at the cost of some compression), the filter graph's threads
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

CI paths (V3c-2): the `renderer` job builds the common image and runs the ffmpeg parameter; the `hyperframes` job builds both images and runs both parameters. A change inside `hyperframes-image/` alone starts only the `hyperframes` job; a change to `shared/references/video-presets.json`, `shared/references/platforms/instagram.json` or `skills/mkt-social-copy/scripts/check_script.py` (read by every render) starts both.

Live files and their variables: `WB_RENDERER_DOCKER_TESTS=1` (the ffmpeg image), `WB_HYPERFRAMES_DOCKER_TESTS=1` (both images), `WB_ENGINE_MAC_LEGS=1` and `WB_ENGINE_REPORT=<new file>` (the machine legs of `test_engine_contract_live.py`).

`uv run --with pytest pytest providers/renderer/tests` (the whole suite takes about five minutes). Browser and ffmpeg tests
skip with a reason where those are absent; the host side runs against a fake docker that executes `_inner.py` with a local Chromium.
`UPDATE_GOLDEN=1` rewrites `tests/golden/*.json` (the exact ffmpeg argv of a plan).

## Not verified here

- The four-slice-thread x264 of the compose, the proxy and the final encode (V3c-3): its cost, its bytes (about +0.5 to +0.8 % against one thread at the same CRF) and its determinism on this Mac are in `reports/engine-contract-2026-11-10-arm64.json` and the decision file `docs/decisions/2026-11-09-v3c-3-x264-one-thread-compose.md`; on amd64 CI the renderer job passed 3 attempts at cf3fe3f.
- The engine contract's machine legs have run only on the Mac the supervisor names in the report; the figures of M1 and M2 (the sha256 at 4 and 8 cores, the stage seconds, the memory) are in `reports/engine-contract-2026-11-09-arm64.json`: both engines give one sha256 at 4 and at 8 cores, the real-size HyperFrames render took 1011 s at 4 cores and 945 s at 8, and the 298 s input 1378 s at 8 (cap 1800); `oom_events` is null there. On amd64 the legs first run in V3c-2's `hyperframes` CI job (its first run is the first amd64 build of the HyperFrames image: until it has run, nothing here is verified on amd64). The memory in the report is `docker stats` (cache left out, one sample a second: a short peak can be missed), unverified on Docker Desktop.

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

The recording length bound is 300 s (`limits.input_seconds_max`, decision VD7): intake enforces it, and the renderer matches it as defence
in depth (`analyse`, `base` and `render` refuse longer). The output length is the platform file's maximum.
