#!/usr/bin/env bash
# An isolated OpenClaw gateway for filming ClawReflex: its own state, workspace and port,
# only the cerebras and clawreflex plugins, no channels (your own gateway and chats are untouched).
#   bash clawreflex/stage.sh start   # prints the Control UI URL (token in the fragment; keep it off screen)
#   bash clawreflex/stage.sh stop
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STAGE="${CLAWREFLEX_STAGE:-$ROOT/out/clawreflex/stage}"
PORT="${CLAWREFLEX_STAGE_PORT:-18790}"
export OPENCLAW_STATE_DIR="$STAGE/state" OPENCLAW_CONFIG_PATH="$STAGE/openclaw.json"

case "${1:-}" in
start)
  mkdir -p "$STAGE/workspace" "$STAGE/agent"
  [ -s "$STAGE/gwtoken" ] || head -c 18 /dev/urandom | xxd -p > "$STAGE/gwtoken"
  [ -s "$STAGE/tooltoken" ] || head -c 24 /dev/urandom | xxd -p > "$STAGE/tooltoken"
  python3 - "$STAGE" "$PORT" "$ROOT" <<'PY'
import json, os, sys
stage, port, root = sys.argv[1], int(sys.argv[2]), sys.argv[3]
user = json.load(open(os.path.expanduser("~/.openclaw/openclaw.json")))
model = user["agents"]["defaults"]["model"]
config = {
    "gateway": {"mode": "local", "port": port, "bind": "loopback", "auth": {"mode": "token"}, "tailscale": {"mode": "off"}},
    "plugins": {"entries": {"cerebras": {"enabled": True}, "clawreflex": {"enabled": True}},
                "load": {"paths": [root + "/clawreflex/openclaw"]}, "allow": ["cerebras", "clawreflex"]},
    "tools": {"profile": "full"},
    "models": user["models"],
    "agents": {"defaults": {"model": model, "workspace": stage + "/workspace", "thinkingDefault": "low"},
               "entries": {"main": {"name": "ClawReflex", "workspace": stage + "/workspace", "agentDir": stage + "/agent",
                                    "identity": {"name": "ClawReflex"}}}},
}
path = stage + "/openclaw.json"
config["models"]["providers"]["cerebras"]["apiKey"] = "${CEREBRAS_API_KEY}"  # from .env, never copied into the stage
json.dump(config, open(path, "w"), indent=1)
os.chmod(path, 0o600)
PY
  # The workspace persona: what the agent reads before every turn.
  cat > "$STAGE/workspace/AGENTS.md" <<'MD'
# ClawReflex
You guard one repository. When a save arrives, prove the bug with clawreflex_probe, then repair it with clawreflex_patch.
Never claim success unless clawreflex_patch returns ok=true and applied=true. Be brief: one short line per step.
MD
  : > "$STAGE/workspace/SOUL.md"; : > "$STAGE/workspace/USER.md"; : > "$STAGE/workspace/TOOLS.md"; : > "$STAGE/workspace/IDENTITY.md"
  set -a; . "$ROOT/.env"; set +a
  CLAWREFLEX_URL="http://127.0.0.1:$((PORT + 1))" CLAWREFLEX_TOKEN="$(cat "$STAGE/tooltoken")" \
  OPENCLAW_GATEWAY_TOKEN="$(cat "$STAGE/gwtoken")" \
    setsid openclaw gateway run --port "$PORT" --auth token --bind loopback > "$STAGE/gateway.log" 2>&1 < /dev/null &
  echo $! > "$STAGE/gateway.pid"
  for _ in $(seq 60); do curl -sf -o /dev/null "http://127.0.0.1:$PORT/" && break; sleep 1; done
  echo "http://127.0.0.1:$PORT/#token=$(cat "$STAGE/gwtoken")"
  ;;
fresh)  # an empty chat for the next take: the old state is moved aside, never deleted
  bash "$0" stop; sleep 2
  [ -d "$STAGE/state" ] && mv "$STAGE/state" "$STAGE/state-$(date -u +%Y%m%dT%H%M%SZ)"
  [ -d "$STAGE/chrome-profile" ] && mv "$STAGE/chrome-profile" "$STAGE/chrome-profile-$(date -u +%Y%m%dT%H%M%SZ)"
  exec bash "$0" start
  ;;
stop)
  [ -s "$STAGE/gateway.pid" ] && kill -- -"$(cat "$STAGE/gateway.pid")" 2>/dev/null || true
  rm -f "$STAGE/gateway.pid"
  ;;
*) echo "usage: $0 start|stop|fresh" >&2; exit 2 ;;
esac
