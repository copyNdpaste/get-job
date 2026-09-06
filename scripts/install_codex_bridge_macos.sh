#!/bin/sh
set -eu

LABEL="com.jobradar.codex-bridge"
PORT="${CODEX_BRIDGE_PORT:-48765}"
MODEL="${CODEX_BRIDGE_MODEL:-gpt-5.6-luna}"
REVIEW_MODEL="${CODEX_BRIDGE_REVIEW_MODEL:-gpt-5.6-terra}"
ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
BRIDGE="$ROOT_DIR/scripts/codex_bridge.py"
INSTALL_DIR="$HOME/Library/Application Support/JobRadar"
INSTALLED_BRIDGE="$INSTALL_DIR/codex_bridge.py"
CODEX_BIN="${CODEX_BIN:-/Applications/ChatGPT.app/Contents/Resources/codex}"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"

if [ ! -x "$CODEX_BIN" ]; then
  echo "Codex CLI를 찾을 수 없습니다: $CODEX_BIN" >&2
  exit 1
fi

mkdir -p "$HOME/Library/LaunchAgents" "$INSTALL_DIR"
/bin/cp "$BRIDGE" "$INSTALLED_BRIDGE"
launchctl bootout "$DOMAIN" "$PLIST" 2>/dev/null || true
/usr/bin/plutil -create xml1 "$PLIST"
/usr/bin/plutil -insert Label -string "$LABEL" "$PLIST"
ARGS_JSON=$(/usr/bin/python3 -c 'import json,sys; print(json.dumps(sys.argv[1:]))' /usr/bin/python3 "$INSTALLED_BRIDGE" --codex "$CODEX_BIN" --model "$MODEL" --allowed-model "$REVIEW_MODEL" --port "$PORT")
/usr/bin/plutil -insert ProgramArguments -json "$ARGS_JSON" "$PLIST"
/usr/bin/plutil -insert WorkingDirectory -string "$INSTALL_DIR" "$PLIST"
/usr/bin/plutil -insert RunAtLoad -bool true "$PLIST"
/usr/bin/plutil -insert KeepAlive -bool true "$PLIST"
/usr/bin/plutil -insert ProcessType -string Interactive "$PLIST"
/usr/bin/plutil -insert StandardOutPath -string /tmp/get-job-codex-bridge.log "$PLIST"
/usr/bin/plutil -insert StandardErrorPath -string /tmp/get-job-codex-bridge.error.log "$PLIST"
ENV_JSON=$(/usr/bin/python3 -c 'import json,sys; print(json.dumps({"HOME":sys.argv[1],"CODEX_HOME":sys.argv[1]+"/.codex","PATH":"/usr/bin:/bin:/usr/sbin:/sbin:/Applications/ChatGPT.app/Contents/Resources","PYTHONUNBUFFERED":"1"}))' "$HOME")
/usr/bin/plutil -insert EnvironmentVariables -json "$ENV_JSON" "$PLIST"
/usr/bin/plutil -lint "$PLIST"
launchctl bootstrap "$DOMAIN" "$PLIST"
launchctl kickstart -k "$DOMAIN/$LABEL"
echo "Codex GPT bridge installed on 127.0.0.1:$PORT"
