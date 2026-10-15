"""Response cassettes: record live responses, replay them exactly, never fall back."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from caseforge.common.hashing import canonical_json_bytes
from caseforge.reasoning.models import ReasonerRequest, ReasonerResponse
from caseforge.reasoning.ports import Reasoner, ReplayMismatchError


class Cassette:
    """JSONL file of responses keyed by request hash; repeats keep their call order."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def append(self, request_sha256: str, response: ReasonerResponse) -> None:
        line = canonical_json_bytes(
            {"request_sha256": request_sha256, "response": response.model_dump(mode="json")}
        ).decode("utf-8")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(line + "\n")

    def load(self) -> dict[str, list[ReasonerResponse]]:
        recorded: dict[str, list[ReasonerResponse]] = {}
        if not self.path.exists():
            return recorded
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                entry = json.loads(line)
                response = ReasonerResponse.model_validate(entry["response"])
                recorded.setdefault(entry["request_sha256"], []).append(response)
        return recorded


class RecordingReasoner:
    """Wraps a reasoner and appends every response to a cassette."""

    def __init__(self, inner: Reasoner, cassette: Cassette) -> None:
        self._inner = inner
        self._cassette = cassette

    def complete(self, request: ReasonerRequest) -> ReasonerResponse:
        response = self._inner.complete(request)
        self._cassette.append(request.sha256(), response)
        return response


class ReplayReasoner:
    """Returns recorded responses for identical requests, in their original order."""

    def __init__(self, cassette: Cassette) -> None:
        self._recorded = cassette.load()
        self._used: Counter[str] = Counter()

    def complete(self, request: ReasonerRequest) -> ReasonerResponse:
        digest = request.sha256()
        responses = self._recorded.get(digest, [])
        occurrence = self._used[digest]
        if occurrence >= len(responses):
            raise ReplayMismatchError(
                f"no recorded response for request {digest[:12]} (occurrence {occurrence + 1})"
            )
        self._used[digest] += 1
        return responses[occurrence]
