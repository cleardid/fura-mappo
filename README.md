# FURA-MAPPO

Forecast-guided, uncertainty-aware multi-agent resource pre-positioning under nonstationary spatiotemporal demand.

## Status

- Stable engineering baseline: WP-00 and OPS-01 completed.
- Remote `main` baseline: `62675e43d17726adde3696f7fd5e5ab4208b6a2a`.
- Current work package: **WP-01A**, implementing the exogenous demand core and stationary Poisson demand.
- The reviewed WP-01A patch has no known blocking defect. Final Python 3.11 Mac verification, commit, push, and A100 server acceptance are still pending.
- WP-01 remains CPU-only; PyTorch, CUDA changes, GPU training, agents, rewards, and MAPPO are out of scope.

## Research objective

The project studies whether future demand forecasts and calibrated forecast uncertainty can improve proactive multi-agent resource placement under nonstationary demand. The research sequence first establishes exogenous demand processes and reactive/oracle baselines, then introduces forecasting and uncertainty-aware MAPPO, followed by in-distribution, out-of-distribution, and forecast-value phase-diagram analyses.

## Documentation

- Chinese overview: `README_zh.md`
- Project requirements: `docs/PROJECT_REQUIREMENTS.md`
- Research plan: `docs/RESEARCH_PLAN.md`
- Current state: `docs/PROJECT_STATE.md`
- Codex workflow: `docs/CODEX_WORKFLOW.md`
- WP-01 demand specification: `docs/WP01_DEMAND_GENERATION.md`
- WP-01A specification: `docs/WP01A_SPEC.md`
- WP-01A runbook: `docs/WP01A_RUNBOOK.md`
- WP-01A review record: `docs/WP01A_REVIEW.md`

## CPU verification

```bash
python -m pip install -e ".[dev]"
bash scripts/verify_cpu.sh
```

All version-control writes are performed manually by the user. Codex may edit and test files but must not commit or push.
