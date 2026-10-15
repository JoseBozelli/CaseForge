"""Tests for structured calls, call provenance, snapshots and exact replay."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import BaseModel, Field

from caseforge.common.hashing import canonical_json_bytes
from caseforge.reasoning.fake import FakeReasoner
from caseforge.reasoning.models import CallContext, ModelSpec
from caseforge.reasoning.ports import OutputValidationError, ReasonerCallError, ReplayMismatchError
from caseforge.reasoning.prompts import PromptRegistry
from caseforge.reasoning.replay import Cassette, RecordingReasoner, ReplayReasoner
from caseforge.reasoning.structured import SnapshotWriter, StructuredCaller

FIXED = datetime(2026, 1, 5, 9, 0, tzinfo=UTC)
MODEL = ModelSpec(provider="fake", model="fake-model", params={"temperature": 0.0})
CONTEXT = CallContext(run_id="run-0001", case_id="case-0001", node="evidence", step=0)
VARIABLES = {"case_id": "case-0001", "events": "task.delayed"}
GOOD = {"summary": "Task overdue.", "confidence": 0.8}
SECOND = {"summary": "Still overdue.", "confidence": 0.6}
PROMPT = (
    "---\n"
    "id: probe\n"
    "version: 1\n"
    "purpose: Test prompt.\n"
    "output_schema: ProbeFinding\n"
    "---\n"
    "Case $case_id has events: $events\n"
)


class ProbeFinding(BaseModel):
    summary: str
    confidence: float = Field(ge=0, le=1)


class OtherOutput(BaseModel):
    value: int


def _registry(directory: Path, text: str = PROMPT) -> PromptRegistry:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "probe.v1.md").write_text(text, encoding="utf-8")
    return PromptRegistry.from_directory(directory)


@pytest.fixture
def prompts(tmp_path: Path) -> PromptRegistry:
    return _registry(tmp_path / "prompts")


def _caller(prompts, reasoner, model=MODEL, snapshots=None) -> StructuredCaller:
    return StructuredCaller(reasoner, prompts, model, clock=lambda: FIXED, snapshots=snapshots)


def test_call_returns_validated_output_and_record(prompts) -> None:
    result = _caller(prompts, FakeReasoner({"probe": [GOOD]})).call(
        "probe", VARIABLES, ProbeFinding, CONTEXT
    )
    assert result.output == ProbeFinding(**GOOD)
    record = result.record
    assert record.call_id == "run-0001:evidence:0"
    assert record.status == "ok"
    assert record.template_sha256 == prompts.get("probe").sha256
    assert (record.provider, record.model) == ("fake", "fake-model")
    assert record.usage is not None and record.usage.input_tokens > 0
    assert record.created_at == FIXED
    assert record.snapshot_ref is None


def test_request_and_response_hashes_are_deterministic(prompts) -> None:
    first = _caller(prompts, FakeReasoner({"probe": [GOOD]})).call(
        "probe", VARIABLES, ProbeFinding, CONTEXT
    )
    second = _caller(prompts, FakeReasoner({"probe": [GOOD]})).call(
        "probe", VARIABLES, ProbeFinding, CONTEXT
    )
    assert first.record == second.record


def test_request_hash_changes_with_inputs_and_settings(prompts) -> None:
    def digest(variables, model):
        caller = _caller(prompts, FakeReasoner({"probe": [GOOD]}), model=model)
        return caller.call("probe", variables, ProbeFinding, CONTEXT).record.request_sha256

    base = digest(VARIABLES, MODEL)
    assert digest({**VARIABLES, "events": "none"}, MODEL) != base
    warmer = MODEL.model_copy(update={"params": {"temperature": 0.7}})
    assert digest(VARIABLES, warmer) != base


def test_template_change_changes_hashes(tmp_path: Path) -> None:
    original = _registry(tmp_path / "a")
    edited = _registry(tmp_path / "b", PROMPT.replace("has events", "shows events"))
    records = [
        _caller(registry, FakeReasoner({"probe": [GOOD]}))
        .call("probe", VARIABLES, ProbeFinding, CONTEXT)
        .record
        for registry in (original, edited)
    ]
    assert records[0].template_sha256 != records[1].template_sha256
    assert records[0].request_sha256 != records[1].request_sha256


def test_invalid_output_raises_with_record(prompts) -> None:
    caller = _caller(prompts, FakeReasoner({"probe": [{"summary": "x", "confidence": 3}]}))
    with pytest.raises(OutputValidationError) as info:
        caller.call("probe", VARIABLES, ProbeFinding, CONTEXT)
    assert info.value.record.status == "invalid_output"
    assert "confidence" in (info.value.record.error or "")


def test_reasoner_failure_raises_with_error_record(prompts) -> None:
    with pytest.raises(ReasonerCallError) as info:
        _caller(prompts, FakeReasoner({"probe": []})).call(
            "probe", VARIABLES, ProbeFinding, CONTEXT
        )
    assert info.value.record.status == "error"
    assert info.value.record.response_sha256 is None


def test_output_schema_mismatch_rejected(prompts) -> None:
    with pytest.raises(ValueError, match="expects output schema"):
        _caller(prompts, FakeReasoner({"probe": [GOOD]})).call(
            "probe", VARIABLES, OtherOutput, CONTEXT
        )


@pytest.mark.parametrize("mode", ["full", "redacted", "off"])
def test_snapshot_modes(prompts, tmp_path: Path, mode: str) -> None:
    directory = tmp_path / "snapshots"
    caller = _caller(
        prompts, FakeReasoner({"probe": [GOOD]}), snapshots=SnapshotWriter(directory, mode)
    )
    record = caller.call("probe", VARIABLES, ProbeFinding, CONTEXT).record
    if mode == "off":
        assert record.snapshot_ref is None
        assert not directory.exists()
        return
    assert record.snapshot_ref == "run-0001/evidence-000.json"
    data = json.loads((directory / record.snapshot_ref).read_text(encoding="utf-8"))
    assert data["request_sha256"] == record.request_sha256
    assert data["response"]["output"] == GOOD
    prompt_text = data["request"]["prompt"]
    if mode == "full":
        assert "Case case-0001" in prompt_text
    else:
        assert prompt_text.startswith("[redacted sha256:")
        assert "case-0001" not in prompt_text


def test_replay_reproduces_recorded_call(prompts, tmp_path: Path) -> None:
    cassette = Cassette(tmp_path / "cassette.jsonl")
    recording = RecordingReasoner(FakeReasoner({"probe": [GOOD]}), cassette)
    recorded = _caller(prompts, recording).call("probe", VARIABLES, ProbeFinding, CONTEXT)
    replayed = _caller(prompts, ReplayReasoner(cassette)).call(
        "probe", VARIABLES, ProbeFinding, CONTEXT
    )
    assert replayed.output == recorded.output
    assert replayed.record == recorded.record


def test_changed_request_fails_replay(prompts, tmp_path: Path) -> None:
    cassette = Cassette(tmp_path / "cassette.jsonl")
    _caller(prompts, RecordingReasoner(FakeReasoner({"probe": [GOOD]}), cassette)).call(
        "probe", VARIABLES, ProbeFinding, CONTEXT
    )
    with pytest.raises(ReasonerCallError) as info:
        _caller(prompts, ReplayReasoner(cassette)).call(
            "probe", {**VARIABLES, "events": "none"}, ProbeFinding, CONTEXT
        )
    assert isinstance(info.value.__cause__, ReplayMismatchError)
    assert info.value.record.status == "error"


def test_repeated_requests_replay_in_order(prompts, tmp_path: Path) -> None:
    cassette = Cassette(tmp_path / "cassette.jsonl")
    recorder = _caller(
        prompts, RecordingReasoner(FakeReasoner({"probe": [GOOD, SECOND]}), cassette)
    )
    for step in (0, 1):
        recorder.call("probe", VARIABLES, ProbeFinding, CONTEXT.model_copy(update={"step": step}))
    replayer = _caller(prompts, ReplayReasoner(cassette))
    outputs = [
        replayer.call(
            "probe", VARIABLES, ProbeFinding, CONTEXT.model_copy(update={"step": step})
        ).output
        for step in (0, 1)
    ]
    assert outputs == [ProbeFinding(**GOOD), ProbeFinding(**SECOND)]
    with pytest.raises(ReasonerCallError):
        replayer.call("probe", VARIABLES, ProbeFinding, CONTEXT.model_copy(update={"step": 2}))


def test_cassette_lines_are_canonical_json(prompts, tmp_path: Path) -> None:
    cassette = Cassette(tmp_path / "cassette.jsonl")
    _caller(prompts, RecordingReasoner(FakeReasoner({"probe": [GOOD]}), cassette)).call(
        "probe", VARIABLES, ProbeFinding, CONTEXT
    )
    for line in cassette.path.read_text(encoding="utf-8").splitlines():
        assert line == canonical_json_bytes(json.loads(line)).decode("utf-8")


def test_missing_cassette_replays_nothing(prompts, tmp_path: Path) -> None:
    replayer = _caller(prompts, ReplayReasoner(Cassette(tmp_path / "absent.jsonl")))
    with pytest.raises(ReasonerCallError) as info:
        replayer.call("probe", VARIABLES, ProbeFinding, CONTEXT)
    assert isinstance(info.value.__cause__, ReplayMismatchError)
