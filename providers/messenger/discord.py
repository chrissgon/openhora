#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["keyring==25.7.0", "websockets==16.1.1"]
# ///
"""Messenger provider for Discord: an implementation of the class messenger:<platform> for the platform discord, with
buttons, through Discord's Gateway (providers/messenger/README.md holds the interface every messenger implements).
It works only in the listen mode: the Gateway delivers a button tap only on its open connection, so one long-lived
process keeps the connection, and the bridge starts it once. The dependencies are hash-locked in the file next to this
one (discord.py.lock, written by `uv lock --script providers/messenger/discord.py`); `uv run` honours it.

Sources (Discord's developer documentation, read 2026-10-12):
  Gateway (docs.discord.com/developers/events/gateway): `GET /gateway/bot` gives the URL and `session_start_limit`;
    connect to `wss://<host>/?v=10&encoding=json`; Hello (op 10) gives `heartbeat_interval` in milliseconds; the first
    heartbeat is sent after interval times a random jitter, then every interval, with the last sequence number; a
    heartbeat that gets no ACK (op 11) before the next one is due means a zombied connection: close it and resume;
    Identify (op 2: token, intents, properties) is limited to 1000 per 24 hours (a bot that passes it has its token
    reset); Ready gives `session_id` and `resume_gateway_url`; Resume is op 6; a close with code 1000 or 1001
    invalidates the session, so a close made to resume uses 4000; op 7 asks to reconnect, op 9 says the session is
    invalid (`d` true: it may be resumed); op 1 asks for a heartbeat at once; a payload is at most 4096 bytes; 120
    events per 60 seconds per connection. Close codes: 4004 authentication failed, 4007 invalid sequence, 4009 session
    timed out, 4010 to 4013 invalid shard, sharding required, invalid API version, invalid intents, 4014 disallowed
    intents. Direct-message content needs no privileged intent.
  Interactions (docs.discord.com/developers/interactions/receiving-and-responding): a button tap arrives as
    INTERACTION_CREATE (type 3, `context` 1 for a direct message with the bot, `user`, `data.custom_id`, `message`)
    and the first response is due within 3 seconds, `POST /interactions/<id>/<token>/callback`; callback type 6
    (DEFERRED_UPDATE_MESSAGE) changes nothing the person sees.
  Messages (docs.discord.com/developers/resources/message, .../components/reference): content up to 2000 characters;
    an action row holds up to 5 buttons; `custom_id` 1 to 100 characters, label up to 80; `message_reference` makes a
    reply; `allowed_mentions` {"parse": []} stops every ping; flag SUPPRESS_EMBEDS (1 << 2) stops link previews; files
    go as multipart with `payload_json`. A direct message channel is opened with `POST /users/@me/channels`
    (`recipient_id`); a bot that may not message a user gets HTTP 403 with code 50007. Requests carry
    `Authorization: Bot <token>` and a `User-Agent: DiscordBot (<url>, <version>)`; a 429 carries `retry_after`.
  Message formatting (docs.discord.com/developers/reference): the syntaxes <@id>, <#id>, <@&id>, <t:..>, <:name:id>,
    <a:name:id>, </command:id> and <id:..> are mentions, channels, timestamps, emoji, commands and guild links.

Verbs (JSON on stdout, diagnostics on stderr, input by flags, no prompt):
  capabilities --platform discord
  listen --platform discord           the long-lived verb (the protocol of providers/messenger/README.md)
  --check --platform discord          verify the token with GET /users/@me; exit 0 ready, 3 not configured
  receive, send, ack                  exit 2: discord works only in listen mode

The text of a message is Markdown, as the agents write it. Discord renders Markdown itself, so render_discord keeps
it, outside code only made safe: a masked link becomes `text (url)`, the openers of mentions, timestamps, emoji,
commands and guild links and the `||` of a spoiler are escaped with a backslash, a run of table lines is fenced. Every
message is sent with `allowed_mentions` empty and the no-embeds flag. A text that is longer than 2000 characters once
rendered is sent as it was (the bridge cuts it to the 1900 this provider declares).

The bot's token is the secret MESSENGER_DISCORD_BOT_TOKEN, read only through providers/secrets/resolver.py (the
environment, else the OS secret store, username messenger-discord). It is sent only in the Authorization header and in
the Identify payload, never in an argument, a log, an output or a traceback; every error is built from the exception's
class, the HTTP status and the service's own description, with the token, anything shaped like one and an interaction's
token removed. No HTTP redirect is followed (urllib would forward the Authorization header). The Gateway URL must be
wss:// on a discord.gg host. The websockets library is imported only where the Gateway is opened, and its logger stays at
WARNING (DEBUG logs the Identify frame).

Environment:
  MESSENGER_DISCORD_BOT_TOKEN         the bot's token (never printed)

Exit codes: 0 ok (also the end of stdin or SIGTERM in listen), 1 failed, 2 usage (also close codes 4010 to 4013),
3 not configured (no token, a token Discord refuses (HTTP 401, close code 4004), disallowed intents (4014), too few
Identify calls left).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import os
import queue
import random
import re
import signal
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

# The platforms this implementation serves. providers/resolve.py reads this one line as text, without importing the
# file, to choose among the implementations of messenger:<platform> (providers/CONTRACT.md).
PLATFORMS = ("discord",)

SECRET = "MESSENGER_DISCORD_BOT_TOKEN"
KEYRING_USERNAME = "messenger-discord"
EXIT_OK, EXIT_SERVICE, EXIT_USAGE, EXIT_NOT_CONFIGURED = 0, 1, 2, 3
API_BASE = "https://discord.com/api/v10"
USER_AGENT = "DiscordBot (https://github.com/chrissgon/openhora, 0.1)"
GATEWAY_QUERY = "/?v=10&encoding=json"
CAPABILITIES = {"max_text": 1900, "buttons": True, "max_buttons": 5, "max_button_label": 80, "lists": False,
                "max_list_rows": 0, "url_buttons": True, "reply_context": True, "documents": True, "listen": True}
DISCORD_TEXT_LIMIT = 2000
CUSTOM_ID_LIMIT = 100
LINK_URL_LIMIT = 512
DOCUMENT_LIMIT = 1_000_000
INTENTS = 1 << 12                 # DIRECT_MESSAGES, and nothing else
SUPPRESS_EMBEDS = 1 << 2
MIN_IDENTIFY_GAP = 5.0            # seconds between two Identify calls
MIN_IDENTIFY_LEFT = 50            # below this many Identify calls left in the period the provider stops
RESUME_CLOSE = 4000               # a close made to resume (1000 and 1001 invalidate the session)
HTTP_TIMEOUT = 10.0
CALLBACK_TIMEOUT = 2.5            # the first response to an interaction is due within 3 seconds
RATE_LIMIT_WAIT = 30.0            # a 429 is waited for once, at most this long
MAX_BODY = 1_000_000
MAX_REQUEST_LINE = 1_048_576
CONNECT_BACKOFF = (1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 60.0)
PROPERTIES = {"os": "linux", "browser": "openhora", "device": "openhora"}
FORBIDDEN_SENTENCE = ("the bot cannot message this user: share a server with the bot and allow direct messages from "
                      "that server's members (Discord error 50007)")
SNOWFLAKE = re.compile(r"\d{1,20}")
INTERACTION_TOKEN = re.compile(r"[A-Za-z0-9_-]{1,512}")
TOKEN_SHAPE = re.compile(r"[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{20,}")
LONG_SECRET = re.compile(r"[A-Za-z0-9_-]{60,}")
INTERACTION_PATH = re.compile(r"/interactions/\d+/[A-Za-z0-9_-]+")


class ProviderError(Exception):
    def __init__(self, message: str, code: int = EXIT_SERVICE, kind: str = "failed"):
        super().__init__(message)
        self.code = code
        self.kind = kind


class HttpError(ProviderError):
    """A ProviderError that keeps the HTTP status, Discord's error code and the wait of a 429 (all already safe)."""

    def __init__(self, message: str, status: int, description: str = "", discord_code=None, retry_after=None):
        super().__init__(message, EXIT_NOT_CONFIGURED if status == 401 else EXIT_SERVICE,
                         "not-configured" if status == 401 else "failed")
        self.status, self.description = status, description
        self.discord_code, self.retry_after = discord_code, retry_after


def redact(text, token: str = "") -> str:
    """The text with the token, anything shaped like one, an interaction's token and any very long token-like word replaced."""
    out = str(text)
    if token:
        out = out.replace(token, "<token>")
    out = INTERACTION_PATH.sub("/interactions/<id>/<token>", out)
    out = TOKEN_SHAPE.sub("<token>", out)
    return LONG_SECRET.sub("<token>", out)


def secret_resolver():
    """The workbench's secret resolver, by path: next to this file first (a copy), then providers/secrets/resolver.py."""
    here = Path(__file__).resolve()
    path = next((c for c in (here.parent / "resolver.py", here.parents[1] / "secrets" / "resolver.py") if c.is_file()), None)
    if path is None:
        raise ProviderError("providers/secrets/resolver.py is not next to this script nor in the workbench",
                            EXIT_NOT_CONFIGURED, "not-configured")
    spec = importlib.util.spec_from_file_location("workbench_secret_resolver", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_token() -> str:
    found = secret_resolver().resolve(SECRET)
    token = found[0] if found else ""
    if not token:
        raise ProviderError(f"no Discord bot token: export {SECRET}, or store one with "
                            f"uv run --with keyring==25.7.0 keyring set openhora {KEYRING_USERNAME}",
                            EXIT_NOT_CONFIGURED, "not-configured")
    if not re.fullmatch(r"[A-Za-z0-9._-]+", token):
        raise ProviderError("the Discord bot token has characters a token does not have", EXIT_NOT_CONFIGURED,
                            "not-configured")
    return token


# --- HTTP -----------------------------------------------------------------------------------------------------------

class RefuseRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow a redirect: urllib would forward the Authorization header to wherever it points."""

    def redirect_request(self, req, fp, code, msg, hdrs, newurl):
        fp.close()
        raise ProviderError(f"refusing to follow a {code} redirect: the request carries the bot's token", EXIT_SERVICE)


OPENER = urllib.request.build_opener(RefuseRedirect)


def _http_error(error, token: str) -> HttpError:
    status = getattr(error, "code", 0)
    description, discord_code, retry_after = "", None, None
    try:
        parsed = json.loads(error.read(MAX_BODY).decode("utf-8"))
        if isinstance(parsed, dict):
            description = str(parsed.get("message") or "")
            code = parsed.get("code")
            discord_code = code if isinstance(code, int) else None
            wait = parsed.get("retry_after")
            retry_after = float(wait) if isinstance(wait, (int, float)) and not isinstance(wait, bool) else None
    except Exception:  # an unreadable body is only a missing description
        pass
    if retry_after is None:
        try:
            header = error.headers.get("Retry-After") if getattr(error, "headers", None) else None
            retry_after = float(header) if header is not None else None
        except (TypeError, ValueError):
            retry_after = None
    description = redact(description, token)[:200]
    if status == 401:
        message = "Discord refused the bot token (401): store a valid one"
    else:
        message = f"Discord answered {status}" + (f": {description}" if description else "")
    return HttpError(message, status, description, discord_code, retry_after)


class Api:
    """Discord's REST API with the standard library. Every failure is a ProviderError whose text holds no token."""

    def __init__(self, token: str, base: str = API_BASE, timeout: float = HTTP_TIMEOUT):
        self.token, self.base, self.timeout = token, base, timeout

    def request(self, method: str, path: str, body=None, *, raw: bytes | None = None, content_type: str = "application/json",
                auth: bool = True, timeout: float | None = None):
        data = raw if raw is not None else (None if body is None else json.dumps(body).encode("utf-8"))
        headers = {"User-Agent": USER_AGENT}
        if data is not None:
            headers["Content-Type"] = content_type
        if auth:
            headers["Authorization"] = f"Bot {self.token}"
        request = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        label = f"{method} {redact(path.split('?')[0], self.token)}"
        try:
            with OPENER.open(request, timeout=timeout or self.timeout) as response:
                answer = response.read(MAX_BODY)
        except urllib.error.HTTPError as e:
            raise _http_error(e, self.token) from None
        except ProviderError:
            raise
        except urllib.error.URLError as e:
            raise ProviderError(f"Discord {label}: could not be reached ({type(getattr(e, 'reason', e)).__name__})") from None
        except (OSError, ValueError) as e:
            raise ProviderError(f"Discord {label}: the call failed ({type(e).__name__})") from None
        if not answer:
            return None
        try:
            return json.loads(answer.decode("utf-8"))
        except ValueError:
            raise ProviderError(f"Discord {label}: the answer was not JSON") from None


# --- rendering ------------------------------------------------------------------------------------------------------
# Discord renders Markdown, so the text is kept. Outside code spans and fenced blocks only, it is made safe: a masked
# link shows where it points, the openers that would draw a mention, a channel, a timestamp, an emoji, a command or a
# guild link are escaped, and so is a spoiler. A code span or a fence is never touched, so the effect command stays as
# it was written.
FENCE_OPEN = re.compile(r"\s*```[\w+.-]*\s*")
FENCE_CLOSE = re.compile(r"\s*```\s*")
MASKED_LINK = re.compile(r"\[([^\[\]\n]+)\]\s*\(\s*(?:<([^<>\s]+)>|([^()\s]+))(?:\s+(?:\"[^\"\n]*\"|'[^'\n]*'))?\s*\)")
MENTION_OPENER = re.compile(r"(?<!\\)((?:\\\\)*)<(?=@|#|t:|:|a:|/|id:)")
SPOILER = re.compile(r"(?<!\\)\|(?=\|)|(?<=\|)\|")
STRAY_LINK_OPENER = re.compile(r"\]\s*\(")


def _split_code(text: str) -> list:
    """The line as [("text", s) | ("code", s)]; a code item holds the span with its backticks, so that it is written back unchanged.
    A run of n backticks opens a span that the next run of exactly n closes; a run with no closer is text."""
    out, buf, i, n = [], [], 0, len(text)
    while i < n:
        if text[i] != "`":
            buf.append(text[i])
            i += 1
            continue
        j = i
        while j < n and text[j] == "`":
            j += 1
        run = j - i
        k, close = j, -1
        while k < n:
            if text[k] != "`":
                k += 1
                continue
            m = k
            while m < n and text[m] == "`":
                m += 1
            if m - k == run:
                close = k
                break
            k = m
        if close > j:
            if buf:
                out.append(("text", "".join(buf)))
                buf = []
            out.append(("code", text[i:close + run]))
            i = close + run
        else:
            buf.append(text[i:j])
            i = j
    if buf:
        out.append(("text", "".join(buf)))
    return out


def _unmask(match) -> str:
    return f"{match.group(1)} ({match.group(2) or match.group(3)})"


def _safe_text(text: str) -> str:
    for _ in range(5):  # a link inside the text of a link is unmasked from the inside out
        replaced = MASKED_LINK.sub(_unmask, text)
        if replaced == text:
            break
        text = replaced
    text = STRAY_LINK_OPENER.sub("]\\\\(", text)
    text = MENTION_OPENER.sub(lambda m: m.group(1) + "\\<", text)
    return SPOILER.sub("\\\\|", text)


def _as_text(line: str) -> str:
    """The line with no code in it at all: every backtick escaped, then made safe."""
    return _safe_text(line.replace("`", "\\`"))


def _safe_line(line: str) -> str:
    parts = _split_code(line)
    if any(kind == "text" and "```" in s for kind, s in parts):
        return _as_text(line)  # a stray fence mark: Discord may open a block here, so nothing on the line counts as code
    return "".join(s if kind == "code" else _safe_text(s) for kind, s in parts)


def render_discord(text: str, fence_tables: bool = True) -> str:
    """The text made safe for Discord (see the comment above). CRLF and CR are one newline. A fenced block is read as
    code only when Discord would read it the same way: its opener and its closer are lines of their own and no line
    inside holds ``` (Discord closes a block at a ``` anywhere); any other would-be block is text, backticks escaped. A
    fence that never closes is text too. A run of table lines is put in a fenced block when `fence_tables`."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out, i = [], 0
    while i < len(lines):
        line = lines[i]
        if FENCE_OPEN.fullmatch(line):
            end = next((j for j in range(i + 1, len(lines)) if FENCE_CLOSE.fullmatch(lines[j])), -1)
            if end != -1 and not any("```" in lines[j] for j in range(i + 1, end)):
                out.extend(lines[i:end + 1])
                i = end + 1
                continue
            stop = end + 1 if end != -1 else i + 1  # a doubtful block is text, whole; an unclosed fence is text, its line only
            out.extend(_as_text(l) for l in lines[i:stop])
            i = stop
            continue
        if fence_tables and line.lstrip().startswith("|"):
            j = i
            while j < len(lines) and lines[j].lstrip().startswith("|"):
                j += 1
            body = "\n".join(lines[i:j]).replace("```", "``\u200b`")  # a zero-width space keeps a cell from closing the fence
            out.append("```\n" + body + "\n```")
            i = j
            continue
        out.append(_safe_line(line))
        i += 1
    return "\n".join(out)


CONTINUES = "\n(continues on the page)"


def rendered_for_send(text: str) -> str:
    """The rendered text. When that is over 2000 characters, the same text without the fenced tables (which add
    characters), and when that is still over, cut with a closing line. Never raw text: links and openers stay safe."""
    rendered = render_discord(text)
    if len(rendered) <= DISCORD_TEXT_LIMIT:
        return rendered
    rendered = render_discord(text, fence_tables=False)
    if len(rendered) <= DISCORD_TEXT_LIMIT:
        return rendered
    return rendered[:DISCORD_TEXT_LIMIT - len(CONTINUES)].rstrip("\\") + CONTINUES


# --- the message ----------------------------------------------------------------------------------------------------

def check_message(message) -> dict:
    """The neutral message, checked against the capabilities: a usage error (exit 2) when it does not fit."""
    if not isinstance(message, dict):
        raise ProviderError("the message must be a JSON object", EXIT_USAGE, "usage")
    text = message.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ProviderError("the message needs a text", EXIT_USAGE, "usage")
    if len(text) > CAPABILITIES["max_text"]:
        raise ProviderError(f"the text is {len(text)} characters; this provider takes {CAPABILITIES['max_text']}",
                            EXIT_USAGE, "usage")
    actions = message.get("actions") or []
    if not isinstance(actions, list) or len(actions) > CAPABILITIES["max_buttons"]:
        raise ProviderError(f"a message takes at most {CAPABILITIES['max_buttons']} actions", EXIT_USAGE, "usage")
    for action in actions:
        if not isinstance(action, dict) or not isinstance(action.get("id"), str) or not isinstance(action.get("label"), str) \
                or not action["id"] or not action["label"]:
            raise ProviderError("an action is {\"id\": text, \"label\": text}", EXIT_USAGE, "usage")
        if len(action["id"]) > CUSTOM_ID_LIMIT:
            raise ProviderError(f"an action id is at most {CUSTOM_ID_LIMIT} characters (Discord's custom_id)", EXIT_USAGE, "usage")
    link = message.get("link")
    if link is not None:
        if not isinstance(link, dict) or not isinstance(link.get("label"), str) or not link["label"] \
                or not isinstance(link.get("url"), str) or not re.fullmatch(r"https?://[^\s]+", link["url"]) \
                or len(link["url"]) > LINK_URL_LIMIT:
            raise ProviderError("a link is {\"label\": text, \"url\": an http:// or https:// URL of at most 512 characters}", EXIT_USAGE, "usage")
    document = message.get("document")
    if document is not None and (not isinstance(document, dict) or not isinstance(document.get("name"), str)
                                 or not isinstance(document.get("text"), str) or not document["text"]
                                 or len(document["text"]) > DOCUMENT_LIMIT):
        raise ProviderError("a document is {\"name\": text, \"text\": text}", EXIT_USAGE, "usage")
    reply_to = message.get("reply_to")
    if reply_to is not None and (not isinstance(reply_to, str) or not SNOWFLAKE.fullmatch(reply_to)):
        raise ProviderError("reply_to is the id of a Discord message: whole digits", EXIT_USAGE, "usage")
    return message


def components(message: dict) -> list:
    """The buttons: the actions in one action row (the first primary, the others secondary), the link in a row of its own."""
    rows = []
    buttons = [{"type": 2, "style": 1 if n == 0 else 2, "label": a["label"][:CAPABILITIES["max_button_label"]],
                "custom_id": a["id"]} for n, a in enumerate(message.get("actions") or [])]
    if buttons:
        rows.append({"type": 1, "components": buttons})
    link = message.get("link")
    if link:
        rows.append({"type": 1, "components": [{"type": 2, "style": 5, "label": link["label"][:CAPABILITIES["max_button_label"]],
                                                "url": link["url"]}]})
    return rows


def payload_of(message: dict) -> dict:
    body = {"content": rendered_for_send(message["text"]), "allowed_mentions": {"parse": []}, "flags": SUPPRESS_EMBEDS}
    rows = components(message)
    if rows:
        body["components"] = rows
    if message.get("reply_to"):
        body["message_reference"] = {"message_id": message["reply_to"], "fail_if_not_exists": False}
    return body


def document_name(name: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", name)[:60] or "document"
    return safe if safe.endswith((".txt", ".md")) else safe + ".txt"


def multipart(payload: dict, name: str, text: str) -> tuple:
    """(body, content type) of a message with one file: `payload_json`, then `files[0]`."""
    boundary = "wb" + uuid.uuid4().hex
    filename = document_name(name)
    payload = dict(payload, attachments=[{"id": 0, "filename": filename}])
    parts = [(f'--{boundary}\r\nContent-Disposition: form-data; name="payload_json"\r\nContent-Type: application/json\r\n\r\n'
              ).encode("utf-8") + json.dumps(payload).encode("utf-8") + b"\r\n",
             (f'--{boundary}\r\nContent-Disposition: form-data; name="files[0]"; filename="{filename}"\r\n'
              "Content-Type: text/plain; charset=utf-8\r\n\r\n").encode("utf-8") + text.encode("utf-8")
             + f"\r\n--{boundary}--\r\n".encode("utf-8")]
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


# --- what the Gateway delivers, as updates --------------------------------------------------------------------------

def _id(value):
    return value if isinstance(value, str) and SNOWFLAKE.fullmatch(value) else None


def message_update(d) -> dict | None:
    """The listen update of a MESSAGE_CREATE: a plain message or a reply, in a direct message, from a person; else None."""
    if not isinstance(d, dict) or "guild_id" in d or d.get("webhook_id") or d.get("type") not in (0, 19):
        return None
    author = d.get("author")
    if not isinstance(author, dict) or author.get("bot") is True or _id(author.get("id")) is None or _id(d.get("id")) is None:
        return None
    content = d.get("content")
    if not isinstance(content, str) or not content.strip():
        return None
    reply_to = None
    reference = d.get("message_reference")
    if isinstance(reference, dict) and reference.get("type", 0) == 0 and _id(reference.get("message_id")):
        reply_to = reference["message_id"]
    return {"update_id": d["id"], "sender": author["id"], "chat": author["id"], "private": True, "text": content,
            "action": None, "action_ref": None, "reply_to": reply_to}


def interaction_update(d) -> dict | None:
    """The listen update of a tapped button in a direct message with the bot (type 3, context 1, a `user`, no guild)."""
    if not isinstance(d, dict) or d.get("type") != 3 or "guild_id" in d or d.get("context") != 1:
        return None
    user, data, message = d.get("user"), d.get("data"), d.get("message")
    if not isinstance(user, dict) or _id(user.get("id")) is None or not isinstance(data, dict):
        return None
    custom_id = data.get("custom_id")
    if not isinstance(custom_id, str) or not custom_id or not isinstance(message, dict):
        return None
    return {"update_id": d.get("id"), "sender": user["id"], "chat": user["id"], "private": True, "text": None,
            "action": custom_id, "action_ref": None, "reply_to": _id(message.get("id"))}


# --- the Gateway as a state machine ---------------------------------------------------------------------------------
# No socket and no clock of its own: it is fed decoded payloads, close codes and the time, and returns what to do.
# Effects: ("send", payload) write it; ("event", line) write it to the bridge; ("callback", interaction id, token) answer a
# tap with type 6, before the ("event", update) that follows it; ("reconnect", resume, wait) close with 4000, wait, connect
# again; ("fatal", exit code, kind, sentence) tell the bridge and stop.

class Plan:
    def __init__(self, resume: bool = False, wait: float = 0.0, fatal=None):
        self.resume, self.wait, self.fatal = resume, wait, fatal


FATAL_CLOSES = {
    4004: (EXIT_NOT_CONFIGURED, "not-configured", "Discord refused the bot's token (close code 4004): store a valid one "
                                                 f"with uv run --with keyring==25.7.0 keyring set openhora {KEYRING_USERNAME}"),
    4014: (EXIT_NOT_CONFIGURED, "not-configured", "Discord does not allow the intent this bot asks for (close code 4014): the "
                                                 "bridge asks only for direct messages; check the application's settings"),
}
USAGE_CLOSES = {4010: "invalid shard", 4011: "sharding required", 4012: "invalid API version", 4013: "invalid intents"}


class Gateway:
    def __init__(self, token: str, clock, rng):
        self.token, self.clock, self.rng = token, clock, rng
        self.session_id = None
        self.resume_url = None
        self.seq = None
        self.last_identify = None
        self.begin(False)

    @property
    def resumable(self) -> bool:
        return bool(self.session_id and self.resume_url and self.seq is not None)

    def begin(self, resume: bool) -> None:
        """A new connection is about to open: forget what belonged to the last one."""
        self.resuming = bool(resume) and self.resumable
        self.interval = None
        self.next_beat = None
        self.acked = True
        self.ready_sent = False

    def identify_wait(self) -> float:
        """Seconds to wait before another Identify may start (at most one in 5 seconds)."""
        if self.last_identify is None:
            return 0.0
        return max(0.0, MIN_IDENTIFY_GAP - (self.clock() - self.last_identify))

    def next_wake(self):
        return None if self.next_beat is None else self.next_beat - self.clock()

    def _heartbeat(self) -> dict:
        return {"op": 1, "d": self.seq}

    def on_payload(self, payload) -> list:
        if not isinstance(payload, dict):
            return []
        op, data = payload.get("op"), payload.get("d")
        if op == 10:
            return self._hello(data)
        if op == 11:
            self.acked = True
            return []
        if op == 1:  # a request for a heartbeat at once
            self.acked = False
            if self.interval:
                self.next_beat = self.clock() + self.interval
            return [("send", self._heartbeat())]
        if op == 7:
            return [("reconnect", True, 0.0)]
        if op == 9:
            if data is True and self.resumable:
                return [("reconnect", True, 1.0 + 4.0 * self.rng())]
            self.session_id = self.resume_url = self.seq = None
            return [("reconnect", False, 1.0 + 4.0 * self.rng())]
        if op == 0:
            if isinstance(payload.get("s"), int):
                self.seq = payload["s"]
            return self._dispatch(payload.get("t"), data)
        return []

    def _hello(self, data) -> list:
        interval = data.get("heartbeat_interval") if isinstance(data, dict) else None
        if not isinstance(interval, (int, float)) or isinstance(interval, bool) or interval <= 0:
            return [("reconnect", self.resumable, 5.0)]
        self.interval = interval / 1000.0
        self.next_beat = self.clock() + self.interval * self.rng()
        self.acked = True
        if self.resuming:
            return [("send", {"op": 6, "d": {"token": self.token, "session_id": self.session_id, "seq": self.seq}})]
        self.session_id = self.resume_url = self.seq = None
        self.last_identify = self.clock()
        return [("send", {"op": 2, "d": {"token": self.token, "intents": INTENTS, "properties": dict(PROPERTIES)}})]

    def _dispatch(self, name, data) -> list:
        if name == "READY":
            if isinstance(data, dict):
                url = data.get("resume_gateway_url")
                self.session_id = data.get("session_id") if isinstance(data.get("session_id"), str) else None
                self.resume_url = url if isinstance(url, str) and gateway_url_ok(url) else None
            if self.ready_sent:
                return []
            self.ready_sent = True
            return [("event", {"event": "ready"})]
        if name == "RESUMED":
            return [("good",)]
        if name == "MESSAGE_CREATE":
            update = message_update(data)
            return [("event", {"event": "update", "update": update})] if update else []
        if name == "INTERACTION_CREATE":
            update = interaction_update(data)
            if update is None:
                return []
            effects = []
            if _id(data.get("id")) and isinstance(data.get("token"), str) and INTERACTION_TOKEN.fullmatch(data["token"]):
                effects.append(("callback", data["id"], data["token"]))
            effects.append(("event", {"event": "update", "update": update}))
            return effects
        return []

    def tick(self) -> list:
        if self.next_beat is None or self.clock() < self.next_beat:
            return []
        if not self.acked:  # the last heartbeat was never acknowledged: a zombied connection
            return [("reconnect", True, 0.0)]
        self.acked = False
        self.next_beat = self.clock() + self.interval
        return [("send", self._heartbeat())]

    def on_close(self, code) -> Plan:
        """What to do after the connection closed with this code (None when it dropped without one)."""
        if code in FATAL_CLOSES:
            exit_code, kind, sentence = FATAL_CLOSES[code]
            return Plan(fatal=(exit_code, kind, sentence))
        if code in USAGE_CLOSES:
            return Plan(fatal=(EXIT_USAGE, "usage", f"Discord refused the connection (close code {code}, {USAGE_CLOSES[code]}); "
                                                    "this is a defect of the provider, not of the setup"))
        if code in (4007, 4009) or code in (1000, 1001):
            self.session_id = self.resume_url = self.seq = None
            return Plan(resume=False, wait=1.0 + 4.0 * self.rng())
        return Plan(resume=self.resumable, wait=5.0 if code == 4008 else 0.0)  # 4008: rate limited


def gateway_url_ok(url) -> bool:
    """A Gateway URL is wss:// on a discord.gg host, with no credentials in it."""
    try:
        parsed = urllib.parse.urlparse(url)
        host = (parsed.hostname or "").lower()
        return parsed.scheme == "wss" and (host == "discord.gg" or host.endswith(".discord.gg")) \
            and parsed.username is None and parsed.password is None and parsed.port in (None, 443)
    except ValueError:
        return False


# --- the transport: websockets, imported only here ------------------------------------------------------------------

class Closed(Exception):
    """The connection closed; `code` is the close code the peer sent, or None."""

    def __init__(self, code=None):
        super().__init__(f"closed {code}")
        self.code = code


class ConnectFailed(Exception):
    """The connection could not be opened; the text is the exception's class, never its message."""


class WebsocketsTransport:
    """Opens a Gateway connection with the websockets library (the synchronous client). The import is here so that the
    rest of the module, and its tests, need no library."""

    def connect(self, url: str):
        try:
            from websockets.sync.client import connect  # imported only when the Gateway opens
        except ImportError:
            raise ConnectFailed("the websockets library is not installed: run this script with uv run") from None
        logging.getLogger("websockets").setLevel(logging.WARNING)  # DEBUG would log the Identify frame, with the token
        try:
            return _WebsocketsConnection(connect(url, open_timeout=15, close_timeout=2, max_size=16 * 1024 * 1024, ping_interval=None))
        except Exception as e:
            raise ConnectFailed(f"could not open the Gateway connection ({type(e).__name__})") from None


class _WebsocketsConnection:
    def __init__(self, ws):
        self.ws = ws

    def recv(self, timeout: float):
        """The next text frame, or None when `timeout` seconds pass with none."""
        try:
            frame = self.ws.recv(timeout=timeout)
        except TimeoutError:
            return None
        except Exception as e:
            raise Closed(self._code(e)) from None
        return frame.decode("utf-8", "replace") if isinstance(frame, (bytes, bytearray)) else frame

    def send(self, text: str) -> None:
        try:
            self.ws.send(text)
        except Exception as e:
            raise Closed(self._code(e)) from None

    def close(self, code: int = 1000) -> None:
        try:
            self.ws.close(code)
        except Exception:
            pass

    @staticmethod
    def _code(error):
        received = getattr(error, "rcvd", None)
        code = getattr(received, "code", None)
        return code if isinstance(code, int) else None


# --- the listen mode ------------------------------------------------------------------------------------------------

class Out:
    """The bridge's protocol descriptor: one JSON line, ASCII, flushed, under one lock."""

    def __init__(self, stream):
        self.stream, self.lock = stream, threading.Lock()

    def write(self, line: dict) -> None:
        data = json.dumps(line, ensure_ascii=True).encode("ascii") + b"\n"
        with self.lock:
            try:
                self.stream.write(data)
                self.stream.flush()
            except (OSError, ValueError):
                pass  # the bridge is gone: stdin ends too, and that stops everything


class Listener:
    """One listen process: the Gateway thread, the sender thread and the stdin reader share this object."""

    def __init__(self, token: str, *, api, transport, out, stdin, clock=time.monotonic, rng=random.random, pause=None,
                 log=None):
        self.token, self.api, self.transport, self.out, self.stdin = token, api, transport, out, stdin
        self.clock, self.rng = clock, rng
        self.stop = threading.Event()
        self.code = None
        self.lock = threading.Lock()
        self.pause = pause or self._pause
        self.log = log or (lambda text: print(redact(text, token), file=sys.stderr, flush=True))
        self.gateway = Gateway(token, clock, rng)
        self.requests = queue.Queue()
        self.channels = {}
        self.healthy = False

    # shared helpers
    def _pause(self, seconds: float) -> bool:
        """Wait up to `seconds`; True when the process was told to stop meanwhile."""
        return self.stop.wait(max(0.0, seconds))

    def finish(self, code: int) -> None:
        with self.lock:
            if self.code is None:
                self.code = code
        self.stop.set()

    def error_event(self, kind: str, reason: str) -> None:
        self.out.write({"event": "error", "kind": kind, "reason": redact(reason, self.token)})

    def fatal(self, exit_code: int, kind: str, sentence: str) -> None:
        self.error_event(kind, sentence)
        self.finish(exit_code)

    # stdin
    def read_stdin(self) -> None:
        try:
            while not self.stop.is_set():
                line = self.stdin.readline(MAX_REQUEST_LINE + 1)
                if not line:
                    break
                if len(line) > MAX_REQUEST_LINE:
                    while line and not line.endswith(b"\n"):  # the rest of an over-long line is read and dropped
                        line = self.stdin.readline(MAX_REQUEST_LINE)
                    self.log("dropped a request line over 1 MiB")
                    continue
                try:
                    request = json.loads(line.decode("utf-8"))
                except ValueError:
                    self.log("dropped a request line that is not JSON")
                    continue
                self.requests.put(request)
        except (OSError, ValueError):
            pass
        self.finish(EXIT_OK)

    # the sender
    def answer(self, rid, ok: bool, **fields) -> None:
        self.out.write({"id": rid, "ok": ok, **fields})

    def work(self) -> None:
        while not self.stop.is_set():
            try:
                request = self.requests.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self.handle(request)
            except Exception as e:  # nothing else may print a traceback
                self.log(f"a send failed unexpectedly ({type(e).__name__})")
                if isinstance(request, dict) and isinstance(request.get("id"), int):
                    self.answer(request["id"], False, kind="failed", reason="the send failed unexpectedly")

    def handle(self, request) -> None:
        rid = request.get("id") if isinstance(request, dict) else None
        if not isinstance(rid, int) or isinstance(rid, bool):
            self.log("dropped a request with no integer id")
            return
        try:
            if request.get("op") != "send":
                raise ProviderError("the only request is send", EXIT_USAGE, "usage")
            chat = request.get("chat")
            if not isinstance(chat, str) or not SNOWFLAKE.fullmatch(chat):
                raise ProviderError("chat is a Discord user id: whole digits", EXIT_USAGE, "usage")
            message = check_message(request.get("message"))
            message_id = self.send(chat, message, [RATE_LIMIT_WAIT])
        except HttpError as e:
            if e.status == 401:
                self.answer(rid, False, kind="not-configured", reason=redact(e, self.token))
                self.fatal(EXIT_NOT_CONFIGURED, "not-configured", str(e))
            elif e.status == 403:
                self.answer(rid, False, kind="failed", reason=FORBIDDEN_SENTENCE if e.discord_code == 50007 else
                            "Discord refused the request (403" + (f", code {e.discord_code}" if e.discord_code else "")
                            + "): check what the bot may do")
            else:
                self.answer(rid, False, kind="failed", reason=redact(e, self.token))
        except ProviderError as e:
            self.answer(rid, False, kind=e.kind, reason=redact(e, self.token))
        else:
            self.answer(rid, True, message_id=message_id)

    def waiting_once(self, call, budget):
        """call(); a 429 is waited for once, out of the request's budget (a one-item list of seconds shared by every
        call of one request, 30 in all; a wait that does not fit fails at once), then asked again."""
        try:
            return call()
        except HttpError as e:
            if e.status != 429:
                raise
            wait = e.retry_after if e.retry_after is not None else 1.0
            if wait > budget[0]:
                raise
            budget[0] -= wait
            if self.pause(wait):
                raise ProviderError("stopping") from None
            return call()

    def send(self, chat: str, message: dict, budget) -> str:
        channel = self.channels.get(chat)
        if channel is None:
            opened = self.waiting_once(lambda: self.api.request("POST", "/users/@me/channels", {"recipient_id": chat}), budget)
            channel = opened.get("id") if isinstance(opened, dict) else None
            if not isinstance(channel, str) or not SNOWFLAKE.fullmatch(channel):
                raise ProviderError("Discord did not open a direct message channel")
            self.channels[chat] = channel
        payload = payload_of(message)
        path = f"/channels/{channel}/messages"
        document = message.get("document")
        if document:
            body, kind = multipart(payload, document["name"], document["text"])
            call = lambda: self.api.request("POST", path, raw=body, content_type=kind)
        else:
            call = lambda: self.api.request("POST", path, payload)
        try:
            sent = self.waiting_once(call, budget)
        except HttpError as e:
            if e.status == 404:
                self.channels.pop(chat, None)
            raise
        if not isinstance(sent, dict) or not isinstance(sent.get("id"), str):
            raise ProviderError("Discord did not return the id of the message")
        return sent["id"]

    # the Gateway
    def run_gateway(self) -> None:
        failures = 0
        resume = False
        while not self.stop.is_set():
            try:
                self.healthy = False
                plan = self.connection(resume)
                if self.healthy:   # READY or RESUMED came: the connection did its job before it ended
                    failures = 0
                elif not self.stop.is_set() and not plan.fatal:  # accepted and dropped: no tight loop on it
                    wait = CONNECT_BACKOFF[min(failures, len(CONNECT_BACKOFF) - 1)]
                    failures += 1
                    self.error_event("failed", f"the Gateway connection ended before it was ready; trying again in {int(wait)} s")
                    plan = Plan(resume=plan.resume, wait=max(plan.wait, wait))
            except ProviderError as e:
                if getattr(e, "status", None) == 401:
                    self.fatal(EXIT_NOT_CONFIGURED, "not-configured", str(e))
                    return
                plan = self.retry(redact(e, self.token), failures)
                failures += 1
            except ConnectFailed as e:
                plan = self.retry(str(e), failures)
                failures += 1
            except Exception as e:
                plan = self.retry(f"the Gateway connection failed ({type(e).__name__})", failures)
                failures += 1
            if plan.fatal:
                self.fatal(*plan.fatal)
                return
            resume = plan.resume
            if plan.wait and self.pause(plan.wait):
                return

    def retry(self, reason: str, failures: int) -> Plan:
        wait = CONNECT_BACKOFF[min(failures, len(CONNECT_BACKOFF) - 1)]
        self.error_event("failed", f"{reason}; trying again in {int(wait)} s")
        return Plan(resume=self.gateway.resumable, wait=wait)

    def connection(self, resume: bool) -> Plan:
        gw = self.gateway
        resume = resume and gw.resumable
        if resume:
            url = gw.resume_url
        else:
            if self.pause(gw.identify_wait()):
                return Plan()
            info = self.api.request("GET", "/gateway/bot")
            left = info.get("session_start_limit", {}).get("remaining") if isinstance(info, dict) else None
            if isinstance(left, int) and left < MIN_IDENTIFY_LEFT:
                reset = info["session_start_limit"].get("reset_after")
                return Plan(fatal=(EXIT_NOT_CONFIGURED, "not-configured",
                                   f"Discord allows this bot only {left} more Identify calls in this period"
                                   + (f" (it resets in {int(reset) // 1000} s)" if isinstance(reset, int) else "")
                                   + ": the bridge stops before passing the limit, which would reset the token; wait, then run it again"))
            url = info.get("url") if isinstance(info, dict) else None
        if not isinstance(url, str) or not gateway_url_ok(url):
            return Plan(fatal=(EXIT_SERVICE, "failed", "the Gateway URL is not a wss:// URL on a discord.gg host; not connecting"))
        conn = self.transport.connect(url.rstrip("/") + GATEWAY_QUERY)
        gw.begin(resume)
        return self.pump(conn)

    def pump(self, conn) -> Plan:
        gw = self.gateway
        while not self.stop.is_set():
            wake = gw.next_wake()
            timeout = 1.0 if wake is None else max(0.01, min(1.0, wake))
            try:
                frame = conn.recv(timeout)
                effects = []
                if frame is not None:
                    try:
                        effects = gw.on_payload(json.loads(frame))
                    except ValueError:
                        self.log("ignored a Gateway frame that is not JSON")
                effects += gw.tick()
                plan = self.apply(conn, effects)
            except Closed as e:
                return gw.on_close(e.code)
            if plan is not None:
                return plan
        conn.close(1000)
        return Plan()

    def apply(self, conn, effects):
        for effect in effects:
            kind = effect[0]
            if kind == "send":
                conn.send(json.dumps(effect[1]))
            elif kind == "good":
                self.healthy = True
            elif kind == "event":
                if effect[1].get("event") == "ready":
                    self.healthy = True
                self.out.write(effect[1])
            elif kind == "callback":
                try:
                    self.api.request("POST", f"/interactions/{effect[1]}/{effect[2]}/callback", {"type": 6}, auth=False,
                                     timeout=CALLBACK_TIMEOUT)
                except ProviderError as e:
                    self.log(f"the answer to a button tap failed ({type(e).__name__})")
            elif kind == "reconnect":
                conn.close(RESUME_CLOSE)
                return Plan(resume=effect[1] and self.gateway.resumable, wait=effect[2])
        return None

    def run(self) -> int:
        threads = [threading.Thread(target=self.run_gateway, daemon=True), threading.Thread(target=self.work, daemon=True),
                   threading.Thread(target=self.read_stdin, daemon=True)]
        for thread in threads:
            thread.start()
        self.stop.wait()
        threads[0].join(3.0)  # the Gateway thread closes its connection with 1000 within a second
        return self.code or EXIT_OK


def listen(token: str, *, api=None, transport=None, out=None, stdin=None, install_signals: bool = False, **options) -> int:
    """Run the listen verb until stdin ends, SIGTERM, or a fatal error; the exit code. The protocol goes to `out`."""
    listener = Listener(token, api=api or Api(token), transport=transport or WebsocketsTransport(), out=out, stdin=stdin,
                        **options)
    if install_signals:
        signal.signal(signal.SIGTERM, lambda *_: listener.finish(EXIT_OK))
        signal.signal(signal.SIGINT, lambda *_: listener.finish(EXIT_OK))
    return listener.run()


def run_listen(token: str, **options) -> int:
    """The process wiring: the protocol on a copy of fd 1, fd 1 pointed at stderr so that no print reaches the bridge."""
    protocol = os.fdopen(os.dup(1), "wb")
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    hook = threading.excepthook
    threading.excepthook = lambda args: print(f"error: a thread failed ({args.exc_type.__name__})", file=sys.stderr, flush=True)
    try:
        return listen(token, out=Out(protocol), stdin=sys.stdin.buffer, install_signals=True, **options)
    finally:
        threading.excepthook = hook


# --- the command line -----------------------------------------------------------------------------------------------

def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--check", action="store_true", help="verify the token with GET /users/@me; exit 0 ready, 3 not configured")
    p.add_argument("--platform")
    sub = p.add_subparsers(dest="verb")
    for name in ("capabilities", "listen", "receive", "send", "ack"):
        s = sub.add_parser(name)
        s.add_argument("--platform", default=argparse.SUPPRESS)
    return p


def run(argv) -> int:
    args, _ = parser().parse_known_args(argv)  # receive, send and ack take arguments this provider refuses anyway
    if args.platform != "discord":
        raise ProviderError("this implementation serves --platform discord", EXIT_USAGE, "usage")
    if not args.check and not args.verb:
        raise ProviderError("give a verb: capabilities or listen (see --help)", EXIT_USAGE, "usage")
    if args.verb == "capabilities":
        print(json.dumps(CAPABILITIES))
        return EXIT_OK
    if args.verb in ("receive", "send", "ack"):
        raise ProviderError("discord works only in listen mode", EXIT_USAGE, "usage")
    token = load_token()
    if args.check:
        try:
            Api(token).request("GET", "/users/@me")
        except ProviderError as e:
            raise ProviderError(redact(e, token), e.code, e.kind) from None
        print(json.dumps({"ok": True}))
        return EXIT_OK
    return run_listen(token)


def main(argv=None) -> int:
    try:
        return run(sys.argv[1:] if argv is None else argv)
    except ProviderError as e:
        print(f"error: {redact(e)}", file=sys.stderr)
        return e.code
    except SystemExit:
        raise
    except BaseException as e:  # nothing else may print a traceback: a request's text can hold a token
        print(f"error: unexpected failure ({type(e).__name__})", file=sys.stderr)
        return EXIT_SERVICE


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)  # daemon threads may still be in a network call; the process ends now, within the 5 seconds
