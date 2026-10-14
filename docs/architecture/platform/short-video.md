# The short video

Part of [the platform map](README.md). This page is not a layer page: it follows one feature, a person turning a script into a vertical video they approve and post by hand, across the layers that carry it (the project's files, the media store, the operations layer, the local service, two providers that run in containers, the page, two skills). It states what the code does, with file references, and points to the contracts for the rules; when this page and the file it points to disagree, the file wins and the page is corrected. It was written on 2026-10-14 from the code of the integration branch `feature/short-video` at commit `9c42df1f` (the intake, the transcriber, the renderer, the pipeline, the caption review, the project's theme, the still frame, the approval and the storyboard verb of the renderer), from `contracts/runtime.md` and from the plan `docs/architecture/short-video-posts-2026-10-12.md` on the branch `plan/short-video-posts` (decisions D1 to D35 and amendments A1 to A6, cited here by number, never copied).

## Purpose and scope

A person who posts short videos spends most of the work in the edit: cutting the silences and the retakes, putting the words on screen, showing a number or a list at the right second, checking the result. The feature does that edit with code and keeps the person in charge of every decision that is theirs. What a person can do today:

- **Script.** The skill `mkt-social-copy` writes a post file whose `script` block holds the spoken lines, one beat each, and the animation each beat asks for (`skills/mkt-social-copy/references/video-script.md`).
- **Record and upload.** The person records the video with the phone and gives it to the Mac that runs the service. The page's "New short video" (or `media-in` in the terminal) takes the file into the media store, reading its type from its bytes.
- **The caption review.** The pipeline transcribes the recording, finds the silences and the retakes, matches each beat's line to the words, and stops at "Check the captions". The person corrects words, confirms or undoes each retake, anchors beats the code could not match, answers each empty asset slot, says where the face is and where the cover is taken, and presses Done.
- **Render.** Code cuts, captions and draws the video in a container and checks the file in a second, fresh container before it keeps it.
- **Watch, approve, send back, download.** The video card plays the render, shows the caption and the two hashes, and takes the approval of exactly that file and that caption. A send-back with a comment reopens the review. A download gives the approved file under a plain name.

What is not built (the list is "Open items"): publishing or scheduling (the first milestone has none: the person posts by hand), a model that proposes animations from the transcript, the caption styles and the richer motion of amendment A5, sound cues, the catalogue of animations, the storyboard's operations and card, "Add an animation" in the review, a still frame behind the face-box picker on the page, a second renderer or transcriber.

What it is not: not an editor with a timeline, and not a place with a model of its own. **No operation of the feature calls a model** (every row of `runtime/operations.py` for it has `model: False`), no transcript, post or recording reaches one, and the hosted-service paths of the plan are not built. A model's only part in the whole feature is earlier: the skill that wrote the script.

Scope of this page: the artifacts and their relations, the pipeline, the operations and routes, the two providers, the page, the security model, a runbook and the open items. The contracts that bind it are [contracts/runtime.md](../../../contracts/runtime.md) ("The media store", "The media pipeline and the caption review", "The rendered video"), [providers/CONTRACT.md](../../../providers/CONTRACT.md), [providers/transcriber/README.md](../../../providers/transcriber/README.md), [providers/renderer/README.md](../../../providers/renderer/README.md) and [shared/references/video-presets.md](../../../shared/references/video-presets.md).

## The decisions and why

Decisions are the plan's own numbers (D1 to D35, amendments A1 to A6), all answered by the maintainer on 2026-10-13 and 2026-10-14. The table gives the ones that shape the code; for the full text and the reasons read the plan.

| Decision | What | Why |
|---|---|---|
| D12 (path 1), C1 | Code builds a base edit list from the transcript; the model, where it is used at all, writes only indices, preset names and typed texts; code derives every time and every caption. In M1 no model sees the transcript. | The recording and the person's words must not reach a model by default, and a time a model wrote is a way to put text anywhere. A hard limit lives in code (principle 11). |
| D17 | A per-project consent setting, default off, gates any later step in which a model reads the transcript (the annotation of M2) and any hosted transcriber. | The person decides, project by project, who sees their words. |
| D1, D3 | Instagram Reels first; no TikTok publisher; M1 ends with a download the person posts by hand. | A public post needs a linked page and an audit the person has not chosen; the hand-off needs neither. |
| D4, D20, A3 | Transcription is local whisper.cpp in a Docker container, CPU, built from a definition the provider owns and pinned by tag, commit and model hash. | The voice stays on the machine, and the test is the same on a server as on a laptop. |
| D22 | The renderer runs in a provider-owned Docker image too: ffmpeg and a pinned headless Chrome inside, no network, read-only root. Chrome's own sandbox is off inside the image, with the container as the boundary, as a stated trade-off. | A render must be the same on any machine, and the browser reads what the person typed. |
| D21 | `renderer:video` and `transcriber:speech` are provider classes with stable verbs and one renderer-neutral edit list, so another implementation (Remotion, a hosted service) can replace the first behind the same verbs. | Editing and rendering are swappable, "like lego". The plan leaves the name of the project key open; none exists yet ("How to swap an implementation"). |
| D23 | HyperFrames was spiked as the second renderer and **not adopted** (outcome K): its captions are fixed to 1920x1080 with English-only helpers, it needs 11 GB, its bytes are not guaranteed and it enforces neither our fonts nor a face-box guard. Its ideas are borrowed as our own presets; no file is copied. | The spike ran once (n=1: two presets, no layouts, no contract tests); the seam held, the engine did not fit. |
| D5, D6, A1, A2 | Word-highlight captions and per-beat presets with typed parameters, drawn as HTML templates frame by frame by code, with layout presets that show a file the person uploads; one pinned font set. | Presets are data the person can name in a script; templates are pinned by hash. |
| D19 | An `image` or `clip` parameter is filled only by a file the person uploads for that slot: no download, no generated image, no file picked from the project. | Copyright and reuse are the person's judgement; a download would bring URLs into the pipeline. |
| D24 | Captions are written as spoken (a speaker's contractions and slang stay as said), and the person corrects them in the review; code never rewrites a spoken form into a standard spelling. | A speaker's voice is the point; the only change a text goes through is hardening. |
| A4, C3 | The caption review: the person edits words, never times; code owns every time and re-maps edits onto word indices; retakes found by rule are proposed and the person confirms them; timestamps are `dtw`. | `dtw` placed far fewer words inside silences than the word mode on the first real recording (check C3). |
| D7, D8 | The media lives in `<data_dir>/media/<id>/`, outside every repository, and is deleted by code on a schedule; 1 GiB and 300 s per recording, a 30-minute render limit. | A recording is the person's, and a folder that can hold a gigabyte must not sit in git or in a run copy. |
| D32, D34 | The project's colours and fonts come from a closed `brand-tokens` block that `brand-identity` writes and code maps to the renderer's roles; no `media.theme` key. | One source of the theme; code, not a model, decides which colour goes where. |
| D11 | Both classes are runtime-only: no skill may require them, so they are not in `contracts/environment.md`. | No skill calls them. |
| D35 | A catalogue and a storyboard may cross the LAN socket; recordings, the review and the video stay on the loopback socket. | Fictional data and text already in a decision cross the LAN; a person's words and video do not. |
| D25 to D27, D29 to D31, D33 | Decided, not built: sound cues, the caption band's bottom at 1560 px, Anton for the Block style, the catalogue, the storyboard on the page, "Add an animation", the text request of M2. | See "Open items". |

## Architecture

### The layers and what calls what

The shells reach the operations layer (see [shells.md](shells.md) and [runtime.md](runtime.md)); the operations call small modules that own one job each; a provider runs in a container.

```text
   page                                             terminal
   interface/js/floor/                              runtime/cli.py
     media-start.js  captions-view.js  video-card.js     |
        |  (loopback socket for the media, the review and the bytes)
        v                                                |
   runtime/service.py  (routes: loopback flag, one video gate, ranges)
        |                                                |
        +---------------------+--------------------------+
                              v
        runtime/ops.py  and  runtime/operations.py (the rows, the groups)
          ops_media.py     ops_pipeline.py                   ops_video.py
            |                |        |                        |
        media.py        pipeline.py  captions.py            video.py
        (the store:     (the steps,  (re-map of the         (which file a render is,
         intake, record, state file,  person's words,        the approval's comparison)
         retention)      stops)       the review)                |
                         |   theme.py (brand-tokens -> renderer roles)
                         v
        providers/resolve.py  call(class, verb, args)   <- a minimal environment (ENV_KEEP)
                |                                   |
   transcriber:speech                         renderer:video
   providers/transcriber/whispercpp.py        providers/renderer/ffmpeg.py   (the host side)
        | docker run                                | docker run (and a second one to verify)
        v                                           v
   whisper-cli in a container                 _inner.py: ffmpeg + headless Chrome in a container

   read by the pipeline, written by other layers:
     docs/marketing/content/<post>.md      mkt-social-copy (script and post blocks), checked by check_script.py
     docs/brand/identity.md                brand-identity (the brand-tokens block), checked by check_brand_tokens.py
     shared/references/video-presets.json  the closed vocabulary; platforms/<platform>.json the video spec
```

A shell parses and calls one operation; the operation holds the rule. `runtime/ops_pipeline.py` makes the pipeline's context (`_make_context`), which hands the steps a `call` (`providers/resolve.py`'s `call`, its refusal read as a closed code by `pipeline.failure_from`), a `move` (the store's `code_task_move`), a credential `scan` and a clock. `runtime/pipeline.py` knows no provider script and no store function: that is what lets its tests run with a fake `call`.

### From the script to the approval

```text
 script block ──► media-in ──► media-pipeline ───────────────────────────────────────────────┐
 (post file)      (raw.mov)    transcribe  analyse  [still]  retakes  align-proposal          │
                                                                  │                          │
                                       STOP 1: "Check the captions" (decision, kind question)│
                                       the person edits words, retakes, anchors, slots,      │
                                       face box, cover, theme; presses Done (captions-done)  │
                                                                  │                          │
                                       remap  base  align  check  render  cover              │
                                                                  │                          │
                                       STOP 2: "Approve the rendered video" (decision) ◄─────┘
                                       the video card: watch, approve (hashes), send back, download
                                                │ send back: resume at the review, nothing re-run
                                                └──────────────► STOP 1 again
```

The two stops are the only places the person is asked. Both are decisions of kind `question` on one **code task** per recording (no skill, key `media:<recording id>`), so the lobby's pending list shows them; neither is answered by `answer`, `release` or `reject` ("The pipeline").

## Artifacts and objects

Every file below is named, owned and moded. Nothing the pipeline makes is in the project, in git, in the documents mirror or in a run copy: the project holds only the two files a person or a skill writes, and the media store holds the rest under `<data_dir>/media/<id>/` (mode 0700; every file 0600 unless the table says 0400). `<id>` is 16 hexadecimal characters issued by code (`media.new_id`); `<sha12>` is the first 12 hexadecimal characters of a sha256.

### In the project

| File | Owner | When written | Read by | Key properties |
|---|---|---|---|---|
| `docs/marketing/content/<date>-<slug>.md`, the post file | `mkt-social-copy` | when the script is drafted; edited by the person | `pipeline.post_file` (`_check_start`, `align`, `check`), `video.caption_of` (the card, the approval) | Header lines `- Network:` (the platform; the pipeline's network when `--network` is not given), `- Format:` (`reel` or `video`), `- Status:`; a ```` ```script ```` block (required: a start without one is refused); a ```` ```post ```` block (the caption, exactly one); a regular file under `docs/`, at most 2 MiB, never a link |
| `docs/brand/identity.md`, `brand-tokens` block | `brand-identity` | when the identity is written and approved | `theme.read_identity` at the `base` step | A closed JSON block (below); a draft, a bad block or a low contrast stops the step |

**The script block** (`skills/mkt-social-copy/references/video-script.md`, checked by `skills/mkt-social-copy/scripts/check_script.py`, which the renderer's `align` runs inside the container; vocabulary version 2 of `shared/references/video-presets.json`). One `key: value` per line; beats separated by a blank line.

| Part | Fields | Notes |
|---|---|---|
| Header, before `beat: 1` | `hook_type` (contrarian, mistake, result, curiosity, number, question, story), `title` (3 to 5 words, at most 40 characters), `cta_kind` (save, send, comment, follow-up-video), `send_to` (at most 40 characters, only for `send`), `loop` (yes, no), `pattern` (list, myth, story, problem-solution, before-after, steps) | `hook_type` and `title` are always written for a `reel` or `video`; each key at most once; `align` copies `title` and `loop` into `beats.json`'s optional `script` object |
| Beat | `beat` (1, 2, 3 ...), `line` (the exact words said, at most 240 characters), `role` (hook, setup, point, proof, turn, payoff, cta), `emphasis` (`punch` where a punch-in is wanted), `on-screen`, `preset`, and the preset's own parameters | At most 12 beats; no field is a time; beat 1 is the hook and the last beat the `cta`; `on-screen` IS the preset's main text parameter and is never written twice |
| Presets and parameters | `keyword` (`text`, `icon`, `color`), `list` (`items` up to 4, `icon`, `color`), `number` (`value`, `label`, `color`), `quote` (`text`, `author`, `color`), `cutaway` (`asset`, `fit`, `label`), `pip` (`asset`, `position`, `label`) | `asset` is a description in words (3 to 80 characters), never a file name, path or link; captions are always on and are not a preset |

**The brand-tokens block** (`shared/scripts/check_brand_tokens.py`; `runtime/check_brand_tokens.py` is its generated copy): a fenced block ```` ```brand-tokens ```` whose body is one closed JSON object: `version` (1), `status` (draft or approved), `mode_default`, `color` (`bg`, `fg`, `muted`, `accent` required, `surface` optional; each `dark`, `light` or both, `#RRGGBB`), `font` (`display` and `body` required, `mono` optional; each `{family, weight}`). `theme.theme_args` reads the dark column and maps `bg`, `fg`, `muted`, `accent` and `surface` to the renderer's `bg`, `text`, `muted`, `accent` (and `chip_border`) and `chip_fill`, derives `chip_text`, and passes a font only when an allow-listed font has exactly that family and weight.

### In the media store

The record and the files the person's own steps make.

| File | Written by | Written when | Read by | Mode | Key properties |
|---|---|---|---|---|---|
| `record.json` | `runtime/media.py` (`create`, `update`, under `.record.lock`); `ops_video.py` for the approval keys | intake; every change of status, slot, post link, task, approval or send-back | everything | 0600 | `version`, `id`, `created_at`, `updated_at`, `status` (open, scheduled, published, cancelled), `ended_at`, `raw`, `posts`, `slots`, `frozen`, `tasks`, `purged`, and, once used, `approvals`, `approval_log`, `sent_back`, `resume` ("The record") |
| `raw.mov` or `raw.mp4` | `media.receive` | the upload | the transcriber and the renderer (read-only mounts), `analyse` | 0600 | named by its type, never by the person's file name; never replaced (`os.link`) |
| `assets/<slot>-<sha12>.<ext>` | `media.receive` with a slot | an upload for one asset slot | `render` (PNG and JPEG only) | 0600 | named by its own hash, so a new file never overwrites the one the record names; untrusted |
| `pipeline.json` | `runtime/pipeline.py` | after every step | `media-list`, the page, the resume | 0600 | `version`, `recording`, `platform`, `post`, `task`, `request`, `steps` (each `{status, at, result}`; status pending, done, waiting, failed or skipped), `failure` (`{step, code, field, provider, next, at}`), `decisions` (the open decision's id per stop), `sent_back_at` |
| `transcript.json` | the transcriber (`transcribe`) | the `transcribe` step | the renderer (`base`, `align`), the review | 0600 | `schema_version`, `language`, `duration`, `words` (`index`, `text`, `start`, `end`, `segment`, `probability`, `estimated`), `segments`, `facts` (the run: image id, model and hash, `timestamps`, `flags`, `words_without_timing`, `clamped_words`, `dropped_annotations`); never changed |
| `analysis.json` | the renderer (`analyse`) | the `analyse` step | `base`, the still's offset | 0600 | `schema_version`, `facts` (ffprobe, including the recording's `sha256` and `has_audio`), `silences` (`start`, `end`; null for a recording with no audio), `noise_db`, `min_silence` |
| `still-<sha12>.png` | the renderer (`still`) | the still side step | `media-still` | 0400 | 1080 x 1920 PNG of the recording at about 1.5 s, framed as the render frames it; named by its own sha256 |
| `proposal.edl.json` | the renderer (`base`, no retake confirmed) | the `retakes` step | the review (`view`) | 0600 | an edit list ("The edit list") whose `proposals` are the retakes found by rule and whose `normalisation` says what was re-timed or left out |
| `proposal.beats.json` | the renderer (`align`) on the transcript | the `align-proposal` step | the review, the later `align` | 0600 | a beats file with `report` (per beat: `beat`, `preset`, `score`, `matched`, word range, `reordered`, `fallback`), `threshold`, `slots` |

The person's decisions and the files the render makes.

| File | Written by | Written when | Read by | Mode | Key properties |
|---|---|---|---|---|---|
| `review.json` | `captions-edit` (the pipeline's process, under the task's lock) | every accepted edit | `captions-read`, `base`, `align`, `cover` | 0600 | `version`, `revision` (raised by each accepted edit), `confirmed_retakes` (`{id, from, to, seconds}`, an origin range), `anchors` (beat number to `[from, to]`, an origin range), `dropped_beats`, `empty_slots` (slot to `keyword` or `none`), `face_box` (`{x, y, w, h}` in frame pixels, or null), `cover_offset_ms` (0 to 600000), `theme` (`identity` or `default`) |
| `transcript.edited.json` | `captions-edit`, then `remap` | each edit; hardened again at `remap` | `base`, `align`, the review | 0600 | the transcript's shape, whose words also carry `origin` (`[first, last]` of `transcript.json` words each stands for) and `edited`, whose segments carry `source` (`transcriber` or `edited`), and whose `facts` gain `edited: true` and `revision` |
| `edl.json` | the renderer (`base` on the edited transcript) | the `base` step | `align`, `check`, `render` | 0600 | the edit list ("The edit list"); numbering is the edited transcript's |
| `beats.json` | the renderer (`align` on the edited transcript) | the `align` step; the dropped overlays removed after | `check`, `render` | 0600 | the beats ("The edit list"); numbering is the edited transcript's |
| `render-<sha12>.mp4` | the renderer (`render`) | the `render` step, after the second container verified it | `video-raw`, `video-download`, `cover`, the approval | 0400 | 1080 x 1920, 30 fps, H.264 with AAC, bt709, metadata stripped; named by its own bytes; never rewritten |
| `render.json` | `pipeline.write_render_result` | the `render` step, written again by `cover` | the card (`video.read_result`) | 0600 | `sha256`, `bytes`, `output` (ffprobe facts), `name`, `seconds`, `replayed`, `unmatched_beats`, `fonts`, `browser_sandbox`, `image`, `theme` (`source`, `reason`, `colors`, `fonts`, `notes`, `hash`), `verified`, and, after the cover, `cover` (`offset_ms`, `sha256`, `name`) |
| `cover-<sha12>.png` | the renderer (`cover`) | the `cover` step | `video-cover` | 0600 | one frame of the render at `cover_offset_ms`; `<sha12>` is the render's |
| storyboard outputs (`beat-<n>.png`, `sheet.png`) | the renderer (`storyboard`) | not written by the runtime yet | none yet | 0400 | the verb exists ("The renderer"); the operations and the card that would keep and show them are not built |

Temporary files (`.incoming-<id>.part`, `.tmp-*.json`) exist only while a write is under way; a stray one older than a day is swept. Locks: `.upload.lock` and `.record.lock` in the store's root, `pipeline.lock` in a recording's folder, and the code task's own `task-<id>.lock` in `<data_dir>/locks/`.

### The record

`record.json` is the one file that ties a recording to the rest. Its properties, as the code writes them (`runtime/media.py`, `runtime/ops_video.py`, `runtime/video.py`):

| Key | Shape | Set by |
|---|---|---|
| `status` | `open`, `scheduled`, `published`, `cancelled`; `published` and `cancelled` stamp `ended_at` and freeze the assets | `media.mark`, called by the packages that publish or cancel; **nothing calls it yet**, so every recording stays `open` |
| `raw` | `{bytes, sha256, type, name, uploaded_at, duration, width, height, fps, video_codec, audio_codec, file}`, or null before the upload and after a purge of the raw | `media.receive` |
| `posts` | platform to a project-relative post file, `{"instagram": "docs/marketing/content/<post>.md"}` | `media.link_posts`, at the first `media-pipeline` with `--post` |
| `slots` | slot id (12 hexadecimal characters, from the recording id and the beat's slot key) to `{key, description_sha256, asset}`; `asset` is `{bytes, sha256, type, name, uploaded_at, file, stale, ...}` or null; `stale` when the slot's description changed | `media.register_slots` (the `align-proposal` step), `media.receive` |
| `tasks` | `{"code": <task id>, "edit": <task id>}` | `media.bind_tasks`; only `code` is used in M1 |
| `approvals.<platform>` | `{video_sha256, video_bytes, caption_sha256, caption, platform, approved_at, approved_via}` | `video-approve` |
| `approval_log` | the last 50 events (`approved`, `sent_back`) with platform, time and hashes | `video.log_event` |
| `sent_back` | `{platform, comment, at, render_sha256, caption_sha256}`, null once an approval is recorded | `video-send-back` |
| `resume` | `{step: "review", reason: "sent_back", platform, at}`, cleared by the next pipeline call | `video-send-back`; `ops_pipeline._consume_resume` |
| `frozen`, `purged`, `ended_at`, `created_at`, `updated_at` | the retention reads `updated_at`, `ended_at` and `purged.raw` | `media.update`, `media.mark`, `media.purge` |

### The edit list and the beats

`providers/renderer/edl.schema.json` is the renderer-neutral contract (every object closed, no filter text, no path, no URL, no time a person or a model wrote); `providers/renderer/_edl.py` holds the checks a schema cannot say. `edl.json` (`schema_version` 2; a version 1 list is refused with `edl_schema_outdated`) is written by `base`:

| Object | What it holds |
|---|---|
| `fps`, `size`, `source` | the output frame rate and size, and the recording the list was made from (`sha256`, `duration`, `width`, `height`, `has_audio`); a render refuses another recording |
| `kept`, `out_frames` | the kept ranges as `[from_frame, to_frame)` of the recording, ordered, not overlapping; the sum |
| `words` | the live words on the **output** timeline (`index`, `text`, `start`, `end`, `estimated`); `index` is the position in the transcript the step was given |
| `captions` | `position` and `chunks` (`[word_from, word_to]` of one to three words) |
| `theme` | `colors` (every token of the palette to `#RRGGBB`) and `fonts` (role to `{id, weight}`); `id` is `default` or an allow-listed id |
| `normalisation` | counts of what was done to the transcript's times: zero-length words spread, starts clamped, segments dropped as impossible speech, plus `retimed_words` (a word silence covers, moved into the voiced span next to it) and `unplaced_words` (left out of the captions) |
| `face_box` | `{x, y, w, h}`: cards live above it, captions below it, and a render fails when one touches it |
| `zoom` | `mode` (alternate or none), `factor`, `push_in`, `anchor_y` |
| `proposals` | the retakes found by rule (`id`, `kind`, `word_from`, `word_to`, `keep_from`, `seconds`, `confirmed`); only a confirmed one has been cut |

`beats.json` (`schema_version` 1) is written by `align`: `threshold` (0.6 until calibrated), `overlays` and `layouts` (each an entry: `id`, `beat`, `preset`, `params`, `word_from`, `word_to`, `score`, and the optional `role` and `emphasis`; a slot parameter holds a slot id), `slots` (`slot`, `beat`, `param`, `type`, `description`), `report`, `unmatched` (beats whose line was not found: they get no overlay), `fallbacks` (an empty slot the person resolved to a keyword or to nothing) and the optional `script`.

### Relations

```text
 raw.mov ──► transcribe ──► transcript.json ──────────────────────────────┐ (words 0..n-1, "origin" space)
    │                              │                                      │
    ├──► analyse ──► analysis.json │                                      │
    │         │                    ├──► retakes ──► proposal.edl.json     │
    │         └─► still-<sha12>.png├──► align-proposal ──► proposal.beats.json
    │                              │         (both numbered by transcript.json)
    │                              ▼
    │                   review.json (confirmed_retakes, anchors: origin ranges of transcript.json)
    │                              │                                      ▲
    │                              ▼                                      │ origin [first, last] on every word
    │                   transcript.edited.json  (words renumbered 0..m-1; each word keeps its origin)
    │                              │
    │            + review.json + analysis.json + identity.md's brand-tokens
    │                              ▼
    │                   edl.json ──────────┐   (numbered by transcript.edited.json)
    │                              │       │
    │          + post file, review ▼       │
    │                   beats.json ────────┤
    │                                      ▼
    └──────────────────────────────► render-<sha12>.mp4 ──► render.json ──► cover-<sha12>.png
                                           │                    │
                                           └───── video card: approvals.<platform> in record.json
                                                  binds render's sha256 + caption's sha256
```

**Origin indices.** The proposals are made on `transcript.json`, so their word numbers are that file's. After an edit the words are numbered again, because the renderer reads a word's index as its position; each word of `transcript.edited.json` therefore carries `origin`, the range of `transcript.json` words it stands for, and every decision is kept in that numbering: `confirmed_retakes` and `anchors` are origin ranges (`captions.origin_span`), and `captions.span_current` finds the edited words that stand for a range. At `base` a confirmed retake is found again by the words it drops (`confirmed_ids`); at `align` an anchor is found again by the words it stood on (`anchors_current`). When the words a decision stood on are gone the step stops (`retake_lost`, `anchor_lost`), the confirmation is dropped and the person decides again from the review.

### Content addressing and integrity

- **Names are hashes.** A render is `render-<sha12>.mp4`, a still `still-<sha12>.png`, a cover `cover-<render's sha12>.png`, an asset `<slot>-<sha12>.<ext>`. The renderer stores a render only after a fresh container verified it against the platform's spec, its bt709 tags, its length and its sha256, and never rewrites it (mode 0400, `exclusive` copy). A second render of the same bytes is a replay, not a new file.
- **A file is chosen by id and hash, never by a path.** The routes carry the recording id (16 hexadecimal) and the sha256 (64); `video.open_render`, `open_cover` and `open_still` build the name themselves (`runtime/video.py:140-258`), so the raw recording, an asset, the record and any path outside the recording's folder cannot be asked for.
- **Open without following.** The folder is opened with `O_NOFOLLOW|O_DIRECTORY`, the file with `O_NOFOLLOW`; it must be a regular file with one link, within its limit (the recording limit for a render, 8 MiB for a cover or a still), an MP4 or a PNG by its first bytes. The open descriptor is hashed, the digest must equal the sha256 asked for, and the bytes are read from that same descriptor, so a file swapped after the hash is not served.
- **A digest is remembered by identity** (device, inode, size, modification and change time), single flight per file, so a range request does not hash a gigabyte again; an approval always hashes again (`fresh=True`, `ops_video.video_approve`).
- **Intake never overwrites.** The upload is written to a temporary name opened with `O_CREAT|O_EXCL|O_NOFOLLOW` in a folder checked with `lstat` (a directory, ours, 0700), hashed as it is written, and linked to its final name with `os.link` only after the length, the hash and the checks passed (`media._finish`).
- **JSON is read as untrusted.** `pipeline.read_json` opens with `O_NOFOLLOW`, refuses a file that is not regular or is over 5 MiB; every write goes through a temporary file of its own and `os.replace`.

## The pipeline

`runtime/pipeline.py` holds the steps, `runtime/ops_pipeline.py` the operations around them. Each step is a function of a `Context`, its result recorded in `pipeline.json` as closed words and numbers (a code, a count, a hash, a name; never a word of a transcript or a post). `ORDER` is `pipeline.py:71`.

| Step | Does | Reads | Writes |
|---|---|---|---|
| `transcribe` | `transcriber:speech transcribe --timestamps dtw` with the project's `media.model` and `media.language`, `--max-seconds 300` | `raw.*` | `transcript.json` |
| `analyse` | renderer `analyse` (ffprobe, `silencedetect` at -35 dB, 0.25 s); the recording's hash is compared with the record's (`recording_changed`) | `raw.*` | `analysis.json` |
| `still` (side step) | renderer `still` at about 1.5 s, or 300 ms before the first speech after a leading silence of 2 s or more, never nearer than 100 ms to the end (`still_offset`) | `raw.*`, `analysis.json` | `still-<sha12>.png` |
| `retakes` | renderer `base` with no retake confirmed | transcript, analysis | `proposal.edl.json` |
| `align-proposal` | renderer `align` on the transcript (runs `check_script.py` in the container); registers the asset slots | post file, transcript | `proposal.beats.json`; `slots` in the record |
| `review` | **stop 1**: opens "Check the captions" (kind `question`; a fixed text with the recording id and counts, no word of the transcript) | proposals | the decision |
| `remap` | makes `transcript.edited.json` (or the transcript stands in), hardens every word, scans for credentials (`workcopy.credential_findings`) | edited transcript, transcript | `transcript.edited.json` |
| `base` | renderer `base` on the edited transcript with `--face-box`, `--color`, `--font` from `theme.theme_args`, and `--confirm <id>` for each confirmed retake (a second call) | edited transcript, analysis, review, identity | `edl.json` |
| `align` | renderer `align` with `--anchor`, `--empty-slot`; a dropped overlay is removed afterwards | post, edited transcript, edl, review, proposal | `beats.json` |
| `check` | renderer `check`: schema, bounds, hardening, colours and fonts, credential shapes, the platform's file | edl, beats, vocabulary | none |
| `render` | renderer `render` with the recording, the platform file and each used slot's file bound by id and sha256; refused at 20 renders kept (`render_cap`) | edl, beats, raw, assets | `render-<sha12>.mp4`, `render.json` |
| `cover` | renderer `cover` at the person's offset (default the first frame) | render, review | `cover-<sha12>.png`, `render.json` |
| `approval` | **stop 2**: opens "Approve the rendered video" (kind `question`; the render's name, hash, size and the cover, and, when the default theme was used, why) | render.json | the decision |

The plan's separate `resolve` step, its host-side annotation validator and its payload builder are not steps: the renderer resolves the beats at `render`, `align` runs the skill's own checker inside the container (`runtime/isolated.py` only gives the checker's path), and the payload builder belongs to the publishing packages that are not built.

**Resumable.** A step that is `done` is not run again; a step that fails leaves the task `failed` with the note `<step>: <code> [<field>] -- <what to do>` and `pipeline.json`'s `failure`; the next `media-pipeline` (or `prepare-again`) starts at the failed step. A step's own exception is turned into a closed word: `StepFailure` for a refusal, `io_error` for an `OSError`, `provider_output_invalid` for a provider's JSON of the wrong shape (`pipeline._execute`). A provider that is not set up gives a code and the command the person runs (`next_for`): the pipeline never builds, pulls, fetches or pins.

**Locks and one writer.** One pipeline per recording. The first state of a recording and its code task are made under `pipeline.lock` (waited for), so a double click makes one task. The long work holds the code task's `task-<id>.lock` (`ops_pipeline._held`): it is the proof the task is alive (`ops_runs._recover` ends a `running` task whose lock nobody holds as `failed`), and it makes every write of `pipeline.json`, `transcript.edited.json` and `review.json` one writer at a time, read again under the lock. A second `media-pipeline`, `captions-edit`, `captions-done` or `prepare-again` meanwhile is refused (`already being run`). The code task itself has no skill and no run row; the store keeps it out of every model path (`NEXT_READY_TASK`, `task_claim`, `task_retry`, `pending_resolve`), and its states move only through `code_task_move`.

**The two stops.** At each stop the task is `waiting` and the decision is open; the pipeline does nothing more until the person acts. Stop 1 is answered by `captions-done` (the operation answers the decision as the person, with an answer that holds no text, and resumes at `remap`); it needs the `revision` the person looked at (`stale_revision` otherwise) and is refused while a slot has neither a file nor a choice (`slot_needs_a_choice`). Stop 2 is answered by the video card: approving or sending back; no operation answers it as a free text.

**Send-back and resume.** `video-send-back` stores `sent_back` and `resume` in the record. The next `media-pipeline` or `prepare-again` of that platform, whatever step it names, opens the review again as the person left it (`step` becomes `review`), with no provider run, clears `resume`, and the decision says the video was sent back. The comment is shown by `captions-read` and never copied into a decision. Until then `video-approve` refuses with `sent_back` while the render and the caption are still the pair that was sent back; a new render or an edited caption lifts it.

**The still is a side step.** It runs after `analyse` and before `retakes`, is recorded like every step, and its failure never fails the pipeline: it is `skipped` with a closed `code`, the task and any open decision are not touched, and the next call tries again. It is made only while the review is not answered, so a recording already waiting at its review gets its still on the next call with no other step run again. `prepare-again --step still` makes it alone and keeps the earlier still when the remake is skipped (`pipeline.remake_side_step`).

**`prepare-again`.** `--step <step>` resets that step and every later one (the files they made are removed; a render stays until retention), keeps the person's decisions from `review` on, and from `align-proposal` or before also removes `transcript.edited.json` and `review.json`, because the words are new. Preparing `review` opens the captions as the person left them, with no model and nothing run again. Refused while the pipeline runs.

## Operations and routes

Rows of `runtime/operations.py:245-309`; the groups are `operations.GROUPS` (`:324`). A route marked loopback answers on the loopback socket only: on the `--lan` socket, or with a `Host` that is not a loopback one, it is a route that does not exist (`404`), except `approve` and `send-back`, which are refused there with `409` and the sentence "Watch and approve on the Mac that runs the service" (`service.LAN_APPROVAL`). None of the rows lists `mcp`, `chat` or `messaging`.

| Operation | Channels | Policy group | Route | Loopback only | What it does |
|---|---|---|---|---|---|
| `media-in` | terminal, page | `media` | `POST /projects/{p}/media` (octet-stream; headers `X-Recording-Id`, `X-Slot-Id`, `X-File-Name`) | yes | takes a recording (or, with a slot, an asset's image or clip) into the store; type read from the bytes; without a recording id one is issued |
| `media-list` | terminal, page | `read` | `GET /projects/{p}/media?recording=` | no | the recordings with status, file facts, slots, retention dates and pipeline summary; the store's use of its limits; the `platforms` the service has a data file for |
| `media-purge` | terminal | none (the terminal is never narrowed) | none | n/a | applies the retention now; with `--recording`, that recording whatever its age (a `scheduled` one only with `--include-scheduled`) |
| `media-pipeline` | terminal, page | `media` | `POST /projects/{p}/media/{rid}/pipeline` (`post`, `network`, `request`) | yes | a job: starts or resumes the pipeline; links the post file to the network on the first call |
| `captions-read` | terminal, page | `media` | `GET .../media/{rid}/captions` | yes | the review: words as caption chunks, retakes, adjusted and left-out words, beats with score, slots, decisions, `still`, `sent_back` |
| `captions-edit` | terminal, page | `media` | `POST .../media/{rid}/captions` (`revision`, `text`) | yes | applies a JSON list of closed edit objects; refused as a whole when one is |
| `captions-done` | terminal, page | `media` | `POST .../media/{rid}/captions/done` (`revision`) | yes | a job: answers stop 1 and runs on to the cover |
| `prepare-again` | terminal, page | `media` | `POST .../media/{rid}/prepare-again` (`step`) | yes | a job: starts over from a named step |
| `video-card` | terminal, page | `read` | `GET /projects/{p}/video/{rid}?platform=` | no | the card: the render's facts, the cover, the caption with its hash, the approval and whether it holds, the last send-back, the download name, `problems` |
| `video-approve` | terminal, page | `video` | `POST .../video/{rid}/approve` (`video_sha256`, `caption_sha256`, `platform`) | yes (409 elsewhere) | the person's one explicit action; records `approvals.<platform>` |
| `video-send-back` | terminal, page | `video` | `POST .../video/{rid}/send-back` (`comment`, `platform`) | yes (409 elsewhere) | removes the approval, records `sent_back` and `resume` |
| `video-raw` | page | `read` | `GET .../video/{rid}/render/{sha}` | yes | the render's bytes, streamed with ranges; one at a time |
| `video-cover` | page | `read` | `GET .../video/{rid}/cover/{sha}` | yes | the cover PNG (small, no gate) |
| `video-download` | page | `read` | `GET .../video/{rid}/download/{platform}` | yes | the approved file as an attachment; refused while no approval holds; one at a time |
| `media-still` | page | `read` | `GET .../media/{rid}/still/{sha}` | yes | the still PNG chosen by the recording and its own sha256 |

Not built: the storyboard's operations (`storyboard`, `storyboard-raw`, `storyboard-preview-raw`), the catalogue's and the review-only beat's. The renderer's `storyboard` verb exists and nothing in `runtime/operations.py` calls it. `media-pipeline`, `captions-done` and `prepare-again` are jobs (`"job": True`): the service answers at once with a job to ask for again.

Byte routes are streamed in chunks of 256 KiB from the verified descriptor; one `Range` is answered `206`, a bad or multiple one `416`; headers are `ETag` (the sha256), `Cache-Control: no-store`, `nosniff`, `Content-Disposition` inline or, for the download, `attachment; filename="short-video-<platform>-<sha12>.mp4"`. A stream has a total time of 30 s plus its length at 256 KiB/s, at most 30 minutes, after which the file and the gate are given back (`service.py:279-286`). The page's policy allows `media-src blob:` and `img-src blob:`: the page fetches the bytes with the bearer header and plays a `blob:` URL it built, so the token is never in an address.

## The providers

Both are classes the runtime uses and no skill requires (D11); both run everything that reads a recording in a container, built by a command the person types, and are run by the image id the build recorded. The pipeline reaches them only through `providers/resolve.py`'s `call`, with a minimal environment (`ops_pipeline.ENV_KEEP`: what finds a program, a home, a docker daemon and the state folder, and the choice of an implementation).

### The transcriber (`transcriber:speech`)

`providers/transcriber/whispercpp.py` (standard library only) runs whisper.cpp `v1.9.5` (`whisper-cli`) in a container built from `providers/transcriber/Dockerfile` (base image by digest, the tag and commit pinned, a dated Debian snapshot, ffmpeg inside, CPU only, a fixed CPU floor per architecture). Image `openhora-transcriber:<definition hash>`; the build records the image id in `<state>/transcriber/image.json`. Verbs: `--check`, `models`, `build (--dry-run | --confirmed)`, `reap`, `transcribe`. The audio never leaves the machine as long as the docker daemon is local: the provider refuses a remote `DOCKER_HOST` or context.

- **Models** (`providers/transcriber/models.json`): `tiny`, `small`, `medium`, `large-v3-turbo`, each with the file, the sha256 and size Hugging Face lists at a pinned revision, the DTW preset and the container's memory limit (1, 2, 4 and 5 GiB). The person puts the file in `<state>/transcriber/models/`; the provider hashes it against the pin before any container starts, and refuses a model with no pin. The project chooses one in `runtime.json` `media.model`.
- **Modes** (`--timestamps`): `word` (whisper's token times), `ml1` (one word per segment, a silence absorbed by the word before) and `dtw` (the start from dynamic time warping over the attention heads, a word ends where the next begins; `-nfa` because whisper.cpp turns DTW off with flash attention). The pipeline always asks for `dtw` (check C3) and the transcript records the mode in `facts.timestamps`.
- **What it reports** (`transcript.schema.json`): words with `start`, `end`, `segment`, `probability` and `estimated` (a word whisper left untimed lies between its neighbours); segments; and in `facts` the counts `words_without_timing`, `clamped_words` and `dropped_annotations` (a note such as `[BLANK_AUDIO]` is not a word), the image id, the model's hash, the CPU flags and `wall_seconds`. The text of the speech is never printed; a failure shows the last 300 characters of stderr or a closed code.
- **The container** (each limit a test in `providers/transcriber/tests/test_whispercpp.py`): `--network none`, a read-only root, memory-backed `/tmp` and `/scratch`, `--cap-drop ALL`, `no-new-privileges`, a non-root user, no environment, `--pull never`, pids, memory (swap included) and CPU limits, the input and the model read-only, one work folder read-write that the provider looks at afterwards (at most 8 entries, regular files only, at most 80 MiB, every file opened with `O_NOFOLLOW`), the disk checked before the run, a timeout that removes the container by name, and a label so that `reap` finds a leftover.

### The renderer (`renderer:video`)

`providers/renderer/ffmpeg.py` is the host side (standard library only): it checks the flags, stages the inputs into a private job folder, builds the `docker run` command, runs it and reads the result as untrusted. `_inner.py` is the container's entry point; the other `_*.py` files are the edit list and its checks, the cuts and captions, the beats and their alignment, the CDP driver and frame loop, ffmpeg and ffprobe, and the storyboard. Image `openhora-renderer:<definition hash>`: `debian` by digest, packages from a dated Debian snapshot, and Chrome for Testing's headless shell pinned by version (`155.0.8059.39`) and by the sha256 of the archive (`providers/renderer/browser-pin.json`).

**Verbs.** Every verb prints one JSON object; a refusal exits 1 with `refused: <closed code> <field>` as the first line of stderr.

| Verb | What it does |
|---|---|
| `analyse` | ffprobe facts, the recording's sha256, `silencedetect` intervals |
| `base` | the code-generated edit list: silence-first cuts (no range under 0.4 s, 0.14 s of tail and 0.10 s of attack kept), captions of one to three words, a zoom on every second range, the face box, the theme, the retake proposals; `--confirm <id>` cuts a proposal |
| `align` | runs the post-writing skill's own checker inside the container, matches each beat's line to word indices (NFKC, casefold, best window; figures excluded; a tie goes to the last occurrence), writes `beats.json`; `--anchor`, `--empty-slot`, `--edl` |
| `check` | schema, bounds, text hardening, colours, fonts, credential shapes, the platform's file |
| `render` | draws the overlay frames with Chrome, composes with ffmpeg, then **verifies in a fresh container** (`verify`, an inner verb: ffprobe facts against the platform's spec, bt709 tags, length, sha256) and names the file only after that passes |
| `verify` | the inner verb `render` calls in the second container; not a verb of the host's command line |
| `cover` | one PNG frame of a render at `--offset-ms` |
| `still` | one PNG of the recording at `--at-ms`, framed exactly as the render frames the source into 1080 x 1920 (`_media.framing_filter`), so a pixel of the still is a pixel of the render's unzoomed picture |
| `storyboard` | what a script's beats will look like before a recording exists: the beats' lines become synthetic words at 2.5 a second, the render's own checks run before a frame is drawn, one still per beat and a contact sheet are written over a flat neutral picture; no recording and no transcript are mounted |
| `build`, `pin-browser`, `--check`, `reap`, `pin-templates` | the person's and the maintainer's commands; only `build` and `pin-browser` take `--confirmed` and use the network |

**The edit-list contract** is the renderer-neutral pair `edl.json` and `beats.json` above. `base` writes frame ranges, word indices, tokens and a face box and no filter text; `align` writes preset names, typed parameters and slot ids, never a description or a file; `render` takes both, the recording, the platform's file and the person's asset files by slot. What an implementation owns is only how it draws.

**Presets are HTML templates.** `providers/renderer/templates/` holds `caption`, `keyword`, `list`, `number`, `quote`, `cutaway` and `pip`, each a pure `renderAt(t, data)`, each pinned by sha256 in `templates/pins.json` (a template whose hash differs is refused). What the renderer decides about the vocabulary is `renderer-presets.json`: the frame (1080 x 1920, 30 fps), the default colours, each preset's timing, the limits (4000 words, 40 characters a word, 300 s of input, 27000 frames), the zones and the zoom. A test holds the presets, their templates and the parameters equal to `shared/references/video-presets.json`. The fonts a render may use are `providers/renderer/assets/fonts/allowlist.json` (Inter 500 and 800 and JetBrains Mono 500, SIL OFL, each with its hash); a font not listed is never used and the render says which font each role used. Text is drawn with `textContent`.

**The face-box zones.** The person gives the face box once per recording (a default `{x:240, y:620, w:600, h:560}` otherwise). Cards (`keyword`, `list`, `number`, `quote`) live in the band above it (from y 110 down to the face less 18 px), captions in the band below it (the face plus 18 px down to y 1620). The box is the zoomed one: a zoomed range is a punch-in about a fixed point (the face's horizontal centre, a quarter of its height down), and the bands are computed from the union of the face's box over every range a card or caption lives through. Every drawn card, chip and caption word is measured after each frame and the render fails (`overlay_hits_face`) when one touches the box; `base` refuses a box that leaves less than 80 px above or 120 px below at the largest zoom (`face_box_leaves_no_room`).

**Determinism.** The compose command pins the encoder's threads (`-threads 4`, whose output depends on the count), the filter graph's threads, `-sws_flags` and the flags of every explicit `scale` (`lanczos+accurate_rnd+bitexact`), `+bitexact` on the muxer and the streams, and no metadata. Measured on 15 s of the first real recording, in the container with `--cpuset-cpus` so that it really saw 4, 8 and 14 cores: the pinned command gave one sha256 at all three, the same command without the pins gave a different one each time (`providers/renderer/README.md`, "What makes a render the same bytes"). A render is reproducible on the same image and CPU architecture; across architectures it is expected to look the same, not to be byte-identical.

**The image and the browser pin.** `build --confirmed` pulls the pinned base, installs the snapshot's packages and downloads the browser; it refuses while the sha256 of the daemon's architecture is not pinned, and the image's own build (`_fetch_browser.py`) refuses an archive whose size, md5 or sha256 differs. In the repository the `linux-arm64` archive has its sha256 and `linux64` has none (`browser-pin.json`): an amd64 daemon cannot build the image until the maintainer runs `pin-browser --confirmed` and commits the result. The image's tag is the hash of its definition, so a change to a verb changes the tag: until the person builds again every renderer step reports `image_not_built` (or `image_stale` for an older image).

**How to swap an implementation (D21).** Write another implementation of the class, `providers/renderer/<impl>.py` (or `providers/transcriber/<impl>.py`), with the same verbs and the same edit list; it must read `edl.json` and `beats.json` as they are, pass the contract tests, and produce a file the host stores only after its own check. `providers/resolve.py` picks among several implementations of one class by `RENDERER_VIDEO_PROVIDER` then `RENDERER_PROVIDER` (and `TRANSCRIBER_SPEECH_PROVIDER` then `TRANSCRIBER_PROVIDER`), which the pipeline's provider environment passes through. **There is no key of `runtime.json` for it yet**: D21 decided that the person chooses per project by a setting accepted with `accept-config` and left its name to the package that adds a second implementation; today the choice is an environment variable of the service. A hosted implementation brings the privacy terms of path 3a and, by D21, is gated by the consent setting of D17. Principle 11 holds for any implementation: the edit list carries no executable text, and the approval binds the bytes that come back.

## The page

The three parts live in the Tasks tab and the Agent tab of a project's floor (`interface/js/floor/`). Each puts every value in with `textContent`, withholds a control the page's policy turns off (and says so on one line), and, off the Mac, says to open the page there and reads nothing but the pipeline's steps.

**New short video** (`media-start.js`, `media-upload.js`, `media-start-model.js`). Choose a file (a `.mov` or `.mp4` up to 1 GiB and 5 minutes) and "Upload the recording"; a progress bar shows the upload. Every stored recording whose pipeline has not started is offered, from `media-list`, so a reload strands none: choose the post file (the Markdown documents under `docs/` that carry a script block, read from `artifacts` and `artifact`; with several the page asks and never picks, and with none it asks for the path), the network (the post file's `- Network:` line, else a choice among the `platforms` the service has a data file for), and "Edit this recording". That calls `media-pipeline` and lists the steps until it stops at "Check the captions" or at a failure, told in the sentence of its closed code with the command to run. No model is called and no request is needed.

**Check the captions** (`captions-view.js`, `captions-model.js`, `autosave.js`). In the opened row of the code task, with a chip for the state ("Waiting for you", "Checked", "Running", "Not at the review yet", "On the Mac"). Every change is one `captions-edit` call with the revision last read and a list of closed objects; a refused change shows its reason as a sentence and changes nothing on screen.

| Part | What each control does |
|---|---|
| The words | the transcript as caption chunks, each word a button: select one word or a range. Dashed strike-through marks a retake the code proposes cutting, a red double strike-through a retake you confirmed, a dotted underline a word whose timing the code adjusted. "Save the spelling" (`edit`), "Split at the spaces" (`split`: the word's time is shared out and marked estimated), "Merge into one word" (`merge`), "Delete the word" or "Delete these N words" (`delete`), "Clear the selection". There is no field for a time |
| Retakes | each proposal with its text, seconds and kind; "Confirm the cut" or "Undo" (`retake`) |
| Beats of the script | each beat with its preset, score and the words it matched; one below the threshold is flagged. "Anchor to the selected words" (`anchor`), "Clear the anchor", "Drop the overlay" or "Keep the overlay" (`overlay`) |
| Words the code moved or left out | the adjusted words, and the words left out of the captions because they sit in silence the transcriber could not place them in |
| Asset slots | for each slot of a `cutaway` or `pip`: upload a PNG or JPEG for that slot, or choose `keyword` or `none` (`slot`); the page says the renderer takes an image for now |
| Face box and cover | a schematic of the frame (not a picture): tap where the face is, choose small, medium or large, or type x, y, w, h; "Clear the face box"; the cover's second in the finished video, "First frame". Numbers autosave after a pause or on leaving the field (`face_box`, `cover`) |
| Done | "Done: the captions are right" sends the revision and nothing of the words; it is withheld while a slot has neither a file nor a choice. After it, "Open the captions again" runs `prepare-again --step review` |

The review has no control for the `theme` edit, and the picture behind the face box is a schematic: `api.mediaStill` exists and no view uses it (open items).

**The video card** (`video-card.js`). It shows what `video-card` returned for one recording: the video (fetched with the bearer header and played from a `blob:` URL), the cover, the size, length and sha256 of the file (the first 12 characters for the eye), and the caption exactly as the post file has it with its own sha256. States: no render yet (making: the page reads the pipeline again by itself, at most 200 reads, then says to press "Check again"; or idle: the pipeline stopped); a render that has not loaded (approval waits: "You can approve once the video has loaded"); **"Approve this video and caption"**, which sends the two hashes the card shows, read back from its own state at the click; **Approved** (with `Download short-video-<platform>-<sha12>.mp4`, for the person to post by hand); **Approval no longer holds** when the render or the caption changed (`render_changed`, `caption_changed`); **sent back** (the comment, and the notice that it takes no approval until it is rendered again or its caption edited); "Send back with a comment" (required, at most 1000 characters). Off the Mac the card shows the caption and the hashes and says "Watch and approve on the Mac".

## Security model

### Hard limits that live in code

Principle 11 of [AGENTS.md](../../../AGENTS.md): what must never happen is prevented by code or structure, not by a prompt or a test. For the short video:

| Limit | Where it is enforced |
|---|---|
| The person approves the exact file and caption: the approval binds the render's sha256, the caption's sha256, the platform and the date; the file is hashed again at the approval; a re-render or an edit makes it stale; a stale approval downloads nothing | `ops_video.video_approve`, `video.approval_state`, `video.open_render(fresh=True)`, `video_download` |
| An approval is refused from any channel but the terminal and the page, from the LAN socket, for a post that is not `open`, and while a send-back holds the post (checked again under the record lock) | `ops_video.APPROVE_CHANNELS`, `service.py` (`LAN_APPROVAL`), `_sent_back_blocks` |
| No operation of the feature calls a model, and none is on `mcp`, `chat` or `messaging` | the rows of `runtime/operations.py:245-309` (`model: False`, channels) |
| The person edits words, never times; a key that names a time is refused, not ignored | `captions.OPS`, `captions.TIME_KEYS`; the operation has no field |
| A file is chosen by id and hash, opened without following a link, verified through the descriptor it is read from | `runtime/video.py:140-258` |
| A recording does not cross the network: the media, review and byte routes are no route on the LAN socket | `service._route(..., loopback=True)`, `handle_stream` |
| One video read at a time and a total time for a stream | `service.ONE_AT_A_TIME`, `STREAM_*` |
| Intake: type read from the bytes, length bounded before one byte is read, free space, quota, one upload at a time, a deadline, one video stream, at most 300 s, not HDR, `O_EXCL|O_NOFOLLOW` temporary, `os.link` never over a file | `media.receive` (`test_media_limits.py` names each limit) |
| Retention runs in code, never by a task or a model | `media.purge`, `ops_media.purge_round` (called at the start of every dispatcher round) |
| Providers run in containers with no network, a read-only root, every capability dropped, no host environment, an image run by its recorded id, never pulled at run time, three mounts at most | `providers/transcriber/whispercpp.py` and `providers/renderer/_docker.py` (`container_argv`; `test_renderer_docker.py`, `test_whispercpp.py`) |
| The renderer's output is untrusted: looked at (links, FIFOs, count, size), read with `O_NOFOLLOW`, hashed, and a render is verified in a fresh container before it is named | `providers/renderer/ffmpeg.py`, `_docker.copy_out` |
| The pipeline never builds, pulls, fetches or pins: a build downloads, and downloads are the person's word | `pipeline.next_for` (the command is the person's); no step calls a verb that takes `--confirmed` |
| Closed words only in notes, decisions and files: no word of a transcript or a post | `pipeline.failure_from`, `StepFailure`, `review_decision` (counts only) |
| A transcript is scanned for credentials before it is drawn, and the renderer scans again | `workcopy.credential_findings` at `remap`; `check` in the renderer |
| Templates and fonts are pinned: a template whose hash differs, a font not on the allow-list is refused | `templates/pins.json`, `assets/fonts/allowlist.json` |
| An asset is only a file the person uploads for the slot, bound by its slot id and sha256, PNG or JPEG at render | `pipeline._asset_for`, `_render` (`asset_type`), `media.register_slots` |
| The theme is data: nothing in the tokens block is CSS, a path or a command; a draft identity, a bad block or a text pair under 4.5:1 stops the step with a closed code | `runtime/theme.py` (`ThemeError`, `MIN_TEXT_RATIO`) |
| The provider's environment is minimal: no key or token of the runtime reaches a container's client | `ops_pipeline._provider_env`, `ENV_KEEP` |

### Residual risks, stated plainly

- **Chrome's own sandbox is off inside the renderer image**, with the container as the boundary (`--no-sandbox`, a stated trade-off: the alternative is a wider seccomp profile that cannot be tested here). A renderer-process exploit is contained by the container only. What the container can reach is what its mounts allow: it reads the recording and everything staged in the job folder (the transcript, the post, the assets) and writes the output folder, which the host reads as untrusted. It has no network, so nothing can leave the machine. The mode is never silent: every render's result says `browser_sandbox`, and the sandbox is on everywhere but inside the image.
- **A same-user write in place.** The render is 0400 and the checks above hold against a swap, but the person's own account owns the files and can change one under any check; a write in place while a stream is going is seen only by the next request, whose identity has moved. The same account can write an `approvals` entry into `record.json` by hand: the approval is a plain record in the person's own folder, not a signature. Download and the card hash the file again, so a forged approval of a file that exists still downloads that file; it cannot name a file that does not hash to its name.
- **An asset is only header-checked.** An image or clip for a slot is checked by its header and, for a clip, by ffprobe; it is not decoded or re-encoded by the intake, and the browser in the container decodes it. The renderer's README says the intake must normalise; the intake does not (open items). Clips are not supported at render (`asset_type`).
- **Backups and the download are outside the retention.** The operating system's backups and the MP4 the person downloads are not removed by `media.purge`, and the page says so.
- **The images are only as trustworthy as their pins.** A model's hash is compared on the host and the file is then mounted by path (the models folder must be 0700 and the user's); the base images are pinned by digest and the packages by a dated snapshot, not audited. The amd64 renderer image has not been built or run, and a render is byte-identical only on the same image and CPU architecture.
- **Measured on one recording.** The choice of `dtw`, the cut parameters, the zones and the presets were judged on one real recording (a 192.7 s one, A4 and A5.1); their quality beyond it is unverified, and the transcript's accuracy depends on the model and the speaker.
- **The card crosses the LAN.** `media-list` and `video-card` are not loopback-only: the caption, the hashes and the pipeline's steps are readable over `--lan` (plain HTTP, with the token); the video, the review and every recording byte are not.
- **Hashing a gigabyte costs a pass.** A cold card of a large render reads it once, single flight; an approval reads it again.

## Operating it

1. **Build the transcriber's image and put a model in place** (the person's commands, once; Docker must be installed and running):

   ```sh
   python3 providers/transcriber/whispercpp.py build --confirmed
   python3 providers/transcriber/whispercpp.py models
   python3 providers/transcriber/whispercpp.py --check --model small
   ```

   `models` prints the models folder (`<state>/transcriber/models/`) and, for each pinned model, its source URL and whether the file is there; download the file from that URL into the folder and run `--check` to hash it against the pin. The models folder must be mode 0700 and the user's. Nothing in the repository downloads a model.
2. **Build the renderer's image** (the maintainer pins the browser once; on Apple silicon the arm64 pin is already committed):

   ```sh
   python3 providers/renderer/ffmpeg.py pin-browser --confirmed   # only where the daemon's architecture has no sha256 in browser-pin.json
   python3 providers/renderer/ffmpeg.py build --confirmed
   python3 providers/renderer/ffmpeg.py --check
   ```

   Build again after any change to the renderer's definition (its tag is the definition's hash); until then every renderer step says `image_not_built`.
3. **Set the project's `media` setting** in `docs/workbench/runtime.json` (fictional values; nothing in it is a secret):

   ```json
   {"media": {"model": "small", "language": "en"}}
   ```

   `model` is a name of `providers/transcriber/models.json`; `language` is a two or three letter code or `auto`. A project with no setting stops at its first step and says which. The file is accepted by its hash: any operation refuses a configuration whose hash is not the accepted one and prints the hash; then `python3 runtime/cli.py accept-config --project <dir> --sha256 <hash>`. No operation of the page changes the setting.
4. **Make a reel.** Have `mkt-social-copy` write the post file (or write one with a ```` ```script ```` block, a ```` ```post ```` block and a `- Network:` line). Start the service (`uv run --with keyring==25.7.0 python3 runtime/service.py --project <dir>`), open the page on the Mac, upload the recording in "New short video", choose the post file and "Edit this recording". The same from the terminal:

   ```sh
   python3 runtime/cli.py media-in --project <dir> --file <recording.mov>
   python3 runtime/cli.py media-pipeline --project <dir> --recording <id> --post docs/marketing/content/<post>.md --network instagram
   ```

   When the task waits at "Check the captions", open its row, check the words, retakes, beats, slots, face box and cover, and press Done. When it waits at "Approve the rendered video", open the video card, watch, and approve, send back or download.
5. **What to do on a closed refusal code.** The code is in the task's note and in `pipeline.json`'s `failure`; the next `media-pipeline` resumes at the failed step.

   | Code | Cause | What to do |
   |---|---|---|
   | `docker_missing`, `docker_not_answering`, `docker_daemon_not_local` | Docker is not installed, stopped, or not a local daemon | install and start Docker; the pipeline never starts it |
   | `image_not_built`, `image_stale`, `image_not_recorded` | the provider's image is missing, older than its definition, or not recorded | run the provider's `build --confirmed` (the note names the command) |
   | `model_missing`, `model_mismatch` | the transcriber's model file is absent, unpinned or differs from its pin | `whispercpp.py models`, put the file in place, `--check` |
   | `pin_incomplete` | the browser archive of this architecture has no pinned sha256 | the maintainer runs `ffmpeg.py pin-browser --confirmed` and commits the pin |
   | `not_configured` (`media.model`, `media.language`) | the project's `media` setting is missing | set it in `runtime.json` and accept it |
   | `retake_lost`, `anchor_lost` | the words a confirmed retake or an anchor stood on were deleted | `prepare-again --step review` (or "Open the captions again") and decide again |
   | `slot_empty`, `slot_needs_a_choice` | a `cutaway` or `pip` slot has neither a file nor a choice | upload a PNG or JPEG for it, or choose `keyword` or `none` |
   | `asset_type` | the file of a slot is not a PNG or a JPEG | export it as one of them and upload again |
   | `overlay_hits_face`, `face_box_leaves_no_room` | a card or caption would touch the face box, or the box leaves no room | move or shrink the face box in the review, or change the beat's preset |
   | `credential_in_transcript` | a word of the edited transcript looks like a credential | correct the word in the review |
   | `theme_draft`, `theme_low_contrast`, `theme_block_invalid` and the other `theme_*` | the identity is a draft, a text pair is under 4.5:1, or the block is wrong | fix or approve the identity, or choose the default theme (the sentence names the `theme` edit of `captions-edit`) |
   | `render_cap` | 20 renders are kept | `media-purge`, or delete an abandoned recording by id |
   | `stale_revision` | the review changed since the person read it | read the captions again |
   | `sent_back` | the post was sent back and has not changed | edit the caption or render again |
   | `timeout`, `provider_output_invalid`, `io_error` | a verb ran past its limit, answered the wrong shape, or the disk failed | run again; check the disk |

6. **Retention and purge.** Code applies it at the start of every dispatcher round and with `python3 runtime/cli.py media-purge --project <dir>`. The raw recording, transcript, analysis, still, proposals, edited transcript, review, assets and the edit task's run folders go 7 days after a post is published or cancelled; renders, covers and the payload folder go 30 days after publication; the media of an abandoned post (`open`, untouched) go 30 days after its last change; a `scheduled` recording is never purged by age. A recording whose code or edit task is running, or whose open post's task still waits, is left for the next round. Because nothing yet marks a post `published` or `cancelled`, a finished short video stays `open`, and the abandoned rule skips an open post whose task is `waiting` (`ops_media._run_dirs_of`): approving a video writes only `record.json`, so the code task stays `waiting` at stop 2 and its decision stays open. A finished reel is therefore removed only by a purge by id, or after its request is cancelled. A purge by id (`--recording <id>`) removes a recording whatever its age (a `scheduled` one only with `--include-scheduled`). The OS's backups and the downloaded MP4 are outside it.

## Open items

- **Publishing and scheduling** (plan packages P8 to P10) are not built: the first milestone ends with a download the person posts by hand. `media.mark` is never called, so no recording leaves `open`.
- **Approving does not close stop 2.** `video-approve` records the approval in `record.json` and moves nothing else: the decision "Approve the rendered video" stays in the pending list, the code task stays `waiting`, and nobody can answer that decision (`pending_resolve` refuses it and says it is resolved "by the approval of the render", which `video-approve` does not do). Until a package closes it on approval, the pending list keeps it and the age-based retention never reaches the recording.
- **The model's part** (P6, the annotation of M2, amended by A6.7) waits for the consent setting (D17) and for the new presets and the review's "Add an animation".
- **The look of the video** (amendment A5): the six caption styles and the pt-BR chunking rule (P5c), the richer motion and the new presets (P5d), the caption band's bottom at 1560 px (D26, the code still has 1620) and Anton for the Block style (D27), and sound cues (P5e, D25) are decided and not built.
- PerfectUI only: remove every own padding and font size on tabs, link-style buttons, the lobby request title and tab count, the request chip, the frame's icon buttons and `wb-muted`, and empty the `PENDING` list of `runtime/tests/test_interface_button_sizes.py` (decided 2026-10-14: if PerfectUI provides an option, use only it).
- Still frame behind the face box in the caption review: the backend (`still`, `media-still`, `api.mediaStill`) is merged; the view does not use it yet.
- Page control for the default-theme choice in the caption review: the backend (the `theme` edit) is merged; today it is a `captions-edit` call in a terminal.
- Wave 2 of A6: the runtime operations and the review card for the storyboard (`storyboard`, `storyboard-raw`, `storyboard-preview-raw` on the loopback socket), the catalogue of animations (P5f) and "Add an animation" in the review (P4f).
- Rebuild the renderer image after the pending renderer changes merge (the tag changes), then rerun the reel through the page to check the brand colours.
- Lab tests waiting for the maintainer's word: `brand-identity` (15 runs) and `mkt-social-copy` (after P5c and P5d).
- **A second implementation** of either class, and the project key that chooses it (D21): none exists, the choice is an environment variable. HyperFrames may stay an optional render-only provider only if a second engine is wanted (D23).
- **The assets' normalisation:** the intake accepts PNG, JPEG, WebP and clips of up to 60 s, and the render takes only PNG and JPEG without re-encoding them; a decode-once-in-the-container step that writes a metadata-free PNG at frame size is not built.
- **The amd64 renderer image** has no pinned browser archive, and neither image has been built or run on any machine but the one that measured them.
- **`linkedin` is offered as a network** by `media-list` (it has a data file) but its file has no `video` block, so a render for it would be checked against no video spec; the list is every file of `shared/references/platforms/`.

## Glossary additions

The terms added to the platform map's glossary ([README.md](README.md)):

| Term | What it is |
|---|---|
| Media store | `<data_dir>/media/`: one folder per recording, outside every repository; `runtime/media.py` is the one module that writes there |
| Recording | A person's video in the media store, named by an id issued by code (16 hexadecimal characters); one `record.json` ties it to its post files, slots and tasks |
| Media pipeline | The steps from a recording to its rendered video and cover, with two stops; code and containers only, no model (`runtime/pipeline.py`) |
| Code task | The task of a recording's pipeline: no skill, key `media:<recording id>`, moved only through `code_task_move`, carrying its two decisions |
| Caption review | The stop "Check the captions": the person edits words, confirms retakes, anchors beats, answers slots, gives the face box and the cover; code owns every time |
| Origin | The range of `transcript.json` words an edited word stands for; the numbering every decision of the review is kept in |
| Edit list | `edl.json`, with `beats.json`: the renderer-neutral description of a video (cuts, words, captions, theme, face box, zoom, overlays), holding no executable text |
| Beat | One spoken thought of a script, with its line, role and, optionally, a preset and its parameters |
| Preset | One entry of the closed vocabulary `shared/references/video-presets.json`: an animation drawn by an HTML template, with typed parameters |
| Asset slot | A place in a beat for a file the person uploads, named by an id issued by code and bound to the file's sha256 |
| Face box | The speaker's face in frame pixels; cards live above it and captions below it, and a render fails when one touches it |
| Still | One frame of the recording, framed as the render frames it, for placing the face box |
| Render | `render-<sha12>.mp4`, written once by the renderer, 0400, named by its own bytes, verified in a fresh container |
| Video approval | The person's approval of one render and one caption, bound by their two sha256 values; stale the moment either changes |
| Send-back | The person's return of a video to the review with a comment; it removes the approval and holds the post until it changes |
| Brand tokens | The closed `brand-tokens` block of `docs/brand/identity.md` that code maps to the renderer's colours and fonts |

## Changes

- 2026-10-14: first version, written from the code at the head of `feature/short-video` (`9c42df1f`), `contracts/runtime.md` and the plan's decisions D1 to D35 and amendments A1 to A6: the artifacts and their relations, the pipeline, the operations and routes, the transcriber and the renderer, the page, the security model, a runbook and the open items.
