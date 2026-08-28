from __future__ import annotations

import hashlib
import inspect
from dataclasses import FrozenInstanceError, dataclass, fields, replace
from pathlib import Path

import numpy as np
import pytest

import fura_mappo.prediction as prediction_module
import fura_mappo.prediction.dataset as dataset_module
import fura_mappo.prediction.evaluation as evaluation_module
from fura_mappo.demand import DemandEvent, DemandTrace, compute_config_hash, save_demand_trace
from fura_mappo.prediction import (
    BaselineKind,
    CalibrationDisposition,
    DatasetProtocolSpec,
    DemandForecast,
    FirstOfficialTestExecution,
    ForecastProvenance,
    ForecastRecord,
    HistoryTransformKind,
    LearnedConfigFreezeIdentity,
    LockedBaselineFreezeIdentity,
    LockedLearnedPredictorIdentity,
    OfficialPointForecastRecord,
    OfficialPredictorSplitForecasts,
    OfficialTestExecutionKind,
    PointObjectiveKind,
    PredictionBootstrapSpec,
    PredictionOODKind,
    PreTestFreeze,
    PreTrainingFreeze,
    SealedEvaluationState,
    SplitLabel,
    TraceOODAssignment,
    VerifiedPredictionArtifact,
    ZoneSchema,
    bind_official_baseline_split_forecasts,
    bind_official_learned_split_forecasts,
    build_sealed_evaluation_state,
    build_split_manifest_from_artifacts,
    derive_prediction_samples_from_artifact,
    load_verified_prediction_artifact,
    record_first_official_test_execution,
)
from fura_mappo.prediction import TestSetDisposition as Disposition


def _sha256(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _zone_sha256() -> str:
    return ZoneSchema([[0.0, 1.0, 0.0, 1.0], [1.0, 2.0, 0.0, 1.0]]).sha256


def _trace(
    *,
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
    intensity_array = np.tile(
        np.asarray(intensities, dtype=np.float64),
        (len(counts), 1),
    )
    return DemandTrace(start_step, count_array, intensity_array, tuple(events))


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
    start_step: int,
    counts: list[list[int]],
    intensities: tuple[float, float],
) -> VerifiedPredictionArtifact:
    trace = _trace(start_step=start_step, counts=counts, intensities=intensities)
    artifact_path = save_demand_trace(
        tmp_path / f"{trace_id}.npz",
        trace,
        resolved_config=_resolved_config(
            seed=seed,
            num_steps=len(counts),
            intensities=intensities,
        ),
    )
    return load_verified_prediction_artifact(artifact_path, trace_id)


def _learned_predictor_sha256(
    *,
    predictor_implementation_sha256: str,
    config_sha256: str,
    protocol_sha256: str,
    training_seed: int,
    checkpoint_sha256: str,
) -> str:
    return compute_config_hash(
        {
            "schema": "fura-mappo.prediction-locked-learned-predictor",
            "version": 1,
            "predictor_implementation_sha256": predictor_implementation_sha256,
            "config_sha256": config_sha256,
            "protocol_sha256": protocol_sha256,
            "training_seed": training_seed,
            "checkpoint_sha256": checkpoint_sha256,
        }
    )


@dataclass(frozen=True)
class _Fixture:
    protocol: DatasetProtocolSpec
    layer_a: PreTrainingFreeze
    pretest: PreTestFreeze
    artifacts: tuple[VerifiedPredictionArtifact, ...]
    unspent: SealedEvaluationState
    spent: SealedEvaluationState


@pytest.fixture
def fixture(tmp_path: Path) -> _Fixture:
    tmp_path.mkdir(parents=True, exist_ok=True)
    protocol = DatasetProtocolSpec(2, 2, _zone_sha256())
    definitions = (
        (
            SplitLabel.TRAIN,
            "train_a",
            1,
            0,
            [[1, 0], [0, 0], [0, 1], [0, 0]],
            (0.2, 0.3),
        ),
        (
            SplitLabel.VALIDATION,
            "validation_a",
            2,
            10,
            [[0, 1], [0, 0], [1, 0], [0, 0]],
            (0.2, 0.3),
        ),
        (SplitLabel.TEST_ID, "test_id_a_zero", 3, 20, [[0, 0]], (0.2, 0.3)),
        (
            SplitLabel.TEST_ID,
            "test_id_z",
            4,
            30,
            [[1, 0], [0, 1], [1, 1], [0, 0]],
            (0.2, 0.3),
        ),
        (
            SplitLabel.TEST_OOD,
            "test_ood_a",
            5,
            40,
            [[2, 0], [0, 0], [0, 1], [0, 0]],
            (0.7, 0.8),
        ),
        (
            SplitLabel.TEST_OOD,
            "test_ood_z",
            6,
            50,
            [[0, 2], [1, 0], [0, 0], [0, 1]],
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
    learned_config = LearnedConfigFreezeIdentity(
        config_sha256=_sha256("learned-config"),
        protocol_sha256=protocol.sha256,
        objective=PointObjectiveKind.O0,
        transform=HistoryTransformKind.T0,
        model_complexity_key=(8, 32),
        canonical_order=0,
    )
    layer_a = PreTrainingFreeze(
        primary_protocol=protocol,
        secondary_protocols=(),
        split_manifest=manifest,
        calibration_disposition=CalibrationDisposition.EMPTY,
        ood_assignments=(
            TraceOODAssignment("test_id_a_zero", PredictionOODKind.ID, "primary_id_a"),
            TraceOODAssignment("test_id_z", PredictionOODKind.ID, "primary_id_z"),
            TraceOODAssignment("test_ood_a", PredictionOODKind.NEAR_OOD, "near_axis_a"),
            TraceOODAssignment(
                "test_ood_z",
                PredictionOODKind.STRUCTURAL_OOD,
                "heldout_family_z",
            ),
        ),
        fixed_training_seeds=(3, 1, 2),
        learned_config_identities=(learned_config,),
        rng_namespace_plan_sha256=_sha256("rng-plan"),
        training_plan_sha256=_sha256("training-plan"),
        baseline_plan_sha256=_sha256("baseline-plan"),
    )
    locked_baselines = tuple(
        LockedBaselineFreezeIdentity(
            baseline=baseline,
            protocol_sha256=protocol.sha256,
            predictor_sha256=_sha256(f"{baseline.value}-predictor"),
            alpha=0.5 if baseline is BaselineKind.B3 else None,
        )
        for baseline in BaselineKind
    )
    predictor_implementation_sha256 = _sha256("predictor-implementation")
    learned_predictors = []
    for training_seed in layer_a.fixed_training_seeds:
        checkpoint_sha256 = _sha256(f"checkpoint-{training_seed}")
        learned_predictors.append(
            LockedLearnedPredictorIdentity(
                training_seed,
                checkpoint_sha256,
                _learned_predictor_sha256(
                    predictor_implementation_sha256=predictor_implementation_sha256,
                    config_sha256=learned_config.config_sha256,
                    protocol_sha256=learned_config.protocol_sha256,
                    training_seed=training_seed,
                    checkpoint_sha256=checkpoint_sha256,
                ),
            )
        )
    pretest = PreTestFreeze(
        pretraining_freeze=layer_a,
        locked_baselines=locked_baselines,
        selected_baseline=BaselineKind.B0,
        selected_learned_config_identity=learned_config,
        learned_predictor_identities=tuple(learned_predictors),
        predictor_implementation_sha256=predictor_implementation_sha256,
        metric_implementation_sha256=_sha256("metric-implementation"),
        evaluation_plan_sha256=_sha256("evaluation-plan"),
        bootstrap_spec=PredictionBootstrapSpec(200, 17, "linear"),
        bootstrap_implementation_sha256=_sha256("bootstrap-implementation"),
        official_failure_state_plan_sha256=_sha256("failure-state-plan"),
        git_commit_sha="a" * 40,
        runtime_provenance_sha256=_sha256("runtime-provenance"),
    )
    unspent = build_sealed_evaluation_state((pretest,))
    first_execution = FirstOfficialTestExecution(
        pretest.sha256,
        SplitLabel.TEST_ID,
        OfficialTestExecutionKind.FORECAST_GENERATION,
    )
    spent = record_first_official_test_execution(unspent, first_execution)
    return _Fixture(protocol, layer_a, pretest, artifacts, unspent, spent)


def _artifacts_for_split(
    fixture: _Fixture,
    split: SplitLabel,
) -> tuple[VerifiedPredictionArtifact, ...]:
    trace_ids = (
        fixture.pretest.test_id_trace_ids
        if split is SplitLabel.TEST_ID
        else fixture.pretest.test_ood_trace_ids
    )
    artifacts_by_trace_id = {artifact.source.trace_id: artifact for artifact in fixture.artifacts}
    return tuple(artifacts_by_trace_id[trace_id] for trace_id in trace_ids)


def _locked_forecast_identity(
    fixture: _Fixture,
    *,
    baseline: BaselineKind | None,
    training_seed: int | None,
) -> tuple[str, str]:
    if baseline is not None:
        locked = next(
            identity
            for identity in fixture.pretest.locked_baselines
            if identity.baseline is baseline
        )
        return locked.predictor_sha256, fixture.layer_a.baseline_plan_sha256
    locked = next(
        identity
        for identity in fixture.pretest.learned_predictor_identities
        if identity.training_seed == training_seed
    )
    return locked.predictor_sha256, fixture.pretest.selected_learned_config_identity.config_sha256


def _forecast_records(
    fixture: _Fixture,
    *,
    split: SplitLabel,
    baseline: BaselineKind | None = BaselineKind.B0,
    training_seed: int | None = None,
) -> tuple[ForecastRecord, ...]:
    predictor_sha256, config_sha256 = _locked_forecast_identity(
        fixture,
        baseline=baseline,
        training_seed=training_seed,
    )
    records: list[ForecastRecord] = []
    for artifact in _artifacts_for_split(fixture, split):
        samples = derive_prediction_samples_from_artifact(artifact, fixture.protocol)
        for sample in samples:
            forecast = DemandForecast(
                absolute_step=sample.context.absolute_step,
                horizon=sample.context.prediction_horizon,
                zone_schema_sha256=sample.context.zone_schema_sha256,
                valid_mask=sample.target.valid_mask,
                mean=sample.target.counts.astype(np.float64),
            )
            provenance = ForecastProvenance(
                predictor_artifact_sha256=predictor_sha256,
                prediction_config_sha256=config_sha256,
                dataset_protocol_sha256=fixture.protocol.sha256,
                split_manifest_sha256=fixture.layer_a.split_manifest.sha256,
                sample_id=sample.sample_id,
                execution_git_commit=fixture.pretest.git_commit_sha,
            )
            records.append(ForecastRecord(forecast, provenance))
    return tuple(records)


def _bind(
    fixture: _Fixture,
    *,
    split: SplitLabel = SplitLabel.TEST_ID,
    baseline: BaselineKind | None = BaselineKind.B0,
    training_seed: int | None = None,
    state: SealedEvaluationState | None = None,
    pretest: PreTestFreeze | None = None,
    artifacts: object | None = None,
    records: object | None = None,
) -> OfficialPredictorSplitForecasts:
    actual_state = fixture.spent if state is None else state
    actual_pretest = fixture.pretest if pretest is None else pretest
    actual_artifacts = _artifacts_for_split(fixture, split) if artifacts is None else artifacts
    actual_records = (
        _forecast_records(
            fixture,
            split=split,
            baseline=baseline,
            training_seed=training_seed,
        )
        if records is None
        else records
    )
    if baseline is not None:
        return bind_official_baseline_split_forecasts(
            state=actual_state,
            pretest_freeze=actual_pretest,
            split=split,
            baseline=baseline,
            verified_artifacts=actual_artifacts,  # type: ignore[arg-type]
            forecast_records=actual_records,  # type: ignore[arg-type]
        )
    assert training_seed is not None
    return bind_official_learned_split_forecasts(
        state=actual_state,
        pretest_freeze=actual_pretest,
        split=split,
        training_seed=training_seed,
        verified_artifacts=actual_artifacts,  # type: ignore[arg-type]
        forecast_records=actual_records,  # type: ignore[arg-type]
    )


@pytest.mark.parametrize("split", [SplitLabel.TEST_ID, SplitLabel.TEST_OOD])
def test_successful_baseline_binding_has_exact_frozen_provenance(
    fixture: _Fixture,
    split: SplitLabel,
) -> None:
    bundle = _bind(fixture, split=split)
    locked = fixture.pretest.locked_baselines[0]
    expected_trace_ids = (
        fixture.pretest.test_id_trace_ids
        if split is SplitLabel.TEST_ID
        else fixture.pretest.test_ood_trace_ids
    )

    assert bundle.sealed_evaluation_state_sha256 == fixture.spent.sha256
    assert bundle.pretraining_freeze_sha256 == fixture.layer_a.sha256
    assert bundle.pretest_freeze_sha256 == fixture.pretest.sha256
    assert bundle.split is split
    assert bundle.baseline is BaselineKind.B0
    assert bundle.training_seed is None
    assert bundle.predictor_artifact_sha256 == locked.predictor_sha256
    assert bundle.prediction_config_sha256 == fixture.layer_a.baseline_plan_sha256
    assert bundle.protocol_sha256 == fixture.protocol.sha256
    assert bundle.split_manifest_sha256 == fixture.layer_a.split_manifest.sha256
    assert bundle.execution_git_commit == fixture.pretest.git_commit_sha
    assert bundle.prediction_horizon == fixture.protocol.prediction_horizon
    assert bundle.num_zones == fixture.pretest.num_zones
    assert bundle.zone_schema_sha256 == fixture.pretest.zone_schema_sha256
    assert bundle.trace_ids == expected_trace_ids
    assert bundle.point_records == tuple(record.point_record for record in bundle.records)


@pytest.mark.parametrize("split", [SplitLabel.TEST_ID, SplitLabel.TEST_OOD])
def test_successful_learned_binding_has_exact_locked_identity(
    fixture: _Fixture,
    split: SplitLabel,
) -> None:
    training_seed = fixture.layer_a.fixed_training_seeds[0]
    bundle = _bind(fixture, split=split, baseline=None, training_seed=training_seed)
    locked = fixture.pretest.learned_predictor_identities[0]

    assert bundle.baseline is None
    assert bundle.training_seed == training_seed
    assert bundle.predictor_artifact_sha256 == locked.predictor_sha256
    assert (
        bundle.prediction_config_sha256
        == fixture.pretest.selected_learned_config_identity.config_sha256
    )
    assert (
        bundle.protocol_sha256 == fixture.pretest.selected_learned_config_identity.protocol_sha256
    )


def test_unspent_rejected_before_artifact_or_forecast_access(
    fixture: _Fixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    derivation_calls = 0

    def forbidden_derivation(*args: object, **kwargs: object) -> object:
        nonlocal derivation_calls
        derivation_calls += 1
        raise AssertionError("artifact/sample derivation must not run")

    monkeypatch.setattr(
        evaluation_module,
        "derive_prediction_samples_from_artifact",
        forbidden_derivation,
    )
    with pytest.raises(ValueError, match="already-SPENT"):
        bind_official_baseline_split_forecasts(
            state=fixture.unspent,
            pretest_freeze=fixture.pretest,
            split=SplitLabel.TEST_ID,
            baseline=BaselineKind.B0,
            verified_artifacts=object(),  # type: ignore[arg-type]
            forecast_records=object(),  # type: ignore[arg-type]
        )
    assert derivation_calls == 0


def test_missing_first_exposure_is_rejected(fixture: _Fixture) -> None:
    forged_state = replace(fixture.unspent)
    object.__setattr__(forged_state, "disposition", Disposition.SPENT)

    with pytest.raises(ValueError, match="first official execution"):
        _bind(fixture, state=forged_state, artifacts=object(), records=object())


@pytest.mark.parametrize("state", [None, "state", object()])
def test_wrong_state_type_is_rejected(fixture: _Fixture, state: object) -> None:
    with pytest.raises(TypeError, match="state"):
        bind_official_baseline_split_forecasts(
            state=state,  # type: ignore[arg-type]
            pretest_freeze=fixture.pretest,
            split=SplitLabel.TEST_ID,
            baseline=BaselineKind.B0,
            verified_artifacts=object(),  # type: ignore[arg-type]
            forecast_records=object(),  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("pretest", [None, "freeze", object()])
def test_wrong_pretest_type_is_rejected(fixture: _Fixture, pretest: object) -> None:
    with pytest.raises(TypeError, match="pretest_freeze"):
        bind_official_baseline_split_forecasts(
            state=fixture.spent,
            pretest_freeze=pretest,  # type: ignore[arg-type]
            split=SplitLabel.TEST_ID,
            baseline=BaselineKind.B0,
            verified_artifacts=object(),  # type: ignore[arg-type]
            forecast_records=object(),  # type: ignore[arg-type]
        )


def test_unregistered_pretest_is_rejected(fixture: _Fixture) -> None:
    unregistered = replace(
        fixture.pretest,
        evaluation_plan_sha256=_sha256("different-evaluation-plan"),
    )

    with pytest.raises(ValueError, match="registered"):
        _bind(fixture, pretest=unregistered, artifacts=object(), records=object())


@pytest.mark.parametrize(
    ("field_name", "value", "message"),
    [
        ("pretraining_freeze_sha256", "b" * 64, "Layer-A SHA"),
        ("test_id_trace_ids", ("different_id",), "TEST_ID"),
        ("test_ood_trace_ids", ("different_ood",), "TEST_OOD"),
    ],
)
def test_pretest_state_rebind_is_exact(
    fixture: _Fixture,
    field_name: str,
    value: object,
    message: str,
) -> None:
    forged_pretest = replace(fixture.pretest)
    object.__setattr__(forged_pretest, field_name, value)

    with pytest.raises(ValueError, match=message):
        _bind(fixture, pretest=forged_pretest, artifacts=object(), records=object())


@pytest.mark.parametrize(
    "split",
    [SplitLabel.TRAIN, SplitLabel.VALIDATION, SplitLabel.CALIBRATION],
)
def test_non_test_split_is_rejected_before_artifact_access(
    fixture: _Fixture,
    split: SplitLabel,
) -> None:
    with pytest.raises(ValueError, match="TEST_ID"):
        _bind(fixture, split=split, artifacts=object(), records=object())


def test_split_requires_exact_enum_type(fixture: _Fixture) -> None:
    with pytest.raises(TypeError, match="split"):
        bind_official_baseline_split_forecasts(
            state=fixture.spent,
            pretest_freeze=fixture.pretest,
            split="test_id",  # type: ignore[arg-type]
            baseline=BaselineKind.B0,
            verified_artifacts=object(),  # type: ignore[arg-type]
            forecast_records=object(),  # type: ignore[arg-type]
        )


def test_artifact_coverage_missing_extra_and_duplicate(fixture: _Fixture) -> None:
    artifacts = _artifacts_for_split(fixture, SplitLabel.TEST_ID)
    records = _forecast_records(fixture, split=SplitLabel.TEST_ID)
    train_artifact = next(
        artifact for artifact in fixture.artifacts if artifact.source.trace_id == "train_a"
    )

    with pytest.raises(ValueError, match="exactly|精确"):
        _bind(fixture, artifacts=artifacts[:-1], records=records)
    with pytest.raises(ValueError, match="exactly|精确"):
        _bind(fixture, artifacts=(*artifacts, train_artifact), records=records)
    with pytest.raises(ValueError, match="duplicate|重复"):
        _bind(fixture, artifacts=(*artifacts, artifacts[0]), records=records)


@pytest.mark.parametrize("value", [None, "artifact", object()])
def test_artifact_collection_requires_verified_types(fixture: _Fixture, value: object) -> None:
    with pytest.raises(TypeError, match="VerifiedPredictionArtifact"):
        _bind(fixture, artifacts=(value,))


def test_wrong_authoritative_source_binding_is_rejected(fixture: _Fixture) -> None:
    artifacts = list(_artifacts_for_split(fixture, SplitLabel.TEST_ID))
    original = artifacts[0]
    forged_source = replace(original.source, seed=original.source.seed + 100)
    artifacts[0] = VerifiedPredictionArtifact(
        original.artifact,
        forged_source,
        dataset_module._VERIFIED_ARTIFACT_TOKEN,
    )

    with pytest.raises(ValueError, match="PredictionSource"):
        _bind(fixture, artifacts=tuple(artifacts))


def test_caller_artifact_order_does_not_change_output(fixture: _Fixture) -> None:
    artifacts = _artifacts_for_split(fixture, SplitLabel.TEST_OOD)
    records = _forecast_records(fixture, split=SplitLabel.TEST_OOD)

    first = _bind(fixture, split=SplitLabel.TEST_OOD, artifacts=artifacts, records=records)
    second = _bind(
        fixture,
        split=SplitLabel.TEST_OOD,
        artifacts=tuple(reversed(artifacts)),
        records=records,
    )

    assert first.trace_ids == second.trace_ids
    assert tuple(
        (
            record.point_record.trace_id,
            record.point_record.sample.sample_id,
            record.point_record.sample.context.absolute_step,
            record.provenance,
        )
        for record in first.records
    ) == tuple(
        (
            record.point_record.trace_id,
            record.point_record.sample.sample_id,
            record.point_record.sample.context.absolute_step,
            record.provenance,
        )
        for record in second.records
    )


@pytest.mark.parametrize("baseline", tuple(BaselineKind))
def test_each_locked_baseline_is_individually_bindable(
    fixture: _Fixture,
    baseline: BaselineKind,
) -> None:
    bundle = _bind(
        fixture,
        baseline=baseline,
        records=_forecast_records(fixture, split=SplitLabel.TEST_ID, baseline=baseline),
    )
    locked = next(
        identity for identity in fixture.pretest.locked_baselines if identity.baseline is baseline
    )

    assert bundle.baseline is baseline
    assert bundle.predictor_artifact_sha256 == locked.predictor_sha256
    assert bundle.protocol_sha256 == locked.protocol_sha256
    assert bundle.prediction_config_sha256 == fixture.layer_a.baseline_plan_sha256


@pytest.mark.parametrize("baseline", [None, "B0", 0, object()])
def test_baseline_requires_exact_kind(fixture: _Fixture, baseline: object) -> None:
    with pytest.raises(TypeError, match="baseline"):
        bind_official_baseline_split_forecasts(
            state=fixture.spent,
            pretest_freeze=fixture.pretest,
            split=SplitLabel.TEST_ID,
            baseline=baseline,  # type: ignore[arg-type]
            verified_artifacts=object(),  # type: ignore[arg-type]
            forecast_records=object(),  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("training_seed_index", [0, 1, 2])
def test_each_fixed_training_seed_is_bindable(
    fixture: _Fixture,
    training_seed_index: int,
) -> None:
    training_seed = fixture.layer_a.fixed_training_seeds[training_seed_index]
    records = _forecast_records(
        fixture,
        split=SplitLabel.TEST_ID,
        baseline=None,
        training_seed=training_seed,
    )
    bundle = _bind(
        fixture,
        baseline=None,
        training_seed=training_seed,
        records=records,
    )
    locked = next(
        identity
        for identity in fixture.pretest.learned_predictor_identities
        if identity.training_seed == training_seed
    )

    assert bundle.training_seed == training_seed
    assert bundle.predictor_artifact_sha256 == locked.predictor_sha256
    assert bundle.prediction_config_sha256 == (
        fixture.pretest.selected_learned_config_identity.config_sha256
    )
    assert (
        bundle.protocol_sha256 == fixture.pretest.selected_learned_config_identity.protocol_sha256
    )


@pytest.mark.parametrize("training_seed", [0, 99])
def test_unknown_training_seed_is_rejected(
    fixture: _Fixture,
    training_seed: int,
) -> None:
    with pytest.raises(ValueError, match="training_seed"):
        bind_official_learned_split_forecasts(
            state=fixture.spent,
            pretest_freeze=fixture.pretest,
            split=SplitLabel.TEST_ID,
            training_seed=training_seed,
            verified_artifacts=object(),  # type: ignore[arg-type]
            forecast_records=object(),  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("training_seed", [True, 1.0, "1", None])
def test_training_seed_requires_nonbool_integer(
    fixture: _Fixture,
    training_seed: object,
) -> None:
    with pytest.raises(TypeError, match="training_seed"):
        bind_official_learned_split_forecasts(
            state=fixture.spent,
            pretest_freeze=fixture.pretest,
            split=SplitLabel.TEST_ID,
            training_seed=training_seed,  # type: ignore[arg-type]
            verified_artifacts=object(),  # type: ignore[arg-type]
            forecast_records=object(),  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    ("field_name", "replacement_value", "message"),
    [
        ("predictor_artifact_sha256", _sha256("wrong-predictor"), "predictor artifact"),
        ("prediction_config_sha256", _sha256("wrong-config"), "prediction config"),
        ("dataset_protocol_sha256", _sha256("wrong-protocol"), "protocol"),
        ("split_manifest_sha256", _sha256("wrong-manifest"), "manifest"),
        ("execution_git_commit", "b" * 40, "Git commit"),
    ],
)
def test_each_locked_provenance_mismatch_is_rejected(
    fixture: _Fixture,
    field_name: str,
    replacement_value: object,
    message: str,
) -> None:
    records = list(_forecast_records(fixture, split=SplitLabel.TEST_ID))
    records[0] = replace(
        records[0],
        provenance=replace(records[0].provenance, **{field_name: replacement_value}),
    )

    with pytest.raises(ValueError, match=message):
        _bind(fixture, records=tuple(records))


def test_provenance_sample_id_mismatch_is_rejected(fixture: _Fixture) -> None:
    records = list(_forecast_records(fixture, split=SplitLabel.TEST_ID))
    records[0] = replace(
        records[0],
        provenance=replace(records[0].provenance, sample_id=_sha256("unknown-sample")),
    )

    with pytest.raises(ValueError, match="sample IDs"):
        _bind(fixture, records=tuple(records))


@pytest.mark.parametrize(
    ("field_name", "replacement_value", "message"),
    [
        ("normalization_sha256", _sha256("normalization"), "normalization_sha256"),
        ("inference_rng_id", "rng-stream", "inference_rng_id"),
    ],
)
def test_point_only_provenance_rejects_optional_transform_or_rng(
    fixture: _Fixture,
    field_name: str,
    replacement_value: object,
    message: str,
) -> None:
    records = list(_forecast_records(fixture, split=SplitLabel.TEST_ID))
    records[0] = replace(
        records[0],
        provenance=replace(records[0].provenance, **{field_name: replacement_value}),
    )

    with pytest.raises(ValueError, match=message):
        _bind(fixture, records=tuple(records))


def test_forecast_coverage_missing_extra_and_duplicate(fixture: _Fixture) -> None:
    records = _forecast_records(fixture, split=SplitLabel.TEST_ID)
    extra = replace(
        records[0],
        provenance=replace(records[0].provenance, sample_id=_sha256("extra-sample")),
    )

    with pytest.raises(ValueError, match="exactly|精确"):
        _bind(fixture, records=records[:-1])
    with pytest.raises(ValueError, match="exactly|精确"):
        _bind(fixture, records=(*records, extra))
    with pytest.raises(ValueError, match="duplicate|重复"):
        _bind(fixture, records=(*records, records[0]))


@pytest.mark.parametrize("value", [None, "record", object()])
def test_forecast_collection_requires_record_types(fixture: _Fixture, value: object) -> None:
    with pytest.raises(TypeError, match="ForecastRecord"):
        _bind(fixture, records=(value,))


def test_caller_forecast_order_is_ignored_and_output_is_canonical(fixture: _Fixture) -> None:
    records = _forecast_records(fixture, split=SplitLabel.TEST_OOD)

    bundle = _bind(
        fixture,
        split=SplitLabel.TEST_OOD,
        records=tuple(reversed(records)),
    )
    actual_order = tuple(
        (
            record.point_record.trace_id,
            record.point_record.sample.context.absolute_step,
        )
        for record in bundle.records
    )
    expected_order = tuple(
        sorted(
            actual_order,
            key=lambda item: (bundle.trace_ids.index(item[0]), item[1]),
        )
    )

    assert actual_order == expected_order


def test_frozen_nonlexical_trace_order_is_preserved(fixture: _Fixture) -> None:
    forged_pretest = replace(fixture.pretest)
    reversed_trace_ids = tuple(reversed(fixture.pretest.test_ood_trace_ids))
    object.__setattr__(forged_pretest, "test_ood_trace_ids", reversed_trace_ids)
    unspent = build_sealed_evaluation_state((forged_pretest,))
    first_execution = FirstOfficialTestExecution(
        forged_pretest.sha256,
        SplitLabel.TEST_OOD,
        OfficialTestExecutionKind.FORECAST_GENERATION,
    )
    spent = record_first_official_test_execution(unspent, first_execution)
    records = _forecast_records(fixture, split=SplitLabel.TEST_OOD)

    bundle = _bind(
        fixture,
        split=SplitLabel.TEST_OOD,
        state=spent,
        pretest=forged_pretest,
        records=records,
    )

    assert bundle.trace_ids == reversed_trace_ids
    assert tuple(dict.fromkeys(record.point_record.trace_id for record in bundle.records)) == (
        reversed_trace_ids
    )


def test_one_step_trace_is_retained_with_zero_records(fixture: _Fixture) -> None:
    bundle = _bind(fixture, split=SplitLabel.TEST_ID)

    assert "test_id_a_zero" in bundle.trace_ids
    assert all(record.point_record.trace_id != "test_id_a_zero" for record in bundle.records)


def _replace_first_forecast(
    records: tuple[ForecastRecord, ...],
    **changes: object,
) -> tuple[ForecastRecord, ...]:
    changed = list(records)
    changed[0] = replace(changed[0], forecast=replace(changed[0].forecast, **changes))
    return tuple(changed)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"absolute_step": 999}, "absolute_step"),
        ({"zone_schema_sha256": _sha256("wrong-zone")}, "zone_schema"),
    ],
)
def test_forecast_context_identity_mismatch_is_rejected(
    fixture: _Fixture,
    changes: dict[str, object],
    message: str,
) -> None:
    records = _forecast_records(fixture, split=SplitLabel.TEST_ID)

    with pytest.raises(ValueError, match=message):
        _bind(fixture, records=_replace_first_forecast(records, **changes))


def test_forecast_horizon_and_zone_count_mismatch_are_rejected(fixture: _Fixture) -> None:
    records = _forecast_records(fixture, split=SplitLabel.TEST_ID)
    first_forecast = records[0].forecast
    wrong_horizon = _replace_first_forecast(
        records,
        horizon=1,
        valid_mask=first_forecast.valid_mask[:1],
        mean=first_forecast.mean[:1],
    )
    wrong_zone_count = _replace_first_forecast(
        records,
        mean=first_forecast.mean[:, :1],
    )

    with pytest.raises(ValueError, match="prediction_horizon"):
        _bind(fixture, records=wrong_horizon)
    with pytest.raises(ValueError, match="zone|num_zones"):
        _bind(fixture, records=wrong_zone_count)


def test_forecast_valid_mask_mismatch_is_rejected(fixture: _Fixture) -> None:
    records = _forecast_records(fixture, split=SplitLabel.TEST_ID)
    first_forecast = records[0].forecast
    wrong_mean = np.array(first_forecast.mean, copy=True)
    wrong_mean[1] = 0.0
    wrong_mask = _replace_first_forecast(
        records,
        valid_mask=np.asarray([True, False]),
        mean=wrong_mean,
    )

    with pytest.raises(ValueError, match="valid_mask"):
        _bind(fixture, records=wrong_mask)


@pytest.mark.parametrize("bad_value", [np.nan, -1.0])
def test_nonfinite_or_negative_point_mean_is_rejected_before_binding(
    fixture: _Fixture,
    bad_value: float,
) -> None:
    sample = next(
        sample
        for artifact in _artifacts_for_split(fixture, SplitLabel.TEST_ID)
        for sample in derive_prediction_samples_from_artifact(artifact, fixture.protocol)
    )
    mean = sample.target.counts.astype(np.float64)
    mean[0, 0] = bad_value

    with pytest.raises(ValueError):
        DemandForecast(
            absolute_step=sample.context.absolute_step,
            horizon=sample.context.prediction_horizon,
            zone_schema_sha256=sample.context.zone_schema_sha256,
            valid_mask=sample.target.valid_mask,
            mean=mean,
        )


@pytest.mark.parametrize("payload_kind", ["variance", "quantiles", "scenarios"])
def test_probabilistic_forecast_payload_is_rejected(
    fixture: _Fixture,
    payload_kind: str,
) -> None:
    records = _forecast_records(fixture, split=SplitLabel.TEST_ID)
    forecast = records[0].forecast
    changes: dict[str, object]
    if payload_kind == "variance":
        changes = {"variance": np.zeros_like(forecast.mean)}
    elif payload_kind == "quantiles":
        changes = {
            "quantile_levels": np.asarray([0.5]),
            "quantiles": forecast.mean[np.newaxis, :, :],
        }
    else:
        changes = {"scenarios": np.zeros((1, *forecast.mean.shape), dtype=np.int64)}

    with pytest.raises(ValueError, match=payload_kind):
        _bind(fixture, records=_replace_first_forecast(records, **changes))


def test_result_records_are_frozen_slotted_and_identity_only(fixture: _Fixture) -> None:
    bundle = _bind(fixture)
    record = bundle.records[0]
    bundle_field_names = tuple(item.name for item in fields(bundle))

    assert not hasattr(bundle, "__dict__")
    assert not hasattr(record, "__dict__")
    assert bundle_field_names == (
        "sealed_evaluation_state_sha256",
        "pretraining_freeze_sha256",
        "pretest_freeze_sha256",
        "split",
        "baseline",
        "training_seed",
        "predictor_artifact_sha256",
        "prediction_config_sha256",
        "protocol_sha256",
        "split_manifest_sha256",
        "execution_git_commit",
        "prediction_horizon",
        "num_zones",
        "zone_schema_sha256",
        "trace_ids",
        "records",
    )
    assert all(
        not isinstance(getattr(bundle, item.name), (VerifiedPredictionArtifact, DemandTrace))
        for item in fields(bundle)
    )
    assert not hasattr(bundle, "schema")
    assert not hasattr(bundle, "version")
    assert not hasattr(bundle, "sha256")
    assert not hasattr(bundle, "timestamp")
    assert not hasattr(bundle, "nonce")
    with pytest.raises(FrozenInstanceError):
        bundle.baseline = BaselineKind.B1  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        record.provenance = record.provenance  # type: ignore[misc]


def test_result_requires_exact_baseline_training_seed_one_of(fixture: _Fixture) -> None:
    bundle = _bind(fixture)

    with pytest.raises(ValueError, match="one-of"):
        replace(bundle, baseline=None, training_seed=None)
    with pytest.raises(ValueError, match="one-of"):
        replace(bundle, baseline=BaselineKind.B0, training_seed=1)


def test_official_point_record_rejects_wrong_types_and_sample_binding(
    fixture: _Fixture,
) -> None:
    bundle = _bind(fixture)
    record = bundle.records[0]

    with pytest.raises(TypeError, match="point_record"):
        OfficialPointForecastRecord(object(), record.provenance)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="provenance"):
        OfficialPointForecastRecord(record.point_record, object())  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="sample_id"):
        OfficialPointForecastRecord(
            record.point_record,
            replace(record.provenance, sample_id=_sha256("other-sample")),
        )


def test_state_and_pretest_remain_immutable_after_binding(fixture: _Fixture) -> None:
    state_before = (
        fixture.spent.sha256,
        fixture.spent.disposition,
        fixture.spent.first_official_test_execution,
        fixture.spent.registered_pretest_freeze_sha256s,
        fixture.spent.test_id_trace_ids,
        fixture.spent.test_ood_trace_ids,
    )
    pretest_before = (fixture.pretest.sha256, fixture.pretest.test_id_trace_ids)

    _bind(fixture)

    assert state_before == (
        fixture.spent.sha256,
        fixture.spent.disposition,
        fixture.spent.first_official_test_execution,
        fixture.spent.registered_pretest_freeze_sha256s,
        fixture.spent.test_id_trace_ids,
        fixture.spent.test_ood_trace_ids,
    )
    assert pretest_before == (fixture.pretest.sha256, fixture.pretest.test_id_trace_ids)
    assert fixture.spent.disposition is Disposition.SPENT


def test_public_api_exports_exact_slice_14_surface() -> None:
    expected = {
        "OfficialPointForecastRecord": OfficialPointForecastRecord,
        "OfficialPredictorSplitForecasts": OfficialPredictorSplitForecasts,
        "bind_official_baseline_split_forecasts": bind_official_baseline_split_forecasts,
        "bind_official_learned_split_forecasts": bind_official_learned_split_forecasts,
    }

    for name, value in expected.items():
        assert getattr(prediction_module, name) is value
        assert name in prediction_module.__all__
    assert evaluation_module.__all__ == list(expected)


def test_production_has_no_generation_science_rng_persistence_or_failure_construction() -> None:
    source = inspect.getsource(evaluation_module)
    forbidden = (
        ".predict(",
        "derive_synthetic_prediction_samples",
        "evaluate_point_forecasts",
        "compute_locked_test_point_estimate",
        "bootstrap_locked_test_delta_rmse",
        "interpret_primary_id_bootstrap",
        "record_prediction_evaluation_failure(",
        "np.random",
        "numpy.random",
        "default_rng",
        "PCG64",
        "random.Random",
        "torch",
        "subprocess",
        "os.system",
        "GitPython",
        "write_text(",
        "write_bytes(",
        "json.dump",
        "yaml",
        "np.save",
        "timestamp",
        "nonce",
        "artifact_path",
        "PredictionEvaluationSuccess",
        "finalize_success",
        "recover_prediction_evaluation",
        "retry_prediction_evaluation",
    )

    assert all(token not in source for token in forbidden)
    for scientific_token in ("delta_rmse", "ci_lower", "ci_upper", "primary_id_label"):
        assert scientific_token not in source.lower()


def test_public_factory_signatures_are_keyword_only_and_do_not_generate_forecasts() -> None:
    baseline_signature = inspect.signature(bind_official_baseline_split_forecasts)
    learned_signature = inspect.signature(bind_official_learned_split_forecasts)

    assert tuple(baseline_signature.parameters) == (
        "state",
        "pretest_freeze",
        "split",
        "baseline",
        "verified_artifacts",
        "forecast_records",
    )
    assert tuple(learned_signature.parameters) == (
        "state",
        "pretest_freeze",
        "split",
        "training_seed",
        "verified_artifacts",
        "forecast_records",
    )
    assert all(
        parameter.kind is inspect.Parameter.KEYWORD_ONLY
        for parameter in baseline_signature.parameters.values()
    )
    assert all(
        parameter.kind is inspect.Parameter.KEYWORD_ONLY
        for parameter in learned_signature.parameters.values()
    )
    assert "predictor" not in baseline_signature.parameters
    assert "predictor" not in learned_signature.parameters
