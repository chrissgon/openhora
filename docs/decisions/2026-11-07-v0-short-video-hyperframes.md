## 2026-11-07: HyperFrames becomes a second engine of renderer:video beside ffmpeg, and the rules of the video delivery are recorded (V0; documentation only: no code, no skill, no measurement change, no lab run)

**What this entry is.** V0 is the first package of the video delivery. This entry records:
- the maintainer's decisions of 2026-11-07 on drawing short videos with HyperFrames;
- the standing rules of the delivery, `VD1` to `VD18` (section 10).

Most of those rules were first decided between 2026-10-12 and 2026-10-14, in planning that was never merged. They are restated here as decisions of this entry, so this entry stands alone, and later entries and packages cite them by their `VD` id.

Nothing here builds anything. Each part names the package that implements it (V1a to V6). The delivery plan and its two independent reviews are kept outside the repository.

The maintainer's requirements for this delivery, quoted with the accents dropped, then in English:

- "Precisamos criar de forma que possamos utilizar o hyperframes, mas sendo possivel extende-lo, e nao limitar-se a ele." validate: allow english-only -- the maintainer's words, quoted
  In English: we need to build it so that we can use HyperFrames while being able to extend it, and not be limited to it.
- "O catalogo de animacoes deve poder ser o nosso ou do hyperframes. Devemos poder utilizar as animacoes deles tambem, apenas nao se limitar a elas." validate: allow english-only -- the maintainer's words, quoted
  In English: the catalogue of animations can be ours or HyperFrames'. We must be able to use their animations too, only not be limited to them.

### 1. HyperFrames, measured: the spike S2 and its outcome

An earlier trial, S1 (2026-10-14, on HyperFrames 0.8), did not adopt HyperFrames. It found four problems:
- caption layouts fixed at 1920x1080;
- a peak memory of 11.37 GB;
- bytes that were not guaranteed;
- no font or face-box guard.

HyperFrames 0.9 changed enough to measure it again.

The spike S2 measured HyperFrames 0.9.19 (tag `v0.9.19`, commit `b4cc674f`, Apache-2.0) as the drawing engine behind our edit list, inside the limits of `providers/_container.py`. It ran on one arm64 machine, with Docker given 14 CPUs, on two inputs:
- a synthetic input of 15.6 s;
- one real recording: 4K HEVC at 60 fps, 192.66 s, cut to 107.03 s in 29 kept ranges, with 7 beats.

Its checks:

- **C1, offline and quiet: pass.** 32 renders of the two test matrices ran with no network, and HyperFrames reported its telemetry disabled.
- **C2, same bytes: fail.** Three runs at the same container limits gave identical files for every input and block. But the video stream differed between 4 and 8 visible cores, and again with `--workers auto`, because HyperFrames gives x264 a thread count taken from the cores it sees. Two fixes were measured:
  - fixed `--cpus 8` and `--workers 4`, which repeat the bytes on any host with at least 8 cores;
  - a two-stage encode: HyperFrames writes a ProRes HQ intermediate, whose frames were identical at 4 and 8 cores, and ffmpeg encodes it with one thread. This gave one sha256 at 4 and at 8 cores on the synthetic input, with an intermediate of 217 MB for 15.6 s. It was not measured on the real input.
- **C3, the cuts are ours: pass, within one frame.** Compared with our own render of the same edit list:
  - synthetic: a mean PSNR of 45.6 dB at shift 0, and 5 of 5 ranges best at shift 0;
  - real: 43.5 dB at shift 0, with 27 of 29 ranges best at shift 0 and the other 2 best at one frame;
  - the lag between audio and video was 0 ms.
- **C4, our verify accepts it: pass,** for all 32 renders.
- **C5, only our fonts: pass, with a guard in code.** Only allow-listed faces were drawn, and the pt-BR letters had glyphs. But HyperFrames adds a bundled font for any named family it does not find declared, so a check that refuses such a page is required.
- **C6, the face-box guard: the method passes.** Every caption and card box was measured after HyperFrames' own seek of each frame, and a planted overlap was caught on both inputs. Per block, the highlight and pill captions had 0 hits, and the slam caption crossed the face box in 50 frames of the real input.
- **C7, cost: recorded.** The real input rendered in 162 to 168 s with a peak near 11.4 GiB. It needed a 12288 MB memory limit and a process limit of 1024 or more. The ffmpeg engine took 232 s with a peak of 1.3 GiB. The image was 1.11 GB, against 826 MB.
- **C8, fit: recorded.** On the real input, the highlight and pill captions reached 1586 and 1580 px. That is below the 1560 line (VD12) in 366 and 289 frames, and never below 1620.
- **C9, licence: recorded.** The six ported blocks carry no licence of their own and take the repository's Apache-2.0. GSAP 3.14.2, which every block needs, is under its own no-charge licence, not an open-source one.
- **C10, look: pending.** Contact sheets were made; the verdict is the maintainer's (decision 9).
- Beats of the kind `list` were not ported: 2 of the 7 real beats were not drawn.

**Outcome: NO-GO by C2 alone; accepted with the nine conditions.** By the spike's own rule, one failed check is a NO-GO, and C2 failed. Its cause is known and two fixes were measured. So on 2026-11-07 the maintainer accepted the start of the HyperFrames provider with conditions, and confirmed the nine conditions as written the same day.

The full S2 report, its result files and its contact sheets stay outside the repository, because one sheet holds frames of a real person. The figures above therefore cannot be checked from the repository (principle 10).

The nine conditions, as the delivery carries them:

1. **Determinism.** The two-stage encode, with stage 2 run by the common image's ffmpeg with pinned threads, and the proxy encode with pinned threads too. The fallback is fixed `--cpus 8` and `--workers 4`. It is tested at 4 and at 8 cores (decision 4).
2. **Limits.**
   - A 1080x1920 proxy of the recording, made by code (decision 5), and `--pids-limit 1024`.
   - The ProRes intermediate is about 1.5 GB per 107 s, so about 4.2 GB for a 300 s recording. It goes on a disk-backed mount under the media folder, after a free-space check, and is purged under VD8. It never goes into the memory-backed scratch.
   - The limits are stated in code.
3. **The face box is a hard limit in code.** It rests on the structural clip of each block, the per-frame check of the drawn boxes against the zoom plan's face box, and a pixel check. `slam` is out of M1 (decision 6).
4. **`list` beats.** A `list` block is built (V3b).
5. **Captions.** The 1560 line (VD12) is a gate on both engines.
6. **Fonts stay closed.** A guard refuses a page that names a family outside the allow-list (VD6), and a purge layer leaves no other font file in the image.
7. **Supply chain.**
   - Base images are pinned by digest, and archives by sha256 on both architectures (amd64 and arm64), for both engines.
   - The npm lockfile carries integrity hashes and is installed with `npm ci --ignore-scripts`.
   - The network is used only while an image is built, by a command the person starts.
8. **Licences.** Checked per item, as the allowlist rule of section 3 says. GSAP is installed from the lockfile at build and never committed (decision 7).
9. **Look (C10).** The maintainer judges each block before the pull request that brings it merges. The S2 sheets are judged now (decision 9).

### 2. HyperFrames is one engine of renderer:video, behind the edit list; ffmpeg stays

- **The seam is the edit list (VD1).** Both engines read the same renderer-neutral edit list (`edl.json` and `beats.json`) and pass the same contract tests:
  - same edit list in;
  - our verify accepts the result;
  - cuts within one frame;
  - the face box checked per frame;
  - closed fonts;
  - captions above 1560.

  The functional legs of these tests run in a CI docker job. The 4-against-8-core leg and the real-size leg run on the maintainer's machine, on a synthetic real-size input, with a committed report (V3c).
- **Code writes the composition** on both engines (VD3, principle 11).
- **`renderer:video` stays a runtime role** (VD2). `providers/resolve.py` takes an explicit implementation.
- **The two engines of M1:**
  - `ffmpeg` draws each frame with Chrome and our HTML `renderAt(t, data)` templates, then encodes with ffmpeg. Its code is reused from earlier work (V1a).
  - `hyperframes` draws with HyperFrames and GSAP (`providers/renderer/hyperframes.py`, V3a).
- **Choosing the engine.**
  - A project key, `media: {"renderer": "auto" | "<implementation>"}`, shaped like `outbox` and `code` and accepted with `accept-config`.
  - Until V4, the default is `ffmpeg`. V4 adds the key and states what `auto` chooses.
  - HyperFrames becomes the default only after it passes the shared contract tests (V3c) and the maintainer has approved its blocks' look.
- **Images (VD4).** Each engine has its own provider-owned image, and each image's hash covers only its manifest's file list.
  - The ffmpeg engine's image is the common image: it does the verify step, the cover, the stills, the stage-2 encode and the proxy. So a project that uses HyperFrames builds both images.
  - Adding an `oh:` block rebuilds no image. Admitting an `hf:` block rebuilds the HyperFrames image only.
- **Blocks at render time.** At the start of a render, `blocks/` is copied into the job's work folder. The copy is hashed and mounted read-only. The live checkout is never mounted, since it may change during a render. The blocks' hashes go into `render.json` and into the effect document of section 4, so the approval binds them too.
- **What HyperFrames may never do here.**
  - No HyperFrames command that reaches a network or an account is called: `cloud`, `billing`, `publish`, `lambda`, `tts`, `transcribe --engine heygen`, `skills`, `upgrade`, `update`.
  - Its README's install and upgrade instructions are not followed.
  - Telemetry is off by `HYPERFRAMES_NO_TELEMETRY=1` and `DO_NOT_TRACK=1`, and in any case by the lack of a network.
  - An update of HyperFrames is its own package, and repeats the S2 checks.

### 3. The catalogue of animations: sources with namespaces

A block is named `<source>:<block>`. It has a manifest and one implementation per drawing runtime, each file named after its runtime. Whether one `renderAt` file can serve both runtimes is measured in V3b, after V3a.

- **`oh:`, our own blocks.** `providers/renderer/blocks/<block>/block.json` holds:
  - the name and the kind;
  - typed parameters with their bounds;
  - the band and `may_cross_face`;
  - the licence and the source;
  - `use_when`;
  - sample values and the natural duration.

  The ffmpeg engine's templates become `oh:` blocks (V3b0).
- **`hf:`, HyperFrames' registry, usable when an item passes.**
  - **Tier A, the generic wrapper.** It takes components that declare typed `variables`, need nothing but GSAP, and fit a 9:16 band. Per instance, the wrapper:
    - runs the block in a function scope, prefixes its ids, and scopes its `querySelector` calls to the instance root;
    - applies `@scope (#hf-inst-N)` CSS and drops `html, body` rules;
    - binds its text to our variables and removes CDN tags;
    - maps fonts to the allow-list, and refuses fonts set in script;
    - intercepts `window.__timelines` with a local object, rewrites fixed composition ids, and nests the instance's timeline at the beat's offset in the shared timeline;
    - clips the instance root to its declared band, with `contain: paint` plus `clip-path` or `overflow: clip`.

    The compatibility run checks these admission rules statically, and includes planted-escape cases. A block is refused if it:
    - writes `window.*` other than `__timelines`;
    - uses the top layer (`dialog.showModal`, the popover API, `requestFullscreen`);
    - walks out of its root (`ownerDocument`, `parentNode`, `parentElement`, `closest(`, `getRootNode`).
  - **Tier B, a reviewed port per block,** committed under `oh:` or in an `hf:` override folder. Captions come first: highlight, pill, count-up, testimonial and spring-pop, plus a `list` block.
  - **Out of M1:** full-frame 1920x1080 compositions, and blocks that need three.js, d3 or lottie.
- **Admission is a committed allowlist.** The compatibility run writes it, and a pull request reviews it together with the run's report and contact sheets. Each `hf:` entry carries the pinned commit, the sha256 of each file, the licence, the copyright notice found, and the tier. It also carries fields we write and review ourselves:
  - `use_when`, our own line, never the registry's text;
  - the parameter bounds: a string's length, a number's range, enum options, a `color` mapped to a palette token, and an `image` refused;
  - sample values and the natural duration;
  - `may_cross_face: false`.
- **Licences.**
  - Accepted: Apache-2.0, MIT and OFL, alone or combined, with the copyright line found.
  - Refused: an item whose notice cannot be found, bundled media of any kind (VD11), brand mock-ups, and names that match the validator's harness pattern.
- **Principles 11 and 13, stated.**
  - The allowlist pull request reviews names, hashes, the run's report and the sheets. It does not review every line of third-party code: tier-A code is pinned and gated, not line-reviewed.
  - The safety rests on three things. First, the container: no network, a read-only root, and pixels as the only output. Second, the structural clip. Third, the per-frame checks: the face box tested against the drawn boxes measured after each seek, and fonts read through the browser's DevTools protocol.
  - V3b adds a pixel check as a second guard. It compares each output frame's face-box region with the source frame, within a tolerance.
  - What this saves is a manual port per block. What it gives up is a line-by-line review of tier-A code. The saving is accepted because the three guards above are code, not review.
- **Engine and fallback.** An `hf:` block exists only on `hyperframes`. The fallback works at the preset level: an edit list that names an `hf:` block explicitly is refused on `ffmpeg`, and the refusal names the preset or the `oh:` equivalent.
- **Two blocks for one preset.** The engine's preset map names a default, and the person may override it in the caption review.
- **Choice per video.**
  - Lab-tested skills cite renderer-neutral preset names only (VD9).
  - In M1 the person picks, in the caption review (VD15).
  - In M2 a picking skill (V5) reads the catalogue as an input artifact. It reads our fields only, never registry text.
- **The catalogue file is generated (VD13).**
- **Block parameters** are checked by a renderer-side checker against `block.json` or the allowlist entry (V3b0). `check_script.py` of `mkt-social-copy` checks presets only.
- **What stays closed.**
  - No model or person writes HTML, CSS or script for a render (VD3).
  - No model reads the transcript in M1 (VD17).
  - Recorded media stays loopback only, while the catalogue may cross the LAN socket (VD18).
  - Blocks of a project's own come later, vetted like an imported skill (decision 10).

### 4. The `deliver` effect kind: approving the rendered video

The video is released by a step `Gate` with a new effect kind, `deliver`. The step engine (`runtime/steps.py`) is not edited.

- **A runtime-only word.** `deliver` joins the closed side-effect vocabulary of `contracts/environment.md` and `RUNTIME_ONLY_EFFECTS` of `scripts/validate.py`.
  - No skill may declare it, so no skill is bumped.
  - Its approval group is `approve-effect-deliver`.
  - This is a stated change of the contract. V1b1 makes it, with the tests that hold the word lists.
  - The word `release` was rejected, because an operation and a group of that name already exist.
- **What the gate binds.** The sha256 of the effect document, which carries the video's sha256 and the hashes of the blocks used.
- **Where it can be approved.** On the terminal, and on the page through the loopback socket, only.
  - Never on messaging: a card cannot carry a video, and recorded media stays loopback only (VD18).
  - The kind's `on_cards` always answers false, as the pull-request kind's does, so a messaging grant of the word has no effect.
  - An approval that arrives on the LAN socket is refused.
- **What executing it does.** It marks the approved sha256 as downloadable. The download is an operation after the task is `done`, because a gate is the last step of its kind. In M2 the same effect feeds the publish payload.
- **The way back.** While the task waits at the gate:
  1. `captions-edit` writes `review.json`, and answers the open effect decision with a fixed sentence, under the effect resolution guard.
  2. The engine restarts at the gate's `redo`, which is `remap`, the first step after the caption review.
  3. The video is rendered again, gets a new sha256, and needs a new approval.

  An edit that changes nothing is refused before it answers the decision. Three tests cover this (V1b1): approve, then `done`; edit at the gate, render again, approve again, then `done`; and an edit that changes nothing.

### 5. The order of M1 (VD10)

1. The script is written and reviewed: the existing `short-video` flow, text only, with a preset per beat.
2. The person records.
3. A new video is made from the recording: a request that names the post and the recording's media id, and runs a step task of kind `media`. V1b1 owns this flow and settles its name.
4. The person reviews the captions, and may add an animation (VD15) or pick the block for a preset.
5. The video is rendered and verified.
6. The `deliver` approval (section 4).
7. The download.

A rendered video can go back to step 4, by the way back of section 4. The storyboard before recording (VD14) comes in M2.

### 6. How this delivery is built: an integration branch, with skill packages into main

- **Runtime and provider packages go into the branch `video/integration`:** V1a, V1b1, V1b2, V3a, V3b0, V3b, V3c, V1c and V4. For this delivery, this sets aside the practice of sending new work straight into `main`.
  - Each executor's worktree sets `git config --worktree workbench.baseRef origin/video/integration`.
  - The supervisor regenerates the generated blocks once per batch, and opens a batch pull request into `main` at each milestone, M1 first.
  - The integration branch takes `main` in after each merge into `main` that it needs.
- **Skill packages go straight into `main`, never through the integration branch.**
  - V2 makes Y changes of `mkt-social-copy` and `brand-identity` (VD16). It runs a full test of each on the four lab models, with baselines reused.
  - V5 and V6 follow the same rule.
  - Why: a version file may gain one line per change against its base, and lab evidence counts only for a version line that stays. A skill bumped on the integration branch would have to be bumped again on top of `main`, which voids its lab runs.
- **Code reused from earlier work is re-applied file by file** onto `main`'s step engine, intake and container helper, never merged. A skill's change follows its class.
- **No package of this delivery changes a file of the measurement fingerprint.**
- **Every download needs the maintainer's word, per package:**
  - V1a: Chrome's amd64 archive for the ffmpeg engine's pin (about 124 MB), the Debian snapshot, and the whisper.cpp model;
  - V3a: the HyperFrames image inputs, and Chrome amd64;
  - V3b: the registry files at the pin.

  So does every lab run.

### 7. Decisions 12 and 13

- **Decision 12, retention (accepted 2026-11-07).** The figures of VD8 apply, with delivery standing in for publication, since M1 publishes nothing:
  - the recording and its transcript are deleted 7 days after delivery;
  - the render is deleted 30 days after delivery;
  - an abandoned task's media is deleted 30 days after it was abandoned.

  The HyperFrames intermediate and the proxy are in the same purge. M1 has no "keep" switch.
- **Decision 13, protecting the integration branch (accepted 2026-11-07).**
  - A ruleset on `video/integration` requires the checks `validate` and `tests`. It is a repository setting, so the maintainer sets it.
  - The nightly run stays on `main`. The integration branch gets a manual run (`workflow_dispatch`) at the end of each phase.

### 8. Naming HyperFrames and its maker (principle 1)

- HyperFrames is an open-source renderer, not an AI tool, so it may be named in `providers/`.
- Its maker, HeyGen, sells generative AI video. That name appears in three places only, each something the code must recognise or a licence requires:
  - the copyright line of the NOTICE;
  - the registry's source URL, in the image's fetch step;
  - `--engine heygen`, in the list of refused commands.
- Neither name appears in `skills/`, `agents/`, `shared/`, `contracts/` or `templates/`.
- Registry text, such as an item's description, never enters a provider file or a skill's input: the allowlist carries our own `use_when`.

### 9. The maintainer's decisions of 2026-11-07

Decisions 1 to 11 were accepted as recommended. Decisions 12 and 13 were added after the second review, and accepted the same day.

1. The integration branch is `video/integration`, with a batch pull request into `main` per milestone. The skill packages go into `main` (section 6).
2. Approval is by an effect kind, `deliver`, with no change to the step engine. It is approvable on the terminal and the loopback page only, as a stated change of the vocabulary (section 4).
3. This entry is committed.
4. C2 is fixed by the two-stage encode, with fixed cores as the fallback. Its cost is a disk-backed intermediate of about 4.2 GB for a 5-minute recording.
5. Memory is bounded by the proxy made by code, whose encode is pinned too.
6. `slam` is out of M1.
7. GSAP's no-charge licence is accepted.
8. The transcriber is whisper.cpp (VD5).
9. The maintainer looks at the S2 contact sheets now (C10).
10. Blocks of a project's own come later, vetted like an imported skill.
11. Publishing comes after M1: Reels first, TikTok last. The TikTok publisher needs its own decision.
12. Retention (section 7).
13. The integration branch's ruleset, and the nightly run (section 7).

### 10. The standing rules of the video delivery

Each rule is a decision of this entry. A later change to one is a new entry that names its id.

| Id | Rule |
|---|---|
| VD1 | Engines are swappable behind one renderer-neutral edit list (`edl.json`, `beats.json`), which carries no executable text. Every engine passes the same contract tests, and the approval binds the bytes that come back. A project chooses its engine by a key in `runtime.json`, accepted with `accept-config`. |
| VD2 | `renderer:video` and `transcriber:speech` are runtime roles of `providers/resolve.py`, not classes of `contracts/environment.md`. No skill requires them. |
| VD3 | Code builds the edit list and writes the composition. No model and no person writes HTML, CSS or script that a render runs, on any engine. |
| VD4 | Each engine runs in a provider-owned Docker image: the base pinned by digest, packages and browser pinned per architecture, and the image built only by a command the person starts. The container runs with `--network none --read-only --cap-drop ALL --security-opt no-new-privileges`, as a non-root user, with CPU, memory and process limits, read-only inputs and one writable output folder. The host's own ffmpeg is never used for a render. |
| VD5 | Transcription is local whisper.cpp in a provider-owned CPU image, pinned to a release and a commit, with its model pinned by sha256. A hosted transcriber needs the consent of VD17. |
| VD6 | Fonts and icons come from one pinned set with permissive licences, each stored with its licence file and hash. Every engine draws only the fonts of that allow-list. |
| VD7 | An upload is at most 1 GiB, a recording at most 300 s, and a render at most 30 minutes. The final cut stays within the platform's maximum length. |
| VD8 | Media lives under `<data_dir>/media/<id>/`, outside the project. The recording and its transcript are deleted 7 days after publication or cancellation, and the render 30 days after publication. An abandoned task's media is deleted after a maximum age (decision 12 sets the figures for M1). Code purges in a dispatcher round, with no model. OS backups and the file the person downloads are outside this retention, and the page says so. |
| VD9 | The script names a preset per beat, with typed parameters. Lab-tested skills cite renderer-neutral preset names only. A preset is drawn by a block of the catalogue. |
| VD10 | The person says which animation goes where before recording, in the script, per beat. M1 runs in the order of section 5. |
| VD11 | A block's `image` or `clip` slot is filled only by a file the person uploads for that slot: no download and no generated image. No block brings bundled stock media, 3D models or sound. Sound cues come after the visual work: fixed per preset, and CC0 only. |
| VD12 | The bottom of the caption band is 1560 px, to clear the apps' interface. It is a gate on every engine. |
| VD13 | The catalogue of animations is generated from the `oh:` manifests and the committed `hf:` allowlist, never from an image and never by hand. An entry without a sample fails a test. |
| VD14 | A storyboard before recording: code only, no model, and advisory. It is attached to the script's review, and shows a still per beat over a neutral placeholder with the default face box. It comes in M2. |
| VD15 | "Add an animation" in the caption review is an edit kind of `captions-edit`. It stores a review-only beat in `review.json`, appended to `beats.json` after alignment, and never written into the post file. It offers catalogue blocks, whose parameters the renderer-side checker checks against `block.json` or the allowlist entry. |
| VD16 | The project's theme comes from the closed tokens block that `brand-identity` writes, mapped by code to the renderer's roles. Adding that block is a Y change of `brand-identity`, made in V2. |
| VD17 | A per-project consent key in `runtime.json`, off by default, accepted with `accept-config` and checked by code, is required before a transcript reaches a model or a hosted service. No model reads the transcript in M1. Animations proposed by a model come in V5, behind that key. |
| VD18 | Recorded media and the preview of a review-only beat stay on the loopback socket only, and so does the `deliver` approval. The catalogue and the storyboard may cross the LAN socket, behind the same token and origin checks. |

### Alternatives rejected

- **Grow only our own presets.** The maintainer wants HyperFrames' animations too, without being limited to them.
- **HyperFrames only, without ffmpeg.** The ffmpeg engine's image does the verify step, the stage-2 encode and the proxy for both engines. It is also the fallback, and the default until V4.
- **A model writes the HyperFrames composition,** the tool's native way. That puts text written by a model into a browser that reads the person's recording, which VD3 and principle 11 keep out.
- **Copy registry blocks into the repository as files.** Tier A is fetched at a pinned commit and admitted by the allowlist. Only tier-B ports are committed.
- **A new `approval` stop in the step engine.** It edits the engine, which has one stop word, `review`. An effect kind needs no engine change.
- **The word `release`,** which collides with an existing operation and group.
- **Approval on messaging by grant,** which contradicts VD18.

### Not decided here

- The shape of `block.json`: one implementation file per runtime, or one `renderAt` file for both. Measured in V3b.
- What `auto` chooses (V4).
- The name of the flow that makes a new video (V1b1).
- Where V5's catalogue lives in a project (V5).
- The TikTok publisher (its own decision, V6).
- The look of each block (C10, judged per block).

### Kind and cost

Documentation. No file of the measurement fingerprint changes and no skill changes, so there is no bump and no lab run. The cost is this file. What it buys is that the rules the delivery rests on are on `main`, in one place, with their own ids.

### Verified and not verified

**Verified.** The figures of section 1 come from S2's report, measured by S2 on one arm64 machine. This entry did not measure them again.

**Not verified.**
- Determinism on amd64.
- The two-stage encode on a real-size input, at 4 and 8 cores.
- How many `hf:` items pass tier A under the added rules. The counts so far are static.
- Whether one `renderAt` file can serve both runtimes.
- The GSAP licence text, which decision 7 accepted on S2's summary.
- Chrome's amd64 sha256 for the ffmpeg engine's image (V1a). The HyperFrames image pins its own (V3a-image).
