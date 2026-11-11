## 2026-11-10: the class `stock:media` and Pexels photos and clips (V9b-1; no measurement change, no skill changed, no lab run)

Package V9b-1 of the video plan (cutaway media found by the agent). It adds the runtime-only class `stock:media`, its folder `providers/stock/`, the Pexels
implementation and its source file. Nothing was run against a real library: every test is offline, with a fake network, generated media and a fake key; the
source file is committed with nulls and every verb refuses (exit 3, `source_not_ready`) until the maintainer's approval fills it (V9b STOP 1, STOP 4). The
secret's registry entry and its row of `contracts/secrets.md` are not in this package: they land in the STOP 2 commit, from the values the supervisor hands over.

**The one rule: nothing reaches a video that the workbench cannot show it may reuse.** Every file comes from a library the project turned on, whose licence id is
in the accepted tuple; the URL of every file comes from that library's own API answer; each asset carries its source, item, author and licence.

### Decisions

- **D1. The class** is `stock:media` (variables `STOCK_MEDIA_PROVIDER`, then `STOCK_PROVIDER`), a runtime-only role in `ROLES` like `renderer` and `fetcher`, not in
  `contracts/environment.md` (decision VD2). One implementation per library, `providers/stock/<name>.py`, each with `SERVES = "stock:media"`, `SOURCE`, `VERBS`
  and its source data file `providers/stock/sources/<name>.json`. `providers/stock/_stock.py` is the class; an implementation only says how to call its API and read
  its answer. Adding a library is those two files (and its secret's rows, when it has a key): a test copies `pexels.py` to a new name in a temporary checkout.
- **D2. The licence policy lives in code** (the maintainer's decision of 2026-11-10): `LICENCES_ACCEPTED` is `pexels-license`, `pixabay-content-license`, `cc0-1.0`,
  `pdm-1.0`, `cc-by-4.0`, `cc-by-3.0`; `LICENCES_CREDIT` is the two CC BY ids. Never CC BY-SA, NC, ND, "editorial only" or a licence with no version. A source file with a
  licence outside the tuple is refused at load; a candidate outside it is dropped; a credit licence with no author is dropped. `runtime/media_stock.py` (V9b-3) holds
  the same two tuples, and a test compares them once that file exists (skipped until then). A new licence id is a new decision.
- **D3. The `unverified` tier is a seam, refused by default.** A source file may declare `licence_tier: "unverified"`; its candidates carry the id `unverified`, which is
  not accepted. The provider refuses such a source (`licence_refused`, no request made) unless `--allow-unverified` is given, which the runtime will pass only when the
  project's own switch is on; the per-asset approval is the runtime's (V9b-3). No such source is built; tests plant a synthetic one. Building one is its own package.
- **D4. The network is the provider's own standard-library code on the host, with closed lists** (`providers/stock/_net.py`, the pattern of `runtime/cloud_fetch.py`):
  https on 443, no user info, the host checked against the source file's list before any lookup, every resolved address global (private, loopback, link-local, NAT64,
  6to4, Teredo and IPv4-mapped private ones refused), the connection opened to the address checked, no proxy variable read, no cookie jar, a request that carries the
  key follows no redirect, a download follows at most one, only to a listed host, with `Content-Length` known and under the cap before a byte is read, a body that matches
  its length and the signature of its declared type, and the partial file removed on any failure. The host decodes nothing: the first bytes are compared with the declared
  type's signature and the rest goes to a file and a hash. The reason not to reuse the reference fetcher's proxy container: that container exists because third-party
  code (yt-dlp) opens the sockets; here our own code does, and it holds the key, which a container would have to receive.
- **D5. No verb takes a URL.** `fetch` takes an item id; the provider asks the API for that item and takes the rendition URL from the answer, then checks its host and path
  against the source file. A test shows argparse refuses `--url`.
- **D6. The key** is the secret named in the source file, read only through `providers/secrets/resolver.py`, carried in the API call's header or query, and in no
  download, output, error, cache file, file name or log. A test plants a key and scans every output, error, written file and file name. The cache refuses to write an
  answer that holds the key. The library's own error text is never kept: an exception that could hold a header value (`http.client` quotes it) is replaced by `network`.
- **D7. The source file** is committed with nulls (the V7e pattern): hosts, paths, patterns, licence URL, `terms_read_on`, the secret's name and place, the cache time are
  filled by the maintainer's approval. `terms_read_on` older than 365 days refuses (`terms_stale`).
- **D8. Two stages.** `search` downloads only each candidate's preview picture (at most 1 MiB, JPEG or PNG); `fetch` downloads the full file of a pick. Previews are
  downloaded `--jobs` (3) at a time; one that fails removes the ones already written.
- **D9. Caps** are named constants in `_stock.py` with tests: query 1 to 6 words of ASCII letters; a search 15 s and 1 MiB; one full image 16 MiB and 60 s; one full clip
  120 MiB and 180 s; floors of 1080 x 1350 for an image and 2 s to 60 s for a clip, the clip rendition being the smallest of at least 1080 px on its short side.

- **D10. Review fixes (independent security review, same day).** The source file must be the implementation's own (`providers/stock/sources/<SOURCE>.json`, real
  paths compared, a seam for tests) and the secret it names must equal the implementation's `SECRET` constant (`STOCK_PEXELS_API_KEY`): a caller's file cannot point a key at
  another host or another credential. Every number read from an answer is finite (NaN and infinity in the JSON are a bad answer, output is written with `allow_nan=False`);
  a JSON answer nests at most 32 deep and is read within one deadline; any unexpected exception ends in a fixed refusal code with no exception text; IPv4-compatible IPv6
  (`::/96`), local-use NAT64, NAT64 and every reserved address are refused; `fetch` refuses an answer whose id is not the item asked and applies the floors of a search;
  an item with no positive integer id is dropped; `cache_put` and `cache_get` share one cap (2 MiB of what is written).
- **Residual risk until V9b-3 (stated).** The provider-side `--allow-unverified` flag alone opens the `unverified` tier: nothing in this package can tell who passed it.
  The per-asset approval and the project's own switch are V9b-3's; no `unverified` source exists, so the flag opens nothing today, and V9b-3 must pass the flag only
  when both hold.
- **File names V9b-3 must match.** A clip's files carry a `-clip` suffix (`prev-<source>-<item>-clip.<ext>`, `full-<source>-<item>-clip.mp4`); an image's do not. The runtime
  should read the `preview` and `file` names the answers give, not rebuild them.
- `_net.get_json` has no `secret_in_url` argument any more (it was unused): a URL that holds a key is never put in an error whatever the caller says.

### Alternatives rejected

- The V7 proxy and fetch containers (one more image, and the key inside a container). A library behind `fetcher:video` (a different job: a pinned third-party tool).
- Reading a library's licence text with code: a library item's licence is the library's declaration; the residual risk is stated below.

### What is not verified, and the residual risk

The libraries' answers and files keeping the fields and hosts their pages name (the live leg K1 reads them); which rendition covers 1080 x 1920; whether a media host
redirects, and where. The residual risk of the licence policy: a library item may itself have been uploaded without its owner's right, and a picture may show a person
or a brand the licence does not clear for that use. The person's review and the libraries' takedown processes are the guard, not code.
