#!/usr/bin/env bash
# Container entrypoint: start llama-server (CPU), wait for health, then uvicorn.
set -euo pipefail
cd "$(dirname "$0")/.."

PORT="${PORT:-7860}"
LLAMA_PORT="${LLAMA_PORT:-8080}"
GGUF="${MAMAI_GGUF_MODEL:-assets/gemma-4-E4B-it-Q4_0.gguf}"
N_CTX="${MAMAI_N_CTX:-4096}"
THREADS="${THREADS:-$(nproc)}"

# Persist feedback to /data when a volume is mounted (paid Spaces / VPS).
if [ -d /data ] && [ -w /data ]; then
  export MAMAI_FEEDBACK_DB="${MAMAI_FEEDBACK_DB:-/data/feedback.sqlite}"
fi

echo "==> starting llama-server (CPU, ${THREADS} threads) on :${LLAMA_PORT}"
llama-server -m "$GGUF" --host 127.0.0.1 --port "$LLAMA_PORT" \
  -c "$N_CTX" -t "$THREADS" --no-webui > /tmp/llama.log 2>&1 &
LLAMA_PID=$!

echo "==> waiting for llama-server health…"
for i in $(seq 1 300); do
  if curl -sf "http://127.0.0.1:${LLAMA_PORT}/health" >/dev/null 2>&1; then echo "ready after ${i}s"; break; fi
  if ! kill -0 "$LLAMA_PID" 2>/dev/null; then echo "llama-server died:"; tail -30 /tmp/llama.log; exit 1; fi
  sleep 1
done

export MAMAI_LLAMA_URL="http://127.0.0.1:${LLAMA_PORT}"
echo "==> starting FastAPI on :${PORT}"
exec python -m uvicorn backend.app:app --host 0.0.0.0 --port "$PORT"
