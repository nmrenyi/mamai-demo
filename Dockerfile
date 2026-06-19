# MAM-AI clinician-feedback demo — single-container image.
# Stage 1 builds a static llama-server (CPU); stage 2 adds the Python app and
# bakes the model assets into the image so cold-wake on HF Spaces is fast
# (no 4.3 GB runtime download). Works on HF Spaces (Docker SDK) and any VPS.

# ---------- stage 1: build llama-server (static, CPU) ----------
FROM python:3.10-slim AS llama
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential cmake git ca-certificates && rm -rf /var/lib/apt/lists/*
RUN git clone --depth 1 https://github.com/ggml-org/llama.cpp /src
WORKDIR /src
# Static link so the single binary is self-contained; GGML_NATIVE=OFF + AVX2 for
# a portable build (HF build host CPU features may differ from the runtime host).
RUN cmake -B build -DCMAKE_BUILD_TYPE=Release \
        -DLLAMA_CURL=OFF -DBUILD_SHARED_LIBS=OFF \
        -DGGML_NATIVE=OFF -DGGML_AVX2=ON \
 && cmake --build build --config Release -j --target llama-server \
 && cp build/bin/llama-server /usr/local/bin/llama-server

# ---------- stage 2: runtime ----------
FROM python:3.10-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
      libgomp1 curl ca-certificates && rm -rf /var/lib/apt/lists/*
COPY --from=llama /usr/local/bin/llama-server /usr/local/bin/llama-server

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt "huggingface_hub[cli]"

COPY backend/ backend/
COPY frontend/ frontend/
COPY deploy/ deploy/

# Bake assets into the image (current deploy: EmbeddingGemma v0.3.0 + Q4_0 GGUF).
RUN mkdir -p assets \
 && hf download nmrenyi/embeddinggemma-300m-litert-mamai \
      embeddinggemma-300M_seq256_mixed-precision.tflite sentencepiece.model --local-dir assets/ \
 && hf download unsloth/gemma-3n-E4B-it-GGUF gemma-3n-E4B-it-Q4_0.gguf --local-dir assets/ \
 && curl -fL -o /tmp/bundle.tar.gz \
      https://github.com/nmrenyi/mamai-medical-guidelines/releases/download/v0.3.0/rag-bundle-v0.3.0.tar.gz \
 && tar -xzf /tmp/bundle.tar.gz -C /tmp \
 && cp /tmp/rag-bundle-v0.3.0/runtime/embeddings.sqlite assets/embeddings.sqlite \
 && cp deploy/system_en.txt assets/system_en.txt \
 && rm -rf /tmp/bundle.tar.gz /tmp/rag-bundle-v0.3.0

# HF Spaces routes to app_port (7860). Feedback DB at /data if a persistent
# volume is mounted (paid Spaces / VPS); otherwise ephemeral in the container.
ENV MAMAI_LLAMA_URL=http://127.0.0.1:8080 \
    PORT=7860 \
    HF_HUB_DISABLE_TELEMETRY=1
EXPOSE 7860
CMD ["bash", "deploy/start.sh"]
