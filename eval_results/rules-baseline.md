# Evaluation: rules-baseline

- Mode: `deterministic`
- Reasoner: `fake/fake-model`
- Spend cap (USD): n/a
- Benchmark: `caseforge-core` v1 (sha256 `238ab8307b3a`)
- Configuration sha256: `0972fc418585`
- Git commit: `f312b058773e`
- Outcomes are synthetic: they measure decisions inside the simulator, - The evaluation approver approves every request, so wrong approval requests are executed; a real approver might catch them.
not real-world effects.

## Summary

| Metric | Value |
|---|---|
| Cases | 48 |
| Run status | completed: 46, halted: 2 |
| Route accuracy | n/a |
| Decision accuracy | 0.5435 |
| Acceptable decisions | 0.8696 |
| Resolution rate | 0.4348 |
| Unauthorized actions | 0 |
| Forbidden actions | 0 |
| Duplicate executions | 0 |
| Failure escalations (not scored as decisions) | 0 |
| Approval requests (wrong / total) | 0 / 0 |
| Conditions not exercised | 7 |
| Within budget | 1.0 |
| Total cost (USD) | 0.0 |
| Cost per resolved case (USD) | 0.0 |

## By family

| Family | Cases | Completed | Decision accuracy | Resolution rate | Model calls |
|---|---|---|---|---|---|
| conflicting-records | 8 | 8 | 1.0 | 0.75 | 0 |
| exception-on-late-task | 10 | 10 | 0.0 | 0.1 | 0 |
| missing-document | 10 | 10 | 0.5 | 0.3 | 0 |
| policy-question | 10 | 9 | 0.6667 | 0.4444 | 0 |
| routine-stalled-task | 10 | 9 | 0.6667 | 0.6667 | 0 |

## Notable cases

None.

## Conditions not exercised

- `conflicting-records/006/tool_failure`
- `exception-on-late-task/006/tool_failure`
- `exception-on-late-task/007/tool_failure`
- `exception-on-late-task/008/approval_rejected`
- `policy-question/006/approval_rejected`
- `policy-question/007/approval_rejected`
- `policy-question/008/tool_failure`
