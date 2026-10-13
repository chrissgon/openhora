"""Static lint of an HTML template: the determinism contract (plan A1).

A template is a pure function renderAt(t, data). It must contain none of: CSS animation or transition,
Date, performance.now, Math.random, requestAnimationFrame, timers, <video>, <audio>, <iframe>, fetch,
XMLHttpRequest, WebSocket, Worker, dynamic import, any src/href/url() or import of an external resource,
and no markup injection (innerHTML, outerHTML, insertAdjacentHTML, document.write, eval, new Function).
Text is set with textContent only.
"""
import re

RULES = [
    ("css-keyframes", r"@keyframes"),
    ("css-transition", r"\btransition\s*:|\btransition-(property|duration|delay|timing-function)\b|\.style\.transition\b"),
    ("css-animation", r"\banimation(-[a-z]+)?\s*:|\.style\.animation\b|\.animate\s*\("),
    ("date", r"\bDate\b"),
    ("performance-now", r"performance\s*\.\s*now"),
    ("math-random", r"Math\s*\.\s*random"),
    ("raf", r"requestAnimationFrame|cancelAnimationFrame"),
    ("timers", r"\b(setTimeout|setInterval|setImmediate|requestIdleCallback)\b"),
    ("media-element", r"<\s*(video|audio|iframe|embed|object|link)\b"),
    ("network", r"\b(fetch|XMLHttpRequest|WebSocket|EventSource|sendBeacon)\b"),
    ("worker", r"\b(Worker|SharedWorker|importScripts)\b|navigator\s*\.\s*serviceWorker"),
    ("dynamic-import", r"\bimport\s*\(|^\s*import\s"),
    ("external-src", r"\b(src|href|srcset|poster|action|formaction)\s*=|\burl\s*\(|@import"),
    ("markup-injection", r"\b(innerHTML|outerHTML|insertAdjacentHTML|document\s*\.\s*write(ln)?|srcdoc)\b|\beval\s*\(|new\s+Function\b"),
]
_COMPILED = [(name, re.compile(rx, re.M)) for name, rx in RULES]


def lint(html):
    """Return a sorted list of rule names that the template breaks (empty = clean)."""
    return sorted({name for name, rx in _COMPILED if rx.search(html)})
