from __future__ import annotations

import hashlib
import inspect
from dataclasses import FrozenInstanceError, dataclass, fields, replace

import pytest

import fura_mappo.prediction as prediction_module
import fura_mappo.prediction.governance as governance_module
from fura_mappo.demand import compute_config_hash
from fura_mappo.prediction import (
    BaselineKind,
    CalibrationDisposition,
    DatasetProtocolSpec,
    DatasetSplitManifest,
    FirstOfficialTestExecution,
    HistoryTransformKind,
    LearnedConfigFreezeIdentity,
    LockedBaselineFreezeIdentity,
    LockedLearnedPredictorIdentity,
    OfficialTestExecutionKind,
    PointObjectiveKind,
    PredictionBootstrapSpec,
    PredictionEvaluationFailure,
    PredictionOODKind,
    PredictionSource,
    PreTestFreeze,
    PreTrainingFreeze,
    SealedEvaluationState,
    SplitEntry,
    SplitLabel,
    TraceOODAssignment,
    build_sealed_evaluation_state,
    record_first_official_test_execution,
    record_prediction_evaluation_failure,
)
from fura_mappo.prediction import TestSetDisposition as Disposition


def _sha256(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _source(trace_id: str, seed: int, zone_schema_sha256: str) -> PredictionSource:
    return PredictionSource(
        trace_id=trace_id,
        seed=seed,
        process_type="synthetic_identity",
        config_sha256=_sha256(f"{trace_id}-config"),
        content_sha256=_sha256(f"{trace_id}-content"),
        realized_trace_sha256=_sha256(f"{trace_id}-realized"),
        condition_sha256=_sha256(f"{trace_id}-condition"),
        zone_schema_sha256=zone_schema_sha256,
        start_step=10,
        num_steps=20,
        num_zones=2,
    )


def _pretraining_freeze() -> PreTrainingFreeze:
    zone_schema_sha256 = _sha256("zone-schema")
    protocol = DatasetProtocolSpec(8, 2, zone_schema_sha256)
    definitions = (
        (SplitLabel.TRAIN, "train_a", 1),
        (SplitLabel.VALIDATION, "validation_a", 2),
        (SplitLabel.TEST_ID, "test_id_z", 3),
        (SplitLabel.TEST_ID, "test_id_a", 4),
        (SplitLabel.TEST_OOD, "test_ood_a", 5),
        (SplitLabel.TEST_OOD, "test_ood_z", 6),
    )
    manifest = DatasetSplitManifest(
        tuple(
            SplitEntry(split, _source(trace_id, seed, zone_schema_sha256))
            for split, trace_id, seed in definitions
        )
    )
    learned_identity = LearnedConfigFreezeIdentity(
        config_sha256=_sha256("learned-config"),
        protocol_sha256=protocol.sha256,
        objective=PointObjectiveKind.O0,
        transform=HistoryTransformKind.T0,
        model_complexity_key=(8, 32),
        canonical_order=0,
    )
    return PreTrainingFreeze(
        primary_protocol=protocol,
        secondary_protocols=(),
        split_manifest=manifest,
        calibration_disposition=CalibrationDisposition.EMPTY,
        ood_assignments=(
            TraceOODAssignment("test_id_z", PredictionOODKind.ID, "primary_id_z"),
            TraceOODAssignment("test_id_a", PredictionOODKind.ID, "primary_id_a"),
            TraceOODAssignment(
                "test_ood_a",
                PredictionOODKind.NEAR_OOD,
                "near_axis_a",
            ),
            TraceOODAssignment(
                "test_ood_z",
                PredictionOODKind.STRUCTURAL_OOD,
                "heldout_family_z",
            ),
        ),
        fixed_training_seeds=(1, 2, 3),
        learned_config_identities=(learned_identity,),
        rng_namespace_plan_sha256=_sha256("rng-plan"),
        training_plan_sha256=_sha256("training-plan"),
        baseline_plan_sha256=_sha256("baseline-plan"),
    )


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


def _pretest_freeze(
    *,
    identity_label: str,
    pretraining_freeze: PreTrainingFreeze,
) -> PreTestFreeze:
    protocol_sha256 = pretraining_freeze.primary_protocol.sha256
    predictor_implementation_sha256 = _sha256("predictor-implementation")
    locked_baselines = tuple(
        LockedBaselineFreezeIdentity(
            baseline=baseline,
            protocol_sha256=protocol_sha256,
            predictor_sha256=_sha256(f"{identity_label}-{baseline.value}-predictor"),
            alpha=0.5 if baseline is BaselineKind.B3 else None,
        )
        for baseline in BaselineKind
    )
    selected_learned = pretraining_freeze.learned_config_identities[0]
    learned_predictors = []
    for training_seed in pretraining_freeze.fixed_training_seeds:
        checkpoint_sha256 = _sha256(f"{identity_label}-checkpoint-{training_seed}")
        learned_predictors.append(
            LockedLearnedPredictorIdentity(
                training_seed,
                checkpoint_sha256,
                _learned_predictor_sha256(
                    predictor_implementation_sha256=predictor_implementation_sha256,
                    config_sha256=selected_learned.config_sha256,
                    protocol_sha256=selected_learned.protocol_sha256,
                    training_seed=training_seed,
                    checkpoint_sha256=checkpoint_sha256,
                ),
            )
        )
    return PreTestFreeze(
        pretraining_freeze=pretraining_freeze,
        locked_baselines=locked_baselines,
        selected_baseline=BaselineKind.B0,
        selected_learned_config_identity=selected_learned,
        learned_predictor_identities=tuple(learned_predictors),
        predictor_implementation_sha256=predictor_implementation_sha256,
        metric_implementation_sha256=_sha256("metric-implementation"),
        evaluation_plan_sha256=_sha256(f"{identity_label}-evaluation-plan"),
        bootstrap_spec=PredictionBootstrapSpec(200, 17, "linear"),
        bootstrap_implementation_sha256=_sha256("bootstrap-implementation"),
        official_failure_state_plan_sha256=_sha256(f"{identity_label}-failure-state-plan"),
        git_commit_sha="a" * 40,
        runtime_provenance_sha256=_sha256("runtime-provenance"),
    )


@dataclass(frozen=True)
class _Fixture:
    primary: PreTestFreeze
    secondary: PreTestFreeze
    unspent: SealedEvaluationState
    spent: SealedEvaluationState
    first_execution: FirstOfficialTestExecution


@pytest.fixture
def fixture() -> _Fixture:
    layer_a = _pretraining_freeze()
    primary = _pretest_freeze(identity_label="primary", pretraining_freeze=layer_a)
    secondary = _pretest_freeze(identity_label="secondary", pretraining_freeze=layer_a)
    unspent = build_sealed_evaluation_state((secondary, primary))
    first_execution = FirstOfficialTestExecution(
        primary.sha256,
        SplitLabel.TEST_ID,
        OfficialTestExecutionKind.FORECAST_GENERATION,
    )
    spent = record_first_official_test_execution(unspent, first_execution)
    return _Fixture(primary, secondary, unspent, spent, first_execution)


def _record(
    fixture: _Fixture,
    *,
    pretest_freeze: PreTestFreeze | None = None,
    failure_split: SplitLabel = SplitLabel.TEST_ID,
    failure_action_kind: OfficialTestExecutionKind = OfficialTestExecutionKind.METRIC_COMPUTATION,
    failure_reason: str = "required checkpoint missing",
) -> PredictionEvaluationFailure:
    return record_prediction_evaluation_failure(
        state=fixture.spent,
        pretest_freeze=pretest_freeze or fixture.primary,
        failure_split=failure_split,
        failure_action_kind=failure_action_kind,
        failure_reason=failure_reason,
    )


def _direct_changes(
    failure: PredictionEvaluationFailure,
    **changes: object,
) -> PredictionEvaluationFailure:
    return replace(failure, **changes)


def _forged_pretest(
    freeze: PreTestFreeze,
    **derived_changes: object,
) -> PreTestFreeze:
    forged = replace(freeze)
    for name, value in derived_changes.items():
        object.__setattr__(forged, name, value)
    return forged


def test_exact_status_public_api_and_no_failure_kind_taxonomy(fixture: _Fixture) -> None:
    failure = _record(fixture)

    assert failure.status == "PREDICTION_EVALUATION_FAILURE"
    assert failure.status not in {
        "PROTOCOL_FAIL",
        "PRE_TRAINING_DATA_FREEZE_FAILURE",
        "PREDICTION_BASELINE_SELECTION_FAILURE",
        "PREDICTION_MODEL_SELECTION_FAILURE",
        "TRAINING_FAILURE",
    }
    assert prediction_module.PredictionEvaluationFailure is PredictionEvaluationFailure
    assert (
        prediction_module.record_prediction_evaluation_failure
        is record_prediction_evaluation_failure
    )
    assert "PredictionEvaluationFailure" in prediction_module.__all__
    assert "record_prediction_evaluation_failure" in prediction_module.__all__
    for name in ("PredictionEvaluationFailureKind", "EvaluationFailureKind"):
        assert not hasattr(governance_module, name)
        assert not hasattr(prediction_module, name)


def test_successful_record_copies_exact_identities_without_mutating_state(
    fixture: _Fixture,
) -> None:
    before = (
        fixture.spent.sha256,
        fixture.spent.disposition,
        fixture.spent.first_official_test_execution,
        fixture.spent.registered_pretest_freeze_sha256s,
        fixture.spent.test_id_trace_ids,
        fixture.spent.test_ood_trace_ids,
    )

    failure = _record(fixture, failure_reason="  forecast/context binding failed  ")

    assert failure.sealed_evaluation_state_sha256 == fixture.spent.sha256
    assert failure.pretraining_freeze_sha256 == fixture.spent.pretraining_freeze_sha256
    assert (
        failure.registered_pretest_freeze_sha256s == fixture.spent.registered_pretest_freeze_sha256s
    )
    assert failure.pretest_freeze_sha256 == fixture.primary.sha256
    assert failure.evaluation_plan_sha256 == fixture.primary.evaluation_plan_sha256
    assert (
        failure.official_failure_state_plan_sha256
        == fixture.primary.official_failure_state_plan_sha256
    )
    assert failure.test_id_trace_ids == fixture.spent.test_id_trace_ids
    assert failure.test_ood_trace_ids == fixture.spent.test_ood_trace_ids
    assert failure.first_official_test_execution is fixture.first_execution
    assert failure.failure_split is SplitLabel.TEST_ID
    assert failure.failure_action_kind is OfficialTestExecutionKind.METRIC_COMPUTATION
    assert failure.failure_reason == "forecast/context binding failed"
    assert fixture.spent.disposition is Disposition.SPENT
    assert before == (
        fixture.spent.sha256,
        fixture.spent.disposition,
        fixture.spent.first_official_test_execution,
        fixture.spent.registered_pretest_freeze_sha256s,
        fixture.spent.test_id_trace_ids,
        fixture.spent.test_ood_trace_ids,
    )


@pytest.mark.parametrize("pretest_name", ["primary", "secondary"])
def test_any_registered_freeze_can_be_the_failure_location(
    fixture: _Fixture,
    pretest_name: str,
) -> None:
    pretest_freeze = getattr(fixture, pretest_name)

    failure = _record(fixture, pretest_freeze=pretest_freeze)

    assert failure.pretest_freeze_sha256 == pretest_freeze.sha256
    assert failure.evaluation_plan_sha256 == pretest_freeze.evaluation_plan_sha256
    assert (
        failure.official_failure_state_plan_sha256
        == pretest_freeze.official_failure_state_plan_sha256
    )
    assert failure.first_official_test_execution is fixture.first_execution


@pytest.mark.parametrize("failure_split", [SplitLabel.TEST_ID, SplitLabel.TEST_OOD])
@pytest.mark.parametrize("failure_action_kind", tuple(OfficialTestExecutionKind))
def test_each_official_failure_location_is_recordable_after_exposure(
    fixture: _Fixture,
    failure_split: SplitLabel,
    failure_action_kind: OfficialTestExecutionKind,
) -> None:
    failure = _record(
        fixture,
        pretest_freeze=fixture.secondary,
        failure_split=failure_split,
        failure_action_kind=failure_action_kind,
    )

    assert failure.failure_split is failure_split
    assert failure.failure_action_kind is failure_action_kind
    assert (
        failure.first_official_test_execution.kind is OfficialTestExecutionKind.FORECAST_GENERATION
    )


def test_unspent_and_missing_first_exposure_are_hard_failures(fixture: _Fixture) -> None:
    with pytest.raises(ValueError, match="already-exposed"):
        record_prediction_evaluation_failure(
            state=fixture.unspent,
            pretest_freeze=fixture.primary,
            failure_split=SplitLabel.TEST_ID,
            failure_action_kind=OfficialTestExecutionKind.FORECAST_GENERATION,
            failure_reason="synthetic failure",
        )

    forged = replace(fixture.unspent)
    object.__setattr__(forged, "disposition", Disposition.SPENT)
    with pytest.raises(ValueError, match="first official execution"):
        record_prediction_evaluation_failure(
            state=forged,
            pretest_freeze=fixture.primary,
            failure_split=SplitLabel.TEST_ID,
            failure_action_kind=OfficialTestExecutionKind.FORECAST_GENERATION,
            failure_reason="synthetic failure",
        )


@pytest.mark.parametrize(
    ("state", "pretest_freeze", "message"),
    [
        (None, None, "state"),
        ("state", None, "state"),
    ],
)
def test_factory_rejects_wrong_state_type(
    state: object,
    pretest_freeze: object,
    message: str,
) -> None:
    with pytest.raises(TypeError, match=message):
        record_prediction_evaluation_failure(
            state=state,  # type: ignore[arg-type]
            pretest_freeze=pretest_freeze,  # type: ignore[arg-type]
            failure_split=SplitLabel.TEST_ID,
            failure_action_kind=OfficialTestExecutionKind.FORECAST_GENERATION,
            failure_reason="synthetic failure",
        )


@pytest.mark.parametrize("value", [None, "freeze", object()])
def test_factory_rejects_wrong_pretest_type(fixture: _Fixture, value: object) -> None:
    with pytest.raises(TypeError, match="pretest_freeze"):
        record_prediction_evaluation_failure(
            state=fixture.spent,
            pretest_freeze=value,  # type: ignore[arg-type]
            failure_split=SplitLabel.TEST_ID,
            failure_action_kind=OfficialTestExecutionKind.FORECAST_GENERATION,
            failure_reason="synthetic failure",
        )


def test_unregistered_pretest_freeze_is_rejected(fixture: _Fixture) -> None:
    unregistered = replace(
        fixture.primary,
        evaluation_plan_sha256=_sha256("unregistered-evaluation-plan"),
    )

    with pytest.raises(ValueError, match="registered"):
        _record(fixture, pretest_freeze=unregistered)


@pytest.mark.parametrize(
    ("field_name", "value", "message"),
    [
        ("pretraining_freeze_sha256", "b" * 64, "Layer-A SHA"),
        ("test_id_trace_ids", ("different_test_id",), "TEST_ID"),
        ("test_ood_trace_ids", ("different_test_ood",), "TEST_OOD"),
    ],
)
def test_factory_rebinds_exact_layer_a_and_test_identities(
    fixture: _Fixture,
    field_name: str,
    value: object,
    message: str,
) -> None:
    forged = _forged_pretest(fixture.primary, **{field_name: value})

    with pytest.raises(ValueError, match=message):
        _record(fixture, pretest_freeze=forged)


@pytest.mark.parametrize(
    "failure_split",
    [SplitLabel.TRAIN, SplitLabel.VALIDATION, SplitLabel.CALIBRATION],
)
def test_non_test_failure_split_is_rejected(
    fixture: _Fixture,
    failure_split: SplitLabel,
) -> None:
    with pytest.raises(ValueError, match="TEST_ID"):
        _record(fixture, failure_split=failure_split)


def test_failure_location_requires_exact_enum_types(fixture: _Fixture) -> None:
    with pytest.raises(TypeError, match="failure_split"):
        record_prediction_evaluation_failure(
            state=fixture.spent,
            pretest_freeze=fixture.primary,
            failure_split="TEST_ID",  # type: ignore[arg-type]
            failure_action_kind=OfficialTestExecutionKind.FORECAST_GENERATION,
            failure_reason="synthetic failure",
        )
    with pytest.raises(TypeError, match="failure_action_kind"):
        record_prediction_evaluation_failure(
            state=fixture.spent,
            pretest_freeze=fixture.primary,
            failure_split=SplitLabel.TEST_ID,
            failure_action_kind="FORECAST_GENERATION",  # type: ignore[arg-type]
            failure_reason="synthetic failure",
        )


@pytest.mark.parametrize("failure_reason", ["", " ", "\t\n"])
def test_empty_failure_reason_is_rejected(
    fixture: _Fixture,
    failure_reason: str,
) -> None:
    with pytest.raises(ValueError, match="failure_reason"):
        _record(fixture, failure_reason=failure_reason)


@pytest.mark.parametrize("failure_reason", [None, 1, object()])
def test_failure_reason_requires_string(fixture: _Fixture, failure_reason: object) -> None:
    with pytest.raises(TypeError, match="failure_reason"):
        record_prediction_evaluation_failure(
            state=fixture.spent,
            pretest_freeze=fixture.primary,
            failure_split=SplitLabel.TEST_ID,
            failure_action_kind=OfficialTestExecutionKind.FORECAST_GENERATION,
            failure_reason=failure_reason,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    "field_name",
    [
        "sealed_evaluation_state_sha256",
        "pretraining_freeze_sha256",
        "pretest_freeze_sha256",
        "evaluation_plan_sha256",
        "official_failure_state_plan_sha256",
    ],
)
@pytest.mark.parametrize("value", ["A" * 64, "a" * 63, "g" * 64, None])
def test_direct_record_requires_exact_lowercase_sha_fields(
    fixture: _Fixture,
    field_name: str,
    value: object,
) -> None:
    failure = _record(fixture)

    with pytest.raises(ValueError, match="SHA-256"):
        _direct_changes(failure, **{field_name: value})


@pytest.mark.parametrize(
    "registered",
    [(), ("a" * 64, "a" * 64), ("invalid",)],
)
def test_direct_record_validates_registered_freezes(
    fixture: _Fixture,
    registered: tuple[str, ...],
) -> None:
    failure = _record(fixture)

    with pytest.raises(ValueError):
        _direct_changes(failure, registered_pretest_freeze_sha256s=registered)


def test_direct_record_requires_failure_and_first_exposure_to_be_registered(
    fixture: _Fixture,
) -> None:
    failure = _record(fixture)
    only_secondary = (fixture.secondary.sha256,)
    with pytest.raises(ValueError, match="pretest_freeze_sha256"):
        _direct_changes(
            failure,
            registered_pretest_freeze_sha256s=only_secondary,
        )

    unknown_first = FirstOfficialTestExecution(
        "b" * 64,
        SplitLabel.TEST_ID,
        OfficialTestExecutionKind.FORECAST_GENERATION,
    )
    with pytest.raises(ValueError, match="first official execution"):
        _direct_changes(failure, first_official_test_execution=unknown_first)


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("test_id_trace_ids", ()),
        ("test_ood_trace_ids", ()),
        ("test_id_trace_ids", ("duplicate", "duplicate")),
        ("test_ood_trace_ids", ("duplicate", "duplicate")),
        ("test_id_trace_ids", ("shared",)),
    ],
)
def test_direct_record_validates_test_identity_collections(
    fixture: _Fixture,
    field_name: str,
    value: tuple[str, ...],
) -> None:
    failure = _record(fixture)
    changes: dict[str, object] = {field_name: value}
    if value == ("shared",):
        changes["test_ood_trace_ids"] = ("shared",)

    with pytest.raises(ValueError):
        _direct_changes(failure, **changes)


def test_direct_record_requires_exact_first_execution_type(fixture: _Fixture) -> None:
    failure = _record(fixture)

    with pytest.raises(TypeError, match="first_official_test_execution"):
        _direct_changes(failure, first_official_test_execution=None)


def test_failure_record_is_frozen_slotted_and_identity_only(fixture: _Fixture) -> None:
    failure = _record(fixture)
    field_names = [item.name for item in fields(failure)]

    assert not hasattr(failure, "__dict__")
    assert field_names == [
        "sealed_evaluation_state_sha256",
        "pretraining_freeze_sha256",
        "registered_pretest_freeze_sha256s",
        "pretest_freeze_sha256",
        "evaluation_plan_sha256",
        "official_failure_state_plan_sha256",
        "test_id_trace_ids",
        "test_ood_trace_ids",
        "first_official_test_execution",
        "failure_split",
        "failure_action_kind",
        "failure_reason",
    ]
    forbidden_fields = {
        "schema",
        "version",
        "sha256",
        "artifact_path",
        "serialization_version",
        "test_algorithm_mse",
        "test_algorithm_rmse",
        "baseline_mse",
        "baseline_rmse",
        "delta_rmse",
        "ci_lower",
        "ci_upper",
        "bootstrap_replicates",
        "primary_id_label",
        "forecast",
        "target",
        "prediction",
        "scientific_result",
        "partial_result",
        "replacement_result",
        "timestamp",
        "nonce",
    }
    assert set(field_names).isdisjoint(forbidden_fields)
    with pytest.raises(FrozenInstanceError):
        failure.failure_reason = "changed"  # type: ignore[misc]


def test_direct_constructor_is_structural_and_factory_is_authoritative(
    fixture: _Fixture,
) -> None:
    failure = _record(fixture)
    structurally_valid_but_unbound = replace(
        failure,
        evaluation_plan_sha256=_sha256("not-authoritatively-bound"),
    )
    docstring = inspect.getdoc(PredictionEvaluationFailure)

    assert structurally_valid_but_unbound.evaluation_plan_sha256 != (
        fixture.primary.evaluation_plan_sha256
    )
    assert docstring is not None
    assert "structural consistency" in docstring
    assert "record_prediction_evaluation_failure" in docstring
    assert "authoritative" in docstring


def test_production_source_has_no_execution_payload_persistence_or_rng() -> None:
    production_definitions = (
        PredictionEvaluationFailure,
        record_prediction_evaluation_failure,
    )
    source = "\n".join(inspect.getsource(value) for value in production_definitions)
    forbidden = (
        "PredictionEvaluationFailureKind",
        "EvaluationFailureKind",
        "VerifiedPredictionArtifact",
        "DemandTrace",
        "DemandEvent",
        "PredictionSource",
        ".artifact",
        ".counts",
        ".intensities",
        "PredictionTarget",
        "DemandForecast",
        "PointMetricSummary",
        "LockedTestPointEstimate",
        "PairedTraceBootstrapResult",
        "PrimaryIDInterpretation",
        "PrimaryIDLabel",
        ".predict(",
        "fit_static_train_climatology(",
        "fit_absolute_step_train_climatology(",
        "select_validation_baselines(",
        "select_learned_validation_config(",
        "compute_locked_test_point_estimate(",
        "evaluate_point_forecasts(",
        "bootstrap_locked_test_delta_rmse(",
        "interpret_primary_id_bootstrap(",
        "np.random",
        "numpy.random",
        "default_rng",
        "PCG64",
        "random.Random",
        "torch",
        "datetime",
        "time.time",
        "subprocess",
        "formal_h1",
        "run_formal_h1",
        "open(",
        "write_text(",
        "write_bytes(",
        "json.dump",
        "yaml",
        "np.save",
    )
    forbidden_outcomes = (
        "SUCCESS",
        "PARTIAL_SUCCESS",
        "RETRYABLE",
        "RECOVERED",
        "INCOMPLETE_SUCCESS",
        "NO_CLEAR_DIFFERENCE",
    )

    assert all(token not in source for token in forbidden)
    assert all(token not in source for token in forbidden_outcomes)


def test_no_success_serialization_or_same_set_recovery_api() -> None:
    forbidden_symbols = (
        "PredictionEvaluationSuccess",
        "OfficialEvaluationSuccess",
        "EvaluationCompleted",
        "publish_result",
        "finalize_success",
        "write_prediction_evaluation_failure",
        "read_prediction_evaluation_failure",
        "save_prediction_evaluation_failure",
        "load_prediction_evaluation_failure",
        "recover_prediction_evaluation",
        "retry_prediction_evaluation",
        "retry",
        "rerun",
        "resume",
        "recover",
        "replacement",
        "fallback",
        "drop_failed",
        "smaller_n",
        "impute",
        "fresh_test",
        "unspend",
        "reopen",
        "reset",
    )

    assert all(not hasattr(governance_module, name) for name in forbidden_symbols)
    assert all(not hasattr(prediction_module, name) for name in forbidden_symbols)


def test_factory_signature_has_no_execution_or_result_dependency() -> None:
    signature = inspect.signature(record_prediction_evaluation_failure)

    assert tuple(signature.parameters) == (
        "state",
        "pretest_freeze",
        "failure_split",
        "failure_action_kind",
        "failure_reason",
    )
    assert all(
        parameter.kind is inspect.Parameter.KEYWORD_ONLY
        for parameter in signature.parameters.values()
    )
    for name in ("callback", "result", "success", "complete", "forecast", "target"):
        assert name not in signature.parameters
