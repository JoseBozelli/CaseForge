"""Live Claude adapter, tested against a stand-in client (no network)."""

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from caseforge.agents.contracts import EvidenceStep
from caseforge.common.errors import ConfigError
from caseforge.reasoning.claude import ClaudeReasoner, load_api_key
from caseforge.reasoning.models import CallContext, ModelSpec, ReasonerRequest, TokenUsage
from caseforge.reasoning.ports import BilledReasonerError, ReasonerCallError, ReasonerError
from caseforge.reasoning.prompts import PromptRegistry
from caseforge.reasoning.structured import StructuredCaller

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
    "additionalProperties": False,
}


class StandInClient:
    def __init__(self, response=None, error: Exception | None = None) -> None:
        self.calls: list[dict] = []
        self.messages = self
        self._response = response
        self._error = error

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return self._response


def _response(text: str, stop: str = "end_turn"):
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(input_tokens=120, output_tokens=30),
        model="claude-sonnet-5-5",
        stop_reason=stop,
    )


def _request(**params) -> ReasonerRequest:
    return ReasonerRequest(
        model=ModelSpec(provider="anthropic", model="claude-sonnet-5-5", params=params),
        template_id="evidence",
        template_version=1,
        template_sha256="a" * 64,
        prompt="Case details.",
        output_schema_name="Answer",
        output_schema=SCHEMA,
    )


def test_structured_output_mode_sends_the_schema_and_parses_the_answer() -> None:
    client = StandInClient(_response('{"answer": "yes"}'))
    response = ClaudeReasoner(client).complete(_request(max_tokens=512, temperature=0))
    (call,) = client.calls
    assert call["output_config"]["format"]["type"] == "json_schema"
    assert (call["model"], call["max_tokens"], call["temperature"]) == ("claude-sonnet-5-5", 512, 0)
    assert response.output == {"answer": "yes"}
    assert response.usage == TokenUsage(input_tokens=120, output_tokens=30)
    assert response.reported_model == "claude-sonnet-5-5"


def test_prompt_mode_puts_the_schema_in_the_prompt_and_accepts_fenced_json() -> None:
    client = StandInClient(_response('```json\n{"answer": "no"}\n```'))
    response = ClaudeReasoner(client).complete(_request(output_mode="prompt"))
    (call,) = client.calls
    assert "output_config" not in call
    assert "JSON schema" in call["messages"][0]["content"]
    assert response.output == {"answer": "no"}


@pytest.mark.parametrize("stop", ["max_tokens", "refusal"])
def test_early_stops_are_billed_failures(stop: str) -> None:
    client = StandInClient(_response('{"answer": "partial', stop=stop))
    with pytest.raises(BilledReasonerError) as info:
        ClaudeReasoner(client).complete(_request())
    assert info.value.usage.output_tokens == 30


def test_malformed_json_is_a_billed_failure() -> None:
    client = StandInClient(_response("not json at all"))
    with pytest.raises(BilledReasonerError):
        ClaudeReasoner(client).complete(_request())


def test_provider_errors_never_echo_provider_text() -> None:
    client = StandInClient(error=RuntimeError("bad request for key sk-ant-SECRET"))
    with pytest.raises(ReasonerError) as info:
        ClaudeReasoner(client).complete(_request())
    assert "SECRET" not in str(info.value)
    assert "RuntimeError" in str(info.value)


def test_api_key_loading(tmp_path: Path) -> None:
    key_file = tmp_path / "anthropic_api_key"
    key_file.write_text('# local only\nANTHROPIC_API_KEY="sk-test-1"\n', encoding="utf-8")
    assert load_api_key(key_file, {}) == "sk-test-1"
    key_file.write_text("sk-test-2\n", encoding="utf-8")
    assert load_api_key(key_file, {}) == "sk-test-2"
    assert load_api_key(key_file, {"ANTHROPIC_API_KEY": "sk-env"}) == "sk-env"
    with pytest.raises(ConfigError) as info:
        load_api_key(tmp_path / "missing", {})
    assert "sk-" not in str(info.value)


def test_billed_failures_are_charged_to_the_budget() -> None:
    usage = TokenUsage(input_tokens=500, output_tokens=40)
    charged: list[TokenUsage] = []

    class Budget:
        def before_call(self, context) -> None:
            pass

        def after_call(self, context, used) -> None:
            charged.append(used)

    class Billed:
        def complete(self, request):
            raise BilledReasonerError("Claude stopped early (max_tokens)", usage)

    caller = StructuredCaller(
        Billed(),
        PromptRegistry.from_directory(ROOT / "config" / "prompts"),
        ModelSpec(provider="fake", model="m"),
        clock=lambda: datetime(2026, 2, 1, tzinfo=UTC),
        budget=Budget(),
    )
    variables = {
        "case_id": "c",
        "question": "q",
        "steps_remaining": "1",
        "tools": "[]",
        "transcript": "[]",
    }
    with pytest.raises(ReasonerCallError):
        caller.call(
            "evidence", variables, EvidenceStep, CallContext(run_id="r", node="evidence", step=0)
        )
    assert charged == [usage]
