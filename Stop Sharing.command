#!/bin/bash
# Double-click to stop sharing the dashboard (takes the public link offline).
cd "$(dirname "$0")" || exit 1
pkill -f "streamlit run src/dashboard.py" 2>/dev/null
pkill -f "cloudflared tunnel" 2>/dev/null
echo "Sharing stopped. The public link is now offline."
sleep 2
