"""Offline tests of providers/messenger/whatsapp-twilio.py as a program: the verbs, the secrets, the settings and `setup`,
`whoami`, the state folder, and a real process (the protocol on a copy of fd 1, nothing private on any stream, the exit within
5 seconds of the end of stdin or SIGTERM). Twilio's API is a fake opener; the only socket is the provider's own on 127.0.0.1.

Every test points OPENHORA_STATE_DIR at a temporary folder. Run: uv run --with pytest pytest providers/messenger/tests/test_whatsapp_twilio.py
"""
from __future__ import annotations

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

import whatsapp_twilio_kit as kit
from whatsapp_twilio_kit import (ACCOUNT, AUTH, BSUID, BUTTONS, FROM, HOST, KEY_SECRET, KEY_SID, PATH, PERSON, PUBLIC_URL, SENDER, TEMPLATE,
                                 TEXT, inbound, wt)

REPO = Path(__file__).resolve().parents[3]
NAMES = (wt.SECRET_KEY_SID, wt.SECRET_KEY_SECRET, wt.SECRET_AUTH)


@pytest.fixture
def home(tmp_path, monkeypatch):
    state = tmp_path / "state"
    monkeypatch.setenv("OPENHORA_STATE_DIR", str(state))
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    for name in NAMES:
        monkeypatch.delenv(name, raising=False)
    old = os.umask(0o077)
    yield state
    os.umask(old)


@pytest.fixture
def secrets_in_env(monkeypatch):
    for name, value in kit.SECRETS.items():
        monkeypatch.setenv(name, value)


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# --- the verbs ----------------------------------------------------------------------------------------------------------------


def test_the_script_declares_its_platform_and_the_resolver_finds_it_and_capabilities_need_no_settings(home):
    assert wt.PLATFORMS == ("whatsapp-twilio",) and kit.SCRIPT.name == "whatsapp-twilio.py"
    env = {**os.environ, "OPENHORA_STATE_DIR": str(home)}
    done = subprocess.run([sys.executable, str(kit.SCRIPT), "capabilities", "--platform", "whatsapp-twilio"], capture_output=True,
                          text=True, env=env)
    assert json.loads(done.stdout) == wt.capabilities(None) and done.returncode == 0
    assert not home.exists(), "reading the capabilities makes no folder"
    spec = importlib.util.spec_from_file_location("resolve_for_whatsapp_twilio", REPO / "providers" / "resolve.py")
    resolve = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = resolve
    spec.loader.exec_module(resolve)
    got = resolve.resolve("messenger:whatsapp-twilio", env={})
    assert got["implementation"] == "whatsapp-twilio" and got["path"] == str(kit.SCRIPT)
    assert resolve.variables("messenger:whatsapp-twilio") == ["MESSENGER_WHATSAPP_TWILIO_PROVIDER", "MESSENGER_PROVIDER"]


def test_capabilities_read_the_buttons_from_the_saved_settings(home, capsys):
    folder = wt.own_folder()
    wt.write_private_json(folder + "/" + wt.SETTINGS, kit.settings(port=8787, buttons=BUTTONS))
    assert wt.main(["capabilities"]) == 0
    assert json.loads(capsys.readouterr().out) == wt.capabilities(kit.settings(buttons=BUTTONS)) and wt.capabilities(kit.settings(buttons=BUTTONS))["buttons"]
    wt.write_private_json(folder + "/" + wt.SETTINGS, {"nonsense": True})
    assert wt.main(["capabilities"]) == 0 and json.loads(capsys.readouterr().out)["buttons"] is False


@pytest.mark.parametrize("verb", ["receive", "send", "ack"])
def test_the_one_shot_verbs_exit_2_with_the_listen_only_sentence(verb, capsys):
    assert wt.main([verb, "--platform", "whatsapp-twilio"]) == 2
    assert "listen mode" in capsys.readouterr().err


def test_a_platform_other_than_whatsapp_twilio_is_a_usage_error():
    for other in ("whatsapp", "whatsapp-cloud"):
        with pytest.raises(SystemExit) as e:
            wt.main(["capabilities", "--platform", other])
        assert e.value.code == 2


def test_main_sets_umask_077(home):
    os.umask(0o022)
    wt.main(["capabilities"])
    assert os.umask(0o077) == 0o077


# --- the secrets ----------------------------------------------------------------------------------------------------------------


class Resolver:
    def __init__(self, values):
        self.values = values

    def resolve(self, name):
        return (self.values[name], "environment") if name in self.values else None


def test_the_three_secrets_are_read_through_the_resolver_with_the_repositorys_names():
    assert NAMES == ("MESSENGER_WHATSAPP_TWILIO_API_KEY_SID", "MESSENGER_WHATSAPP_TWILIO_API_KEY_SECRET",
                     "MESSENGER_WHATSAPP_TWILIO_AUTH_TOKEN")
    assert list(wt.KEYRING_USERNAMES.values()) == ["messenger-whatsapp-twilio-api-key-sid", "messenger-whatsapp-twilio-api-key-secret",
                                                   "messenger-whatsapp-twilio-auth-token"]
    registry = wt.secret_resolver().REGISTRY
    for name, username in wt.KEYRING_USERNAMES.items():
        assert registry[name].store_username == username and registry[name].readers == ("providers/messenger/whatsapp-twilio.py",)
    assert wt.load_secrets(resolver=Resolver(kit.SECRETS)) == kit.SECRETS


def test_a_missing_or_malformed_secret_is_not_configured_and_names_the_secret_and_never_a_value():
    for values in ({}, {wt.SECRET_KEY_SID: KEY_SID}, {**kit.SECRETS, wt.SECRET_AUTH: "has a space"}, {**kit.SECRETS, wt.SECRET_KEY_SECRET: ""}):
        with pytest.raises(wt.ProviderError) as e:
            wt.load_secrets(resolver=Resolver(values))
        assert e.value.kind == "not-configured" and e.value.code == 3 and "keyring set openhora messenger-whatsapp-twilio" in str(e.value)
        assert KEY_SECRET not in str(e.value) and AUTH not in str(e.value)


def test_listen_without_the_secrets_or_the_settings_writes_not_configured_and_exits_3(home, capsys, monkeypatch):
    monkeypatch.setattr(wt, "secret_resolver", lambda: Resolver({}))
    assert wt.main(["listen"]) == 3            # no settings yet
    first = json.loads(capsys.readouterr().out)
    assert first["event"] == "error" and first["kind"] == "not-configured" and "setup" in first["reason"]
    wt.write_private_json(str(wt.own_folder()) + "/" + wt.SETTINGS, kit.settings(port=8787))
    assert wt.main(["listen"]) == 3            # settings, no secrets
    second = json.loads(capsys.readouterr().out)
    assert second["kind"] == "not-configured" and "MESSENGER_WHATSAPP_TWILIO_API_KEY_SID" in second["reason"]


def test_the_auth_token_is_used_only_to_check_signatures_and_the_key_only_to_send():
    source = kit.SCRIPT.read_text(encoding="utf-8")
    uses = re.findall(r"secrets\[(SECRET_[A-Z_]+)\]", source)        # each value is read at one place: the signature, and the API client
    assert sorted(uses) == ["SECRET_AUTH", "SECRET_KEY_SECRET", "SECRET_KEY_SID"]
    assert re.search(r"signature_ok\(self\.secrets\[SECRET_AUTH\]", source)
    assert re.search(r"Twilio\(secrets\[SECRET_KEY_SID\], secrets\[SECRET_KEY_SECRET\]", source)
    assert "Basic" in source and source.count("Basic ") == 1


# --- the state folder -----------------------------------------------------------------------------------------------------------


def test_the_folder_is_the_bridges_rule_and_the_lock_name_agrees(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("ledger_for_whatsapp_twilio_parity", REPO / "runtime" / ("messaging" + "_ledger.py"))
    ledger = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = ledger
    spec.loader.exec_module(ledger)
    for env in ({"OPENHORA_STATE_DIR": str(tmp_path / "chosen")}, {"XDG_STATE_HOME": str(tmp_path / "xdg")}, {"XDG_STATE_HOME": "relative"}, {}):
        for name in ("OPENHORA_STATE_DIR", "XDG_STATE_HOME"):
            monkeypatch.delenv(name, raising=False)
        for name, value in env.items():
            monkeypatch.setenv(name, value)
        assert wt.state_dir() == ledger.state_dir()
    assert ledger.STATE_ENV == wt.STATE_ENV
    assert ledger.LOCK.format(platform="whatsapp-twilio") == wt.LOCK.format(platform="whatsapp-twilio")


def test_the_folder_is_made_0700_and_a_folder_open_to_others_or_a_link_is_refused(home):
    own = wt.own_folder()
    assert own == str(home / "whatsapp-twilio") and stat.S_IMODE(os.lstat(own).st_mode) == 0o700
    os.chmod(own, 0o750)
    with pytest.raises(wt.ProviderError) as e:
        wt.own_folder()
    assert e.value.kind == "not-configured" and "chmod 700" in str(e.value)
    os.chmod(own, 0o700)
    os.rmdir(own)
    elsewhere = home.parent / "elsewhere"
    elsewhere.mkdir(mode=0o700)
    os.symlink(elsewhere, own)
    with pytest.raises(wt.ProviderError) as e:
        wt.own_folder()
    assert "not a real directory" in str(e.value)


def test_every_file_of_the_state_is_0600(tmp_path):
    r = kit.Rig(tmp_path).start()
    try:
        r.post(inbound())
        r.ask(1, PERSON, kit.plain(TEXT))
    finally:
        r.stop()
    names = set(os.listdir(r.folder))
    assert {"seen.json", "window.json", "sent.json"} <= names
    for name in names:
        assert stat.S_IMODE(os.stat(os.path.join(r.folder, name)).st_mode) == 0o600, name


# --- setup ------------------------------------------------------------------------------------------------------------------------


def run_setup(*argv):
    return wt.cmd_setup(wt.build_parser().parse_args(["setup", *argv]))


GOOD = ["--account-sid", ACCOUNT, "--sender", "+14155550100", "--template-sid", TEMPLATE]


def test_setup_writes_the_settings_0600_prints_the_urls_and_the_funnel_command(home, capsys, monkeypatch, secrets_in_env):
    monkeypatch.setattr(wt, "funnel_host", lambda: HOST)
    assert run_setup(*GOOD, "--port", "8800") == 0
    shown = capsys.readouterr().out
    path = home / "whatsapp-twilio" / "settings.json"
    saved = json.loads(path.read_text())
    assert stat.S_IMODE(path.stat().st_mode) == 0o600 and stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert set(saved) == {"account_sid", "sender", "port", "webhook_path", "public_url", "template_sid", "template_button_id", "buttons"}
    assert saved["port"] == 8800 and saved["sender"] == SENDER and saved["template_button_id"] == "see-decisions" and saved["buttons"] == {}
    p = saved["webhook_path"]
    assert re.fullmatch(r"[0-9a-f]{32}", p) and saved["public_url"] == f"https://{HOST}/{p}"
    assert f"  {saved['public_url']}\n" in shown                                     # the webhook URL for the sender
    assert f"{saved['public_url']}?status=1" in shown                                # the status callback URL, passed per message
    assert "Do not also set a status callback" in shown
    assert f"tailscale funnel --bg --https=443 --set-path=/{p} http://127.0.0.1:8800/{p}" in shown
    assert "MagicDNS" in shown and "funnel attribute" in shown and TEMPLATE in shown and "see-decisions" in shown
    assert "Card buttons: off" in shown
    for secret in (KEY_SID, KEY_SECRET, AUTH):
        assert secret not in shown
    assert wt.check_settings(saved) == saved


def test_setup_refuses_without_the_secrets_with_exit_3_and_writes_nothing(home, capsys, monkeypatch):
    monkeypatch.setattr(wt, "funnel_host", lambda: HOST)
    with pytest.raises(wt.ProviderError) as e:
        run_setup(*GOOD)
    assert e.value.kind == "not-configured" and e.value.code == 3 and "MESSENGER_WHATSAPP_TWILIO_AUTH_TOKEN" in str(e.value)
    assert not (home / "whatsapp-twilio").exists()
    assert wt.main(["setup", *GOOD]) == 3 and "keyring set" in capsys.readouterr().err


def test_setup_keeps_the_path_and_the_earlier_values_unless_asked_and_a_new_path_changes_the_url(home, capsys, monkeypatch, secrets_in_env):
    monkeypatch.setattr(wt, "funnel_host", lambda: HOST)
    run_setup(*GOOD)
    first = json.loads((home / "whatsapp-twilio" / "settings.json").read_text())
    monkeypatch.setattr(wt, "funnel_host", lambda: None)               # the host is then taken from the saved URL
    run_setup("--template-button-id", "ver-decisoes")
    second = json.loads((home / "whatsapp-twilio" / "settings.json").read_text())
    assert second["webhook_path"] == first["webhook_path"] and second["public_url"] == first["public_url"]
    assert second["template_button_id"] == "ver-decisoes" and second["account_sid"] == ACCOUNT and second["port"] == 8787
    run_setup("--new-path")
    third = json.loads((home / "whatsapp-twilio" / "settings.json").read_text())
    assert third["webhook_path"] != first["webhook_path"] and third["public_url"] == f"https://{HOST}/{third['webhook_path']}"


def test_setup_without_a_known_funnel_hostname_asks_for_public_host(home, capsys, monkeypatch, secrets_in_env):
    monkeypatch.setattr(wt, "funnel_host", lambda: None)
    assert run_setup(*GOOD) == 2 and "--public-host" in capsys.readouterr().err
    assert not (home / "whatsapp-twilio" / "settings.json").exists()
    assert run_setup(*GOOD, "--public-host", "box.tail9.ts.net") == 0
    assert json.loads((home / "whatsapp-twilio" / "settings.json").read_text())["public_url"].startswith("https://box.tail9.ts.net/")
    assert run_setup(*GOOD, "--public-host", "bad host/") == 2


def test_setup_records_the_three_button_templates_or_none_and_can_clear_them(home, capsys, monkeypatch, secrets_in_env):
    monkeypatch.setattr(wt, "funnel_host", lambda: HOST)
    sids = ["--button-sid-1", BUTTONS["1"], "--button-sid-2", BUTTONS["2"], "--button-sid-3", BUTTONS["3"]]
    assert run_setup(*GOOD, *sids) == 0 and "Card buttons: on" in capsys.readouterr().out
    saved = json.loads((home / "whatsapp-twilio" / "settings.json").read_text())
    assert saved["buttons"] == BUTTONS and wt.capabilities(saved)["buttons"] is True
    assert run_setup("--port", "8801") == 0                                       # earlier buttons are kept
    assert json.loads((home / "whatsapp-twilio" / "settings.json").read_text())["buttons"] == BUTTONS
    assert run_setup("--button-sid-1", BUTTONS["1"]) == 2 and "go together" in capsys.readouterr().err
    assert run_setup("--button-sid-1", "HXshort", "--button-sid-2", BUTTONS["2"], "--button-sid-3", BUTTONS["3"]) == 2
    assert run_setup("--clear-buttons") == 0
    assert json.loads((home / "whatsapp-twilio" / "settings.json").read_text())["buttons"] == {}


@pytest.mark.parametrize("argv", [
    [], ["--account-sid", ACCOUNT], ["--account-sid", "ACshort", "--sender", "+14155550100", "--template-sid", TEMPLATE],
    ["--account-sid", ACCOUNT, "--sender", "not a number", "--template-sid", TEMPLATE],
    ["--account-sid", ACCOUNT, "--sender", "+14155550100", "--template-sid", "HXshort"],
    ["--account-sid", ACCOUNT, "--sender", "+14155550100", "--template-sid", TEMPLATE, "--template-button-id", "has space"],
])
def test_setup_refuses_missing_or_malformed_values_with_exit_2_and_writes_nothing(home, capsys, monkeypatch, secrets_in_env, argv):
    monkeypatch.setattr(wt, "funnel_host", lambda: HOST)
    assert run_setup(*argv) == 2
    assert not (home / "whatsapp-twilio" / "settings.json").exists() and "--account-sid" in capsys.readouterr().err


@pytest.mark.parametrize("sender", ["+14155550100", "14155550100", "whatsapp:+14155550100", " whatsapp:+14155550100 "])
def test_the_sender_may_be_given_with_or_without_the_prefix(home, monkeypatch, secrets_in_env, sender):
    monkeypatch.setattr(wt, "funnel_host", lambda: HOST)
    assert run_setup("--account-sid", ACCOUNT, "--sender", sender, "--template-sid", TEMPLATE) == 0
    assert json.loads((home / "whatsapp-twilio" / "settings.json").read_text())["sender"] == SENDER


@pytest.mark.parametrize("port", ["0", "70000", "-5"])
def test_a_bad_port_is_refused_by_name(home, capsys, secrets_in_env, port):
    assert run_setup(*GOOD, "--port", port) == 2 and "--port" in capsys.readouterr().err
    assert not (home / "whatsapp-twilio" / "settings.json").exists()


def test_check_settings_rejects_what_would_break_the_server_the_url_or_the_signature():
    good = kit.settings(port=8787)
    assert wt.check_settings(good) == good
    for change in ({"port": "8787"}, {"port": True}, {"port": 0}, {"webhook_path": "short"}, {"account_sid": "AC12"}, {"sender": "+141"},
                   {"public_url": "http://" + HOST + "/" + PATH}, {"public_url": f"https://{HOST}/{'e' * 32}"}, {"public_url": ""},
                   {"template_sid": ""}, {"template_button_id": ""}, {"buttons": {"1": BUTTONS["1"]}}, {"buttons": {"1": "x", "2": "y", "3": "z"}},
                   {"buttons": []}):
        with pytest.raises(wt.ProviderError) as e:
            wt.check_settings({**good, **change})
        assert e.value.kind == "not-configured", change
    with pytest.raises(wt.ProviderError):
        wt.check_settings([])
    assert wt.check_settings({**good, "buttons": BUTTONS})["buttons"] == BUTTONS
    assert wt.check_settings({k: v for k, v in good.items() if k != "buttons"})["buttons"] == {}


# --- whoami ------------------------------------------------------------------------------------------------------------------------


def prepare_whoami(home, monkeypatch, port):
    wt.write_private_json(wt.own_folder() + "/" + wt.SETTINGS, kit.settings(port=port))
    monkeypatch.setenv(wt.SECRET_AUTH, AUTH)


def test_whoami_writes_only_to_a_terminal(home, monkeypatch, capsys):
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
    assert wt.main(["whoami"]) == 2 and "terminal" in capsys.readouterr().err
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    assert wt.main(["whoami", "--seconds", "0"]) == 2


def test_whoami_refuses_while_a_bridge_holds_the_platform_lock(home, monkeypatch, capsys):
    prepare_whoami(home, monkeypatch, free_port())
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    held = wt.take_lock(str(home))
    assert held is not None
    try:
        assert wt.main(["whoami", "--seconds", "1"]) == 2
        assert "bridge" in capsys.readouterr().err
    finally:
        os.close(held)


def test_whoami_needs_only_the_auth_token(home, monkeypatch, capsys):
    wt.write_private_json(wt.own_folder() + "/" + wt.SETTINGS, kit.settings(port=free_port()))
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    assert wt.main(["whoami", "--seconds", "1"]) == 3
    assert "MESSENGER_WHATSAPP_TWILIO_AUTH_TOKEN" in capsys.readouterr().err
    assert wt.SECRET_KEY_SECRET not in capsys.readouterr().err


def test_whoami_prints_the_digits_and_the_business_scoped_id_of_each_signed_message_and_nothing_else(home, monkeypatch, capsys):
    port = free_port()
    prepare_whoami(home, monkeypatch, port)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    result = []
    thread = threading.Thread(target=lambda: result.append(wt.main(["whoami", "--seconds", "3"])), daemon=True)
    thread.start()
    assert kit.wait_for(lambda: socket.socket().connect_ex(("127.0.0.1", port)) == 0, 5)

    def post(fields, token=AUTH):
        pairs = kit.as_pairs(fields)
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("POST", "/" + PATH, kit.form_body(pairs), {"X-Twilio-Signature": kit.reference_signature(token, PUBLIC_URL, pairs)})
        status = conn.getresponse().status
        conn.close()
        return status
    assert post(inbound(1, ExternalUserId=BSUID)) == 200
    assert post(inbound(2, frm="whatsapp:+5511911111111", WaId="5511911111111", ExternalUserId="BR.second00000000001")) == 200
    assert post(inbound(3, frm="whatsapp:+5511922222222"), token="wrong") == 403
    assert post(inbound(4, frm="whatsapp:+5511933333333", account=kit.OTHER_ACCOUNT)) == 200
    thread.join(10)
    assert result == [0]
    shown = capsys.readouterr()
    assert f"digits: {PERSON}" in shown.out and BSUID in shown.out and "5511911111111" in shown.out and "BR.second00000000001" in shown.out
    assert "5511922222222" not in shown.out and "5511933333333" not in shown.out and TEXT not in shown.out + shown.err
    assert not (home / "whatsapp-twilio" / wt.SEEN).exists() or json.loads((home / "whatsapp-twilio" / wt.SEEN).read_text()) == {}


# --- a real process ----------------------------------------------------------------------------------------------------------------

RUNNER = textwrap.dedent('''
    import importlib.util, json, os, sys, time, threading, urllib.error
    spec = importlib.util.spec_from_file_location("wt_under_test", sys.argv[1])
    wt = importlib.util.module_from_spec(spec); sys.modules[spec.name] = wt; spec.loader.exec_module(wt)
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
            if mode == "auth":
                raise urllib.error.HTTPError(request.full_url, 401, "x", {}, __import__("io").BytesIO(b'{"code":20003,"message":"PLANTED_BODY_TEXT"}'))
            return Resp({"sid": "SM%032x" % (4096 + Opener.n)})
    wt.OPENER = Opener()
    if os.environ.get("FAKE_NOISE"):
        real = wt.Store.__init__
        def noisy(self, *a, **k):
            print("a library printed this to stdout")
            os.write(1, b"and wrote this straight to fd 1\\n")
            real(self, *a, **k)
        wt.Store.__init__ = noisy
    code = wt.main(["listen"])
    sys.stdout.flush(); sys.stderr.flush()
    os._exit(code)
''')


class Process:
    def __init__(self, tmp_path, monkeypatch, mode="ok", noise=False):
        self.state = tmp_path / "state"
        monkeypatch.setenv("OPENHORA_STATE_DIR", str(self.state))
        old = os.umask(0o077)
        self.port = free_port()
        wt.write_private_json(wt.own_folder() + "/" + wt.SETTINGS, kit.settings(port=self.port))
        os.umask(old)
        runner = tmp_path / "runner.py"
        runner.write_text(RUNNER)
        env = {**os.environ, "OPENHORA_STATE_DIR": str(self.state), "FAKE_MODE": mode, **kit.SECRETS}
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

    def post(self, fields, token=AUTH, query=""):
        pairs = kit.as_pairs(fields)
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("POST", "/" + PATH + ("?" + query if query else ""), kit.form_body(pairs),
                     {"X-Twilio-Signature": kit.reference_signature(token, PUBLIC_URL + ("?" + query if query else ""), pairs)})
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


def ready(p):
    return kit.wait_for(lambda: any(o.get("event") == "ready" for o in p.objects()), 10)


def test_a_real_process_speaks_the_protocol_on_stdout_and_nothing_private_reaches_either_stream(process):
    p = process(noise=True)
    assert ready(p), p.everything()
    assert p.post(inbound(1)) == 200
    assert kit.wait_for(lambda: any(o.get("event") == "update" for o in p.objects()), 5)
    assert p.post(inbound(2), token="wrong") == 403
    conn = http.client.HTTPConnection("127.0.0.1", p.port, timeout=5)
    conn.request("GET", f"/elsewhere-{PATH}?secret=hunter2")
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
    for secret in (KEY_SID, KEY_SECRET, AUTH, ACCOUNT, PATH, "hunter2"):
        assert secret not in stdout and secret not in stderr
    assert PERSON not in stderr and TEXT not in stderr and "5511977777777" not in stderr and "5511977777777" not in stdout.replace('"chat"', "")
    assert "PLANTED" not in stdout + stderr


def test_stdin_eof_ends_the_process_within_five_seconds_with_code_0_and_closes_the_port(process):
    p = process()
    assert ready(p)
    start = time.monotonic()
    p.proc.stdin.close()
    assert p.proc.wait(5) == 0 and time.monotonic() - start < 5
    assert socket.socket().connect_ex(("127.0.0.1", p.port)) != 0


def test_sigterm_ends_the_process_within_five_seconds(process):
    p = process()
    assert ready(p)
    start = time.monotonic()
    p.proc.send_signal(signal.SIGTERM)
    assert p.proc.wait(5) == 0 and time.monotonic() - start < 5


def test_eof_during_a_hanging_send_still_ends_the_process_within_five_seconds(process):
    p = process(mode="hang")
    assert ready(p), "ready does not wait for any call to Twilio"
    p.post(inbound(1))
    p.request({"id": 1, "op": "send", "chat": PERSON, "message": {"text": TEXT, "actions": [], "link": None, "document": None}})
    time.sleep(0.3)
    start = time.monotonic()
    p.proc.stdin.close()
    p.proc.wait(5)
    assert time.monotonic() - start < 5


def test_a_rejected_key_ends_the_process_with_exit_3_and_the_event_and_no_body_text(process):
    p = process(mode="auth")
    assert ready(p), "no remote ready check: a key that Twilio refuses is found on the first send"
    p.post(inbound(1))
    p.request({"id": 1, "op": "send", "chat": PERSON, "message": {"text": TEXT, "actions": [], "link": None, "document": None}})
    assert p.proc.wait(10) == 3
    objects = p.objects()
    assert any(o.get("kind") == "not-configured" and o.get("event") == "error" for o in objects)
    stdout, stderr = p.everything()
    assert "PLANTED_BODY_TEXT" not in stdout + stderr and KEY_SECRET not in stdout + stderr and AUTH not in stdout + stderr
