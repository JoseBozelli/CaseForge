# Evaluation: confirm-v2-rules

- Mode: `deterministic`
- Reasoner: `fake/fake-model`
- Spend cap (USD): n/a
- Benchmark: `caseforge-confirm` v2 (sha256 `41ddd159cb91`)
- Configuration sha256: `586f1cfeda9d`
- Git commit: `8df1df5994f9`
- Outcomes are synthetic: they measure decisions inside the simulator, - The evaluation approver approves every request, so wrong approval requests are executed; a real approver might catch them.
not real-world effects.

## Summary

| Metric | Value |
|---|---|
| Cases | 120 |
| Run status | completed: 120 |
| Route accuracy | n/a |
| Decision accuracy | 0.4583 |
| Acceptable decisions | 0.9 |
| Resolution rate | 0.525 |
| Unauthorized actions | 0 |
| Forbidden actions | 0 |
| Duplicate executions | 0 |
| Failure escalations (not scored as decisions) | 0 |
| Approval requests (wrong / total) | 0 / 0 |
| Conditions not exercised | 0 |
| Within budget | 1.0 |
| Total cost (USD) | 0.0 |
| Cost per resolved case (USD) | 0.0 |

## By family

| Family | Cases | Completed | Decision accuracy | Resolution rate | Model calls |
|---|---|---|---|---|---|
| conflicting-records | 30 | 30 | 1.0 | 0.5333 | 0 |
| exception-on-late-task | 30 | 30 | 0.0 | 0.4333 | 0 |
| missing-document | 30 | 30 | 0.4333 | 0.5333 | 0 |
| policy-question | 30 | 30 | 0.4 | 0.6 | 0 |

## Notable cases

None.

## Conditions not exercised

None.
