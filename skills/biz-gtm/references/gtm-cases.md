# Cases that change how gtm.md is written

Read the case that matches at the step that points here. Each case keeps the owner's decisions and adds no number without a source.

## A. The owner's choice on a close call differs from the rank order (step 5)
Under Channels, write: the order the owner chose, the owner's words in quotation marks with the date, and the ranked totals exactly as `rank.py` printed them. Never change a score to make the table agree with the choice.

## B. A channel used only to boost another channel (step 4)
Paid boosts of the owner's own posts, a newsletter swap that only repeats a post, and similar are not a channel: they get no row in the ranking. Write them as an action row of the First four weeks table under the channel they boost (`Channel` cell: `<boosted channel> (boost)`), with their hours, and their cost inside the paid budget of the scope. Access for bought reach scores 3 at most, and the Channels reading says so.

## C. A tactic the owner proposes that breaks a platform's published rules but has a compliant variant (Stop rule 4, step 4)
1. Leave the proposed tactic out: it goes under Left out with the rule quoted, its source and the sentence of the request that proposed it.
2. Score the compliant variant as its own action or channel (for example, a post the rules allow, on the day or thread they allow).
3. The reply names both: what was left out and what replaces it.

## D. Rules score labels (step 5)
Both score 1 on rules, with a different label in the Channel rules table:
- the rules page exists and could not be read (blocked, empty, login wall): `not researched yet: unreadable`, and the Unknowns section says what to read by hand;
- a search found no published rules for promotion: the Source cell reads `no published rules page found` (queries under Method) and the Rule cell reads `no published rules`; the rules score is 1 until the owner or the community confirms a rule.

## E. A decision that contradicts another skill's recorded decision (step 2)
Example: the owner decides on a free plan after `biz-business-model` recorded "no free plan".
1. Record the new decision in the state file as a dated decision with the owner's quote, and write the contradiction in one line: what the other skill recorded, and in which artifact.
2. Under Unknowns of gtm.md, name the other skill's artifacts that need an update by that skill (for example `docs/business/business-model.md`, `docs/business/pricing.md`). Never edit them.
3. Plan with the newer decision.

## F. A rerun after the upstream artifacts changed (step 1)
When `docs/business/gtm.md` exists and positioning, pricing, business model or market files changed since its Date line:
1. List which sections each changed input feeds: positioning feeds Channel rules claims and Next skills; pricing and business model feed Motion; market feeds Channels; icp feeds all.
2. Recheck only those sections. Keep the owner's recorded channel order, the measurement results and every closed decision.
3. Do not rerun the channel research or `rank.py` unless a channel's facts changed (a source older than 12 months, a rule that changed, a size that changed). When it reruns, keep the owner's recorded order as in case A.
4. Add a dated line under Method saying what changed and which sections were rechecked, and run step 10 again.

## G. Open questions, work before launch, funnel rows, next skills (steps 6 to 9)
- Open questions: every question the plan leaves open goes under `Open questions` as `OPEN-<n>` with the question, your recommended answer and `Ready: no`; the header's `Ready` line is `no` while any is open. Close one only on the owner's answer, rewritten as `Decided by the owner on <date>: "<quote>"` with `Ready: yes`.
- Before launch: work that must happen before launch (validation interviews, setting up a profile) goes in the `Before launch` list with its hours, outside the four weeks; the weeks still count from the launch.
- Funnel: a step that is not a channel (free plan to paid, install to first result) gets its own Measurement row, `Funnel: <step>` in the Channel cell, the two counts that make its rate in Metric, the week to read it, and the same `Continue if` and `Stop if`.
- Next skills: the marketing skills (copy, posts, publishing) and any skill whose input this plan created (for example a business skill that must update its artifacts, or a product skill for a feature the owner decided), each with what it takes from this plan.
