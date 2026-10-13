# Short video prototype (not the M1 packages)

**This is a prototype. It is not the M1 packages of the short-video plan and is not to be merged as is.**
It exists to prove the core of the decided design end to end on one Mac, to measure it, and to let the maintainer
judge a real rendered video. The plan is `docs/architecture/short-video-posts-2026-10-12.md` (condition C1, amendments
A1 and A2 and their review). The prototype lives outside the core folders; nothing in the core reads it.

Python standard library only, plus `ffmpeg` and `ffprobe` and a Chromium. Nothing is installed or downloaded.

## What it does

```
post file (```script block)    --from_post.py--> script beats (refused unless check_script.py passes it)
transcript.json + script beats --edl.py-->  edit list on the OUTPUT timeline (code only, no model)
source.mp4                     --ffmpeg-->   cut by the kept ranges
edit list + templates/         --Chromium--> transparent PNG frames, renderAt(t, data), over a DevTools pipe
cut + frames + assets          --ffmpeg-->   H.264 + AAC, 1080x1920, faststart, bt709 tagged
```

| File | Role |
|---|---|
| `cdp.py` | Minimal Chrome DevTools Protocol client over `--remote-debugging-pipe` (fds 3 and 4). Sandbox on, every host mapped to not found, the Fetch domain answers every request from memory under one synthetic origin (`https://render.invalid/`) and fails everything else; nothing is ever navigated to `file://`. The browser runs in its own session and is stopped with `killpg`. |
| `from_post.py` | Reads the ```script block of a post file in the shipped format (`skills/mkt-social-copy`), by importing the real `check_script.py` and refusing a post that does not pass it, and maps each beat to the prototype's presets. Asset fallbacks are reported. `python3 from_post.py --help`. |
| `presets.json`, `presets.py` | The preset contract, reconciled with `shared/references/video-presets.json` (typed parameters: `text`, `icon`, `color`, `image`, `choice`, plus `figure`) and its validator: colours are `#RRGGBB` or a palette token, undeclared parameters are refused, text is NFC and refused if it holds a Cc, Cf, Zl or Zp character. |
| `templates/*.html` | Self-contained presets: `caption`, `keyword`, `list`, `number`, `quote`, `cutaway`, `pip`. Each is a pure `renderAt(t, data)`, styled by colour tokens and fonts passed as data, text only through `textContent`. |
| `lint.py` | The determinism lint: no CSS animation or transition, no `Date`, `Math.random`, timers, network, media elements, markup injection, or external `src`/`url()`. |
| `edl.py` | Kept ranges (word gaps over a threshold, leading and trailing silence, a margin, frame grid, optional `silencedetect` confirmation), caption chunks, and beat alignment by deterministic fuzzy matching. `python3 edl.py --help`. |
| `render.py` | The whole pipeline, with timings and the output sha256. `--post <post file>` or `--script <script.json>` (the demo path). `python3 render.py --help`. |
| `media.py` | `ffprobe`, `silencedetect`, helpers. Every ffmpeg call is an argv list; the recording input gets `-f mov -protocol_whitelist file`. |
| `from_whisper.py` | Converts a whisper.cpp JSON to `transcript.json` (unverified, see below). |
| `demo/` | A fully fictional demo: `make_demo.py` builds a synthetic vertical source (test pattern and a tone that is silent between sentences), an image asset, and renders with `transcript.json` and `script.json`, or with `--post` through `post.md` (the shipped format). |
| `tests/` | Offline tests. `python3 -m unittest discover -s tests -p 'test_sv_proto_*.py'` (the browser and ffmpeg tests skip with a reason where those are absent). |

## Run the demo

```
python3 demo/make_demo.py --out-dir <scratch folder> --out <scratch>/demo.mp4 -- --jobs 2          # script.json
python3 demo/make_demo.py --out-dir <scratch folder> --out <scratch>/demo.mp4 --post -- --jobs 2    # demo/post.md
```

Generated media never goes into git. The default browser search is the Playwright cache
(`chromium_headless_shell-*`, then `chromium-*`), then `/Applications/Google Chrome.app`; pass `--browser <path>` to choose.
Brand tokens and fonts are passed by flag: `--color accent=#07B6F0 --font display=<file.woff2>:800`.

## What the post file gives, and what the person gives

The beats come from the post file's ```script block, as `mkt-social-copy` writes it (`skills/mkt-social-copy/references/video-script.md`,
`shared/references/video-presets.md`). A beat is `beat: N`, `line:` (the words said, used to find the beat in the transcript),
optionally `on-screen:` (the preset's main text) and `preset:` (`keyword`, `list`, `number`, `quote`, `cutaway`, `pip`) and that
preset's other parameters. A beat with no preset is caption only: captions are always on, nothing else is drawn.

| Preset | `on-screen` is | Other parameters |
|---|---|---|
| keyword | `text` (24 characters) | `icon`, `color` |
| list | the items, one line, ` | ` between them (1 to 4, 30 characters each); no title | `icon`, `color` |
| number | `label` (40); the figure is `value` (digits with `.` or `,`) | `color` |
| quote | `text` (120) | `author`, `color` |
| cutaway | `label`, optional | `asset`, `fit` (cover or contain) |
| pip | `label`, optional | `asset`, `position` (top or bottom) |

`asset` is a description in words. The file is the person's: upload it after recording and pass `--asset <beat number>=<file>`
(PNG or JPEG only for now), for example `--asset 7=dashboard.png`. A cutaway or pip beat with no file falls back to a `keyword` with
its label (when the label fits 24 characters), or to caption only, and the fallback is printed and returned in the render summary
(`post.beats`). A file given for a beat that has no asset slot is an error. The prototype does not take video clips yet.

`from_post.py` runs the same check as `check_script.py` (imported from the repository, not copied) and refuses a post file it does not
pass, printing the beat, the field and a closed code, never the text. A post whose `Format:` line is not `reel` or `video` is refused.
`python3 from_post.py --post <post file> [--asset N=file]` prints the beat table and the resulting script, useful to look at before a render.

`transcript.json`:

```json
{"language": "en", "duration": 39.8,
 "words": [{"i": 0, "text": "Hey,", "start": 1.0, "end": 1.28, "segment": 0}]}
```

Words carry their index, start and end seconds and a segment (sentence) index. The older `script.json` (the demo path, `--script`)
holds `beats` (the spoken `line`, a `preset`, its typed `params`, a short `label`) and `assets` (slot id to a description); there an
image parameter is a slot id and the key of `--asset` is the slot id.

## Running it on a real recording (the maintainer's steps)

whisper.cpp is not installed on the machine this was built on and nothing below was run; the transcript step is unverified until
the first real recording, and the accuracy of word timestamps in Brazilian Portuguese is condition C3 of the plan.

1. Send the recording to the Mac with AirDrop (it lands in `~/Downloads`). Keep the original; the render never changes it.
2. Install whisper.cpp: `brew install whisper-cpp` (the command is `whisper-cli`).
3. Get a model yourself (this prototype downloads nothing). Recommended for Brazilian Portuguese: **`ggml-large-v3-turbo.bin`**
   (about 1.6 GB, multilingual). Official location: the whisper.cpp model list on Hugging Face,
   `https://huggingface.co/ggerganov/whisper.cpp/tree/main` (the same files `models/download-ggml-model.sh` in the whisper.cpp
   repository fetches). If it is too slow, `ggml-medium.bin` (about 1.5 GB) is the fallback. Do not use a file ending in `.en`.
   Put it somewhere stable, for example `~/models/whisper/`.
4. Make the audio and the word-level JSON, then the transcript:

```
REC=~/Downloads/recording.mov
WORK=~/video-work; mkdir -p $WORK
ffmpeg -i "$REC" -ar 16000 -ac 1 -c:a pcm_s16le $WORK/audio.wav
whisper-cli -m ~/models/whisper/ggml-large-v3-turbo.bin -f $WORK/audio.wav -l pt -ml 1 -sow -ojf -of $WORK/whisper-out
DUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$REC")
python3 prototypes/short-video/from_whisper.py --whisper-json $WORK/whisper-out.json --duration $DUR --out $WORK/transcript.json
```

   `-l pt` fixes the language (Brazilian Portuguese is `pt`), `-ml 1 -sow` gives one word per entry and `-ojf` writes
   `whisper-out.json` with the offsets `from_whisper.py` reads. Open `transcript.json` and read it against what you said before
   rendering: a word that is wrong still renders, as a wrong caption.

5. Render with the post file and the brand of that project (the colours and fonts of the earlier brand render):

```
P=/Users/chrissgon/projects/chrissgon-posts
python3 prototypes/short-video/render.py --video "$REC" --transcript $WORK/transcript.json \
  --post $P/docs/marketing/content/<post>.md \
  --color bg=#000000 --color text=#FFFFFF --color muted=#9CA3AF --color accent=#07B6F0 \
  --color chip_fill=#011B24 --color chip_text=#6BC9F5 --color chip_border=#07B6F0 \
  --font display=$P/docs/brand/pieces/fonts/inter-800.woff2:800 \
  --font text=$P/docs/brand/pieces/fonts/inter-500.woff2:500 \
  --font mono=$P/docs/brand/pieces/fonts/jbm-500.woff2:500 \
  --silence-detect --jobs 3 --out $WORK/out.mp4 --workdir $WORK/render
```

   Add `--asset <beat>=<file.png>` once for each cutaway or pip beat the post has. The summary printed at the end lists
   `unmatched_beats` (a beat whose line was not found in the transcript gets no overlay) and `post.beats` (every fallback).
   `$WORK/render/edl.json` holds where every beat landed; `script.from_post.json` holds what was read from the post file.
   Generated media never goes into git.

## What differs from the plan

See the report that came with the branch. In short: one browser with several pages instead of a pinned Chrome for Testing
(a Playwright-cached headless shell, version recorded in each render's facts); no asset normalisation beyond a PNG header
check; no font allow-list file (fonts are checked by their bytes); one added parameter type, `number`; templates are linted
but their hashes are only printed, not pinned; no `check` or `install-browser` verb; the renderer is not a provider.
