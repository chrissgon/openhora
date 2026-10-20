#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Messenger provider for WhatsApp through Twilio: an implementation of the class messenger:<platform> for the platform
whatsapp-twilio (providers/messenger/README.md holds the interface every messenger implements and the section "WhatsApp
through Twilio" holds the comparison with the other two WhatsApp platforms, the setup, the costs and the caveats). It works
only in the listen mode.

Inbound messages reach a small HTTP server on 127.0.0.1 as webhook calls from Twilio; the person exposes that one path at a public
HTTPS address by any means (a tunnel, a reverse proxy, a server; Tailscale Funnel is one option, never required). Outbound messages go to Twilio's Messages API. Standard library only. What it
shares with whatsapp-cloud.py (the server and its limits, the window and the template mark, the store of ids, the identity
map, the rendering) is in whatsapp_meta.py next to this file, loaded by path.

Verbs (JSON on stdout, diagnostics on stderr, input by flags, no prompt):
  capabilities --platform whatsapp-twilio
  setup --account-sid AC... --sender +<digits> [--template-sid HX... | --no-template] [--port 8787] [--new-path]
        [--public-url https://<host>[:<port>][/<prefix>] | --public-host <host>]
        [--template-button-id see-decisions] [--button-sid-1 HX... --button-sid-2 HX... --button-sid-3 HX... | --clear-buttons]
                                      write the settings, print the webhook URL, the status callback URL and what must
                                      reach the local port
  whoami [--seconds 120]              print, in the terminal, the phone digits and the business-scoped user id of whoever
                                      writes to the number meanwhile; refuses while a bridge runs
  listen --platform whatsapp-twilio   the long-lived verb (the protocol of providers/messenger/README.md)
  receive, send, ack, fetch-attachment
                                      exit 2: whatsapp-twilio works only in listen mode (a file a sender sent is fetched by the
                                      listen op `fetch` of the protocol, never by a one-shot verb)

Files a sender sends (ATT-3): `NumMedia`, `MediaUrlN` and `MediaContentTypeN` become an update with `attachments` (ref = `<MM...>:<ME...>`, parsed
from the address by a full-match pattern for this account; no name, no size; the body is the caption). The op `fetch` rebuilds the address from
the two ids and the settings' account, requests it with the Restricted API key (HTTP-Basic) at api.twilio.com only, follows one redirect and only
to Twilio's media host (MEDIA_HOSTS, an exact list) with the key left out, counts the bytes while they stream and writes `<out>/content` (O_EXCL,
O_NOFOLLOW, 0600). The Restricted API key must be allowed to read media (contracts/secrets.md).

Secrets (read only through providers/secrets/resolver.py, never in an argument, a log, an output or an exception):
  MESSENGER_WHATSAPP_TWILIO_API_KEY_SID     the SID of a Restricted API key (store username messenger-whatsapp-twilio-api-key-sid)
  MESSENGER_WHATSAPP_TWILIO_API_KEY_SECRET  that key's secret, used to send (messenger-whatsapp-twilio-api-key-secret)
  MESSENGER_WHATSAPP_TWILIO_AUTH_TOKEN      the account's Auth Token, used only to check X-Twilio-Signature
                                            (messenger-whatsapp-twilio-auth-token)

State, under the state folder (OPENHORA_STATE_DIR, else an absolute XDG_STATE_HOME with /openhora, else
~/.local/state/openhora), in whatsapp-twilio/ (mode 0700, every file 0600): settings.json (account_sid, sender, port,
webhook_path, public_url, template_sid, template_button_id, buttons), seen.json (the MessageSids handled, 8 days), window.json
(per chat: last_inbound and template_sent_at), identities.json (business-scoped user id to phone digits, 30 days), sent.json
(the MessageSids this process sent, 2 days, to match a late status after a restart). The folder holds phone numbers: keep it
out of backups.

Sources, read 2026-10-13: Twilio's documentation (twilio.com/docs/messaging/guides/webhook-request, usage/webhooks/
webhooks-security, usage/webhooks/webhooks-connection-overrides, messaging/api/message-resource, iam/api-keys,
content/twilio-quick-reply, content/using-variables-with-content-api, api/errors/63016, whatsapp/key-concepts) and Tailscale's
(kb/1223 Funnel, kb/1311 Serve and Funnel CLI).

Exit codes: 0 ok (also the end of stdin or SIGTERM in listen), 1 failed, 2 usage, 3 not configured (a secret or the settings
are missing, the key is refused, the port is taken).
"""
from __future__ import annotations

import argparse
import base64
import collections
import hashlib
import hmac
import http.client
import importlib.util
import json
import os
import re
import secrets as randomness
import signal
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

# The platforms this implementation serves. providers/resolve.py reads this one line as text, without importing the
# file, to choose among the implementations of messenger:<platform> (providers/CONTRACT.md).
PLATFORMS = ("whatsapp-twilio",)


def _shared_module():
    """whatsapp_meta.py, the file next to this one that the two official WhatsApp providers share, loaded by path (one module
    in sys.modules whichever provider loads it first)."""
    loaded = sys.modules.get("whatsapp_meta")
    if loaded is not None:
        return loaded
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "whatsapp_meta.py")
    spec = importlib.util.spec_from_file_location("whatsapp_meta", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["whatsapp_meta"] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop("whatsapp_meta", None)       # a half-loaded module must not be found by the next import
        raise
    return module


meta = _shared_module()
globals().update({name: getattr(meta, name) for name in meta.shared_names()})   # the shared names, as if defined here

SECRET_KEY_SID, SECRET_KEY_SECRET, SECRET_AUTH = ("MESSENGER_WHATSAPP_TWILIO_API_KEY_SID",
                                                  "MESSENGER_WHATSAPP_TWILIO_API_KEY_SECRET",
                                                  "MESSENGER_WHATSAPP_TWILIO_AUTH_TOKEN")   # the names the resolver registers
KEYRING_USERNAMES = dict(zip((SECRET_KEY_SID, SECRET_KEY_SECRET, SECRET_AUTH),
                             ("messenger-whatsapp-twilio-api-key-sid", "messenger-whatsapp-twilio-api-key-secret",
                              "messenger-whatsapp-twilio-auth-token")))
API_BASE = "https://api.twilio.com/2010-04-01"
FOLDER = "whatsapp-twilio"
SENT = "sent.json"
ACCOUNT_SID = re.compile(r"AC[0-9a-f]{32}")
CONTENT_SID = re.compile(r"HX[0-9a-f]{32}")
KEY_SID = re.compile(r"SK[0-9a-f]{32}")
MESSAGE_SID = re.compile(r"[A-Za-z0-9]{10,64}")
SENDER = re.compile(r"whatsapp:\+([1-9][0-9]{5,14})")
PUBLIC_URL = re.compile(r"https://([A-Za-z0-9.-]{3,253})(?::([0-9]{1,5}))?((?:/[A-Za-z0-9._~-]+)*)/([0-9a-f]{32})")
HOST = re.compile(r"[A-Za-z0-9.-]{3,253}")
BUTTON_ID = re.compile(r"[A-Za-z0-9_.:-]{1,128}")
ACTION_ID = re.compile(r"[0-9]{1,12}:[a-z][a-z-]{0,30}")      # the bridge's action ids: <seq>:<op>
DEFAULT_BUTTON_ID = "see-decisions"
STATUS_QUERY = "status=1"
TEXT_LIMIT, BODY_LIMIT, ID_LIMIT = 1600, 1024, 128
MAX_FORM_BODY = 256 * 1024                      # a Twilio form is a few kilobytes; the server's default is 3 MiB
MAX_FIELDS = 1000
TWILIO_TIMEOUT = 10.0
SENT_KEEP = 2 * 86400
CODE_WINDOW, CODE_RATE, CODE_CREDENTIALS, CODE_VARIABLES = 63016, 63018, 20003, 21656
NOT_LISTEN = "whatsapp-twilio works only in listen mode"
MEDIA_HOSTS = ("media.twiliocdn.com", "mms.twiliocdn.com")   # Twilio's media hosts, an exact list (never a suffix); the redirect of the API goes here, without the key
MEDIA_URL = re.compile(r"https://api\.twilio\.com/2010-04-01/Accounts/(AC[0-9a-f]{32})/Messages/(MM[0-9a-f]{32})/Media/(ME[0-9a-f]{32})")
MEDIA_REF = re.compile(r"(MM[0-9a-f]{32}):(ME[0-9a-f]{32})")      # the ref of an attachment: <message SID>:<media SID>
MEDIA_MAX_COUNT = 10                             # NumMedia over this drops the message
REDIRECTS = (301, 302, 303, 307, 308)
CODE_NOT_ALLOWED = 20403                          # the key is not allowed to read what it asked for
meta.KNOWN_LABELS.update((SECRET_KEY_SID, SECRET_KEY_SECRET, SECRET_AUTH, *KEYRING_USERNAMES.values()))   # not secrets: they tell the person what to store
CUT_LIMIT = TEXT_LIMIT


class TwilioError(ApiError):
    """A Twilio API call that failed. `status` is the HTTP status (0: no answer), `error_code` Twilio's code. The text is built
    from these two numbers only, never from the answer."""

    def __init__(self, status: int, code=None, what: str = ""):
        refused = status == 401 or code == CODE_CREDENTIALS
        text = what or (f"Twilio answered {status}" + (f" (error {code})" if code is not None else ""))
        super().__init__(text, status, code, refused)


# --- secrets ----------------------------------------------------------------------------------------------------------


def secret_resolver():
    """The workbench's secret resolver, by path: next to this file first (a copy), then providers/secrets/resolver.py."""
    return meta.secret_resolver()


def load_secrets(names=(SECRET_KEY_SID, SECRET_KEY_SECRET, SECRET_AUTH), resolver=None) -> dict:
    """{name: value} for each name; a ProviderError (not-configured) naming every missing or malformed one."""
    return meta.load_secrets(names, KEYRING_USERNAMES, resolver or secret_resolver(), by_username=True)


def own_folder() -> str:
    return provider_folder(FOLDER, "WhatsApp Twilio folder")


# --- the settings -----------------------------------------------------------------------------------------------------


def normalise_sender(value):
    """`whatsapp:+<digits>` from `whatsapp:+<digits>`, `+<digits>` or `<digits>`; None when it is none of these."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.startswith("whatsapp:"):
        text = text[len("whatsapp:"):]
    text = text.lstrip("+")
    return f"whatsapp:+{text}" if PHONE.fullmatch(text) else None


def check_settings(found) -> dict:
    """The settings, validated; a not-configured ProviderError naming the first thing wrong. `buttons` is {} (typed commands)
    or the three Content SIDs of the quick-reply templates for one, two and three buttons."""
    def refuse(name):
        raise ProviderError(f"settings.json has a missing or malformed {name}; run setup again", EXIT_NOT_CONFIGURED, "not-configured")
    if not isinstance(found, dict):
        raise ProviderError("settings.json is not an object; run setup again", EXIT_NOT_CONFIGURED, "not-configured")
    port = found.get("port")
    path, url = found.get("webhook_path"), found.get("public_url")
    buttons = found.get("buttons", {})
    checks = (("account_sid", isinstance(found.get("account_sid"), str) and ACCOUNT_SID.fullmatch(found["account_sid"])),
              ("sender", isinstance(found.get("sender"), str) and SENDER.fullmatch(found["sender"])),
              ("port", type(port) is int and 1 <= port <= 65535),
              ("webhook_path", isinstance(path, str) and WEBHOOK_PATH.fullmatch(path)),
              ("public_url", isinstance(url, str) and PUBLIC_URL.fullmatch(url) and url.endswith("/" + str(path))),
              ("template_sid", found.get("template_sid") is None
               or (isinstance(found.get("template_sid"), str) and CONTENT_SID.fullmatch(found["template_sid"]))),
              ("template_button_id", isinstance(found.get("template_button_id"), str)
               and BUTTON_ID.fullmatch(found["template_button_id"])),
              ("buttons (all three Content SIDs, or none)",
               buttons == {} or (isinstance(buttons, dict) and sorted(buttons) == ["1", "2", "3"]
                                 and all(isinstance(v, str) and CONTENT_SID.fullmatch(v) for v in buttons.values()))))
    for name, ok in checks:
        if not ok:
            refuse(name)
    keys = ("account_sid", "sender", "port", "webhook_path", "public_url", "template_sid", "template_button_id")
    return {**{k: found.get(k) for k in keys}, "buttons": dict(buttons)}


def load_settings(folder: str) -> dict:
    path = os.path.join(folder, SETTINGS)
    if not os.path.isfile(path):
        raise ProviderError("no settings; run: python3 providers/messenger/whatsapp-twilio.py setup (see the README)",
                            EXIT_NOT_CONFIGURED, "not-configured")
    return check_settings(read_json(path, {}))


def capabilities(settings=None) -> dict:
    """What the bridge may rely on. Buttons are on only when setup recorded the three quick-reply templates; otherwise the bridge
    folds the actions into typed commands. The provider splits nothing: the bridge cuts a card to max_text and splits replies."""
    on = bool(settings and settings.get("buttons"))
    return {"max_text": TEXT_LIMIT, "buttons": on, "max_buttons": 3 if on else 0, "max_button_label": 20 if on else 0,
            "lists": False, "max_list_rows": 0, "url_buttons": False, "reply_context": True, "documents": False, "listen": True,
            "attachments": True, "max_attachment_bytes": 16777216}     # 16 MiB: what Twilio's WhatsApp media allows for one file (to confirm in the live test)


def saved_settings():
    """The settings when a valid file exists, else None. Reads only: it makes no folder."""
    path = os.path.join(state_dir(), FOLDER, SETTINGS)
    try:
        return check_settings(read_json(path, {}))
    except ProviderError:
        return None


# --- the state --------------------------------------------------------------------------------------------------------


class SentLog:
    """The MessageSids this process sent, with the chat and the time, kept for two days in sent.json (0600): a status callback
    that reports error 63016 for one of them still matches after a restart. `folder` None keeps it in memory."""

    def __init__(self, folder=None, clock=time.time):
        self.folder, self.clock, self.lock = folder, clock, threading.Lock()
        self.rows = {}
        if folder:
            found = read_json(os.path.join(folder, SENT), {})
            self.rows = {k: v for k, v in found.items() if isinstance(k, str) and isinstance(v, list) and len(v) == 2
                         and isinstance(v[0], str) and type(v[1]) in (int, float)}
        self.prune()

    def prune(self) -> None:
        now = self.clock()
        with self.lock:
            kept = sorted(((k, v) for k, v in self.rows.items() if now - v[1] < SENT_KEEP), key=lambda kv: kv[1][1])
            self.rows = dict(kept[-SENT_MAX:])
            self.write()

    def write(self) -> None:
        if self.folder:
            try:
                write_private_json(os.path.join(self.folder, SENT), self.rows)
            except OSError:
                pass        # kept in memory; a restart then forgets them, and only a late 63016 after it is missed

    def add(self, sid: str, chat: str, when: float) -> None:
        with self.lock:
            self.rows[sid] = [chat, when]
            while len(self.rows) > SENT_MAX:
                self.rows.pop(next(iter(self.rows)))
            self.write()

    def info(self, sid: str):
        with self.lock:
            row = self.rows.get(sid)
            return (row[0], float(row[1])) if row else None


# --- rendering --------------------------------------------------------------------------------------------------------
# The same rules as renderWhatsApp in providers/messenger/whatsapp/render.go, on a shared corpus (tests/whatsapp_render_corpus.json);
# the code is in whatsapp_meta.py. Twilio takes 1600 characters in a message body.


def render_whatsapp_twilio(text: str) -> str:
    """The bridge's Markdown as WhatsApp shows it, within the 1600 characters of a message body."""
    return render_whatsapp(text, CUT_LIMIT)


# --- the Twilio API ---------------------------------------------------------------------------------------------------


class RefuseRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow a redirect: urllib would forward the Authorization header to wherever it points."""

    def redirect_request(self, req, fp, code, msg, hdrs, newurl):
        fp.close()
        raise TwilioError(code, None, f"refusing to follow a {code} redirect: the request carries the key")


OPENER = urllib.request.build_opener(RefuseRedirect)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Follow no redirect: urllib then raises the HTTPError of the 3xx answer, with its Location header, for the caller to check against the list of
    media hosts (the one redirect a media fetch follows is followed by the caller, with the key left out)."""

    def redirect_request(self, req, fp, code, msg, hdrs, newurl):
        return None


MEDIA_OPENER = urllib.request.build_opener(NoRedirect)


class Twilio:
    """The Messages API with the standard library, as the Restricted API key. Every failure is a TwilioError built from numbers."""

    def __init__(self, key_sid: str, key_secret: str, account_sid: str, opener=None, base: str = API_BASE, media_opener=None):
        self.key_sid, self.key_secret, self.account, self.opener, self.base = key_sid, key_secret, account_sid, opener or OPENER, base
        self.media_opener = media_opener or MEDIA_OPENER

    def basic(self) -> str:
        return "Basic " + base64.b64encode(f"{self.key_sid}:{self.key_secret}".encode("utf-8")).decode("ascii")

    def fetch_media(self, ref, out_dir, max_bytes: int) -> dict:
        """Fetch the medium `ref` (`<MM...>:<ME...>`) into `<out_dir>/content`, at most `max_bytes`: {"bytes", "sha256"}. The address is rebuilt from the
        two ids, this account and the fixed base, and requested with the key (HTTP Basic). Twilio answers with a redirect to its media host: one is
        followed, only to MEDIA_HOSTS and with the key left out; any other redirect, or a second, is refused. A medium Twilio no longer has is a
        ProviderError of kind `gone`."""
        found = MEDIA_REF.fullmatch(ref) if isinstance(ref, str) else None
        if found is None:
            raise ProviderError("the reference is not the pair of a Twilio message SID and media SID", EXIT_USAGE, "usage")
        end = time.monotonic() + FETCH_DEADLINE
        url = f"{self.base}/Accounts/{self.account}/Messages/{found.group(1)}/Media/{found.group(2)}"
        try:
            try:
                response = self.media_opener.open(self.media_request(url, {"Authorization": self.basic()}), timeout=FETCH_CONNECT)
            except urllib.error.HTTPError as e:
                if e.code not in REDIRECTS:
                    raise
                location = e.headers.get("Location") if e.headers is not None and hasattr(e.headers, "get") else None
                e.close()
                target = url_on_hosts(location, MEDIA_HOSTS)
                if target is None:
                    raise ProviderError("Twilio redirected the medium to a host that is not its media host", EXIT_SERVICE, "failed") from None
                return self.stream_from(target, out_dir, max_bytes, end)
            with response:
                return save_stream(response, out_dir, max_bytes, None, end)
        except ProviderError:
            raise
        except urllib.error.HTTPError as e:
            raise self.status_error(e, first=True) from None
        except urllib.error.URLError as e:
            raise TwilioError(0, None, f"Twilio could not be reached ({type(getattr(e, 'reason', e)).__name__})") from None
        except (OSError, ValueError, http.client.HTTPException) as e:
            raise TwilioError(0, None, f"the call to Twilio failed ({type(e).__name__})") from None

    @staticmethod
    def media_request(url: str, headers: dict):
        return urllib.request.Request(url, method="GET", headers={"Accept": "*/*", **headers})

    def stream_from(self, url: str, out_dir, max_bytes: int, end: float) -> dict:
        """The second request of a media fetch: the redirect's target, with no credential, no redirect followed."""
        try:
            with self.media_opener.open(self.media_request(url, {}), timeout=FETCH_CONNECT) as response:
                return save_stream(response, out_dir, max_bytes, None, end)
        except ProviderError:
            raise
        except urllib.error.HTTPError as e:
            raise self.status_error(e, first=False) from None
        except urllib.error.URLError as e:
            raise ProviderError(f"Twilio's media host could not be reached ({type(getattr(e, 'reason', e)).__name__})", EXIT_SERVICE, "failed") from None
        except (OSError, ValueError, http.client.HTTPException) as e:
            raise ProviderError(f"the call to Twilio's media host failed ({type(e).__name__})", EXIT_SERVICE, "failed") from None

    @staticmethod
    def status_error(e, first: bool):
        """The error for an HTTP error answer of a media fetch, from numbers only. 404 and 410 are a medium Twilio no longer serves."""
        status = e.code
        code = None
        if first:
            try:
                parsed = json.loads(e.read(65536).decode("utf-8"))
                found = parsed.get("code") if isinstance(parsed, dict) else None
                code = found if type(found) is int else None
            except Exception:  # an unreadable body is only a missing code
                pass
        e.close()
        if status in (404, 410):
            return ProviderError("Twilio no longer serves that file", EXIT_SERVICE, "gone")
        if not first:
            return ProviderError(f"Twilio's media host answered {status}", EXIT_SERVICE, "failed")
        if status in (401, 403) or code in (CODE_NOT_ALLOWED, CODE_CREDENTIALS):
            # a failure of this fetch, not a stop of the provider: a key that was really revoked is caught by the next send
            return ProviderError(f"Twilio answered {status}: the API key may lack the permission to read media", EXIT_SERVICE, "failed")
        return TwilioError(status, code)

    def post_message(self, fields: dict) -> str:
        """POST a form to Messages.json; the SID of the message Twilio accepted."""
        request = urllib.request.Request(
            f"{self.base}/Accounts/{self.account}/Messages.json", data=urllib.parse.urlencode(fields).encode("utf-8"), method="POST",
            headers={"Authorization": self.basic(), "Accept": "application/json",
                     "Content-Type": "application/x-www-form-urlencoded"})
        try:
            with self.opener.open(request, timeout=TWILIO_TIMEOUT) as response:
                answer = response.read(MAX_ANSWER)
        except urllib.error.HTTPError as e:
            code = None
            try:
                parsed = json.loads(e.read(65536).decode("utf-8"))
                found = parsed.get("code") if isinstance(parsed, dict) else None
                code = found if type(found) is int else None
            except Exception:  # an unreadable body is only a missing code
                pass
            raise TwilioError(e.code, code) from None
        except TwilioError:
            raise
        except urllib.error.URLError as e:
            raise TwilioError(0, None, f"Twilio could not be reached ({type(getattr(e, 'reason', e)).__name__})") from None
        except (OSError, ValueError, http.client.HTTPException) as e:
            raise TwilioError(0, None, f"the call to Twilio failed ({type(e).__name__})") from None
        try:
            parsed = json.loads(answer.decode("utf-8")) if answer else {}
        except ValueError:
            raise TwilioError(0, None, "Twilio's answer was not JSON") from None
        found = parsed.get("sid") if isinstance(parsed, dict) else None
        if not isinstance(found, str) or not MESSAGE_SID.fullmatch(found):
            raise TwilioError(0, None, "Twilio did not return the SID of the message")
        return found


def status_url(settings: dict) -> str:
    return settings["public_url"] + "?" + STATUS_QUERY


def text_fields(settings: dict, to: str, text: str) -> dict:
    return {"From": settings["sender"], "To": to, "Body": text, "StatusCallback": status_url(settings)}


def content_fields(settings: dict, to: str, sid: str, variables=None) -> dict:
    fields = {"From": settings["sender"], "To": to, "ContentSid": sid, "StatusCallback": status_url(settings)}
    if variables:
        fields["ContentVariables"] = json.dumps(variables, ensure_ascii=True, sort_keys=True)
    return fields


def button_variables(body: str, actions: list) -> dict:
    """The variables of a quick-reply template: {{1}} the body, then the title and the id of each button ({{2}} and {{3}} for
    the first, {{4}} and {{5}} for the second, {{6}} and {{7}} for the third)."""
    variables = {"1": body}
    for n, (action, title) in enumerate(zip(actions, button_titles(actions))):
        variables[str(2 + 2 * n)] = title
        variables[str(3 + 2 * n)] = action["id"]
    return variables


def check_message(message, settings=None) -> dict:
    """The neutral message, checked against the capabilities: a usage error (exit 2) when it does not fit."""
    caps = capabilities(settings)
    return meta.check_message(message, max_text=caps["max_text"], max_buttons=caps["max_buttons"], id_limit=ID_LIMIT,
                              documents=False)


# --- sending ----------------------------------------------------------------------------------------------------------


class Sender(meta.BaseSender):
    """The send side: the window gate, the template, the messages. The SIDs sent are kept in sent.json, to match the status
    callback that reports error 63016 (a free-form message outside the 24-hour window), which arrives after Twilio accepted it."""

    platform = "whatsapp-twilio"

    def __init__(self, api: Twilio, store, settings: dict, log, clock=time.time, sent_log=None):
        super().__init__(store, log, clock)
        self.api, self.settings, self.sent_log = api, settings, sent_log or SentLog(None, clock)
        self.variables_refused = False      # set when Twilio refused a card's variables once; later cards go the other way
        self.cards = collections.OrderedDict()   # SID of a Content card -> (chat, text, actions): to resend it if Twilio refuses later

    def recipient(self, chat: str) -> str:
        return "whatsapp:+" + super().recipient(chat)

    def remember_sent(self, wamid: str, chat: str, when: float) -> None:
        super().remember_sent(wamid, chat, when)
        self.sent_log.add(wamid, chat, when)

    def sent_info(self, wamid: str):
        return super().sent_info(wamid) or self.sent_log.info(wamid)

    def has_template(self) -> bool:
        return bool(self.settings.get("template_sid"))

    def post_template(self, to: str) -> str:
        return self.api.post_message(content_fields(self.settings, to, self.settings["template_sid"]))

    def card_template(self, count: int):
        return self.settings["buttons"].get(str(count))

    def buttons_message(self, to: str, body: str, actions: list) -> str:
        return self.api.post_message(content_fields(self.settings, to, self.card_template(len(actions)),
                                                    button_variables(body, actions)))

    def late_failure(self, item) -> None:
        """A status callback reported a failure. ("variables", sid): Twilio refused a Content card's variables after accepting it
        (error 21656 by callback): resend that card once as the text and the fixed-body buttons message. A plain SID: error 63016."""
        if not isinstance(item, tuple):
            return super().late_failure(item)
        with self.sent_lock:
            card = self.cards.pop(item[1], None)
        if card is None or self.sent_info(item[1]) is None:
            return
        chat, rendered, actions = card
        now = self.clock()
        if not self.store.window_open(chat, now):
            return
        to = self.recipient(chat)
        self.variables_refused = True
        self.log("Twilio refused the variables of a card in a status report (error 21656): resending it as text and a "
                 "buttons message with a short fixed body")
        try:
            first = self.api.post_message(text_fields(self.settings, to, rendered))
            self.remember_sent(first, chat, now)
            got = self.buttons_message(to, BUTTONS_LINE, actions)
            self.remember_sent(got, chat, now)
            self.set_alias(got, first)
        except TwilioError as e:
            if e.kind == "not-configured":
                raise
            self.log(f"the card could not be resent ({e.status}, {e.error_code})")

    def send(self, chat: str, message: dict) -> str:
        """Send the card or text; the SID of the message that carries the text. Raises Deferred when the window is closed.
        Twilio has no reply-to parameter, so `reply_to` is not used."""
        to = self.recipient(chat)
        now = self.clock()
        if not self.store.window_open(chat, now):
            self.defer(chat, to)
        rendered = render_whatsapp_twilio(message["text"])
        actions = message.get("actions") or []
        if actions and not self.card_template(len(actions)):
            actions = []                       # buttons are off: the bridge folds the actions, so this is only a guard
        first, follow = None, []
        try:
            if actions and len(rendered) <= BODY_LIMIT and not (self.variables_refused and "\n" in rendered):
                try:
                    first = self.buttons_message(to, rendered, actions)
                except TwilioError as e:
                    if e.error_code != CODE_VARIABLES:
                        raise
                    self.variables_refused = True
                    self.log("Twilio refused the variables of a card (error 21656), probably a newline in the text: sending the "
                             "text and then a buttons message with a short fixed body, from now on")
            if first is None:
                first = self.api.post_message(text_fields(self.settings, to, rendered))
                if actions:
                    follow = [("buttons", lambda: self.buttons_message(to, BUTTONS_LINE, actions))]
        except TwilioError as e:
            if e.error_code == CODE_WINDOW:
                self.store.close_window(chat, now)
                self.persist()
                self.defer(chat, to)
            raise
        self.remember_sent(first, chat, now)
        if actions and not follow:
            with self.sent_lock:
                self.cards[first] = (chat, rendered, actions)
                while len(self.cards) > SENT_MAX:
                    self.cards.popitem(last=False)
        for what, step in follow:
            try:
                got = step()
                self.remember_sent(got, chat, now)
                self.set_alias(got, first)
            except TwilioError as e:
                if e.kind == "not-configured":
                    raise
                # the text is delivered: failing the send would make the bridge send it twice
                self.log(f"the {what} after the text could not be sent ({e.status}, {e.error_code})")
        return first


# --- the webhook ------------------------------------------------------------------------------------------------------


def parse_form(body: bytes):
    """The (name, value) pairs of a form-encoded body, as Twilio's validator reads them (keep blank values, UTF-8), or None."""
    try:
        return urllib.parse.parse_qsl(body.decode("utf-8"), keep_blank_values=True, encoding="utf-8", errors="strict",
                                      max_num_fields=MAX_FIELDS)
    except (UnicodeDecodeError, ValueError):
        return None


def compute_signature(token: str, url: str, pairs) -> str:
    """base64(HMAC-SHA1(token, url + each parameter name followed by its value)), the names sorted, each name's values sorted
    and a repeated value counted once: Twilio's own validator (twilio-python, request_validator.py)."""
    grouped = {}
    for name, value in pairs:
        grouped.setdefault(name, set()).add(value)
    text = url
    for name in sorted(grouped):
        for value in sorted(grouped[name]):
            text += name + value
    return base64.b64encode(hmac.new(token.encode("utf-8"), text.encode("utf-8"), hashlib.sha1).digest()).decode("ascii")


def url_forms(url: str) -> list:
    """The URL as given and with the default port of an https URL added (:443) or removed, as Twilio's validator accepts both."""
    found = re.fullmatch(r"(https://)([^/:?#]+)(?::([0-9]+))?(.*)", url, re.S)
    if not found:
        return [url]
    scheme, host, port, rest = found.groups()
    if port is None:
        return [url, f"{scheme}{host}:443{rest}"]
    if port == "443":
        return [url, f"{scheme}{host}{rest}"]
    return [url]


def signature_ok(token: str, url: str, pairs, header) -> bool:
    """X-Twilio-Signature, checked against the URL as Twilio called it (with and without :443) and the form's parameters,
    compared on bytes in constant time."""
    if not isinstance(header, str) or not header:
        return False
    given = header.encode("latin-1", "replace")
    ok = False
    for form in url_forms(url):
        ok |= hmac.compare_digest(compute_signature(token, form, pairs).encode("ascii"), given)
    return ok


TWIML = b"<?xml version=\"1.0\" encoding=\"UTF-8\"?><Response/>"      # the empty answer: no reply is sent by Twilio


class Webhook(meta.HookBase):
    """What the server does with a call: the signature and the form. `emit(update, uid)` takes an update; `late` takes the SID of a
    message this process sent that Twilio reports as failed for error 63016."""

    methods = ("POST",)

    def handle_post(self, headers, query: str, body: bytes):
        if not self.accepting:
            return 503, b"", None
        pairs = parse_form(body)
        url = self.settings["public_url"] + ("?" + query if query else "")      # the query as received, never re-encoded
        if pairs is None or not signature_ok(self.secrets[SECRET_AUTH], url, pairs, headers.get("X-Twilio-Signature")):
            self.note("signature", "webhook: a call with a missing or wrong signature was refused")
            return 403, b"", None
        try:
            if query == "":
                self.message(Fields(pairs))
            elif query == STATUS_QUERY:
                self.status(Fields(pairs))
            else:
                self.note("query", "webhook: a signed call with an unknown query was ignored")
            self.store.flush()        # a failure is an OSError: the answer is 500 (Twilio does not retry it, so this message is lost)
        except Exception as e:
            self.note("processing", f"webhook: processing failed ({type(e).__name__})")
            return 500, b"", None
        return 200, TWIML, "text/xml; charset=utf-8"

    def mine(self, fields) -> bool:
        return fields.get("AccountSid") == self.settings["account_sid"]

    def status(self, fields) -> None:
        if not self.mine(fields) or fields.get("From") != self.settings["sender"]:
            return
        if fields.get("MessageStatus") not in ("failed", "undelivered") or fields.get("ErrorCode") not in (str(CODE_WINDOW), str(CODE_VARIABLES)):
            return
        sid = fields.get("MessageSid")
        if isinstance(sid, str) and self.sent_info(sid) is not None:
            self.late(sid if fields.get("ErrorCode") == str(CODE_WINDOW) else ("variables", sid))

    def identity(self, fields):
        """(chat, business-scoped id) from `From`: `whatsapp:+<digits>`, or, for a person who uses a username, an id with no
        number; `ExternalUserId` and `WaId` are read only when they have the shape of an id and of a number."""
        raw = fields.get("From") or ""
        if not raw.startswith("whatsapp:"):
            return None, None            # not a WhatsApp sender (an SMS number, say)
        digits = uid = None
        rest = raw[len("whatsapp:"):]
        if not rest:
            return None, None
        if rest.startswith("+"):
            digits = rest[1:]
        else:
            uid = rest
        uid = uid or fields.get("ExternalUserId")
        wa = fields.get("WaId")
        digits = digits or (wa if isinstance(wa, str) and PHONE.fullmatch(wa) else None)
        return self.identity_of(digits, uid)

    def message(self, fields) -> None:
        if not self.mine(fields) or fields.get("To") != self.settings["sender"]:
            return
        sid = fields.get("MessageSid")
        if not isinstance(sid, str) or not MESSAGE_SID.fullmatch(sid) or self.store.is_seen(sid):
            return
        text = action = reply_to = attachments = None
        payload = fields.get("ButtonPayload")
        if not payload and not fields.get("ButtonText") and self.media_count(fields):
            attachments = self.media_of(fields)
            if attachments is None:
                self.note("media", "webhook: a message with media this provider could not read was ignored")
                return
            body = fields.get("Body")
            text = body if isinstance(body, str) and body.strip() else None      # the caption; the bridge reads only an exact @<id> of it
        elif payload:
            # a tap: only the action (or the template's "See decisions" as /pending); Twilio also puts the title in Body, never read
            if payload == self.settings["template_button_id"]:
                text = "/pending"
            elif ACTION_ID.fullmatch(payload):
                action = payload
            else:
                return
        else:
            body = fields.get("Body")
            if not isinstance(body, str) or not body.strip() or fields.get("ButtonText"):
                return
            text = body
        chat, uid = self.identity(fields)
        if chat is None:
            return
        replied = fields.get("OriginalRepliedMessageSid")
        if text != "/pending" and isinstance(replied, str) and MESSAGE_SID.fullmatch(replied):
            reply_to = self.alias(replied)
        self.store.note_inbound(chat, self.clock())      # Twilio sends no message time: the time of receipt (before the update, so the reply finds the window open)
        update = {"update_id": sid, "sender": chat, "chat": chat, "private": True, "text": text, "action": action,
                  "action_ref": None, "reply_to": reply_to}
        if attachments:
            update["attachments"] = attachments
        if action is None and meta.forwarded_field(fields):
            update["forwarded"] = True      # the key is there only for a forward (providers/messenger/README.md); a tap is never one
        self.emit(update, uid)
        self.store.mark_seen(sid)

    @staticmethod
    def media_count(fields) -> int:
        """NumMedia as a number: 0 when it is absent or not a plain number (the message is then read as it always was, by its Body)."""
        value = fields.get("NumMedia")
        return int(value) if isinstance(value, str) and value.isascii() and value.isdigit() and len(value) <= 4 else 0

    def media_of(self, fields):
        """The attachments of a message with media, or None when any of them cannot be read: the whole message is then dropped, since an update that
        showed only some of the files would hide the rest. Each address must be exactly Twilio's media address for this account (MEDIA_URL); the
        ref is the message SID and the media SID in it; there is no name and no size; the type is the declared content type, mapped for the kinds
        the bridge refuses before it downloads."""
        count = self.media_count(fields)
        if not 1 <= count <= MEDIA_MAX_COUNT:
            return None
        found = []
        for n in range(count):
            url = fields.get(f"MediaUrl{n}")
            parts = MEDIA_URL.fullmatch(url) if isinstance(url, str) else None
            if parts is None or parts.group(1) != self.settings["account_sid"] or parts.group(2) != fields.get("MessageSid"):
                return None      # the address must be of this account and of this very message
            found.append({"ref": f"{parts.group(2)}:{parts.group(3)}", "name": None, "size": None,
                          "type": type_for_mime(fields.get(f"MediaContentType{n}"))})
        return found


class Fields:
    """The values of a form by name: the one value, or None when the name is absent or carries different values (a parameter that
    arrives twice with different values is ambiguous, so the filters never read it)."""

    def __init__(self, pairs):
        grouped = {}
        for name, value in pairs:
            grouped.setdefault(name, set()).add(value)
        self.values = {k: next(iter(v)) for k, v in grouped.items() if len(v) == 1}

    def get(self, name, default=None):
        return self.values.get(name, default)


# --- the listen mode --------------------------------------------------------------------------------------------------


class Listener(meta.Listener):
    """One listen process: the webhook server, the sender thread and the stdin reader share this object. There is no remote ready
    check (the key may be restricted to sending): `ready` is written when the server listens, and a refused key on the first send
    is `not-configured` (exit 3)."""

    refused_reason = "Twilio refused the API key"
    refused_fatal = "Twilio refused the API key: check the key, its permissions and the account, then store it again"
    rate_codes = (CODE_RATE,)
    can_fetch = True

    def __init__(self, settings: dict, secrets: dict, store, *, api=None, **options):
        super().__init__(settings, secrets, store, max_body=MAX_FORM_BODY, **options)
        self.api = api or Twilio(secrets[SECRET_KEY_SID], secrets[SECRET_KEY_SECRET], settings["account_sid"])
        self.sender = Sender(self.api, store, settings, self.log, self.clock, SentLog(store.folder, self.clock))

    def check(self, message) -> dict:
        return check_message(message, self.settings)

    def fetch(self, ref, out_dir, max_bytes: int) -> dict:
        return self.api.fetch_media(ref, out_dir, max_bytes)

    def make_hook(self):
        return Webhook(self.settings, self.secrets, self.store, self.emit, late=lambda sid: self.requests.put(("late", sid)),
                       sent_info=self.sender.sent_info, note=self.note, clock=self.clock, alias=self.sender.alias_of)

    def startup(self) -> None:
        if not self.stop.is_set():
            self.begin()


def run_listen(*, install_signals: bool = True, folder=None, secrets=None, **options) -> int:
    """The process wiring: the protocol on a copy of fd 1, fd 1 pointed at stderr so that no print reaches the bridge."""
    folder = folder or own_folder()
    settings = load_settings(folder)
    secrets = secrets or load_secrets()
    return meta.serve(lambda out, stdin: Listener(settings, secrets, Store(folder), out=out, stdin=stdin, **options),
                      install_signals=install_signals)


# --- verbs ------------------------------------------------------------------------------------------------------------


def take_lock(state: str):
    """The platform's lock, non-blocking, held while whoami runs (a bridge holds it for its life). The descriptor, or None."""
    return meta.take_lock(state, "whatsapp-twilio")


def host_of(url):
    found = PUBLIC_URL.fullmatch(url) if isinstance(url, str) else None
    return found.group(1) if found else None


def cmd_setup(args) -> int:
    if args.port is not None and not 1 <= args.port <= 65535:
        say("--port is a number from 1 to 65535")
        return EXIT_USAGE
    if args.no_template and args.template_sid:
        say("--no-template cannot be combined with --template-sid")
        return EXIT_USAGE
    path = os.path.join(state_dir(), FOLDER, SETTINGS)       # read only: no folder is made before every flag is valid
    current = read_json(path, {})
    given = (args.button_sid_1, args.button_sid_2, args.button_sid_3)
    if args.clear_buttons:
        buttons = {}
    elif any(given):
        buttons = {str(n): sid for n, sid in zip((1, 2, 3), given)}
        if not all(given):
            say("--button-sid-1, --button-sid-2 and --button-sid-3 go together: the Content SIDs of the quick-reply templates for "
                "one, two and three buttons (or none, for typed commands)")
            return EXIT_USAGE
    else:
        buttons = current.get("buttons", {})
    chosen = {"account_sid": args.account_sid or current.get("account_sid"),
              "sender": normalise_sender(args.sender) if args.sender else current.get("sender"),
              "port": args.port if args.port is not None else current.get("port", DEFAULT_PORT),
              "webhook_path": current.get("webhook_path"),
              "template_sid": None if args.no_template else (args.template_sid or current.get("template_sid")),
              "template_button_id": args.template_button_id or current.get("template_button_id") or DEFAULT_BUTTON_ID,
              "buttons": buttons}
    if args.new_path or not (isinstance(chosen["webhook_path"], str) and WEBHOOK_PATH.fullmatch(chosen["webhook_path"])):
        chosen["webhook_path"] = randomness.token_hex(16)
    saved = current.get("public_url")
    base, used_tailscale, problem = choose_public_base(
        args.public_url, args.public_host, funnel=funnel_host,
        saved=saved.rsplit("/", 1)[0] if isinstance(saved, str) and parse_public_url(saved.rsplit("/", 1)[0]) else None)
    if problem:
        say(problem)
        return EXIT_USAGE
    chosen["public_url"] = f"{base}/{chosen['webhook_path']}"
    try:
        settings = check_settings(chosen)
    except ProviderError as e:
        say(str(e).replace("; run setup again", "") + ": give --account-sid and --sender")
        return EXIT_USAGE
    load_secrets()                      # the three secrets must be in the store or the environment before anything is written
    path = os.path.join(own_folder(), SETTINGS)
    write_private_json(path, settings)
    on = bool(settings["buttons"])
    print(f"Settings written to {path} (mode 0600).\n"
          "In the Twilio Console, on the WhatsApp sender's Endpoint configuration, set \"When a message comes in\" to this URL "
          f"(method POST):\n  {settings['public_url']}\n"
          f"Status callbacks: the provider asks for them in each message it sends, at {status_url(settings)}. Do not also set a "
          "status callback URL on the sender (every report would arrive twice).\n"
          + expose_lines(base, settings, used_tailscale)
          + "If the public address changes, run setup again and update the URL in the Twilio Console.\n"
          + (f"Outside the 24-hour window the provider sends the Content template {settings['template_sid']}; its quick reply must "
             f"have the id {settings['template_button_id']}.\n" if settings["template_sid"] else
             "No reminder template: after 24 hours of silence the person must write first; the cards wait until then.\n")
          + ("Card buttons: on (three quick-reply templates recorded)." if on else
             "Card buttons: off, the bridge sends the actions as typed commands (give --button-sid-1/2/3 to turn them on)."))
    return EXIT_OK


def cmd_whoami(args) -> int:
    if not sys.stdout.isatty():
        say("whoami prints phone numbers and so writes only to a terminal; run it in one, not into a pipe, a file or a log")
        return EXIT_USAGE
    if not 1 <= args.seconds <= 600:
        say("--seconds is a number from 1 to 600")
        return EXIT_USAGE
    folder = own_folder()
    settings = load_settings(folder)
    secrets = load_secrets((SECRET_AUTH,))
    lock = take_lock(state_dir())
    if lock is None:
        return EXIT_USAGE
    stop = threading.Event()

    def show(update, uid):
        print(f"digits: {update['sender'] if PHONE.fullmatch(update['sender']) else '-'}   business-scoped user id: {uid or '-'}",
              flush=True)
    hook = Webhook(settings, secrets, Store(None), show, note=Notes(say))
    try:
        server = Server(settings["port"], hook, max_body=MAX_FORM_BODY)
    except OSError as e:
        say(f"the webhook server cannot listen on {LOOPBACK}:{settings['port']} ({e.strerror or e.__class__.__name__})")
        os.close(lock)
        return EXIT_NOT_CONFIGURED
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True).start()
    say(f"Listening for {args.seconds} seconds. Send a message to the business number from your own WhatsApp.")
    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGINT, lambda *_: stop.set())
    stop.wait(args.seconds)
    closer = threading.Thread(target=server.shutdown, daemon=True)
    closer.start()
    closer.join(2.0)
    server.server_close()
    os.close(lock)
    return EXIT_OK


def cmd_capabilities(args) -> int:
    print(json.dumps(capabilities(saved_settings())))
    return EXIT_OK


def cmd_listen(args) -> int:
    return run_listen()


def cmd_one_shot(args) -> int:
    say(NOT_LISTEN)
    return EXIT_USAGE


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="verb", required=True)
    for name, func in (("capabilities", cmd_capabilities), ("listen", cmd_listen)):
        sub.add_parser(name).set_defaults(func=func)
    setup = sub.add_parser("setup")
    for flag in ("--account-sid", "--sender", "--public-url", "--public-host", "--template-sid", "--template-button-id",
                 "--button-sid-1", "--button-sid-2", "--button-sid-3"):
        setup.add_argument(flag)
    setup.add_argument("--port", type=int)
    setup.add_argument("--new-path", action="store_true")
    setup.add_argument("--clear-buttons", action="store_true")
    setup.add_argument("--no-template", action="store_true")
    setup.set_defaults(func=cmd_setup)
    who = sub.add_parser("whoami")
    who.add_argument("--seconds", type=int, default=120)
    who.set_defaults(func=cmd_whoami)
    for name in ("receive", "send", "ack", "fetch-attachment"):
        one = sub.add_parser(name)
        one.set_defaults(func=cmd_one_shot)
        for flag in ("--offset", "--timeout", "--chat", "--message-file", "--action-ref", "--ref", "--out", "--max-bytes"):
            one.add_argument(flag)
    for parser in sub.choices.values():
        parser.add_argument("--platform", default="whatsapp-twilio", choices=PLATFORMS)
    return p


def main(argv=None) -> int:
    return meta.run_cli(build_parser, argv)


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)  # daemon threads may still be in a network call; the process ends now, within the 5 seconds
