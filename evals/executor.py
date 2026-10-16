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
          run's proxy variables. With a held key (below): the run's own network, see next
  open    the default network (a case with "allow_web": true); a run whose key a key proxy holds is put
          on its own network instead, which is not internal, where only its key proxy also listens

Secrets reach a container as environment variables named by the caller; their values travel in the
environment of the docker client, never on a command line. A variable passed that way can be read by
every command the model runs: that is why the runner replaces the passed values in everything a run
leaves (evals/eval_run.py, "Secrets in what a run leaves"). A provider's credential is kept out of its
runs instead, by a key proxy (evals/container/keyproxy/): a route file per provider
(route-<provider>.json) names the variable that holds the key, and the gate file's entry of the run's model
(evals/eval-gate.json, "models") names its route, its pin, the model names its runner sends and its token
budget, so that adding a model to that list changes no file the measurement fingerprint covers. When a
command is passed one of those variables, the run container gets a placeholder in it and its key proxy's
base URL in the route's "base_url_env".

One key proxy per run. hold() starts, for each run, a key proxy container named after the run's container
(wb-eval-keys-<run id>) and an internal network of its own (wb-eval-held-<run id>; one that is not internal for a
run on the web) on which only that run and its key proxy sit, so two runs never share a proxy or a network.
The key proxy is started with the one model of the run, its pin, the names the runner may send and the run's
token budget; it forwards the route's model endpoints only ("paths"), to the provider's one host, over HTTPS and
through the egress proxy, refuses a request whose "model" is not one of those names, drops every credential
header a run sends, adds the key to each call, counts the tokens of each response into a meter file in a folder
(a temporary one of the runner's, outside the run's folder) that only the key proxy mounts, and stops answering
with a stated error when the budget is reached. It is also on its route's internal network, where the egress
proxy is and no run is (its way to the provider; "route_network"). A run on "proxy" with a held key is put on
its own network and nowhere else, with no proxy variable, so the egress proxy is out of its reach. It can reach
its key proxy, and through it its provider's model endpoints with the key the proxy holds; it cannot read the
key, print it, take it elsewhere, send a credential of its own to a provider, call a model other than its own
or reach another run's proxy. release() removes the key proxy and the network when the run ends, on every way
out. What stays: the proxy filters by host name only, and the hosts it lets through serve many accounts, so a
run could still hand data to another account of the same provider through a prompt. Nor is a web run (its own
network is not internal, by design) held apart from the open internet. The proxy is not a guarantee that
nothing leaves.

A local model. A model on the person's own machine (evals/local_models.py, evals/README.md "Testing a local model") is
served by a container of its own beside the run, not by a key proxy: hold_local() starts, for each run, a network
(wb-eval-held-<run id>, always internal) and on it a model server (wb-eval-model-<run id>), the llama.cpp server of the
image evals/local-model-server.json pins by digest, with the weights mounted read-only and nothing else, and with no
published port, no environment variable and no route to the host. The run container (command(local=...)) is put on that
network only, with no proxy variable and no key, and is told two things: LOCAL_MODEL_BASE_URL, the server's address on
that network, and LOCAL_MODEL_CONTEXT. It reaches the server and nothing else. The server is not shared between runs: a
later run (a baseline) could be sped up by, or read, an earlier run's prompt cache, which holds the skill. release_local()
stops the server and removes it and the network on every way out. Nothing here changes a run of a hosted model: its
arguments and its call sequence are those of before (evals/tests/test_executor_local_golden.py proves it).

Every container of the harness carries the labels wb.eval=1 and, for a run's own (the run container, its key
proxy and its network), wb.eval.run=<run id>, so that an orphan left by a crash is found by label; the egress
proxy's and the key proxies' logs are limited in size.

Environment. The clock (TZ=UTC), the locale, the user name and the git identity of a run are the
image's own: nothing of the caller's machine sets them. From the caller come only the two variables
that keep git inside the case folder (FORWARD) and the variables the caller names.

Privileges. A run container starts with every capability dropped, with no way to gain a privilege
(no-new-privileges) and with a limit on the number of processes (PIDS_LIMIT).

The image. Its definition is pinned (base images by digest, a dated package index, a lock file for
the two runners), and it is built for one of the CPU platforms in IMAGE_PLATFORMS: lab evidence is made on either, and the run line
records which. The default is the docker host's own platform when it is one of them (IMAGE_PLATFORM, arm64, when
docker does not say), so that no run is emulated. WB_EVAL_IMAGE_PLATFORM chooses another one; an image for a platform
other than the host's, or not in the list, is a trial (`ensure` says so in "image_platform" and "host_platform", and
the runner writes no evidence from it). The images, the networks and the proxies are named after a hash of
evals/container/ (the hash of the definition's text, not of an image: two builds of one definition can differ,
which is why a built image is kept as an archive), so a change to the definition builds new ones.

The published image. evals/image-lock.json ({"repository", "images": {<definition hash>: {"index_digest",
"platforms": {<platform>: {"manifest_digest", "config_digest"}}}}}) names the image published for a
definition. When it names the current definition and platform, the run image is <repository>@<manifest_digest>,
and `ensure` NEVER pulls or builds it (a pull in the middle of a dispatch is the failure to prevent): if it is
not present it says so and names `python3 scripts/image_lock.py pull` (which verifies the provenance, then calls
`pull` below). The identity of that image, which the
evidence records, is its repo digest (the platform manifest's), never the local image id, which differs from one
image store to another. When the lock names no image for the definition, `ensure` builds it, as before, and its
identity is the local id ("image_source" is "local"; "published" for the other).

Usage (the runner imports this module; the commands are for a person):
  python3 evals/executor.py ensure     build what is missing, start the proxy, print the environment
  python3 evals/executor.py pull       pull the published image the lock names for this definition and platform,
                                       and check its repo digest equals the lock's
  python3 evals/executor.py pull-local-server [--accelerator cpu|cuda]
                                       pull the llama.cpp server image evals/local-model-server.json pins (by digest) and
                                       check docker lists that digest for it; a test of a local model never pulls
  python3 evals/executor.py clean      remove the egress proxy and the networks of the current definition
  python3 evals/executor.py archive --out <file.tar>
                                       save the built image as an archive, to be kept: prints its
                                       sha256, the image's digest and its platform as JSON
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEFINITION = os.path.join(HERE, "container")
KEYPROXY = os.path.join(DEFINITION, "keyproxy")  # the key proxy's definition and its route files (route-<provider>.json)
GATE_FILE = os.path.join(HERE, "eval-gate.json")  # the model list: outside the fingerprint, so a model is a line in it
LOCK_FILE = os.path.join(HERE, "image-lock.json")  # the published image of each definition, outside the fingerprint
ROUTE_PREFIX, ROUTE_SUFFIX = "route-", ".json"
NETWORKS = ("none", "proxy", "open")
PROXY_PORT = 8888
RUNNER_MOUNT = "/wb/run-prompt.sh"  # where the one adapter script in use is seen inside a container
METER_MOUNT = "/meter"  # where only a key proxy sees its run's meter folder
# Passed into a container when the caller's environment has them: what keeps git inside the case folder.
# Neither a time zone nor a git identity: both are the image's, the same for every caller.
FORWARD = ("GIT_ALLOW_PROTOCOL", "GIT_TERMINAL_PROMPT")
# The CPU platforms lab evidence is made on (the plan's decisions 4 and 20); the first is the default. Another
# one is for testing the definition.
IMAGE_PLATFORMS = ("linux/arm64", "linux/amd64")
IMAGE_PLATFORM = IMAGE_PLATFORMS[0]
PLATFORM_ENV = "WB_EVAL_IMAGE_PLATFORM"
# The most processes and threads a run container may hold: room for a browser and a test suite, an end to a fork loop.
PIDS_LIMIT = 4096
# What every container of the harness starts without: capabilities, and a way to gain a privilege.
CONFINED = ("--cap-drop", "ALL", "--security-opt", "no-new-privileges")
# The size of the log a long-lived container keeps: three files of 10 MB at most.
LOG_OPTS = ("--log-opt", "max-size=10m", "--log-opt", "max-file=3")
NO_PULL = "--pull=never"  # no `docker run` of the harness fetches an image: a missing one is an error, never a download
LABEL_ALL, LABEL_RUN = "wb.eval", "wb.eval.run"  # on every container and network of the harness; the run's id on a run's own
KEYPROXY_READY_SECONDS = 20
LOCAL_SERVER_FILE = os.path.join(HERE, "local-model-server.json")  # the pinned model server images, outside the fingerprint
LOCAL_IMAGE_RE = re.compile(r"ghcr\.io/ggml-org/llama\.cpp:[A-Za-z0-9._-]+@sha256:[0-9a-f]{64}")
LOCAL_REPOSITORY = "ghcr.io/ggml-org/llama.cpp"
MODEL_PORT = 8080  # where the model server listens, on the run's internal network only
LOCAL_POLL_SECONDS = 1.0  # how often a starting model server is looked at
LOCAL_HEALTH_INTERVAL = "2s"  # the image's HEALTHCHECK runs every 30 s by default: a server that is ready is seen within seconds
LOCAL_LOAD_DEFAULT = 900  # seconds a model server has to load its weights (the configuration may lower or raise it, up to 1500)
LOCAL_MAX_THREADS = 128  # the server's threads are capped well under its process limit (256): its own helper threads count too
STOP_SECONDS = 10  # how long a stopping key proxy has to write what it still holds
RUN_ID_RE = re.compile(r"[0-9a-f]{16}")
DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}")
REPOSITORY_RE = re.compile(r"ghcr\.io/[a-z0-9]([a-z0-9-]*[a-z0-9])?/[a-z0-9]+([._-][a-z0-9]+)*")  # ghcr.io/<owner>/<name>, lowercase
PULL_COMMAND = "python3 scripts/image_lock.py pull"  # what a person runs: it verifies the provenance, then calls pull() here


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


_NATIVE = {}  # the docker host's platform, asked until docker answers, then once per process


def native_platform():
    """The docker host's CPU platform, asked of docker until it answers and then once per process (None when docker
    says another platform than the listed ones). A docker that does not answer (not running yet, not installed, timed
    out) is not an answer: None is returned and nothing is kept, so that a long-lived process started before the
    docker daemon asks again instead of defaulting to arm64 for its whole life."""
    if "platform" not in _NATIVE:
        try:
            answered, platform = asked_host_platform()
        except (ExecutorError, subprocess.SubprocessError, OSError):
            return None
        if not answered:
            return None
        _NATIVE["platform"] = platform
    return _NATIVE["platform"]


def image_platform():
    """The CPU platform the image is built for and run as: WB_EVAL_IMAGE_PLATFORM when it is set; else the docker host's
    own platform when it is one of IMAGE_PLATFORMS, so that an amd64 host builds and runs amd64 natively and never
    emulates arm64; else IMAGE_PLATFORM (arm64)."""
    native = None if os.environ.get(PLATFORM_ENV) else native_platform()  # asked once: each ask of a hung daemon costs a timeout
    value = os.environ.get(PLATFORM_ENV) or (native if native in IMAGE_PLATFORMS else IMAGE_PLATFORM)
    if not value.startswith("linux/") or not value[len("linux/"):].replace("/", "").isalnum():
        raise ExecutorError(f"{PLATFORM_ENV} must be a platform such as linux/amd64, not {value!r}")
    return value


def image_lock(path=None):
    """The lock file's content: {"repository": str or None, "images": {definition hash: entry}}. A missing file is
    an empty lock; a file that is not in its form is an error (the runner never guesses which image to trust)."""
    path = path or LOCK_FILE
    if not os.path.isfile(path):
        return {"repository": None, "images": {}}
    try:
        with open(path, encoding="utf-8") as f:
            lock = json.load(f)
    except (OSError, ValueError) as e:
        raise ExecutorError(f"{path} is not valid JSON: {e}") from None
    problems = lock_problems(lock)
    if problems:
        raise ExecutorError(f"{path} is not a valid lock file: {problems[0]}")
    return lock


def lock_problems(lock):
    """Why a lock file is outside its form; [] when it is valid."""
    if not (isinstance(lock, dict) and set(lock) == {"repository", "images"}):
        return ["it must be {\"repository\": ..., \"images\": {...}}"]
    repository, images = lock["repository"], lock["images"]
    if repository is not None and not (isinstance(repository, str) and REPOSITORY_RE.fullmatch(repository)):
        return ["repository must be ghcr.io/<owner>/<name> in lowercase, or null"]
    if not isinstance(images, dict):
        return ["images must map a definition hash to its entry"]
    if images and repository is None:
        return ["images names an image but repository is null"]
    for definition, entry in images.items():
        if not re.fullmatch(r"[0-9a-f]{64}", definition):
            return [f"{definition!r} is not a definition hash (64 hexadecimal characters)"]
        platforms = entry.get("platforms") if isinstance(entry, dict) else None
        if not (isinstance(entry, dict) and set(entry) == {"index_digest", "platforms"} and DIGEST_RE.fullmatch(str(entry.get("index_digest")))
                and isinstance(platforms, dict) and platforms):
            return [f"the entry of {definition[:12]} must be exactly an index_digest and a non-empty platforms"]
        for platform, digests in platforms.items():
            if not (re.fullmatch(r"linux/[a-z0-9]+(/[a-z0-9]+)?", platform) and isinstance(digests, dict)
                    and set(digests) == {"manifest_digest", "config_digest"} and DIGEST_RE.fullmatch(str(digests.get("manifest_digest"))) and DIGEST_RE.fullmatch(str(digests.get("config_digest")))):
                return [f"the entry of {definition[:12]} for {platform!r} must be exactly a manifest_digest and a config_digest, each sha256:<64 hex>"]
    return []


def published_image(folder=DEFINITION, platform=None, lock=None):
    """{"ref": <repository>@<manifest_digest>, "manifest_digest", "config_digest"} of the image the lock publishes for
    the definition at folder on the platform, or None when the lock names none (the image is then built here)."""
    lock = image_lock() if lock is None else lock
    entry = (lock.get("images") or {}).get(definition_hash(folder))
    found = ((entry or {}).get("platforms") or {}).get(platform or image_platform())
    if not found:
        return None
    return {"ref": f"{lock['repository']}@{found['manifest_digest']}", "manifest_digest": found["manifest_digest"],
            "config_digest": found["config_digest"]}


def names(folder=DEFINITION):
    tag = definition_hash(folder)[:12]
    if image_platform() != IMAGE_PLATFORM:  # an image of another platform never takes the default one's name
        tag += "-" + image_platform().split("/", 1)[1].replace("/", "")
    published = published_image(folder)
    return {"image": published["ref"] if published else f"wb-eval:{tag}", "proxy_image": f"wb-eval-proxy:{tag}",
            "network": f"wb-eval-net-{tag}", "proxy": f"wb-eval-proxy-{tag}", "keys_image": f"wb-eval-keys:{tag}",
            "tag": tag}


def route_file(name, folder=KEYPROXY):
    return f"{ROUTE_PREFIX}{name}{ROUTE_SUFFIX}"


def route_names(folder=KEYPROXY):
    """The providers that have a route file, sorted."""
    if not os.path.isdir(folder):
        return []
    return sorted(f[len(ROUTE_PREFIX):-len(ROUTE_SUFFIX)] for f in os.listdir(folder)
                  if f.startswith(ROUTE_PREFIX) and f.endswith(ROUTE_SUFFIX) and re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", f[len(ROUTE_PREFIX):-len(ROUTE_SUFFIX)]))


def route(folder=KEYPROXY, name="openrouter"):
    """A provider's route (route-<provider>.json): the variable it holds, the placeholder a run gets in its place, the
    variable that carries its key proxy's base URL, the provider, the path prefix, the port and the timeout."""
    if name not in route_names(folder):
        raise ExecutorError(f"there is no route {name!r}: the key proxy's folder holds {', '.join(route_names(folder)) or 'none'}")
    with open(os.path.join(folder, route_file(name)), encoding="utf-8") as f:
        return json.load(f)


def routes(folder=KEYPROXY):
    """{name: route} of the route files that exist."""
    return {name: route(folder, name) for name in route_names(folder)}


def route_network(name, n=None):
    """The internal network of one provider's route: where the egress proxy is, and the key proxies of the runs that
    use the route, and no run. A key proxy's way to its provider; never a network a run is on."""
    return f"wb-eval-route-{name}-{(n or names())['tag']}"


def model_entry(model, gate=None):
    """The object-shaped entry of the gate file's "models" for the model id or alias, with its listed id under "id",
    or None (no such model, or one listed in the old form, a list of aliases, which has no route). The gate file is
    read at each call: a model added to it is served at once."""
    path = gate or GATE_FILE
    if not model or not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            models = json.load(f).get("models")
    except (OSError, ValueError, AttributeError):
        return None
    if not isinstance(models, dict):
        return None
    for listed, entry in models.items():
        aliases = entry.get("aliases") if isinstance(entry, dict) else entry
        if model == listed or model in (aliases or []):
            return {**entry, "id": listed} if isinstance(entry, dict) else None
    return None


def held_route(pass_names, env=None, network="proxy", model=None, gate=None):
    """The name of the route (the provider) a command needs a key proxy of, or None: the command is passed the
    variable a route holds, that variable has a value in the caller's environment, and the command has a network.
    The route is the one the gate file's entry of the command's model names; a held key passed to a command that
    names no such model, or to a model of another route, is an error and never a command that holds the key."""
    if network == "none":
        return None
    secrets = {r["secret"]: name for name, r in routes().items()}
    carried = {secrets[v] for v in dict.fromkeys(pass_names or ()) if v in secrets and (env or {}).get(v)}
    if not carried:
        return None
    entry = model_entry(model, gate)
    if entry is None or not entry.get("route"):
        raise ExecutorError("a command is passed a key a key proxy holds, and the model it runs "
                            f"({model!r}) has no object entry with a route in the gate file's models")
    if carried != {entry["route"]}:
        raise ExecutorError(f"a command is passed the key of {', '.join(sorted(carried))} and its model {entry['id']!r} "
                            f"is served by {entry['route']!r}: one command, one key proxy")
    return entry["route"]


def holds(pass_names, env=None, network="proxy", model=None, gate=None):
    """True when a command needs a key proxy (held_route())."""
    return held_route(pass_names, env, network, model, gate) is not None


def new_run_id():
    return uuid.uuid4().hex[:16]


def run_names(run_id):
    """The names of one run's own container, key proxy, model server and network, after its id."""
    if not RUN_ID_RE.fullmatch(str(run_id)):
        raise ExecutorError("a run id is 16 hexadecimal characters")
    return {"container": f"wb-eval-run-{run_id}", "keys": f"wb-eval-keys-{run_id}", "network": f"wb-eval-held-{run_id}",
            "model": f"wb-eval-model-{run_id}"}


def labels(run_id=None):
    """The docker arguments that label a container or a network of the harness (and of one run, when run_id is given)."""
    return ["--label", f"{LABEL_ALL}=1", *(["--label", f"{LABEL_RUN}={run_id}"] if run_id else [])]


def user():
    """The docker arguments that run a container as the caller on Linux, where a bind mount keeps numeric owners (a run's
    folder, and the meter folder only a key proxy writes in); none elsewhere, where the runtime maps them."""
    return ["--user", f"{os.getuid()}:{os.getgid()}"] if sys.platform.startswith("linux") else []


def keyproxy_url(run_id, name):
    """The base URL a run gives its provider calls: the key proxy of its own, by its name on the run's network."""
    r = route(name=name)
    path = r["base_path"] if "base_path" in r else r["prefix"].rstrip("/")
    return f"http://{run_names(run_id)['keys']}:{r['port']}{path}"


def docker(*args, env=None, check=True, timeout=1800):
    try:
        r = subprocess.run(["docker", *args], capture_output=True, text=True, env=env, timeout=timeout)
    except FileNotFoundError as e:
        raise ExecutorError("docker is not installed or not on PATH: evals run only in a container") from e
    if check and r.returncode != 0:
        raise ExecutorError(f"docker {' '.join(args[:2])} failed: {(r.stderr or r.stdout).strip()[-400:]}")
    return r


def repo_digests(image, env=None):
    """The repo digests docker lists for an image (["<repository>@sha256:..."]); [] when it cannot say."""
    r = docker("image", "inspect", "--format", "{{json .RepoDigests}}", image, env=env, check=False)
    try:
        found = json.loads(r.stdout.strip() or "[]") if r.returncode == 0 else []
    except ValueError:
        return []
    return [d for d in found or [] if isinstance(d, str)]


HOST_ARCHITECTURES = {"aarch64": "linux/arm64", "arm64": "linux/arm64", "x86_64": "linux/amd64", "amd64": "linux/amd64"}


HOST_INFO_TIMEOUT = 15  # seconds `docker info` has: a daemon that hangs reads as "unknown", it never stalls the runner


def asked_host_platform(env=None):
    """(answered, platform): answered is True when `docker info` ran and succeeded, platform is the host's CPU platform
    mapped to linux/arm64 or linux/amd64, or None when docker says another. A docker that fails, or does not answer
    within HOST_INFO_TIMEOUT, is (False, None): unknown, not a platform."""
    try:
        r = docker("info", "--format", "{{.Architecture}}", env=env, check=False, timeout=HOST_INFO_TIMEOUT)
    except subprocess.TimeoutExpired:
        return False, None
    if r.returncode != 0:
        return False, None
    return True, HOST_ARCHITECTURES.get(r.stdout.strip().lower())


def host_platform(env=None):
    """The CPU platform of the docker host (`docker info`, mapped to linux/arm64 or linux/amd64), or None when docker
    does not say, does not answer in time, or says another. An image of another platform than this runs emulated:
    that run is a trial."""
    return asked_host_platform(env)[1]


def ensure(env=None):
    """Build the local images that are missing, check that the published image the lock names is present, create
    the eval's networks (the run network, and an internal network per provider route where each key proxy and the
    egress proxy meet), and start the egress proxy, which joins the run network and every route network and never
    a run's own (a run's key proxy starts when a command needs it: hold()). Idempotent, and safe when several
    runners call it at once (a second create of the same name is not an error).
    Never pulls and never builds a published image: when the lock names one for this definition and platform and it
    is not present, it raises with the command to run (pull()).
    Returns the environment a record names: the definition's hash, the image, its digest, its source and its platform,
    and the docker host's own platform ("host_platform": evidence needs the two to be the same, since an emulated run is
    not the platform it says)."""
    if docker("info", "--format", "{{.ServerVersion}}", env=env, check=False).returncode != 0:
        raise ExecutorError("the docker daemon is not running: start it; evals run only in a container")
    answered, host = asked_host_platform(env)
    if not answered:
        # No run starts with an unknown host platform: the image would default to arm64, possibly emulated on an amd64
        # host, and the record could not say so.
        raise ExecutorError(f"docker did not say its platform within {HOST_INFO_TIMEOUT} seconds (`docker info` failed or "
                            "timed out): start the test again when the docker daemon answers")
    _NATIVE["platform"] = host  # a real answer, kept for image_platform()
    n, platform = names(), image_platform()
    published = published_image()
    proxies = ((n["proxy_image"], os.path.join(DEFINITION, "proxy")), (n["keys_image"], KEYPROXY))
    for image, folder in proxies + (() if published else ((n["image"], DEFINITION),)):
        if docker("image", "inspect", image, env=env, check=False).returncode != 0:
            docker("build", "-q", "--platform", platform, "-t", image, folder, env=env)
    if published:
        verify_published(published, env)
    created = [(n["network"], True)] + [(route_network(name, n), True) for name in route_names()]
    for network, internal in created:
        if docker("network", "inspect", network, env=env, check=False).returncode != 0:
            r = docker("network", "create", *(["--internal"] if internal else []), *labels(), network, env=env, check=False)
            if r.returncode != 0 and "already exists" not in r.stderr:
                raise ExecutorError(f"cannot create the eval network {network}: {r.stderr.strip()[-300:]}")
    state = docker("inspect", "--format", "{{.State.Running}}", n["proxy"], env=env, check=False)
    if state.returncode != 0 or state.stdout.strip() != "true":
        docker("rm", "-f", n["proxy"], env=env, check=False)
        r = docker("run", "-d", NO_PULL, "--restart", "unless-stopped", "--platform", platform, *CONFINED, *LOG_OPTS, *labels(),
                   "--name", n["proxy"], n["proxy_image"], env=env, check=False)
        if r.returncode != 0 and "already in use" not in r.stderr:
            raise ExecutorError(f"cannot start the eval proxy: {r.stderr.strip()[-300:]}")
        r = docker("network", "connect", n["network"], n["proxy"], env=env, check=False)
        if r.returncode != 0 and "already exists" not in r.stderr:
            raise ExecutorError(f"cannot connect the eval proxy: {r.stderr.strip()[-300:]}")
    for name in route_names():  # the networks of the key proxies, where no run is
        network = route_network(name, n)
        r = docker("network", "connect", network, n["proxy"], env=env, check=False)
        if r.returncode != 0 and "already exists" not in r.stderr:
            raise ExecutorError(f"cannot connect the eval proxy to the key proxies' network {network}: {r.stderr.strip()[-300:]}")
    if published:
        # The identity of a published image is its repo digest, the platform manifest's: the local image id differs
        # from one image store to another and is never read.
        return {"kind": "container", "definition_sha256": definition_hash(), "image": n["image"], "image_id": None,
                "image_digest": published["manifest_digest"], "image_platform": platform, "image_source": "published",
                "host_platform": host}
    image_id = docker("image", "inspect", "--format", "{{.Id}}", n["image"], env=env).stdout.strip()
    # image_digest is the id of the built image: it survives `docker save` and `docker load`, so the kept
    # archive and the image a run executed in can be told to be the same. image_id is the same value under
    # the name the records of the first round use.
    return {"kind": "container", "definition_sha256": definition_hash(), "image": n["image"], "image_id": image_id,
            "image_digest": image_id, "image_platform": platform, "image_source": "local", "host_platform": host}


def verify_published(published, env=None):
    """Raise unless the published image is present and docker lists the lock's repo digest for it. Never pulls."""
    if docker("image", "inspect", published["ref"], env=env, check=False).returncode != 0:
        raise ExecutorError(f"the published image {published['ref']} is not present on this machine: "
                            f"run `{PULL_COMMAND}` once, then start the test again (a test never pulls)")
    if published["ref"] not in repo_digests(published["ref"], env):
        raise ExecutorError(f"the image present as {published['ref']} does not list that repo digest: remove it and "
                            f"run `{PULL_COMMAND}`")


def pull(env=None):
    """Pull the published image the lock names for this definition and platform, and check its repo digest equals the
    lock's. It does not verify provenance: the script that writes a lock entry did that. Returns the image's reference,
    its digest and its platform."""
    published, platform = published_image(), image_platform()
    if published is None:
        raise ExecutorError(f"evals/image-lock.json names no published image for the definition {definition_hash()[:12]} "
                            f"on {platform}: `ensure` builds it here")
    if docker("info", "--format", "{{.ServerVersion}}", env=env, check=False).returncode != 0:
        raise ExecutorError("the docker daemon is not running: start it")
    docker("pull", "--platform", platform, published["ref"], env=env, timeout=3600)
    verify_published(published, env)
    return {"image": published["ref"], "image_digest": published["manifest_digest"], "image_platform": platform}


def hold(run_id, model, env, network="proxy", meter_dir=None, upstream=None, cafile=None, egress=True, budget=None, gate=None):
    """Start the run's own network and key proxy. model is the run's model (an id or an alias of the gate file's
    "models"); its entry gives the route, the pin, the model names the key proxy lets through and the token budget
    (budget overrides the last). network is "proxy" (the run's network is internal) or "open" (it is not). The
    key reaches the key proxy's container through the docker client's environment, never a command line; the meter
    file is <meter_dir>/<run id>.json, a folder only the key proxy mounts. upstream and cafile put a test's
    stand-in in the provider's place, reached directly (egress=False) instead of through the egress proxy; a real
    run passes none of them. Returns {"keys", "network", "route", "meter"} and, when it cannot start, raises
    ExecutorError after removing whatever it made."""
    entry = model_entry(model, gate)
    if entry is None or not entry.get("route"):
        raise ExecutorError(f"the model {model!r} has no object entry with a route in the gate file's models")
    name, r = entry["route"], route(name=entry["route"])
    names_, n, platform = run_names(run_id), names(), image_platform()
    value = ((env or {}).get(r["secret"]) or "").strip()
    if not value:
        raise ExecutorError(f"{r['secret']} has no value: the key proxy has no key to hold")
    models, pin = entry.get("upstream_models"), entry.get("provider_pin")
    budget = budget if budget is not None else entry.get("run_token_budget")
    if not (isinstance(models, list) and models and all(isinstance(m, str) and m for m in models)):
        raise ExecutorError(f"the entry of {entry['id']!r} lists no upstream_models: a key proxy serves a named model")
    if not (isinstance(budget, int) and not isinstance(budget, bool) and budget > 0):
        raise ExecutorError(f"the entry of {entry['id']!r} has no run_token_budget")
    if not meter_dir or not os.path.isdir(meter_dir):
        raise ExecutorError("hold() needs the folder the key proxy writes its meter file in")
    os.chmod(meter_dir, 0o700)  # only the caller, and on Linux the key proxy running as the caller (user()); never world-writable
    meter = os.path.join(meter_dir, f"{run_id}.json")
    try:
        created = docker("network", "create", *(["--internal"] if network == "proxy" else []), *labels(run_id),
                         names_["network"], env=env, check=False)
        if created.returncode != 0:
            why = created.stderr.strip()[-300:]
            hint = (" (docker's address pools are used up: about 31 networks fit; run fewer runs at a time, or remove "
                    "networks nothing uses)" if "pool" in why.lower() else "")
            raise ExecutorError(f"cannot create the run's network {names_['network']}: {why}{hint}")
        argv = ["run", "-d", NO_PULL, "--rm", "--init", "--platform", platform, *CONFINED, "--pids-limit", "256", *LOG_OPTS,
                *labels(run_id), *user(), "--name", names_["keys"], "--network", route_network(name, n), "-e", r["secret"]]
        if egress:
            argv += ["-e", f"HTTPS_PROXY=http://{n['proxy']}:{PROXY_PORT}"]
        if cafile:
            argv += ["-v", f"{os.path.realpath(cafile)}:/etc/keyproxy/upstream-ca.pem:ro"]
        argv += ["-v", f"{os.path.realpath(meter_dir)}:{METER_MOUNT}", n["keys_image"],
                 f"--route=/etc/keyproxy/{route_file(name)}", f"--run={run_id}", f"--model={entry['id']}",
                 f"--meter={METER_MOUNT}/{run_id}.json", f"--budget-tokens={budget}",
                 *[f"--upstream-model={m}" for m in models], *([f"--pin={pin}"] if pin else []),
                 *([f"--upstream={upstream}"] if upstream else []), *(["--cafile=/etc/keyproxy/upstream-ca.pem"] if cafile else [])]
        started = docker(*argv, env={**(env or {}), r["secret"]: value}, check=False)
        if started.returncode != 0:
            raise ExecutorError(f"cannot start the key proxy: {started.stderr.strip()[-300:]}")
        joined = docker("network", "connect", names_["network"], names_["keys"], env=env, check=False)
        if joined.returncode != 0:
            raise ExecutorError(f"cannot connect the key proxy to the run's network: {joined.stderr.strip()[-300:]}")
        deadline = time.monotonic() + KEYPROXY_READY_SECONDS
        while "keyproxy: listening" not in docker("logs", names_["keys"], env=env, check=False).stderr:
            if time.monotonic() > deadline:
                logs = docker("logs", names_["keys"], env=env, check=False)
                raise ExecutorError(f"the key proxy did not start: {(logs.stderr or logs.stdout).strip()[-300:]}")
            time.sleep(0.2)
    except BaseException:
        release(run_id, env)  # never left half made for a later call to find
        raise
    return {"keys": names_["keys"], "network": names_["network"], "route": name, "meter": meter, "model": entry["id"]}


def release(run_id, env=None):
    """Remove a run's key proxy and its network. Safe to call twice, and on a run that never started its proxy: the
    run container is removed first by the caller (a network with a container on it is not removed; it is tried again)."""
    names_ = run_names(run_id)
    # SIGTERM first: the key proxy records the answers it is still reading as unknown before it exits (a plain `rm -f`
    # kills it at once and those answers would be lost in silence). It exits at the signal; the grace is for a hung one.
    docker("stop", "-t", str(STOP_SECONDS), names_["keys"], env=env, check=False, timeout=STOP_SECONDS + 60)
    docker("rm", "-f", names_["keys"], env=env, check=False, timeout=60)
    for attempt in range(5):
        r = docker("network", "rm", names_["network"], env=env, check=False, timeout=60)
        if r.returncode == 0 or "No such network" in r.stderr or "not found" in r.stderr:
            return
        time.sleep(0.3 * (attempt + 1))


def local_server_pins(path=None):
    """{accelerator: {"image", "platforms", "source", "accessed"}} of evals/local-model-server.json: the llama.cpp server
    images, each pinned by the digest of its index, with the manifest digest of each CPU platform. A file that is not in
    its form is an error; the runner never guesses which image to trust."""
    path = path or LOCAL_SERVER_FILE
    try:
        with open(path, encoding="utf-8") as f:
            pins = json.load(f)
    except (OSError, ValueError) as e:
        raise ExecutorError(f"{path} is not readable JSON: {e}") from None
    if not (isinstance(pins, dict) and pins and set(pins) <= {"cpu", "cuda"}):
        raise ExecutorError(f"{path} must map cpu and cuda to their pinned image")
    for accelerator, pin in pins.items():
        platforms = pin.get("platforms") if isinstance(pin, dict) else None
        if not (isinstance(pin, dict) and set(pin) == {"image", "platforms", "source", "accessed"}
                and isinstance(pin["image"], str) and LOCAL_IMAGE_RE.fullmatch(pin["image"])
                and isinstance(platforms, dict) and platforms and all(
                    p in IMAGE_PLATFORMS and isinstance(d, str) and DIGEST_RE.fullmatch(d) for p, d in platforms.items())
                and isinstance(pin["source"], str) and pin["source"] and re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(pin["accessed"]))):
            raise ExecutorError(f"the entry {accelerator!r} of {path} must be exactly an image "
                                f"({LOCAL_REPOSITORY}:<tag>@sha256:<digest>), the manifest digest of each platform, a source and the access date")
    return pins


def local_server(accelerator="cpu", platform=None, pins=None):
    """{"image", "index_digest", "manifest_digest", "platform"} of the model server image for the accelerator on the
    platform the run uses. The image is named by digest: docker ignores its tag, which is there for the reader."""
    pins = local_server_pins() if pins is None else pins
    if accelerator not in pins:
        raise ExecutorError(f"no model server image is pinned for the accelerator {accelerator!r} ({', '.join(sorted(pins))} are)")
    pin, platform = pins[accelerator], platform or image_platform()
    if platform not in pin["platforms"]:
        raise ExecutorError(f"the {accelerator} model server image is pinned for {', '.join(sorted(pin['platforms']))}, not {platform}")
    return {"image": pin["image"], "index_digest": pin["image"].rsplit("@", 1)[1], "manifest_digest": pin["platforms"][platform],
            "platform": platform}


def verify_local_server(accelerator="cpu", env=None, pins=None):
    """Raise unless the pinned model server image is present and docker lists the pinned digest for it. Never pulls."""
    server = local_server(accelerator, pins=pins)
    if docker("image", "inspect", server["image"], env=env, check=False).returncode != 0:
        raise ExecutorError(f"the model server image {server['image']} is not present on this machine: run "
                            f"`python3 evals/executor.py pull-local-server{'' if accelerator == 'cpu' else ' --accelerator ' + accelerator}` "
                            "once, then start the test again (a test never pulls)")
    if f"{LOCAL_REPOSITORY}@{server['index_digest']}" not in repo_digests(server["image"], env):
        raise ExecutorError(f"the image present as {server['image']} does not list the pinned digest: remove it and run pull-local-server")
    return server


def pull_local_server(accelerator="cpu", env=None, pins=None):
    """Pull the pinned model server image for this machine's platform, by digest, and check docker lists that digest for it.
    Returns the image, its digests and the platform."""
    server = local_server(accelerator, pins=pins)
    if docker("info", "--format", "{{.ServerVersion}}", env=env, check=False).returncode != 0:
        raise ExecutorError("the docker daemon is not running: start it")
    docker("pull", "--platform", server["platform"], server["image"], env=env, timeout=3600)
    verify_local_server(accelerator, env, pins)
    return {"image": server["image"], "index_digest": server["index_digest"], "manifest_digest": server["manifest_digest"],
            "platform": server["platform"]}


def local_user():
    """The docker arguments that run a model server as an unprivileged user: the caller on Linux, where a bind mount keeps
    numeric owners, and the user "nobody" elsewhere. The weights are mounted read-only, and a server writes nothing."""
    return ["--user", f"{os.getuid()}:{os.getgid()}" if sys.platform.startswith("linux") else "65534:65534"]


def local_server_argv(run_id, spec, image, platform, weights, user_args):
    """The docker arguments (after `docker`) that start the model server of one run. spec: {"alias", "context",
    "memory_gb", "accelerator", "cpus"[, "load_timeout_seconds"]}. The server has a read-only root and a small temporary folder, no capability, no
    new privilege, a limit on processes, memory with no swap, a limit on CPUs, the log limits and the labels of the run,
    and is on the run's network and no other. It has no published port, no mount but the weights (read-only), no added host
    and no environment variable. One slot (--parallel 1): the run's model calls come one at a time. The image's health
    check answers 503 while the weights load, so the container is given a start period as long as the load limit
    (load_timeout_seconds): failures in it do not count, and the status stays `starting` until the server answers. The
    threads are the CPUs, at most LOCAL_MAX_THREADS, so that the server stays inside its process limit."""
    names_ = run_names(run_id)
    cuda = spec["accelerator"] == "cuda"
    memory = f"{spec['memory_gb']}g"
    start_period = f"{spec.get('load_timeout_seconds') or LOCAL_LOAD_DEFAULT}s"
    threads = min(spec["cpus"], LOCAL_MAX_THREADS)
    return ["run", "-d", NO_PULL, "--rm", "--init", "--platform", platform, *CONFINED, "--pids-limit", "256", "--read-only",
            "--tmpfs", "/tmp:rw,nosuid,nodev,size=256m", "--memory", memory, "--memory-swap", memory, "--cpus", str(spec["cpus"]),
            *LOG_OPTS, "--health-interval", LOCAL_HEALTH_INTERVAL, "--health-start-period", start_period, *labels(run_id), *user_args, "--name", names_["model"],
            "--network", names_["network"], "-v", f"{weights}:/models/model.gguf:ro", *(["--gpus", "all"] if cuda else []), image,
            "-m", "/models/model.gguf", "--host", "0.0.0.0", "--port", str(MODEL_PORT), "-c", str(spec["context"]),
            "--alias", spec["alias"], "--jinja", "--parallel", "1", "--threads", str(threads),
            "-ngl", "999" if cuda else "0", "--no-webui", "--no-slots", "--no-context-shift"]


def host_cpus(env=None):
    """The docker host's CPU count, asked of docker."""
    r = docker("info", "--format", "{{.NCPU}}", env=env, check=False, timeout=HOST_INFO_TIMEOUT)
    if r.returncode != 0 or not r.stdout.strip().isdigit() or int(r.stdout.strip()) < 1:
        raise ExecutorError("docker did not say how many CPUs it has: give \"cpus\" in the local models file")
    return int(r.stdout.strip())


def local_server_version(accelerator="cpu", env=None, pins=None):
    """The version line of the model server (`--version`), read once per event in a container with no network, as the
    runner's tool versions are; limited to the characters an evidence line allows."""
    server = verify_local_server(accelerator, env, pins)
    r = docker("run", "--rm", NO_PULL, "--platform", server["platform"], *CONFINED, "--pids-limit", "256", "--network", "none",
               *labels(), *local_user(), server["image"], "--version", env=env, check=False, timeout=120)
    text = (r.stderr or "") + (r.stdout or "")
    line = next((l.strip() for l in text.splitlines() if l.strip().lower().startswith("version")), "")
    line = re.sub(r"[^A-Za-z0-9 ._()/+:,-]", "?", line)[:80]
    if r.returncode != 0 or not line:
        raise ExecutorError(f"the model server did not say its version: {text.strip()[-200:]}")
    return line


def hold_local(run_id, spec, env=None, image=None):
    """Start the run's own internal network and its model server, and wait until the server is ready. spec: {"alias",
    "weights", "context", "memory_gb", "accelerator", "cpus", "load_timeout_seconds"}; image replaces the pinned image
    (a test's stand-in). The weights are mounted read-only by their real path. Readiness is the image's HEALTHCHECK
    (docker's health status `healthy`); an image with none is ready when its log says the server is listening. A server
    that exits, is unhealthy or is not ready within load_timeout_seconds fails as ExecutorError with the last 300
    characters of its log, after removing whatever was made. Returns {"model", "network", "url", "seconds"}."""
    names_, platform = run_names(run_id), image_platform()
    server = {"image": image} if image else local_server(spec["accelerator"], platform)
    weights = os.path.realpath(spec["weights"])
    if not os.path.isfile(weights):
        raise ExecutorError(f"the weights {spec['weights']} are not a file")
    timeout = spec.get("load_timeout_seconds") or LOCAL_LOAD_DEFAULT
    started = time.monotonic()
    try:
        created = docker("network", "create", "--internal", *labels(run_id), names_["network"], env=env, check=False)
        if created.returncode != 0:
            why = created.stderr.strip()[-300:]
            hint = (" (docker's address pools are used up: about 31 networks fit; run fewer runs at a time, or remove "
                    "networks nothing uses)" if "pool" in why.lower() else "")
            raise ExecutorError(f"cannot create the run's network {names_['network']}: {why}{hint}")
        argv = local_server_argv(run_id, spec, server["image"], platform, weights, local_user())
        begun = docker(*argv, env=env, check=False)
        if begun.returncode != 0:
            raise ExecutorError(f"cannot start the model server: {begun.stderr.strip()[-300:]}")
        deadline = started + timeout
        while True:
            state = docker("inspect", "--format", "{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}",
                           names_["model"], env=env, check=False)
            status, _, health = state.stdout.strip().partition(" ")
            if state.returncode != 0 or status in ("exited", "dead"):
                raise ExecutorError(f"the model server stopped before it was ready: {local_log_tail(names_['model'], env)}")
            if health == "healthy":
                break
            if health == "none" and "llama_server: listening on" in local_log_tail(names_["model"], env, 4000):
                break
            if health == "unhealthy":
                raise ExecutorError(f"the model server is unhealthy: {local_log_tail(names_['model'], env)}")
            if time.monotonic() > deadline:
                raise ExecutorError(f"the model server was not ready within {timeout} seconds (load_timeout_seconds): "
                                    f"{local_log_tail(names_['model'], env)}")
            time.sleep(LOCAL_POLL_SECONDS)
    except BaseException:
        release_local(run_id, env)  # never left half made for a later call to find
        raise
    return {"model": names_["model"], "network": names_["network"], "url": f"http://{names_['model']}:{MODEL_PORT}/v1",
            "seconds": round(time.monotonic() - started, 1)}


def local_log_tail(name, env=None, chars=300):
    """The last characters of a container's log (both streams), for an error message."""
    logs = docker("logs", name, env=env, check=False)
    return ((logs.stdout or "") + (logs.stderr or "")).strip()[-chars:]


def release_local(run_id, env=None):
    """Stop a run's model server and remove it and the run's network. Safe to call twice, and on a run whose server never
    started: the run container is removed first by the caller (a network with a container on it is not removed; it is
    tried again). The server gets STOP_SECONDS to end before it is killed."""
    names_ = run_names(run_id)
    docker("stop", "-t", str(STOP_SECONDS), names_["model"], env=env, check=False, timeout=STOP_SECONDS + 60)
    docker("rm", "-f", names_["model"], env=env, check=False, timeout=60)
    for attempt in range(5):
        r = docker("network", "rm", names_["network"], env=env, check=False, timeout=60)
        if r.returncode == 0 or "No such network" in r.stderr or "not found" in r.stderr:
            return
        time.sleep(0.3 * (attempt + 1))


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
    docker("rm", "-f", n["proxy"], env=env, check=False)
    for network in [n["network"]] + [route_network(name, n) for name in route_names()]:
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


def command(cmd, root, cwd=None, env=None, runner=None, pass_names=(), network="none", model=None, run_id=None, local=None):
    """(docker argv, container name) that runs cmd in a container. cmd, cwd and the mounts are host paths.
    runner is the adapter script cmd starts: a file, the only one of the workbench the container sees.
    model is the model the command runs (an id or alias of the gate file's list); it chooses the key proxy's route.
    The variable a key proxy holds never enters: it is given the route's placeholder, and on a network the run
    also gets its own key proxy's base URL (the caller starts that proxy first with the same run_id: held_route(),
    hold()). A held run goes on its run's own network, where only its key proxy is, and gets no proxy variable:
    it has no way to the egress proxy and so none to a provider with a credential of its own. The container is
    named after run_id (a fresh one when none is given) and labelled with it.
    local ({"context": n}) is a run of a local model (hold_local() started its server first, with the same run_id): the
    run goes on the run's own network, where only its model server is, with no proxy variable, and gets two variables,
    LOCAL_MODEL_BASE_URL and LOCAL_MODEL_CONTEXT. A command with no network stays on none."""
    if runner and not os.path.isfile(runner):
        raise ExecutorError(f"the adapter script {runner} does not exist")
    if network not in NETWORKS:
        raise ExecutorError(f"network must be one of {', '.join(NETWORKS)}")
    n, env = names(), env or {}
    pairs = mounts(root, runner)
    run_id = run_id or new_run_id()
    run = run_names(run_id)
    argv = ["docker", "run", NO_PULL, "--rm", "--init", "--platform", image_platform(), *CONFINED,
            "--pids-limit", str(PIDS_LIMIT), *labels(run_id), "--name", run["container"], "-w", translate(cwd or root, pairs),
            "-e", "ENABLE_CLAUDEAI_MCP_SERVERS=false",
            "-e", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1"]
    if sys.platform.startswith("linux"):  # a bind mount keeps numeric owners there; elsewhere the runtime maps them
        argv += [*user(), "-e", "HOME=/home/eval"]
    for host, inside, read_only in pairs:
        if os.path.exists(host):
            argv += ["-v", f"{os.path.realpath(host)}:{inside}" + (":ro" if read_only else "")]
    for key in FORWARD:
        if env.get(key):
            argv += ["-e", f"{key}={env[key]}"]
    held_by = None if local else held_route(pass_names, env, network, model)  # a local model holds no key
    kept = {r["secret"]: r["placeholder"] for r in routes().values()}  # what a key proxy holds never enters a container
    for key in dict.fromkeys(pass_names):
        if key in kept and env.get(key):
            argv += ["-e", f"{key}={kept[key]}"]  # the key stays with its key proxy
        elif env.get(key):
            argv += ["-e", key]  # the value comes from the docker client's environment
    if held_by:
        argv += ["-e", f"{route(name=held_by)['base_url_env']}={keyproxy_url(run_id, held_by)}"]
    if local and network != "none":  # the run's own network: its model server is the only host a run reaches
        argv += ["-e", f"LOCAL_MODEL_BASE_URL=http://{run['model']}:{MODEL_PORT}/v1", "-e", f"LOCAL_MODEL_CONTEXT={int(local['context'])}"]
    if network == "none":
        argv += ["--network", "none"]
    elif local:
        argv += ["--network", run["network"]]
    elif held_by:  # the run's own network: its key proxy is the only host a run reaches
        argv += ["--network", run["network"]]
    elif network == "proxy":
        proxy = f"http://{n['proxy']}:{PROXY_PORT}"
        argv += ["--network", n["network"]]
        for key in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy"):
            argv += ["-e", f"{key}={proxy}"]
        direct = "localhost,127.0.0.1"
        argv += ["-e", f"NO_PROXY={direct}", "-e", f"no_proxy={direct}"]
    return argv + [n["image"]] + [translate(a, pairs) for a in cmd], run["container"]


def run_id_of(container):
    """The run id a container name made by command() carries."""
    return container[len("wb-eval-run-"):]


def remove(name, env=None):
    """End a container by name: the docker client's process group ending does not end it."""
    docker("rm", "-f", name, env=env, check=False, timeout=60)


def meter_folder(base=None):
    """A new folder for a run's meter file, outside the run's folder: nothing else is ever put in it, and only the
    run's key proxy mounts it."""
    return tempfile.mkdtemp(prefix="wb-meter-", dir=base)


def read_meter(path):
    """The meter file a key proxy wrote, or None when there is none or it is not in its form: {"input", "output",
    "cache_read", "cache_write", "total", "responses", "unknown_responses", ...} as the key proxy wrote it."""
    try:
        with open(path, encoding="utf-8") as f:
            meter = json.load(f)
    except (OSError, ValueError):
        return None
    kinds = ("input", "output", "cache_read", "cache_write")
    ok = isinstance(meter, dict) and all(isinstance(meter.get(k), int) and not isinstance(meter.get(k), bool) and meter[k] >= 0 for k in kinds)
    return meter if ok and isinstance(meter.get("unknown_responses"), int) else None


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv == ["ensure"]:
        print(json.dumps(ensure(), indent=2))
    elif argv == ["pull"]:
        print(json.dumps(pull(), indent=2))
    elif argv[:1] == ["pull-local-server"] and (len(argv) == 1 or (len(argv) == 3 and argv[1] == "--accelerator" and argv[2] in ("cpu", "cuda"))):
        print(json.dumps(pull_local_server(argv[2] if len(argv) == 3 else "cpu"), indent=2))
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
