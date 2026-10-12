#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["keyring==25.7.0"]
# ///
"""Messenger provider for Telegram: an implementation of the class messenger:<platform> for the platform telegram. It
receives what a person sends to a bot and sends the bridge's neutral messages back, with the Bot API over HTTPS and
the standard library (providers/messenger/README.md holds the interface every messenger implements).

Sources (the Bot API reference, https://core.telegram.org/bots/api, read 2026-10-11): getUpdates (long polling,
`offset`, `timeout`, `allowed_updates`; the answer is an array of Update, and an Update that is acknowledged by a
later offset is not delivered again), sendMessage (`chat_id`, `text` of 1 to 4096 characters, `reply_markup`,
InlineKeyboardMarkup of InlineKeyboardButton with `text` and either `callback_data` of 1 to 64 bytes or `url`),
sendDocument (multipart/form-data, `document`, `reply_to_message_id`), answerCallbackQuery (`callback_query_id`),
getMe, and the rule that getUpdates cannot be used while a webhook is set (the service answers 409).

Verbs (JSON on stdout, diagnostics on stderr, input by flags or files, no prompt):
  capabilities --platform telegram
  receive --platform telegram --offset <n> --timeout <seconds>
  send --platform telegram --chat <id> --message-file <f>
  ack --platform telegram --action-ref <ref>
  --check --platform telegram         verify the token with getMe; exit 0 ready, 3 not configured

The message file is the neutral message {"text", "actions": [{"id", "label"}], "link": {"label", "url"} | null,
"document": {"name", "text"} | null}. The text is sent as plain text: no parse mode is ever set, so nothing a project
wrote is read as markup. An action becomes a row of the inline keyboard whose button carries the action id as
`callback_data`; a link becomes a last row with a URL button. A document is sent after the message, as a reply to it,
so that the message id this verb prints is the one of the message a person replies to. The verb refuses (exit 2) a
message beyond the capabilities it prints: the bridge reads them first and never sends one.

The bot's token is the secret MESSENGER_TELEGRAM_BOT_TOKEN, read only through providers/secrets/resolver.py (the
environment, else the OS secret store, username messenger-telegram). Telegram carries the token in the request path,
so every error is built from the exception's class, the HTTP status and the service's own description, with the
token and anything shaped like one removed; the token is in no argument, no log, no stdout and no traceback. No
redirect is followed. A request has a timeout. A verb never retries.

Environment:
  MESSENGER_TELEGRAM_BOT_TOKEN        the bot's token (never printed)
  MESSENGER_TELEGRAM_API_BASE         tests only: a loopback URL that replaces https://api.telegram.org; the secret
                                      store is then never read

Exit codes: 0 ok, 1 failed (the service answered an error, or could not be reached), 2 usage (also a message beyond
the capabilities), 3 not configured (no token, a token the service rejects, a webhook is set,
another program is reading this bot's updates: both 409 answers of getUpdates, each with its own sentence; the provider
has no exit 4, see providers/CONTRACT.md).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

# The platforms this implementation serves. providers/resolve.py reads this one line as text, without importing the
# file, to choose among the implementations of messenger:<platform> (providers/CONTRACT.md).
PLATFORMS = ("telegram",)

SECRET = "MESSENGER_TELEGRAM_BOT_TOKEN"
KEYRING_USERNAME = "messenger-telegram"
ENV_BASE = "MESSENGER_TELEGRAM_API_BASE"
DEFAULT_API_BASE = "https://api.telegram.org"
EXIT_OK, EXIT_SERVICE, EXIT_USAGE, EXIT_NOT_CONFIGURED = 0, 1, 2, 3
CAPABILITIES = {"max_text": 4096, "buttons": True, "max_buttons": 6, "max_button_label": 40, "lists": False,
                "max_list_rows": 0, "url_buttons": True, "reply_context": True, "documents": True}
CALLBACK_DATA_BYTES = 64
HTTP_MARGIN_SECONDS = 15
SEND_TIMEOUT_SECONDS = 30
MAX_POLL_SECONDS = 50
ALLOWED_UPDATES = ["message", "callback_query"]
WEBHOOK_SENTENCE = ("a webhook is set for this bot, so Telegram will not hand its messages to a poll: remove it "
                    "(the Bot API method deleteWebhook, called once for this bot) and run the bridge again")
CONFLICT_SENTENCE = ("another program is reading this bot's updates (a second bridge, or another tool with the same "
                     "token): stop it, then run the bridge again")
TOKEN_SHAPE = re.compile(r"\d{5,}:[A-Za-z0-9_-]{10,}")
CHAT_ID = re.compile(r"-?\d{1,20}")


class ProviderError(Exception):
    def __init__(self, message: str, code: int = EXIT_SERVICE):
        super().__init__(message)
        self.code = code


def redact(text, token: str = "") -> str:
    """The text with the token, and anything shaped like one, replaced."""
    out = str(text)
    if token:
        out = out.replace(token, "<token>")
    return TOKEN_SHAPE.sub("<token>", out)


def secret_resolver():
    """The workbench's secret resolver, by path: next to this file first (a copy), then providers/secrets/resolver.py."""
    here = Path(__file__).resolve()
    path = next((c for c in (here.parent / "resolver.py", here.parents[1] / "secrets" / "resolver.py") if c.is_file()), None)
    if path is None:
        raise ProviderError("providers/secrets/resolver.py is not next to this script nor in the workbench",
                            EXIT_NOT_CONFIGURED)
    spec = importlib.util.spec_from_file_location("workbench_secret_resolver", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def api_base() -> tuple:
    """(base URL, test mode). The override is for tests and must be a loopback URL."""
    override = os.environ.get(ENV_BASE)
    if not override:
        return DEFAULT_API_BASE, False
    host = urllib.parse.urlparse(override).hostname
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise ProviderError(f"{ENV_BASE} is for tests only and must be a loopback URL such as http://127.0.0.1:8080",
                            EXIT_USAGE)
    return override.rstrip("/"), True


def load_token(test_mode: bool) -> str:
    found = secret_resolver().resolve(SECRET, allow_store=not test_mode)
    token = found[0] if found else ""
    if not token:
        raise ProviderError(f"no Telegram bot token: export {SECRET}, or store one with "
                            f"uv run --with keyring==25.7.0 keyring set openhora {KEYRING_USERNAME}", EXIT_NOT_CONFIGURED)
    if not re.fullmatch(r"[A-Za-z0-9:_-]+", token):
        raise ProviderError("the Telegram bot token has characters a token does not have", EXIT_NOT_CONFIGURED)
    return token


class RefuseRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow a redirect: every request carries the token in its path."""

    def redirect_request(self, req, fp, code, msg, hdrs, newurl):
        fp.close()
        raise ProviderError(f"refusing to follow a {code} redirect: the request carries the bot's token", EXIT_SERVICE)


OPENER = urllib.request.build_opener(RefuseRedirect)


def call(method: str, fields: dict, token: str, base: str, timeout: float, body: bytes | None = None,
         content_type: str = "application/json") -> dict:
    """One Bot API method; the `result` of an `ok` answer. Every failure is a ProviderError whose text holds no token."""
    data = body if body is not None else json.dumps(fields).encode("utf-8")
    request = urllib.request.Request(f"{base}/bot{token}/{method}", data=data, method="POST",
                                     headers={"Content-Type": content_type})
    try:
        with OPENER.open(request, timeout=timeout) as response:
            answer = response.read()
    except urllib.error.HTTPError as e:
        raise _http_error(method, e, token) from None
    except ProviderError:
        raise
    except urllib.error.URLError as e:
        raise ProviderError(f"Telegram {method}: could not be reached ({type(getattr(e, 'reason', e)).__name__})",
                            EXIT_SERVICE) from None
    except (OSError, ValueError) as e:
        raise ProviderError(f"Telegram {method}: the call failed ({type(e).__name__})", EXIT_SERVICE) from None
    try:
        parsed = json.loads(answer.decode("utf-8"))
    except ValueError:
        raise ProviderError(f"Telegram {method}: the answer was not JSON", EXIT_SERVICE) from None
    if not isinstance(parsed, dict) or parsed.get("ok") is not True:
        raise ProviderError(f"Telegram {method}: the service did not accept the call", EXIT_SERVICE)
    return parsed.get("result")


def _http_error(method: str, error, token: str) -> ProviderError:
    status = getattr(error, "code", 0)
    description = ""
    try:
        parsed = json.loads(error.read().decode("utf-8"))
        description = str(parsed.get("description") or "") if isinstance(parsed, dict) else ""
    except Exception:  # an unreadable body is only a missing description
        description = ""
    description = redact(description, token)[:200]
    if status == 409 and method == "getUpdates":
        said = description.lower()
        if "terminated" in said and "getupdates" in said and "webhook" not in said:  # another getUpdates request took the stream
            return ProviderError(f"Telegram answered 409: {CONFLICT_SENTENCE}", EXIT_NOT_CONFIGURED)
        return ProviderError(f"Telegram answered 409: {WEBHOOK_SENTENCE}", EXIT_NOT_CONFIGURED)  # a 409 matching neither text keeps this sentence (old behaviour)
    if status in (401, 404):
        return ProviderError(f"Telegram refused the bot token ({status}): store a valid one", EXIT_NOT_CONFIGURED)
    return ProviderError(f"Telegram {method} answered {status}" + (f": {description}" if description else ""), EXIT_SERVICE)


def _text(value) -> str | None:
    return value if isinstance(value, str) and value else None


def mapped(update: dict) -> dict | None:
    """The neutral update of a Telegram Update: a text message or a tapped button; None for anything else."""
    if not isinstance(update, dict) or not isinstance(update.get("update_id"), int):
        return None
    out = {"update_id": update["update_id"], "text": None, "action": None, "action_ref": None, "reply_to": None}
    message = update.get("message")
    query = update.get("callback_query")
    if isinstance(message, dict):
        sender, chat = message.get("from"), message.get("chat")
        out["text"] = _text(message.get("text"))
        replied = message.get("reply_to_message")
        if isinstance(replied, dict) and isinstance(replied.get("message_id"), int):
            out["reply_to"] = str(replied["message_id"])
        if out["text"] is None:
            return None
    elif isinstance(query, dict):
        sender = query.get("from")
        chat = (query.get("message") or {}).get("chat") if isinstance(query.get("message"), dict) else None
        out["action"], out["action_ref"] = _text(query.get("data")), _text(query.get("id"))
        if out["action"] is None:
            return None
    else:
        return None
    if not isinstance(sender, dict) or not isinstance(chat, dict) or "id" not in sender or "id" not in chat:
        return None
    out.update(sender=str(sender["id"]), chat=str(chat["id"]), private=chat.get("type") == "private")
    return out


def receive(offset: int, timeout: int, token: str, base: str) -> dict:
    timeout = max(0, min(int(timeout), MAX_POLL_SECONDS))
    result = call("getUpdates", {"offset": offset, "timeout": timeout, "allowed_updates": ALLOWED_UPDATES}, token, base,
                  timeout + HTTP_MARGIN_SECONDS)
    if not isinstance(result, list):
        raise ProviderError("Telegram getUpdates: the result was not a list", EXIT_SERVICE)
    ids = [u["update_id"] for u in result if isinstance(u, dict) and isinstance(u.get("update_id"), int)]
    updates = [m for m in (mapped(u) for u in result) if m is not None]
    return {"updates": updates, "next_offset": max(ids) + 1 if ids else offset}


def check_message(message) -> dict:
    """The neutral message, checked against the capabilities: a usage error (exit 2) when it does not fit."""
    if not isinstance(message, dict):
        raise ProviderError("the message file must hold a JSON object", EXIT_USAGE)
    text = message.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ProviderError("the message needs a text", EXIT_USAGE)
    if len(text) > CAPABILITIES["max_text"]:
        raise ProviderError(f"the text is {len(text)} characters; Telegram takes {CAPABILITIES['max_text']}", EXIT_USAGE)
    actions = message.get("actions") or []
    if not isinstance(actions, list) or len(actions) > CAPABILITIES["max_buttons"]:
        raise ProviderError(f"a message takes at most {CAPABILITIES['max_buttons']} actions", EXIT_USAGE)
    for action in actions:
        if not isinstance(action, dict) or not isinstance(action.get("id"), str) or not isinstance(action.get("label"), str) \
                or not action["id"] or not action["label"]:
            raise ProviderError("an action is {\"id\": text, \"label\": text}", EXIT_USAGE)
        if len(action["id"].encode("utf-8")) > CALLBACK_DATA_BYTES:
            raise ProviderError(f"an action id is at most {CALLBACK_DATA_BYTES} bytes (Telegram's callback_data)", EXIT_USAGE)
        if len(action["label"]) > CAPABILITIES["max_button_label"]:
            raise ProviderError(f"a button label is at most {CAPABILITIES['max_button_label']} characters", EXIT_USAGE)
    link = message.get("link")
    if link is not None:
        if not isinstance(link, dict) or not isinstance(link.get("label"), str) or not link["label"] \
                or not isinstance(link.get("url"), str) or not re.fullmatch(r"https?://[^\s]+", link["url"]):
            raise ProviderError("a link is {\"label\": text, \"url\": an http:// or https:// URL}", EXIT_USAGE)
        if len(link["label"]) > CAPABILITIES["max_button_label"]:
            raise ProviderError(f"a link label is at most {CAPABILITIES['max_button_label']} characters", EXIT_USAGE)
    document = message.get("document")
    if document is not None and (not isinstance(document, dict) or not isinstance(document.get("name"), str)
                                 or not isinstance(document.get("text"), str) or not document["text"]):
        raise ProviderError("a document is {\"name\": text, \"text\": text}", EXIT_USAGE)
    return message


def keyboard(message: dict) -> dict | None:
    rows = [[{"text": a["label"], "callback_data": a["id"]}] for a in message.get("actions") or []]
    if message.get("link"):
        rows.append([{"text": message["link"]["label"], "url": message["link"]["url"]}])
    return {"inline_keyboard": rows} if rows else None


def multipart(fields: dict, name: str, text: str) -> tuple:
    """(body, content type) of a sendDocument request: the fields, then one text file."""
    boundary = "wb" + uuid.uuid4().hex
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", name)[:60] or "document.txt"
    parts = []
    for key, value in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode("utf-8"))
    parts.append((f'--{boundary}\r\nContent-Disposition: form-data; name="document"; filename="{safe}"\r\n'
                  "Content-Type: text/plain; charset=utf-8\r\n\r\n").encode("utf-8") + text.encode("utf-8")
                 + f"\r\n--{boundary}--\r\n".encode("utf-8"))
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def send(chat: str, message: dict, token: str, base: str) -> dict:
    if not CHAT_ID.fullmatch(chat):
        raise ProviderError("--chat is a Telegram chat id: whole digits, with a leading minus for a group", EXIT_USAGE)
    message = check_message(message)
    fields = {"chat_id": int(chat), "text": message["text"]}  # no parse_mode: the text is plain text
    markup = keyboard(message)
    if markup:
        fields["reply_markup"] = markup
    sent = call("sendMessage", fields, token, base, SEND_TIMEOUT_SECONDS)
    if not isinstance(sent, dict) or not isinstance(sent.get("message_id"), int):
        raise ProviderError("Telegram sendMessage: the result had no message id", EXIT_SERVICE)
    document = message.get("document")
    if document:
        body, kind = multipart({"chat_id": chat, "reply_to_message_id": sent["message_id"]}, document["name"], document["text"])
        try:
            call("sendDocument", {}, token, base, SEND_TIMEOUT_SECONDS, body=body, content_type=kind)
        except ProviderError as e:  # the card went out: its id is still printed, so the bridge records it and never resends
            print(f"warning: the message was sent and its document was not ({redact(e, token)})", file=sys.stderr)
            return {"message_id": str(sent["message_id"]), "document_failed": True}
    return {"message_id": str(sent["message_id"])}


def ack(action_ref: str, token: str, base: str) -> dict:
    if not action_ref or len(action_ref) > 200:
        raise ProviderError("--action-ref is the reference a received update carried", EXIT_USAGE)
    call("answerCallbackQuery", {"callback_query_id": action_ref}, token, base, SEND_TIMEOUT_SECONDS)
    return {"acked": True}


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--check", action="store_true", help="verify the token with getMe; exit 0 ready, 3 not configured")
    p.add_argument("--platform")
    sub = p.add_subparsers(dest="verb")
    for name in ("capabilities", "receive", "send", "ack"):
        s = sub.add_parser(name)
        s.add_argument("--platform", default=argparse.SUPPRESS)
        if name == "receive":
            s.add_argument("--offset", type=int, default=0)
            s.add_argument("--timeout", type=int, default=0)
        if name == "send":
            s.add_argument("--chat", required=True)
            s.add_argument("--message-file", required=True)
        if name == "ack":
            s.add_argument("--action-ref", required=True)
    return p


def run(argv) -> int:
    args = parser().parse_args(argv)
    if args.platform != "telegram":
        raise ProviderError("this implementation serves --platform telegram", EXIT_USAGE)
    if not args.check and not args.verb:
        raise ProviderError("give a verb: capabilities, receive, send or ack (see --help)", EXIT_USAGE)
    if args.verb == "capabilities":
        print(json.dumps(CAPABILITIES))
        return EXIT_OK
    message = None
    if args.verb == "send":
        try:
            with open(args.message_file, encoding="utf-8") as f:
                message = json.load(f)
        except (OSError, ValueError):
            raise ProviderError("--message-file must name a JSON file", EXIT_USAGE) from None
        check_message(message)
    base, test_mode = api_base()
    token = load_token(test_mode)
    try:
        if args.check:
            call("getMe", {}, token, base, SEND_TIMEOUT_SECONDS)
            print(json.dumps({"ok": True}))
        elif args.verb == "receive":
            print(json.dumps(receive(args.offset, args.timeout, token, base)))
        elif args.verb == "send":
            print(json.dumps(send(args.chat, message, token, base)))
        else:
            print(json.dumps(ack(args.action_ref, token, base)))
    except ProviderError as e:
        raise ProviderError(redact(e, token), e.code) from None
    return EXIT_OK


def main(argv=None) -> int:
    try:
        return run(sys.argv[1:] if argv is None else argv)
    except ProviderError as e:
        print(f"error: {redact(e)}", file=sys.stderr)
        return e.code
    except SystemExit:
        raise
    except BaseException as e:  # nothing else may print a traceback: a request's URL holds the token
        print(f"error: unexpected failure ({type(e).__name__})", file=sys.stderr)
        return EXIT_SERVICE


if __name__ == "__main__":
    sys.exit(main())
