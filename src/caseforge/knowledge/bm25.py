"""Deterministic BM25 retrieval.

Tokenizer simple-en-v1: lowercase, ASCII letters and digits, a fixed stopword list,
no stemming. Scores use Okapi BM25 with a non-negative IDF. Ties are broken by key.
Documents scoring below min_score are withheld (abstention).
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Iterable, Sequence
from typing import Final

from caseforge.knowledge.corpus import Chunk
from caseforge.knowledge.ports import Passage

TOKENIZER_VERSION: Final = "simple-en-v1"
_TOKEN = re.compile(r"[a-z0-9]+")
_STOPWORDS: Final = frozenset(
    [
        "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
        "has", "have", "if", "in", "is", "it", "its", "of", "on", "or",
        "that", "the", "this", "to", "was", "were", "which", "who", "with",
    ]
)  # fmt: skip


def tokenize(text: str) -> list[str]:
    return [token for token in _TOKEN.findall(text.lower()) if token not in _STOPWORDS]


class Bm25Index:
    """BM25 over (key, text) documents; search returns (score, position) pairs."""

    def __init__(
        self, documents: Sequence[tuple[str, str]], *, k1: float, b: float, min_score: float
    ) -> None:
        self._keys = [key for key, _ in documents]
        self._k1, self._b, self._min_score = k1, b, min_score
        self._terms = [Counter(tokenize(text)) for _, text in documents]
        self._lengths = [sum(terms.values()) for terms in self._terms]
        self._average = (sum(self._lengths) / len(self._lengths)) if self._lengths else 1.0
        document_frequency = Counter(term for terms in self._terms for term in terms)
        n = len(documents)
        self._idf = {
            term: math.log((n - df + 0.5) / (df + 0.5) + 1.0)
            for term, df in document_frequency.items()
        }

    def search(self, query: str, top_k: int) -> list[tuple[float, int]]:
        terms = sorted(set(tokenize(query)))
        if not terms or top_k < 1:
            return []
        scored: list[tuple[float, int]] = []
        for position, (counts, length) in enumerate(zip(self._terms, self._lengths, strict=True)):
            norm = self._k1 * (1 - self._b + self._b * length / self._average)
            score = sum(
                self._idf[t] * counts[t] * (self._k1 + 1) / (counts[t] + norm)
                for t in terms
                if counts[t]
            )
            if score > 0 and score >= self._min_score:
                scored.append((round(score, 6), position))
        scored.sort(key=lambda item: (-item[0], self._keys[item[1]]))
        return scored[:top_k]


class Bm25KnowledgeProvider:
    """KnowledgeProvider that ranks corpus chunks by BM25 and abstains below min_score."""

    def __init__(self, chunks: Iterable[Chunk], *, k1: float, b: float, min_score: float) -> None:
        self._chunks = tuple(chunks)
        self._index = Bm25Index(
            [(c.chunk_id, f"{c.heading}\n{c.text}") for c in self._chunks],
            k1=k1,
            b=b,
            min_score=min_score,
        )

    def search(self, query: str, top_k: int) -> tuple[Passage, ...]:
        return tuple(
            Passage(
                doc_id=chunk.doc_id,
                doc_version=chunk.doc_version,
                chunk_id=chunk.chunk_id,
                title=f"{chunk.title}: {chunk.heading}",
                text=chunk.text,
                score=score,
            )
            for score, chunk in (
                (score, self._chunks[position])
                for score, position in self._index.search(query, top_k)
            )
        )
