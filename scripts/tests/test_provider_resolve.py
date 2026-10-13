"""Offline tests of providers/resolve.py: a requirement class resolves to one provider script.

They live here because scripts/test_dirs.py discovers providers/<class>/tests, not a tests folder directly
under providers/. Every workbench below is a temporary folder with empty provider files; nothing is run.

Run: uv run --with pytest pytest scripts/tests/test_provider_resolve.py
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "providers" / "resolve.py"
spec = importlib.util.spec_from_file_location("workbench_provider_resolve_under_test", SCRIPT)
resolve = importlib.util.module_from_spec(spec)
spec.loader.exec_module(resolve)


def workbench(tmp_path, *files, **serving):
    """A workbench with empty provider files. A keyword gives a publisher the platforms it declares:
    workbench(tmp, "publisher/one.py", one=("chirp",)) writes `PLATFORMS = ("chirp",)` into publisher/one.py."""
    root = tmp_path / "wb"
    for rel in files:
        path = root / "providers" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        platforms = serving.get(path.stem)
        path.write_text("" if platforms is None else f"import nothing_installed\nPLATFORMS = {tuple(platforms)!r}\n")
    (root / "providers").mkdir(parents=True, exist_ok=True)
    return root


def cli(args, env=None):
    base = {"PATH": "/usr/bin:/bin"}
    return subprocess.run([sys.executable, str(SCRIPT), *args], env={**base, **(env or {})},
                          capture_output=True, text=True, timeout=30)


def test_class_maps_to_its_folder_and_variables():
    assert resolve.folder("publisher:chirp") == "publisher"
    assert resolve.folder("generator:image") == "generator"
    assert resolve.folder("integration:vcs") == "vcs"
    assert resolve.folder("integration:issue-tracker") == "issue-tracker"
    assert resolve.variables("publisher:chirp") == ["PUBLISHER_CHIRP_PROVIDER", "PUBLISHER_PROVIDER"]
    assert resolve.variables("publisher:<platform>") == ["PUBLISHER_PROVIDER"]  # a placeholder means "any"
    assert resolve.variables("generator:image") == ["GENERATOR_IMAGE_PROVIDER", "GENERATOR_PROVIDER"]
    assert resolve.variables("integration:vcs") == ["INTEGRATION_VCS_PROVIDER"]  # no shared fallback
    assert resolve.variables("integration:issue-tracker") == ["INTEGRATION_ISSUE_TRACKER_PROVIDER"]


RENAMED = [("reader:email", "mailbox", "MAILBOX_PROVIDER"), ("sender:email", "mailer", "MAILER_PROVIDER"),
           ("scheduler:job", "scheduler", "SCHEDULER_PROVIDER"), ("store:runtime", "store", "STORE_PROVIDER")]


@pytest.mark.parametrize("cls, old, variable", RENAMED)
def test_the_four_renamed_classes_keep_their_folder_and_their_variable(cls, old, variable):
    """Decision 14a: only the class name changed. By the derivation the other classes use, reader:email would
    give providers/reader/ and READER_EMAIL_PROVIDER; the table keeps what exists on users' machines."""
    assert resolve.folder(cls) == old and resolve.variables(cls) == [variable]
    assert resolve.folder(old) == old and resolve.variables(old) == [variable]  # the old name is an alias
    assert resolve.canonical(old) == cls and resolve.canonical(cls) == cls
    assert resolve.split_class(old) == resolve.split_class(cls) == tuple(cls.split(":"))
    assert cls in resolve.LISTED and old not in resolve.LISTED


def test_an_old_name_resolves_to_the_same_script_and_reports_the_new_class(tmp_path):
    root = workbench(tmp_path, "store/sqlite.py", "mailbox/gmail.py", "scheduler/launchd.py", "scheduler/systemd.py")
    for cls, old, variable in RENAMED:
        if old == "mailer":
            continue  # no implementation ships
        new = resolve.resolve(cls, root=root, env={}, platform="darwin")
        assert resolve.resolve(old, root=root, env={}, platform="darwin") == new and new["class"] == cls
        assert new["variables"] == [variable] and f"/providers/{old}/" in new["path"]
    r = cli(["--class", "store"], {"WORKBENCH_ROOT": str(root)})
    assert r.returncode == 0 and r.stdout.strip().endswith("providers/store/sqlite.py")
    assert "old name of the class store:runtime" in r.stderr
    assert cli(["--class", "store:runtime"], {"WORKBENCH_ROOT": str(root)}).stderr == ""


@pytest.mark.parametrize("cls", ["nope", "../x:y", "integration", "publisher:Chirp Net", "a:b:c", "", "scheduler/../x",
                                 "scheduler:foo", "store:x", "mailbox:x", "reader:rss", "reader", "sender", "mailbox:email",
                                 # RS4: a bare role is not a class; every class is <role>:<target>
                                 "publisher", "search", "generator", "publisher:"])
def test_unknown_class_is_refused(cls):
    with pytest.raises(resolve.UnknownClass):
        resolve.resolve(cls, env={})


def test_environment_wins_most_specific_first(tmp_path):
    root = workbench(tmp_path, "publisher/one.py", "publisher/two.py", "publisher/auth.py",
                     one=("chirp",), two=("chirp", "flock"))
    env = {"PUBLISHER_PROVIDER": "one", "PUBLISHER_CHIRP_PROVIDER": "two"}
    got = resolve.resolve("publisher:chirp", root=root, env=env)
    assert (got["implementation"], got["source"], got["variable"]) == ("two", "environment", "PUBLISHER_CHIRP_PROVIDER")
    assert got["path"] == str(root.resolve() / "providers" / "publisher" / "two.py")
    got = resolve.resolve("publisher:chirp", root=root, env={"PUBLISHER_PROVIDER": "one"})
    assert (got["implementation"], got["variable"]) == ("one", "PUBLISHER_PROVIDER")
    assert resolve.implementations("publisher:chirp", root=root) == ["one", "two"]  # auth.py is a helper


# --- a class with a parameter: the implementations declare the platforms they serve (RS1) -------------

def test_a_publisher_is_chosen_among_the_implementations_that_serve_the_platform(tmp_path):
    root = workbench(tmp_path, "publisher/one.py", one=("chirp",))
    assert resolve.resolve("publisher:chirp", root=root, env={})["implementation"] == "one"
    with pytest.raises(resolve.Unresolved) as e:  # before: the only implementation resolved for any platform
        resolve.resolve("publisher:flock", root=root, env={})
    assert "serves flock" in str(e.value) and "PLATFORMS" in str(e.value)


def test_a_second_publisher_does_not_break_the_first(tmp_path):
    root = workbench(tmp_path, "publisher/one.py", "publisher/two.py", one=("chirp",), two=("flock",))
    for platform, name in (("chirp", "one"), ("flock", "two")):
        got = resolve.resolve(f"publisher:{platform}", root=root, env={})
        assert (got["implementation"], got["source"]) == (name, "only-implementation")
    # The general variable is a preference: set for the first platform, it is passed over for the second.
    env = {"PUBLISHER_PROVIDER": "one"}
    assert resolve.resolve("publisher:flock", root=root, env=env)["implementation"] == "two"
    assert resolve.resolve("publisher:chirp", root=root, env=env)["source"] == "environment"
    # The variable of one platform, and the caller's configuration, are exact: a wrong name is an error.
    for kwargs in ({"env": {"PUBLISHER_FLOCK_PROVIDER": "one"}}, {"env": {}, "implementation": "one"}):
        with pytest.raises(resolve.Unresolved) as e:
            resolve.resolve("publisher:flock", root=root, **kwargs)
        assert "does not serve flock" in str(e.value) and "['two']" in str(e.value)


def test_two_implementations_of_one_platform_need_a_choice_and_the_placeholder_means_any(tmp_path):
    root = workbench(tmp_path, "publisher/one.py", "publisher/two.py", "publisher/old.py",
                     one=("chirp",), two=("chirp", "flock"))
    with pytest.raises(resolve.Unresolved) as e:
        resolve.resolve("publisher:chirp", root=root, env={})
    assert "PUBLISHER_CHIRP_PROVIDER" in str(e.value) and "['one', 'two']" in str(e.value)
    assert resolve.resolve("publisher:flock", root=root, env={})["implementation"] == "two"
    assert resolve.serving("publisher:<platform>", root=root) == ["old", "one", "two"]
    assert resolve.platform_of("publisher:chirp") == "chirp" and resolve.platform_of("publisher:<platform>") is None
    assert resolve.platform_of("integration:vcs") is None and resolve.platform_of("store") is None


def test_the_declaration_is_read_as_text_and_a_file_that_declares_nothing_serves_nothing(tmp_path):
    root = workbench(tmp_path, "publisher/one.py", "publisher/old.py", "publisher/odd.py", one=("chirp", "flock"))
    (root / "providers/publisher/odd.py").write_text("PLATFORMS = compute()\n    PLATFORMS = ('chirp',)\n")
    assert resolve.served_platforms("publisher:chirp", "one", root=root) == ["chirp", "flock"]  # never imported
    assert resolve.served_platforms("publisher:chirp", "old", root=root) == []
    assert resolve.served_platforms("publisher:chirp", "odd", root=root) == []
    assert resolve.served_platforms("publisher:chirp", "absent", root=root) == []
    (root / "providers/publisher/odd.py").write_text('PLATFORMS = ["chirp", "Not A Name", 3]  # served\n')
    assert resolve.served_platforms("publisher:chirp", "odd", root=root) == ["chirp"]


def test_scheduler_default_follows_the_platform(tmp_path):
    root = workbench(tmp_path, "scheduler/launchd.py", "scheduler/systemd.py")
    for platform, name in (("darwin", "launchd"), ("linux", "systemd")):
        got = resolve.resolve("scheduler:job", root=root, env={}, platform=platform)
        assert (got["implementation"], got["source"]) == (name, "platform-default")
    got = resolve.resolve("scheduler:job", root=root, env={"SCHEDULER_PROVIDER": "launchd"}, platform="linux")
    assert (got["implementation"], got["source"]) == ("launchd", "environment")
    with pytest.raises(resolve.Unresolved) as e:
        resolve.resolve("scheduler:job", root=root, env={}, platform="win32")
    assert "SCHEDULER_PROVIDER" in str(e.value) and "launchd" in str(e.value)


def test_the_only_implementation_resolves_and_none_or_several_do_not(tmp_path):
    root = workbench(tmp_path, "store/sqlite.py", "vcs/github.py", "vcs/gitlab.py", "scheduler/launchd.py")
    got = resolve.resolve("store:runtime", root=root, env={})
    assert (got["implementation"], got["source"]) == ("sqlite", "only-implementation")
    # A platform default that is not shipped is not chosen; the only implementation is.
    assert resolve.resolve("scheduler:job", root=root, env={}, platform="linux")["implementation"] == "launchd"
    with pytest.raises(resolve.Unresolved) as e:
        resolve.resolve("integration:vcs", root=root, env={})
    assert "INTEGRATION_VCS_PROVIDER" in str(e.value)
    with pytest.raises(resolve.Unresolved) as e:
        resolve.resolve("sender:email", root=root, env={})
    assert "MAILER_PROVIDER" in str(e.value) and "providers/mailer/" in str(e.value)


def test_a_name_is_never_a_path(tmp_path):
    root = workbench(tmp_path, "scheduler/launchd.py", "publisher/one.py", "publisher/auth.py", one=("chirp",))
    for bad in ("../../tmp/x", "/tmp/x", "auth", "LAUNCHD", "nope", "launchd.py", ""):
        with pytest.raises(resolve.Unresolved):
            resolve.resolve("scheduler:job", root=root, env={}, implementation=bad)
        if bad:
            with pytest.raises(resolve.Unresolved):
                resolve.resolve("publisher:chirp", root=root, env={"PUBLISHER_PROVIDER": bad})


def test_an_explicit_implementation_wins_over_the_environment(tmp_path):
    root = workbench(tmp_path, "scheduler/launchd.py", "scheduler/systemd.py")
    got = resolve.resolve("scheduler:job", root=root, env={"SCHEDULER_PROVIDER": "systemd"}, platform="linux",
                          implementation="launchd")
    assert (got["implementation"], got["source"]) == ("launchd", "configuration")


def test_workbench_root_comes_from_the_variable_then_from_the_script(tmp_path):
    root = workbench(tmp_path, "store/sqlite.py")
    assert resolve.workbench_root(env={}) == REPO
    assert resolve.workbench_root(env={"WORKBENCH_ROOT": str(root)}) == root.resolve()
    assert resolve.workbench_root(root=tmp_path, env={"WORKBENCH_ROOT": str(root)}) == tmp_path.resolve()
    with pytest.raises(resolve.Unresolved):
        resolve.workbench_root(env={"WORKBENCH_ROOT": "relative/path"})
    assert resolve.secret_resolver(env={}) == REPO / "providers" / "secrets" / "resolver.py"
    assert resolve.provider_path("store:runtime", env={"WORKBENCH_ROOT": str(root)}) == root.resolve() / "providers/store/sqlite.py"


def test_cli_prints_the_path_and_uses_the_documented_exit_codes(tmp_path):
    root = workbench(tmp_path, "store/sqlite.py", "scheduler/launchd.py", "scheduler/systemd.py")
    env = {"WORKBENCH_ROOT": str(root), "SCHEDULER_PROVIDER": "systemd"}
    r = cli(["--class", "scheduler:job"], env)
    assert r.returncode == 0 and r.stdout.strip() == str(root.resolve() / "providers" / "scheduler" / "systemd.py")
    r = cli(["--class", "store:runtime", "--json"], env)
    assert r.returncode == 0 and json.loads(r.stdout)["implementation"] == "sqlite"
    r = cli(["--class", "reader:email"], env)
    assert r.returncode == 3 and r.stdout == "" and "MAILBOX_PROVIDER" in r.stderr
    r = cli(["--class", "scheduler:job"], {**env, "SCHEDULER_PROVIDER": "cron"})
    assert r.returncode == 3 and "SCHEDULER_PROVIDER" in r.stderr and "cron" in r.stderr
    r = cli(["--class", "teleporter"], env)
    assert r.returncode == 2 and "unknown class" in r.stderr
    assert cli([], env).returncode == 2 and cli(["--class", "store:runtime", "--list"], env).returncode == 2
    assert cli(["--help"]).returncode == 0
    r = cli(["--class", "store:runtime", "--root", str(REPO)], env)  # --root beats the variable
    assert r.stdout.strip() == str(REPO / "providers" / "store" / "sqlite.py")


def test_cli_list_names_every_class_and_what_resolves(tmp_path):
    root = workbench(tmp_path, "store/sqlite.py", "vcs/github.py", "vcs/gitlab.py", "publisher/one.py",
                     "publisher/old.py", one=("chirp", "flock"))
    r = cli(["--list"], {"WORKBENCH_ROOT": str(root)})
    assert r.returncode == 0
    out = json.loads(r.stdout)
    assert out["root"] == str(root.resolve()) and out["root_variable"] == "WORKBENCH_ROOT"
    rows = {row["class"]: row for row in out["classes"]}
    assert set(rows) == set(resolve.LISTED)
    store = rows["store:runtime"]
    assert store["resolves"] == "sqlite" and store["source"] == "only-implementation"
    assert (store["folder"], store["variables"], store["old_name"]) == ("providers/store/", ["STORE_PROVIDER"], "store")
    assert rows["publisher:<platform>"]["platforms"] == {"old": [], "one": ["chirp", "flock"]}
    assert "platforms" not in store and "old_name" not in rows["integration:vcs"]
    assert rows["integration:vcs"]["implementations"] == ["github", "gitlab"]
    assert rows["integration:vcs"]["resolves"] is None and "INTEGRATION_VCS_PROVIDER" in rows["integration:vcs"]["note"]
    assert rows["sender:email"]["implementations"] == [] and rows["sender:email"]["folder"] == "providers/mailer/"


def test_this_checkout_resolves_what_it_ships():
    env = {}
    assert resolve.resolve("store:runtime", env=env)["implementation"] == "sqlite"
    assert resolve.resolve("reader:email", env=env)["implementation"] == "gmail"
    assert resolve.resolve("integration:vcs", env=env)["implementation"] == "github"
    assert resolve.resolve("scheduler:job", env=env, platform="darwin")["implementation"] == "launchd"
    assert resolve.resolve("scheduler:job", env=env, platform="linux")["implementation"] == "systemd"
    # Every publisher shipped declares at least one platform, and resolves for each platform it declares
    # unless another publisher declares it too.
    publishers = resolve.implementations("publisher:<platform>", env=env)
    assert publishers
    for name in publishers:
        platforms = resolve.served_platforms("publisher:<platform>", name, env=env)
        assert platforms, f"providers/publisher/{name}.py declares no PLATFORMS"
        for platform in platforms:
            if resolve.serving(f"publisher:{platform}", env=env) == [name]:
                assert resolve.resolve(f"publisher:{platform}", env=env)["implementation"] == name
    for cls in resolve.LISTED:  # every listed class is a class
        resolve.variables(cls)


def test_every_class_of_the_environment_contract_is_listed():
    text = (REPO / "contracts" / "environment.md").read_text(encoding="utf-8")
    table = text.split("## Classes", 1)[1].split("\n## ", 1)[0]
    classes = [line.split("|")[1].strip().strip("`") for line in table.splitlines()
               if line.startswith("| `")]
    assert classes and sorted(classes) == sorted(resolve.LISTED)


def test_a_verbs_row_says_when_no_implementation_ships():
    # CT6: the verbs table listed verbs for classes that no provider implements, as if one answered them.
    contract = (REPO / "providers" / "CONTRACT.md").read_text(encoding="utf-8")
    table = contract.split("## Verbs per class", 1)[1].split("\n### ", 1)[0]
    rows = [line for line in table.splitlines() if line.startswith("| `")]
    assert rows
    for row in rows:
        cls = row.split("|")[1].strip().strip("`")
        shipped = bool(resolve.implementations_in(resolve.folder(cls), root=REPO))
        reserved = row.split("|")[2].strip().startswith("No implementation ships.")
        assert shipped != reserved, cls
    assert 'A row that starts "No implementation ships" is a reserved shape' in contract


# --- calling a provider from code (resolve.call, resolve.invoke) ---------------------------------------------------

STAND_IN = '''#!/usr/bin/env python3
# /// script
# dependencies = []
# ///
import json, os, stat, sys
args = sys.argv[1:]
code = int(os.environ.get("STAND_IN_EXIT", "0"))
if code:
    print("a line\\nthe reason it ended", file=sys.stderr)
    sys.exit(code)
if os.environ.get("STAND_IN_RAW"):
    print(os.environ["STAND_IN_RAW"])
    sys.exit(0)
config = None
if "--config-file" in args:
    path = args[args.index("--config-file") + 1]
    config = {"path": path, "mode": stat.S_IMODE(os.stat(path).st_mode), "text": open(path).read()}
print(json.dumps({"args": args, "config": config, "env": sorted(os.environ)}))
'''


def stand_in_workbench(tmp_path, header=None):
    root = workbench(tmp_path, "vcs/standin.py")
    text = STAND_IN if header is None else STAND_IN.replace("# dependencies = []", header)
    (root / "providers" / "vcs" / "standin.py").write_text(text)
    return root


def test_the_interpreter_follows_the_header(tmp_path):
    bare = tmp_path / "bare.py"
    bare.write_text("#!/usr/bin/env python3\n# /// script\n# dependencies = []\n# ///\n")
    pinned = tmp_path / "pinned.py"
    pinned.write_text('# /// script\n# dependencies = ["keyring==25.7.0"]\n# ///\n')
    assert resolve.interpreter_for(bare) == [sys.executable]
    assert resolve.interpreter_for(pinned) == ["uv", "run"]
    with pytest.raises(resolve.ProviderCallError) as caught:
        resolve.interpreter_for(tmp_path / "missing.py")
    assert caught.value.kind == "not-configured"


def test_a_script_with_a_lockfile_next_to_it_starts_with_uv_run_locked(tmp_path):
    pinned = tmp_path / "pinned.py"
    pinned.write_text('# /// script\n# dependencies = ["websockets==16.1.1"]\n# ///\n')
    assert resolve.interpreter_for(pinned) == ["uv", "run"]
    (tmp_path / "pinned.py.lock").write_text("version = 1\n")
    assert resolve.interpreter_for(pinned) == ["uv", "run", "--locked"]
    bare = tmp_path / "bare.py"
    bare.write_text("# /// script\n# dependencies = []\n# ///\n")
    (tmp_path / "bare.py.lock").write_text("version = 1\n")
    assert resolve.interpreter_for(bare) == [sys.executable]       # nothing to install, so nothing to lock


def test_the_discord_provider_is_started_with_its_hash_lock():
    script = REPO / "providers" / "messenger" / "discord.py"
    assert (REPO / "providers" / "messenger" / "discord.py.lock").is_file()
    assert resolve.interpreter_for(script) == ["uv", "run", "--locked"]


def test_a_call_returns_the_one_json_object_and_passes_the_arguments(tmp_path):
    root = stand_in_workbench(tmp_path)
    out = resolve.call("integration:vcs", "read-file", ["--repo", "a/b"], root=root, env={"PATH": "/usr/bin:/bin"})
    assert out["args"] == ["read-file", "--repo", "a/b"] and out["config"] is None
    bare = resolve.call("integration:vcs", None, ["commit-files", "--dry-run"], root=root, env={})
    assert bare["args"] == ["commit-files", "--dry-run"]  # no verb: the first argument is the verb


def test_the_configuration_goes_in_a_private_file_removed_afterwards(tmp_path):
    root = stand_in_workbench(tmp_path)
    out = resolve.call("integration:vcs", "list", ["--x"], root=root, config={"provider": "standin"}, env={})
    assert out["args"][:2] == ["list", "--config-file"] and out["args"][-1] == "--x"
    assert out["config"]["mode"] == 0o600 and json.loads(out["config"]["text"]) == {"provider": "standin"}
    assert not Path(out["config"]["path"]).exists()


def test_exit_codes_are_mapped_and_the_tail_is_kept(tmp_path):
    root = stand_in_workbench(tmp_path)
    for code, kind in ((2, "usage"), (3, "not-configured"), (1, "failed"), (7, "failed")):
        with pytest.raises(resolve.ProviderCallError) as caught:
            resolve.call("integration:vcs", "v", [], root=root, env={"STAND_IN_EXIT": str(code)})
        assert (caught.value.kind, caught.value.exit_code) == (kind, code)
        assert caught.value.stderr_tail.endswith("the reason it ended") and len(caught.value.stderr_tail) <= 300


@pytest.mark.parametrize("raw", ["not json", "[1, 2]", ""])
def test_anything_but_one_json_object_is_refused(tmp_path, raw):
    root = stand_in_workbench(tmp_path)
    with pytest.raises(resolve.ProviderCallError) as caught:
        resolve.call("integration:vcs", "v", [], root=root, env={"STAND_IN_RAW": raw or " "})
    assert caught.value.kind == "failed"


def test_a_given_environment_is_the_whole_environment_of_the_child(tmp_path, monkeypatch):
    root = stand_in_workbench(tmp_path)
    monkeypatch.setenv("CALLER_ONLY_VARIABLE", "x")
    shown = resolve.call("integration:vcs", "v", [], root=root, env={"ONLY_THIS": "1"})["env"]
    assert "ONLY_THIS" in shown and "CALLER_ONLY_VARIABLE" not in shown
    inherited = resolve.call("integration:vcs", "v", [], root=root)["env"]
    assert "CALLER_ONLY_VARIABLE" in inherited  # without env, the caller's environment is inherited


def test_a_class_that_does_not_resolve_is_a_not_configured_error(tmp_path):
    root = workbench(tmp_path)
    with pytest.raises(resolve.ProviderCallError) as caught:
        resolve.call("integration:vcs", "v", [], root=root, env={})
    assert caught.value.kind == "not-configured" and caught.value.exit_code is None
    with pytest.raises(resolve.ProviderCallError):
        resolve.call("integration:vcs", "v", [], root=root, implementation="other", env={})


def test_a_pinned_header_starts_with_uv_and_a_stand_in_run_replaces_the_start(tmp_path):
    root = stand_in_workbench(tmp_path, header='# dependencies = ["keyring==25.7.0"]')
    seen = []

    def run(argv):
        seen.append(argv)
        return subprocess.CompletedProcess(argv, 0, '{"ok": true}', "")

    assert resolve.call("integration:vcs", "v", ["--a"], root=root, env={}, run=run) == {"ok": True}
    assert seen[0][:2] == ["uv", "run"] and seen[0][2].endswith("standin.py") and seen[0][3:] == ["v", "--a"]


def test_a_start_over_the_timeout_is_a_timeout_error(tmp_path):
    root = stand_in_workbench(tmp_path)
    (root / "providers" / "vcs" / "standin.py").write_text("# dependencies = []\nimport time\ntime.sleep(5)\n")
    with pytest.raises(resolve.ProviderCallError) as caught:
        resolve.call("integration:vcs", "v", [], root=root, timeout=1, env={})
    assert caught.value.kind == "timeout"


def test_the_command_line_still_resolves_a_class(tmp_path):
    root = stand_in_workbench(tmp_path)
    done = cli(["--class", "integration:vcs", "--root", str(root)])
    assert done.returncode == 0 and done.stdout.strip().endswith("standin.py")


def test_messenger_is_a_class_with_a_platform_parameter_and_telegram_serves_telegram():
    assert resolve.variables("messenger:telegram") == ["MESSENGER_TELEGRAM_PROVIDER", "MESSENGER_PROVIDER"]
    assert resolve.folder("messenger:telegram") == "messenger" and resolve.platform_of("messenger:telegram") == "telegram"
    assert resolve.served_platforms("messenger:<platform>", "telegram", env={}) == ["telegram"]
    got = resolve.resolve("messenger:telegram", env={})
    assert got["implementation"] == "telegram" and got["path"] == str(REPO / "providers" / "messenger" / "telegram.py")
    with pytest.raises(resolve.Unresolved):
        resolve.resolve("messenger:whatsapp", env={})


# --- starting a long-lived verb (resolve.start) ----------------------------------------------------------------

LONG_LIVED = '''# /// script
# dependencies = []
# ///
import json, os, sys
sys.stdout.buffer.write((json.dumps({"args": sys.argv[1:], "pgid": os.getpgid(0), "sid": os.getsid(0)}) + "\\n").encode())
sys.stdout.buffer.flush()
sys.stderr.write("diagnostic\\n")
sys.stderr.flush()
sys.stdin.buffer.read()
'''


def test_start_runs_the_verb_in_its_own_session_with_three_binary_pipes_and_the_given_arguments(tmp_path):
    import os
    root = stand_in_workbench(tmp_path)
    (root / "providers" / "vcs" / "standin.py").write_text(LONG_LIVED)
    proc = resolve.start("integration:vcs", "listen", ["--platform", "chirp"], root=root, env={"PATH": "/usr/bin:/bin"})
    try:
        said = json.loads(proc.stdout.readline())
        assert said["args"] == ["listen", "--platform", "chirp"]
        assert said["sid"] == proc.pid == said["pgid"] != os.getpgid(0)   # a session of its own: the group is the child's
        assert isinstance(said, dict) and proc.stdin.write(b"") == 0   # binary pipes
    finally:
        proc.stdin.close()
        assert proc.wait(10) == 0
        assert proc.stderr.read() == b"diagnostic\n"   # stderr is a pipe the caller reads, not inherited
        proc.stdout.close()
        proc.stderr.close()


def test_start_picks_the_interpreter_as_call_does_and_passes_the_pipes_and_the_session(tmp_path, monkeypatch):
    seen = []

    class Fake:
        pid = 1

    def popen(argv, **kw):
        seen.append((argv, kw))
        return Fake()

    monkeypatch.setattr(resolve.subprocess, "Popen", popen)
    bare = stand_in_workbench(tmp_path / "a")
    resolve.start("integration:vcs", "listen", ["--x", 3], root=bare, env={"K": "v"})
    pinned = stand_in_workbench(tmp_path / "b", header='# dependencies = ["keyring==25.7.0"]')
    resolve.start("integration:vcs", "listen", [], root=pinned, env={})
    (argv, kw), (argv2, _) = seen
    assert argv[0] == sys.executable and argv[1].endswith("standin.py") and argv[2:] == ["listen", "--x", "3"]
    assert argv2[:2] == ["uv", "run"] and argv2[2].endswith("standin.py") and argv2[3:] == ["listen"]
    assert argv[0] == resolve.interpreter_for(argv[1])[0]
    assert kw["stdin"] == kw["stdout"] == kw["stderr"] == subprocess.PIPE
    assert kw["text"] is False and kw["start_new_session"] is True and kw["close_fds"] is True and kw["env"] == {"K": "v"}


def test_start_names_a_class_that_does_not_resolve_and_a_program_that_cannot_start(tmp_path, monkeypatch):
    root = stand_in_workbench(tmp_path)
    with pytest.raises(resolve.ProviderCallError) as caught:
        resolve.start("integration:vcs", "listen", [], root=root, implementation="other", env={})
    assert caught.value.kind == "not-configured"

    def refuse(argv, **kw):
        raise PermissionError(13, "denied")

    monkeypatch.setattr(resolve.subprocess, "Popen", refuse)
    with pytest.raises(resolve.ProviderCallError) as caught:
        resolve.start("integration:vcs", "listen", [], root=root, env={})
    assert caught.value.kind == "failed" and "PermissionError" in caught.value.reason
