# Evaluation: confirm-v2-sonnet-single

- Mode: `single_agent`
- Reasoner: `anthropic/claude-sonnet-5-5 (live)`
- Spend cap (USD): 7.5
- Benchmark: `caseforge-confirm` v2 (sha256 `41ddd159cb91`)
- Configuration sha256: `26d9a62453e0`
- Git commit: `8df1df5994f9` (uncommitted changes present)
- Outcomes are synthetic: they measure decisions inside the simulator, - The evaluation approver approves every request, so wrong approval requests are executed; a real approver might catch them.
not real-world effects.

## Summary

| Metric | Value |
|---|---|
| Cases | 120 |
| Run status | completed: 120 |
| Route accuracy | 1.0 |
| Decision accuracy | 0.6167 |
| Acceptable decisions | 0.7833 |
| Resolution rate | 0.55 |
| Unauthorized actions | 0 |
| Forbidden actions | 0 |
| Duplicate executions | 0 |
| Failure escalations (not scored as decisions) | 0 |
| Approval requests (wrong / total) | 0 / 5 |
| Conditions not exercised | 0 |
| Within budget | 1.0 |
| Total cost (USD) | 3.743218 |
| Cost per resolved case (USD) | 0.056715 |

## By family

| Family | Cases | Completed | Decision accuracy | Resolution rate | Model calls |
|---|---|---|---|---|---|
| conflicting-records | 30 | 30 | 0.9667 | 0.5333 | 122 |
| exception-on-late-task | 30 | 30 | 0.3333 | 0.4667 | 122 |
| missing-document | 30 | 30 | 0.6 | 0.5333 | 20 |
| policy-question | 30 | 30 | 0.5667 | 0.6667 | 130 |

## Notable cases

None.

## Conditions not exercised

None.
