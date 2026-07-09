#!/bin/bash
# Double-click ONCE to turn on the daily automatic Gmail fetch (runs ~11:15 AM).
# Double-click "Stop Daily Email Schedule.command" to turn it back off.

cd "$(dirname "$0")" || exit 1
LABEL="com.warehouse.gmailfetch"
AGENTS="$HOME/Library/LaunchAgents"
PLIST="$AGENTS/$LABEL.plist"
WRAPPER="$(pwd)/fetch_and_refresh.command"
LOGDIR="$(pwd)/logs"

mkdir -p "$AGENTS" "$LOGDIR"

# Fill the template's placeholders with real absolute paths.
sed -e "s#__WRAPPER__#$WRAPPER#g" -e "s#__LOGDIR__#$LOGDIR#g" \
    config/com.warehouse.gmailfetch.plist > "$PLIST"

# Reload (unload first in case it was already installed).
launchctl unload "$PLIST" 2>/dev/null
launchctl load "$PLIST" && \
  echo "✅ Daily fetch is ON. It will run every day at 11:15 AM." || \
  echo "⚠️ Could not load the schedule. See the message above."

echo
echo "It runs automatically only while your Mac is awake at 11:15 AM."
echo "You can always click 'Pull from Gmail' in the dashboard to update now."
