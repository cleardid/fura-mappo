"""确定性资源服务环境的公共数据模型。"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from numbers import Real
from typing import TypeAlias

import numpy as np

from fura_mappo.demand import DemandEvent

Position: TypeAlias = tuple[float, float]


def _normalize_finite_real(value: object, name: str) -> float:
    """规范化有限实数并显式拒绝布尔值。"""

    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise TypeError(f"{name} 必须是实数且不能是布尔值")
    try:
        normalized = float(value)
    except OverflowError as error:
        raise ValueError(f"{name} 必须能转换为有限 Python float") from error
    if not math.isfinite(normalized):
        raise ValueError(f"{name} 必须是有限值")
    return normalized


def _normalize_nonnegative_integer(value: object, name: str) -> int:
    """规范化非负整数并显式拒绝布尔值。"""

    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)):
        raise TypeError(f"{name} 必须是整数且不能是布尔值")
    normalized = int(value)
    if normalized < 0:
        raise ValueError(f"{name} 必须是非负整数")
    return normalized


def _sequence_items(value: object, name: str) -> tuple[object, ...]:
    """读取可重复序列或 ndarray，不接受字符串和 Mapping。"""

    if isinstance(value, np.ndarray):
        if value.ndim == 0:
            raise TypeError(f"{name} 必须是序列")
        return tuple(value)
    if isinstance(value, (str, bytes, Mapping)) or not isinstance(value, Sequence):
        raise TypeError(f"{name} 必须是序列")
    return tuple(value)


def _normalize_position(value: object, name: str) -> Position:
    """规范化有限二维坐标。"""

    items = _sequence_items(value, name)
    if len(items) != 2:
        raise ValueError(f"{name} 必须恰好包含两个坐标")
    return (
        _normalize_finite_real(items[0], f"{name}[0]"),
        _normalize_finite_real(items[1], f"{name}[1]"),
    )


class ResourceStatus(str, Enum):
    """资源在当前边界的派生状态。"""

    AVAILABLE = "available"
    SERVING = "serving"


class TaskStatus(str, Enum):
    """任务在当前边界或 episode 终局的派生状态。"""

    WAITING = "waiting"
    IN_SERVICE = "in_service"
    COMPLETED = "completed"
    EXPIRED = "expired"
    TRUNCATED = "truncated"


@dataclass(frozen=True, slots=True)
class ResourceServiceConfig:
    """资源服务环境的最小物理配置。

    Attributes:
        initial_resource_positions: 初始连续二维位置，逻辑形状为
            ``[num_resources, 2]``。
        movement_speed: 每个时间槽允许的最大欧氏移动距离。
    """

    initial_resource_positions: tuple[Position, ...]
    movement_speed: float

    def __post_init__(self) -> None:
        """防御性规范化配置且不修改调用方输入。"""

        positions = _sequence_items(
            self.initial_resource_positions,
            "initial_resource_positions",
        )
        if not positions:
            raise ValueError("initial_resource_positions 必须至少包含一个资源")
        normalized_positions = tuple(
            _normalize_position(position, f"initial_resource_positions[{index}]")
            for index, position in enumerate(positions)
        )
        movement_speed = _normalize_finite_real(self.movement_speed, "movement_speed")
        if movement_speed <= 0.0:
            raise ValueError("movement_speed 必须严格大于零")

        object.__setattr__(self, "initial_resource_positions", normalized_positions)
        object.__setattr__(self, "movement_speed", movement_speed)


@dataclass(frozen=True, slots=True)
class IdleAction:
    """让 AVAILABLE 资源在当前槽保持空闲。"""


@dataclass(frozen=True, slots=True)
class ContinueAction:
    """让 SERVING 资源继续其不可抢占服务。"""


@dataclass(frozen=True, slots=True)
class MoveAction:
    """让 AVAILABLE 资源在当前槽朝有限二维目标移动。"""

    target_position: Position

    def __post_init__(self) -> None:
        """防御性规范化目标坐标。"""

        object.__setattr__(
            self,
            "target_position",
            _normalize_position(self.target_position, "target_position"),
        )


@dataclass(frozen=True, slots=True)
class ServeAction:
    """请求 AVAILABLE 资源服务当前 WAITING 任务。"""

    event_id: int

    def __post_init__(self) -> None:
        """规范化非负事件编号。"""

        object.__setattr__(
            self,
            "event_id",
            _normalize_nonnegative_integer(self.event_id, "event_id"),
        )


ResourceAction: TypeAlias = IdleAction | ContinueAction | MoveAction | ServeAction


@dataclass(frozen=True, slots=True)
class ResourceSnapshot:
    """单个资源的不可变边界快照。"""

    resource_id: int
    position: Position
    status: ResourceStatus
    assigned_event_id: int | None


@dataclass(frozen=True, slots=True)
class TaskSnapshot:
    """单个已到达活动任务的不可变边界快照。"""

    event: DemandEvent
    status: TaskStatus
    assigned_resource_id: int | None
    remaining_service: int
    service_start_step: int | None
    completion_time: int | None


@dataclass(frozen=True, slots=True)
class EnvironmentSnapshot:
    """环境全局当前状态；不等同于未来 RL actor observation。"""

    absolute_step: int
    steps_remaining: int
    resources: tuple[ResourceSnapshot, ...]
    active_tasks: tuple[TaskSnapshot, ...]
    current_arrivals: tuple[DemandEvent, ...]


@dataclass(frozen=True, slots=True)
class StepMetrics:
    """一个槽及其结束边界的组成指标。"""

    absolute_step: int
    arrived: int
    completed: int
    expired: int
    truncated: int
    service_slots: int
    movement_slots: int
    idle_slots: int
    movement_distance: float
    duplicate_assignment_conflicts: int
    zero_distance_moves: int


@dataclass(frozen=True, slots=True)
class EpisodeMetrics:
    """由终局任务账本和资源槽累计量构造的 episode 指标。"""

    arrived: int
    completed: int
    expired: int
    truncated: int
    arrived_priority_sum: float
    completed_priority_sum: float
    expired_priority_sum: float
    truncated_priority_sum: float
    demanded_service_work: int
    service_slots: int
    movement_slots: int
    idle_slots: int
    movement_distance: float
    completed_service_work: int
    expired_service_work: int
    truncated_service_work: int
    expired_remaining_work: int
    truncated_remaining_work: int
    service_start_wait_sum: int
    service_start_count: int
    completed_response_sum: int
    completed_response_count: int
    duplicate_assignment_conflicts: int
    zero_distance_moves: int
    per_zone_arrived: tuple[int, ...]
    per_zone_completed: tuple[int, ...]
    per_zone_expired: tuple[int, ...]
    per_zone_truncated: tuple[int, ...]
    completion_rate: float | None
    expiration_rate: float | None
    truncation_rate: float | None
    mean_service_start_wait: float | None
    mean_completed_response: float | None


@dataclass(frozen=True, slots=True)
class StepResult:
    """一次成功环境转换的不可变结果。"""

    next_snapshot: EnvironmentSnapshot | None
    step_metrics: StepMetrics
    is_terminal: bool
    episode_metrics: EpisodeMetrics | None


__all__ = [
    "ContinueAction",
    "EnvironmentSnapshot",
    "EpisodeMetrics",
    "IdleAction",
    "MoveAction",
    "Position",
    "ResourceAction",
    "ResourceServiceConfig",
    "ResourceSnapshot",
    "ResourceStatus",
    "ServeAction",
    "StepMetrics",
    "StepResult",
    "TaskSnapshot",
    "TaskStatus",
]
