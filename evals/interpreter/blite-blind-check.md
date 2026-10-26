# blite-blind-v1: independent gold check

Set: `evals/interpreter/blite-blind-v1.jsonl`, sha256 `0912d128...dc4d` (checked, unchanged; the set was not written to).
Read against: the set's README (rule B1, gold rules, debatable calls), clone 764c9a3 `evals/interpreter/README.md` (L1-L10), `runtime/interpreter_catalog.json`, `runtime/interpreter_prompt.txt` (rule 9 and examples), `contracts/runtime.md` rows L54, L61, L63-L65, `runtime/interpreter_score.py` (exact slot set; span values compared by `natural.normal`, so case, accents, quotes and punctuation do not matter).
Offline checks run: `scripts/interpreter_corpus.py check` gives 60 items, 0 problems; every gold moment recomputed (date and weekday from the clock and zone): all 10 correct; a scan for missing left-widenings over every span value, then read by hand.

## Findings

| Item | Severity | Problem | Rule | Proposed fix |
|---|---|---|---|---|
| test-de-60004 | missing alternative | `text` lists "die Pflanzen von Frau Kesselbach zu gießen" and "daran, die Pflanzen ..." but not the core. The shortest piece holding every content word starts at "Pflanzen"; "die" is an article (a left widening), not part of the core. Every other item lists its article-free core (e.g. pt-BR-60015 "buscar o terno ...", en-60001 "call with ..."). | B1.1, B1.2 | add "Pflanzen von Frau Kesselbach zu gießen" to `text` |
| test-en-60009 | missing alternative | `question` lists "whether the Harborview ferry ..." and "the Harborview ferry ..." but not "Harborview ferry is running this Sunday". "the" does not say what to find out; rule 6 then applies rule 2, so the article-free form is the core. The set's other research items list their article-free form (en-60012, fr-60003, pt-BR-60017, pt-BR-60030). | B1.6, B1.2 | add "Harborview ferry is running this Sunday" to `question` |
| test-en-60005 | missing alternative (unlikely output) | `target` lists "the email from Gideon Farrow ..." but not "to the email from ...". Rule 3 accepts the family noun with its own function words "(rule 2 again)": up to two, and "to the" stand immediately left of "email". The set does this in es-60002 ("al correo de Ignacio Bermejal", after "Responde"). | B1.3, B1.2 | add "to the email from Gideon Farrow about the warehouse lease" to `target` |
| test-pt-br-60030 | style (README wording) | Rule 6 says the question runs "to the last place or day word". The line's last place word is "Morro Azul", in the negated tail "não em Morro Azul". The gold rightly stops at "Vila Esmeralda", so the gold is right and the rule's wording is loose. | B1.6 | no gold change; in the v2 README, say "the last place or day word of the question asked (not of a clause that rejects a value)" |
| test-pt-br-60003 | style | `also: clarify` is not required by L5 ("next with a weekday": list both moments, which the gold does). It is allowed ("also, sparingly") and the README states it, so it stays. It only makes the item more lenient. | L5, item `also` rule | none required; keep, or drop the also in v2 if the maintainer wants L5 applied to the letter |
| test-pt-br-60005 | style (tag) | It is tagged `typo`, but the only candidate is "to" for "tô", which is a missing accent or a colloquial spelling, not a typo. Tags are not scored, only reported by tag. | tag list | retag `no-accents` (or keep `typo` and say why in the README) |
| (README) | style | `evals/interpreter/README.md` L4 "Correcting a confirmation" still gives the `answer` + `confirm: no` form. The set follows L65 and prompt rule 9 instead (the corrected request is an `op`). This is right for `plan-confirm`, and code turns a `confirm: no` with a span into the revised op anyway (L65, `_plan_correction`). | L4 vs L65 | in the v2 README, one line saying that L65 and rule 9 replace L4's form for `plan-confirm` items |

No wrong gold found: every op, outcome, slot set, clarify or route call and correction after "Posso?" holds.

## Checked and accepted (60)

de: 60001, 60002, 60003, 60004 (gold right; alternative to add, above).
en: 60001, 60002, 60003, 60004, 60005 (alternative to add), 60006, 60007, 60008, 60009 (alternative to add), 60010, 60011, 60012, 60013, 60014, 60015.
es: 60001, 60002, 60003, 60004.
fr: 60001, 60002, 60003, 60004.
it: 60001, 60002, 60003.
pt-BR: 60001-60030, all of them, 60003, 60005 and 60030 with the style notes above.

Notes on the calls I checked closely and accept:
- The 13 corrections after "Posso?" (de-60003, en-60011, en-60012, en-60013, es-60003, fr-60003, it-60003, pt-BR-60016 to 60020, pt-BR-60030): each is the corrected request, an `op` with the op of `frame.last` and the new detail. No inherited slot is needed (each line restates the whole value).
- Routes and clarifications: en-60014, pt-BR-60022 (bulk, route + clarify), fr-60004, pt-BR-60023 (open-ended, route), pt-BR-60025 (wording left to the platform: route + clarify; `mail-draft` exists, but an also may never be a different effect op), en-60015, pt-BR-60021, pt-BR-60024 (no target, clarify).
- The debatable calls in the README (pt-BR-60007, 60008, 60014, 60029, en-60008, de-60004 "daran,") are consistent with B1 and the catalog.
- de-60002 asks for two things, but both are covered by one `items` op (rule 3 of the prompt), so it is not L9's two requests.
