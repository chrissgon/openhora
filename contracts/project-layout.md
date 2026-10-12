# Artifact contract: layout of a target project

Skills never keep state inside this repository. Everything they produce for a project lives in that project, under `docs/`, so that later phases, other skills and other people can find it.

```
<target-project>/
├── AGENTS.md                     # project conventions; owned by core-agents-md
├── .workbench-local/             # git-ignored work data: payloads/<date>/ (approved payloads that run later), evidence/ (recorded uses of a skill), drop/<task id>/ (files the person handed to one task of the task runtime), and the machine files a project's runtime.json names there (a dependency file)
└── docs/
    ├── workbench/
    │   ├── state.md              # phase, artifact status, decisions, open questions (schema: state.md)
    │   ├── runtime.json          # the agent runtime's configuration, written by the person who sets it up (schema: runtime.md)
    │   ├── policies/<policy>.json # the bounds of a standing approval of the task runtime, written by the person (approve-policy binds its hash)
    │   ├── briefs/<topic>.md     # shared-understanding briefs written by core-clarify
    │   ├── critiques/<topic>.md  # adversarial reviews written by core-critique
    │   └── research/<topic>.md   # sourced research briefs written by core-research (with <topic>.check.json)
    ├── business/                 # idea-validation.md, market.md, icp.md, positioning.md, business-model.md, pricing.md, gtm.md, business-plan.md
    ├── product/                  # discovery.md, prd.md, specs/<feature>.md, roadmap.md, backlog.md, metrics.md; the lint records beside them: prd.lint.json and prd.lint-before.json, specs/<feature>.lint.json and specs/<feature>.lint-before.json, roadmap.lint.json, backlog.lint.json and backlog.lint-before.json
    ├── brand/                    # profile.md, name.md, strategy.md, identity.md, voice.md, guidelines.md, pieces/ (the brand pieces and their renders, written by brand-identity)
    ├── design/                   # research.md, flows.md (with flows.lint.json), wireframes/, screens/ (an existing screen-by-screen specification, registered), design-system.md (with design-system.lint.json), briefs/<artifact>.md (with <artifact>.lint.json), results/<artifact>.md (with <artifact>.lint.json), results/<artifact>/ (the run folders of that artifact), handoff/<screen>.md (with <screen>.lint.json), handoff/<screen>/export/ (the unpacked export of that screen)
    ├── engineering/              # architecture.md (or codebase-map.md beside a registered spec), designs/<feature>.md, adr/<NNNN>-<title>.md, designs/<feature>.check.json, plans/<task>.md (and handoff.md, migration.md when an existing document is registered there), reviews/<change>.md, security-reviews/<date>.md
    ├── ai/                       # opportunity.md, requirements.md, evals/, governance.md
    ├── delivery/                 # repo-baseline.md, runbooks/, releases/, incidents/
    ├── marketing/                # messaging.md (with messaging.lint.json), launch-plan.md, calendar.md, content/<post>.md, campaigns/, engagement-policy.md, engagement-inbox.md, engagement-log.jsonl
    └── security/                 # audit-<date>.md, vetting-<skill>-<date>.md: the records of core-security-audit, in the workbench or in a project that vets a skill
```

The tree names every slot, built or planned. Which skill owns a slot that is built is in "Owning skills" below.

## Declaring artifacts: `inputs`, `outputs`, `updates`

A skill's frontmatter declares the workbench artifacts it touches: the paths under `docs/`, and `AGENTS.md`.

- `inputs`: the artifacts it reads if they exist.
- `outputs`: the artifacts it **owns**. It creates them and its template defines their structure. An artifact has exactly one owner.
- `updates`: the artifacts another skill owns that it writes into, inside the owner's structure: a row, a section, a status, an approval. It may create the file when it is missing only with the owner's header, and only when its body says so. Writing implies reading: a path in `updates` is repeated in `inputs` only when the skill also reads it for content before deciding anything.

A path is never in both `outputs` and `updates` of one skill. A path may be in `inputs` and `outputs` of its owner (a later run updates the earlier artifact). The order the artifacts give is "the owner of a path comes before a skill that reads it"; `updates` adds nothing to it, and it has no cycle.

Project files that are the work itself (source, tests, documents, workflow files, rendered images) are not declared.

## Placeholders

A declared path may hold placeholders. A placeholder is `<name>`: lowercase letters and hyphens between angle brackets, standing for one path segment or a part of one. No other wildcard is allowed in `inputs`, `outputs` or `updates`: no `*`, no `{}`, no bare `NNNN`, and no `#` to address a section of a file. A path that ends in `/` is a folder the skill owns as a whole.

Two paths are the same artifact when they are equal after every placeholder is replaced by a wildcard, and one artifact is spelled with the same placeholders wherever it is declared. A skill's body may expand a placeholder this table defines (`<post>` written as `<YYYY-MM-DD>-<slug>`).

The vocabulary is closed. A new name is added to this table in the pull request that first uses it.

| Placeholder | Stands for |
|-------------|------------|
| `<topic>` | a short kebab-case name of the subject |
| `<feature>` | the feature's kebab-case name; the same value in `docs/product/specs/` and `docs/engineering/designs/` |
| `<artifact>` | the name of a visual artifact |
| `<screen>` | one screen of an artifact |
| `<task>` | a kebab-case name of the task or of the symptom |
| `<change>` | the task id, else the branch name, else the pull request number |
| `<date>` | `YYYY-MM-DD`; a second file of the same day ends in `-2`, a third in `-3` |
| `<post>` | `<date>-<slug>` |
| `<NNNN>` | a four-digit sequence number, zero-padded; the one name that is not lowercase |
| `<title>` | a kebab-case title |
| `<skill>` | the name of a skill |
| `<policy>` | the kebab-case name of a policy; its bounds file's name |

## Slots no built skill writes

An input that no skill owns is listed here, or the validator reports it. `Provided by` is `user` (a person writes it, or it exists before the workbench) or `planned: <skill>` (a skill that is not built yet). A row leaves when a built skill owns its path.

| Path | Provided by |
|------|-------------|
| `docs/business/idea-validation.md` | planned: biz-validate-idea |
| `docs/marketing/launch-plan.md` | planned: mkt-launch-plan |
| `docs/workbench/runtime.json` | user |
| `docs/workbench/policies/<policy>.json` | user |

## Owning skills

Generated from the skills' frontmatter by `python3 scripts/owner_table.py`; never edited by hand. A pull request that changes a skill's `outputs` or `updates` runs it. "Owning skill" is the skill whose `outputs` lists the path; "Updated by" the skills whose `updates` lists it.

<!-- owner-table:begin -->
| Artifact | Owning skill | Updated by |
|----------|--------------|------------|
| `AGENTS.md` | core-agents-md | core-project-init |
| `docs/brand/guidelines.md` | brand-guidelines | - |
| `docs/brand/identity.md` | brand-identity | - |
| `docs/brand/name.md` | brand-name | - |
| `docs/brand/pieces/` | brand-identity | - |
| `docs/brand/profile.md` | brand-profile | - |
| `docs/brand/strategy.md` | brand-strategy | - |
| `docs/brand/voice.md` | brand-voice | - |
| `docs/business/icp.md` | biz-icp-positioning | - |
| `docs/business/market.md` | biz-market-analysis | - |
| `docs/business/positioning.md` | biz-icp-positioning | - |
| `docs/delivery/repo-baseline.md` | ops-repo-baseline | - |
| `docs/design/briefs/<artifact>.lint.json` | design-brief | - |
| `docs/design/briefs/<artifact>.md` | design-brief | - |
| `docs/design/design-system.lint.json` | design-system | - |
| `docs/design/design-system.md` | design-system | - |
| `docs/design/flows.lint.json` | design-ux-flows | - |
| `docs/design/flows.md` | design-ux-flows | - |
| `docs/design/handoff/<screen>.lint.json` | design-handoff | - |
| `docs/design/handoff/<screen>.md` | design-handoff | - |
| `docs/design/handoff/<screen>/export/` | design-handoff | - |
| `docs/design/results/<artifact>.lint.json` | design-execute | - |
| `docs/design/results/<artifact>.md` | design-execute | - |
| `docs/design/results/<artifact>/` | design-execute | - |
| `docs/engineering/adr/<NNNN>-<title>.md` | eng-architecture | eng-implement, eng-tradeoffs |
| `docs/engineering/architecture.md` | eng-codebase-map | - |
| `docs/engineering/codebase-map.md` | eng-codebase-map | - |
| `docs/engineering/designs/<feature>.check.json` | eng-architecture | - |
| `docs/engineering/designs/<feature>.md` | eng-architecture | - |
| `docs/engineering/plans/<task>.md` | eng-root-cause | eng-docs, eng-impact-analysis, eng-implement, eng-integration-tests, eng-refactor, eng-tradeoffs, eng-unit-tests, ops-ci-pipeline |
| `docs/engineering/reviews/<change>.md` | eng-code-review | - |
| `docs/engineering/security-reviews/<date>.md` | eng-security-review | - |
| `docs/marketing/calendar.md` | mkt-content-plan | mkt-publish, mkt-social-copy, mkt-vote-round |
| `docs/marketing/content/<post>.md` | mkt-social-copy | mkt-vote-round |
| `docs/marketing/engagement-inbox.md` | mkt-engage | - |
| `docs/marketing/engagement-log.jsonl` | mkt-engage | - |
| `docs/marketing/engagement-policy.md` | mkt-engage | - |
| `docs/marketing/messaging.lint.json` | mkt-messaging | - |
| `docs/marketing/messaging.md` | mkt-messaging | - |
| `docs/product/backlog.lint-before.json` | product-backlog | - |
| `docs/product/backlog.lint.json` | product-backlog | - |
| `docs/product/backlog.md` | product-backlog | eng-implement |
| `docs/product/prd.lint-before.json` | product-prd | - |
| `docs/product/prd.lint.json` | product-prd | - |
| `docs/product/prd.md` | product-prd | - |
| `docs/product/roadmap.lint.json` | product-roadmap | - |
| `docs/product/roadmap.md` | product-roadmap | - |
| `docs/product/specs/<feature>.lint-before.json` | product-feature-spec | - |
| `docs/product/specs/<feature>.lint.json` | product-feature-spec | - |
| `docs/product/specs/<feature>.md` | product-feature-spec | - |
| `docs/security/audit-<date>.md` | core-security-audit | - |
| `docs/security/vetting-<skill>-<date>.md` | core-security-audit | - |
| `docs/workbench/briefs/<topic>.md` | core-clarify | - |
| `docs/workbench/critiques/<topic>.md` | core-critique | - |
| `docs/workbench/research/<topic>.check.json` | core-research | - |
| `docs/workbench/research/<topic>.md` | core-research | - |
| `docs/workbench/state.md` | core-project-init | biz-icp-positioning, biz-market-analysis, brand-guidelines, brand-identity, brand-name, brand-profile, brand-strategy, brand-voice, core-clarify, core-critique, core-orchestrator, core-research, design-brief, design-execute, design-handoff, design-system, design-ux-flows, eng-architecture, eng-codebase-map, eng-security-review, flow-fix-bug, mkt-content-plan, mkt-engage, mkt-messaging, mkt-publish, ops-branch-sync, ops-ci-pipeline, ops-pull-request, ops-repo-baseline, product-backlog, product-feature-spec, product-prd, product-roadmap |
<!-- owner-table:end -->

## Rules

- `metadata.outputs` lists the workbench artifacts a skill owns, and `metadata.updates` the ones it writes into without owning them ("Declaring artifacts" above). A skill may own several artifacts; each has a fixed name or a name with placeholders.
- A skill reads its `metadata.inputs` if they exist. If an input is missing, it says so and either asks the user for the information or names the skill that produces it, for the user to run. It never silently invents the content of a missing input.
- Artifacts are Markdown unless the content is inherently structured (design tokens, eval datasets, a check script's report), in which case JSON or YAML sits next to a Markdown summary.
- Every Markdown artifact starts with a short header that carries at least `- Owner:` (the owning skill), `- Status:` and `- Date:`. The status mirrored in `docs/workbench/state.md` is `draft`, `approved` or `skipped`; the header itself may carry a finer status that the owner's template defines.
- Day-to-day engineering tasks (implementing a ticket, fixing a bug) create no artifact under `docs/` except a plan in `docs/engineering/plans/` and a review in `docs/engineering/reviews/`. Both are the working records of one task: they are not registered in the state file, and no skill removes them; whether they are kept once the task ships is the project's decision.
- An artifact's template lives with the skill that owns the artifact: in the skill's `assets/` folder, or inline in its `SKILL.md` when it is short. A skill that writes into an artifact it does not own follows the owner's template and says so. `contracts/templates/` holds only a README.
- Work data that must outlive a session and is not an artifact (an approved payload that runs later, a record of a use) goes to `.workbench-local/`, which git ignores; a skill checks that it is ignored before writing there (`contracts/environment.md`).

## Existing projects

A project that already keeps specifications elsewhere (`ARCHITECTURE.md` at the root, a `specs/` folder) does not move them. `core-project-init` registers each one in `docs/workbench/state.md` as the slot it fills, with its real path and owner `existing`. A skill whose `inputs` list that slot reads the registered path. Only new artifacts follow the layout above. End-user documentation under `docs/` (a documentation site) is product content, never a workbench artifact.
