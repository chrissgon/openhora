#!/usr/bin/env python3
"""The executor: where an eval's commands run. Every model run, grading, case setup and fixture commit
executes in a container built from evals/container/, one container per command (docs/decisions.md,
2026-10-01: one environment, no host mode).

What a container sees:
  /eval               the run's folder (case/, out/, prompt.md), read-write: the only thing a run can change.
                      The runner staged in case/ the copies of the skills this run is given, before the
                      container started (evals/eval_run.py, scripts/stage_skills.py)
  /wb/run-prompt.sh   the one adapter script the command starts, read-only (model runs and gradings only)
Nothing else of the machine or of the workbench: no adapters folder, no skill folder, no shared folder, no
home folder, no other checkout, no credential store.

Network, per command:
  none    no network at all (setup commands, the fixture commit)
  proxy   without a held key: an internal network whose only way out is a proxy that lets through the hosts
          listed in evals/container/proxy/allow.txt, the model providers, with the proxy's address in the
          run's proxy variables. With a held key (below): the route's held network, see next
  open    the default network (a case with "allow_web": true); a run whose key a key proxy holds is put
          on that proxy's open network instead, one of the eval's own, where the proxy also listens

Secrets reach a container as environment variables named by the caller; their values travel in the
environment of the docker client, never on a command line. A variable passed that way can be read by
every command the model runs: that is why the runner replaces the passed values in everything a run
leaves (evals/eval_run.py, "Secrets in what a run leaves"). Each tier's credential is kept out of its
runs instead, by a key proxy of its own (evals/container/keyproxy/: keyproxy.json names the floor model's
provider key, keyproxy-strong.json the strong model's credential). When a command is passed one of those
variables, the run container gets a placeholder in it and its proxy's base URL in the route's
"base_url_env"; that key proxy, a container of its own, holds the value, forwards the route's model
endpoints only ("paths"), to the provider's one host, over HTTPS and through the egress proxy, drops every
credential header a run sends, and adds the key to each call.
The key proxy is on three networks of its route: its own internal network, where the egress proxy is and
no run is (its way to the provider; the floor route's is "keys_network", the strong route's "strong_network",
and the network every run without a held key uses, "network", has no key proxy on it), the open network (where
a web run reaches it) and the held network. The held network
is an internal network that holds only the route's key proxy and its held runs: a run on "proxy" with a held
key is put there and nowhere else, with no proxy variable, so the egress proxy is out of its reach. It can
reach its key proxy, and through it its provider's model endpoints with the key the proxy holds; it cannot
read the key, print it, take it elsewhere, send a credential of its own to a provider or reach the other
tier's proxy. The runner starts the proxy (keyproxy()) before such a command. What stays: the proxy filters
by host name only, and the hosts it lets through serve many accounts, so a run could still hand data to
another account of the same provider through a prompt. Nor is a web run (the open network, by design) held
apart from the open internet. The proxy is not a guarantee that nothing leaves.

Environment. The clock (TZ=UTC), the locale, the user name and the git identity of a run are the
image's own: nothing of the caller's machine sets them. From the caller come only the two variables
that keep git inside the case folder (FORWARD) and the variables the caller names.

Privileges. A run container starts with every capability dropped, with no way to gain a privilege
(no-new-privileges) and with a limit on the number of processes (PIDS_LIMIT).

The image. Its definition is pinned (base images by digest, a dated package index, a lock file for
the two runners), and it is built for one CPU platform, IMAGE_PLATFORM: lab evidence is made on that
platform only. WB_EVAL_IMAGE_PLATFORM builds and runs another one (the CI job, which tests the
definition on its own architecture); `ensure` then says so in "image_platform", and the runner
writes no evidence from such an environment. The images, the networks and the proxies are named after
a hash of evals/container/ (the hash of the definition's text, not of an image: two builds of one
definition can differ, which is why a built image is kept as an archive), so a change to the
definition builds new ones.

Usage (the runner imports this module; the commands are for a person):
  python3 evals/executor.py ensure     build what is missing, start the proxy, print the environment
  python3 evals/executor.py clean      remove the proxies and the networks of the current definition
  python3 evals/executor.py archive --out <file.tar>
                                       save the built image as an archive, to be kept: prints its
                                       sha256, the image's digest and its platform as JSON
"""
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEFINITION = os.path.join(HERE, "container")
KEYPROXY = os.path.join(DEFINITION, "keyproxy")  # the key proxy's definition and its route (keyproxy.json)
ROUTE_FILES = {"floor": "keyproxy.json", "strong": "keyproxy-strong.json"}
NETWORKS = ("none", "proxy", "open")
PROXY_PORT = 8888
RUNNER_MOUNT = "/wb/run-prompt.sh"  # where the one adapter script in use is seen inside a container
# Passed into a container when the caller's environment has them: what keeps git inside the case folder.
# Neither a time zone nor a git identity: both are the image's, the same for every caller.
FORWARD = ("GIT_ALLOW_PROTOCOL", "GIT_TERMINAL_PROMPT")
# The CPU platform lab evidence is made on (the plan's decision 4). Another one is for testing the definition.
IMAGE_PLATFORM = "linux/arm64"
PLATFORM_ENV = "WB_EVAL_IMAGE_PLATFORM"
# The most processes and threads a run container may hold: room for a browser and a test suite, an end to a fork loop.
PIDS_LIMIT = 4096
# What every container of the harness starts without: capabilities, and a way to gain a privilege.
CONFINED = ("--cap-drop", "ALL", "--security-opt", "no-new-privileges")
KEYPROXY_LABEL = "wb.keyproxy"  # a hash of what the running key proxy was started with; never the key
KEYPROXY_READY_SECONDS = 20
KEYPROXY_LOCK = threading.Lock()


class ExecutorError(RuntimeError):
    pass


def definition_hash(folder=DEFINITION):
    """sha256 over the files of evals/container/ (sorted relative paths and their bytes)."""
    h = hashlib.sha256()
    for dp, dns, fns in os.walk(folder):
        dns.sort()
        for fn in sorted(fns):
            path = os.path.join(dp, fn)
            h.update(os.path.relpath(path, folder).encode() + b"\0")
            with open(path, "rb") as f:
                h.update(f.read())
            h.update(b"\0")
    return h.hexdigest()


def image_platform():
    """The CPU platform the image is built for and run as: IMAGE_PLATFORM, unless WB_EVAL_IMAGE_PLATFORM names another."""
    value = os.environ.get(PLATFORM_ENV) or IMAGE_PLATFORM
    if not value.startswith("linux/") or not value[len("linux/"):].replace("/", "").isalnum():
        raise ExecutorError(f"{PLATFORM_ENV} must be a platform such as linux/amd64, not {value!r}")
    return value


def names(folder=DEFINITION):
    tag = definition_hash(folder)[:12]
    if image_platform() != IMAGE_PLATFORM:  # an image of another platform never takes the evidence image's name
        tag += "-" + image_platform().split("/", 1)[1].replace("/", "")
    return {"image": f"wb-eval:{tag}", "proxy_image": f"wb-eval-proxy:{tag}", "network": f"wb-eval-net-{tag}",
            "proxy": f"wb-eval-proxy-{tag}", "keys_image": f"wb-eval-keys:{tag}", "keys": f"wb-eval-keys-{tag}",
            "open_network": f"wb-eval-open-{tag}", "keys_strong": f"wb-eval-keys-strong-{tag}",
            "strong_network": f"wb-eval-strong-{tag}", "strong_open_network": f"wb-eval-strong-open-{tag}",
            "held_network": f"wb-eval-held-{tag}", "strong_held_network": f"wb-eval-strong-held-{tag}",
            "keys_network": f"wb-eval-keys-net-{tag}"}


def route(folder=KEYPROXY, name="floor"):
    """A key proxy's route (keyproxy.json for the floor model, keyproxy-strong.json for the strong one): the variable
    it holds, the placeholder a run gets in its place, the variable that carries the proxy's base URL, the provider,
    the path prefix, the port and the timeout."""
    with open(os.path.join(folder, ROUTE_FILES[name]), encoding="utf-8") as f:
        return json.load(f)


def routes(folder=KEYPROXY):
    """{name: route} of the route files that exist."""
    return {name: route(folder, name) for name, file in ROUTE_FILES.items() if os.path.isfile(os.path.join(folder, file))}


def held_route(pass_names, env=None, network="proxy"):
    """The name of the key proxy a command needs ("floor" or "strong"), or None: the command is passed the variable
    that proxy holds, that variable has a value in the caller's environment, and the command has a network."""
    if network == "none":
        return None
    found = [name for name, r in routes().items() if r["secret"] in (pass_names or ()) and (env or {}).get(r["secret"])]
    if len(found) > 1:
        raise ExecutorError("a command is passed the keys of both key proxies")
    return found[0] if found else None


def holds(pass_names, env=None, network="proxy"):
    """True when a command needs a key proxy (held_route())."""
    return held_route(pass_names, env, network) is not None


def places(name, n=None):
    """(the key proxy's container, its internal network, its open network) of one route. The internal network of a
    key proxy is its route's own, where the egress proxy is and no run is: "network" is the one every run without
    a held key uses, and a key proxy is never on it."""
    n = n or names()
    if name == "strong":
        return n["keys_strong"], n["strong_network"], n["strong_open_network"]
    return n["keys"], n["keys_network"], n["open_network"]


def held_network(name, n=None):
    """The held network of one route: an internal network that holds only that route's key proxy and the run
    containers it serves. The egress proxy is never on it, so a run there has no way out but its key proxy."""
    n = n or names()
    return n["strong_held_network"] if name == "strong" else n["held_network"]


def keyproxy_url(n=None, name="floor"):
    """The base URL a run gives its provider calls: the key proxy of its route, by its name on that route's networks."""
    r, n = route(name=name), n or names()
    path = r["base_path"] if "base_path" in r else r["prefix"].rstrip("/")
    return f"http://{places(name, n)[0]}:{r['port']}{path}"


def docker(*args, env=None, check=True, timeout=1800):
    try:
        r = subprocess.run(["docker", *args], capture_output=True, text=True, env=env, timeout=timeout)
    except FileNotFoundError as e:
        raise ExecutorError("docker is not installed or not on PATH: evals run only in a container") from e
    if check and r.returncode != 0:
        raise ExecutorError(f"docker {' '.join(args[:2])} failed: {(r.stderr or r.stdout).strip()[-400:]}")
    return r


def ensure(env=None):
    """Build the images that are missing, create the eval's networks (an internal and a held network per route,
    an open network per route, and a network where each key proxy and the egress proxy meet), and start the egress
    proxy, which joins the run network and the two key proxies' networks and never a held one (the key proxy starts when a command needs it: keyproxy()). Idempotent, and
    safe when several runners call it at once (a second create of the same name is not an error).
    Returns the environment a record names: the definition's hash, the image, its digest and its platform."""
    n, platform = names(), image_platform()
    if docker("info", "--format", "{{.ServerVersion}}", env=env, check=False).returncode != 0:
        raise ExecutorError("the docker daemon is not running: start it; evals run only in a container")
    for image, folder in ((n["image"], DEFINITION), (n["proxy_image"], os.path.join(DEFINITION, "proxy")),
                          (n["keys_image"], KEYPROXY)):
        if docker("image", "inspect", image, env=env, check=False).returncode != 0:
            docker("build", "-q", "--platform", platform, "-t", image, folder, env=env)
    for network, internal in ((n["network"], True), (n["keys_network"], True), (n["open_network"], False), (n["held_network"], True),
                              (n["strong_network"], True), (n["strong_open_network"], False),
                              (n["strong_held_network"], True)):
        if docker("network", "inspect", network, env=env, check=False).returncode != 0:
            r = docker("network", "create", *(["--internal"] if internal else []), network, env=env, check=False)
            if r.returncode != 0 and "already exists" not in r.stderr:
                raise ExecutorError(f"cannot create the eval network {network}: {r.stderr.strip()[-300:]}")
    state = docker("inspect", "--format", "{{.State.Running}}", n["proxy"], env=env, check=False)
    if state.returncode != 0 or state.stdout.strip() != "true":
        docker("rm", "-f", n["proxy"], env=env, check=False)
        r = docker("run", "-d", "--restart", "unless-stopped", "--platform", platform, *CONFINED, "--name", n["proxy"],
                   n["proxy_image"], env=env, check=False)
        if r.returncode != 0 and "already in use" not in r.stderr:
            raise ExecutorError(f"cannot start the eval proxy: {r.stderr.strip()[-300:]}")
        r = docker("network", "connect", n["network"], n["proxy"], env=env, check=False)
        if r.returncode != 0 and "already exists" not in r.stderr:
            raise ExecutorError(f"cannot connect the eval proxy: {r.stderr.strip()[-300:]}")
    for network in (n["keys_network"], n["strong_network"]):  # the networks of the key proxies, where no run is
        r = docker("network", "connect", network, n["proxy"], env=env, check=False)
        if r.returncode != 0 and "already exists" not in r.stderr:
            raise ExecutorError(f"cannot connect the eval proxy to the key proxies' network {network}: {r.stderr.strip()[-300:]}")
    image_id = docker("image", "inspect", "--format", "{{.Id}}", n["image"], env=env).stdout.strip()
    # image_digest is the id of the built image: it survives `docker save` and `docker load`, so the kept
    # archive and the image a run executed in can be told to be the same. image_id is the same value under
    # the name the records of the first round use.
    return {"kind": "container", "definition_sha256": definition_hash(), "image": n["image"], "image_id": image_id,
            "image_digest": image_id, "image_platform": platform}


def keyproxy(env=None, upstream=None, cafile=None, egress=True, name="floor"):
    """Start the key proxy holding the value the caller's environment has for the route's variable, unless it
    runs already with that value (and the same upstream). Returns its name. The value reaches the proxy's
    container through the docker client's environment, never a command line; the container's label holds a
    hash of what it was started with, so a key stored again (rotated) replaces it. upstream and cafile put a
    test's stand-in in the provider's place, reached directly (egress=False) instead of through the egress
    proxy; a real run passes none of them. The container has no restart policy and is removed when it stops:
    after a restart of docker the next command that needs it starts it again.
    name is the route: "floor" (the default) or "strong"."""
    r, n, platform = route(name=name), names(), image_platform()
    keys, internal, opened = places(name, n)
    value = ((env or {}).get(r["secret"]) or "").strip()
    if not value:
        raise ExecutorError(f"{r['secret']} has no value: the key proxy has no key to hold")
    started_with = json.dumps([value, upstream, os.path.realpath(cafile) if cafile else None, bool(egress)])
    label = hashlib.sha256(b"wb-eval-keyproxy\0" + started_with.encode("utf-8")).hexdigest()
    with KEYPROXY_LOCK:
        state = docker("inspect", "--format", "{{.State.Running}} {{index .Config.Labels \"%s\"}}" % KEYPROXY_LABEL,
                       keys, env=env, check=False)
        if state.returncode == 0 and state.stdout.split() == ["true", label]:
            return keys
        docker("rm", "-f", keys, env=env, check=False)
        argv = ["run", "-d", "--rm", "--init", "--platform", platform, *CONFINED, "--pids-limit", "256",
                "--name", keys, "--label", f"{KEYPROXY_LABEL}={label}", "--network", internal, "-e", r["secret"]]
        if egress:
            argv += ["-e", f"HTTPS_PROXY=http://{n['proxy']}:{PROXY_PORT}"]
        if cafile:
            argv += ["-v", f"{os.path.realpath(cafile)}:/etc/keyproxy/upstream-ca.pem:ro"]
        argv += [n["keys_image"], *(["--route", "/etc/keyproxy/" + ROUTE_FILES[name]] if name != "floor" else []),
                 *(["--upstream", upstream] if upstream else []),
                 *(["--cafile", "/etc/keyproxy/upstream-ca.pem"] if cafile else [])]
        started = docker(*argv, env={**(env or {}), r["secret"]: value}, check=False)
        if started.returncode != 0 and "already in use" not in started.stderr:
            raise ExecutorError(f"cannot start the key proxy: {started.stderr.strip()[-300:]}")
        for what, network in (("open", opened), ("held", held_network(name, n))):
            joined = docker("network", "connect", network, keys, env=env, check=False)
            if joined.returncode != 0 and "already exists" not in joined.stderr:
                docker("rm", "-f", keys, env=env, check=False)  # never left half connected for a later call to reuse by its label
                raise ExecutorError(f"cannot connect the key proxy to the {what} network: {joined.stderr.strip()[-300:]}")
        deadline = time.monotonic() + KEYPROXY_READY_SECONDS
        while "keyproxy: listening" not in docker("logs", keys, env=env, check=False).stderr:
            if time.monotonic() > deadline:
                logs = docker("logs", keys, env=env, check=False)
                docker("rm", "-f", keys, env=env, check=False)
                raise ExecutorError(f"the key proxy did not start: {(logs.stderr or logs.stdout).strip()[-300:]}")
            time.sleep(0.2)
    return keys


def archive(out, env=None):
    """Save the built image as an archive at out. Returns its checksum, the image's digest and its platform:
    the values docs/decisions.md records when a measurement version is closed."""
    environment = ensure(env=env)
    out = os.path.abspath(out)
    if os.path.exists(out):
        raise ExecutorError(f"{out} exists: an archive is never overwritten")
    docker("save", "-o", out, environment["image"], env=env, timeout=3600)
    h = hashlib.sha256()
    with open(out, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return {"archive": out, "archive_sha256": h.hexdigest(), "image": environment["image"],
            "image_digest": environment["image_digest"], "image_platform": environment["image_platform"]}


def clean(env=None):
    n = names()
    docker("rm", "-f", n["keys"], env=env, check=False)
    docker("rm", "-f", n["keys_strong"], env=env, check=False)
    docker("rm", "-f", n["proxy"], env=env, check=False)
    for network in (n["network"], n["keys_network"], n["open_network"], n["held_network"], n["strong_network"],
                    n["strong_open_network"], n["strong_held_network"]):
        docker("network", "rm", network, env=env, check=False)


def mounts(root, runner=None):
    """[(host path, container path, read_only)], longest host path first, for translating a command.
    The run's folder, and the one adapter script the command starts when there is one."""
    pairs = [(root, "/eval", False)]
    if runner:
        pairs.append((runner, RUNNER_MOUNT, True))
    return sorted(pairs, key=lambda p: len(p[0]), reverse=True)


def translate(value, pairs):
    """A host path under a mounted folder becomes its path in the container; anything else is unchanged."""
    for host, inside, _ in pairs:
        for h in dict.fromkeys((host, os.path.realpath(host))):
            if value == h or value.startswith(h + os.sep):
                return inside + value[len(h):]
    return value


def command(cmd, root, cwd=None, env=None, runner=None, pass_names=(), network="none"):
    """(docker argv, container name) that runs cmd in a container. cmd, cwd and the mounts are host paths.
    runner is the adapter script cmd starts: a file, the only one of the workbench the container sees.
    The variable the key proxy holds never enters: it is given the route's placeholder, and on a network the
    run also gets the key proxy's base URL (the caller starts the proxy first: holds(), keyproxy()). A held run
    on "proxy" goes on its route's held network, where only its key proxy is, and gets no proxy variable: it
    has no way to the egress proxy and so none to a provider with a credential of its own."""
    if runner and not os.path.isfile(runner):
        raise ExecutorError(f"the adapter script {runner} does not exist")
    if network not in NETWORKS:
        raise ExecutorError(f"network must be one of {', '.join(NETWORKS)}")
    n, env = names(), env or {}
    pairs = mounts(root, runner)
    name = f"wb-eval-run-{uuid.uuid4().hex[:16]}"
    argv = ["docker", "run", "--rm", "--init", "--platform", image_platform(), *CONFINED,
            "--pids-limit", str(PIDS_LIMIT), "--name", name, "-w", translate(cwd or root, pairs),
            "-e", "ENABLE_CLAUDEAI_MCP_SERVERS=false",
            "-e", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1"]
    if sys.platform.startswith("linux"):  # a bind mount keeps numeric owners there; elsewhere the runtime maps them
        argv += ["--user", f"{os.getuid()}:{os.getgid()}", "-e", "HOME=/home/eval"]
    for host, inside, read_only in pairs:
        if os.path.exists(host):
            argv += ["-v", f"{os.path.realpath(host)}:{inside}" + (":ro" if read_only else "")]
    for key in FORWARD:
        if env.get(key):
            argv += ["-e", f"{key}={env[key]}"]
    held_by = held_route(pass_names, env, network)
    held = held_by is not None
    kept = {r["secret"]: r["placeholder"] for r in routes().values()}  # what a key proxy holds never enters a container
    for key in dict.fromkeys(pass_names):
        if key in kept and env.get(key):
            argv += ["-e", f"{key}={kept[key]}"]  # the key stays with its key proxy
        elif env.get(key):
            argv += ["-e", key]  # the value comes from the docker client's environment
    if held:
        argv += ["-e", f"{route(name=held_by)['base_url_env']}={keyproxy_url(n, held_by)}"]
    _, internal, opened = places(held_by, n) if held else (None, n["network"], None)
    if network == "none":
        argv += ["--network", "none"]
    elif network == "proxy" and held:  # the held network: the key proxy is the only host a run reaches
        argv += ["--network", held_network(held_by, n)]
    elif network == "proxy":
        proxy = f"http://{n['proxy']}:{PROXY_PORT}"
        argv += ["--network", internal]
        for key in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy"):
            argv += ["-e", f"{key}={proxy}"]
        direct = "localhost,127.0.0.1"
        argv += ["-e", f"NO_PROXY={direct}", "-e", f"no_proxy={direct}"]
    elif held:  # open: the open network of the run's own key proxy, where that proxy also listens
        argv += ["--network", opened]
    return argv + [n["image"]] + [translate(a, pairs) for a in cmd], name


def remove(name, env=None):
    """End a container by name: the docker client's process group ending does not end it."""
    docker("rm", "-f", name, env=env, check=False, timeout=60)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv == ["ensure"]:
        print(json.dumps(ensure(), indent=2))
    elif argv == ["clean"]:
        clean()
    elif len(argv) == 3 and argv[:2] == ["archive", "--out"]:
        print(json.dumps(archive(argv[2]), indent=2))
    else:
        print(__doc__.strip())
        return 0 if argv in (["--help"], ["-h"]) else 2
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ExecutorError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
