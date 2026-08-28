from __future__ import annotations

import hashlib
import inspect
from dataclasses import FrozenInstanceError, dataclass, fields, replace
from pathlib import Path

import numpy as np
import pytest

import fura_mappo.prediction as prediction_module
import fura_mappo.prediction.governance as governance_module
from fura_mappo.demand import DemandEvent, DemandTrace, save_demand_trace
from fura_mappo.prediction import (
    BaselineKind,
    BaselineSelectionFailure,
    BaselineValidationCandidate,
    CalibrationDisposition,
    DatasetProtocolSpec,
    DatasetSplitManifest,
    HistoryTransformKind,
    LearnedConfigFreezeIdentity,
    LearnedConfigValidationCandidate,
    LockedBaselineFreezeIdentity,
    LockedLearnedPredictorIdentity,
    PointMetricSummary,
    PointObjectiveKind,
    PredictionBootstrapSpec,
    PredictionOODKind,
    PreTestFreeze,
    PreTrainingFreeze,
    PreTrainingFreezeFailure,
    SplitLabel,
    TraceOODAssignment,
    TracePointMetrics,
    TrainingSeedValidationResult,
    VerifiedPredictionArtifact,
    ZoneSchema,
    build_pretest_freeze,
    build_pretraining_freeze,
    build_split_manifest_from_artifacts,
    load_verified_prediction_artifact,
    select_learned_validation_config,
    select_validation_baselines,
)


def _sha256(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _zone_sha256() -> str:
    return ZoneSchema([[0.0, 1.0, 0.0, 1.0], [1.0, 2.0, 0.0, 1.0]]).sha256


def _trace(
    *,
    start_step: int,
    num_steps: int,
    marker: int,
    intensities: tuple[float, float],
) -> DemandTrace:
    counts = np.zeros((num_steps, 2), dtype=np.int64)
    counts[0, marker % 2] = marker
    events = tuple(
        DemandEvent(
            event_id=event_id,
            arrival_step=start_step,
            zone_id=marker % 2,
            position=(marker % 2 + 0.5, 0.5),
            priority=0.5,
            service_time=1,
            deadline=start_step + 2,
        )
        for event_id in range(marker)
    )
    intensity_array = np.tile(np.asarray(intensities, dtype=np.float64), (num_steps, 1))
    return DemandTrace(start_step, counts, intensity_array, events)


def _resolved_config(
    *,
    seed: int,
    num_steps: int,
    intensities: tuple[float, float],
) -> dict[str, object]:
    return {
        "schema": "fura-mappo.demand-generation",
        "version": 1,
        "demand": {
            "type": "stationary_poisson",
            "seed": seed,
            "intensities": list(intensities),
            "zone_bounds": [[0.0, 1.0, 0.0, 1.0], [1.0, 2.0, 0.0, 1.0]],
            "priority_range": [0.5, 0.5],
            "service_time_range": [1, 1],
            "deadline_offset_range": [2, 2],
        },
        "generation": {"num_steps": num_steps},
    }


def _verified_artifact(
    tmp_path: Path,
    *,
    trace_id: str,
    seed: int,
    start_step: int = 10,
    num_steps: int = 20,
    marker: int = 1,
    intensities: tuple[float, float] = (0.2, 0.3),
) -> VerifiedPredictionArtifact:
    tmp_path.mkdir(parents=True, exist_ok=True)
    trace = _trace(
        start_step=start_step,
        num_steps=num_steps,
        marker=marker,
        intensities=intensities,
    )
    path = save_demand_trace(
        tmp_path / f"{trace_id}.npz",
        trace,
        resolved_config=_resolved_config(
            seed=seed,
            num_steps=num_steps,
            intensities=intensities,
        ),
    )
    return load_verified_prediction_artifact(path, trace_id)


def _metrics(
    primary_mse: float,
    *,
    signature: tuple[tuple[str, int, int], ...],
    prediction_horizon: int = 2,
    num_zones: int = 2,
    schema: str | None = None,
) -> PointMetricSummary:
    zone_schema = schema or _zone_sha256()
    mse = [[primary_mse] * num_zones for _ in range(prediction_horizon)]
    mae = [[primary_mse**0.5] * num_zones for _ in range(prediction_horizon)]
    bias = [[0.0] * num_zones for _ in range(prediction_horizon)]
    return PointMetricSummary(
        trace_metrics=tuple(
            TracePointMetrics(
                trace_id=trace_id,
                trace_start_step=start_step,
                trace_num_steps=num_steps,
                anchor_counts_by_horizon=[
                    num_steps - lead for lead in range(1, prediction_horizon + 1)
                ],
                mse_by_horizon_zone=mse,
                mae_by_horizon_zone=mae,
                bias_by_horizon_zone=bias,
            )
            for trace_id, start_step, num_steps in signature
        ),
        prediction_horizon=prediction_horizon,
        num_zones=num_zones,
        zone_schema_sha256=zone_schema,
    )


@dataclass(frozen=True)
class _Fixture:
    freeze: PreTrainingFreeze
    artifacts: tuple[VerifiedPredictionArtifact, ...]
    protocols_by_history: dict[int, DatasetProtocolSpec]
    validation_signature: tuple[tuple[str, int, int], ...]
    baseline_selection: object
    learned_selection: object
    baseline_predictor_hashes: dict[BaselineKind, str]


def _baseline_selection(
    fixture: _Fixture,
    *,
    winner: BaselineKind = BaselineKind.B3,
    b2_history: int = 16,
    b3_history: int = 8,
    b3_alpha: float = 0.5,
) -> object:
    locked_scores = {
        BaselineKind.B0: 3.0,
        BaselineKind.B1: 4.0,
        BaselineKind.B2: 5.0,
        BaselineKind.B3: 6.0,
        BaselineKind.B4: 7.0,
        BaselineKind.B5: 8.0,
    }
    locked_scores[winner] = 0.25
    fixed_histories = {
        BaselineKind.B0: 4,
        BaselineKind.B1: 8,
        BaselineKind.B4: 16,
        BaselineKind.B5: 32,
    }
    candidates = [
        BaselineValidationCandidate(
            baseline=baseline,
            protocol=fixture.protocols_by_history[history_length],
            metrics=_metrics(
                locked_scores[baseline],
                signature=fixture.validation_signature,
            ),
        )
        for baseline, history_length in fixed_histories.items()
    ]
    candidates.extend(
        BaselineValidationCandidate(
            baseline=BaselineKind.B2,
            protocol=fixture.protocols_by_history[history_length],
            metrics=_metrics(
                locked_scores[BaselineKind.B2] if history_length == b2_history else 20.0,
                signature=fixture.validation_signature,
            ),
        )
        for history_length in (4, 8, 16, 32)
    )
    candidates.extend(
        BaselineValidationCandidate(
            baseline=BaselineKind.B3,
            protocol=fixture.protocols_by_history[history_length],
            metrics=_metrics(
                locked_scores[BaselineKind.B3]
                if (history_length, alpha) == (b3_history, b3_alpha)
                else 20.0,
                signature=fixture.validation_signature,
            ),
            alpha=alpha,
        )
        for history_length in (4, 8, 16, 32)
        for alpha in (0.25, 0.5, 0.75)
    )
    return select_validation_baselines(candidates)


def _learned_selection(
    fixture: _Fixture,
    *,
    winner_config_sha256: str | None = None,
    checkpoint_label: str = "checkpoint",
) -> object:
    winner_sha = winner_config_sha256 or fixture.freeze.learned_config_identities[0].config_sha256
    protocols = {
        protocol.sha256: protocol
        for protocol in (
            fixture.freeze.primary_protocol,
            *fixture.freeze.secondary_protocols,
        )
    }
    candidates = []
    for identity in fixture.freeze.learned_config_identities:
        primary_mse = 0.25 if identity.config_sha256 == winner_sha else 4.0
        candidates.append(
            LearnedConfigValidationCandidate(
                config_sha256=identity.config_sha256,
                protocol=protocols[identity.protocol_sha256],
                objective=identity.objective,
                transform=identity.transform,
                model_complexity_key=identity.model_complexity_key,
                canonical_order=identity.canonical_order,
                seed_results=tuple(
                    TrainingSeedValidationResult(
                        training_seed=seed,
                        checkpoint_sha256=_sha256(
                            f"{checkpoint_label}-{identity.config_sha256}-{seed}"
                        ),
                        metrics=_metrics(primary_mse, signature=fixture.validation_signature),
                        deterministic_validation_passed=True,
                        failure_reason=None,
                    )
                    for seed in fixture.freeze.fixed_training_seeds
                ),
            )
        )
    return select_learned_validation_config(candidates)


def _fixture(
    tmp_path: Path,
    *,
    geometry: dict[str, tuple[int, int]] | None = None,
    fixed_seeds: tuple[int, ...] = (1, 2, 3),
    selected_learned_history: int = 8,
    ood_cell: str = "near_axis_a",
) -> _Fixture:
    tmp_path.mkdir(parents=True, exist_ok=True)
    geometry = geometry or {}
    protocols_by_history = {
        history_length: DatasetProtocolSpec(history_length, 2, _zone_sha256())
        for history_length in (4, 8, 16, 32)
    }
    definitions = (
        (SplitLabel.TRAIN, "train_a", 1, 1, (0.2, 0.3)),
        (SplitLabel.TRAIN, "train_b", 2, 2, (0.2, 0.3)),
        (SplitLabel.VALIDATION, "validation_z", 3, 3, (0.2, 0.3)),
        (SplitLabel.VALIDATION, "validation_a", 4, 4, (0.2, 0.3)),
        (SplitLabel.TEST_ID, "test_id_z", 5, 5, (0.2, 0.3)),
        (SplitLabel.TEST_ID, "test_id_a", 6, 6, (0.2, 0.3)),
        (SplitLabel.TEST_OOD, "test_ood_z", 7, 7, (0.7, 0.8)),
        (SplitLabel.TEST_OOD, "test_ood_a", 8, 8, (0.9, 1.0)),
    )
    artifacts = tuple(
        _verified_artifact(
            tmp_path,
            trace_id=trace_id,
            seed=seed,
            start_step=geometry.get(trace_id, (10, 20))[0],
            num_steps=geometry.get(trace_id, (10, 20))[1],
            marker=marker,
            intensities=intensities,
        )
        for _, trace_id, seed, marker, intensities in definitions
    )
    primary = protocols_by_history[4]
    manifest = build_split_manifest_from_artifacts(
        tuple(
            (split, artifact)
            for (split, _, _, _, _), artifact in zip(definitions, artifacts, strict=True)
        ),
        primary,
    )
    selected_protocol = protocols_by_history[selected_learned_history]
    learned_identities = (
        LearnedConfigFreezeIdentity(
            _sha256("learned-selected"),
            selected_protocol.sha256,
            PointObjectiveKind.O0,
            HistoryTransformKind.T0,
            (8, 32),
            0,
        ),
        LearnedConfigFreezeIdentity(
            _sha256("learned-other"),
            primary.sha256,
            PointObjectiveKind.O1,
            HistoryTransformKind.T1,
            (16, 64),
            1,
        ),
    )
    freeze = build_pretraining_freeze(
        primary_protocol=primary,
        secondary_protocols=tuple(
            protocol
            for history_length, protocol in protocols_by_history.items()
            if history_length != 4
        ),
        split_manifest=manifest,
        verified_artifacts=artifacts,
        calibration_disposition=CalibrationDisposition.EMPTY,
        ood_assignments=(
            TraceOODAssignment("test_id_z", PredictionOODKind.ID, "primary_id_z"),
            TraceOODAssignment("test_id_a", PredictionOODKind.ID, "primary_id_a"),
            TraceOODAssignment("test_ood_z", PredictionOODKind.NEAR_OOD, ood_cell),
            TraceOODAssignment(
                "test_ood_a",
                PredictionOODKind.STRUCTURAL_OOD,
                "heldout_family_a",
            ),
        ),
        fixed_training_seeds=fixed_seeds,
        learned_config_identities=learned_identities,
        rng_namespace_plan_sha256=_sha256("rng-plan"),
        training_plan_sha256=_sha256("training-plan"),
        baseline_plan_sha256=_sha256("baseline-plan"),
    )
    signature = tuple(
        sorted(
            (
                (entry.source.trace_id, entry.source.start_step, entry.source.num_steps)
                for entry in manifest.entries
                if entry.split is SplitLabel.VALIDATION
            ),
            key=lambda item: item[0],
        )
    )
    shell = _Fixture(
        freeze=freeze,
        artifacts=artifacts,
        protocols_by_history=protocols_by_history,
        validation_signature=signature,
        baseline_selection=None,
        learned_selection=None,
        baseline_predictor_hashes={
            baseline: _sha256(f"baseline-predictor-{baseline.value}") for baseline in BaselineKind
        },
    )
    object.__setattr__(shell, "baseline_selection", _baseline_selection(shell))
    object.__setattr__(shell, "learned_selection", _learned_selection(shell))
    return shell


def _build(fixture: _Fixture, **changes: object) -> PreTestFreeze:
    values: dict[str, object] = {
        "pretraining_freeze": fixture.freeze,
        "verified_artifacts": fixture.artifacts,
        "baseline_selection": fixture.baseline_selection,
        "learned_selection": fixture.learned_selection,
        "baseline_predictor_sha256_by_kind": fixture.baseline_predictor_hashes,
        "predictor_implementation_sha256": _sha256("predictor-implementation"),
        "metric_implementation_sha256": _sha256("metric-implementation"),
        "evaluation_plan_sha256": _sha256("evaluation-plan"),
        "bootstrap_spec": PredictionBootstrapSpec(200, 17, "linear"),
        "bootstrap_implementation_sha256": _sha256("bootstrap-implementation"),
        "official_failure_state_plan_sha256": _sha256("failure-state-plan"),
        "git_commit_sha": "a" * 40,
        "runtime_provenance_sha256": _sha256("runtime-provenance"),
    }
    values.update(changes)
    return build_pretest_freeze(**values)  # type: ignore[arg-type]


def test_successful_factory_returns_only_immutable_layer_b_identities(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    result = _build(fixture)

    assert result.schema == "fura-mappo.prediction-pre-test-freeze"
    assert result.version == 1
    assert result.pretraining_freeze is fixture.freeze
    assert result.pretraining_freeze_sha256 == fixture.freeze.sha256
    assert result.prediction_horizon == 2
    assert result.num_zones == 2
    assert result.zone_schema_sha256 == _zone_sha256()
    assert len(result.sha256) == 64
    assert not hasattr(result, "__dict__")
    with pytest.raises(FrozenInstanceError):
        result.git_commit_sha = "b" * 40  # type: ignore[misc]

    names = {item.name for item in fields(result)}
    forbidden = {
        "verified_artifacts",
        "baseline_selection",
        "learned_selection",
        "validation_metrics",
        "test_metrics",
        "forecast",
        "bootstrap_result",
        "scientific_label",
    }
    assert names.isdisjoint(forbidden)


def test_exact_baseline_identities_b2_b3_and_selected_b_star(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    result = _build(fixture)

    assert tuple(item.baseline for item in result.locked_baselines) == tuple(BaselineKind)
    assert all(isinstance(item, LockedBaselineFreezeIdentity) for item in result.locked_baselines)
    by_kind = {item.baseline: item for item in result.locked_baselines}
    assert by_kind[BaselineKind.B2].protocol_sha256 == fixture.protocols_by_history[16].sha256
    assert by_kind[BaselineKind.B3].protocol_sha256 == fixture.protocols_by_history[8].sha256
    assert by_kind[BaselineKind.B3].alpha == 0.5
    assert all(
        item.alpha is None
        for item in result.locked_baselines
        if item.baseline is not BaselineKind.B3
    )
    assert result.selected_baseline is fixture.baseline_selection.selected.baseline
    assert result.selected_baseline_identity is by_kind[result.selected_baseline]
    assert all(
        item.predictor_sha256 == fixture.baseline_predictor_hashes[item.baseline]
        for item in result.locked_baselines
    )


def test_locked_baseline_identity_enforces_b3_alpha_contract() -> None:
    with pytest.raises(ValueError, match="frozen grid"):
        LockedBaselineFreezeIdentity(BaselineKind.B3, "a" * 64, "b" * 64, 0.3)
    with pytest.raises(ValueError, match="None"):
        LockedBaselineFreezeIdentity(BaselineKind.B2, "a" * 64, "b" * 64, 0.5)


@pytest.mark.parametrize(
    "mapping",
    [
        {
            baseline: _sha256(baseline.value)
            for baseline in BaselineKind
            if baseline is not BaselineKind.B5
        },
        {**{baseline: _sha256(baseline.value) for baseline in BaselineKind}, "extra": "a" * 64},
        {baseline: "A" * 64 for baseline in BaselineKind},
        [(baseline, _sha256(baseline.value)) for baseline in BaselineKind],
    ],
)
def test_baseline_predictor_mapping_requires_exact_typed_coverage(
    tmp_path: Path,
    mapping: object,
) -> None:
    fixture = _fixture(tmp_path)

    with pytest.raises((TypeError, ValueError)):
        _build(fixture, baseline_predictor_sha256_by_kind=mapping)


def test_caller_mapping_and_artifact_order_do_not_change_hash(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    forward = _build(fixture)
    reverse_mapping = dict(reversed(tuple(fixture.baseline_predictor_hashes.items())))
    reordered = _build(
        fixture,
        verified_artifacts=tuple(reversed(fixture.artifacts)),
        baseline_predictor_sha256_by_kind=reverse_mapping,
    )

    assert reordered == forward
    assert reordered.sha256 == forward.sha256


def test_selected_learned_identity_and_all_seed_predictors_are_exact(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    result = _build(fixture)
    selected = fixture.learned_selection.selected

    assert result.selected_learned_config_identity == fixture.freeze.learned_config_identities[0]
    assert tuple(item.training_seed for item in result.learned_predictor_identities) == (1, 2, 3)
    assert all(
        isinstance(item, LockedLearnedPredictorIdentity)
        for item in result.learned_predictor_identities
    )
    assert tuple(item.checkpoint_sha256 for item in result.learned_predictor_identities) == tuple(
        seed.checkpoint_sha256 for seed in selected.seed_results
    )
    assert len({item.predictor_sha256 for item in result.learned_predictor_identities}) == 3
    assert [item.name for item in fields(LockedLearnedPredictorIdentity)] == [
        "training_seed",
        "checkpoint_sha256",
        "predictor_sha256",
    ]


@pytest.mark.parametrize(
    ("field_name", "replacement"),
    [
        ("config_sha256", _sha256("unknown-config")),
        ("protocol_sha256", None),
        ("objective", PointObjectiveKind.O1),
        ("transform", HistoryTransformKind.T1),
        ("model_complexity_key", (99, 100)),
        ("canonical_order", 9),
    ],
)
def test_selected_learned_candidate_requires_full_layer_a_match(
    tmp_path: Path,
    field_name: str,
    replacement: object,
) -> None:
    fixture = _fixture(tmp_path)
    selected_identity = fixture.freeze.learned_config_identities[0]
    value = fixture.protocols_by_history[16].sha256 if replacement is None else replacement
    forged_identity = replace(selected_identity, **{field_name: value})
    forged_freeze = replace(
        fixture.freeze,
        learned_config_identities=(forged_identity, fixture.freeze.learned_config_identities[1]),
    )

    with pytest.raises(ValueError):
        _build(fixture, pretraining_freeze=forged_freeze)


def test_layer_a_rejects_duplicate_learned_config_ambiguity(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    selected = fixture.freeze.learned_config_identities[0]

    with pytest.raises(PreTrainingFreezeFailure):
        replace(
            fixture.freeze,
            learned_config_identities=(selected, replace(selected, canonical_order=99)),
        )


def test_fixed_seed_set_and_checkpoint_completeness_are_hard_requirements(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    mismatched_freeze = replace(fixture.freeze, fixed_training_seeds=(4, 5, 6))
    with pytest.raises(ValueError, match="fixed seeds"):
        _build(fixture, pretraining_freeze=mismatched_freeze)

    selected = fixture.learned_selection.selected
    object.__setattr__(selected.seed_results[0], "checkpoint_sha256", None)
    with pytest.raises(ValueError, match="checkpoint"):
        _build(fixture)


def test_seed_results_cannot_be_dropped_replaced_or_reordered(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    selected = fixture.learned_selection.selected
    object.__setattr__(selected, "seed_results", tuple(reversed(selected.seed_results)))

    with pytest.raises(ValueError, match="fixed training seeds"):
        _build(fixture)


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("prediction_horizon", 3),
        ("num_zones", 3),
        ("zone_schema_sha256", "f" * 64),
        ("validation_trace_signature", (("wrong", 10, 20),)),
    ],
)
def test_baseline_and_learned_validation_bindings_must_match(
    tmp_path: Path,
    field_name: str,
    value: object,
) -> None:
    fixture = _fixture(tmp_path)
    object.__setattr__(fixture.learned_selection, field_name, value)

    with pytest.raises(ValueError, match="baseline/learned"):
        _build(fixture)


@pytest.mark.parametrize(
    ("field_name", "value", "match"),
    [
        ("num_zones", 3, "manifest geometry"),
        ("zone_schema_sha256", "f" * 64, "Layer-A freeze"),
        ("validation_trace_signature", (("wrong", 10, 20),), "Layer-A membership"),
    ],
)
def test_selection_geometry_must_match_layer_a_manifest(
    tmp_path: Path,
    field_name: str,
    value: object,
    match: str,
) -> None:
    fixture = _fixture(tmp_path)
    object.__setattr__(fixture.baseline_selection, field_name, value)
    object.__setattr__(fixture.learned_selection, field_name, value)

    with pytest.raises(ValueError, match=match):
        _build(fixture)


def test_unknown_locked_protocol_is_rejected(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    candidate = fixture.baseline_selection.locked_variants[0]
    object.__setattr__(candidate, "protocol", DatasetProtocolSpec(64, 2, _zone_sha256()))

    with pytest.raises(ValueError, match="unknown"):
        _build(fixture)


def test_authoritative_artifact_missing_extra_duplicate_and_wrong_type_fail(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path / "fixture")
    extra = _verified_artifact(
        tmp_path / "extra",
        trace_id="extra_trace",
        seed=99,
        marker=9,
        intensities=(1.2, 1.3),
    )

    with pytest.raises(PreTrainingFreezeFailure):
        _build(fixture, verified_artifacts=fixture.artifacts[:-1])
    with pytest.raises(PreTrainingFreezeFailure):
        _build(fixture, verified_artifacts=(*fixture.artifacts, extra))
    with pytest.raises(PreTrainingFreezeFailure):
        _build(fixture, verified_artifacts=(*fixture.artifacts, fixture.artifacts[0]))
    with pytest.raises(TypeError):
        _build(fixture, verified_artifacts=(*fixture.artifacts, object()))


def test_authoritative_source_mismatch_uses_layer_a_failure(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    forged_manifest = DatasetSplitManifest(
        tuple(
            replace(
                entry,
                source=replace(entry.source, content_sha256=_sha256("forged-content")),
            )
            if entry.source.trace_id == "validation_a"
            else entry
            for entry in fixture.freeze.split_manifest.entries
        )
    )
    forged_freeze = replace(fixture.freeze, split_manifest=forged_manifest)

    with pytest.raises(PreTrainingFreezeFailure):
        _build(fixture, pretraining_freeze=forged_freeze)


def test_b5_structural_support_failure_namespace_propagates(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path, geometry={"train_b": (30, 20)})

    with pytest.raises(BaselineSelectionFailure) as captured:
        _build(fixture)

    assert captured.value.status == "PREDICTION_BASELINE_SELECTION_FAILURE"


def test_test_trace_and_ood_identities_derive_only_from_layer_a(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    result = _build(fixture)

    assert result.test_id_trace_ids == fixture.freeze.trace_ids_for_split(SplitLabel.TEST_ID)
    assert result.test_ood_trace_ids == fixture.freeze.trace_ids_for_split(SplitLabel.TEST_OOD)
    assert result.test_id_trace_ids == ("test_id_z", "test_id_a")
    assert result.test_ood_trace_ids == ("test_ood_a", "test_ood_z")
    assert result.final_ood_assignments == fixture.freeze.ood_assignments
    assert tuple(item.cell_id for item in result.final_ood_assignments) == (
        "primary_id_a",
        "primary_id_z",
        "heldout_family_a",
        "near_axis_a",
    )


def test_bootstrap_spec_is_bound_without_computation(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    spec = PredictionBootstrapSpec(321, 654, "lower")
    result = _build(fixture, bootstrap_spec=spec)

    assert result.bootstrap_spec is spec
    assert result.bootstrap_spec.num_resamples == 321
    assert result.bootstrap_spec.rng_seed == 654
    assert result.bootstrap_spec.quantile_method == "lower"


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("predictor_implementation_sha256", "A" * 64),
        ("metric_implementation_sha256", "short"),
        ("evaluation_plan_sha256", "0" * 63),
        ("bootstrap_implementation_sha256", "g" * 64),
        ("official_failure_state_plan_sha256", None),
        ("runtime_provenance_sha256", 1),
        ("git_commit_sha", "A" * 40),
        ("git_commit_sha", "a" * 39),
    ],
)
def test_explicit_hash_and_git_identities_are_strict(
    tmp_path: Path,
    field_name: str,
    value: object,
) -> None:
    fixture = _fixture(tmp_path)

    with pytest.raises((TypeError, ValueError)):
        _build(fixture, **{field_name: value})


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("predictor_implementation_sha256", _sha256("predictor-implementation-v2")),
        ("metric_implementation_sha256", _sha256("metric-implementation-v2")),
        ("evaluation_plan_sha256", _sha256("evaluation-plan-v2")),
        ("bootstrap_implementation_sha256", _sha256("bootstrap-implementation-v2")),
        ("official_failure_state_plan_sha256", _sha256("failure-state-plan-v2")),
        ("git_commit_sha", "b" * 40),
        ("runtime_provenance_sha256", _sha256("runtime-provenance-v2")),
    ],
)
def test_explicit_identity_changes_are_hash_sensitive(
    tmp_path: Path,
    field_name: str,
    value: object,
) -> None:
    fixture = _fixture(tmp_path)

    assert _build(fixture, **{field_name: value}).sha256 != _build(fixture).sha256


@pytest.mark.parametrize(
    "spec",
    [
        PredictionBootstrapSpec(201, 17, "linear"),
        PredictionBootstrapSpec(200, 18, "linear"),
        PredictionBootstrapSpec(200, 17, "lower"),
    ],
)
def test_bootstrap_identity_components_change_layer_b_hash(
    tmp_path: Path,
    spec: PredictionBootstrapSpec,
) -> None:
    fixture = _fixture(tmp_path)

    assert _build(fixture, bootstrap_spec=spec).sha256 != _build(fixture).sha256


def test_baseline_lock_variants_and_selected_b_star_change_hash(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    original = _build(fixture)
    changed_b2 = _build(fixture, baseline_selection=_baseline_selection(fixture, b2_history=32))
    changed_b3_protocol = _build(
        fixture,
        baseline_selection=_baseline_selection(fixture, b3_history=16),
    )
    changed_b3_alpha = _build(
        fixture,
        baseline_selection=_baseline_selection(fixture, b3_alpha=0.75),
    )
    changed_b_star = _build(
        fixture,
        baseline_selection=_baseline_selection(fixture, winner=BaselineKind.B0),
    )

    assert (
        len(
            {
                original.sha256,
                changed_b2.sha256,
                changed_b3_protocol.sha256,
                changed_b3_alpha.sha256,
                changed_b_star.sha256,
            }
        )
        == 5
    )


def test_learned_config_protocol_checkpoint_and_seed_changes_are_hash_sensitive(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path / "original")
    original = _build(fixture)
    changed_selected = _build(
        fixture,
        learned_selection=_learned_selection(
            fixture,
            winner_config_sha256=fixture.freeze.learned_config_identities[1].config_sha256,
        ),
    )
    changed_checkpoint = _build(
        fixture,
        learned_selection=_learned_selection(fixture, checkpoint_label="checkpoint-v2"),
    )
    protocol_fixture = _fixture(tmp_path / "protocol", selected_learned_history=16)
    seed_fixture = _fixture(tmp_path / "seeds", fixed_seeds=(4, 5, 6))

    hashes = {
        original.sha256,
        changed_selected.sha256,
        changed_checkpoint.sha256,
        _build(protocol_fixture).sha256,
        _build(seed_fixture).sha256,
    }
    assert len(hashes) == 5


def test_layer_a_source_test_membership_and_ood_cell_change_hash(tmp_path: Path) -> None:
    original = _fixture(tmp_path / "original")
    source_changed = _fixture(
        tmp_path / "source",
        geometry={"validation_a": (11, 19), "test_id_a": (11, 19)},
    )
    ood_changed = _fixture(tmp_path / "ood", ood_cell="near_axis_b")

    assert (
        len(
            {
                _build(original).sha256,
                _build(source_changed).sha256,
                _build(ood_changed).sha256,
            }
        )
        == 3
    )


def test_baseline_predictor_sha_change_is_hash_sensitive(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    changed = dict(fixture.baseline_predictor_hashes)
    changed[BaselineKind.B2] = _sha256("baseline-predictor-B2-v2")

    assert (
        _build(
            fixture,
            baseline_predictor_sha256_by_kind=changed,
        ).sha256
        != _build(fixture).sha256
    )


def test_direct_construction_is_structural_only_and_factory_is_trust_boundary(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    built = _build(fixture)
    direct = PreTestFreeze(
        pretraining_freeze=built.pretraining_freeze,
        locked_baselines=built.locked_baselines,
        selected_baseline=built.selected_baseline,
        selected_learned_config_identity=built.selected_learned_config_identity,
        learned_predictor_identities=built.learned_predictor_identities,
        predictor_implementation_sha256=built.predictor_implementation_sha256,
        metric_implementation_sha256=built.metric_implementation_sha256,
        evaluation_plan_sha256=built.evaluation_plan_sha256,
        bootstrap_spec=built.bootstrap_spec,
        bootstrap_implementation_sha256=built.bootstrap_implementation_sha256,
        official_failure_state_plan_sha256=built.official_failure_state_plan_sha256,
        git_commit_sha=built.git_commit_sha,
        runtime_provenance_sha256=built.runtime_provenance_sha256,
    )

    assert direct.sha256 == built.sha256
    docstring = inspect.getdoc(PreTestFreeze)
    assert docstring is not None
    assert "structural consistency" in docstring
    assert "build_pretest_freeze" in docstring
    assert "authoritative" in docstring


def test_production_builder_has_no_numeric_test_or_execution_surface() -> None:
    source = inspect.getsource(governance_module)
    builder_source = inspect.getsource(build_pretest_freeze)
    forbidden = (
        ".artifact",
        ".counts",
        ".intensities",
        "DemandTrace",
        "DemandEvent",
        "fit_absolute_step_train_climatology",
        "compute_locked_test_point_estimate",
        "evaluate_point_forecasts",
        "bootstrap_locked_test_delta_rmse",
        "interpret_primary_id_bootstrap",
        ".predict(",
        "np.random",
        "numpy.random",
        "subprocess",
        "os.system",
        "GitPython",
        "PREDICTION_EVALUATION_FAILURE",
        "FIRST_OFFICIAL_TEST_EXECUTION",
    )

    assert all(token not in source for token in forbidden)
    assert "preflight_layer_a_b5_support(" in builder_source
    assert "baseline_selection.selected.baseline" in builder_source
    assert ".primary_rmse" not in builder_source
    assert ".metrics" not in builder_source


def test_public_layer_b_api_is_exported_without_changing_layer_a_governance_all() -> None:
    assert prediction_module.LockedBaselineFreezeIdentity is LockedBaselineFreezeIdentity
    assert prediction_module.LockedLearnedPredictorIdentity is LockedLearnedPredictorIdentity
    assert prediction_module.PreTestFreeze is PreTestFreeze
    assert prediction_module.build_pretest_freeze is build_pretest_freeze
    for name in (
        "LockedBaselineFreezeIdentity",
        "LockedLearnedPredictorIdentity",
        "PreTestFreeze",
        "build_pretest_freeze",
    ):
        assert name in prediction_module.__all__
    assert governance_module.__all__ == [
        "CalibrationDisposition",
        "LearnedConfigFreezeIdentity",
        "PredictionOODKind",
        "PreTrainingFreeze",
        "PreTrainingFreezeFailure",
        "TraceOODAssignment",
        "build_pretraining_freeze",
    ]


def test_no_new_scientific_failure_class_or_automatic_recovery(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    source = inspect.getsource(governance_module)

    assert "class PreTestFreezeFailure" not in source
    assert "fallback predictor" not in source
    assert "rerun" not in source.lower()
    assert "recovery" not in source.lower()
    with pytest.raises(ValueError):
        _build(fixture, git_commit_sha="invalid")
