"""
tests/test_rag_lib_coverage.py

Offline coverage for lib/rag.py — the local-numpy RAG index/search layer.
All OpenAI calls are mocked; no network or real API key is required.
"""

import json
import types

import numpy as np
import pytest

from lib import rag


# ── Pure helpers: _chunk_text ────────────────────────────────────────────────

def test_chunk_text_single_short_paragraph():
    text = "This is a single paragraph that comfortably exceeds the fifty character minimum."
    chunks = rag._chunk_text(text)
    assert len(chunks) == 1
    assert chunks[0].startswith("This is a single paragraph")


def test_chunk_text_drops_sub_threshold_chunks():
    # Whole text is under the 50-char floor → filtered out entirely.
    assert rag._chunk_text("too short") == []


def test_chunk_text_splits_long_paragraph_by_sentences():
    sentence = "Alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu. "
    text = sentence * 20  # one giant paragraph, well over max_chars
    chunks = rag._chunk_text(text, max_chars=200, overlap=20)
    assert len(chunks) > 1
    assert all(len(c) > 50 for c in chunks)


def test_chunk_text_merges_multiple_paragraphs():
    paras = "\n\n".join(f"Paragraph number {i} with enough text to clear the floor easily." for i in range(6))
    chunks = rag._chunk_text(paras, max_chars=120, overlap=20)
    assert len(chunks) >= 2


# ── Pure helpers: format_results ─────────────────────────────────────────────

def test_format_results_empty():
    assert rag.format_results([]) == "No relevant results found."


def test_format_results_populated():
    hits = [
        {"text": "chunk one", "source": "resume.txt", "score": 0.91, "category": "resume"},
        {"text": "chunk two", "source": "prep.txt", "score": 0.77, "category": "interview_prep"},
    ]
    out = rag.format_results(hits, header="My Results")
    assert "═══ My Results ═══" in out
    assert "[1] resume.txt (score: 0.91, category: resume)" in out
    assert "[2] prep.txt (score: 0.77, category: interview_prep)" in out
    assert "chunk one" in out and "chunk two" in out


# ── Path helpers ─────────────────────────────────────────────────────────────

def test_path_helpers(monkeypatch, tmp_path):
    monkeypatch.setattr(rag._cfg_module, "get_active_data_folder", lambda: tmp_path)
    assert rag._data_dir() == tmp_path
    assert rag._index_file() == tmp_path / "rag_index.json"
    assert rag._embed_file() == tmp_path / "rag_embeddings.npy"


# ── _openai_client ───────────────────────────────────────────────────────────

def test_openai_client_missing_key(monkeypatch):
    monkeypatch.setattr(rag._cfg_module, "get_config_value", lambda *_a, **_k: "")
    with pytest.raises(ValueError, match="openai_api_key not set"):
        rag._openai_client()


def test_openai_client_with_key(monkeypatch):
    monkeypatch.setattr(rag._cfg_module, "get_config_value", lambda *_a, **_k: "sk-test")
    client = rag._openai_client()
    assert client is not None  # constructed without a network call


# ── _embed ───────────────────────────────────────────────────────────────────

def test_embed_returns_vectors_from_client():
    fake_client = types.SimpleNamespace(
        embeddings=types.SimpleNamespace(
            create=lambda model, input: types.SimpleNamespace(
                data=[types.SimpleNamespace(embedding=[float(len(t)), 1.0]) for t in input]
            )
        )
    )
    vecs = rag._embed(["aa", "bbbb"], fake_client)
    assert vecs == [[2.0, 1.0], [4.0, 1.0]]


# ── search ───────────────────────────────────────────────────────────────────

def _seed_index(data_dir, chunks, metadata, embeddings):
    (data_dir / "rag_index.json").write_text(
        json.dumps({"chunks": chunks, "metadata": metadata}), encoding="utf-8"
    )
    np.save(str(data_dir / "rag_embeddings.npy"), np.array(embeddings, dtype=np.float32))


def test_search_missing_index_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(rag._cfg_module, "get_active_data_folder", lambda: tmp_path)
    with pytest.raises(FileNotFoundError, match="RAG index not found"):
        rag.search("anything")


def test_search_category_filter_no_match_returns_empty(monkeypatch, tmp_path):
    monkeypatch.setattr(rag._cfg_module, "get_active_data_folder", lambda: tmp_path)
    _seed_index(
        tmp_path,
        chunks=["resume chunk"],
        metadata=[{"source": "r.txt", "category": "resume"}],
        embeddings=[[1.0, 0.0]],
    )
    monkeypatch.setattr(rag, "_openai_client", lambda: object())
    monkeypatch.setattr(rag, "_embed", lambda texts, client: [[1.0, 0.0]])
    assert rag.search("q", category="nonexistent") == []


def test_search_ranks_by_cosine_similarity(monkeypatch, tmp_path):
    monkeypatch.setattr(rag._cfg_module, "get_active_data_folder", lambda: tmp_path)
    _seed_index(
        tmp_path,
        chunks=["aligned", "orthogonal", "opposite"],
        metadata=[
            {"source": "a.txt", "category": "resume"},
            {"source": "b.txt", "category": "resume"},
            {"source": "c.txt", "category": "resume"},
        ],
        embeddings=[[1.0, 0.0], [0.0, 1.0], [-1.0, 0.0]],
    )
    monkeypatch.setattr(rag, "_openai_client", lambda: object())
    # Query vector points along +x → "aligned" should rank first.
    monkeypatch.setattr(rag, "_embed", lambda texts, client: [[1.0, 0.0]])

    results = rag.search("query", n_results=3)
    assert [r["source"] for r in results] == ["a.txt", "b.txt", "c.txt"]
    assert results[0]["score"] == 1.0
    assert results[0]["text"] == "aligned"


def test_search_category_filter_match(monkeypatch, tmp_path):
    monkeypatch.setattr(rag._cfg_module, "get_active_data_folder", lambda: tmp_path)
    _seed_index(
        tmp_path,
        chunks=["resume chunk", "prep chunk"],
        metadata=[
            {"source": "r.txt", "category": "resume"},
            {"source": "p.txt", "category": "interview_prep"},
        ],
        embeddings=[[1.0, 0.0], [0.0, 1.0]],
    )
    monkeypatch.setattr(rag, "_openai_client", lambda: object())
    monkeypatch.setattr(rag, "_embed", lambda texts, client: [[0.0, 1.0]])
    results = rag.search("q", category="interview_prep")
    assert len(results) == 1
    assert results[0]["source"] == "p.txt"


# ── build_index ──────────────────────────────────────────────────────────────

def _wire_build_index(monkeypatch, resume_folder, data_folder, leetcode_folder):
    monkeypatch.setattr(rag, "_openai_client", lambda: object())
    monkeypatch.setattr(rag, "_embed", lambda texts, client: [[0.5, 0.5] for _ in texts])
    monkeypatch.setattr(rag._cfg_module, "get_active_workspace_folder", lambda: resume_folder)
    monkeypatch.setattr(rag._cfg_module, "get_active_leetcode_folder", lambda: leetcode_folder)
    monkeypatch.setattr(rag._cfg_module, "get_active_data_folder", lambda: data_folder)
    monkeypatch.setattr(rag._cfg_module, "get_active_workspace_path", lambda rel: resume_folder / rel)
    # get_config_value(key, default) → default; leetcode paths default to "" (skipped).
    monkeypatch.setattr(rag._cfg_module, "get_config_value", lambda key, default="": default)


def test_build_index_empty_returns_empty(monkeypatch, tmp_path):
    resume_folder = tmp_path / "resume"
    resume_folder.mkdir()
    data_folder = tmp_path / "data"
    leetcode_folder = tmp_path / "lc"
    leetcode_folder.mkdir()
    _wire_build_index(monkeypatch, resume_folder, data_folder, leetcode_folder)
    monkeypatch.setattr(rag._cfg_module, "MASTER_RESUME", tmp_path / "nope.txt")

    assert rag.build_index(verbose=False) == {}


def test_build_index_with_files_writes_index(monkeypatch, tmp_path):
    resume_folder = tmp_path / "resume"
    resume_folder.mkdir()
    data_folder = tmp_path / "data"
    leetcode_folder = tmp_path / "lc"
    leetcode_folder.mkdir()
    _wire_build_index(monkeypatch, resume_folder, data_folder, leetcode_folder)

    master = tmp_path / "master.txt"
    master.write_text("Master resume content that is clearly longer than the fifty char floor.", encoding="utf-8")
    monkeypatch.setattr(rag._cfg_module, "MASTER_RESUME", master)
    # A prep file in the resume root (matches the 'prep'/'interview' keyword filter).
    (resume_folder / "interview_prep.txt").write_text(
        "Interview prep notes with more than enough characters to survive chunking.", encoding="utf-8"
    )

    counts = rag.build_index(verbose=True)
    assert counts.get("resume", 0) >= 1
    assert counts.get("interview_prep", 0) >= 1
    # Index artifacts written to the data folder.
    assert (data_folder / "rag_index.json").exists()
    assert (data_folder / "rag_embeddings.npy").exists()
    saved = json.loads((data_folder / "rag_index.json").read_text(encoding="utf-8"))
    assert len(saved["chunks"]) == len(saved["metadata"]) >= 2


def test_build_index_covers_all_optional_folders(monkeypatch, tmp_path):
    resume_folder = tmp_path / "resume"
    resume_folder.mkdir()
    data_folder = tmp_path / "data"
    leetcode_folder = tmp_path / "lc"
    leetcode_folder.mkdir()
    _wire_build_index(monkeypatch, resume_folder, data_folder, leetcode_folder)
    monkeypatch.setattr(rag._cfg_module, "MASTER_RESUME", tmp_path / "absent.txt")

    body = "This file holds well over fifty characters so its chunk survives the floor."

    # Optional workspace sub-folders, each resolved via get_active_workspace_path.
    for sub in ("01-Current-Optimized", "02-Cover-Letters", "06-Reference-Materials"):
        d = resume_folder / sub
        d.mkdir()
        (d / "doc.txt").write_text(body, encoding="utf-8")
    # A MASTER file in the optimized dir must be excluded by name.
    (resume_folder / "01-Current-Optimized" / "MASTER_resume.txt").write_text(body, encoding="utf-8")

    # Prep docs + job assessment folders (relative to the resume root).
    for sub in ("08-Interview-Prep-Docs", "07-Job-Assessments"):
        d = resume_folder / sub
        d.mkdir()
        (d / "note.md").write_text(body, encoding="utf-8")
    # Assessment file dropped in the resume root.
    (resume_folder / "fitment_notes.txt").write_text(body, encoding="utf-8")

    # An unreadable entry (a directory named like a .txt file, matching the
    # prep keyword filter) exercises the read-failure `continue` branch.
    (resume_folder / "interview_broken.txt").mkdir()

    counts = rag.build_index(verbose=False)
    assert counts.get("cover_letters", 0) >= 1
    assert counts.get("reference", 0) >= 1
    assert counts.get("job_assessments", 0) >= 1
    # The MASTER-named optimized resume was filtered out, so resume chunks come
    # only from the single non-master doc.
    assert counts.get("resume", 0) >= 1
