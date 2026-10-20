# Pre-registration: confirmatory study v2

Registered before any run of the confirmatory benchmark. The git tag `prereg-v2` marks the
registered state; results produced from later commits must be reported as deviations.

## Question

Is the cost-optimized configuration (Claude Haiku 5.5, hierarchy) good enough to recommend
over the strong configuration (Claude Sonnet 5.5, single agent) at about one tenth of the
cost per agent-handled case? The idea arose from exploratory comparisons in benchmark v1
(`docs/evaluation.md`); it is tested here on new cases.

## Design

- **Cases:** `config/evaluation/benchmark.v2-confirm.yaml`: 120 cases, seeds 10-39 in
  `missing-document`, `policy-question`, `exception-on-late-task` and `conflicting-records`;
  no injected conditions. These seeds were never run before registration.
- **Configurations:** rules only (deterministic mode); cheap: Haiku 5.5 hierarchy; strong:
  Sonnet 5.5 single agent. Code, prompts (v3) and governance as at the registration commit.
- **Each case is run once per configuration, live, with responses recorded.** No re-runs:
  a failed or escalated run counts as recorded.
- **Primary metric:** decision accuracy on decided cases (the chosen action addresses the
  hidden cause; failure escalations are never correct).

## Hypotheses (one-sided, Bonferroni: alpha = 0.025 each)

- **H1 (superiority):** the cheap configuration is more accurate than rules. Exact one-sided
  McNemar test on paired cases; supported if p < 0.025.
- **H2 (non-inferiority):** the cheap configuration's accuracy is at most 10 percentage points
  below the strong configuration's. Supported if the lower bound of the 95% Newcombe interval
  for the paired difference (cheap minus strong) exceeds -0.10.

## Registered decision rule

| H1 | H2 | Conclusion |
|---|---|---|
| yes | yes | Recommend the cheap configuration as the cost-optimized default |
| yes | no | The cheap configuration beats rules, but the strong one is recommended where decisions matter |
| no | yes | Neither hypothesis alone supports a cheap-agent default |
| no | no | The strong configuration remains recommended |

The analysis is applied mechanically by `python -m caseforge.evaluation.confirm`.

## Secondary (descriptive only)

Resolution rate, cost per agent case and per resolved case, safety counts (unauthorized,
forbidden, duplicate executions), failure escalations, and wrong approval requests.

## Spend

Estimated about $0.50 (cheap) and $5.20 (strong); caps $1.50 and $7.50 per run. If a cap
stops a run early, the study is reported as incomplete; caps are not raised to finish it.

## Known limitations carried over

Synthetic outcomes; one provider; one run per case; an evaluation approver that approves
every request; the warranted-extension cases depend on an unstated rule (see
`docs/evaluation.md`).
