"""Knowledge provider with no documents (placeholder until a corpus is configured)."""

from __future__ import annotations

from caseforge.knowledge.ports import Passage


class EmptyKnowledgeProvider:
    def search(self, query: str, top_k: int) -> tuple[Passage, ...]:
        return ()
