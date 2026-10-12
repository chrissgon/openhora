# Publisher providers

Implementations of the `publisher:<platform>` class. Interface: `providers/CONTRACT.md`.

## LinkedIn (`linkedin.py`)

Publishes one post as the authenticated member through the versioned Posts API (`LinkedIn-Version: 202609`), with at most one image uploaded through the Images API, and comments on posts through the Comments API: a post's first comment in the same command, or a `comment` verb for replies. The member Posts API has no scheduling: a future `--at` is refused, and scheduling belongs to the `scheduler` class.

### Setup (once)

1. Create an app at https://www.linkedin.com/developers/apps. LinkedIn requires the app to be linked to a LinkedIn Page; posts are still published as you, the member.
2. In the app's Products tab, add "Share on LinkedIn" (scope `w_member_social`) and "Sign In with LinkedIn using OpenID Connect" (scopes `openid profile`).
3. In the Auth tab, add the redirect URL `http://localhost:8765/callback`.
4. Export the client ID and secret in your shell, never in a file:

   ```sh
   export LINKEDIN_CLIENT_ID=...
   export LINKEDIN_CLIENT_SECRET=...
   ```

5. Run `uv run providers/publisher/auth.py --provider linkedin` and approve in the browser. The access token and its expiry go to the OS secret store (service `openhora`, username `publisher-linkedin`), never to disk in plain text. A record authorised before the rename is still read through the fallback to the old service, so authorising again is not required (`contracts/secrets.md`).
6. Verify: `uv run providers/publisher/linkedin.py --check`.

Access tokens last 60 days and self-serve apps get no refresh token. `--check` warns under 7 days; rerun step 5 before expiry.

### Usage

```sh
uv run providers/publisher/linkedin.py publish --platform linkedin \
    --text-file post.txt [--media cover.png] --idempotency-key <k> --dry-run
uv run providers/publisher/linkedin.py publish --platform linkedin \
    --text-file post.txt [--media cover.png] [--first-comment-file link.txt] \
    --idempotency-key <k> --confirmed
uv run providers/publisher/linkedin.py comment --platform linkedin \
    --text-file reply.txt --idempotency-key <k> \
    (--on-key <post key> | --post-id <urn>) [--parent-comment-id <comment urn>] \
    (--dry-run | --confirmed)
uv run providers/publisher/linkedin.py resolve --idempotency-key <k> \
    (--post-id <urn> | --comment-id <urn> | --not-published) --confirmed
uv run providers/publisher/linkedin.py posts --platform linkedin \
    --since <ISO-8601 with an offset>
```

`--post-id`, `--comment-id` and `--parent-comment-id` are the generic names of the publisher class (`providers/CONTRACT.md`, "Identifiers of a class with a parameter"): a caller passes the value it was given and never builds one. On this platform a post id is a post URN and a comment id is a comment URN; their shapes are below and in `shared/references/platforms/linkedin.md`. The names in use before 2026-10-02, `--post-urn`, `--comment-urn` and `--parent-comment`, are accepted as aliases.

Each verb takes only its own flags: a flag the verb does not read (`--media` with `comment`, `--on-key` with `publish`, `--text-file` with `resolve`) is a usage error (exit 2), and so is `--check` with a verb.

The dry run reads no token and sends nothing, so the author URN is shown as a placeholder (`/v2/userinfo` is only called when publishing).

### The first comment

`--first-comment-file <f>` posts that file as a comment on the post right after the post goes out, with the idempotency key `<post key>.first-comment`. One command publishes both, so one scheduler job and one approval cover the post and its first comment. The dry run shows both request bodies; the comment's target is a placeholder until the post exists.

- When the post goes out and the comment fails, the command prints JSON with `post_urn`, `first_comment: null` and `first_comment_error`, and exits 1. Rerun the same command: the post key is `published`, so the post is replayed (not published again) and only the comment is retried.
- On success the JSON has `first_comment` with `comment_urn`, `idempotency_key` and `replayed`.
- When the command is scheduled, the first-comment file is an input file argument like `--text-file`: list it in the job's `snapshot` (`providers/scheduler/README.md`), or the job is refused.

### The comment verb

`comment` posts one comment as the member on a post, or a reply to a comment. The post is given by `--on-key` (the post's publish idempotency key; its ledger entry must be `published`, otherwise the command exits 2) or by `--post-id` (`urn:li:share:<digits>`, `urn:li:ugcPost:<digits>` or `urn:li:activity:<digits>`). `--parent-comment-id urn:li:comment:(urn:li:activity:<digits>,<digits>)` makes it a reply: the request goes to the parent comment and the body carries `parentComment`. Both URNs go into the request path, so their shape is checked strictly and they are URL-encoded. It needs `--confirmed` or `--dry-run`, and prints `comment_urn`, `post_urn`, `parent_comment`, `idempotency_key`, `replayed` and the token expiry fields.

A comment's text is sent as written: the Comments API carries a comment as text plus `attributes` (mentions), not in the little text format, so nothing is escaped. No comment length limit is documented on the Comments API page, so none is enforced; an empty text is refused. LinkedIn limits comment creation per member per minute (`429 Comment create throttled`); the command then exits 1 and the key stays `pending`: a 429 does not say whether the comment was taken, so check the post's comments and run `resolve` before the same command runs again.

### The posts verb

`posts` lists the published posts the ledger records, for a caller that needs them without the network (the task runtime's weekly routine of published posts, `runtime/handlers/published_posts.py`). It is read-only: it reads the ledger and nothing else, reads no token, sends no request, takes no lock and writes nothing, so it needs neither `--confirmed` nor `--dry-run`. A post is an entry whose status is `published` (an entry written before the ledger's version 2 has no status and counts as published when it holds a post URN) and whose kind is not `comment`, so a first comment and a reply are never listed. `--since` must state its offset (`+00:00`, `Z`, ...); a time without one is refused with exit 2. It prints:

```json
{"platform": "linkedin", "since": "<--since as given>", "ledger": "<the ledger read>",
 "posts": [{"idempotency_key": "<k>", "post_url": "https://www.linkedin.com/feed/update/<post urn>/",
            "published_at": "<the entry's created_at>"}],
 "undated": ["<k>"]}
```

`posts` holds the posts whose `created_at` is at or after `--since`, oldest first. `published_at` is the entry's `created_at`, written when LinkedIn answered the post with 201; for a key settled by `resolve --post-id` it is the time `resolve` ran, which can be later than the post. A published post without a readable `created_at` (an entry written before version 2) is listed by key under `undated`, whatever `--since`: no time is derived for it, and the caller decides what to do (the weekly routine stops and lists nothing).

### At most once per key

`--idempotency-key` is required: one key per post or comment, reused on every retry of it. The key is recorded as `pending` in the ledger, under a file lock, before any request, and as `published` with the post or comment URN after LinkedIn's answer; a second run with a published key returns the existing post or comment. A key holds one content: the ledger keeps the sha256 of what was sent (the text as sent, and the image's own sha256), so a run with a published key and other content is refused with exit 1, naming the key, and sends nothing; an entry written before the hash was kept has none and replays as before. `resolve` keeps the hash of the pending attempt. When the outcome is unknown (a timeout, a dropped connection, a 5xx, a 408, a 429 or a crash after the request was sent), the key stays `pending` and every new attempt is refused until the user checks the profile or the post's comments and runs `resolve`: `--post-id <urn>` if the post is there, `--comment-id <urn>` if the comment is there, `--not-published` if it is not. `resolve` needs `--confirmed`; with `--dry-run` it prints what it would record and changes nothing, also when `--confirmed` is given with it. A 4xx answer other than 408 and 429 (LinkedIn refused the request), or a failure before the request, releases the key. A key names either a post or a comment, never both. Redirects are refused, so the token never leaves for a URL that was not checked. The ledger and its lock are 0600, and the ledger is written to a temporary file, synced to disk and then put in place, so a crash leaves the old ledger or the new one. The provider's own data folder is 0700, set so even when it existed with wider permissions; a folder the user chose for the ledger (`PUBLISHER_LINKEDIN_LEDGER`, or `--ledger` elsewhere) keeps its own mode.

The post text is written in LinkedIn's little text format. A `#word` made of ASCII letters, digits and `_`, with at least one letter, not inside a word and not followed by another letter, becomes the documented hashtag template `{hashtag|\#|word}`, so it shows as a hashtag. Every other reserved character (`\ | { } @ [ ] ( ) < > # * _ ~`) is escaped and appears literally: `@name` is plain text, not a mention, and a `#` that does not start such a word (`C#`, `#1`, `#café`) is plain text too.

### To verify on first use

- **Permission to comment, checked on 2026-09-30 with a member token (`w_member_social`).** The versioned endpoint, `POST /rest/socialActions/{target}/comments`, answered `403 Not enough permissions to access: partnerApiSocialActions.CREATE` (partner access). The unversioned `POST /v2/socialActions/{target}/comments`, sent with `--legacy-v2` and the same body without the `LinkedIn-Version` header, created the reply (it returned the new comment URN). The current documentation does not describe `/v2` for members, so it may change. `/v2` is the default for comments and first comments since 2026-09-30; `--comments-endpoint rest` keeps the versioned path for an app with partner access (`--legacy-v2` is kept as an alias of the default, and wins over `--comments-endpoint rest`). Both apply to `comment` and to the first comment of `publish`; they are this implementation's own flags, which a portable caller of the class does not pass (`providers/CONTRACT.md`).
- **Comment text.** That comment text needs no little-text escaping (the Comments API page does not mention the little text format; the little text page names only the Posts API), and whether `#word` in a comment shows as a hashtag.
- **Target of a first comment.** That a comment on a fresh post is accepted with the post's `urn:li:share:` URN as both the request target and `object`, and that the answer carries `commentUrn` (the provider falls back to `object` and `x-restli-id`).
- **Hashtags.** That `{hashtag|\#|word}` in the post commentary renders as a hashtag.

Sources, accessed 2026-09-29: [Comments API](https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/comments-api?view=li-lms-2026-09), [little text format](https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/little-text-format?view=li-lms-2026-09), [getting access](https://learn.microsoft.com/en-us/linkedin/shared/authentication/getting-access).

### Environment variables

| Variable | Used by | Purpose |
|----------|---------|---------|
| `LINKEDIN_CLIENT_ID` | `auth.py` | App client ID; required for the authorization. |
| `LINKEDIN_CLIENT_SECRET` | `auth.py` | App client secret; required for the authorization. |
| `LINKEDIN_ACCESS_TOKEN` | `linkedin.py` | Optional; a token from the environment instead of the secret store. |
| `LINKEDIN_TOKEN_EXPIRES_AT` | `linkedin.py` | Optional; ISO-8601 expiry of `LINKEDIN_ACCESS_TOKEN`. |
| `PUBLISHER_LINKEDIN_LEDGER` | `linkedin.py` | Path of the idempotency ledger. Default, in a data folder: `~/Library/Application Support/ai-workbench/publisher-linkedin.json` on macOS, `$XDG_DATA_HOME/ai-workbench/publisher-linkedin.json` (or `~/.local/share/...`) elsewhere. It used to be `~/.cache/ai-workbench/publisher-linkedin.json` (or under `$XDG_CACHE_HOME`), where clearing the cache lost the record: when the new file does not exist and the old one does, the first verb that writes the ledger copies the old one to the new place, says so on stderr and never deletes the old one; a dry run reads the old one where it is and writes nothing. Jobs scheduled before this change run a copy of the old provider and keep writing to the old location, so they must be scheduled again after upgrading. A scheduler does not pass this variable on to its jobs (launchd and systemd start them with their own short environment): a command that runs later carries `--ledger <path>` instead, with the `ledger` value its dry run printed, and the provider refuses to run (exit 2, nothing sent) when this variable then names another file. Without `--ledger`, a job scheduled from a shell where the variable is set looks its key up in the default ledger at its slot. |
| `LINKEDIN_API_BASE` | `linkedin.py` | Tests only: a loopback URL that replaces `https://api.linkedin.com`. When set, the secret store is not read. |
| `LINKEDIN_HTTP_TIMEOUT` | `linkedin.py` | Tests only, honoured with `LINKEDIN_API_BASE`: request timeout in seconds (default 60). |

### Tests

```sh
uv run --with pytest==9.1.1 pytest providers/publisher/tests
```

The tests use a local fake server and a fake token; they need no network and no credentials. The tests of `posts` (`tests/test_publisher_posts_verb.py`) read a ledger the test writes, with invented keys and post ids.
