#!/usr/bin/env python3
"""stock:media on Openverse: pictures searched by words through the library's keyless API (package V9b-1c).

This file only says how to call Openverse and how to read its answer; the verbs, the caps, the licence rule, the cache and the refusals are the class's
(providers/stock/_stock.py). Every host, path, pattern, licence URL, licence table and credit line comes from providers/stock/sources/openverse.json, which is
committed with nulls and filled by the maintainer's approval; every verb refuses (exit 3, `source_not_ready`) until it is filled.

The tier is `per-item`: each item states its own licence and version, and the source file's `licences` table maps `"<licence> <version>"` (lower case, one space; a
licence with no version is its name alone, which no table maps) to one of our accepted ids. An item whose pair is not in the table is dropped, so CC BY-SA, NC, ND and
a CC BY with no version never pass. An item with a credit licence and no author is dropped by the class. An item whose preview or file host is not in the source
file's `media_hosts` is dropped. The search asks for licences that allow commercial use and modification, as a first filter only: the table is the rule.

  --check --source-file F --today D            the source file ready (no key: Openverse is read anonymously, `secret_in` is `none`)
  search --source-file F --today D --kind image --query Q [--count N] --out DIR
                                               one API call (or the cache), then each candidate's preview picture into DIR
  fetch --source-file F --today D --kind image --item ID --max-bytes B --out DIR
                                               one API call for the item (or the cache), then one download of the file its answer names

No key exists, so none is read, sent or stored. No verb takes a URL. Exit codes: 0 ok, 1 failed, 2 usage, 3 not configured. Standard library only.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _stock  # noqa: E402

SERVES = "stock:media"
SOURCE = "openverse"
VERBS = ("search", "fetch")
SECRET = ""      # the one secret this implementation reads is none: the class compares a source file's secret with this, so a file that names one is refused (`secret`)
LICENCE_TYPE = "commercial,modification"     # the library's own filter: licences that allow commercial use and changes


def _id(value):
    """The item id as text, or None (the item is then dropped) when the answer holds no id of the allowed shape."""
    return value if isinstance(value, str) and _stock.ITEM.fullmatch(value) else None


def _int(value):
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def licence_key(item) -> "str | None":
    """The key of an item's own licence in the source file's `licences` table: the lower-case licence name, a space and the version; the name alone when the item
    states no version (and no table maps that); None when the item states no licence."""
    own = item.get("license")
    if not isinstance(own, str) or not own.strip():
        return None
    version = item.get("license_version")
    version = version.strip() if isinstance(version, str) else ""
    return own.strip().lower() + (" " + version if version else "")


def auth(src, key):
    """Openverse is read anonymously: no header and no query parameter carry a credential."""
    return {}, {}


def search_request(src, kind, query, per_page):
    """(path, parameters) of one search: licences that allow commercial use and modification, `per_page` results."""
    return src["api"]["search_" + kind], {"q": query, "license_type": LICENCE_TYPE, "page_size": str(per_page)}


def item_request(src, kind, item):
    """(path, parameters) of one item; the path template holds `{item}` once."""
    return src["api"]["item_" + kind].replace("{item}", item), {}


def _image(src, item):
    return {"item": _id(item.get("id")), "width": _int(item.get("width")), "height": _int(item.get("height")), "seconds": None,
            "author": item.get("creator"), "title": item.get("title"), "page": item.get("foreign_landing_url"), "preview_url": item.get("thumbnail"),
            "file_url": item.get("url"), "licence": _stock.map_licence(src["licences"], licence_key(item))}


def read_search(src, kind, answer):
    """The raw candidates of a search answer (`results`); a shape the answer does not have gives none."""
    items = answer.get("results") if isinstance(answer, dict) else None
    return [_image(src, i) for i in items if isinstance(i, dict)] if isinstance(items, list) and kind == "image" else []


def read_item(src, kind, answer):
    """The raw item of an item answer (the item object itself), or None."""
    return _image(src, answer) if isinstance(answer, dict) and kind == "image" else None


if __name__ == "__main__":
    sys.exit(_stock.run(sys.modules[__name__]))
