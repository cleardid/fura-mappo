from __future__ import annotations

import math
import random
from collections.abc import Callable

import numpy as np
import pytest

from fura_mappo.demand import DemandEvent, DemandTrace
from fura_mappo.envs import (
    ContinueAction,
    IdleAction,
    MoveAction,
    ResourceServiceConfig,
    ResourceServiceEnvironment,
    ResourceStatus,
    ServeAction,
    TaskStatus,
)
from fura_mappo.envs._movement import _calculate_single_slot_move


def _event(
    event_id: int,
    arrival_step: int,
    *,
    zone_id: int = 0,
    position: tuple[float, float] = (0.0, 0.0),
    priority: float = 0.5,
    service_time: int = 1,
    deadline: int | None = None,
) -> DemandEvent:
    return DemandEvent(
        event_id=event_id,
        arrival_step=arrival_step,
        zone_id=zone_id,
        position=position,
        priority=priority,
        service_time=service_time,
        deadline=arrival_step + 1 if deadline is None else deadline,
    )


def _trace(
    events: tuple[DemandEvent, ...] = (),
    *,
    start_step: int = 0,
    num_steps: int = 1,
    num_zones: int = 1,
    intensity: float = 0.0,
) -> DemandTrace:
    counts = np.zeros((num_steps, num_zones), dtype=np.int64)
    for event in events:
        counts[event.arrival_step - start_step, event.zone_id] += 1
    intensities = np.full((num_steps, num_zones), intensity, dtype=np.float64)
    return DemandTrace(start_step, counts, intensities, events)


def _env(
    positions: object = ((0.0, 0.0),),
    speed: float = 1.0,
) -> ResourceServiceEnvironment:
    return ResourceServiceEnvironment(
        ResourceServiceConfig(positions, speed),  # type: ignore[arg-type]
    )


def _exception_signature(call: Callable[[], object]) -> tuple[type[Exception], str]:
    try:
        call()
    except Exception as error:
        return type(error), str(error)
    raise AssertionError("预期调用抛出异常")


def _assert_numpy_states_equal(left: tuple[object, ...], right: tuple[object, ...]) -> None:
    assert left[0] == right[0]
    np.testing.assert_array_equal(left[1], right[1])
    assert left[2:] == right[2:]


def test_step_before_reset_and_after_terminal_are_rejected_atomically() -> None:
    env = _env()
    with pytest.raises(ValueError, match="reset"):
        env.step((IdleAction(),))

    env.reset(_trace())
    result = env.step((IdleAction(),))
    terminal_state = env._state

    assert result.is_terminal
    with pytest.raises(ValueError, match="terminal"):
        env.step((IdleAction(),))
    assert env._state is terminal_state


def test_reset_injects_current_arrivals_and_supports_nonzero_unordered_steps() -> None:
    events = (
        _event(0, 6, deadline=8),
        _event(1, 5, deadline=7),
    )
    env = _env()

    snapshot = env.reset(_trace(events, start_step=5, num_steps=2))

    assert snapshot.absolute_step == 5
    assert snapshot.steps_remaining == 2
    assert [event.event_id for event in snapshot.current_arrivals] == [1]
    assert [task.event.event_id for task in snapshot.active_tasks] == [1]

    result = env.step((IdleAction(),))
    assert result.next_snapshot is not None
    assert result.next_snapshot.absolute_step == 6
    assert result.next_snapshot.steps_remaining == 1
    assert [event.event_id for event in result.next_snapshot.current_arrivals] == [0]


def test_service_time_one_completes_before_same_boundary_expiration() -> None:
    event = _event(0, 0, service_time=1, deadline=1)
    env = _env()
    snapshot = env.reset(_trace((event,)))

    result = env.step((ServeAction(0),))
    metrics = result.episode_metrics

    assert snapshot.current_arrivals == (event,)
    assert result.is_terminal and result.next_snapshot is None
    assert result.step_metrics.completed == 1
    assert result.step_metrics.expired == 0
    assert metrics is not None
    assert (metrics.completed, metrics.expired, metrics.truncated) == (1, 0, 0)
    assert metrics.completed_response_sum == 1
    assert metrics.service_start_wait_sum == 0
    assert metrics.service_slots == 1
    assert env._state is not None
    assert env._state.resource_to_event == (None,)


def test_move_clamps_exactly_and_cannot_service_until_next_slot() -> None:
    event = _event(0, 0, position=(1.0, 0.0), deadline=3)
    env = _env(speed=1.0)
    env.reset(_trace((event,), num_steps=3))
    action = MoveAction((1.0, 0.0))

    moved = env.step((action,))
    assert moved.next_snapshot is not None
    assert moved.next_snapshot.resources[0].position is action.target_position
    assert moved.next_snapshot.resources[0].position == event.position
    assert moved.next_snapshot.active_tasks[0].status is TaskStatus.WAITING
    assert moved.step_metrics.movement_slots == 1
    assert moved.step_metrics.service_slots == 0

    served = env.step((ServeAction(0),))
    assert served.next_snapshot is not None
    assert served.step_metrics.completed == 1
    assert served.next_snapshot.active_tasks == ()

    terminal = env.step((IdleAction(),))
    assert terminal.episode_metrics is not None
    assert terminal.episode_metrics.completed == 1


def test_multi_step_movement_and_zero_distance_move_accounting() -> None:
    env = _env(speed=1.0)
    env.reset(_trace(num_steps=3))

    first = env.step((MoveAction((2.0, 0.0)),))
    assert first.next_snapshot is not None
    assert first.next_snapshot.resources[0].position == (1.0, 0.0)
    assert first.step_metrics.movement_distance == 1.0

    second = env.step((MoveAction((2.0, 0.0)),))
    assert second.next_snapshot is not None
    assert second.next_snapshot.resources[0].position == (2.0, 0.0)
    assert second.step_metrics.movement_slots == 1

    terminal = env.step((MoveAction((2.0, 0.0)),))
    assert terminal.step_metrics.zero_distance_moves == 1
    assert terminal.step_metrics.movement_slots == 0
    assert terminal.step_metrics.idle_slots == 1
    assert terminal.episode_metrics is not None
    assert terminal.episode_metrics.movement_distance == 2.0
    assert terminal.episode_metrics.zero_distance_moves == 1


def test_move_contracts_actual_float_position_without_epsilon() -> None:
    current = (-0.6475645430192594, -0.5360862663609285)
    target = (-0.5333278326382778, -0.030074539317286764)
    movement_speed = 0.1
    env = _env(positions=(current,), speed=movement_speed)
    env.reset(_trace(num_steps=2))

    result = env.step((MoveAction(target),))

    assert result.next_snapshot is not None
    candidate = result.next_snapshot.resources[0].position
    actual_distance = math.hypot(
        candidate[0] - current[0],
        candidate[1] - current[1],
    )
    assert all(math.isfinite(coordinate) for coordinate in candidate)
    assert 0.0 < actual_distance <= movement_speed
    assert result.step_metrics.movement_distance == actual_distance
    displacement = (
        candidate[0] - current[0],
        candidate[1] - current[1],
    )
    target_direction = (
        target[0] - current[0],
        target[1] - current[1],
    )
    assert (
        math.fsum(
            component * direction
            for component, direction in zip(displacement, target_direction, strict=True)
        )
        > 0.0
    )
    assert math.hypot(target[0] - candidate[0], target[1] - candidate[1]) < math.hypot(
        target[0] - current[0],
        target[1] - current[1],
    )


def test_exact_position_has_no_hidden_tolerance() -> None:
    event = _event(0, 0, position=(1.0, 0.0), deadline=2)
    almost = math.nextafter(1.0, 0.0)
    env = _env(positions=((almost, 0.0),))
    env.reset(_trace((event,), num_steps=2))
    before = env._state

    with pytest.raises(ValueError, match="精确位于"):
        env.step((ServeAction(0),))
    assert env._state is before


def test_in_service_expiration_releases_resource_at_boundary() -> None:
    event = _event(0, 0, service_time=3, deadline=2)
    env = _env()
    env.reset(_trace((event,), num_steps=3))

    first = env.step((ServeAction(0),))
    assert first.next_snapshot is not None
    assert first.next_snapshot.resources[0].status is ResourceStatus.SERVING
    assert first.next_snapshot.active_tasks[0].remaining_service == 2
    assert first.next_snapshot.active_tasks[0].assigned_resource_id == 0

    expired = env.step((ContinueAction(),))
    assert expired.next_snapshot is not None
    assert expired.step_metrics.expired == 1
    assert expired.next_snapshot.resources[0].status is ResourceStatus.AVAILABLE
    assert expired.next_snapshot.active_tasks == ()

    terminal = env.step((IdleAction(),))
    metrics = terminal.episode_metrics
    assert metrics is not None
    assert metrics.expired_service_work == 2
    assert metrics.expired_remaining_work == 1


def test_last_slot_completion_and_terminal_truncation_are_distinct() -> None:
    completing = _event(0, 1, service_time=1, deadline=2)
    env = _env()
    first = env.reset(_trace((completing,), num_steps=2))
    assert first.active_tasks == ()
    arrival = env.step((IdleAction(),))
    assert arrival.next_snapshot is not None
    assert arrival.next_snapshot.current_arrivals == (completing,)
    completed = env.step((ServeAction(0),))
    assert completed.episode_metrics is not None
    assert completed.episode_metrics.completed == 1

    unfinished = _event(0, 0, service_time=2, deadline=5)
    truncated_env = _env()
    truncated_env.reset(_trace((unfinished,)))
    truncated = truncated_env.step((ServeAction(0),))
    assert truncated.step_metrics.truncated == 1
    assert truncated.episode_metrics is not None
    assert truncated.episode_metrics.truncated_service_work == 1
    assert truncated.episode_metrics.truncated_remaining_work == 1


def test_terminal_expiration_precedes_truncation() -> None:
    event = _event(0, 0, service_time=2, deadline=1)
    env = _env()
    env.reset(_trace((event,)))

    result = env.step((ServeAction(0),))

    assert result.step_metrics.expired == 1
    assert result.step_metrics.truncated == 0
    assert result.episode_metrics is not None
    assert result.episode_metrics.expired == 1


def test_duplicate_serve_uses_lowest_resource_id_and_counts_losers_idle() -> None:
    event = _event(0, 0, service_time=2, deadline=3)
    env = _env(positions=((0.0, 0.0),) * 3)
    env.reset(_trace((event,), num_steps=2))

    first = env.step((ServeAction(0), ServeAction(0), ServeAction(0)))

    assert first.next_snapshot is not None
    assert first.next_snapshot.resources[0].assigned_event_id == 0
    assert first.next_snapshot.resources[1].status is ResourceStatus.AVAILABLE
    assert first.next_snapshot.resources[2].status is ResourceStatus.AVAILABLE
    assert first.next_snapshot.active_tasks[0].assigned_resource_id == 0
    assert first.step_metrics.duplicate_assignment_conflicts == 2
    assert first.step_metrics.service_slots == 1
    assert first.step_metrics.idle_slots == 2

    terminal = env.step((ContinueAction(), IdleAction(), IdleAction()))
    assert terminal.episode_metrics is not None
    assert terminal.episode_metrics.duplicate_assignment_conflicts == 2


def test_multiple_tasks_at_same_position_can_be_served_by_different_resources() -> None:
    events = (_event(0, 0), _event(1, 0))
    env = _env(positions=((0.0, 0.0), (0.0, 0.0)))
    env.reset(_trace(events))

    result = env.step((ServeAction(0), ServeAction(1)))

    assert result.episode_metrics is not None
    assert result.episode_metrics.completed == 2
    assert result.step_metrics.service_slots == 2


@pytest.mark.parametrize(
    "actions",
    [
        [IdleAction()],
        (),
        (IdleAction(), IdleAction()),
        (object(),),
        (ContinueAction(),),
        (ServeAction(999),),
    ],
)
def test_invalid_actions_do_not_modify_or_advance_state(actions: object) -> None:
    env = _env()
    env.reset(_trace(num_steps=2))
    before = env._state

    with pytest.raises((TypeError, ValueError)):
        env.step(actions)  # type: ignore[arg-type]

    assert env._state is before


def test_serving_resource_cannot_preempt_migrate_or_accept_cooperation() -> None:
    event = _event(0, 0, service_time=3, deadline=4)
    env = _env(positions=((0.0, 0.0), (0.0, 0.0)))
    env.reset(_trace((event,), num_steps=3))
    env.step((ServeAction(0), IdleAction()))
    before = env._state

    with pytest.raises(ValueError, match="ContinueAction"):
        env.step((MoveAction((1.0, 0.0)), IdleAction()))
    assert env._state is before

    message = _exception_signature(lambda: env.step((ContinueAction(), ServeAction(0))))
    unknown = _exception_signature(lambda: env.step((ContinueAction(), ServeAction(999))))
    assert message == unknown
    assert env._state is before


def test_future_and_unknown_event_ids_have_identical_public_errors() -> None:
    future_event = _event(99, 1, deadline=3)
    with_future = _env()
    without_future = _env()
    snapshot_with = with_future.reset(_trace((future_event,), num_steps=2))
    snapshot_without = without_future.reset(_trace(num_steps=2))
    state_with = with_future._state
    state_without = without_future._state

    future_signature = _exception_signature(lambda: with_future.step((ServeAction(99),)))
    unknown_signature = _exception_signature(lambda: without_future.step((ServeAction(99),)))

    assert (
        future_signature
        == unknown_signature
        == (
            ValueError,
            "event_id 必须引用当前 WAITING 任务",
        )
    )
    assert with_future._state is state_with
    assert without_future._state is state_without
    assert snapshot_with == snapshot_without
    assert not hasattr(with_future, "source")
    assert not hasattr(with_future, "future_schedule")


def test_completed_expired_future_and_unknown_ids_share_one_public_error() -> None:
    events = (
        _event(0, 0, service_time=1, deadline=3),
        _event(1, 0, service_time=2, deadline=1),
        _event(2, 2, deadline=3),
    )
    env = _env(positions=((0.0, 0.0), (0.0, 0.0)))
    env.reset(_trace(events, num_steps=3))
    first = env.step((ServeAction(0), IdleAction()))
    before = env._state

    assert first.next_snapshot is not None
    assert first.step_metrics.completed == 1
    assert first.step_metrics.expired == 1
    signatures = {
        _exception_signature(
            lambda event_id=event_id: env.step((ServeAction(event_id), IdleAction()))
        )
        for event_id in (0, 1, 2, 999)
    }

    assert signatures == {(ValueError, "event_id 必须引用当前 WAITING 任务")}
    assert env._state is before


def test_displacement_overflow_is_rejected_before_commit() -> None:
    env = _env(positions=((-1e308, 0.0),), speed=1.0)
    env.reset(_trace(num_steps=2))
    before = env._state

    with pytest.raises(ValueError, match="displacement"):
        env.step((MoveAction((1e308, 0.0)),))
    assert env._state is before


def test_second_resource_move_failure_does_not_commit_first_move() -> None:
    env = _env(positions=((0.0, 0.0), (-1e308, 0.0)), speed=1.0)
    snapshot = env.reset(_trace(num_steps=2))
    before = env._state

    with pytest.raises(ValueError, match="displacement"):
        env.step((MoveAction((1.0, 0.0)), MoveAction((1e308, 0.0))))

    assert env._state is before
    assert snapshot.resources[0].position == (0.0, 0.0)


def test_unrepresentable_positive_move_is_rejected() -> None:
    current = 1e308
    target = math.nextafter(current, math.inf)
    env = _env(positions=((current, 0.0),), speed=1.0)
    env.reset(_trace(num_steps=2))
    before = env._state

    with pytest.raises(ValueError, match="可表示的正位移"):
        env.step((MoveAction((target, 0.0)),))
    assert env._state is before


def test_cumulative_distance_overflow_is_rejected_atomically() -> None:
    env = _env(positions=((0.0, 0.0), (0.0, 0.0)), speed=1e308)
    env.reset(_trace(num_steps=2))
    before = env._state

    with pytest.raises(ValueError, match="movement_distance"):
        env.step((MoveAction((1e308, 0.0)), MoveAction((-1e308, 0.0))))
    assert env._state is before


def test_failed_reset_preserves_previous_episode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = _env()
    env.reset(_trace(num_steps=2))
    before = env._state

    def fail_snapshot(state: object) -> object:
        raise RuntimeError("snapshot failure")

    monkeypatch.setattr(env, "_build_snapshot", fail_snapshot)
    with pytest.raises(RuntimeError, match="snapshot failure"):
        env.reset(_trace(start_step=5, num_steps=2))
    assert env._state is before


def test_reset_rejects_non_trace_without_destroying_previous_episode() -> None:
    env = _env()
    env.reset(_trace(num_steps=2))
    before = env._state

    with pytest.raises(TypeError, match="DemandTrace"):
        env.reset(object())  # type: ignore[arg-type]

    assert env._state is before


def test_snapshot_failure_cannot_commit_step(monkeypatch: pytest.MonkeyPatch) -> None:
    env = _env()
    env.reset(_trace(num_steps=2))
    before = env._state

    def fail_snapshot(state: object) -> object:
        raise RuntimeError("snapshot failure")

    monkeypatch.setattr(env, "_build_snapshot", fail_snapshot)
    with pytest.raises(RuntimeError, match="snapshot failure"):
        env.step((IdleAction(),))
    assert env._state is before


def test_metrics_failure_cannot_commit_terminal_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = _env()
    env.reset(_trace())
    before = env._state

    def fail_metrics(state: object) -> object:
        raise RuntimeError("metrics failure")

    monkeypatch.setattr(env, "_build_episode_metrics", fail_metrics)
    with pytest.raises(RuntimeError, match="metrics failure"):
        env.step((IdleAction(),))
    assert env._state is before


def test_different_actions_cannot_change_future_arrivals() -> None:
    event = _event(0, 1, deadline=3)
    trace = _trace((event,), num_steps=2)
    idle_env = _env()
    moving_env = _env()
    idle_env.reset(trace)
    moving_env.reset(trace)

    idle = idle_env.step((IdleAction(),))
    moving = moving_env.step((MoveAction((1.0, 0.0)),))

    assert idle.next_snapshot is not None and moving.next_snapshot is not None
    assert idle.next_snapshot.current_arrivals == moving.next_snapshot.current_arrivals == (event,)


def test_changed_intensities_with_same_events_do_not_change_dynamics() -> None:
    event = _event(0, 0)
    zero = _trace((event,), intensity=0.0)
    high = _trace((event,), intensity=999.0)
    first = _env()
    second = _env()

    assert first.reset(zero) == second.reset(high)
    assert first.step((ServeAction(0),)) == second.step((ServeAction(0),))


def test_terminal_metrics_satisfy_all_task_and_resource_conservation() -> None:
    events = (
        _event(0, 0, zone_id=0, priority=0.2, service_time=1, deadline=1),
        _event(1, 0, zone_id=1, priority=0.3, service_time=3, deadline=1),
        _event(2, 0, zone_id=1, priority=0.5, service_time=3, deadline=5),
    )
    env = _env(positions=((0.0, 0.0),) * 3)
    env.reset(_trace(events, num_steps=2, num_zones=2))
    first = env.step((ServeAction(0), ServeAction(1), ServeAction(2)))
    assert first.next_snapshot is not None

    terminal = env.step((IdleAction(), IdleAction(), ContinueAction()))
    metrics = terminal.episode_metrics

    assert metrics is not None
    assert (metrics.arrived, metrics.completed, metrics.expired, metrics.truncated) == (
        3,
        1,
        1,
        1,
    )
    assert metrics.demanded_service_work == 7
    assert metrics.service_slots == 4
    assert (
        metrics.completed_service_work,
        metrics.expired_service_work,
        metrics.expired_remaining_work,
        metrics.truncated_service_work,
        metrics.truncated_remaining_work,
    ) == (1, 1, 2, 2, 1)
    assert metrics.service_slots == (
        metrics.completed_service_work
        + metrics.expired_service_work
        + metrics.truncated_service_work
    )
    assert metrics.demanded_service_work == (
        metrics.completed_service_work
        + metrics.expired_service_work
        + metrics.expired_remaining_work
        + metrics.truncated_service_work
        + metrics.truncated_remaining_work
    )
    assert 3 * 2 == metrics.service_slots + metrics.movement_slots + metrics.idle_slots
    assert metrics.per_zone_arrived == (1, 2)
    assert metrics.per_zone_completed == (1, 0)
    assert metrics.per_zone_expired == (0, 1)
    assert metrics.per_zone_truncated == (0, 1)
    for zone_id in range(2):
        assert metrics.per_zone_arrived[zone_id] == (
            metrics.per_zone_completed[zone_id]
            + metrics.per_zone_expired[zone_id]
            + metrics.per_zone_truncated[zone_id]
        )
    assert metrics.arrived_priority_sum == pytest.approx(1.0)
    assert metrics.service_start_count == 3
    assert metrics.service_start_wait_sum == 0
    assert metrics.completed_response_sum == 1
    assert env._state is not None
    assert env._state.resource_to_event == (None, None, None)
    for entry in env._state.tasks.values():
        assert (entry.remaining_service == 0) == (entry.terminal_outcome is TaskStatus.COMPLETED)
        assert not hasattr(entry, "assigned_resource_id")


def test_zero_event_rates_are_none_and_slots_are_conserved() -> None:
    env = _env(positions=((0.0, 0.0), (1.0, 0.0)))
    env.reset(_trace(num_steps=2, num_zones=2))
    env.step((IdleAction(), MoveAction((2.0, 0.0))))
    terminal = env.step((IdleAction(), IdleAction()))
    metrics = terminal.episode_metrics

    assert metrics is not None
    assert metrics.arrived == 0
    assert metrics.completion_rate is None
    assert metrics.expiration_rate is None
    assert metrics.truncation_rate is None
    assert metrics.mean_service_start_wait is None
    assert metrics.mean_completed_response is None
    assert metrics.per_zone_arrived == (0, 0)
    assert 4 == metrics.service_slots + metrics.movement_slots + metrics.idle_slots


def test_environment_is_deterministic_and_does_not_pollute_global_rng() -> None:
    numpy_state = np.random.get_state()
    python_state = random.getstate()
    event = _event(0, 0, service_time=2, deadline=3)
    trace = _trace((event,), num_steps=2)
    first = _env()
    second = _env()

    first_snapshots = [first.reset(trace)]
    second_snapshots = [second.reset(trace)]
    first_results = [first.step((ServeAction(0),)), first.step((ContinueAction(),))]
    second_results = [second.step((ServeAction(0),)), second.step((ContinueAction(),))]

    assert first_snapshots == second_snapshots
    assert first_results == second_results
    _assert_numpy_states_equal(numpy_state, np.random.get_state())
    assert python_state == random.getstate()


@pytest.mark.parametrize(
    ("current", "target", "speed"),
    [
        ((0.0, 0.0), (2.0, 0.0), 1.0),
        ((0.0, 0.0), (1.0, 0.0), 1.0),
        ((1.0, 1.0), (1.0, 1.0), 1.0),
        (
            (-0.6475645430192594, -0.5360862663609285),
            (-0.5333278326382778, -0.030074539317286764),
            0.1,
        ),
    ],
)
def test_environment_move_wrapper_matches_shared_primitive(
    current: tuple[float, float],
    target: tuple[float, float],
    speed: float,
) -> None:
    env = _env(positions=(current,), speed=speed)

    shared = _calculate_single_slot_move(current, target, speed)
    wrapped = env._calculate_move(current, target)

    assert wrapped == shared
    assert wrapped.distance <= speed
    if math.hypot(target[0] - current[0], target[1] - current[1]) <= speed:
        assert wrapped.position is target


@pytest.mark.parametrize(
    ("current", "target", "speed"),
    [
        ((-1e308, 0.0), (1e308, 0.0), 1.0),
        ((1e308, 0.0), (math.nextafter(1e308, math.inf), 0.0), 1.0),
    ],
)
def test_environment_move_wrapper_preserves_shared_exception_type_and_message(
    current: tuple[float, float],
    target: tuple[float, float],
    speed: float,
) -> None:
    env = _env(positions=(current,), speed=speed)

    shared = _exception_signature(lambda: _calculate_single_slot_move(current, target, speed))
    wrapped = _exception_signature(lambda: env._calculate_move(current, target))

    assert wrapped == shared
