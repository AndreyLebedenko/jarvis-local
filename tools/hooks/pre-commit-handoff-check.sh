#!/bin/sh
# jarvis-handoff-hook-start
# Handoff self-sufficiency gate (Testing protocol item 4, AGENTS.md/CLAUDE.md).
# Checks staged tasks/**.md handoff sections: a handoff that mentions hotkeys
# must name the literal binding. Installed by tools/install_handoff_hook.ps1.
# Bypass (emergency only): JARVIS_SKIP_HANDOFF_CHECK=1

if [ "${JARVIS_SKIP_HANDOFF_CHECK:-0}" = "1" ]; then
    exit 0
fi

# Skip during rebase/merge/cherry-pick
GIT_DIR=$(git rev-parse --git-dir 2>/dev/null)
[ -d "$GIT_DIR/rebase-merge" ] && exit 0
[ -d "$GIT_DIR/rebase-apply" ] && exit 0
[ -f "$GIT_DIR/MERGE_HEAD" ] && exit 0
[ -f "$GIT_DIR/CHERRY_PICK_HEAD" ] && exit 0

changed=$(git diff --cached --name-only --diff-filter=ACMR -- 'tasks/*.md' 'tasks/**/*.md')
if [ -z "$changed" ]; then
    exit 0
fi

# Locate a repository Python (project venv first, then PATH).
PYTHON=""
if [ -x ".venv/Scripts/python.exe" ]; then
    PYTHON=".venv/Scripts/python.exe"
elif command -v python >/dev/null 2>&1; then
    PYTHON=python
else
    echo "[handoff-check] no Python found; skipping check (not a pass)." >&2
    exit 0
fi

# shellcheck disable=SC2086
"$PYTHON" tools/check_handoff_self_sufficiency.py $changed