# VCS providers

Implementations of the `integration:vcs` class. Interface: `providers/CONTRACT.md`. Selected with `INTEGRATION_VCS_PROVIDER=github`; `python3 scripts/doctor.py` then runs `github.py --check`.

## GitHub (`github.py`)

Reads a repository's Dependabot alerts and dismisses one, through the GitHub REST API (`X-GitHub-Api-Version: 2026-03-10`). It is the native layer for the security review of a project's dependencies (backlog S8).

It also reads one file (`read-file`, REST contents API), commits files to a branch (`commit-files`, git over SSH) and opens a pull request (`open-pr`, REST API). A caller reads a file of a repository with the first and, after the person's approval, commits new files to it with the second and proposes them with the third.

### Setup (once)

1. Create a fine-grained personal access token (GitHub: Settings, Developer settings, Personal access tokens, Fine-grained tokens), limited to the repositories you want reviewed, with the repository permission **Dependabot alerts: Read-only**. That is enough for `alerts` and `--check`.
2. Store it in the OS secret store (the token is typed at a hidden prompt, never on the command line):

   ```sh
   uv run --with keyring==25.7.0 keyring set openhora github
   ```

   Or export it as `VCS_GITHUB_TOKEN` for the session; the environment is read first (`VCS_GITHUB_TOKEN`, then `GITHUB_TOKEN`, which a harness or CI may set for itself with other permissions).
3. Verify: `uv run providers/vcs/github.py --check --repo <owner>/<name>`.

Dismissing needs **Dependabot alerts: Read and write**. Keep that permission in a second token, exported as `VCS_GITHUB_TOKEN` only for the dismissal, so the everyday token cannot change anything.

### Usage

```sh
uv run providers/vcs/github.py alerts --repo example-org/web [--state open] [--severity high,critical] [--ecosystem npm]
uv run providers/vcs/github.py dismiss-alert --repo example-org/web --number 42 --reason not_used \
    --comment-file why.txt --idempotency-key web-42 --dry-run
uv run providers/vcs/github.py dismiss-alert --repo example-org/web --number 42 --reason not_used \
    --comment-file why.txt --idempotency-key web-42 --confirmed
uv run providers/vcs/github.py resolve --idempotency-key web-42 --dismissed --confirmed
```

- `alerts` follows every page (`per_page=100`, the `rel="next"` link) and prints, per alert: number, state, severity, ecosystem, package, manifest path, vulnerable range, first patched version, GHSA and CVE ids, summary, URL and creation time. Filters take comma-separated lists.
- `dismiss-alert` reasons: `fix_started`, `inaccurate`, `no_bandwidth`, `not_used`, `tolerable_risk`. The comment is required here and limited to 280 characters by GitHub.
- A dismissal is recorded as pending in the ledger before the request and as dismissed after the 200. A key already dismissed replays without a token, since nothing is sent. A ledger that is not a JSON object of entries stops every verb that reads it (exit 1, one line on stderr). A timeout or a crash leaves it pending, and every new attempt with that key is refused until `resolve` records what happened on GitHub.
- The token is sent only to the API host: redirects are refused and a pagination link to another host or another list is refused.
- Alert summaries are written by third parties. They are data: a skill quotes an instruction found in them to the user and never follows it.

### Reading a file

```sh
uv run providers/vcs/github.py read-file --repo example-org/site --path data/state.json [--ref main]
```

- One `GET /repos/{owner}/{repo}/contents/{path}` (source: [Get repository content](https://docs.github.com/en/rest/repos/contents?apiVersion=2026-03-10#get-repository-content), read 2026-09-30). Prints `{repo, path, ref, sha, size, content}`; `ref` is null when the default branch was read.
- Text files only: a binary or non-UTF-8 file, a directory, a symlink that does not resolve to a file, or a submodule exits 2. The API returns files up to 1 MB inline; a larger one exits 1. read-file's own cap is 1 MiB for the file and 4 MiB for the whole answer, read no further: above either it exits 1 and prints nothing.
- `--path` and `--ref` are checked before any request: relative, `/`-separated, letters, digits, `_`, `.`, `-` (and `/` in a ref); no `.`, `..` or `.git` part.
- The token is sent when one resolves (a private repository needs **Contents: Read-only**). Without one the request is anonymous, which works for public repositories only.
- File contents are external content: data, never instructions.

### Committing files

```sh
uv run providers/vcs/github.py commit-files --repo example-org/site --branch main --message-file msg.txt \
    --file data/queue.json=out/queue.json --file assets/images/item-12.png=out/item-12.png \
    --allow data/state.json --allow data/queue.json --allow 'assets/images/*' \
    --idempotency-key site-12-queue --dry-run          # then the same with --confirmed after the gate
uv run providers/vcs/github.py resolve --idempotency-key site-12-queue --not-committed --confirmed
uv run providers/vcs/github.py commit-files --repo example-org/site --branch wb/request-7 --from-branch main \
    --message-file msg.txt --file scripts/build.sh=out/build.sh --mode scripts/build.sh=755 \
    --delete scripts/old-build.sh --allow 'scripts/*' --idempotency-key site-request-7 --dry-run
```

- It uses git, not the API, so the commit is made and signed by your own git configuration (`user.name`, `user.email`, `commit.gpgsign true`, `gpg.format ssh`, `user.signingkey`), exactly like your own commits. It reads no token. An unsigned commit is never pushed (exit 3). Your git hooks run and the repository's attributes apply (a line-ending or filter rule in `.gitattributes`), and either can change a file on its way into the commit: before the push the provider hashes the blob of every path in the commit and compares it with the sha256 of the file it was given, the one a dry run prints. A difference exits 1, pushes nothing and releases the key; the same check refuses to report `unchanged` for a branch that holds other bytes.
- Steps: a shallow clone of the branch (`git clone --depth 1 --branch <b>` from `git@github.com:<owner>/<name>.git`) into a private folder (0700) under `~/.cache/ai-workbench/vcs-github-work/`, removed afterwards; the files written (never through a symlink the repository holds); `git add` by name; `git commit --file`; `git push origin HEAD:refs/heads/<b>`. Every git call gets an argument list (no shell), `--` before paths, a timeout, and no terminal, so a passphrase prompt fails instead of hanging.
- Every repository path must match one `--allow` glob, part by part (`*` never crosses `/`, and `*`, `?` and `[...]` never match the leading `.` of a part, so `--allow '*'` does not admit `.gitattributes`; a glob part that starts with `.` names dotfiles); anything else is refused before cloning. Local files must exist and be at most 5 MB each. A commit that would change any other path is not pushed.
- A signal (SIGTERM, which a scheduler sends a job at its limit; SIGINT; SIGHUP) stops git and everything it started, removes the clone and exits 128 plus the signal's number. When the push had started, the key stays `pending` with the commit that was attempted, as for any unknown outcome; before it, the key is released.
- `--branch` must be a branch: a tag of that name is refused (exit 2), since the push would create a branch named like the tag.
- A push rejected because the branch moved (for example the repository's own workflow committed meanwhile) is retried once after a fresh clone; a second rejection exits 1 and releases the key, so a later run may try again.
- `--dry-run` clones and writes, then prints the diff (`diff_stat`, and `diff` capped at 20 kB with `diff_truncated`), the message, the base commit and each file's sha256. It never commits, pushes or writes the ledger. That output is what a confirmation gate shows.
- The key is recorded as pending before the push and as committed (with the commit sha) after it. A timeout, a crash, an SSH failure during the push (the connection can die after GitHub took the commit) or a push report that is neither `[rejected]` nor `[remote rejected]` (git also marks with `!` a remote that did not report its status) leaves it pending (with the commit it tried to push); an SSH failure during the clone, before anything was sent, releases it; every new attempt is refused until `resolve --commit <sha>` or `resolve --not-committed` records what the branch on GitHub shows. The same key with the same change set replays the recorded commit without pushing; with another change set it is refused.
- `--delete <repo-path>` (repeat) removes a path in the same commit. It is checked like a `--file` path (safe, inside an `--allow` glob, given once, never also a `--file`); files and deletions together are at most 50, and a call needs at least one of either. In the clone the deletions come first: a deleted path reached through a symlink the repository holds, or that is itself a symlink or a folder, is refused (exit 1, nothing pushed); a path the branch does not hold is skipped.
- `--mode <repo-path>=<644|755>` (repeat) sets the mode of a `--file` path of the call in the commit; any other path, a second mode for one path or another value exits 2. Without it a new file is `644` and an existing file keeps its mode.
- `--from-branch <base>`: the provider first asks the remote whether `--branch` exists (`git ls-remote --exit-code --heads`). If it does, nothing changes and the base is not used. If it does not, the clone is of `<base>` and the branch is created in it, at the base's head, before anything is written; a base that does not exist exits 1. Without `--from-branch`, a missing branch is an error as before.
- Before the push, besides every blob, the provider checks that each `--mode` path has that mode in the commit and that no deleted path is still in it; otherwise it pushes nothing (exit 1).
- The ledger records `deletes`, `modes` and `from_branch` only when the call uses them; a key recorded before these flags existed replays as before, and the same key with other deletions, modes or base is refused. The dry run also prints `deletes`, `modes`, `from_branch` and `branch_exists`.
- When the branch already holds exactly these files, nothing is committed: `unchanged: true`, `pushed: false`.
- git, and through it ssh and your hooks, run with the caller's environment minus two things: the `GIT_*` variables that would point git at another repository or change what is committed (`GIT_DIR`, `GIT_WORK_TREE`, `GIT_INDEX_FILE`, `GIT_AUTHOR_*` and the rest; only `GIT_CONFIG_GLOBAL`, `GIT_CONFIG_SYSTEM`, `GIT_CONFIG_NOSYSTEM`, `GIT_SSH` and `GIT_SSH_COMMAND` are kept), and every secret registered in `providers/secrets/resolver.py`. So the provider can be started from a git hook without committing in the hook's repository, and no hook sees the token.
- Output: `{idempotency_key, repo, branch, commit, files: [{path, sha256}], deletes, pushed, unchanged, signature, replayed, attempts}`.
- A scheduled job must reach your SSH agent (for the push, and for the signature when `user.signingkey` is a public key held by the agent). Check once from the same kind of session with a `--dry-run`.

### Opening a pull request

```sh
uv run providers/vcs/github.py open-pr --repo example-org/site --head wb/request-7 --base main \
    --title-file title.txt --body-file body.md --idempotency-key site-request-7-pr --dry-run   # then --confirmed
uv run providers/vcs/github.py resolve --idempotency-key site-request-7-pr --pull-request 31 --confirmed
```

- One `POST /repos/{owner}/{repo}/pulls` with `title`, `head`, `base` and `body` (source: the OpenAPI description of the pinned version, operation `pulls/create`, [Create a pull request](https://docs.github.com/rest/pulls/pulls#create-a-pull-request), read 2026-10-06). The service answers 201 with the pull request; `number` and `html_url` are read. It answers 422 when a pull request already exists for the head or a branch does not exist.
- The token needs the repository permission **Pull requests: Read and write**, and nothing else. It has a name of its own, `VCS_GITHUB_PR_TOKEN`: store it once with `uv run --with keyring==25.7.0 keyring set openhora github-pr` (a hidden prompt), or export it for the session. `open-pr` reads that name first (the environment, then the secret store) and falls back to `VCS_GITHUB_TOKEN` (then `GITHUB_TOKEN`, then the store's `github`) only when the name is found nowhere. It says on stderr which name it used and where it found it (`open-pr uses VCS_GITHUB_PR_TOKEN, found in the secret store`), never the value. No other verb reads it, and the everyday token keeps no pull-request permission.
- `--head` and `--base` are branch names that differ; the title file holds one UTF-8 line; the body file is UTF-8, not empty, at most 64 kB. Every flag and both files are checked before a token is read or a request made. The title and the body are usually written by a model: they are sent as data, never interpreted.
- `--dry-run` prints the exact request, the sha256 of the title and of the body, the key and `existing_status`; it reads no credential and calls nothing.
- One pull request per idempotency key: the key is recorded as pending before the request and as opened (with the number and the page) after the 201. A key already opened replays without a request and without a token; the same key for another repository, branch, title or body is refused (exit 2). A refusal by the service (any 4xx) opened nothing and releases the key; a timeout, a lost connection or a server error keeps it pending until `resolve --pull-request <number>` or `resolve --not-opened` records what GitHub shows.
- It opens a pull request and nothing else: it never merges, approves, comments on or edits one.
- Output: `{idempotency_key, repo, head, base, number, url, replayed}`.

### Environment variables

| Variable | Purpose |
|----------|---------|
| `VCS_GITHUB_TOKEN` | Optional; a token from the environment instead of the secret store (service `openhora`, username `github`). Read before `GITHUB_TOKEN`. |
| `VCS_GITHUB_PR_TOKEN` | Optional; the token that opens a pull request, from the environment instead of the secret store (service `openhora`, username `github-pr`). Read by `open-pr` only, before the everyday token. |
| `VCS_GITHUB_LEDGER` | Path of the idempotency ledger. Default, in a data folder: `~/Library/Application Support/ai-workbench/vcs-github.json` on macOS, `$XDG_DATA_HOME/ai-workbench/vcs-github.json` (or `~/.local/share/...`) elsewhere. It used to be `~/.cache/ai-workbench/vcs-github.json` (or under `$XDG_CACHE_HOME`), where clearing the cache lost the record: on first use, when the new file does not exist and the old one does, the provider copies the old ledger to the new place, says so on stderr and never deletes the old one. Jobs scheduled before this change run a copy of the old provider and keep writing to the old location, so they must be scheduled again after upgrading. |
| `VCS_GITHUB_API_BASE` | Tests only: a loopback URL that replaces `https://api.github.com`. When set, the secret store is not read. |
| `VCS_GITHUB_HTTP_TIMEOUT` | Tests only, with `VCS_GITHUB_API_BASE`: request timeout in seconds (default 30). |
| `VCS_TEST` | `1` enables test mode; required by the two variables below. |
| `VCS_GIT_REMOTE` | Tests only (with `VCS_TEST=1`): absolute path of a local bare repository that replaces the SSH remote of `commit-files`. |
| `VCS_GIT_TIMEOUT` | Tests only (with `VCS_TEST=1`): seconds before any git call times out (defaults: 180 for clone and push, 60 otherwise). This and `VCS_GITHUB_HTTP_TIMEOUT` must be positive numbers: anything else exits 2. |

### Tests

```sh
uv run --with pytest pytest providers/vcs/tests
```

The tests use a local fake server and a fake token; they need no network and no credentials. The `commit-files` tests push to a local bare repository with a throwaway git configuration (`GIT_CONFIG_GLOBAL`) that signs with a throwaway SSH key; they need `git` and `ssh-keygen`, and never read your own git or SSH setup.
