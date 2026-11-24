## 2026-11-24: the media consent key (P6; VD17; spec SPEC-video-P6-consent-key)

**VD17 is built.** "A per-project consent key in `runtime.json`, off by default, accepted with `accept-config` and checked by code, is required before a transcript reaches a model or a hosted service" (decision of 2026-11-07, `v0-short-video-hyperframes`) had never been built. P6 builds it as a widening item of the kind `media.references` and `media.stock` already are, and ships the one check every sender calls (`runtime/ops_media_consent.py` `require`), wired into the two paths that send recording-derived data out today. Limit L81.

**The key.** `media.consent` is a list of up to four different words of a closed tuple (`project_config.MEDIA_CONSENT_WORDS`): `transcript`, `intonation`, `published-frames`, `render-ocr`. Absent or `[]` is off. Each listed word is its own widening item (place `media-consent`, group `media-consent=<word>@<terms version>`), carried by the record `config:accounts` and the hash `accept-config --widen` takes. A change of a word's terms raises its version and the item is listed again; until it is accepted again `require` refuses that word. A project without the key has the same items, widening list and hash as before (tested).

**The words and their terms (version 1; draft until the maintainer approves the text, STOP A).** The service is named by its role, not by company, because the model of a run is chosen per run (named, or `auto`).
- `transcript`: the words of the recordings, with the time of each word and of each pause, go to the model service that runs a video's task and to the company that serves that model; no sound and no picture is sent.
- `intonation`: how each part is said, measured on this computer as words and numbers, goes with the transcript to the same service; no sound is sent.
- `published-frames`: still pictures of videos already published go to a model service that reads images, to be labelled from a fixed list of words; never a picture of a recording that is not published.
- `render-ocr`: the text read from the frames of a rendered video, its captions included, goes to the model service that explains what the scan found; never a picture.

**D2 made structural.** "No audio and no recording frames reach a model": the closed list has no word for audio or for a frame of a recording, and `require` raises `ValueError` for any word outside `MODEL_WORDS + MESSAGING_WORDS`. Adding such a word is a code change and a decision, never a configuration.

**The inventory at the base commit (`6ca49fc0`), the senders of recording-derived data.**

| # | Path | What leaves | To | Gated by |
|---|---|---|---|---|
| S1 | `runtime/ops_media_phone.py` `_caption_text`, called by `video_phone_start`, `video_phone_reply`, `video_phone_run`; sent by `runtime/messaging_video.py` | the caption words (the transcript) as text | the messaging app's servers | the sender's profile holds `media-phone`; now also `require(["messaging-captions"])` |
| S2 | `runtime/ops_media_preview.py` `video_preview`; sent by `runtime/messaging_preview.py` | the preview of the render, captions drawn in | the messaging app's servers | the sender's profile covers `approve` of `effect:deliver`; now also `require(["messaging-preview"])` |

Checked and not senders: the transcriber is local whisper.cpp in a container; no transcript reaches a model (no module that touches the transcript calls the model class, and the renderer runs offline); stock and open-web search send the search words of a slot, which are words typed for it, consented by the `stock=` items (when P8's agent writes search words from the transcript, P8 calls `require` with `transcript`); the delivery document and its card hold no caption text; `video-watch`, `video-download`, the storyboard and the caption review are local; a plain line a sender types may reach the interpreter's model under the `interpret` group, which is the person's own words and not recording-derived. VD5 stands: a hosted transcriber would need a consent word of its own.

**D10.** The grant `media-phone` is the VD17 consent for the caption words on a messaging app: its shown text (`operations.GROUP_TEXT["media-phone"]`, used because `GRANT_TEXT` has no `messaging:media-phone` key) names what is sent (the captions) and the service (the app's servers), which is the condition v3 put on D10. The maintainer's answer: "Sim, conta" (validate: allow english-only -- the maintainer's own words, quoted). The text does not say what the app keeps; left as it is unless he asks.

**STOP B (open: the maintainer decides before the merge).** Does the grant `approve-effect-deliver` count as the consent for the preview of a delivery on a messaging app? Its shown text says "the recording and the preview pass through the messaging provider's servers". Built as recommended: yes, as it is, which changes no behaviour. The alternative (also require `media-phone`) would stop a phone approver without `media-phone` from receiving the preview of a video started on the page; if he chooses it, only rule 4 of `require`, its test and the docs change.

**Callers to come.** P7 calls `require` with `published-frames`; P8 with `transcript` and `intonation` (and `transcript` again if its agent writes search words); P9-b's explaining skill with `render-ocr` (R3-24).

**Where code cannot enforce it.** The check is code; the obligation to call it is not. A new sender that forgets the call is caught by the `SENDERS` test only when it calls `require` somewhere (the test reads every `runtime/*.py` and compares the calls with `SENDERS`), and otherwise by review (principle 11).

**Verified.** The widening pattern was copied from `references` and `stock`; the new tests (`runtime/tests/test_media_consent.py`, plus cases in `test_media_config.py`) cover the configuration, the items, a raised terms version, the unchanged answers for a project without the key, the end to end acceptance, `require` for each kind of word, the closed list, both senders and the inventory.

**Not verified.** Nothing real was sent. That the inventory is complete beyond a reading of the code and a search (a path built dynamically could hide). The final terms (STOP A) and the preview rule (STOP B) await the maintainer.
