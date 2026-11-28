## 2026-11-28: The office is built in interface/ from parts, not a fork of Habblaud (office1; R23, 10c, O1 to O4)

**Decision.** The agent office is a screen of the static `interface/`, built from small permissive parts, not a fork of Habblaud (decision 10c; R23, chrissgon/openhora#884, and AC10, chrissgon/openhora#999). Slice 1 is `#/p/<id>/office`: one room, the agents of the store, the waiting count first, a placeholder figure. Habblaud was not forked because it has a build step (the page here has none), its comments are not in English, its World service is on by default and it has one main author. What it was adopted for is one part, the path finder.

**Parts adopted, per need.**

| Need | Part | Source | Commit | Licence | Notice |
|---|---|---|---|---|---|
| walk grid and path finding | the walk grid and the 4-direction A* | Habblaud, `client/src/world/path/grid.ts` and `astar.ts` | `faa1a012b5fbf632c66dc6801c5383e53a542406` | MIT | header of `interface/js/office/astar.js` and the "Ported code" list of `interface/README.md` |

The port strips the TypeScript, translates every comment to English and changes no logic; the test file runs the cases of its source, translated.

**Rules kept.** No build step, no package, no URL or host in any file, relative imports only, text from the service by `textContent`, positions only through custom properties, tokens only in the stylesheet, no 3D module, and no client call: the office reads the snapshot the page already holds. It never approves, answers, rejects or sends: a figure or row only moves the hash to a waiting row's link or an agent's floor (step 2, need 7).

**Options not built.** Server-sent events and a long poll for live state. The page keeps the change signal it has (`GET /versions` every second, a reload when a number moves) and a later events read (AC4) feeds "doing now"; step 2 measured the latencies of both options, so AC4 can reopen them with those numbers (O4).

**The waiting count.** It is the project's open decisions, the rows of "Waiting for you", not the agents that wait. Step 2's fixture: four decisions (a plan of the planning agent, an effect of engineering, an effect and a question of marketing) and one waiting agent (marketing) show "4 decisions waiting for you", and the test holds it.

**O1 to O4.** O1: "doing now" will be the kind of step only, and slice 1 shows none (there is no events read before AC4). O2: words come from a lookup that takes the project's language setting; only the English table exists until the dictionary of slice 7. O3: one room for each area, later (slice 1 has one room for all areas). O4: poll the change signal each second plus an events read, no SSE.

**Art.** The figures are placeholders (a body and a head in the agent's hue). The maintainer is asked again before any art is chosen; none is chosen here.

**Later slices.** Rooms for each area and floors, the layout editor and its route, meters, columns and the feed, the events route (AC4), the card in a drawer, the art, the Portuguese dictionary, and then the retirement of the 3D scene and `vendor/three/` (slice 8). Nothing of those is built by this package, and the 3D screens are unchanged.
