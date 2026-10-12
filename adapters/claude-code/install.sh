#!/usr/bin/env bash
# Install openhora into Claude Code as a plugin.
#
# Usage: bash adapters/claude-code/install.sh [--pack <name>] [--dry-run] [--uninstall]
#          [--listing-budget print|write|skip] [--project <dir>] [--settings-scope project|local|user]
#
# Builds build/<pack>/ (a plugin folder with symlinked skills, the shared references beside them
# and generated agents), then symlinks it to ~/.claude/skills/openhora (CLAUDE_SKILLS_DIR
# replaces ~/.claude/skills). Claude Code loads any folder under a skills directory that contains
# .claude-plugin/plugin.json as a plugin on the next session.
# Default pack: default (every area except optional ones). See packs/README.md.
# One pack is installed at a time: an install removes the builds of other packs, --uninstall
# removes the link and every build. A pack that selects no skill is reported and changes nothing.
# Compatibility stage of the rename (removed with T23): a link named ai-workbench under the same skills
# directory that points into this checkout's build/ is the plugin as it was called before; an install
# removes it (and says so) so that two plugins do not load, and --uninstall removes either link.
# When the linked folder is not picked up, load the build for one session instead:
#   claude --plugin-dir adapters/claude-code/build/<pack>
# The skill listing: Claude Code lists skills within a character budget, SLASH_COMMAND_TOOL_CHAR_BUDGET,
# and lists those past it by name only. The install computes the budget the pack needs and, by
# default (--listing-budget print), prints the line to add and the file it goes in, writing nothing.
# --listing-budget write merges it into the settings file of --settings-scope, with a backup:
# project (<dir>/.claude/settings.json, the default) or local (<dir>/.claude/settings.local.json),
# both with --project <dir>; user (~/.claude/settings.json) only when named. --uninstall puts back
# what it wrote, where the value is still the one written. See listing_budget.py --help.
# Exit codes: 0 ok, 1 the target exists and is not this installer's, or a settings file was
# refused, 2 usage error.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
SKILLS_HOME="${CLAUDE_SKILLS_DIR:-$HOME/.claude/skills}"
TARGET="$SKILLS_HOME/openhora"
LEGACY_TARGET="$SKILLS_HOME/ai-workbench"  # T23: the link of the installer before the rename
BUDGET="$HERE/listing_budget.py"
PACK="default" DRY=0 UNINSTALL=0 BUDGET_MODE="print" SCOPE="project" PROJECT=""
need() { [[ $# -ge 2 ]] || { echo "Error: $1 needs a value. See --help." >&2; exit 2; }; }
while [[ $# -gt 0 ]]; do
  case "$1" in
    --pack) need "$@"; PACK="$2"; shift 2 ;;
    --dry-run) DRY=1; shift ;;
    --uninstall) UNINSTALL=1; shift ;;
    --listing-budget) need "$@"; BUDGET_MODE="$2"; shift 2 ;;
    --settings-scope) need "$@"; SCOPE="$2"; shift 2 ;;
    --project) need "$@"; PROJECT="$2"; shift 2 ;;
    --help|-h) sed -n '2,27p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Error: unknown option '$1'. See --help." >&2; exit 2 ;;
  esac
done
case "$BUDGET_MODE" in print|write|skip) ;; *) echo "Error: --listing-budget takes print, write or skip. See --help." >&2; exit 2 ;; esac
case "$SCOPE" in project|local|user) ;; *) echo "Error: --settings-scope takes project, local or user. See --help." >&2; exit 2 ;; esac
if [[ $BUDGET_MODE == write && $SCOPE != user && -z "$PROJECT" ]]; then
  echo "Error: --listing-budget write needs --project <dir> (or --settings-scope user). See --help." >&2; exit 2
fi
# One JSON line on stdout, built by a JSON writer so that a path holding a quote or a backslash
# stays valid JSON. Arguments: key=value (a string), key:=value (JSON: a number, true, false, null
# or the object a helper printed).
emit() {
  python3 - "$@" <<'PY'
import json, sys
out = {}
for arg in sys.argv[1:]:
    key, sep, value = arg.partition("=")
    out[key[:-1] if key.endswith(":") else key] = json.loads(value) if key.endswith(":") else value
print(json.dumps(out))
PY
}
# Only a link into this adapter's build folder is ours to replace or remove.
ours() { [[ -L "$TARGET" && "$(readlink -- "$TARGET")" == "$HERE/build/"* ]]; }
legacy_ours() { [[ -L "$LEGACY_TARGET" && "$(readlink -- "$LEGACY_TARGET")" == "$HERE/build/"* ]]; }
# Removes the old link when it is ours and says so; prints nothing on stdout.
remove_legacy() {
  legacy_ours || return 1
  rm -f -- "$LEGACY_TARGET"
  echo "Removed the old plugin link $LEGACY_TARGET: the plugin is now called openhora." >&2
}
budget_arg=()
if [[ $UNINSTALL -eq 1 ]]; then
  # The settings values this installer wrote are put back first: they are its own whatever the link is.
  undo_args=(undo); [[ $DRY -eq 1 ]] && undo_args+=(--dry-run)
  undo_status=0
  undone="$(python3 "$BUDGET" "${undo_args[@]}")" || undo_status=$?
  [[ -n "$undone" && "$undone" != "{}" ]] && budget_arg=("listing_budget:=$undone")
  legacy_arg=()
  if [[ $DRY -eq 1 ]]; then
    legacy_ours && legacy_arg=("would_remove_legacy=$LEGACY_TARGET")
    emit "would_remove=$TARGET" ${legacy_arg[@]+"${legacy_arg[@]}"} ${budget_arg[@]+"${budget_arg[@]}"}; exit 0
  fi
  # Either link is removed when it is ours; one that points elsewhere is left in place.
  remove_legacy && legacy_arg=("legacy_removed=$LEGACY_TARGET")
  if ours; then
    rm -f -- "$TARGET"
    python3 "$HERE/build.py" --clean >/dev/null
    emit "removed=$TARGET" ${legacy_arg[@]+"${legacy_arg[@]}"} ${budget_arg[@]+"${budget_arg[@]}"}; exit "$undo_status"
  fi
  [[ -e "$TARGET" || -L "$TARGET" ]] && { echo "Error: $TARGET was not created by this installer; left in place." >&2; exit 1; }
  python3 "$HERE/build.py" --clean >/dev/null
  emit "removed:=null" ${legacy_arg[@]+"${legacy_arg[@]}"} ${budget_arg[@]+"${budget_arg[@]}"}; exit "$undo_status"
fi
selected="$(python3 "$ROOT/scripts/select_skills.py" --pack "$PACK" --lines)" || exit 2
if [[ -z "$selected" ]]; then
  echo "Pack '$PACK' selects no skill: nothing was built and nothing was changed at $TARGET." >&2
  emit "pack=$PACK" "linked:=null" "skills:=0"; exit 0
fi
BUILD="$HERE/build/$PACK"
# The listing budget: printed, or merged into a settings file with --listing-budget write. Its JSON
# joins the installer's line under "listing_budget".
budget() {
  [[ $BUDGET_MODE == skip ]] && return 0
  local args=(apply --pack "$PACK" --scope "$SCOPE" --mode "$BUDGET_MODE")
  [[ -n "$PROJECT" ]] && args+=(--project "$PROJECT")
  [[ $DRY -eq 1 ]] && args+=(--dry-run)
  python3 "$BUDGET" "${args[@]}"
}
if [[ $DRY -eq 1 ]]; then
  python3 "$HERE/build.py" --pack "$PACK" --prune --dry-run
  b="$(budget)" || exit $?
  [[ -n "$b" ]] && budget_arg=("listing_budget:=$b")
  legacy_arg=()
  legacy_ours && legacy_arg=("would_remove_legacy=$LEGACY_TARGET")
  emit "would_link=$TARGET" "to=$BUILD" ${legacy_arg[@]+"${legacy_arg[@]}"} ${budget_arg[@]+"${budget_arg[@]}"}; exit 0
fi
if [[ -e "$TARGET" || -L "$TARGET" ]] && ! ours; then
  echo "Error: $TARGET exists and was not created by this installer. Move it away or set CLAUDE_SKILLS_DIR." >&2; exit 1
fi
# Before the build, so that a settings file it refuses leaves everything as it was.
b="$(budget)" || exit $?
[[ -n "$b" ]] && budget_arg=("listing_budget:=$b")
python3 "$HERE/build.py" --pack "$PACK" --prune >/dev/null
mkdir -p "$(dirname "$TARGET")"
ln -sfn "$BUILD" "$TARGET"
# The plugin loaded once under its old name: take that link away now that the new one exists.
legacy_arg=()
remove_legacy && legacy_arg=("legacy_removed=$LEGACY_TARGET")
emit "linked=$TARGET" "to=$BUILD" "pack=$PACK" \
  "next=restart the session; the plugin loads as openhora@skills-dir" \
  "fallback=claude --plugin-dir $BUILD" ${legacy_arg[@]+"${legacy_arg[@]}"} ${budget_arg[@]+"${budget_arg[@]}"}
