
def search_materials(query: str, category: str = "") -> str:
    """Semantic search across all job search materials (resumes, cover letters, interview prep, LeetCode notes, reference files). Optionally filter by category. Requires OpenAI API key and a built index — run reindex_materials() first if needed."""
    try:
        from lib.rag import search, format_results

        hits = search(query, category=category or None, n_results=6)
        return format_results(hits, f'Results for: "{query}"')
    except Exception as e:
        if "openai_api_key" in str(e).lower() or "not set" in str(e).lower():
            return (
                "RAG search requires an OpenAI API key.\n"
                "Add 'openai_api_key' to config.json, then run reindex_materials()."
            )
        return f"Search error: {e}\nTry running reindex_materials() first."



def reindex_stories() -> str:
    """Build (or rebuild) the semantic embedding index for the personal story library.

    This enables semantic story retrieval during cover letter generation — stories
    that share mission/brand language with a job description but few literal keywords
    (e.g. an indie-label story for a 'democratize knowledge' company) will now score
    correctly. Run this after adding new stories via log_personal_story() or
    ingest_anecdote(). Requires an OpenAI API key set in config.json.
    """
    try:
        from lib import config
        from lib.story_retrieval import _load_semantic_index, clear_cache

        clear_cache()
        path = config.PERSONAL_CONTEXT_FILE
        stories, embeddings = _load_semantic_index(path)
        import numpy as np  # already imported inside story_retrieval — safe here
        n = len(stories)
        shape = getattr(embeddings, "shape", (n,))
        return (
            f"✓ Story semantic index built.\n"
            f"  {n} stories embedded  ({shape[-1] if len(shape) > 1 else '?'}d vectors)\n"
            f"  Index written to {path.parent}/\n\n"
            f"Semantic retrieval is now active for cover letter generation."
        )
    except Exception as e:
        if "openai_api_key" in str(e).lower() or "not configured" in str(e).lower():
            return (
                "Story indexing requires an OpenAI API key.\n"
                "Add 'openai_api_key' to config.json and try again."
            )
        return f"Story index error: {e}"


def reindex_materials() -> str:
    """Rebuild the semantic search index over all job search materials AND the personal
    story library. Run this after adding new resumes, cover letters, prep files, or
    stories. Requires an OpenAI API key set in config.json."""
    try:
        from lib.rag import build_index

        counts = build_index(verbose=False)
        total = sum(counts.values())
        lines = [f"✓ Materials index built. {total} total chunks indexed:", ""]
        for cat, count in counts.items():
            lines.append(f"  {cat:<16} {count} chunks")
        lines += ["", "You can now use search_materials() for semantic search."]
        mat_result = "\n".join(lines)
    except Exception as e:
        if "openai_api_key" in str(e).lower() or "not set" in str(e).lower():
            return (
                "Indexing requires an OpenAI API key.\n"
                "Add 'openai_api_key' to config.json and try again."
            )
        return f"Indexing error: {e}"

    story_result = reindex_stories()
    return f"{mat_result}\n\n{story_result}"


def register(mcp) -> None:
    mcp.tool()(search_materials)
    mcp.tool()(reindex_materials)
    mcp.tool()(reindex_stories)
