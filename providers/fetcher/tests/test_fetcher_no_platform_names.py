"""Design rule 2: no social platform's name or host in a file of providers/fetcher/ (its README and tests included) or in the runtime's
reference modules. Every host, pattern and extractor comes from a platform's fetch file through a path given by flag."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PLATFORMS = ROOT / "shared" / "references" / "platforms"
SKIP = {"__pycache__"}


def forbidden():
    words = set()
    for path in PLATFORMS.glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        words.add(data["platform"].lower())
        for host in data.get("hosts") or []:
            words.add(host.lower())
        for host in (data.get("link") or {}).get("hosts") or []:
            words.add(host.lower())
        words.update(h.lower() for h in data.get("fetch_hosts") or [])
        words.update(s.lower().lstrip(".") for s in data.get("fetch_suffixes") or [])
    return sorted(w for w in words if w)


def files():
    found = [p for p in (ROOT / "providers" / "fetcher").rglob("*") if p.is_file() and not (set(p.parts) & SKIP) and p.suffix != ".pyc"]
    found += [ROOT / "runtime" / name for name in ("references.py", "ops_references.py") if (ROOT / "runtime" / name).is_file()]
    return found


def test_the_word_list_is_not_empty_and_holds_the_data_files_platforms():
    words = forbidden()
    assert len(words) >= 6 and any(w.startswith("www.") for w in words)


def test_no_file_of_the_fetcher_or_the_reference_modules_holds_a_platform_name_or_host():
    words = forbidden()
    found = []
    for path in files():
        text = path.read_text(encoding="utf-8", errors="ignore").lower()
        found += [(path.relative_to(ROOT).as_posix(), w) for w in words if re.search(r"(?<![a-z0-9])%s(?![a-z0-9])" % re.escape(w), text)]
    assert found == []
