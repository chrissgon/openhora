# A feature across layers: the short video

Part of [the platform map](README.md). This page has the eight sections of a layer page, in the same order, and it is not a layer: it follows one feature (a recording and a script become a vertical video) through the providers, the shared presets and the checks. The layer that holds the code is [providers.md](providers.md).

## Purpose

Two classes make a short video, and both are used by the task runtime alone: no skill requires them (decision VD2 of [the V0 decision](../../decisions/2026-11-07-v0-short-video-hyperframes.md)), so [contracts/environment.md](../../../contracts/environment.md) does not list them. `providers/resolve.py` knows both as roles (`ROLES`).

- **`transcriber:speech`** (`providers/transcriber/whispercpp.py`). Takes an audio or video file, a pinned model name and a language, and writes a transcript, word by word with times (`transcript.schema.json`). It runs whisper.cpp in a container on the person's machine; the audio never leaves it and no model of any provider sees it. It returns counts on stdout, never words.
- **`renderer:video`** (`providers/renderer/ffmpeg.py`, the one engine built today). Takes a recording, a transcript, a post with a script block and a platform file, and returns a 1080x1920 H.264 + AAC video, a cover frame or a still frame of a recording. No model is involved: the edit list is built by code from the transcript, the beats come from the post's script block, a pinned headless browser draws the overlays frame by frame, and ffmpeg cuts and composes. A second engine (HyperFrames) is planned behind the same class (VD1); `CLASS_DEFAULTS` keeps `ffmpeg` as the default, so a caller that names no implementation never gets the other one.

Everything that reads a recording, a transcript or a post runs inside a container (VD4), through `providers/_container.py`: no network, a read-only root, every capability dropped, no host environment, an image run by the id the build recorded.

## Artifacts it owns

| Path | Where | Format | Written by | Read by | Lifecycle | Versioned | Generated |
|---|---|---|---|---|---|---|---|
| `providers/transcriber/transcript.schema.json` | repo | the transcript: words with start and end times, the segments, and the facts of the run | maintainers | `whispercpp.py` (writes), `renderer` `base` and `align` (read) | changed by pull request, with its tests | yes | no |
| `providers/renderer/edl.schema.json` | repo | the edit list and the beats, renderer-neutral: frame ranges, word indices, preset names, typed parameters, slot ids, theme tokens, nothing a renderer would run | maintainers | `base`, `align`, `check`, `render` | version 2 writes `zoom.anchor_y`; a version 1 list is refused as `edl_schema_outdated` | yes | no |
| `providers/renderer/renderer-presets.json` | repo | what the renderer decides about `shared/references/video-presets.json`: frame, zones, cuts, zoom, timing, limits | maintainers | the renderer, both sides | changed by pull request; part of the image | yes | no |
| `providers/renderer/image-manifest.json`, `.dockerignore` | repo | the files the ffmpeg image is built from, and the same list as a Docker ignore file | maintainers | `_image.py` (the tag), the build | a test keeps the two equal | yes | no |
| `providers/transcriber/models.json`, `providers/renderer/browser-pin.json`, `providers/renderer/blocks/pins.json`, `providers/renderer/assets/fonts/allowlist.json` | repo | the pins: the models (sha256, size, source), the browser (version, URL, size, md5, sha256 per architecture), every block file, the engines files and the allowlist (sha256) and the fonts (sha256, licence, source) | maintainers; `pin-browser --confirmed` and `pin-blocks --confirmed` rewrite two of them | the providers | a pin changes only in a reviewed commit | yes | no |
| `providers/renderer/blocks/` (`oh/<name>/block.json` and `renderat.html`, `engines/<engine>.json`, `hf/allowlist.json`, `block.schema.json`) | repo | the catalogue's sources: each block's kind, band, typed parameters, samples and page; each engine's runtimes and block per preset; the admitted `hf:` blocks | maintainers | `_blocks.py`, both engines | a change is pinned with `pin-blocks --confirmed`; staged per job, not in the image | yes | no |
| `providers/renderer/blocks/catalogue.json` | repo | the catalogue of animations, our fields only | `pin-blocks --confirmed` | the caption review (V1c), the picking skill (V5) | written with the pins; a test holds it equal to the generator | yes | yes |
| `<out>/render-<sha12>.mp4` | the folder the caller names | the finished video, content-addressed, mode 0400, never rewritten | `renderer` `render` | the caller | the same bytes again are a replay, other bytes under the same name are refused | no | yes |
| `<out>/cover.png`, `<dir>/still-<sha12>.png` | the folder the caller names | one PNG frame of a render (0600), and one frame of a recording framed as the render frames it (0400, never rewritten) | `renderer` `render --cover-out`, `cover`, `still` | the caller | written once | no | yes |
| `<dir>/beat-<n>.png`, `<dir>/sheet.png` | the folder the caller names | the storyboard: a still per beat and a contact sheet, no recording and no transcript go in | `renderer` `storyboard` | the person | written once | no | yes |
| `<state>/transcriber/` and the renderer's state folder (`image.json`, work folders) | state | the recorded image id, and private work folders (0700) | the `build` and run verbs | the same providers; `reap` removes what a killed run left | removed after each run | no | yes |

## Abstractions

**The common part and the drawing part.** The renderer's modules fall in four kinds, and the kind says what a module may import.

| Kind | Modules |
|---|---|
| Common (no browser, used by every engine) | `_align`, `_edl`, `_media`, `_redact`, `_text`, `_timeline`, `_vocab`, `_layout`, `_assets`, `_output`, `_blocks` |
| Drawing (the ffmpeg engine's own: the browser, the frames, the storyboard) | `_cdp`, `_frames`, `_lint`, `_render`, `_preview`; the host's `_browser` |
| Host (not in the image) | `_docker`, `_image`, `_host`, `ffmpeg.py` |
| Inner (the container's entry point) | `_inner.py`: imports only common modules at the top; `render`, `storyboard` and `selfcheck` import the drawing modules inside their own functions |

What the three newest common modules hold: `_layout` is the arithmetic of where a thing may be drawn (`zones`, `face_hit`, `caption_hit`); `_assets` is what is served to a page (`font_allowlist`, `load_fonts`, `load_assets`, `read_regular`); `_output` is how a result is stored (`read_platform`, `make_cover`, `make_still`, `png_size`, `write_once`). An old module imports each moved name back, so a caller and a test still find it where it was. A second engine imports the common modules and `_host.add_common_parsers` and never `_frames`, `_cdp`, `_render` or `_preview`. `_blocks` is the catalogue: the blocks, the engine that may draw each, and the check of a block's parameters.

**The host and the inner side.** The host (`_host.py`, with `_docker.py`) checks the flags, stages the inputs into a private job folder (`Job`), builds the `docker run` command, runs it and reads the result as untrusted, rebuilt from a closed schema. The inner side (`_inner.py`) runs inside the container on `/job` and `/in` (read-only), `/out` (the one writable mount) and `/scratch` (memory-backed). `_host.COMMON_VERBS` names the verbs that need no browser and that every engine serves the same way: `analyse`, `base`, `align`, `check`, `cover`, `still` and `verify`.

**The image of each provider and its manifest.** The transcriber image is built from `providers/transcriber/Dockerfile` (the base by digest, whisper.cpp by tag and commit), and holds no model. The ffmpeg engine's image is built only from the files `image-manifest.json` lists; the tag is the sha256 of exactly those files (`_image.py`), so an edit to a host-only file (`ffmpeg.py`, `_docker.py`, `_browser.py`, `_host.py`, `_image.py`) never changes it. `scripts/doctor.py` names each family's definition module and finds the images of earlier definitions to remove.

## Dependencies

- `providers/_container.py`: the one container lifecycle (the docker client, the local-daemon check, the run command, the stderr cap, the reaping) behind both providers' function names. This page's providers never call docker another way.
- `providers/resolve.py`: `ROLES` (`transcriber`, `renderer`) and `CLASS_DEFAULTS` (`renderer:video` is `ffmpeg`).
- `shared/references/video-presets.json`: the vocabulary of presets and their typed parameters, read by flag (`--vocabulary`).
- `skills/mkt-social-copy/scripts/check_script.py`: the post-writing skill's own checker, which `align` and `storyboard` run isolated inside the container and whose refusal is final.
- The shared redaction copy: `providers/renderer/_redact.py`, a generated copy of `shared/scripts/redact.py` (the credential formats `check` scans with), kept identical by `scripts/sync_copies.py`.
- `shared/references/platforms/<platform>.json`: the platform file a render is checked against (`--platform-file`).

## Business rules

| Rule | Held by |
|---|---|
| No network in a run: the container has no network, a read-only root, no capability and no new privileges, and the host refuses a daemon that is not local | `providers/renderer/tests/test_renderer_docker.py` (`test_the_container_has_no_network_a_read_only_root_no_capability_and_no_new_privileges`, `test_the_daemon_must_be_local`); `providers/transcriber/tests/test_whispercpp.py` (`test_the_run_the_provider_starts_has_no_network_no_environment_and_three_mounts`) |
| The image is run by the recorded id and never pulled; a missing, stale or swapped image is "not configured" and no container starts | `test_renderer_docker.py` (`test_the_image_is_never_pulled_is_run_by_its_id_and_is_labelled_for_reaping`, `test_a_missing_stale_or_swapped_image_is_not_configured_and_no_container_starts`); `test_whispercpp.py` (`test_a_run_refuses_an_image_that_was_not_built_or_was_replaced`) |
| The image tag is the hash of the manifest's files, and a host-only edit changes nothing | `test_renderer_image.py` (`test_no_host_only_file_is_in_the_manifest_and_the_tag_does_not_change_when_ffmpeg_py_does`) |
| The 1560 line: the caption band ends at `zones.caption_bottom` = 1560 (VD12); a caption drawn with its bottom below it fails the render as `caption_below_line` | `test_renderer_common.py` (`test_a_caption_drawn_ending_at_1560_passes_the_frame_loop`, `test_a_caption_drawn_ending_at_1561_is_refused_with_caption_below_line_and_names_the_frame_and_the_bottom`) |
| The face box: a card or a caption that touches it fails the render as `overlay_hits_face`, and a face box that leaves no room for a card (80 px) or a caption (120 px) is refused at `base` | `test_renderer_engine.py` (`test_a_card_drawn_over_the_face_fails_the_frame_loop`); `test_renderer_edit.py` (`test_the_face_box_must_be_inside_the_frame_and_leave_room_for_cards_and_captions`, `test_a_drawn_box_that_touches_the_face_box_is_found`) |
| Fonts come only from the allow-list, each checked by sha256 and by its header bytes | `test_renderer_engine.py` (`test_fonts_come_only_from_the_allow_list_and_are_hash_checked`) |
| The browser is pinned by version, URL, size, md5 and sha256, and a build refuses what differs from the pin | `test_renderer_browser_pin.py` (`test_the_shipped_pin_names_the_version_and_both_architectures_and_the_sha256_is_not_invented`, `test_the_build_download_refuses_what_differs_from_the_pin`) |
| A page loads nothing but what is served from memory: a network or file request fails the render | `test_renderer_engine.py` (`test_a_network_or_file_request_fails_the_render`) |
| The common modules import nothing of the drawing part, and the verbs that need no browser load none of it | `test_renderer_common.py` (`test_no_common_module_imports_a_drawing_or_a_host_module`, `test_verify_cover_and_still_run_without_loading_a_drawing_or_a_host_module`) |
| The transcriber's model is compared with its pinned sha256 before any container starts | `test_whispercpp.py` (`test_a_model_that_differs_from_its_pin_is_refused_before_any_run`) |
| `renderer:video` resolves to `ffmpeg` by the class default | `test_renderer_contract.py` (`test_renderer_video_is_a_runtime_only_class_with_one_implementation_and_underscore_helpers_are_not_implementations`) |
| A render draws only pinned blocks, copied into the job's read-only folder and hashed there; the container checks the hash again and the result names it | `test_renderer_blocks.py` (`test_stage_blocks_copies_only_the_pinned_files_and_hashes_the_copy`, `test_a_changed_file_a_link_an_unknown_file_or_another_pins_hash_is_refused`); `test_renderer_docker.py` (`test_a_render_or_storyboard_result_that_names_other_blocks_is_refused`) |
| A block the engine cannot draw is refused, naming the engine's own block for the preset | `test_renderer_blocks.py` (`test_an_hf_block_fits_the_schema_unchanged_and_is_refused_on_ffmpeg_naming_the_oh_block`); `test_renderer_render.py` (`test_a_beat_that_names_a_block_the_engine_cannot_draw_is_refused_before_any_frame`) |
| The catalogue is generated, never edited, and an entry without a sample is refused (VD13) | `test_renderer_blocks.py` (`test_the_catalogue_file_is_what_the_generator_writes`, `test_every_catalogue_entry_has_a_sample_and_every_sample_passes_the_checker`) |
| Every `oh:` block's page is its old template, byte for byte | `test_renderer_blocks.py` (`test_every_oh_block_is_its_old_template_byte_for_byte`) |

## Entry points

Each verb prints one JSON object on stdout and diagnostics on stderr; a refusal is `refused: <closed code> <field>` on the first line, and the text of an input is never echoed. The full flags are in `python3 providers/transcriber/whispercpp.py --help` and `python3 providers/renderer/ffmpeg.py --help`.

| Provider | Verbs |
|---|---|
| `providers/transcriber/whispercpp.py` | `--check [--model <name>]`, `models`, `build (--confirmed \| --dry-run)`, `reap`, `transcribe --in <file> --model <name> --language <code\|auto> --out <transcript.json> [--timestamps word\|ml1\|dtw] [--timeout <s>] [--threads <n>] [--max-seconds <s>] [--memory-mb <n>] [--dry-run]` |
| `providers/renderer/ffmpeg.py` | `--check`, `build (--dry-run \| --confirmed)`, `pin-browser (--dry-run \| --confirmed)`, `reap`, `pin-blocks --confirmed`, `block-params`, and the common verbs `analyse`, `base`, `align`, `check`, `cover`, `still`, `verify`, and the drawing verbs `render` and `storyboard` |

`verify --in <mp4> --platform-file <f> [--sha256 <hex>] [--edl <f>]` checks a stored render in a fresh container: the sha256 (given, or the file's own), ffprobe's facts against the platform's spec, the bt709 tags and, with an edit list, the length. Every renderer verb also takes `--memory-mb`, `--cpus`, `--scratch-mb` and `--timeout`. Exit codes: 0 ok, 1 refused or failed, 2 usage error, 3 not configured.

## Known limits and improvements

- The storyboard (`storyboard`, `_preview.py`) is ported and tested but no flow uses it yet (M2, VD14).
- The ffmpeg image installs the DejaVu system font (`fonts-dejavu-core`) and has no last layer that fails on a font outside the allow-list, which condition 6 of the V0 decision asks for; the HyperFrames image has that layer (OPEN-3). A purge layer for this image is left to a later package.
- The HyperFrames engine is not built here. It comes with V3a, and V3b adds its half of the 1560 gate; it will reuse `_layout.caption_hit`.
- `selfcheck` is the one inner verb that is not a drawing verb and still imports the drawing part (`_cdp`), because it reports the container mode.
- The `hf:` allowlist is empty and no engine runs the `gsap` runtime until V3b; a block whose parameters differ from its preset's cannot be named by a beat yet (OPEN-6 of the V3b0 spec).
- The synthetic render in CI proves the container path on a generated recording; a render of a real recording on the maintainer's machine is a separate, manual step.

## Changes

Written on 2026-11-07 by V1a-3.
