# Running unattended

What makes the task runtime supportable for weeks on a machine nobody sits at: a secret store that says when it is locked, a way to keep secrets with no desktop session, a password manager as a fourth place for secrets, remote access that does not open the machine to a network, retention of what a run leaves on disk, the removal of orphan containers, one writer at a time for a synced sources folder, and a doctor that checks the machine. It crosses the layers of the platform map and belongs to none alone: the secret resolver is a provider (`providers/secrets/resolver.py`), the upkeep is the runtime's (`runtime/upkeep.py`, `runtime/orphans.py`, `runtime/lease.py`, `runtime/secret_state.py`) and the doctor is a script (`scripts/doctor.py`, `scripts/doctor_ops.py`). The package is P-OPS of the delegation plan (findings I3, I4 and I6).

## Purpose

A routine that fires at night must fail in a way the person can see and fix, and must not fill the disk or depend on a desktop session. Four things went wrong silently before this package: a locked keychain read as "the key is not stored"; a headless server had nowhere to keep a secret; run folders, old source versions and half-removed containers accumulated for ever; and a sources folder in a synced drive could be written from two machines. Each now has a rule in code, a message that says what it is, and a check in the doctor.

## Remote access: an SSH tunnel, never `--lan`

The local service listens on `127.0.0.1` and serves the page with a bearer token (`<data_dir>/service.token`, mode 0600). To use the page from another machine, forward the port over SSH and open it on the machine you sit at:

```sh
ssh -N -L 8765:127.0.0.1:8765 deploy@runtime-host.example      # on your laptop; leave it running
ssh deploy@runtime-host.example cat /srv/openhora/data/service.token   # the token, pasted once per browser session
# then open http://127.0.0.1:8765 on the laptop
```

Use the same port number at both ends: the service accepts a request only when its `Host` header is `127.0.0.1:<its port>` or `localhost:<its port>`, so a tunnel that maps the port to another number on the laptop is answered 403. The traffic between the two machines is then SSH's, and the service never listens on a network address. `--lan` serves the same page on the local network over plain HTTP with the token in clear: it is a risk the person accepts for a phone on the same home network, and it is never the way across networks, through a router's port forward or onto a public address. No other way to reach the page is built.

## The secret store: locked is not missing

The resolver looks for a secret in four places, in this order: the environment, the credentials directory, the OS secret store (service `openhora`), and, only for a name the person mapped in `password-manager.json`, the password manager ("Use with 1Password" below). The order is fixed and the person cannot change it. A store that raises instead of answering (a locked keychain or collection, or no backend on a machine with no desktop session) used to read as "not found". It is now told apart (`resolver.resolve_state`):

| State | Meaning | What the person sees |
|---|---|---|
| `found` | a value, from one of the four places | where it was found (for the manager, `password manager (1password)`), never the value or the reference |
| `missing` | nothing holds it; for a mapped name, the manager says the item or field does not exist | "set it: ..." with the command; for the manager, "check the reference of NAME in the mapping file" |
| `locked` | the store raised (locked, or no backend), or the password manager is locked, not signed in, its prompt dismissed or timed out, or its tool is not installed or answered something unrecognised (never read as missing) | "the secret store is locked or unavailable: unlock it", or the manager's own sentence ("the password manager (1Password) is locked or not signed in: ..."; the store's comes first when both fail), in the held reason of a task, in what gets past it, in the connections read, in the three messengers' errors, in `--check` (exit 4), in `--list` and in the doctor |
| `unsafe` | the credentials directory or its file is a link, too large, owned by neither this user nor root, writable by others, or (when this user owns it) readable by others; or the password-manager mapping file is refused for the same reasons of owner and mode, or because it is not JSON, has a key or backend the resolver does not know, holds a reference that fails the syntax check, or maps the manager's own token (then the manager is not called) | "the credentials directory is unsafe" or "the password-manager mapping ... ", the reason and the fix (`chmod`, or what to correct), wherever "missing" would have been said |

`resolve` and `resolve_detail` still return `None` for the last three, so a caller that reads only `None` is unchanged; the messages are the ones that ask for the state. The sentence a message adds comes from the backend that failed (`LOCKED_SENTENCE` for the OS store, the manager's own sentence for the manager, the reason for an unsafe mapping), kept by the resolver (`store_locked_note()`); `runtime/secret_state.py` is the runtime's use of it, and it probes and blames the manager only when the secrets that cannot be read could be held by it (a name in the mapping, or a mapping that is refused) (a probe of the store with a name nothing stores, then, when a mapping file exists, `op whoami` for the manager, each kept for 30 seconds so a page that asks every few seconds does not make a locked keychain or app prompt every time; a value is never cached, in the resolver or here). A message never carries the backend's own text.

### The credentials directory: the one supported headless backend

For a machine with no desktop session the supported backend is a **credentials directory**: one file per secret, named exactly like the secret (`VCS_GITHUB_TOKEN`), holding its value. It is looked for in `OPENHORA_CREDENTIALS_DIR`, then in `CREDENTIALS_DIRECTORY` (the folder a systemd unit gets for `LoadCredential=` and `LoadCredentialEncrypted=`, and what a container's mounted secrets look like), then in `~/.config/openhora/credentials` when it exists. It is read and never written. A link is refused, a file is at most 64 KiB, and the folder and each file must be owned by this user or by root and not writable by group or others. **One this user owns must also be unreadable by anyone else (folder 0700, file 0600 or 0400). One root owns may be readable by others (0755 and 0444):** that is how an administrator or an orchestrator provisions it (systemd credentials, Docker secrets, a Kubernetes secret volume), the read-only mount is theirs, and who else may read it is their decision and not a leak this user made. The value is what the environment variable would hold: for a token, the bare token.

A directory that is refused does not hide behind "missing". The lookup says `unsafe` with the reason and the `chmod` that fixes it; the same sentence is what the held reason of a task, what gets past it, the connections read, the three messengers' errors, `--check` (exit 4), `--list` and the doctor print. Note that a refused directory is refused for every secret at once: until it is fixed, no secret is read from it, and the OS store is not asked for a name the directory would have answered.

```sh
install -d -m 700 ~/.config/openhora/credentials
umask 077 && cat > ~/.config/openhora/credentials/VCS_GITHUB_TOKEN     # type the value, end with Ctrl-D; never on a command line
python3 providers/secrets/resolver.py --check VCS_GITHUB_TOKEN          # found (credentials directory), no value printed
```

With systemd, the unit names the file and the service reads it from `$CREDENTIALS_DIRECTORY`, so the secret exists as a file only in a private memory-backed folder of the service while it runs; `LoadCredentialEncrypted=` keeps it encrypted at rest with the host's key (read the version of systemd the host runs for the user manager's support). The scheduler providers write the unit, and a person adds the `LoadCredential=` lines to it; the runtime does not write a secret.

Why this one (decision recorded in `docs/decisions.md`, 2026-10-15): it adds no dependency, no daemon and no password to type at 3 a.m.; it is the convention systemd, containers and orchestrators already share, so the file can come from any of them; the resolver already treats a value from the environment the same way, so no provider changed; and it is honest about what it protects: a file readable only by its owner is the level of `~/.aws/credentials`, `~/.netrc` or a deploy key, and encryption at rest with a key on the same disk would add the look of protection and not the thing. The alternatives and why they were not chosen: `keyrings.alt`'s file backends (the encrypted one asks for a password the first time, which a headless start cannot give, and the plain one is this directory with a worse format); `pass` (needs a GPG key with no passphrase to be unattended, which is this directory with extra moving parts); a desktop keyring daemon under a virtual session (works until the session or the daemon dies, and then a locked store is back).

### Use with 1Password

The password manager is a **fourth place**, after the three above, for a company or a person who keeps secrets in 1Password. It never replaces the order (the environment first lets CI and a cloud session override), it is asked only for a name the person wrote in a mapping file, and it holds no value in the workbench: the mapping holds references. The package is S16; the decision is recorded in `docs/decisions.md`, 2026-10-15; the limit is L39 (a password manager's tool is never called inside a run container).

1. **Install the vendor's command-line tool** (`op`, version 2) from the vendor's site and check that `op --version` answers. The resolver finds it on the `PATH` it was started with.
2. **Sign in, once, as the person.** On a laptop, turn on the integration with the desktop app in the app's settings (Developer: "Integrate with 1Password CLI"); the app then asks for the unlock when a call arrives. On a headless company machine, create a **service account** in the 1Password admin with read access to only the vaults the mapping will name, and put its token in the credentials directory under the name `OP_SERVICE_ACCOUNT_TOKEN` (`umask 077 && cat > ~/.config/openhora/credentials/OP_SERVICE_ACCOUNT_TOKEN`, typed or piped, never on a command line). The token is found in the environment, the credentials directory or the OS secret store (store username `password-manager-1password`), never through the manager, and it cannot be mapped. Nothing in the workbench runs `op signin` or `op account add`, unlocks the app or touches the terminal.
3. **Write the mapping file**, outside any repository: `$XDG_CONFIG_HOME/openhora/password-manager.json`, else `~/.config/openhora/password-manager.json`, then `chmod 600` it:

```json
{
  "backend": "1password",
  "account": "example-team.1password.example",
  "timeout_seconds": 15,
  "references": {
    "VCS_GITHUB_TOKEN": "op://Example Vault/github-read/credential",
    "NOTION_TOKEN": "op://Example Vault/notion-board/section one/credential"
  }
}
```

   `backend` and `references` are required; `account` (the sign-in address, passed as `--account`) and `timeout_seconds` (1 to 60, default 15) are optional; any other key is refused. A reference is `op://<vault>/<item>[/<section>]/<field>`, each part made of letters, digits, spaces, hyphens, underscores and periods (a name with other characters is written as its ID); a query (`?attribute=otp`), a variable or anything before `op://` is refused. Only a name written here is ever asked of the manager; without the file nothing changes.
4. **Check it**, without printing a value: `python3 providers/secrets/resolver.py --check VCS_GITHUB_TOKEN` (exit 0 found, 3 missing, 4 locked or unsafe), `python3 providers/secrets/resolver.py --list`, and `python3 scripts/doctor.py --unattended --project <dir>`, whose `password_manager` row is `na` without a mapping, `ok` when `op whoami` answers, and `warn` with the fix when the manager is locked, the tool is not installed or the file is refused.

A token that is only exported (`OP_SERVICE_ACCOUNT_TOKEN` in the shell) never reaches a provider the runtime starts, because a provider's environment is a fixed minimum that strips `OP_*`; for a provider, put the token in the credentials directory or the OS secret store. Inside a run container the manager is never used, and says so.

What each state looks like: `found` says `password manager (1password)` and never the reference; `missing` (the tool says the item or field does not exist) says "check the reference of NAME in the mapping file"; `locked` is a manager that is locked, not signed in, whose prompt was dismissed or timed out, or whose tool is not installed or answered something unrecognised: "the password manager (1Password) is locked or not signed in: unlock the app, or on a headless machine provide OP_SERVICE_ACCOUNT_TOKEN in the credentials directory", in the same places the store's sentence is told (held reasons, the connections read, the three messengers' errors, `--check`, `--list`, the doctor), and never as "missing"; `unsafe` is the mapping file (a link, not this user's, readable by others, too large, not JSON, an unknown key or backend, a reference that fails the check, the token mapped), with the reason and the fix, and the tool is not called. A name found earlier that is also in the mapping is marked "mapped in the password manager, not asked: found earlier" in `--list` and the doctor, with no call: a stale entry in the OS secret store would shadow the manager, and this line shows it.

How a call is made: `op read <reference>` (and `--account <a>` when set), as a list of arguments with no shell, stdin on `/dev/null`, a deadline, and an environment of only `PATH`, `HOME`, `USER`, `LANG`, `TMPDIR`, `XDG_CONFIG_HOME` and `XDG_RUNTIME_DIR` when set, plus `OP_SERVICE_ACCOUNT_TOKEN` when the resolver found it. What the tool prints on its error output is read for fixed markers and dropped: it is never shown, logged or put in an exception. Output over 64 KiB is refused. In `report` (`--list`, the doctor), once the manager has failed it is not asked again for the other mapped names, because each ask may prompt.

### OAuth consent: on a machine with a browser

`providers/mailbox/auth.py --provider gmail` and `providers/publisher/auth.py --provider linkedin` start a listener on the loopback address, open the consent page in a browser and receive the code there, so they run on **a machine with a browser**, never on the headless server. The record they write goes to **that machine's OS secret store** (service `openhora`, store usernames `mailbox-gmail` and `publisher-linkedin`; a JSON object with the token and its dates), not to the server. To use the authorization on the server, put the bare token in the credentials directory, without ever showing it: on the machine that has the record, pipe it into the file on the server under a restrictive umask (the record is a JSON object; `refresh_token` is the field):

```sh
( umask 077; uv run --with keyring==25.7.0 keyring get openhora mailbox-gmail \
    | python3 -c 'import json,sys; sys.stdout.write(json.load(sys.stdin)["refresh_token"])' \
    | ssh deploy@runtime-host.example 'umask 077; cat > ~/.config/openhora/credentials/GMAIL_REFRESH_TOKEN' )
```

For LinkedIn the file is `LINKEDIN_ACCESS_TOKEN` (field `access_token`), with the expiry in the environment variable `LINKEDIN_TOKEN_EXPIRES_AT`, as the provider reads it from the environment. The client id and secret of the app go the same way as files.

**Google Drive as a source** (`GDRIVE_SOURCES_TOKEN`) is the exception: its consent is `uv run providers/documents/gdrive_auth.py authorize`, on a machine with a browser, and the secret is **one JSON record** (refresh token, the Desktop app client, the Picker's API key, the project number, the scope and the date), not a bare token. The environment variable holds the same JSON text, and so does the file of the credentials directory: copy the whole record, not a field of it. A bare token in the file makes the provider say the authorization is unreadable.

```sh
( umask 077; uv run --with keyring==25.7.0 keyring get openhora gdrive-sources \
    | ssh deploy@runtime-host.example 'umask 077; cat > ~/.config/openhora/credentials/GDRIVE_SOURCES_TOKEN' )
```

The consent page of the Picker (`gdrive_auth.py pick`) also needs a browser; the files it picks are then read by the server with the record alone. A refresh token of a Google project in "Testing" expires after seven days (the provider's `auth.py` cites the source): a server that runs for weeks needs the project published, or a weekly consent. The runtime never runs the consent itself.

**OneDrive as a source** (`ONEDRIVE_SOURCES_TOKEN`) is the same kind of record (JSON: refresh token, client id, tenant, scope, account kind, date; no client secret exists), made by `uv run providers/documents/onedrive_auth.py authorize` on a machine with a browser, and copied whole to the credentials directory the same way. Microsoft replaces the refresh token on every use and the old one lives out its 90 days. A record in the OS secret store is rewritten with the new token after each refresh (`onedrive.py`); a record in the environment or in the credentials directory is never rewritten, so it ages **90 days from the consent**, used or not: a server that runs for months needs `authorize` run again, and the file copied again, before then (`onedrive.py --check` prints `rotation`, which says whether a new token was stored).

**Google Calendar as a source** (`GOOGLE_CALENDAR_TOKEN`) is the same shape: its consent is `uv run <workbench>/providers/calendar/google_auth.py authorize`, on a machine with a browser, and the secret is **one JSON record** (refresh token, the Desktop app client, the two scopes, the account and the date) under the store username `calendar-google`. It is a record of its own, not the Gmail one: copy the whole record, not a field of it.

```sh
( umask 077; uv run --with keyring==25.7.0 keyring get openhora calendar-google \
    | ssh deploy@runtime-host.example 'umask 077; cat > ~/.config/openhora/credentials/GOOGLE_CALENDAR_TOKEN' )
```

The same seven-day expiry of a project left in "Testing" applies; `google_auth.py check` says whether a record is found without calling Google, and `google_auth.py forget` removes the local record (it does not tell Google: the app's access is also removed in the Google Account).

**Outlook mail and calendar as sources** (`OUTLOOK_MAIL_TOKEN`, `OUTLOOK_CALENDAR_TOKEN`) are two more records of the same kind (JSON: refresh token, client id, tenant, scope, date; no client secret), each made by its own `uv run <workbench>/providers/mailbox/outlook_auth.py authorize` and `uv run <workbench>/providers/calendar/outlook_auth.py authorize`, with the client id of its own Microsoft app registration (one registration per purpose: Microsoft binds a refresh token to a user and a client, not to a resource), and each copied whole to the credentials directory the same way. The rotation is the OneDrive one, from the shared code (`providers/_msgraph.py`): a record in the OS secret store is rewritten after a refresh only if it still holds the token the provider used; a record in the environment or the credentials directory ages **90 days from the consent**, used or not, so a server that runs for months needs `authorize` run again, and the file copied again, before then (`outlook.py --check` prints `rotation`). The runtime side (mail and calendar as source types, with a freshness bound) is a later package (RT-1) and is not built here.

## Retention (I6)

Two keys of `runtime.json`, both optional, accepted in the terminal like every key of the file:

| Key | Default | Range | What it does |
|---|---|---|---|
| `run_retention_days` | 30 | 1 to 3650 | the folder of a run under `<data_dir>/task-runs/<run id>/`, and a folder of `<data_dir>/contained-runs/<n>/`, older than this is removed, unless the run is still needed (below) |
| `source_versions_kept` | 5 | 2 to 1000 | each source keeps its newest versions in the sources folder; the older version folders are removed |

What is never removed (limit L29): the folder of a run whose row is `running` or whose task lock a live process holds; **the folder of any run whose task is not finished (not `done` or `cancelled`: a task that ended at a confirmation gate is `waiting`, and its effect document and its change set live in the run's folder, which approving needs), whose request is not finished (the next code task of a request builds on the change sets of the earlier runs), or that an open pending decision references**; a folder younger than the age (its age is the newest modification time of the folder and of its entries); the dispatcher's `children` folder (it has its own 14 days); the highest numbered `contained-runs` folder; a symbolic link (not followed, not removed); and, for the source versions, **a version a task that is not finished received** (the rows `task_sources` record the id, version and sha256 of what each run received, decision D29; a failed task, which can be retried, is not finished and keeps its version). So a request left open for ever keeps its folders for ever: cancel or finish it to let them go. The minimum of 2 versions is there because a task copies the newest version when it starts: with one kept, a second import during the copy could take it away.

If a run folder of an open request is gone anyway (removed by hand), the next code task of that request is refused with the reason ("the run folder ... is gone, and the change set it held with it: cancel the request if it is still open, and start a new request for the work"), never started without the earlier work (`changeset.current`).

The rows of the store stay, as limit L13 says (a source version's row is never deleted): a pruned version has a row and no folder. Nothing reads an old version (a task receives the newest), the next import is numbered after the highest recorded version, and the catalog still shows the count of versions. The cost and tokens of an old run are columns of its row; only what the run left on disk goes, so the usage that costs recompute from a run's own files is unknown for a run older than the retention.

Where it runs: the dispatcher's round calls `upkeep.run_quietly` as its first step (`runtime/ops_runs.py`), once an hour at most (`<data_dir>/upkeep.json` holds the time of the last pass, and the lock `upkeep.lock` keeps two processes from running it together). A part that fails is reported and tried again at the next hour; the round never fails for it. Every removal goes through the open descriptor of its folder with `O_NOFOLLOW` and a device and inode check (`os.path.samestat`) before it touches anything inside; it deletes nothing outside `data_dir` and the sources folder.

## Orphan containers (I6)

A run starts a container (`wb-eval-run-<run id>`), a key proxy (`wb-eval-keys-<run id>`) and an internal network (`wb-eval-held-<run id>`). When the process that started them dies, the proxy and the network can stay. The harness labels everything it makes `wb.eval=1` and, for a run's own three, `wb.eval.run=<run id>` (`evals/executor.py`; this package does not change that file). The sweep (`runtime/orphans.py`) selects by **name**: `wb-eval-run-<16 hex>`, `wb-eval-keys-<16 hex>` and `wb-eval-held-<16 hex>`; the label says how the name was found (a run started before the label existed has only the name) and selects nothing by itself, so a container that carries the label but another name is never touched.

It never selects the harness's long-lived objects: its egress proxy (`wb-eval-proxy-<tag>`), its networks (`wb-eval-net-<tag>`, `wb-eval-route-<name>-<tag>`, `wb-eval-open-...`) and its shared key holders (`wb-eval-keys-<12 hex tag>`, `wb-eval-keys-strong-...`, `wb-eval-keys-net-...`, `wb-eval-strong-held-...`): none has 16 hexadecimal characters after a run prefix, and `is_shared` refuses them again just before any removal, whatever their labels.

**The pass the dispatcher's round makes by itself is conservative and reads no lock.** (No lock says whether a run is live: the lab's lock folder follows the environment's temporary folder, so a scheduler's job and a terminal can look at different ones.) It removes only what cannot belong to a run in progress:

- a run container that has **ended** (`exited` or `dead`);
- a key proxy whose run container **no longer exists** in any state, once it is older than 30 minutes (the executor starts the proxy a moment before the container it serves, and a run's setup commands can take 15 minutes);
- a network no container of its run is on any more, past the same 30 minutes.

**A running run container is never removed by a pass, whatever its age.** The one way is a command a person types: `python3 runtime/upkeep.py containers --include-running` (add `--dry-run` to see first), which removes a running run container only when it is older than 6 hours (a stuck one); a battery started with a longer timeout is the person's to judge. An object whose age or state cannot be read is kept.

The automatic pass is a setting of the project: `sweep_orphan_containers` in `runtime.json` (default true; false turns it off), accepted in the terminal like every key, so that it reaches a scheduler's job (an environment variable would not). `OPENHORA_UPKEEP_CONTAINERS=off` also skips it (the tests' switch). Without a docker client it is skipped. The sweep goes through the lab facade (`lab.container_tool`), and every test of it uses a fake container tool.

## Images of earlier definitions (T38)

The providers that build an image (the converter, the exporter and the script runner; a provider that builds an image adds itself to `IMAGE_FAMILIES` of `scripts/doctor.py`, with its own test) tag it with the hash of its definition, so each change of a definition leaves the earlier image on disk, hundreds of megabytes each. Nothing removes them by itself: **no run, no upkeep pass and no other doctor mode ever sends an image command**. The doctor lists them and removes them on the person's word:

- the `images` row of `python3 scripts/doctor.py --unattended`: the count and total size of the images of earlier definitions and the command below. It is never a `warn`, so it never changes the exit code (also under `--strict`); without docker it is `unverified`;
- `python3 scripts/doctor.py --remove-old-images (--dry-run | --confirmed)` prints one JSON object (`removed`, `would_remove`, `kept` with the reason of each, `freed_bytes`). `--dry-run` sends no removal. One of the two is required.

**What is selected, and only this** (`providers/_container.py`): an image is a candidate when **all three** hold: it carries the label `org.openhora.definition`, its repository equals that provider's `IMAGE_REPOSITORY` exactly, and its label value (and its tag) differ from the provider's current `definition_hash()`. Never selected: an image without the label, an untagged image, any reference that starts with `wb-eval`, the current definition's image, and an image of another repository (the exporter's, when the converter's are asked for). Each candidate is inspected again right before its removal and removed by tag (`docker image rm <repository:tag>`), never with `--force` and never with `prune`; an image that is in use or that docker refuses is kept and reported with the reason.

**Why it is never automatic.** Unlike a dead run's container, an old image can still be wanted: a person who goes back to an earlier definition rebuilds it (the network, minutes), and an image a stopped container uses is refused anyway. The decision to spend that is the person's, and the removal is the one write in this area that cannot be undone by waiting (principle 5: a decision that is the user's is asked). The tests use a fake container tool only (`scripts/tests/test_container_images.py`; `runtime/tests/test_upkeep.py` proves the hourly pass sends no image command).

## A synced sources folder: the lease (I4)

The sources folder is the one place a person may keep in a synced drive, so that two machines see it. Two things keep two runtimes from corrupting it (limit L28):

- **The lease.** A host that is about to write the folder (an import, the removal of old versions) takes its lease first, right before the write: `.openhora-lease` in the folder holds the host id, the host name, the pid, when it was taken and when it ends (5 minutes after the last write). A second host that finds a live lease of another host refuses to write and names that host and the time its lease ends. An expired lease of another host is taken over, and **the takeover is told**: the answer of the operation carries `lease_took_over`, the upkeep pass reports it, and the runtime records it in `<data_dir>/lease-takeover.json`, which the doctor's `lease` check shows as a warning until a person acknowledges it with `python3 scripts/doctor.py --unattended --project <dir> --ack-lease` (that removes only that record). This host's own lease is renewed, a damaged one is taken as expired. A read, an import that finds the bytes already held and an upkeep pass with nothing to remove write nothing and take no lease. It is taken **always**, not only when the folder is known to be synced, because a synced folder cannot be recognised in general (a mounted share, a repository pulled by hand, a sync client the code has never heard of) and the cost is one small file per write. The host id is made once, atomically (two processes starting together end with the same id), and kept in `<data_dir>/host-id`, never in the synced folder. **What it covers: concurrent writes within the lease window.** A host that writes while another host's last write is less than five minutes old is refused. It does not tell that a second runtime is merely running (an idle runtime holds no lease), and it is not a lock: a sync that takes longer than five minutes to bring the lease over, and two hosts that start in the same instant, before either file reaches the other, are not covered.
- **Nothing else in a synced folder.** `data_dir` (run folders, locks) and the store's database are refused in one at load: SQLite and a lock file do not survive a sync client. A folder is taken as synced when a component of its real path is, **as a whole name**, the folder of a sync client (`iCloud Drive`, `Dropbox`, `Dropbox (Personal)`, `OneDrive - Company`, `Google Drive`, `Nextcloud`, `pCloud Drive`, `Box Sync`, `MEGAsync`, `Mobile Documents`, `CloudStorage`) or a parent holds a marker a client leaves (`.dropbox`, `.stfolder`...). A folder that only starts like one (`dropbox-backup-tool`, `icloud-notes`) is somebody's project and is not refused. The list is closed: a client it does not know is not detected, and the refusal names what it saw. **What it cannot see:** on macOS, iCloud's "Desktop & Documents" keeps `~/Desktop` and `~/Documents` in iCloud while their paths stay ordinary and no marker tells so, so a `data_dir` or a database there is not refused; keep them elsewhere (the home folder's `Library/Application Support`, or `/var/lib`).

## The doctor's checks

`python3 scripts/doctor.py --unattended --project <dir>` runs these checks on top of the usual report (`--json` has them under `unattended`; `--strict` exits 1 when one warns). It is the one mode of the doctor that asks docker to list and inspect the harness's containers.

| Check | Can verify | Cannot verify |
|---|---|---|
| `linger` (Linux) | `loginctl show-user <user> --property=Linger --value`: whether the user's services survive the last logout and start after a reboot | whether the scheduler's timers are enabled (the scheduler provider's check) |
| `sources_access` (macOS) | whether the folder lies in a place macOS protects (Desktop, Documents, Downloads, iCloud Drive, a cloud provider's folder, a volume) and whether this process can list it | whether the interpreter a launchd job runs has been allowed: no query tells, so for a protected place the status is `unverified` and the detail names the requirement (System Settings > Privacy & Security > Full Disk Access) and how to test it (run the job once and read its log) |
| `disk` | free space on the filesystem of `data_dir` and of `sources_dir` against a threshold (5 GiB; `--min-free-gib`) | a quota, or a full cloud drive behind a sync client |
| `proxy_logs` | `docker inspect` of the containers labelled `wb.eval` whose names are a proxy's or a key holder's: whether a log size limit is set | a container not running here; it reads and never changes |
| `lease` | whether this host took over the expired lease of another host's write of the sources folder (the record `<data_dir>/lease-takeover.json`; `--ack-lease` clears it) | whether another machine is running now (an idle runtime holds no lease) |
| `secret_store` | whether the credentials directory is safe to read (an unsafe one is a warning, not a missing secret) and whether the OS secret store answers, is locked or has no backend | that a given secret is in either (`--list` says that) |
| `password_manager` | `na` without a mapping file; otherwise `op whoami` (no secret read): ok when it answers, a warning with the fix when the manager is locked or not signed in, the tool is not installed, or the mapping file is refused | that a given reference points at an item, or that a service account's hourly limit is not spent; it may make a locked desktop app ask the person to unlock it |
| `image` | the eval image in its four states, and the command that sets it up when it is not present: `python3 scripts/image_lock.py pull` (a published image, by digest, with the provenance check) or `python3 evals/executor.py ensure` (a local build). The first pull is an explicit step (decision D39), never automatic and never in the middle of a dispatch | whether the image runs: it is not started |
| `images` | the images of earlier definitions of the providers that build one: their count and total size, and the command that removes them on the person's word (`python3 scripts/doctor.py --remove-old-images --dry-run`, then `--confirmed`) | whether an image is wanted again; it removes nothing and is never a `warn` |

A status is `ok`, `warn` (with the command that fixes it), `unverified` (the doctor cannot tell from here, and says what to check by hand) or `na` (the check does not apply on this machine).

## Known limits

| Limit | Where |
|---|---|
| The lease covers concurrent writes within its five minutes, not a sync slower than that or two hosts starting together; an idle second runtime is not seen | above |
| iCloud's "Desktop & Documents" cannot be detected, so a database or `data_dir` there is not refused | above |
| A request left open keeps its run folders and the versions its tasks received for ever | above |
| The macOS permission of a scheduled job on a protected folder cannot be queried; the doctor states the requirement and stays `unverified` | above |
| A token that is a JSON record in the secret store is the bare token in the credentials directory; the expiry of a LinkedIn token is read from the environment only | above |
| The automatic sweep never removes a running run container, so a stuck one stays until a person runs `python3 runtime/upkeep.py containers --include-running` | above |
| A pruned source version leaves a row and no folder | above |
| The images of earlier definitions stay until a person runs `python3 scripts/doctor.py --remove-old-images --confirmed` | above |
| The password manager keeps no cache: each lookup starts one process of the vendor's tool (to verify: roughly a second, and a service account's hourly and daily request limits count each one). A cache, if ever needed, is in process memory, at most 60 seconds, never on disk, and a later decision | Use with 1Password |
| `op signin` sessions (`OP_SESSION_*`, stripped from a provider's environment, and they expire in minutes) and a 1Password Connect server are not supported | Use with 1Password |
| The order is fixed, so a stale OS secret store entry shadows the manager; `--list` and the doctor mark it, with no call | Use with 1Password |
| The marker texts the tool prints are read from the vendor's documentation and public reports where they exist; the rest are to verify on a real machine, and an unrecognised error is read as `locked`, never `missing` | Use with 1Password |

## Changes

- 2026-10-16: the images of earlier definitions of the converter and the exporter are listed in the doctor's `images` row and removed on the person's word with `python3 scripts/doctor.py --remove-old-images (--dry-run | --confirmed)`, never automatically (T38).
- 2026-10-15: S16: the password manager (1Password first) as the fourth place a secret is looked up, with a mapping file of references, one call of the vendor's tool per lookup and no cache, its states told apart from a missing secret, the doctor's `password_manager` check and limit L39. `provider_environment` keeps `OPENHORA_CREDENTIALS_DIR` and `CREDENTIALS_DIRECTORY`, so a provider's process finds a credentials directory that only those variables name.
- 2026-10-15: after review: a run folder is kept while its task, its request or a pending decision is open; the container sweep never removes a running container and can be turned off in `runtime.json`; the lease is taken only before a write and a takeover is told; an unsafe credentials directory is told, and root-provisioned read-only secrets are accepted; whole-name detection of synced folders.
- 2026-10-15: first version, with package P-OPS (a locked secret store told apart from a missing one, the credentials directory, retention of run folders and source versions, the orphan sweep, the lease of the sources folder with limits L28 and L29, the doctor's unattended checks).
