"""Tests of the Control room screen that look at its presentation (R4-S): the classes its modules build against the stylesheet and the Connections tab's rows. A package
for the Control room edits this file and `test_interface_control.py`, `interface/css/control.css` and `interface/js/views/control*.js`; the tests of the shared files
(`test_interface_files.py`: routes, writes, text as text) stay where they are. The tests below were moved here from the shared files with their names and their
assertions unchanged; each reads what it needs through the module it came from.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interface_r4_control.py
"""
from __future__ import annotations

import re

from interface_css import interface_css
from test_interface_files import INTERFACE, control_modules
from test_interface_plates_meters import CONTROL, needs_node, run_node


# --- moved from test_interface_files.py ------------------------------------------------------------------------------------------


def test_every_wb_class_the_control_room_builds_is_a_rule_of_the_stylesheet():
    css = interface_css()
    defined = set(re.findall(r"\.(wb-[a-z0-9-]+)", css))
    markers = {"is-open", "is-wide", "is-selected"}  # state words, not classes of their own
    for path in control_modules():
        text = path.read_text(encoding="utf-8")
        for group in re.findall(r"class: `?\"?([^\"`]+)[\"`]", text):
            for name in re.findall(r"\bwb-[a-z0-9-]+", group.split("${")[0]):
                if name.endswith("-"):
                    continue
                assert name in defined or name in markers, f"{path.name} builds the class {name}, which the stylesheets do not draw"
    # the three tab words the hash carries are the router's, and the page reaches the screen from its one router
    main = (INTERFACE / "js" / "main.js").read_text(encoding="utf-8")
    assert 'import { createControlView } from "./views/control.js";' in main and 'route.screen === "control"' in main
    model = (INTERFACE / "js" / "views" / "control-model.js").read_text(encoding="utf-8")
    assert re.search(r'TABS = Object\.freeze\(\[\["skills", "Skills"\], \["costs", "Costs"\], \["connections", "Connections"\]\]\)', model)

# --- moved from test_interface_plates_meters.py ----------------------------------------------------------------------------------


@needs_node
def test_the_connections_tab_shows_each_problem_the_service_found_at_its_start_and_the_command_that_starts_it_again(tmp_path):
    got = run_node(tmp_path, CONTROL)
    whats = [r[0] for r in got["rows"]]
    assert whats == ["Secret store", "Credential", "Image", "Dispatch", "Problem"], "one row per verdict that is not ok, in this order"
    commands = {r[0]: r[2] for r in got["rows"]}
    assert commands["Secret store"].startswith("uv run --with keyring==25.7.0 python3 /ck/runtime/service.py"), "the service's `start`, verbatim"
    assert commands["Dispatch"] == commands["Secret store"], "dispatch off is started again the same way"
    assert commands["Credential"] is None and commands["Image"] is None and commands["Problem"] is None, "no command exists for these: the sentence only"
    assert got["ok"] == [] and got["none"] == [[], []]
    assert got["card"]["rows"] == 5 and len(got["card"]["codes"]) == 2 and got["card"]["copies"] == 2
    assert got["cardNone"] == 0
