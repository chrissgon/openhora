#!/usr/bin/env python3
"""The lock file of the published eval image: write it from what the publishing workflow recorded, or check it.

The eval image is built and published by .github/workflows/eval-image.yml (a push to main that changes
evals/container/, or a manual run on main). The workflow records, as a JSON artifact, the hash of the definition it
built from, the digest of the index it pushed and, for each platform, the digest of its manifest and of its config.
evals/image-lock.json is the file the executor reads to know which published image belongs to a definition. This
script is the only thing that writes it, and it writes it only for what it has verified.

Usage:
  python3 scripts/image_lock.py --from-json <artifact.json> [--source-repo <owner/name>] [--replace] [--lock <file>]
  python3 scripts/image_lock.py --check [--verify-provenance] [--source-repo <owner/name>] [--lock <file>]
  python3 scripts/image_lock.py pull [--source-repo <owner/name>] [--lock <file>]
  python3 scripts/image_lock.py --print-definition-hash

The artifact: {"repository": "ghcr.io/<owner>/<name>", "definition_sha256": "<64 hex>", "index_digest": "sha256:<64 hex>",
"platforms": {"linux/amd64": {"manifest_digest": "sha256:...", "config_digest": "sha256:..."}, "linux/arm64": {...}}}.

--from-json verifies, before it writes anything, that:
  1. the artifact is well formed: both platforms, every digest in the form sha256:<64 hex>, a repository
     ghcr.io/<owner>/<name> in lower case whose owner is the owner of the source repository;
  2. its definition_sha256 equals the hash of this checkout's evals/container/ (evals/executor.py definition_hash):
     an image built from another definition is not the image of this checkout;
  3. the provenance of the index and of each platform manifest verifies, as the workflow of this repository on
     main made it (gh attestation verify oci://<repository>@<digest> --repo <owner/name> --cert-identity
     https://github.com/<owner/name>/.github/workflows/eval-image.yml@refs/heads/main --source-ref refs/heads/main
     --deny-self-hosted-runners; the identity is the exact one, not a prefix);
  4. the registry agrees with the artifact: the index lists the two manifests for their platforms, and each
     manifest names the config digest the artifact gives (docker buildx imagetools inspect --raw).
A failure of any of them writes nothing and exits 1. The lock file is written sorted, with a stable layout. An
entry for a definition that is already in the lock is left as it is when it is equal, and refused when it differs
unless --replace is given (evidence measured in the old digest would no longer match it).

--check reads the lock without writing: it checks its shape, refuses a repository whose owner is not the source
repository's owner (offline too; the source repository is --source-repo or the origin remote), and says whether the
current definition has an entry. It makes no network call unless --verify-provenance is given, which verifies the
provenance of every digest the lock holds. CI runs it with --verify-provenance on every change of the lock
(.github/workflows/image-lock.yml).

pull is the setup step for a published image (decision D39): it verifies the provenance of the lock's entry for this
definition and this platform (the index and the platform manifest), then runs `python3 evals/executor.py pull`, which
pulls <repository>@<manifest digest> and checks the repo digest. Nothing is pulled when the provenance does not verify.

--print-definition-hash prints the hash of this checkout's evals/container/ (the workflow records it).

Needs the GitHub CLI (gh) for the provenance (--from-json, pull, --verify-provenance) and docker with buildx for the
manifests (--from-json). Standard library only. The calls have timeouts and no credential is read or printed: gh and
docker use the maintainer's own login.

Exit codes: 0 ok, 1 refused or failed, 2 usage error.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCK_PATH = os.path.join(ROOT, "evals", "image-lock.json")
EXECUTOR_PATH = os.path.join(ROOT, "evals", "executor.py")
WORKFLOW = ".github/workflows/eval-image.yml"
SOURCE_REF = "refs/heads/main"
PLATFORMS = ("linux/amd64", "linux/arm64")
DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
HEX64 = re.compile(r"[0-9a-f]{64}")
REPOSITORY = re.compile(r"ghcr\.io/([a-z0-9][a-z0-9-]*)/([a-z0-9][a-z0-9._-]*)")
SOURCE = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9._-]+")
TIMEOUT = 120


class Refused(Exception):
    pass


def _executor():
    spec = importlib.util.spec_from_file_location("workbench_image_lock_executor", EXECUTOR_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def definition_hash() -> str:
    """The hash of this checkout's evals/container/, by the executor's own function (a read-only use of it)."""
    return _executor().definition_hash()


def image_platform() -> str:
    """The platform the executor builds, runs and pulls for on this machine (a read-only use of it)."""
    return _executor().image_platform()


# --- reading the lock (also used by runtime/lab.py and scripts/doctor.py) ---------------------------------------------

def empty_lock() -> dict:
    return {"repository": None, "images": {}}


def read_lock(path: str = LOCK_PATH) -> dict:
    """The lock as a dict. A missing file reads as the empty lock; a file that is not JSON or not an object is an error
    (Refused): a lock nobody can read must not pass for an empty one."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return empty_lock()
    except (OSError, ValueError) as e:
        raise Refused(f"{path} cannot be read: {e}") from None
    if not isinstance(data, dict):
        raise Refused(f"{path} is not a JSON object")
    return data


def lock_problems(lock) -> list:
    """What is wrong with the shape of a lock, as sentences; [] when it is well formed. The repository may be null (no
    image published yet) only while there are no images."""
    if not isinstance(lock, dict):
        return ["the lock is not a JSON object"]
    problems = []
    if set(lock) != {"repository", "images"}:
        problems.append("the lock holds exactly the keys repository and images")
    repository, images = lock.get("repository"), lock.get("images")
    if repository is not None and not (isinstance(repository, str) and REPOSITORY.fullmatch(repository)):
        problems.append("repository must be null or ghcr.io/<owner>/<name> in lower case")
    if not isinstance(images, dict):
        return problems + ["images must be an object"]
    if images and repository is None:
        problems.append("images are listed but the repository is null")
    for sha, entry in sorted(images.items()):
        if not HEX64.fullmatch(str(sha)):
            problems.append(f"{sha!r} is not a definition hash (64 hexadecimal characters)")
        problems += [f"{str(sha)[:12]}: {p}" for p in entry_problems(entry)]
    return problems


def entry_problems(entry) -> list:
    if not isinstance(entry, dict) or set(entry) != {"index_digest", "platforms"}:
        return ["an entry holds exactly index_digest and platforms"]
    problems = []
    if not (isinstance(entry["index_digest"], str) and DIGEST.fullmatch(entry["index_digest"])):
        problems.append("index_digest must be sha256:<64 hexadecimal characters>")
    platforms = entry["platforms"]
    if not isinstance(platforms, dict) or not platforms:
        return problems + ["platforms must be a non-empty object"]
    for name, found in sorted(platforms.items()):
        if not re.fullmatch(r"linux/[a-z0-9]+(/[a-z0-9]+)?", str(name)):
            problems.append(f"{name!r} is not a platform such as linux/arm64")
        if not isinstance(found, dict) or set(found) != {"manifest_digest", "config_digest"} or not all(
                isinstance(v, str) and DIGEST.fullmatch(v) for v in found.values()):
            problems.append(f"{name}: manifest_digest and config_digest must be sha256:<64 hexadecimal characters>")
    return problems


def published(lock, definition_sha: str, platform: str):
    """What the lock names for this definition and platform, or None when it names none: {"repository", "ref",
    "manifest_digest", "config_digest", "index_digest"}. ref is <repository>@<manifest_digest>. A lock that is not well
    formed raises Refused: it is never read as an empty one."""
    problems = lock_problems(lock)
    if problems:
        raise Refused("the lock is not well formed: " + "; ".join(problems))
    entry = lock["images"].get(definition_sha)
    found = (entry or {}).get("platforms", {}).get(platform)
    if not found:
        return None
    return {"repository": lock["repository"], "ref": f"{lock['repository']}@{found['manifest_digest']}",
            "manifest_digest": found["manifest_digest"], "config_digest": found["config_digest"],
            "index_digest": entry["index_digest"]}


def published_digests(lock) -> list:
    """Every manifest digest the lock names (any definition, any platform): the images whose evidence is portable."""
    if lock_problems(lock):
        return []
    return sorted({p["manifest_digest"] for e in lock["images"].values() for p in e["platforms"].values()})


def repo_digests(inspect, ref: str):
    """The RepoDigests of the image ref, as a list, or None when the image is not on this machine. inspect(args) runs
    `docker image inspect <args>` and returns (returncode, stdout)."""
    code, out = inspect(["--format", "{{json .RepoDigests}}", ref])
    if code != 0:
        return None
    try:
        found = json.loads(out.strip() or "null")
    except ValueError:
        return None
    return [d for d in found if isinstance(d, str)] if isinstance(found, list) else None


def present(wanted: dict, inspect) -> bool:
    """Whether the published image `wanted` (from published()) is on this machine: the image the reference names has
    exactly the repo digest <repository>@<manifest digest> the lock records, which is what the executor requires too
    (never the index's). The image's own id is never read: it differs between the two image stores of Docker, the repo
    digest does not."""
    return wanted["ref"] in (repo_digests(inspect, wanted["ref"]) or [])


# --- verifying what the workflow recorded ------------------------------------------------------------------------------

def source_repo_default() -> str:
    """owner/name of the origin remote, for --source-repo when it is not given."""
    try:
        r = subprocess.run(["git", "-C", ROOT, "config", "--get", "remote.origin.url"], capture_output=True, text=True,
                           timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    m = re.search(r"github\.com[:/]([^/\s]+/[^/\s]+?)(?:\.git)?\s*$", r.stdout.strip())
    return m.group(1) if m else ""


def verify_attestation(repository: str, digest: str, source_repo: str):
    """None when the provenance of repository@digest verifies, else why not. The one function a test replaces."""
    argv = ["gh", "attestation", "verify", f"oci://{repository}@{digest}", "--repo", source_repo,
            "--cert-identity", f"https://github.com/{source_repo}/{WORKFLOW}@{SOURCE_REF}", "--source-ref", SOURCE_REF,
            "--deny-self-hosted-runners"]
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"gh attestation verify did not run: {e}"
    if r.returncode != 0:
        return f"no valid provenance (gh exit {r.returncode}): {(r.stderr or r.stdout).strip()[:300]}"
    return None


def fetch_manifest(repository: str, digest: str):
    """The manifest or index repository@digest as a dict (docker buildx imagetools inspect --raw). The second function
    a test replaces. Raises Refused when it cannot be read."""
    argv = ["docker", "buildx", "imagetools", "inspect", "--raw", f"{repository}@{digest}"]
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=TIMEOUT)
        if r.returncode != 0:
            raise Refused(f"{repository}@{digest} cannot be read from the registry: {r.stderr.strip()[:300]}")
        found = json.loads(r.stdout)
    except (OSError, subprocess.TimeoutExpired, ValueError) as e:
        raise Refused(f"{repository}@{digest} cannot be read from the registry: {e}") from None
    if not isinstance(found, dict):
        raise Refused(f"{repository}@{digest} is not a manifest")
    return found


def artifact_problems(art, source_repo: str) -> list:
    if not isinstance(art, dict) or set(art) != {"repository", "definition_sha256", "index_digest", "platforms"}:
        return ["the artifact holds exactly repository, definition_sha256, index_digest and platforms"]
    problems = []
    repository = art["repository"]
    m = REPOSITORY.fullmatch(repository) if isinstance(repository, str) else None
    if not m:
        problems.append("repository must be ghcr.io/<owner>/<name> in lower case")
    elif m.group(1) != source_repo.split("/")[0].lower():
        problems.append(f"the repository's owner {m.group(1)!r} is not the source repository's owner")
    if not (isinstance(art["definition_sha256"], str) and HEX64.fullmatch(art["definition_sha256"])):
        problems.append("definition_sha256 must be 64 hexadecimal characters")
    platforms = art["platforms"]
    if not isinstance(platforms, dict) or set(platforms) != set(PLATFORMS):
        problems.append("platforms must be exactly " + " and ".join(PLATFORMS))
    problems += entry_problems({"index_digest": art["index_digest"], "platforms": platforms}) \
        if isinstance(platforms, dict) else []
    return problems


def verify_artifact(art, *, source_repo: str, expected_definition: str, verify, fetch) -> dict:
    """The lock entry {"index_digest", "platforms"} for a verified artifact; raises Refused on the first problem."""
    problems = artifact_problems(art, source_repo)
    if problems:
        raise Refused("the artifact is not well formed: " + "; ".join(problems))
    if art["definition_sha256"] != expected_definition:
        raise Refused(f"the artifact was built from the definition {art['definition_sha256'][:12]}, and this checkout's "
                      f"evals/container/ hashes to {expected_definition[:12]}: build the image from this definition")
    repository = art["repository"]
    digests = [art["index_digest"]] + [art["platforms"][p]["manifest_digest"] for p in PLATFORMS]
    for digest in digests:
        why = verify(repository, digest, source_repo)
        if why:
            raise Refused(f"{repository}@{digest}: {why}")
    index = fetch(repository, art["index_digest"])
    listed = {}
    for item in index.get("manifests") or []:
        platform = item.get("platform") or {}
        listed[f"{platform.get('os')}/{platform.get('architecture')}"] = item.get("digest")
    for name in PLATFORMS:
        found = art["platforms"][name]
        if listed.get(name) != found["manifest_digest"]:
            raise Refused(f"the index {art['index_digest']} does not list {found['manifest_digest']} for {name}")
        config = (fetch(repository, found["manifest_digest"]).get("config") or {}).get("digest")
        if config != found["config_digest"]:
            raise Refused(f"the manifest {found['manifest_digest']} names the config {config}, not {found['config_digest']}")
    return {"index_digest": art["index_digest"],
            "platforms": {p: {"manifest_digest": art["platforms"][p]["manifest_digest"],
                              "config_digest": art["platforms"][p]["config_digest"]} for p in PLATFORMS}}


def merged(lock: dict, repository: str, definition_sha: str, entry: dict, replace: bool) -> dict:
    """The lock with the entry added. Refuses another repository, and a different entry for a definition that has one
    unless replace."""
    problems = lock_problems(lock)
    if problems:
        raise Refused("the existing lock is not well formed: " + "; ".join(problems))
    if lock["repository"] not in (None, repository):
        raise Refused(f"the lock names the repository {lock['repository']}, not {repository}")
    old = lock["images"].get(definition_sha)
    if old is not None and old != entry and not replace:
        raise Refused(f"the lock already holds a different image for the definition {definition_sha[:12]}: evidence "
                      "measured in it would no longer match; pass --replace to replace it")
    images = dict(lock["images"])
    images[definition_sha] = entry
    return {"repository": repository, "images": images}


def render(lock: dict) -> str:
    """The stable layout: sorted keys, two spaces, a final newline."""
    return json.dumps(lock, indent=2, sort_keys=True) + "\n"


def write_lock(path: str, lock: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(render(lock))
    os.replace(tmp, path)


# --- the commands --------------------------------------------------------------------------------------------------

def owner_problem(lock: dict, source_repo: str):
    """Why the lock's repository is not this source repository's to publish to, or None: the owner of
    ghcr.io/<owner>/<name> must be the owner of the source repository (compared in lower case). A lock with no
    repository yet has nothing to compare."""
    repository = lock.get("repository")
    if repository is None:
        return None
    owner = repository.split("/")[1]
    if owner != source_repo.split("/")[0].lower():
        return f"the lock's repository {repository} is not owned by the source repository's owner {source_repo.split('/')[0]}"
    return None


def pull_image() -> int:
    """`python3 evals/executor.py pull` (the executor pulls <repository>@<manifest digest> and checks its repo digest);
    its exit code. The function a test replaces for the pull."""
    try:
        return subprocess.run([sys.executable, EXECUTOR_PATH, "pull"], timeout=3600).returncode
    except (OSError, subprocess.TimeoutExpired) as e:
        print(f"Error: the pull did not run: {e}", file=sys.stderr)
        return 1


def run(argv, *, verify=None, fetch=None, expected_definition=None, platform=None, pull=None, out=None, err=None) -> int:
    """The script, with what a test replaces as arguments: verify(repository, digest, source_repo) -> None or why,
    fetch(repository, digest) -> dict, expected_definition (the hash of this checkout's definition), platform (the
    one the executor pulls for) and pull() -> exit code."""
    out, err = out or sys.stdout, err or sys.stderr
    verify, fetch, pull = verify or verify_attestation, fetch or fetch_manifest, pull or pull_image
    argv = list(argv)
    pulling = bool(argv) and argv[0] == "pull"
    if pulling:
        argv = argv[1:]
    parser = argparse.ArgumentParser(prog="image_lock.py", description=__doc__.strip().split("\n\n")[0],
                                     add_help=False, exit_on_error=False)
    parser.add_argument("--help", "-h", action="store_true")
    parser.add_argument("--from-json")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--verify-provenance", action="store_true")
    parser.add_argument("--print-definition-hash", action="store_true")
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--source-repo")
    parser.add_argument("--lock", default=LOCK_PATH)
    try:
        args = parser.parse_args(argv)
    except (argparse.ArgumentError, SystemExit):
        print("Error: unknown or incomplete option. See --help.", file=err)
        return 2
    if args.help:
        print(__doc__.strip(), file=out)
        return 0
    modes = [bool(args.from_json), args.check, args.print_definition_hash, pulling]
    if sum(modes) != 1 or (pulling and (args.verify_provenance or args.replace)):
        print("Error: give exactly one of --from-json, --check, pull, --print-definition-hash. See --help.", file=err)
        return 2
    try:
        current = expected_definition or definition_hash()
        if args.print_definition_hash:
            print(current, file=out)
            return 0
        lock = read_lock(args.lock)
        problems = lock_problems(lock) if (args.check or pulling) else []
        if problems:
            raise Refused("the lock is not well formed: " + "; ".join(problems))
        source = args.source_repo or source_repo_default()
        needs_source = args.from_json or args.verify_provenance or pulling or (args.check and lock.get("repository"))
        if needs_source and not SOURCE.fullmatch(source):
            print("Error: the source repository is unknown: give --source-repo <owner/name>.", file=err)
            return 2
        if args.check or pulling:
            why = owner_problem(lock, source) if needs_source else None
            if why:
                raise Refused(why)
        if pulling:
            wanted = published(lock, current, platform or image_platform())
            if wanted is None:
                raise Refused(f"the lock names no published image for the definition {current[:12]} and this platform: "
                              "nothing to pull; the image of this definition is built locally with "
                              "`python3 evals/executor.py ensure`")
            for digest in (wanted["index_digest"], wanted["manifest_digest"]):
                why = verify(wanted["repository"], digest, source)
                if why:
                    raise Refused(f"{wanted['repository']}@{digest}: {why}; nothing was pulled")
            print(f"provenance verified for {wanted['ref']}; pulling it", file=out)
            return pull()
        if args.check:
            if args.verify_provenance:
                for sha, entry in sorted(lock["images"].items()):
                    digests = [entry["index_digest"]] + [p["manifest_digest"] for _, p in sorted(entry["platforms"].items())]
                    for digest in digests:
                        why = verify(lock["repository"], digest, source)
                        if why:
                            raise Refused(f"{lock['repository']}@{digest} (definition {sha[:12]}): {why}")
            names = "published: " + ", ".join(sorted(lock["images"][current]["platforms"])) \
                if current in lock["images"] else "no published image for this definition"
            print(f"ok: {len(lock['images'])} image(s) in the lock; the current definition {current[:12]}: {names}", file=out)
            return 0
        try:
            with open(args.from_json, encoding="utf-8") as f:
                art = json.load(f)
        except (OSError, ValueError) as e:
            raise Refused(f"{args.from_json} cannot be read: {e}") from None
        entry = verify_artifact(art, source_repo=source, expected_definition=current, verify=verify, fetch=fetch)
        write_lock(args.lock, merged(lock, art["repository"], current, entry, args.replace))
        print(f"wrote {args.lock}: the image of the definition {current[:12]}, verified", file=out)
        return 0
    except Refused as e:
        print(f"Refused: {e}", file=err)
        return 1


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
