"""需求事件、单步结果和轨迹数据对象。"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise
from numbers import Real

import numpy as np


def _contains_boolean(value: object) -> bool:
    """检查原始数组或嵌套序列中是否包含布尔标量。"""

    if isinstance(value, (bool, np.bool_)):
        return True
    if isinstance(value, np.ndarray):
        if np.issubdtype(value.dtype, np.bool_):
            return value.size > 0
        if value.dtype == np.dtype(object):
            return any(_contains_boolean(item) for item in value.flat)
        return False
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return any(_contains_boolean(item) for item in value)
    return False


def _normalize_integer(value: object, name: str, minimum: int) -> int:
    """将合法整数标量规范化为 Python ``int``。"""

    if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
        raise TypeError(f"{name} 必须是整数且不能是布尔值")
    normalized = int(value)
    if normalized < minimum:
        raise ValueError(f"{name} 必须大于或等于 {minimum}")
    return normalized


def _normalize_finite_real(value: object, name: str) -> float:
    """将合法有限实数规范化为 Python ``float``。"""

    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{name} 必须是实数且不能是布尔值")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError(f"{name} 必须是有限值")
    return normalized


def _normalize_float_array(value: object, name: str, ndim: int) -> np.ndarray:
    """复制并验证有限、非负的 ``float64`` 数组。"""

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
    if np.any(normalized < 0.0):
        raise ValueError(f"{name} 必须全部非负")
    normalized.setflags(write=False)
    return normalized


def _normalize_count_array(value: object, name: str, ndim: int) -> np.ndarray:
    """复制并验证非负的 ``int64`` 计数数组。"""

    if _contains_boolean(value):
        raise TypeError(f"{name} 不能包含布尔值")
    array = np.asarray(value)
    if array.ndim != ndim:
        raise ValueError(f"{name} 必须是 {ndim} 维数组")
    if np.issubdtype(array.dtype, np.bool_) or not np.issubdtype(array.dtype, np.integer):
        raise TypeError(f"{name} 必须包含整数且不能包含布尔值")

    normalized = np.array(array, dtype=np.int64, copy=True)
    if np.any(normalized < 0):
        raise ValueError(f"{name} 必须全部非负")
    normalized.setflags(write=False)
    return normalized


def _normalize_events(value: object) -> tuple[DemandEvent, ...]:
    """将事件集合防御性转换为元组并验证元素类型。"""

    try:
        events = tuple(value)  # type: ignore[arg-type]
    except TypeError as exc:
        raise TypeError("events 必须是 DemandEvent 的可迭代对象") from exc
    if not all(isinstance(event, DemandEvent) for event in events):
        raise TypeError("events 中每一项都必须是 DemandEvent")
    return events


def _validate_strictly_increasing_event_ids(events: tuple[DemandEvent, ...]) -> None:
    """验证事件 ID 严格递增。"""

    for previous, current in pairwise(events):
        if current.event_id <= previous.event_id:
            raise ValueError("events 中的 event_id 必须严格递增")


@dataclass(frozen=True, slots=True)
class DemandEvent:
    """描述一个外生需求事件。

    Attributes:
        event_id: 当前需求轨迹中的非负事件编号。
        arrival_step: 事件到达的非负时间步。
        zone_id: 事件所属的非负区域编号。
        position: 二维有限坐标，形状为 ``[2]``。
        priority: 位于闭区间 ``[0.0, 1.0]`` 的优先级。
        service_time: 至少为 1 的服务时长。
        deadline: 严格晚于到达时间步的截止时间。
    """

    event_id: int
    arrival_step: int
    zone_id: int
    position: tuple[float, float]
    priority: float
    service_time: int
    deadline: int

    def __post_init__(self) -> None:
        """规范化标量并验证事件局部约束。"""

        event_id = _normalize_integer(self.event_id, "event_id", 0)
        arrival_step = _normalize_integer(self.arrival_step, "arrival_step", 0)
        zone_id = _normalize_integer(self.zone_id, "zone_id", 0)
        service_time = _normalize_integer(self.service_time, "service_time", 1)
        deadline = _normalize_integer(self.deadline, "deadline", 0)

        if not isinstance(self.position, tuple):
            raise TypeError("position 必须是恰好包含两个坐标的 tuple")
        if len(self.position) != 2:
            raise ValueError("position 必须恰好包含两个坐标")
        position = (
            _normalize_finite_real(self.position[0], "position[0]"),
            _normalize_finite_real(self.position[1], "position[1]"),
        )

        priority = _normalize_finite_real(self.priority, "priority")
        if not 0.0 <= priority <= 1.0:
            raise ValueError("priority 必须位于 [0.0, 1.0]")
        if deadline <= arrival_step:
            raise ValueError("deadline 必须严格晚于 arrival_step")

        object.__setattr__(self, "event_id", event_id)
        object.__setattr__(self, "arrival_step", arrival_step)
        object.__setattr__(self, "zone_id", zone_id)
        object.__setattr__(self, "position", position)
        object.__setattr__(self, "priority", priority)
        object.__setattr__(self, "service_time", service_time)
        object.__setattr__(self, "deadline", deadline)


@dataclass(frozen=True, slots=True, eq=False)
class DemandStep:
    """保存单个时间步的需求强度、计数和事件。

    Attributes:
        step: 非负绝对时间步。
        intensity: 各区域强度，形状 ``[num_zones]``，dtype 为 ``float64``。
        counts: 各区域事件计数，形状 ``[num_zones]``，dtype 为 ``int64``。
        events: 按严格递增 event ID 排列的事件元组。
    """

    step: int
    intensity: np.ndarray
    counts: np.ndarray
    events: tuple[DemandEvent, ...]

    def __post_init__(self) -> None:
        """复制输入数据并验证单步内部一致性。"""

        step = _normalize_integer(self.step, "step", 0)
        intensity = _normalize_float_array(self.intensity, "intensity", 1)
        if intensity.size < 1:
            raise ValueError("DemandStep 必须至少包含一个区域")
        counts = _normalize_count_array(self.counts, "counts", 1)
        if intensity.shape != counts.shape:
            raise ValueError("intensity 和 counts 的形状必须完全一致")

        events = _normalize_events(self.events)
        actual_counts = np.zeros(counts.shape, dtype=np.int64)
        for event in events:
            if event.arrival_step != step:
                raise ValueError("事件 arrival_step 必须等于 DemandStep.step")
            if event.zone_id >= counts.size:
                raise ValueError("事件 zone_id 超出 DemandStep 的区域范围")
            actual_counts[event.zone_id] += 1
        if not np.array_equal(actual_counts, counts):
            raise ValueError("按区域聚合的事件数量必须与 counts 完全一致")
        _validate_strictly_increasing_event_ids(events)

        object.__setattr__(self, "step", step)
        object.__setattr__(self, "intensity", intensity)
        object.__setattr__(self, "counts", counts)
        object.__setattr__(self, "events", events)


@dataclass(frozen=True, slots=True, eq=False)
class DemandTrace:
    """保存一段连续需求轨迹。

    Attributes:
        start_step: 轨迹第一行对应的非负绝对时间步。
        counts: 每步各区域计数，形状 ``[num_steps, num_zones]``，dtype 为 ``int64``。
        intensities: 每步各区域强度，形状 ``[num_steps, num_zones]``，dtype 为
            ``float64``。
        events: 按严格递增 event ID 排列的全局扁平事件元组。
    """

    start_step: int
    counts: np.ndarray
    intensities: np.ndarray
    events: tuple[DemandEvent, ...]

    def __post_init__(self) -> None:
        """复制输入数据并验证轨迹内部一致性。"""

        start_step = _normalize_integer(self.start_step, "start_step", 0)
        counts = _normalize_count_array(self.counts, "counts", 2)
        intensities = _normalize_float_array(self.intensities, "intensities", 2)
        if counts.shape != intensities.shape:
            raise ValueError("counts 和 intensities 的形状必须完全一致")
        num_steps, num_zones = counts.shape
        if num_steps < 1:
            raise ValueError("DemandTrace 必须至少包含一个时间步")
        if num_zones < 1:
            raise ValueError("DemandTrace 必须至少包含一个区域")

        events = _normalize_events(self.events)
        actual_counts = np.zeros(counts.shape, dtype=np.int64)
        stop_step = start_step + num_steps
        for event in events:
            if not start_step <= event.arrival_step < stop_step:
                raise ValueError("事件 arrival_step 超出 DemandTrace 的时间范围")
            if event.zone_id >= num_zones:
                raise ValueError("事件 zone_id 超出 DemandTrace 的区域范围")
            actual_counts[event.arrival_step - start_step, event.zone_id] += 1
        if not np.array_equal(actual_counts, counts):
            raise ValueError("按时间步和区域聚合的事件数量必须与 counts 完全一致")
        _validate_strictly_increasing_event_ids(events)

        object.__setattr__(self, "start_step", start_step)
        object.__setattr__(self, "counts", counts)
        object.__setattr__(self, "intensities", intensities)
        object.__setattr__(self, "events", events)
