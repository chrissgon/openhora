#!/usr/bin/env bash
# Eval contract for tools that read .agents/skills. Default runner: OpenCode (`opencode run`).
#
# Usage: run-prompt.sh --prompt-file <f> --cwd <dir> --model <id> --out <dir>
#                      [--allow-web] [--max-cost-usd <amount>]
#
# Writes <out>/response.md, the assistant's last message (the reply the grader is given), <out>/timing.json
# (the tokens and the cost the runner's step events report; "skills_loaded", the skills of the case folder
# the events show the model loading: the skill tool, or any tool that reads <skills folder>/<name>/SKILL.md
# (read, grep or bash naming the SKILL.md of one skill); and "skills_used" (R12), every skill whose folder a command,
# a path or a pattern names (never a write's content or a subagent's prompt), a script run by its path, a reference
# read, a listing of the folder: a superset of "skills_loaded", so a
# follow-up run that ran a script without reading the skill's text is used and not loaded; one command or grep that names
# the SKILL.md of two skills loads neither, an under-report: both are used; the folder ends at "/", whitespace, a
# quote, a backtick, one of ; | ) & < > : or the end) and
# <out>/stream.jsonl, the runner's whole event stream (`run --format json`), kept beside the reply and never
# shown to the grader. A custom runner (RUN_PROMPT_CMD) prints text:
# that text is the reply, and its tokens are unknown (null). It installs nothing: the eval
# runner stages the skill under test and a case's dependency skills in <cwd>/.agents/skills/<name>
# before this script starts ("skills_dir" of this adapter's eval.json names that folder). The runner refuses
# a case folder that carries a name of eval.json's "settings": .agents/, .opencode/ and
# opencode.json[c], and what the default runner also reads at project level, another tool's skills
# folder and instruction file (.claude/, CLAUDE.md) and its own older instruction file (CONTEXT.md);
# checked in the binary of opencode 1.18.32. AGENTS.md is not in the list: it is the project's own
# instruction file, which fixtures ship and this runner reads.
# Override the command with RUN_PROMPT_CMD, a template with {prompt_file}, {model} and {cwd}, each
# replaced by a shell-quoted value, e.g. RUN_PROMPT_CMD='mytool --model {model} < {prompt_file}'. The command
# gets RUN_PROMPT_ALLOW_WEB=1 in its environment with --allow-web, 0 without, so that it can search or not.
# Flags verified against opencode 1.18.32 (run --help); re-check after upgrades.
# It runs only inside the eval container (evals/executor.py; the image sets WB_EVAL_CONTAINER=1) and
# refuses to start anywhere else: the default runner approves every tool (--auto), and the container is
# the boundary. --allow-web turns on the default runner's web search (OPENCODE_ENABLE_EXA=1, verified with
# opencode 1.18.32: without it the model can only fetch URLs it guesses). Without --allow-web the page-fetch tool
# is denied (OPENCODE_PERMISSION, read by opencode 1.18.32: --auto approves only what is not denied), so both
# tiers have the same tools on a case without the web.
# A model id "ollama/<name>" runs a local model served by Ollama (http://127.0.0.1:11434, or
# RUN_PROMPT_OLLAMA_URL): the provider entry is written into the throwaway HOME, never into the case
# folder. Give the model a context that fits the runner's own prompt and the skill (see README.md).
# A model id "local/<name>@<12 hex>" (the weights' hash) runs a model the eval container serves beside the run, on the
# run's internal network (LOCAL_MODEL_BASE_URL, LOCAL_MODEL_CONTEXT; see the block below and README.md).
# A model id "openrouter/<vendor>/<model>" with OPENROUTER_BASE_URL set (the eval container's key proxy) sends
# its calls to that base URL; the key is the proxy's, and OPENROUTER_API_KEY in the run holds a placeholder.
# Stopping this script (TERM, INT, HUP) stops the runner and everything it started.
# Connectors and MCP servers: the throwaway HOME below hides the user's configuration and
# project configuration is refused, so none load; RUN_PROMPT_KEEP_HOME=1 loses that guarantee.
# Exit codes: 0 the run ended normally; 1 it did not (the runner failed, whatever code it gave); 2 a usage
# error of this script.
set -euo pipefail
PROMPT="" CWD="" MODEL="" OUT="" WEB=0 CAPPED=0 STRUCTURED=0
# A flag that takes a value and is given last, or followed by another flag, is a usage error (exit 2).
need() { [[ $# -ge 2 && -n "$2" && "$2" != --* ]] || { echo "Error: $1 needs a value. See --help." >&2; exit 2; }; }
while [[ $# -gt 0 ]]; do
  case "$1" in
    --prompt-file) need "$@"; PROMPT="$2"; shift 2 ;;
    --cwd) need "$@"; CWD="$2"; shift 2 ;;
    --model) need "$@"; MODEL="$2"; shift 2 ;;
    --out) need "$@"; OUT="$2"; shift 2 ;;
    --allow-web) WEB=1; shift ;;
    --max-cost-usd)
      need "$@"
      [[ "$2" =~ ^[0-9]+(\.[0-9]+)?$ ]] || { echo "Error: --max-cost-usd needs a number, e.g. 0.50." >&2; exit 2; }
      CAPPED=1; shift 2 ;;
    --help|-h) sed -n '2,40p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Error: unknown option '$1'. See --help." >&2; exit 2 ;;
  esac
done
[[ -f "$PROMPT" && -d "$CWD" && -n "$MODEL" && -n "$OUT" ]] || { echo "Error: --prompt-file, --cwd, --model and --out are required. See --help." >&2; exit 2; }
[[ "${WB_EVAL_CONTAINER:-}" == "1" ]] || { echo "Error: this adapter approves every tool a model asks for, so it runs only inside the container that evals/eval_run.py starts." >&2; exit 2; }
mkdir -p "$OUT"
[[ $CAPPED -eq 1 ]] && echo "note: --max-cost-usd is not enforced by this runner (opencode has no spend limit); eval_run.py --timeout and a credit limit on the provider key are the caps." >&2
if [[ -n "${RUN_PROMPT_CMD:-}" ]]; then
  # Values are shell-quoted so a model id or path cannot add commands to the template.
  CMD="${RUN_PROMPT_CMD//\{prompt_file\}/$(printf '%q' "$PROMPT")}"
  CMD="${CMD//\{model\}/$(printf '%q' "$MODEL")}"
  CMD="${CMD//\{cwd\}/$(printf '%q' "$CWD")}"
  RUN=(bash -c "$CMD")  # security-scan: allow shell-string -- the template is the operator's own RUN_PROMPT_CMD; every value put in it is shell-quoted above
  export RUN_PROMPT_ALLOW_WEB="$WEB"
elif command -v opencode >/dev/null; then
  # --pure: no external plugins; --auto: approve tool permissions inside the sandboxed cwd (override with OPENCODE_EVAL_ARGS)
  read -r -a ARGS <<< "${OPENCODE_EVAL_ARGS:---pure --auto}"
  RUN=(opencode run ${ARGS[@]+"${ARGS[@]}"} --format json -m "$MODEL" "$(cat "$PROMPT")")
  STRUCTURED=1
  if [[ $WEB -eq 1 ]]; then export OPENCODE_ENABLE_EXA=1; else export OPENCODE_PERMISSION='{"webfetch": "deny"}'; fi
else
  echo "Error: no runner. Install opencode or set RUN_PROMPT_CMD (see --help)." >&2; exit 1
fi
START=$(python3 -c 'import time; print(int(time.time()*1000))')
# Isolation: the default runner loads skills and config from the user's home (its own and other tools').
# Run with a throwaway HOME so only the project-scoped skill in <cwd> is visible; provider keys still come
# from the environment. Set RUN_PROMPT_KEEP_HOME=1 to use the real home instead.
ISO_HOME=""
if [[ -z "${RUN_PROMPT_KEEP_HOME:-}" ]]; then ISO_HOME="$(mktemp -d)"; export HOME="$ISO_HOME" XDG_CONFIG_HOME="$ISO_HOME/.config" XDG_DATA_HOME="$ISO_HOME/.local/share"; fi
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
cleanup() { stop_runner; [[ -n "$ISO_HOME" ]] && rm -rf "$ISO_HOME"; return 0; }
trap cleanup EXIT
trap 'exit 143' TERM INT HUP
if [[ "$MODEL" == ollama/* && -z "${RUN_PROMPT_CMD:-}" ]]; then
  [[ "$MODEL" =~ ^ollama/[A-Za-z0-9._:/-]+$ ]] || { echo "Error: a local model id is ollama/<name> with letters, digits and . _ : / - only." >&2; exit 2; }
  [[ -n "$ISO_HOME" ]] || { echo "Error: a local model needs the throwaway HOME (unset RUN_PROMPT_KEEP_HOME)." >&2; exit 2; }
  mkdir -p "$XDG_CONFIG_HOME/opencode"
  python3 - "${MODEL#ollama/}" "${RUN_PROMPT_OLLAMA_URL:-http://127.0.0.1:11434/v1}" > "$XDG_CONFIG_HOME/opencode/opencode.json" <<'PY'
import json, sys
name, url = sys.argv[1], sys.argv[2]
print(json.dumps({"$schema": "https://opencode.ai/config.json", "provider": {"ollama": {
    "npm": "@ai-sdk/openai-compatible", "name": "Ollama (local)", "options": {"baseURL": url},
    "models": {name: {"name": name}}}}}))
PY
fi
# A model id "local/<name>@<12 hex>" runs a model served by the model server the eval container starts beside the run
# (evals/executor.py, "A local model"): LOCAL_MODEL_BASE_URL is the server's address on the run's internal network (a plain
# http://<host>:<port>/v1 URL), LOCAL_MODEL_CONTEXT its context in tokens. The provider entry (provider "local", the
# OpenAI-compatible SDK the runner ships) is written into the throwaway HOME; no key is needed and none is passed.
if [[ "$MODEL" == local/* && -z "${RUN_PROMPT_CMD:-}" ]]; then
  [[ "$MODEL" =~ ^local/[a-z0-9][a-z0-9._-]{0,63}@[0-9a-f]{12}$ ]] || { echo "Error: a local model id is local/<name>@<12 hex> (the name in lowercase letters, digits and . _ -)." >&2; exit 2; }
  [[ "${LOCAL_MODEL_BASE_URL:-}" =~ ^http://[A-Za-z0-9.-]+(:[0-9]+)?(/[A-Za-z0-9._/-]*)?$ ]] || { echo "Error: LOCAL_MODEL_BASE_URL must be a plain http://<host>:<port>/v1 URL (the container that runs this script sets it)." >&2; exit 2; }
  [[ "${LOCAL_MODEL_CONTEXT:-}" =~ ^[0-9]{2,8}$ ]] || { echo "Error: LOCAL_MODEL_CONTEXT must be the model's context in tokens (the container that runs this script sets it)." >&2; exit 2; }
  [[ -n "$ISO_HOME" ]] || { echo "Error: a local model needs the throwaway HOME (unset RUN_PROMPT_KEEP_HOME)." >&2; exit 2; }
  mkdir -p "$XDG_CONFIG_HOME/opencode"
  python3 - "${MODEL#local/}" "$LOCAL_MODEL_BASE_URL" "$LOCAL_MODEL_CONTEXT" > "$XDG_CONFIG_HOME/opencode/opencode.json" <<'PY'
import json, sys
name, url, context = sys.argv[1], sys.argv[2], int(sys.argv[3])
print(json.dumps({"$schema": "https://opencode.ai/config.json", "provider": {"local": {
    "npm": "@ai-sdk/openai-compatible", "name": "Local model", "options": {"baseURL": url},
    "models": {name: {"name": name, "limit": {"context": context, "output": max(1, min(8192, context // 4))}}}}}}))
PY
fi
# The eval container's key proxy holds the OpenRouter key: the run has a placeholder in OPENROUTER_API_KEY and
# the proxy's base URL in OPENROUTER_BASE_URL (evals/executor.py). The runner's OpenRouter provider takes the
# base URL from its configuration (provider.openrouter.options.baseURL, read by opencode 1.18.32 and passed to
# its OpenRouter SDK, which calls <baseURL>/chat/completions), written into the throwaway HOME like a local model's.
if [[ "$MODEL" == openrouter/* && -z "${RUN_PROMPT_CMD:-}" && -n "${OPENROUTER_BASE_URL:-}" ]]; then
  [[ "$OPENROUTER_BASE_URL" =~ ^https?://[A-Za-z0-9.-]+(:[0-9]+)?(/[A-Za-z0-9._/-]*)?$ ]] || { echo "Error: OPENROUTER_BASE_URL is not a plain http(s) URL." >&2; exit 2; }
  [[ -n "$ISO_HOME" ]] || { echo "Error: a base URL for OpenRouter needs the throwaway HOME (unset RUN_PROMPT_KEEP_HOME)." >&2; exit 2; }
  mkdir -p "$XDG_CONFIG_HOME/opencode"
  python3 - "$OPENROUTER_BASE_URL" > "$XDG_CONFIG_HOME/opencode/opencode.json" <<'PY'
import json, sys
print(json.dumps({"$schema": "https://opencode.ai/config.json", "provider": {"openrouter": {"options": {"baseURL": sys.argv[1]}}}}))
PY
fi
# stdin closed: the runner otherwise waits on an inherited pipe that never ends
set +e
( cd "$CWD" && exec "${OWN_SESSION[@]}" "${RUN[@]}" ) < /dev/null > "$OUT/stream.jsonl" 2> "$OUT/stderr.log" &
RUNNER_PID=$!
wait "$RUNNER_PID"; RC=$?
set -e
cleanup   # what the runner left running (a browser, a server) stops with it; the keychain goes with the home
END=$(python3 -c 'import time; print(int(time.time()*1000))')
python3 - "$OUT" "$((END-START))" "$RC" "$STRUCTURED" <<'PY'
import json, os, re, sys
out, dur, rc, structured = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4] == "1"
raw = open(os.path.join(out, "stream.jsonl"), encoding="utf-8", errors="ignore").read()
KINDS = ("text", "step_start", "step_finish", "tool_use", "reasoning", "error")
events = []
for line in raw.splitlines() if structured else []:
    try:
        item = json.loads(line)
    except ValueError:
        continue
    if isinstance(item, dict) and item.get("type") in KINDS:
        events.append(item)
timing = {"total_tokens": None, "duration_ms": dur, "cost_usd": None, "exit_code": rc}
if not events:  # a custom runner, or output that is not the runner's events: the text is the reply
    open(os.path.join(out, "response.md"), "w", encoding="utf-8").write(raw)
    json.dump(timing, open(os.path.join(out, "timing.json"), "w"))
    sys.exit(0 if rc == 0 else 1)
# The reply is the assistant's last message: the text of the last step that has text. Narration of the steps
# before it (a model that writes between its tool calls) is in the stream, never in the reply.
steps, step = [], []
for e in events:
    if e["type"] == "step_start":
        if step:
            steps.append(step)
        step = []
    elif e["type"] == "text":
        text = ((e.get("part") or {}).get("text") or "").strip()
        if text:
            step.append(text)
if step:
    steps.append(step)
reply = "\n\n".join(steps[-1]) + "\n" if steps else ""
open(os.path.join(out, "response.md"), "w", encoding="utf-8").write(reply)
tokens, cost, seen = 0, 0.0, False
for e in events:
    part = e.get("part") or {}
    if e["type"] == "step_finish" and isinstance(part.get("tokens"), dict):
        t, seen = part["tokens"], True
        cache = t.get("cache") if isinstance(t.get("cache"), dict) else {}
        tokens += t["total"] if isinstance(t.get("total"), int) else sum(
            int(v or 0) for v in (t.get("input"), t.get("output"), t.get("reasoning"), cache.get("read"), cache.get("write")))
        cost += float(part.get("cost") or 0)
if seen:
    timing.update(total_tokens=tokens, cost_usd=round(cost, 6))
# The skills the model touched. Loaded: the skill tool's input, or a tool that reads <skills folder>/<name>/SKILL.md
# (read's filePath, grep's path, bash's command), when that one input names the SKILL.md of a single skill: a grep or
# a command over several skills' SKILL.md loads none of them. Used: every skill whose folder a tool input that names
# files names (a command, a path, a pattern: never a write's content, an edit's text or a subagent's prompt).
NAME = r"([A-Za-z0-9][A-Za-z0-9._-]*)"   # never "." or ".."
FOLDER_RE = re.compile(r"(?<![A-Za-z0-9._-])\.agents/skills/" + NAME + r"(?=[/\s'\"`;|)&<>:]|$)")
SKILL_RE = re.compile(r"(?<![A-Za-z0-9._-])\.agents/skills/" + NAME + r"/SKILL\.md(?![A-Za-z0-9._-])")
READS = {"read": ("filePath", "file_path"), "grep": ("path",), "bash": ("command",)}
NAMING_FIELDS = ("command", "filePath", "file_path", "path", "pattern", "include", "glob")


def note(into, names):
    for n in names:
        if n not in into:
            into.append(n)


loaded, used = [], []
for e in events:
    part = e.get("part") or {}
    if e["type"] != "tool_use":
        continue
    args = (part.get("state") or {}).get("input") or {}
    names = []
    if part.get("tool") == "skill" and isinstance(args, dict) and isinstance(args.get("name"), str) and args["name"]:
        names.append(args["name"])
    for field in READS.get(part.get("tool"), ()) if isinstance(args, dict) else ():
        chunk = args.get(field)
        targets = {m.group(1) for m in SKILL_RE.finditer(chunk)} if isinstance(chunk, str) else set()
        names += sorted(targets) if len(targets) == 1 else []
    note(loaded, names)
    note(used, names)
    for field in NAMING_FIELDS if isinstance(args, dict) else ():
        chunk = args.get(field)
        if isinstance(chunk, str):
            note(used, [m.group(1) for m in FOLDER_RE.finditer(chunk)])
timing["skills_loaded"] = loaded
timing["skills_used"] = used
errors = [e.get("error") for e in events if e["type"] == "error"]
if errors:  # an error the runner reported as an event: beside its own diagnostics, where the harness looks
    with open(os.path.join(out, "stderr.log"), "a", encoding="utf-8") as f:
        for err in errors:
            f.write("error: " + json.dumps(err) + "\n")
json.dump(timing, open(os.path.join(out, "timing.json"), "w"))
sys.exit(0 if rc == 0 else 1)
PY
