## 2026-10-28: GPT-6 Luna is enabled as the outage route of the interpreter, on the maintainer's decision (LUNA-ENABLE; no model call, no provider call, no lab run in this entry, fingerprint unchanged)

This entry records two decisions of the maintainer, the rule that judged the measurement, the measurement itself (raw figures and hand-read figures side by side, principle 10), and the one change it makes: a new newest entry in `runtime/interpreter_enable.json` whose `fallback` names the route `or-gpt-6-luna`. Nothing was re-run for this entry. The figures come from two recorded events whose evidence lines are committed with it, byte for byte, in `evals/interpreter/evidence/`.

### The maintainer's decisions of 2026-10-28

Both were given in chat in Portuguese and are translated here from Portuguese.

1. "Yes: enable GPT-6 Luna as the fallback route, with the dated decision and the raw and hand-read figures side by side." (Portuguese: "Sim: ative o GPT-6 Luna como rota de reserva, com a decisão datada e os números brutos e lidos à mão lado a lado.") validate: allow english-only -- the maintainer's own words, quoted
2. On the condition set on 2026-10-26, zero retention confirmed in writing before any use, he chose "I accept the OpenRouter page" (Portuguese: "Aceito a página do OpenRouter"). He accepts OpenRouter's zero-data-retention page, which lists `openai/gpt-6-luna` on Azure among the endpoints with a zero-data-retention policy (read 2026-10-26), as the written evidence. **Azure's own written terms were not checked.** The sentence that said nothing is sent to this route before the maintainer accepts that evidence is replaced, in the `retention` text of the row `or-gpt-6-luna` in `runtime/interpreter_routes.json`, by one that says he accepted the page on 2026-10-28 and that Azure's own terms were not checked. The text is what a person is shown when they widen the group `interpret-fallback`. `retention` is not part of the route's hash (`interpreter_route.stdin_route` hashes the id, address, model, pin, `allow_fallbacks`, `data_collection`, `zdr`, `cache_breakpoint`, and `pin_reply` and `reasoning_off` when present), so the row's hash is unchanged, `e029d4a761ad82cdd1668536362313afc91b9082556188e9999313f932146e8f`, the one Luna was measured with. validate: allow english-only -- the maintainer's own words, quoted

### What the entry does and does not do

- It adds one entry dated 2026-10-28 (basis `maintainer-decision`) that copies every pin of the previous newest entry (the CB-9 entry: route, route hash, prompt, catalog, protocol, the six languages, the e-mail compose and revise prompts) and adds `fallback: [{route: or-gpt-6-luna, route_sha256: e029d4a7..., measured: ...}]`. Before the entry was written, the served catalog (`160f0831...`), the prompt (`3112db68...`), the protocol (`2a6f7f19...`) and the Luna row's hash on this branch's tip were each compared to what Luna was measured on: all equal.
- The mechanism is the one S41-10 built and is not changed: a sender's lines reach the second company only when the sender widened the group `interpret-fallback` (in no default, valid only beside `interpret`) and their consent record covers that company, and only after an outage of the daily route (`E_TIMEOUT`, `E_NETWORK`, `E_RATE`, `E_UPSTREAM`) or with its breaker open, inside what is left of the line's deadline. A model that wrongly reads a line can still only open a card the person approves.
- The other fallback row (`or-gemini-3.5-flash-lite`) is not named and stays off.
- Turning it off is a new dated entry without `fallback`, or a change of the row's hash.

### The rule, chosen before the figure

The absolute rules of the full step (the bars of `evals/interpreter/thresholds.json` per language, with Wilson upper bounds of 0.02 over 800 items) fail the primary on its own `ix-test-v1` evidence from 2026-10-21, so they cannot judge a fallback. Before the primary's figure at the same hashes existed, the maintainer chose to judge the fallback **relative to the primary at the same hashes**:

1. hard rule: `wrong_effect_unconfirmed` = 0;
2. `wrong_card` read by hand (the flagged items re-traced as the product would act on the model's answer);
3. `correct_direct` at most 10 points below the primary, in pt-BR and en.

The primary was then measured at the same hashes as Luna (catalog `160f0831`, prompt `3112db68`, protocol `2a6f7f19`, harness `5e8dd68d`, thresholds `2b15b94c`), so the comparison is like for like.

### The figures

Common to every figure: measurement of the interpreter's full step (the held-out split `ix-test-v1`, 800 items, `corpus_sha256` `f82837d7...`, the bytes of `test-split.json`), the harness `5e8dd68d...`, prompt `3112db68...`, catalog `160f0831...`, protocol `2a6f7f19...`, thresholds `2b15b94c...`, taxonomy `72d02a19...`, 2 runs per item, an item taken at the worst of its 2 runs, run on 2026-10-28 by the maintainer, 1,512 live model calls for each route. Models: `openrouter/openai/gpt-6-luna` (route `or-gpt-6-luna`, row hash `e029d4a7...`, pinned to Azure, event `20261028T201315Z-daa387c8`) and `openrouter/deepseek/deepseek-v4.1-flash` (route `or-deepseek-v4.1-flash`, row hash `1365ea7c...`, event `20261028T214447Z-751dcc45`). **Provenance can be checked:** both events' evidence lines are committed in `evals/interpreter/evidence/` (the file names are the event ids with the prefix `ix-`), they pass the validator of `evals/interpreter_status.py`, and every count below can be recomputed from them (the per-item worst-of-2 of the `category` of each item line). The raw answers of the two sittings and their summary files are not committed.

**Raw (the harness's own scoring), `correct_direct` and clarify rate, primary against Luna:**

| Language | Items | Primary | Luna | Luna minus primary (`correct_direct`) |
|---|---|---|---|---|
| pt-BR | 280 | 0.849; clarify 0.084 | 0.773; clarify 0.143 | -7.6 points |
| en | 210 | 0.860; clarify 0.119 | 0.767; clarify 0.155 | -9.3 points |
| es | 124 | 0.746; clarify 0.202 | 0.684; clarify 0.237 | -6.1 points |
| de | 62 | 0.782; clarify 0.182 | 0.655; clarify 0.291 | -12.7 points (outside the rule's languages) |
| fr | 62 | 0.849; clarify 0.132 | 0.811; clarify 0.132 | -3.8 points |
| it | 62 | 0.807; clarify 0.175 | 0.754; clarify 0.193 | -5.3 points |
| all | 800 | 0.827; clarify 0.130 | 0.750; clarify 0.176 | -7.7 points |

**Raw wrong counts, items at their worst of 2 runs, primary / Luna:** `wrong_card` 22 / 15; `wrong_read` 12 / 12; `wrong_route` 0 / 14; `wrong_item_binding` 1 / 5; `wrong_reminder_reading` 6 / 1; `wrong_effect_unconfirmed` 0 / 0. Luna had 7 timeouts in 1,512 calls (0.46 per cent), each of which ends in the path a line takes when no fallback exists, and 34 runs (2.3 per cent) that did not parse, 32 of them a provider-side refusal to read a line that carries an injected instruction (the product never follows the text; the line gets a question).

**Against the rule:**

| Rule | Result | Verdict |
|---|---|---|
| 1, `wrong_effect_unconfirmed` = 0 | primary 0, Luna 0 | met |
| 2, `wrong_card` read by hand | Luna 4 of 800 items (Wilson upper bound 0.013), all four confirmable cards, none an effect without approval | met |
| 3, `correct_direct` at most 10 points below the primary in pt-BR and en | pt-BR -7.6, en -9.3 | met (en with 0.7 points to spare) |

**Hand-read.** Of Luna's 15 raw `wrong_card` items, 6 cannot occur on a fallback line, 4 are correct (3 scorer artifacts and 1 stale gold), 1 ends in a refusal sentence with no card, and 4 are real cards: three defensible event cards and one mail card with a dropped second intent. All four are cards the person confirms. The hand reading is one-sided by construction: it can only lower a `wrong_card`. The primary's 22 raw `wrong_card` items were not hand-read in this entry. Luna also gives up more than the primary: about 23 per cent of the lines that should be answered directly become a question or a miss (of its 125 clarify runs in pt-BR and en, 62 are an invalid answer, either unparsed or rejected by the check), which the product turns into a question and not into an action. That 23 per cent and the 62 come from the analysis of the sitting, which this entry did not redo.

**Not hand-read.** Luna's 14 `wrong_route`, 5 `wrong_item_binding`, 12 `wrong_read` and 15 `missed` items were not read by hand. With `wrong_effect_unconfirmed` 0, a wrong route ends in a question or in a card the person confirms; this is the harness's category and no trace of those items was made.

**Not verified.**
- Azure's own written terms for this use. The maintainer's acceptance rests on OpenRouter's statement that the endpoint has a zero-data-retention policy, which code cannot check.
- The gaps just named: the hand reading covers Luna's 15 raw `wrong_card` items only.
- No end-to-end replay through the messaging turn was run for the hand-read items; the traces called the functions with the recorded texts.
- Half the calls carry no price (a call with a cache write has none), so the cost figure is not a decided measure and is not used here; the latency p95 of the evidence lines of a run made one call at a time is not a decided measure either.
- German is 12.7 points below the primary; the rule names pt-BR and en only.
- The primary at this catalog scores 0.860 in en against 0.902 at the earlier catalog on 2026-10-21 (not like for like); it does not change this decision and is noted for the follow-ups of CB-9.

### What the interpreter's status script shows after this entry

`python3 evals/interpreter_status.py status` reads the two committed events as events of the current set (route, prompt, protocol, catalog and thresholds equal the checkout's) and says, for both routes and every language, `needs a run: no sequential run`, because the full step was run with `sequential` false. No band moves. The band of the daily route is not changed by this decision, and the outage route's band stays `needs a run`: the enabling is the maintainer's decision, not a band.
