## 2026-11-07: the deliver effect kind (V1b1-3; no measurement change, no skill changed, no lab run)

- `deliver` joins the closed side-effect vocabulary as a runtime-only word (`scripts/validate.py` `RUNTIME_ONLY_EFFECTS`, `contracts/environment.md`): no skill declares it, so no skill is bumped. It is placed before `write`, so the tests that pin the ends of both tuples hold.
- `runtime/effect_deliver.py` executes it: approving the document's hash marks that exact render downloadable, after hashing the file again; a changed render is answered by code and rendered again for a new approval (limit L67). No provider is called and nothing is published.
- It is approvable on the terminal and the loopback page; on a messaging app only under decision 14's grant; never on the MCP mode; an approval arriving on the `--lan` socket is refused in `runtime/service.py`, the one place that knows the socket, before any configuration check.
- Saving: the step engine is not edited, as V0 required. Loss: none; the LAN rule is a check of the service and not of the operations layer, which cannot tell the two sockets apart.
- Numbering note: the limit is L67 as the spec assigned it; L66 is not in `contracts/runtime.md` on this branch, and the tests that list the limits (`runtime/tests/expected/v1b1-3.json`) add 67 only.
