"""Live retrieval for the demo — faithful to the deployed on-device pipeline.

Mirrors the current deploy (rag-bundle-v0.3.0):
  - EmbeddingGemma-300M (seq256 LiteRT) encodes the query with the QUERY prompt
    prefix "task: search result | query: "  (the on-device query mode — see the
    R2c parity note in the improvement plan: queries must use query mode, not the
    document mode used to build the store).
  - Cosine top-k over the EmbeddingGemma-embedded vector store (embeddings.sqlite,
    63,650 chunks, 768-d, L2-normalised, VF32 blob format).
  - Chunks are rendered as `Document N:` blocks with the [SOURCE|PAGE] prefix
    stripped, exactly as the eval's format_app_context_chunks does.

Encoding is byte-for-byte the deployed scheme (see
mamai-medical-guidelines/scripts/reembed_embeddinggemma.py):
  ids = [BOS] + spm(PROMPT + text) + [EOS], truncate/right-pad to 256 int32.
"""

import re
import sqlite3
import struct
import threading

import numpy as np

from backend import config

SEQ = 256
BOS, EOS = 2, 1
QUERY_PROMPT = "task: search result | query: "  # on-device query mode

_METADATA_PREFIX = re.compile(r"^\[SOURCE:([^|]+)\|PAGE:(\d+)\]")
_NONFILE = re.compile(r"[^A-Za-z0-9\-.]")


def pdf_filename(source: str) -> str:
    """Map a chunk source id to its PDF filename, matching the app's
    normalizeSourceId: non-[A-Za-z0-9-.] -> '_', collapse '_', trim '_'."""
    s = _NONFILE.sub("_", source)
    s = re.sub(r"_+", "_", s).strip("_")
    return f"{s}.pdf" if s else ""


class EmbeddingGemmaEmbedder:
    """EmbeddingGemma-300M TFLite query encoder (CPU/XNNPACK).

    Replicates the on-device EmbeddingGemmaEmbedder query path.
    """

    def __init__(self, model_path: str, tokenizer_path: str):
        import sentencepiece as spm
        from ai_edge_litert.interpreter import Interpreter

        self.interp = Interpreter(model_path=model_path, num_threads=4)
        self.interp.allocate_tensors()
        self.in_idx = self.interp.get_input_details()[0]["index"]
        self.out_idx = self.interp.get_output_details()[0]["index"]

        self.sp = spm.SentencePieceProcessor()
        self.sp.load(tokenizer_path)

        # TFLite interpreter is not thread-safe; serialise invokes.
        self._lock = threading.Lock()

    def embed(self, text: str) -> np.ndarray:
        """Embed a query string. Returns an L2-normalised 768-d float32 vector."""
        ids = [BOS] + self.sp.encode_as_ids(QUERY_PROMPT + text) + [EOS]
        ids = ids[:SEQ] + [0] * max(0, SEQ - len(ids))
        inp = np.array([ids], dtype=np.int32)
        with self._lock:
            self.interp.set_tensor(self.in_idx, inp)
            self.interp.invoke()
            out = self.interp.get_tensor(self.out_idx)
        v = out.flatten().astype(np.float32)
        return v / (np.linalg.norm(v) + 1e-9)


def parse_chunk_metadata(raw: str) -> dict:
    """Parse the app's [SOURCE:stem|PAGE:n] prefix from a stored chunk."""
    m = _METADATA_PREFIX.match(raw)
    if not m:
        return {"text": raw.strip(), "source": "", "page": 0}
    return {"text": raw[m.end():].strip(), "source": m.group(1), "page": int(m.group(2))}


class VectorStore:
    """In-memory cosine index over the app's SQLite vector store."""

    def __init__(self, db_path: str):
        conn = sqlite3.connect(db_path)
        rows = conn.execute("SELECT text, embeddings FROM rag_vector_store").fetchall()
        conn.close()

        texts, vecs = [], []
        for text, blob in rows:
            # 4-byte "VF32" header, then 768 little-endian float32.
            n = (len(blob) - 4) // 4
            vecs.append(np.array(struct.unpack(f"<{n}f", blob[4:]), dtype=np.float32))
            texts.append(text)

        self.texts = texts
        matrix = np.stack(vecs)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        self.normed = matrix / norms  # (n_chunks, dim), pre-normalised
        self.dim = matrix.shape[1]

    def __len__(self) -> int:
        return len(self.texts)

    def search(self, query_vec: np.ndarray, top_k: int, threshold: float = 0.0) -> list[dict]:
        q = query_vec / (np.linalg.norm(query_vec) + 1e-10)
        sims = self.normed @ q
        idx = np.argsort(sims)[-top_k:][::-1]
        out = []
        for i in idx:
            score = float(sims[i])
            if score < threshold:  # per-chunk abstention (R1); threshold 0.0 = keep all
                continue
            meta = parse_chunk_metadata(self.texts[i])
            out.append({**meta, "score": score})
        return out


def format_context(docs: list[dict]) -> tuple[str, list[dict]]:
    """Render retrieved docs into the app-parity context string + citation list.

    Returns (context_str, citations) where context_str is the exact string the
    deployed pipeline injects: `Document N:\\n{text}` blocks joined by blank lines.
    """
    blocks, citations = [], []
    for i, d in enumerate(docs):
        n = i + 1
        blocks.append(f"Document {n}:\n{d['text']}")
        citations.append({
            "n": n,
            "source": d.get("source", ""),
            "page": d.get("page", 0),
            "file": pdf_filename(d.get("source", "")),
            "score": round(d.get("score", 0.0), 4),
            "snippet": d["text"][:240] + ("…" if len(d["text"]) > 240 else ""),
        })
    return "\n\n".join(blocks), citations


class Retriever:
    """Bundles the embedder + store; one call does the device's per-turn retrieval."""

    def __init__(self):
        self.embedder = EmbeddingGemmaEmbedder(config.EMBED_MODEL, config.TOKENIZER)
        self.store = VectorStore(config.VECTOR_DB)

    def retrieve(self, query: str) -> tuple[str, list[dict]]:
        """Embed the (latest-turn) query, retrieve top-k, return (context_str, citations).

        Device parity (R3.4): callers must pass ONLY the latest user turn, never
        the whole conversation — the on-device app embeds the latest turn alone.
        """
        if not query.strip():
            return "", []
        qv = self.embedder.embed(query)
        docs = self.store.search(qv, config.RETRIEVAL_TOP_K, config.RETRIEVAL_THRESHOLD)
        return format_context(docs)
