from __future__ import annotations

import hashlib
from dataclasses import FrozenInstanceError, replace

import numpy as np
import pytest

import fura_mappo.prediction.metrics as metrics_module
from fura_mappo.prediction import (
    DemandForecast,
    PointForecastRecord,
    PointMetricSummary,
    PredictionContext,
    PredictionSample,
    PredictionTarget,
    TracePointMetrics,
    evaluate_point_forecasts,
)

_SCHEMA_A = "a" * 64
_SCHEMA_B = "b" * 64


def _sample_id(trace_id: str, absolute_step: int, token: str = "default") -> str:
    payload = f"{trace_id}:{absolute_step}:{token}".encode()
    return hashlib.sha256(payload).hexdigest()


def _record(
    trace_id: str,
    trace_num_steps: int,
    anchor_offset: int,
    prediction_horizon: int,
    num_zones: int,
    *,
    trace_start_step: int = 0,
    schema: str = _SCHEMA_A,
    target_counts: object | None = None,
    residuals: object | None = None,
    sample_token: str = "default",
    sample_id: str | None = None,
    steps_remaining: int | None = None,
) -> PointForecastRecord:
    absolute_step = trace_start_step + anchor_offset
    remaining = trace_num_steps - anchor_offset
    num_valid = min(prediction_horizon, remaining - 1)
    valid_mask = np.zeros(prediction_horizon, dtype=np.bool_)
    valid_mask[:num_valid] = True

    if target_counts is None:
        target_array = np.zeros((prediction_horizon, num_zones), dtype=np.int64)
    else:
        target_array = np.asarray(target_counts, dtype=np.int64)
    if residuals is None:
        residual_array = np.zeros((prediction_horizon, num_zones), dtype=np.float64)
    else:
        residual_array = np.asarray(residuals, dtype=np.float64)
    target_array = np.array(target_array, dtype=np.int64, order="C", copy=True)
    residual_array = np.array(residual_array, dtype=np.float64, order="C", copy=True)
    target_array[~valid_mask] = 0
    residual_array[~valid_mask] = 0.0
    forecast_mean = target_array.astype(np.float64) + residual_array

    context = PredictionContext(
        absolute_step=absolute_step,
        steps_remaining=remaining if steps_remaining is None else steps_remaining,
        history_counts=np.zeros((1, num_zones), dtype=np.int64),
        history_mask=[True],
        zone_schema_sha256=schema,
        prediction_horizon=prediction_horizon,
    )
    target = PredictionTarget(target_array, valid_mask)
    sample = PredictionSample(
        sample_id or _sample_id(trace_id, absolute_step, sample_token),
        context,
        target,
    )
    forecast = DemandForecast(
        absolute_step=absolute_step,
        horizon=prediction_horizon,
        zone_schema_sha256=schema,
        valid_mask=valid_mask,
        mean=forecast_mean,
    )
    return PointForecastRecord(
        trace_id=trace_id,
        trace_start_step=trace_start_step,
        trace_num_steps=trace_num_steps,
        sample=sample,
        forecast=forecast,
    )


def _complete_records(
    trace_id: str,
    trace_num_steps: int,
    prediction_horizon: int,
    num_zones: int,
    *,
    trace_start_step: int = 0,
    schema: str = _SCHEMA_A,
    residual_by_horizon_zone: object | None = None,
    target_by_horizon_zone: object | None = None,
) -> list[PointForecastRecord]:
    return [
        _record(
            trace_id,
            trace_num_steps,
            anchor_offset,
            prediction_horizon,
            num_zones,
            trace_start_step=trace_start_step,
            schema=schema,
            residuals=residual_by_horizon_zone,
            target_counts=target_by_horizon_zone,
        )
        for anchor_offset in range(trace_num_steps - 1)
    ]


def test_hand_calculated_single_trace_metrics_are_exact() -> None:
    residuals = (
        [[1.0, -2.0], [3.0, 4.0]],
        [[-1.0, 0.0], [1.0, -3.0]],
        [[2.0, 1.0], [0.0, 0.0]],
    )
    records = []
    for anchor_offset, residual in enumerate(residuals):
        target = np.zeros((2, 2), dtype=np.int64)
        target[: min(2, 3 - anchor_offset)] = 5
        records.append(
            _record(
                "manual",
                4,
                anchor_offset,
                2,
                2,
                target_counts=target,
                residuals=residual,
            )
        )

    summary = evaluate_point_forecasts(records)
    trace = summary.trace_metrics[0]

    np.testing.assert_array_equal(trace.anchor_counts_by_horizon, [3, 2])
    np.testing.assert_allclose(
        trace.mse_by_horizon_zone,
        [[2.0, 5.0 / 3.0], [5.0, 12.5]],
    )
    np.testing.assert_allclose(
        trace.mae_by_horizon_zone,
        [[4.0 / 3.0, 1.0], [2.0, 3.5]],
    )
    np.testing.assert_allclose(
        trace.bias_by_horizon_zone,
        [[2.0 / 3.0, -1.0 / 3.0], [2.0, 0.5]],
    )
    assert summary.primary_mse == pytest.approx(127.0 / 24.0)
    assert summary.primary_rmse == pytest.approx(np.sqrt(127.0 / 24.0))
    assert summary.secondary_mae == pytest.approx(47.0 / 24.0)
    assert summary.mean_bias == pytest.approx(17.0 / 24.0)


def test_trace_equal_aggregation_does_not_weight_long_trace_more() -> None:
    short = _complete_records("a_short", 2, 1, 1, residual_by_horizon_zone=[[4.0]])
    long = _complete_records(
        "b_long",
        6,
        1,
        1,
        trace_start_step=10,
        residual_by_horizon_zone=[[0.0]],
    )

    summary = evaluate_point_forecasts([*long, *short])
    pooled_wrong_mse = 16.0 / 6.0

    np.testing.assert_array_equal(summary.mse_by_horizon_zone, [[8.0]])
    assert summary.primary_mse == 8.0
    assert summary.primary_mse != pooled_wrong_mse
    assert [metric.trace_id for metric in summary.trace_metrics] == ["a_short", "b_long"]


def test_horizon_equal_aggregation_does_not_weight_h1_anchor_count_more() -> None:
    records = _complete_records(
        "horizon_equal",
        5,
        2,
        1,
        residual_by_horizon_zone=[[1.0], [4.0]],
    )

    summary = evaluate_point_forecasts(records)
    pooled_wrong_mse = (4.0 * 1.0 + 3.0 * 16.0) / 7.0

    np.testing.assert_array_equal(summary.mse_by_horizon_zone, [[1.0], [16.0]])
    assert summary.primary_mse == 8.5
    assert summary.primary_mse != pooled_wrong_mse


def test_zones_are_equal_weight_and_zero_targets_are_retained() -> None:
    records = _complete_records(
        "zone_equal",
        3,
        1,
        2,
        residual_by_horizon_zone=[[10.0, 0.0]],
        target_by_horizon_zone=[[0, 100]],
    )

    summary = evaluate_point_forecasts(records)

    np.testing.assert_array_equal(summary.mse_by_horizon_zone, [[100.0, 0.0]])
    np.testing.assert_array_equal(summary.mae_by_horizon_zone, [[10.0, 0.0]])
    assert summary.primary_mse == 50.0
    assert summary.secondary_mae == 5.0
    assert summary.mean_bias == 5.0


def test_terminal_masks_preserve_exact_lead_anchor_counts_and_denominators() -> None:
    records = _complete_records(
        "terminal",
        6,
        4,
        1,
        residual_by_horizon_zone=[[1.0], [2.0], [3.0], [4.0]],
    )

    summary = evaluate_point_forecasts(records)
    trace = summary.trace_metrics[0]

    np.testing.assert_array_equal(trace.anchor_counts_by_horizon, [5, 4, 3, 2])
    np.testing.assert_array_equal(trace.mse_by_horizon_zone[:, 0], [1.0, 4.0, 9.0, 16.0])
    np.testing.assert_array_equal(trace.mae_by_horizon_zone[:, 0], [1.0, 2.0, 3.0, 4.0])
    np.testing.assert_array_equal(trace.bias_by_horizon_zone[:, 0], [1.0, 2.0, 3.0, 4.0])


@pytest.mark.parametrize("prediction_horizon", [1, 2, 4])
def test_evaluator_supports_generic_prediction_horizon(prediction_horizon: int) -> None:
    trace_num_steps = prediction_horizon + 2
    records = _complete_records(
        f"generic_p{prediction_horizon}",
        trace_num_steps,
        prediction_horizon,
        2,
    )

    summary = evaluate_point_forecasts(records)

    assert summary.prediction_horizon == prediction_horizon
    assert summary.mse_by_horizon_zone.shape == (prediction_horizon, 2)
    np.testing.assert_array_equal(
        summary.trace_metrics[0].anchor_counts_by_horizon,
        [trace_num_steps - lead for lead in range(1, prediction_horizon + 1)],
    )


def test_point_forecast_record_validates_trace_and_boundary_binding() -> None:
    record = _record("valid", 3, 0, 2, 1)

    with pytest.raises(ValueError, match="trace_id"):
        replace(record, trace_id="../unsafe")
    with pytest.raises(TypeError, match="trace_start_step"):
        replace(record, trace_start_step=True)
    with pytest.raises(TypeError, match="trace_num_steps"):
        replace(record, trace_num_steps=False)
    with pytest.raises(ValueError, match="trace_num_steps"):
        replace(record, trace_num_steps=0)
    with pytest.raises(ValueError, match="supervised anchor set"):
        replace(record, trace_num_steps=1)
    with pytest.raises(TypeError, match="PredictionSample"):
        replace(record, sample=object())
    with pytest.raises(TypeError, match="DemandForecast"):
        replace(record, forecast=object())

    wrong_context = replace(record.sample.context, steps_remaining=2)
    wrong_sample = replace(record.sample, context=wrong_context)
    with pytest.raises(ValueError, match="steps_remaining"):
        replace(record, sample=wrong_sample)


def test_record_rejects_target_mask_not_bound_to_forecast_and_context() -> None:
    context = PredictionContext(1, 2, [[0]], [True], _SCHEMA_A, 2)
    target = PredictionTarget([[0], [1]], [True, True])
    sample = PredictionSample("c" * 64, context, target)
    forecast = DemandForecast(1, 2, _SCHEMA_A, [True, False], [[0.0], [0.0]])

    with pytest.raises(ValueError, match="forecast.valid_mask"):
        PointForecastRecord("mask", 0, 3, sample, forecast)


def test_evaluator_rejects_empty_and_nonrecord_inputs() -> None:
    with pytest.raises(ValueError, match="至少包含一个"):
        evaluate_point_forecasts([])
    with pytest.raises(TypeError, match="PointForecastRecord"):
        evaluate_point_forecasts([object()])
    with pytest.raises(TypeError, match="finite iterable|有限 iterable"):
        evaluate_point_forecasts(None)  # type: ignore[arg-type]


def test_evaluator_rejects_missing_anchor_and_duplicate_anchor() -> None:
    complete = _complete_records("complete", 4, 2, 1)
    with pytest.raises(ValueError, match="完整 trace supervised anchor set"):
        evaluate_point_forecasts(complete[:-1])

    duplicate = _record(
        "complete",
        4,
        0,
        2,
        1,
        sample_token="duplicate",
    )
    with pytest.raises(ValueError, match="trace_id/absolute_step"):
        evaluate_point_forecasts([*complete, duplicate])


def test_evaluator_rejects_duplicate_sample_id_across_traces() -> None:
    duplicate_id = "d" * 64
    first = _record("trace_a", 2, 0, 1, 1, sample_id=duplicate_id)
    second = _record("trace_b", 2, 0, 1, 1, sample_id=duplicate_id)

    with pytest.raises(ValueError, match="sample_id"):
        evaluate_point_forecasts([first, second])


def test_evaluator_rejects_trace_shorter_than_horizon_condition() -> None:
    record = _record("too_short", 2, 0, 2, 1)

    with pytest.raises(ValueError, match=r"prediction_horizon \+ 1"):
        evaluate_point_forecasts([record])


def test_evaluator_rejects_inconsistent_geometry_for_same_trace_id() -> None:
    first = _record("same_trace", 3, 0, 1, 1)
    second = _record("same_trace", 4, 1, 1, 1)

    with pytest.raises(ValueError, match="start_step/num_steps"):
        evaluate_point_forecasts([first, second])


def test_evaluator_rejects_mixed_horizon() -> None:
    p1 = _complete_records("p1", 2, 1, 1)
    p2 = _complete_records("p2", 3, 2, 1)

    with pytest.raises(ValueError, match="prediction_horizon"):
        evaluate_point_forecasts([*p1, *p2])


def test_evaluator_rejects_mixed_num_zones() -> None:
    z1 = _complete_records("z1", 2, 1, 1)
    z2 = _complete_records("z2", 2, 1, 2)

    with pytest.raises(ValueError, match="num_zones"):
        evaluate_point_forecasts([*z1, *z2])


def test_evaluator_rejects_mixed_zone_schema() -> None:
    schema_a = _complete_records("schema_a", 2, 1, 1, schema=_SCHEMA_A)
    schema_b = _complete_records("schema_b", 2, 1, 1, schema=_SCHEMA_B)

    with pytest.raises(ValueError, match="zone_schema_sha256"):
        evaluate_point_forecasts([*schema_a, *schema_b])


def test_caller_order_does_not_affect_trace_order_arrays_or_scalars() -> None:
    records = [
        *_complete_records("trace_c", 4, 2, 1, residual_by_horizon_zone=[[3.0], [1.0]]),
        *_complete_records("trace_a", 3, 2, 1, residual_by_horizon_zone=[[1.0], [2.0]]),
        *_complete_records("trace_b", 5, 2, 1, residual_by_horizon_zone=[[2.0], [4.0]]),
    ]
    permutation = records[::2] + records[1::2]

    summaries = (
        evaluate_point_forecasts(records),
        evaluate_point_forecasts(reversed(records)),
        evaluate_point_forecasts(permutation),
    )
    reference = summaries[0]
    assert [metric.trace_id for metric in reference.trace_metrics] == [
        "trace_a",
        "trace_b",
        "trace_c",
    ]
    for summary in summaries[1:]:
        assert [metric.trace_id for metric in summary.trace_metrics] == [
            "trace_a",
            "trace_b",
            "trace_c",
        ]
        np.testing.assert_array_equal(summary.mse_by_horizon_zone, reference.mse_by_horizon_zone)
        np.testing.assert_array_equal(summary.mae_by_horizon_zone, reference.mae_by_horizon_zone)
        np.testing.assert_array_equal(summary.bias_by_horizon_zone, reference.bias_by_horizon_zone)
        assert summary.primary_mse == reference.primary_mse
        assert summary.primary_rmse == reference.primary_rmse
        assert summary.secondary_mae == reference.secondary_mae
        assert summary.mean_bias == reference.mean_bias


def test_result_arrays_are_canonical_readonly_defensive_and_unaliased() -> None:
    anchor_counts = np.array([2, 1], dtype=np.int16)
    mse = np.asfortranarray([[1, 2], [3, 4]], dtype=np.float32)
    mae = np.asfortranarray([[1, 1], [2, 2]], dtype=np.int32)
    bias = np.asfortranarray([[-1, 1], [2, -2]], dtype=np.float32)
    trace = TracePointMetrics("trace", 5, 3, anchor_counts, mse, mae, bias)
    summary = PointMetricSummary((trace,), 2, 2, _SCHEMA_A)

    anchor_counts[:] = 99
    mse[:] = 99
    mae[:] = 99
    bias[:] = 99

    np.testing.assert_array_equal(trace.anchor_counts_by_horizon, [2, 1])
    np.testing.assert_array_equal(trace.mse_by_horizon_zone, [[1.0, 2.0], [3.0, 4.0]])
    for array in (
        trace.anchor_counts_by_horizon,
        trace.mse_by_horizon_zone,
        trace.mae_by_horizon_zone,
        trace.bias_by_horizon_zone,
        summary.mse_by_horizon_zone,
        summary.mae_by_horizon_zone,
        summary.bias_by_horizon_zone,
    ):
        assert array.flags.c_contiguous
        assert not array.flags.writeable
        assert np.isfinite(array).all()
        with pytest.raises(ValueError):
            array.flat[0] = 100
    assert trace.anchor_counts_by_horizon.dtype == np.int64
    assert trace.mse_by_horizon_zone.dtype == np.float64
    assert trace.mae_by_horizon_zone.dtype == np.float64
    assert trace.bias_by_horizon_zone.dtype == np.float64
    assert not np.shares_memory(trace.mse_by_horizon_zone, mse)
    assert not np.shares_memory(summary.mse_by_horizon_zone, trace.mse_by_horizon_zone)
    assert not hasattr(trace, "__dict__")
    assert not hasattr(summary, "__dict__")
    with pytest.raises(FrozenInstanceError):
        trace.trace_id = "changed"  # type: ignore[misc]


def test_metric_result_rejects_invalid_structural_state() -> None:
    with pytest.raises(ValueError, match="anchor_counts"):
        TracePointMetrics("trace", 0, 3, [1, 1], [[0.0], [0.0]], [[0.0], [0.0]], [[0.0], [0.0]])
    with pytest.raises(ValueError, match="有限"):
        TracePointMetrics("trace", 0, 2, [1], [[np.nan]], [[0.0]], [[0.0]])
    with pytest.raises(ValueError, match="非负"):
        TracePointMetrics("trace", 0, 2, [1], [[-1.0]], [[0.0]], [[0.0]])
    with pytest.raises(ValueError, match="至少包含"):
        PointMetricSummary((), 1, 1, _SCHEMA_A)


def test_metric_results_do_not_alias_forecast_target_or_input_collection() -> None:
    target_source = np.array([[0]], dtype=np.int64)
    forecast_source = np.array([[3.0]], dtype=np.float64)
    context = PredictionContext(0, 2, [[0]], [True], _SCHEMA_A, 1)
    target = PredictionTarget(target_source, [True])
    sample = PredictionSample("e" * 64, context, target)
    forecast = DemandForecast(0, 1, _SCHEMA_A, [True], forecast_source)
    records = [PointForecastRecord("detached", 0, 2, sample, forecast)]

    target_source[:] = 100
    forecast_source[:] = 100.0
    summary = evaluate_point_forecasts(records)
    records.clear()

    np.testing.assert_array_equal(summary.mse_by_horizon_zone, [[9.0]])
    np.testing.assert_array_equal(summary.mae_by_horizon_zone, [[3.0]])
    np.testing.assert_array_equal(summary.bias_by_horizon_zone, [[3.0]])


def test_public_metrics_surface_is_minimal() -> None:
    assert metrics_module.__all__ == [
        "PointForecastRecord",
        "PointMetricSummary",
        "TracePointMetrics",
        "evaluate_point_forecasts",
    ]
