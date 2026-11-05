## 2026-10-30: the batch regenerates the platform blocks after 44-C4a (BATCH-KEEPER; no model call, no lab run, fingerprint unchanged)

After 44-C4a (#666) merged, one generated block of `docs/architecture/platform/runtime.md` differed from its source: the `runtime-modules` block, which needed one new row for `runtime/ops_task_run.py`. `python3 scripts/architecture_tables.py --write` rewrote it, and `--check` is clean afterwards, also with `WB_GENERATED_BLOCKS=strict`. `python3 runtime/tests/phrase_snapshot.py --write` left both snapshot files unchanged.

The same commit fixes a citation found in the review of #666: the gate that turns a run's effect into a pending approval is limits L15 (the effect is executed by code with the approved content) and L16 (a skill runs up to its gate), while L17 is only "the approval lives in the approvals table". The module text of `runtime/ops_task_run.py` and the docstring of `runtime/tests/test_gate_hash_chain.py` now cite L15 and L16. Comment and docstring text only; no code and no test name changed.

Principle 13: as for the earlier batches, one regeneration per group of merges lets a package's own pull request leave the blocks alone; the loss is a block that can be stale on the integration branch between batches, which the strict mode on a batch closes.
