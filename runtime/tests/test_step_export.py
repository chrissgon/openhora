"""Tests of the file-output step kinds (runtime/step_export.py, package P8): `export-csv`, `export-xlsx`, `export-docx` and `export-pdf`
on the step engine. A stand-in renderer takes the place of the container, except for the CSV kind, which also runs the real program
of the renderer (providers/exporter/_render.py, the standard library only) so that a file comes out of a fixture,
offline, with the formula guard applied. The input is read and the output written the way the engine says: inside the footprint, never
the sources folder, no link followed. Fictional fixtures.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_step_export.py
"""
from __future__ import annotations

import csv
import hashlib
import importlib.util
import io
import os
import sys
from pathlib import Path

import pytest

import standin_tree as st
from test_steps_engine import FakeTask

steps = st.load("steps")
step_export = st.load("step_export")

RENDERER = st.REPO / "providers" / "exporter" / "_render.py"
REPORT = "# Quarterly report\n\nSales rose in the harbour towns.\n"
TABLE = 'name,note,qty\napple,=1+1,10\npear,+2,-5\nplum,@x,3\n"fig","tab\tin",4\n'


def real_renderer():
    spec = importlib.util.spec_from_file_location("render_for_the_export_tests", RENDERER)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def csv_through_the_real_program(tmp_path):
    module = real_renderer()

    def render(fmt, data):
        name, out, counts, tools = module.render(fmt, data, str(tmp_path / "work"))
        return {"output": out, "tool_versions": tools}
    return render


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "project"
    (root / "docs").mkdir(parents=True)
    return root


def context(project, fmt, args, services, protected=lambda path: False):
    kind = steps.kind_of(f"export-{fmt}")
    checked = kind.check(args)
    task = FakeTask()
    return kind, task, task.context(checked, services=services, project=str(project), footprint=steps.footprint_of(kind, checked),
                                    protected=protected)


def run(project, fmt, args, services, protected=lambda path: False):
    kind, task, ctx = context(project, fmt, args, services, protected)
    return steps.run(ctx, kind, steps.new_state(kind)), task


def test_the_four_kinds_are_registered_and_none_starts_on_its_own():
    for fmt in ("csv", "xlsx", "docx", "pdf"):
        kind = steps.kind_of(f"export-{fmt}")
        assert kind.order == ("render",) and kind.unattended is False and kind.gates == {} and kind.effectful == ()


def test_the_footprint_is_the_one_output_file_under_docs_outputs():
    plan = steps.plan_task("export-pdf", {"input": "docs/report.md", "name": "q3-report"}, key="k", title="t", text="x")
    assert plan["footprint"] == ["docs/outputs/q3-report.pdf"] and plan["step"] == "export-pdf" and plan["agent"] == steps.OWNER
    plan = steps.plan_task("export-xlsx", {"input": "docs/t.csv", "name": "t"}, key="k", title="t", text="x")
    assert plan["footprint"] == ["docs/outputs/t.xlsx"]


@pytest.mark.parametrize("fmt,args", [
    ("csv", {"input": "docs/a.md", "name": "a"}), ("xlsx", {"input": "docs/a.md", "name": "a"}),
    ("docx", {"input": "docs/a.csv", "name": "a"}), ("pdf", {"input": "docs/a.csv", "name": "a"}),
    ("csv", {"input": "other/a.csv", "name": "a"}), ("csv", {"input": "docs/../a.csv", "name": "a"}),
    ("csv", {"input": "/etc/a.csv", "name": "a"}), ("csv", {"input": "docs/a.csv", "name": "A b"}),
    ("csv", {"input": "docs/a.csv", "name": "../x"}), ("csv", {"input": "docs/a.csv", "name": ""}),
    ("csv", {"input": "docs/a.csv"}), ("csv", {"input": "docs/a.csv", "name": "a", "extra": 1}), ("csv", "no"), ("csv", {"input": 3, "name": "a"}),
])
def test_the_arguments_are_checked_when_the_task_is_planned(fmt, args):
    with pytest.raises(steps.StepFailure) as refused:
        steps.plan_task(f"export-{fmt}", args, key="k", title="t", text="x")
    assert refused.value.code == "bad_args"


@pytest.mark.parametrize("cell", ["=1+1", "+1+1", "-1+1", "@SUM(A1:A2)", "\tcmd", "\rcmd", "\ncmd", "\uff1d1+1", "  =lead", "\u200b=lead"])
def test_limit_32_a_cell_that_starts_with_a_formula_character_is_written_as_text(project, tmp_path, cell):
    quoted = '"' + cell.replace('"', '""') + '"'
    (project / "docs" / "table.csv").write_text(f"name,note\nrow,{quoted}\n", encoding="utf-8", newline="")
    out, _ = run(project, "csv", {"input": "docs/table.csv", "name": "table"}, {"render": csv_through_the_real_program(tmp_path)})
    assert out["ok"] is True
    rows = list(csv.reader(io.StringIO((project / "docs" / "outputs" / "table.csv").read_bytes().decode("utf-8").lstrip("\ufeff"), newline="")))
    assert rows[1] == ["row", "'" + cell], "the cell is the same text with one quote in front of it"


def test_a_csv_comes_out_of_a_fixture_with_each_guarded_cell_written_as_text(project, tmp_path):
    (project / "docs" / "table.csv").write_text(TABLE, encoding="utf-8")
    out, task = run(project, "csv", {"input": "docs/table.csv", "name": "table"}, {"render": csv_through_the_real_program(tmp_path)})
    assert out["ok"] is True and out["done"] is True and task.state == "running" or out["done"]
    written = (project / "docs" / "outputs" / "table.csv").read_bytes()
    rows = list(csv.reader(io.StringIO(written.decode("utf-8").lstrip("\ufeff"), newline="")))
    assert rows[0] == ["name", "note", "qty"] and rows[1] == ["apple", "'=1+1", "10"] and rows[2] == ["pear", "'+2", "'-5"]
    assert rows[3] == ["plum", "'@x", "3"] and rows[4] == ["fig", "tab\tin", "4"]
    result = task.saved["steps"]["render"]["result"]
    assert result["path"] == "docs/outputs/table.csv" and result["bytes"] == len(written)
    assert result["sha256"] == hashlib.sha256(written).hexdigest() and result["input_sha256"] == hashlib.sha256(TABLE.encode()).hexdigest()


@pytest.mark.parametrize("fmt,suffix,source", [("xlsx", "csv", TABLE), ("docx", "md", REPORT), ("pdf", "md", REPORT)])
def test_each_kind_writes_what_its_renderer_returned_into_docs_outputs_and_records_closed_facts(project, fmt, suffix, source):
    (project / "docs" / f"in.{suffix}").write_text(source, encoding="utf-8")
    seen = {}

    def render(kind, data):
        seen.update(kind=kind, data=data)
        return {"output": b"%BYTES-" + fmt.encode(), "tool_versions": {"tool": "1.0"}}

    out, task = run(project, fmt, {"input": f"docs/in.{suffix}", "name": "result"}, {"render": render})
    assert out["done"] is True and seen == {"kind": fmt, "data": source.encode()}
    assert (project / "docs" / "outputs" / f"result.{fmt}").read_bytes() == b"%BYTES-" + fmt.encode()
    result = task.saved["steps"]["render"]["result"]
    assert result["tools"] == {"tool": "1.0"} and result["path"] == f"docs/outputs/result.{fmt}"
    assert set(result) == {"path", "bytes", "sha256", "input_sha256", "tools"}, "closed words and numbers, never the text"


def test_a_rerun_replaces_the_file_whole_and_never_half(project):
    (project / "docs" / "in.md").write_text(REPORT, encoding="utf-8")
    for body in (b"first", b"second"):
        run(project, "docx", {"input": "docs/in.md", "name": "same"}, {"render": lambda fmt, data, b=body: {"output": b}})
    assert (project / "docs" / "outputs" / "same.docx").read_bytes() == b"second"
    assert sorted(p.name for p in (project / "docs" / "outputs").iterdir()) == ["same.docx"], "no temporary file is left"


def test_an_input_that_is_missing_a_link_a_folder_or_too_large_is_not_rendered(project):
    services = {"render": lambda fmt, data: pytest.fail("rendered")}
    out, _ = run(project, "csv", {"input": "docs/none.csv", "name": "a"}, services)
    assert out["ok"] is False and out["code"] == "input_missing"
    (project / "docs" / "real.csv").write_text("a\n1\n", encoding="utf-8")
    (project / "docs" / "link.csv").symlink_to(project / "docs" / "real.csv")
    out, _ = run(project, "csv", {"input": "docs/link.csv", "name": "a"}, services)
    assert out["ok"] is False and out["code"] == "input_missing"
    (project / "docs" / "folder.csv").mkdir()
    out, _ = run(project, "csv", {"input": "docs/folder.csv", "name": "a"}, services)
    assert out["ok"] is False and out["code"] == "input_missing"
    (project / "docs" / "big.csv").write_bytes(b"a\n" + b"x" * (step_export.INPUT_MAX + 1))
    out, _ = run(project, "csv", {"input": "docs/big.csv", "name": "a"}, services)
    assert out["ok"] is False and out["code"] == "input_too_large"


def test_an_input_that_holds_a_credential_is_not_rendered_and_the_value_is_nowhere_in_the_record(project):
    key = "sk-" + "ant-" + "api03-" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6"
    (project / "docs" / "notes.md").write_text(f"The key is {key}\n", encoding="utf-8")
    out, task = run(project, "docx", {"input": "docs/notes.md", "name": "a"}, {"render": lambda fmt, data: pytest.fail("rendered")})
    assert out["ok"] is False and out["code"] == "input_refused"
    assert key not in repr(task.saved) and key not in repr(task.moves) and not (project / "docs" / "outputs").exists()


def test_an_input_inside_the_sources_folder_is_refused_and_so_is_an_output_there(project):
    (project / "docs" / "kept").mkdir()
    (project / "docs" / "kept" / "t.csv").write_text("a\n1\n", encoding="utf-8")
    inside = lambda path: "/docs/kept" in path or "/docs/outputs" in path
    out, _ = run(project, "csv", {"input": "docs/kept/t.csv", "name": "a"}, {"render": lambda fmt, data: pytest.fail("rendered")}, inside)
    assert out["ok"] is False and out["code"] == "protected_path"
    (project / "docs" / "t.csv").write_text("a\n1\n", encoding="utf-8")
    out, _ = run(project, "csv", {"input": "docs/t.csv", "name": "a"}, {"render": lambda fmt, data: {"output": b"x"}}, inside)
    assert out["ok"] is False and out["code"] == "protected_path", "write_file refuses what the context protects"


def test_a_symlinked_output_folder_is_never_followed(project, tmp_path):
    (project / "docs" / "t.csv").write_text("a\n1\n", encoding="utf-8")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (project / "docs" / "outputs").symlink_to(elsewhere)
    out, _ = run(project, "csv", {"input": "docs/t.csv", "name": "a"}, {"render": lambda fmt, data: {"output": b"x"}})
    assert out["ok"] is False and out["code"] == "path_unsafe" and list(elsewhere.iterdir()) == []


def test_a_renderer_that_fails_or_returns_nothing_fails_the_step_with_a_closed_code(project):
    (project / "docs" / "t.csv").write_text("a\n1\n", encoding="utf-8")

    def broken(fmt, data):
        raise steps.StepFailure("render_failed", "renderer", "renderer")
    out, _ = run(project, "csv", {"input": "docs/t.csv", "name": "a"}, {"render": broken})
    assert out["ok"] is False and out["code"] == "render_failed"
    for answer in ({"output": b""}, {"output": "text"}, {}, None):
        out, _ = run(project, "csv", {"input": "docs/t.csv", "name": "a"}, {"render": lambda fmt, data, a=answer: a})
        assert out["ok"] is False and out["code"] in ("render_failed", "step_output_invalid"), answer


class FakeResolver:
    """The resolver of providers/resolve.py, as step_export reaches the exporter through it: the class, the verb and the arguments are
    recorded, the folder the provider writes to is filled by `writes`, or the call fails with `fails`."""

    class ProviderCallError(Exception):
        def __init__(self, kind, reason=""):
            super().__init__(f"{kind}: {reason}")
            self.kind, self.reason = kind, reason

    def __init__(self, writes=None, fails=None, tools=None):
        self.writes, self.fails, self.tools, self.seen = writes, fails, tools or {"pandoc": "3.1"}, []

    def provider_environment(self, cls, env=None, passes=()):
        return {"PATH": "/usr/bin"}

    def call(self, cls, verb, args, **kwargs):
        flags = dict(zip(args[0::2], args[1::2]))
        self.seen.append((cls, verb, flags, kwargs.get("env")))
        if self.fails:
            raise self.ProviderCallError(self.fails)
        assert Path(flags["--input"]).read_bytes() and oct(Path(flags["--out-dir"]).stat().st_mode & 0o777) == "0o700"
        for name, data in (self.writes or {}).items():
            (Path(flags["--out-dir"]) / name).write_bytes(data)
        return {"renderer": "document", "tool_versions": self.tools}


def with_resolver(monkeypatch, fake):
    project_config = st.load("project_config")
    monkeypatch.setattr(project_config, "resolver", lambda root: fake)


def test_the_default_renderer_is_the_provider_of_the_class_called_through_the_resolver(project, monkeypatch):
    (project / "docs" / "t.csv").write_text("a\n1\n", encoding="utf-8")
    fake = FakeResolver(writes={"output.csv": b"BYTES"})
    with_resolver(monkeypatch, fake)
    out, task = run(project, "csv", {"input": "docs/t.csv", "name": "a"}, {})
    assert out["done"] is True and (project / "docs" / "outputs" / "a.csv").read_bytes() == b"BYTES"
    cls, verb, flags, env = fake.seen[0]
    assert (cls, verb, flags["--format"]) == ("exporter:document", "render", "csv") and env == {"PATH": "/usr/bin"}
    assert not Path(flags["--input"]).exists(), "the private copy of the input is removed"
    assert task.saved["steps"]["render"]["result"]["tools"] == {"pandoc": "3.1"}


def test_an_image_not_built_says_how_to_build_it_and_writes_nothing(project, monkeypatch):
    (project / "docs" / "t.csv").write_text("a\n1\n", encoding="utf-8")
    with_resolver(monkeypatch, FakeResolver(fails="not-configured"))
    out, _ = run(project, "csv", {"input": "docs/t.csv", "name": "a"}, {})
    assert out["ok"] is False and out["code"] == "not_configured" and "container.py build --confirmed" in out["next"]
    assert not (project / "docs" / "outputs").exists()


def test_what_the_exporter_leaves_in_its_folder_is_read_back_with_the_same_care(project, monkeypatch):
    (project / "docs" / "t.csv").write_text("a\n1\n", encoding="utf-8")
    for writes in ({}, {"output.csv": b"x", "other": b"y"}, {"other.csv": b"x"}, {"output.csv": b"x" * (step_export.OUTPUT_MAX + 1)}):
        with_resolver(monkeypatch, FakeResolver(writes=writes))
        out, _ = run(project, "csv", {"input": "docs/t.csv", "name": "a"}, {})
        assert out["ok"] is False and out["code"] == "render_failed", writes
    with_resolver(monkeypatch, FakeResolver(fails="failed"))
    assert run(project, "csv", {"input": "docs/t.csv", "name": "a"}, {})[0]["code"] == "render_failed"
    assert not (project / "docs" / "outputs").exists()
