## 2026-11-23: the preview of a web image with no thumbnail is the file itself, up to 16 MiB, and an oversized picture is dropped alone (V9b-3c; finding C of K4)

**The defect.** `_preview` of `runtime/ops_media_websearch.py` previewed a candidate with no `thumb_url` from its `media_url` through the open-web provider's `preview` verb, whose cap is 4 MiB. A full-size
photo of a stock or free-photo site is commonly larger, the provider answered `too_large`, and the candidate was dropped (`dropped.preview`). In the K4 live run 3 of the 5 previews were dropped this way,
every one an image with no thumbnail. The file of an image may be up to 16 MiB (`media_stock.KIND_BYTES["image"]`, the provider's `CAPS["image_bytes"]`), so the preview cap refused images that the fetch of the pick would accept.

**The maintainer's choice, 2026-11-23**, between a preview up to 16 MiB and no preview at all (as a clip): "Prévia até 16 MiB" (validate: allow english-only -- the maintainer's own words, quoted)

**The call, by row.**

| Row | Call | Cap | Timeout |
|-----|------|-----|---------|
| clip with no `thumb_url` | none (unchanged, fix B of K4) | n/a | n/a |
| any row with a `thumb_url` | provider verb `preview`, `--kind image --url <thumb_url>` (unchanged) | `PREVIEW_BYTES` (4 MiB) | `PREVIEW_TIMEOUT` (40 s) |
| image with no `thumb_url` | provider verb `fetch`, `--kind image --url <media_url>` | `FILE_PREVIEW_BYTES` = `KIND_BYTES["image"]` (16 MiB) | `FILE_PREVIEW_TIMEOUT` (70 s) |

For an image with no thumbnail the preview is the file itself, which is what `fetch --kind image` is by the provider's contract (16 MiB, 60 s, PNG or JPEG, into the quarantine as `q-<sha12>.<ext>`, the
same answer keys). The provider is not edited. The flags are otherwise the same as before (`--out`, `--max-bytes`, `--allow-unverified`, the person's host lists). The answer check is unchanged with the cap of the
call in place of the 4 MiB one. The call is still one of at most 18 previews, 4 at a time, and does not count toward the provider's per-video file count.

**The size check of every preview.** After the facts check, `media_stock.image_size` reads the width and height from the file's own header bytes (PNG IHDR; JPEG: the segments walked to the first SOF marker),
standard library only, through the safe open of the stock folder and its quarantine (regular file, no link, at most 16 MiB read). A candidate is dropped, counted in `dropped.preview`, when the header is not
understood, a side is under 1 or over 8192 px, or the area is over 40,000,000 px. Why: the renderer's contact sheet refuses the WHOLE sheet when one picture is over those limits
(`providers/renderer/renderer-presets.json`, `limits.asset_max_side` and `asset_max_pixels`), and the same limits refuse the picture at render time, so such a candidate could never be used and must not spoil the
others. With previews up to 16 MiB a very wide photo became likely. The constants `PREVIEW_MAX_SIDE` and `PREVIEW_MAX_PIXELS` of `runtime/media_stock.py` equal those limits and a test compares them.

**The disclosure.** `VID_WEB_PREVIEW` (en and pt-BR, keys unchanged) no longer says "small previews": it says a preview of each picture found, up to 16 MiB each. The comment of `videoMediaWebsearch` in
`interface/js/api.js`, the operation's help text, `docs/architecture/platform/short-video.md`, `runtime.md` and `contracts/runtime.md` say the same. The approved web-widening text is not touched.

**Not changed.** Licensed previews of `video-media-find` (a library's preview is small) keep their rules and get no size check. The pick still fetches its file again even when the preview was the file itself:
a possible later saving, not done.

**Verified.** Offline tests in `runtime/tests/test_media_websearch.py` (the three rows of the call, the 4 MiB cap of `preview` against the 16 MiB of the file preview, the size check with oversized, over-area and
truncated pictures and a JPEG with a large APP1 segment, the comparisons with the provider's caps and the renderer's limits) and `runtime/tests/test_media_image_size.py` (`image_size`: PNG, baseline and
progressive JPEG, a file that is not a JPEG, a link refused). Not verified: the live leg (a K4-style run of the web search on a real recording, which sends data off the machine), run later by the supervisor
after the maintainer's own yes.
