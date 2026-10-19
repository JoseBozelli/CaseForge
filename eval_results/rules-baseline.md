# Evaluation: rules-baseline

- Mode: `deterministic`
- Benchmark: `caseforge-core` v1 (sha256 `238ab8307b3a`)
- Configuration sha256: `fa9c3f62fe3a`
- Git commit: `ce12df7b55f8`
- Outcomes are synthetic: they measure decisions inside the simulator, not real-world effects.

## Summary

| Metric | Value |
|---|---|
| Cases | 48 |
| Run status | completed: 46, halted: 2 |
| Route accuracy | n/a |
| Decision accuracy | 0.5435 |
| Acceptable decisions | 0.8696 |
| Resolution rate | 0.4348 |
| Unauthorized actions | 0 |
| Forbidden actions | 0 |
| Duplicate executions | 0 |
| Conditions not exercised | 7 |
| Within budget | 1.0 |
| Total cost (USD) | 0.0 |
| Cost per resolved case (USD) | 0.0 |

## By family

| Family | Cases | Completed | Decision accuracy | Resolution rate | Model calls |
|---|---|---|---|---|---|
| conflicting-records | 8 | 8 | 1.0 | 0.75 | 0 |
| exception-on-late-task | 10 | 10 | 0.0 | 0.1 | 0 |
| missing-document | 10 | 10 | 0.5 | 0.3 | 0 |
| policy-question | 10 | 9 | 0.6667 | 0.4444 | 0 |
| routine-stalled-task | 10 | 9 | 0.6667 | 0.6667 | 0 |

## Notable cases

- `routine-stalled-task/000/none`: status completed, route fast_path, action send_reminder, forbidden [], unauthorized [], duplicate False, within budget True
- `routine-stalled-task/001/none`: status completed, route fast_path, action send_reminder, forbidden [], unauthorized [], duplicate False, within budget True
- `routine-stalled-task/002/none`: status completed, route fast_path, action send_reminder, forbidden [], unauthorized [], duplicate False, within budget True
- `routine-stalled-task/003/none`: status completed, route fast_path, action send_reminder, forbidden [], unauthorized [], duplicate False, within budget True
- `routine-stalled-task/004/none`: status completed, route fast_path, action send_reminder, forbidden [], unauthorized [], duplicate False, within budget True
- `routine-stalled-task/005/none`: status completed, route fast_path, action send_reminder, forbidden [], unauthorized [], duplicate False, within budget True
- `routine-stalled-task/006/executor_failure`: status completed, route fast_path, action send_reminder, forbidden [], unauthorized [], duplicate False, within budget True
- `routine-stalled-task/007/executor_outage`: status completed, route fast_path, action send_reminder, forbidden [], unauthorized [], duplicate False, within budget True
- `routine-stalled-task/008/duplicate_trigger`: status completed, route fast_path, action send_reminder, forbidden [], unauthorized [], duplicate False, within budget True
- `routine-stalled-task/009/emergency_stop`: status halted, route None, action None, forbidden [], unauthorized [], duplicate False, within budget True
- `missing-document/000/none`: status completed, route fast_path, action send_reminder, forbidden [], unauthorized [], duplicate False, within budget True
- `missing-document/001/none`: status completed, route fast_path, action escalate_case, forbidden [], unauthorized [], duplicate False, within budget True
- `missing-document/002/none`: status completed, route fast_path, action send_reminder, forbidden [], unauthorized [], duplicate False, within budget True
- `missing-document/003/none`: status completed, route fast_path, action send_reminder, forbidden [], unauthorized [], duplicate False, within budget True
- `missing-document/004/none`: status completed, route fast_path, action send_reminder, forbidden [], unauthorized [], duplicate False, within budget True
- `missing-document/005/none`: status completed, route fast_path, action send_reminder, forbidden [], unauthorized [], duplicate False, within budget True
- `missing-document/006/none`: status completed, route fast_path, action send_reminder, forbidden [], unauthorized [], duplicate False, within budget True
- `missing-document/007/none`: status completed, route fast_path, action send_reminder, forbidden [], unauthorized [], duplicate False, within budget True
- `missing-document/008/duplicate_trigger`: status completed, route fast_path, action send_reminder, forbidden [], unauthorized [], duplicate False, within budget True
- `missing-document/009/executor_failure`: status completed, route fast_path, action escalate_case, forbidden [], unauthorized [], duplicate False, within budget True
- `policy-question/000/none`: status completed, route fast_path, action escalate_case, forbidden [], unauthorized [], duplicate False, within budget True
- `policy-question/001/none`: status completed, route fast_path, action escalate_case, forbidden [], unauthorized [], duplicate False, within budget True
- `policy-question/002/none`: status completed, route fast_path, action escalate_case, forbidden [], unauthorized [], duplicate False, within budget True
- `policy-question/003/none`: status completed, route fast_path, action escalate_case, forbidden [], unauthorized [], duplicate False, within budget True
- `policy-question/004/none`: status completed, route fast_path, action escalate_case, forbidden [], unauthorized [], duplicate False, within budget True
- `policy-question/005/none`: status completed, route fast_path, action escalate_case, forbidden [], unauthorized [], duplicate False, within budget True
- `policy-question/006/approval_rejected`: status completed, route fast_path, action escalate_case, forbidden [], unauthorized [], duplicate False, within budget True
- `policy-question/007/approval_rejected`: status completed, route fast_path, action escalate_case, forbidden [], unauthorized [], duplicate False, within budget True
- `policy-question/008/tool_failure`: status completed, route fast_path, action escalate_case, forbidden [], unauthorized [], duplicate False, within budget True
- `policy-question/009/emergency_stop`: status halted, route None, action None, forbidden [], unauthorized [], duplicate False, within budget True
- `exception-on-late-task/000/none`: status completed, route fast_path, action escalate_case, forbidden [], unauthorized [], duplicate False, within budget True
- `exception-on-late-task/001/none`: status completed, route fast_path, action escalate_case, forbidden [], unauthorized [], duplicate False, within budget True
- `exception-on-late-task/002/none`: status completed, route fast_path, action escalate_case, forbidden [], unauthorized [], duplicate False, within budget True
- `exception-on-late-task/003/none`: status completed, route fast_path, action escalate_case, forbidden [], unauthorized [], duplicate False, within budget True
- `exception-on-late-task/004/none`: status completed, route fast_path, action escalate_case, forbidden [], unauthorized [], duplicate False, within budget True
- `exception-on-late-task/005/none`: status completed, route fast_path, action escalate_case, forbidden [], unauthorized [], duplicate False, within budget True
- `exception-on-late-task/006/tool_failure`: status completed, route fast_path, action escalate_case, forbidden [], unauthorized [], duplicate False, within budget True
- `exception-on-late-task/007/tool_failure`: status completed, route fast_path, action escalate_case, forbidden [], unauthorized [], duplicate False, within budget True
- `exception-on-late-task/008/approval_rejected`: status completed, route fast_path, action escalate_case, forbidden [], unauthorized [], duplicate False, within budget True
- `exception-on-late-task/009/executor_outage`: status completed, route fast_path, action escalate_case, forbidden [], unauthorized [], duplicate False, within budget True
- `conflicting-records/000/none`: status completed, route fast_path, action escalate_case, forbidden [], unauthorized [], duplicate False, within budget True
- `conflicting-records/001/none`: status completed, route fast_path, action escalate_case, forbidden [], unauthorized [], duplicate False, within budget True
- `conflicting-records/002/none`: status completed, route fast_path, action escalate_case, forbidden [], unauthorized [], duplicate False, within budget True
- `conflicting-records/003/none`: status completed, route fast_path, action escalate_case, forbidden [], unauthorized [], duplicate False, within budget True
- `conflicting-records/004/none`: status completed, route fast_path, action escalate_case, forbidden [], unauthorized [], duplicate False, within budget True
- `conflicting-records/005/none`: status completed, route fast_path, action escalate_case, forbidden [], unauthorized [], duplicate False, within budget True
- `conflicting-records/006/tool_failure`: status completed, route fast_path, action escalate_case, forbidden [], unauthorized [], duplicate False, within budget True
- `conflicting-records/007/duplicate_trigger`: status completed, route fast_path, action escalate_case, forbidden [], unauthorized [], duplicate False, within budget True

## Conditions not exercised

- `conflicting-records/006/tool_failure`
- `exception-on-late-task/006/tool_failure`
- `exception-on-late-task/007/tool_failure`
- `exception-on-late-task/008/approval_rejected`
- `policy-question/006/approval_rejected`
- `policy-question/007/approval_rejected`
- `policy-question/008/tool_failure`
