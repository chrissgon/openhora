#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The post as the publishing skill's own script builds it (package PUBLISH-EFFECT): runs skills/mkt-publish/scripts/payload.py, unedited, on one
content file, in a private folder, and reads what it wrote. Nothing is published here and no provider is called.

Why the script and not a second reader of the content file. The skill's script is what decides what a post is: the text of its ```post block, its
first comment, the one image its header names, the key (the file's name without `.md`), the platform's limits (the platform's data file, shared/
references/platforms/<platform>.json), and the refusal of what a platform does not take. Running it, as runtime/effect_reply.py runs mkt-engage's
gate, keeps those rules in one place, and the files the publisher is given are the files the skill's own scheduled job would give it: the same
bytes, so the publisher's ledger sees the same content under the same key, whichever path ran first.

`build` runs `payload.py build --content <file> --platform <p> --platform-file <data file> --workbench <root> --out <private folder>` through
runtime/isolated.py (the interpreter's isolated mode, an environment of five names, the project as the working folder). It passes no `--publisher`, so
no job is written. Its answer is read back: exactly one post, every file under the private folder and a regular file, each file's hash the one the
manifest states, the text UTF-8, and the image (when there is one) a plain relative path of the project whose file, opened with no link anywhere on the
way, has the hash of the copy the script made (a path outside the project, a link or a file changed meanwhile is refused). The fields that payload.py
prints are pinned by runtime/tests/test_publish_post.py, so a later change to that script that breaks this reading fails a test.

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import datetime
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import effect_send  # noqa: E402  (read_project_file: the one reader of a project file with no link on the way)
import isolated  # noqa: E402
import publish_document  # noqa: E402

SKILL, SCRIPT = "mkt-publish", "payload.py"
BUILD_TIMEOUT = 120


class PayloadError(Exception):
    """The script refused the post, or what it wrote is not what it stated. `reason` is a sentence about the post, never its text."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class Built:
    """What `build` read. `folder` is the private folder (0700) that holds the files; `cleanup` removes it."""

    def __init__(self, folder: str, key: str, at: str, text: str, comment, image, paths: dict):
        self.folder, self.key, self.at, self.text, self.comment, self.image, self.paths = folder, key, at, text, comment, image, paths

    def cleanup(self) -> None:
        shutil.rmtree(self.folder, ignore_errors=True)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.cleanup()

    def data(self) -> dict:
        """The post without the folder: what a caller that publishes nothing keeps."""
        return {"key": self.key, "at": self.at, "text": self.text, "comment": self.comment, "image": self.image}


PASSES = ("XDG_DATA_HOME",)   # the publisher's ledger is in the data folder; the skill's own job and this path must see the same one


def platform_file(root: str, platform: str) -> str:
    return os.path.join(root, "shared", "references", "platforms", f"{platform}.json")


def publisher_class(platform: str) -> str:
    """The class of the provider that publishes on this platform (providers/CONTRACT.md: a class with a parameter)."""
    return f"publisher:{publish_document.platform_name(platform)}"


def environment(resolve, platform: str) -> dict:
    """The environment of the publisher's process: the minimum the resolver allows, and the data folder's variable, so that a person whose
    ledger is not under the default place of their home has one ledger for the skill's job and for this path. No token passes: the provider reads
    its own from the secret store."""
    return resolve.provider_environment(publisher_class(platform), None, PASSES)


def _under(folder: str, path) -> str:
    """`path` as a regular file with one link, really inside `folder`, or PayloadError."""
    real = os.path.realpath(path) if isinstance(path, str) else ""
    if not real.startswith(os.path.realpath(folder) + os.sep) or os.path.islink(path) or not os.path.isfile(real):
        raise PayloadError("the payload builder wrote a file outside its folder or no file at all")
    return real


def _read(folder: str, path, expected, what: str) -> bytes:
    real = _under(folder, path)
    with open(real, "rb") as f:
        data = f.read(publish_document.IMAGE_MAX + 1)
    if publish_document.sha(data) != expected:
        raise PayloadError(f"the {what} is not the file whose hash the payload builder stated")
    return data


def ledger_problem(resolve, root: str, platform: str, key: str, args: list, ledger):
    """Why the ledger this path would use may not be the one that decides whether `key` was published, or None. Two ways the same key can be looked up
    in another ledger and a post go out twice: the person's own environment names a ledger (a variable whose name has LEDGER in it) that the publisher,
    started with the minimum environment, does not see; and a scheduled job for this key was pinned to a ledger by `--ledger` (the vote job does it, from the
    tick's environment). `args` are the publisher's `publish` flags without the dry run's; `ledger` is the path a dry run printed (None: the provider names
    none, and there is nothing to compare). A scheduler that cannot be listed has no job to compare with."""
    if not ledger:
        return None
    cls, extra = publisher_class(platform), {k: v for k, v in os.environ.items() if "LEDGER" in k.upper() and v}
    if extra:
        try:
            other = resolve.call(cls, "publish", args + ["--dry-run"], root=root, timeout=120, env={**environment(resolve, platform), **extra})
        except resolve.ProviderCallError as e:
            return f"the publisher's dry run with your ledger variable failed ({e.reason}), so it is not known which ledger you use"
        if isinstance(other, dict) and isinstance(other.get("ledger"), str) and other["ledger"] != ledger:
            return f"your environment names the ledger {other['ledger']} and this path would use {ledger}: set them to one file"
    try:
        listed = resolve.call("scheduler:job", "list", [], root=root, timeout=60, env=resolve.provider_environment("scheduler:job", None, ()))
    except (resolve.ProviderCallError, resolve.UnknownClass):
        return None
    for job in (listed.get("jobs") if isinstance(listed, dict) else None) or []:
        argv = job.get("argv") if isinstance(job, dict) else None
        if not isinstance(argv, list) or not all(isinstance(a, str) for a in argv):
            continue
        keyed = any(argv[i] in ("--idempotency-key", "--key") and argv[i + 1] == key for i in range(len(argv) - 1))
        pinned = [argv[i + 1] for i in range(len(argv) - 1) if argv[i] == "--ledger"]
        if keyed and any(path != ledger for path in pinned):
            return f"a scheduled job for this key is pinned to the ledger {pinned[0]} and this path would use {ledger}: they would not see each other's keys"
    return None


def token_problem(ready, now=None):
    """Why the provider's `--check` answer is no ground to publish now, or None. The publishing skill compares the token's expiry with the last
    slot it schedules; this path publishes now, so the token must be valid now: the answer says ready, and its expiry, when it states one that this
    function can read, is not past."""
    if not isinstance(ready, dict) or ready.get("ready") is not True:
        return "the publisher is not ready"
    expires = ready.get("token_expires_at")
    if isinstance(expires, str) and expires:
        try:
            when = datetime.datetime.fromisoformat(expires.strip().replace("Z", "+00:00").replace("z", "+00:00"))
        except ValueError:
            return None
        if when.tzinfo is None:
            when = when.replace(tzinfo=datetime.timezone.utc)
        if when <= (now or datetime.datetime.now(datetime.timezone.utc)):
            return "the publisher's token has expired"
    return None


def build(root: str, project: str, content: str, platform: str, work_dir=None, run_script=None) -> Built:
    """Run the script and read its answer. `content` is the post's path in the project, `platform` its name in lowercase, `work_dir` the folder the
    private folder is made in (the runtime's data folder; the system's temporary folder when None). `run_script` replaces runtime/isolated.run_script
    (a stand-in in tests). PayloadError when the script refuses or its answer is not what is described above. The caller removes the folder
    (`Built.cleanup`, or `with`)."""
    key = publish_document.content_key(content)
    publish_document.platform_name(platform)
    data_file = platform_file(root, platform)
    if not os.path.isfile(data_file):
        raise PayloadError(f"the platform {platform} has no data file in shared/references/platforms/: the publishing skill's script needs it")
    folder = tempfile.mkdtemp(prefix="openhora-publish-", dir=work_dir)
    try:
        out = os.path.join(folder, "payload")
        args = ["build", "--content", content, "--platform", platform, "--platform-file", data_file, "--workbench", root, "--out", out]
        try:
            done = (run_script or isolated.run_script)(isolated.skill_script(root, SKILL, SCRIPT), args, cwd=project, timeout=BUILD_TIMEOUT)
        except (OSError, subprocess.SubprocessError) as e:
            raise PayloadError(f"the payload builder could not run ({type(e).__name__})") from None
        if done.returncode != 0:
            raise PayloadError("the publishing skill's payload builder refused this post: " + " ".join((done.stderr or "").split())[-300:])
        try:
            answer = json.loads(done.stdout)
        except ValueError:
            answer = None
        posts = answer.get("posts") if isinstance(answer, dict) else None
        if not isinstance(posts, list) or len(posts) != 1 or not isinstance(posts[0], dict) or answer.get("platform") != platform:
            raise PayloadError("the payload builder did not answer exactly one post for this platform")
        entry = posts[0]
        if entry.get("key") != key or not isinstance(entry.get("at"), str) or not publish_document.SLOT.fullmatch(entry["at"]):
            raise PayloadError("the payload builder's key or slot is not the one the content file gives")
        text_bytes = _read(folder, entry.get("post_file"), entry.get("post_sha256"), "post text")
        try:
            text = text_bytes.decode("utf-8")
        except UnicodeDecodeError:
            raise PayloadError("the post is not UTF-8 text") from None
        comment, comment_bytes = None, None
        if entry.get("comment_file") is not None:
            comment_bytes = _read(folder, entry["comment_file"], entry.get("comment_sha256"), "first comment")
            try:
                comment = comment_bytes.decode("utf-8")
            except UnicodeDecodeError:
                raise PayloadError("the first comment is not UTF-8 text") from None
        image = None
        if entry.get("image_file") is not None:
            data = _read(folder, entry["image_file"], entry.get("image_sha256"), "image")
            source = entry.get("image_source")
            if not isinstance(source, str) or not publish_document.IMAGE_SOURCE.fullmatch(source) or ".." in source.split("/"):
                raise PayloadError("the image is outside the project or not a plain path: give a file of the project, relative to its folder")
            try:
                original = effect_send.read_project_file(project, source, publish_document.IMAGE_MAX)
            except (OSError, ValueError):
                raise PayloadError("the image is missing, is a link or is not a regular file of the project") from None
            if publish_document.sha(original) != publish_document.sha(data):
                raise PayloadError("the image changed while the payload was built")
            image = {"source": source, "name": os.path.basename(entry["image_file"]), "bytes": len(data), "sha256": publish_document.sha(data)}
        paths = {"text": _under(folder, entry["post_file"]), "comment": _under(folder, entry["comment_file"]) if comment is not None else None,
                 "image": _under(folder, entry["image_file"]) if image else None}
        return Built(folder, key, entry["at"], text, comment, image, paths)
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)
        raise


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
