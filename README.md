# MAM-AI — Clinician-Feedback Demo

A hosted web demo of the **MAM-AI** clinical decision-support app for nurse-midwives
in Zanzibar. It exists so clinicians can try the system with realistic queries and
tell us **where it helps and where it fails** — feedback that feeds the prompt /
retrieval improvement work (G1/G2 in the improvement plan).

It implements the *"Faithful clinician-feedback demo (hosted)"* item from
`mamai-eval` improvement plan §5.

## Fidelity — what this mirrors

The demo is built to behave like the deployed on-device app, not better or worse:

| Aspect | Demo | Deployed app |
|---|---|---|
| Generator | Gemma 3n E4B, **Q4_0 GGUF** via `llama-server` | Gemma 3n E4B int4 `.litertlm` on device |
| Retriever | **EmbeddingGemma-300M** (TFLite, query mode) | same |
| Vector store | `rag-bundle-v0.3.0` (63,650 chunks, 87 sources) | same |
| Prompt | `system_en.txt` (config-v0.2.0) | same |
| Gen params | temp 1.0 · top_p 0.95 · top_k 64 · n_ctx 4096 | same |
| Context injection | `RELEVANT CONTEXT…` / `Question:` · `Document N:` blocks · top-3 · threshold 0.0 | same |
| Conversational retrieval | **latest-turn only** (device parity) | same |

### Fidelity caveats (also shown in the UI)
- **Q4_0 GGUF ≠ the literal `.litertlm`.** It's ~4-bit but a different quantization;
  validated (`device-vs-host-fidelity-20260611`) to track the device build closely and
  *slightly pessimistically* (the demo never looks better than the phone).
- **Server latency ≠ a phone.** Don't read timing from this demo.
- For bit-identical parity you'd serve the on-device `.litertlm` via the LiteRT-LM
  runtime instead of `llama-server` (heavier to stand up; not needed for feedback).

> **Demonstration only — not medical advice.** The UI gates entry behind this notice.

## Architecture

```
Browser (chat UI + disclaimer gate + per-response feedback form)
   │  POST /api/chat  (SSE stream)
   ▼
FastAPI (backend/)
  ├ retrieval.py   EmbeddingGemma query embed → cosine top-3 over embeddings.sqlite
  ├ prompts.py     system_en.txt + context injection + Gemma IT template
  ├ app.py         proxy → llama-server /completion (stream), feedback endpoints
  └ feedback.py    SQLite: exchanges + feedback
   │
   ▼
llama-server  (Q4_0 GGUF, Metal/CPU)
```

## Run locally

```bash
# 1. Python deps (Python 3.10)
pip install -r requirements.txt

# 2. Fetch model assets into ./assets (EmbeddingGemma + Q4_0 GGUF; links local store + prompt)
bash scripts/fetch_assets.sh

# 3. Launch llama-server + FastAPI  →  http://127.0.0.1:8000
bash scripts/run.sh
```

`scripts/run.sh` offloads all layers to the Metal GPU by default (`NGL=999`); set
`NGL=0` for CPU-only. Override ports with `APP_PORT` / `LLAMA_PORT`.

## Configuration

All paths and params are env-overridable (see `backend/config.py`) so the same code
runs locally and in the cloud. Key vars: `MAMAI_LLAMA_URL`, `MAMAI_GGUF_MODEL`,
`MAMAI_VECTOR_DB`, `MAMAI_SYSTEM_PROMPT`, `MAMAI_ASSETS_DIR`.

## Feedback data

Stored in `feedback.sqlite` (gitignored):
- `exchanges` — query, retrieved context, citations, full response per message.
- `feedback` — clinician rating (1–5), issue tags, free-text comment, keyed by message.

## Deployment

Local-first; cloud migration is infra-only (no code changes — config is env-driven).
See the deployment notes for hosting options for a ~4.3 GB GGUF + `llama-server`.
