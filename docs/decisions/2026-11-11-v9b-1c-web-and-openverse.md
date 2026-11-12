## 2026-11-11: the open-web source `web` and Openverse (V9b-1c; no measurement change, no skill changed, no lab run)

Part V9b-1c of the video plan's package V9b (cutaway media found by the agent). It adds two implementations of the class `stock:media` to `providers/stock/`: `openverse.py`
(keyless, per-item licences) and `web.py` (the file at a URL a model's web search wrote, tier `unverified`), with their source files, `_net.fetch_open` and tests. Nothing was
run against a real library or a real web page: every test is offline, with a fake network, generated media and `.example` hosts. `sources/openverse.json` is committed with
nulls and `sources/web.json` is the five fixed fields of the spec; the supervisor hands the values over at STOP 1 and STOP 4.

### What the maintainer decided (2026-11-11, relayed by the supervisor; quoted as written)

- Decision 7: "Para falar a verdade eu nao acho que acaba sendo muito util cobrar do usuario contas nessas plataformas para ter acessos ao videos e imagens. Vamos fazer buscando pelo google mesmo, e alertamos do possivel problema com direitos autorais. Vamos deixar essas opcoes de pixabay caso ele queira ou já tenha criado uma conta nessas plataformas mais recomendadas" validate: allow english-only -- a quotation of the maintainer's own words
- Decision 8, after being told that Openverse needs no account and could be on by default and asked whether the search is done with the agent's own search tool: "Sim, assim" validate: allow english-only -- a quotation of the maintainer's own words

Meaning: the default sources need no account (a web search done by the agent, in the `unverified` tier, and Openverse, keyless, in the `per-item` tier); Pixabay and Pexels are optional.

### The facts found that day (relayed, not read here)

- Pexels shows "New API key issuance is currently paused and cannot be requested." (the maintainer's screenshot).
- Pexels' terms, section 8, forbid "Data mining, extraction, scraping and the use of programs or robots for automatic data collection".
- Pixabay's documentation says "Systematic mass downloads are not allowed".
- Google's Custom Search JSON API is closed to new customers and is discontinued on 2027-01-01 (the source is Google's overview page as third parties cite it).
- Scraping a search engine is out: it breaks the engine's terms and is blocked by captchas, which are never bypassed.

### Decisions

- **D1. `web.py` is the one place a URL a model wrote is opened** (spec D8, limit L79 once V9b-3b writes it). It never searches; the page URL of a candidate is never fetched. The
  checks live in `_net.fetch_open`, beside `download`, which is unchanged for the licensed sources: https on 443 only, a public host name (no IP literal, no trailing dot), every
  resolved address global and the connection opened to the one checked, per hop, at most two redirects each checked again, no cookie, `Authorization` or `Referer`, a size cap
  before and while the body is read, the type read from the first 16 bytes (PNG, JPEG, MP4, WebM) before any byte is written, the file 0600 in `<task>/stock/quarantine` under its hash.
  The person's refused and allowed host lists are arguments, empty by default. Nothing is decoded; no HTML is kept.
- **D2. Nothing prints a URL beyond its host.** Diagnostics hold a code and a validated host name; a usage error is a fixed text (argparse would echo the argument, and an argument can be a URL);
  an unforeseen exception is a fixed refusal. A test plants a token in a path, a query and a `Location` and scans every output and every file name.
- **D3. The quarantine folder is a rule of the fetch, not of its caller.** `check_quarantine` requires a folder `check_out` accepts, named `quarantine`, inside a folder named `stock`; a folder
  anywhere else, with another mode or inside a reference store is `out_refused` before any lookup.
- **D4. The `unverified` tier stays refused without `--allow-unverified`**, for `web.py` too (`licence_refused`, no request), though the spec's flag list for `preview` and `fetch` does not name it:
  the rule of `_stock.py` ("refused unless the caller says the project turned it on") holds for every source of that tier. V9b-3b passes the flag only when the project's `web` switch is on.
- **D5. `read_source` accepts an open-web source file** (the spec allowed this edit of `_stock.py`): exactly the keys `source`, `licence_tier`, `secret_in`, `kinds`, `terms_read_on`, with the tier
  `unverified`, `secret_in` `none`, valid kinds and `terms_read_on` null (a date would claim a reading that never happened; the 365-day rule does not apply). The answer carries every other key empty.
- **D6. Openverse** is tier `per-item`, `secret_in` `none`, kinds `image`. Each item's own licence and version are keyed `"<licence> <version>"` (lower case) into the source file's `licences`
  table; an item whose pair is not in the table is dropped, so CC BY-SA, NC, ND and a CC BY with no version never pass, and the class refuses a table that maps to an id outside the
  accepted tuple. An item with a credit licence and no author is dropped by the class, and one whose preview or file host is not in `media_hosts` is dropped (`host`). `SECRET` is the empty
  string, so a source file that names a secret is refused and no key is read, sent or kept.
- **D7. Licence policy unchanged.** No licence id is added; `LICENCES_ACCEPTED` and `LICENCES_CREDIT` are as in V9b-1.

### Deviations from the spec text, stated

- The search of Openverse sends `license_type=commercial,modification`, `q` and `page_size`. It does **not** send a filter "only for the upstream sources whose hosts are in `media_hosts`": the
  library's `source` parameter names providers, not hosts, and the source file has no field for them. The host rule is applied to each item instead (`host`), which gives the same guarantee for
  what reaches a render. The parameter and field names are from the library's public documentation as known to the author, not read this session: K1 verifies them.
- `web.py` and the other sources take `--source-file` and `--today` before the verb, like the class; the spec's flag list for `preview` and `fetch` omits them.
- `fetch_open` returns `redirects` as well as the five fields the verb prints, and `web.py` writes `web: ok host=<host> redirects=<n>` on stderr for success, so K1 can record the redirects without
  the URL being printed.

### What the tests could not leave as they were

Three tests of V9b-1's `tests/test_stock_registration.py` fail with the new sources, which this part's row does not let it edit (stop rule 2 of the spec): `test_every_implementation_declares_the_class_and_its_verbs_as_text`
(it requires `VERBS == ("search", "fetch")`, and `web.py` has `("preview", "fetch")`), `test_no_source_name_appears_in_the_runtime_or_the_renderer` (it searches for the word `web`, which occurs in 100 files
of `runtime/` as ordinary English: "open web", "web search"), and `test_adding_a_source_is_two_files_and_no_other_change` (its expected list is `["aster", "pexels"]`). The supervisor decides how they change.

### What is not verified, and the residual risk

Everything about a real library or web server: Openverse's access, limits, field and parameter names and upstream hosts; whether real servers' redirects, lengths and types behave as the fake network's
do (K1). The sniff reads the first 16 bytes only: a file that begins as a PNG and carries other content is kept as a PNG, which is why nothing here decodes it and the renderer decodes it only in a
container with no network. The residual risk of the `unverified` tier is the one the maintainer accepted with decisions 7 and 8: a web file may be someone's property, and the copyright warning and the per-asset approval of V9b-3 are the guard, not code.

### Openverse values approved (2026-11-11)

The supervisor asked the maintainer: "Aprova os valores do Openverse como recomendei, e a busca de teste K1?" He answered: "Aprovo os dois". validate: allow english-only -- a quotation of the maintainer's own words

This answers STOP 1 and the first part of STOP 4 for Openverse. The upstream file hosts are not approved yet; they come after K1.

Facts read on 2026-11-11 from the public schema (https://api.openverse.org/v1/schema/, version 50135c9), the terms of service (https://docs.openverse.org/terms_of_service.html, effective 2022-05-05) and the rate-limit headers:

- Anonymous limits: `anon_burst` 20 a minute, `anon_sustained` 200 a day; thumbnails have their own bucket, `anon_thumbnail`, 1000 a day. `page_size` defaults to 20 and more than 20 is throttled for anonymous callers.
- The `license` filter takes `by`, `by-nc`, `by-nc-nd`, `by-nc-sa`, `by-nd`, `by-sa`, `cc0`, `nc-sampling+`, `pdm`, `sampling+`. Results carry `license`, `license_version`, `url`, `thumbnail`, `foreign_landing_url`, `creator`, `title`, `source`, `attribution` and `mature`.
- `mature` defaults to false and `filter_dead` to true; `source` is a comma-separated list of the `source_name`s of `/v1/images/stats/`.
- Endpoints: `/v1/images/` (search), `/v1/images/{identifier}/` (detail), `/v1/images/{identifier}/thumb/` (thumbnail, served by api.openverse.org itself).
- Terms of service: no scraping; adhere to all rate limits; no several machines to get around them; proper attribution to CC-licensed works; an app built with the API must prominently say it was made using Openverse but is not endorsed or certified by Openverse; Openverse does not verify licensing status; it may charge fees for commercial or heavy use.

Values committed in `providers/stock/sources/openverse.json` (their own commit, as for V7e):

- `licences`: `cc0 1.0` to `cc0-1.0`, `pdm 1.0` to `pdm-1.0`, `by 4.0` to `cc-by-4.0`, `by 3.0` to `cc-by-3.0`; `licence` stays null (per-item tier).
- `licence_url` the terms of service URL; `terms_read_on` `2026-11-11`; `cache_seconds` 86400.
- `api`: host `api.openverse.org`, search `/v1/images/`, item `/v1/images/{item}/`, no clip endpoints.
- `media_hosts` `["api.openverse.org"]` (the preview host), `redirect_hosts` `[]`; `path_patterns.preview` `^/v1/images/[0-9a-f-]{36}/thumb/$`; `image` and `clip` stay null until K1.
- `rendition`: preview `thumbnail`, image `url`, clip null. `openverse.py` reads the answer's fields directly, so the class's own check (a name of 1 to 40 characters) is all that reads these.
- `credit_line`: `{title} by {author}, {licence}, via Openverse`. The class documents no placeholder vocabulary for it; the names are the ones given in the approval.

Code: the search sends `license=cc0,pdm,by`, `source=flickr,wikimedia,stocksnap,rawpixel,nasa,met` (constant `UPSTREAM_SOURCES`, since the class's `SOURCE_KEYS` is strict; `inaturalist` is out on purpose, mostly species photos), `page_size` at most 20 and `mature=false`. `license_type` is gone. The table stays the rule; the filter is a first pass.

The source stays `source_not_ready` (field `path_patterns.image`) until K1 fills the file hosts and the image pattern.

### CC BY 2.0 and 2.5, and the hosts from K1 (2026-11-11)

K1, the supervisor's live leg, searched Openverse with the approved parameters, then made one detail call, one file fetch and one thumbnail fetch. The supervisor then asked the maintainer: "Aceito também CC BY 2.0 e 2.5, com crédito na legenda como a 3.0 e a 4.0?" He answered: "Sim, aceite". validate: allow english-only -- a quotation of the maintainer's own words

This is a licence policy change (the maintainer's word), and the spec's amendment of 2026-11-11 widens this row to `providers/stock/_stock.py`, `LICENCES_ACCEPTED` and `LICENCES_CREDIT` only.

K1 facts: 20 results, all `license` "by" with `license_version` "2.0"; 19 from the source flickr with `url` host `live.staticflickr.com` and paths like `/3731/11907599844_507ae44b10_b.jpg`, `/2370/2325882432_94b118903a.jpg`, `/51/121209617_949ce54a9d_b.jpg`; 1 from wikimedia, host `upload.wikimedia.org`, path like `/wikipedia/commons/b/b8/P%C3%B4r-do-sol_no_Vale_do_Rio_das_Antas_%285982770740%29.jpg`; the thumbnails all on `api.openverse.org`. The Flickr file came back 200, `image/jpeg`, 1024x768, no redirect. The version string of pdm was not seen, so `pdm 1.0` stays.

Changes:

- `_stock.py`: `cc-by-2.5` and `cc-by-2.0` join `LICENCES_ACCEPTED` and `LICENCES_CREDIT` (an item with one of them and no author is dropped, like 3.0 and 4.0). Nothing else in that file.
- `sources/openverse.json`, in its own commit: `licences` gains `by 2.5` and `by 2.0`; `media_hosts` is `["api.openverse.org", "live.staticflickr.com", "upload.wikimedia.org"]`; `redirect_hosts` stays `[]`; `path_patterns.image` accepts exactly the two path shapes (`/<digits>/<digits>_<hex>[_<letter>].jpg|jpeg|png` and `/wikipedia/commons/<hex>/<2 hex>/<name>.jpg|jpeg|png`, a name of letters, digits and `_ . % ( ) -` without `..`). The source is ready.
- A `by 1.0`, `by-sa`, `by-nc`, `by-nd` and a `by` with no version are still dropped.

Limits found, stated:

- The class applies `path_patterns` with `fullmatch` on the URL's path only, one pattern for every host (`_stock.py`, `_net.split_url`). A pattern per host is not possible, so a Flickr-shaped path on the Wikimedia host matches too; the host list is what keeps other hosts out.
- The path the pattern sees leaves out the query: `split_url` returns the path without it, and the request target keeps it, so the pattern alone would let a file URL with a query through. This is closed in the implementation, not in `_net.py`: `openverse.py` (`_clean_url`) drops an item whose `url` or `thumbnail` has a query, a fragment, user info, a port or a scheme other than https. The class then refuses the missing URL with its existing codes: `host` in a search (counted in `dropped`), `host_refused` in a fetch. `_net.py` is unchanged.

### Downloads with no Content-Length, and the row extension (2026-11-11, after K1)

K1's live fetch of an Openverse file got an item answer of 200 and a Flickr file answer of 200 `image/jpeg`, and the provider refused it with `no_length`: Flickr's CDN serves the file with `Transfer-Encoding: chunked` and no `Content-Length` (seen three times with curl `--http1.1`). The class's `_net._save` refused every download without a length, while `_save_open` already read one under the cap.

The supervisor approved extending this row to `providers/stock/_net.py`, `_save` only, to follow `_save_open`'s rule:

- A missing `Content-Length` means the length is unknown; the cap is enforced while the body is read (`too_large` once the total passes it) and the final "exactly that long" check applies only when a length was given.
- A `Content-Length` that is present and not a number is still `no_length`; a given length over the cap is still `too_large` before a byte is read; the signature sniff, the deadline, the 0600 temp file and its removal on any failure are unchanged. The `download` docstring says so.
- Tests (`test_stock_net.py`): a chunked answer under the cap is saved with the right sha256; one that passes the cap mid-stream is `too_large` with no file and no `.part-*`; a malformed length is `no_length`; a body shorter than a given length is `network`; a body with no length still has its signature checked.

The residual risk: a server with no length can make the provider read up to the cap (the per-file cap) before refusing; the deadline still bounds the time.

