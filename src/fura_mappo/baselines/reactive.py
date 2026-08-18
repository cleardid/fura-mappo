"""仅使用当前环境快照的确定性 Reactive 控制器。"""

from __future__ import annotations

import math
from numbers import Real

import numpy as np

from fura_mappo.envs._movement import _calculate_single_slot_move
from fura_mappo.envs.models import (
    ContinueAction,
    EnvironmentSnapshot,
    IdleAction,
    MoveAction,
    Position,
    ResourceAction,
    ResourceSnapshot,
    ResourceStatus,
    ServeAction,
    TaskSnapshot,
    TaskStatus,
)


def _normalize_movement_speed(value: object) -> float:
    """规范化有限正速度并显式拒绝布尔值。"""

    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise TypeError("movement_speed 必须是实数且不能是布尔值")
    try:
        normalized = float(value)
    except OverflowError as error:
        raise ValueError("movement_speed 必须能转换为有限 Python float") from error
    if not math.isfinite(normalized):
        raise ValueError("movement_speed 必须是有限值")
    if normalized <= 0.0:
        raise ValueError("movement_speed 必须严格大于零")
    return normalized


def _finite_distance(resource: ResourceSnapshot, task: TaskSnapshot) -> float | None:
    """返回资源到任务的有限欧氏距离；不可有限表示时返回 ``None``。"""

    dx = task.event.position[0] - resource.position[0]
    dy = task.event.position[1] - resource.position[1]
    if not math.isfinite(dx) or not math.isfinite(dy):
        return None
    distance = math.hypot(dx, dy)
    return distance if math.isfinite(distance) else None


def _exact_travel_slots(
    current: Position,
    target: Position,
    movement_speed: float,
    travel_budget: int,
) -> int | None:
    """用共享单槽原语求精确浮点移动槽数，不使用解析近似。"""

    if travel_budget < 0:
        return None
    if current == target:
        return 0

    position = current
    for travel_slots in range(1, travel_budget + 1):
        try:
            move = _calculate_single_slot_move(position, target, movement_speed)
        except ValueError:
            return None
        position = move.position
        if position == target:
            return travel_slots
    return None


class ReactiveController:
    """无状态、无随机数且仅消费当前快照的集中式反应控制器。"""

    __slots__ = ("_movement_speed",)

    def __init__(self, movement_speed: float) -> None:
        """保存与配对环境一致的有限正移动速度。"""

        self._movement_speed = _normalize_movement_speed(movement_speed)

    def act(self, snapshot: EnvironmentSnapshot) -> tuple[ResourceAction, ...]:
        """按冻结的任务紧迫度和精确可达性生成确定性动作。"""

        if not isinstance(snapshot, EnvironmentSnapshot):
            raise TypeError("snapshot 必须是 EnvironmentSnapshot")
        for index, resource in enumerate(snapshot.resources):
            if resource.resource_id != index:
                raise ValueError("snapshot.resources 必须按连续 resource_id 排列")

        actions: list[ResourceAction] = [IdleAction() for _ in snapshot.resources]
        available = [False] * len(snapshot.resources)
        for resource in snapshot.resources:
            if resource.status is ResourceStatus.SERVING:
                actions[resource.resource_id] = ContinueAction()
            elif resource.status is ResourceStatus.AVAILABLE:
                available[resource.resource_id] = True
            else:
                raise ValueError("resource status 必须是 AVAILABLE 或 SERVING")

        stop_step = snapshot.absolute_step + snapshot.steps_remaining
        waiting_tasks = sorted(
            (task for task in snapshot.active_tasks if task.status is TaskStatus.WAITING),
            key=lambda task: (
                min(task.event.deadline, stop_step) - task.remaining_service,
                -task.event.priority,
                task.event.arrival_step,
                task.event.event_id,
            ),
        )

        for task in waiting_tasks:
            effective_deadline = min(task.event.deadline, stop_step)
            travel_budget = effective_deadline - task.remaining_service - snapshot.absolute_step
            if travel_budget < 0:
                continue

            choices: list[tuple[int, float, int]] = []
            for resource in snapshot.resources:
                resource_id = resource.resource_id
                if not available[resource_id]:
                    continue
                distance = _finite_distance(resource, task)
                if distance is None:
                    continue
                travel_slots = _exact_travel_slots(
                    resource.position,
                    task.event.position,
                    self._movement_speed,
                    travel_budget,
                )
                if travel_slots is None:
                    continue
                earliest_service_start = snapshot.absolute_step + travel_slots
                earliest_completion = earliest_service_start + task.remaining_service
                if earliest_completion <= effective_deadline:
                    choices.append((travel_slots, distance, resource_id))

            if not choices:
                continue
            _, _, selected_id = min(choices)
            selected = snapshot.resources[selected_id]
            actions[selected_id] = (
                ServeAction(task.event.event_id)
                if selected.position == task.event.position
                else MoveAction(task.event.position)
            )
            available[selected_id] = False

        return tuple(actions)


__all__ = ["ReactiveController"]
