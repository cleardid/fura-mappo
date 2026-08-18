"""消费冻结 DemandTrace 的确定性连续二维资源服务环境。"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from fura_mappo.demand import DemandEvent, DemandTrace
from fura_mappo.envs.models import (
    ContinueAction,
    EnvironmentSnapshot,
    EpisodeMetrics,
    IdleAction,
    MoveAction,
    Position,
    ResourceAction,
    ResourceServiceConfig,
    ResourceSnapshot,
    ResourceStatus,
    ServeAction,
    StepMetrics,
    StepResult,
    TaskSnapshot,
    TaskStatus,
)

_TERMINAL_OUTCOMES = frozenset(
    {
        TaskStatus.COMPLETED,
        TaskStatus.EXPIRED,
        TaskStatus.TRUNCATED,
    }
)
_WAITING_EVENT_ID_ERROR = "event_id 必须引用当前 WAITING 任务"


@dataclass(frozen=True, slots=True)
class _TaskEntry:
    """任务账本条目；assignment 只保存在 resource_to_event。"""

    event: DemandEvent
    remaining_service: int
    service_start_step: int | None
    completion_time: int | None
    terminal_outcome: TaskStatus | None


@dataclass(frozen=True, slots=True)
class _MoveResult:
    """预先验证完成的单资源移动候选。"""

    position: Position
    distance: float
    is_zero_distance: bool


@dataclass(frozen=True, slots=True)
class _EpisodeState:
    """一次 episode 的不可变事务状态。"""

    start_step: int
    stop_step: int
    num_steps: int
    num_zones: int
    absolute_step: int
    arrival_schedule: Mapping[int, tuple[DemandEvent, ...]]
    resource_positions: tuple[Position, ...]
    resource_to_event: tuple[int | None, ...]
    tasks: Mapping[int, _TaskEntry]
    current_arrivals: tuple[DemandEvent, ...]
    service_slots: int
    movement_slots: int
    idle_slots: int
    movement_distance: float
    duplicate_assignment_conflicts: int
    zero_distance_moves: int


class ResourceServiceEnvironment:
    """给定 DemandTrace 和动作序列后完全确定的资源服务环境。"""

    def __init__(self, config: ResourceServiceConfig) -> None:
        """防御性保存最小物理配置，但不创建 episode。"""

        if not isinstance(config, ResourceServiceConfig):
            raise TypeError("config 必须是 ResourceServiceConfig")
        self._config = ResourceServiceConfig(
            initial_resource_positions=config.initial_resource_positions,
            movement_speed=config.movement_speed,
        )
        self._state: _EpisodeState | None = None

    def reset(self, source: DemandTrace) -> EnvironmentSnapshot:
        """事务式加载完整外生轨迹并返回首个可行动边界快照。"""

        if not isinstance(source, DemandTrace):
            raise TypeError("source 必须是 DemandTrace")

        num_steps, num_zones = source.counts.shape
        start_step = source.start_step
        stop_step = start_step + num_steps
        schedule_lists: dict[int, list[DemandEvent]] = {}
        for event in source.events:
            schedule_lists.setdefault(event.arrival_step, []).append(event)
        schedule = MappingProxyType(
            {
                step: tuple(sorted(events, key=lambda event: event.event_id))
                for step, events in schedule_lists.items()
            }
        )
        current_arrivals = schedule.get(start_step, ())
        tasks = MappingProxyType(
            {event.event_id: self._new_task_entry(event) for event in current_arrivals}
        )
        candidate = _EpisodeState(
            start_step=start_step,
            stop_step=stop_step,
            num_steps=num_steps,
            num_zones=num_zones,
            absolute_step=start_step,
            arrival_schedule=schedule,
            resource_positions=self._config.initial_resource_positions,
            resource_to_event=(None,) * len(self._config.initial_resource_positions),
            tasks=tasks,
            current_arrivals=current_arrivals,
            service_slots=0,
            movement_slots=0,
            idle_slots=0,
            movement_distance=0.0,
            duplicate_assignment_conflicts=0,
            zero_distance_moves=0,
        )
        self._validate_state(candidate)
        snapshot = self._build_snapshot(candidate)
        self._state = candidate
        return snapshot

    def step(self, actions: tuple[ResourceAction, ...]) -> StepResult:
        """事务式执行当前槽；任意异常均不得部分提交。"""

        state = self._state
        if state is None:
            raise ValueError("首次 step 前必须成功 reset")
        if state.absolute_step >= state.stop_step:
            raise ValueError("terminal episode 不能继续 step")

        normalized_actions, move_results, serve_requests = self._validate_actions(
            state,
            actions,
        )
        winners, duplicate_conflicts = self._resolve_duplicate_serves(serve_requests)
        current_step = state.absolute_step
        next_step = current_step + 1

        positions = list(state.resource_positions)
        assignments = list(state.resource_to_event)
        tasks = dict(state.tasks)
        step_distances: list[float] = []
        step_movement_slots = 0
        step_zero_distance_moves = 0

        for resource_id, move in move_results.items():
            positions[resource_id] = move.position
            if move.is_zero_distance:
                step_zero_distance_moves += 1
            else:
                step_movement_slots += 1
                step_distances.append(move.distance)

        for event_id, resource_id in winners.items():
            assignments[resource_id] = event_id
            entry = tasks[event_id]
            tasks[event_id] = _TaskEntry(
                event=entry.event,
                remaining_service=entry.remaining_service,
                service_start_step=current_step,
                completion_time=None,
                terminal_outcome=None,
            )

        step_service_slots = 0
        for event_id in assignments:
            if event_id is None:
                continue
            step_service_slots += 1
            entry = tasks[event_id]
            tasks[event_id] = _TaskEntry(
                event=entry.event,
                remaining_service=entry.remaining_service - 1,
                service_start_step=entry.service_start_step,
                completion_time=None,
                terminal_outcome=None,
            )

        completed_ids: list[int] = []
        for resource_id, event_id in enumerate(assignments):
            if event_id is None:
                continue
            entry = tasks[event_id]
            if entry.remaining_service == 0:
                tasks[event_id] = _TaskEntry(
                    event=entry.event,
                    remaining_service=0,
                    service_start_step=entry.service_start_step,
                    completion_time=next_step,
                    terminal_outcome=TaskStatus.COMPLETED,
                )
                assignments[resource_id] = None
                completed_ids.append(event_id)

        expired_ids: list[int] = []
        assigned_by_event = self._invert_assignments(assignments)
        for event_id in sorted(tasks):
            entry = tasks[event_id]
            if entry.terminal_outcome is not None or entry.event.deadline > next_step:
                continue
            resource_id = assigned_by_event.get(event_id)
            if resource_id is not None:
                assignments[resource_id] = None
            tasks[event_id] = _TaskEntry(
                event=entry.event,
                remaining_service=entry.remaining_service,
                service_start_step=entry.service_start_step,
                completion_time=None,
                terminal_outcome=TaskStatus.EXPIRED,
            )
            expired_ids.append(event_id)

        is_terminal = next_step == state.stop_step
        truncated_ids: list[int] = []
        if is_terminal:
            for event_id in sorted(tasks):
                entry = tasks[event_id]
                if entry.terminal_outcome is not None:
                    continue
                tasks[event_id] = _TaskEntry(
                    event=entry.event,
                    remaining_service=entry.remaining_service,
                    service_start_step=entry.service_start_step,
                    completion_time=None,
                    terminal_outcome=TaskStatus.TRUNCATED,
                )
                truncated_ids.append(event_id)
            assignments = [None] * len(assignments)
            next_arrivals: tuple[DemandEvent, ...] = ()
        else:
            next_arrivals = state.arrival_schedule.get(next_step, ())
            for event in next_arrivals:
                if event.event_id in tasks:
                    raise RuntimeError("arrival schedule 包含重复 event_id")
                tasks[event.event_id] = self._new_task_entry(event)

        step_idle_slots = len(normalized_actions) - step_service_slots - step_movement_slots
        if step_idle_slots < 0:
            raise RuntimeError("resource slot 分类产生负 idle 数")

        try:
            step_movement_distance = math.fsum(step_distances)
            cumulative_movement_distance = math.fsum(
                (state.movement_distance, step_movement_distance)
            )
        except OverflowError as error:
            raise ValueError("累计 movement_distance 必须保持有限") from error
        if not math.isfinite(step_movement_distance) or not math.isfinite(
            cumulative_movement_distance
        ):
            raise ValueError("累计 movement_distance 必须保持有限")

        candidate = _EpisodeState(
            start_step=state.start_step,
            stop_step=state.stop_step,
            num_steps=state.num_steps,
            num_zones=state.num_zones,
            absolute_step=next_step,
            arrival_schedule=state.arrival_schedule,
            resource_positions=tuple(positions),
            resource_to_event=tuple(assignments),
            tasks=MappingProxyType(tasks),
            current_arrivals=next_arrivals,
            service_slots=state.service_slots + step_service_slots,
            movement_slots=state.movement_slots + step_movement_slots,
            idle_slots=state.idle_slots + step_idle_slots,
            movement_distance=cumulative_movement_distance,
            duplicate_assignment_conflicts=(
                state.duplicate_assignment_conflicts + duplicate_conflicts
            ),
            zero_distance_moves=state.zero_distance_moves + step_zero_distance_moves,
        )
        step_metrics = StepMetrics(
            absolute_step=current_step,
            arrived=len(state.current_arrivals),
            completed=len(completed_ids),
            expired=len(expired_ids),
            truncated=len(truncated_ids),
            service_slots=step_service_slots,
            movement_slots=step_movement_slots,
            idle_slots=step_idle_slots,
            movement_distance=step_movement_distance,
            duplicate_assignment_conflicts=duplicate_conflicts,
            zero_distance_moves=step_zero_distance_moves,
        )

        if is_terminal:
            episode_metrics = self._build_episode_metrics(candidate)
            next_snapshot = None
        else:
            episode_metrics = None
            next_snapshot = self._build_snapshot(candidate)
        result = StepResult(
            next_snapshot=next_snapshot,
            step_metrics=step_metrics,
            is_terminal=is_terminal,
            episode_metrics=episode_metrics,
        )
        self._validate_state(candidate)
        self._state = candidate
        return result

    @staticmethod
    def _new_task_entry(event: DemandEvent) -> _TaskEntry:
        """为刚到达任务构造未分配账本条目。"""

        return _TaskEntry(
            event=event,
            remaining_service=event.service_time,
            service_start_step=None,
            completion_time=None,
            terminal_outcome=None,
        )

    def _validate_actions(
        self,
        state: _EpisodeState,
        actions: object,
    ) -> tuple[
        tuple[ResourceAction, ...],
        dict[int, _MoveResult],
        dict[int, list[int]],
    ]:
        """针对 pre-step 状态完成全部类型、状态和数值验证。"""

        if not isinstance(actions, tuple):
            raise TypeError("actions 必须是按 resource_id 排列的 tuple")
        if len(actions) != len(state.resource_positions):
            raise ValueError("actions 长度必须严格等于资源数")
        allowed_types = (IdleAction, ContinueAction, MoveAction, ServeAction)
        for action in actions:
            if not isinstance(action, allowed_types):
                raise TypeError("actions 中包含不支持的 action 类型")

        assigned_event_ids = {
            event_id for event_id in state.resource_to_event if event_id is not None
        }
        waiting_ids = {
            event_id
            for event_id, entry in state.tasks.items()
            if entry.terminal_outcome is None and event_id not in assigned_event_ids
        }
        move_results: dict[int, _MoveResult] = {}
        serve_requests: dict[int, list[int]] = {}

        for resource_id, action in enumerate(actions):
            assigned_event_id = state.resource_to_event[resource_id]
            if assigned_event_id is not None:
                if not isinstance(action, ContinueAction):
                    raise ValueError("SERVING 资源只能提交 ContinueAction")
                continue
            if isinstance(action, ContinueAction):
                raise ValueError("AVAILABLE 资源不能提交 ContinueAction")
            if isinstance(action, MoveAction):
                move_results[resource_id] = self._calculate_move(
                    state.resource_positions[resource_id],
                    action.target_position,
                )
            elif isinstance(action, ServeAction):
                if action.event_id not in waiting_ids:
                    raise ValueError(_WAITING_EVENT_ID_ERROR)
                event = state.tasks[action.event_id].event
                if state.resource_positions[resource_id] != event.position:
                    raise ValueError("ServeAction 要求资源精确位于任务位置")
                serve_requests.setdefault(action.event_id, []).append(resource_id)

        normalized = tuple(actions)
        return normalized, move_results, serve_requests

    @staticmethod
    def _resolve_duplicate_serves(
        serve_requests: Mapping[int, list[int]],
    ) -> tuple[dict[int, int], int]:
        """按最小 resource_id 选 winner，并统计失败的合法重复请求。"""

        winners: dict[int, int] = {}
        conflicts = 0
        for event_id in sorted(serve_requests):
            resources = serve_requests[event_id]
            winner = min(resources)
            winners[event_id] = winner
            conflicts += len(resources) - 1
        return winners, conflicts

    def _calculate_move(self, current: Position, target: Position) -> _MoveResult:
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
        if distance <= self._config.movement_speed:
            return _MoveResult(position=target, distance=distance, is_zero_distance=False)

        # 先归一化方向再乘速度，避免 speed / distance 下溢后丢失本可表示的位移。
        candidate = (
            current[0] + (dx / distance) * self._config.movement_speed,
            current[1] + (dy / distance) * self._config.movement_speed,
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
        while actual_distance > self._config.movement_speed:
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
        if actual_distance > self._config.movement_speed:
            raise ValueError("实际移动距离不能超过 movement_speed")
        return _MoveResult(
            position=candidate,
            distance=actual_distance,
            is_zero_distance=False,
        )

    @staticmethod
    def _invert_assignments(
        assignments: list[int | None] | tuple[int | None, ...],
    ) -> dict[int, int]:
        """由唯一 canonical assignment 派生 event 到 resource 的只读视图。"""

        inverse: dict[int, int] = {}
        for resource_id, event_id in enumerate(assignments):
            if event_id is None:
                continue
            if event_id in inverse:
                raise RuntimeError("同一任务被多个资源引用")
            inverse[event_id] = resource_id
        return inverse

    def _build_snapshot(self, state: _EpisodeState) -> EnvironmentSnapshot:
        """只从 canonical state 派生不可变公共快照。"""

        assigned_by_event = self._invert_assignments(state.resource_to_event)
        resources = tuple(
            ResourceSnapshot(
                resource_id=resource_id,
                position=state.resource_positions[resource_id],
                status=(
                    ResourceStatus.SERVING if event_id is not None else ResourceStatus.AVAILABLE
                ),
                assigned_event_id=event_id,
            )
            for resource_id, event_id in enumerate(state.resource_to_event)
        )
        active_tasks: list[TaskSnapshot] = []
        for event_id in sorted(state.tasks):
            entry = state.tasks[event_id]
            if entry.terminal_outcome is not None:
                continue
            assigned_resource_id = assigned_by_event.get(event_id)
            active_tasks.append(
                TaskSnapshot(
                    event=entry.event,
                    status=(
                        TaskStatus.IN_SERVICE
                        if assigned_resource_id is not None
                        else TaskStatus.WAITING
                    ),
                    assigned_resource_id=assigned_resource_id,
                    remaining_service=entry.remaining_service,
                    service_start_step=entry.service_start_step,
                    completion_time=None,
                )
            )
        return EnvironmentSnapshot(
            absolute_step=state.absolute_step,
            steps_remaining=state.stop_step - state.absolute_step,
            resources=resources,
            active_tasks=tuple(active_tasks),
            current_arrivals=state.current_arrivals,
        )

    def _build_episode_metrics(self, state: _EpisodeState) -> EpisodeMetrics:
        """从终局 task ledger 重建 outcome、work、priority 与时延指标。"""

        arrived = len(state.tasks)
        outcome_counts = {
            TaskStatus.COMPLETED: 0,
            TaskStatus.EXPIRED: 0,
            TaskStatus.TRUNCATED: 0,
        }
        priority_values: dict[TaskStatus, list[float]] = {
            TaskStatus.COMPLETED: [],
            TaskStatus.EXPIRED: [],
            TaskStatus.TRUNCATED: [],
        }
        all_priorities: list[float] = []
        demanded_service_work = 0
        completed_service_work = 0
        expired_service_work = 0
        truncated_service_work = 0
        expired_remaining_work = 0
        truncated_remaining_work = 0
        service_start_wait_sum = 0
        service_start_count = 0
        completed_response_sum = 0
        completed_response_count = 0
        per_zone_arrived = [0] * state.num_zones
        per_zone_completed = [0] * state.num_zones
        per_zone_expired = [0] * state.num_zones
        per_zone_truncated = [0] * state.num_zones

        for event_id in sorted(state.tasks):
            entry = state.tasks[event_id]
            outcome = entry.terminal_outcome
            if outcome not in _TERMINAL_OUTCOMES:
                raise RuntimeError("terminal metrics 要求每个任务都有终局 outcome")
            event = entry.event
            delivered_work = event.service_time - entry.remaining_service
            demanded_service_work += event.service_time
            outcome_counts[outcome] += 1
            priority_values[outcome].append(event.priority)
            all_priorities.append(event.priority)
            per_zone_arrived[event.zone_id] += 1

            if entry.service_start_step is not None:
                service_start_wait_sum += entry.service_start_step - event.arrival_step
                service_start_count += 1

            if outcome is TaskStatus.COMPLETED:
                completed_service_work += delivered_work
                per_zone_completed[event.zone_id] += 1
                if entry.completion_time is None:
                    raise RuntimeError("COMPLETED task 缺少 completion_time")
                completed_response_sum += entry.completion_time - event.arrival_step
                completed_response_count += 1
            elif outcome is TaskStatus.EXPIRED:
                expired_service_work += delivered_work
                expired_remaining_work += entry.remaining_service
                per_zone_expired[event.zone_id] += 1
            else:
                truncated_service_work += delivered_work
                truncated_remaining_work += entry.remaining_service
                per_zone_truncated[event.zone_id] += 1

        completed = outcome_counts[TaskStatus.COMPLETED]
        expired = outcome_counts[TaskStatus.EXPIRED]
        truncated = outcome_counts[TaskStatus.TRUNCATED]
        if arrived != completed + expired + truncated:
            raise RuntimeError("任务 outcome 守恒失败")
        if state.service_slots != (
            completed_service_work + expired_service_work + truncated_service_work
        ):
            raise RuntimeError("service_slots 与 delivered work 守恒失败")
        if demanded_service_work != (
            completed_service_work
            + expired_service_work
            + expired_remaining_work
            + truncated_service_work
            + truncated_remaining_work
        ):
            raise RuntimeError("demanded service work 分解失败")
        if len(state.resource_positions) * state.num_steps != (
            state.service_slots + state.movement_slots + state.idle_slots
        ):
            raise RuntimeError("resource slot 守恒失败")

        def rate(numerator: int, denominator: int) -> float | None:
            return None if denominator == 0 else numerator / denominator

        return EpisodeMetrics(
            arrived=arrived,
            completed=completed,
            expired=expired,
            truncated=truncated,
            arrived_priority_sum=math.fsum(all_priorities),
            completed_priority_sum=math.fsum(priority_values[TaskStatus.COMPLETED]),
            expired_priority_sum=math.fsum(priority_values[TaskStatus.EXPIRED]),
            truncated_priority_sum=math.fsum(priority_values[TaskStatus.TRUNCATED]),
            demanded_service_work=demanded_service_work,
            service_slots=state.service_slots,
            movement_slots=state.movement_slots,
            idle_slots=state.idle_slots,
            movement_distance=state.movement_distance,
            completed_service_work=completed_service_work,
            expired_service_work=expired_service_work,
            truncated_service_work=truncated_service_work,
            expired_remaining_work=expired_remaining_work,
            truncated_remaining_work=truncated_remaining_work,
            service_start_wait_sum=service_start_wait_sum,
            service_start_count=service_start_count,
            completed_response_sum=completed_response_sum,
            completed_response_count=completed_response_count,
            duplicate_assignment_conflicts=state.duplicate_assignment_conflicts,
            zero_distance_moves=state.zero_distance_moves,
            per_zone_arrived=tuple(per_zone_arrived),
            per_zone_completed=tuple(per_zone_completed),
            per_zone_expired=tuple(per_zone_expired),
            per_zone_truncated=tuple(per_zone_truncated),
            completion_rate=rate(completed, arrived),
            expiration_rate=rate(expired, arrived),
            truncation_rate=rate(truncated, arrived),
            mean_service_start_wait=rate(service_start_wait_sum, service_start_count),
            mean_completed_response=rate(
                completed_response_sum,
                completed_response_count,
            ),
        )

    def _validate_state(self, state: _EpisodeState) -> None:
        """验证 canonical state、派生状态及整数守恒不变量。"""

        num_resources = len(self._config.initial_resource_positions)
        if (
            len(state.resource_positions) != num_resources
            or len(state.resource_to_event) != num_resources
        ):
            raise RuntimeError("资源状态形状与配置不一致")
        if not state.start_step <= state.absolute_step <= state.stop_step:
            raise RuntimeError("absolute_step 超出 episode 边界")
        if state.stop_step - state.start_step != state.num_steps:
            raise RuntimeError("episode 步数不一致")
        for position in state.resource_positions:
            if not math.isfinite(position[0]) or not math.isfinite(position[1]):
                raise RuntimeError("资源位置必须保持有限")
        if not math.isfinite(state.movement_distance) or state.movement_distance < 0.0:
            raise RuntimeError("movement_distance 必须保持有限非负")
        counters = (
            state.service_slots,
            state.movement_slots,
            state.idle_slots,
            state.duplicate_assignment_conflicts,
            state.zero_distance_moves,
        )
        if any(value < 0 for value in counters):
            raise RuntimeError("累计整数指标不能为负")

        assigned_by_event = self._invert_assignments(state.resource_to_event)
        for event_id, resource_id in assigned_by_event.items():
            entry = state.tasks.get(event_id)
            if entry is None:
                raise RuntimeError("资源引用了不存在的 active task")
            if entry.terminal_outcome is not None:
                raise RuntimeError("terminal task 不得被 resource 引用")
            if not 0 <= resource_id < num_resources:
                raise RuntimeError("assignment resource_id 超出范围")

        delivered_total = 0
        for event_id, entry in state.tasks.items():
            if event_id != entry.event.event_id:
                raise RuntimeError("task ledger key 与 event_id 不一致")
            if entry.remaining_service < 0:
                raise RuntimeError("remaining_service 不能为负")
            is_completed = entry.terminal_outcome is TaskStatus.COMPLETED
            if (entry.remaining_service == 0) != is_completed:
                raise RuntimeError("remaining_service == 0 当且仅当 COMPLETED")
            if entry.terminal_outcome is not None and entry.terminal_outcome not in (
                _TERMINAL_OUTCOMES
            ):
                raise RuntimeError("terminal_outcome 非法")
            if is_completed != (entry.completion_time is not None):
                raise RuntimeError("completion_time 必须仅属于 COMPLETED task")
            delivered = entry.event.service_time - entry.remaining_service
            if delivered < 0:
                raise RuntimeError("remaining_service 超过原始 service_time")
            if (entry.service_start_step is None) != (delivered == 0):
                raise RuntimeError("service_start_step 与 delivered work 不一致")
            if entry.event.arrival_step > state.absolute_step:
                raise RuntimeError("future event 提前进入 task ledger")
            delivered_total += delivered
        if delivered_total != state.service_slots:
            raise RuntimeError("task delivered work 与 service_slots 不一致")

        completed_slots = state.absolute_step - state.start_step
        if num_resources * completed_slots != (
            state.service_slots + state.movement_slots + state.idle_slots
        ):
            raise RuntimeError("当前 resource slot 守恒失败")
        if state.absolute_step == state.stop_step:
            if any(event_id is not None for event_id in state.resource_to_event):
                raise RuntimeError("terminal 后 assignment 必须全部为空")
            if any(entry.terminal_outcome is None for entry in state.tasks.values()):
                raise RuntimeError("terminal 后所有已到达任务必须有 outcome")
            if state.current_arrivals:
                raise RuntimeError("terminal state 不得包含 current_arrivals")
        else:
            if state.stop_step - state.absolute_step < 1:
                raise RuntimeError("非 terminal snapshot 必须至少剩余一个槽")
            if any(event.arrival_step != state.absolute_step for event in state.current_arrivals):
                raise RuntimeError("current_arrivals 必须属于当前绝对边界")


__all__ = ["ResourceServiceEnvironment"]
