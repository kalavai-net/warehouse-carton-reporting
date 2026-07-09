#!/bin/bash
# Double-click this file to launch the Warehouse Carton Reporting dashboard.
# It opens in your web browser. Close the Terminal window to stop it.

cd "$(dirname "$0")" || exit 1

echo "Starting the Warehouse Carton Reporting dashboard…"
echo "Your browser will open automatically. Keep this window open while using it."
echo

# Load the Anthropic API key for the Ask (Q&A) tab, if it has been set up.
# (config/secrets.env is local-only and never committed — see .gitignore.)
if [ -f config/secrets.env ]; then
  set -a
  . config/secrets.env
  set +a
fi

# Use python -m streamlit so it works even if 'streamlit' isn't on PATH.
python3 -m streamlit run src/dashboard.py --server.port 8520
