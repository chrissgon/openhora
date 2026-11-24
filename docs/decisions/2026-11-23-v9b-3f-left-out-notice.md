## 2026-11-23: the person is told what the render left out of the video (V9b-3f; spec `SPEC-video-V9b-3f`)

**The gap.** The renderer leaves beats and effects out of the timeline and said so in its render answer, but nothing reached the person: the render step kept `effects_dropped` and `pictures_dropped` in the step
result only, no card, page or document read them, and a beat dropped by the timeline was reported nowhere. After V9b-3e (the picture wins) a text highlight under a picture is dropped more often (three of four on
the live shape). The HyperFrames engine reported no beats at all. The maintainer asked whether the runtime should tell him when a text highlight is left out of the video, and answered:

> Sim, faça. (validate: allow english-only -- the maintainer's own words, quoted)

**What was built.**

- **Both engines report every dropped beat with a reason.** Closed list: `overlap` (a beat the neighbour pass cut to nothing, new), `under_picture`, `pip_no_room`, `split_no_room`. `beats_dropped_reasons`
  now covers every id of `beats_dropped` on the ffmpeg engine; the HyperFrames page stage returns `beats_dropped` and `beats_dropped_reasons` (only when non-empty), the host copies them into the render answer, and
  the `hf-page` schema of `providers/renderer/_docker.py` lists both.
- **One list for the person.** `runtime/step_media.py` reads the reasons as closed rows (an id of `beats.json` and a reason of the list; anything else, or an id twice, is `provider_output_invalid` on `render`)
  and builds `left_out`, rows `{id, kind, reason}` sorted by id: `picture` for a layout whose parameters name a picture handed to the render, `text` for any other beat, `effect` for a row of `effects_dropped`.
  It is written into `render.json` and the step result only when non-empty; no key of the step result was removed.
- **Where the person sees it.** The delivery document carries `left_out` as an optional key (checked: closed words, sorted, none twice, the reason of the kind's own list), and the decision shows it before the
  approval: one body line per row, `Left out of the video: <id>, <kind in words>, <reason in words>`, and one card line per row in the project's language. A render that left nothing out has the document, the
  body and the digest it always had (a test pins them against the earlier code's output).
- **Phrases.** The card line needs the kind and the reason said in the project's language, and a card line's values are never translated, so there is one phrase per kind and reason
  (`CARD_VIDEO_LEFT_OUT_<KIND>_<REASON>`, twelve in `runtime/phrases_parts/v9b-3f.*.json`), each with only the field `id`; the English phrase is the body line word for word (a test compares them).

**Rejected.** One phrase with fields `what` and `reason` holding closed words: the words would stay English on a Portuguese card. Putting the reasons into the effect summary only: the person reads the body and the card, not the summary.

**Verified.** Offline tests: `providers/renderer/tests/test_left_out_reasons.py` (the neighbour pass's reason, one reason per dropped id, the page result, the schema, the host), `runtime/tests/test_step_media_assets.py` (the list in the
record and the step result, a3 once as a picture, invalid rows refused) and `runtime/tests/test_deliver_card_lines.py` (card and body lines, the unchanged document, Portuguese). **Not verified:** a live render
through a container, and a phone card on a real messenger.
