## 2026-10-29: the batch regenerates the platform blocks after S41-11 PR 2a and 2b (BATCH-KEEPER; no model call, no lab run, fingerprint unchanged)

After S41-11 PR 2a (#648) and PR 2b (#649) merged, one generated block of `docs/architecture/platform/runtime.md` differed from its source: the `limits` block (row L63). `python3 scripts/architecture_tables.py --write` rewrote it, and `--check` is clean afterwards. `python3 runtime/tests/phrase_snapshot.py --write` rewrote both snapshot files and left them unchanged (PR 2a had already regenerated them), and the strict check passes. `python3 scripts/owner_table.py --check` found the table of owning skills current. The commit holds only the regenerated output and this entry.

Principle 13: as for the earlier batches, one regeneration per group of merges lets a package's own pull request leave the blocks alone; the loss is a block that can be stale on the integration branch between batches, which the strict mode on a batch closes.
