"""The scheduled tick runs runtime/handlers/social.py with /usr/bin/python3 (Python 3.9 on macOS), and the runtime starts
the scripts below with that same interpreter (providers/CONTRACT.md, "Python version"). Three guards:

1. Syntax: each file parses as Python 3.9, and a `X | None` annotation, which 3.9 evaluates at definition time and
   refuses, is either absent or deferred with `from __future__ import annotations`.
2. Header: a script with an inline-metadata header declares a `requires-python` that admits 3.9, so the header
   never claims a newer interpreter than the one the scheduler starts it with.
3. Execution: each file is imported by the interpreter running this test, on Python 3.9 only (.github/workflows/checks.yml and
   nightly.yml, the python39 jobs), where the import is the real check; on a newer interpreter it is skipped, since each
   module's own tests import it there.

Providers that reach the network run through `uv run` under their own `requires-python` and are not listed.
Every module of runtime/ and runtime/handlers/ runs on the scheduler's interpreter unless EXCLUDED names it with a reason: the list of those is derived from the folders (HOT-1), so a new
module is covered without anyone listing it. A new script outside them that the runtime or a scheduler starts with the system interpreter is added to OTHERS."""
import ast
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
EXCLUDED = {}      # {repository-relative path: the reason}: a runtime module that must NOT run on the scheduler's interpreter. Empty: every runtime module runs on it.
RUNTIME_FILES = sorted(p for p in ["runtime/" + x.name for x in (REPO / "runtime").glob("*.py")] + ["runtime/handlers/" + x.name for x in (REPO / "runtime" / "handlers").glob("*.py")]
                       if p not in EXCLUDED)      # HOT-1: derived, so a new module is covered without anyone listing it
OTHERS = [      # the entries outside runtime/ and runtime/handlers/, literal
    "scripts/redact.py",
    "providers/resolve.py", "providers/store/sqlite.py",
    "providers/scheduler/launchd.py", "providers/scheduler/systemd.py",
    "skills/mkt-engage/scripts/policy_gate.py", "skills/mkt-engage/scripts/parse_notification.py",
    "skills/mkt-vote-round/scripts/vote_state.py", "skills/mkt-vote-round/scripts/vote_update.py",
    "skills/mkt-social-copy/scripts/check_post.py", "skills/mkt-publish/scripts/payload.py",
    "skills/brand-identity/scripts/render.py", "skills/brand-identity/scripts/contrast.py",
    "skills/brand-voice/scripts/voice_stats.py", "skills/brand-profile/scripts/sensitive_topics.py",
    # The sources of the four above that are generated copies (shared/scripts/copies.json): a copy is adopted
    # from its source, so the source runs on the system interpreter too.
    "shared/scripts/check_post.py", "shared/scripts/contrast.py", "shared/scripts/voice_stats.py",
    "shared/scripts/sensitive_topics.py", "shared/scripts/redact.py",
    # The field recorder: the runtime calls `record --start` before it starts an agent (the reliability model,
    # section 7), and it loads the status script for the form of a field line and the content hash.
    "scripts/evidence.py", "evals/eval_status.py", "evals/evidence_lines.py", "evals/interpreter_status.py",
    # The document converter's provider runs a container; the host side is plain Python and runs on the scheduler's interpreter too.
    "providers/converter/container.py",
    # The mailers' shared module (W2): plain Python.
    "providers/_mailer_account.py",
    # S16: the password-manager backends, loaded by path by the resolver, which the runtime loads under the system interpreter too.
    "providers/secrets/password_managers.py",
    # E-mail sent from the project's outbox (EMAIL-SEND): the provider with its shared code.
    "providers/_email.py", "providers/mailer/smtp.py",
    # The project script (P9): the provider's host side (it loads the two programs that run inside its image, which parse here too).
    "providers/script/container.py", "providers/script/egress_proxy.py", "providers/script/_inner.py",
    # The resolver of a pack: runtime/plan.py starts it with its own interpreter (stage 3; listed in stage 6, WP-6.7).
    "scripts/select_skills.py",
    # The product backlog's parser: the task runtime runs it as an isolated subprocess to propose sub-tasks (stage 6,
    # WP-6.5; runtime/isolated.py).
    "skills/eng-implement/scripts/task.py",
    # The task board's local implementation: the task runtime calls it with its own interpreter (stage 3).
    "providers/issue-tracker/local.py",
    # The WhatsApp provider: standard library only, so the resolver starts it with the caller's interpreter (MSG-7).
    "providers/messenger/whatsapp.py",
    # The official WhatsApp API provider: standard library only, so the resolver starts it with the caller's interpreter (MSG-8).
    "providers/messenger/whatsapp-cloud.py",
    # The same API through Twilio, and the module the two official WhatsApp providers share (MSG-9).
    "providers/messenger/whatsapp-twilio.py", "providers/messenger/whatsapp_meta.py",
    # The documents' local implementation, called the same way (stage 3).
    "providers/documents/local.py",
    # The interpreter's model calls (IX-2b): the provider of the class model:text (standard library only).
    "providers/model/chat-http.py",
]
ON_SYSTEM_PYTHON = RUNTIME_FILES + OTHERS
RUNTIME = ("runtime/handlers/social.py", "runtime/handlers/social_vote_job.py")  # the scheduler starts these
SYSTEM_PYTHON = (3, 9)
REQUIRES = re.compile(r'^# requires-python = "([^"]+)"$', re.M)
IMPORT = ("import importlib.util, sys; sys.path.insert(0, sys.argv[2]); "
          "spec = importlib.util.spec_from_file_location('on_system_python', sys.argv[1]); "
          "module = importlib.util.module_from_spec(spec); sys.modules[spec.name] = module; "
          "spec.loader.exec_module(module)")


def annotations(tree):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = node.args
            for a in args.posonlyargs + args.args + args.kwonlyargs + [args.vararg, args.kwarg]:
                if a is not None and a.annotation is not None:
                    yield a.annotation
            if node.returns is not None:
                yield node.returns
        elif isinstance(node, ast.AnnAssign):
            yield node.annotation


def admits(spec, version):
    """True when a requires-python specifier made of >=, >, ==, <, <= clauses on X.Y admits `version`."""
    for clause in spec.split(","):
        m = re.fullmatch(r"\s*(>=|<=|==|>|<)\s*(\d+)\.(\d+)(?:\.\d+)?\s*", clause)
        assert m, f"requires-python clause not understood: {clause!r}"
        bound = (int(m.group(2)), int(m.group(3)))
        ok = {">=": version >= bound, ">": version > bound, "==": version == bound,
              "<": version < bound, "<=": version <= bound}[m.group(1)]
        if not ok:
            return False
    return True


def test_the_specifier_check_knows_what_admits_python_39():
    assert admits(">=3.9", SYSTEM_PYTHON) and admits(">=3.8,<3.13", SYSTEM_PYTHON)
    assert not admits(">=3.10", SYSTEM_PYTHON) and not admits(">=3.9,<3.9", SYSTEM_PYTHON)


def test_every_scheduler_provider_and_the_resolution_function_are_listed():
    shipped = {str(p.relative_to(REPO)) for p in (REPO / "providers" / "scheduler").glob("*.py")}
    shipped |= {str(p.relative_to(REPO)) for p in (REPO / "providers" / "store").glob("*.py")}
    assert shipped | {"providers/resolve.py"} <= set(ON_SYSTEM_PYTHON)


def union_problem(root, rel):
    """The message for a file of `root` that evaluates a `X | None` annotation on Python 3.9, or None."""
    tree = ast.parse((Path(root) / rel).read_text(encoding="utf-8"), feature_version=SYSTEM_PYTHON)
    deferred = any(isinstance(n, ast.ImportFrom) and n.module == "__future__" and
                   any(x.name == "annotations" for x in n.names) for n in tree.body)
    if deferred:
        return None
    unions = [ast.unparse(a) for a in annotations(tree)
              if any(isinstance(n, ast.BinOp) and isinstance(n.op, ast.BitOr) for n in ast.walk(a))]
    return f"{rel}: add 'from __future__ import annotations' (3.9 evaluates {unions[0]!r})" if unions else None


@pytest.mark.parametrize("rel", ON_SYSTEM_PYTHON)
def test_no_union_annotation_is_evaluated_on_python_39(rel):
    problem = union_problem(REPO, rel)
    assert not problem, problem


def test_the_list_of_runtime_modules_is_derived_and_complete():
    assert len(RUNTIME_FILES) >= 190, len(RUNTIME_FILES)
    assert {"runtime/ops.py", "runtime/phrases.py", "runtime/handlers/social.py"} <= set(RUNTIME_FILES)
    assert not [p for p in RUNTIME_FILES if p.startswith("runtime/tests/")], "the tests of the runtime are not on the scheduler's interpreter"
    assert len(set(ON_SYSTEM_PYTHON)) == len(ON_SYSTEM_PYTHON), "no entry twice"
    assert not set(RUNTIME_FILES) & set(OTHERS) and not [p for p in OTHERS if p.startswith("runtime/") and p.count("/") == 1], "OTHERS holds nothing the folders already give"
    assert all(p.endswith(".py") and (REPO / p).is_file() for p in ON_SYSTEM_PYTHON)


def test_every_excluded_module_exists_and_has_a_reason():
    for path, reason in EXCLUDED.items():
        assert (REPO / path).is_file(), path
        assert isinstance(reason, str) and reason.strip(), f"{path}: a reason is required"
    assert not set(EXCLUDED) & set(RUNTIME_FILES), "an excluded module is not in the list"


def test_vacuity_a_planted_runtime_module_is_derived_into_the_list_and_its_union_annotation_fails_the_check(tmp_path):
    (tmp_path / "runtime" / "handlers").mkdir(parents=True)
    (tmp_path / "runtime" / "zz_planted.py").write_text("def f(x: int | None) -> None:\n    return None\n", encoding="utf-8")
    (tmp_path / "runtime" / "zz_fine.py").write_text("from __future__ import annotations\n\n\ndef f(x: int | None) -> None:\n    return None\n", encoding="utf-8")
    found = sorted("runtime/" + p.name for p in (tmp_path / "runtime").glob("*.py"))
    assert found == ["runtime/zz_fine.py", "runtime/zz_planted.py"], "a planted module is picked up by the same glob the list uses"
    assert "3.9 evaluates" in union_problem(tmp_path, "runtime/zz_planted.py")
    assert union_problem(tmp_path, "runtime/zz_fine.py") is None


@pytest.mark.parametrize("rel", ON_SYSTEM_PYTHON)
def test_header_does_not_claim_a_newer_python_than_the_scheduler_uses(rel):
    head = (REPO / rel).read_text(encoding="utf-8")[:600]
    found = REQUIRES.search(head)
    if rel.startswith("providers/") or rel in RUNTIME:
        assert found, f"{rel}: a provider carries an inline-metadata header with requires-python"
    if rel in RUNTIME:  # RT16: providers/CONTRACT.md, "Python version", asks it of every script of this set
        assert '# requires-python = ">=3.9"' in head and "# dependencies = []" in head, rel
    if found:
        assert admits(found.group(1), SYSTEM_PYTHON), \
            f"{rel}: requires-python = {found.group(1)!r} excludes 3.9, the interpreter the scheduler starts it with"


@pytest.mark.parametrize("rel", ON_SYSTEM_PYTHON)
@pytest.mark.skipif(sys.version_info[:2] != SYSTEM_PYTHON, reason="the import is the check only on Python 3.9, the interpreter the scheduler starts these with: the python39 job runs it on every pull request and at night")
def test_imports_on_the_interpreter_running_the_tests(rel, tmp_path):
    """On the python39 CI job this is Python 3.9: definitions, annotations and imports are really evaluated."""
    path = REPO / rel
    r = subprocess.run([sys.executable, "-c", IMPORT, str(path), str(path.parent)], cwd=tmp_path,
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, f"{rel} does not import on Python {sys.version_info[:2]}: {r.stderr[-600:]}"
