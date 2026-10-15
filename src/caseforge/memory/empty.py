"""Episode provider with no history (placeholder until episodic memory exists)."""

from __future__ import annotations

from caseforge.memory.ports import EpisodeSummary


class EmptyEpisodeProvider:
    def search(
        self, tenant_id: str, query: str, top_k: int, exclude_case_id: str | None = None
    ) -> tuple[EpisodeSummary, ...]:
        return ()
