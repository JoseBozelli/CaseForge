# Evaluation: bench-v1-sonnet-single

- Mode: `single_agent`
- Reasoner: `anthropic/claude-sonnet-5-5 (live)`
- Spend cap (USD): 1.75
- Benchmark: `caseforge-core` v1 (sha256 `238ab8307b3a`)
- Configuration sha256: `6abe4ef0166a`
- Git commit: `eb86ae12eb19` (uncommitted changes present)
- Outcomes are synthetic: they measure decisions inside the simulator, - The evaluation approver approves every request, so wrong approval requests are executed; a real approver might catch them.
not real-world effects.

## Summary

| Metric | Value |
|---|---|
| Cases | 48 |
| Run status | completed: 46, halted: 2 |
| Route accuracy | 1.0 |
| Decision accuracy | 0.7174 |
| Acceptable decisions | 0.8261 |
| Resolution rate | 0.5435 |
| Unauthorized actions | 0 |
| Forbidden actions | 0 |
| Duplicate executions | 0 |
| Failure escalations (not scored as decisions) | 0 |
| Approval requests (wrong / total) | 0 / 2 |
| Conditions not exercised | 2 |
| Within budget | 1.0 |
| Total cost (USD) | 1.230192 |
| Cost per resolved case (USD) | 0.049208 |

## By family

| Family | Cases | Completed | Decision accuracy | Resolution rate | Model calls |
|---|---|---|---|---|---|
| conflicting-records | 8 | 8 | 1.0 | 0.75 | 39 |
| exception-on-late-task | 10 | 10 | 0.4 | 0.5 | 45 |
| missing-document | 10 | 10 | 0.7 | 0.4 | 8 |
| policy-question | 10 | 9 | 0.8889 | 0.4444 | 40 |
| routine-stalled-task | 10 | 9 | 0.6667 | 0.6667 | 0 |

## Notable cases

None.

## Conditions not exercised

- `exception-on-late-task/008/approval_rejected`
- `policy-question/006/approval_rejected`
