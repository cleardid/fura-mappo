from __future__ import annotations

import hashlib
import math
import random
from dataclasses import FrozenInstanceError, replace

import pytest

import fura_mappo.prediction.comparison as comparison_module
from fura_mappo.prediction import (
    BaselineKind,
    BaselineSelectionResult,
    BaselineValidationCandidate,
    DatasetProtocolSpec,
    HistoryTransformKind,
    LearnedConfigValidationCandidate,
    LearnedModelSelectionResult,
    LockedTestPointEstimate,
    PointMetricSummary,
    PointObjectiveKind,
    TracePointMetrics,
    TrainingSeedTestResult,
    TrainingSeedValidationResult,
    compute_locked_test_point_estimate,
    select_learned_validation_config,
    select_validation_baselines,
)

_SCHEMA_A = "a" * 64
_SCHEMA_B = "b" * 64
_VALIDATION_SIGNATURE = (
    ("validation_a", 2, 8),
    ("validation_b", 20, 9),
)
_TEST_SIGNATURE = (
    ("test_a", 100, 9),
    ("test_b", 200, 10),
)
_HISTORY_LENGTHS = (4, 8, 16, 32)
_ALPHAS = (0.25, 0.50, 0.75)
_FIXED_LENGTHS = {
    BaselineKind.B0: 32,
    BaselineKind.B1: 16,
    BaselineKind.B4: 8,
    BaselineKind.B5: 4,
}


def _sha256(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _checkpoint(training_seed: int) -> str:
    return _sha256(f"locked-checkpoint-{training_seed}")


def _metrics(
    primary_mse: float,
    *,
    prediction_horizon: int = 2,
    num_zones: int = 2,
    schema: str = _SCHEMA_A,
    signature: tuple[tuple[str, int, int], ...] = _TEST_SIGNATURE,
) -> PointMetricSummary:
    mse = [[primary_mse] * num_zones for _ in range(prediction_horizon)]
    mae_value = math.sqrt(primary_mse)
    mae = [[mae_value] * num_zones for _ in range(prediction_horizon)]
    bias = [[0.0] * num_zones for _ in range(prediction_horizon)]
    trace_metrics = tuple(
        TracePointMetrics(
            trace_id=trace_id,
            trace_start_step=trace_start_step,
            trace_num_steps=trace_num_steps,
            anchor_counts_by_horizon=[
                trace_num_steps - lead for lead in range(1, prediction_horizon + 1)
            ],
            mse_by_horizon_zone=mse,
            mae_by_horizon_zone=mae,
            bias_by_horizon_zone=bias,
        )
        for trace_id, trace_start_step, trace_num_steps in signature
    )
    return PointMetricSummary(
        trace_metrics=trace_metrics,
        prediction_horizon=prediction_horizon,
        num_zones=num_zones,
        zone_schema_sha256=schema,
    )


def _learned_selection(
    *,
    prediction_horizon: int = 2,
    num_zones: int = 2,
    schema: str = _SCHEMA_A,
    validation_signature: tuple[tuple[str, int, int], ...] = _VALIDATION_SIGNATURE,
    seeds: tuple[int, ...] = (1, 2, 3),
) -> LearnedModelSelectionResult:
    seed_results = tuple(
        TrainingSeedValidationResult(
            training_seed=seed,
            checkpoint_sha256=_checkpoint(seed),
            metrics=_metrics(
                1.0,
                prediction_horizon=prediction_horizon,
                num_zones=num_zones,
                schema=schema,
                signature=validation_signature,
            ),
            deterministic_validation_passed=True,
            failure_reason=None,
        )
        for seed in seeds
    )
    candidate = LearnedConfigValidationCandidate(
        config_sha256=_sha256("selected-learned-config"),
        protocol=DatasetProtocolSpec(8, prediction_horizon, schema),
        objective=PointObjectiveKind.O0,
        transform=HistoryTransformKind.T0,
        model_complexity_key=(10, 100),
        canonical_order=0,
        seed_results=seed_results,
    )
    return select_learned_validation_config([candidate])


def _baseline_selection(
    *,
    prediction_horizon: int = 2,
    num_zones: int = 2,
    schema: str = _SCHEMA_A,
    validation_signature: tuple[tuple[str, int, int], ...] = _VALIDATION_SIGNATURE,
) -> BaselineSelectionResult:
    def candidate(
        baseline: BaselineKind,
        history_length: int,
        *,
        alpha: float | None = None,
    ) -> BaselineValidationCandidate:
        return BaselineValidationCandidate(
            baseline=baseline,
            protocol=DatasetProtocolSpec(history_length, prediction_horizon, schema),
            metrics=_metrics(
                1.0,
                prediction_horizon=prediction_horizon,
                num_zones=num_zones,
                schema=schema,
                signature=validation_signature,
            ),
            alpha=alpha,
        )

    candidates = [
        candidate(baseline, history_length) for baseline, history_length in _FIXED_LENGTHS.items()
    ]
    candidates.extend(candidate(BaselineKind.B2, length) for length in _HISTORY_LENGTHS)
    candidates.extend(
        candidate(BaselineKind.B3, length, alpha=alpha)
        for length in _HISTORY_LENGTHS
        for alpha in _ALPHAS
    )
    return select_validation_baselines(candidates)


def _selections(
    *,
    prediction_horizon: int = 2,
    num_zones: int = 2,
    schema: str = _SCHEMA_A,
    validation_signature: tuple[tuple[str, int, int], ...] = _VALIDATION_SIGNATURE,
) -> tuple[LearnedModelSelectionResult, BaselineSelectionResult]:
    return (
        _learned_selection(
            prediction_horizon=prediction_horizon,
            num_zones=num_zones,
            schema=schema,
            validation_signature=validation_signature,
        ),
        _baseline_selection(
            prediction_horizon=prediction_horizon,
            num_zones=num_zones,
            schema=schema,
            validation_signature=validation_signature,
        ),
    )


def _test_seed_results(
    learned_selection: LearnedModelSelectionResult,
    test_mses: tuple[float, ...] = (1.0, 4.0, 9.0),
    *,
    prediction_horizon: int | None = None,
    num_zones: int | None = None,
    schema: str | None = None,
    signature: tuple[tuple[str, int, int], ...] = _TEST_SIGNATURE,
) -> tuple[TrainingSeedTestResult, ...]:
    horizon = prediction_horizon or learned_selection.prediction_horizon
    zones = num_zones or learned_selection.num_zones
    zone_schema = schema or learned_selection.zone_schema_sha256
    checkpoint_by_seed = {
        result.training_seed: result.checkpoint_sha256
        for result in learned_selection.selected.seed_results
    }
    return tuple(
        TrainingSeedTestResult(
            training_seed=seed,
            checkpoint_sha256=checkpoint_by_seed[seed],  # type: ignore[arg-type]
            metrics=_metrics(
                test_mse,
                prediction_horizon=horizon,
                num_zones=zones,
                schema=zone_schema,
                signature=signature,
            ),
        )
        for seed, test_mse in zip(
            learned_selection.fixed_training_seeds,
            test_mses,
            strict=True,
        )
    )


def _estimate(
    test_mses: tuple[float, ...] = (1.0, 4.0, 9.0),
    *,
    baseline_mse: float = 4.0,
    prediction_horizon: int = 2,
    num_zones: int = 2,
    schema: str = _SCHEMA_A,
    test_signature: tuple[tuple[str, int, int], ...] = _TEST_SIGNATURE,
) -> LockedTestPointEstimate:
    learned_selection, baseline_selection = _selections(
        prediction_horizon=prediction_horizon,
        num_zones=num_zones,
        schema=schema,
    )
    seed_results = _test_seed_results(
        learned_selection,
        test_mses,
        signature=test_signature,
    )
    baseline_metrics = _metrics(
        baseline_mse,
        prediction_horizon=prediction_horizon,
        num_zones=num_zones,
        schema=schema,
        signature=test_signature,
    )
    return compute_locked_test_point_estimate(
        learned_selection,
        baseline_selection,
        seed_results,
        baseline_metrics,
    )


def test_training_seed_test_result_is_complete_immutable_record() -> None:
    metrics = _metrics(2.0)
    result = TrainingSeedTestResult(7, "c" * 64, metrics)

    assert result.training_seed == 7
    assert result.checkpoint_sha256 == "c" * 64
    assert result.metrics is metrics
    assert not hasattr(result, "failure_reason")
    assert not hasattr(result, "status")
    assert not hasattr(result, "__dict__")
    with pytest.raises(FrozenInstanceError):
        result.training_seed = 8  # type: ignore[misc]


@pytest.mark.parametrize("training_seed", [True, -1, 1.5, "1"])
def test_training_seed_test_result_rejects_invalid_seed(training_seed: object) -> None:
    with pytest.raises((TypeError, ValueError), match="training_seed"):
        TrainingSeedTestResult(
            training_seed=training_seed,  # type: ignore[arg-type]
            checkpoint_sha256="a" * 64,
            metrics=_metrics(1.0),
        )


@pytest.mark.parametrize("checkpoint_sha256", [None, "A" * 64, "a" * 63, "x" * 64])
def test_training_seed_test_result_rejects_invalid_checkpoint(
    checkpoint_sha256: object,
) -> None:
    with pytest.raises(ValueError, match="64 位小写 SHA-256"):
        TrainingSeedTestResult(
            training_seed=1,
            checkpoint_sha256=checkpoint_sha256,  # type: ignore[arg-type]
            metrics=_metrics(1.0),
        )


def test_training_seed_test_result_requires_point_metric_summary() -> None:
    with pytest.raises(TypeError, match="PointMetricSummary"):
        TrainingSeedTestResult(1, "a" * 64, object())  # type: ignore[arg-type]


def test_adversarial_aggregation_is_sqrt_of_mean_seed_mse() -> None:
    result = _estimate((1.0, 4.0, 9.0), baseline_mse=4.0)

    assert result.test_algorithm_mse == pytest.approx(14.0 / 3.0)
    assert result.test_algorithm_rmse == pytest.approx(math.sqrt(14.0 / 3.0))
    assert result.test_algorithm_rmse != pytest.approx(2.0)
    assert result.baseline_mse == 4.0
    assert result.baseline_rmse == 2.0
    assert result.delta_rmse == pytest.approx(math.sqrt(14.0 / 3.0) - 2.0)


@pytest.mark.parametrize(
    ("learned_mse", "expected_delta"),
    [
        (1.0, -1.0),
        (9.0, 1.0),
    ],
)
def test_delta_rmse_uses_learned_minus_locked_bstar_sign(
    learned_mse: float,
    expected_delta: float,
) -> None:
    result = _estimate((learned_mse,) * 3, baseline_mse=4.0)

    assert result.delta_rmse == expected_delta


def test_zero_error_semantics_are_valid() -> None:
    result = _estimate((0.0, 0.0, 0.0), baseline_mse=0.0)

    assert result.test_algorithm_mse == 0.0
    assert result.test_algorithm_rmse == 0.0
    assert result.baseline_mse == 0.0
    assert result.baseline_rmse == 0.0
    assert result.delta_rmse == 0.0


@pytest.mark.parametrize("prediction_horizon", [2, 4])
def test_comparison_core_is_generic_in_prediction_horizon(prediction_horizon: int) -> None:
    result = _estimate(prediction_horizon=prediction_horizon)

    assert result.prediction_horizon == prediction_horizon
    assert all(
        seed_result.metrics.prediction_horizon == prediction_horizon
        for seed_result in result.learned_seed_results
    )


def test_result_binds_original_locked_selections_and_baseline_metrics() -> None:
    learned_selection, baseline_selection = _selections()
    learned_selected = learned_selection.selected
    baseline_selected = baseline_selection.selected
    seed_results = _test_seed_results(learned_selection)
    baseline_metrics = _metrics(4.0)

    result = compute_locked_test_point_estimate(
        learned_selection,
        baseline_selection,
        seed_results,
        baseline_metrics,
    )

    assert result.learned_selection is learned_selection
    assert result.learned_selection.selected is learned_selected
    assert result.baseline_selection is baseline_selection
    assert result.baseline_selection.selected is baseline_selected
    assert result.baseline_metrics is baseline_metrics
    assert result.baseline_mse == baseline_metrics.primary_mse
    assert result.baseline_rmse == baseline_metrics.primary_rmse


def test_validation_and_test_trace_signatures_may_differ() -> None:
    result = _estimate()

    assert result.test_trace_signature == _TEST_SIGNATURE
    assert result.learned_selection.validation_trace_signature == _VALIDATION_SIGNATURE
    assert result.test_trace_signature != result.learned_selection.validation_trace_signature


def test_seed_caller_order_is_canonical_and_deterministic() -> None:
    learned_selection, baseline_selection = _selections()
    seed_results = list(_test_seed_results(learned_selection))
    shuffled = seed_results.copy()
    random.Random(20260827).shuffle(shuffled)
    baseline_metrics = _metrics(4.0)
    results = (
        compute_locked_test_point_estimate(
            learned_selection,
            baseline_selection,
            seed_results,
            baseline_metrics,
        ),
        compute_locked_test_point_estimate(
            learned_selection,
            baseline_selection,
            reversed(seed_results),
            baseline_metrics,
        ),
        compute_locked_test_point_estimate(
            learned_selection,
            baseline_selection,
            shuffled,
            baseline_metrics,
        ),
    )
    reference = results[0]

    for result in results:
        assert tuple(item.training_seed for item in result.learned_seed_results) == (1, 2, 3)
        assert result.test_algorithm_mse == reference.test_algorithm_mse
        assert result.test_algorithm_rmse == reference.test_algorithm_rmse
        assert result.delta_rmse == reference.delta_rmse
        assert result.test_trace_signature == reference.test_trace_signature


@pytest.mark.parametrize("case", ["missing", "duplicate", "extra"])
def test_comparison_rejects_nonexact_fixed_seed_coverage(case: str) -> None:
    learned_selection, baseline_selection = _selections()
    seed_results = list(_test_seed_results(learned_selection))
    if case == "missing":
        seed_results.pop()
    elif case == "duplicate":
        seed_results[1] = replace(seed_results[0])
    else:
        seed_results.append(
            TrainingSeedTestResult(
                4,
                _checkpoint(4),
                _metrics(1.0),
            )
        )

    with pytest.raises(ValueError, match="training_seed|精确覆盖"):
        compute_locked_test_point_estimate(
            learned_selection,
            baseline_selection,
            seed_results,
            _metrics(4.0),
        )


def test_comparison_rejects_wrong_or_swapped_checkpoint_identity() -> None:
    learned_selection, baseline_selection = _selections()
    seed_results = list(_test_seed_results(learned_selection, (1.0, 1.0, 1.0)))
    wrong = seed_results.copy()
    wrong[0] = replace(wrong[0], checkpoint_sha256=_sha256("wrong-checkpoint"))
    swapped = seed_results.copy()
    swapped[0] = replace(swapped[0], checkpoint_sha256=seed_results[1].checkpoint_sha256)
    swapped[1] = replace(swapped[1], checkpoint_sha256=seed_results[0].checkpoint_sha256)

    for invalid_results in (wrong, swapped):
        with pytest.raises(ValueError, match="locked checkpoint identity"):
            compute_locked_test_point_estimate(
                learned_selection,
                baseline_selection,
                invalid_results,
                _metrics(4.0),
            )


@pytest.mark.parametrize(
    "changed_signature",
    [
        (("test_a", 100, 9), ("test_c", 200, 10)),
        (("test_a", 101, 9), ("test_b", 200, 10)),
        (("test_a", 100, 8), ("test_b", 200, 10)),
    ],
)
def test_comparison_rejects_one_learned_seed_with_different_test_signature(
    changed_signature: tuple[tuple[str, int, int], ...],
) -> None:
    learned_selection, baseline_selection = _selections()
    seed_results = list(_test_seed_results(learned_selection))
    seed_results[1] = replace(
        seed_results[1],
        metrics=_metrics(4.0, signature=changed_signature),
    )

    with pytest.raises(ValueError, match="test trace signature"):
        compute_locked_test_point_estimate(
            learned_selection,
            baseline_selection,
            seed_results,
            _metrics(4.0),
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("prediction_horizon", 4, "prediction_horizon"),
        ("num_zones", 3, "num_zones"),
        ("schema", _SCHEMA_B, "zone_schema_sha256"),
    ],
)
def test_comparison_rejects_one_learned_seed_with_mixed_geometry(
    field: str,
    value: object,
    message: str,
) -> None:
    learned_selection, baseline_selection = _selections()
    seed_results = list(_test_seed_results(learned_selection))
    kwargs = {
        "prediction_horizon": 2,
        "num_zones": 2,
        "schema": _SCHEMA_A,
    }
    kwargs[field] = value
    seed_results[1] = replace(
        seed_results[1],
        metrics=_metrics(4.0, **kwargs),  # type: ignore[arg-type]
    )

    with pytest.raises(ValueError, match=message):
        compute_locked_test_point_estimate(
            learned_selection,
            baseline_selection,
            seed_results,
            _metrics(4.0),
        )


@pytest.mark.parametrize(
    "changed_signature",
    [
        (("test_a", 100, 9), ("test_c", 200, 10)),
        (("test_a", 101, 9), ("test_b", 200, 10)),
        (("test_a", 100, 8), ("test_b", 200, 10)),
    ],
)
def test_comparison_rejects_baseline_with_different_test_signature(
    changed_signature: tuple[tuple[str, int, int], ...],
) -> None:
    learned_selection, baseline_selection = _selections()

    with pytest.raises(ValueError, match="test trace signature"):
        compute_locked_test_point_estimate(
            learned_selection,
            baseline_selection,
            _test_seed_results(learned_selection),
            _metrics(4.0, signature=changed_signature),
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("prediction_horizon", 4, "prediction_horizon"),
        ("num_zones", 3, "num_zones"),
        ("schema", _SCHEMA_B, "zone_schema_sha256"),
    ],
)
def test_comparison_rejects_baseline_with_mixed_geometry(
    field: str,
    value: object,
    message: str,
) -> None:
    learned_selection, baseline_selection = _selections()
    kwargs = {
        "prediction_horizon": 2,
        "num_zones": 2,
        "schema": _SCHEMA_A,
    }
    kwargs[field] = value

    with pytest.raises(ValueError, match=message):
        compute_locked_test_point_estimate(
            learned_selection,
            baseline_selection,
            _test_seed_results(learned_selection),
            _metrics(4.0, **kwargs),  # type: ignore[arg-type]
        )


def test_comparison_rejects_selection_prediction_horizon_mismatch_first() -> None:
    learned_selection = _learned_selection(prediction_horizon=2)
    baseline_selection = _baseline_selection(prediction_horizon=4)

    with pytest.raises(ValueError, match="selections.*prediction_horizon"):
        compute_locked_test_point_estimate(
            learned_selection,
            baseline_selection,
            _test_seed_results(learned_selection),
            _metrics(4.0),
        )


def test_comparison_rejects_selection_num_zones_mismatch_first() -> None:
    learned_selection = _learned_selection(num_zones=2)
    baseline_selection = _baseline_selection(num_zones=3)

    with pytest.raises(ValueError, match="selections.*num_zones"):
        compute_locked_test_point_estimate(
            learned_selection,
            baseline_selection,
            _test_seed_results(learned_selection),
            _metrics(4.0),
        )


def test_comparison_rejects_selection_zone_schema_mismatch_first() -> None:
    learned_selection = _learned_selection(schema=_SCHEMA_A)
    baseline_selection = _baseline_selection(schema=_SCHEMA_B)

    with pytest.raises(ValueError, match="selections.*zone_schema_sha256"):
        compute_locked_test_point_estimate(
            learned_selection,
            baseline_selection,
            _test_seed_results(learned_selection),
            _metrics(4.0),
        )


def test_comparison_rejects_selection_validation_signature_mismatch_first() -> None:
    changed_validation_signature = (
        ("validation_a", 3, 8),
        ("validation_b", 20, 9),
    )
    learned_selection = _learned_selection()
    baseline_selection = _baseline_selection(
        validation_signature=changed_validation_signature,
    )

    with pytest.raises(ValueError, match="validation trace signature"):
        compute_locked_test_point_estimate(
            learned_selection,
            baseline_selection,
            _test_seed_results(learned_selection),
            _metrics(4.0),
        )


def test_direct_result_construction_revalidates_and_canonicalizes() -> None:
    learned_selection, baseline_selection = _selections()
    seed_results = list(reversed(_test_seed_results(learned_selection)))
    baseline_metrics = _metrics(4.0)
    result = LockedTestPointEstimate(
        learned_selection=learned_selection,
        baseline_selection=baseline_selection,
        learned_seed_results=seed_results,  # type: ignore[arg-type]
        baseline_metrics=baseline_metrics,
    )
    seed_results.clear()

    assert tuple(item.training_seed for item in result.learned_seed_results) == (1, 2, 3)
    assert result.test_trace_signature == _TEST_SIGNATURE
    assert result.prediction_horizon == 2
    assert result.num_zones == 2
    assert result.zone_schema_sha256 == _SCHEMA_A
    assert result.test_algorithm_mse == pytest.approx(14.0 / 3.0)
    assert not hasattr(result, "__dict__")
    with pytest.raises(FrozenInstanceError):
        result.delta_rmse = 0.0  # type: ignore[misc]


def test_comparison_rejects_wrong_top_level_input_types() -> None:
    learned_selection, baseline_selection = _selections()
    seed_results = _test_seed_results(learned_selection)
    baseline_metrics = _metrics(4.0)
    with pytest.raises(TypeError, match="LearnedModelSelectionResult"):
        compute_locked_test_point_estimate(
            object(),  # type: ignore[arg-type]
            baseline_selection,
            seed_results,
            baseline_metrics,
        )
    with pytest.raises(TypeError, match="BaselineSelectionResult"):
        compute_locked_test_point_estimate(
            learned_selection,
            object(),  # type: ignore[arg-type]
            seed_results,
            baseline_metrics,
        )
    with pytest.raises(TypeError, match="PointMetricSummary"):
        compute_locked_test_point_estimate(
            learned_selection,
            baseline_selection,
            seed_results,
            object(),  # type: ignore[arg-type]
        )


def test_comparison_rejects_invalid_seed_result_iterables() -> None:
    learned_selection, baseline_selection = _selections()
    baseline_metrics = _metrics(4.0)
    with pytest.raises(TypeError, match="有限 iterable"):
        compute_locked_test_point_estimate(
            learned_selection,
            baseline_selection,
            None,  # type: ignore[arg-type]
            baseline_metrics,
        )
    with pytest.raises(ValueError, match="非空"):
        compute_locked_test_point_estimate(
            learned_selection,
            baseline_selection,
            [],
            baseline_metrics,
        )
    with pytest.raises(TypeError, match="TrainingSeedTestResult"):
        compute_locked_test_point_estimate(
            learned_selection,
            baseline_selection,
            [object()],  # type: ignore[list-item]
            baseline_metrics,
        )


def test_result_has_no_label_bootstrap_ci_or_spent_test_state() -> None:
    result = _estimate((1.0, 1.0, 1.0), baseline_mse=4.0)

    forbidden_attributes = (
        "label",
        "verdict",
        "ci_lower",
        "ci_upper",
        "bootstrap_seed",
        "bootstrap_resamples",
        "spent_test",
        "prediction_evaluation_failure",
    )
    assert all(not hasattr(result, name) for name in forbidden_attributes)


def test_exact_arithmetic_is_not_rounded_or_clipped() -> None:
    test_mses = (1.0, 1.0, 1.0 + 1.0e-12)
    baseline_mse = 1.0
    result = _estimate(test_mses, baseline_mse=baseline_mse)
    expected_mse = math.fsum(test_mses) / 3
    expected_rmse = math.sqrt(expected_mse)

    assert result.test_algorithm_mse == expected_mse
    assert result.test_algorithm_rmse == expected_rmse
    assert result.delta_rmse == expected_rmse - math.sqrt(baseline_mse)
    assert result.delta_rmse > 0.0


def test_public_comparison_surface_is_minimal() -> None:
    assert comparison_module.__all__ == [
        "LockedTestPointEstimate",
        "TrainingSeedTestResult",
        "compute_locked_test_point_estimate",
    ]
    assert "_test_trace_signature" not in comparison_module.__all__
    assert "_locked_checkpoint_by_seed" not in comparison_module.__all__
    assert "_mean_test_mse" not in comparison_module.__all__
