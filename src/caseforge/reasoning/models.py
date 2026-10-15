"""Reasoner request/response contracts and the provenance record of each model call."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from caseforge.common.hashing import sha256_hex
from caseforge.events.envelope import NonEmptyStr, Sha256Hex, UtcDatetime


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ModelSpec(_Frozen):
    """Provider, model and generation parameters used for a call."""

    provider: NonEmptyStr
    model: NonEmptyStr
    params: dict[str, JsonValue] = Field(default_factory=dict)


class ReasonerRequest(_Frozen):
    """Everything sent to a reasoner; its hash identifies the request for replay."""

    model: ModelSpec
    template_id: NonEmptyStr
    template_version: int = Field(ge=1)
    template_sha256: Sha256Hex
    prompt: str
    output_schema_name: NonEmptyStr
    output_schema: dict[str, JsonValue]

    def sha256(self) -> str:
        return sha256_hex(self.model_dump(mode="json"))


class TokenUsage(_Frozen):
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)


class ReasonerResponse(_Frozen):
    output: dict[str, JsonValue]
    usage: TokenUsage
    reported_model: NonEmptyStr

    def sha256(self) -> str:
        return sha256_hex(self.model_dump(mode="json"))


class CallContext(_Frozen):
    """Where in an execution a call happens."""

    run_id: NonEmptyStr
    case_id: NonEmptyStr | None = None
    node: NonEmptyStr
    step: int = Field(ge=0)


CallStatus = Literal["ok", "invalid_output", "error"]


class LlmCallRecord(_Frozen):
    """Provenance of one model call. Contains hashes and references, never secrets."""

    call_id: NonEmptyStr
    run_id: NonEmptyStr
    case_id: NonEmptyStr | None
    node: NonEmptyStr
    step: int
    template_id: NonEmptyStr
    template_version: int
    template_sha256: Sha256Hex
    provider: NonEmptyStr
    model: NonEmptyStr
    params: dict[str, JsonValue]
    serialization: Literal["canonical-json-v1"] = "canonical-json-v1"
    request_sha256: Sha256Hex
    response_sha256: Sha256Hex | None
    status: CallStatus
    error: str | None = None
    usage: TokenUsage | None
    cost_usd: float | None = None
    snapshot_ref: str | None = None
    created_at: UtcDatetime
