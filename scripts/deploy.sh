#!/usr/bin/env bash
# First-time setup / manual redeploy of the PlacidWay chatbot on the VPS.
# Usage: bash deploy.sh   (as root, or a user with docker rights)
set -euo pipefail

APP_DIR=/opt/pw-chatbot
REPO="${REPO_URL:-https://github.com/anasfauzi/pw-chatbot.git}"
IMAGE=pw-chatbot
PORT=8000

command -v docker >/dev/null || { echo "install docker first: curl -fsSL https://get.docker.com | sh"; exit 1; }
command -v git >/dev/null || apt-get install -y git

if [ -d "$APP_DIR/.git" ]; then
  (cd "$APP_DIR" && git pull --ff-only)
else
  git clone --depth 1 "$REPO" "$APP_DIR"
fi

if [ ! -f "$APP_DIR/.env" ]; then
  cat > "$APP_DIR/.env" << 'ENV'
LLM_PROVIDER=openrouter
LLM_API_KEY=PASTE_KEY_HERE
LLM_MODEL=minimax/minimax-m3.1-flash:free
REFRESH_TOKEN=
ENV
  echo "!! Created $APP_DIR/.env — set LLM_API_KEY (and a random REFRESH_TOKEN), then rerun."
  exit 1
fi
chmod 600 "$APP_DIR/.env"

# knowledge base is baked at build time; data/ survives rebuilds via the volume
docker build -t "$IMAGE" "$APP_DIR"
docker rm -f "$IMAGE" >/dev/null 2>&1 || true
docker run -d --restart unless-stopped --name "$IMAGE" \
  --env-file "$APP_DIR/.env" \
  -p "${PORT}:8000" \
  -v "$APP_DIR/data:/app/data" \
  "$IMAGE"

IP=$(hostname -I 2>/dev/null | awk '{print $1}')
echo "up: http://$IP:$PORT"
# optional TLS, after the DNS A record points at this machine:
# docker run -d --restart unless-stopped --name caddy -p 80:80 -p 443:443 \
#   -v caddy_data:/data caddy caddy reverse-proxy --from chat.anasfauzi.biz.id --to :8000
