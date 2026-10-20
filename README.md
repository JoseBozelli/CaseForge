# CaseForge

CaseForge is a governed, multi-agent workflow engine for operational cases (stalled tasks,
missing documents, policy exceptions, conflicting records). Deterministic rules handle routine
cases; language-model agents handle the rest under an independent Control Plane that enforces
approvals, budgets, circuit breakers, an emergency stop, and an append-only audit log. Every
external action passes through an idempotent ledger, so restarts and duplicate triggers never
act twice.

The repository includes a synthetic case simulator with hidden ground truth, a versioned
benchmark, recorded model responses that replay exactly at no cost, and a pre-registered
confirmatory study.

## Quick start (no API key, no cost)

Requirements: Python 3.11 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
bash scripts/check.sh                       # quality gate: lint, format, 480+ tests
uv run streamlit run src/caseforge/ui/app.py
```

The operator console runs demo cases in which agent decisions replay recorded Claude
Sonnet 5.5 and Claude Haiku 5.5 answers from the benchmark. Operators can approve or reject
proposed actions (roles are enforced), engage and release the emergency stop, inspect
breakers and audit entries, and browse evaluation results.

The same capabilities are available as an HTTP API:

```bash
uv run uvicorn --factory caseforge.api.app:create_app --port 8000
# interactive documentation: http://127.0.0.1:8000/docs
```

## Results

All figures come from `eval_results/`; the method, development history, and limitations are in
[`docs/evaluation.md`](docs/evaluation.md).

**Benchmark v1** (43 held-out cases, planned comparisons with Holm correction):

| Configuration | Decision accuracy (95% interval) | Cost per agent-handled case |
|---|---|---|
| Rules only | 0.53 (0.39-0.67) | $0 |
| Claude Sonnet 5.5, single agent | **0.72** (0.57-0.83) | $0.043 |
| Claude Sonnet 5.5, hierarchy | 0.63 (0.48-0.76) | $0.065 |

**Confirmatory study v2** (120 new cases; hypotheses registered before any run in
[`docs/preregistration-v2.md`](docs/preregistration-v2.md)):

| Configuration | Decision accuracy (95% interval) | Cost per agent-handled case |
|---|---|---|
| Rules only | 0.46 (0.37-0.55) | $0 |
| Claude Haiku 5.5, hierarchy | 0.45 (0.36-0.54) | $0.004 |
| Claude Sonnet 5.5, single agent | **0.62** (0.53-0.70) | $0.039 |

- The Sonnet single agent outperformed rules in benchmark v1 (8 vs 0 discordant cases,
  corrected p = 0.023), and in the same direction on the 120 new cases (20 vs 1, descriptive).
- No evidence that the hierarchy improves accuracy over the single agent; it costs about 50%
  more per case.
- An exploratory indication that a cheaper model in the hierarchy could match the strong
  configuration did not replicate: in the registered study it performed at rules level and
  below the Sonnet single agent by roughly 10 to 23 points.
- Across all evaluated runs: zero actions without required approval, zero forbidden actions,
  zero duplicate executions.

**Recommended configuration:** Claude Sonnet 5.5, single agent. Outcomes are synthetic, so
these figures measure decisions inside the simulator, not real-world effects.

## Governance

| Control | Effect |
|---|---|
| Roles and permissions | Approvals, emergency stop, breaker resets, and reconciliation require configured roles; every decision is audited |
| Approval gate | Configured actions pause for an authorized approver; execution re-checks approval independently |
| Emergency stop | Halts every run at the next boundary (node, model call, tool call, or dispatch) |
| Budgets | Per-run limits on model calls, tokens, cost, and tool calls; failures that are billed still count |
| Circuit breakers | Stop calls to a failing reasoner, tool, or executor across runs |
| Action ledger | Exactly-once execution across crashes, restarts, and duplicate triggers |

Agents act only through a typed, allowlisted tool registry that contains no governance
operations; architecture tests enforce that agent-side code cannot import governance write
paths. Details and limitations: [`docs/governance.md`](docs/governance.md).

## Reproducing the evaluation

Replaying a recorded run costs nothing and reproduces every reported figure:

```bash
uv run python -m caseforge.evaluation.cli --label replay-check --mode single_agent \
  --provider anthropic --source replay --model claude-sonnet-5-5 \
  --cassette ../eval_results/cassettes/bench-v1-sonnet-single.jsonl
uv run python -m caseforge.evaluation.compare --name comparison-check \
  --reports rules-baseline bench-v1-sonnet-single bench-v1-sonnet-hierarchical
```

Live runs require an Anthropic API key, read from the `ANTHROPIC_API_KEY` environment variable
or from an `ANTHROPIC_API_KEY=...` line in a local `.secrets` file (ignored by Git and verified
by the quality gate). Live runs always record responses to a cassette and stop starting new
cases once a spend cap is reached:

```bash
uv run python -m caseforge.evaluation.cli --label my-run --mode single_agent \
  --provider anthropic --source live --model claude-sonnet-5-5 \
  --cassette ../eval_results/cassettes/my-run.jsonl --spend-cap 2.00
```

## Documentation

| Document | Contents |
|---|---|
| [`docs/architecture.md`](docs/architecture.md) | Case graph, layers and boundaries, persistence, determinism |
| [`docs/governance.md`](docs/governance.md) | Controls, enforcement points, evidence, limitations |
| [`docs/evaluation.md`](docs/evaluation.md) | Method, development history, results, validity, limitations |
| [`docs/preregistration-v2.md`](docs/preregistration-v2.md) | Registered design of the confirmatory study |

## Limitations

- Synthetic cases and outcomes; results may not transfer to real workflows.
- Two models from one provider; one run per case.
- Operator identity is simulated (roles are enforced, identities are not authenticated).
- Governance runs in the same process as the agents; isolation is application-level.
- The evaluation approver approves every request.

## Repository layout

```
config/          settings, vocabulary, policies, prompts, scenario families, benchmarks
src/caseforge/   engine, agents, tools, knowledge, memory, reasoning, governance,
                 persistence, simulation, evaluation, api, ui
tests/           unit, contract, architecture, restart (real process kills), API, console
eval_results/    evaluation reports, comparisons, and recorded model responses
docs/            architecture, governance, evaluation, pre-registration
```
