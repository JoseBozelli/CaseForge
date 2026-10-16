"""Adapts the Control Plane's per-run budget to StructuredCaller's CallBudget hook."""

from __future__ import annotations

from caseforge.governance.control_plane import ControlPlane
from caseforge.reasoning.models import CallContext, TokenUsage
from caseforge.reasoning.ports import BudgetExhausted


class LlmBudget:
    def __init__(self, control_plane: ControlPlane) -> None:
        self._control_plane = control_plane

    def before_call(self, context: CallContext) -> None:
        decision = self._control_plane.reserve_llm_call(context.run_id)
        if not decision.allowed:
            raise BudgetExhausted(decision.reason or "model call budget exhausted")

    def after_call(self, context: CallContext, usage: TokenUsage) -> None:
        self._control_plane.record_llm_usage(context.run_id, usage)
