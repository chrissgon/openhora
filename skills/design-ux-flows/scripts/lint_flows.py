#!/usr/bin/env python3
"""Lint a UX flows document written from assets/flows-template.md against its PRD.

Usage: python3 lint_flows.py --file <flows.md> --prd <prd.md> [--phase P-n] [--report <lint.json>] [--json]

Prints JSON on stdout: ok, summary (the line a reply quotes), counts, errors. --report <path> also writes
the record of the evidence convention to that file (script, date, arguments, ok, summary, errors, counts),
so a reviewer can check the lint ran and what it checked. Usage errors, an unknown flag among them, go to
stderr with exit 2 and write no report.

Checks:
  - required sections are present; ids (IA, SCREEN, FLOW, ASSUMPTION, OPEN) are unique
  - every IA has Parent:, URL:, Filled by: and Source:
  - every SCREEN has Purpose:, Regions:, States:, Breakpoints: and Source:
  - screen-states: every SCREEN names at least one state called `empty` or `error` in States: (for a
    message such as an email or a notification, the error state is the delivery failure)
  - every FLOW has Actor: U-n, Trigger:, Steps:, End:, Failures:, Keyboard: and Source:, and its
    steps name at least one SCREEN- that exists
  - every SCREEN is named by at least one FLOW
  - every must/should feature of the PRD (in the given phase, when --phase is set) has a Coverage line
  - every Coverage line names FLOW-/SCREEN- ids that exist, or "no screen:" with a reason
  - spec-pending-line: the header has a `- Spec pending:` line whose value is `none` or a list of F-n ids
  - spec-pending-steps: every step of a FLOW whose Source: names a listed F-n carries the words `spec pending`
  - every OPEN has Blocks: and Recommended:

Exit codes: 0 ok, 1 problems found, 2 usage error.
"""
import datetime
import json
import re
import sys

SECTIONS = ["## Summary", "## Sources", "## Information architecture", "## Screens", "## Flows", "## Coverage",
            "## Assumptions", "## Open questions", "## Readiness"]
STATES_RE = re.compile(r"States:\s*(.*?)(?=\s*(?:Purpose|Regions|Breakpoints|Source):|$)")
ID_RE = re.compile(r"^\s*-\s*((?:IA|SCREEN|FLOW|ASSUMPTION|OPEN|F)-\d+)\s*:", re.M)


def blocks(text, prefixes):
    out, cur = {}, None
    for ln in text.splitlines():
        m = ID_RE.match(ln)
        if m and m.group(1).startswith(prefixes):
            cur = m.group(1)
            out[cur] = [ln]
        elif cur and ln.startswith("  "):
            out[cur].append(ln)
        else:
            cur = None
    return {k: " ".join(v) for k, v in out.items()}


def section(text, title):
    m = re.search(r"^## " + re.escape(title) + r"\s*$", text, re.M)
    if not m:
        return ""
    rest = text[m.end():]
    n = re.search(r"^## ", rest, re.M)
    return rest[: n.start()] if n else rest


VALUE_FLAGS = ("--file", "--prd", "--phase", "--report")
SWITCHES = ("--json",)


def parse(argv):
    """The flags given, as {flag: value or True}, and None; or None and the message of a usage error."""
    args, i = {}, 0
    while i < len(argv):
        a = argv[i]
        if a in VALUE_FLAGS:
            if i + 1 >= len(argv):
                return None, f"{a} needs a value"
            args[a] = argv[i + 1]
            i += 2
        elif a in SWITCHES:
            args[a] = True
            i += 1
        else:
            return None, f"unknown argument {a!r}"
    return args, None


def main(argv):
    if "--help" in argv or "-h" in argv:
        print(__doc__)
        return 0
    args, problem = parse(argv)
    if problem:
        print(f"Error: {problem}. See --help.", file=sys.stderr)
        return 2
    as_json = bool(args.get("--json"))
    path, prd, phase, report = args.get("--file"), args.get("--prd"), args.get("--phase"), args.get("--report")
    if not path or not prd:
        print("Error: --file <flows.md> and --prd <prd.md> are required. See --help.", file=sys.stderr)
        return 2
    try:
        text = open(path, encoding="utf-8").read()
        prd_text = open(prd, encoding="utf-8").read()
    except OSError as e:
        print(f"Error: cannot read input: {e}", file=sys.stderr)
        return 2
    errors = []
    for s in SECTIONS:
        if s not in text:
            errors.append(f"missing section {s!r}")
    ids = [i for i in ID_RE.findall(text) if not i.startswith("F-")]
    dup = {i for i in ids if ids.count(i) > 1}
    if dup:
        errors.append(f"duplicate ids: {sorted(dup)}")
    ia = blocks(section(text, "Information architecture"), ("IA-",))
    screens = blocks(section(text, "Screens"), ("SCREEN-",))
    flows = blocks(section(text, "Flows"), ("FLOW-",))
    for i, b in ia.items():
        for part in ("Parent:", "URL:", "Filled by:", "Source:"):
            if part not in b:
                errors.append(f"{i} lacks {part}")
    for i, b in screens.items():
        for part in ("Purpose:", "Regions:", "States:", "Breakpoints:", "Source:"):
            if part not in b:
                errors.append(f"{i} lacks {part}")
        sm = STATES_RE.search(b)
        if sm and not re.search(r"\b(?:empty|error)\b", sm.group(1), re.I):
            errors.append(f"screen-states: {i} names no empty or error state in States: "
                          "(for a message, the error state is the delivery failure)")
    crossed = set()
    for i, b in flows.items():
        for part in ("Trigger:", "Steps:", "End:", "Failures:", "Keyboard:", "Source:"):
            if part not in b:
                errors.append(f"{i} lacks {part}")
        if not re.search(r"Actor:\s*U-\d+", b):
            errors.append(f"{i} lacks Actor: U-n")
        named = set(re.findall(r"\bSCREEN-\d+\b", b))
        if not named:
            errors.append(f"{i} names no SCREEN- in its steps")
        for s in named:
            if s not in screens:
                errors.append(f"{i} names {s}, which is not listed under Screens")
        crossed |= named
    for s in screens:
        if s not in crossed:
            errors.append(f"{s} is crossed by no flow")
    prd_feats = {}
    for fid, body in blocks(prd_text, ("F-",)).items():
        pm = re.search(r"Priority:\s*(must|should|later)\b", body)
        ph = re.search(r"Phase:\s*(P-\d+)", body)
        prd_feats[fid] = (pm.group(1) if pm else "unknown", ph.group(1) if ph else None)
    coverage = blocks(section(text, "Coverage"), ("F-",))
    for fid, (pr, ph) in prd_feats.items():
        if pr in ("must", "should") and (phase is None or ph == phase):
            if fid not in coverage:
                errors.append(f"{fid} ({pr}, {ph}) has no Coverage line")
    for fid, b in coverage.items():
        if fid not in prd_feats:
            errors.append(f"Coverage names {fid}, which the PRD does not define")
        refs = re.findall(r"\b(?:FLOW|SCREEN)-\d+\b", b)
        if not refs and "no screen:" not in b:
            errors.append(f"Coverage line for {fid} names no FLOW/SCREEN and gives no 'no screen:' reason")
        for r in refs:
            if r not in flows and r not in screens:
                errors.append(f"Coverage for {fid} names {r}, which does not exist")
    for i, b in blocks(text, ("OPEN-",)).items():
        for part in ("Blocks:", "Recommended:"):
            if part not in b:
                errors.append(f"{i} lacks {part}")
    sp = re.search(r"^-\s*Spec pending:[ \t]*(.*)$", text, re.M)
    if not sp:
        errors.append('missing the "- Spec pending:" header line')
    else:
        value = sp.group(1).strip()
        pending = re.findall(r"\bF-\d+\b", value)
        if value.lower().rstrip(".") != "none" and not pending:
            errors.append('spec-pending-line: "- Spec pending:" must be none or a list of F-n ids')
        for fid in pending:
            for i, b in flows.items():
                src = re.search(r"Source:(.*)$", b)
                if not src or not re.search(r"\b" + re.escape(fid) + r"\b", src.group(1)):
                    continue
                sm = re.search(r"Steps:\s*(.*?)\s*(?:End:|$)", b)
                steps = re.split(r"(?=\d+\.\s+on SCREEN-\d+)", sm.group(1)) if sm else []
                for step in [s for s in steps if re.match(r"\d+\.", s)]:
                    if not re.search(r"spec pending", step, re.I):
                        n = re.match(r"(\d+)\.", step).group(1)
                        errors.append(f'spec-pending-steps: {i} step {n} lacks "spec pending" ({fid} has no spec)')
    ok = not errors
    counts = {"IA": len(ia), "SCREEN": len(screens), "FLOW": len(flows), "covered": len(coverage)}
    summary = (f"lint_flows {'ok' if ok else 'FAILED'}: {len(errors)} errors; {counts['IA']} IA nodes, "
               f"{counts['SCREEN']} screens, {counts['FLOW']} flows, {counts['covered']} features covered"
               + (f"; phase {phase}" if phase else "; every phase"))
    result = {"ok": ok, "summary": summary, "counts": counts, "errors": errors}
    if report:
        record = {"script": "lint_flows.py", "date": datetime.date.today().isoformat(),
                  "arguments": {k: v for k, v in args.items() if k != "--report"},
                  "ok": ok, "summary": summary, "errors": errors, "counts": counts}
        try:
            with open(report, "w", encoding="utf-8") as f:
                json.dump(record, f, indent=2)
                f.write("\n")
        except OSError as e:
            print(f"Error: cannot write the report: {e}", file=sys.stderr)
            return 2
    print(json.dumps(result, indent=2 if as_json else None))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
