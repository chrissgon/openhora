## 2026-11-08: the renderer's preview verb, a copy of a delivered render small enough for a phone (V3d; no measurement change, no skill changed, no lab run)

- A render larger than 15 MiB gets a copy that fits from a new common verb `preview` of the renderer: 720x1280 H.264 at CRF 23, capped by
  a rate computed from the render's length (60 s: 1843 kbit/s, 300 s: 296 kbit/s), AAC 96 kbit/s, its index first, at most 15 MiB, named
  by its own hash, made in the container from the render mounted read-only and re-hashed by the host. A render up to 15 MiB stays its own
  preview (V1d-2), so the renderer is not asked.
- The limit moved from 20 MiB to 15 MiB (`deliver_document.PREVIEW_MAX_BYTES` = `renderer-presets.json` `preview.max_bytes`): under
  Telegram's 20 MiB and under WhatsApp-through-Twilio's 16 MB read as either 16,000,000 bytes or 16 MiB, with room for the container.
- One pass with a capped CRF, not two passes: one thread makes it deterministic, and the cap already holds the size (measured on synthetic
  test patterns with a local ffmpeg: 60 s gave 14,101,201 bytes in 21 s; 300 s gave 15,053,020 bytes in 72 s; the same sha256 twice).
  Preset medium, not veryfast: 21 s against 9 s for 60 s, for a better picture at the same cap.
- The runtime asks for it in a side step `preview` between `verify` and `document`: a failure never fails the task, and the document then
  has no preview, so the delivery is approved in the terminal or on the page, as for a large render before.
- The preview goes with the recording 7 days after the delivery; it is never delivered, downloaded or approved: the approval stays the
  sha256 of the exact render (L67, unchanged).
- The image definition changed (three listed files; no file added and no new download), so the image tag changed: the image is built
  again, by CI's renderer job and on the maintainer's machine from the same pins.
- Not measured: the image's own ffmpeg (a Debian snapshot build, not the local 9.0.2 the figures came from); a real recording; how the
  messaging apps show the copy.
