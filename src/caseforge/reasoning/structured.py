"""Structured model calls: render, call, validate, and record provenance."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ValidationError

from caseforge.common.hashing import canonical_json_bytes, sha256_hex
from caseforge.reasoning.models import (
    CallContext,
    LlmCallRecord,
    ModelSpec,
    ReasonerRequest,
    ReasonerResponse,
)
from caseforge.reasoning.ports import (
    CallBudget,
    OutputValidationError,
    Reasoner,
    ReasonerCallError,
    ReasonerError,
)
from caseforge.reasoning.prompts import PromptRegistry

T = TypeVar("T", bound=BaseModel)
SnapshotMode = Literal["full", "redacted", "off"]


def _safe(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", text)


def _summarize(exc: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(part) for part in err['loc']) or 'output'}: {err['msg']}"
        for err in exc.errors()
    )


class SnapshotWriter:
    """Writes per-call snapshots to a directory kept out of version control.

    full: exact request and response. redacted: the rendered prompt is replaced by
    its hash (template identity, settings and response are kept). off: nothing.
    """

    def __init__(self, directory: str | Path, mode: SnapshotMode) -> None:
        self._directory = Path(directory)
        self._mode = mode

    def write(
        self,
        context: CallContext,
        request: ReasonerRequest,
        response: ReasonerResponse | None,
    ) -> str | None:
        if self._mode == "off":
            return None
        request_data = request.model_dump(mode="json")
        if self._mode == "redacted":
            request_data["prompt"] = f"[redacted sha256:{sha256_hex(request.prompt)}]"
        relative = f"{_safe(context.run_id)}/{_safe(context.node)}-{context.step:03d}.json"
        path = self._directory / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {
            "request_sha256": request.sha256(),
            "request": request_data,
            "response": None if response is None else response.model_dump(mode="json"),
        }
        path.write_bytes(canonical_json_bytes(payload))
        return relative


@dataclass(frozen=True)
class StructuredResult(Generic[T]):
    output: T
    record: LlmCallRecord


class StructuredCaller:
    """Renders a versioned template, calls the reasoner and validates typed output."""

    def __init__(
        self,
        reasoner: Reasoner,
        prompts: PromptRegistry,
        model: ModelSpec,
        *,
        clock: Callable[[], datetime],
        snapshots: SnapshotWriter | None = None,
        budget: CallBudget | None = None,
    ) -> None:
        self._budget = budget
        self._reasoner = reasoner
        self._prompts = prompts
        self._model = model
        self._clock = clock
        self._snapshots = snapshots

    def call(
        self,
        template_id: str,
        variables: Mapping[str, str],
        output_model: type[T],
        context: CallContext,
        *,
        version: int | None = None,
    ) -> StructuredResult[T]:
        template = self._prompts.get(template_id, version)
        if template.output_schema != output_model.__name__:
            raise ValueError(
                f"template {template_id!r} expects output schema {template.output_schema!r}, "
                f"got {output_model.__name__!r}"
            )
        request = ReasonerRequest(
            model=self._model,
            template_id=template.template_id,
            template_version=template.version,
            template_sha256=template.sha256,
            prompt=template.render(variables),
            output_schema_name=output_model.__name__,
            output_schema=output_model.model_json_schema(),
        )
        base: dict[str, Any] = {
            "call_id": f"{context.run_id}:{context.node}:{context.step}",
            "run_id": context.run_id,
            "case_id": context.case_id,
            "node": context.node,
            "step": context.step,
            "template_id": template.template_id,
            "template_version": template.version,
            "template_sha256": template.sha256,
            "provider": self._model.provider,
            "model": self._model.model,
            "params": self._model.params,
            "request_sha256": request.sha256(),
            "created_at": self._clock(),
        }

        try:
            if self._budget is not None:
                self._budget.before_call(context)
            response = self._reasoner.complete(request)
        except ReasonerError as exc:
            billed = getattr(exc, "usage", None)
            if self._budget is not None and billed is not None:
                self._budget.after_call(context, billed)  # billed failures still count
            record = LlmCallRecord(
                **base,
                response_sha256=None,
                status="error",
                error=str(exc),
                usage=None,
                snapshot_ref=self._snapshot(context, request, None),
            )
            raise ReasonerCallError(str(exc), record) from exc

        if self._budget is not None:
            self._budget.after_call(context, response.usage)
        snapshot_ref = self._snapshot(context, request, response)
        try:
            output = output_model.model_validate(response.output)
        except ValidationError as exc:
            record = LlmCallRecord(
                **base,
                response_sha256=response.sha256(),
                status="invalid_output",
                error=_summarize(exc),
                usage=response.usage,
                snapshot_ref=snapshot_ref,
            )
            raise OutputValidationError(record.error or "invalid output", record) from exc

        record = LlmCallRecord(
            **base,
            response_sha256=response.sha256(),
            status="ok",
            usage=response.usage,
            snapshot_ref=snapshot_ref,
        )
        return StructuredResult(output=output, record=record)

    def _snapshot(
        self, context: CallContext, request: ReasonerRequest, response: ReasonerResponse | None
    ) -> str | None:
        if self._snapshots is None:
            return None
        return self._snapshots.write(context, request, response)
