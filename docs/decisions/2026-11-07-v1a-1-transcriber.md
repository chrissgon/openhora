## 2026-11-07: the speech transcriber on the shared container box (V1a-1; no measurement change, no skill changed, no lab run)

- `transcriber:speech` is served by `providers/transcriber/whispercpp.py`, ported from the old short-video branch. It is a class the
  runtime uses and no skill requires (VD2), so `contracts/environment.md` does not list it.
- Its container lifecycle and limits are `providers/_container.py`'s (VD4). The provider keeps its own function names as wrappers, so its
  tests are the old branch's, unchanged. `scripts/tests/test_provider_container.py` already proved the box writes the same command.
- `scripts/doctor.py` names the module of each image family, because the transcriber's image is defined in `whispercpp.py`, not in a
  `container.py` (a file of that name in a class folder would be an implementation of the class).
- The whisper.cpp model is never part of the image: the person places it in the models folder; the image is built only by
  `build --confirmed`. Saving: no download in this package. Loss: none.
