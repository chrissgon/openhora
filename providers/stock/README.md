# providers/stock: the class `stock:media`

Libraries of pictures and clips whose licence allows reuse in a published video, searched by words through their API. A runtime-only class, like
`renderer:video` and `fetcher:video`: no skill requires it and `contracts/environment.md` does not list it. One implementation per library
(`providers/stock/<name>.py`), each with its source data file (`providers/stock/sources/<name>.json`). Package V9b-1 builds the class and Pexels; package V9b-1c
adds Openverse and the open-web source `web`; Pixabay is V9b-1b, later. Nothing here has run against a real library or a real web page yet: the tests use a fake
network, generated media and a fake key.

```
providers/stock/
  _stock.py           the class: licence tuple, source file checks, caps, query rule, answer cache, secret lookup, candidate schema, the verbs
  _net.py             the closed-host fetch: host list, global addresses, the address checked is the address connected, one redirect to a listed host
  pexels.py           how to call Pexels and read its answer (SERVES = "stock:media")
  openverse.py        how to call Openverse (keyless, per-item licences) and read its answer
  web.py              the open-web source: fetch the file at a URL a model wrote, through `_net.fetch_open`, into quarantine (the one place such a URL is opened)
  sources/<name>.json the source data, committed with nulls: every value is filled by the maintainer's approval (web.json is five fixed fields)
  tests/              offline tests (a fake opener, `.example` hosts)
```

## The verbs

JSON on stdout, diagnostics on stderr, exit codes per `providers/CONTRACT.md` (0 ok, 1 failed, 2 usage, 3 not configured). A refusal prints
`{"ok": false, "code": <closed word>, "fields": [...]}`. No verb prints a key, a URL or a query.

- `--check --source-file F --today D`: the source file ready and its key found, printed as where it was found, never the value.
- `search --source-file F --today D --kind image|clip --query Q [--count N] [--jobs J] --out DIR`: one API call (or the cache), portrait orientation,
  then each candidate's preview picture into `DIR/prev-<source>-<item>[-clip].<jpg|png>`. Answers `candidates` (`item`, `kind`, `width`, `height`,
  `seconds`, `author`, `title`, `licence`, `page`, `preview`, `preview_sha256`), `dropped` (`too_small`, `licence`, `host`, `too_long`), `requests` (API
  calls; 0 when cached), `cached`, `previews`.
- `fetch --source-file F --today D --kind image|clip --item ID --max-bytes B --out DIR`: one API call for the item (or the cache), then one download
  of the rendition URL **that answer names**, into `DIR/full-<source>-<item>[-clip].<jpg|png|mp4>` (0600). **No verb takes a URL**: a URL never comes
  from a person or a model. Answers `file`, `bytes`, `sha256`, `licence`, `author`, `title`, `page`, `seconds`.
- `--allow-unverified` on `search` and `fetch`: the caller says the project turned the `unverified` tier on. Without it a source of that tier is refused
  (`licence_refused`) and no request is made.

`DIR` is a real folder of this user, mode 0700, not a link, and not inside a reference store (a tree that holds the file `.openhora-reference`).

Closed refusal codes: `source_not_ready` (3), `terms_stale` (3), `no_key` (3), `query_refused` (2), `out_refused` (2), `host_refused`, `address_refused`,
`redirect_refused`, `status`, `no_length`, `too_large`, `type_refused`, `licence_refused`, `rate_limited` (HTTP 429: no retry), `network` (1).

## Caps and the query rule (named constants in `_stock.py`, each with a test)

| What | Cap |
|---|---|
| query | `[A-Za-z][A-Za-z' -]{1,59}`, 1 to 6 words, ASCII letters only; no `@`, `.`, `/`, `:` or digit |
| one search | 15 s, answer at most 1 MiB, at most 6 candidates; previews at most 1 MiB each |
| one full image | 16 MiB, 60 s |
| one full clip | 120 MiB, 180 s; the rendition chosen is the smallest of at least 1080 px on its short side |
| floors | image at least 1080 x 1350; clip from 2 s to 60 s |

The per-video caps (6 slots, 36 previews, 400 MiB, 40 API calls) belong to the runtime, which holds them.

## The licence rule

Accepted: a library's own licence (`pexels-license`, `pixabay-content-license`), `cc0-1.0`, `pdm-1.0`, `cc-by-4.0` and `cc-by-3.0`
(`LICENCES_ACCEPTED`; the two that ask for credit are `LICENCES_CREDIT`, and an item with one of them and no author is dropped). Never CC BY-SA, NC, ND,
"editorial only", a licence with no version. A candidate outside the tuple is dropped here and again by the runtime; a source file whose licence is
outside it is refused at load (`licence_refused`). A source file declares a `licence_tier`:

- `library`: one licence for every item, named in the file;
- `per-item`: each item states its own; the implementation maps it through the file's `licences` table and drops an item it cannot map;
- `unverified`: no licence the code can read. `web` is the one source of this tier: the provider refuses it without `--allow-unverified`, and the runtime
  (V9b-3) passes that only with the project's own switch and admits an asset only with a separate approval of that asset, bound to its bytes.

## The source file

The source file must be the implementation's own, `providers/stock/sources/<SOURCE>.json` (real paths compared), and the secret it names must be the one the
implementation's `SECRET` constant gives: a file anywhere else, or one that names another credential, is refused (`source_not_ready`, `source_file` or `secret`).

Committed with nulls (`sources/pexels.json`), filled by the maintainer's approval (hosts, paths, patterns, licence URL, the date the terms were read,
the secret's name and where it travels, the cache time). Every verb but `--help` refuses (exit 3, `source_not_ready`, naming the fields) while a field its
tier and `kinds` need is null or empty, and refuses with `terms_stale` once `terms_read_on` is more than 365 days before `--today` (`date +%F`).
Hosts are exact names; `media_hosts` and `redirect_hosts` are the closed lists a download may open; patterns are regular expressions of at most 200
characters, matched against the whole path of the rendition URL. `secret_in` is `header`, `query` or `none`.

## The network

The provider's own standard-library code does the network, on the host, with closed lists (decision D4): https on 443 only, no user info, the host
checked against the file's list before any lookup, every address it resolves to global (private, loopback, link-local, NAT64, 6to4, Teredo and
IPv4-mapped private ones are refused), the connection opened to the address that was checked, no proxy variable read, no cookie jar. A request that
carries a key (the API) follows no redirect; a download follows at most one, to a host of `redirect_hosts`, and carries no key. A download's
`Content-Length` is known and under the cap before a byte is read, the body is exactly that long and begins with the signature of its declared type,
and the partial file is removed on any failure. Nothing here decodes a downloaded file: decoding is the renderer's, in a container with no network.

## The key

The secret named in the source file, read through `providers/secrets/resolver.py` (`contracts/secrets.md`); a header or query value it cannot carry is
`no_key`. It goes in the API call's header or query and nowhere else: not in a download, an output, an error, the cache, a file or a log. The cache
(`<state>/stock/cache/<source>/`, 0700 and 0600) holds the API answer for the file's `cache_seconds` and is used before any request; it is never
written with an answer that holds the key.

## How to add a source

1. `providers/stock/<name>.py` with the lines `SERVES = "stock:media"`, `SOURCE = "<name>"` and `VERBS = ("search", "fetch")`, and `auth`,
   `search_request`, `item_request`, `read_search`, `read_item` (copy `pexels.py`: it is the whole of how to call one API and read its answer; set `SECRET` to the one key it reads).
2. `providers/stock/sources/<name>.json`, committed with nulls; the values come from the maintainer's approval of the library's terms.
3. If the library needs a key, its `REGISTRY` entry in `providers/secrets/resolver.py` and its row of `contracts/secrets.md`, in the same change.
4. No skill, runtime or renderer file changes: the runtime lists sources from `providers/resolve.py` and the source files. A test copies `pexels.py`
   to a new name in a temporary checkout to prove it.

Two exceptions are not files-only additions: a source whose licence id is not in `LICENCES_ACCEPTED` is a **licence policy change** (both tuples, a
decision file, the maintainer's word), and a source of the `unverified` tier is its own package with its own terms (`web`, V9b-1c).

Select the implementation with `STOCK_MEDIA_PROVIDER`, then `STOCK_PROVIDER`; the runtime names each source a project turned on.

## The sources

| Source | Tier | Key | Kinds | Notes |
|---|---|---|---|---|
| `pexels` | `library` (`pexels-license`) | `STOCK_PEXELS_API_KEY` | image, clip | optional; stays off while the library issues no keys |
| `openverse` | `per-item` | none | image | each item's own licence and version, mapped through the file's `licences` table; any pair not in the table is dropped |
| `web` | `unverified` | none | image, clip | no search here: the search is a model's; this file only fetches a URL it wrote (below) |

`openverse.json` is committed with nulls (`licence_tier` `per-item`, `secret_in` `none` and `kinds` `["image"]` are its fixed fields). The `licences` table maps
`"<licence> <version>"` (the item's `license` in lower case, a space, its `license_version`) to one of our ids; an item with no version is keyed by its name alone,
which no table maps, so a `by` with no version, `by-sa`, `by-nc` and `by-nd` never pass. The class refuses a table that maps to an id outside `LICENCES_ACCEPTED`.
An item whose preview or file host is not in `media_hosts` is dropped (`host`). The implementation names no secret (`SECRET = ""`): a source file that names one is
refused (`source_not_ready`, `secret`), so no key is read, sent or kept. The search asks the library for licences that allow commercial use and modification
(`license_type`), as a first filter only: the table is the rule.

## The open web (`web.py`)

`web.py` is the one place in the workbench where **a URL written by a model is opened**. The provider never searches: the search is the contained web-search run of
V9b-3b, which returns URLs and text; the page URL of a candidate is never fetched, it is kept as text. Every other provider takes an item id and reads the file's
URL from its library's own answer.

```
web.py --source-file F --today D preview|fetch --kind image|clip --url U --out DIR --max-bytes B [--refuse-host H]... [--allow-host H]... --allow-unverified
```

Answers `{"ok", "file", "bytes", "sha256", "type", "host"}` (`file` is a name inside `DIR`; the URL is never printed). `preview` is always an image (PNG or JPEG, 4 MiB,
30 s: the thumbnail of a clip is an image; a clip with no thumbnail has no preview). `fetch` is the file: an image (16 MiB, 60 s) or a clip (MP4 or WebM, 120 MiB,
180 s). `--max-bytes` only lowers a cap. The checks live in `_net.fetch_open` and each has a test (`tests/test_stock_web.py`):

1. **The URL**: a text of at most 2048 printable ASCII characters (no space, no backslash), `https`, no user info, no port or 443, a host that is a name (no IP
   literal, no trailing dot), not under a refused host (`--refuse-host`, the name and its sub-domains), under an allowed host when `--allow-host` is given. The two lists
   are the person's, empty by default; a refused host wins over an allowed one.
2. **Every resolved address is global** (private, reserved, loopback, link-local, multicast, `::/96`, NAT64, 6to4 and IPv4-mapped private are refused), and the
   connection opens the address checked, hop by hop.
3. **At most two redirects**, each `Location` joined and checked by 1 and 2 again; a redirect to `http`, a port, user info, a literal or a refused host is `redirect_refused`.
4. **Headers sent**: `Host`, a fixed `User-Agent`, `Accept: image/png, image/jpeg, video/mp4, video/webm` and `Accept-Encoding: identity`. Never a cookie,
   `Authorization` or `Referer`; a `Set-Cookie` is never read.
5. **Only a 200.** A `Content-Length` over the cap is `too_large` before a byte is read; the body is counted while it is read, and a server that sends no length is read up
   to the cap and refused one byte over.
6. **The type is read from the first 16 bytes** (PNG, JPEG, MP4 `ftyp` at offset 4, WebM) before a byte is written, whatever `Content-Type` said. HTML, WebP, GIF, SVG and
   anything else is `type_refused` and nothing is kept. Nothing is decoded here.
7. **The file** is written 0600 under a temporary name in `DIR`, then renamed `q-<first 12 hex of the sha256>.<png|jpg|mp4|webm>`; any failure removes it. `DIR` must be a
   real folder of this user, mode 0700, named `quarantine` inside a folder named `stock` (`<data dir>/media/<task>/stock/quarantine`), and not inside a reference store.
8. **Diagnostics** print the code and the host that was reached (a validated host name), never a URL, a path or a query; a usage error prints a fixed text. The
   `unverified` tier is refused without `--allow-unverified` (`licence_refused`, no request): the runtime passes it only when the project's own switch is on.

The source file `sources/web.json` holds five fixed fields and nothing a maintainer fills (no host, no pattern, no terms date: the open web has no terms to read, and its
risk is carried by the copyright warning and the per-asset approval of V9b-3). `read_source` accepts exactly these five keys as an open-web source.

## What is not verified

That a library's answers and files keep the fields and hosts its documentation names (the first live run, K1, reads them); Openverse's anonymous access, its limits,
its parameter and field names (`license_type`, `page_size`, `results`, `license`, `license_version`, `creator`, `url`, `thumbnail`, `foreign_landing_url`) and which
upstream hosts its files come from (K1, STOP 1 and STOP 4); whether a real web server's redirects, lengths and types behave as the fake network's do (K1); which rendition of a
photo or a clip covers 1080 x 1920; whether a redirect of a media host goes to a listed host; whether downloads count against a library's limits; the
Python 3.9 run (the test suite parses every file as 3.9 and the code uses nothing newer, but no 3.9 interpreter was available to run it).
