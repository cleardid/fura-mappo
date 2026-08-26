"""只依赖当前因果历史的确定性 point-demand baselines。"""

from __future__ import annotations

from dataclasses import dataclass
from numbers import Real

import numpy as np

from fura_mappo.prediction.interfaces import validate_forecast_for_context
from fura_mappo.prediction.models import DemandForecast, PredictionContext

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


__all__ = [
    "EWMADemandPredictor",
    "MaskedMeanDemandPredictor",
    "PersistenceDemandPredictor",
    "ZeroDemandPredictor",
]
