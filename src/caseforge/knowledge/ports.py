"""Knowledge retrieval port: versioned passages with provenance."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from caseforge.events.envelope import NonEmptyStr


class Passage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    doc_id: NonEmptyStr
    doc_version: int = Field(ge=1)
    chunk_id: NonEmptyStr
    title: NonEmptyStr
    text: NonEmptyStr
    score: float


class KnowledgeProvider(Protocol):
    def search(self, query: str, top_k: int) -> tuple[Passage, ...]: ...
