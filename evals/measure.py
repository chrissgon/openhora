#!/usr/bin/env python3
"""What decides what a run measures, in one module (item B10 of docs/architecture/final-plan-2026-10-02.md
(removed on 2026-10-14; `git show d3e60770:docs/architecture/final-plan-2026-10-02.md`)).

The eval runner (evals/eval_run.py) and the status script (evals/eval_status.py) import it; it imports
neither. It holds:

  - the facts block the grader is given (facts_block), the commands that read the case's repository for it
    (VCS_SCRIPT) and the length they are cut at (VCS_LIMIT);
  - what the grader is shown of a file a run produced (shown, binary_stub, NOT_SHOWN, FILE_LIMIT);
  - the grading prompt (assertion_text, grading_prompt) and the reading of the grader's answer
    (read_grading, which refuses a verdict that disagrees with what its own evidence concludes: conclusion),
    with the number of times a refused answer is asked for again (GRADING_RETRIES);
  - which failed verdicts of a with-skill run are graded once more, and which of them the second grading
    confirms (guard_positions, failed_guards, confirmed_guards);
  - the early-end rule (early_end), which decides which runs are made again instead of scored;
  - the replacement of the passed variables' values by a marker (redaction_values, replace_values);
  - the scoring of a run (score, grading_summary) and the unrounded comparisons of the gate (at_threshold,
    within_tolerance, gate_passes).

The constants that no other file owns (the file limit, the early-end phrase lists and the others above) are
data in evals/measurement.json, read once when the module loads. The number of runs, the timeout and the
retries of an event have their home in the gate file (evals/eval-gate.json); what an adapter's harness prints
on a refusal or an exhausted account, in that adapter's eval.json.

This file and evals/measurement.json are in the measurement fingerprint (eval_status.py, FINGERPRINT_FILES):
a change to either is committed as one of the three kinds of the reliability model's section 8
(`python3 evals/eval_status.py measurement --kind grader|execution|infrastructure`). The rest of the runner
(arguments, concurrency, the shared lock, resuming, the reports) is infrastructure and may change freely.

Standard library only. It has no command line of its own: `--help` prints this text.
"""
import json
import os
import re
import secrets
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CONSTANTS = os.path.join(HERE, "measurement.json")


def _constants(path=CONSTANTS):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    early = data["early_end"]
    return data, early


_DATA, _EARLY = _constants()

# The grader sees each produced file up to this many characters. Plans and reports run to several thousand; at
# 3,000 an early run graded the end of a plan as missing, and at 20,000 an assertion about every source of a
# long research artifact failed as unproven.
FILE_LIMIT = _DATA["file_limit"]
VCS_LIMIT = _DATA["vcs_limit"]  # characters of the version-control facts shown to the grader
GRADING_RETRIES = _DATA["grading_retries"]  # a refused or unparsable grading is made again up to this many times
# A passed variable whose value is shorter than this is not replaced: it is a switch, not a credential, and
# replacing "1" or "true" wherever it occurs would rewrite what a run produced.
REDACT_MIN = _DATA["redact_min"]

# An early end: the model ended its turn before doing the work, with no error (eval_run.py, "Early ends").
# Markup of a tool call or a control block printed as text; it counts only at the start of a line, so a reply
# that quotes such markup inline to the user is left alone. Seen from a floor model: <skill_tool>, and loops
# of <system-reminder> blocks it wrote itself; the "tool" entries are the models' own tool-call tokens and the
# "dsml" ones the call markup of DeepSeek's models (a loop of it, fullwidth bar included, was graded once because
# the run had written a file).
EARLY_END_MARKUP = tuple(_EARLY["markup"])
# A loop of raw tool-call syntax is an early end even when a file was written (item T27). The lines of the reply,
# outside fenced code blocks and indented code, that are markup (a line with a tag of EARLY_END_MARKUP or
# "<parameter" in it, or any line inside a call block, from an opening call tag to its closing one) are at least
# "min_lines" and at least "share" of the non-empty lines there, or of their characters. 20 and 0.5 are
# measurement constants: a reply that shows a tool call quotes a few lines, inside a fence, and a loop is nearly
# all markup, the content of its write calls included. Read over the 1,903 replies of the maintainer's local eval
# workspace (2026-10), the rule flags two, each a real loop of <system-reminder> blocks (floor model), and none of the others.
EARLY_END_COLLAPSE_MIN_LINES = _EARLY["collapse"]["min_lines"]
EARLY_END_COLLAPSE_SHARE = _EARLY["collapse"]["share"]
COLLAPSE_EXTRA = ("<parameter",)  # a parameter of a call, beside the entries of EARLY_END_MARKUP
COLLAPSE_BLOCKS = ("function_calls", "tool_call", "invoke", "skill_tool", "system-reminder")  # the tags that open a call block
COLLAPSE_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
COLLAPSE_CODE_SPAN_RE = re.compile(r"`[^`]*`")
COLLAPSE_RESCANS = 8  # fences and blocks left open at the end are ignored one by one; past this many, they are off from the last one on
COLLAPSE_TAG_SPAN = 200  # a tag is read to its ">" within this many characters, so a long line is read in linear time


def _collapse_tag_re():
    """A tag of the markup entries, anywhere in a line, opening or closing. A name made of letters ends where the
    tag does (so "<parameters>", "<parameterDefinition>" and "<tool_calls>" are not "<parameter" and "<tool_call");
    an entry that is a special-token prefix ("<|tool", "<｜dsml") has no such end, its name goes on. The tags are
    matched in any case, except "parameter": the syntax of a call has it in lower case, and another format's
    <Parameter name=... value=.../> is not a call."""
    words, tokens = [], []
    for entry in EARLY_END_MARKUP + COLLAPSE_EXTRA:
        body = entry[1:].lower()
        piece = "(?-i:" + re.escape(body) + ")" if body == "parameter" else re.escape(body)
        (tokens if body[:1] in ("|", "｜") else words).append(piece)
    parts = []
    if words:
        parts.append("(?:" + "|".join(words) + ")(?![A-Za-z0-9_-])")
    if tokens:
        parts.append("(?:" + "|".join(tokens) + ")")
    return re.compile(r"<(/?)(?:" + "|".join(parts) + ")", re.I)


COLLAPSE_TAG_RE = _collapse_tag_re()


def _collapse_tags(line):
    """(whether the line holds a tag, [+1 for each call block it opens, -1 for each it closes]). A block opens only
    when its tag starts the line or follows only other tags, so a sentence that mentions a tag ("Each call is printed
    as <invoke name=...> by the old format.") opens nothing; a closing tag always closes. Linear in the line."""
    clean = COLLAPSE_CODE_SPAN_RE.sub("", line)
    found, moves = False, []
    chain, previous = True, 0  # chain: nothing but tags and spaces precede this tag on the line
    for m in COLLAPSE_TAG_RE.finditer(clean):
        found = True
        chain = chain and not clean[previous:m.start()].strip()
        end = clean.find(">", m.start(), m.start() + COLLAPSE_TAG_SPAN)
        span = clean[m.start():end + 1] if end >= 0 else clean[m.start():m.start() + COLLAPSE_TAG_SPAN]
        previous = end + 1 if end >= 0 else m.end()
        name = re.split(r"[\s>]", span.lower())[0]  # the tag's name, without its attributes
        block = any(word in name for word in COLLAPSE_BLOCKS)
        if re.search(r"[\u2581_]end", name) or (m.group(1) and block):
            moves.append(-1)
        elif chain and not m.group(1) and (re.search(r"[\u2581_]begin", name) or (block and not span.endswith("/>"))):
            moves.append(1)
    return found, moves


def _collapse_scan(lines, ignored, off_from, ignored_blocks, blocks_off):
    """(lines counted, markup lines, characters counted, markup characters, the index of a fence still open at the
    end or None, the index of the line that opened the outermost call block still open at the end or None)."""
    stack, fence, opened = [], None, None
    counted = markup = chars = markup_chars = 0
    for i, raw in enumerate(lines):
        line = raw.strip()
        if not line:
            continue
        if fence is not None:
            m = COLLAPSE_FENCE_RE.match(raw)
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= fence[1] and not raw.strip().strip(fence[0]):
                fence = None
            continue
        if not stack:
            m = COLLAPSE_FENCE_RE.match(raw)
            if m and i not in ignored and (off_from is None or i < off_from):
                fence, opened = (m.group(1)[0], len(m.group(1))), i
                continue
            if raw.startswith(("    ", "\t")):
                continue  # indented code
        counted += 1
        chars += len(line)
        inside = bool(stack)
        found, moves = _collapse_tags(line)
        for move in moves:
            if move < 0:
                if stack:
                    stack.pop()
            elif i not in ignored_blocks and (blocks_off is None or i < blocks_off):
                stack.append(i)
        if inside or found:
            markup += 1
            markup_chars += len(line)
    return counted, markup, chars, markup_chars, (opened if fence is not None else None), (stack[0] if stack else None)


def collapse_loop(response):
    """"<n> of <m> lines" when the reply is a loop of raw tool-call syntax, else None. It counts the non-empty
    lines outside fenced code blocks (opened by three or more backticks or tildes, closed by as many or more of the
    same; a fence still open at the end is not one, and the lines after it are counted) and outside indented code (four
    spaces or a tab), where a line is markup when it holds a tag of EARLY_END_MARKUP or "<parameter", closing or
    opening, anywhere in it, outside an inline code span, or when it lies inside a call block (from an opening call tag
    that starts its line, or follows only tags, to its closing one: a write call's content is markup too; a block
    whose closing tag never comes is not one, and the lines after it are counted; a fence inside a block does not
    toggle). A loop: at least EARLY_END_COLLAPSE_MIN_LINES markup lines and at least EARLY_END_COLLAPSE_SHARE of the
    counted lines or of their characters. By design a loop written on one line, with no newline, is one line, under the
    minimum."""
    lines = response.splitlines()
    ignored, off_from, ignored_blocks, blocks_off = set(), None, set(), None
    for attempt in range(2 * COLLAPSE_RESCANS + 3):
        counted, markup, chars, markup_chars, fence, block = _collapse_scan(lines, ignored, off_from, ignored_blocks, blocks_off)
        if fence is None and block is None:
            break
        late = attempt >= COLLAPSE_RESCANS
        if fence is not None:
            if late:
                off_from = fence
            else:
                ignored.add(fence)
        elif late:
            blocks_off = block
        else:
            ignored_blocks.add(block)
    if markup >= EARLY_END_COLLAPSE_MIN_LINES and (markup >= EARLY_END_COLLAPSE_SHARE * counted
                                                   or markup_chars >= EARLY_END_COLLAPSE_SHARE * chars):
        return f"{markup} of {counted} lines"
    return None


# How a last line announces a next action instead of ending the turn's work. Matched, in lower case, at the
# start of a sentence of the last line ("Let me update the file:", "Now I'll write the spec:").
# Not a bare "i'll": "I'll also need to know where the code should go" ends a reply that states a blocker.
EARLY_END_ANNOUNCE = tuple(_EARLY["announce"])
# A last line with one of these waits for the user ("Let me know which you prefer", "I'll wait for the brief",
# "If you approve it, I'll run it"): never an early end.
EARLY_END_NOT = tuple(_EARLY["not"])
# A reply longer than EARLY_END_BLOCKER_MIN characters that holds one of these states a blocker or asks for an
# input in the imperative ("I can't read the ticket ... paste it"): a stop, never an early end. The length
# keeps a one-line "Now I need the format. Let me update the file:" an early end.
EARLY_END_BLOCKER = tuple(_EARLY["blocker"])
EARLY_END_BLOCKER_MIN = _EARLY["blocker_min"]
# An announcement is an early end in a short reply, or when the last line ends as one that was cut (":", "...").
EARLY_END_SHORT = _EARLY["short"]
PSEUDO_TAG_LINE_RE = re.compile(r"^<([A-Za-z_-]+)>.*</\1>$")
# A trailing line that is only a tag, such as a tool call the model printed as text and never ran
# (<read filePath="...">, </read>): skipped to reach the last line of prose.
TAG_ONLY_LINE_RE = re.compile(r"^</?[A-Za-z_][\w-]*(\s[^<>]*)?/?>$")


def early_end(response, changed):
    """Why a run that exited 0 is an early end, or None. Conservative: a run that wrote a file, a reply that
    asks the user a question and a reply that states a blocker are never one, with one exception that a written
    file does not excuse: a loop of raw tool-call syntax (collapse_loop)."""
    loop = collapse_loop(response)
    if loop:
        return f"a loop of raw tool-call syntax printed as text ({loop})"
    if changed:
        return None
    lines = [line.strip() for line in response.splitlines() if line.strip()]
    if not lines:
        return "empty response and no file written"
    for line in lines:
        hit = next((m for m in EARLY_END_MARKUP if line.lower().startswith(m)), None)
        if hit:
            return f"tool or control markup printed as text ({hit}) and no file written"
    if "?" in response:
        return None
    while len(lines) > 1 and (PSEUDO_TAG_LINE_RE.match(lines[-1]) or TAG_ONLY_LINE_RE.match(lines[-1])):
        lines.pop()  # a trailing note the model wrapped in a tag of its own
    low = response.lower().replace("’", "'")
    if len(response) > EARLY_END_BLOCKER_MIN and any(phrase in low for phrase in EARLY_END_BLOCKER):
        return None  # states a blocker or asks for an input
    last = lines[-1].lower().replace("’", "'")
    if any(phrase in last for phrase in EARLY_END_NOT):
        return None
    # The FINAL sentence of the last line, not any sentence of it: "I'll fetch it myself. I'll also need to
    # know which project it belongs to." ends on a request.
    final = re.split(r"(?<=[.!:;])\s+", last)[-1].lstrip("-*>#_`0123456789.) ")
    if final.startswith(EARLY_END_ANNOUNCE) and (len(response) <= EARLY_END_SHORT or lines[-1].endswith((":", "...", "…"))):
        return "the reply ends by announcing a next action, no question was asked and no file written"
    return None


# --- the values of the passed variables, replaced by a marker (item B6a) --------------------------------

def redaction_values(names, env=None):
    """[(value, marker)] for the variables passed into a run, longest value first: what replace_values() looks
    for. The marker names the variable, never its value."""
    env = os.environ if env is None else env
    found = {}
    for name in dict.fromkeys(names):
        value = env.get(name) or ""
        if len(value) >= REDACT_MIN:
            found.setdefault(value, f"[redacted:{name}]")
    return sorted(found.items(), key=lambda pair: len(pair[0]), reverse=True)


def replace_values(data, values):
    """Replace each exact value in data (bytes or text) by its marker. Returns (the new data, the number of
    replacements). Exact values only, no pattern of what a credential looks like: a planted fake secret in a
    fixture is not one of the passed values and stays, so an assertion that a reply does not repeat it still
    measures the reply."""
    count = 0
    for value, marker in values:
        if isinstance(data, bytes):
            value, marker = value.encode("utf-8"), marker.encode("utf-8")
        hits = data.count(value)
        if hits:
            data, count = data.replace(value, marker), count + hits
    return data, count


# --- what the grader is given -----------------------------------------------------------------------

# What the harness asks the case's repository after a run, in the case folder, in a container with no
# network. One literal script: nothing of a case or of a run is put into it.
VCS_SCRIPT = """
if ! git rev-parse --git-dir >/dev/null 2>&1; then echo "(the case folder is not a repository)"; exit 0; fi
echo '$ git status --short'; git status --short 2>&1 | head -n 200
echo '$ git log --oneline -n 20 --all'; git log --oneline -n 20 --all 2>&1
echo '$ git branch -a'; git branch -a 2>&1 | head -n 100
for remote in $(git remote 2>/dev/null); do
  echo "\\$ git ls-remote --heads $remote"; git ls-remote --heads "$remote" 2>&1 | head -n 50
done
"""
NOT_SHOWN = "[not shown: a symbolic link, a special file or a path outside the case folder; the harness does not read it]"


def cut_vcs(text):
    """The version-control facts as the grader is given them: cut at VCS_LIMIT characters."""
    text = (text or "").strip() or "(no output)"
    if len(text) > VCS_LIMIT:
        text = text[:VCS_LIMIT] + f"\n[... cut at {VCS_LIMIT} characters ...]"
    return text


def facts_block(delta, vcs):
    """The facts the grader is given: what the harness measured, never what the model said."""
    listing = lambda paths: "\n".join(f"- {p.replace(os.sep, '/')}" for p in paths) or "- (none)"
    return (f"created:\n{listing(delta['created'])}\n"
            f"modified:\n{listing(delta['modified'])}\n"
            f"deleted:\n{listing(delta['deleted'])}\n"
            f"unchanged inputs:\n{listing(delta['unchanged'])}\n"
            "version control (commands the harness ran in the case folder after the run):\n"
            f"{vcs if vcs is not None else '(not read)'}")


def _read_text(path, limit):
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            return f.read(limit)
    except OSError:
        return ""


def binary_stub(path):
    """What the grader is told about a file that is not text: its kind, its size and, for a PNG, its
    dimensions. None when the file reads as text. Bytes pasted as text told the grader nothing, and a
    few images made the grading prompt too long to pass to a harness."""
    try:
        with open(path, "rb") as f:
            head = f.read(4096)
        size = os.path.getsize(path)
    except OSError:
        return None
    if head.startswith(b"\x89PNG\r\n\x1a\n") and len(head) >= 24:
        width, height = int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")
        return f"[binary file: PNG image, {width}x{height} pixels, {size} bytes; its content is not shown]"
    kinds = ((b"\xff\xd8\xff", "JPEG image"), (b"GIF8", "GIF image"), (b"%PDF", "PDF document"), (b"PK\x03\x04", "zip archive"))
    for magic, kind in kinds:
        if head.startswith(magic):
            return f"[binary file: {kind}, {size} bytes; its content is not shown]"
    if b"\0" in head:
        return f"[binary file, {size} bytes; its content is not shown]"
    return None


def shown(path):
    """What the grader is shown of one file: a line for a binary file, the text up to FILE_LIMIT characters."""
    stub = binary_stub(path)
    if stub:
        return stub
    text = _read_text(path, FILE_LIMIT + 1)
    if len(text) > FILE_LIMIT:
        return text[:FILE_LIMIT] + f"\n[... truncated at {FILE_LIMIT} characters: the file continues ...]"
    return text


def assertion_text(assertion):
    """The text of an assertion of a case file: the assertion itself, or the "text" of one written as an object
    with tags. None when it is neither. The tags (guard, format) are for the status and the validator: the
    grader is given the text and never the tags."""
    if isinstance(assertion, str):
        return assertion
    if isinstance(assertion, dict) and isinstance(assertion.get("text"), str):
        return assertion["text"]
    return None


def grading_prompt(tpl, case, response, facts="(none)", files_blob="(none)", inputs_blob="(none)"):
    """Fill the grading template in one pass, fencing what the model wrote or left with a marker it cannot predict.

    One pass: a response that contains "{files}" or "{assertions}" stays text instead of being replaced.
    The assertions are given as their text, numbered in the case's order; their tags are never shown.
    """
    marker = secrets.token_hex(8)
    while any(marker in text for text in (response, facts, files_blob, inputs_blob)):
        marker = secrets.token_hex(8)
    values = {"prompt": case["prompt"], "response": response, "facts": facts, "files": files_blob, "inputs": inputs_blob,
              "marker": marker,
              "assertions": "\n".join(f"{i + 1}. {assertion_text(a)}" for i, a in enumerate(case.get("assertions") or []))}
    return re.sub(r"\{(prompt|response|facts|files|inputs|assertions|marker)\}", lambda m: values[m.group(1)], tpl)


# --- a verdict that disagrees with its own evidence ----------------------------------------------------
# In the smoke pass of phase D (docs/architecture/phase-d-smoke-2026-10-03.md, removed on 2026-10-14;
# `git show d3e60770:docs/architecture/phase-d-smoke-2026-10-03.md`) the grader wrote "passed" before
# its evidence, reasoned inside the evidence, and in six gradings ended it on the other verdict ("..., so this
# should pass", "..., so this part holds") while "passed" stayed false; in three more it wrote a correction after
# the array, which was refused. The template now asks for the evidence first and a last sentence that is
# "Passes." or "Fails: ...". conclusion() reads what the evidence concludes, and read_grading() refuses an answer
# in which a verdict disagrees with it, so that the grading is made again.
#
# Only the grader's own words are read: quoted passages (the output it cites) are removed first, and only the
# final clause of the last sentence counts, with a subject that is the assertion or a part of it, so "the file
# still holds conflict markers" or "the first part holds, but the second does not" conclude nothing.
QUOTED_RE = re.compile(r"\"[^\"]*\"|“[^”]*”|‘[^’]*’|`[^`]*`|(?<!\w)'[^']*'(?!\w)")
SENTENCE_END_RE = re.compile(r"(?<=[.!?])\s+")
CLAUSE_BREAK_RE = re.compile(r"[,;:()]|\s[-–—]\s|\b(?:but|however|yet|although|though|except|whereas)\b", re.I)
CONCLUSION_SUBJECT = (r"(?:this|it|the (?:compound |whole )?assertion"
                      r"|(?:this|that|the first|the second|the third|the last|each|every|either) part|both parts"
                      r"|all (?:two |three |four )?parts)")
# Between the subject and the verb, at most one adverb of this list ("the assertion therefore fails").
CONCLUSION_ADVERB = r"(?:(?:also|therefore|thus|still|clearly|literally|then|so|indeed|now|again|only)\s+)?"
# "passes" and "fails" may be followed by a few words ("..., so the assertion fails on its literal wording");
# "holds", "is met" and the like end the clause, since "it holds the table" is about the output.
CLAUSE_END = r"[\s.!?]*$"
CONCLUSION_FAIL_RE = re.compile(
    rf"\b{CONCLUSION_SUBJECT}\s+{CONCLUSION_ADVERB}(?:(?:fails|failed|is failed|(?:should|would|does|must|will) fail"
    r"|(?:does not|doesn't|cannot|can't|should not|shouldn't|would not|wouldn't|will not|won't) pass)\b"
    rf"|(?:(?:does not|doesn't|cannot|can't|should not|would not) hold|is not (?:met|satisfied|shown)){CLAUSE_END})", re.I)
CONCLUSION_PASS_RE = re.compile(
    rf"\b{CONCLUSION_SUBJECT}\s+{CONCLUSION_ADVERB}(?:(?:passes|(?:should|would|does|must|will|can) pass)\b"
    rf"|(?:holds|is met|is satisfied|(?:should|would|does|must|will|can) hold){CLAUSE_END})", re.I)
CONCLUSION_WORD_RE = re.compile(r"^(passes|fails)\b", re.I)


def conclusion(evidence):
    """What a verdict's evidence concludes in the grader's own words: "pass", "fail", or None when its last
    sentence states no conclusion. The template's form is a last sentence "Passes." or "Fails: <why>."; an
    evidence that ends "..., so this should pass" or "..., so the assertion fails" concludes as well."""
    text = QUOTED_RE.sub(" ", str(evidence or "")).strip()
    sentences = [s.strip() for s in SENTENCE_END_RE.split(text) if s.strip()]
    if not sentences:
        return None
    last = sentences[-1].strip(" *_-")
    word = CONCLUSION_WORD_RE.match(last)
    if word:
        return "pass" if word.group(1).lower() == "passes" else "fail"
    clauses = [c.strip() for c in CLAUSE_BREAK_RE.split(last) if c and c.strip(" .!?")]
    final = clauses[-1] if clauses else ""
    if CONCLUSION_FAIL_RE.search(final):
        return "fail"
    if CONCLUSION_PASS_RE.search(final):
        return "pass"
    return None


def read_grading(raw, count):
    """The grader's verdicts, read by position: (results, None), or (None, why the answer is refused).

    Refused: no JSON array, an array whose length is not the number of assertions (one grading of the first
    round returned 6 results for 5 assertions and was scored over 6), an item that is not an object with a
    true or false "passed", and an item whose evidence concludes the other verdict (conclusion()). The
    assertion's text is not asked for and not read."""
    m = re.search(r"\[\s*\{.*\}\s*\]", raw, re.S)
    if not m:
        return None, "no JSON array in the answer"
    try:
        items = json.loads(m.group(0))
    except ValueError as e:
        return None, f"the array is not valid JSON ({e})"
    if not isinstance(items, list) or len(items) != count:
        return None, f"{len(items) if isinstance(items, list) else 'no'} results for {count} assertions"
    if not all(isinstance(item, dict) and isinstance(item.get("passed"), bool) for item in items):
        return None, "a result is not an object with \"passed\": true or false"
    for i, item in enumerate(items, 1):
        said = conclusion(item.get("evidence"))
        if said is not None and said != ("pass" if item["passed"] else "fail"):
            return None, (f"result {i} is \"passed\": {'true' if item['passed'] else 'false'}, "
                          f"but its evidence concludes that the assertion {'passes' if said == 'pass' else 'fails'}")
    return [{"id": i + 1, "passed": item["passed"], "evidence": str(item.get("evidence", ""))}
            for i, item in enumerate(items)], None


# --- guard assertions: a failed verdict is graded once more before it counts (the model's section 4) ------

def assertion_tags(assertion):
    """The tags of an assertion: those of an object, none for a text."""
    return [t for t in assertion.get("tags") or [] if isinstance(t, str)] if isinstance(assertion, dict) else []


def guard_positions(case):
    """The positions (from 1, in the case's order) of the assertions tagged guard or guard:<effect>."""
    return [i for i, a in enumerate(case.get("assertions") or [], 1)
            if any(t == "guard" or t.startswith("guard:") for t in assertion_tags(a))]


def failed_guards(case, results):
    """The guard positions the verdicts (results: the grader's, by position) failed: a with-skill run whose
    grading fails one of them is graded once more."""
    return [p for p in guard_positions(case) if p <= len(results) and not results[p - 1]["passed"]]


def confirmed_guards(failed, second):
    """Of the guard positions the first grading failed, those the second grading of the same reply failed too:
    the run line's "guard_failed". The first grading's results and score stand: the second raises no mean."""
    return [p for p in failed if p <= len(second) and not second[p - 1]["passed"]]


# --- the score of a run and the comparisons of the gate --------------------------------------------------

def score(results):
    """The score of a graded run: the share of its assertions that passed (results: a list of 0 and 1, or of
    verdicts with "passed"). 0 for no assertion."""
    passed = [1 if (r.get("passed") if isinstance(r, dict) else r) else 0 for r in results]
    return sum(passed) / len(passed) if passed else 0.0


def grading_summary(results):
    passed = sum(1 for r in results if r["passed"])
    return {"passed": passed, "failed": len(results) - passed, "total": len(results), "pass_rate": score(results)}


# What a sum of floating-point scores loses, and nothing more: six runs at 0.8 average 0.7999999999999999, which
# is 0.8. Far below any difference a score can make (a run of 100 assertions moves a mean of 1,000 runs by 1e-5).
FLOAT_SLACK = 1e-9


def at_threshold(mean, threshold):
    """The first condition of the gate, unrounded: a mean of 0.7996 is below a threshold of 0.8, and a mean that
    is the threshold but for the arithmetic of floats (FLOAT_SLACK) is at it."""
    return mean >= threshold - FLOAT_SLACK


def within_tolerance(with_mean, baseline_mean, tolerance):
    """The second condition of the gate, unrounded: the mean with the skill is not below the baseline's mean by
    more than the tolerance (FLOAT_SLACK aside). True when there is no baseline mean."""
    return baseline_mean is None or with_mean >= baseline_mean - tolerance - FLOAT_SLACK


def gate_passes(with_mean, baseline_mean, threshold, tolerance):
    """The gate of the reliability model's section 2, on unrounded means."""
    return at_threshold(with_mean, threshold) and within_tolerance(with_mean, baseline_mean, tolerance)


if __name__ == "__main__":
    print(__doc__)
    sys.exit(0 if sys.argv[1:] in ([], ["--help"], ["-h"]) else 2)
