# Secrets contract

The workbench is automation that runs anywhere: a laptop, a cloud session, CI and the agent runtime. Every script and provider asks for a secret by name through one resolver, `providers/secrets/resolver.py`, and never knows where the value lives. Only where the value is stored changes between environments; the code path is the same.

## Rules

- A secret is read only through the resolver. A provider, script or eval never reads a credential from its own environment variable or the OS secret store directly. The one direct use of the store is a write: an `auth.py` stores the record of an authorization it has just run; its `--check` reads that record back through the resolver, like the provider does.
- Lookup order, the same everywhere: the environment variable named like the secret, then its aliases, then the OS secret store (keyring, service `openhora`, the username in the registry). The first non-empty value wins.
- Compatibility stage: a name not found under the service `openhora` is looked up under the service the workbench used before it was renamed, `ai-workbench` (`LEGACY_SERVICE` in the resolver), so a credential stored earlier keeps working. The resolver's `--check` and `--list` say which service answered (`service: "ai-workbench (legacy)"`), so the person knows what to store again; every write (the command the runtime shows, the records an `auth.py` stores) names `openhora` only. The fallback is removed with the next change of reference model (backlog T23). A job scheduled before the rename runs a snapshot of the provider with the resolver of that day, which reads `ai-workbench` only, so the old entries are kept until those jobs have run or are scheduled again; delete them only then.
- Never in the repository, a project file, a flag, a prompt or the conversation. The resolver, `scripts/doctor.py` and every provider print where a secret was found (`environment (NAME)` or `secret store`), never its value, not even partially.
- One secret per purpose, with the minimum permission listed below. A permission that writes (dismissing alerts, publishing) lives in a separate secret from the one that reads, when the service allows it.
- A secret a provider reads is added to `REGISTRY` in the resolver and to the table below in the same change; the resolver's tests compare the two cell by cell and fail when they disagree.
- A secret only an adapter's runs need (a model provider's key, a login token of the tool the adapter drives) is registered by that adapter, in the `secrets` list of `adapters/<harness>/adapter.json`, with the same fields as a registry entry (`name`, `purpose`, `permission`, `readers`, and optionally `store_username`, `aliases`, `note`, `set_local`) and one more, required in a manifest: `billing`, how the credential is billed ("How a credential is billed" below). The core lists none of them and the resolver never opens an adapter by itself: a caller outside the core hands it the file (`--registry <file>` on the command line, `register_file(path)` in code) and the list is merged for that call. A name two adapters register must agree on its store username and aliases.
- A new place to keep secrets (a password manager) is a new lookup function in the resolver, after the OS secret store; callers do not change.

## Where to put a secret, per environment

| Environment | Where | How |
|-------------|-------|-----|
| Cloud session | the environment's settings, as an environment variable | name it exactly like the secret (`VCS_GITHUB_TOKEN`) |
| CI | a repository secret, mapped to an environment variable of the same name in the workflow | `env: VCS_GITHUB_TOKEN: ${{ secrets.VCS_GITHUB_TOKEN }}` |
| Local machine | the OS secret store (preferred), or an export in the shell | `uv run --with keyring==25.7.0 keyring set openhora <username>`: the value is typed at a hidden prompt, never on the command line |
| Agent runtime | wherever the machine it runs on keeps secrets (one of the rows above), through the same resolver | the runtime's configuration holds paths and limits only (`contracts/runtime.md`) |

Check what is set, without printing any value: `python3 providers/secrets/resolver.py --list` for the table below, or `python3 scripts/doctor.py`, which adds the secrets every adapter registers and names the requirement classes that read each one.

**Variables passed into an eval run.** The names have one home: `floor_pass_env` and `strong_pass_env` of `evals/eval-gate.json` (and the runner's `--pass-env` and `--floor-pass-env` flags for a run by hand). The eval runner checks each of those names against the secrets the adapters register and takes no name from that registry: a name that is registered for eval runs and missing from the environment is filled from the OS secret store, so a key kept there reaches the runs without an export; any other name is passed as it is. A variable named for one model's runs never reaches the other model's runs.

**Where the eval models' credentials live during an eval run.** Not in the run. Since 2026-10-03 the floor model's provider key is held by the key proxy of the eval network (`evals/container/keyproxy/`, whose `keyproxy.json` names the variable): a container of its own, beside the egress proxy, that the eval executor starts with the key in its environment. The run container gets a placeholder in the key's variable and the proxy's base URL; the proxy forwards the provider's API path only, to the provider's one host, over HTTPS and through the egress proxy, and adds the key to each call. It also pins the floor model's provider: on every POST to a path ending in `/chat/completions` it sets `"provider": {"only": [<the route's provider_only>], "allow_fallbacks": false}` in the body, whatever the run asked for, and it refuses a body that is not a JSON object. The strong model's credential, the maintainer's account token, is held the same way by a second key proxy (`keyproxy-strong.json`), on networks of its own: a run gets a placeholder and its own tier's proxy address, can spend its own tier's credential through that proxy and cannot reach the other tier's proxy. A model under test can still spend a credential through its proxy, within that credential's limit, but cannot read it, print it or carry it to another host. The runner still replaces every passed value in what a run leaves, by exact value, before anything is stored or graded.

## How a credential is billed

Every entry of the `secrets` list of an adapter's manifest states `billing`, one of three words, and `scripts/validate.py` fails (an error, not a warning) on an entry without one or with another word. The runtime reads the words, and nothing else about money, from the manifests (`runtime/billing.py`), to decide which daily cap a run counts against (`contracts/runtime.md`, "The daily caps"):

| Word | A run on this credential | Counted against |
|------|--------------------------|-----------------|
| `subscription` | is covered by a fixed fee (an account's login or long-lived token); what a run costs is not billed | `max_runs_per_day` |
| `metered` | is paid by use (an API key of a model provider); the cost of the run is recorded | `max_usd_per_day` |
| `free` | costs nothing and needs no key: a model on the person's own machine | `max_runs_per_day` |

`free` is for a credential-less local model. No adapter has one today, so no entry of this checkout carries it; the word exists so that an adapter for such a model declares itself `free` (through `login_billing` below, there being no variable) without a change to the caps.

A harness that holds the credential itself (the login of its own command-line tool, no variable passed) declares it once in the manifest, outside the `secrets` list, as `"login_billing"`: one of the same three words, read when a run passes no variable. A manifest without it and a run without a variable have no billing the runtime can know, and the dispatcher does not start the run (it never guesses a cap).

`login_billing` is reachable only in a configuration whose tier passes no variable; inside the eval container the CLI's login does not exist, so a runtime run there always passes a variable.

A credential two adapters list has the same word in both (the validator checks it), and a run that passes several variables is billed by the strictest: `metered`, then `subscription`, then `free`. Today the long-lived token of the reference model's harness and that harness's own login are `subscription`, and every model provider's key an adapter registers (the reference model's alternative key, the floor model's provider keys, the key for the open-network eval cases) is `metered`; the manifest of each adapter is the list.

## Registry

The secrets the core reads. Each cell is the text of the same field in `REGISTRY`.

| Secret | Aliases, read after it | Purpose | Minimum permission | Read by | Store username | Stored locally with | Note |
|---|---|---|---|---|---|---|---|
| `VCS_GITHUB_TOKEN` | `GITHUB_TOKEN` | read (and, with a separate token, dismiss) Dependabot alerts; read one file of a repository | fine-grained token, only the repositories concerned: "Dependabot alerts: Read-only" ("Read and write" only in the separate token used to dismiss); "Contents: Read-only" to read a file of a private repository (read-file); commit-files uses no token | `providers/vcs/github.py`, `.github/workflows/dependabot-alerts.yml` | `github` | `keyring set` | GITHUB_TOKEN is read last: a harness or CI may set its own, with other permissions; open-pr reads it only when VCS_GITHUB_PR_TOKEN is found nowhere |
| `VCS_GITHUB_PR_TOKEN` | none | open a pull request (open-pr); nothing else | fine-grained token, only the repositories concerned: "Pull requests: Read and write" only | `providers/vcs/github.py`, `runtime/effects.py` | `github-pr` | `keyring set` | open-pr reads it first and names it (never its value); when it is found nowhere, open-pr falls back to VCS_GITHUB_TOKEN |
| `LINKEDIN_ACCESS_TOKEN` | none | publish posts on LinkedIn | OAuth scopes openid, profile and w_member_social (providers/publisher/auth.py) | `providers/publisher/linkedin.py`, `providers/publisher/auth.py` | `publisher-linkedin` | uv run providers/publisher/auth.py --provider linkedin (writes the record after the browser consent) | the store holds a JSON record written by providers/publisher/auth.py (access_token, expires_at); from the environment, LINKEDIN_TOKEN_EXPIRES_AT may give the expiry |
| `LINKEDIN_CLIENT_ID` | none | the LinkedIn app that authorizes the publisher, once | an app with the "Share on LinkedIn" product | `providers/publisher/auth.py` | `linkedin-client-id` | `keyring set` | none |
| `LINKEDIN_CLIENT_SECRET` | none | the LinkedIn app's secret, used once by the authorization | the app's primary client secret | `providers/publisher/auth.py` | `linkedin-client-secret` | `keyring set` | none |
| `GMAIL_REFRESH_TOKEN` | none | read the user's Gmail (search and read messages, never change them) | OAuth scope https://www.googleapis.com/auth/gmail.readonly only (providers/mailbox/auth.py) | `providers/mailbox/gmail.py`, `providers/mailbox/auth.py` | `mailbox-gmail` | uv run providers/mailbox/auth.py --provider gmail (writes the record after the browser consent) | the store holds a JSON record written by providers/mailbox/auth.py (refresh_token, scope, obtained_at, account); from the environment, the bare refresh token |
| `GMAIL_CLIENT_ID` | none | the Google Cloud OAuth client (Desktop app) that authorizes and refreshes the Gmail access | a Desktop app OAuth client in a project with the Gmail API and only the gmail.readonly scope | `providers/mailbox/auth.py`, `providers/mailbox/gmail.py` | `gmail-client-id` | `keyring set` | none |
| `GMAIL_CLIENT_SECRET` | none | that Google OAuth client's secret, used by the authorization and every token refresh | the Desktop app client's secret | `providers/mailbox/auth.py`, `providers/mailbox/gmail.py` | `gmail-client-secret` | `keyring set` | none |
| `NOTION_TOKEN` | none | read and write the task board and the documents of a project on Notion | an internal integration with read content, update content, insert content and read comments, given only the base and the parent page the project names | `providers/issue-tracker/notion.py`, `providers/documents/notion.py` | `notion` | `keyring set` | none |
| `MESSENGER_TELEGRAM_BOT_TOKEN` | none | receive the person's messages and send the notices of the messaging bridge, as a Telegram bot | a bot created for this person with the platform's bot service, used only by this bridge | `providers/messenger/telegram.py` | `messenger-telegram` | `keyring set` | none |

`keyring set` stands for the command of the "Local machine" row above, with the store username of the row.

## Why

Decided on 2026-09-28 (backlog S13): the first calls to real services showed each provider resolving its credential its own way, a cloud session's own `GITHUB_TOKEN` shadowing the maintainer's token (fixed with `VCS_GITHUB_TOKEN`), and a model provider's key living only in one shell and lost to later sessions. The lookup order (environment, then the OS secret store) is the one the providers already used; a password manager waits for a real case (backlog S16).

Decided on 2026-10-02: the registry named one AI tool's credential variable, its store name and three adapter paths, against the rule that the core names no AI tool and never reads an adapter. Each adapter now registers its own secrets, and the names passed into eval runs stay in the gate file alone.
