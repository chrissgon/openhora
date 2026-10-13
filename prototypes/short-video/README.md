# Short video prototype (not the M1 packages)

**This is a prototype. It is not the M1 packages of the short-video plan and is not to be merged as is.**
It exists to prove the core of the decided design end to end on one Mac, to measure it, and to let the maintainer
judge a real rendered video. The plan is `docs/architecture/short-video-posts-2026-10-12.md` (condition C1, amendments
A1 and A2 and their review). The prototype lives outside the core folders; nothing in the core reads it.

Python standard library only, plus `ffmpeg` and `ffprobe` and a Chromium. Nothing is installed or downloaded.

## What it does

```
transcript.json + script.json  --edl.py-->  edit list on the OUTPUT timeline (code only, no model)
source.mp4                     --ffmpeg-->   cut by the kept ranges
edit list + templates/         --Chromium--> transparent PNG frames, renderAt(t, data), over a DevTools pipe
cut + frames + assets          --ffmpeg-->   H.264 + AAC, 1080x1920, faststart, bt709 tagged
```

| File | Role |
|---|---|
| `cdp.py` | Minimal Chrome DevTools Protocol client over `--remote-debugging-pipe` (fds 3 and 4). Sandbox on, every host mapped to not found, the Fetch domain answers every request from memory under one synthetic origin (`https://render.invalid/`) and fails everything else; nothing is ever navigated to `file://`. The browser runs in its own session and is stopped with `killpg`. |
| `presets.json`, `presets.py` | The preset contract (typed parameters: `text`, `icon`, `color`, `image`, `choice`, plus `number`) and its validator: colours are `#RRGGBB` or a palette token, undeclared parameters are refused, text is NFC and refused if it holds a Cc, Cf, Zl or Zp character. |
| `templates/*.html` | Self-contained presets: `caption`, `keyword`, `list`, `number`, `quote`, `cutaway`, `pip`. Each is a pure `renderAt(t, data)`, styled by colour tokens and fonts passed as data, text only through `textContent`. |
| `lint.py` | The determinism lint: no CSS animation or transition, no `Date`, `Math.random`, timers, network, media elements, markup injection, or external `src`/`url()`. |
| `edl.py` | Kept ranges (word gaps over a threshold, leading and trailing silence, a margin, frame grid, optional `silencedetect` confirmation), caption chunks, and beat alignment by deterministic fuzzy matching. `python3 edl.py --help`. |
| `render.py` | The whole pipeline, with timings and the output sha256. `python3 render.py --help`. |
| `media.py` | `ffprobe`, `silencedetect`, helpers. Every ffmpeg call is an argv list; the recording input gets `-f mov -protocol_whitelist file`. |
| `from_whisper.py` | Converts a whisper.cpp JSON to `transcript.json` (unverified, see below). |
| `demo/` | A fully fictional demo: `make_demo.py` builds a synthetic vertical source (test pattern and a tone that is silent between sentences), an image asset, and renders with `transcript.json` and `script.json`. |
| `tests/` | Offline tests. `python3 -m unittest discover -s tests -p 'test_sv_proto_*.py'` (the browser and ffmpeg tests skip with a reason where those are absent). |

## Run the demo

```
python3 demo/make_demo.py --out-dir <scratch folder> --out <scratch>/demo.mp4 -- --jobs 2
```

Generated media never goes into git. The default browser search is the Playwright cache
(`chromium_headless_shell-*`, then `chromium-*`), then `/Applications/Google Chrome.app`; pass `--browser <path>` to choose.
Brand tokens and fonts are passed by flag: `--color accent=#07B6F0 --font display=<file.woff2>:800`.

## Inputs

`transcript.json`:

```json
{"language": "en", "duration": 39.8,
 "words": [{"i": 0, "text": "Hey,", "start": 1.0, "end": 1.28, "segment": 0}]}
```

Words carry their index, start and end seconds and a segment (sentence) index. `script.json` holds `beats` (the spoken
`line`, a `preset`, its typed `params`, a short `label`) and `assets` (slot id to a description, never a path). An image
parameter is a slot id; the file is bound to it by `--asset <slot>=<file.png>`.

## Producing a transcript with whisper.cpp (the maintainer's step)

whisper.cpp is not installed on the machine this was built on, so none of this was run:

```
brew install whisper-cpp
# download a ggml model from the whisper.cpp model list (for example small or medium), then:
ffmpeg -i recording.mp4 -ar 16000 -ac 1 -c:a pcm_s16le audio.wav
whisper-cli -m <model.bin> -f audio.wav -ml 1 -sow -ojf -of whisper-out     # one word per entry
python3 from_whisper.py --whisper-json whisper-out.json --duration <seconds> --out transcript.json
```

`from_whisper.py` assumes the JSON shape the whisper.cpp CLI documents (`transcription[].offsets.from/to` in
milliseconds). The word timestamps' accuracy in the person's language is condition C3 of the plan and is not measured here.

## What differs from the plan

See the report that came with the branch. In short: one browser with several pages instead of a pinned Chrome for Testing
(a Playwright-cached headless shell, version recorded in each render's facts); no asset normalisation beyond a PNG header
check; no font allow-list file (fonts are checked by their bytes); one added parameter type, `number`; templates are linted
but their hashes are only printed, not pinned; no `check` or `install-browser` verb; the renderer is not a provider.
