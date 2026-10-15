"""The project-script runner in real containers (providers/script/container.py with the image of providers/script/Dockerfile): what a
script can and cannot do (read an environment credential, write outside its scratch folder, see a host path, reach a network), the
egress proxy on a real INTERNAL network (a declared name is served; an undeclared name is refused by name, an IP literal by address;
an undeclared name cannot be resolved from the script's container at all), the limits, the forged stream, and the clean-up.

Opt in: these tests need a local docker daemon and the image of the current definition (built once, as `build --confirmed` does: a
network step to the Debian snapshot archive; a few minutes the first time). They run only with

    WB_SCRIPT_DOCKER_TESTS=1 uv run --with pytest==9.1.1 pytest providers/script/tests/test_script_docker.py

The stand-in remote services are two containers of the same image on a test network, reached only through the proxy; no real host is
called. Everything the tests start carries the label org.openhora.script.test (the runner's own objects carry org.openhora.script, and
are removed by the runner); the image is the provider's own tag. The containers of the eval harness are never looked at.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import textwrap
import uuid
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("WB_SCRIPT_DOCKER_TESTS") != "1",
                                reason="real containers: set WB_SCRIPT_DOCKER_TESTS=1 (builds the script image once)")

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("script_container_docker_test", HERE.parent / "container.py")
host = importlib.util.module_from_spec(spec)
sys.modules["script_container_docker_test"] = host
spec.loader.exec_module(host)
box = host.box
TEST_LABEL = "org.openhora.script.test=1"

SERVER = textwrap.dedent('''
    import socket, sys
    word = sys.argv[1].encode()
    s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); s.bind(("0.0.0.0", 8080)); s.listen(8)
    while True:
        c, _ = s.accept()
        c.recv(4096)
        c.sendall(b"HTTP/1.0 200 OK\\r\\n\\r\\n" + word)
        c.close()
''')


@pytest.fixture(autouse=True)
def one_docker_test_at_a_time():
    """The tests count what a run leaves behind in the daemon, so two of them never run together, whatever the number of workers."""
    import fcntl
    import tempfile
    with open(os.path.join(tempfile.gettempdir(), "openhora-script-docker-tests.lock"), "w") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def docker(*args, check=True):
    done = box.docker(list(args), timeout=120)
    if check and done.returncode != 0:
        raise AssertionError(f"docker {' '.join(args[:3])} failed: {done.stderr.strip()[:300]}")
    return done


@pytest.fixture(scope="module")
def image():
    host.local_daemon()
    try:
        return host.image_id(host.image_tag())
    except host.ProviderError:
        assert host.cmd_build({"--confirmed": True}) == 0
        return host.image_id(host.image_tag())


@pytest.fixture(scope="module")
def remote(image):
    """A test network with two stand-in remote services on it, aliased allowed.test and other.test: {network, allowed, other} (the
    addresses of the services). Removed at the end."""
    token = uuid.uuid4().hex[:8]
    network = f"openhora-script-test-{token}"
    docker("network", "create", "--label", TEST_LABEL, network)
    names, ips = [], {}
    try:
        for alias, word in (("allowed.test", "hello-allowed"), ("other.test", "hello-other")):
            name = f"openhora-script-test-{alias.split('.')[0]}-{token}"
            docker("run", "-d", "--rm", "--init", "--pull", "never", "--name", name, "--label", TEST_LABEL, "--network", network,
                   "--network-alias", alias, "--read-only", "--cap-drop", "ALL", image, "python3", "-I", "-c", SERVER, word)
            names.append(name)
            ips[alias] = docker("inspect", "-f", '{{(index .NetworkSettings.Networks "%s").IPAddress}}' % network, name).stdout.strip()
        yield {"network": network, "allowed": ips["allowed.test"], "other": ips["other.test"]}
    finally:
        for name in names:
            box.remove(name)
        docker("network", "rm", network, check=False)


class Runner:
    def __init__(self, tmp_path, image, remote):
        self.tmp, self.image, self.remote = tmp_path, image, remote
        self.count = 0

    def run(self, body: str, destinations=(), timeout=60, allow_private=True, kind="py", **kwargs):
        """Run a script; returns (the provider's answer, the text of result.txt)."""
        self.count += 1
        folder = self.tmp / f"run{self.count}"
        folder.mkdir()
        script = folder / "script"
        script.write_text(textwrap.dedent(body))
        script.chmod(0o444)
        out = folder / "out"
        out.mkdir(mode=0o700)
        done = host.run_script(str(script), kind, str(out), destinations=list(destinations), timeout=timeout, base=self.image,
                               allow_private=allow_private, egress_network=self.remote["network"] if destinations else None, **kwargs)
        result = out / "result.txt"
        return done, result.read_text() if result.exists() else None


@pytest.fixture
def runner(tmp_path, image, remote):
    yield Runner(tmp_path, image, remote)
    leftovers = docker("ps", "-a", "--filter", "name=openhora-script-run-", "--filter", "name=openhora-script-proxy-",
                       "--filter", "name=openhora-script-build-", "--format", "{{.Names}}").stdout.split()
    networks = [n for n in docker("network", "ls", "--format", "{{.Name}}").stdout.split()
                if n.startswith("openhora-script-in-") or n.startswith("openhora-script-out-")]
    assert leftovers == [] and networks == [], (leftovers, networks)         # a run leaves nothing behind


def test_a_script_runs_and_its_result_and_account_come_back(runner):
    done, text = runner.run("import os\nopen(os.environ['OUTPUT_DIR'] + '/result.txt', 'w').write('hello')\nprint('log line')\n")
    assert text == "hello" and done["exit"] == 0 and done["signal"] is None and done["results"] == ["result.txt"] and done["refused"] == []
    assert sorted(done["outputs"]) == ["info.json", "result.txt"]


def test_a_shell_script_runs_in_the_same_container(runner):
    done, text = runner.run('printf "from bash" > "$OUTPUT_DIR/result.txt"\n', kind="sh")
    assert text == "from bash" and done["exit"] == 0


def test_no_credential_of_the_calling_environment_is_inside_the_container(runner, monkeypatch):
    for name in ("OPENAI_API_KEY", "NOTION_TOKEN", "ANTHROPIC_API_KEY", "AWS_SECRET_ACCESS_KEY", "GITHUB_TOKEN"):
        monkeypatch.setenv(name, "planted-" + uuid.uuid4().hex)
    done, text = runner.run('''
        import json, os
        seen = {"environ": sorted(os.environ)}
        for path in ("/proc/self/environ", "/proc/1/environ"):
            try:
                seen[path] = sorted(p.split("=")[0] for p in open(path).read().split("\\0") if p)
            except OSError as e:
                seen[path] = str(e)
        open(os.environ["OUTPUT_DIR"] + "/result.txt", "w").write(json.dumps(seen))
    ''')
    seen = json.loads(text)
    everything = json.dumps(seen)
    for name in ("OPENAI_API_KEY", "NOTION_TOKEN", "ANTHROPIC_API_KEY", "AWS_SECRET_ACCESS_KEY", "GITHUB_TOKEN", "planted"):
        assert name not in everything
    assert set(seen["environ"]) <= {"PATH", "HOME", "LANG", "PYTHONDONTWRITEBYTECODE", "OUTPUT_DIR"}
    assert set(seen["/proc/1/environ"]) <= {"PATH", "HOSTNAME", "HOME", "LANG", "PYTHONDONTWRITEBYTECODE", "container"}


def test_the_root_is_read_only_the_user_is_not_root_and_no_capability_is_held(runner):
    done, text = runner.run('''
        import json, os
        tried = {}
        for path in ("/etc/x", "/usr/x", "/opt/script/x", "/deps/x", "/in/x", "/in/script", "/x", "/proc/sys/kernel/hostname"):
            try:
                open(path, "w").write("1")
                tried[path] = "written"
            except OSError as e:
                tried[path] = e.__class__.__name__
        exe = "/scratch/prog"
        open(exe, "w").write("#!/bin/sh\\necho hi\\n"); os.chmod(exe, 0o755)
        try:
            os.execv(exe, [exe]); ran = True
        except OSError as e:
            ran = e.__class__.__name__
        status = dict(line.split(":\\t") for line in open("/proc/self/status").read().splitlines() if ":\\t" in line)
        open(os.environ["OUTPUT_DIR"] + "/result.txt", "w").write(json.dumps({"tried": tried, "exec": ran, "uid": os.getuid(),
              "capeff": status["CapEff"].strip(), "nonewprivs": status["NoNewPrivs"].strip(), "tmp": open("/tmp/ok", "w").write("1")}))
    ''')
    seen = json.loads(text)
    assert all(v != "written" for v in seen["tried"].values()), seen["tried"]
    assert seen["exec"] == "PermissionError" and seen["uid"] != 0 and int(seen["capeff"], 16) == 0 and seen["nonewprivs"] == "1"


def test_only_the_script_is_mounted_and_nothing_else_of_the_host_is_visible(runner, tmp_path):
    done, text = runner.run('''
        import json, os
        mounts = [line.split() for line in open("/proc/self/mountinfo").read().splitlines()]
        binds = [m[4] for m in mounts if m[4].startswith("/in") or m[4].startswith("/host") or m[4].startswith("/Users") or m[4].startswith("/home")]
        open(os.environ["OUTPUT_DIR"] + "/result.txt", "w").write(json.dumps({
            "in": sorted(os.listdir("/in")), "binds": binds, "users": os.path.exists("/Users"), "home": os.path.exists("/home/" + str(os.getuid())),
            "deps": sorted(os.listdir("/deps")), "root": sorted(os.listdir("/")), "mnt": sorted(os.listdir("/mnt"))}))
    ''')
    seen = json.loads(text)
    assert seen["in"] == ["script"] and seen["binds"] == ["/in/script"] and not seen["users"] and seen["deps"] == [] and seen["mnt"] == []
    assert not {"Users", "host_mnt", "host", "Volumes"} & set(seen["root"])


def test_with_no_destination_there_is_no_network_at_all(runner):
    done, text = runner.run('''
        import json, os, socket
        out = {"eth0": any(l.split(":")[0].strip() == "eth0" for l in open("/proc/net/dev").read().splitlines()[2:]),
               "routes": len(open("/proc/net/route").read().splitlines()) - 1}
        for label, target in (("direct", ("1.1.1.1", 443)), ("lookup", None)):
            try:
                if target:
                    socket.create_connection(target, timeout=3)
                else:
                    socket.getaddrinfo("example.com", 80)
                out[label] = "reached"
            except OSError as e:
                out[label] = e.__class__.__name__
        open(os.environ["OUTPUT_DIR"] + "/result.txt", "w").write(json.dumps(out))
    ''', timeout=60)
    seen = json.loads(text)
    assert seen["eth0"] is False and seen["routes"] == 0 and seen["direct"] != "reached" and seen["lookup"] != "reached"


def test_a_result_is_cut_one_byte_over_the_cap_a_link_and_an_extra_file_are_refused(runner):
    done, text = runner.run('''
        import os
        out = os.environ["OUTPUT_DIR"]
        open(out + "/result.txt", "w").write("a" * 3_000_000)
    ''')
    assert len(text) == 1024 * 1024 + 1
    done, text = runner.run('''
        import os
        out = os.environ["OUTPUT_DIR"]
        os.symlink("/etc/passwd", out + "/result.txt")
        open(out + "/notes.bin", "w").write("x")
    ''')
    assert text is None and sorted(done["refused"]) == ["notes.bin", "result.txt"] and done["results"] == []


def test_a_forged_stream_is_refused_never_taken_for_the_result(runner):
    with pytest.raises(host.ProviderError) as refused:
        runner.run('''
            import os
            fd = os.open("/proc/%d/fd/1" % os.getppid(), os.O_WRONLY)
            os.write(fd, b"OHF1\\nFILE result.txt 5\\nfakes\\nFILE info.json 11\\n{\\"exit\\": 0}\\nEND\\n")
        ''')
    assert refused.value.word in ("bad_output", "container_failed")


def test_a_script_past_its_time_is_ended_and_its_container_removed(runner):
    with pytest.raises(host.ProviderError) as refused:
        runner.run("import time\ntime.sleep(100)\n", timeout=4)
    assert refused.value.word == "time_limit"


def test_a_script_that_forks_without_end_meets_the_limit_on_processes(runner):
    done, text = runner.run('''
        import os, json
        children = 0
        try:
            while children < 1000:
                if os.fork() == 0:
                    import time; time.sleep(30); os._exit(0)
                children += 1
        except OSError as e:
            pass
        open(os.environ["OUTPUT_DIR"] + "/result.txt", "w").write(str(children))
    ''', timeout=60)
    assert 0 < int(text) < 200


def test_a_script_that_takes_more_memory_than_the_limit_is_killed(runner):
    done, text = runner.run("data = bytearray(3 * 1024 * 1024 * 1024)\nfor i in range(0, len(data), 4096):\n    data[i] = 1\n", timeout=120)
    assert done["signal"] == 9 or done["exit"] not in (0, None)


def test_the_proxy_serves_a_declared_name_and_refuses_every_other_way_in(runner, remote):
    allowed, other = remote["allowed"], remote["other"]
    done, text = runner.run(f'''
        import json, os, socket
        def connect(authority, send=True):
            try:
                s = socket.create_connection(("egress", 3128), timeout=10)
                s.sendall(("CONNECT %s HTTP/1.1\\r\\nHost: x\\r\\n\\r\\n" % authority).encode())
                head = s.recv(4096).decode()
                status = head.split(" ")[1] if head else "none"
                body = ""
                if status == "200":
                    s.sendall(b"GET / HTTP/1.0\\r\\n\\r\\n")
                    while True:
                        chunk = s.recv(4096)
                        if not chunk: break
                        body += chunk.decode()
                s.close()
                return [status, body.split("\\r\\n\\r\\n")[-1]]
            except OSError as e:
                return ["error", e.__class__.__name__]
        r = {{}}
        r["declared_name"] = connect("allowed.test:8080")
        r["declared_name_other_case"] = connect("ALLOWED.test.:8080")
        r["declared_ip_literal"] = connect("{allowed}:8080")
        r["undeclared_name"] = connect("other.test:8080")
        r["other_ip_literal"] = connect("{other}:8080")
        r["wrong_port"] = connect("allowed.test:9090")
        r["loopback"] = connect("127.0.0.1:8080")
        r["metadata"] = connect("169.254.169.254:80")
        r["decimal"] = connect("2130706433:8080")
        r["hex"] = connect("0x7f000001:8080")
        r["ipv6"] = connect("[::1]:8080")
        r["external_name"] = connect("example.com:443")
        open(os.environ["OUTPUT_DIR"] + "/result.txt", "w").write(json.dumps(r))
    ''', destinations=["allowed.test:8080"])
    seen = json.loads(text)
    assert seen["declared_name"] == ["200", "hello-allowed"] and seen["declared_name_other_case"] == ["200", "hello-allowed"]
    assert seen["declared_ip_literal"] == ["200", "hello-allowed"]
    for refused in ("undeclared_name", "other_ip_literal", "wrong_port", "loopback", "metadata", "decimal", "hex", "ipv6", "external_name"):
        assert seen[refused][0] == "403", (refused, seen[refused])


def test_an_undeclared_name_cannot_be_resolved_from_the_script_container_and_there_is_no_way_out_but_the_proxy(runner, remote):
    done, text = runner.run(f'''
        import json, os, socket
        r = {{}}
        for name in ("other.test", "allowed.test", "example.com", "nonexistent-name.invalid", "pypi.org"):
            try:
                r[name] = "resolved: " + socket.getaddrinfo(name, 80)[0][4][0]
            except OSError as e:
                r[name] = "unresolvable"
        r["proxy"] = socket.getaddrinfo("egress", 3128)[0][4][0] != ""
        for label, target in (("direct_allowed", ("{remote['allowed']}", 8080)), ("direct_other", ("{remote['other']}", 8080)),
                              ("direct_internet", ("1.1.1.1", 443))):
            try:
                socket.create_connection(target, timeout=4)
                r[label] = "reached"
            except OSError as e:
                r[label] = "blocked"
        r["default_route"] = any(line.split()[1] == "00000000" for line in open("/proc/net/route").read().splitlines()[1:])
        r["eth0"] = any(l.split(":")[0].strip() == "eth0" for l in open("/proc/net/dev").read().splitlines()[2:])
        r["routes"] = len(open("/proc/net/route").read().splitlines()) - 1
        open(os.environ["OUTPUT_DIR"] + "/result.txt", "w").write(json.dumps(r))
    ''', destinations=["allowed.test:8080"])
    seen = json.loads(text)
    for name in ("other.test", "allowed.test", "example.com", "nonexistent-name.invalid", "pypi.org"):
        assert seen[name] == "unresolvable", (name, seen[name])
    assert seen["proxy"] is True and seen["direct_allowed"] == seen["direct_other"] == seen["direct_internet"] == "blocked"
    assert seen["default_route"] is False and seen["eth0"] is True and seen["routes"] == 1       # the step's subnet, and no way beyond it


PROBE = textwrap.dedent("""
    import json, re, socket, time
    text = open("/proc/net/fib_trie").read().split("Local:")[0]
    own = [m for m in re.findall(r"\\|-- (\\d+\\.\\d+\\.\\d+\\.\\d+)\\n\\s+/32 host LOCAL", text) if not m.startswith("127.")]
    proxy = socket.getaddrinfo("egress", 3128)[0][4][0]
    subnet = own[0].rsplit(".", 1)[0]
    answers = {}
    for last in ("1", "2", "3", "4", "254"):
        host = subnet + "." + last
        if host in own or host == proxy:
            continue
        for port in (22, 53, 80, 443, 2375, 3128, 8080):
            s = socket.socket(); s.settimeout(4)
            try:
                s.connect((host, port)); answers[f"{host}:{port}"] = "connected"
            except Exception as e:
                answers[f"{host}:{port}"] = e.__class__.__name__ + " " + str(e.args[0] if e.args else "")
    neighbours = [l.split()[0] for l in open("/proc/net/arp").read().splitlines()[1:] if l.split()[3] != "00:00:00:00:00:00"]
    print(json.dumps({"own": own, "proxy": proxy, "answers": answers, "neighbours": neighbours}))
""")


def test_the_host_has_no_address_on_the_step_network_and_nothing_but_the_proxy_answers(image, remote):
    """Review finding B1: on a plain internal bridge the host's gateway address answers (ARP, then resets from its stack on any port), which
    reaches every service the host listens on without the proxy. The step's network is created with the isolated gateway mode."""
    with host.Egress(["allowed.test:8080"], token=host.new_token(), image=image, timeout=60, allow_private=True,
                     egress_network=remote["network"]) as egress:
        config = json.loads(docker("network", "inspect", "--format", "{{json .IPAM.Config}}", egress.network).stdout)
        assert config and all("Gateway" not in entry for entry in config), config
        options = json.loads(docker("network", "inspect", "--format", "{{json .Options}}", egress.network).stdout)
        assert options["com.docker.network.bridge.gateway_mode_ipv4"] == "isolated"
        seen = json.loads(docker("run", "--rm", "--pull", "never", "--network", egress.network, "--label", TEST_LABEL, image,
                                 "python3", "-I", "-c", PROBE).stdout)
    assert seen["answers"], "something was probed"
    for where, answer in seen["answers"].items():
        assert not answer.startswith("connected") and "refused" not in answer.lower() and "reset" not in answer.lower(), (where, answer)
    assert seen["neighbours"] in ([], [seen["proxy"]]), seen["neighbours"]      # the only address that ever answered is the proxy's


def test_a_run_on_a_network_without_the_isolation_is_refused_before_anything_starts(runner, monkeypatch):
    monkeypatch.setattr(host, "internal_network_args", lambda name, labels: ["network", "create", "--driver", "bridge", "--internal", *labels, name])
    with pytest.raises(host.ProviderError) as refused:
        runner.run("print(1)\n", destinations=["allowed.test:8080"])
    assert refused.value.word == "network_not_internal"


def test_a_declared_name_that_is_not_a_public_address_is_refused_before_the_script_starts(runner):
    with pytest.raises(host.ProviderError) as refused:
        runner.run("print(1)\n", destinations=["allowed.test:8080"], allow_private=False)
    assert refused.value.word == "destination_not_public"


def test_a_declared_name_that_does_not_resolve_is_refused_before_the_script_starts(runner):
    with pytest.raises(host.ProviderError) as refused:
        runner.run("print(1)\n", destinations=["no-such-service.test:443"])
    assert refused.value.word == "destination_unresolvable"


def test_the_build_container_runs_with_no_mount_gets_the_lock_on_standard_input_and_keeps_nothing_when_it_fails(image, remote, tmp_path):
    lock = "idna==3.7 --hash=sha256:" + "a" * 64 + "\n"
    import hashlib
    with pytest.raises(host.ProviderError) as refused:
        host.build_deps(lock.encode(), hashlib.sha256(lock.encode()).hexdigest(), timeout=90, index_url="http://allowed.test:8080/simple",
                        index_hosts=["allowed.test:8080"], allow_private=True, egress_network=remote["network"], base=image)
    assert refused.value.word == "build_failed"
    tag = host.deps_tag(hashlib.sha256(lock.encode()).hexdigest())
    assert box.docker(["image", "inspect", tag]).returncode != 0                 # nothing was kept
    assert docker("ps", "-a", "--filter", "name=openhora-script-build-", "--format", "{{.Names}}").stdout.split() == []


def test_the_image_kept_from_a_build_carries_nothing_the_build_container_was_given(image):
    """The commit of a build container keeps its configuration too: the proxy variables, the user, the labels. commit_args puts them back."""
    import hashlib
    sha = hashlib.sha256(b"a lock").hexdigest()
    name, tag = "openhora-script-test-commit-" + uuid.uuid4().hex[:8], "openhora-script-test-commit:" + uuid.uuid4().hex[:8]
    docker("run", "--name", name, "--label", TEST_LABEL, "--label", "org.openhora.script=1", "--label", "org.openhora.script.deadline=5",
           "--user", "4321:4321", "-e", "HTTPS_PROXY=http://egress:3128", "-e", "SCRIPT_DESTINATIONS=a.example:443", "--pull", "never",
           image, "python3", "-I", "-c", "open('/deps/marker', 'w').write('built')")
    try:
        docker(*host.commit_args(sha, name, tag))
        config = json.loads(docker("image", "inspect", "--format", "{{json .Config}}", tag).stdout)
        env = " ".join(config["Env"] or [])
        assert "egress" not in env and "a.example" not in env      # the names stay, set to nothing; _inner.py passes on only a name with a value
        assert config["User"] == "65534:65534" and config["Labels"]["org.openhora.script.lock"] == sha
        assert config["Labels"]["org.openhora.script"] == "" and config["Labels"]["org.openhora.script.deadline"] == ""
        image_id = docker("image", "inspect", "--format", "{{.Id}}", tag).stdout.strip()
        assert host.deps_image(image_id, sha) == image_id
        with pytest.raises(host.ProviderError):                       # not for another lock file
            host.deps_image(image_id, "f" * 64)
        # a run from it sees the built file read-only, and no proxy variable
        done = docker("run", "--rm", "--read-only", "--pull", "never", tag, "python3", "-I", "-c",
                      "import os; print(open('/deps/marker').read(), sorted(k for k, v in os.environ.items() if v and ('PROXY' in k.upper() or 'DESTINATIONS' in k)))")
        assert done.stdout.strip() == "built []"
    finally:
        box.remove(name)
        docker("image", "rm", "-f", tag, check=False)


def test_a_lock_that_is_not_a_lock_never_starts_a_container(image):
    with pytest.raises(host.ProviderError) as refused:
        host.build_deps(b"requests>=2\n", __import__("hashlib").sha256(b"requests>=2\n").hexdigest(), base=image)
    assert refused.value.word == "bad_lock"


def test_what_a_killed_run_leaves_is_reaped_from_its_labels(image):
    token = uuid.uuid4().hex[:8]
    name, network = f"openhora-script-test-reap-{token}", f"openhora-script-test-reapnet-{token}"
    docker("network", "create", "--label", "org.openhora.script=1", "--label", "org.openhora.script.deadline=1", network)
    docker("create", "--name", name, "--label", "org.openhora.script=1", "--label", "org.openhora.script.deadline=1", image, "true")
    try:
        gone = host.reap_all()
        assert docker("ps", "-a", "--filter", f"name={name}", "--format", "{{.Names}}").stdout.split() == []
        assert network not in docker("network", "ls", "--format", "{{.Name}}").stdout.split()
        assert gone["containers"] and gone["networks"]
    finally:
        box.remove(name)
        docker("network", "rm", network, check=False)


def test_the_provider_answers_check_and_the_run_verb_through_its_command_line(image, tmp_path, capsys):
    assert host.main(["--check"]) == 0
    assert json.loads(capsys.readouterr().out)["image"] == image
    script = tmp_path / "s.py"
    script.write_text("import os\nopen(os.environ['OUTPUT_DIR'] + '/result.md', 'w').write('# via the verb')\n")
    script.chmod(0o444)
    out = tmp_path / "out"
    out.mkdir(mode=0o700)
    assert host.main(["run", "--script", str(script), "--kind", "py", "--out-dir", str(out), "--timeout", "60"]) == 0
    answer = json.loads(capsys.readouterr().out)
    assert answer["exit"] == 0 and (out / "result.md").read_text() == "# via the verb"
