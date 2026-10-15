# Running unattended

What makes the task runtime supportable for weeks on a machine nobody sits at: a secret store that says when it is locked, a way to keep secrets with no desktop session, remote access that does not open the machine to a network, retention of what a run leaves on disk, the removal of orphan containers, one writer at a time for a synced sources folder, and a doctor that checks the machine. It crosses the layers of the platform map and belongs to none alone: the secret resolver is a provider (`providers/secrets/resolver.py`), the upkeep is the runtime's (`runtime/upkeep.py`, `runtime/orphans.py`, `runtime/lease.py`, `runtime/secret_state.py`) and the doctor is a script (`scripts/doctor.py`, `scripts/doctor_ops.py`). The package is P-OPS of the delegation plan (findings I3, I4 and I6).

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

The resolver looks for a secret in three places, in this order: the environment, the credentials directory, the OS secret store (service `openhora`). A store that raises instead of answering (a locked keychain or collection, or no backend on a machine with no desktop session) used to read as "not found". It is now told apart (`resolver.resolve_state`):

| State | Meaning | What the person sees |
|---|---|---|
| `found` | a value, from one of the three places | where it was found, never the value |
| `missing` | nothing holds it | "set it: ..." with the command |
| `locked` | the store raised (locked, or no backend) | "the secret store is locked or unavailable: unlock it", in the held reason of a task, in what gets past it, in the connections read, in the three messengers' errors, in `--check` (exit 4), in `--list` and in the doctor |
| `unsafe` | the credentials directory or its file is readable by others, not this user's, a link, or too large | the reason, and the `chmod` that fixes it |

`resolve` and `resolve_detail` still return `None` for the last three, so a caller that reads only `None` is unchanged; the messages are the ones that ask for the state. The sentence a message adds comes from one place (`LOCKED_SENTENCE`); `runtime/secret_state.py` is the runtime's use of it (a probe of the store with a name nothing stores, kept for 30 seconds so a page that asks every few seconds does not make a locked keychain prompt every time). A message never carries the backend's own text.

### The credentials directory: the one supported headless backend

For a machine with no desktop session the supported backend is a **credentials directory**: one file per secret, named exactly like the secret (`VCS_GITHUB_TOKEN`), holding its value, in a folder of mode 0700 that is this user's, each file 0600 or 0400. It is looked for in `OPENHORA_CREDENTIALS_DIR`, then in `CREDENTIALS_DIRECTORY` (the folder a systemd unit gets for `LoadCredential=` and `LoadCredentialEncrypted=`, and what a container's mounted secrets look like), then in `~/.config/openhora/credentials` when it exists. It is read and never written, a link is refused, and a file is at most 64 KiB. The value is what the environment variable would hold: for a token, the bare token.

```sh
install -d -m 700 ~/.config/openhora/credentials
umask 077 && cat > ~/.config/openhora/credentials/VCS_GITHUB_TOKEN     # type the value, end with Ctrl-D; never on a command line
python3 providers/secrets/resolver.py --check VCS_GITHUB_TOKEN          # found (credentials directory), no value printed
```

With systemd, the unit names the file and the service reads it from `$CREDENTIALS_DIRECTORY`, so the secret exists as a file only in a private memory-backed folder of the service while it runs; `LoadCredentialEncrypted=` keeps it encrypted at rest with the host's key (read the version of systemd the host runs for the user manager's support). The scheduler providers write the unit, and a person adds the `LoadCredential=` lines to it; the runtime does not write a secret.

Why this one (decision recorded in `docs/decisions.md`, 2026-10-15): it adds no dependency, no daemon and no password to type at 3 a.m.; it is the convention systemd, containers and orchestrators already share, so the file can come from any of them; the resolver already treats a value from the environment the same way, so no provider changed; and it is honest about what it protects: a file readable only by its owner is the level of `~/.aws/credentials`, `~/.netrc` or a deploy key, and encryption at rest with a key on the same disk would add the look of protection and not the thing. The alternatives and why they were not chosen: `keyrings.alt`'s file backends (the encrypted one asks for a password the first time, which a headless start cannot give, and the plain one is this directory with a worse format); `pass` (needs a GPG key with no passphrase to be unattended, which is this directory with extra moving parts); a desktop keyring daemon under a virtual session (works until the session or the daemon dies, and then a locked store is back).

### OAuth consent: on a machine with a browser

`providers/mailbox/auth.py --provider gmail` and `providers/publisher/auth.py --provider linkedin` start a listener on the loopback address, open the consent page in a browser and receive the code there, so they run on **a machine with a browser**, never on the headless server. The record they write goes to **that machine's OS secret store** (service `openhora`, store usernames `mailbox-gmail` and `publisher-linkedin`; a JSON object with the token and its dates), not to the server. To use the authorization on the server, put the bare token in the credentials directory: read the record on the machine that has it (`uv run --with keyring==25.7.0 keyring get openhora mailbox-gmail` prints JSON; take `refresh_token`), and write that one value to a file named `GMAIL_REFRESH_TOKEN` (for LinkedIn the file `LINKEDIN_ACCESS_TOKEN`, with the expiry in the environment variable `LINKEDIN_TOKEN_EXPIRES_AT`, as the provider reads it from the environment). The client id and secret of the app go the same way as files. A refresh token of a Google project in "Testing" expires after seven days (the provider's `auth.py` cites the source): a server that runs for weeks needs the project published, or a weekly consent. The runtime never runs the consent itself.

## Retention (I6)

Two keys of `runtime.json`, both optional, accepted in the terminal like every key of the file:

| Key | Default | Range | What it does |
|---|---|---|---|
| `run_retention_days` | 30 | 1 to 3650 | the folder of a run under `<data_dir>/task-runs/<run id>/`, and a folder of `<data_dir>/contained-runs/<n>/`, older than this is removed |
| `source_versions_kept` | 5 | 2 to 1000 | each source keeps its newest versions in the sources folder; the older version folders are removed |

What is never removed (limit L29): the folder of a run whose row is `running` or whose task lock a live process holds; a folder younger than the age (its age is the newest modification time of the folder and of its entries); the dispatcher's `children` folder (it has its own 14 days); the highest numbered `contained-runs` folder; a symbolic link (not followed, not removed); and, for the source versions, **a version a task that is not finished received** (the rows `task_sources` record the id, version and sha256 of what each run received, decision D29; a task is finished when it is `done` or `cancelled`, so a failed task, which can be retried, keeps its version). The minimum of 2 versions is there because a task copies the newest version when it starts: with one kept, a second import during the copy could take it away.

The rows of the store stay, as limit L13 says (a source version's row is never deleted): a pruned version has a row and no folder. Nothing reads an old version (a task receives the newest), the next import is numbered after the highest recorded version, and the catalog still shows the count of versions. The cost and tokens of an old run are columns of its row; only what the run left on disk goes, so the usage that costs recompute from a run's own files is unknown for a run older than the retention.

Where it runs: the dispatcher's round calls `upkeep.run_quietly` as its first step (`runtime/ops_runs.py`), once an hour at most (`<data_dir>/upkeep.json` holds the time of the last pass, and the lock `upkeep.lock` keeps two processes from running it together). A part that fails is reported and tried again at the next hour; the round never fails for it. Every removal goes through the open descriptor of its folder with `O_NOFOLLOW` and a device and inode check (`os.path.samestat`) before it touches anything inside; it deletes nothing outside `data_dir` and the sources folder.

## Orphan containers (I6)

A run starts a container (`wb-eval-run-<run id>`), a key proxy (`wb-eval-keys-<run id>`) and an internal network (`wb-eval-held-<run id>`). When the process that started them dies, the proxy and the network can stay. The harness labels everything it makes `wb.eval=1` and, for a run's own three, `wb.eval.run=<run id>` (`evals/executor.py`; this package does not change that file). The sweep (`runtime/orphans.py`) selects:

1. by label: a container or network whose `wb.eval.run` label holds a run id of 16 hexadecimal characters;
2. by name, for what was started before the label existed: `wb-eval-run-<16 hex>`, `wb-eval-keys-<16 hex>` and `wb-eval-held-<16 hex>`.

It never selects the harness's long-lived objects: its egress proxy (`wb-eval-proxy-<tag>`), its networks (`wb-eval-net-<tag>`, `wb-eval-route-<name>-<tag>`) and its shared key holders (`wb-eval-keys-<12 hex tag>`, named after a hash of the container definition, not a run id): none of those names has 16 hexadecimal characters after a run prefix, and `is_shared` refuses them again just before any removal, whatever their labels. The harness holds no lock per run, so liveness is read from the locks it does hold: a task, router or effect lock of the project's locks folder, and a place of the lab's `total` lock (held around every attempt). When any is held, only what is older than 6 hours is removed (far over a run's timeout); when none is, what is older than 30 minutes (over the 15 minutes an install of dependencies may take, which holds no place of the lab's lock, possibly in another project's runtime on this machine). An object whose age cannot be read is kept. The order is the run's container, its key proxy, its network. Without a docker client, or with `OPENHORA_UPKEEP_CONTAINERS=off`, the sweep is skipped. The sweep goes through the lab facade (`lab.container_tool`), and every test of it uses a fake container tool.

## A synced sources folder: the lease (I4)

The sources folder is the one place a person may keep in a synced drive, so that two machines see it. Two things keep two runtimes from corrupting it (limit L28):

- **The lease.** A writer of the folder first takes its lease, `.openhora-lease` in the folder: host id, host name, pid, when it was taken and when it ends (5 minutes after the last write). A second host that finds a live lease of another host refuses to write and names that host and the time its lease ends; an expired or damaged lease is taken over; this host's own is renewed. It is taken **always**, not only when the folder is known to be synced, because a synced folder cannot be recognised in general (a mounted share, a repository pulled by hand, a sync client the code has never heard of) and the cost is one small file per write. The host id is made once and kept in `<data_dir>/host-id`, never in the synced folder. What the lease cannot do: a sync that takes longer than five minutes to bring it over, and two hosts that start in the same instant, before either file reaches the other. It catches the usual mistake (the runtime left running on two machines against one folder), not every race, and the page says so.
- **Nothing else in a synced folder.** `data_dir` (run folders, locks) and the store's database are refused in one at load: SQLite and a lock file do not survive a sync client. A folder is taken as synced when a component of its real path is the name of a sync client's folder (iCloud Drive, Dropbox, OneDrive, Google Drive, Nextcloud...) or a parent holds a marker a client leaves (`.dropbox`, `.stfolder`...). The list is closed: a client it does not know is not detected, and the refusal names what it saw.

## The doctor's checks

`python3 scripts/doctor.py --unattended --project <dir>` runs these checks on top of the usual report (`--json` has them under `unattended`; `--strict` exits 1 when one warns). It is the one mode of the doctor that asks docker to list and inspect the harness's containers.

| Check | Can verify | Cannot verify |
|---|---|---|
| `linger` (Linux) | `loginctl show-user <user> --property=Linger --value`: whether the user's services survive the last logout and start after a reboot | whether the scheduler's timers are enabled (the scheduler provider's check) |
| `sources_access` (macOS) | whether the folder lies in a place macOS protects (Desktop, Documents, Downloads, iCloud Drive, a cloud provider's folder, a volume) and whether this process can list it | whether the interpreter a launchd job runs has been allowed: no query tells, so for a protected place the status is `unverified` and the detail names the requirement (System Settings > Privacy & Security > Full Disk Access) and how to test it (run the job once and read its log) |
| `disk` | free space on the filesystem of `data_dir` and of `sources_dir` against a threshold (5 GiB; `--min-free-gib`) | a quota, or a full cloud drive behind a sync client |
| `proxy_logs` | `docker inspect` of the containers labelled `wb.eval` whose names are a proxy's or a key holder's: whether a log size limit is set | a container not running here; it reads and never changes |
| `secret_store` | whether the OS secret store answers, is locked or has no backend | that a given secret is in it (`--list` says that) |
| `image` | the eval image in its four states, and the command that sets it up when it is not present: `python3 scripts/image_lock.py pull` (a published image, by digest, with the provenance check) or `python3 evals/executor.py ensure` (a local build). The first pull is an explicit step (decision D39), never automatic and never in the middle of a dispatch | whether the image runs: it is not started |

A status is `ok`, `warn` (with the command that fixes it), `unverified` (the doctor cannot tell from here, and says what to check by hand) or `na` (the check does not apply on this machine).

## Known limits

| Limit | Where |
|---|---|
| The lease covers the common mistake, not a sync slower than five minutes or two hosts starting together | above |
| The macOS permission of a scheduled job on a protected folder cannot be queried; the doctor states the requirement and stays `unverified` | above |
| A token that is a JSON record in the secret store is the bare token in the credentials directory; the expiry of a LinkedIn token is read from the environment only | above |
| The sweep of containers reads liveness from the locks a run holds, since the harness holds none per run; a run longer than 6 hours that holds no lock would be at risk on a busy machine | above |
| A pruned source version leaves a row and no folder | above |

## Changes

- 2026-10-15: first version, with package P-OPS (a locked secret store told apart from a missing one, the credentials directory, retention of run folders and source versions, the orphan sweep, the lease of the sources folder with limits L28 and L29, the doctor's unattended checks).
