"""Tests of the media consent key (package P6, decision VD17): `media.consent` of runtime.json, its widening items (runtime/policy_widening.py), the check every sender
calls (runtime/ops_media_consent.py `require`) and the two senders of today (the caption words and the preview on a messaging app). Real project, real store and operations
layer, the engine of media_kit; nothing is called and every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_media_consent.py
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

import standin_tree as st
from media_kit import open_items, ops, ops_core, to_gate, world  # noqa: F401  (world is a fixture)
from test_ops_media_phone import STEM, configure as phone_configure, refused as phone_refused, start as phone_start

project_config = st.load("project_config")
policy_widening = st.load("policy_widening")
operations = st.load("operations")
ops_media_consent = st.load("ops_media_consent")
ops_media_phone = st.load("ops_media_phone")
ops_media_preview = st.load("ops_media_preview")
ops_config = st.load("ops_config")
RUNTIME = st.RUNTIME
PHONE, APPROVER, READER = "4242424242", "5151515151", "6262626262"
PHONE_KEY, APPROVER_KEY, READER_KEY = (f"telegram:{i}" for i in (PHONE, APPROVER, READER))
POLICIES = {"phone": ["read", "answer", "media-phone"], "approver": ["read", "approve-effect-deliver"], "reader": ["read"]}
SENDERS_KEYS = {"messaging": {"senders": {"telegram": [{"id": PHONE, "policy": "phone"}, {"id": APPROVER, "policy": "approver"}, READER]}}}


def write_runtime(world, **keys):
    path = Path(world["path"]) / "docs" / "workbench" / "runtime.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw.update(keys)
    path.write_text(json.dumps(raw), encoding="utf-8")


def set_consent(world, words, accept=True):
    """The project's runtime.json with `media.consent` set to `words` (None: the key left out), accepted with the widening it shows."""
    path = Path(world["path"]) / "docs" / "workbench" / "runtime.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    media = dict(raw.get("media") or {})
    media.pop("consent", None)
    if words is not None:
        media["consent"] = words
    raw["media"] = media
    path.write_text(json.dumps(raw), encoding="utf-8")
    if accept:
        shown = ops.config(world["path"])
        ops.accept_config(world["path"], shown["sha256"], widen=shown["widening_sha256"])


def ctx_of(world):
    return ops_core.context(world["path"])


def require(world, purposes, **kw):
    return ops_media_consent.require(ctx_of(world), purposes, **kw)


# 1. the configuration (the refusals of a bad list are in test_media_config.py)


def test_the_consent_words_are_the_closed_list_and_none_names_audio_or_a_frame():
    assert project_config.MEDIA_CONSENT_WORDS == ("transcript", "intonation", "published-frames", "render-ocr")
    assert not any("audio" in w or "recording-frame" in w for w in project_config.MEDIA_CONSENT_WORDS)


# 2. the terms table


def test_the_terms_table_has_the_words_of_the_config_and_integer_versions():
    assert tuple(policy_widening.CONSENT_TERMS) == project_config.MEDIA_CONSENT_WORDS
    for word, (version, terms) in policy_widening.CONSENT_TERMS.items():
        assert type(version) is int and version >= 1 and terms == terms.lower() and ";" in terms


# 3. the items


def test_no_item_without_a_media_object_a_consent_key_or_with_an_empty_list():
    for cfg in ({}, {"media": {}}, {"media": {"consent": []}}, {"media": {"stock": []}}, None):
        assert policy_widening.consent_items(cfg, "k") == []


def test_one_item_per_listed_word_in_the_fixed_order_with_a_keyed_digest():
    cfg = {"media": {"consent": ["render-ocr", "transcript"]}}
    items = policy_widening.consent_items(cfg, "k")
    assert [i["group"] for i in items] == ["media-consent=transcript@1", "media-consent=render-ocr@1"]
    assert all(i["place"] == i["channel"] == "media-consent" for i in items)
    assert [i["means"] for i in items] == [policy_widening.CONSENT_TERMS["transcript"][1], policy_widening.CONSENT_TERMS["render-ocr"][1]]
    other = policy_widening.consent_items(cfg, "another")
    assert [i["digest"] for i in items] != [i["digest"] for i in other]
    assert {i["digest"] for i in policy_widening.account_items(cfg, "k")} >= {i["digest"] for i in items}


# 4. a new terms version lists the item again


def test_a_raised_terms_version_lists_that_item_alone_again(monkeypatch):
    cfg = {"media": {"consent": ["transcript", "intonation"]}}
    record = policy_widening.dump_accounts(cfg, "k")
    assert policy_widening.account_widening(record, cfg, "k") == []
    terms = dict(policy_widening.CONSENT_TERMS)
    terms["intonation"] = (2, terms["intonation"][1] + "; and one more thing")
    monkeypatch.setattr(policy_widening, "CONSENT_TERMS", terms)
    wide = policy_widening.account_widening(record, cfg, "k")
    assert [i["group"] for i in wide] == ["media-consent=intonation@2"] and wide[0]["means"].endswith("one more thing")
    assert policy_widening.consent_missing(record, cfg, ["transcript", "intonation"], "k") == ["intonation"]


# 5. a project without the key is unchanged


def test_a_project_without_consent_has_the_same_items_list_and_hash(monkeypatch):
    cfg = {"media": {"stock": []}, "accounts": {"google": {"address": "ana@example.org", "calendars": {"work": "primary"}}}}
    before = (policy_widening.account_items(cfg, "k"), policy_widening.account_widening(None, cfg, "k"))
    monkeypatch.setattr(policy_widening, "consent_items", lambda cfg, secret="": [])
    after = (policy_widening.account_items(cfg, "k"), policy_widening.account_widening(None, cfg, "k"))
    assert before == after
    assert policy_widening.widening_sha256(before[1]) == policy_widening.widening_sha256(after[1])


# 6. end to end


def test_a_file_that_adds_a_word_is_refused_until_the_widening_is_accepted(world):
    write_runtime(world, media={"consent": ["transcript"]})
    shown = ops.config(world["path"])
    lines = [(i["place"], i["group"], i["means"]) for i in shown["widening"] if i["place"] == "media-consent"]
    assert lines == [("media-consent", "media-consent=transcript@1", policy_widening.CONSENT_TERMS["transcript"][1])]
    with pytest.raises(ops_core.OpsError) as refused:
        ops.accept_config(world["path"], shown["sha256"])
    assert "media-consent:media-consent=transcript@1" in str(refused.value) and "--widen" in str(refused.value)
    ops.accept_config(world["path"], shown["sha256"], widen=shown["widening_sha256"])
    assert require(world, ["transcript"]) is None


# 7. require, the model words


def test_a_word_not_listed_is_refused_naming_the_word_and_the_command(world):
    set_consent(world, None)
    with pytest.raises(ops_core.OpsError) as refused:
        require(world, ["transcript"])
    text = str(refused.value)
    assert refused.value.code == 1 and text.startswith("media_consent_missing: ") and "transcript" in text and "accept-config --widen" in text


def test_a_file_that_lists_a_word_is_not_in_force_until_it_is_accepted_with_the_widening(world):
    set_consent(world, ["intonation"], accept=False)
    with pytest.raises(Exception) as refused:      # the configuration itself is not accepted: no operation runs on it
        require(world, ["intonation"])
    assert "accept-config" in str(refused.value) and "--widen" in str(refused.value)
    shown = ops.config(world["path"])
    ops.accept_config(world["path"], shown["sha256"], widen=shown["widening_sha256"])
    assert require(world, ["intonation"]) is None


def test_the_record_must_hold_the_item_even_when_the_file_lists_the_word(world):
    set_consent(world, ["transcript"])
    ctx = ctx_of(world)
    ctx["store"].cursor_set(ctx["conn"], policy_widening.ACCOUNTS, json.dumps({"v": 1, "items": ""}))
    with pytest.raises(ops_core.OpsError):
        require(world, ["transcript"])


def test_a_raised_terms_version_refuses_the_word_until_it_is_accepted_again(world, monkeypatch):
    set_consent(world, ["transcript", "render-ocr"])
    assert require(world, ["transcript", "render-ocr"]) is None
    terms = dict(policy_widening.CONSENT_TERMS)
    terms["transcript"] = (2, terms["transcript"][1] + "; a second sentence")
    monkeypatch.setattr(policy_widening, "CONSENT_TERMS", terms)
    with pytest.raises(ops_core.OpsError) as refused:
        require(world, ["transcript", "render-ocr"])
    assert "transcript" in str(refused.value) and "render-ocr" not in str(refused.value)      # only the word that is missing is named
    shown = ops.config(world["path"])
    assert [i["group"] for i in shown["widening"]] == ["media-consent=transcript@2"]
    ops.accept_config(world["path"], shown["sha256"], widen=shown["widening_sha256"])
    assert require(world, ["transcript", "render-ocr"]) is None


# 8. the closed list


@pytest.mark.parametrize("bad", [[], (), "transcript", ["audio"], ["recording-frames"], ["transcript", "audio"], ["Transcript"], [3], None])
def test_a_purpose_outside_the_closed_list_is_a_programming_error(world, bad):
    set_consent(world, ["transcript"])
    with pytest.raises(ValueError):
        require(world, bad)


# 9 and 10. the messaging senders


def messaging(world):
    write_runtime(world, policies=POLICIES, channels={"messaging": "reader"}, **SENDERS_KEYS)
    shown = ops.config(world["path"])
    ops.accept_config(world["path"], shown["sha256"], widen=shown["widening_sha256"])


def test_the_caption_words_go_only_to_a_sender_whose_profile_holds_media_phone(world):
    messaging(world)
    assert require(world, ["messaging-captions"], channel="messaging", sender=PHONE_KEY) is None
    for kw in ({"channel": "messaging", "sender": APPROVER_KEY}, {"channel": "messaging", "sender": READER_KEY}, {"channel": "page", "sender": PHONE_KEY},
               {"channel": "terminal", "sender": PHONE_KEY}, {"channel": None, "sender": PHONE_KEY}, {"channel": "messaging", "sender": None}, {}):
        with pytest.raises(ops_core.OpsError) as refused:
            require(world, ["messaging-captions"], **kw)
        assert str(refused.value).startswith("media_consent_missing: "), kw


def test_the_preview_goes_only_to_a_sender_the_delivery_grant_covers(world):
    messaging(world)
    assert require(world, ["messaging-preview"], channel="messaging", sender=APPROVER_KEY) is None
    for kw in ({"channel": "messaging", "sender": PHONE_KEY}, {"channel": "messaging", "sender": READER_KEY}, {"channel": "page", "sender": APPROVER_KEY},
               {"channel": "messaging", "sender": None}, {}):
        with pytest.raises(ops_core.OpsError) as refused:
            require(world, ["messaging-preview"], **kw)
        assert str(refused.value).startswith("media_consent_missing: "), kw


def test_a_messaging_purpose_does_not_need_the_key_and_a_model_word_does_not_need_the_sender(world):
    set_consent(world, None)
    messaging(world)
    assert require(world, ["messaging-captions"], channel="messaging", sender=PHONE_KEY) is None      # the key is for a model, not for the messaging app
    set_consent(world, ["transcript"])
    assert require(world, ["transcript"]) is None      # no channel, no sender: the key is the project's


# 11. on the path


def boom(*args, **kwargs):
    raise ops_core.OpsError("media_consent_missing: stand-in", 1)


def test_the_caption_words_are_not_returned_when_the_check_refuses(world, monkeypatch):
    phone_configure(world)
    started = phone_start(world)
    assert "words" in started
    [item] = open_items(world, started["task"])
    with monkeypatch.context() as patched:
        patched.setattr(ops_media_consent, "require", boom)
        with pytest.raises(ops_core.OpsError):
            ops_media_phone.video_phone_start(world["path"], world["rid"], STEM, channel="messaging", sender=SENDER_PHONE)
        with pytest.raises(ops_core.OpsError):
            ops_media_phone.video_phone_reply(world["path"], item["id"], "Aster -> Astor", channel="messaging", sender=SENDER_PHONE)
    with monkeypatch.context() as patched:
        patched.setattr(ops_media_consent, "require", boom)
        patched.setattr(ops_media_phone.ops_media, "video_run", lambda project, task, channel=None: {"task": task, "stopped": "review"})      # a run that stops at the review carries its caption text
        with pytest.raises(ops_core.OpsError):
            ops_media_phone.video_phone_run(world["path"], started["task"], channel="messaging", sender=SENDER_PHONE)


SENDER_PHONE = "telegram:4242424242"      # test_ops_media_phone's sender with the group


def test_the_preview_is_not_returned_when_the_check_refuses(world, monkeypatch):
    messaging(world)
    task, gate = to_gate(world)
    assert ops_media_preview.video_preview(world["path"], gate["id"], channel="messaging", sender=APPROVER_KEY)["data"]
    monkeypatch.setattr(ops_media_consent, "require", boom)
    with pytest.raises(ops_core.OpsError):
        ops_media_preview.video_preview(world["path"], gate["id"], channel="messaging", sender=APPROVER_KEY)


# 12. the inventory of the senders


def _is_require(node, text):
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr == "require" and isinstance(func.value, ast.Name) and func.value.id == "ops_media_consent"
    return isinstance(func, ast.Name) and func.id == "require" and "from ops_media_consent import" in text


def _calls_of_require():
    found = set()
    for path in sorted(RUNTIME.glob("*.py")):
        if path.stem == "ops_media_consent":
            continue
        text = path.read_text(encoding="utf-8")
        for fn in ast.walk(ast.parse(text)):
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for node in ast.walk(fn):
                    if _is_require(node, text):
                        words = node.args[1] if len(node.args) > 1 else None
                        first = words.elts[0].value if isinstance(words, (ast.List, ast.Tuple)) and words.elts and isinstance(words.elts[0], ast.Constant) else None
                        found.add((path.stem, fn.name, first))
    return found


def test_every_call_of_require_in_the_runtime_is_a_row_of_senders_and_every_row_is_a_call():
    assert _calls_of_require() == set(ops_media_consent.SENDERS)
    assert set(w for _, _, w in ops_media_consent.SENDERS) <= set(ops_media_consent.MESSAGING_WORDS + ops_media_consent.MODEL_WORDS)


# 13. the ground of decision D10 and of STOP B


def test_the_shown_text_of_media_phone_says_the_captions_pass_through_the_apps_servers():
    text = policy_widening.means("messaging", "media-phone")
    assert "sends the captions" in text and "the app's servers" in text
    assert "messaging:media-phone" not in operations.GRANT_TEXT
    assert not any("media-phone" in (v if isinstance(v, (tuple, list, set, frozenset)) else (v,)) for v in operations.IMPLIED.values())
    assert "the preview pass through the messaging provider's servers" in operations.GRANT_TEXT["messaging:approve-effect-deliver"]


# 14. the limit


def test_limit_81_a_recording_derived_send_passes_the_check_first(world):
    set_consent(world, None)
    with pytest.raises(ops_core.OpsError):
        require(world, ["transcript"])
    set_consent(world, ["transcript"])
    assert require(world, ["transcript"]) is None
    with pytest.raises(ValueError):
        require(world, ["audio"])
    messaging(world)
    assert require(world, ["messaging-captions"], channel="messaging", sender=PHONE_KEY) is None
    with pytest.raises(ops_core.OpsError):
        require(world, ["messaging-captions"], channel="messaging", sender=READER_KEY)
    assert require(world, ["messaging-preview"], channel="messaging", sender=APPROVER_KEY) is None
    with pytest.raises(ops_core.OpsError):
        require(world, ["messaging-preview"], channel="messaging", sender=PHONE_KEY)


def test_the_module_starts_on_its_own():
    import subprocess
    import sys
    done = subprocess.run([sys.executable, "-I", str(RUNTIME / "ops_media_consent.py"), "--help"], capture_output=True, text=True, timeout=60, env={})
    assert done.returncode == 0 and "media consent" in done.stdout
    assert subprocess.run([sys.executable, "-I", str(RUNTIME / "ops_media_consent.py"), "--nope"], capture_output=True, text=True, timeout=60, env={}).returncode == 2
