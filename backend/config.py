"""Central config for the MAM-AI clinician-feedback demo.

Everything is env-overridable so the same code runs on a Mac (local-first) and
later in the cloud without edits. Defaults point at ./assets relative to repo root.
"""

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ASSETS_DIR = Path(os.environ.get("MAMAI_ASSETS_DIR", REPO_ROOT / "assets"))


def _asset(name: str, env: str) -> str:
    return os.environ.get(env, str(ASSETS_DIR / name))


# --- Retrieval assets (current deploy: EmbeddingGemma-300M + rag-bundle-v0.3.0) ---
EMBED_MODEL = _asset("embeddinggemma-300M_seq256_mixed-precision.tflite", "MAMAI_EMBED_MODEL")
TOKENIZER = _asset("sentencepiece.model", "MAMAI_TOKENIZER")
VECTOR_DB = _asset("embeddings.sqlite", "MAMAI_VECTOR_DB")
SYSTEM_PROMPT_FILE = _asset("system_en.txt", "MAMAI_SYSTEM_PROMPT")

# --- Generation backend (llama-server serving the Q4_0 GGUF) ---
LLAMA_SERVER_URL = os.environ.get("MAMAI_LLAMA_URL", "http://127.0.0.1:8080")
GGUF_MODEL = _asset("gemma-3n-E4B-it-Q4_0.gguf", "MAMAI_GGUF_MODEL")

# --- Feedback store ---
FEEDBACK_DB = os.environ.get("MAMAI_FEEDBACK_DB", str(REPO_ROOT / "feedback.sqlite"))

# --- Generation params (config-v0.2.0 params.json; unchanged in deploy) ---
TEMPERATURE = float(os.environ.get("MAMAI_TEMPERATURE", "1.0"))
TOP_P = float(os.environ.get("MAMAI_TOP_P", "0.95"))
TOP_K = int(os.environ.get("MAMAI_TOP_K", "64"))
N_CTX = int(os.environ.get("MAMAI_N_CTX", "4096"))
MAX_TOKENS = int(os.environ.get("MAMAI_MAX_TOKENS", "2048"))

# --- Retrieval params ---
RETRIEVAL_TOP_K = int(os.environ.get("MAMAI_TOP_K_RETRIEVAL", "3"))
RETRIEVAL_THRESHOLD = float(os.environ.get("MAMAI_SIM_THRESHOLD", "0.0"))

# --- Context-injection labels (params.json) ---
CONTEXT_LABEL = "RELEVANT CONTEXT FROM MEDICAL GUIDELINES:"
QUESTION_LABEL = "Question:"

# Stamps shown in the UI so the demo is honest about what it mirrors.
STACK_LABEL = os.environ.get("MAMAI_STACK_LABEL", "deploy / EmbeddingGemma-300M + rag-bundle-v0.3.0")
GENERATOR_LABEL = os.environ.get("MAMAI_GENERATOR_LABEL", "Gemma 3n E4B · Q4_0 GGUF (llama.cpp)")
