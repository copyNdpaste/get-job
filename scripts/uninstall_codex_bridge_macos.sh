#!/bin/sh
set -eu

LABEL="com.jobradar.codex-bridge"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"
INSTALL_DIR="$HOME/Library/Application Support/JobRadar"

launchctl bootout "$DOMAIN" "$PLIST" 2>/dev/null || true
if [ -f "$PLIST" ]; then
  /bin/rm "$PLIST"
fi
if [ -f "$INSTALL_DIR/codex_bridge.py" ]; then
  /bin/rm "$INSTALL_DIR/codex_bridge.py"
fi
rmdir "$INSTALL_DIR" 2>/dev/null || true
echo "Codex GPT bridge removed"
