#!/usr/bin/env python3
"""A stand-in for the docker command-line client, for the renderer's host-side tests. It reads its script from
$DOCKER_CONFIG/fake.json (DOCKER_CONFIG is one of the few variables the provider passes to the client) and logs every call to
$DOCKER_CONFIG/calls.jsonl. `run` either executes the container's entry point on the host (mapping /job, /out, /in/recording and
/scratch to the mounted folders, with a local Chromium) or does what the script says: sleep, write named files into /out, exit with a code."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

CONFIG = os.environ["DOCKER_CONFIG"]
CFG = json.load(open(os.path.join(CONFIG, "fake.json")))
ARGV = sys.argv[1:]
with open(os.path.join(CONFIG, "calls.jsonl"), "a") as log:
    log.write(json.dumps({"argv": ARGV, "env": sorted(os.environ)}) + "\n")

WITH_VALUE = {"--name", "--label", "--network", "--cap-drop", "--security-opt", "--pids-limit", "--memory", "--memory-swap", "--cpus", "--tmpfs", "--user",
              "-v", "--pull", "-e", "--env-file", "--mount", "--platform", "--shm-size", "--ulimit", "--entrypoint"}


def out(text=""):
    sys.stdout.write(text)
    sys.stdout.flush()


cmd = ARGV[0] if ARGV else ""
if cmd == "version":
    if CFG.get("down"):
        sys.exit(1)
    out("27.0.0\n")
elif cmd == "context":
    out(CFG.get("context", "unix:///var/run/docker.sock") + "\n")
elif cmd == "info":
    out("%d %s\n" % (CFG.get("ncpu", 8), CFG.get("arch", "aarch64")))
elif cmd == "image" and ARGV[1] == "inspect":
    ref = ARGV[2]
    for tag, img in CFG.get("images", {}).items():
        if ref in (tag, img["Id"]):
            out(json.dumps([{"Id": img["Id"], "Config": {"Labels": img["Labels"]}, "Architecture": "arm64"}]))
            sys.exit(0)
    sys.exit(1)
elif cmd == "build":
    args = {a.split("=", 1)[0]: a.split("=", 1)[1] for a in ARGV if "=" in a}
    tag = ARGV[ARGV.index("--tag") + 1]
    labels = {"org.openhora.definition": args.get("DEFINITION_HASH", ""), "org.openhora.chrome.version": args.get("CHROME_VERSION", ""),
              "org.openhora.debian-snapshot": "20261006T000000Z"}
    CFG.setdefault("images", {})[tag] = {"Id": "sha256:" + "ab" * 32, "Labels": labels}
    CFG["built_with"] = {k: args.get(k) for k in ("CHROME_SHA256", "CHROME_URL", "CHROME_SIZE", "CHROME_MD5")}
    json.dump(CFG, open(os.path.join(CONFIG, "fake.json"), "w"))
    sys.exit(CFG.get("build_rc", 0))
elif cmd == "rm":
    sys.exit(0)
elif cmd == "ps":
    out(CFG.get("ps", ""))
elif cmd == "run":
    i, mounts, name = 1, {}, None
    while i < len(ARGV):
        a = ARGV[i]
        if a in WITH_VALUE:
            if a == "-v":
                src, dst, mode = ARGV[i + 1].rsplit(":", 2)
                mounts[dst] = (src, mode)
            if a == "--name":
                name = ARGV[i + 1]
            i += 2
        elif a.startswith("-"):
            i += 1
        else:
            break
    inner = ARGV[i + 1:]
    mode = CFG.get("run", "execute")
    if mode == "sleep":
        time.sleep(600)
        sys.exit(0)
    if mode == "files":
        if CFG.get("stderr"):
            sys.stderr.write(CFG["stderr"])
        if CFG.get("flood"):
            chunk = "x" * 65536
            for _ in range(CFG["flood"] // 65536):
                sys.stderr.write(chunk)
        dest = mounts["/out"][0]
        for fname, spec in CFG.get("files", {}).items():
            path = os.path.join(dest, fname)
            kind = spec.get("kind", "text")
            if kind == "text":
                open(path, "w").write(spec["text"])
            elif kind == "bytes":
                with open(path, "wb") as fh:
                    fh.write(bytes.fromhex(spec["hex"]))
            elif kind == "link":
                os.symlink(spec["target"], path)
            elif kind == "fifo":
                os.mkfifo(path)
            elif kind == "big":
                with open(path, "wb") as fh:
                    fh.truncate(spec["size"])
        sys.exit(CFG.get("rc", 0))
    scratch = tempfile.mkdtemp(prefix="fake-scratch-")
    table = {k: v[0] for k, v in mounts.items()}
    table["/scratch"] = scratch
    import re
    pattern = re.compile("|".join(re.escape(k) for k in sorted(table, key=lambda k: -len(k))) + "(?![A-Za-z0-9_.-])")
    mapped = [pattern.sub(lambda m: table[m.group(0)], a) for a in inner]       # one pass: a host path that holds "/out" is not rewritten again
    if "selfcheck" in inner and CFG.get("selfcheck"):          # the image's own self-check, canned where this machine has no ffmpeg or browser to run it
        with open(mapped[mapped.index("--result") + 1], "w") as fh:
            json.dump(CFG["selfcheck"], fh)
        shutil.rmtree(scratch, ignore_errors=True)
        sys.exit(0)
    env = {"PATH": os.environ["PATH"], "HOME": scratch, "TMPDIR": scratch}
    if CFG.get("browser"):
        env["RENDERER_BROWSER"] = CFG["browser"]
    if "verify" in inner and CFG.get("verify_platform"):          # the fresh container sees a stricter platform file than the render's
        host_platform = mapped[mapped.index("--platform-file") + 1]
        json.dump(CFG["verify_platform"], open(host_platform, "w"))
    inner_py = CFG["inner"]
    done = subprocess.run([sys.executable, "-I", inner_py] + mapped, env=env, cwd=scratch, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    sys.stderr.write(done.stderr.decode("utf-8", "replace")[-300:])
    shutil.rmtree(scratch, ignore_errors=True)
    sys.exit(done.returncode)
else:
    sys.exit(1)
