"""Local, scalable retrieval layer for personal-context (STAR) stories.

Why this exists
---------------
Cover-letter / resume generation must inject relevant personal stories into the
prompt. The naive approach (dump every story) blows past the model's TPM limit
once the library grows past a few dozen entries, and scoring every story on
every request does not scale.

This module implements a retrieval-first design:

  1. Build a cached inverted index over the story library (lazily, rebuilt only
     when personal_context.json changes — keyed on file mtime).
  2. Extract query terms from the role title + job description.
  3. Retrieve *candidate* stories via the inverted index — only stories that
     share at least one query term are ever scored.
  4. Score only that candidate subset (IDF-weighted; tags weighted higher).
  5. Select stories greedily within a configurable token budget.
  6. Return rich diagnostics (considered / selected / scores / token counts).

Keyword retrieval is pure local TF-IDF matching, which is deterministic, fast,
and scales to thousands of stories. Cover letters can additionally opt into a
story-only semantic retrieval pass with cached embeddings; that catches thematic
mission matches keyword search cannot see (for example an indie record label
story matching a company mission to democratize stories and knowledge).
"""
from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from lib.io import _load_json

try:  # pragma: no cover - optional semantic retrieval dependencies
    import numpy as np
    from openai import OpenAI
except Exception:  # pragma: no cover - keyword retrieval still works without these
    np = None
    OpenAI = None

# ── Token estimation ────────────────────────────────────────────────────────
# Prefer tiktoken for accuracy; fall back to a chars/4 heuristic if unavailable
# so this module never hard-depends on the tokenizer package.
try:  # pragma: no cover - import guard
    import tiktoken  # type: ignore[import-not-found]

    _ENC = tiktoken.get_encoding("cl100k_base")

    def estimate_tokens(text: str) -> int:
        if not text:
            return 0
        return len(_ENC.encode(text))
except Exception:  # pragma: no cover - fallback path
    def estimate_tokens(text: str) -> int:
        if not text:
            return 0
        return max(1, len(text) // 4)


# ── Tokenization / keywords ─────────────────────────────────────────────────

_STOPWORDS = {
    "the", "and", "for", "with", "you", "your", "our", "are", "will", "have",
    "this", "that", "from", "they", "their", "what", "when", "where", "which",
    "into", "over", "under", "about", "across", "able", "must", "should", "would",
    "role", "team", "work", "working", "experience", "years", "year", "including",
    "strong", "ability", "using", "use", "used", "build", "building", "help",
    "looking", "join", "want", "need", "well", "also", "make", "made", "such",
    "who", "how", "why", "but", "not", "all", "any", "can", "has", "was", "were",
}


def tokenize(text: str) -> list[str]:
    """Lowercase keyword tokens (length >= 3), stopwords removed.

    Keeps tech-friendly characters so tokens like ``c++``, ``c#``, ``ci/cd``,
    ``node.js`` survive reasonably.
    """
    raw = re.findall(r"[a-zA-Z][a-zA-Z0-9+#.\-/]{2,}", (text or "").lower())
    return [t for t in raw if t not in _STOPWORDS]


# Scraped job descriptions (esp. the LinkedIn share-sheet path) arrive wrapped in
# navigation chrome: URLs, markdown image/link syntax, and long opaque asset
# hashes. Left in, these flood the query with junk terms (e.g. ``auth-button``,
# ``apply-link-offsite``, a 40-char CDN hash) that dilute the real signal and can
# spuriously match. Strip them before tokenizing so retrieval ranks on prose.
_MD_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_MD_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")  # keep visible text, drop target
_URL_RE = re.compile(r"https?://\S+|www\.\S+")
_LONG_HASH_RE = re.compile(r"\b[a-z0-9]*\d[a-z0-9]*\b", re.IGNORECASE)


def _strip_query_chrome(text: str) -> str:
    """Remove URLs, markdown link/image syntax, and asset hashes from query text.

    Only used to build the retrieval query; the original JD is never mutated.
    Keeps the human-readable anchor text of markdown links so real words survive.
    """
    if not text:
        return ""
    t = _MD_IMAGE_RE.sub(" ", text)
    t = _MD_LINK_RE.sub(r"\1", t)
    t = _URL_RE.sub(" ", t)
    # Drop opaque alphanumeric hash tokens (any run mixing letters and digits),
    # which are almost always asset IDs rather than meaningful query terms.
    t = _LONG_HASH_RE.sub(" ", t)
    return t


def _load_openai_key(path: Path) -> str:
    """Best-effort config lookup without importing lib.config.

    ``path`` is usually ``data/personal_context.json``; config.json lives one
    directory above ``data`` in this project. Keeping this lookup local avoids a
    dependency cycle and keeps keyword retrieval usable when no API key exists.
    """
    cfg_path = path.parent.parent / "config.json"
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception:
        return ""
    return str(cfg.get("openai_api_key") or os.environ.get("OPENAI_API_KEY") or "")


def _embed_texts(texts: list[str], path: Path) -> list[list[float]]:
    if OpenAI is None:
        raise RuntimeError("openai package is not available")
    key = _load_openai_key(path)
    if not key:
        raise RuntimeError("openai_api_key not configured")
    client = OpenAI(api_key=key)
    response = client.embeddings.create(model="text-embedding-3-small", input=texts)
    return [item.embedding for item in response.data]


# ── Diagnostics ─────────────────────────────────────────────────────────────

@dataclass
class ScoredStory:
    story_id: int
    title: str
    score: float
    tokens: int


@dataclass
class RetrievalDiagnostics:
    total_stories: int = 0
    candidates_considered: int = 0
    selected_count: int = 0
    query_terms: list[str] = field(default_factory=list)
    scored: list[ScoredStory] = field(default_factory=list)  # all scored candidates, desc
    selected_ids: list[int] = field(default_factory=list)
    token_budget: int = 0
    tokens_used: int = 0
    semantic_enabled: bool = False
    semantic_candidates: int = 0

    def render(self) -> str:
        lines = [
            "═══ STORY RETRIEVAL DIAGNOSTICS ═══",
            f"Library size (total stories):  {self.total_stories}",
            f"Candidates considered (scored): {self.candidates_considered}",
            f"Stories selected:               {self.selected_count}",
            f"Token budget / used:            {self.token_budget} / {self.tokens_used}",
            f"Semantic retrieval:             {'on' if self.semantic_enabled else 'off'}"
            + (f" ({self.semantic_candidates} candidates)" if self.semantic_enabled else ""),
            f"Query terms ({len(self.query_terms)}): {', '.join(self.query_terms[:25])}"
            + (" …" if len(self.query_terms) > 25 else ""),
            "",
            "Ranked candidates (id · score · tokens · title):",
        ]
        if not self.scored:
            lines.append("  (none — no candidate stories shared query terms)")
        for s in self.scored:
            marker = "✓" if s.story_id in self.selected_ids else " "
            lines.append(
                f"  {marker} #{s.story_id:<4} {s.score:6.2f}  {s.tokens:>5}t  {s.title[:60]}"
            )
        return "\n".join(lines)


# ── Inverted index ──────────────────────────────────────────────────────────

class StoryIndex:
    """Inverted index over a story library for candidate retrieval + scoring.

    Built once per file revision and cached. Postings map each term to the set
    of story positions containing it, so retrieval touches only stories that
    share a query term rather than the whole library.
    """

    # Body terms get base weight 1.0; tag terms are strong relevance signals.
    _TAG_WEIGHT = 3.0
    _TITLE_WEIGHT = 2.0

    def __init__(self, stories: list[dict]) -> None:
        self.stories: list[dict] = stories
        self._postings: dict[str, set[int]] = {}
        # Per-story term-weight maps: term -> accumulated weight in that story.
        self._story_terms: list[dict[str, float]] = []
        self._doc_freq: dict[str, int] = {}
        self._token_cost: list[int] = []
        self._build()

    def _build(self) -> None:
        n = len(self.stories)
        for pos, story in enumerate(self.stories):
            weights: dict[str, float] = {}

            for t in story.get("tags", []) or []:
                # Tags may be multi-word; index each sub-token and the whole tag.
                for tok in tokenize(str(t)) or [str(t).lower()]:
                    weights[tok] = weights.get(tok, 0.0) + self._TAG_WEIGHT

            for tok in tokenize(story.get("title", "")):
                weights[tok] = weights.get(tok, 0.0) + self._TITLE_WEIGHT

            for tok in tokenize(story.get("story", "")):
                weights[tok] = weights.get(tok, 0.0) + 1.0

            self._story_terms.append(weights)
            for term in weights:
                self._postings.setdefault(term, set()).add(pos)
                self._doc_freq[term] = self._doc_freq.get(term, 0) + 1

            self._token_cost.append(estimate_tokens(_format_story(story)))

        self._n_docs = max(1, n)

    def _idf(self, term: str) -> float:
        df = self._doc_freq.get(term, 0)
        if df <= 0:
            return 0.0
        # Smoothed IDF — downweights terms common across the whole library.
        return math.log((self._n_docs + 1) / (df + 1)) + 1.0

    def candidate_positions(self, query_terms: set[str]) -> set[int]:
        """Union of postings for any query term — the only stories we score."""
        cand: set[int] = set()
        for term in query_terms:
            postings = self._postings.get(term)
            if postings:
                cand |= postings
        return cand

    def score_position(self, pos: int, query_terms: set[str]) -> float:
        weights = self._story_terms[pos]
        score = 0.0
        for term in query_terms:
            w = weights.get(term)
            if w:
                score += w * self._idf(term)
        return score

    def token_cost(self, pos: int) -> int:
        return self._token_cost[pos]


# ── Index cache (rebuilds only when the file changes) ────────────────────────

_INDEX_CACHE: dict[str, tuple[float, int, StoryIndex]] = {}


def _get_index(path: Path) -> StoryIndex:
    key = str(path)
    try:
        stat = path.stat()
        revision = (stat.st_mtime, stat.st_size)
    except OSError:
        revision = (0.0, 0)

    cached = _INDEX_CACHE.get(key)
    if cached and (cached[0], cached[1]) == revision:
        return cached[2]

    stories = _load_json(path, {"stories": []}).get("stories", [])
    index = StoryIndex(stories)
    _INDEX_CACHE[key] = (revision[0], revision[1], index)
    return index


def clear_cache() -> None:
    """Drop the cached index (call after mutating the story library in-process)."""
    _INDEX_CACHE.clear()


def _score_with_boost(
    index: "StoryIndex",
    pos: int,
    query_terms: set[str],
    boost: set[str],
    boost_factor: float,
) -> float:
    """Base relevance score, multiplied by ``boost_factor`` when the story at
    ``pos`` carries any tag in ``boost``. Kept module-level so the public
    retrieval function stays within its cognitive-complexity budget."""
    score = index.score_position(pos, query_terms)
    if boost and score > 0:
        tags = {str(t).lower() for t in (index.stories[pos].get("tags") or [])}
        if tags & boost:
            score *= boost_factor
    return score


# ── Semantic story index (cover-letter mission hooks) ───────────────────────

_SEMANTIC_CACHE: dict[str, tuple[float, int, list[dict], object]] = {}


def _semantic_cache_paths(path: Path) -> tuple[Path, Path]:
    stem = path.with_suffix("")
    return stem.with_name(stem.name + "_semantic_index.json"), stem.with_name(
        stem.name + "_semantic_embeddings.npy"
    )


def _story_semantic_text(story: dict) -> str:
    """Text embedded for semantic retrieval.

    Include title/tags/people so domain labels like music, film, creativity, and
    entrepreneurship carry semantic signal even when the story prose uses a
    different vocabulary from the target company's mission statement.
    """
    return "\n".join(
        part for part in (
            f"Title: {story.get('title', '')}",
            "Tags: " + ", ".join(str(t) for t in (story.get("tags") or [])),
            "People: " + ", ".join(str(p) for p in (story.get("people") or [])),
            f"Story: {story.get('story', '')}",
        ) if part.strip() not in {"Tags:", "People:"}
    )


def _load_semantic_index(path: Path) -> tuple[list[dict], object]:
    """Load or rebuild cached embeddings for the personal story library."""
    if np is None:
        raise RuntimeError("numpy package is not available")

    stat = path.stat()
    revision = (stat.st_mtime, stat.st_size)
    key = str(path)
    cached = _SEMANTIC_CACHE.get(key)
    if cached and (cached[0], cached[1]) == revision:
        return cached[2], cached[3]

    index_file, embed_file = _semantic_cache_paths(path)
    stories = _load_json(path, {"stories": []}).get("stories", [])

    if index_file.exists() and embed_file.exists():
        try:
            meta = json.loads(index_file.read_text(encoding="utf-8"))
            if tuple(meta.get("revision", ())) == revision:
                embeddings = np.load(str(embed_file))
                _SEMANTIC_CACHE[key] = (revision[0], revision[1], stories, embeddings)
                return stories, embeddings
        except Exception:
            pass

    texts = [_story_semantic_text(s) for s in stories]
    embeddings = np.array(_embed_texts(texts, path), dtype=np.float32)
    np.save(str(embed_file), embeddings)
    index_file.write_text(
        json.dumps(
            {
                "revision": [revision[0], revision[1]],
                "model": "text-embedding-3-small",
                "count": len(stories),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    _SEMANTIC_CACHE[key] = (revision[0], revision[1], stories, embeddings)
    return stories, embeddings


def _mission_query(role: str, job_description: str) -> str:
    """Build a compact semantic query focused on mission/product language."""
    text = _strip_query_chrome(job_description)
    mission_lines = []
    mission_terms = re.compile(
        r"\b(mission|purpose|curiosity|stories|knowledge|democratize|ideas|"
        r"community|culture|customers?|users?|artists?|creators?|platform|"
        r"understanding|expertise|access|insight)\b",
        re.IGNORECASE,
    )
    for raw in text.splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if line and mission_terms.search(line):
            mission_lines.append(line)
        if len(" ".join(mission_lines)) > 1800:
            break
    mission = "\n".join(mission_lines) or text[:1800]
    lower = text.lower()
    expansions: list[str] = []
    if any(term in lower for term in ("stories", "knowledge", "ideas", "curiosity", "understanding")):
        expansions.append(
            "Relevant personal hooks may involve storytelling, publishing, writing, "
            "music, film, independent creators, artists, overlooked voices, giving "
            "people a stage or shelf space, and democratizing access to creative work."
        )
    if any(term in lower for term in ("creator", "artist", "community", "audience", "platform")):
        expansions.append(
            "Look for ventures, communities, creative platforms, audience-building, "
            "and work that helped people reach an audience."
        )
    if any(term in lower for term in ("fan", "sports", "game", "entertainment", "media")):
        expansions.append(
            "Relevant hooks may involve fandom, entertainment, media, culture, "
            "collecting, loyalty, and emotional connection to a product."
        )
    expansion = "\n".join(expansions)
    return (
        f"Target role: {role}\n"
        "Find personal stories that create a genuine cover-letter hook for this "
        "company mission, product, brand, audience, or cultural purpose.\n"
        f"Mission hook expansion:\n{expansion}\n"
        f"Company/job mission text:\n{mission}"
    )


def _expanded_query_text(role: str, job_description: str) -> str:
    """Keyword query plus conservative mission-to-story bridge terms.

    The bridge is intentionally small and only triggers from mission/product
    language. It lets metadata tags such as music/film/creativity participate
    when a JD talks abstractly about stories, ideas, curiosity, or audiences.
    """
    cleaned = _strip_query_chrome(f"{role} {job_description}")
    lower = cleaned.lower()
    expansions: list[str] = []
    if any(term in lower for term in ("stories", "knowledge", "ideas", "curiosity", "understanding")):
        expansions.append(
            "storytelling publishing writing music film creativity creative "
            "entrepreneurship independent production artists creators audience "
            "stage platform access"
        )
    if any(term in lower for term in ("creator", "artist", "community", "audience", "platform")):
        expansions.append("community creators artists audience platform venture")
    if any(term in lower for term in ("fan", "sports", "game", "entertainment", "media")):
        expansions.append("fanboy fandom loyalty entertainment media culture")
    return "\n".join([cleaned] + expansions)


def _semantic_story_scores(
    role: str,
    job_description: str,
    *,
    path: Path,
    top_k: int,
) -> dict[int, float]:
    """Return story-position -> cosine similarity for top semantic matches."""
    if top_k <= 0 or np is None:
        return {}
    stories, embeddings = _load_semantic_index(path)
    if not stories:
        return {}
    np_mod = cast(Any, np)
    matrix = cast(Any, embeddings)
    query_vec = np_mod.array(_embed_texts([_mission_query(role, job_description)], path)[0], dtype=np_mod.float32)
    denom = np_mod.linalg.norm(matrix, axis=1) * np_mod.linalg.norm(query_vec)
    sims = np_mod.divide(
        matrix @ query_vec,
        denom,
        out=np_mod.zeros(len(stories), dtype=np_mod.float32),
        where=denom != 0,
    )
    ranked = np_mod.argsort(sims)[::-1][: min(top_k, len(stories))]
    return {int(pos): float(sims[pos]) for pos in ranked if float(sims[pos]) > 0}


def _semantic_scores_best_effort(
    role: str,
    job_description: str,
    *,
    path: Path,
    enabled: bool,
    top_k: int,
) -> dict[int, float]:
    if not enabled:
        return {}
    try:
        return _semantic_story_scores(role, job_description, path=path, top_k=top_k)
    except Exception:
        # Semantic retrieval is an enhancement, not a hard dependency. If an API
        # key/dependency/network is unavailable, preserve deterministic keyword
        # behavior rather than failing generation.
        return {}


def _blended_story_score(
    index: "StoryIndex",
    pos: int,
    query_terms: set[str],
    boost: set[str],
    boost_factor: float,
    semantic_scores: dict[int, float],
    semantic_weight: float,
) -> float:
    score = _score_with_boost(index, pos, query_terms, boost, boost_factor)
    sem = semantic_scores.get(pos, 0.0)
    if not sem:
        return score
    score += sem * semantic_weight
    tags = {str(t).lower() for t in (index.stories[pos].get("tags") or [])}
    if boost and tags & boost:
        score += sem * semantic_weight * 0.35
    return score


# ── Formatting ──────────────────────────────────────────────────────────────

def _format_story(story: dict) -> str:
    parts = [f"▪ #{story.get('id', '?')} — {story.get('title', '')}"]
    if story.get("tags"):
        parts.append(f"  Tags:   {', '.join(story['tags'])}")
    if story.get("people"):
        parts.append(f"  People: {', '.join(story['people'])}")
    parts.append(f"  {story.get('story', '')}")
    return "\n".join(parts)


def format_stories(stories: list[dict]) -> str:
    if not stories:
        return ""
    header = f"═══ PERSONAL CONTEXT ({len(stories)} most relevant stories) ═══"
    return "\n\n".join([header] + [_format_story(s) for s in stories])


# ── Public retrieval API ─────────────────────────────────────────────────────

def retrieve_stories(
    role: str,
    job_description: str,
    *,
    path: Path,
    token_budget: int,
    max_stories: int,
    boost_tags: set[str] | None = None,
    boost_factor: float = 2.5,
    semantic: bool = False,
    semantic_top_k: int = 64,
    semantic_weight: float = 260.0,
) -> tuple[list[dict], RetrievalDiagnostics]:
    """Retrieve the most relevant stories within a token budget.

    Args:
        role:            Target role title (query signal).
        job_description: Target JD text (query signal).
        path:            Path to personal_context.json.
        token_budget:    Max tokens the selected story block may consume.
        max_stories:     Hard cap on number of stories returned.
        boost_tags:      Optional set of tag names (lowercase). A candidate story
                         carrying any of these has its score multiplied by
                         ``boost_factor``. Used by the cover-letter path to let
                         human/identity/brand stories compete with work stories
                         whose literal keyword overlap is always higher.
        boost_factor:    Multiplier applied to boosted stories' scores.
        semantic:        If True, blend a cached embedding search over stories
                 into the keyword ranking. Best for cover letters where
                 a mission/brand hook may share few literal JD tokens.
        semantic_top_k:  Number of semantic candidates to merge into scoring.
        semantic_weight: Multiplier that converts cosine similarity into the
                 same rough range as keyword relevance scores.

    Returns:
        (selected_stories, diagnostics)
    """
    index = _get_index(path)
    diag = RetrievalDiagnostics(
        total_stories=len(index.stories),
        token_budget=max(0, token_budget),
    )

    boost = {t.lower() for t in (boost_tags or set())}
    query_terms = set(tokenize(_expanded_query_text(role, job_description)))
    diag.query_terms = sorted(query_terms)
    diag.semantic_enabled = semantic
    if not index.stories or token_budget <= 0:
        return [], diag

    # Step 3: retrieve candidates (only stories sharing a query term).
    candidate_positions = index.candidate_positions(query_terms)
    semantic_scores = _semantic_scores_best_effort(
        role,
        job_description,
        path=path,
        enabled=semantic,
        top_k=semantic_top_k,
    )
    candidate_positions |= set(semantic_scores)
    diag.semantic_candidates = len(semantic_scores)
    diag.candidates_considered = len(candidate_positions)

    # Step 4: score only the candidate subset. Apply the optional tag boost so
    # thematically-relevant personal stories are not buried by work stories that
    # merely share more technical vocabulary with the role title.
    scored: list[tuple[int, float]] = []
    for pos in candidate_positions:
        scored.append((
            pos,
            _blended_story_score(
                index,
                pos,
                query_terms,
                boost,
                boost_factor,
                semantic_scores,
                semantic_weight,
            ),
        ))
    scored.sort(key=lambda t: (t[1], -index.token_cost(t[0])), reverse=True)

    for pos, score in scored:
        story = index.stories[pos]
        diag.scored.append(
            ScoredStory(
                story_id=int(story.get("id", pos)),
                title=str(story.get("title", "")),
                score=round(score, 4),
                tokens=index.token_cost(pos),
            )
        )

    # Step 5: greedy selection within the token budget. We iterate in score
    # order and skip (rather than stop at) a story too large for the remaining
    # budget, so we keep packing the next-most-relevant stories that still fit.
    selected: list[dict] = []
    used = 0
    for pos, _score in scored:
        if len(selected) >= max_stories:
            break
        cost = index.token_cost(pos)
        if used + cost > token_budget:
            continue
        selected.append(index.stories[pos])
        used += cost

    diag.selected_count = len(selected)
    diag.selected_ids = [int(s.get("id", -1)) for s in selected]
    diag.tokens_used = used
    return selected, diag
