# A project's own script

How a project runs its own code as a step, and why that is allowed to exist: the script is approved by the hash of its exact content, runs in a sandbox with nothing of the machine in it, reaches only the destinations it declared and the person approved, and leaves its result as a new version of a source. It crosses three layers and belongs to none alone: the runtime owns the step kind (`runtime/step_project_script.py`), a provider owns the containers (`providers/script/`), and the sources module owns where the result lands (`runtime/sources.py`). Package P9 of the delegation platform plan, decision D25, findings S8 and F11.

## Purpose

A project has work that is plain code: turn an export into a table, call its own API, compute a weekly figure. No model is needed, but the work must not become a way around the platform's rules. The **project-script step kind** (`project-script`) is that work as a step of a workflow. It is a step task like `ingest` (it runs no skill and calls no model), with three differences that all come from one fact: the code is the project's own, so it is run only under limits that live in code (principle 11).

The idea behind each piece, in one line each:

- the script is approved by the sha256 of its exact bytes, together with its declared destinations and its lock file's sha256, all in the plan's arguments and so in the plan's hash; a changed file never runs, and the step tells the person to plan it again so that the new hash is approved by a plan of its own;
- the script runs with no credential in its environment (an allow-list written out in the command, never this process's environment), a read-only root, one read-only mount (itself), a size-capped memory-backed folder for its output, a non-root user, no capability, and limits on memory, processes, CPU and time;
- it has no network, unless it declares destinations; then it has an **internal** Docker network whose only other member is a per-step egress proxy, which serves a CONNECT to the declared `host:port` pairs and nothing else, refusing by name and by address;
- its dependencies are installed in a separate build container from a hashed lock file, with no mount at all; only the resulting image layer reaches the run, read-only;
- its result is one file that leaves as frames on the container's standard output, is read by the host with the rules of limit L24, and becomes a new version of a source, labelled as produced by the script (its sha256); it has no other way to write and no way to cause an effect.

## Artifacts it owns

| Artifact | Where | Notes |
|---|---|---|
| The step kind | `runtime/step_project_script.py` | `project-script`; steps `verify`, `deps`, `run`; empty footprint; not `unattended` |
| The provider | `providers/script/` (`container.py`, `_inner.py`, `egress_proxy.py`, `Dockerfile`, `.dockerignore`) | the class `script:project`, a runtime-only role |
| The script image | `openhora-script:<12 characters of the definition's hash>` | one image, three roles (the script, the dependency build, the proxy); built by a step the person starts, never pulled |
| A dependency image | `openhora-script-deps:<16 characters of the lock's sha256>-<12 of the definition>` | the layer a lock file's wheels were installed in; labelled `org.openhora.script.lock`; cached |
| A result | a new version of a `file` source, `<sources_dir>/<source id>/<n>/` | `manifest.json` has `produced_by` (kind, script path, `script_sha256`, destinations, `lock_sha256`) and `converter` (`project-script`, with the same fields as its tools) |
| Per-step objects | containers `openhora-script-{run,proxy,build}-<16 hex>`, networks `openhora-script-{in,out}-<16 hex>` | labelled `org.openhora.script=1` and `org.openhora.script.deadline=<epoch>`; removed by name when the step ends, reaped from the labels when a crash leaves them |

## Abstractions

| Name | What it is | Where |
|---|---|---|
| Arguments | `{"script", "sha256", "source", "destinations", ["lock", "lock_sha256"]}`, canonical, in the plan hash | `step_project_script.check`, `prepare` |
| Prepare | reads the files, scans them for credentials (a refusal names the line, never the value) and hashes them: the arguments of a plan | `step_project_script.prepare`, `python3 runtime/step_project_script.py prepare` |
| Files | the verified bytes of the script and the lock; what is staged and mounted | `step_project_script.load_files`, `stage` |
| Frames | the one stream a container's result leaves in: `OHF1`, `FILE <name> <size>` records, `END`; names `result.md`, `result.csv`, `result.txt`, `info.json` | `container.parse_frames`, `_inner.frames` |
| Egress | the network of one step: an internal network, an egress network for the proxy alone, the proxy joined to both | `container.Egress` |
| Declaration | a lowercase DNS name with a dot, a top label that starts with a letter, a port: no IP literal, no wildcard | `egress_proxy.parse_declared`, `step_project_script.check_destination` (a test holds them equal) |

## Dependencies

- `runtime/steps.py` (P5): the registry, the engine, `StepFailure`, `REL_PATH`.
- `runtime/sources.py` (P4): `import_version` (the one door a version enters by), `collect_outputs` (limit L24, now with a `names` list), `register`, the staging folder, the folder's lease.
- `runtime/workcopy.py`: `credential_findings` for the scan, and `scripts/redact.py` under it.
- `providers/_container.py` (P0): `argv` (every limit), `run` (the lifecycle, `stdout_cap`), `reap`, `remove`. The runner adds options before the image and a network in place of `none`; it never turns a limit off but the build container's `--rm` and `--read-only` (a layer must be kept, and the unprivileged build must write `/deps`).
- `providers/resolve.py`: the role `script` (in `ROLES`, not in `LISTED`, not in `contracts/environment.md`: no skill may require it).
- A local docker daemon and the script image (`python3 providers/script/container.py build --confirmed`, once).

## Business rules

**Approval.** The arguments are in the plan hash, which the person approves (terminal or page). `prepare` is how a person (or a tool) gets the arguments, and it refuses a credential before anything is approved. The kind also vets its arguments when a plan is built and before it is approved (`Kind.vet`, called from `ops_flows`): the script and the lock file are read from the project, the hash compared, the credential scan and the lock rules made, so a sha256 written by hand into a workflow does not reach a person's approval unchecked. At run time `verify` reads the file again, from the project root, a folder at a time with `O_NOFOLLOW`, and compares its sha256 with the plan's (`script_changed`; `lock_changed` for the lock file). The `run` step reads and hashes it once more and writes **those bytes** to the staging folder (mode 0444, in a 0700 folder under `<data_dir>/sources-staging/`), which is what the container mounts (its host path is visible to the script in `/proc/self/mountinfo`, so keep `data_dir` at a path that names nobody): a file swapped between the check and the start changes nothing. A path may not begin a folder or file name with a dot, may not lie in the sources folder, and may not pass through a link.

**A changed file asks.** A changed script stops the step (`script_changed`), nothing is staged and no container starts. The task is `failed` and resumable; its note tells the person to read the file and plan the step again with `prepare`, so the new hash is approved by the plan card, a pending decision of kind `plan` that only the terminal and the page approve. It is not a `question` decision on purpose: the default policy of the messaging channel answers questions, and a chat message must not be able to approve new code.

**Not unattended.** The kind says `unattended=False`: the dispatcher never starts it; a person starts it with `run-step`. The kind is `networked` (always: it cannot know at registration whether a task declares destinations), so a routine whose workflow holds one is made and changed only from the terminal or the page (limit L33), and the routine's approved content holds, for each such step, the script's sha256, its destinations, the lock file's sha256 and the definition hash of the script image (`Kind.routine_slot`, `steps.routine_slots`, the `scripts` slot of runtime/routines.py), so that a change to any of them stops the routine and asks. A routine that fires finds the task held `start it by hand`: the kind is not unattended, and running a script without a person is a later decision.

**The container.** `providers/_container.py` `argv` gives the limits (a read-only root, every capability dropped, `no-new-privileges`, a limit on processes and memory with swap, CPUs, memory-backed `/tmp` and `/scratch` with no exec, an image that is never pulled, the label and the deadline, the caller's user on Linux). The runner adds the script mount, the log limit and the `-e NAME=VALUE` pairs of `ENV_ALLOWED`, which holds proxy variables and a few build switches and nothing that looks like a key; a name outside the list is refused, a bare `-e NAME` (which docker fills from the client's environment) is never written, and this process's environment is never read. Inside, `_inner.py` runs the script as a child with an environment of its own, the child's output going to a file and never to the stream the host reads, and kills what the script left running.

**The result.** One file, `result.md`, `result.csv` or `result.txt`, written to `$OUTPUT_DIR`. `_inner.py` reads it with `lstat` and `O_NOFOLLOW` (a link, a folder, a pipe, a second link or any other name is refused, not read), cuts it one byte over the runtime's cap, and prints the frames. The host parses them with fixed rules (a start and an end marker, nothing after, closed names, caps, at most two records), writes them into an empty 0700 folder with `O_EXCL | O_NOFOLLOW`, and the step reads that folder back with `sources.collect_outputs` (limit L24), then imports the file: Markdown and text through the text path, CSV through the converter. A script cannot forge the stream into something it could not produce legitimately, because everything the host accepts is a result file or the account of the run; a forged stream is a stream that breaks the end-marker rule and is refused whole (`bad_output`, tested against a real container).

**The network.** `--network none` unless the arguments declare destinations. With destinations, the provider (1) creates the step's network with `--internal` and the gateway mode `isolated` (on a plain internal bridge the host's gateway address answers, with resets from its stack, and every service the host listens on is reachable without the proxy; isolated gives the network no host address at all) and reads `Internal`, the option and the IPv6 setting back before it starts anything on it (a daemon that cannot isolate the gateway refuses the run: `network_not_internal`); (2) creates an egress network for the proxy alone; (3) starts the proxy on the egress network, which resolves every declared name once, refuses a name that does not resolve or any of whose addresses is not public (loopback, link-local, private, carrier-grade, multicast, unspecified, reserved), and then listens; (4) joins the proxy to the internal network under the alias `egress`; (5) starts the script on the internal network only, with `HTTPS_PROXY` and friends pointing at `egress:3128`. The proxy serves `CONNECT` and nothing else: a declared name with a declared port, or an IP literal that is one of the addresses it froze for such a name, with that port. A name that is not declared is refused by name (403); an IP literal that is not in the frozen resolution is refused by address (403), whatever its spelling (`2130706433` and `0x7f000001` are undeclared names); a CONNECT dials the frozen addresses, never a fresh lookup. On an internal network a container has no route out and no external DNS (item 11 of the plan's "To verify", tested here against a real daemon): an undeclared name does not resolve at all, and a script that ignores the proxy variables and dials an address gets nothing.

**Dependencies.** Python only; a shell script has none. A lock file is `name==version` followed by `--hash=sha256:<hex>` options and nothing else (no index, no URL, no path, no `-r`, no editable install); the same rules are checked at `prepare`, at `verify`, before the build and inside the build container. The build container has no mount and no volume at all: the lock arrives on standard input, pip runs with `--require-hashes --only-binary=:all: --no-deps` (wheels only, so no package code runs at install time), the network is the package index (`pypi.org`, `files.pythonhosted.org`) through the same kind of per-step proxy, and the container's file system is kept as an image layer by `docker commit`, labelled with the lock's sha256. A lock file is built once per image definition. The run takes that image only with the approved lock's sha256 and checks both of the image's labels (the lock, and the definition now current). The build's memory-backed `/tmp` is 512 MiB (`BUILD_TMP_MB`: pip unpacks wheels there; a wheel larger than that does not build). The run uses that image, so the dependencies are read-only because the root is.

**Containers and the sweep.** Everything is named `openhora-script-<role>-<16 hex>`, a shape the eval harness's orphan sweep (`runtime/orphans.py`) never selects (it selects `wb-eval-run-`, `wb-eval-keys-` and `wb-eval-held-` only; a test holds this). The provider reaps its own: every `run` and `deps` first removes containers and networks of the label `org.openhora.script` whose deadline label has passed; `python3 providers/script/container.py reap` does the same by hand. The proxy also ends by itself after the step's time limit and a margin.

## Entry points

| Call | What it does |
|---|---|
| `python3 runtime/step_project_script.py prepare --project <dir> --script <path> --source <id> [--destination <host:port>]... [--lock <path>]` | prints the arguments (JSON) of a plan, after the credential scan; writes nothing |
| a flow task `{"key", "step": "project-script", "args": {...}}` | the step in a workflow (flow files learn `step` with P6) |
| `python3 runtime/cli.py run-step --project <dir> --task <id>` | the person starts the task; the dispatcher does not |
| `python3 providers/script/container.py --check \| build --confirmed \| run ... \| deps ... \| reap` | the provider's verbs; `run` and `deps` are what the step calls |

The failures are closed codes in the task's note and state: `bad_args`, `script_missing`, `script_too_large`, `script_not_text`, `path_unsafe`, `protected_path`, `script_changed`, `lock_changed`, `script_has_credential` (field `line_<n>`), `bad_lock`, `deps_missing`, `script_failed` (field `exit_<n>`), `script_killed` (field `signal_<n>`), `no_result`, `output_refused`, `output_too_large`, `source_type`, `import_<reason>`, and the provider's words (`time_limit`, `destination_unresolvable`, `destination_not_public`, `network_not_internal`, `proxy_failed`, `bad_output`, `build_failed`, `not_configured`, `provider_failed`, ...). The script's own log is never kept: not in the state, a note or a decision.

## Known limits and improvements

- **Destinations are TLS endpoints.** The proxy tunnels CONNECT only, so a client must speak `https` (or tunnel); a plain `http://` request through a proxy is a different method and is refused. A destination must resolve to public addresses: a service on the person's own network cannot be declared. Both are the stricter rule on purpose (principle 13); a later decision can add a per-destination allowance that enters the hash.
- **The package index is a constant** (`pypi.org`, `files.pythonhosted.org`). A private index would be a declared destination of the build that enters the lock's hash; it is not built.
- **The boundary of a destination is an address and a port.** The proxy does not look at the TLS server name: a declared name that resolves to a shared address (a CDN) can front another site on that address. A declaration says which addresses may be dialled, not which site answers.
- **The host path of the mount** is visible to the script in `/proc/self/mountinfo`: the staged copy lives under `<data_dir>/sources-staging/`, so a `data_dir` that carries a user name shows it.
- **No script log.** A failing script says its exit code and nothing else; run it yourself to see why.
- **Dependency images are not pruned.** Each lock file leaves one image (`openhora-script-deps:*`); remove old ones with `docker image rm`.
- **Wheels for the image's platform.** The build installs for the platform of the image (Linux, Python 3.11, the architecture of the machine's docker); a lock whose hashes are of wheels for another platform fails at the build.
- **The real package index was not exercised by a test.** The build's orchestration, its argument list, the lock rules and its failure path are tested against a real daemon; a successful install needs the real index (or a TLS index with its own certificate), and no test calls a real service.
- **Not a boundary:** the frames. `_inner.py` is not trusted to be the only writer of the stream, and the host does not need it to be. The boundary is the host's parse, the folder it writes into and `collect_outputs`.

## Changes

- 2026-10-15: first version, with package P9: the step kind `project-script`, the provider `script:project`, limits L34 to L38.
