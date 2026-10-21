# Model providers

Implementations of the class `model:text` (a role of `providers/resolve.py`, in `ROLES` and in neither `LISTED` nor `contracts/environment.md`, so no skill may require it): one text prompt in, one text reply out. Its one caller is `runtime/interpreter_route.py`; the interface is in `providers/CONTRACT.md` ("Verbs per class"). Selected with `MODEL_TEXT_PROVIDER` (then `MODEL_PROVIDER`); one implementation ships, so it is also chosen when nothing is set.

## `chat-http.py`

A chat-completions request over HTTPS, standard library only (`dependencies = []`, Python 3.9). It holds no route table, no prompt and no key of its own.

| Verb | What it does |
|---|---|
| `--help` | prints the usage |
| `--check` | exit 0 when `MODEL_TEXT_KEY` is set, else exit 3 (`E_KEY`); no connection |
| `complete [--dry-run]` | reads one JSON request on standard input and prints one JSON reply; with `--dry-run` prints `{"would": {"method", "url", "body"}, "would_sha256"}` and reads no key and opens no connection |

**The request** (standard input, version 1): `route` (`id`, `base_url`, `model`, `pin`, `allow_fallbacks`, `data_collection`, `zdr`, `cache_breakpoint`), `accepted` (the sha256 of each route the person accepted), `key_prefix` (4 to 32 printable characters: what every key of the service starts with), `params` (`temperature`, `max_tokens`, `reasoning` `off` or `on`), `system`, `user`, `deadline_ms`. The hash is over `json.dumps(route, ensure_ascii=False, sort_keys=True, separators=(",", ":"))` in UTF-8. The text goes on standard input, never on the command line and never in a file.

**The reply** (standard output): `v`, `text`, `finish` (`stop`, `length` or `other`), `usage` (`input`, `output`, `cache_read`, `cache_write`; an integer or null each), `latency_ms`, `upstream` (the provider that served it, lower case, or null).

**What it refuses before any connection** (exit 3, `E_KEY`): a `MODEL_TEXT_KEY` that does not start with the request's `key_prefix`, so a credential of another service never reaches this one. The provider names no vendor: the prefix arrives in the request, from the caller's closed table of shapes (`runtime/interpreter_route.py`, `KEY_SHAPES`). It is no part of the route, of the route's hash or of the body sent upstream, and a missing, shorter-than-4 or longer-than-32-character prefix is `E_USAGE` (exit 2). With `--dry-run` the prefix is checked for its form and no key is read.

**What it refuses before any connection** (exit 3, `E_ROUTE`): a route whose hash is not in `accepted` (a route changed after it was accepted is another route); a `base_url` that is not `https`, has a login, a query or a fragment; `allow_fallbacks` other than false; `data_collection` other than `deny`. `MODEL_TEXT_LOOPBACK_TEST=1` additionally lets an `http` address on `127.0.0.1`, `::1` or `localhost` through; it is for the test stand-in and nothing in the runtime sets it. The request always carries `provider: {allow_fallbacks: false, data_collection: "deny", zdr}`, with `order: [pin]` when the route has a pin. No redirect is followed, and no proxy variable is read.

**The deadline** is hard: `deadline_ms` is a timer (`SIGALRM`) over the whole exchange, connection and every read included, so a service that sends one byte at a time is cut at the deadline (`E_TIMEOUT`). **The text** must be encodable: a lone surrogate in `system` or `user` is `E_USAGE`; the reply is printed ASCII-escaped, so no text can fail to print.

**The key** arrives only as `MODEL_TEXT_KEY` in the process environment (`runtime/interpreter_route.py` reads it through the secret resolver, checks its shape against the route's `key_prefix` and passes it, the writers' precedent); this file never reads the store and checks the shape again, so it holds even for a caller that skipped the first check.

**Failures.** The only output is one line on standard error, `chat-http: <CODE>`: never a request, a reply body, a URL, a key or a traceback, not even from an unexpected exception. The caller reads that one line and nothing else.

| Code | Exit | When |
|---|---|---|
| `E_USAGE` | 2 | a bad command, or a request that is not the shape above |
| `E_KEY`, `E_ROUTE` | 3 | no usable key, or a key that does not start with `key_prefix`; a route that is not accepted or widens |
| `E_TIMEOUT`, `E_NETWORK` | 1 | the deadline passed; the connection failed |
| `E_RATE`, `E_UPSTREAM` | 1 | status 429; status 500 or above |
| `E_HTTP` | 1 | any other status that is not 200, a redirect included |
| `E_PIN` | 1 | the reply names another provider than the route's pin |
| `E_RESPONSE` | 1 | the reply is not JSON, is over 65,536 bytes or has no text |
| `E_INTERNAL` | 1 | anything else |

**Tests** (`providers/model/tests/`) run against a stand-in service on loopback (`chat_http_stub.py`) with the fake key `sk-test-not-a-key` (and `test_chat_http_keyshape.py` for the shape check); no test reaches a real service, and the folder names no vendor and no model (a test fails if it does).
