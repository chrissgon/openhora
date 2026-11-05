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
import os
import shutil
import sys
from pathlib import Path

import pytest

import standin_tree as st
from test_ask import accept, write_config
from test_ops_natural import KEY, OWNER, PROFILES, SENDERS, world  # noqa: F401  (the real-operations world fixture)
# Every pinned hash of the test suite is in scripts/tests/pinned_hashes.json, with what it hashes and why it is pinned.
PINNED_HASHES = json.loads((Path(__file__).resolve().parents[2] / "scripts" / "tests" / "pinned_hashes.json").read_text(encoding="utf-8"))["pins"]

interpreter_enable = st.load("interpreter_enable")
event_card = st.load("event_card")
interpreter_route = st.load("interpreter_route")
interpreter_evidence = st.load("interpreter_evidence")
operations = st.load("operations")
policy_widening = st.load("policy_widening")
ops = st.load("ops")

REPO = Path(__file__).resolve().parents[2]
FILE = REPO / "runtime" / "interpreter_enable.json"
ROUTE = "or-deepseek-v4.1-flash"
HASHES = {"route_sha256": PINNED_HASHES["route_or_deepseek_v4_1_flash"], "prompt_sha256": PINNED_HASHES["interpreter_prompt"],
          "catalog_sha256": PINNED_HASHES["interpreter_catalog_v4"], "protocol_sha256": PINNED_HASHES["interpreter_protocol"]}      # P5: the catalog of version 4 and the prompt with the second exception of rule 3
OLD_HASHES = dict(HASHES, prompt_sha256=PINNED_HASHES["interpreter_prompt_9e63"], catalog_sha256=PINNED_HASHES["interpreter_catalog_mail_ask"])      # what the entries from MAIL-SUMMARY-FLIP (the catalog) and ANY-QUESTION Q3 (the prompt) to RESERVE-V3 were decided on
RECORDED = dict(HASHES, prompt_sha256=PINNED_HASHES["interpreter_prompt_5bee"], catalog_sha256=PINNED_HASHES["interpreter_catalog_blite"])      # the prompt and the catalog every entry before BL5B was decided on (rule 9 of BL5B changed the prompt)
FIRST = dict(RECORDED, catalog_sha256=PINNED_HASHES["interpreter_catalog_before_s8"])      # the entry decided before slice S8 added `file-read` to the catalog
LANGUAGES = ["pt-BR", "en", "es", "fr", "de", "it"]
S8_STATUS_LINE = "enabled by maintainer decision 2026-10-21 (S8: file-read added to the catalog), below the gate"
COMPOSE_STATUS_LINE = "enabled by maintainer decision 2026-10-21, below the gate; the e-mail text is worded by the model (compose prompt pinned)"      # the entry of slice S7
S12_STATUS_LINE = "enabled by maintainer decision 2026-10-21, below the gate; the e-mail text is worded by the model (compose prompt re-pinned 2026-10-22)"      # the entry of slice S12
S13_STATUS_LINE = "enabled by maintainer decision 2026-10-21, below the gate; the e-mail text is worded and revised by the model (compose re-pinned and revise prompts pinned)"      # the entry of slice S13
PINS = ("route_sha256", "prompt_sha256", "protocol_sha256", "compose_prompt_sha256", "revise_prompt_sha256")
R2F1_STATUS_LINE = S13_STATUS_LINE + "; research added to the catalog 2026-10-22 (R2-F1)"      # the entry of slice R2-F1
S13B_STATUS_LINE = "enabled by maintainer decision 2026-10-21, below the gate; the e-mail text is worded and revised by the model (compose re-pinned, revise prompt re-pinned 2026-10-22)"      # the entry of slice S13b
R2A_STATUS_LINE = S13B_STATUS_LINE + "; file-trash added to the catalog 2026-10-22 (R2-A)"      # the entry of slice R2-A
BL1_STATUS_LINE = R2A_STATUS_LINE + "; target and day slots added to the catalog 2026-10-24 (B″-lite), served before its measurement"      # the entry of slice BL1
BL5B_STATUS_LINE = BL1_STATUS_LINE + "; the prompt revised 2026-10-25 (BL5B: a correction after \"Posso?\" states a new plan), served before its measurement"      # the entry of package BL5B
BL73_STATUS_LINE = BL5B_STATUS_LINE + "; the prompt revised 2026-10-26 (BL7-3: described replies, subject kept in target, inherit and correction rules), measured on this PR's head before merge"      # the entry of package BL7-3
CB9_STATUS_LINE = ("enabled by maintainer decision 2026-10-21, below the gate; the e-mail text is worded and revised by the model; the catalog grew (file-read, research, file-trash, the target and day slots) and the prompt was revised twice (BL5B, BL7-3); "
               "the catalog moved to version 2 on 2026-10-28 (CB-9: the catalog batch, file-ask and the model-facing descriptions, re-worded once after the first measurement), measured on this PR's head before merge")      # the entry of package CB-9; the earlier lines were joined one after the other until the cap of 600 characters, so this one says it over
assert len(CB9_STATUS_LINE) <= 600
LUNA_STATUS_LINE = CB9_STATUS_LINE + "; the outage path or-gpt-6-luna enabled on 2026-10-28 by maintainer decision"      # the entry of package LUNA-ENABLE: the entry of CB-9 and the outage path
assert len(LUNA_STATUS_LINE) <= 600
MAIL_ASK_STATUS_LINE = (CB9_STATUS_LINE.split("; the catalog moved to version 2")[0] + "; the catalog moved to version 2 on 2026-10-28 (CB-9) and to version 3 on 2026-10-31 (MAIL-SUMMARY-FLIP: mail-ask), measured on this PR's head before merge; "
               "the outage path or-gpt-6-luna enabled on 2026-10-28 by maintainer decision")      # the entry of package MAIL-SUMMARY-FLIP: the catalog of version 3, the outage path as the entry before it
assert len(MAIL_ASK_STATUS_LINE) <= 600
EVENT_CARD_STATUS_LINE = MAIL_ASK_STATUS_LINE + "; the event card shown to the model (2026-11-01)"      # the entry of package CARD-MODEL-SEES: the entry of MAIL-SUMMARY-FLIP and the event card text
assert len(EVENT_CARD_STATUS_LINE) <= 600
RECIPIENT_STATUS_LINE = EVENT_CARD_STATUS_LINE + "; revise prompt re-pinned 2026-11-01 (a question about the recipient)"      # the entry of package mail-card-recipient, third text: the entry of CARD-MODEL-SEES and the re-pinned revise prompt
assert len(RECIPIENT_STATUS_LINE) <= 600
ANY_QUESTION_STATUS_LINE = ("enabled by maintainer decision 2026-10-21, below the gate; the e-mail text is worded and revised by the model; the catalog grew and moved to version 2 (CB-9, 2026-10-28) and 3 (MAIL-SUMMARY-FLIP, 2026-10-31); "
               "the prompt revised three times (BL5B, BL7-3, ANY-QUESTION 2026-11-03: the kind question, below rule 4); the outage path or-gpt-6-luna enabled on 2026-10-28 by maintainer decision; "
               "the event card shown to the model (2026-11-01); revise prompt re-pinned 2026-11-01 (a question about the recipient)")      # the entry of ANY-QUESTION Q3, the probe of the draft (no longer the newest)
assert len(ANY_QUESTION_STATUS_LINE) <= 600
STATUS_LINE = ANY_QUESTION_STATUS_LINE.replace("the outage path or-gpt-6-luna enabled on 2026-10-28 by maintainer decision", "the outage path or-gpt-6-luna re-measured 2026-11-03, kept below rule 2")      # the newest entry (RESERVE-V3, 2026-11-03): the entry of ANY-QUESTION Q3 with the outage path re-measured
assert STATUS_LINE != ANY_QUESTION_STATUS_LINE and len(STATUS_LINE) <= 600
PROBE_DATE = "2026-11-03"      # the day the probe entry of ANY-QUESTION Q3 was written, and the day of the entry of RESERVE-V3 after it
P5_DATE = "2026-11-05"      # the day the probe entry of P5 (catalog version 4 and prompt rule 3) was written: the newest entry
P5_STATUS_LINE = ("enabled by maintainer decision 2026-10-21, below the gate; the e-mail text is worded and revised by the model; the catalog grew and moved to version 2 (CB-9, 2026-10-28), 3 (MAIL-SUMMARY-FLIP, 2026-10-31) and 4 (P5, 2026-11-05: agenda, service); "
                  "the prompt revised four times (BL5B, BL7-3, ANY-QUESTION 2026-11-03, P5 rule 3); the outage path or-gpt-6-luna re-measured 2026-11-03, kept below rule 2; the event card shown to the model (2026-11-01); revise prompt re-pinned 2026-11-01")
assert len(P5_STATUS_LINE) <= 600
MAIL_CARD_RECIPIENT_REASON = "The e-mail revise prompt (rule 3) gained a sentence: a question about who receives the e-mail asks for no change, even when it writes an address, and a polite request with a question mark is still a request. Two earlier paid proofs failed. Measured on this PR's head 8430a9ae, RESULT-MAIL-CARD-RECIPIENT-2026-11-01: 3 of 12 rows of the bar not met, one call of 102 in group D changed the recipient; enabled below the bar by the maintainer's decision of 2026-11-01. Only revise_prompt_sha256 changes."      # the newest entry (package mail-card-recipient): the text decided after the third proof; the test below fixes it
EVENT_CARD_PIN = PINNED_HASHES["event_card_prompt"]
LUNA_ROUTE_SHA256 = PINNED_HASHES["route_or_gpt_6_luna"]


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
    assert set(doc) == {"v", "entries"} and doc["v"] == 1 and len(doc["entries"]) >= 3
    p5 = doc["entries"][-1]
    doc = dict(doc, entries=doc["entries"][:-1])      # P5 appended its probe entry: the assertions below read the entries before it as they were decided (RESERVE-V3 is the last of them), the P5 block at the end reads the probe
    first, entry = doc["entries"][0], doc["entries"][-1]
    assert {key: first[key] for key in FIRST} == FIRST and first["date"] == "2026-10-21"      # the earlier entries stay as they were decided
    assert {key: entry[key] for key in OLD_HASHES} == OLD_HASHES      # the entry of RESERVE-V3 names the hashes it was decided on; the probe of P5 names those of this checkout
    assert entry["basis"] == "maintainer-decision" and entry["date"] == PROBE_DATE and entry["route"] == ROUTE
    assert entry["languages"] == LANGUAGES and entry["status_line"] == STATUS_LINE
    by_line = {e["status_line"]: e for e in doc["entries"]}
    assert "compose_prompt_sha256" not in by_line[S8_STATUS_LINE], "the entry of S8 pins no compose prompt"
    assert by_line[COMPOSE_STATUS_LINE]["date"] == "2026-10-21" and by_line[COMPOSE_STATUS_LINE]["compose_prompt_sha256"] == PINNED_HASHES["compose_prompt_s7"] and "revise_prompt_sha256" not in by_line[COMPOSE_STATUS_LINE]
    assert by_line[S12_STATUS_LINE]["date"] == "2026-10-22" and by_line[S12_STATUS_LINE]["compose_prompt_sha256"] != by_line[COMPOSE_STATUS_LINE]["compose_prompt_sha256"] and "revise_prompt_sha256" not in by_line[S12_STATUS_LINE]
    assert by_line[S13_STATUS_LINE]["date"] == "2026-10-22" and by_line[S13_STATUS_LINE]["compose_prompt_sha256"] == by_line[S12_STATUS_LINE]["compose_prompt_sha256"] and "revise_prompt_sha256" in by_line[S13_STATUS_LINE]
    assert by_line[S13_STATUS_LINE]["catalog_sha256"] == PINNED_HASHES["interpreter_catalog_s13"] != by_line[R2F1_STATUS_LINE]["catalog_sha256"], "R2-F1 added `research` to the catalog: its entry names the new hash"
    pins = ("route_sha256", "prompt_sha256", "protocol_sha256", "compose_prompt_sha256", "revise_prompt_sha256")
    assert {key: by_line[R2F1_STATUS_LINE][key] for key in pins} == {key: by_line[S13_STATUS_LINE][key] for key in pins}, "every other pin of the entry of R2-F1 stands as decided"
    s13b = by_line[S13B_STATUS_LINE]
    assert s13b["catalog_sha256"] == by_line[R2F1_STATUS_LINE]["catalog_sha256"] != entry["catalog_sha256"] == OLD_HASHES["catalog_sha256"], "S13b names the catalog of R2-F1; R2-A adds `file-trash` and its entry names the new hash"
    assert by_line[S13_STATUS_LINE]["revise_prompt_sha256"] != s13b["revise_prompt_sha256"] and "revise_prompt_sha256" in s13b, "the revise prompt was re-pinned by the entry of S13b"
    assert s13b["compose_prompt_sha256"] == by_line[S12_STATUS_LINE]["compose_prompt_sha256"], "and it carries the compose pin of S12"
    assert {key: s13b[key] for key in ("route_sha256", "prompt_sha256", "protocol_sha256")} == {key: by_line[S13_STATUS_LINE][key] for key in ("route_sha256", "prompt_sha256", "protocol_sha256")}
    r2a = by_line[R2A_STATUS_LINE]
    assert r2a["date"] == "2026-10-22" and r2a["catalog_sha256"] == PINNED_HASHES["interpreter_catalog_s8"] != entry["catalog_sha256"], "an earlier entry (R2-A) names the catalog before B″-lite; the newest names the new hash"
    assert {key: r2a[key] for key in PINS} == {key: s13b[key] for key in PINS}, "R2-A carries every pin of S13b, the re-pinned revise prompt included"
    bl1 = by_line[BL1_STATUS_LINE]
    assert bl1["date"] == "2026-10-24" and {key: bl1[key] for key in RECORDED} == RECORDED, "B″-lite was decided on the recorded prompt"
    assert {key: bl1[key] for key in PINS} == {key: r2a[key] for key in PINS} and {key for key in bl1 if bl1[key] != r2a[key]} == {"date", "catalog_sha256", "reason", "status_line"}
    bl5b = by_line[BL5B_STATUS_LINE]
    assert bl5b["date"] == "2026-10-25" and bl5b["prompt_sha256"] == PINNED_HASHES["interpreter_prompt_1423"] != bl1["prompt_sha256"] == PINNED_HASHES["interpreter_prompt_5bee"]
    assert {key for key in bl5b if bl5b[key] != bl1[key]} == {"date", "prompt_sha256", "reason", "status_line"}, "the entry of BL5B changes the prompt hash, the date, the reason and the status line, and nothing else"
    bl73 = by_line[BL73_STATUS_LINE]
    assert bl73["date"] == "2026-10-26" and {key for key in bl73 if bl73[key] != bl5b[key]} == {"date", "prompt_sha256", "reason", "status_line"}, "the entry of BL7-3 changes the prompt hash, the date, the reason and the status line, and nothing else"
    assert bl73["prompt_sha256"] == PINNED_HASHES["interpreter_prompt_3112"] != bl5b["prompt_sha256"] == PINNED_HASHES["interpreter_prompt_1423"]
    cb9, luna, mail_ask, card_entry = doc["entries"][-7], doc["entries"][-6], doc["entries"][-5], doc["entries"][-4]
    assert bl73["catalog_sha256"] == PINNED_HASHES["interpreter_catalog_blite"] != cb9["catalog_sha256"] == PINNED_HASHES["interpreter_catalog_cb9"], "the entry before CB-9 names the catalog of version 1; the entry of CB-9 names the catalog of version 2"
    assert mail_ask["catalog_sha256"] == card_entry["catalog_sha256"] == entry["catalog_sha256"] == PINNED_HASHES["interpreter_catalog_mail_ask"] != luna["catalog_sha256"] == PINNED_HASHES["interpreter_catalog_cb9"], "the entry of the flip and the two after it name the catalog of version 3, served with the row mail-ask; the entry before them still names version 2"
    assert cb9["status_line"] == CB9_STATUS_LINE and cb9["date"] == "2026-10-28" and "fallback" not in cb9
    assert {key for key in cb9 if cb9[key] != bl73[key]} == {"date", "catalog_sha256", "reason", "status_line"}, "the entry of CB-9 changes the catalog hash, the date, the reason and the status line, and nothing else: prompt, protocol, route and e-mail prompts stand as decided"
    assert doc["entries"][-8] == bl73 and "CB-9" in cb9["status_line"] and "CB-9" in cb9["reason"] and "version 2" in cb9["reason"] and len(cb9["reason"]) <= interpreter_enable.TEXT_MAX and len(cb9["status_line"]) <= interpreter_enable.TEXT_MAX
    assert "Measured on this PR's head before merge" in cb9["reason"] and "only after the maintainer's decision on that measurement" in cb9["reason"]
    # LUNA-ENABLE: its entry copies every pin of the entry of CB-9 and adds the outage path, and nothing else changes but the date text fields
    assert luna["status_line"] == LUNA_STATUS_LINE and luna["date"] == "2026-10-28"
    assert {key for key in luna if luna.get(key) != cb9.get(key)} == {"reason", "status_line", "fallback"}, "the entry of LUNA-ENABLE changes the reason and the status line and adds `fallback`; every pin stands as decided"
    assert luna["fallback"] == [{"route": "or-gpt-6-luna", "route_sha256": LUNA_ROUTE_SHA256, "measured": luna["fallback"][0]["measured"]}] and len(luna["reason"]) <= interpreter_enable.TEXT_MAX
    assert "20261028T201315Z-daa387c8" in luna["fallback"][0]["measured"] and "20261028T214447Z-751dcc45" in luna["fallback"][0]["measured"] and "2026-10-28-luna-enable-fallback" in luna["fallback"][0]["measured"]
    # MAIL-SUMMARY-FLIP: its entry copies every pin and the outage path of the entry before it and changes the catalog hash, the date and the two texts, and nothing else
    assert mail_ask["status_line"] == MAIL_ASK_STATUS_LINE and mail_ask["date"] == "2026-10-31"
    assert {key for key in mail_ask if mail_ask.get(key) != luna.get(key)} == {"date", "catalog_sha256", "reason", "status_line"}, "the entry of the flip changes the catalog hash, the date and the texts; prompt, protocol, route, e-mail prompts and the outage path stand as decided"
    assert mail_ask["fallback"] == luna["fallback"] and len(mail_ask["reason"]) <= interpreter_enable.TEXT_MAX and len(mail_ask["status_line"]) <= interpreter_enable.TEXT_MAX
    assert "MAIL-SUMMARY-FLIP" in mail_ask["reason"] and "mail-ask" in mail_ask["reason"] and "version 3" in mail_ask["reason"]
    assert "Measured on this PR's head before merge" in mail_ask["reason"] and "only after the maintainer's decision on that measurement" in mail_ask["reason"]
    # CARD-MODEL-SEES: its entry copies every pin and the outage path of the entry of the flip and adds the pin of the event card text, and nothing else changes but the date text fields
    assert {key for key in card_entry if card_entry.get(key) != mail_ask.get(key)} - {"date"} == {"reason", "status_line", "event_card_prompt_sha256"}, "its entry adds the event card pin; every other pin and the outage path stand as decided"
    assert card_entry["date"] >= mail_ask["date"], "an entry is dated no earlier than the one above it: `load` raises otherwise"
    assert card_entry["fallback"] == mail_ask["fallback"] and card_entry["event_card_prompt_sha256"] == EVENT_CARD_PIN and "event_card_prompt_sha256" not in mail_ask
    assert "RESULT-CARD-MODEL-2026-11-01" in card_entry["reason"] and "<date>" not in card_entry["reason"] and "enabled below that rule by the maintainer's decision of 2026-11-01" in card_entry["reason"] and "wrong_card 2 items of 140 against at most 1" in card_entry["reason"] and len(card_entry["reason"]) <= interpreter_enable.TEXT_MAX and len(card_entry["status_line"]) <= interpreter_enable.TEXT_MAX
    assert card_entry["status_line"] == EVENT_CARD_STATUS_LINE and card_entry["date"] == "2026-11-01"
    recipient, probe = doc["entries"][-3], doc["entries"][-2]
    # mail-card-recipient, third text: the entry of mail-card-recipient copies every pin, the event card pin and the outage path of the entry before it and re-pins the revise prompt, and nothing else changes but the texts
    assert recipient["status_line"] == RECIPIENT_STATUS_LINE and recipient["date"] == "2026-11-01" and recipient["date"] >= card_entry["date"]
    assert {key for key in recipient if recipient.get(key) != card_entry.get(key)} == {"reason", "status_line", "revise_prompt_sha256"}, "the entry of mail-card-recipient changes the reason, the status line and the revise prompt's pin, and nothing else"
    assert recipient["fallback"] == card_entry["fallback"] and recipient["event_card_prompt_sha256"] == EVENT_CARD_PIN and recipient["compose_prompt_sha256"] == card_entry["compose_prompt_sha256"]
    assert recipient["revise_prompt_sha256"] == PINNED_HASHES["revise_prompt_recipient_v3"] != card_entry["revise_prompt_sha256"] and len(recipient["reason"]) <= interpreter_enable.TEXT_MAX and len(recipient["status_line"]) <= interpreter_enable.TEXT_MAX
    assert recipient["reason"] == MAIL_CARD_RECIPIENT_REASON, "the newest entry carries the text the maintainer decided on 2026-11-01, after the third proof (RESULT-MAIL-CARD-RECIPIENT-2026-11-01)"
    assert "Two earlier paid proofs failed" in recipient["reason"] and "a question about who receives the e-mail asks for no change" in recipient["reason"] and "RESULT-MAIL-CARD-RECIPIENT-2026-11-01" in recipient["reason"] and "<date>" not in recipient["reason"] and "enabled below the bar by the maintainer's decision of 2026-11-01" in recipient["reason"] and "3 of 12 rows of the bar not met" in recipient["reason"]
    # ANY-QUESTION Q3, the probe of the draft: the probe entry (the second newest) copies every pin of the entry before it and re-pins the interpreter's prompt, and nothing else changes but the date and the texts
    assert {key for key in probe if probe.get(key) != recipient.get(key)} == {"date", "prompt_sha256", "reason", "status_line"}, "the probe entry changes the prompt hash, the date, the reason and the status line, and nothing else"
    assert probe["prompt_sha256"] == PINNED_HASHES["interpreter_prompt_9e63"] != recipient["prompt_sha256"] == PINNED_HASHES["interpreter_prompt_3112"]
    assert probe["date"] >= recipient["date"] and probe["status_line"] == ANY_QUESTION_STATUS_LINE and len(probe["reason"]) <= interpreter_enable.TEXT_MAX and len(probe["status_line"]) <= interpreter_enable.TEXT_MAX
    assert "ANY-QUESTION Q3" in probe["reason"] and "rule 12" in probe["reason"] and "the outage path serves the new prompt unmeasured" in probe["reason"], "the entry of 2026-11-03 (ANY-QUESTION Q3) is kept as it was decided; the entry after it records the measurement"
    assert "RESULT-ANY-QUESTION-2026-11-03" in probe["reason"] and "<date>" not in probe["reason"] and "enabled below that rule by the maintainer's decision of 2026-11-03" in probe["reason"] and "rule 4 not met" in probe["reason"]
    # RESERVE-V3: the newest entry copies every key and value of the probe entry (the prompt, catalog, protocol, route, languages, compose, revise and event card pins) and changes only the reason, the status line and, inside the outage path, the text `measured` (its date is the probe entry's)
    assert {key for key in set(entry) | set(probe) if entry.get(key) != probe.get(key)} == {"reason", "status_line", "fallback"}, "the entry of RESERVE-V3 changes the reason, the status line and the outage path's `measured` against the probe entry (the date is the same day), and nothing else"
    assert entry["date"] == "2026-11-03" and entry["date"] >= probe["date"] and len(entry["fallback"]) == len(probe["fallback"]) == 1
    new_item, old_item = entry["fallback"][0], probe["fallback"][0]
    assert {key for key in set(new_item) | set(old_item) if new_item.get(key) != old_item.get(key)} == {"measured"}, "inside the outage path only `measured` differs: the measurement of 2026-11-03"
    assert new_item["route"] == old_item["route"] == "or-gpt-6-luna" and new_item["route_sha256"] == old_item["route_sha256"] == LUNA_ROUTE_SHA256
    assert interpreter_enable.fallbacks(entry) == interpreter_enable.fallbacks(probe) and 0 < len(new_item["measured"]) <= interpreter_enable.TEXT_MAX
    assert "2026-11-03" in new_item["measured"] and "20261103T184754Z-5dad949d" in new_item["measured"] and "20261103T184655Z-19a743ea" in new_item["measured"] and "2026-11-03-reserve-route-kept" in new_item["measured"] and "2026-10-28-luna-enable-fallback" in new_item["measured"] and "rule 2 not met" in new_item["measured"]
    assert interpreter_enable.fallbacks(entry) == [{"route": "or-gpt-6-luna", "route_sha256": LUNA_ROUTE_SHA256}], "the outage route stays in force with the row hash the entry pins"
    assert entry["status_line"] == STATUS_LINE and len(entry["reason"]) <= interpreter_enable.TEXT_MAX and len(entry["status_line"]) <= interpreter_enable.TEXT_MAX and "re-measured 2026-11-03, kept below rule 2" in entry["status_line"] and "enabled on 2026-10-28" not in entry["status_line"]
    assert "RESULT-RESERVE-V3-2026-11-03" in entry["reason"] and "rule 2 not met" in entry["reason"] and "kept as the fallback below rule 2 by the maintainer's decision of 2026-11-03" in entry["reason"] and "<date>" not in entry["reason"]
    assert "or-gpt-6-luna" in entry["reason"] and "rules 1 and 4 met" in entry["reason"] and "12.7" in entry["reason"] and "11.9" in entry["reason"] and "at most 10" in entry["reason"] and "no effect without confirmation" in entry["reason"]
    # P5: the newest entry, the probe of the draft, copies every key and value of the entry of RESERVE-V3 (route, protocol, languages, compose, revise and event card pins, the outage path) and changes only the date, the prompt hash, the catalog hash, the reason and the status line
    assert {key for key in set(p5) | set(entry) if p5.get(key) != entry.get(key)} == {"date", "prompt_sha256", "catalog_sha256", "reason", "status_line"}, "the probe entry of P5 changes the date, the two hashes and the two texts, and nothing else"
    assert {key: p5[key] for key in HASHES} == HASHES and p5["date"] == P5_DATE and p5["date"] >= entry["date"] and p5["basis"] == "maintainer-decision" and p5["route"] == ROUTE and p5["languages"] == LANGUAGES
    assert p5["prompt_sha256"] == PINNED_HASHES["interpreter_prompt"] != entry["prompt_sha256"] == PINNED_HASHES["interpreter_prompt_9e63"], "the probe names the prompt with the second exception of rule 3; the entry before it names the one of ANY-QUESTION Q3"
    assert p5["catalog_sha256"] == PINNED_HASHES["interpreter_catalog_v4"] != entry["catalog_sha256"] == PINNED_HASHES["interpreter_catalog_mail_ask"], "the probe names the catalog of version 4; the entry before it names version 3"
    assert p5["fallback"] == entry["fallback"] and p5["event_card_prompt_sha256"] == EVENT_CARD_PIN and p5["compose_prompt_sha256"] == entry["compose_prompt_sha256"] and p5["revise_prompt_sha256"] == entry["revise_prompt_sha256"], "the outage path (Luna) and every other pin stand as decided: the question about the outage route is decided after the measurement"
    assert p5["status_line"] == P5_STATUS_LINE and len(p5["reason"]) <= interpreter_enable.TEXT_MAX and len(p5["status_line"]) <= interpreter_enable.TEXT_MAX
    assert "P5" in p5["reason"] and "version 4" in p5["reason"] and "prompt rule 3" in p5["reason"] and "agenda" in p5["reason"] and "service" in p5["reason"]
    assert "Measured on this PR's head before merge (RESULT-P5-CATALOG-V4-<date>)" in p5["reason"] and "only after the maintainer's decision on that measurement" in p5["reason"], "the marker stands until the result is written: the merge gate below is red while it does"


@pytest.mark.skipif(not os.environ.get("CI"), reason="the merge gate of the draft: it runs in CI (which sets CI) and is skipped on a machine, the pre-commit hook included, so that the draft can be committed with the marker still in the reason; CI=1 runs it by hand")
def test_the_newest_entry_names_the_result_file_it_was_decided_on_before_the_pull_request_merges():
    """The reason of the newest entry says "RESULT-P5-CATALOG-V4-<date>" while the measurement is pending (it is filled, as the entries before it say "RESULT-RESERVE-V3-2026-11-03", "RESULT-ANY-QUESTION-2026-11-03" and "RESULT-MAIL-CARD-RECIPIENT-2026-11-01"); while a measurement is pending a marker "RESULT-<name>-<date>" stands and this test is red until the date of the run is written there: the marker cannot merge unfilled."""
    reason = committed()["entries"][-1]["reason"]
    assert "<date>" not in reason, "write the date of the measurement's result file in the reason of the newest entry (RESULT-<name>-YYYY-MM-DD)"


def test_the_marker_gate_reads_the_reason_and_the_dates_of_the_entries_are_in_order(tmp_path):
    entries = committed()["entries"]
    assert [e["date"] for e in entries] == sorted(e["date"] for e in entries), "`load` raises on an entry dated before the one above it, and the interpreter goes off for everyone"
    assert "<date>" in variant(tmp_path, "pending.json", reason="Measured on this PR's head before merge (RESULT-MAIL-CARD-RECIPIENT-<date>).").read_text(encoding="utf-8"), "control: the marker form the gate refuses"


def test_the_checkout_has_the_hashes_the_entry_was_decided_on_and_it_is_in_force_for_each_listed_language():
    assert interpreter_enable.checkout_hashes(ROUTE) == HASHES
    assert interpreter_evidence.hashes(interpreter_route.find(ROUTE))["protocol_sha256"] == HASHES["protocol_sha256"]
    for language in LANGUAGES:
        found = interpreter_enable.active(language)
        assert found is not None and found["route"]["id"] == ROUTE and found["route"]["kind"] == "http" and found["entry"]["date"] == P5_DATE, language
    for language in ("ja", "pt-br", "en-GB", "", None):
        assert interpreter_enable.active(language) is None, language


def test_the_event_card_is_on_only_while_the_newest_entry_pins_this_checkouts_text_and_a_changed_text_turns_only_it_off(tmp_path):
    assert interpreter_enable.card_active("en")["entry"]["event_card_prompt_sha256"] == EVENT_CARD_PIN == event_card.prompt_sha256()
    for name, change in (("wrong", {"event_card_prompt_sha256": "0" * 64}), ("missing", {"event_card_prompt_sha256": None})):
        path = str(variant(tmp_path, name + ".json", **change))
        assert interpreter_enable.card_active("en", path=path) is None, name
        assert interpreter_enable.active("en", path=path) is not None and interpreter_enable.revise_active("en", path=path) is not None and interpreter_enable.compose_active("en", path=path) is not None, \
            name + ": the interpreter and the e-mail paths stay on"
    assert interpreter_enable.card_active("en", path=str(variant(tmp_path, "same.json"))) is not None, "control: the unchanged copy is on, so the two cases above are off because of the pin"
    assert interpreter_enable.card_active("ja") is None, "a language the entry does not list is off"


@pytest.mark.parametrize("name, change", [
    ("prompt", {"prompt_sha256": "0" * 64}), ("catalog", {"catalog_sha256": "0" * 64}), ("route", {"route_sha256": "0" * 64}), ("protocol", {"protocol_sha256": "0" * 64}),
    ("language", {"languages": ["ja"]}), ("unknown-route", {"route": "no-such-route"}), ("account-route", {"route": "acct-claude-sonnet-5.5"}),
    ("extra-key", {"extra": "key"}), ("missing-key", {"reason": None}), ("date-shape", {"date": "21/10/2026"}), ("date-not-a-day", {"date": "2026-02-30"}),
    ("basis", {"basis": "evidence"}), ("hash-shape", {"prompt_sha256": "5BEE55CE" + HASHES["prompt_sha256"][8:]}), ("languages-twice", {"languages": ["en", "en"]}),
    ("compose-hash-shape", {"compose_prompt_sha256": "NOT-A-HASH"}), ("event-card-hash-shape", {"event_card_prompt_sha256": "NOT-A-HASH"}),
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


def test_the_committed_entries_are_in_date_order_and_an_entry_appended_with_an_earlier_date_turns_the_interpreter_off(tmp_path):
    """Review of MAIL-SUMMARY-FLIP: packages that append an entry each (#674 and #680 are dated 2026-10-30, the flip 2026-10-31) must date it at least as late as the newest entry when they are rebased onto
    the others: `load` raises on a file whose dates are not sorted, and `active` then answers None for every language, so the interpreter is off for everyone."""
    doc = committed()
    dates = [e["date"] for e in doc["entries"]]
    assert dates == sorted(dates) and interpreter_enable.load()["entries"] == doc["entries"]
    late = dict(doc["entries"][-1], date="2026-10-30")      # the day before the newest entry
    path = tmp_path / "late.json"
    path.write_text(json.dumps({"v": 1, "entries": doc["entries"] + [late]}), encoding="utf-8")
    with pytest.raises(interpreter_enable.EnableError):
        interpreter_enable.load(str(path))
    assert all(interpreter_enable.active(language, path=str(path)) is None for language in LANGUAGES)
    same_day = dict(doc["entries"][-1])
    path.write_text(json.dumps({"v": 1, "entries": doc["entries"] + [same_day]}), encoding="utf-8")
    assert interpreter_enable.load(str(path)) and interpreter_enable.active("en", path=str(path)) is not None, "the same day is in order"


def test_the_status_reads_the_same_committed_file_and_prints_the_decision_beside_the_route():
    status = status_module()
    read = status.enable_status(str(REPO), status.load_inputs())
    assert read["present"] and read["in_force"] and read["date"] == P5_DATE and read["route"] == ROUTE and read["languages"] == LANGUAGES and read["status_line"] == P5_STATUS_LINE
    assert interpreter_enable.active("en") is not None
    assert f"  {ROUTE}: {P5_STATUS_LINE}" in status.table(status.status(str(REPO)))


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
