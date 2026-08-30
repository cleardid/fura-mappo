# FURA-MAPPO

Forecast-guided, uncertainty-aware multi-agent resource pre-positioning under nonstationary spatiotemporal demand.

## Status

- WP-01: completed (`wp01c-stable` -> `29a042f7b9fc80d3356cd5c63df1cd26b4078d9b`).
- WP-02A/B/C/D1/D2/D3 engineering: completed and accepted.
- WP-02D Primary gate: **SCIENTIFICALLY ACCEPTED PASS** at execution/provenance HEAD
  `0b0742f51d59c2a8aa63614993e51131016cd33c`; 256/256 traces were valid. Formal sensitivity has not
  been executed.
- **WP-03 IMPLEMENTATION CLOSED**; WP-03 accepted implementation Commit:
  `55dd9ef5f951d9328266b8e331ba5ae68854b414`.
- No WP-03 scientific result or official WP-03 prediction experiment exists.
- Current stage: **WP-03 Official Prediction Experiment Specification Freeze**.

## Completed demand system

The package provides four exogenous demand processes, strict YAML configuration v1, stable config hashing, NPZ demand-trace artifact v1, provenance/integrity checks, `fura-demand generate`, `fura-demand summarize`, and deterministic JSON summaries.

In the frozen Primary H=2 setting, the true-future Oracle improved normalized completion fraction over
Reactive by about 0.3175 on average. This does not establish learned-predictor, forecast-control,
uncertainty, MAPPO, or cross-environment results. The next stage is read-only specification design/freeze;
no official prediction data generation, training, or test execution is authorized before independent spec
review and manual Commit/Push/Actions acceptance.

## Documentation

- `README_zh.md`
- `docs/PROJECT_STATE.md`
- `docs/SESSION_HANDOFF.md`
- `docs/RESEARCH_PLAN.md`
- `docs/ANALYSIS_PLAN.md`
- `docs/DECISIONS.md`
- `docs/WP01C_SPEC.md`
- `docs/WP01C_REVIEW.md`
