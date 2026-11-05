"""The language of the fixed sentences, per sender or per channel (package TT-2, maintainer decision 2026-10-27, option C): a profile of `policies` may carry
`sentence_language` (a tag of the phrase table), and the sentences the runtime says to a person (cards, confirmations, refusals, reminders, the plan question) are
then said in that language for that sender, or on the channel the profile is assigned to; every other sender, the terminal and every artifact keep the project's
language. The key (runtime/project_config.py `_policies`), its resolution (runtime/phrases.py `sentence_tag`, `sentence_override`), the thread-local scope
(`phrases.scope`, a `with` block) and where it is opened (`Bridge.sentences_for` in runtime/messaging_bridge.py and runtime/messaging_remind.py, `ops_say._sentences`).

The wording is asserted as the test's own literals of the column the sentence is in, never read from the table under test; a vacuity case in each part plants the wrong
result the part exists to prevent (the scope not read, the key read by the artifacts' language, a scan that cannot see a read). Offline, no model, no network; every name
and id is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_sentence_language.py
"""
from __future__ import annotations

import json
import re
import shutil
import threading
from pathlib import Path

import pytest

import standin_tree as st
from phone_literals import PLAIN_REFUSAL, PLAIN_REFUSAL_PT
from plan_bridge_kit import ASKER_ID, OWNER_ID, brig, rig, world  # noqa: F401  (the bridge, the stand-in messenger and the real-operations world of the plan question)
from plan_confirm_kit import PROF
from test_effects import tree  # noqa: F401  (the stand-in tree fixture)
from test_messaging_reminders import WITH, day, reminder_texts  # noqa: F401  (the lab with a clock and three listed senders)
from test_ops_natural import SENDERS as WORLD_SENDERS
from test_sender_profiles import OWNER, STAFF, accept, loaded
from test_sender_profiles_bridge import CLERK, OTHER, lab  # noqa: F401  (the lab fixture)
from closed_heads import closed_heads, tier1_forms, words_interpreted  # noqa: F401  (S41-11: the claim of the write families and of every closed form, as fixtures; a plain line is read by the interpreter's stand-in)

ops = st.load("ops")
ops_core = st.load("ops_core")
ops_say = st.load("ops_say")
bridge = st.load("messaging_bridge")
language = st.load("language")
phrases = st.load("phrases")
ek = st.load("entry_kit")
project_config = st.load("project_config")

RUNTIME = st.REPO / "runtime"

# The sentences, as the test's own literals of the column each is in (T8: a phrase key and the column it is read from).
ASK_EN, ASK_PT = "Shall I go ahead?", "Posso?"
GREET_EN = "Hello! Here is what I can do for you now:"
GREET_PT = "Olá! Eu posso ajudar com isto:"  # validate: allow english-only -- the Portuguese sentence under test
NONE_OPEN_EN, NONE_OPEN_PT = "No request is open.", "Nenhum pedido aberto."
REMINDER_EN, REMINDER_PT = "Reminder: ", "Lembrete: "
PLAN_CARD_EN, PLAN_CARD_PT = "northwind-shop · plan #", "northwind-shop · plano #"

GUEST = ["read-limited", "talk"]
PT_ONLY = {"language": "pt-BR"}


def test_the_literals_are_the_columns_they_say_they_are():
    """The oracle's own check: each literal is the sentence of its key in its column, and the two columns differ (so a test that reads one cannot pass on the other)."""
    for key, en, pt in (("PLAN_ASK", ASK_EN, ASK_PT), ("GREET_HEAD", GREET_EN, GREET_PT), ("STATE_NONE_OPEN", NONE_OPEN_EN, NONE_OPEN_PT)):
        assert phrases.TABLE["en"][key] == en and phrases.TABLE["pt-BR"][key] == pt and en != pt, key
    assert phrases.TABLE["en"]["RM_TEXT_LINE"] == REMINDER_EN + "{text}" and phrases.TABLE["pt-BR"]["RM_TEXT_LINE"] == REMINDER_PT + "{text}"
    assert list(phrases.TABLE) == ["en", "pt-BR"], "the two tags a profile may name: TT-2 adds no column"


# --- 1. the key ----------------------------------------------------------------------------------------------------------------------------------


def refusal(profile):
    with pytest.raises(project_config.ConfigError) as caught:
        project_config._policies({"p": profile})
    return str(caught.value)


def test_a_value_that_is_not_a_tag_of_the_phrase_table_is_refused_naming_the_two():
    for given in ("es", "pt-br", "pt_BR", "", "EN", None, 5, True, ["en"], {"en": 1}):
        message = refusal({"groups": ["read"], "sentence_language": given})
        assert "runtime.json policies.p.sentence_language must be one of en, pt-BR" in message, given


def test_a_tag_of_the_table_is_kept_in_the_profile_and_no_key_adds_nothing():
    for given in ("en", "pt-BR"):
        assert project_config._policies({"p": {"groups": ["read"], "sentence_language": given}}) == \
            {"p": {"groups": ["read"], "notices": "all", "sentence_language": given}}
    # a file with no key loads as it always did: the record is the two keys it had, the list form has no place for the key
    assert project_config._policies({"p": {"groups": ["read"]}, "q": ["read"]}) == \
        {"p": {"groups": ["read"], "notices": "all"}, "q": {"groups": ["read"], "notices": "all"}}
    assert "sentence_language" in project_config.PROFILE_KEYS


def test_the_key_is_not_a_group_and_grants_nothing():
    senders = {"telegram": [{"id": "111", "policy": "p"}]}
    plain = loaded({"p": {"groups": ["read", "talk"]}}, {"messaging": "p"}, {"senders": senders})
    keyed = loaded({"p": {"groups": ["read", "talk"], "sentence_language": "en"}}, {"messaging": "p"}, {"senders": senders})
    assert keyed[1] == plain[1] and keyed[2] == plain[2], "the sender table and the channels' resolved groups are the same with the key and without it"
    assert set(keyed[0]["p"]) - set(plain[0]["p"]) == {"sentence_language"}
    with pytest.raises(project_config.ConfigError):      # it is not a name of the list of groups: a group list that carries it is refused as any unknown group is
        project_config._policies({"p": ["read", "sentence_language"]})


# --- 2. the resolution ---------------------------------------------------------------------------------------------------------------------------


def configuration(**extra):
    """A configuration as `project_config.load` shapes it, in the project's language pt-BR: an owner with no key, a sender with `en`, a sender with a profile that has no key, a channel profile."""
    cfg = {"language": "pt-BR",
           "policies": {"owner": {"groups": ["read"], "notices": "all"}, "en-desk": {"groups": ["read"], "notices": "all", "sentence_language": "en"},
                        "pt-desk": {"groups": ["read"], "notices": "all", "sentence_language": "pt-BR"}, "bare": {"groups": ["read"], "notices": "all"}},
           "channel_profiles": {"page": "en-desk", "mcp": "bare", "messaging": "pt-desk"},
           "messaging": {"sender_profiles": {"telegram": {"111": "en-desk", "222": "owner", "333": "bare"}}}}
    cfg.update(extra)
    return cfg


def test_the_sender_s_profile_wins_then_the_channel_s_then_the_project_s_language():
    cfg = configuration()
    assert phrases.sentence_tag(cfg, "messaging", "telegram:111") == "en", "the sender's own profile"
    assert phrases.sentence_tag(cfg, "messaging", "telegram:222") == "pt-BR", "a profile with no key: the channel's (pt-desk) says pt-BR, as the project does"
    cfg["channel_profiles"]["messaging"] = "en-desk"
    assert phrases.sentence_tag(cfg, "messaging", "telegram:222") == "en", "a sender whose profile sets nothing takes the channel profile's key"
    assert phrases.sentence_tag(cfg, "messaging", "telegram:999") == "en", "a sender with no profile of their own: the channel's"
    assert phrases.sentence_tag(cfg, "messaging", "telegram:111") == "en"
    del cfg["channel_profiles"]["messaging"]
    assert phrases.sentence_tag(cfg, "messaging", "telegram:222") == "pt-BR" and phrases.sentence_tag(cfg, "messaging", "telegram:999") == "pt-BR", "no key anywhere: the project's language"
    assert phrases.sentence_override(cfg, "messaging", "telegram:222") is None and phrases.sentence_override(cfg, "messaging", "telegram:111") == "en"
    assert phrases.sentence_override(cfg, "messaging") is None and phrases.sentence_override(cfg, "messaging", None) is None, "no sender: only the channel's profile could set it, and it has none here"


def test_the_page_and_the_mcp_mode_read_the_channel_s_profile_and_the_terminal_is_never_narrowed():
    cfg = configuration()
    assert phrases.sentence_tag(cfg, "page") == "en" and phrases.sentence_tag(cfg, "mcp") == "pt-BR", "page: en-desk; mcp: a profile with no key"
    for channel in ("terminal", "chat", "queue", None, "bogus"):
        assert phrases.sentence_override(cfg, channel, "telegram:111") is None, channel
        assert phrases.sentence_tag(cfg, channel, "telegram:111") == "pt-BR", channel
    cfg["channel_profiles"]["terminal"] = "en-desk"      # not a file the loader accepts (the terminal has no profile), and not read if it were
    assert phrases.sentence_tag(cfg, "terminal") == "pt-BR"


def test_a_value_outside_the_table_that_got_into_a_configuration_is_ignored_and_the_project_language_is_kept():
    cfg = configuration()
    del cfg["channel_profiles"]["messaging"]      # nothing for the sender to fall back to but the project's language
    for planted in ("es", 5, None, ["en"], ""):
        cfg["policies"]["en-desk"]["sentence_language"] = planted
        assert phrases.sentence_override(cfg, "messaging", "telegram:111") is None and phrases.sentence_tag(cfg, "messaging", "telegram:111") == "pt-BR", planted
    assert phrases.sentence_tag({}, "messaging", "telegram:111") == "en" and phrases.sentence_tag(None, "page") == "en", "no configuration: the default of the table"
    assert phrases.sentence_tag({"language": "fr"}, "page") == "fr", "a project language with no table is the project's, and `text` gives it English as it always did"


# --- 3. the scope --------------------------------------------------------------------------------------------------------------------------------


def test_inside_a_scope_the_sentence_is_the_scoped_column_and_the_project_s_outside():
    assert phrases.text("PLAN_ASK", PT_ONLY) == ASK_PT and phrases.tag(PT_ONLY) == "pt-BR"
    with phrases.scope("en"):
        assert phrases.tag(PT_ONLY) == "en" and phrases.text("PLAN_ASK", PT_ONLY) == ASK_EN
        assert phrases.text("PLAN_ASK", {"language": "en"}) == ASK_EN and phrases.text("PLAN_ASK", None) == ASK_EN
    with phrases.scope("pt-BR"):
        assert phrases.text("PLAN_ASK", {}) == ASK_PT and phrases.text("PLAN_ASK", None) == ASK_PT, "a project with no language: the scope still says it"
    assert phrases.text("PLAN_ASK", PT_ONLY) == ASK_PT and phrases.current_scope() is None


def test_a_scope_nests_restores_on_every_exit_and_a_name_with_no_column_is_the_project_s_language():
    with phrases.scope("en"):
        with phrases.scope(None):
            assert phrases.tag(PT_ONLY) == "pt-BR" and phrases.current_scope() is None, "an inner scope with no name is the project's language, not the outer scope"
        assert phrases.current_scope() == "en"
        with phrases.scope("es"):
            assert phrases.tag(PT_ONLY) == "pt-BR", "a tag the table has no column for is not a scope"
        with phrases.scope("pt-BR"):
            assert phrases.tag({"language": "en"}) == "pt-BR"
        assert phrases.tag(PT_ONLY) == "en", "the outer scope came back"
    assert phrases.current_scope() is None
    with pytest.raises(RuntimeError):
        with phrases.scope("en"):
            raise RuntimeError("a line that failed")
    assert phrases.current_scope() is None and phrases.tag(PT_ONLY) == "pt-BR", "an exception inside the block does not leave the scope set"
    for planted in (5, ["en"], {"en": 1}):
        with phrases.scope(planted):
            assert phrases.current_scope() is None, planted


def test_a_scope_is_the_thread_s_own():
    inside, seen = threading.Event(), {}
    leave = threading.Event()

    def other():
        inside.wait(5)
        seen["tag"] = phrases.tag(PT_ONLY)
        leave.set()
    thread = threading.Thread(target=other)
    thread.start()
    with phrases.scope("en"):
        inside.set()
        assert leave.wait(5)
        assert phrases.tag(PT_ONLY) == "en"
    thread.join(5)
    assert seen == {"tag": "pt-BR"}, "another thread never sees the scope of this one"


def test_a_job_the_bridge_starts_takes_the_scope_of_the_thread_that_creates_it(day):
    seen = []
    with phrases.scope("en"):
        job = day.bridge.inherit(lambda: seen.append((phrases.tag(PT_ONLY), phrases.current_scope())))
    thread = threading.Thread(target=job)
    thread.start()
    thread.join(5)
    assert seen == [("en", "en")] and phrases.current_scope() is None
    plain = day.bridge.inherit(lambda: seen.append((phrases.tag(PT_ONLY), phrases.current_scope())))
    assert plain.__name__ != "run", "no scope and no languages read: the call itself, as it always was"
    thread = threading.Thread(target=plain)
    thread.start()
    thread.join(5)
    assert seen[-1] == ("pt-BR", None)


def test_vacuity_a_tag_that_ignores_the_scope_says_the_project_s_language_inside_it(monkeypatch):
    monkeypatch.setattr(phrases, "tag", lambda cfg=None: phrases._project_tag(cfg))
    with phrases.scope("en"):
        assert phrases.text("PLAN_ASK", PT_ONLY) == ASK_PT != ASK_EN, "the planted result: the assertions of the scope tests above would fail on it"


# --- 4. the bridge: one project in pt-BR, senders that differ ------------------------------------------------------------------------------------


def pt_project(day, owner_key=None, keys=("en", "en")):
    """The lab's project in pt-BR with four listed senders: the owner and the staff keep the project's language, the desk (OTHER) and a guest (CLERK) say `en`."""
    policies = {**WITH, "owner": WITH["owner"] if owner_key is None else {"groups": WITH["owner"], "sentence_language": owner_key},
                "desk": {"groups": WITH["desk"], "sentence_language": keys[0]}, "guest": {"groups": GUEST, "sentence_language": keys[1]}}
    accept(day.path, language="pt-BR", policies=policies, channels={"messaging": "staff"},
           messaging={"senders": {"telegram": [{"id": OWNER, "policy": "owner"}, {"id": STAFF, "policy": "staff"}, {"id": OTHER, "policy": "desk"},
                                               {"id": CLERK, "policy": "guest"}]}, "notices": "text"})
    return day


def test_a_refusal_is_said_in_the_language_of_the_sender_it_is_for(day):
    pt_project(day)
    day.say(STAFF, "/approve 3")
    day.say(CLERK, "/approve 3")
    assert day.texts(STAFF)[-1] == PLAIN_REFUSAL_PT, "the staff has no key: the project's language"
    assert day.texts(CLERK)[-1] == PLAIN_REFUSAL, "the guest's profile says en"
    assert phrases.current_scope() is None, "nothing stays open after a line"


def test_the_greeting_the_reminder_and_the_delivery_follow_each_sender_and_a_scope_never_reaches_the_next_line(day):
    pt_project(day)
    for who in (OTHER, OWNER, OTHER):
        day.say(who, "oi")
        day.settle()      # a greeting is answered from a job: the next line waits for it, as a person's would
    assert day.texts(OTHER)[0].startswith(GREET_EN) and day.texts(OTHER)[1].startswith(GREET_EN), "the en sender, twice"
    assert day.texts(OWNER)[0].startswith(GREET_PT), "the line of the other sender between them: pt-BR, never the en of the line before"
    day.say(OWNER, "/remind 15:00 Call the dentist")
    day.say(OTHER, "/remind 15:00 Take the bread out")
    assert day.texts(OWNER)[-1].startswith("Lembrete #1:") and day.texts(OTHER)[-1].startswith("Reminder #2:")  # validate: allow english-only -- the Portuguese sentence under test
    day.clock.set("2026-10-18 15:00")
    day.bridge.tick()
    assert [t for t in day.texts(OWNER) if t.startswith(REMINDER_PT)] == [REMINDER_PT + "Call the dentist"], "a delivery at tick time, outside any line: the sender's own language"
    assert [t for t in day.texts(OTHER) if t.startswith(REMINDER_EN)] == [REMINDER_EN + "Take the bread out"]
    assert not [t for t in day.texts(OTHER) if t.startswith(REMINDER_PT)] and not [t for t in day.texts(OWNER) if t.startswith(REMINDER_EN)]
    assert phrases.current_scope() is None


def test_a_card_is_drawn_in_the_language_of_the_sender_it_is_sent_to(day):
    pt_project(day)
    day.bridge.tick()
    plans = {who: next(t for t in day.texts(who) if t.split("\n")[0].endswith("#3")) for who in (OWNER, STAFF, OTHER)}      # the card of the plan: its first line is the project, the kind and the number
    assert plans[OWNER].startswith(PLAN_CARD_PT + "3") and plans[STAFF].startswith(PLAN_CARD_PT + "3"), "the owner and the staff: the project's language"
    assert plans[OTHER].startswith(PLAN_CARD_EN + "3"), "the desk's profile says en: the kind word of the card is English"
    assert "The plan." in plans[OTHER] and "The plan." in plans[OWNER], "the decision's own text is never translated"


def replies(day, lines):
    """What each line is answered with: [(sender, [the texts it added])], one line at a time, each settled (a greeting is answered from a job)."""
    out = []
    for who, line in lines:
        before = len(day.texts(who))
        day.say(who, line)
        day.settle()
        out.append((who, day.texts(who)[before:]))
        day.bridge.remind.drafts.clear()
    return out


def test_a_key_equal_to_the_project_s_language_changes_nothing_a_line_says(day):
    """The desk and the guest with the key set to the project's own language, and the same project with no key at all (the default): the same replies, byte for byte, on a set of lines."""
    lines = [(OTHER, "oi"), (CLERK, "oi"), (CLERK, "/approve 3"), (OTHER, "/remind"), (OTHER, "/forget x"), (CLERK, "ajuda"), (OTHER, "status"), (OWNER, "oi")]
    pt_project(day, keys=("pt-BR", "pt-BR"))
    with_key = replies(day, lines)
    accept(day.path, language="pt-BR", policies={**WITH, "guest": GUEST}, channels={"messaging": "staff"},
           messaging={"senders": {"telegram": [{"id": OWNER, "policy": "owner"}, {"id": STAFF, "policy": "staff"}, {"id": OTHER, "policy": "desk"},
                                               {"id": CLERK, "policy": "guest"}]}, "notices": "text"})
    without = replies(day, lines)
    assert with_key == without and all(texts for _, texts in without)
    assert [texts for who, texts in without if who == OTHER][0][0].startswith(GREET_PT) and [texts for who, texts in without if who == CLERK][1] == [PLAIN_REFUSAL_PT]
    pt_project(day, keys=("en", "en"))
    narrowed = replies(day, lines)
    assert narrowed != without and narrowed[0][1][0].startswith(GREET_EN) and narrowed[2][1] == [PLAIN_REFUSAL], "the same lines with the key `en` say something else: the comparison above has teeth"


def test_an_unaccepted_change_of_the_key_is_not_read_and_a_bridge_that_cannot_read_a_project_says_the_project_s_language(day, monkeypatch):
    pt_project(day)
    project = day.bridge.projects[0]
    assert day.bridge.sentence_name(OTHER, project) == "en" and day.bridge.sentence_name(OWNER, project) is None
    assert day.bridge.sentence_name(OTHER) == "en", "with no project: the first served project that lists the chat"
    accept_before = ops.config(day.path)["sha256"]
    raw_file = Path(day.path) / "docs" / "workbench" / "runtime.json"
    raw_file.write_text(raw_file.read_text().replace('"sentence_language": "en"', '"sentence_language": "pt-BR"'))
    assert ops.config(day.path)["sha256"] != accept_before and ops.config(day.path)["accepted"] is False
    assert day.bridge.sentence_name(OTHER, project) is None, "a file nobody accepted sets no language: it is a configuration change, accepted like any other"

    def broken(path):
        raise RuntimeError("the file cannot be read")
    monkeypatch.setattr(day.bridge.ops, "config", broken)
    assert day.bridge.sentence_name(OTHER, project) is None, "a project that cannot be read is said in the project's language, never held back"
    with day.bridge.sentences_for(OTHER, project):
        assert phrases.current_scope() is None


def test_vacuity_a_tag_that_ignores_the_scope_gives_the_en_sender_the_project_s_language(day, monkeypatch):
    pt_project(day)
    monkeypatch.setattr(phrases, "tag", lambda cfg=None: phrases._project_tag(cfg))
    day.say(CLERK, "/approve 3")
    assert day.texts(CLERK)[-1] == PLAIN_REFUSAL_PT != PLAIN_REFUSAL, "the planted result the refusal test above would fail on"


# --- 5. the plan question, on the real operations layer ------------------------------------------------------------------------------------------


def accept_world(world, **profile_keys):
    """The world of test_ops_natural.py in pt-BR with the plan question's senders; the asker's profile carries the keys given."""
    policies = {**PROF, "asker": {"groups": PROF["asker"], **profile_keys}}
    accept(world["path"], language="pt-BR", policies=policies, messaging={"senders": WORLD_SENDERS})


@pytest.mark.usefixtures("tier1_forms", "words_interpreted")
def test_the_question_posso_is_said_in_the_language_of_the_sender_who_asked(brig):
    accept_world(brig.world, sentence_language="en")
    brig.ask("mostra minha agenda", sender=OWNER_ID)
    brig.ask("mostra minha agenda", sender=ASKER_ID)
    assert brig.texts(OWNER_ID)[-1].endswith(ASK_PT) and not brig.texts(OWNER_ID)[-1].endswith(ASK_EN)
    assert brig.texts(ASKER_ID)[-1].endswith(ASK_EN) and not brig.texts(ASKER_ID)[-1].endswith(ASK_PT)
    assert phrases.current_scope() is None


# --- 6. the page, the MCP mode and the terminal ----------------------------------------------------------------------------------------------------


def page_profiles(world, **channels):
    policies = {**PROF, "page-en": {"groups": ["read", "talk"], "sentence_language": "en"}, "page-bare": ["read", "talk"], "mcp-en": {"groups": ["read", "talk"], "sentence_language": "en"}}
    accept(world["path"], language="pt-BR", policies=policies, channels=channels, messaging={"senders": WORLD_SENDERS})


def test_a_page_line_is_answered_in_the_channel_profile_s_language_and_the_terminal_in_the_project_s(world):
    page_profiles(world, page="page-en", mcp="mcp-en")
    assert ops.say(world["path"], "status", channel="page")["reply"].startswith(NONE_OPEN_EN)
    assert ops.say(world["path"], "status", channel="mcp")["reply"].startswith(NONE_OPEN_EN)
    assert ops.say(world["path"], "status", channel="terminal")["reply"].startswith(NONE_OPEN_PT), "the terminal is never narrowed"
    assert ops.say(world["path"], "status")["reply"].startswith(NONE_OPEN_PT), "nor the conversation's own shell"
    assert phrases.current_scope() is None
    page_profiles(world, page="page-bare")
    assert ops.say(world["path"], "status", channel="page")["reply"].startswith(NONE_OPEN_PT), "a profile with no key: the project's language"
    page_profiles(world)
    assert ops.say(world["path"], "status", channel="page")["reply"].startswith(NONE_OPEN_PT), "no channel profile: the project's language"


def test_vacuity_a_say_that_opens_no_scope_answers_a_page_line_in_the_project_s_language(world, monkeypatch):
    page_profiles(world, page="page-en")
    monkeypatch.setattr(ops_say, "_sentences", lambda ctx, channel: phrases.scope(None))
    assert ops.say(world["path"], "status", channel="page")["reply"].startswith(NONE_OPEN_PT), "the planted result: the opening in `say` is what the page tests above read"


def test_the_stored_reply_of_a_page_line_is_the_one_that_was_said(world):
    page_profiles(world, page="page-en")
    said = ops.say(world["path"], "status", channel="page")["reply"]
    ctx = ops_core.context(world["path"])
    stored = [m["text"] for m in ctx["store"].messages_list(ctx["conn"], ops.CONVERSATION, limit=50) if m["role"] == "assistant"]
    assert stored and stored[-1] == said and said.startswith(NONE_OPEN_EN)


# --- 7. the artifacts keep the one source --------------------------------------------------------------------------------------------------------


def test_the_language_of_an_artifact_never_sees_the_key(world):
    plain = {**PROF, "asker": {"groups": PROF["asker"]}}
    accept(world["path"], language="pt-BR", policies=plain, messaging={"senders": WORLD_SENDERS})
    before = ops_core.context(world["path"])["cfg"]
    accept_world(world, sentence_language="en")
    page_profiles(world, page="page-en")
    after = ops_core.context(world["path"])["cfg"]
    assert any("sentence_language" in record for record in after["policies"].values()) and after["language"] == before["language"] == "pt-BR"
    for cfg in (before, after):
        assert artifact_facts(cfg) == ARTIFACT_FACTS
    with phrases.scope("en"):      # nor a scope: the language of an artifact is the request's or the key, whatever sentences are being said
        assert phrases.tag(after) == "en" and artifact_facts(after) == ARTIFACT_FACTS


def artifact_facts(cfg):
    """What decides the language of a deliverable for this configuration: the order, the run's paragraph, the router's paragraph and the plan's line."""
    return (language.effective(None, cfg["language"]), language.line(None, cfg["language"]), language.router_line(None, cfg["language"]), language.plan_line([None, None], cfg["language"]))


ARTIFACT_FACTS = (("pt-BR", False), language.PROJECT_LINE.format(tag="pt-BR"), language.ROUTER_LINE.format(tag="pt-BR"), "Language: pt-BR")


def test_vacuity_a_language_rule_that_read_the_key_would_change_the_artifact_and_the_test_above_would_fail(monkeypatch):
    monkeypatch.setattr(language, "effective", lambda requested, key: ("en", False))      # the planted result: the artifact follows the sentence language
    assert artifact_facts({"language": "pt-BR"}) != ARTIFACT_FACTS


READERS = ("sentence_language", "sentence_override", "sentence_tag", "sentence_name", "sentences_for", "_sentences")
EXPECTED_READERS = {"phrases.py", "project_config.py", "messaging_bridge.py", "messaging_remind.py", "ops_say.py"}


def readers(folder: Path) -> set:
    return {p.name for p in sorted(folder.glob("*.py")) if any(re.search(rf"\b{word}\b", p.read_text(encoding="utf-8")) for word in READERS)}


def test_only_the_five_files_of_the_sentence_language_read_it():
    """Probe 1 of the package: the key reaches no run, no plan line, no router prompt and no artifact's language. The files that mention it or the functions that read it are exactly these;
    `language.py`, the run's prompt builders and the composers are not among them."""
    assert readers(RUNTIME) == EXPECTED_READERS
    assert "sentence_language" not in (RUNTIME / "language.py").read_text(encoding="utf-8")


def test_vacuity_the_scan_sees_a_read_planted_in_the_artifacts_language(tmp_path):
    copy = tmp_path / "runtime"
    copy.mkdir()
    for path in RUNTIME.glob("*.py"):
        shutil.copy(path, copy / path.name)
    assert readers(copy) == EXPECTED_READERS
    with (copy / "language.py").open("a", encoding="utf-8") as handle:
        handle.write('\n\ndef planted(cfg):\n    return cfg["policies"]["p"]["sentence_language"]\n')
    assert readers(copy) == EXPECTED_READERS | {"language.py"}


# --- 8. the vocabulary of the entry replay package ------------------------------------------------------------------------------------------------


def row(**changes):
    base = {"id": "tt-2.probe.01", "channel": "messaging", "platform": "buttons", "sender": "owner", "prestate": "two_languages", "text": "oi", "reply_to": None, "forwarded": False,
            "kind": "text", "action": None}
    return {**base, **changes}


def package_folder(root, name, rows):
    folder = root / name / "entry_ext"
    folder.mkdir(parents=True)
    (folder / "tt-2.scenarios.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    return folder


def test_the_recorded_package_is_well_formed_and_the_two_new_names_are_used_where_they_belong():
    assert ek.ext_problems() == []
    assert ek.check_scenario(row()) == [] and ek.check_scenario(row(sender="asker_en")) == []
    assert ek.check_scenario(row(sender="asker_en", prestate="none")) != [], "the sender has no other pre-state"
    assert ek.check_scenario(row(channel="page")) != [] and ek.check_scenario(row(sender="reader")) != [] and ek.check_scenario(row(platform="email")) != []


def test_a_package_row_that_names_an_unknown_pre_state_or_sender_is_still_refused(tmp_path):
    assert ek.ext_problems(package_folder(tmp_path, "good", [row()])) == []
    for name, changes in (("state", {"prestate": "nowhere"}), ("sender", {"sender": "stranger"}), ("misplaced", {"sender": "asker_en", "prestate": "none"})):
        found = ek.ext_problems(package_folder(tmp_path, name, [row(**changes)]))
        assert found and "tt-2.probe.01" in found[0], name


def test_vacuity_a_check_without_the_tt2_rule_lets_the_misplaced_sender_through(monkeypatch):
    assert ek.check_scenario(row(sender="asker_en", prestate="none")) != []
    monkeypatch.setattr(ek, "vocabulary_problems", lambda scenario: [])
    assert ek.check_scenario(row(sender="asker_en", prestate="none")) == [], "the planted result: the rule of the block is what refuses it"
