# Brand profile: Dana Example

- Owner: brand-profile
- Status: confirmed
- Date: 2038-09-20
- Language of artifacts: English; language of posts: English and Portuguese [2]

## Who they are
- Public name: Dana Example [1]
- Experience: 8 years 8 months since 2030-01 [1]

## Citable proof
| Proof | What it shows | Type | Source | May cite |
|-------|---------------|------|--------|----------|
| tinykv: a 900-line key-value store, zero dependencies | small, boring tools | public product | [1] | yes [2] |
| p99 query latency cut by 64% | databases | self-reported | [1] | yes, without the employer [2] |

## Never expose
- Employer names [2]
- Family [2]
- Salary [2]
- Exact location [2]

## Sensitive topics
```sensitive-topics
{"action": "never_reply_escalate_to_user",
 "topics": {
  "family": {"keywords": ["family", "dad", "mom", "father", "mother", "wife", "husband", "son", "daughter"], "exclude": ["font family"]},
  "salary": {"keywords": ["salary", "how much do you make", "income"], "exclude": []},
  "employer": {"keywords": ["where do you work", "your employer", "your company"], "exclude": []},
  "location": {"keywords": ["where do you live", "your address"], "exclude": []},
  "jobs": {"keywords": ["hiring", "job offer", "recruiter", "open to work"], "exclude": []}
 }}
```

## Sources
[1] LinkedIn export and code host, 2038-09-19.
[2] Decisions in docs/workbench/state.md, 2038-09-19 and 2038-09-22.
