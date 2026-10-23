"""The table of operations: the one place that says what the operations layer (runtime/ops.py) offers to a shell.

A shell (the terminal's runtime/cli.py, the conversation's runtime/chat.py, the local service's runtime/service.py, the MCP
mode's runtime/mcp.py, the messaging bridge's runtime/messaging.py) derives what it accepts from
this table and spells nothing of its own: one row per operation, with its arguments, the channels that may call it
and whether it calls a model. Adding an operation adds one row here and one function in ops.py; adding a shell adds a
file. The channel rule is a column: a row lists the channels that may call it, and a row whose function takes the
channel (`channel_arg`) is told which one called it, so that code, not a prompt, refuses what a channel may not do
(an effect is approved with its hash, in the terminal or on the local page, or on a messaging app that the project's configuration grants that effect's word; never from the conversation or the MCP mode).

The channel policy (decisions M-8, M-12, M-13, POL-1, POL-2) is the second half of the file: GROUPS, GROUP_TEXT, DEFAULT_POLICY, BRAKES,
EFFECT_CHANNELS, GRANTS and the pure functions effective_groups, permitted, policy_allows, refusal and permissions. A project narrows a
channel's ceiling with named groups and widens it only by a grant of GRANTS; a policy is a named set of groups, a channel has a default
and on a messaging app each listed sender may have their own (`effective_groups(channel, cfg, sender)`). `refusal` is the one helper
every shell and the operations layer call, and contracts/runtime.md says where.

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
              {"name": "title", "kind": "str"}, {"name": "after", "kind": "int"}, {"name": "model", "kind": "str"},
              {"name": "language", "kind": "str"}),
     "channels": ("terminal", "page", "mcp"), "model": False,
     "help": "record what you want; with a flow, plan it from the flow file, else it waits for its route; with after, run it after that request; with model, run its tasks on that model (an id of the gate file, or auto); with language, write its deliverables in that language (a tag such as en or pt-BR; else the project's language setting)"},
    {"name": "route", "call": "route",
     "args": ({"name": "request_id", "kind": "int", "required": True, "flag": "request"}, {"name": "flow", "kind": "str"},
              {"name": "params", "kind": "list", "flag": "param"}),
     "channels": ("terminal", "page", "mcp"), "model": "without --flow", "job": True, "channel_arg": True, "queues": True,
     "help": "plan a request that waits for its route: one run of the router skill, or the plan of a flow file of the workbench or of the project (with --param name=value, repeated, for the flow's parameters; a file parameter names a file stage-file handed over); on the page, while a run is in progress, the request is queued"},
    {"name": "route-queued", "call": "route_queued", "args": (), "channels": ("terminal",), "model": True, "job": True,
     "help": "route the oldest queued line or request, when no run is in progress (the local service calls it every few seconds)"},
    {"name": "status", "call": "status", "args": (), "channels": ("terminal", "chat", "page", "mcp", "messaging"), "model": False,
     "help": "requests, tasks and what waits for you"},
    {"name": "task", "call": "task",
     "args": ({"name": "task_id", "kind": "int", "required": True, "flag": "task", "label": "task id"},),
     "channels": ("terminal", "page", "mcp", "messaging"), "model": False, "channel_arg": True,
     "help": "one task or request with its runs and its pending decisions"},
    {"name": "flows", "call": "flows", "args": (), "channels": ("terminal", "page", "mcp"), "model": False,
     "help": "the flows: the files of this checkout and of the project (docs/workbench/flows/), with their titles, how many tasks each holds, their parameters, step kinds and the result of the flow check"},
    {"name": "flow-check", "call": "check_flow",
     "args": ({"name": "flow", "kind": "str", "required": True},),
     "channels": ("terminal", "page", "mcp"), "model": False,
     "help": "the flow check of one flow: a task that requires the web must not receive sources; for a skill that reads a research brief the check offers the split the code makes. It writes nothing"},
    {"name": "flow-save", "call": "flow_save",
     "args": ({"name": "name", "kind": "str", "required": True},
              {"name": "pending_id", "kind": "int", "flag": "id"}, {"name": "flow", "kind": "str"}, {"name": "title", "kind": "str"},
              {"name": "split", "kind": "flag"}, {"name": "replace", "kind": "flag"}),
     "channels": ("terminal", "page"), "model": False,
     "help": "save an approved plan (--id) or a flow already there (--flow) as the flow --name of this project (docs/workbench/flows/); the flow check runs first and a finding refuses it, unless --split makes the code-made split; an existing file is replaced only with --replace"},
    {"name": "stage-file", "call": "stage_file",
     "args": ({"name": "request_id", "kind": "int", "required": True, "flag": "request", "label": "request id"},
              {"name": "file", "kind": "str", "required": True}),
     "channels": ("terminal", "page"), "model": False,
     "help": "copy one file of yours for a request that waits for its plan, so that a flow with a file parameter can name it and its plan carry the file's hash (the plan's approval moves it into the task that reads it)"},
    {"name": "config", "call": "config", "args": (), "channels": ("terminal", "page"), "model": False,
     "help": "the configuration's path and hash, whether you accepted it, the data folder, the profiles of the channels and senders, and what the file widens (the list whose hash accept-config --widen takes); it never refuses"},
    {"name": "progress", "call": "progress", "args": ({"name": "since", "kind": "str"},),
     "channels": ("terminal", "chat", "page", "mcp", "messaging"), "model": False, "chat_reply": "text",
     "help": "where the work stands and what happened (since: 7d, <n>d or YYYY-MM-DD)"},
    {"name": "pending", "call": "pending",
     "args": ({"name": "pending_id", "kind": "int", "flag": "id"},),
     "channels": ("terminal", "chat", "page", "mcp", "messaging"), "model": False, "channel_arg": True,
     "help": "what waits for you; with an id, that decision whole (the MCP mode and a messaging reader without the group ask-mail do not see the current text of an event a calendar card shows, nor the addresses, the subject, the text and the attachment names of an e-mail card)"},
    {"name": "answer", "call": "answer_proposing",
     "args": ({"name": "pending_id", "kind": "int", "required": True, "flag": "id"},
              {"name": "text", "kind": "text", "required": True},
              {"name": "with_comments", "kind": "flag", "flag": "with-comments"}),
     "channels": ("terminal", "chat", "page", "mcp", "messaging"), "model": False, "channel_arg": True,
     "help": "answer a pending decision; the answer to a question may come back with a proposal (instruction_proposal) to add your own line to the project's instructions, which is added only by instructions-add, from the terminal or the page"},
    {"name": "release", "call": "release",
     "args": ({"name": "pending_id", "kind": "int", "required": True, "flag": "id"},),
     "channels": ("terminal", "chat", "page", "mcp", "messaging"), "model": False, "channel_arg": True, "job": True,
     "help": "release a delivery (it stays a draft)"},
    {"name": "approve", "call": "approve",
     "args": ({"name": "pending_id", "kind": "int", "required": True, "flag": "id"}, {"name": "sha256", "kind": "str"},
              {"name": "go_ahead", "kind": "list", "flag": "go-ahead"}),
     "channels": ("terminal", "chat", "page", "messaging"), "model": False, "channel_arg": True, "job": True,
     "help": "approve a plan or an acceptance (a plan: --go-ahead <task key>, repeated, drops that task's derived waits); an effect is approved with its hash, in the terminal, on the page, or on a messaging app the project grants that effect's word (from a card that carried the whole text)"},
    {"name": "reject", "call": "reject",
     "args": ({"name": "pending_id", "kind": "int", "required": True, "flag": "id"}, {"name": "note", "kind": "str"}),
     "channels": ("terminal", "chat", "page", "messaging"), "model": False, "channel_arg": True,
     "help": "reject a plan, an acceptance or an effect"},
    {"name": "retry", "call": "retry",
     "args": ({"name": "task_id", "kind": "int", "required": True, "flag": "task", "label": "task id"},),
     "channels": ("terminal", "chat", "page", "messaging"), "model": False, "channel_arg": True,
     "help": "make a failed or blocked task ready again"},
    {"name": "go-ahead", "call": "go_ahead",
     "args": ({"name": "task_id", "kind": "int", "required": True, "flag": "task", "label": "task id"},
              {"name": "drop_after", "kind": "flag", "flag": "drop-after"}),
     "channels": ("terminal", "page"), "model": False,
     "help": "go ahead on a task that waits for another request's task: its derived waits end (with drop-after, its after wait)"},
    {"name": "cancel", "call": "cancel",
     "args": ({"name": "request_id", "kind": "int", "required": True, "flag": "request", "label": "request id"},),
     "channels": ("terminal", "chat", "page", "messaging"), "model": False, "channel_arg": True,
     "help": "cancel a request at any moment, even while a task of it runs: the run is ended and returns nothing, what it used so far is spent"},
    {"name": "stop-task", "call": "stop_task",
     "args": ({"name": "task_id", "kind": "int", "required": True, "flag": "task", "label": "task id"},),
     "channels": ("terminal", "chat", "page", "messaging"), "model": False, "channel_arg": True,
     "help": "stop one running task: its run is ended and returns nothing, the task is blocked, and retry resumes it"},
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
     "help": "run one named step task in this process, no model: what the dispatcher starts (with --unattended, which asks again for the brake and the kind's flag) for a step task of a kind it may start on its own (ingest, and the kinds that follow); a flow can hold a step task since P6a"},
    {"name": "accept-config", "call": "accept_config",
     "args": ({"name": "sha256", "kind": "str", "required": True},
              {"name": "adopt_sources", "kind": "flag", "flag": "adopt-sources"},
              {"name": "widen", "kind": "str"}),
     "channels": ("terminal",), "model": False,
     "help": "record the hash of runtime.json you accept; --adopt-sources also lets this project take over a sources folder marked for another; a file that gives a channel or a listed sender a group the accepted file did not effectively give it (a grant, a group such as release or retry, a sender moved to a wider profile) is accepted only with --widen <the sha256 of the widening list that config shows>"},
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
    {"name": "ask", "call": "ask", "args": ({"name": "text", "kind": "text", "required": True},),
     "channels": ("terminal", "chat", "page", "messaging"), "model": True, "job": True, "channel_arg": True, "chat_reply": "reply",
     "help": "answer a question from the text of the project's sources, with the quotes it rests on and the sources and versions read: one run of the answer skill, no plan to approve; the sources are chosen by code (@<id> to name them), the answer goes only to the shell or chat that asked; never the MCP mode, and on a messaging app only for a sender whose profile lists the group ask"},
    {"name": "agents", "call": "agents", "args": (), "channels": ("terminal", "page", "mcp", "messaging"), "model": False,
     "help": "each area agent: its mode, its caps, what it used today and how many tasks wait for it"},
    {"name": "conversation", "call": "conversation",
     "args": ({"name": "conversation", "kind": "str"}, {"name": "after", "kind": "int"}),
     "channels": ("terminal", "page", "mcp"), "model": False, "channel_arg": True,
     "help": "the messages of the project's conversation above a message id, oldest first; the answer to a /ask is shown only to the channel that asked"},
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
              {"name": "source_type", "kind": "choice", "choices": ("file", "notion", "drive", "onedrive", "mail", "calendar"), "required": True, "flag": "type"},
              {"name": "origin", "kind": "str", "required": True},
              {"name": "description", "kind": "str"}),
     "channels": ("terminal", "page"), "model": False, "channel_arg": True,
     "help": "register a source of this project: its id, its type (file, notion, drive, onedrive, mail or calendar) and its origin (a file's name, a Notion page's address or id, a Drive file's id, a OneDrive file's <drive id>/<item id>, or the closed line of a mail or calendar window; a OneDrive, mail or calendar source is registered only from the terminal); nothing is imported and no credential is kept"},
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
    {"name": "source-onedrive", "call": "source_onedrive",
     "args": ({"name": "search", "kind": "str"}, {"name": "folder", "kind": "str"}, {"name": "item", "kind": "list"},
              {"name": "source_id", "kind": "str", "flag": "source", "label": "source id"},
              {"name": "description", "kind": "str"}),
     "channels": ("terminal",), "model": False,
     "help": "make OneDrive files sources: --search <text> or --folder <path> lists up to 25 candidates (name, folder, size, date and the <drive id>/<item id>) and registers nothing; --item <drive id>/<item id>, repeated for several files, makes each chosen file a source and imports its first version (never a folder)"},
    {"name": "source-mail", "call": "source_mail",
     "args": ({"name": "source_id", "kind": "str", "required": True, "flag": "source", "label": "source id"},
              {"name": "origin", "kind": "str"}, {"name": "description", "kind": "str"}),
     "channels": ("terminal",), "model": False,
     "help": "a window of your mailbox as a source (terminal only): --origin gmail:box=<inbox|important|starred|unread>;days=<1-31>;max=<1-100> (or outlook:box=<inbox|unread>;...) registers the source and reads its first snapshot; with no origin, a source already registered is read again; each snapshot is a dated version with the links replaced and every message scanned for credentials, never read by a run"},
    {"name": "source-calendar", "call": "source_calendar",
     "args": ({"name": "source_id", "kind": "str", "required": True, "flag": "source", "label": "source id"},
              {"name": "origin", "kind": "str"}, {"name": "description", "kind": "str"}),
     "channels": ("terminal",), "model": False,
     "help": "one calendar's window as a source (terminal only): --origin google:calendar=<id>;past=<0-7>;ahead=<0-31> (or outlook:calendar=<default|id>;...) registers the source and reads its first snapshot; with no origin, a source already registered is read again; each snapshot is a dated version of the events (no description, no attendee), never read by a run"},
    {"name": "source-describe", "call": "source_describe",
     "args": ({"name": "source_id", "kind": "str", "required": True, "flag": "source", "label": "source id"},
              {"name": "description", "kind": "str"}),
     "channels": ("terminal", "page"), "model": False,
     "help": "set your description of a source (what it is, what it is for); the planner reads it with the catalog; an empty one clears it"},
    {"name": "sources", "call": "sources_catalog", "args": (), "channels": ("terminal", "page", "mcp", "messaging"), "model": False,
     "help": "the catalog of the project's sources: each source, its newest version (name, type, size, date, sheets and columns with sample values, first headings), your description and whether its files changed outside the runtime"},
    {"name": "attachments", "call": "attachments", "args": (), "channels": ("terminal", "chat", "page", "messaging"), "model": False, "channel_arg": True,
     "help": "the files people sent through a messaging app (from a messaging app, only the ones you sent): those held for your answer (name, kind, size, the source each would become, when it expires), the latest decisions, the day's count and the limits; a held file is in the data folder, never in a run, a prompt or the sources folder"},
    # NR-5 (Q6): the numbered items of the mail and calendar snapshots, so that "the e-mail 3" has something to point to on a phone. Private: the terminal and the page, and a
    # messaging sender only with the group ask-mail (the operation asks item_refs.may_read); never on the MCP mode.
    {"name": "items", "call": "items",
     "args": ({"name": "kind", "kind": "choice", "choices": ("mail", "calendar")}, {"name": "source", "kind": "str"}),
     "channels": ("terminal", "page", "messaging"), "model": False, "channel_arg": True,
     "help": "the numbered items of the newest snapshot of each mail or calendar source (--kind mail|calendar and --source <id> narrow it): a message by its sender and subject, an event by its line, numbered as the references <source>#<n> number them; a messaging sender needs the group ask-mail; nothing is called and nothing is written"},
    {"name": "attachment-hold", "call": "attachment_hold",
     "args": ({"name": "incoming", "kind": "str", "required": True},
              {"name": "platform", "kind": "str", "required": True, "flag": "messenger-platform"},
              {"name": "ref", "kind": "str", "required": True}, {"name": "name", "kind": "str", "required": True},
              {"name": "declared_type", "kind": "str", "flag": "declared-type"}, {"name": "declared_bytes", "kind": "int", "flag": "declared-bytes"},
              {"name": "target", "kind": "str"}, {"name": "direct", "kind": "flag"},
              {"name": "max_bytes", "kind": "int", "flag": "max-bytes"}, {"name": "failed", "kind": "str"},
              {"name": "fetched_bytes", "kind": "int", "flag": "fetched-bytes"}),
     "channels": ("messaging",), "model": False, "channel_arg": True,
     "help": "the messaging bridge's call after it fetched a file into an incoming folder it made: the intake bounds it, reads its type from its bytes and hashes it, and it is kept for your answer; with the grant add-sources-direct a file for a new source is added at once; with failed, a fetch that ended with no file is recorded so that it counts against the day"},
    {"name": "attachment-add", "call": "attachment_add",
     "args": ({"name": "attachment_id", "kind": "int", "required": True, "flag": "id", "label": "id"},),
     "channels": ("terminal", "page", "messaging"), "model": False, "channel_arg": True,
     "help": "add a held file as a source of the project, or as the next version of the source it names: converted in a container with no network, scanned for credentials, kept as an immutable version with where it came from (never who sent it); the held file is deleted whatever the result"},
    {"name": "attachment-discard", "call": "attachment_discard",
     "args": ({"name": "attachment_id", "kind": "int", "required": True, "flag": "id", "label": "id"},),
     "channels": ("terminal", "page", "messaging"), "model": False, "channel_arg": True,
     "help": "delete a held file without adding it (from a messaging app, only a file you sent, and only by the answer to its card: /add and /discard)"},
    {"name": "remind", "call": "remind",
     "args": ({"name": "when", "kind": "str", "required": True, "label": "HH:MM | YYYY-MM-DD HH:MM | in <n>m|h|d"},
              {"name": "text", "kind": "text", "required": True}, {"name": "to", "kind": "str", "label": "platform:id"}),
     "channels": ("terminal", "page", "messaging"), "model": False, "channel_arg": True,
     "help": "make a reminder: a line of your own words that the messaging bridge sends once, at that time, to the chat of a listed sender, with no model in between (--when HH:MM is today or, when past, tomorrow; YYYY-MM-DD HH:MM; in <n>m|h|d; the machine's local time; 1 minute to 366 days ahead; --text up to 300 characters, refused if it looks like a credential); --to names the listed sender it goes to (from a messaging app it is always the sender who asks); never an effect (limit L51), off for a messaging app until the project's configuration lists the group reminders; at most 100 wait in a project, 30 for one chat, and 30 are made for one chat in a day"},
    {"name": "reminders", "call": "reminders_read", "args": (), "channels": ("terminal", "page", "messaging"), "model": False, "channel_arg": True,
     "help": "the reminders that wait and the ones that did not go out in the last 7 days (missed: the bridge was down more than 6 hours past the time; dropped: the sender was removed or lost the group before it fired); from a messaging app only the ones made for you, and no text when the project's notices are `count`"},
    {"name": "reminder-forget", "call": "reminder_forget",
     "args": ({"name": "reminder_id", "kind": "int", "required": True, "flag": "id", "label": "id"},),
     "channels": ("terminal", "page", "messaging"), "model": False, "channel_arg": True,
     "help": "cancel a reminder that waits (from a messaging app, only one made for you: /forget); one that is being sent or has ended is not changed"},
    {"name": "reminder-restore", "call": "reminder_restore",
     "args": ({"name": "reminder_id", "kind": "int", "flag": "id", "label": "id"},),
     "channels": ("terminal", "page", "messaging"), "model": False, "channel_arg": True,
     "help": "bring back a reminder cancelled in the last 10 minutes, as a new one with the same words, time and chat (from a messaging app: the last one you cancelled, asked as `undo`; the terminal and the page may name one with --id); not when its time is less than a minute away, and not when it is already back"},
    # W4a: files in the person's own Drive or OneDrive. Each prepares one change as an effect card of the exact content and writes nothing until the person approves
    # its hash (limit L55); in no default policy (the group files-write is listed by a profile and confirmed with accept-config --widen); never on the MCP mode.
    {"name": "file-create", "call": "file_create",
     "args": ({"name": "account", "kind": "choice", "choices": ("google", "microsoft"), "required": True},
              {"name": "file_name", "kind": "str", "required": True, "flag": "name"},
              {"name": "content", "kind": "str"}, {"name": "content_file", "kind": "file", "flag": "content-file"},
              {"name": "from_path", "kind": "str", "flag": "from"}, {"name": "folder", "kind": "str"}),
     "channels": ("terminal", "page", "messaging"), "model": False, "channel_arg": True,
     "help": "prepare a NEW file in a folder of your Google Drive (account google) or OneDrive (account microsoft) and ask for the approval of its card: --name ends in .md, .txt or .docx (or .gdoc for a Google Doc made from Markdown text); give the text (--content or --content-file, at most 64 KiB) or a file of the project (--from docs/<path>); --folder is a name the project lists under accounts.<account>.folders (default: the one named default); a file of that name in the folder is refused, a new file never replaces one; nothing is written until you approve the card's hash"},
    {"name": "file-replace", "call": "file_replace",
     "args": ({"name": "account", "kind": "choice", "choices": ("google", "microsoft"), "required": True},
              {"name": "file", "kind": "str", "required": True},
              {"name": "content", "kind": "str"}, {"name": "content_file", "kind": "file", "flag": "content-file"},
              {"name": "from_path", "kind": "str", "flag": "from"}),
     "channels": ("terminal", "page", "messaging"), "model": False, "channel_arg": True,
     "help": "prepare a NEW REVISION of a file that is a source of the project (--file is its source id; it must be a file of that account and its source must be up to date: refresh it first) and ask for the approval of its card, which shows the revision it replaces; the previous revision stays in the service's history; give the text (--content or --content-file) or a file of the project of the same type (--from docs/<path>); nothing is written until you approve the card's hash, and not if the file moved since it was read"},
    {"name": "file-save", "call": "file_save",
     "args": ({"name": "account", "kind": "choice", "choices": ("google", "microsoft"), "required": True},
              {"name": "attachment", "kind": "int", "required": True, "label": "id"},
              {"name": "file_name", "kind": "str", "flag": "name"}, {"name": "folder", "kind": "str"}),
     "channels": ("terminal", "page", "messaging"), "model": False, "channel_arg": True,
     "help": "prepare the saving of a file someone sent through a messaging app (--attachment is the number of a held file, see attachments) in a folder of your Drive or OneDrive, named as it was sent or by --name, and ask for the approval of its card, which names the file, its size and its hash; from a messaging app, only a file you sent, approved only by you; the held file stays held (add or discard it as before)"},
    # S8: the text of one file, found by its name in the folders the project lists under `accounts.<account>.folders`. A read: nothing is written, nothing is sent to a model, and the
    # text is shown to the channel that asked and kept nowhere. The group read-files is in no default policy and never on the MCP mode (no row lists it).
    {"name": "file-read", "call": "file_read",
     "args": ({"name": "file", "kind": "str", "required": True},
              {"name": "account", "kind": "choice", "choices": ("google", "microsoft")}),
     "channels": ("terminal", "page", "messaging"), "model": False, "channel_arg": True,
     "help": "show the text of a file of your Google Drive (account google) or OneDrive (account microsoft), found by its name (case, accents and the extension do not matter) among the direct contents of the folders the project lists under accounts.<account>.folders in runtime.json, and in no other folder; without --account both accounts are searched. One match is read and its text shown (at most 3,500 characters, then how many remain); several are listed to choose from; none says which folders were searched. Nothing is written or sent to a model; from a messaging app the sender needs the group read-files"},
    # R2-F1: a question of general information (the weather, a price, the news, a fact) answered by a web search. One run of the skill core-research with web access, chosen by code, outside any
    # area agent's pack; the question and the answer's links pass a web search service and the model that runs it. The group research is in no default policy; never on the page or the MCP mode.
    {"name": "research", "call": "research",
     "args": ({"name": "question", "kind": "str", "required": True},),
     "channels": ("terminal", "messaging"), "model": True, "job": True, "channel_arg": True,
     "help": "answer a question of general information (the weather, a price or quote, the news, a fact) from a web search: one run of the research skill with web access, at most the project's research cost per run (research.max_cost_usd), time (research.timeout_seconds) and runs per day (research.max_per_day); the question is sent to a web search service and to the model that runs it (no file of the project and none of the standing instructions are); a question that names the person's own calendar, mail, files or folders (\"my calendar\") does not run; the reply is the answer in plain words with its sources as links, stored as a neutral word; the run folder keeps the prompt (the question) and the brief for run_retention_days, outside git; from a messaging app the sender needs the group research"},
    {"name": "instructions", "call": "instructions_read", "args": (), "channels": ("terminal", "page", "mcp", "messaging"), "model": False,
     "help": "the project's standing instructions (docs/workbench/instructions.md, written only by you): whether the file is there, its sha256, its characters against the cap, the problem that would stop a run, and the text; every model run of the project receives it in its prompt, and it never replaces a skill's stop rule, a confirmation gate or an approval"},
    {"name": "instructions-set", "call": "instructions_set",
     "args": ({"name": "text", "kind": "text", "required": True},
              {"name": "base_sha256", "kind": "str", "required": True, "flag": "base-sha256", "label": "sha256 or none"}),
     "channels": ("terminal", "page"), "model": False, "channel_arg": True,
     "help": "replace the whole text of the project's standing instructions (--text or --text-file; an empty text clears them); --base-sha256 is the sha256 you read (none for a file that is not there), and a file that changed since is never overwritten; by default only the terminal and the page write it (limit L40; `INSTRUCTIONS_CHANNELS`; no policy of today widens it)"},
    {"name": "instructions-add", "call": "instructions_add",
     "args": ({"name": "line", "kind": "str", "required": True}, {"name": "base_sha256", "kind": "str", "required": True, "flag": "base-sha256", "label": "sha256 or none"}),
     "channels": ("terminal", "page"), "model": False, "channel_arg": True,
     "help": "append one line `- <text>` to the project's standing instructions; --base-sha256 is the sha256 you read (none for a file that is not there); by default only the terminal and the page write it (limit L40; `INSTRUCTIONS_CHANNELS`; no policy of today widens it)"},
    {"name": "routines", "call": "routines_read", "args": ({"name": "routine_id", "kind": "int", "flag": "id"},),
     "channels": ("terminal", "page", "mcp", "messaging"), "model": False,
     "help": "the routines (a flow started by a schedule): state, schedule, the hash of the content now against the approved one, the last fire; with an id, its fires and what approving it needs"},
    {"name": "routine-create", "call": "routine_create",
     "args": ({"name": "name", "kind": "str", "required": True}, {"name": "flow", "kind": "str", "required": True}, {"name": "params", "kind": "list", "flag": "param"},
              {"name": "every", "kind": "choice", "choices": ("day", "week", "minutes")}, {"name": "at", "kind": "str"},
              {"name": "weekday", "kind": "int"}, {"name": "minutes", "kind": "int"}, {"name": "model", "kind": "str"},
              {"name": "providers", "kind": "list", "flag": "provider"}, {"name": "window_seconds", "kind": "int", "flag": "window-seconds"},
              {"name": "consent", "kind": "flag"}, {"name": "warning_sha256", "kind": "str", "flag": "warning-sha256"}),
     "channels": ("terminal", "page", "messaging"), "model": False, "channel_arg": True,
     "help": "create a routine as a draft: --flow a flow, --param name=value its fixed arguments, --every day|week|minutes with --at HH:MM, --weekday, --minutes, --model (an id, auto, or the project's default), --provider (the approved set for auto), --window-seconds (the catch-up window, default its period), --consent (terminal; the page sends the hash of the warning) for a fixed model with no evidence; nothing fires until routine-approve; from messaging only when the project's `channels.messaging` lists routine-edit, and never for a flow with a networked script or one a standing policy covers"},
    {"name": "routine-change", "call": "routine_change",
     "args": ({"name": "routine_id", "kind": "int", "required": True, "flag": "id"}, {"name": "flow", "kind": "str"}, {"name": "params", "kind": "list", "flag": "param"},
              {"name": "every", "kind": "choice", "choices": ("day", "week", "minutes")}, {"name": "at", "kind": "str"},
              {"name": "weekday", "kind": "int"}, {"name": "minutes", "kind": "int"}, {"name": "model", "kind": "str"},
              {"name": "providers", "kind": "list", "flag": "provider"}, {"name": "window_seconds", "kind": "int", "flag": "window-seconds"},
              {"name": "consent", "kind": "flag"}, {"name": "warning_sha256", "kind": "str", "flag": "warning-sha256"}),
     "channels": ("terminal", "page", "messaging"), "model": False, "channel_arg": True,
     "help": "change a routine: what is given replaces what is there; its approval is cleared and it is a draft until routine-approve; a change of the model clears the consent"},
    {"name": "routine-approve", "call": "routine_approve",
     "args": ({"name": "routine_id", "kind": "int", "required": True, "flag": "id"}, {"name": "sha256", "kind": "str"}),
     "channels": ("terminal", "page"), "model": False,
     "help": "approve a routine by the sha256 of its exact content (schedule, flow template and fixed arguments, skill versions X.Y, eval image, model and consent, providers, and the sha256 of the project's instructions when the file is there): without --sha256 the preview and the hash; a stopped routine is approved again the same way"},
    {"name": "routine-pause", "call": "routine_pause", "args": ({"name": "routine_id", "kind": "int", "required": True, "flag": "id"},),
     "channels": ("terminal", "page", "messaging"), "model": False, "channel_arg": True, "help": "pause an active routine: nothing fires while it is paused, and the slots it passes are not made up"},
    {"name": "routine-resume", "call": "routine_resume", "args": ({"name": "routine_id", "kind": "int", "required": True, "flag": "id"},),
     "channels": ("terminal", "page"), "model": False, "help": "resume a paused routine; its approval stands and every fire still compares the hash"},
    {"name": "routine-cancel", "call": "routine_cancel", "args": ({"name": "routine_id", "kind": "int", "required": True, "flag": "id"},),
     "channels": ("terminal", "page", "messaging"), "model": False, "help": "cancel a routine for good (it is never deleted; its fires stay on record)"},
    # W1: the person's own calendar (SPEC-SECRETARY-WRITES 3.1). Each one PREPARES a card and writes nothing: the event is written when its card is approved with its hash
    # (limit L55). Off for a messaging app until a profile lists the group calendar-write; never on the MCP mode.
    {"name": "event-create", "call": "event_create",
     "args": ({"name": "account", "kind": "choice", "choices": ("google", "microsoft"), "required": True},
              {"name": "title", "kind": "str", "required": True},
              {"name": "start", "kind": "str", "required": True, "label": "YYYY-MM-DDTHH:MM | YYYY-MM-DD"},
              {"name": "end", "kind": "str", "label": "YYYY-MM-DDTHH:MM | YYYY-MM-DD"},
              {"name": "calendar", "kind": "str"}, {"name": "location", "kind": "str"},
              {"name": "reminder_minutes", "kind": "int", "flag": "reminder-minutes"}, {"name": "notes", "kind": "str"}),
     "channels": ("terminal", "page", "messaging"), "model": False, "channel_arg": True,
     "help": "prepare a new event on a calendar of your own Google or Microsoft account and stop at a card that asks you to approve it (nothing is written until you do, with its hash): --start and --end are YYYY-MM-DDTHH:MM in this machine's zone or YYYY-MM-DD for an all-day event (the end defaults to an hour after the start, or the same day); --calendar is a name of the account's calendars in runtime.json (the first when absent); nobody is invited and no e-mail is sent; no recurrence"},
    {"name": "event-change", "call": "event_change",
     "args": ({"name": "account", "kind": "choice", "choices": ("google", "microsoft"), "required": True},
              {"name": "event", "kind": "str", "required": True, "label": "<source>#<n> | created:<decision>"},
              {"name": "calendar", "kind": "str"}, {"name": "title", "kind": "str"}, {"name": "start", "kind": "str", "label": "YYYY-MM-DDTHH:MM | YYYY-MM-DD"},
              {"name": "end", "kind": "str", "label": "YYYY-MM-DDTHH:MM | YYYY-MM-DD"}, {"name": "location", "kind": "str"},
              {"name": "reminder_minutes", "kind": "int", "flag": "reminder-minutes"}, {"name": "notes", "kind": "str"}),
     "channels": ("terminal", "page", "messaging"), "model": False, "channel_arg": True, "job": True,
     "help": "prepare a change to an event of your own calendar and stop at a card that shows each part as it was and as it will be (nothing is written until you approve it with its hash, and only if the event is still as it was read): only an event you organize with no other attendee and no recurrence; a start alone moves the event and keeps its length; --event is <source>#<n> (the n-th item of a calendar snapshot) or created:<decision> and the calendar is the one it is on (--calendar names it; another one is refused); nobody is told"},
    {"name": "event-cancel", "call": "event_cancel",
     "args": ({"name": "account", "kind": "choice", "choices": ("google", "microsoft"), "required": True},
              {"name": "event", "kind": "str", "required": True, "label": "<source>#<n> | created:<decision>"}, {"name": "calendar", "kind": "str"}),
     "channels": ("terminal", "page", "messaging"), "model": False, "channel_arg": True, "job": True,
     "help": "prepare the removal of an event of your own calendar and stop at a card (nothing is removed until you approve it with its hash, and only if the event is still as it was read): only an event you organize with no other attendee and no recurrence; Google is expected to move it to the calendar's trash for 30 days (to verify live); on Outlook this is not available yet; nobody is told"},
    # W2: an e-mail from the person's own account (SPEC-SECRETARY-WRITES 3.2). Each one PREPARES a card and sends nothing: the e-mail is sent when its card is approved with its
    # hash (limits L55 and L42). Off for a messaging app until a profile lists the group mail-send; never on the MCP mode.
    {"name": "mail-send", "call": "mail_send",
     "args": ({"name": "account", "kind": "choice", "choices": ("google", "microsoft"), "required": True},
              {"name": "to", "kind": "str", "required": True, "label": "a@x.example[,b@y.example]"}, {"name": "cc", "kind": "str"}, {"name": "bcc", "kind": "str"},
              {"name": "subject", "kind": "str", "required": True}, {"name": "text", "kind": "text", "required": True}, {"name": "attach", "kind": "list"}),
     "channels": ("terminal", "page", "messaging"), "model": False, "channel_arg": True,
     "help": "prepare an e-mail from your own Google or Microsoft account and stop at a card that shows the whole e-mail (nothing is sent until you approve the card with its hash): --text or --text-file is the body; --to, --cc and --bcc are plain comma-separated addresses, at most 20 in all (a Google account sends no Bcc in this version); --attach is a file under docs/ (repeat it), and an e-mail with a file is approved in the terminal or on the page, never on a messaging card; the sender is the address of the account in runtime.json (the key accounts); it is sent once"},
    {"name": "mail-reply", "call": "mail_reply",
     "args": ({"name": "account", "kind": "choice", "choices": ("google", "microsoft"), "required": True},
              {"name": "message", "kind": "str", "required": True, "label": "<source>#<n>"}, {"name": "text", "kind": "text", "required": True}),
     "channels": ("terminal", "page", "messaging"), "model": False, "channel_arg": True,
     "help": "prepare a reply to a message of a mail snapshot and stop at a card (nothing is sent until you approve the card with its hash): --message is <source>#<n>, the n-th message of the newest snapshot of a mail source of that account; --text or --text-file is the body; the reply goes to the sender of that message and to no one else (a Reply-To is shown on the card and not used; there is no reply to all), with the subject after Re:, in the message's conversation; from a messaging app the sender also needs the group ask-mail to name a message"},
    # W3: the person's own mailbox (SPEC-SECRETARY-WRITES 3.3). Each one PREPARES a card and writes nothing: the change is made when its card is approved with its hash
    # (limit L55); nothing is sent and nothing is deleted for good. `messages` is references <source id>#<n> to the messages of a mail snapshot, comma-separated. Off for a
    # messaging app until a profile lists the group mail-organize; never on the MCP mode.
    {"name": "mail-draft", "call": "mail_draft",
     "args": ({"name": "account", "kind": "choice", "choices": ("google", "microsoft"), "required": True},
              {"name": "to", "kind": "str"}, {"name": "cc", "kind": "str"}, {"name": "bcc", "kind": "str"}, {"name": "subject", "kind": "str"},
              {"name": "body", "kind": "str", "required": True}, {"name": "message", "kind": "str", "label": "<source>#<n>"}),
     "channels": ("terminal", "page", "messaging"), "model": False, "channel_arg": True, "job": True,
     "help": "prepare a draft in your own mailbox and stop at a card that shows it whole (nothing is saved until you approve it with its hash, and it is NEVER sent): a new one (--to, --subject, --body; --cc and --bcc optional; comma-separated plain addresses, at most 20 in all) or a reply (--message <source>#<n> and --body: it goes to that message's sender, never to its Reply-To)"},
    {"name": "mail-archive", "call": "mail_archive",
     "args": ({"name": "account", "kind": "choice", "choices": ("google", "microsoft"), "required": True}, {"name": "messages", "kind": "str", "required": True, "label": "<source>#<n>,..."}),
     "channels": ("terminal", "page", "messaging"), "model": False, "channel_arg": True, "job": True,
     "help": "prepare taking 1 to 20 messages out of the inbox (Gmail: the label INBOX is removed; Outlook: they move to the Archive folder) and stop at a card that lists each one by its subject and sender as the mailbox holds them now (nothing changes until you approve it with its hash, and only if every message is still as listed); --messages are references <source>#<n> to the messages of a mail snapshot"},
    {"name": "mail-move", "call": "mail_move",
     "args": ({"name": "account", "kind": "choice", "choices": ("google", "microsoft"), "required": True}, {"name": "messages", "kind": "str", "required": True, "label": "<source>#<n>,..."}, {"name": "folder", "kind": "str", "required": True}),
     "channels": ("terminal", "page", "messaging"), "model": False, "channel_arg": True, "job": True,
     "help": "prepare moving 1 to 20 messages to a mail folder or label (--folder is a name of the account's mail_folders in runtime.json; no other folder is written to) and stop at a card that lists each message (nothing changes until you approve it with its hash, and only if every message is still as listed)"},
    {"name": "mail-mark", "call": "mail_mark",
     "args": ({"name": "account", "kind": "choice", "choices": ("google", "microsoft"), "required": True}, {"name": "messages", "kind": "str", "required": True, "label": "<source>#<n>,..."}, {"name": "state", "kind": "choice", "choices": ("read", "unread"), "required": True}),
     "channels": ("terminal", "page", "messaging"), "model": False, "channel_arg": True, "job": True,
     "help": "prepare marking 1 to 20 messages as read or unread and stop at a card that lists each message (nothing changes until you approve it with its hash, and only if every message is still as listed)"},
    {"name": "mail-trash", "call": "mail_trash",
     "args": ({"name": "account", "kind": "choice", "choices": ("google", "microsoft"), "required": True}, {"name": "messages", "kind": "str", "required": True, "label": "<source>#<n>,..."}),
     "channels": ("terminal", "page", "messaging"), "model": False, "channel_arg": True, "job": True,
     "help": "prepare moving 1 to 20 messages to the trash (Gmail empties it after 30 days; Outlook empties Deleted Items after 30 days; this code deletes nothing) and stop at a card that lists each message (nothing moves until you approve it with its hash, and only if every message is still as listed)"},
)

# What the conversation answers itself, with no operation: the help, and a new request whatever is open.
CHAT_OWN = (
    {"name": "help", "args": "", "help": "list the commands", "order": "first"},
    {"name": "new", "args": "text", "help": "start a new request, whatever is open (--after <id> before the text: run it after that request)", "order": "last"},
)

# The channel policy (decisions M-8, M-12, M-13). The `channels` column of the table is the ceiling of a channel; a
# project's runtime.json (`channels.<channel>`, a list of these group names) narrows it, and widens it only by a grant (GRANTS). A group names
# the operations it covers, and, for `approve`, the kind of decision (a group with no kind covers every kind its
# operations take). Every operation that the page, the MCP mode or the messaging channel may call is in exactly one group
# (a test walks the table). A group is valid on a channel when one of its operations is in that channel's ceiling; it then
# covers the ceiling's share of it. Pure literals, like the table.
GROUPS = {
    "read": {"operations": ("status", "progress", "pending", "task", "agents", "costs", "skills", "artifacts", "artifact",
                            "flows", "flow-check", "routines", "instructions", "conversation", "connections", "version", "config", "commands", "artifact-raw", "items"),
             "kind": None},
    # POL-2: what a limited reader sees on a messaging app: `read` without the spend (costs, agents' caps and spend), the connections and
    # the configuration, and without `task` and `progress`, which carry a run's cost. A profile lists `read` or `read-limited`, not both.
    "read-limited": {"operations": ("status", "pending", "skills", "artifacts", "artifact", "flows", "flow-check", "routines",
                                    "instructions", "conversation", "version", "commands", "artifact-raw"), "kind": None},
    "talk": {"operations": ("say",), "kind": None},
    "answer": {"operations": ("answer",), "kind": None},
    "release": {"operations": ("release",), "kind": None},
    "request": {"operations": ("request", "route"), "kind": None},
    "approve-plans": {"operations": ("approve",), "kind": "plan"},
    "approve-acceptances": {"operations": ("approve",), "kind": "acceptance"},
    "approve-effects": {"operations": ("approve",), "kind": "effect"},   # the umbrella: every word, on the page alone; a messaging app takes the per-word groups below, as grants
    "approve-effect-create": {"operations": ("approve",), "kind": "effect:create"},       # a pull request (effect_pull_request.py)
    "approve-effect-write": {"operations": ("approve",), "kind": "effect:write"},         # a write to the documents platform (effect_write.py)
    "approve-effect-send-own": {"operations": ("approve",), "kind": "effect:send-own"},      # an e-mail from the person's own account (effect_send.approval_word; its own grant, decision of 2026-10-19)
    "approve-effect-send": {"operations": ("approve",), "kind": "effect:send"},           # an e-mail from the project's outbox (effect_send.py APPROVAL_GROUP)
    "approve-effect-publish": {"operations": ("approve",), "kind": "effect:publish"},     # a post (effect_publish.py APPROVAL_GROUP)
    "approve-networked-plans": {"operations": ("approve",), "kind": "plan:networked"},    # a plan that holds a step reaching the network (P9, limit L36): on top of approve-plans
    "ask": {"operations": ("ask",), "kind": None},   # an answer from the full text of the project's sources: in no default (a messaging sender gets it only from a profile or channel entry accepted with --widen), never on the MCP mode
    # NR-2 (the maintainer's decision of 2026-10-18, superseding the RT-1 rule for its holders): the sender may ask about the mail and calendar sources of the project from a
    # messaging app, and those sources join the automatic selection of their questions. It adds a capability to `ask` and never grants `ask` (KIND_ONLY): a profile lists both.
    # In no default; the accepted file widens it only with accept-config --widen like every other group.
    "ask-mail": {"operations": ("ask",), "kind": "mail"},
    "go-ahead": {"operations": ("go-ahead",), "kind": None},
    "reject-cancel": {"operations": ("reject", "cancel"), "kind": None},
    "brakes": {"operations": ("cancel", "stop-task"), "kind": None},   # R18: end what runs, turned on for messaging by listing it (in no default); `cancel` is also in reject-cancel, so a written policy stays valid
    "retry": {"operations": ("retry",), "kind": None},
    "set-mode": {"operations": ("set-mode", "set-model"), "kind": None},
    "consent": {"operations": ("give-consent",), "kind": None},   # the page's consent for an autonomous agent (D38): a group of its own, so granting set-mode never grants it
    "dispatch": {"operations": ("dispatch",), "kind": None},
    "documents": {"operations": ("sync", "hand-over"), "kind": None},
    "flow-write": {"operations": ("flow-save", "stage-file"), "kind": None},   # saving a flow of the project, and handing a file over for the plan of one (not `flows`, the read operation of the group `read`)
    # routines (P6b): the brakes reach the messaging channel by default; making and changing one is turned on by `channels.messaging` listing `routine-edit`
    # (and never for a flow that holds a networked script or that a standing policy covers: ROUTINE_LOCAL_CHANNELS); approving one
    # (by the hash of its content) and resuming it are the terminal's and the page's
    "routine-brakes": {"operations": ("routine-pause", "routine-cancel"), "kind": None},
    "routine-edit": {"operations": ("routine-create", "routine-change"), "kind": None},
    "routine-approve": {"operations": ("routine-approve", "routine-resume"), "kind": None},   # the approval of a routine's exact content by its hash, and the lifting of a pause
    "instructions-write": {"operations": ("instructions-set", "instructions-add"), "kind": None},   # writing the person's standing instructions (L40): the terminal and the page alone BY DEFAULT, whatever a policy lists today (a later package makes it a grant); not `instructions`, the read operation of the group `read`
    "verdict": {"operations": ("verdict",), "kind": None},
    "sources": {"operations": ("source-add", "source-import", "source-refresh", "source-describe", "sources"), "kind": None},
    # ATT-1: files sent through a messaging app. `add-sources` is the group of everything about them (a messaging app takes a file only when its policy lists it,
    # by default none does; the page keeps its ceiling unless its policy narrows it; the MCP mode has no row). `add-sources-direct` is a grant of the messaging
    # channel: the file a listed sender sends becomes a version of a source at once, with no card; it holds the one call the bridge makes after a fetch
    "add-sources": {"operations": ("attachments", "attachment-hold", "attachment-add", "attachment-discard"), "kind": None},
    "add-sources-direct": {"operations": ("attachment-hold",), "kind": "direct"},
    # RM-1: reminders, a one-shot notice the messaging bridge sends to the chat that made it (limit L51). In no default policy: a messaging app takes it only when the
    # project's configuration lists the group (accept-config --widen confirms it); never on the MCP mode (no row lists it). The group is a notice and never an effect.
    "reminders": {"operations": ("remind", "reminders", "reminder-forget", "reminder-restore"), "kind": None},
    # W1: the person's own calendar (SPEC-SECRETARY-WRITES 5). In no default policy: a messaging sender gets it only from a profile or channel entry accepted with
    # --widen; never on the MCP mode. It prepares a card and writes nothing: the write is the approval of the card's hash (`approve-effect-calendar` on a messaging app).
    "calendar-write": {"operations": ("event-create", "event-change", "event-cancel"), "kind": None},
    "approve-effect-calendar": {"operations": ("approve",), "kind": "effect:calendar"},      # a change to the person's own calendar (effect_calendar.py APPROVAL_GROUP)
    # W4a: new files and new revisions in the person's own Drive and OneDrive. In no default policy: a messaging app takes it only when the project's configuration
    # lists the group (accept-config --widen confirms it); never on the MCP mode. Each operation only prepares a card; the write waits for approve-effect-files or the
    # terminal and the page.
    "files-write": {"operations": ("file-create", "file-replace", "file-save"), "kind": None},
    "approve-effect-files": {"operations": ("approve",), "kind": "effect:files"},          # a file in the person's own Drive or OneDrive (effect_files.py APPROVAL_GROUP)
    # W2: e-mail from the person's own account (SPEC-SECRETARY-WRITES 5). In no default policy: a messaging sender gets it only from a profile or channel entry accepted with
    # --widen; never on the MCP mode. It prepares a card and sends nothing: the send is the approval of the card's hash (`approve-effect-send` on a messaging app).
    "mail-send": {"operations": ("mail-send", "mail-reply"), "kind": None},
    # W3: the person's own mailbox (SPEC-SECRETARY-WRITES 5). In no default policy: a messaging sender gets it only from a profile or channel entry accepted with --widen;
    # never on the MCP mode. It prepares a card and writes nothing: the write is the approval of the card's hash (`approve-effect-mailbox` on a messaging app).
    "mail-organize": {"operations": ("mail-draft", "mail-archive", "mail-move", "mail-mark", "mail-trash"), "kind": None},
    "approve-effect-mailbox": {"operations": ("approve",), "kind": "effect:mailbox"},      # a change to the person's own mailbox (effect_mailbox.py APPROVAL_GROUP)
    # S1: the plain lines no list takes go to the interpreter's model service (runtime/ops_interpret.py). A capability added to `say` that never grants it (KIND_ONLY): a profile lists
    # `talk` too. In no default policy: a messaging sender gets it only from a profile or channel entry accepted with --widen (which prints the route's retention beside it).
    "interpret": {"operations": ("say",), "kind": "interpret"},
    # S8: the text of a file in the folders the project lists under `accounts`, read by its name. In no default policy: a messaging sender gets it only from a profile or channel entry accepted
    # with --widen; never on the MCP mode (the row does not list it). It reads and shows; it writes nothing and sends nothing to a model.
    "read-files": {"operations": ("file-read",), "kind": None},
    # S18: the file itself, sent as an attachment beside the text, when file-read finds one. A capability added to `file-read` that never grants it (KIND_ONLY, as `interpret` is): it needs
    # `read-files` beside it (project_config refuses a policy that lists it alone). In no default policy: a messaging sender gets it only from a profile or channel entry accepted with
    # --widen; never on the MCP mode. The whole file leaves the drive for the messaging app's servers.
    "send-files": {"operations": ("file-read",), "kind": "send"},
    # R2-F1: a question of general information answered by a web search (runtime/ops_research.py). In no default policy: a messaging sender gets it only from a profile or channel entry accepted with
    # --widen; never on the page or the MCP mode (the row does not list them). It reads and answers; it writes nothing, opens no card and sends nothing but the question, to a search service and a model.
    "research": {"operations": ("research",), "kind": None},
}
# The policy of a channel that has no entry in the project's configuration. A channel absent from this table keeps its
# whole ceiling; the terminal is never narrowed. The messaging channel is closed: what changes the work other than a
# line to the planning agent and an answer is turned on explicitly.
DEFAULT_POLICY = {"messaging": ("read", "talk", "answer", "routine-brakes")}
NEVER_NARROWED = ("terminal",)
POLICY_CHANNELS = ("page", "mcp", "messaging")     # the channels a project's configuration narrows; `chat` (local access, equal to the terminal) and `terminal` never are
MUST_READ = ("page", "mcp")                        # a policy for these lists `read`
PAGE_ONLY_GROUPS = ("approve-effects",)            # valid on the page alone (an effect is approved nowhere else, by EFFECT_CHANNELS)
MESSAGING_ONLY_GROUPS = ("read-limited", "ask-mail", "interpret", "send-files")          # valid on a messaging app alone (the page and the MCP mode list `read`; the page and the terminal name a mail source with @<id> as they always did)
KIND_ONLY = ("ask-mail", "interpret", "send-files")                           # groups that add a capability to an operation another group grants: they never grant the operation when no kind is asked (policy_allows)
# A group that holds all of another's operations: whoever has it has that one too, so the list of what a file adds never lists the second when it lists
# the first (a test ties each pair to GROUPS).
IMPLIED = {"read": ("read-limited",),
           "approve-effects": ("approve-effect-create", "approve-effect-write", "approve-effect-send", "approve-effect-send-own", "approve-effect-publish", "approve-effect-calendar", "approve-effect-files", "approve-effect-mailbox")}
SENDERS_KEY = "senders"                            # POL-2: in the LOADED policy mapping (never in runtime.json), {"<platform>:<sender id>": [groups]} of each listed sender whose entry names a profile
EFFECT_CHANNELS = ("terminal", "page")             # the channels an effect may be approved from (decision D8, extended)
INSTRUCTIONS_CHANNELS = ("terminal", "page")       # the channels that write the person's standing instructions BY DEFAULT (limit L40; a later package of channel policies makes it a grant): the rows instructions-set and instructions-add list exactly these (a literal each, as the table is read by ast.literal_eval; a test compares), and no policy widens a row's channels
NETWORKED_PLAN_CHANNELS = ("terminal", "page")     # BY DEFAULT: the channels a plan that holds a step of a networked kind (a project script, P9) may be approved from (limit L36); one named literal, which a later policy makes a grant
ROUTINE_LOCAL_CHANNELS = ("terminal", "page")      # the channels a routine whose flow holds a networked script, or that a standing effect policy covers, is made and changed from (limit L33, S10)
BRAKES = ("cancel", "stop-task", "set-mode", "routine-pause", "routine-cancel")                    # never withheld from the page: cancel, and a move of a mode DOWN (the direction is checked by ops_config.set_mode)

# Grants (POL-1). A channel restriction is a policy: the default is today's rule, and the person may widen it in the project's
# configuration. "Grant" means one thing here: a group of GRANTS below, which goes BEYOND the ceiling of a channel (an effect on a
# messaging app, a networked plan, and the operations the MCP mode's rows do not list), and which a channel reaches only when the
# project's OWN entry for it lists it (never through DEFAULT_POLICY, never through "no entry keeps the ceiling"). accept-config shows
# what each grant gives away and takes the hash of that list (--widen) before it accepts a file that adds one. The other groups
# (approve-plans, release, reject-cancel, retry, brakes, routine-edit, ...) are inside a channel's ceiling: a project turns them on
# by listing them, and that is a widening too (POL-2): accept-config takes the same hash for ANY group a channel or a listed sender
# has in the file and did not effectively have in the one accepted before (messaging: the default; the page and the MCP mode: their
# ceiling), a text line for each in GROUP_TEXT (policy_widening). An effect is approved by the exact hash on every
# channel; a grant changes where, never whether. The MCP mode (a model client) is granted no effect, no networked plan and no consent.
#
# Profiles (POL-2). A policy is a named set of groups, a profile (runtime.json `policies`); a channel's entry may name one, and on a messaging
# app each listed sender may have their own, which REPLACES the channel's groups for that sender (SENDERS_KEY in the loaded policy mapping;
# effective_groups(channel, cfg, sender)). Nothing but accept-config in the terminal changes a profile, and nothing a sender sends names one.
ACCOUNT_APPROVAL_WORDS = ("calendar", "mailbox", "files", "send-own")   # the approval words of a write to the person's own accounts: a card of one that cannot be read as a card is not shown to a reader of no mail
EFFECT_APPROVAL_WORDS = ("create", "write", "send", "send-own", "publish", "calendar", "files", "mailbox")   # the words of an effect that an approval path opens (a test ties each to its module and its group `approve-effect-<word>`)
GRANTS = {
    "messaging": ("approve-effect-create", "approve-effect-write", "approve-effect-send", "approve-effect-send-own", "approve-effect-publish", "approve-networked-plans",
                  "add-sources-direct", "approve-effect-calendar", "approve-effect-files", "approve-effect-mailbox"),
    "mcp": ("approve-plans", "approve-acceptances", "reject-cancel", "retry"),
}
GRANT_TEXT = {
    "messaging:approve-effect-create": "a messaging app may approve a pull request, with its hash; today its card shows the files and their hashes and not the code, so no pull request is approved from a card yet and this grant approves nothing until a card shows the change",
    "messaging:approve-effect-write": "a messaging app may approve the write of a page of your documents platform (never a table: its card is a preview), from a card that carries the whole text, with its hash",
    "messaging:approve-effect-send": "a messaging app may approve an e-mail sent from your outbox (never one with an attachment), from a card that carries the whole text, with its hash",
    "messaging:approve-effect-send-own": "a messaging app may approve an e-mail sent from one of your own accounts (never one with an attachment), from a card that carries the whole text, with its hash; the grant of the outbox's e-mail does not cover it",
    "messaging:approve-effect-publish": "a messaging app may approve a post to a social platform (never one with an image), from a card that carries the whole text, with its hash",
    "messaging:approve-effect-calendar": "a messaging app may approve an event on your own calendars (create, change or remove), from a card that carries the whole event, with its hash",
    "messaging:approve-effect-files": "a messaging app may approve a new file or a new revision in your own Drive or OneDrive, from a card that carries the whole text, with its hash; a file you sent from the phone is saved on a card that names it, its size and its hash, and only the sender who sent it approves it",
    "messaging:approve-effect-mailbox": "a messaging app may approve a change to your own mailbox (a draft, archive, a move to a folder, read state, the trash), from a card that lists every message or shows the draft whole, with its hash; the card shows the subjects, senders, addresses and text only to a sender who may read your mail (ask-mail), so for any other sender it approves nothing",
    "messaging:approve-networked-plans": "a messaging app may approve a plan that holds a script which reaches the network, with the plan's hash",
    "messaging:add-sources-direct": "a file a listed sender sends becomes a new source of the project without a confirmation (a file for a source that already exists still waits for a card)",
    "mcp:approve-plans": "a connected AI client may approve a plan, with its hash: a model then authorises runs on its own request chain",
    "mcp:approve-acceptances": "a connected AI client may accept what a request delivered or proposed: a model then authorises more work",
    "mcp:reject-cancel": "a connected AI client may reject a decision and cancel a request",
    "mcp:retry": "a connected AI client may make a failed or blocked task ready again",
}
GROUP_TEXT = {
    "read": "reads everything the channel shows: the state of the work, what waits, the spend, the agents' caps and the connections",
    "read-limited": "reads what the work is and what waits for the person, never the spend (costs, agents, a run's cost in task and progress), the connections or the config operation",
    "talk": "writes a line to the planning agent (a new request, or the answer to its question)",
    "answer": "answers a question a task asked",
    "release": "releases a delivery (it stays a draft)",
    "request": "makes a request and has it routed",
    "approve-plans": "approves a plan, with its hash: the tasks start to run",
    "approve-acceptances": "accepts what a request delivered or proposed: more work follows",
    "approve-effects": "approves any effect with its hash (the page alone)",
    "approve-effect-create": "approves a pull request, with its hash",
    "approve-effect-write": "approves the write of a page of the documents platform, with its hash",
    "approve-effect-send": "approves an e-mail sent from the project's outbox, with its hash",
    "approve-effect-send-own": "approves an e-mail sent from one of the person's own accounts, with its hash",
    "approve-effect-publish": "approves a post to a social platform, with its hash",
    "approve-effect-calendar": "approves an event on the person's own calendars (create, change or remove), with its hash",
    "approve-effect-files": "approves a new file or a new revision in your own Drive or OneDrive, with its hash",
    "approve-effect-mailbox": "approves a change to the person's own mailbox (a draft, archive, a move to a folder, read state, the trash), with its hash",
    "approve-networked-plans": "approves a plan that holds a script which reaches the network, with the plan's hash",
    "ask": "asks a question answered by a model from the full text of the project's sources; the answer and its quotes are sent to this channel (on a messaging app they pass the platform's servers)",
    "ask-mail": "asks about the mail and calendar sources from a messaging app and has them read for questions that name no source: their text goes to a model and the answer passes the platform (adds to `ask`, never grants it)",
    "go-ahead": "goes ahead on a task that waits for another request",
    "reject-cancel": "rejects a decision and cancels a request",
    "brakes": "cancels a request and stops a running task",
    "retry": "makes a failed or blocked task ready again",
    "set-mode": "moves an agent's autonomy mode up or down",
    "consent": "gives the consent an autonomous agent needs (the page alone)",
    "dispatch": "starts the dispatcher's round",
    "documents": "syncs the documents platform and hands a file over to a task",
    "flow-write": "saves a flow of the project and hands a file over for a plan",
    "routine-brakes": "pauses and cancels a routine",
    "routine-edit": "makes and changes a routine (it stays a draft until it is approved)",
    "routine-approve": "approves a routine by its hash and resumes it",
    "instructions-write": "writes the person's standing instructions",
    "verdict": "records a verdict on a skill's use",
    "sources": "adds, imports, refreshes and describes the project's sources",
    "add-sources": "takes the files a listed sender sends through a messaging app (held, then added or discarded on a card or on the page), and lists and decides the held files",
    "add-sources-direct": "a file a listed sender sends becomes a new source of the project without a confirmation; a file for an existing source still waits for a card (it holds the hold alone, and adds nothing else)",
    "calendar-write": "prepares changes to your own calendars (create, change, remove an event); each one waits for approval of its card",
    "mail-send": "prepares e-mails from your own accounts (a new e-mail, a reply to a message of a mail snapshot); each one waits for approval of its card",
    "reminders": "makes, lists and forgets reminders: one-shot lines of the sender's own words that the bridge sends back to their own chat at the time they chose",
    "files-write": "prepares new files and new revisions in your own Drive and OneDrive, and the saving of a file you sent; each one waits for approval of its card",
    "mail-organize": "prepares changes to your mailbox (a draft, archive, a move to a folder, read state, the trash); each one waits for approval of its card, and nothing is sent or deleted for good",
    "interpret": "sends the plain lines no list takes to the interpreter's model service, which reads them in any language; retention: the route's terms (adds to talk, never grants it)",
    "read-files": "shows the text of the files in your configured Drive and OneDrive folders in the chat, found by their names; a messaging app's servers see it as they see any message, and no model reads it",
    "send-files": "sends the found file itself to the chat, not only its text: the whole file leaves your drive for the messaging app's servers; one whose text looks like a password or a key is not sent (adds to read-files)",
    "research": "answers general questions (weather, prices, news, facts) from a web search: the question is sent to a web search service and to the model that runs the research, and the answer comes back to this chat",
}
NEVER_GRANTED = ("chat", "terminal")   # channels with no entry in GRANTS; and no group of an effect, a networked plan, consent, set-mode or routine-approve is ever in GRANTS["mcp"] (a test reads this)


def by_name(name: str) -> dict:
    """The row of an operation. KeyError when there is none."""
    for row in OPERATIONS:
        if row["name"] == name:
            return row
    raise KeyError(name)


def sender_key(platform: str, sender: str) -> str:
    """The key of a listed sender in the policy mapping and in the widening list: `<platform>:<sender id>`. A platform has no colon (project_config
    refuses it), so the first colon always ends the platform."""
    return f"{platform}:{sender}"


def actor_text(actor) -> str | None:
    """An actor, as the store keeps it (`terminal`, `page`, `mcp`, `chat`, or `messaging:<platform>:<profile>:<sender id>`), as a person or a versioned
    file may read it: `<profile> on <platform>` for a messaging sender, WITHOUT the sender id; the channel's name otherwise; None for none."""
    if not isinstance(actor, str) or not actor:
        return None
    if not actor.startswith("messaging:"):
        return actor
    parts = actor.split(":", 3)
    return f"{parts[2]} on {parts[1]}" if len(parts) == 4 else "messaging"


def _explicit(channel: str, cfg, sender=None):
    """The project's own entry for a channel (the groups it lists), or None when it has none; for a messaging sender (`sender`: sender_key) whose entry
    names a profile, the profile's groups instead. A grant counts only from here."""
    if sender is not None and channel == "messaging":
        mine = ((cfg or {}).get(SENDERS_KEY) or {}).get(sender)
        if mine is not None:
            return tuple(mine)
    given = (cfg or {}).get(channel)
    return tuple(given) if given is not None else None


def effective_groups(channel: str, cfg, sender=None) -> tuple | None:
    """The one seam every check of the policy reads: the groups that apply to a channel, or to one sender of the messaging channel: the sender's
    profile (its entry in `messaging.senders` names one), else the channel's entry (a list of groups, or the profile the channel names), else the
    default of the channel (DEFAULT_POLICY), else None (the whole ceiling). A sender's profile REPLACES the channel's groups for that sender: it may be
    narrower. Pure. `cfg` is the project's loaded `channels` mapping (project_config); `sender` is `sender_key(platform, id)` and is read for the
    messaging channel only. A grant counts only when it comes from an explicit entry or an explicit profile (`_explicit`), never from the default."""
    given = _explicit(channel, cfg, sender)
    return given if given is not None else DEFAULT_POLICY.get(channel)


def policy_groups(channel: str, policy) -> tuple:
    """The groups that apply to a channel: the project's entry, else the default of the channel, else None (the whole
    ceiling). The name the callers and the tests know; the rule is effective_groups."""
    return effective_groups(channel, policy)


def is_read(op_name: str) -> bool:
    """Whether an operation is in the group `read`: a read, which the page and the MCP mode always keep (their policy
    must list `read`), so a shell asks nothing of the configuration for it."""
    return op_name in GROUPS["read"]["operations"]


def is_effect_kind(kind) -> bool:
    """Whether a kind of `approve` is of the effect family: `effect` (the umbrella, no word) or `effect:<word>`."""
    return kind == "effect" or (isinstance(kind, str) and kind.startswith("effect:"))


def _covers(group_kind, kind) -> bool:
    """Whether a group of this kind covers a decision of that kind: a group with no kind covers every kind, `kind` None asks whether
    any does, equal kinds match, and the umbrella `effect` covers every `effect:<word>`."""
    return group_kind is None or kind is None or group_kind == kind or (group_kind == "effect" and is_effect_kind(kind) and kind != "effect")


def granted(op_name: str, channel: str, cfg, kind=None, sender=None) -> bool:
    """Whether the project's own entry for the channel lists a group of GRANTS[channel] that covers the operation (for this kind).
    The umbrella `approve-effects` is not a grant, and no default holds one."""
    given = _explicit(channel, cfg, sender)
    if not given:
        return False
    for name in given:
        group = GROUPS.get(name)
        if name in GRANTS.get(channel, ()) and group and op_name in group["operations"] and _covers(group["kind"], kind):
            return True
    return False


def grants(cfg) -> list:
    """[(channel, group)] of the grants the project's own entries list, in the order of GRANTS (pure)."""
    return [(channel, name) for channel, names in GRANTS.items() for name in names if name in (_explicit(channel, cfg) or ())]


def sender_grants(cfg) -> list:
    """[(sender key, group)] of the grants that the profiles of the listed senders hold, in the order of GRANTS["messaging"] (pure)."""
    listed = (cfg or {}).get(SENDERS_KEY) or {}
    return [(key, name) for key in sorted(listed) for name in GRANTS["messaging"] if name in listed[key]]


def group_refusal(channel: str, group: str) -> str | None:
    """The sentence that refuses one group for one channel, or None when the channel takes it (pure; project_config uses it for a channel's entry and
    for a profile at the place it is assigned). A group is valid when one of its operations is in the channel's ceiling (a policy narrows), or when it
    is a grant of that channel (GRANTS: the one way a policy widens). The effect groups and the networked-plan group are never valid on the MCP mode, the
    umbrella `approve-effects` is the page's alone, and `read-limited` is a messaging app's alone."""
    spec = GROUPS[group]
    effect_family = is_effect_kind(spec["kind"]) or spec["kind"] == "plan:networked"
    if group in PAGE_ONLY_GROUPS and channel != "page":
        return (f"the group {group!r} is valid on the page only (an effect is approved in the terminal or on the page, with its hash; "
                f"a messaging app takes one word at a time: {', '.join(g for g in GRANTS['messaging'] if g.startswith('approve-effect-'))})")
    if group in MESSAGING_ONLY_GROUPS and channel != "messaging":
        return (f"the group {group!r} is valid on a messaging app only (the {channel} reads everything it shows: list the group 'read')")
    if channel == "mcp" and effect_family:
        return (f"the group {group!r} is not valid on the MCP mode (an effect and a networked plan are approved by a person; "
                "the MCP mode is a model client)")
    if group == "approve-networked-plans" and channel != "messaging":
        return (f"the group {group!r} is valid on a messaging app only (a plan that reaches the network is approved in the terminal "
                "or on the page by default, and nowhere else unless the project grants a messaging app)")
    if group in GRANTS.get(channel, ()):
        return None
    names = spec["operations"]
    if not any(channel in by_name(name)["channels"] for name in names):
        return (f"the group {group!r} covers {', '.join(names)}, which the table of operations does not give the channel {channel}; "
                "a policy narrows the ceiling and never widens it, except by a grant"
                + (f" (the grants of {channel}: {', '.join(GRANTS[channel])})" if channel in GRANTS else " (this channel has none)"))
    return None


def ceiling_groups(channel: str) -> tuple:
    """The groups a channel with NO entry of its own holds: every group the channel takes (group_refusal) that is not a grant of the channel (a
    grant is held only by listing it), in the order of GROUPS. What `accept-config` compares a file with when a channel's entry is removed."""
    return tuple(name for name in GROUPS if group_refusal(channel, name) is None and name not in GRANTS.get(channel, ()))


def default_groups(channel: str) -> tuple:
    """What a channel holds when the project lists nothing for it: the default of the channel (DEFAULT_POLICY), else its whole ceiling."""
    return tuple(DEFAULT_POLICY[channel]) if channel in DEFAULT_POLICY else ceiling_groups(channel)


def grant_only_rows(channel: str) -> tuple:
    """The names of the operations whose row does not list the channel and that a grant of the channel reaches (the MCP mode: approve,
    reject, cancel and retry, off unless the project grants them)."""
    names = {op for name in GRANTS.get(channel, ()) for op in GROUPS[name]["operations"] if channel not in by_name(op)["channels"]}
    return tuple(row["name"] for row in OPERATIONS if row["name"] in names)


def policy_allows(op_name: str, channel: str, policy, kind: str | None = None, sender=None) -> bool:
    """Whether the channel's ceiling lists the operation and the project's groups cover it (pure), without the brakes.
    The terminal is never narrowed; a channel with no groups keeps its ceiling. For a group with a kind, the decision's
    kind must equal it (`kind` None asks whether any group covers the operation). Four cases, in this order:
    (1) the kind is `plan:networked` (a plan with a networked step): the channels of NETWORKED_PLAN_CHANNELS ask as for a plan, any
    other needs the grant; (2) an effect (`effect` or `effect:<word>`) on a channel outside EFFECT_CHANNELS: only a grant of the
    channel for that word (`effect` with no word is false, and so is the umbrella); (3) a row that does not list the channel: only a
    grant that covers the operation; (4) the rest: the ceiling and the effective groups, as before."""
    try:
        row = by_name(op_name)
    except KeyError:
        return False
    if channel in NEVER_NARROWED:
        return channel in row["channels"]
    if op_name == "approve" and kind == "plan:networked":
        if channel not in NETWORKED_PLAN_CHANNELS:
            return channel in row["channels"] and granted(op_name, channel, policy, kind, sender)
        kind = "plan"
    if op_name == "approve" and is_effect_kind(kind) and channel not in EFFECT_CHANNELS:
        return channel in row["channels"] and kind != "effect" and granted(op_name, channel, policy, kind, sender)
    if channel not in row["channels"]:
        return granted(op_name, channel, policy, kind, sender)
    groups = effective_groups(channel, policy, sender)
    if groups is None:
        return True
    for name in groups:
        group = GROUPS.get(name)
        if name in KIND_ONLY and kind is None:
            continue
        if group and op_name in group["operations"] and _covers(group["kind"], kind):
            return True
    return False


def holds(group: str, channel: str, policy, sender=None) -> bool:
    """Whether the project's own entry for the channel (or the sender's profile) LISTS the group, and the channel takes it (pure). A channel with no entry,
    which keeps its whole ceiling, holds nothing here: a capability such as `ask-mail` is held only by being listed, so the page and the terminal never do."""
    given = _explicit(channel, policy, sender)
    if given is None:
        given = DEFAULT_POLICY.get(channel)
    return group in GROUPS and group in (given or ()) and group_refusal(channel, group) is None


def permitted(op_name: str, channel: str, policy, kind: str | None = None, sender=None) -> bool:
    """Whether a channel may call an operation under a project's policy (pure): `policy_allows`, and, on the page, the
    BRAKES whatever the policy says (cancel, and set-mode, whose direction ops_config.set_mode checks: a move down is
    never withheld, a move up needs the group). Never the only guard of an effect: an effect is approved with its hash,
    in EFFECT_CHANNELS or where the project grants the word, from a card that carried the whole text, and a line typed
    into any channel never approves one (ops.approve, ops_say, messaging_bridge)."""
    if channel == "page" and op_name in BRAKES and policy_allows(op_name, channel, None):
        return True
    return policy_allows(op_name, channel, policy, kind, sender)


def not_enabled(name: str, channel: str) -> str:
    """The sentence of an operation the channel's ceiling lists and the project's policy does not turn on. For an operation whose row does not list the channel
    and that no grant of the channel reaches, no configuration can turn it on, and the sentence says where it is done."""
    try:
        row = by_name(name)
    except KeyError:
        row = None
    if row is not None and channel not in row["channels"] and not any(name in GROUPS[g]["operations"] for g in GRANTS.get(channel, ())):
        places = [words for place, words in (("terminal", "in the terminal"), ("page", "on the page")) if place in row["channels"]]
        return f"/{name} is done " + " or ".join(places) if places else f"/{name} is not done on this channel"
    return f"/{name} is not enabled for this channel; the project's configuration (channels.{channel}) turns it on"


def refusal(op_name: str, channel: str, policy, kind: str | None = None, go_ahead: bool = False, sender=None):
    """The sentence that refuses a call, or None when the channel's policy lets it through (pure; the one helper the
    page, the MCP mode, a typed line, the approve rule and the queue's drain call). `kind` is the decision's kind for
    approve; `go_ahead` is true when approve carries task keys, which needs the group `go-ahead` too (on a channel with
    a policy). The caller raises OpsError(sentence, 1). A channel with no policy entry keeps its ceiling, so this
    refuses only what the ceiling or the project's groups refuse; the terminal and the conversation are never refused."""
    if not permitted(op_name, channel, policy, kind, sender):
        return not_enabled(op_name, channel)
    if go_ahead and channel in POLICY_CHANNELS and not permitted("go-ahead", channel, policy, None, sender):
        return not_enabled("go-ahead", channel)
    return None


def permissions(channel: str, policy) -> list:
    """What the channel may do under the policy, as the names the page reads (a list in the table's order): the plain
    name of every operation the channel's row lists and `permitted` allows, except `approve` and `set-mode`, which are
    pairs: approve:plan, approve:acceptance, approve:effect:<word> for each word the policy covers (and approve:effect when
    any is), approve:go-ahead (a plan's task keys: the kind plan and the group go-ahead) and set-mode:down, set-mode:up.
    On the page cancel and set-mode:down are always there (the brakes)."""
    out = []
    for row in OPERATIONS:
        name = row["name"]
        if channel not in row["channels"]:
            continue
        if name == "approve":
            kinds = [k for k in ("plan", "acceptance") if permitted("approve", channel, policy, k)]
            words = [w for w in EFFECT_APPROVAL_WORDS if permitted("approve", channel, policy, "effect:" + w)]
            out += ["approve:" + k for k in kinds] + (["approve:effect"] + ["approve:effect:" + w for w in words] if words else [])
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
