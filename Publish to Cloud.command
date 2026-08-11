#!/bin/bash
# Double-click to publish the current local data to the always-on cloud dashboard.
# (Refresh the dashboard first so the numbers are current.)
cd "$(dirname "$0")" || exit 1
if [ -f config/secrets.env ]; then set -a; . config/secrets.env; set +a; fi
PY=""
for cand in "$HOME/anaconda3/bin/python3" "/opt/homebrew/bin/python3" \
            "/usr/local/bin/python3" "$(command -v python3 2>/dev/null)"; do
  [ -x "$cand" ] && PY="$cand" && break
done
"$PY" src/publish_snapshot.py --push
echo
echo "Done. If the push couldn't run, open GitHub Desktop and click Push."
read -r -p "Press Return to close."
