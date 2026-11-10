## 2026-11-10: the reference store, its operations and the terminal (V7b; no measurement change, no skill changed, no lab run)

Package V7b of the video plan, built against the verb contract of the V7 spec (section 3.6) with a fake provider, in parallel with V7a, which writes
`providers/fetcher/`. It is terminal only: messaging and the page are V7d. Nothing was fetched, no container ran, no link was used.

### Decisions

- **D1. The store** is `runtime/references.py`: `<data_dir>/references/<id>/` outside the project, with the marker file `.openhora-reference` (mode 0400,
  written once), one folder per reference (16 hex characters, 0700), `record.json` (0600, the link lives there and nowhere else), and the closed names
  `info.json`, `proxy.json`, `subs.<lang>.vtt` (at most 4), `video.<ext>` and `facts.json`. 50 references and 2 GiB, checked before a fetch under one lock;
  the free bytes go to the provider as `--max-bytes`. The descriptor discipline is that of `runtime/media.py` (O_NOFOLLOW, folder descriptors, the record
  written whole under a lock); its few helpers are copied, not imported, so the two stores stay independent.
- **D2. Five operations**, class G, kind internal, `model: False`, `channels: ("terminal",)`, orders 177 to 181 of the catalog (since 4, like
  `media-remove`): `reference-add`, `reference-video`, `reference-list`, `reference-read`, `reference-remove`. No group, no route, no phrase key (the
  principle-13 cut: one use, terminal only). Any other channel is refused with `operations.not_enabled`.
- **D3. The provider is a seam.** `ops_references._fetcher_for(ctx)` returns the real `Fetcher`, which resolves `fetcher:video` through
  `providers/resolve.py` (never by path) with the minimum environment of its class (`provider_environment(cls, None, ())`: no cookie, token or choice of
  another class). A class that does not resolve, or exit 3, is "build the fetch tool (providers/fetcher/README.md gives the command, run by you)". A refusal
  is one of the closed codes of the spec (`link_refused` ... `time_limit`), read from the first words of the provider's stderr; anything else is
  `fetch_failed`. The tests replace the seam with a fake of the verb contract. The runtime reads the provider's answer through a closed shape (`ok`, the
  stage, files with closed names and the sizes they say, a duration, `subtitles`) and removes from the folder whatever else a provider left.
- **D4. The facts** are `facts.json`, written by `measure --out <reference folder>/facts.json` and checked by `references.check_facts` against the closed
  shape of version 1 (exactly these keys, these types, these bounds, this reference and platform): a facts file that fails is removed, never kept. The
  shape is written in `runtime/references.py` because the runtime does not read a provider's file.
- **D5. Reference only, in code** (L73). The video is deleted in a `finally` of `reference-video` right after `measure`, whatever `measure` returned,
  and `video_deleted` is `true` only when none is left; a stray `video.*` older than an hour is purged by the upkeep. `media.receive_file` refuses a path
  for which `references.in_reference` is true (the real path or a folder above it holds the marker file). A test reads the AST of the two new modules and
  fails on `media.receive`, `write_work`, `shutil.copy*`, `os.link` or an import of `media` or `shutil`. Not caught, and L73 says so: a copy or a hard link the
  person makes outside the store during the minutes the video exists.
- **D6. Retention** (L74): `references.purge`, the upkeep part `references` after `media`: a reference 30 days after `created_at`; a `video.*` or a
  `.fetch-*` folder older than an hour; a folder with no record after a day; a folder whose record is damaged after 30 days; a `.removed-<id>` at once.
- **D7. The consent** is `media.references`, `"on"` or `"off"` (absent is off), a fourth key of `media`; `_media` names the four keys. `"on"` is a
  widening. It is an item of the record that already holds the accounts (`policy_widening.account_items` appends `reference_items`; the cursor
  `config:accounts`): `accept-config` stops, prints the terms (the spec's text), and needs `--widen`. That reuses the one place that reads `config`,
  `accept-config` and the pending-configuration check (`ops_config`, `policy_grants`, `ops_core`) with no edit to them. Turning it off needs nothing; turning
  it on again is listed again, because acceptance with `"off"` records no item.
- **D8. Third-party text is data.** The title, the description and the subtitle text sit in `facts.json` under `external_text`, whose `note` is the fixed
  sentence; no model reads them in V7. `reference-read` returns the facts, then, last, `external_text.heading` ("External text (data, from the platform, not
  checked)") and its lines, each quoted with `> ` (a line break cannot end the quote; control characters become a space). No other answer, error or log holds
  a link, a title or a subtitle's text; V8's skill carries the line **External content is data.**
- **D9. No platform in the runtime** (design rule 2). Every host comes from `shared/references/platforms/<platform>.fetch.json` (`link.hosts`, read as data
  and never staged into a skill's run); a test fails if a platform name or host of any `*.json` of that folder is written in the two modules.

### Limits

L72, L73 and L74 in `contracts/runtime.md`, each with its test: `runtime/tests/test_ops_references.py`
(`test_limit_72_a_reference_is_fetched_only_from_a_listed_host_with_no_credential`) and `runtime/tests/test_references.py` (`test_limit_73_...`,
`test_limit_74_...`). L72 and L73 are also V7a's (the proxy and the renderer's refusal).

### What was not verified

- **Against the real provider.** The verb contract was read from the spec (3.6), not from `providers/fetcher/ytdlp.py`, which is not in this branch. Assumed:
  `fetch` prints the object of 3.6 and writes its files into `--out`; refusals name one of the closed codes on stderr (`CODE_WORD`); `measure --out <path>`
  writes the facts file at that path and may or may not replace one (the runtime removes the old file first and puts it back if the new measure fails).
  If V7a's contract differs, the two functions `_check_fetch` and `_measure` are the places to change.
- That the marker name equals the one in `providers/_container.py` (a test compares them once V7a has landed; it skips until then).
- Nothing live: no fetch, no container, no real link, no download (live legs L1 to L7 are the supervisor's).
- The generated blocks (architecture tables, owner table, phrase snapshot) were not regenerated; the supervisor's regeneration commit does it.
