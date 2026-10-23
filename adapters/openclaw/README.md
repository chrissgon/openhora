# Using the MCP mode from an OpenClaw gateway

This folder is documentation only. It is not a harness adapter: no skill of this repository runs inside OpenClaw, it has no `adapter.json` and no installer, and nothing here is measured. Running skills in it would need an adapter with its own battery of tests (the proof rule: evidence holds for one model and adapter pair), which this file is not. What it describes is narrower: a person who already runs an OpenClaw gateway can register the runtime's MCP mode as one of the gateway's MCP servers and reach a project's operations from the gateway's messaging channels.

Every statement about OpenClaw below cites its official documentation at docs.openclaw.ai, read on 2026-10-11. A point the documentation does not state is marked as a risk or left out. OpenClaw changes; read the live page before relying on a detail.

## What it gives

OpenClaw's documentation describes a gateway that connects messaging channels to an agent (home page, https://docs.openclaw.ai/, and https://docs.openclaw.ai/channels, accessed 2026-10-11). Its MCP page covers adding a stdio MCP server in Settings, from the CLI and directly in configuration under `mcp.servers`; the fields it names are a `command`, `args`, an optional `cwd`, `transport: "stdio"`, `enabled` and a `toolFilter` of `include` and `exclude` lists (https://docs.openclaw.ai/tools/mcp, accessed 2026-10-11). The page has no literal stdio example in configuration (its configuration example is an HTTP server); its stdio example is a CLI command of this form: `openclaw mcp add <name> --command <cmd> --arg <arg> --cwd <dir>`. The page also gives a check, `openclaw mcp doctor <name> --probe`, and says `openclaw mcp probe <name>` shows the tools a server advertises.

The runtime's MCP mode (`runtime/mcp.py`, described in [runtime/README.md](../../runtime/README.md), "The MCP mode") is a stdio MCP server started by its client: `python3 <checkout>/runtime/mcp.py --project <dir>`. It needs no key, no token and no network. Registered in the gateway's configuration, using the fields the MCP page names (this block is assembled from those fields and the CLI flags, not copied from an example on the page), it reads:

```json5
{
  mcp: {
    servers: {
      "openhora": {
        command: "python3",
        args: [
          "/home/demo/openhora/runtime/mcp.py",
          "--project", "/home/demo/northwind-shop"
        ],
        transport: "stdio",
        enabled: true
      }
    }
  }
}
```

Steps:

1. Configure the project and accept its configuration in the terminal first (`accept-config`). Until then every tool answers with the `412` sentence and does nothing.
2. Add the server above to the gateway's configuration (or with `openclaw mcp add`). The command must resolve in the gateway process's environment and `cwd`, if you set one, must exist (MCP page, "A stdio server does not start").
3. Apply the change: with gateway hot reload, changed servers are picked up on the next turn; otherwise the gateway needs its own reload or restart (MCP page, "Changes do not reach an active agent").
4. Confirm the result with `openclaw mcp doctor openhora --probe`, and see the advertised tools with `openclaw mcp probe openhora`. If the gateway rejects the block, trust its answer over this file.

The MCP page says a server's tools go through the gateway's normal tool profile and tool policy and that connecting a server does not bypass that policy. It does not document how the tools are named for the agent; look at the probe output. Use `toolFilter` to expose fewer tools than the list below if the person wants less.

## What the person can do through it

The tools are one per row of `runtime/operations.py` that lists the `mcp` channel, plus two of the server's own ([contracts/runtime.md](../../contracts/runtime.md), "The MCP mode"):

- Reads: `status`, `pending`, `task`, `flows`, `progress`, `agents`, `conversation`, `skills`, `costs`, `connections`, `artifacts`, `artifact`, `version`.
- Writes: `request` (a new request), `route` (route a request), `answer` (answer a question the router asked), `release` (release a draft), `say` (one conversation turn).
- The server's own: `projects` (the projects served, and whether each configuration is accepted) and `job` (ask again for a job that `route`, `release` or `say` started; these call a model, so they answer at once with a running job).

What it can never do, by code and not by instruction (decision D8): approve an effect, a plan that reaches the network or consent, accept a configuration, set a mode, run the next task, grant a standing approval, or approve an effect with its hash. Those operations have no tool. By default it also cannot approve, reject, cancel or retry anything; a project may grant it plans (with their hash), acceptances, reject-cancel and retry in `channels.mcp`, and accepting that widening needs the hash of the widening list (`accept-config --widen`), so the person chooses it once and in the terminal. A command typed into `say` is refused the same way: `/approve`, `/reject`, `/retry` and `/cancel` answer that the action is done in the terminal or on the page. The channel is fixed by the server (`mcp`); a client cannot name another. An effect (a publication, a pull request, a sent message) is approved only with its hash, in the terminal or on the page, or on a messaging app the project grants that effect's word; never from here, whatever the configuration lists.

## Risks

State these to the person before they enable it.

- **A model sits between the channel and the tools.** The gateway's agent decides which tool to call, and the text a tool returns (a document, a reply, a comment from the project) goes back into that model's context. That text can carry external content. A prompt injection could make the model request work, route it, answer a router question, release a draft (which runs the router and readies dependent tasks) or send a line through `say`, all of it within the project's configured caps. It can never approve, because no approval tool exists. OpenClaw's own pages say any content the bot reads can carry adversarial instructions and that its wrapping of external content complements, and does not replace, access controls and tool restrictions (https://docs.openclaw.ai/gateway/security/prompt-injection, accessed 2026-10-11).
- **The project's text leaves the machine.** What a tool returns passes through the servers of the messaging channel and the gateway's model provider. Do not serve a project whose text must not leave the machine. This follows from how a gateway works; the documentation pages cited here do not describe it as a single statement.
- **The WhatsApp channel uses an unofficial client.** OpenClaw's WhatsApp page says the channel runs through WhatsApp Web (Baileys) and that the gateway owns the linked session; it does not mention the official WhatsApp Cloud API and carries no warning about restrictions (https://docs.openclaw.ai/channels/whatsapp, accessed 2026-10-11). Our own risk statement, not a quote: a number used through an unofficial client may be restricted by WhatsApp. Use a number you can lose.
- **Third-party skills are untrusted code.** OpenClaw's skills page says to treat third-party skills as untrusted code and read them before enabling (https://docs.openclaw.ai/tools/skills, accessed 2026-10-11). Install none to use this setup.
- **Gateway exposure.** OpenClaw's security page says a regular host install binds the gateway to loopback and that container images default to an exposed bind, to be paired with authentication; it adds that most chat channels answer unknown direct-message senders with a pairing code (https://docs.openclaw.ai/gateway/security, accessed 2026-10-11). Its exposure runbook recommends keeping the gateway loopback-only and sets token authentication in its minimum safe baseline (https://docs.openclaw.ai/gateway/security/exposure-runbook, accessed 2026-10-11). The pages read do not state the authentication default; check it with the gateway's own security audit and do not expose the gateway before you have.
- **Notices and cost.** The MCP mode sends nothing on its own and runs no background loop; a message reaches the person only as the reply to something they sent. Any periodic check is a model turn of the gateway, not of this runtime: OpenClaw's heartbeat runs periodic agent turns, 30 minutes by default; the page says applying a provider's defaults bumps it to 1h when the resolved auth mode is OAuth/token, but only while `heartbeat.every` is unset. Shorter intervals burn more tokens (https://docs.openclaw.ai/gateway/heartbeat, accessed 2026-10-11).

## What the openhora messaging bridge does differently

The messaging bridge (`runtime/messaging.py`) is a separate way to reach a project from a chat app and does not use this path. It puts no model between the channel and the operations: a message becomes an operation by code, a plan is approved with its hash, and notices are sent by code, not by a model's turn. It also has a channel policy whose default is closed: reading, talking and answering only, while approving plans, releasing and the rest are turned on in the project's configuration. It is a separate package that had not merged when this file was written, so it is not linked here; read [contracts/runtime.md](../../contracts/runtime.md) for the runtime's rules once it has. Prefer it when the text must not pass a gateway's model; use the MCP mode only when you already run an OpenClaw gateway and accept the risks above.
