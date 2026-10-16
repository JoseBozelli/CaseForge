"""Serialization of stored records (canonical-json-v1) and their content hashes."""

from __future__ import annotations

import dataclasses
import json

from pydantic import BaseModel

from caseforge.common.hashing import canonical_json_bytes, sha256_hex
from caseforge.events.envelope import EventEnvelope
from caseforge.events.mapping import Rejection, RejectionCode
from caseforge.events.vocabulary import Violation, ViolationCode


def encode_model(model: BaseModel) -> tuple[str, str]:
    """Return (canonical JSON payload, sha256) for any record model."""
    data = model.model_dump(mode="json")
    return canonical_json_bytes(data).decode("utf-8"), sha256_hex(data)


def encode_event(event: EventEnvelope) -> tuple[str, str]:
    """Return (payload, sha256) for an event."""
    return encode_model(event)


def event_sha256(event: EventEnvelope) -> str:
    return encode_event(event)[1]


def decode_event(payload: str) -> EventEnvelope:
    return EventEnvelope.model_validate_json(payload)


def rejection_key(rejection: Rejection) -> tuple[str, str, str, int, str]:
    return (
        rejection.source_system,
        rejection.source_event_id,
        rejection.mapping_id,
        rejection.mapping_version,
        rejection.raw_sha256,
    )


def encode_rejection(rejection: Rejection) -> str:
    return canonical_json_bytes(dataclasses.asdict(rejection)).decode("utf-8")


def decode_rejection(payload: str) -> Rejection:
    data = json.loads(payload)
    data["code"] = RejectionCode(data["code"])
    data["violations"] = tuple(
        Violation(code=ViolationCode(item["code"]), detail=item["detail"])
        for item in data["violations"]
    )
    return Rejection(**data)
