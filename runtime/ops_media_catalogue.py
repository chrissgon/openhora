#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The catalogue of animations of a new video (package V1b3, VD15): what the caption review can add, read from the renderer's generated catalogue (our
fields only), with whether this project's engine can add each block now. Read-only; it may cross the LAN socket (VD18; it is not in
operations.LAN_REFUSED_OPS).

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import media_animation  # noqa: E402
import ops_core as core  # noqa: E402
import ops_media  # noqa: E402
import ops_step_seams  # noqa: E402


def video_catalogue(project, channel=None) -> dict:
    """The listing of runtime/media_animation.py for this project's engine. core.OpsError when the channel may not call it or the catalogue
    cannot be read."""
    ctx = core.context(project)
    ops_media._channel(ctx, "video-catalogue", channel)
    try:
        return media_animation.listing(ops_step_seams.MediaStore(ctx).root())
    except media_animation.CatalogueError as e:
        raise core.OpsError(f"the catalogue of animations cannot be read ({e.code})", 1) from None


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)
