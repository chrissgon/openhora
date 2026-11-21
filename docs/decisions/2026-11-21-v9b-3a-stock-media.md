## 2026-11-21: the licensed media set on the runtime, the set approval and the step's checks for a picture nobody checked (V9b-3a; spec `SPEC-video-V9b`, section 7.1 to 7.4 and 7.6 to 7.8, and its amendment of 2026-11-21)

**What was built.**

- **The store** (`runtime/media_stock.py`): `<data_dir>/media/<id>/stock/` (0700) with the previews (`prev-*`), the full files (`full-*`), the quarantine for the open web,
  the PNGs the renderer made (`asset-<sha12>.png`), the two contact sheets, `set.json` and `approved.json`. The set document (`{version, task, assets, credits}`, canonical JSON)
  is what the person approves and what `set_hash` hashes; the credit line of a CC BY picture and the credits record (`<data_dir>/media/credits/<task>.json`) are built by code.
  It calls no provider. The media store (`runtime/media.py`) names the closed files of that folder (`stock/set.json`, `stock/approved.json`, `stock/asset-<sha12>.png`,
  the two sheets) so the step kind reads them through `store.read` and `store.path` and imports no new module (limit L30's structure holds).
- **The operations** (`runtime/ops_media_stock.py`): `video-media-find` (without `--confirm` it sends nothing and says which words go to which sources; with it, each
  licensed source that serves the kind is searched, the sources of a slot at the same time and each source one request at a time, the candidates are merged round robin, at
  most six a slot and two from a source, a licence outside the tuple is dropped, and the renderer's `asset-sheet` draws the preview sheet), `video-media-fetch-picks`
  (every slot needs a pick; a licensed pick is fetched by its provider from the item id, an open-web pick by the web provider into the quarantine; the renderer normalises each
  file in a container; a clip pick is refused `clip_not_drawn` on an engine whose catalogue draws no clips), `video-media-sheet-file` (only the PNGs the container made),
  `video-media-approve` (the set, its hash and its credits; with the current hash it approves exactly that set) and `video-credits`. The sources are the implementations of
  the class `stock:media` that `providers/resolve.py` lists and their data files, read as data: **no source is named in the runtime** (a test greps).
- **The switch** (`media.stock`, `runtime/project_config.py`, `runtime/policy_widening.py`): a list of 1 to 8 shipped sources, `[]` for none, absent for the keyless ones.
  One widening item per licensed source (`stock=<name>@<terms_read_on>`) rides the record of the accounts: `accept-config` stops, prints what the person gives away, and
  needs `--widen`; until the record holds the items, the search answers `stock_not_accepted` (Q1: after one acceptance). The open web is not an item of this package.
- **The review edits** (`runtime/captions.py`, `runtime/ops_media_edit.py`, `runtime/media_animation.py`): the choice `stock`, `slot_search`, `slot_asset`, and layouts
  (a block with exactly one picture parameter, not an `hf:` block) an `animation` edit can add, each with a slot `a<n>` of its own. A pick that changes voids the approval.
  `REVIEW_VERSION` stays 1: the two new keys read as `{}` when absent.
- **The step's checks** (`runtime/step_media.py`): Continue is refused (`media_not_approved`) while a pick is not approved; the engine is handed `--asset` and
  `--asset-sha256` only for an approved picture a beat draws, and the approval is checked again at the render (`asset_not_approved`). A picture is approved when the set's
  `approved.json` holds the current hash, its file hashes to the set's sha256 again, and its licence is in the tuple or it is `unverified` with an approval of its own for this
  task and this sha256 from a source the project still uses (limit L76). The delivery document gains three keys only when they hold something (`assets`, `web`, `credits`),
  so a video with no picture keeps the document and the hash it had; the card and the body say the pictures, the credit lines to put in the caption and, for a picture
  nobody checked, its host (the address is read from the store, shown only when it is the one the document's hash names).
- **Retention** (L77): the previews, the full files, the quarantine and every picture the set does not list go after a day (`media.purge`) and at the approval, a new find
  and a new fetch; the approved pictures go with the recording 7 days after the delivery, and with the folder; the credits record is kept 365 days after the approval.
- **Limits L75 to L77** in `contracts/runtime.md`, each with its test; the phrases `v9b-3a.*` and the ledger `runtime/tests/expected/v9b-3a.json`.

**The saving and the loss of each limit.**

- **L75** (accepted sources, the confirm, the class only): the saving is that a project that never accepted a library never sends a word to it, and that the person sees
  the exact words before they leave. The loss is two steps (an acceptance once, a confirm per video) before the first picture, and a fetch that fails when the provider's
  answer is not in the closed shape, so a library that changes its answer is a `fetch_failed` until its implementation is fixed.
- **L76** (only approved pictures are rendered): the saving is that no picture whose licence the platform could not show, or that changed after it was looked at, reaches
  a render. The loss is that a swapped or edited file stops the video (`asset_changed`) and the set must be fetched and approved again, and a source turned off after the
  approval stops a video that had its picture approved.
- **L77** (retention): the saving is that raw third-party files do not stay on the computer after the choice, and the credits survive the recording for a year. The loss is
  that a picture is fetched again for another video (an approval belongs to one task and one sha256, so nothing is reused).

**Readings of the spec** (the PR lists them too).

- The default sources of a project that names none are every shipped source whose data file says `secret_in: "none"` (read as data: openverse and the open web today), not a
  literal list, so that no source is named in the runtime. Only a project with a `media` object has the default (the person has set up videos); a project with none uses no stock source.
- The operations are class `G` (kind internal, never served in words), like every media operation, with privacy `off-host` and cost `provider` for the two that reach a
  library. The spec says class `R`; a class `R` row would put a network search in the catalog a line in words reaches and move the interpreter's catalog hash, which is a
  decision of the maintainer's. The terminal and the page may call them, the local network's socket may not call the first, second and fourth.
- Continue is refused at the step that follows the review (`remap`), not at the answer: the step kind has no hook on an answer. The task then fails with `media_not_approved`
  and the person approves the set or clears the picks (the review edit and the media operations accept a task that failed this way) and runs the video again.
- The credits record is kept 365 days after the approval (the spec says after the delivery); the delivery follows the approval, and the record is written once.
- A script slot is searched when it has the choice `stock` and a search; an added layout when it has a search and is not set to `none`.
- `runtime/ops.py` gets one import line for the five operations (the file is not in the part's row; every operation is reached through it, and `test_ops_facade` requires it).
- `interface/js/permissions.js` gets the three write functions of the page (`videoMediaFind`, `videoMediaFetchPicks`, `videoMediaApprove`), because the static test of `api.js` requires every POST function to be
  gated; the tests that list the routes, the jobs and the write functions (`test_service.py`, `test_service_media.py`, `test_interface_msg3c.py`) name the new ones. The page files are in
  `interface/js/views/` (`lobby-captions.js`, `lobby-captions-model.js`), where the spec's row names them without the folder; the delivery card needed no change (the card lines come from the document).
- The page draws the Pictures section only on this computer's own page and only at the caption review; the open-web asset's own panel and the warning texts are V9b-3b.
- The download answer does not repeat the credits (`runtime/ops_media.py` is not in the part's row); the card, the body and `video-credits` carry them.

**Verified.** The tests named in the pull request, offline, with a fake provider, a fake renderer and flat-colour PNGs made with zlib. **Not verified.** K3 (the supervisor's live
leg, after the maintainer's yes): a real search of Openverse, a pick, the fetch, the container's normalisation, the approval, a render with the picture and the delivery card.
No real picture, link, author or search result was used or committed. The open-web path (`video-media-websearch`, the stronger approval, the warning texts) is V9b-3b.
