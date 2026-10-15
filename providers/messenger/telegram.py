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
"document": {"name", "text"} | null}. The text is Markdown, as the agents write it. It is sent in Telegram's HTML parse
mode after render_html: everything is escaped first, so nothing a project wrote can open a tag, and only a small
subset of marks is turned into the tags b, s, code, pre and blockquote (see render_html). Link previews are off on
every message. When Telegram answers 400 "can't parse entities", the same message is sent once more as plain text,
with the same keyboard. An action becomes a row of the inline keyboard whose button carries the action id as
`callback_data`; a link becomes a last row with a URL button. A document is sent after the message, as a reply to it,
so that the message id this verb prints is the one of the message a person replies to. The verb refuses (exit 2) a
message beyond the capabilities it prints: the bridge reads them first and never sends one.

The bot's token is the secret MESSENGER_TELEGRAM_BOT_TOKEN, read only through providers/secrets/resolver.py (the
environment, else the OS secret store, username messenger-telegram). Telegram carries the token in the request path,
so every error is built from the exception's class, the HTTP status and the service's own description, with the
token and anything shaped like one removed; the token is in no argument, no log, no stdout and no traceback. No
redirect is followed. A request has a timeout. A verb never retries a call; the one exception is the plain resend of a text Telegram refused to parse, a second
call made on purpose.

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
import html
import html.parser
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


class HttpError(ProviderError):
    """A ProviderError that keeps the HTTP status and the service's description (already redacted and cut)."""

    def __init__(self, message: str, code: int, status: int, description: str):
        super().__init__(message, code)
        self.status, self.description = status, description


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


def store_missing_note(resolver, test_mode: bool = False) -> str:
    """The sentence that tells the OS secret store cannot be read in this Python (no keyring library), with its trailing space,
    or "" (also in test mode, where the store is not asked on purpose, and for a resolver without the check)."""
    if test_mode:
        return ""
    unsafe = getattr(resolver, "unsafe_note", None)   # a credentials directory that is refused is not a token that is absent (package P-OPS)
    try:
        refused = "" if unsafe is None else unsafe()
    except Exception:  # a broken check must not hide the real error
        refused = ""
    if isinstance(refused, str) and refused:
        return f"the credentials directory is unsafe, so no secret is read from it: {refused}. "
    locked = getattr(resolver, "store_locked_note", None)   # a locked store is not a missing token (package P-OPS)
    try:
        said = "" if locked is None else locked()
    except Exception:  # a broken check must not hide the real error
        said = ""
    if isinstance(said, str) and said:
        return said + ". "
    available = getattr(resolver, "store_available", None)
    try:
        if test_mode or available is None or available():
            return ""
    except Exception:  # a broken check must not hide the real error
        return ""
    return ("the OS secret store is not available in this Python (the keyring library is missing): run this command with "
            "`uv run --with keyring==25.7.0 python3 ...`, or export the variable. ")


def load_token(test_mode: bool) -> str:
    resolver = secret_resolver()
    found = resolver.resolve(SECRET, allow_store=not test_mode)
    token = found[0] if found else ""
    if not token:
        raise ProviderError(store_missing_note(resolver, test_mode) +
                            f"no Telegram bot token: export {SECRET}, or store one with "
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
            return HttpError(f"Telegram answered 409: {CONFLICT_SENTENCE}", EXIT_NOT_CONFIGURED, status, description)
        return HttpError(f"Telegram answered 409: {WEBHOOK_SENTENCE}", EXIT_NOT_CONFIGURED, status, description)  # a 409 matching neither text keeps this sentence (old behaviour)
    if status in (401, 404):
        return HttpError(f"Telegram refused the bot token ({status}): store a valid one", EXIT_NOT_CONFIGURED, status, description)
    return HttpError(f"Telegram {method} answered {status}" + (f": {description}" if description else ""), EXIT_SERVICE,
                     status, description)


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


# --- Markdown to Telegram's HTML parse mode ---------------------------------------------------------------------------
# The project's text is never trusted: every character that reaches the output passes html.escape, and the only tags
# are the ones this code writes: b, s, code, pre, blockquote. Single-mark italics (*x*, _x_) are not rendered: paths,
# globs, dunders and snake_case are common in the agents' text, and a command built with shlex.quote leaves _ and *.
FENCE_OPEN = re.compile(r"\s*```[\w+.-]*\s*")
FENCE_CLOSE = re.compile(r"\s*```\s*")
HEADING = re.compile(r"(#{1,6})[ \t]+(\S.*)")
BULLET = re.compile(r"(\s*)[-*] (.*)")
LINK = re.compile(r"\[([^\[\]\n]+)\]\(([^()\s]+)\)")
MARKS = {"**": "b", "~~": "s"}
ALLOWED_TAGS = ("b", "s", "code", "pre", "blockquote")


def _esc(text: str) -> str:
    return html.escape(text, quote=False)


def _split_code(text: str) -> list:
    """The line as [("text", s) | ("code", s)]: a run of n backticks opens a span that the next run of exactly n closes."""
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
        k = j
        close = -1
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
            content = text[j:close]
            if len(content) > 2 and content[0] == " " and content[-1] == " " and content.strip():
                content = content[1:-1]  # CommonMark: one padding space at each end is not part of the code
            out.append(("code", content))
            i = close + run
        else:
            buf.append(text[i:j])
            i = j
    if buf:
        out.append(("text", "".join(buf)))
    return out


def _opens(text: str, i: int) -> bool:
    before = text[i - 1] if i else " "
    after = text[i + 2] if i + 2 < len(text) else " "
    return (before.isspace() or before == "(") and not after.isspace()


def _closer(text: str, mark: str, start: int) -> int:
    """The index of the mark that closes one opened before `start`, or -1: content before it ends in a non-space and
    it is followed by the end of the line, a space or punctuation."""
    k = text.find(mark, start + 1)
    while k != -1:
        after = text[k + 2] if k + 2 < len(text) else " "
        if k > start and not text[k - 1].isspace() and not (after.isalnum() or after == "_"):
            return k
        k = text.find(mark, k + 1)
    return -1


def _marks(text: str, allow: tuple) -> str:
    """Bold, strike and links on text that holds no code span. One pass; a mark with no closer, or that would cross
    another, stays literal."""
    out, i = [], 0
    while i < len(text):
        two = text[i:i + 2]
        tag = MARKS.get(two)
        if tag and tag in allow and _opens(text, i):
            k = _closer(text, two, i + 2)
            if k != -1:
                out.append(f"<{tag}>" + _marks(text[i + 2:k], tuple(t for t in allow if t != tag)) + f"</{tag}>")
                i = k + 2
                continue
        if text[i] == "[":
            found = LINK.match(text, i)
            if found:
                out.append(_esc(f"{found.group(1)} ({found.group(2)})"))
                i = found.end()
                continue
        out.append(_esc(text[i]))
        i += 1
    return "".join(out)


def _inline(text: str) -> str:
    return "".join(f"<code>{_esc(s)}</code>" if kind == "code" else _marks(s, ("b", "s")) for kind, s in _split_code(text))


def _heading(text: str) -> str:
    """A heading is bold; a code span inside it is closed out of the bold, since a code span cannot sit inside a mark."""
    out = []
    for kind, s in _split_code(text):
        if kind == "code":
            out.append(f"<code>{_esc(s)}</code>")
        elif s.strip():
            s = re.sub(r"\*\*(?=\S)(.+?)(?<=\S)\*\*", r"\1", s)  # a heading is bold already: its **x** pairs lose the marks
            out.append("<b>" + _marks(s, ("s",)) + "</b>")
        else:
            out.append(_esc(s))
    return "".join(out)


def _line(line: str) -> str:
    found = HEADING.fullmatch(line)
    if found:
        return _heading(found.group(2))
    found = BULLET.fullmatch(line)
    if found:
        return found.group(1) + "• " + _inline(found.group(2))
    return _inline(line)


def _quoted(line: str):
    """The text of a `> ` line, or None when the line is not a quote line with something in it."""
    if line.startswith("> ") and line[2:].strip():
        return line[2:]
    return None


def render_html(markdown: str) -> str:
    """Telegram HTML for a Markdown message. CRLF and CR are one newline. Fenced blocks (a fence that never closes is
    ordinary text), runs of table lines and runs of `> ` lines are found on the raw text; a fence and a table become
    <pre> with their content escaped and not read; everything else is escaped as it is written out. Headings are bold,
    `- ` and `* ` bullets become a dot (the indent stays), **x** is bold, ~~x~~ strike, `x` code, and [t](u) is the
    text `t (u)`: a link is never an <a>. The output is never longer, once its tags are removed, than the input."""
    lines = markdown.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out, i = [], 0
    while i < len(lines):
        line = lines[i]
        if FENCE_OPEN.fullmatch(line):
            end = next((j for j in range(i + 1, len(lines)) if FENCE_CLOSE.fullmatch(lines[j])), -1)
            if end != -1:
                out.append("<pre>" + _esc("\n".join(lines[i + 1:end])) + "</pre>")
                i = end + 1
                continue
        if line.lstrip().startswith("|"):
            j = i
            while j < len(lines) and lines[j].lstrip().startswith("|"):
                j += 1
            out.append("<pre>" + _esc("\n".join(lines[i:j])) + "</pre>")
            i = j
            continue
        if _quoted(line) is not None:
            j, run = i, []
            while j < len(lines) and _quoted(lines[j]) is not None:
                run.append(_line(_quoted(lines[j])))
                j += 1
            out.append("<blockquote>" + "\n".join(run) + "</blockquote>")
            i = j
            continue
        out.append(_line(line))
        i += 1
    return "\n".join(out)


def visible_text(rendered: str) -> str:
    """What a person sees of rendered HTML: the tags removed and the entities read."""
    return html.unescape(re.sub(r"<[^>]*>", "", rendered))


def _is_parse_refusal(error) -> bool:
    return isinstance(error, HttpError) and error.status == 400 and "can't parse entities" in error.description.lower()


def send(chat: str, message: dict, token: str, base: str) -> dict:
    if not CHAT_ID.fullmatch(chat):
        raise ProviderError("--chat is a Telegram chat id: whole digits, with a leading minus for a group", EXIT_USAGE)
    message = check_message(message)
    fields = {"chat_id": int(chat), "text": message["text"], "link_preview_options": {"is_disabled": True}}
    markup = keyboard(message)
    if markup:
        fields["reply_markup"] = markup
    rendered = render_html(message["text"])
    if visible_text(rendered).strip():  # a text with nothing to show once rendered (an empty fence) goes out plain
        formatted = dict(fields, text=rendered, parse_mode="HTML")
        try:
            sent = call("sendMessage", formatted, token, base, SEND_TIMEOUT_SECONDS)
        except ProviderError as e:
            if not _is_parse_refusal(e):
                raise
            print("Telegram refused the formatted text; sent as plain text", file=sys.stderr)
            sent = call("sendMessage", fields, token, base, SEND_TIMEOUT_SECONDS)
    else:
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
