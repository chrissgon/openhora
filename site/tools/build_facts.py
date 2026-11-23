#!/usr/bin/env python3
"""Write the figures the pages of site/ state (counts, dates, bands, the lab models) from their sources, so that a page cannot go stale.

Usage (from the repository root):
  python3 site/tools/build_facts.py --write    rewrite every block of every page
  python3 site/tools/build_facts.py --check    exit 1 and name each block that differs, and each constant that disagrees with the gate file

A block is the text between `<!-- facts:begin <name> -->` and `<!-- facts:end <name> -->` in a page (site/*.html). Its content is made here
from site/assets/data/proof.json (the band and model tables of docs/inventory.md and the gate file, built by build_proof_json.py) and from
count_facts.py (the skills that carry the external-content line, the guard assertions, and the sizes of the folders). Nothing between the
two marks is edited by hand. The marks are comments: the pages stay static HTML, and need no script to show the numbers.

Run `python3 site/tools/build_proof_json.py` first when docs/inventory.md or evals/eval-gate.json changed. Standard library only; no network.
"""
import argparse
import glob
import html
import json
import math
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SITE = os.path.join(ROOT, "site")
BAND_CLASS = {"reliable": "ok", "watch": "w", "needs a test": "e"}
WORD_CLASS = {"reliable": "ok", "watch": "warn", "needs a test": "err"}
ORDER = ["reliable", "watch", "needs a test"]
BLOCK = re.compile(r"(<!-- facts:begin (?P<name>[a-z0-9-]+) -->)(?P<body>.*?)(<!-- facts:end (?P=name) -->)", re.S)
esc = html.escape


# ---------------------------------------------------------------- the data
def load_proof():
    return json.load(open(os.path.join(SITE, "assets", "data", "proof.json"), encoding="utf-8"))


def load_counts():
    out = subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "count_facts.py")], capture_output=True, text=True, cwd=ROOT, check=True).stdout
    return json.loads(out.strip().splitlines()[-1])


class Facts:
    def __init__(self, proof, counts):
        self.proof = proof
        self.counts = counts
        self.models = [m["model"] for m in proof["lab_models"]]
        self.skills = proof["skills"]
        self.n = len(self.skills)
        self.commit = proof["generated_at_commit"]

    def band(self, skill, model):
        return skill["models"].get(model, {}).get("band", "needs a test")

    def tally(self, model):
        t = {b: 0 for b in ORDER}
        for s in self.skills:
            t[self.band(s, model)] += 1
        return t

    def dominant(self, model):
        t = self.tally(model)
        top = max(t.values())
        for b in ("needs a test", "watch", "reliable"):
            if t[b] == top:
                return b, top

    def groups(self, model):
        """[(band, text, count)]: the reliable skills first, then each cause of the others, the most frequent first."""
        out, causes = [], {}
        rel = 0
        for s in self.skills:
            m = s["models"].get(model, {})
            b = m.get("band", "needs a test")
            if b == "reliable":
                rel += 1
                continue
            key = (b, norm_cause(m.get("cause") or "no evidence on this model"))
            causes[key] = causes.get(key, 0) + 1
        if rel:
            out.append(("reliable", "reliable, no cause to clear" if not causes else "reliable", rel))
        for (b, c), k in sorted(causes.items(), key=lambda kv: (-kv[1], kv[0])):
            out.append((b, c, k))
        return out

    def full_range(self):
        dates = sorted(m.group(0) for s in self.skills for m in [re.match(r"\d{4}-\d{2}-\d{2}", s.get("last_full_test", ""))] if m)
        return (dates[0], dates[-1]) if dates else ("none", "none")


def norm_cause(c):
    if c.startswith("no baseline in force"):
        return "no baseline in force on this model"
    if c.startswith("guard assertion"):
        return "guard assertions have no run in the current set"
    if c.startswith("no full test") or c.startswith("no current case"):
        return "no full test of the current version, or no current case in the gate"
    return re.sub(r"\s*for case\(s\).*$", "", c)


def word(b):
    return f'<span class="band-word {WORD_CLASS[b]}">{esc(b)}</span>'


def plural(n, one, many=None):
    return f"{n} {one if n == 1 else (many or one + 's')}"


# ---------------------------------------------------------------- inline blocks
def b_skills(f):
    return str(f.n)


def b_commit(f):
    return f.commit


def b_full_range(f):
    a, b = f.full_range()
    return f"{a} to {b}"


def b_threshold(f):
    return str(f.proof["threshold"])


def b_tolerance(f):
    return str(f.proof["tolerance"])


def b_gate_values(f):
    return f"threshold {f.proof['threshold']}, tolerance {f.proof['tolerance']}, {f.proof['runs_per_case']} runs per case"


def b_models_n(f):
    return str(len(f.models))


def b_external(f):
    return str(f.counts["external_content_skills"])


def b_guards(f):
    return str(f.counts["guard_assertions"])


def counter(key):
    return lambda f: str(f.counts[key])


# ---------------------------------------------------------------- the dial
def pt(r, k, n):
    a = 2 * math.pi * k / n
    return 300 + r * math.sin(a), 300 - r * math.cos(a)


def b_dial(f):
    n, N = len(f.models), f.n
    step = min(40.0, (262 - 126) / (n - 1)) if n > 1 else 40.0
    length = max(5.0, min(16.0, step - 22))
    radii = [262 - step * i for i in range(n)]
    desc = "; ".join(f"Ring {i + 1}, lab model {m}: " + ", ".join(f"{f.tally(m)[b]} {b}" for b in ORDER) for i, m in enumerate(f.models))
    out = [f'\n  <title id="dial-t">One tick per skill, one ring per lab model, the outer ring first. {esc(desc)}. Snapshot at commit {f.commit}.</title>', "  <defs>"]
    for i, r in enumerate(radii):
        base = r + 5
        out.append(f'    <path id="arc-{i}" d="M {300 - base:g} 300 A {base:g} {base:g} 0 1 1 {300 + base:g} 300"/>')
    out.append("  </defs>")
    out.append('  <circle class="ring r0" cx="300" cy="300" r="94"/><circle class="ring r1" cx="300" cy="300" r="108"/>')
    out.append('  <circle class="rim faint" cx="300" cy="300" r="116"/>')
    for i, m in enumerate(f.models):
        ticks = []
        for k, s in enumerate(f.skills):
            x1, y1 = pt(radii[i], k, N)
            x2, y2 = pt(radii[i] - length, k, N)
            cls = {"reliable": "ok", "watch": "w", "needs a test": "e"}[f.band(s, m)]
            ticks.append(f'<line class="tk {cls}" style="--i:{k}" x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}"/>')
        out.append(f'  <g class="ring-g{" sub" if i else ""}" style="--r:{i}">' + "".join(ticks) + "</g>")
    for i, m in enumerate(f.models):
        out.append(f'  <text aria-hidden="true" class="arc-label{" in" if i else ""}"><textPath href="#arc-{i}" startOffset="50%" text-anchor="middle">{esc(m)}</textPath></text>')
    return "\n".join(out) + "\n"


def b_dial_key(f):
    out = ["\n"]
    for i, m in enumerate(f.models):
        t = f.tally(m)
        out.append(f'        <span class="kr"><span class="kn">ring {i + 1} · {esc(m)}</span>' + "".join(f'<span class="band-word {WORD_CLASS[b]}">{b} {t[b]}</span>' for b in ORDER) + "</span>\n")
    out.append(f'        <span class="kr muted">one tick per skill · of {f.n} skills · snapshot at commit {f.commit}</span>\n      ')
    return "".join(out)


def b_ledger(f):
    c = f.counts
    rows = [(f.n, "skills (all capabilities)"), (c["agents"], "agents"), (c["adapters"], "adapters"), (c["flows"], "flow data files"), (c["packs"], "packs")]
    return "\n" + "".join(f"          <li><b>{n}</b><span>{esc(t)}</span></li>\n" for n, t in rows) + "        "


# ---------------------------------------------------------------- the figures of the home page
def cells(f, model):
    return "".join(
        f'<i{"" if f.band(s, model) == "reliable" else f" class={chr(34)}{BAND_CLASS[f.band(s, model)]}{chr(34)}"} style="--i:{k}"></i>' for k, s in enumerate(f.skills))


def floor_list(f, model, label):
    lis = "".join(f'\n          <li>{word(b)}<span>{plural(k, "skill")}: {esc(t)}</span></li>' for b, t, k in f.groups(model))
    return f'<ul class="floor-list" aria-label="{esc(label)}">{lis}\n        </ul>'


def b_proof_figures(f):
    multi = len(f.models) > 2
    out = [f'\n    <div class="proof-grid{" multi" if multi else ""}">']
    for i, m in enumerate(f.models):
        t = f.tally(m)
        b, k = f.dominant(m)
        big = not multi and i == 0
        aria = f"Lab model {m}: " + ", ".join(f"{t[x]} {x}" for x in ORDER) + f", of {f.n} skills, snapshot at commit {f.commit}"
        out.append('      <div class="figure-cell">')
        if i == 0:
            out.append('        <div class="glow" aria-hidden="true"></div>')
        out.append(f'        <p class="fig-model"><span>Lab model</span><strong>{esc(m)}</strong></p>')
        out.append(f'        <div class="figure{"" if big else " small"}" role="img" aria-label="{esc(aria)}">')
        out.append(f'          <span class="num" data-count="{k}" aria-hidden="true">{k}</span>')
        out.append(f'          <span class="of" aria-hidden="true">{word(b)}<span>of {f.n} skills</span></span>')
        out.append("        </div>")
        out.append(f'        <div class="cells" aria-hidden="true">{cells(f, m)}</div>')
        out.append('        <p class="legend" aria-hidden="true">' + "".join(f'<span class="band-word {WORD_CLASS[x]}">{x} {t[x]}</span>' for x in ORDER) + "</p>")
        out.append("        " + floor_list(f, m, "The bands of the skills on this lab model, by cause"))
        out.append("      </div>")
    out.append("    </div>")
    a, z = f.full_range()
    out.append('    <dl class="meta-row">')
    out.append(f"      <div><dt>counted over</dt><dd>{f.n} skills</dd></div>")
    out.append(f"      <div><dt>snapshot</dt><dd>commit {f.commit}</dd></div>")
    out.append(f"      <div><dt>last full tests</dt><dd>{a} to {z}</dd></div>")
    out.append(f"      <div><dt>lab models</dt><dd>{len(f.models)}</dd></div>")
    out.append("    </dl>\n    ")
    return "\n".join(out)


def b_lab_models(f):
    items = []
    for m in f.models:
        for b, t, k in f.groups(m):
            txt = f"{m}: {plural(k, 'skill')}" + ("" if b == "reliable" else f", {t}")
            items.append(f'          <li>{word(b)}<span>{esc(txt)}</span></li>')
    names = ", ".join(f.models[:-1]) + (" and " if len(f.models) > 1 else "") + f.models[-1]
    return (f'<p class="label anim">Lab models · snapshot at commit {f.commit} · {plural(f.n, "skill")}</p>\n'
            f'        <ul class="floor-list anim" aria-label="Lab models, {esc(names)}, snapshot at commit {f.commit}">\n' + "\n".join(items) + "\n        </ul>")


def b_claim_rows(f):
    out = ["\n"]
    for m in f.models:
        t = f.tally(m)
        out.append(f'        <div class="br"><span class="br-model"><b>{esc(m)}</b><small>lab model</small></span>' + "".join(f'<span class="band-word {WORD_CLASS[b]}">{b} {t[b]}</span>' for b in ORDER) + "</div>\n")
    a, z = f.full_range()
    out.append(f'        <p class="br-meta">of {f.n} skills · snapshot at commit {f.commit} · last full tests {a} to {z}</p>\n      ')
    return "".join(out)


def b_evidence_rows(f):
    out = ["\n"]
    for m in f.models:
        for j, (b, t, k) in enumerate(f.groups(m)):
            who = f"<b>{esc(m)}</b><small>lab model</small>" if j == 0 else "<b>&nbsp;</b><small>&nbsp;</small>"
            out.append(f'        <div class="br"><span class="br-model">{who}</span>{word(b)}<span>{plural(k, "skill")}: {esc(t)}</span></div>\n')
    out.append(f'        <p class="br-meta">{plural(f.n, "skill")} with a band on each of {plural(len(f.models), "lab model")} · snapshot at commit {f.commit}</p>\n      ')
    return "".join(out)


# ---------------------------------------------------------------- the status excerpts
def b_status_excerpt(f):
    s0 = f.skills[[s["skill"] for s in f.skills].index("biz-icp-positioning")] if any(s["skill"] == "biz-icp-positioning" for s in f.skills) else f.skills[0]
    m1 = f.models[0]
    m2 = f.models[1] if len(f.models) > 1 else f.models[0]
    t = f.tally(m1)
    ln = lambda i, body, extra="": f'<span class="ln reveal-line{extra}" style="--i:{i}">{body}</span>'
    k = lambda x: f'<span class="k">"{x}"</span>'
    main = [
        ln(0, "{"), ln(1, f"  {k('skills')}: ["), ln(2, "    {"),
        ln(3, f'      {k("skill")}: "{esc(s0["skill"])}",'), ln(4, f'      {k("version")}: "{esc(s0["version"])}",'),
        ln(5, f'      {k("band")}: "{f.band(s0, m1)}",'), ln(6, "…", " gap"),
        ln(7, f'  {k("counts")}: {{'),
        ln(8, f'    {k("needs a test")}: {t["needs a test"]},'), ln(9, f'    {k("watch")}: {t["watch"]},'),
        ln(10, f'    {k("reliable")}: {t["reliable"]}', " hl"), ln(11, "  },"),
        '<span class="ln reveal-line" style="--i:12"><span class="cursor" aria-hidden="true"></span></span>',
    ]
    m = s0["models"].get(m2, {})
    cause = m.get("cause")
    float_ = [
        f'<span class="ln">{k("skill")}: "{esc(s0["skill"])}",</span>', '<span class="ln gap">…</span>',
        f'<span class="ln">{k(m2)}: {{</span>', f'<span class="ln">  {k("band")}: "{esc(m.get("band", "needs a test"))}",</span>',
        f'<span class="ln">  {k("cause")}: ' + ("null" if cause is None else f'"{esc(cause)}"') + ",</span>",
    ]
    bar = '<div class="term-bar"><span class="lights" aria-hidden="true"><i></i><i></i><i></i></span><span class="tab">{}</span><span class="meta">{}</span></div>'
    return ('<div class="stack"><div class="term main">' + bar.format("terminal", "repository root") +
            '<pre class="code"><span class="ln type" style="--steps:37;--dur:1.1s;--delay:.4s"><span class="p">$ </span><span class="a">python3 evals/eval_status.py status</span></span>' + "".join(main) + "</pre></div>"
            '<div class="term float">' + bar.format("status · lab model", "excerpt") + '<pre class="code">' + "".join(float_) + "</pre></div></div>")


def b_result_card(f):
    m = f.models[0]
    t = f.tally(m)
    b, k = f.dominant(m)
    label = f"Lab model {m}: " + ", ".join(f"{t[x]} {x}" for x in ORDER) + f", of {f.n} skills, snapshot at commit {f.commit}"
    return (f'<div class="result-card anim" role="group" aria-label="{esc(label)}"><span class="rc-fig" aria-hidden="true">{k}<small>/{f.n}</small></span>'
            f'<span class="rc-body" aria-hidden="true">{word(b)}<span class="rc-meta">{esc(m)} · lab model · snapshot at commit {f.commit}</span></span></div>')


def gate_lines():
    path = os.path.join(ROOT, "evals", "eval-gate.json")
    lines = open(path, encoding="utf-8").read().splitlines()
    out = {}
    for i, line in enumerate(lines, 1):
        m = re.match(r'^  "(grader|threshold|tolerance|runs)": (.*?),?$', line)
        if m and m.group(1) not in out:
            out[m.group(1)] = (i, m.group(2))
    return out


def b_gate_excerpt(f):
    g = gate_lines()
    rows = []
    for key in ("grader", "threshold", "tolerance", "runs"):
        i, v = g[key]
        rows.append(f'<span class="ln{" hl" if key in ("threshold", "tolerance") else ""}"><span class="n">{i}</span><span>  <span class="k">"{key}"</span>: {esc(v)},</span></span>')
    first, last = g["grader"][0], g["runs"][0]
    return ('<div class="term "><div class="term-bar"><span class="lights" aria-hidden="true"><i></i><i></i><i></i></span><span class="tab">evals/eval-gate.json</span>'
            f'<span class="meta">lines {first} to {last}</span></div><pre class="code numbered">' + "".join(rows) + "</pre></div>")


# ---------------------------------------------------------------- the proof page: the skill list and the default result
def b_skill_list(f):
    return "".join(f'<li><button type="button" class="sk-opt" data-skill="{esc(s["skill"])}"{" aria-current=" + chr(34) + "true" + chr(34) if s["skill"] == "mkt-social-copy" else ""}><span>{esc(s["skill"])}</span><small>{esc(s["version"])}</small></button></li>' for s in f.skills)


def b_route_default(f, name="mkt-social-copy"):
    """The result the page script would draw for `name` (proof.js, render): what shows with no script."""
    s = next((x for x in f.skills if x["skill"] == name), f.skills[0])
    adapters = {m["model"]: m["adapter"] for m in f.proof["lab_models"]}
    rows = []
    for m in f.models:
        v = s["models"].get(m, {"band": "needs a test", "cause": "no evidence on this model", "score": "n/a", "mean": "n/a", "runs": "0", "gate": "-"})
        cause = f'<small class="mr-cause">{esc(v["cause"])}</small>' if v.get("cause") else ""
        rows.append(f'<tr><th scope="row"><b>{esc(m)}</b><small>{esc(adapters[m])}</small></th><td>{word(v["band"])}{cause}</td>'
                    f'<td>{esc(v["score"])}</td><td>{esc(v["mean"])}</td><td>{esc(v["runs"])}</td><td>{esc(v["gate"])}</td></tr>')
    reliable = [m for m in f.models if f.band(s, m) == "reliable"]
    why = (f"its band is reliable on {len(reliable)} of {len(f.models)} lab models: the runtime may release a run on them without review, when the measurement and the image match the recorded ones, "
           "and auto picks the cheapest of them by price and measured usage; a model you name runs whatever its band, and then waits for you"
           if reliable else "no lab model has a reliable band for it: a run waits for your review, whichever model you name")
    badge = ("pui-success", "reliable") if reliable else ("pui-theme", "supervised")
    return ('\n          <div class="mr-head"><h4 class="mr-name">' + esc(s["skill"]) + f'</h4><span class="mr-ver">v{esc(s["version"])} · last full test {esc(s["last_full_test"])}</span></div>\n'
            '          <table class="mr-table"><thead><tr><th scope="col">Model</th><th scope="col">Band</th><th scope="col">Score</th><th scope="col">Mean</th><th scope="col">Runs counted</th><th scope="col">Gate</th></tr></thead><tbody>'
            + "".join(rows) + "</tbody></table>\n"
            f'          <div class="mr-route {"is-floor" if reliable else "is-ref"}"><p class="mr-k">Released without review on</p><p class="mr-model">'
            + (esc(", ".join(reliable)) if reliable else "no lab model") + f' <span class="pui-badge pui-soft {badge[0]}">{badge[1]}</span></p>'
            f'<p class="mr-why"><span>Why:</span> {esc(why)}.</p></div>\n        ')


BLOCKS = {
    "skills": b_skills, "commit": b_commit, "full-range": b_full_range, "threshold": b_threshold, "tolerance": b_tolerance, "gate-values": b_gate_values,
    "models-n": b_models_n, "external-skills": b_external, "guard-assertions": b_guards,
    "dial": b_dial, "dial-key": b_dial_key, "ledger": b_ledger, "proof-figures": b_proof_figures, "lab-models": b_lab_models,
    "claim-rows": b_claim_rows, "evidence-rows": b_evidence_rows, "status-excerpt": b_status_excerpt, "result-card": b_result_card,
    "gate-excerpt": b_gate_excerpt, "skill-list": b_skill_list, "route-default": b_route_default,
}


# ---------------------------------------------------------------- pages
def pages():
    return sorted(glob.glob(os.path.join(SITE, "*.html")))


def rebuild(text, facts):
    """(new text, [names of the blocks that changed], [names of unknown blocks])."""
    changed, unknown = [], []

    def sub(m):
        name = m.group("name")
        if name not in BLOCKS:
            unknown.append(name)
            return m.group(0)
        body = BLOCKS[name](facts)
        if body != m.group("body"):
            changed.append(name)
        return m.group(1) + body + m.group(4)

    return BLOCK.sub(sub, text), changed, unknown


def check_constants(facts):
    """The gate widget's constants in proof.js agree with the gate file: the page has no block for a script."""
    js = open(os.path.join(SITE, "assets", "js", "proof.js"), encoding="utf-8").read()
    m = re.search(r"THRESHOLD = ([0-9.]+), TOLERANCE = ([0-9.]+)", js)
    problems = []
    if not m:
        problems.append("assets/js/proof.js: no `THRESHOLD = x, TOLERANCE = y` line")
    elif (float(m.group(1)), float(m.group(2))) != (facts.proof["threshold"], facts.proof["tolerance"]):
        problems.append(f"assets/js/proof.js: THRESHOLD/TOLERANCE {m.group(1)}/{m.group(2)} differ from the gate file {facts.proof['threshold']}/{facts.proof['tolerance']}")
    return problems


def main(argv=None):
    global SITE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--write", action="store_true", help="rewrite the blocks")
    g.add_argument("--check", action="store_true", help="exit 1 when a block differs")
    ap.add_argument("--site", default=SITE, help="the folder of the pages (default: site/ of this checkout; the proof data is read from it)")
    a = ap.parse_args(argv)
    SITE = a.site
    facts = Facts(load_proof(), load_counts())
    bad = []
    for path in pages():
        text = open(path, encoding="utf-8").read()
        new, changed, unknown = rebuild(text, facts)
        rel = os.path.relpath(path, ROOT) if path.startswith(ROOT) else path
        bad += [f"{rel}: unknown block {n}" for n in unknown]
        if changed:
            if a.write:
                open(path, "w", encoding="utf-8").write(new)
                print(f"{rel}: rewrote {', '.join(sorted(set(changed)))}", file=sys.stderr)
            else:
                bad += [f"{rel}: block {n} differs" for n in sorted(set(changed))]
    bad += check_constants(facts)
    if bad:
        print("\n".join(bad), file=sys.stderr)
        if a.check:
            print("fix: python3 site/tools/build_proof_json.py && python3 site/tools/build_facts.py --write", file=sys.stderr)
        sys.exit(1)
    if a.check:
        print("the facts of the pages are current", file=sys.stderr)


if __name__ == "__main__":
    main()
