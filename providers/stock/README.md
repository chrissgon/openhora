# providers/stock: the class `stock:media`

Libraries of pictures and clips whose licence allows reuse in a published video, searched by words through their API. A runtime-only class, like
`renderer:video` and `fetcher:video`: no skill requires it and `contracts/environment.md` does not list it. One implementation per library
(`providers/stock/<name>.py`), each with its source data file (`providers/stock/sources/<name>.json`). Package V9b-1 builds the class and Pexels;
Pixabay and Openverse are V9b-1b. Nothing here has run against a real library yet: the tests use a fake network, generated media and a fake key.

```
providers/stock/
  _stock.py           the class: licence tuple, source file checks, caps, query rule, answer cache, secret lookup, candidate schema, the verbs
  _net.py             the closed-host fetch: host list, global addresses, the address checked is the address connected, one redirect to a listed host
  pexels.py           how to call Pexels and read its answer (SERVES = "stock:media")
  sources/pexels.json the source data, committed with nulls: every value is filled by the maintainer's approval
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
- `unverified`: no licence the code can read. A seam only: no such source is built, the provider refuses it without `--allow-unverified`, and the
  runtime (V9b-3) admits one only with the project's own switch and a separate approval of each asset.

## The source file

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
   `search_request`, `item_request`, `read_search`, `read_item` (copy `pexels.py`: it is the whole of how to call one API and read its answer).
2. `providers/stock/sources/<name>.json`, committed with nulls; the values come from the maintainer's approval of the library's terms.
3. If the library needs a key, its `REGISTRY` entry in `providers/secrets/resolver.py` and its row of `contracts/secrets.md`, in the same change.
4. No skill, runtime or renderer file changes: the runtime lists sources from `providers/resolve.py` and the source files. A test copies `pexels.py`
   to a new name in a temporary checkout to prove it.

Two exceptions are not files-only additions: a source whose licence id is not in `LICENCES_ACCEPTED` is a **licence policy change** (both tuples, a
decision file, the maintainer's word), and a source of the `unverified` tier is its own package with its own terms.

Select the implementation with `STOCK_MEDIA_PROVIDER`, then `STOCK_PROVIDER`; the runtime names each source a project turned on.

## What is not verified

That a library's answers and files keep the fields and hosts its documentation names (the first live run, K1, reads them); which rendition of a
photo or a clip covers 1080 x 1920; whether a redirect of a media host goes to a listed host; whether downloads count against a library's limits; the
Python 3.9 run (the test suite parses every file as 3.9 and the code uses nothing newer, but no 3.9 interpreter was available to run it).
