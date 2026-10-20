# Evaluation: pilot3-sonnet-hierarchical

- Mode: `hierarchical`
- Reasoner: `anthropic/claude-sonnet-5-5 (live)`
- Spend cap (USD): 0.5
- Benchmark: `caseforge-core` v1 (sha256 `238ab8307b3a`)
- Configuration sha256: `70d16b26452c`
- Git commit: `9ac146cc2bf4` (uncommitted changes present)
- Outcomes are synthetic: they measure decisions inside the simulator, - The evaluation approver approves every request, so wrong approval requests are executed; a real approver might catch them.
not real-world effects.

## Summary

| Metric | Value |
|---|---|
| Cases | 3 |
| Run status | completed: 3 |
| Route accuracy | 1.0 |
| Decision accuracy | 0.6667 |
| Acceptable decisions | 0.6667 |
| Resolution rate | 0.3333 |
| Unauthorized actions | 0 |
| Forbidden actions | 0 |
| Duplicate executions | 0 |
| Failure escalations (not scored as decisions) | 0 |
| Approval requests (wrong / total) | 0 / 0 |
| Conditions not exercised | 0 |
| Within budget | 1.0 |
| Total cost (USD) | 0.198502 |
| Cost per resolved case (USD) | 0.198502 |

## By family

| Family | Cases | Completed | Decision accuracy | Resolution rate | Model calls |
|---|---|---|---|---|---|
| conflicting-records | 1 | 1 | 1.0 | 1.0 | 8 |
| exception-on-late-task | 1 | 1 | 0.0 | 0.0 | 8 |
| policy-question | 1 | 1 | 1.0 | 0.0 | 6 |

## Notable cases

None.

## Conditions not exercised

None.
