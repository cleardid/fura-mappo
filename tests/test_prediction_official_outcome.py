from __future__ import annotations

import ast
import inspect
import math
from collections.abc import Iterator, Mapping
from dataclasses import FrozenInstanceError, dataclass, fields, replace
from pathlib import Path

import numpy as np
import pytest

import fura_mappo.prediction as prediction_module
import fura_mappo.prediction.official_outcome as outcome_module
from fura_mappo.prediction import (
    BaselineKind,
    BaselineSelectionResult,
    ForecastRecord,
    OfficialPredictionEvaluationResult,
    OfficialTestExecutionKind,
    PredictionBootstrapSpec,
    PredictionEvaluationFailure,
    SplitLabel,
    bootstrap_locked_test_delta_rmse,
    build_sealed_evaluation_state,
    finalize_official_prediction_evaluation,
    interpret_primary_id_bootstrap,
    record_first_official_test_execution,
)
from fura_mappo.prediction.governance import FirstOfficialTestExecution
from fura_mappo.prediction.governance import TestSetDisposition as Disposition
from tests.test_prediction_official_metrics import (
    _Fixture as _MetricsFixture,
)
from tests.test_prediction_official_metrics import (
    _make_fixture as _make_metrics_fixture,
)
from tests.test_prediction_official_metrics import _validation_metrics

_BASELINE_ORDER = tuple(BaselineKind)
_MISSING = object()


def _raw_records(bundle: object) -> tuple[ForecastRecord, ...]:
    return tuple(
        ForecastRecord(record.point_record.forecast, record.provenance)
        for record in bundle.records  # type: ignore[attr-defined]
    )


@dataclass(frozen=True)
class _Fixture:
    metrics: _MetricsFixture
    test_id_baselines: dict[BaselineKind, tuple[ForecastRecord, ...]]
    test_ood_baselines: dict[BaselineKind, tuple[ForecastRecord, ...]]
    test_id_learned: dict[int, tuple[ForecastRecord, ...]]
    test_ood_learned: dict[int, tuple[ForecastRecord, ...]]


def _outcome_fixture(metrics: _MetricsFixture) -> _Fixture:
    return _Fixture(
        metrics=metrics,
        test_id_baselines={
            bundle.baseline: _raw_records(bundle)
            for bundle in metrics.test_id_baselines
            if bundle.baseline is not None
        },
        test_ood_baselines={
            bundle.baseline: _raw_records(bundle)
            for bundle in metrics.test_ood_baselines
            if bundle.baseline is not None
        },
        test_id_learned={
            bundle.training_seed: _raw_records(bundle)
            for bundle in metrics.test_id_learned
            if bundle.training_seed is not None
        },
        test_ood_learned={
            bundle.training_seed: _raw_records(bundle)
            for bundle in metrics.test_ood_learned
            if bundle.training_seed is not None
        },
    )


@pytest.fixture(scope="module")
def fixture(tmp_path_factory: pytest.TempPathFactory) -> _Fixture:
    return _outcome_fixture(_make_metrics_fixture(tmp_path_factory.mktemp("official-outcome")))


def _finalize(
    fixture: _Fixture,
    *,
    state: object = _MISSING,
    pretest_freeze: object = _MISSING,
    baseline_selection: object = _MISSING,
    learned_selection: object = _MISSING,
    test_id_artifacts: object = _MISSING,
    test_ood_artifacts: object = _MISSING,
    test_id_baselines: object = _MISSING,
    test_ood_baselines: object = _MISSING,
    test_id_learned: object = _MISSING,
    test_ood_learned: object = _MISSING,
) -> OfficialPredictionEvaluationResult | PredictionEvaluationFailure:
    metrics = fixture.metrics
    return finalize_official_prediction_evaluation(
        state=metrics.spent if state is _MISSING else state,  # type: ignore[arg-type]
        pretest_freeze=(metrics.pretest if pretest_freeze is _MISSING else pretest_freeze),  # type: ignore[arg-type]
        baseline_selection=(
            metrics.baseline_selection if baseline_selection is _MISSING else baseline_selection
        ),  # type: ignore[arg-type]
        learned_selection=(
            metrics.learned_selection if learned_selection is _MISSING else learned_selection
        ),  # type: ignore[arg-type]
        test_id_artifacts=(
            metrics.test_id_artifacts if test_id_artifacts is _MISSING else test_id_artifacts
        ),  # type: ignore[arg-type]
        test_ood_artifacts=(
            metrics.test_ood_artifacts if test_ood_artifacts is _MISSING else test_ood_artifacts
        ),  # type: ignore[arg-type]
        test_id_baseline_forecast_records=(
            fixture.test_id_baselines if test_id_baselines is _MISSING else test_id_baselines
        ),  # type: ignore[arg-type]
        test_ood_baseline_forecast_records=(
            fixture.test_ood_baselines if test_ood_baselines is _MISSING else test_ood_baselines
        ),  # type: ignore[arg-type]
        test_id_learned_forecast_records=(
            fixture.test_id_learned if test_id_learned is _MISSING else test_id_learned
        ),  # type: ignore[arg-type]
        test_ood_learned_forecast_records=(
            fixture.test_ood_learned if test_ood_learned is _MISSING else test_ood_learned
        ),  # type: ignore[arg-type]
    )


def _forge(value: object, **changes: object) -> object:
    forged = replace(value)  # type: ignore[type-var]
    for name, replacement in changes.items():
        object.__setattr__(forged, name, replacement)
    return forged


def _result_fields(
    result: OfficialPredictionEvaluationResult,
) -> dict[str, object]:
    return {field.name: getattr(result, field.name) for field in fields(result)}


def _assert_failure(
    value: object,
    *,
    split: SplitLabel,
    action: OfficialTestExecutionKind,
    phase: str,
) -> PredictionEvaluationFailure:
    assert isinstance(value, PredictionEvaluationFailure)
    assert value.failure_split is split
    assert value.failure_action_kind is action
    assert value.failure_reason.startswith(f"{phase}: ")
    return value


def _replace_ood_error(
    mapping: dict[object, tuple[ForecastRecord, ...]],
    delta: float,
) -> dict[object, tuple[ForecastRecord, ...]]:
    changed: dict[object, tuple[ForecastRecord, ...]] = {}
    for key, records in mapping.items():
        replacements = []
        for record in records:
            mean = record.forecast.mean.copy()
            mean[record.forecast.valid_mask] += delta
            forecast = replace(record.forecast, mean=mean)
            replacements.append(replace(record, forecast=forecast))
        changed[key] = tuple(replacements)
    return changed


def test_success_constructs_complete_factory_only_chain(fixture: _Fixture) -> None:
    before_state = (
        fixture.metrics.spent.sha256,
        fixture.metrics.spent.disposition,
        fixture.metrics.spent.first_official_test_execution,
        fixture.metrics.spent.registered_pretest_freeze_sha256s,
        fixture.metrics.spent.test_id_trace_ids,
        fixture.metrics.spent.test_ood_trace_ids,
    )
    result = _finalize(fixture)

    assert isinstance(result, OfficialPredictionEvaluationResult)
    assert result.state is fixture.metrics.spent
    assert result.pretest_freeze is fixture.metrics.pretest
    assert (
        tuple(item.forecasts.baseline for item in result.point_metrics.test_id_baselines)
        == _BASELINE_ORDER
    )
    assert (
        tuple(item.forecasts.baseline for item in result.point_metrics.test_ood_baselines)
        == _BASELINE_ORDER
    )
    assert tuple(item.forecasts.training_seed for item in result.point_metrics.test_id_learned) == (
        1,
        2,
        3,
    )
    assert tuple(
        item.forecasts.training_seed for item in result.point_metrics.test_ood_learned
    ) == (1, 2, 3)
    assert result.point_estimate.baseline_metrics is (
        result.point_metrics.selected_baseline_test_id.metrics
    )
    assert result.bootstrap_result.point_estimate is result.point_estimate
    assert result.bootstrap_result.spec is fixture.metrics.pretest.bootstrap_spec
    assert result.interpretation.bootstrap_result is result.bootstrap_result
    assert result.label is result.interpretation.label
    assert result.delta_rmse == result.point_estimate.delta_rmse
    assert result.ci_lower == result.bootstrap_result.ci_lower
    assert result.ci_upper == result.bootstrap_result.ci_upper
    assert result.selected_baseline is BaselineKind.B2
    assert not hasattr(result, "__dict__")
    assert (
        fixture.metrics.spent.sha256,
        fixture.metrics.spent.disposition,
        fixture.metrics.spent.first_official_test_execution,
        fixture.metrics.spent.registered_pretest_freeze_sha256s,
        fixture.metrics.spent.test_id_trace_ids,
        fixture.metrics.spent.test_ood_trace_ids,
    ) == before_state
    with pytest.raises(FrozenInstanceError):
        result.point_estimate = result.point_estimate  # type: ignore[misc]


def test_fixed_seed_estimand_and_diagnostic_vector_are_exact(fixture: _Fixture) -> None:
    result = _finalize(fixture)
    assert isinstance(result, OfficialPredictionEvaluationResult)
    metrics_by_seed = {
        item.forecasts.training_seed: item.metrics for item in result.point_metrics.test_id_learned
    }
    expected = tuple(
        (seed, metrics_by_seed[seed].primary_mse, metrics_by_seed[seed].primary_rmse)
        for seed in fixture.metrics.pretraining.fixed_training_seeds
    )
    assert result.per_seed_test_diagnostics == expected
    mean_mse = math.fsum(item[1] for item in expected) / len(expected)
    mean_rmse = math.fsum(item[2] for item in expected) / len(expected)
    assert result.test_algorithm_mse == pytest.approx(mean_mse)
    assert result.test_algorithm_rmse == pytest.approx(math.sqrt(mean_mse))
    assert result.test_algorithm_rmse != pytest.approx(mean_rmse)
    assert result.baseline_mse == result.point_estimate.baseline_mse
    assert result.baseline_rmse == result.point_estimate.baseline_rmse


def test_bootstrap_and_label_exactly_reuse_accepted_paths(fixture: _Fixture) -> None:
    result = _finalize(fixture)
    assert isinstance(result, OfficialPredictionEvaluationResult)
    independent = bootstrap_locked_test_delta_rmse(
        result.point_estimate,
        fixture.metrics.pretest.bootstrap_spec,
    )
    np.testing.assert_array_equal(
        result.bootstrap_result.delta_rmse_replicates,
        independent.delta_rmse_replicates,
    )
    assert result.ci_lower == independent.ci_lower
    assert result.ci_upper == independent.ci_upper
    assert result.label is interpret_primary_id_bootstrap(independent).label


def test_layer_b_provenance_properties_are_exact_proxies(fixture: _Fixture) -> None:
    result = _finalize(fixture)
    assert isinstance(result, OfficialPredictionEvaluationResult)
    for name in (
        "evaluation_plan_sha256",
        "predictor_implementation_sha256",
        "metric_implementation_sha256",
        "bootstrap_implementation_sha256",
        "official_failure_state_plan_sha256",
        "git_commit_sha",
        "runtime_provenance_sha256",
    ):
        assert getattr(result, name) == getattr(fixture.metrics.pretest, name)


def test_finalizer_does_not_mutate_selections_or_raw_records(fixture: _Fixture) -> None:
    baseline_selection = fixture.metrics.baseline_selection
    learned_selection = fixture.metrics.learned_selection
    raw_records = tuple(
        record
        for mapping in (
            fixture.test_id_baselines,
            fixture.test_id_learned,
            fixture.test_ood_baselines,
            fixture.test_ood_learned,
        )
        for records in mapping.values()
        for record in records
    )
    raw_ids = tuple(id(record) for record in raw_records)
    raw_means = tuple(record.forecast.mean.tobytes() for record in raw_records)
    result = _finalize(fixture)
    assert isinstance(result, OfficialPredictionEvaluationResult)
    assert fixture.metrics.baseline_selection is baseline_selection
    assert fixture.metrics.learned_selection is learned_selection
    assert tuple(id(record) for record in raw_records) == raw_ids
    assert tuple(record.forecast.mean.tobytes() for record in raw_records) == raw_means


def test_ood_changes_cannot_rescue_or_alter_primary_inference(fixture: _Fixture) -> None:
    original = _finalize(fixture)
    changed = _finalize(
        fixture,
        test_ood_baselines=_replace_ood_error(fixture.test_ood_baselines, 7.0),
        test_ood_learned=_replace_ood_error(fixture.test_ood_learned, 11.0),
    )
    assert isinstance(original, OfficialPredictionEvaluationResult)
    assert isinstance(changed, OfficialPredictionEvaluationResult)
    assert changed.test_algorithm_mse == original.test_algorithm_mse
    assert changed.test_algorithm_rmse == original.test_algorithm_rmse
    assert changed.baseline_rmse == original.baseline_rmse
    assert changed.delta_rmse == original.delta_rmse
    np.testing.assert_array_equal(
        changed.bootstrap_result.delta_rmse_replicates,
        original.bootstrap_result.delta_rmse_replicates,
    )
    assert (changed.ci_lower, changed.ci_upper, changed.label) == (
        original.ci_lower,
        original.ci_upper,
        original.label,
    )
    assert (
        changed.point_metrics.test_ood_learned[0].metrics.primary_mse
        != original.point_metrics.test_ood_learned[0].metrics.primary_mse
    )


def test_validation_locked_b3_is_not_reselected_using_test_rmse(fixture: _Fixture) -> None:
    metrics = fixture.metrics
    validation_source = next(
        entry.source
        for entry in metrics.pretraining.split_manifest.entries
        if entry.split is SplitLabel.VALIDATION
    )
    values = {
        BaselineKind.B0: 4.0,
        BaselineKind.B1: 3.0,
        BaselineKind.B2: 2.0,
        BaselineKind.B3: 0.25,
        BaselineKind.B4: 5.0,
        BaselineKind.B5: 6.0,
    }
    candidates = tuple(
        replace(
            candidate,
            metrics=_validation_metrics(validation_source, values[candidate.baseline]),
        )
        for candidate in metrics.baseline_selection.locked_variants
    )
    baseline_selection = BaselineSelectionResult(
        locked_variants=candidates,
        selected=candidates[3],
        validation_trace_signature=metrics.baseline_selection.validation_trace_signature,
        prediction_horizon=metrics.baseline_selection.prediction_horizon,
        num_zones=metrics.baseline_selection.num_zones,
        zone_schema_sha256=metrics.baseline_selection.zone_schema_sha256,
    )
    pretest = replace(metrics.pretest, selected_baseline=BaselineKind.B3)
    unspent = build_sealed_evaluation_state((pretest,))
    spent = record_first_official_test_execution(
        unspent,
        FirstOfficialTestExecution(
            pretest.sha256,
            SplitLabel.TEST_ID,
            OfficialTestExecutionKind.METRIC_COMPUTATION,
        ),
    )
    b5_records = tuple(
        ForecastRecord(b0.forecast, b5.provenance)
        for b0, b5 in zip(
            fixture.test_id_baselines[BaselineKind.B0],
            fixture.test_id_baselines[BaselineKind.B5],
            strict=True,
        )
    )
    id_baselines = dict(fixture.test_id_baselines)
    id_baselines[BaselineKind.B5] = b5_records
    result = _finalize(
        fixture,
        state=spent,
        pretest_freeze=pretest,
        baseline_selection=baseline_selection,
        test_id_baselines=id_baselines,
    )
    assert isinstance(result, OfficialPredictionEvaluationResult)
    b5_metrics = result.point_metrics.test_id_baselines[5].metrics
    assert b5_metrics.primary_rmse < result.baseline_rmse
    assert result.selected_baseline is BaselineKind.B3
    assert result.point_estimate.baseline_metrics is (
        result.point_metrics.test_id_baselines[3].metrics
    )


class _CanaryMapping(Mapping[object, object]):
    def __init__(self) -> None:
        self.accesses = 0

    def __getitem__(self, key: object) -> object:
        self.accesses += 1
        raise AssertionError("mapping value must not be accessed")

    def __iter__(self) -> Iterator[object]:
        self.accesses += 1
        raise AssertionError("mapping must not be iterated")

    def __len__(self) -> int:
        self.accesses += 1
        raise AssertionError("mapping length must not be read")


def _forbidden_iterable(counter: list[int]) -> Iterator[object]:
    counter[0] += 1
    raise AssertionError("artifact inventory must not be iterated")
    yield object()


@pytest.mark.parametrize("missing_first", [False, True])
def test_unspent_admission_rejects_before_all_raw_or_downstream_access(
    fixture: _Fixture,
    monkeypatch: pytest.MonkeyPatch,
    missing_first: bool,
) -> None:
    artifact_accesses = [0]
    canaries = tuple(_CanaryMapping() for _ in range(4))
    downstream_calls = [0]

    def forbidden(*args: object, **kwargs: object) -> object:
        downstream_calls[0] += 1
        raise AssertionError("downstream call must not run")

    for name in (
        "bind_official_baseline_split_forecasts",
        "bind_official_learned_split_forecasts",
        "evaluate_official_sealed_point_metrics",
        "compute_official_mandatory_breakdowns",
        "compute_locked_test_point_estimate",
        "bootstrap_locked_test_delta_rmse",
        "interpret_primary_id_bootstrap",
        "record_prediction_evaluation_failure",
    ):
        monkeypatch.setattr(outcome_module, name, forbidden)
    state = fixture.metrics.unspent
    if missing_first:
        state = _forge(state, disposition=Disposition.SPENT)  # type: ignore[assignment]
    with pytest.raises(ValueError):
        finalize_official_prediction_evaluation(
            state=state,
            pretest_freeze=fixture.metrics.pretest,
            baseline_selection=fixture.metrics.baseline_selection,
            learned_selection=fixture.metrics.learned_selection,
            test_id_artifacts=_forbidden_iterable(artifact_accesses),
            test_ood_artifacts=_forbidden_iterable(artifact_accesses),
            test_id_baseline_forecast_records=canaries[0],
            test_ood_baseline_forecast_records=canaries[1],
            test_id_learned_forecast_records=canaries[2],
            test_ood_learned_forecast_records=canaries[3],
        )
    assert artifact_accesses == [0]
    assert sum(canary.accesses for canary in canaries) == 0
    assert downstream_calls == [0]


def _raising_records() -> Iterator[ForecastRecord]:
    raise RuntimeError("synthetic raw readback failure")
    yield  # type: ignore[misc]


@pytest.mark.parametrize(
    ("case", "expected_split", "expected_phase"),
    [
        ("id_missing_b5", SplitLabel.TEST_ID, "RAW_FORECAST_INVENTORY"),
        ("ood_missing_b3", SplitLabel.TEST_OOD, "RAW_FORECAST_INVENTORY"),
        ("id_extra_baseline", SplitLabel.TEST_ID, "RAW_FORECAST_INVENTORY"),
        ("id_missing_seed", SplitLabel.TEST_ID, "RAW_FORECAST_INVENTORY"),
        ("ood_extra_seed", SplitLabel.TEST_OOD, "RAW_FORECAST_INVENTORY"),
        ("id_wrong_seed", SplitLabel.TEST_ID, "RAW_FORECAST_INVENTORY"),
        ("id_non_record", SplitLabel.TEST_ID, "RAW_FORECAST_READBACK"),
        ("ood_iterator_error", SplitLabel.TEST_OOD, "RAW_FORECAST_READBACK"),
    ],
)
def test_raw_inventory_failures_are_terminal_before_binding(
    fixture: _Fixture,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
    expected_split: SplitLabel,
    expected_phase: str,
) -> None:
    id_baselines: dict[object, object] = dict(fixture.test_id_baselines)
    ood_baselines: dict[object, object] = dict(fixture.test_ood_baselines)
    id_learned: dict[object, object] = dict(fixture.test_id_learned)
    ood_learned: dict[object, object] = dict(fixture.test_ood_learned)
    if case == "id_missing_b5":
        id_baselines.pop(BaselineKind.B5)
    elif case == "ood_missing_b3":
        ood_baselines.pop(BaselineKind.B3)
    elif case == "id_extra_baseline":
        id_baselines["B6"] = ()
    elif case == "id_missing_seed":
        id_learned.pop(2)
    elif case == "ood_extra_seed":
        ood_learned[999] = ()
    elif case == "id_wrong_seed":
        id_learned[-1] = id_learned.pop(2)
    elif case == "id_non_record":
        id_baselines[BaselineKind.B0] = (object(),)
    else:
        ood_learned[3] = _raising_records()
    binding_calls = [0]

    def forbidden(*args: object, **kwargs: object) -> object:
        binding_calls[0] += 1
        raise AssertionError("binding must not run")

    monkeypatch.setattr(outcome_module, "bind_official_baseline_split_forecasts", forbidden)
    monkeypatch.setattr(outcome_module, "bind_official_learned_split_forecasts", forbidden)
    result = _finalize(
        fixture,
        test_id_baselines=id_baselines,
        test_ood_baselines=ood_baselines,
        test_id_learned=id_learned,
        test_ood_learned=ood_learned,
    )
    _assert_failure(
        result,
        split=expected_split,
        action=OfficialTestExecutionKind.SCIENTIFIC_RESULT_READBACK,
        phase=expected_phase,
    )
    assert binding_calls == [0]


@pytest.mark.parametrize(
    ("split", "value"),
    [
        (SplitLabel.TEST_ID, (object(),)),
        (SplitLabel.TEST_OOD, (object(),)),
        (SplitLabel.TEST_ID, _raising_records()),
        (SplitLabel.TEST_OOD, _raising_records()),
    ],
)
def test_artifact_materialization_failure_mapping(
    fixture: _Fixture,
    monkeypatch: pytest.MonkeyPatch,
    split: SplitLabel,
    value: object,
) -> None:
    calls = [0]

    def forbidden(*args: object, **kwargs: object) -> object:
        calls[0] += 1
        raise AssertionError("binding must not run")

    monkeypatch.setattr(outcome_module, "bind_official_baseline_split_forecasts", forbidden)
    result = _finalize(
        fixture,
        test_id_artifacts=value if split is SplitLabel.TEST_ID else _MISSING,
        test_ood_artifacts=value if split is SplitLabel.TEST_OOD else _MISSING,
    )
    _assert_failure(
        result,
        split=split,
        action=OfficialTestExecutionKind.TARGET_RESULT_EVALUATION,
        phase="VERIFIED_ARTIFACT_READBACK",
    )
    assert calls == [0]


@pytest.mark.parametrize(
    ("defect", "failure_call", "expected_split"),
    [
        ("wrong predictor SHA", 1, SplitLabel.TEST_ID),
        ("wrong protocol SHA", 6, SplitLabel.TEST_ID),
        ("wrong manifest SHA", 7, SplitLabel.TEST_ID),
        ("fabricated sample/provenance mismatch", 9, SplitLabel.TEST_ID),
        ("missing forecast record", 10, SplitLabel.TEST_OOD),
        ("probabilistic forecast payload", 15, SplitLabel.TEST_OOD),
    ],
)
def test_slice14_rejections_stop_all_scientific_stages(
    fixture: _Fixture,
    monkeypatch: pytest.MonkeyPatch,
    defect: str,
    failure_call: int,
    expected_split: SplitLabel,
) -> None:
    original_baseline = outcome_module.bind_official_baseline_split_forecasts
    original_learned = outcome_module.bind_official_learned_split_forecasts
    binding_calls = [0]
    scientific_calls = [0]

    def maybe_fail_baseline(*args: object, **kwargs: object) -> object:
        binding_calls[0] += 1
        if binding_calls[0] == failure_call:
            raise ValueError(f"synthetic Slice14 rejection: {defect}")
        return original_baseline(*args, **kwargs)

    def maybe_fail_learned(*args: object, **kwargs: object) -> object:
        binding_calls[0] += 1
        if binding_calls[0] == failure_call:
            raise ValueError(f"synthetic Slice14 rejection: {defect}")
        return original_learned(*args, **kwargs)

    def forbidden(*args: object, **kwargs: object) -> object:
        scientific_calls[0] += 1
        raise AssertionError("scientific stage must not run")

    monkeypatch.setattr(
        outcome_module,
        "bind_official_baseline_split_forecasts",
        maybe_fail_baseline,
    )
    monkeypatch.setattr(
        outcome_module,
        "bind_official_learned_split_forecasts",
        maybe_fail_learned,
    )
    for name in (
        "evaluate_official_sealed_point_metrics",
        "compute_official_mandatory_breakdowns",
        "compute_locked_test_point_estimate",
        "bootstrap_locked_test_delta_rmse",
        "interpret_primary_id_bootstrap",
    ):
        monkeypatch.setattr(outcome_module, name, forbidden)
    result = _finalize(fixture)
    _assert_failure(
        result,
        split=expected_split,
        action=OfficialTestExecutionKind.TARGET_RESULT_EVALUATION,
        phase="SLICE14_FORECAST_BINDING",
    )
    assert scientific_calls == [0]


@pytest.mark.parametrize(
    (
        "failing_name",
        "downstream_names",
        "split",
        "action",
        "phase",
    ),
    [
        (
            "evaluate_official_sealed_point_metrics",
            (
                "compute_official_mandatory_breakdowns",
                "compute_locked_test_point_estimate",
                "bootstrap_locked_test_delta_rmse",
                "interpret_primary_id_bootstrap",
            ),
            SplitLabel.TEST_ID,
            OfficialTestExecutionKind.METRIC_COMPUTATION,
            "SEALED_METRICS_CROSS_SPLIT",
        ),
        (
            "compute_official_mandatory_breakdowns",
            (
                "compute_locked_test_point_estimate",
                "bootstrap_locked_test_delta_rmse",
                "interpret_primary_id_bootstrap",
            ),
            SplitLabel.TEST_ID,
            OfficialTestExecutionKind.METRIC_COMPUTATION,
            "MANDATORY_BREAKDOWNS_CROSS_SPLIT",
        ),
        (
            "compute_locked_test_point_estimate",
            ("bootstrap_locked_test_delta_rmse", "interpret_primary_id_bootstrap"),
            SplitLabel.TEST_ID,
            OfficialTestExecutionKind.METRIC_COMPUTATION,
            "PRIMARY_ID_POINT_ESTIMATE",
        ),
        (
            "bootstrap_locked_test_delta_rmse",
            ("interpret_primary_id_bootstrap",),
            SplitLabel.TEST_ID,
            OfficialTestExecutionKind.BOOTSTRAP_COMPUTATION,
            "PRIMARY_ID_BOOTSTRAP",
        ),
        (
            "interpret_primary_id_bootstrap",
            (),
            SplitLabel.TEST_ID,
            OfficialTestExecutionKind.SCIENTIFIC_RESULT_READBACK,
            "PRIMARY_ID_INTERPRETATION",
        ),
    ],
)
def test_each_scientific_phase_has_terminal_failure_handoff(
    fixture: _Fixture,
    monkeypatch: pytest.MonkeyPatch,
    failing_name: str,
    downstream_names: tuple[str, ...],
    split: SplitLabel,
    action: OfficialTestExecutionKind,
    phase: str,
) -> None:
    downstream_calls = [0]

    def fail(*args: object, **kwargs: object) -> object:
        raise ValueError("synthetic phase failure")

    def forbidden(*args: object, **kwargs: object) -> object:
        downstream_calls[0] += 1
        raise AssertionError("downstream stage must not run")

    monkeypatch.setattr(outcome_module, failing_name, fail)
    for name in downstream_names:
        monkeypatch.setattr(outcome_module, name, forbidden)
    result = _finalize(fixture)
    _assert_failure(result, split=split, action=action, phase=phase)
    assert downstream_calls == [0]


def test_failure_recorder_failure_propagates_without_retry(
    fixture: _Fixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = [0]

    def fail_metrics(*args: object, **kwargs: object) -> object:
        raise ValueError("metric failure")

    def fail_recorder(*args: object, **kwargs: object) -> object:
        calls[0] += 1
        raise RuntimeError("recorder unavailable")

    monkeypatch.setattr(outcome_module, "evaluate_official_sealed_point_metrics", fail_metrics)
    monkeypatch.setattr(outcome_module, "record_prediction_evaluation_failure", fail_recorder)
    with pytest.raises(RuntimeError, match="recorder unavailable"):
        _finalize(fixture)
    assert calls == [1]


@pytest.mark.parametrize("exception", [KeyboardInterrupt(), SystemExit(), GeneratorExit()])
def test_base_exceptions_are_not_converted(
    fixture: _Fixture,
    monkeypatch: pytest.MonkeyPatch,
    exception: BaseException,
) -> None:
    recorder_calls = [0]

    def interrupt(*args: object, **kwargs: object) -> object:
        raise exception

    def recorder(*args: object, **kwargs: object) -> object:
        recorder_calls[0] += 1
        raise AssertionError("recorder must not run")

    monkeypatch.setattr(outcome_module, "evaluate_official_sealed_point_metrics", interrupt)
    monkeypatch.setattr(outcome_module, "record_prediction_evaluation_failure", recorder)
    with pytest.raises(type(exception)):
        _finalize(fixture)
    assert recorder_calls == [0]


def test_regular_runtime_error_is_converted(
    fixture: _Fixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*args: object, **kwargs: object) -> object:
        raise RuntimeError("ordinary exception")

    monkeypatch.setattr(outcome_module, "evaluate_official_sealed_point_metrics", fail)
    result = _finalize(fixture)
    failure = _assert_failure(
        result,
        split=SplitLabel.TEST_ID,
        action=OfficialTestExecutionKind.METRIC_COMPUTATION,
        phase="SEALED_METRICS_CROSS_SPLIT",
    )
    assert "RuntimeError: ordinary exception" in failure.failure_reason


def test_final_result_is_factory_only_and_token_is_private(fixture: _Fixture) -> None:
    result = _finalize(fixture)
    assert isinstance(result, OfficialPredictionEvaluationResult)
    with pytest.raises(TypeError, match="finalize_official_prediction_evaluation"):
        OfficialPredictionEvaluationResult(**_result_fields(result))
    assert not hasattr(prediction_module, "_OFFICIAL_RESULT_TOKEN")
    assert "_OFFICIAL_RESULT_TOKEN" not in prediction_module.__all__


def test_internal_token_rejects_inconsistent_chain(fixture: _Fixture) -> None:
    first = _finalize(fixture)
    second = _finalize(fixture)
    assert isinstance(first, OfficialPredictionEvaluationResult)
    assert isinstance(second, OfficialPredictionEvaluationResult)
    token = outcome_module._OFFICIAL_RESULT_TOKEN
    cases: list[dict[str, object]] = []
    cases.append({"state": fixture.metrics.unspent})
    cases.append(
        {
            "pretest_freeze": replace(
                fixture.metrics.pretest,
                evaluation_plan_sha256="f" * 64,
            )
        }
    )
    cases.append(
        {
            "point_metrics": _forge(
                first.point_metrics,
                pretest_freeze_sha256="0" * 64,
            )
        }
    )
    cases.append({"mandatory_breakdowns": second.mandatory_breakdowns})
    cases.append(
        {
            "point_estimate": _forge(
                first.point_estimate,
                baseline_metrics=first.point_metrics.test_id_baselines[0].metrics,
            )
        }
    )
    substituted_seed = replace(
        first.point_estimate.learned_seed_results[0],
        metrics=first.point_metrics.test_id_learned[1].metrics,
    )
    cases.append(
        {
            "point_estimate": _forge(
                first.point_estimate,
                learned_seed_results=(
                    substituted_seed,
                    *first.point_estimate.learned_seed_results[1:],
                ),
            )
        }
    )
    cases.append({"bootstrap_result": second.bootstrap_result})
    cases.append(
        {
            "bootstrap_result": _forge(
                first.bootstrap_result,
                spec=PredictionBootstrapSpec(
                    fixture.metrics.pretest.bootstrap_spec.num_resamples,
                    fixture.metrics.pretest.bootstrap_spec.rng_seed,
                    fixture.metrics.pretest.bootstrap_spec.quantile_method,
                ),
            )
        }
    )
    cases.append({"interpretation": second.interpretation})
    for changes in cases:
        kwargs = _result_fields(first)
        kwargs.update(changes)
        with pytest.raises((TypeError, ValueError)):
            OfficialPredictionEvaluationResult(
                **kwargs,
                _verification_token=token,
            )


def test_all_binding_completes_before_metrics_and_order_is_canonical(
    fixture: _Fixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_baseline = outcome_module.bind_official_baseline_split_forecasts
    original_learned = outcome_module.bind_official_learned_split_forecasts
    original_metrics = outcome_module.evaluate_official_sealed_point_metrics
    events: list[tuple[str, SplitLabel, object]] = []

    def baseline(*args: object, **kwargs: object) -> object:
        events.append(("baseline", kwargs["split"], kwargs["baseline"]))
        return original_baseline(*args, **kwargs)

    def learned(*args: object, **kwargs: object) -> object:
        events.append(("learned", kwargs["split"], kwargs["training_seed"]))
        return original_learned(*args, **kwargs)

    def metrics(*args: object, **kwargs: object) -> object:
        events.append(("metrics", SplitLabel.TEST_ID, None))
        return original_metrics(*args, **kwargs)

    monkeypatch.setattr(outcome_module, "bind_official_baseline_split_forecasts", baseline)
    monkeypatch.setattr(outcome_module, "bind_official_learned_split_forecasts", learned)
    monkeypatch.setattr(outcome_module, "evaluate_official_sealed_point_metrics", metrics)
    result = _finalize(fixture)
    assert isinstance(result, OfficialPredictionEvaluationResult)
    expected = [("baseline", SplitLabel.TEST_ID, baseline) for baseline in _BASELINE_ORDER]
    expected.extend(
        ("learned", SplitLabel.TEST_ID, seed)
        for seed in fixture.metrics.pretraining.fixed_training_seeds
    )
    expected.extend(("baseline", SplitLabel.TEST_OOD, baseline) for baseline in _BASELINE_ORDER)
    expected.extend(
        ("learned", SplitLabel.TEST_OOD, seed)
        for seed in fixture.metrics.pretraining.fixed_training_seeds
    )
    expected.append(("metrics", SplitLabel.TEST_ID, None))
    assert events == expected


def test_final_result_does_not_retain_raw_inputs_or_persistence_surface(
    fixture: _Fixture,
) -> None:
    result = _finalize(fixture)
    assert isinstance(result, OfficialPredictionEvaluationResult)
    assert tuple(field.name for field in fields(result)) == (
        "state",
        "pretest_freeze",
        "point_metrics",
        "mandatory_breakdowns",
        "point_estimate",
        "bootstrap_result",
        "interpretation",
    )
    for forbidden in (
        "artifacts",
        "forecast_records",
        "demand_trace",
        "artifact_path",
        "schema",
        "version",
        "sha256",
        "timestamp",
        "nonce",
        "status",
    ):
        assert not hasattr(result, forbidden)


def test_public_surface_and_source_isolation_are_exact() -> None:
    assert outcome_module.__all__ == [
        "OfficialPredictionEvaluationResult",
        "finalize_official_prediction_evaluation",
    ]
    assert prediction_module.OfficialPredictionEvaluationResult is (
        outcome_module.OfficialPredictionEvaluationResult
    )
    assert prediction_module.finalize_official_prediction_evaluation is (
        outcome_module.finalize_official_prediction_evaluation
    )
    source = inspect.getsource(outcome_module)
    lowered = source.lower()
    for forbidden in (
        "record_first_official_test_execution",
        "formal_h1",
        "delta_min",
        "seed_std",
        "seed_variance",
        "seed_se",
        "seed_cv",
        "seed_range",
        "seed_iqr",
    ):
        assert forbidden not in lowered
    tree = ast.parse(source)
    called_names = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    called_attributes = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert not called_names & {
        "record_first_official_test_execution",
        "retry",
        "rerun",
        "fallback",
    }
    assert not called_attributes & {"predict", "save", "to_json", "to_yaml"}
    assert "import numpy" not in lowered
    assert "np." not in lowered
    assert "bootstrap_locked_test_delta_rmse" in source
    assert "interpret_primary_id_bootstrap" in source


def test_protocol_freezes_final_chain_and_vector_without_scalar_dispersion() -> None:
    protocol = (Path(__file__).parents[1] / "docs" / "PREDICTION_BASELINE_PROTOCOL.md").read_text(
        encoding="utf-8"
    )
    for required in (
        "Final official evaluation construction",
        "already-SPENT",
        "VerifiedPredictionArtifact",
        "ForecastRecord",
        "Slice 14",
        "Slice 15",
        "Slice 16",
        "PREDICTION_EVALUATION_FAILURE",
        "Fixed-seed dispersion report v1",
        "training_seed",
        "Test MSE_r",
        "Test RMSE_r",
        "record_first_official_test_execution",
        "FORECAST_GENERATION",
    ):
        assert required in protocol
    section = protocol.split("### Fixed-seed dispersion report v1", 1)[1]
    assert "standard deviation" in section
    assert "variance" in section
    assert "standard error" in section
    assert "coefficient of variation" in section
    assert "range" in section
    assert "IQR" in section
