"""需求过程公共状态接口和平稳 Poisson 实现。"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from numbers import Real

import numpy as np
import numpy.typing as npt

from fura_mappo.demand.models import DemandEvent, DemandStep, DemandTrace, _contains_boolean
from fura_mappo.utils.seeding import create_numpy_generator


def _normalize_numeric_array(value: object, name: str, ndim: int) -> np.ndarray:
    """复制并规范化有限实数数组。"""

    if _contains_boolean(value):
        raise TypeError(f"{name} 不能包含布尔值")
    array = np.asarray(value)
    if array.ndim != ndim:
        raise ValueError(f"{name} 必须是 {ndim} 维数组")
    if np.issubdtype(array.dtype, np.bool_) or not np.issubdtype(array.dtype, np.number):
        raise TypeError(f"{name} 必须包含实数")
    if np.issubdtype(array.dtype, np.complexfloating):
        raise TypeError(f"{name} 必须包含实数")

    normalized = np.array(array, dtype=np.float64, copy=True)
    if not np.all(np.isfinite(normalized)):
        raise ValueError(f"{name} 必须全部为有限值")
    return normalized


def _normalize_real_range(value: object, name: str) -> tuple[float, float]:
    """验证并复制闭区间实数范围。"""

    if isinstance(value, (str, bytes, Mapping)) or not isinstance(value, Sequence):
        raise TypeError(f"{name} 必须是恰好包含两个实数的序列")
    items = tuple(value)
    if len(items) != 2:
        raise ValueError(f"{name} 必须恰好包含两个元素")

    normalized: list[float] = []
    for item in items:
        if isinstance(item, bool) or not isinstance(item, Real):
            raise TypeError(f"{name} 必须包含实数且不能包含布尔值")
        number = float(item)
        if not math.isfinite(number):
            raise ValueError(f"{name} 必须全部为有限值")
        normalized.append(number)
    return normalized[0], normalized[1]


def _normalize_integer_range(value: object, name: str) -> tuple[int, int]:
    """验证并复制闭区间整数范围。"""

    if isinstance(value, (str, bytes, Mapping)) or not isinstance(value, Sequence):
        raise TypeError(f"{name} 必须是恰好包含两个整数的序列")
    items = tuple(value)
    if len(items) != 2:
        raise ValueError(f"{name} 必须恰好包含两个元素")

    normalized: list[int] = []
    for item in items:
        if isinstance(item, bool) or not isinstance(item, (int, np.integer)):
            raise TypeError(f"{name} 必须包含整数且不能包含布尔值")
        normalized.append(int(item))
    return normalized[0], normalized[1]


class DemandProcess(ABC):
    """统一管理需求过程的随机数、时间步和事件编号状态。"""

    def __init__(self, seed: int) -> None:
        """使用显式种子创建可立即采样的需求过程。"""

        rng = create_numpy_generator(seed)
        self._base_seed = int(seed)
        self._rng = rng
        self._current_step = 0
        self._next_event_id = 0

    @property
    def base_seed(self) -> int:
        """返回当前用于重放轨迹的基准种子。"""

        return self._base_seed

    @property
    def current_step(self) -> int:
        """返回下一次 ``step`` 将生成的绝对时间步。"""

        return self._current_step

    @property
    def next_event_id(self) -> int:
        """返回下一事件将使用的编号。"""

        return self._next_event_id

    def reset(self, seed: int | None = None) -> None:
        """重建独立 Generator，并将时间步和事件编号重置为零。

        Args:
            seed: 新基准种子；为 ``None`` 时复用当前基准种子。
        """

        base_seed = self._base_seed if seed is None else seed
        rng = create_numpy_generator(base_seed)
        self._base_seed = int(base_seed)
        self._rng = rng
        self._current_step = 0
        self._next_event_id = 0

    def step(self) -> DemandStep:
        """生成当前时间步，并在成功构造结果后推进公共状态。"""

        result = self._sample_step(self._current_step, self._next_event_id)
        if not isinstance(result, DemandStep):
            raise TypeError("_sample_step 必须返回 DemandStep")
        if result.step != self._current_step:
            raise ValueError("_sample_step 返回了错误的 step")

        expected_ids = tuple(range(self._next_event_id, self._next_event_id + len(result.events)))
        actual_ids = tuple(event.event_id for event in result.events)
        if actual_ids != expected_ids:
            raise ValueError("_sample_step 必须从首个 event_id 连续分配事件编号")

        self._current_step += 1
        self._next_event_id += len(result.events)
        return result

    def generate(self, num_steps: int, seed: int | None = None) -> DemandTrace:
        """从当前状态生成连续需求轨迹。

        Args:
            num_steps: 要生成的正整数时间步数。
            seed: 指定时先以新种子重置；为 ``None`` 时从当前状态继续。

        Returns:
            计数形状为 ``[num_steps, num_zones]`` 的连续需求轨迹。

        Raises:
            TypeError: ``num_steps`` 不是整数或是布尔值时抛出。
            ValueError: ``num_steps`` 不是正数时抛出。
        """

        if isinstance(num_steps, bool) or not isinstance(num_steps, (int, np.integer)):
            raise TypeError("num_steps 必须是整数且不能是布尔值")
        normalized_num_steps = int(num_steps)
        if normalized_num_steps <= 0:
            raise ValueError("num_steps 必须是正整数")
        if seed is not None:
            self.reset(seed)

        start_step = self._current_step
        steps = tuple(self.step() for _ in range(normalized_num_steps))
        counts = np.stack([item.counts for item in steps], axis=0)
        intensities = np.stack([item.intensity for item in steps], axis=0)
        events = tuple(event for item in steps for event in item.events)
        return DemandTrace(
            start_step=start_step,
            counts=counts,
            intensities=intensities,
            events=events,
        )

    @abstractmethod
    def _sample_step(self, step: int, first_event_id: int) -> DemandStep:
        """采样一个时间步，但不修改公共时间和事件编号状态。"""


class StationaryPoissonDemand(DemandProcess):
    """在固定矩形区域中生成平稳 Poisson 外生需求。"""

    def __init__(
        self,
        *,
        seed: int,
        intensities: npt.ArrayLike,
        zone_bounds: npt.ArrayLike,
        priority_range: Sequence[float],
        service_time_range: Sequence[int],
        deadline_offset_range: Sequence[int],
    ) -> None:
        """验证配置并创建平稳 Poisson 需求过程。

        Args:
            seed: 非负整数随机种子。
            intensities: 逐区域 Poisson 强度，形状 ``[num_zones]``，保存为
                ``float64``。
            zone_bounds: 区域边界，形状 ``[num_zones, 4]``，每行为
                ``(x_min, x_max, y_min, y_max)``，保存为 ``float64``。
            priority_range: 连续均匀优先级的闭区间配置。
            service_time_range: 离散均匀服务时长的闭区间配置。
            deadline_offset_range: 离散均匀截止偏移的闭区间配置。
        """

        normalized_intensities = _normalize_numeric_array(intensities, "intensities", 1)
        if normalized_intensities.size < 1:
            raise ValueError("intensities 必须至少包含一个区域")
        if np.any(normalized_intensities < 0.0):
            raise ValueError("intensities 必须全部非负")
        poisson_limit = float(np.iinfo(np.int64).max) - 10.0 * math.sqrt(
            float(np.iinfo(np.int64).max)
        )
        if np.any(normalized_intensities > poisson_limit):
            raise ValueError("intensities 超出 NumPy Poisson 采样的安全范围")

        normalized_bounds = _normalize_numeric_array(zone_bounds, "zone_bounds", 2)
        if normalized_bounds.shape != (normalized_intensities.size, 4):
            raise ValueError("zone_bounds 形状必须为 [num_zones, 4] 并匹配 intensities")
        if np.any(normalized_bounds[:, 0] >= normalized_bounds[:, 1]):
            raise ValueError("zone_bounds 必须满足 x_min < x_max")
        if np.any(normalized_bounds[:, 2] >= normalized_bounds[:, 3]):
            raise ValueError("zone_bounds 必须满足 y_min < y_max")
        with np.errstate(over="ignore"):
            widths = normalized_bounds[:, 1] - normalized_bounds[:, 0]
            heights = normalized_bounds[:, 3] - normalized_bounds[:, 2]
        if not np.all(np.isfinite(widths)) or not np.all(np.isfinite(heights)):
            raise ValueError("zone_bounds 的坐标跨度必须为有限值")

        normalized_priority = _normalize_real_range(priority_range, "priority_range")
        if not 0.0 <= normalized_priority[0] <= normalized_priority[1] <= 1.0:
            raise ValueError("priority_range 必须满足 0.0 <= low <= high <= 1.0")

        normalized_service = _normalize_integer_range(service_time_range, "service_time_range")
        normalized_deadline = _normalize_integer_range(
            deadline_offset_range, "deadline_offset_range"
        )
        max_integer = int(np.iinfo(np.int64).max)
        for name, bounds in (
            ("service_time_range", normalized_service),
            ("deadline_offset_range", normalized_deadline),
        ):
            if not 1 <= bounds[0] <= bounds[1]:
                raise ValueError(f"{name} 必须满足 1 <= low <= high")
            if bounds[1] > max_integer:
                raise ValueError(f"{name} 上界不能超过 int64 最大值")

        normalized_intensities.setflags(write=False)
        normalized_bounds.setflags(write=False)
        self._intensities = normalized_intensities
        self._zone_bounds = normalized_bounds
        self._priority_range = normalized_priority
        self._service_time_range = normalized_service
        self._deadline_offset_range = normalized_deadline
        super().__init__(seed)

    def _sample_step(self, step: int, first_event_id: int) -> DemandStep:
        """使用实例私有 Generator 采样一个平稳需求时间步。"""

        counts = np.asarray(self._rng.poisson(self._intensities), dtype=np.int64)
        events: list[DemandEvent] = []
        next_event_id = first_event_id

        for zone_id, zone_count_value in enumerate(counts):
            zone_count = int(zone_count_value)
            if zone_count == 0:
                continue

            x_min, x_max, y_min, y_max = self._zone_bounds[zone_id]
            x_positions = self._rng.uniform(x_min, x_max, size=zone_count)
            y_positions = self._rng.uniform(y_min, y_max, size=zone_count)
            x_positions = np.minimum(x_positions, np.nextafter(x_max, x_min))
            y_positions = np.minimum(y_positions, np.nextafter(y_max, y_min))

            priority_low, priority_high = self._priority_range
            if priority_low == priority_high:
                priorities = np.full(zone_count, priority_low, dtype=np.float64)
            else:
                priorities = self._rng.uniform(priority_low, priority_high, size=zone_count)

            service_times = self._sample_integer_range(self._service_time_range, zone_count)
            deadline_offsets = self._sample_integer_range(self._deadline_offset_range, zone_count)

            for index in range(zone_count):
                deadline_offset = int(deadline_offsets[index])
                events.append(
                    DemandEvent(
                        event_id=next_event_id,
                        arrival_step=step,
                        zone_id=zone_id,
                        position=(
                            float(x_positions[index]),
                            float(y_positions[index]),
                        ),
                        priority=float(priorities[index]),
                        service_time=int(service_times[index]),
                        deadline=step + deadline_offset,
                    )
                )
                next_event_id += 1

        return DemandStep(
            step=step,
            intensity=self._intensities,
            counts=counts,
            events=tuple(events),
        )

    def _sample_integer_range(self, bounds: tuple[int, int], size: int) -> np.ndarray:
        """从闭区间采样 ``int64`` 数组，形状为 ``[size]``。"""

        low, high = bounds
        if low == high:
            return np.full(size, low, dtype=np.int64)
        return self._rng.integers(low, high, size=size, dtype=np.int64, endpoint=True)
