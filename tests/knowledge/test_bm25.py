"""Retrieval tests: relevance on the shipped corpus, abstention and determinism."""

from pathlib import Path

import pytest

from caseforge.knowledge.bm25 import Bm25KnowledgeProvider, tokenize
from caseforge.knowledge.corpus import load_corpus

CORPUS_DIR = Path(__file__).resolve().parents[2] / "config" / "knowledge" / "policies"


@pytest.fixture(scope="module")
def provider() -> Bm25KnowledgeProvider:
    chunks = load_corpus(CORPUS_DIR).chunks
    return Bm25KnowledgeProvider(chunks, k1=1.5, b=0.75, min_score=1.0)


def test_tokenizer_lowercases_and_drops_stopwords() -> None:
    assert tokenize("The Owner's, overdue TASKS!") == ["owner", "s", "overdue", "tasks"]


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("owner has several overdue tasks", "task-follow-up#reassignment"),
        ("wrong document type was uploaded", "document-requests#wrong-document-received"),
        ("who must approve a policy exception", "policy-exceptions#approval-required"),
        ("evidence is conflicting", "escalation#when-to-escalate"),
        ("case was reopened after closing", "case-closure#reopened-cases"),
    ],
)
def test_most_relevant_section_ranks_first(provider, query: str, expected: str) -> None:
    assert provider.search(query, top_k=3)[0].chunk_id == expected


def test_unrelated_query_abstains(provider) -> None:
    assert provider.search("quarterly marketing budget", top_k=3) == ()


def test_stopword_only_query_returns_nothing(provider) -> None:
    assert provider.search("the of and", top_k=3) == ()


def test_results_are_deterministic_sorted_and_capped(provider) -> None:
    first = provider.search("overdue task reminder owner", top_k=2)
    assert first == provider.search("overdue task reminder owner", top_k=2)
    assert len(first) == 2
    assert first[0].score >= first[1].score


def test_passages_carry_provenance(provider) -> None:
    passage = provider.search("evidence is conflicting", top_k=1)[0]
    assert (passage.doc_id, passage.doc_version) == ("escalation", 1)
    assert passage.title == "Escalation procedure: When to escalate"
    assert passage.text.startswith("Escalate a case")
