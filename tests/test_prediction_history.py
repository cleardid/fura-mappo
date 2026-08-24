from __future__ import annotations

import inspect

import numpy as np
import pytest

from fura_mappo.demand import DemandEvent, DemandTrace
from fura_mappo.envs import IdleAction, ResourceServiceConfig, ResourceServiceEnvironment
from fura_mappo.prediction import (
    DatasetProtocolSpec,
    ObservedDemandHistory,
    ZoneSchema,
    derive_prediction_context,
)


def _trace() -> DemandTrace:
    events = (
        DemandEvent(0, 0, 0, (0.5, 0.5), 0.5, 1, 2),
        DemandEvent(1, 1, 1, (1.5, 0.5), 0.5, 1, 3),
        DemandEvent(2, 1, 1, (1.5, 0.5), 0.5, 1, 3),
        DemandEvent(3, 3, 0, (0.5, 0.5), 0.5, 1, 4),
    )
    return DemandTrace(
        0,
        [[1, 0], [0, 2], [0, 0], [1, 0]],
        np.full((4, 2), 99.0),
        events,
    )


def _zone_schema() -> ZoneSchema:
    return ZoneSchema([[0.0, 1.0, 0.0, 1.0], [1.0, 2.0, 0.0, 1.0]])


def test_online_history_matches_offline_context_at_every_decision_boundary() -> None:
    trace = _trace()
    schema = _zone_schema()
    spec = DatasetProtocolSpec(3, 2, schema.sha256)
    history = ObservedDemandHistory(schema, 3, 2)
    environment = ResourceServiceEnvironment(ResourceServiceConfig(((0.0, 0.0),), 1.0))
    snapshot = environment.reset(trace)

    while True:
        online = history.observe(snapshot)
        offline = derive_prediction_context(trace, spec, snapshot.absolute_step)
        np.testing.assert_array_equal(online.history_counts, offline.history_counts)
        np.testing.assert_array_equal(online.history_mask, offline.history_mask)
        assert online.absolute_step == offline.absolute_step
        assert online.steps_remaining == offline.steps_remaining
        result = environment.step((IdleAction(),))
        if result.next_snapshot is None:
            break
        snapshot = result.next_snapshot


def test_online_history_includes_current_arrivals_and_distinguishes_zero() -> None:
    trace = _trace()
    environment = ResourceServiceEnvironment(ResourceServiceConfig(((0.0, 0.0),), 1.0))
    snapshot = environment.reset(trace)
    history = ObservedDemandHistory(_zone_schema(), 2, 1)

    at_zero = history.observe(snapshot)
    np.testing.assert_array_equal(at_zero.history_counts, [[0, 0], [1, 0]])
    np.testing.assert_array_equal(at_zero.history_mask, [False, True])
    snapshot = environment.step((IdleAction(),)).next_snapshot
    assert snapshot is not None
    at_one = history.observe(snapshot)
    np.testing.assert_array_equal(at_one.history_counts, [[1, 0], [0, 2]])
    np.testing.assert_array_equal(at_one.history_mask, [True, True])
    snapshot = environment.step((IdleAction(),)).next_snapshot
    assert snapshot is not None
    at_two = history.observe(snapshot)
    np.testing.assert_array_equal(at_two.history_counts, [[0, 2], [0, 0]])
    np.testing.assert_array_equal(at_two.history_mask, [True, True])


def test_online_history_rejects_noncontiguous_or_cross_episode_snapshots_transactionally() -> None:
    trace = _trace()
    environment = ResourceServiceEnvironment(ResourceServiceConfig(((0.0, 0.0),), 1.0))
    first = environment.reset(trace)
    second = environment.step((IdleAction(),)).next_snapshot
    assert second is not None
    history = ObservedDemandHistory(_zone_schema(), 2, 1)
    baseline = history.observe(first)

    with pytest.raises(ValueError, match="连续"):
        history.observe(first)
    after_failure = history.observe(second)
    np.testing.assert_array_equal(after_failure.history_counts[-2], baseline.history_counts[-1])

    history.reset()
    restarted = history.observe(first)
    np.testing.assert_array_equal(restarted.history_counts, baseline.history_counts)


def test_online_component_has_no_demand_trace_input_or_retained_future_source() -> None:
    signature = inspect.signature(ObservedDemandHistory.observe)
    assert tuple(signature.parameters) == ("self", "snapshot")
    history = ObservedDemandHistory(_zone_schema(), 2, 1)
    assert not hasattr(history, "trace")
    assert not hasattr(history, "source")
    assert not hasattr(history, "intensities")


def test_online_history_validates_zone_and_arrival_boundary() -> None:
    from fura_mappo.envs import EnvironmentSnapshot

    history = ObservedDemandHistory(_zone_schema(), 2, 1)
    wrong_step = DemandEvent(0, 1, 0, (0.5, 0.5), 0.5, 1, 2)
    snapshot = EnvironmentSnapshot(0, 2, (), (), (wrong_step,))
    with pytest.raises(ValueError, match="arrival_step"):
        history.observe(snapshot)

    wrong_zone = DemandEvent(1, 0, 2, (2.5, 0.5), 0.5, 1, 2)
    snapshot = EnvironmentSnapshot(0, 2, (), (), (wrong_zone,))
    with pytest.raises(ValueError, match="zone_id"):
        history.observe(snapshot)
