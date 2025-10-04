#!/usr/bin/env bash
set -euo pipefail

STREAMLIT_CMD=(
  streamlit run app/main.py \
    --server.headless true \
    --server.port 8501 \
    --server.address 127.0.0.1 \
    --browser.gatherUsageStats false \
    --server.fileWatcherType none
)

"${STREAMLIT_CMD[@]}" &
APP_PID=$!

cleanup() {
  if kill -0 "$APP_PID" 2>/dev/null; then
    kill "$APP_PID" 2>/dev/null || true
    wait "$APP_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

for _ in $(seq 1 30); do
  if curl -sf http://127.0.0.1:8501/_stcore/health >/dev/null; then
    echo "Streamlit app responded successfully."
    exit 0
  fi

  if ! kill -0 "$APP_PID" 2>/dev/null; then
    echo "Streamlit process exited before health check succeeded." >&2
    exit 1
  fi

  sleep 1
done

echo "Timed out waiting for Streamlit health endpoint." >&2
exit 1
