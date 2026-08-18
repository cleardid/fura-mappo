from __future__ import annotations

from dataclasses import FrozenInstanceError

import numpy as np
import pytest

from fura_mappo.demand import DemandEvent
from fura_mappo.envs import (
    EnvironmentSnapshot,
    MoveAction,
    ResourceServiceConfig,
    ResourceSnapshot,
    ResourceStatus,
    ServeAction,
    TaskSnapshot,
    TaskStatus,
)


def _event() -> DemandEvent:
    return DemandEvent(0, 0, 0, (1.0, 2.0), 0.5, 1, 2)


def test_config_defensively_normalizes_positions_and_speed() -> None:
    positions = np.array([[0, 1], [2, 3]], dtype=np.int64)
    config = ResourceServiceConfig(positions, np.float64(1.5))  # type: ignore[arg-type]
    positions[:] = 99

    assert config.initial_resource_positions == ((0.0, 1.0), (2.0, 3.0))
    assert config.movement_speed == 1.5
    assert isinstance(config.initial_resource_positions, tuple)


@pytest.mark.parametrize(
    ("positions", "speed", "error_type"),
    [
        ([], 1.0, ValueError),
        ([(0.0,)], 1.0, ValueError),
        ([(0.0, 1.0, 2.0)], 1.0, ValueError),
        ([(True, 0.0)], 1.0, TypeError),
        ([(np.nan, 0.0)], 1.0, ValueError),
        ([(0.0, np.inf)], 1.0, ValueError),
        ([(0.0, 0.0)], True, TypeError),
        ([(0.0, 0.0)], 0.0, ValueError),
        ([(0.0, 0.0)], -1.0, ValueError),
        ([(0.0, 0.0)], np.inf, ValueError),
    ],
)
def test_config_rejects_invalid_values(
    positions: object,
    speed: object,
    error_type: type[Exception],
) -> None:
    with pytest.raises(error_type):
        ResourceServiceConfig(positions, speed)  # type: ignore[arg-type]


def test_config_rejects_non_sequence_and_one_shot_position_inputs() -> None:
    with pytest.raises(TypeError, match="序列"):
        ResourceServiceConfig({"position": (0.0, 0.0)}, 1.0)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="序列"):
        ResourceServiceConfig(((value, value) for value in (0.0,)), 1.0)  # type: ignore[arg-type]


def test_public_real_normalization_converts_float_overflow_to_value_error() -> None:
    huge_real = 10**10000

    with pytest.raises(ValueError, match="有限 Python float"):
        ResourceServiceConfig(((0.0, 0.0),), huge_real)
    with pytest.raises(ValueError, match="有限 Python float"):
        ResourceServiceConfig(((huge_real, 0.0),), 1.0)
    with pytest.raises(ValueError, match="有限 Python float"):
        MoveAction((huge_real, 0.0))


def test_move_and_serve_actions_normalize_defensively() -> None:
    target = np.array([1, 2], dtype=np.int64)
    move = MoveAction(target)  # type: ignore[arg-type]
    serve = ServeAction(np.int64(7))
    target[:] = 99

    assert move.target_position == (1.0, 2.0)
    assert serve.event_id == 7


@pytest.mark.parametrize(
    ("factory", "value", "error_type"),
    [
        (MoveAction, (0.0,), ValueError),
        (MoveAction, (0.0, np.nan), ValueError),
        (MoveAction, (False, 0.0), TypeError),
        (ServeAction, True, TypeError),
        (ServeAction, -1, ValueError),
        (ServeAction, 1.0, TypeError),
    ],
)
def test_actions_reject_invalid_values(
    factory: object,
    value: object,
    error_type: type[Exception],
) -> None:
    with pytest.raises(error_type):
        factory(value)  # type: ignore[operator]


def test_public_snapshots_are_recursively_immutable() -> None:
    event = _event()
    resource = ResourceSnapshot(0, (0.0, 0.0), ResourceStatus.AVAILABLE, None)
    task = TaskSnapshot(event, TaskStatus.WAITING, None, 1, None, None)
    snapshot = EnvironmentSnapshot(0, 1, (resource,), (task,), (event,))

    with pytest.raises(FrozenInstanceError):
        snapshot.absolute_step = 3  # type: ignore[misc]
    with pytest.raises(TypeError):
        snapshot.resources[0] = resource  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        snapshot.active_tasks[0].remaining_service = 0  # type: ignore[misc]
