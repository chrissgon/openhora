"""The part of a stand-in for Microsoft that the mail and calendar suites share: the Microsoft identity token endpoint and a Graph listener on
127.0.0.1 that records every request, for the offline tests of providers/mailbox/outlook.py and providers/calendar/outlook.py (and their
authorization helpers). Not a test file, and never a copy of the live service: a subclass serves exactly the calls the provider's docstring
names and refuses what the reference says the service refuses. No real account, tenant, key or message is ever involved: every credential of a
test is a made-up string.

What it records, for the assertions: `requests` (method, path, query, the headers in lower case, whether a bearer token came) for the Graph
calls, `token_forms` (every form posted to the token endpoint) and `methods` (every HTTP method the Graph API saw: the provider must send GET
only). Several knobs make it misbehave on purpose: a rotated or malformed token, a wider scope, an error answer, a redirect, a next-page
address that leaves the request.

A subclass sets SCOPE (the one permission its provider asks) and CLIENT_ID, and implements `route(rest, query)` (called with the path after
/v1.0 and the query as a dict of its first values) which answers through `self.json(...)`/`self.error(...)` of the handler it is given.
"""
from __future__ import annotations

import json
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SCOPE_URL_PREFIX = "https://graph.microsoft.com/"
TENANT = "common"
REFRESH_TOKEN = "fake-refresh-token-0-not-real"
ACCESS_TOKEN = "fake-access-token-not-real"
CODE = "fake-authorization-code"
GRAPH_PREFIX = "/v1.0"


class FakeMicrosoft:
    SCOPE = "Mail.Read"
    CLIENT_ID = "11111111-2222-3333-4444-555555555555"

    def __init__(self):
        self.requests, self.token_forms, self.methods = [], [], []
        self.scope_granted = f"{SCOPE_URL_PREFIX}{self.SCOPE} offline_access"   # what the token endpoint says it granted
        self.omit_scope = False             # answer a token with no scope field at all
        self.token_status = 200             # set 400 and token_error to answer an OAuth error
        self.token_error = {"error": "invalid_grant", "error_description": "AADSTS70008: The refresh token has expired."}
        self.code = CODE
        self.no_refresh_token = False       # answer an authorization code with no refresh token
        self.rotate = True                  # every refresh answers a new refresh token; the old one stays valid
        self.rotated_value = None           # answer this refresh token instead of a generated one (a malformed one, say)
        self.valid_refresh = {REFRESH_TOKEN}
        self.rotations = 0
        self.fail_next = None               # (status, headers, body obj): answer the next Graph GET with it
        self.redirect_next = False          # answer the next Graph GET with a 302 elsewhere
        self.access_token = ACCESS_TOKEN    # what the token endpoint issues and Graph accepts
        self.lock = threading.Lock()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                return

            def _send(self, status, body=b"", ctype="application/json", headers=None):
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(body)

            def json(self, status, obj, headers=None):
                self._send(status, json.dumps(obj).encode(), headers=headers)

            def error(self, status, code, message, headers=None):
                self.json(status, {"error": {"code": code, "message": message, "innerError": {"request-id": "fake"}}}, headers)

            def do_POST(self):   # noqa: N802
                parsed = urllib.parse.urlparse(self.path)
                if parsed.path != "/token":
                    with owner.lock:
                        owner.methods.append("POST")
                    return self.error(405, "methodNotAllowed", "no write is served")
                length = int(self.headers.get("Content-Length", "0"))
                form = {k: v[0] for k, v in urllib.parse.parse_qs(self.rfile.read(length).decode()).items()}
                with owner.lock:
                    owner.token_forms.append(form)
                    return self._token(form)

            def _token(self, form):
                if owner.token_status != 200:
                    return self.json(owner.token_status, owner.token_error)
                if form.get("client_id") != owner.CLIENT_ID:
                    return self.json(401, {"error": "invalid_client", "error_description": "AADSTS700016: Application not found."})
                if "client_secret" in form:
                    return self.json(400, {"error": "invalid_client", "error_description": "a public client sends no secret"})
                answer = {"access_token": owner.access_token, "expires_in": 3599, "token_type": "Bearer", "scope": owner.scope_granted}
                if owner.omit_scope:
                    del answer["scope"]
                if form.get("grant_type") == "refresh_token":
                    if form.get("refresh_token") not in owner.valid_refresh:
                        return self.json(400, {"error": "invalid_grant", "error_description": "AADSTS70000: bad refresh token"})
                    if owner.rotate:
                        owner.rotations += 1
                        answer["refresh_token"] = owner.rotated_value or f"fake-refresh-token-{owner.rotations}-not-real"
                        owner.valid_refresh.add(answer["refresh_token"])
                    else:
                        answer["refresh_token"] = form["refresh_token"]
                    return self.json(200, answer)
                if form.get("grant_type") == "authorization_code":
                    if form.get("code") != owner.code or not form.get("code_verifier") or not form.get("redirect_uri"):
                        return self.json(400, {"error": "invalid_grant", "error_description": "AADSTS70000: bad code"})
                    answer["refresh_token"] = REFRESH_TOKEN
                    if owner.no_refresh_token:
                        del answer["refresh_token"]
                    return self.json(200, answer)
                return self.json(400, {"error": "unsupported_grant_type"})

            def _other(self):
                with owner.lock:
                    owner.methods.append(self.command)
                self.error(405, "methodNotAllowed", "no write is served")

            do_PUT = do_PATCH = do_DELETE = _other   # noqa: N815

            def do_GET(self):   # noqa: N802
                parsed = urllib.parse.urlparse(self.path)
                path = urllib.parse.unquote(parsed.path)
                query = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
                auth = self.headers.get("Authorization", "")
                with owner.lock:
                    owner.methods.append("GET")
                    owner.requests.append({"method": "GET", "path": path, "raw_path": parsed.path, "query": query, "auth": bool(auth),
                                           "headers": {k.lower(): v for k, v in self.headers.items()}})
                    redirect, failure = owner.redirect_next, owner.fail_next
                    if redirect:
                        owner.redirect_next = False
                    if failure:
                        owner.fail_next = None
                if redirect:
                    return self._send(302, headers={"Location": "http://127.0.0.1:1/elsewhere"})
                if auth != f"Bearer {owner.access_token}":
                    return self.error(401, "InvalidAuthenticationToken", "Access token is empty or invalid.")
                if failure:
                    status, headers, body = failure
                    return self.json(status, body, headers)
                if not path.startswith(GRAPH_PREFIX + "/"):
                    return self.error(404, "notFound", "not served")
                owner.route(self, path[len(GRAPH_PREFIX):], query)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        self.root = f"http://127.0.0.1:{self.port}"
        self.base = self.root + GRAPH_PREFIX
        self.token_url = f"{self.root}/token"
        self._thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        self._thread.start()

    def route(self, handler, rest, query):   # a subclass answers the Graph calls
        handler.error(404, "notFound", "not served")

    # --- what a test reads -----------------------------------------------------------------------------------------------------

    def record(self, **over):
        record = {"refresh_token": REFRESH_TOKEN, "client_id": self.CLIENT_ID, "tenant": TENANT, "scope": self.SCOPE,
                  "obtained_at": "2026-10-17T08:00:00Z"}
        record.update(over)
        return record

    def record_json(self, **over):
        return json.dumps(self.record(**over))

    def api_requests(self):
        return [r for r in self.requests if r["path"].startswith(GRAPH_PREFIX + "/")]

    def close(self):
        self.server.shutdown()
        self.server.server_close()
