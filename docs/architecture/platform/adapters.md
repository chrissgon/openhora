# Layer 5: adapters

Part of [the platform map](README.md). Every layer page has the same eight sections, in this order.

## Purpose

An adapter holds everything that is specific to one AI tool (a harness): how a pack of skills is installed where that tool discovers it, how one prompt is run through it inside the eval container, how one agent is run on one task, and the settings, overrides and credentials that only that tool needs. The core reads none of it and names no tool; adding a harness adds a folder and edits nothing in the core ([AGENTS.md](../../../AGENTS.md), principles 1 and 2).

The adapters are `claude-code` (the reference model's adapter: a plugin build, the eval runner, the runtime runner), `agents-dir` (the floor model's adapter: a skills folder many tools read, the eval runner) and `api` (a tool-free runtime runner for the first runtime). Each folder's `README.md` is the source; this page maps them and does not repeat them.

## Artifacts it owns

Where: **repo** is this repository, **home** is the person's machine outside every repository, **project** is a target project, **run** is a lab or runtime run folder.

| Path | Where | Format | Written by | Read by | Lifecycle | Versioned | Generated |
|---|---|---|---|---|---|---|---|
| `adapters/<harness>/adapter.json` | repo | `harness`, `covers`, `consumes`, `strategy`, `install`, `generated`, `eval_runner`, `runtime_runner`, `secrets` (the credentials only this adapter's runs need, with the registry's fields) | maintainers | `evals/execution.py` (the `secrets` list, for the credentials a run passes in), `runtime/lab.py` (`credential_usernames`), `providers/secrets/resolver.py` when a caller hands it the file, `scripts/doctor.py` | changed by pull request; outside the measurement fingerprint | yes | no |
| `adapters/<harness>/eval.json` | repo | exactly four keys: `skills_dir`, `settings`, `account_limit`, `refusal_markers` | maintainers | `evals/execution.py` (`adapter_eval`, which `evals/eval_run.py` and `runtime/lab.py` call; `evals/run_attempts.py` reads no adapter file and is handed what it needs) | a change is a measurement change | yes | no |
| `adapters/<harness>/run-prompt.sh` | repo | bash; the eval contract | maintainers | the eval container (`evals/executor.py` mounts this script alone, read-only, as `/wb/run-prompt.sh`); `evals/eval_run.py` and `runtime/lab.py` build its path | a change is a measurement change | yes | no |
| `adapters/<harness>/run-agent.sh` (and `api/run_agent.py`, `api/prices.json`) | repo | bash, Python; the runtime contract | maintainers | the first runtime, `scripts/runtime.py`, for the adapter `runtime.json` names (its rollback until WP-7.5); the task runtime does not read it | changed by pull request | yes | no |
| `adapters/<harness>/install.sh`, `build.py`, `listing_budget.py`, `plugin.json` | repo | bash, Python | maintainers | the person who installs | changed by pull request | yes | no |
| `adapters/claude-code/overrides/<agent>.yaml` | repo | frontmatter keys merged into a generated agent (`tools`, `permissionMode`) | maintainers | `build.py` | one file per core agent that needs one | yes | no |
| `adapters/claude-code/connectors.json` | repo | `{"classes": {class: what serves it}}` | maintainers | `scripts/doctor.py --harness claude-code` | changed by pull request | yes | no |
| `adapters/<harness>/tests/` | repo | pytest with a stand-in runner or server; no model call | maintainers | CI, the hook | grows | yes | no |
| `adapters/claude-code/build/<pack>/` | repo folder, ignored | a plugin: `.claude-plugin/plugin.json`, a link per selected skill, `shared/references`, merged agents | `build.py` | the tool, through the link the installer makes | rebuilt per install; other packs' builds pruned | no | yes |
| `adapters/claude-code/installed/listing-budget.json` | repo folder, ignored | the record of each settings value the installer wrote | `listing_budget.py` | `install.sh --uninstall` | until uninstall | no | yes |
| The installed skills (`~/.agents/skills/<name>` or `<project>/.agents/skills/<name>`; the link to the plugin build) | home or project | a link per skill, or a copy with `--copy` | `install.sh` | the tool | one pack at a time | no | yes |
| `.installed-by-openhora` (before 2026-10-09 `.installed-by-ai-workbench`, which the installer and the content hash still accept until T23) | inside each copied skill folder and the installed `shared` folder | an empty marker file | `agents-dir/install.sh --copy`; `scripts/stage_skills.py --marker` | the installer (what it may replace or remove); `evals/eval_status.py` leaves both names out of the content hash | removed with the copy | no | yes |
| The staged skills folder (`<case>/<skills_dir>/<name>`, `<case>/<skills_dir>/../shared/references/`) | run | copies made by `scripts/stage_skills.py`: no `evals/`, no `scripts/tests/`, the cited references only | the eval runner, before the container starts | the harness inside the run | one run; excluded from the case's git | no | yes |
| `<out>/response.md`, `timing.json` and `stderr.log` (every script); `stream.jsonl` (the two `run-prompt.sh` only); `raw.json` (the two `claude-code` scripts and `api`); `request.json` (`api` only) | run | the last message; the whole stream, never shown to the grader; `timing.json` holds `total_tokens`, `duration_ms`, `cost_usd` (null when unknown) and `exit_code`, and `skills_loaded` in the two `run-prompt.sh` only | `run-prompt.sh`, `run-agent.sh` | the runner, the facade, the first runtime | kept in the run folder | no | yes |
| The hook that records a use | project or the tool's settings | (planned) a hook that runs `scripts/evidence.py record --start` with the checkout's absolute path and the model id the harness gives | (planned) an installer | the harness | none exists yet | no | yes |

## Abstractions

**Harness.** One AI tool, named by its adapter's folder (`claude-code`, `agents-dir`, `api`). The gate file names two of them, by folder name only: `strong_harness` and `floor_harness`.

**Eval adapter.** An adapter that has a `run-prompt.sh`, and therefore an `eval.json`. `claude-code` and `agents-dir` are eval adapters; `api` is not (it has only `run-agent.sh`). Only an eval adapter's two files enter the measurement fingerprint.

**The eval contract**, `run-prompt.sh --prompt-file <f> --cwd <dir> --model <id> --out <dir> [--allow-web] [--max-cost-usd <amount>] [--no-tools]`: runs one prompt in `<cwd>` and installs nothing (the runner has staged the skill under test and the case's dependency skills into `skills_dir`). It refuses to start outside the eval container (`WB_EVAL_CONTAINER=1`), lets the model run every command inside it, loads no connector, gives the web tools only with `--allow-web`, gives no tool at all with `--no-tools` (a grading call; only `claude-code` implements it, `agents-dir` refuses it as an unknown option with exit 2, and the grading call is made with the strong tier's adapter), stops at the spend limit or says on stderr that it cannot, ends its whole process group when it returns or is stopped, and writes `response.md`, `stream.jsonl` and `timing.json`. Exit 1 for a failed run whatever the runner's own code, 2 for usage.

**The runtime contract**, `run-agent.sh --agent-file <agents/name.md> --task-file <f> --project <dir> --model <id> --out <dir> [--skill-dir <dir>]... [--max-cost-usd <amount>] [--timeout-seconds <n>]`: one agent on one task with reading tools only (`claude-code`) or no tool at all (`api`), the skills copied, never linked, into a fresh folder, no connector and no user-level settings; it writes `response.md` and `timing.json`. Its caller is the first runtime (`scripts/runtime.py`), for which it stays the rollback until WP-7.5; `claude-code`'s takes `--timeout-seconds` from 30 to 3600 (default 600). The task runtime (`runtime/`) does not use it: it runs a skill through the lab facade and the eval adapter's `run-prompt.sh` ([runtime.md](runtime.md)), and the social handler runs its agent as a contained run (`runtime/cli.py contained-run`; `contracts/runtime.md`, "The contained run").

**The settings names.** `settings` of `eval.json` lists the files and folders that carry a harness's settings or instructions at project level (its settings folder, its instruction file, what its runner also reads). A case folder, or a runtime run copy, that holds one of the names of any eval adapter, at any depth outside `.git`, is refused before any model call: the harness would apply those rules, hooks or servers to the run. The runner refuses it, not the adapter.

**The account-limit and refusal markers.** `account_limit` names what the harness prints when its account is exhausted: the runner then pauses every run on that account until a probe succeeds or the operator gives a time, and the run that met the limit is made again without counting. `refusal_markers` names a provider's refusal on policy grounds, which is retried like a timeout, with the skill and without it alike.

**The skills-listing budget.** A harness may list installed skills to the model within a character budget and list the rest by name only, so a skill past the budget is one the model cannot tell when to use. The `claude-code` eval runner raises the budget for every run; its installer computes the budget a pack needs (the pack's listing plus a bounded margin) and prints it, or writes it into a settings file when the person asks, never lowering a larger value and putting back what it replaced on uninstall. Descriptions are never shortened for it.

**The pack installed.** One pack at a time (`packs/<name>.txt`, resolved by `scripts/select_skills.py`). An install removes what an earlier pack installed and this one does not select; `--uninstall` removes everything the installer made, and only that: a folder of the same name without the marker is the person's and is left alone.

## Dependencies

**What it reads.** The core: `skills/`, `shared/references/`, `agents/` (for a plugin build and the runtime runner), `packs/` through `scripts/select_skills.py`, the secrets resolver (with its own `adapter.json` handed over for its keys). An adapter may link or copy core folders; it never modifies them.

**Who reads it.**

| Reader | What | How |
|---|---|---|
| The lab (`evals/execution.py` reads `eval.json` and the `secrets` list; `evals/eval_run.py` builds the path of `run-prompt.sh`; `evals/executor.py` mounts it) | `eval.json`, `run-prompt.sh`, the `secrets` list of `adapter.json` | by the gate file's `strong_harness` and `floor_harness`, or `--harness` for a trial; the script mounted alone, read-only, in the container; `evals/run_attempts.py` reads no adapter file |
| The task runtime | the same, through the lab only (`runtime/lab.py`: the kit's `adapter_eval`, `harness_settings`, `settings_in`, and the `secrets` list of every `adapter.json` in `credential_usernames`) | no module of `runtime/` names an adapter |
| The first runtime (`scripts/runtime.py`) | `run-agent.sh` of the adapter its `runtime.json` names | `bash adapters/<harness>/run-agent.sh` |
| `scripts/doctor.py` | `connectors.json`, every adapter's `secrets` | `--harness <name>`; never a value |
| `scripts/stage_skills.py` | nothing of an adapter: it is given a target folder | the runner passes `skills_dir` |

**The rules.**

- The core never reads an adapter and names no harness: the validator's `harness-name` check covers the core folders, including a path inside `adapters/`; the secrets registry names no adapter.
- The measurement fingerprint holds each eval adapter's `run-prompt.sh` and `eval.json`, and not `adapter.json` (installation text and secrets): `evals/eval_status.py`, `measurement_fingerprint`.
- No file of an adapter reaches the runtime or the lab: the row `adapters/**` of `ALLOWED` in `scripts/tests/test_layer_map.py` lets it reach the core, `scripts/` and `adapters/` only (`test_every_edge_of_the_code_is_allowed_or_tolerated`).
- No module of the task runtime names an adapter or a model: both come from the gate file (`runtime/tests/test_runtime_rules.py`).

## Business rules

Each invariant with its guard. A test is in the adapter's own `tests/` folder unless its path is given.

**The core stays harness-free.**

- No core file names a harness or reads an adapter's path: `scripts/validate.py`, check `harness-name` (`HARNESS_PATTERNS`, `HARNESS_WIDE_PATTERNS`); `scripts/tests/test_validate_rules.py::test_this_repository_names_no_harness_in_its_core`.
- The core's secrets registry names no adapter secret; each adapter registers its own: `providers/secrets/tests/test_resolver.py::test_the_core_registry_names_no_adapter`; `scripts/tests/test_adapter_secrets.py::test_the_core_alone_registers_no_adapter_secret`, `test_every_adapter_secret_names_readers_that_exist_and_its_own_adapter`.
- A name passed into eval runs is registered by the adapter of its tier: `scripts/tests/test_adapter_secrets.py::test_the_names_passed_into_eval_runs_are_registered_by_the_adapter_of_their_tier`.
- `adapter.json` carries no eval block, and each `eval.json` holds exactly its four keys: `evals/tests/test_eval_block.py::test_no_adapter_json_has_an_eval_key_and_each_eval_json_holds_exactly_the_four_keys`.

**The measurement.**

- A change to `run-prompt.sh` or `eval.json` changes the fingerprint, and the validator fails until it is committed as a measurement change: `scripts/validate.py` (eval-status check, `fingerprint_problem`); `evals/tests/test_eval_status.py::test_the_validator_fails_when_the_fingerprint_differs_from_the_committed_one`, `test_the_fingerprint_follows_the_files_that_decide_what_a_run_measures`.
- Each `run-prompt.sh` runs in the image with a stand-in runner: `evals/tests/test_executor_docker.py::test_each_run_prompt_sh_runs_in_the_image_with_a_stub_runner` (the container job of CI).

**The run's boundary.**

- Outside the eval container the adapter refuses to start: `test_outside_the_eval_container_the_adapter_refuses_to_start` (both eval adapters).
- Inside it every tool is allowed and the web only when asked; a grading call gets no tool at all: `test_inside_the_eval_container_every_tool_is_allowed_and_the_web_only_when_asked`, `test_a_grading_call_gets_no_tool_at_all`, `test_a_model_run_keeps_its_tools` (`claude-code`); `test_without_the_web_the_page_fetch_tool_is_denied_and_with_it_search_is_on` (`agents-dir`).
- The spend limit: `claude-code` turns `--max-cost-usd` into its runner's budget; `agents-dir` accepts it and says on stderr that it cannot enforce it, so a credit limit on the provider key is the cap: `test_max_cost_becomes_a_budget_and_bad_values_are_refused`, `test_max_cost_is_accepted_and_said_to_be_unenforced`.
- No connectors: `claude-code` turns them off by flag and environment (`test_the_adapter_installs_nothing_and_connectors_are_off`); `agents-dir` gives each run a throwaway home that holds none (no test named after the connectors; `test_a_local_model_needs_the_throwaway_home` covers the home).
- Nothing a run starts outlives it: `test_what_the_cli_leaves_in_the_background_stops_when_it_returns`, `test_a_stopped_adapter_stops_the_cli_and_its_children` (and the `agents-dir` pair); `test_the_timeout_stops_everything_the_cli_started` (`run-agent.sh`).
- No key in the run: a floor run is pointed at the key proxy in its throwaway home and gets a placeholder: `test_an_openrouter_model_is_pointed_at_the_key_proxy_in_the_throwaway_home`; `evals/tests/test_keyproxy_docker.py::test_the_floor_adapter_sends_its_calls_through_the_key_proxy`.
- The model id given to a runner cannot add commands: `test_the_model_id_cannot_add_commands` (`agents-dir`).

**What a run sees of the skills.**

- The adapter installs nothing; the runner stages, and a staged skill is left as it is: `test_the_adapter_installs_nothing`, `test_the_options_that_made_the_adapter_copy_a_skill_are_gone`, `test_a_skill_the_runner_staged_is_left_as_it_is` (both eval adapters).
- A staged skill is a copy, never a link, without its cases and tests: `scripts/tests/test_stage_skills.py::test_a_staged_skill_is_a_copy_without_its_cases_its_tests_and_caches`, `test_a_link_inside_a_skill_is_copied_as_its_content_and_never_points_back`; `evals/tests/test_executor_docker.py::test_a_run_reads_the_staged_skill_and_never_its_cases_its_tests_or_an_uncited_reference`.
- `run-agent.sh` copies the skills with links followed (`cp -RL`) and gives the reading tools only: `test_the_skills_are_reachable_with_the_reading_tools_only`. Whether the tool lets those reading tools leave the project folder is the tool's rule, which nothing here checks.
- A case folder or a run copy that carries a harness's settings is refused before any model call: `evals/tests/test_eval_run.py::test_a_case_folder_that_carries_harness_settings_is_refused_before_any_run`, `test_settings_made_by_a_setup_command_are_refused_too`; `runtime/tests/test_lab_facade.py::test_a_copy_that_carries_a_tools_settings_is_refused_before_any_model_call`, `test_the_names_of_a_tools_settings_come_from_the_adapters_lists`.
- The `claude-code` eval runner raises the listing budget so the skill keeps its description: `test_the_skill_listing_budget_is_raised_so_the_skill_keeps_its_description`.

**Evidence and the marker.**

- Evidence is written only by the runner, from the real adapters in the container; a stand-in runner or grader writes into the run folder's scratch tree: `evals/tests/test_eval_run.py::test_a_trial_never_writes_into_the_skill`; `evals/tests/test_executor_docker.py::test_the_grading_path_with_a_stub_grader_runs_in_the_container_and_a_stub_run_leaves_no_file_under_skills`. That a person does not type a line into a pull request has no code guard: the code owners' review and the rule that the maintainer runs the reference model's tests are the protection ([evals/README.md](../../../evals/README.md), "Who runs the lab tests").
- A copied skill with its marker has the hash of its source: `scripts/tests/test_evidence.py::test_a_copied_skill_folder_with_its_marker_gives_the_hash_of_its_source`.
- The model id of a recorded use comes from a flag only, never from a model's own account: `scripts/tests/test_evidence.py::test_the_model_comes_from_the_flag_only_and_an_unlisted_one_is_unknown`.

**Installers.**

- An installer replaces and removes only what it made: `scripts/tests/test_installers.py::test_symlink_install_skips_and_keeps_a_folder_it_did_not_make`, `test_copy_install_replaces_and_removes_only_its_copies`, `test_plugin_install_refuses_a_target_it_did_not_make_and_builds_nothing`.
- One pack at a time, and uninstall leaves nothing: `test_agents_dir_pack_change_and_uninstall_leave_nothing_behind`, `test_plugin_pack_change_and_uninstall_remove_the_old_builds`.
- The shared references sit beside the skills so a skill's relative path resolves: `test_agents_dir_install_puts_the_shared_references_beside_the_skills`, `test_plugin_install_puts_the_shared_references_in_the_build`.
- The listing budget is printed by default, written only when asked, never lowers a larger value and is put back on uninstall: `test_claude_code_listing_budget.py` (`test_by_default_the_line_and_its_file_are_printed_and_nothing_is_written`, `test_a_larger_value_the_person_set_is_kept`, `test_write_merges_keeps_every_key_backs_up_and_uninstall_puts_it_back`, `test_the_user_scope_is_written_only_when_named`).

**The tool-free runner (`api`).** No tool is ever sent; files are inlined only from inside the project, never from quoted external content; a key is never written and an echoed key is redacted; redirects are refused: `test_api_run_agent.py` (`test_anthropic_request_has_no_tools_and_carries_agent_and_skill`, `test_paths_outside_the_project_hidden_files_and_symlinks_out_are_refused`, `test_a_path_named_inside_quoted_external_content_is_not_inlined`, `test_a_key_echoed_by_the_provider_is_redacted`, `test_redirects_are_not_followed`). The cost of a call comes from the provider's report or, for one endpoint, from `adapters/api/prices.json`: a call whose estimate is over `--max-cost-usd` is refused before it is made, and a model missing from the file runs with a warning and a null cost for one endpoint, which the first runtime's `today_spend` (`scripts/runtime.py`) counts as `max_cost_usd_per_run`: `test_cost_estimate_over_the_limit_refuses_before_the_call`, `test_unknown_price_warns_and_reports_null_cost`.

## Entry points

| Command | What it does | Calls a model |
|---|---|---|
| `bash adapters/agents-dir/install.sh [--pack <name>] [--project <dir>] [--copy] [--uninstall]` | links (or copies, with the marker) the pack's skills and the shared references into the user's or a project's skills folder | no |
| `bash adapters/claude-code/install.sh [--pack <name>] [--listing-budget print\|write\|skip] [--project <dir>] [--settings-scope project\|local\|user] [--dry-run] [--uninstall]` | builds the plugin for the pack, links it where the tool finds it (`~/.claude/skills/openhora`; an install removes a link named `ai-workbench` that points into this checkout's build, an uninstall removes either), prints or writes the listing budget | no |
| `python3 adapters/claude-code/build.py [--pack <name>] [--prune] [--clean] [--dry-run]` | the plugin build alone | no |
| `python3 adapters/claude-code/listing_budget.py compute --pack <name>` | the budget a pack needs | no |
| `python3 adapters/claude-code/listing_budget.py apply --pack <name> [--mode print\|write] [--scope project\|local\|user] [--project <dir>] [--dry-run]` | prints the line to add, or with `--mode write` merges it into a settings file, keeping a dated backup and recording what it wrote | no |
| `python3 adapters/claude-code/listing_budget.py undo [--dry-run]` | puts back what each recorded write replaced, only while the value is still the one written | no |
| `adapters/<harness>/run-prompt.sh --prompt-file <f> --cwd <dir> --model <id> --out <dir> [--allow-web] [--max-cost-usd <amount>] [--no-tools]` | the eval contract; started by the runner inside the container, never by hand | yes |
| `adapters/<harness>/run-agent.sh --agent-file <f> --task-file <f> --project <dir> --model <id> --out <dir> [--skill-dir <dir>]... [--max-cost-usd <amount>] [--timeout-seconds <n>]` | the runtime contract; started by `scripts/runtime.py` | yes |
| `python3 scripts/doctor.py --harness <name>` | the classes the adapter's connectors satisfy, and every registered secret | no |
| `python3 scripts/select_skills.py --pack <name>` | which skills a pack selects | no |
| `uv run --with pytest==9.1.1 pytest -q adapters/<harness>/tests` | the adapter's tests, with stand-in runners | no |

## Known limits and improvements

| Limit or improvement | Where it is recorded |
|---|---|
| No adapter installs the hook that records a use; until one does, the block of the project's instruction file asks the model to run the recorder, and the model id is then `unknown`, since it is never taken from a model's own account | [adapters/claude-code/README.md](../../../adapters/claude-code/README.md), "Recording a use in a project"; [reliability model](../reliability-model-2026-10-02.md), section 7 |
| The adapter's report of the skills a run loaded (`skills_loaded`) is not reliable; no rule reads it | [backlog](../../backlog.md), R12 |
| A runtime agent run by `run-agent.sh` (the first runtime's) is limited by its tool list only; whether the reading tools can leave the project is the tool's rule. The contained run closes this for the task runtime | [backlog](../../backlog.md), N15; `contracts/runtime.md`, "The contained run" |
| A model on the person's own machine is not reachable from the eval container | [backlog](../../backlog.md), N14 (the `agents-dir` README still cites T12, archived) |
| The two eval tiers see different homes inside the container (the container's own for `claude-code`, a throwaway one for `agents-dir`); a case must not depend on either | both eval adapters' READMEs, "Evals" |
| The pinned command-line tool of the reference model does not know that model: the cost it reports is priced as for an unknown model, and its limits are its defaults | [backlog](../../backlog.md), T23 |
| A tool-free runtime runner sends whole files in the prompt; the platform reference is the only reference it sends, and a folder a task names is not expanded | [adapters/api/README.md](../../../adapters/api/README.md), "The prompt it builds" |
| The `api` adapter's first run against each endpoint with a real key is still to confirm | [adapters/api/README.md](../../../adapters/api/README.md), "Not yet verified with a real key" |
| An always-on, chat-first agent platform reads the `agents-dir` folder today; an adapter of its own (a scheduler, a messaging channel) would be an optional later package, planned in no file | [docs/decisions.md](../../decisions.md), 2026-09-22 |
| Agents are installed only by the plugin build; `agents-dir` installs skills alone | [adapters/agents-dir/README.md](../../../adapters/agents-dir/README.md), "Limitations" |
| The staging module says the installers are its second caller; they do not call it (they link, or copy with `cp -R`, which keeps `evals/` and `scripts/tests/` in a copy) | `scripts/stage_skills.py`, its docstring; `adapters/agents-dir/install.sh`; [AGENTS.md](../../../AGENTS.md), "Layout" |
| `evals/measure.py` says the refusal and account-limit texts are in `adapter.json`; they are in `eval.json` | [backlog](../../backlog.md), T23 |
| `adapters/agents-dir/run-prompt.sh` tests `OPENROUTER_BASE_URL` by name, which the floor route's `base_url_env` defines, and `adapters/agents-dir/adapter.json` registers a secret (`DEEPSEEK_API_KEY`) whose host is not on the proxy's allow list. Open, waiting for the next change of its layer | [review-2026-10-06.md](review-2026-10-06.md), finding 12; [lab.md](lab.md) |
| The eval contract has no shared conformance suite: each eval adapter's tests check it their own way, and the lab's container tests list the two eval adapters by name. Open, waiting for the next change of its layer | [review-2026-10-06.md](review-2026-10-06.md), finding 13; [lab.md](lab.md) |
| The strong model's runs of web cases use the variables `strong_web_pass_env` of the gate file names (a key with a low limit, in place of the account's token); `claude-code` registers `CLAUDE_CODE_WEB_API_KEY` for it, and while the gate file names none, a web case passes the account token like any run | `evals/eval_status.py`, the gate keys; `adapters/claude-code/adapter.json` |

## Changes

- 2026-10-06: first version, written from the code at the central branch's head of that day.
- 2026-10-09: the page is brought to the code of the central branch: the readers of the adapters' files are the kit, the runner, the executor and the facade, the files each script writes are listed per script, `--no-tools` is said to be `claude-code`'s alone, the contained run and the first runtime's rollback are stated, the listing budget's `apply` and `undo` are in the entry points, the layer map is named as the guard that no adapter file reaches the runtime or the lab, and the rows for findings 12 and 13 and for the web key are added.
- 2026-10-09: the workbench is called openhora: the plugin is `openhora` (link, manifest name, listing line `- openhora:<name>`, settings backups `.openhora-<time>.bak`), the installer removes the old link, and the install marker is `.installed-by-openhora` with the old one accepted until T23.
