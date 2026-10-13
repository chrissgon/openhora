"""Offline tests of the public HTTPS address of the two official WhatsApp providers (MSG-11): `setup --public-url`, the
`--public-host` shorthand, Tailscale as an optional helper, the tunnel-neutral lines `setup` prints, and the Twilio signature over
a stored URL with a port and a prefix. Nothing reaches a network; the only socket is the provider's own on 127.0.0.1.

Every test points OPENHORA_STATE_DIR at a temporary folder. Run: uv run --with pytest pytest providers/messenger/tests/test_whatsapp_public_url.py
"""
from __future__ import annotations

import json
import os
import re
import stat

import pytest

import whatsapp_cloud_kit as ckit
import whatsapp_twilio_kit as tkit
from whatsapp_cloud_kit import PHONE_ID, wc
from whatsapp_twilio_kit import ACCOUNT, PATH, TEMPLATE, wt

SHOWN_HOST = "northwind-shop.example"
ON_TWILIO = ["--account-sid", ACCOUNT, "--sender", "+14155550100", "--template-sid", TEMPLATE]
ON_CLOUD = ["--phone-number-id", PHONE_ID, "--template", "decisions_waiting", "--template-language", "pt_BR"]
NO_ADDRESS = "give the public HTTPS address that reaches this machine: --public-url https://<host>"


@pytest.fixture
def cloud(tmp_path, monkeypatch):
    state = tmp_path / "state"
    monkeypatch.setenv("OPENHORA_STATE_DIR", str(state))
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    monkeypatch.setattr(wc, "funnel_host", lambda: None)
    old = os.umask(0o077)
    yield state / "whatsapp-cloud" / "settings.json"
    os.umask(old)


@pytest.fixture
def twilio(tmp_path, monkeypatch):
    state = tmp_path / "state"
    monkeypatch.setenv("OPENHORA_STATE_DIR", str(state))
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    for name, value in tkit.SECRETS.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(wt, "funnel_host", lambda: None)
    old = os.umask(0o077)
    yield state / "whatsapp-twilio" / "settings.json"
    os.umask(old)


def setup_cloud(*argv):
    return wc.cmd_setup(wc.build_parser().parse_args(["setup", *argv]))


def setup_twilio(*argv):
    return wt.cmd_setup(wt.build_parser().parse_args(["setup", *argv]))


# --- the shared parser ------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("given, base", [
    ("https://box.example", "https://box.example"),
    ("https://box.example/", "https://box.example"),
    ("https://box.example:8443", "https://box.example:8443"),
    ("https://box.example/team/bridge", "https://box.example/team/bridge"),
    ("https://box.example:8443/team/bridge/", "https://box.example:8443/team/bridge"),
    ("https://a-b.c-d.example", "https://a-b.c-d.example"),
])
def test_a_good_public_url_is_normalised(given, base):
    assert wc.parse_public_url(given) == base == wt.parse_public_url(given)


@pytest.mark.parametrize("given", [
    "http://box.example", "box.example", "https://", "https://box.example?x=1", "https://box.example/p?x=1", "https://box.example/p#f",
    "https://user:pw@box.example", "https://user@box.example", "https://box .example", "https://box.example/a b", "https://box.example:0",
    "https://box.example:70000", "https://box.example:", "https://bo_x.example", "https://-box.example", "https://box.example//x",
    "https://box.example/../x", "https://box.example/./x", "https://box.example/a%20b", "", None, "ftp://box.example", "https://[::1]",
])
def test_a_malformed_public_url_is_refused(given):
    assert wc.parse_public_url(given) is None


# --- WhatsApp Cloud ---------------------------------------------------------------------------------------------------------------


def test_cloud_public_url_with_a_host_gives_the_callback_url_and_the_neutral_line_and_no_funnel_command(cloud, capsys):
    assert setup_cloud(*ON_CLOUD, "--port", "8800", "--public-url", f"https://{SHOWN_HOST}") == 0
    shown = capsys.readouterr().out
    p = json.loads(cloud.read_text())["webhook_path"]
    assert stat.S_IMODE(cloud.stat().st_mode) == 0o600
    assert f"Callback URL for the app's webhook settings: https://{SHOWN_HOST}/{p}\n" in shown
    assert f"Expose: https://{SHOWN_HOST}/{p} must reach http://127.0.0.1:8800/{p} (the path kept)" in shown
    assert "tailscale" not in shown.lower() and "Funnel" not in shown


def test_cloud_public_url_with_a_port_and_a_prefix_is_kept_whole(cloud, capsys):
    assert setup_cloud(*ON_CLOUD, "--public-url", f"https://{SHOWN_HOST}:8443/team/bridge/") == 0
    shown = capsys.readouterr().out
    p = json.loads(cloud.read_text())["webhook_path"]
    assert f"Callback URL for the app's webhook settings: https://{SHOWN_HOST}:8443/team/bridge/{p}\n" in shown
    assert f"must reach http://127.0.0.1:8787/{p}" in shown and "removes the address prefix /team/bridge" in shown


@pytest.mark.parametrize("bad", ["http://box.example", "https://box.example?x=1", "https://u:p@box.example", "https://box .example"])
def test_cloud_a_malformed_public_url_exits_2_naming_the_flag_and_writes_nothing(cloud, capsys, bad):
    assert setup_cloud(*ON_CLOUD, "--public-url", bad) == 2
    err = capsys.readouterr().err
    assert "--public-url" in err and "https://<host>[:<port>][/<prefix>]" in err and "Funnel" not in err
    assert not cloud.exists()


def test_cloud_public_host_is_still_accepted_as_a_shorthand(cloud, capsys):
    assert setup_cloud(*ON_CLOUD, "--public-host", SHOWN_HOST) == 0
    p = json.loads(cloud.read_text())["webhook_path"]
    assert f"https://{SHOWN_HOST}/{p}" in capsys.readouterr().out
    assert setup_cloud(*ON_CLOUD, "--public-host", "bad host/") == 2 and "--public-host" in capsys.readouterr().err
    assert setup_cloud(*ON_CLOUD, "--public-host", SHOWN_HOST, "--public-url", f"https://{SHOWN_HOST}") == 2
    assert "not both" in capsys.readouterr().err


def test_cloud_without_an_address_and_without_tailscale_says_what_to_give(cloud, capsys):
    assert setup_cloud(*ON_CLOUD) == 2
    err = capsys.readouterr().err
    assert NO_ADDRESS in err and "http://127.0.0.1:<port>/<path>, keeping the path" in err and not cloud.exists()


def test_cloud_with_tailscale_found_uses_its_host_and_prints_the_funnel_command_as_one_example(cloud, capsys, monkeypatch):
    monkeypatch.setattr(wc, "funnel_host", lambda: "northwind-laptop.tail1234.ts.net")
    assert setup_cloud(*ON_CLOUD, "--port", "8800") == 0
    shown = capsys.readouterr().out
    p = json.loads(cloud.read_text())["webhook_path"]
    assert f"https://northwind-laptop.tail1234.ts.net/{p}" in shown and f"Expose: https://northwind-laptop.tail1234.ts.net/{p} must reach" in shown
    assert f"tailscale funnel --bg --https=443 --set-path=/{p} http://127.0.0.1:8800/{p}" in shown and "One way, Tailscale Funnel" in shown


def test_cloud_a_flag_wins_over_tailscale_and_no_funnel_command_is_printed(cloud, capsys, monkeypatch):
    monkeypatch.setattr(wc, "funnel_host", lambda: "northwind-laptop.tail1234.ts.net")
    assert setup_cloud(*ON_CLOUD, "--public-url", f"https://{SHOWN_HOST}") == 0
    shown = capsys.readouterr().out
    assert SHOWN_HOST in shown and "tail1234" not in shown and "tailscale funnel" not in shown


# --- Twilio -----------------------------------------------------------------------------------------------------------------------


def test_twilio_public_url_with_a_port_and_a_prefix_is_stored_exactly_and_shown(twilio, capsys):
    assert setup_twilio(*ON_TWILIO, "--port", "8800", "--public-url", f"https://{SHOWN_HOST}:8443/team/bridge") == 0
    shown = capsys.readouterr().out
    saved = json.loads(twilio.read_text())
    p = saved["webhook_path"]
    assert saved["public_url"] == f"https://{SHOWN_HOST}:8443/team/bridge/{p}" and wt.check_settings(saved) == saved
    assert f"  {saved['public_url']}\n" in shown and f"{saved['public_url']}?status=1" in shown
    assert f"Expose: {saved['public_url']} must reach http://127.0.0.1:8800/{p}" in shown and "Funnel" not in shown
    assert "update the URL in the Twilio Console" in shown


def test_twilio_public_url_with_a_host_only(twilio, capsys):
    assert setup_twilio(*ON_TWILIO, "--public-url", f"https://{SHOWN_HOST}") == 0
    saved = json.loads(twilio.read_text())
    assert saved["public_url"] == f"https://{SHOWN_HOST}/{saved['webhook_path']}"


@pytest.mark.parametrize("bad", ["http://box.example", "https://box.example?x=1", "https://u:p@box.example", "https://box .example",
                                 "box.example", "https://box.example:99999"])
def test_twilio_a_malformed_public_url_exits_2_naming_the_flag_before_the_secrets_and_writes_nothing(twilio, capsys, monkeypatch, bad):
    for name in tkit.SECRETS:
        monkeypatch.delenv(name)
    assert setup_twilio(*ON_TWILIO, "--public-url", bad) == 2
    assert "--public-url" in capsys.readouterr().err and not twilio.parent.exists()


def test_twilio_public_host_is_still_accepted_and_neither_flag_without_tailscale_says_what_to_give(twilio, capsys):
    assert setup_twilio(*ON_TWILIO) == 2
    err = capsys.readouterr().err
    assert NO_ADDRESS in err and "--public-host" in err and not twilio.parent.exists()
    assert setup_twilio(*ON_TWILIO, "--public-host", SHOWN_HOST) == 0
    assert json.loads(twilio.read_text())["public_url"].startswith(f"https://{SHOWN_HOST}/")
    assert setup_twilio(*ON_TWILIO, "--public-host", SHOWN_HOST, "--public-url", f"https://{SHOWN_HOST}") == 2


def test_twilio_with_tailscale_found_uses_its_host_and_prints_the_funnel_command(twilio, capsys, monkeypatch):
    monkeypatch.setattr(wt, "funnel_host", lambda: tkit.HOST)
    assert setup_twilio(*ON_TWILIO, "--port", "8800") == 0
    shown = capsys.readouterr().out
    p = json.loads(twilio.read_text())["webhook_path"]
    assert f"Expose: https://{tkit.HOST}/{p} must reach http://127.0.0.1:8800/{p}" in shown
    assert f"tailscale funnel --bg --https=443 --set-path=/{p} http://127.0.0.1:8800/{p}" in shown


def test_twilio_an_earlier_address_is_kept_when_no_flag_is_given_and_a_flag_changes_it(twilio, capsys):
    assert setup_twilio(*ON_TWILIO, "--public-url", f"https://{SHOWN_HOST}:8443/team") == 0
    first = json.loads(twilio.read_text())
    assert setup_twilio("--port", "8801") == 0
    second = json.loads(twilio.read_text())
    assert second["public_url"] == first["public_url"]
    assert setup_twilio("--new-path") == 0
    third = json.loads(twilio.read_text())
    assert third["public_url"] == f"https://{SHOWN_HOST}:8443/team/{third['webhook_path']}" != first["public_url"]
    assert setup_twilio("--public-url", "https://other.example") == 0
    assert json.loads(twilio.read_text())["public_url"] == f"https://other.example/{third['webhook_path']}"


def test_twilio_a_settings_file_with_a_prefix_in_the_url_is_valid_and_one_with_a_foreign_path_is_not():
    good = tkit.settings(port=8787, public_url=f"https://box.example:8443/team/bridge/{PATH}")
    assert wt.check_settings(good)["public_url"] == good["public_url"]
    for url in (f"https://box.example/{'a' * 32}", f"http://box.example/{PATH}", f"https://box.example/a?b/{PATH}", f"https://box.example//{PATH}"):
        with pytest.raises(wt.ProviderError):
            wt.check_settings(tkit.settings(port=8787, public_url=url))


def test_twilio_the_signature_is_computed_over_the_stored_url_with_a_port_and_a_prefix(tmp_path):
    url = f"https://{SHOWN_HOST}:8443/team/bridge/{PATH}"
    rig = tkit.Rig(tmp_path, config={"public_url": url}).start()
    try:
        fields = tkit.inbound(1)
        status, _, _ = rig.post(fields, url=url)                                 # signed as Twilio signs it: over the full public URL
        assert status == 200
        assert rig.post(fields, url=f"https://{SHOWN_HOST}:8443/{PATH}")[0] == 403          # the prefix dropped: another URL
        assert rig.post(fields, url=f"https://{SHOWN_HOST}/team/bridge/{PATH}")[0] == 403   # the port dropped
        assert rig.post(fields, url=tkit.PUBLIC_URL)[0] == 403                              # an address of another setup
    finally:
        rig.stop()


# --- Tailscale as an optional helper ----------------------------------------------------------------------------------------------


def test_the_tailscale_command_is_found_in_the_path_or_at_the_macos_app(tmp_path):
    fake = tmp_path / "Tailscale"
    fake.write_text('#!/bin/sh\necho \'{"Self": {"DNSName": "box.tail9.ts.net."}}\'\n')
    fake.chmod(0o755)
    assert wc.funnel_host(which=lambda n: None, app_paths=(str(fake),)) == "box.tail9.ts.net"
    assert wc.funnel_host(which=lambda n: None, app_paths=(str(tmp_path / "missing"),)) is None
    assert wc.funnel_host(which=lambda n: None, app_paths=()) is None
    assert wc.TAILSCALE_APP == "/Applications/Tailscale.app/Contents/MacOS/Tailscale"


def test_a_tailscale_hostname_that_is_not_a_host_is_not_used(cloud, capsys, monkeypatch):
    monkeypatch.setattr(wc, "funnel_host", lambda: "not a host")
    assert setup_cloud(*ON_CLOUD) == 2 and NO_ADDRESS in capsys.readouterr().err


def test_the_setup_text_never_calls_funnel_the_only_way(cloud, capsys):
    assert setup_cloud(*ON_CLOUD, "--public-url", "https://box.example") == 0
    assert re.search(r"funnel", capsys.readouterr().out, re.I) is None


# --- review fixes ------------------------------------------------------------------------------------------------------------------


def test_a_saved_address_is_not_replaced_by_tailscale_on_a_later_setup_twilio(twilio, capsys, monkeypatch):
    assert setup_twilio(*ON_TWILIO, "--public-url", "https://tunnel.example") == 0
    monkeypatch.setattr(wt, "funnel_host", lambda: tkit.HOST)
    assert setup_twilio("--port", "8801") == 0
    shown = capsys.readouterr().out
    assert json.loads(twilio.read_text())["public_url"].startswith("https://tunnel.example/") and "tailscale funnel" not in shown.split("Expose:")[-1]
    assert setup_twilio("--public-host", "other.example") == 0                  # a flag still wins


def test_a_saved_address_is_not_replaced_by_tailscale_on_a_later_setup_cloud(cloud, capsys, monkeypatch):
    assert setup_cloud(*ON_CLOUD, "--public-url", "https://tunnel.example:8443/x") == 0
    monkeypatch.setattr(wc, "funnel_host", lambda: "northwind-laptop.tail1234.ts.net")
    assert setup_cloud("--template-language", "en_US") == 0                    # no flag needed on a re-run
    shown = capsys.readouterr().out.split("Settings written")[-1]
    saved = json.loads(cloud.read_text())
    assert saved["public_base"] == "https://tunnel.example:8443/x" and "tail1234" not in shown and "tailscale funnel" not in shown
    assert wc.check_settings(saved) == saved


def test_cloud_with_no_saved_address_and_tailscale_found_stores_its_host(cloud, monkeypatch):
    monkeypatch.setattr(wc, "funnel_host", lambda: "northwind-laptop.tail1234.ts.net")
    assert setup_cloud(*ON_CLOUD) == 0
    assert json.loads(cloud.read_text())["public_base"] == "https://northwind-laptop.tail1234.ts.net"


def test_cloud_a_malformed_stored_address_is_refused_by_check_settings():
    good = ckit.settings(port=8787, public_base="https://box.example")
    assert wc.check_settings(good)["public_base"] == "https://box.example"
    with pytest.raises(wc.ProviderError):
        wc.check_settings(ckit.settings(port=8787, public_base="http://box.example"))


def test_the_port_is_stored_without_leading_zeros():
    assert wc.parse_public_url("https://box.example:08443/x") == "https://box.example:8443/x"
    assert wt.parse_public_url("https://box.example:00443") == "https://box.example:443"
    assert wc.parse_public_url("https://box.example:000") is None
