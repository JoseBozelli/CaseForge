# Evaluation: pilot2-sonnet-hierarchical

- Mode: `hierarchical`
- Reasoner: `anthropic/claude-sonnet-5-5 (live)`
- Spend cap (USD): 0.5
- Benchmark: `caseforge-core` v1 (sha256 `238ab8307b3a`)
- Configuration sha256: `34fe860c16fd`
- Git commit: `ce8955acc3fb` (uncommitted changes present)
- Outcomes are synthetic: they measure decisions inside the simulator, not real-world effects.

## Summary

| Metric | Value |
|---|---|
| Cases | 3 |
| Run status | completed: 3 |
| Route accuracy | 1.0 |
| Decision accuracy | 0.6667 |
| Acceptable decisions | 0.6667 |
| Resolution rate | 0.6667 |
| Unauthorized actions | 0 |
| Forbidden actions | 0 |
| Duplicate executions | 0 |
| Failure escalations (not scored as decisions) | 0 |
| Conditions not exercised | 0 |
| Within budget | 1.0 |
| Total cost (USD) | 0.19257 |
| Cost per resolved case (USD) | 0.096285 |

## By family

| Family | Cases | Completed | Decision accuracy | Resolution rate | Model calls |
|---|---|---|---|---|---|
| conflicting-records | 1 | 1 | 1.0 | 1.0 | 8 |
| exception-on-late-task | 1 | 1 | 1.0 | 1.0 | 7 |
| policy-question | 1 | 1 | 0.0 | 0.0 | 6 |

## Notable cases

None.

## Conditions not exercised

None.
