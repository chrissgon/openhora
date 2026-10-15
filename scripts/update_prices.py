#!/usr/bin/env python3
"""Write the prices of the models the runtime knows into runtime/prices.json, from an adopted source.

runtime/prices.json is the one price table of the workbench: the runtime's cost of a run, the `auto` ranking, the proof
page and the API adapter read it. An entry holds the prices in dollars per million tokens, the URL they were read from
(`source`) and the day they were read (`accessed`). This script writes an entry from the one source it can read:
OpenRouter's models API, https://openrouter.ai/api/v1/models (principle 14: adopt what exists). It leaves a model it
cannot find in that list without an entry; it never invents a price and never changes an entry it was not asked for.

Usage:
  python3 scripts/update_prices.py [--model <id>]... [--refresh] [--from-file <models.json>] [--dry-run] [--table <file>]
  python3 scripts/update_prices.py --help

  --model <id>       a model to price, written as the table writes it: `openrouter/<id on OpenRouter>`, such as
                     openrouter/deepseek/deepseek-v4.1-flash. Without --model, the models of evals/eval-gate.json whose
                     route is OpenRouter.
  --refresh          also read again the entries the table already holds from OpenRouter (their `source` is that URL);
                     without it an entry that exists is left exactly as it is, with its source and date
  --from-file <f>    read the API answer from a file instead of the network (a test, or a saved answer); `accessed` is
                     still today's date
  --dry-run          print what would be written; write nothing
  --table <file>     another table than runtime/prices.json

An entry is written with `accessed` set to today's date (the clock). OpenRouter lists the price of one token as a text;
the entry holds it per million tokens. A kind the list does not price (a model with no cache charge) is left out of the
entry: the reader of the table treats a missing kind as unknown, and a run that used none of that kind costs the same
either way. A model with a time-of-day price (OpenRouter's `overrides`) is written at its listed base price and the
entry says so in `notes`.

Prints a JSON summary to stdout (written, kept, missing); diagnostics go to stderr.
Exit codes: 0 ok, 1 the source could not be read or a requested model is not in it, 2 usage error.

Standard library only. Runs on Python 3.9.
"""
import datetime
import json
import os
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TABLE = os.path.join(ROOT, "runtime", "prices.json")
GATE = os.path.join(ROOT, "evals", "eval-gate.json")
URL = "https://openrouter.ai/api/v1/models"
PREFIX = "openrouter/"
FIELDS = {"prompt": "input_usd_per_mtok", "completion": "output_usd_per_mtok",
          "input_cache_read": "cache_read_usd_per_mtok", "input_cache_write": "cache_write_usd_per_mtok"}
TIMEOUT = 60
MAX_BYTES = 64 * 1024 * 1024


def die(message, code=2):
    print(f"error: {message}", file=sys.stderr)
    sys.exit(code)


def read_source(path):
    """The API answer as an object: from the file when given, else from the network."""
    try:
        if path:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        with urllib.request.urlopen(urllib.request.Request(URL, headers={"Accept": "application/json"}), timeout=TIMEOUT) as r:
            return json.loads(r.read(MAX_BYTES).decode("utf-8"))
    except (OSError, ValueError) as e:
        die(f"{path or URL} could not be read: {e}", 1)


def per_million(text):
    """Dollars per million tokens from OpenRouter's dollars per token (a text), or None when it is not a number."""
    try:
        value = float(text)
    except (TypeError, ValueError):
        return None
    if value < 0:
        return None
    return round(value * 1_000_000, 6)


def entry_from(listed, today):
    """The table entry for one model of the API answer."""
    pricing = listed.get("pricing") if isinstance(listed.get("pricing"), dict) else {}
    entry = {}
    for name, field in FIELDS.items():
        value = per_million(pricing.get(name)) if name in pricing else None
        if value is not None:
            entry[field] = value
    entry["source"] = URL
    entry["accessed"] = today
    if pricing.get("overrides"):
        entry["notes"] = "OpenRouter lists a price by time of day for this model; the entry holds its base price"
    return entry


def gate_models():
    """The ids of the gate file's models whose route is OpenRouter."""
    try:
        with open(GATE, encoding="utf-8") as f:
            gate = json.load(f)
    except (OSError, ValueError):
        return []
    models = gate.get("models") if isinstance(gate.get("models"), dict) else {}
    return sorted(m for m, e in models.items() if isinstance(e, dict) and e.get("route") == "openrouter" and m.startswith(PREFIX))


def main(argv):
    wanted, refresh, source, dry, table = [], False, None, False, TABLE
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("--help", "-h"):
            print(__doc__.strip())
            return 0
        if a in ("--model", "--from-file", "--table"):
            if i + 1 >= len(argv):
                die(f"{a} needs a value.")
            if a == "--model":
                wanted.append(argv[i + 1])
            elif a == "--from-file":
                source = argv[i + 1]
            else:
                table = argv[i + 1]
            i += 2
        elif a == "--refresh":
            refresh = True
            i += 1
        elif a == "--dry-run":
            dry = True
            i += 1
        else:
            die(f"unknown option {a!r}. See --help.")
    try:
        with open(table, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        die(f"{table} could not be read: {e}")
    if not isinstance(data, dict) or not isinstance(data.get("models"), dict):
        die(f"{table} is not a price table (an object with a \"models\" object).")
    models = data["models"]
    if not wanted:
        wanted = gate_models()
    if refresh:
        wanted += sorted(m for m, e in models.items() if m.startswith(PREFIX) and e.get("source") == URL and m not in wanted)
    bad = [m for m in wanted if not m.startswith(PREFIX)]
    if bad:
        die(f"--model {bad[0]}: this script prices OpenRouter models, written openrouter/<id>.")
    today = datetime.date.today().isoformat()
    answer = read_source(source)
    listed = {m.get("id"): m for m in (answer.get("data") or []) if isinstance(m, dict)} if isinstance(answer, dict) else {}
    written, kept, missing = [], [], []
    for model in dict.fromkeys(wanted):
        if model in models and not (refresh and models[model].get("source") == URL):
            kept.append(model)
            continue
        found = listed.get(model[len(PREFIX):])
        entry = entry_from(found, today) if found is not None else None
        if entry is None or not any(field in entry for field in FIELDS.values()):
            missing.append(model)
            continue
        old = models.get(model) or {}
        if old.get("aliases"):
            entry = {"aliases": old["aliases"], **entry}
        models[model] = entry
        written.append(model)
    if written and not dry:
        data["models"] = dict(sorted(models.items()))
        tmp = table + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, table)
    print(json.dumps({"written": written, "kept": kept, "missing": missing, "dry_run": dry, "accessed": today}, indent=2))
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
