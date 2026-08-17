from __future__ import annotations

from dataclasses import fields

import numpy as np
import pytest

from fura_mappo.demand.models import DemandEvent, DemandStep, DemandTrace


def _event(
    event_id: int = 0,
    arrival_step: int = 0,
    zone_id: int = 0,
) -> DemandEvent:
    return DemandEvent(
        event_id=event_id,
        arrival_step=arrival_step,
        zone_id=zone_id,
        position=(0.25, 0.75),
        priority=0.5,
        service_time=2,
        deadline=arrival_step + 3,
    )


def test_demand_event_accepts_and_normalizes_valid_numpy_scalars() -> None:
    event = DemandEvent(
        event_id=np.int64(3),
        arrival_step=np.int32(2),
        zone_id=np.int64(1),
        position=(np.float32(0.25), np.int64(1)),
        priority=np.float64(0.75),
        service_time=np.int64(2),
        deadline=np.int64(5),
    )

    assert event == DemandEvent(3, 2, 1, (0.25, 1.0), 0.75, 2, 5)
    assert all(field.name in repr(event) for field in fields(DemandEvent))


@pytest.mark.parametrize(
    ("field_name", "invalid_value", "error_type"),
    [
        ("event_id", True, TypeError),
        ("event_id", -1, ValueError),
        ("event_id", 1.0, TypeError),
        ("arrival_step", False, TypeError),
        ("arrival_step", -1, ValueError),
        ("zone_id", True, TypeError),
        ("zone_id", -1, ValueError),
        ("service_time", True, TypeError),
        ("service_time", 0, ValueError),
        ("deadline", False, TypeError),
        ("deadline", 0, ValueError),
        ("priority", True, TypeError),
        ("priority", -0.01, ValueError),
        ("priority", 1.01, ValueError),
        ("priority", np.nan, ValueError),
        ("priority", np.inf, ValueError),
        ("priority", -np.inf, ValueError),
    ],
)
def test_demand_event_rejects_invalid_scalar_fields(
    field_name: str, invalid_value: object, error_type: type[Exception]
) -> None:
    values: dict[str, object] = {
        "event_id": 0,
        "arrival_step": 0,
        "zone_id": 0,
        "position": (0.25, 0.75),
        "priority": 0.5,
        "service_time": 1,
        "deadline": 1,
    }
    values[field_name] = invalid_value

    with pytest.raises(error_type):
        DemandEvent(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("position", "error_type"),
    [
        ([0.0, 1.0], TypeError),
        ((0.0,), ValueError),
        ((0.0, 1.0, 2.0), ValueError),
        ((np.nan, 0.0), ValueError),
        ((np.inf, 0.0), ValueError),
        ((0.0, -np.inf), ValueError),
        ((True, 0.0), TypeError),
    ],
)
def test_demand_event_rejects_invalid_position(
    position: object, error_type: type[Exception]
) -> None:
    with pytest.raises(error_type):
        DemandEvent(0, 0, 0, position, 0.5, 1, 1)  # type: ignore[arg-type]


def test_demand_event_requires_deadline_after_arrival() -> None:
    with pytest.raises(ValueError, match="晚于"):
        DemandEvent(0, 3, 0, (0.0, 0.0), 0.5, 1, 3)


def test_demand_step_is_consistent_defensive_and_read_only() -> None:
    intensity = np.array([0.5, 1.5], dtype=np.float32)
    counts = np.array([1, 1], dtype=np.int32)
    event_list = [_event(10, 2, 0), _event(11, 2, 1)]

    step = DemandStep(2, intensity, counts, event_list)  # type: ignore[arg-type]
    intensity[:] = 99.0
    counts[:] = 99
    event_list.clear()

    assert step.step == 2
    assert step.intensity.dtype == np.float64
    assert step.counts.dtype == np.int64
    np.testing.assert_array_equal(step.intensity, [0.5, 1.5])
    np.testing.assert_array_equal(step.counts, [1, 1])
    assert len(step.events) == 2
    assert not step.intensity.flags.writeable
    assert not step.counts.flags.writeable
    with pytest.raises(ValueError):
        step.counts[0] = 3

    duplicate = DemandStep(2, [0.5, 1.5], [1, 1], step.events)  # type: ignore[arg-type]
    assert step != duplicate


@pytest.mark.parametrize(
    ("intensity", "counts", "error_type"),
    [
        (1.0, [0], ValueError),
        ([[1.0]], [0], ValueError),
        ([1.0], 0, ValueError),
        ([1.0], [[0]], ValueError),
        ([1.0], [0.0], TypeError),
        ([1.0], [True], TypeError),
        ([1.0], [-1], ValueError),
        ([-1.0], [0], ValueError),
        ([np.nan], [0], ValueError),
        ([np.inf], [0], ValueError),
        ([-np.inf], [0], ValueError),
        ([True], [0], TypeError),
        ([], [], ValueError),
        ([1.0, 2.0], [0], ValueError),
    ],
)
def test_demand_step_rejects_invalid_arrays(
    intensity: object, counts: object, error_type: type[Exception]
) -> None:
    with pytest.raises(error_type):
        DemandStep(0, intensity, counts, ())  # type: ignore[arg-type]


@pytest.mark.parametrize("invalid_step", [True, -1, 1.5])
def test_demand_step_rejects_invalid_step(invalid_step: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        DemandStep(invalid_step, [1.0], [0], ())  # type: ignore[arg-type]


def test_demand_step_rejects_invalid_events_and_inconsistency() -> None:
    with pytest.raises(TypeError, match="DemandEvent"):
        DemandStep(0, [1.0], [1], (object(),))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="arrival_step"):
        DemandStep(0, [1.0], [1], (_event(0, 1, 0),))
    with pytest.raises(ValueError, match="zone_id"):
        DemandStep(0, [1.0], [1], (_event(0, 0, 1),))
    with pytest.raises(ValueError, match="counts"):
        DemandStep(0, [1.0], [0], (_event(),))
    with pytest.raises(ValueError, match="严格递增"):
        DemandStep(0, [1.0], [2], (_event(1), _event(1)))


@pytest.mark.parametrize("boolean", [True, np.bool_(True)])
def test_demand_step_rejects_boolean_mixed_into_numeric_arrays(boolean: object) -> None:
    with pytest.raises(TypeError, match="布尔"):
        DemandStep(0, [1.0, boolean], [0, 0], ())  # type: ignore[list-item]

    matching_event = _event(0, 0, 1)
    with pytest.raises(TypeError, match="布尔"):
        DemandStep(
            0,
            [1.0, 1.0],
            [0, boolean],  # type: ignore[list-item]
            (matching_event,),
        )


def test_demand_trace_is_consistent_defensive_and_read_only() -> None:
    counts = np.array([[1, 0], [0, 1]], dtype=np.int32)
    intensities = np.array([[0.5, 1.0], [0.5, 1.0]], dtype=np.float32)
    event_list = [_event(4, 3, 0), _event(5, 4, 1)]

    trace = DemandTrace(3, counts, intensities, event_list)  # type: ignore[arg-type]
    counts[:] = 9
    intensities[:] = 9.0
    event_list.clear()

    assert trace.start_step == 3
    assert trace.counts.dtype == np.int64
    assert trace.intensities.dtype == np.float64
    np.testing.assert_array_equal(trace.counts, [[1, 0], [0, 1]])
    np.testing.assert_array_equal(trace.intensities, [[0.5, 1.0], [0.5, 1.0]])
    assert len(trace.events) == 2
    assert not trace.counts.flags.writeable
    assert not trace.intensities.flags.writeable
    with pytest.raises(ValueError):
        trace.intensities[0, 0] = 5.0

    duplicate = DemandTrace(3, [[1, 0], [0, 1]], [[0.5, 1.0]] * 2, trace.events)  # type: ignore[arg-type]
    assert trace != duplicate


@pytest.mark.parametrize(
    ("counts", "intensities", "error_type"),
    [
        ([0], [[1.0]], ValueError),
        ([[0]], [1.0], ValueError),
        ([[0.0]], [[1.0]], TypeError),
        ([[-1]], [[1.0]], ValueError),
        ([[0]], [[-1.0]], ValueError),
        ([[0]], [[np.nan]], ValueError),
        ([[0]], [[np.inf]], ValueError),
        (np.empty((0, 1), dtype=int), np.empty((0, 1)), ValueError),
        (np.empty((1, 0), dtype=int), np.empty((1, 0)), ValueError),
        ([[0, 0]], [[1.0]], ValueError),
    ],
)
def test_demand_trace_rejects_invalid_arrays(
    counts: object, intensities: object, error_type: type[Exception]
) -> None:
    with pytest.raises(error_type):
        DemandTrace(0, counts, intensities, ())  # type: ignore[arg-type]


@pytest.mark.parametrize("invalid_start", [True, -1, 0.5])
def test_demand_trace_rejects_invalid_start_step(invalid_start: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        DemandTrace(invalid_start, [[0]], [[1.0]], ())  # type: ignore[arg-type]


def test_demand_trace_rejects_invalid_events_and_inconsistency() -> None:
    with pytest.raises(TypeError, match="DemandEvent"):
        DemandTrace(0, [[1]], [[1.0]], (object(),))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="时间范围"):
        DemandTrace(2, [[1]], [[1.0]], (_event(0, 3, 0),))
    with pytest.raises(ValueError, match="zone_id"):
        DemandTrace(0, [[1]], [[1.0]], (_event(0, 0, 1),))
    with pytest.raises(ValueError, match="counts"):
        DemandTrace(0, [[0]], [[1.0]], (_event(),))
    with pytest.raises(ValueError, match="严格递增"):
        DemandTrace(0, [[2]], [[1.0]], (_event(1), _event(0)))


@pytest.mark.parametrize("boolean", [True, np.bool_(True)])
def test_demand_trace_rejects_boolean_mixed_into_numeric_arrays(boolean: object) -> None:
    with pytest.raises(TypeError, match="布尔"):
        DemandTrace(
            0,
            [[0, 0]],
            [[1.0, boolean]],  # type: ignore[list-item]
            (),
        )

    matching_event = _event(0, 0, 1)
    with pytest.raises(TypeError, match="布尔"):
        DemandTrace(
            0,
            [[0, boolean]],  # type: ignore[list-item]
            [[1.0, 1.0]],
            (matching_event,),
        )
