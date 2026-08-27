from __future__ import annotations

import hashlib
import inspect
import math
import random
from dataclasses import FrozenInstanceError

import numpy as np
import pytest

import fura_mappo.prediction.bootstrap as bootstrap_module
from fura_mappo.prediction import (
    BaselineKind,
    BaselineValidationCandidate,
    DatasetProtocolSpec,
    HistoryTransformKind,
    LearnedConfigValidationCandidate,
    LockedTestPointEstimate,
    PairedTraceBootstrapResult,
    PointMetricSummary,
    PointObjectiveKind,
    PredictionBootstrapSpec,
    TracePointMetrics,
    TrainingSeedTestResult,
    TrainingSeedValidationResult,
    bootstrap_locked_test_delta_rmse,
    compute_locked_test_point_estimate,
    select_learned_validation_config,
    select_validation_baselines,
)

_SCHEMA = "a" * 64
_HISTORY_LENGTHS = (4, 8, 16, 32)
_ALPHAS = (0.25, 0.50, 0.75)
_FIXED_LENGTHS = {
    BaselineKind.B0: 32,
    BaselineKind.B1: 16,
    BaselineKind.B4: 8,
    BaselineKind.B5: 4,
}
_DEFAULT_LEARNED_TRACE_MSE = (
    (1.0, 4.0, 9.0),
    (4.0, 9.0, 16.0),
    (9.0, 16.0, 25.0),
)
_DEFAULT_BASELINE_TRACE_MSE = (2.0, 8.0, 18.0)


def _sha256(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _checkpoint(training_seed: int) -> str:
    return _sha256(f"locked-checkpoint-{training_seed}")


def _signature(
    prefix: str, count: int, prediction_horizon: int
) -> tuple[tuple[str, int, int], ...]:
    return tuple(
        (
            f"{prefix}_{index}",
            100 * (index + 1),
            prediction_horizon + 4 + index,
        )
        for index in range(count)
    )


def _metrics(
    trace_mses: tuple[float, ...],
    *,
    prediction_horizon: int,
    num_zones: int = 2,
    schema: str = _SCHEMA,
    signature: tuple[tuple[str, int, int], ...],
) -> PointMetricSummary:
    if len(trace_mses) != len(signature):
        raise ValueError("test helper trace_mses/signature length mismatch")
    trace_metrics = tuple(
        TracePointMetrics(
            trace_id=trace_id,
            trace_start_step=trace_start_step,
            trace_num_steps=trace_num_steps,
            anchor_counts_by_horizon=[
                trace_num_steps - lead for lead in range(1, prediction_horizon + 1)
            ],
            mse_by_horizon_zone=[[trace_mse] * num_zones for _ in range(prediction_horizon)],
            mae_by_horizon_zone=[
                [math.sqrt(trace_mse)] * num_zones for _ in range(prediction_horizon)
            ],
            bias_by_horizon_zone=[[0.0] * num_zones for _ in range(prediction_horizon)],
        )
        for trace_mse, (trace_id, trace_start_step, trace_num_steps) in zip(
            trace_mses,
            signature,
            strict=True,
        )
    )
    return PointMetricSummary(
        trace_metrics=trace_metrics,
        prediction_horizon=prediction_horizon,
        num_zones=num_zones,
        zone_schema_sha256=schema,
    )


def _learned_selection(
    *,
    prediction_horizon: int,
    num_zones: int,
    validation_signature: tuple[tuple[str, int, int], ...],
    seeds: tuple[int, ...] = (1, 2, 3),
):
    validation_metrics = _metrics(
        (1.0,) * len(validation_signature),
        prediction_horizon=prediction_horizon,
        num_zones=num_zones,
        signature=validation_signature,
    )
    candidate = LearnedConfigValidationCandidate(
        config_sha256=_sha256("selected-learned-config"),
        protocol=DatasetProtocolSpec(8, prediction_horizon, _SCHEMA),
        objective=PointObjectiveKind.O0,
        transform=HistoryTransformKind.T0,
        model_complexity_key=(10, 100),
        canonical_order=0,
        seed_results=tuple(
            TrainingSeedValidationResult(
                training_seed=seed,
                checkpoint_sha256=_checkpoint(seed),
                metrics=validation_metrics,
                deterministic_validation_passed=True,
                failure_reason=None,
            )
            for seed in seeds
        ),
    )
    return select_learned_validation_config([candidate])


def _baseline_selection(
    *,
    prediction_horizon: int,
    num_zones: int,
    validation_signature: tuple[tuple[str, int, int], ...],
):
    validation_metrics = _metrics(
        (1.0,) * len(validation_signature),
        prediction_horizon=prediction_horizon,
        num_zones=num_zones,
        signature=validation_signature,
    )

    def candidate(
        baseline: BaselineKind,
        history_length: int,
        *,
        alpha: float | None = None,
    ) -> BaselineValidationCandidate:
        return BaselineValidationCandidate(
            baseline=baseline,
            protocol=DatasetProtocolSpec(history_length, prediction_horizon, _SCHEMA),
            metrics=validation_metrics,
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


def _point_estimate(
    learned_trace_mse: tuple[tuple[float, ...], ...] = _DEFAULT_LEARNED_TRACE_MSE,
    baseline_trace_mse: tuple[float, ...] = _DEFAULT_BASELINE_TRACE_MSE,
    *,
    prediction_horizon: int = 2,
    num_zones: int = 2,
) -> LockedTestPointEstimate:
    if not learned_trace_mse:
        raise ValueError("test helper requires learned seeds")
    num_traces = len(baseline_trace_mse)
    if any(len(row) != num_traces for row in learned_trace_mse):
        raise ValueError("test helper learned/baseline trace count mismatch")
    validation_signature = _signature("validation", 2, prediction_horizon)
    test_signature = _signature("test", num_traces, prediction_horizon)
    seeds = tuple(range(1, len(learned_trace_mse) + 1))
    learned_selection = _learned_selection(
        prediction_horizon=prediction_horizon,
        num_zones=num_zones,
        validation_signature=validation_signature,
        seeds=seeds,
    )
    baseline_selection = _baseline_selection(
        prediction_horizon=prediction_horizon,
        num_zones=num_zones,
        validation_signature=validation_signature,
    )
    learned_seed_results = tuple(
        TrainingSeedTestResult(
            training_seed=seed,
            checkpoint_sha256=_checkpoint(seed),
            metrics=_metrics(
                trace_mses,
                prediction_horizon=prediction_horizon,
                num_zones=num_zones,
                signature=test_signature,
            ),
        )
        for seed, trace_mses in zip(seeds, learned_trace_mse, strict=True)
    )
    baseline_metrics = _metrics(
        baseline_trace_mse,
        prediction_horizon=prediction_horizon,
        num_zones=num_zones,
        signature=test_signature,
    )
    return compute_locked_test_point_estimate(
        learned_selection,
        baseline_selection,
        learned_seed_results,
        baseline_metrics,
    )


def _manual_delta_replicates(
    learned_trace_mse: tuple[tuple[float, ...], ...],
    baseline_trace_mse: tuple[float, ...],
    sampled_indices: np.ndarray,
) -> np.ndarray:
    learned = np.asarray(learned_trace_mse, dtype=np.float64)
    baseline = np.asarray(baseline_trace_mse, dtype=np.float64)
    per_seed_mse = np.mean(learned[:, sampled_indices], axis=2, dtype=np.float64)
    algorithm_rmse = np.sqrt(np.mean(per_seed_mse, axis=0, dtype=np.float64))
    baseline_rmse = np.sqrt(np.mean(baseline[sampled_indices], axis=1, dtype=np.float64))
    return algorithm_rmse - baseline_rmse


def _assert_legacy_numpy_state_equal(
    left: tuple[object, ...],
    right: tuple[object, ...],
) -> None:
    assert left[0] == right[0]
    assert np.array_equal(left[1], right[1])
    assert left[2:] == right[2:]


def test_bootstrap_spec_has_explicit_immutable_identity_without_defaults() -> None:
    spec = PredictionBootstrapSpec(25, 7, "linear")

    assert spec.num_resamples == 25
    assert spec.rng_seed == 7
    assert spec.quantile_method == "linear"
    assert not hasattr(spec, "confidence_level")
    assert not hasattr(spec, "alpha")
    assert not hasattr(spec, "__dict__")
    assert all(
        parameter.default is inspect.Parameter.empty
        for parameter in inspect.signature(PredictionBootstrapSpec).parameters.values()
    )
    with pytest.raises(FrozenInstanceError):
        spec.rng_seed = 8  # type: ignore[misc]


@pytest.mark.parametrize("num_resamples", [0, -1, True, 1.5])
def test_bootstrap_spec_rejects_invalid_num_resamples(num_resamples: object) -> None:
    with pytest.raises((TypeError, ValueError), match="num_resamples"):
        PredictionBootstrapSpec(
            num_resamples=num_resamples,  # type: ignore[arg-type]
            rng_seed=7,
            quantile_method="linear",
        )


@pytest.mark.parametrize("rng_seed", [-1, True, 1.5])
def test_bootstrap_spec_rejects_invalid_rng_seed(rng_seed: object) -> None:
    with pytest.raises((TypeError, ValueError), match="rng_seed"):
        PredictionBootstrapSpec(
            num_resamples=10,
            rng_seed=rng_seed,  # type: ignore[arg-type]
            quantile_method="linear",
        )


@pytest.mark.parametrize("quantile_method", ["", "   ", "not-a-method", 1])
def test_bootstrap_spec_rejects_invalid_quantile_method(quantile_method: object) -> None:
    with pytest.raises((TypeError, ValueError), match="quantile_method"):
        PredictionBootstrapSpec(
            num_resamples=10,
            rng_seed=7,
            quantile_method=quantile_method,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("quantile_method", ["linear", "nearest"])
def test_bootstrap_spec_preserves_supported_quantile_method(quantile_method: str) -> None:
    spec = PredictionBootstrapSpec(10, 7, quantile_method)

    assert spec.quantile_method == quantile_method


def test_bootstrap_is_byte_deterministic_for_same_explicit_spec() -> None:
    point_estimate = _point_estimate()
    spec = PredictionBootstrapSpec(40, 17, "linear")

    first = bootstrap_locked_test_delta_rmse(point_estimate, spec)
    second = bootstrap_locked_test_delta_rmse(point_estimate, spec)

    assert first.delta_rmse_replicates.tobytes() == second.delta_rmse_replicates.tobytes()
    assert first.ci_lower == second.ci_lower
    assert first.ci_upper == second.ci_upper
    assert first.point_delta_rmse == second.point_delta_rmse


def test_different_prediction_bootstrap_seeds_change_replicate_sequence() -> None:
    point_estimate = _point_estimate()
    first = bootstrap_locked_test_delta_rmse(
        point_estimate,
        PredictionBootstrapSpec(40, 17, "linear"),
    )
    second = bootstrap_locked_test_delta_rmse(
        point_estimate,
        PredictionBootstrapSpec(40, 18, "linear"),
    )

    assert not np.array_equal(first.delta_rmse_replicates, second.delta_rmse_replicates)


def test_bootstrap_does_not_mutate_python_or_numpy_global_rng_state() -> None:
    point_estimate = _point_estimate()
    python_state = random.getstate()
    numpy_state = np.random.get_state()

    bootstrap_locked_test_delta_rmse(
        point_estimate,
        PredictionBootstrapSpec(20, 11, "linear"),
    )

    assert random.getstate() == python_state
    _assert_legacy_numpy_state_equal(np.random.get_state(), numpy_state)


def test_explicit_pcg64_first_replicate_matches_manual_whole_trace_math() -> None:
    learned = _DEFAULT_LEARNED_TRACE_MSE
    baseline = _DEFAULT_BASELINE_TRACE_MSE
    point_estimate = _point_estimate(learned, baseline)
    spec = PredictionBootstrapSpec(5, 11, "linear")
    result = bootstrap_locked_test_delta_rmse(point_estimate, spec)
    generator = np.random.Generator(np.random.PCG64(spec.rng_seed))
    sampled_indices = generator.integers(
        0,
        len(baseline),
        size=(spec.num_resamples, len(baseline)),
        dtype=np.int64,
    )
    expected = _manual_delta_replicates(learned, baseline, sampled_indices)

    assert result.delta_rmse_replicates[0] == expected[0]


def test_paired_same_indices_match_expected_and_not_independent_resampling() -> None:
    learned = (
        (1.0, 9.0, 25.0, 49.0),
        (4.0, 16.0, 36.0, 64.0),
        (9.0, 25.0, 49.0, 81.0),
    )
    baseline = (1.5, 10.0, 27.0, 52.0)
    point_estimate = _point_estimate(learned, baseline)
    spec = PredictionBootstrapSpec(16, 23, "linear")
    result = bootstrap_locked_test_delta_rmse(point_estimate, spec)

    paired_generator = np.random.Generator(np.random.PCG64(spec.rng_seed))
    paired_indices = paired_generator.integers(
        0,
        len(baseline),
        size=(spec.num_resamples, len(baseline)),
        dtype=np.int64,
    )
    expected_paired = _manual_delta_replicates(learned, baseline, paired_indices)

    independent_generator = np.random.Generator(np.random.PCG64(spec.rng_seed))
    learned_indices = independent_generator.integers(
        0,
        len(baseline),
        size=(spec.num_resamples, len(baseline)),
        dtype=np.int64,
    )
    baseline_indices = independent_generator.integers(
        0,
        len(baseline),
        size=(spec.num_resamples, len(baseline)),
        dtype=np.int64,
    )
    learned_array = np.asarray(learned, dtype=np.float64)
    baseline_array = np.asarray(baseline, dtype=np.float64)
    wrong_algorithm_rmse = np.sqrt(
        np.mean(
            np.mean(learned_array[:, learned_indices], axis=2, dtype=np.float64),
            axis=0,
            dtype=np.float64,
        )
    )
    wrong_baseline_rmse = np.sqrt(
        np.mean(baseline_array[baseline_indices], axis=1, dtype=np.float64)
    )
    wrong_independent = wrong_algorithm_rmse - wrong_baseline_rmse

    assert np.array_equal(result.delta_rmse_replicates, expected_paired)
    assert not np.array_equal(result.delta_rmse_replicates, wrong_independent)


def test_every_replicate_uses_all_fixed_training_seeds_exactly_once() -> None:
    learned = (
        (1.0, 1.0, 1.0),
        (16.0, 16.0, 16.0),
        (81.0, 81.0, 81.0),
    )
    baseline = (0.0, 0.0, 0.0)
    result = bootstrap_locked_test_delta_rmse(
        _point_estimate(learned, baseline),
        PredictionBootstrapSpec(12, 5, "linear"),
    )
    expected = math.sqrt((1.0 + 16.0 + 81.0) / 3.0)

    assert np.all(result.delta_rmse_replicates == expected)
    assert not np.any(result.delta_rmse_replicates == 1.0)
    assert not np.any(result.delta_rmse_replicates == 4.0)
    assert not np.any(result.delta_rmse_replicates == 9.0)


def test_bootstrap_algorithm_rmse_is_sqrt_mean_mse_not_mean_seed_rmse() -> None:
    learned = (
        (1.0, 1.0, 1.0),
        (4.0, 4.0, 4.0),
        (9.0, 9.0, 9.0),
    )
    baseline = (0.0, 0.0, 0.0)
    result = bootstrap_locked_test_delta_rmse(
        _point_estimate(learned, baseline),
        PredictionBootstrapSpec(8, 9, "linear"),
    )
    expected = math.sqrt(14.0 / 3.0)

    assert np.all(result.delta_rmse_replicates == expected)
    assert not np.any(result.delta_rmse_replicates == 2.0)


def test_repeated_trace_indices_contribute_with_occurrence_multiplicity() -> None:
    learned = (
        (1.0, 9.0, 25.0),
        (1.0, 9.0, 25.0),
        (1.0, 9.0, 25.0),
    )
    baseline = (0.0, 0.0, 0.0)
    spec = PredictionBootstrapSpec(1, 7, "linear")
    result = bootstrap_locked_test_delta_rmse(_point_estimate(learned, baseline), spec)
    generator = np.random.Generator(np.random.PCG64(spec.rng_seed))
    sampled = generator.integers(0, 3, size=(1, 3), dtype=np.int64)[0]
    expected = math.sqrt(float(np.mean(np.asarray(learned[0])[sampled])))
    deduplicated_wrong = math.sqrt(float(np.mean(np.asarray(learned[0])[np.unique(sampled)])))

    assert tuple(sampled) == (2, 1, 2)
    assert result.delta_rmse_replicates[0] == expected
    assert result.delta_rmse_replicates[0] != deduplicated_wrong


def test_one_trace_case_is_degenerate_at_locked_point_delta() -> None:
    learned = ((1.0,), (4.0,), (9.0,))
    baseline = (4.0,)
    point_estimate = _point_estimate(learned, baseline)
    result = bootstrap_locked_test_delta_rmse(
        point_estimate,
        PredictionBootstrapSpec(20, 31, "linear"),
    )

    assert np.all(result.delta_rmse_replicates == point_estimate.delta_rmse)
    assert result.ci_lower == point_estimate.delta_rmse
    assert result.ci_upper == point_estimate.delta_rmse


def test_zero_error_case_has_zero_replicates_and_interval() -> None:
    learned = ((0.0, 0.0), (0.0, 0.0), (0.0, 0.0))
    baseline = (0.0, 0.0)
    result = bootstrap_locked_test_delta_rmse(
        _point_estimate(learned, baseline),
        PredictionBootstrapSpec(20, 41, "linear"),
    )

    assert np.array_equal(result.delta_rmse_replicates, np.zeros(20))
    assert result.ci_lower == 0.0
    assert result.ci_upper == 0.0


@pytest.mark.parametrize("prediction_horizon", [2, 4])
def test_bootstrap_core_is_generic_in_prediction_horizon(prediction_horizon: int) -> None:
    point_estimate = _point_estimate(prediction_horizon=prediction_horizon)
    result = bootstrap_locked_test_delta_rmse(
        point_estimate,
        PredictionBootstrapSpec(12, 13, "linear"),
    )

    assert result.point_estimate.prediction_horizon == prediction_horizon
    assert result.delta_rmse_replicates.shape == (12,)


@pytest.mark.parametrize("quantile_method", ["linear", "nearest"])
def test_result_uses_requested_method_for_fixed_two_sided_95_percentile_ci(
    quantile_method: str,
) -> None:
    point_estimate = _point_estimate()
    replicates = np.asarray([-3.0, -1.0, 0.0, 2.0, 8.0], dtype=np.float64)
    spec = PredictionBootstrapSpec(len(replicates), 7, quantile_method)
    result = PairedTraceBootstrapResult(point_estimate, spec, replicates)
    expected = np.quantile(
        replicates,
        [0.025, 0.975],
        method=quantile_method,
    )

    assert result.spec.quantile_method == quantile_method
    assert (result.ci_lower, result.ci_upper) == (float(expected[0]), float(expected[1]))


def test_result_replicates_are_defensive_float64_c_contiguous_read_only_copy() -> None:
    point_estimate = _point_estimate()
    source = np.asarray([3, 1, 2], dtype=np.int64)
    expected = source.astype(np.float64)
    result = PairedTraceBootstrapResult(
        point_estimate,
        PredictionBootstrapSpec(3, 7, "linear"),
        source,
    )
    source[:] = 99

    assert np.array_equal(result.delta_rmse_replicates, expected)
    assert result.delta_rmse_replicates.dtype == np.dtype(np.float64)
    assert result.delta_rmse_replicates.flags.c_contiguous
    assert not result.delta_rmse_replicates.flags.writeable
    assert not hasattr(result, "__dict__")
    with pytest.raises(ValueError):
        result.delta_rmse_replicates[0] = 0.0
    with pytest.raises(FrozenInstanceError):
        result.ci_lower = 0.0  # type: ignore[misc]


@pytest.mark.parametrize(
    "replicates",
    [
        np.asarray([1.0, 2.0]),
        np.asarray([1.0, np.nan, 3.0]),
        np.asarray([1.0, np.inf, 3.0]),
        np.asarray([[1.0, 2.0, 3.0]]),
        np.asarray([True, False, True]),
        np.asarray(["1", "2", "3"]),
    ],
)
def test_result_rejects_wrong_length_nonfinite_non1d_or_nonnumeric_replicates(
    replicates: np.ndarray,
) -> None:
    with pytest.raises((TypeError, ValueError)):
        PairedTraceBootstrapResult(
            _point_estimate(),
            PredictionBootstrapSpec(3, 7, "linear"),
            replicates,
        )


def test_result_and_function_reject_wrong_top_level_types() -> None:
    point_estimate = _point_estimate()
    spec = PredictionBootstrapSpec(3, 7, "linear")
    replicates = np.zeros(3)
    with pytest.raises(TypeError, match="LockedTestPointEstimate"):
        PairedTraceBootstrapResult(object(), spec, replicates)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="PredictionBootstrapSpec"):
        PairedTraceBootstrapResult(point_estimate, object(), replicates)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="LockedTestPointEstimate"):
        bootstrap_locked_test_delta_rmse(object(), spec)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="PredictionBootstrapSpec"):
        bootstrap_locked_test_delta_rmse(point_estimate, object())  # type: ignore[arg-type]


def test_bootstrap_defensively_rejects_corrupted_learned_trace_alignment() -> None:
    point_estimate = _point_estimate()
    changed_signature = (
        ("test_0", 101, 6),
        ("test_1", 200, 7),
        ("test_2", 300, 8),
    )
    corrupted_metrics = _metrics(
        _DEFAULT_LEARNED_TRACE_MSE[0],
        prediction_horizon=2,
        signature=changed_signature,
    )
    object.__setattr__(point_estimate.learned_seed_results[0], "metrics", corrupted_metrics)

    with pytest.raises(ValueError, match="learned.*whole-trace alignment"):
        bootstrap_locked_test_delta_rmse(
            point_estimate,
            PredictionBootstrapSpec(3, 7, "linear"),
        )


def test_bootstrap_defensively_rejects_corrupted_baseline_trace_alignment() -> None:
    point_estimate = _point_estimate()
    changed_signature = (
        ("test_0", 100, 6),
        ("test_1", 201, 7),
        ("test_2", 300, 8),
    )
    corrupted_metrics = _metrics(
        _DEFAULT_BASELINE_TRACE_MSE,
        prediction_horizon=2,
        signature=changed_signature,
    )
    object.__setattr__(point_estimate, "baseline_metrics", corrupted_metrics)

    with pytest.raises(ValueError, match="baseline.*whole-trace alignment"):
        bootstrap_locked_test_delta_rmse(
            point_estimate,
            PredictionBootstrapSpec(3, 7, "linear"),
        )


def test_point_delta_property_preserves_slice6_sign_and_value() -> None:
    point_estimate = _point_estimate()
    result = bootstrap_locked_test_delta_rmse(
        point_estimate,
        PredictionBootstrapSpec(10, 7, "linear"),
    )

    assert result.point_delta_rmse == point_estimate.delta_rmse


def test_no_official_values_label_margin_or_spent_test_surface() -> None:
    source = inspect.getsource(bootstrap_module)
    result = bootstrap_locked_test_delta_rmse(
        _point_estimate(),
        PredictionBootstrapSpec(10, 7, "linear"),
    )
    forbidden_attributes = (
        "label",
        "verdict",
        "delta_min",
        "equivalence_margin",
        "spent_test",
        "prediction_evaluation_failure",
    )

    assert "90260819" not in source
    assert "50000" not in source
    assert all(not hasattr(result, name) for name in forbidden_attributes)


def test_public_bootstrap_surface_is_minimal() -> None:
    assert bootstrap_module.__all__ == [
        "PairedTraceBootstrapResult",
        "PredictionBootstrapSpec",
        "bootstrap_locked_test_delta_rmse",
    ]
    assert "_extract_trace_mse" not in bootstrap_module.__all__
    assert "_percentile_interval" not in bootstrap_module.__all__
    assert "_normalize_replicates" not in bootstrap_module.__all__
