# FURA-MAPPO

Forecast-guided, uncertainty-aware multi-agent resource pre-positioning under nonstationary spatiotemporal demand.

## Status

- WP-00 and OPS-01 are complete.
- WP-01A is complete at implementation Commit `b7b48bb394bd4613652b4d1ff4158cb8503f52a5`.
- GitHub Actions `CPU checks` run #3 completed successfully for that Commit.
- A100 CPU and WP-01A acceptance tests passed, as confirmed by the project operator.
- Stable milestone tag: `wp01a-stable` → `b7b48bb394bd4613652b4d1ff4158cb8503f52a5`.
- The next work package is **WP-01B**. It starts with read-only design analysis for Drifting Hotspot, Markov Switching, and Burst Demand; no implementation begins before design review.
- WP-01 remains CPU-only. PyTorch, CUDA changes, GPU training, agents, rewards, forecasting models, and MAPPO remain out of scope.

## Research objective

The project studies whether future demand forecasts and calibrated forecast uncertainty can improve proactive multi-agent resource placement under nonstationary demand. The research sequence first establishes exogenous demand processes and reactive/oracle baselines, then introduces forecasting and uncertainty-aware MAPPO, followed by in-distribution, out-of-distribution, and forecast-value phase-diagram analyses.

## Documentation

- Chinese overview: `README_zh.md`
- Project requirements: `docs/PROJECT_REQUIREMENTS.md`
- Research plan: `docs/RESEARCH_PLAN.md`
- Current state: `docs/PROJECT_STATE.md`
- Codex workflow: `docs/CODEX_WORKFLOW.md`
- WP-01 demand specification: `docs/WP01_DEMAND_GENERATION.md`
- Completed WP-01A specification: `docs/WP01A_SPEC.md`
- Completed WP-01A review record: `docs/WP01A_REVIEW.md`
- Session handoff and WP-01B entry point: `docs/SESSION_HANDOFF.md`

## CPU verification

```bash
python -m pip install -e ".[dev]"
bash scripts/verify_cpu.sh
```

All version-control writes are performed manually by the user. Codex may edit and test files but must not commit or push.
