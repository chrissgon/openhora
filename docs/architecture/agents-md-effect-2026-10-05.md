# The effect of a project's AGENTS.md in the two adapters (2026-10-05)

Item 2.9 of the platform plan (`platform-plan-2026-10-05.md`). The task runtime puts the project's `AGENTS.md` into the run copy of a skill that declares it (limit L5 of `contracts/runtime.md`): the whole file in a project whose `protected_paths` does not match it, only the workbench section otherwise. The lab measured each skill on a case folder that has no such file, so it was not known whether the adapter of the reference model and the adapter of the floor model (both named in `evals/eval-gate.json`) give that file to the model by themselves, or only when the skill's own step reads it. This record measures it, as observed. It decides nothing by itself.

It holds counts, yes or no and the invented name only: no reply text and no path of the machine.

## How it was measured

- A scratch project outside every repository, with invented content, initialised by `core-project-init` as "Lantern Notes" (autonomy `milestones`, docs none), with its own data folder and an accepted configuration; `protected_paths` absent, so with the file present the whole file enters.
- Condition **with**: one line added to the project's `AGENTS.md`, outside the workbench markers: a convention that every reply ends with the line `convention: lantern`. Condition **without**: `AGENTS.md` moved out of the project.
- For each condition and each tier: a new request on the flow `market-positioning`, its first task (`biz-market-analysis`) run once through the runtime, the request cancelled afterwards. The reference model with `run-next --tier strong`; the floor model with `run-next` and no option, because `proof --skill biz-market-analysis` gave the tier `floor` (both bands `reliable`, both checks passing, the key found). The first run of this task asks for the scope and writes nothing.
- The runtime ran from a checkout of the central branch at the head that holds WP-2.11; the eval image was the evidence's (its digest is the one in `docs/decisions.md`).

## The runs

| Run | Condition | Tier | Key of a floor run | `entered.agents_md` | Status | Ending | `skill_loaded` | Tokens | Duration (ms) |
|---|---|---|---|---|---|---|---|---|---|
| 1 | with | strong | none | whole | ok | question | 1 | 122,006 | 18,106 |
| 2 | with | floor | lab | whole | ok | question | 1 | 44,302 | 89,146 |
| 3 | without | strong | none | not entered | ok | question | 1 | 125,119 | 16,778 |
| 4 | without | floor | lab | not entered | ok | question | 1 | 54,059 | 47,817 |

| Run | The reply's last line is the convention line | Lines of the run's stream that hold the file's name | Tool calls that name the file | The reply mentions the orchestrator skill | The reply mentions the evidence recorder | Language of the reply |
|---|---|---|---|---|---|---|
| 1 | yes | 2 | 0 | no | no | English |
| 2 | yes | 4 | 0 | no | no | English |
| 3 | no | 3 | 1 | no | no | English |
| 4 | no | 4 | 1 | no | no | English |

Every run: one attempt, no failure, no value replaced in what it left, a use recorded. Every reply opened with the skill's asking opening and asked for the scope. The lines of the streams that hold the file's name are the skill's own text and file listings; the tool calls of runs 3 and 4 are the model looking for the file, once each, and not finding it.

## Reading

- **The reference model's adapter:** with the file in the copy, the reply followed the line outside the workbench section, and no tool call read the file. The adapter gives the copy's `AGENTS.md` to the model by itself. Without it, the reply did not follow the convention.
- **The floor model's adapter:** the same. With the file, the reply followed the convention line, and no tool call read the file; without it, it did not.
- No reply mentioned the orchestrator skill or the evidence recorder, with or without the workbench section in context: the two lines of the section that ask for them (recording a use, the skill check) are removed from every copy by limit L5, and the replies show no trace of them.
- So in both adapters, what limit L5 puts in the copy is what reaches the model, with no step of the skill needed. The limit governs the file as designed.

## The line per adapter

Written as a plain reading of the fields above, on the supervisor's delegation (the maintainer delegated supervision on 2026-10-05):

- The reference model's adapter: **no change** to limit L5.
- The floor model's adapter: **no change** to limit L5.

The scratch project and its data folder were deleted after the runs.
