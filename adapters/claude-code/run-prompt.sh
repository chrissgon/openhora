#!/usr/bin/env bash
# Eval contract: run one prompt through Claude Code non-interactively, inside the eval container.
#
# Usage: run-prompt.sh --prompt-file <f> --cwd <dir> --model <id> --out <dir>
#                      [--allow-web] [--max-cost-usd <amount>] [--no-tools]
#
# Writes <out>/response.md, the assistant's last message (the reply the grader is given), <out>/timing.json,
# <out>/stream.jsonl, the CLI's whole event stream (kept beside the reply, never shown to the grader), and
# <out>/raw.json, the stream's result event. timing.json also names two lists of skills of the case folder:
# "skills_loaded", the skills the stream shows the model loading (the skill tool, or any tool that reads a
# skill's SKILL.md: Read, Grep or Bash naming <skills folder>/<name>/SKILL.md), which the runner reads as
# whether the skill under test was invoked; and "skills_used" (R12), every skill whose folder any tool input
# names (a script run by its path, a reference read, a listing of the folder), a superset of "skills_loaded":
# a follow-up run that ran a skill's script without reading its text is "used" and not "loaded". A name is
# letters, digits, "." "_" "-" and does not start with a dot; the folder is followed by "/", a space, a quote
# or the end. A subagent's tool calls count as the model's. It installs nothing: the eval runner stages the
# skill under test and a case's dependency skills in <cwd>/.claude/skills/<name> before this script
# starts ("skills_dir" of this adapter's eval.json names that folder; scripts/stage_skills.py copies them),
# so they are discoverable at project scope. Settings are limited to the project scope; the runner
# refuses a case folder that carries a name of eval.json's "settings" (.claude, .mcp.json or
# the project-instructions files CLAUDE.md and CLAUDE.local.md, from a fixture or a setup), since the
# project scope would apply its rules, hooks, servers or instructions.
# No MCP servers or claude.ai connectors are loaded (--strict-mcp-config, ENABLE_CLAUDEAI_MCP_SERVERS=false).
# It runs only inside the eval container (evals/executor.py; the image sets WB_EVAL_CONTAINER=1) and
# refuses to start anywhere else: the container is the boundary, so every tool is allowed
# (--dangerously-skip-permissions), which on a person's machine would let a model do anything.
# --allow-web leaves WebSearch and WebFetch available, for a case that must search the web; without it
# both are disallowed.
# --no-tools is for a grading call: the model gets no tool at all (--tools ""), and no permission is
# skipped, since there is nothing to permit. A grader holds this tier's credential and reads text a
# model under test wrote; it judges that text and does not act. Not combined with --allow-web.
# --max-cost-usd becomes claude's --max-budget-usd: the run stops once it has spent that much.
# SLASH_COMMAND_TOOL_CHAR_BUDGET is raised (200000 unless set): the CLI lists skills to the model within a
# character budget, its own bundled skills first, and past the budget a project skill is listed by name
# only, with no description, so the model cannot tell when to use the skill under test.
# The CLI authenticates with CLAUDE_CODE_OAUTH_TOKEN (or ANTHROPIC_API_KEY) from the environment.
# In an eval run that variable holds a placeholder and ANTHROPIC_BASE_URL names the eval's key proxy, which holds
# the real value and adds it to each call (evals/executor.py): the CLI reads both from the environment.
# CLAUDE_CODE_WEB_API_KEY, when set, is used in place of both: the runner passes it, and not the account's
# token, to a run of a case on the open network only when evals/eval-gate.json names it in
# strong_web_pass_env, so that a leak there costs at most that key's limit; without that key such a run gets
# the account's token as a placeholder, held by the key proxy. It reaches the CLI as ANTHROPIC_API_KEY.
# Extra CLI flags: CLAUDE_EVAL_ARGS.
# The prompt reaches the CLI on standard input, not as an argument: a grading prompt with long files
# is larger than one argument may be.
# Stopping this script (TERM, INT, HUP) stops the CLI and everything it started.
# Exit codes: 0 the run ended normally; 1 it did not (the CLI failed, whatever code it gave); 2 a usage error
# of this script.
set -euo pipefail
PROMPT="" CWD="" MODEL="" OUT="" WEB="" MAX_COST="" NO_TOOLS=""
# A flag that takes a value and is given last, or followed by another flag, is a usage error (exit 2).
need() { [[ $# -ge 2 && -n "$2" && "$2" != --* ]] || { echo "Error: $1 needs a value. See --help." >&2; exit 2; }; }
while [[ $# -gt 0 ]]; do
  case "$1" in
    --prompt-file) need "$@"; PROMPT="$2"; shift 2 ;;
    --cwd) need "$@"; CWD="$2"; shift 2 ;;
    --model) need "$@"; MODEL="$2"; shift 2 ;;
    --out) need "$@"; OUT="$2"; shift 2 ;;
    --allow-web) WEB=1; shift ;;
    --no-tools) NO_TOOLS=1; shift ;;
    --max-cost-usd)
      need "$@"
      [[ "$2" =~ ^[0-9]+(\.[0-9]+)?$ ]] || { echo "Error: --max-cost-usd needs a number, e.g. 0.50." >&2; exit 2; }
      MAX_COST="$2"; shift 2 ;;
    --help|-h) sed -n '2,40p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Error: unknown option '$1'. See --help." >&2; exit 2 ;;
  esac
done
[[ -f "$PROMPT" && -d "$CWD" && -n "$MODEL" && -n "$OUT" ]] || { echo "Error: --prompt-file, --cwd, --model and --out are required. See --help." >&2; exit 2; }
[[ -z "$NO_TOOLS" || -z "$WEB" ]] || { echo "Error: --no-tools and --allow-web do not go together: a call with no tools has no web tools." >&2; exit 2; }
[[ "${WB_EVAL_CONTAINER:-}" == "1" ]] || { echo "Error: this adapter allows a model every tool, so it runs only inside the container that evals/eval_run.py starts." >&2; exit 2; }
command -v claude >/dev/null || { echo "Error: 'claude' CLI not found on PATH." >&2; exit 1; }
if [[ -n "${CLAUDE_CODE_WEB_API_KEY:-}" ]]; then
  export ANTHROPIC_API_KEY="$CLAUDE_CODE_WEB_API_KEY"
  unset CLAUDE_CODE_OAUTH_TOKEN CLAUDE_CODE_WEB_API_KEY
fi
mkdir -p "$OUT"
# The runner gets its own session, so everything it starts (model sessions, browsers) is one process group
# that can be stopped as a whole: when it exits, and when this script gets TERM, INT or HUP (a timeout or a
# stop of eval_run.py). Without it a stopped eval left model sessions working for minutes.
RUNNER_PID=""
stop_runner() {
  [[ -n "$RUNNER_PID" ]] || return 0
  kill -TERM -- "-$RUNNER_PID" 2>/dev/null || return 0
  for _ in 1 2 3 4 5 6 7 8 9 10; do kill -0 -- "-$RUNNER_PID" 2>/dev/null || return 0; sleep 0.2; done
  kill -KILL -- "-$RUNNER_PID" 2>/dev/null || true
}
# exec, so that the session leader is the background job itself and RUNNER_PID names its process group.
OWN_SESSION=(python3 -c 'import os, sys; os.setsid(); os.execvp(sys.argv[1], sys.argv[1:])')
trap 'stop_runner; exit 143' TERM INT HUP
START=$(python3 -c 'import time; print(int(time.time()*1000))')
set +e
if [[ -n "$NO_TOOLS" ]]; then
  EXTRA=(--tools "")   # the flag is in the 2.1.284 binary (a search of the package on 2026-10-16, no run): "" disables every built-in tool
else
  EXTRA=(--dangerously-skip-permissions)
  [[ -n "$WEB" ]] || EXTRA+=(--disallowedTools "WebSearch,WebFetch")
fi
[[ -n "$MAX_COST" ]] && EXTRA+=(--max-budget-usd "$MAX_COST")
# Connectors: https://code.claude.com/docs/en/mcp (read 2026-09-27): claude.ai connectors load when logged in
# with a claude.ai account unless ENABLE_CLAUDEAI_MCP_SERVERS=false, and `claude -p` loads project servers
# without asking unless --strict-mcp-config (the flag is in the 2.1.284 binary, found by a search of the package on 2026-10-16).
( cd "$CWD" && export ENABLE_CLAUDEAI_MCP_SERVERS=false SLASH_COMMAND_TOOL_CHAR_BUDGET="${SLASH_COMMAND_TOOL_CHAR_BUDGET:-200000}" && exec "${OWN_SESSION[@]}" claude -p --model "$MODEL" \
    --setting-sources project,local --strict-mcp-config --output-format stream-json --verbose ${CLAUDE_EVAL_ARGS:-} ${EXTRA[@]+"${EXTRA[@]}"} ) \
  < "$PROMPT" > "$OUT/stream.jsonl" 2> "$OUT/stderr.log" &
RUNNER_PID=$!
wait "$RUNNER_PID"; RC=$?
stop_runner   # what the CLI left running (a browser, a server) stops with it
set -e
END=$(python3 -c 'import time; print(int(time.time()*1000))')
python3 - "$OUT" "$START" "$END" "$RC" <<'PY'
import json, os, re, sys
out, start, end, rc = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4])
raw = open(os.path.join(out, "stream.jsonl"), encoding="utf-8", errors="ignore").read()
events = []
for line in raw.splitlines():
    try:
        item = json.loads(line)
    except ValueError:
        continue
    events.append(item) if isinstance(item, dict) else events.extend(x for x in item if isinstance(x, dict)) if isinstance(item, list) else None
# The result event carries the reply (the assistant's last message), the usage and the cost.
result = next((e for e in reversed(events) if e.get("type") == "result" or ("result" in e and "type" not in e)), None)
text, tokens, cost, dur = raw, None, None, end - start
if result is not None:
    text = result.get("result") if result.get("result") is not None else ""
    u = result.get("usage") or {}
    if u:
        tokens = sum(int(u.get(k) or 0) for k in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
    cost = result.get("total_cost_usd")
    dur = result.get("duration_ms") or dur
    json.dump(result, open(os.path.join(out, "raw.json"), "w"))
else:
    open(os.path.join(out, "raw.json"), "w", encoding="utf-8").write(raw)
# The skills the model touched. Loaded: the skill tool's input, or a tool that reads <skills folder>/<name>/SKILL.md
# (Read's file_path, Grep's path, Bash's command). Used: every skill whose folder any tool input names.
NAME = r"([A-Za-z0-9][A-Za-z0-9._-]*)"   # never "." or ".."
FOLDER_RE = re.compile(r"(?<![A-Za-z0-9._-])\.claude/skills/" + NAME + r"(?=[/\s'\"`]|$)")
SKILL_RE = re.compile(r"(?<![A-Za-z0-9._-])\.claude/skills/" + NAME + r"/SKILL\.md(?![A-Za-z0-9._-])")
READS = {"Read": "file_path", "Grep": "path", "Bash": "command"}


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)


def note(into, names):
    for n in names:
        if n not in into:
            into.append(n)


loaded, used = [], []
for e in events:
    content = (e.get("message") or {}).get("content") if e.get("type") == "assistant" else None
    for block in content if isinstance(content, list) else []:
        if not isinstance(block, dict) or block.get("type") != "tool_use":
            continue
        args = block.get("input") or {}
        names = []
        if block.get("name") == "Skill" and isinstance(args, dict):
            name = args.get("skill") or args.get("command") or args.get("name")
            if isinstance(name, str) and name.strip("/"):
                names.append(name.strip("/"))
        field = READS.get(block.get("name"))
        chunk = args.get(field) if field and isinstance(args, dict) else None
        names += [m.group(1) for m in SKILL_RE.finditer(chunk)] if isinstance(chunk, str) else []
        note(loaded, names)
        note(used, names)
        for chunk in strings(args):
            note(used, [m.group(1) for m in FOLDER_RE.finditer(chunk)])
open(os.path.join(out, "response.md"), "w", encoding="utf-8").write(text if isinstance(text, str) else json.dumps(text))
json.dump({"total_tokens": tokens, "duration_ms": dur, "cost_usd": cost, "exit_code": rc,
           **({"skills_loaded": loaded, "skills_used": used} if events else {})}, open(os.path.join(out, "timing.json"), "w"))
sys.exit(0 if rc == 0 else 1)
PY
