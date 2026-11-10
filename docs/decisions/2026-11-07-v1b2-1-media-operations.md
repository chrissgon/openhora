## 2026-11-07: the media operations and the media settings key (V1b2-1; no measurement change, no skill changed, no lab run)

- Settled by the supervisor on the spec's recommendation (OPEN-1 to OPEN-11 of the V1b2 spec), not as the maintainer's word.
- `runtime/ops_media.py` holds the eight operations of a new video: `media-in`, `media-list`, `video-new`, `video-run`, `captions-read`, `captions-edit`, `video-download`, `video-still`. The operations layer checks every rule; the shells carry.
- `video-new` makes one request with one step task of the kind `media` (no plan, as `runtime/account_start.py` does for an account write) and runs it to the caption review; the flow `new-video` stays the generic path. The task's title and text are the flow's.
- `video-run` is the person's own start of a ready video, for the media kind alone: `run-step` stays terminal-only, because it runs any step kind.
- The rows are class G, kind `internal`, catalog version 4: never served in words in M1, so the served catalog and its hash do not move. Serving one in words is a later, measured change of the catalog.
- A video or a still is written only to a new file outside the project (VD8, decision 12: a video never enters git). The download hashes the render again from the descriptor it copies from (limit L67).
- `runtime.json` gains the key `media` (`language`, `transcriber_model`, each optional). The defaults stay the step kind's: `small` and `pt` (the maintainer's word, 2026-11-07).
- Phrases: `TITLE_VIDEO_MAKE` and `TITLE_VIDEO_REVIEW` (en, pt-BR). The review's body and the deliver title cannot be matched by the phrase table's matchers (whole numbers only in a field); their words on a phone are V1d's.
- The quota refusal of the media store says "a recording must be removed first", and no operation removes a recording yet (`media-remove` is a later package, OPEN-9). `runtime/media.py` is not edited here; `ops_media` rewords the refusal when it shows it (the store is full, no operation removes a recording yet, the 30-day retention frees one that was never delivered, the folder is `media/` in the project's data folder). The code `(quota)` still ends the sentence.
- Not done here: the page (V1b2-2), the removal of one recording, asset slots, "Add an animation" (VD15, its own package V1b3), the messaging path (V1d).
