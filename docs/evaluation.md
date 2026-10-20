# Evaluation

This report compares three ways of deciding workflow cases under identical governance:
deterministic rules only, a single bounded agent, and a hierarchy (a supervisor that plans,
two specialist workers, and a synthesis step). Every figure comes from result files in
`eval_results/`; every live model response is recorded in `eval_results/cassettes/` and
replays exactly at no cost.

## Method

**Simulator.** Five scenario families of synthetic cases with hidden ground truth (the
cause of the delay and the actions that would resolve it). Outcomes after an action are
probabilistic, so a correct decision does not always resolve a case.

**Benchmark.** `config/evaluation/benchmark.v1.yaml`: 48 cases (family x seed x injected
condition). Conditions: none, tool failure, transient and persistent executor failure,
duplicate trigger, approval rejected, and emergency stop. Expectations (route, forbidden
actions, cost ceilings) were fixed before any evaluation; correct actions come from ground
truth at scoring time.

**Architectures.** All three share intake, rule triage (routine cases never reach a model),
the approval gate, the action ledger, budgets, breakers, and the emergency stop. Only the
decision step differs.

**Models.** Claude Sonnet 5.5 (primary) and Claude Haiku 5.5 (exploratory), both
through structured outputs. The API in use accepts no sampling parameters; reproducibility
rests on recorded responses.

**Scoring.**
- *Decision accuracy*: the chosen action is one that addresses the hidden cause.
- *Failure escalations*: escalations caused by an error. They count as safe, never as
  correct decisions.
- *Resolution rate*: the observed outcome after a simulated wait is success.
- *Safety*: actions executed without required approval, forbidden actions, and duplicate
  executions.
- *Approval requests*: total and wrong. The evaluation approver approves every request, so
  a wrong request is executed; a real approver might catch it.

**Statistics.** 95% Wilson intervals for accuracy; exact McNemar tests on paired cases.
The planned comparison is rules vs single agent vs hierarchy on Sonnet (three tests, Holm
correction). Comparisons involving Haiku were added afterwards and are exploratory.

**Development cases.** Three cases (`policy-question/001`, `exception-on-late-task/002`,
`conflicting-records/003`) were used during development to diagnose problems and shape
prompts. They are excluded from the held-out results and reported alongside.

## Development history

The development runs are recorded (`smoke-*`, `pilot-*`, `pilot2-*`, `pilot3-*`) and
document problems found before the benchmark:

1. **Schema incompatibility.** Free-form tool arguments produced a JSON schema that
   structured outputs reject; every agent step failed locally before any request was sent.
   Arguments are now a JSON string decoded by the contract.
2. **Unsupported option.** The SDK rejected `temperature`; sampling options are now refused
   in configuration rather than silently ignored.
3. **Failures scored as decisions.** An escalation caused by an error was initially scored
   as a correct decision when escalation happened to be right. Failure escalations are now
   reported separately.
4. **Length limit.** The supervisor's escalation reasons exceeded a 500-character limit,
   turning every reasoned escalation into a failure. The limit was raised to 1,500.
5. **Invisible governance.** Agents escalated policy exceptions because they believed that
   proposing one would bypass approval. Prompt v2 explained the approval gate, and agents
   then proposed unjustified exceptions because "an approver will decide": rubber-stamp
   delegation, two wrong approval requests in three cases. Prompt v3 states that approval
   checks judgment rather than replacing it; wrong approval requests fell to zero.
   Prompts were then frozen (`git tag prompts-frozen-v3`).

## Results (held-out cases, n = 43)

| Configuration | Decision accuracy | 95% interval | Resolution | Cost per agent-path case | Total cost |
|---|---|---|---|---|---|
| Rules only | 0.535 | 0.389-0.675 | 0.442 | - | $0.00 |
| Sonnet single agent | **0.721** | 0.573-0.833 | 0.558 | $0.043 | $1.12 |
| Sonnet hierarchy | 0.628 | 0.479-0.756 | 0.512 | $0.065 | $1.69 |
| Haiku single agent | 0.535 | 0.389-0.675 | 0.465 | $0.002 | $0.06 |
| Haiku hierarchy | 0.605 | 0.456-0.736 | 0.488 | $0.004 | $0.11 |

Across all five configurations and 240 runs: 0 actions without required approval,
0 forbidden actions, 0 duplicate executions, 0 failure escalations. All four agent
configurations made identical decisions on routine cases, which rules handle at no cost.

### Paired comparisons (discordant cases; exact McNemar)

| Comparison | Only first correct | Only second correct | p | Status |
|---|---|---|---|---|
| Rules vs Sonnet single | 0 | 8 | 0.008 (Holm 0.023) | planned |
| Rules vs Sonnet hierarchy | 0 | 4 | 0.125 | planned |
| Sonnet single vs Sonnet hierarchy | 4 | 0 | 0.125 | planned |
| Sonnet single vs Haiku single | 8 | 0 | 0.008 | exploratory |
| Sonnet hierarchy vs Haiku hierarchy | 1 | 0 | 1.0 | exploratory |
| Haiku single vs Haiku hierarchy | 0 | 3 | 0.25 | exploratory |
| Rules vs Haiku single | 3 | 3 | 1.0 | exploratory |

### Findings

1. **The Sonnet single agent outperforms rules.** It was correct on eight cases where rules
   failed and on none where rules succeeded; this holds after correction for the three
   planned comparisons. Gains come from reassigning stalled late tasks, requesting the
   right document, and recognizing justified exceptions.
2. **No evidence that the hierarchy improves accuracy with Sonnet,** at about 50% higher
   cost per agent-path case. The hierarchy never decided a case correctly that the single
   agent missed.
3. **Model and architecture appear to interact (exploratory).** With Haiku, the single
   agent performed at rules level, mainly because it requested documents on three
   conflicting-record cases that called for escalation. The Haiku hierarchy decided all
   three correctly and came close to the Sonnet hierarchy at about one fifteenth of the
   cost. Decomposition may compensate for a weaker model; the differences are not
   significant at this sample size.
4. **Cost and quality frontier.** Rules ($0, 0.53), Haiku hierarchy ($0.004 per agent case,
   0.60), and Sonnet single agent ($0.043, 0.72) are non-dominated. The Sonnet hierarchy and
   the Haiku single agent are dominated.

## Validity: warranted extensions on late tasks

No configuration ever granted a warranted extension on a late task. The tool data show the
justification signal (a `supporting_statement` document, type only, without content) in
the same form as in policy-question cases, where the Sonnet single agent did grant
correctly. Two causes are identified:

- **Benchmark limitation.** The simulator treats a supporting statement as the
  justification, but the statement's content is not visible and no policy says that such a
  statement justifies an exception (the policies say only that exceptions are rare and must
  be justified by case facts). These cases partly measure an unstated rule.
- **Agent pattern.** When an overdue task makes the reminder policy also applicable, agents
  prefer the routine reminder over the exception.

A post-hoc sensitivity analysis (`comparison-v1-sensitivity`) excludes the five held-out
cases that hinge on this rule. Sonnet single vs rules remains significant (6-0, p = 0.031);
the single-vs-hierarchy difference shrinks to 2-0 (p = 0.5). The conclusions are unchanged:
the single agent outperforms rules, and no accuracy difference between the two agent
architectures is established.

## Reproducibility and cost

All live responses are recorded; replaying the benchmark tapes reproduced every reported
figure exactly. Live spend for the whole evaluation was about US$4.38: development runs
(smoke test and three pilots) about $1.09, the Sonnet benchmark $3.10, and the Haiku
benchmark $0.19. The configuration fingerprint is stable across processes; reports record
the benchmark hash, configuration hash, and git commit.

## Limitations

- **Synthetic setting.** Outcomes reflect the simulator's assumptions, not real-world
  effects.
- **Sample size.** 43 held-out cases, one run per case per configuration; differences of a
  few cases are not resolvable.
- **Single provider.** Two models from one provider; results may not transfer.
- **No sampling control.** Repeated live runs can differ; one repeated development run
  produced identical decisions, but repeatability was not measured systematically.
- **Idealized approver.** The evaluation approver approves every request; the zero wrong
  approval requests in the benchmark do not measure how a real approver would perform.
- **Development influence.** Prompts were shaped on three development cases, excluded from
  the held-out results.
- **Benchmark validity.** The warranted-extension cases depend on an unstated rule.

## Future work

- Benchmark v2: state the justification rule in policy or expose document content; more
  seeds per family; repeated runs to measure decision stability.
- A simulated approver with imperfect accuracy, to measure the cost of wrong approval
  requests.
- Batch processing for evaluation runs (50% lower cost).
