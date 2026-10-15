#!/usr/bin/env python3
"""Write the prices of the models the runtime knows into runtime/prices.json, from an adopted source.

runtime/prices.json is the one price table of the workbench: the runtime's cost of a run, the `auto` ranking, the proof
page and the API adapter read it. An entry holds the prices in dollars per million tokens, the URL they were read from
(`source`) and the day they were read (`accessed`). This script writes an entry from the one source it can read:
OpenRouter's models API, https://openrouter.ai/api/v1/models (principle 14: adopt what exists). It leaves a model it
cannot find in that list without an entry; it never invents a price and never changes an entry it was not asked for.

A model whose entry in evals/eval-gate.json has a `provider_pin` is served by that one provider, so it is priced at that
provider and not at the cheapest endpoint of the model: the price comes from OpenRouter's endpoints API,
https://openrouter.ai/api/v1/models/<id>/endpoints, at the endpoint whose provider is the pin (its `tag`, before the slash of
a quantization, or its `provider_name`, spelled the same way). Where the pin has several endpoints (one for each
quantization) the dearest is written, so that a cost estimate is never lower than what a run can pay. A pinned model whose
pin has no endpoint is missing: the script never falls back to another provider's price. The entry names the provider
(`provider`) and its source is the endpoints URL.

Usage:
  python3 scripts/update_prices.py [--model <id>]... [--refresh] [--from-file <models.json>] [--endpoints-file <f>] [--dry-run] [--table <file>]
  python3 scripts/update_prices.py --help

  --model <id>       a model to price, written as the table writes it: `openrouter/<id on OpenRouter>`, such as
                     openrouter/deepseek/deepseek-v4.1-flash. Without --model, the models of evals/eval-gate.json whose
                     route is OpenRouter.
  --refresh          also read again the entries the table already holds from OpenRouter (their `source` is that URL);
                     without it an entry that exists is left exactly as it is, with its source and date, except the entry of a
                     pinned model that was not priced at its pin (no `provider`, or another one): that one is written again
  --from-file <f>    read the models list from a file instead of the network (a test, or a saved answer); `accessed` is
                     still today's date
  --endpoints-file <f>  the same for the endpoints of the pinned models: an object of the OpenRouter id of a model to the
                     answer of its endpoints API
  --dry-run          print what would be written; write nothing
  --table <file>     another table than runtime/prices.json

An entry is written with `accessed` set to today's date (the clock). OpenRouter lists the price of one token as a text;
the entry holds it per million tokens. A kind the list does not price (a model with no cache charge) is left out of the
entry: the reader of the table treats a missing kind as unknown, and a run that used none of that kind costs the same
either way. A model with a time-of-day price (OpenRouter's `overrides`) is written at its listed base price and the
entry says so in `notes`.

Prints a JSON summary to stdout (written, kept, missing); diagnostics go to stderr.
Exit codes: 0 ok, 1 the source could not be read or a requested model (or its pinned provider) is not in it, 2 usage error.

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


def gate_entries():
    """{id: entry} of the gate file's models whose route is OpenRouter."""
    try:
        with open(GATE, encoding="utf-8") as f:
            gate = json.load(f)
    except (OSError, ValueError):
        return {}
    models = gate.get("models") if isinstance(gate.get("models"), dict) else {}
    return {m: e for m, e in sorted(models.items()) if isinstance(e, dict) and e.get("route") == "openrouter" and m.startswith(PREFIX)}


def gate_models():
    """The ids of the gate file's models whose route is OpenRouter."""
    return list(gate_entries())


def read_endpoints(model, files):
    """The endpoints answer of one model (its id as the table writes it): from the file map when given, else the network.
    None when it cannot be read."""
    openrouter_id = model[len(PREFIX):]
    if files is not None:
        return files.get(openrouter_id)
    url = f"{URL}/{openrouter_id}/endpoints"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"Accept": "application/json"}), timeout=TIMEOUT) as r:
            return json.loads(r.read(MAX_BYTES).decode("utf-8"))
    except (OSError, ValueError):
        return None


def pin_matches(endpoint, pin):
    """Whether an endpoint is served by the pinned provider: its tag before the slash of a quantization (`deepinfra/fp8`), or
    its provider name without spaces, in lower case."""
    tag = str(endpoint.get("tag") or "").lower().split("/")[0]
    name = str(endpoint.get("provider_name") or "").lower().replace(" ", "")
    return pin.lower() in (tag, name)


def entry_from_pinned(answer, pin, model, today):
    """The table entry for a model at its pinned provider, or None when the pin has no priced endpoint in the answer. The
    dearest endpoint of the pin is written (one for each quantization)."""
    data = answer.get("data") if isinstance(answer, dict) and isinstance(answer.get("data"), dict) else {}
    found = []
    for endpoint in data.get("endpoints") or []:
        if isinstance(endpoint, dict) and pin_matches(endpoint, pin):
            entry = entry_from(endpoint, today)
            if "input_usd_per_mtok" in entry and "output_usd_per_mtok" in entry:
                found.append((entry["input_usd_per_mtok"] + entry["output_usd_per_mtok"], entry, endpoint))
    if not found:
        return None
    _, entry, endpoint = max(found, key=lambda t: t[0])
    entry["source"] = f"{URL}/{model[len(PREFIX):]}/endpoints"
    entry["provider"] = pin
    notes = [f"priced at the pinned provider {pin}, not at the cheapest endpoint of the model"]
    discount = (endpoint.get("pricing") or {}).get("discount")
    if isinstance(discount, (int, float)) and not isinstance(discount, bool) and discount > 0:
        notes.append(f"OpenRouter lists a discount of {round(discount * 100)}% on this endpoint; the entry holds the listed price")
    if entry.get("notes"):
        notes.append(entry["notes"])
    entry["notes"] = "; ".join(notes)
    return entry


def main(argv):
    wanted, refresh, source, dry, table, endpoints_file = [], False, None, False, TABLE, None
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("--help", "-h"):
            print(__doc__.strip())
            return 0
        if a in ("--model", "--from-file", "--table", "--endpoints-file"):
            if i + 1 >= len(argv):
                die(f"{a} needs a value.")
            if a == "--model":
                wanted.append(argv[i + 1])
            elif a == "--from-file":
                source = argv[i + 1]
            elif a == "--endpoints-file":
                endpoints_file = argv[i + 1]
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
        wanted += sorted(m for m, e in models.items() if m.startswith(PREFIX) and str(e.get("source") or "").startswith(URL) and m not in wanted)
    bad = [m for m in wanted if not m.startswith(PREFIX)]
    if bad:
        die(f"--model {bad[0]}: this script prices OpenRouter models, written openrouter/<id>.")
    today = datetime.date.today().isoformat()
    pins = {m: e.get("provider_pin") for m, e in gate_entries().items() if e.get("provider_pin")}
    answer = None
    if any(m not in pins for m in dict.fromkeys(wanted)):
        answer = read_source(source)  # the models list is read only when a model without a pin needs it
    listed = {m.get("id"): m for m in (answer.get("data") or []) if isinstance(m, dict)} if isinstance(answer, dict) else {}
    endpoint_answers = None
    if endpoints_file:
        endpoint_answers = read_source(endpoints_file)
        if not isinstance(endpoint_answers, dict):
            die(f"{endpoints_file} is not an object of model ids to endpoints answers.", 1)
    written, kept, missing = [], [], []
    for model in dict.fromkeys(wanted):
        stale_pin = model in pins and models.get(model, {}).get("provider") != pins[model]  # priced before the pin was read: not at the pin
        if model in models and not stale_pin and not (refresh and str(models[model].get("source") or "").startswith(URL)):
            kept.append(model)
            continue
        if model in pins:
            endpoints = read_endpoints(model, endpoint_answers)
            entry = entry_from_pinned(endpoints, pins[model], model, today) if endpoints is not None else None
            found = entry
        else:
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
