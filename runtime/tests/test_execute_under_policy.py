"""Tests of limit L15 for policy effects (WP-R.1 of the architecture-fix plan): an effect inside a standing approval is
executed only by the operations layer, ops.execute_under_policy, and only inside the approval's bounds. A handler
prepares the effect document and hands it over; the operation checks the approval (autonomy.covers, the policy file's
hash now, today's count under the run lock), makes the provider's dry run and its confirmed call, and records the
action. Offline: the stand-in tree and its stand-in code provider of runtime/tests/standin_tree.py; no network, no
push. Every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_execute_under_policy.py
"""
from __future__ import annotations

import datetime
import hashlib
import json
import shutil
import subprocess

import pytest

import standin_tree as st

autonomy = st.load("autonomy")
effects = st.load("effects")
lab = st.load("lab")
ops = st.load("ops")
ops_core = st.load("ops_core")
cli = st.load("cli")

POLICY = "docs/workbench/policies/published-posts.json"
TARGET = "example-owner/example-profile@main"
BOUNDS = {"policy": "published-posts", "agent": "marketing", "effects": ["push"], "targets": [TARGET],
          "files": ["data/posts.json", "assets/posts/*"], "max_per_day": 1, "max_items_per_run": 10}
CODE = {"provider": "github", "repo": "example-owner/example-profile", "base": "main"}


def ahead(days: int) -> str:
    return (datetime.date.today() + datetime.timedelta(days=days)).isoformat()


@pytest.fixture
def tree(tmp_path, monkeypatch):
    built = st.build(tmp_path, monkeypatch, lab)
    monkeypatch.setattr(ops_core, "ROOT", str(built["tree"]))
    (built["tree"] / "scripts").mkdir(exist_ok=True)  # the one source of the vocabulary of side effects
    shutil.copyfile(st.REPO / "scripts" / "validate.py", built["tree"] / "scripts" / "validate.py")
    project = built["project"]
    config = project / "docs" / "workbench" / "runtime.json"
    data = json.loads(config.read_text())
    data["area_agents"] = {"planning": {"pack": "planning"},
                           "marketing": {"pack": "brand", "mode": "autonomous-with-policy"}}
    data["code"] = CODE
    config.write_text(json.dumps(data))
    (project / "docs" / "workbench" / "policies").mkdir()
    write_bounds(built, BOUNDS)
    ops.accept_config(str(project), ops.project_config.load(str(project))["sha256"])
    return built


def write_bounds(tree, bounds: dict) -> None:
    (tree["project"] / POLICY).write_text(json.dumps(bounds, indent=2) + "\n")


def project_of(tree) -> str:
    return str(tree["project"])


def approve(tree, days: int = 30) -> dict:
    digest = hashlib.sha256((tree["project"] / POLICY).read_bytes()).hexdigest()
    return ops.approve_policy(project_of(tree), POLICY, "marketing", digest, ahead(days))


def calls(tree) -> list:
    path = tree["tree"] / "providers" / "vcs" / "calls.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.is_file() else []


def effect_file(tree, name="effect.json", **changes) -> str:
    """An effect document as the handler writes it, with its files beside it."""
    folder = tree["project"].parent / "handed"
    folder.mkdir(exist_ok=True)
    (folder / "target.json").write_text("[]\n")
    (folder / "message.txt").write_text("Add a post\n")
    doc = {"policy": "published-posts", "kind": "push", "target": TARGET, "files": ["data/posts.json"], "items": 1,
           "idempotency_key": "published-posts-2026-W42", "payload_sha256": "ab" * 32,
           "args": ["--repo", "example-owner/example-profile", "--branch", "main",
                    "--message-file", str(folder / "message.txt"), "--file", f"data/posts.json={folder / 'target.json'}"]}
    doc.update(changes)
    doc = {k: v for k, v in doc.items() if v is not None}
    path = folder / name
    path.write_text(json.dumps(doc))
    return str(path)


def execute(tree, **changes) -> dict:
    return ops.execute_under_policy(project_of(tree), "published-posts", effect_file(tree, **changes))


def executed_today(tree) -> int:
    return ops.standing(project_of(tree), "published-posts")["executed_today"]


def test_a_policy_effect_is_executed_by_the_operations_layer_inside_its_bounds_only(tree):
    approved = approve(tree)
    out = execute(tree)
    assert out["executed"] is True and out["policy"] == "published-posts" and out["approval_id"] == approved["id"]
    assert out["action"]["created"] is True and out["result"]["commit"] == "c" * 40
    made = calls(tree)
    assert [c["argv"][0] for c in made] == ["commit-files", "commit-files"]
    dry, real = made[0]["argv"], made[1]["argv"]
    assert "--dry-run" in dry and "--confirmed" not in dry and "--confirmed" in real and "--dry-run" not in real
    assert dry[:-1] == real[:-1] and (dry[-1], real[-1]) == ("--dry-run", "--confirmed")  # the same call, then confirmed
    assert [real[i + 1] for i, a in enumerate(real) if a == "--allow"] == BOUNDS["files"]  # exactly the bounds' globs
    assert real[real.index("--idempotency-key") + 1] == "published-posts-2026-W42"
    assert real[real.index("--repo") + 1] == "example-owner/example-profile"
    assert executed_today(tree) == 1  # the action row exists and counts against the day


@pytest.mark.parametrize("bounds, changes, words", [
    ({"effects": ["publish"]}, {}, "effects"),
    ({"targets": ["example-owner/another@main"]}, {}, "targets"),
    ({}, {"files": ["data/posts.json", "secrets/key.json"]}, "files"),
    ({"max_items_per_run": 1}, {"items": 2}, "per run"),
    ({"max_per_day": 1}, {}, "per day"),
])
def test_a_change_outside_one_of_the_five_bounds_runs_nothing_and_names_the_bound(tree, bounds, changes, words):
    write_bounds(tree, {**BOUNDS, **bounds})
    approve(tree)
    if words == "per day":
        assert execute(tree)["executed"] is True
        before = calls(tree)
        changes = {"idempotency_key": "published-posts-2026-W43"}
    else:
        before = []
    out = execute(tree, **changes)
    assert out["executed"] is False and words in out["why"], out
    assert calls(tree) == before
    assert executed_today(tree) == (1 if words == "per day" else 0)


def test_no_active_approval_covers_nothing(tree):
    out = execute(tree)
    assert out["executed"] is False and "no active standing approval" in out["why"] and calls(tree) == []


def test_an_expired_approval_covers_nothing(tree):
    approved = approve(tree)
    store = ops_core.store_module()
    later = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=31)).isoformat()
    assert store.approvals_expire(store.open_db(str(tree["db"])), later) == 1
    out = execute(tree)
    assert approved["status"] == "active" and out["executed"] is False and calls(tree) == []


def test_a_changed_policy_file_covers_nothing(tree):
    approve(tree)
    write_bounds(tree, {**BOUNDS, "max_per_day": 5})
    out = execute(tree)
    assert out["executed"] is False and "changed" in out["why"] and calls(tree) == []


def test_an_agent_outside_the_policy_mode_covers_nothing(tree):
    approve(tree)
    changed = ops.set_mode(project_of(tree), "marketing", "autonomous")
    ops.accept_config(project_of(tree), changed["config_sha256"])
    out = execute(tree)
    assert out["executed"] is False and "autonomous" in out["why"] and calls(tree) == []


@pytest.mark.parametrize("flag", ["--confirmed", "--dry-run", "--allow", "--idempotency-key"])
def test_args_holding_a_reserved_flag_are_refused_and_nothing_runs(tree, flag):
    approve(tree)
    doc = json.loads(open(effect_file(tree)).read())
    with pytest.raises(ops.OpsError) as refused:
        execute(tree, args=doc["args"] + [flag, "x"])
    assert refused.value.code == 2 and flag in str(refused.value)
    assert calls(tree) == [] and executed_today(tree) == 0


@pytest.mark.parametrize("changes", [
    {"idempotency_key": None},           # a missing key
    {"colour": "red"},                   # an extra key
    {"kind": "publish"},                 # a kind of effect (a reply) whose document this one is not
    {"kind": "schedule"},                # a word of the vocabulary with no kind of effect
    {"kind": "teleport"},                # not a word of the vocabulary
    {"policy": "another-policy"},        # not the policy the call is for
    {"items": "1"},                      # a wrong type
    {"payload_sha256": "not-a-hash"},    # a hash the store would refuse after the provider ran
])
def test_a_malformed_effect_document_is_refused_and_nothing_runs(tree, changes):
    approve(tree)
    with pytest.raises(ops.OpsError) as refused:
        execute(tree, **changes)
    assert refused.value.code == 2 and calls(tree) == [] and executed_today(tree) == 0


def test_the_dry_run_failing_confirms_nothing_and_records_nothing(tree, monkeypatch):
    approve(tree)
    real = effects._subprocess
    monkeypatch.setattr(effects, "_subprocess", lambda argv: subprocess.CompletedProcess(argv, 1, "", "the branch is protected")
                        if "--dry-run" in argv else real(argv))
    with pytest.raises(ops.OpsError) as refused:
        execute(tree)
    assert refused.value.code == 1 and "nothing was executed" in str(refused.value) and "protected" in str(refused.value)
    assert calls(tree) == [] and executed_today(tree) == 0


def test_the_confirmed_call_failing_records_nothing_and_the_error_names_the_replay(tree, monkeypatch):
    approve(tree)
    real = effects._subprocess
    monkeypatch.setattr(effects, "_subprocess", lambda argv: subprocess.CompletedProcess(argv, 1, "", "the remote refused")
                        if "--confirmed" in argv else real(argv))
    with pytest.raises(ops.OpsError) as refused:
        execute(tree)
    assert refused.value.code == 1 and "after the dry run" in str(refused.value) and "replay" in str(refused.value)
    assert [c["argv"][0] for c in calls(tree)] == ["commit-files"] and executed_today(tree) == 0


def test_the_shell_answers_with_one_json_object_and_exit_0_whether_or_not_the_approval_covers(tree, capsys):
    approve(tree)
    path = effect_file(tree)
    argv = ["execute-under-policy", "--project", project_of(tree), "--policy", "published-posts", "--effect-file", path]
    assert cli.main(argv) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["executed"] is True and first["action"]["created"] is True
    write_bounds(tree, {**BOUNDS, "max_per_day": 1})  # the file as approved: the day's cap of 1 is now reached
    assert cli.main(argv) == 0
    second = json.loads(capsys.readouterr().out)
    assert second["executed"] is False and "per day" in second["why"]
    assert cli.main(argv[:-2]) != 0  # the flag is needed


# --- the generic operation (CONS-3): the kind module answers what the operation needs ------------------------------


def published_posts_document(folder, **changes) -> dict:
    """The effect document as runtime/handlers/published_posts.py writes it for a week with two posts and one image,
    with its files beside it: effect `push`, target <repo>@<branch>, the paths, the number of posts, the key of the
    week, the hash of the new target text, and the flags of commit-files."""
    folder.mkdir(exist_ok=True)
    (folder / "target.json").write_text("[]\n")
    (folder / "message.txt").write_text("Add the posts published in the week before 2026-W42\n")
    (folder / "image.png").write_bytes(b"png")
    doc = {"policy": "published-posts", "kind": "push", "target": TARGET,
           "files": ["data/posts.json", "assets/posts/example-one.png"], "items": 2,
           "idempotency_key": "published-posts-2026-W42", "payload_sha256": hashlib.sha256(b"[]\n").hexdigest(),
           "args": ["--repo", "example-owner/example-profile", "--branch", "main", "--message-file",
                    str(folder / "message.txt"), "--file", f"data/posts.json={folder / 'target.json'}",
                    "--file", f"assets/posts/example-one.png={folder / 'image.png'}"]}
    doc.update(changes)
    (folder / "effect.json").write_text(json.dumps(doc))
    return doc


def test_the_document_of_the_published_posts_handler_runs_through_the_generic_operation_with_the_same_argv(tree):
    approve(tree)
    folder = tree["project"].parent / "handed-posts"
    doc = published_posts_document(folder)
    out = ops.execute_under_policy(project_of(tree), "published-posts", str(folder / "effect.json"))
    assert out["executed"] is True and out["action"]["created"] is True
    base = ["commit-files", *doc["args"], "--allow", "data/posts.json", "--allow", "assets/posts/*",
            "--idempotency-key", "published-posts-2026-W42"]
    assert [c["argv"] for c in calls(tree)] == [base + ["--dry-run"], base + ["--confirmed"]]
    assert executed_today(tree) == 1


def test_a_kind_of_the_gate_path_cannot_run_under_a_policy_and_the_refusal_names_the_kinds_that_can(tree):
    write_bounds(tree, {**BOUNDS, "effects": ["push", "create"]})
    approve(tree)
    with pytest.raises(ops.OpsError) as refused:
        execute(tree, kind="create")
    assert refused.value.code == 2
    assert str(refused.value) == "the effect kind 'create' cannot run under a policy (it can: publish, push)"
    assert calls(tree) == [] and executed_today(tree) == 0


def test_a_word_outside_the_vocabulary_is_refused_with_the_vocabulary_named(tree):
    approve(tree)
    with pytest.raises(ops.OpsError) as refused:
        execute(tree, kind="teleport")
    assert refused.value.code == 2 and "kind of the effect file is one of publish, send, schedule" in str(refused.value)
    assert calls(tree) == []


def standin_kind(monkeypatch, word: str, **names):
    """A kind module registered under a word of the vocabulary, as a later package adds one: a module and a row."""
    import sys
    import types
    kind = types.ModuleType("standin_policy_kind")
    kind.POLICY, kind.PROVIDER_CLASS = True, "integration:vcs"
    kind.policy_platform = lambda doc: None
    kind.policy_effect = lambda doc: {key: doc[key] for key in ("kind", "target", "files", "items")}
    kind.policy_argv = lambda doc: ["commit-files", *doc["args"]]
    kind.describe = lambda doc: "a stand-in"
    for name, value in names.items():
        setattr(kind, name, value)
    monkeypatch.setitem(sys.modules, "standin_policy_kind", kind)
    monkeypatch.setitem(effects.KINDS, word, "standin_policy_kind")
    return kind


def test_the_operation_asks_the_kind_module_for_the_effect_and_the_argv_it_checks_and_runs(tree, monkeypatch):
    write_bounds(tree, {**BOUNDS, "effects": ["send"]})
    approve(tree)
    standin_kind(monkeypatch, "send",
                 policy_effect=lambda doc: {"kind": "send", "target": TARGET, "files": ["data/posts.json"], "items": 1},
                 policy_argv=lambda doc: ["commit-files", "--repo", "example-owner/example-profile", "--branch", "main"])
    out = execute(tree, kind="send", target="an-alias-the-module-resolves")  # the bounds name the resolved target
    assert out["executed"] is True
    real = calls(tree)[1]["argv"]
    assert real[:5] == ["commit-files", "--repo", "example-owner/example-profile", "--branch", "main"]
    assert real[5:] == ["--allow", "data/posts.json", "--allow", "assets/posts/*", "--idempotency-key",
                        "published-posts-2026-W42", "--confirmed"]  # the document's own args were not used
    import sqlite3
    with sqlite3.connect(str(tree["db"])) as db:  # the action records the target the module resolved, not the document's
        assert db.execute("SELECT target FROM actions").fetchall() == [(TARGET,)]


def test_a_kind_whose_module_says_it_may_not_run_under_a_policy_is_refused_before_anything_is_checked(tree, monkeypatch):
    write_bounds(tree, {**BOUNDS, "effects": ["send"]})
    approve(tree)
    standin_kind(monkeypatch, "send", POLICY=False)
    with pytest.raises(ops.OpsError) as refused:
        execute(tree, kind="send")
    assert refused.value.code == 2 and "the effect kind 'send' cannot run under a policy" in str(refused.value)
    assert calls(tree) == []


def publisher_tree(tree, platforms=("standin",)) -> None:
    """A stand-in publisher provider that records its arguments, in the tree's providers/publisher/."""
    folder = tree["tree"] / "providers" / "publisher"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "standin.py").write_text(
        "# /// script\n# requires-python = \">=3.9\"\n# dependencies = []\n# ///\n"
        f"PLATFORMS = {tuple(platforms)!r}\n"
        "import json, os, sys\n"
        "with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'calls.jsonl'), 'a') as f:\n"
        "    f.write(json.dumps(sys.argv[1:]) + '\\n')\n"
        "print(json.dumps({'posted': '--confirmed' in sys.argv}))\n", encoding="utf-8")


def test_a_kind_on_a_publisher_is_resolved_with_the_platform_its_module_names(tree, monkeypatch):
    publisher_tree(tree)
    write_bounds(tree, {**BOUNDS, "effects": ["send"]})
    approve(tree)
    standin_kind(monkeypatch, "send", PROVIDER_CLASS="publisher:<platform>", policy_platform=lambda doc: "standin",
                 policy_argv=lambda doc: ["post", "--platform", "standin", *doc["args"]])
    out = execute(tree, kind="send")
    assert out["executed"] is True and out["result"] == {"posted": True}
    made = [json.loads(line) for line in (tree["tree"] / "providers" / "publisher" / "calls.jsonl").read_text().splitlines()]
    assert [m[0] for m in made] == ["post", "post"] and made[0][-1] == "--dry-run" and made[1][-1] == "--confirmed"
    assert calls(tree) == []  # not the code provider


def test_the_provider_path_takes_the_platform_in_the_class_and_refuses_a_class_and_a_platform_that_do_not_fit(tree):
    publisher_tree(tree)
    cfg = ops_core.context(project_of(tree))["cfg"]
    found = ops._provider_path(cfg, "publisher:<platform>", platform="standin")
    assert found == str(tree["tree"] / "providers" / "publisher" / "standin.py")
    for cls, platform in (("publisher:<platform>", "elsewhere"),   # no provider serves it
                          ("publisher:<platform>", "<x>"),         # would read back as the placeholder: any provider
                          ("publisher:<platform>", "a:b"),         # not one name
                          ("publisher:<platform>", ""),            # not a name
                          ("publisher:<platform>", 7),             # not a text
                          ("publisher:<platform>", None),          # the class names a platform and none was given
                          ("integration:vcs", "standin")):         # a platform for a class that takes none
        with pytest.raises(ops.OpsError) as refused:
            ops._provider_path(cfg, cls, platform=platform)
        assert refused.value.code == 3, (cls, platform)
    assert ops._provider_path(cfg, "integration:vcs").endswith("providers/vcs/github.py")  # the code.provider rule stays


def test_a_kind_module_whose_argv_holds_a_flag_only_the_operation_adds_runs_nothing(tree, monkeypatch):
    write_bounds(tree, {**BOUNDS, "effects": ["send"]})
    approve(tree)
    standin_kind(monkeypatch, "send", policy_argv=lambda doc: ["commit-files", "--allow", "**"])
    with pytest.raises(ops.OpsError) as refused:
        execute(tree, kind="send")
    assert refused.value.code == 1 and "--allow" in str(refused.value)
    assert calls(tree) == [] and executed_today(tree) == 0
