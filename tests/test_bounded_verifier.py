from __future__ import annotations

import random
from dataclasses import replace
from typing import cast

import numpy as np
import pytest

import fura_mappo.experiments as experiments_package
import fura_mappo.experiments._bounded_verifier as bounded_module
from fura_mappo.baselines import RollingTrueFutureOracle, build_true_future_view
from fura_mappo.demand import DemandEvent, DemandTrace
from fura_mappo.envs import (
    ContinueAction,
    EnvironmentSnapshot,
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
from fura_mappo.experiments._bounded_verifier import (
    BoundedDiagnosticLabel,
    BoundedFixtureComparison,
    BoundedVerifierError,
    action_key,
    classify_bounded_suite,
    enumerate_joint_actions,
    joint_action_key,
    run_bounded_verifier,
    sequence_key,
)


def _event(
    event_id: int,
    *,
    arrival: int,
    position: tuple[float, float],
    service: int = 1,
    deadline: int,
) -> DemandEvent:
    return DemandEvent(
        event_id=event_id,
        arrival_step=arrival,
        zone_id=0,
        position=position,
        priority=0.5,
        service_time=service,
        deadline=deadline,
    )


def _trace(events: tuple[DemandEvent, ...] = (), *, num_steps: int = 4) -> DemandTrace:
    counts = np.zeros((num_steps, 1), dtype=np.int64)
    for event in events:
        counts[event.arrival_step, 0] += 1
    return DemandTrace(
        start_step=0,
        counts=counts,
        intensities=np.zeros((num_steps, 1), dtype=np.float64),
        events=events,
    )


def _config(
    positions: tuple[tuple[float, float], ...] = ((0.0, 0.0),),
    speed: float = 1.0,
) -> ResourceServiceConfig:
    return ResourceServiceConfig(positions, speed)


def _rollout_primary(
    trace: DemandTrace,
    config: ResourceServiceConfig,
    horizon: int,
) -> tuple[tuple[tuple[ResourceAction, ...], ...], tuple[StepResult, ...], int]:
    environment = ResourceServiceEnvironment(config)
    controller = RollingTrueFutureOracle(config.movement_speed, horizon)
    snapshot: EnvironmentSnapshot | None = environment.reset(trace)
    actions: list[tuple[ResourceAction, ...]] = []
    results: list[StepResult] = []
    while snapshot is not None:
        view = build_true_future_view(trace, snapshot, horizon)
        joint_action = controller.act(snapshot, view)
        result = environment.step(joint_action)
        actions.append(joint_action)
        results.append(result)
        snapshot = result.next_snapshot
    metrics = results[-1].episode_metrics
    if metrics is None:
        raise AssertionError("Primary rollout 必须产生 terminal EpisodeMetrics")
    return tuple(actions), tuple(results), metrics.completed


def _fixture(
    name: str,
) -> tuple[DemandTrace, ResourceServiceConfig, int]:
    if name == "F1":
        events = (_event(0, arrival=2, position=(2.0, 0.0), deadline=3),)
        return _trace(events), _config(), 2
    if name == "F2":
        events = (
            _event(0, arrival=0, position=(0.0, 0.0), deadline=4),
            _event(1, arrival=2, position=(1.0, 0.0), deadline=3),
        )
        return _trace(events), _config(), 2
    if name == "F3":
        events = (
            _event(0, arrival=1, position=(0.0, 0.0), deadline=4),
            _event(1, arrival=2, position=(0.0, 0.0), service=2, deadline=4),
        )
        return _trace(events), _config(), 2
    if name == "F4":
        events = (
            _event(0, arrival=2, position=(1.0, 0.0), deadline=3),
            _event(1, arrival=2, position=(-2.0, 0.0), deadline=3),
        )
        return _trace(events), _config(((0.0, 0.0), (3.0, 0.0))), 2
    if name == "F5":
        events = (_event(0, arrival=2, position=(3.0, 0.0), deadline=3),)
        return _trace(events, num_steps=3), _config(), 2
    if name in {"F6A", "F6B"}:
        outside_position = (3.0, 0.0) if name == "F6A" else (-3.0, 0.0)
        events = (
            _event(0, arrival=2, position=(0.0, 0.0), deadline=3),
            _event(1, arrival=3, position=outside_position, deadline=4),
        )
        return _trace(events), _config(((0.0, 0.0), (0.0, 0.0))), 2
    raise ValueError(f"unknown fixture: {name}")


def _snapshot(
    *,
    resources: tuple[ResourceSnapshot, ...],
    tasks: tuple[TaskSnapshot, ...] = (),
    absolute_step: int = 0,
    steps_remaining: int = 2,
) -> EnvironmentSnapshot:
    return EnvironmentSnapshot(
        absolute_step=absolute_step,
        steps_remaining=steps_remaining,
        resources=resources,
        active_tasks=tasks,
        current_arrivals=(),
    )


@pytest.mark.parametrize(
    ("name", "primary_completed", "verifier_completed"),
    [
        ("F1", 1, 1),
        ("F2", 1, 2),
        ("F3", 1, 2),
        ("F4", 1, 2),
        ("F5", 0, 0),
        ("F6A", 1, 1),
        ("F6B", 1, 1),
    ],
)
def test_preregistered_fixture_acceptance_counts(
    name: str,
    primary_completed: int,
    verifier_completed: int,
) -> None:
    trace, config, horizon = _fixture(name)

    _, _, actual_primary = _rollout_primary(trace, config, horizon)
    verifier = run_bounded_verifier(trace, config, horizon)

    assert actual_primary == primary_completed
    assert verifier.episode_metrics.completed == verifier_completed
    assert len(verifier.actions) == trace.counts.shape[0]
    assert len(verifier.step_results) == trace.counts.shape[0]
    assert len(verifier.root_records) == trace.counts.shape[0]
    assert verifier.step_results[-1].is_terminal
    assert verifier.step_results[-1].episode_metrics == verifier.episode_metrics


def test_fixture_6_pair_has_identical_root_information_and_first_action() -> None:
    left_trace, config, horizon = _fixture("F6A")
    right_trace, _, _ = _fixture("F6B")

    left = run_bounded_verifier(left_trace, config, horizon)
    right = run_bounded_verifier(right_trace, config, horizon)
    left_root = left.root_records[0]
    right_root = right.root_records[0]

    assert left_root.root_snapshot == right_root.root_snapshot
    assert left_root.official_future_view == right_root.official_future_view
    assert set(left_root.k_event_ids) == set(right_root.k_event_ids) == {0}
    assert (3.0, 0.0) not in left_root.move_targets
    assert (-3.0, 0.0) not in left_root.move_targets
    assert (3.0, 0.0) not in right_root.move_targets
    assert (-3.0, 0.0) not in right_root.move_targets
    assert left.actions[0] == right.actions[0]
    assert left_root.selected_sequence[0] == right_root.selected_sequence[0]


@pytest.mark.parametrize(
    ("trace", "config", "horizon", "message"),
    [
        (_trace(num_steps=5), _config(), 2, "4 个 episode steps"),
        (
            _trace(
                tuple(
                    _event(index, arrival=index, position=(0.0, 0.0), deadline=index + 1)
                    for index in range(4)
                )
            ),
            _config(),
            2,
            "3 个 events",
        ),
        (_trace(), _config(((0.0, 0.0),) * 3), 2, "2 个 resources"),
    ],
)
def test_hard_bounds_are_rejected(
    trace: DemandTrace,
    config: ResourceServiceConfig,
    horizon: int,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        run_bounded_verifier(trace, config, horizon)


@pytest.mark.parametrize("horizon", [-1, True, 1.5, "2"])
def test_horizon_must_be_nonnegative_integer(horizon: object) -> None:
    error = TypeError if horizon in (True, 1.5, "2") else ValueError
    with pytest.raises(error):
        run_bounded_verifier(_trace(num_steps=1), _config(), horizon)  # type: ignore[arg-type]


def test_exact_action_joint_and_sequence_keys() -> None:
    move = MoveAction((-1.5, 2.0))
    serve = ServeAction(7)

    assert action_key(ContinueAction()) == (0,)
    assert action_key(IdleAction()) == (1,)
    assert action_key(move) == (2, -1.5, 2.0)
    assert action_key(serve) == (3, 7)
    joint = (serve, IdleAction(), move)
    assert joint_action_key(joint) == ((3, 7), (1,), (2, -1.5, 2.0))
    assert sequence_key((joint, (ContinueAction(), IdleAction()))) == (
        ((3, 7), (1,), (2, -1.5, 2.0)),
        ((0,), (1,)),
    )
    with pytest.raises(TypeError):
        action_key(cast(ResourceAction, object()))


def test_duplicate_positions_are_deduplicated_and_zero_distance_move_is_retained() -> None:
    events = (
        _event(0, arrival=0, position=(0.0, 0.0), deadline=3),
        _event(1, arrival=1, position=(0.0, 0.0), deadline=3),
    )
    trace = _trace(events, num_steps=3)
    snapshot = ResourceServiceEnvironment(_config()).reset(trace)
    view = build_true_future_view(trace, snapshot, 1)
    root = bounded_module._freeze_root_information(snapshot, view)

    assert root.positions == ((0.0, 0.0),)
    joint_actions = enumerate_joint_actions(snapshot, root)
    assert (MoveAction((0.0, 0.0)),) in joint_actions
    assert (ServeAction(0),) in joint_actions


def test_duplicate_k_event_ids_are_hard_failure() -> None:
    current = _event(0, arrival=0, position=(0.0, 0.0), deadline=3)
    duplicate = _event(0, arrival=1, position=(1.0, 0.0), deadline=3)
    trace = _trace((current,), num_steps=3)
    snapshot = ResourceServiceEnvironment(_config()).reset(trace)

    with pytest.raises(BoundedVerifierError, match="K event_id"):
        bounded_module._freeze_root_information(
            snapshot,
            bounded_module.TrueFutureView(0, 1, (duplicate,)),
        )


def test_duplicate_serve_joint_actions_are_enumerated_in_resource_order() -> None:
    event = _event(0, arrival=0, position=(0.0, 0.0), deadline=2)
    trace = _trace((event,), num_steps=2)
    snapshot = ResourceServiceEnvironment(_config(((0.0, 0.0),) * 2)).reset(trace)
    root = bounded_module._freeze_root_information(
        snapshot,
        build_true_future_view(trace, snapshot, 0),
    )
    joint_actions = enumerate_joint_actions(snapshot, root)

    assert (ServeAction(0), ServeAction(0)) in joint_actions
    assert (ServeAction(0), IdleAction()) in joint_actions
    assert (IdleAction(), ServeAction(0)) in joint_actions
    assert joint_action_key((ServeAction(0), IdleAction())) == ((3, 0), (1,))


def test_serving_resource_has_continue_only() -> None:
    event = _event(0, arrival=0, position=(0.0, 0.0), service=2, deadline=3)
    trace = _trace((event,), num_steps=3)
    environment = ResourceServiceEnvironment(_config())
    environment.reset(trace)
    first = environment.step((ServeAction(0),))
    assert first.next_snapshot is not None
    root = bounded_module._freeze_root_information(
        first.next_snapshot,
        build_true_future_view(trace, first.next_snapshot, 0),
    )

    assert enumerate_joint_actions(first.next_snapshot, root) == ((ContinueAction(),),)


def test_k_outside_task_attributes_do_not_expand_actions() -> None:
    class OutsideEventIdentity:
        event_id = 99

    outside_task = TaskSnapshot(
        event=cast(DemandEvent, OutsideEventIdentity()),
        status=TaskStatus.WAITING,
        assigned_resource_id=None,
        remaining_service=1,
        service_start_step=None,
        completion_time=None,
    )
    snapshot = _snapshot(
        resources=(ResourceSnapshot(0, (0.0, 0.0), ResourceStatus.AVAILABLE, None),),
        tasks=(outside_task,),
    )
    root = bounded_module._FrozenRootInformation((), frozenset(), ())

    assert enumerate_joint_actions(snapshot, root) == ((IdleAction(),),)


def test_search_does_not_refresh_future_view_in_branches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    original = bounded_module.build_true_future_view

    def counted_builder(
        trace: DemandTrace,
        snapshot: EnvironmentSnapshot,
        horizon: int,
    ) -> object:
        nonlocal calls
        calls += 1
        return original(trace, snapshot, horizon)

    monkeypatch.setattr(bounded_module, "build_true_future_view", counted_builder)
    result = run_bounded_verifier(_trace(num_steps=3), _config(), 2)

    assert calls == 3
    assert len(result.root_records) == 3


def test_prefix_replay_snapshot_or_result_mismatch_is_hard_failure() -> None:
    trace = _trace(num_steps=2)
    config = _config()
    environment = ResourceServiceEnvironment(config)
    reset_snapshot = environment.reset(trace)
    first_result = environment.step((IdleAction(),))
    assert first_result.next_snapshot is not None

    wrong_root = replace(first_result.next_snapshot, absolute_step=99)
    wrong_snapshot_replay = bounded_module._make_branch_replayer(
        trace,
        config,
        expected_reset_snapshot=reset_snapshot,
        real_prefix_actions=((IdleAction(),),),
        real_prefix_results=(first_result,),
        expected_root_snapshot=wrong_root,
    )
    with pytest.raises(BoundedVerifierError, match="root snapshot"):
        wrong_snapshot_replay((), ())

    wrong_metrics = replace(
        first_result.step_metrics,
        completed=first_result.step_metrics.completed + 1,
    )
    wrong_result_replay = bounded_module._make_branch_replayer(
        trace,
        config,
        expected_reset_snapshot=reset_snapshot,
        real_prefix_actions=((IdleAction(),),),
        real_prefix_results=(replace(first_result, step_metrics=wrong_metrics),),
        expected_root_snapshot=first_result.next_snapshot,
    )
    with pytest.raises(BoundedVerifierError, match="StepResult"):
        wrong_result_replay((), ())


def test_reset_or_accepted_prefix_errors_propagate(monkeypatch: pytest.MonkeyPatch) -> None:
    class FailingResetEnvironment:
        reset_calls = 0

        def __init__(self, config: ResourceServiceConfig) -> None:
            self._wrapped = ResourceServiceEnvironment(config)

        def reset(self, trace: DemandTrace) -> EnvironmentSnapshot:
            type(self).reset_calls += 1
            if type(self).reset_calls > 1:
                raise ValueError("replay reset failure")
            return self._wrapped.reset(trace)

        def step(self, actions: tuple[ResourceAction, ...]) -> StepResult:
            return self._wrapped.step(actions)

    monkeypatch.setattr(bounded_module, "ResourceServiceEnvironment", FailingResetEnvironment)
    with pytest.raises(ValueError, match="replay reset failure"):
        run_bounded_verifier(_trace(num_steps=1), _config(), 0)


def test_new_candidate_value_error_only_removes_that_child() -> None:
    event = _event(0, arrival=0, position=(1e308, 0.0), deadline=1)
    trace = _trace((event,), num_steps=1)
    config = _config(((-1e308, 0.0),), speed=1.0)

    result = run_bounded_verifier(trace, config, 0)

    assert result.actions == ((IdleAction(),),)
    assert result.episode_metrics.completed == 0


def test_in_service_root_completion_is_counted() -> None:
    event = _event(0, arrival=0, position=(0.0, 0.0), service=2, deadline=2)
    result = run_bounded_verifier(_trace((event,), num_steps=3), _config(), 0)

    assert result.actions[:2] == ((ServeAction(0),), (ContinueAction(),))
    assert result.root_records[1].root_snapshot.active_tasks[0].status is TaskStatus.IN_SERVICE
    assert result.root_records[1].selected_completed_over_k == 1


def test_completions_before_root_are_excluded_from_later_root_score() -> None:
    event = _event(0, arrival=0, position=(0.0, 0.0), deadline=1)
    result = run_bounded_verifier(_trace((event,), num_steps=2), _config(), 0)

    assert result.step_results[0].step_metrics.completed == 1
    assert result.root_records[1].k_event_ids == ()
    assert result.root_records[1].selected_completed_over_k == 0
    assert result.episode_metrics.completed == 1


def test_k_outside_arrival_and_expiration_do_not_inflate_root_score() -> None:
    outside = _event(0, arrival=1, position=(2.0, 0.0), deadline=2)
    result = run_bounded_verifier(_trace((outside,), num_steps=3), _config(), 0)
    first_root = result.root_records[0]

    assert first_root.k_event_ids == ()
    assert first_root.move_targets == ()
    assert first_root.selected_completed_over_k == 0
    assert all(actions == (IdleAction(),) for actions in first_root.selected_sequence)


def test_last_slot_deadline_equal_completion_and_terminal_handling() -> None:
    event = _event(0, arrival=0, position=(0.0, 0.0), deadline=1)
    result = run_bounded_verifier(_trace((event,), num_steps=1), _config(), 0)

    assert result.actions == ((ServeAction(0),),)
    assert result.step_results[0].step_metrics.completed == 1
    assert result.step_results[0].step_metrics.expired == 0
    assert result.step_results[0].is_terminal
    assert result.step_results[0].next_snapshot is None
    assert result.episode_metrics.completed == 1


def test_h_window_upper_boundary_is_included_and_next_step_is_excluded() -> None:
    events = (
        _event(0, arrival=2, position=(0.0, 0.0), deadline=3),
        _event(1, arrival=3, position=(3.0, 0.0), deadline=4),
    )
    result = run_bounded_verifier(
        _trace(events),
        _config(((0.0, 0.0), (0.0, 0.0))),
        2,
    )
    first_root = result.root_records[0]

    assert tuple(event.event_id for event in first_root.official_future_view.future_events) == (0,)
    assert first_root.k_event_ids == (0,)
    assert first_root.move_targets == ((0.0, 0.0),)


def test_repeated_execution_is_deterministic_and_rng_free() -> None:
    numpy_state = np.random.get_state()
    python_state = random.getstate()
    trace, config, horizon = _fixture("F2")

    first = run_bounded_verifier(trace, config, horizon)
    second = run_bounded_verifier(trace, config, horizon)

    assert first == second
    current_numpy_state = np.random.get_state()
    assert current_numpy_state[0] == numpy_state[0]
    np.testing.assert_array_equal(current_numpy_state[1], numpy_state[1])
    assert current_numpy_state[2:] == numpy_state[2:]
    assert random.getstate() == python_state


def test_classifier_uses_only_preregistered_completed_comparison() -> None:
    no_miss = (
        BoundedFixtureComparison(primary_completed=1, verifier_completed=1),
        BoundedFixtureComparison(primary_completed=1, verifier_completed=0),
    )
    miss = (*no_miss, BoundedFixtureComparison(primary_completed=1, verifier_completed=2))

    assert classify_bounded_suite(no_miss) is (
        BoundedDiagnosticLabel.NO_HEURISTIC_MISS_DETECTED_WITHIN_PREREGISTERED_BOUNDED_SUITE
    )
    assert classify_bounded_suite(miss) is BoundedDiagnosticLabel.PRIMARY_HEURISTIC_MISS_DETECTED


def test_verifier_remains_private_to_module() -> None:
    assert "run_bounded_verifier" not in experiments_package.__all__
    assert "BoundedVerifierResult" not in experiments_package.__all__
    assert not hasattr(experiments_package, "run_bounded_verifier")
    assert not hasattr(experiments_package, "BoundedVerifierResult")


def test_environment_access_is_constructor_reset_step_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_environment_type = ResourceServiceEnvironment

    class PublicOnlyEnvironment:
        __slots__ = ("_wrapped",)
        constructions = 0

        def __init__(self, config: ResourceServiceConfig) -> None:
            type(self).constructions += 1
            object.__setattr__(self, "_wrapped", real_environment_type(config))

        def __getattribute__(self, name: str) -> object:
            if name in {
                "reset",
                "step",
                "__class__",
                "constructions",
            }:
                return object.__getattribute__(self, name)
            raise AssertionError(f"verifier 访问了非公共 environment attribute: {name}")

        def reset(self, trace: DemandTrace) -> EnvironmentSnapshot:
            wrapped = object.__getattribute__(self, "_wrapped")
            return wrapped.reset(trace)

        def step(self, actions: tuple[ResourceAction, ...]) -> StepResult:
            wrapped = object.__getattribute__(self, "_wrapped")
            return wrapped.step(actions)

    monkeypatch.setattr(bounded_module, "ResourceServiceEnvironment", PublicOnlyEnvironment)
    result = run_bounded_verifier(_trace(num_steps=2), _config(), 0)

    assert result.episode_metrics.completed == 0
    assert PublicOnlyEnvironment.constructions > 1


def test_k_outside_truncation_does_not_change_empty_root_objective() -> None:
    outside = _event(0, arrival=1, position=(2.0, 0.0), service=2, deadline=4)
    result = run_bounded_verifier(_trace((outside,), num_steps=2), _config(), 0)

    assert result.root_records[0].k_event_ids == ()
    assert result.root_records[0].selected_completed_over_k == 0
    assert result.root_records[0].selected_sequence == ((IdleAction(),), (IdleAction(),))
