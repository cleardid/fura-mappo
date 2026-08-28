from __future__ import annotations

import hashlib
import inspect
from dataclasses import FrozenInstanceError, dataclass, fields, replace
from enum import Enum

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
    PredictionOODKind,
    PredictionSource,
    PreTestFreeze,
    PreTrainingFreeze,
    SealedEvaluationState,
    SplitEntry,
    SplitLabel,
    TraceOODAssignment,
    build_pretest_freeze,
    build_pretraining_freeze,
    build_sealed_evaluation_state,
    preflight_layer_a_b5_support,
    record_first_official_test_execution,
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


def _pretraining_freeze(*, identity_label: str = "layer-a") -> PreTrainingFreeze:
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
        rng_namespace_plan_sha256=_sha256(f"{identity_label}-rng-plan"),
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
    identity_label: str = "primary",
    pretraining_freeze: PreTrainingFreeze | None = None,
) -> PreTestFreeze:
    layer_a = pretraining_freeze or _pretraining_freeze()
    protocol_sha256 = layer_a.primary_protocol.sha256
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
    selected_learned = layer_a.learned_config_identities[0]
    learned_predictors = []
    for training_seed in layer_a.fixed_training_seeds:
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
        pretraining_freeze=layer_a,
        locked_baselines=locked_baselines,
        selected_baseline=BaselineKind.B0,
        selected_learned_config_identity=selected_learned,
        learned_predictor_identities=tuple(learned_predictors),
        predictor_implementation_sha256=predictor_implementation_sha256,
        metric_implementation_sha256=_sha256("metric-implementation"),
        evaluation_plan_sha256=_sha256(f"{identity_label}-evaluation-plan"),
        bootstrap_spec=PredictionBootstrapSpec(200, 17, "linear"),
        bootstrap_implementation_sha256=_sha256("bootstrap-implementation"),
        official_failure_state_plan_sha256=_sha256("failure-state-plan"),
        git_commit_sha="a" * 40,
        runtime_provenance_sha256=_sha256("runtime-provenance"),
    )


@dataclass(frozen=True)
class _Fixture:
    primary: PreTestFreeze
    secondary: PreTestFreeze


@pytest.fixture
def fixture() -> _Fixture:
    primary = _pretest_freeze()
    secondary = replace(
        primary,
        evaluation_plan_sha256=_sha256("secondary-evaluation-plan"),
    )
    return _Fixture(primary, secondary)


def _first_execution(
    freeze: PreTestFreeze,
    *,
    split: SplitLabel = SplitLabel.TEST_ID,
    kind: OfficialTestExecutionKind = OfficialTestExecutionKind.FORECAST_GENERATION,
) -> FirstOfficialTestExecution:
    return FirstOfficialTestExecution(freeze.sha256, split, kind)


def _forged_pretest(
    freeze: PreTestFreeze,
    *,
    label: str,
    **derived_changes: object,
) -> PreTestFreeze:
    forged = replace(
        freeze,
        evaluation_plan_sha256=_sha256(f"{label}-evaluation-plan"),
    )
    for name, value in derived_changes.items():
        object.__setattr__(forged, name, value)
    return forged


def test_public_enums_have_exact_values_and_no_extra_dispositions() -> None:
    assert tuple(Disposition) == (
        Disposition.UNSPENT,
        Disposition.SPENT,
    )
    assert tuple(item.value for item in Disposition) == ("UNSPENT", "SPENT")
    assert tuple(item.value for item in OfficialTestExecutionKind) == (
        "FORECAST_GENERATION",
        "TARGET_RESULT_EVALUATION",
        "METRIC_COMPUTATION",
        "BOOTSTRAP_COMPUTATION",
        "SCIENTIFIC_RESULT_READBACK",
    )
    assert issubclass(Disposition, Enum)
    assert issubclass(Disposition, str)
    assert issubclass(OfficialTestExecutionKind, Enum)
    assert issubclass(OfficialTestExecutionKind, str)


def test_disposition_source_is_a_direct_auditable_enum_declaration() -> None:
    source = inspect.getsource(Disposition)

    assert "class TestSetDisposition(str, Enum):" in source
    assert 'UNSPENT = "UNSPENT"' in source
    assert 'SPENT = "SPENT"' in source
    assert '"UNS" + "PENT"' not in source
    assert '"S" + "PENT"' not in source


def test_public_api_exports_exact_slice_12_governance_surface() -> None:
    expected = {
        "TestSetDisposition": Disposition,
        "OfficialTestExecutionKind": OfficialTestExecutionKind,
        "FirstOfficialTestExecution": FirstOfficialTestExecution,
        "SealedEvaluationState": SealedEvaluationState,
        "build_sealed_evaluation_state": build_sealed_evaluation_state,
        "record_first_official_test_execution": record_first_official_test_execution,
    }
    for name, value in expected.items():
        assert getattr(prediction_module, name) is value
        assert name in prediction_module.__all__


def test_first_execution_is_immutable_test_only_identity(fixture: _Fixture) -> None:
    execution = _first_execution(fixture.primary)

    assert execution.pretest_freeze_sha256 == fixture.primary.sha256
    assert execution.split is SplitLabel.TEST_ID
    assert execution.kind is OfficialTestExecutionKind.FORECAST_GENERATION
    assert not hasattr(execution, "__dict__")
    assert [item.name for item in fields(execution)] == [
        "pretest_freeze_sha256",
        "split",
        "kind",
    ]
    with pytest.raises(FrozenInstanceError):
        execution.kind = OfficialTestExecutionKind.METRIC_COMPUTATION  # type: ignore[misc]


@pytest.mark.parametrize("value", ["A" * 64, "a" * 63, None, 1])
def test_first_execution_requires_exact_lowercase_pretest_sha(value: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        FirstOfficialTestExecution(
            value,  # type: ignore[arg-type]
            SplitLabel.TEST_ID,
            OfficialTestExecutionKind.FORECAST_GENERATION,
        )


@pytest.mark.parametrize(
    "split",
    [SplitLabel.TRAIN, SplitLabel.VALIDATION, SplitLabel.CALIBRATION],
)
def test_non_test_first_execution_split_is_rejected(split: SplitLabel) -> None:
    with pytest.raises(ValueError, match="TEST_ID"):
        FirstOfficialTestExecution(
            "a" * 64,
            split,
            OfficialTestExecutionKind.FORECAST_GENERATION,
        )


def test_first_execution_requires_exact_enum_types() -> None:
    with pytest.raises(TypeError):
        FirstOfficialTestExecution(
            "a" * 64,
            "test_id",  # type: ignore[arg-type]
            OfficialTestExecutionKind.FORECAST_GENERATION,
        )
    with pytest.raises(TypeError):
        FirstOfficialTestExecution(
            "a" * 64,
            SplitLabel.TEST_ID,
            "FORECAST_GENERATION",  # type: ignore[arg-type]
        )


def test_single_freeze_builds_exact_immutable_unspent_state(fixture: _Fixture) -> None:
    state = build_sealed_evaluation_state((fixture.primary,))

    assert state.schema == "fura-mappo.prediction-sealed-evaluation-state"
    assert state.version == 1
    assert state.pretraining_freeze_sha256 == fixture.primary.pretraining_freeze_sha256
    assert state.registered_pretest_freeze_sha256s == (fixture.primary.sha256,)
    assert state.test_id_trace_ids == fixture.primary.test_id_trace_ids
    assert state.test_ood_trace_ids == fixture.primary.test_ood_trace_ids
    assert state.disposition is Disposition.UNSPENT
    assert state.first_official_test_execution is None
    assert len(state.sha256) == 64
    assert not hasattr(state, "__dict__")
    with pytest.raises(FrozenInstanceError):
        state.disposition = Disposition.SPENT  # type: ignore[misc]


def test_multi_freeze_registration_is_canonical_and_order_invariant(
    fixture: _Fixture,
) -> None:
    forward = build_sealed_evaluation_state((fixture.primary, fixture.secondary))
    reverse = build_sealed_evaluation_state((fixture.secondary, fixture.primary))
    expected = tuple(sorted((fixture.primary.sha256, fixture.secondary.sha256)))

    assert forward.registered_pretest_freeze_sha256s == expected
    assert reverse.registered_pretest_freeze_sha256s == expected
    assert forward == reverse
    assert forward.sha256 == reverse.sha256


@pytest.mark.parametrize("value", [(), [], (object(),), None, "not-an-iterable"])
def test_sealed_factory_rejects_empty_or_wrong_input(value: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        build_sealed_evaluation_state(value)  # type: ignore[arg-type]


def test_duplicate_pretest_sha_is_rejected(fixture: _Fixture) -> None:
    with pytest.raises(ValueError, match="唯一"):
        build_sealed_evaluation_state((fixture.primary, fixture.primary))


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("pretraining_freeze_sha256", _sha256("other-layer-a")),
        ("zone_schema_sha256", _sha256("other-zone-schema")),
        ("test_id_trace_ids", ("other_test_id",)),
        ("test_ood_trace_ids", ("other_test_ood",)),
    ],
)
def test_all_registered_freezes_require_exact_shared_layer_a_test_identity(
    fixture: _Fixture,
    field_name: str,
    value: object,
) -> None:
    forged = _forged_pretest(
        fixture.primary,
        label=field_name,
        **{field_name: value},
    )

    with pytest.raises(ValueError, match="Layer-A"):
        build_sealed_evaluation_state((fixture.primary, forged))


@pytest.mark.parametrize(
    ("field_name", "value", "match"),
    [
        ("test_id_trace_ids", (), "都非空"),
        ("test_ood_trace_ids", (), "都非空"),
        ("test_id_trace_ids", ("test_id_a", "test_id_a"), "不得重复"),
        ("test_ood_trace_ids", ("test_ood_a", "test_ood_a"), "不得重复"),
        ("test_ood_trace_ids", ("test_id_a",), "不得重叠"),
    ],
)
def test_factory_rejects_empty_duplicate_or_overlapping_test_identity(
    fixture: _Fixture,
    field_name: str,
    value: tuple[str, ...],
    match: str,
) -> None:
    forged = _forged_pretest(
        fixture.primary,
        label=f"invalid-{field_name}-{value}",
        **{field_name: value},
    )

    with pytest.raises(ValueError, match=match):
        build_sealed_evaluation_state((forged,))


def test_structural_governance_paths_do_not_spend(fixture: _Fixture) -> None:
    state = build_sealed_evaluation_state((fixture.primary, fixture.secondary))
    structural_functions = (
        build_pretraining_freeze,
        preflight_layer_a_b5_support,
        build_pretest_freeze,
        build_sealed_evaluation_state,
    )

    assert state.disposition is Disposition.UNSPENT
    assert state.first_official_test_execution is None
    for function in structural_functions:
        source = inspect.getsource(function)
        assert "record_first_official_test_execution(" not in source
        assert "TestSetDisposition.SPENT" not in source


@pytest.mark.parametrize("kind", tuple(OfficialTestExecutionKind))
def test_each_official_execution_kind_spends_both_test_sets(
    fixture: _Fixture,
    kind: OfficialTestExecutionKind,
) -> None:
    unspent = build_sealed_evaluation_state((fixture.primary, fixture.secondary))
    execution = _first_execution(fixture.primary, kind=kind)
    spent = record_first_official_test_execution(unspent, execution)

    assert unspent.disposition is Disposition.UNSPENT
    assert unspent.first_official_test_execution is None
    assert spent.disposition is Disposition.SPENT
    assert spent.first_official_test_execution is execution
    assert spent.test_id_trace_ids == unspent.test_id_trace_ids
    assert spent.test_ood_trace_ids == unspent.test_ood_trace_ids
    assert spent.registered_pretest_freeze_sha256s == unspent.registered_pretest_freeze_sha256s
    assert spent.sha256 != unspent.sha256


def test_test_ood_first_trigger_spends_the_entire_sealed_phase(fixture: _Fixture) -> None:
    unspent = build_sealed_evaluation_state((fixture.primary, fixture.secondary))
    execution = _first_execution(fixture.secondary, split=SplitLabel.TEST_OOD)
    spent = record_first_official_test_execution(unspent, execution)

    assert spent.disposition is Disposition.SPENT
    assert spent.first_official_test_execution == execution
    assert spent.test_id_trace_ids == unspent.test_id_trace_ids
    assert spent.test_ood_trace_ids == unspent.test_ood_trace_ids
    assert not hasattr(spent, "test_id_disposition")
    assert not hasattr(spent, "test_ood_disposition")


def test_unregistered_pretest_trigger_is_rejected(fixture: _Fixture) -> None:
    state = build_sealed_evaluation_state((fixture.primary,))
    execution = _first_execution(fixture.secondary)

    with pytest.raises(ValueError, match="registered"):
        record_first_official_test_execution(state, execution)


def test_transition_requires_exact_state_and_execution_types(fixture: _Fixture) -> None:
    state = build_sealed_evaluation_state((fixture.primary,))

    with pytest.raises(TypeError):
        record_first_official_test_execution(object(), _first_execution(fixture.primary))  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        record_first_official_test_execution(state, object())  # type: ignore[arg-type]


def test_second_exposure_is_rejected_and_first_exposure_is_retained(
    fixture: _Fixture,
) -> None:
    unspent = build_sealed_evaluation_state((fixture.primary, fixture.secondary))
    first = _first_execution(fixture.primary)
    spent = record_first_official_test_execution(unspent, first)
    second = _first_execution(
        fixture.secondary,
        split=SplitLabel.TEST_OOD,
        kind=OfficialTestExecutionKind.SCIENTIFIC_RESULT_READBACK,
    )

    with pytest.raises(ValueError, match="unexposed"):
        record_first_official_test_execution(spent, second)
    assert spent.first_official_test_execution is first


def test_direct_state_construction_enforces_disposition_relationship(
    fixture: _Fixture,
) -> None:
    unspent = build_sealed_evaluation_state((fixture.primary,))
    first = _first_execution(fixture.primary)

    with pytest.raises(ValueError, match="unexposed"):
        replace(unspent, first_official_test_execution=first)
    with pytest.raises(ValueError, match="exposed"):
        replace(unspent, disposition=Disposition.SPENT)
    with pytest.raises(ValueError, match="registered"):
        replace(
            unspent,
            disposition=Disposition.SPENT,
            first_official_test_execution=_first_execution(fixture.secondary),
        )


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("schema", "wrong-schema"),
        ("version", 2),
        ("disposition", "UNSPENT"),
        ("pretraining_freeze_sha256", "A" * 64),
        ("registered_pretest_freeze_sha256s", ("short",)),
        ("test_id_trace_ids", "test_id_a"),
        ("test_ood_trace_ids", ("bad/path",)),
    ],
)
def test_direct_state_construction_rejects_invalid_structure(
    fixture: _Fixture,
    field_name: str,
    value: object,
) -> None:
    state = build_sealed_evaluation_state((fixture.primary,))

    with pytest.raises((TypeError, ValueError)):
        replace(state, **{field_name: value})


def test_state_hash_is_deterministic_and_sensitive_to_all_locked_identities(
    fixture: _Fixture,
) -> None:
    original = build_sealed_evaluation_state((fixture.primary, fixture.secondary))
    repeated = build_sealed_evaluation_state((fixture.secondary, fixture.primary))
    registered_changed = replace(
        original,
        registered_pretest_freeze_sha256s=(
            original.registered_pretest_freeze_sha256s[0],
            _sha256("other-registered-pretest"),
        ),
    )
    layer_a_changed = replace(
        original,
        pretraining_freeze_sha256=_sha256("other-layer-a"),
    )
    test_id_changed = replace(
        original,
        test_id_trace_ids=tuple(reversed(original.test_id_trace_ids)),
    )
    test_ood_changed = replace(
        original,
        test_ood_trace_ids=tuple(reversed(original.test_ood_trace_ids)),
    )

    assert original.sha256 == repeated.sha256
    assert (
        len(
            {
                original.sha256,
                registered_changed.sha256,
                layer_a_changed.sha256,
                test_id_changed.sha256,
                test_ood_changed.sha256,
            }
        )
        == 5
    )


def test_spent_hash_is_sensitive_to_trigger_freeze_split_and_kind(fixture: _Fixture) -> None:
    unspent = build_sealed_evaluation_state((fixture.primary, fixture.secondary))
    primary_id = record_first_official_test_execution(
        unspent,
        _first_execution(fixture.primary),
    )
    secondary_id = record_first_official_test_execution(
        unspent,
        _first_execution(fixture.secondary),
    )
    primary_ood = record_first_official_test_execution(
        unspent,
        _first_execution(fixture.primary, split=SplitLabel.TEST_OOD),
    )
    primary_metric = record_first_official_test_execution(
        unspent,
        _first_execution(
            fixture.primary,
            kind=OfficialTestExecutionKind.METRIC_COMPUTATION,
        ),
    )

    assert (
        len(
            {
                unspent.sha256,
                primary_id.sha256,
                secondary_id.sha256,
                primary_ood.sha256,
                primary_metric.sha256,
            }
        )
        == 5
    )


def test_state_payload_boundary_contains_only_structural_identities(
    fixture: _Fixture,
) -> None:
    state = build_sealed_evaluation_state((fixture.primary, fixture.secondary))
    assert [item.name for item in fields(state)] == [
        "pretraining_freeze_sha256",
        "registered_pretest_freeze_sha256s",
        "test_id_trace_ids",
        "test_ood_trace_ids",
        "disposition",
        "first_official_test_execution",
        "schema",
        "version",
        "sha256",
    ]
    forbidden = {
        "verified_prediction_artifact",
        "prediction_source",
        "prediction_target",
        "forecast",
        "metric",
        "point_estimate",
        "bootstrap_result",
        "interpretation",
        "scientific_label",
        "timestamp",
        "nonce",
    }
    assert {item.name.lower() for item in fields(state)}.isdisjoint(forbidden)


def test_slice_12_production_source_has_no_scientific_execution_or_payload_access() -> None:
    sources = "\n".join(
        inspect.getsource(value)
        for value in (
            Disposition,
            OfficialTestExecutionKind,
            FirstOfficialTestExecution,
            SealedEvaluationState,
            build_sealed_evaluation_state,
            record_first_official_test_execution,
        )
    )
    forbidden = (
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
        "subprocess",
        "formal_h1",
        "run_formal_h1",
    )
    assert all(token not in sources for token in forbidden)


def test_no_scientific_failure_or_fresh_test_reset_surface() -> None:
    production_source = inspect.getsource(governance_module)
    forbidden_symbols = (
        "PredictionEvaluationFailure",
        "reset",
        "unspend",
        "reopen",
        "clear_spent",
        "mark_unspent",
        "reuse",
        "rearm",
        "add_pretest_freeze",
        "register_pretest_freeze",
        "register_later",
    )

    assert "PREDICTION_" + "EVALUATION_FAILURE" not in production_source
    assert all(not hasattr(governance_module, name) for name in forbidden_symbols)
    assert all(not hasattr(prediction_module, name) for name in forbidden_symbols)
    assert tuple(
        node.__name__
        for node in governance_module.__dict__.values()
        if isinstance(node, type)
        and node.__module__ == governance_module.__name__
        and node.__name__.endswith("Failure")
    ) == ("PreTrainingFreezeFailure",)


def test_transition_signature_has_no_result_or_success_dependency() -> None:
    signature = inspect.signature(record_first_official_test_execution)
    assert tuple(signature.parameters) == ("state", "first_execution")
    assert "result" not in signature.parameters
    assert "success" not in signature.parameters
    assert "failure" not in signature.parameters


def test_direct_construction_and_official_factories_document_trust_boundaries() -> None:
    state_docstring = inspect.getdoc(SealedEvaluationState)
    build_docstring = inspect.getdoc(build_sealed_evaluation_state)
    transition_docstring = inspect.getdoc(record_first_official_test_execution)

    assert state_docstring is not None
    assert "structural consistency" in state_docstring
    assert "build_sealed_evaluation_state" in state_docstring
    assert "record_first_official_test_execution" in state_docstring
    assert build_docstring is not None and "trust boundary" in build_docstring
    assert transition_docstring is not None and "不运行 action" in transition_docstring
