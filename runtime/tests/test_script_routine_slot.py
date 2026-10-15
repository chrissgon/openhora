"""A project script and the routines (package P9 with P6b): the kind is networked, so a routine that holds it is made only from the terminal
or the page (limit L33), and a routine's approved content holds the script's sha256, destinations, lock sha256 and the definition hash of
the script image, so that a change to any of them stops the routine and asks. Offline; invented names only.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_script_routine_slot.py
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import standin_tree as st

REPO = Path(__file__).resolve().parents[2]
steps = st.load("steps")
step_project_script = st.load("step_project_script")
routines = st.load("routines")
ops_routines = st.load("ops_routines")


def test_the_kind_is_networked_so_a_routine_that_holds_it_is_made_only_from_the_terminal_or_the_page():
    assert steps.kind_of("project-script").networked is True
    flow = {"tasks": [{"key": "script", "step": "project-script", "args": {"source": "figures"}}]}
    assert "reaches the network" in ops_routines.local_reason({}, flow)


def test_a_routines_approved_content_holds_the_script_its_destinations_its_lock_and_the_definition_of_the_image():
    args = {"script": "scripts/report.py", "sha256": "a" * 64, "source": "report", "destinations": ["b.example:443", "a.example:443"],
            "lock": "scripts/r.lock", "lock_sha256": "b" * 64}
    tasks = [{"key": "script", "step": "project-script", "args": args}, {"key": "think", "skill": "biz-market-analysis"}]
    slots = steps.routine_slots(tasks, str(REPO))
    assert slots == [{"key": "script", "kind": "project-script", "script": "scripts/report.py", "sha256": "a" * 64,
                      "destinations": ["a.example:443", "b.example:443"], "lock_sha256": "b" * 64, "image_definition": slots[0]["image_definition"]}]
    spec = importlib.util.spec_from_file_location("container_for_slot", REPO / "providers" / "script" / "container.py")
    container = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(container)
    assert slots[0]["image_definition"] == container.definition_hash(), "the runtime and the provider hash the image definition the same way"

    def digest(slot_tasks):
        body = routines.content(schedule={"every": "day", "at": "07:00"}, window_seconds=None, flow="weekly", template_sha256="t" * 64, params={},
                                skills={}, image="sha256:" + "1" * 64, scripts=steps.routine_slots(slot_tasks, str(REPO)), model="m", consent=False,
                                warning_sha256="w" * 64, providers=[])
        return routines.sha256_of(body)

    base = digest(tasks)
    for change in ({"sha256": "c" * 64}, {"destinations": ["a.example:443"]}, {"lock_sha256": "d" * 64}):
        changed = [{"key": "script", "step": "project-script", "args": {**args, **change}}, tasks[1]]
        assert digest(changed) != base, change
    assert digest(tasks) == base
    assert steps.routine_slots([tasks[1]], str(REPO)) == []
    assert steps.routine_slots(tasks, "/nowhere")[0]["image_definition"] is None


def test_a_change_to_the_image_definition_changes_the_slot(tmp_path):
    folder = tmp_path / "providers" / "script"
    folder.mkdir(parents=True)
    for name in step_project_script.SCRIPT_IMAGE_FILES:
        (folder / name).write_text(name)
    one = step_project_script.image_definition(str(tmp_path))
    (folder / "egress_proxy.py").write_text("changed")
    assert one and step_project_script.image_definition(str(tmp_path)) != one
