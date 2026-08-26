"""Point-demand forecast 的确定性、trace-equal 科学评估。"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

import numpy as np

from fura_mappo.prediction.interfaces import validate_forecast_for_context
from fura_mappo.prediction.models import (
    DemandForecast,
    PredictionSample,
    _normalize_count_array,
    _normalize_float_array,
    _normalize_integer,
    _normalize_sha256,
)

_TRACE_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,254}\Z")


def _normalize_trace_id(value: object) -> str:
    """验证与 prediction dataset source 一致的安全 trace ID。"""

    if not isinstance(value, str) or _TRACE_ID_PATTERN.fullmatch(value) is None:
        raise ValueError("trace_id 必须是安全的 1..255 字符标识符")
    return value


def _normalize_metric_float_array(
    value: object,
    name: str,
    *,
    nonnegative: bool,
) -> np.ndarray:
    """返回 C-order、只读、有限的 ``float64[P,Z]`` 防御性副本。"""

    return _normalize_float_array(value, name, 2, nonnegative=nonnegative)


@dataclass(frozen=True, slots=True, eq=False)
class PointForecastRecord:
    """把完整 trace identity、supervised sample 与 forecast 绑定的 audit-only record。"""

    trace_id: str
    trace_start_step: int
    trace_num_steps: int
    sample: PredictionSample
    forecast: DemandForecast

    def __post_init__(self) -> None:
        """验证 trace geometry、sample boundary 与 forecast/target mask 的完整绑定。"""

        trace_id = _normalize_trace_id(self.trace_id)
        trace_start = _normalize_integer(
            self.trace_start_step,
            "trace_start_step",
            0,
        )
        trace_num_steps = _normalize_integer(
            self.trace_num_steps,
            "trace_num_steps",
            1,
        )
        if not isinstance(self.sample, PredictionSample):
            raise TypeError("sample 必须是 PredictionSample")
        if not isinstance(self.forecast, DemandForecast):
            raise TypeError("forecast 必须是 DemandForecast")

        context = self.sample.context
        target = self.sample.target
        stop_step = trace_start + trace_num_steps
        if not trace_start <= context.absolute_step < stop_step - 1:
            raise ValueError("sample anchor 必须位于完整 trace 的 supervised anchor set")
        expected_steps_remaining = stop_step - context.absolute_step
        if context.steps_remaining != expected_steps_remaining:
            raise ValueError("sample.context.steps_remaining 与 trace boundary 不一致")

        validate_forecast_for_context(context, self.forecast)
        if not np.array_equal(self.forecast.valid_mask, target.valid_mask):
            raise ValueError("forecast.valid_mask 必须精确等于 sample.target.valid_mask")
        if self.forecast.horizon != target.horizon:
            raise ValueError("forecast.horizon 必须等于 sample.target.horizon")
        if self.forecast.num_zones != target.num_zones:
            raise ValueError("forecast.num_zones 必须等于 sample.target.num_zones")

        object.__setattr__(self, "trace_id", trace_id)
        object.__setattr__(self, "trace_start_step", trace_start)
        object.__setattr__(self, "trace_num_steps", trace_num_steps)


@dataclass(frozen=True, slots=True, eq=False)
class TracePointMetrics:
    """单条完整 trace 的逐 horizon、逐 zone point-forecast metrics。"""

    trace_id: str
    trace_start_step: int
    trace_num_steps: int
    anchor_counts_by_horizon: np.ndarray
    mse_by_horizon_zone: np.ndarray
    mae_by_horizon_zone: np.ndarray
    bias_by_horizon_zone: np.ndarray

    def __post_init__(self) -> None:
        """规范化并验证 trace-level audit result。"""

        trace_id = _normalize_trace_id(self.trace_id)
        trace_start = _normalize_integer(
            self.trace_start_step,
            "trace_start_step",
            0,
        )
        trace_num_steps = _normalize_integer(
            self.trace_num_steps,
            "trace_num_steps",
            1,
        )
        anchor_counts = _normalize_count_array(
            self.anchor_counts_by_horizon,
            "anchor_counts_by_horizon",
            1,
        )
        mse = _normalize_metric_float_array(
            self.mse_by_horizon_zone,
            "mse_by_horizon_zone",
            nonnegative=True,
        )
        mae = _normalize_metric_float_array(
            self.mae_by_horizon_zone,
            "mae_by_horizon_zone",
            nonnegative=True,
        )
        bias = _normalize_metric_float_array(
            self.bias_by_horizon_zone,
            "bias_by_horizon_zone",
            nonnegative=False,
        )
        prediction_horizon, num_zones = mse.shape
        if prediction_horizon < 1 or num_zones < 1:
            raise ValueError("metric arrays 形状必须为 [P,Z]，且 P、Z 均至少为 1")
        if mae.shape != mse.shape or bias.shape != mse.shape:
            raise ValueError("mse、mae 与 bias arrays 形状必须完全一致")
        if anchor_counts.shape != (prediction_horizon,):
            raise ValueError("anchor_counts_by_horizon 形状必须为 [P]")
        if trace_num_steps < prediction_horizon + 1:
            raise ValueError("trace_num_steps 必须至少为 prediction_horizon + 1")
        expected_counts = np.asarray(
            [trace_num_steps - lead for lead in range(1, prediction_horizon + 1)],
            dtype=np.int64,
        )
        if not np.array_equal(anchor_counts, expected_counts):
            raise ValueError("anchor_counts_by_horizon 与完整 trace lead counts 不一致")
        if np.any(anchor_counts <= 0):
            raise ValueError("anchor_counts_by_horizon 必须全部为正")

        object.__setattr__(self, "trace_id", trace_id)
        object.__setattr__(self, "trace_start_step", trace_start)
        object.__setattr__(self, "trace_num_steps", trace_num_steps)
        object.__setattr__(self, "anchor_counts_by_horizon", anchor_counts)
        object.__setattr__(self, "mse_by_horizon_zone", mse)
        object.__setattr__(self, "mae_by_horizon_zone", mae)
        object.__setattr__(self, "bias_by_horizon_zone", bias)

    @property
    def prediction_horizon(self) -> int:
        """返回 metric horizon 数量。"""

        return int(self.mse_by_horizon_zone.shape[0])

    @property
    def num_zones(self) -> int:
        """返回 metric zone 数量。"""

        return int(self.mse_by_horizon_zone.shape[1])

    @property
    def primary_mse(self) -> float:
        """返回本 trace 的 horizon-equal、zone-equal MSE。"""

        return float(np.mean(self.mse_by_horizon_zone, dtype=np.float64))

    @property
    def primary_rmse(self) -> float:
        """返回本 trace MSE 的平方根。"""

        return float(np.sqrt(self.primary_mse))

    @property
    def secondary_mae(self) -> float:
        """返回本 trace 的 horizon-equal、zone-equal MAE。"""

        return float(np.mean(self.mae_by_horizon_zone, dtype=np.float64))

    @property
    def mean_bias(self) -> float:
        """返回本 trace 的 mean prediction-minus-target bias。"""

        return float(np.mean(self.bias_by_horizon_zone, dtype=np.float64))


@dataclass(frozen=True, slots=True, eq=False)
class PointMetricSummary:
    """跨完整 traces 等权聚合的 point-forecast metric summary。"""

    trace_metrics: tuple[TracePointMetrics, ...]
    prediction_horizon: int
    num_zones: int
    zone_schema_sha256: str
    mse_by_horizon_zone: np.ndarray = field(init=False)
    mae_by_horizon_zone: np.ndarray = field(init=False)
    bias_by_horizon_zone: np.ndarray = field(init=False)

    def __post_init__(self) -> None:
        """建立 canonical trace ordering，并从 trace arrays 唯一计算 aggregate arrays。"""

        try:
            trace_metrics = tuple(self.trace_metrics)
        except TypeError as error:
            raise TypeError("trace_metrics 必须是 TracePointMetrics 的有限 iterable") from error
        if not trace_metrics:
            raise ValueError("trace_metrics 必须至少包含一条完整 trace")
        if any(not isinstance(metric, TracePointMetrics) for metric in trace_metrics):
            raise TypeError("trace_metrics 必须全部是 TracePointMetrics")
        ordered_metrics = tuple(sorted(trace_metrics, key=lambda metric: metric.trace_id))
        trace_ids = [metric.trace_id for metric in ordered_metrics]
        if len(trace_ids) != len(set(trace_ids)):
            raise ValueError("trace_metrics 的 trace_id 必须全部唯一")

        prediction_horizon = _normalize_integer(
            self.prediction_horizon,
            "prediction_horizon",
            1,
        )
        num_zones = _normalize_integer(self.num_zones, "num_zones", 1)
        zone_hash = _normalize_sha256(self.zone_schema_sha256, "zone_schema_sha256")
        expected_shape = (prediction_horizon, num_zones)
        for metric in ordered_metrics:
            if metric.mse_by_horizon_zone.shape != expected_shape:
                raise ValueError("trace metric horizon/zone shape 与 summary 不一致")

        mse = _normalize_metric_float_array(
            np.mean(
                np.stack(
                    [metric.mse_by_horizon_zone for metric in ordered_metrics],
                    axis=0,
                ),
                axis=0,
                dtype=np.float64,
            ),
            "mse_by_horizon_zone",
            nonnegative=True,
        )
        mae = _normalize_metric_float_array(
            np.mean(
                np.stack(
                    [metric.mae_by_horizon_zone for metric in ordered_metrics],
                    axis=0,
                ),
                axis=0,
                dtype=np.float64,
            ),
            "mae_by_horizon_zone",
            nonnegative=True,
        )
        bias = _normalize_metric_float_array(
            np.mean(
                np.stack(
                    [metric.bias_by_horizon_zone for metric in ordered_metrics],
                    axis=0,
                ),
                axis=0,
                dtype=np.float64,
            ),
            "bias_by_horizon_zone",
            nonnegative=False,
        )

        object.__setattr__(self, "trace_metrics", ordered_metrics)
        object.__setattr__(self, "prediction_horizon", prediction_horizon)
        object.__setattr__(self, "num_zones", num_zones)
        object.__setattr__(self, "zone_schema_sha256", zone_hash)
        object.__setattr__(self, "mse_by_horizon_zone", mse)
        object.__setattr__(self, "mae_by_horizon_zone", mae)
        object.__setattr__(self, "bias_by_horizon_zone", bias)

    @property
    def primary_mse(self) -> float:
        """返回 trace-equal、horizon-equal、zone-equal Primary MSE。"""

        return float(np.mean(self.mse_by_horizon_zone, dtype=np.float64))

    @property
    def primary_rmse(self) -> float:
        """返回 ``sqrt(Primary MSE)``。"""

        return float(np.sqrt(self.primary_mse))

    @property
    def secondary_mae(self) -> float:
        """返回 trace-equal、horizon-equal、zone-equal MAE。"""

        return float(np.mean(self.mae_by_horizon_zone, dtype=np.float64))

    @property
    def mean_bias(self) -> float:
        """返回 trace-equal、horizon-equal、zone-equal mean bias。"""

        return float(np.mean(self.bias_by_horizon_zone, dtype=np.float64))


def _trace_metrics(
    records: tuple[PointForecastRecord, ...],
    prediction_horizon: int,
    num_zones: int,
) -> TracePointMetrics:
    """对一条已 canonicalize 的完整 trace 计算逐 lead/zone metrics。"""

    first = records[0]
    trace_num_steps = first.trace_num_steps
    if trace_num_steps < prediction_horizon + 1:
        raise ValueError("trace_num_steps 必须至少为 prediction_horizon + 1")

    expected_anchors = set(
        range(
            first.trace_start_step,
            first.trace_start_step + trace_num_steps - 1,
        )
    )
    actual_anchors = {record.sample.context.absolute_step for record in records}
    if actual_anchors != expected_anchors:
        raise ValueError("records 必须恰好覆盖完整 trace supervised anchor set 一次")

    expected_counts = np.asarray(
        [trace_num_steps - lead for lead in range(1, prediction_horizon + 1)],
        dtype=np.int64,
    )
    actual_counts = np.zeros(prediction_horizon, dtype=np.int64)
    mse = np.empty((prediction_horizon, num_zones), dtype=np.float64)
    mae = np.empty((prediction_horizon, num_zones), dtype=np.float64)
    bias = np.empty((prediction_horizon, num_zones), dtype=np.float64)

    for horizon_index in range(prediction_horizon):
        residual_rows = [
            record.forecast.mean[horizon_index] - record.sample.target.counts[horizon_index]
            for record in records
            if bool(record.sample.target.valid_mask[horizon_index])
        ]
        actual_counts[horizon_index] = len(residual_rows)
        if actual_counts[horizon_index] != expected_counts[horizon_index]:
            raise ValueError("valid lead anchor count 与完整 trace scientific count 不一致")
        residuals = np.stack(residual_rows, axis=0)
        if residuals.shape != (expected_counts[horizon_index], num_zones):
            raise ValueError("valid residual shape 与 horizon/zone geometry 不一致")
        with np.errstate(over="ignore", invalid="ignore"):
            squared_residuals = np.square(residuals)
        if not np.all(np.isfinite(residuals)) or not np.all(np.isfinite(squared_residuals)):
            raise ValueError("point residual 与 squared residual 必须全部有限")
        mse[horizon_index] = np.mean(
            squared_residuals,
            axis=0,
            dtype=np.float64,
        )
        mae[horizon_index] = np.mean(
            np.abs(residuals),
            axis=0,
            dtype=np.float64,
        )
        bias[horizon_index] = np.mean(
            residuals,
            axis=0,
            dtype=np.float64,
        )

    return TracePointMetrics(
        trace_id=first.trace_id,
        trace_start_step=first.trace_start_step,
        trace_num_steps=trace_num_steps,
        anchor_counts_by_horizon=actual_counts,
        mse_by_horizon_zone=mse,
        mae_by_horizon_zone=mae,
        bias_by_horizon_zone=bias,
    )


def evaluate_point_forecasts(
    records: Iterable[PointForecastRecord],
) -> PointMetricSummary:
    """对 one predictor/run 的完整 trace forecast set 计算冻结 point metrics。"""

    try:
        normalized = tuple(records)
    except TypeError as error:
        raise TypeError("records 必须是 PointForecastRecord 的有限 iterable") from error
    if not normalized:
        raise ValueError("records 必须至少包含一个 PointForecastRecord")
    if any(not isinstance(record, PointForecastRecord) for record in normalized):
        raise TypeError("records 必须全部是 PointForecastRecord")
    ordered = tuple(
        sorted(
            normalized,
            key=lambda record: (
                record.trace_id,
                record.sample.context.absolute_step,
                record.sample.sample_id,
            ),
        )
    )

    prediction_horizon = ordered[0].sample.context.prediction_horizon
    num_zones = ordered[0].sample.context.num_zones
    zone_hash = ordered[0].sample.context.zone_schema_sha256
    seen_anchors: set[tuple[str, int]] = set()
    seen_sample_ids: set[str] = set()
    trace_geometry: dict[str, tuple[int, int]] = {}
    grouped: dict[str, list[PointForecastRecord]] = {}

    for record in ordered:
        context = record.sample.context
        if context.prediction_horizon != prediction_horizon:
            raise ValueError("所有 traces 必须共享 prediction_horizon")
        if context.num_zones != num_zones:
            raise ValueError("所有 traces 必须共享 num_zones")
        if context.zone_schema_sha256 != zone_hash:
            raise ValueError("所有 traces 必须共享 zone_schema_sha256")

        anchor_key = (record.trace_id, context.absolute_step)
        if anchor_key in seen_anchors:
            raise ValueError("同一 trace_id/absolute_step 不能重复")
        seen_anchors.add(anchor_key)
        if record.sample.sample_id in seen_sample_ids:
            raise ValueError("sample_id 不能重复")
        seen_sample_ids.add(record.sample.sample_id)

        geometry = (record.trace_start_step, record.trace_num_steps)
        previous_geometry = trace_geometry.setdefault(record.trace_id, geometry)
        if previous_geometry != geometry:
            raise ValueError("同一 trace_id 的 start_step/num_steps 必须一致")
        grouped.setdefault(record.trace_id, []).append(record)

    trace_metrics = tuple(
        _trace_metrics(
            tuple(grouped[trace_id]),
            prediction_horizon,
            num_zones,
        )
        for trace_id in sorted(grouped)
    )
    return PointMetricSummary(
        trace_metrics=trace_metrics,
        prediction_horizon=prediction_horizon,
        num_zones=num_zones,
        zone_schema_sha256=zone_hash,
    )


__all__ = [
    "PointForecastRecord",
    "PointMetricSummary",
    "TracePointMetrics",
    "evaluate_point_forecasts",
]
