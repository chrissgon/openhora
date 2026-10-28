#!/usr/bin/env python3
"""The expectation ledger of the runtime's tests (package HOT-1; SPEC-HOTSPOTS 4.2).

THE POINT. A catalog package used to edit one long hard-coded line in each of several test modules (the set of effects, the list of operations on the messaging channel, the
non-operations of `ops.py`, ...), so two packages edited the same line and conflicted. Each such constant keeps its literal in the test as the BASE, and reads the additions of the
packages through `extend("<test module without test_>.<CONSTANT>", <base>)`. A package writes `runtime/tests/expected/<id>.json`:

    {"package": "<id>", "add": {"natural_table.R": ["a-new-operation"], "registry_rows.SEPARATES": {"a-new-operation": "words"}}}

`extend` returns the base's type (set, frozenset, list, tuple or dict) with every file's additions, in file-name order for a list or a tuple. The DOUBLE ENTRY IS KEPT: an item is still written
by hand, outside its source (the operations table, the registry), and a test still fails when the source has an item the expectation lacks and when the expectation has one the source lacks.
What `extend` refuses (it raises ValueError): an item listed twice (in the base and a file, or in two files, or twice in one file), a file whose `package` is not its stem, a file with a key
other than `package` and `add`, a malformed file, an addition whose type is not the base's.

  python3 runtime/tests/expected_kit.py --show natural_table.R     the merged value of one constant, as the test module computes it
  python3 runtime/tests/expected_kit.py --list                     every name any file of expected/ adds to

`EXPECTED_DIR` is a module constant; the tests of this kit monkeypatch it (and pass `folder` to the functions that take one).
"""
from __future__ import annotations

import argparse
import importlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXPECTED_DIR = HERE / "expected"
PACKAGE_ID = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
NAME = re.compile(r"^[a-z0-9_]+\.[A-Za-z_][A-Za-z0-9_]*$")
KEYS = {"package", "add"}


def _freeze(item):
    """A hashable form of an item (JSON gives lists where a base may hold tuples)."""
    if isinstance(item, (list, tuple)):
        return tuple(_freeze(x) for x in item)
    if isinstance(item, dict):
        return tuple(sorted((k, _freeze(v)) for k, v in item.items()))
    return item


def files(folder=None) -> list:
    """[(package, {name: additions})] of every ledger file, in file-name order. Raises ValueError on a malformed file."""
    folder = Path(folder or EXPECTED_DIR)
    found = []
    for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as error:
            raise ValueError(f"{path.name}: not valid JSON ({error})")
        if not isinstance(data, dict) or set(data) != KEYS:
            raise ValueError(f"{path.name}: the keys are exactly {sorted(KEYS)}")
        if data["package"] != path.stem or not PACKAGE_ID.match(path.stem):
            raise ValueError(f"{path.name}: `package` is {data['package']!r}; it is the file name without .json, lower case words joined by hyphens")
        if not isinstance(data["add"], dict):
            raise ValueError(f"{path.name}: `add` is an object of list names")
        for name, added in data["add"].items():
            if not NAME.match(name):
                raise ValueError(f"{path.name}: {name!r} is not `<test module without test_>.<CONSTANT>`")
            if not isinstance(added, (list, dict)):
                raise ValueError(f"{path.name}: {name} is a list of items or an object")
        found.append((path.stem, data["add"]))
    return found


def names(folder=None) -> dict:
    """{list name: [packages that add to it]}"""
    table = {}
    for package, add in files(folder):
        for name in add:
            table.setdefault(name, []).append(package)
    return table


def extend(name, base, folder=None):
    """`base` with the additions every file of the ledger lists under `name`, of the base's own type."""
    if isinstance(base, dict):
        merged = dict(base)
        for package, add in files(folder):
            if name in add:
                if not isinstance(add[name], dict):
                    raise ValueError(f"{package}: {name} is a dict in the test; add an object")
                for key, value in add[name].items():
                    if key in merged:
                        raise ValueError(f"{name}: {key!r} is listed twice (in {package} and before it)")
                    merged[key] = value
        return merged
    items = list(base)
    seen = {_freeze(item) for item in items}
    if len(seen) != len(items):
        raise ValueError(f"{name}: the base lists an item twice")
    for package, add in files(folder):
        if name in add:
            if not isinstance(add[name], list):
                raise ValueError(f"{package}: {name} is a list in the test; add an array")
            for item in add[name]:
                key = _freeze(item)
                if key in seen:
                    raise ValueError(f"{name}: {item!r} is listed twice (in {package} and before it)")
                seen.add(key)
                items.append(item)
    if isinstance(base, (set, frozenset)):
        return type(base)(_freeze(item) if isinstance(item, list) else item for item in items)
    if isinstance(base, tuple):
        return tuple(items)
    return items


def readers(tests_dir=None) -> set:
    """The names that some `extend("<name>"` of the test modules reads, found by a regular expression over their text (this kit and its own test are left out: they name fictional lists)."""
    found = set()
    for path in sorted(Path(tests_dir or HERE).glob("*.py")):
        if path.name in ("expected_kit.py", "test_expected_kit.py"):
            continue
        found |= set(re.findall(r"\bextend\(\s*\"([a-z0-9_]+\.[A-Za-z_][A-Za-z0-9_]*)\"", path.read_text(encoding="utf-8")))
    return found


def unread(folder=None, tests_dir=None) -> list:
    """The names of the ledger that no test module reads."""
    return sorted(set(names(folder)) - readers(tests_dir))


def show(name) -> str:
    module, constant = name.split(".", 1)
    sys.path.insert(0, str(HERE))
    value = getattr(importlib.import_module(f"test_{module}"), constant)
    if isinstance(value, dict):
        return json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True, default=str)
    return json.dumps(sorted(value, key=repr) if isinstance(value, (set, frozenset)) else list(value), indent=2, ensure_ascii=False, default=str)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Show the merged value of an expectation constant of the runtime's tests, or the names the ledger adds to.")
    parser.add_argument("--show", metavar="NAME", help="print the merged value of <test module without test_>.<CONSTANT>")
    parser.add_argument("--list", action="store_true", help="print every name a file of expected/ adds to, with its packages")
    args = parser.parse_args(argv)
    if args.show:
        print(show(args.show))
        return 0
    if args.list:
        for name, packages in sorted(names().items()):
            print(name, ", ".join(packages))
        return 0
    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
