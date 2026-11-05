"""A stand-in for the llama.cpp model server, for the tests of a local model (evals/tests/test_local_model_docker.py).

It takes the arguments the real server is started with (-m, --host, --port, -c, --alias, ...) and uses only --port and --alias.
It answers GET /health, GET /v1/models and POST /v1/chat/completions (streamed or not) with a fixed reply and a `usage`, and
writes one line to its log for each request ("seen {method, path, model, stream}"). No model, no weights are read. Standard
library only.
"""
import http.server
import json
import sys
import threading
import time

ARGS = sys.argv[1:]
PORT = int(ARGS[ARGS.index("--port") + 1]) if "--port" in ARGS else 8080
ALIAS = ARGS[ARGS.index("--alias") + 1] if "--alias" in ARGS else "standin"
REPLY = "stand-in reply"
START = time.monotonic()
try:  # a "weights" file that starts with "SLOW <seconds>" makes the server answer /health with 503 for that long, as a loading model does
    with open("/models/model.gguf", "rb") as _f:
        _head = _f.read(32)
    DELAY = float(_head[5:].split()[0]) if _head.startswith(b"SLOW ") else 0.0
except (OSError, ValueError, IndexError):
    DELAY = 0.0
USAGE = {"prompt_tokens": 11, "completion_tokens": 3, "total_tokens": 14}


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def send_json(self, status, doc):
        data = json.dumps(doc).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        print("seen " + json.dumps({"method": "GET", "path": self.path}), flush=True)
        if self.path == "/health":
            if time.monotonic() - START < DELAY:
                self.send_json(503, {"error": {"message": "Loading model", "code": 503}})
            else:
                self.send_json(200, {"status": "ok"})
        elif self.path in ("/v1/models", "/models"):
            self.send_json(200, {"object": "list", "data": [{"id": ALIAS, "object": "model", "owned_by": "standin"}]})
        else:
            self.send_json(404, {"error": {"message": "not found"}})

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        try:
            doc = json.loads(body or b"{}")
        except ValueError:
            doc = {}
        doc = doc if isinstance(doc, dict) else {}
        print("seen " + json.dumps({"method": "POST", "path": self.path, "model": doc.get("model"), "stream": doc.get("stream") is True,
                                    "tools": len(doc.get("tools") or [])}), flush=True)
        if self.path not in ("/v1/chat/completions", "/chat/completions"):
            self.send_json(404, {"error": {"message": "not found"}})
            return
        base = {"id": "chatcmpl-standin", "object": "chat.completion", "created": 1, "model": ALIAS}
        if doc.get("stream") is True:
            chunks = [{**base, "object": "chat.completion.chunk", "choices": [{"index": 0, "delta": {"role": "assistant", "content": ""}, "finish_reason": None}]},
                      {**base, "object": "chat.completion.chunk", "choices": [{"index": 0, "delta": {"content": REPLY}, "finish_reason": None}]},
                      {**base, "object": "chat.completion.chunk", "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
                      {**base, "object": "chat.completion.chunk", "choices": [], "usage": USAGE}]
            data = b"".join(b"data: " + json.dumps(c).encode() + b"\n\n" for c in chunks) + b"data: [DONE]\n\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        else:
            self.send_json(200, {**base, "choices": [{"index": 0, "message": {"role": "assistant", "content": REPLY}, "finish_reason": "stop"}],
                                 "usage": USAGE})


server = http.server.ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
print(f"stand-in: listening on http://0.0.0.0:{PORT}", flush=True)
threading.Thread(target=server.serve_forever, daemon=True).start()
threading.Event().wait()
