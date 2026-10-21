"""The loopback stub of `run-text.sh --probe`: it speaks the streamed reply of a messages API with one fixed answer.

It listens on 127.0.0.1 only, on a port the system picks, and records every request it gets (method, path without its query,
headers, parsed body) so that the probe can say what the CLI sent. It holds no credential and calls no host. Standard library only.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ANSWER = "probe-ok"
# The token counts the stub reports, in the runner's own keys: what a reply read from the stub must show (the probe's reply_ok).
USAGE = {"input": 1, "output": 1, "cache_read": 0, "cache_write": 0}
MAX_BODY = 8 * 1024 * 1024


def events(model):
    """The server-sent events of one streamed reply that ends its turn."""
    usage = {"input_tokens": 1, "output_tokens": 1, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
    return [
        ("message_start", {"type": "message_start", "message": {"id": "msg_probe", "type": "message", "role": "assistant", "model": model,
                                                                "content": [], "stop_reason": None, "stop_sequence": None, "usage": usage}}),
        ("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}),
        ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": ANSWER}}),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                           "usage": {"output_tokens": 1}}),
        ("message_stop", {"type": "message_stop"}),
    ]


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):   # nothing is logged: a request holds the probe texts only, but the rule is the same
        pass

    def reply(self, status, body, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def handle_any(self):
        path = self.path.split("?", 1)[0]
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length > MAX_BODY:
            return self.reply(413, b"{}", "application/json")
        raw = self.rfile.read(length) if length else b""
        try:
            body = json.loads(raw.decode("utf-8")) if raw else None
        except ValueError:
            body = None
        self.server.record({"method": self.command, "path": path, "headers": {k.lower(): v for k, v in self.headers.items()},
                            "body": body})
        if self.command == "POST" and path == "/v1/messages":
            model = body.get("model") if isinstance(body, dict) and isinstance(body.get("model"), str) else "probe"
            if isinstance(body, dict) and body.get("stream"):
                text = "".join("event: %s\ndata: %s\n\n" % (name, json.dumps(data)) for name, data in events(model))
                return self.reply(200, text.encode("utf-8"), "text/event-stream")
            message = {"id": "msg_probe", "type": "message", "role": "assistant", "model": model,
                       "content": [{"type": "text", "text": ANSWER}], "stop_reason": "end_turn", "stop_sequence": None,
                       "usage": {"input_tokens": 1, "output_tokens": 1}}
            return self.reply(200, json.dumps(message).encode("utf-8"), "application/json")
        return self.reply(200, b"{}", "application/json")

    do_GET = do_POST = do_PUT = do_DELETE = do_HEAD = handle_any


class Stub(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self):
        super().__init__(("127.0.0.1", 0), Handler)
        self._lock = threading.Lock()
        self._seen = []

    def record(self, request):
        with self._lock:
            self._seen.append(request)

    def requests(self):
        with self._lock:
            return list(self._seen)

    def reset(self):
        with self._lock:
            self._seen = []


def start():
    """A running stub; the caller reads `server_address`, then `requests()`, and ends it with shutdown() and server_close()."""
    server = Stub()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
