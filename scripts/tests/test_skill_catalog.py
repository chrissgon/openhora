"""Tests of scripts/skill_catalog.py: the compact catalog of skills, flows and planned skills with their proof.

A fixture tree in tmp_path stands for the workbench (fictional skills and flows); one smoke test reads the real tree.
No network, no model, no git needed (a tree that is not a checkout reads `Commit: unknown`).

Run: uv run --with pytest pytest scripts/tests/test_skill_catalog.py
"""
from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "skill_catalog.py"
sys.path.insert(0, str(SCRIPT.parent))
spec = importlib.util.spec_from_file_location("skill_catalog_under_test", SCRIPT)
catalog = importlib.util.module_from_spec(spec)
spec.loader.exec_module(catalog)

DATE = "2026-01-15"
MODELS = ["model-strong", "model-cheap"]

SKILL_LINE = re.compile(
    r"^- skill `[a-z][a-z0-9-]*` \| [^|]+ \| [^|]+ \| v[^|]+ \| runtime: (yes|no) \| effects: [^|]+ \| requires: [^|]+ "
    r"\| in: [^|]+ \| out: [^|]+ \| does: [^|]+$")
PROOF_LINE = re.compile(r"^  - proof(?: `[^`]+`: [^()|]+ \(\d+ runs, source [a-z]+\)|: unknown \([a-z ]+\))$")
FLOW_LINE = re.compile(r"^- flow `[a-z][a-z0-9-]*` \| [^|]* \| tasks: [^|]+$")
PLANNED_LINE = re.compile(r"^- planned `[a-z][a-z0-9-]*` \| [^|]+ \| intent: [^|]+ \| backlog: ([A-Z]+[0-9]+|none)$")


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def skill(root: Path, name: str, description: str, area: str = "business", kind: str = "capability", version: str = "1.0.0",
          inputs: str = "[]", outputs: str = "[]", requires: str = "[]", effects: str = "[]") -> None:
    write(root / "skills" / name / "SKILL.md",
          "---\nname: %s\ndescription: >\n  %s\nlicense: MIT\nmetadata:\n  area: %s\n  kind: %s\n  inputs: %s\n"
          "  outputs: %s\n  updates: []\n  requires: %s\n  side_effects: %s\n  version: \"%s\"\n---\n\n# %s\n"
          % (name, description.replace("\n", "\n  "), area, kind, inputs, outputs, requires, effects, version, name))


def manifest(root: Path, name: str, whole: bool = True) -> None:
    data = {"skill": name}
    if whole:
        data.update({"documents": [], "machine_files": [], "mandatory_milestone": False, "asking_openings": [],
                     "gate": None})
    write(root / "skills" / name / "evals" / "runtime-manifest.json", json.dumps(data))


@pytest.fixture()
def tree(tmp_path):
    root = tmp_path / "bench"
    skill(root, "biz-demo", "Plan the demo offer for one small shop.\nThen write the notes. Use it when asked about a shop.",
          inputs="[docs/a.md, docs/b/<topic>.md]", outputs="[docs/demo.md]", requires="[search:web]")
    skill(root, "eng-widget", "Build a widget " + "and keep it tidy " * 20 + "end. Second sentence here.", area="engineering",
          effects="[publish, send]")
    skill(root, "core-router", "Route a request.", area="core")
    skill(root, "flow-demo", "Run the demo phases.", area="engineering", kind="flow")
    manifest(root, "biz-demo")
    manifest(root, "core-router", whole=False)  # partial: the skill is in a pack in use but is not runnable
    write(root / "packs" / "work.txt", "# comment\nbiz-*\narea:core\n!flow-*\n")
    write(root / "runtime" / "roles.json", json.dumps({"packs_in_use": ["work"]}))
    write(root / "evals" / "eval-gate.json", json.dumps({
        "measurement_version": 7, "lab_models": MODELS,
        "models": {"model-cheap": {"adapter": "adapter-b"}, "model-strong": {"adapter": "adapter-a"},
                   "model-extra": {"adapter": "adapter-c"}}}))
    write(root / "flows" / "demo.json", json.dumps({"flow": "demo", "title": "A demo flow", "tasks": [
        {"key": "first", "skill": "biz-demo"}, {"key": "second", "step": "catalog"}, {"key": "third", "skill": "eng-widget"}]}))
    write(root / "flows" / "broken.json", "{not json")
    write(root / "skills" / "core-orchestrator" / "references" / "routing.md",
          "# Routing\n\n## Business (`biz-`)\n\n| Intent | Skill |\n|---|---|\n"
          "| Plan the demo | biz-demo |\n"
          "| Price an offer; a \\| b split | biz-pricing (planned) |\n"
          "| Already built but still marked | eng-widget (planned) |\n"
          "## Cross-area\n\n| Intent | Skill |\n|---|---|\n| Build a whole product | flow-product (planned) |\n")
    write(root / "docs" / "inventory.md",
          "# Inventory\n\n| Skill | Produces | State |\n|---|---|---|\n"
          "| biz-pricing | docs/pricing.md | create (backlog NS15) |\n| eng-widget | w | built |\n")
    return root


def status_file(tmp_path: Path, rows: dict, extra=()) -> Path:
    skills = []
    for name, models in rows.items():
        skills.append({"skill": name, "models": {m: {"band": b, "runs": r} for m, (b, r) in models.items()}})
    for name in extra:
        skills.append({"skill": name, "models": {"model-strong": {"band": "reliable", "runs": 3.0}}})
    path = tmp_path / "status.json"
    path.write_text(json.dumps({"skills": skills}), encoding="utf-8")
    return path


def run(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          universal_newlines=True)


def entries(text: str, kind: str):
    return [line for line in text.splitlines() if line.startswith("- %s `" % kind)]


def test_folded_description_and_first_sentence(tree):
    text = catalog.build(str(tree), date=DATE)
    line = [l for l in entries(text, "skill") if "`biz-demo`" in l][0]
    assert "does: Plan the demo offer for one small shop." in line and "Then write" not in line
    assert "| in: docs/a.md, docs/b/<topic>.md |" in line and "| out: docs/demo.md |" in line
    assert "| requires: search:web |" in line and "| effects: none |" in line


def test_a_long_first_sentence_is_cut_on_a_word_with_dots(tree):
    text = catalog.build(str(tree), date=DATE)
    line = [l for l in entries(text, "skill") if "`eng-widget`" in l][0]
    does = line.split("| does: ")[1]
    assert does.endswith("...") and len(does) <= 200 and "Second sentence" not in does
    assert not does[:-3].endswith(" ") and "and keep it tidy" in does
    assert "| effects: publish, send |" in line
    assert catalog.first_sentence("x" * 250).endswith("...") and len(catalog.first_sentence("x" * 250)) == 200
    assert catalog.first_sentence("Short one. Next.") == "Short one."
    assert catalog.first_sentence("A | pipe") == "A / pipe"


def test_runtime_yes_needs_a_pack_in_use_and_a_whole_manifest(tree):
    text = catalog.build(str(tree), date=DATE)
    runtime = {re.search(r"`([^`]+)`", l).group(1): "runtime: yes" in l for l in entries(text, "skill")}
    # biz-demo: in the pack and whole; core-router: in the pack, manifest partial; eng-widget: not in the pack
    assert runtime == {"biz-demo": True, "core-router": False, "eng-widget": False, "flow-demo": False}


def test_flows_list_their_tasks_in_order_and_a_broken_file_is_noted(tree):
    done = run("--root", tree, "--date", DATE)
    assert done.returncode == 0
    assert entries(done.stdout, "flow") == [
        "- flow `demo` | A demo flow | tasks: first (biz-demo) -> second (step catalog) -> third (eng-widget)"]
    assert "broken.json" in done.stderr and "flow skipped" in done.stderr


def test_planned_rows_strip_the_mark_take_the_section_and_the_backlog_id(tree):
    done = run("--root", tree, "--date", DATE)
    assert entries(done.stdout, "planned") == [
        "- planned `biz-pricing` | Business | intent: Price an offer; a / b split | backlog: NS15",
        "- planned `flow-product` | Cross-area | intent: Build a whole product | backlog: none"]
    built = {re.search(r"`([^`]+)`", l).group(1) for l in entries(done.stdout, "skill")}
    planned = {re.search(r"`([^`]+)`", l).group(1) for l in entries(done.stdout, "planned")}
    assert not built & planned and "`eng-widget` is marked planned" in done.stderr
    assert "(planned)" not in done.stdout


def test_bands_from_a_status_file_in_the_gate_file_order(tree, tmp_path):
    status = status_file(tmp_path, {"biz-demo": {"model-cheap": ("reliable", 3.0), "model-strong": ("watch", 12)}},
                         extra=["skill-gone"])
    done = run("--root", tree, "--status", status, "--date", DATE)
    assert done.returncode == 0
    lines = done.stdout.splitlines()
    at = [i for i, l in enumerate(lines) if l.startswith("- skill `biz-demo`")][0]
    assert lines[at + 1] == "  - proof `model-strong`: watch (12 runs, source lab)"
    assert lines[at + 2] == "  - proof `model-cheap`: reliable (3 runs, source lab)"
    assert "  - proof: unknown (not in the status)" in lines  # a skill with no entry in the file
    assert "- Proof from: status" in lines
    assert "`skill-gone` is in the status but not on disk; skipped" in done.stderr and "skill-gone" not in done.stdout


def test_bands_from_a_proof_file_carry_their_source(tree, tmp_path):
    proof = tmp_path / "proof.json"
    proof.write_text(json.dumps({"version": 4, "skills": {"biz-demo": {"pairs": [
        {"model": "model-cheap", "band": "reliable", "runs": 6, "source": "community"},
        {"model": "model-strong", "band": "needs a test", "runs": 0, "source": None}]}}}), encoding="utf-8")
    done = run("--root", tree, "--proof", proof, "--date", DATE)
    lines = done.stdout.splitlines()
    at = [i for i, l in enumerate(lines) if l.startswith("- skill `biz-demo`")][0]
    assert lines[at + 1] == "  - proof `model-strong`: needs a test (0 runs, source none)"
    assert lines[at + 2] == "  - proof `model-cheap`: reliable (6 runs, source community)"
    assert "- Proof from: proof file" in lines
    assert "  - proof: unknown (not in the proof file)" in lines


def test_without_a_status_or_proof_every_skill_reads_unknown(tree):
    text = catalog.build(str(tree), date=DATE)
    proofs = [l for l in text.splitlines() if l.startswith("  - proof")]
    assert proofs == ["  - proof: unknown (no status given)"] * 4
    assert "- Proof from: none" in text


def test_the_header_names_the_models_the_date_and_the_measurement(tree):
    text = catalog.build(str(tree), date=DATE)
    assert "- Date: 2026-01-15" in text and "- Measurement version: 7" in text
    assert ("- Models: `model-strong` (adapter adapter-a), `model-cheap` (adapter adapter-b), "
            "`model-extra` (adapter adapter-c)") in text
    assert "- Commit: unknown" in text  # the fixture is not a checkout
    assert "- Counts: 4 skills, 1 flows, 2 planned skills" in text


def test_two_runs_are_byte_identical_and_sorted(tree, tmp_path):
    status = status_file(tmp_path, {"biz-demo": {"model-strong": ("reliable", 3)}})
    a, b = run("--root", tree, "--status", status, "--date", DATE), run("--root", tree, "--status", status, "--date", DATE)
    assert a.stdout == b.stdout and a.stdout
    names = [re.search(r"`([^`]+)`", l).group(1) for l in entries(a.stdout, "skill")]
    assert names == sorted(names)


def test_every_line_has_the_documented_grammar(tree, tmp_path):
    status = status_file(tmp_path, {"biz-demo": {"model-strong": ("reliable", 3.0)}})
    for args in ((), ("--status", status)):
        text = run("--root", tree, "--date", DATE, *args).stdout
        for line in text.splitlines():
            if line.startswith("- skill `"):
                assert SKILL_LINE.match(line), line
            elif line.startswith("  - proof"):
                assert PROOF_LINE.match(line), line
            elif line.startswith("- flow `"):
                assert FLOW_LINE.match(line), line
            elif line.startswith("- planned `"):
                assert PLANNED_LINE.match(line), line
            else:
                assert not line.startswith("  ") and not re.match(r"- (skill|flow|planned) ", line), line


def test_over_the_limit_it_exits_2_and_writes_nothing(tree, tmp_path):
    out = tmp_path / "out" / "catalog.md"
    done = run("--root", tree, "--date", DATE, "--max-chars", "300", "--out", out)
    assert done.returncode == 2 and done.stdout == "" and not out.exists() and not out.parent.exists()
    assert "over the limit of 300" in done.stderr
    ok = run("--root", tree, "--date", DATE, "--out", out)
    assert ok.returncode == 0 and ok.stdout == "" and out.read_text(encoding="utf-8").startswith("# Skill catalog")
    assert not list(out.parent.glob(".skill-catalog-*"))


def test_usage_errors_exit_2(tree, tmp_path):
    status = status_file(tmp_path, {})
    assert run("--bogus").returncode == 2
    assert run("--root").returncode == 2
    assert run("--root", tree, "--status", status, "--proof", status).returncode == 2
    assert run("--root", tree, "--date", "15/01/2026").returncode == 2
    assert run("--root", tree, "--max-chars", "many").returncode == 2
    missing = run("--root", tree, "--status", tmp_path / "nope.json")
    assert missing.returncode == 2 and "cannot read" in missing.stderr
    bad = tmp_path / "bad.json"
    bad.write_text("[]", encoding="utf-8")
    assert run("--root", tree, "--status", bad).returncode == 2


def test_help_prints_the_usage():
    done = run("--help")
    assert done.returncode == 0 and "--status" in done.stdout and "--max-chars" in done.stdout


def test_the_pack_reading_agrees_with_select_skills_on_the_real_tree():
    spec2 = importlib.util.spec_from_file_location("select_skills_for_catalog_test", ROOT / "scripts" / "select_skills.py")
    select = importlib.util.module_from_spec(spec2)
    spec2.loader.exec_module(select)
    skills = catalog.read_skills(str(ROOT))
    packs = catalog.read_packs(str(ROOT))
    assert "planning" in packs
    for pack in packs:
        assert sorted(catalog.pack_members(packs[pack], skills)) == select.resolve(pack=pack), pack


def test_smoke_on_the_real_tree(tmp_path):
    status = tmp_path / "status.json"
    status.write_text(json.dumps({"skills": [{"skill": "core-orchestrator", "models": {
        "frozen-model": {"band": "watch", "runs": 3}}}]}), encoding="utf-8")
    done = run("--status", status, "--date", DATE)
    assert done.returncode == 0, done.stderr
    folders = sorted(p.parent.name for p in (ROOT / "skills").glob("*/SKILL.md"))
    listed = [re.search(r"`([^`]+)`", l).group(1) for l in entries(done.stdout, "skill")]
    assert listed == folders and len(set(listed)) == len(listed)
    assert len(done.stdout) < catalog.DEFAULT_MAX
    assert "  - proof `frozen-model`: watch (3 runs, source lab)" in done.stdout
    assert len(entries(done.stdout, "flow")) == len(list((ROOT / "flows").glob("*.json")))
    assert len(entries(done.stdout, "planned")) >= 1
    for line in done.stdout.splitlines():
        if line.startswith("- skill `"):
            assert SKILL_LINE.match(line), line
