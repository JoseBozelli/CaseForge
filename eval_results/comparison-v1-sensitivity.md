# Comparison: comparison-v1-sensitivity

Outcomes are synthetic; results measure decisions inside the simulator. The evaluation approver approves every request. Intervals are 95% Wilson intervals; paired tests are exact McNemar tests on cases both architectures decided.

Cases excluded from the held-out results (development cases, plus any post-hoc exclusions explained with this report): conflicting-records/003/none, exception-on-late-task/002/none, exception-on-late-task/003/none, exception-on-late-task/004/none, exception-on-late-task/009/executor_outage, policy-question/001/none, policy-question/003/none, policy-question/007/approval_rejected

## Held-out cases

| Metric | rules-baseline | bench-v1-sonnet-single | bench-v1-sonnet-hierarchical |
|---|---|---|---|
| Decided cases | 38 | 38 | 38 |
| Decision accuracy | 0.6053 | 0.7632 | 0.7105 |
| 95% interval | [0.4472, 0.744] | [0.6079, 0.8701] | [0.5524, 0.83] |
| Resolution rate | 0.4737 | 0.6053 | 0.5526 |
| Failure escalations | 0 | 0 | 0 |
| Wrong / total approval requests | 0 / 0 | 0 / 0 | 0 / 0 |
| Unauthorized / forbidden / duplicate | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 |
| Model calls | 0 | 98 | 168 |
| Total cost (USD) | 0.0 | 0.889188 | 1.38883 |
| Cost per agent-path case (USD) | n/a | 0.0423 | 0.0661 |
| Cost per resolved case (USD) | 0.0 | 0.0387 | 0.0661 |

## All cases (including development cases)

| Metric | rules-baseline | bench-v1-sonnet-single | bench-v1-sonnet-hierarchical |
|---|---|---|---|
| Decided cases | 46 | 46 | 46 |
| Decision accuracy | 0.5435 | 0.7174 | 0.6304 |
| 95% interval | [0.4018, 0.6785] | [0.5745, 0.8268] | [0.486, 0.7548] |
| Resolution rate | 0.4348 | 0.5435 | 0.5 |

## Paired comparisons (held-out cases)

### rules-baseline vs bench-v1-sonnet-single

- Cases decided by both: 38
- Both correct 23, only rules-baseline 0, only bench-v1-sonnet-single 6, neither 9
- Exact McNemar p-value: 0.0312

| Case | rules-baseline | bench-v1-sonnet-single | Effective |
|---|---|---|---|
| `exception-on-late-task/000/none` | escalate_case ✗ | reassign_task ✓ | reassign_task |
| `exception-on-late-task/001/none` | escalate_case ✗ | reassign_task ✓ | reassign_task |
| `exception-on-late-task/005/none` | escalate_case ✗ | reassign_task ✓ | reassign_task |
| `exception-on-late-task/008/approval_rejected` | escalate_case ✗ | reassign_task ✓ | reassign_task |
| `missing-document/001/none` | escalate_case ✗ | request_document ✓ | request_document |
| `missing-document/009/executor_failure` | escalate_case ✗ | request_document ✓ | request_document |

### rules-baseline vs bench-v1-sonnet-hierarchical

- Cases decided by both: 38
- Both correct 23, only rules-baseline 0, only bench-v1-sonnet-hierarchical 4, neither 11
- Exact McNemar p-value: 0.125

| Case | rules-baseline | bench-v1-sonnet-hierarchical | Effective |
|---|---|---|---|
| `exception-on-late-task/001/none` | escalate_case ✗ | reassign_task ✓ | reassign_task |
| `exception-on-late-task/005/none` | escalate_case ✗ | reassign_task ✓ | reassign_task |
| `missing-document/001/none` | escalate_case ✗ | request_document ✓ | request_document |
| `missing-document/009/executor_failure` | escalate_case ✗ | request_document ✓ | request_document |

### bench-v1-sonnet-single vs bench-v1-sonnet-hierarchical

- Cases decided by both: 38
- Both correct 27, only bench-v1-sonnet-single 2, only bench-v1-sonnet-hierarchical 0, neither 9
- Exact McNemar p-value: 0.5

| Case | bench-v1-sonnet-single | bench-v1-sonnet-hierarchical | Effective |
|---|---|---|---|
| `exception-on-late-task/000/none` | reassign_task ✓ | escalate_case ✗ | reassign_task |
| `exception-on-late-task/008/approval_rejected` | reassign_task ✓ | escalate_case ✗ | reassign_task |

## By family (held-out cases)

| Family | rules-baseline accuracy / resolution / cost | bench-v1-sonnet-single accuracy / resolution / cost | bench-v1-sonnet-hierarchical accuracy / resolution / cost |
|---|---|---|---|
| conflicting-records | 1.0 / 0.7143 / $0.0 | 1.0 / 0.7143 / $0.329078 | 1.0 / 0.7143 / $0.50105 |
| exception-on-late-task | 0.0 / 0.1667 / $0.0 | 0.6667 / 0.8333 / $0.252412 | 0.3333 / 0.5 / $0.40301 |
| missing-document | 0.5 / 0.3 / $0.0 | 0.7 / 0.4 / $0.065286 | 0.7 / 0.4 / $0.11009 |
| policy-question | 0.8333 / 0.5 / $0.0 | 0.8333 / 0.5 / $0.242412 | 0.8333 / 0.5 / $0.37468 |
| routine-stalled-task | 0.6667 / 0.6667 / $0.0 | 0.6667 / 0.6667 / $0.0 | 0.6667 / 0.6667 / $0.0 |
