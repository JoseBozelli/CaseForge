# Evaluation: pilot-sonnet-single

- Mode: `single_agent`
- Reasoner: `anthropic/claude-sonnet-5-5 (live)`
- Spend cap (USD): 0.5
- Benchmark: `caseforge-core` v1 (sha256 `238ab8307b3a`)
- Configuration sha256: `7fa9e715dc1c`
- Git commit: `d2102db03b64` (uncommitted changes present)
- Outcomes are synthetic: they measure decisions inside the simulator, not real-world effects.

## Summary

| Metric | Value |
|---|---|
| Cases | 3 |
| Run status | completed: 3 |
| Route accuracy | 1.0 |
| Decision accuracy | 0.6667 |
| Acceptable decisions | 1.0 |
| Resolution rate | 0.3333 |
| Unauthorized actions | 0 |
| Forbidden actions | 0 |
| Duplicate executions | 0 |
| Failure escalations (not scored as decisions) | 0 |
| Conditions not exercised | 0 |
| Within budget | 1.0 |
| Total cost (USD) | 0.107456 |
| Cost per resolved case (USD) | 0.107456 |

## By family

| Family | Cases | Completed | Decision accuracy | Resolution rate | Model calls |
|---|---|---|---|---|---|
| conflicting-records | 1 | 1 | 1.0 | 1.0 | 4 |
| exception-on-late-task | 1 | 1 | 0.0 | 0.0 | 4 |
| policy-question | 1 | 1 | 1.0 | 0.0 | 4 |

## Notable cases

None.

## Conditions not exercised

None.
