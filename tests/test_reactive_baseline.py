from __future__ import annotations

import inspect
import math
import random

import numpy as np
import pytest

import fura_mappo.baselines.reactive as reactive_module
from fura_mappo.baselines import ReactiveController
from fura_mappo.demand import DemandEvent, DemandTrace
from fura_mappo.envs import (
    ContinueAction,
    EnvironmentSnapshot,
    EpisodeMetrics,
    IdleAction,
    MoveAction,
    ResourceAction,
    ResourceServiceConfig,
    ResourceServiceEnvironment,
    ResourceSnapshot,
    ResourceStatus,
    ServeAction,
    TaskSnapshot,
    TaskStatus,
)


def _event(
    event_id: int,
    *,
    arrival_step: int = 0,
    position: tuple[float, float] = (0.0, 0.0),
    priority: float = 0.5,
    service_time: int = 1,
    deadline: int = 10,
) -> DemandEvent:
    return DemandEvent(
        event_id=event_id,
        arrival_step=arrival_step,
        zone_id=0,
        position=position,
        priority=priority,
        service_time=service_time,
        deadline=deadline,
    )


def _task(
    event_id: int,
    *,
    arrival_step: int = 0,
    position: tuple[float, float] = (0.0, 0.0),
    priority: float = 0.5,
    service_time: int = 1,
    deadline: int = 10,
    remaining_service: int | None = None,
    status: TaskStatus = TaskStatus.WAITING,
    assigned_resource_id: int | None = None,
) -> TaskSnapshot:
    event = _event(
        event_id,
        arrival_step=arrival_step,
        position=position,
        priority=priority,
        service_time=service_time,
        deadline=deadline,
    )
    return TaskSnapshot(
        event=event,
        status=status,
        assigned_resource_id=assigned_resource_id,
        remaining_service=(service_time if remaining_service is None else remaining_service),
        service_start_step=None,
        completion_time=None,
    )


def _resource(
    resource_id: int,
    position: tuple[float, float] = (0.0, 0.0),
    *,
    status: ResourceStatus = ResourceStatus.AVAILABLE,
    assigned_event_id: int | None = None,
) -> ResourceSnapshot:
    return ResourceSnapshot(
        resource_id=resource_id,
        position=position,
        status=status,
        assigned_event_id=assigned_event_id,
    )


def _snapshot(
    *,
    resources: tuple[ResourceSnapshot, ...] = (_resource(0),),
    tasks: tuple[TaskSnapshot, ...] = (),
    absolute_step: int = 0,
    steps_remaining: int = 10,
    current_arrivals: tuple[DemandEvent, ...] = (),
) -> EnvironmentSnapshot:
    return EnvironmentSnapshot(
        absolute_step=absolute_step,
        steps_remaining=steps_remaining,
        resources=resources,
        active_tasks=tasks,
        current_arrivals=current_arrivals,
    )


def _trace(
    events: tuple[DemandEvent, ...],
    *,
    start_step: int,
    num_steps: int,
) -> DemandTrace:
    counts = np.zeros((num_steps, 1), dtype=np.int64)
    for event in events:
        counts[event.arrival_step - start_step, 0] += 1
    intensities = np.zeros((num_steps, 1), dtype=np.float64)
    return DemandTrace(start_step, counts, intensities, events)


def _rollout(
    trace: DemandTrace,
    config: ResourceServiceConfig,
) -> tuple[tuple[tuple[ResourceAction, ...], ...], EpisodeMetrics]:
    env = ResourceServiceEnvironment(config)
    controller = ReactiveController(config.movement_speed)
    snapshot: EnvironmentSnapshot | None = env.reset(trace)
    actions: list[tuple[ResourceAction, ...]] = []
    metrics: EpisodeMetrics | None = None
    while snapshot is not None:
        step_actions = controller.act(snapshot)
        actions.append(step_actions)
        result = env.step(step_actions)
        snapshot = result.next_snapshot
        metrics = result.episode_metrics
    if metrics is None:
        raise AssertionError("terminal rollout 必须返回 EpisodeMetrics")
    return tuple(actions), metrics


def _assert_numpy_states_equal(left: tuple[object, ...], right: tuple[object, ...]) -> None:
    assert left[0] == right[0]
    np.testing.assert_array_equal(left[1], right[1])
    assert left[2:] == right[2:]


@pytest.mark.parametrize("value", [True, np.bool_(False)])
def test_constructor_rejects_boolean_speed(value: object) -> None:
    with pytest.raises(TypeError, match="布尔"):
        ReactiveController(value)  # type: ignore[arg-type]


def test_constructor_rejects_non_real_speed() -> None:
    with pytest.raises(TypeError, match="实数"):
        ReactiveController("1.0")  # type: ignore[arg-type]


@pytest.mark.parametrize("value", [0.0, -1.0, math.nan, math.inf, -math.inf])
def test_constructor_rejects_nonpositive_or_nonfinite_speed(value: float) -> None:
    with pytest.raises(ValueError):
        ReactiveController(value)


def test_constructor_converts_float_overflow_to_value_error() -> None:
    with pytest.raises(ValueError, match="有限 Python float"):
        ReactiveController(10**10000)


@pytest.mark.parametrize("value", [1.5, np.float64(2.5)])
def test_constructor_saves_only_normalized_python_float(value: object) -> None:
    controller = ReactiveController(value)  # type: ignore[arg-type]

    assert controller._movement_speed == float(value)
    assert type(controller._movement_speed) is float
    assert ReactiveController.__slots__ == ("_movement_speed",)
    assert not hasattr(controller, "__dict__")


def test_controller_public_boundary_has_no_trace_reset_or_stateful_dependencies() -> None:
    controller = ReactiveController(1.0)
    signature = inspect.signature(controller.act)

    assert tuple(signature.parameters) == ("snapshot",)
    assert "DemandTrace" not in str(signature)
    assert not hasattr(controller, "reset")
    for forbidden in ("env", "history", "reservation", "rng", "trace", "previous_actions"):
        assert not hasattr(controller, forbidden)


def test_act_rejects_non_snapshot_and_misordered_resource_ids() -> None:
    controller = ReactiveController(1.0)
    with pytest.raises(TypeError, match="EnvironmentSnapshot"):
        controller.act(object())  # type: ignore[arg-type]

    invalid = _snapshot(resources=(_resource(1), _resource(0)))
    with pytest.raises(ValueError, match="resource_id"):
        controller.act(invalid)


def test_serving_resources_continue_and_available_without_waiting_idle() -> None:
    snapshot = _snapshot(
        resources=(
            _resource(
                0,
                status=ResourceStatus.SERVING,
                assigned_event_id=9,
            ),
            _resource(1, (1.0, 0.0)),
        )
    )

    actions = ReactiveController(1.0).act(snapshot)

    assert actions == (ContinueAction(), IdleAction())


def test_exact_position_serves_and_nonzero_feasible_distance_moves() -> None:
    tasks = (
        _task(0, position=(0.0, 0.0), deadline=3),
        _task(1, position=(2.0, 0.0), deadline=4),
    )
    snapshot = _snapshot(
        resources=(_resource(0), _resource(1, (1.0, 0.0))),
        tasks=tasks,
        steps_remaining=4,
    )

    actions = ReactiveController(1.0).act(snapshot)

    assert actions == (ServeAction(0), MoveAction((2.0, 0.0)))


def test_deadline_and_terminal_horizon_infeasible_tasks_are_skipped() -> None:
    deadline_limited = _snapshot(
        resources=(_resource(0, (0.0, 0.0)),),
        tasks=(_task(0, position=(1.0, 0.0), deadline=6),),
        absolute_step=5,
        steps_remaining=3,
    )
    terminal_limited = _snapshot(
        resources=(_resource(0, (0.0, 0.0)),),
        tasks=(_task(0, position=(1.0, 0.0), deadline=20),),
        absolute_step=5,
        steps_remaining=1,
    )

    assert ReactiveController(1.0).act(deadline_limited) == (IdleAction(),)
    assert ReactiveController(1.0).act(terminal_limited) == (IdleAction(),)


def test_in_service_tasks_are_not_candidates_for_available_resources() -> None:
    task = _task(
        0,
        status=TaskStatus.IN_SERVICE,
        assigned_resource_id=1,
        deadline=3,
    )

    assert ReactiveController(1.0).act(_snapshot(tasks=(task,))) == (IdleAction(),)


def test_feasibility_uses_remaining_service_not_original_service_time() -> None:
    task = _task(
        0,
        service_time=5,
        remaining_service=1,
        deadline=6,
    )
    snapshot = _snapshot(tasks=(task,), absolute_step=5, steps_remaining=1)

    assert ReactiveController(1.0).act(snapshot) == (ServeAction(0),)


def test_task_order_prefers_smaller_latest_service_start() -> None:
    less_urgent = _task(0, priority=1.0, service_time=1, deadline=10)
    urgent = _task(1, priority=0.0, service_time=2, deadline=4)

    assert ReactiveController(1.0).act(_snapshot(tasks=(less_urgent, urgent)))[0] == ServeAction(1)


def test_task_order_breaks_tie_by_higher_priority() -> None:
    low = _task(0, priority=0.1, deadline=5)
    high = _task(1, priority=0.9, deadline=5)

    assert ReactiveController(1.0).act(_snapshot(tasks=(low, high)))[0] == ServeAction(1)


def test_task_order_breaks_tie_by_earlier_arrival_step() -> None:
    late = _task(0, arrival_step=4, deadline=10)
    early = _task(1, arrival_step=2, deadline=10)
    snapshot = _snapshot(tasks=(late, early), absolute_step=5)

    assert ReactiveController(1.0).act(snapshot)[0] == ServeAction(1)


def test_task_order_breaks_final_tie_by_smaller_event_id() -> None:
    larger = _task(8, deadline=5)
    smaller = _task(3, deadline=5)

    assert ReactiveController(1.0).act(_snapshot(tasks=(larger, smaller)))[0] == ServeAction(3)


def test_exact_feasibility_rejects_floating_ceil_counterexample() -> None:
    current = (-0.6475645430192594, -0.5360862663609285)
    target = (-0.5333278326382778, -0.030074539317286764)
    distance = 0.5187464639921483
    speed = 0.17291548799738277
    task = _task(0, position=target, deadline=4)
    snapshot = _snapshot(
        resources=(_resource(0, current),),
        tasks=(task,),
        steps_remaining=4,
    )

    assert math.ceil(distance / speed) == 3
    assert reactive_module._exact_travel_slots(current, target, speed, 4) == 4
    actions = ReactiveController(speed).act(snapshot)

    assert actions == (IdleAction(),)


def test_resource_order_prefers_exact_travel_slots_before_distance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def controlled_slots(
        current: tuple[float, float],
        target: tuple[float, float],
        movement_speed: float,
        travel_budget: int,
    ) -> int:
        del target, movement_speed, travel_budget
        return 1 if current == (2.0, 0.0) else 2

    monkeypatch.setattr(reactive_module, "_exact_travel_slots", controlled_slots)
    snapshot = _snapshot(
        resources=(_resource(0, (2.0, 0.0)), _resource(1, (1.0, 0.0))),
        tasks=(_task(0, deadline=5),),
        steps_remaining=5,
    )

    assert ReactiveController(1.0).act(snapshot) == (MoveAction((0.0, 0.0)), IdleAction())


def test_resource_order_breaks_equal_slot_count_by_finite_distance() -> None:
    snapshot = _snapshot(
        resources=(_resource(0, (2.0, 0.0)), _resource(1, (1.0, 0.0))),
        tasks=(_task(0, deadline=3),),
        steps_remaining=3,
    )

    assert ReactiveController(10.0).act(snapshot) == (IdleAction(), MoveAction((0.0, 0.0)))


def test_resource_order_breaks_final_tie_by_smaller_resource_id() -> None:
    snapshot = _snapshot(
        resources=(_resource(0, (-1.0, 0.0)), _resource(1, (1.0, 0.0))),
        tasks=(_task(0, deadline=3),),
        steps_remaining=3,
    )

    assert ReactiveController(1.0).act(snapshot) == (MoveAction((0.0, 0.0)), IdleAction())


def test_multi_resource_multi_task_matching_is_unique_and_ordered() -> None:
    snapshot = _snapshot(
        resources=(_resource(0), _resource(1)),
        tasks=(_task(0, deadline=3), _task(1, deadline=3)),
        steps_remaining=3,
    )

    actions = ReactiveController(1.0).act(snapshot)

    assert actions == (ServeAction(0), ServeAction(1))
    served_ids = [action.event_id for action in actions if isinstance(action, ServeAction)]
    assert len(served_ids) == len(set(served_ids))


def test_infeasible_most_urgent_task_does_not_block_later_feasible_task() -> None:
    impossible = _task(0, position=(10.0, 0.0), priority=1.0, deadline=1)
    feasible = _task(1, position=(0.0, 0.0), priority=0.0, deadline=4)

    actions = ReactiveController(1.0).act(_snapshot(tasks=(impossible, feasible)))

    assert actions == (ServeAction(1),)


def test_primitive_value_error_rejects_only_one_pair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = reactive_module._calculate_single_slot_move

    def fail_one_pair(
        current: tuple[float, float],
        target: tuple[float, float],
        speed: float,
    ) -> object:
        if current == (0.0, 0.0):
            raise ValueError("injected pair failure")
        return original(current, target, speed)

    monkeypatch.setattr(reactive_module, "_calculate_single_slot_move", fail_one_pair)
    snapshot = _snapshot(
        resources=(_resource(0), _resource(1, (1.0, 0.0))),
        tasks=(_task(0, position=(2.0, 0.0), deadline=4),),
        steps_remaining=4,
    )

    actions = ReactiveController(1.0).act(snapshot)

    assert actions == (IdleAction(), MoveAction((2.0, 0.0)))


def test_same_snapshot_is_deterministic_and_does_not_pollute_global_rng() -> None:
    numpy_state = np.random.get_state()
    python_state = random.getstate()
    snapshot = _snapshot(
        resources=(_resource(0, (1.0, 0.0)), _resource(1)),
        tasks=(_task(0, deadline=3), _task(1, position=(2.0, 0.0), deadline=4)),
        steps_remaining=4,
    )
    controller = ReactiveController(np.float64(1.0))

    first = controller.act(snapshot)
    second = controller.act(snapshot)

    assert first == second
    _assert_numpy_states_equal(numpy_state, np.random.get_state())
    assert python_state == random.getstate()


def test_current_arrivals_do_not_change_actions() -> None:
    task = _task(0, deadline=3)
    base = _snapshot(tasks=(task,), steps_remaining=3)
    changed = _snapshot(
        tasks=(task,),
        steps_remaining=3,
        current_arrivals=(_event(99, deadline=3),),
    )

    controller = ReactiveController(1.0)
    assert controller.act(base) == controller.act(changed)


def test_same_current_state_with_different_future_traces_has_same_actions() -> None:
    current = _event(0, deadline=3)
    future_left = _event(1, arrival_step=1, position=(-10.0, 0.0), deadline=3)
    future_right = _event(1, arrival_step=1, position=(10.0, 0.0), deadline=3)
    config = ResourceServiceConfig(((0.0, 0.0),), 1.0)
    left_env = ResourceServiceEnvironment(config)
    right_env = ResourceServiceEnvironment(config)
    left = left_env.reset(_trace((current, future_left), start_step=0, num_steps=3))
    right = right_env.reset(_trace((current, future_right), start_step=0, num_steps=3))

    assert left == right
    controller = ReactiveController(1.0)
    assert controller.act(left) == controller.act(right) == (ServeAction(0),)


def test_stateless_replanning_can_redirect_available_resource() -> None:
    controller = ReactiveController(1.0)
    first = _snapshot(
        resources=(_resource(0),),
        tasks=(_task(0, position=(3.0, 0.0), deadline=6),),
        steps_remaining=6,
    )
    second = _snapshot(
        resources=(_resource(0, (1.0, 0.0)),),
        tasks=(
            _task(0, position=(3.0, 0.0), deadline=6),
            _task(1, position=(0.0, 0.0), deadline=3),
        ),
        absolute_step=1,
        steps_remaining=5,
    )

    assert controller.act(first) == (MoveAction((3.0, 0.0)),)
    assert controller.act(second) == (MoveAction((0.0, 0.0)),)


def test_move_then_next_slot_serve_completes_at_deadline_and_stop_step() -> None:
    event = _event(0, arrival_step=5, position=(1.0, 0.0), deadline=7)
    trace = _trace((event,), start_step=5, num_steps=2)
    config = ResourceServiceConfig(((0.0, 0.0),), 1.0)
    env = ResourceServiceEnvironment(config)
    controller = ReactiveController(config.movement_speed)
    first_snapshot = env.reset(trace)

    first_actions = controller.act(first_snapshot)
    first_result = env.step(first_actions)
    assert first_result.next_snapshot is not None
    second_actions = controller.act(first_result.next_snapshot)
    terminal = env.step(second_actions)

    assert first_actions == (MoveAction((1.0, 0.0)),)
    assert second_actions == (ServeAction(0),)
    assert terminal.episode_metrics is not None
    assert terminal.episode_metrics.completed == 1
    assert terminal.episode_metrics.completed_response_sum == 2


def test_exact_position_allows_deadline_and_terminal_equality() -> None:
    deadline_equal = _snapshot(
        tasks=(_task(0, arrival_step=4, deadline=6),),
        absolute_step=5,
        steps_remaining=3,
    )
    terminal_equal = _snapshot(
        tasks=(_task(1, arrival_step=4, deadline=20),),
        absolute_step=5,
        steps_remaining=1,
    )

    controller = ReactiveController(1.0)
    assert controller.act(deadline_equal) == (ServeAction(0),)
    assert controller.act(terminal_equal) == (ServeAction(1),)


def test_predicted_earliest_completion_matches_environment_rollout() -> None:
    event = _event(
        0,
        arrival_step=5,
        position=(2.0, 0.0),
        service_time=2,
        deadline=9,
    )
    trace = _trace((event,), start_step=5, num_steps=5)
    config = ResourceServiceConfig(((0.0, 0.0),), 1.0)

    actions, metrics = _rollout(trace, config)

    assert actions == (
        (MoveAction((2.0, 0.0)),),
        (MoveAction((2.0, 0.0)),),
        (ServeAction(0),),
        (ContinueAction(),),
        (IdleAction(),),
    )
    assert metrics.completed == 1
    assert metrics.completed_response_sum == 4
    assert metrics.movement_slots == 2
    assert metrics.service_slots == 2
    assert metrics.idle_slots == 1
    assert metrics.duplicate_assignment_conflicts == 0


def test_repeated_full_rollout_has_identical_actions_and_episode_metrics() -> None:
    events = (
        _event(0, position=(1.0, 0.0), service_time=2, deadline=4),
        _event(1, arrival_step=1, position=(0.0, 0.0), deadline=4),
    )
    trace = _trace(events, start_step=0, num_steps=4)
    config = ResourceServiceConfig(((0.0, 0.0), (2.0, 0.0)), 1.0)

    first_actions, first_metrics = _rollout(trace, config)
    second_actions, second_metrics = _rollout(trace, config)

    assert first_actions == second_actions
    assert first_metrics == second_metrics
    assert first_metrics.duplicate_assignment_conflicts == 0
    for step_actions in first_actions:
        serve_ids = [action.event_id for action in step_actions if isinstance(action, ServeAction)]
        assert len(serve_ids) == len(set(serve_ids))


def test_action_tuple_length_and_resource_order_are_total() -> None:
    resources = tuple(_resource(index, (float(index), 0.0)) for index in range(4))
    actions = ReactiveController(1.0).act(_snapshot(resources=resources))

    assert isinstance(actions, tuple)
    assert len(actions) == len(resources)
    assert all(isinstance(action, IdleAction) for action in actions)
