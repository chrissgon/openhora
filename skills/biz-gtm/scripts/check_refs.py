#!/usr/bin/env python3
"""Check the citations of a researched artifact: every reference used is defined, and every source is complete.

Usage:
  python3 check_refs.py --file <artifact.md> [--sources-heading Sources] [--method-heading Method]
      [--published-label Published] [--undated-label undated] [--accessed-label Accessed] [--tier-label Tier]

Reads the Markdown file. References are [n] or [nb] (numbers, optional letter) and M<n> for
commands. Sources are the lines under the sources heading that start with [n]; commands are the
M<n> labels that appear under the method heading. A source entry has this form:

  [1] <Title>, <Publisher>. Published <date | undated>. Accessed <date>. <URL>. Tier <1|2|3>. <kind>. Quote: "<...>"

Reports:
  undefined: references used in the text with no source entry (or M<n> absent from Method);
  unused: source entries never cited in the text;
  incomplete: source entries with a part missing, each with the list of what is missing:
    publisher  no ", <publisher>" after the title, before the published label
    published  no "<published label> <date>" and no "<published label> <undated label>"
    accessed   no "<accessed label> <date>"
    url        no http(s) URL
    tier       no "<tier label> 1", "2" or "3"
    quote      no quoted text ("...")
A date is YYYY, YYYY-MM or YYYY-MM-DD. Headings and labels are matched case-insensitive; pass the
translated heading or label when the artifact is not in English.
Prints JSON to stdout; exit 1 when anything is reported, 2 on a bad argument or unreadable file.
"""
import argparse
import json
import re
import sys

REF = re.compile(r"\[(\d+[a-z]?)\]")
CMD = re.compile(r"\bM(\d+)\b")
QUOTE = re.compile(r"[\"“”]")
DATE = r"\d{4}(?:-\d{2}){0,2}(?!\d)"
PARTS = ("publisher", "published", "accessed", "url", "tier", "quote")


def missing_parts(entry, labels):
    """The parts of one source entry that are not there, in the order of PARTS."""
    published, undated, accessed, tier = (re.escape(labels[k]) for k in ("published", "undated", "accessed", "tier"))
    head = re.split(r"\b" + published + r"\b", entry, maxsplit=1, flags=re.I)[0]
    found = {
        "publisher": bool(re.search(r"\S\s*,\s*\S", head)),
        "published": bool(re.search(r"\b" + published + r"\s+(?:" + DATE + "|" + undated + r"\b)", entry, re.I)),
        "accessed": bool(re.search(r"\b" + accessed + r"\s+" + DATE, entry, re.I)),
        "url": bool(re.search(r"https?://\S", entry)),
        "tier": bool(re.search(r"\b" + tier + r"\s+[123](?!\d)", entry, re.I)),
        "quote": bool(QUOTE.search(entry)),
    }
    return [p for p in PARTS if not found[p]]


def sections(text):
    out, name, buf = {}, "", []
    for line in text.splitlines():
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if m:
            out[name] = out.get(name, "") + "\n".join(buf)
            name, buf = m.group(1).strip().lower(), []
        else:
            buf.append(line)
    out[name] = out.get(name, "") + "\n".join(buf)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", required=True)
    ap.add_argument("--sources-heading", default="Sources")
    ap.add_argument("--method-heading", default="Method")
    ap.add_argument("--published-label", default="Published")
    ap.add_argument("--undated-label", default="undated")
    ap.add_argument("--accessed-label", default="Accessed")
    ap.add_argument("--tier-label", default="Tier")
    args = ap.parse_args()
    labels = {"published": args.published_label, "undated": args.undated_label, "accessed": args.accessed_label,
              "tier": args.tier_label}
    if not all(v.strip() for v in labels.values()):
        print("check_refs.py: a label cannot be empty", file=sys.stderr)
        sys.exit(2)
    try:
        with open(args.file, encoding="utf-8") as fh:
            text = fh.read()
    except (OSError, UnicodeDecodeError) as exc:
        print(f"check_refs.py: cannot read {args.file}: {exc}", file=sys.stderr)
        sys.exit(2)
    secs = sections(text)
    src_key, meth_key = args.sources_heading.lower(), args.method_heading.lower()
    if src_key not in secs:
        print(f"check_refs.py: no '## {args.sources_heading}' heading in {args.file}", file=sys.stderr)
        sys.exit(2)
    sources = secs[src_key]
    method = secs.get(meth_key, "")
    body = "\n".join(v for k, v in secs.items() if k not in (src_key, meth_key))
    entries = {}
    for line in sources.splitlines():
        m = re.match(r"^\s*\[(\d+[a-z]?)\]\s*(.*)$", line)
        if m:
            entries[m.group(1)] = m.group(2)
    used = set(REF.findall(body))
    cmds_used = set(CMD.findall(body))
    cmds_defined = set(CMD.findall(method))
    key = lambda r: (int(re.match(r"\d+", r).group()), r)
    report = {
        "file": args.file,
        "sources": len(entries),
        "undefined": sorted(used - set(entries), key=key) + [f"M{n}" for n in sorted(cmds_used - cmds_defined, key=int)],
        "unused": sorted(set(entries) - used, key=key),
        "incomplete": [{"ref": r, "missing": missing_parts(e, labels)}
                       for r, e in sorted(entries.items(), key=lambda kv: key(kv[0])) if missing_parts(e, labels)],
    }
    report["ok"] = not (report["undefined"] or report["unused"] or report["incomplete"])
    json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    sys.exit(0 if report["ok"] else 1)


if __name__ == "__main__":
    main()
