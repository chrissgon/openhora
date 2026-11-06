#!/usr/bin/env bash
# Collect what a pull request needs to be written, as JSON on stdout.
#
# Usage: bash pr-context.sh [--base <branch>] [--help]
#
# Prints: repository root, current branch, base branch (the remote's default, else main or
# master) and the ref compared with (origin/<base> after a fetch, so a stale local base cannot
# list the base's own commits as the branch's), the commits the branch adds, the files it
# changes, whether it is pushed, the address of the origin remote (null when there is none), the pull request template (path and content, first found in the
# usual places), the last base commits (to read the commit convention), the lines of AGENTS.md or
# CONTRIBUTING.md about merging, and an open pull request for the branch when the code host's
# command-line tool, when present, can tell.
#
# A --base that is not a valid branch name (git check-ref-format --branch), or that starts with
# "-", is refused with exit 2 before any git call uses it, so it cannot be read as an option.
set -euo pipefail
BASE=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --base) [[ $# -ge 2 ]] || { echo "Error: --base needs a value. See --help." >&2; exit 2; }; BASE="$2"; shift 2 ;;
    --help|-h) sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Error: unknown option '$1'. See --help." >&2; exit 2 ;;
  esac
done
valid_branch() { [[ -n "$1" && "$1" != -* ]] && git check-ref-format --branch "$1" >/dev/null 2>&1; }
if [[ -n "$BASE" ]] && ! valid_branch "$BASE"; then
  echo "Error: --base '$BASE' is not a branch name. See --help." >&2
  exit 2
fi
ROOT=$(git rev-parse --show-toplevel)
cd "$ROOT"
BRANCH=$(git branch --show-current)
if [[ -z "$BASE" ]]; then
  BASE=$(git symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null | sed 's#^origin/##' || true)
  [[ -z "$BASE" ]] && for b in main master; do git show-ref --verify --quiet "refs/heads/$b" && { BASE=$b; break; }; done
  [[ -n "$BASE" ]] && ! valid_branch "$BASE" && BASE=""
fi
CMP="$BASE"
if [[ -n "$BASE" ]] && git remote get-url origin >/dev/null 2>&1; then
  git fetch --quiet --end-of-options origin "$BASE" 2>/dev/null || true
  git show-ref --verify --quiet "refs/remotes/origin/$BASE" && CMP="origin/$BASE"
fi
TEMPLATE=""
for f in .github/pull_request_template.md .github/PULL_REQUEST_TEMPLATE.md PULL_REQUEST_TEMPLATE.md docs/pull_request_template.md; do
  [[ -f "$f" ]] && { TEMPLATE=$f; break; }
done
PUSHED=false
[[ -n "$BRANCH" ]] && git ls-remote --exit-code --heads --end-of-options origin "refs/heads/$BRANCH" >/dev/null 2>&1 && PUSHED=true
REMOTE=$(git remote get-url origin 2>/dev/null || true)
OPEN_PR=""
command -v gh >/dev/null && OPEN_PR=$(gh pr list --head "$BRANCH" --json url --jq '.[0].url' 2>/dev/null || true)
python3 - "$ROOT" "$BRANCH" "$BASE" "$CMP" "$TEMPLATE" "$PUSHED" "$OPEN_PR" "$REMOTE" <<'PY'
import json, os, subprocess, sys
root, branch, base, cmp, template, pushed, open_pr, remote = sys.argv[1:]
git = lambda *a: subprocess.run(["git", *a], capture_output=True, text=True).stdout.strip()
rules = []
for doc in ("AGENTS.md", "CONTRIBUTING.md"):
    if os.path.isfile(doc):
        rules += [f"{doc}: {l.strip()}" for l in open(doc, encoding="utf-8") if any(w in l.lower() for w in ("merge", "squash", "rebase", "commit"))]
print(json.dumps({
    "root": root,
    "branch": branch,
    "base": base,
    "compared_with": cmp,
    "commits": git("log", "--format=%h %s", "--end-of-options", f"{cmp}..HEAD", "--").splitlines() if base else [],
    "files": git("diff", "--name-status", "--end-of-options", f"{cmp}...HEAD", "--").splitlines() if base else [],
    "pushed": pushed == "true",
    "remote": remote or None,
    "open_pull_request": open_pr or None,
    "template": {"path": template, "content": open(template, encoding="utf-8").read()} if template else None,
    "base_history": git("log", "--format=%s", "-8", "--end-of-options", cmp, "--").splitlines() if base else [],
    "merge_rules": rules,
}, indent=2))
PY
