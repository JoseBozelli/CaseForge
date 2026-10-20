"""Live reasoner for the Claude API. Used only when explicitly configured.

Generation settings come from the request's model params (part of the request hash):
max_tokens (default 2048), output_mode ("json_schema" or "prompt"), and temperature
when present. Errors never include the API key or raw provider messages.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from caseforge.common.errors import ConfigError
from caseforge.reasoning.models import ReasonerRequest, ReasonerResponse, TokenUsage
from caseforge.reasoning.ports import BilledReasonerError, ReasonerError

KEY_NAME = "ANTHROPIC_API_KEY"


def load_api_key(path: Path, environ: Mapping[str, str]) -> str:
    """Read the key from the environment, else from a file holding KEY=value or a bare key."""
    if environ.get(KEY_NAME, "").strip():
        return environ[KEY_NAME].strip()
    if not path.is_file():
        raise ConfigError(f"no API key: set {KEY_NAME} or add {KEY_NAME}=... to {path.name}")
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            name, _, value = line.partition("=")
            if name.strip().removeprefix("export ").strip() != KEY_NAME:
                continue
            line = value.strip()
        key = line.strip().strip('"').strip("'")
        if key:
            return key
    raise ConfigError(f"{path.name} contains no {KEY_NAME}")


def _api_schema(schema: Mapping[str, Any]) -> dict[str, Any]:
    """Adapt a JSON schema to what structured outputs accept, when the SDK offers it."""
    try:
        from anthropic import transform_schema
    except ImportError:  # older SDK: send the schema as is
        return dict(schema)
    return transform_schema(dict(schema))


def _parse_json(text: str) -> dict[str, Any]:
    body = text.strip()
    if body.startswith("```"):
        body = body.strip("`")
        body = body.removeprefix("json").strip()
    value = json.loads(body)
    if not isinstance(value, dict):
        raise ValueError("expected a JSON object")
    return value


class ClaudeReasoner:
    def __init__(self, client: Any) -> None:
        self._client = client

    def complete(self, request: ReasonerRequest) -> ReasonerResponse:
        params = dict(request.model.params)
        mode = params.get("output_mode", "json_schema")
        prompt = request.prompt
        kwargs: dict[str, Any] = {
            "model": request.model.model,
            "max_tokens": int(params.get("max_tokens", 2048)),
        }
        if "temperature" in params:
            kwargs["temperature"] = params["temperature"]
        if mode == "json_schema":
            try:
                schema = _api_schema(request.output_schema)
            except ValueError as exc:  # our own schema problem: safe and useful to report
                raise ReasonerError(
                    f"output schema {request.output_schema_name} not supported ({exc})"
                ) from None
            kwargs["output_config"] = {"format": {"type": "json_schema", "schema": schema}}
        elif mode == "prompt":
            prompt += (
                "\n\nRespond with only a JSON object that matches this JSON schema:\n"
                + json.dumps(request.output_schema, sort_keys=True)
            )
        else:
            raise ReasonerError(f"unknown output_mode {mode!r}")
        kwargs["messages"] = [{"role": "user", "content": prompt}]

        try:
            response = self._client.messages.create(**kwargs)
        except Exception as exc:  # never surface provider text: it may echo request data
            raise ReasonerError(f"Claude API call failed ({type(exc).__name__})") from None

        usage = TokenUsage(
            input_tokens=int(response.usage.input_tokens),
            output_tokens=int(response.usage.output_tokens),
        )
        stop = getattr(response, "stop_reason", None)
        if stop in ("max_tokens", "refusal"):
            raise BilledReasonerError(f"Claude stopped early ({stop})", usage)
        text = "".join(
            block.text for block in response.content if getattr(block, "type", None) == "text"
        )
        try:
            output = _parse_json(text)
        except ValueError:
            raise BilledReasonerError("Claude returned no valid JSON object", usage) from None
        return ReasonerResponse(output=output, usage=usage, reported_model=str(response.model))
