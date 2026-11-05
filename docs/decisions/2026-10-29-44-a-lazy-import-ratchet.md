## 2026-10-29: a ratchet on the lazy imports of the runtime (44-A, PLAN-BRAIN section 4.4; no model call, no provider call, no lab run, fingerprint unchanged)

`runtime/tests/test_import_breakers.py` reads every module of `runtime/` and `runtime/handlers/` by AST and finds the lazy edges: a function, method or lambda of a module that calls `importlib.import_module("<runtime module>")` with a constant name, or holds an `import` or `from ... import` statement of one. It fixes the number of lazy calls and of distinct edges, and lists every edge in `ALLOWED_LAZY` with its reason. Tests only; no product code changed.

**The numbers on this tip (34102d10, after S41-11 PR 2b), and the spec's (3afee52b), which did not hold:**

| | Spec (3afee52b) | This tip |
|---|---|---|
| lazy calls | 160 `import_module` + 32 statements = 192 | 236 (204 `import_module` + 32 statements) |
| distinct lazy edges | 140 | 172, in 53 modules |
| edges that can become top-level imports | "about 97" (a greedy pass in file order) | 137 on their own; 120 by the same greedy pass in sorted order |
| edges that cannot | 43 | 35 forced by a cycle on their own; 52 by the greedy pass |
| edges to `ops` | 12 | 14 (`dispatcher`, `ops_ask`, `ops_cancel`, `ops_card_revise`, `ops_contained`, `ops_event_revise`, `ops_file_ask`, `ops_instructions`, `ops_natural`, `ops_natural_writes`, `ops_reads`, `ops_research`, `ops_runs`, `ops_say`); 12 forced, 2 not (`ops_natural_writes`, `ops_event_revise`) |
| largest strongly connected component | 68 modules | 67 |
| cycles among top-level imports alone | none | none |

The spec's counts were taken at 3afee52b and 58 commits older; the code gained lazy edges since. The greedy count depends on the order of the edges, so the ratchet does not use it: an edge is *forced by a cycle* when its target already reaches its module through top-level imports, tested on each edge alone. Under that rule 137 edges close no cycle on their own (some of them conflict with each other, which is why the greedy count is lower). 11 dynamic `import_module(<variable>)` calls (the registries) and the scripts loaded by path are not edges and not counted.

**The ratchet.** `LAZY_CALLS_BUDGET = 236`, `LAZY_EDGES_BUDGET = 172`, `PLAIN_DEBT_BUDGET = 137`; nothing raises a number without a reason written beside it, and 44-B and 44-C lower them. Each reason starts with its kind: `cycle:` (checked against the graph: on an edge that closes no cycle the test fails with "make it a top-level import"), `debt:` (closes no cycle today; 44-B converts it or writes the `light-start:` reason it stays lazy; the debt edges are capped), `light-start:`. A forced edge tagged `debt:` fails. The reasons are written by module and kind, in rows, not edge by edge: the spec allowed the grouping, and the 44-B and 44-C packages sharpen them as they touch a cluster.

**Deviation from the spec's rule 3.** The spec says an edge that closes no cycle fails. On this tip 137 of them exist, so the rule is a ratchet on them (`PLAIN_DEBT_BUDGET`) and fails outright for a new edge that is not listed, which is the spec's rule for every edge from here on; 44-B takes the debt to zero or to a stated `light-start:` reason.

**Vacuity.** The reader is checked on a planted tree of every form (top-level, `try`, class body, method, lambda, a variable name, a string that is no module); each rule is checked on a planted tree of two modules (a lazy import of a leaf fails rule 3, a cycle edge needs a `cycle:` reason, a wrong kind, an unlisted edge, a listed edge that is gone, an extra call over the budget all fail); and the real tree plus one planted extra edge fails the listing and both budgets.
