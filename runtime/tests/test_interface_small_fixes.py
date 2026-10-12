"""Tests of two small fixes of the local interface (WP-9.12): the job poll of the client (interface/js/api.js) pauses
while the tab is hidden, and the token prompt's 401 sentence is the one of the flows (design/01-flows.md, FLOW-1).
The poll is run with Node over the real api.js, a stand-in for `fetch`, a fake `document` and a virtual clock (the
test waits no real second). No browser, no model and no service; the served page was looked at in a browser pane by the
package's report.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interface_small_fixes.py
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

import standin_tree as st

INTERFACE = st.REPO / "interface"
JS = INTERFACE / "js"
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node is not installed: the poll is tested only by its text")

# The flows' sentence for a 401 (FLOW-1, failures, in the design's flows), the one the page must show.
FLOWS_401 = "The token was not accepted. The service writes a new token every time it starts: read the token file again."

POLL = r"""
import { setToken } from "@JS@/token.js";

// A virtual clock: setTimeout and clearTimeout run on a time the test moves, so 5 seconds cost no real time.
let now = 0;
let timers = [];
let nextId = 1;
globalThis.setTimeout = (fn, ms) => { const t = { id: nextId++, at: now + (ms || 0), fn }; timers.push(t); return t.id; };
globalThis.clearTimeout = (id) => { timers = timers.filter((t) => t.id !== id); };
const flush = async () => { for (let i = 0; i < 20; i++) await Promise.resolve(); };
async function advance(ms) {
  const end = now + ms;
  for (;;) {
    await flush();
    const due = timers.filter((t) => t.at <= end).sort((a, b) => a.at - b.at)[0];
    if (!due) break;
    timers = timers.filter((t) => t !== due);
    now = due.at;
    due.fn();
  }
  now = end;
  await flush();
}

// A fake document: `hidden` and the visibilitychange listeners.
const listeners = [];
globalThis.document = {
  hidden: false,
  addEventListener(type, fn) { if (type === "visibilitychange") listeners.push(fn); },
  removeEventListener(type, fn) { const at = listeners.indexOf(fn); if (type === "visibilitychange" && at >= 0) listeners.splice(at, 1); },
};
const setHidden = async (hidden) => { document.hidden = hidden; [...listeners].forEach((fn) => fn({ type: "visibilitychange" })); await flush(); };

// A stand-in for fetch: the job runs until `endsAt` (on the virtual clock), then it is done.
let fetches = [];
let endsAt = Infinity;
globalThis.fetch = async (url, init) => {
  fetches.push(now);
  const state = now >= endsAt ? "done" : "running";
  return { ok: true, status: 200, json: async () => ({ job: 7, state, result: state === "done" ? { reply: "ok" } : null, error: null }) };
};
setToken("t".repeat(40));
const api = await import("@JS@/api.js");
const out = {};
const reset = () => { fetches = []; endsAt = Infinity; timers = []; };

// 1. hidden from the start: no request for 5 s; visible: one at once, then every second
reset(); document.hidden = true;
let settled = null;
const p1 = api.pollJob(7, 1000).then((j) => { settled = j.state; });
await advance(5000);
out.hiddenFetches = fetches.length;
out.listenersWhileHidden = listeners.length;
const returnAt = now;
await setHidden(false);
await advance(0);
out.atReturn = fetches.map((t) => t - returnAt);
await advance(3000);
out.afterThree = fetches.map((t) => t - returnAt);
endsAt = now;                      // the job ends now
await advance(1000);
await p1;
out.settled = settled;
out.listenersAfterEnd = listeners.length;

// 2. the tab hides while the poll sleeps: the sleep ends, nothing is asked while hidden; the job ends while hidden and
//    the first poll after the return sees it
reset(); document.hidden = false;
settled = null;
const p2 = api.pollJob(7, 1000).then((j) => { settled = j.state; });
await advance(0);
out.firstFetch = fetches.length;
await setHidden(true);
await advance(4000);
out.hiddenLater = fetches.length;     // still the one poll made before the tab was hidden
endsAt = now;                         // ends while hidden
await advance(2000);
out.stillHidden = fetches.length;
out.settledWhileHidden = settled;
const back = now;
await setHidden(false);
await advance(0);
await p2;
out.seenAtOnce = { fetches: fetches.length, at: fetches[fetches.length - 1] - back, settled };
out.listenersAfterSeen = listeners.length;

// 3. abort while hidden rejects at once and leaves no listener
reset(); document.hidden = true;
const abort = new AbortController();
let rejected = null;
const p3 = api.pollJob(7, 1000, { signal: abort.signal }).catch((e) => { rejected = e.name; });
await advance(2000);
out.abortBefore = [rejected, fetches.length, listeners.length];
abort.abort();
await flush();
out.abortAfter = [rejected, fetches.length, listeners.length];
await p3;

// 4. no document at all (a worker, a test): the poll runs as before
delete globalThis.document;
reset();
const start4 = now;
endsAt = now + 2000;
const p4 = api.pollJob(7, 1000);
await advance(3000);
out.noDocument = [(await p4).state, fetches.map((t) => t - start4)];
console.log(JSON.stringify(out));
"""


def run_node(tmp_path: Path, body: str) -> dict:
    script = tmp_path / "check.mjs"
    script.write_text(body.replace("@JS@", JS.as_uri()), encoding="utf-8")
    done = subprocess.run([NODE, str(script)], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


@needs_node
def test_the_job_poll_pauses_while_the_tab_is_hidden_and_asks_at_once_on_return(tmp_path):
    out = run_node(tmp_path, POLL)
    # hidden for 5 s: no request, and the one listener the poll keeps while it waits
    assert out["hiddenFetches"] == 0, "no request while the tab is hidden"
    assert out["listenersWhileHidden"] == 1
    # visible: one request at once, then one every second
    assert out["atReturn"] == [0]
    assert out["afterThree"] == [0, 1000, 2000, 3000]
    assert out["settled"] == "done" and out["listenersAfterEnd"] == 0, "the promise settles with the job's end and the listener is gone"
    # a job that ends while hidden is seen by the first poll after the return
    assert out["firstFetch"] == 1 and out["hiddenLater"] == 1 and out["stillHidden"] == 1
    assert out["settledWhileHidden"] is None, "the poll has not settled while the tab is hidden"
    assert out["seenAtOnce"] == {"fetches": 2, "at": 0, "settled": "done"}
    assert out["listenersAfterSeen"] == 0
    # abort while paused rejects at once and leaves no listener
    assert out["abortBefore"] == [None, 0, 1]
    assert out["abortAfter"] == ["AbortError", 0, 0]
    # no document: unchanged behaviour
    assert out["noDocument"][0] == "done" and out["noDocument"][1][:3] == [0, 1000, 2000]


def test_the_poll_has_no_second_fetch_path():
    source = (JS / "api.js").read_text(encoding="utf-8")
    assert len(re.findall(r"\btransport\(", source)) == 1 and not re.search(r"\bfetch\(", source), "api.js keeps one network call"


def test_the_token_prompt_shows_the_flows_sentence_for_a_401():
    main = (JS / "main.js").read_text(encoding="utf-8")
    assert f'pendingMessage = "{FLOWS_401}";' in main, "the 401 message is the flows' sentence, verbatim"
    assert "did not accept" not in main and "paste the current one" not in main, "the earlier wording is gone"
