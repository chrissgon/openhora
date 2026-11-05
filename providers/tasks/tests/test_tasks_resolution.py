"""How the two tasks classes of package CB-4 resolve (providers/resolve.py): `integration:tasks` is the folder `providers/tasks/` with the implementations `google` and `microsoft`, chosen by
INTEGRATION_TASKS_PROVIDER alone (an integration never shares a fallback variable with another); `writer:tasks` is served by `google-tasks` and `microsoft-todo` of `providers/writer/`, each
declaring the one class it serves, so a caller of `writer:tasks` can never start the writer of files, mail or the calendar, and none of those can be started for `writer:tasks`. Neither class is
listed in contracts/environment.md: the runtime uses them (package CB-5), no skill may require them. No provider is started and no credential is read.

Run: uv run --with pytest==9.1.1 pytest providers/tasks/tests/test_tasks_resolution.py
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location("resolve_for_the_tasks_classes", REPO / "providers" / "resolve.py")
resolve = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(resolve)


def test_the_reader_class_is_the_folder_tasks_with_its_own_variable_only():
    assert resolve.split_class("integration:tasks") == ("integration", "tasks") and resolve.folder("integration:tasks") == "tasks"
    assert resolve.variables("integration:tasks") == ["INTEGRATION_TASKS_PROVIDER"]
    assert resolve.implementations("integration:tasks", root=REPO) == ["google", "microsoft"]
    assert resolve.serving("integration:tasks", root=REPO) == ["google", "microsoft"]


def test_the_writer_class_is_served_by_exactly_the_two_tasks_writers_and_by_no_other_writer():
    assert resolve.implementations("writer:tasks", root=REPO) == ["google-tasks", "microsoft-todo"]
    for other in ("gdrive", "gmail", "google-calendar", "onedrive", "outlook-calendar", "outlook-mail"):
        assert resolve.serves_class("writer:tasks", other, root=REPO, strict=True) is False, other
    for name in ("google-tasks", "microsoft-todo"):
        assert resolve.serves_class("writer:tasks", name, root=REPO, strict=True) is True
        for cls in ("writer:calendar", "writer:mailbox", "writer:files"):
            assert resolve.serves_class(cls, name, root=REPO, strict=True) is False, (cls, name)


def test_a_writer_class_names_its_implementation_explicitly_and_the_reader_class_is_a_known_integration():
    assert resolve.variables("writer:tasks") == ["WRITER_TASKS_PROVIDER", "WRITER_PROVIDER"]
    assert resolve.folder("writer:tasks") == "writer"
    for cls in ("integration:tasks", "writer:tasks"):
        assert cls not in resolve.LISTED, "runtime-only: no skill may require it, and contracts/environment.md does not list it"
    environment = (REPO / "contracts" / "environment.md").read_text(encoding="utf-8")
    assert "integration:tasks" not in environment and "writer:tasks" not in environment


def test_the_implementation_files_are_what_the_resolver_lists_and_no_helper_is_one():
    assert sorted(p.name for p in (REPO / "providers" / "tasks").glob("*.py")) == ["google.py", "microsoft.py"]
    assert not any(name.startswith("_") for name in resolve.implementations("writer:tasks", root=REPO))
    assert (REPO / "providers" / "_writer_tasks.py").is_file() and "_writer_tasks" not in resolve.implementations_in("writer", root=REPO)


def test_vacuity_a_writer_that_declared_no_class_would_serve_every_class_unless_asked_strictly(tmp_path):
    """The oracle: copy the tree's resolver rule to a folder with a writer that declares nothing; non-strict it serves a class it should not, strict it serves none."""
    (tmp_path / "providers" / "writer").mkdir(parents=True)
    (tmp_path / "providers" / "writer" / "stray.py").write_text("print('no SERVES line')\n", encoding="utf-8")
    assert resolve.serves_class("writer:tasks", "stray", root=tmp_path) is True
    assert resolve.serves_class("writer:tasks", "stray", root=tmp_path, strict=True) is False
