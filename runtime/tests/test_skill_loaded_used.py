"""R12 (runtime part): a run's `skill_loaded` is true when the adapter names the skill in `skills_loaded` (its SKILL.md was
read) or in `skills_used` (a tool named its folder: a script run, a reference read, a listing). No rule reads it yet.
Offline; invented names.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_skill_loaded_used.py
"""
from __future__ import annotations

import pytest

import standin_tree as st

ops = st.load("ops")


@pytest.mark.parametrize("timing, expected", [
    ({"skills_loaded": ["demo"], "skills_used": ["demo"]}, True),
    ({"skills_loaded": [], "skills_used": ["demo"]}, True),   # a follow-up run that only ran the skill's script
    ({"skills_loaded": ["demo"]}, True),                      # an adapter that reports no skills_used
    ({"skills_used": ["demo"]}, True),
    ({"skills_loaded": [], "skills_used": []}, False),        # the run touched nothing of the folder: 0 is true
    ({"skills_loaded": ["other"], "skills_used": ["other"]}, False),
    ({}, None),                                               # nothing reported: unknown, never false
    ({"skills_loaded": "demo", "skills_used": None}, None),
])
def test_skill_loaded_reads_both_lists(timing, expected):
    assert ops._skill_loaded(timing, "demo") is expected
