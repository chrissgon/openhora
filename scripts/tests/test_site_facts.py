"""Offline tests of the generated facts of the website (site/): site/assets/data/proof.json must be what site/tools/build_proof_json.py builds from
docs/inventory.md and evals/eval-gate.json, and every block `<!-- facts:begin x -->` of site/*.html must be what site/tools/build_facts.py writes.
So a change of the inventory, the gate file, the count of skills or a page that is not followed by the two site commands fails here, in CI.
The planted cases use temporary copies; the real files are never edited. Nothing calls a model or the network.

If a test here fails on a real change, run (from the repository root):
  python3 site/tools/build_proof_json.py && python3 site/tools/build_facts.py --write

Run: uv run --with pytest pytest scripts/tests/test_site_facts.py
"""
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PROOF_TOOL = REPO / "site" / "tools" / "build_proof_json.py"
FACTS_TOOL = REPO / "site" / "tools" / "build_facts.py"
FIX = "python3 site/tools/build_proof_json.py && python3 site/tools/build_facts.py --write"
# the files the checks read; a change to one of them selects this test (scripts/select_tests.py names a test that holds the path in a string)
READ = ("docs/inventory.md", "evals/eval-gate.json", "site/assets/data/proof.json", "site/assets/js/proof.js", "site/index.html", "site/proof.html", "site/how-it-is-built.html")


def test_every_file_the_checks_read_exists():
    assert [p for p in READ if not (REPO / p).is_file()] == []


def run(*args):
    return subprocess.run([sys.executable, *map(str, args)], capture_output=True, text=True, cwd=REPO)


def test_proof_json_is_what_the_inventory_and_the_gate_file_give():
    r = run(PROOF_TOOL, "--check")
    assert r.returncode == 0, f"site/assets/data/proof.json is stale against docs/inventory.md and evals/eval-gate.json. Fix: {FIX}\n{r.stderr}"


def test_the_blocks_of_the_pages_are_what_the_tool_writes():
    r = run(FACTS_TOOL, "--check")
    assert r.returncode == 0, f"a facts block of site/*.html is stale. Fix: {FIX}\n{r.stderr}"


def test_a_planted_inventory_with_one_band_changed_fails_the_proof_check(tmp_path):
    text = (REPO / "docs" / "inventory.md").read_text(encoding="utf-8")
    planted, n = re.subn(r"(\| `asst-answer` \| `[^`|]+` \| )reliable( \|)", r"\1needs a test\2", text, count=1)
    if n == 0:  # the first row of the per-model table
        planted, n = re.subn(r"(^\| `[^`]+` \| `[^`]+` \| )reliable( \|)", r"\1needs a test\2", text, count=1, flags=re.M)
    assert n == 1 and planted != text
    inv = tmp_path / "inventory.md"
    inv.write_text(planted, encoding="utf-8")
    r = run(PROOF_TOOL, "--inventory", inv, "--check")
    assert r.returncode == 1
    assert "differs" in r.stderr and "build_facts.py --write" in r.stderr


def copy_site(tmp_path):
    site = tmp_path / "site"
    for rel in ("assets/data/proof.json", "assets/js/proof.js"):
        (site / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO / "site" / rel, site / rel)
    for page in (REPO / "site").glob("*.html"):
        shutil.copy(page, site / page.name)
    return site


def test_a_page_with_a_changed_number_in_a_block_fails_and_names_the_block(tmp_path):
    site = copy_site(tmp_path)
    page = site / "index.html"
    text = page.read_text(encoding="utf-8")
    planted, n = re.subn(r"(<!-- facts:begin skills -->)\d+(<!-- facts:end skills -->)", r"\g<1>999\2", text, count=1)
    assert n == 1
    page.write_text(planted, encoding="utf-8")
    r = run(FACTS_TOOL, "--check", "--site", site)
    assert r.returncode == 1
    assert "block skills differs" in r.stderr and "index.html" in r.stderr


def test_write_repairs_the_planted_page(tmp_path):
    site = copy_site(tmp_path)
    page = site / "proof.html"
    text = page.read_text(encoding="utf-8")
    page.write_text(re.sub(r"(<!-- facts:begin commit -->)[0-9a-f]+(<!-- facts:end commit -->)", r"\g<1>0000000\2", text, count=1), encoding="utf-8")
    assert run(FACTS_TOOL, "--check", "--site", site).returncode == 1
    assert run(FACTS_TOOL, "--write", "--site", site).returncode == 0
    assert run(FACTS_TOOL, "--check", "--site", site).returncode == 0


def test_the_gate_widget_constants_agree_with_the_gate_file(tmp_path):
    site = copy_site(tmp_path)
    js = site / "assets" / "js" / "proof.js"
    js.write_text(js.read_text(encoding="utf-8").replace("THRESHOLD = 0.8", "THRESHOLD = 0.9"), encoding="utf-8")
    r = run(FACTS_TOOL, "--check", "--site", site)
    assert r.returncode == 1 and "THRESHOLD" in r.stderr
