from __future__ import annotations

from collections.abc import Callable
from dataclasses import FrozenInstanceError
from pathlib import Path

import numpy as np
import pytest

import fura_mappo.prediction.baselines as baselines_module
from fura_mappo.demand import DemandEvent, DemandTrace, save_demand_trace
from fura_mappo.prediction import (
    AbsoluteStepClimatologyDemandPredictor,
    DemandForecast,
    PredictionContext,
    StaticClimatologyDemandPredictor,
    VerifiedPredictionArtifact,
    fit_absolute_step_train_climatology,
    fit_static_train_climatology,
    load_verified_prediction_artifact,
)

FitFunction = Callable[
    [object],
    StaticClimatologyDemandPredictor | AbsoluteStepClimatologyDemandPredictor,
]


def _zone_bounds(num_zones: int, *, width: float = 1.0) -> list[list[float]]:
    return [[zone_id * width, (zone_id + 1) * width, 0.0, 1.0] for zone_id in range(num_zones)]


def _trace(
    counts: list[list[int]],
    *,
    start_step: int = 0,
    intensity_value: float = 0.1,
) -> DemandTrace:
    count_array = np.asarray(counts, dtype=np.int64)
    events: list[DemandEvent] = []
    event_id = 0
    for row, zone_counts in enumerate(count_array):
        arrival_step = start_step + row
        for zone_id, zone_count in enumerate(zone_counts):
            for _ in range(int(zone_count)):
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
    intensities = np.full(count_array.shape, intensity_value, dtype=np.float64)
    return DemandTrace(start_step, count_array, intensities, tuple(events))


def _resolved_config(
    trace: DemandTrace,
    *,
    seed: int,
    zone_bounds: list[list[float]],
) -> dict[str, object]:
    return {
        "schema": "fura-mappo.demand-generation",
        "version": 1,
        "demand": {
            "type": "stationary_poisson",
            "seed": seed,
            "intensities": trace.intensities[0].tolist(),
            "zone_bounds": zone_bounds,
            "priority_range": [0.5, 0.5],
            "service_time_range": [1, 1],
            "deadline_offset_range": [2, 2],
        },
        "generation": {"num_steps": int(trace.counts.shape[0])},
    }


def _verified(
    tmp_path: Path,
    trace: DemandTrace,
    *,
    name: str,
    seed: int,
    trace_id: str | None = None,
    zone_bounds: list[list[float]] | None = None,
) -> VerifiedPredictionArtifact:
    bounds = zone_bounds or _zone_bounds(int(trace.counts.shape[1]))
    path = save_demand_trace(
        tmp_path / f"{name}.npz",
        trace,
        resolved_config=_resolved_config(trace, seed=seed, zone_bounds=bounds),
    )
    return load_verified_prediction_artifact(path, trace_id or name)


def _context(
    zone_schema_sha256: str,
    *,
    num_zones: int,
    absolute_step: int,
    prediction_horizon: int,
    steps_remaining: int,
) -> PredictionContext:
    return PredictionContext(
        absolute_step=absolute_step,
        steps_remaining=steps_remaining,
        history_counts=np.zeros((1, num_zones), dtype=np.int64),
        history_mask=[True],
        zone_schema_sha256=zone_schema_sha256,
        prediction_horizon=prediction_horizon,
    )


def test_b4_uses_equal_trace_weight_for_unequal_lengths_and_is_order_invariant(
    tmp_path: Path,
) -> None:
    short = _verified(
        tmp_path,
        _trace([[10], [10]]),
        name="short",
        seed=1,
    )
    long = _verified(
        tmp_path,
        _trace([[0], [0], [0], [0], [0], [0]]),
        name="long",
        seed=2,
    )

    forward = fit_static_train_climatology([short, long])
    reverse = fit_static_train_climatology([long, short])

    np.testing.assert_array_equal(forward.climatology, [5.0])
    np.testing.assert_array_equal(forward.climatology, reverse.climatology)
    assert forward.climatology[0] != 2.5

    context = _context(
        forward.zone_schema_sha256,
        num_zones=1,
        absolute_step=0,
        prediction_horizon=4,
        steps_remaining=3,
    )
    forecast = forward.predict(context)
    np.testing.assert_array_equal(forecast.valid_mask, [True, True, False, False])
    np.testing.assert_array_equal(forecast.mean, [[5.0], [5.0], [0.0], [0.0]])


def test_b5_fits_exact_common_support_with_equal_per_step_trace_weight(
    tmp_path: Path,
) -> None:
    trace_a = _verified(
        tmp_path,
        _trace([[0], [2], [4], [6], [8], [10]], start_step=0),
        name="trace_a",
        seed=3,
    )
    trace_b = _verified(
        tmp_path,
        _trace([[20], [22], [24], [26], [28], [30]], start_step=2),
        name="trace_b",
        seed=4,
    )

    forward = fit_absolute_step_train_climatology([trace_a, trace_b])
    reverse = fit_absolute_step_train_climatology([trace_b, trace_a])

    assert forward.support_start_step == 2
    assert forward.support_stop_step == 6
    np.testing.assert_array_equal(forward.step_means, [[12.0], [14.0], [16.0], [18.0]])
    np.testing.assert_array_equal(forward.step_means, reverse.step_means)


@pytest.mark.parametrize("prediction_horizon", [2, 4, 8])
def test_b5_supports_generic_prediction_horizons(prediction_horizon: int) -> None:
    predictor = AbsoluteStepClimatologyDemandPredictor(
        "a" * 64,
        0,
        [[step, step * 2] for step in range(9)],
    )
    context = _context(
        "a" * 64,
        num_zones=2,
        absolute_step=0,
        prediction_horizon=prediction_horizon,
        steps_remaining=prediction_horizon + 1,
    )

    forecast = predictor.predict(context)

    np.testing.assert_array_equal(
        forecast.mean,
        [[step, step * 2] for step in range(1, prediction_horizon + 1)],
    )
    np.testing.assert_array_equal(
        forecast.valid_mask,
        np.ones(prediction_horizon, dtype=np.bool_),
    )


def test_b5_required_support_and_terminal_suffix_semantics() -> None:
    predictor = AbsoluteStepClimatologyDemandPredictor(
        "a" * 64,
        2,
        [[2.0], [3.0], [4.0], [5.0]],
    )
    fully_supported = _context(
        "a" * 64,
        num_zones=1,
        absolute_step=1,
        prediction_horizon=4,
        steps_remaining=5,
    )
    missing_last_valid = _context(
        "a" * 64,
        num_zones=1,
        absolute_step=3,
        prediction_horizon=4,
        steps_remaining=4,
    )
    terminal_suffix_outside_support = _context(
        "a" * 64,
        num_zones=1,
        absolute_step=4,
        prediction_horizon=8,
        steps_remaining=2,
    )

    success = predictor.predict(fully_supported)
    np.testing.assert_array_equal(success.mean, [[2.0], [3.0], [4.0], [5.0]])
    with pytest.raises(ValueError, match="required valid lead"):
        predictor.predict(missing_last_valid)

    terminal = predictor.predict(terminal_suffix_outside_support)
    np.testing.assert_array_equal(
        terminal.valid_mask,
        [True, False, False, False, False, False, False, False],
    )
    np.testing.assert_array_equal(terminal.mean[0], [5.0])
    np.testing.assert_array_equal(terminal.mean[1:], np.zeros((7, 1)))


def test_b4_and_b5_hard_bind_zone_schema() -> None:
    context = _context(
        "b" * 64,
        num_zones=1,
        absolute_step=0,
        prediction_horizon=2,
        steps_remaining=3,
    )
    predictors = (
        StaticClimatologyDemandPredictor("a" * 64, [1.0]),
        AbsoluteStepClimatologyDemandPredictor("a" * 64, 0, [[0.0], [1.0], [2.0]]),
    )

    for predictor in predictors:
        with pytest.raises(ValueError, match="zone_schema_sha256"):
            predictor.predict(context)


@pytest.mark.parametrize(
    "fit_function",
    [fit_static_train_climatology, fit_absolute_step_train_climatology],
)
def test_fitters_reject_empty_raw_arbitrary_and_mixed_inputs(
    tmp_path: Path,
    fit_function: FitFunction,
) -> None:
    trace = _trace([[0], [1]])
    verified = _verified(tmp_path, trace, name="valid", seed=5)

    with pytest.raises(ValueError, match="至少包含一个"):
        fit_function([])
    with pytest.raises(TypeError, match="VerifiedPredictionArtifact"):
        fit_function([trace])
    with pytest.raises(TypeError, match="VerifiedPredictionArtifact"):
        fit_function([object()])
    with pytest.raises(TypeError, match="VerifiedPredictionArtifact"):
        fit_function([verified, object()])


@pytest.mark.parametrize(
    "fit_function",
    [fit_static_train_climatology, fit_absolute_step_train_climatology],
)
def test_fitters_reject_mixed_zone_schemas(
    tmp_path: Path,
    fit_function: FitFunction,
) -> None:
    first = _verified(
        tmp_path,
        _trace([[0, 0], [0, 0]], start_step=0),
        name="first_schema",
        seed=6,
    )
    second = _verified(
        tmp_path,
        _trace([[0, 0], [1, 0]], start_step=0),
        name="second_schema",
        seed=7,
        zone_bounds=_zone_bounds(2, width=2.0),
    )

    with pytest.raises(ValueError, match="zone_schema_sha256"):
        fit_function([first, second])


@pytest.mark.parametrize(
    "fit_function",
    [fit_static_train_climatology, fit_absolute_step_train_climatology],
)
def test_fitters_reject_duplicate_logical_trace_despite_different_packaging(
    tmp_path: Path,
    fit_function: FitFunction,
) -> None:
    first = _verified(
        tmp_path,
        _trace([[1], [0]], intensity_value=0.2),
        name="packaging_a",
        seed=8,
        trace_id="logical_a",
    )
    second = _verified(
        tmp_path,
        _trace([[1], [0]], intensity_value=0.9),
        name="packaging_b",
        seed=9,
        trace_id="logical_b",
    )
    assert first.source.realized_trace_sha256 == second.source.realized_trace_sha256
    assert first.source.content_sha256 != second.source.content_sha256
    assert first.source.trace_id != second.source.trace_id

    with pytest.raises(ValueError, match="realized_trace_sha256"):
        fit_function([first, second])


def test_b5_rejects_empty_common_absolute_step_support(tmp_path: Path) -> None:
    early = _verified(
        tmp_path,
        _trace([[0], [1]], start_step=0),
        name="early",
        seed=10,
    )
    late = _verified(
        tmp_path,
        _trace([[2], [0]], start_step=3),
        name="late",
        seed=11,
    )

    with pytest.raises(ValueError, match="no common absolute-step support"):
        fit_absolute_step_train_climatology([early, late])


def test_fitting_isolated_from_trace_intensities(tmp_path: Path) -> None:
    counts_a = [[0, 2], [4, 0], [2, 2]]
    counts_b = [[6, 0], [0, 8], [2, 4]]
    low_intensity_set = [
        _verified(
            tmp_path,
            _trace(counts_a, intensity_value=0.1),
            name="low_a",
            seed=12,
            trace_id="trace_a",
        ),
        _verified(
            tmp_path,
            _trace(counts_b, intensity_value=0.2),
            name="low_b",
            seed=13,
            trace_id="trace_b",
        ),
    ]
    high_intensity_set = [
        _verified(
            tmp_path,
            _trace(counts_a, intensity_value=50.0),
            name="high_a",
            seed=14,
            trace_id="trace_a",
        ),
        _verified(
            tmp_path,
            _trace(counts_b, intensity_value=80.0),
            name="high_b",
            seed=15,
            trace_id="trace_b",
        ),
    ]

    low_b4 = fit_static_train_climatology(low_intensity_set)
    high_b4 = fit_static_train_climatology(high_intensity_set)
    low_b5 = fit_absolute_step_train_climatology(low_intensity_set)
    high_b5 = fit_absolute_step_train_climatology(high_intensity_set)

    np.testing.assert_array_equal(low_b4.climatology, high_b4.climatology)
    np.testing.assert_array_equal(low_b5.step_means, high_b5.step_means)


def test_direct_fitted_arrays_are_float64_c_contiguous_readonly_and_unaliased() -> None:
    climatology_input = np.array([1.0, 2.0], dtype=np.float32)
    step_input = np.asfortranarray([[1, 2], [3, 4], [5, 6]], dtype=np.int64)
    static = StaticClimatologyDemandPredictor("a" * 64, climatology_input)
    absolute = AbsoluteStepClimatologyDemandPredictor("a" * 64, np.int64(3), step_input)

    climatology_input[0] = 99.0
    step_input[0, 0] = 99

    np.testing.assert_array_equal(static.climatology, [1.0, 2.0])
    np.testing.assert_array_equal(absolute.step_means, [[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]])
    for array in (static.climatology, absolute.step_means):
        assert array.dtype == np.float64
        assert array.flags.c_contiguous
        assert not array.flags.writeable
        assert np.isfinite(array).all()
        assert (array >= 0.0).all()
        with pytest.raises(ValueError):
            array.flat[0] = 100.0
    assert not np.shares_memory(static.climatology, climatology_input)
    assert not np.shares_memory(absolute.step_means, step_input)
    assert not hasattr(static, "__dict__")
    assert not hasattr(absolute, "__dict__")
    with pytest.raises(FrozenInstanceError):
        static.zone_schema_sha256 = "b" * 64  # type: ignore[misc]


@pytest.mark.parametrize(
    ("constructor", "arguments"),
    [
        (StaticClimatologyDemandPredictor, ("a" * 64, [])),
        (StaticClimatologyDemandPredictor, ("a" * 64, [np.nan])),
        (StaticClimatologyDemandPredictor, ("a" * 64, [-1.0])),
        (AbsoluteStepClimatologyDemandPredictor, ("a" * 64, 0, np.empty((0, 1)))),
        (AbsoluteStepClimatologyDemandPredictor, ("a" * 64, 0, [[np.inf]])),
        (AbsoluteStepClimatologyDemandPredictor, ("a" * 64, 0, [[-1.0]])),
    ],
)
def test_direct_fitted_arrays_reject_invalid_state(
    constructor: type[object],
    arguments: tuple[object, ...],
) -> None:
    with pytest.raises(ValueError):
        constructor(*arguments)


def test_fitted_predictors_are_stateless_and_detached_from_artifact_collection(
    tmp_path: Path,
) -> None:
    artifacts = [
        _verified(tmp_path, _trace([[0], [2], [4], [6]]), name="state_a", seed=16),
        _verified(tmp_path, _trace([[2], [4], [6], [8]]), name="state_b", seed=17),
    ]
    static = fit_static_train_climatology(artifacts)
    absolute = fit_absolute_step_train_climatology(artifacts)
    artifacts.clear()
    context_a = _context(
        static.zone_schema_sha256,
        num_zones=1,
        absolute_step=0,
        prediction_horizon=2,
        steps_remaining=3,
    )
    context_b = _context(
        static.zone_schema_sha256,
        num_zones=1,
        absolute_step=1,
        prediction_horizon=2,
        steps_remaining=2,
    )

    for predictor in (static, absolute):
        first_a = predictor.predict(context_a)
        predictor.predict(context_b)
        second_a = predictor.predict(context_a)
        np.testing.assert_array_equal(first_a.mean, second_a.mean)
        np.testing.assert_array_equal(first_a.valid_mask, second_a.valid_mask)


def test_b4_and_b5_invoke_shared_forecast_validator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[PredictionContext, DemandForecast]] = []
    original = baselines_module.validate_forecast_for_context

    def _record(context: PredictionContext, forecast: DemandForecast) -> None:
        calls.append((context, forecast))
        original(context, forecast)

    monkeypatch.setattr(baselines_module, "validate_forecast_for_context", _record)
    context = _context(
        "a" * 64,
        num_zones=1,
        absolute_step=0,
        prediction_horizon=2,
        steps_remaining=3,
    )

    StaticClimatologyDemandPredictor("a" * 64, [1.0]).predict(context)
    AbsoluteStepClimatologyDemandPredictor(
        "a" * 64,
        0,
        [[0.0], [1.0], [2.0]],
    ).predict(context)

    assert calls == [(context, calls[0][1]), (context, calls[1][1])]
