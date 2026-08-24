"""从环境当前到达流构造纯因果、bounded demand history。"""

from __future__ import annotations

import numpy as np

from fura_mappo.demand import DemandEvent
from fura_mappo.envs import EnvironmentSnapshot
from fura_mappo.prediction.models import (
    PredictionContext,
    ZoneSchema,
    _normalize_integer,
)


class ObservedDemandHistory:
    """逐 decision boundary 累积 realized zone counts 的确定性在线 buffer。

    实例只保存 count rows、boundary counters 和静态 zone identity；不接收或保留
    ``DemandTrace``、未来事件、intensity、seed、config 或 artifact provenance。
    """

    def __init__(
        self,
        zone_schema: ZoneSchema,
        history_length: int,
        prediction_horizon: int,
    ) -> None:
        """创建空历史；首个 ``observe`` 可位于任意合法绝对边界。"""

        if not isinstance(zone_schema, ZoneSchema):
            raise TypeError("zone_schema 必须是 ZoneSchema")
        self._zone_schema_sha256 = zone_schema.sha256
        self._num_zones = zone_schema.num_zones
        self._history_length = _normalize_integer(history_length, "history_length", 1)
        self._prediction_horizon = _normalize_integer(
            prediction_horizon,
            "prediction_horizon",
            1,
        )
        self._rows: tuple[np.ndarray, ...] = ()
        self._last_absolute_step: int | None = None
        self._episode_stop_step: int | None = None

    def reset(self) -> None:
        """清空 episode-local 历史，不改变静态协议参数。"""

        self._rows = ()
        self._last_absolute_step = None
        self._episode_stop_step = None

    @property
    def history_length(self) -> int:
        """返回 bounded buffer 长度。"""

        return self._history_length

    @property
    def prediction_horizon(self) -> int:
        """返回 context 中声明的预测 horizon。"""

        return self._prediction_horizon

    def observe(self, snapshot: EnvironmentSnapshot) -> PredictionContext:
        """消费当前 boundary arrivals 并返回包含当前 ``t`` 的 context。

        相邻调用必须来自同一 episode 的连续边界。验证和 context 构造全部成功后才提交
        buffer 状态，因此非法 snapshot 不会部分推进在线历史。
        """

        if not isinstance(snapshot, EnvironmentSnapshot):
            raise TypeError("snapshot 必须是 EnvironmentSnapshot")
        absolute_step = _normalize_integer(snapshot.absolute_step, "snapshot.absolute_step", 0)
        steps_remaining = _normalize_integer(
            snapshot.steps_remaining,
            "snapshot.steps_remaining",
            1,
        )
        episode_stop_step = absolute_step + steps_remaining
        if self._last_absolute_step is not None:
            if absolute_step != self._last_absolute_step + 1:
                raise ValueError("online history 必须按连续 absolute_step 观察")
            if episode_stop_step != self._episode_stop_step:
                raise ValueError("online history 不能跨 episode 或改变 stop boundary")

        current_counts = np.zeros(self._num_zones, dtype=np.int64)
        try:
            arrivals = tuple(snapshot.current_arrivals)
        except TypeError as error:
            raise TypeError("snapshot.current_arrivals 必须是 DemandEvent 序列") from error
        for event in arrivals:
            if not isinstance(event, DemandEvent):
                raise TypeError("snapshot.current_arrivals 每一项都必须是 DemandEvent")
            if event.arrival_step != absolute_step:
                raise ValueError("current arrival 的 arrival_step 必须等于 snapshot.absolute_step")
            if event.zone_id >= self._num_zones:
                raise ValueError("current arrival 的 zone_id 超出 ZoneSchema")
            current_counts[event.zone_id] += 1

        candidate_rows = (*self._rows, current_counts)
        if len(candidate_rows) > self._history_length:
            candidate_rows = candidate_rows[-self._history_length :]
        history = np.zeros(
            (self._history_length, self._num_zones),
            dtype=np.int64,
        )
        mask = np.zeros(self._history_length, dtype=np.bool_)
        observed = len(candidate_rows)
        history[-observed:, :] = np.stack(candidate_rows, axis=0)
        mask[-observed:] = True
        context = PredictionContext(
            absolute_step=absolute_step,
            steps_remaining=steps_remaining,
            history_counts=history,
            history_mask=mask,
            zone_schema_sha256=self._zone_schema_sha256,
            prediction_horizon=self._prediction_horizon,
        )

        self._rows = tuple(np.array(row, dtype=np.int64, copy=True) for row in candidate_rows)
        self._last_absolute_step = absolute_step
        self._episode_stop_step = episode_stop_step
        return context


__all__ = ["ObservedDemandHistory"]
