# Evaluation: bench-v1-sonnet-hierarchical

- Mode: `hierarchical`
- Reasoner: `anthropic/claude-sonnet-5-5 (live)`
- Spend cap (USD): 3.0
- Benchmark: `caseforge-core` v1 (sha256 `238ab8307b3a`)
- Configuration sha256: `3edf5c3e2316`
- Git commit: `eb86ae12eb19` (uncommitted changes present)
- Outcomes are synthetic: they measure decisions inside the simulator, - The evaluation approver approves every request, so wrong approval requests are executed; a real approver might catch them.
not real-world effects.

## Summary

| Metric | Value |
|---|---|
| Cases | 48 |
| Run status | completed: 46, halted: 2 |
| Route accuracy | 1.0 |
| Decision accuracy | 0.6304 |
| Acceptable decisions | 0.7826 |
| Resolution rate | 0.5 |
| Unauthorized actions | 0 |
| Forbidden actions | 0 |
| Duplicate executions | 0 |
| Failure escalations (not scored as decisions) | 0 |
| Approval requests (wrong / total) | 0 / 0 |
| Conditions not exercised | 3 |
| Within budget | 0.9583 |
| Total cost (USD) | 1.867912 |
| Cost per resolved case (USD) | 0.081214 |

## By family

| Family | Cases | Completed | Decision accuracy | Resolution rate | Model calls |
|---|---|---|---|---|---|
| conflicting-records | 8 | 8 | 1.0 | 0.75 | 65 |
| exception-on-late-task | 10 | 10 | 0.2 | 0.3 | 75 |
| missing-document | 10 | 10 | 0.7 | 0.4 | 13 |
| policy-question | 10 | 9 | 0.6667 | 0.4444 | 68 |
| routine-stalled-task | 10 | 9 | 0.6667 | 0.6667 | 0 |

## Notable cases

- `policy-question/008/tool_failure`: status completed, route supervisor, action escalate_case, forbidden [], unauthorized [], duplicate False, within budget False, failure escalation False
- `conflicting-records/007/duplicate_trigger`: status completed, route supervisor, action escalate_case, forbidden [], unauthorized [], duplicate False, within budget False, failure escalation False

## Conditions not exercised

- `exception-on-late-task/008/approval_rejected`
- `policy-question/006/approval_rejected`
- `policy-question/007/approval_rejected`
