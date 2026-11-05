"""The page's side of the grants (package POL-1; interface/js/permissions.js and floor/cards.js): `can` reads the effect words the service lists
(`approve:effect:<word>`), `grantsText` draws one line from the entry's `grants` and nothing when there are none, a three-part name is never split on
`:` when it is asked as a pair, and the service lists the grants only when the project grants something. Node runs the real module; no browser, no
model.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_channel_grants_page.py
"""
from __future__ import annotations

import re

import standin_tree as st
from test_interface_floor import INTERFACE, needs_node, run_node

operations = st.load("operations")

PAGE = r"""
import { can, withheld, fingerprint, grantsText, ASKED } from "@JS@/permissions.js";
const list = (allowed, grants) => ({ id: "p", permissions: { channel: "page", allowed, ...(grants ? { grants } : {}) } });
const only = list(["status", "approve:plan", "approve:effect", "approve:effect:write"]);
const out = {};
out.words = [can(only, "approve", "effect:write"), can(only, "approve", "effect:send"), can(only, "approve", "effect"), can(only, "approve", "plan")];
out.withheld = withheld(only, [["approve", "effect:write"], ["approve", "effect:send"], ["approve", "effect:publish"]]);
out.everything = [can({ id: "p" }, "approve", "effect:send"), can(null, "approve", "effect:send"), can({ id: "p", permissions: null }, "approve", "effect:write")];
out.asked = ASKED.filter(([op, kind]) => op === "approve").map(([, kind]) => kind);
out.fingerprint = fingerprint((op, kind) => can(only, op, kind)).length === ASKED.length;
out.text = [
  grantsText(list([], [{ channel: "messaging", group: "approve-effect-write", text: "a messaging app may approve a write" }])),
  grantsText(list([], [{ channel: "messaging", group: "a", text: "one" }, { channel: "mcp", group: "b", text: "two" }, { channel: "mcp", group: "c" }])),
  grantsText(list([])), grantsText(null), grantsText({ id: "p" }), grantsText({ permissions: { grants: "no" } }), grantsText({ permissions: { grants: [null, 3] } }),
];
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_page_asks_by_word_draws_one_line_for_the_grants_and_a_project_without_them_shows_nothing(tmp_path):
    got = run_node(tmp_path, PAGE)
    assert got["words"] == [True, False, True, True], "the word the service listed is allowed; another word is not; `approve:effect` says that some word is"
    assert got["withheld"] == ["approve"], "withheld names the operation, once, for the words refused"
    assert got["everything"] == [True, True, True], "an entry without the key, or null, hides nothing"
    assert got["asked"] == ["plan", "acceptance", "effect", "go-ahead", "effect:create", "effect:write", "effect:send", "effect:send-own", "effect:publish", "effect:calendar", "effect:files", "effect:mailbox", "effect:tasks"]
    assert got["fingerprint"] is True
    assert got["text"][0] == "Your configuration widens: a messaging app may approve a write."
    assert got["text"][1] == "Your configuration widens: one; two."
    assert got["text"][2:] == ["", "", "", "", ""]


def test_the_card_asks_the_policy_by_the_effects_word_and_the_words_are_the_operations_layers():
    cards = (INTERFACE / "js" / "floor" / "cards.js").read_text(encoding="utf-8")
    assert "`effect:${state.item.effect_word}`" in cards, "the card asks approve:effect:<word>, and `effect` when the decision names no word"
    asked = re.findall(r'\["approve", "(effect:[a-z-]+)"\]', (INTERFACE / "js" / "permissions.js").read_text(encoding="utf-8"))
    assert asked == [f"effect:{word}" for word in operations.EFFECT_APPROVAL_WORDS]


def test_the_service_lists_the_grants_only_when_the_project_grants_something():
    service = st.load("service")
    policies = {"page": ["read"]}
    fake = type("Ops", (), {"operations": operations, "config": staticmethod(lambda folder: {"accepted": True, "channels": policies}),
                            "OpsError": Exception})
    holder = type("Service", (), {"ops": fake})
    entry = {"folder": "x", "config": {"accepted": True}}
    assert "grants" not in service._permissions(holder, entry)
    policies.update({"messaging": ["read", "approve-effect-write"], "mcp": ["read", "retry"]})
    listed = service._permissions(holder, entry)["grants"]
    assert [(g["channel"], g["group"]) for g in listed] == [("messaging", "approve-effect-write"), ("mcp", "retry")]
    assert all(g["text"] == operations.GRANT_TEXT[f"{g['channel']}:{g['group']}"] for g in listed)


def test_the_service_names_a_group_a_senders_profile_holds_and_never_the_sender():
    service = st.load("service")
    policies = {"page": ["read"], operations.SENDERS_KEY: {"telegram:55119000000001": ["read", "approve-effect-write", "approve-effect-send"]}}
    fake = type("Ops", (), {"operations": operations, "config": staticmethod(lambda folder: {"accepted": True, "channels": policies}),
                            "OpsError": Exception})
    holder = type("Service", (), {"ops": fake})
    entry = {"folder": "x", "config": {"accepted": True}}
    listed = service._permissions(holder, entry)["grants"]
    assert [(g["channel"], g["group"]) for g in listed] == [("messaging", "approve-effect-write"), ("messaging", "approve-effect-send")]
    assert all(g["text"].endswith("(to a listed sender whose profile lists it)") and "55119000000001" not in g["text"] for g in listed)
    policies["messaging"] = ["read", "approve-effect-write"]        # the channel grants it itself: said once, as the channel's
    listed = service._permissions(holder, entry)["grants"]
    assert [(g["channel"], g["group"], g["text"].endswith("lists it)")) for g in listed] == [("messaging", "approve-effect-write", False),
                                                                                              ("messaging", "approve-effect-send", True)]
