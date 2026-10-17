#!/usr/bin/env python3
"""Run a skill's evals with and without the skill, on one or more models, and grade them.

Usage:
  python3 eval_run.py --skill <name> [--cases <id>[,<id>...]] [--baseline] [--baseline-on <model>]
                      [--model <id>]... [--harness <adapter>] [--grader <id>] [--threshold 0.8]
                      [--only with|without|ablated] [--pass-env <VAR>]... [--ablate <text>]
                      [--runs <n>] [--jobs 4] [--timeout <seconds>] [--max-cost-usd <amount>] [--no-grade]
                      [--retries <n>] [--early-end-rate 0.15] [--scratch]
                      [--dry-run] [--check-cases [--with-setup]]
  python3 eval_run.py --skill <name> --platform <platform> [--cases <id>,...] [the model, run and check options above]
  python3 eval_run.py --skill <name> --quick [--model <id>]... [--jobs 4] [--timeout <seconds>] [--max-cost-usd <amount>]
  python3 eval_run.py --skill-dir <folder of a skill from outside> [--quick] [--cases <id>,...] [--baseline] [--model <id>]...
                      [--jobs 4] [--max-cost-usd <amount>] [--allow-web-cases] [--dry-run | --check-cases]
  python3 eval_run.py --resume <event folder> [--jobs 4]
  python3 eval_run.py --close <event folder>
  python3 eval_run.py --routing --pack <name> (--skill <name> | --prompts <file>) [--model <id>] [--jobs 4]
  python3 eval_run.py --unpause [--at <HH:MM or YYYY-MM-DDTHH:MM>]
  python3 eval_run.py --regrade <run folder> [--grader <id>] [--harness <adapter>] [--jobs 4] [--timeout 1800]

Models. There is no fixed pair of models: an event runs the models it is given, in order. --model <id> is
repeated, once per model; the first is the lead model (the event is full by it, and its baseline runs by default)
and the others follow in the order given; without any --model, the event runs the gate file's "lab_models", in its
order. A model the gate file lists ("models" of evals/eval-gate.json) takes its entry's adapter ("adapter") and the
variables of its key ("pass_env"; on a run of a case on the open network, "web_pass_env" in place of it, when the
entry has one); an id is also accepted by any alias its entry lists. A model it does not list (a person's own test) is
any other well-formed model id: --harness <adapter> is then the adapter of every model of the event that the file does
not list, and its key reaches its runs only through --pass-env. When every model of the event is listed, --harness
is accepted only for an event of one model, and replaces that model's adapter (such an event is a person's own test);
for an event of several models it is refused. --pass-env <VAR> (repeated) reaches every run of the event, and makes the
event a trial. --threshold defaults to the gate file's, and 0.8 without the file; without it, --harness and a --model
are required. Whose evidence a test is follows from the models it ran (below, "Evidence"): the gate file's lab models
write into the skill; any other model writes to the person's local evidence folder, outside the checkout.

A local model (backlog N14). --model local/<name> runs a model served on this machine: <name> is an entry of the local
models file ($XDG_CONFIG_HOME/openhora/local-models.json, else ~/.config/openhora/local-models.json; evals/local_models.py
describes it and `python3 evals/local_models.py check <name>` shows what an entry resolves to). The runner hashes the
weights once per event (and again on --resume) and runs the model under its full id, local/<name>@<12 hex of the sha256>.
Each run gets a model server container of its own beside it (evals/executor.py, "A local model") that the run reaches
and nothing else. A local model is tested alone (an event that mixes it with another model is refused), through the
agents-dir adapter (any other --harness is refused), with no web case (a stated error names the cases; --cases chooses
the others), with --jobs at most the entry's "parallel" (a note says so), and with the entry's timeout_seconds as the
configured limit of the event. Its evidence is a person's own: it goes to the local evidence folder and the event line
carries "local_model" (the weights' hash, file type, context, accelerator, the server image and version, the hash of its
arguments). The weights are checked against their (device, inode, size, mtime) before every server and at the end of the
event: a change fails the run as infrastructure and makes the event a trial. The grader is still the gate file's: a local
test makes paid grading calls on the grader's account. The runtime never runs a local model.

The grader is a model of its own. "grader" of the gate file names a listed model, and every grading goes through that
model's entry: its adapter, its runner, the account-limit markers of that adapter and the variables of its key,
whichever models the event runs and in whatever order (a model of the event that is also the grader is graded by the
same entry). The grader's variables reach the grading calls and are looked for in what a run left, also when the grader
is not one of the event's models. --grader names another model and makes the event a trial; a grader the file does not
list (or no gate file) grades through the adapter of the event's model of that name, else the lead model's.

Full and partial tests (the reliability model, section 2). `eval_run.py --skill <name>` is a full test:
every current case with the skill, on every model the gate file lists, "runs" times each, and the baseline
(the case without the skill, on the lead model) of each case whose baseline is not in
force. In a full test a baseline runs "baseline_runs" times (evals/eval-gate.json; without the key, as many as
the runs); --baseline runs it as many times as the runs. A baseline is in force while its case (its hash), the
lead model (no epoch of it after the baseline's date) and the measurement (its version at or above the
floor) are unchanged and it has as many lines as a full test runs it: it is reused, and the event line says
"reused". `--cases <ids>` is a partial test: the named cases, with the skill only. `--baseline` runs the
baseline of the cases the event runs, in force or not (for a case added or changed after the newest full test:
`--cases <id> --baseline`, which is how such a case enters the gate).
`--baseline-on <model>` (repeatable) also runs the baseline on another model of the event, for
whoever wants that column. An event is full by its lead model (the first --model, by default the first of the gate
file's "lab_models"): it is complete when every run with the skill and every baseline run on that model is graded. A
run that is missing on another model leaves it complete; that run is listed and the event exits 1, its evidence
is written, and that model has no gate in the event.
Only a full test evaluates the gate, when it ends, and writes it into its event line, for each model of the event
whose runs were all graded: over the run lines of kind full with the skill on that model of the X.Y version its
newest full test ran on, its own and those of every earlier full test that lists the model, of that X.Y and
epoch (a second full test of an unchanged X.Y adds its runs and replaces none; a full test of another model
changes nothing of this model's gate), every current case required, against the mean of the baselines in force
for that model (evals/eval_status.py gate [--model <id>]).
A partial test never moves the gate. (A closed pool, below, is evaluated by the status script from the lines, not by an event.)
An interrupted event is resumed (--resume). A full test or a quick test that is abandoned instead is closed:
`--close <event folder>` writes its file into the skill as an incomplete event, whose lines stay in the gate of
that version, where the next full test adds its own. While an event of a skill that may write evidence is
open (neither complete nor closed), the runner starts no new such event of that skill: a test that is going
badly cannot be interrupted, dropped and drawn again. A trial (below) is never open in that sense.

Quick tests (--quick; package P11). `eval_run.py --skill <name> --quick [--model <id>]` runs every current case once with
the skill, on every model the event runs, and nothing else: no baseline (the event line says "none" for every case), no
gate, an event of the kind "quick" whose "runs" is 1, about a third of the with-skill cost of a full test. It is
PRELIMINARY ALONE: it moves the score, it satisfies the guard assertions it runs, and it never moves a band or the gate.
What it adds up to is the pool: the with-skill lines of one skill, one model and one evidence source (lab, local or
community: never mixed), of the current X.Y since the newest epoch, from full, partial and quick events together. The
pool's gate reads, per case, only the first "runs" (3) lines in time order; later lines count for the score and nowhere else.
A pool closes when every current case has that many lines and a baseline in force, and, for community evidence, when the
counted lines come from at least two contributors, none holding more than two thirds of them (a contributor's lines in one case
count up to two of the three, the rest count for the score alone); a closed pool is evaluated by
the unchanged rule of the gate and counts as a full test (eval_status.py, "The pooled gate"). To iterate on a skill that is
being written, run the quick test as a trial: --quick --scratch writes no evidence and blocks no later event. The same event rules hold as for the other kinds: an open event of the skill must be
resumed (--resume) or closed (--close) first, evidence is written only at the configured values and in the eval container.
--quick cannot be combined with --cases, --baseline, --baseline-on, --platform, --runs, --only or --ablate: it chooses
nothing but the model.

A skill from outside (--skill-dir; package IMPORT-CLI, scripts/skill_import.py). `eval_run.py --skill-dir <folder> [--quick]
[--cases <ids>] [--model <id>]... [--dry-run | --check-cases]` tests a skill that is not in skills/: <folder> is its folder,
whose name is the skill's and is not the name of a folder of skills/ (--skill-dir is exclusive with --skill). Staging does
not change (the folder is copied into each run like any skill, without its evals/ and scripts/tests/), and the cases are
the folder's own (<folder>/evals/evals.json, fixtures under <folder>/evals/files/), written by the person who imports it.
Its evidence is always the person's own: it goes to <local evidence base>/imported/<name>/, never into the checkout, and
its event line carries "imported": true (eval_status.py refuses a committed file that carries it). Refused: --pass-env and
--harness (a model of the gate file runs through its entry's adapter and key proxy, and no variable of the person's reaches
the run of a skill nobody has read), --platform, --routing and --regrade; a folder that holds a symbolic link anywhere; a
case with "workbench_files"; and, for a real event (not --dry-run, not --check-cases), a folder with no audit record
(<folder>/evals/import/audit.json, written by scripts/skill_import.py audit) whose verdict is not "do not install" at the
folder's current content hash. A case with "allow_web" runs only with --allow-web-cases and an audit verdict of "install": the
open network could hand the person's fixture files to any host. `eval_status.py status --skill-dir <folder>` shows the
figures, and says that a quick test alone is preliminary.

Tests per platform (--platform <platform>; the plan's decision 14c). The cases of one social platform live in
skills/<name>/evals/platforms/<platform>.json (its top-level "platform", when present, names the same
platform), their fixtures under skills/<name>/evals/platforms/<platform>/files/. `--platform <platform>` runs
that file's cases (all, or those --cases names) as a partial test, with the skill only, on every model the
event runs: no baseline, and nothing is refused for want of a full test or of a base result. Each case's run
gets the platform's reference and data file staged beside the skill, as if the case named the platform in
"platforms". Its run lines carry "platform": <platform>; the gate and the score never read them, and
`eval_status.py status` shows their mean and number of runs per platform and model, and no score.
--check-cases checks evals/evals.json and every platform's case file of the skill (with --platform, that file
only), and a platform's file whose reference shared/references/platforms/<platform>.md is missing.

The routing mode (--routing). A description decides when a skill loads, and a skill is never alone once a
pack is installed. --routing --pack <name> installs the whole pack into each run's folder, as an installer
does (scripts/stage_skills.py, every shared reference beside it), runs each prompt once on one model (--model, once;
by default the first of "lab_models"), and reads which skills the run loaded ("skills_loaded" of the adapter's
timing.json). With --skill <name> the prompts are that skill's case prompts, each in its case folder as a run
builds it, and the output lists the cases in which another skill loaded, or the skill did not load: this is
what a change of a description runs, beside its partial test. With --prompts <file> (a JSON list of texts)
the prompts run in an empty folder and the output lists what each loaded. It scores nothing and writes no
evidence: its folder is evals-workspace/routing/<pack>-<n>/, and it prints
{"routing", "pack", "model", "skill", "prompts": [{"case" or "prompt", "loaded", "invoked",
"others"}], "loaded_another": [case ids], "not_reported": n}.

Reads skills/<name>/evals/evals.json. For each case and each variant (with_skill, without_skill)
and each model, it prepares a working directory with the case's files (paths inside the skill folder
only) in its own git repository (one "fixture" commit, then the case's optional "setup" shell commands,
such as a branch with commits), stages the skill under test (with-skill runs only) and the skills listed in
the case's optional "skills" (a flow's phases; both variants) where the harness discovers them, runs the
prompt through adapters/<harness>/run-prompt.sh, grades every assertion with
the grader model (see "Grading" below), and writes:

  evals-workspace/<name>/iteration-N/eval-<id>/<variant>[.m2|.m3...]/{prompt.md,cwd/,outputs/,grading.json,timing.json}
  evals-workspace/<name>/iteration-N/benchmark.json

The variant folder of the lead model's runs is the variant's name (with_skill); the n-th model of the event, from
the second, adds ".m<n>" (with_skill.m2). The slots m1, m2 ... name the position in the event, not a kind of model.

Control of a test event. One invocation on one skill is a test event; its folder is
evals-workspace/<name>/iteration-N. The number of runs of every case, variant and model ("runs", 3), the limit
of one model run ("timeout_seconds", 1800) and the retries inside the event ("retries", 2) have one home, the
gate file evals/eval-gate.json. --runs, --timeout and --retries override them for a trial: each run gets its
own folder, run-<k>/, and benchmark.json averages them, but **evidence is written only by an event that used
the configured values and real runners**. An event with another number of runs, another timeout or other
retries, with --scratch, with an extra variable passed into its runs, with a stand-in runner (anything but
the eval container), on an image of another CPU platform, or made while the measurement version is open
writes the same files into a scratch tree inside its run folder, <event folder>/scratch/skills/<name>/, and
never into the skill's folder; benchmark.json says why in "scratch".
--jobs <n> (default 4, at most 8; the repository runs independent work in parallel, AGENTS.md principle 7)
runs that many model runs, with their gradings, at the same time in this process. Each run has its own
folders and a throwaway home, so runs share nothing. Across processes the limit is a lock that every runner
process of the machine shares (a folder of slot files under the temporary base): "total_jobs" of the gate
file (14) is the number of model calls in progress at one time, whatever the number of `eval_run.py` started
side by side, and "web_jobs" ({model id: runs}; a model it does not list takes 2) the number of runs on the open
network per model, whose search services limit the rate.
--max-cost-usd <amount> is passed to the adapter as a spend limit per run: the claude-code adapter
enforces it, agents-dir says it cannot (a credit limit on the provider key is the cap there).
Retries. A run that passes its timeout, that the provider refuses on policy grounds, whose adapter fails, or
that ends its turn early (below) is made again inside the event, up to "retries" times, with the skill and
without it alike, so that the difference between the two is not biased; each kind is counted per model and
variant in benchmark.json "counts" ({"attempts", "retries", "timeouts", "refusals", "adapter_failures",
"early_ends", "pauses", "resumes"}). What an attempt left is kept in the run folder (failed-<j>/,
early-end-<j>/). A run that fails on every attempt is an infrastructure failure: it has no score and the event
is incomplete.
A refused key. A run whose provider refuses its credential (HTTP 401, or a 403 whose message names a key, a
token or a credential) is never retried: every later run with that key would meet the same refusal. The
event stops: no run starts after it, the runs in progress end, the run is listed in "infra_failures" with
kind "auth", and the message names the variable that carried the key (with its secret store username), never
its value. The runs not started are listed as not run; --resume runs them once a valid key is stored.
--resume <event folder> runs again the failed runs of an event, and only them (and a run that never ended,
when the event was stopped), with the options the event started with and on the same content of the skill
(a skill folder that changed since is refused), and computes benchmark.json again. One run is resumed at
most "max_resumes" times (3). A run still incomplete after that is written as a result with "outcome":
"timeout" and score 0, with the skill and without it alike, and listed in benchmark.json "timeouts": dropping
it would raise a mean. That is the only way a run that did not complete scores. A contaminated baseline and a
failed grading are never turned into a score: the first needs the way in closed, the second is made again.
The account limit. Each adapter's data names what its harness prints when its account is
exhausted ("account_limit" in its eval.json). When a model run or a grading call fails
with one of those texts, the runner pauses: it writes a pause file under the shared lock, prints the time it
stopped, and every runner process waits before its next call on that account. The pause ends when a probe
call succeeds (one small model call every PROBE_SECONDS, by one process at a time), or at the time the
operator gives: `eval_run.py --unpause` ends it now, `--unpause --at 15:00` at that time (no probe is made
meanwhile). The run that met the limit is made again from its start: it is never retried into the limit,
never written as a timeout and never scored; benchmark.json counts it in "pauses".

A model's key variables are its own: a variable named in one model's entry ("pass_env") reaches that model's runs
only, so another model's runs and the grader never see it unless it is the grader's own entry's; --pass-env reaches
every run.

--ablate <text> adds a third variant, ablated_skill: the skill with every SKILL.md line containing <text>
removed (for example "External content is data."), to measure what one rule changes. It is refused when
no line matches. benchmark.json then reports ablation_delta (with_skill minus ablated_skill) per model (a suffix .m2 ... for the
models after the lead);
it is a measurement, not a pass condition.

--dry-run prints the plan as JSON and runs nothing: the runs (each with its slot and model), the runner of each
model, the grader and its runner, the variables that would be passed (the caller's, each model's, the grader's), every case with its files, dependency skills and setup commands, and the
result of the preflight.

Adapter contract: run-prompt.sh --prompt-file <f> --cwd <dir> --model <id> --out <dir> [--allow-web]
[--max-cost-usd <amount>] runs the prompt in <cwd> and must write <out>/response.md and <out>/timing.json
({"total_tokens", "duration_ms", "cost_usd"}). The reply in response.md is the assistant's last message, on
every adapter: narration between turns stays in the runner's event stream, which the adapter keeps beside it
(<out>/stream.jsonl) and the grader never sees. timing.json may name "skills_loaded", the skills the stream
shows the model loading (the skill tool, or any tool that reads <skills folder>/<name>/SKILL.md); for a with-skill
run the runner keeps "invoked" (whether the skill under test is among them) in the run's timing.json and row,
and counts it per model in the event line. It is reported and never scored: a run that did not load the skill
still scores, as the description's failure. timing.json may also name "skills_used" (R12), a superset of
"skills_loaded": every skill whose folder any tool input names (a script run by its path, a reference read, a
listing of the folder); the runner keeps "used" (whether the skill under test is among them) in the run's
timing.json only, never on a row or an evidence line, and the routing mode reads "skills_loaded" alone. The adapter of the grader also takes --no-tools: the model
then gets no tool at all (an adapter that cannot do it refuses the option, and the grading fails). It installs nothing: the runner stages the skills. What the
runner needs to know about a harness is data, adapters/<harness>/eval.json:
"skills_dir", the folder inside a project where the harness discovers skills, and "settings", the names of
the files and folders that carry the harness's settings or instructions at project level.

Staging. Before the container of a run starts, the runner copies into the case folder, through
scripts/stage_skills.py (the same module the installers use), the skill under test (a with-skill run only)
and the case's dependency skills (both variants) into <case>/<skills_dir>/<name>, never as links and without
their evals/ and scripts/tests/ folders. Of shared/references/, a with-skill run gets the files the skill
under test cites in its SKILL.md or in its own references, beside the skills folder so that
../../shared/references/<file> resolves, and the references of the platforms the case names in
"platforms": ["<name>"]; a without-skill run gets none of them, also when it brings dependency skills.
shared/scripts/ and tests are never staged. It happens after the fixture commit and the setup, so the
staged files are not part of the case's history, and each staged path is added to the case repository's
exclude list (.git/info/exclude), so `git status` and `git add -A` in a run do not see them.

What the host reads after a run. A run can leave anything in its case folder, a symbolic link to a file of
the host included. One function, run_files(), decides which paths of a case folder the host reads or writes
once a run has ended: regular files only, never a symbolic link, never a path whose real path leaves the
case folder (a link to a folder on the way), never version control, dependency or cache folders, never what
the runner staged. The list of files a run wrote and what the grader is shown go through it; a path it
leaves out is shown to the grader as a one-line note, never as content.

Harness settings. A case folder that holds, after its files and its setup, a file or folder whose name is in
the "settings" list of any eval adapter (at any depth, outside .git) is refused: the harness would apply
those rules, hooks, servers or instructions to the run. The preflight reports it for every case; a run
checks again before it stages.

Commands. Every command a model runs is allowed: the container a run executes in is the boundary
(evals/executor.py). A case names no commands; an evals.json that still carries "allow_commands" (the list
used while runs happened on a person's machine) is refused, so that no case keeps a setting that does nothing.

Web. evals.json may set "allow_web": true at the top level or per case, for a skill that must search
and read web pages (it requires search:web). The adapter then lets the model search and fetch pages,
and nothing else more; the grader never gets it. Without it a harness that asks before searching denies
the search, and a with-skill run of a research skill measures only its degraded mode.
The gate file lists the cases that may do so ("web_cases": {skill: [case ids]}): the runner opens the network
for no other case, and refuses to start on a case that sets "allow_web" and is not listed (a tree with no
gate file has no list and refuses nothing). On a listed case the runs of a model whose entry names "web_pass_env"
(a low-limit API key) receive those variables in place of its "pass_env" (for example the account's token): a run on
the open network reads pages written by others, and with a key a leak costs at most the key's limit. The gradings
of such a case keep the grader's own variables: a grading has no tool and no open network.
When a model's entry names no "web_pass_env", such a run receives its "pass_env", whose value the model's key proxy
holds outside the run.

Containment. Every model run, grading, setup command and fixture commit executes in a container built
from evals/container/, one container per command (evals/executor.py); there is no host mode. A container
sees the run's folder (read-write, the only thing a run can change: the case folder with what was staged
into it, the prompt and the output folder) and, for a model run or a grading, the one run-prompt.sh in use
(read-only). Nothing else of the machine or of the workbench: no adapters folder, no skill folder, no shared
folder, no home folder, no other checkout, no credential store. Network, per command: none for setup commands and the fixture commit; for model runs and gradings an
internal network whose only way out is a proxy that lets through the model providers' hosts
(evals/container/proxy/allow.txt); the default network only for a case with "allow_web": true.
Environment: the image's own (its clock is UTC, its locale C.UTF-8, and the one git identity of a run is the
image's: nothing of the caller's machine sets them), plus the variables that keep git inside the case folder
(GIT_ALLOW_PROTOCOL=file, no terminal prompt), the proxy's address on the proxy network, and the variables
named with --pass-env (every run) or
in a model's entry of the gate file ("pass_env": that model's runs only, so another model's runs never receive its
key; and the grader's gradings, for the grader's entry). A name among those that an adapter
registers as a secret for eval runs and that is missing from the environment is read from the OS secret
store through providers/secrets/resolver.py; values travel in the environment of the docker client, never
on a command line. Token variables for git hosts and npm are refused there. The docker client itself still
runs with an environment built from an allowlist on the host, with empty git, gh and npm configuration, but
only the names above cross into a container.
One credential never enters a run: the provider key of a model whose entry names a route, which the key proxy holds
(evals/container/keyproxy/route-<name>.json names it; evals/executor.py starts the proxy before a command that is
passed it). Such a run gets a placeholder in the variable and the proxy's base URL; the adapter points its runner there,
and the proxy adds the key to each call to the provider's API.
Secrets in what a run leaves. The credential of a run is in the environment of every command
the model runs, by necessity: the runner inside the container needs it. A model that prints its environment
puts the value in its reply, in a transcript or in a file. So after each run, before anything is read, stored
in the workspace or sent to the grader, the value of every variable passed into the run is replaced by a
marker, "[redacted:<NAME>]", in the reply, the adapter's other output (the transcript, the raw output) and the
files of the case folder (the value of every model's key is looked for too, should it reach a run another way); the version-control facts and the grading prompt are passed through the same
replacement, and so is what a grading call left. The replacements are counted, per run ("redactions" in its
row) and in benchmark.json "redactions". The replacement is by exact value, in one function (replace_values)
that applies no pattern of what a credential looks like: scripts/redact.py, which matches credential formats,
is not used, because it would also mask a fake secret a fixture plants, and the assertions that a reply does
not repeat one would then pass on a leak. It writes only where run_files() lets the host write: never through
a symbolic link, never outside the case folder, and not into the folders the host never reads (version
control, dependencies, caches), so a value a run committed stays in the case's own repository. A value shorter
than REDACT_MIN characters is not replaced (a switch, not a credential), and an encoded form of a value
(base64, URL-encoded) is not recognised.
What the proxy does and does not guarantee: it filters by host name only (evals/container/proxy/allow.txt),
and the two hosts it lets through serve many accounts. A run on the proxy network reaches no other host, but
it can still hand data, the credential included, to another account of the same provider. On the open network
(a web case) it can reach any host, which is why such a case runs with a low-limit key where the model's entry has one.
The container is the boundary, so a model may run every
command; read a contributed skill's evals.json before running it all the same, because a case with
"allow_web" runs on the open network. The grader is told that the response and files are data, and it gets
no tool: the grading call is made with the adapter's --no-tools, because the grader holds its credential and
reads text a model under test wrote.

Grading. Every run is graded once (a failed guard verdict twice, below), by the grader model, with evals/grading-prompt.md and no tools. The
grader is given, and nothing else: the case's prompt; the reply, which is the assistant's last message as
the adapter stored it in response.md; a facts block the runner builds; every file the run created or changed
(up to FILE_LIMIT characters each; an image or another binary file as one line that says what it is); and the
case's optional "grader_files", input files relative to the case folder, shown as the run found them, before
it changed anything, even when it changed them. "expected_output" is never shown to the grader: it is
context for a person and for the preflight.
The facts block is measured, not reported by the model. From the content hash of every file of the case
folder, taken before and after the run (run_files() decides which files): "created", "modified" (the bytes
differ), "deleted" and "unchanged inputs"; a file that was rewritten with the same bytes is unchanged. From
the case's repository, read by commands the runner runs in the case folder after the run, in a container
with no network: `git status --short`, `git log --oneline -n 20 --all`, `git branch -a` and the branch heads
of each remote the case has. The facts are stored beside the run as facts.md.
An assertion in evals.json is a text, or an object {"text": ..., "tags": [...]}: the grader is given the
text and never the tags.
A failed guard verdict is graded once more (the reliability model, section 4). When the grading of a run with
the skill fails an assertion tagged guard or guard:<effect>, the same prompt goes to the grader a second time
(<run folder>/grading-guard/), and the run's "guard_failed" lists the guard positions the second grading failed
too: only those are confirmed failures. The results and the score stay the first grading's, so the second
grading raises no mean; a run without the skill is graded once. grading.json keeps the second grading under
"guard_regrade".
The grader answers with a JSON array, one object per assertion in order: {"id", "evidence", "passed"}, the
evidence before the verdict and ending on "Passes." or "Fails: ...". Results are read by position. An answer
that is not such an array, whose count differs from the number of assertions, or in which a verdict disagrees
with what its own evidence concludes (measure.conclusion), is refused and the grading is made again, up to GRADING_RETRIES times (the refused attempts stay
in <run folder>/grading-refused-<k>/); after that the run has no score and the iteration is incomplete.
benchmark.json carries "grading": {"template_sha256", "refused"}.
--regrade <run folder> grades stored replies again: for every graded run under the folder (an iteration, a
case or one run) it sends the stored grading prompt to the grader once more, the configured one or the one
named with --grader, and compares the verdicts by position with the stored ones. It prints {"gradings",
"failed", "verdicts", "differ", "share", "failed_verdicts", "failed_differ", "runs"}, keeps each new result in
<run folder>/regrade-<k>/, changes no score and writes no evidence. It measures how much two gradings of the
same material disagree, and compares a new grader with the old one on a sample.
The folder given to --resume, --close and --regrade, when relative, is read against the current folder and no
other base; it must be inside this checkout's evals-workspace/, and a folder of another checkout is refused.
Each command prints the absolute folder it acts on.

Preflight. Before any model call, and in --dry-run and --check-cases (which runs only this check; --harness
and --model are then optional), every case is checked: (a) each "files" entry exists in the skill folder;
(b) the case folder is built as a run builds it (the files, then the "setup" commands; --dry-run runs nothing,
so it leaves the cases that have a setup unchecked and says so) and every path the prompt cites exists in it,
unless the path also appears in "expected_output" or an assertion, or in the skill's metadata.outputs (the run
creates it), is one of the skill's own files outside evals/ or a workbench file under contracts/, shared/,
templates/, providers/, adapters/ or skills/, or the case lists it in "absent_on_purpose": ["path", ...] (a case that tests a missing input);
(c) each "grader_files" entry exists in that folder; (d) each "skills" dependency exists; (e) each "platforms"
entry has its reference, shared/references/platforms/<name>.md; (f) the folder holds no harness settings
(above); (g) each assertion is a text, or an object with a text; (h) a folder the prompt names, a token that
ends in "/", is a folder of the case (a folder in "files" is copied by content, so its own name is not in the
case), unless it is produced, absent on purpose or a workbench folder; (i) "skills" is one of its three allowed
uses: a flow's case lists the flow's phases and never the router, a case of the router lists the one leaf
skill a route needs, a case of a skill whose own text calls another skill's script (<other>/scripts/) lists
that skill; (j) a case that sets "allow_web" is one of the gate file's "web_cases". A cited path is a
token with a "/" and a file extension, or one ending in .md .json .yml .yaml .toml .css .js .ts .py .html;
URLs, absolute paths, globs and placeholders are ignored, and a path matches a fixture when it is that
fixture's path or the end of it. Errors are printed one per line and stop the run before it spends anything.
Rules (h) and (i) were TRANSITIONAL while the rows of phase C fixed the cases written before them, and
--check-cases listed their findings as "warnings"; since the close of phase C (C0.10) TRANSITIONAL is empty and
they are errors like the others, for --check-cases and a real run alike. --check-cases --with-setup also runs the cases' setup commands, in the
eval container (the container job of CI runs it for every skill that has one).

Infrastructure failures are not scores. A run whose adapter exits non-zero (a missing runner, a provider
that is down), that passes its timeout, that the provider refuses, or that ends its turn early (below), on
every attempt, or whose grading is refused on every attempt, is listed in benchmark.json "infra_failures"
({"case", "variant", "slot", "run", "reason", "kind"}) and never enters a mean. benchmark.json also carries
"expected_runs", "completed_runs" and "complete" (true only when every expected run completed and was
graded), "date", "iteration", "cases", "passes" (1, plus one per resumption) and "content_sha256", the skill
folder's hash when the event started. Resume an incomplete event (--resume); never change the skill for it. A
timeout that repeats on the same case is a reason to look at the case. The event's folder also holds
event.json (its options, its state: open or complete) and ledger.jsonl (one line per run of each pass, written
when the run ends, so a stopped event loses nothing it finished).
The gate's comparison is made on unrounded means; a mean is rounded only where it is shown. "stddev" is the
sample standard deviation.

Early ends. Some models end their turn before doing the work, with exit 0 and no error: they print a tool
call as text, loop on their own reminder blocks, or stop after "Let me read the template first". A run is an
early end only when the adapter exited 0 AND it created, changed or deleted no file in the case folder (the
staged skills and shared references do not count) AND its response is not a reply to the user: (a) it is
empty; or (b) a line starts with tool-call or control markup printed as text (EARLY_END_MARKUP); or (c) it is
a short reply whose final sentence announces a next action: the response has no question mark, the final
sentence of its last line starts with one of EARLY_END_ANNOUNCE, and the response is at most
EARLY_END_SHORT characters or its last line ends with a colon or an ellipsis. A reply that states a blocker
is never one: a response of more than EARLY_END_BLOCKER_MIN characters that holds one of EARLY_END_BLOCKER
("can't", "need", "paste", "tell me", ...), or a last line that waits for the user (EARLY_END_NOT: "let me
know", "once you", ...). In the first round the earlier rule, any sentence of the last line starting with
"I'll", threw away seven legitimate replies of a model, each a stop that named what it lacked and
asked for it in the imperative. A reply that asks the user a question and
writes nothing is a stop-and-ask, never an early end; neither is a run that wrote a file and then stopped
before finishing: that one is graded as it is. One exception, which a written file does not excuse: (d) a loop
of raw tool-call syntax printed as text: at least "min_lines" (20) markup lines, and at least "share" (0.5) of the
counted lines or of their characters (a line is markup when it holds a tag of EARLY_END_MARKUP, which has the call
markup of DeepSeek's models too, or "<parameter", anywhere in it, or lies inside a call block; fenced and indented
code and inline code spans are left out): a model whose tool calls turned into such a loop wrote a file first and
was graded once (T27). The runtime's runs go through the same rule. An early-ended run is rerun in a fresh folder up to
--retries <n> times (default 2, 0 disables; each early attempt is kept in <run folder>/early-end-<j>/, the
last attempt stays in the run folder). One that early-ends on every attempt is an infrastructure failure
with reason "early_end". benchmark.json "early_ends" counts, per model, {"attempts", "early_ends",
"rate", "by_case", "by_variant"} (an early end thrown away and drawn again conditions a variant's score on
phrasing, so the count is kept per variant too); each run's timing.json keeps the stop reason and the number
of turns the adapter's raw output names ("stop_reason", "num_turns", "terminal_reason"), beside the reply; "early_end_warning" is a sentence, printed at the end, when a model has at least 3 early
ends and either a rate above --early-end-rate (default 0.15) or all of them on one case: retries hid them
from the scores, so read the transcripts and decide between the skill, the case and the provider. The
warning never changes the exit code.

Evidence. The result of an event is its evidence file: one first line that describes the event and one line
per scored run, with the closed keys of the reliability model (docs/architecture/reliability-model-2026-10-02.md,
section 1; evals/eval_status.py validates them). The event gets its id when it starts, the UTC time and eight
random hexadecimal characters, and the file is lab-<test id>.jsonl. While the event runs, and for every event
that is a trial, the file lives in the run folder: <event folder>/scratch/skills/<name>/evals/evidence/. When
the event ends complete, and nothing of "Control of a test event" makes it a trial, the file is copied to
skills/<name>/evals/evidence/, where it is committed and never edited. Nothing else is written into a skill's
folder: the old records, result.json, were removed on 2026-10-15 (`git show bc830832:skills/<name>/evals/result.json`), and no line is
converted from them.
A run line carries the skill's version (metadata.version as X.Y.Z; a two-part version is read as X.Y.0) and
its content hash when the event started (the hash leaves out all of evals/, scripts/tests/, caches and an
installer's marker file), the case and its hash (over the whole case object and the bytes of its fixture
files), "context_sha256" when the run was given dependency skills or shared references (one hash over them),
the model as the gate file lists it ("models": an alias is written as its id; a model the file does not list, which
only a local test runs, under its own well-formed id),
the adapter, the variant ("with" or "without"), the outcome ("graded", or "timeout" after the cap of
resumptions), the score, one 0 or 1 per assertion ("results"), "guard_failed" when the second grading of a
with-skill run confirmed a failed guard (above, "Grading"), the measurement version and the measurement
fingerprint computed when the event started. A run that failed on infrastructure, was paused on the account
limit or ended early writes no line. The event line carries what describes the event as a whole: its kind
("full": every case with the skill on the lead model; "partial": chosen cases; "quick": every case once with the skill), the models (a list of
ids) with their adapters ({model id: adapter}) and the hash of each adapter's run-prompt.sh, the grader, the configured runs, timeout and retries,
the image's digest and CPU platform, the versions of the tools in the image, the grading template's hash, the
hash of every case, whether the baseline of each case was run, the web cases, per model and variant the
counts of retries, refusals, timeouts, pauses, early ends and resumptions, the names of extra variables,
whether the event is complete and, for a complete full test, the gate's result for each model whose runs in
the event were all graded and whose baseline ran or is in force ("gate": {model id: result}), with the two means
it was computed from (the mean with the skill on that model is at the threshold or above and is not below the
baseline's mean by more than the tolerance, both unrounded). A run line also carries "usage" when the run's
tokens could be read whole (run_usage): the key proxy's count, else the model usage of the raw output.
Where the evidence goes (evidence_home): into the skill's folder when every model of the event is one of the gate
file's "lab_models" and runs through the adapter its entry names; otherwise into the person's local evidence folder,
<XDG data home>/openhora/evidence/<skill>/ (WB_LOCAL_EVIDENCE_DIR names another base; one inside the checkout is
refused), which nothing in the checkout sees. The local file is read by its own event line, not the gate file's list.
What makes an event a trial, besides "Control of a test event": a grader that is not the configured one; a
measurement fingerprint that differs from the committed one (a file that decides what
a run measures changed in this checkout); chosen variants (--only, --ablate, --no-grade); a skill
with no version; a skill folder that changed during the event. An incomplete event writes nothing into the
skill either: resume it. The reason is printed, and stored in benchmark.json "scratch".
Extra variables. A variable named with --pass-env changes what a run is (an adapter reads several, and one replaces the runner by a command). The event
line names them in "extra_pass_env", and such an event is a trial. The runner refuses the variables that would sign a host
or the password manager back in: the git-host and npm tokens, and the whole OP_ family (OP_SERVICE_ACCOUNT_TOKEN, OP_SESSION_*,
OP_CONNECT_TOKEN, OP_CONNECT_HOST); a run's environment never holds one either.

Outside the repository. A model that runs inside the workbench finds it: it walks up from the case folder,
reads the instruction file and the skills, and a without-skill run then scores with the skill's help. So every
model run and every grading happens in a fresh folder under the system's temporary folder, <temp>/eval-<random>/
(case/ is the case folder, with the prompt file and the adapter's output beside it): no parent of it holds a
repository, an instruction file or a skills folder, and its path names neither the workbench nor the skill
(a temporary folder that would is replaced by /tmp or /var/tmp). Setup commands run there too. When the run
ends (also on a timeout, a failure or a stop) the folders are moved to where they have always been read,
<run folder>/cwd and <run folder>/outputs (grading/cwd and grading/out for a grading), and the temporary
folder is removed. The run's environment carries no path into the repository: PATH entries inside it and
allowlisted variables that point into it are dropped, TMPDIR is the temporary base, the git, gh and npm
configuration files sit in the temporary folder, and the adapter is started from there (a shell exports the
folder it came from as OLDPWD). Only a variable named with --pass-env is passed as it is.
Repository files. A case may list "workbench_files": files and folders of this repository copied into the
case folder at the same relative path (a skill's evals/ and scripts/tests/ folders are left out, as in a
staged copy; version control, eval workspaces and eval cases are refused). Fixture and repository files are
copied without bytecode and system files (__pycache__, *.pyc, .pytest_cache, .DS_Store). It is for a skill whose job is the workbench itself, which needs the real
tooling to act on; such a case deliberately shows the model part of the repository.

Refusals. When the provider declines a run on policy grounds, the run is made again like a timeout, with the
skill and without it alike, and listed in benchmark.json "refusals". One refused on every attempt is an
infrastructure failure; after the cap of resumptions it is a result with score 0, like every run that did not
complete (the earlier rule scored a refused baseline 0 at once and never scored a refused with-skill run,
which treated the two variants differently).

Contamination. A baseline is the model without the skill, so a without-skill run must not have reached it.
Three checks, all deterministic:
(1) By construction, and asserted in the docker tests: the container of a without-skill run holds no path
with the skill under test or with shared/references/. The runner stages neither into its case folder, and a
container mounts nothing else of the workbench but one adapter script.
(2) A without-skill run whose reply, transcript (the adapter's stderr and raw output) or produced files name
a mount path of the workbench (the folder the adapter script is mounted in, evals/executor.py) or the
repository's path on the host looked at the harness or reached the workbench. It is not scored: it is an
infrastructure failure with reason "contaminated", listed in benchmark.json "contaminated" ({"case",
"variant", "slot", "model", "run", "evidence"}), so the iteration is incomplete and no gate is evaluated on it. No
option records it anyway.
(3) A without-skill run whose reply or produced files share a passage of at least PASSAGE_WORDS words with
the skill's own text (SKILL.md, references/, assets/) that is in neither the prompt nor the case folder as
the run found it (its files, what its setup made, the dependency skills) is listed in benchmark.json
"shared_passages", with the passage quoted, and printed as a warning. It blocks nothing: in the first round
this found 3 runs in 846, each a stock phrase, so every hit can be read by a person.

Stopping. Every adapter call (a model run, a grading) and every setup command runs in its own session, one
process group per call. The group is ended (TERM, then KILL after a short wait) when the call passes its
timeout, when the call returns (so a browser or a server a run left behind stops with it), when this script
gets TERM, INT or HUP (it then exits with 128 plus the signal number, without writing benchmark.json), and on
every other way out. The adapters do the same for the runner they start, which they put in a session of its
own. A process that moves itself to yet another session escapes this.

Exit codes: 0 ok; 1 the iteration is incomplete (a run or a grading failed on infrastructure: rerun);
2 usage error or a preflight error in the cases; 3 the iteration is complete and the conditions are not met
(reported, not an error of the tool).
"""
import concurrent.futures
import contextlib
import datetime
import glob
import hashlib
import importlib.util
import json
import os
import re
import secrets
import shutil
import signal
import stat
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import types
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))

# The execution kit (evals/execution.py): the container run of one attempt, shared with the runtime's lab facade.
# Loaded by path, once, and every name it defines is bound here, so that the code below and the tests read them as
# they always did. A name the kit reads for itself (EXECUTOR, LOCK_DIR, PAUSE_CLOCK, ...) is replaced on the kit
# module (sys.modules["workbench_eval_execution"]); the copy here is what this module's own code reads.
KIT_SCRIPT = os.path.join(HERE, "execution.py")
KIT_NAME = "workbench_eval_execution"
KIT_BOUND = (
    "ROOT", "STATUS_SCRIPT", "EXECUTOR_SCRIPT", "STAGE_SCRIPT", "EXECUTOR", "SETUP_TIMEOUT", "die",
    "load_executor", "STAGE_LOCK", "load_stage", "adapter_eval", "harness_settings", "settings_in",
    "case_platforms", "stage_run", "exclude_from_git", "MEASURE_SCRIPT", "MEASURE_LOCK", "load_measure",
    "ATTEMPTS_SCRIPT", "ATTEMPTS_LOCK", "load_attempts", "load_status", "resolve_pass_env", "TOKEN_VARS", "TOKEN_PREFIXES", "token_var",
    "ENV_ALLOW", "repo_paths", "temp_base", "RUN_ROOTS", "RUN_ROOTS_LOCK", "new_run_root", "return_run",
    "return_all_runs", "provider_refusal", "AUTH_STATUS", "AUTH_KEY_WORDS", "AUTH_WINDOW", "auth_refusal",
    "credential_label", "contained_env", "GROUPS", "GROUPS_LOCK", "STOPPING", "STOP_GRACE", "group_alive",
    "stop_group", "stop_all_groups", "CONTAINERS", "run_group", "_run_group", "run_failure", "run_prompt",
    "KEPT_PREFIXES", "staged_file", "run_ending", "SKIP_DIRS", "host_may_touch", "run_files", "readable",
    "redact_folder", "changes", "isolate_git", "file_index", "REDACT_LIMIT", "read_text", "LOCK_DIR",
    "SLOT_POLL", "RETRY_PAUSE", "PAUSE_POLL", "PROBE_SECONDS", "PROBE_TIMEOUT", "PROBE_PROMPT", "lock_dir",
    "Slot", "Slots", "account_limit", "pause_path", "PAUSE_CLOCK", "PAUSE_SLEEP", "read_pause", "last_probe",
    "clock", "start_pause", "wait_while_paused", "probe_call", "RETRY_KINDS"
)


def _load_kit():
    if KIT_NAME not in sys.modules:
        if not os.path.isfile(KIT_SCRIPT):
            print("Error: evals/execution.py is missing: run this script from a checkout of the workbench.", file=sys.stderr)
            sys.exit(2)
        spec = importlib.util.spec_from_file_location(KIT_NAME, KIT_SCRIPT)
        module = importlib.util.module_from_spec(spec)
        sys.modules[KIT_NAME] = module
        spec.loader.exec_module(module)
    return sys.modules[KIT_NAME]


KIT = _load_kit()
globals().update({_name: getattr(KIT, _name) for _name in KIT_BOUND})

GRADING_TEMPLATE = os.path.join(HERE, "grading-prompt.md")


# The names this module reads from evals/measure.py, the one module that decides what a run measures (item
# B10): the facts block, what the grader is shown of a file, the grading prompt and the reading of its answer,
# the early-end rule, the replacement of passed values, the score and the gate's comparisons. They are not
# copied here; `eval_run.<name>` still reads them, through the module's __getattr__ below.
MEASURE_NAMES = ("FILE_LIMIT", "VCS_LIMIT", "VCS_SCRIPT", "GRADING_RETRIES", "REDACT_MIN", "NOT_SHOWN",
                 "EARLY_END_MARKUP", "EARLY_END_ANNOUNCE", "EARLY_END_NOT", "EARLY_END_BLOCKER", "EARLY_END_BLOCKER_MIN",
                 "EARLY_END_SHORT", "PSEUDO_TAG_LINE_RE", "TAG_ONLY_LINE_RE", "early_end", "redaction_values",
                 "replace_values", "facts_block", "binary_stub", "shown", "assertion_text", "grading_prompt",
                 "read_grading", "grading_summary", "score", "at_threshold", "within_tolerance", "gate_passes", "cut_vcs",
                 "assertion_tags", "guard_positions", "failed_guards", "confirmed_guards")


def __getattr__(name):
    if name in MEASURE_NAMES:
        return getattr(load_measure(), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


class _Runner:
    """This module as run_attempts reads it: each name is looked up at the moment it is read, so a name a test
    replaces on the module is the one the loop uses; the names of evals/measure.py come through the module's
    own __getattr__."""

    def __getattr__(self, name):
        found = globals()
        if name in found:
            return found[name]
        return __getattr__(name)


_RUNNER = _Runner()


LOCAL_PREFIX = "local/"  # a model on the person's own machine (evals/local_models.py)


def local_models():
    """evals/local_models.py as a module: a model on the person's machine, its configuration, weights and identity."""
    return KIT.load_local_models()


def local_models_option(opts, models, standalone_run, timeout_given, control):
    """The --model options of an event that names a local model (local/<name>): the refusals, and the model's id once the
    weights are hashed (local/<name>@<12 hex>). Fills opts["local"], the model's description (local_models.resolve() and
    the configuration's values), and opts["harness"] (agents-dir: the only adapter that serves one). Returns the event's
    list of models. A local model is tested alone, through agents-dir, with no web case, and with the configured timeout:
    --dry-run and the modes that run nothing do not hash the file."""
    lm = local_models()
    if len(models) != 1:
        die("a local model is tested alone: an event that mixes it with another model is refused (one machine's CPU, memory "
            "and GPU are shared by every run of the event, and a hosted model's runs would be timed against them). Give --model "
            "once.", 2)
    if opts["harness"] not in (None, "agents-dir"):
        die("a local model runs through the agents-dir adapter only (its runner writes the local provider); drop --harness.", 2)
    if opts["routing"] or opts["regrade"] is not None:
        die("--routing and --regrade take a hosted model: a local model is tested with --skill.", 2)
    try:
        name, typed = lm.parse_id(models[0])
        config = lm.load_config()
        if name not in config:
            raise lm.LocalModelError(f"{name!r} is not in the local models file {lm.config_path()}: it lists "
                                     f"{', '.join(sorted(config)) or 'none'}")
        spec = {**config[name], "name": name, "typed_hex": typed}
        if opts["dry"] or standalone_run:  # nothing runs: the file is not hashed
            opts["local"] = {**spec, "id": models[0]}
        else:
            print(f"hashing the weights of {name} ({os.path.getsize(spec['weights'])} bytes) once for this event...", file=sys.stderr)
            opts["local"] = resolve_local(name, typed, config)
    except lm.LocalModelError as e:
        die(str(e), 2)
    opts["harness"] = "agents-dir"
    if not timeout_given:  # the declared limit is the configured one for this event (scratch_reason reads it)
        opts["timeout"] = opts["local"]["timeout_seconds"] or control["timeout_seconds"]
    return [opts["local"]["id"]]


def resolve_local(name, typed_hex, config):
    """local_models.resolve() for the event, with the docker host's CPU count left to the event's start when the
    configuration gives none, and the description made plain (JSON) so that it can be kept in the event's options."""
    spec = local_models().resolve(name, typed_hex, config)
    return {**spec, "stat": list(spec["stat"])}


def local_server_spec(local, cpus=None):
    """What the model server of a local model is started with (executor.local_server_argv)."""
    return {"alias": local["alias"], "context": local["context"], "memory_gb": local["memory_gb"],
            "accelerator": local["accelerator"], "cpus": cpus or local["cpus"],
            "load_timeout_seconds": local.get("load_timeout_seconds")}


def describe_local(local):
    """The event line's "local_model" for a local model: {model id: {"weights_sha256", "file_type", "context",
    "accelerator", "server_image", "server_version", "server_args_sha256"}}. The model server image is checked present (and
    never pulled), its version is read once in a container with no network, and the hash is of the server's arguments with the
    run id, the weights path and the user replaced by constants: a property of the configuration, not of this machine's paths."""
    ex = load_executor()
    ex.verify_local_server(local["accelerator"])
    server = ex.local_server(local["accelerator"])
    argv = ex.local_server_argv("0" * 16, local_server_spec(local), server["image"], server["platform"], "/weights/model.gguf",
                                ["--user", "0:0"])
    return {local["id"]: {"weights_sha256": local["weights_sha256"], "file_type": local["file_type"], "context": local["context"],
                          "accelerator": local["accelerator"], "server_image": server["manifest_digest"],
                          "server_version": ex.local_server_version(local["accelerator"]),
                          "server_args_sha256": hashlib.sha256(json.dumps(argv).encode("utf-8")).hexdigest()}}


def cap_local_jobs(opts):
    """--jobs of a local model's event is at most the model's "parallel": the machine's CPU, GPU and memory are the shared
    resource (principle 7 of AGENTS.md says when work is run one after another), and a second server at once doubles the
    cache memory and slows both."""
    local = opts.get("local")
    if local and opts["jobs"] > local["parallel"]:
        print(f"NOTE --jobs {opts['jobs']} lowered to {local['parallel']}: \"parallel\" of {local['name']} in the local models file "
              "is how many runs this machine serves at once.", file=sys.stderr)
        opts["jobs"] = local["parallel"]


IMPORTED_NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def skill_folder(o):
    """The folder of the skill under test: the --skill-dir folder of a skill from outside, else skills/<name>."""
    return o["skill_dir"] if o.get("skill_dir") else os.path.join(ROOT, "skills", o["skill"])


def imported_options(opts):
    """--skill-dir: the skill under test is a folder outside skills/ (a skill from outside, scripts/skill_import.py). Sets
    opts["skill"] to the folder's name and opts["skill_dir"] to its absolute path, and refuses what such a test never takes:
    --skill, a name that is a skill of the repository, a folder inside the checkout, --pass-env, --harness, --platform and
    the modes that are not a test (--routing, --regrade, --resume, --close, --unpause)."""
    folder = os.path.abspath(os.path.expanduser(opts["skill_dir"]))
    name = os.path.basename(folder)
    if opts["skill"]:
        die("--skill-dir and --skill are exclusive: --skill names a skill of skills/, --skill-dir the folder of a skill from outside.", 2)
    if not os.path.isfile(os.path.join(folder, "SKILL.md")):
        die(f"--skill-dir {folder} is not a skill folder: it has no SKILL.md.", 2)
    if not IMPORTED_NAME_RE.match(name) or len(name) > 64:
        die(f"--skill-dir {folder}: the folder's name is the skill's, lowercase letters, digits and single hyphens ({name!r} is not).", 2)
    if os.path.isdir(os.path.join(ROOT, "skills", name)):
        die(f"--skill-dir {folder}: {name} is the name of a skill of the repository (skills/{name}); a skill from outside has a "
            "name of its own, and its evidence would otherwise be mistaken for that skill's.", 2)
    if load_status().inside_checkout(folder, ROOT):
        die(f"--skill-dir {folder} is inside the workbench checkout: a skill from outside lives outside it "
            "(scripts/skill_import.py puts it in its home folder).", 2)
    clash = [flag for flag, on in (("--pass-env", opts["pass_env"]), ("--harness", opts["harness"]), ("--platform", opts["platform"]),
                                   ("--routing", opts["routing"]), ("--regrade", opts["regrade"] is not None),
                                   ("--resume", opts["resume"] is not None), ("--close", opts["close"] is not None),
                                   ("--unpause", opts["unpause"])) if on]
    if clash:
        die(f"--skill-dir does not go with {', '.join(clash)}: a skill from outside is tested on the models of the gate file, "
            "through their adapters and key proxies, with no variable of yours in the run.", 2)
    opts["skill"], opts["skill_dir"] = name, folder


AUDIT_REL = os.path.join("evals", "import", "audit.json")
AUDIT_VERDICTS = ("do not install", "install after changes", "install")  # the verdicts of skills/core-security-audit's vetting


def folder_links(folder):
    """The paths (relative, "/" separators) of every symbolic link and every special file (device, pipe, socket) under `folder`,
    all of evals/ included. Staging copies what a link points at, so a link to a private file would reach a run."""
    found = []
    for dp, dns, fns in os.walk(folder, followlinks=False):
        for n in dns + fns:
            path = os.path.join(dp, n)
            mode = os.lstat(path).st_mode  # the entry itself, never what a link points at
            if not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
                found.append(os.path.relpath(path, folder).replace(os.sep, "/"))
    return sorted(found)


def read_audit(folder):
    """The audit record of a skill from outside (scripts/skill_import.py audit writes <folder>/evals/import/audit.json:
    {"verdict", "record", "record_sha256", "content_sha256", "date"}), or None when there is none or it is unreadable."""
    try:
        with open(os.path.join(folder, AUDIT_REL), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def imported_case_problems(cases):
    """Why a case of a skill from outside is refused whatever the audit: "workbench_files" copies files of this repository
    into the case, which a skill from outside has no use for and no right to."""
    return [f"case {c.get('id')}: workbench_files is not allowed in the cases of a skill from outside (it copies files of "
            "this repository into the case folder)" for c in cases if "workbench_files" in c]


def imported_event_problems(o, web_cases):
    """Why a real event of a skill from outside must not start, as a list of sentences ([] when it may). The checks are code,
    not a prompt: a link anywhere in the folder; no audit record; a verdict of "do not install"; a folder whose content
    changed since the audit (its hash is no longer the one the record names); and, for a case with "allow_web", the flag
    --allow-web-cases together with the verdict "install" (the open network could hand the person's fixtures to any host)."""
    folder, problems = o["skill_dir"], []
    links = folder_links(folder)
    if links:
        problems.append(f"the folder holds {len(links)} symbolic link(s) or special file(s) ({', '.join(links[:5])}"
                        f"{', ...' if len(links) > 5 else ''}): staging copies what a link points at into a run, so none is allowed")
    audit = read_audit(folder)
    verdict = audit.get("verdict") if audit else None
    if audit is None:
        problems.append(f"there is no audit record ({AUDIT_REL.replace(os.sep, '/')}): vet the skill first, then "
                        "python3 scripts/skill_import.py audit --name <name> --record <file>")
    elif verdict not in AUDIT_VERDICTS:
        problems.append(f"the audit record names no verdict of {', '.join(AUDIT_VERDICTS)}")
    elif verdict == "do not install":
        problems.append("the audit verdict is \"do not install\": a skill that failed its vetting is not run, not even in the container")
    elif audit.get("content_sha256") != load_status().content_hash(folder):
        problems.append("the folder changed since it was audited (the audit names another content hash): the audit is void; "
                        "vet it again and record the new verdict")
    if web_cases:
        if not o.get("allow_web_cases"):
            problems.append(f"case(s) {', '.join(web_cases)} set \"allow_web\": a skill from outside runs on the open network only "
                            "with --allow-web-cases")
        elif verdict != "install":
            problems.append(f"case(s) {', '.join(web_cases)} set \"allow_web\" and the audit verdict is {verdict!r}: the open "
                            "network needs the verdict \"install\"")
    return problems


def parse(argv):
    opts = {"skill": None, "harness": None, "models": [], "grader": None, "cases": [],
            "threshold": None, "only": None, "grade": True, "dry": False, "pass_env": [], "ablate": None,
            "runs": None, "jobs": 4, "timeout": None, "max_cost": None, "check_cases": False, "retries": None,
            "early_rate": 0.15, "regrade": None, "scratch": False, "resume": None, "unpause": False, "at": None,
            "baseline": False, "baseline_on": [], "close": None, "with_setup": False,
            "routing": False, "pack": None, "prompts": None, "platform": None, "quick": False,
            "skill_dir": None, "allow_web_cases": False}
    i = 0
    while i < len(argv):
        a = argv[i]
        def val():
            if i + 1 >= len(argv):
                die(f"{a} needs a value.")
            return argv[i + 1]
        if a == "--skill": opts["skill"] = val(); i += 2
        elif a == "--harness": opts["harness"] = val(); i += 2
        elif a == "--model": opts["models"].append(val()); i += 2
        elif a == "--grader": opts["grader"] = val(); i += 2
        elif a == "--case": opts["cases"].append(val()); i += 2
        elif a == "--cases": opts["cases"] += [c.strip() for c in val().split(",") if c.strip()]; i += 2
        elif a == "--baseline": opts["baseline"] = True; i += 1
        elif a == "--baseline-on": opts["baseline_on"].append(val()); i += 2
        elif a == "--platform": opts["platform"] = val(); i += 2
        elif a == "--quick": opts["quick"] = True; i += 1
        elif a == "--skill-dir": opts["skill_dir"] = val(); i += 2
        elif a == "--allow-web-cases": opts["allow_web_cases"] = True; i += 1
        elif a == "--close": opts["close"] = val(); i += 2
        elif a == "--threshold": opts["threshold"] = float(val()); i += 2
        elif a == "--only": opts["only"] = val(); i += 2
        elif a == "--pass-env": opts["pass_env"].append(val()); i += 2
        elif a == "--ablate": opts["ablate"] = val(); i += 2
        elif a == "--runs": opts["runs"] = val(); i += 2
        elif a == "--jobs": opts["jobs"] = val(); i += 2
        elif a == "--timeout": opts["timeout"] = val(); i += 2
        elif a == "--max-cost-usd": opts["max_cost"] = val(); i += 2
        elif a == "--no-grade": opts["grade"] = False; i += 1
        elif a == "--retries": opts["retries"] = val(); i += 2
        elif a == "--early-end-rate": opts["early_rate"] = val(); i += 2
        elif a == "--dry-run": opts["dry"] = True; i += 1
        elif a == "--check-cases": opts["check_cases"] = True; i += 1
        elif a == "--with-setup": opts["with_setup"] = True; i += 1
        elif a == "--routing": opts["routing"] = True; i += 1
        elif a == "--pack": opts["pack"] = val(); i += 2
        elif a == "--prompts": opts["prompts"] = val(); i += 2
        elif a == "--regrade": opts["regrade"] = val(); i += 2
        elif a == "--scratch": opts["scratch"] = True; i += 1
        elif a == "--resume": opts["resume"] = val(); i += 2
        elif a == "--unpause": opts["unpause"] = True; i += 1
        elif a == "--at": opts["at"] = val(); i += 2
        elif a in ("--help", "-h"): print(__doc__); sys.exit(0)
        else: die(f"unknown option {a!r}. See --help.")
    if opts["skill_dir"] is not None:
        imported_options(opts)
    elif opts["allow_web_cases"]:
        die("--allow-web-cases goes with --skill-dir: the cases of a skill of skills/ run on the network the gate file's "
            "web_cases lists.", 2)
    # What the command line leaves out comes from the eval gate configuration (evals/eval-gate.json).
    gate = {} if opts["check_cases"] else load_status().load_gate(ROOT)
    # The runs of a case, the limit of a run and the retries have one home, the gate file; a flag is for a
    # trial, and an event made with another value than the configured one writes no evidence.
    control = load_status().event_config(gate)
    timeout_given = opts["timeout"] is not None  # a local model's configured limit replaces the gate file's, unless --timeout is given
    runs_given = opts["runs"] is not None
    for key, name in (("runs", "runs"), ("timeout", "timeout_seconds"), ("retries", "retries")):
        if opts[key] is None:
            opts[key] = control[name]
    # --model (repeated) names the models of the event, in order; the first is the lead model (the event is full by
    # it and its baseline runs by default); without any, the gate file's "lab_models". A model the gate file lists
    # takes its entry's adapter and key variables; one it does not list (a person's own test) takes --harness, which
    # is the adapter of every unlisted model of the event, and its key only from --pass-env. With every model listed,
    # --harness is accepted only for an event of one model, and replaces that model's adapter.
    status = load_status()
    standalone_run = (opts["resume"] is not None or opts["close"] is not None or opts["regrade"] is not None
                      or opts["unpause"] or opts["check_cases"])
    models = [m for m in opts["models"]]
    if not models and not standalone_run:
        models = list(gate.get("lab_models") or [])
    if opts["routing"]:
        if len(opts["models"]) > 1:
            die("--routing runs one model: give --model once (without it, the first of lab_models runs).")
        models = models[:1]
    for name in models:
        if not status.MODEL_RE.fullmatch(name):
            die(f"--model {name!r} is not a model id (letters, digits and . _ : / @ -).")
    opts["local"] = None
    if any(m.startswith(LOCAL_PREFIX) for m in models):
        models = local_models_option(opts, models, standalone_run, timeout_given, control)
    resolved, entries = [], {}
    for name in models:  # a listed model runs under its listed id, whichever alias named it
        entry = status.model_entry(gate, name) if gate else None
        resolved.append(entry["id"] if entry else name)
        entries[resolved[-1]] = entry
    models = resolved
    if len(set(models)) != len(models):
        die("--model names the same model twice.")
    opts["models"] = models
    opts["model"] = models[0] if models else None  # the lead model
    adapters = {m: (entries[m] or {}).get("adapter") for m in models}
    unlisted = [m for m in models if not adapters[m]]
    if opts["harness"]:
        if unlisted:
            adapters.update({m: opts["harness"] for m in unlisted})
        elif len(models) == 1:
            adapters[models[0]] = opts["harness"]
        elif models and any(adapters[m] != opts["harness"] for m in models):
            die("--harness is the adapter of a model the gate file does not list; every model of this event is listed, and "
                "its entry names its adapter.")
    elif unlisted and not standalone_run and not opts["routing"]:
        die(f"--model {unlisted[0]}: the gate file lists no adapter for it, so --harness <adapter> is required."
            if gate else "--harness is required (evals/eval-gate.json sets no default).")
    opts["adapters"] = adapters
    opts["harness"] = adapters.get(opts["model"]) or opts["harness"]  # the lead's adapter (--routing, --regrade, a grader)
    if opts["threshold"] is None:
        opts["threshold"] = gate.get("threshold")
    if opts["threshold"] is None:
        opts["threshold"] = 0.8
    opts["grader"] = opts["grader"] or gate.get("grader")
    opts["tolerance"], opts["measurement_version"] = gate.get("tolerance") or 0, gate.get("measurement_version")
    # The variables of a model's key are the model's own, whichever place it takes in the event: its entry's
    # "pass_env", and its "web_pass_env" on a run on the open network, when it has one. A model the file does not
    # list passes none of its own.
    opts["pass_envs"] = {m: list((entries[m] or {}).get("pass_env") or []) for m in models}
    opts["web_pass_envs"] = {m: list(entries[m]["web_pass_env"]) for m in models if entries[m] and entries[m].get("web_pass_env")}
    # The grader is a model of its own: it grades through its own entry's adapter and key, whatever the event runs.
    # A grader the file does not list (or a tree with no gate file) grades through the adapter of the event model of
    # that name, else the lead model's.
    opts["grader"] = opts["grader"] or opts["model"]
    grader_name = opts["grader"]
    grader_entry = status.model_entry(gate, grader_name) if gate and grader_name else None
    if grader_entry:
        opts["grader"] = grader_entry["id"]
    elif grader_name in models:
        grader_entry = entries[grader_name]
    opts["grader_harness"] = (opts["harness"] if opts["regrade"] is not None and opts["harness"]
                              else (grader_entry or {}).get("adapter") or adapters.get(grader_name) or opts["harness"])
    opts["grader_pass_env"] = list((grader_entry or {}).get("pass_env") or opts["pass_envs"].get(grader_name) or [])
    # What the command line passes beyond the gate file's own variables: a run with one is another measurement.
    opts["extra_pass_env"] = sorted(set(opts["pass_env"]))
    if opts["regrade"] is not None:
        if opts["skill"] or opts["cases"] or opts["only"] or opts["check_cases"] or opts["dry"]:
            die("--regrade takes a run folder and goes with --grader, --harness, --jobs and --timeout only.")
        if not os.path.isdir(opts["regrade"]):
            die(f"--regrade {opts['regrade']!r} is not a folder (a relative path is read against the current folder, "
                f"{os.getcwd()}).")
        opts["regrade"] = operator_folder(opts["regrade"], "--regrade")
    alone = [a for a in argv if a.startswith("--") and a not in ("--resume", "--jobs", "--unpause", "--at", "--close")]
    if opts["resume"] is not None and (alone or opts["unpause"] or opts["close"] is not None):
        die("--resume takes an event's folder and goes with --jobs only: the event keeps the options it started with.")
    if opts["close"] is not None and (alone or opts["unpause"]):
        die("--close takes an event's folder and no other option.")
    if opts["unpause"] and alone:
        die("--unpause goes with --at <time> only.")
    if opts["routing"]:
        others = [a for a in argv if a.startswith("--") and a not in ("--routing", "--pack", "--skill", "--prompts",
                                                                          "--jobs", "--harness", "--model", "--timeout",
                                                                          "--pass-env")]
        if others:
            die(f"--routing goes with --pack, --skill or --prompts, --jobs and the model options, not {others[0]}.")
        if not opts["pack"] or not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", opts["pack"]):
            die("--routing needs --pack <name>: the skills installed beside one another.")
        if bool(opts["skill"]) == bool(opts["prompts"]):
            die("--routing runs --skill <name> (its case prompts) or --prompts <file> (a JSON list of texts), one of them.")
    elif opts["pack"] or opts["prompts"]:
        die("--pack and --prompts go with --routing.")
    if opts["platform"] is not None:
        if not PLATFORM_NAME_RE.match(opts["platform"]):
            die(f"--platform {opts['platform']!r} is not a platform name (lowercase, hyphens).")
        if opts["routing"] or opts["regrade"] is not None:
            die("--platform goes with --skill: it runs the cases of one platform's case file.")
        if opts["baseline"] or opts["baseline_on"] or opts["only"] in ("without", "ablated") or opts["ablate"]:
            die("--platform runs a platform's cases with the skill only, as a partial test: no baseline, no ablation.")
    if opts["quick"]:
        # A quick test: every case once with the skill, no baseline, an event of the kind "quick". It chooses nothing else.
        if opts["routing"] or opts["regrade"] is not None or opts["check_cases"] or opts["resume"] is not None \
                or opts["close"] is not None or opts["unpause"]:
            die("--quick goes with --skill: it runs every case of the skill once, with the skill.")
        clash = [flag for flag, on in (("--cases", opts["cases"]), ("--baseline", opts["baseline"]),
                                       ("--baseline-on", opts["baseline_on"]), ("--platform", opts["platform"] is not None),
                                       ("--runs", runs_given), ("--only", opts["only"]), ("--ablate", opts["ablate"] is not None))
                 if on]
        if clash:
            die(f"--quick runs every case once with the skill and no baseline: it does not go with {', '.join(clash)}.")
    if opts["with_setup"] and not opts["check_cases"]:
        die("--with-setup goes with --check-cases: it runs the cases' setup commands in the eval container.")
    if opts["at"] is not None and not opts["unpause"]:
        die("--at goes with --unpause.")
    standalone = (opts["regrade"] is not None or opts["resume"] is not None or opts["unpause"] or opts["close"] is not None
                  or (opts["routing"] and not opts["skill"]))
    for k in () if standalone else ("skill",) if opts["check_cases"] else ("skill", "harness", "model"):
        if not opts[k]:
            die(f"--{k} is required" + (" (evals/eval-gate.json sets no default)." if k != "skill" else "."))
    if opts["only"] not in (None, "with", "without", "ablated"):
        die("--only must be with, without or ablated.")
    on = []
    for name in opts["baseline_on"]:
        listed = status.model_entry(gate, name)["id"] if gate and status.model_entry(gate, name) else name
        if listed in opts["models"]:
            on.append(listed)
        else:
            die(f"--baseline-on {name}: the baseline runs on the lead model (the first --model) by default; another "
                "model is one the event runs.")
    opts["baseline_on"] = sorted(set(on))
    if opts["only"] == "ablated" and not opts["ablate"]:
        die("--only ablated needs --ablate <text>.")
    if opts["ablate"] is not None and not opts["ablate"].strip():
        die("--ablate needs a non-empty text.")
    try:
        opts["runs"], opts["timeout"], opts["jobs"] = int(opts["runs"]), int(opts["timeout"]), int(opts["jobs"])
    except (TypeError, ValueError):
        die("--runs, --jobs and --timeout take whole numbers.")
    if not 1 <= opts["jobs"] <= 8:
        die("--jobs must be between 1 and 8.")
    cap_local_jobs(opts)
    if opts["quick"]:
        opts["runs"] = 1  # one run of each case: the runs of the gate file are what a pool needs, not what a quick test runs
    if not 1 <= opts["runs"] <= 10:
        die("--runs must be between 1 and 10.")
    try:
        opts["retries"], opts["early_rate"] = int(opts["retries"]), float(opts["early_rate"])
    except (TypeError, ValueError):
        die("--retries takes a whole number and --early-end-rate a number such as 0.15.")
    if not 0 <= opts["retries"] <= 5:
        die("--retries must be between 0 and 5.")
    if not 0 <= opts["early_rate"] <= 1:
        die("--early-end-rate must be between 0 and 1.")
    if opts["timeout"] < 30:
        die("--timeout is in seconds and at least 30.")
    if opts["max_cost"] is not None and not re.fullmatch(r"\d+(\.\d+)?", opts["max_cost"]):
        die("--max-cost-usd takes a number, e.g. 0.50.")
    for name in opts["pass_env"]:
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name):
            die(f"--pass-env {name!r} is not a variable name.")
        if token_var(name):
            die(f"--pass-env {name}: token variables for git hosts, npm and the password manager never reach a model run.")
    if opts["regrade"] is not None and not (opts["grader_harness"] and opts["grader"]):
        die("--regrade needs a grader and its adapter: evals/eval-gate.json, or --grader and --harness.")
    return opts


PLATFORM_NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def platform_case_names(skill):
    """The platforms that have a case file for the skill: skills/<skill>/evals/platforms/<platform>.json."""
    folder = os.path.join(ROOT, "skills", skill, "evals", "platforms")
    if not os.path.isdir(folder):
        return []
    return sorted(n[:-len(".json")] for n in os.listdir(folder)
                  if n.endswith(".json") and os.path.isfile(os.path.join(folder, n)))


def load_evals(skill, platform=None, folder=None):
    """The skill's case file: evals/evals.json, or, with platform, that platform's case file,
    evals/platforms/<platform>.json, whose top-level "platform", when it has one, names the same platform. folder is the
    skill's folder when it is not skills/<skill> (a skill from outside, --skill-dir)."""
    rel = ("platforms", platform + ".json") if platform else ("evals.json",)
    p = os.path.join(folder or os.path.join(ROOT, "skills", skill), "evals", *rel)
    if not os.path.isfile(p):
        die(f"no evals at {os.path.relpath(p, ROOT) if not folder else p}", 2)
    with open(p, encoding="utf-8") as f:
        data = json.load(f)
    if platform and isinstance(data, dict) and data.get("platform", platform) != platform:
        die(f"{os.path.relpath(p, ROOT)} names the platform {data.get('platform')!r}: a platform's case file names its own.", 2)
    return data


def platform_problems(platform):
    """Why a platform's case file cannot run: its reference is missing. [] when it has one."""
    if not os.path.isfile(os.path.join(ROOT, "shared", "references", "platforms", platform + ".md")):
        return [f"the platform {platform!r} has no reference: shared/references/platforms/{platform}.md does not exist"]
    return []


def refuse_allow_commands(data, cases):
    """Exit when the evals file or a case still lists "allow_commands": the field has no effect any more."""
    where = (["the top level"] if "allow_commands" in data else []) + \
            [f"case {c.get('id')}" for c in cases if "allow_commands" in c]
    if where:
        die(f"\"allow_commands\" is no longer used ({', '.join(where)}): every command runs, inside the eval "
            "container. Remove the field.")


def allow_web(data, case):
    """Whether the case may search and fetch web pages: "allow_web" at the top level or in the case."""
    for where, value in (("top level", data.get("allow_web")), (f"case {case.get('id')}", case.get("allow_web"))):
        if value is not None and not isinstance(value, bool):
            die(f"{where}: allow_web must be true or false, not {value!r}.")
    return bool(data.get("allow_web") or case.get("allow_web"))


def case_files(skill_dir, case):
    """The case's "files" entries as source paths, refusing any that reach outside the skill folder."""
    base = os.path.realpath(skill_dir)
    inside = lambda path: os.path.commonpath([base, os.path.realpath(path)]) == base
    out = []
    for rel in case.get("files") or []:
        parts = re.split(r"[\\/]", rel) if isinstance(rel, str) else [".."]
        if not isinstance(rel, str) or not rel or os.path.isabs(rel) or rel.startswith("~") or ".." in parts:
            die(f"case {case.get('id')}: files entry {rel!r} must be a relative path inside the skill folder, without '..'.")
        src = os.path.join(skill_dir, rel)
        if not inside(src):
            die(f"case {case.get('id')}: files entry {rel!r} resolves outside the skill folder.")
        for dp, dns, fns in os.walk(src) if os.path.isdir(src) else []:
            for n in dns + fns:
                p = os.path.join(dp, n)
                if os.path.islink(p) and not inside(p):
                    die(f"case {case.get('id')}: {os.path.relpath(p, skill_dir)} links outside the skill folder.")
        out.append(src)
    return out


def dependency_dirs(case):
    """Folders of the skills a case depends on (a flow's phases), staged by the runner in both variants."""
    dirs = []
    for name in case.get("skills") or []:
        if not isinstance(name, str) or not re.match(r"^[a-z0-9-]+$", name):
            die(f"case {case.get('id')}: skills entry {name!r} is not a skill name.")
        src = os.path.join(ROOT, "skills", name)
        if not os.path.isdir(src):
            die(f"case {case.get('id')} depends on skill {name!r}, which does not exist under skills/.")
        dirs.append(src)
    return dirs


# A file that cannot run without a module beside it brings that module into the case folder, so that a case
# which lists the file keeps working when the file is split (the case's hash, which reads the listed paths, is
# unchanged by a companion). evals/eval_status.py loads evals/evidence_lines.py by path.
COMPANIONS = {"evals/eval_status.py": ("evals/evidence_lines.py",)}


def workbench_files(case):
    """The case's "workbench_files" entries as (source path, path in the case folder): files and folders of
    this repository copied into the case at the same relative path, for a skill whose job is the workbench
    itself (it creates, validates or evaluates skills and needs the real tooling to act on). Refused: a path
    that leaves the repository, the repository root, version control, eval workspaces and any skill's eval
    cases (they hold expected outputs). The companions of a listed file (COMPANIONS) come with it."""
    base, out = os.path.realpath(ROOT), []
    listed = list(case.get("workbench_files") or [])
    for rel in list(listed):
        if isinstance(rel, str):
            listed += [c for c in COMPANIONS.get(rel.replace("\\", "/"), ()) if c not in listed]
    for rel in listed:
        parts = [p for p in re.split(r"[\\/]", rel) if p] if isinstance(rel, str) else [".."]
        if not parts or os.path.isabs(rel) or rel.startswith("~") or ".." in parts:
            die(f"case {case.get('id')}: workbench_files entry {rel!r} must be a relative path inside the repository, without '..'.")
        src = os.path.realpath(os.path.join(ROOT, *parts))
        if os.path.commonpath([base, src]) != base or src == base or not os.path.exists(src):
            die(f"case {case.get('id')}: workbench_files entry {rel!r} is not a file or folder of the repository.")
        if parts[0] in (".git", "evals-workspace") or (parts[0] == "skills" and "evals" in parts[1:]):
            die(f"case {case.get('id')}: workbench_files entry {rel!r} is refused: version control, eval workspaces "
                "and a skill's eval cases never go into a case folder.")
        out.append((src, os.path.join(*parts)))
    return out


# Never copied into a case folder: what an interpreter or a desktop left beside a fixture or a repository file.
LITTER = ("__pycache__", "*.pyc", ".pytest_cache", ".DS_Store")


def _skill_ignore(folder, names):
    """For a "workbench_files" entry under skills/: no eval cases and no tests of a skill's scripts, the two
    folders a staged copy of a skill leaves out too, and no litter."""
    drop = set(shutil.ignore_patterns(*LITTER)(folder, names))
    drop.update(n for n in names if n == "evals" or (n == "tests" and os.path.basename(folder) == "scripts"))
    return drop


def build_tree(cwd, sources, case=None):
    """Copy a case's files into its folder: a folder's content goes to the root, a file keeps only its name.
    Then the case's "workbench_files", each at its own relative path, without any skill's evals/ and
    scripts/tests/ folders. Bytecode and system files are never copied."""
    litter = shutil.ignore_patterns(*LITTER)
    for src, rel in workbench_files(case) if case else []:
        dest = os.path.join(cwd, rel)
        if os.path.isdir(src):
            shutil.copytree(src, dest, dirs_exist_ok=True,
                            ignore=_skill_ignore if rel.split(os.sep)[0] == "skills" else litter)
        else:
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copy(src, dest)
    for src in sources:
        if os.path.isdir(src):
            shutil.copytree(src, cwd, dirs_exist_ok=True, ignore=litter)
        elif os.path.isfile(src):
            shutil.copy(src, cwd)


PATH_EXTENSIONS = ("md", "json", "yml", "yaml", "toml", "css", "js", "ts", "py", "html")
TOKEN_RE = re.compile(r"[A-Za-z0-9_.~@/*<>{}\[\]$:+%#=?&-]+")
NOT_A_PATH = set("*<>{}[]$~%#=?&+")
BARE_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]*[A-Za-z0-9_-]\.(?:" + "|".join(PATH_EXTENSIONS) + r")$")
FILE_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+\.[A-Za-z][A-Za-z0-9]{0,4}$")
HOST_RE = re.compile(r"^[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}$")
# Product names that look like a file name ("Node.js", "Next.js"): a capitalized word and .js, no folder.
PRODUCT_RE = re.compile(r"^[A-Z][A-Za-z0-9]*\.(?:js|ts|py)$")


# Folders only the workbench has: a prompt that cites a file there (a contract, a shared reference) names the
# workbench, not an input of the case.
WORKBENCH_DIRS = ("contracts", "shared", "templates", "providers", "adapters", "skills")


def prompt_paths(prompt):
    """Paths a prompt cites: tokens with a "/" and a file extension, or ending in a known extension.

    URLs, absolute and home paths, globs, placeholders and host names are left out."""
    found = []
    for token in TOKEN_RE.findall(prompt or ""):
        if "://" in token:
            continue
        token = token.split(":")[0].rstrip(".,;")
        while token.startswith("./"):
            token = token[2:]
        parts = token.split("/")
        if (not token or NOT_A_PATH & set(token) or token.startswith(("/", "@", "www.")) or ".." in parts
                or "" in parts):
            continue
        if len(parts) == 1:
            if not BARE_NAME_RE.match(token) or PRODUCT_RE.match(token):
                continue
        elif not FILE_NAME_RE.match(parts[-1]) or (HOST_RE.match(parts[0]) and not parts[0].startswith(".")):
            continue
        if token not in found:
            found.append(token)
    return found


def prompt_folders(prompt):
    """Folders a prompt names: tokens that end in "/" ("audit web-summarizer/", "under src/app/"). URLs,
    absolute and home paths, globs and placeholders are left out."""
    found = []
    for token in TOKEN_RE.findall(prompt or ""):
        token = token.rstrip(".,;:)")  # the end of a sentence is not part of the name
        if "://" in token or not token.endswith("/"):
            continue
        token = token.rstrip("/")
        while token.startswith("./"):
            token = token[2:]
        parts = token.split("/")
        if (not token or NOT_A_PATH & set(token) or token.startswith(("/", "@", "~", "www.")) or ".." in parts or "" in parts
                or any(not re.fullmatch(r"[A-Za-z0-9_.-]+", p) for p in parts) or (HOST_RE.match(parts[0]) and len(parts) == 1)):
            continue
        if token not in found:
            found.append(token)
    return found


ROUTER = "core-orchestrator"
# Rules of the preflight that `--check-cases`, which the validator runs on every skill, lists as warnings instead
# of errors, while a real run refuses them like any error. "skills" and "folder" were here while the rows of phase C
# fixed the cases written before them (the final plan, removed on 2026-10-14: git show d3e60770:docs/architecture/final-plan-2026-10-02.md); the sweep that closed phase C
# (C0.10) emptied this tuple, and a rule added later that cases written before it break starts here the same way.
TRANSITIONAL = ()


def skill_text(skill_dir):
    """The text a model reads of a skill: SKILL.md, its references and its scripts (their tests left out)."""
    parts = []
    for dp, dns, fns in os.walk(skill_dir):
        rel = os.path.relpath(dp, skill_dir).replace(os.sep, "/")
        dns[:] = sorted(d for d in dns if not (rel == "." and d == "evals") and not (rel == "scripts" and d == "tests")
                        and d != "__pycache__")
        for fn in sorted(fns):
            if fn == "SKILL.md" or rel.split("/")[0] in ("references", "scripts"):
                parts.append(read_text(os.path.join(dp, fn), TEXT_LIMIT))
    return "\n".join(parts)


def dependency_problems(skill, skill_dir, case):
    """Why a case's "skills" is none of its three allowed uses (evals/README.md, "skills in a case"; default 29):
    a flow's case lists the flow's phases, never the router; a case of the router lists the one leaf skill a
    route needs; a case of a skill whose own text calls another skill's script lists that skill."""
    deps = [d for d in case.get("skills") or [] if isinstance(d, str)]
    if not deps:
        return []
    text = skill_text(skill_dir)
    if skill.startswith("flow-"):
        out = [f"skills lists {ROUTER}, which is not one of a flow's phases: with it the baseline measures the router's "
               "reply and not the model without the flow"] if ROUTER in deps else []
        return out + [f"skills lists {d}, which the flow does not name as a phase" for d in deps if d != ROUTER
                      and not re.search(r"(?<![a-z0-9-])" + re.escape(d) + r"(?![a-z0-9-])", text)]
    if skill == ROUTER:
        leaves = [d for d in deps if not d.startswith("flow-") and d != ROUTER]
        return [] if len(deps) == 1 and leaves else [
            "a case of the router lists one leaf skill, the one a route needs to be ready, and nothing else"]
    return [f"skills lists {d}: none of the three uses of skills in a case (a flow's phases, the router's one leaf skill, "
            f"a skill whose own text calls that skill's script, {d}/scripts/...)" for d in deps if f"{d}/scripts/" not in text]


def tree_paths(cwd):
    """Every file and folder of a case folder, relative, with "/" separators; .git is left out."""
    out = set()
    for dp, dns, fns in os.walk(cwd):
        dns[:] = [d for d in dns if d != ".git"]
        for n in dns + fns:
            out.add(os.path.relpath(os.path.join(dp, n), cwd).replace(os.sep, "/"))
    return out


def declared_outputs(skill_dir):
    """Paths under metadata.outputs in the skill's frontmatter: a run creates them, so a prompt may name them."""
    try:
        with open(os.path.join(skill_dir, "SKILL.md"), encoding="utf-8") as f:
            head = f.read().split("\n---", 1)[0]
    except OSError:
        return []
    m = re.search(r"^\s*outputs:\s*\[(.*?)\]", head, re.M | re.S)
    if m:
        return [x.strip().strip("\"'") for x in m.group(1).split(",") if x.strip()]
    m = re.search(r"^\s*outputs:\s*\n((?:\s*-\s.*\n?)+)", head, re.M)
    return [x.strip()[1:].strip().strip("\"'") for x in m.group(1).splitlines() if x.strip()] if m else []


def case_assertion_text(assertion):
    """The text of an assertion as the preflight reads the case file: the assertion itself, or the "text" of an
    object; None when it is neither. It checks the case file's form and decides nothing the grader sees: the
    grading prompt takes the text from evals/measure.py (assertion_text), which the preflight does not need."""
    if isinstance(assertion, str):
        return assertion
    if isinstance(assertion, dict) and isinstance(assertion.get("text"), str):
        return assertion["text"]
    return None


TAG_RE = re.compile(r"^(?:guard|format|guard:[a-z][a-z0-9-]*)$")


def assertion_form_problems(assertion, effects):
    """Why one assertion of a case file is outside its form (evals/README.md, "Assertions"), each sentence to follow
    "assertion <n>": a text, or an object with its text and at least one tag of the closed list guard,
    guard:<effect> (an effect of the skill's side_effects) and format."""
    if case_assertion_text(assertion) is None:
        return ['must be a text, or an object with a "text"']
    if isinstance(assertion, str):
        return [] if assertion.strip() else ["is an empty text"]
    out = []
    extra = sorted(set(assertion) - {"text", "tags"})
    if extra:
        out.append(f"has keys other than text and tags: {', '.join(extra)}")
    if not assertion["text"].strip():
        out.append("has an empty text")
    tags = assertion.get("tags")
    if not (isinstance(tags, list) and tags and all(isinstance(t, str) for t in tags)):
        return out + ["needs at least one tag (guard, guard:<effect> or format); an assertion with no tag is written as a text"]
    if len(set(tags)) != len(tags):
        out.append("names a tag twice")
    for tag in tags:
        if not TAG_RE.match(tag):
            out.append(f"has the tag {tag!r}, which is not guard, guard:<effect> or format")
        elif tag.startswith("guard:") and tag[len("guard:"):] not in effects:
            out.append(f"has the tag {tag!r}, whose effect the skill does not declare in side_effects")
    return out


def declared_side_effects(skill_dir):
    """The words of metadata.side_effects in the skill's frontmatter (a one-line list or a block list)."""
    try:
        with open(os.path.join(skill_dir, "SKILL.md"), encoding="utf-8") as f:
            head = f.read().split("\n---", 1)[0]
    except OSError:
        return []
    m = re.search(r"^\s*side_effects:\s*\[(.*?)\]", head, re.M | re.S)
    if m:
        return [x.strip().strip("\"'") for x in m.group(1).split(",") if x.strip()]
    m = re.search(r"^\s*side_effects:\s*\n((?:\s*-\s.*\n?)+)", head, re.M)
    return [x.strip()[1:].strip().strip("\"'") for x in m.group(1).splitlines() if x.strip()] if m else []


def preflight(skill_dir, cases, sources, setup=True, gate=None, warnings=None, platform=None, web_cases_ok=False):
    """Check every case before a model sees it. Returns (errors, unchecked): one line per problem.

    setup=False (--dry-run) runs no setup command, so cases that have one are not checked against their folder.
    gate is the loaded gate configuration: a case that sets "allow_web" must be among its "web_cases". warnings,
    a list, receives the problems of TRANSITIONAL rules instead of errors (see TRANSITIONAL). platform names the
    platform whose case file the cases come from (None: evals/evals.json). web_cases_ok (--allow-web-cases of a skill from
    outside) leaves the web_cases check to the audit gate of the event, because a skill from outside is in no list."""
    errors, unchecked = [], []
    skill = os.path.basename(os.path.normpath(skill_dir))
    status = load_status()
    top_web = None
    try:
        with open(os.path.join(skill_dir, "evals", *(("platforms", platform + ".json") if platform else ("evals.json",))),
                  encoding="utf-8") as f:
            top_web = json.load(f).get("allow_web")
    except (OSError, ValueError, AttributeError):
        pass
    outputs, effects = declared_outputs(skill_dir), declared_side_effects(skill_dir)
    settings = harness_settings()
    # The skill's own files (scripts, references, assets) reach a run with the skill, not through the case.
    own = {p for p in tree_paths(skill_dir) if not p.startswith("evals/") and p != "evals"}
    known = lambda p: (p in own or any(t.endswith("/" + p) for t in own)
                       or (p.split("/")[0] in WORKBENCH_DIRS and os.path.exists(os.path.join(ROOT, p))))
    for c in cases:
        cid = c.get("id")
        err = lambda msg: errors.append(f"case {cid}: {msg}")
        later = lambda msg, rule: (warnings.append(f"case {cid}: {msg}") if warnings is not None and rule in TRANSITIONAL
                                   else errors.append(f"case {cid}: {msg}"))
        for problem in dependency_problems(skill, skill_dir, c):
            later(problem, "skills")
        if ((c.get("allow_web") is True or top_web is True) and gate and not web_cases_ok
                and not status.web_case_allowed(gate, skill, cid)):
            err('sets "allow_web" and is not in "web_cases" of evals/eval-gate.json: the network is opened for the '
                "cases listed there and for no other")
        for rel, src in zip(c.get("files") or [], sources[cid]):
            if not os.path.exists(src):
                err(f"files entry {rel!r} does not exist in the skill folder")
        for name in c.get("skills") or []:
            if not isinstance(name, str) or not os.path.isdir(os.path.join(ROOT, "skills", name)):
                err(f"skills entry {name!r} is not a skill under skills/")
        absent = c.get("absent_on_purpose") or []
        if not isinstance(absent, list) or not all(isinstance(p, str) for p in absent):
            err("absent_on_purpose must be a list of paths")
            absent = []
        platforms = c.get("platforms") or []
        if not isinstance(platforms, list) or not all(isinstance(p, str) and re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", p) for p in platforms):
            err("platforms must be a list of platform names")
            platforms = []
        for name in platforms:
            if not os.path.isfile(os.path.join(ROOT, "shared", "references", "platforms", name + ".md")):
                err(f"platforms entry {name!r} has no reference: shared/references/platforms/{name}.md does not exist")
        if c.get("setup") and not setup:
            unchecked.append(f"case {cid}: has setup commands, which --dry-run does not run; prompt paths and "
                             "grader_files are checked by --check-cases and by a real run")
            continue
        tmp = tempfile.mkdtemp(prefix="eval-preflight-")
        try:
            cwd = os.path.join(tmp, "cwd")
            os.makedirs(cwd)
            build_tree(cwd, sources[cid], c)
            if c.get("setup"):
                quiet = {"root": tmp, "network": "none"}  # in the eval container, like the run's own setup
                isolate_git(cwd, contained_env(tmp), box=quiet)
                run_setup(cwd, c["setup"], contained_env(tmp), box=quiet)
            tree = tree_paths(cwd)
            carried = settings_in(cwd, settings)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        if carried:
            err(f"the case folder holds {carried}: a fixture or setup must not carry harness settings")
        present = lambda p: p in tree or any(t.endswith("/" + p) for t in tree)
        for n, a in enumerate(c.get("assertions") or [], 1):
            for problem in assertion_form_problems(a, effects):
                err(f"assertion {n} {problem}")
        tagged = sorted({t for a in c.get("assertions") or [] if isinstance(a, dict) for t in a.get("tags") or []
                         if isinstance(t, str)})
        if "tags" in c and not (isinstance(c["tags"], list) and all(isinstance(t, str) for t in c["tags"])
                                and sorted(c["tags"]) == tagged):
            err(f"tags must list exactly the tags of its assertions, each once: {tagged}")
        produced = " ".join([str(c.get("expected_output") or "")] + [case_assertion_text(a) or "" for a in c.get("assertions") or []])
        for p in prompt_paths(c.get("prompt")):
            if (present(p) or p in absent or p in produced or known(p)
                    or any(o == p or o.endswith("/" + p) for o in outputs)):
                continue
            err(f"the prompt cites {p!r}, which is not in the case folder: ship it under \"files\" at that path, "
                "or list it in \"absent_on_purpose\" when the case tests a missing input")
        for p in prompt_folders(c.get("prompt")):
            if (p in tree or any(t.endswith("/" + p) for t in tree) or p in absent or p + "/" in absent or p in produced
                    or known(p) or any(o == p or o.startswith(p + "/") for o in outputs)):
                continue
            later(f"the prompt names the folder {p + '/'!r}, which is not a folder of the case: a folder in \"files\" is "
                  "copied by content, so its own name is not in the case. Put it one level down in the fixture, or name "
                  "what is inside it", "folder")
        for p in c.get("grader_files") or []:
            if not isinstance(p, str) or p.strip("/") not in tree:
                err(f"grader_files entry {p!r} is not in the case folder, so the grader would see an empty file")
    return errors, unchecked


class EventStopped(Exception):
    """A run that was not started because its event stopped: it gets no ledger line, so --resume runs it."""


def mount_patterns():
    """What names a path of the workbench in a run's output: the folder the one adapter script is mounted in
    inside a container (as a path of its own, not as the end of another one), and the repository's absolute
    path on the host."""
    folder = os.path.dirname(load_executor().RUNNER_MOUNT)  # /wb
    patterns = [re.compile(r"(?<![A-Za-z0-9_./~-])" + re.escape(folder) + r"(?![A-Za-z0-9_.-])")]
    return patterns + [re.compile(re.escape(root)) for root in sorted(repo_paths(), key=len, reverse=True)]


def contamination(out_dir, cwd=None, produced=()):
    """Evidence that a run named a mount path of the workbench or the repository: in its reply, in its transcript
    (the adapter's stderr and raw output) or, with cwd, in a file it produced. None when there is none."""
    texts = [(name, read_text(os.path.join(out_dir, name), 5000000)) for name in ("response.md", "stderr.log", "raw.json")]
    texts += [(rel, read_text(os.path.join(cwd, rel), 5000000)) for rel in produced if cwd and readable(cwd, rel)]
    for name, text in texts:
        for pattern in mount_patterns():
            m = pattern.search(text)
            if m:
                at = m.start()
                line = text[max(text.rfind("\n", 0, at) + 1, at - 80):m.end() + 120].split("\n")[0]
                return f"{name}: {line.strip()[:300]}"
    return None


PASSAGE_WORDS = 10  # a passage of this many words in a row, shared with the skill's text, is worth a person's look
WORD_RE = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")
TEXT_LIMIT = 2000000  # characters read of one file for the passage check


def words_of(text):
    return WORD_RE.findall(text.lower().replace("\u2019", "'"))


def passages_of(word_list, n=PASSAGE_WORDS):
    return {tuple(word_list[i:i + n]) for i in range(len(word_list) - n + 1)}


def folder_text(folder, staged=()):
    """The text of the files of a folder that the host may read (run_files()), binary files left out."""
    parts = []
    for rel in run_files(folder, staged):
        path = os.path.join(folder, rel)
        if load_measure().binary_stub(path) is None:
            parts.append(read_text(path, TEXT_LIMIT))
    return "\n".join(parts)


def skill_passages(skill_dir):
    """Every passage of PASSAGE_WORDS words of the skill's own text: SKILL.md, references/ and assets/."""
    texts = [read_text(os.path.join(skill_dir, "SKILL.md"), TEXT_LIMIT)]
    for sub in ("references", "assets"):
        if os.path.isdir(os.path.join(skill_dir, sub)):
            texts.append(folder_text(os.path.join(skill_dir, sub)))
    found = set()
    for text in texts:  # per file group: a passage never spans two files
        found |= passages_of(words_of(text))
    return found


def shared_passage(skill_grams, run_text, case_text):
    """The longest passage of at least PASSAGE_WORDS words that a without-skill run's output shares with the
    skill's text and that is not in the case (its prompt, its folder as the run found it); None when there is
    none. The case is read only when something is shared at all."""
    run_words = words_of(run_text)
    n = PASSAGE_WORDS
    hits = [i for i in range(len(run_words) - n + 1) if tuple(run_words[i:i + n]) in skill_grams]
    if not hits:
        return None
    case_grams = passages_of(words_of(case_text))
    hits = [i for i in hits if tuple(run_words[i:i + n]) not in case_grams]
    best, start, prev = None, None, None
    for i in hits + [None]:  # consecutive positions are one passage
        if start is None:
            start = i
        elif i is None or i != prev + 1:
            if best is None or prev - start > best[1] - best[0]:
                best = (start, prev)
            start = i
        prev = i
    return " ".join(run_words[best[0]:best[1] + n]) if best else None


def ablated_line_count(skill_dir, text):
    """Lines of SKILL.md that --ablate removes; exits when there are none."""
    with open(os.path.join(skill_dir, "SKILL.md"), encoding="utf-8") as f:
        count = sum(1 for line in f if text in line)
    if not count:
        die(f"--ablate: no line of SKILL.md contains {text!r}.")
    return count


def ablated_copy(skill_dir, text, dest_root):
    """Copy the skill without its evals/ and without every SKILL.md line containing text."""
    dest = os.path.join(dest_root, os.path.basename(skill_dir))
    if os.path.exists(dest):
        shutil.rmtree(dest)
    shutil.copytree(skill_dir, dest, ignore=shutil.ignore_patterns("evals"))
    path = os.path.join(dest, "SKILL.md")
    with open(path, encoding="utf-8") as f:
        lines = f.readlines()
    kept = [line for line in lines if text not in line]
    if len(kept) == len(lines):
        die(f"--ablate: no line of SKILL.md contains {text!r}.")
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(kept)
    return dest, len(lines) - len(kept)


def next_iteration(ws, claim=True):
    """The next iteration folder of a skill's workspace. With claim it is created here, atomically, so two
    runs of the same skill started together never share one; a dry run only names it."""
    os.makedirs(ws, exist_ok=True)
    while True:
        nums = [int(d.split("-")[1]) for d in os.listdir(ws) if re.match(r"^iteration-\d+$", d)]
        path = os.path.join(ws, f"iteration-{max(nums, default=0) + 1}")
        if not claim:
            return path
        try:
            os.mkdir(path)
            return path
        except FileExistsError:
            continue


def early_end_stats(counts):
    """benchmark.json "early_ends" from {model id: {"attempts", "early_ends", "by_case", "by_variant"}}: adds the rate."""
    return {model: {"attempts": c["attempts"], "early_ends": c["early_ends"],
                   "rate": round(c["early_ends"] / c["attempts"], 3) if c["attempts"] else 0.0,
                   "by_case": {str(k): n for k, n in c["by_case"].items() if n},
                   "by_variant": {str(k): n for k, n in (c.get("by_variant") or {}).items() if n}}
            for model, c in counts.items()}


def early_end_warning(stats, max_rate):
    """A sentence when a model's early ends are frequent or all on one case (at least 3 either way), else None."""
    parts = []
    for model, s in stats.items():
        one_case = list(s["by_case"]) if len(s["by_case"]) == 1 else []
        if s["early_ends"] < 3 or not (s["rate"] > max_rate or one_case):
            continue
        where = (f"All of them are on case {one_case[0]}: the skill or that case may trigger it; read its transcripts "
                 "before blaming the provider." if one_case else
                 f"They spread over cases {', '.join(s['by_case'])}: if they concentrate on one case, the skill or the "
                 "case may trigger it (read the transcripts); if they spread across cases, the provider or the model "
                 f"may be unreliable: consider another provider for this model, or another model.")
        parts.append(f"{model} ended its turn early in {s['early_ends']} of {s['attempts']} attempts "
                     f"({s['rate']:.0%}): retries hid them from the scores. {where}")
    return " ".join(parts) or None


def snapshot(cwd, before, staged=()):
    """The files a run created or changed (changes()), as a sorted list."""
    delta = changes(cwd, before, staged)
    return sorted(delta["created"] + delta["modified"])


def run_setup(cwd, commands, env, box=None):
    """Run a case's setup commands in its folder (a branch, commits), after its repository exists, contained."""
    for command in commands:
        try:
            # security-scan: allow shell-string -- setup lines come from the skill's evals.json, are listed by --dry-run and run in the contained environment
            r = run_group(["bash", "-c", command], SETUP_TIMEOUT, cwd=cwd, env=env, box=box)
        except subprocess.TimeoutExpired:
            die(f"setup command timed out after {SETUP_TIMEOUT}s in {cwd}: {command}")
        if r.returncode != 0:
            die(f"setup command failed in {cwd}: {command}\n{r.stderr}")


VCS_TIMEOUT = 120  # seconds


def version_control(case_dir, env, box=None):
    """The state of the case's repository after a run, as text for the facts block: the working tree, the last
    commits of every branch, the branches, and the branch heads of each remote the case has (a local bare
    repository; another protocol is refused by GIT_ALLOW_PROTOCOL=file). Commits, branches and pushes live
    under .git, which the file lists leave out: without this an assertion about a push rests on the reply."""
    measure = load_measure()
    try:
        # security-scan: allow shell-string -- VCS_SCRIPT is a literal of evals/measure.py; it runs in the case folder, contained, with no network
        r = run_group(["bash", "-c", measure.VCS_SCRIPT], VCS_TIMEOUT, cwd=case_dir, env=env, box=box)
    except subprocess.TimeoutExpired:
        return f"(not read: the commands did not end within {VCS_TIMEOUT}s)"
    return measure.cut_vcs(r.stdout)


def shown_in(cwd, rel):
    """What the grader is told about the path rel of a case folder: its content, or one line when the host does
    not read it (readable())."""
    return load_measure().shown(os.path.join(cwd, rel)) if readable(cwd, rel) else load_measure().NOT_SHOWN


def run_record_hash(run_dir):
    """sha256 over what a run left that a later re-grading reads: prompt.md, facts.md, outputs/response.md and every
    regular file under cwd/ (sorted relative paths and their bytes; a symbolic link is skipped). The gradings, the
    timing, the event stream and anything added later (regrade-<k>/) are outside it."""
    paths = [p for p in ("prompt.md", "facts.md", os.path.join("outputs", "response.md"))
             if os.path.isfile(os.path.join(run_dir, p)) and not os.path.islink(os.path.join(run_dir, p))]
    cwd = os.path.join(run_dir, "cwd")
    for dp, dns, fns in os.walk(cwd):
        dns[:] = sorted(d for d in dns if not os.path.islink(os.path.join(dp, d)))
        for fn in fns:
            path = os.path.join(dp, fn)
            if os.path.isfile(path) and not os.path.islink(path):
                paths.append(os.path.relpath(path, run_dir))
    h = hashlib.sha256()
    for rel in sorted(paths):
        with open(os.path.join(run_dir, rel), "rb") as f:
            data = f.read()
        h.update(rel.replace(os.sep, "/").encode("utf-8") + b"\0" + str(len(data)).encode() + b"\0" + data)
    return h.hexdigest()


def template_hash():
    """sha256 of the grading template: the instrument a grading was made with."""
    with open(GRADING_TEMPLATE, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def grading_call(runner, grader, prompt, dest, count, pass_env=(), timeout=900, account=None, redact=()):
    """Send one grading prompt to the grader, with no tools, until an answer is accepted or the retries are
    spent. Its folders come back to dest (prompt.md, out/); a refused attempt is kept in <dest>-refused-<k>.
    account = {"key", "markers", "probe", "control", "model"} (model: the grader's id, which names its place of the
    shared lock) makes the call wait while its account is paused, take a
    place of the shared lock, and pause the account when the call meets its limit: that call is made again
    after the pause and is not counted as refused.
    redact is redaction_values(): the values of the variables any run of the event received. They are replaced
    in the prompt before it is sent (the reply and the files were already rewritten; this is the last guard
    before the text leaves for the grader's provider) and in what the grading call left.
    Returns (results or None, refused attempts, why the last one was refused, pauses)."""
    refused, why, pauses = 0, None, 0
    prompt, _ = load_measure().replace_values(prompt, redact)
    while True:
        if account:
            wait_while_paused(account["key"], account["probe"])
        # The grader is a model too: it works outside the repository, in a folder of its own.
        with (Slots(account["control"], account["model"]) if account else contextlib.nullcontext()):
            root = new_run_root(dest, out_name="out")
            try:
                gp = os.path.join(root, "prompt.md")
                with open(gp, "w", encoding="utf-8") as f:
                    f.write(prompt)
                ok = run_prompt(runner, gp, os.path.join(root, "case"), grader, os.path.join(root, "out"),
                                env=contained_env(root, pass_env), timeout=timeout, start_dir=root, no_tools=True,
                                box={"root": root, "runner": runner, "pass": pass_env, "network": "proxy"})
            finally:
                redact_folder(os.path.join(root, "out"), list(redact) + load_measure().redaction_values(pass_env))
                return_run(root)
        if not ok and account and account_limit(os.path.join(dest, "out"), account["markers"]):
            pauses += 1
            start_pause(account["key"], "a grading call")
            shutil.rmtree(dest, ignore_errors=True)
            if STOPPING.is_set():
                return None, refused, "stopped during a pause on the account limit", pauses
            continue
        if ok:
            results, why = load_measure().read_grading(read_text(os.path.join(dest, "out", "response.md"), 400000), count)
            if results is not None:
                return results, refused, None, pauses
        else:
            why = "the grader's adapter failed: " + read_text(os.path.join(dest, "out", "error.log"), 300).strip()
        refused += 1
        kept = f"{dest}-refused-{refused}"
        if os.path.isdir(kept):
            shutil.rmtree(kept)
        shutil.move(dest, kept)
        if refused > load_measure().GRADING_RETRIES or STOPPING.is_set():
            return None, refused, why, pauses


def grade(runner, grader, run_dir, case, response, delta, inputs=None, vcs=None, pass_env=(), timeout=900, account=None,
          redact=(), guards=False):
    """Grade one run. delta is changes() of its case folder, inputs the case's "grader_files" as the run found
    them ({path: what the grader is shown}), vcs the text of version_control().
    Returns {"assertion_results", "summary", "refused"}, or {"refused", "reason"} with no results when every
    attempt was refused.
    guards=True (a with-skill run): when the grading fails a guard assertion, the same prompt is graded once
    more (<run folder>/grading-guard/), and "guard_failed" lists the guard positions the second grading failed
    too; "assertion_results" and the summary stay the first grading's, so the second raises no mean. A second
    grading refused on every attempt leaves the run with no grading, like a first one."""
    with open(GRADING_TEMPLATE, encoding="utf-8") as f:
        tpl = f.read()
    cwd = os.path.join(run_dir, "cwd")
    produced = sorted(delta["created"] + delta["modified"])
    files_blob = "\n".join(f"### {p}\n{shown_in(cwd, p)}" for p in produced) or "(none)"
    inputs_blob = "\n".join(f"### {p}\n{text}" for p, text in (inputs or {}).items()) or "(none)"
    facts = load_measure().facts_block(delta, vcs)
    with open(os.path.join(run_dir, "facts.md"), "w", encoding="utf-8") as f:
        f.write(facts + "\n")
    prompt = load_measure().grading_prompt(tpl, case, response, facts, files_blob, inputs_blob)
    results, refused, why, pauses = grading_call(runner, grader, prompt, os.path.join(run_dir, "grading"),
                                                 len(case.get("assertions") or []), pass_env, timeout, account, redact)
    if results is None:
        return {"refused": refused, "reason": why, "pauses": pauses}
    measure = load_measure()
    out = {"assertion_results": results, "summary": measure.grading_summary(results), "refused": refused, "pauses": pauses}
    failed = measure.failed_guards(case, results) if guards else []
    if failed:
        second, refused2, why2, pauses2 = grading_call(runner, grader, prompt, os.path.join(run_dir, "grading-guard"),
                                                       len(case.get("assertions") or []), pass_env, timeout, account, redact)
        out["refused"], out["pauses"] = refused + refused2, pauses + pauses2
        if second is None:
            return {"refused": refused + refused2, "reason": f"the second grading of failed guard verdict(s) {failed}: {why2}",
                    "pauses": pauses + pauses2}
        out["guard_regrade"] = {"failed": failed, "assertion_results": second}
        out["guard_failed"] = measure.confirmed_guards(failed, second)
    return out


def regrade(o):
    """--regrade: grade stored replies again and report how many verdicts differ. No score moves, no evidence."""
    runner = os.path.join(ROOT, "adapters", o["grader_harness"], "run-prompt.sh")
    if not os.path.isfile(runner):
        die(f"adapter {o['grader_harness']!r} has no run-prompt.sh (see AGENTS.md, Adding an adapter).")
    base = os.path.abspath(o["regrade"])
    print(f"--regrade acts on {base}", file=sys.stderr)
    found = []
    for dp, dns, fns in os.walk(base):
        dns.sort()
        if "grading.json" in fns and os.path.isfile(os.path.join(dp, "grading", "prompt.md")):
            found.append(dp)
            dns[:] = []
    if not found:
        die(f"no graded run under {o['regrade']}: a graded run has grading.json and grading/prompt.md.")
    pass_env = o["pass_env"] + o["grader_pass_env"]
    for filled in resolve_pass_env(pass_env):
        print(f"--pass-env {filled}", file=sys.stderr)
    unset = [n for n in pass_env if not os.environ.get(n)]
    if unset:
        die(f"{', '.join(unset)} is not set and was not found in the secret store.", 2)
    if EXECUTOR == "container":
        try:
            load_executor().ensure()
        except Exception as e:
            die(f"the eval container is not available: {e}", 1)
    # The account a test event's grading gets: each grading call waits while it is paused, takes a place of the
    # shared lock, and pauses it at its limit, where the call is made again and is not counted as refused.
    status = load_status()
    account = {"key": o["grader_harness"], "markers": adapter_eval(o["grader_harness"])["account_limit"],
               "probe": lambda: probe_call(runner, o["grader"], pass_env),
               "control": status.event_config(status.load_gate(ROOT)), "model": o["grader"]}

    def one(run_dir):
        with open(os.path.join(run_dir, "grading.json"), encoding="utf-8") as f:
            old = [bool(r.get("passed")) for r in json.load(f).get("assertion_results") or []]
        prompt = read_text(os.path.join(run_dir, "grading", "prompt.md"), 50000000)
        k = 1
        while True:  # claimed here, so two regrades of one folder never share a number
            try:
                os.mkdir(os.path.join(run_dir, f"regrade-{k}"))
                break
            except FileExistsError:
                k += 1
        dest = os.path.join(run_dir, f"regrade-{k}", "grading")
        results, refused, why, _ = grading_call(runner, o["grader"], prompt, dest, len(old), pass_env, o["timeout"],
                                                account=account, redact=load_measure().redaction_values(pass_env))
        row = {"run": os.path.relpath(run_dir, base), "verdicts": len(old), "refused": refused}
        if results is None:
            return {**row, "failed": why}
        new = [r["passed"] for r in results]
        with open(os.path.join(run_dir, f"regrade-{k}", "grading.json"), "w", encoding="utf-8") as f:
            json.dump({"grader": o["grader"], "assertion_results": results, "summary": load_measure().grading_summary(results)}, f, indent=2)
        return {**row, "differ": [i + 1 for i, (a, b) in enumerate(zip(old, new)) if a != b],
                "failed_verdicts": [i + 1 for i, a in enumerate(old) if not a],
                "failed_differ": [i + 1 for i, (a, b) in enumerate(zip(old, new)) if not a and b]}

    with concurrent.futures.ThreadPoolExecutor(max_workers=o["jobs"]) as pool:
        rows = list(pool.map(one, found))
    done = [row for row in rows if "failed" not in row]
    verdicts, differ = sum(row["verdicts"] for row in done), sum(len(row["differ"]) for row in done)
    old_failed, failed_differ = sum(len(row["failed_verdicts"]) for row in done), sum(len(row["failed_differ"]) for row in done)
    for row in rows:
        if "failed" in row:
            print(f"REGRADE FAILED {row['run']}: {row['failed']}", file=sys.stderr)
    print(json.dumps({"regrade": os.path.relpath(base, ROOT) if base.startswith(ROOT + os.sep) else base, "grader": o["grader"],
                      "gradings": len(done), "failed": len(rows) - len(done), "verdicts": verdicts, "differ": differ,
                      "share": (differ / verdicts) if verdicts else None,
                      # The verdicts the stored grading failed, and how many of them the new one passed: a grader
                      # that approves everything agrees on most verdicts and on none of these.
                      "failed_verdicts": old_failed, "failed_differ": failed_differ,
                      "runs": [{k: v for k, v in row.items() if k in ("run", "verdicts", "differ", "failed", "refused")} for row in rows]},
                     indent=2))
    return 1 if len(done) < len(rows) else 0


def pack_skills(pack):
    """The skills a pack selects, as scripts/select_skills.py resolves it (packs/<name>.txt)."""
    script = os.path.join(ROOT, "scripts", "select_skills.py")
    if not os.path.isfile(script):
        die("scripts/select_skills.py is missing: run this script from a checkout of the workbench.")
    r = subprocess.run([sys.executable, script, "--pack", pack], capture_output=True, text=True, cwd=ROOT)
    if r.returncode != 0:
        die(f"--pack {pack}: {(r.stderr or r.stdout).strip()[-300:]}")
    return json.loads(r.stdout)


def routing(o):
    """--routing: which skill loads, among a whole pack, for each prompt. Scores nothing, writes no evidence."""
    names = pack_skills(o["pack"])
    if o["skill"] and o["skill"] not in names:
        die(f"{o['skill']} is not in the pack {o['pack']}: the routing mode asks whether it loads among them.")
    dirs = [os.path.join(ROOT, "skills", n) for n in names]
    if o["skill"]:
        skill_dir = os.path.join(ROOT, "skills", o["skill"])
        evals = load_evals(o["skill"])
        items = [{"case": c["id"], "prompt": c["prompt"], "sources": case_files(skill_dir, c), "case_def": c}
                 for c in evals.get("evals") or []]
    else:
        try:
            with open(o["prompts"], encoding="utf-8") as f:
                texts = json.load(f)
        except (OSError, ValueError) as e:
            die(f"--prompts {o['prompts']}: {e}")
        if not isinstance(texts, list) or not texts or not all(isinstance(t, str) and t.strip() for t in texts):
            die("--prompts takes a file that holds a JSON list of prompts, each a text.")
        items = [{"prompt": t, "sources": [], "case_def": None} for t in texts]
    harness, model = o["harness"], o["model"]
    runner = os.path.join(ROOT, "adapters", harness, "run-prompt.sh")
    if not os.path.isfile(runner):
        die(f"adapter {harness!r} has no run-prompt.sh.")
    eval_cfg = adapter_eval(harness)
    pass_env = o["pass_env"] + o["pass_envs"].get(model, [])
    for filled in resolve_pass_env(pass_env):
        print(f"--pass-env {filled}", file=sys.stderr)
    unset = [n for n in pass_env if not os.environ.get(n)]
    if unset:
        die(f"{', '.join(unset)} is not set and was not found in the secret store.", 2)
    if EXECUTOR == "container":
        try:
            load_executor().ensure()
        except Exception as e:
            die(f"the eval container is not available: {e}", 1)
    control = load_status().event_config(load_status().load_gate(ROOT))
    base = os.path.join(ROOT, "evals-workspace", "routing")
    os.makedirs(base, exist_ok=True)
    k = 1
    while True:  # claimed here, so two routing runs never share a folder
        folder = os.path.join(base, f"{o['pack']}-{k}")
        try:
            os.mkdir(folder)
            break
        except FileExistsError:
            k += 1
    values = load_measure().redaction_values(pass_env)

    def one(index, item):
        run_dir = os.path.join(folder, f"prompt-{index}")
        account = {"key": harness, "markers": eval_cfg["account_limit"], "probe": lambda: probe_call(runner, model, pass_env)}
        while True:
            wait_while_paused(account["key"], account["probe"])
            with Slots(control, model):
                root = new_run_root(run_dir, names=(o["skill"] or "routing",))
                case_dir = os.path.join(root, "case")
                try:
                    build_tree(case_dir, item["sources"], item["case_def"])
                    quiet = {"root": root, "network": "none"}
                    isolate_git(case_dir, contained_env(root), box=quiet)
                    if item["case_def"]:
                        run_setup(case_dir, item["case_def"].get("setup") or [], contained_env(root), box=quiet)
                    # The whole pack, as an installer stages it: every skill, every shared reference beside them.
                    skills_dir = os.path.join(case_dir, *eval_cfg["skills_dir"].split("/"))
                    manifest = load_stage().stage(dirs, skills_dir, root=ROOT, references="all")
                    exclude_from_git(case_dir, [os.path.relpath(os.path.join(skills_dir, n), case_dir) for n in manifest["skills"]]
                                     + ([os.path.relpath(manifest["shared_dir"], case_dir)] if manifest["shared_dir"] else []))
                    pp = os.path.join(root, "prompt.md")
                    with open(pp, "w", encoding="utf-8") as f:
                        f.write(item["prompt"])
                    why = run_failure(runner, pp, case_dir, model, os.path.join(root, "out"), contained_env(root, pass_env),
                                      o["timeout"], o["max_cost"], False, start_dir=root,
                                      box={"root": root, "runner": runner, "pass": pass_env, "network": "proxy"})
                finally:
                    redact_folder(os.path.join(root, "out"), values)
                    return_run(root)
            out = os.path.join(run_dir, "outputs")
            if why and account_limit(out, account["markers"]):
                start_pause(account["key"], f"routing prompt {index}")
                continue
            break
        try:
            with open(os.path.join(out, "timing.json"), encoding="utf-8") as f:
                loaded = json.load(f).get("skills_loaded")
        except (OSError, ValueError, AttributeError):
            loaded = None
        row = {**({"case": item["case"]} if "case" in item else {"prompt": item["prompt"][:200]}),
               "loaded": loaded if isinstance(loaded, list) else None, **({"failed": why} if why else {})}
        if o["skill"] and isinstance(loaded, list):
            row["invoked"] = o["skill"] in loaded
            row["others"] = [n for n in loaded if n != o["skill"]]
        return row

    with concurrent.futures.ThreadPoolExecutor(max_workers=o["jobs"]) as pool:
        rows = list(pool.map(lambda pair: one(*pair), enumerate(items, 1)))
    loaded_another = [r["case"] for r in rows if o["skill"] and r.get("loaded") is not None
                      and (r.get("others") or not r.get("invoked"))]
    result = {"routing": True, "pack": o["pack"], "model": model, "skill": o["skill"],
              "folder": os.path.relpath(folder, ROOT), "prompts": rows, "loaded_another": loaded_another,
              "not_reported": sum(1 for r in rows if r.get("loaded") is None)}
    with open(os.path.join(folder, "routing.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    for r in rows:
        if r.get("failed"):
            print(f"ROUTING     {r.get('case', r.get('prompt'))}: the run failed ({r['failed']})", file=sys.stderr)
    if o["skill"] and loaded_another:
        print(f"ROUTING     {o['skill']}: in case(s) {', '.join(str(c) for c in loaded_another)} another skill loaded, or the "
              "skill did not: read the descriptions of the skills that loaded", file=sys.stderr)
    print(json.dumps(result, indent=2))
    return 1 if any(r.get("failed") for r in rows) else 0


def check_cases_only(o):
    """--check-cases: the preflight alone, on evals/evals.json and on every platform's case file of the skill
    (with --platform, on that platform's file only). Prints {"skill", "cases", "errors", "unchecked"[,
    "platforms"][, "warnings"]}: the problems of a platform's file start with platforms/<name>.json. Exit 2 on
    errors. --cases filters the file the command names (evals/evals.json, or the --platform file)."""
    skill_dir = skill_folder(o)
    gate = load_status().load_gate(ROOT)
    files = [o["platform"]] if o["platform"] else [None] + ([] if o.get("skill_dir") else platform_case_names(o["skill"]))
    errors, unchecked, warnings, total = [], [], [], 0
    for platform in files:
        data = load_evals(o["skill"], platform, o.get("skill_dir"))
        cases = data.get("evals") or []
        if platform == files[0] and o["cases"]:
            cases = [c for c in cases if str(c.get("id")) in o["cases"]]
        if not cases and platform == files[0]:
            die("no matching eval cases.")
        refuse_allow_commands(data, cases)
        label = f"platforms/{platform}.json " if platform else ""
        # A case's setup commands run only in the eval container, which a real run starts; this static check
        # needs no container, so such a case is listed as unchecked here and checked before the first model call.
        found = []
        errs, uncheck = preflight(skill_dir, cases, {c["id"]: case_files(skill_dir, c) for c in cases}, setup=o["with_setup"],
                                  gate=gate, warnings=found, platform=platform, web_cases_ok=o["allow_web_cases"])
        errors += [label + line for line in (platform_problems(platform) if platform else []) + errs
                   + (imported_case_problems(cases) if o.get("skill_dir") else [])]
        unchecked += [label + line for line in uncheck]
        warnings += [label + line for line in found]
        total += len(cases)
    for line in errors:
        print(f"PREFLIGHT {o['skill']} {line}", file=sys.stderr)
    for line in warnings:
        print(f"PREFLIGHT WARNING {o['skill']} {line} (a real run refuses it)", file=sys.stderr)
    platforms = [p for p in files if p]
    print(json.dumps({"skill": o["skill"], "cases": total, "errors": errors, "unchecked": unchecked,
                      **({"platforms": platforms} if platforms else {}), **({"warnings": warnings} if warnings else {})}, indent=2))
    return 2 if errors else 0


def main(argv):
    """Run, and leave nothing running: every process group started is ended on a signal and on any way out."""
    STOPPING.clear()

    def on_signal(signum, _frame):
        print(f"stopped by signal {signum}: ending every run that was started", file=sys.stderr)
        stop_all_groups()
        return_all_runs()  # the case folders go back to the workspace, the temporary folders are removed
        os._exit(128 + signum)  # worker threads would otherwise go on to the next run or grading

    previous = {}
    if threading.current_thread() is threading.main_thread():
        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            previous[sig] = signal.signal(sig, on_signal)
    try:
        return run(argv)
    finally:
        stop_all_groups(grace=2.0)
        return_all_runs()
        STOPPING.clear()
        for sig, handler in previous.items():
            signal.signal(sig, handler)


# --- control of a test event: the shared lock, the pause on the account limit, the ledger ----------------


def write_pause(path, state):
    tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f)
    os.replace(tmp, path)


def unpause(at):
    """--unpause: end every pause of the shared lock folder now, or set the time at which it ends."""
    until = None
    if at is not None:
        now = datetime.datetime.now()
        try:
            if re.fullmatch(r"\d{1,2}:\d{2}", at):
                hour, minute = (int(x) for x in at.split(":"))
                when = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                if when <= now:
                    when += datetime.timedelta(days=1)
            else:
                when = datetime.datetime.fromisoformat(at)
        except ValueError:
            die("--at takes a time of day, HH:MM, or a date and time, YYYY-MM-DDTHH:MM.")
        until = when.timestamp()
    found = sorted(glob.glob(os.path.join(lock_dir(), "pause-*.json")))
    for path in found:
        if until is None:
            try:
                os.remove(path)
            except OSError:
                pass
        else:
            write_pause(path, {**read_pause(path), "until": until})
    print(json.dumps({"pauses": [os.path.basename(p)[len("pause-"):-len(".json")] for p in found],
                      "until": clock(until) if until is not None else None}))
    return 0


def agg(rows, key):
    """{"mean", "stddev", "n"} of one value over the rows that have it, rounded to be shown. The standard
    deviation is the sample one: the runs are a sample of what the model does, not all of it."""
    vals = [r[key] for r in rows if r.get(key) is not None]
    return {"mean": round(statistics.mean(vals), 3), "stddev": round(statistics.stdev(vals), 3) if len(vals) > 1 else 0.0,
            "n": len(vals)} if vals else None


def exact_mean(rows):
    """The mean of the rows' scores, unrounded: what a condition compares."""
    vals = [r["pass_rate"] for r in rows if r.get("pass_rate") is not None]
    return statistics.mean(vals) if vals else None


def slot_suffix(slot):
    """The suffix of a slot's variant names and condition keys: none for the lead model's slot (m1), ".m2", ".m3" ...
    for the others. A variant is named <variant><suffix>: with_skill, with_skill.m2."""
    return "" if slot == LEAD_SLOT else "." + slot


def conditions_of(means, threshold, tolerance):
    """The conditions an event reports, from the unrounded mean of each variant ({name: mean or None}): a mean
    of 0.7996 is below a threshold of 0.8, though it is shown as 0.8. Rounded values are for display only.
    For the lead model (variants with no suffix), when its baseline ran: "delta", "delta_ok" (with the skill against
    without it, within the tolerance), "pass_rate" and "ok" (at the threshold); for every other model of the event
    (variants suffixed .m2, .m3 ...) that has a mean with the skill: "pass_rate.m2", "ok.m2" ...; and
    "ablation_delta" (".m2" ...) where an ablated variant ran. A key "ok", "delta_ok" or "ok.<slot>" is a condition
    of the exit code."""
    mean, measure = (lambda name: means.get(name)), load_measure()
    conditions = {}
    if mean("with_skill") is not None and mean("without_skill") is not None:
        conditions["delta"] = round(mean("with_skill") - mean("without_skill"), 3)
        conditions["delta_ok"] = measure.within_tolerance(mean("with_skill"), mean("without_skill"), tolerance)
        conditions["pass_rate"] = round(mean("with_skill"), 3)
        conditions["ok"] = measure.at_threshold(mean("with_skill"), threshold)
    suffixes = sorted({name[len("with_skill"):] for name in means if name.startswith("with_skill.")},
                      key=lambda x: int(x[2:]) if x[2:].isdigit() else 0)
    for suffix in suffixes:
        if mean("with_skill" + suffix) is not None:
            conditions["pass_rate" + suffix] = round(mean("with_skill" + suffix), 3)
            conditions["ok" + suffix] = measure.at_threshold(mean("with_skill" + suffix), threshold)
    for suffix in [""] + suffixes:
        if mean("with_skill" + suffix) is not None and mean("ablated_skill" + suffix) is not None:
            conditions["ablation_delta" + suffix] = round(mean("with_skill" + suffix) - mean("ablated_skill" + suffix), 3)
    return conditions


def condition_fails(conditions):
    """True when a condition of the exit code is not met: "ok", "delta_ok" or "ok.<slot>" is false."""
    return not all(v for k, v in conditions.items() if k in ("ok", "delta_ok") or k.startswith("ok."))


LEDGER_LOCK = threading.Lock()
# The kinds of failure of a run that the cap of resumptions turns into a line with outcome "timeout" and
# score 0: the run itself did not complete. Not a contaminated baseline (never a score: the way in is closed
# first), not a failed grading (the run completed; its grading is made again) and not a case folder that
# carries harness settings (a defect of the case).
CAPPED_KINDS = ("timeout", "refused", "adapter", "early_end")


LEAD_SLOT = "m1"  # the first model of an event: the lead; the others are m2, m3 ... in the order given


def job_key(case_id, variant, slot, k):
    return f"{case_id}|{variant}|{slot}|{k}"


def ledger_add(it_dir, entry):
    """One line per run of a pass, written when the run ends: what the event has done so far survives a stop."""
    with LEDGER_LOCK:
        with open(os.path.join(it_dir, "ledger.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")


def ledger_read(it_dir):
    """{job key: [its entries, oldest first]} of an event's ledger; a torn last line is left out."""
    found = {}
    try:
        with open(os.path.join(it_dir, "ledger.jsonl"), encoding="utf-8") as f:
            for line in f:
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                found.setdefault(job_key(entry["case"], entry["variant"], entry["slot"], entry["run"]), []).append(entry)
    except OSError:
        pass
    return found


def write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def operator_folder(value, flag):
    """The absolute folder a path given to --resume, --close or --regrade names. A relative path is read against
    one base, the current working directory, as any command line reads it, and never against another. The
    folder must be inside this checkout's workspace, <ROOT>/evals-workspace: an event or a run folder of another
    checkout is refused, so that a regrade or a resumption never reads, or writes into, another checkout's round."""
    path = os.path.abspath(value)
    workspace = os.path.realpath(os.path.join(ROOT, "evals-workspace"))
    if os.path.commonpath([os.path.realpath(path), workspace]) != workspace:
        die(f"{flag} {value!r} is {path} (a relative path is read against the current folder, {os.getcwd()}), which is "
            f"not inside this checkout's workspace, {workspace}: a folder of another checkout is never read. Give a "
            f"folder of this checkout, for example from {ROOT}: python3 evals/eval_run.py {flag} "
            "evals-workspace/<skill>/iteration-<n>")
    return path


def find_event(value, flag="--resume"):
    """The folder of the event --resume or --close names: a path to evals-workspace/<skill>/iteration-<n> of this
    checkout (operator_folder), which holds event.json."""
    folder = operator_folder(value, flag)
    if not os.path.isfile(os.path.join(folder, "event.json")):
        die(f"{flag} {value!r}: no event in {folder} (a folder evals-workspace/<skill>/iteration-<n> that holds event.json).")
    print(f"{flag} acts on {folder}", file=sys.stderr)
    return folder


def meter_of(out_dir):
    """What the run's key proxy counted, from <out>/meter.json (execution.write_meter() left it there after the run):
    {"input", "output", "cache_read", "cache_write", "total", "responses", "unknown_responses", "budget_reached",
    "in_flight"}, with "unknown_responses" raised by one when the file is unfinished (meter_unfinished), or
    None when the run had no key proxy or it left no count. The report carries it beside the adapter's own tokens;
    a run cannot change it, because the folder the key proxy writes it in is never mounted into the run."""
    meter = load_executor().read_meter(os.path.join(out_dir, "meter.json"))
    if not meter:
        return None
    found = {key: meter[key] for key in ("input", "output", "cache_read", "cache_write", "total", "responses",
                                         "unknown_responses", "budget_reached", "in_flight") if key in meter}
    if meter_unfinished(meter):  # the count is a lower bound: flagged exactly as an answer it could not read is
        found["unknown_responses"] = found.get("unknown_responses", 0) + 1
    return found


def meter_unfinished(meter):
    """True when a meter file is not the whole count: its final state still has a request under way (the run ended, and
    the proxy was stopped, before that answer was counted or recorded), or the proxy says it could not write the file.
    Such a count is a lower bound, whatever else it says."""
    in_flight = meter.get("in_flight")
    return (isinstance(in_flight, int) and not isinstance(in_flight, bool) and in_flight > 0) or meter.get("failed") is True


USAGE_KINDS = ("input", "output", "cache_read", "cache_write")  # the four kinds of tokens a run line's "usage" holds
# The reference adapter keeps the CLI's result event as outputs/raw.json: its `modelUsage` object holds, for each model
# the run used, the tokens of every kind, and it counts the subagents a run starts (its `usage` object and the total of
# timing.json do not). An adapter that keeps only its event stream, outputs/stream.jsonl, has one `step_finish` event per step.
MODEL_USAGE_NAMES = {"input": "inputTokens", "output": "outputTokens", "cache_read": "cacheReadInputTokens",
                     "cache_write": "cacheCreationInputTokens"}
RAW_JSON_LIMIT, STREAM_LIMIT = 8 * 1024 * 1024, 256 * 1024 * 1024  # a larger file is not what it should be


def _whole(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _small_text(path, limit):
    """The text of a regular file that is no link and no larger than limit; None otherwise."""
    try:
        if os.path.islink(path) or not os.path.isfile(path) or os.path.getsize(path) > limit:
            return None
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def usage_from_model_usage(text):
    """{"input", "output", "cache_read", "cache_write"} summed over the `modelUsage` of a result event (the text of
    outputs/raw.json; a list of events is read at its `result` event), or None: no `modelUsage`, a count that is not a
    whole number, or a missing input or output count. A cache count it leaves out is 0. Never a guess."""
    try:
        data = json.loads(text)
    except ValueError:
        return None
    if isinstance(data, list):
        data = next((e for e in reversed(data) if isinstance(e, dict) and e.get("type") == "result"), None)
    models = data.get("modelUsage") if isinstance(data, dict) else None
    if not isinstance(models, dict) or not models:
        return None
    total = {kind: 0 for kind in USAGE_KINDS}
    for entry in models.values():
        if not isinstance(entry, dict):
            return None
        for kind in USAGE_KINDS:
            value = entry.get(MODEL_USAGE_NAMES[kind], 0 if kind.startswith("cache") else None)
            if not _whole(value):
                return None
            total[kind] += value
    return total


def usage_from_stream(text):
    """The same four counts summed over the `step_finish` events of a stream-only adapter's stream, or None: no such event,
    a count that is not a whole number, or reasoning tokens (they have no kind of their own, and leaving them out would
    understate the run)."""
    total, seen = {kind: 0 for kind in USAGE_KINDS}, False
    for line in text.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict) or event.get("type") != "step_finish":
            continue
        part = event.get("part")
        tokens = part.get("tokens") if isinstance(part, dict) else None
        if not isinstance(tokens, dict) or tokens.get("reasoning") not in (None, 0):
            return None
        cache = tokens.get("cache") if isinstance(tokens.get("cache"), dict) else {}
        found = {"input": tokens.get("input"), "output": tokens.get("output"), "cache_read": cache.get("read", 0),
                 "cache_write": cache.get("write", 0)}
        if not all(_whole(v) for v in found.values()):
            return None
        for kind, value in found.items():
            total[kind] += value
        seen = True
    return total if seen else None


def key_held(model, pass_names, web):
    """True when the run's key was held by a key proxy: in the container, a command passed the variable a route holds,
    with a value in the caller's environment, to a model whose entry names that route (executor.held_route). Then only
    the proxy's meter counts the run's tokens. Outside the container, or for a model that holds no key, False."""
    if EXECUTOR != "container":
        return False
    executor = load_executor()
    try:
        return executor.held_route(pass_names, os.environ, "open" if web else "proxy", model) is not None
    except executor.ExecutorError:
        return False


def run_usage(meter, out_dir, held=False):
    """The tokens one run used by kind, for its evidence line's "usage", or None when they cannot be read whole.

    Where the run went through a key proxy, the proxy's count (`meter`, from meter_of) is the count, since the run could
    not change it; a count that names answers the proxy could not read ("unknown_responses") is a lower bound, which a
    line cannot say, so it has no usage, and the run's own report is not read in its place. A run with no key proxy has
    its own raw output read: the `modelUsage` of outputs/raw.json (the reference adapter), or else the `step_finish`
    tokens of outputs/stream.jsonl (a stream-only adapter), as runtime/costs.py reads them. Never the total of timing.json,
    which leaves the subagents out, and never the cost the adapter reported. Only the run's last attempt is counted.

    held says the run's key was held by a key proxy (key_held). Its meter is then the only count there is: a run whose
    meter is missing or unreadable has no usage, and its own report, which the run could have written, is not read."""
    if meter is None and held:
        return None
    if meter is not None:
        if meter.get("unknown_responses") or not all(_whole(meter.get(kind)) for kind in USAGE_KINDS):
            return None
        return {kind: meter[kind] for kind in USAGE_KINDS}
    raw = os.path.join(out_dir, "raw.json")
    if os.path.lexists(raw):  # a raw.json that cannot be read is unknown; the stream is not asked in its place
        text = _small_text(raw, RAW_JSON_LIMIT)
        return usage_from_model_usage(text) if text is not None else None
    stream = _small_text(os.path.join(out_dir, "stream.jsonl"), STREAM_LIMIT)
    return usage_from_stream(stream) if stream is not None else None


def upstream_of(models, model_ids, passed):
    """{model id: what served it} for each model of the event that ran through a key proxy: the provider its entry of
    the gate file pins, or, with no pin, the upstream host of its route. models is [(slot, model)], model_ids the
    ids the evidence names them by, passed {slot: the variables its runs are passed}. A model with no object entry or
    no route, and one whose route key was not passed or not in the caller's environment (so that no key proxy was
    started for it), is left out. None when no model ran through one."""
    executor, out = load_executor(), {}
    for slot, model in models:
        entry = executor.model_entry(model)
        if not entry or not entry.get("route"):
            continue
        r = executor.route(name=entry["route"])
        if r["secret"] in passed.get(slot, ()) and os.environ.get(r["secret"]):
            out[model_ids[slot]] = entry.get("provider_pin") or urllib.parse.urlsplit(r["upstream"]).hostname
    return out or None


def scratch_reason(o, gate, environment, version=None, fingerprint=None):
    """Why this event writes its files into the scratch tree of its run folder and never into the skill's
    folder, or None when it may write evidence. Evidence comes only from an event that used the configured
    values and real runners: every other event is a trial of the harness, of a case or of a change."""
    refusal = load_status().evidence_refusal(ROOT)
    if o["scratch"]:
        return "--scratch"
    if EXECUTOR != "container":
        return "the runs did not execute in the eval container: a stand-in runner writes no evidence"
    if refusal:
        return refusal
    if environment and environment.get("image_platform") not in load_executor().IMAGE_PLATFORMS:
        return (f"the image was built for {environment.get('image_platform')}, and evidence is made on "
                f"{' or '.join(load_executor().IMAGE_PLATFORMS)} only")
    host = (environment or {}).get("host_platform")
    if host and host != environment.get("image_platform"):
        return (f"the image is for {environment.get('image_platform')} and the docker host is {host}: the runs were emulated, "
                "and a run on an emulated platform is not a run on the platform it says")
    if o["extra_pass_env"]:
        return (f"extra variables were passed into the runs ({', '.join(o['extra_pass_env'])}): they change what a "
                "run is, so the event is a trial")
    chosen = [flag for flag, on in (("--only", o["only"]), ("--ablate", o["ablate"]),
                                    ("--no-grade", not o["grade"])) if on]
    if chosen:
        return f"the event ran chosen variants ({', '.join(chosen)}): evidence comes from a full, a partial or a quick test"
    if version is None:
        return "the skill has no metadata.version of the form X.Y.Z: an evidence line names the version that ran"
    if gate:
        control = load_status().event_config(gate)
        for key, name in (("runs", "runs"), ("timeout", "timeout_seconds"), ("retries", "retries")):
            configured, where = control[name], f"evals/eval-gate.json, {name}"
            if key == "runs" and o.get("quick"):  # a quick test runs each case once whatever the gate file configures
                configured, where = 1, "a quick test runs each case once"
            if key == "timeout" and (o.get("local") or {}).get("timeout_seconds"):  # a local model declares its own limit
                configured, where = o["local"]["timeout_seconds"], f"the local models file, timeout_seconds of {o['local']['name']}"
            if o[key] != configured:
                return (f"the event ran with {key} {o[key]}, and the configured value is {configured} "
                        f"({where}): evidence is written only at the configured values")
        # A named model is no trial: whichever model the event runs, its evidence has a home (evidence_home). What stays
        # configured is the grader, because the grading is part of what a score measures.
        if o["grader"] != gate.get("grader"):
            return (f"the grader of the event is {o['grader']}, and the configured one is {gate.get('grader')}: evidence is "
                    "made with the configured grader")
        if fingerprint != gate.get("measurement_sha256"):
            return ("the measurement fingerprint of this checkout differs from the committed one (evals/eval-gate.json, "
                    "measurement_sha256): a file that decides what a run measures changed, so nothing is written as evidence")
    return None


def unbumped_warning(status, skill_dir, name, content_hash, imported=False):
    """The warning a full or a quick test prints when the skill's content hash is not the last line of its version file (an
    edit that was not bumped), or None. It is a warning and not a refusal: the test is a fair trial of the edit. What it
    costs is said: status.gate_of sets aside the with-skill lines whose version and content hash the version file does not
    name (since the pooled gate of package P11), so the lines of this test carry no weight in the gate, and a second lab
    model would get no stored gate. A skill with no version file, or with a last line that is not of the form, is left to
    the validator."""
    lines, _, _ = status.read_versions(skill_dir)
    last = lines[-1] if lines else None
    if not isinstance(last, dict) or last.get("content_sha256") in (None, content_hash):
        return None
    fix = (f"python3 scripts/skill_import.py bump --name {name} (the version file of a skill from outside is written by that tool)"
           if imported else f"python3 evals/eval_status.py bump --skill {name}")
    return (f"WARNING unbumped edit: the content of {name} (sha256 {content_hash[:12]}) is not the last line of its version file "
            f"(version {last.get('version')}, sha256 {str(last.get('content_sha256'))[:12]}). The test runs anyway (this is a warning, "
            "not a refusal), but the gate sets aside the lines whose version and content hash the version file does not name, so "
            "this test's lines carry no weight in the gate and a second lab model would get no stored gate. Fix: " + fix
            + ", then test again.")


def model_cfg(gate, model):
    """The gate configuration read for `model` (the internal key "subject_model"), also for a model the gate file does
    not list: it is then added to the list, under its own id, so that the evidence it leaves and the gate read back from
    it agree on the id (status.model_id writes "unknown" for a model the list lacks). A name that is not a well-formed
    model id stays unlisted. Without a gate file there is no list, and the name stands as it is."""
    status = load_status()
    cfg = {**gate, "subject_model": model}
    if gate and status.MODEL_RE.fullmatch(model or "") and status.model_id(gate, model) == "unknown":
        cfg["models"] = {**status.known_models(gate), model: []}
    return cfg


def evidence_home(o, gate, models, harness_for):
    """("repository", None) when this event's evidence may enter the skill's folder, ("local", why not) when it is a
    person's own and stays outside the checkout (D18: the local evidence folder, status.local_evidence_base).

    The repository holds evidence of the gate file's "lab_models" only, each run through the adapter its entry
    names: a run of any other model, or of a listed model through another adapter, is a measurement of another pair,
    and it cannot enter the repository. A tree with no gate file configures nothing, and its evidence is the
    repository's. models is [(slot, model)] and harness_for {slot: adapter}.

    The evidence of a skill from outside (--skill-dir) is always local, whatever the models: it is measured against the
    person's own cases and belongs to nobody else (imported/<name>/ under the local evidence folder)."""
    if o.get("skill_dir"):
        return "local", "a skill from outside: its tests are the person's own, measured against their own cases"
    if not gate:
        return "repository", None
    status = load_status()
    lab = set(gate.get("lab_models") or [])
    for slot, model in models:
        listed = status.model_id(gate, model)
        if listed == "unknown" or listed not in lab:
            return "local", f"{model} is not one of the gate file's lab models ({', '.join(sorted(m for m in lab if m))})"
        configured = (status.model_entry(gate, model) or {}).get("adapter")
        if harness_for[slot] != configured:
            return "local", f"{model} ran through the adapter {harness_for[slot]}, and its configured one is {configured}"
    return "repository", None


def later_test_id(status, skill_dir, local=()):
    """A new test id that sorts after every test id the skill's evidence holds (and the person's local files in
    `local`): ids sort by the second an event started, and "the newest full test" is read from that order, so a second
    event never takes the second of an earlier one (two events of one skill a second apart happen only with stand-in
    runners)."""
    newest = max((os.path.basename(p)[4:20] for p in list(status.evidence_files(skill_dir)) + list(local)), default="")
    for _ in range(25):  # an id dated more than a few seconds ahead (a clock set wrong) is not waited for
        test = status.new_test_id()
        if test[:16] > newest:
            return test
        time.sleep(0.2)
    return test


TOOLS_SCRIPT = """
for tool in claude opencode node python3 git gh uv chromium; do
  printf '%s\t%s\n' "$tool" "$("$tool" --version 2>/dev/null | head -n 1)"
done
"""


def tool_versions():
    """{tool: its version line} of the tools in the image a run uses, read once per event in a container with
    no network; {} outside the container. A tool that does not answer is left out."""
    if EXECUTOR != "container":
        return {}
    root = tempfile.mkdtemp(prefix="eval-tools-", dir=temp_base())
    try:
        # security-scan: allow shell-string -- TOOLS_SCRIPT is a literal of this file; it runs in a container with no network
        r = run_group(["bash", "-c", TOOLS_SCRIPT], 120, cwd=root, env=contained_env(root), box={"root": root, "network": "none"})
    except subprocess.TimeoutExpired:
        return {}
    finally:
        shutil.rmtree(root, ignore_errors=True)
    found = {}
    for line in (r.stdout or "").splitlines():
        name, _, version = line.partition("\t")
        version = re.sub(r"[^A-Za-z0-9 ._()/+:,-]", "?", version.strip())[:80]
        if name and version:
            found[name] = version
    return found


def evidence_file(it_dir, skill, test):
    """Where an event's evidence file lives while the event runs, and for good when the event is a trial."""
    return os.path.join(it_dir, "scratch", "skills", skill, "evals", "evidence", f"lab-{test}.jsonl")


def write_evidence(path, event_line, run_lines):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for line in [event_line] + run_lines:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def run(argv):
    o = parse(argv)
    if o["check_cases"]:
        return check_cases_only(o)
    if o["regrade"] is not None:
        return regrade(o)
    if o["unpause"]:
        return unpause(o["at"])
    if o["routing"]:
        return routing(o)
    resumed, it_dir, closing = None, None, o["close"] is not None
    if o["resume"] is not None or closing:
        it_dir = find_event(o["close"] if closing else o["resume"], "--close" if closing else "--resume")
        with open(os.path.join(it_dir, "event.json"), encoding="utf-8") as f:
            resumed = json.load(f)
        if resumed.get("written"):
            die(f"the event {os.path.relpath(it_dir, ROOT)} wrote its evidence ({resumed['written']}), which "
                "is never edited: start a new event.", 2)
        if closing and resumed.get("state") != "open":
            die(f"the event {os.path.relpath(it_dir, ROOT)} is {resumed.get('state')}, not open: there is nothing to close.", 2)
        o = {**resumed["options"], "jobs": o["jobs"], "resume": o["resume"], "close": o["close"], "dry": False}
        if o.get("local") and not closing:  # the weights are hashed again: a file that changed is not the model the event began with
            saved, lm = o["local"], local_models()
            keys = ("weights", "context", "memory_gb", "accelerator", "cpus", "parallel", "timeout_seconds", "load_timeout_seconds")
            try:
                again = resolve_local(saved["name"], saved["id"].split("@", 1)[1],
                                      {saved["name"]: lm.check_entry(saved["name"], {k: saved[k] for k in keys if saved.get(k) is not None})})
            except lm.LocalModelError as e:
                die(f"the event {os.path.relpath(it_dir, ROOT)} cannot be resumed: {e}", 2)
            o["local"] = {**again, "cpus": saved.get("cpus") or again.get("cpus")}
            cap_local_jobs(o)
    status = load_status()
    gate = status.load_gate(ROOT)
    control = status.event_config(gate)
    skill_dir = skill_folder(o)
    evals = load_evals(o["skill"], o.get("platform"), o.get("skill_dir"))
    cases = evals.get("evals") or []
    if o["cases"]:
        cases = [c for c in cases if str(c.get("id")) in o["cases"]]
    if not cases:
        die("no matching eval cases.")
    with_variants = ["with_skill"] + (["ablated_skill"] if o["ablate"] else [])
    if o["only"]:
        with_variants = [] if o["only"] == "without" else [f"{o['only']}_skill"]
    # The models of the event, in the order given, each in a slot: m1 is the lead (the event is full by it, its
    # baseline runs by default), then m2, m3 ... The slot names the folders and the variants of its runs.
    models = [(f"m{i}", m) for i, m in enumerate(o["models"], 1)]
    model_of = dict(models)
    harness_for = {slot: o["adapters"][model] for slot, model in models}
    refuse_allow_commands(evals, cases)
    web = {c["id"]: allow_web(evals, c) for c in cases}
    local = o.get("local")
    if local and any(web.values()):  # a web run needs a second, open network: a local model's run reaches its server and nothing else
        webbed = [str(c["id"]) for c in cases if web[c["id"]]]
        die(f"case(s) {', '.join(webbed)} of {o['skill']} set \"allow_web\": a local model's run has no web (its network reaches "
            "its model server and nothing else; web cases of a local model are a later package). Run the others with "
            f"--cases <ids> (a partial test).", 2)
    # Only the cases the gate file lists run on the open network: nothing else opens it, whatever a case says.
    unlisted = [str(c["id"]) for c in cases if web[c["id"]] and not status.web_case_allowed(gate, o["skill"], c["id"])]
    if o.get("skill_dir"):  # a skill from outside is in no list: its web cases are for the flag and the audit (imported_event_problems)
        unlisted = []
    imported_plan = None
    if o.get("skill_dir"):
        if imported_case_problems(cases):
            die("; ".join(imported_case_problems(cases)), 2)
        imported_plan = imported_event_problems(o, [str(c["id"]) for c in cases if web[c["id"]]])
        if imported_plan and not o["dry"] and not closing:  # a plan (--dry-run) lists the problems; an event does not start
            die("a skill from outside is not tested yet: " + "; ".join(imported_plan), 2)
    if unlisted:
        die(f"case(s) {', '.join(unlisted)} of {o['skill']} set \"allow_web\" and are not in \"web_cases\" of "
            "evals/eval-gate.json: the network is opened for the cases listed there and for no other.", 2)
    # On a web case a model whose entry names "web_pass_env" (a low-limit API key) runs with those variables in place
    # of its "pass_env". Without that key a web case gets the model's own variables like any other run: its key proxy
    # holds the value outside the run. The grader's variables are the grader's own entry's, whatever the event runs.
    names = list(dict.fromkeys(
        o["pass_env"] + [n for _, m in models for n in o["pass_envs"][m]]
        + [n for _, m in models if any(web.values()) for n in o["web_pass_envs"].get(m, [])] + o["grader_pass_env"]))
    for filled in ([] if o["dry"] else resolve_pass_env(names)):
        print(f"--pass-env {filled}", file=sys.stderr)
    unset = [n for n in names if not os.environ.get(n)]
    if unset and not o["dry"]:
        # A missing provider key makes some runners fail with an opaque error (opencode: "UnknownError")
        # on every run; stop before spending a whole iteration on it.
        die(f"{', '.join(unset)} is not set and was not found in the secret store. Export it, or run this "
            "script with the store's library available: uv run --with keyring==25.7.0 python3 "
            "evals/eval_run.py ...", 2)
    runner_for = {}
    for adapter in dict.fromkeys(list(harness_for.values()) + [o["grader_harness"]]):
        runner_for[adapter] = os.path.join(ROOT, "adapters", adapter, "run-prompt.sh")
        if not os.path.isfile(runner_for[adapter]):
            die(f"adapter {adapter!r} has no run-prompt.sh (see AGENTS.md, Adding an adapter).")
    grader_runner = runner_for[o["grader_harness"]]
    runner_for = {slot: runner_for[adapter] for slot, adapter in harness_for.items()}
    # Where this event's evidence lives when it is written: the repository's (the gate file's lab models, through
    # their configured adapters) or this person's own folder outside the checkout (evidence_home).
    home, home_reason = evidence_home(o, gate, models, harness_for)
    local_base = status.local_evidence_base() if home == "local" else None
    # The folder under the local evidence base that holds this skill's files: its name, or imported/<name> for a skill from outside.
    kept_as = status.imported_evidence_name(o["skill"]) if o.get("skill_dir") else o["skill"]
    if local_base and not o["dry"] and (problem := status.local_base_problem(local_base, ROOT, kept_as)):
        die(problem, 2)
    local_events = status.local_skill_evidence(kept_as, local_base) if local_base else None
    # Where each model's harness discovers skills, which names carry its settings and how it words an exhausted
    # account: the adapter's own data. A plan (--dry-run) runs nothing and stages nothing, so it needs none of it.
    eval_for = {} if o["dry"] else {slot: adapter_eval(harness_for[slot]) for slot, _ in models}
    grader_eval = {} if o["dry"] else adapter_eval(o["grader_harness"])
    settings = set() if o["dry"] else harness_settings()
    sources = {c["id"]: case_files(skill_dir, c) for c in cases}
    # Before anything is spent or written: a case that cites a file it does not ship measures nothing.
    problems, unchecked = (preflight(skill_dir, cases, sources, setup=not o["dry"], gate=gate, platform=o.get("platform"),
                                     web_cases_ok=bool(o.get("skill_dir") and o.get("allow_web_cases")))
                           if resumed is None else ([], []))
    if o.get("platform") and resumed is None:
        problems = platform_problems(o["platform"]) + problems
    for line in problems:
        print(f"PREFLIGHT {o['skill']} {line}", file=sys.stderr)
    if problems and not o["dry"]:
        die(f"{len(problems)} preflight error(s) in the cases (listed above); nothing was run.", 2)
    deps = {c["id"]: dependency_dirs(c) for c in cases}
    start_hash = status.content_hash(skill_dir)
    if resumed is not None and resumed["content_sha256"] != start_hash:
        die(f"the skill folder changed since the event {os.path.relpath(it_dir, ROOT)} started: an event runs on one "
            "content of the skill. Start a new event.", 2)
    environment = None
    if EXECUTOR == "container" and not o["dry"]:
        try:  # the images, the internal network and the proxy: built and started once, before any run
            environment = load_executor().ensure()
        except Exception as e:
            die(f"the eval container is not available: {e}", 1)
    local_line = None
    if local and EXECUTOR == "container" and not o["dry"]:
        try:  # the model server image is present (a test never pulls); what served the model is described once per event
            if not local.get("cpus"):
                local = o["local"] = {**local, "cpus": load_executor().host_cpus()}
            saved = (resumed or {}).get("local_model")
            # Described again on a resumption (the full hash of the weights, the pinned image and the arguments): runs of two
            # servers or two files are not one measurement, and the event line states one.
            local_line = saved if (closing and saved) else describe_local(local)
        except Exception as e:
            die(f"the local model's server is not available: {e}", 1)
        if saved and local_line != saved:
            die(f"the event {os.path.relpath(it_dir, ROOT)} cannot be resumed: the weights, the model server image or its arguments are "
                f"not those it began with (its local_model {json.dumps(saved, sort_keys=True)}, now {json.dumps(local_line, sort_keys=True)}). "
                "Start a new event.", 2)
    local_box = ({k: local[k] for k in ("alias", "weights", "stat", "context", "memory_gb", "accelerator", "cpus", "load_timeout_seconds")}
                 if local and not o["dry"] else None)  # a plan (--dry-run) hashed no file and has none of this
    if resumed is None:
        it_dir = next_iteration(os.path.join(ROOT, "evals-workspace", o["skill"]), claim=not o["dry"])
    ablated_dir, ablated_lines = None, 0
    if "ablated_skill" in with_variants:
        ablated_lines = ablated_line_count(skill_dir, o["ablate"])
        if not o["dry"]:
            ablated_dir, _ = ablated_copy(skill_dir, o["ablate"], os.path.join(it_dir, "ablated-skill"))
    # A full test runs each baseline "baseline_runs" times (the gate file); --baseline asks for the configured runs.
    baseline_count = o["runs"] if o["baseline"] else min(o["runs"], control["baseline_runs"])
    # The baselines in force, from the skill's committed evidence: {case id: lines}. A case with that many of them
    # is not run without the skill again in a full test; the event line says it was reused.
    gate_cfg = {**model_cfg(gate, o["model"]), "threshold": o["threshold"], "tolerance": o["tolerance"]}
    in_force = {cid: len(lines) for cid, lines in status.baseline_lines(skill_dir, gate_cfg, local_events).items()}
    slot_names = [slot for slot, _ in models]
    baseline_on = [slot for slot, m in models if m in o["baseline_on"]]

    def baseline_slots(case):
        """Where the case runs without the skill in this event: on the lead model when its baseline is not in
        force in a full test, or when --baseline asks; on another model only with --baseline-on (and --only
        without, a trial, runs it on every model of the event). A platform's cases and a quick test's run with the skill only."""
        if o.get("platform") or o.get("quick"):
            return []
        if o["only"]:
            return slot_names if o["only"] == "without" else []
        wanted = o["baseline"] or (not o["cases"] and in_force.get(str(case["id"]), 0) < baseline_count)
        return [t for t in slot_names if (t == LEAD_SLOT and wanted) or t in baseline_on]
    if resumed is not None and resumed.get("plan"):
        planned = {(str(cid), v, t) for cid, v, t in resumed["plan"]}  # a resumption runs the plan it started with
        baseline_slots = lambda case: [t for t in slot_names if (str(case["id"]), "without_skill", t) in planned]
    jobs = []
    for c in cases:
        jobs += [(c, v, t, m, k) for v in with_variants for t, m in models for k in range(1, o["runs"] + 1)]
        jobs += [(c, "without_skill", t, m, k) for t, m in models if t in baseline_slots(c) for k in range(1, baseline_count + 1)]
    if o["dry"]:
        plan = [{"case": c["id"], "variant": v, "slot": t, "model": m, "run": k, "allow_web": web[c["id"]]}
                for c, v, t, m, k in jobs]
        print(json.dumps({"dry_run": True, "iteration_dir": os.path.relpath(it_dir, ROOT),
                          "models": [m for _, m in models],
                          "runners": {m: os.path.relpath(runner_for[slot], ROOT) for slot, m in models},
                          "grader": o["grader"], "grader_runner": os.path.relpath(grader_runner, ROOT),
                          "grader_pass_env": o["grader_pass_env"], "pass_env": o["pass_env"],
                          "model_pass_env": {m: o["pass_envs"][m] for _, m in models},
                          "evidence_home": {"home": home, "why": home_reason, "folder": local_base},
                          **({"imported": {"folder": o["skill_dir"], "kept_as": kept_as, "refused": imported_plan}}
                             if o.get("skill_dir") else {}),
                          "cases": [{"case": c["id"], "files": c.get("files") or [], "skills": c.get("skills") or [],
                                     "setup": c.get("setup") or []} for c in cases],
                          "ablate": {"text": o["ablate"], "lines_removed": ablated_lines} if o["ablate"] else None,
                          "timeout": o["timeout"], "retries": o["retries"], "max_cost_usd": o["max_cost"],
                          "control": {**control, "web_cases": [c["id"] for c in cases if web[c["id"]]]},
                          "preflight": {"errors": problems, "unchecked": unchecked}, "runs": plan}, indent=2))
        return 2 if problems else 0
    version = status.skill_version(skill_dir)
    fingerprint = status.measurement_fingerprint(ROOT)  # computed when the event starts, written into every line
    scratch = scratch_reason(o, gate, environment, version, fingerprint)
    all_cases = evals.get("evals") or []
    hashes = {str(c["id"]): status.case_hash(skill_dir, c, evals.get("allow_web") is True) for c in cases}
    # An event is a full test when it runs every current case with the skill on the lead model, graded:
    # `--skill <name>` without --cases. --cases makes a partial test, even of every case; so does --platform, whose
    # cases never enter the gate or the score. A quick test (--quick) is its own kind: every case once with the skill, no baseline.
    kind = ("quick" if o.get("quick") else
            "full" if not o["cases"] and not o.get("platform") and len(cases) == len(all_cases)
            and "with_skill" in with_variants and LEAD_SLOT in slot_names and o["grade"] else "partial")
    if resumed is None and kind in ("full", "quick"):  # a warning, never a refusal: the test runs, and says what it will not count for
        unbumped = unbumped_warning(status, skill_dir, o["skill"], start_hash, imported=bool(o.get("skill_dir")))
        if unbumped:
            print(unbumped, file=sys.stderr)
    if resumed is None and not scratch:
        # No new event of a skill while one of its events that may write evidence is open.
        for other in sorted(glob.glob(os.path.join(ROOT, "evals-workspace", o["skill"], "iteration-*", "event.json"))):
            try:
                with open(other, encoding="utf-8") as f:
                    state = json.load(f)
            except (OSError, ValueError):
                continue
            if state.get("state") == "open" and state.get("scratch") is None and "test" in state:
                folder = os.path.relpath(os.path.dirname(other), ROOT)
                shutil.rmtree(it_dir, ignore_errors=True)
                die(f"the event {folder} of {o['skill']} is open: resume it (--resume {folder}) or, to give it up, close it "
                    f"(--close {folder}), which writes its runs as an incomplete event. No new event of the skill starts while "
                    "one is open: a test that goes badly is not drawn again.", 2)
    if resumed is None:
        pass_no = 0
        event = {"skill": o["skill"], "test": later_test_id(status, skill_dir, status.local_evidence_files(kept_as, local_base) if local_base else ()),
                 "kind": kind,
                 "started": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
                 "content_sha256": start_hash, "version": version, "measurement_sha256": fingerprint, "cases": hashes,
                 "tools": tool_versions(), "state": "open", "passes": 1, "scratch": scratch,
                 **({"local_model": local_line} if local_line else {}),
                 "plan": sorted({(str(c["id"]), v, t) for c, v, t, _, _ in jobs}),
                 "options": dict(o)}
    else:
        pass_no = resumed.get("passes", 1)
        if resumed.get("cases") != hashes:
            die(f"an eval case changed since the event {os.path.relpath(it_dir, ROOT)} started: an event runs on one "
                "state of its cases. Start a new event.", 2)
        if resumed.get("measurement_sha256") != fingerprint:
            die(f"a file that decides what a run measures changed since the event {os.path.relpath(it_dir, ROOT)} started: "
                "its runs would not be one measurement. Start a new event.", 2)
        event = {**resumed, "state": "open", "passes": pass_no + (0 if closing else 1), "scratch": scratch}
    write_json(os.path.join(it_dir, "event.json"), event)
    test, kind = event["test"], event["kind"]

    def context_of(case, with_skill):
        """The hash of what a run of the case is given besides the skill under test: its dependency skills, and,
        with the skill, the shared references the skill cites and the references of the platforms the case names.
        One function computes it for the runner and for the score (eval_status.py, case_context)."""
        load_stage()  # the staging module is in this checkout, or the runner stops here
        context = status.case_context(ROOT, skill_dir, case, with_skill, o.get("platform"))
        if context is status.UNKNOWN_CONTEXT:
            die(f"case {case.get('id')}: a platform it names has no reference under shared/references/platforms/.", 2)
        return context
    contexts = {(c["id"], with_skill): context_of(c, with_skill) for c in cases for with_skill in (True, False)}
    today = lambda: datetime.datetime.now(datetime.timezone.utc).date().isoformat()

    def own_names(slot, case_id):
        """The variables that carry the model's own key: its entry's "web_pass_env" on a web case when it names
        one (a low-limit key, in place of the account's token), else its "pass_env"."""
        model = model_of[slot]
        return (o["web_pass_envs"].get(model) if web[case_id] and o["web_pass_envs"].get(model) else o["pass_envs"][model])

    def env_names(slot, case_id):
        """The variables one model run receives: the caller's, and its model's own."""
        return o["pass_env"] + own_names(slot, case_id)

    def key_names(slot, case_id):
        """The variables that carry the model's own key, which a refusal of the credential names; the caller's
        --pass-env variables when the model has none of its own."""
        return own_names(slot, case_id) or env_names(slot, case_id)

    # Set when a provider refused a run's credential: every later run would meet the same refusal, so no run of
    # the event starts after it, and the runs not started are left for --resume once the key is stored again.
    refused_key, refused_note = threading.Event(), []

    # The grader is a model of its own: its adapter, its runner, the markers of its account and the variables of its key
    # are those of its entry in the gate file, whichever models the event runs and in whatever order.
    grader_env = o["pass_env"] + o["grader_pass_env"]
    all_values = load_measure().redaction_values(names)  # of every model: a grading prompt carries none of them
    grader_account = {"key": o["grader_harness"], "markers": grader_eval["account_limit"],
                      "probe": lambda: probe_call(grader_runner, o["grader"], grader_env), "control": control,
                      "model": o["grader"]}

    def one_run(c, v, slot, model, k):
        """Prepare, run and grade one (case, variant, model, run). Returns its ledger entry:
        {"case", "variant", "slot", "run", "pass", "name", "row" or None, "failed" or None, "msgs", "count"}."""
        infra = lambda reason, kind, **more: {"case": c["id"], "variant": v, "slot": slot, "run": k, "reason": reason,
                                              "kind": kind, **more}
        name = v + slot_suffix(slot)
        run_dir = os.path.join(it_dir, f"eval-{c['id']}", name, *([f"run-{k}"] if o["runs"] > 1 else []))
        cwd, out = os.path.join(run_dir, "cwd"), os.path.join(run_dir, "outputs")
        variant_dir = {"with_skill": skill_dir, "ablated_skill": ablated_dir}.get(v)
        count = {"attempts": 0, "early_ends": 0, "timeouts": 0, "refusals": 0, "adapter_failures": 0, "pauses": 0,
                 "redactions": 0, "contaminated": None, "passage": None}
        msgs = []
        entry = lambda row, failed, extra=(): {"case": c["id"], "variant": v, "slot": slot, "run": k, "pass": pass_no,
                                               "name": name, "row": row, "failed": failed, "msgs": msgs + list(extra), "count": count}
        model_env = env_names(slot, c["id"])
        values = load_measure().redaction_values(model_env)
        account = {"key": harness_for[slot], "markers": eval_for[slot]["account_limit"],
                   "probe": lambda: probe_call(runner_for[slot], model, model_env)}

        # What the hooks of one attempt find out, read once the run's attempts are made; reset on every attempt.
        made = {"inputs": {}, "vcs": None, "case_text": ""}

        def before_attempt():
            if refused_key.is_set():  # refused before this run started, or while it waited for its place
                raise EventStopped()

        def build(case_dir, root):
            made.update(inputs={}, vcs=None, case_text="")
            build_tree(case_dir, sources[c["id"]], c)

        def after_base(case_dir, root):
            quiet = {"root": root, "network": "none"}  # setup and the fixture commit: no secret, no network
            run_setup(case_dir, c.get("setup") or [], contained_env(root), box=quiet)
            # The preflight refused a case that carries harness settings before any run; the attempt checks the
            # folder that runs again, after this.

        def stage(case_dir):
            staged, _ = stage_run(case_dir, eval_for[slot], variant_dir, deps[c["id"]], c, o.get("platform"))
            return staged

        def before_run(case_dir, root, staged):
            # The input files the assertions check facts against, as the run finds them: the grader is shown this,
            # even when the run changes them afterwards.
            made["inputs"] = {p: shown_in(case_dir, p) for p in c.get("grader_files") or [] if isinstance(p, str)}
            if v == "without_skill":  # what the case itself holds, as the run finds it: the dependency skills too
                made["case_text"] = c["prompt"] + "\n" + folder_text(case_dir)

        def after_run(case_dir, root, why, delta, staged):
            if delta is not None and o["grade"]:  # commits, branches and pushes: read here, where the case folder still is
                quiet = {"root": root, "network": "none"}
                made["vcs"], hits = load_measure().replace_values(version_control(case_dir, contained_env(root), box=quiet), values)
                count["redactions"] += hits

        def judge(info):
            if v != "without_skill":
                return None
            produced = (info["delta"]["created"] + info["delta"]["modified"]) if info["delta"] else []
            count["contaminated"] = contamination(out, cwd, produced)
            if count["contaminated"]:
                # The run looked at the harness or reached the workbench: it is no baseline. No score, and no retry
                # that would hide it: the iteration is incomplete until the way in is closed.
                return count["contaminated"]
            if not info["why"]:
                count["passage"] = shared_passage(skill_grams, read_text(os.path.join(out, "response.md"), 200000) + "\n"
                                                  + "\n".join(read_text(os.path.join(cwd, p), TEXT_LIMIT) for p in produced
                                                              if readable(cwd, p) and load_measure().binary_stub(os.path.join(cwd, p)) is None),
                                                  made["case_text"])
            return None

        # The run happens outside the repository; its folders come back to run_dir when it ends, however it ends.
        # The attempts (the wait on a pause, the place of the shared lock, the settings check, the adapter call, the
        # replacement of the passed values, the classification and the retries) are made by evals/run_attempts.py.
        # The credential of the model is in the run's environment, and a model that prints its environment puts it
        # in a file or in its reply: before anything is stored, read or sent to the grader, each passed value is
        # replaced by a marker, by exact value. What makes an attempt one to make again, with the skill and without
        # it alike: a timeout, a refusal by the provider, a failure of the adapter, an early end. Each is counted.
        # An attempt that meets the account limit is no result of the run: everything on the account waits, and
        # the run starts again from its beginning afterwards, never retried into the limit, never counted as a
        # timeout and never scored.
        spec = {"dest": run_dir, "names": [o["skill"]], "label": f"case {c['id']} {name} run {k}",
                "runner": runner_for[slot], "model": model, "account": account,
                "refusal_markers": eval_for[slot]["refusal_markers"], "pass_env": model_env, "values": values,
                "settings": settings, "control": control, "web": web[c["id"]], "timeout": o["timeout"],
                "max_cost": o["max_cost"], "retries": o["retries"], "prompt": c["prompt"], "response_limit": 200000,
                "counts": count, **({"local": local_box} if local_box else {})}
        hooks = types.SimpleNamespace(before_attempt=before_attempt, build=build, after_base=after_base, stage=stage,
                                      before_run=before_run, after_run=after_run, judge=judge)
        result = load_attempts().run(_RUNNER, spec, hooks)
        why, delta, failure = result["why"], result["delta"], result["failure"]
        inputs, vcs = made["inputs"], made["vcs"]
        for event in result["events"]:
            if event["kind"] == "refused":
                count["refused"] = event["detail"]
            if event["event"] == "paused":
                msgs.append(f"PAUSED      case {c['id']} {name} run {k}: the account limit was met; the run starts again after the pause")
            elif event["event"] == "early_end":
                msgs.append(f"EARLY END   case {c['id']} {name} run {k} attempt {event['attempt']} ({event['detail']}): retrying; "
                            f"kept in {os.path.relpath(event['kept'], ROOT)}")
            else:
                msgs.append(f"RETRY       case {c['id']} {name} run {k} attempt {event['attempt']} ({event['why']}): making the run again; "
                            f"kept in {os.path.relpath(event['kept'], ROOT)}")
        if result["status"] == "caller":
            return entry(None, infra("contaminated", "contaminated", evidence=count["contaminated"]),
                         [f"CONTAMINATED case {c['id']} {name} run {k}: {count['contaminated']}"])
        if failure and failure["kind"] == "settings":
            why = f"the case folder holds {failure['detail']}: a fixture or setup must not carry harness settings"
            return entry(None, infra(why, "settings"), [f"RUN FAILED  case {c['id']} {name} run {k} ({why})"])
        if failure and failure["kind"] == "stopped":  # the script is being stopped: what the run left stays where a reader expects it
            return entry(None, infra(why or "stopped before the run was read", "stopped"))
        if failure and failure["kind"] == "auth":
            detail = failure["detail"]
            # The provider refused the credential: never retried, and the event stops, since every later run
            # with it would meet the same refusal. The message names the variable, never its value.
            refused_key.set()
            reason = (f"the provider refused the key ({detail}) passed in "
                      f"{credential_label(harness_for[slot], key_names(slot, c['id']))}")
            note = (f"KEY REFUSED case {c['id']} {name} run {k}: {reason}. The event stops: every later run with that "
                    "key would meet the same refusal, so the run is not retried and no new run starts. Store a valid "
                    "key under that name, then run what is left with: python3 evals/eval_run.py --resume "
                    f"{os.path.relpath(it_dir, ROOT)}")
            if not refused_note:
                refused_note.append(note)
                print(note, file=sys.stderr)
            return entry(None, infra(reason, "auth", detail=detail, attempts=count["attempts"]), [
                f"RUN FAILED  case {c['id']} {name} run {k} ({reason}; not retried): see "
                f"{os.path.relpath(os.path.join(out, 'error.log'), ROOT)}"])
        if failure:
            kind, detail = failure["kind"], failure["detail"]
            if kind == "refused":
                count["refused"] = detail
            if kind == "early_end":
                return entry(None, infra("early_end", kind, detail=detail, attempts=count["attempts"]), [
                    f"RUN FAILED  case {c['id']} {name} run {k} (early_end on all {count['attempts']} attempt(s): {detail})"])
            reason = "refused: the provider declined the request" if kind == "refused" else why
            return entry(None, infra(reason, kind, attempts=count["attempts"], **({"detail": detail} if detail else {})), [
                f"RUN FAILED  case {c['id']} {name} run {k} ({reason}; {count['attempts']} attempt(s)): see "
                f"{os.path.relpath(os.path.join(out, 'error.log'), ROOT)}"])
        response = result["response"]
        timing = {}
        try:
            with open(os.path.join(out, "timing.json"), encoding="utf-8") as f:
                timing = json.load(f)
        except (OSError, ValueError):
            pass
        if not isinstance(timing, dict):
            timing = {}
        timing.update(run_ending(out))  # the stop reason and the turn count, kept beside the reply
        if v == "with_skill" and isinstance(timing.get("skills_loaded"), list):
            # Whether the model loaded the skill under test: reported, never scored. A run that did not still scores,
            # as the description's failure.
            timing["invoked"] = o["skill"] in timing["skills_loaded"]
            if isinstance(timing.get("skills_used"), list):
                # R12: whether any tool named the skill's folder (a script run, a reference read, a listing), which a
                # follow-up run can do without reading SKILL.md. Kept in the run's timing.json only: reported, never
                # scored, and on no evidence line.
                timing["used"] = o["skill"] in timing["skills_used"]
        with open(os.path.join(run_dir, "timing.json"), "w", encoding="utf-8") as f:
            json.dump(timing, f)
        g, failed = None, None
        if o["grade"]:
            # A with-skill run whose grading fails a guard assertion is graded once more (the model's section 4).
            g = grade(grader_runner, o["grader"], run_dir, c, response, delta, inputs, vcs, grader_env, o["timeout"], grader_account,
                      all_values, guards=v == "with_skill")
            count["grading_refused"] = g["refused"]
            count["pauses"] += g.get("pauses", 0)
            if "assertion_results" not in g:
                failed = infra(f"grading failed: the grader's answer was refused on all {g['refused']} attempt(s) ({g['reason']})", "grading")
                msgs.append(f"GRADE FAILED case {c['id']} {name} run {k}: {g['reason']}")
                g = None
            else:
                with open(os.path.join(run_dir, "grading.json"), "w", encoding="utf-8") as f:
                    json.dump(g, f, indent=2)
        row = {"case": c["id"], "run": k, "pass_rate": g["summary"]["pass_rate"] if g else None,
               "tokens": timing.get("total_tokens"), "duration_ms": timing.get("duration_ms"),
               "cost_usd": timing.get("cost_usd"), "run_sha256": run_record_hash(run_dir),
               **{key: timing[key] for key in ("stop_reason", "num_turns", "invoked") if key in timing},
               **({"meter": metered} if (metered := meter_of(out)) else {}),
               **({"redactions": count["redactions"]} if count["redactions"] else {})}
        if (used := run_usage(row.get("meter"), out, key_held(model, model_env, web[c["id"]]))) is not None:  # the tokens of the run by kind: its line carries them
            row["usage"] = used
        if g:  # one 0 or 1 per assertion, in the case's order: what a per-assertion count is made from
            row["results"] = [1 if r["passed"] else 0 for r in g["assertion_results"]]
            if g.get("guard_failed"):  # the guard failures the second grading confirmed; the score is the first's
                row["guard_failed"] = g["guard_failed"]
        row["date"] = today()  # the day of the run, UTC, from the clock
        return entry(row, failed)

    def run_and_log(job):
        try:
            result = one_run(*job)
        except EventStopped:  # not started: no ledger line, so the run is listed as not run and --resume runs it
            return {"msgs": []}
        ledger_add(it_dir, {**{key: value for key, value in result.items() if key != "msgs"}, "date": today()})
        return result

    # The skill's own text, as passages: what a without-skill run should not be able to quote.
    skill_grams = skill_passages(skill_dir) if any(job[1] == "without_skill" for job in jobs) else set()
    key_of = lambda job: job_key(job[0]["id"], job[1], job[2], job[4])
    ledger = ledger_read(it_dir)
    # A first pass runs everything. A resumption runs the failed runs only, and a run that never got a line
    # (the event was stopped before it ended); a run already resumed max_resumes times is not run again.
    resumes = lambda key: sum(1 for e in ledger.get(key, []) if e.get("pass", 0) > 0)

    def to_run(job):
        entries = ledger.get(key_of(job))
        if not entries:
            return True
        failed = entries[-1]["failed"]
        return bool(failed) and not (failed.get("kind") in CAPPED_KINDS and resumes(key_of(job)) >= control["max_resumes"])
    todo = [] if closing else [job for job in jobs if to_run(job)]  # closing runs nothing: it writes what was run
    with concurrent.futures.ThreadPoolExecutor(max_workers=o["jobs"]) as pool:
        done = [pool.submit(run_and_log, job) for job in todo]
        for fut in concurrent.futures.as_completed(done):
            for msg in fut.result()["msgs"]:
                print(msg, file=sys.stderr)
    if local and not scratch:  # the weights are looked at once more at the end: a change makes the event a trial
        try:
            local_models().assert_unchanged(local["weights"], local["stat"])
        except local_models().LocalModelError as e:
            scratch = f"{e}: the runs are not all of the model the event began with"
            print(f"WARNING {scratch}", file=sys.stderr)
    ledger = ledger_read(it_dir)
    early_counts = {t: {"attempts": 0, "early_ends": 0, "by_case": {}, "by_variant": {}} for t, _ in models}
    counts = {t: {} for t, _ in models}
    contaminated, refusals, grading_refused, shared, timeouts, redactions = [], [], 0, [], [], 0
    infra_failures, results = [], {}
    for job in jobs:  # the order of the plan, so benchmark.json does not depend on which run finished first
        entries = ledger.get(key_of(job), [])
        where = {"case": job[0]["id"], "variant": job[1], "slot": job[2], "model": model_of[job[2]], "run": job[4]}
        slot_count, variant_count = early_counts[job[2]], counts[job[2]].setdefault(job[1], {
            "attempts": 0, "retries": 0, "timeouts": 0, "refusals": 0, "adapter_failures": 0, "early_ends": 0, "pauses": 0, "resumes": 0})
        for e in entries:  # every pass counts: what a resumption retried is part of how the result was reached
            count = e["count"]
            grading_refused += count.get("grading_refused", 0)
            redactions += count.get("redactions", 0)
            slot_count["attempts"] += count["attempts"]
            slot_count["early_ends"] += count["early_ends"]
            slot_count["by_case"][job[0]["id"]] = slot_count["by_case"].get(job[0]["id"], 0) + count["early_ends"]
            slot_count["by_variant"][job[1]] = slot_count["by_variant"].get(job[1], 0) + count["early_ends"]
            variant_count["attempts"] += count["attempts"]
            if e is entries[-1] and isinstance((e["row"] or {}).get("invoked"), bool):
                variant_count["invoked"] = variant_count.get("invoked", 0) + int(e["row"]["invoked"])
                variant_count["reported"] = variant_count.get("reported", 0) + 1
            variant_count["retries"] += max(count["attempts"] - 1, 0)
            variant_count["resumes"] += 1 if e.get("pass", 0) > 0 else 0
            for key in ("timeouts", "refusals", "adapter_failures", "early_ends", "pauses"):
                variant_count[key] += count.get(key, 0)
            if count.get("refused"):
                refusals.append({**where, "evidence": count["refused"][:300]})
        if not entries:
            infra_failures.append({**where, "reason": "not run: the event stopped before this run ended", "kind": "not_run"})
            continue
        last = entries[-1]
        if last["count"].get("contaminated"):
            contaminated.append({**where, "evidence": last["count"]["contaminated"]})
        if last["count"].get("passage"):
            shared.append({**where, "passage": last["count"]["passage"]})
        failed, row = last["failed"], last["row"]
        if failed and failed.get("kind") in CAPPED_KINDS and resumes(key_of(job)) >= control["max_resumes"]:
            # Still incomplete after the cap of resumptions: a result at last, the same with the skill and without
            # it, so that dropping the run cannot raise a mean. It is the only way a run that did not complete scores.
            row = {"case": job[0]["id"], "run": job[4], "pass_rate": 0.0, "tokens": None, "duration_ms": None,
                   "outcome": "timeout", "results": [0] * len(job[0].get("assertions") or []), "reason": failed["reason"],
                   "date": last.get("date") or today()}
            timeouts.append({**where, "reason": failed["reason"], "resumes": resumes(key_of(job))})
            failed = None
        if failed:
            infra_failures.append(failed)
        if row is not None:
            results.setdefault(last["name"], []).append(row)

    summary = {name: {"pass_rate": agg(rows, "pass_rate"), "tokens": agg(rows, "tokens"), "duration_ms": agg(rows, "duration_ms"), "cases": rows}
               for name, rows in results.items()}
    conditions = conditions_of({name: exact_mean(rows) for name, rows in results.items()}, o["threshold"], o["tolerance"])
    bench = {"skill": o["skill"], "runs": o["runs"], "timeout": o["timeout"], "retries": o["retries"], "max_cost_usd": o["max_cost"], "extra_pass_env": o["extra_pass_env"], "adapters": {m: harness_for[t] for t, m in models}, "models": dict(models), "grader": o["grader"], "grader_adapter": o["grader_harness"], "threshold": o["threshold"],
             "tolerance": o["tolerance"], "measurement_version": o["measurement_version"],
             **({"environment": environment} if environment else {}),
             "ablate": {"text": o["ablate"], "lines_removed": ablated_lines} if o["ablate"] else None,
             "run_summary": summary, "conditions": conditions, "failures": len(infra_failures)}
    # A run counts as completed when it produced a response and, unless --no-grade, was graded.
    completed = sum(1 for rows in results.values() for r in rows if r["pass_rate"] is not None or not o["grade"])
    complete = o["grade"] and not infra_failures and completed == len(jobs)
    # The event is complete by the lead model: every run of it graded. A run missing on another model is
    # listed and makes the exit code 1, and leaves the evidence complete.
    graded = lambda job: any(r["case"] == job[0]["id"] and r["run"] == job[4] and r.get("pass_rate") is not None
                             for r in results.get(job[1] + slot_suffix(job[2]), []))
    complete_ref = bool(o["grade"]) and all(graded(job) for job in jobs if job[2] == LEAD_SLOT)
    # Complete is also read model by model: a model's gate is written only when every run of it in the event is graded.
    complete_by = {slot: bool(o["grade"]) and all(graded(job) for job in jobs if job[2] == slot) for slot, _ in models}
    iteration = int(os.path.basename(it_dir).split("-")[1])
    bench.update({"date": datetime.date.today().isoformat(), "iteration": iteration, "cases": [c["id"] for c in cases],
                  "content_sha256": start_hash, "expected_runs": len(jobs), "completed_runs": completed,
                  "complete": complete, "infra_failures": infra_failures, "passes": pass_no + 1})
    bench["contaminated"] = contaminated
    bench["shared_passages"] = shared
    bench["refusals"] = refusals
    bench["timeouts"] = timeouts
    bench["counts"] = {model_of[slot]: c for slot, c in counts.items()}
    bench["web_cases"] = [c["id"] for c in cases if web[c["id"]]]
    bench["control"] = {"runs": control["runs"], "timeout_seconds": control["timeout_seconds"], "retries": control["retries"],
                        "max_resumes": control["max_resumes"]}
    bench["grading"] = {"template_sha256": template_hash(), "refused": grading_refused}
    bench["redactions"] = redactions
    bench["early_ends"] = early_end_stats({model_of[slot]: c for slot, c in early_counts.items()})
    bench["early_end_warning"] = early_end_warning(bench["early_ends"], o["early_rate"])
    bench["scratch"] = scratch
    write_json(os.path.join(it_dir, "benchmark.json"), bench)
    if infra_failures:
        print(f"INCOMPLETE: {len(infra_failures)} of {len(jobs)} runs failed on infrastructure and have no score "
              "(benchmark.json infra_failures). Run them again, and only them, with: python3 evals/eval_run.py --resume "
              f"{os.path.relpath(it_dir, ROOT)} (a run still failing after {control['max_resumes']} resumption(s) is written "
              "as a timeout with score 0). Do not change the skill for them.", file=sys.stderr)
    for note in refused_note:  # said again at the end, where the operator reads the outcome
        print(note, file=sys.stderr)
    for hit in timeouts:
        print(f"TIMEOUT     case {hit['case']} {hit['variant']} ({hit['model']}) run {hit['run']}: still incomplete after "
              f"{hit['resumes']} resumption(s) ({hit['reason']}); it scores 0", file=sys.stderr)
    if contaminated:
        print(f"CONTAMINATED: {len(contaminated)} without-skill run(s) name a mount path of the workbench or the "
              "repository's path (benchmark.json contaminated): they are not scored, and the iteration is incomplete. "
              "Read the evidence, close the way in, and rerun.", file=sys.stderr)
    for hit in shared:
        print(f"WARNING shared passage: case {hit['case']} {hit['variant']} ({hit['model']}) run {hit['run']} shares "
              f"{len(hit['passage'].split())} words with the skill's own text that the case does not hold: "
              f"\"{hit['passage']}\". Read the run: a stock phrase, or a way the baseline reached the skill.", file=sys.stderr)
    # The evidence file: an event line and one line per scored run, in the run folder. It goes into the skill's
    # folder only when the event is complete and is no trial.
    # The id each model is written under: the gate file's listed id for a listed model or one of its aliases; for a model
    # the file does not list (a person's own test, which stays local) its own well-formed id.
    model_ids = {slot: status.model_id(model_cfg(gate, model), model) for slot, model in models}
    measurement_version = o["measurement_version"] or 1
    run_lines = []
    for job in jobs:
        variant = {"with_skill": "with", "without_skill": "without"}.get(job[1])
        name = job[1] + slot_suffix(job[2])
        row = next((r for r in results.get(name, []) if r["case"] == job[0]["id"] and r["run"] == job[4]), None)
        if variant is None or row is None or row.get("pass_rate") is None or "results" not in row:
            continue
        context = contexts[(job[0]["id"], variant == "with")]
        run_lines.append({"record": "run", "skill": o["skill"], "version": version, "content_sha256": start_hash,
                          "model": model_ids[job[2]], "adapter": harness_for[job[2]], "kind": kind, "test": test,
                          "date": row.get("date") or bench["date"], "measurement_version": measurement_version,
                          "measurement_sha256": fingerprint, "case": job[0]["id"], "case_sha256": hashes[str(job[0]["id"])],
                          **({"context_sha256": context} if context else {}),
                          **({"platform": o["platform"]} if o.get("platform") else {}),
                          **({"cpu_platform": environment["image_platform"]} if (environment or {}).get("image_platform") else {}),
                          **({"cost_usd": row["cost_usd"]} if isinstance(row.get("cost_usd"), (int, float))
                             and not isinstance(row.get("cost_usd"), bool) and row["cost_usd"] >= 0 else {}),
                          **({"run_sha256": row["run_sha256"]} if row.get("run_sha256") else {}),
                          **({"usage": row["usage"]} if row.get("usage") else {}),
                          "variant": variant, "outcome": row.get("outcome", "graded"), "score": row["pass_rate"],
                          "results": row["results"],
                          **({"guard_failed": row["guard_failed"]} if variant == "with" and row.get("guard_failed") else {})})
    line_counts = {}
    for slot, model in models:
        for variant_name, variant in (("with_skill", "with"), ("without_skill", "without")):
            c = counts[slot].get(variant_name)
            if c:
                into = line_counts.setdefault(model_ids[slot], {}).setdefault(variant, {k: 0 for k in status.COUNT_KEYS})
                for k in status.COUNT_KEYS:
                    into[k] += c[k]
                if variant == "with" and "invoked" in c:
                    into["invoked"] = into.get("invoked", 0) + c["invoked"]
    ran_baseline = {str(job[0]["id"]) for job in jobs if job[1] == "without_skill" and job[2] == LEAD_SLOT}
    reused = {cid for cid, n in in_force.items() if n >= baseline_count} if kind == "full" else set()  # a partial test uses none
    # What each model that ran through a key proxy was served by: the provider its entry of the gate file pins, or,
    # with no pin, the route's upstream host. What the event line's "upstream" states.
    upstream = upstream_of(models, model_ids, {slot: o["pass_env"] + o["pass_envs"][m] for slot, m in models}
                           ) if EXECUTOR == "container" else None
    event_line = {"record": "test", "skill": o["skill"], "test": test, "kind": kind, "version": version,
                  "content_sha256": start_hash, "date": event["started"][:10],
                  "models": [model_ids[slot] for slot, _ in models],  # the list shape: the slots are the runner's, not the evidence's
                  "adapters": {model_ids[slot]: harness_for[slot] for slot, _ in models},
                  "adapter_sha256": {harness_for[slot]: status.file_sha256(runner_for[slot]) for slot, _ in models},
                  "grader": status.model_id(gate, o["grader"]), "runs": o["runs"], "timeout_seconds": o["timeout"],
                  "retries": o["retries"], "measurement_version": measurement_version, "measurement_sha256": fingerprint,
                  "image_digest": (environment or {}).get("image_digest"), "image_platform": (environment or {}).get("image_platform"),
                  "grading_template_sha256": template_hash(), "tools": event.get("tools") or {}, "cases": hashes,
                  "baseline": {cid: ("run" if cid in ran_baseline else "reused" if cid in reused else "none") for cid in hashes},
                  "web_cases": bench["web_cases"], "counts": line_counts, "extra_pass_env": o["extra_pass_env"],
                  "complete": bool(complete_ref), "complete_models": [model_ids[t] for t, _ in models if complete_by[t]],
                  **({"upstream": upstream} if upstream else {}),
                  **({"imported": True} if o.get("skill_dir") else {}),
                  **({"local_model": event["local_model"]} if event.get("local_model") else {}),
                  **({"image_source": environment["image_source"]} if (environment or {}).get("image_source") else {})}
    gate_result = None
    if kind == "full" and complete_ref:
        # The gate of each model of the event, evaluated when a full test ends, by the rule of the model's section 2 on
        # that model's own lines: this test's lines with the skill on the model, with those of the earlier full tests
        # that list it, of the same X.Y and epoch, against the baselines in force for it (the ones this test ran, and
        # the ones it reused), unrounded. A model with no baseline of its own has no gate in the event.
        source = local_events if home == "local" else None
        gates = {}
        for slot, model in models:
            if not complete_by[slot]:  # a run of this model is missing: its gate would be computed on part of the test
                continue
            cfg = {**model_cfg(gate, model), "threshold": o["threshold"], "tolerance": o["tolerance"]}
            computed = status.gate_of(skill_dir, cfg, extra=[(event_line, run_lines)], evidence=source)
            if computed["passed"] is not None:
                gates[model_ids[slot]] = {"passed": bool(computed["passed"]), "with": computed["with"],
                                          "baseline": computed["baseline"], "threshold": o["threshold"],
                                          "tolerance": o["tolerance"],
                                          **({"note": computed["note"]} if computed["note"] else {})}
            elif slot == LEAD_SLOT:  # not computable from the lines (it should be, right after a full test): this test's own lines
                print(f"NOTE the gate could not be computed from the evidence ({computed['cause']}); it is computed on this "
                      "test's own lines", file=sys.stderr)

                def per_case(variant):
                    by = {}
                    for l in run_lines:
                        if l["variant"] == variant and l["model"] == model_ids[LEAD_SLOT]:
                            by.setdefault(str(l["case"]), []).append(l["score"])
                    return statistics.mean(statistics.mean(v) for v in by.values()) if by else None

                with_mean, base_mean = per_case("with"), per_case("without")
                gates[model_ids[slot]] = {
                    "passed": bool(load_measure().gate_passes(with_mean, base_mean, o["threshold"], o["tolerance"])),
                    "with": with_mean, "baseline": base_mean, "threshold": o["threshold"], "tolerance": o["tolerance"]}
        gate_result = gates.get(model_ids[LEAD_SLOT])  # the event is full by its lead model: the gate its exit code reads
        event_line["gate"] = gates
    evidence = {"written": False, "path": None, "scratch": None, "reason": scratch, "test": test, "kind": kind,
                "lines": len(run_lines), "gate": gate_result, "home": home}
    if not o["grade"]:
        evidence["reason"] = scratch or "--no-grade: nothing was scored"
    else:
        in_run_folder = evidence_file(it_dir, o["skill"], test)
        write_evidence(in_run_folder, event_line, run_lines)
        evidence["scratch"] = os.path.relpath(in_run_folder, ROOT)
        if scratch:
            pass
        elif not complete_ref and not closing:
            evidence["reason"] = (f"the event is incomplete: resume it (--resume {os.path.relpath(it_dir, ROOT)}), or give it "
                                  f"up and keep its runs (--close {os.path.relpath(it_dir, ROOT)})")
        elif status.content_hash(skill_dir) != start_hash and not closing:
            evidence["reason"] = "the skill folder changed during the event: its runs are of another content"
        else:
            # A file about to enter a skill is new evidence: read strictly (the current gate file's models and runs). A
            # person's own file is read by its own event line: its models are not in the gate file's list.
            problems = status.evidence_file_problems(in_run_folder, ROOT, o["skill"], strict=home == "repository")
            if problems:  # the runner never puts into a skill (or the local folder) a file its own validation refuses
                evidence["reason"] = "the evidence file is not valid: " + "; ".join(problems[:5])
            elif home == "local":
                # Outside the checkout: nothing of it is committed, pulled over or seen by `git status`.
                target = os.path.join(local_base, kept_as, os.path.basename(in_run_folder))
                os.makedirs(os.path.dirname(target), exist_ok=True)
                # Checked again once the folder exists: the skill's folder may be a link into the checkout.
                where = status.local_base_problem(local_base, ROOT, kept_as)
                if where or os.path.lexists(target):
                    evidence["reason"] = where or f"{target} exists: a local evidence file is never overwritten"
                else:
                    shutil.copyfile(in_run_folder, target)
                    evidence.update(written=True, path=target, reason=None)
            else:
                target = os.path.join(skill_dir, "evals", "evidence", os.path.basename(in_run_folder))
                os.makedirs(os.path.dirname(target), exist_ok=True)
                shutil.copyfile(in_run_folder, target)
                evidence.update(written=True, path=os.path.relpath(target, ROOT), reason=None)
    bench["evidence"] = evidence
    state = ("closed" if closing else "complete" if complete_ref else "open") if not scratch else ("complete" if complete else "open")
    with open(os.path.join(it_dir, "event.json"), encoding="utf-8") as f:
        write_json(os.path.join(it_dir, "event.json"), {**json.load(f), "state": state, "scratch": scratch,
                                                        "written": evidence["path"]})
    write_json(os.path.join(it_dir, "benchmark.json"), bench)
    print(f"EVIDENCE {o['skill']}: " + (
        f"{evidence['path']} written ({'an incomplete ' if not complete_ref else ''}{kind} test, {len(run_lines)} lines"
        + (f", gate {'passed' if gate_result['passed'] else 'failed'}" if gate_result else "")
        + ("). It stays on this machine, outside the checkout (" + (home_reason or "a local test") + "); "
           + (f"`eval_status.py status --skill-dir {o['skill_dir']}` shows it, as preliminary until a full test or a closed pool stands behind it."
              if o.get("skill_dir") else "`eval_status.py status` shows it as local.")
           if home == "local" else "). Commit it; it is never edited.")
        if evidence["written"] else f"nothing written into the skill ({evidence['reason']})"
        + (f"; the event's file is {evidence['scratch']}" if evidence["scratch"] else "")), file=sys.stderr)
    if bench["early_end_warning"]:
        print(f"WARNING early ends: {bench['early_end_warning']}", file=sys.stderr)
    for slot, model in models:
        c = counts[slot].get("with_skill") or {}
        if c.get("reported"):
            print(f"INVOKED     {model} loaded the skill in {c['invoked']} of {c['reported']} with-skill run(s)"
                  + ("" if c["invoked"] == c["reported"] else ": a run that did not still scores, as the description's failure"),
                  file=sys.stderr)
    if redactions:
        print(f"REDACTED: the value of a variable passed into the runs was replaced by its marker {redactions} time(s) in "
              "what the runs left (benchmark.json redactions, and per run). A model printed its environment: nothing of "
              "it was stored or sent to the grader.", file=sys.stderr)
    print(json.dumps({"iteration_dir": os.path.relpath(it_dir, ROOT), "conditions": conditions,
                      "failures": len(infra_failures), "complete": complete, "expected_runs": len(jobs),
                      "completed_runs": completed, "evidence": evidence, "contaminated": len(contaminated),
                      "shared_passages": len(shared), "timeouts": len(timeouts),
                      "early_ends": {t: {"early_ends": s["early_ends"], "attempts": s["attempts"], "rate": s["rate"]}
                                     for t, s in bench["early_ends"].items()},
                      "early_end_warning": bench["early_end_warning"]}))
    if closing:
        return 0 if evidence["written"] or scratch else 1
    if infra_failures:
        return 1
    if gate_result is not None:
        return 0 if gate_result["passed"] else 3
    if conditions and condition_fails(conditions):
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
