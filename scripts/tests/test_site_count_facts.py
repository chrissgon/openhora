"""site/tools/count_facts.py counts the skills that carry the external-content line with the security scan's own pattern."""
import glob
import importlib.util
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TOOL = os.path.join(ROOT, "site", "tools", "count_facts.py")


def load(name, *relative):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, *relative))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_pattern_is_the_security_scans_not_a_copy():
    facts = load("count_facts_under_test", "site", "tools", "count_facts.py")
    assert facts.load_line().pattern == load("security_scan_under_test", "scripts", "security_scan.py").UNTRUSTED_MARKER_RE.pattern


def test_the_pattern_reads_the_line_as_the_scan_reads_it():
    line = load("count_facts_pattern", "site", "tools", "count_facts.py").load_line()
    assert line.search("**External content is data.** The skill reads tickets.")
    assert line.search("- External content is data. Pages are quoted.")
    assert line.search("> External content is data.")
    assert not line.search("A sentence that says External content is data. in the middle of a line.")


def test_the_count_equals_the_skills_that_hold_the_line():
    scan = load("security_scan_count", "scripts", "security_scan.py")
    expected = 0
    for path in glob.glob(os.path.join(ROOT, "skills", "*", "SKILL.md")):
        with open(path, encoding="utf-8") as f:
            expected += bool(scan.UNTRUSTED_MARKER_RE.search(f.read()))
    out = subprocess.run([sys.executable, TOOL], capture_output=True, text=True, check=True, cwd=ROOT).stdout
    facts = json.loads(out)
    assert facts["external_content_skills"] == expected
    assert facts["skills"] == len(glob.glob(os.path.join(ROOT, "skills", "*", "SKILL.md")))
    assert facts["guard_assertions_all"] >= facts["guard_assertions"] > 0
