"""环境与控制基线共享的确定性单槽移动原语。"""

from __future__ import annotations

import math
from dataclasses import dataclass

from fura_mappo.envs.models import Position


@dataclass(frozen=True, slots=True)
class _MoveResult:
    """预先验证完成的单资源移动候选。"""

    position: Position
    distance: float
    is_zero_distance: bool


def _calculate_single_slot_move(
    current: Position,
    target: Position,
    movement_speed: float,
) -> _MoveResult:
    """计算单槽移动，并拒绝所有不可有限表示的中间结果。"""

    dx = target[0] - current[0]
    dy = target[1] - current[1]
    if not math.isfinite(dx) or not math.isfinite(dy):
        raise ValueError("current-target displacement 必须有限")
    distance = math.hypot(dx, dy)
    if not math.isfinite(distance):
        raise ValueError("Euclidean distance 必须有限")
    if distance == 0.0:
        return _MoveResult(position=target, distance=0.0, is_zero_distance=True)
    if distance <= movement_speed:
        return _MoveResult(position=target, distance=distance, is_zero_distance=False)

    # 先归一化方向再乘速度，避免 speed / distance 下溢后丢失本可表示的位移。
    candidate = (
        current[0] + (dx / distance) * movement_speed,
        current[1] + (dy / distance) * movement_speed,
    )
    if not math.isfinite(candidate[0]) or not math.isfinite(candidate[1]):
        raise ValueError("candidate position 必须有限")
    actual_distance = math.hypot(
        candidate[0] - current[0],
        candidate[1] - current[1],
    )
    if not math.isfinite(actual_distance):
        raise ValueError("actual movement distance 必须有限")

    # 乘法收缩可能舍入回同一个 candidate。逐坐标 nextafter 才能保证每轮实际
    # 浮点位置都严格朝 current 收缩；选择距离最小的候选也保持确定性。
    while actual_distance > movement_speed:
        contractions: list[tuple[float, int, Position]] = []
        for axis in range(2):
            if candidate[axis] == current[axis]:
                continue
            coordinate = math.nextafter(candidate[axis], current[axis])
            contracted = (coordinate, candidate[1]) if axis == 0 else (candidate[0], coordinate)
            contracted_distance = math.hypot(
                contracted[0] - current[0],
                contracted[1] - current[1],
            )
            if not math.isfinite(contracted_distance):
                raise ValueError("actual movement distance 必须有限")
            contractions.append((contracted_distance, axis, contracted))
        if not contractions:
            break
        actual_distance, _, candidate = min(
            contractions,
            key=lambda item: (item[0], item[1]),
        )
    if not math.isfinite(actual_distance):
        raise ValueError("actual movement distance 必须有限")
    if actual_distance <= 0.0:
        raise ValueError("正距离移动必须产生可表示的正位移")
    if actual_distance > movement_speed:
        raise ValueError("实际移动距离不能超过 movement_speed")
    return _MoveResult(
        position=candidate,
        distance=actual_distance,
        is_zero_distance=False,
    )
