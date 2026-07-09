#!/bin/bash
# Downloads today's Catalyst/MLG/Novo reports from Gmail and rebuilds the data.
# Used two ways: double-click to run now, AND run automatically each morning by
# the daily schedule (com.warehouse.gmailfetch). Safe to run anytime.

cd "$(dirname "$0")" || exit 1
mkdir -p logs

# Load Gmail + API credentials (local-only, git-ignored).
if [ -f config/secrets.env ]; then set -a; . config/secrets.env; set +a; fi

# Find a python3 (launchd has a bare PATH, so check common spots).
PY=""
for cand in "$HOME/anaconda3/bin/python3" "/opt/homebrew/bin/python3" \
            "/usr/local/bin/python3" "$(command -v python3 2>/dev/null)"; do
  [ -x "$cand" ] && PY="$cand" && break
done
[ -z "$PY" ] && { echo "python3 not found"; exit 1; }

echo "$(date '+%Y-%m-%d %H:%M:%S')  running Gmail fetch + pipeline…"
"$PY" src/gmail_fetch.py
echo "Done. See logs/ for details."
