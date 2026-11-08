## 2026-11-08: the media routes of the page and limit L68 (V1b2-2; no measurement change, no skill changed, no lab run)

- Settled by the supervisor on the spec's recommendation (OPEN-1 to OPEN-11 of the V1b2 spec), not as the maintainer's word.
- The page reaches the eight media operations through one policy group, `media`, in no grant list: a page with no policy entry keeps its ceiling, and no messaging app or connected client can list it (V1d decides its own grant).
- The upload is a POST of the recording's bytes (video/mp4, video/quicktime or application/octet-stream, at most 1 GiB), read as a stream into the media store; every other POST stays JSON. The download is a GET streamed as an attachment named `video-<12 hex>.mp4`.
- VD18, kept by decision 14 for the local network: the upload, the still and the download are refused on the `--lan` socket before a byte is read or a file is opened (limit L68). The captions, the list and the starts may cross it: they are text and ids under the token, as the documents the page reads.
- `video-new` and `video-run` are jobs on the page (they run steps for minutes); they take no model slot.
- The handler's timeouts hold for a 1 GiB body: one read waits at most 30 s (the handler's socket timeout) and the whole body at most 1800 s (`intake.UPLOAD_MAX_SECONDS`); a stalled or dropped client is a 400 and the new recording folder is removed. Not measured on a real 1 GiB upload.
- A download is the operation's rehash from the descriptor it then streams: a file changed in place after that hash and during the send is not seen (the file is the store's own, mode 0600, written once at render).
