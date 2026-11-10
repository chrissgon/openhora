## 2026-11-10: impersonation wheels and a video with no stated length (V7e; no measurement change, no skill changed, no lab run)

Package V7e of the video plan closes the two gaps the first live run of the reference fetcher found, recorded in the decision file of V7a
(`docs/decisions/2026-11-10-v7a-reference-fetcher.md`, which is never edited): one platform's extractor asks for browser impersonation and the
dependency was not in the image, and another platform's details carry no duration, so the video stage refused with `no_duration`. The maintainer's
decisions of 2026-11-10: "Liberar" for the pinned `curl_cffi`; and for the length, the recommendation accepted (the video stage runs without a known
duration, only under the byte cap the proxy already enforces; the length is measured with ffprobe inside the container after the download; over
`max-seconds` the file is deleted and the fetch refused; a missing duration never lifts the byte cap or the time cap). This answers the open design
question of line 116 of the V7a file. Nothing was built or fetched by this package: no docker, no download, no network call.

**The rule of the package: nothing it adds widens what a fetch may reach, spend or keep.**

### Decisions

- **D1. `curl_cffi` comes as pinned wheels, unpacked by our script, never by pip.** `providers/fetcher/wheel-pin.json` (in the manifest and the
  `.dockerignore`, so the definition hash covers it) is read inside the build by `_fetch_tool.py wheels`. It is a file of its own and not a key of
  `tool-pin.json`: V7c's local raise copies every key of the committed pin and checks three, so a key there would let a stale raise carry an old wheel
  pin into the effective pin.
- **D2. Departure from the spec: its dependencies are wheels too, not Debian packages.** The spec proposed `python3-cffi-backend` and `python3-certifi`
  from the pinned snapshot. STOP A showed that `curl_cffi` 0.17.0, the tool's own pin, requires `cffi>=2.1.1` and `certifi>=2026.10.19`, newer than
  the snapshot's `python3-cffi-backend` 1.15.1 and `python3-certifi` 2022.9.24 (every `curl_cffi` from 0.10 on needs `certifi>=2024.2.2`; from 0.15
  `cffi>=2.0`). The spec's own fallback for a dependency bookworm lacks was a wheel entry of the same shape. The supervisor decided, and the maintainer
  approved ("Sim, aprovo os 4", 2026-11-10), to adopt the tool's own tested release set as four wheel packages: `curl_cffi` and `cffi` per
  architecture (amd64, arm64; abi3 and cp311, since the image's python is 3.11) and `certifi` and `pycparser`, pure (arch `any`, file tag `py3-none-any`).
  The apt line is unchanged. The checker therefore accepts a pure wheel (arch `any`, platform tag `any`) beside the manylinux ones, accepts the tags
  `cp3<n>-abi3` (n up to 11), `cp311-cp311` and `py3-none`, and requires, per package, either one `any` entry or both architectures. A second small
  departure: the `cffi` wheel holds its C module `_cffi_backend` as a top-level file beside its folder (not verified: from the usual layout of that
  wheel, read at STOP B), so `_fetch_tool.py` allows that one name for that one package besides `<name>/`, `<name>-<version>.dist-info/` and
  `<name>.libs/`; any other top-level name is refused.
- **D3. The image proves the pairing at build.** `selfcheck --expect-wheels` imports `curl_cffi` under `python3 -I`, requires its version to equal the
  pin and requires the tool to list at least one impersonation target backed by `curl_cffi`; a failure is `build_failed`. A later raise of the tool that
  no longer accepts the pinned `curl_cffi` fails its build loudly, which is why the V7c routine does not watch `curl_cffi`.
- **D4. The length is read from the file in every video fetch**, inside the fetch container right after the tool ends (`_fetcher_inner.py`
  `probe_seconds`, ffprobe through `_measure.probe_duration`). Over `max_seconds` the container deletes the file and writes `too_long`; the host reads
  the closed result (now `{ok, code, exit, seconds}`, `seconds` null or a finite number above 0 and at most 86400) and refuses before moving anything.
  With no length from the file the platform's stated length stands; with neither, nothing is kept (`no_duration`). A stated length over the bound is
  still refused before any container. The tool's own timeout in the video stage is shortened by 30 s so the probe fits inside the container's time cap.
- **D5. A missing duration changes no cap.** `max_bytes`, the proxy's cap (`max_bytes x 1.10`), `--max-filesize` and the container's timeout are computed
  from the same inputs as before; the duration is not one of them. `test_fetcher_length.py` records the proxy and fetch commands for a stated length
  and for none and requires them equal word for word, the run token masked.
- **D6. The V7c routine does not watch `curl_cffi`** (principle 13): it would add a second host (PyPI), a second raise path and a second local pin for a
  package that only has to match the tool's accepted range, and D3 turns a mismatch into a failed build at the next raise. Cost: a newer `curl_cffi` with a
  fix is noticed only when a fetch fails; the README's raise section says to read the new release's accepted range before a raise.

Alternatives rejected (principle 14): the tool's standalone Linux builds, which bundle `curl_cffi` (not verified): a self-extracting executable unpacks
native libraries at each start and the container's `/tmp` and `/scratch` are `noexec`, and it would replace the one architecture-independent asset by two;
`pip install --require-hashes --no-index`: a test forbids pip in the image, and installing `python3-pip` adds a package set to unpack what a `zipfile` loop
unpacks, while the wheel's sha256 is pinned.

### The runtime

`runtime/ops_references.py`: a record with a null duration is no longer refused before a fetch. The preview keeps its keys, `duration` is null and the
warning says the fetch is bounded by the size bound and its time limit and that the length is measured from the file. After a video fetch the measured
length is written into the record when it was null, and a measured length over `references.VIDEO_SECONDS_MAX` deletes the video and refuses `too_long`.
`REFUSALS["no_duration"]` now reads "the length of this video is not known: neither the platform nor the fetched file gave one, and nothing was kept". The
test that asserted `no_duration` before any container (`test_fetcher_link.py`, and the runtime test of the same name) changed by the maintainer's decision
of 2026-11-10 and says so.

### What code cannot catch

The length is measured inside the fetch container, which parses third-party media (as the tool's own ffmpeg merge already does there). A container
subverted by a hostile file could report a false `seconds`; the bounds are then the byte cap, enforced by the separate proxy container, and the time cap,
enforced by the host; and V7b deletes the video right after `measure` (limit L73).

### STOP A, the wheel pin (read by the supervisor; no download)

Recorded below by counts and short digests (the first and last six hex of each sha256); the full values are in `providers/fetcher/wheel-pin.json`.

Read on 2026-11-10 from PyPI's JSON API (no download, no executable). The tool's tag 2026.10.26 accepts `curl-cffi>=0.5.10,!=0.6.*,!=0.7.*,!=0.8.*,!=0.9.*,<0.18`
and its own release pins are certifi 2026.10.23, cffi 2.1.1, curl-cffi 0.17.0, pycparser 3.11, which the pin adopts (D2). Every version is at least 14 days old
on the read date (`curl_cffi` 15). The maintainer approved the four packages ("Sim, aprovo os 4", answering "Aprova os 4 pacotes fixados do V7e, em vez de 1?").

| package | version | arch | licence | size | sha256 (first 6 ... last 6) |
|---|---|---|---|---|---|
| curl_cffi | 0.17.0 | amd64 | MIT | 14053278 | af0782 ... 9f4e24 |
| curl_cffi | 0.17.0 | arm64 | MIT | 13438302 | aa91d2 ... 39506e |
| cffi | 2.1.1 | amd64 | MIT-0 | 217807 | 34e261 ... 364632 |
| cffi | 2.1.1 | arm64 | MIT-0 | 218716 | 3311ed ... f95813 |
| certifi | 2026.10.23 | any | MPL-2.0 | 135082 | e9b54d ... 2f61d1 |
| pycparser | 3.11 | any | BSD-3-Clause | 51178 | 51d5a8 ... 29cd80 |

Hosts: `download_hosts` is `files.pythonhosted.org`; `redirect_hosts` is empty (headers only, on the `curl_cffi` arm64 wheel: HTTP 200, no `Location`; the
other five are assumed to answer the same, which the build shows). The `cffi` wheels are cp311 because bookworm's python is 3.11. The amd64 digests are
checked only by an amd64 build (not in this package).

### Verified offline

The unpacker against a loopback server and wheels built in the tests (both machines, null fields, size, sha256, hosts, redirects, each refused member, the
member and size limits, modes); the pin check, each rule broken once; build, `--check` and `--dry-run` refusing a null or malformed pin before any docker
call; `pin-show`; the video stage's caps, `too_long` and `no_duration` with nothing kept; the result's closed shape; the self check with fake import and
target output; ffprobe on a generated file where the machine has one; a browser-shaped ClientHello through `parse_sni` and the tunnel; the runtime's
preview, record update and second guard. **Not verified** (each is read at a STOP or a live leg, never assumed): that the pinned wheels carry the tags the
checker expects and bundle their native libraries; that `site.getsitepackages()` lists a `/usr/local/lib/` folder on the image's python under `-I`; the
output form of `--list-impersonate-targets`; that the tool asks for impersonation by itself in the extractor that needs it; that the proxy accepts the
impersonated ClientHello (one record, at most 16 KiB; the tunnel is proved only on a synthetic hello); that ffprobe reads a length from every merged file
the video stage gives; the fetch-file values of both platforms (STOP C and D, not part of this commit).
