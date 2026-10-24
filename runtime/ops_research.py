#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""A question of general information answered by a web search (slice R2-F1): `research`, one run of the skill `core-research` with web access.

  research(project, question, [channel, sender])          the operation (the terminal, a messaging app): {"reply", "ran", "status", "refusal", "request_id", "run_id", "links"}
  reply(project, ctx, args, said, channel, sender, extras) the reply a line in words gets (runtime/ops_natural.py `run` calls it for `research`)
  stop(project, sender)                                    the brake (BL2a): the sender's own running search is cancelled; True when one was running (below)

The interpreter picks `research` for a question of general information (the weather, a price or a quote, the news, a fact) that no file or source of the person's own answers. It is a
read in the interpreter's catalog and the one read that calls a model: code, not the router, runs one task with the skill NAMED HERE (SKILL), so no question is put to the person first
and no plan is made. What code decides, in this order, before anything runs:

  1. The policy: from a messaging app the sender's profile must hold the group `research` (in no default policy; `accept-config --widen` shows that the question goes to a web search
     service and to the model that runs the research); the terminal is never narrowed; the page and the MCP mode have no row.
  2. The skill: a folder of this checkout that declares `search:web` and no side effect (else the sentence RS_NOT_BUILT). It is outside every area agent's pack and needs no runtime
     manifest: nothing it writes comes back.
  3. The routing, by the rule of every conversation run (runtime/ops_models.py): the project's default model, else `auto` (the cheapest pair on which the skill is `reliable`, else the
     reference model). The web is allowed only when the chosen pair was MEASURED with the web (the proof's `web`): a pair that was not runs nothing and the reply says there is no web
     (RS_NO_WEB). Proof decides what a model may be asked to do; it is never traded for an answer.
  3b. The question: one that holds a possessive form of a source of the project ("minha agenda", "my e-mails", runtime/research_guard.py) is not run: the sentence that asks again.
  4. The bounds, from the configuration's key `research` (runtime/project_config.py): at most `max_per_day` runs in a local day (counted from the store, whatever their end), and, per
     run, `max_cost_usd` (the adapter's --max-cost-usd) and `timeout_seconds`. The route lock (one conversation model call per project) is held for the run.

The run (ops_contained.execute with open_web): the open network, the adapter's --allow-web, one attempt, and NO file of the project in the copy, so the run sees nothing of the project; its
prompt is the question in the person's words and a fixed task text that names the consumer (the chat): NOT the person's standing instructions either, because a page the run reads could
ask it to send them out (a run on the open network gets nothing of the project, in its files or in its prompt). Nothing it writes comes back. Its brief is read from the copy (runtime/research_reply.py) to write the reply: a few plain lines, the sources as short links, cut to the limit of a
message, with no skill, flow or file name and no code fence; a run that is not proven says so in one sentence. A failure (no web, a timeout, the cost cap, any other) is one plain sentence.

The brake (BL2a, the maintainer's decision of 2026-10-24). On a messaging app a search that runs is recorded in memory for the sender who asked it (runtime/pending_items.py, kind `research-run`,
the request id only); that sender's stop word (runtime/plan_confirm.py `stop_form`, a closed list; the messaging bridge reads it under L64's conditions) calls `stop`, which cancels THAT
request through the cancel path that stops what runs (runtime/ops_cancel.py `cancel_request`: its watcher is the one `_run` passes to the run). It reaches no other sender's search and no request that
is not a research. The reply is RS_CANCELLED. Nothing of the question is in the record.

What is kept (limits L50 and L63): the question is the person's line, which the interpreter stores as a neutral word; the reply is stored as a neutral word too (RS_STORED), so the
conversation, which the MCP mode reads, holds neither. The run is a row of the store as an answer run is (a request called "Question <n>" whose text is the neutral word "web research",
and its run: the skill, the model, the cost, the tokens), which is what the daily count and the costs read; neither holds the question or the answer. The run folder
(<data_dir>/contained-runs/<n>/) holds the prompt and the brief for the project's retention (`run_retention_days`) like every contained run, outside git. Nothing here logs, prints or
stores the question or the answer; an error prints the name of its type only.

Sibling of runtime/ops.py, which exposes `research` under its name. The shared names come from ops_core, read as `core.<name>`; what stays in runtime/ops.py is reached at call time
through `_ops()`. Standard library only. Runs on Python 3.9: python3 runtime/ops_research.py --help
"""
from __future__ import annotations

import contextlib
import importlib
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lab  # noqa: E402
import line_stage  # noqa: E402
import natural  # noqa: E402
import operations  # noqa: E402
import ops_actor  # noqa: E402
import ops_cancel  # noqa: E402
import ops_contained  # noqa: E402
import ops_core as core  # noqa: E402
import pending_items  # noqa: E402
import phrases  # noqa: E402
import research_guard  # noqa: E402
import research_reply  # noqa: E402
import skill_meta  # noqa: E402
import workcopy  # noqa: E402

SKILL = "core-research"
QUESTION_MAX = 500         # characters of a question (a line on a messaging app is cut well before this by its span)
PHONE_MAX = 1800           # characters of a reply on a messaging app (the limit of a read: ops_natural.RENDER_MAX)
OTHER_MAX = 6000           # ... and on any other channel
NEUTRAL = "web research"   # the text of the request a run makes: the question is never in the store
TASK_TEXT = ("answer the question above with a web search, as your skill does. The decision it informs: the person asked it in a chat and reads your answer there; "
             "there is no other consumer. Use the defaults of your skill for the scope and mark them assumed; ask nothing back. Write the brief to "
             "docs/workbench/research/answer.md and keep the answer short: at most five lines under Answer in brief, each with its source number. "
             "Write the brief and the reply in the language of the question.")
FAILURES = {"timeout": "RS_TIMEOUT"}      # a failure kind with a sentence of its own; every other one is RS_FAILED


def _ops():
    """runtime/ops.py, found at call time."""
    return importlib.import_module("ops")


def _outcome(reply: str, status: str, **more) -> dict:
    return {"reply": reply, "ran": False, "status": status, "refusal": None if status == "answer" else status, "request_id": None, "run_id": None, "links": [], **more}


def _check_policy(ctx: dict, channel, sender) -> None:
    """The policy again, in the operation: a messaging sender by their profile; any other channel by the table (the page and the MCP mode have no row, so they are refused)."""
    ops_actor.guard(ctx, "research", channel, sender)
    carried = ops_actor.label(ctx["cfg"], channel, sender)
    if carried in ("page", "mcp"):
        refused = operations.refusal("research", carried, ctx["cfg"]["channels"])
        if refused:
            raise core.OpsError(refused, 1)


def _still_may(project: str, channel, sender) -> bool:
    """Whether the asker may still ask, read from the configuration as it is NOW (the research took minutes): a sender removed from the list, narrowed to a profile without `research`, or a
    configuration that is no longer the accepted one gets nothing. The terminal is never narrowed."""
    try:
        fresh = core.context(project)
    except core.OpsError:
        return False
    cfg = fresh["cfg"]
    where = ops_actor.label(cfg, channel, sender)
    if where in (None, "terminal", "chat"):
        return True
    if channel == "messaging":
        platform, ident = ops_actor.split(sender)
        if ident not in ((cfg.get("messaging") or {}).get("senders") or {}).get(platform, ()):
            return False
        return operations.permitted("research", "messaging", cfg["channels"], None, sender)
    return operations.permitted("research", where, cfg["channels"])


def _scope() -> dict:
    """The skill's declarations, or OpsError: a folder of this checkout that requires the web and has no side effect (a research that could act is not run from a line)."""
    try:
        meta = skill_meta.declared(os.path.join(core.ROOT, "skills", SKILL))
    except skill_meta.SkillError:
        raise core.OpsError("the research skill is not in this checkout", 3) from None
    if not meta["web"] or meta["side_effects"]:
        raise core.OpsError("the research skill does not declare the web and no side effect", 3)
    return meta


def _today(ctx: dict) -> int:
    """How many research runs were started today (local day), whatever their end."""
    store = ctx["store"]
    rows = core._stored(ctx, store.runs_since, _ops()._midnight_utc())
    return sum(1 for row in rows if row.get("skill") == SKILL and row.get("task_id") == row.get("request_id"))      # a run on a REQUEST: a task of a flow or of an agent that runs the same skill is not counted


def _links(parsed: dict, shown: str) -> list:
    return [link for link in parsed["links"].values() if link in shown]


def _failure_word(result: dict, cap: float) -> str:
    """The phrase key for a run that failed: the timeout, the cost cap (a reported cost at the cap), else the general sentence."""
    failure = result.get("failure") or {}
    if failure.get("kind") in FAILURES:
        return FAILURES[failure["kind"]]
    spent = (result.get("reported") or {}).get("cost_usd")
    if isinstance(spent, (int, float)) and not isinstance(spent, bool) and spent >= cap:
        return "RS_CAP"
    return "RS_FAILED"


def _research(project: str, ctx: dict, question: str, channel, sender, line=None) -> dict:
    cfg, store = ctx["cfg"], ctx["store"]
    t = lambda key, **fields: phrases.text(key, cfg, **fields)  # noqa: E731
    limits = cfg["research"]
    limit = PHONE_MAX if channel == "messaging" else OTHER_MAX
    if research_guard.personal(question, line):      # about the person's own calendar, mail or files: not for a web search, whatever the model said
        return _outcome(t("IX_ASK_AGAIN"), "personal")
    try:
        _scope()
    except core.OpsError:
        return _outcome(t("RS_NOT_BUILT"), "not-built")
    line_stage.publish("research")      # S19: the stage a phone is told if the reply takes a while
    try:
        meta, keys, routing = ops_contained.routed(ctx, SKILL)
    except core.OpsError:
        return _outcome(t("RS_FAILED"), "failed")
    if not routing["web"]:      # the pair was not measured with the web: proof decides, so nothing runs
        return _outcome(t("RS_NO_WEB"), "no-web")
    try:
        identity = lab.skill_identity(SKILL)
        prompt = _ops().task_prompt(question, TASK_TEXT, [])      # the question and the fixed task text: no standing instructions and nothing else of the project (the run is on the open network)
    except lab.LabError:
        return _outcome(t("RS_FAILED"), "failed")
    with core._route_lock(cfg):      # RunBusy: one conversation model call per project at a time
        importlib.import_module("ops_runs")._recover(ctx, holding_route=True)
        number, dest = ops_contained._contained_folder(cfg)
        prepared_dir = os.path.join(cfg["data_dir"], core.PREPARED_DIR, f"contained-{number}")
        try:
            with core._claim_lock(cfg):      # the day's count and the run row are one step
                made = _today(ctx)
                if made >= limits["max_per_day"]:
                    return _outcome(t("RS_LIMIT_ONE") if made == 1 else t("RS_LIMIT", count=made), "limit")
                started = core._stored(ctx, store.answer_run_start, skill=SKILL, model=routing["model"], adapter=routing["adapter"],
                                       skill_version=identity["version"], skill_sha256=identity["content_sha256"],
                                       billing=routing["billing"] or "unknown", autonomy=routing["autonomy"], title=store.ANSWER_TITLE, text=NEUTRAL, web=True)
            running = None
            if channel == "messaging":      # the brake: the sender's stop word reaches this run (`stop`)
                running = pending_items.new_item("research-run", *_binding(project, sender), state={"request_id": started["request_id"]})
                pending_items.put(running)
            try:
                return _run(project, ctx, question, channel, sender, meta, keys, routing, prompt, started, dest, prepared_dir, limit)
            finally:
                if running is not None:
                    pending_items.pop(running["id"])
        finally:
            shutil.rmtree(prepared_dir, ignore_errors=True)
            with contextlib.suppress(OSError):
                os.rmdir(dest)      # a refusal before the run leaves the folder it claimed empty: it goes (a folder with a run in it stays)


def _run(project, ctx, question, channel, sender, meta, keys, routing, prompt, started, dest, prepared_dir, limit) -> dict:
    cfg, store = ctx["cfg"], ctx["store"]
    t = lambda key, **fields: phrases.text(key, cfg, **fields)  # noqa: E731
    limits = cfg["research"]
    request_id, run_id = started["request_id"], started["run_id"]
    base = {"request_id": request_id, "run_id": run_id}

    def finish(**fields):
        """End the run and its request (one transaction). A request cancelled meanwhile has the run recorded cancelled: nothing is answered, and this returns the outcome that says so."""
        done = core._stored(ctx, store.answer_run_finish, run_id, run_dir=dest, **fields)
        return _outcome(t("RS_CANCELLED"), "cancelled", ran=True, **base) if done["cancelled"] else None

    def fail(kind: str, reason: str, word: str, counts=None, image=None, reported=None) -> dict:
        return finish(status="failed", failure=kind, attempts=(counts or {}).get("attempts", 0), image_digest=image,
                      error=_ops()._note(reason), **_ops()._reported_usage(reported, routing)) or _outcome(t(word), "failed" if word == "RS_FAILED" else word[3:].lower(), ran=True, **base)

    try:
        result = ops_contained.execute(ctx, SKILL, meta, keys, routing, prompt, timeout=limits["timeout_seconds"], dest=dest, prepared_dir=prepared_dir,
                                       max_cost=limits["max_cost_usd"], around=ops_cancel.watch(ctx, request_id), open_web=True)
    except core.OpsError:
        return fail("internal", "the run could not be made", "RS_FAILED")
    except Exception as e:      # the run row never stays `running`; the error is recorded by its type only, never its text (it can hold the question)
        print(f"research: internal error {type(e).__name__}", file=sys.stderr)
        return fail("internal", f"internal error {type(e).__name__}", "RS_FAILED")
    counts, timing = result["counts"], result["timing"]
    if result["status"] != "ok":
        failure = result["failure"]
        return fail(failure["kind"], failure["reason"], _failure_word(result, limits["max_cost_usd"]), counts, result["image_digest"], result.get("reported"))
    parsed = research_reply.parse(workcopy.masked_reply(result["response"])[0], research_reply.read_brief(result["cwd"]))
    proven = routing["autonomy"] == "proven"
    words = {"no-web": "RS_NO_WEB", "ask-again": "RS_ASK_AGAIN", "nothing": "RS_NOTHING", "unreadable": "RS_FAILED"}
    if parsed["status"] == "answer":
        shown, _masked = workcopy.masked_reply(research_reply.render(parsed, cfg, proven, limit))
    else:
        shown = t(words[parsed["status"]])
    number_of = lambda key, kind: timing.get(key) if isinstance(timing.get(key), kind) and not isinstance(timing.get(key), bool) else None  # noqa: E731
    every = _ops()._reported_usage(lab.reported_usage(dest), routing)
    cancelled = finish(status="ok", attempts=counts["attempts"],
                       cost_usd=every.get("cost_usd", number_of("cost_usd", (int, float)) if routing["billing"] == "metered" else None),
                       tokens=every.get("tokens", number_of("total_tokens", int)), duration_ms=number_of("duration_ms", int),
                       skill_loaded=_ops()._skill_loaded(timing, SKILL), image_digest=result["image_digest"], redactions=_ops()._count(counts.get("redactions")))
    if cancelled:
        return cancelled
    if not _still_may(project, channel, sender):
        return _outcome(t("WITHHELD"), "withheld", ran=True, **base)      # the run is recorded: it was made and spent
    out = _outcome(shown, parsed["status"], ran=True, **base)
    out["links"] = _links(parsed, shown) if parsed["status"] == "answer" else []
    return out


def _binding(project: str, sender) -> tuple:
    """The key of a sender's running search in runtime/pending_items.py: (the project's id in the shells, "messaging", the sender)."""
    return (importlib.import_module("ops_natural").project_key(project), "messaging", sender or "")


def stop(project: str, sender) -> bool:
    """The brake: cancel THIS sender's running web search. True when one was running and was cancelled; False for no search, a search of another sender, and a sender whose profile does not
    hold `research` now (the policy again, as `_still_may` asks it). It says nothing to the person (the search's own reply, RS_CANCELLED, does) and keeps nothing. The cancel is the path that
    stops what runs, called with the request id this sender's own record names; no other request can be named here. The call is not made as the messaging sender: that path would ask the
    group `cancel`, which a sender who may search need not hold, and the stop word is the answer to this sender's own search."""
    ctx = core.context(project)
    if not operations.permitted("research", "messaging", ctx["cfg"]["channels"], None, sender):
        return False
    item = pending_items.find(_binding(project, sender), "research-run")
    if item is None:
        return False
    ops_cancel.cancel_request(ctx, item["state"]["request_id"], by="person from messaging")
    return True


def _question(value, what: str = "the question") -> str:
    text = core._text(value, what)
    if len(text) > QUESTION_MAX:
        raise core.OpsError(f"{what} is over {QUESTION_MAX} characters", 2)
    return text


def research(project: str, question: str, channel: str | None = None, sender: str | None = None) -> dict:
    """The operation `research`: answer one question of general information from a web search. From a messaging app the sender's profile must hold the group `research` (the sentence the
    bridge uses otherwise). Raises OpsError for what is not an answer: a refused channel (1), an empty or long question (2); RunBusy while the router or another answer is running.
    Returns {"reply": the text for the person, "ran": whether a model ran, "status": answer | not-built | no-web | limit | failed | timeout | cap | ask-again | nothing | cancelled |
    withheld, "refusal": the same word when nothing was answered, else None, "request_id", "run_id", "links": the sources shown}."""
    ctx = core.context(project)
    _check_policy(ctx, channel, sender)
    return _research(project, ctx, _question(question), channel, sender)


def reply(project: str, ctx: dict, args: dict, said: str, channel, sender, extras: dict) -> str:
    """The reply of `research` chosen by the interpreter (runtime/ops_natural.py `run` has already asked the policy). The question is checked to be a span of the line, as the name of a
    file is; else the fixed ask-again sentence and nothing runs. The conversation keeps a neutral word for the reply, and the interpreter stored the line as one."""
    cfg = ctx["cfg"]
    extras["stored"] = phrases.text("RS_STORED", cfg)
    wanted = args.get("question")
    if not isinstance(wanted, str) or not natural.normal(wanted) or natural.normal(wanted) not in natural.normal(said) or len(wanted.strip()) > QUESTION_MAX:
        return phrases.text("IX_ASK_AGAIN", cfg)
    try:
        return _research(project, ctx, wanted.strip(), channel, sender, said)["reply"]
    except core.RunBusy:
        return phrases.text("RS_BUSY", cfg)
    except core.OpsError as e:
        return phrases.text("RS_FAILED", cfg) if channel == "messaging" else "error: " + phrases.localize(str(e), cfg)


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
