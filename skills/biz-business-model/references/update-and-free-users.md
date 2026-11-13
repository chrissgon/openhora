# Updating an artifact, and free users

## Updating

Use this when `docs/business/business-model.md` or `pricing.md` exists and an input changed since the artifact's date (the state file, market.md, icp.md, positioning.md, a brief).

1. Rerun `unit_economics.py` for every computation whose inputs changed, with a new label (`M2`, `M3`), and replace that table. Leave a computation whose inputs did not change as it is.
2. Add one dated line under Method: `Update <YYYY-MM-DD>: <what changed>; reran <M labels>`.
3. An open item the owner has since decided is reworded as `decided by the owner on <date>: "<their words>"`. Set `Ready: yes` only when no open item is left; an item still undecided stays as it is, with `Ready: no`.
4. Keep the price test, its criteria and its results.

## Free users

A free plan costs money to serve. Add this key to the JSON of step 6:

```json
"free_users": {"per_payer": {"value": 5, "source": "assumed"},
               "cost": {"value": 0.8, "source": "M2"},
               "mode": "monthly",
               "margin_floor_percent": {"value": 60, "source": "user"}}
```

- `per_payer`: free users each paying unit carries. `cost`: what one free user costs.
- `mode`: `monthly` (the cost recurs each month, the default) or `once-per-account` (a one-time cost per free user, such as one trial run).
- `margin_floor_percent` is optional; it comes from the owner or the state file.
- The script prints the contribution and margin with free users, how many free users one payer covers until the contribution reaches zero, how many while the margin stays at or above the floor, and, for `once-per-account`, the months that repay the one-time cost.
- Paste the rows as printed. A figure the script prints as `unknown` stays `unknown`.
