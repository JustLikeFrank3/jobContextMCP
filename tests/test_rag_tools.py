import sys
import types

from tools import rag


def test_search_materials_success(monkeypatch):
    fake_rag = types.SimpleNamespace(
        search=lambda *_a, **_k: [{"text": "hit"}],
        format_results=lambda hits, title: f"{title} ({len(hits)})",
    )
    monkeypatch.setitem(sys.modules, "rag", fake_rag)

    out = rag.search_materials("python")
    assert 'Results for: "python"' in out
    assert "(1)" in out


def test_search_materials_error_paths(monkeypatch):
    def _raise_key(*_a, **_k):
        raise RuntimeError("openai_api_key not set")

    def _raise_generic(*_a, **_k):
        raise RuntimeError("index missing")

    monkeypatch.setitem(sys.modules, "rag", types.SimpleNamespace(search=_raise_key, format_results=lambda *_a, **_k: "x"))
    out = rag.search_materials("q")
    assert "requires an OpenAI API key" in out

    monkeypatch.setitem(sys.modules, "rag", types.SimpleNamespace(search=_raise_generic, format_results=lambda *_a, **_k: "x"))
    out2 = rag.search_materials("q")
    assert out2.startswith("Search error:")
    assert "reindex_materials" in out2


def test_reindex_materials_success_and_error(monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        "rag",
        types.SimpleNamespace(build_index=lambda verbose=False: {"resumes": 2, "letters": 3}),
    )
    out = rag.reindex_materials()
    assert "5 total chunks indexed" in out
    assert "resumes" in out

    def _raise_key(*_a, **_k):
        raise RuntimeError("openai_api_key not set")

    monkeypatch.setitem(sys.modules, "rag", types.SimpleNamespace(build_index=_raise_key))
    out2 = rag.reindex_materials()
    assert "requires an OpenAI API key" in out2


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
