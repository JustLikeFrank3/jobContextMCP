#!/usr/bin/env python3
"""
RAG (Retrieval-Augmented Generation) module for job-search-mcp.
Indexes all resume, prep, and LeetCode materials using OpenAI embeddings
stored locally as numpy arrays — no external vector DB required.
"""

import hashlib
import json
import re
from pathlib import Path
from typing import Optional

import numpy as np
from openai import OpenAI

from lib import config as _cfg_module

# ─── CONFIG ───────────────────────────────────────────────────────────────────

_TXT_GLOB = "*.txt"


def _data_dir() -> Path:
    return _cfg_module.get_active_data_folder()


def _index_file() -> Path:
    return _data_dir() / "rag_index.json"


def _embed_file() -> Path:
    return _data_dir() / "rag_embeddings.npy"


# ─── CLIENT ───────────────────────────────────────────────────────────────────

def _openai_client() -> OpenAI:
    key = _cfg_module.get_config_value("openai_api_key", "")
    if not key:
        raise ValueError(
            "openai_api_key not set in config.json. "
            "Add it to use RAG search."
        )
    return OpenAI(api_key=key)


# ─── CHUNKING ─────────────────────────────────────────────────────────────────

def _chunk_text(text: str, max_chars: int = 800, overlap: int = 100) -> list[str]:  # NOSONAR
    """Split text into overlapping chunks, respecting paragraph boundaries."""
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    chunks: list[str] = []
    current = ""

    for para in paragraphs:
        if len(para) > max_chars:
            sentences = re.split(r"(?<=[.!?])\s+", para)
            for sent in sentences:
                if len(current) + len(sent) > max_chars and current:
                    chunks.append(current.strip())
                    current = current[-overlap:] + " " + sent
                else:
                    current += " " + sent
        else:
            if len(current) + len(para) > max_chars and current:
                chunks.append(current.strip())
                current = current[-overlap:] + "\n\n" + para
            else:
                current += "\n\n" + para

    if current.strip():
        chunks.append(current.strip())

    return [c for c in chunks if len(c) > 50]


# ─── EMBEDDING ────────────────────────────────────────────────────────────────

def _embed(texts: list[str], client: OpenAI) -> list[list[float]]:
    """Embed a batch of texts using text-embedding-3-small."""
    response = client.embeddings.create(
        model="text-embedding-3-small",
        input=texts,
    )
    return [item.embedding for item in response.data]


# ─── INDEX ────────────────────────────────────────────────────────────────────

def build_index(verbose: bool = True) -> dict[str, int]:  # NOSONAR
    """
    (Re)build the RAG index from all job search materials.
    Saves embeddings to data/rag_embeddings.npy and metadata to data/rag_index.json.
    Returns chunk counts per category.
    """
    oai     = _openai_client()

    resume_folder   = _cfg_module.get_active_workspace_folder()
    leetcode_folder = _cfg_module.get_active_leetcode_folder()

    # Gather all files to index
    file_groups: list[tuple[list[Path], str]] = []

    # Master resume
    master = _cfg_module.MASTER_RESUME
    if master.exists():
        file_groups.append(([master], "resume"))

    # All resumes
    optimized_dir = _cfg_module.get_active_workspace_path(_cfg_module.get_config_value("optimized_resumes_dir", "01-Current-Optimized"))
    if optimized_dir.exists():
        file_groups.append(([
            f for f in optimized_dir.glob(_TXT_GLOB) if "MASTER" not in f.name
        ], "resume"))

    # Cover letters
    cl_dir = _cfg_module.get_active_workspace_path(_cfg_module.get_config_value("cover_letters_dir", "02-Cover-Letters"))
    if cl_dir.exists():
        file_groups.append((list(cl_dir.glob(_TXT_GLOB)), "cover_letters"))

    # Reference materials
    ref_dir = _cfg_module.get_active_workspace_path(_cfg_module.get_config_value("reference_materials_dir", "06-Reference-Materials"))
    if ref_dir.exists():
        file_groups.append((list(ref_dir.glob(_TXT_GLOB)), "reference"))

    # Interview prep files
    prep_files = [
        f for f in resume_folder.glob(_TXT_GLOB)
        if any(kw in f.name.lower() for kw in ("prep", "interview", "call", "cheat"))
    ]
    file_groups.append((prep_files, "interview_prep"))

    # Interview prep docs folder (08-Interview-Prep-Docs)
    prep_docs_dir = resume_folder / "08-Interview-Prep-Docs"
    if prep_docs_dir.exists():
        prep_doc_files = list(prep_docs_dir.glob(_TXT_GLOB)) + list(prep_docs_dir.glob("*.md"))
        file_groups.append((prep_doc_files, "interview_prep"))

    # Job assessments (fitment analysis, notes on specific roles)
    assessments_dir = resume_folder / "07-Job-Assessments"
    if assessments_dir.exists():
        assessment_files = list(assessments_dir.glob(_TXT_GLOB)) + list(assessments_dir.glob("*.md"))
        file_groups.append((assessment_files, "job_assessments"))
    # Also pick up any assessment .txt files dropped in the resume root
    root_assessment_files = [
        f for f in resume_folder.glob(_TXT_GLOB)
        if any(kw in f.name.lower() for kw in ("assessment", "fitment"))
    ]
    if root_assessment_files:
        file_groups.append((root_assessment_files, "job_assessments"))

    # LeetCode
    lc_files = [
        p for name in (
            _cfg_module.get_config_value("leetcode_cheatsheet_path", ""),
            _cfg_module.get_config_value("quick_reference_path", ""),
        )
        if name and (p := leetcode_folder / name).exists()
    ]
    file_groups.append((lc_files, "leetcode"))

    # Build chunks + metadata
    all_chunks:   list[str]  = []
    all_metadata: list[dict] = []
    counts: dict[str, int]   = {}

    for files, category in file_groups:
        cat_chunks = 0
        for fpath in files:
            try:
                text = fpath.read_text(encoding="utf-8", errors="ignore").strip()
            except Exception:
                continue
            chunks = _chunk_text(text)
            for chunk in chunks:
                all_chunks.append(chunk)
                all_metadata.append({"source": fpath.name, "category": category})
                cat_chunks += 1
        if cat_chunks:
            counts[category] = counts.get(category, 0) + cat_chunks
            if verbose:
                print(f"  ✓ {category}: {cat_chunks} chunks")

    if not all_chunks:
        return {}

    if verbose:
        print(f"\nEmbedding {len(all_chunks)} chunks...")

    # Embed in batches of 100
    all_embeddings: list[list[float]] = []
    for i in range(0, len(all_chunks), 100):
        batch = all_chunks[i:i + 100]
        all_embeddings.extend(_embed(batch, oai))
        if verbose:
            print(f"  {min(i + 100, len(all_chunks))}/{len(all_chunks)}")

    # Save
    _data_dir().mkdir(parents=True, exist_ok=True)
    np.save(str(_embed_file()), np.array(all_embeddings, dtype=np.float32))
    _index_file().write_text(json.dumps({
        "chunks":   all_chunks,
        "metadata": all_metadata,
    }, ensure_ascii=False), encoding="utf-8")

    if verbose:
        print(f"\n✓ Index saved. {len(all_chunks)} total chunks.")

    return counts


# ─── SEARCH ───────────────────────────────────────────────────────────────────

def search(
    query: str,
    category: Optional[str] = None,
    n_results: int = 6,
) -> list[dict]:
    """
    Semantic search across indexed materials.
    Returns list of {text, source, category, score} dicts.
    """
    if not _index_file().exists() or not _embed_file().exists():
        raise FileNotFoundError(
            "RAG index not found. Run reindex_materials() first."
        )

    oai = _openai_client()

    # Load index
    index_data = json.loads(_index_file().read_text(encoding="utf-8"))
    chunks     = index_data["chunks"]
    metadata   = index_data["metadata"]
    embeddings = np.load(str(_embed_file()))  # shape: (N, dim)

    # Filter by category if requested
    if category:
        indices = [i for i, m in enumerate(metadata) if m["category"] == category]
        if not indices:
            return []
        embeddings = embeddings[indices]
        chunks     = [chunks[i]   for i in indices]
        metadata   = [metadata[i] for i in indices]

    # Embed query
    q_vec = np.array(_embed([query], oai)[0], dtype=np.float32)

    # Cosine similarity
    norms = np.linalg.norm(embeddings, axis=1) * np.linalg.norm(q_vec)
    norms = np.where(norms == 0, 1e-9, norms)
    scores = (embeddings @ q_vec) / norms

    top_indices = np.argsort(scores)[::-1][:n_results]

    return [
        {
            "text":     chunks[i],
            "source":   metadata[i]["source"],
            "category": metadata[i]["category"],
            "score":    round(float(scores[i]), 3),
        }
        for i in top_indices
    ]


def format_results(hits: list[dict], header: str = "Search Results") -> str:
    if not hits:
        return "No relevant results found."
    lines = [f"═══ {header} ═══", ""]
    for i, hit in enumerate(hits, 1):
        lines.append(f"[{i}] {hit['source']} (score: {hit['score']}, category: {hit['category']})")
        lines.append(hit["text"])
        lines.append("")
    return "\n".join(lines)


# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":  # pragma: no cover
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "search":
        query = " ".join(sys.argv[2:])
        if not query:
            print("Usage: python rag.py search <query>")
            sys.exit(1)
        hits = search(query)
        print(format_results(hits, f"Results for: {query}"))
    else:
        build_index()
