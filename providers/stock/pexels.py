#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["keyring==25.7.0"]
# ///
"""stock:media on Pexels: photos and clips searched by words through the library's API (package V9b-1).

This file only says how to call Pexels and how to read its answer; the verbs, the caps, the licence rule, the cache and the refusals are the
class's (providers/stock/_stock.py). Every host, path, pattern, licence URL and rendition name comes from providers/stock/sources/pexels.json,
which is committed with nulls and filled by the maintainer's approval; every verb refuses (exit 3, `source_not_ready`) until it is filled.

  --check --source-file F --today D            the source file ready and the key found (printed as where it was found, never the value)
  search --source-file F --today D --kind image|clip --query Q [--count N] --out DIR
                                               one API call (or the cache), then each candidate's preview picture into DIR
  fetch --source-file F --today D --kind image|clip --item ID --max-bytes B --out DIR
                                               one API call for the item (or the cache), then one download of the rendition its answer names

The key is the secret named in the source file (read through providers/secrets/resolver.py) and goes in the `Authorization` header of the API call
and nowhere else: not in a download, an output, an error, the cache or a file. No verb takes a URL. Exit codes: 0 ok, 1 failed, 2 usage,
3 not configured. Standard library only (the keyring library is the resolver's, for the OS secret store).
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _stock  # noqa: E402

SERVES = "stock:media"
SOURCE = "pexels"
SECRET = "STOCK_PEXELS_API_KEY"      # the one secret this implementation reads; a source file that names another is refused (V9b STOP 2 registers it)
VERBS = ("search", "fetch")
IMAGE_MIN = _stock.FLOOR["image"]      # 1080 x 1350, portrait


def _int(value):
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _id(value):
    """The item id as text, or None (the item is then dropped) when the answer holds no integer id."""
    return str(value) if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def auth(src, key):
    """(headers, extra query) that carry the key: the `Authorization` header, never the query."""
    return {"Authorization": key}, {}


def search_request(src, kind, query, per_page):
    """(path, parameters) of one search: portrait orientation, `per_page` results."""
    return src["api"]["search_" + kind], {"query": query, "orientation": "portrait", "per_page": str(per_page)}


def item_request(src, kind, item):
    """(path, parameters) of one item; the path template holds `{item}` once."""
    return src["api"]["item_" + kind].replace("{item}", item), {}


def _photo(src, photo):
    sizes = photo.get("src") if isinstance(photo.get("src"), dict) else {}
    preview, full = sizes.get(src["rendition"]["preview"]), sizes.get(src["rendition"]["image"])
    return {"item": _id(photo.get("id")), "width": _int(photo.get("width")), "height": _int(photo.get("height")), "seconds": None,
            "author": photo.get("photographer"), "title": "", "page": photo.get("url"), "preview_url": preview, "file_url": full}


def _clip(src, video):
    """The smallest rendition of the wanted type whose short side is at least 1080 px (decision: the file the render needs, no larger)."""
    files = [f for f in (video.get("video_files") or []) if isinstance(f, dict) and f.get("file_type") == src["rendition"]["clip"]
             and _int(f.get("width")) and _int(f.get("height")) and min(f["width"], f["height"]) >= _stock.FLOOR["clip_short_side"]
             and isinstance(f.get("link"), str)]
    best = min(files, key=lambda f: (f["width"] * f["height"], f["link"])) if files else None
    user = video.get("user") if isinstance(video.get("user"), dict) else {}
    return {"item": _id(video.get("id")), "width": best["width"] if best else _int(video.get("width")),
            "height": best["height"] if best else _int(video.get("height")), "seconds": video.get("duration"), "author": user.get("name"),
            "title": "", "page": video.get("url"), "preview_url": video.get("image"), "file_url": best["link"] if best else None}


def read_search(src, kind, answer):
    """The raw candidates of a search answer (`photos` or `videos`); a shape the answer does not have gives none."""
    items = answer.get("photos" if kind == "image" else "videos") if isinstance(answer, dict) else None
    read = _photo if kind == "image" else _clip
    return [read(src, i) for i in items if isinstance(i, dict)] if isinstance(items, list) else []


def read_item(src, kind, answer):
    """The raw item of an item answer (the photo or the video object itself), or None."""
    if not isinstance(answer, dict):
        return None
    return (_photo if kind == "image" else _clip)(src, answer)


if __name__ == "__main__":
    sys.exit(_stock.run(sys.modules[__name__]))
