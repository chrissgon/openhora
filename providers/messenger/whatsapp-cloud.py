#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Messenger provider for the official WhatsApp Cloud API: an implementation of the class messenger:<platform> for the
platform whatsapp-cloud (providers/messenger/README.md holds the interface every messenger implements and the section
"WhatsApp Cloud API" holds the setup, the tunnel options, the privacy and the costs). It works only in the listen mode.

Inbound messages reach a small HTTP server on 127.0.0.1 as webhook calls from Meta; the person exposes that one path at a public
HTTPS address by any means (a tunnel, a reverse proxy, a server; Tailscale Funnel is one option, never required). Outbound messages go to the Graph API. Standard library only. What it shares
with whatsapp-twilio.py (the server and its limits, the window and the template mark, the store of ids, the identity map, the
rendering) is in whatsapp_meta.py next to this file, loaded by path; the names are taken over here, so this file reads as
one provider.

Verbs (JSON on stdout, diagnostics on stderr, input by flags, no prompt):
  capabilities --platform whatsapp-cloud
  setup --phone-number-id <id> [--public-url https://<host>[:<port>][/<prefix>] | --public-host <host>]
        [--template <name> --template-language <code> | --no-template] [--port 8787] [--new-path]
                                      write the settings, print the callback URL and what must reach the local port (without
                                      either flag the hostname of the tailscale command is used, when that command is found)
  whoami [--seconds 120]              print, in the terminal, the phone digits and the business-scoped user id of whoever
                                      writes to the number meanwhile; refuses while a bridge runs
  listen --platform whatsapp-cloud    the long-lived verb (the protocol of providers/messenger/README.md)
  receive, send, ack                  exit 2: whatsapp-cloud works only in listen mode

Secrets (read only through providers/secrets/resolver.py, never in an argument, a log, an output or an exception):
  MESSENGER_WHATSAPP_CLOUD_TOKEN         the system user's permanent token (store username messenger-whatsapp-cloud)
  MESSENGER_WHATSAPP_CLOUD_APP_SECRET    the app secret, used only to check the signature of a webhook call
  MESSENGER_WHATSAPP_CLOUD_VERIFY_TOKEN  the string typed in the app's webhook settings, used only for the handshake

State, under the state folder (OPENHORA_STATE_DIR, else an absolute XDG_STATE_HOME with /openhora, else
~/.local/state/openhora; the rule is written again here because a provider may not import runtime/), in whatsapp-cloud/
(mode 0700, every file 0600): settings.json (phone_number_id, port, template, template_language, webhook_path, public_base),
seen.json (the ids of messages already handled, 8 days), window.json (per chat: last_inbound and template_sent_at),
identities.json (business-scoped user id to phone digits, 30 days). The folder holds phone numbers: keep it out of backups.

Sources, read 2026-10-13: Meta's developer documentation for WhatsApp Business Platform (webhooks: create-webhook-endpoint,
overview, components; messages; business-scoped user ids; error codes; pricing; template categorization) and Tailscale's
(kb/1223 Funnel, kb/1153 HTTPS certificates, kb/1311 Serve and Funnel CLI).

Exit codes: 0 ok (also the end of stdin or SIGTERM in listen), 1 failed, 2 usage, 3 not configured (a secret or the settings
are missing, the token is refused, the port is taken).
"""
from __future__ import annotations

import argparse
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
import uuid

# The platforms this implementation serves. providers/resolve.py reads this one line as text, without importing the
# file, to choose among the implementations of messenger:<platform> (providers/CONTRACT.md).
PLATFORMS = ("whatsapp-cloud",)


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

SECRET_TOKEN, SECRET_APP, SECRET_VERIFY = ("MESSENGER_WHATSAPP_CLOUD_TOKEN", "MESSENGER_WHATSAPP_CLOUD_APP_SECRET",
                                           "MESSENGER_WHATSAPP_CLOUD_VERIFY_TOKEN")   # the names the resolver registers
KEYRING_USERNAMES = dict(zip((SECRET_TOKEN, SECRET_APP, SECRET_VERIFY),
                             ("messenger-whatsapp-cloud", "messenger-whatsapp-cloud-app-secret", "messenger-whatsapp-cloud-verify-token")))
GRAPH_BASE = "https://graph.facebook.com/v25.0"
CAPABILITIES = {"max_text": 4096, "buttons": True, "max_buttons": 3, "max_button_label": 20, "lists": False,
                "max_list_rows": 0, "url_buttons": False, "reply_context": True, "documents": True, "listen": True}
FOLDER = "whatsapp-cloud"
PHONE_NUMBER_ID = re.compile(r"[0-9]{5,25}")
TEMPLATE_NAME = re.compile(r"[a-z0-9_]{1,512}")
TEMPLATE_LANGUAGE = re.compile(r"[a-z]{2,3}(?:_[A-Za-z]{2,4})?")
GRAPH_TIMEOUT, UPLOAD_TIMEOUT = 10.0, 20.0
TEXT_LIMIT, BODY_LIMIT, ID_LIMIT = 4096, 1024, 256
DOCUMENT_LIMIT = 1_000_000
CODE_WINDOW, CODE_RATE, CODE_RATE_2 = 131047, 130429, 131056
CODE_TOKEN = (190, 0)                           # the token expired or is refused (0 is an authentication exception)
NOT_LISTEN = "whatsapp-cloud works only in listen mode"


class GraphError(ApiError):
    """A Graph API call that failed. `status` is the HTTP status (0: no answer), `code` Meta's error code. The text is built
    from these two numbers only, never from the answer."""

    def __init__(self, status: int, code=None, what: str = ""):
        refused = status == 401 or code in CODE_TOKEN
        text = what or (f"WhatsApp answered {status}" + (f" (error {code})" if code is not None else ""))
        super().__init__(text, status, code, refused)


# --- secrets ----------------------------------------------------------------------------------------------------------


def secret_resolver():
    """The workbench's secret resolver, by path: next to this file first (a copy), then providers/secrets/resolver.py."""
    return meta.secret_resolver()


def load_secrets(names=(SECRET_TOKEN, SECRET_APP, SECRET_VERIFY), resolver=None) -> dict:
    """{name: value} for each name; a ProviderError (not-configured) naming every missing or malformed one."""
    return meta.load_secrets(names, KEYRING_USERNAMES, resolver or secret_resolver())


# --- the state folder (the rule of runtime/messaging_ledger.py, written again in whatsapp_meta.py: a provider may not import
# runtime/) ---------------------------------------------------------------------------------------------------------------


def own_folder() -> str:
    return provider_folder(FOLDER, "WhatsApp Cloud folder")


# --- the settings -----------------------------------------------------------------------------------------------------

def check_settings(found) -> dict:
    """The settings, validated; a not-configured ProviderError naming the first thing wrong."""
    if not isinstance(found, dict):
        raise ProviderError("settings.json is not an object; run setup again", EXIT_NOT_CONFIGURED, "not-configured")
    port = found.get("port")
    checks = (("phone_number_id", isinstance(found.get("phone_number_id"), str) and PHONE_NUMBER_ID.fullmatch(found["phone_number_id"])),
              ("port", type(port) is int and 1 <= port <= 65535),
              ("template", found.get("template") is None or (isinstance(found.get("template"), str)
                                                              and TEMPLATE_NAME.fullmatch(found["template"]))),
              ("template_language", found.get("template_language") is None
               or (isinstance(found.get("template_language"), str) and TEMPLATE_LANGUAGE.fullmatch(found["template_language"]))),
              ("template and template_language (both, or neither)",
               (found.get("template") is None) == (found.get("template_language") is None)),
              ("public_base", found.get("public_base") is None or parse_public_url(found.get("public_base")) == found.get("public_base")),
              ("webhook_path", isinstance(found.get("webhook_path"), str) and WEBHOOK_PATH.fullmatch(found["webhook_path"])))
    for name, ok in checks:
        if not ok:
            raise ProviderError(f"settings.json has a missing or malformed {name}; run setup again", EXIT_NOT_CONFIGURED,
                                "not-configured")
    kept = {k: found.get(k) for k in ("phone_number_id", "port", "template", "template_language", "webhook_path")}
    if found.get("public_base") is not None:        # the address given to setup, kept so that a later setup needs no flag
        kept["public_base"] = found["public_base"]
    return kept


def load_settings(folder: str) -> dict:
    path = os.path.join(folder, SETTINGS)
    if not os.path.isfile(path):
        raise ProviderError(f"no settings; run: python3 providers/messenger/whatsapp-cloud.py setup (see the README)",
                            EXIT_NOT_CONFIGURED, "not-configured")
    return check_settings(read_json(path, {}))


# --- the state --------------------------------------------------------------------------------------------------------


class Store(meta.Store):
    """What survives a restart (whatsapp_meta.Store); the bound on the ids kept is this module's SEEN_MAX."""

    def seen_max(self) -> int:
        return SEEN_MAX


# --- rendering --------------------------------------------------------------------------------------------------------
# The same rules as renderWhatsApp in providers/messenger/whatsapp/render.go, on a shared corpus (tests/whatsapp_render_corpus.json);
# the code is in whatsapp_meta.py.


def render_whatsapp_cloud(text: str) -> str:
    """The bridge's Markdown as WhatsApp shows it, within the Cloud API's 4096 characters."""
    return render_whatsapp(text, RENDER_LIMIT)


# --- the Graph API ----------------------------------------------------------------------------------------------------


class RefuseRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow a redirect: urllib would forward the Authorization header to wherever it points."""

    def redirect_request(self, req, fp, code, msg, hdrs, newurl):
        fp.close()
        raise GraphError(code, None, f"refusing to follow a {code} redirect: the request carries the token")


OPENER = urllib.request.build_opener(RefuseRedirect)


class Graph:
    """The Graph API with the standard library. Every failure is a GraphError built from numbers only."""

    def __init__(self, token: str, phone_number_id: str, opener=None, base: str = GRAPH_BASE):
        self.token, self.phone, self.opener, self.base = token, phone_number_id, opener or OPENER, base

    def call(self, method: str, path: str, body=None, raw=None, content_type="application/json", timeout=GRAPH_TIMEOUT):
        data = raw if raw is not None else (None if body is None else json.dumps(body).encode("utf-8"))
        headers = {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = content_type
        request = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        try:
            with self.opener.open(request, timeout=timeout) as response:
                answer = response.read(MAX_ANSWER)
        except urllib.error.HTTPError as e:
            code = None
            try:
                parsed = json.loads(e.read(65536).decode("utf-8"))
                found = parsed.get("error", {}).get("code") if isinstance(parsed, dict) and isinstance(parsed.get("error"), dict) else None
                code = found if type(found) is int else None
            except Exception:  # an unreadable body is only a missing code
                pass
            raise GraphError(e.code, code) from None
        except GraphError:
            raise
        except urllib.error.URLError as e:
            raise GraphError(0, None, f"WhatsApp could not be reached ({type(getattr(e, 'reason', e)).__name__})") from None
        except (OSError, ValueError, http.client.HTTPException) as e:
            raise GraphError(0, None, f"the call to WhatsApp failed ({type(e).__name__})") from None
        try:
            parsed = json.loads(answer.decode("utf-8")) if answer else {}
        except ValueError:
            raise GraphError(0, None, "WhatsApp's answer was not JSON") from None
        return parsed if isinstance(parsed, dict) else {}

    def post_message(self, body: dict) -> str:
        sent = self.call("POST", f"/{self.phone}/messages", body)
        messages = sent.get("messages")
        found = messages[0].get("id") if isinstance(messages, list) and messages and isinstance(messages[0], dict) else None
        if not isinstance(found, str) or not found:
            raise GraphError(0, None, "WhatsApp did not return the id of the message")
        return found

    def check(self) -> None:
        self.call("GET", f"/{self.phone}?fields=id")

    def upload(self, name: str, text: str) -> str:
        boundary = "wb" + uuid.uuid4().hex
        parts = [(f'--{boundary}\r\nContent-Disposition: form-data; name="messaging_product"\r\n\r\nwhatsapp\r\n'
                  f'--{boundary}\r\nContent-Disposition: form-data; name="type"\r\n\r\ntext/plain\r\n'
                  f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\n'
                  "Content-Type: text/plain\r\n\r\n").encode("utf-8"), text.encode("utf-8"),
                 f"\r\n--{boundary}--\r\n".encode("utf-8")]
        done = self.call("POST", f"/{self.phone}/media", raw=b"".join(parts),
                         content_type=f"multipart/form-data; boundary={boundary}", timeout=UPLOAD_TIMEOUT)
        media = done.get("id")
        if not isinstance(media, str) or not media:
            raise GraphError(0, None, "WhatsApp did not return the id of the document")
        return media


def text_body(to: str, text: str, reply_to=None) -> dict:
    body = {"messaging_product": "whatsapp", "recipient_type": "individual", "to": to, "type": "text",
            "text": {"body": text, "preview_url": False}}
    if reply_to:
        body["context"] = {"message_id": reply_to}
    return body



def buttons_body(to: str, text: str, actions: list, reply_to=None) -> dict:
    body = {"messaging_product": "whatsapp", "recipient_type": "individual", "to": to, "type": "interactive",
            "interactive": {"type": "button", "body": {"text": text},
                            "action": {"buttons": [{"type": "reply", "reply": {"id": a["id"], "title": t}}
                                                   for a, t in zip(actions, button_titles(actions))]}}}
    if reply_to:
        body["context"] = {"message_id": reply_to}
    return body


def template_body(to: str, name: str, language: str) -> dict:
    return {"messaging_product": "whatsapp", "recipient_type": "individual", "to": to, "type": "template",
            "template": {"name": name, "language": {"code": language}}}


def document_body(to: str, media: str, filename: str, reply_to=None) -> dict:
    body = {"messaging_product": "whatsapp", "recipient_type": "individual", "to": to, "type": "document",
            "document": {"id": media, "filename": filename}}
    if reply_to:
        body["context"] = {"message_id": reply_to}
    return body


def document_name(name: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", name)[:60] or "document"
    return safe if safe.endswith((".txt", ".md")) else safe + ".txt"




def check_message(message) -> dict:
    """The neutral message, checked against the capabilities: a usage error (exit 2) when it does not fit."""
    return meta.check_message(message, max_text=CAPABILITIES["max_text"], max_buttons=CAPABILITIES["max_buttons"],
                              id_limit=ID_LIMIT, documents=True, document_limit=DOCUMENT_LIMIT)


# --- sending ----------------------------------------------------------------------------------------------------------


class Sender(meta.BaseSender):
    """The send side: the window gate, the template, the messages. `sent` remembers the ids this process sent, to match a
    late failure report (error 131047 arrives in a webhook status, usually after the API accepted the message)."""

    platform = "whatsapp-cloud"

    def __init__(self, graph: Graph, store: Store, settings: dict, log, clock=time.time):
        super().__init__(store, log, clock)
        self.graph, self.settings = graph, settings

    def has_template(self) -> bool:
        return bool(self.settings.get("template"))

    def post_template(self, to: str) -> str:
        return self.graph.post_message(template_body(to, self.settings["template"], self.settings["template_language"]))

    def send(self, chat: str, message: dict) -> str:
        """Send the card or text; the id of the message that carries the text. Raises Deferred when the window is closed."""
        to = self.recipient(chat)
        now = self.clock()
        if not self.store.window_open(chat, now):
            self.defer(chat, to)
        rendered = render_whatsapp_cloud(message["text"])
        actions = message.get("actions") or []
        reply_to = message.get("reply_to")
        try:
            if actions and len(rendered) <= BODY_LIMIT:
                first = self.graph.post_message(buttons_body(to, rendered, actions, reply_to))
                follow = []
            else:
                first = self.graph.post_message(text_body(to, rendered, reply_to))
                follow = [("buttons", lambda: self.graph.post_message(buttons_body(to, BUTTONS_LINE, actions, first)))] if actions else []
        except GraphError as e:
            if e.error_code == CODE_WINDOW:
                self.store.close_window(chat, now)
                self.persist()
                self.defer(chat, to)
            raise
        self.remember_sent(first, chat, now)
        document = message.get("document")
        if document:
            follow.append(("document", lambda: self.graph.post_message(
                document_body(to, self.graph.upload(document_name(document["name"]), document["text"]),
                              document_name(document["name"]), first))))
        document_failed = False
        for what, step in follow:
            try:
                got = step()
                self.remember_sent(got, chat, now)
                if what == "buttons":
                    self.set_alias(got, first)
            except GraphError as e:
                if e.kind == "not-configured":
                    raise
                # the text is delivered: failing the send would make the bridge send it twice
                self.log(f"the {what} after the text could not be sent ({e.status}, {e.error_code})")
                document_failed = document_failed or what == "document"
        return meta.SentId(first, document_failed)      # a str: the id; `document_failed` says the document did not go out


# --- the webhook ------------------------------------------------------------------------------------------------------


def signature_ok(app_secret: str, body: bytes, header) -> bool:
    """X-Hub-Signature-256 is `sha256=` and the HMAC-SHA256 of the raw body in hex. Compared on bytes, in constant time."""
    if not isinstance(header, str):
        return False
    expected = b"sha256=" + hmac.new(app_secret.encode("utf-8"), body, hashlib.sha256).hexdigest().encode("ascii")
    return hmac.compare_digest(expected, header.encode("latin-1", "replace"))


class Webhook(meta.HookBase):
    """What the server does with a call: the handshake, the signature, the payload. `emit(update)` takes an update; `late`
    takes the id of a message this process sent that Meta reports as failed for a closed window."""

    # GET: the handshake
    def handshake(self, query: str):
        """(status, body): 200 with the challenge when the mode is subscribe and the verify token is right, else 403."""
        found = urllib.parse.parse_qs(query, keep_blank_values=True, max_num_fields=20)
        one = lambda k: (found.get(k) or [None])[0] if len(found.get(k) or []) == 1 else None
        mode, token, challenge = one("hub.mode"), one("hub.verify_token"), one("hub.challenge")
        good = isinstance(token, str) and hmac.compare_digest(token.encode("utf-8", "replace"),
                                                              self.secrets[SECRET_VERIFY].encode("utf-8"))
        if mode != "subscribe" or not good:
            self.note("handshake", "webhook: a handshake was refused")
            return 403, b""
        if not isinstance(challenge, str) or not re.fullmatch(r"[A-Za-z0-9._~-]{1,256}", challenge):
            return 400, b""
        return 200, challenge.encode("ascii")

    def handle_get(self, query: str):
        return self.handshake(query)

    def handle_post(self, headers, query: str, body: bytes):
        return self.post(body, headers.get("X-Hub-Signature-256")), b"", None

    # POST: a signed payload
    def post(self, body: bytes, header) -> int:
        if not self.accepting:
            return 503           # not ready: nothing is marked seen, so Meta's retry is handled after the token check
        if not signature_ok(self.secrets[SECRET_APP], body, header):
            self.note("signature", "webhook: a call with a missing or wrong signature was refused")
            return 401
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, RecursionError):
            self.note("unparsable", "webhook: a signed call was not JSON; ignored")
            return 200
        try:
            self.process(payload)
        except Exception as e:  # Meta retries on a 500; what was emitted is deduplicated by id (in memory as well as on disk)
            self.note("processing", f"webhook: processing failed ({type(e).__name__})")
            return 500
        return 200

    def process(self, payload) -> None:
        for entry in as_list(as_dict(payload).get("entry")):
            for change in as_list(as_dict(entry).get("changes")):
                value = as_dict(as_dict(change).get("value"))
                if as_dict(value.get("metadata")).get("phone_number_id") != self.settings["phone_number_id"]:
                    continue
                for status in as_list(value.get("statuses")):
                    self.status(as_dict(status))
                for message in as_list(value.get("messages")):
                    self.message(as_dict(message))
        self.store.flush()      # a failure is an OSError: the caller answers 500 and Meta retries (the retry is deduplicated in memory)

    def status(self, status: dict) -> None:
        if status.get("status") != "failed":
            return
        wamid = status.get("id")
        if not isinstance(wamid, str) or self.sent_info(wamid) is None:
            return
        if any(as_dict(e).get("code") == CODE_WINDOW for e in as_list(status.get("errors"))):
            self.late(wamid)

    def identity(self, message: dict):
        return self.identity_of(message.get("from"), message.get("from_user_id"))

    def when(self, message: dict) -> float:
        now = self.clock()
        stamp = message.get("timestamp")
        if isinstance(stamp, str) and stamp.isascii() and stamp.isdigit() and len(stamp) <= 12:
            return min(float(stamp), now + CLOCK_SKEW)
        return now

    def message(self, message: dict) -> None:
        wamid = message.get("id")
        if not isinstance(wamid, str) or not wamid or len(wamid) > 512 or self.store.is_seen(wamid):
            return
        kind = message.get("type")
        text = action = None
        if kind == "text":
            body = as_dict(message.get("text")).get("body")
            if not isinstance(body, str) or not body.strip():
                return
            text = body
        elif kind == "interactive":
            reply = as_dict(message.get("interactive"))
            if reply.get("type") != "button_reply" or not isinstance(as_dict(reply.get("button_reply")).get("id"), str):
                return
            action = reply["button_reply"]["id"]
        elif kind == "button":
            text = "/pending"        # a tap on the template's quick reply: the person wants the cards
        else:
            return
        chat, uid = self.identity(message)
        if chat is None:
            return
        context = as_dict(message.get("context")).get("id")
        reply_to = self.alias(context) if isinstance(context, str) and context and kind != "button" else None
        self.store.note_inbound(chat, self.when(message))        # before the update: the bridge's reply must find the window open
        self.emit({"update_id": wamid, "sender": chat, "chat": chat, "private": True, "text": text, "action": action,
                   "action_ref": None, "reply_to": reply_to}, uid)
        self.store.mark_seen(wamid)


# --- the listen mode --------------------------------------------------------------------------------------------------


class Listener(meta.Listener):
    """One listen process: the webhook server, the sender thread and the stdin reader share this object."""

    refused_reason = "WhatsApp refused the token"
    refused_fatal = "WhatsApp refused the token: store a new one"
    rate_codes = (CODE_RATE, CODE_RATE_2)

    def __init__(self, settings: dict, secrets: dict, store: Store, *, graph=None, **options):
        super().__init__(settings, secrets, store, max_body=MAX_BODY, **options)
        self.graph = graph or Graph(secrets[SECRET_TOKEN], settings["phone_number_id"])
        self.sender = Sender(self.graph, store, settings, self.log, self.clock)

    def check(self, message) -> dict:
        return check_message(message)

    def make_hook(self):
        return Webhook(self.settings, self.secrets, self.store, self.emit, late=lambda wamid: self.requests.put(("late", wamid)),
                       sent_info=self.sender.sent_info, note=self.note, clock=self.clock, alias=self.sender.alias_of)

    def startup(self) -> None:
        """The token is checked while the server already listens; `ready` is written when it works."""
        try:
            self.graph.check()
        except GraphError as e:
            if e.kind == "not-configured" or e.status in (400, 403):
                self.fatal(EXIT_NOT_CONFIGURED, "not-configured", "WhatsApp refused the token or the phone number id: check "
                           f"{SECRET_TOKEN} and the settings (error {e.error_code if e.error_code is not None else e.status})")
            else:
                self.fatal(EXIT_SERVICE, "failed", "could not check the token with WhatsApp; the bridge will start this again")
            return
        if self.stop.is_set():
            return
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
    return meta.take_lock(state, "whatsapp-cloud")

def cmd_setup(args) -> int:
    if args.port is not None and not 1 <= args.port <= 65535:
        say("--port is a number from 1 to 65535")
        return EXIT_USAGE
    if args.no_template and (args.template or args.template_language):
        say("--no-template cannot be combined with --template or --template-language")
        return EXIT_USAGE
    folder = own_folder()
    path = os.path.join(folder, SETTINGS)
    current = read_json(path, {})
    if args.no_template:
        template, language = None, None
    else:
        template = args.template or current.get("template")
        language = args.template_language or current.get("template_language")
    chosen = {"phone_number_id": args.phone_number_id or current.get("phone_number_id"),
              "port": args.port if args.port is not None else current.get("port", DEFAULT_PORT),
              "template": template,
              "template_language": language,
              "webhook_path": current.get("webhook_path")}
    if args.new_path or not (isinstance(chosen["webhook_path"], str) and WEBHOOK_PATH.fullmatch(chosen["webhook_path"])):
        chosen["webhook_path"] = randomness.token_hex(16)
    try:
        settings = check_settings(chosen)
    except ProviderError as e:
        say(str(e).replace("; run setup again", "") + ": give --phone-number-id, and --template with --template-language (or neither, for no reminder template)")
        return EXIT_USAGE
    saved = current.get("public_base")
    base, used_tailscale, problem = choose_public_base(args.public_url, args.public_host, funnel=funnel_host,
                                                       saved=saved if parse_public_url(saved) == saved else None)
    if problem:
        say(problem)
        return EXIT_USAGE
    settings["public_base"] = base
    write_private_json(path, settings)
    url = f"{base}/{settings['webhook_path']}"
    print(f"Settings written to {path} (mode 0600).\n"
          f"Callback URL for the app's webhook settings: {url}\n"
          f"Verify token: the value of {SECRET_VERIFY} (type the same string in the app's webhook settings).\n"
          + expose_lines(base, settings, used_tailscale)
          + "Subscribe the app to `messages` in the webhook settings. If the public address changes, run setup again and update the "
            "callback URL in Meta.\n"
          + (f"Outside the 24-hour window the provider sends the template {settings['template']} ({settings['template_language']})."
             if settings["template"] else
             "No reminder template: after 24 hours of silence the person must write first; the cards wait until then."))
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
    secrets = load_secrets((SECRET_APP, SECRET_VERIFY))
    lock = take_lock(state_dir())
    if lock is None:
        return EXIT_USAGE
    stop = threading.Event()

    def show(update, uid):
        print(f"digits: {update['sender'] if PHONE.fullmatch(update['sender']) else '-'}   business-scoped user id: {uid or '-'}",
              flush=True)
    hook = Webhook(settings, secrets, Store(None), show, note=Notes(say))
    try:
        server = Server(settings["port"], hook)
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
    print(json.dumps(CAPABILITIES))
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
    setup.add_argument("--phone-number-id")
    setup.add_argument("--public-url")
    setup.add_argument("--public-host")
    setup.add_argument("--port", type=int)
    setup.add_argument("--template")
    setup.add_argument("--template-language")
    setup.add_argument("--no-template", action="store_true")
    setup.add_argument("--new-path", action="store_true")
    setup.set_defaults(func=cmd_setup)
    who = sub.add_parser("whoami")
    who.add_argument("--seconds", type=int, default=120)
    who.set_defaults(func=cmd_whoami)
    for name in ("receive", "send", "ack"):
        one = sub.add_parser(name)
        one.set_defaults(func=cmd_one_shot)
        for flag in ("--offset", "--timeout", "--chat", "--message-file", "--action-ref"):
            one.add_argument(flag)
    for parser in sub.choices.values():
        parser.add_argument("--platform", default="whatsapp-cloud", choices=PLATFORMS)
    return p



def main(argv=None) -> int:
    return meta.run_cli(build_parser, argv)


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)  # daemon threads may still be in a network call; the process ends now, within the 5 seconds
