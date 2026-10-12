#!/usr/bin/env python3
"""List the GitHub links of the site's pages that point at a path of the repository's main branch, and say which of them do not resolve.

Every https://github.com/chrissgon/openhora/blob/main/<path> and /tree/main/<path> link in the href of a page is checked against the files
of the repository: `git ls-files` of the checkout this tool is in, or a list of paths given with --files. Offline: nothing is fetched.
A blob link must name a file; a tree link must name a folder (a path that some file lies under) or a file. A fragment (#L10) or a query is ignored.

Output on stdout, one tab-separated line per distinct link, sorted by kind and path:
  OK|MISSING <TAB> blob|tree <TAB> <path> <TAB> <pages that carry it, comma separated>
then one line:  SUMMARY <TAB> checked=<n> <TAB> missing=<n>
Exit code: 0 when every link resolves, 1 when at least one is missing, 2 when the tool cannot run (diagnostics on stderr).
This tool does not check the links of the site to its own pages: website.test.mjs does.
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote

REPO_URL = "https://github.com/chrissgon/openhora"
LINK = re.compile(r'''\bhref\s*=\s*["']''' + re.escape(REPO_URL) + r'''/(blob|tree)/main/([^"'#?]*)''')


def parse_args():
    here = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--site", type=Path, default=here, help="the folder that holds the pages (*.html); default: the site folder next to tools/")
    ap.add_argument("--repo", type=Path, default=None, help="the repository checkout whose `git ls-files` is the truth; default: the folder above --site")
    ap.add_argument("--files", type=Path, default=None, help="a text file with one repository path per line, used instead of `git ls-files`")
    ap.add_argument("--only-missing", action="store_true", help="print only the MISSING lines and the SUMMARY")
    return ap.parse_args()


def repository_files(args):
    if args.files:
        return [line.strip().strip("/") for line in args.files.read_text(encoding="utf-8").splitlines() if line.strip()]
    repo = args.repo or args.site.resolve().parent
    done = subprocess.run(["git", "-C", str(repo), "ls-files"], capture_output=True, text=True)
    if done.returncode != 0:
        print(f"check_links: git ls-files failed in {repo}: {done.stderr.strip()}", file=sys.stderr)
        sys.exit(2)
    return done.stdout.splitlines()


def main():
    args = parse_args()
    if not args.site.is_dir():
        print(f"check_links: {args.site} is not a folder", file=sys.stderr)
        return 2
    files = set(repository_files(args))
    folders = {"/".join(p.split("/")[:i]) for p in files for i in range(1, len(p.split("/")))}
    found = {}  # (kind, path) -> set of page names
    for page in sorted(args.site.glob("*.html")):
        for kind, raw in LINK.findall(page.read_text(encoding="utf-8")):
            found.setdefault((kind, unquote(raw).strip("/")), set()).add(page.name)
    missing = 0
    lines = []
    for (kind, path), pages in sorted(found.items()):
        ok = (path in files) if kind == "blob" else (path in folders or path in files)
        missing += 0 if ok else 1
        lines.append((ok, f"{'OK' if ok else 'MISSING'}\t{kind}\t{path}\t{','.join(sorted(pages))}"))
    for ok, line in lines:
        if not (args.only_missing and ok):
            print(line)
    print(f"SUMMARY\tchecked={len(found)}\tmissing={missing}")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
