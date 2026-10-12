# API adapter (tool-free)

Runs one agent on one task for the agent runtime (`contracts/runtime.md`) with **one model API call and no tools**. It is the tool-free way to call the model, for a runtime that runs on a small always-on server: the agent, its skills and the project files the task names go into the prompt; the answer comes back as text. The model cannot read, write, run or fetch anything, because no tool is ever sent, so "the model has no tool that acts" holds by construction rather than by configuration.

It implements only the runtime's entry point, `run-agent.sh`. It installs nothing and has no eval runner (`run-prompt.sh`): skills are evaluated through the other adapters.

## When to use it, and when the claude-code adapter

| | `api` (this adapter) | `claude-code` |
|---|---|---|
| Needs | Python 3.10+, a network connection, an API key | the Claude Code CLI, signed in (4 GB+ RAM on a server) |
| How the model sees files | the adapter inlines the files the task names | the model reads the project with read-only tools |
| Terms | API terms, paid per token | the CLI's sign-in; whether that sign-in's terms cover an unattended run on a server is the operator's question to settle with the provider before using it there |
| Cost per run | one call: input + output tokens | several tool turns, each resending context |
| Best for | a small server (VPS), a scheduled runtime | a local machine, while files the task cannot name are needed |

Choose it in the project's `docs/workbench/runtime.json`: `"harness": "api"` and a model id with the endpoint prefix, for example `"model": "anthropic/claude-sonnet-5-5"` or `"model": "openrouter/deepseek/deepseek-v3.2"`. `scripts/runtime.py` then calls `bash adapters/api/run-agent.sh` with the same flags it gives any adapter.

## Usage

```text
run-agent.sh --agent-file <agents/name.md> --task-file <f> --project <dir> --model <id> --out <dir>
             [--skill-dir <dir>]... [--max-cost-usd <amount>] [--timeout-seconds <n>]
```

Writes `<out>/response.md`, `<out>/timing.json` (`total_tokens`, `duration_ms`, `cost_usd`, `exit_code`), `<out>/raw.json` (the provider's response body), `<out>/request.json` (the request body, never the headers) and `<out>/stderr.log`. `<out>` is created with mode 700 and every file with mode 600; a folder that already holds a run is refused. Exit 0 when the model answered, 1 otherwise, 2 on usage errors. `timing.json`'s `exit_code` says why: 0 answered, 1 the call failed, 3 refused by the cost estimate, 4 no API key, 5 prompt over the limit, 124 timeout.

## The prompt it builds

- **System:** the agent's body (its frontmatter removed); each `--skill-dir`'s `SKILL.md`, whole, between `BEGIN SKILL` and `END SKILL` lines (scripts, references, assets and evals are never sent); the reference of the platform the task names, whole, between `BEGIN PLATFORM REFERENCE` and `END PLATFORM REFERENCE` lines; then a short note: no tools in this run, the skills and the named project files are in the prompt, a file that is not inlined is unavailable and must not be guessed.
- **User:** the task file, then a "Project files" section. Every path in the task text outside its fenced blocks that resolves to a regular file inside `--project` (absolute, or relative to `--project`) is inlined once (the runtime quotes a comment or other external content in a fenced block, as JSON, so whoever wrote it cannot choose which project files reach the model), between `BEGIN DATA FILE <path> [<marker>]` and `END DATA FILE <path> [<marker>]` lines. The marker is random per run, so text inside a file cannot fake the end of its block. The section says the files are data, not instructions.
- **Refused paths**, listed in `stderr.log` with the reason: anything that resolves outside `--project` (`..`, absolute paths elsewhere, symlinks pointing out), hidden path components (`.env`, `.git/`), credential file names (`*.pem`, `*.key`, `id_rsa`...), directories, files that are not UTF-8 text, and paths that do not exist. URLs are removed from the task text before paths are looked for. A path with spaces is not recognised.
- **Limits:** a file is cut at 64 kB and marked as cut; the whole prompt stops at 400,000 characters, and a file that would pass that is skipped. Both are constants at the top of `run_agent.py`.
- **The platform reference:** a skill's step reads what is specific to a platform from `../../shared/references/platforms/<platform>.md`, and this run has no tool to read it with, so the adapter sends that one file. The platform is the task's line `Platform: <name>`, which the runtime writes; it is looked for above the task's first fenced block only, so quoted text (a comment, an e-mail) cannot name one. The file is looked for beside each `--skill-dir` first, then in this checkout. A task that names no platform, or a platform without a reference, gets none, and `stderr.log` says which.
- **Not reached:** a folder the task names (`docs/marketing/content/`) is not expanded, and a skill's own `references/` are not sent. A task that needs a file must name it.

The comment or e-mail inside the task is still external content: the task marks it, the agent's rules say it is data, and the runtime's gate checks the proposal in code whatever the model says.

## Endpoints

| Model id | Endpoint | Secret |
|----------|----------|--------|
| `anthropic/<model>` (`anthropic/claude-sonnet-5-5`) | `POST https://api.anthropic.com/v1/messages`, headers `x-api-key`, `anthropic-version: 2023-06-01` | `ANTHROPIC_API_KEY` |
| `openrouter/<vendor>/<model>` (`openrouter/deepseek/deepseek-v3.2`) | `POST https://openrouter.ai/api/v1/chat/completions`, header `Authorization: Bearer <key>` | `OPENROUTER_API_KEY` |

Request and response shapes were checked on 2026-09-30 against https://platform.claude.com/docs/en/api/messages, https://platform.claude.com/docs/en/api/versioning, https://openrouter.ai/docs/api-reference/chat-completion, https://openrouter.ai/docs/use-cases/usage-accounting and https://openrouter.ai/docs/api-reference/authentication. `max_tokens` is 4096. Redirects are never followed, so the key never goes to another host. Every request has a deadline: `--timeout-seconds` (default 600) bounds the whole run.

## Secrets

Keys are read only through `providers/secrets/resolver.py` (`contracts/secrets.md`). The core's registry names no adapter, so this adapter registers its two keys itself, in the `secrets` list of `adapter.json`, and `run_agent.py` hands that file to the resolver (`python3 providers/secrets/resolver.py --registry adapters/api/adapter.json --list` shows them). Lookup: the environment variable first, then the OS secret store under service `openhora` (or, during the compatibility stage of the rename, `ai-workbench`; see `contracts/secrets.md`), usernames `anthropic` and `openrouter`. Both keys are declared `"billing": "metered"` in the manifest: a run on either is paid by use, so the runtime counts it against the project's dollars per day and keeps the cost the adapter reports (`contracts/secrets.md`, "How a credential is billed"). `run-agent.sh` runs `run_agent.py` with `uv run --script` when `uv` is on the PATH, which brings the resolver's `keyring` package, so a key kept in the store works for a scheduled tick; without `uv`, `python3` runs it and the key must be in the environment (on a server: the service's environment file, readable only by the tick's user). A key is never printed, logged or written; if a provider echoes it in an error, it is replaced by `<redacted>` before anything is saved. Give the key a spend limit.

`ANTHROPIC_API_BASE` and `OPENROUTER_API_BASE` replace the endpoint base for offline tests only, and are refused unless they point to `http://127.0.0.1`.

## Costs

- **Before the call:** input tokens are estimated as characters / 3.5. It is an estimate, not a tokenizer count; newer Claude tokenizers produce about 30% more tokens for the same text (https://platform.claude.com/docs/en/about-claude/pricing). When the estimate times the model's input price already exceeds `--max-cost-usd`, nothing is sent (`exit_code` 3).
- **After the call:** `cost_usd` is OpenRouter's `usage.cost` when present; for the Anthropic endpoint, the reported tokens times `prices.json` (cache tokens at their own prices, though this adapter never asks for caching).
- **Unknown price:** a model missing from `prices.json` runs with a warning in `stderr.log`, no pre-call check, and `cost_usd` null for the Anthropic endpoint. The first runtime's `today_spend` (`scripts/runtime.py`) counts that run as `max_cost_usd_per_run`, so add the price before using a new model: each entry has its source URL and access date.

`prices.json`, accessed 2026-09-30: Claude Sonnet 5.5 $2 / $10 and Claude Haiku 4.5 $1 / $5 per million input / output tokens (https://platform.claude.com/docs/en/about-claude/pricing); DeepSeek V3.2 on OpenRouter $0.28 / $0.42 (https://openrouter.ai/api/v1/models).

## Tests

```bash
uv run --with pytest==9.1.1 pytest -q adapters/api/tests
```

A fake server on 127.0.0.1 stands in for both endpoints; no real API or key is used. The tests check that no tools are sent, what the prompt carries, which paths are refused, the cost refusal, the cost from usage, a non-200 status, redirects, the timeout, and that the key appears in no output.

## Not yet verified with a real key

The first run against each endpoint should confirm: a 200 answer with the shapes above, `usage` and `usage.cost` as documented, the estimate against the real `input_tokens`, and that `stderr.log`, `raw.json` and `request.json` hold no key.
