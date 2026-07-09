#!/bin/bash
# Double-click to share the dashboard with a stakeholder via a temporary public link.
# Keep this window open and your Mac awake while they review. Double-click
# "Stop Sharing.command" when you're done.
#
# NOTE: the public link changes every time you start sharing — send the NEW link
# (and the password) shown below each time.

cd "$(dirname "$0")" || exit 1
mkdir -p logs .tools

# stop any previous share
pkill -f "streamlit run src/dashboard.py" 2>/dev/null
pkill -f "cloudflared tunnel" 2>/dev/null
sleep 2

# stable access password (reused across restarts so it stays the same for Armando)
if [ ! -f .tools/share_password.txt ]; then
  python3 -c "import random; print('americhine-'+str(random.randint(1000,9999)))" > .tools/share_password.txt
fi
PW="$(cat .tools/share_password.txt)"

# load the Anthropic API key (for the Ask tab) if present
if [ -f config/secrets.env ]; then set -a; . config/secrets.env; set +a; fi
export SHARE_PASSWORD="$PW"

echo "Starting the shared dashboard…"
nohup python3 -m streamlit run src/dashboard.py \
  --server.headless true --server.port 8520 \
  --server.enableCORS false --server.enableXsrfProtection false \
  --browser.gatherUsageStats false > logs/share_streamlit.log 2>&1 &
sleep 8

echo "Opening the public link…"
nohup .tools/cloudflared tunnel --url http://localhost:8520 > logs/cloudflared.log 2>&1 &

# wait for the public URL to appear
URL=""
for i in $(seq 1 20); do
  URL=$(grep -Eo "https://[a-zA-Z0-9.-]+\.trycloudflare\.com" logs/cloudflared.log | head -1)
  [ -n "$URL" ] && break
  sleep 1
done

echo
echo "=================================================================="
echo "  SHARE THESE TWO THINGS WITH ARMANDO:"
echo
echo "  Link:     ${URL:-（still starting — check logs/cloudflared.log）}"
echo "  Password: $PW"
echo
echo "  The link works only while this window stays open and your Mac is"
echo "  awake. Double-click \"Stop Sharing.command\" when finished."
echo "=================================================================="
echo
echo "(Keep this window open. Press Ctrl-C or run Stop Sharing to end.)"
# keep the window/process alive
wait
