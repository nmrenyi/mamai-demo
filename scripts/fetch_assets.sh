#!/usr/bin/env bash
# Fetch the model assets for the demo into ./assets (current deploy: EmbeddingGemma
# v0.3.0 retriever + Gemma 4 E4B Q4_0 GGUF generator). Re-runnable; skips existing.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p assets

HF="${HF:-hf}"  # huggingface_hub CLI

echo "==> EmbeddingGemma-300M retriever (tflite + tokenizer)"
"$HF" download nmrenyi/embeddinggemma-300m-litert-mamai \
  embeddinggemma-300M_seq256_mixed-precision.tflite sentencepiece.model \
  --local-dir assets/

echo "==> Gemma 4 E4B Q4_0 GGUF generator (~4.84 GB)"
"$HF" download unsloth/gemma-4-E4B-it-GGUF gemma-4-E4B-it-Q4_0.gguf --local-dir assets/

# Vector store + system prompt: link the local repos if present, else instruct.
GUIDELINES="${GUIDELINES:-$HOME/Downloads/mamai-medical-guidelines}"
MAMAI="${MAMAI:-$HOME/Downloads/mamai}"
STORE="$GUIDELINES/releases/rag-bundle-v0.3.0/runtime/embeddings.sqlite"
PROMPT="$MAMAI/config/prompts/system_en.txt"

if [ -f "$STORE" ]; then ln -sf "$STORE" assets/embeddings.sqlite; echo "linked v0.3.0 vector store"; \
  else echo "!! embeddings.sqlite not found at $STORE — fetch rag-bundle-v0.3.0 from mamai-medical-guidelines releases"; fi
if [ -f "$PROMPT" ]; then ln -sf "$PROMPT" assets/system_en.txt; echo "linked system_en.txt"; \
  else echo "!! system_en.txt not found at $PROMPT"; fi

echo "==> assets:"; ls -laL assets/
