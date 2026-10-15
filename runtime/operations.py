"""The table of operations: the one place that says what the operations layer (runtime/ops.py) offers to a shell.

A shell (the terminal's runtime/cli.py, the conversation's runtime/chat.py, the local service's runtime/service.py, the MCP
mode's runtime/mcp.py, the messaging bridge's runtime/messaging.py) derives what it accepts from
this table and spells nothing of its own: one row per operation, with its arguments, the channels that may call it
and whether it calls a model. Adding an operation adds one row here and one function in ops.py; adding a shell adds a
file. The channel rule is a column: a row lists the channels that may call it, and a row whose function takes the
channel (`channel_arg`) is told which one called it, so that code, not a prompt, refuses what a channel may not do
(an effect is approved only from the terminal or from the local page, with its hash; never from the conversation).

The channel policy (decisions M-8, M-12, M-13) is the second half of the file: GROUPS, DEFAULT_POLICY, BRAKES, EFFECT_CHANNELS
and the pure functions permitted, policy_allows, refusal and permissions. A project narrows a channel's ceiling with named
groups; `refusal` is the one helper every shell and the operations layer call, and contracts/runtime.md says where.

OPERATIONS and CHAT_OWN are pure literals (`ast.literal_eval` reads them: scripts/architecture_tables.py and a test
do, so that the generated tables and the shells cannot differ). A row:

  name         the terminal's verb and the conversation's command word (`run-next`, `/approve`)
  call         the function of ops.py that runs it
  args         the arguments, in the order the conversation reads them; each {"name": the function's parameter,
               "kind": int | str | text | file | list | flag | choice | pairs, "required": True, "flag": the terminal flag when it
               is not the name with hyphens, "label": the placeholder in a help line, "choices": for a choice}.
               `text` is the terminal's --text / --text-file pair and, in the conversation, the rest of the line;
               `flag` is true when present; `pairs` is the handler's repeated --arg k=v; `file` is the path of a file the
               shell reads whole, as text, and the function takes the text; `list` is a repeated flag, the function takes
               the list
  channels     which channels may call it: "terminal", "chat", "page" (the local service, runtime/service.py: a route
               exists only for an operation whose row lists "page"; an operation that widens what an agent may do on
               its own, or that runs the next task by hand, lists "terminal" only), "mcp" (the MCP mode,
               runtime/mcp.py: a tool exists only for an operation whose row lists "mcp"; the reads, and the writes a
               model client may make: request, route, answer, release a draft and say; never approve, reject, cancel
               or retry, as a tool or typed into `say`, whose row takes the channel and does a command only when
               that command's row lists it), "messaging" (the messaging bridge, runtime/messaging.py: the reads, the
               writes a chat may make, and approve, reject, retry and cancel; code, not a prompt, narrows approve there:
               a plan only with its hash, an acceptance bound by the bridge to the card the person saw, an effect never)
  model        whether it calls a model: False, True, or the words that say when ("without --flow")
  help         one line: what it does
  channel_arg  (optional) the function takes `channel=<name>` and decides what that channel may do
  chat_reply   (optional) the key of the result the conversation shows instead of the whole result
  exclusive    (optional) whether a shell gives the operation the project's model slot (one job that calls a model at a
               time); default `bool(model)`. False for `dispatch` and `run-task`, which start task runs beside one another
               and beside the router's run
  job          (optional) true when the operation calls a model or a platform, so that it may take minutes: the local
               service starts it in a thread and answers at once with a job to ask for again, instead of holding the
               request open. It is the one source of "returns a job"; every row whose `model` is not False has it
  queues       (optional) true when the operation, while a run of the project is in progress, records its call and
               answers `{"queued": true}` instead of refusing, and the local service routes it when the run ends
               (`say`, `route`); only for a channel that drains the queue (ops_say.QUEUING_CHANNELS: the page), every
               other channel is refused as before, so such a row also takes the channel (`channel_arg`). The service
               lets such a job start while another job holds the model slot, so the operation itself finds the
               router's lock held and queues
  exit_unless  (optional) [key, value]: the terminal prints the result and exits 1 unless result[key] == value (a
               result that says the model did not answer is not a failure of the operation, and is still printed)

The functions are pure and use the standard library only. Runs on Python 3.9: python3 runtime/operations.py --help
"""
from __future__ import annotations

import os
import re
import shlex
import sys
import unicodedata

TERMINAL = "python3 runtime/cli.py"             # the relative form, in a text stored before it is shown (no checkout to name)
KEYRING_PIN = "keyring==25.7.0"                 # the secret-store library the providers pin (providers/secrets/resolver.py)
UV_PREFIX = f"uv run --with {KEYRING_PIN}"
UV_MARK = "WORKBENCH_STARTED_WITH_UV"           # "1" or "0" says how the process was started, over what its interpreter shows
HELP_HEAD = "Commands, one per line; any other line is a request for the planning agent, or the answer to its question:"
HELP_WIDTH = 27

OPERATIONS = (
    {"name": "request", "call": "request",
     "args": ({"name": "text", "kind": "text", "required": True}, {"name": "flow", "kind": "str"},
              {"name": "title", "kind": "str"}, {"name": "after", "kind": "int"}, {"name": "model", "kind": "str"}),
     "channels": ("terminal", "page", "mcp"), "model": False,
     "help": "record what you want; with a flow, plan it from the flow file, else it waits for its route; with after, run it after that request; with model, run its tasks on that model (an id of the gate file, or auto)"},
    {"name": "route", "call": "route",
     "args": ({"name": "request_id", "kind": "int", "required": True, "flag": "request"}, {"name": "flow", "kind": "str"}),
     "channels": ("terminal", "page", "mcp"), "model": "without --flow", "job": True, "channel_arg": True, "queues": True,
     "help": "plan a request that waits for its route: one run of the router skill, or the plan of a flow file; on the page, while a run is in progress, the request is queued"},
    {"name": "route-queued", "call": "route_queued", "args": (), "channels": ("terminal",), "model": True, "job": True,
     "help": "route the oldest queued line or request, when no run is in progress (the local service calls it every few seconds)"},
    {"name": "status", "call": "status", "args": (), "channels": ("terminal", "chat", "page", "mcp", "messaging"), "model": False,
     "help": "requests, tasks and what waits for you"},
    {"name": "task", "call": "task",
     "args": ({"name": "task_id", "kind": "int", "required": True, "flag": "task", "label": "task id"},),
     "channels": ("terminal", "page", "mcp", "messaging"), "model": False,
     "help": "one task or request with its runs and its pending decisions"},
    {"name": "flows", "call": "flows", "args": (), "channels": ("terminal", "page", "mcp"), "model": False,
     "help": "the flow files of this checkout, with their titles and how many tasks each holds"},
    {"name": "config", "call": "config", "args": (), "channels": ("terminal", "page"), "model": False,
     "help": "the configuration's path and hash, whether you accepted it, and the data folder; it never refuses"},
    {"name": "progress", "call": "progress", "args": ({"name": "since", "kind": "str"},),
     "channels": ("terminal", "chat", "page", "mcp", "messaging"), "model": False, "chat_reply": "text",
     "help": "where the work stands and what happened (since: 7d, <n>d or YYYY-MM-DD)"},
    {"name": "pending", "call": "pending",
     "args": ({"name": "pending_id", "kind": "int", "flag": "id"},),
     "channels": ("terminal", "chat", "page", "mcp", "messaging"), "model": False,
     "help": "what waits for you; with an id, that decision whole"},
    {"name": "answer", "call": "answer",
     "args": ({"name": "pending_id", "kind": "int", "required": True, "flag": "id"},
              {"name": "text", "kind": "text", "required": True},
              {"name": "with_comments", "kind": "flag", "flag": "with-comments"}),
     "channels": ("terminal", "chat", "page", "mcp", "messaging"), "model": False,
     "help": "answer a pending decision"},
    {"name": "release", "call": "release",
     "args": ({"name": "pending_id", "kind": "int", "required": True, "flag": "id"},),
     "channels": ("terminal", "chat", "page", "mcp", "messaging"), "model": False, "job": True,
     "help": "release a delivery (it stays a draft)"},
    {"name": "approve", "call": "approve",
     "args": ({"name": "pending_id", "kind": "int", "required": True, "flag": "id"}, {"name": "sha256", "kind": "str"},
              {"name": "go_ahead", "kind": "list", "flag": "go-ahead"}),
     "channels": ("terminal", "chat", "page", "messaging"), "model": False, "channel_arg": True, "job": True,
     "help": "approve a plan or an acceptance (a plan: --go-ahead <task key>, repeated, drops that task's derived waits); an effect is approved in the terminal or on the page, with its hash"},
    {"name": "reject", "call": "reject",
     "args": ({"name": "pending_id", "kind": "int", "required": True, "flag": "id"}, {"name": "note", "kind": "str"}),
     "channels": ("terminal", "chat", "page", "messaging"), "model": False,
     "help": "reject a plan, an acceptance or an effect"},
    {"name": "retry", "call": "retry",
     "args": ({"name": "task_id", "kind": "int", "required": True, "flag": "task", "label": "task id"},),
     "channels": ("terminal", "chat", "page", "messaging"), "model": False,
     "help": "make a failed or blocked task ready again"},
    {"name": "go-ahead", "call": "go_ahead",
     "args": ({"name": "task_id", "kind": "int", "required": True, "flag": "task", "label": "task id"},
              {"name": "drop_after", "kind": "flag", "flag": "drop-after"}),
     "channels": ("terminal", "page"), "model": False,
     "help": "go ahead on a task that waits for another request's task: its derived waits end (with drop-after, its after wait)"},
    {"name": "cancel", "call": "cancel",
     "args": ({"name": "request_id", "kind": "int", "required": True, "flag": "request", "label": "request id"},),
     "channels": ("terminal", "chat", "page", "messaging"), "model": False,
     "help": "cancel a request"},
    {"name": "deps", "call": "deps", "args": (), "channels": ("terminal",), "model": False,
     "help": "install the dependency sets of runtime.json, by code"},
    {"name": "run-next", "call": "run_next", "args": ({"name": "model", "kind": "str"},),
     "channels": ("terminal",), "model": True, "job": True,
     "help": "run the next ready task: one skill, once, on the model chosen for it (or the one you name with --model)"},
    {"name": "run-task", "call": "run_task",
     "args": ({"name": "task_id", "kind": "int", "required": True, "flag": "task", "label": "task id"},
              {"name": "model", "kind": "str"}),
     "channels": ("terminal",), "model": True, "job": True, "exclusive": False,
     "help": "run one named task in this process; the dispatcher starts it, a person uses run-next"},
    {"name": "run-step", "call": "run_step",
     "args": ({"name": "task_id", "kind": "int", "required": True, "flag": "task", "label": "task id"},
              {"name": "unattended", "kind": "flag"}),
     "channels": ("terminal",), "model": False,
     "help": "run one named step task in this process, no model: what the dispatcher starts (with --unattended, which asks again for the brake and the kind's flag) for a step task of a kind it may start on its own (ingest, and the kinds that follow); nothing but tests creates a step task today, until the flow files learn `step` (P6)"},
    {"name": "accept-config", "call": "accept_config",
     "args": ({"name": "sha256", "kind": "str", "required": True},
              {"name": "adopt_sources", "kind": "flag", "flag": "adopt-sources"}),
     "channels": ("terminal",), "model": False,
     "help": "record the hash of runtime.json you accept; --adopt-sources also lets this project take over a sources folder marked for another"},
    {"name": "proof", "call": "proof", "args": ({"name": "skill", "kind": "str"},),
     "channels": ("terminal",), "model": False,
     "help": "the model each skill in use would run on when nothing chooses one, with its band, price and expected cost on every model, and the two checks"},
    {"name": "verdict", "call": "verdict",
     "args": ({"name": "run_id", "kind": "int", "required": True, "flag": "run"},
              {"name": "word", "kind": "str", "required": True}),
     "channels": ("terminal", "page"), "model": False,
     "help": "record your verdict on what one run delivered (worked, corrected or failed)"},
    {"name": "sync", "call": "sync",
     "args": ({"name": "dry_run", "kind": "flag", "flag": "dry-run"},
              {"name": "take", "kind": "choice", "choices": ("page", "project")}, {"name": "path", "kind": "str"}),
     "channels": ("terminal", "page"), "model": False, "job": True,
     "help": "mirror the tasks with the task board and the documents with the documents platform"},
    {"name": "hand-over", "call": "hand_over",
     "args": ({"name": "task_id", "kind": "int", "required": True, "flag": "task"},
              {"name": "file", "kind": "str", "required": True}),
     "channels": ("terminal", "page"), "model": False,
     "help": "copy one file of yours into a task's file drop"},
    {"name": "set-mode", "call": "set_mode",
     "args": ({"name": "agent", "kind": "str", "required": True}, {"name": "mode", "kind": "str", "required": True},
              {"name": "accept", "kind": "flag"}, {"name": "consent", "kind": "flag"}),
     "channels": ("terminal", "page"), "model": False, "channel_arg": True,
     "help": "set one area agent's autonomy mode in runtime.json (for the agent `runtime`, the owner of step tasks, only stopped or autonomous: the brake of step tasks, kept in the store); --accept (terminal only) also accepts the hash it makes, when the file was the accepted one before; --consent (terminal only) is the consent an autonomous agent with a model fixed needs, and is distinct from --accept"},
    {"name": "set-model", "call": "set_model",
     "args": ({"name": "agent", "kind": "str", "required": True}, {"name": "model", "kind": "str", "required": True},
              {"name": "accept", "kind": "flag"}, {"name": "consent", "kind": "flag"}),
     "channels": ("terminal", "page"), "model": False, "channel_arg": True,
     "help": "fix one area agent to a model (an id of the gate file, auto, or default) in runtime.json; --accept (terminal only) accepts the hash; --consent (terminal only, distinct from --accept) is, for an agent in an autonomous mode, your consent after the warning: its reviews on that model are released by the mode and recorded as autonomy by consent"},
    {"name": "give-consent", "call": "give_consent",
     "args": ({"name": "agent", "kind": "str", "required": True}, {"name": "model", "kind": "str", "required": True},
              {"name": "mode", "kind": "str", "required": True}, {"name": "config_sha256", "kind": "str", "required": True},
              {"name": "warning_sha256", "kind": "str", "required": True}),
     "channels": ("page",), "model": False, "channel_arg": True,
     "help": "the page gives your consent for one area agent in an autonomous mode: it sends the model, the mode, the hash of the configuration it read and the hash of the warning it showed; only that consent is recorded and accepted. In the terminal the consent is set-model --consent"},
    {"name": "approve-policy", "call": "approve_policy",
     "args": ({"name": "file", "kind": "str", "required": True}, {"name": "agent", "kind": "str", "required": True},
              {"name": "sha256", "kind": "str"}, {"name": "expires", "kind": "str"}, {"name": "what", "kind": "str"}),
     "channels": ("terminal",), "model": False,
     "help": "approve a policy file for one area agent (a standing approval)"},
    {"name": "revoke-policy", "call": "revoke_policy",
     "args": ({"name": "approval_id", "kind": "int", "required": True, "flag": "id"},),
     "channels": ("terminal",), "model": False,
     "help": "end a standing approval"},
    {"name": "standing", "call": "standing",
     "args": ({"name": "policy", "kind": "str", "required": True},),
     "channels": ("terminal",), "model": False,
     "help": "whether an active standing approval covers a policy now; it executes nothing"},
    {"name": "execute-under-policy", "call": "execute_under_policy",
     "args": ({"name": "policy", "kind": "str", "required": True},
              {"name": "effect_file", "kind": "str", "required": True, "flag": "effect-file"},
              {"name": "replay_log", "kind": "str", "flag": "replay-log"}),
     "channels": ("terminal",), "model": False,
     "help": "execute an effect a handler wrote, inside the bounds of a standing approval; with --replay-log, only check it"},
    {"name": "contained-run", "call": "contained_run",
     "args": ({"name": "skill", "kind": "str", "required": True},
              {"name": "prompt", "kind": "file", "required": True, "flag": "prompt-file"},
              {"name": "out_dir", "kind": "str", "required": True, "flag": "out"},
              {"name": "platforms", "kind": "list", "flag": "platform"},
              {"name": "timeout", "kind": "int", "flag": "timeout-seconds"}),
     "channels": ("terminal",), "model": True, "job": True, "exit_unless": ("status", "ok"),
     "help": "run one skill of an area agent's pack in the container on the artifacts it declares; only its reply comes out"},
    {"name": "dispatch", "call": "dispatch", "args": (), "channels": ("terminal", "page"), "model": True, "job": True,
     "channel_arg": True, "exclusive": False,
     "help": "one round of the dispatcher: the handlers' ticks, the releases by a mode, the ready tasks the rules allow, each a process of its own; the terminal waits for them, the page returns at once"},
    {"name": "poll", "call": "poll", "args": (), "channels": ("terminal",), "model": False,
     "help": "the short job: mirrors, expired approvals, the state file's generated lines, the releases"},
    {"name": "handler", "call": "handler_call",
     "args": ({"name": "name", "kind": "str", "required": True}, {"name": "verb", "kind": "str", "required": True},
              {"name": "args", "kind": "pairs", "flag": "arg"}),
     "channels": ("terminal",), "model": False, "job": True,
     "help": "start one verb of a handler that runtime.json names"},
    {"name": "pin", "call": "pin", "args": (), "channels": ("terminal",), "model": False,
     "help": "write the pin of the dispatcher's two jobs"},
    {"name": "say", "call": "say", "args": ({"name": "text", "kind": "text", "required": True},),
     "channels": ("terminal", "page", "mcp", "messaging"), "model": "for a new request", "job": True, "channel_arg": True, "queues": True,
     "help": "one turn of the conversation with the planning agent; on the page, while a run is in progress, a line that needs the planner is queued (elsewhere refused); a question about the state is answered at once"},
    {"name": "agents", "call": "agents", "args": (), "channels": ("terminal", "page", "mcp", "messaging"), "model": False,
     "help": "each area agent: its mode, its caps, what it used today and how many tasks wait for it"},
    {"name": "conversation", "call": "conversation",
     "args": ({"name": "conversation", "kind": "str"}, {"name": "after", "kind": "int"}),
     "channels": ("terminal", "page", "mcp"), "model": False,
     "help": "the messages of the project's conversation above a message id, oldest first"},
    {"name": "skills", "call": "skills", "args": (), "channels": ("terminal", "page", "mcp", "messaging"), "model": False,
     "help": "the skills in scope with their proof on each model, their runs here and the two checks of the proof"},
    {"name": "costs", "call": "costs", "args": ({"name": "since", "kind": "str"},),
     "channels": ("terminal", "page", "mcp", "messaging"), "model": False,
     "help": "the runs by day, agent, model and adapter, with the recorded cost and the cost recomputed from the prices"},
    {"name": "connections", "call": "connections", "args": (), "channels": ("terminal", "page", "mcp"), "model": False,
     "help": "which provider each requirement class resolves to, which secrets are found (never a value), the image"},
    {"name": "artifacts", "call": "artifacts", "args": (), "channels": ("terminal", "page", "mcp", "messaging"), "model": False,
     "help": "the project's files under docs/ with their owner skill, size and time"},
    {"name": "artifact", "call": "artifact",
     "args": ({"name": "path", "kind": "str", "required": True},),
     "channels": ("terminal", "page", "mcp", "messaging"), "model": False,
     "help": "the text of one file under docs/ of the project, read-only"},
    {"name": "artifact-raw", "call": "artifact_raw",
     "args": ({"name": "path", "kind": "str", "required": True},),
     "channels": ("page",), "model": False,
     "help": "the bytes of one image under docs/ of the project (png, jpeg, webp or svg, by its magic number), read-only; the service answers them with their media type"},
    {"name": "version", "call": "version", "args": (), "channels": ("page", "mcp"), "model": False,
     "help": "the change signal of the project's store: a number that grows on every write, and when the file was last written"},
    {"name": "commands", "call": "commands", "args": (), "channels": ("page",), "model": False,
     "help": "the commands of the conversation as rows, command, arguments and help line, in the order /help prints them (the page lists them when the person types /)"},
    {"name": "stop-runs", "call": "stop_runs", "args": ({"name": "every", "kind": "flag", "flag": "all"},),
     "channels": ("terminal",), "model": False,
     "help": "end the runs this process started (the local service calls it before it exits); with --all, every task run of the project that a live process holds"},
    {"name": "service-check", "call": "service_check", "args": ({"name": "dispatch_every", "kind": "int", "flag": "dispatch-every"},),
     "channels": ("terminal",), "model": False,
     "help": "what the local service checks at its start: the secret store, the credential, docker, the eval image and whether it dispatches (the service calls it for each project)"},
    {"name": "source-add", "call": "source_add",
     "args": ({"name": "source_id", "kind": "str", "required": True, "flag": "source", "label": "source id"},
              {"name": "source_type", "kind": "choice", "choices": ("file", "notion", "drive"), "required": True, "flag": "type"},
              {"name": "origin", "kind": "str", "required": True},
              {"name": "description", "kind": "str"}),
     "channels": ("terminal", "page"), "model": False,
     "help": "register a source of this project: its id, its type (file, notion or drive) and its origin (a file's name, a Notion page's address or id, or a Drive file's id); nothing is imported and no credential is kept"},
    {"name": "source-import", "call": "source_import",
     "args": ({"name": "source_id", "kind": "str", "required": True, "flag": "source", "label": "source id"},
              {"name": "file", "kind": "str"}, {"name": "url", "kind": "str"}, {"name": "origin", "kind": "str"},
              {"name": "description", "kind": "str"}),
     "channels": ("terminal", "page"), "model": False,
     "help": "import a version of a source from a file of yours (--file) or from a Notion page (--url, its address or id): read, converted to text in a container with no network, scanned, and kept as an immutable version in the sources folder"},
    {"name": "source-refresh", "call": "source_refresh",
     "args": ({"name": "source_id", "kind": "str", "required": True, "flag": "source", "label": "source id"},
              {"name": "file", "kind": "str"}),
     "channels": ("terminal", "page"), "model": False,
     "help": "a new version of a source: from a new file, from its Notion page again, or, with neither, from the file you changed in the sources folder (it becomes a version labelled as yours, which a task that starts on its own never receives)"},
    {"name": "source-drive", "call": "source_drive",
     "args": ({"name": "file_id", "kind": "str", "flag": "file-id"},
              {"name": "source_id", "kind": "str", "flag": "source", "label": "source id"},
              {"name": "description", "kind": "str"}),
     "channels": ("terminal",), "model": False,
     "help": "make Google Drive files sources: the Picker opens on a one-shot page on 127.0.0.1 and you choose one or more files (never a folder); each becomes a source and its first version is imported; with --file-id and --source, one file already picked is imported or refreshed"},
    {"name": "source-describe", "call": "source_describe",
     "args": ({"name": "source_id", "kind": "str", "required": True, "flag": "source", "label": "source id"},
              {"name": "description", "kind": "str"}),
     "channels": ("terminal", "page"), "model": False,
     "help": "set your description of a source (what it is, what it is for); the planner reads it with the catalog; an empty one clears it"},
    {"name": "sources", "call": "sources_catalog", "args": (), "channels": ("terminal", "page", "mcp", "messaging"), "model": False,
     "help": "the catalog of the project's sources: each source, its newest version (name, type, size, date, sheets and columns with sample values, first headings), your description and whether its files changed outside the runtime"},
)

# What the conversation answers itself, with no operation: the help, and a new request whatever is open.
CHAT_OWN = (
    {"name": "help", "args": "", "help": "list the commands", "order": "first"},
    {"name": "new", "args": "text", "help": "start a new request, whatever is open (--after <id> before the text: run it after that request)", "order": "last"},
)

# The channel policy (decisions M-8, M-12, M-13). The `channels` column of the table is the ceiling of a channel; a
# project's runtime.json (`channels.<channel>`, a list of these group names) narrows it, never widens it. A group names
# the operations it covers, and, for `approve`, the kind of decision (a group with no kind covers every kind its
# operations take). Every operation that the page, the MCP mode or the messaging channel may call is in exactly one group
# (a test walks the table). A group is valid on a channel when one of its operations is in that channel's ceiling; it then
# covers the ceiling's share of it. Pure literals, like the table.
GROUPS = {
    "read": {"operations": ("status", "progress", "pending", "task", "agents", "costs", "skills", "artifacts", "artifact",
                            "flows", "conversation", "connections", "version", "config", "commands", "artifact-raw"),
             "kind": None},
    "talk": {"operations": ("say",), "kind": None},
    "answer": {"operations": ("answer",), "kind": None},
    "release": {"operations": ("release",), "kind": None},
    "request": {"operations": ("request", "route"), "kind": None},
    "approve-plans": {"operations": ("approve",), "kind": "plan"},
    "approve-acceptances": {"operations": ("approve",), "kind": "acceptance"},
    "approve-effects": {"operations": ("approve",), "kind": "effect"},
    "go-ahead": {"operations": ("go-ahead",), "kind": None},
    "reject-cancel": {"operations": ("reject", "cancel"), "kind": None},
    "retry": {"operations": ("retry",), "kind": None},
    "set-mode": {"operations": ("set-mode", "set-model"), "kind": None},
    "consent": {"operations": ("give-consent",), "kind": None},   # the page's consent for an autonomous agent (D38): a group of its own, so granting set-mode never grants it
    "dispatch": {"operations": ("dispatch",), "kind": None},
    "documents": {"operations": ("sync", "hand-over"), "kind": None},
    "verdict": {"operations": ("verdict",), "kind": None},
    "sources": {"operations": ("source-add", "source-import", "source-refresh", "source-describe", "sources"), "kind": None},
}
# The policy of a channel that has no entry in the project's configuration. A channel absent from this table keeps its
# whole ceiling; the terminal is never narrowed. The messaging channel is closed: what changes the work other than a
# line to the planning agent and an answer is turned on explicitly.
DEFAULT_POLICY = {"messaging": ("read", "talk", "answer")}
NEVER_NARROWED = ("terminal",)
POLICY_CHANNELS = ("page", "mcp", "messaging")     # the channels a project's configuration narrows; `chat` (local access, equal to the terminal) and `terminal` never are
MUST_READ = ("page", "mcp")                        # a policy for these lists `read`
PAGE_ONLY_GROUPS = ("approve-effects",)            # valid on the page alone (an effect is approved nowhere else, by EFFECT_CHANNELS)
EFFECT_CHANNELS = ("terminal", "page")             # the channels an effect may be approved from (decision D8, extended)
BRAKES = ("cancel", "set-mode")                    # never withheld from the page: cancel, and a move of a mode DOWN (the direction is checked by ops_config.set_mode)


def by_name(name: str) -> dict:
    """The row of an operation. KeyError when there is none."""
    for row in OPERATIONS:
        if row["name"] == name:
            return row
    raise KeyError(name)


def policy_groups(channel: str, policy) -> tuple:
    """The groups that apply to a channel: the project's entry, else the default of the channel, else None (the whole
    ceiling)."""
    given = (policy or {}).get(channel)
    return tuple(given) if given is not None else DEFAULT_POLICY.get(channel)


def is_read(op_name: str) -> bool:
    """Whether an operation is in the group `read`: a read, which the page and the MCP mode always keep (their policy
    must list `read`), so a shell asks nothing of the configuration for it."""
    return op_name in GROUPS["read"]["operations"]


def policy_allows(op_name: str, channel: str, policy, kind: str | None = None) -> bool:
    """Whether the channel's ceiling lists the operation and the project's groups cover it (pure), without the brakes.
    The terminal is never narrowed; a channel with no groups keeps its ceiling. For a group with a kind, the decision's
    kind must equal it (`kind` None asks whether any group covers the operation)."""
    try:
        row = by_name(op_name)
    except KeyError:
        return False
    if channel not in row["channels"]:
        return False
    if channel in NEVER_NARROWED:
        return True
    if op_name == "approve" and kind == "effect" and channel not in EFFECT_CHANNELS:
        return False
    groups = policy_groups(channel, policy)
    if groups is None:
        return True
    for name in groups:
        group = GROUPS.get(name)
        if group and op_name in group["operations"] and (group["kind"] is None or kind is None or group["kind"] == kind):
            return True
    return False


def permitted(op_name: str, channel: str, policy, kind: str | None = None) -> bool:
    """Whether a channel may call an operation under a project's policy (pure): `policy_allows`, and, on the page, the
    BRAKES whatever the policy says (cancel, and set-mode, whose direction ops_config.set_mode checks: a move down is
    never withheld, a move up needs the group). Never the only guard of an effect: an effect is approved only from
    EFFECT_CHANNELS, with its hash, and a line typed into any channel never approves one (ops.approve, ops_say)."""
    if channel == "page" and op_name in BRAKES and policy_allows(op_name, channel, None):
        return True
    return policy_allows(op_name, channel, policy, kind)


def not_enabled(name: str, channel: str) -> str:
    """The sentence of an operation the channel's ceiling lists and the project's policy does not turn on."""
    return f"/{name} is not enabled for this channel; the project's configuration (channels.{channel}) turns it on"


def refusal(op_name: str, channel: str, policy, kind: str | None = None, go_ahead: bool = False):
    """The sentence that refuses a call, or None when the channel's policy lets it through (pure; the one helper the
    page, the MCP mode, a typed line, the approve rule and the queue's drain call). `kind` is the decision's kind for
    approve; `go_ahead` is true when approve carries task keys, which needs the group `go-ahead` too (on a channel with
    a policy). The caller raises OpsError(sentence, 1). A channel with no policy entry keeps its ceiling, so this
    refuses only what the ceiling or the project's groups refuse; the terminal and the conversation are never refused."""
    if not permitted(op_name, channel, policy, kind):
        return not_enabled(op_name, channel)
    if go_ahead and channel in POLICY_CHANNELS and not permitted("go-ahead", channel, policy):
        return not_enabled("go-ahead", channel)
    return None


def permissions(channel: str, policy) -> list:
    """What the channel may do under the policy, as the names the page reads (a list in the table's order): the plain
    name of every operation the channel's row lists and `permitted` allows, except `approve` and `set-mode`, which are
    pairs: approve:plan, approve:acceptance, approve:effect, approve:go-ahead (a plan's task keys: the kind plan and the
    group go-ahead) and set-mode:down, set-mode:up. On the page cancel and set-mode:down are always there (the brakes)."""
    out = []
    for row in OPERATIONS:
        name = row["name"]
        if channel not in row["channels"]:
            continue
        if name == "approve":
            kinds = [k for k in ("plan", "acceptance", "effect") if permitted("approve", channel, policy, k)]
            out += ["approve:" + k for k in kinds]
            if "plan" in kinds and permitted("go-ahead", channel, policy):
                out.append("approve:go-ahead")
        elif name == "set-mode":
            if permitted(name, channel, policy):
                out.append("set-mode:down")
            if policy_allows(name, channel, policy):
                out.append("set-mode:up")
        elif permitted(name, channel, policy):
            out.append(name)
    return out


POSITIONAL = ("int", "str", "text")  # the kinds the conversation reads from a line


def terminal_verbs() -> tuple:
    """The verbs of the terminal shell, in the table's order."""
    return tuple(row["name"] for row in OPERATIONS if "terminal" in row["channels"])


def flag_of(arg: dict) -> str:
    """The terminal flag of an argument, without the leading dashes."""
    return arg.get("flag") or arg["name"].replace("_", "-")


def _label(arg: dict) -> str:
    return arg.get("label") or (flag_of(arg) if arg["kind"] == "int" else arg["name"])


def _usage(row: dict) -> str:
    parts = ["/" + row["name"]]
    for arg in row["args"]:
        if arg["kind"] in POSITIONAL:
            parts.append(f"<{_label(arg)}>" if arg.get("required") else f"[{_label(arg)}]")
    return " ".join(parts)


def chat_commands() -> tuple:
    """The conversation's commands, in the order of its help: {"name", "usage", "help"}. The rows that list the chat
    channel, between the conversation's own two (CHAT_OWN)."""
    own = [{"name": c["name"], "usage": "/" + c["name"] + (f" <{c['args']}>" if c["args"] else ""), "help": c["help"],
            "order": c["order"]} for c in CHAT_OWN]
    rows = [{"name": r["name"], "usage": _usage(r), "help": r["help"]} for r in OPERATIONS if "chat" in r["channels"]]
    first = [{k: v for k, v in c.items() if k != "order"} for c in own if c["order"] == "first"]
    last = [{k: v for k, v in c.items() if k != "order"} for c in own if c["order"] == "last"]
    return tuple(first + rows + last)


def chat_command_rows() -> list:
    """The conversation's commands as data, the rows `chat_help` prints, in its order: {"command": "/status", "arguments":
    "[since]" or "", "help"}. Built from `chat_commands`, the one source the help uses, so the two cannot differ."""
    return [{"command": c["usage"].split(" ", 1)[0], "arguments": c["usage"].partition(" ")[2], "help": c["help"]}
            for c in chat_commands()]


def chat_help() -> str:
    """The text the conversation shows for /help and for a line it does not understand."""
    lines = [HELP_HEAD]
    lines += [f"{c['usage']:<{HELP_WIDTH}}{c['help']}" for c in chat_commands()]
    return "\n".join(lines)


AFTER_WORD = re.compile(r"--after\s+(\d+)(?:\s+|$)")


def split_new(rest: str) -> tuple:
    """(after, text) of what follows `/new`: `--after <id>` before the text is the request this one runs after (an
    integer, digits only), else None; text is the rest."""
    found = AFTER_WORD.match(rest)
    if found is None:
        return None, rest.strip()
    return int(found.group(1)), rest[found.end():].strip()


def parse_chat(line: str):
    """One line of the conversation. None when it is not one of its commands with its arguments: the shell then shows
    the help and runs nothing. ("help", rest) and ("new", text) are the conversation's own; (name, kwargs) is an
    operation of the table that lists the chat channel, kwargs being the function's parameters. The arguments are
    read in the row's order, one word each; an integer is digits only; the last argument that is not an integer takes
    the rest of the line; anything left over, or a required argument missing, is None."""
    word, _, rest = line.partition(" ")
    if not word.startswith("/"):
        return None
    name, rest = word[1:], rest.strip()
    if name == "help":
        return ("help", rest)
    if name == "new":
        return ("new", rest) if split_new(rest)[1] else None
    try:
        row = by_name(name)
    except KeyError:
        return None
    if "chat" not in row["channels"]:
        return None
    args = [a for a in row["args"] if a["kind"] in POSITIONAL]
    kwargs = {}
    for n, arg in enumerate(args):
        if not rest:
            break
        if n == len(args) - 1 and arg["kind"] != "int":
            value, rest = rest, ""
        else:
            parts = rest.split(None, 1)
            value, rest = parts[0], (parts[1].strip() if len(parts) > 1 else "")
        if arg["kind"] == "int":
            if not (value.isascii() and value.isdigit()):
                return None
            value = int(value)
        kwargs[arg["name"]] = value
    if rest or any(a.get("required") and a["name"] not in kwargs for a in args):
        return None
    return (name, kwargs)


def started_with_uv() -> bool:
    """Whether this process was started through `uv run`: uv sets UV_RUN_RECURSION_DEPTH for what it starts (whatever
    environment it made: its cache, a project's .venv, a custom UV_CACHE_DIR); or, failing that, the interpreter lives
    in an environment uv built in its cache (a folder `builds-v<n>` or `environments-v<n>` under a folder named uv or
    under UV_CACHE_DIR). The environment variable WORKBENCH_STARTED_WITH_UV ("1" or "0") says it outright and wins."""
    marked = os.environ.get(UV_MARK)
    if marked in ("0", "1"):
        return marked == "1"
    if os.environ.get("UV_RUN_RECURSION_DEPTH"):
        return True
    prefix = os.path.realpath(sys.prefix)
    cache = os.environ.get("UV_CACHE_DIR")
    if cache and prefix.startswith(os.path.realpath(cache) + os.sep):
        return True
    parts = prefix.split(os.sep)
    return "uv" in parts and any(p.startswith(("builds-v", "environments-v")) for p in parts)


def _word(value) -> str:
    text = str(value)
    return text if re.fullmatch(r"<[^<>]*>", text) else shlex.quote(text)


def _runner(checkout, script: str, uv) -> str:
    """The start of a command: `python3 <checkout>/runtime/<script>` (the checkout's absolute path, quoted), or, with
    no checkout, the relative TERMINAL (the terminal's script only); and, for an absolute command run through uv (uv
    true, or uv None and this process started through uv), the prefix `uv run --with keyring==...`."""
    if checkout is None:
        return TERMINAL
    use_uv = started_with_uv() if uv is None else bool(uv)
    return (UV_PREFIX + " " if use_uv else "") + "python3 " + _word(os.path.join(checkout, "runtime", script))


def command_line(name: str, project: str, /, *, checkout=None, uv=None, **args) -> str:
    """The terminal's form of one operation: the one place that spells the terminal's syntax. An argument that is
    None or False is left out; a value written as <placeholder> is kept as it is. With checkout (the absolute path
    of the running checkout, which the operations layer and the service know), the command is absolute, so it runs
    from any folder, and it carries the uv prefix when this process was started through uv (or when uv is true:
    an operation that needs the secret store). Without checkout it is the relative form of a stored text."""
    row = by_name(name)
    known = {a["name"] for a in row["args"]}
    unknown = sorted(set(args) - known)
    if unknown:
        raise ValueError(f"{name} has no argument {', '.join(unknown)}")
    parts = [_runner(checkout, "cli.py", uv), name, "--project", _word(project)]
    for arg in row["args"]:
        value = args.get(arg["name"])
        if value is None or value is False:
            continue
        flag = "--" + flag_of(arg)
        if arg["kind"] == "flag":
            parts.append(flag)
        elif arg["kind"] == "pairs":
            for key, item in value.items():
                parts += [flag, _word(f"{key}={item}")]
        elif arg["kind"] == "list":
            for item in value:
                parts += [flag, _word(item)]
        else:
            parts += [flag, _word(value)]
    return " ".join(parts)


def keyring_line(username: str) -> str:
    """The command that stores a credential in the secret store, the value typed at a hidden prompt:
    `uv run --with keyring==... keyring set openhora <username>`, the username shell-quoted (a value written as
    <placeholder> is kept as it is). It needs the library, so it always goes through uv. The one place that spells it."""
    return f"{UV_PREFIX} keyring set openhora {_word(username)}"


def service_line(checkout: str, projects, *, uv=None, port=None) -> str:
    """The command that starts the local service on these project folders: `python3 <checkout>/runtime/service.py
    --project <dir> ...`, with the uv prefix when uv is true (the service needs the secret store to dispatch) or,
    when uv is None, when this process was started through uv. The one place that spells it."""
    parts = [_runner(checkout, "service.py", uv)]
    for project in projects:
        parts += ["--project", _word(project)]
    if port is not None:
        parts += ["--port", str(int(port))]
    return " ".join(parts)


POWERSHELL_QUOTES = "'\u2018\u2019\u201a\u201b"  # PowerShell reads each of these as a single quote, inside a single-quoted string too


def _plain_path(path) -> bool:
    """True for an absolute path made of text a shell and a person can read, and that JSON can carry: no control, format,
    line or paragraph separator character (a newline would end the command, an escape sequence would rewrite the screen),
    and no surrogate, private-use or unassigned code point (a folder name that is not valid UTF-8, read with
    surrogateescape, holds a lone surrogate that cannot be written out as UTF-8)."""
    if not (isinstance(path, str) and path and os.path.isabs(path)):
        return False
    if any(unicodedata.category(c) in ("Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp") for c in path):
        return False
    try:
        path.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def token_commands(path):
    """The commands that read the service's token file, one per system, or None when the path cannot be written safely
    as a command (not text, not absolute, or holding a control, format, line or paragraph separator character). They
    are the service's text for the page: the page chooses one by the browser's system and joins nothing into it.
    macos: `pbcopy < <path>` (the token goes to the clipboard); linux: `cat <path>` (it is printed in the terminal);
    powershell: `Get-Content -LiteralPath '<path>' | Set-Clipboard`. The POSIX forms quote the path with shlex.quote;
    the PowerShell form is a single-quoted literal in which every single-quote character, typographic ones included,
    is doubled. The one place that spells them."""
    if not _plain_path(path):
        return None
    literal = "".join(c * 2 if c in POWERSHELL_QUOTES else c for c in path)
    return {"macos": "pbcopy < " + shlex.quote(path), "linux": "cat " + shlex.quote(path),
            "powershell": f"Get-Content -LiteralPath '{literal}' | Set-Clipboard"}


def chat_line(name: str, /, **args) -> str:
    """The conversation's form of one command, such as `/approve 12 <hash>`; what parse_chat reads back."""
    if name == "help":
        return "/help"
    if name == "new":
        return "/new " + (f"--after {args['after']} " if args.get("after") is not None else "") + args["text"]
    row = by_name(name)
    parts = ["/" + name]
    for arg in row["args"]:
        if arg["kind"] not in POSITIONAL:
            continue
        value = args.get(arg["name"])
        if value is None:
            if arg.get("required"):
                raise ValueError(f"{name} needs {arg['name']}")
            break
        parts.append(str(value))
    return " ".join(parts)


if __name__ == "__main__":
    print(__doc__.strip())
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
