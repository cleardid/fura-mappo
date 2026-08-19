"""只使用严格有界真实未来事件的滚动匹配 Oracle。"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from fura_mappo.baselines.reactive import ReactiveController, _exact_travel_slots
from fura_mappo.demand import DemandEvent, DemandTrace
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


def _normalize_nonnegative_integer(value: object, name: str) -> int:
    """规范化非负整数并显式拒绝布尔值。"""

    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)):
        raise TypeError(f"{name} 必须是整数且不能是布尔值")
    normalized = int(value)
    if normalized < 0:
        raise ValueError(f"{name} 必须是非负整数")
    return normalized


def _normalize_events(value: object, name: str) -> tuple[DemandEvent, ...]:
    """防御性读取事件并按到达边界和事件编号规范排序。"""

    try:
        events = tuple(value)  # type: ignore[arg-type]
    except TypeError as error:
        raise TypeError(f"{name} 必须是 DemandEvent 的可迭代对象") from error
    if not all(isinstance(event, DemandEvent) for event in events):
        raise TypeError(f"{name} 中每一项都必须是 DemandEvent")
    ordered = tuple(sorted(events, key=lambda event: (event.arrival_step, event.event_id)))
    event_ids = [event.event_id for event in ordered]
    if len(event_ids) != len(set(event_ids)):
        raise ValueError(f"{name} 中的 event_id 必须唯一")
    return ordered


@dataclass(frozen=True, slots=True)
class TrueFutureView:
    """当前边界可见的不可变真实未来事件窗口。

    Attributes:
        absolute_step: view 对应的非负绝对时间步。
        horizon: 非负可见 horizon；零表示没有未来事件。
        future_events: 规范排列的未来 ``DemandEvent`` 元组。
    """

    absolute_step: int
    horizon: int
    future_events: tuple[DemandEvent, ...]

    def __post_init__(self) -> None:
        """完成不依赖 episode 终点的局部校验。"""

        absolute_step = _normalize_nonnegative_integer(self.absolute_step, "absolute_step")
        horizon = _normalize_nonnegative_integer(self.horizon, "horizon")
        future_events = _normalize_events(self.future_events, "future_events")
        if horizon == 0 and future_events:
            raise ValueError("horizon 为零时 future_events 必须为空")
        local_window_end = absolute_step + horizon
        for event in future_events:
            if not absolute_step < event.arrival_step <= local_window_end:
                raise ValueError(
                    "future event arrival_step 必须位于 (absolute_step, absolute_step + horizon]"
                )

        object.__setattr__(self, "absolute_step", absolute_step)
        object.__setattr__(self, "horizon", horizon)
        object.__setattr__(self, "future_events", future_events)


def build_true_future_view(
    source: DemandTrace,
    snapshot: EnvironmentSnapshot,
    horizon: int,
) -> TrueFutureView:
    """从配对轨迹构造严格受 snapshot 终点约束的真实未来 view。

    该函数只把冻结 ``DemandEvent`` 字段传入 view，不传入 counts、intensity、
    需求过程状态、seed、RNG、config 或 artifact manifest。最低限度 prefix 校验
    只能降低误配风险，不能证明 source 与环境内部轨迹具有完整身份一致性。
    """

    if not isinstance(source, DemandTrace):
        raise TypeError("source 必须是 DemandTrace")
    if not isinstance(snapshot, EnvironmentSnapshot):
        raise TypeError("snapshot 必须是 EnvironmentSnapshot")
    normalized_horizon = _normalize_nonnegative_integer(horizon, "horizon")

    absolute_step = snapshot.absolute_step
    source_stop = source.start_step + source.counts.shape[0]
    stop_step = absolute_step + snapshot.steps_remaining
    if not source.start_step <= absolute_step < source_stop:
        raise ValueError("snapshot.absolute_step 必须位于 source 时间范围内")
    if source_stop != stop_step:
        raise ValueError("source 终点必须与 snapshot episode 终点一致")

    source_current = tuple(
        sorted(
            (event for event in source.events if event.arrival_step == absolute_step),
            key=lambda event: (event.arrival_step, event.event_id),
        )
    )
    snapshot_current = _normalize_events(snapshot.current_arrivals, "snapshot.current_arrivals")
    if source_current != snapshot_current:
        raise ValueError("source 当前到达事件必须与 snapshot.current_arrivals 一致")

    source_by_id = {event.event_id: event for event in source.events}
    for task in snapshot.active_tasks:
        if not isinstance(task, TaskSnapshot):
            raise TypeError("snapshot.active_tasks 中每一项都必须是 TaskSnapshot")
        if source_by_id.get(task.event.event_id) != task.event:
            raise ValueError("snapshot active task 必须与 source 中同 event_id 事件一致")

    window_end = min(absolute_step + normalized_horizon, stop_step - 1)
    future_events = tuple(
        event for event in source.events if absolute_step < event.arrival_step <= window_end
    )
    return TrueFutureView(
        absolute_step=absolute_step,
        horizon=normalized_horizon,
        future_events=future_events,
    )


@dataclass(frozen=True, slots=True)
class _Candidate:
    """当前或未来匹配候选的统一内部表示。"""

    event: DemandEvent
    work: int
    is_future: bool


_PairResult = tuple[int, float] | None


def _finite_distance(current: Position, target: Position) -> float | None:
    """返回有限欧氏距离；中间值不可有限表示时返回 ``None``。"""

    dx = target[0] - current[0]
    dy = target[1] - current[1]
    if not math.isfinite(dx) or not math.isfinite(dy):
        return None
    distance = math.hypot(dx, dy)
    return distance if math.isfinite(distance) else None


def _evaluate_pair(
    resource: ResourceSnapshot,
    candidate: _Candidate,
    *,
    absolute_step: int,
    stop_step: int,
    movement_speed: float,
) -> _PairResult:
    """按共享精确移动语义计算一个资源—候选 pair 的可行性。"""

    effective_deadline = min(candidate.event.deadline, stop_step)
    travel_budget = effective_deadline - candidate.work - absolute_step
    if travel_budget < 0:
        return None
    distance = _finite_distance(resource.position, candidate.event.position)
    if distance is None:
        return None
    try:
        travel_slots = _exact_travel_slots(
            resource.position,
            candidate.event.position,
            movement_speed,
            travel_budget,
        )
    except ValueError:
        return None
    if travel_slots is None:
        return None
    earliest_service_start = max(
        candidate.event.arrival_step,
        absolute_step + travel_slots,
    )
    if earliest_service_start + candidate.work > effective_deadline:
        return None
    return travel_slots, distance


def _candidate_sort_key(candidate: _Candidate, stop_step: int) -> tuple[float, ...]:
    """返回 current/future 共用的冻结任务排序键。"""

    return (
        min(candidate.event.deadline, stop_step) - candidate.work,
        -candidate.event.priority,
        candidate.event.arrival_step,
        candidate.event.event_id,
    )


class RollingTrueFutureOracle:
    """有限 horizon、无状态且确定性的真实未来滚动匹配启发式。"""

    __slots__ = ("_horizon", "_reactive")

    def __init__(self, movement_speed: float, horizon: int) -> None:
        """构造与冻结 Reactive 共享速度边界的 Oracle。"""

        self._reactive = ReactiveController(movement_speed)
        self._horizon = _normalize_nonnegative_integer(horizon, "horizon")

    def act(
        self,
        snapshot: EnvironmentSnapshot,
        future_view: TrueFutureView,
    ) -> tuple[ResourceAction, ...]:
        """根据当前快照和严格有界真实未来事件产生确定性动作。"""

        future_events = self._validate_inputs(snapshot, future_view)

        # 零额外事件信息必须结构性复用冻结 Reactive，而不是重走另一套 current greedy。
        if not future_events:
            return self._reactive.act(snapshot)

        absolute_step = snapshot.absolute_step
        stop_step = absolute_step + snapshot.steps_remaining
        movement_speed = self._reactive._movement_speed
        available_resources = tuple(
            resource
            for resource in snapshot.resources
            if resource.status is ResourceStatus.AVAILABLE
        )
        future_candidates = tuple(
            _Candidate(event=event, work=event.service_time, is_future=True)
            for event in future_events
        )

        # 只缓存本次调用中的 future pair；不得形成跨 step 的 reservation 或计划状态。
        future_pairs: dict[tuple[int, int], _PairResult] = {}
        has_feasible_future_pair = False
        for candidate in future_candidates:
            for resource in available_resources:
                result = _evaluate_pair(
                    resource,
                    candidate,
                    absolute_step=absolute_step,
                    stop_step=stop_step,
                    movement_speed=movement_speed,
                )
                future_pairs[(candidate.event.event_id, resource.resource_id)] = result
                has_feasible_future_pair = has_feasible_future_pair or result is not None

        # 非空但当前不存在任何 physically feasible future pair 时也保持逐值 Reactive 等价。
        if not has_feasible_future_pair:
            return self._reactive.act(snapshot)

        actions: list[ResourceAction] = [IdleAction() for _ in snapshot.resources]
        available = [False] * len(snapshot.resources)
        for resource in snapshot.resources:
            if resource.status is ResourceStatus.SERVING:
                actions[resource.resource_id] = ContinueAction()
            else:
                available[resource.resource_id] = True

        current_candidates = tuple(
            _Candidate(event=task.event, work=task.remaining_service, is_future=False)
            for task in snapshot.active_tasks
            if task.status is TaskStatus.WAITING
        )
        candidates = sorted(
            (*current_candidates, *future_candidates),
            key=lambda candidate: _candidate_sort_key(candidate, stop_step),
        )

        for candidate in candidates:
            choices: list[tuple[int, float, int]] = []
            for resource in snapshot.resources:
                resource_id = resource.resource_id
                if not available[resource_id]:
                    continue
                if candidate.is_future:
                    result = future_pairs[(candidate.event.event_id, resource_id)]
                else:
                    result = _evaluate_pair(
                        resource,
                        candidate,
                        absolute_step=absolute_step,
                        stop_step=stop_step,
                        movement_speed=movement_speed,
                    )
                if result is None:
                    continue
                travel_slots, distance = result
                choices.append((travel_slots, distance, resource_id))

            if not choices:
                continue
            _, _, selected_id = min(choices)
            selected = snapshot.resources[selected_id]
            if selected.position != candidate.event.position:
                actions[selected_id] = MoveAction(candidate.event.position)
            elif candidate.is_future:
                actions[selected_id] = IdleAction()
            else:
                actions[selected_id] = ServeAction(candidate.event.event_id)
            available[selected_id] = False

        return tuple(actions)

    def _validate_inputs(
        self,
        snapshot: EnvironmentSnapshot,
        future_view: TrueFutureView,
    ) -> tuple[DemandEvent, ...]:
        """每次调用重新校验 snapshot/view，不能信任 view 已完成 episode 校验。"""

        if not isinstance(snapshot, EnvironmentSnapshot):
            raise TypeError("snapshot 必须是 EnvironmentSnapshot")
        if not isinstance(future_view, TrueFutureView):
            raise TypeError("future_view 必须是 TrueFutureView")
        for index, resource in enumerate(snapshot.resources):
            if not isinstance(resource, ResourceSnapshot):
                raise TypeError("snapshot.resources 中每一项都必须是 ResourceSnapshot")
            if resource.resource_id != index:
                raise ValueError("snapshot.resources 必须按连续 resource_id 排列")
            if resource.status not in (ResourceStatus.AVAILABLE, ResourceStatus.SERVING):
                raise ValueError("resource status 必须是 AVAILABLE 或 SERVING")

        view_step = _normalize_nonnegative_integer(
            future_view.absolute_step,
            "future_view.absolute_step",
        )
        view_horizon = _normalize_nonnegative_integer(
            future_view.horizon,
            "future_view.horizon",
        )
        if view_step != snapshot.absolute_step:
            raise ValueError("future_view.absolute_step 必须等于 snapshot.absolute_step")
        if view_horizon != self._horizon:
            raise ValueError("future_view.horizon 必须等于 Oracle horizon")

        future_events = _normalize_events(future_view.future_events, "future_view.future_events")
        current_ids = {
            task.event.event_id for task in snapshot.active_tasks if isinstance(task, TaskSnapshot)
        }
        current_ids.update(
            event.event_id for event in snapshot.current_arrivals if isinstance(event, DemandEvent)
        )
        if any(event.event_id in current_ids for event in future_events):
            raise ValueError("future event_id 不得与当前任务或当前到达事件重叠")

        stop_step = snapshot.absolute_step + snapshot.steps_remaining
        window_end = min(snapshot.absolute_step + self._horizon, stop_step - 1)
        for event in future_events:
            if not snapshot.absolute_step < event.arrival_step <= window_end:
                raise ValueError("future event arrival_step 必须位于 clamped future window")
        return future_events


__all__ = [
    "RollingTrueFutureOracle",
    "TrueFutureView",
    "build_true_future_view",
]
