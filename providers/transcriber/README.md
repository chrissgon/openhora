# Transcriber providers

An implementation of the class `transcriber:speech`: speech to text, with a start and an end for every word, on this machine. The first and only implementation, `whispercpp.py`, runs [whisper.cpp](https://github.com/ggml-org/whisper.cpp) (`whisper-cli`) inside a container. The audio never leaves the computer **as long as the docker daemon is local**: the provider refuses a `DOCKER_HOST` or a docker context that is not a unix socket. No model of any provider sees the audio, and no credential is involved.

`transcriber:speech` is a class the runtime uses, not one a skill may require: on purpose it is not in `contracts/environment.md` (decision D11 of the short-video plan; it goes there the day a skill needs it). The interface of every provider is `providers/CONTRACT.md`; the verbs of this class are in its "Verbs per class" table; `providers/resolve.py` finds the script (`TRANSCRIBER_SPEECH_PROVIDER`, then `TRANSCRIBER_PROVIDER`; with one implementation, none is needed).

| Implementation | Runs | Select with |
|----------------|------|-------------|
| `whispercpp.py` | whisper.cpp `v1.9.5` in a container built from the `Dockerfile` next to it, CPU only | `TRANSCRIBER_SPEECH_PROVIDER=whispercpp` |

The file is `whispercpp.py`, not `whisper_cpp.py`: `providers/resolve.py` takes a name with an underscore for a helper next to the providers (`notion_blocks.py`), not for an implementation.

## Files

| File | What it is |
|------|------------|
| `whispercpp.py` | The provider (standard library only, Python 3.9). Verbs: `--check`, `models`, `build`, `reap`, `transcribe`. |
| `Dockerfile`, `transcribe.sh`, `.dockerignore` | The image's definition. Their hash (`definition_hash`) is the image's tag and a label of it. |
| `models.json` | The pinned models: file, sha256, size, source URL, the DTW preset, the container's memory limit. |
| `transcript.schema.json` | The format of the transcript the `transcribe` verb writes. |
| `tests/` | Offline tests: a fake `docker` on PATH, fictional speech. One live test, skipped unless `OPENHORA_TRANSCRIBER_LIVE=1`. |

## Setup (the person does it, once)

Nothing in the repository downloads, builds or pulls anything by itself. Two things are needed, and each is a command the person starts. Docker (a daemon and the `docker` client) must be installed.

**1. Build the image.** It pulls the pinned base image (`debian` by digest) and clones the pinned whisper.cpp tag from GitHub, compiles `whisper-cli` for a fixed CPU floor of this machine's architecture (below), and installs ffmpeg from a dated Debian snapshot. It takes some minutes and writes `<state>/transcriber/image.json` (the id of the image, which every later run must find unchanged).

```
python3 providers/transcriber/whispercpp.py build --confirmed
```

`build --dry-run` prints the exact `docker build` command and runs nothing. Without `--confirmed` the verb refuses. The image is one architecture (arm64 or amd64, the daemon's): build it again on the other kind of machine, or after the `Dockerfile`, `transcribe.sh` or `.dockerignore` change (then `--check` says so). It is not tied to the CPU that built it.

**2. Put a model in the models folder** (`<state>/transcriber/models/`, or the folder `--models-dir` names). `python3 providers/transcriber/whispercpp.py models` prints the folder, and for each pinned model its file, size, source URL and whether the file is there. The files come from `https://huggingface.co/ggerganov/whisper.cpp` at the revision `models.json` pins; for example:

```
mkdir -p -m 700 ~/.local/state/openhora/transcriber/models
curl -fL -o ~/.local/state/openhora/transcriber/models/ggml-small.bin \
  https://huggingface.co/ggerganov/whisper.cpp/resolve/5359861c739e955e79d9a303bcbc70fb988958b1/ggml-small.bin
python3 providers/transcriber/whispercpp.py --check --model small
```

The check hashes the file and compares it with the sha256 pinned in `models.json`; a file that differs is refused, and so is a model whose pin is `null` (none is, today). `OPENHORA_STATE_DIR` moves the state folder (the rule of `providers/messenger/whatsapp.py`).

## Using it

```
python3 providers/transcriber/whispercpp.py transcribe --in recording.mp4 --model small --language pt --out transcript.json
```

`--in` is any audio or video file ffmpeg opens; the container converts it to 16 kHz mono. `--language` is a code (`pt`, `en`) or `auto`. `--out` is written once, mode 0600, through a temporary file and a rename. The verb prints counts (words, segments, duration, wall time), never the text. `--max-seconds` (default 300, at most 3600) is the longest audio accepted: a longer input exits 2 before whisper starts. `--timeout` (default 1800 s) kills the container. `--threads` (default: the CPUs up to 4) also sets the container's CPU limit, and both are lowered to the daemon's CPU count (`docker info --format {{.NCPU}}`, read once per run), because docker refuses a limit above it; `--memory-mb` overrides the model's limit. `reap` removes what a killed run left behind (below).

### Timestamps

`--timestamps` is the way whisper.cpp times a word. The comparison between them is the short-video plan's check C3; the provider takes no side, and the transcript says which one it used (`facts.timestamps`, `facts.flags`).

| Mode | whisper-cli flags | What a word's times are |
|------|-------------------|-------------------------|
| `word` (default) | `-ojf` | The start of its first token and the end of its last, from whisper's token timestamps. Sentence segments and the gaps between words are kept. |
| `ml1` | `-ojf -ml 1 -sow` | whisper cuts a segment at every word, and a word ends where the next begins: a silence is absorbed by the word before it. Every segment is one word (`facts.segment_unit` is `word`). |
| `dtw` | `-ojf -nfa -dtw <preset>` | The start from dynamic time warping over the attention heads (the model's preset in `models.json`); a word ends where the next in its segment begins. `-nfa` because whisper.cpp switches DTW off while flash attention (on by default) is on. A word with no DTW time fails the run; none is invented. |

Tokens are joined into words by the leading space; punctuation stays with its word; a note such as `[BLANK_AUDIO]`, `[ Silence ]`, `(applause)` or `♪` is not a word (it is counted in `facts.dropped_annotations`, and its segment has `first_word: null`). A word whisper left untimed lies between its neighbours and carries `"estimated": true`.

## The container

Every limit is in code (`container_argv`) and has a test named after it in `tests/test_whispercpp.py`.

| Limit | How |
|-------|-----|
| No network | `--network none` |
| Nothing writable but one folder | `--read-only`; `/tmp` (64 MiB) and `/scratch` (256 MiB) are memory-backed, `noexec`, gone with the container; one work folder, `<state>/transcriber/work/.transcribe-*` (0700, removed afterwards), is mounted read-write |
| The output is not trusted | after the run the provider refuses a work folder with more than 8 entries, anything that is not a regular file, or more than 80 MiB; each file it reads is opened with `O_NOFOLLOW\|O_NONBLOCK`, checked with `fstat` to be a regular file and read up to a limit, so a link or a FIFO the container left is never followed or waited on (the writable mount cannot be capped while the container runs: a full disk is the residual risk) |
| Input and model read-only | `-v <input>:/in/input:ro`, `-v <model>:/models/model.bin:ro` |
| The model is the pinned one | its sha256 is computed and compared with `models.json` before any container starts (a model that is a link, missing, unpinned or different is refused) |
| No privileges | `--cap-drop ALL`, `--security-opt no-new-privileges`, a non-root user (`10001`; on Linux, the caller's ids) |
| No environment | no `-e`, no `--env-file`; the docker client itself gets only `PATH`, `HOME`, `DOCKER_*` and a few locale variables |
| A local daemon | `DOCKER_HOST` (or, when it is unset, the current docker context) must be a `unix://` socket, or the provider refuses with exit 3 |
| Safe mount paths | a `:` or a control character in the input, the models folder, the model path or the work folder is refused with exit 2 before docker is called |
| Bounded | `--pids-limit 256`, `--memory` with `--memory-swap` equal, `--cpus`, the audio's length (`--max-seconds`, checked inside by ffprobe and again by ffmpeg's `-t`), and each tool inside by `timeout` a little under `--timeout` (exit 124) |
| Never fetched at run time | `--pull never`; the image is run by the **id** recorded at build time, so an image rebuilt or retagged by hand is refused |
| A timeout kills it | `--timeout`: the docker client is killed first, then the container is removed by name (`docker rm -f`), also when the provider receives SIGTERM or SIGINT |
| Leftovers are found again | every container carries the labels `org.openhora.transcriber=1` and `org.openhora.transcriber.deadline=<epoch>`. A SIGKILL, a crash or a power cut of the provider can leave the container and a `.transcribe-*` work folder (0700); `reap`, and the start of each `transcribe`, remove containers past their deadline and work folders older than the longest timeout (`--check` changes nothing) |
| Nothing of the speech in a log | whisper's stdout goes to `/dev/null`, its logs are off (`-np`), ffmpeg runs at `-loglevel error`, and a failure shows the last 300 characters of stderr |
| ffmpeg opens only a file | `-protocol_whitelist file,pipe`, so a playlist inside a video cannot reach another host or file |

What this does not claim: the model hash is compared on the host and the file is then mounted by path, so a process that can rewrite the person's own state folder in between could swap it (that process can already read everything else there; the models folder must be `0700` and this user's, which both `--check --model` and `transcribe` enforce); the image is only as trustworthy as the pinned base image, the Debian snapshot and the whisper.cpp commit, which `Dockerfile` pins and the build checks; and a container shares the host's kernel.

## The CPU floor

`GGML_NATIVE` is off: it makes gcc probe the build machine, which inside a virtual machine can miss a feature the code then needs (the first build failed that way on Apple Silicon, fp16 intrinsics without `+fp16`), and it ties the image to that machine. The `Dockerfile` pins a floor per architecture and picks it with `dpkg --print-architecture`; any other architecture fails the build.

| Architecture | cmake flags | Runs on |
|--------------|-------------|---------|
| arm64 | `-DGGML_CPU_ARM_ARCH=armv8.2-a+dotprod+fp16` (becomes `-march=armv8.2-a+dotprod+fp16`) | Apple M1 and later, Graviton 2 and later, Ampere, Raspberry Pi 5 |
| amd64 | `-DGGML_SSE42=ON -DGGML_AVX=ON -DGGML_AVX2=ON -DGGML_FMA=ON -DGGML_F16C=ON -DGGML_BMI2=ON -DGGML_AVX512=OFF` | Intel Haswell (2013) and later, AMD Zen; the AVX2 / FMA / F16C / BMI2 set of x86-64-v3, no AVX-512 |

Both strings are labels of the image (`org.openhora.whisper-cpp.cpu-flags.arm64` and `.amd64`); `--check` prints the one for the image's architecture, and every transcript's facts carry `cpu_arch` and `cpu_flags`. A CPU below the floor stops with an illegal-instruction error at the first run, not with a wrong answer. A faster floor (AVX-512, `i8mm`) is a change of these two lines and a new definition hash.

## Pinned

- whisper.cpp `v1.9.5`, commit `d1be6fde11ac6e0407606b4e42fe72d34add8037` (the tag points to an annotated tag object, `d2a764c648779feb36d44363f212a29b00aad1af`). The build fails if the tag no longer points to that commit. Read from the GitHub API on 2026-10-13; to move it, change the two `ARG` lines in the `Dockerfile` in both stages.
- Base image `debian@sha256:7c7b2c966bc9ee8cedfeef67e0e279108992c77681fa595db4a9d65c06ccc587` (tag `bookworm-20261005-slim`, read from Docker Hub's metadata on 2026-10-13; the tag is a comment, the digest is the pin).
- Debian package snapshot `20261006T000000Z`.
- Models: the sha256 and size of `models.json` are the Git LFS object ids the Hugging Face listing gave for revision `5359861c739e955e79d9a303bcbc70fb988958b1` on 2026-10-13; nothing was downloaded to compute them. The `memory_mb` values are estimates, not measurements.

## Not yet measured

The Dockerfile and the container run were written from whisper.cpp's source at the pinned tag and tested against a fake `docker`. The first real build (arm64, Docker 29, gcc 12) failed with `GGML_NATIVE=ON` (fp16 intrinsics without `+fp16` inside the VM), which is why the CPU floors above exist; the build with the floors has not been run when this was written. Still to check on real hardware: that build, the amd64 floor, that a non-root container user can write the bind-mounted work folder on macOS (Docker Desktop), the memory limits (estimates), and the speed of each model on CPU. The live test (`OPENHORA_TRANSCRIBER_LIVE=1`, the `tiny` model) is the quick check.
