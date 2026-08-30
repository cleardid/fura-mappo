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
- Scientific design status: **WP-03 OFFICIAL POINT-PREDICTION v1 SCIENTIFIC SPEC FROZEN — D-043**.
- WP-03 official experiment: **NOT EXECUTED**; `FIRST OFFICIAL TEST EXECUTION`: not occurred;
  `test_id/test_ood`: `UNSPENT`.

## Completed demand system

The package provides four exogenous demand processes, strict YAML configuration v1, stable config hashing, NPZ demand-trace artifact v1, provenance/integrity checks, `fura-demand generate`, `fura-demand summarize`, and deterministic JSON summaries.

In the frozen Primary H=2 setting, the true-future Oracle improved normalized completion fraction over
Reactive by about 0.3175 on average. This does not establish learned-predictor, forecast-control,
uncertainty, MAPPO, or cross-environment results. D-043 freezes P2 point prediction only: P4/P8 are not
executed and calibration is `EMPTY (0 traces)`. Repository publication is determined externally by independent
patch review, manual Commit/Push, and successful GitHub Actions; the specification does not self-assert that its
Commit is accepted, and publication is not execution authorization. The next engineering stage after
accepted-main publication is only `WP-03 Execution Stack Implementation Preparation`. Official execution
remains locked without separate explicit authorization.

## Documentation

- `README_zh.md`
- `docs/PROJECT_STATE.md`
- `docs/SESSION_HANDOFF.md`
- `docs/RESEARCH_PLAN.md`
- `docs/ANALYSIS_PLAN.md`
- `docs/DECISIONS.md`
- `docs/WP03_OFFICIAL_EXPERIMENT_SPEC.md`
- `docs/WP01C_SPEC.md`
- `docs/WP01C_REVIEW.md`
