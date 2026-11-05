"""Tests of scripts/skill_catalog.py: the compact catalog of skills, flows and planned skills with their proof.

A fixture tree in tmp_path stands for the workbench (fictional skills and flows); one smoke test reads the real tree.
No network, no model, no git needed (a tree that is not a checkout reads `Commit: unknown`).

Run: uv run --with pytest pytest scripts/tests/test_skill_catalog.py
"""
from __future__ import annotations

import importlib.util
import json
import os
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
    r"^- skill `[a-z][a-z0-9-]*` \| [^|]+ \| [^|]+ \| v[^|]+ \| runtime: (yes|contained|no) \| effects: [^|]+ \| requires: [^|]+ "
    r"\| in: [^|]+ \| out: [^|]+ \| does: [^|]+$")
PROOF_LINE = re.compile(
    r"^  - proof(?: `[^`]+`: [^()|]+ \((?:\d+|unknown) runs, source [a-z]+\)| `[^`]+`: unknown \(no evidence in the [a-z ]+\)"
    r"|: unknown \([a-z ]+\))(?: \(proof of v[0-9.]+\))?$")
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
    skill(root, "mkt-post", "Write one post.", area="marketing")
    manifest(root, "biz-demo")
    manifest(root, "mkt-post")
    manifest(root, "core-router", whole=False)  # partial: the skill is in a pack in use but is not runnable
    write(root / "packs" / "work.txt", "# comment\nbiz-*\narea:core\n!flow-*\n")
    write(root / "packs" / "social.txt", "mkt-*\n")
    write(root / "packs" / "default.txt", "*\n")  # a catch-all pack never makes a skill `contained`
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
    runtime = {re.search(r"`([^`]+)`", l).group(1): re.search(r"runtime: (\w+)", l).group(1) for l in entries(text, "skill")}
    # biz-demo: in the pack in use and whole; core-router: in it, manifest partial; eng-widget: in no pack;
    # mkt-post: whole manifest and a pack outside packs_in_use that a project can give an area agent
    assert runtime == {"biz-demo": "yes", "core-router": "no", "eng-widget": "no", "flow-demo": "no", "mkt-post": "contained"}


def test_flows_list_their_tasks_in_order_and_a_broken_file_is_noted(tree):
    done = run("--root", tree, "--date", DATE)
    assert done.returncode == 0
    assert entries(done.stdout, "flow") == [
        "- flow `demo` | A demo flow | tasks: first (biz-demo) -> second (step catalog) -> third (eng-widget)"]
    assert "broken.json" in done.stderr and "flow skipped" in done.stderr


def test_planned_rows_strip_the_mark_take_the_section_and_the_backlog_id(tree):
    done = run("--root", tree, "--date", DATE)
    assert entries(done.stdout, "planned") == [
        "- planned `biz-pricing` | business | intent: Price an offer; a / b split | backlog: NS15",
        "- planned `flow-product` | cross-area | intent: Build a whole product | backlog: none"]
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
    proof.write_text(json.dumps({"version": catalog.PROOF_VERSION, "skills": {"biz-demo": {"pairs": [
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
    assert proofs == ["  - proof: unknown (no status given)"] * 5
    assert "- Proof from: none" in text


def test_the_header_names_the_models_the_date_and_the_measurement(tree):
    text = catalog.build(str(tree), date=DATE)
    assert "- Date: 2026-01-15" in text and "- Measurement version: 7" in text
    assert ("- Models: `model-strong` (adapter adapter-a), `model-cheap` (adapter adapter-b), "
            "`model-extra` (adapter adapter-c)") in text
    assert "- Commit: unknown" in text  # the fixture is not a checkout
    assert "- Counts: 5 skills, 1 flows, 2 planned skills" in text


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


def test_smoke_on_the_real_tree_with_the_real_status(tmp_path):
    """The shape and the size are tested on what `eval_status.py status` really prints for this checkout."""
    status = subprocess.run([sys.executable, str(ROOT / "evals" / "eval_status.py"), "status"], stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, universal_newlines=True, cwd=str(ROOT))
    assert status.returncode == 0, status.stderr
    real = tmp_path / "status.json"
    real.write_text(status.stdout, encoding="utf-8")
    done = run("--status", real, "--date", DATE)
    assert done.returncode == 0, done.stderr
    folders = sorted(p.parent.name for p in (ROOT / "skills").glob("*/SKILL.md"))
    listed = [re.search(r"`([^`]+)`", l).group(1) for l in entries(done.stdout, "skill")]
    assert listed == folders and len(set(listed)) == len(listed)
    assert len(done.stdout) < catalog.DEFAULT_MAX
    models = json.loads((ROOT / "evals" / "eval-gate.json").read_text(encoding="utf-8"))["models"]
    lines = done.stdout.splitlines()
    for at, line in enumerate(lines):
        if line.startswith("- skill `"):
            assert SKILL_LINE.match(line), line
            # every skill, with or without evidence, has a proof line for each model of the gate file
            block = []
            for follow in lines[at + 1:]:
                if not follow.startswith("  - proof"):
                    break
                block.append(follow)
            assert len(block) >= len(models), line
            for follow in block:
                assert PROOF_LINE.match(follow), follow
            for model in models:
                assert any("`%s`" % model in follow for follow in block), (line, model)
    assert len(entries(done.stdout, "flow")) == len(list((ROOT / "flows").glob("*.json")))
    assert len(entries(done.stdout, "planned")) >= 1
    contained = [l for l in entries(done.stdout, "skill") if "runtime: contained" in l]
    assert sorted(re.search(r"`([^`]+)`", l).group(1) for l in contained) == ["asst-answer", "mkt-engage", "mkt-vote-round"]


def test_a_status_row_with_no_models_still_prints_one_line_for_each_gate_model(tree, tmp_path):
    path = tmp_path / "status.json"
    path.write_text(json.dumps({"skills": [
        {"skill": "biz-demo", "version": "1.0.0", "models": {}},
        {"skill": "eng-widget", "models": {"model-cheap": {"band": "watch", "runs": 3}}}]}), encoding="utf-8")
    lines = run("--root", tree, "--status", path, "--date", DATE).stdout.splitlines()
    at = [i for i, l in enumerate(lines) if l.startswith("- skill `biz-demo`")][0]
    assert lines[at + 1:at + 3] == ["  - proof `model-strong`: unknown (no evidence in the status)",
                                    "  - proof `model-cheap`: unknown (no evidence in the status)"]
    at = [i for i, l in enumerate(lines) if l.startswith("- skill `eng-widget`")][0]
    assert lines[at + 1] == "  - proof `model-strong`: unknown (no evidence in the status)"
    assert lines[at + 2] == "  - proof `model-cheap`: watch (3 runs, source lab)"


def test_a_stale_proof_names_its_version_and_a_bad_run_count_reads_unknown(tree, tmp_path):
    path = tmp_path / "status.json"
    path.write_text(json.dumps({"skills": [{"skill": "biz-demo", "version": "0.9.0", "models": {
        "model-strong": {"band": "watch", "runs": -2}, "model-cheap": {"band": "watch", "runs": "many"}}}]}),
        encoding="utf-8")
    lines = run("--root", tree, "--status", path, "--date", DATE).stdout.splitlines()
    at = [i for i, l in enumerate(lines) if l.startswith("- skill `biz-demo`")][0]
    assert lines[at + 1] == "  - proof `model-strong`: watch (unknown runs, source lab) (proof of v0.9.0)"
    assert lines[at + 2] == "  - proof `model-cheap`: watch (unknown runs, source lab) (proof of v0.9.0)"
    path.write_text(json.dumps({"skills": [{"skill": "biz-demo", "version": "1.0.0", "models": {}}]}), encoding="utf-8")
    assert "proof of" not in run("--root", tree, "--status", path, "--date", DATE).stdout


def write_proof(tmp_path, data):
    path = tmp_path / "proof.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_a_proof_file_of_another_version_is_refused_and_odd_entries_read_unknown(tree, tmp_path):
    refused = run("--root", tree, "--proof", write_proof(tmp_path, {"version": 3, "skills": {}}), "--date", DATE)
    assert refused.returncode == 2 and "version 3" in refused.stderr and refused.stdout == ""
    odd = write_proof(tmp_path, {"version": catalog.PROOF_VERSION, "skills": {
        "biz-demo": {"pairs": "none", "skill_version": "1.0.0"}, "eng-widget": {"pairs": []}, "core-router": 5}})
    done = run("--root", tree, "--proof", odd, "--date", DATE)
    assert done.returncode == 0
    lines = done.stdout.splitlines()
    for name in ("biz-demo", "eng-widget", "core-router"):
        at = [i for i, l in enumerate(lines) if l.startswith("- skill `%s`" % name)][0]
        assert lines[at + 1] == "  - proof `model-strong`: unknown (no evidence in the proof file)"
        assert lines[at + 2] == "  - proof `model-cheap`: unknown (no evidence in the proof file)"
        assert "`%s` has no usable pair in the proof file" % name in done.stderr


def test_the_constants_mirrored_from_the_runtime_are_the_runtimes():
    proof_text = (ROOT / "runtime" / "proof.py").read_text(encoding="utf-8")
    assert re.search(r"^VERSION = %d$" % catalog.PROOF_VERSION, proof_text, re.M)
    plan_text = (ROOT / "runtime" / "plan.py").read_text(encoding="utf-8")
    found = re.search(r"^CATCH_ALL_PACKS = \(([^)]*)\)", plan_text, re.M)
    assert tuple(re.findall(r'"([^"]+)"', found.group(1))) == catalog.CATCH_ALL_PACKS
    manifest_text = (ROOT / "runtime" / "manifest.py").read_text(encoding="utf-8")
    keys = re.search(r"^KEYS = \(([^)]*)\)", manifest_text, re.M)
    assert tuple(re.findall(r'"([^"]+)"', keys.group(1))) == catalog.MANIFEST_KEYS


@pytest.mark.parametrize("name,text,fragment", [
    ("status-models-list", {"skills": [{"skill": "biz-demo", "models": ["a"]}]}, "`models` of `biz-demo` is not an object"),
    ("status-skill-list", {"skills": [{"skill": ["biz-demo"], "models": {}}]}, "an entry of `skills`"),
    ("status-entry-string", {"skills": ["biz-demo"]}, "an entry of `skills`"),
    ("status-not-object", ["x"], "no `skills` list"),
])
def test_a_malformed_status_is_a_clear_error_not_a_traceback(tree, tmp_path, name, text, fragment):
    path = tmp_path / (name + ".json")
    path.write_text(json.dumps(text), encoding="utf-8")
    done = run("--root", tree, "--status", path)
    assert done.returncode == 2 and fragment in done.stderr and "Traceback" not in done.stderr and done.stdout == ""


@pytest.mark.parametrize("relative,text,fragment", [
    ("runtime/roles.json", "[]", "`packs_in_use`"),
    ("runtime/roles.json", '{"packs_in_use": "work"}', "`packs_in_use`"),
    ("runtime/roles.json", "{nope", "not valid JSON"),
    ("evals/eval-gate.json", "[]", "not a JSON object"),
    ("evals/eval-gate.json", '{"models": ["a"]}', "`models` is not an object"),
    ("evals/eval-gate.json", '{"models": {}, "lab_models": "a"}', "`lab_models` is not a list"),
])
def test_a_malformed_workbench_file_is_a_clear_error_not_a_traceback(tree, relative, text, fragment):
    write(tree / relative, text)
    done = run("--root", tree)
    assert done.returncode == 2 and fragment in done.stderr and "Traceback" not in done.stderr


def test_the_older_alias_list_form_of_the_gate_models_is_read(tree):
    write(tree / "evals" / "eval-gate.json", json.dumps({"measurement_version": 3, "lab_models": ["model-a"],
                                                         "models": {"model-a": ["alias-a"], "model-b": {"adapter": "x"}}}))
    text = run("--root", tree, "--date", DATE).stdout
    assert "- Models: `model-a` (adapter unknown), `model-b` (adapter x)" in text


def test_a_skill_with_a_string_metadata_is_skipped_with_a_note(tree):
    write(tree / "skills" / "odd-skill" / "SKILL.md", "---\nname: odd-skill\ndescription: x\nmetadata: nothing\n---\n")
    done = run("--root", tree, "--date", DATE)
    assert done.returncode == 0 and "odd-skill" not in done.stdout
    assert "skills/odd-skill/SKILL.md: the frontmatter has no `metadata` object; skipped" in done.stderr


def test_an_unwritable_out_leaves_no_temporary_file_and_exits_2(tree, tmp_path):
    folder = tmp_path / "taken"
    folder.mkdir()
    done = run("--root", tree, "--date", DATE, "--out", folder)
    assert done.returncode == 2 and "cannot write" in done.stderr and "Traceback" not in done.stderr
    assert not list(tmp_path.glob(".skill-catalog-*"))
    blocked = tmp_path / "file"
    blocked.write_text("x", encoding="utf-8")
    done = run("--root", tree, "--date", DATE, "--out", blocked / "inner" / "c.md")
    assert done.returncode == 2 and "cannot write" in done.stderr


def test_the_date_must_be_a_real_date(tree):
    assert run("--root", tree, "--date", "2026-02-30").returncode == 2
    assert run("--root", tree, "--date", "2026-13-01").returncode == 2
    assert run("--root", tree, "--date", "2026-02-28").returncode == 0


def test_a_pipe_in_a_code_span_is_escaped_and_elsewhere_becomes_a_slash():
    assert catalog.one_line("run `a | b` or c | d") == "run `a \\| b` or c / d"
    assert catalog.one_line(catalog.one_line("run `a | b` or c | d")) == "run `a \\| b` or c / d"  # idempotent
    assert catalog.first_sentence("Use `x|y` first. Then more.") == "Use `x\\|y` first."


def run_git(root, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}  # a commit hook sets GIT_INDEX_FILE and more
    subprocess.run(["git", "-C", str(root), "-c", "user.name=Test", "-c", "user.email=test@example.test", *args], check=True,
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)


def test_the_commit_line_marks_uncommitted_changes_to_skills_and_flows(tree):
    run_git(tree, "init", "-q")
    run_git(tree, "add", "-A")
    run_git(tree, "commit", "-q", "-m", "fixture")
    clean = catalog.git_commit(str(tree))
    assert re.fullmatch(r"[0-9a-f]{12}", clean)
    write(tree / "docs" / "note.md", "outside skills and flows")
    assert catalog.git_commit(str(tree)) == clean
    skill_md = tree / "skills" / "biz-demo" / "SKILL.md"
    write(skill_md, skill_md.read_text(encoding="utf-8") + "\n")
    assert catalog.git_commit(str(tree)) == clean + " (uncommitted changes)"
    assert "- Commit: %s (uncommitted changes)" % clean in catalog.build(str(tree), date=DATE)
