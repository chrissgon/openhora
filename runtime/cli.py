#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The terminal shell of the task runtime: one command per operation of runtime/ops.py, nothing else.

Usage:
  python3 runtime/cli.py request  --project <dir> [--flow <name>] (--text <text> | --text-file <file>) [--title <title>]
  python3 runtime/cli.py route    --project <dir> --request <request id> [--flow <name> [--param <name>=<value>]...]
  python3 runtime/cli.py route-queued --project <dir>
  python3 runtime/cli.py approve  --project <dir> --id <pending id> [--sha256 <plan hash> | --sha256 <effect hash>]
  python3 runtime/cli.py reject   --project <dir> --id <pending id> [--note <text>]
  python3 runtime/cli.py deps     --project <dir>
  python3 runtime/cli.py run-next --project <dir> [--model <id>|auto]
  python3 runtime/cli.py run-task --project <dir> --task <task id> [--model <id>|auto]
  python3 runtime/cli.py run-step --project <dir> --task <task id> [--unattended]
  python3 runtime/cli.py pending  --project <dir> [--id <pending id>]
  python3 runtime/cli.py answer   --project <dir> --id <pending id> (--text <text> | --text-file <file>) [--with-comments]
  python3 runtime/cli.py release  --project <dir> --id <pending id>
  python3 runtime/cli.py retry    --project <dir> --task <task id>
  python3 runtime/cli.py cancel   --project <dir> --request <request id>
  python3 runtime/cli.py status   --project <dir>
  python3 runtime/cli.py task     --project <dir> --task <task id>
  python3 runtime/cli.py flows    --project <dir>
  python3 runtime/cli.py flow-check --project <dir> --flow <name>
  python3 runtime/cli.py flow-save --project <dir> --name <name> (--id <plan's pending id> | --flow <name>) [--title <text>] [--split] [--replace]
  python3 runtime/cli.py stage-file --project <dir> --request <request id> --file <path>
  python3 runtime/cli.py instructions --project <dir>
  python3 runtime/cli.py instructions-set --project <dir> (--text <text> | --text-file <file>) --base-sha256 <sha256 | none>
  python3 runtime/cli.py instructions-add --project <dir> --line <text> --base-sha256 <sha256 | none>
  python3 runtime/cli.py routines --project <dir> [--id <routine id>]
  python3 runtime/cli.py routine-create --project <dir> --name <name> --flow <workflow> [--param <name>=<value>]... (--every day --at HH:MM | --every week --weekday 1-7 --at HH:MM | --every minutes --minutes N) [--model <id>|auto] [--provider <name>]... [--window-seconds <n>] [--consent]
  python3 runtime/cli.py routine-change --project <dir> --id <routine id> [the fields of routine-create, except --name]
  python3 runtime/cli.py routine-approve --project <dir> --id <routine id> [--sha256 <hash>]
  python3 runtime/cli.py routine-pause --project <dir> --id <routine id>
  python3 runtime/cli.py routine-resume --project <dir> --id <routine id>
  python3 runtime/cli.py routine-cancel --project <dir> --id <routine id>
  python3 runtime/cli.py agents   --project <dir>
  python3 runtime/cli.py conversation --project <dir> [--conversation <name>] [--after <message id>]
  python3 runtime/cli.py skills   --project <dir>
  python3 runtime/cli.py costs    --project <dir> [--since YYYY-MM-DD]
  python3 runtime/cli.py connections --project <dir>
  python3 runtime/cli.py artifacts --project <dir>
  python3 runtime/cli.py artifact --project <dir> --path <docs/...>
  python3 runtime/cli.py config   --project <dir>
  python3 runtime/cli.py accept-config --project <dir> --sha256 <hash>
  python3 runtime/cli.py proof    --project <dir> [--skill <name>]
  python3 runtime/cli.py verdict  --project <dir> --run <run id> --word worked|corrected|failed
  python3 runtime/cli.py sync     --project <dir> [--dry-run] [--take page|project --path <relative path>]
  python3 runtime/cli.py hand-over --project <dir> --task <task id> --file <path>
  python3 runtime/cli.py source-add --project <dir> --source <id> --type file|notion|drive --origin <file name | Notion page address | Drive file id> [--description <text>]
  python3 runtime/cli.py source-import --project <dir> --source <id> (--file <path> | --url <Notion page address or id>) [--origin <text>] [--description <text>]
  python3 runtime/cli.py source-refresh --project <dir> --source <id> [--file <path>]
  python3 runtime/cli.py source-describe --project <dir> --source <id> [--description <text>]
  python3 runtime/cli.py source-drive --project <dir> [--file-id <Drive file id> --source <id>] [--description <text>]
  python3 runtime/cli.py sources  --project <dir>
  python3 runtime/cli.py progress --project <dir> [--since 7d | <n>d | YYYY-MM-DD]
  python3 runtime/cli.py approve-policy --project <dir> --file <docs/...> --agent <name> [--sha256 <hash> --expires <YYYY-MM-DD>] [--what <text>]
  python3 runtime/cli.py revoke-policy --project <dir> --id <approval id>
  python3 runtime/cli.py standing --project <dir> --policy <name>
  python3 runtime/cli.py execute-under-policy --project <dir> --policy <name> --effect-file <path>
  python3 runtime/cli.py set-mode --project <dir> --agent <name> --mode stopped|supervised|milestones|autonomous|autonomous-with-policy [--accept] [--consent]
  python3 runtime/cli.py set-model --project <dir> --agent <name> --model <id>|auto|default [--accept] [--consent]
  python3 runtime/cli.py contained-run --project <dir> --skill <name> --prompt-file <file> --out <dir> [--platform <name>]... [--timeout-seconds <n>]
  python3 runtime/cli.py dispatch --project <dir>
  python3 runtime/cli.py poll     --project <dir>
  python3 runtime/cli.py handler  --project <dir> --name <handler> --verb <verb> [--arg <flag>=<value>]...
  python3 runtime/cli.py stop-runs --project <dir> [--all]
  python3 runtime/cli.py service-check --project <dir> [--dispatch-every <seconds>]
  python3 runtime/cli.py pin      --project <dir>
  python3 runtime/cli.py say      --project <dir> (--text <line> | --text-file <file or ->)

request   records what you want. With --flow, plans it from the flow file flows/<name>.json: its tasks, with the
          dependencies the file writes; a task without a dependency is ready at once. Without --flow, the
          request waits for its route. A flow of the project, a flow with a step and a flow with parameters are not started
          this way: record the request, then route it (route --flow), so that you approve the plan by its hash.
route     plans a request that waits for its route. Without --flow: one run of the router skill, as it is, asked
          only for the route (it calls a model, like run-next; nothing it writes comes back); a route it gives
          becomes a plan for you to approve, a question it asks is answered with answer (then route again), and
          a reply with no recognised route opens a question with one sentence and the reply whole in its payload, a
          direct turn (route none, shape direct) opens nothing and prints kind "direct" with the router's next line.
          With --flow: the plan of that flow file (the workbench's, or the project's in docs/workbench/flows/), no run and no
          route lock; --param name=value, repeated, fills the flow's parameters (a file parameter names a file stage-file
          handed over for the request), and {today} and {week} are filled from the clock of this machine, in its time zone,
          which the plan states. The plan's hash covers the filled tasks. While the router answers another request of
          the project the request is refused here (as before; a run of a task never makes it); only the local page queues
          it ({"queued": true}), and the service's loop, or route-queued, routes it when that run ends.
route-queued  answers the oldest line of the conversation, or routes the oldest request, that waited for the end of the
          router's run (the local page queues them while the router answers another request): one per call, only when
          the router is free. The local service calls it every few seconds; it calls a model, like route.
approve   approves a plan (its tasks are created; pass the plan's hash, shown with it, as --sha256 to approve
          exactly what you read) or a request written on the task board.
          An effect (a pull request a skill prepared up to its confirmation gate) is approved only here, in the
          terminal, or on the local page (runtime/service.py), and only with its hash (the conversation refuses it):
          code then checks that nothing moved, makes the one commit with your own git and signature through the
          code provider and opens the pull request. The provider reads the token that opens a pull request by its
          own name (VCS_GITHUB_PR_TOKEN, from the secret store or the environment, providers/vcs/README.md); the
          runtime passes none.
reject    rejects a plan or a request written on the task board: the request is cancelled. An effect rejected
          cancels its task, and nothing is sent.
run-next  runs the next ready task that the rules of the slots let in (runtime/parallel.py), in this process: one skill,
          once, in the eval container, on the model chosen for it (the request's, the task's, the agent's fixed model, the
          project's default_model, else auto: the cheapest model on which the skill is reliable; --model <id> or --model auto
          names the model for this run and wins over all of those), on a copy
          of what may enter by limits L1 to L6 (runtime/workcopy.py). What the run left comes back by the path rule
          (runtime/path_rule.py); then the task waits for you. Other tasks of the project may be running: up to
          max_running at once, each agent up to its max_parallel, never two that write the same file. Start it with
          the secret store's library available, as the eval runner is started:
            uv run --with keyring==25.7.0 python3 runtime/cli.py run-next --project <dir>
run-task  runs one named task in this process (--task <id>): what the dispatcher starts for every task it runs, one process
          each. It takes the task's lock, ends what dead processes left, and admits and claims the task under the claim
          lock; a task that was refused (not ready, waiting, a document not taken, a cap) is not run and exits 4, except
          when the reason is one of the words of the held tasks (a slot, the project's limit, an artifact in use), which
          exits 0 and prints it. A person uses run-next.
run-step  runs one named step task in this process (--task <id>), as run-task runs a task: what the dispatcher starts for every step
          task. A step task runs no skill and calls no model: code runs its steps (runtime/steps.py), the kind of the task names
          them (today `ingest`, which brings a version of a source into the project), and the task is `done`, `failed` (resumable at
          its step) or `waiting` at a stop for you. It takes the task's lock, so a killed process is detected by it and the task ends
          `failed`; stop-runs ends it. Same refusals and exit codes as run-task. The dispatcher starts only a kind that says it may run
          unattended (`ingest` does) and only while the runtime is not stopped, and it asks again under the claim lock (--unattended is
          the flag it starts the process with); your own start with run-step or run-next needs neither.
          Nothing but tests creates a step task today: the flow files learn `step` with P6. A stop of a step task asks for the verdict
          `continue` or `stop` (any other answer asks again).
pending   lists what waits for you; with --id, prints that pending decision whole: the reply, what came back,
          what was kept in the run folder.
answer    answers a pending decision; the task becomes ready and its next run is given your answer. The answer to a
          question may come back with "instruction_proposal": your own line, offered once per request as a line for the
          project's instructions; it is added only by instructions-add. With
          --with-comments, the comments saved from the task board for that task, and from the documents platform
          for the documents its skill writes, are added to your answer, under
          "Comments left on the platform:"; without it, no comment enters an answer.
release   releases a delivery (a pending decision of kind review): the task is done and what depended on it
          becomes ready. The delivery stays a draft: releasing is not approving. A run that wrote a document
          and still asks (ending draft_with_questions) opens a review too: release it as it stands, its open
          questions left in it, or answer it. A run that wrote nothing and asks opens a question: answer it.
retry     makes a failed or blocked task ready again.
go-ahead  (--task <id>) ends the derived waits of a task that waits for another request's task, and records your decision in
          the state file; an `after` request is yours and stays unless you add --drop-after, which ends it for that task.
          approve takes --go-ahead <task key> for a plan's tasks.
cancel    cancels a request, its tasks that are not done and their open pending decisions.
status    requests, tasks (each with its title and area agent) and pending decisions (each with its task's "agent" and
          "actions", the words it may be resolved with), from the store's records; for each request and task, whether it is
          on the task board and how many comments saved from there are open; each mirrored document, its status
          and its note.
task      one task or request: its row, its runs (status, failure, ending, attempts, duration, tokens, cost, model) and
          its pending decisions of every status, each with "actions". For a request: the router's runs and the
          decisions on the request itself.
flows     the workflows: the flow files of this checkout (flows/*.json) and of the project (docs/workbench/flows/*.json, the
          person's own, versioned with the project): each one's name, title, origin, number of tasks, parameters, step kinds and
          the result of the flow check; a file that fails its checks is listed with its error.
flow-check  the flow check of one workflow: a task that requires the web must not receive sources (the ones it lists and those
          of the ingest steps before it). For a skill that reads a research brief it offers the split the code makes: a research
          task with the web and no source, then the skill without the web, with the sources and the brief. For any other skill it
          asks you which way to go. It writes nothing; `next` is the command that saves the split.
flow-save saves an approved plan (--id: the plan's pending decision, resolved approved) or a workflow already there (--flow)
          as the workflow --name of the project, in docs/workbench/flows/<name>.json: a plan without a text of its own for a task
          becomes a workflow with the parameter `request` (your words are its default). The flow check runs first; a finding
          refuses the save, nothing is written, unless --split makes the code-made split. An existing file is replaced only with
          --replace. A name of a workbench flow is refused. Run it by `route --request <id> --flow <name>` (with --param
          name=value for its parameters).
instructions  the project's standing instructions: docs/workbench/instructions.md, a Markdown file only you write. Every model run of the
          project (a task, the planning agent, a handler's agent run) receives its text in the prompt, after the task's paragraph; a run
          that is a step (code) does not. The text never replaces a skill's stop rule, a confirmation gate, an approval or a limit of the
          runtime. It prints the path, whether the file is there, its sha256, its characters against the cap of 4,000, the problem that
          would stop a run (a credential, an invisible character, a line of the form `--- ... ---`, a link, text that is not UTF-8, a file
          over the cap) and the text. A file with a problem stops every run of the project until it is fixed; nothing is cut.
instructions-set  replaces the whole text of the file (--text or --text-file; an empty text clears it). --base-sha256 is the sha256 that
          `instructions` printed (none when the file is not there): a file changed since is never overwritten, and the refusal shows the
          current hash. Only the terminal and the page write the file (limit L40). A change of the file changes the hash of every routine
          of the project, which then stops at its next fire and asks you to approve it again.
instructions-add  appends one line `- <text>` to the file, with the same base hash and the same rules.
routines  the routines: a workflow started by a schedule. Each with its state (draft, active, paused, stopped, cancelled), schedule,
          the hash of its content now against the hash you approved, and its last fire; with --id, its fires (a slot is fired once; a slot
          missed is skipped and noted, and only the newest missed slot younger than the window is made up) and, for a routine not approved,
          what approving it needs.
routine-create  makes a routine as a draft; it fires nothing until you approve it. The workflow must pass the flow check and take no file. The
          schedule is every day at HH:MM, every week on a weekday at HH:MM, or every N minutes (15 to 720, dividing a day). --model is an id of the
          gate file, auto (with --provider, the providers it may use: the cheapest reliable pair inside them, and a better candidate outside
          them stops the routine and asks) or none (the project's default). --consent (terminal only; the page sends the hash of the warning)
          is the routine's own consent for a fixed model that has no evidence: its tasks' reviews are released by their agent's mode, each
          run recorded as autonomy by consent; a change of the model asks again. The agent's consent is never read for a routine.
routine-change  changes the fields given; the approval is cleared and the routine is a draft again.
routine-approve  without --sha256 prints the preview and the hash; with it, approves exactly that content: the schedule, the workflow's template and
          fixed arguments (not the dates), the X.Y of each skill (a Z change stops nothing), the eval image, the model and consent, the
          providers, and the sha256 of the project's instructions when the file is there. At each fire the hash is computed again; if it differs the routine stops and a question says what changed.
routine-pause  pauses an active routine: nothing fires while it is paused, and the slots it passes are not made up.
routine-resume  resumes a paused routine; its approval stands, and every fire still compares the hash.
routine-cancel  cancels a routine for good (it is never deleted; its fires stay on record).
stage-file  copies one file of yours for a request that waits for its plan (.workbench-local/drop/request-<id>/), with every
          check of hand-over (a regular file, a plain name, a size cap, no credential, a git project that ignores the folder, a
          name not taken). A workflow with a file parameter names it (route ... --param survey=<name>) and its plan carries the
          hash of those bytes; approving the plan checks the hash again and moves the file into the drop of the task that reads it.
agents    each area agent of runtime.json: its pack, whether it is enabled, the mode it is set to and the mode it acts in now,
          its two daily caps, what it used today (runs on a subscription or free credential, dollars of runs on a metered
          one, the metered runs whose cost is unknown) and how many ready tasks wait for it. Computed from the configuration and the
          store's records; {"agents": []} without area_agents.
conversation  the messages of the project's conversation above a message id (--after, default 0), oldest first, at most
          500: id, role, text, the request it made or answered, the run, the time. The conversation is named project
          (--conversation is the store's name, and no other is in use).
skills    the skills in scope of the project (the packs of its agents, else the default pack): version, area, whether a
          runtime manifest exists, the proof on every model of the gate file as the proof file gives it (band, cause, score,
          mean, runs, the source of the evidence, the model's price with its date and the expected cost of a run), the runs
          of the skill in this project, and the two checks of the proof (the
          measurement files, the eval image). It calls no model.
costs     the runs from a day on (--since YYYY-MM-DD, default the last 30 days) by day, agent, model and adapter: runs,
          tokens, the cost the store recorded, and the cost recomputed from the token counts a run left and the prices
          of runtime/prices.json (with their source, date and whether the price is stale). A run whose token counts are not there, or a
          model with no price, has no recomputed cost; the row counts such runs as unknown_runs. Also the daily caps.
connections  which provider each requirement class of the skills in scope resolves to (providers/resolve.py), which
          secrets are found and where (the environment or the secret store; never a value), whether the eval image is on
          this machine and is the evidence's, and the platform: the machine's architecture, the evidence's platform, the one the eval image runs as here
          (here) and whether the two are the same (same: true, false, or null when unknown). It starts no provider and
          makes no network call.
artifacts the project's files under docs/ that are documents or machine files, each with its owner skill (the skill whose
          outputs name it), the area agent whose pack holds that skill, size, modification time, its kind (text, markdown, image or other, decided by the file's bytes, never its name alone) and
          whether a pending decision binds it. Never the runtime's configuration.
artifact  the text of one file under docs/ of the project (--path, relative to the project), read-only. Refused for a path
          outside docs/, a hidden file or folder, a link, the runtime's configuration, a file over 1 MiB or one that is not UTF-8 text.
config    the project's configuration: its path, its hash, whether you accepted that hash, and the data folder. The one
          command that does not refuse a configuration you did not accept yet.
proof     the model each skill in use would run on, with the bands and the two checks (the measurement files,
          the eval image). It calls no model.
verdict   records your verdict on what one run delivered (worked, corrected, failed), with the existing
          recorder (scripts/evidence.py), on the use the run recorded. One verdict per run; only you give one.
sync      mirrors the tasks with the project's task board (task_board in runtime.json): a title, a text or a
          comment you wrote there comes in, and three state moves are taken (ready on a failed or blocked task,
          cancelled on a request, done on a task waiting on a review); any other move is written back. An item
          you wrote there waits for your approve before it can be routed. With documents in runtime.json it then
          mirrors the documents a skill's runtime manifest lists: a page you edited comes into the project when the
          project's file is still what was last written there and the skill's checker passes (else nothing changes
          and the document is rejected, with the reason; no task that reads it runs until it is settled), and a
          document that changed in the project goes to the platform, its open comments saved first. --dry-run
          reads nothing and prints every write it would make. A page that changed since the last write is never
          written over: a read-only type's page (it carries a notice saying so) is rejected until settled.
          --take page|project with --path settles a rejected document: the page's text (for a read-only type,
          the page kept as it is and the file not mirrored until it changes), or the project's file over the
          page.
hand-over copies one file of yours into the task's file drop, <project>/.workbench-local/drop/<task id>/: it
          enters that task's runs and no other, and the run's prompt lists it; what a run leaves there never comes
          back. Refused for a link, a folder, a file over 25 MB, a name with other characters than letters,
          digits, '.', '_' and '-', a name already handed over, a task that is done, cancelled or running, a
          file holding what looks like a credential, and a git project that does not ignore .workbench-local/. A task
          whose skill uses the web takes the file too (the maintainer's decision: the file is the person's own choice)
          and the answer carries "web": true and the line "this file will be visible to a run with the open network".
source-add  registers a source of the project: an id (lowercase letters, digits, hyphens), its type (file, notion or drive) and its origin (a
          file's name, a Notion page's address or id, or a Drive file's id); nothing is imported and no credential is kept. The registry is in the
          store; the versions are in the project's sources folder (sources_dir of runtime.json, runtime/sources.py).
source-import  imports a version of a source from a file of yours (--file) or from a Notion page (--url): the generic intake
          bounds the length and reads the type from the bytes (PDF, Word, spreadsheet, CSV, HTML, text), a container with no network
          converts it to text with adopted open tools, the text is scanned for credentials (a key inside a PDF's compressed text is
          found there), and the original, the converted text and a manifest are kept as an immutable version. A Notion page is read
          with its own read-only secret (NOTION_SOURCES_TOKEN), never the one that writes. An unregistered id is registered.
source-refresh  makes a new version: from a new file (--file), from the Notion page again, or, with neither, from the file you
          changed in the sources folder (the files are hashed against the record; a changed one is sniffed, converted and scanned
          again, and becomes a version labelled as yours, which a task that starts on its own never receives).
source-describe  sets your description of a source, which the planner reads with its catalog; no --description clears it.
source-drive  makes Google Drive files sources. It opens the Picker on a one-shot page on 127.0.0.1 (the command prints the address and
          opens your browser): you choose one or more FILES, never a folder (a picked folder gives the app nothing inside it), and each
          becomes a source, named from the file, with its first version imported (a Google Doc as Markdown, a Sheet as a workbook, Slides
          as a PDF, any other file as it is, then the same converter, scan and rows as a file of yours). With --file-id and --source, one
          file you picked before is imported or refreshed. source-refresh asks Drive for the file's version and reads it only when it
          moved. Needs the one-time authorization: uv run providers/documents/gdrive_auth.py authorize. The scope, drive.file, lets the
          app read and write the files you pick, so it is not read-only; the runtime asks for reads only.
sources   the catalog of the sources: each one's newest version (name, type, size, date, sheets and columns with sample values,
          first headings), your description, and whether its files changed outside the runtime. It calls no model.
deps      installs the dependency sets of runtime.json ("dependencies") by code, with no model: in the eval
          image, in a step that sees only the dependency files, on the open network; the result is cached under
          the data folder by the files and the image, and a run whose copy holds versioned files gets a copy of it.
progress  where the work stands (each open request, what waits for you, what is stuck) and what happened in a
          period (default the last 7 days; --since <n>d or a date YYYY-MM-DD): deliveries, runs, the known cost and
          the runs without one, your decisions and those of an autonomy mode, the effects executed. Computed from
          the store's records; it calls no model. "text" holds the same as plain lines.
approve-policy  approves a policy file for one area agent (a standing approval). Without --sha256 it shows the
          file's bounds and hash and writes nothing; type the hash it shows with --expires, a date at most 365 days
          ahead. A bounds file (docs/workbench/policies/<policy>.json) is checked whole; any other file under docs/
          (an engagement policy) is bound by its hash only. An earlier approval of the same policy and agent is
          revoked; the state file's Approvals table gets the generated row a skill's gate reads. An edited file is
          covered by nothing until you approve it again. Only an agent in the mode autonomous-with-policy acts on it.
revoke-policy  ends a standing approval; its row leaves the state file.
standing  whether an active standing approval covers a policy now, and why not; it executes nothing.
execute-under-policy  the one place an effect under a standing approval is executed: it checks the effect document a
          handler wrote against the approval's bounds, holding the write lock, makes the provider's dry run and its
          confirmed call, and records the action. {"executed": false, "why"} when the approval does not cover it:
          nothing ran. A handler never confirms a provider verb itself.
set-mode  for the agent `runtime`, the owner of step tasks: stopped or autonomous, the brake of step tasks (the dispatcher starts none
          while it is stopped; run-next and run-step still run one), kept in the store, nothing to accept. For an area agent:
          sets its autonomy mode in docs/workbench/runtime.json (area_agents): stopped (it starts
          nothing), supervised (every delivery waits for you), milestones (the default: a milestone waits, the rest is
          released by the mode), autonomous (only what must reach you waits), autonomous-with-policy (as autonomous,
          and an effect inside a policy you approved runs without asking). A question, an unclassified reply, a
          draft with open questions and a mandatory milestone always wait for you. The modes are in that order, the
          least first. A move down it (stop, supervise) widens nothing: code accepts the new hash at once and says
          `code:narrowing`, so nothing refuses afterwards. A move up never is accepted by code: with --accept (this
          command, in the terminal, never the page) you set it and accept the new hash in one step, recorded
          `person`, but only when the file was the accepted one before the change, so the one difference you accept
          is this mode; with another unaccepted change in the file, it is refused and writes nothing: read the file
          and run accept-config. Without --accept, accept the new hash with accept-config, after reading the file;
          either rewrites the Checkpoints line of the state file. Raising an agent that is fixed to a model to an
          autonomous mode needs your consent (the warning is printed with the refusal): --consent is that consent, a flag of its
          own and not --accept (which accepts the hash); with it the warning is printed again. A move down is never withheld
          and never asks: the consent for autonomous-with-policy follows to autonomous.
set-model fixes one area agent to a model (an id of evals/eval-gate.json), to auto (its tasks go to the cheapest model on
          which the skill is reliable) or to default (no model of its own: the request's, else the project's
          default_model, else auto). On an agent in an autonomous mode, fixing a model is your consent (decisions D34 and
          D38): the warning is printed with the refusal and the command with --consent (the consent, a flag of its own) and
          --accept (the hash, in the same step); --consent is the terminal's, and the page gives the same consent on its
          own with the exact warning it showed (give-consent), never a messaging channel or the MCP mode; the consent is
          stored with the agent and names the model and the mode, so changing either asks again. From then on the reviews of that agent's runs on that model, even with no
          reliable evidence, are released by the mode, and each such run is recorded as autonomy by consent, never as
          proven. Without --accept the hash is accepted with accept-config, after reading the file.
contained-run  one run of one skill of an area agent's pack, once, in the eval container, on a copy that holds only the
          artifacts the skill declares (never runtime.json, never a versioned file the skill does not declare), on the
          model the skill's proof gives, with no credential but the model's own, no open network and no retry, within
          --timeout-seconds (the gate file's when absent). Nothing is brought back: no file the run created or changed
          reaches the project (their number is "ignored_changes"). The reply, past the credential scan, is written to
          <out>/response.md, and <out>/timing.json holds total_tokens, duration_ms, exit_code and cost_usd (null unless
          the run's credential is metered). Each --platform names a platform whose reference the run is given besides the ones the skill
          cites. Exits 0 when the model answered, 1 when it did not (the result is still printed), 2 for a skill outside
          every pack of the configuration, 3 when no run could be made (no eval image on this machine, a platform with no
          reference): the image is never built. It calls a model.
dispatch  one round of the dispatcher: the ticks of the handlers whose dispatch is true, the deliveries each area
          agent's mode releases (released, never approved), and every ready task that the agent's mode, its daily caps
          (runs per day on a subscription or free credential, dollars per day on a metered one), its slots, the project's
          max_running and the files in use allow, each as a process of its own (run-task). Here it waits for them: it
          keeps reaping and deciding until none of its children is alive, so that the scheduler's worker job, which calls
          it, never returns while a run is alive. It calls a model, like run-next.
poll      the short job: mirrors the task board and the documents, expires standing approvals, rewrites the state file's
          generated lines, and releases what a mode releases. It calls no model and starts no task.
pin       writes the pin of the dispatcher's two jobs (<data_dir>/dispatch-pin.json): the path and the hash of the
          accepted runtime.json. The scheduler's entry (runtime/dispatcher.py) refuses to run when the file changed;
          after any change: accept-config, pin, then schedule both jobs again with the new command files.
say       one turn of the conversation with the planning agent (the same as one line of runtime/chat.py): a command
          (/help lists them), the answer to its question, or a new request, which runs the router (a model call) and
          shows the plan; refused when the planning agent is stopped or at its cap. A line that asks about the state
          ("status", "how are we", "como estamos", "o que falta", "what is running") is answered at once from the
          store's records, with no model and no request; a line that needs the planner, typed while another
          run of the project is in progress, is refused before it is stored (only the local page queues one).
handler   starts one verb of a handler (runtime/handlers/) that handlers in runtime.json names, and prints its result.
stop-runs ends the runs this process started (its children, the container and the process group of each run). The local
          service calls it before it exits; started on its own it has no run to end. With --all it ends every task run of
          the project that a live process holds, whoever started it (by the process group its task lock names; a lock
          nobody holds is never signalled). To keep the dispatcher from starting more, stop the agent: set-mode stopped.
service-check  what the local service checks at its start, for this project: whether this interpreter can read the
          secret store, whether the default model's credential is set or in it, docker on the PATH, the eval image on
          this machine, and whether a service dispatches (--dispatch-every <seconds>; absent: "not a service"). It starts
          nothing and remembers nothing when run here: the service calls it, and `connections` and `status` show its
          answer.
accept-config  records the hash of docs/workbench/runtime.json you accept. Type the hash the refusal shows, after
          reading the file. Every other command refuses a file with another hash.

--text-file - reads the text from standard input.
The project is configured in <project>/docs/workbench/runtime.json (runtime/project_config.py).
Prints one JSON object on stdout; diagnostics on stderr.
Exit codes: 0 ok, 1 the operation failed or was refused, 2 usage error, 3 the project is not configured, 4 refused and
not run (run-task and run-step only).
Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ops  # noqa: E402  (the same folder)

table = ops.operations  # the table of operations, re-exported by the operations layer


class Usage(Exception):
    pass


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise Usage(message)


def dest_of(arg: dict) -> str:
    """The name a flag's value is kept under: never `verb` or `text`, which a flag and the command word both use."""
    return "f_" + table.flag_of(arg).replace("-", "_")


def build_parser() -> Parser:
    """The parser of every verb: the command word, --project, and every flag of every row of the table, once
    (the same flag of two rows is the same kind: a test checks it)."""
    p = Parser(prog="cli.py", add_help=False)
    p.add_argument("command", choices=table.terminal_verbs())
    p.add_argument("--project", required=True)
    seen = set()
    for row in table.OPERATIONS:
        if "terminal" not in row["channels"]:
            continue
        for arg in row["args"]:
            flag = "--" + table.flag_of(arg)
            if flag in seen:
                continue
            seen.add(flag)
            kind = arg["kind"]
            if kind == "text":
                p.add_argument("--text")
                p.add_argument("--text-file")
            elif kind == "int":
                p.add_argument(flag, dest=dest_of(arg), type=int)
            elif kind == "flag":
                p.add_argument(flag, dest=dest_of(arg), action="store_true")
            elif kind == "choice":
                p.add_argument(flag, dest=dest_of(arg), choices=arg["choices"])
            elif kind in ("pairs", "list"):
                p.add_argument(flag, dest=dest_of(arg), action="append", default=[])
            else:
                p.add_argument(flag, dest=dest_of(arg))
    return p


def text_of(a) -> str:
    if (a.text is None) == (a.text_file is None):
        raise Usage("give exactly one of --text and --text-file")
    if a.text is not None:
        return a.text
    try:
        if a.text_file == "-":
            return sys.stdin.read()
        with open(a.text_file, encoding="utf-8") as f:
            return f.read()
    except OSError as e:
        raise Usage(f"--text-file: cannot read {a.text_file}: {e.strerror}") from None


def pairs_of(items: list, flag: str) -> dict:
    pairs = {}
    for item in items:
        if "=" not in item:
            raise Usage(f"--{flag} takes <flag>=<value>, not {item!r}")
        key, value = item.split("=", 1)
        pairs[key] = value
    return pairs


def file_text_of(path: str, flag: str) -> str:
    """The whole text of the file a `file` argument names, line ends as they are."""
    try:
        with open(path, encoding="utf-8", newline="") as f:
            return f.read()
    except (OSError, UnicodeDecodeError) as e:
        raise Usage(f"--{flag}: cannot read {path}: {getattr(e, 'strerror', None) or 'not UTF-8 text'}") from None


def run_row(argv) -> tuple:
    """(row, result) of one command line."""
    a = build_parser().parse_args(argv)
    project = os.path.abspath(a.project)
    row = table.by_name(a.command)
    kwargs = {}
    for arg in row["args"]:
        flag = table.flag_of(arg)
        if arg["kind"] == "text":
            kwargs[arg["name"]] = text_of(a)
            continue
        value = getattr(a, dest_of(arg))
        if value is None and arg.get("required"):
            raise Usage(f"{a.command} needs --{flag}")
        if arg["kind"] == "pairs":
            value = pairs_of(value, flag)
        elif arg["kind"] == "file" and value is not None:
            value = file_text_of(value, flag)
        kwargs[arg["name"]] = value
    if row.get("channel_arg"):
        kwargs["channel"] = "terminal"
    return row, getattr(ops, row["call"])(project, **kwargs)


def run(argv) -> dict:
    return run_row(argv)[1]


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or "--help" in argv or "-h" in argv:
        print(__doc__.strip(), file=sys.stdout if argv else sys.stderr)
        return 0 if argv else 2
    try:
        row, out = run_row(argv)
    except Usage as e:
        print(f"error: {e}. See --help.", file=sys.stderr)
        return 2
    except ops.OpsError as e:
        print(f"error: {e}", file=sys.stderr)
        return e.code
    json.dump(out, sys.stdout, ensure_ascii=False, indent=1, default=str)
    print()
    if row["name"] in ("set-mode", "set-model") and isinstance(out, dict) and out.get("warning"):
        print(f"consent recorded for {out['agent']}: {out['warning']}", file=sys.stderr)  # the warning the consent answered, once more
    if row["name"] in ("run-task", "run-step") and out.get("ran") is None and not out.get("held"):
        return 4  # refused, not run: the dispatcher that started this process records it (ops_runs.reap)
    unless = row.get("exit_unless")  # the row says which result is not a success; the result is printed either way
    return 1 if unless and out.get(unless[0]) != unless[1] else 0


if __name__ == "__main__":
    sys.exit(main())
