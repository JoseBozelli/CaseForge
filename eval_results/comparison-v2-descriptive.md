# Comparison: comparison-v2-descriptive

Outcomes are synthetic; results measure decisions inside the simulator. The evaluation approver approves every request. Intervals are 95% Wilson intervals; paired tests are exact McNemar tests on cases both architectures decided.

Cases excluded from the held-out results (development cases, plus any post-hoc exclusions explained with this report): none

## Held-out cases

| Metric | confirm-v2-rules | confirm-v2-haiku-hierarchical | confirm-v2-sonnet-single |
|---|---|---|---|
| Decided cases | 120 | 120 | 120 |
| Decision accuracy | 0.4583 | 0.45 | 0.6167 |
| 95% interval | [0.3719, 0.5474] | [0.3639, 0.5392] | [0.5273, 0.6988] |
| Resolution rate | 0.525 | 0.525 | 0.55 |
| Failure escalations | 0 | 0 | 0 |
| Wrong / total approval requests | 0 / 0 | 0 / 0 | 0 / 5 |
| Unauthorized / forbidden / duplicate | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 |
| Model calls | 0 | 754 | 394 |
| Total cost (USD) | 0.0 | 0.382995 | 3.743218 |
| Cost per agent-path case (USD) | n/a | 0.004 | 0.0394 |
| Cost per resolved case (USD) | 0.0 | 0.0061 | 0.0567 |

## All cases (including development cases)

| Metric | confirm-v2-rules | confirm-v2-haiku-hierarchical | confirm-v2-sonnet-single |
|---|---|---|---|
| Decided cases | 120 | 120 | 120 |
| Decision accuracy | 0.4583 | 0.45 | 0.6167 |
| 95% interval | [0.3719, 0.5474] | [0.3639, 0.5392] | [0.5273, 0.6988] |
| Resolution rate | 0.525 | 0.525 | 0.55 |

## Paired comparisons (held-out cases)

### confirm-v2-rules vs confirm-v2-haiku-hierarchical

- Cases decided by both: 120
- Both correct 48, only confirm-v2-rules 7, only confirm-v2-haiku-hierarchical 6, neither 59
- Exact McNemar p-value: 1.0

| Case | confirm-v2-rules | confirm-v2-haiku-hierarchical | Effective |
|---|---|---|---|
| `conflicting-records/011/none` | escalate_case ✓ | request_document ✗ | escalate_case |
| `conflicting-records/012/none` | escalate_case ✓ | request_document ✗ | escalate_case |
| `conflicting-records/014/none` | escalate_case ✓ | request_document ✗ | escalate_case |
| `conflicting-records/021/none` | escalate_case ✓ | request_document ✗ | escalate_case |
| `conflicting-records/028/none` | escalate_case ✓ | request_document ✗ | escalate_case |
| `conflicting-records/031/none` | escalate_case ✓ | request_document ✗ | escalate_case |
| `conflicting-records/034/none` | escalate_case ✓ | request_document ✗ | escalate_case |
| `exception-on-late-task/010/none` | escalate_case ✗ | send_reminder ✗ | grant_policy_exception |
| `exception-on-late-task/012/none` | escalate_case ✗ | send_reminder ✗ | reassign_task |
| `exception-on-late-task/014/none` | escalate_case ✗ | reassign_task ✓ | reassign_task |
| `exception-on-late-task/016/none` | escalate_case ✗ | send_reminder ✗ | grant_policy_exception |
| `exception-on-late-task/024/none` | escalate_case ✗ | reassign_task ✓ | reassign_task |
| `exception-on-late-task/027/none` | escalate_case ✗ | send_reminder ✗ | grant_policy_exception |
| `exception-on-late-task/036/none` | escalate_case ✗ | send_reminder ✗ | grant_policy_exception |
| `exception-on-late-task/038/none` | escalate_case ✗ | send_reminder ✗ | grant_policy_exception |
| `missing-document/011/none` | escalate_case ✗ | request_document ✓ | request_document |
| `missing-document/020/none` | escalate_case ✗ | request_document ✓ | request_document |
| `missing-document/031/none` | escalate_case ✗ | request_document ✓ | request_document |
| `missing-document/034/none` | escalate_case ✗ | request_document ✓ | request_document |

### confirm-v2-rules vs confirm-v2-sonnet-single

- Cases decided by both: 120
- Both correct 54, only confirm-v2-rules 1, only confirm-v2-sonnet-single 20, neither 45
- Exact McNemar p-value: 0.0

| Case | confirm-v2-rules | confirm-v2-sonnet-single | Effective |
|---|---|---|---|
| `conflicting-records/029/none` | escalate_case ✓ | request_document ✗ | escalate_case |
| `exception-on-late-task/012/none` | escalate_case ✗ | reassign_task ✓ | reassign_task |
| `exception-on-late-task/014/none` | escalate_case ✗ | reassign_task ✓ | reassign_task |
| `exception-on-late-task/016/none` | escalate_case ✗ | send_reminder ✗ | grant_policy_exception |
| `exception-on-late-task/017/none` | escalate_case ✗ | send_reminder ✗ | grant_policy_exception |
| `exception-on-late-task/019/none` | escalate_case ✗ | reassign_task ✓ | reassign_task |
| `exception-on-late-task/020/none` | escalate_case ✗ | send_reminder ✗ | grant_policy_exception |
| `exception-on-late-task/021/none` | escalate_case ✗ | send_reminder ✗ | grant_policy_exception |
| `exception-on-late-task/022/none` | escalate_case ✗ | send_reminder ✗ | grant_policy_exception |
| `exception-on-late-task/023/none` | escalate_case ✗ | send_reminder ✗ | grant_policy_exception |
| `exception-on-late-task/024/none` | escalate_case ✗ | reassign_task ✓ | reassign_task |
| `exception-on-late-task/025/none` | escalate_case ✗ | reassign_task ✓ | reassign_task |
| `exception-on-late-task/026/none` | escalate_case ✗ | send_reminder ✗ | grant_policy_exception |
| `exception-on-late-task/027/none` | escalate_case ✗ | send_reminder ✗ | grant_policy_exception |
| `exception-on-late-task/028/none` | escalate_case ✗ | reassign_task ✓ | reassign_task |
| `exception-on-late-task/029/none` | escalate_case ✗ | reassign_task ✓ | reassign_task |
| `exception-on-late-task/030/none` | escalate_case ✗ | send_reminder ✗ | grant_policy_exception |
| `exception-on-late-task/031/none` | escalate_case ✗ | send_reminder ✗ | grant_policy_exception |
| `exception-on-late-task/032/none` | escalate_case ✗ | send_reminder ✗ | grant_policy_exception |
| `exception-on-late-task/033/none` | escalate_case ✗ | reassign_task ✓ | reassign_task |
| `exception-on-late-task/034/none` | escalate_case ✗ | reassign_task ✓ | reassign_task |
| `exception-on-late-task/036/none` | escalate_case ✗ | send_reminder ✗ | grant_policy_exception |
| `exception-on-late-task/037/none` | escalate_case ✗ | send_reminder ✗ | grant_policy_exception |
| `exception-on-late-task/039/none` | escalate_case ✗ | reassign_task ✓ | reassign_task |
| `missing-document/011/none` | escalate_case ✗ | request_document ✓ | request_document |
| `missing-document/017/none` | escalate_case ✗ | request_document ✓ | request_document |
| `missing-document/020/none` | escalate_case ✗ | request_document ✓ | request_document |
| `missing-document/031/none` | escalate_case ✗ | request_document ✓ | request_document |
| `missing-document/034/none` | escalate_case ✗ | request_document ✓ | request_document |
| `policy-question/010/none` | escalate_case ✗ | grant_policy_exception ✓ | grant_policy_exception |
| `policy-question/013/none` | escalate_case ✗ | grant_policy_exception ✓ | grant_policy_exception |
| `policy-question/017/none` | escalate_case ✗ | grant_policy_exception ✓ | grant_policy_exception |
| `policy-question/023/none` | escalate_case ✗ | grant_policy_exception ✓ | grant_policy_exception |
| `policy-question/024/none` | escalate_case ✗ | grant_policy_exception ✓ | grant_policy_exception |

### confirm-v2-haiku-hierarchical vs confirm-v2-sonnet-single

- Cases decided by both: 120
- Both correct 53, only confirm-v2-haiku-hierarchical 1, only confirm-v2-sonnet-single 21, neither 45
- Exact McNemar p-value: 0.0

| Case | confirm-v2-haiku-hierarchical | confirm-v2-sonnet-single | Effective |
|---|---|---|---|
| `conflicting-records/011/none` | request_document ✗ | escalate_case ✓ | escalate_case |
| `conflicting-records/012/none` | request_document ✗ | escalate_case ✓ | escalate_case |
| `conflicting-records/014/none` | request_document ✗ | escalate_case ✓ | escalate_case |
| `conflicting-records/021/none` | request_document ✗ | escalate_case ✓ | escalate_case |
| `conflicting-records/028/none` | request_document ✗ | escalate_case ✓ | escalate_case |
| `conflicting-records/029/none` | escalate_case ✓ | request_document ✗ | escalate_case |
| `conflicting-records/031/none` | request_document ✗ | escalate_case ✓ | escalate_case |
| `conflicting-records/034/none` | request_document ✗ | escalate_case ✓ | escalate_case |
| `exception-on-late-task/010/none` | send_reminder ✗ | escalate_case ✗ | grant_policy_exception |
| `exception-on-late-task/012/none` | send_reminder ✗ | reassign_task ✓ | reassign_task |
| `exception-on-late-task/017/none` | escalate_case ✗ | send_reminder ✗ | grant_policy_exception |
| `exception-on-late-task/019/none` | escalate_case ✗ | reassign_task ✓ | reassign_task |
| `exception-on-late-task/020/none` | escalate_case ✗ | send_reminder ✗ | grant_policy_exception |
| `exception-on-late-task/021/none` | escalate_case ✗ | send_reminder ✗ | grant_policy_exception |
| `exception-on-late-task/022/none` | escalate_case ✗ | send_reminder ✗ | grant_policy_exception |
| `exception-on-late-task/023/none` | escalate_case ✗ | send_reminder ✗ | grant_policy_exception |
| `exception-on-late-task/025/none` | escalate_case ✗ | reassign_task ✓ | reassign_task |
| `exception-on-late-task/026/none` | escalate_case ✗ | send_reminder ✗ | grant_policy_exception |
| `exception-on-late-task/028/none` | escalate_case ✗ | reassign_task ✓ | reassign_task |
| `exception-on-late-task/029/none` | escalate_case ✗ | reassign_task ✓ | reassign_task |
| `exception-on-late-task/030/none` | escalate_case ✗ | send_reminder ✗ | grant_policy_exception |
| `exception-on-late-task/031/none` | escalate_case ✗ | send_reminder ✗ | grant_policy_exception |
| `exception-on-late-task/032/none` | escalate_case ✗ | send_reminder ✗ | grant_policy_exception |
| `exception-on-late-task/033/none` | escalate_case ✗ | reassign_task ✓ | reassign_task |
| `exception-on-late-task/034/none` | escalate_case ✗ | reassign_task ✓ | reassign_task |
| `exception-on-late-task/037/none` | escalate_case ✗ | send_reminder ✗ | grant_policy_exception |
| `exception-on-late-task/038/none` | send_reminder ✗ | escalate_case ✗ | grant_policy_exception |
| `exception-on-late-task/039/none` | escalate_case ✗ | reassign_task ✓ | reassign_task |
| `missing-document/017/none` | escalate_case ✗ | request_document ✓ | request_document |
| `policy-question/010/none` | escalate_case ✗ | grant_policy_exception ✓ | grant_policy_exception |
| `policy-question/013/none` | escalate_case ✗ | grant_policy_exception ✓ | grant_policy_exception |
| `policy-question/017/none` | escalate_case ✗ | grant_policy_exception ✓ | grant_policy_exception |
| `policy-question/023/none` | escalate_case ✗ | grant_policy_exception ✓ | grant_policy_exception |
| `policy-question/024/none` | escalate_case ✗ | grant_policy_exception ✓ | grant_policy_exception |

## By family (held-out cases)

| Family | confirm-v2-rules accuracy / resolution / cost | confirm-v2-haiku-hierarchical accuracy / resolution / cost | confirm-v2-sonnet-single accuracy / resolution / cost |
|---|---|---|---|
| conflicting-records | 1.0 / 0.5333 / $0.0 | 0.7667 / 0.4333 / $0.120225 | 0.9667 / 0.5333 / $1.161544 |
| exception-on-late-task | 0.0 / 0.4333 / $0.0 | 0.0667 / 0.5333 / $0.131335 | 0.3333 / 0.4667 / $1.20818 |
| missing-document | 0.4333 / 0.5333 / $0.0 | 0.5667 / 0.5333 / $0.016683 | 0.6 / 0.5333 / $0.162338 |
| policy-question | 0.4 / 0.6 / $0.0 | 0.4 / 0.6 / $0.114752 | 0.5667 / 0.6667 / $1.211156 |
