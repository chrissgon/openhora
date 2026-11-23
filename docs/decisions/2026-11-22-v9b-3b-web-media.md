## 2026-11-22: the pictures found on the web, their own approval and the copyright warning (V9b-3b; spec `SPEC-video-V9b`, sections 7.1, 7.5 to 7.8 and 8.3, and its amendment of 2026-11-22)

**What was built.**

- **`video-media-websearch --task T [--confirm]`** (`runtime/ops_media_websearch.py`; class G, kind internal, privacy `off-host`, cost `model`, a job; terminal and page; refused on the `--lan` socket,
  messaging and the MCP mode). Code decides, in order and with nothing run before the last: the video waits at the review; the open-web source (the one whose data file says `unverified`; no source is named in
  the runtime) is on and accepted (`web_off`, `stock_not_accepted`); the slots, at most six, a clip slot not sent while the engine's catalogue draws no clip (`skipped`, with `VID_STOCK_CLIP_NOT_DRAWN`) and every value
  sent checked again; the skill is a folder of this checkout that declares `search:web` and no side effect (`VID_WEB_NOT_BUILT`); the routed pair was measured with the web (`VID_WEB_NO_WEB`); the day's count is under
  `media.websearch.max_per_day` (`VID_WEB_LIMIT`); and without `--confirm` the words are printed and nothing else (`VID_WEB_PREVIEW`). With `--confirm` the run is `ops_research`'s again for this skill: the route
  lock, the claim lock, `answer_run_start` with the neutral text `web media search` and `web=True`, `ops_contained.execute(..., open_web=True)` with the bounds of `media.websearch` and the cancel watcher.
  The prompt is rendered (`render_prompt`) in the form the skill was measured on, and a test compares it with case 1 of the skill's evals, byte for byte.
- **The read-back.** `<run cwd>/.workbench-local/video/web-candidates.json`, every step opened without following a link, a regular file, at most 64 KiB, read once; the bytes are copied (0600) into a scratch folder, checked by
  `skills/mkt-video-media-search/scripts/check_candidates.py` (`python3 -I`, no shell) and again by `media_stock.read_web_candidates` (the same rules, plus: the slot and kind are exactly those sent, no unknown field);
  either failing refuses the file whole (`candidates_invalid`, `VID_WEB_FAILED`). The scratch folder and the whole run folder are removed in a `finally`, after the usage was read and the row finished.
- **The previews.** One `preview` call of the open-web provider for each candidate (`--kind image --url <thumbnail, else the file> --out <quarantine> --max-bytes 4194304 --allow-unverified`, the person's host lists, 40 s,
  at most 18 a run, 4 at once); the answer is checked against the closed shape, the type, the name and the file's own facts; a refused preview drops its candidate and is counted. The record kept in `set.json` holds the
  link of the file; no answer, run row or log does.
- **One set, two searches** (`ops_media_stock._compose`, `_carried`): `video-media-find` replaces the licensed candidates and keeps the open-web ones of a `found` set whose slot has the same words and kind and whose
  preview file is still there with its sha256; `video-media-websearch` does the converse; both void the approval; a new web search removes the open-web previews, a new find the licensed ones (limit L77).
  `video-media-fetch-picks` asks for the acceptance of a licensed source only when a licensed pick exists and of the web source only when a web pick exists, so a project with only the web source fetches.
- **`video-media-approve-asset --task T --slot S --sha256 H [--confirm-digits <12 hex>]`**: refusals, each with nothing written: not at the review; no fetched set or a changed file; the set approval does not match the current hash
  (`not_approved`); the slot is not an `unverified` asset (`not_unverified`); `H` is not its sha256 (`wrong_hash`); the web source is off or not accepted. Without `--confirm-digits` it answers the warning, the host, the page,
  the claim ("claimed by the page, not checked") and the first 12 digits to type; with them it writes `approved.json["unverified"][S] = {sha256, task, at, channel}` and nothing else of the approval changes (`wrong_confirm`
  otherwise). The step's checks (`step_media._stock_assets`) already require that record for this task and this sha256; neither `step_media.py` nor `deliver_document.py` was edited.
- **The set approval** lists `needs_own_approval` (the web files with no approval of their own) and `own_approved`; approving the same set again keeps the own approvals (V9b-3a rewrote `unverified: {}`); the page no longer
  disables "Approve the media" while a file needs its own approval, which was a deadlock: the file is approved after the set.
- **The switch** (`runtime/policy_widening.py`, `runtime/project_config.py`): the open-web source is a widening item of its own, `stock=<source>@none`, with the approved text of 7.1 (below); a project accepted under V9b-3a
  accepts again. `media.web_refused_hosts` and `media.web_allowed_hosts` (lists of at most 100 lower-case host names, the expression of the provider's `HOST_RE`, which a test compares) and `media.websearch`
  (`max_per_day` 5, `max_cost_usd` 0.60, `timeout_seconds` 300, the ranges of `research`) are accepted keys.
- **The page** (`interface/js/views/lobby-captions.js`, `lobby-captions-model.js`, `api.js`, `permissions.js`): "Search the web" beside "Find media", each with its preview first and sending only on "Send the words and
  search the web"; a web candidate's tile says where it was found, what its page claims, whether it is a still of a screen work and the page address as plain text (never an anchor, never an image from another host;
  the CSP stays `img-src 'self' blob:`); after the set approval, one panel for each file that needs its own approval, with the warning in the project's language, the asset's own PNG and "Approve this file".
- **Credits and pages**: the download answer gains `source_pages` ("Source page: <page>") from the credits record; a card shows no page address (S4).
- **Limits L78 to L80** in `contracts/runtime.md`, each with its test; the phrases `v9b-3b.*`; the ledger `runtime/tests/expected/v9b-3b.json`.

**The approved warning texts, quoted** (the maintainer approved them, Q2; in Portuguese the platform is "plataforma"). The key is `VID_WEB_WARNING`; `{host}` and `{page}` are filled by code.

- en: Copyright warning: this file was found on the open web, on {host}. The platform could not check who owns it or whether it may be reused, and the licence the page states, if any, was not checked. If you approve it and publish the video, the video may be taken down and your account may receive a copyright strike. Approve it only if you know you may use it. Source page: {page}
- pt-BR: Aviso de direitos autorais: este arquivo foi encontrado na internet, em {host}. A plataforma não conseguiu verificar quem é o dono nem se ele pode ser reutilizado, e a licença que a página diz ter, se houver, não foi verificada. Se você aprovar e publicar o vídeo, ele pode ser removido e sua conta pode receber uma advertência por direitos autorais. Aprove só se souber que pode usá-lo. Página de origem: {page} (validate: allow english-only -- the approved pt-BR warning)

The short form on the card is 3a's `CARD_VIDEO_WEB` ("Found on the web, licence not checked: {host}"), which already holds the approved short text in both languages; no `VID_WEB_WARNING_SHORT` was added. The other approved texts are
`VID_WEB_NOT_BUILT`, `VID_WEB_NO_WEB` and `VID_WEB_NEEDS_OWN` (7.7). The widening text of the web item is the approved one of 7.1, unchanged:

- web search: the search words of each video are sent to the web search of the model that runs it and to that model's provider; the pictures and clips found have no licence the workbench can check; each needs its own approval after a copyright warning; a published video that uses one can be taken down and can strike your account

**Not part of the approved set** (new in this package; the maintainer may change them): `VID_WEB_PREVIEW` (the per-video confirm phrase, which carries the download disclosure: "These words will be sent to the web search of the
model that runs it and to that model's provider, and this computer will then download small previews from the sites found: {words}."), `VID_WEB_LIMIT`, `VID_WEB_FAILED` and `VID_WEB_NOTHING`. The disclosure that this computer
fetches previews and files from third-party sites, which see its address, was put in the per-video phrase and not in the approved web-widening text, which stays as approved.

**The saving and the loss of each limit.**

- **L78** (accepted, confirmed, measured with the web, nothing of the project, checked, removed): the saving is that a search that sends words to a model's provider and spends model money happens only when the person saw
  the exact words, accepted the item and chose a pair the lab measured with the web, and that nothing a page said stays on the machine but a checked, bounded file's candidates. The loss is two steps before the first
  web picture, a refusal on a pair with no web proof, and a run folder that cannot be inspected afterwards (stricter than research, which keeps its folder for `run_retention_days`).
- **L79** (a link a model wrote is opened only by the provider): the saving is that one file holds every rule of the reach to the open web. The loss is that a link the provider refuses (a port, a redirect, a type) is
  a dropped candidate, and a preview costs a download from a site that sees this computer's address.
- **L80** (a file needs its own approval, for this task and this sha256): the saving is that no file nobody checked is drawn on one yes for a set, and none is reused for another video. The loss is one more step for each
  such file, and a fetch again for another video.
- **Class G** (the amendment): both operations are internal rows, so the catalog a line in words reaches does not move (principle 12); the loss is that a search cannot be asked in words, only on the page and in the terminal.

**Readings of the spec and departures** (the pull request lists them too).

- The terminal flag of the 12 digits is `--confirm-digits`, not `--confirm` as the amendment writes it: `test_operations_table.py` requires one flag name to be one kind across the rows, and `--confirm` is a switch in every other row (the argument is still `confirm` in the operation and in the page's request).
- `roles.json` is not touched: the skill is the constant `SKILL = "mkt-video-media-search"`, as `ops_research.py` does (B1).
- The websearch row carries `"model": True`, since `test_registry_rows.py` ties the cost `model` to the `model` column, and the ledger holds one more key than the amendment lists (`registry_rows.MODEL_ROWS`).
- The tests that count the rows, the jobs, the routes and the page's writes are extended for the two operations, as V9b-3a extended them: `test_registry_rows.py` (136 rows), `test_interpreter_interfaces.py`,
  `test_service.py`, `test_service_media.py` and `test_interface_msg3c.py`; `test_service_media.py` also gains the test of the LAN refusal, and `DIALOG` of `test_interface_stock.py` gains an `extraApi` hook that is empty for
  every earlier test. The two assertions the amendment names (`test_media_stock.py` and the `own` assertion of `test_interface_stock.py`) changed as it says.
- The run row records the kind of a failure and never the lab's reason (it could hold a link); `answer_run_finish` is given no `run_dir`, since the folder is removed.
- A search that finds candidates but whose every preview is refused is not an error: the set is rewritten without the open-web ones and the message is `VID_WEB_NOTHING`. A candidates file with no candidate is an error
  (`web_nothing`, or `web_no_web` for an `open` item `no_search_tool`) that changes nothing.
- The page address of a candidate is kept whole in `set.json` (up to the 2048 characters the checker allows); the licensed path's 300-character cut applies to the credit line only.
- `candidateText` of the page's model is unchanged; `webLines` draws a web candidate's tile.

**Verified.** The tests named in the pull request, offline: a stand-in for the run of the skill that writes the candidates file, a fake of the class `stock:media` whose `preview` and `fetch` write flat-colour PNGs, a fake renderer
`asset-sheet`, the real checker script of the skill and the real approval path through the step. Nothing was searched, fetched or run on a model; every name is invented and every host ends in `.example`.
**Not verified.** K4 (the supervisor's live leg, after the maintainer's yes): that `routing["web"]` is true for the skill on the model chosen and on its adapter; what `result["cwd"]` holds for this skill (assumed as for
research); that the renderer's container reads a preview from the quarantine folder for the contact sheet; how often a model returns direct file links with a thumbnail; the hosts, redirects, cost and time of a real search.

## K4 fix: the picks

**Cause.** A search writes one set row per slot it was given, with or without candidates (`_compose`), and `_picked` of `video-media-fetch-picks` required a pick for every row of `set.json`, read from the set and not from the
review as it is now. In the live run on 2026-11-23 the clip slot `a2` was skipped by design (the engine draws no clips) yet stayed in the set with 0 candidates, and setting its choice to `none` did not help: the fetch stopped
with `no_pick`. The licensed path of V9b-3a on `main` has the same `_picked`: a find whose sources found nothing for a slot, or a clip slot no licensed source serves, blocks the same way (the person could get past it by choosing
`none` and running `video-media-find` again, with no model call). The fix reaches `main` with this pull request, not as a hotfix (the maintainer ruled: wait).

**Decision A1.** For each row of the set: (1) a row with a pick must have a pick that is one of its candidates, with the clip checks as before; (2) a row with no pick that has no candidates, or is no longer one of
`media_stock.stock_slots` (another option chosen, the layout removed, the words lost), is left without a picture: it is not fetched, the step renders it as the person's choice, and the answer lists it
(`without_picture`) with a sentence (`VID_STOCK_NO_PICTURE`); (3) a row with no pick that has candidates and is still a stock slot is `no_pick`, as before. With no pick at all the answer is `no_pick` ("no slot has a
pick"). `_compose`, `_carried`, `stock_slots`, the skipped list and the step are unchanged, so the page still shows "nothing found" for an empty row. Saving: no model call and no manual round trip to get past an empty slot.
Loss: a person who forgets a slot with no candidates gets no refusal, but the answer names the slot.

**Tests** (offline): `test_a_skipped_clip_slot_does_not_block_the_fetch_and_is_left_without_a_picture` (the live failure), `test_a_slot_the_sources_found_nothing_for_is_left_without_a_picture` (the licensed path),
`test_a_slot_whose_choice_is_no_longer_stock_is_skipped_by_the_fetch`, `test_the_fetch_with_no_pick_at_all_is_refused`; the existing test of a missing pick (rule 3) is unchanged. A check that the step passes
`--empty-slot beat8=none` and renders `beat7` only was not added: the step kit needs new plumbing to reach it.

## K4, the live leg (2026-11-23)

**Run.** By the supervisor after the maintainer's yes, on a scratch project and state folder, with the project's default model `claude-haiku-5-5` (adapter claude-code, subscription billing; routing web true, autonomy
proven; bounds max_cost_usd 0.6, timeout 300 s), a generated recording and a built transcript, three slots (two pictures, one clip).

**First attempts.** On 2026-11-23 they found two defects that stopped every run at `video-media-fetch-picks` with `no_pick`: A, a slot with no candidates (the skipped clip slot of 3b) blocked the fetch, and B, a web
clip with no thumbnail was always dropped at the preview. Both are fixed in this round (A in "K4 fix: the picks" above, B in the decision file of V9b-5c). On this branch's own code (images
openhora-renderer:cc41c16fd797 and openhora-hyperframes:12ff7f4128cb) the run before fix A reached: clip slot skipped as designed, 4 picture candidates, every preview made (thumbnails given), 50 s, 268,386 tokens;
then `no_pick`.

**The complete run.** Made on the code of V9b-5c at 02904ef, which contains this branch with fix A (images openhora-renderer:d6feec7d70e9 and openhora-hyperframes:5bbbcd52f5e0):
- Web search: 47 s, 334,297 tokens, run ok. Candidates: slot 1 one picture (page host isorepublic.com), slot 2 one clip (page host pixabay.com, no thumbnail), slot 3 none (three full-size pictures without a thumbnail
  were refused at the preview, probably over the 4 MiB preview cap: noted, not fixed in this round).
- Fetch: 43 s; `without_picture` named slot 3. The set was approved in the terminal; the picture's own approval was given on the page channel and the clip's in the terminal, each warning showing the host.
- Render verified on HyperFrames (204 s, then 278 s on a re-render) and on ffmpeg (93 s, then 117 s).
- The deliver card listed the two web hosts and held no page address. A second task could not use the first task's own approvals (`media_not_approved`).
- Delivered: the local download listed 2 source pages (hosts isorepublic.com, pixabay.com) and the page's credits held 2 web entries with their pages.
- `media-remove` removed the recording and the stock folder. Every fetched file was deleted after the run.

**Not checked.** Redirects counted per fetch; the page itself in a browser (the page channel was exercised through the operation the page calls).
