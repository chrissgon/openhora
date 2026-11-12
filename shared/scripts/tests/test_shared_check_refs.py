"""Tests for shared/scripts/check_refs.py. Offline; every name and number below is fictional.

Run: uv run --with pytest pytest shared/scripts/tests
"""
from __future__ import annotations

import json

import pytest

from shared_helpers import clean_usage_error, run

CHECK_REFS = "check_refs.py"
FULL = '{title}, Northwind Institute. Published 2026-03-02. Accessed 2026-09-30. https://northwind.example/r. ' \
       'Tier 1. fact. Quote: "10 firms"'


def doc(tmp_path, sources, body="- 10 firms [1]\n", method="- M1: `python3 capacity.py`\n", heads=("Sources", "Method")):
    path = tmp_path / "market.md"
    path.write_text(f"# M\n\n## Buyers\n{body}\n## {heads[0]}\n{sources}\n\n## {heads[1]}\n{method}", encoding="utf-8")
    return str(path)


def test_a_complete_entry_passes(tmp_path):
    r = run(CHECK_REFS, "--file", doc(tmp_path, "[1] " + FULL.format(title="Survey")))
    assert r.returncode == 0, r.stdout + r.stderr
    out = json.loads(r.stdout)
    assert out["ok"] is True and out["sources"] == 1 and out["incomplete"] == []


def test_undefined_unused_and_incomplete_are_reported(tmp_path):
    sources = "\n".join(["[1] " + FULL.format(title="T"), "[2] " + FULL.format(title="T2"),
                         "[3] T3, P. no link and no quote"])
    r = run(CHECK_REFS, "--file", doc(tmp_path, sources, body="- 10 firms [1][3]; capacity M1 and M2\n"))
    assert r.returncode == 1
    out = json.loads(r.stdout)
    assert out["undefined"] == ["M2"]
    assert out["unused"] == ["2"]
    assert out["incomplete"] == [{"ref": "3", "missing": ["published", "accessed", "url", "tier", "quote"]}]


@pytest.mark.parametrize("entry, missing", [
    ('Survey. Published 2026-03-02. Accessed 2026-09-30. https://n.example. Tier 1. fact. Quote: "x"', ["publisher"]),
    ('Survey, Northwind. Accessed 2026-09-30. https://n.example. Tier 1. fact. Quote: "x"', ["published"]),
    ('Survey, Northwind. Published last spring. Accessed 2026-09-30. https://n.example. Tier 1. Quote: "x"', ["published"]),
    ('Survey, Northwind. Published undated. https://n.example. Tier 2. estimate. Quote: "x"', ["accessed"]),
    ('Survey, Northwind. Published 2026. Accessed today. https://n.example. Tier 2. Quote: "x"', ["accessed"]),
    ('Survey, Northwind. Published 2026-03. Accessed 2026-09-30. northwind.example. Tier 3. Quote: "x"', ["url"]),
    ('Survey, Northwind. Published 2026-03. Accessed 2026-09-30. https://n.example. opinion. Quote: "x"', ["tier"]),
    ('Survey, Northwind. Published 2026-03. Accessed 2026-09-30. https://n.example. Tier 4. Quote: "x"', ["tier"]),
    ('Survey, Northwind. Published 2026-03. Accessed 2026-09-30. https://n.example. Tier 1. fact.', ["quote"]),
    ('https://n.example/ab "x"', ["publisher", "published", "accessed", "tier"]),
])
def test_each_part_of_an_entry_is_required(tmp_path, entry, missing):
    """Publisher, dates and tier were left to the reader: an entry with a URL and a quote passed."""
    r = run(CHECK_REFS, "--file", doc(tmp_path, "[1] " + entry))
    assert r.returncode == 1
    assert json.loads(r.stdout)["incomplete"] == [{"ref": "1", "missing": missing}]


def test_a_file_location_counts_as_a_location(tmp_path):
    entry = '[1] Interview notes, Northwind Institute. Published undated. Accessed 2026-09-30. file: docs/notes/interviews.md. ' \
            'Tier 2. fact. Quote: "10 firms"'
    r = run(CHECK_REFS, "--file", doc(tmp_path, entry))
    assert r.returncode == 0, r.stdout + r.stderr
    assert json.loads(r.stdout)["ok"] is True
    bare = entry.replace("file: docs/notes/interviews.md. ", "")
    r = run(CHECK_REFS, "--file", doc(tmp_path, bare))
    assert json.loads(r.stdout)["incomplete"] == [{"ref": "1", "missing": ["url"]}]


def test_undated_and_a_year_alone_alone_are_dates_of_publication(tmp_path):
    for published in ("undated", "2025", "2025-11", "2025-11-03"):
        entry = f'Survey, Northwind. Published {published}. Accessed 2026-09-30. https://n.example. Tier 2. fact. Quote: "x"'
        assert run(CHECK_REFS, "--file", doc(tmp_path, "[1] " + entry)).returncode == 0, published


def test_translated_headings_and_labels(tmp_path):
    entry = '[1] Estudio, Instituto Norte. Publicado sin fecha. Consultado 2026-09-30. https://n.example. ' \
            'Nivel 2. hecho. Cita: "dato"'
    path = doc(tmp_path, entry, body="- dato [1] (M1)\n", method="- M1\n", heads=("Fuentes", "Metodo"))
    labels = ["--sources-heading", "Fuentes", "--method-heading", "Metodo", "--published-label", "Publicado",
              "--undated-label", "sin fecha", "--accessed-label", "Consultado", "--tier-label", "Nivel"]
    r = run(CHECK_REFS, "--file", path, *labels)
    assert r.returncode == 0, r.stdout + r.stderr
    assert run(CHECK_REFS, "--file", path).returncode == 2  # no "## Sources" heading
    half = run(CHECK_REFS, "--file", path, *labels[:4])
    assert json.loads(half.stdout)["incomplete"] == [{"ref": "1", "missing": ["published", "accessed", "tier"]}]


def test_help_and_usage_errors(tmp_path):
    r = run(CHECK_REFS, "--help")
    assert r.returncode == 0 and "Usage:" in r.stdout and "publisher" in r.stdout
    assert clean_usage_error(run(CHECK_REFS))
    assert clean_usage_error(run(CHECK_REFS, "--file"))
    assert clean_usage_error(run(CHECK_REFS, "--file", str(tmp_path / "absent.md")))
    assert clean_usage_error(run(CHECK_REFS, "--file", doc(tmp_path, "[1] x"), "--tier-label", " "))
    assert clean_usage_error(run(CHECK_REFS, "--file", doc(tmp_path, "[1] x"), "--tier-label"))
