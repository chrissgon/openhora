"""The title of a script, as the edit list's schema bounds it, is as long as the vocabulary allows."""
from __future__ import annotations

import json

import renderer_kit as K


def test_the_title_of_the_schema_is_bounded_like_the_vocabulary():
    schema = json.loads((K.REPO / "providers/renderer/edl.schema.json").read_text(encoding="utf-8"))
    vocab = json.loads(K.VOCABULARY.read_text(encoding="utf-8"))
    assert schema["$defs"]["beats"]["properties"]["script"]["properties"]["title"]["maxLength"] == vocab["script"]["limits"]["title_max"]
