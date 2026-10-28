## 2026-10-28: the third batch regenerates the platform blocks (BATCH-KEEPER regen 3; no model call, no lab run, fingerprint unchanged)

After the merges since regen 2 (CB-6, L64H and RESEARCH-NO-DOCKER among them), two generated blocks of `docs/architecture/platform/` differed from their sources: `provider-classes` (`providers.md`) and `limits` (`runtime.md`). `python3 scripts/architecture_tables.py --write` rewrote them, and `--check` is clean afterwards. `python3 scripts/owner_table.py --check` found the table of owning skills current, so it was not rewritten. The commit holds only the regenerated output and this entry.

Principle 13: as for regen 1 and 2, a batch pays for the regeneration once per group of merges and lets a package's own pull request leave the blocks alone; the loss is a block that can be stale on the integration branch between batches, which the strict mode on a batch closes.
