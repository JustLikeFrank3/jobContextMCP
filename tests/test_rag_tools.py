import sys
import types

from tools import rag


def test_search_materials_success(monkeypatch):
    fake_rag = types.SimpleNamespace(
        search=lambda *_a, **_k: [{"text": "hit"}],
        format_results=lambda hits, title: f"{title} ({len(hits)})",
    )
    monkeypatch.setitem(sys.modules, "lib.rag", fake_rag)

    out = rag.search_materials("python")
    assert 'Results for: "python"' in out
    assert "(1)" in out


def test_search_materials_error_paths(monkeypatch):
    def _raise_key(*_a, **_k):
        raise RuntimeError("openai_api_key not set")

    def _raise_generic(*_a, **_k):
        raise RuntimeError("index missing")

    monkeypatch.setitem(sys.modules, "lib.rag", types.SimpleNamespace(search=_raise_key, format_results=lambda *_a, **_k: "x"))
    out = rag.search_materials("q")
    assert "requires an OpenAI API key" in out

    monkeypatch.setitem(sys.modules, "lib.rag", types.SimpleNamespace(search=_raise_generic, format_results=lambda *_a, **_k: "x"))
    out2 = rag.search_materials("q")
    assert out2.startswith("Search error:")
    assert "reindex_materials" in out2


def test_reindex_materials_success_and_error(monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        "lib.rag",
        types.SimpleNamespace(build_index=lambda verbose=False: {"resumes": 2, "letters": 3}),
    )
    out = rag.reindex_materials()
    assert "5 total chunks indexed" in out
    assert "resumes" in out

    def _raise_key(*_a, **_k):
        raise RuntimeError("openai_api_key not set")

    monkeypatch.setitem(sys.modules, "lib.rag", types.SimpleNamespace(build_index=_raise_key))
    out2 = rag.reindex_materials()
    assert "requires an OpenAI API key" in out2

    def _raise_generic(*_a, **_k):
        raise RuntimeError("chroma unavailable")

    monkeypatch.setitem(sys.modules, "lib.rag", types.SimpleNamespace(build_index=_raise_generic))
    out3 = rag.reindex_materials()
    assert out3.startswith("Indexing error:")
    assert "chroma unavailable" in out3


def _fake_story_retrieval(load_fn):
    return types.SimpleNamespace(clear_cache=lambda: None, _load_semantic_index=load_fn)


def test_reindex_stories_success(monkeypatch, tmp_path):
    path = tmp_path / "personal_context.json"
    monkeypatch.setitem(sys.modules, "lib.config", types.SimpleNamespace(PERSONAL_CONTEXT_FILE=path))
    monkeypatch.setitem(
        sys.modules,
        "lib.story_retrieval",
        _fake_story_retrieval(lambda p: (["s1", "s2", "s3"], types.SimpleNamespace(shape=(3, 1536)))),
    )

    out = rag.reindex_stories()
    assert "Story semantic index built" in out
    assert "3 stories embedded" in out
    assert "1536d vectors" in out
    assert "Semantic retrieval is now active" in out


def test_reindex_stories_missing_api_key(monkeypatch, tmp_path):
    def _raise_key(_p):
        raise RuntimeError("openai_api_key not configured")

    monkeypatch.setitem(sys.modules, "lib.config", types.SimpleNamespace(PERSONAL_CONTEXT_FILE=tmp_path / "pc.json"))
    monkeypatch.setitem(sys.modules, "lib.story_retrieval", _fake_story_retrieval(_raise_key))

    out = rag.reindex_stories()
    assert "requires an OpenAI API key" in out


def test_reindex_stories_generic_error(monkeypatch, tmp_path):
    def _raise(_p):
        raise RuntimeError("disk full")

    monkeypatch.setitem(sys.modules, "lib.config", types.SimpleNamespace(PERSONAL_CONTEXT_FILE=tmp_path / "pc.json"))
    monkeypatch.setitem(sys.modules, "lib.story_retrieval", _fake_story_retrieval(_raise))

    out = rag.reindex_stories()
    assert out.startswith("Story index error:")
    assert "disk full" in out


def test_register_tools():
    registered = []

    class _FakeMCP:
        def tool(self):
            def _decorator(fn):
                registered.append(fn.__name__)
                return fn

            return _decorator

    rag.register(_FakeMCP())
    assert "search_materials" in registered
    assert "reindex_materials" in registered
    assert "reindex_stories" in registered
