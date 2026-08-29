from __future__ import annotations

import hashlib
import inspect
from dataclasses import FrozenInstanceError, dataclass, fields, replace
from pathlib import Path

import numpy as np
import pytest

import fura_mappo.prediction as prediction_module
import fura_mappo.prediction.governance as governance_module
import fura_mappo.prediction.official_metrics as official_metrics_module
from fura_mappo.demand import DemandEvent, DemandTrace, save_demand_trace
from fura_mappo.prediction import (
    BaselineKind,
    BaselineSelectionResult,
    BaselineValidationCandidate,
    CalibrationDisposition,
    DatasetProtocolSpec,
    DemandForecast,
    FirstOfficialTestExecution,
    ForecastProvenance,
    HistoryTransformKind,
    LearnedConfigFreezeIdentity,
    LearnedConfigValidationCandidate,
    LearnedModelSelectionResult,
    LockedBaselineFreezeIdentity,
    LockedLearnedPredictorIdentity,
    OfficialPointForecastRecord,
    OfficialPredictorSplitForecasts,
    OfficialPredictorSplitMetrics,
    OfficialSealedPointMetrics,
    OfficialTestExecutionKind,
    PointForecastRecord,
    PointMetricSummary,
    PointObjectiveKind,
    PredictionBootstrapSpec,
    PredictionOODKind,
    PredictionSample,
    PredictionSource,
    PredictionTarget,
    PreTestFreeze,
    PreTrainingFreeze,
    SealedEvaluationState,
    SplitLabel,
    TraceOODAssignment,
    TracePointMetrics,
    TrainingSeedValidationResult,
    VerifiedPredictionArtifact,
    ZoneSchema,
    build_sealed_evaluation_state,
    build_split_manifest_from_artifacts,
    derive_prediction_samples_from_artifact,
    evaluate_official_sealed_point_metrics,
    load_verified_prediction_artifact,
    record_first_official_test_execution,
)
from fura_mappo.prediction import TestSetDisposition as Disposition

_BASELINE_ORDER = tuple(BaselineKind)
_MISSING = object()


def _sha256(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _zone_sha256() -> str:
    return ZoneSchema([[0.0, 1.0, 0.0, 1.0], [1.0, 2.0, 0.0, 1.0]]).sha256


def _trace(
    start_step: int,
    counts: list[list[int]],
    intensities: tuple[float, float],
) -> DemandTrace:
    count_array = np.asarray(counts, dtype=np.int64)
    events: list[DemandEvent] = []
    event_id = 0
    for offset, zone_counts in enumerate(count_array):
        for zone_id, zone_count in enumerate(zone_counts):
            for _ in range(int(zone_count)):
                arrival_step = start_step + offset
                events.append(
                    DemandEvent(
                        event_id=event_id,
                        arrival_step=arrival_step,
                        zone_id=zone_id,
                        position=(zone_id + 0.5, 0.5),
                        priority=0.5,
                        service_time=1,
                        deadline=arrival_step + 2,
                    )
                )
                event_id += 1
    intensity_array = np.tile(np.asarray(intensities, dtype=np.float64), (len(counts), 1))
    return DemandTrace(start_step, count_array, intensity_array, tuple(events))


def _resolved_config(
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
    start_step: int,
    counts: list[list[int]],
    intensities: tuple[float, float],
) -> VerifiedPredictionArtifact:
    artifact_path = save_demand_trace(
        tmp_path / f"{trace_id}.npz",
        _trace(start_step, counts, intensities),
        resolved_config=_resolved_config(seed, len(counts), intensities),
    )
    return load_verified_prediction_artifact(artifact_path, trace_id)


def _validation_metrics(source: PredictionSource, value: float) -> PointMetricSummary:
    prediction_horizon = 2
    shape = (prediction_horizon, source.num_zones)
    trace = TracePointMetrics(
        trace_id=source.trace_id,
        trace_start_step=source.start_step,
        trace_num_steps=source.num_steps,
        anchor_counts_by_horizon=np.asarray(
            [source.num_steps - lead for lead in range(1, prediction_horizon + 1)]
        ),
        mse_by_horizon_zone=np.full(shape, value),
        mae_by_horizon_zone=np.full(shape, np.sqrt(value)),
        bias_by_horizon_zone=np.zeros(shape),
    )
    return PointMetricSummary((trace,), prediction_horizon, source.num_zones, _zone_sha256())


def _forecast_for_sample(sample: PredictionSample, offset: float) -> DemandForecast:
    mean = sample.target.counts.astype(np.float64)
    mean[sample.target.valid_mask] += offset
    forecast = DemandForecast(
        absolute_step=sample.context.absolute_step,
        horizon=sample.context.prediction_horizon,
        zone_schema_sha256=sample.context.zone_schema_sha256,
        valid_mask=sample.target.valid_mask,
        mean=mean,
    )
    return forecast


def _records_for_source(
    *,
    artifact: VerifiedPredictionArtifact,
    protocol: DatasetProtocolSpec,
    predictor_sha256: str,
    prediction_config_sha256: str,
    split_manifest_sha256: str,
    git_commit_sha: str,
    offset: float,
) -> tuple[OfficialPointForecastRecord, ...]:
    records: list[OfficialPointForecastRecord] = []
    for sample in derive_prediction_samples_from_artifact(artifact, protocol):
        forecast = _forecast_for_sample(sample, offset)
        provenance = ForecastProvenance(
            predictor_artifact_sha256=predictor_sha256,
            prediction_config_sha256=prediction_config_sha256,
            dataset_protocol_sha256=protocol.sha256,
            split_manifest_sha256=split_manifest_sha256,
            sample_id=sample.sample_id,
            execution_git_commit=git_commit_sha,
        )
        point_record = PointForecastRecord(
            trace_id=artifact.source.trace_id,
            trace_start_step=artifact.source.start_step,
            trace_num_steps=artifact.source.num_steps,
            sample=sample,
            forecast=forecast,
        )
        records.append(OfficialPointForecastRecord(point_record, provenance))
    return tuple(records)


def _bundle(
    *,
    state: SealedEvaluationState,
    pretest: PreTestFreeze,
    artifacts: tuple[VerifiedPredictionArtifact, ...],
    split: SplitLabel,
    baseline: BaselineKind | None,
    training_seed: int | None,
    offset: float,
) -> OfficialPredictorSplitForecasts:
    if baseline is not None:
        locked = next(item for item in pretest.locked_baselines if item.baseline is baseline)
        predictor_sha256 = locked.predictor_sha256
        prediction_config_sha256 = pretest.pretraining_freeze.baseline_plan_sha256
        protocol_sha256 = locked.protocol_sha256
    else:
        locked_learned = next(
            item
            for item in pretest.learned_predictor_identities
            if item.training_seed == training_seed
        )
        predictor_sha256 = locked_learned.predictor_sha256
        prediction_config_sha256 = pretest.selected_learned_config_identity.config_sha256
        protocol_sha256 = pretest.selected_learned_config_identity.protocol_sha256
    protocol = next(
        item
        for item in (
            pretest.pretraining_freeze.primary_protocol,
            *pretest.pretraining_freeze.secondary_protocols,
        )
        if item.sha256 == protocol_sha256
    )
    trace_ids = (
        pretest.test_id_trace_ids if split is SplitLabel.TEST_ID else pretest.test_ood_trace_ids
    )
    artifact_by_trace = {artifact.source.trace_id: artifact for artifact in artifacts}
    records = tuple(
        record
        for trace_id in trace_ids
        for record in _records_for_source(
            artifact=artifact_by_trace[trace_id],
            protocol=protocol,
            predictor_sha256=predictor_sha256,
            prediction_config_sha256=prediction_config_sha256,
            split_manifest_sha256=pretest.pretraining_freeze.split_manifest.sha256,
            git_commit_sha=pretest.git_commit_sha,
            offset=offset,
        )
    )
    return OfficialPredictorSplitForecasts(
        sealed_evaluation_state_sha256=state.sha256,
        pretraining_freeze_sha256=state.pretraining_freeze_sha256,
        pretest_freeze_sha256=pretest.sha256,
        split=split,
        baseline=baseline,
        training_seed=training_seed,
        predictor_artifact_sha256=predictor_sha256,
        prediction_config_sha256=prediction_config_sha256,
        protocol_sha256=protocol.sha256,
        split_manifest_sha256=pretest.pretraining_freeze.split_manifest.sha256,
        execution_git_commit=pretest.git_commit_sha,
        prediction_horizon=pretest.prediction_horizon,
        num_zones=pretest.num_zones,
        zone_schema_sha256=pretest.zone_schema_sha256,
        trace_ids=trace_ids,
        records=records,
    )


@dataclass(frozen=True)
class _Fixture:
    protocol: DatasetProtocolSpec
    pretraining: PreTrainingFreeze
    pretest: PreTestFreeze
    unspent: SealedEvaluationState
    spent: SealedEvaluationState
    baseline_selection: BaselineSelectionResult
    learned_selection: LearnedModelSelectionResult
    test_id_artifacts: tuple[VerifiedPredictionArtifact, ...]
    test_ood_artifacts: tuple[VerifiedPredictionArtifact, ...]
    test_id_baselines: tuple[OfficialPredictorSplitForecasts, ...]
    test_id_learned: tuple[OfficialPredictorSplitForecasts, ...]
    test_ood_baselines: tuple[OfficialPredictorSplitForecasts, ...]
    test_ood_learned: tuple[OfficialPredictorSplitForecasts, ...]


def _make_fixture(tmp_path: Path, *, short_test_trace: bool = False) -> _Fixture:
    protocol = DatasetProtocolSpec(4, 2, _zone_sha256())
    definitions = (
        (
            SplitLabel.TRAIN,
            "train",
            0,
            0,
            [[1, 0], [0, 1], [1, 1], [0, 0], [1, 0]],
            (0.2, 0.3),
        ),
        (
            SplitLabel.VALIDATION,
            "validation",
            1,
            20,
            [[0, 1], [1, 0], [0, 0], [1, 1], [0, 0]],
            (0.2, 0.3),
        ),
        (
            SplitLabel.TEST_ID,
            "test_id_z",
            2,
            100,
            ([[1, 0], [0, 1]] if short_test_trace else [[1, 0], [0, 1], [1, 1], [0, 0]]),
            (0.2, 0.3),
        ),
        (
            SplitLabel.TEST_ID,
            "test_id_a",
            3,
            200,
            [[0, 0], [1, 0], [0, 1], [1, 1], [0, 0]],
            (0.2, 0.3),
        ),
        (
            SplitLabel.TEST_OOD,
            "test_ood_z",
            4,
            300,
            [[2, 0], [0, 1], [0, 0], [1, 1]],
            (0.7, 0.8),
        ),
        (
            SplitLabel.TEST_OOD,
            "test_ood_a",
            5,
            400,
            [[0, 2], [1, 0], [0, 1], [0, 0], [1, 1]],
            (0.9, 1.0),
        ),
    )
    artifacts = tuple(
        _verified_artifact(
            tmp_path,
            trace_id=trace_id,
            seed=seed,
            start_step=start_step,
            counts=counts,
            intensities=intensities,
        )
        for _, trace_id, seed, start_step, counts, intensities in definitions
    )
    manifest = build_split_manifest_from_artifacts(
        tuple(
            (split, artifact)
            for (split, _, _, _, _, _), artifact in zip(definitions, artifacts, strict=True)
        ),
        protocol,
    )
    artifacts_by_trace = {artifact.source.trace_id: artifact for artifact in artifacts}
    validation_source = artifacts_by_trace["validation"].source
    test_id_artifacts = tuple(
        artifacts_by_trace[trace_id] for trace_id in ("test_id_a", "test_id_z")
    )
    test_ood_artifacts = tuple(
        artifacts_by_trace[trace_id] for trace_id in ("test_ood_a", "test_ood_z")
    )
    learned_identity = LearnedConfigFreezeIdentity(
        config_sha256=_sha256("learned-config"),
        protocol_sha256=protocol.sha256,
        objective=PointObjectiveKind.O0,
        transform=HistoryTransformKind.T0,
        model_complexity_key=(8, 32),
        canonical_order=0,
    )
    pretraining = PreTrainingFreeze(
        primary_protocol=protocol,
        secondary_protocols=(),
        split_manifest=manifest,
        calibration_disposition=CalibrationDisposition.EMPTY,
        ood_assignments=(
            TraceOODAssignment("test_id_z", PredictionOODKind.ID, "primary_z"),
            TraceOODAssignment("test_id_a", PredictionOODKind.ID, "primary_a"),
            TraceOODAssignment("test_ood_z", PredictionOODKind.NEAR_OOD, "near_z"),
            TraceOODAssignment(
                "test_ood_a",
                PredictionOODKind.STRUCTURAL_OOD,
                "structural_a",
            ),
        ),
        fixed_training_seeds=(3, 1, 2),
        learned_config_identities=(learned_identity,),
        rng_namespace_plan_sha256=_sha256("rng-plan"),
        training_plan_sha256=_sha256("training-plan"),
        baseline_plan_sha256=_sha256("baseline-plan"),
    )

    validation_values = {
        BaselineKind.B0: 1.0,
        BaselineKind.B1: 2.0,
        BaselineKind.B2: 0.25,
        BaselineKind.B3: 3.0,
        BaselineKind.B4: 4.0,
        BaselineKind.B5: 5.0,
    }
    locked_candidates = tuple(
        BaselineValidationCandidate(
            baseline=baseline,
            protocol=protocol,
            metrics=_validation_metrics(validation_source, validation_values[baseline]),
            alpha=0.5 if baseline is BaselineKind.B3 else None,
        )
        for baseline in _BASELINE_ORDER
    )
    baseline_selection = BaselineSelectionResult(
        locked_variants=locked_candidates,
        selected=locked_candidates[2],
        validation_trace_signature=(
            (
                validation_source.trace_id,
                validation_source.start_step,
                validation_source.num_steps,
            ),
        ),
        prediction_horizon=protocol.prediction_horizon,
        num_zones=validation_source.num_zones,
        zone_schema_sha256=protocol.zone_schema_sha256,
    )
    locked_baselines = tuple(
        LockedBaselineFreezeIdentity(
            baseline=baseline,
            protocol_sha256=protocol.sha256,
            predictor_sha256=_sha256(f"baseline-predictor:{baseline.value}"),
            alpha=0.5 if baseline is BaselineKind.B3 else None,
        )
        for baseline in _BASELINE_ORDER
    )
    predictor_implementation_sha256 = _sha256("predictor-implementation")
    checkpoints = {seed: _sha256(f"checkpoint:{seed}") for seed in pretraining.fixed_training_seeds}
    learned_predictors = tuple(
        LockedLearnedPredictorIdentity(
            seed,
            checkpoints[seed],
            governance_module._learned_predictor_sha256(
                predictor_implementation_sha256=predictor_implementation_sha256,
                config_sha256=learned_identity.config_sha256,
                protocol_sha256=learned_identity.protocol_sha256,
                training_seed=seed,
                checkpoint_digest=checkpoints[seed],
            ),
        )
        for seed in pretraining.fixed_training_seeds
    )
    pretest = PreTestFreeze(
        pretraining_freeze=pretraining,
        locked_baselines=locked_baselines,
        selected_baseline=BaselineKind.B2,
        selected_learned_config_identity=learned_identity,
        learned_predictor_identities=learned_predictors,
        predictor_implementation_sha256=predictor_implementation_sha256,
        metric_implementation_sha256=_sha256("metric-implementation"),
        evaluation_plan_sha256=_sha256("evaluation-plan"),
        bootstrap_spec=PredictionBootstrapSpec(200, 17, "linear"),
        bootstrap_implementation_sha256=_sha256("bootstrap-implementation"),
        official_failure_state_plan_sha256=_sha256("failure-plan"),
        git_commit_sha="a" * 40,
        runtime_provenance_sha256=_sha256("runtime-provenance"),
    )
    validation_metrics = _validation_metrics(validation_source, 0.5)
    seed_results = tuple(
        TrainingSeedValidationResult(seed, checkpoints[seed], validation_metrics, True, None)
        for seed in pretraining.fixed_training_seeds
    )
    learned_candidate = LearnedConfigValidationCandidate(
        config_sha256=learned_identity.config_sha256,
        protocol=protocol,
        objective=learned_identity.objective,
        transform=learned_identity.transform,
        model_complexity_key=learned_identity.model_complexity_key,
        canonical_order=learned_identity.canonical_order,
        seed_results=seed_results,
    )
    learned_selection = LearnedModelSelectionResult(
        selected=learned_candidate,
        valid_candidates=(learned_candidate,),
        failed_candidates=(),
        fixed_training_seeds=pretraining.fixed_training_seeds,
        validation_trace_signature=(
            (
                validation_source.trace_id,
                validation_source.start_step,
                validation_source.num_steps,
            ),
        ),
        prediction_horizon=protocol.prediction_horizon,
        num_zones=validation_source.num_zones,
        zone_schema_sha256=protocol.zone_schema_sha256,
    )
    unspent = build_sealed_evaluation_state((pretest,))
    spent = record_first_official_test_execution(
        unspent,
        FirstOfficialTestExecution(
            pretest.sha256,
            SplitLabel.TEST_ID,
            OfficialTestExecutionKind.METRIC_COMPUTATION,
        ),
    )
    baseline_offsets = {
        BaselineKind.B0: 0.0,
        BaselineKind.B1: 1.0,
        BaselineKind.B2: 3.0,
        BaselineKind.B3: 2.0,
        BaselineKind.B4: 4.0,
        BaselineKind.B5: 5.0,
    }
    test_id_baselines = tuple(
        _bundle(
            state=spent,
            pretest=pretest,
            artifacts=test_id_artifacts,
            split=SplitLabel.TEST_ID,
            baseline=baseline,
            training_seed=None,
            offset=baseline_offsets[baseline],
        )
        for baseline in _BASELINE_ORDER
    )
    test_ood_baselines = tuple(
        _bundle(
            state=spent,
            pretest=pretest,
            artifacts=test_ood_artifacts,
            split=SplitLabel.TEST_OOD,
            baseline=baseline,
            training_seed=None,
            offset=baseline_offsets[baseline] + 0.25,
        )
        for baseline in _BASELINE_ORDER
    )
    test_id_learned = tuple(
        _bundle(
            state=spent,
            pretest=pretest,
            artifacts=test_id_artifacts,
            split=SplitLabel.TEST_ID,
            baseline=None,
            training_seed=seed,
            offset=float(seed),
        )
        for seed in pretraining.fixed_training_seeds
    )
    test_ood_learned = tuple(
        _bundle(
            state=spent,
            pretest=pretest,
            artifacts=test_ood_artifacts,
            split=SplitLabel.TEST_OOD,
            baseline=None,
            training_seed=seed,
            offset=float(seed) + 0.25,
        )
        for seed in pretraining.fixed_training_seeds
    )
    return _Fixture(
        protocol,
        pretraining,
        pretest,
        unspent,
        spent,
        baseline_selection,
        learned_selection,
        test_id_artifacts,
        test_ood_artifacts,
        test_id_baselines,
        test_id_learned,
        test_ood_baselines,
        test_ood_learned,
    )


@pytest.fixture
def fixture(tmp_path: Path) -> _Fixture:
    return _make_fixture(tmp_path)


def _evaluate(
    fixture: _Fixture,
    *,
    state: object = _MISSING,
    pretest: object = _MISSING,
    baseline_selection: object = _MISSING,
    learned_selection: object = _MISSING,
    test_id_artifacts: object = _MISSING,
    test_ood_artifacts: object = _MISSING,
    test_id_baselines: object = _MISSING,
    test_id_learned: object = _MISSING,
    test_ood_baselines: object = _MISSING,
    test_ood_learned: object = _MISSING,
) -> OfficialSealedPointMetrics:
    return evaluate_official_sealed_point_metrics(
        state=fixture.spent if state is _MISSING else state,  # type: ignore[arg-type]
        pretest_freeze=(
            fixture.pretest if pretest is _MISSING else pretest  # type: ignore[arg-type]
        ),
        baseline_selection=(
            fixture.baseline_selection if baseline_selection is _MISSING else baseline_selection
        ),  # type: ignore[arg-type]
        learned_selection=(
            fixture.learned_selection if learned_selection is _MISSING else learned_selection
        ),  # type: ignore[arg-type]
        test_id_artifacts=(
            fixture.test_id_artifacts if test_id_artifacts is _MISSING else test_id_artifacts
        ),  # type: ignore[arg-type]
        test_ood_artifacts=(
            fixture.test_ood_artifacts if test_ood_artifacts is _MISSING else test_ood_artifacts
        ),  # type: ignore[arg-type]
        test_id_baselines=(
            fixture.test_id_baselines if test_id_baselines is _MISSING else test_id_baselines
        ),  # type: ignore[arg-type]
        test_id_learned=(
            fixture.test_id_learned if test_id_learned is _MISSING else test_id_learned
        ),  # type: ignore[arg-type]
        test_ood_baselines=(
            fixture.test_ood_baselines if test_ood_baselines is _MISSING else test_ood_baselines  # type: ignore[arg-type]
        ),
        test_ood_learned=(
            fixture.test_ood_learned if test_ood_learned is _MISSING else test_ood_learned  # type: ignore[arg-type]
        ),
    )


def _forge(value: object, **changes: object) -> object:
    forged = replace(value)  # type: ignore[type-var]
    for name, replacement in changes.items():
        object.__setattr__(forged, name, replacement)
    return forged


def _replace_group_item(
    group: tuple[OfficialPredictorSplitForecasts, ...],
    index: int,
    replacement: OfficialPredictorSplitForecasts,
) -> tuple[OfficialPredictorSplitForecasts, ...]:
    changed = list(group)
    changed[index] = replacement
    return tuple(changed)


def _replace_first_record(
    bundle: OfficialPredictorSplitForecasts,
    *,
    sample: PredictionSample | None = None,
    forecast: DemandForecast | None = None,
    provenance: ForecastProvenance | None = None,
) -> OfficialPredictorSplitForecasts:
    """以 direct constructors 替换首条 record，同时保持 bundle 结构合法。"""

    original = bundle.records[0]
    point_record = PointForecastRecord(
        trace_id=original.point_record.trace_id,
        trace_start_step=original.point_record.trace_start_step,
        trace_num_steps=original.point_record.trace_num_steps,
        sample=original.point_record.sample if sample is None else sample,
        forecast=original.point_record.forecast if forecast is None else forecast,
    )
    replacement = OfficialPointForecastRecord(
        point_record,
        original.provenance if provenance is None else provenance,
    )
    return replace(bundle, records=(replacement, *bundle.records[1:]))


def _forge_verified_source(
    verified: VerifiedPredictionArtifact,
    source: PredictionSource,
) -> VerifiedPredictionArtifact:
    forged = object.__new__(VerifiedPredictionArtifact)
    object.__setattr__(forged, "artifact", verified.artifact)
    object.__setattr__(forged, "source", source)
    return forged


def test_success_evaluates_all_bundles_and_preserves_validation_locked_bstar(
    fixture: _Fixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = official_metrics_module.evaluate_point_forecasts
    original_derive = official_metrics_module.derive_prediction_samples_from_artifact
    calls = 0
    derive_calls: list[tuple[str, str]] = []

    def counted(records: object) -> PointMetricSummary:
        nonlocal calls
        calls += 1
        return original(records)  # type: ignore[arg-type]

    def counted_derive(
        artifact: VerifiedPredictionArtifact,
        protocol: DatasetProtocolSpec,
    ) -> tuple[PredictionSample, ...]:
        derive_calls.append((artifact.source.trace_id, protocol.sha256))
        return original_derive(artifact, protocol)

    monkeypatch.setattr(official_metrics_module, "evaluate_point_forecasts", counted)
    monkeypatch.setattr(
        official_metrics_module,
        "derive_prediction_samples_from_artifact",
        counted_derive,
    )
    result = _evaluate(
        fixture,
        test_id_artifacts=tuple(reversed(fixture.test_id_artifacts)),
        test_ood_artifacts=tuple(reversed(fixture.test_ood_artifacts)),
        test_id_baselines=tuple(reversed(fixture.test_id_baselines)),
        test_id_learned=tuple(reversed(fixture.test_id_learned)),
        test_ood_baselines=tuple(reversed(fixture.test_ood_baselines)),
        test_ood_learned=tuple(reversed(fixture.test_ood_learned)),
    )

    assert calls == 2 * (6 + len(fixture.pretraining.fixed_training_seeds))
    assert len(derive_calls) == 4
    assert len(set(derive_calls)) == 4
    assert tuple(item.forecasts.baseline for item in result.test_id_baselines) == _BASELINE_ORDER
    assert tuple(item.forecasts.baseline for item in result.test_ood_baselines) == _BASELINE_ORDER
    assert tuple(item.forecasts.training_seed for item in result.test_id_learned) == (1, 2, 3)
    assert tuple(item.forecasts.training_seed for item in result.test_ood_learned) == (1, 2, 3)
    assert len(result.test_id_baselines) == len(result.test_ood_baselines) == 6
    assert result.baseline_selection.selected_kind is BaselineKind.B2
    assert result.test_id_baselines[0].metrics.primary_rmse == 0.0
    assert result.selected_baseline_test_id.forecasts.baseline is BaselineKind.B2
    assert result.selected_baseline_test_id.metrics.primary_rmse > 0.0
    for item in (*result.test_id_baselines, *result.test_ood_learned):
        assert item.metrics.mse_by_horizon_zone.shape == (2, 2)
        assert item.metrics.mae_by_horizon_zone.shape == (2, 2)
        assert item.metrics.bias_by_horizon_zone.shape == (2, 2)
        assert set(metric.trace_id for metric in item.metrics.trace_metrics) == set(
            item.forecasts.trace_ids
        )


def test_unspent_rejected_before_bundle_or_metric_access(
    fixture: _Fixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metric_calls = 0
    bundle_iterations = 0
    artifact_iterations = 0

    def forbidden_metric(records: object) -> PointMetricSummary:
        nonlocal metric_calls
        metric_calls += 1
        raise AssertionError("metric computation must not run")

    def forbidden_bundles() -> object:
        nonlocal bundle_iterations
        bundle_iterations += 1
        raise AssertionError("bundles must not be materialized")
        yield object()

    def forbidden_artifacts() -> object:
        nonlocal artifact_iterations
        artifact_iterations += 1
        raise AssertionError("artifacts must not be materialized")
        yield object()

    monkeypatch.setattr(
        official_metrics_module,
        "evaluate_point_forecasts",
        forbidden_metric,
    )
    monkeypatch.setattr(
        official_metrics_module,
        "validate_prediction_source_for_artifact",
        lambda *args: pytest.fail("artifact source must not be read"),
    )
    monkeypatch.setattr(
        official_metrics_module,
        "derive_prediction_samples_from_artifact",
        lambda *args: pytest.fail("artifact samples must not be derived"),
    )
    with pytest.raises(ValueError, match="already-SPENT"):
        _evaluate(
            fixture,
            state=fixture.unspent,
            baseline_selection=object(),
            learned_selection=object(),
            test_id_artifacts=forbidden_artifacts(),
            test_ood_artifacts=forbidden_artifacts(),
            test_id_baselines=forbidden_bundles(),
            test_id_learned=forbidden_bundles(),
            test_ood_baselines=forbidden_bundles(),
            test_ood_learned=forbidden_bundles(),
        )
    assert metric_calls == 0
    assert bundle_iterations == 0
    assert artifact_iterations == 0


def test_missing_first_exposure_rejected_before_metrics(
    fixture: _Fixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forged = replace(fixture.unspent)
    object.__setattr__(forged, "disposition", Disposition.SPENT)
    monkeypatch.setattr(
        official_metrics_module,
        "evaluate_point_forecasts",
        lambda records: pytest.fail("metric computation must not run"),
    )
    artifact_iterations = 0

    def forbidden_artifacts() -> object:
        nonlocal artifact_iterations
        artifact_iterations += 1
        raise AssertionError("artifacts must not be materialized")
        yield object()

    with pytest.raises(ValueError, match="first official execution"):
        _evaluate(
            fixture,
            state=forged,
            test_id_artifacts=forbidden_artifacts(),
            test_ood_artifacts=forbidden_artifacts(),
        )
    assert artifact_iterations == 0


@pytest.mark.parametrize(
    "failure_kind",
    ["missing", "extra", "duplicate", "wrong_split", "wrong_type"],
)
def test_exact_verified_artifact_coverage_rejected_before_metrics(
    fixture: _Fixture,
    monkeypatch: pytest.MonkeyPatch,
    failure_kind: str,
) -> None:
    calls = 0

    def counted(records: object) -> PointMetricSummary:
        nonlocal calls
        calls += 1
        raise AssertionError("metric computation must not run")

    monkeypatch.setattr(official_metrics_module, "evaluate_point_forecasts", counted)
    artifacts: object
    if failure_kind == "missing":
        artifacts = fixture.test_id_artifacts[:-1]
    elif failure_kind == "extra":
        artifacts = (*fixture.test_id_artifacts, fixture.test_ood_artifacts[0])
    elif failure_kind == "duplicate":
        artifacts = (fixture.test_id_artifacts[0], fixture.test_id_artifacts[0])
    elif failure_kind == "wrong_split":
        artifacts = fixture.test_ood_artifacts
    else:
        artifacts = (object(),)

    with pytest.raises((TypeError, ValueError), match="artifact|trace|frozen"):
        _evaluate(fixture, test_id_artifacts=artifacts)
    assert calls == 0


def test_verified_artifact_is_rebound_to_exact_manifest_source_before_metrics(
    fixture: _Fixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = fixture.test_id_artifacts[0]
    forged_source = replace(original.source, seed=999)
    forged_artifact = _forge_verified_source(original, forged_source)
    artifacts = (forged_artifact, *fixture.test_id_artifacts[1:])
    monkeypatch.setattr(
        official_metrics_module,
        "evaluate_point_forecasts",
        lambda records: pytest.fail("metric computation must not run"),
    )

    with pytest.raises(ValueError, match="PredictionSource|artifact"):
        _evaluate(fixture, test_id_artifacts=artifacts)


@pytest.mark.parametrize("fabrication", ["target_counts", "target_mask", "history", "sample_id"])
def test_direct_bundle_fabricated_authoritative_sample_rejected_before_metrics(
    fixture: _Fixture,
    monkeypatch: pytest.MonkeyPatch,
    fabrication: str,
) -> None:
    bundle = fixture.test_id_baselines[0]
    original = bundle.records[0]
    sample = original.point_record.sample
    forecast = original.point_record.forecast
    provenance = original.provenance
    requires_frozen_invariant_bypass = False

    if fabrication == "target_counts":
        counts = sample.target.counts.copy()
        counts[0, 0] += 7
        fabricated_sample = PredictionSample(
            sample.sample_id,
            sample.context,
            PredictionTarget(counts, sample.target.valid_mask),
        )
    elif fabrication == "target_mask":
        valid_mask = sample.target.valid_mask.copy()
        valid_mask[-1] = False
        counts = sample.target.counts.copy()
        counts[-1] = 0
        fabricated_sample = PredictionSample(
            sample.sample_id,
            sample.context,
            PredictionTarget(counts, valid_mask),
        )
        requires_frozen_invariant_bypass = True
    elif fabrication == "history":
        history_counts = sample.context.history_counts.copy()
        history_counts[-1, 0] += 9
        fabricated_context = replace(sample.context, history_counts=history_counts)
        fabricated_sample = PredictionSample(sample.sample_id, fabricated_context, sample.target)
    else:
        fabricated_sample = PredictionSample("b" * 64, sample.context, sample.target)
        provenance = replace(provenance, sample_id=fabricated_sample.sample_id)

    if requires_frozen_invariant_bypass:
        forged_point_record = _forge(original.point_record, sample=fabricated_sample)
        forged_record = OfficialPointForecastRecord(
            forged_point_record,  # type: ignore[arg-type]
            provenance,
        )
        forged_bundle = replace(bundle, records=(forged_record, *bundle.records[1:]))
    else:
        forged_bundle = _replace_first_record(
            bundle,
            sample=fabricated_sample,
            forecast=forecast,
            provenance=provenance,
        )
    group = _replace_group_item(fixture.test_id_baselines, 0, forged_bundle)
    calls = 0

    def counted(records: object) -> PointMetricSummary:
        nonlocal calls
        calls += 1
        raise AssertionError("metric computation must not run")

    monkeypatch.setattr(official_metrics_module, "evaluate_point_forecasts", counted)
    with pytest.raises(ValueError, match="authoritative"):
        _evaluate(fixture, test_id_baselines=group)
    assert calls == 0


@pytest.mark.parametrize(
    "bypass_kind",
    ["normalization", "inference_rng", "variance", "quantiles", "scenarios"],
)
def test_direct_bundle_factory_only_surface_bypass_rejected_before_metrics(
    fixture: _Fixture,
    monkeypatch: pytest.MonkeyPatch,
    bypass_kind: str,
) -> None:
    bundle = fixture.test_id_baselines[0]
    original = bundle.records[0]
    forecast = original.point_record.forecast
    provenance = original.provenance
    if bypass_kind == "normalization":
        provenance = replace(provenance, normalization_sha256="b" * 64)
    elif bypass_kind == "inference_rng":
        provenance = replace(provenance, inference_rng_id="forged-rng")
    elif bypass_kind == "variance":
        forecast = replace(forecast, variance=np.zeros_like(forecast.mean))
    elif bypass_kind == "quantiles":
        forecast = replace(
            forecast,
            quantile_levels=np.asarray([0.5]),
            quantiles=forecast.mean[np.newaxis, ...],
        )
    else:
        forecast = replace(
            forecast,
            scenarios=original.point_record.sample.target.counts[np.newaxis, ...],
        )
    forged_bundle = _replace_first_record(
        bundle,
        forecast=forecast,
        provenance=provenance,
    )
    group = _replace_group_item(fixture.test_id_baselines, 0, forged_bundle)
    calls = 0

    def counted(records: object) -> PointMetricSummary:
        nonlocal calls
        calls += 1
        raise AssertionError("metric computation must not run")

    monkeypatch.setattr(official_metrics_module, "evaluate_point_forecasts", counted)
    with pytest.raises(ValueError, match="normalization|inference_rng|probabilistic"):
        _evaluate(fixture, test_id_baselines=group)
    assert calls == 0


@pytest.mark.parametrize(
    ("pretest_changes", "message"),
    [
        ({"pretraining_freeze_sha256": "b" * 64}, "Layer-A"),
        ({"test_id_trace_ids": ("wrong_id",)}, "TEST_ID"),
        ({"test_ood_trace_ids": ("wrong_ood",)}, "TEST_OOD"),
    ],
)
def test_state_pretest_exact_rebind_rejects_mismatch_before_metrics(
    fixture: _Fixture,
    monkeypatch: pytest.MonkeyPatch,
    pretest_changes: dict[str, object],
    message: str,
) -> None:
    forged = _forge(fixture.pretest, **pretest_changes)
    monkeypatch.setattr(
        official_metrics_module,
        "evaluate_point_forecasts",
        lambda records: pytest.fail("metric computation must not run"),
    )

    with pytest.raises(ValueError, match=message):
        _evaluate(fixture, pretest=forged)


def test_unregistered_pretest_rejected_before_metrics(
    fixture: _Fixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unregistered = replace(
        fixture.pretest,
        evaluation_plan_sha256=_sha256("other-evaluation-plan"),
    )
    monkeypatch.setattr(
        official_metrics_module,
        "evaluate_point_forecasts",
        lambda records: pytest.fail("metric computation must not run"),
    )

    with pytest.raises(ValueError, match="registered"):
        _evaluate(fixture, pretest=unregistered)


def test_baseline_selection_selected_bstar_mismatch_rejected(fixture: _Fixture) -> None:
    forged = _forge(
        fixture.baseline_selection,
        selected=fixture.baseline_selection.locked_variants[0],
    )

    with pytest.raises(ValueError, match=r"B\*"):
        _evaluate(fixture, baseline_selection=forged)


@pytest.mark.parametrize("mismatch", ["protocol", "alpha"])
def test_baseline_locked_identity_mismatch_rejected(
    fixture: _Fixture,
    mismatch: str,
) -> None:
    candidates = list(fixture.baseline_selection.locked_variants)
    index = 3 if mismatch == "alpha" else 0
    candidate = candidates[index]
    if mismatch == "protocol":
        other_protocol = DatasetProtocolSpec(8, 2, fixture.protocol.zone_schema_sha256)
        replacement = BaselineValidationCandidate(
            candidate.baseline,
            other_protocol,
            candidate.metrics,
            candidate.alpha,
        )
    else:
        replacement = BaselineValidationCandidate(
            candidate.baseline,
            candidate.protocol,
            candidate.metrics,
            0.25,
        )
    candidates[index] = replacement
    forged = _forge(fixture.baseline_selection, locked_variants=tuple(candidates))

    with pytest.raises(ValueError, match="protocol|alpha"):
        _evaluate(fixture, baseline_selection=forged)


@pytest.mark.parametrize(
    ("field_name", "replacement", "message"),
    [
        ("validation_trace_signature", (("wrong", 0, 4),), "validation trace"),
        ("prediction_horizon", 3, "prediction_horizon"),
        ("num_zones", 3, "num_zones"),
        ("zone_schema_sha256", "b" * 64, "zone schema"),
    ],
)
def test_baseline_selection_geometry_and_validation_signature_rebind(
    fixture: _Fixture,
    field_name: str,
    replacement: object,
    message: str,
) -> None:
    forged = _forge(fixture.baseline_selection, **{field_name: replacement})

    with pytest.raises(ValueError, match=message):
        _evaluate(fixture, baseline_selection=forged)


@pytest.mark.parametrize(
    ("field_name", "replacement", "message"),
    [
        ("config_sha256", "b" * 64, "config_sha256"),
        ("objective", PointObjectiveKind.O1, "objective"),
        ("transform", HistoryTransformKind.T1, "transform"),
        ("model_complexity_key", (99,), "model_complexity_key"),
        ("canonical_order", 7, "canonical_order"),
    ],
)
def test_learned_selected_identity_field_mismatch_rejected(
    fixture: _Fixture,
    field_name: str,
    replacement: object,
    message: str,
) -> None:
    selected = _forge(fixture.learned_selection.selected, **{field_name: replacement})
    learned = _forge(
        fixture.learned_selection,
        selected=selected,
        valid_candidates=(selected,),
    )

    with pytest.raises(ValueError, match=message):
        _evaluate(fixture, learned_selection=learned)


def test_learned_selected_protocol_mismatch_rejected(fixture: _Fixture) -> None:
    other_protocol = DatasetProtocolSpec(8, 2, fixture.protocol.zone_schema_sha256)
    selected = _forge(fixture.learned_selection.selected, protocol=other_protocol)
    learned = _forge(
        fixture.learned_selection,
        selected=selected,
        valid_candidates=(selected,),
    )

    with pytest.raises(ValueError, match="protocol_sha256"):
        _evaluate(fixture, learned_selection=learned)


@pytest.mark.parametrize(
    ("field_name", "replacement", "message"),
    [
        ("fixed_training_seeds", (1, 2, 99), "fixed training seeds"),
        ("validation_trace_signature", (("wrong", 0, 4),), "validation trace"),
        ("prediction_horizon", 3, "prediction_horizon"),
        ("num_zones", 3, "num_zones"),
        ("zone_schema_sha256", "b" * 64, "zone schema"),
    ],
)
def test_learned_selection_batch_rebind_rejects_mismatch(
    fixture: _Fixture,
    field_name: str,
    replacement: object,
    message: str,
) -> None:
    forged = _forge(fixture.learned_selection, **{field_name: replacement})

    with pytest.raises(ValueError, match=message):
        _evaluate(fixture, learned_selection=forged)


def test_learned_checkpoint_mismatch_rejected(fixture: _Fixture) -> None:
    results = list(fixture.learned_selection.selected.seed_results)
    results[0] = _forge(results[0], checkpoint_sha256="b" * 64)  # type: ignore[assignment]
    selected = _forge(fixture.learned_selection.selected, seed_results=tuple(results))
    learned = _forge(
        fixture.learned_selection,
        selected=selected,
        valid_candidates=(selected,),
    )

    with pytest.raises(ValueError, match="checkpoint"):
        _evaluate(fixture, learned_selection=learned)


def test_failed_selected_seed_rejected(fixture: _Fixture) -> None:
    results = list(fixture.learned_selection.selected.seed_results)
    failed = TrainingSeedValidationResult(results[0].training_seed, None, None, False, "failed")
    results[0] = failed
    selected = _forge(fixture.learned_selection.selected, seed_results=tuple(results))
    learned = _forge(
        fixture.learned_selection,
        selected=selected,
        valid_candidates=(selected,),
    )

    with pytest.raises(ValueError, match="VALID|successful"):
        _evaluate(fixture, learned_selection=learned)


@pytest.mark.parametrize("split_name", ["test_id_baselines", "test_ood_baselines"])
def test_baseline_bundle_missing_extra_and_duplicate_rejected(
    fixture: _Fixture,
    split_name: str,
) -> None:
    bundles = getattr(fixture, split_name)

    with pytest.raises(ValueError, match="6 个"):
        _evaluate(fixture, **{split_name: bundles[:-1]})
    with pytest.raises(ValueError, match="6 个"):
        _evaluate(fixture, **{split_name: (*bundles, bundles[0])})
    with pytest.raises(ValueError, match="重复"):
        _evaluate(fixture, **{split_name: (*bundles[:-1], bundles[0])})


@pytest.mark.parametrize("split_name", ["test_id_learned", "test_ood_learned"])
def test_learned_bundle_missing_extra_and_duplicate_rejected(
    fixture: _Fixture,
    split_name: str,
) -> None:
    bundles = getattr(fixture, split_name)
    extra = _forge(bundles[0], training_seed=99)

    with pytest.raises(ValueError, match="frozen training seeds"):
        _evaluate(fixture, **{split_name: bundles[:-1]})
    with pytest.raises(ValueError, match="frozen training seeds"):
        _evaluate(fixture, **{split_name: (*bundles, extra)})
    with pytest.raises(ValueError, match="重复"):
        _evaluate(fixture, **{split_name: (*bundles[:-1], bundles[0])})


@pytest.mark.parametrize(
    ("field_name", "replacement", "message"),
    [
        ("split", SplitLabel.TEST_OOD, "split"),
        ("sealed_evaluation_state_sha256", "b" * 64, "sealed state"),
        ("pretraining_freeze_sha256", "b" * 64, "Layer-A"),
        ("pretest_freeze_sha256", "b" * 64, "PreTestFreeze"),
        ("trace_ids", ("wrong",), "trace tuple"),
        ("prediction_horizon", 3, "prediction_horizon"),
        ("num_zones", 3, "num_zones"),
        ("zone_schema_sha256", "b" * 64, "zone schema"),
        ("split_manifest_sha256", "b" * 64, "manifest"),
        ("execution_git_commit", "b" * 40, "Git commit"),
    ],
)
def test_common_bundle_provenance_mismatch_rejected_before_metrics(
    fixture: _Fixture,
    monkeypatch: pytest.MonkeyPatch,
    field_name: str,
    replacement: object,
    message: str,
) -> None:
    forged = _forge(fixture.test_id_baselines[0], **{field_name: replacement})
    group = _replace_group_item(fixture.test_id_baselines, 0, forged)  # type: ignore[arg-type]
    calls = 0

    def counted(records: object) -> PointMetricSummary:
        nonlocal calls
        calls += 1
        raise AssertionError("metric computation must not run")

    monkeypatch.setattr(official_metrics_module, "evaluate_point_forecasts", counted)
    with pytest.raises(ValueError, match=message):
        _evaluate(fixture, test_id_baselines=group)
    assert calls == 0


@pytest.mark.parametrize(
    ("field_name", "replacement", "message"),
    [
        ("predictor_artifact_sha256", "b" * 64, "predictor"),
        ("prediction_config_sha256", "b" * 64, "prediction config"),
        ("protocol_sha256", "b" * 64, "protocol"),
    ],
)
def test_baseline_bundle_locked_identity_mismatch_rejected(
    fixture: _Fixture,
    field_name: str,
    replacement: object,
    message: str,
) -> None:
    forged = _forge(fixture.test_id_baselines[0], **{field_name: replacement})
    group = _replace_group_item(fixture.test_id_baselines, 0, forged)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match=message):
        _evaluate(fixture, test_id_baselines=group)


@pytest.mark.parametrize(
    ("field_name", "replacement", "message"),
    [
        ("predictor_artifact_sha256", "b" * 64, "predictor"),
        ("prediction_config_sha256", "b" * 64, "prediction config"),
        ("protocol_sha256", "b" * 64, "protocol"),
    ],
)
def test_learned_bundle_locked_identity_mismatch_rejected(
    fixture: _Fixture,
    field_name: str,
    replacement: object,
    message: str,
) -> None:
    forged = _forge(fixture.test_id_learned[0], **{field_name: replacement})
    group = _replace_group_item(fixture.test_id_learned, 0, forged)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match=message):
        _evaluate(fixture, test_id_learned=group)


@pytest.mark.parametrize(
    ("group_name", "field_name"),
    [
        ("baseline", "predictor_artifact_sha256"),
        ("baseline", "prediction_config_sha256"),
        ("baseline", "protocol_sha256"),
        ("learned", "predictor_artifact_sha256"),
        ("learned", "prediction_config_sha256"),
        ("learned", "protocol_sha256"),
    ],
)
def test_explicit_id_ood_same_predictor_parity_guard(
    fixture: _Fixture,
    group_name: str,
    field_name: str,
) -> None:
    if group_name == "baseline":
        test_id = fixture.test_id_baselines
        test_ood = fixture.test_ood_baselines
    else:
        test_id = fixture.test_id_learned
        test_ood = fixture.test_ood_learned
    forged = _forge(test_ood[0], **{field_name: "b" * 64})
    changed = _replace_group_item(test_ood, 0, forged)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="same|同一"):
        official_metrics_module._validate_same_predictors_across_splits(
            test_id,
            changed,
            group_name,
        )


@pytest.mark.parametrize("failure_kind", ["missing_b5", "missing_seed", "wrong_selection"])
def test_structural_failure_has_zero_metric_calls(
    fixture: _Fixture,
    monkeypatch: pytest.MonkeyPatch,
    failure_kind: str,
) -> None:
    calls = 0

    def counted(records: object) -> PointMetricSummary:
        nonlocal calls
        calls += 1
        raise AssertionError("metric computation must not run")

    monkeypatch.setattr(official_metrics_module, "evaluate_point_forecasts", counted)
    kwargs: dict[str, object]
    if failure_kind == "missing_b5":
        kwargs = {"test_id_baselines": fixture.test_id_baselines[:-1]}
    elif failure_kind == "missing_seed":
        kwargs = {"test_ood_learned": fixture.test_ood_learned[:-1]}
    else:
        kwargs = {
            "baseline_selection": _forge(
                fixture.baseline_selection,
                selected=fixture.baseline_selection.locked_variants[0],
            )
        }
    with pytest.raises(ValueError):
        _evaluate(fixture, **kwargs)
    assert calls == 0


def test_missing_anchor_and_zero_record_trace_fail_before_metrics(
    fixture: _Fixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = fixture.test_id_baselines[0]
    first_trace = bundle.trace_ids[0]
    without_one_anchor = replace(bundle, records=bundle.records[1:])
    without_first_trace = replace(
        bundle,
        records=tuple(
            record for record in bundle.records if record.point_record.trace_id != first_trace
        ),
    )
    monkeypatch.setattr(
        official_metrics_module,
        "evaluate_point_forecasts",
        lambda records: pytest.fail("metric computation must not run"),
    )

    for changed in (without_one_anchor, without_first_trace):
        group = _replace_group_item(fixture.test_id_baselines, 0, changed)
        with pytest.raises(ValueError, match="anchors|records"):
            _evaluate(fixture, test_id_baselines=group)


def test_too_short_trace_fails_before_metrics(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixture = _make_fixture(tmp_path, short_test_trace=True)
    calls = 0

    def counted(records: object) -> PointMetricSummary:
        nonlocal calls
        calls += 1
        raise AssertionError("metric computation must not run")

    monkeypatch.setattr(official_metrics_module, "evaluate_point_forecasts", counted)
    with pytest.raises(ValueError, match="num_steps"):
        _evaluate(fixture)
    assert calls == 0


def test_metric_trace_coverage_is_rechecked_after_accepted_metric_call(
    fixture: _Fixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    incomplete = fixture.baseline_selection.locked_variants[0].metrics
    calls = 0

    def incomplete_metric(records: object) -> PointMetricSummary:
        nonlocal calls
        calls += 1
        return incomplete

    monkeypatch.setattr(
        official_metrics_module,
        "evaluate_point_forecasts",
        incomplete_metric,
    )
    with pytest.raises(ValueError, match="trace"):
        _evaluate(fixture)
    assert calls == 1


def test_official_predictor_split_metrics_rejects_wrong_types_and_geometry(
    fixture: _Fixture,
) -> None:
    bundle = fixture.test_id_baselines[0]
    valid = official_metrics_module._evaluate_official_predictor_split_metrics(bundle)

    with pytest.raises(TypeError, match="forecasts"):
        OfficialPredictorSplitMetrics(object(), valid.metrics)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="metrics"):
        OfficialPredictorSplitMetrics(bundle, object())  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="trace"):
        OfficialPredictorSplitMetrics(
            bundle,
            fixture.baseline_selection.locked_variants[0].metrics,
        )


def test_result_is_frozen_slotted_complete_and_not_success(fixture: _Fixture) -> None:
    result = _evaluate(fixture)

    assert not hasattr(result, "__dict__")
    assert not hasattr(result.test_id_baselines[0], "__dict__")
    assert tuple(item.name for item in fields(result)) == (
        "sealed_evaluation_state_sha256",
        "pretraining_freeze_sha256",
        "pretest_freeze_sha256",
        "baseline_selection",
        "learned_selection",
        "test_id_baselines",
        "test_id_learned",
        "test_ood_baselines",
        "test_ood_learned",
    )
    for forbidden in (
        "status",
        "success",
        "schema",
        "version",
        "sha256",
        "timestamp",
        "nonce",
        "artifact_path",
        "delta_rmse",
        "ci_lower",
        "ci_upper",
        "label",
    ):
        assert not hasattr(result, forbidden)
    assert result.sealed_evaluation_state_sha256 == fixture.spent.sha256
    assert result.pretraining_freeze_sha256 == fixture.pretraining.sha256
    assert result.pretest_freeze_sha256 == fixture.pretest.sha256
    with pytest.raises(FrozenInstanceError):
        result.pretest_freeze_sha256 = "b" * 64  # type: ignore[misc]


def test_state_pretest_selections_and_bundles_are_not_mutated(fixture: _Fixture) -> None:
    state_before = (
        fixture.spent.sha256,
        fixture.spent.disposition,
        fixture.spent.first_official_test_execution,
        fixture.spent.registered_pretest_freeze_sha256s,
        fixture.spent.test_id_trace_ids,
        fixture.spent.test_ood_trace_ids,
    )
    pretest_before = governance_module._pretest_freeze_identity(fixture.pretest)
    selection_before = (
        fixture.baseline_selection.locked_variants,
        fixture.baseline_selection.selected,
        fixture.learned_selection.selected,
        fixture.learned_selection.fixed_training_seeds,
    )
    bundles_before = (
        fixture.test_id_baselines,
        fixture.test_id_learned,
        fixture.test_ood_baselines,
        fixture.test_ood_learned,
    )

    _evaluate(fixture)

    assert state_before == (
        fixture.spent.sha256,
        fixture.spent.disposition,
        fixture.spent.first_official_test_execution,
        fixture.spent.registered_pretest_freeze_sha256s,
        fixture.spent.test_id_trace_ids,
        fixture.spent.test_ood_trace_ids,
    )
    assert pretest_before == governance_module._pretest_freeze_identity(fixture.pretest)
    assert selection_before == (
        fixture.baseline_selection.locked_variants,
        fixture.baseline_selection.selected,
        fixture.learned_selection.selected,
        fixture.learned_selection.fixed_training_seeds,
    )
    assert bundles_before == (
        fixture.test_id_baselines,
        fixture.test_id_learned,
        fixture.test_ood_baselines,
        fixture.test_ood_learned,
    )


def test_public_exports_and_keyword_only_factory() -> None:
    expected = {
        "OfficialPredictorSplitMetrics": OfficialPredictorSplitMetrics,
        "OfficialSealedPointMetrics": OfficialSealedPointMetrics,
        "evaluate_official_sealed_point_metrics": evaluate_official_sealed_point_metrics,
    }
    for name, value in expected.items():
        assert getattr(prediction_module, name) is value
        assert name in prediction_module.__all__
    assert official_metrics_module.__all__ == list(expected)
    signature = inspect.signature(evaluate_official_sealed_point_metrics)
    assert tuple(signature.parameters) == (
        "state",
        "pretest_freeze",
        "baseline_selection",
        "learned_selection",
        "test_id_artifacts",
        "test_ood_artifacts",
        "test_id_baselines",
        "test_id_learned",
        "test_ood_baselines",
        "test_ood_learned",
    )
    assert all(
        parameter.kind is inspect.Parameter.KEYWORD_ONLY
        for parameter in signature.parameters.values()
    )


def test_production_isolation_and_mandatory_breakdown_boundary() -> None:
    source = inspect.getsource(official_metrics_module)
    forbidden = (
        "TrainingSeedTestResult",
        "LockedTestPointEstimate",
        "compute_locked_test_point_estimate",
        "PairedTraceBootstrapResult",
        "bootstrap_locked_test_delta_rmse",
        "PrimaryIDInterpretation",
        "interpret_primary_id_bootstrap",
        "record_prediction_evaluation_failure(",
        "record_first_official_test_execution(",
        ".predict(",
        "np.random",
        "numpy.random",
        "default_rng",
        "PCG64",
        "random.Random",
        "torch",
        "subprocess",
        "GitPython",
        "open(",
        "write_text(",
        "write_bytes(",
        "json.dump",
        "yaml",
        "np.save",
        "timestamp",
        "nonce",
        "artifact_path",
        "PredictionEvaluationSuccess",
        "OfficialEvaluationSuccess",
        "FinalPredictionResult",
    )
    assert all(token not in source for token in forbidden)
    assert "derive_synthetic_prediction_samples" not in source
    assert source.count("derive_prediction_samples_from_artifact(") == 1
    assert "validate_prediction_source_for_artifact(" in source
    assert "np.array_equal" in source
    assert source.count("evaluate_point_forecasts(") == 1
    docstring = inspect.getdoc(OfficialSealedPointMetrics)
    assert docstring is not None
    for boundary in ("target-zero/nonzero", "condition", "near-OOD", "structural-OOD"):
        assert boundary in docstring
    assert "scientific success" in docstring
