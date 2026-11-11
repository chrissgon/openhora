#!/usr/bin/env python3
"""Convert weekly delivery hours into jobs per month.

Usage:
  python3 capacity.py --hours-per-week 15 --hours-per-job 40 [--utilization 0.7]

Utilization is the share of the weekly hours that goes to the work counted in --hours-per-job
(the rest is admin, support and anything no job counts). Sales hours are not taken out here when
they are already inside --hours-per-job; take them out here only when they are not. Default 1.0. A month is 52/12 weeks. Prints JSON to stdout with the inputs,
the billable hours per month and the jobs per month (one decimal). Exit 2 on a bad argument.
"""
import argparse
import json
import sys

WEEKS_PER_MONTH = 52 / 12


def positive(text):
    try:
        val = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a number: {text!r}")
    if val <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return val


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--hours-per-week", type=positive, required=True)
    ap.add_argument("--hours-per-job", type=positive, required=True)
    ap.add_argument("--utilization", type=positive, default=1.0)
    args = ap.parse_args()
    if args.utilization > 1:
        ap.error("--utilization must be at most 1")
    billable = args.hours_per_week * WEEKS_PER_MONTH * args.utilization
    json.dump({
        "hours_per_week": args.hours_per_week,
        "hours_per_job": args.hours_per_job,
        "utilization": args.utilization,
        "weeks_per_month": round(WEEKS_PER_MONTH, 3),
        "billable_hours_per_month": round(billable, 1),
        "jobs_per_month": round(billable / args.hours_per_job, 1),
    }, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
