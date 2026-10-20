# Evaluation: confirm-v2-haiku-hierarchical

- Mode: `hierarchical`
- Reasoner: `anthropic/claude-haiku-5-5 (live)`
- Spend cap (USD): 1.5
- Benchmark: `caseforge-confirm` v2 (sha256 `41ddd159cb91`)
- Configuration sha256: `711e5654e963`
- Git commit: `8df1df5994f9` (uncommitted changes present)
- Outcomes are synthetic: they measure decisions inside the simulator, - The evaluation approver approves every request, so wrong approval requests are executed; a real approver might catch them.
not real-world effects.

## Summary

| Metric | Value |
|---|---|
| Cases | 120 |
| Run status | completed: 120 |
| Route accuracy | 1.0 |
| Decision accuracy | 0.45 |
| Acceptable decisions | 0.7917 |
| Resolution rate | 0.525 |
| Unauthorized actions | 0 |
| Forbidden actions | 0 |
| Duplicate executions | 0 |
| Failure escalations (not scored as decisions) | 0 |
| Approval requests (wrong / total) | 0 / 0 |
| Conditions not exercised | 0 |
| Within budget | 0.9667 |
| Total cost (USD) | 0.382995 |
| Cost per resolved case (USD) | 0.006079 |

## By family

| Family | Cases | Completed | Decision accuracy | Resolution rate | Model calls |
|---|---|---|---|---|---|
| conflicting-records | 30 | 30 | 0.7667 | 0.4333 | 235 |
| exception-on-late-task | 30 | 30 | 0.0667 | 0.5333 | 249 |
| missing-document | 30 | 30 | 0.5667 | 0.5333 | 33 |
| policy-question | 30 | 30 | 0.4 | 0.6 | 237 |

## Notable cases

- `policy-question/016/none`: status completed, route supervisor, action escalate_case, forbidden [], unauthorized [], duplicate False, within budget False, failure escalation False
- `policy-question/022/none`: status completed, route supervisor, action escalate_case, forbidden [], unauthorized [], duplicate False, within budget False, failure escalation False
- `policy-question/028/none`: status completed, route supervisor, action escalate_case, forbidden [], unauthorized [], duplicate False, within budget False, failure escalation False
- `policy-question/029/none`: status completed, route supervisor, action escalate_case, forbidden [], unauthorized [], duplicate False, within budget False, failure escalation False

## Conditions not exercised

None.
