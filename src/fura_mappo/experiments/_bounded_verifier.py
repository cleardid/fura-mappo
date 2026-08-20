"""WP-02D2 有界 task-target root-information 穷举诊断 verifier。"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import Enum
from itertools import product
from numbers import Integral
from typing import TypeAlias

from fura_mappo.baselines import TrueFutureView, build_true_future_view
from fura_mappo.demand import DemandEvent, DemandTrace
from fura_mappo.envs import (
    ContinueAction,
    EnvironmentSnapshot,
    EpisodeMetrics,
    IdleAction,
    MoveAction,
    Position,
    ResourceAction,
    ResourceServiceConfig,
    ResourceServiceEnvironment,
    ResourceStatus,
    ServeAction,
    StepResult,
    TaskStatus,
)

ActionKey: TypeAlias = tuple[int] | tuple[int, int] | tuple[int, float, float]
JointAction: TypeAlias = tuple[ResourceAction, ...]
JointActionKey: TypeAlias = tuple[ActionKey, ...]
ActionSequence: TypeAlias = tuple[JointAction, ...]
SequenceKey: TypeAlias = tuple[JointActionKey, ...]


class BoundedVerifierError(RuntimeError):
    """表示 verifier 协议或确定性 replay 失败。"""


class BoundedDiagnosticLabel(str, Enum):
    """预注册 bounded suite 的两个私有诊断标签。"""

    PRIMARY_HEURISTIC_MISS_DETECTED = "PRIMARY_HEURISTIC_MISS_DETECTED"
    NO_HEURISTIC_MISS_DETECTED_WITHIN_PREREGISTERED_BOUNDED_SUITE = (
        "NO_HEURISTIC_MISS_DETECTED_WITHIN_PREREGISTERED_BOUNDED_SUITE"
    )


@dataclass(frozen=True, slots=True)
class BoundedFixtureComparison:
    """一个 fixture 的 Primary/verifier 完成数比较。"""

    primary_completed: int
    verifier_completed: int

    def __post_init__(self) -> None:
        """拒绝布尔值和负完成数。"""

        object.__setattr__(
            self,
            "primary_completed",
            _normalize_nonnegative_integer(self.primary_completed, "primary_completed"),
        )
        object.__setattr__(
            self,
            "verifier_completed",
            _normalize_nonnegative_integer(self.verifier_completed, "verifier_completed"),
        )


@dataclass(frozen=True, slots=True)
class BoundedVerifierRootRecord:
    """一个真实 decision boundary 的冻结信息与最优完整序列。"""

    root_snapshot: EnvironmentSnapshot
    official_future_view: TrueFutureView
    k_event_ids: tuple[int, ...]
    move_targets: tuple[Position, ...]
    selected_sequence: ActionSequence
    selected_completed_over_k: int


@dataclass(frozen=True, slots=True)
class BoundedVerifierResult:
    """rolling verifier 的实际动作、结果、root 诊断与终局指标。"""

    actions: ActionSequence
    step_results: tuple[StepResult, ...]
    root_records: tuple[BoundedVerifierRootRecord, ...]
    episode_metrics: EpisodeMetrics


@dataclass(frozen=True, slots=True)
class _FrozenRootInformation:
    """一次 root search 内不可变化的 task-target information。"""

    events: tuple[DemandEvent, ...]
    event_ids: frozenset[int]
    positions: tuple[Position, ...]


@dataclass(frozen=True, slots=True)
class _SearchOutcome:
    """一个 root 从当前边界直到 episode terminal 的最优结果。"""

    sequence: ActionSequence
    step_results: tuple[StepResult, ...]
    completed_over_k: int


_BranchReplayer: TypeAlias = Callable[
    [ActionSequence, tuple[StepResult, ...]],
    tuple[ResourceServiceEnvironment, EnvironmentSnapshot | None],
]


def _normalize_nonnegative_integer(value: object, name: str) -> int:
    """规范化非负整数并拒绝布尔值。"""

    if isinstance(value, bool) or not isinstance(value, Integral):
        raise TypeError(f"{name} 必须是整数且不能是布尔值")
    normalized = int(value)
    if normalized < 0:
        raise ValueError(f"{name} 必须是非负整数")
    return normalized


def action_key(action: ResourceAction) -> ActionKey:
    """返回冻结的无 reward action total-order key。"""

    if isinstance(action, ContinueAction):
        return (0,)
    if isinstance(action, IdleAction):
        return (1,)
    if isinstance(action, MoveAction):
        return (2, action.target_position[0], action.target_position[1])
    if isinstance(action, ServeAction):
        return (3, action.event_id)
    raise TypeError("action 必须是受支持的 ResourceAction")


def joint_action_key(actions: JointAction) -> JointActionKey:
    """按 resource_id 顺序返回 joint-action key。"""

    if not isinstance(actions, tuple):
        raise TypeError("actions 必须是 tuple")
    return tuple(action_key(action) for action in actions)


def sequence_key(sequence: ActionSequence) -> SequenceKey:
    """按时间顺序返回完整 action-sequence key。"""

    if not isinstance(sequence, tuple):
        raise TypeError("sequence 必须是 tuple")
    return tuple(joint_action_key(actions) for actions in sequence)


def classify_bounded_suite(
    comparisons: Sequence[BoundedFixtureComparison],
) -> BoundedDiagnosticLabel:
    """按预注册规则分类 bounded fixture suite。"""

    if isinstance(comparisons, (str, bytes)) or not isinstance(comparisons, Sequence):
        raise TypeError("comparisons 必须是 BoundedFixtureComparison 序列")
    for comparison in comparisons:
        if not isinstance(comparison, BoundedFixtureComparison):
            raise TypeError("comparisons 中每一项都必须是 BoundedFixtureComparison")
        if comparison.verifier_completed > comparison.primary_completed:
            return BoundedDiagnosticLabel.PRIMARY_HEURISTIC_MISS_DETECTED
    return BoundedDiagnosticLabel.NO_HEURISTIC_MISS_DETECTED_WITHIN_PREREGISTERED_BOUNDED_SUITE


def _validate_problem(
    trace: DemandTrace,
    config: ResourceServiceConfig,
    horizon: object,
) -> int:
    """验证 WP-02D2 的硬规模边界。"""

    if not isinstance(trace, DemandTrace):
        raise TypeError("trace 必须是 DemandTrace")
    if not isinstance(config, ResourceServiceConfig):
        raise TypeError("config 必须是 ResourceServiceConfig")
    normalized_horizon = _normalize_nonnegative_integer(horizon, "horizon")
    if len(config.initial_resource_positions) > 2:
        raise ValueError("bounded verifier 最多允许 2 个 resources")
    if trace.counts.shape[0] > 4:
        raise ValueError("bounded verifier 最多允许 4 个 episode steps")
    if len(trace.events) > 3:
        raise ValueError("bounded verifier 最多允许 3 个 events")
    return normalized_horizon


def _freeze_root_information(
    snapshot: EnvironmentSnapshot,
    future_view: TrueFutureView,
) -> _FrozenRootInformation:
    """只从真实 root snapshot 与 official view 冻结 K。"""

    events = tuple(task.event for task in snapshot.active_tasks) + future_view.future_events
    ordered = tuple(sorted(events, key=lambda event: event.event_id))
    event_ids = tuple(event.event_id for event in ordered)
    if len(event_ids) != len(set(event_ids)):
        raise BoundedVerifierError("root K event_id 必须唯一")

    ordered_positions = sorted(
        (event.position for event in ordered), key=lambda item: (item[0], item[1])
    )
    unique_positions: list[Position] = []
    for position in ordered_positions:
        if not unique_positions or position != unique_positions[-1]:
            unique_positions.append(position)
    return _FrozenRootInformation(
        events=ordered,
        event_ids=frozenset(event_ids),
        positions=tuple(unique_positions),
    )


def _available_actions(
    snapshot: EnvironmentSnapshot,
    root: _FrozenRootInformation,
) -> tuple[tuple[ResourceAction, ...], ...]:
    """枚举每个 resource 的冻结有限动作集。"""

    waiting_k_ids: set[int] = set()
    for task in snapshot.active_tasks:
        event_id = task.event.event_id
        if event_id not in root.event_ids:
            continue
        if task.status is TaskStatus.WAITING:
            waiting_k_ids.add(event_id)

    per_resource: list[tuple[ResourceAction, ...]] = []
    for expected_resource_id, resource in enumerate(snapshot.resources):
        if resource.resource_id != expected_resource_id:
            raise BoundedVerifierError("snapshot.resources 必须按连续 resource_id 排列")
        if resource.status is ResourceStatus.SERVING:
            if resource.assigned_event_id not in root.event_ids:
                raise BoundedVerifierError("SERVING resource 必须指向 frozen K event")
            per_resource.append((ContinueAction(),))
            continue
        if resource.status is not ResourceStatus.AVAILABLE:
            raise BoundedVerifierError("resource status 必须是 AVAILABLE 或 SERVING")

        actions: list[ResourceAction] = [IdleAction()]
        actions.extend(MoveAction(position) for position in root.positions)
        actions.extend(
            ServeAction(event.event_id)
            for event in root.events
            if event.event_id in waiting_k_ids and resource.position == event.position
        )
        per_resource.append(tuple(sorted(actions, key=action_key)))
    return tuple(per_resource)


def enumerate_joint_actions(
    snapshot: EnvironmentSnapshot,
    root: _FrozenRootInformation,
) -> tuple[JointAction, ...]:
    """按 resource_id Cartesian product 穷举 joint actions。"""

    per_resource = _available_actions(snapshot, root)
    return tuple(sorted(product(*per_resource), key=joint_action_key))


def _make_branch_replayer(
    trace: DemandTrace,
    config: ResourceServiceConfig,
    *,
    expected_reset_snapshot: EnvironmentSnapshot,
    real_prefix_actions: ActionSequence,
    real_prefix_results: tuple[StepResult, ...],
    expected_root_snapshot: EnvironmentSnapshot,
) -> _BranchReplayer:
    """隔离完整 trace，只暴露 fresh public reset/step replay callback。"""

    if len(real_prefix_actions) != len(real_prefix_results):
        raise BoundedVerifierError("真实 prefix actions/results 长度不一致")

    def replay(
        candidate_suffix: ActionSequence,
        candidate_results: tuple[StepResult, ...],
    ) -> tuple[ResourceServiceEnvironment, EnvironmentSnapshot | None]:
        if len(candidate_suffix) != len(candidate_results):
            raise BoundedVerifierError("candidate suffix actions/results 长度不一致")

        environment = ResourceServiceEnvironment(config)
        snapshot: EnvironmentSnapshot | None = environment.reset(trace)
        if snapshot != expected_reset_snapshot:
            raise BoundedVerifierError("prefix replay reset snapshot 不一致")

        for actions, expected_result in zip(
            real_prefix_actions,
            real_prefix_results,
            strict=True,
        ):
            if snapshot is None:
                raise BoundedVerifierError("真实 prefix 在 replay 中提前 terminal")
            actual_result = environment.step(actions)
            if actual_result != expected_result:
                raise BoundedVerifierError("真实 prefix StepResult replay 不一致")
            snapshot = actual_result.next_snapshot
        if snapshot != expected_root_snapshot:
            raise BoundedVerifierError("prefix replay root snapshot 不一致")

        for actions, expected_result in zip(candidate_suffix, candidate_results, strict=True):
            if snapshot is None:
                raise BoundedVerifierError("accepted candidate suffix 提前 terminal")
            actual_result = environment.step(actions)
            if actual_result != expected_result:
                raise BoundedVerifierError("accepted candidate suffix StepResult replay 不一致")
            snapshot = actual_result.next_snapshot
        return environment, snapshot

    return replay


def _is_better(candidate: _SearchOutcome, incumbent: _SearchOutcome | None) -> bool:
    """比较 completed objective，再比较冻结 sequence key。"""

    if incumbent is None:
        return True
    if candidate.completed_over_k != incumbent.completed_over_k:
        return candidate.completed_over_k > incumbent.completed_over_k
    return sequence_key(candidate.sequence) < sequence_key(incumbent.sequence)


def _search_root(
    replay: _BranchReplayer,
    root: _FrozenRootInformation,
) -> _SearchOutcome:
    """无 pruning/memoization 地从 root 穷举到固定 episode terminal。"""

    best: _SearchOutcome | None = None

    def visit(
        suffix: ActionSequence,
        accepted_results: tuple[StepResult, ...],
        completed_over_k: int,
    ) -> None:
        nonlocal best
        _, snapshot = replay(suffix, accepted_results)
        if snapshot is None:
            candidate = _SearchOutcome(
                sequence=suffix,
                step_results=accepted_results,
                completed_over_k=completed_over_k,
            )
            if _is_better(candidate, best):
                best = candidate
            return

        for actions in enumerate_joint_actions(snapshot, root):
            environment, replayed_snapshot = replay(suffix, accepted_results)
            if replayed_snapshot != snapshot:
                raise BoundedVerifierError("candidate node replay snapshot 不一致")
            try:
                result = environment.step(actions)
            except ValueError:
                continue
            visit(
                (*suffix, actions),
                (*accepted_results, result),
                completed_over_k + result.step_metrics.completed,
            )

    visit((), (), 0)
    if best is None or not best.sequence:
        raise BoundedVerifierError("root search 未产生完整合法 action sequence")
    return best


def run_bounded_verifier(
    trace: DemandTrace,
    config: ResourceServiceConfig,
    horizon: int,
) -> BoundedVerifierResult:
    """运行 rolling bounded task-target root-information exhaustive verifier。"""

    normalized_horizon = _validate_problem(trace, config, horizon)
    real_environment = ResourceServiceEnvironment(config)
    reset_snapshot = real_environment.reset(trace)
    snapshot: EnvironmentSnapshot | None = reset_snapshot
    real_actions: list[JointAction] = []
    real_results: list[StepResult] = []
    root_records: list[BoundedVerifierRootRecord] = []

    while snapshot is not None:
        official_view = build_true_future_view(trace, snapshot, normalized_horizon)
        root = _freeze_root_information(snapshot, official_view)
        replay = _make_branch_replayer(
            trace,
            config,
            expected_reset_snapshot=reset_snapshot,
            real_prefix_actions=tuple(real_actions),
            real_prefix_results=tuple(real_results),
            expected_root_snapshot=snapshot,
        )
        selected = _search_root(replay, root)
        selected_action = selected.sequence[0]
        actual_result = real_environment.step(selected_action)
        if actual_result != selected.step_results[0]:
            raise BoundedVerifierError("真实 first action 与 selected branch StepResult 不一致")

        root_records.append(
            BoundedVerifierRootRecord(
                root_snapshot=snapshot,
                official_future_view=official_view,
                k_event_ids=tuple(event.event_id for event in root.events),
                move_targets=root.positions,
                selected_sequence=selected.sequence,
                selected_completed_over_k=selected.completed_over_k,
            )
        )
        real_actions.append(selected_action)
        real_results.append(actual_result)
        snapshot = actual_result.next_snapshot

    if not real_results or real_results[-1].episode_metrics is None:
        raise BoundedVerifierError("rolling verifier 未产生 terminal EpisodeMetrics")
    return BoundedVerifierResult(
        actions=tuple(real_actions),
        step_results=tuple(real_results),
        root_records=tuple(root_records),
        episode_metrics=real_results[-1].episode_metrics,
    )
