# Evaluation: bench-v1-haiku-single

- Mode: `single_agent`
- Reasoner: `anthropic/claude-haiku-5-5 (live)`
- Spend cap (USD): 0.3
- Benchmark: `caseforge-core` v1 (sha256 `238ab8307b3a`)
- Configuration sha256: `823addb07f15`
- Git commit: `4a9fcd01d618` (uncommitted changes present)
- Outcomes are synthetic: they measure decisions inside the simulator, - The evaluation approver approves every request, so wrong approval requests are executed; a real approver might catch them.
not real-world effects.

## Summary

| Metric | Value |
|---|---|
| Cases | 48 |
| Run status | completed: 46, halted: 2 |
| Route accuracy | 1.0 |
| Decision accuracy | 0.5435 |
| Acceptable decisions | 0.7826 |
| Resolution rate | 0.4565 |
| Unauthorized actions | 0 |
| Forbidden actions | 0 |
| Duplicate executions | 0 |
| Failure escalations (not scored as decisions) | 0 |
| Approval requests (wrong / total) | 0 / 0 |
| Conditions not exercised | 3 |
| Within budget | 1.0 |
| Total cost (USD) | 0.065283 |
| Cost per resolved case (USD) | 0.003109 |

## By family

| Family | Cases | Completed | Decision accuracy | Resolution rate | Model calls |
|---|---|---|---|---|---|
| conflicting-records | 8 | 8 | 0.625 | 0.625 | 39 |
| exception-on-late-task | 10 | 10 | 0.1 | 0.2 | 43 |
| missing-document | 10 | 10 | 0.7 | 0.4 | 8 |
| policy-question | 10 | 9 | 0.6667 | 0.4444 | 38 |
| routine-stalled-task | 10 | 9 | 0.6667 | 0.6667 | 0 |

## Notable cases

None.

## Conditions not exercised

- `exception-on-late-task/008/approval_rejected`
- `policy-question/006/approval_rejected`
- `policy-question/007/approval_rejected`
