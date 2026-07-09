#!/bin/bash
# Double-click to turn OFF the daily automatic Gmail fetch.
LABEL="com.warehouse.gmailfetch"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
launchctl unload "$PLIST" 2>/dev/null
rm -f "$PLIST"
echo "🛑 Daily fetch is OFF. (You can still use the 'Pull from Gmail' button.)"
sleep 1
