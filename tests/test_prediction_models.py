from __future__ import annotations

from dataclasses import FrozenInstanceError

import numpy as np
import pytest

from fura_mappo.prediction import (
    DemandForecast,
    ForecastProvenance,
    ForecastRecord,
    PredictionContext,
    PredictionSample,
    PredictionTarget,
    ZoneSchema,
    validate_forecast_for_context,
)

_SHA_A = "a" * 64
_SHA_B = "b" * 64
_SHA_C = "c" * 64
_SHA_D = "d" * 64
_GIT_SHA = "1" * 40


def _zone_schema() -> ZoneSchema:
    return ZoneSchema([[0.0, 1.0, 0.0, 1.0], [1.0, 2.0, 0.0, 1.0]])


def _context() -> PredictionContext:
    return PredictionContext(
        absolute_step=3,
        steps_remaining=4,
        history_counts=[[0, 0], [1, 0], [0, 2]],
        history_mask=[False, True, True],
        zone_schema_sha256=_zone_schema().sha256,
        prediction_horizon=2,
    )


def test_zone_schema_is_defensive_readonly_and_stably_hashed() -> None:
    bounds = np.array([[0, 1, 0, 1], [1, 3, -1, 2]], dtype=np.int32)
    schema = ZoneSchema(bounds)
    same = ZoneSchema([[0.0, 1.0, 0.0, 1.0], [1.0, 3.0, -1.0, 2.0]])
    changed = ZoneSchema([[0.0, 1.0, 0.0, 1.0], [1.0, 4.0, -1.0, 2.0]])
    bounds[:] = 99

    assert schema.bounds.dtype == np.float64
    assert schema.bounds.flags.c_contiguous
    assert not schema.bounds.flags.writeable
    assert schema.zone_ids == (0, 1)
    assert schema.sha256 == same.sha256
    assert schema.sha256 != changed.sha256
    assert not np.shares_memory(schema.bounds, bounds)
    np.testing.assert_array_equal(schema.bounds[0], [0.0, 1.0, 0.0, 1.0])
    with pytest.raises(FrozenInstanceError):
        schema.sha256 = _SHA_A  # type: ignore[misc]


@pytest.mark.parametrize(
    "bounds",
    [
        [0.0, 1.0, 0.0, 1.0],
        [[0.0, 1.0, 0.0]],
        [],
        [[0.0, 0.0, 0.0, 1.0]],
        [[1.0, 0.0, 0.0, 1.0]],
        [[0.0, 1.0, 2.0, 2.0]],
        [[0.0, np.inf, 0.0, 1.0]],
        [[0.0, 1.0, np.nan, 1.0]],
        [[False, 1.0, 0.0, 1.0]],
    ],
)
def test_zone_schema_rejects_invalid_geometry(bounds: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        ZoneSchema(bounds)  # type: ignore[arg-type]


def test_context_and_target_are_canonical_defensive_and_mask_aware() -> None:
    counts = np.array([[0, 0], [1, 0], [0, 2]], dtype=np.int16)
    mask = np.array([False, True, True])
    context = PredictionContext(3, 4, counts, mask, _zone_schema().sha256, 2)
    target_counts = np.array([[2, 1], [0, 0]], dtype=np.int32)
    target_mask = np.array([True, False])
    target = PredictionTarget(target_counts, target_mask)
    sample = PredictionSample(_SHA_A, context, target)
    counts[:] = 9
    mask[:] = False
    target_counts[:] = 9
    target_mask[:] = True

    assert context.history_counts.dtype == np.int64
    assert context.history_mask.dtype == np.bool_
    assert target.counts.dtype == np.int64
    assert not context.history_counts.flags.writeable
    assert not context.history_mask.flags.writeable
    assert not target.counts.flags.writeable
    assert not target.valid_mask.flags.writeable
    assert not np.shares_memory(context.history_counts, counts)
    assert not np.shares_memory(target.counts, target_counts)
    np.testing.assert_array_equal(context.history_counts, [[0, 0], [1, 0], [0, 2]])
    np.testing.assert_array_equal(target.counts, [[2, 1], [0, 0]])
    assert sample.context is context
    assert sample.target is target


@pytest.mark.parametrize(
    ("counts", "mask"),
    [
        ([[0], [0]], [True]),
        ([[0], [0]], [0, 1]),
        ([[0.5]], [True]),
        ([[True]], [True]),
        ([[-1]], [True]),
        ([[1], [0]], [False, True]),
    ],
)
def test_prediction_target_rejects_invalid_arrays(counts: object, mask: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        PredictionTarget(counts, mask)  # type: ignore[arg-type]


def test_prediction_context_rejects_invalid_scalars_shapes_and_padding() -> None:
    zone_hash = _zone_schema().sha256
    invalid = [
        (-1, 2, [[0]], [True], zone_hash, 1),
        (0, 0, [[0]], [True], zone_hash, 1),
        (0, 1, [[0]], [True], zone_hash, 0),
        (0, 1, [[1]], [False], zone_hash, 1),
        (0, 1, [[0]], [False], zone_hash, 1),
        (0, 1, [[0], [0], [0]], [True, False, True], zone_hash, 1),
        (0, 1, [[True]], [True], zone_hash, 1),
        (0, 1, [[0]], [True], "x", 1),
    ]
    for arguments in invalid:
        with pytest.raises((TypeError, ValueError)):
            PredictionContext(*arguments)  # type: ignore[arg-type]


def test_prediction_sample_requires_matching_horizon_and_zones() -> None:
    context = _context()
    with pytest.raises(ValueError, match="horizon"):
        PredictionSample(_SHA_A, context, PredictionTarget([[0, 0]], [True]))
    with pytest.raises(ValueError, match="zone"):
        PredictionSample(_SHA_A, context, PredictionTarget([[0], [0]], [True, True]))
    with pytest.raises(ValueError, match="sample_id"):
        PredictionSample("not-a-hash", context, PredictionTarget([[0, 0]] * 2, [True] * 2))


def test_point_forecast_is_natural_scale_defensive_and_readonly() -> None:
    mean = np.array([[0.5, 1.0], [0.0, 0.0]], dtype=np.float32)
    mask = np.array([True, False])
    forecast = DemandForecast(3, 2, _zone_schema().sha256, mask, mean)
    mean[:] = 9.0
    mask[:] = False

    assert forecast.mean.dtype == np.float64
    assert forecast.valid_mask.dtype == np.bool_
    assert forecast.mean.flags.c_contiguous
    assert not forecast.mean.flags.writeable
    assert not forecast.valid_mask.flags.writeable
    assert forecast.variance is None
    assert forecast.quantiles is None
    assert forecast.scenarios is None
    np.testing.assert_array_equal(forecast.mean, [[0.5, 1.0], [0.0, 0.0]])


def test_probabilistic_forecast_validates_all_optional_projections() -> None:
    forecast = DemandForecast(
        absolute_step=np.int64(4),
        horizon=np.int64(2),
        zone_schema_sha256=_zone_schema().sha256,
        valid_mask=[True, True],
        mean=[[1.0, 2.0], [3.0, 4.0]],
        variance=[[0.5, 1.0], [1.5, 2.0]],
        quantile_levels=[0.1, 0.5, 0.9],
        quantiles=[
            [[0.0, 1.0], [1.0, 2.0]],
            [[1.0, 2.0], [3.0, 4.0]],
            [[2.0, 3.0], [5.0, 6.0]],
        ],
        scenarios=[
            [[0, 1], [2, 3]],
            [[2, 3], [4, 5]],
        ],
    )

    assert forecast.variance is not None and forecast.variance.dtype == np.float64
    assert forecast.quantile_levels is not None
    assert forecast.quantiles is not None
    assert forecast.scenarios is not None and forecast.scenarios.dtype == np.int64
    for array in (
        forecast.variance,
        forecast.quantile_levels,
        forecast.quantiles,
        forecast.scenarios,
    ):
        assert not array.flags.writeable


@pytest.mark.parametrize(
    "changes",
    [
        {"mean": [[-1.0]]},
        {"mean": [[np.nan]]},
        {"mean": [[np.inf]]},
        {"variance": [[-1.0]]},
        {"variance": [[0.0], [0.0]]},
        {"quantile_levels": [0.5], "quantiles": None},
        {"quantile_levels": [0.0], "quantiles": [[[0.0]]]},
        {"quantile_levels": [0.5, 0.5], "quantiles": [[[0.0]], [[1.0]]]},
        {"quantile_levels": [0.2, 0.8], "quantiles": [[[1.0]], [[0.0]]]},
        {"scenarios": [[[0.5]]]},
        {"scenarios": [[[-1]]]},
        {"valid_mask": [False], "mean": [[1.0]]},
        {
            "horizon": 3,
            "valid_mask": [True, False, True],
            "mean": [[0.0], [0.0], [0.0]],
        },
    ],
)
def test_forecast_rejects_invalid_values(changes: dict[str, object]) -> None:
    values: dict[str, object] = {
        "absolute_step": 0,
        "horizon": 1,
        "zone_schema_sha256": _zone_schema().sha256,
        "valid_mask": [True],
        "mean": [[0.0]],
    }
    values.update(changes)
    with pytest.raises((TypeError, ValueError)):
        DemandForecast(**values)  # type: ignore[arg-type]


def test_forecast_record_keeps_provenance_outside_payload() -> None:
    forecast = DemandForecast(0, 1, _zone_schema().sha256, [True], [[0.0]])
    provenance = ForecastProvenance(
        predictor_artifact_sha256=_SHA_A,
        prediction_config_sha256=_SHA_B,
        dataset_protocol_sha256=_SHA_C,
        split_manifest_sha256=_SHA_D,
        normalization_sha256=None,
        sample_id=_SHA_A,
        inference_rng_id="scenario-stream-0",
        execution_git_commit=_GIT_SHA,
    )
    record = ForecastRecord(forecast, provenance)

    assert record.forecast is forecast
    assert not hasattr(forecast, "provenance")
    assert not hasattr(forecast, "seed")
    assert not hasattr(forecast, "process_type")
    assert not hasattr(forecast, "trace_id")


def test_forecast_context_binding_accepts_only_exact_pair() -> None:
    context = _context()
    correct = DemandForecast(
        context.absolute_step,
        context.prediction_horizon,
        context.zone_schema_sha256,
        [True, True],
        [[1.0, 0.0], [0.0, 1.0]],
    )
    validate_forecast_for_context(context, correct)

    wrong_step = DemandForecast(4, 2, context.zone_schema_sha256, [True, True], [[0.0] * 2] * 2)
    with pytest.raises(ValueError, match="absolute_step"):
        validate_forecast_for_context(context, wrong_step)

    wrong_horizon = DemandForecast(
        3,
        3,
        context.zone_schema_sha256,
        [True, True, True],
        [[0.0] * 2] * 3,
    )
    with pytest.raises(ValueError, match="horizon"):
        validate_forecast_for_context(context, wrong_horizon)

    wrong_schema = DemandForecast(3, 2, "f" * 64, [True, True], [[0.0] * 2] * 2)
    with pytest.raises(ValueError, match="zone_schema_sha256"):
        validate_forecast_for_context(context, wrong_schema)

    wrong_zones = DemandForecast(3, 2, context.zone_schema_sha256, [True, True], [[0.0], [0.0]])
    with pytest.raises(ValueError, match="num_zones"):
        validate_forecast_for_context(context, wrong_zones)


def test_forecast_context_binding_enforces_terminal_mask() -> None:
    schema = _zone_schema()
    context = PredictionContext(
        absolute_step=8,
        steps_remaining=2,
        history_counts=[[0, 1]],
        history_mask=[True],
        zone_schema_sha256=schema.sha256,
        prediction_horizon=3,
    )
    wrong = DemandForecast(8, 3, schema.sha256, [True, True, False], [[0.0] * 2] * 3)
    with pytest.raises(ValueError, match="valid_mask"):
        validate_forecast_for_context(context, wrong)

    correct = DemandForecast(8, 3, schema.sha256, [True, False, False], [[0.0] * 2] * 3)
    validate_forecast_for_context(context, correct)

    terminal_context = PredictionContext(
        absolute_step=9,
        steps_remaining=1,
        history_counts=[[0, 0]],
        history_mask=[True],
        zone_schema_sha256=schema.sha256,
        prediction_horizon=2,
    )
    terminal_forecast = DemandForecast(9, 2, schema.sha256, [False, False], [[0.0] * 2] * 2)
    validate_forecast_for_context(terminal_context, terminal_forecast)


def test_supervised_sample_rejects_all_masked_target() -> None:
    with pytest.raises(ValueError, match="lead 1"):
        PredictionSample(
            _SHA_A,
            _context(),
            PredictionTarget([[0, 0], [0, 0]], [False, False]),
        )
