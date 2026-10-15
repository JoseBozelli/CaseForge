"""Scripted Reasoner for tests and offline development."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from caseforge.common.hashing import canonical_json_bytes
from caseforge.reasoning.models import ReasonerRequest, ReasonerResponse, TokenUsage
from caseforge.reasoning.ports import ReasonerError


def _estimate_tokens(text: str) -> int:
    """Rough estimate (four characters per token); fake usage is never billed."""
    return max(1, len(text) // 4)


class FakeReasoner:
    """Returns queued outputs per template_id, in order; records every request."""

    def __init__(
        self, script: Mapping[str, Sequence[Mapping[str, Any]]], reported_model: str = "fake-model"
    ) -> None:
        self._queues = {template_id: list(outputs) for template_id, outputs in script.items()}
        self._reported_model = reported_model
        self.requests: list[ReasonerRequest] = []

    def complete(self, request: ReasonerRequest) -> ReasonerResponse:
        self.requests.append(request)
        queue = self._queues.get(request.template_id)
        if not queue:
            raise ReasonerError(f"no scripted output left for {request.template_id!r}")
        output = dict(queue.pop(0))
        return ReasonerResponse(
            output=output,
            usage=TokenUsage(
                input_tokens=_estimate_tokens(request.prompt),
                output_tokens=_estimate_tokens(canonical_json_bytes(output).decode("utf-8")),
            ),
            reported_model=self._reported_model,
        )
