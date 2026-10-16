"""A stand-in publisher provider (class publisher:<platform>, serving the platform `linkedin`) for the tests of the publish effect: it behaves as
providers/publisher/linkedin.py does where the runtime depends on it, with no network and no token. Not a test file.

What it models, and nothing else: the verbs `--check` and `publish` (`--dry-run`, `--confirmed`), the idempotency ledger with its states and its
refusals (a published key replays; a key holds one content; a pending key blocks), the dry run that prints the request it would make, the ledger path
and what the ledger holds under the key (`existing_status`), and the failures a real publisher has. It records each call in `calls.jsonl` and each post
it "published" in `posts.jsonl`, both beside the script. The folder of the ledger is $XDG_DATA_HOME when the environment has it, else the script's folder.
`mode.json` beside the script says how it behaves:

  {"check": {...}}                the answer of --check (default: ready, a token that expires in 2099)
  {"check_exit": 3}               the exit code of --check (default 0), with its message on stderr
  {"confirm": "ok" | "refuse" | "unknown" | "comment" | "sleep"}
        ok       publishes (the default)
        refuse   the platform refuses: the key is released, exit 1
        unknown  the outcome is unknown: the key stays pending, exit 1
        comment  the post is published and its first comment fails: exit 1, the key is published
        sleep    claims the key and then waits 5 seconds (a test shortens the runtime's timeout), so the key stays pending
  {"dry_run_text": "..."}         a different text in the dry run's request than the one in the file (a provider that would send something else)
"""
from __future__ import annotations

PUBLISHER = r'''# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
PLATFORMS = ("linkedin",)
import hashlib, json, os, sys, time

here = os.path.dirname(os.path.abspath(__file__))
argv = sys.argv[1:]
mode_file = os.path.join(here, "mode.json")
mode = json.load(open(mode_file)) if os.path.isfile(mode_file) else {}
ledger_path = os.path.join(os.environ.get("XDG_DATA_HOME") or here, "standin-ledger.json")
EXPIRES = "2099-01-01T00:00:00Z"
FLAGS = {"--platform": 1, "--text-file": 1, "--first-comment-file": 1, "--media": 1, "--idempotency-key": 1, "--dry-run": 0, "--confirmed": 0,
         "--check": 0}


def log(entry):
    with open(os.path.join(here, "calls.jsonl"), "a") as f:
        f.write(json.dumps(entry) + "\n")


def usage(message):
    print(message, file=sys.stderr)
    sys.exit(2)


verb = argv[0] if argv and not argv[0].startswith("--") else None
rest = argv[1:] if verb else argv
values, seen, i = {}, [], 0
while i < len(rest):
    name = rest[i]
    if name not in FLAGS:
        usage(f"not a flag of this provider: {name}")
    seen.append(name)
    if FLAGS[name]:
        values[name] = rest[i + 1]
        i += 2
    else:
        i += 1
log({"argv": argv, "xdg_data_home": os.environ.get("XDG_DATA_HOME"), "env": sorted(os.environ)})

if "--check" in seen:
    if mode.get("check_exit"):
        print("the token is missing: run auth.py", file=sys.stderr)
        sys.exit(mode["check_exit"])
    print(json.dumps(mode.get("check") or {"ready": True, "platform": "linkedin", "token_expires_at": EXPIRES}))
    sys.exit(0)
if verb != "publish":
    usage("give a verb")
if values.get("--platform") != "linkedin":
    usage("not served")
key = values.get("--idempotency-key")
if not key or "--text-file" not in values or ("--dry-run" in seen) == ("--confirmed" in seen):
    usage("publish needs a text, a key, and exactly one of --dry-run and --confirmed")


def read(path):
    return open(path, "rb").read()


text = read(values["--text-file"]).decode("utf-8").strip("\n")
media = read(values["--media"]) if "--media" in values else None
comment = read(values["--first-comment-file"]).decode("utf-8").strip("\n") if "--first-comment-file" in values else None
digest = hashlib.sha256(json.dumps({"text": text, "media": hashlib.sha256(media).hexdigest() if media is not None else None},
                                   sort_keys=True).encode()).hexdigest()
ledger = json.load(open(ledger_path)) if os.path.isfile(ledger_path) else {"entries": {}}


def save():
    os.makedirs(os.path.dirname(ledger_path), exist_ok=True)
    json.dump(ledger, open(ledger_path, "w"))


entry = ledger["entries"].get(key)
if "--dry-run" in seen:
    body = {"commentary": mode.get("dry_run_text", text)}
    if media is not None:
        body["media"] = f"<{len(media)} bytes of {values['--media']}>"
    out = {"dry_run": True, "platform": "linkedin", "requests": [{"method": "POST", "url": "https://api.example/rest/posts", "body": body}],
           "idempotency_key": key, "ledger": ledger_path, "existing_status": entry["status"] if entry else None}
    if comment is not None:
        out["first_comment_idempotency_key"] = key + ".first-comment"
        out["first_comment_existing_status"] = (ledger["entries"].get(key + ".first-comment") or {}).get("status")
    print(json.dumps(out))
    sys.exit(0)

how = mode.get("confirm", "ok")


def post_json(urn, replayed, extra=None):
    out = {"platform": "linkedin", "post_urn": urn, "post_url": f"https://www.linkedin.com/feed/update/{urn}/", "token_expires_at": EXPIRES,
           "idempotency_key": key, "replayed": replayed}
    out.update(extra or {})
    return out


def comment_part():
    if comment is None:
        return {}
    done = ledger["entries"].get(key + ".first-comment")
    if done:
        return {"first_comment": {"comment_urn": done["comment_urn"], "idempotency_key": key + ".first-comment", "replayed": True}}
    urn = "urn:li:comment:(urn:li:activity:1,2)"
    ledger["entries"][key + ".first-comment"] = {"status": "published", "comment_urn": urn}
    save()
    return {"first_comment": {"comment_urn": urn, "idempotency_key": key + ".first-comment", "replayed": False}}


if entry:
    if entry["status"] == "pending":
        print(f"idempotency key {key!r} is pending: check the profile, then run resolve", file=sys.stderr)
        sys.exit(1)
    if entry["digest"] != digest:
        print(f"idempotency key {key!r} already holds a post with other content; nothing was sent", file=sys.stderr)
        sys.exit(1)
    print(json.dumps(post_json(entry["post_urn"], True, comment_part())))
    sys.exit(0)

ledger["entries"][key] = {"status": "pending", "digest": digest}
save()
if how == "refuse":
    del ledger["entries"][key]
    save()
    print("the platform refused the post (400)", file=sys.stderr)
    sys.exit(1)
if how == "unknown":
    print("the platform did not answer (timeout); the key stays pending", file=sys.stderr)
    sys.exit(1)
if how == "sleep":
    time.sleep(5)
n = 1 + sum(1 for _ in open(os.path.join(here, "posts.jsonl"))) if os.path.isfile(os.path.join(here, "posts.jsonl")) else 1
urn = f"urn:li:share:70000000000000000{n:02d}"
with open(os.path.join(here, "posts.jsonl"), "a") as f:
    f.write(json.dumps({"key": key, "text": text, "comment": comment, "media_sha256": hashlib.sha256(media).hexdigest() if media is not None else None}) + "\n")
ledger["entries"][key] = {"status": "published", "digest": digest, "post_urn": urn}
save()
if how == "comment":
    print(f"error: the post is published ({urn}) but its first comment failed. Rerun the same command.", file=sys.stderr)
    sys.exit(1)
print(json.dumps(post_json(urn, False, comment_part())))
'''
