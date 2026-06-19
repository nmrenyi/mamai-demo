#!/usr/bin/env bash
# Launch the demo locally: llama-server (Q4_0 GGUF, Metal) + FastAPI backend.
# Ctrl-C stops both.
set -euo pipefail
cd "$(dirname "$0")/.."

PY="${PY:-$HOME/miniforge3/bin/python3}"
GGUF="${MAMAI_GGUF_MODEL:-assets/gemma-3n-E4B-it-Q4_0.gguf}"
LLAMA_PORT="${LLAMA_PORT:-8080}"
APP_PORT="${APP_PORT:-8000}"
N_CTX="${MAMAI_N_CTX:-4096}"
NGL="${NGL:-999}"   # offload all layers to Metal GPU; set 0 for CPU-only

if [ ! -f "$GGUF" ]; then echo "Missing $GGUF — run scripts/fetch_assets.sh first."; exit 1; fi

echo "==> starting llama-server on :$LLAMA_PORT"
llama-server -m "$GGUF" --host 127.0.0.1 --port "$LLAMA_PORT" \
  -c "$N_CTX" -ngl "$NGL" --no-webui > /tmp/mamai_llama.log 2>&1 &
LLAMA_PID=$!
trap 'kill $LLAMA_PID 2>/dev/null || true' EXIT

echo "==> waiting for llama-server health…"
for i in $(seq 1 120); do
  if curl -sf "http://127.0.0.1:$LLAMA_PORT/health" >/dev/null 2>&1; then echo "llama-server ready."; break; fi
  if ! kill -0 $LLAMA_PID 2>/dev/null; then echo "llama-server died — see /tmp/mamai_llama.log"; tail -20 /tmp/mamai_llama.log; exit 1; fi
  sleep 1
done

export MAMAI_LLAMA_URL="http://127.0.0.1:$LLAMA_PORT"
echo "==> starting FastAPI on :$APP_PORT  →  http://127.0.0.1:$APP_PORT"
"$PY" -m uvicorn backend.app:app --host 0.0.0.0 --port "$APP_PORT"
