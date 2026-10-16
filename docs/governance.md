# Governance

CaseForge separates decision-making (agents) from authority (the Control Plane).
Agents propose; deterministic code decides what is permitted, and records it.

## Separation

- Governance state lives in its own SQLite database (`governance.db`), separate from
  case records (`records.db`), graph checkpoints, and the simulated outside world.
- Only `caseforge.governance` and the composition root may import the governance
  store or the `ControlPlane`. An architecture test enforces this on every check.
- Agents act only through typed, allowlisted tool calls. No registered tool reads or
  changes governance state, executes code, or writes files.

## Controls

| Control | Enforced at | Configuration | Evidence |
|---|---|---|---|
| Roles and permissions | `ControlPlane.require` before every governed operation; the permission catalog is fixed in code | `governance.roles`, `governance.operators` | `tests/governance/test_control_plane.py` |
| Approval of configured actions | Side-effect-free `approval_gate` before execution, re-checked in `act`; answering requires `approve_action` | `engine.approval_required` | `tests/engine/test_approval.py`, `tests/governance/test_control_plane.py` |
| Emergency stop | Every graph node start, model call, tool call, and immediately before action dispatch | `emergency_stop` permission | `tests/governance/test_emergency_stop.py` |
| Per-run budgets | Reserved before each model or tool call in one database transaction | `governance.budgets`, `reasoning.pricing` | `tests/governance/test_budgets.py` |
| Circuit breakers | Before each model call, tool call, and external action; per resource, shared across runs | `governance.breakers` | `tests/governance/test_breakers.py` |
| Executor retries | Exponential backoff, only when the external system ignores repeated action ids | `governance.retries` | `tests/governance/test_breakers.py`, `tests/engine/test_ledger_execution.py` |
| Action ledger | `intent -> dispatched -> succeeded / failed / unknown`; the first committed decision per run wins | none | `tests/engine/test_ledger_execution.py`, `tests/restart/test_process_kill.py` |
| Reconciliation of unknown actions | Admin-only resolution of `unknown` ledger entries | `reconcile_action` permission | `tests/governance/test_self_protection.py` |
| Audit log | Every authorization decision (allowed or denied) and every governed operation | none | `tests/governance/test_control_plane.py` |

## Behavior on refusal

| Refusal | Result |
|---|---|
| Permission denied | `PermissionDenied`; the operation does not happen; the denial is audited |
| Emergency stop engaged | The run halts at the next boundary with `halted: True`; `run.halted` is audited; the run resumes after release |
| Model-call budget or open reasoner breaker | Reasoner error; the worker or supervisor fails; the case escalates without further model calls |
| Tool budget or open tool breaker | Typed tool result (`budget_exhausted`, `circuit_open`) returned to the agent |
| Open executor breaker or exhausted retries | Ledger entry `failed`; the outcome is reported as unavailable |
| Approval rejected or missing | Action recorded as `not_executed`; nothing is sent |

## What agents cannot do

- Grant themselves permissions, change roles, raise budgets, or reset breakers.
- Engage or release the emergency stop.
- Approve their own proposals or answer approval requests.
- Delete or rewrite audit entries through application code.
- Execute arbitrary code or reach tools outside their configured allowlist.

`tests/governance/test_self_protection.py` includes a scripted agent that attempts
governance operations through the tool interface; every attempt returns
`unknown_tool` and governance state is unchanged.

## Limitations

- **In-process separation.** Governance runs in the same Python process as the agents.
  The guarantees above hold for the application's code paths, not against code that
  is already executing inside the process. Process or infrastructure isolation is
  production work.
- **Audit log tamper resistance.** Database triggers refuse updates and deletes from
  the application. A process able to change the database schema can remove them; a
  test documents this.
- **Simulated identity.** Operator names are supplied by the caller and are not
  authenticated. Roles limit what each name may do, not who presents it.
- **Stop timing.** The emergency stop takes effect at the next boundary. An in-flight
  model call or an already-dispatched external action completes; compensation is out
  of scope.
- **Budget precision.** Token and cost limits are checked before each call and can be
  exceeded by at most one call. Cost is estimated from configured pricing.
- **Breakers and budgets interact.** A model call refused by an open breaker still
  counts toward the run's call budget.
- **Durability.** SQLite in WAL mode survives process crashes; power-loss durability
  would require `synchronous=FULL`.
- **Trusted configuration.** Governance policy is read from the same configuration
  tree as the engine; a separately controlled policy source is production work.
