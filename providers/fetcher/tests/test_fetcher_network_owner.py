"""Only the fetcher passes a network to the container box, and the box's default command is what it always was."""
from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

import pytest

PROVIDERS = Path(__file__).resolve().parents[2]
ROOT = PROVIDERS.parent
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "tests"}
_spec = importlib.util.spec_from_file_location("workbench_container_for_network_owner", PROVIDERS / "_container.py")
box = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = box
_spec.loader.exec_module(box)


def callers_that_pass_a_network(root=ROOT):
    """Every call of a function named `argv` with a `network` keyword, in any Python file of the repository outside a tests folder."""
    found = []
    for path in sorted(root.rglob("*.py")):
        if set(path.relative_to(root).parts) & SKIP_DIRS:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "attr", getattr(node.func, "id", None)) == "argv" \
                    and any(k.arg == "network" for k in node.keywords):
                found.append(path.relative_to(root).as_posix())
    return found


def test_only_files_under_the_fetcher_pass_network_to_argv_anywhere_in_the_repository():
    found = callers_that_pass_a_network()
    assert found and all(name.startswith("providers/fetcher/") for name in found), found


def command(**extra):
    return box.argv("job-1", "sha256:img", ["go"], label="org.openhora.job", deadline=1760000000, mounts=[("/data/in", "/in", "ro"), ("/work/out", "/out", "rw")],
                    memory_mb=512, cpus=2, scratch_mb=64, platform="linux", **extra)


GOLDEN_LINUX = ['docker', 'run', '--rm', '--init', '--pull', 'never', '--name', 'job-1', '--label', 'org.openhora.job=1', '--label',
                'org.openhora.job.deadline=1760000000', '--network', 'none', '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
                '--pids-limit', '256', '--memory', '512m', '--memory-swap', '512m', '--cpus', '2', '--tmpfs', '/tmp:rw,noexec,nosuid,nodev,size=64m',
                '--tmpfs', '/scratch:rw,noexec,nosuid,nodev,size=64m,mode=1777']


def test_the_default_command_is_byte_for_byte_the_one_every_other_provider_has_always_had(monkeypatch):
    monkeypatch.setattr(box.os, "getuid", lambda: 1000)
    monkeypatch.setattr(box.os, "getgid", lambda: 1001)
    expected = GOLDEN_LINUX + ['--user', '1000:1001', '-v', '/data/in:/in:ro', '-v', '/work/out:/out:rw', 'sha256:img', 'go']
    assert command() == expected and command(network="none") == expected


@pytest.mark.parametrize("name", ["host", "bridge", "container:x", "openhora-fetch-in-XYZ", "openhora-fetch-in-0123456789abc", "openhora-fetch-x-0123456789ab",
                                  "openhora-fetch-in-0123456789ab ", "", None, 3])
def test_a_network_that_is_not_none_or_a_fetch_network_name_is_refused(name):
    with pytest.raises(box.ContainerError) as caught:
        command(network=name)
    assert caught.value.code == "bad_network"


@pytest.mark.parametrize("name", ["openhora-fetch-in-0123456789ab", "openhora-fetch-out-abcdef012345"])
def test_a_fetch_network_name_is_passed_through(name):
    argv = command(network=name)
    assert argv[argv.index("--network") + 1] == name


def test_a_planted_caller_elsewhere_would_be_found(tmp_path):
    (tmp_path / "providers").mkdir()
    (tmp_path / "providers" / "zz_planted_caller.py").write_text("import _container as box\nbox.argv('n', 'i', [], network='openhora-fetch-in-0123456789ab')\n")
    (tmp_path / "providers" / "other.py").write_text("import _container as box\nbox.argv('n', 'i', [])\n")
    assert callers_that_pass_a_network(tmp_path) == ["providers/zz_planted_caller.py"]
