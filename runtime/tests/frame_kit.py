"""What a test needs to ask one kind of the frame about one line (package S41-8): the `claims` that `Bridge.plan_line`, `word_line`, `research_stop_line` and `revise_line` were, called the way the
dispatcher calls a kind (`runtime/messaging_turn.py`: `applies`, then `take`). Not a test file."""
from __future__ import annotations

import standin_tree as st

messaging_turn = st.load("messaging_turn")


def turn_of(bridge, update: dict, intent: dict, kind: str, project: dict, listed: list, chat: str, sender: str = "") -> object:
    """The turn the dispatcher would hold for this update once the envelope rows have read it."""
    turn = messaging_turn.Turn(update=update, sender=sender or str(update.get("sender")), chat=chat, listed=listed, project=project, bridge=bridge)
    turn.intent, turn.kind, turn.replied = intent, kind, update.get("reply_to")
    return turn


def claims(bridge, name: str, update: dict, intent: dict, kind: str, project: dict, listed: list, chat: str, sender: str = "") -> bool:
    """Whether the kind `name` reads the line and takes it (the call is made when it does), as the frame asks it."""
    turn = turn_of(bridge, update, intent, kind, project, listed, chat, sender)
    entry = messaging_turn.KINDS[name]
    found = entry.applies(bridge, turn)
    return bool(found and entry.take(bridge, turn, found))
