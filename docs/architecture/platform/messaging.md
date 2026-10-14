# The messaging channels

Part of [the platform map](README.md). This page is not a layer page: it follows one feature, a person running projects from a messaging app they already use, across the layers that carry it (the operations layer, a shell, the providers, the secrets contract, the page). It states what the code does, with file references, and points to the contracts for the rules; when this page and the file it points to disagree, the file wins and the page is corrected. It was written on 2026-10-13 from the code of the integration branch after packages MSG-1 to MSG-11 and from the decisions that shaped them.

## Purpose and scope

A person who runs a project through openhora needs two things away from the keyboard: to hear that a decision waits, and to answer it. The page of [the local service](shells.md) does both, but it is a web page to learn and keep open. The messaging channels take the same operations to apps the person already has: Telegram, Discord and three kinds of WhatsApp. The person is told, in a chat with a bot or a number, that a plan, a question, a review or an acceptance waits; reads its text; taps a button or types a short command; and can write a free line to the planning agent as in the terminal conversation.

What reaches the phone:

- **Notices.** One card for each open pending decision, once per content, to every listed sender (`runtime/messaging_cards.py`, `runtime/messaging_bridge.py`).
- **Replies** to what the person writes: the answer of an operation, or the planning agent's reply to a free line.
- **The decisions the project's policy allows the phone to take**: by default only reading, talking to the planning agent and answering a question (`operations.DEFAULT_POLICY`); approving a plan or an acceptance, releasing a delivery, rejecting, cancelling and retrying are turned on one group at a time by the project's configuration ("The channel policy").

What never reaches the phone as an approval: **an effect** (a commit, a pull request, a post, a message sent in the project's name). Decision D8 holds on every channel: an effect is approved only in the terminal or on the local page, with its hash typed or clicked there (`operations.EFFECT_CHANNELS = ("terminal", "page")`). The card of an effect carries the exact command, with its hash, and no button.

What the channels are not: not a second runtime and not a place with a model of its own. No model sits between the app and the operations layer; free text goes to `say`, which is the same planning agent the terminal and the page reach. And the bridge is not an assistant platform: a gateway that is itself an MCP client can use the MCP mode instead, and the note for that is `adapters/openclaw/README.md`; it is outside the core and runs a model between the chat and the tools, which the bridge does not.

Scope of this page: the bridge and its modules, the channel policy for all three channels that take one, the messenger interface, the five platforms built today, the public address the official WhatsApp paths need, the security model, a runbook and the open items. The contracts that bind it are [contracts/runtime.md](../../../contracts/runtime.md) ("The messaging bridge", "The channel policy", "The listen mode"), [providers/CONTRACT.md](../../../providers/CONTRACT.md), [providers/messenger/README.md](../../../providers/messenger/README.md) and [contracts/secrets.md](../../../contracts/secrets.md).

## The decisions and why

Decisions are numbered M-n in the supervisor's record of the messaging work; the table gives each as the workbench's own decision. "The maintainer" is the person who owns the repository. Dates are those of the decision (2026-10-11 to 2026-10-13); a row that groups several says which.

| Decision | What | Why |
|---|---|---|
| M-1 (10-11) | An openhora bridge of its own: no model between the app and the operations layer; free text goes to `say`. Telegram first, over the Bot API with long polling and no open port. Each platform is a provider, so another one adds a file. | A model between a chat and the tools can be argued into acting by text it reads; code cannot. A generic bridge with one provider per platform keeps the cost of the next platform at one file. |
| M-2 (10-11) | The messaging channel may approve a plan, with the plan's hash carried by the button. | The tap names exactly the content the person saw; `ops.approve` refuses a plan whose hash moved. |
| M-3 (10-11) | Effects stay under D8: approved in the terminal or on the page; the notice carries the command. Standing approvals reduce how often that is needed. Approving effects from the messaging channel is a later opt-in and is not built. | An effect leaves the machine and cannot be undone; the person must see its content and hash on a surface that is local to them. |
| M-4 (10-11) | Notices carry the decision's text by default; a project may choose `count` (a line and a link, no project text). | The platform's servers see what is sent; the person chooses how much. |
| M-5 (10-11) | The route through a gateway that is an MCP client (the MCP mode) is documented outside the core (`adapters/openclaw/README.md`), for people who already run one. Running skills inside such a gateway would be a later project with its own battery. | It serves people who already have a gateway. It puts a model between the chat and the tools, which the bridge does not, and anything specific to one tool lives in `adapters/` (principle 2). |
| M-6 (10-11) | An acceptance may also be approved from the messaging channel; the bridge binds it to the content of the card the person saw. Reject, retry and cancel are allowed there too (when the policy turns them on). | An acceptance has no hash. A person who wants more safety uses the page, the fully safe channel. |
| M-7 (10-11) | Cards are platform-neutral (header, body, actions, link, document). Each provider declares capabilities; the bridge folds what does not fit into typed commands (`/approve 12`), which always work. One decision per message. | One bridge for every platform; a platform without buttons loses nothing but convenience. |
| M-8, M-12, M-13, M-14 (10-11 to 10-12) | A channel policy: the table's `channels` column is the ceiling; `runtime.json` `channels.<channel>` narrows it with named groups. Messaging is closed by default (`read`, `talk`, `answer`). The policy covers the page and the MCP mode too; the conversation (`chat`) and the terminal are never narrowed; the MCP mode keeps its ceiling unless narrowed; `cancel` and a move down of an agent's mode are never withheld from the page, `--lan` included. Two independent reviews of the plan and a third of the written specs shaped these (a group's validity, the queue's stored group, the ledger's migration keeping `seq`, the state folder checked, provider exit codes staying 0 to 3, test hooks as keyword parameters only). | One rule for every surface instead of one per shell. The person who has lost trust must always be able to stop work from the page. The chat's input is local access, equal to the terminal, so it is not narrowed. |
| M-9, M-13 (10-11, 10-12) | `service.py --messaging <platform>` starts the bridge as a child process of the service with the same projects; one start brings up the page and the bridge. | One command for a person who wants both; the child's stop is tied to the service's. |
| M-10 to M-19 (10-11 to 10-12) | Order of delivery: the policy for the page and the MCP mode and `--messaging` waited for the parallel runtime work that owned the same files (the table, `ops_say`, `service`, `mcp`), then were split: the bridge's state folder, lock and child process first (MSG-3a), the policy on the server rebased onto that work (MSG-3b), and the page hiding what the policy refuses in a package of its own after the interface work (MSG-3c). | Several packages owned the same files; the order avoided conflicts without changing any rule. |
| M-20, M-21 (10-12) | Telegram renders the Markdown of a message safely (HTML parse mode, everything escaped first); an effect command is a tap-to-copy code span; link previews are off for every message the Telegram provider sends. | Agents write Markdown; raw marks are hard to read. A command that is one tap to copy is harder to mistype than one typed from a screenshot. |
| M-22 (10-12) | Discord with buttons, through its Gateway, with `websockets` adopted rather than built. WhatsApp after it, through an unofficial web client first, as another gateway does. A long-lived `listen` mode for a messenger provider comes first, generic. | The Gateway delivers button taps only on its open connection. The maintainer decided on the unofficial WhatsApp client knowing that WhatsApp's consumer terms bar automation and the number may be restricted; the risk is written in the provider's README. |
| M-23, M-26 (10-12, 10-13) | An expired or logged-out WhatsApp session makes the bridge wait and ask again every few minutes, not stop. The `paused` line repeats every 24 hours. A `whoami` subcommand prints the sender digits, on a terminal only. The README documents excluding the session from backups. Messages sent while paused are processed on reconnect. | The same behaviour as a project that is not ready: only the person can mend it, and the bridge recovers by itself. |
| M-24 (10-12) | Discord's `websockets` dependency is hash-locked (`discord.py.lock`), honoured by the way `resolve.py` starts the provider (`uv run --locked`). | The dependency holds a credential on a long-lived connection; a version pin is not an integrity check. |
| M-25, M-27 (10-13) | WhatsApp unofficial through whatsmeow, a Go program built from source on the person's machine and pinned by `go.sum`, driven by a Python provider; a separate number of the person's own; typed commands only. The GPL-3.0 licence of a library it links is accepted on two conditions: openhora never distributes the built binary, and the note stays in the provider's README. | Research found the alternatives downloading a native library without a hash check, or with a published vulnerability and a lookalike package that stole sessions. A separate number keeps a restriction away from the personal account. |
| M-28, M-29, M-35 (10-13) | The official WhatsApp Cloud API as a second platform, `whatsapp-cloud`. Outside the 24-hour window the provider sends one fixed template with no project text ("N decisions wait; reply to see them") with a "See decisions" quick reply mapped to `/pending`, at most once per closed window and once every 7 days; the template is optional (without it a card waits until the person writes). The Meta-direct provider's state folder is documented as excluded from backups; it remembers message ids 8 days and identity pairs 30 days. | The official path has no restriction risk for the number. A fixed text is the only thing that can be sent where free-form text cannot. |
| M-30 to M-34 (10-13) | A third WhatsApp provider, `whatsapp-twilio`, for a number that is a Twilio WhatsApp sender. A restricted API key sends; the Auth Token only checks `X-Twilio-Signature`. No documents (text cut at 1600); no card buttons until the person records three quick-reply template ids; no catch-up of messages lost while the machine slept. Shared code with `whatsapp-cloud` lives in `providers/messenger/whatsapp_meta.py`. Leaving Twilio later is Meta's migration between WhatsApp Business Accounts, never deleting the sender. | The maintainer's test number is a Twilio sender. Twilio documents the Auth Token as the signing key and a restricted key for sending, so each secret does one job. |
| M-36 (10-13) | The official WhatsApp providers take any public HTTPS address (`--public-url`); Tailscale is an optional helper, not a requirement. A README table says who can read the traffic for each option. A missing `keyring` library is reported as such, not as "secret missing". | Forcing one tunnel vendor on every user is not the workbench's choice; the person decides who sits in the path. |
| M-37 (10-13) | This page and the entry in [decisions.md](../../decisions.md). | The integration is the workbench's own knowledge and must outlive the conversation that built it. |

## Architecture

### The shells and where the bridge sits

The operations layer (`runtime/ops.py` and the table `runtime/operations.py`) is reached by five shells. Each parses what it was given, calls one operation and returns what came back; none decides a rule a second shell would have to decide again.

```text
   terminal         chat           page              mcp            messaging
   runtime/cli.py   runtime/chat.py runtime/service.py runtime/mcp.py runtime/messaging.py
       |               |               |               |               |
       +---------------+---------------+-------------+-----------------+
                                       |
                          runtime/ops.py  (the operations layer)
                 runtime/operations.py: the table, the ceilings, the groups, refusal()
                                       |
                 the store, the project's files, the lab (a model run is a container)

   inside runtime/messaging.py:

   person's phone --- platform servers --- provider  providers/messenger/<impl>.py
                                              |       class messenger:<platform>, resolved by providers/resolve.py
                                              |       one process per verb (Telegram) or one long-lived `listen`
                                              v
                                   messaging_provider.py  (Messenger, ListenSession)
                                              |
        messaging_inbound.py  --->  messaging_bridge.py  <---  messaging_cards.py  (a decision as a neutral card)
        (an update as an intent)          |        |
                                          |        +--->  messaging_ledger.py  (what was sent; state folder, lock)
                                          v
                       Bridge.run_op: the policy first, then the operation, as the channel "messaging"
```

With `--messaging`, the local service also starts `runtime/messaging.py` as a child process (`service_bridge.py`); the two are separate processes that share the operations layer, not a call path.

The five channels are the values of the `channels` column of the table (`runtime/operations.py`): `terminal`, `chat`, `page`, `mcp` and `messaging`. The ceiling of `messaging` is the rows `status`, `task`, `progress`, `pending`, `answer`, `release`, `approve`, `reject`, `retry`, `cancel`, `say`, `agents`, `skills`, `costs`, `artifacts` and `artifact`, and no other (not `request`, `route`, `set-mode`, `accept-config`, `go-ahead`, `config`, `dispatch`, the standing approvals, nor anything terminal-only). `messaging` is not in `ops_say.QUEUING_CHANNELS` (only the page queues a line while a run holds the project): a line that arrives meanwhile is answered with the sentence in `messaging_bridge.RUN_BUSY`.

### The bridge

`runtime/messaging.py` is the shell: `uv run --with keyring==25.7.0 python3 runtime/messaging.py --project <dir> [--project <dir>]... --platform <platform> [--notice-every 60] [--state-dir <dir>] [--stop-on-stdin-eof]`. It runs until SIGINT or SIGTERM, then stops polling, ends the runs it started (`ops.stop_runs`) and, last, closes the provider's session. It prints one JSON line at the start (the platform and the projects' ids and names, never a sender or a token) and logs to standard error with no sender id, no text and no result. Exit codes: 0 stopped, 2 usage (also a state folder that is not safe, and a `--platform` that is not a lowercase word of letters, digits and hyphens), 3 a folder that is not a configured project, or the messenger provider is not configured (also the provider's two Telegram 409 answers, and the end of a listen provider that said it could not go on), 4 another bridge already serves the platform for this user.

Its modules, each with one job (the layer map in `scripts/tests/test_layer_map.py` lets `messaging.py` import `ops.py`, `shell_kit.py` and these, and `service.py` import `service_bridge.py`):

| Module | Job |
|---|---|
| `messaging_bridge.py` | The logic. `Bridge.run_op` is the one call path: `operations.permitted` for the channel and the project's policy, then the operation, as the channel `messaging`. Notices (`tick`, `notify_project`), the intents (`handle`, `tapped`, `act`, `approve`), `say` and `release` in threads (`shell_kit.Jobs`, one model job per project), the poll loop and the listen loop |
| `messaging_cards.py` | A pending decision as a neutral card, fitted to the capabilities; pure. Also `content_sha256` and `split` |
| `messaging_inbound.py` | An update as an intent (`approve`, `reject`, `release`, `answer`, `pending`, `project`, `help`, `reply`, `action`, `text`, `usage`, `ignore`); pure |
| `messaging_ledger.py` | The state folder (made and checked), the lock, the ledger file; no network |
| `messaging_provider.py` | `Messenger` (the four verbs through `providers/resolve.py`) and `ListenSession` (the long-lived `listen` verb) |
| `service_bridge.py` | The bridge as a child of the local service (below); standard library only |

**The ledger and the state folder.** Per user, never in a repository. The folder is `--state-dir`, else `$OPENHORA_STATE_DIR`, else `$XDG_STATE_HOME/openhora` when that variable is set and absolute, else `~/.local/state/openhora` (`messaging_ledger.state_dir`). `prepare_state_dir` makes it mode 0700 and **checks** it with `lstat`: a real directory (not a link), owned by the user, no group or other bits; anything else is `StateError` and exit 2 naming the path. `take_lock` opens `<state>/messaging-<platform>.lock` with `O_CREAT | O_NOFOLLOW` at mode 0600, checks it is a regular file of the user, and takes `flock(LOCK_EX | LOCK_NB)` for the life of the process; a held lock is `LockHeld` and exit 4 ("another messaging bridge already serves <platform> on this machine (its lock: <path>); stop it first"). The system releases the lock when the process ends, so a crash leaves none stale. Only `messaging.py` takes it: a provider is a separate process and must not.

The ledger is `<state>/messaging-<platform>.json` (mode 0600), written through a temporary file (`O_EXCL`, random name, fsync) and published with `os.link` the first time and `os.replace` after. It holds no text of a project. For each card: the platform, the project id, the pending id and kind, `content_sha256` (a plan's hash, an effect's payload hash, else the sha256 of the decision's text), the chat, the platform's message id, the action ids made for it (`<seq>:<operation>`) and the time; plus the platform's next update offset (Telegram only) and `seq`. A card is found by platform, project id and chat, so two sets of projects on one machine never suppress each other's cards, and a restart sends no card twice. A one-time migration copies, from `<data_dir of the first project>/messaging-<platform>.json` (where the first versions kept it), the cards of the projects this bridge serves, with the old `seq` and `offset`, so an action id on a card already sent still acts on that card; the old file is left and one line says it can be deleted.

**Skip and re-check.** A project whose configuration is not accepted, or whose accepted configuration lists no sender for the platform, is skipped, not a reason to stop. `Bridge.recheck` runs at the start of every notice period; it logs one line when a project's state changes (`skipping <name>: its configuration is not accepted (run accept-config in the terminal)`, `... runtime.json messaging.senders.<platform> lists no sender`, `<name> is ready: now served`) and serves a project from its accepted file the moment it is ready. With every project skipped the bridge keeps running. Until a project is ready no update is served for it: a message from its sender in that window is dropped like one from an unlisted sender ("Operating it").

**Inbound.** An update from a sender who is not in `messaging.senders.<platform>` of at least one served project, or from a chat that is not private, or whose `chat` differs from `sender`, is dropped with no reply and one log line (`dropped an update from an unlisted sender`, no id, no text). A tapped button is looked up in the ledger by action id and chat (an unknown one gets "This button is no longer valid. Send /pending."), acknowledged where the platform needs it, and run with the recorded pending id. A typed command is read by `messaging_inbound.parse`; a reply to a question's card is `answer`; any other text is `say`, in a thread, one model call per project at a time ("Still working on the last message."), and its reply goes back as a neutral message split to the platform's limit. A person listed in several projects chooses with `/project <name>`; the default is the first.

### `service.py --messaging` and `service_bridge.py`

`service.py --messaging <platform> [--notice-every <s>]` (off by default) brings up the page and the bridge in one start. After the sockets are bound and the JSON line is printed (which then ends with `"messaging": "<platform>"`), `service_bridge.Child` starts `[sys.executable, runtime/messaging.py, --project <each project>..., --platform <platform>, --stop-on-stdin-eof]`:

- in its **own session** (`start_new_session`), so a signal to the service's group does not reach it and one signal to its group reaches the bridge and everything it started;
- with **standard input a pipe** the service holds open and never writes to: when the service dies, however it dies, the pipe closes and the bridge, started with `--stop-on-stdin-eof`, stops as a SIGTERM stops it (the flag is off by default because a bridge started by hand under `nohup`, `&`, launchd or systemd has its input at `/dev/null`);
- with **standard output at `/dev/null`** and standard error the service's;
- with **the environment snapshot** `dict(os.environ)` that `service.main` takes before any thread or run, so a key a run in progress writes into the service's own environment never reaches the child;
- with the service's **own interpreter**, so a service started with `uv run --with keyring==25.7.0` starts a bridge that can read the secret store.

When the child exits, at any time, the service writes one line with the code and its meaning (`service_bridge.MEANINGS`; a negative code names the signal) and goes on serving the page; nothing restarts the bridge in this version. The service's own `GET /api/v1/projects` answers `{"projects": [...], "messaging": {"platform", "state": "running" | "stopped", "exit_code": <n> | null} | null}`: the field belongs to the service, beside the projects and not inside each, and is `null` without the option (`shell_kit.projects_list`, which the MCP mode shares, is unchanged). On the service's stop, for any reason, `begin_stop` runs first (close the child's stdin, SIGTERM to its process group by the group id its own session made), then the service ends its own runs, then `finish_stop` waits up to `BRIDGE_STOP_WAIT` = 150 s (above the bridge's own 120 s wait for its jobs) and sends SIGKILL to the group if the child is still alive. The service cannot know which model jobs a killed bridge was running (its output is not read), so the line says "unknown": the containers such a bridge started stay until removed by hand or by a later `stop-runs --all`; a `stop-runs` of another process does not reach them. The service and the bridge each hold their own model slot per project, in memory; only the project's file locks keep two router runs apart. An upgrade or restart of the service restarts the bridge, and a bridge started by hand cannot run beside the service's child for the same platform (the second exits 4).

## The channel policy

### Groups, ceiling and defaults

The `channels` column of the table (`runtime/operations.py`) is the **ceiling** of a channel. A project's `docs/workbench/runtime.json` may narrow it with named groups, `"channels": {"page": [...], "mcp": [...], "messaging": [...]}`, and never widens it; like every key of the file, a change takes effect only after `accept-config` is typed in the terminal. `runtime/project_config.py` (`_channels`) refuses an unknown group, a group none of whose operations the channel's ceiling lists, `approve-effects` anywhere but the page, a `page` or `mcp` list without `read`, and an entry for `chat` or `terminal` (neither is ever narrowed: the conversation's input is local access, equal to the terminal).

The groups are a closed list in `operations.GROUPS`, a pure literal, and every row the page, the MCP mode or messaging may call is in exactly one: `read` (`status`, `progress`, `pending`, `task`, `agents`, `costs`, `skills`, `artifacts`, `artifact`, `flows`, `conversation`, `connections`, `version`, `config`, `commands`, `artifact-raw`), `talk` (`say`, which also creates and routes the requests a line makes), `answer`, `release`, `request` (`request`, `route`), `approve-plans`, `approve-acceptances`, `approve-effects` (page only), `go-ahead`, `reject-cancel`, `retry`, `set-mode`, `dispatch`, `documents` (`sync`, `hand-over`), `verdict`. A group is valid on a channel when one of its operations is in that channel's ceiling; it then covers the ceiling's share.

| Channel | With no entry in `channels` | Narrowed by |
|---|---|---|
| `terminal` | the whole ceiling, always | never |
| `chat` | the whole ceiling, always | never (an error to name it) |
| `page` | the whole ceiling | `channels.page`, which must list `read` |
| `mcp` | the whole ceiling | `channels.mcp`, which must list `read` |
| `messaging` | **closed**: `read`, `talk`, `answer` (`operations.DEFAULT_POLICY`) | `channels.messaging`: approving, releasing, rejecting, cancelling and retrying are turned on one group at a time |

### One helper, and every place it runs

`operations.permitted(op, channel, policy, kind=None)` is pure; `operations.refusal(op, channel, policy, kind=None, go_ahead=False)` returns the sentence "/<operation> is not enabled for this channel; the project's configuration (channels.<channel>) turns it on", or `None`; the caller raises `OpsError` with code 1. It runs in code, never in a prompt:

| Where | What it checks |
|---|---|
| `runtime/service.py` `_policy_refusal` | every route of the page, after the query is read and before the bytes of an upload are written and before a job starts: a refused route is `409` `refused`, takes no model slot, writes nothing. A read returns first; a configuration that is not accepted is left to the operation (`412`) |
| `runtime/mcp.py` `_refuse_by_policy` | each `tools/call`, per project, before a job starts. `tools/list` still shows the ceiling's tools |
| `runtime/ops_say.py` `_say_command` | a command typed into `say`, under the channel that carries the line (`page`, `mcp` or `messaging`, never `chat`) |
| `runtime/ops_waits.py` `only_on_plans` (called from `ops.approve`) | approval of a plan, an acceptance (and an effect, for a channel that may approve one at all), and a non-empty `go_ahead` (which needs the group `go-ahead` too) |
| `runtime/ops_config.py` `set_mode` | the direction of a mode change from the page (below) |
| `runtime/ops_say.py` `_drain_refusal` | a queued entry, again when the page's queue is drained (below) |
| `runtime/messaging_bridge.py` `Bridge.allow` / `run_op` | every operation the bridge calls, and the card it draws |

The policy is read from the project's accepted configuration at each call (`Bridge.settings` asks `ops.config` every time), so a change the person accepted takes effect without a restart, and a configuration that is not accepted refuses everything.

**The brakes.** `operations.BRAKES = ("cancel", "set-mode")`: on the page, `cancel` and a move **down** of an agent's mode are permitted whatever the policy says, `--lan` included, so a person who has lost trust can always stop work from the page; a page policy may omit them without error. A move **up** is refused unless the policy lists `set-mode`; the direction is known only after the mode is read, so `ops_config.set_mode` checks it before its lock and any write. The brakes do not leak to other channels: `cancel` on `messaging` still needs `reject-cancel`.

**The queue's stored group.** Only the page queues a line or a route while a run holds the project. Each queue entry stores the group that created it (`talk` for a line and for a request a line made, `request` for a route the page asked for); `route_queued` re-checks that group under `page`, with the policy as it is at drain time, before it answers the line or routes the request. A refused entry gets a stored reply with the sentence and leaves the queue; an entry queued before the group was stored is checked as `talk` (a line) or `request` (a route), under `page`.

### Approvals are bound to what the person saw

| Decision | What the person's tap or command is bound to | Where |
|---|---|---|
| A plan | The plan's own hash. The card is bound to `payload.plan_sha256`; the tap or `/approve <id>` sends the hash the ledger recorded; `ops.approve` refuses a plan whose tasks no longer have the hash it states or that differs from the one given; and from `messaging` a plan **cannot be approved without a hash** ("a plan is approved from a messaging app only with its hash") | `messaging_cards.content_sha256`, `messaging_bridge.approve`, `ops_waits.only_on_plans`, `ops.approve` |
| An acceptance | The content of the card. An acceptance has no hash, so the bridge compares the sha256 of the decision's text now with the hash recorded for the card; when they differ it approves nothing, replies "This decision changed since you saw it." and sends the new card | `messaging_bridge.approve` |
| An effect | Never from a line or a messaging app. The card ends with the exact command, with its hash, in single backticks (a command that holds a backtick is wrapped in a longer run); approving is typing it in the terminal or clicking on the page. A line typed into any channel is refused with the sentence that names the terminal and the command, whatever the policy | `messaging_cards.build`, `ops_say._say_command`, `ops.approve`, `operations.EFFECT_CHANNELS` |
| A typed `/approve 12` | The newest card of decision 12 in that chat; with none, "Send /pending first, so you see what you approve." The bridge reads these commands itself and never passes `/approve` to `say`; an `/approve` that does reach `say` from `messaging` is answered "use the card's button, or /approve <id> as the whole line" | `messaging_bridge.act`, `ops_say._say_command` |
| A tap of an old card | The ledger finds the card by action id and chat; if the sender is not listed for that card's project, nothing happens; a card it cannot find is "no longer valid" | `messaging_bridge.tapped` |

### What the page reads

The service's own `GET /projects` adds, per project, `"permissions": {"channel": "page", "allowed": [...]}`, or `null` when the configuration is not accepted (`service._permissions`, built from `operations.permissions`, in the handler and not in `shell_kit`). `allowed` is in the table's order and holds the plain name of every operation the page may call, except `approve` and `set-mode`, which are pairs: `approve:plan`, `approve:acceptance`, `approve:effect`, `approve:go-ahead` and `set-mode:down`, `set-mode:up`; `cancel` and `set-mode:down` are always there. The answer of `commands` leaves out the commands the page's policy refuses (`/new` follows `talk`, `/help` stays).

`interface/js/permissions.js` is the page's side: no network, no DOM; `can(project, op, kind)` looks a name up in that list. A project entry without the key, with `null`, or with a shape that is not a list allows everything, so the page never hides a control because of a shape it does not know. The controls (`floor/cards.js`, `cards/plan.js`, `cards/plan-waits.js`, `floor/task-actions.js`, `floor/agent-tab.js`, `views/lobby-composer.js`, `views/lobby.js`, `views/lobby-request.js`) draw only what the list allows and say on one line what is turned off; `cancel` and `setMode` are exempt from the check as brakes. A test ties the write functions of `interface/js/api.js` to the module's `OPS` and `EXEMPT` maps so a new one cannot be added without a decision. The page decides nothing: a write the page still sends against the policy is refused by the service with `409`, and the service's check is the authority. The policy governs a person's requests, not the dispatch loop the service runs on its own timer.

## The messenger interface

### The class and its resolution

A messenger is a provider of the class `messenger:<platform>`, in `providers/messenger/<impl>.py`. The class is one the runtime uses, not one a skill may require, so on purpose it is not in the class table of `contracts/environment.md` (which skills copy); it is documented in [providers/CONTRACT.md](../../../providers/CONTRACT.md). The part after the colon is handed to the script as `--platform`; each script declares the platforms it serves on one top-level line, `PLATFORMS = ("<platform>",)`, which `providers/resolve.py` reads as text. The variables `MESSENGER_<PLATFORM>_PROVIDER`, then `MESSENGER_PROVIDER`, choose among several; one candidate is chosen on its own. The bridge names no implementation.

`resolve.py` has two ways to run a provider: `call(cls, verb, args, ...)`, one JSON object per process, and `start(cls, verb, args, ...)`, which returns the running `Popen` of a long-lived verb (binary stdin, stdout and stderr pipes, its own session, no file descriptor of the caller). `interpreter_for(path)` picks the interpreter: the caller's own for a header with `# dependencies = []`, otherwise `uv run`, and `uv run --locked` when `<script>.lock` sits next to the script. The exit codes of a verb map to `ProviderCallError.kind`: 2 `usage`, 3 `not-configured`, anything else `failed`, and a timeout `timeout`.

### Capabilities and the neutral message

`capabilities --platform <p>` prints `max_text`, `buttons`, `max_buttons`, `max_button_label`, `lists`, `max_list_rows`, `url_buttons`, `reply_context`, `documents` and, optional, `listen` (absent means false). `Messenger.capabilities` reads them once and checks every key's type.

The neutral message the bridge sends is `{"text", "actions": [{"id", "label"}], "link": {"label", "url"} | null, "document": {"name", "text"} | null}`, where the text is Markdown as the agents write it and the action ids are `<seq>:<operation>` made by the bridge. `messaging_cards.build` makes it from a pending decision:

- a header `<project name> · <kind> #<id>`, then the body, then a footer;
- **actions**: one for each resolution word of the decision whose operation the policy permits (approved and accepted are `approve`, rejected `reject`, released `release`), in the order approve, release, reject; an effect is never offered an approval; a question is answered by replying to its card, when the policy permits `answer` and the platform keeps reply context;
- **folding**: buttons are drawn only when the platform declares them, and only as many as `max_buttons`; the rest become typed lines in the footer, "Send /approve 12", which always work. What the **policy** refuses is neither drawn nor offered as a line: the card says "Act on it on the page or in the terminal.";
- **link**: a page link (when `messaging.page_url` is set and the card is an effect, has a refused action, or is in `count` mode) becomes a link button where the platform has `url_buttons`, else the URL in the footer;
- **text**: with `notices: "text"` the decision's text, cut to `max_text` with "(continues on the page)" or, where the platform takes documents, a short body plus the whole text as a document; with `"count"`, "A <kind> waits for you." and no project text;
- at most 10 cards per project per tick, then the line "And <n> more waiting. Send /pending to list them."

### The per-call verbs

The first mode, used by Telegram, runs one process per call. `receive --platform <p> --offset <n> --timeout <s>` returns `{"updates": [{"update_id", "sender", "chat", "private", "text", "action", "action_ref", "reply_to"}], "next_offset"}` (long polling where the platform has it); `send --platform <p> --chat <id> --message-file <f>` reads the neutral message from a file of mode 0600 that the bridge removes afterwards and prints `{"message_id"}`; `ack --platform <p> --action-ref <ref>` acknowledges a tapped button. `send` has no `--confirmed` and no idempotency key (which CONTRACT.md asks of other verbs that send): the bridge is the only caller, sends only to a chat of the project's accepted `messaging.senders` list, and keeps the ledger. A provider refuses a message beyond its capabilities (exit 2); the bridge never sends one.

### The listen mode

A platform that must stay connected (a gateway that delivers taps only on its open connection, a client with one live session, a webhook server) declares `"listen": true` and implements `listen --platform <p>`. The bridge starts it once, through `resolve.start`, and keeps it (`ListenSession`, `runtime/messaging_provider.py`).

- **Protocol.** JSON lines on binary standard input and output, UTF-8 written as ASCII (`ensure_ascii=True`), one flush per line, at most 1 MiB per line. The bridge writes `{"id", "op": "send", "chat", "message"}`; the provider writes `{"event": "ready"}`, `{"event": "update", "update": {...}}` (the shape of one element of `receive`), `{"event": "error", "kind", "reason"}` and the answers `{"id", "ok": true, "message_id"}` or `{"id", "ok": false, "kind", "reason"}`. Nothing else is ever written to stdout. There is no `ack`: the provider acknowledges its own taps at once and emits `action_ref: null` (the bridge forces it to null); no offset applies.
- **Validation.** The reader drops, and logs by class, a line over the limit, one that is not JSON or not an object, an unknown event, an answer to an unknown id, and an update that is not private or lacks a non-empty string `sender` or `chat`. Updates feed a bounded queue (1000; the newest are dropped when full, with one line).
- **Lifecycle.** One supervisor starts the process, waits for `ready` (180 s; missing it counts as a crash and kills the group), and decides after an exit: **2 or 3 stops the bridge** (exit 3, with the reason of the last error event, else the redacted stderr tail, else `exit <n>`); anything else restarts it after a backoff of 1, 2, 4 ... up to 300 s (the first wait again only after 10 minutes ready), at most 200 starts per rolling 24 hours for each bridge process, after which the bridge stops with a sentence (a platform may reset a credential that connects too often). Notices wait until `ready` and are looked at again at once when it comes back. A watcher on `proc.wait()` detects an exit, kills the leader's group and fails every waiting request. Stderr is drained, the last 300 characters kept and shown only after `scripts/redact.py`, and only when no error event gave a reason.
- **Stop.** The bridge closes the session after its jobs have ended: stdin closed, then 10 s, SIGTERM to the provider's group, 5 s, SIGKILL, by group id only. A provider must exit **within 5 s of the end of its standard input**: it runs in a session of its own, so killing the bridge never reaches it, and the end of its stdin is what stops it.
- **Rules for a provider.** Duplicate fd 1 for the protocol and point fd 1 at stderr; never `setsid`; interactive pairing is a separate verb run in a terminal, never inside `listen`.

### The `paused` and `deferred` kinds

- **`paused`** is an error-event kind: the platform session is gone and only the person can mend it (a logged-out WhatsApp device). The provider writes the event and exits 3. This is the one exit 3 that does not stop the bridge: it logs the redacted reason, waits 5 minutes (a close interrupts the wait), and starts the provider again; that start is not charged to the 200-starts ceiling and the backoff is left alone; the line is written again every 24 hours while it stays paused and again after the provider has been connected in between. Cards wait as for any provider that is not ready.
- **`deferred`** is an answer kind only: `{"id", "ok": false, "kind": "deferred", "reason"}` is a platform that lets a business write first only inside a window (the official WhatsApp API: 24 hours after the person's last message) saying it cannot take the card now. It is not an error and never a reason to stop or restart. The bridge records nothing in the ledger for that card, so it is offered again at the next notice period and at once when the person next writes from that chat (`Bridge.deferred_chats`), and it logs one line for a card and a chat at most every 24 hours.

### At-least-once delivery

A send in flight when the provider dies fails, and its card is sent again after the next `ready`. The first copy, if it was delivered, has buttons the ledger has no record of, which answer the stale-button sentence. What the platform delivers to a linked device while the provider is paused or restarting is delivered when it reconnects, each approval still bound to the card the person saw. Duplicates are therefore possible; a wrong approval is not, because the binding is the hash or the card's content, not the delivery.

### Rendering per platform

The text is Markdown. Each provider renders the subset its platform can show, with everything escaped first so text from a project can never become markup, or sends it plain.

| Platform | Rendering |
|---|---|
| Telegram | `render_html` into Telegram's HTML parse mode: fenced blocks, table lines and quote runs found on the raw text, everything else escaped with `html.escape` before any mark; headings bold, bullets a dot, `**x**` bold, `~~x~~` strike, `` `x` `` code, fences and tables `<pre>`, quotes `<blockquote>`; no single-mark italics; a link shown as `text (url)`, never an anchor; previews off on every message; on a 400 "can't parse entities" one plain resend with the same keyboard |
| Discord | Discord renders Markdown itself; `render_discord` keeps the text and makes it safe outside code spans and fenced blocks: masked links to `text (url)`, mention openers escaped, `||` escaped, table runs fenced; `allowed_mentions` is empty and embeds are off |
| WhatsApp (unofficial) | In the Go program (`render.go`): `**x**` to `*x*`, `~~x~~` to `~x~`, headings to `*text*`, links to `text (url)`, tables fenced, code byte for byte; cut at 4096 with "(continues on the page)" |
| WhatsApp Cloud API, Twilio | The shared renderer of `whatsapp_meta.py` with the platform's limit, held to the Go renderer on a shared corpus (`providers/messenger/tests/whatsapp_render_corpus.json`) |

### How to add a platform

Add one file, `providers/messenger/<impl>.py`, that declares `PLATFORMS` and implements the four subcommands (or `listen` and `capabilities`), register its credential in `providers/secrets/resolver.py` and `contracts/secrets.md` (store usernames only; a provider may not import `runtime/`), and add offline tests in `providers/messenger/tests/` with the network patched out. Nothing in the bridge changes: the platform's name goes in `runtime.json` (`messaging.senders.<platform>`, a lowercase word with hyphens) and on the bridge's `--platform` flag. A dependency worth a hash check is locked with `uv lock --script`.

## The platforms

| | Telegram | Discord | WhatsApp, unofficial | WhatsApp Cloud API | WhatsApp through Twilio |
|---|---|---|---|---|---|
| Platform name | `telegram` | `discord` | `whatsapp` | `whatsapp-cloud` | `whatsapp-twilio` |
| Provider | `telegram.py` | `discord.py` (+ `discord.py.lock`) | `whatsapp.py` + Go program `whatsapp/` | `whatsapp-cloud.py` | `whatsapp-twilio.py` |
| Mode | one process per verb | listen | listen | listen | listen |
| How it receives | `getUpdates` long polling | Gateway (WebSocket), direct messages | linked-device session of a Go client | webhook (local server, public HTTPS) | webhook (local server, public HTTPS) |
| How it sends | Bot API `sendMessage` | REST `POST` on the DM channel | the Go client | Graph API | Messages API |
| Buttons | inline keyboard, up to 6, label 40, URL button | up to 5, label 80, link button | none (typed commands) | up to 3 reply buttons per message | typed commands until three quick-reply template ids are recorded, then up to 3 |
| Documents | `sendDocument` | `.txt` in the same message | text/plain or text/markdown after the text | media upload after the text | no (text cut at 1600) |
| `max_text` | 4096 | 1900 | 4096 | 4096 | 1600 |
| Sender id | numeric user id | user id | phone digits | phone digits (and, if used, a business-scoped id) | phone digits (and, if used, a business-scoped id) |
| Secrets (store usernames) | `messenger-telegram` | `messenger-discord` | none: the session file | `messenger-whatsapp-cloud`, `-app-secret`, `-verify-token` | `messenger-whatsapp-twilio-api-key-sid`, `-api-key-secret`, `-auth-token` |
| Public HTTPS address | no | no | no | yes | yes |
| Live test | no result recorded in the sources | run by the maintainer; findings below | an attempt showed the number must be separate | **not tested live** | **passed** (text and typed commands); buttons not tested |

### Telegram

`telegram.py` serves `telegram` over HTTPS with the standard library. It is the one provider that uses the per-call verbs: `getUpdates` long polling (the provider caps the wait at 50 s; the bridge asks 25 s; never a webhook), `sendMessage` with an inline keyboard (the action ids are the buttons' `callback_data`, at most 64 bytes), a URL button for the link, `sendDocument`, `answerCallbackQuery` for `ack`. The sender and chat are the numeric ids, and `private` is true when the chat type is `private`. A `409` of `getUpdates` is told in two: one whose description says another `getUpdates` request terminated this one gives "another program is reading this bot's updates (a second bridge, or another tool with the same token)"; any other gives the sentence that tells the person to remove the webhook; both exit 3, since a provider has no exit 4. The token is the secret `MESSENGER_TELEGRAM_BOT_TOKEN` (store username `messenger-telegram`); Telegram carries it in the request path, so every error is built from the class of the exception, the status and the service's own description, with anything shaped like a token removed. Rendering is above. A chat with a bot is not end-to-end encrypted.

### Discord

`discord.py` serves `discord`, with buttons, through the Gateway, only in the listen mode (`receive`, `send` and `ack` exit 2). It uses the standard library for HTTP and `websockets` 16.1.1, pinned in the script's header, imported only where the Gateway opens, and **hash-locked** in `discord.py.lock`, which `resolve.py` honours by starting the script with `uv run --locked` (a stale lock is refused, not re-resolved). No port is opened. The Gateway is a pure state machine over a fake clock in the tests: Hello, Identify with the intent `DIRECT_MESSAGES` only, heartbeats with jitter, Resume after a drop, op 7 and a missing acknowledgement closing with 4000, one Identify per 5 s, `session_start_limit.remaining` read before each Identify (below 50 is an error and exit 3), close codes 4004 and 4014 exiting 3 and 4010 to 4013 exiting 2. **Direct messages only**: a message in a server channel, from a bot or a webhook is ignored; `chat` and `sender` are both the person's user id, never the DM channel id, and the provider opens the DM channel itself when it sends. A tap (an interaction of type 3 in a DM) is acknowledged at once with callback type 6 before the update is written. A bot can message a person only when they share a server with it (or the application is installed to the person) and the person allows direct messages from that server; Discord otherwise answers 403 (error 50007), the send fails with a sentence, and the bridge keeps running. The token is `MESSENGER_DISCORD_BOT_TOKEN` (`messenger-discord`), masked in every error path together with any Discord token shape. Discord messages are not end-to-end encrypted.

### WhatsApp, unofficial client

`whatsapp.py` serves `whatsapp` through [whatsmeow](https://github.com/tulir/whatsmeow) (MPL-2.0), an unofficial WhatsApp Web client, in a small Go program in `providers/messenger/whatsapp/` that is **built from source on the machine that runs the bridge** and never downloaded. It works only in the listen mode and has **no buttons**: every action is a typed line.

- **Build and pin.** `whatsapp.py build` builds the program into `<state folder>/whatsapp/bin/` with `GOENV=off`, `GOFLAGS=-mod=readonly`, `GOWORK=off`, `CGO_ENABLED=0` and the settings that would weaken the checks cleared, runs `go mod verify`, and records `build.json` (mode 0600) with the hashes of the binary, `go.sum` and the sources. `listen` refuses to start when the program or its sources differ from the record, and says to run `build` again. The pure-Go SQLite driver means no C compiler. `go.sum` holds the hash of every module; CI runs `go mod verify`, `go vet` and `go test`.
- **Pairing, `status`, `whoami`.** `pair --phone <digits>` prints a pairing code (no QR code) and the steps; it refuses an already paired session. `status` prints whether the session is paired and never connects. `whoami` prints the phone digits of each one-to-one sender that writes within a window (default 120 s), on a terminal only, never sends, and refuses while a bridge holds `messaging-whatsapp.lock`.
- **A separate number.** The bridge is a linked device of the number it pairs. The person writes to it from their personal WhatsApp as to any contact. Pairing the person's own number would make the bridge a linked device of the personal account, which cannot talk to itself: use a separate number you can afford to lose.
- **Identity.** An update is made only for a text message in a one-to-one chat from another person, not from the linked device itself, not a group, broadcast list, status or newsletter, not an edit, reaction or protocol message, not a medium. `sender` and `chat` are both the phone digits (a hidden LID address is resolved to the number, else the message is dropped with a line that carries no id). Senders in `runtime.json` are digits only, with the country code and no `+` (for example `5511900000000`); `whoami` prints the exact ones.
- **Session and `paused`.** `session.db` (0600, in `whatsapp/`, mode 0700) holds the keys of a linked device: whoever holds the file can read and send as that number. A logged-out device makes the provider write a `paused` event naming `pair` and exit 3; the bridge waits and asks again. A second program using the same session is not a pause: the provider says so and the bridge stops. A refused client version stops it the same way, with a sentence to update and build again.
- **Licences and risk.** The program links whatsmeow (MPL-2.0) and, through it, `go.mau.fi/libsignal` (GPL-3.0). The repository carries source only; do not hand a built binary to anyone without meeting the GPL-3.0. WhatsApp's terms bar automation and unofficial clients, so the number may be restricted or banned; the protocol is not published and may change under the client.
- **Privacy.** Messages are end-to-end encrypted between WhatsApp's clients; this program is one of them and decrypts them on the machine that runs the bridge. WhatsApp sees who writes to whom and when.
- **Tested.** Offline (Go and Python). The sources record the need for a separate number from a live attempt; no other live result is recorded for this platform.

### WhatsApp Cloud API (Meta direct)

`whatsapp-cloud.py` serves `whatsapp-cloud`, the official WhatsApp Business Cloud API, with buttons, only in the listen mode, with the standard library only. It shares its server, window rules, state store, identity map and renderer with the Twilio provider through `whatsapp_meta.py` (loaded by path; its underscore keeps the resolver from listing it).

- **Receives** through a small HTTP server on `127.0.0.1:<port>` only (default 8787): `GET` and `POST` on a random 32-hex path (any other path 404, other method 405), `Content-Length` required, 3 MiB cap, a total deadline of 10 s per request, at most 8 requests at once, no request in any log. The handshake needs `hub.mode=subscribe` and the verify token, compared as bytes in constant time. A `POST` is accepted only with `X-Hub-Signature-256: sha256=<HMAC-SHA256 of the raw body keyed with the app secret>` over the raw bytes (a re-serialised body fails); a valid call is processed (the update line is written and flushed, `seen.json` persisted) **before** the 200. A message id is remembered 8 days, so Meta's retries and duplicates are dropped, also after a restart.
- **Sends** with `POST` on the Graph API (`graph.facebook.com/v25.0/<phone_number_id>/messages`, `Authorization: Bearer`), no link preview. A card whose rendered text is at most 1024 characters is one interactive message with up to 3 reply buttons (title cut to 20 characters, made distinct); a longer one is a text message followed by a message with the fixed line "Choose an action for the card above." and the buttons. The answered id is the text message's. A document is uploaded and sent after the text.
- **The window.** WhatsApp lets a business send free-form text only within 24 hours of the person's last message. The provider records, per chat, the time of the last message as the message's own timestamp (`window.json`), and sends a card only while that is under 23 h 30 min old. Outside it a send is not made: with an approved template (optional), the provider sends it once per closed window and again at most every 7 days; without one it sends nothing and logs one line per chat per 24 hours; either way the send answers `deferred`. A late error 131047 (reported later as a `failed` status for a message the process sent) closes that chat's window and sends the template, still once.
- **Identity.** `sender` and `chat` are the phone digits in `from`; for a person who uses a WhatsApp username Meta may send only a business-scoped id, in which case the digits remembered for that id (30 days, `identities.json`) are used, else the id. List the digits and, if needed, the id in `messaging.senders.whatsapp-cloud`.
- **Secrets**: the system user's token, the app secret (signature only) and the verify token (handshake only). **State**: `<state folder>/whatsapp-cloud/` (0700; files 0600) holds `settings.json`, `seen.json`, `window.json`, `identities.json` with phone numbers: exclude it from backups.
- **Errors.** 190, 0 and HTTP 401: an error event `not-configured` and exit 3; rate limits are `failed` with a wait; nothing ever carries a response body.
- **Tested.** Offline (a local HTTP client against the server on port 0, the Graph API replaced by a fake opener, a shared render corpus). **Not tested live**: the Meta side needs a number off the WhatsApp app and a developer account the maintainer did not yet have.

### WhatsApp through Twilio

`whatsapp-twilio.py` serves `whatsapp-twilio`: WhatsApp reached through a Twilio WhatsApp sender, only in the listen mode, standard library only, sharing `whatsapp_meta.py` with the Cloud provider.

- **Receives** on the same kind of server, `POST` only, a body cap of 256 KiB. `X-Twilio-Signature` is `base64(HMAC-SHA1(Auth Token, URL + the form parameters))` computed as Twilio's own validator does: the body is read as a UTF-8 form with blank values kept, names sorted, each name's values sorted with a repeated value counted once, over UTF-8 bytes; the URL is the stored `public_url` plus the query exactly as received, accepted with and without `:443`; the comparison is on bytes in constant time. A missing or wrong signature is a 403 and nothing is processed. The answer to a valid call is an empty TwiML `<Response/>`. Only calls whose `AccountSid` and `To` are the configured account and sender are read; a `MessageSid` is remembered 8 days.
- **A tap.** When `ButtonPayload` is present the provider emits only the action, never `Body`: the template's `see-decisions` becomes `/pending`; `<seq>:<operation>` becomes the action of a card button; any other payload is ignored.
- **Sends** a form `POST` to `Messages.json` with HTTP Basic using a **restricted API key**; the Auth Token never sends. `max_text` is 1600 and `documents` false: the bridge cuts a card to 1600 and splits replies itself. Twilio has no reply-to parameter.
- **Buttons are off until configured.** `capabilities` reports `buttons: true` only after `setup` records the ids of three quick-reply Content templates the person created (one, two and three buttons); then a short card is one Content message and a longer one is text followed by a message with the fixed buttons line. If Twilio refuses the variables (error 21656) the provider logs it once and falls back to the text plus the fixed-body buttons message. This path has not been tested live.
- **The window** is the same rule as the Cloud provider's, with the time of receipt as the clock (Twilio sends no timestamp). Error 63016, from the send or a per-message status callback for a SID this process sent (`sent.json`, 2 days), closes the window and sends the template once. The person must leave the status callback URL of the sender empty: the provider passes it on every message and both together would deliver each report twice.
- **Costs.** Twilio charges per message, inbound or outbound, plus Meta's fees for a template outside the window and a small fee for a failed message; figures are in the provider's README, from Twilio's pricing page at the time of writing.
- **Messages lost while asleep.** Twilio retries a webhook once, and only on a connection failure. A message the person sends while the machine is asleep or offline is lost for good, unlike Meta's retries of up to 7 days. There is no catch-up; the person writes again.
- **Tested.** Offline, including Twilio's published signature vector. **Passed the maintainer's live test** (text in and out, typed commands). Not tested live: card buttons, the second published signature vector (its parameters are not in the sources), the template path after 24 hours.

## Public HTTPS for webhooks

Only the two official WhatsApp paths need it. Telegram and Discord are reached by the bridge's own outbound connection; the unofficial client is one too. Meta and Twilio, instead, **call** the person's machine: the webhook must reach the provider's local server over HTTPS from the internet. The workbench does not choose how: any public HTTPS address that forwards `https://<host>[:<port>][/<prefix>]/<path>` to `http://127.0.0.1:<port>/<path>` works, with `<path>` the random 32-hex path `setup` makes, kept by the proxy (an address prefix is removed by it). A tunnel must forward to `127.0.0.1:<port>`, the port `setup` stored: a tunnel started for another port answers 502.

- **`--public-url`.** `setup --public-url https://<host>[:<port>][/<prefix>]` takes the base address (https only, a host of letters, digits, dots and hyphens, an optional port, an optional prefix; no query, fragment or credentials); `--public-host <host>` is shorthand. The order is the flag, then the address saved by an earlier `setup`, then a Tailscale hostname (only if the `tailscale` command is found); otherwise exit 2 with a sentence that says what to give. A saved tunnel address is never silently replaced. `setup` prints the callback URL for Meta or Twilio and the line `Expose: https://<host>/<path> must reach http://127.0.0.1:<port>/<path> (the path kept)`; the Funnel command is printed only when Tailscale was used. Twilio signs the exact URL, so `setup` stores it whole and the provider checks the signature against that text.
- **Who can read the traffic.**

| Option | Who can read the messages in transit | Address | Account |
|---|---|---|---|
| Tailscale Funnel | nobody in between: TLS ends on your machine, Tailscale's relays carry the encrypted traffic | stable | a Tailscale account and its macOS app |
| Cloudflare Tunnel | Cloudflare: TLS ends there | stable, a name on a domain you own | a Cloudflare account and a domain |
| ngrok | ngrok: TLS ends there | changes at each start on the free plan | an ngrok account |
| A reverse proxy on a server you run | nobody in between: TLS ends on your server | stable | the server |

- **The secret path as defence in depth.** The signature is the only authentication: Meta signs the raw body with the app secret and Twilio signs URL plus parameters with the Auth Token; no tunnel or identity header reaches the service. The random path keeps the endpoint out of a casual scan, and the provider's server binds `127.0.0.1` only so nothing else on the network can reach it. A Funnel hostname is published in Certificate Transparency logs; the path is not.
- **If the address changes**, run `setup` again with the new `--public-url` and update the webhook in Meta's app settings or the Twilio Console.

## Security model

### Hard limits that live in code

Principle 11 of [AGENTS.md](../../../AGENTS.md): what must never happen is prevented by code or structure, not by a prompt or a test. For the messaging channels:

| Limit | Where it is enforced |
|---|---|
| An effect is never approved from a messaging app or a line | `operations.EFFECT_CHANNELS`, `ops.approve`, `ops_waits.only_on_plans`, `ops_say._say_command` (the kind is read first), the card of an effect has no button |
| A plan is approved only with its hash; an acceptance only if its card still matches | `ops_waits.only_on_plans`, `ops.approve`, `messaging_bridge.approve` |
| Only listed senders, only private chats | `Bridge.handle` (`projects_for`, `private`, `chat == sender`); an update that is neither is dropped with no reply and no id logged; a card of one project is acted on only by that project's listed senders (`listed_in`) |
| The channel policy | `operations.permitted` and `refusal`, run by the service, the MCP mode, `ops_say`, `ops_waits`, `ops_config` and the bridge ("The channel policy"); the policy comes from the accepted configuration only |
| Webhook authentication | Meta: HMAC-SHA256 of the raw body, constant-time compare, 401 otherwise; Twilio: HMAC-SHA1 over the stored URL and the sorted parameters, 403 otherwise; the verify token for the handshake |
| Bind address and request limits | the webhook server binds `127.0.0.1` only; body caps (3 MiB, 256 KiB for Twilio), a 10 s deadline, 8 concurrent requests, a `Content-Length` requirement, the path matched on the raw target; the bridge's own limits: protocol lines 1 MiB, the update queue 1000, 10 cards per project per tick, 200 provider starts per rolling 24 hours |
| Redaction | a provider builds errors from the class of an exception, the status and the service's description, never a body or a token; `scripts/redact.py` masks credential formats in the reason of a stopped listen provider and in the paused line; `whatsapp_meta.redact` masks secrets, long tokens and runs of eight digits; Discord masks the exact token and token shapes; Telegram removes anything shaped like a token |
| Private files | the state folder 0700, checked (`lstat`: real directory, owned, no group or other bits); lock `O_NOFOLLOW`, 0600; ledger and message files 0600; a provider's folder 0700 and files 0600; the WhatsApp Go program starts with `umask 077` |
| No credential in a run | the bridge never reads or passes a credential: `Messenger._call` passes none, a provider reads its own through `providers/secrets/resolver.py`; a model run is the container's, which holds no credential, and the service's child gets the environment snapshot taken before any run, so a floor-model key written into the service's own environment never reaches it |
| Tests never reach the real secret store or state folder | `providers/loopback_only.py` (the guard every provider suite applies: no network but loopback, the null keyring backend, a fresh `OPENHORA_STATE_DIR` for each test) and `OPENHORA_STATE_DIR` set in every runtime test that reaches the bridge, the ledger or the service's child |
| A dependency that holds a credential is hash-locked | `discord.py.lock`, `uv run --locked`; the Go program by `go.sum` and `go mod verify` |

### Residual risks, stated plainly

- **Platform servers see the text.** What the person writes, and every notice in `text` mode, passes the platform's servers: a Telegram bot chat and a Discord direct message are not end-to-end encrypted; Meta processes the messages of the Cloud API, and Twilio and Meta both those of the Twilio path. `count` mode keeps notices free of the project's text, but replies to what the person writes still carry text. A person who wants more safety leaves the policy closed and uses the page. In `count` mode an effect's card still carries the approve command, which holds the project's folder path and the effect's hash.
- **The unofficial client's terms.** WhatsApp bars automation and unofficial clients; the number may be restricted or banned, and the protocol may change under the client. The session file is the account.
- **A tunnel can read the traffic** when its TLS ends at the vendor (Cloudflare Tunnel, ngrok). A Funnel hostname is public (Certificate Transparency); the signature, not secrecy of the hostname, is the defence.
- **At-least-once duplicates.** A card or a reply may arrive twice; the second copy's buttons answer the stale-button sentence. This is safe because every approval is bound to a hash or to the card's content.
- **Messages lost while the machine sleeps** on the Twilio path (a single retry on connection failure only).
- **Delivery gaps by design.** A resolved decision's card is not edited; acting on it later gets the operation's refusal as the reply. A line that arrives while a run holds the project is answered busy, not queued.
- **The page does not show a paused bridge.** `GET /projects` reports `running` or `stopped`; the paused state of a listen provider is a log line only.

## Operating it

1. **Set the platform up** once, following its section in [providers/messenger/README.md](../../../providers/messenger/README.md) (the bot, the token or secrets, the pairing or webhook). Every command that reads a secret is run as `uv run --with keyring==25.7.0 python3 ...`: the `setup` and `whoami` verbs of the official WhatsApp providers read secrets, and a plain `python3` has no `keyring` library. Without it the provider says "the OS secret store is not available in this Python (the keyring library is missing)" instead of "missing or malformed".
2. **Configure the project** in `docs/workbench/runtime.json` (fictional values; nothing in it is a secret):

   ```json
   {
     "messaging": {"senders": {"telegram": ["123456789"], "whatsapp-twilio": ["5511900000000"]}, "notices": "text", "page_url": null},
     "channels": {"messaging": ["read", "talk", "answer", "approve-plans"]}
   }
   ```

   `senders` maps each platform to a list of ids with no space; `notices` is `text` or `count`; `page_url` is an `http(s)` URL or null; `channels.messaging` narrows the closed default, or turns on more of it, group by group.
3. **Accept it.** Any operation refuses a configuration whose hash is not the accepted one and prints the hash; then `python3 runtime/cli.py accept-config --project <dir> --sha256 <hash>`. A change of senders or channels takes effect only after this.
4. **Start it.** With the page: `uv run --with keyring==25.7.0 python3 runtime/service.py --project <dir> --messaging <platform>`. On its own: `uv run --with keyring==25.7.0 python3 runtime/messaging.py --project <dir> --platform <platform>`. One bridge per platform and user; set `OPENHORA_STATE_DIR` identically for the provider commands and the bridge where a provider keeps state (WhatsApp does).
5. **Check it.** `GET /api/v1/projects` (with the bearer token, from the page or a client) shows the service's `messaging` field; the bridge's first line on standard output names the projects it serves, and its log says when it skips a project.

Common errors, with their cause:

| What the person sees | Cause | What to do |
|---|---|---|
| The first messages after starting get no answer; the log says `dropped an update from an unlisted sender` | The bridge started while the project was not yet accepted (or listed no sender), so it was skipped; a message in that window is dropped like an unlisted sender's, until the next notice period serves the project | Run `accept-config`, wait up to one notice period (60 s by default), write again. Also check the sender id is the one the platform reports, not a display name |
| `skipping <name>: its configuration is not accepted ...` / `... lists no sender` | The skip rule | Accept the configuration; add `messaging.senders.<platform>` |
| `another messaging bridge already serves <platform> on this machine (its lock: <path>)` (exit 4) | A second bridge for the platform, often a hand-started one beside the service's child | Stop the other one |
| Telegram: another program is reading this bot's updates / remove the webhook | Two readers of one token, or a webhook set on the bot | Stop the other reader; delete the webhook |
| `... is not available in this Python (the keyring library is missing)` | The command was run with a plain `python3` | Re-run with `uv run --with keyring==25.7.0 python3 ...` |
| An ngrok or other tunnel answers 502 | The tunnel forwards to a port other than the provider's | Forward to `127.0.0.1:<port>` where `<port>` is the one `setup` printed in the `Expose:` line |
| A webhook call is refused with 403 (Twilio) or 401 (Meta) | The signature does not match: the stored public URL differs from the one Twilio calls, or a wrong secret | Run `setup` again with the exact address; check the secret |
| Discord: nothing arrives in a server channel | The bridge works only in direct messages | Write to the bot in a direct message |
| Discord: "Public Bot" cannot be turned off in the developer portal | The application's default install link is still set | Set the default install link to None first, then turn off "Public Bot", guild install only |
| Discord: the bot cannot open a direct message (403, error 50007) | The bot and the person share no server, or direct messages from that server's members are off | Share a private server with the bot; allow direct messages |
| WhatsApp unofficial: the bridge cannot talk to the person | The number paired is the person's own: the bridge became a linked device of their personal account | Use a separate number for the bridge |
| WhatsApp: `paused ... run pair` in the log | The device was logged out | Delete `whatsapp/session.db`, run `pair`; the bridge recovers within 5 minutes |
| `This button is no longer valid. Send /pending.` | The card is older than the ledger's record, or the bridge was restarted | Send `/pending` |
| `is not enabled for this channel; the project's configuration (channels.messaging) turns it on` | The policy lacks the group | Add the group, accept the configuration |
| "The planning agent is answering another request. Send it again in a moment." / "Still working on the last message." | A run holds the project, or the previous line is still being answered | Send again |

## Open items

- **The Meta live test.** `whatsapp-cloud` has not been run against Meta: the handshake, a signed message, a card with buttons, a tap, a document, the template after 24 hours of silence, whether `--set-path` of a tunnel reaches the service as `/<path>`, and whether Meta renders the marks the renderer writes. The setup steps are in the provider's README.
- **The second Twilio signature vector.** Twilio publishes two examples; the first is a test. The parameters of the second (a repeated `Digits` value) are not in the sources, so the rule for a repeated parameter is tested only against a reference implementation written in the test kit.
- **Buttons on Twilio** are built and tested offline and not live: the three templates, the 21656 fallback and the callback-driven resend.
- **The page state for a paused bridge.** A paused listen provider is a log line only; `GET /projects` has no state for it.
- **Telegram and Discord live results** are not recorded in the sources this page was written from; the live-test findings that exist are the ones in "Operating it".
- **Restarting a crashed bridge** and **queuing a line while a run holds the project** are not built; so is **editing a sent card** when a decision is resolved elsewhere, and **approving effects from the messaging channel** (decision M-3, an opt-in for later).
- **A Go job in CI** uses the runner's own Go instead of a pinned setup action; moving it to a pinned action is open.

## Changes

- 2026-10-13: first version, written from the code at the head of the integration branch after MSG-1 to MSG-11 (the bridge, the policy, the service's child, the listen mode, Telegram, Discord and the three WhatsApp providers) and the supervisor's record of decisions M-1 to M-37.
