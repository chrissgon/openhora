## 2026-11-07: the caption review and the brand theme, ported (V1b1-2; no measurement change, no skill changed, no lab run)

- `runtime/captions.py` (the closed edits of the caption review, pure) and `runtime/theme.py` (the identity's closed brand-tokens block to the renderer's colour and font flags) are ported from the old short-video branch; their tests come with them.
- `theme_from_text` takes the identity as text, so the step kind reads `docs/brand/identity.md` with `steps.read_file` (no link, never the sources folder) and opens no file another way.
- `runtime/check_brand_tokens.py` is the adopted generated copy of `shared/scripts/check_brand_tokens.py`, kept identical by `scripts/sync_copies.py`.
