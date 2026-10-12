"""The roles of the runtime (runtime/roles.py, runtime/roles.json): the skills the runtime names, the code areas and the
packs in use are data, bound to the skills and packs of the repository, and each module reads its constant from them.
Offline; nothing is run.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_roles.py
"""
from __future__ import annotations

import json
import sys

import pytest

import standin_tree as st

roles = st.load("roles")
router = st.load("router")
plan = st.load("plan")
workcopy = st.load("workcopy")
manifest = st.load("manifest")

REPO = st.REPO


def test_every_role_names_a_skill_that_exists_and_the_packs_resolve():
    data = roles.load()
    for key in ("router", "brief", "subtask"):
        assert (REPO / "skills" / data[key] / "SKILL.md").is_file(), key
    assert data["packs_in_use"] and all((REPO / "packs" / f"{p}.txt").is_file() for p in data["packs_in_use"])
    in_use = manifest.skills_in_use(str(REPO))
    assert in_use, "the packs in use select no skill"
    assert data["router"] in in_use and data["brief"] in in_use, "the router and the brief skill are in the packs in use"


def test_each_module_reads_its_constant_from_the_file():
    data = json.loads((REPO / "runtime" / "roles.json").read_text(encoding="utf-8"))
    assert router.ROUTER_SKILL == data["router"]
    assert plan.BRIEF_SKILL == data["brief"] and plan.SUBTASK_SKILL == data["subtask"]
    assert workcopy.CODE_AREAS == tuple(data["code_areas"])
    assert manifest.PACKS_IN_USE == tuple(data["packs_in_use"])


def test_the_areas_are_the_closed_list_of_the_validator():
    sys.path.insert(0, str(REPO / "scripts"))
    try:
        import validate
    finally:
        sys.path.remove(str(REPO / "scripts"))
    assert set(roles.AREAS) == set(validate.AREAS)


def write(tmp_path, data):
    file = tmp_path / "roles.json"
    file.write_text(json.dumps(data) if not isinstance(data, str) else data, encoding="utf-8")
    return str(file)


def good():
    return json.loads((REPO / "runtime" / "roles.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("change, named", [
    (lambda d: d.pop("router"), "missing key `router`"),
    (lambda d: d.update(extra=1), "unknown key `extra`"),
    (lambda d: d.update(brief="no-such-skill"), "`brief` is 'no-such-skill'"),
    (lambda d: d.update(subtask=3), "`subtask` is 3"),
    (lambda d: d.update(code_areas=[]), "`code_areas` is not a non-empty list"),
    (lambda d: d.update(code_areas=["engineering", "plumbing"]), "'plumbing'"),
    (lambda d: d.update(packs_in_use=["business", "no-such-pack"]), "'no-such-pack'"),
    (lambda d: d.update(packs_in_use="business"), "`packs_in_use` is not a non-empty list"),
])
def test_a_roles_file_that_is_not_well_formed_is_refused_naming_the_key(tmp_path, change, named):
    data = good()
    change(data)
    with pytest.raises(roles.RolesError) as raised:
        roles.load(file=write(tmp_path, data))
    assert named in str(raised.value)


def test_a_file_that_is_not_json_or_not_an_object_is_refused(tmp_path):
    for body in ("{", "[]"):
        with pytest.raises(roles.RolesError):
            roles.load(file=write(tmp_path, body))
    with pytest.raises(roles.RolesError):
        roles.load(file=str(tmp_path / "missing.json"))


def test_the_design_chain_has_one_owner_each_and_every_skill_of_a_pack_in_use_has_a_whole_manifest():
    """A-36 part 1: `product-prd`, `design-execute` and `design-handoff` are in the design agent's pack, so the planner can chain the design
    skills one by one; each is owned by exactly one enabled agent (`plan.agent_of`) and has the manifest a task needs."""
    agents = {name: sorted(plan.resolve_pack(name, str(REPO)))
              for name in ("business", "brand", "design", "planning", "code")}
    for skill in ("product-prd", "design-ux-flows", "design-system", "design-brief", "design-execute", "design-handoff"):
        assert plan.agent_of(skill, agents) == "design", skill
    for skill in ("product-prd", "design-execute", "design-handoff"):
        assert skill in manifest.skills_in_use(str(REPO))
        assert manifest.load(str(REPO), skill)["skill"] == skill
