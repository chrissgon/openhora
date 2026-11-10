## 2026-11-10: the storyboard of a short-video post (V5-1; no measurement change, no skill changed, no lab run)

Package V5-1 of the video plan (VD14). It gives the verb `storyboard`, ported and tested on the ffmpeg engine since V0 but called by nothing, an operation that
the page and the terminal ask for one post, and a retention rule for what it draws.

### Decisions

- **D1. The storyboard is drawn by the ffmpeg engine for every project.** HyperFrames has no `storyboard` verb, and the ffmpeg image is the common image every
  HyperFrames project already builds. For a beat whose engine draws no block for the preset (HyperFrames: `cutaway`, `pip`) the result says so beat by beat
  (`video_block` is `null`); for a beat whose block differs it names both. Advisory, as VD14 says.
- **D2. It is asked for, never automatic.** One operation, `video-storyboard --post`, from the page and the terminal; no flow calls it and nothing waits on it.
- **D3. Replay by key.** The folder is `<data_dir>/media/storyboards/<key>/`, the key the first 16 hex of the sha256 of the post's bytes, the theme's flags and
  `blocks/pins.json`. The same key is returned without a call. The verb gives the same bytes for the same inputs, so the replay is the same answer, not a stale one.
- **D4. Retention by code, 30 days from the last use.** `upkeep.sweep_storyboards`, in the media part of the pass, by the folder's modification time, which each
  replay touches. The folder holds the stills of the script's own on-screen text (project data) and no recording and no transcript.
- **D5. Both operations may cross the LAN socket (VD18).** They are not in `operations.LAN_REFUSED_OPS`: there is no recording in what they serve.
- **D6. The draw is a job, asked with POST.** It can take minutes (the verb's timeout is 300 s) and starts a container, so the route answers 202 with a job as
  `video-new` does, and it is a `POST`, never a `GET`, because it changes state. `api.js` gains `videoStoryboard`, `permissions.js` gates it (`OPS`, `ASKED`) and
  the page asks `can` before it draws the control. The picture route is a raw `GET`, as the still's.
- **D7. Class G, kind internal.** Like the catalogue: not served in words. The oracle files that list every operation (`runtime/gated_ops.json` and the
  literal lists of the tests that read it, the media group, the routes and the row counts) got the two rows added, and no assertion was loosened.

### Saving and loss (principle 13)

- **Saved:** a person sees the beats of a script, with the block that will draw each, before recording, at the cost of one container run (a minute or so) the
  first time and nothing after, for a folder of a few PNGs.
- **Lost:** the drawing is not the video. It uses a neutral placeholder, the default face box and the ffmpeg engine's own blocks; a beat the project's engine
  draws differently is only named, never drawn. A theme the person has not finished (a draft identity) refuses the drawing, as it refuses `base`.

### Measured and not measured

- Measured: the operation, its post checks, the key, the replay, the engine named, the refusals' codes, the file route, the LAN rule and the retention, with the
  media kit's fake engine (`runtime/tests/test_media_storyboard.py`).
- Not measured: a real drawing in the container (the supervisor runs it), the page's look in a browser, and the demo copy (it has no engine and says so).
