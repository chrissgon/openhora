#!/usr/bin/env python3
"""Check a drafted post file: extract its post and first-comment blocks and run the brand checks on them.

Usage:
  python3 check_post.py --content docs/marketing/content/2026-10-05-slug.md \
      [--voice docs/brand/voice.md] [--profile docs/brand/profile.md] [--no-body-links] [--skills-dir skills] \
      [--platform-file shared/references/platforms/<platform>.json]

The content file carries the exact text in fenced blocks:
  ```post            the post body, exactly as it will be published
  ```first-comment   optional; the first comment (usually the link)

For the post it runs voice_stats.py check (limits from the voice guide's voice-rules block) and
sensitive_topics.py (the profile's sensitive-topics block); for the first comment, only
sensitive_topics.py. The two scripts are looked up next to this one first (the copies a skill carries),
then as <dir>/brand-voice/scripts/voice_stats.py and <dir>/brand-profile/scripts/sensitive_topics.py in
each --skills-dir (default: skills, then the folder the skills are installed in). A missing script or
input file is reported as "unchecked", never as a pass.

Links are found by one pattern (LINK below): an address with http:// or https://, one that starts with
www., a host with a path (short.example/x), or a bare host under a common ending (name.com, name.dev).
--no-body-links makes a link in the post body a problem: pass it when the voice or the strategy puts
links in the first comment. A link in the first comment is never a problem.

--platform-file adds the platform's caption limits, read from the keys of its data file: post.max_characters,
post.max_hashtags, post.max_mentions, post.unit ("utf-16" counts UTF-16 code units, the unit of TikTok's limit;
anything else counts characters) and post.first_comment (supported, max_characters). A key the file lacks or sets
to null is not checked. A hashtag is # followed by letters, digits or underscores, a mention is @ followed by a
handle; an address or an e-mail is neither. The post then also reports "length", "unit", "hashtags" and "mentions".

Prints JSON: {"ok", "post": {"chars", "lines", "links", "voice", "sensitive"}, "first_comment": {...} | null,
"unchecked": [...], "problems": [...]}. "ok" is true only when every check ran and passed.
Exit 0 when ok, 1 when a check failed or could not run, 2 on a bad content file, a bad platform file or a usage error.
Standard library only; no network.
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

# The one link pattern of the skills that check links. In order: an address with a scheme or www.; a host
# followed by a path, whatever its ending; a bare host under a common ending. A file name (notes.md, run.py)
# is not a link: it has no path after it and its ending is not in the list. Neither is the host of an e-mail
# address.
LINK = re.compile(r"(?:https?://|www\.)\S+"
                  r"|(?<![\w@.-])[\w-]+(?:\.[\w-]+)*\.[a-z]{2,}/\S+"
                  r"|(?<![\w@.-])[\w-]+(?:\.[\w-]+)*\.(?:com|dev|io|org|net|app|br|ly|co|ai|me)\b(?!\.\w)", re.I)
FENCE = re.compile(r"^```([\w-]*)\s*$")
HASHTAG = re.compile(r"(?<![\w&/#])#\w*[^\W_]\w*")
MENTION = re.compile(r"(?<![\w@.])@\w[\w.]*")


def blocks(text: str) -> dict:
    """Return {name: body} for fenced blocks named post and first-comment; raise on duplicates or no close."""
    found, name, buf = {}, None, []
    for line in text.splitlines():
        m = FENCE.match(line)
        if name is None:
            if m and m.group(1) in ("post", "first-comment"):
                if m.group(1) in found:
                    raise ValueError(f"more than one ```{m.group(1)} block")
                name, buf = m.group(1), []
        elif m and m.group(1) == "":
            found[name] = "\n".join(buf).strip("\n")
            name = None
        else:
            buf.append(line)
    if name is not None:
        raise ValueError(f"```{name} block is not closed")
    return found


def links(text: str) -> list:
    """Every link in the text, as written, without the punctuation that closes a sentence after it."""
    return [m.group(0).rstrip(".,;:!?)\"'") for m in LINK.finditer(text)]


def length(text: str, unit: str) -> int:
    """The length of the text in the platform's unit: UTF-16 code units for "utf-16", else characters."""
    return len(text.encode("utf-16-le")) // 2 if unit == "utf-16" else len(text)


def hashtags(text: str) -> list:
    return HASHTAG.findall(text)


def mentions(text: str) -> list:
    return [m.rstrip(".") for m in MENTION.findall(text)]


def load_limits(path: str) -> dict:
    """The caption limits of a platform data file; raise ValueError when the file cannot give them."""
    try:
        post = json.loads(Path(path).read_text(encoding="utf-8"))["post"]
        if not isinstance(post, dict):
            raise TypeError("post is not an object")
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise ValueError(f"{path}: not a platform data file ({type(e).__name__})")
    limits = {}
    for key in ("max_characters", "max_hashtags", "max_mentions"):
        value = post.get(key)
        if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 0):
            raise ValueError(f"{path}: post.{key} is not a whole number or null")
        limits[key] = value
    unit = post.get("unit")
    if unit is not None and not isinstance(unit, str):
        raise ValueError(f"{path}: post.unit is not a string or null")
    limits["unit"] = "utf-16" if unit == "utf-16" else "characters"
    first = post.get("first_comment")
    first = first if isinstance(first, dict) else {}
    limits["first_comment_supported"] = first.get("supported")
    limits["first_comment_max_characters"] = first.get("max_characters")
    return limits


def find_script(skills_dirs: list, skill: str, script: str):
    beside = Path(__file__).resolve().parent / script
    if beside.is_file():
        return beside
    for d in skills_dirs:
        p = Path(d) / skill / "scripts" / script
        if p.is_file():
            return p
    return None


def run(cmd: list, stdin: str):
    try:
        r = subprocess.run(cmd, input=stdin, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, f"{Path(cmd[1]).name}: {e}"
    try:
        return (r.returncode, json.loads(r.stdout)), None
    except json.JSONDecodeError:
        return None, f"{Path(cmd[1]).name} exited {r.returncode}: {r.stderr.strip()[:200]}"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--content", required=True)
    p.add_argument("--voice", default="docs/brand/voice.md")
    p.add_argument("--profile", default="docs/brand/profile.md")
    p.add_argument("--no-body-links", action="store_true",
                   help="a link in the post body is a problem (links go in the first comment)")
    p.add_argument("--skills-dir", action="append", default=None)
    p.add_argument("--platform-file", default=None,
                   help="the platform's data file: its caption limits are checked as well")
    a = p.parse_args(argv)

    limits = None
    if a.platform_file:
        try:
            limits = load_limits(a.platform_file)
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2

    try:
        found = blocks(Path(a.content).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:  # a missing file, bytes that are not UTF-8, a block that is not closed
        print(f"error: {a.content}: {e}", file=sys.stderr)
        return 2
    if not found.get("post"):
        print(f"error: {a.content} has no ```post block", file=sys.stderr)
        return 2

    dirs = a.skills_dir or ["skills", str(Path(__file__).resolve().parents[2])]
    voice_py = find_script(dirs, "brand-voice", "voice_stats.py")
    sens_py = find_script(dirs, "brand-profile", "sensitive_topics.py")
    unchecked, problems = [], []

    def sensitive(text: str, label: str):
        if not sens_py:
            unchecked.append(f"{label}: sensitive_topics.py not installed")
            return None
        if not Path(a.profile).is_file():
            unchecked.append(f"{label}: {a.profile} not found")
            return None
        res, err = run([sys.executable, str(sens_py), "--profile", a.profile], text)
        if err:
            unchecked.append(f"{label}: {err}")
            return None
        code, out = res
        if code != 0:
            problems.append(f"{label}: sensitive topics {out.get('topics')}")
        return out

    post = found["post"]
    out = {"post": {"chars": len(post), "lines": len(post.splitlines()), "links": links(post)}}
    if limits:
        n, unit = length(post, limits["unit"]), limits["unit"]
        tags, names = hashtags(post), mentions(post)
        out["post"].update({"length": n, "unit": unit, "hashtags": len(tags), "mentions": names})
        for label, count, limit in (("characters" if unit == "characters" else "UTF-16 code units", n, limits["max_characters"]),
                                    ("hashtags", len(tags), limits["max_hashtags"]),
                                    ("mentions", len(names), limits["max_mentions"])):
            if limit is not None and count > limit:
                problems.append(f"post: {count} {label}, limit {limit}")
    if a.no_body_links and out["post"]["links"]:
        problems.append(f"post: links in the body {out['post']['links']}; they go in the first comment")
    if not voice_py:
        unchecked.append("post: voice_stats.py not installed")
    elif not Path(a.voice).is_file():
        unchecked.append(f"post: {a.voice} not found")
    else:
        res, err = run([sys.executable, str(voice_py), "check", "--rules", a.voice],
                       json.dumps({"id": Path(a.content).stem, "text": post}, ensure_ascii=False))
        if err:
            unchecked.append(f"post: {err}")
        else:
            out["post"]["voice"] = res[1]
            if not res[1].get("ok"):
                problems.append(f"post: voice {res[1].get('violations')}")
    out["post"]["sensitive"] = sensitive(post, "post")

    comment = found.get("first-comment")
    if comment:
        out["first_comment"] = {"chars": len(comment), "links": links(comment),
                                "sensitive": sensitive(comment, "first comment")}
        if limits and limits["first_comment_supported"] is False:
            problems.append("first comment: the platform has none")
        elif limits and limits["first_comment_max_characters"] is not None:
            n = length(comment, limits["unit"])
            if n > limits["first_comment_max_characters"]:
                problems.append(f"first comment: {n} characters, limit {limits['first_comment_max_characters']}")
    else:
        out["first_comment"] = None
    out["unchecked"], out["problems"] = unchecked, problems
    out["ok"] = not unchecked and not problems
    json.dump(out, sys.stdout, ensure_ascii=False, indent=1)
    print()
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
