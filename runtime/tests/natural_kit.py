"""Helpers of the tests of natural requests (package NR-1). Not a test file.

A reminder asked in free text is made only after a "yes" to the reading that was shown (the maintainer's rule: nothing in the person's own words is made without being
shown first). A test that is about what a line MEANS says "yes" to the question and looks at what was made; a test about the question looks at the question.
"""
from __future__ import annotations


def made(natural, line, now, how="trigger"):
    """What `line` makes once the person says yes to the reading shown: the dict `{"when", "text", "reading"}`, or the question when the line asks something other than a
    confirmation or the kind (its time, a reading, its words, a routine's sentence). The confirmation is asked exactly once: a second question is returned as it is."""
    got = natural.understand(line, now, how)
    if "ask" in got and got["ask"]["need"] in ("confirm", "kind"):
        got = natural.complete(got["ask"], "yes", now)
    return got


def said_yes(ops, path, sender, said, how="trigger"):
    """`remind(said=...)` as the bridge calls it, followed by the "yes" that makes the reminder: the operation's answer when it made one, else the question."""
    first = ops.remind(path, channel="messaging", sender=sender, said=said, how=how)
    if "ask" in first and first["ask"]["need"] in ("confirm", "kind"):
        return ops.remind(path, channel="messaging", sender=sender, said="yes", how=how, draft=first["ask"])
    return first


def open_draft(day, chat):
    """The reminder question the chat has open: the bridge's own (a typed /remind) or the one the interpreter's carry-out left in the store of drafts (S41-11)."""
    import standin_tree as st
    mine = day.bridge.remind.drafts.get(chat)
    return mine or st.load("drafts").get("messaging", day.bridge.key(chat), "remind") or {}


def say_yes(day, chat, line, **fields):
    """The person writes `line` and, when the bridge answers with the reading to be confirmed (or the kind question that shows it), says yes. A line that asks anything
    else (its time, a reading, its words) is left asking."""
    day.say(chat, line, **fields)
    if open_draft(day, chat).get("need") in ("confirm", "kind"):
        day.say(chat, "yes")
