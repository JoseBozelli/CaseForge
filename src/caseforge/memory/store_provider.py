"""Episode search over the record store: one tenant at a time, current case excluded."""

from __future__ import annotations

from caseforge.knowledge.bm25 import Bm25Index
from caseforge.memory.ports import EpisodeSummary
from caseforge.persistence.ports import RecordStore


class StoreEpisodeProvider:
    def __init__(self, store: RecordStore, *, k1: float, b: float, min_score: float) -> None:
        self._store = store
        self._k1, self._b, self._min_score = k1, b, min_score

    def search(
        self, tenant_id: str, query: str, top_k: int, exclude_case_id: str | None = None
    ) -> tuple[EpisodeSummary, ...]:
        episodes = [
            e for e in self._store.episodes_for_tenant(tenant_id) if e.case_id != exclude_case_id
        ]
        index = Bm25Index(
            [(e.run_id, e.summary) for e in episodes],
            k1=self._k1,
            b=self._b,
            min_score=self._min_score,
        )
        return tuple(
            EpisodeSummary(
                episode_id=episodes[position].run_id,
                case_id=episodes[position].case_id,
                summary=episodes[position].summary,
                action_type=episodes[position].action_type,
                outcome_status=episodes[position].outcome_status,
                score=score,
            )
            for score, position in index.search(query, top_k)
        )
