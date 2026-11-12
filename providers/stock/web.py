#!/usr/bin/env python3
"""stock:media on the open web: fetch the file at a URL that a model's web search wrote (package V9b-1c, decisions D6 to D8 of the V9b spec).

This is the one place in the workbench where a URL written by a model is opened, and it is opened only through the checks of providers/stock/_net.py
(`fetch_open`): https on 443, a public host name (no IP literal), every address global and the connection opened to the one checked, at most two redirects each
checked again, no cookie, `Authorization` or `Referer`, a size cap before and while the body is read, and the file's type read from its first bytes (PNG, JPEG,
MP4, WebM) before a byte is written. Nothing is decoded here and no HTML is ever kept. The file lands 0600 in `<task's stock folder>/quarantine`, named
`q-<sha256 first 12>.<png|jpg|mp4|webm>`; it leaves quarantine only at the runtime's per-asset approval (V9b-3).

The provider never searches: the search is the model's (a contained run on the open network, V9b-3b). Its candidates carry the licence id `unverified`, which is
never an accepted licence, so a source of this tier is refused unless the caller passes `--allow-unverified`, which the runtime passes only when the project's own
switch is on. A page URL is never fetched here; it is kept by the runtime as text.

  preview --source-file F --today D --kind image|clip --url U --out DIR --max-bytes B [--refuse-host H]... [--allow-host H]... --allow-unverified
  fetch   --source-file F --today D --kind image|clip --url U --out DIR --max-bytes B [--refuse-host H]... [--allow-host H]... --allow-unverified

`preview` is the picture a person looks at before choosing: always an image (PNG or JPEG), at most 4 MiB, within 30 s (the thumbnail of a clip is an image).
`fetch` is the file itself: an image (16 MiB, 60 s) or a clip (MP4 or WebM, 120 MiB, 180 s). `--max-bytes` can only lower a cap. `--refuse-host` and `--allow-host` are the
person's lists (a name matches itself and its sub-domains; an empty allow list allows every public host).

Answers `{"ok", "file", "bytes", "sha256", "type", "host"}` on stdout: the file's name inside `DIR`, never the URL. A refusal prints `{"ok": false, "code": <closed word>,
"fields": []}` (`fields` names the null fields of a source file that is not ready, never a value). Diagnostics on stderr hold the code and, when one was reached, the host: never a URL, a path or a query. Exit codes: 0 ok, 1 failed, 2 usage, 3 not
configured. Standard library only; runs on Python 3.9.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _net  # noqa: E402
import _stock  # noqa: E402

SERVES = "stock:media"
SOURCE = "web"
VERBS = ("preview", "fetch")
MIB = 1024 * 1024
CAPS = {"preview_bytes": 4 * MIB, "image_bytes": 16 * MIB, "clip_bytes": 120 * MIB,
        "preview_seconds": 30, "image_seconds": 60, "clip_seconds": 180,
        "host_list": 100}                 # entries of one --refuse-host or --allow-host list
PER_VIDEO = {"previews": 18, "files": 6}      # counted by the runtime (V9b-3b), which reads them from here
PREVIEW_TYPES = ("image/png", "image/jpeg")
TYPES = {"image": PREVIEW_TYPES, "clip": ("video/mp4", "video/webm")}


class _Parser(argparse.ArgumentParser):
    """argparse echoes a bad argument in its message, and an argument can be a URL: the text here is fixed."""

    def error(self, message):
        sys.stderr.write("web: usage error\n")
        raise SystemExit(2)


def parser() -> argparse.ArgumentParser:
    p = _Parser(prog="web.py", description=(__doc__ or "").strip(), allow_abbrev=False, formatter_class=argparse.RawDescriptionHelpFormatter,
                epilog="Exit codes: 0 ok, 1 failed, 2 usage, 3 not configured. Every refusal prints {\"ok\": false, \"code\": <closed word>} on stdout.")
    p.add_argument("--source-file", help="providers/stock/sources/web.json")
    p.add_argument("--today", help="YYYY-MM-DD from `date +%%F`, never from memory")
    sub = p.add_subparsers(dest="verb", parser_class=_Parser)
    for name, text in (("preview", "the picture of a candidate: an image, at most 4 MiB"), ("fetch", "the file itself, into quarantine")):
        v = sub.add_parser(name, allow_abbrev=False, help=text)
        v.add_argument("--kind", required=True, choices=_stock.KINDS)
        v.add_argument("--url", required=True, help="an https URL a model wrote; it is never printed")
        v.add_argument("--out", required=True, help="<task>/stock/quarantine: a folder of this user, mode 0700, not inside a reference store")
        v.add_argument("--max-bytes", type=int, required=True, help="a cap that can only lower the verb's own")
        v.add_argument("--refuse-host", action="append", default=[], help="a host the person refuses (and its sub-domains); repeatable")
        v.add_argument("--allow-host", action="append", default=[], help="a host the person allows (and its sub-domains); repeatable")
        v.add_argument("--allow-unverified", action="store_true", help="the project turned the unverified tier on")
    return p


def _hosts(values, name) -> list:
    """A list of the person's host names: each lower case and a valid host name, at most CAPS["host_list"]; else query_refused (usage)."""
    if len(values) > CAPS["host_list"] or not all(isinstance(h, str) and h == h.lower() and _net.valid_host(h) for h in values):
        raise _stock.Refusal("query_refused", "%s is a list of host names" % name)
    return list(values)


def do_fetch(args) -> dict:
    src = _stock.read_source(args.source_file, args.today, SOURCE, None)
    if args.kind not in src["kinds"]:
        raise _stock.Refusal("query_refused", "this source does not serve that kind")
    if not args.allow_unverified:
        raise _stock.Refusal("licence_refused", "a source of the unverified tier is refused unless the project turned that tier on")
    if not isinstance(args.max_bytes, int) or args.max_bytes <= 0:
        raise _stock.Refusal("query_refused", "--max-bytes is a positive number")
    refuse, allow = _hosts(args.refuse_host, "--refuse-host"), _hosts(args.allow_host, "--allow-host")
    if args.verb == "preview":
        types, cap, seconds = PREVIEW_TYPES, CAPS["preview_bytes"], CAPS["preview_seconds"]
    else:
        types, cap, seconds = TYPES[args.kind], CAPS[args.kind + "_bytes"], CAPS[args.kind + "_seconds"]
    folder = _net.check_quarantine(args.out)
    got = _net.fetch_open(args.url, min(args.max_bytes, cap), folder, types, refuse_hosts=refuse, allow_hosts=allow, timeout=seconds)
    return {"ok": True, "file": os.path.basename(got["file"]), "bytes": got["bytes"], "sha256": got["sha256"], "type": got["type"], "host": got["host"],
            "_redirects": got["redirects"]}


def main(argv=None, out=None, err=None) -> int:
    """One verb: prints one JSON object on `out` and returns the exit code."""
    out, err = out or sys.stdout, err or sys.stderr
    args = parser().parse_args(argv)
    if not args.verb or not args.source_file or not args.today:
        err.write("usage: preview or fetch, with --source-file and --today\n")
        return 2
    try:
        _stock.pin_source(args.source_file, sys.modules[__name__])
        answer = do_fetch(args)
        redirects = answer.pop("_redirects")
        text = json.dumps(answer, sort_keys=True, allow_nan=False)
    except _stock.Refusal as stop:
        return _refuse(out, err, stop.code, stop.reason, None, stop.exit_code, stop.fields)
    except _net.NetError as stop:
        return _refuse(out, err, stop.code, stop.code, getattr(stop, "host", None), _stock.EXIT.get(stop.code, 1))
    except Exception:        # anything else: a fixed refusal, never the exception's text, which could hold a URL
        return _refuse(out, err, "network", "the verb failed", None, 1)
    out.write(text + "\n")
    err.write("web: ok host=%s redirects=%d\n" % (answer["host"], redirects))
    return 0


def _refuse(out, err, code, reason, host, exit_code, fields=()) -> int:
    out.write(json.dumps({"ok": False, "code": code, "fields": list(fields)}, sort_keys=True) + "\n")
    shown = host if isinstance(host, str) and _net.valid_host(host) else None
    err.write("web: %s%s\n" % (reason, " host=" + shown if shown else ""))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
