# Environment contract: requirement classes

Skills declare what they need from the environment as *classes*, never as products. The environment (a harness connector, an MCP server, or a provider script) satisfies a class. This keeps the core harness-agnostic and lets the orchestrator degrade gracefully when something is missing.

## Classes

<!-- class-table:begin -->
| Class | What satisfies it | Used by |
|-------|-------------------|---------|
| `integration:issue-tracker` | Jira, Linear, GitHub Issues | engineering flows |
| `integration:vcs` | GitHub, GitLab | delivery |
| `integration:design-tool` | Figma; the design-system projects of a generative design tool | design, validation |
| `search:web` | read-only access to the public web: a search tool, fetching a page, reading a public registry or a public API | research, business, brand, engineering, marketing |
| `generator:image` | any image model behind an API | design assets, marketing |
| `generator:video` | any video model behind an API | marketing (slot reserved, not implemented) |
| `publisher:<platform>` | the publishing API of the platform, called directly or through a scheduling service; the platform is a parameter | marketing |
| `sender:email` | SMTP, a mail API | marketing, notifications |
| `reader:email` | Gmail API, IMAP (read only: search and read messages) | marketing, engagement |
| `scheduler:job` | launchd on macOS, systemd on Linux (a job runs a command once at a set time or every N minutes); or a harness routine | marketing, operations, the agent runtime's trigger |
| `store:runtime` | SQLite (a local file); a cloud database later | the agent runtime: cursors, events, runs, approval inbox, executed actions |
<!-- class-table:end -->

Add a class when a second skill needs it; do not add classes speculatively. A skill copies a name exactly as this table spells it, and every skill that uses a class declares it in `requires`, whether its procedure needs the class or only uses it when it is there: the body says what the skill does without it ("Resolution order", step 3), and `scripts/doctor.py` then reports it.

**`search:web` covers any read-only use of the public web**, required or optional: searching, fetching the pages a search returns or a page the user names, and reading a public registry or a public API without credentials (a package's versions, a domain's registration, a public profile). Anything that needs an account, or that writes, is another class.

**Every class has the form `<role>:<target>`**, in one of two forms:

- **A fixed target.** The target is part of the class's identity, and another target would have other verbs: `integration:issue-tracker`, `integration:vcs`, `integration:design-tool`, `search:web`, `generator:image`, `generator:video`, `sender:email`, `reader:email`, `scheduler:job`, `store:runtime`. `requires` names the class exactly as written.
- **A parameter.** `publisher:<platform>` is the one class whose part after the colon is handed to the provider, as `--platform`: one implementation may serve several platforms, and each declares the ones it serves (`providers/CONTRACT.md`, "Selection"). In `requires` it is written with the placeholder, `publisher:<platform>`, by a skill that works on whichever platform the request names, or with a value by a skill that is about one platform. This table gives no platform as an example, so that a new platform edits no copy of it.

Class names are identifiers. Four of them were bare until 2026-10-02 (`mailer`, `mailbox`, `scheduler`, `store`) and are now `sender:email`, `reader:email`, `scheduler:job` and `store:runtime`. Only the names changed: the provider folders (`providers/mailbox/`, `providers/scheduler/`, `providers/store/`), the selection variables (`MAILBOX_PROVIDER`, `MAILER_PROVIDER`, `SCHEDULER_PROVIDER`, `STORE_PROVIDER`), the keys of a project's `runtime.json` and every data name (ledgers, job labels, stored credentials) are what they were, so a project that uses the workbench changes nothing. `providers/resolve.py` still reads the four old names as aliases, for the copies of the runtime that jobs scheduled earlier keep running; a skill's `requires` does not use them, and the validator reports one that does.

## Resolution order

1. **Harness connector** (MCP server or built-in integration). Authentication is handled by the harness and consented by the user in its UI. Preferred: the model never touches credentials.
2. **Provider script** under `providers/<class>/`, following `providers/CONTRACT.md`, reading credentials from environment variables or the OS secret store. Used when the harness has no connector for the class, or for harnesses without connectors at all.
3. **Degrade.** The skill produces the deliverable up to the point where the tool is needed, tells the user exactly what is missing, and stops. It never fakes the effect.

A skill's body must describe its behaviour at step 3 for every class it requires.

## Reaching a provider script

A skill, the agent runtime and `scripts/doctor.py` reach a provider by its class, through one resolution function, `providers/resolve.py`. None of them names an implementation or builds a provider's path.

- **The command:** `python3 <workbench root>/providers/resolve.py --class <class>` prints the path of the provider script for the class (`--json` adds the implementation and how it was chosen; `--list` prints every class with its implementations and the one that resolves now). Exit 0 with the path, 3 when nothing resolves (the message names the variable to set; the skill degrades), 2 on an unknown class.
- **The order:** the environment variable of the class, `<ROLE>_<TARGET>_PROVIDER` then `<ROLE>_PROVIDER` (`PUBLISHER_<PLATFORM>_PROVIDER` then `PUBLISHER_PROVIDER`; `INTEGRATION_VCS_PROVIDER`; `SCHEDULER_PROVIDER` for `scheduler:job`, one of the four classes that keep the variable of their old name); then the platform default where one exists (`scheduler:job`: launchd on macOS, systemd on Linux); then the only implementation left: for `publisher:<platform>`, among the implementations that serve the platform asked. Details: `providers/CONTRACT.md`, "Selection".
- **The workbench root:** the environment variable `WORKBENCH_ROOT`, the absolute path of the workbench checkout a project uses. Unset, the function uses the checkout it is in; a skill, which runs from the project and cannot know that path, asks the user once and records the answer as a decision in the state file.
- **In a skill:** write "Resolve the provider by its class: `python3 <workbench root>/providers/resolve.py --class scheduler:job` prints the path of the provider script", then use the printed path in the commands that follow. `requires` in the frontmatter names the same class.

## Credentials

- Never in this repository. `.env` files are ignored by git.
- `<ROLE>_PROVIDER` (or `<ROLE>_<TARGET>_PROVIDER`) picks the implementation of a class (read by `providers/resolve.py`, see "Reaching a provider script"); it holds a name, never a credential. Provider scripts read provider-specific variables for credentials (documented in the script's `--help`).
- OAuth-based services need a one-time interactive authorization performed by the user with a dedicated script, which stores the refresh token in the OS secret store, never in a file inside a project.
- Service-side access approval (for example, platform APIs that require an approved developer application) is outside this repository's control. Skills say so when relevant.

## Side effects and consent

Any skill that changes something outside the repository declares it in `metadata.side_effects` and implements a `## Confirmation gate` section. The vocabulary is closed:

| Word | The skill |
|------|-----------|
| `publish` | makes content public on a platform |
| `send` | sends a message to a person: an e-mail, a direct message |
| `schedule` | registers a job that acts later |
| `deploy` | puts code or configuration into a running environment |
| `create` | creates or changes a record at a remote service: a ticket, a pull request, a file in a design tool, a comment or a reply posted on a host |
| `push` | pushes commits to a remote repository |
| `dismiss` | closes or dismisses a record at a remote service (an alert) |

Writing a file inside the project is not a side effect, and there is no word for it. A new word is added here, and to the validator's list, in the pull request of the first skill that needs it.

**One explicit approval, then autonomy.** The user approves once; after that the skill proceeds without asking again, including later and unattended for scheduled work. The gate exists to make the user see exactly what will happen, not to interrupt them repeatedly.

Approval scopes, recorded in `docs/workbench/state.md` under "Approvals":

| Scope | What the user approves | What runs without asking again | Default for |
|-------|------------------------|--------------------------------|-------------|
| action | one exact payload (text, media, recipients, time, target) | that payload, once, now or at its scheduled time | irreversible public actions: publish, send, deploy to production |
| plan | a set of actions shown together (a week of posts, a release with its steps) | every action in the set, as long as it matches what was shown | batches and scheduled series |
| standing | a class of action within stated bounds (open PRs on `feature/*`, commit to non-protected branches), with an expiry | any action inside the bounds until expiry | reversible, low-blast-radius actions inside the project |

Rules:

- The gate shows the exact payload or plan, asks once, and proceeds on an explicit yes. Silence, a previous different approval, or an approval for a similar item is not consent.
- An approval covers exactly what was shown. Any deviation (changed content, new recipient, different time or target) needs a new approval for the changed part only.
- **The approval binds a hash of the payload.** In this order:
  1. The skill writes the payload, exactly as shown, to a file, and records `sha256sum <file>` (macOS: `shasum -a 256`) in the approval's `Payload hash`. Only the hash is stored, never the payload.
  2. The folder is one from `mktemp -d` when the payload runs now. When it runs later than the approval (a scheduled post, a plan that runs over days), the folder is a durable one inside the project that git ignores (`.workbench-local/payloads/<date>/`, mode 0700), never a temporary folder: the system removes old temporary folders, and an approval whose payload is gone cannot be verified or executed again. The skill checks that git ignores the folder before writing to it.
  3. For a payload in a durable folder, the hash covers contents and paths relative to the payload folder, never absolute paths, so the same payload moved or built again from unchanged sources has the same hash and stays approved.
  4. What the skill executes is that file, never a payload written again (a model does not write the same text twice).
  5. Before executing under an `action` or `plan` approval, it hashes the file again and executes only when the hash equals the approval's; a missing file or a different hash means showing the payload and asking again.
  6. When a skill changes how it computes the hash, approvals already recorded keep their recorded hash and the skill says how to check them; an old approval whose payload cannot be checked any more is asked again for what has not run.
  7. A `standing` approval covers a class of action within bounds, not a payload. When its bounds are written in a file (an engagement policy), its `Payload hash` is `policy:<sha256 of that file>`, and every action under it checks that hash first, so editing the bounds stops the actions until the person approves the new file.
- Approvals are recorded in state with scope, summary, date, expiry and status (`pending-execution`, `executed`, `active`, `expired`, `revoked`). A resumed session reads them and never re-asks for what is already approved.
- **Pre-approved execution**: when an action runs later or unattended (a scheduled post, a nightly job), the confirmation happens at scheduling time with the final payload. At execution time the skill verifies the payload still matches the approval (same `Payload hash`), executes, and updates the status to `executed` with a timestamp. If it no longer matches, it does not execute and leaves a note in "Open questions".
- Standing approvals are never granted by default for public or irreversible actions; the user must state them explicitly, with bounds and expiry.
- Providers refuse side-effect verbs without `--confirmed` (see `providers/CONTRACT.md`), so a skill that skipped its gate fails loudly.

**Two records of approvals.** An approval given in a session (a skill's confirmation gate) is recorded in `docs/workbench/state.md` under "Approvals", as above, and that table is where a skill looks before asking. An approval given to a runtime is recorded in the runtime's store instead (`store:runtime`, `contracts/runtime.md`), and the store's record is the one the runtime's code checks before it acts: a model run returns the state file, so a row of that file alone never authorises a runtime. The two runtimes keep that record in two ways. In the first runtime (`scripts/runtime.py`), the item the person approves or rejects is an inbox item with its payload hash, what then ran is an action row, and that runtime writes nothing to the state file; the standing approval of an engagement policy it runs under is the state file's row (`policy:<sha256>`) a session recorded, which the skill's gate script reads at every event. In the task runtime (`runtime/`), decided on 2026-10-05 (the platform plan, `docs/architecture/platform-plan-2026-10-05.md`, limits 10 and 17), an approval is a row of the store's approvals table: an effect's approval (`runtime/cli.py approve --sha256`) and a standing approval of a policy file (`runtime/cli.py approve-policy`). Its rows in the state file are copies code generates from the store's rows (an executed effect's row, and the standing row `policy:<sha256>` that a skill's gate script reads there); only code writes such a row, the row of a revoked standing approval leaves the file, and what a run leaves in the Approvals table is never taken back. Neither record stands for the other: a skill that checks the state file does not see what the person approved in the first runtime's inbox, a runtime does not see a session's `action` or `plan` approvals, and an action approved in one record is never executed on the strength of the other.

## Checking an environment

`python3 scripts/doctor.py [--harness <adapter>]`, run in the workbench checkout, lists every class the skills of that checkout require (its own `skills/` folder, not the copies an installer put in a project) and whether a connector (declared in `adapters/<harness>/connectors.json`) or a native provider satisfies it: the provider `providers/resolve.py` chooses for the class, when its `--check` passes (`--check --platform <p>` for `publisher:<p>`, so that a platform nobody serves is reported as missing). A class the resolution function does not know is reported as `unknown`, and counts as missing. It runs each provider's `--check` through `uv run`, never with the caller's interpreter, and reports a provider as missing when `uv` is not on `PATH`. It is a tool for the person who sets an environment up, and it exists only where the workbench checkout is, so a skill never depends on it: before a step that needs an external tool, a skill resolves the class and reads the provider's `--check` itself ("Reaching a provider script"), and degrades as its body says.
