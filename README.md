# FURA-MAPPO

Forecast-guided, uncertainty-aware multi-agent resource pre-positioning under nonstationary spatiotemporal demand.

## Status

- WP-00 and OPS-01 are complete.
- WP-01A is complete at `b7b48bb394bd4613652b4d1ff4158cb8503f52a5` (`wp01a-stable`).
- WP-01B is complete at `d67f71b5d75ee47adb120686914d32572ea7d6d1` (`wp01b-stable`).
- GitHub Actions `CPU checks` run #5 succeeded for the WP-01B implementation Commit.
- A100 CPU acceptance passed on Python 3.11.15 in the `fura-mappo` Conda environment, as confirmed by the project operator.
- The current work package is **WP-01C**, beginning with read-only design analysis for configuration, serialization, CLI, summaries, and optional visualization.
- WP-01 remains CPU-only. Agents, rewards, forecasting models, MAPPO, PyTorch, CUDA changes, and GPU training remain out of scope.

## Implemented demand processes

- `StationaryPoissonDemand`
- `DriftingHotspotDemand`
- `MarkovSwitchingDemand`
- `BurstDemand`

All processes are exogenous, reproducible, instance-RNG isolated, and share the frozen `DemandProcess.reset/step/generate` semantics.

## Research objective

The project studies whether future demand forecasts and calibrated forecast uncertainty improve proactive multi-agent resource placement under nonstationary demand. The sequence first establishes exogenous demand processes and reactive/oracle baselines, then introduces forecasting and uncertainty-aware MAPPO, followed by in-distribution, out-of-distribution, and forecast-value phase-diagram analyses.

## Documentation

- Chinese overview: `README_zh.md`
- Project requirements: `docs/PROJECT_REQUIREMENTS.md`
- Research plan: `docs/RESEARCH_PLAN.md`
- Current state: `docs/PROJECT_STATE.md`
- Codex workflow: `docs/CODEX_WORKFLOW.md`
- WP-01 demand specification: `docs/WP01_DEMAND_GENERATION.md`
- Completed WP-01A specification: `docs/WP01A_SPEC.md`
- Completed WP-01B specification: `docs/WP01B_SPEC.md`
- WP-01B review record: `docs/WP01B_REVIEW.md`
- Session handoff and WP-01C entry point: `docs/SESSION_HANDOFF.md`

## CPU verification

```bash
python -m pip install -e ".[dev]"
bash scripts/verify_cpu.sh
```

Version-control writes are initiated by the user. Codex may edit and test files but must not commit, push, or tag.
