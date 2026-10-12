# agents-dir adapter

Installs the selected pack of skills into `~/.agents/skills/`, the directory that Codex, Cursor, Cline, OpenCode, OpenClaw and most tools following the Agent Skills standard scan. Nothing is generated; each skill folder is symlinked (or copied with `--copy`).

```bash
bash adapters/agents-dir/install.sh                # pack "default", user-level
bash adapters/agents-dir/install.sh --pack all     # optional areas too
bash adapters/agents-dir/install.sh --project .    # project-level: ./.agents/skills
```

## Limitations

- Agents (`agents/`) are not installed by this adapter: agent formats differ per tool. Add a dedicated adapter when a tool's subagent format is needed.
- The shared references are installed beside the skills, in `<skills folder>/../shared/references` (a link, or a copy with `--copy`), so a skill's `../../shared/references/<file>` resolves by the installed path. The `shared` folder holds the installer's marker file (`.installed-by-openhora`; a copy or a `shared` folder that holds the marker the installer wrote before the rename, `.installed-by-ai-workbench`, still counts as its own and is replaced with the new one; removed with the next change of reference model, T23); a `shared` folder the installer did not make is left alone and reported, and the run exits 1.
- One pack is installed at a time: installing a pack removes what an earlier pack installed and this one does not select (a dangling link to a renamed skill included), and `--uninstall` removes everything the installer made, whatever pack installed it.

## Evals

`eval_run.py` creates the case folder (`--cwd`) in a temporary folder outside the repository and moves it into `evals-workspace/` afterwards, so a model that walks up from it finds no workbench; the adapter only needs to locate itself by its own path, which it does. `run-prompt.sh` implements the eval contract with OpenCode (`opencode run --format json`) by default, or any CLI through `RUN_PROMPT_CMD` (`{prompt_file}`, `{model}`, `{cwd}` placeholders, filled with shell-quoted values; such a command's text is the reply and its tokens are unknown). It installs nothing: the eval runner has copied the skill under test (in a run with the skill only) and a case's dependency skills into `.agents/skills/` of the case folder before it starts, through `scripts/stage_skills.py`, never linked, so a run that approves every tool cannot edit the workbench. The runner, not this script, refuses a case folder that carries a name of `settings` in `eval.json`: `.agents/`, `.opencode/`, `opencode.json[c]`, and what the default runner also reads at project level, another tool's skills folder and instruction file and its own older instruction file. A run leaves `response.md`, the assistant's last message, which is the reply the grader is given; `stream.jsonl`, the runner's event stream, never shown to the grader; and `timing.json`, with the tokens and the cost the step events report and `skills_loaded`, which the runner records as whether the skill under test was invoked. Without `--allow-web` the page-fetch tool is denied, so both tiers have the same tools on a case without the web. `run-prompt.sh` and `eval.json` are in the measurement fingerprint, and `adapter.json` is not: a change to either of the two is committed as one of the three kinds of measurement change (`AGENTS.md`, "Writing standard"). It runs only inside the eval container that `evals/eval_run.py` starts (the image sets `WB_EVAL_CONTAINER=1`; the script refuses to start without it), since the default runner approves every tool: the container is the boundary. The runner's provider key is named in `evals/eval-gate.json` (`floor_pass_env`) or with `eval_run.py --floor-pass-env`. The adapter replaces `HOME` (and the XDG configuration and data folders) with a temporary folder that it removes when the run ends, so the floor model's commands see an empty home; the strong model's adapter does not, and its commands see the container's own home (`/home/eval`). The two homes differ and both are inside the container: neither is the home of the person who runs the evals, and a case must not depend on what a home holds. No connectors or MCP servers load while the throwaway home is used (the default; `RUN_PROMPT_KEEP_HOME=1` keeps the container's home and loses that guarantee). The default runner also loads skills from the user-level skill folders of other tools: in the container the throwaway home holds none, and the runner checks that a run without the skill names no path that holds it.

The floor model's results are information: no rule reads them, and its runs are made with the skill only by default (the reliability model, section 2); the battery adds one baseline run per case with `--baseline-on floor`. A run made with a stand-in runner, such as this adapter's tests and the container job, is not evidence: its files go to a scratch tree inside the run folder, never into a skill's evidence folder.

## Floor model through OpenRouter

The floor model of the eval gate is `openrouter/deepseek/deepseek-v4.1-flash` since 2026-10-01 (it was `openrouter/deepseek/deepseek-v3.2`), set in `evals/eval-gate.json` with this adapter and the key variable `OPENROUTER_API_KEY`, so `eval_run.py --skill <name>` needs no model flag. It is served by one pinned provider, `provider_only` in `evals/container/keyproxy/keyproxy.json`, not by whichever provider OpenRouter picks. The floor runs recorded before 2026-09-28 used `claude-haiku-4-5-20251001` (35 runs, through the claude-code adapter) and `openrouter/deepseek/deepseek-v3.2` (6 runs, through this adapter), read from `evals-workspace/*/iteration-*/benchmark.json` on the maintainer's machine. OpenCode had no stored credentials (`opencode auth list`: 0), so the OpenRouter key came from the shell environment. Since the containment of 2026-09-27, `eval_run.py` passes only an allowlisted environment and this adapter uses a throwaway home, so the key must be named explicitly:

```bash
# OPENROUTER_API_KEY from the environment settings, or stored once in the OS secret store:
#   uv run --with keyring==25.7.0 keyring set openhora openrouter
# --pass-env reads it from there when it is not exported (contracts/secrets.md): this adapter registers
# the key in the "secrets" list of its adapter.json; the name to pass stays in evals/eval-gate.json.
python3 evals/eval_run.py --skill <name>
# the same, spelled out (what evals/eval-gate.json supplies):
python3 evals/eval_run.py --skill <name> --harness claude-code --model <strong-id> \
  --floor-harness agents-dir --floor-model openrouter/deepseek/deepseek-v4.1-flash --floor-pass-env OPENROUTER_API_KEY
```

`--floor-pass-env` names the key for the floor model's runs only; the strong model's runs and the grader never see it. The strong model and the grader run through the claude-code adapter on the user's own account (decided 2026-09-28).

Both keys this adapter registers, `OPENROUTER_API_KEY` and `DEEPSEEK_API_KEY`, are declared `"billing": "metered"` in `adapter.json`: a runtime run on the floor model with either is counted against the project's dollars per day, and the cost `timing.json` carries is kept as the run's cost (`contracts/secrets.md`, "How a credential is billed"). A floor model on the person's own machine (below) needs no key; an adapter for it declares `"login_billing": "free"`, which this one does not yet, so the runtime has no billing to count such a run by and its dispatcher does not start it (it never guesses a cap).

**Where the key lives during a run: in the key proxy, never in the run (since 2026-10-03).** Twice in phase D the floor model ran `env` inside the container and printed its own key into its transcript; the runner redacted it from everything stored, but the value had reached the model's context. Now the eval executor starts the key proxy (`evals/container/keyproxy/`), a container of its own on the eval network beside the egress proxy, with the key in its environment, and a floor run container gets `OPENROUTER_API_KEY=held-by-the-eval-key-proxy` (a placeholder) and `OPENROUTER_BASE_URL=http://wb-eval-keys-<definition hash>:8890/api/v1`. When the model id is `openrouter/<vendor>/<model>` and `OPENROUTER_BASE_URL` is set, `run-prompt.sh` writes `provider.openrouter.options.baseURL` into the throwaway home's `opencode.json`; OpenCode 1.18.32 passes it to its OpenRouter SDK, which then calls `<baseURL>/chat/completions` with the placeholder as its bearer token (both read in the binary the image ships). The key proxy drops that header, adds the real one, pins the provider of each chat completion to the one the route names (`deepinfra`, chosen because the account's data policy excludes DeepSeek's own endpoint), with fallbacks off, so that every floor run is served by one provider, and forwards the call over HTTPS, through the egress proxy, to `openrouter.ai` and its `/api/v1/` path only; it streams the answer back as it arrives and logs no header. A model can still spend the key through the proxy, so the credit limit on the key stays the cap; it can no longer read it. A custom runner (`RUN_PROMPT_CMD`) gets the same two variables and must use the base URL itself. `DEEPSEEK_API_KEY` (a floor model id `deepseek/<model>`) is not held by the proxy and still travels into the run.

Requires `opencode` on `PATH`.

Learned in a cloud session on 2026-09-28 (`opencode-ai@1.18.32`):
- Behind an outbound proxy, also name it: `--pass-env HTTPS_PROXY --pass-env NO_PROXY`, since the allowlisted environment drops it.
- Decided by the user on 2026-09-28: the OpenRouter key is for the floor model only. Claude models (the strong model and the grader) run through the claude-code adapter with the maintainer's own login (`--harness claude-code --model <claude-id> --floor-harness agents-dir --floor-model openrouter/deepseek/deepseek-v4.1-flash`); in a cloud session the CLI is already signed in, and `claude -p` works with only `PATH` and `HOME` from the allowlisted environment.
- The runner's web search (`--allow-web`) goes through a search service that limits concurrent use: with many runs searching at once it answers 429 and the model waits until the run times out (seen 2026-10-01 on a skill whose cases research the web). Measure such a skill alone, with `--jobs 2`.
- Three `eval_run.py` in parallel made `opencode run` fail within seconds with `UnknownError`, and those runs and their gradings were lost. The cause, found later, was a provider key that did not reach the runner, not the parallelism: runs share nothing, and several skills are evaluated at the same time within the provider's rate limits (`eval_run.py --help`, `--jobs`).

## Stopping a run

`run-prompt.sh` starts the runner in a session of its own, so the runner and everything it starts (model sessions, browsers, servers) form one process group. The group is ended, with TERM and then KILL after two seconds, when the runner returns and when the script itself gets TERM, INT or HUP (it then exits with 143). `eval_run.py` does the same one level up for every adapter call and setup command, on a timeout, on a signal and on any way out, so stopping an evaluation leaves no model session working. Before this, killing `eval_run.py` or passing a timeout left the sessions alive for many minutes. A process that moves itself into yet another session escapes this.

## Floor model on your own machine (Ollama)

Not wired to the eval container yet: evals now run in a container whose network reaches only the hosted providers, so a model served on the person's machine is not reachable from a run until the executor gains a route to it (backlog N14, split from T12, which is archived). What follows describes the adapter's side, which is unchanged.

A model id `ollama/<name>` runs a model served by Ollama on this machine (`http://127.0.0.1:11434`, or `RUN_PROMPT_OLLAMA_URL`). The adapter writes the provider entry into the run's throwaway home; nothing is added to the case folder and no key is needed.

Ollama's default context is too small for the runner's own prompt plus a skill, and the OpenAI-compatible endpoint the runner uses cannot set it per request. Create a variant with a larger context once, and use that name:

```bash
ollama pull <model>:<tag>
printf 'FROM <model>:<tag>\nPARAMETER num_ctx 32768\n' > Modelfile
ollama create <model>-32k -f Modelfile
```

Then run the floor tier one run at a time (a local model serves one request at a time; more jobs only queue and hit the timeout):

```bash
python3 evals/eval_run.py --skill <name> --harness <strong adapter> --model <strong-id> \
    --floor-model ollama/<model>-32k --floor-harness agents-dir --jobs 1 --timeout 1800
```

A local model is a measured goal, not the gate: a test on it is made with another model than the gate file's, so it writes its files into the scratch tree of its run folder and no evidence.

Memory: the model's file size plus the context must fit in the machine's memory with room to spare; a variant that swaps is slower than the timeout allows.
