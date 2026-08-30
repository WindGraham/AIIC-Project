#!/usr/bin/env bash
# One-shot build/start for ProbeDesk. Run on the server AFTER copying the repo
# and filling .env. Requires: python3, pnpm, and (optional) systemd/nginx.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "== build agent =="
cd "$ROOT/apps/agent"
python3 -m venv .venv 2>/dev/null || true
.venv/bin/pip install -e . >/dev/null

echo "== build web =="
cd "$ROOT/apps/web"
pnpm install >/dev/null
pnpm build

echo "== run =="
echo "agent:  cd $ROOT/apps/agent && PYTHONPATH=src .venv/bin/python -m uvicorn agent.main:app --port 8000"
echo "web:    cd $ROOT/apps/web && next start -p 3101   (AGENT_API_URL=http://127.0.0.1:8000)"
echo "systemd: sudo cp deploy/aiic-agent.service deploy/aiic-web.service /etc/systemd/system/ && sudo systemctl enable --now aiic-agent aiic-web"
echo "nginx:   edit deploy/nginx.conf server_name, then enable + reload (certbot for HTTPS)"
