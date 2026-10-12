# Scheduler providers

Implementations of the `scheduler:job` class (`scheduler` until 2026-10-02; the folder and `SCHEDULER_PROVIDER` keep that name). Interface: `providers/CONTRACT.md`, the same in both: `--check`, `schedule --id <id> (--at <ISO-8601 with offset> | --every <minutes>) --command-file <f> (--dry-run | --confirmed --approved <digest>)`, `list`, `cancel --id <id> (--dry-run | --confirmed)`, `resolve --id <id> (--done | --failed) (--dry-run | --confirmed)` and `run --id <id>` (internal: what the service calls; a skill never calls it). The command file holds `argv`, `cwd`, `snapshot`, `outputs`, `grace_minutes` and `timeout_minutes` ("Command file" below and `--help`).

| Implementation | Host | Select with |
|----------------|------|-------------|
| `launchd.py` | macOS, user agent in the login session | `SCHEDULER_PROVIDER=launchd` |
| `systemd.py` | Linux, systemd user units (a VPS) | `SCHEDULER_PROVIDER=systemd` |

Both take the same verbs, flags and command file, and compute the approval digest from the same fields the same way, so a job approved on one means the same thing on the other.

## macOS launchd (`launchd.py`)

Runs a command as a launchd user agent, once at a set time (`--at`) or every N minutes (`--every`, a recurring job). Standard library only; launchd calls it with `/usr/bin/python3`.

### What a job guarantees

- **What was approved is what runs.** `snapshot` is required, and every argument that names an existing file (bare or as `--flag=/path`, absolute or relative to `cwd`) must be in it, or the job is refused; paths the command only writes go in `outputs`. Those two spellings are the ones the scheduler understands: a file named in another one (`-f/abs/file`, `key=/abs/file`, a list joined by `,`, `:` or `;`) cannot be swapped for a copy, so the job is refused instead of running on a file nobody verified. Inside such an argument an absolute path of an existing file counts, and a list counts when every item is an existing file; a sentence that holds a file's name does not. The files are copied into the job folder with their SHA-256 and the arguments are swapped for the copies. The program (`argv[0]`) and this runner are hashed too, and launchd calls a copy of the runner kept in the job folder. Editing the originals, switching branches or merging and deleting the branch changes nothing. At run time the copies, the program and the runner are hashed again; a mismatch records the job as `refused` and runs nothing. Directories (`cwd`, a folder argument) are not snapshotted: files read from them are not verified.
- **Fixed at approval.** The dry run prints an `approved` digest of everything above. The confirmed call must pass it back (`--confirmed --approved <digest>`); if anything changed since the dry run, it refuses and the gate has to show the new dry run.
- **At most once.** The runner takes `run.lock` in the job folder and holds it from reading the job to recording its outcome: it records `running` before the command starts and removes its agent afterwards; a second firing finds the lock or the status and exits. `cancel` and `resolve` change `job.json` only while they hold the same lock, so none of the three writes over another.
- **A one-shot job always ends.** The command runs in its own process group for at most `timeout_minutes` (optional in the command file for `--at`: default 10, 1 to 240, part of the approved digest when given). Past the limit the whole group gets SIGTERM, then SIGKILL 5 seconds later, and the job is `failed` with a reason starting `timeout`. What the command printed is kept as it was written, bytes that are not UTF-8 included, in `run.stdout.log` and `run.stderr.log`, also after a timeout, and a `post_url` it printed before the limit is still read. An error in the runner itself records the job as `failed`. A command that takes longer than 10 minutes (a publication followed by a commit) needs its own `timeout_minutes`.
- **A job left `running` can be settled.** When the runner died mid-run (a crash, a power loss), `job.json` stays `running` and the id is refused by `schedule`. `cancel --id <id> --confirmed` stops whatever still runs and waits up to 15 seconds for a live runner to record its own outcome and let go of the lock (if it still holds the job then, cancel exits 1 and records nothing: run it again); a job still `running` once the lock is free is recorded `cancelled` with `"interrupted": true`: the command may have acted, so check before scheduling it again. `resolve --id <id> (--done | --failed) --confirmed` records what the user found instead; it is refused while a runner still holds the lock. A runner copied into a job folder before this rule holds no lock, so for such a job `resolve` cannot tell and takes the user's word.
- **Late means missed.** launchd fires a time missed during sleep on wake. Within `grace_minutes` (default 120; an integer from 0 to 10080, a week) the command runs; after it, the job is recorded as `missed`. `--at` must carry an offset (`-03:00` or `Z`); a time without one is refused (exit 2), never read as the machine's local time. The plist holds local wall time, so a change of the system time zone after scheduling fires the job early: a firing up to 26 hours early (the widest gap between two time zones) waits in the runner for the time, reading the wall clock every minute, and then runs; `cancel` ends the wait. A firing earlier than that cannot come from a time zone; it is logged and the job stays `scheduled`.
- **A notification** reports every outcome (the post URL when the command prints one), and the job folder keeps `job.json` and the command's output.
- **Private files.** Job folders are 0700, `job.json`, logs and the plist 0600, the copies 0400. Scheduling an id whose job has finished moves the old folder to `.history/` in the jobs folder, which keeps the 100 folders archived last and deletes older ones.
- **Bounded files.** `run.stdout.log` and `run.stderr.log` keep at most the last MiB of what the command printed (the full output is still read for `post_url`), and `launchd.out.log` and `launchd.err.log` are cut to their last MiB at each firing, in place; a file that was cut starts with a line saying how many bytes were dropped. `runs.jsonl` moves to `runs.1.jsonl` past 4 MB.
- **Bounded waits.** Every `launchctl` call times out after 30 seconds; a bootstrap that times out records the job as `failed`.

### Recurring jobs (`--every`)

`schedule --id <id> --every <minutes> --command-file <f> (--dry-run | --confirmed --approved <digest>)`, with `--every` from 5 to 1440 and never together with `--at`. The plist carries `StartInterval` (the minutes in seconds) and no `StartCalendarInterval`. Everything above about snapshots, hashes and the approved digest holds; the digest covers `every_minutes` and `timeout_minutes` instead of `at` and `grace_minutes`, and `job.json` has `"kind": "recurring"` (a one-shot job has no `kind`).

- **Re-verified at every firing.** The copies, the program and the runner are hashed again each time. A mismatch records the firing as `refused`, marks the job `refused` and unloads it: a recurring job that stopped matching its approval does not fire again. Schedule it again, through the dry run and the gate, to resume. The program is the resolved `argv[0]`: when it is an interpreter from a package manager, upgrading the interpreter refuses the job the same way.
- **No overlap.** A firing takes `run.lock` in the job folder (an `flock` plus the holder's PID). A firing that finds it held records `skipped-overlap` and exits. The kernel drops the lock when its holder dies, so a lock left by a runner that died is stale: the next firing takes it over and records `stale_lock_pid`. The command runs in a session of its own, so it can outlive a runner that was killed (launchd's SIGKILL after its exit timeout, a crash): while a firing's command runs, its process-group id is kept in `run.group` beside the lock, and a firing that finds that group still alive records `skipped-overlap` and starts nothing. The record is removed when the command ends, or when a later firing finds the group gone.
- **Bounded firings.** `timeout_minutes` in the command file (default 30, 1 to 240) bounds each firing. The command runs in its own process group; past the limit the group gets SIGTERM, then SIGKILL 5 seconds later, and the firing is recorded as `failed` with a reason starting `timeout`. If launchd stops the runner (a `cancel` during a firing), the runner kills the group the same way and records `failed`.
- **A log of firings.** Each firing appends one JSON line to `runs.jsonl` in the job folder: `started_at`, `ended_at`, `status` (`done`, `failed`, `refused`, `skipped-overlap`), `exit_code`, `reason` when there is one, and `stdout_tail` and `stderr_tail`, the last 4 kB of each. The file is 0600; past 4 MB it moves to `runs.1.jsonl` (replacing the older one). `list` shows each recurring job's `every_minutes` and `last_run` (its last firing without the tails).
- **Notifications on trouble only.** A `refused` firing notifies, and so does a `failed` one whose previous firing did not fail; a job that keeps failing notifies once until it recovers.
- **`cancel --id <id> --confirmed`** unloads it and records `cancelled`, as for a one-shot job.

What launchd does with the interval, from `launchd.plist(5)` (man page dated 30 July 2019, read with `man 5 launchd.plist` on macOS 27.0.1 on 2026-09-29):

- `StartInterval` "causes the job to be started every N seconds". `RunAtLoad` defaults to false, so the first firing comes one interval after `bootstrap`, and after a login, one interval after the agent loads from `~/Library/LaunchAgents`.
- **Sleep:** an interval firing due while the system is asleep "will be missed due to shortcomings in kqueue(3)". The coalescing into one firing on wake that the man page describes belongs to `StartCalendarInterval`, not to `StartInterval`. The provider adds no catch-up: the next firing is the next interval launchd delivers.
- **Overlap:** a firing due while the job still runs is missed by launchd itself; the lock covers any other way the runner is started twice.

A command file for the agent runtime's tick:

```json
{
  "argv": ["/usr/bin/python3", "/abs/openhora/scripts/runtime.py", "tick",
           "--project", "/abs/project", "--pin", "/abs/data/tick-pin.json"],
  "cwd": "/abs/project",
  "snapshot": ["/abs/openhora/scripts/runtime.py", "/abs/openhora/scripts/runtime_vote.py",
               "/abs/openhora/scripts/redact.py", "/abs/openhora/providers/resolve.py",
               "/abs/data/tick-pin.json"],
  "timeout_minutes": 30
}
```

The agent is not an argument: the tick reads it from the project's `docs/workbench/runtime.json`. `argv[0]` is the system interpreter by its fixed path, whose hash does not change with a package upgrade (a bare `python3` is resolved on the approver's `PATH` and hashed wherever it was found). The job runs the copy of `runtime.py` kept in its folder, so whatever that script finds next to itself (its sibling module `runtime_vote.py`; `redact.py`, the credential formats every text is checked against before it is published; and `providers/resolve.py`; the last two it loads from its own folder first and from the configured workbench otherwise) has to be in the snapshot too or passed as an argument; a folder argument such as `--project` is not snapshotted or verified. `--pin` names the file `runtime.py pin --project <dir>` writes (in the runtime's `data_dir`): run it just before scheduling. It holds the sha256 of `runtime.json` and of the gate script, and, being in the snapshot, it is part of what the person approves; at every firing the tick refuses to run when either file differs. What the approval does not cover is listed in `contracts/runtime.md`, "What the approval of a recurring tick covers".

A command file for the task runtime's worker, as `/usr/bin/python3 runtime/dispatcher.py command-file --job work --project <dir> --pin <pin>` prints it (the poller's is the same with `poll` and `"timeout_minutes": 5`):

```json
{
  "argv": ["/usr/bin/python3", "/abs/openhora/runtime/dispatcher.py", "work",
           "--project", "/abs/project", "--pin", "/abs/data/dispatch-pin.json"],
  "cwd": "/abs/project",
  "snapshot": ["/abs/openhora/runtime/dispatcher.py", "/abs/data/dispatch-pin.json"],
  "timeout_minutes": 240
}
```

The entry works alone from its copy: it checks `runtime.json` against the pin `runtime/cli.py pin` wrote before it loads the checkout `runtime.json` names. What the two jobs' approval covers, and how a scheduled run reaches the model's credential, is in `contracts/runtime.md`, "The dispatcher's two jobs".

### Usage

```sh
python3 providers/scheduler/launchd.py --check
python3 providers/scheduler/launchd.py schedule --id <id> --at 2026-09-29T09:00:00-03:00 \
    --command-file job.json --dry-run      # prints the job and its "approved" digest
python3 providers/scheduler/launchd.py schedule --id <id> --at 2026-09-29T09:00:00-03:00 \
    --command-file job.json --confirmed --approved <digest>   # after the calling skill's gate
python3 providers/scheduler/launchd.py schedule --id <id> --every 15 --command-file tick.json --dry-run
python3 providers/scheduler/launchd.py list
python3 providers/scheduler/launchd.py cancel --id <id> --confirmed
```

Command file:

```json
{
  "argv": ["uv", "run", "/abs/providers/publisher/linkedin.py", "publish", "--platform", "linkedin",
           "--text-file", "/abs/post.txt", "--media", "/abs/image.png",
           "--idempotency-key", "launch-post", "--confirmed"],
  "cwd": "/abs/openhora",
  "snapshot": ["/abs/providers/publisher/linkedin.py", "/abs/providers/secrets/resolver.py",
               "/abs/post.txt", "/abs/image.png"],
  "grace_minutes": 120
}
```

A provider reads its credential through `providers/secrets/resolver.py`; the job runs a copy of the provider from its own folder, so the resolver goes into the snapshot too, and the copy finds it next to itself. A job scheduled without it fails at run time with a message that names the snapshot. A job scheduled before the workbench was renamed to openhora carries a resolver that reads the OS secret store under the service `ai-workbench` only: do not delete the old entries (`keyring delete ai-workbench <username>`) until those jobs have run or have been scheduled again, after which the snapshot holds the resolver that reads `openhora` first (`contracts/secrets.md`). Jobs scheduled before 2026-09-28 hold a copy of the provider from before the resolver and run as they are.

Jobs live in `~/Library/Application Support/ai-workbench/scheduler/<id>/`, agents in `~/Library/LaunchAgents/dev.ai-workbench.scheduler.<id>.plist`.

### Requirements at run time

The Mac must be on and the user logged in (a locked screen is fine); a user agent runs in the login session, which is also what lets the publisher read its token from the login keychain. To wake a sleeping Mac, the user can run `sudo pmset schedule wake "MM/DD/YYYY HH:MM:SS"` a few minutes before.

### Rehearse before the real job

Schedule a job two minutes ahead whose command has no side effect (for the LinkedIn publisher, `linkedin.py --check`). The first real use did this and proved, from launchd rather than a terminal, that `uv` resolved, the keychain answered and the agent removed itself.

### Tests

`uv run --with pytest==9.1.1 pytest providers/scheduler/tests`: offline, with a fake `launchctl` (`SCHEDULER_LAUNCHCTL`, honoured only with `SCHEDULER_TEST=1`) and temporary job and agent folders. `test_launchd_recurring.py` covers `--every`; its timeout test shortens the minute in-process instead of adding an environment override.

## Linux systemd (`systemd.py`)

The same verbs, command file and guarantees as `launchd.py`, on the user's systemd service manager: the snapshot and its hashes, the approval digest (same fields, same computation; a test checks that `launchd.py` computes the same digest for a job planned here), re-verification at every firing, at most once, late means missed, the one-shot limit with its kept output and `cancel` and `resolve` of a job left `running` for `--at`, the bounded files (`systemd.out.log` and `systemd.err.log` are cut as launchd's logs are), no overlap, `timeout_minutes` and `runs.jsonl` for `--every`, files 0600 and folders 0700. Standard library only; the service runs the runner's copy with `/usr/bin/python3`.

### What it writes

- `~/.config/systemd/user/dev.ai-workbench.scheduler.<id>.service` (or under `$XDG_CONFIG_HOME`; override `SCHEDULER_UNITS_DIR`): `Type=oneshot`, `ExecStart=` the runner copy with `run --id <id>`, `Environment=` with `PATH`, `SCHEDULER_HOME` and `SCHEDULER_UNITS_DIR`, `UMask=0077`, and stdout and stderr appended to `systemd.out.log` and `systemd.err.log` in the job folder (created 0600 first).
- `dev.ai-workbench.scheduler.<id>.timer` next to it, with `Unit=` the service, `AccuracySec=1s` (the default is 1 minute) and `WantedBy=timers.target`, plus:
  - one-shot (`--at`): `OnCalendar=YYYY-MM-DD HH:MM:SS UTC` and `Persistent=true`;
  - recurring (`--every N`): `OnActiveSec=Nmin` and `OnUnitActiveSec=Nmin`.
- Job folders in `$XDG_DATA_HOME/ai-workbench/scheduler/<id>/` (default `~/.local/share/ai-workbench/scheduler/<id>/`; override `SCHEDULER_HOME`). The folder's path is written into the service unquoted (`append:`), so a path with spaces, quotes, backslashes, `%` or `$` is refused.

Scheduling runs `systemctl --user daemon-reload` and `systemctl --user enable --now <timer>`; if either fails or times out (30 s), the job is `failed` and the unit files are removed. When a one-shot job finishes, or a recurring firing is refused, the runner runs `disable --now <timer>`, for a one-shot timer `clean --what=state <timer>` (the `Persistent=` timestamp), removes both files and runs `daemon-reload`. It never stops its own service. `cancel` does the same plus `stop <service>`, which ends a firing in progress: the runner receives SIGTERM, kills the command's process group and records the firing as `failed`, and systemd's default `KillMode=control-group` then kills anything left in the service's control group, including processes that left the process group.

### Why this mapping

From `systemd.timer(5)`, `systemd.time(7)` and the timer code (`src/core/timer.c`), read on 2026-09-30:

- **One-shot: `OnCalendar=` with the year, in UTC, and `Persistent=true`.** A calendar event with the year names one point in time, so there is no yearly repeat; the 330-day limit is kept only so both providers accept the same jobs. `Persistent=true` stores the last trigger time and, when the timer starts again (at boot, through `timers.target`), triggers the service at once if the time passed while the timer was inactive. Without it, a VPS that was down at the set time would leave the job `scheduled` forever. With it, the runner fires late and applies `grace_minutes`: within the grace the command runs, after it the job is `missed`. That is launchd's "fires on wake, the runner decides", and the runner's check is what decides. A calendar timer due during suspend is acted on at resume either way.
- **Recurring: `OnActiveSec=` plus `OnUnitActiveSec=`, not `OnCalendar=*:0/N`.** A calendar repetition restarts every hour (`*:0/45` fires at :00 and :45), so it cannot express most intervals from 5 to 1440 minutes; the monotonic pair can. `OnUnitActiveSec=` counts from the service's last activation and has no base before the first one, so `OnActiveSec=` gives the first firing one interval after the timer starts, as launchd's `StartInterval` does after loading. `OnBootSec=` was not used: one already in the past elapses at once when the timer is activated, so scheduling would fire immediately. Monotonic timers pause during suspend and `Persistent=` does not apply to them: a missed interval is not caught up, as with launchd.
- **Overlap.** `systemd.timer(5)`: a unit that is still running when the timer elapses "is not restarted, but simply left running", and a `Type=oneshot` service stays "activating" until its program exits. The lock in `run.lock` covers any other start (`systemctl start`, a manual `run`).
- **Timeouts.** `TimeoutStartSec=` is off by default for `Type=oneshot`, so systemd never kills a firing on its own; `timeout_minutes` in the runner does, as on the Mac.

### Requirements at run time

User timers run only while the user's service manager runs, which by default is while the user is logged in. On a server, turn on lingering once: `loginctl enable-linger <user>` (it needs the polkit action `org.freedesktop.login1.set-user-linger`, usually granted to root). `--check` reads `loginctl show-user <user> --property=Linger --value`; it exits 3 with the command to run when lingering is off, and when the user manager cannot be reached (`systemctl --user list-timers` fails).

A server has no desktop: outcomes that launchd.py shows as a macOS notification are appended to `notifications.jsonl` in the jobs folder (0600, its newest whole lines up to 1 MiB) for a notification channel to send; that channel (e-mail) is not built yet. `SCHEDULER_NOTIFY=0` turns it off.

### Usage

```sh
python3 providers/scheduler/systemd.py --check
python3 providers/scheduler/systemd.py schedule --id <id> --at 2026-09-29T09:00:00-03:00 \
    --command-file job.json --dry-run      # prints the job, both unit files and the "approved" digest
python3 providers/scheduler/systemd.py schedule --id <id> --at 2026-09-29T09:00:00-03:00 \
    --command-file job.json --confirmed --approved <digest>
python3 providers/scheduler/systemd.py schedule --id <id> --every 15 --command-file tick.json --dry-run
python3 providers/scheduler/systemd.py list      # units_present instead of plist_present
python3 providers/scheduler/systemd.py cancel --id <id> --confirmed
```

On the host, `systemctl --user list-timers` shows the next firing and `systemd-analyze calendar '<OnCalendar value>'` checks a calendar expression.

### Not verified yet

This provider was written and tested on a Mac without systemd: the tests use a fake `systemctl` and `loginctl` (`SCHEDULER_SYSTEMCTL`, `SCHEDULER_LOGINCTL`, honoured only with `SCHEDULER_TEST=1`). Before the first real job, rehearse on the Linux host as for launchd: a one-shot job two minutes ahead with a side-effect-free command, and a recurring job every 5 minutes, then check `systemd-analyze verify` on both unit files, that the timer fires, that `clean --what=state` is accepted by the host's systemd version, that the units are removed after the one-shot run, that a reboot past a one-shot time records `done` or `missed`, and that timers keep firing after logout with lingering on.

### Sources (accessed 2026-09-30)

freedesktop.org answered with a bot check on 2026-09-30, so the pages were read from their source in the systemd repository (`man/*.xml` and `src/core/timer.c` at commit `889bc48f101a7cbb56cb4be202e85e1f6d933151`, 2026-09-29), which the pages below are generated from:

- systemd.timer(5): https://www.freedesktop.org/software/systemd/man/latest/systemd.timer.html
- systemd.time(7): https://www.freedesktop.org/software/systemd/man/latest/systemd.time.html
- systemd.service(5): https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html
- systemd.exec(5): https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html
- systemd.kill(5): https://www.freedesktop.org/software/systemd/man/latest/systemd.kill.html
- systemd.unit(5): https://www.freedesktop.org/software/systemd/man/latest/systemd.unit.html
- systemd.special(7): https://www.freedesktop.org/software/systemd/man/latest/systemd.special.html
- systemd.syntax(7): https://www.freedesktop.org/software/systemd/man/latest/systemd.syntax.html
- systemctl(1): https://www.freedesktop.org/software/systemd/man/latest/systemctl.html
- loginctl(1): https://www.freedesktop.org/software/systemd/man/latest/loginctl.html
- org.freedesktop.login1(5) (`Linger`, `SetUserLinger()`): https://www.freedesktop.org/software/systemd/man/latest/org.freedesktop.login1.html
- Timer code: https://github.com/systemd/systemd/blob/889bc48f101a7cbb56cb4be202e85e1f6d933151/src/core/timer.c

### Tests

`test_systemd.py`, in the same run as launchd's: offline, with a fake `systemctl` and `loginctl` and temporary job and unit folders. `test_scheduler_one_shot.py` runs once per provider: output that is not UTF-8, the one-shot limit, an error in the runner, `cancel` and `resolve` of a job left `running`. `test_scheduler_parity.py` holds the two providers together: they cannot import a common module (a job runs a copy of one file, alone), so the functions they share are written twice, and the test fails when one of them differs between the files or when a function both define is on neither of its lists. It also checks that the `scheduler:job` row of `providers/CONTRACT.md` and the interface line at the top of this file name every verb, flag and command-file key the two scripts take. `test_systemd.py` covers the dry run and digest parity with `launchd.py`, the unit files and their modes, one-shot and recurring firings, missed, overlap, stale lock, tampering, the timeout that kills the process group, `list`, `cancel`, and `--check` with and without lingering.
