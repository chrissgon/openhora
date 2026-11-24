"""The reduced escape lint of an admitted page (the second contract, decision of PF-a2, R3-2).

It runs over every file an admitted entry serves, after the entry's edits, as text with the comments kept. It refuses the ways a page can reach
outside its own box: frames and links, anything remote, storage, the browser's top layer, markup built from data, the network, media, workers,
fonts a page loads itself and the GPU.

What it is not: a determinism lint. The HyperFrames runtime and GSAP read clocks and timers by design (the virtual-time shim replaces them), so
determinism is a recorded test (3 forward runs and 1 reverse run with identical hashes), not a text rule.

What it cannot do: a text lint is evadable by computed keys (`window["fe"+"tch"]("/x")` passes it). It is a first screen, not the wall. What
holds is the page policy (`connect-src 'none'`), the interception that serves only what the host put in memory and fails and records the rest
(a recorded block fails the render), and the exact pixel gates on every frame the page draws.

`PLANTED` holds, for every rule, one snippet that must be refused and one near miss that must pass; `self_test()` runs it and `check()` runs it
first, so a rule that was loosened or broken stops every admission and every render. Standard library only.
"""
from __future__ import annotations

import re

from _text import Refusal

# (category, rule, regex, flags). Each regex is searched in the text of one file.
_I = re.IGNORECASE
RULES = (
    ("frames", "iframe", r"<\s*(?:iframe|frame|object|embed)\b", _I),
    ("frames", "srcdoc", r"\bsrcdoc\b", _I),
    ("links", "link", r"<\s*link\b", _I),
    ("remote", "url", r"https?://", _I),
    ("remote", "protocol-relative", r"""(?:\b(?:src|href)\s*=\s*["']?|url\(\s*["']?)\s*//""", _I),
    ("remote", "dynamic-import", r"\bimport\s*\(", 0),
    ("remote", "static-import", r"""(?m)^\s*import\s*(?:[\w{*][^;\n]*?\sfrom\s*)?["']""", 0),
    ("remote", "css-import", r"@import\b", _I),
    ("remote", "import-scripts", r"\bimportScripts\b", 0),
    ("storage", "storage", r"\b(?:localStorage|sessionStorage|indexedDB)\b", 0),
    ("storage", "cookie", r"\bdocument\s*\.\s*cookie\b", 0),
    ("storage", "caches", r"\bcaches\s*\.", 0),
    ("storage", "navigator-storage", r"\bnavigator\s*\.\s*storage\b", 0),
    ("storage", "broadcast", r"\bBroadcastChannel\b", 0),
    ("top-layer", "modal", r"\b(?:showModal|showPopover|requestFullscreen|requestPointerLock)\b", 0),
    ("top-layer", "popover", r"\bpopover\b", _I),
    ("top-layer", "window-open", r"\bwindow\s*\.\s*open\b", 0),
    ("top-layer", "dialogs", r"(?<![\w$.])(?:alert|confirm|prompt)\s*\(", 0),
    ("top-layer", "print", r"(?<![\w$])print\s*\(", 0),
    ("markup-from-data", "inner-html", r"\b(?:innerHTML|outerHTML|insertAdjacentHTML)\b", 0),
    ("markup-from-data", "document-write", r"\bdocument\s*\.\s*write(?:ln)?\b", 0),
    ("markup-from-data", "eval", r"(?<![\w$.])eval\s*\(", 0),
    ("markup-from-data", "new-function", r"\bnew\s+Function\b", 0),
    ("markup-from-data", "event-attribute", r"""\bsetAttribute\s*\(\s*["']on""", _I),
    ("network", "fetch", r"(?<![\w$])fetch\s*\(", 0),
    ("network", "xhr", r"\bXMLHttpRequest\b", 0),
    ("network", "socket", r"\b(?:WebSocket|EventSource|WebTransport|RTCPeerConnection)\b", 0),
    ("network", "beacon", r"\bsendBeacon\b", 0),
    ("media", "media", r"<\s*(?:video|audio)\b", _I),
    ("workers", "worker", r"(?<![\w$])(?:Worker|SharedWorker)\s*\(", 0),
    ("workers", "service-worker", r"\bserviceWorker\b", 0),
    ("fonts", "fontface", r"\bFontFace\b", 0),
    ("fonts", "font-face-rule", r"@font-face\b", _I),
    ("gpu", "gpu", r"\bnavigator\s*\.\s*gpu\b|\bdata-requires-webgpu\b", _I),
)

# (rule, a snippet that must be refused, a near miss that must pass)
PLANTED = (
    ("iframe", '<iframe src="x"></iframe>', "<div class=\"iframe-note\">frame rate</div>"),
    ("srcdoc", '<div srcdoc="x"></div>', "<div data-doc=\"x\"></div>"),
    ("link", '<link rel="stylesheet" href="a.css">', "<div data-link=\"a\"></div>"),
    ("url", '<img src="https://example.test/a.png">', '<img src="/h/a.png">'),
    ("protocol-relative", '<script src="//example.test/a.js"></script>', '<script src="/h/a.js"></script>'),
    ("dynamic-import", 'import("/h/x.js")', "var important = 1;"),
    ("static-import", 'import { a } from "./x.js";', "var s = 'important';"),
    ("css-import", '@import url("a.css");', "/* imports nothing */"),
    ("import-scripts", 'importScripts("x.js")', "var scripts = 1;"),
    ("storage", 'window.localStorage.setItem("a", "b")', "var store = 1;"),
    ("cookie", 'var c = document.cookie;', "var c = 'document-cookie';"),
    ("caches", 'caches.open("a")', "var caches1 = 1;"),
    ("navigator-storage", 'navigator.storage.estimate()', "navigator.language"),
    ("broadcast", 'new BroadcastChannel("a")', "var broadcastChannelName = 1;"),
    ("modal", 'dlg.showModal()', "dlg.show()"),
    ("popover", '<div popover>a</div>', "<div class=\"pop\">a</div>"),
    ("window-open", 'window.open("a")', "window.opener"),
    ("dialogs", 'alert("a")', "el.alerted = 1; var promptly = 2;"),
    ("print", 'window.print()', "blueprint(1)"),
    ("inner-html", 'el.innerHTML = a;', "el.textContent = a;"),
    ("document-write", 'document.write("a")', "document.title"),
    ("eval", 'eval("1")', "var retrieval = 1;"),  # security-scan: allow dynamic-eval -- a planted page-script snippet the lint must refuse, never run
    ("new-function", 'new Function("return 1")', "var functions = 1;"),
    ("event-attribute", 'el.setAttribute("onclick", "x()")', 'el.setAttribute("class", "a")'),
    ("fetch", 'fetch("/x")', "var prefetchHint = 1;"),
    ("xhr", 'new XMLHttpRequest()', "var xhrLike = 1;"),
    ("socket", 'new WebSocket("a")', "var socketNumber = 1;"),
    ("beacon", 'navigator.sendBeacon("/x")', "var beaconColour = 1;"),
    ("media", '<video src="a"></video>', "<div data-video=\"a\"></div>"),
    ("worker", 'new Worker("a.js")', "var workers = 1;"),
    ("service-worker", 'navigator.serviceWorker.register("a")', "var service = 1;"),
    ("fontface", 'new FontFace("a", "url(b)")', "var fontFaceName = 1;"),
    ("font-face-rule", '@font-face { font-family: a; }', "font-family: a;"),
    ("gpu", 'navigator.gpu.requestAdapter()', "navigator.hardwareConcurrency"),
)

_COMPILED = [(cat, rule, re.compile(pattern, flags)) for cat, rule, pattern, flags in RULES]


def scan(name: str, text: str) -> list:
    """[(category, rule, line)] for one file's text, in order of appearance."""
    out = []
    for cat, rule, rx in _COMPILED:
        for m in rx.finditer(text):
            out.append((cat, rule, text.count("\n", 0, m.start()) + 1))
    return sorted(out, key=lambda x: (x[2], x[1]))


def self_test() -> None:
    """Run PLANTED: every rule must refuse its snippet and pass its near miss, and every rule must have a row. Raises RuntimeError otherwise."""
    rules = {rule for _cat, rule, _p, _f in RULES}
    if {row[0] for row in PLANTED} != rules or len(PLANTED) != len(rules):
        raise RuntimeError("the planted table does not cover the rules one for one")
    for rule, bad, good in PLANTED:
        if rule not in {r for _c, r, _l in scan("planted", bad)}:
            raise RuntimeError("the lint did not refuse its planted snippet: %s" % rule)
        if scan("planted", good):
            raise RuntimeError("the lint refused its near miss: %s" % rule)


def check(files: dict) -> None:
    """Refuse (`block_lint`, field `<rule>:<file>:<line>`) the first finding in any file; `files` is {name: bytes or str}. Runs `self_test` first."""
    try:
        self_test()
    except RuntimeError as exc:
        raise Refusal("block_lint", "self_test") from exc
    for name in sorted(files):
        raw = files[name]
        try:
            text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        except UnicodeDecodeError:
            raise Refusal("block_lint", "encoding:%s:0" % re.sub(r"[^A-Za-z0-9._-]", "_", name)[:40]) from None
        found = scan(name, text)
        if found:
            _cat, rule, line = found[0]
            raise Refusal("block_lint", "%s:%s:%d" % (rule, re.sub(r"[^A-Za-z0-9._-]", "_", name)[:40], line))
