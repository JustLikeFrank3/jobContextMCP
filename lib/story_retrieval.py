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

There is no network dependency and no embedding cost: retrieval is pure local
keyword/TF-IDF matching, which is deterministic, fast, and scales to thousands
of stories. (The separate rag.py embedding layer is intentionally not used here
because it requires an OpenAI call per retrieval.)
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path

from lib.io import _load_json

# ── Token estimation ────────────────────────────────────────────────────────
# Prefer tiktoken for accuracy; fall back to a chars/4 heuristic if unavailable
# so this module never hard-depends on the tokenizer package.
try:  # pragma: no cover - import guard
    import tiktoken

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

    def render(self) -> str:
        lines = [
            "═══ STORY RETRIEVAL DIAGNOSTICS ═══",
            f"Library size (total stories):  {self.total_stories}",
            f"Candidates considered (scored): {self.candidates_considered}",
            f"Stories selected:               {self.selected_count}",
            f"Token budget / used:            {self.token_budget} / {self.tokens_used}",
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
) -> tuple[list[dict], RetrievalDiagnostics]:
    """Retrieve the most relevant stories within a token budget.

    Args:
        role:            Target role title (query signal).
        job_description: Target JD text (query signal).
        path:            Path to personal_context.json.
        token_budget:    Max tokens the selected story block may consume.
        max_stories:     Hard cap on number of stories returned.

    Returns:
        (selected_stories, diagnostics)
    """
    index = _get_index(path)
    diag = RetrievalDiagnostics(
        total_stories=len(index.stories),
        token_budget=max(0, token_budget),
    )

    query_terms = set(tokenize(f"{role} {job_description}"))
    diag.query_terms = sorted(query_terms)
    if not index.stories or token_budget <= 0:
        return [], diag

    # Step 3: retrieve candidates (only stories sharing a query term).
    candidate_positions = index.candidate_positions(query_terms)
    diag.candidates_considered = len(candidate_positions)

    # Step 4: score only the candidate subset.
    scored: list[tuple[int, float]] = [
        (pos, index.score_position(pos, query_terms)) for pos in candidate_positions
    ]
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
