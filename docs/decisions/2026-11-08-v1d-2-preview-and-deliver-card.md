## 2026-11-08: the preview and the deliver card on a messaging app (V1d-2; no measurement change, no skill changed, no lab run)

- Decision 14's preview is the render itself when it is at most 20 MiB: no second file and no renderer verb (no image rebuild). A larger render has no preview, so it is approved in the terminal or on the page.
- The bridge sends the preview as a video before the deliver card; the card offers its approval only after the provider confirmed the video in that chat, by the bridge's existing whole rule. An app that cannot be sent a video gets a card with no approval.
- The deliver decision carries its body as card lines (`CARD_VIDEO_*`), so a phone reads it in the project's language; the English body is byte-identical to V1b1's. The title is the fixed "Deliver the video" (the platform is the body's first line). The review's body no longer names the still's file, so it is said in the project's language too.
- Telegram sends a video by sendVideo, up to 20 MiB; two optional capability keys, `max_video_bytes` and `video_types`.
- Not measured: whether the app recompresses a video sent as a video; the preview is for looking, the approval is of the hash of the exact render.
- Departures accepted by the supervisor: the field of `CARD_VIDEO_PREVIEW` is `{origin}`, not `{from}` (the phrase test refuses the English word "from" in a Portuguese template); `ops_media_preview.KIND` is computed from `deliver_document.WORD` and a test compares it with `messaging_cards.effect_kind`; `messaging_preview.send` re-raises a `not-configured` error and the bridge turns it into `Fatal`, since the module cannot import the bridge.
- A test outside the spec's list changed: `providers/messenger/tests/test_telegram.py` pins the full capability key set, which gains the two keys.
