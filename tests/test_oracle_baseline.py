from __future__ import annotations

import inspect
import math
import random
from dataclasses import FrozenInstanceError, fields

import numpy as np
import pytest

import fura_mappo.baselines as baselines_package
import fura_mappo.baselines.oracle as oracle_module
from fura_mappo.baselines import (
    ReactiveController,
    RollingTrueFutureOracle,
    TrueFutureView,
    build_true_future_view,
)
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
    StepResult,
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
        remaining_service=service_time if remaining_service is None else remaining_service,
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
    steps_remaining: int = 5,
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
    events: tuple[DemandEvent, ...] = (),
    *,
    start_step: int = 0,
    num_steps: int = 5,
) -> DemandTrace:
    counts = np.zeros((num_steps, 1), dtype=np.int64)
    for event in events:
        counts[event.arrival_step - start_step, 0] += 1
    return DemandTrace(
        start_step=start_step,
        counts=counts,
        intensities=np.zeros((num_steps, 1), dtype=np.float64),
        events=events,
    )


def _rollout_reactive(
    trace: DemandTrace,
    config: ResourceServiceConfig,
) -> tuple[tuple[tuple[ResourceAction, ...], ...], tuple[StepResult, ...], EpisodeMetrics]:
    environment = ResourceServiceEnvironment(config)
    controller = ReactiveController(config.movement_speed)
    snapshot: EnvironmentSnapshot | None = environment.reset(trace)
    actions: list[tuple[ResourceAction, ...]] = []
    results: list[StepResult] = []
    while snapshot is not None:
        step_actions = controller.act(snapshot)
        result = environment.step(step_actions)
        actions.append(step_actions)
        results.append(result)
        snapshot = result.next_snapshot
    metrics = results[-1].episode_metrics
    if metrics is None:
        raise AssertionError("terminal rollout 必须返回 EpisodeMetrics")
    return tuple(actions), tuple(results), metrics


def _rollout_oracle(
    trace: DemandTrace,
    config: ResourceServiceConfig,
    horizon: int,
) -> tuple[tuple[tuple[ResourceAction, ...], ...], tuple[StepResult, ...], EpisodeMetrics]:
    environment = ResourceServiceEnvironment(config)
    controller = RollingTrueFutureOracle(config.movement_speed, horizon)
    snapshot: EnvironmentSnapshot | None = environment.reset(trace)
    actions: list[tuple[ResourceAction, ...]] = []
    results: list[StepResult] = []
    while snapshot is not None:
        view = build_true_future_view(trace, snapshot, horizon)
        step_actions = controller.act(snapshot, view)
        result = environment.step(step_actions)
        actions.append(step_actions)
        results.append(result)
        snapshot = result.next_snapshot
    metrics = results[-1].episode_metrics
    if metrics is None:
        raise AssertionError("terminal rollout 必须返回 EpisodeMetrics")
    return tuple(actions), tuple(results), metrics


def _assert_numpy_states_equal(left: tuple[object, ...], right: tuple[object, ...]) -> None:
    assert left[0] == right[0]
    np.testing.assert_array_equal(left[1], right[1])
    assert left[2:] == right[2:]


def _unsafe_replace_events(
    view: TrueFutureView,
    events: tuple[DemandEvent, ...],
) -> TrueFutureView:
    object.__setattr__(view, "future_events", events)
    return view


@pytest.mark.parametrize("value", [True, np.bool_(False)])
def test_horizon_rejects_boolean(value: object) -> None:
    with pytest.raises(TypeError, match="布尔"):
        RollingTrueFutureOracle(1.0, value)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="布尔"):
        TrueFutureView(0, value, ())  # type: ignore[arg-type]


def test_horizon_rejects_negative_and_accepts_zero_positive_and_very_large() -> None:
    with pytest.raises(ValueError, match="非负"):
        RollingTrueFutureOracle(1.0, -1)

    zero = RollingTrueFutureOracle(1.0, 0)
    positive = RollingTrueFutureOracle(1.0, np.int64(3))
    huge = TrueFutureView(np.int64(0), 10**100, ())

    assert zero._horizon == 0
    assert positive._horizon == 3
    assert huge.horizon == 10**100


@pytest.mark.parametrize("speed", [True, "1.0", 0.0, -1.0, math.nan, math.inf])
def test_movement_speed_validation_matches_reactive(speed: object) -> None:
    def signature(factory: object) -> tuple[type[Exception], str]:
        try:
            factory(speed)  # type: ignore[operator]
        except Exception as error:
            return type(error), str(error)
        raise AssertionError("预期非法 movement_speed 抛错")

    assert signature(ReactiveController) == signature(
        lambda value: RollingTrueFutureOracle(value, 1)
    )


def test_true_future_view_is_frozen_slotted_and_defensively_canonical() -> None:
    later = _event(3, arrival_step=3, deadline=5)
    earlier_large_id = _event(2, arrival_step=2, deadline=5)
    earlier_small_id = _event(1, arrival_step=2, deadline=5)
    source = [later, earlier_large_id, earlier_small_id]

    view = TrueFutureView(1, 2, source)  # type: ignore[arg-type]
    source.clear()

    assert view.future_events == (earlier_small_id, earlier_large_id, later)
    assert not hasattr(view, "__dict__")
    with pytest.raises(FrozenInstanceError):
        view.horizon = 9  # type: ignore[misc]


@pytest.mark.parametrize("value", [True, np.bool_(True), -1])
def test_true_future_view_rejects_invalid_absolute_step(value: object) -> None:
    error_type = TypeError if isinstance(value, (bool, np.bool_)) else ValueError
    with pytest.raises(error_type):
        TrueFutureView(value, 0, ())  # type: ignore[arg-type]


def test_true_future_view_rejects_event_type_and_duplicate_ids() -> None:
    with pytest.raises(TypeError, match="DemandEvent"):
        TrueFutureView(0, 1, (object(),))  # type: ignore[arg-type]

    first = _event(1, arrival_step=1, deadline=3)
    duplicate = _event(1, arrival_step=2, deadline=4)
    with pytest.raises(ValueError, match="唯一"):
        TrueFutureView(0, 2, (first, duplicate))


def test_true_future_view_local_window_boundaries() -> None:
    lower = _event(0, arrival_step=6, deadline=9)
    upper = _event(1, arrival_step=7, deadline=9)
    assert TrueFutureView(5, 2, (upper, lower)).future_events == (lower, upper)

    too_late = _event(2, arrival_step=8, deadline=9)
    with pytest.raises(ValueError, match="arrival_step"):
        TrueFutureView(5, 2, (too_late,))
    with pytest.raises(ValueError, match="为空"):
        TrueFutureView(5, 0, (lower,))


def test_builder_rejects_wrong_source_snapshot_and_horizon_types() -> None:
    trace = _trace()
    snapshot = _snapshot()
    with pytest.raises(TypeError, match="DemandTrace"):
        build_true_future_view(object(), snapshot, 1)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="EnvironmentSnapshot"):
        build_true_future_view(trace, object(), 1)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="布尔"):
        build_true_future_view(trace, snapshot, True)


def test_builder_window_boundaries_clamp_and_nonzero_start() -> None:
    events = (
        _event(0, arrival_step=5, deadline=10),
        _event(1, arrival_step=6, deadline=10),
        _event(2, arrival_step=7, deadline=10),
        _event(3, arrival_step=8, deadline=10),
        _event(4, arrival_step=9, deadline=10),
    )
    trace = _trace(events, start_step=5, num_steps=5)
    environment = ResourceServiceEnvironment(ResourceServiceConfig(((0.0, 0.0),), 1.0))
    snapshot = environment.reset(trace)

    assert build_true_future_view(trace, snapshot, 0).future_events == ()
    assert build_true_future_view(trace, snapshot, 2).future_events == events[1:3]
    assert build_true_future_view(trace, snapshot, 3).future_events == events[1:4]
    assert build_true_future_view(trace, snapshot, 10**100).future_events == events[1:]


def test_builder_rejects_source_stop_current_arrival_and_active_task_mismatch() -> None:
    current = _event(0, arrival_step=0, deadline=3)
    trace = _trace((current,), num_steps=3)
    environment = ResourceServiceEnvironment(ResourceServiceConfig(((0.0, 0.0),), 1.0))
    snapshot = environment.reset(trace)

    wrong_stop = _trace((current,), num_steps=4)
    with pytest.raises(ValueError, match="终点"):
        build_true_future_view(wrong_stop, snapshot, 1)

    missing_current = _trace((), num_steps=3)
    with pytest.raises(ValueError, match="当前到达"):
        build_true_future_view(missing_current, snapshot, 1)

    changed = _event(0, arrival_step=0, position=(1.0, 0.0), deadline=3)
    changed_trace = _trace((changed,), num_steps=3)
    changed_snapshot = _snapshot(
        tasks=(TaskSnapshot(current, TaskStatus.WAITING, None, 1, None, None),),
        absolute_step=1,
        steps_remaining=2,
    )
    with pytest.raises(ValueError, match="active task"):
        build_true_future_view(changed_trace, changed_snapshot, 1)


def test_builder_output_exposes_only_demand_events_not_trace_arrays() -> None:
    event = _event(0, arrival_step=1, deadline=3)
    trace = _trace((event,), num_steps=3)
    snapshot = ResourceServiceEnvironment(ResourceServiceConfig(((0.0, 0.0),), 1.0)).reset(trace)

    view = build_true_future_view(trace, snapshot, 1)

    assert tuple(field.name for field in fields(view)) == (
        "absolute_step",
        "horizon",
        "future_events",
    )
    assert view.future_events == (event,)
    for forbidden in ("counts", "intensities", "config", "seed", "rng", "manifest"):
        assert not hasattr(view, forbidden)


def test_act_rejects_wrong_input_types_and_misordered_resources() -> None:
    oracle = RollingTrueFutureOracle(1.0, 1)
    view = TrueFutureView(0, 1, ())
    with pytest.raises(TypeError, match="EnvironmentSnapshot"):
        oracle.act(object(), view)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="TrueFutureView"):
        oracle.act(_snapshot(), object())  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="resource_id"):
        oracle.act(_snapshot(resources=(_resource(1), _resource(0))), view)


def test_act_rejects_view_step_and_horizon_mismatch() -> None:
    oracle = RollingTrueFutureOracle(1.0, 2)
    with pytest.raises(ValueError, match="absolute_step"):
        oracle.act(_snapshot(), TrueFutureView(1, 2, ()))
    with pytest.raises(ValueError, match="Oracle horizon"):
        oracle.act(_snapshot(), TrueFutureView(0, 1, ()))


def test_act_rechecks_terminal_clamp_for_manual_view() -> None:
    event = _event(0, arrival_step=3, deadline=5)
    view = TrueFutureView(0, 3, (event,))
    snapshot = _snapshot(steps_remaining=3)

    with pytest.raises(ValueError, match="clamped"):
        RollingTrueFutureOracle(1.0, 3).act(snapshot, view)


def test_act_rechecks_duplicate_ids_after_manual_mutation() -> None:
    first = _event(1, arrival_step=1, deadline=3)
    duplicate = _event(1, arrival_step=2, deadline=4)
    view = _unsafe_replace_events(TrueFutureView(0, 2, (first,)), (first, duplicate))

    with pytest.raises(ValueError, match="唯一"):
        RollingTrueFutureOracle(1.0, 2).act(_snapshot(), view)


@pytest.mark.parametrize("overlap_source", ["active", "arrival"])
def test_act_rejects_current_future_id_overlap(overlap_source: str) -> None:
    future = _event(7, arrival_step=1, deadline=3)
    view = TrueFutureView(0, 1, (future,))
    if overlap_source == "active":
        snapshot = _snapshot(tasks=(_task(7, deadline=3),))
    else:
        snapshot = _snapshot(current_arrivals=(_event(7, deadline=3),))

    with pytest.raises(ValueError, match="重叠"):
        RollingTrueFutureOracle(1.0, 1).act(snapshot, view)


def test_horizon_zero_action_values_equal_reactive() -> None:
    snapshot = _snapshot(
        resources=(
            _resource(0),
            _resource(1, status=ResourceStatus.SERVING, assigned_event_id=5),
        ),
        tasks=(
            _task(1, position=(1.0, 0.0), deadline=4),
            _task(
                5,
                service_time=2,
                status=TaskStatus.IN_SERVICE,
                assigned_resource_id=1,
            ),
        ),
    )

    reactive_actions = ReactiveController(1.0).act(snapshot)
    oracle_actions = RollingTrueFutureOracle(1.0, 0).act(
        snapshot,
        TrueFutureView(0, 0, ()),
    )

    assert oracle_actions == reactive_actions


def test_positive_horizon_empty_view_action_values_equal_reactive() -> None:
    snapshot = _snapshot(tasks=(_task(0, deadline=2),))
    reactive_actions = ReactiveController(1.0).act(snapshot)

    assert (
        RollingTrueFutureOracle(1.0, 3).act(
            snapshot,
            TrueFutureView(0, 3, ()),
        )
        == reactive_actions
    )


def test_all_future_pairs_physically_infeasible_delegates_reactive() -> None:
    current = _task(0, deadline=2)
    impossible = _event(
        1,
        arrival_step=1,
        position=(10.0, 0.0),
        service_time=1,
        deadline=2,
    )
    snapshot = _snapshot(tasks=(current,), steps_remaining=2)
    view = TrueFutureView(0, 1, (impossible,))

    assert RollingTrueFutureOracle(1.0, 1).act(snapshot, view) == (
        ReactiveController(1.0).act(snapshot)
    )


def test_future_pair_value_error_is_infeasible_and_delegates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    future = _event(1, arrival_step=1, position=(1.0, 0.0), deadline=3)
    snapshot = _snapshot(tasks=(_task(0, deadline=2),), steps_remaining=3)

    def fail_travel(*args: object, **kwargs: object) -> int:
        del args, kwargs
        raise ValueError("injected expected movement failure")

    monkeypatch.setattr(oracle_module, "_exact_travel_slots", fail_travel)
    assert RollingTrueFutureOracle(1.0, 1).act(
        snapshot,
        TrueFutureView(0, 1, (future,)),
    ) == ReactiveController(1.0).act(snapshot)


def test_horizon_zero_full_rollout_matches_actions_results_and_metrics() -> None:
    events = (
        _event(0, position=(1.0, 0.0), service_time=2, deadline=4),
        _event(1, arrival_step=1, position=(0.0, 0.0), deadline=4),
        _event(2, arrival_step=3, position=(2.0, 0.0), deadline=5),
    )
    trace = _trace(events, num_steps=5)
    config = ResourceServiceConfig(((0.0, 0.0), (2.0, 0.0)), 1.0)

    reactive_actions, reactive_results, reactive_metrics = _rollout_reactive(trace, config)
    oracle_actions, oracle_results, oracle_metrics = _rollout_oracle(trace, config, 0)

    assert oracle_actions == reactive_actions
    assert oracle_results == reactive_results
    assert oracle_metrics == reactive_metrics


def test_events_outside_window_do_not_change_action() -> None:
    outside_left = _event(0, arrival_step=3, position=(-3.0, 0.0), deadline=5)
    outside_right = _event(0, arrival_step=3, position=(3.0, 0.0), deadline=5)
    left_trace = _trace((outside_left,), num_steps=5)
    right_trace = _trace((outside_right,), num_steps=5)
    config = ResourceServiceConfig(((0.0, 0.0),), 1.0)
    left_snapshot = ResourceServiceEnvironment(config).reset(left_trace)
    right_snapshot = ResourceServiceEnvironment(config).reset(right_trace)
    oracle = RollingTrueFutureOracle(1.0, 2)

    left = oracle.act(left_snapshot, build_true_future_view(left_trace, left_snapshot, 2))
    right = oracle.act(right_snapshot, build_true_future_view(right_trace, right_snapshot, 2))

    assert left == right == (IdleAction(),)


def test_event_inside_window_can_change_action() -> None:
    left = _event(0, arrival_step=2, position=(-2.0, 0.0), deadline=3)
    right = _event(0, arrival_step=2, position=(2.0, 0.0), deadline=3)
    snapshot = _snapshot(steps_remaining=3)
    oracle = RollingTrueFutureOracle(1.0, 2)

    left_actions = oracle.act(snapshot, TrueFutureView(0, 2, (left,)))
    right_actions = oracle.act(snapshot, TrueFutureView(0, 2, (right,)))

    assert left_actions == (MoveAction((-2.0, 0.0)),)
    assert right_actions == (MoveAction((2.0, 0.0)),)


def test_oracle_controller_holds_no_trace_environment_history_or_rng() -> None:
    oracle = RollingTrueFutureOracle(1.0, 2)
    signature = inspect.signature(oracle.act)

    assert tuple(signature.parameters) == ("snapshot", "future_view")
    assert "DemandTrace" not in str(signature)
    assert RollingTrueFutureOracle.__slots__ == ("_horizon", "_reactive")
    assert not hasattr(oracle, "__dict__")
    for forbidden in (
        "trace",
        "source",
        "environment",
        "history",
        "reservation",
        "rng",
        "previous_plan",
        "movement_target",
    ):
        assert not hasattr(oracle, forbidden)


def test_baselines_package_exports_frozen_reactive_and_oracle_api() -> None:
    assert baselines_package.__all__ == [
        "ReactiveController",
        "RollingTrueFutureOracle",
        "TrueFutureView",
        "build_true_future_view",
    ]
    assert baselines_package.ReactiveController is ReactiveController
    assert baselines_package.RollingTrueFutureOracle is RollingTrueFutureOracle


def test_future_preposition_moves_then_waits_and_never_serves_before_arrival() -> None:
    event = _event(0, arrival_step=3, position=(1.0, 0.0), deadline=4)
    oracle = RollingTrueFutureOracle(1.0, 3)

    moving = oracle.act(_snapshot(steps_remaining=4), TrueFutureView(0, 3, (event,)))
    waiting_snapshot = _snapshot(
        resources=(_resource(0, (1.0, 0.0)),),
        absolute_step=1,
        steps_remaining=3,
    )
    waiting_view = TrueFutureView(1, 3, (event,))
    waiting = oracle.act(waiting_snapshot, waiting_view)

    assert moving == (MoveAction((1.0, 0.0)),)
    assert waiting == (IdleAction(),)
    assert not any(isinstance(action, ServeAction) for action in (*moving, *waiting))


def test_serving_resource_continues_and_in_service_task_is_not_rematched() -> None:
    future = _event(1, arrival_step=1, position=(2.0, 0.0), deadline=4)
    in_service = _task(
        0,
        service_time=2,
        status=TaskStatus.IN_SERVICE,
        assigned_resource_id=0,
    )
    snapshot = _snapshot(
        resources=(
            _resource(0, status=ResourceStatus.SERVING, assigned_event_id=0),
            _resource(1, (1.0, 0.0)),
        ),
        tasks=(in_service,),
        steps_remaining=4,
    )

    assert RollingTrueFutureOracle(1.0, 1).act(
        snapshot,
        TrueFutureView(0, 1, (future,)),
    ) == (ContinueAction(), MoveAction((2.0, 0.0)))


def test_future_and_current_compete_by_same_urgency() -> None:
    current = _task(0, position=(0.0, 0.0), deadline=10)
    urgent_future = _event(
        1,
        arrival_step=2,
        position=(2.0, 0.0),
        deadline=3,
    )
    snapshot = _snapshot(tasks=(current,), steps_remaining=10)

    assert RollingTrueFutureOracle(1.0, 2).act(
        snapshot,
        TrueFutureView(0, 2, (urgent_future,)),
    ) == (MoveAction((2.0, 0.0)),)

    urgent_current = _task(0, position=(0.0, 0.0), deadline=1)
    assert RollingTrueFutureOracle(1.0, 2).act(
        _snapshot(tasks=(urgent_current,), steps_remaining=3),
        TrueFutureView(0, 2, (urgent_future,)),
    ) == (ServeAction(0),)


@pytest.mark.parametrize(
    ("events", "expected_target"),
    [
        (
            (
                _event(0, arrival_step=1, position=(1.0, 0.0), deadline=5),
                _event(1, arrival_step=2, position=(2.0, 0.0), deadline=3),
            ),
            (2.0, 0.0),
        ),
        (
            (
                _event(
                    0,
                    arrival_step=1,
                    position=(1.0, 0.0),
                    priority=0.1,
                    deadline=4,
                ),
                _event(
                    1,
                    arrival_step=2,
                    position=(2.0, 0.0),
                    priority=0.9,
                    deadline=4,
                ),
            ),
            (2.0, 0.0),
        ),
        (
            (
                _event(0, arrival_step=2, position=(2.0, 0.0), deadline=4),
                _event(1, arrival_step=1, position=(1.0, 0.0), deadline=4),
            ),
            (1.0, 0.0),
        ),
        (
            (
                _event(2, arrival_step=1, position=(2.0, 0.0), deadline=4),
                _event(1, arrival_step=1, position=(1.0, 0.0), deadline=4),
            ),
            (1.0, 0.0),
        ),
    ],
)
def test_unified_task_ordering_keys(
    events: tuple[DemandEvent, ...],
    expected_target: tuple[float, float],
) -> None:
    actions = RollingTrueFutureOracle(1.0, 2).act(
        _snapshot(steps_remaining=5),
        TrueFutureView(0, 2, events),
    )

    assert actions == (MoveAction(expected_target),)


def test_resource_order_prefers_exact_slots_then_distance_then_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    future = _event(0, arrival_step=1, position=(0.0, 0.0), deadline=5)

    def controlled_slots(
        current: tuple[float, float],
        target: tuple[float, float],
        speed: float,
        budget: int,
    ) -> int:
        del target, speed, budget
        return 1 if current == (2.0, 0.0) else 2

    monkeypatch.setattr(oracle_module, "_exact_travel_slots", controlled_slots)
    slots_actions = RollingTrueFutureOracle(1.0, 1).act(
        _snapshot(resources=(_resource(0, (1.0, 0.0)), _resource(1, (2.0, 0.0)))),
        TrueFutureView(0, 1, (future,)),
    )
    assert slots_actions == (IdleAction(), MoveAction((0.0, 0.0)))

    monkeypatch.setattr(oracle_module, "_exact_travel_slots", lambda *args: 1)
    distance_actions = RollingTrueFutureOracle(1.0, 1).act(
        _snapshot(resources=(_resource(0, (2.0, 0.0)), _resource(1, (1.0, 0.0)))),
        TrueFutureView(0, 1, (future,)),
    )
    assert distance_actions == (IdleAction(), MoveAction((0.0, 0.0)))

    id_actions = RollingTrueFutureOracle(1.0, 1).act(
        _snapshot(resources=(_resource(0, (-1.0, 0.0)), _resource(1, (1.0, 0.0)))),
        TrueFutureView(0, 1, (future,)),
    )
    assert id_actions == (MoveAction((0.0, 0.0)), IdleAction())


def test_pair_failure_rejects_only_that_resource(monkeypatch: pytest.MonkeyPatch) -> None:
    original = oracle_module._exact_travel_slots

    def fail_one_resource(
        current: tuple[float, float],
        target: tuple[float, float],
        speed: float,
        budget: int,
    ) -> int | None:
        if current == (0.0, 0.0):
            raise ValueError("injected pair failure")
        return original(current, target, speed, budget)

    monkeypatch.setattr(oracle_module, "_exact_travel_slots", fail_one_resource)
    future = _event(0, arrival_step=1, position=(2.0, 0.0), deadline=4)
    actions = RollingTrueFutureOracle(1.0, 1).act(
        _snapshot(resources=(_resource(0), _resource(1, (1.0, 0.0))), steps_remaining=4),
        TrueFutureView(0, 1, (future,)),
    )

    assert actions == (IdleAction(), MoveAction((2.0, 0.0)))


def test_exact_travel_uses_known_three_vs_four_slot_semantics() -> None:
    current = (-0.6475645430192594, -0.5360862663609285)
    target = (-0.5333278326382778, -0.030074539317286764)
    speed = 0.17291548799738277
    distance = 0.5187464639921483
    future = _event(0, arrival_step=1, position=target, deadline=4)

    assert math.ceil(distance / speed) == 3
    assert oracle_module._exact_travel_slots(current, target, speed, 3) is None
    actions = RollingTrueFutureOracle(speed, 1).act(
        _snapshot(resources=(_resource(0, current),), steps_remaining=4),
        TrueFutureView(0, 1, (future,)),
    )

    assert actions == (IdleAction(),)


def test_replanning_is_deterministic_stateless_and_rng_free() -> None:
    numpy_state = np.random.get_state()
    python_state = random.getstate()
    future = _event(0, arrival_step=2, position=(2.0, 0.0), deadline=4)
    view = TrueFutureView(0, 2, (future,))
    snapshot = _snapshot(resources=(_resource(0), _resource(1, (3.0, 0.0))))
    oracle = RollingTrueFutureOracle(np.float64(1.0), 2)

    first = oracle.act(snapshot, view)
    second = oracle.act(snapshot, view)

    assert first == second
    assert not hasattr(oracle, "reservation")
    assert not hasattr(oracle, "history")
    assert not hasattr(oracle, "previous_plan")
    _assert_numpy_states_equal(numpy_state, np.random.get_state())
    assert python_state == random.getstate()
    serve_ids = [action.event_id for action in first if isinstance(action, ServeAction)]
    assert len(serve_ids) == len(set(serve_ids))


def test_rolling_window_transitions_future_event_to_current_waiting() -> None:
    event = _event(0, arrival_step=1, position=(1.0, 0.0), deadline=3)
    trace = _trace((event,), num_steps=3)
    config = ResourceServiceConfig(((0.0, 0.0),), 1.0)
    environment = ResourceServiceEnvironment(config)
    oracle = RollingTrueFutureOracle(1.0, 1)
    first_snapshot = environment.reset(trace)

    first_view = build_true_future_view(trace, first_snapshot, 1)
    first_actions = oracle.act(first_snapshot, first_view)
    first_result = environment.step(first_actions)
    assert first_result.next_snapshot is not None
    second_snapshot = first_result.next_snapshot
    second_view = build_true_future_view(trace, second_snapshot, 1)
    second_actions = oracle.act(second_snapshot, second_view)

    assert first_view.future_events == (event,)
    assert first_actions == (MoveAction((1.0, 0.0)),)
    assert second_view.future_events == ()
    assert second_snapshot.current_arrivals == (event,)
    assert second_snapshot.active_tasks[0].status is TaskStatus.WAITING
    assert second_actions == (ServeAction(0),)


def test_future_event_enters_window_when_horizon_rolls() -> None:
    event = _event(0, arrival_step=2, position=(1.0, 0.0), deadline=4)
    trace = _trace((event,), num_steps=4)
    environment = ResourceServiceEnvironment(ResourceServiceConfig(((0.0, 0.0),), 1.0))
    first_snapshot = environment.reset(trace)

    first_view = build_true_future_view(trace, first_snapshot, 1)
    first_result = environment.step((IdleAction(),))
    assert first_result.next_snapshot is not None
    second_view = build_true_future_view(trace, first_result.next_snapshot, 1)

    assert first_view.future_events == ()
    assert second_view.future_events == (event,)


def test_canonical_mechanism_oracle_completes_and_reactive_cannot() -> None:
    event = _event(
        0,
        arrival_step=2,
        position=(2.0, 0.0),
        service_time=1,
        deadline=3,
    )
    trace = _trace((event,), num_steps=3)
    config = ResourceServiceConfig(((0.0, 0.0),), 1.0)

    oracle_actions, _, oracle_metrics = _rollout_oracle(trace, config, 2)
    reactive_actions, _, reactive_metrics = _rollout_reactive(trace, config)

    assert oracle_actions == (
        (MoveAction((2.0, 0.0)),),
        (MoveAction((2.0, 0.0)),),
        (ServeAction(0),),
    )
    assert oracle_metrics.completed == 1
    assert oracle_metrics.expired == 0
    assert reactive_actions == ((IdleAction(),), (IdleAction(),), (IdleAction(),))
    assert reactive_metrics.completed == 0
    assert reactive_metrics.expired == 1


def test_repeated_oracle_rollout_is_identical_and_has_no_duplicate_serve() -> None:
    events = (
        _event(0, arrival_step=1, position=(1.0, 0.0), deadline=3),
        _event(1, arrival_step=2, position=(2.0, 0.0), deadline=4),
    )
    trace = _trace(events, num_steps=4)
    config = ResourceServiceConfig(((0.0, 0.0), (3.0, 0.0)), 1.0)

    first = _rollout_oracle(trace, config, 2)
    second = _rollout_oracle(trace, config, 2)

    assert first == second
    for step_actions in first[0]:
        served = [action.event_id for action in step_actions if isinstance(action, ServeAction)]
        assert len(served) == len(set(served))
    assert first[2].duplicate_assignment_conflicts == 0
