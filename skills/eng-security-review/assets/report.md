# Security review: <repository>, <YYYY-MM-DD>

- Owner: eng-security-review
- Language: <the tag this file is written in: on an update, the one already here unless the request sets another; else the project language>
- Status: draft | approved | done
- Scope: dependency alerts only (secrets, authentication, input handling and configuration not reviewed)
- Source: <integration | provider | file from the user>, fetched <date>; <open_count> open alerts
- Grouping: `triage_alerts.py --alerts <file name> --repo <project root>` → open_count <n>, groups <n>
- By severity: critical <n>, high <n>, medium <n>, low <n>

## Manifests
| Manifest | Open alerts | Packages | Shipped? | Installed or run? | Copied from | Evidence (command and its output line, verbatim, or file:line) |
|----------|-------------|----------|----------|-------------------|-------------|------------------------------------------------------------------|

## Plan
| # | Manifest | Package | Declared | Alerts (numbers) | Max severity | Recommendation | Reason | Target version |
|---|----------|---------|----------|------------------|--------------|----------------|--------|----------------|

## Dismissal comments
- Group <#>: "<comment, at most 280 characters>"

## Approval
- <date>: <the user's words>, rows <#…>, payload sha256 <hash>

## Results
| Alert | Action | Result |
|-------|--------|--------|

## Proposed tasks
- <update <package> in <manifest> to <version> (major: read the migration guide), or none>

## Assumptions
- <Assumption: ..., or none>
