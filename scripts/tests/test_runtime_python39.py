"""The scheduled tick runs scripts/runtime.py with /usr/bin/python3 (Python 3.9 on macOS), and the runtime starts
the scripts below with that same interpreter (providers/CONTRACT.md, "Python version"). Three guards:

1. Syntax: each file parses as Python 3.9, and a `X | None` annotation, which 3.9 evaluates at definition time and
   refuses, is either absent or deferred with `from __future__ import annotations`.
2. Header: a script with an inline-metadata header declares a `requires-python` that admits 3.9, so the header
   never claims a newer interpreter than the one the scheduler starts it with.
3. Execution: each file is imported by the interpreter running this test. CI runs this file, and the tests of the
   scripts on this path, on Python 3.9 (.github/workflows/checks.yml, job python39), where the import is the real check.

Providers that reach the network run through `uv run` under their own `requires-python` and are not listed.
A new script the runtime or a scheduler starts with the system interpreter is added to ON_SYSTEM_PYTHON."""
import ast
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
ON_SYSTEM_PYTHON = [
    "scripts/runtime.py", "scripts/runtime_vote.py", "scripts/vote_job.py", "scripts/redact.py",
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
    "scripts/evidence.py", "evals/eval_status.py", "evals/evidence_lines.py",
    # The task runtime: its shell runs on the system interpreter, and a scheduler will start its dispatcher.
    "runtime/lab.py", "runtime/ops.py", "runtime/ops_core.py", "runtime/ops_say.py", "runtime/ops_reads.py", "runtime/ops_waits.py", "runtime/ops_config.py", "runtime/ops_runs.py", "runtime/ops_models.py", "runtime/prices.py", "runtime/cli.py", "runtime/flow_files.py", "runtime/skill_meta.py",
    "runtime/path_rule.py", "runtime/state_merge.py", "runtime/endings.py", "runtime/project_config.py",
    "runtime/manifest.py", "runtime/workcopy.py", "runtime/proof.py", "runtime/router.py", "runtime/plan.py",
    "runtime/board.py", "runtime/documents.py", "runtime/drop.py", "runtime/deps.py", "runtime/changeset.py", "runtime/effects.py", "runtime/effect_pull_request.py", "runtime/effect_commit.py", "runtime/effect_reply.py",
    "runtime/progress.py", "runtime/autonomy.py", "runtime/dispatcher.py", "runtime/chat.py", "runtime/operations.py",
    # The local service (stage 9): it serves the operations layer, so it runs where the layer runs.
    "runtime/service.py", "runtime/service_bridge.py",
    # The MCP mode (stage 9): the same operations layer over standard input and output.
    "runtime/mcp.py",
    # The messaging bridge (MSG-1): its shell and its modules, started with the system interpreter like the other shells.
    "runtime/messaging.py", "runtime/messaging_bridge.py", "runtime/messaging_cards.py", "runtime/messaging_inbound.py",
    "runtime/messaging_ledger.py", "runtime/messaging_provider.py",
    # What the two shells share (stage 9, WP-9.9): the job registry, the status words, the project list.
    "runtime/shell_kit.py",
    # The cost of a run recomputed from its token counts (stage 9): the operations layer imports it.
    "runtime/costs.py",
    # The generic streaming intake of a body (P0): a source module of the runtime calls it.
    "runtime/intake.py",
    # The sources of a project (P4): the registry, the versions, the catalog and the guardrails of the folder, and the ingest operations.
    # The document converter's provider runs a container; the host side is plain Python and runs on the scheduler's interpreter too.
    "runtime/sources.py", "runtime/sources_onedrive.py", "runtime/sources_mail.py", "runtime/snapshot_text.py", "runtime/ops_sources.py", "providers/converter/container.py",
    # Files sent through a messaging app (ATT-1): the limits and folders of the hold, and the operations over it.
    "runtime/attachments.py", "runtime/ops_attachments.py", "runtime/messaging_attach.py",
    # The start of a write to the person's own accounts (FND): the one function an operation of the family calls.
    "runtime/account_start.py",
    # Reminders (RM-1): the pure part, the operations and the bridge's part.
    "runtime/reminders.py", "runtime/ops_reminders.py", "runtime/messaging_remind.py",
    # package P-OPS: upkeep (retention), the orphan containers, the lease of the sources folder, the secret store's state
    "runtime/upkeep.py", "runtime/orphans.py", "runtime/lease.py", "runtime/secret_state.py", "runtime/ops_cancel.py", "runtime/run_stop.py",
    # S16: the password-manager backends, loaded by path by the resolver, which the runtime loads under the system interpreter too.
    "providers/secrets/password_managers.py",
    # The step engine (P5): the engine, the run of a step task (a process the dispatcher starts), and the kind `ingest`.
    "runtime/steps.py", "runtime/ops_steps.py", "runtime/step_ingest.py", "runtime/step_export.py", "runtime/step_write_back.py",
    "runtime/effect_write.py", "runtime/ops_step_effects.py", "runtime/write_document.py", "runtime/ops_step_seams.py",
    # Outputs to the documents platform (NOTION-OUT): the kinds, the document of a new page or table, and the table reader.
    "runtime/step_output.py", "runtime/output_document.py", "runtime/table_data.py", "runtime/ops_cancel.py",
    # E-mail sent from the project's outbox (EMAIL-SEND): the kind, the document, the effect, the address rule, and the provider with its shared code.
    "runtime/step_send_email.py", "runtime/send_document.py", "runtime/effect_send.py", "runtime/mail_address.py",
    "providers/_email.py", "providers/mailer/smtp.py",
    # A post published from the approval path (PUBLISH-EFFECT): the kind, the document, the script runner, and the effect that fronts the word `publish`.
    "runtime/step_publish_post.py", "runtime/publish_document.py", "runtime/publish_payload.py", "runtime/effect_publish.py",
    # The flows (P6a): the flow check, and the operations over flow files (list, check, save a plan, stage a file).
    "runtime/flow_check.py", "runtime/ops_flows.py",
    # The routines (P6b): the pure schedule and content, and the operations and the tick.
    "runtime/routines.py", "runtime/ops_routines.py",
    # The person's standing instructions (package INSTRUCTIONS): the file and its checks, and the operations over it.
    "runtime/instructions.py", "runtime/ops_instructions.py", "runtime/ops_contained.py",
    # The grants of the channel policy (POL-1): the effect's word and card, and the widening list with its hash; who acted (POL-2): the sender, its profile and the record.
    "runtime/ops_grants.py", "runtime/policy_grants.py", "runtime/policy_widening.py", "runtime/ops_actor.py",
    # The language the deliverables are written in (LANGUAGE): the rule, the order and the words; the operations that check a request's choice.
    "runtime/language.py", "runtime/ops_language.py",
    # The runtime's replies in the project's language (LR-1): the phrase table and the function that picks a sentence.
    "runtime/phrases.py", "runtime/phrases_pt_br.py",
    # The answer from sources (AQ-1): the selection of the sources a question reads, the checks of the reply, and the operation `ask`.
    "runtime/ask_select.py", "runtime/ask_reply.py", "runtime/ops_ask.py",
    # The project script (P9): the step kind, the provider's host side (it loads the two programs that run inside its image, which parse here too).
    "runtime/step_project_script.py", "providers/script/container.py", "providers/script/egress_proxy.py", "providers/script/_inner.py",
    # The rules of tasks that run at once (PAR-2): pure functions the dispatcher's caller passes in.
    "runtime/parallel.py",
    # How the credential of a run is billed, read from the adapters' manifests (ADJ-R3): the operations layer imports it.
    "runtime/billing.py",
    # The roles of the runtime as data, and the isolated runner of skill code (WP-R.5).
    "runtime/roles.py", "runtime/isolated.py",
    # The handlers the dispatcher's worker ticks (stage 6): the weekly routine of the published posts (WP-6.9).
    "runtime/handlers/published_posts.py",
    # The ported social agent (stage 7, WP-7.1): the scheduler will start the tick, and the vote step and its job.
    "runtime/handlers/social.py", "runtime/handlers/social_vote.py", "runtime/handlers/social_vote_job.py",
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
]
RUNTIME = ("scripts/runtime.py", "scripts/runtime_vote.py", "scripts/vote_job.py",
           "runtime/handlers/social.py", "runtime/handlers/social_vote_job.py")  # the scheduler starts these
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


@pytest.mark.parametrize("rel", ON_SYSTEM_PYTHON)
def test_no_union_annotation_is_evaluated_on_python_39(rel):
    tree = ast.parse((REPO / rel).read_text(encoding="utf-8"), feature_version=SYSTEM_PYTHON)
    deferred = any(isinstance(n, ast.ImportFrom) and n.module == "__future__" and
                   any(x.name == "annotations" for x in n.names) for n in tree.body)
    if deferred:
        return
    unions = [ast.unparse(a) for a in annotations(tree)
              if any(isinstance(n, ast.BinOp) and isinstance(n.op, ast.BitOr) for n in ast.walk(a))]
    assert not unions, f"{rel}: add 'from __future__ import annotations' (3.9 evaluates {unions[0]!r})"


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
def test_imports_on_the_interpreter_running_the_tests(rel, tmp_path):
    """On the python39 CI job this is Python 3.9: definitions, annotations and imports are really evaluated."""
    path = REPO / rel
    r = subprocess.run([sys.executable, "-c", IMPORT, str(path), str(path.parent)], cwd=tmp_path,
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, f"{rel} does not import on Python {sys.version_info[:2]}: {r.stderr[-600:]}"
