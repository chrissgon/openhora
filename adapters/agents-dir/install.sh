#!/usr/bin/env bash
# Install openhora skills into the cross-tool skills directory.
#
# Usage: bash adapters/agents-dir/install.sh [--pack <name>] [--project <dir>] [--copy] [--dry-run] [--uninstall]
#
# Default target is ~/.agents/skills (read by Codex, Cursor, Cline, OpenCode, OpenClaw and others).
# --pack <name>    which skills to install (packs/<name>.txt); default: default
# --project <dir>  target <dir>/.agents/skills instead of the user-level directory
# --copy           copy folders instead of symlinking (for filesystems without symlinks)
# --uninstall      remove everything this installer made in the target, whatever pack installed it
# The shared references go beside the skills, in <target>/../shared/references, so that a skill's
# ../../shared/references/<file> resolves by the installed path. A pack that selects no skill is
# reported and changes nothing (exit 0). Installing a pack removes what an earlier pack installed
# and this one does not select, a dangling link to a renamed or removed skill included.
# Replaces or removes only what it made (its symlinks, or copies holding its marker file; the
# shared folder holds the marker in both modes). The marker it wrote before the rename,
# .installed-by-ai-workbench, still counts as its own (removed with T23). A folder of the same
# name that is not its own is skipped and reported, and the run exits 1. Exit 2 on a usage error.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
SKILLS="$ROOT/skills"
TARGET="$HOME/.agents/skills"
PACK="default" DRY=0 UNINSTALL=0 COPY=0
need() { [[ $# -ge 2 ]] || { echo "Error: $1 needs a value. See --help." >&2; exit 2; }; }
while [[ $# -gt 0 ]]; do
  case "$1" in
    --pack) need "$@"; PACK="$2"; shift 2 ;;
    --project) need "$@"; TARGET="$2/.agents/skills"; shift 2 ;;
    --copy) COPY=1; shift ;;
    --dry-run) DRY=1; shift ;;
    --uninstall) UNINSTALL=1; shift ;;
    --help|-h) sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Error: unknown option '$1'. See --help." >&2; exit 2 ;;
  esac
done
SHARED="$(dirname "$TARGET")/shared"
names=()
selected="$(python3 "$ROOT/scripts/select_skills.py" --pack "$PACK" --lines)" || exit 2
while IFS= read -r n; do [[ -n "$n" ]] && names+=("$n"); done <<< "$selected"
# One JSON line on stdout, built by a JSON writer so that a path holding a quote or a backslash
# stays valid JSON. Arguments: key=value (a string), key:=value (a number or true/false),
# key@=a line-separated list.
emit() {
  python3 - "$@" <<'PY'
import json, sys
out = {}
for arg in sys.argv[1:]:
    key, sep, value = arg.partition("=")
    if key.endswith(":"):
        out[key[:-1]] = json.loads(value)
    elif key.endswith("@"):
        out[key[:-1]] = [v for v in value.split("\n") if v]
    else:
        out[key] = value
print(json.dumps(out))
PY
}
joined() { local IFS=$'\n'; echo "$*"; }
MODE="$([[ $COPY -eq 1 ]] && echo copy || echo symlink)"
if [[ $DRY -eq 1 ]]; then
  emit "target=$TARGET" "shared=$SHARED" "pack=$PACK" "mode=$MODE" "uninstall:=$UNINSTALL" \
    "skills@=$(joined ${names[@]+"${names[@]}"})"
  exit 0
fi
if [[ $UNINSTALL -eq 0 && ${#names[@]} -eq 0 ]]; then
  echo "Pack '$PACK' selects no skill: nothing was installed and nothing was changed in $TARGET." >&2
  emit "target=$TARGET" "pack=$PACK" "installed:=0" "skipped@=" "uninstall:=0"
  exit 0
fi
# Only what this script made is replaced or removed: a symlink into this checkout's skills, or a
# folder holding the marker file. Anything else with the same name is the user's; it is skipped and
# reported, never deleted.
MARK=".installed-by-openhora"
LEGACY_MARK=".installed-by-ai-workbench"  # T23: what this installer wrote before the rename
marked() { [[ -f "$1/$MARK" || -f "$1/$LEGACY_MARK" ]]; }
ours() {
  if [[ -L "$1" ]]; then [[ "$(readlink -- "$1")" == "$SKILLS/"* ]]; return; fi
  [[ -d "$1" ]] && marked "$1"
}
remove_ours() {
  if [[ -L "$1" ]]; then rm -f -- "$1"; elif [[ -d "$1" ]]; then rm -rf -- "${1:?}"; fi
}
selects() {
  local n
  for n in ${names[@]+"${names[@]}"}; do [[ "$n" == "$1" ]] && return 0; done
  return 1
}
done_count=0 skipped=()
[[ $UNINSTALL -eq 1 ]] || mkdir -p "$TARGET"
# What an earlier run left and this one does not want: on an install, everything of ours outside the
# pack; on an uninstall, everything of ours.
stale=0
if [[ -d "$TARGET" ]]; then
  for dest in "$TARGET"/*; do
    [[ -e "$dest" || -L "$dest" ]] || continue
    ours "$dest" || continue
    if [[ $UNINSTALL -eq 0 ]] && selects "$(basename "$dest")"; then continue; fi
    remove_ours "$dest"
    if [[ $UNINSTALL -eq 1 ]]; then done_count=$((done_count + 1)); else stale=$((stale + 1)); fi
  done
fi
for n in ${names[@]+"${names[@]}"}; do
  dest="$TARGET/$n" src="$SKILLS/$n"
  if [[ -e "$dest" || -L "$dest" ]] && ! ours "$dest"; then
    echo "Skipped $dest: it exists and this installer did not create it. Move it away and run again." >&2
    skipped+=("$n")
    continue
  fi
  [[ $UNINSTALL -eq 1 ]] && continue
  remove_ours "$dest"
  if [[ $COPY -eq 1 ]]; then cp -R "$src" "$dest" && : > "$dest/$MARK"; else ln -s "$src" "$dest"; fi
  done_count=$((done_count + 1))
done
# The shared folder: a real folder holding the marker in both modes, with `references` inside it
# (a link into the checkout, or a copy with --copy). A `shared` this installer did not make is the
# user's or another tool's: it is left alone and reported.
shared_state="absent"
if [[ -e "$SHARED" || -L "$SHARED" ]] && { [[ -L "$SHARED" ]] || ! marked "$SHARED"; }; then
  echo "Skipped $SHARED: it exists and this installer did not create it, so the shared references were not installed. Move it away and run again." >&2
  skipped+=("shared")
  shared_state="skipped"
else
  [[ -d "$SHARED" ]] && { rm -rf -- "${SHARED:?}"; shared_state="removed"; }
  if [[ $UNINSTALL -eq 0 ]]; then
    mkdir -p "$SHARED"
    : > "$SHARED/$MARK"
    if [[ $COPY -eq 1 ]]; then cp -R "$ROOT/shared/references" "$SHARED/references"; else ln -s "$ROOT/shared/references" "$SHARED/references"; fi
    shared_state="installed"
  fi
fi
emit "target=$TARGET" "pack=$PACK" "$([[ $UNINSTALL -eq 1 ]] && echo removed || echo installed):=$done_count" \
  "stale_removed:=$stale" "shared=$shared_state" "skipped@=$(joined ${skipped[@]+"${skipped[@]}"})" \
  "uninstall:=$UNINSTALL"
[[ ${#skipped[@]} -eq 0 ]] || exit 1
