"""
DocuMind – RAG Engine (Local AI – No API Required)
PDF extraction → chunking → embeddings → FAISS → extractive QA
All models run 100% offline. No API key needed.
"""

import os
import re
import json
import time
import random
import pickle
import logging
from pathlib import Path
from typing import Optional
from collections import Counter

import numpy as np
import pdfplumber                          # type: ignore
from sentence_transformers import SentenceTransformer  # type: ignore
import faiss                               # type: ignore
from rank_bm25 import BM25Okapi           # type: ignore
from dotenv import load_dotenv            # type: ignore

# sklearn is installed as a transitive dep of sentence-transformers
from sklearn.feature_extraction.text import TfidfVectorizer  # type: ignore

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s [RAG] %(message)s")
logger = logging.getLogger("rag_engine")

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR    = Path(__file__).parent
STORE_DIR   = BASE_DIR / "faiss_store"
DATASET_DIR = BASE_DIR / "hackathon dataset"
ENV_FILE    = BASE_DIR / ".env"
STORE_DIR.mkdir(exist_ok=True)
load_dotenv(ENV_FILE)

# ── Constants ─────────────────────────────────────────────────────────────────
EMBED_MODEL   = "sentence-transformers/all-MiniLM-L6-v2"
CHUNK_SIZE    = 500
CHUNK_OVERLAP = 100
TOP_K_DEFAULT = 5

FEEDBACK_FILE = STORE_DIR / "feedback.json"

DOMAIN_PROMPTS = {
    "General":  "Be a helpful and concise assistant.",
    "Legal":    "Use formal language and prioritize precise clauses.",
    "Medical":  "Prioritize evidence-based facts and clinical terminology.",
    "Research": "Focus on methodology and logical coherence.",
}

# ── Singletons ────────────────────────────────────────────────────────────────
_embed_model: Optional[SentenceTransformer] = None
_index:       Optional[faiss.IndexFlatIP]   = None
_metadata:    list = []
_bm25:        Optional[BM25Okapi]           = None
_status = {"embedding": "loading", "llm": "local (offline)", "vector_db": "offline", "ocr": "disabled"}


# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════════
def _split_sentences(text: str) -> list[str]:
    """Split text into sentences."""
    sents = re.split(r"(?<=[.!?])\s+", text)
    return [s.strip() for s in sents if len(s.strip()) > 15]


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


# ═══════════════════════════════════════════════════════════════════════════════
# JSON HELPERS
# ═══════════════════════════════════════════════════════════════════════════════
def save_json(filename: str, data):
    path = STORE_DIR / filename
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def load_json(filename: str, default=None):
    path = STORE_DIR / filename
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default


# ═══════════════════════════════════════════════════════════════════════════════
# MODEL LOADING
# ═══════════════════════════════════════════════════════════════════════════════
def _load_embed() -> SentenceTransformer:
    global _embed_model
    if _embed_model is None:
        logger.info("Loading embedding model...")
        try:
            _embed_model = SentenceTransformer(EMBED_MODEL, local_files_only=True)
        except Exception:
            _embed_model = SentenceTransformer(EMBED_MODEL)
        _status["embedding"] = "ready"
        logger.info("Embedding model ready.")
    return _embed_model


def get_status() -> dict:
    return dict(_status)


# ═══════════════════════════════════════════════════════════════════════════════
# FAISS INDEX
# ═══════════════════════════════════════════════════════════════════════════════
def _index_path():  return STORE_DIR / "index.faiss"
def _meta_path():   return STORE_DIR / "metadata.json"
def _bm25_path():   return STORE_DIR / "bm25.pkl"


def _load_index() -> bool:
    global _index, _metadata, _bm25
    if _index_path().exists() and _meta_path().exists():
        _index = faiss.read_index(str(_index_path()))
        with open(_meta_path(), "r", encoding="utf-8") as f:
            _metadata = json.load(f)
        if _bm25_path().exists():
            with open(_bm25_path(), "rb") as f:
                _bm25 = pickle.load(f)
        _status["vector_db"] = "online"
        logger.info(f"FAISS index loaded: {_index.ntotal} vectors, {len(_metadata)} chunks.")
        return True
    return False


def _save_index():
    if _index is not None:
        faiss.write_index(_index, str(_index_path()))
    with open(_meta_path(), "w", encoding="utf-8") as f:
        json.dump(_metadata, f, indent=2, ensure_ascii=False)
    if _bm25:
        with open(_bm25_path(), "wb") as f:
            pickle.dump(_bm25, f)
    _status["vector_db"] = "online"
    logger.info("FAISS index saved.")


def _rebuild_bm25():
    global _bm25
    corpus = [m["chunk"].lower().split() for m in _metadata]
    _bm25 = BM25Okapi(corpus) if corpus else None


def _init_index(dim: int):
    global _index
    _index = faiss.IndexFlatIP(dim)


# ═══════════════════════════════════════════════════════════════════════════════
# TEXT EXTRACTION
# ═══════════════════════════════════════════════════════════════════════════════
def extract_text_from_pdf(pdf_path: str) -> list[dict]:
    pages = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for i, page in enumerate(pdf.pages, 1):
                text = page.extract_text() or ""
                text = _clean_text(text)
                if text:
                    pages.append({"page": i, "text": text})
    except Exception as e:
        logger.error(f"PDF extract error {pdf_path}: {e}")
    return pages


def extract_text_from_txt(txt_path: str) -> list[dict]:
    try:
        text = Path(txt_path).read_text(encoding="utf-8", errors="replace")
        chunks = []
        for i, para in enumerate(text.split("\n\n"), 1):
            para = _clean_text(para)
            if para:
                chunks.append({"page": i, "text": para})
        return chunks
    except Exception as e:
        logger.error(f"TXT extract error {txt_path}: {e}")
        return []


def extract_text_from_image(img_path: str, api_key: str = "") -> list[dict]:
    """Image OCR is disabled (no API). Returns a placeholder."""
    return [{"page": 1, "text": f"Image file: {Path(img_path).name}. Image text extraction is disabled in offline mode."}]


# ═══════════════════════════════════════════════════════════════════════════════
# CHUNKING
# ═══════════════════════════════════════════════════════════════════════════════
def _chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    if not text or not text.strip():
        return []
    blocks = re.split(r"\n\n+", text)
    chunks, current_chunk, current_length, last_heading = [], [], 0, ""

    for block in blocks:
        block = block.strip()
        if not block:
            continue
        if re.match(r"^#{1,6}\s+", block):
            last_heading = block
        is_table = block.count("|") > 4
        words = block.split()
        block_len = len(words)

        if block_len > chunk_size and not is_table:
            if current_chunk:
                chunks.append(" ".join(current_chunk))
                current_chunk, current_length = [], 0
            sentences = re.split(r"(?<=[.!?])\s+", block)
            for sent in sentences:
                sent_words = sent.split()
                if current_length + len(sent_words) > chunk_size and current_chunk:
                    chunks.append((f"{last_heading}\n" if last_heading else "") + " ".join(current_chunk))
                    current_chunk = current_chunk[-overlap:] + sent_words
                    current_length = len(current_chunk)
                else:
                    current_chunk.extend(sent_words)
                    current_length += len(sent_words)
        else:
            if current_length + block_len > chunk_size and current_chunk:
                chunks.append((f"{last_heading}\n" if last_heading else "") + " ".join(current_chunk))
                current_chunk, current_length = [], 0
            current_chunk.extend(words)
            current_length += block_len

    if current_chunk:
        chunks.append((f"{last_heading}\n" if last_heading else "") + " ".join(current_chunk))
    return [c.strip() for c in chunks if len(c.strip()) > 30]


# ═══════════════════════════════════════════════════════════════════════════════
# INDEXING
# ═══════════════════════════════════════════════════════════════════════════════
def index_document(file_path: str, progress_cb=None) -> dict:
    global _index, _metadata, _bm25
    path = Path(file_path)
    doc_name = path.name
    ext = path.suffix.lower()

    already = [m for m in _metadata if m["doc_name"] == doc_name]
    if already:
        return {"doc_name": doc_name, "chunks": len(already), "pages": already[-1]["page"], "skipped": True}

    if progress_cb: progress_cb(0.1, "📖 Extracting text…")
    if ext == ".pdf":
        pages = extract_text_from_pdf(file_path)
    elif ext in [".jpg", ".jpeg", ".png"]:
        pages = extract_text_from_image(file_path)
    else:
        pages = extract_text_from_txt(file_path)

    if not pages:
        return {"doc_name": doc_name, "chunks": 0, "pages": 0, "error": "No text extracted"}

    if progress_cb: progress_cb(0.3, "✂️ Chunking text…")
    raw_chunks = []
    for p in pages:
        for chunk in _chunk_text(p["text"]):
            raw_chunks.append({"doc_name": doc_name, "page": p["page"], "chunk": chunk})

    if not raw_chunks:
        return {"doc_name": doc_name, "chunks": 0, "pages": len(pages), "error": "No chunks produced"}

    if progress_cb: progress_cb(0.5, "🔢 Creating embeddings…")
    model = _load_embed()
    texts = [c["chunk"] for c in raw_chunks]
    embeddings = model.encode(texts, show_progress_bar=False, normalize_embeddings=True).astype(np.float32)

    if _index is None:
        _init_index(embeddings.shape[1])

    if progress_cb: progress_cb(0.8, "🗄️ Adding to vector database…")
    _index.add(embeddings)
    _metadata.extend(raw_chunks)
    _rebuild_bm25()

    if progress_cb: progress_cb(0.95, "💾 Saving index…")
    _save_index()

    size_mb = round(path.stat().st_size / 1024 / 1024, 2)
    return {"doc_name": doc_name, "chunks": len(raw_chunks), "pages": pages[-1]["page"], "size_mb": size_mb}


def index_dataset(progress_cb=None, clear_first: bool = False) -> list[dict]:
    global _index, _metadata, _bm25
    if clear_first:
        _index, _metadata, _bm25 = None, [], None
    results = []
    pdfs = list(DATASET_DIR.glob("*.pdf")) + list(DATASET_DIR.glob("*.txt"))
    total = len(pdfs)
    for i, pdf in enumerate(pdfs):
        def _pcb(frac, msg, _i=i, _t=total):
            if progress_cb:
                progress_cb((_i + frac) / _t, f"[{_i+1}/{_t}] {msg} {pdf.name}")
        results.append(index_document(str(pdf), _pcb))
    return results


def list_indexed_docs() -> list[dict]:
    seen, docs = set(), []
    for m in _metadata:
        if m["doc_name"] not in seen:
            seen.add(m["doc_name"])
            chunks_list = [x for x in _metadata if x["doc_name"] == m["doc_name"]]
            pages_list  = [x["page"] for x in chunks_list]
            docs.append({
                "name":   m["doc_name"],
                "type":   m["doc_name"].rsplit(".", 1)[-1].upper(),
                "pages":  max(pages_list) if pages_list else 1,
                "chunks": len(chunks_list),
                "size":   "—", "date": "—", "status": "ready",
            })
    return docs


# ═══════════════════════════════════════════════════════════════════════════════
# RETRIEVAL
# ═══════════════════════════════════════════════════════════════════════════════
def _hybrid_retrieve(query: str, top_k: int = TOP_K_DEFAULT,
                     doc_filter: str | list | None = None) -> list[dict]:
    if _index is None or _index.ntotal == 0:
        return []
    model = _load_embed()
    q_vec = model.encode([query], normalize_embeddings=True).astype(np.float32)
    k = min(top_k * 3, _index.ntotal)
    scores, indices = _index.search(q_vec, k)

    semantic_hits = {}
    for score, idx in zip(scores[0], indices[0]):
        if idx < 0 or idx >= len(_metadata):
            continue
        meta = _metadata[idx]
        if doc_filter and doc_filter != "all":
            allowed = [doc_filter] if isinstance(doc_filter, str) else doc_filter
            if meta["doc_name"] not in allowed:
                continue
        semantic_hits[idx] = {"meta": meta, "sem": float(score)}

    bm25_hits = {}
    if _bm25:
        q_tokens = query.lower().split()
        bm25_scores = _bm25.get_scores(q_tokens)
        for idx in np.argsort(bm25_scores)[::-1][:top_k * 3]:
            if idx >= len(_metadata):
                continue
            meta = _metadata[idx]
            if doc_filter and doc_filter != "all":
                allowed = [doc_filter] if isinstance(doc_filter, str) else doc_filter
                if meta["doc_name"] not in allowed:
                    continue
            bm25_hits[idx] = {"meta": meta, "bm25": float(bm25_scores[idx])}

    all_idx = set(semantic_hits) | set(bm25_hits)
    if not all_idx:
        return []

    max_sem  = max((semantic_hits[i]["sem"]  for i in semantic_hits),  default=1) or 1
    max_bm25 = max((bm25_hits[i]["bm25"]    for i in bm25_hits),       default=1) or 1

    results = []
    for idx in all_idx:
        sem  = semantic_hits.get(idx, {}).get("sem",  0) / max_sem
        bm25 = bm25_hits.get(idx, {}).get("bm25", 0) / max_bm25
        meta = (semantic_hits.get(idx) or bm25_hits.get(idx))["meta"]
        results.append({
            "chunk": meta["chunk"], "doc_name": meta["doc_name"], "page": meta["page"],
            "score": 0.65 * sem + 0.35 * bm25, "semantic_score": sem,
        })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_k]


def _build_context(chunks: list[dict]) -> str:
    parts = [f"[Chunk {i} | Doc: {c['doc_name']} | Page {c['page']}]\n{c['chunk']}"
             for i, c in enumerate(chunks, 1)]
    return "\n\n---\n\n".join(parts)


# ═══════════════════════════════════════════════════════════════════════════════
# LOCAL EXTRACTIVE QA
# ═══════════════════════════════════════════════════════════════════════════════
def _extract_answer_from_context(query: str, chunks: list[dict]) -> tuple:
    """
    Uses the sentence-transformer embedding model to find the most relevant
    sentences within retrieved chunks and returns a formatted answer.
    Returns: (answer_text, confidence_int, relevant_sentence_str)
    """
    model = _load_embed()

    # Collect all sentences from all chunks
    all_sents = []
    for chunk in chunks:
        for s in _split_sentences(chunk["chunk"]):
            if len(s) > 20:
                all_sents.append({"text": s, "doc": chunk["doc_name"], "page": chunk["page"]})

    if not all_sents:
        fallback = chunks[0]["chunk"][:400]
        return f"**Extracted from document:**\n\n{fallback}", 40, fallback[:100]

    # Embed query + sentences
    q_vec  = model.encode([query], normalize_embeddings=True)
    s_vecs = model.encode([s["text"] for s in all_sents], normalize_embeddings=True)
    sims   = np.dot(s_vecs, q_vec.T).flatten()

    # Top 5 by similarity
    top_indices = np.argsort(sims)[::-1][:5]
    top_hits    = [(all_sents[i], float(sims[i])) for i in top_indices]
    filtered    = [(s, sc) for s, sc in top_hits if sc > 0.15] or top_hits[:3]

    confidence  = min(99, max(30, int(filtered[0][1] * 100)))
    best_sent   = filtered[0][0]["text"]
    best_doc    = filtered[0][0]["doc"]
    best_page   = filtered[0][0]["page"]

    # Build a clean markdown answer
    seen = set()
    bullets = []
    for sent_info, _ in filtered[:4]:
        s = sent_info["text"]
        if s not in seen:
            seen.add(s)
            bullets.append(f"- {s}")

    answer = "**Answer from your documents:**\n\n" + "\n\n".join(bullets)
    answer += f"\n\n---\n📌 *Source: **{best_doc}** | Page {best_page}*"
    return answer, confidence, best_sent


def _generate_followups(query: str, chunks: list[dict]) -> list[str]:
    stop = {"what","is","the","a","an","in","of","how","why","where","when","does","do","and","or","are","was","were"}
    key_words = [w for w in re.findall(r"\b\w+\b", query) if w.lower() not in stop and len(w) > 3]
    followups = []
    if key_words:
        followups = [
            f"What is the definition of {key_words[0]}?",
            f"How does {key_words[0]} work in practice?",
            f"What are the main properties of {key_words[0]}?",
        ]
    if len(followups) < 3:
        followups += ["Can you elaborate more?", "What are the key takeaways?", "Are there any exceptions?"]
    return followups[:3]


# ═══════════════════════════════════════════════════════════════════════════════
# ANSWER QUESTION (Main Q&A)
# ═══════════════════════════════════════════════════════════════════════════════
def answer_question(query: str, doc_filter: str | list = "all",
                    top_k: int = TOP_K_DEFAULT, api_key: str = "",
                    persona: str = "Professional", complexity: str = "Expert",
                    domain: str = "General") -> dict:
    """Local extractive RAG Q&A — no API required."""
    _load_embed()
    chunks = _hybrid_retrieve(query, top_k, None if doc_filter == "all" else doc_filter)

    if not chunks:
        return {
            "answer": "No relevant information found in your documents. Please upload and index a document first.",
            "source_text": "N/A", "doc_name": "None", "page": 0,
            "confidence": 0, "confidence_reason": "No chunks found.",
            "followups": ["Upload a document first", "Try a different question", "Check if documents are indexed"],
            "relevant_sentence": "", "chunks": [], "query_intent": "Unknown",
            "rewritten_q": query, "missed_info": "", "graph_info": False,
        }

    answer_text, confidence, rel_sent = _extract_answer_from_context(query, chunks)
    best = chunks[0]
    source_snippet = best["chunk"][:300].strip() + ("…" if len(best["chunk"]) > 300 else "")

    # Add complexity note to answer
    if complexity == "Explain Like I'm 10 (ELI5)":
        answer_text = "🧒 **Simple Explanation:**\n\n" + answer_text
    elif complexity == "Expert":
        answer_text = "🎓 **Expert-Level Extraction:**\n\n" + answer_text

    return {
        "answer":            answer_text,
        "source_text":       f"📌 {best['doc_name']} | Page {best['page']}:\n\"{source_snippet}\"",
        "doc_name":          best["doc_name"],
        "page":              best["page"],
        "confidence":        confidence,
        "confidence_reason": f"Extracted from {len(chunks)} relevant chunks.",
        "followups":         _generate_followups(query, chunks),
        "relevant_sentence": rel_sent,
        "chunks":            chunks,
        "graph_info":        False,
        "query_intent":      "Fact-seeking",
        "rewritten_q":       query,
        "missed_info":       "",
    }


# ═══════════════════════════════════════════════════════════════════════════════
# MULTI-HOP Q&A
# ═══════════════════════════════════════════════════════════════════════════════
def multi_hop_answer_question(query: str, doc_filter: str | list = "all",
                              api_key: str = "", top_k: int = 4,
                              persona: str = "Professional", domain: str = "General") -> dict:
    """Local multi-hop: decomposes query by keywords, retrieves per sub-topic, merges."""
    stop = {"what","is","the","a","an","in","of","how","why","where","when","does","do","and","or"}
    words = [w for w in re.findall(r"\b\w+\b", query) if w.lower() not in stop and len(w) > 3]

    topics = [query]
    if len(words) >= 2:
        topics.append(" ".join(words[:2]))
    if len(words) >= 4:
        topics.append(" ".join(words[2:4]))

    all_chunks, seen_ids, hops = [], set(), []
    filt = None if doc_filter == "all" else doc_filter
    for t in topics[:3]:
        found = _hybrid_retrieve(t, 3, filt)
        new_cnt = 0
        for c in found:
            key = f"{c['doc_name']}|{c['page']}|{c['chunk'][:50]}"
            if key not in seen_ids:
                seen_ids.add(key); all_chunks.append(c); new_cnt += 1
        hops.append({"topic": t, "new_chunks": new_cnt})

    if not all_chunks:
        return answer_question(query, doc_filter, top_k)

    answer_text, confidence, rel_sent = _extract_answer_from_context(query, all_chunks)
    best = all_chunks[0]

    return {
        "answer":            answer_text,
        "followups":         _generate_followups(query, all_chunks),
        "reasoning":         f"Searched {len(topics)} sub-topics, retrieved {len(all_chunks)} unique chunks.",
        "hops":              hops,
        "source_text":       f"📌 {best['doc_name']} | Page {best['page']}",
        "confidence":        confidence,
        "graph_info":        False,
        "query_intent":      "Multi-hop",
        "rewritten_q":       query,
        "missed_info":       "",
    }


# ═══════════════════════════════════════════════════════════════════════════════
# SUMMARISATION (Extractive – TF-IDF)
# ═══════════════════════════════════════════════════════════════════════════════
def _tfidf_summarize(chunks: list[dict], n: int = 8) -> str:
    all_sents = []
    for chunk in chunks:
        all_sents.extend([s for s in _split_sentences(chunk["chunk"]) if len(s) > 30])
    if len(all_sents) < 3:
        return " ".join(all_sents)
    try:
        vec = TfidfVectorizer(stop_words="english", max_features=500)
        mat = vec.fit_transform(all_sents).toarray()
        scores = [float(np.mean(row[row > 0])) if row.sum() > 0 else 0 for row in mat]
        # Slight position bias (earlier = higher)
        scores = [s * (1.0 - 0.2 * i / len(scores)) for i, s in enumerate(scores)]
        top_idx = sorted(np.argsort(scores)[::-1][:n])
        return " ".join(all_sents[i] for i in top_idx)
    except Exception as e:
        logger.warning(f"TF-IDF summarize error: {e}")
        return " ".join(all_sents[:n])


def summarise_document(doc_name: str, mode: str = "short", api_key: str = "") -> dict:
    chunks = [m for m in _metadata if m["doc_name"] == doc_name]
    if not chunks:
        return {"summary": "Document not found in index.", "confidence": 0}

    step    = max(1, len(chunks) // 15)
    sampled = chunks[::step][:15]
    summary_text = _tfidf_summarize(sampled, n=10)

    if mode == "short":
        lines = _split_sentences(summary_text)[:4]
        body  = " ".join(lines)
        out   = f"**Summary of {doc_name}**\n\n{body}"
    elif mode == "keypoints":
        lines = _split_sentences(summary_text)[:7]
        out   = f"**Key Points — {doc_name}**\n\n" + "\n".join(f"- {l}" for l in lines)
    else:  # bullets
        lines = _split_sentences(summary_text)[:10]
        out   = f"**Section Breakdown — {doc_name}**\n\n" + "\n".join(f"- {l}" for l in lines)

    return {"summary": out, "confidence": 80}


# ═══════════════════════════════════════════════════════════════════════════════
# STUDY MATERIALS (Pattern-based extraction)
# ═══════════════════════════════════════════════════════════════════════════════
def generate_study_materials(doc_name: str, mode: str = "Quiz", api_key: str = "") -> list:
    chunks = [m for m in _metadata if m["doc_name"] == doc_name]
    if not chunks:
        return [{"type": "error", "question": "Document not indexed.", "options": [], "answer": ""}]

    step    = max(1, len(chunks) // 10)
    sampled = chunks[::step][:10]

    all_sents = []
    for c in sampled:
        all_sents.extend([s for s in _split_sentences(c["chunk"]) if len(s) > 25])

    if mode == "Flashcards":
        patterns = [
            r"(.{5,60}?)\s+(?:is|are|refers to|means|defined as|known as)\s+(.{10,})",
            r"(.{5,50}?)\s*[:\-–]\s*(.{15,})",
        ]
        cards = []
        for s in all_sents:
            for pat in patterns:
                m = re.match(pat, s, re.IGNORECASE)
                if m:
                    front = m.group(1).strip().capitalize()
                    back  = m.group(2).strip()
                    if 3 < len(front) < 70 and len(back) > 10:
                        cards.append({"type": "flashcard", "front": front, "back": back})
                        break
            if len(cards) >= 8:
                break
        if not cards:
            for i, c in enumerate(sampled[:6]):
                sents = _split_sentences(c["chunk"])
                if sents:
                    cards.append({"type": "flashcard",
                                  "front": f"Concept {i+1}",
                                  "back":  sents[0][:200]})
        return cards

    else:  # Quiz
        all_terms = []
        for s in all_sents:
            all_terms.extend([w for w in s.split() if len(w) > 4 and w[0].isupper() and w.isalpha()])
        common_terms = [t for t, _ in Counter(all_terms).most_common(40)]

        quiz = []
        for s in all_sents:
            cap_words = [w for w in s.split() if len(w) > 4 and w[0].isupper() and w.isalpha()]
            if cap_words and len(s) > 40:
                answer_term = cap_words[0]
                question    = s.replace(answer_term, "_______", 1)
                distractors = [t for t in common_terms if t != answer_term][:3]
                while len(distractors) < 3:
                    distractors.append(f"Option {len(distractors)+1}")
                options = [answer_term] + distractors
                random.shuffle(options)
                quiz.append({
                    "type":        "quiz",
                    "question":    f"Fill in the blank: {question}",
                    "options":     options,
                    "answer":      answer_term,
                    "explanation": f'From the document: "{s}"',
                })
            if len(quiz) >= 5:
                break

        if not quiz:
            for s in all_sents[:5]:
                quiz.append({
                    "type": "quiz", "question": f"True or False: {s[:150]}",
                    "options": ["True", "False"], "answer": "True",
                    "explanation": "This statement is taken directly from the document.",
                })
        return quiz


# ═══════════════════════════════════════════════════════════════════════════════
# ANALYTICS (Local keyword analysis)
# ═══════════════════════════════════════════════════════════════════════════════
def predict_trends(api_key: str = "") -> dict:
    if not _metadata:
        return {
            "trends": ["Upload and index documents to see trends."],
            "risks":  ["No data available."],
            "summary": "Knowledge base is empty.",
        }
    all_text = [m["chunk"] for m in _metadata]
    try:
        vec = TfidfVectorizer(stop_words="english", max_features=200, ngram_range=(1, 2))
        mat = vec.fit_transform(all_text)
        feature_names = vec.get_feature_names_out()
        mean_scores   = np.array(mat.mean(axis=0)).flatten()
        top_idx       = np.argsort(mean_scores)[::-1]
        top_terms     = [feature_names[i] for i in top_idx[:15]]

        trends = [f"Recurring theme: '{t.title()}'" for t in top_terms[:3]]
        risks  = [f"Potential knowledge gap: '{t.title()}'" for t in top_terms[3:5]]
        n_docs = len(set(m["doc_name"] for m in _metadata))
        summary = (f"Analyzed {len(_metadata)} chunks across {n_docs} document(s). "
                   f"Top concept: '{top_terms[0].title()}'.")
    except Exception as e:
        logger.warning(f"Trend analysis failed: {e}")
        top = get_top_concepts()
        trends  = [f"Key topic: {t[0]}" for t in top[:3]] or ["No clear trends detected"]
        risks   = ["Could not compute risk patterns"]
        summary = "Basic keyword analysis applied."

    return {"trends": trends, "risks": risks, "summary": summary}


def analyze_sentiment(doc_name: str) -> str:
    positive = ["success", "profit", "growth", "policy", "safety", "trust", "achievement"]
    negative = ["risk", "loss", "warning", "incident", "failure", "crisis", "error"]
    name_low = doc_name.lower()
    if any(p in name_low for p in positive): return "Positive"
    if any(n in name_low for n in negative): return "Negative"
    return "Neutral"


def detect_knowledge_gaps() -> list:
    if not _metadata:
        return ["Upload documents to unlock Knowledge Gap analysis."]
    all_text = " ".join(m["chunk"] for m in _metadata[:20])
    try:
        vec = TfidfVectorizer(stop_words="english", max_features=100)
        mat = vec.fit_transform([m["chunk"] for m in _metadata])
        names  = vec.get_feature_names_out()
        counts = np.array((mat > 0).sum(axis=0)).flatten()
        # Terms that appear in only 1 doc = potential gaps
        gaps = [names[i] for i in np.where(counts == 1)[0][:3]]
        return gaps if gaps else ["No significant gaps detected"]
    except Exception:
        return ["Analysis unavailable"]


def get_top_concepts() -> list:
    if not _metadata:
        return [("No data", 0)]
    all_text = [m["chunk"] for m in _metadata]
    try:
        vec  = TfidfVectorizer(stop_words="english", max_features=50)
        mat  = vec.fit_transform(all_text)
        names = vec.get_feature_names_out()
        mean  = np.array(mat.mean(axis=0)).flatten()
        top   = np.argsort(mean)[::-1][:5]
        return [(names[i], round(float(mean[i]) * 100, 1)) for i in top]
    except Exception:
        return [("No concepts", 0)]


def get_graph_data() -> list:
    return []  # Knowledge Graph disabled (was Gemini-only)


def save_feedback(query: str, answer: str, score: str):
    try:
        fb = load_json(str(FEEDBACK_FILE), [])
        fb.append({"time": time.time(), "q": query, "a": answer, "score": score})
        save_json(str(FEEDBACK_FILE), fb)
    except Exception as e:
        logger.error(f"Feedback save failed: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# STARTUP
# ═══════════════════════════════════════════════════════════════════════════════
def initialise(api_key: str = "", progress_cb=None):
    """Call once at app startup. Loads embedding model + FAISS index."""
    if progress_cb: progress_cb(0.2, "🧠 Loading local AI model...")
    _load_embed()
    if progress_cb: progress_cb(0.6, "🗄️ Loading document index...")
    if not _load_index():
        logger.info("No index found – indexing hackathon dataset…")
        _status["vector_db"] = "indexing"
        index_dataset(progress_cb)
    _status["llm"] = "local (offline)"
    if progress_cb: progress_cb(1.0, "✅ Ready!")
    return get_status()
