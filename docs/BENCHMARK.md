# Agent Benchmark

JobPilot V0.4 includes a deterministic, offline benchmark so changes to Agent routing and reliability can be measured in CI without spending model tokens.

Run:

```bash
python -m app.evaluation.benchmark
```

or:

```http
POST /api/benchmarks/run
```

The core suite currently checks:

1. Job-search Planner routing (`resume -> search -> ranking -> evaluate`).
2. Application routing (`resume -> browser -> evaluate`) without bypassing the outer approval gate.
3. Evaluation quality-gate behavior for a successful auditable browser run.
4. Timeout classification as retryable.
5. CAPTCHA classification as non-retryable.

Results are persisted in `benchmark_runs`, allowing the UI/metrics endpoint to show recent benchmark history.

This suite is intentionally deterministic. A later online benchmark can add live-browser success rate, Top-K ranking quality and cost/latency distributions when credentials and a controlled test environment are available.
