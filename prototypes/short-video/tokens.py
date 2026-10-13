"""Text normalisation shared by the aligner, the retake detector and the cutter.

NFKC, casefold, apostrophes dropped, other punctuation to a space; tokens are compared fuzzily
(difflib ratio of at least 0.75 for words longer than three letters, otherwise equal).
"""
import difflib
import re
import unicodedata

SIM_FLOOR = 0.75    # token similarity below this is a plain mismatch


def norm_tokens(text):
    """NFKC, casefold, apostrophes dropped, other punctuation to a space; returns tokens."""
    t = unicodedata.normalize("NFKC", text).casefold()
    t = re.sub(r"['’]", "", t)
    t = re.sub(r"[^\w\s]|_", " ", t)
    return t.split()


def has_digit(tok):
    return any(c.isdigit() for c in tok)


_sim_cache = {}


def token_sim(a, b):
    if a == b:
        return 1.0
    key = (a, b)
    if key not in _sim_cache:
        r = difflib.SequenceMatcher(None, a, b).ratio()
        _sim_cache[key] = r if (r >= SIM_FLOOR and min(len(a), len(b)) > 3) else 0.0
    return _sim_cache[key]


def flatten_words(words, skip_dropped=True):
    """Transcript words -> flat token list with the word index of each token.

    A word flagged `dropped` (a retake the cutter removed) is left out, so a beat is never placed on it."""
    toks, widx = [], []
    for w in words:
        if skip_dropped and w.get("dropped"):
            continue
        for t in norm_tokens(w["text"]):
            toks.append(t)
            widx.append(w["i"])
    return toks, widx
