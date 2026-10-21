#!/usr/bin/env bash
# The text contract of this adapter (contracts/runtime.md, "The text contract"): one system text and one user text in
# (a JSON object on stdin), one reply out (a JSON object on stdout).
#
# Usage: run-text.sh --model <id>
#        run-text.sh --probe --model <id> --max-tokens <n> --reasoning <r> [--repeat N]
#
# The work is in run_text.py beside this file; `run-text.sh --help` prints its description.
set -euo pipefail
exec python3 "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/run_text.py" "$@"
