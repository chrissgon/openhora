## 2026-10-28: the sixth batch regenerates the platform blocks (BATCH-KEEPER regen 6; no model call, no lab run, fingerprint unchanged)

After the merges since regen 5 (T6 and CB-9 among them), two generated blocks of `docs/architecture/platform/runtime.md` differed from their sources: `runtime-modules` and `limits`. `python3 scripts/architecture_tables.py --write` rewrote them, and `--check` is clean afterwards. `python3 scripts/owner_table.py --check` found the table of owning skills current, so it was not rewritten. The commit holds only the regenerated output and this entry.

Principle 13: as for the earlier batches, one regeneration per group of merges lets a package's own pull request leave the blocks alone; the loss is a block that can be stale on the integration branch between batches, which the strict mode on a batch closes.
