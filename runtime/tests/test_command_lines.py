"""Tests of the one source of terminal commands (WP-9.14, items A-15 and A-18): `operations.command_line` takes the
checkout the process runs from and gives an absolute command, with the uv prefix when the process was started through
uv, and every sentence the operations layer returns that names a command is built by it. Offline; invented names.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_command_lines.py
"""
from __future__ import annotations

import ast
import shlex
import subprocess
import sys

import pytest

import standin_tree as st
from test_autonomy import tree  # noqa: F401  (a project whose configuration is accepted)

operations = st.load("operations")
ops = st.load("ops")

CHECKOUT = "/work/ai workbench"
UV = "uv run --with keyring==25.7.0 "


@pytest.fixture(autouse=True)
def plain_start(monkeypatch):
    """The tests run under uv themselves; a test says how the process started."""
    monkeypatch.setenv(operations.UV_MARK, "0")


def test_a_command_with_the_checkout_is_absolute_and_quotes_what_needs_it():
    got = operations.command_line("accept-config", "/p q", checkout=CHECKOUT, sha256="ab")
    assert got == "python3 '/work/ai workbench/runtime/cli.py' accept-config --project '/p q' --sha256 ab"
    assert operations.command_line("run-next", "/p", checkout="/w", tier="strong") == \
        "python3 /w/runtime/cli.py run-next --project /p --tier strong"
    assert operations.command_line("accept-config", "/p", sha256="ab") == "python3 runtime/cli.py accept-config --project /p --sha256 ab"


def test_a_process_started_through_uv_gets_the_prefix_and_one_started_without_it_does_not(monkeypatch):
    assert operations.command_line("status", "/p", checkout="/w") == "python3 /w/runtime/cli.py status --project /p"
    monkeypatch.setenv(operations.UV_MARK, "1")
    assert operations.command_line("status", "/p", checkout="/w") == UV + "python3 /w/runtime/cli.py status --project /p"
    assert operations.command_line("status", "/p") == "python3 runtime/cli.py status --project /p"  # a stored text names no checkout
    assert operations.command_line("status", "/p", checkout="/w", uv=False).startswith("python3 /w/")
    monkeypatch.setenv(operations.UV_MARK, "0")
    assert operations.command_line("run-next", "/p", checkout="/w", uv=True).startswith(UV + "python3 /w/")


def test_uv_is_told_from_the_interpreter_when_no_mark_says(monkeypatch):
    monkeypatch.delenv(operations.UV_MARK)
    monkeypatch.delenv("UV_RUN_RECURSION_DEPTH", raising=False)
    monkeypatch.delenv("UV_CACHE_DIR", raising=False)
    monkeypatch.setattr(sys, "prefix", "/home/u/.cache/uv/builds-v0/.tmpAbC")
    assert operations.started_with_uv() is True
    monkeypatch.setattr(sys, "prefix", "/home/u/.cache/uv/environments-v2/abc123")
    assert operations.started_with_uv() is True
    monkeypatch.setattr(sys, "prefix", "/home/u/.pyenv/versions/3.11.6")
    assert operations.started_with_uv() is False
    monkeypatch.setattr(sys, "prefix", "/home/u/builds-v0/project")  # a folder of that name that is not uv's
    assert operations.started_with_uv() is False


def test_the_pin_is_the_one_the_providers_pin():
    assert operations.KEYRING_PIN in (st.REPO / "providers" / "secrets" / "resolver.py").read_text(encoding="utf-8")


def test_the_service_start_line_is_spelled_here(monkeypatch):
    assert operations.service_line("/w", ["/p one", "/q"], uv=True, port=8765) == \
        UV + "python3 /w/runtime/service.py --project '/p one' --project /q --port 8765"
    assert operations.service_line("/w", ["/p"], uv=False) == "python3 /w/runtime/service.py --project /p"
    monkeypatch.setenv(operations.UV_MARK, "1")
    assert operations.service_line("/w", ["/p"]).startswith(UV)


def test_the_refusal_of_an_unaccepted_configuration_names_the_command_to_run_from_any_folder(tree, monkeypatch):
    project = str(tree["project"])
    config = tree["project"] / "docs" / "workbench" / "runtime.json"
    config.write_text(config.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(ops.OpsError) as refused:
        ops.status(project)
    sha = ops.project_config.load(project)["sha256"]
    assert refused.value.code == 3
    assert f"run: python3 {tree['tree']}/runtime/cli.py accept-config --project {project} --sha256 {sha}" in str(refused.value)
    monkeypatch.setenv(operations.UV_MARK, "1")
    with pytest.raises(ops.OpsError) as refused:
        ops.status(project)
    assert f"run: {UV}python3 {tree['tree']}/runtime/cli.py accept-config" in str(refused.value)


def test_the_next_of_a_widened_mode_is_absolute_too(tree):
    project = str(tree["project"])
    out = ops.set_mode(project, "planning", "autonomous")
    assert out["next"] == (f"python3 {tree['tree']}/runtime/cli.py accept-config --project {project} "
                           f"--sha256 {out['config_sha256']}")


def test_no_sentence_of_the_operations_layer_builds_a_command_but_through_the_one_helper():
    """ops.py spells a command in one function, _command, which adds the checkout the process runs from: a relative
    command in a returned sentence would fail from any other folder. (The text of an effect, stored before it is
    approved and naming no checkout, is built in effect_pull_request.py.)"""
    # the layer is ops.py and its siblings ops_*.py (CONS-1B): `_command` lives in ops_core.py with the other shared names
    trees = [ast.parse(p.read_text(encoding="utf-8")) for p in [st.RUNTIME / "ops.py", *sorted(st.RUNTIME.glob("ops_*.py"))]]
    inside = {id(n) for tree_ in trees for f in ast.walk(tree_) if isinstance(f, ast.FunctionDef) and f.name == "_command"
              for n in ast.walk(f)}
    calls = [n for tree_ in trees for n in ast.walk(tree_) if isinstance(n, ast.Call) and ast.unparse(n.func) == "operations.command_line"]
    assert calls and all(id(c) in inside for c in calls), [c.lineno for c in calls if id(c) not in inside]
    assert any(isinstance(n, ast.keyword) and n.arg == "checkout" for c in calls for n in c.keywords)


def test_uv_is_told_from_the_variable_uv_sets_for_a_project_environment_and_a_custom_cache(monkeypatch, tmp_path):
    monkeypatch.delenv(operations.UV_MARK)
    monkeypatch.delenv("UV_RUN_RECURSION_DEPTH", raising=False)
    monkeypatch.delenv("UV_CACHE_DIR", raising=False)
    monkeypatch.setattr(sys, "prefix", str(tmp_path / "project" / ".venv"))  # a uv project's own environment
    assert operations.started_with_uv() is False
    monkeypatch.setenv("UV_RUN_RECURSION_DEPTH", "1")  # `uv run` sets it for what it starts, whatever the environment
    assert operations.started_with_uv() is True
    monkeypatch.delenv("UV_RUN_RECURSION_DEPTH")
    cache = tmp_path / "mycache"
    monkeypatch.setenv("UV_CACHE_DIR", str(cache))
    monkeypatch.setattr(sys, "prefix", str(cache / "builds-v0" / ".tmpX"))  # a cache folder that is not named uv
    assert operations.started_with_uv() is True
    monkeypatch.setattr(sys, "prefix", str(tmp_path / "elsewhere" / "builds-v0"))
    assert operations.started_with_uv() is False


# --- ADJ-B3 (A-39): the commands that read the token file, built where the terminal's commands are spelled ----------------------------

AWKWARD = [
    "/home/demo/my shop/.openhora/service.token",
    '/home/demo/a "quoted" dir/service.token',
    "/home/demo/$HOME and $(whoami)/service.token",
    "/home/demo/back`tick`/service.token",
    "/home/demo/it's here/service.token",
    "/home/demo/all ' \" $ ` \\ ; & | < > ( ) * ? # ~ !/service.token",
    "/home/demo/caf\u00e9 \u2019 \u4e2d/service.token",
]


def powershell_literal(text):
    """Read back the one single-quoted PowerShell string after `-LiteralPath`: a quote character doubled is one quote
    character, and PowerShell counts the typographic single quotes as quotes too."""
    quotes = "'\u2018\u2019\u201a\u201b"
    assert text[0] in quotes, text
    out, i = "", 1
    while True:
        assert i < len(text), "the literal is never closed"
        if text[i] in quotes:
            if i + 1 < len(text) and text[i + 1] in quotes:
                out += text[i + 1]
                i += 2
                continue
            return out, text[i + 1:]
        out += text[i]
        i += 1


@pytest.mark.parametrize("path", AWKWARD)
def test_the_token_commands_quote_any_path_so_that_the_shell_reads_it_back_whole(path):
    got = operations.token_commands(path)
    assert set(got) == {"macos", "linux", "powershell"}
    assert shlex.split(got["macos"]) == ["pbcopy", "<", path], "one word for the path, whatever it holds"
    assert shlex.split(got["linux"]) == ["cat", path]
    head = "Get-Content -LiteralPath "
    assert got["powershell"].startswith(head) and got["powershell"].endswith(" | Set-Clipboard")
    literal, rest = powershell_literal(got["powershell"][len(head):])
    assert literal == path and rest == " | Set-Clipboard", "single quotes doubled, so the literal ends where the path ends"


def test_the_token_commands_of_a_plain_path_are_the_ones_the_page_shows(tmp_path):
    got = operations.token_commands("/home/demo/shop/.openhora/service.token")
    assert got == {"macos": "pbcopy < /home/demo/shop/.openhora/service.token", "linux": "cat /home/demo/shop/.openhora/service.token",
                   "powershell": "Get-Content -LiteralPath '/home/demo/shop/.openhora/service.token' | Set-Clipboard"}
    assert operations.token_commands("/home/demo/it's/service.token")["powershell"] == \
        "Get-Content -LiteralPath '/home/demo/it''s/service.token' | Set-Clipboard"
    assert operations.token_commands("/home/demo/it\u2019s/service.token")["powershell"] == \
        "Get-Content -LiteralPath '/home/demo/it\u2019\u2019s/service.token' | Set-Clipboard", "PowerShell reads a typographic quote as a quote"


@pytest.mark.parametrize("path", [pytest.param(p, id=f"awkward-{i}") for i, p in enumerate(AWKWARD[:5])])
def test_the_linux_command_run_by_a_shell_prints_the_file_of_an_awkward_path(path, tmp_path):
    """The proof the quoting is not only a string: a file with that very name is read by the command, in a real shell."""
    target = tmp_path / path.lstrip("/")
    target.parent.mkdir(parents=True)
    target.write_text("the file content\n", encoding="utf-8")
    command = operations.token_commands(str(target))["linux"]
    done = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=20)  # security-scan: allow shell-invocation -- the test is that a shell reads the quoted command back whole
    assert (done.returncode, done.stdout, done.stderr) == (0, "the file content\n", ""), command


@pytest.mark.parametrize("path", ["/home/demo/a\nb/service.token", "/home/demo/a\rb", "/home/demo/a\x00b", "/home/demo/a\x1b[31mb",
                                  "/home/demo/a\x7fb", "/home/demo/a\x85b", "/home/demo/a\u2028b", "/home/demo/a\u202eb",
                                  "/home/\udcff/x", "/home/demo/a\ue000b", "/home/demo/a\u0378b",
                                  "relative/service.token", "", None, 7, b"/home/demo/x"])
def test_a_path_with_a_control_character_or_no_absolute_path_gives_no_command(path):
    assert operations.token_commands(path) is None
