"""WP-7.1, from WP-7.3b on: the ported vote job is scripts/vote_job.py with a closed list of replacements.

runtime/handlers/social_vote_job.py was made with cp from scripts/vote_job.py and edited only as REPLACEMENTS
says. While the old script stays (until WP-7.5), this test keeps the two from drifting: a repair made to the
source must be made in the port too, and the other way round. Only that file is compared from WP-7.3b on:
social.py and social_vote.py now differ from scripts/runtime.py and scripts/runtime_vote.py by design (the
agent's run is a contained run, with the task text of the measured cases), so their entries are gone. The test
is retired at WP-7.6. The last test is about the handler's own command, not about parity: it checks that the
verbs the handler lists are the ones its parser takes.
"""
import ast
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HANDLERS = REPO / "runtime" / "handlers"
sys.path.insert(0, str(HANDLERS))

# source -> (ported file, [(find, replace, times in the source)])
REPLACEMENTS = {
    "scripts/vote_job.py": ("runtime/handlers/social_vote_job.py", [
        ("python3 vote_job.py", "python3 social_vote_job.py", 1),
    ]),
}
# No comment or docstring line was reworded: the lines that still name the old paths stay as they are.
REWORDED_LINES = []


def read(rel):
    return (REPO / rel).read_text(encoding="utf-8")


def test_each_ported_file_is_its_source_with_only_the_listed_replacements():
    for source, (port, replacements) in REPLACEMENTS.items():
        text = read(source)
        for find, replace, times in replacements:
            text = text.replace(find, replace)
        ported = read(port)
        assert ported == text, f"{port} is not {source} with the listed replacements"
    assert REWORDED_LINES == []


def test_every_listed_replacement_occurs_the_stated_number_of_times():
    for source, (_, replacements) in REPLACEMENTS.items():
        text = read(source)
        for find, _, times in replacements:
            assert text.count(find) == times, f"{source}: {find!r} occurs {text.count(find)} times, not {times}"


def test_the_handler_lists_the_verbs_its_command_takes():
    import social
    source = read("runtime/handlers/social.py")
    choices = re.search(r'p\.add_argument\("verb", choices=(\[.*?\])\)', source).group(1)
    assert list(social.VERBS) == ast.literal_eval(choices)  # a literal list of words, read from our own file
    assert list(social.VERBS) == ["tick", "pin", "add-comment", "status", "inbox", "approve", "reject", "replay"]
