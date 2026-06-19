"""MAM-AI clinician-feedback demo — FastAPI backend.

Faithful to the deployed on-device app:
  - EmbeddingGemma-300M live retrieval (latest-turn only) over rag-bundle-v0.3.0
  - system_en.txt + deployed generation params
  - Gemma 3n E4B Q4_0 GGUF via llama-server (proxied here)

New pieces (per the improvement-plan §5 demo spec):
  - live retrieval endpoint, chat UI, click-through source citations, a persistent
    "not medical advice" banner, and an optional feedback form (flag-gated; off in
    the deployment image).
"""

import json
import os
import time
import uuid
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.responses import StreamingResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend import config, feedback
from backend.prompts import SYSTEM_PROMPT, build_prompt
from backend.retrieval import Retriever

app = FastAPI(title="MAM-AI clinician-feedback demo")

_retriever: Retriever | None = None
FRONTEND_DIR = config.REPO_ROOT / "frontend"


@app.on_event("startup")
def _startup() -> None:
    global _retriever
    if config.ENABLE_FEEDBACK:
        feedback.init_db()
    print("Loading EmbeddingGemma retriever + vector store…")
    _retriever = Retriever()
    print(f"Vector store ready: {len(_retriever.store)} chunks, dim={_retriever.store.dim}")


# ---------------------------------------------------------------- models

class Turn(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class ChatRequest(BaseModel):
    messages: list[Turn]
    session_id: str | None = None


class FeedbackRequest(BaseModel):
    message_id: str
    session_id: str | None = None
    rating: int | None = None          # 1-5 overall usefulness
    helpful: bool | None = None
    issues: list[str] = []             # structured tags
    comment: str | None = None


# ---------------------------------------------------------------- meta / health

@app.get("/api/meta")
def meta() -> dict:
    return {
        "stack": config.STACK_LABEL,
        "generator": config.GENERATOR_LABEL,
        "retriever": "EmbeddingGemma-300M (TFLite, query mode) · top-3 · threshold 0.0",
        "corpus": "rag-bundle-v0.3.0 · 63,650 chunks · 87 sources",
        "feedback_enabled": config.ENABLE_FEEDBACK,
        "docs_available": os.path.isdir(config.DOCS_DIR),
        "params": {"temperature": config.TEMPERATURE, "top_p": config.TOP_P,
                   "top_k": config.TOP_K, "n_ctx": config.N_CTX, "max_tokens": config.MAX_TOKENS},
        "caveats": [
            "Demonstration only — not medical advice.",
            "Q4_0 GGUF is ~4-bit but not the literal on-device .litertlm bundle; "
            "validated to track the device build closely and slightly pessimistically.",
            "Server latency does not match a phone.",
            "Conversational retrieval embeds only the latest turn, mirroring the device.",
        ],
    }


@app.get("/api/health")
async def health() -> JSONResponse:
    ready = _retriever is not None
    llama_ok = False
    try:
        async with httpx.AsyncClient(timeout=3.0) as c:
            r = await c.get(f"{config.LLAMA_SERVER_URL}/health")
            llama_ok = r.status_code == 200
    except Exception:
        llama_ok = False
    return JSONResponse({"retriever_ready": ready, "llama_server": llama_ok},
                        status_code=200 if (ready and llama_ok) else 503)


# ---------------------------------------------------------------- chat (SSE)

def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.post("/api/chat")
async def chat(req: ChatRequest):
    history = [{"role": t.role, "content": t.content} for t in req.messages]
    if not history or history[-1]["role"] != "user":
        return JSONResponse({"error": "messages must end with a user turn"}, status_code=400)

    session_id = req.session_id or str(uuid.uuid4())
    message_id = str(uuid.uuid4())
    latest_query = history[-1]["content"]

    # Device parity (R3.4): retrieve on the latest user turn only.
    context, citations = _retriever.retrieve(latest_query)
    prompt = build_prompt(history, context)

    async def stream():
        # 1) hand the client the retrieved context up front (as the device shows it).
        yield _sse("context", {"message_id": message_id, "session_id": session_id,
                               "citations": citations})

        payload = {
            "prompt": prompt,
            "n_predict": config.MAX_TOKENS,
            "temperature": config.TEMPERATURE,
            "top_p": config.TOP_P,
            "top_k": config.TOP_K,
            "stop": ["<end_of_turn>"],
            "stream": True,
            "cache_prompt": True,
        }
        full = []
        try:
            async with httpx.AsyncClient(timeout=None) as c:
                async with c.stream("POST", f"{config.LLAMA_SERVER_URL}/completion",
                                    json=payload) as resp:
                    async for line in resp.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        chunk = json.loads(line[5:].strip())
                        tok = chunk.get("content", "")
                        if tok:
                            full.append(tok)
                            yield _sse("token", {"t": tok})
                        if chunk.get("stop"):
                            break
        except Exception as exc:  # surface backend errors to the UI instead of hanging
            yield _sse("error", {"message": f"generation failed: {exc}"})
            return

        response_text = "".join(full).strip()
        if config.ENABLE_FEEDBACK:
            feedback.save_exchange(
                message_id=message_id, session_id=session_id, query=latest_query,
                history=history, context=context, citations=citations, response=response_text,
            )
        yield _sse("done", {"message_id": message_id, "session_id": session_id})

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------------------------------------------------------------- feedback

@app.post("/api/feedback")
def submit_feedback(req: FeedbackRequest):
    if not config.ENABLE_FEEDBACK:
        return JSONResponse({"error": "feedback disabled"}, status_code=404)
    feedback.save_feedback(
        message_id=req.message_id, session_id=req.session_id, rating=req.rating,
        helpful=req.helpful, issues=req.issues, comment=req.comment,
    )
    return {"ok": True}


# ---------------------------------------------------------------- static UI

@app.get("/")
def index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

# Serve the source PDFs so citations can open to the cited page (#page=N).
if os.path.isdir(config.DOCS_DIR):
    app.mount("/docs", StaticFiles(directory=config.DOCS_DIR), name="docs")
