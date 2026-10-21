"""The decision that turns the interpreter on (slice S1, limit L63): the committed file, the runtime's reading of it, the status's reading of it, and the group that gives it to a sender.

The literals below are the hashes of the route, the prompt, the served catalog and the protocol the maintainer decided on (they are also the headers of the recorded development
answers); the committed entry must name exactly them, be in force for this checkout in each of the six languages, and be refused when a key is added, a date is written another way, or a
hash differs. The status script (evals/interpreter_status.py) reads the same file as data and must agree with the runtime on the committed file and on each broken one. The group
`interpret` is a kind-only group of the messaging channel: widening it prints the route's retention. Offline.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interpreter_enable.py
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

import standin_tree as st
from test_ask import accept, write_config
from test_ops_natural import KEY, OWNER, PROFILES, SENDERS, world  # noqa: F401  (the real-operations world fixture)

interpreter_enable = st.load("interpreter_enable")
interpreter_route = st.load("interpreter_route")
interpreter_evidence = st.load("interpreter_evidence")
operations = st.load("operations")
policy_widening = st.load("policy_widening")
ops = st.load("ops")

REPO = Path(__file__).resolve().parents[2]
FILE = REPO / "runtime" / "interpreter_enable.json"
ROUTE = "or-deepseek-v4.1-flash"
HASHES = {"route_sha256": "1365ea7c385a28f38103f9b2d3b959faee6012691ed6ef50478a560d1014c9fd", "prompt_sha256": "5bee55ceb50ea932e6cefe71837268fa9c2d773c1937ea4dcaa2008d7343cb06",
          "catalog_sha256": "a43735d2073b926d34e3deefc0c8a8791b729fbe7601d059aefbd73c36d2885d", "protocol_sha256": "2a6f7f1919ba6c1d9a202dd63cf5995578b5fb254f7175cbb27c9798ed01e504"}
LANGUAGES = ["pt-BR", "en", "es", "fr", "de", "it"]
STATUS_LINE = "enabled by maintainer decision 2026-10-21, below the gate"


def status_module():
    name = "workbench_interpreter_status_for_enable_test"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, REPO / "evals" / "interpreter_status.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


def committed() -> dict:
    return json.loads(FILE.read_text(encoding="utf-8"))


def variant(tmp_path, name, **changes) -> Path:
    """A copy of the committed file with the newest entry changed (None removes a key)."""
    doc = committed()
    for key, value in changes.items():
        if value is None:
            doc["entries"][-1].pop(key, None)
        else:
            doc["entries"][-1][key] = value
    path = tmp_path / name
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def test_the_committed_entry_names_the_decided_hashes_the_languages_and_the_date():
    doc = committed()
    assert set(doc) == {"v", "entries"} and doc["v"] == 1 and len(doc["entries"]) == 1
    entry = doc["entries"][0]
    assert {key: entry[key] for key in HASHES} == HASHES
    assert entry["basis"] == "maintainer-decision" and entry["date"] == "2026-10-21" and entry["route"] == ROUTE
    assert entry["languages"] == LANGUAGES and entry["status_line"] == STATUS_LINE


def test_the_checkout_has_the_hashes_the_entry_was_decided_on_and_it_is_in_force_for_each_listed_language():
    assert interpreter_enable.checkout_hashes(ROUTE) == HASHES
    assert interpreter_evidence.hashes(interpreter_route.find(ROUTE))["protocol_sha256"] == HASHES["protocol_sha256"]
    for language in LANGUAGES:
        found = interpreter_enable.active(language)
        assert found is not None and found["route"]["id"] == ROUTE and found["route"]["kind"] == "http" and found["entry"]["date"] == "2026-10-21", language
    for language in ("ja", "pt-br", "en-GB", "", None):
        assert interpreter_enable.active(language) is None, language


@pytest.mark.parametrize("name, change", [
    ("prompt", {"prompt_sha256": "0" * 64}), ("catalog", {"catalog_sha256": "0" * 64}), ("route", {"route_sha256": "0" * 64}), ("protocol", {"protocol_sha256": "0" * 64}),
    ("language", {"languages": ["ja"]}), ("unknown-route", {"route": "no-such-route"}), ("account-route", {"route": "acct-claude-sonnet-5.5"}),
    ("extra-key", {"extra": "key"}), ("missing-key", {"reason": None}), ("date-shape", {"date": "21/10/2026"}), ("date-not-a-day", {"date": "2026-02-30"}),
    ("basis", {"basis": "evidence"}), ("hash-shape", {"prompt_sha256": "5BEE55CE" + HASHES["prompt_sha256"][8:]}), ("languages-twice", {"languages": ["en", "en"]}),
])
def test_a_changed_entry_is_off_for_the_runtime_and_for_the_status_alike(tmp_path, name, change):
    path = variant(tmp_path, name + ".json", **change)
    assert interpreter_enable.active("en", path=str(path)) is None
    root = tmp_path / ("root-" + name)
    (root / "runtime").mkdir(parents=True)
    shutil.copy(path, root / "runtime" / "interpreter_enable.json")
    status = status_module()
    read = status.enable_status(str(root), status.load_inputs())
    assert read["in_force"] is False, name


def test_vacuity_the_unchanged_copy_is_in_force_for_both_and_a_loader_that_accepts_all_would_not_raise(tmp_path):
    path = variant(tmp_path, "same.json")
    assert interpreter_enable.active("en", path=str(path)) is not None and interpreter_enable.load(str(path))["entries"][0]["date"] == "2026-10-21"
    status = status_module()
    root = tmp_path / "root-same"
    (root / "runtime").mkdir(parents=True)
    shutil.copy(path, root / "runtime" / "interpreter_enable.json")
    assert status.enable_status(str(root), status.load_inputs())["in_force"] is True
    for bad in (variant(tmp_path, "extra.json", extra=1), variant(tmp_path, "date.json", date="2026-1-1")):
        with pytest.raises(interpreter_enable.EnableError):
            interpreter_enable.load(str(bad))


def test_entries_are_read_newest_last_and_an_older_entry_cannot_keep_a_changed_checkout_on(tmp_path):
    doc = committed()
    older = dict(doc["entries"][0])
    newer = dict(older, date="2026-11-02", prompt_sha256="0" * 64)
    path = tmp_path / "two.json"
    path.write_text(json.dumps({"v": 1, "entries": [older, newer]}), encoding="utf-8")
    assert interpreter_enable.active("en", path=str(path)) is None, "the newest entry decides, and its prompt hash is not this checkout's"
    path.write_text(json.dumps({"v": 1, "entries": [newer, older]}), encoding="utf-8")
    with pytest.raises(interpreter_enable.EnableError):
        interpreter_enable.load(str(path))      # dates out of order


def test_the_status_reads_the_same_committed_file_and_prints_the_decision_beside_the_route():
    status = status_module()
    read = status.enable_status(str(REPO), status.load_inputs())
    assert read["present"] and read["in_force"] and read["date"] == "2026-10-21" and read["route"] == ROUTE and read["languages"] == LANGUAGES and read["status_line"] == STATUS_LINE
    assert interpreter_enable.active("en") is not None
    assert f"  {ROUTE}: {STATUS_LINE}" in status.table(status.status(str(REPO)))


def test_the_status_says_the_interpreter_is_off_when_the_file_is_gone(tmp_path):
    status = status_module()
    inputs = status.load_inputs()
    lines = status.table({"rows": [{"model": "m", "route": "r", "lang": "en", "band": "needs a run", "cause": "c"}], "reference": "r", "enable": status.enable_status(str(tmp_path), inputs)})
    assert lines[-1] == "  the interpreter is off: runtime/interpreter_enable.json is missing or not valid"


# --- the group that gives it to a sender ---------------------------------------------------------------------------------------------------------


def test_the_group_interpret_is_kind_only_messaging_only_in_no_default_and_never_grants_say():
    assert operations.GROUPS["interpret"] == {"operations": ("say",), "kind": "interpret"}
    assert "interpret" in operations.KIND_ONLY and "interpret" in operations.MESSAGING_ONLY_GROUPS and "interpret" not in operations.DEFAULT_POLICY["messaging"]
    policy = {"messaging": ["read", "interpret"]}
    assert operations.holds("interpret", "messaging", policy, "telegram:1") is True and operations.permitted("say", "messaging", policy, None, "telegram:1") is False
    assert operations.holds("interpret", "page", {"page": ["read"]}, None) is False and operations.group_refusal("page", "interpret")
    assert operations.GROUP_TEXT["interpret"].startswith("sends the plain lines no list takes to the interpreter's model service")


def test_widening_the_group_prints_the_retention_of_the_daily_route_beside_it(world):
    accept(world["path"], policies=PROFILES, messaging={"senders": SENDERS})      # the file accepted before
    write_config(world["path"], policies=dict(PROFILES, owner=PROFILES["owner"] + ["interpret"]))      # the edit that gives one sender the group
    shown = ops.config(world["path"])
    mine = [item for item in shown["widening"] if item["group"] == "interpret"]
    assert len(mine) == 1 and mine[0]["place"] == KEY["owner"]
    assert mine[0]["means"].endswith("Retention of the daily route: " + interpreter_route.find(ROUTE)["retention"])
    assert "deepinfra's own terms and OpenRouter's terms decide how long a prompt is kept" in mine[0]["means"]
    assert policy_widening.widening_sha256([{"place": KEY["owner"], "group": "interpret"}]) is not None
