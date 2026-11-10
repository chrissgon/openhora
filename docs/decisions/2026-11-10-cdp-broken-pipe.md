## 2026-11-10: a browser that exits before the first write is a CDPError, not a BrokenPipeError (cdp-broken-pipe; no measurement change, no skill changed, no lab run)

`Chrome.send` in `providers/renderer/_cdp.py` wrote to the browser's command pipe with an unguarded `os.write`. When the browser is gone at start
(its `os.execv` fails and the launcher exits 127), `start()` sends `Browser.getVersion` and the write could meet the closed pipe first, raising
`BrokenPipeError` where callers and `test_a_browser_that_cannot_be_executed_says_so_in_one_line` expect `CDPError`. CI run 42777218565 failed that
test once; it is a timing race (the reader thread's "pipe closed" answer wins on most runs).

**Decision.** `send` catches an `OSError` of the write (`BrokenPipeError`, `EPIPE`, or `EBADF` after `close()`), drops its pending slot and raises
`CDPError("browser exited: <method>")`; any other `OSError` still propagates. The one-line reason is unchanged on either path: `browser_reason` reads the
launcher's "exec failed: ..." line from the browser's log, which the launcher writes before it exits, so it is already there when the pipe breaks.
The other pipe operations of the file were checked: `_read_loop` already handles `OSError` and EOF, and `close` already guards its `os.close` calls; `send` holds
the only `os.write`. Two offline tests make the race certain (a child reaped before the first write; a write that raises `BrokenPipeError`, and one that raises
another error); the existing test is unchanged.

**Cost.** `_cdp.py` is in `providers/renderer/image-manifest.json`, so the common renderer image's tag changes; the tag is computed, so no file is edited for it. The
report `engine-contract-2026-11-10-arm64.json` and an earlier decision name the old tag as history and are left as they are.
