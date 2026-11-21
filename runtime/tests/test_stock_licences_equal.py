"""The licence policy is in code in two places and the rules the runtime shares with the class are copied, each with a test that compares the copy (package V9b-3a): the two licence
tuples of providers/stock/_stock.py and runtime/media_stock.py (and the copy the step kind keeps, which it cannot import: limit L30), the search-word rule, the slot-id and the
slot's asset keys. Nothing is called.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_stock_licences_equal.py
"""
from __future__ import annotations

import ast
import re
import sys

import standin_tree as st

media_stock = st.load("media_stock")
step_media = st.load("step_media")
captions = st.load("captions")
deliver_document = st.load("deliver_document")
REPO = st.REPO


def class_module():
    folder = str(REPO / "providers" / "stock")
    if folder not in sys.path:
        sys.path.insert(0, folder)
    import _stock
    return _stock


def test_the_licence_tuples_of_the_class_and_of_the_runtime_are_equal():
    stock = class_module()
    assert media_stock.LICENCES_ACCEPTED == stock.LICENCES_ACCEPTED and media_stock.LICENCES_CREDIT == stock.LICENCES_CREDIT
    assert media_stock.UNVERIFIED == stock.UNVERIFIED and media_stock.TIERS == stock.TIERS
    assert stock.UNVERIFIED not in media_stock.LICENCES_ACCEPTED and set(media_stock.LICENCES_CREDIT) <= set(media_stock.LICENCES_ACCEPTED)


def test_the_step_kind_keeps_the_same_tuple_the_same_asset_keys_and_hashes_the_same_document():
    stock = class_module()
    assert step_media.STOCK_LICENCES == stock.LICENCES_ACCEPTED == media_stock.LICENCES_ACCEPTED
    assert step_media.STOCK_UNVERIFIED == media_stock.UNVERIFIED and step_media.STOCK_KEYS == media_stock.ASSET_KEYS
    found = {"task": 3, "credits": ["x"], "assets": [{"slot": "b", "sha256": "1" * 64, "title": "T", "extra": 1}, {"slot": "a", "sha256": "2" * 64, "licence": "cc0-1.0"}]}
    assert step_media.stock_hash(found) == media_stock.set_hash(media_stock.set_document(found))
    assert step_media.stock_hash(dict(found, credits=["y"])) != step_media.stock_hash(found)
    assert [a["slot"] for a in media_stock.set_document(found)["assets"]] == ["a", "b"] and "extra" not in media_stock.set_document(found)["assets"][0]


def test_the_search_rule_the_slot_id_and_the_word_bounds_are_the_class_and_the_renderers():
    stock = class_module()
    assert captions.SEARCH.pattern == stock.SEARCH.pattern and captions.SEARCH_WORDS == stock.MAX_WORDS == 6 and media_stock.SEARCH is captions.SEARCH
    renderer = (REPO / "providers" / "renderer" / "_vocab.py").read_text(encoding="utf-8")
    assert re.search(r"^SLOT_ID = re\.compile\(r\"%s\"\)" % re.escape(captions.SLOT_ID.pattern), renderer, re.M)
    assert media_stock.MAX_SLOTS == captions.STOCK_SLOTS_MAX == 6 and media_stock.PER_SLOT == 6 and media_stock.PER_SOURCE == 2 and media_stock.MAX_PREVIEWS == 36
    caps = stock.CAPS
    assert media_stock.KIND_BYTES == {"image": caps["image_bytes"], "clip": caps["clip_bytes"]}


def test_the_not_approved_sentence_of_the_step_is_the_english_phrase():
    phrases = st.load("phrases")
    assert step_media.STOCK_NOT_APPROVED == phrases.en("VID_STOCK_NOT_APPROVED")
    for key in ("CARD_VIDEO_ASSET", "CARD_VIDEO_CREDITS", "CARD_VIDEO_CREDIT", "CARD_VIDEO_WEB", "CARD_VIDEO_WEB_PAGE"):
        assert phrases.en(key)
    assert phrases.en("CARD_VIDEO_CREDITS") == phrases.en("VID_STOCK_CREDIT")      # the body's English line and the phrase say the same words


def test_the_step_kind_still_imports_nothing_new_and_the_credit_licence_names_are_built_by_code():
    imported = set()
    for node in ast.walk(ast.parse((REPO / "runtime" / "step_media.py").read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert not imported & {"media_stock", "ops_media_stock", "media", "urllib", "subprocess", "socket"}
    for licence in media_stock.LICENCES_CREDIT:
        name, version, url = media_stock.licence_name(licence)
        assert name == "CC BY" and url == "https://creativecommons.org/licenses/by/%s/" % version and licence == "cc-by-" + version
    assert media_stock.licence_name("cc0-1.0")[0] == "CC0" and media_stock.licence_name(media_stock.LICENCES_ACCEPTED[0]) is None and media_stock.licence_name("cc-by-sa-4.0") is None
