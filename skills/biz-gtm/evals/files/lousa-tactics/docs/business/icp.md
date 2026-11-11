# Ideal customer profile: Lousa

- Owner: biz-icp-positioning
- Language: en
- Status: hypothesis
- Date: 2027-12-02
- Offer: Lousa, an app that generates lesson materials; size band: self-employed, one person; founder access: 300 past students and a small public profile

## Comparison
| Segment | Pain | Reach | Total |
|---|---|---|---|
| Self-employed English teachers | 4 [1] | 4 [2] | 8 |
| Small language schools | 3 [1] | 2 [2] | 5 |
- Totals and the gap between the top two: 3 [M1]
- Reading: self-employed teachers first.

## Primary profile
- Segment and size: self-employed English teachers who teach adults, in Brazil [1]
- Job to be done: prepare class materials faster [1]
- Pain and evidence: preparing a class takes several hours a week [1]
- Today they use: free worksheet sites and a paid kit [1]
- Decider: the teacher, alone [1]
- Triggers: the start of a school term [1]
- Where to find them: teacher associations and their local chapters [2]; the owner's past students and followers (state file, 2027-12-06)
- Rules that shape the offer: none found

## Validation plan
- Interviews: 5 with self-employed teachers, found through the owner's contacts
- Questions (past behaviour only): 1. How many hours did you spend preparing classes last week?
- Validated if: at least 3 of 5 name class preparation as their largest weekly task
- Rejected if: fewer than 2 of 5 name it
- Results:

## Unknowns
- Which teacher groups allow offers in their posts.

## Assumptions
- none

## Sources
[1] Teacher time survey, Teachkit blog. Published 2027-05-10. Accessed 2027-12-02. https://teachkit.example/survey. Tier 3. estimate. Quote: "Teachers spend about six hours a week preparing classes."
[2] Chapters of the teachers association, Association page. Published undated. Accessed 2027-12-02. https://teachers-assoc.example/chapters. Tier 1. fact. Quote: "Local chapters meet monthly."

## Method
- Queries: english teachers class preparation hours; teacher associations Brazil
- M1: rank.py with the scores of the Comparison table on standard input
- Checks: check_refs.py --file docs/business/icp.md; lint_icp.py --file docs/business/icp.md --kind icp
