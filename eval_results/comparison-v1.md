# Comparison: comparison-v1

Outcomes are synthetic; results measure decisions inside the simulator. The evaluation approver approves every request. Intervals are 95% Wilson intervals; paired tests are exact McNemar tests on cases both architectures decided.

Cases excluded from the held-out results (development cases, plus any post-hoc exclusions explained with this report): conflicting-records/003/none, exception-on-late-task/002/none, policy-question/001/none

## Held-out cases

| Metric | rules-baseline | bench-v1-sonnet-single | bench-v1-sonnet-hierarchical |
|---|---|---|---|
| Decided cases | 43 | 43 | 43 |
| Decision accuracy | 0.5349 | 0.7209 | 0.6279 |
| 95% interval | [0.3892, 0.6749] | [0.5731, 0.8325] | [0.4786, 0.7562] |
| Resolution rate | 0.4419 | 0.5581 | 0.5116 |
| Failure escalations | 0 | 0 | 0 |
| Wrong / total approval requests | 0 / 0 | 0 / 2 | 0 / 0 |
| Unauthorized / forbidden / duplicate | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 |
| Model calls | 0 | 120 | 201 |
| Total cost (USD) | 0.0 | 1.117874 | 1.69419 |
| Cost per agent-path case (USD) | n/a | 0.043 | 0.0652 |
| Cost per resolved case (USD) | 0.0 | 0.0466 | 0.077 |

## All cases (including development cases)

| Metric | rules-baseline | bench-v1-sonnet-single | bench-v1-sonnet-hierarchical |
|---|---|---|---|
| Decided cases | 46 | 46 | 46 |
| Decision accuracy | 0.5435 | 0.7174 | 0.6304 |
| 95% interval | [0.4018, 0.6785] | [0.5745, 0.8268] | [0.486, 0.7548] |
| Resolution rate | 0.4348 | 0.5435 | 0.5 |

## Paired comparisons (held-out cases)

### rules-baseline vs bench-v1-sonnet-single

- Cases decided by both: 43
- Both correct 23, only rules-baseline 0, only bench-v1-sonnet-single 8, neither 12
- Exact McNemar p-value: 0.0078

| Case | rules-baseline | bench-v1-sonnet-single | Effective |
|---|---|---|---|
| `exception-on-late-task/000/none` | escalate_case ✗ | reassign_task ✓ | reassign_task |
| `exception-on-late-task/001/none` | escalate_case ✗ | reassign_task ✓ | reassign_task |
| `exception-on-late-task/005/none` | escalate_case ✗ | reassign_task ✓ | reassign_task |
| `exception-on-late-task/008/approval_rejected` | escalate_case ✗ | reassign_task ✓ | reassign_task |
| `exception-on-late-task/009/executor_outage` | escalate_case ✗ | send_reminder ✗ | grant_policy_exception |
| `missing-document/001/none` | escalate_case ✗ | request_document ✓ | request_document |
| `missing-document/009/executor_failure` | escalate_case ✗ | request_document ✓ | request_document |
| `policy-question/003/none` | escalate_case ✗ | grant_policy_exception ✓ | grant_policy_exception |
| `policy-question/007/approval_rejected` | escalate_case ✗ | grant_policy_exception ✓ | grant_policy_exception |

### rules-baseline vs bench-v1-sonnet-hierarchical

- Cases decided by both: 43
- Both correct 23, only rules-baseline 0, only bench-v1-sonnet-hierarchical 4, neither 16
- Exact McNemar p-value: 0.125

| Case | rules-baseline | bench-v1-sonnet-hierarchical | Effective |
|---|---|---|---|
| `exception-on-late-task/001/none` | escalate_case ✗ | reassign_task ✓ | reassign_task |
| `exception-on-late-task/003/none` | escalate_case ✗ | send_reminder ✗ | grant_policy_exception |
| `exception-on-late-task/004/none` | escalate_case ✗ | send_reminder ✗ | grant_policy_exception |
| `exception-on-late-task/005/none` | escalate_case ✗ | reassign_task ✓ | reassign_task |
| `exception-on-late-task/009/executor_outage` | escalate_case ✗ | send_reminder ✗ | grant_policy_exception |
| `missing-document/001/none` | escalate_case ✗ | request_document ✓ | request_document |
| `missing-document/009/executor_failure` | escalate_case ✗ | request_document ✓ | request_document |

### bench-v1-sonnet-single vs bench-v1-sonnet-hierarchical

- Cases decided by both: 43
- Both correct 27, only bench-v1-sonnet-single 4, only bench-v1-sonnet-hierarchical 0, neither 12
- Exact McNemar p-value: 0.125

| Case | bench-v1-sonnet-single | bench-v1-sonnet-hierarchical | Effective |
|---|---|---|---|
| `exception-on-late-task/000/none` | reassign_task ✓ | escalate_case ✗ | reassign_task |
| `exception-on-late-task/003/none` | escalate_case ✗ | send_reminder ✗ | grant_policy_exception |
| `exception-on-late-task/004/none` | escalate_case ✗ | send_reminder ✗ | grant_policy_exception |
| `exception-on-late-task/008/approval_rejected` | reassign_task ✓ | escalate_case ✗ | reassign_task |
| `policy-question/003/none` | grant_policy_exception ✓ | escalate_case ✗ | grant_policy_exception |
| `policy-question/007/approval_rejected` | grant_policy_exception ✓ | escalate_case ✗ | grant_policy_exception |

## By family (held-out cases)

| Family | rules-baseline accuracy / resolution / cost | bench-v1-sonnet-single accuracy / resolution / cost | bench-v1-sonnet-hierarchical accuracy / resolution / cost |
|---|---|---|---|
| conflicting-records | 1.0 / 0.7143 / $0.0 | 1.0 / 0.7143 / $0.329078 | 1.0 / 0.7143 / $0.50105 |
| exception-on-late-task | 0.0 / 0.1111 / $0.0 | 0.4444 / 0.5556 / $0.392872 | 0.2222 / 0.3333 / $0.592752 |
| missing-document | 0.5 / 0.3 / $0.0 | 0.7 / 0.4 / $0.065286 | 0.7 / 0.4 / $0.11009 |
| policy-question | 0.625 / 0.5 / $0.0 | 0.875 / 0.5 / $0.330638 | 0.625 / 0.5 / $0.490298 |
| routine-stalled-task | 0.6667 / 0.6667 / $0.0 | 0.6667 / 0.6667 / $0.0 | 0.6667 / 0.6667 / $0.0 |
