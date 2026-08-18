# FURA-MAPPO

Forecast-guided, uncertainty-aware multi-agent resource pre-positioning under nonstationary spatiotemporal demand.

## Status

- WP-01A: `wp01a-stable`
- WP-01B: `wp01b-stable`
- WP-01C: `wp01c-stable` -> `29a042f7b9fc80d3356cd5c63df1cd26b4078d9b`
- WP-01C Mac: 421 tests passed on Python 3.11.15.
- WP-01C A100: 421 tests passed on Python 3.11.15.
- GitHub Actions `CPU checks`: run #7, success.
- Current next stage: **WP-02 read-only design** for the resource-service environment and reactive/Oracle control baselines.

## Completed demand system

The package provides four exogenous demand processes, strict YAML configuration v1, stable config hashing, NPZ demand-trace artifact v1, provenance/integrity checks, `fura-demand generate`, `fura-demand summarize`, and deterministic JSON summaries.

The next scientific gate is to compare reactive control with a true-future Oracle in a frozen resource-service environment before adding forecasting or MARL.

## Documentation

- `README_zh.md`
- `docs/PROJECT_STATE.md`
- `docs/SESSION_HANDOFF.md`
- `docs/RESEARCH_PLAN.md`
- `docs/ANALYSIS_PLAN.md`
- `docs/DECISIONS.md`
- `docs/WP01C_SPEC.md`
- `docs/WP01C_REVIEW.md`
