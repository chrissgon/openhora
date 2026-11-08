## 2026-11-08: the caption review on the page and "Add an animation" (V1c-2; no measurement change, no skill changed, no lab run)

- A dialog (`interface/js/views/lobby-captions.js`) reads the captions of a new video and sends one closed edit at a time: a word, a merge, a removal, a retake, a beat's anchor or overlay, an animation removed or added. The face box, the cover, the theme and a slot stay in the terminal.
- "Add an animation" shows the catalogue: the addable blocks with when to use them and a sample as text; the others with why they cannot be added. No animation is drawn as a preview on the page (V1b3 OPEN-10).
- At the review, Continue answers the review decision `continue` and runs the video; at the delivery card an edit answers it by code and the page offers Render again.
- A stale revision is read again and said; nothing is retried by itself.
