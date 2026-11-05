# entry_ext/: the scenarios of the packages for the entry replay

The base corpus and golden (`../entry_corpus.jsonl`, `../entry_golden.jsonl`) are closed. A package that adds scenarios writes `<id>.scenarios.jsonl` here: one scenario per line, the corpus keys in the
corpus order, every id starting with `<id>.`, an optional `model_text` (the stand-in model's answer to that scenario's text; the same text carries the same `model_text`).
Then it records `<id>.golden.jsonl` with `entry_corpus_build.py --record-package <id>` (a header with `package`, `commit`, `scenarios_sha256`, `overrides_sha256`, `count`, then `{id, outcome}` in the file's order).
The replay reads the base and every package; a recorded row changes only as a reviewed decision. `--record-added` is refused: the base golden is closed.

These files are Portuguese on purpose and need no line in `.security-scan-allow`: the `english-only` check of `scripts/validate.py` exempts every `runtime/tests/entry_ext/*.jsonl` by rule (so two packages never conflict on that file). The base corpus and golden keep their own lines.
