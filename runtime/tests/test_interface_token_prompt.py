"""Tests of ADJ-B3 (A-39): the token prompt shows the command that reads the token file, in two steps. No browser and no model: the
modules run under Node with a fake document and a fake platform, so what the prompt shows for each system, what Copy puts on the
clipboard and what it shows when the service gave no path are checked. The served page was looked at in the browser pane by the
package's report.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interface_token_prompt.py
"""
from __future__ import annotations

import re

import standin_tree as st
from test_interface_plates_meters import needs_node, run_node
from interface_css import interface_css

INTERFACE = st.REPO / "interface"
JS = INTERFACE / "js"
service = st.load("service")

FALLBACK = ("The token is in the file whose path the service printed when it started (the \"token_file\" value of its first line); "
            "open that file and paste its one line here.")
CLIPBOARD = "It copies the token to the clipboard. The token itself is never shown on this page."
PRINTS = "It prints the token in the terminal; the token itself is never shown on this page."
PATH = "/home/demo/my shop/it's/service.token"          # the page never sees this: only the strings the service built from it
COMMANDS = {"macos": "pbcopy < '/home/demo/my shop/it'\"'\"'s/service.token'", "linux": "cat '/home/demo/my shop/it'\"'\"'s/service.token'",
            "powershell": "Get-Content -LiteralPath '/home/demo/my shop/it''s/service.token' | Set-Clipboard"}

PROMPT = r"""
import { FakeNode, settle, find, all } from "@FAKE@";
import { showTokenPrompt, systemOf } from "@JS@/views/token-prompt.js";

const COMMANDS = @COMMANDS@;
const out = {};
const later = [];
const written = [];
const env = { clipboard: { writeText: async (t) => { written.push(t); } }, select: () => false, later: (fn) => later.push(fn) };

async function draw(platform, tokenFile, extra = {}) {
  const root = new FakeNode("div");
  let submitted = null;
  showTokenPrompt(root, { message: null, onSubmit: async (t) => { submitted = t; }, platform, tokenFile, copyEnv: env, ...extra });
  const before = find(root, ".wb-token-how") ? find(root, ".wb-token-how").textContent : null;
  await settle();
  const code = find(root, ".wb-command-code");
  const labels = all(root, ".wb-token-label").map((n) => n.textContent);
  return {
    root, before, labels, code: code ? code.textContent : null,
    system: find(root, ".wb-token-system") ? find(root, ".wb-token-system").textContent : null,
    help: find(root, ".wb-token-help") ? find(root, ".wb-token-help").textContent : null,
    plain: all(root, ".wb-token-how p").map((n) => n.textContent),
    field: find(root, "#token-field"), button: find(root, "button[type=submit]"), copy: find(root, "button.wb-copy"),
    fieldLabel: find(root, "label[for=token-field] span") ? find(root, "label[for=token-field] span").textContent : null,
    submitted: () => submitted,
  };
}
const shape = (d) => ({ labels: d.labels, code: d.code, system: d.system, help: d.help, fieldLabel: d.fieldLabel, button: d.button.textContent, plain: d.plain });

out.hinted = [
  systemOf("MacIntel", { touchPoints: 5 }), systemOf("MacIntel", { touchPoints: 0 }), systemOf("MacIntel", { touchPoints: 1 }), systemOf("MacIntel", {}),
  systemOf("Linux armv8l", { userAgent: "Mozilla/5.0 (Android 14; Mobile; rv:130.0) Gecko/130.0 Firefox/130.0" }),
  systemOf("Linux x86_64", { userAgent: "Mozilla/5.0 (X11; Linux x86_64; rv:130.0) Gecko/20100101 Firefox/130.0" }),
  systemOf("Win32", { userAgent: "Mozilla/5.0 (Windows NT 10.0)" }), systemOf("Linux", undefined), systemOf("Linux", null),
];
for (const [name, platform, hints] of [["ipad", "MacIntel", { touchPoints: 5, userAgent: "Mozilla/5.0 (Macintosh)" }], ["android", "Linux armv8l", { touchPoints: 5, userAgent: "Mozilla/5.0 (Android 14)" }]]) {
  out[name] = shape(await draw(platform, async () => ({ token_file: "/x", commands: COMMANDS }), { hints }));
}
out.systems = ["MacIntel", "macOS", "Win32", "Windows", "Linux x86_64", "Linux", "X11", "iPhone", "", null, undefined, 7].map((p) => [String(p), systemOf(p)]);

for (const [name, platform] of [["mac", "MacIntel"], ["linux", "Linux x86_64"], ["windows", "Win32"]]) {
  const d = await draw(platform, async () => ({ token_file: "/x", commands: COMMANDS }));
  out[name] = shape(d);
  out[name + "Before"] = d.before;
}

// Copy puts the server's string on the clipboard, whole, and the button says Copied until the moment passes
const d = await draw("MacIntel", async () => ({ token_file: "/x", commands: COMMANDS }));
d.copy.click();
await settle();
out.copy = { written: written.slice(), button: d.copy.textContent, name: d.copy.attrs["aria-label"], later: later.length };
later.forEach((fn) => fn());
out.copyBack = d.copy.textContent;

// the field still works: the token typed is what is submitted, and the field is cleared
const token = "a".repeat(64);
d.field.value = token;
const form = find(d.root, "form");
for (const fn of form.listeners.submit || []) await fn({ preventDefault() {} });
out.submitted = d.submitted() === token;

// every case in which the prompt keeps the sentence it had
const keeps = {};
keeps.noReader = shape(await draw("MacIntel", undefined));
keeps.rejected = shape(await draw("MacIntel", async () => { const e = new Error("not found"); e.status = 404; throw e; }));
keeps.networkFailure = shape(await draw("MacIntel", () => Promise.reject(new Error("down"))));
keeps.nothing = shape(await draw("MacIntel", async () => null));
keeps.noCommands = shape(await draw("MacIntel", async () => ({ token_file: null, commands: null })));
keeps.noKey = shape(await draw("Linux", async () => ({ token_file: "/x", commands: { macos: "pbcopy < /x" } })));
keeps.emptyCommand = shape(await draw("Linux", async () => ({ token_file: "/x", commands: { linux: "   " } })));
keeps.notText = shape(await draw("Linux", async () => ({ token_file: "/x", commands: { linux: { cmd: "cat" } } })));
keeps.unknownSystem = shape(await draw("Nintendo Switch", async () => ({ token_file: "/x", commands: COMMANDS })));
out.keeps = keeps;

// text from the service is text
const hostile = await draw("Linux", async () => ({ token_file: "/x", commands: { linux: "cat '/x/<b>y</b>'" } }));
out.hostile = [hostile.code, all(hostile.root, "b").length];

// the read is asked once, and a slow read leaves the field in place
let asked = 0;
let release;
const slow = new Promise((resolve) => { release = resolve; });
const pending = await draw("MacIntel", () => { asked += 1; return slow; }, {});
out.slow = { asked, hasField: Boolean(pending.field), code: pending.code, plainBefore: pending.plain };
release({ token_file: "/x", commands: COMMANDS });
await settle();
out.slowAfter = find(pending.root, ".wb-command-code") ? find(pending.root, ".wb-command-code").textContent : null;
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_prompt_shows_two_steps_with_the_command_of_the_browsers_system_and_keeps_its_sentence_otherwise(tmp_path):
    got = run_node(tmp_path, PROMPT.replace("@COMMANDS@", __import__("json").dumps(COMMANDS)))
    assert got["systems"] == [["MacIntel", "macos"], ["macOS", "macos"], ["Win32", "windows"], ["Windows", "windows"], ["Linux x86_64", "linux"],
                              ["Linux", "linux"], ["X11", "linux"], ["iPhone", None], ["", None], ["null", None], ["undefined", None], ["7", None]]
    step1, step2 = "1 · Run this in a terminal", "2 · Paste the token"
    assert got["mac"] == {"labels": [step1, step2], "code": COMMANDS["macos"], "system": "macOS", "help": CLIPBOARD, "fieldLabel": step2,
                          "button": "Continue", "plain": []}, "step 1 is the command with the system's name beside it; step 2 is the field and Continue"
    assert got["linux"]["code"] == COMMANDS["linux"] and got["linux"]["system"] == "Linux" and got["linux"]["help"] == PRINTS
    assert got["windows"]["code"] == COMMANDS["powershell"] and got["windows"]["system"] == "Windows" and got["windows"]["help"] == CLIPBOARD
    assert got["macBefore"] == "" and got["linuxBefore"] == "", "until the service has answered nothing stands where the steps will be"
    assert got["copy"] == {"written": [COMMANDS["macos"]], "button": "Copied", "name": "Copy the command", "later": 1}, "Copy writes the service's string, whole"
    assert got["copyBack"] == "Copy", "and the button goes back after a moment"
    assert got["submitted"] is True
    for name, kept in got["keeps"].items():
        assert kept == {"labels": [], "code": None, "system": None, "help": None, "fieldLabel": "Access token", "button": "Continue", "plain": [FALLBACK]}, \
            f"{name}: without a command for this system the prompt keeps the sentence about the first line"
    assert got["hinted"] == [None, "macos", "macos", "macos", None, "linux", "windows", "linux", "linux"], \
        "a touch device that says MacIntel and an Android user agent are unknown; the platform string is a hint"
    for name in ("ipad", "android"):
        assert got[name] == {"labels": [], "code": None, "system": None, "help": None, "fieldLabel": "Access token", "button": "Continue", "plain": [FALLBACK]}, name
    assert got["hostile"] == ["cat '/x/<b>y</b>'", 0]
    assert got["slow"] == {"asked": 1, "hasField": True, "code": None, "plainBefore": []}
    assert got["slowAfter"] == COMMANDS["macos"]


API = r"""
import { setToken, clearToken } from "@JS@/token.js";
import * as api from "@JS@/api.js";

const out = {};
const seen = [];
let answer = { status: 200, body: { token_file: "/x", commands: { linux: "cat /x" } } };
globalThis.fetch = async (url, init) => {
  seen.push({ url, method: init.method, headers: init.headers, credentials: init.credentials, cache: init.cache, mode: init.mode, referrerPolicy: init.referrerPolicy });
  return { ok: answer.status < 300, status: answer.status, json: async () => answer.body };
};
let authFailures = 0;
api.onAuthFailure(() => { authFailures += 1; });

clearToken();
out.noToken = await api.tokenFile();
out.noTokenRequest = seen[0];
answer = { status: 404, body: { error: "not_found", message: "no such route, project or file" } };
try { await api.tokenFile(); out.rejected = null; } catch (e) { out.rejected = [e.name, e.status, e.word]; }
answer = { status: 200, body: { token_file: null, commands: null } };
out.nullAnswer = await api.tokenFile();
// with a token held the request is the same: no header, so the token never leaves for an unauthenticated route
setToken("t".repeat(64));
answer = { status: 200, body: { token_file: "/x", commands: {} } };
await api.tokenFile();
out.withToken = seen[seen.length - 1];
out.authFailures = authFailures;
await api.status("0123456789ab");
out.authenticated = seen[seen.length - 1];
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_client_reads_the_token_file_route_without_a_token_and_never_sends_the_token_to_it(tmp_path):
    got = run_node(tmp_path, API)
    assert got["noToken"] == {"token_file": "/x", "commands": {"linux": "cat /x"}}
    request = got["noTokenRequest"]
    assert request["url"] == "/token-file" and request["method"] == "GET", "a same-origin path outside /api/v1, which holds no token"
    assert "Authorization" not in request["headers"] and request["headers"]["Accept"] == "application/json"
    assert (request["credentials"], request["cache"], request["mode"], request["referrerPolicy"]) == ("omit", "no-store", "same-origin", "no-referrer")
    assert got["rejected"] == ["ApiError", 404, "not_found"], "an older service answers 404; the caller decides, the client does not ask for a token"
    assert got["nullAnswer"] == {"token_file": None, "commands": None}
    assert "Authorization" not in got["withToken"]["headers"], "even with a token held, the route gets no bearer header"
    assert got["authFailures"] == 0, "no token is not a failure of this read"
    assert got["authenticated"]["url"] == "/api/v1/projects/0123456789ab/status" and got["authenticated"]["headers"]["Authorization"] == "Bearer " + "t" * 64


def test_the_client_names_the_services_route_and_the_page_spells_no_command():
    api = (JS / "api.js").read_text(encoding="utf-8")
    assert re.search(r'const TOKEN_FILE = "([^"]+)"', api).group(1) == service.TOKEN_FILE_ROUTE == "/token-file", "the client's path is the service's"
    assert len(re.findall(r"\bfetch\(", api)) == 1, "still one way to reach the service"
    prompt = (JS / "views" / "token-prompt.js").read_text(encoding="utf-8")
    for spelled in ("pbcopy", "Set-Clipboard", "Get-Content", "-LiteralPath", "shlex", "cat "):
        assert spelled not in prompt, f"the prompt spells no command of its own: {spelled}"
    assert not re.search(r"commands\.\w+\s*\+|\+\s*commands\.|`[^`]*\$\{[^}]*(?:token_file|path)[^}]*\}", prompt), "no path is joined into a command"
    main = (JS / "main.js").read_text(encoding="utf-8")
    assert "tokenFile:" in main and "api.tokenFile" in main, "the page hands the prompt the read"
    css = interface_css()
    for name in sorted(set(re.findall(r'"(wb-token-[a-z-]+)"', prompt))):
        assert re.search(r"\." + name + r"(?![\w-])", css), f"{name} is a rule of the stylesheet"
