import json
from pathlib import Path

import pytest

from lib import story_retrieval as sr

def _write_stories(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "stories": [
            {"id": 1, "title": "MCP server", "tags": ["ai", "platform"], "story": "Built MCP and retrieval stack."},
            {"id": 2, "title": "Retail app", "tags": ["react"], "story": "Built consumer frontend experience."},
            {"id": 3, "title": "Creative mission", "tags": ["music", "creators"], "story": "Helped artists reach audiences."},
        ]
    }), encoding="utf-8")


def test_retrieval_diagnostics_render_and_story_index(isolated_server, tmp_path):
    p = tmp_path / "data" / "personal_context.json"
    _write_stories(p)
    idx = sr.StoryIndex(json.loads(p.read_text())["stories"])

    cands = idx.candidate_positions({"mcp", "react"})
    assert cands == {0, 1}
    assert idx.score_position(0, {"mcp"}) > 0
    assert idx.token_cost(0) > 0

    diag = sr.RetrievalDiagnostics(total_stories=3, candidates_considered=2, selected_count=1, token_budget=100, tokens_used=20)
    rendered = diag.render()
    assert "STORY RETRIEVAL DIAGNOSTICS" in rendered
    assert "Candidates considered" in rendered


def test_mission_query_expands_for_mission_language(isolated_server):
    jd = "Our mission helps creators and community share stories and ideas with fans."
    q = sr._mission_query("Platform Engineer", jd)
    assert "Mission hook expansion" in q
    assert "storytelling" in q
    assert "fandom" in q


def test_semantic_story_scores_and_blended_score(isolated_server, tmp_path, monkeypatch):
    if sr.np is None:
        pytest.skip("numpy unavailable")

    p = tmp_path / "data" / "personal_context.json"
    _write_stories(p)
    stories = json.loads(p.read_text())["stories"]
    embeddings = sr.np.array([[1.0, 0.0], [0.0, 1.0], [0.5, 0.5]], dtype=sr.np.float32)

    monkeypatch.setattr(sr, "_load_semantic_index", lambda _path: (stories, embeddings))
    monkeypatch.setattr(sr, "_embed_texts", lambda _texts, _path: [[1.0, 0.0]])

    scores = sr._semantic_story_scores("AI Engineer", "build MCP", path=p, top_k=2)
    assert 0 in scores

    idx = sr.StoryIndex(stories)
    blended = sr._blended_story_score(idx, 0, {"mcp"}, {"ai"}, 2.0, {0: 0.8}, 100.0)
    assert blended > idx.score_position(0, {"mcp"})


def test_load_semantic_index_reuses_cache_files(isolated_server, tmp_path, monkeypatch):
    if sr.np is None:
        pytest.skip("numpy unavailable")

    p = tmp_path / "data" / "personal_context.json"
    _write_stories(p)
    idx_file, emb_file = sr._semantic_cache_paths(p)

    stories = json.loads(p.read_text())["stories"]
    idx_file.write_text(json.dumps({"revision": [p.stat().st_mtime, p.stat().st_size], "model": "x", "count": len(stories)}), encoding="utf-8")
    sr.np.save(str(emb_file), sr.np.array([[1.0, 0.0], [0.0, 1.0], [0.2, 0.8]], dtype=sr.np.float32))

    out_stories, emb = sr._load_semantic_index(p)
    assert len(out_stories) == 3
    assert emb.shape[0] == 3


def test_retrieve_stories_keyword_and_semantic_paths(isolated_server, tmp_path, monkeypatch):
    p = tmp_path / "data" / "personal_context.json"
    _write_stories(p)
    sr.clear_cache()

    selected, diag = sr.retrieve_stories(
        "AI Platform Engineer",
        "Build MCP retrieval platform and agents",
        path=p,
        token_budget=400,
        max_stories=2,
        boost_tags={"ai"},
        semantic=False,
    )
    assert selected
    assert diag.candidates_considered >= 1

    monkeypatch.setattr(sr, "_semantic_scores_best_effort", lambda *_a, **_k: {2: 0.9})
    selected_sem, diag_sem = sr.retrieve_stories(
        "Platform Engineer",
        "Mission around creators and audience",
        path=p,
        token_budget=500,
        max_stories=3,
        semantic=True,
    )
    assert diag_sem.semantic_enabled is True
    assert diag_sem.semantic_candidates == 1
    assert any(s["id"] == 3 for s in selected_sem)


def test_retrieve_stories_handles_empty_budget_and_library(isolated_server, tmp_path):
    p = tmp_path / "data" / "personal_context.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"stories": []}), encoding="utf-8")
    sr.clear_cache()

    selected, diag = sr.retrieve_stories("x", "y", path=p, token_budget=0, max_stories=3)
    assert selected == []
    assert diag.token_budget == 0
