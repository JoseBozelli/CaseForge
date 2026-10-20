# Evaluation: pilot-sonnet-hierarchical-replay

- Mode: `hierarchical`
- Reasoner: `anthropic/claude-sonnet-5-5 (replay)`
- Spend cap (USD): n/a
- Benchmark: `caseforge-core` v1 (sha256 `238ab8307b3a`)
- Configuration sha256: `cdc0e74520f7`
- Git commit: `d2102db03b64` (uncommitted changes present)
- Outcomes are synthetic: they measure decisions inside the simulator, not real-world effects.

## Summary

| Metric | Value |
|---|---|
| Cases | 3 |
| Run status | completed: 3 |
| Route accuracy | 1.0 |
| Decision accuracy | 0.0 |
| Acceptable decisions | 1.0 |
| Resolution rate | 0.3333 |
| Unauthorized actions | 0 |
| Forbidden actions | 0 |
| Duplicate executions | 0 |
| Failure escalations (not scored as decisions) | 3 |
| Conditions not exercised | 0 |
| Within budget | 1.0 |
| Total cost (USD) | 0.19693 |
| Cost per resolved case (USD) | 0.19693 |

## By family

| Family | Cases | Completed | Decision accuracy | Resolution rate | Model calls |
|---|---|---|---|---|---|
| conflicting-records | 1 | 1 | 0.0 | 1.0 | 9 |
| exception-on-late-task | 1 | 1 | 0.0 | 0.0 | 7 |
| policy-question | 1 | 1 | 0.0 | 0.0 | 6 |

## Notable cases

- `policy-question/001/none`: status completed, route supervisor, action escalate_case, forbidden [], unauthorized [], duplicate False, within budget True, failure escalation True
- `exception-on-late-task/002/none`: status completed, route supervisor, action escalate_case, forbidden [], unauthorized [], duplicate False, within budget True, failure escalation True
- `conflicting-records/003/none`: status completed, route supervisor, action escalate_case, forbidden [], unauthorized [], duplicate False, within budget True, failure escalation True

## Conditions not exercised

None.
