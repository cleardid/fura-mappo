"""只依赖当前因果历史的确定性 point-demand baselines。"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from numbers import Real

import numpy as np

from fura_mappo.prediction.dataset import VerifiedPredictionArtifact
from fura_mappo.prediction.interfaces import validate_forecast_for_context
from fura_mappo.prediction.models import (
    DemandForecast,
    PredictionContext,
    _normalize_float_array,
    _normalize_integer,
    _normalize_sha256,
)

_OFFICIAL_EWMA_ALPHAS = (0.25, 0.50, 0.75)


def _forecast_from_level(
    context: PredictionContext,
    level: np.ndarray,
) -> DemandForecast:
    """把 shape ``[Z]`` 的 level 复制到有效 future prefix。"""

    if not isinstance(context, PredictionContext):
        raise TypeError("context 必须是 PredictionContext")
    num_valid = min(
        context.prediction_horizon,
        max(context.steps_remaining - 1, 0),
    )
    valid_mask = np.zeros(context.prediction_horizon, dtype=np.bool_)
    valid_mask[:num_valid] = True
    mean = np.zeros(
        (context.prediction_horizon, context.num_zones),
        dtype=np.float64,
    )
    mean[:num_valid] = level
    forecast = DemandForecast(
        absolute_step=context.absolute_step,
        horizon=context.prediction_horizon,
        zone_schema_sha256=context.zone_schema_sha256,
        valid_mask=valid_mask,
        mean=mean,
    )
    validate_forecast_for_context(context, forecast)
    return forecast


def _normalize_verified_artifacts(
    artifacts: Iterable[VerifiedPredictionArtifact],
) -> tuple[VerifiedPredictionArtifact, ...]:
    """验证 fitting set，并返回不依赖 caller 顺序的 canonical tuple。"""

    try:
        normalized = tuple(artifacts)
    except TypeError as error:
        raise TypeError("artifacts 必须是 VerifiedPredictionArtifact 的有限 iterable") from error
    if not normalized:
        raise ValueError("artifacts 必须至少包含一个 VerifiedPredictionArtifact")
    if any(not isinstance(item, VerifiedPredictionArtifact) for item in normalized):
        raise TypeError("artifacts 必须全部是 VerifiedPredictionArtifact")

    expected_zone_schema = normalized[0].source.zone_schema_sha256
    expected_num_zones = normalized[0].source.num_zones
    realized_trace_hashes: set[str] = set()
    for verified in normalized:
        source = verified.source
        if source.zone_schema_sha256 != expected_zone_schema:
            raise ValueError("所有 artifacts 的 zone_schema_sha256 必须完全相同")
        if source.num_zones != expected_num_zones:
            raise ValueError("所有 artifacts 的 num_zones 必须完全相同")
        if source.realized_trace_sha256 in realized_trace_hashes:
            raise ValueError("artifacts 的 realized_trace_sha256 必须全部唯一")
        realized_trace_hashes.add(source.realized_trace_sha256)

    return tuple(
        sorted(
            normalized,
            key=lambda verified: (
                verified.source.realized_trace_sha256,
                verified.source.trace_id,
                verified.source.content_sha256,
            ),
        )
    )


def _normalize_fitted_array(value: object, name: str, ndim: int) -> np.ndarray:
    """返回 C-order、只读、有限且非负的 ``float64`` 防御性副本。"""

    return _normalize_float_array(value, name, ndim, nonnegative=True)


@dataclass(frozen=True, slots=True)
class ZeroDemandPredictor:
    """B0：所有有效 lead 都预测零需求。"""

    def predict(self, context: PredictionContext) -> DemandForecast:
        """返回 shape ``[P,Z]`` 的全零 point forecast。"""

        if not isinstance(context, PredictionContext):
            raise TypeError("context 必须是 PredictionContext")
        level = np.zeros(context.num_zones, dtype=np.float64)
        return _forecast_from_level(context, level)


@dataclass(frozen=True, slots=True)
class PersistenceDemandPredictor:
    """B1：把最近一个有效观测复制到所有有效 lead。"""

    def predict(self, context: PredictionContext) -> DemandForecast:
        """使用 ``history_mask`` 标记的最后一行构造 forecast。"""

        if not isinstance(context, PredictionContext):
            raise TypeError("context 必须是 PredictionContext")
        level = np.asarray(
            context.history_counts[context.history_mask][-1],
            dtype=np.float64,
        )
        return _forecast_from_level(context, level)


@dataclass(frozen=True, slots=True)
class MaskedMeanDemandPredictor:
    """B2：对有效历史行逐 zone 求算术平均。"""

    def predict(self, context: PredictionContext) -> DemandForecast:
        """排除左 padding，并保留有效的真实零需求观测。"""

        if not isinstance(context, PredictionContext):
            raise TypeError("context 必须是 PredictionContext")
        level = np.mean(
            context.history_counts[context.history_mask],
            axis=0,
            dtype=np.float64,
        )
        return _forecast_from_level(context, level)


@dataclass(frozen=True, slots=True)
class EWMADemandPredictor:
    """B3：从当前 context 的有效历史重新计算指数加权均值。"""

    alpha: float

    def __post_init__(self) -> None:
        """规范化并严格验证冻结的 official alpha grid。"""

        if isinstance(self.alpha, (bool, np.bool_)) or not isinstance(
            self.alpha,
            (Real, np.integer, np.floating),
        ):
            raise TypeError("alpha 必须是实数标量且不能是布尔值")
        normalized = float(self.alpha)
        if not np.isfinite(normalized) or normalized not in _OFFICIAL_EWMA_ALPHAS:
            raise ValueError("alpha 必须精确等于 0.25、0.50 或 0.75")
        object.__setattr__(self, "alpha", normalized)

    def predict(self, context: PredictionContext) -> DemandForecast:
        """按 oldest-to-newest 顺序从有限历史重新计算 EWMA。"""

        if not isinstance(context, PredictionContext):
            raise TypeError("context 必须是 PredictionContext")
        valid_history = np.asarray(
            context.history_counts[context.history_mask],
            dtype=np.float64,
        )
        state = valid_history[0].copy()
        one_minus_alpha = 1.0 - self.alpha
        for row in valid_history[1:]:
            state = self.alpha * row + one_minus_alpha * state
        return _forecast_from_level(context, state)


@dataclass(frozen=True, slots=True, eq=False)
class StaticClimatologyDemandPredictor:
    """B4：绑定 zone schema 的 train-fitted 静态逐 zone climatology。"""

    zone_schema_sha256: str
    climatology: np.ndarray

    def __post_init__(self) -> None:
        """验证 direct-construction fitted state，并建立无别名只读副本。"""

        zone_hash = _normalize_sha256(self.zone_schema_sha256, "zone_schema_sha256")
        climatology = _normalize_fitted_array(self.climatology, "climatology", 1)
        if climatology.shape[0] < 1:
            raise ValueError("climatology 形状必须为 [Z]，且 Z 至少为 1")
        object.__setattr__(self, "zone_schema_sha256", zone_hash)
        object.__setattr__(self, "climatology", climatology)

    def predict(self, context: PredictionContext) -> DemandForecast:
        """把 fitted climatology 复制到全部有效 future lead。"""

        if not isinstance(context, PredictionContext):
            raise TypeError("context 必须是 PredictionContext")
        if context.zone_schema_sha256 != self.zone_schema_sha256:
            raise ValueError("context.zone_schema_sha256 与 fitted predictor 不一致")
        if context.num_zones != self.climatology.shape[0]:
            raise ValueError("context.num_zones 与 fitted climatology 不一致")
        return _forecast_from_level(context, self.climatology)


@dataclass(frozen=True, slots=True, eq=False)
class AbsoluteStepClimatologyDemandPredictor:
    """B5：连续 common absolute-step support 上的 train-fitted climatology。"""

    zone_schema_sha256: str
    support_start_step: int
    step_means: np.ndarray

    def __post_init__(self) -> None:
        """验证 direct-construction fitted state，并建立无别名只读副本。"""

        zone_hash = _normalize_sha256(self.zone_schema_sha256, "zone_schema_sha256")
        support_start = _normalize_integer(
            self.support_start_step,
            "support_start_step",
            0,
        )
        step_means = _normalize_fitted_array(self.step_means, "step_means", 2)
        if step_means.shape[0] < 1 or step_means.shape[1] < 1:
            raise ValueError("step_means 形状必须为 [K,Z]，且 K、Z 均至少为 1")
        object.__setattr__(self, "zone_schema_sha256", zone_hash)
        object.__setattr__(self, "support_start_step", support_start)
        object.__setattr__(self, "step_means", step_means)

    @property
    def support_stop_step(self) -> int:
        """返回 fitted common support 的半开区间终点。"""

        return self.support_start_step + int(self.step_means.shape[0])

    def predict(self, context: PredictionContext) -> DemandForecast:
        """按 future absolute step 索引 B5；有效 lead 缺 support 时 hard fail。"""

        if not isinstance(context, PredictionContext):
            raise TypeError("context 必须是 PredictionContext")
        if context.zone_schema_sha256 != self.zone_schema_sha256:
            raise ValueError("context.zone_schema_sha256 与 fitted predictor 不一致")
        if context.num_zones != self.step_means.shape[1]:
            raise ValueError("context.num_zones 与 fitted step_means 不一致")

        num_valid = min(
            context.prediction_horizon,
            max(context.steps_remaining - 1, 0),
        )
        valid_mask = np.zeros(context.prediction_horizon, dtype=np.bool_)
        valid_mask[:num_valid] = True
        mean = np.zeros(
            (context.prediction_horizon, context.num_zones),
            dtype=np.float64,
        )
        if num_valid:
            first_required_step = context.absolute_step + 1
            last_required_step = context.absolute_step + num_valid
            if (
                first_required_step < self.support_start_step
                or last_required_step >= self.support_stop_step
            ):
                raise ValueError("required valid lead 超出 fitted absolute-step support")
            first_index = first_required_step - self.support_start_step
            mean[:num_valid] = self.step_means[first_index : first_index + num_valid]

        forecast = DemandForecast(
            absolute_step=context.absolute_step,
            horizon=context.prediction_horizon,
            zone_schema_sha256=context.zone_schema_sha256,
            valid_mask=valid_mask,
            mean=mean,
        )
        validate_forecast_for_context(context, forecast)
        return forecast


def fit_static_train_climatology(
    artifacts: Iterable[VerifiedPredictionArtifact],
) -> StaticClimatologyDemandPredictor:
    """从 verified train traces 按 trace-equal 权重拟合 B4。"""

    verified_artifacts = _normalize_verified_artifacts(artifacts)
    trace_means = [
        np.mean(
            verified.artifact.trace.counts,
            axis=0,
            dtype=np.float64,
        )
        for verified in verified_artifacts
    ]
    climatology = np.mean(
        np.stack(trace_means, axis=0),
        axis=0,
        dtype=np.float64,
    )
    return StaticClimatologyDemandPredictor(
        zone_schema_sha256=verified_artifacts[0].source.zone_schema_sha256,
        climatology=climatology,
    )


def fit_absolute_step_train_climatology(
    artifacts: Iterable[VerifiedPredictionArtifact],
) -> AbsoluteStepClimatologyDemandPredictor:
    """从 verified train traces 的 common support 按 trace-equal 权重拟合 B5。"""

    verified_artifacts = _normalize_verified_artifacts(artifacts)
    support_start = max(verified.artifact.trace.start_step for verified in verified_artifacts)
    support_stop = min(
        verified.artifact.trace.start_step + verified.artifact.trace.counts.shape[0]
        for verified in verified_artifacts
    )
    if support_start >= support_stop:
        raise ValueError("no common absolute-step support")

    support_length = support_stop - support_start
    supported_counts = []
    for verified in verified_artifacts:
        trace = verified.artifact.trace
        offset = support_start - trace.start_step
        supported_counts.append(trace.counts[offset : offset + support_length])
    step_means = np.mean(
        np.stack(supported_counts, axis=0),
        axis=0,
        dtype=np.float64,
    )
    return AbsoluteStepClimatologyDemandPredictor(
        zone_schema_sha256=verified_artifacts[0].source.zone_schema_sha256,
        support_start_step=support_start,
        step_means=step_means,
    )


__all__ = [
    "AbsoluteStepClimatologyDemandPredictor",
    "EWMADemandPredictor",
    "MaskedMeanDemandPredictor",
    "PersistenceDemandPredictor",
    "StaticClimatologyDemandPredictor",
    "ZeroDemandPredictor",
    "fit_absolute_step_train_climatology",
    "fit_static_train_climatology",
]
