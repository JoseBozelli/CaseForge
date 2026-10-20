# Confirmatory study v2

Registered in `docs/preregistration-v2.md` before any run. Analysis applied mechanically by
`caseforge.evaluation.confirm`. Outcomes are synthetic.

| Role | Report | Decided | Accuracy | 95% CI | USD per agent case | Unauth / forbid / dup |
|---|---|---|---|---|---|---|
| rules | `confirm-v2-rules` | 120 | 0.4583 | (0.3719, 0.5474) | None | 0 / 0 / 0 |
| cheap | `confirm-v2-haiku-hierarchical` | 120 | 0.45 | (0.3639, 0.5392) | 0.004 | 0 / 0 / 0 |
| strong | `confirm-v2-sonnet-single` | 120 | 0.6167 | (0.5273, 0.6988) | 0.0394 | 0 / 0 / 0 |

**H1: the cheap configuration beats rules.** Discordant cases: cheap only
6, rules only 7. Exact one-sided McNemar
p = 0.7095 (threshold 0.025).
**Not supported.**

**H2: the cheap configuration is non-inferior to the strong one (margin 10%).**
Discordant cases: cheap only 1, strong only
21. Accuracy difference (cheap minus strong) -0.1667,
95% Newcombe interval [-0.2342, -0.0951]; non-inferior if the lower
bound exceeds -0.1. **Not supported.**

## Registered decision

Neither hypothesis is supported; the strong configuration remains recommended.
