"""Retrieval over the Markdown knowledge base used by the AI Chatbot (RAG).

Documents in ``docs/knowledge_base`` are split into heading-based chunks and
embedded with the OpenAI embeddings API. Embeddings are cached on disk and keyed
by a hash of the chunk text, so they are recomputed only when a document changes.
When no OpenAI API key is configured (or the API call fails), retrieval falls
back to a local TF-IDF search so the chatbot can still cite the documents.
"""

import hashlib
import json
import os
import re
import threading
from pathlib import Path

import numpy as np
import requests
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

PROJECT_ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE_BASE_DIR = Path(os.getenv("KNOWLEDGE_BASE_DIR", PROJECT_ROOT / "docs" / "knowledge_base"))
CACHE_PATH = KNOWLEDGE_BASE_DIR / ".embeddings_cache.json"
SUPPORTED_SUFFIXES = {".md", ".txt"}

# Minimum similarity for a chunk to count as relevant to the question.
EMBEDDING_MIN_SCORE = 0.30
TFIDF_MIN_SCORE = 0.08

_lock = threading.Lock()
_index = None


def _embedding_settings():
    return (
        os.getenv("OPENAI_API_KEY"),
        os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
        os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"),
    )


def _split_markdown(text, source):
    """Split a document into one chunk per ``##``/``###`` section.

    Each chunk is prefixed with the document title and its heading path so a
    retrieved chunk still makes sense on its own.
    """
    title = source
    heading_path = []
    chunks = []
    lines = []

    def flush():
        body = "\n".join(lines).strip()
        if body:
            section = " > ".join(heading_path) or title
            chunks.append(
                {
                    "source": source,
                    "title": title,
                    "section": section,
                    "text": f"{title} — {section}\n\n{body}",
                }
            )
        lines.clear()

    for line in text.splitlines():
        match = re.match(r"^(#{1,3})\s+(.*)", line)
        if not match:
            lines.append(line)
            continue
        level, heading = len(match.group(1)), match.group(2).strip()
        if level == 1:
            flush()
            title = heading
            heading_path = []
            continue
        flush()
        heading_path = heading_path[: level - 2] + [heading]
    flush()
    return chunks


def _load_chunks():
    chunks = []
    if not KNOWLEDGE_BASE_DIR.exists():
        return chunks
    for path in sorted(KNOWLEDGE_BASE_DIR.rglob("*")):
        if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES:
            chunks.extend(_split_markdown(path.read_text(encoding="utf-8"), path.name))
    return chunks


def _hash(text, model):
    return hashlib.sha256(f"{model}\n{text}".encode("utf-8")).hexdigest()


def _embed(texts, api_key, base_url, model):
    response = requests.post(
        f"{base_url}/embeddings",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"model": model, "input": texts},
        timeout=60,
    )
    response.raise_for_status()
    data = sorted(response.json()["data"], key=lambda item: item["index"])
    return [item["embedding"] for item in data]


def _read_cache():
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_cache(cache):
    try:
        CACHE_PATH.write_text(json.dumps(cache), encoding="utf-8")
    except OSError:
        pass


def _build_embedding_matrix(chunks):
    api_key, base_url, model = _embedding_settings()
    if not api_key or not chunks:
        return None, None
    cache = _read_cache()
    keys = [_hash(chunk["text"], model) for chunk in chunks]
    missing = [index for index, key in enumerate(keys) if key not in cache]
    try:
        for start in range(0, len(missing), 64):
            batch = missing[start : start + 64]
            vectors = _embed([chunks[index]["text"] for index in batch], api_key, base_url, model)
            for index, vector in zip(batch, vectors):
                cache[keys[index]] = vector
    except (requests.RequestException, KeyError, TypeError, ValueError):
        return None, None
    if missing:
        _write_cache({key: cache[key] for key in keys})
    matrix = np.array([cache[key] for key in keys], dtype=float)
    matrix /= np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix, model


def _signature():
    if not KNOWLEDGE_BASE_DIR.exists():
        return ()
    return tuple(
        (str(path), path.stat().st_mtime)
        for path in sorted(KNOWLEDGE_BASE_DIR.rglob("*"))
        if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES
    ) + (bool(_embedding_settings()[0]),)


def _get_index():
    """Build the index once, and rebuild it if a document or the API key changes."""
    global _index
    signature = _signature()
    with _lock:
        if _index is None or _index["signature"] != signature:
            chunks = _load_chunks()
            tfidf = TfidfVectorizer(lowercase=True, ngram_range=(1, 2), stop_words="english")
            tfidf_matrix = tfidf.fit_transform([chunk["text"] for chunk in chunks]) if chunks else None
            embedding_matrix, embedding_model = _build_embedding_matrix(chunks)
            _index = {
                "signature": signature,
                "chunks": chunks,
                "tfidf": tfidf,
                "tfidf_matrix": tfidf_matrix,
                "embedding_matrix": embedding_matrix,
                "embedding_model": embedding_model,
            }
        return _index


def search(query, top_k=4):
    """Return the knowledge-base chunks most relevant to ``query``."""
    index = _get_index()
    chunks = index["chunks"]
    if not query.strip() or not chunks:
        return {"method": None, "results": []}

    scores = None
    method = "tfidf"
    if index["embedding_matrix"] is not None:
        api_key, base_url, model = _embedding_settings()
        try:
            query_vector = np.array(_embed([query], api_key, base_url, model)[0], dtype=float)
            scores = index["embedding_matrix"] @ (query_vector / np.linalg.norm(query_vector))
            method = "openai-embeddings"
        except (requests.RequestException, KeyError, TypeError, ValueError):
            scores = None
    if scores is None:
        scores = cosine_similarity(index["tfidf"].transform([query]), index["tfidf_matrix"])[0]

    min_score = EMBEDDING_MIN_SCORE if method == "openai-embeddings" else TFIDF_MIN_SCORE
    ranked = np.argsort(scores)[::-1][: max(1, min(top_k, 10))]
    results = [
        {
            "source": chunks[i]["source"],
            "section": chunks[i]["section"],
            "text": chunks[i]["text"],
            "score": round(float(scores[i]), 4),
        }
        for i in ranked
        if scores[i] >= min_score
    ]
    return {"method": method, "results": results}
