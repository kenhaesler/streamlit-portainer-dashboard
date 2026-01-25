#!/usr/bin/env bash
set -euo pipefail

# FastAPI/Uvicorn startup check script
UVICORN_CMD=(
  python -m uvicorn
    portainer_dashboard.main:app
    --host 127.0.0.1
    --port 8000
)

"${UVICORN_CMD[@]}" &
APP_PID=$!

cleanup() {
  if kill -0 "$APP_PID" 2>/dev/null; then
    kill "$APP_PID" 2>/dev/null || true
    wait "$APP_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

for _ in $(seq 1 30); do
  if curl -sf http://127.0.0.1:8000/health >/dev/null; then
    echo "FastAPI app responded successfully."
    exit 0
  fi

  if ! kill -0 "$APP_PID" 2>/dev/null; then
    echo "Uvicorn process exited before health check succeeded." >&2
    exit 1
  fi

  sleep 1
done

echo "Timed out waiting for FastAPI health endpoint." >&2
exit 1
