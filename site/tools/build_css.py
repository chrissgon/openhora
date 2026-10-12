#!/usr/bin/env python3
"""Build one minified stylesheet per page from the readable source assets/css/src/site.css.

For each page it keeps, in the source's order (so the cascade is unchanged):
  - every rule with no class in its selector (tokens, elements, @font-face, @keyframes);
  - every rule whose classes all appear in that page's HTML or in the scripts it loads;
then drops a declaration that a later rule with the same selector, in the same at-rule context, sets again.

Usage (from site/):  python3 tools/build_css.py [page ...]   (no page: all seven)
Writes assets/css/<page>.css for index, proof, first-steps, how-its-built, interface, glossary, 404, and prints sizes.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "assets/css/src/site.css"
PAGES = ["index", "proof", "first-steps", "how-it-is-built", "interface", "glossary", "404"]


def parse(text, ctx=()):
    """Yield (context tuple, head, body) for every leaf rule; at-rules other than @media/@supports are leaves."""
    i, n = 0, len(text)
    while i < n:
        j = text.find("{", i)
        if j < 0:
            return
        head = text[i:j].strip()
        depth, k = 1, j + 1
        while k < n and depth:
            depth += {"{": 1, "}": -1}.get(text[k], 0)
            k += 1
        body = text[j + 1:k - 1]
        if head.startswith(("@media", "@supports")):
            yield from parse(body, ctx + (" ".join(head.split()),))
        else:
            yield ctx, " ".join(head.split()), body.strip()
        i = k


def classes_of(sel):
    sel = re.sub(r":not\([^)]*\)", "", sel)  # a class inside :not() need not be on the page
    return set(re.findall(r"\.([a-zA-Z][\w-]*)", re.sub(r"url\([^)]*\)|\[[^\]]*\]", "", sel)))


def used_classes(page):
    html = (ROOT / f"{page}.html").read_text()
    texts = [html] + [(ROOT / m.lstrip("/")).read_text() for m in re.findall(r'<script src="([^"]+)"', html)]
    used = set()
    for t in texts:
        for m in re.finditer(r'class(?:Name)?\s*=\s*"([^"]+)"', t):
            used.update(m.group(1).split())
        for m in re.finditer(r"""classList\.(?:add|remove|toggle|contains)\(\s*["']([\w-]+)""", t):
            used.add(m.group(1))
        for m in re.finditer(r"""["']([a-z][a-z0-9-]*(?: [a-z][a-z0-9-]*)*)["']""", t):  # class strings built in scripts
            used.update(m.group(1).split())
    return used


def split_decls(body):
    out, buf, depth, q = [], "", 0, None
    for ch in body:
        if q:
            buf += ch
            if ch == q:
                q = None
            continue
        if ch in "\"'":
            q = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == ";" and depth == 0:
            out.append(buf.strip()); buf = ""
        else:
            buf += ch
    if buf.strip():
        out.append(buf.strip())
    return [d for d in out if d]


def minify(s):
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"\s*([{};>])\s*", r"\1", s)
    s = re.sub(r",\s+(?![^()]*\))", ",", s)
    return s.replace(";}", "}")


def build(page, rules):
    used = used_classes(page)
    kept = []
    for ctx, head, body in rules:
        if head.startswith("@"):
            kept.append([ctx, head, body, None])
            continue
        sels = [s.strip() for s in head.split(",") if classes_of(s) <= used]
        if sels:
            kept.append([ctx, ",".join(sels), body, split_decls(body)])
    # drop a declaration a later rule with the same context and selector sets again (not !important ones)
    seen = {}
    for idx in range(len(kept) - 1, -1, -1):
        ctx, head, body, decls = kept[idx]
        if decls is None:
            continue
        key = (ctx, head)
        later = seen.setdefault(key, set())
        keep = []
        for d in decls:
            prop = d.split(":", 1)[0].strip().lower()
            if prop in later and "!important" not in d and not prop.startswith("--"):
                continue
            keep.append(d)
        for d in decls:
            later.add(d.split(":", 1)[0].strip().lower())
        kept[idx][3] = keep
    # keyframes: only those named in an animation of this page
    anim_text = " ".join(";".join(r[3]) for r in kept if r[3])
    out, open_ctx = [], ()
    for ctx, head, body, decls in kept:
        if head.startswith("@keyframes"):
            name = head.split()[1]
            if not re.search(r"\b" + re.escape(name) + r"\b", anim_text):
                continue
            text = f"{head}{{{body}}}"
        elif decls is None:
            text = f"{head}{{{body}}}"
        elif not decls:
            continue
        else:
            text = f"{head}{{{';'.join(decls)}}}"
        for c in reversed(ctx):
            text = f"{c}{{{text}}}"
        out.append(text)
    css = minify("".join(out))
    # merge adjacent identical media wrappers
    prev = None
    while prev != css:
        prev = css
        css = re.sub(r"(@media[^{]+)\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}\1\{", r"\1{\2", css)
    return css


def main():
    src = re.sub(r"/\*.*?\*/", "", SRC.read_text(), flags=re.S)
    rules = list(parse(src))
    for page in sys.argv[1:] or PAGES:
        css = build(page, rules)
        (ROOT / f"assets/css/{'home' if page == 'index' else page}.css").write_text(css)
        print(f"{page:15s} {len(css) / 1024:6.1f} KB", file=sys.stderr)


if __name__ == "__main__":
    main()
