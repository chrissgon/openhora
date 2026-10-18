"""Offline tests of providers/messenger/whatsapp-cloud.py as a program: the verbs, the secrets, the settings and `setup`,
`whoami`, the state folder, and a real process (the protocol on a copy of fd 1, nothing private on any stream, the exit within
5 seconds of the end of stdin or SIGTERM). The Graph API is a fake opener; the only socket is the provider's own on 127.0.0.1.

Every test points OPENHORA_STATE_DIR at a temporary folder. Run: uv run --with pytest pytest providers/messenger/tests/test_whatsapp_cloud.py
"""
from __future__ import annotations

import argparse
import http.client
import importlib.util
import json
import os
import re
import signal
import socket
import stat
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

import whatsapp_cloud_kit as kit
from whatsapp_cloud_kit import APP_SECRET, BSUID, PATH, PERSON, PHONE_ID, TEXT, TOKEN, VERIFY, envelope, text_message, wc

REPO = Path(__file__).resolve().parents[3]


@pytest.fixture
def home(tmp_path, monkeypatch):
    state = tmp_path / "state"
    monkeypatch.setenv("OPENHORA_STATE_DIR", str(state))
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    for name in (wc.SECRET_TOKEN, wc.SECRET_APP, wc.SECRET_VERIFY):
        monkeypatch.delenv(name, raising=False)
    old = os.umask(0o077)
    yield state
    os.umask(old)


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# --- the verbs ----------------------------------------------------------------------------------------------------------------


def test_capabilities_are_the_documented_ones_and_the_resolver_finds_the_script_by_its_platform_line():
    assert wc.CAPABILITIES == {"max_text": 4096, "buttons": True, "max_buttons": 3, "max_button_label": 20, "lists": False,
                               "max_list_rows": 0, "url_buttons": False, "reply_context": True, "documents": True, "listen": True,
                               "attachments": True, "max_attachment_bytes": 104857600}
    assert wc.PLATFORMS == ("whatsapp-cloud",) and kit.SCRIPT.name == "whatsapp-cloud.py"
    done = subprocess.run([sys.executable, str(kit.SCRIPT), "capabilities", "--platform", "whatsapp-cloud"], capture_output=True, text=True)
    assert json.loads(done.stdout) == wc.CAPABILITIES and done.returncode == 0
    spec = importlib.util.spec_from_file_location("resolve_for_whatsapp_cloud", REPO / "providers" / "resolve.py")
    resolve = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = resolve
    spec.loader.exec_module(resolve)
    got = resolve.resolve("messenger:whatsapp-cloud", env={})
    assert got["implementation"] == "whatsapp-cloud" and got["path"] == str(kit.SCRIPT)
    assert resolve.variables("messenger:whatsapp-cloud") == ["MESSENGER_WHATSAPP_CLOUD_PROVIDER", "MESSENGER_PROVIDER"]


@pytest.mark.parametrize("verb", ["receive", "send", "ack"])
def test_the_one_shot_verbs_exit_2_with_the_listen_only_sentence(verb, capsys):
    assert wc.main([verb, "--platform", "whatsapp-cloud"]) == 2
    assert "listen mode" in capsys.readouterr().err


def test_a_platform_other_than_whatsapp_cloud_is_a_usage_error():
    with pytest.raises(SystemExit) as e:
        wc.main(["capabilities", "--platform", "whatsapp"])
    assert e.value.code == 2


def test_main_sets_umask_077(home):
    os.umask(0o022)
    wc.main(["capabilities"])
    assert os.umask(0o077) == 0o077


# --- the secrets ----------------------------------------------------------------------------------------------------------------


class Resolver:
    def __init__(self, values):
        self.values = values

    def resolve(self, name):
        return (self.values[name], "environment") if name in self.values else None


def test_the_three_secrets_are_read_through_the_resolver_with_the_repositorys_names():
    assert (wc.SECRET_TOKEN, wc.SECRET_APP, wc.SECRET_VERIFY) == ("MESSENGER_WHATSAPP_CLOUD_TOKEN", "MESSENGER_WHATSAPP_CLOUD_APP_SECRET",
                                                                   "MESSENGER_WHATSAPP_CLOUD_VERIFY_TOKEN")
    assert list(wc.KEYRING_USERNAMES.values()) == ["messenger-whatsapp-cloud", "messenger-whatsapp-cloud-app-secret",
                                                   "messenger-whatsapp-cloud-verify-token"]
    assert list(wc.KEYRING_USERNAMES) == [wc.SECRET_TOKEN, wc.SECRET_APP, wc.SECRET_VERIFY]
    registry = wc.secret_resolver().REGISTRY
    for name, username in wc.KEYRING_USERNAMES.items():
        assert registry[name].store_username == username and registry[name].readers == ("providers/messenger/whatsapp-cloud.py",)
    assert wc.load_secrets(resolver=Resolver(kit.SECRETS)) == kit.SECRETS


def test_a_missing_or_malformed_secret_is_not_configured_and_names_the_secret_and_never_a_value():
    for values in ({}, {wc.SECRET_TOKEN: TOKEN}, {**kit.SECRETS, wc.SECRET_APP: "has a space"}, {**kit.SECRETS, wc.SECRET_VERIFY: ""}):
        with pytest.raises(wc.ProviderError) as e:
            wc.load_secrets(resolver=Resolver(values))
        assert e.value.kind == "not-configured" and e.value.code == 3 and "keyring set openhora messenger-whatsapp-cloud" in str(e.value)
        assert TOKEN not in str(e.value) and APP_SECRET not in str(e.value)


def test_listen_without_the_secrets_or_the_settings_writes_not_configured_and_exits_3(home, capsys, monkeypatch):
    monkeypatch.setattr(wc, "secret_resolver", lambda: Resolver({}))
    assert wc.main(["listen"]) == 3            # no settings yet
    first = json.loads(capsys.readouterr().out)
    assert first["event"] == "error" and first["kind"] == "not-configured" and "setup" in first["reason"]
    wc.write_private_json(str(wc.own_folder()) + "/" + wc.SETTINGS, kit.settings(port=8787))
    assert wc.main(["listen"]) == 3            # settings, no secrets
    second = json.loads(capsys.readouterr().out)
    assert second["kind"] == "not-configured" and "MESSENGER_WHATSAPP_CLOUD_TOKEN" in second["reason"]


# --- the state folder -----------------------------------------------------------------------------------------------------------


def runtime_ledger():
    path = Path(*REPO.parts, "runtime", "messaging" + "_ledger.py")
    spec = importlib.util.spec_from_file_location("ledger_for_whatsapp_cloud_parity", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("env", [
    {"OPENHORA_STATE_DIR": "{tmp}/chosen"}, {"OPENHORA_STATE_DIR": "{tmp}/rel/../chosen"}, {"XDG_STATE_HOME": "{tmp}/xdg"},
    {"XDG_STATE_HOME": "relative/xdg"}, {"OPENHORA_STATE_DIR": "{tmp}/first", "XDG_STATE_HOME": "{tmp}/xdg"}, {},
])
def test_the_state_folder_rule_is_the_bridges_rule(tmp_path, monkeypatch, env):
    for name in ("OPENHORA_STATE_DIR", "XDG_STATE_HOME"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value.format(tmp=tmp_path))
    ledger = runtime_ledger()
    assert wc.state_dir() == ledger.state_dir() and ledger.STATE_ENV == wc.STATE_ENV
    assert ledger.LOCK.format(platform="whatsapp-cloud") == wc.LOCK.format(platform="whatsapp-cloud")


def test_the_folder_is_made_0700_and_a_folder_open_to_others_or_a_link_is_refused(home):
    own = wc.own_folder()
    assert own == str(home / "whatsapp-cloud") and stat.S_IMODE(os.lstat(own).st_mode) == 0o700
    os.chmod(own, 0o750)
    with pytest.raises(wc.ProviderError) as e:
        wc.own_folder()
    assert e.value.kind == "not-configured" and "chmod 700" in str(e.value)
    os.chmod(own, 0o700)
    os.rmdir(own)
    elsewhere = home.parent / "elsewhere"
    elsewhere.mkdir(mode=0o700)
    os.symlink(elsewhere, own)
    with pytest.raises(wc.ProviderError) as e:
        wc.own_folder()
    assert "not a real directory" in str(e.value)


# --- setup ------------------------------------------------------------------------------------------------------------------------


def run_setup(*argv):
    args = wc.build_parser().parse_args(["setup", *argv])
    return wc.cmd_setup(args)


def test_setup_writes_the_settings_0600_prints_the_callback_url_and_the_funnel_command(home, capsys, monkeypatch):
    monkeypatch.setattr(wc, "funnel_host", lambda: "northwind-laptop.tail1234.ts.net")
    assert run_setup("--phone-number-id", PHONE_ID, "--template", "decisions_waiting", "--template-language", "pt_BR", "--port", "8800") == 0
    shown = capsys.readouterr().out
    path = home / "whatsapp-cloud" / "settings.json"
    saved = json.loads(path.read_text())
    assert stat.S_IMODE(path.stat().st_mode) == 0o600 and stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert set(saved) == {"phone_number_id", "port", "template", "template_language", "webhook_path", "public_base"}   # MSG-11: the address given to setup is kept
    assert saved["port"] == 8800 and saved["template"] == "decisions_waiting" and re.fullmatch(r"[0-9a-f]{32}", saved["webhook_path"])
    p = saved["webhook_path"]
    assert f"https://northwind-laptop.tail1234.ts.net/{p}" in shown
    assert f"tailscale funnel --bg --https=443 --set-path=/{p} http://127.0.0.1:8800/{p}" in shown
    assert "MagicDNS" in shown and "funnel attribute" in shown and "messages" in shown and wc.SECRET_VERIFY in shown
    for secret in (TOKEN, APP_SECRET, VERIFY):
        assert secret not in shown
    assert wc.check_settings(saved) == saved


def test_setup_keeps_the_path_unless_asked_and_keeps_earlier_values_and_keeps_the_public_address(home, capsys, monkeypatch):
    monkeypatch.setattr(wc, "funnel_host", lambda: None)
    url = ["--public-url", "https://northwind-shop.example"]       # MSG-11: the first run gives the address
    run_setup("--phone-number-id", PHONE_ID, "--template", "decisions_waiting", "--template-language", "en_US", *url)
    first = json.loads((home / "whatsapp-cloud" / "settings.json").read_text())
    assert "Expose: https://northwind-shop.example/" in capsys.readouterr().out
    assert first["port"] == 8787
    run_setup("--template-language", "pt_BR", *url)           # only what changes
    second = json.loads((home / "whatsapp-cloud" / "settings.json").read_text())
    assert second["webhook_path"] == first["webhook_path"] and second["template_language"] == "pt_BR" and second["phone_number_id"] == PHONE_ID
    run_setup("--new-path", *url)
    assert json.loads((home / "whatsapp-cloud" / "settings.json").read_text())["webhook_path"] != first["webhook_path"]
    run_setup("--template-language", "en_US")                 # review fix: the saved address makes the flag unnecessary on a re-run
    assert json.loads((home / "whatsapp-cloud" / "settings.json").read_text())["public_base"] == "https://northwind-shop.example"


@pytest.mark.parametrize("argv", [
    [], ["--phone-number-id", "abc", "--template", "t", "--template-language", "pt_BR"],
    ["--phone-number-id", PHONE_ID, "--template", "Bad Name", "--template-language", "pt_BR"],
    ["--phone-number-id", PHONE_ID, "--template", "t", "--template-language", "portuguese"],
])
def test_setup_refuses_missing_or_malformed_values_with_exit_2_and_writes_nothing(home, capsys, argv):
    assert run_setup(*argv) == 2
    assert not (home / "whatsapp-cloud" / "settings.json").exists() and "--phone-number-id" in capsys.readouterr().err


@pytest.mark.parametrize("port", ["0", "70000", "-5"])
def test_a_bad_port_is_refused_by_name(home, capsys, port):
    assert run_setup("--phone-number-id", PHONE_ID, "--template", "t", "--template-language", "pt_BR", "--port", port) == 2
    assert "--port" in capsys.readouterr().err and not (home / "whatsapp-cloud" / "settings.json").exists()


def test_the_hostname_is_read_from_tailscale_status_when_it_can_be():
    class Done:
        def __init__(self, out):
            self.stdout = out
    ok = lambda argv, **k: Done(json.dumps({"Self": {"DNSName": "box.tail9.ts.net."}}))
    assert wc.funnel_host(run=ok, which=lambda n: "/bin/tailscale") == "box.tail9.ts.net"
    assert wc.funnel_host(run=ok, which=lambda n: None) is None
    assert wc.funnel_host(run=lambda *a, **k: Done("not json"), which=lambda n: "/bin/tailscale") is None
    assert wc.funnel_host(run=lambda *a, **k: Done(json.dumps({"Self": {"DNSName": "bad host name!"}})), which=lambda n: "x") is None
    assert wc.funnel_host(run=lambda *a, **k: (_ for _ in ()).throw(OSError("no")), which=lambda n: "x") is None


def test_check_settings_rejects_what_would_break_the_server_or_the_path():
    good = kit.settings(port=8787)
    assert wc.check_settings(good) == good
    for change in ({"port": "8787"}, {"port": True}, {"port": 0}, {"webhook_path": "short"}, {"webhook_path": "G" * 32},
                   {"phone_number_id": ""}, {"template": "x" * 600}, {"template_language": ""}):
        with pytest.raises(wc.ProviderError) as e:
            wc.check_settings({**good, **change})
        assert e.value.kind == "not-configured"
    with pytest.raises(wc.ProviderError):
        wc.check_settings([])


# --- whoami ------------------------------------------------------------------------------------------------------------------------


def prepare_whoami(home, monkeypatch, port):
    wc.write_private_json(wc.own_folder() + "/" + wc.SETTINGS, kit.settings(port=port))
    monkeypatch.setenv(wc.SECRET_APP, APP_SECRET)
    monkeypatch.setenv(wc.SECRET_VERIFY, VERIFY)


def test_whoami_writes_only_to_a_terminal(home, monkeypatch, capsys):
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
    assert wc.main(["whoami"]) == 2 and "terminal" in capsys.readouterr().err
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    assert wc.main(["whoami", "--seconds", "0"]) == 2


def test_whoami_refuses_while_a_bridge_holds_the_platform_lock(home, monkeypatch, capsys):
    prepare_whoami(home, monkeypatch, free_port())
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    held = wc.take_lock(str(home))
    assert held is not None
    try:
        assert wc.main(["whoami", "--seconds", "1"]) == 2
        assert "bridge" in capsys.readouterr().err
    finally:
        os.close(held)


def test_whoami_prints_the_digits_and_the_business_scoped_id_of_each_signed_message_and_nothing_else(home, monkeypatch, capsys):
    port = free_port()
    prepare_whoami(home, monkeypatch, port)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    result = []
    thread = threading.Thread(target=lambda: result.append(wc.main(["whoami", "--seconds", "3"])), daemon=True)
    thread.start()
    assert kit.wait_for(lambda: socket.socket().connect_ex(("127.0.0.1", port)) == 0, 5)

    def post(payload, secret=APP_SECRET):
        body = kit.body_of(payload)
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("POST", "/" + PATH, body, {"X-Hub-Signature-256": kit.sign(body, secret), "Content-Length": str(len(body))})
        status = conn.getresponse().status
        conn.close()
        return status
    assert post(envelope([text_message("wamid.W1")])) == 200
    assert post(envelope([text_message("wamid.W2", sender="5511911111111", uid="BR.second00000000001")])) == 200
    assert post(envelope([text_message("wamid.W3", sender="5511922222222")]), secret="wrong") == 401
    assert post(envelope([text_message("wamid.W4", sender="5511933333333")], phone_id="999")) == 200
    thread.join(10)
    assert result == [0]
    shown = capsys.readouterr()
    assert f"digits: {PERSON}" in shown.out and BSUID in shown.out and "5511911111111" in shown.out and "BR.second00000000001" in shown.out
    assert "5511922222222" not in shown.out and "5511933333333" not in shown.out and TEXT not in shown.out + shown.err
    assert not (home / "whatsapp-cloud" / wc.SEEN).exists() or json.loads((home / "whatsapp-cloud" / wc.SEEN).read_text()) == {}


# --- a real process ----------------------------------------------------------------------------------------------------------------

RUNNER = textwrap.dedent('''
    import importlib.util, json, os, sys, time, threading, urllib.error
    spec = importlib.util.spec_from_file_location("wc_under_test", sys.argv[1])
    wc = importlib.util.module_from_spec(spec); sys.modules[spec.name] = wc; spec.loader.exec_module(wc)
    mode = os.environ.get("FAKE_MODE", "ok")
    class Resp:
        def __init__(self, data): self.data = json.dumps(data).encode()
        def read(self, n=-1): return self.data
        def __enter__(self): return self
        def __exit__(self, *a): return False
    class Opener:
        n = 0
        def open(self, request, timeout=None):
            Opener.n += 1
            if mode == "hang":
                time.sleep(60)
            if mode == "auth" and request.get_method() == "POST":
                raise urllib.error.HTTPError(request.full_url, 401, "x", {}, __import__("io").BytesIO(b'{"error":{"code":190,"message":"PLANTED_BODY_TEXT"}}'))
            if request.full_url.endswith("/messages"):
                return Resp({"messages": [{"id": "wamid.OUT%d" % Opener.n}]})
            return Resp({"id": "1"})
    wc.OPENER = Opener()
    if os.environ.get("FAKE_NOISE"):
        real = wc.Store.__init__
        def noisy(self, *a, **k):
            print("a library printed this to stdout")
            os.write(1, b"and wrote this straight to fd 1\\n")
            real(self, *a, **k)
        wc.Store.__init__ = noisy
    code = wc.main(["listen"])
    sys.stdout.flush(); sys.stderr.flush()
    os._exit(code)
''')


class Process:
    def __init__(self, tmp_path, monkeypatch, mode="ok", noise=False):
        self.state = tmp_path / "state"
        monkeypatch.setenv("OPENHORA_STATE_DIR", str(self.state))
        old = os.umask(0o077)
        self.port = free_port()
        wc.write_private_json(wc.own_folder() + "/" + wc.SETTINGS, kit.settings(port=self.port))
        os.umask(old)
        runner = tmp_path / "runner.py"
        runner.write_text(RUNNER)
        env = {**os.environ, "OPENHORA_STATE_DIR": str(self.state), "FAKE_MODE": mode, wc.SECRET_TOKEN: TOKEN, wc.SECRET_APP: APP_SECRET,
               wc.SECRET_VERIFY: VERIFY}
        if noise:
            env["FAKE_NOISE"] = "1"
        self.proc = subprocess.Popen([sys.executable, str(runner), str(kit.SCRIPT)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, env=env, start_new_session=True)
        self.lines, self.stderr, self.lock = [], [], threading.Lock()
        threading.Thread(target=self.pump_out, daemon=True).start()
        threading.Thread(target=self.pump_err, daemon=True).start()

    def pump_out(self):
        for raw in self.proc.stdout:
            with self.lock:
                self.lines.append(raw)

    def pump_err(self):
        for raw in self.proc.stderr:
            with self.lock:
                self.stderr.append(raw)

    def objects(self):
        with self.lock:
            return [json.loads(l) for l in self.lines]

    def post(self, payload, secret=APP_SECRET):
        body = kit.body_of(payload)
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("POST", "/" + PATH, body, {"X-Hub-Signature-256": kit.sign(body, secret), "Content-Length": str(len(body))})
        status = conn.getresponse().status
        conn.close()
        return status

    def request(self, request):
        self.proc.stdin.write(json.dumps(request).encode() + b"\n")
        self.proc.stdin.flush()

    def everything(self):
        with self.lock:
            return b"".join(self.lines).decode("utf-8", "replace"), b"".join(self.stderr).decode("utf-8", "replace")

    def kill(self):
        if self.proc.poll() is None:
            os.killpg(self.proc.pid, signal.SIGKILL)
        self.proc.wait(10)


@pytest.fixture
def process(tmp_path, monkeypatch):
    made = []

    def make(**kw):
        p = Process(tmp_path, monkeypatch, **kw)
        made.append(p)
        return p
    yield make
    for p in made:
        p.kill()


def test_a_real_process_speaks_the_protocol_on_stdout_and_nothing_private_reaches_either_stream(process):
    p = process(noise=True)
    assert kit.wait_for(lambda: any(o.get("event") == "ready" for o in p.objects()), 10), p.everything()
    assert p.post(envelope([text_message()])) == 200
    assert kit.wait_for(lambda: any(o.get("event") == "update" for o in p.objects()), 5)
    p.post(envelope([text_message("wamid.BAD")]), secret="wrong")
    conn = http.client.HTTPConnection("127.0.0.1", p.port, timeout=5)
    conn.request("GET", f"/{PATH}?hub.mode=subscribe&hub.verify_token=wrong-{VERIFY}&hub.challenge=1")
    conn.getresponse().read()
    conn.close()
    conn = http.client.HTTPConnection("127.0.0.1", p.port, timeout=5)
    conn.request("GET", f"/elsewhere-{PATH}")
    conn.getresponse().read()
    conn.close()
    p.request({"id": 1, "op": "send", "chat": PERSON, "message": {"text": TEXT, "actions": [], "link": None, "document": None}})
    assert kit.wait_for(lambda: any(o.get("id") == 1 for o in p.objects()), 5)
    p.request({"id": 2, "op": "send", "chat": "5511977777777", "message": {"text": TEXT, "actions": [], "link": None, "document": None}})
    assert kit.wait_for(lambda: any(o.get("id") == 2 for o in p.objects()), 5)
    stdout, stderr = p.everything()
    objects = p.objects()
    assert all(("event" in o) != ("id" in o) for o in objects), "every line is an event or an answer: the stray prints went to stderr"
    assert next(o for o in objects if o.get("id") == 1)["ok"] is True
    assert next(o for o in objects if o.get("id") == 2)["kind"] == "deferred"
    assert "a library printed this" in stderr and "straight to fd 1" in stderr and "printed" not in stdout
    for secret in (TOKEN, APP_SECRET, VERIFY, PATH):
        assert secret not in stdout and secret not in stderr
    assert PERSON not in stderr and TEXT not in stderr and "5511977777777" not in stderr
    assert BSUID not in stderr and "PLANTED" not in stdout + stderr


def test_stdin_eof_ends_the_process_within_five_seconds_with_code_0_and_closes_the_port(process):
    p = process()
    assert kit.wait_for(lambda: any(o.get("event") == "ready" for o in p.objects()), 10)
    start = time.monotonic()
    p.proc.stdin.close()
    assert p.proc.wait(5) == 0 and time.monotonic() - start < 5
    assert socket.socket().connect_ex(("127.0.0.1", p.port)) != 0


def test_sigterm_ends_the_process_within_five_seconds(process):
    p = process()
    assert kit.wait_for(lambda: any(o.get("event") == "ready" for o in p.objects()), 10)
    start = time.monotonic()
    p.proc.send_signal(signal.SIGTERM)
    assert p.proc.wait(5) == 0 and time.monotonic() - start < 5


def test_eof_while_the_token_check_hangs_still_ends_the_process_within_five_seconds(process):
    p = process(mode="hang")
    assert kit.wait_for(lambda: socket.socket().connect_ex(("127.0.0.1", p.port)) == 0, 10)
    assert not any(o.get("event") == "ready" for o in p.objects())
    start = time.monotonic()
    p.proc.stdin.close()
    p.proc.wait(5)
    assert time.monotonic() - start < 5


def test_a_rejected_token_ends_the_process_with_exit_3_and_the_event_and_no_body_text(process):
    p = process(mode="auth")
    assert kit.wait_for(lambda: any(o.get("event") == "ready" for o in p.objects()), 10)
    p.post(envelope([text_message()]))
    p.request({"id": 1, "op": "send", "chat": PERSON, "message": {"text": TEXT, "actions": [], "link": None, "document": None}})
    assert p.proc.wait(10) == 3
    objects = p.objects()
    assert any(o.get("kind") == "not-configured" and o.get("event") == "error" for o in objects)
    stdout, stderr = p.everything()
    assert "PLANTED_BODY_TEXT" not in stdout + stderr and TOKEN not in stdout + stderr


def test_the_script_has_no_third_party_import_binds_no_other_address_and_logs_through_one_redacting_path():
    source = kit.SCRIPT.read_text()
    header = source.split('"""')[0]
    assert "# dependencies = []" in header and 'requires-python = ">=3.9"' in header
    imports = set(re.findall(r"^(?:import|from) ([a-z_.]+)", source, re.M))
    assert imports <= {"argparse", "collections", "hashlib", "hmac", "http.client", "http.server", "importlib.util", "json", "os", "queue",
                       "re", "secrets", "shutil", "signal", "socket", "socketserver", "stat", "subprocess", "sys", "threading", "time",
                       "urllib.error", "urllib.parse", "urllib.request", "uuid", "__future__"}, imports
    assert "0.0.0.0" not in source and "setsid" not in source
    assert "Authorization" in source and source.count("Bearer") == 1
