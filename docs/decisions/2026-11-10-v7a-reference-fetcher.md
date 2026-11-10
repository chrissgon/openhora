## 2026-11-10: the reference fetcher, a pinned yt-dlp behind a provider (V7a; no measurement change, no skill changed, no lab run)

Package V7a of the video plan (V7: reference videos, decisions 15 and 16). It adds the class `fetcher:video`, its implementation `providers/fetcher/ytdlp.py`,
the image `openhora-fetcher`, the closed network of a fetch and the measured facts. The runtime and the store are V7b; the pin routine is V7c. Nothing was
downloaded, built or run: every test is offline, with a fake docker.

**The one rule: a reference is looked at and measured, never used.** The video is deleted by the runtime right after `measure` (V7b); the renderer's host side
refuses a path inside a reference store (`providers/renderer/_host.py`, `refuse_reference`, called by `stage`, `mount_recording` and `add_mount`); no verb serves
or copies a reference's bytes. What code cannot catch is stated (principle 11): a person who copies a fetched file out of the store by hand before its deletion, by
a copy or a hard link, and records it as their own, is not stopped. The checks read paths, not content (limit L73, written by V7b).

### Decisions

- **D1. The class** is `fetcher:video` (variables `FETCHER_VIDEO_PROVIDER`, then `FETCHER_PROVIDER`), a runtime-only role in `ROLES` like `transcriber` and `renderer`,
  not in `contracts/environment.md`. yt-dlp is adopted, not rebuilt (principle 14; the Unlicense).
- **D2. One image, three containers**: the proxy (the only one with a way out), the fetch (an internal network whose only other member is the proxy) and the measure
  (`--network none`). `providers/_container.py` gains `argv(network=)` (`none`, or a name `openhora-fetch-(in|out)-<12 hex>`; with the default the command is byte for
  byte what it was, a test compares it with a literal and another test shows only files under `providers/fetcher/` pass `network=`), `create_network`,
  `connect_network`, `remove_network`, `in_reference` and a `reap` that also removes labelled networks past their deadline.
- **D3. Two stages**: `meta` (details and subtitles) always; `video` only after the person confirms the length and size `meta` read.
- **D4. The fetch facts live in `shared/references/platforms/<platform>.fetch.json`**, beside the platform's reference and outside what is staged or hashed (design
  rules 2 and 3; principle 12). `scripts/stage_skills.py` stages only `<name>.md` and `<name>.json`, and `eval_status.case_context` hashes only what those return;
  a test proves it on a copy of the tree. `all_references` (the installers, the routing mode of `eval_run.py`) does ship the folder whole, and routing runs write no
  evidence, so no band moves. Two committed files, for the two platforms that have a data file, hold `link.hosts` copied from it and everything else null or empty
  with `checked: "not checked"`; `fetch` refuses them (`platform_not_ready`) until STOP 4 fills them from a live run.
- **D5. A reference is never material.** See above.
- **D6. Retention** is V7b's: the whole video after `measure`; subtitles, details, `proxy.json` and facts 30 days after the reference was added.
- **D7. The pin** is committed with nulls (`tool-pin.json`); `build` and `--check` refuse while it is not filled. A raise is a typed terminal command each time and the
  routine only tells (V7c).
- **D8. Cookies.** `contracts/secrets.md` gains the rule that a browser cookie or a session file is a credential; the fetcher refuses every way to give one. In code:
  the closed argument list (`ALLOWED` in `_inner.py`, a final check refusing any other word that starts with `-`), no mount of a home or browser folder, no environment.

### Departures from the spec text, approved by the supervisor on 2026-11-10

1. **Zoom detection writes `unknown`**, labelled, until a live leg verifies a parser of ffmpeg's `vidstabdetect` transforms. The host's ffmpeg does not list the filter and
   an unchecked parser would publish facts nobody had checked. The facts file's `zoom.method` is `unknown` (frames measured) or `not_fetched`.
2. **The `meta` stage uses the match filter `!is_live` only** and the host checks the duration: a missing duration is reported (`no_duration`, before the `video` stage),
   not silently refused, and a long video still shows its length instead of failing the first fetch. The `video` stage uses the spec's `!is_live & duration <=? <max-seconds>`.

Smaller choices, each stated in the README: `fetch` also answers `platform_not_ready` when a fetch file lists no `fetch_hosts` and no `fetch_suffixes` (a proxy that lists
nothing could only refuse, so no container is started); the `video` stage keeps no second `proxy.json` (the `meta` stage's stays; its counts are in the answer); the
rolling-caption merge keeps the first cue's start; the hook's `question` accepts `?`, the full-width and the Arabic question mark.

### Our own proxy and not tinyproxy (OPEN-6, justified line by line)

What tinyproxy as configured in `evals/container/proxy/` cannot carry: (a) it filters by host name and does not check the resolved address, so a listed name that
resolves to a private or NAT64 address is reached; (b) it has no byte cap for a run; (c) its `Timeout` is a per-connection idle bound with no deadline for a run; (d) it
does not read the ClientHello, so it cannot compare the TLS name with the CONNECT host; (e) its Dockerfile installs an unpinned `apk` package, a new download for each
build. The host allowlist is the one thing it carries; the rest is about 300 lines of standard-library code with offline tests. What the proxy still cannot see, and the
narrow suffixes of STOP 4 guard: an HTTP `Host` header inside the encrypted stream (fronting behind a shared suffix) and an encrypted inner ClientHello.

### Outside V7a's table, with the supervisor's approval

`shared/scripts/tests/test_shared_check_post.py` globbed `shared/references/platforms/*.json` and passed each file to `check_post.load_limits`, which a fetch file is not;
its glob now skips `*.fetch.json` (the same exclusion `scripts/tests/test_platform_references.py` gets in `DATA_FILES`). A search of the repository for other readers of that
folder found none that lists its `*.json` files: the other readers open `<platform>.json` or `<platform>.md` by name, and `runtime/lab.py` lists the `.md` files.

### The cost (principle 13)

- **Saved.** One image for three jobs; no new download tool beyond the pinned file; a host that never parses third-party media or text; no fetch is possible before a person
  approves a platform's values.
- **Given up.** About 300 lines of proxy code to maintain instead of a configured package; a stale yt-dlp fails fetches until the person raises the pin (the failure sentence
  says the tool may be out of date); the live behaviour of the network fence (an internal network, the engine's DNS forwarding) is not proven until L3.

### Not verified (offline package)

The build; that an `--internal` network isolates the fetch container as expected on the Mac's engine; that `python3 -I` runs the tool's file; the tool's minimum Python
against bookworm's; the asset's digest field and the redirect host of a release download; whether bookworm's ffmpeg has `vidstabdetect`; the extractor names, hosts, suffixes,
path patterns, subtitle patterns and the private-video error text of each platform; whether the tool needs an external JavaScript runtime (the pinned tag's documentation is read
at pin time, STOP 1). The supervisor's live legs L1 to L7 (`live-steps`, not committed) settle them, each after the maintainer's yes.

### Generated blocks expected to change (the supervisor regenerates them, `scripts/architecture_tables.py --write`)

The provider-classes table (a new class row and its verbs), the provider-verbs listing and the image-family listing of `docs/architecture/platform/*.md`; the owner table is
not expected to change.
