## 2026-10-30: the batch regenerates the platform blocks after 44-C3 (BATCH-KEEPER; no model call, no lab run, fingerprint unchanged)

After 44-C3 merged, one generated block of `docs/architecture/platform/runtime.md` differed from its source: the `runtime-modules` block, which needed one new row for `runtime/ops_requests.py`. `python3 scripts/architecture_tables.py --write` rewrote it, and `--check` is clean afterwards. `python3 runtime/tests/phrase_snapshot.py --write` rewrote both snapshot files and left them unchanged. The commit holds only the regenerated output and this entry.

Principle 13: as for the earlier batches, one regeneration per group of merges lets a package's own pull request leave the blocks alone; the loss is a block that can be stale on the integration branch between batches, which the strict mode on a batch closes.
