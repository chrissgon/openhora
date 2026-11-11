# Ideal customer profile: Forja

- Owner: biz-icp-positioning
- Language: en
- Status: hypothesis
- Date: 2027-12-04
- Offer: Forja, an open-source, self-hosted AI workbench; size band: one person; founder access: a direct network of Brazilian developers

## Comparison
| Segment | Pain | Reach | Total |
|---|---|---|---|
| Solo builders | 4 [1] | 5 [2] | 9 |
| Small agencies | 3 [1] | 2 [2] | 5 |
- Totals and the gap between the top two: 4 [M1]
- Reading: solo builders first; the founder reaches them directly.

## Primary profile
- Segment and size: solo builders, one person, who build products with AI help [1]
- Job to be done: open; hypotheses to test in conversations, none chosen
- Pain and evidence: they repeat the same set-up work in every project [1]
- Today they use: their own scripts and the free tier of hosted tools [1]
- Decider: the builder themselves, self-serve [1]
- Triggers: the start of a new project [1]
- Where to find them: a Brazilian developer meetup directory [2]; the founder's own network and followers (state file, 2027-12-06)
- Rules that shape the offer: none found

## Validation plan
- Interviews: 5 with solo builders, found through the founder's network
- Questions (past behaviour only): 1. When did you last set up a new project, and how long did it take?
- Validated if: at least 3 of 5 name the same set-up task
- Rejected if: fewer than 2 of 5 name it
- Results:

## Unknowns
- Which English-language communities reach solo builders, and their rules.

## Assumptions
- none

## Sources
[1] Solo builder survey, Devnotes. Published 2027-03-01. Accessed 2027-12-04. https://devnotes.example/solo-survey. Tier 2. estimate. Quote: "Solo builders spend their first week on set-up."
[2] Brazilian developer meetups, Devmap. Published undated. Accessed 2027-12-04. https://devmap.example/brazil. Tier 3. fact. Quote: "Meetups in 40 Brazilian cities."

## Method
- Queries: solo builders pain; developer meetups Brazil
- M1: rank.py with the scores of the Comparison table on standard input
- Checks: check_refs.py --file docs/business/icp.md; lint_icp.py --file docs/business/icp.md --kind icp
