import types

import pytest

from tools import langgraph_pipeline as lp


def _resp(text: str):
    return types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=text))])


def test_load_context_node_populates_state(isolated_server, monkeypatch):
    monkeypatch.setattr(lp, "get_tone_profile", lambda: "TONE")
    monkeypatch.setattr(lp, "get_star_story_context", lambda tag, company, role: f"{tag}-{company}-{role}")

    out = lp.load_context_node({"role": "AI Engineer", "company": "Acme"})
    assert out["tone_profile"] == "TONE"
    assert "cloud_migration" in out["star_stories"]
    assert out["revision_count"] == 0


def test_retrieve_node_deduplicates_hits(isolated_server, monkeypatch):
    import sys

    fake_rag = types.SimpleNamespace(
        search=lambda q, n_results=5: [{"text": "A", "score": 1}] if "RAG" not in q else [{"text": "A", "score": 0.9}, {"text": "B", "score": 0.8}],
        format_results=lambda rows, _label: "|".join(sorted(h["text"] for h in rows)),
    )
    monkeypatch.setitem(sys.modules, "rag", fake_rag)

    out = lp.retrieve_node({"job_description": "Build platform APIs"})
    assert out["retrieved_context"] in {"A|B", "B|A"}


def test_draft_review_and_revise_nodes(isolated_server, monkeypatch):
    monkeypatch.setattr(lp, "_get_client", lambda: object())
    monkeypatch.setattr(lp, "_model", lambda: "m")
    monkeypatch.setattr(lp.config, "get_active_master_resume_path", lambda: type("P", (), {})())
    monkeypatch.setattr(lp, "_read", lambda _p: "MASTER")

    monkeypatch.setattr(lp, "create_chat_completion", lambda *_a, **_k: _resp("DRAFT"))
    draft = lp.draft_node({
        "company": "Acme", "role": "Engineer", "job_description": "JD", "retrieved_context": "CTX",
        "star_stories": "STAR", "tone_profile": "TONE"
    })
    assert draft["draft"] == "DRAFT"

    monkeypatch.setattr(lp, "create_chat_completion", lambda *_a, **_k: _resp("APPROVED"))
    review_ok = lp.review_node({"role": "Engineer", "company": "Acme", "draft": "D"})
    assert review_ok["approved"] is True

    monkeypatch.setattr(lp, "create_chat_completion", lambda *_a, **_k: _resp("Fix bullets"))
    review_bad = lp.review_node({"role": "Engineer", "company": "Acme", "draft": "D"})
    assert review_bad["approved"] is False

    monkeypatch.setattr(lp, "create_chat_completion", lambda *_a, **_k: _resp("REVISED"))
    revised = lp.revise_node({"review_notes": "Fix", "draft": "D", "revision_count": 1})
    assert revised["draft"] == "REVISED"
    assert revised["revision_count"] == 2


def test_route_after_review_logic(isolated_server):
    assert lp.route_after_review({"approved": True, "revision_count": 0}) == "finalize"
    assert lp.route_after_review({"approved": False, "revision_count": 2}) == "finalize"
    assert lp.route_after_review({"approved": False, "revision_count": 1}) == "revise"


def test_generate_resume_agent_fallback_and_pipeline(isolated_server, monkeypatch):
    monkeypatch.setattr(lp, "_get_client", lambda: None)
    monkeypatch.setattr("tools.generate.generate_resume", lambda *a, **k: "fallback-resume")
    assert lp.generate_resume_agent("Acme", "Engineer", "JD") == "fallback-resume"

    monkeypatch.setattr(lp, "_get_client", lambda: object())

    class _App:
        def invoke(self, state):
            state["draft"] = "FINAL"
            state["revision_count"] = 1
            state["review_notes"] = "Looks good"
            return state

    monkeypatch.setattr(lp, "_build_graph", lambda: _App())
    out = lp.generate_resume_agent("Acme", "Engineer", "JD")
    assert "LangGraph pipeline complete" in out
    assert "FINAL" in out


def test_build_graph_compiles(isolated_server):
    app = lp._build_graph()
    assert hasattr(app, "invoke")
