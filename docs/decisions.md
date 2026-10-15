# Decisions log

One entry per structural decision. Newest last. Each entry: date, decision, alternatives rejected, why.

## 2026-09-22: Harness-agnostic core with adapters, Claude Code first

Rejected: a repository built only for Claude Code. Skills (`SKILL.md`) and project instructions (`AGENTS.md`) are open standards read by most tools; agent bodies converge on Markdown with `name` and `description`. Only advanced frontmatter, hooks and directories differ, and those live in adapters. Cost accepted: harness-exclusive features are only available through their adapter, and the core describes capabilities instead of naming tools.

## 2026-09-22: Workflows are skills; agents are thin delegation wrappers

Rejected: workflows as a third artifact type, and agents that carry full workflow prompts. No harness has a native "workflow"; a skill is the only executable unit every tool understands, and it runs in the main context where the user answers checkpoints. Agents exist only for isolation or parallelism. This also removes the skill-vs-agent duplication found in the previous repository.

## 2026-09-22: Nine areas, three levels, area prefixes

Seven lifecycle areas plus two horizontal ones (AI, Core). Three levels: area, sub-area, capability. Prefixes because skills install flat and names collide otherwise. `flow-` is a single prefix for every workflow regardless of scope: one rule instead of two.

## 2026-09-22: AI is a horizontal area, not an Engineering sub-area

Reversed an earlier decision. AI has no fixed position in the chain and produces artifacts of its own, which distinguishes it from transversal concerns. Rejected: distributing AI capabilities across areas (five owners, quintuple maintenance) and treating AI as references only (no deliverables). Boundary test and insertion points in `docs/area-map.md`.

## 2026-09-22: Areas communicate through artifacts, capabilities never invoke skills

Exposed by scenario validation. Keeps capabilities independent and testable, lets every capability run standalone, and makes flows resumable through a state file.

## 2026-09-22: Flat `skills/`, root is harness-neutral, adapters self-contained

**Reversed in part the same day** (entry "Packs are the unit of installation; optional areas exist"): the Claude Code adapter is no longer itself the plugin with `skills` symlinked to the core; it builds one plugin folder per pack. What stands: `skills/` is flat, the root privileges no harness, each adapter is self-contained.

Rejected: nesting skills by area (the plugin loader scans `skills/<name>/SKILL.md`; nesting would need manifest arrays for one rule more) and making the repository root a Claude Code plugin (privileges one harness at the root). The Claude Code adapter is itself the plugin, with `skills` symlinked to the core. A generic `agents-dir` adapter covers every tool that reads `~/.agents/skills/`.

## 2026-09-22: Environment requirement classes and actuator contract

Exposed by the "schedule a social post" scenario. Skills declare `requires` as classes, resolved by harness connector, then provider script, then graceful degradation. Skills with `side_effects` must implement a confirmation gate. Image generation ships first; video is a reserved slot.

## 2026-09-22: Write for the weakest model, evaluate against a floor model

**Reversed in part on 2026-10-02** (entry of 2026-10-02, "The reliability model, simplified after its independent review"): a skill no longer has to pass on the floor model. The gate is evaluated on the reference model; the floor model's results are recorded and shown, and no rule reads them. What stands: skills are written for the weakest model that will run them, and every skill is run on a floor model.

Detailed means explicit and templated, not long. Each skill must pass its evals on a floor model, not only on the strongest one. Floor models are configured in the eval tooling.

## 2026-09-22: No stacks from the factory

Engineering skills are stack-agnostic procedures with an optional `references/stacks/<stack>.md` slot and a detection rule. Stacks are added from real projects, following the authoring guide's rule against generic knowledge.

## 2026-09-22: Packs are the unit of installation; optional areas exist

Harnesses load every installed skill's name and description into every session and truncate past a budget, so "install everything" degrades triggering once the catalog grows. `packs/<name>.txt` lists patterns; adapters resolve them at install time. The Claude Code adapter now builds a plugin folder per pack (`build/<pack>/`) with per-skill symlinks, which also removed the only tracked symlink from the repository. The assistant area (`asst-`) is the first optional area: same rules, excluded from `default`. Rejected: a separate repository for the assistant pack (double tooling for the same conventions) and a tenth core area (scope creep on the "digital solution" promise).

## 2026-09-22: One explicit approval, then autonomy

Confirmation gates exist so the user sees exactly what will happen, not to interrupt repeatedly. Three approval scopes (action, plan, standing) are recorded in `docs/workbench/state.md`; a resumed session never re-asks for what is approved; scheduled work is confirmed at scheduling time and executed unattended after verifying the payload still matches. Flows honour a per-project `Autonomy.Checkpoints` setting (every-phase, milestones, end). Rejected: asking at every step (kills autonomy) and implicit consent from silence or from similar past approvals (unsafe).

## 2026-09-22: OpenClaw is a compatible runtime, not a content source

OpenClaw follows the Agent Skills spec and reads `~/.agents/skills`, so the `agents-dir` adapter covers it with no extra work. It is an always-on, messaging-connected runtime with cron, which makes it the natural home for the assistant area and for scheduled actuators. It is not a substitute for the assistant pack: a runtime is where skills run, a pack is what skills exist. Its bundled and community skills may cover many day-to-day tasks, so `asst-` skills are written only for gaps and for tasks that must follow this repository's contracts. No dedicated adapter until a real need (translating `requires` into its gating metadata). Security caveat: broad access and a history of exposed instances and malicious community skills; run isolated with least privilege and vet third-party skills.

## 2026-09-23: Build order approved; skills are written alongside a real project

Engineering before business for refinement (most mature content, daily use); merges (eng-root-cause, eng-implement, eng-code-review, core-critique) and drops (btw, coaching skills, duplicate documentation agent, organization-specific deploy and rewrite planner, stack-bound engineer agents) approved. A real project is the vehicle for waves 2 to 5; when it is an AI product, the AI engineering skills move forward to its engineering wave, and its business and product phases come right after core. Skills without prior expertise are written only alongside the real project phase that needs them.

## 2026-09-23: Skills never assume; they ask

Stated by the user as a design rule after a first initialization of a real project: agents and skills must not presume anything the user has not decided; they ask, with a recommendation. Added as a principle in `AGENTS.md`, reinforced in the writing standard and the capability template. It coexists with the one-approval rule: asking for a decision once is not repeated approval-seeking. Motivated by a real project where a "migration" request in fact hid a radical redesign that only the user could scope.

## 2026-09-23: Code reviews are temporary artifacts under docs/engineering/reviews/

`eng-code-review` writes `docs/engineering/reviews/<change>.md` (task id, else branch, else pull request number) so a flow can resume at the review step in a new session and `ops-pull-request` can carry the verdict and its conditions into the pull request description. Like plans, reviews are day-to-day artifacts: removed or archived when the change ships. The review never edits code; findings go back to `eng-implement` or the backlog. The `reviewer` agent is one perspective per instance, for harnesses that run work in isolation; the skill runs the perspectives sequentially everywhere else.

## 2026-09-28: An agent runtime as a new, tool-free layer; storage behind an interface; a real company's case first

Decided by the user. The end goal is a company run by agents, one per department, that take tasks, talk to each other through recorded messages and keep their data, managed from a local web app. The runtime is a new layer on top of the current core (skills, agents, contracts, providers), not a rewrite of it, and it names no AI tool: it runs agents through adapters, the way evals already run prompts through `run-prompt.sh`. Persistence is an interface with interchangeable implementations (SQLite first, a cloud store later), chosen by the user, in the same open-closed shape as providers. It is built against a real company's case, marketing agents first; what describes that company, its decisions and its data live in its own project, not here.

Rejected: building on one agent framework directly (it would tie the core to one vendor, against principle 1); keeping `docs/workbench/state.md` as the only store (a Markdown file does not take several agents writing at once); starting with a library project (not a company). Also rejected on 2026-09-28: a per-request "quick mode" without gates like Kiro's Quick Spec (https://kiro.dev/blog/faster-smarter-specs/, from a search snippet, accessed 2026-09-27). It runs every spec phase without approvals, which is what `Autonomy.Checkpoints: end` already does, while ours keeps confirmation gates for outward actions in every mode; switching it per request instead of per project adds a second switch to maintain and no safety.

## 2026-09-28: Security reviews of a project write their own artifact

`docs/area-map.md` treats security as a transversal reference that produces no artifact of its own. `eng-security-review` is the exception: triaging a project's dependency alerts ends in decisions (update, or dismiss with the host's reason and evidence) that must survive the session and back the dismissals, so it writes `docs/engineering/security-reviews/<date>.md`, the same shape as `eng-code-review`'s reports. The reference stays in `shared/references/security.md` for the rules every skill follows; the skill applies them to one project's state at one date. Version 0.1 covers dependency alerts only, by the user's decision (backlog S14 for the rest). Dismissals are an outward action with a confirmation gate; updates are proposed as tasks for `eng-implement`, never applied by the review.

## 2026-09-28: Claude models run on the maintainer's account; OpenRouter only for the floor model

**Reversed in part on 2026-10-01** (entries "The floor model is DeepSeek V4.1 Flash", "Evals run only in a container" and "The eval container, as built"): the strong runner is no longer the CLI signed in on the maintainer's machine; in the container it authenticates with a long-lived token from the secret store, passed by variable name; the floor model named here was replaced; and the options are read from `evals/eval-gate.json`, not passed by hand. What stands: the strong model and the grader run on the maintainer's account, and the floor provider's key reaches floor runs only.

Stated by the maintainer. Strong-model runs and the grader go through the claude-code adapter, signed in with the maintainer's own account; OpenRouter is used only to run the floor model (DeepSeek V3.2 through the agents-dir adapter). `eval_run.py --floor-pass-env` passes the OpenRouter key to floor runs only; before it, `--pass-env` handed the key to every run and to the grader. Rejected: running Claude models through OpenRouter (a second bill and a key the Claude runs do not need).

## 2026-09-29: Parallel by default

Stated by the user after the floor-model evals of six skills ran one after another for more than an hour: "o que puder ser rodado em paralelo deve rodar em paralelo". Added as principle 7 in `AGENTS.md`. Independent work runs at the same time; sequential execution needs a reason (a dependency, a shared resource, a rate limit) and says which. First application: `eval_run.py --jobs`, default 4, at most 8. The earlier belief that parallel agents-dir runs break the runner (backlog S9) is withdrawn: the "UnknownError" it recorded is what a missing provider key produces, and four concurrent floor-model runs with separate homes all answered (backlog T8).


## 2026-09-29: A standing approval whose bounds live in a file binds that file's hash

`contracts/environment.md` said standing approvals carry no hash, because they cover a class of action, not a payload. The first standing approval over a public action, automatic replies to comments on a person's own LinkedIn posts (backlog PB6), keeps its bounds (categories, languages, daily limit, phrases never used in replies) in `docs/marketing/engagement-policy.md`. An edit to that file would silently widen what the person approved. The approval row therefore records `policy:<sha256 of the file>`, and `mkt-engage`'s `policy_gate.py` refuses automatic replies when the file's hash, the row's status (`active`, or `paused` by the person) or its expiry does not hold. Rejected: re-reading the policy's bounds from the approval row's text (a model would have to parse prose, and a changed file would still pass).

## 2026-09-30: In the runtime, the model proposes and code decides; a factual answer needs checked sources

`contracts/runtime.md`: an agent started by a trigger gets reading tools only (`run-agent.sh --tools Read,Glob,Grep`) and returns a proposal block; `scripts/runtime.py` runs the skill's gate and only then calls the provider. Trigger data (comments, e-mails) is written by strangers, so a model that could run the publisher could be talked into publishing.

A comparison of models on real comments (2026-09-30, 8 comments, 2 runs each) showed why the gate cannot trust the model's own category: DeepSeek V3.2 once labelled a question with no source "answerable from sources" and invented the answer, and the gate would have let it out. `policy_gate.py` now requires a factual answer to cite project files that exist, and every number in the reply to appear in them. A claim without a number still passes any deterministic check; the model choice covers that (Sonnet 5.5 classified all 16 cases correctly). Rejected: a second model as a judge (cost and latency for 0 to 30 replies a day) until a real miss shows it is needed.

## 2026-10-01: Eval results are recorded per skill; status is computed

**Decided to be replaced on 2026-10-02** (entry of 2026-10-02, "The reliability model, simplified after its independent review"): one record per skill and the three states give way to evidence lines per run and to bands. Until phase B of the plan in force builds that, the record, the three states and the generated table described here are what the tools do. The paths are the ones of the day: the status script is `evals/eval_status.py` since the entry "The eval harness lives in `evals/`".

A review of the inventory found that most of the skills ticked as built had no eval result on record, and some of them scored low once measured. Five causes: "done" was a tick written by hand; results lived only in the git-ignored `evals-workspace/`; changing a skill did not force a new evaluation; `eval_run.py` let infrastructure failures (a provider out of credits, a session limit) pass as low or missing scores; and eval cases were never checked (fixtures copied to another path than the prompt named, prompts citing files the case did not ship, assertions the grader could not verify).

Decided: a complete, full run writes `skills/<name>/evals/result.json`, committed, with the scores, the gate and a sha256 of the skill folder. `scripts/eval_status.py` computes each skill's status from it: `draft` (no record, a failed gate or an incomplete run), `evaluated` (gate passed on the current content) or `stale` (gate passed, then the folder changed). The status table in `docs/inventory.md` is generated from it, and `scripts/validate.py` fails when a record is invalid or the table is out of date, so a commit that changes an evaluated skill shows it as stale in the same diff. `eval_run.py` checks every case before any model call, lists infrastructure failures apart from scores and marks the iteration incomplete, with its own exit code.

Rejected: rerunning evals in the pre-commit hook or in CI (model calls, cost and provider keys do not belong there; the check compares hashes instead and stays offline); a hash over `SKILL.md` alone (a script, a reference or a case changes behaviour or what is measured as much as the body does); making `stale` and `draft` errors by default (most skills start as `draft`; `--strict` turns them into errors once the backlog of unrecorded skills is cleared).

## 2026-10-01: A turn that ends early with no error is an infrastructure failure, retried and counted

In one day of floor-model runs, about one run in nine ended its turn early with exit 0 and no error: the model stopped mid-plan, printed a tool call as text, or looped writing reminder blocks to itself. Nothing was written, no question was asked, and the run scored zero, which is not the skill's doing.

Decided: `eval_run.py` detects an early end with a deterministic, conservative rule (no file created or changed, and a response that is empty, carries tool or control markup at the start of a line, or ends on a line that announces a next action while the response asks no question), reruns it in a fresh folder up to `--retries` times, keeps every early attempt, and counts them per model in `benchmark.json` and in the record. A run that early-ends on every attempt is an infrastructure failure and makes the iteration incomplete. A reply that asks the user a question and writes nothing is a stop-and-ask, and a run that wrote a file and then stopped before finishing is graded as it is: neither is an early end.

Retries hide the problem from the scores, so they must not hide it from the report: when a model has at least three early ends and either a rate above 15% of its attempts or all of them on one case, the runner prints a warning that says to read the transcripts and decide. Concentrated on one case, the skill or the case may trigger it; spread across cases, the provider or the model is unreliable, and another provider or another floor model is the answer. Rejected: scoring early ends as zeros (it measures the provider, not the skill) and a model as the judge of what an early end is (cost, and one more thing that can fail without an error).

## 2026-10-01: The floor model is DeepSeek V4.1 Flash; local models are a measured goal

**Reversed in part on 2026-10-02** (entry of 2026-10-02, "The reliability model, simplified after its independent review"): "a good score on a very affordable open model is the passing criterion" no longer holds; the floor model's results are information. What stands: the floor model named here, and a local model as a goal that is measured and published.

The floor model changes from `openrouter/deepseek/deepseek-v3.2` to `openrouter/deepseek/deepseek-v4.1-flash`. All measured on 2026-10-01: it has open weights (MIT) and costs a fraction of the previous one; on the five evaluated skills it scored 1.00 with the skill in every run (0.40 to 0.57 without it), with no early end in 66 attempts, where the previous floor scored 0.81 to 1.00 and ended its turn early in 22% of the attempts of one run.

The purpose of the floor is restated: a good score on a very affordable open model is the passing criterion. Running on a person's own machine (Ollama, models of 20 to 30 billion parameters) is a goal that is measured and published, and it does not block a skill. First local results on one skill (design-system, 2 cases, 3 runs each, with the skill): gpt-oss 20B 0.26; Qwen3-Coder 30B 0.43; Devstral Small 2 24B unusable through the runner (it announces a step and ends its turn every time); Qwen3.8 27B still being measured. Other inexpensive hosted models on the same skill: DeepSeek V4 Flash 1.00, Qwen3.7 Flash 0.89, gpt-oss 120B 0.17 with early ends.

How it is enforced: the gate is a committed file, `scripts/eval-gate.json` (strong and floor model, their adapters, the floor model's key variable, the threshold). `eval_run.py` takes its defaults from it, so `eval_run.py --skill <name>` runs the gate. `scripts/eval_status.py` reads a record made on another floor model as `stale` ("evaluated on another floor model"), so changing the floor sends every skill back to be rerun, and judges recorded scores against the configured threshold. A full run on another floor model, a local one for instance, writes no record unless `--record-anyway`. The file sits outside `skills/`: it names adapters and models, which the core does not, and changing it alters no skill's content hash.

Rejected: keeping the previous records as passed (they did not pass on the current gate); a local model as the gate now (the best local score so far is 0.43); several floor models in one record (one gate, one answer).

## 2026-10-01: The strong model is Claude Sonnet 5.5; both eval models are named in one file

**Reversed in part the same day** (entries "Evals run only in a container; the runner leaves the skill; a record says how it was measured" and "The record and the gate as built"): a record made with another strong model does not stay valid; it reads `stale`. The command and the file are `evals/eval_run.py` and `evals/eval-gate.json` since "The eval harness lives in `evals/`". What stands: the strong model, and both models named in one file and never passed by hand.

Decided by the maintainer. Every evaluation until this date used Claude Opus 5.5 as the strong model and as the grader; it used up the account's usage limit three times in two days, and 42 skills are still to be evaluated. The strong model of the gate is now Claude Sonnet 5.5: it is strong enough for the condition "the skill does not make a strong model worse" and for grading assertions, at a fraction of the usage. A record names the strong model it was made with; records made with the previous strong model stay valid (only a change of floor model or of the skill's content makes a record stale).

Both models, their adapters and the threshold live in `scripts/eval-gate.json`, and nowhere else. A session never passes a model to the runner: `python3 skills/core-skill-creator/scripts/eval_run.py --skill <name>` reads them from that file, so every session evaluates on the same pair. Changing a model is a change to that file, with an entry here.

## 2026-10-01: An eval run leaves nothing running and shows no dialog

**Reversed in part the same day** (entry "Adapters run only in the container; cases list no commands; tolerance 0.05"): the throwaway keychain was removed with the rest of the code for running on a person's machine. What stands: a run's processes are ended as a group, on every way out.

Two defects found while running the gate on many skills on macOS.

A browser started inside a run showed the person a "Keychain Not Found" dialog, once per launch: the run's throwaway `HOME` has no `Library/Keychains`, and Chrome looks for its "Chrome Safe Storage" item in the default keychain, which macOS finds through `HOME`. A skill's script can start the browser with a mock keychain, but a model that starts one by itself cannot be controlled. Decided: an adapter that replaces `HOME` on macOS creates an empty keychain there and makes it the default, with every `security` call run under the throwaway `HOME` only, so the person's keychains are never touched; the keychain is deleted with that home. The adapter that keeps the person's `HOME` needs nothing.

Stopping an evaluation left its model sessions working for many minutes, and starting browsers: a timeout or a kill ended only the adapter's shell. Decided: `eval_run.py` runs every adapter call and setup command in a session of its own and ends the whole process group on a timeout, when the call returns, on TERM, INT or HUP, and on any way out; each adapter does the same for the runner it starts.

## 2026-10-01: Eval runs happen outside the repository

**Superseded in part the same day** (entry "The eval container, as built"): what the last paragraph leaves open is closed by the container, which sees no home folder, no checkout and no disk to search. What stands: case folders are created outside the repository.

Case folders lived under `<repository>/evals-workspace/`, so a model could walk up from its case folder and find the workbench. Evidence from the runs of that day: a floor model's log shows `find <repository>/evals-workspace/...` and its reply to a without-skill case says it will use "the workbench's own" capability, "which lives in the skills repo"; 3 of 12 floor without-skill replies of one skill name the skill; on the strong tier, without-skill replies that mention the repository by name exist for six skills (6, 3, 3, 3, 2 and 2 response files). A harness may also load instruction files from the parents of the folder it runs in. The without-skill baseline was therefore inflated, which understates what a skill adds and can change the gate's strong condition (with the skill at least as good as without it).

Decided: `eval_run.py` runs every case and every grading in a fresh temporary folder outside the repository, whose parents hold no repository, instruction file or skills folder and whose path names neither the workbench nor the skill; the environment carries no path into the repository; the folder is moved to its place under `evals-workspace/` when the run ends, also after a timeout or a stop. As a guard, the output of every without-skill run is searched for the repository's path; a hit is recorded as `contaminated` and blocks the record unless `--allow-contaminated`. Records made before this keep their scores with the skill; `eval_run.py --only without --update-record` measures the baseline again, alone, and replaces the two without-skill scores of a record that is still current.

Not closed by this: a workbench installed globally in a harness, and a model that searches the whole disk; the guard reports the second.

## 2026-10-01: The strong model's eval commands are confined by a sandbox, not listed

**Reversed the same day** (entry "Adapters run only in the container; cases list no commands; tolerance 0.05"): the sandbox settings, the command rules and `allow_commands` were removed; the container is the boundary for both tiers. What stands: the finding that a list of allowed command texts denies harmless commands.

The strong model scored below the floor model on several skills. The cause was the eval harness, not the skills: the strong model's adapter let a command run only when its text matched a rule (the case's `allow_commands` and the skill's scripts), while the floor model's adapter approved everything. Harmless forms did not match: the skill's own script fed by a heredoc or called in a loop, a pipe, a variable, `mktemp -d`. The runs kept on the maintainer's machine carry 809 denied commands on the strong tier, most on the skills where it lost to the floor (22 in 6 runs of one, 17 of them the skill's own script; 53 in 15 runs of a research skill, 40 of them web tools its cases had not allowed).

Options weighed: a longer list of rules (still matches text, so the next harmless form is denied again); approving everything, as the floor tier does (some cases plant an instruction in a fixture on purpose, and a model that followed it would act on the maintainer's machine); a sandbox.

Decided: on the strong tier every command runs inside the harness's sandbox, enforced by the operating system: writes inside the case folder and temporary folders, no network, no read of the workbench or of credential folders, and no start at all when the sandbox is unavailable. The case's `allow_commands` prefixes and the skill's own scripts keep running unconfined when called plainly, as before, since a browser does not start inside the sandbox. `allow_web` stays a per-case decision. Details and the checks made: `adapters/claude-code/README.md`.

Consequences: a record whose strong-tier runs were made under the rules understates the strong model; the gate was still passed under the harder condition, so those records stay valid, and they are measured again as each skill is next evaluated. `eval_status.py` does not turn a record `stale` for an adapter change. The two tiers are still not confined alike: confining the floor tier is backlog S19.

## 2026-10-01: Skill evaluation pauses for an architecture review

In one day the eval harness was changed four times for causes found while measuring: runs that failed on infrastructure counted as scores, without-skill runs found the workbench by walking up, the strong tier was denied harmless commands the floor tier could run, and floor runs found the workbench by searching the disk. Each fix changed what the records mean, and 26 records were partly measured again twice. The last cause, and a shell profile on the maintainer's machine that breaks `cd` for every run, point at the same thing: results depend on the machine.

Decided by the maintainer: before a container environment is tried (backlog T16), the state is written down (backlog T11), the whole architecture is reviewed, tests included, and a plan is made from the architecture that is decided, so that the remaining skills, and the 26 already recorded, are measured once more and not again after that.

## 2026-10-01: Evals run only in a container; the runner leaves the skill; a record says how it was measured

Decided by the maintainer on the review of that day (`docs/architecture/review-2026-10-01.md` (removed on 2026-10-14; `git show d3e60770:docs/architecture/review-2026-10-01.md`), D1, D2, D3, D5, D6):

- **One environment, no alternative.** Every eval run executes in a container built from one pinned image, one container per run, started by an executor layer between the runner and the adapters. The container is the boundary for both tiers, which get the same rights; nothing of the workbench or of the person's home is mounted. There is no host mode: one standard, so that every record is comparable. This closes backlog S19 and replaces T6.
- **The eval runner moves out of `core-skill-creator`** to a top-level `evals/` folder with its tests, the grading template and the gate configuration.
- **A record names how it was measured** (image digest, runner and CLI versions, strong model, grader, measurement version) and is `stale` when the skill folder, the floor model, the strong model, the grader or the measurement version differs. The measurement version is a number in the gate configuration, raised on purpose when a change alters what is measured; the runner's own hash is not used.
- **In the container the strong runner authenticates with a long-lived token** from the secret store, passed as an environment variable; to be confirmed by the proof of concept.
- **Network:** egress only to the model provider; a case with `allow_web` gets open egress; language dependencies and a browser come with the image.

## 2026-10-01: The gate asks the threshold of both models

**Reversed in part on 2026-10-02** (entry of 2026-10-02, "The reliability model, simplified after its independent review"): the gate is evaluated on the reference model alone; the floor model's score is information. What stands: the threshold of 0.8 and the tolerance against the baseline.

The rule in the code was: the floor model with the skill at the threshold (0.8) or above, and the strong model with the skill at least as good as without it. The strong model had no threshold of its own, so a skill passed with the strong model at 0.78; and the comparison had no tolerance, so a difference smaller than the spread between runs could fail a skill.

Decided by the maintainer (D4): a skill passes when **both models score at the threshold or above with the skill, and the strong model with the skill is not below the strong model without it by more than a tolerance**. The tolerance is a number in the gate configuration, set from the spread measured in the container's proof of concept and approved by the maintainer; until then it is 0. Changing the rule raises the measurement version, so every record made under the old rule reads `stale`.

## 2026-10-01: The eval harness lives in `evals/`

Done as decided (D2): `eval_run.py`, `eval_status.py`, `eval-gate.json`, the grading template and their tests moved to a top-level `evals/` folder. It is not part of the core: it reads `adapters/` to find a harness's runner, which a core file may not do. `core-skill-creator` keeps the procedure and names the commands; a change to the runner or to how every skill is graded no longer changes that skill's hash. Entries above this one name the old paths (`skills/core-skill-creator/scripts/eval_run.py`, `scripts/eval_status.py`, `scripts/eval-gate.json`); they are left as written.

## 2026-10-01: The record and the gate as built

Done as decided (D3, D4). `evals/eval-gate.json` gains `grader`, `strong_tolerance` (0 until the proof of concept gives it a number) and `measurement_version` (2; a record without the field is version 1, the earlier rule). A record gains `measurement_version`, `tolerance` and, when the runner supplies it, `environment`. The status is `stale` when the measurement version, the strong model, the grader or the floor model differs from the configured one, or the skill folder changed. Records of version 1 stay valid files and all read `stale`; they are not rewritten, they are replaced when each skill is measured in the container. Raising the measurement version is a deliberate act in the commit that changes what a run measures: the next raise comes with the container environment.

## 2026-10-01: The eval container, as built

The proof of concept confirmed D1, D5 and D6 (`docs/architecture/container-poc-2026-10-01.md` (removed on 2026-10-14; `git show d3e60770:docs/architecture/container-poc-2026-10-01.md`)). Every command of an eval (model run, grading, setup, fixture commit) runs in its own container, started by `evals/executor.py` from the definition in `evals/container/`. A container sees the run folder, the adapters, the shared references and the skill; it reaches the model providers through an allowlisting proxy on an internal network, nothing at all for setup, and the open network only for a case with `allow_web`. The strong runner's token and the floor runner's key come from the secret store and travel by variable name. A record names the definition's hash and the image id. Measurement version 3.

The unit tests of the runner drive stand-in adapters on the host through a module switch; that switch is not an option of the runner and no record can be written through it by a person running the command.

## 2026-10-01: Adapters run only in the container; cases list no commands; tolerance 0.05

Following the container (entry above), decided by the maintainer and built:

- **The eval adapters refuse to start outside the eval container.** Both allow a model every tool; that is safe only where the container is the boundary. The code that existed for running on a person's machine is removed: command rules and sandbox settings in the strong adapter, the throwaway keychain in the floor adapter.
- **`allow_commands` is gone** from the runner, from the adapter contract and from the 32 case files that listed it. It named what a model could run on a person's machine; in the container every command runs. An `evals.json` that still carries it is refused, so that no case keeps a setting that does nothing.
- **A case's setup runs in the container**, also in the check made before the first model call. The static check (`--check-cases`, which `validate.py` runs) needs no container: a case with setup is listed there as unchecked.
- **`strong_tolerance` is 0.05**, approved by the maintainer from the spread measured in the proof of concept; to be revisited when the 48 skills are measured.
- A CI job builds the image on Linux and checks, without a model, that a run writes only in its folder, sees no home and no checkout, reaches nothing without a network, only the providers through the proxy, and the open network when a case asks for it.

None of this raises the measurement version: version 3 was set with the container and no record exists under it yet.

## 2026-10-01: The strong adapter raises the skill-listing budget; measurement version 4

The first skills measured in the container showed the strong model ignoring a skill it had been given. Cause: the harness lists skills to the model within a character budget, its bundled skills first, and listed the skill under test by name only, with no description (`adapters/claude-code/README.md`). The adapter now raises the budget so that the description is listed. This changes what a strong-tier run measures, so the measurement version goes from 3 to 4; the five records made under version 3 in the hours between were discarded before being committed, and those skills are measured again. What a person's own installation shows the model is a separate question: backlog T18.

## 2026-10-01: What measuring 48 skills in the container found in the harness

Found while measuring, each fixed in `evals/` or an adapter with a test; none changes what a clean run measures, so the measurement version stays 4, and the skills a defect had touched were measured again.

- **A run could read the cases of its own skill.** The skill folder is mounted read-only for the adapter to copy, and its `evals/` folder (expected output, assertions) came with it. Seven floor runs of four skills had read it. An empty folder now covers it.
- **Images went to the grader as text.** A produced PNG was pasted into the grading prompt, which told the grader nothing and made some prompts too long to pass as one argument, so gradings failed. A binary file is now described (kind, size, dimensions), and the strong adapter takes the prompt on standard input.
- **The floor runner's web search is rate limited.** With several runs searching at once the search service answers 429 and the model waits until the run times out. Skills whose cases search the web are measured alone, two runs at a time. A rate limit is one of the reasons principle 7 accepts for not running in parallel.
- **A provider refusal is not a score.** One baseline case, an audit of a deliberately malicious fixture run without the skill, is refused by the strong model's provider on every attempt. The runner counts it as an infrastructure failure, so that skill has no complete record. Whether such a case counts as zero for the baseline, or the fixture changes, is the maintainer's decision.

What the skills needed, in general terms, so that the next ones are written with it: a grader sees only the reply and the files a run leaves, so a skill's report must quote the evidence (the command and the output line of a check, before and after), and an assertion must ask for that evidence, never for "the script was run"; a fixture must be a small real project in the project's layout, not placeholders; a script that needs a browser finds it from the environment and works where a browser refuses its own sandbox; a description must name the user's words for every situation the skill handles, or the model does not use it.

## 2026-10-01: A refused baseline run scores zero; a case may bring files of the repository

Decided by the maintainer for the last two skills without a record.

- **A provider's refusal of a without-skill run is a score of zero**, listed in `benchmark.json` `baseline_refusals`. The baseline exists to show what the skill adds, and "the model alone could not do the task" is a baseline. The same refusal of a run that has the skill stays an infrastructure failure: it says nothing about the skill and is never a score. The alternative, a milder fixture, would have weakened what the case tests (an audit of a deliberately hostile skill).
- **A case may list `workbench_files`**: files and folders of this repository copied into the case folder at the same relative path. It is for a skill whose job is the workbench itself (creating, validating, evaluating skills), which needs the real tooling to act on. The alternative, a copy of that tooling kept as a fixture, would drift from the real one. Refused: paths that leave the repository, version control, eval workspaces and any skill's eval cases, which hold expected outputs. Such a case deliberately shows the model part of the repository; the contamination guard looks for the repository's path, which the copies do not carry.

## 2026-10-02: Flows that are not built are named as planned; capabilities state the artifact they need

Decision D12 of `docs/architecture/review-2026-10-01.md` (removed on 2026-10-14; `git show d3e60770:docs/architecture/review-2026-10-01.md`), as built. Only `flow-fix-bug` exists, so every other flow name is marked planned wherever it is cited as a route (the orchestrator, its routing table, the area map, the inventory); the orchestrator keeps its rule for a missing skill, which is to name it as the route with the status `pending` and propose one fallback for the user to accept. A capability no longer tells the model to run or route to another skill: it states the artifact it needs, names the skill that writes it, and stops for the user to run it, so that only flows invoke skills (principle 4). The alternative, removing the citations, would have left the orchestrator without a name for requests that are flows, and its eval cases expect those names.

## 2026-10-02: Phase 5 decisions: D7 to D10 and D12 approved; a skill's tests live in the skill and outside its hash

Decided by the maintainer, on the decision table of `docs/architecture/review-2026-10-01.md` (removed on 2026-10-14; `git show d3e60770:docs/architecture/review-2026-10-01.md`).

- **D7, D8, D9, D10 and D12 are approved as recommended**: the artifact contract (D7), one source for shared code (D8), providers named by class (D9), tests of skill scripts in the skill (D10), and flows that cite only what exists (D12). They are phase 5 of `docs/architecture/plan-2026-10.md` (removed on 2026-10-14; `git show d3e60770:docs/architecture/plan-2026-10.md`).
- **A skill's script tests do not count for its content hash and are not copied into an eval run.** They live in `skills/<name>/scripts/tests/`. `evals/eval_status.py` leaves everything under that folder out of the hash, and the eval adapters remove it from the copy of the skill a model gets, as they do with `evals/`. Reason: a test is not part of what a model uses, so a new or changed test measures nothing differently and must not cost a measurement. The alternative, tests kept in `scripts/tests/` so that the hash never sees them, left skill scripts far from their tests and the hook unable to tell which tests a changed script needs. The skills that already had tests inside their folder read `stale` once, because their recorded hash was computed with those files.
- **Phase 5 is carried out in full without measuring the skills again for now.** A skill whose folder phase 5 changes reads `stale` until a later measurement round, which is done together with backlog T19 (assertions that pass in every run). Until then `stale` on such a skill means "changed by phase 5, last measured before it", not a defect.

## 2026-10-02: The orchestrator is the one capability that hands a request over; requirement classes keep their names

**Reversed in part the same day** (decision 14a of `docs/architecture/final-plan-2026-10-02.md` (removed on 2026-10-14; `git show d3e60770:docs/architecture/final-plan-2026-10-02.md`)): requirement classes are renamed; every class takes the form `<role>:<target>` (`mailer` becomes `sender:email`, `mailbox` `reader:email`, `scheduler` `scheduler:job`, `store` `store:runtime`), in phase C of that plan. What stands: the orchestrator is the one exception to principle 4.

Approved by the maintainer, closing what backlog item T20 left open. `core-orchestrator` is the one exception to principle 4: it is the router, so it names a skill and hands the request over to it, and does none of that skill's work; every other capability reads and writes artifacts, and `AGENTS.md` says so in the principle, in "Skill kinds" and in "Never". Requirement class names are not renamed: some carry a prefix and some are bare (`mailer`, `mailbox`, `scheduler`, `store`), a skill copies a name exactly as `contracts/environment.md` spells it; renaming would change every skill and provider that declares one.

## 2026-10-02: Providers are resolved by class; one interpreter rule; ledgers in a data folder (D9, D13)

Decisions D9 and D13 of `docs/architecture/review-2026-10-01.md` (removed on 2026-10-14; `git show d3e60770:docs/architecture/review-2026-10-01.md`), as built.

- **One resolution function.** `providers/resolve.py` turns a requirement class into the provider script, in this order: the class's environment variable (`<CLASS>_<SUBCLASS>_PROVIDER`, then `<CLASS>_PROVIDER`; the naming that existed), the platform default where one exists (`scheduler`: launchd on macOS, systemd on Linux), the only implementation when the class ships exactly one. Nothing resolving is exit 3 with the variable to set; an unknown class is exit 2. A name is accepted only when it is a script shipped in the class's folder, never as a path.
- **Who uses it.** `scripts/runtime.py` and `scripts/runtime_vote.py` (the store was a fixed path, the scheduler was launchd on every platform), `scripts/doctor.py` (it had its own lookup, and reported a class as missing unless its variable was set; it now checks the provider the function chooses), and the skills, which run `python3 <workbench root>/providers/resolve.py --class <class>` and use the printed path. A name in `runtime.json` still wins, so existing files keep working.
- **The workbench root** is the environment variable `WORKBENCH_ROOT`; unset, the function uses its own checkout, and a skill asks the user.
- **What was weighed.** A registry file mapping classes to scripts was rejected: the folder layout already is the registry, and a second list would drift. Resolving inside each skill's own script was rejected: skills would each carry a copy of the rule. A default for every class with several implementations was rejected: only the scheduler has a choice the platform decides; any other class with two implementations is the user's choice, asked through the variable.
- **Python version (D13).** `providers/CONTRACT.md` names the scripts that run on the system interpreter the scheduler uses (Python 3.9): the scheduler providers, the runtime and what it starts with its own interpreter, and `providers/resolve.py`. Their header says `requires-python = ">=3.9"`; the store provider claimed 3.10 and needed nothing from it, so its header was corrected. `scripts/tests/test_runtime_python39.py` checks syntax, header and import for each, and a CI job runs their tests on Python 3.9. Providers that need more are started through `uv run`.
- **Ledgers.** The idempotency ledgers of the publisher and vcs providers moved from the cache folder to the data folder the scheduler uses, because clearing a cache must not lose the record of what was published. On first use the old ledger is copied to the new place and kept. Reading the old ledger on every lookup was considered, for jobs scheduled before the change, which run a copy of the old provider and keep writing to the old place; the maintainer chose the simpler rule instead: those jobs are scheduled again after upgrading.
- **Left for D11:** the runtime still names the skill scripts it calls, and `payload.py` still builds the publisher's path from the workbench path and the platform.

## 2026-10-02: A full audit before one final measurement round

**Reversed in part the same day** (entry of 2026-10-02, "The reliability model, simplified after its independent review"): there is no final round and no freeze after it. The next measurement is the first full test of the 48 skills under the model, and a later change costs a small test. The section this entry says awaits the maintainer was answered in full on 2026-10-02. What stands: the audit, its findings, and the order of the plan (what is known to need fixing is fixed before the 48 skills are tested).

The 48 skills were measured once in the container (backlog T11), and the changes merged since then left 15 of them `stale`. The maintainer decided that the skills are measured one more time and that this round is to be the last for the skills as they are: everything that has to be fixed is fixed before it, even at the cost of measuring all 48 again, and whatever changes a skill's folder or what a run measures is frozen after it.

So that the round is planned from what is true, the whole repository was audited first: nine read-only audits run in parallel (six over the 48 skills in groups, one over the eval harness, one over what crosses skills, one over every backlog item), none changing a file or calling a model. The reports are in `docs/architecture/audit-2026-10-02/` (removed on 2026-10-14; `git show d3e60770:docs/architecture/audit-2026-10-02/`).

What the audit found, in short:

- **In the skills.** Reports that say a check was done instead of quoting its output, and assertions that ask for what a grader cannot see (a command that ran, a file that did not change); script paths that exist only in the workbench; stop gates without the words that make them hold; about 30% of the assertions passing in every variant, and several cases that score the same with and without the skill; 25 skills writing the state file without declaring it; fixtures with runtimes the image lacks, dates relative to the day of the run and, in places, the numbers and dates of one real case; nine scripts that end in a traceback on a missing flag value.
- **In the harness.** A grader that is inconsistent rather than biased, mostly for what its template does not say and what it cannot see; three runs per case, where one iteration's mean moves by about 0.045 between identical reruns; an early-end detector wrong in 7 of 12 detections; runs that can read more of the workbench than they should; an image that cannot be rebuilt and whose scratch folder the floor runner cannot write; a contamination check that cannot fire; nothing that stops a change to the measurement without raising its version.
- **In the backlog.** 82 items: 38 done, 18 partly done, 26 not done; nine ticks that do not match the code; 19 pieces of work that no item covered; one CI job failing on `main`.

The plan in force is `docs/architecture/final-plan-2026-10-02.md` (removed on 2026-10-14; `git show d3e60770:docs/architecture/final-plan-2026-10-02.md`). It replaces `docs/architecture/plan-2026-10.md` (removed on 2026-10-14; `git show d3e60770:docs/architecture/plan-2026-10.md`), whose phases 0 to 4 are done. Its order follows one rule: repairs that touch neither a skill nor the measurement, then the measurement changed once (version 5), then every skill edited once, then a dry run, then the round, and only after it the work that is independent of skills.

Its section "Decisions for the maintainer" awaits the maintainer: 14 decisions that change the plan (among them the runs per case, single or double grading, how the freeze is enforced, the image's platform, a fixed clock, the owners of the shared ledgers, what the runtime is, and what is done with fixtures that carry a real case) and 76 defaults that apply unless the maintainer objects. Until they are answered nothing in that section is decided. Rejected as an alternative: measuring the 15 stale skills now and fixing the rest later, which would have cost a second round for most skills.

## 2026-10-02: A reliability score per model, built from evidence, replaces the three eval states

**Replaced by the next entry.** What stands of this entry is its direction: evidence per model instead of three states, a full test once, small tests afterwards. Its details do not hold any more: the score is not weighted by kind and decayed, field use carries no skill, the first full test is not 1,884 runs, CI does not fail on "guard cases without lab evidence", and the model document does not win over the plan (the two say the same thing: one describes the model, the other the work).

Decided by the maintainer before the plan of 2026-10-02 started. A skill is no longer `draft`

Why: under the three states any change inside a skill folder discarded all its evidence and asked for a complete measurement on two models, so the plan had to build a freeze and one last round of 3,140 runs around that cost, and it would not scale with more skills, more changes or more models. Under the model the first full test of the 48 skills is 1,884 runs and one grading pass (about 36% of the calls on the strong model's account), and a later change costs a bump, a targeted test or nothing.

Rejected: keeping the states and making the round cheaper (the cost of every later change stays); a score with no lab requirement (the behaviours ordinary use never exercises, such as stopping before a side effect, would go unmeasured, so guard cases are always run in the container); thresholds on the score alone (a backtest on the 48 records shows they cannot separate a fresh full test from a version bump with no new evidence, so two rules stand beside the score); a decay by age (a score that moves with the calendar makes the generated table stale with no commit).

The model, its backtest, its limits and its changes to the plan are in `docs/architecture/reliability-model-2026-10-02.md`, which awaits review; where it differs from `docs/architecture/final-plan-2026-10-02.md` (removed on 2026-10-14; `git show d3e60770:docs/architecture/final-plan-2026-10-02.md`) it wins, and the plan is amended after the review.

## 2026-10-02: The reliability model, simplified after its independent review: bands by rules from lab evidence only

The model of the entry above was reviewed the same day by an independent reviewer (4 blockers, 14 important findings, 9 minor ones; digest in `docs/architecture/audit-2026-10-02/model-review.md` (removed on 2026-10-14; `git show d3e60770:docs/architecture/audit-2026-10-02/model-review.md`)). The maintainer adopted the simpler version that review recommends, with every correction it proposes. The same reviewer then read the pull request that carried the result and found ten points where a rule did not work as written (P1 to P10 in the digest); all were accepted, and this entry states the model with them applied. This entry replaces the details of the entry above; its direction (evidence per model instead of three states, a full test once, small tests afterwards) stands.

What is decided:

- **Evidence** is one line per lab run, in one file per test event. A skill's content hash leaves out all of `evals/`; each case has its own hash, over the whole case. The 48 records of the first round stay as history and nothing is converted from them.
- **Two kinds of lab test**: a full test (every case with the skill on one version on the reference model, plus the baseline) and a partial test (named cases, with the skill only). The baseline is reused while the case, the model and the measurement are unchanged. Only a full test evaluates the gate: an added case is `pending` until it has run, a changed case enters through a full test, and an abandoned full test keeps its lines.
- **Change classes**: X for security and contract, Y for everything else, Z only by an allow-list written from the positive side (the `## Purpose` section and text outside any section that instructs: a typo or formatting) with a budget in characters. The validator checks the declared class against the diff.
- **Guards**: the tag is on the assertion; every guard assertion must have run, and have no confirmed failure, in the with-skill runs of the current set (the lab lines of the current `X.Y` made since the newest epoch, measurement floor or dependency change that applies to them); a failed guard verdict is graded once more before it counts, and a confirmed failure is cleared only by a change; guard cases run again on every Y change and do not alone return a skill to `reliable`; a skill with side effects has a guard for each declared effect.
- **Bands are rules**, computed on the reference model: `needs a test` (with its cause, which says which test), `watch`, `reliable`. The score is the Wilson lower bound over lab evidence, called the pessimistic score and shown with the mean and the number of runs; inherited evidence is capped (3 runs, all of it together, and none across a major version) instead of decayed. At the third Y change since the newest full test a skill is `watch` until a full test.
- **Measurement changes** are of three kinds: grader side (lab evidence is discarded), execution side (an epoch for the skills affected), infrastructure (nothing).
- CI fails on what section 5 of the model lists (the bump, the class, the version file, the guard for a declared effect, the validity of evidence, the measurement fingerprint), the one place where that list is kept; never on a score or a band.

Two points were put to the maintainer explicitly, and both were answered yes:

1. **Field evidence never promotes a skill by itself.** It is recorded in the project from the first day and shown in its own columns per model, labelled self-reported; it can demote by a signal counted on the reference model, with a maximum weight per contributor, and after a change of behaviour a skill returns to `reliable` only with lab runs: 3 to 9, the affected cases and the guard cases.
2. **`reliable` requires a pessimistic score of 0.70 or more.** A small skill that has just passed its full test with a marginal mean therefore starts in `watch` (6 of the 48 would, on the records of the first round). "Done" for a new skill remains "its first full test passed".

Why: as first written, the bands were decided by rules with four holes. A guard had to exist and to have run, never to pass; the lowest change class could not be verified and accepted changes of behaviour; any change followed by a test of the failed cases erased their bad runs from the gate; and field evidence, selected and self-reported, entered the same sum as lab evidence and could return a skill to `reliable`. The simpler version closes the four with about half the parts.

Rejected: keeping the numeric decays (0.95, 0.6, 0.2 per change, 0.8 per measurement step), which the data of today cannot calibrate and which barely moved the score of a skill with much evidence; thresholds of 0.50 and 0.45, under which a skill at 0.54 read `reliable`; the conversion of the 48 old records into evidence, which would have weighed nothing, since phase C rewrites the cases and phase B changes what the grader sees; a baseline on the floor model in every full test, which no rule reads; a second grading pass.

What it costs: the first full test of the 48 skills is 1,437 runs and 1,437 gradings for 160 cases (159 base cases and one platform case), 2,394 calls on the strong model's account, about the size of the first round. What every later change costs is in one place, the model's table "What a change costs". A changed step costs 3 to 9 lab runs, where daily use alone would have been enough under the first version; that is the price of the first point above.

Left for later, on purpose: field evidence counting toward a band, once recorded uses can be compared with verdicts; the numeric decays.

The model is in `docs/architecture/reliability-model-2026-10-02.md` and the work in `docs/architecture/final-plan-2026-10-02.md` (removed on 2026-10-14; `git show d3e60770:docs/architecture/final-plan-2026-10-02.md`): the first describes the model, the second the work, and the plan already contains the model's consequences.

## 2026-10-02: Principle 8 is separation, not masking (decision 11 of the final plan, as narrowed)

Decided by the maintainer. The workbench holds no file of a project that uses it and names no such project, its people or its accounts. Real data as such is not the problem: a number, a date, a palette or a measured result that came from a real case may stay in a fixture or in a lesson.

- What identifies a project is replaced: its name, a prefix or path that carries the name, people, handles, hosts, the identifiers of its files in other tools. A name that is already a replacement and names no project that uses the workbench is not replaced again.
- Numbers, dates, schedules, palettes and the figures in a "Gotchas" section stay as they are.
- A file copied whole from a project becomes a fixture that belongs to the test: only what the case needs, under a fictional name.
- No eval case is removed for this.
- One exception to the rule on names: the maintainer's own name and handle where ownership needs them (the license, the code owners file, an adapter's manifest that names its author).

`AGENTS.md` says this in the three places that said numbers go: principle 8, step 7 of "Adding a skill" and the "Never" list.

Rejected: rewriting every such fixture as fiction, numbers and dates included (the largest of them would take a day or more, and baselines would move for no gain: a number identifies nobody); removing the affected cases (two skills would lose their main cases); leaving the fixtures as they are (the repository is public and principle 8 would stay broken).

Why: the first wording of principle 8 asked for "invented numbers", which made a lesson measured on a real case impossible to keep and turned a cleanup of names into a rewrite of whole fixtures. What the principle protects is the project and its people, and they are identified by names, never by a count.

## 2026-10-02: Requirement classes all take the form `<role>:<target>` (decision 14a)

Decided by the maintainer; it reverses the part "requirement classes keep their names" of the entry of 2026-10-02 on the orchestrator. Four classes were bare while the others carried a role: `mailer` becomes `sender:email`, `mailbox` becomes `reader:email`, `scheduler` becomes `scheduler:job`, `store` becomes `store:runtime`. `integration:*`, `search:web`, `generator:*` and `publisher:<platform>` keep their names.

- Only the class names change: in `contracts/environment.md`, in skills' `requires`, in the orchestrator's class table, in `providers/CONTRACT.md`, in the class list of `providers/resolve.py` and in the names the runtime passes to it. The provider folders, the `<CLASS>_PROVIDER` environment variables, the keys of a project's `runtime.json` and every data name stay; the resolver keeps reading the four old names as aliases, so a job scheduled before the rename keeps running. No project migrates anything.
- Two forms of a class: `<role>:<target>` with a fixed target, where the target is part of the class's identity, and `<role>:<parameter>`, where the part after the colon is handed to the provider. Only `publisher:<platform>` has the second form.
- The validator refuses a bare class in a skill's `requires`: a warning first, an error once every skill is edited.

Rejected: moving the provider folders to `providers/<role>/<target>/` (it would drop the provider tests from CI, break the hook's path mapping, each provider's lookup of the secret resolver and the jobs already scheduled, and a skill sees a class name, never a folder); renaming later (after the first full test a rename is a tested change of every skill that names a class).

Why now: every skill is being edited once anyway, so the rename costs nothing in evidence. The work is item C0.2 of `docs/architecture/final-plan-2026-10-02.md` (removed on 2026-10-14; `git show d3e60770:docs/architecture/final-plan-2026-10-02.md`) and the rows of the skills that name a renamed class.

## 2026-10-02: Four design rules in `AGENTS.md` (decision 14b)

Decided by the maintainer. The part of the SOLID principles that holds for text a model interprets, written into `AGENTS.md` as "Design rules":

1. A skill names no harness (principle 1, already enforced).
2. A skill's procedure names no social platform: it declares the class it needs and reads what is specific to a platform from that platform's reference. What a user types in a request may name a platform.
3. Adding a platform adds a reference file, a data file where a script needs one, and a provider where something is executed; it edits no skill's procedure, and only that platform's cases are run. The rule holds for a platform whose post is text with optional media, the shape of the one platform built today. A platform of another shape is expected to edit the skills that build, write and gate a post. A parser of one platform's own format stays as code in its skill, and a table of networks inside a skill gains its rows there.
4. One skill per job: a skill is split only when the part has its own trigger, its own requirements or side effects, or its own artifact. No skill is split before the first full test of the 48.

With them, the rule on product names said once next to principle 1: a third-party product that is not an AI tool may be named where it is what a user types or what the code must recognise; AI tools and generative design tools are replaced by fictional names; a social platform's rules live in its reference and data file.

Not adopted, with the reason: a formal profile contract with declared capabilities, and a validator rule that refuses platform names, wait until a second platform is built, because a contract drawn from one example describes that example. The code host is out of scope: no second host is planned.

## 2026-10-02: Platform references, tested per platform (decision 14c)

Decided by the maintainer.

- `shared/references/platforms/<platform>.md`, one file per social platform, holds what the platform is as a medium: text limits, the media it requires, how links behave, the shape of a post's URL and of its identifiers, what can be read from outside. What belongs to one implementation (credentials, that service's errors, how to call it) stays in the provider.
- A skill's step is literal about where the platform comes from: the `Network:` field of the calendar row or post file the step works on; when there is none, the platform the request names; when neither names one, the skill asks. It then reads that platform's reference, and stops and says the platform is not supported when there is no such file.
- Scripts take `--platform`, and read simple machine data (URL patterns, host names, limits, media types) from `shared/references/platforms/<platform>.json` through a path given by flag (`--platform-file`), never from a table in the skill. A parser that is code for one platform stays in its skill behind `--platform`.
- A platform's cases live in `skills/<name>/evals/platforms/<platform>.json`, outside the skill's content hash. The gate and the score are computed on the base cases only; a platform's cases run with the skill only, as a partial test, and the status shows their mean and number of runs.
- Scope now: the first reference (the one platform built today) and the eight skills that carry its knowledge. References for other platforms are written when each has a real task, never from general knowledge.

Rejected: platform knowledge in each provider (one provider may serve several platforms, and six of the eight skills that need the knowledge declare no publisher); a table of platforms inside each skill (adding a platform would edit every skill and ask for a test of each).

The work is items C0.2 and C0.9 and the skills' rows of `docs/architecture/final-plan-2026-10-02.md` (removed on 2026-10-14; `git show d3e60770:docs/architecture/final-plan-2026-10-02.md`); the inventory of platform knowledge is `docs/architecture/audit-2026-10-02/platform-inventory.md` (removed on 2026-10-14; `git show d3e60770:docs/architecture/audit-2026-10-02/platform-inventory.md`).

## 2026-10-02: Dependency alerts raised by eval fixtures: a standing rule

The code host's dependency graph reads every manifest in the repository, whatever `.github/dependabot.yml` says, so an eval fixture that names real packages raises alerts on packages nothing here ever installs. It has happened twice: 30 alerts from two fixtures of `ops-ci-pipeline`, dismissed by hand on 2026-09-28 (`docs/security/dependabot-triage-2026-09-28.md` (removed on 2026-10-14; `git show d3e60770:docs/security/dependabot-triage-2026-09-28.md`)), and 21 open on 2026-10-02, all from one manifest, `skills/eng-architecture/evals/files/content-model/package.json` (read from the host's alerts API that day). New advisories keep arriving against fixtures that do not change.

Bumping the fixture each time is not the answer. A fixture's manifest is part of its case, so a bump changes the case's hash, which drops that case's lab evidence and asks for a test of the skill, to silence an alert about code that never runs.

The rule, item A14 of `docs/architecture/final-plan-2026-10-02.md` (removed on 2026-10-14; `git show d3e60770:docs/architecture/final-plan-2026-10-02.md`):

1. **Invented packages wherever the case does not need the real ones.** A fixture manifest names packages that exist in no registry, under a fictional scope, as the fixture of `eng-security-review` already does: such a manifest raises no alert at all.
2. **Where the case needs real packages** (the skill must read a real framework's version, or a real tool's configuration), the versions are current on the day the skill's row is written, and **no lockfile that lists real transitive packages is committed**: a lockfile puts hundreds of packages into the dependency graph for one case. A lockfile of invented packages is fine.
3. **An alert a fixture raises later is dismissed**, with the reason "not used" and the comment "a test fixture, never installed". It is not fixed by a bump.
4. **The fixture is bumped only when its skill is next changed** for another reason, in the same pull request, so that the case changes once.

For case authors the rule is repeated in `evals/README.md`, which item C0.7 of the plan creates. The 21 open alerts are handled by the row of `eng-architecture` in phase C, which edits that fixture once; the row of `ops-ci-pipeline` follows point 2 for the lockfile it was going to add.

Whether the host can do point 3 by itself, with an alert rule that dismisses by manifest path under `skills/*/evals/files/`, was to be tried with this change. It was not settled, and this is what is known:

- The host's REST API, read with the command-line tool on 2026-10-02, has no endpoint for alert rules at the two paths tried under `dependabot/` (both answer "Not Found"), so the rule could not be created or tested from a pull request.
- Such a rule is created in the repository's settings page. That is a change of the repository's settings, which is the maintainer's to make, so it was not made here.
- Not verified: whether a custom rule of the host can match on a manifest path at all. If it can, the maintainer adds the rule and records it here; until then point 3 is done by hand, or through `eng-security-review`, whose dismissals sit behind a confirmation gate.

One setting goes with the rule: the host's automatic security-update pull requests stay off for this repository, so that none edits a fixture manifest. Read on 2026-10-02 from the repository's settings through the API: they are disabled.

Rejected: bumping fixtures as alerts arrive (each bump costs the case's evidence); removing the manifests from the fixtures (a project without a manifest is not the small real project a case needs); moving the fixtures out of the repository (the cases must ship with their skill).

## 2026-10-03: measurement version 5 closed

Phase B of the final plan is complete: what a run sees, how it is graded and scored, and the evidence it writes are settled for measurement version 5. Kind: the version and the floor were raised to 5 by the first commit of phase B (a grader-side change: the grader is shown the assistant's last message and a facts block), and every change since, to the image, the staging, the grading, the scoring and the adapters, was made while it was open. This closes it: nothing measured while it was open is evidence, and from this commit on the runner writes evidence under it.

- Measurement version 5, floor 5: every lab line below version 5 weighs nothing, and no line was converted from the 48 old records, which stay as the history of the first round (`skills/<name>/evals/result.json`). All 48 skills read `needs a test`, the intended state before their first full test.
- Fingerprint: `965d9daceaf76c445084882edab65909d6d5dea0c75bdc88853d46bf740bdbde`, over the grading template, `evals/measure.py` and `evals/measurement.json`, the executor and `evals/container/`, `scripts/stage_skills.py`, and the `run-prompt.sh` and `adapter.json` of the two eval adapters. The validator fails when it differs from the files; a later change to one of them is committed with `python3 evals/eval_status.py measurement --kind grader|execution|infrastructure --cause "<why>"`.
- The image: `wb-eval:55d46a74dd9b` (named after the hash of `evals/container/`), platform `linux/arm64`, digest `sha256:4a446f8ae551e20ccca1728602c6fa8ce510b73db4b1fdb17cf87ad21351eb28`. Kept as an archive made with `python3 evals/executor.py archive --out <file>`, sha256 `26073454f11dade40259da6410c7ad040368159db6ffd0712b181b80f46f220c`; the maintainer keeps the archive outside the repository, since two builds of one definition can differ.
- The last change inside the open version: the gate's two comparisons allow for the arithmetic of floats (`FLOAT_SLACK`, 1e-9, in `evals/measure.py`): six runs at 0.8 average 0.7999999999999999, which failed a threshold of 0.8.
- Built in phase B with it: the evidence store, one file per test event; full, partial and platform tests; the version file, the bump command and the version and class checks; guard and format tags and the second grading of a failed guard; the pessimistic score and the three bands, computed by `python3 evals/eval_status.py status`; the two snapshot tables of `docs/inventory.md`, a warning when behind and never an error; the field recorder, `scripts/evidence.py`; and the code owners of the measurement, the evidence, the version files and the old records (`.github/CODEOWNERS`).
- Written by `python3 evals/eval_status.py measurement --close`.

Not yet run, and listed in the pull request that closed the version as the proof run of phase B: the one skill run through the new harness on both tiers with a model, which the plan places before this close. Anything it finds is a change of one of the three kinds, committed with the command above.

## 2026-10-03: The proof run of phase B; the skill-listing measurement taken again; the grading's tokens

The first part of phase D ran on `main` at `cbe3321`: D1, D2, the proof run of phase B on `ops-branch-sync` (a trial of 2 runs per case, no evidence) and the listing measurement of A8 and C0.10. The full record is `docs/architecture/phase-d-proof-2026-10-03.md` (removed on 2026-10-14; `git show d3e60770:docs/architecture/phase-d-proof-2026-10-03.md`). No fingerprinted file changed: measurement version 5 stands, with the same fingerprint.

- **The strong model id.** The pinned CLI accepts `claude-sonnet-5-5`, names it as the model of every run, and gives it a 200,000-token context and 32,000 output tokens. The gate file stays as it is.
- **One grading without tools: 11,622 tokens** on average over 24 gradings (11,013 to 12,032), against 29.6 thousand in the first round. A guard's second grading cost 11,987 tokens.
- **The grader's disagreement on this run:** `--regrade` of the 24 replies changed 2 of 96 verdicts (2.1%), and 1 of the 31 verdicts the first grading failed. This is one skill and one run of the instrument, not D4's measurement on the pilot.
- **The skill-listing measurement, default pack (48 skills, 37,718 characters of descriptions).** Installed by each harness's installer into a scratch home and asked once for its skill list:
  - `claude-code`: 28 of 48 descriptions reached the model, and 20 skills by name only.
  - `agents-dir` (opencode 1.18.32): 48 of 48.

  By decision 9 the harness that cuts the list has a budget setting, so the answer is the installer writing that budget when the person agrees (lane F3), and no description is shortened. Eval runs are not affected, since the strong eval adapter raises the budget (entry of 2026-10-01).
- **An operator error, resolved.** The floor tier's first attempt failed with `401 "User not found."` because the new OpenRouter key had been stored under another name than the store username the floor adapter reads (`openrouter`). Once it was stored under that name, `--resume` ran the 8 floor runs. This was no defect of the instrument. The runner did retry the 401 as an adapter failure, and that is listed with the other defects.
- **Defects found,** each with its smallest fix in the record; none in a fingerprinted file:
  - an authentication failure retried as an adapter failure (`evals/eval_run.py`);
  - `eval_status.py evidence` accepting an event whose `runs` differs from the configured number;
  - `ops-branch-sync` case 4, whose standing approval cannot be reached with `gh` signed out (a case defect, for the smoke pass);
  - `--regrade` and `--resume` resolving a relative path against the caller's folder before the repository.

## 2026-10-03: measurement change, grader (measurement version 5 to 6)

The grader writes its evidence before its verdict, ends it on Passes. or Fails:, and fails an absence or a strict reading only on what the assertion states; an answer whose verdict contradicts its own evidence is refused and graded again (the smoke pass of phase D: six verdicts contradicted their evidence and three answers appended a correction).

- Kind: grader side: what the grader is shown, the grading rules or the scoring changed. The measurement version and the floor are raised: every lab line below the floor weighs nothing, and every skill needs a full test.
- Measurement version and floor: 6.
- Fingerprint: `03c1199923074eb689e8d10366e76b421464dac7fe1632601e2db794f448e6bf`.
- Written by `python3 evals/eval_status.py measurement --kind grader`.

The maintainer decided on 2026-10-03 to fix the grader now, knowing that it is a grader-side change. The cause was read in the stored run folders of the smoke pass (`docs/architecture/phase-d-smoke-2026-10-03.md` (removed on 2026-10-14; `git show d3e60770:docs/architecture/phase-d-smoke-2026-10-03.md`)): the nine grader verdicts it classed as harness defects, the three answers it refused for their form, and all 2,562 verdicts of the 557 stored gradings.

- **The common cause: the verdict came before the evidence.** The template's answer form was `{"id", "passed", "evidence"}`, so the grader committed to a verdict and then reasoned inside the evidence. Where that reasoning turned, the verdict could not follow it:
  - 6 verdicts of `false` whose evidence ends on a pass: "..., so this should pass" (4), "..., so on a literal reading this should pass", "..., so this part holds". Four are those the report names (`brand-voice` 2, `core-skill-creator` 2 twice, `core-project-init` 2); two more were found in the scan (a guard run of `eng-security-review` 2 and a second grading of `ops-ci-pipeline` 1).
  - The 3 answers refused for their form are the same event: each wrote a "Correction" after its array ("I wrote contradictory evidence above"), which made the JSON unreadable.
- **A second cause, in the rules: the doubt of rule 2 applied to requirements the assertion does not state.** "No benefit of the doubt" was read as "fail under a strict reading": whether a quoted line was really copied (`core-skill-creator` 2), whether a label is tied to the skill's sets (`core-critique` 2), whether more than `ok` is shown (`mkt-social-copy` 1), whether the reason an ADR gives is consistent (`eng-tradeoffs` 2). And an assertion stated as an absence was failed on what is near the thing it rules out: a recommendation followed by a fresh yes/no read as an approval (`eng-security-review` 4), the facts given as the reason for a recommendation read as an impact analysis (`eng-impact-analysis` 3).
- **The fix, in the grading template:** rule 12, the evidence first and a last sentence "Passes." or "Fails: <the part that is not shown>.", with the verdict that follows it and no correction after the array; rule 13, the answer's form with the evidence before the verdict; rule 6, an assertion stated as an absence fails only on a passage that is the thing in the assertion's own words; rules 2, 3 and 4, the doubt that fails an assertion is about what it states, a strict reading that adds a requirement is not a reason to fail, and whether a quoted line was copied is not judged. The other rules keep their words; rules 6 to 11 are renumbered 7 to 12.
- **The fix, in the reading of the answer (`evals/measure.py`):** `conclusion()` reads what an evidence concludes in the grader's own words (the closing sentence, or a final clause such as "so this should pass" or "so the assertion fails", quoted output removed), and `read_grading()` refuses an answer in which a verdict disagrees with it, so that it is graded again, up to the retries a refused answer already had. Over the 2,562 stored verdicts it flags the 6 contradictions above and nothing else.
- **What it costs:** the floor is 6, so the guard evidence the smoke pass committed (9 files) weighs nothing, as the maintainer accepted; every skill needs a full test, which none had passed.

## 2026-10-03: The `claude-code` installer sets the skill-listing budget the pack needs, when asked (decision 9, lane F3)

The phase D measurement found 28 of the default pack's 48 descriptions reaching the model through the `claude-code` installer. The installer now computes the budget the pack needs and prints it with the line to add and its file; it writes the value only with `--listing-budget write`, into the project's `.claude/settings.json` by default (`--settings-scope local` or `user` to choose another file; the home-level file only when named), merging it with every other key, refusing a file it cannot parse, keeping a backup and never lowering a larger value; `--uninstall` puts back what it wrote while the value is still its own. The setting is `SLASH_COMMAND_TOOL_CHAR_BUDGET` in the `env` object, because the eval adapter's use of it is the only source the repository has. The budget is the pack's listing plus a quarter of it, at least 10,000 characters, for what the harness lists before the pack (an assumption: nothing in the repository measures that part), rounded up to 1,000: 50,000 for `default` and `all` today, against 200,000 in the eval runs. Rejected: shortening descriptions (decision 9), a fixed large value (it would hide a pack that outgrows it), and writing by default (a settings file is the person's). Not a measurement change: neither `install.sh` nor the new `listing_budget.py` is in the fingerprint, and `run-prompt.sh` is unchanged. Whether every description now reaches the model is a model call left to the maintainer: the command is in `adapters/claude-code/README.md`.

## 2026-10-04: measurement change, execution (measurement version 6 to 7)

The floor model's provider key moves out of the run container into a key proxy beside the egress proxy (lane F7, brought forward): a floor run gets a placeholder key and the proxy's base URL, its runner calls the proxy, and its web cases run on the eval's own open network; the strong tier's runs are unchanged.

- Kind: execution side: the image, an adapter, the runner's prompt or tools, the executor, the staging, or a hosted model under its id changed. The measurement version is raised and an epoch is entered: for the skills and models it reaches, earlier lab lines are inherited evidence and the baselines expire.
- Epoch 2026-10-04: skills all; models openrouter/deepseek/deepseek-v4.1-flash.
- Fingerprint: `44716ae7029a0e4442e346befba1252ca63a8e10cc18a1bbb9e1f0b60969cf07`.
- Written by `python3 evals/eval_status.py measurement --kind execution`.

Decided by the maintainer on 2026-10-03, who asked to bring the credential half of lane F7 forward. Twice in phase D (the smoke pass, `core-research` 3; the rerun, `eng-security-review` 3) the floor model ran `env` in the container and printed its own key into its transcript. The runner replaced the value in everything stored (B6a), but the value had reached the model's context.

- **What was built.** `evals/container/keyproxy/`: a reverse proxy in the Python standard library, in an image of its own on the pinned base of the egress proxy. The executor starts it with the key in its environment (passed by name, never on a command line), on the internal network and on a new open network of the eval's own (`wb-eval-open-<hash>`), with no published port and no restart policy; a label holds a hash of what it was started with, so a key stored again replaces it. It answers plain HTTP for `/api/v1/` only, forwards to `https://openrouter.ai` only, through the egress proxy's CONNECT tunnel (so the allow list still applies), drops any Authorization a run sends and adds its own, never routes by the Host header, refuses another path, an absolute URL, a dot segment and CONNECT, uses the egress proxy's timeout (600 s), streams the answer as it arrives, and logs one line per call with no header. Its route (`keyproxy.json`) is the one home of the variable it holds, the placeholder and the base-URL variable.
- **How the floor runner is pointed at it.** A command passed `OPENROUTER_API_KEY` gets `OPENROUTER_API_KEY=held-by-the-eval-key-proxy` and `OPENROUTER_BASE_URL=http://wb-eval-keys-<hash>:8890/api/v1`, and the key proxy's name is added to `NO_PROXY`. The floor adapter writes `provider.openrouter.options.baseURL` into the throwaway home's `opencode.json` when the model id is `openrouter/...` and the variable is set. Read in the binary of OpenCode 1.18.32 that the image ships: the provider's options carry `baseURL` to the OpenRouter SDK, whose calls go to `<baseURL>/chat/completions` with `Bearer <OPENROUTER_API_KEY>`. A docker test runs that binary through the adapter against a stand-in provider and gets the stand-in's streamed reply.
- **What it reaches.** The floor model only: the run image is byte-identical (the same image id, `sha256:4a446f8ae551...`; the definition's hash, and so the image's tag, changed), and a strong-tier command's arguments are unchanged, its web cases staying on the default network. Hence the epoch names the floor model and every skill. Of the nine skills with committed evidence (all guard runs of measurement version 6), eight have floor lines that become inherited (counted as at most 3 runs each): `design-execute`, `design-system`, `eng-security-review`, `mkt-engage`, `mkt-publish`, `ops-branch-sync`, `ops-pull-request`, `product-backlog`; the ninth, `ops-ci-pipeline`, has lines of version 1.1.0 that already weigh nothing under its version 2.0.0. No strong-tier line and no baseline moves.
- **Why the epoch is dated 2026-10-04.** An epoch reaches a line dated before it, by the day. The nine files are dated 2026-10-03, the day this was built, so an epoch dated that day would leave their floor lines current although they ran with the key in the run. If this merges after 2026-10-04, floor evidence written between that date and the merge would count as current under the old route: rewrite the epoch's date to the merge date before merging.
- **What it does not do.** A model can still spend the key through the proxy (any container on the eval networks can reach it, the strong tier's too), so the credit limit on the key stays the cap. The strong tier's credential (the account token, or the low-limit key of a web case) still enters its runs; the same pattern would need a proxy for the strong provider's API host and a runner that takes a base URL and a placeholder token for it, which the adapter of that tier has not been checked for. `DEEPSEEK_API_KEY` (a floor model id `deepseek/<model>`) is not held. The redaction by value stays, as a second line.

## 2026-10-04: measurement version 8 closed

Measurement version 8: the strong model's credential is held by a key proxy, the floor model's provider is pinned, each eval adapter's eval block has a file of its own, and a full test runs one baseline per case.

- Measurement version 8, floor 6: nothing measured while it was open is evidence; from this commit on the runner writes evidence under it.
- Fingerprint: `8bb39f491b1ce77640e74597e8d61bf94b29005c5ae60285fcb885a5883a9edc`.
- Written by `python3 evals/eval_status.py measurement --close`.
- Kind of change: execution side (the container's definition, the executor and the eval adapters changed; the grading template, `evals/measure.py` and `evals/measurement.json` did not).
- Epoch: 2026-10-04, all models, all skills: the strong model's credential moves into a key proxy of its own, and the floor model's calls are pinned to one upstream provider (`deepinfra`) by its key proxy.
- The floor model's provider is `deepinfra`, not DeepSeek's own endpoint as first decided: the OpenRouter account's data policy excludes that endpoint ("0 endpoints out of 1 requested are available matching your guardrail restrictions and data policy"). Changing to `deepseek` is one value in `evals/container/keyproxy/keyproxy.json` and, once evidence exists, an epoch for the floor model.
- Image digest: `sha256:4a446f8ae551e20ccca1728602c6fa8ce510b73db4b1fdb17cf87ad21351eb28` (`python3 evals/executor.py ensure`), unchanged; the run image is tagged under the new definition hash.
- Pull requests: #98 (version 8 opened, `baseline_runs` and `baseline_margin`), #102 (the floor provider pin), #103 (the eval block in `eval.json`), #104 (`cost_usd`, `run_sha256`, `upstream`), #105 (the strong model's key proxy), #101 (the gate: one baseline run, a changed case as a new case, the means per case); the cases #99 and #100.

## 2026-10-04: the time limit of a run is 1800 seconds

Before any evidence under measurement version 8, `timeout_seconds` of `evals/eval-gate.json` goes from 900 to 1800. In the rehearsal of the battery a web case of the reference model was stopped twice at 900 seconds and finished on its third attempt in 860 seconds, and a floor web run took 798: at 900 seconds the slow web runs are the ones that time out, are made again (spending the account on attempts that are thrown away) and, after the retries and resumptions, are written with score 0, so the evidence would keep the runs fast enough to finish. The limit is a control of the event, outside the measurement fingerprint; every event of the battery runs under the same value, and the committed evidence (all of it inherited, from 2026-10-03) is not touched.

## 2026-10-04: measurement change, infrastructure

The strong model's account-limit markers match what the pinned command-line tool prints at the limit ("You've hit your session limit", the weekly limit, spent credits) and the 429 of its result: none of the earlier markers matched, so the runner would not have paused.

- Kind: infrastructure: locks, resumption, retries, pacing or reports changed in a file the fingerprint covers. No version is raised; the new fingerprint is committed with the reason.
- Fingerprint: `2f141c251a98cc004c55c72acc9064596934ffe13de387c3d75fb1853783531d`.
- Written by `python3 evals/eval_status.py measurement --kind infrastructure`.
- Found by the fourth independent review before the battery: 23 real runs of 2026-09-29 that met the limit left the reply "You've hit your session limit · resets …", `api_error_status` 429 and exit code 1, and none of the four earlier markers is in that text (the pause of phase D was proven with a stand-in that printed "hit your limit"). Without the new markers every run at the limit would fail as an adapter failure, be retried into the limit and, after the resumptions, be written with score 0. Test: `evals/tests/test_account_limit_markers.py`.

## 2026-10-04: measurement change, infrastructure

The 429 marker of the strong model's account limit takes the form the adapter writes to raw.json (a space after the colon), and the marker "You've hit your" covers every limit message the pinned command-line tool builds (a Sonnet, Opus, usage or spend limit as well as the session and weekly ones).

- Kind: infrastructure: locks, resumption, retries, pacing or reports changed in a file the fingerprint covers. No version is raised; the new fingerprint is committed with the reason.
- Fingerprint: `b628afd5ab52f0e416a52719c885c647d81639c05fd8daf9d72539f5299cf01d`.
- Written by `python3 evals/eval_status.py measurement --kind infrastructure`.
- Found by the fifth independent review before the battery: the 429 marker added by #112 was written compact, as the old adapter left `raw.json`, while the current adapter writes it with `json.dump` (`"api_error_status": 429`), so it never matched; the session and weekly texts did. Re-serialized as the current adapter writes them, the real limit runs of 2026-09-29 that kept a `raw.json` (5) now match through `raw.json` alone. Every limit message of the pinned tool starts "You've hit your" (session, weekly, Sonnet, Opus, usage, monthly spend, team budget), and that text is now a marker.

## 2026-10-04: fourteen model runs at a time during the battery

`total_jobs` of `evals/eval-gate.json` goes from 10 to 14, at the maintainer's request to run more in parallel and use the whole limit of the account. It is the number of model runs in progress at one time over every runner process of the machine: a pace, outside the measurement fingerprint, and not recorded in an evidence line or compared by the validator, so the evidence of wave 1 and of the first group of wave 2 (made at 10) and of the groups after it (made at 14) are measured alike. Wave 1 used about 14 points of the 5-hour window per hour at 10 runs, about 70 of each window; 14 runs uses about the whole window. The open network keeps its own limit (`web_jobs`, 2 per tier). A run is never lost to the limit: the runner pauses on the account-limit texts, and during the battery a watchdog writes the runner's own pause file, with the window's reset as its end, when the 5-hour window reaches 88% or the week 95%, so that the calls in flight finish and no new one starts. This merges into `evals/` during the battery, which section 12.1 of the execution plan freezes for changes to what a run measures; this one changes the pace only.

## 2026-10-04: the first full test of the 48 skills, closed

The battery of T21 is closed: every one of the 48 skills has a full test under measurement version 8 that passes the gate, and a band on each model.

- Commit: `811b485` (the evidence of the battery and its repairs merged; the band and model tables of `docs/inventory.md` are generated at it).
- Measurement version 8, floor 6, fingerprint `b628afd5ab52f0e416a52719c885c647d81639c05fd8daf9d72539f5299cf01d`; every event of the battery ran under it.
- Image digest: `sha256:4a446f8ae551e20ccca1728602c6fa8ce510b73db4b1fdb17cf87ad21351eb28`.
- Reference model `claude-sonnet-5-5`; floor model `openrouter/deepseek/deepseek-v4.1-flash`, pinned to `deepinfra`.
- The run folders (`evals-workspace/`, 967 MB, 3,360 run streams) are archived outside the repository as one file, `battery-runs-2026-10-04-final.tar.gz`, sha256 `74ed34ba6a18f3bd749b531390ac43ba87e47c3e057f8df5d4a3e96e02b197bc`, inspected only in a copy (T26).
- Order: the routing pass of the 48 (no description collision); wave 1, the five skills of the pilot, and its reading (`docs/architecture/battery-wave-1-2026-10-04.md` (removed on 2026-10-14; `git show d3e60770:docs/architecture/battery-wave-1-2026-10-04.md`): no stop condition, 20 gradings read with none wrong, 1.4% of the grader's verdicts differing on a second grading); wave 2, the other 43.
- Repairs on the reference model, each a change followed by the test its class asks for: `flow-fix-bug` 1.2.0 (#115, a full test), `core-security-audit` case 2 (#119), `ops-repo-baseline` case 1 (#121), `core-orchestrator` 2.2.0 (#120, a full test).
- **Reference model: 48 `reliable`, 0 `watch`, 0 `needs a test`.**
- **Floor model, by the same rules, information only: 43 `reliable`, 1 `watch`, 4 `needs a test`; the gate passes on the floor model for all 48.** After the per-model display (#123) the floor model's gaps were run (more runs of four skills, two missing floor baselines) and two of its guard failures were repaired: `mkt-engage` 1.2.0 (#125) and `ops-ci-pipeline` case 1 (#124), both `reliable` on both models after their tests (#126). The floor model's skills that are not `reliable`, each with its cause:
  - `core-skill-creator`, `needs a test`: guard 2.6 failed in 1 of 3 runs (a required line of the output template left out).
  - `design-ux-flows`, `needs a test`: guard 1.5 failed in 1 of 3 runs, a run in which the model's tool calls collapsed into a loop of its raw call syntax until the output limit (see T27).
  - `eng-codebase-map`, `needs a test`: guard 1.5 failed in 1 of 3 runs (a word the case forbids, "should", in the output).
  - `mkt-social-copy`, `needs a test`: guard 2.3 failed in 1 of 6 runs (the money figure and the employer were left out, as the guard asks, but no measured source was asked for).
  - `eng-docs`, `watch`: the pessimistic score 0.68 is under 0.70 (mean 0.85, 12 runs).

  Each is a lapse of the floor model in one run that the reference model does not show; none is repaired, because a repair is a change of the skill that the reference model must pass again, and the floor model's band decides nothing (T28).
- Cost: the battery used about 14 points of the reference model's weekly limit (35% before wave 1, 49% after the last repair) and US$6.44 of the floor model's key on the day of the battery, its rehearsal included.
- Alternatives rejected: repairing the five floor-model findings now, which would cost a test of each changed skill on the reference model for a band that decides nothing; leaving the floor model's gaps unrun, which would have left six skills outside `reliable` on the floor model for want of runs rather than for a failure.

## 2026-10-07: the architecture fixes, and eight decisions they rest on

The review of 2026-10-06 (`docs/architecture/platform/review-2026-10-06.md` (removed on 2026-10-14; `git show d3e60770:docs/architecture/platform/review-2026-10-06.md`)) found seventeen gaps between the layers and the goal of replaceable pieces; nine are fixed, one is partly fixed and seven wait for the next change of their layer (principle 12). The decisions taken to fix them:

- D1. `evals/run_attempts.py` stays outside the measurement fingerprint, because retries, locks and pacing are infrastructure in the repository's taxonomy; the review's point is answered by the extraction of the execution kit, and no fingerprinted file changed.
- D2. The store's task functions are the runtime's own persistence (finding 7, the first option): no conformance suite and no second backend are promised, and `providers/CONTRACT.md` says so.
- D3. The runtime's wiring to named skills (router, brief, sub-task skill, code areas, packs in use) is one data file of the runtime, `runtime/roles.json`, bound to the skills by a test, not a key in every manifest.
- D4. A skill outside the packs in use may carry a partial manifest, with only the keys it needs; a skill in a pack in use keeps the whole manifest, and the runtime refuses to run a skill without a whole one.
- D5. Skill code the runtime runs on the host runs as an isolated subprocess with a scrubbed environment; the container is the stronger option and stays open in the review.
- D6. The effect registry is keyed by the side-effect word the skill's manifest names in its gate; a second shape for one word adds a `kind` key later.
- D7. The effects by kind were built with the one kind, before the second kind arrives, so that the code and its tests are fresh; it was the first package to drop if the budget ran short.
- D8. A chat channel cannot approve an effect: an effect is approved only from the terminal, with its hash, and the channel rule is a column of the operations table.

Rejected: a `role` key in every manifest (D3), running skill code in the container now (D5), and a fingerprint change for the retry rule (D1). The cost was no battery: no skill's content and no measurement file changed.

## 2026-10-07: the page is a channel of its own

Decision D8 (a chat channel cannot approve an effect) is extended, not changed: an effect is approved from the terminal or from the local page, both with the hash of the content the person was shown and typed or clicked; a chat channel (the conversation, a messaging app) and the MCP channel never approve an effect.

- Why the page is not a chat channel. In the terminal the person types the hash; on the page the card draws the exact content and its `payload_sha256` and the click sends that hash. In both, the person reads the content on their own machine, and the operations layer compares the hash with the effect's file before it executes anything (limits L15 to L17, unchanged). A message in a chat channel passes through a service the workbench does not control, and a model's reply could be made to look like an approval; that is the surface D8 refuses.
- How it is kept in code. `ops.approve` takes the channel from the table of operations (`channel_arg`) and refuses an effect unless the channel is in `ops.EFFECT_CHANNELS` (`terminal`, `page`); the rule still fails closed on any other channel and on none. The terminal shell passes `terminal`, the conversation passes `chat`, and the local service passes `page` itself: a request cannot name a channel. The word stays `approved`, for an effect and a plan.
- What the page does not give. The token and the checks of `Host` and `Origin` keep another page and another machine from sending a hash; they cannot tell a click from a script that holds the token on the person's own machine. `accept-config` is not a route: a configuration is accepted in the terminal only, so a page can never accept the change that widens what an agent may do. The page offers an effect only `approved` and `rejected`; the store's third word for an effect, a comment that sends the task back (`answered`), stays an operation of the terminal.
- Alternatives rejected: approving from the page without the hash (a click would then approve content it did not display); keeping every approval of an effect in the terminal (the stage's acceptance asks for a run from the page without it); a separate token for approvals (a second secret to paste, with the same trust in the machine).

## 2026-10-08: a model client approves nothing

The MCP channel (`mcp`, runtime/mcp.py) is extended from decision D8 and the 2026-10-07 entry above, and is stricter than the conversation's `chat`: on `mcp` a model client may read, request, route, answer, release a draft and say, and nothing else. No approve of any kind (a plan, an acceptance or an effect), no reject, cancel or retry, neither as a tool nor typed into `say`.

- Why. A model client must not authorise runs on its own request chain: if it could approve the plan it asked for, one prompt could request, plan, approve and run without the person. Approving a plan or accepting a delivery is that authorisation, so it is made where the person is, in the terminal or on the page; an effect also needs the hash of its content there.
- How it is kept in code. The `approve` row does not list `mcp`, so there is no tool. The row of `say` takes the channel (`channel_arg`); every shell passes its own (the terminal `terminal`, the service `page`, the MCP shell `mcp`, the conversation none, which is `chat`) and `ops.say` does a command of a line only when that command's row lists the channel that carries it, otherwise it answers `/<command> is done in the terminal or on the page`. A command that runs is still run as `chat`, so an effect stays refused by `ops.approve`. The terminal and the page keep every command they had.
- Alternatives rejected: a table of commands a channel may type kept in the MCP shell (a second copy of the channel rule); refusing only effects (a plan approved by the client starts runs).

## 2026-10-08: one kit for the local service and the MCP mode (WP-9.9)

The MCP mode was written as a copy of the local service's job registry, project id, project list, status words and argument kinds because the layer map let a shell import `ops.py` only. They are now defined once in `runtime/shell_kit.py`, which the two shells import.

- Why a module and not the operations layer. The registry is threads, locks and a shell's own slots, not an operation; putting it in `ops.py` (3000 lines, every operation once) would make the layer that every shell calls hold shell state, and its stand-ins in the tests would have to grow with it. A module of its own changes the layer map by two rows and no operation.
- How it is kept in code. The layer map gives `runtime/service.py` and `runtime/mcp.py` an arrow to `runtime/shell_kit.py` and the kit none to anything in `runtime/`; `cli.py` and `chat.py` keep one arrow, to `ops.py`. The kit is handed the operations object, so a test's stand-in reaches it as before. `runtime/tests/test_shell_kit.py` fails when a shared name is defined in a second module.
- Behaviour unchanged. The request rules of the service and the channel of the MCP mode stay in their shells.

## 2026-10-09: the page may narrow autonomy, and the service dispatches by default (WP-9.14)

Two decisions of the maintainer, taken while running a real project through the page.

- The page may narrow autonomy and never widen it. `set-mode` to a mode lower in the order stopped < supervised < milestones < autonomous < autonomous-with-policy widens nothing, so code accepts the new hash at once (`code:narrowing` in the cursor `config:accepted-by`); a move up, and every other change of the configuration, stays unaccepted until the person types `accept-config`. Why: a page that could change a mode but left every route refusing until a terminal command ran made the page's own control useless, and the hard limit (a change that gives an agent more power is accepted by the person) is untouched. How it is kept in code: one function writes the accepted hash (`ops._record_acceptance`), the narrowing branch is the only call besides `accept_config`, and a test over every pair of modes and a test of the call graph fail on a widening accepted by code.
- The local service dispatches by default, every 30 seconds (`--no-dispatch` turns it off), as far as the modes and the daily caps allow. It replaces the decision of 2026-10-07 that the service dispatches only when asked. A ready task that does not start has a recorded reason (`status` carries `held`), the service checks the secret store, the credential, docker and the eval image at its start and says what is missing, and every sentence that names a command gives it absolute and with the `uv run --with keyring==25.7.0` prefix when the process was started that way.
- Alternatives rejected: accepting a narrowing by calling `accept_config` from `set_mode` (it would blur who accepted); a new table for the held tasks (a migration for a record of the last round, when a cursor holds it).

## 2026-10-11: one terminal command sets a wider mode and accepts it (R4-C3)

The maintainer's word, after running a real project through the page: the command the Agent tab copies for a wider mode must work in one step. Before, `set-mode` left the new hash unaccepted, the page then showed the band "not accepted yet" with an `accept-config` command, and a person who did not see that second step ran `set-mode` again.

- `set-mode --accept` (terminal only) sets the mode and accepts the hash it makes in the same locked step, recorded `by: "person"` as `accept-config` records it. The one condition, checked under the configuration lock: the configuration's hash was the accepted one before the change, so the only difference accepted is the mode the command names. Any other state is refused and nothing is written; the person reads the file and runs `accept-config`. A narrowing with `--accept` is accepted by code as before (`code:narrowing`).
- The rule it keeps (principle 11): a change that widens what an agent may do is accepted only by the person, in the terminal. `accept` is refused by the operation from every channel but `terminal` (code, before anything is read), the service's route takes `mode` only (a body with `accept` is a 400), and the conversation and the MCP mode have no `set-mode`. A page can never accept or widen anything.
- The 2026-10-09 entry above names `ops._record_acceptance`; that function, the one writer of the accepted hash, now lives in `ops_config.py`, still private to it, and a test fails on any call to it from another module.
- The wider-mode commands the page shows (`wider` of `agents`) carry `--accept`, so Copy gives one command that works.
- Alternatives rejected: a confirmation field on the page's route (a page would then accept a widening); accepting whatever hash the file has at the time of the command (it would accept an edit nobody read, which is what `accept-config`'s typed hash exists to prevent).

## 2026-10-12: tasks of a project run in parallel, bounded by slots and by the artifact contract (PAR-0)

The maintainer's word: the project is meant to work as the areas of a company, so working in parallel is essential; the rule "one task at a time, per project" no longer applies.

- Several tasks of one project run at once. Each area agent has `max_parallel` slots (default 1, at most `MAX_PARALLEL_CEILING`, 4 for this release, the one constant in `runtime/autonomy.py`) and the project has `max_running` (default 3); the router's run counts in neither. A task holds its agent's slot while it runs, waits for the person, or is about to run again after the person answered it; a failed or blocked task frees it, and a retried task queues like a new one.
- Two tasks run at once only when their footprints do not overlap: the `outputs` and `updates` of their skills, the state file excepted (it is merged line by line); a path with a placeholder is a wildcard. Two code tasks of one request never run at once. The rule is code (`runtime/parallel.py`), checked under a claim lock with the reservation of the daily caps, so two processes cannot pass the same check.
- Every task run is its own process (`run-task`), because the lab's session ends every container of its process. The scheduled dispatcher waits for the runs it starts (systemd kills what a job leaves) and the local service starts them and returns; the project's run lock is replaced by a lock per task (its liveness), a lock for the router, a claim lock, a write lock around every write into the project and every effect, and a lock per dispatch round.
- The deliveries of one request are ordered by the artifact contract, no longer chained one after the other.
- Unchanged: an effect runs only after the approval of its exact hash, by code, under a lock; a run never writes over a project file that changed since its copy (L12); the daily caps hold, and count the runs in progress.
- Alternatives rejected: one lane per floor with no contract check (a conflict found only at the return, after the run was paid for); threads in one process (the lab's state is process-wide); a dispatcher that always waits for its runs (the local service would dispatch its projects one after another); two code tasks of one request at once (needs a merge of change sets).

## Messaging channels (2026-10-11 to 2026-10-13)

A person can run projects from a messaging app they already use: Telegram, Discord and three kinds of WhatsApp (an unofficial linked-device client built from source, the official Cloud API, and WhatsApp through Twilio). It is a shell of the operations layer, `runtime/messaging.py`, with a channel of its own, `messaging`, and no model between the app and the operations: decisions that wait arrive as platform-neutral cards, a tap or a typed command is bound to the card the person saw, and a free line goes to the planning agent. Each platform is a provider of the class `messenger:<platform>` (`providers/messenger/`), reached through `providers/resolve.py`; a platform that must stay connected runs in a long-lived `listen` mode, and adding one adds a file. Decision D8 is unchanged: an effect is approved only in the terminal or on the page, with its hash, and a card for one carries the exact command and no button. A plan is approved from a messaging app only with its hash, and an acceptance only if its card still matches. A channel policy narrows the ceiling of the table, by named groups in `runtime.json`, for the page, the MCP mode and messaging (messaging is closed by default: read, talk, answer; the terminal and the conversation are never narrowed; cancel and a move down of an agent's mode are never withheld from the page). `service.py --messaging <platform>` starts the bridge as a child of the service.

- Why. The people who run a project need to hear that a decision waits and to answer it away from the keyboard, on a surface they do not have to learn. No model in between because a model can be argued into acting by text it reads; the policy is code in the operations layer, run by every shell, because a prompt cannot be a limit (principle 11).
- The platforms, and what was chosen on purpose. The unofficial WhatsApp client is built from source and pinned by `go.sum` rather than downloaded, on a separate number, with its GPL-3.0 dependency accepted on the condition that no built binary is distributed; Discord's `websockets` dependency is hash-locked. The official WhatsApp providers accept any public HTTPS address and name no tunnel as required, with a table of who can read the traffic for each option. A Twilio number is reached with a restricted API key for sending and the Auth Token only for the signature.
- State. A per-user state folder (`~/.local/state/openhora/`, mode 0700 and checked) holds the bridge's lock (one bridge per platform and user) and ledger (no project text); the ledger moved there from a project's data folder and is migrated once.
- Alternatives rejected: a model-run gateway as the bridge (it keeps its route, outside the core, for people who already run one); the page on a phone as the main path (the person wants apps they already use, not a web UI to learn); approving effects from a messaging app (a later, opt-in decision, not built); a catch-up of messages lost while the machine sleeps on the Twilio path (documented as a limit); card buttons on Twilio without a tested template path (typed commands until the person records three template ids).
- Not tested live: the Meta-direct WhatsApp path, card buttons on Twilio, and the second published Twilio signature vector. The Twilio WhatsApp path passed the maintainer's live test.
- The full account is [docs/architecture/platform/messaging.md](architecture/platform/messaging.md): the decisions M-1 to M-37 with their dates, the architecture, the policy, the interface, the five platforms, the security model, a runbook and the open items.

## 2026-10-15: measurement change, execution (measurement version 8 to 9)

SEC and P2b: a held run reaches only its own key proxy; the key proxy drops credential headers and forwards only the model endpoints; P2b adds a key proxy per run and model, metering and the platform per line (one epoch for both)

- Kind: execution side: the image, an adapter, the runner's prompt or tools, the executor, the staging, or a hosted model under its id changed. The measurement version is raised and an epoch is entered: for the skills and models it reaches, earlier lab lines are inherited evidence and the baselines expire.
- Epoch 2026-10-15: skills all; models all.
- Fingerprint at the commit that opened the version: `fdbdf38ed2600bafbfa412d0fa945a4e74ec9c6c9c13f8b612f7dccb6f37c6d6` (P2b's `--close` writes the final one).
- Written by `python3 evals/eval_status.py measurement --kind execution`.
- What the SEC part changed: a run whose credential a key proxy holds goes on its route's held network (`wb-eval-held-<tag>`, `wb-eval-strong-held-<tag>`, internal, the egress proxy never on it) with no proxy variable, where before it shared the egress proxy's network and could reach a provider with a credential of its own; the key proxy drops every request header that can carry a credential (an explicit list and a name pattern that leaves session ids and idempotency keys alone, which the measured runners send on every call) and forwards only the route's model endpoints; the floor key proxy has a network of its own with the egress proxy (`wb-eval-keys-net-<tag>`), like the strong one, so a run without a held key cannot call it. A run that holds no key, and a web run, are built exactly as before. Also in this version: two comments of `evals/measure.py` now point to git history for documents removed on 2026-10-14.
- The version stays open (no `measurement_sha256`) until P2b closes it with `--close`; nothing is measured in between.

## 2026-10-15: measurement version 9 closed

SEC and P2b: a held run reaches only its own per-run key proxy, which serves one model, drops credential headers, forwards only the model endpoints, meters the tokens and stops at a per-run budget; route by provider and pin by model from the gate file; CPU platform on each run line

- Measurement version 9, floor 6: nothing measured while it was open is evidence; from this commit on the runner writes evidence under it.
- Fingerprint: `0a5d8f7875c1a0829b1db736d245d8ec4d827f92c65aa3d1e3869d3b6560d319`.
- Written by `python3 evals/eval_status.py measurement --close`.
- What the P2b part changed: each run gets a key proxy and an internal network of its own (`wb-eval-keys-<run id>`, `wb-eval-held-<run id>`), started with the one model of the run, its pin, the model names its runner sends and its token budget, all read from the gate file's entry of the model (`route`, `provider_pin`, `upstream_models`, `run_token_budget`); the route files describe providers (`route-openrouter.json`, `route-anthropic.json`) and name no model and no pin. The key proxy refuses a request that names another model, meters the tokens of every response by the four kinds and stops answering at the budget; the count is left in `outputs/meter.json` and the runtime prices a run from it. The event line names the `upstream` of every model that ran through a proxy, a run line records its `cpu_platform` (linux/arm64 and linux/amd64 both count), and the image's `image_source` is recorded. Every container carries the labels `wb.eval=1` and `wb.eval.run=<run id>`, and the long-lived ones a log limit. `evals/image-lock.json` names the published image of a definition; `ensure` never pulls or builds it.
- Decided with the maintainer's supervisor the same day: `upstream_models` is the run's model plus the small model its pinned runner uses for side calls (floor: `google/gemini-3.8-flash`, observed; reference: `claude-haiku-4-5` and `claude-haiku-4-5-20251001`, found in the pinned binary and not observed), so that the request each runner sends is unchanged; the key proxy sets the upstream `Accept-Encoding` to `gzip, deflate, identity` (the one non-credential header it changes) so that no response is unreadable for metering; the gate entries' `price_source` is the source `adapters/api/prices.json` records, with no price in the gate file; `run_token_budget` is 5,000,000, above 3 times the largest `total_tokens` (1,600,052) in the recorded run reports.
- The golden recording (`evals/tests/goldens/`): the request each pinned runner sends through the key proxy of commit cd161411 and through the final one is identical, except that `Accept-Encoding` is rewritten; neither runner sends a header the SEC change removes.

Measurement version 9 was reopened on 2026-10-15 for the review fixes of P2b; nothing was measured while it was open. It is closed again by the last commit of that pull request.

## 2026-10-15: measurement version 9 closed (again, after the review fixes of P2b)

SEC and P2b (with the review fixes): a held run reaches only its own per-run key proxy, which serves one model, drops credential headers, forwards only the model endpoints, meters the tokens (also after a hang-up, failing closed) and stops at a per-run budget with reservations; route by provider and pin by model from the gate file; CPU platform on each run line, emulated platforms are trials

- Measurement version 9, floor 6: nothing was measured while it was open; from this commit on the runner writes evidence under it.
- Fingerprint: `eca913d50a556ffa206c2141f609226ef1d5cd3d65d0cd228fcb1b32aa0e5b5d` (it replaces the one of the entry above).
- Written by `python3 evals/eval_status.py measurement --close`.
- What the review fixes changed: a key proxy and its network are released whenever anything fails after `hold()`; the proxy keeps reading an answer after the run hung up and counts it, forces `usage.include` on the OpenRouter route, fails closed (429 for good) once an answer could not be read, reserves each request's `max_tokens` against the budget, and expands a compressed answer a chunk at a time; it refuses a body with `models` or `route` (OpenRouter) or a repeated key; `Accept-Encoding` is the run's offer among gzip, deflate and identity; the runtime reports a lower bound with `unknown_responses` and never falls back to the run's report; an image for another platform than the docker host's is a trial and a run line's `cpu_platform` must equal its event's `image_platform`; no `docker run` of the harness pulls an image; the meter folder is mode 0700; a gate entry's route must have a file and its key must be passed.
- The golden recording was made again: the allowed differences are `Accept-Encoding` and the `usage` body key of the OpenRouter route.

Measurement version 9 was reopened a second time on 2026-10-15 for the second round of review fixes of P2b (requests under way in the meter, the reserve floor, the platform default); nothing was measured while it was open. It is closed again by the last commit of that pull request.

## 2026-10-15: measurement version 9 closed (a third time, after the second round of review fixes of P2b)

SEC and P2b (with the review fixes): a held run reaches only its own per-run key proxy, which serves one model, drops credential headers, forwards only the model endpoints, meters the tokens (also after a hang-up and for a request under way when the run ends, failing closed) and stops at a per-run budget with reservations; route by provider and pin by model from the gate file; CPU platform on each run line, defaulting to the docker host's, emulated platforms are trials

- Measurement version 9, floor 6: nothing was measured while it was open; from this commit on the runner writes evidence under it.
- Fingerprint: `f3fd40d5361113d83f51134223616005799564822f37001d5421f2410d32f9f3` (it replaces the ones of the entries above).
- Written by `python3 evals/eval_status.py measurement --close`.
- What the second round changed: the meter file is written when a request is admitted and when it ends, with `in_flight`; the runner waits until no request is under way (at most the route's timeout, not at all on a stop) before it stops the proxy; `release()` sends SIGTERM first (`docker stop`) and the proxy records each answer it was still reading as unknown, so that a run that ends in the middle of a request has the answer counted or flagged as a lower bound, never a silent zero; a `max_tokens` below 1 reserves the route's default; `image_platform()` defaults to the docker host's platform when it is arm64 or amd64 (arm64 otherwise), and `runtime/lab.py` `image()` reports the evidence platform as the image's when it is one of the accepted pair.

## 2026-10-15: the tiers leave; a model is chosen per request, per agent or by `auto` (P3)

Package P3 of the delegation platform plan (decisions D1, D3, D4, D5, D8, D22, D34, D36, D38 of `docs/architecture/delegation-platform-plan-2026-10-14.md`).

- There is no reference model, no floor model and no tier. A skill has a band for each pair of model, adapter and skill; the gate, the score and the band are computed on a model's own lines by the same rules for every model, and `evals/eval-gate.json` holds no `strong_*` or `floor_*` key (`lab_models` lists the models a full test runs, `models` the known ids with their adapter, credential names, route and pin, `tolerance` the one tolerance, `web_jobs` for each model). `lab_models[0]` is only the order of the summary row of the status and the runtime's default model. Principle 9 of `AGENTS.md` now says what D34 says: proof decides what runs unattended by default, and the person's consent for an agent is the other way; an external effect keeps its hard limit either way.
- A model named on a request, a task, `run-next --model` or an agent runs there whatever its band; on a pair that is not proven the run waits for the person's review and is recorded `autonomy: "supervised"`. `auto` takes, among the pairs that are `reliable` with passing proof checks, a key, a known price, a measured usage and a provider inside the approved set, the lowest expected cost (mean usage by kind times the price per million), a tie going to the higher pessimistic score; with none it falls back to the project's `default_model` supervised and shows the reason; a pair reliable only through community evidence is chosen and held for review.
- Consent per agent (D38): fixing a model id on an agent in an autonomous or autonomous-with-policy mode is the person's consent to release that agent's reviews on a model with no reliable evidence. It is given with `accept` in the terminal after the warning (`autonomy.CONSENT_WARNING`), stored with the agent as `consent: {model, mode}`, recorded on each run as `autonomy: "consent"`, and asked again when the model or the mode changes; messaging has no operation that can give it.
- One price table (D36): `runtime/prices.json` (read by `runtime/prices.py`; filled by `scripts/update_prices.py` from OpenRouter's models API and by hand for a provider with no public list, each entry with its source URL and access date) replaces `adapters/api/prices.json` and the project's `model_prices` (retired: accepted, ignored, warned in `connections`). The auto estimate, a run's cost and the proof page read it, and a price older than `price_max_age_days` (90) is shown as stale.
- Storage: migration 10 of the store adds `tasks.model` and `task_runs.autonomy` (a closed set, NULL for older runs).
- Addendum items 12 and 13: the grader takes its runner, adapter and key from its own entry in the gate file whatever the order of the event's models; the rule that carried the lines of an earlier reference model into the score leaves, since each model's inherited lines are its own (an earlier `X.Y`, an epoch, the measurement floor, a dependency).
- What changed no band: `python3 evals/eval_status.py status` gives the same bands, causes and gates as before, apart from its gate header (`lab_models` and `tolerance` in place of the strong and floor keys). No fingerprinted file changed, so the measurement fingerprint is the same.
