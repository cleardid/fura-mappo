"""预测器公共 Protocol；核心层不依赖 PyTorch 或具体模型架构。"""

from __future__ import annotations

from typing import Protocol

import numpy as np

from fura_mappo.prediction.models import DemandForecast, PredictionContext


class DemandPredictor(Protocol):
    """把纯因果历史映射为相同 boundary 的 demand forecast。"""

    def predict(self, context: PredictionContext) -> DemandForecast:
        """生成候选 forecast；调用方随后必须执行 ``validate_forecast_for_context``。"""


def validate_forecast_for_context(
    context: PredictionContext,
    forecast: DemandForecast,
) -> None:
    """hard-validate predictor output 与其唯一 input context 的完整 binding。

    Episode future rows 不由 predictor 自行声明。Boundary ``t`` 可预测的真实 episode future 数为
    ``steps_remaining - 1``，再由 protocol horizon 截断。
    """

    if not isinstance(context, PredictionContext):
        raise TypeError("context 必须是 PredictionContext")
    if not isinstance(forecast, DemandForecast):
        raise TypeError("forecast 必须是 DemandForecast")
    if forecast.absolute_step != context.absolute_step:
        raise ValueError("forecast.absolute_step 必须等于 context.absolute_step")
    if forecast.horizon != context.prediction_horizon:
        raise ValueError("forecast.horizon 必须等于 context.prediction_horizon")
    if forecast.zone_schema_sha256 != context.zone_schema_sha256:
        raise ValueError("forecast.zone_schema_sha256 必须等于 context.zone_schema_sha256")
    if forecast.num_zones != context.num_zones:
        raise ValueError("forecast num_zones 必须等于 context num_zones")
    num_valid = min(
        context.prediction_horizon,
        max(context.steps_remaining - 1, 0),
    )
    expected_mask = np.zeros(context.prediction_horizon, dtype=np.bool_)
    expected_mask[:num_valid] = True
    if not np.array_equal(forecast.valid_mask, expected_mask):
        raise ValueError("forecast.valid_mask 与 context episode boundary 不一致")


__all__ = ["DemandPredictor", "validate_forecast_for_context"]
