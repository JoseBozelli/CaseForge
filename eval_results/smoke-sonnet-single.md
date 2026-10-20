# Evaluation: smoke-sonnet-single

- Mode: `single_agent`
- Reasoner: `anthropic/claude-sonnet-5-5 (live)`
- Spend cap (USD): 0.25
- Benchmark: `caseforge-core` v1 (sha256 `238ab8307b3a`)
- Configuration sha256: `d74732ebd05a`
- Git commit: `bb76dc7fb5cb` (uncommitted changes present)
- Outcomes are synthetic: they measure decisions inside the simulator, not real-world effects.

## Summary

| Metric | Value |
|---|---|
| Cases | 1 |
| Run status | completed: 1 |
| Route accuracy | 1.0 |
| Decision accuracy | 0.0 |
| Acceptable decisions | 1.0 |
| Resolution rate | 0.0 |
| Unauthorized actions | 0 |
| Forbidden actions | 0 |
| Duplicate executions | 0 |
| Failure escalations (not scored as decisions) | 1 |
| Conditions not exercised | 0 |
| Within budget | 1.0 |
| Total cost (USD) | 0.0 |
| Cost per resolved case (USD) | n/a |

## By family

| Family | Cases | Completed | Decision accuracy | Resolution rate | Model calls |
|---|---|---|---|---|---|
| policy-question | 1 | 1 | 0.0 | 0.0 | 1 |

## Notable cases

- `policy-question/001/none`: status completed, route single_agent, action escalate_case, forbidden [], unauthorized [], duplicate False, within budget True, failure escalation True

## Conditions not exercised

None.
