# Claude Code adapter

Builds a Claude Code plugin from the core for one pack and installs it. The adapter tracks no skill content and no symlinks: `build/<pack>/` is generated and ignored by git.

## Install

```bash
bash adapters/claude-code/install.sh                    # pack "default": every area except optional ones
bash adapters/claude-code/install.sh --pack all         # optional areas too
bash adapters/claude-code/install.sh --listing-budget write --project <dir>  # and the skill-listing budget (below)
claude --plugin-dir adapters/claude-code/build/default  # one session only, after a build
```

Skills are invoked as `/openhora:<skill-name>` and trigger automatically from their descriptions.

The plugin was called `ai-workbench` until 2026-10-09. An install run removes the old link `~/.claude/skills/ai-workbench` when it points into this checkout's `build/` folder, and says so, so that the person is not left with two plugins; a link of that name that points elsewhere is left alone, and `--uninstall` removes either link. This compatibility stage is removed with the next change of reference model (backlog T23).

## The skill-listing budget

Claude Code lists the installed skills to the model within a character budget, its bundled skills first, and lists a skill past the budget by name only. Measured on 2026-10-03 with the default budget, 28 of the default pack's 48 descriptions reached the model (`docs/architecture/phase-d-proof-2026-10-03.md`). A skill listed by name only is one the model cannot tell when to use. By decision 9 of the plan the installer writes the budget when the person agrees, and no description is shortened for it.

- **The setting.** `SLASH_COMMAND_TOOL_CHAR_BUDGET`, a variable of the CLI's environment. Its only source in this repository is this adapter's eval runner, which raises it (see "Evals" below; checked 2026-10-01, CLI 2.1.283). A settings file sets a variable for every session through its `env` object; that an installed project gets every description this way is what the re-measurement below checks.
- **What the installer computes.** Each skill of the pack counted as the line `- openhora:<name>: <description>` (the plugin's name prefixes the skill's), plus a margin of a quarter of that, at least 10,000 characters, rounded up to the next 1,000. The margin is for what the CLI lists before the pack: its bundled skills and any other skill or plugin of the person's. No source in the repository gives their size, so the margin is an assumption, proportionate to the pack so that it grows with it and is never a fixed huge number. `python3 adapters/claude-code/listing_budget.py compute --pack <name>` prints it.
- **The budgets today** (2026-10-03): `default` 50,000 (48 skills, 39,301 characters listed); `all` the same, since no optional skill exists yet; `assistant` none, since it selects no skill. The eval runner's 200,000 stays as it is: a run installs one skill and needs only that it is never cut.
- **What the installer does with it.** By default (`--listing-budget print`) it prints the budget, the line to add and the file it goes in, on stderr and under `listing_budget` in its JSON line, and writes nothing. With `--listing-budget write --project <dir>` it merges the value into `<dir>/.claude/settings.json`; `--settings-scope local` writes `<dir>/.claude/settings.local.json` instead, and `--settings-scope user` writes `~/.claude/settings.json`, which is never written unless that flag names it. `--listing-budget skip` leaves the budget out.
- **How it writes.** It keeps every other key, refuses a file that is not a JSON object (or whose `env` is not one) and changes nothing then, the plugin included; it keeps a dated backup (`settings.json.openhora-<time>.bak`; a backup made before the rename keeps its old name) of a file it changes for the first time; it never lowers a larger value the person set; the value is written as a string, as the `env` object holds them. Each write is recorded in `installed/listing-budget.json` in this adapter, git-ignored. A later install with another pack replaces the value it wrote.
- **Uninstall.** `install.sh --uninstall` puts back what each recorded write replaced (the earlier value, or nothing), only while the value there is still the one written; a value changed since is reported and left alone. A file or a `.claude` folder the write created and that is empty again is removed.

To apply it to a project:

```bash
bash adapters/claude-code/install.sh --pack default --listing-budget write --project /path/to/project
```

To check what reaches the model afterwards (one model call, the maintainer's to run, with the CLI's credential in the environment as in the phase D measurement): the measurement of `docs/architecture/phase-d-proof-2026-10-03.md` again, with the budget written into a scratch project and the call made from it. Run from the checkout; it removes its scratch folders and keeps the reply in `listing-reply.json` of a fresh temporary folder, whose path it prints.

```bash
WB="$PWD" S="$(mktemp -d)" OUT="$(mktemp -d)" && mkdir -p "$S/home" "$S/proj" \
  && HOME="$S/home" bash "$WB/adapters/claude-code/install.sh" --pack default --listing-budget write --project "$S/proj" \
  && (cd "$S/proj" && HOME="$S/home" claude --plugin-dir "$WB/adapters/claude-code/build/default" \
       -p "List every skill you were given: its name and its description, word for word." --output-format json) \
     > "$OUT/listing-reply.json"; \
  HOME="$S/home" bash "$WB/adapters/claude-code/install.sh" --uninstall; rm -rf "$S"; echo "$OUT/listing-reply.json"
```

## What lives here and nowhere else

- `plugin.json`: the manifest source, copied into every build. It names no `agents` path: the build's `agents/` folder is the default place.
- `overrides/<agent>.yaml`: model, tools, permissionMode per agent, merged into the generated agents.
- `listing_budget.py`: the skill-listing budget of a pack, printed or written into a settings file (above); `installed/`, git-ignored, holds its record of what it wrote.
- `connectors.json` (when needed): which requirement classes this harness satisfies through connectors, read by `scripts/doctor.py --harness claude-code`.
- `hooks/` (when needed): validation hooks, referenced from `plugin.json`.

## Limitations

- Symlinks are created at build time, so the filesystem running the build must support them (macOS, Linux; Windows needs developer mode). Nothing symlinked is committed.
- The linked folder under `~/.claude/skills/` is picked up as the plugin `openhora@skills-dir`: confirmed on 2026-10-02 with CLI 2.1.283 in a scratch home, under the old name `ai-workbench` (the folder's name decides it; not measured again under the new name), without a model call (`claude plugin list --json` reads `enabled: true`; `claude plugin details ai-workbench@skills-dir` lists the 48 skills and the 4 agents). The manifest must not carry an `agents` key: with `"agents": "./agents"` the same CLI refused the folder ("invalid manifest file ... agents: Invalid input") and loaded nothing; the `agents/` folder of the build is found by its default place. When a later version does not pick the link up, the fallback is `claude --plugin-dir adapters/claude-code/build/<pack>`, which `install.sh` prints with the build's path.
- The shared references are in the build, at `build/<pack>/shared/references`, so a skill's `../../shared/references/<file>` resolves by the installed path.
- One pack is installed at a time: an install removes the builds of other packs, and `--uninstall` removes the link and every build.

## Evals

`run-prompt.sh` implements the eval contract (`AGENTS.md`, "Adding an adapter"): it runs one prompt with `claude -p` in the case folder, with settings limited to the project scope (`--setting-sources project,local`) and no MCP servers or claude.ai connectors (`--strict-mcp-config`, `ENABLE_CLAUDEAI_MCP_SERVERS=false`; https://code.claude.com/docs/en/mcp, read 2026-09-27). It installs nothing. Before it starts, the eval runner has copied the skill under test (in a run with the skill only) and a case's dependency skills into `.claude/skills/` of the case folder, through `scripts/stage_skills.py`, without their `evals/` and `scripts/tests/`, with the shared references the skill cites beside them; and the runner, not this script, has refused a case folder that carries a name of `settings` in `eval.json` (`.claude`, `.mcp.json`, `CLAUDE.md`, `CLAUDE.local.md`), from a fixture or from a setup command.

What a run leaves: `response.md`, the assistant's last message, which is the reply the grader is given; `stream.jsonl`, the CLI's whole event stream, kept beside it and never shown to the grader; `timing.json`, with the tokens, the cost and `skills_loaded`, the skills the stream shows the model loading, which the runner records as whether the skill under test was invoked (never scored). A grading call runs with `--no-tools`: the grader holds this tier's credential and reads text a model under test wrote, so it gets no tool at all. `eval.json` holds what an exhausted account answers (`account_limit`: the runner then pauses every run on the account until a probe succeeds or the operator gives a time) and the refusal markers (`refusal_markers`). `run-prompt.sh` and `eval.json` are in the measurement fingerprint; `adapter.json` is not: a change to either is committed as one of the three kinds of measurement change (`AGENTS.md`, "Writing standard"; `python3 evals/eval_status.py measurement`).

It runs only inside the eval container that `evals/eval_run.py` starts (`evals/executor.py`): the image sets `WB_EVAL_CONTAINER=1` and the script refuses to start without it. The container is the boundary, so every tool is allowed (`--dangerously-skip-permissions`); the web tools are disallowed unless the case sets `allow_web`. The CLI authenticates with `CLAUDE_CODE_OAUTH_TOKEN`, a long-lived token kept in the secret store (`contracts/secrets.md`) and named in `evals/eval-gate.json` (`strong_pass_env`). The value never enters the run container: in an eval run `CLAUDE_CODE_OAUTH_TOKEN` holds a placeholder and `ANTHROPIC_BASE_URL` names the strong model's key proxy (`evals/container/keyproxy/keyproxy-strong.json`), which adds the real value to each call. A run of a case on the open network (`web_cases` of the gate file) uses the same credential through the same proxy. `CLAUDE_CODE_WEB_API_KEY`, an API key with a low spend limit, is passed to those runs only when the gate file lists it in `strong_web_pass_env`, and today it does not.

The CLI lists the available skills to the model within a character budget, its bundled skills first. With the default budget a project skill whose description is a few hundred characters long was listed by name only: asked to quote its list, the model in the container showed `- core-clarify` with no text, while the bundled skills kept theirs. Without the description the model cannot tell when the skill applies, and in one case it answered on its own in 5 of 6 runs. `run-prompt.sh` therefore sets `SLASH_COMMAND_TOOL_CHAR_BUDGET=200000`; with it the description is listed in full and the same case used the skill in 5 of 5 runs (checked 2026-10-01, CLI 2.1.283). Whether the same happened on the host before the container is not known: those transcripts no longer exist.

How it got here, in one day (2026-10-01, `docs/decisions.md`): rules that matched the text of a command denied harmless forms and made the strong model score below the floor model (809 denied commands in the runs kept on the maintainer's machine); the CLI's own sandbox fixed that on the host; then every eval moved into a container, which made both the rules and the sandbox settings unnecessary and removed them.

The home a run sees is the container's own (`/home/eval`): this adapter does not replace `HOME`, while the floor model's adapter (`adapters/agents-dir/`) gives each run an empty temporary home. The two tiers' commands therefore see different homes, both inside the container and neither the home of the person who runs the evals; a case must not depend on what a home holds.

The token the strong model's runs use is registered by this adapter, in the `secrets` list of `adapter.json` (the core's registry in `providers/secrets/resolver.py` names no adapter); the name passed into the runs has one home, `strong_pass_env` of `evals/eval-gate.json`, and `eval_run.py` fills it from the OS secret store when it is not exported. `python3 scripts/doctor.py` shows whether it is found, never its value.

The manifest also says how each credential is billed (`contracts/secrets.md`, "How a credential is billed"), which is what decides the daily cap a runtime run counts against: `CLAUDE_CODE_OAUTH_TOKEN` is `subscription` (the run counts as a run, and its cost is not recorded as billed), `CLAUDE_CODE_WEB_API_KEY` is `metered`. The CLI's own login, used when a run passes no variable, is declared once as `"login_billing": "subscription"`. An API key as the reference model's credential (`ANTHROPIC_API_KEY`, registered by the `api` adapter as `metered`) is, today, an edit of `strong_pass_env` in the gate file that nothing else supports: the caps then count those runs in dollars and `total_cost_usd` of the CLI's result, which `timing.json` carries as `cost_usd`, is kept as the run's cost, but the key enters the container with `-e` and is not held by a key proxy, so limit L6 (no credential inside a run) does not hold for it. A route for it, with the key held by the proxy, is a later package (A-40).

Lab evidence on the reference model, the strong model of the gate file, comes from tests the maintainer runs on the maintainer's account (`evals/README.md`). A run made with a stand-in runner or grader, such as this adapter's tests and the container job, is not evidence: the runner writes its files into a scratch tree inside the run folder, never into a skill's evidence folder.

## Recording a use in a project

Field evidence, a real use of a skill in a project, is recorded with `scripts/evidence.py record --start` when the use begins (the reliability model, section 7). This adapter does not install a hook for it yet (plan item F9: the installer will write a hook with the checkout's absolute path and the model id the harness gives). Until then the block of the project's instruction file, written by `core-project-init`, asks the model to run the command; the model id is then `unknown`, since it is never taken from a model's own account of what it is.

## Runtime runs

`run-agent.sh` implements the runtime contract (`contracts/runtime.md`): one agent on one task, for `scripts/runtime.py`. The run happens in `<out>/cwd`, with the agent's skills copied (never linked) into `.claude/skills/<name>`, without their `evals/` and `scripts/tests/`. The model gets the reading tools only (`--tools Read,Glob,Grep`), so it reaches a skill by reading its file: the system prompt, after the agent's body, lists each skill's `SKILL.md` path. `--project` is added as a folder the tools may use (`--add-dir`); this adapter does not confine the reading tools to it and the run folder, and whether the CLI lets them read elsewhere is the CLI's rule, which nothing here checks (backlog N15). The CLI runs in a session of its own: at `--timeout-seconds`, and whenever it returns, its whole process group is ended (TERM, then KILL five seconds later), so nothing it started outlives the run; a timeout is `exit_code` 124 in `timing.json`. `tests/test_claude_code_run_agent.py` checks all of this with a stand-in `claude` on the `PATH` (no model is called).

## Stopping a run

`run-prompt.sh` starts the runner in a session of its own, so the runner and everything it starts (model sessions, browsers, servers) form one process group. The group is ended, with TERM and then KILL after two seconds, when the runner returns and when the script itself gets TERM, INT or HUP (it then exits with 143). `eval_run.py` does the same one level up for every adapter call and setup command, on a timeout, on a signal and on any way out, so stopping an evaluation leaves no model session working. Before this, killing `eval_run.py` or passing a timeout left the sessions alive for many minutes. A process that moves itself into yet another session escapes this.
